from __future__ import annotations

import hashlib
import html
import json
import os
import re
import sys
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from bs4 import BeautifulSoup
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config.json"
JOBS_PATH = ROOT / "jobs.json"
STATUS_PATH = ROOT / "scan_status.json"
USER_AGENT = "OlhaJobAgent/1.0 (personal job-feed reader)"


@dataclass
class Job:
    id: str
    source: str
    title: str
    link: str
    description: str
    published: str
    scanned_at: str
    language_hint: str
    budget_text: str
    score: int
    risk: str
    matched_keywords: list[str]
    risk_keywords: list[str]
    status: str = "new"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return default


def atomic_write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, dir=path.parent) as tmp:
        json.dump(data, tmp, ensure_ascii=False, indent=2)
        tmp.write("\n")
        temp_name = tmp.name
    os.replace(temp_name, path)


def clean_html(value: str | None) -> str:
    if not value:
        return ""
    soup = BeautifulSoup(html.unescape(value), "html.parser")
    text = soup.get_text(" ", strip=True)
    return re.sub(r"\s+", " ", text).strip()


def stable_id(source: str, link: str, title: str) -> str:
    return hashlib.sha256(f"{source}|{link}|{title}".encode("utf-8")).hexdigest()[:20]


def detect_language(text: str) -> str:
    lowered = f" {text.lower()} "
    if re.search(r"[іїєґ]", lowered):
        return "uk"
    if re.search(r"[а-яё]", lowered):
        return "ru"
    if any(ch in lowered for ch in "äöüß") or any(
        marker in lowered
        for marker in (" der ", " die ", " das ", " und ", " für ", " mit ", " gesucht ", " bewerbung ")
    ):
        return "de"
    return "en"


def extract_budget(text: str) -> str:
    patterns = [
        r"(?:€|EUR\s?)(\d{1,6}(?:[.,]\d{1,2})?)",
        r"(\d{1,6}(?:[.,]\d{1,2})?)\s?(?:€|EUR)\b",
        r"(?:\$|USD\s?)(\d{1,6}(?:[.,]\d{1,2})?)",
        r"(\d{1,6}(?:[.,]\d{1,2})?)\s?(?:USD|\$)\b",
        r"(?:budget|pay|payment|rate|compensation)\s*(?:is|:|-)?\s*([€$]?\s?\d{1,6}(?:[.,]\d{1,2})?)",
    ]
    hits: list[str] = []
    for pattern in patterns:
        for match in re.finditer(pattern, text, flags=re.I):
            value = match.group(0).strip()
            if value and value not in hits:
                hits.append(value)
    return ", ".join(hits[:3]) if hits else "not stated"


def score_job(title: str, description: str, config: dict[str, Any]) -> tuple[int, list[str], list[str], str]:
    text = f" {title} {description} ".lower()
    scanner_cfg = config.get("scanner", {})
    keywords = [str(item).lower() for item in scanner_cfg.get("keywords", [])]
    negatives = [str(item).lower() for item in scanner_cfg.get("negative_keywords", [])]

    matched = sorted({keyword for keyword in keywords if keyword in text})
    risks = sorted({keyword for keyword in negatives if keyword in text})

    score = min(65, len(matched) * 8)
    if any(marker in text for marker in (" hiring ", " need ", " looking for ", " seeking ", " gesucht ")):
        score += 12
    if extract_budget(text) != "not stated":
        score += 12
    if any(marker in text for marker in (" today ", " urgent ", " asap ", " immediately ", " heute ")):
        score += 6
    score -= min(60, len(risks) * 25)
    score = max(0, min(100, score))
    risk = "high" if len(risks) >= 2 else "medium" if risks else "low"
    return score, matched, risks, risk


def _parse_date(value: str) -> str:
    if not value:
        return utc_now_iso()
    try:
        parsed = parsedate_to_datetime(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).replace(microsecond=0).isoformat()
    except Exception:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc).replace(microsecond=0).isoformat()
        except Exception:
            return utc_now_iso()


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _first_child_text(node: ET.Element, names: tuple[str, ...]) -> str:
    for child in list(node):
        if _local_name(child.tag) in names:
            return "".join(child.itertext()).strip()
    return ""


def _entry_link(node: ET.Element) -> str:
    for child in list(node):
        if _local_name(child.tag) != "link":
            continue
        href = child.attrib.get("href", "").strip()
        rel = child.attrib.get("rel", "alternate")
        if href and rel in ("alternate", ""):
            return href
        text = (child.text or "").strip()
        if text:
            return text
    return ""


def parse_xml_feed(content: bytes) -> list[dict[str, str]]:
    root = ET.fromstring(content)
    root_name = _local_name(root.tag)
    if root_name == "rss":
        channel = next((child for child in list(root) if _local_name(child.tag) == "channel"), root)
        nodes = [child for child in list(channel) if _local_name(child.tag) == "item"]
    elif root_name == "feed":
        nodes = [child for child in list(root) if _local_name(child.tag) == "entry"]
    else:
        nodes = [node for node in root.iter() if _local_name(node.tag) in ("item", "entry")]

    items: list[dict[str, str]] = []
    for node in nodes:
        title = _first_child_text(node, ("title",)) or "Untitled"
        description = _first_child_text(node, ("summary", "description", "content"))
        published_raw = _first_child_text(node, ("published", "updated", "pubdate", "date"))
        items.append({
            "title": clean_html(title),
            "link": _entry_link(node),
            "description": clean_html(description)[:8000],
            "published": _parse_date(published_raw),
        })
    return items


def request_json(url: str) -> Any:
    response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
    response.raise_for_status()
    return response.json()


def request_feed(url: str) -> list[dict[str, str]]:
    response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
    response.raise_for_status()
    return parse_xml_feed(response.content)


def normalize_rss(source: str, url: str, limit: int) -> list[dict[str, str]]:
    parsed_items = request_feed(url)
    items: list[dict[str, str]] = []
    for entry in parsed_items[:limit]:
        items.append({
            "source": source,
            "title": entry.get("title", "Untitled"),
            "link": entry.get("link", ""),
            "description": entry.get("description", "")[:8000],
            "published": entry.get("published", utc_now_iso()),
        })
    return items


def normalize_remoteok(source: str, url: str, limit: int) -> list[dict[str, str]]:
    data = request_json(url)
    if not isinstance(data, list):
        raise RuntimeError("RemoteOK response is not a list")
    items: list[dict[str, str]] = []
    for row in data:
        if not isinstance(row, dict) or not row.get("position"):
            continue
        title = str(row.get("position", "Untitled"))
        company = str(row.get("company", "")).strip()
        tags = ", ".join(str(tag) for tag in row.get("tags", []) if tag)
        description = clean_html(str(row.get("description", "")))
        extra = " · ".join(part for part in (company, tags) if part)
        if extra:
            description = f"{extra}. {description}".strip()
        epoch = row.get("epoch")
        if isinstance(epoch, (int, float)):
            published = datetime.fromtimestamp(epoch, tz=timezone.utc).replace(microsecond=0).isoformat()
        else:
            published = str(row.get("date", "")) or utc_now_iso()
        link = str(row.get("url", "") or row.get("apply_url", "")).strip()
        items.append(
            {
                "source": source,
                "title": title,
                "link": link,
                "description": description[:8000],
                "published": published,
            }
        )
        if len(items) >= limit:
            break
    return items


def fetch_source(source_cfg: dict[str, Any], limit: int) -> list[dict[str, str]]:
    source = str(source_cfg.get("name", "Unnamed source"))
    url = str(source_cfg.get("url", "")).strip()
    source_type = str(source_cfg.get("type", "rss")).lower()
    if not url:
        return []
    if source_type == "remoteok_json":
        return normalize_remoteok(source, url, limit)
    return normalize_rss(source, url, limit)


def scan(config_path: Path = CONFIG_PATH, jobs_path: Path = JOBS_PATH, status_path: Path = STATUS_PATH) -> dict[str, Any]:
    config = load_json(config_path, {})
    old_jobs = load_json(jobs_path, [])
    if not isinstance(old_jobs, list):
        old_jobs = []
    existing = {
        str(job.get("id")): job
        for job in old_jobs
        if isinstance(job, dict) and job.get("id")
    }

    errors: list[str] = []
    added_jobs: list[dict[str, Any]] = []
    enabled_sources = 0
    limit = int(config.get("scanner", {}).get("max_items_per_source", 50))
    minimum_score = int(config.get("scanner", {}).get("minimum_score", 20))

    for source_cfg in config.get("sources", []):
        if not source_cfg.get("enabled"):
            continue
        enabled_sources += 1
        source_name = str(source_cfg.get("name", "Unnamed source"))
        try:
            for item in fetch_source(source_cfg, limit):
                title = item.get("title", "Untitled")
                link = item.get("link", "")
                description = item.get("description", "")
                job_id = stable_id(source_name, link, title)
                if job_id in existing:
                    continue
                score, matched, risks, risk = score_job(title, description, config)
                if score < minimum_score:
                    continue
                job = asdict(
                    Job(
                        id=job_id,
                        source=source_name,
                        title=title,
                        link=link,
                        description=description,
                        published=item.get("published", utc_now_iso()),
                        scanned_at=utc_now_iso(),
                        language_hint=detect_language(f"{title} {description}"),
                        budget_text=extract_budget(f"{title} {description}"),
                        score=score,
                        risk=risk,
                        matched_keywords=matched,
                        risk_keywords=risks,
                    )
                )
                existing[job_id] = job
                added_jobs.append(job)
        except Exception as exc:
            errors.append(f"{source_name}: {type(exc).__name__}: {exc}")

    jobs = list(existing.values())
    jobs.sort(key=lambda job: (int(job.get("score", 0)), str(job.get("published", ""))), reverse=True)
    keep = int(config.get("scanner", {}).get("keep_latest_jobs", 500))
    jobs = jobs[:keep]
    atomic_write_json(jobs_path, jobs)

    result = {
        "ok": enabled_sources > 0,
        "enabled_sources": enabled_sources,
        "added": len(added_jobs),
        "total": len(jobs),
        "errors": errors,
        "finished_at": utc_now_iso(),
    }
    atomic_write_json(status_path, result)
    print(json.dumps(result, ensure_ascii=False))
    maybe_notify_telegram(result, added_jobs[:5])
    return result


def maybe_notify_telegram(result: dict[str, Any], newest: list[dict[str, Any]]) -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id or not newest:
        return
    lines = [f"🔎 Новых подходящих заказов: {result['added']}"]
    for job in newest:
        lines.append(f"• {job.get('score', 0)}/100 — {job.get('title', '')[:100]}\n{job.get('link', '')}")
    try:
        response = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": "\n\n".join(lines), "disable_web_page_preview": True},
            timeout=20,
        )
        response.raise_for_status()
    except Exception as exc:
        print(f"Telegram notification failed: {exc}", file=sys.stderr)


if __name__ == "__main__":
    scan()
