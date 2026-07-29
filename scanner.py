from __future__ import annotations

import hashlib
import html
import json
import re
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config.json"
JOBS_PATH = ROOT / "jobs.json"
STATUS_PATH = ROOT / "scan_status.json"

USER_AGENT = (
    "JobAgent/2.0 "
    "(personal job search assistant; contact through repository owner)"
)

DEFAULT_TIMEOUT = 25
MAX_DESCRIPTION_LENGTH = 12_000


SIMPLE_KEYWORDS = [
    # English
    "translation",
    "translate",
    "translator",
    "proofreading",
    "proofreader",
    "proofread",
    "transcription",
    "transcribe",
    "data entry",
    "copy paste",
    "copy-paste",
    "typing",
    "retyping",
    "subtitle",
    "subtitles",
    "captioning",
    "text editing",
    "text correction",
    "document formatting",
    "pdf to word",
    "image to text",
    "audio to text",
    "web research",
    "internet research",
    "virtual assistant",
    "product description",
    "short description",
    "email writing",
    "content moderation",
    "content review",
    "localization",

    # German
    "übersetzung",
    "übersetzen",
    "übersetzer",
    "korrekturlesen",
    "korrektur",
    "transkription",
    "dateneingabe",
    "daten eingeben",
    "abschreiben",
    "untertitel",
    "texterfassung",
    "textbearbeitung",
    "produktbeschreibung",
    "internetrecherche",
    "virtuelle assistenz",
    "lokalisierung",

    # Russian
    "перевод",
    "перевести",
    "переводчик",
    "проверка текста",
    "редактирование текста",
    "расшифровка",
    "транскрибация",
    "набор текста",
    "ввод данных",
    "копирование данных",
    "субтитры",
    "описание товара",
    "поиск информации",
    "виртуальный помощник",

    # Ukrainian
    "переклад",
    "перекласти",
    "перекладач",
    "перевірка тексту",
    "редагування тексту",
    "розшифровка",
    "транскрипція",
    "набір тексту",
    "введення даних",
    "копіювання даних",
    "субтитри",
    "опис товару",
    "пошук інформації",
    "віртуальний помічник",
]


TRANSLATION_KEYWORDS = [
    "translation",
    "translate",
    "translator",
    "localization",
    "proofreading",
    "proofreader",
    "übersetzung",
    "übersetzen",
    "übersetzer",
    "korrekturlesen",
    "перевод",
    "перевести",
    "переводчик",
    "переклад",
    "перекласти",
    "перекладач",
]


COMPLEX_KEYWORDS = [
    "senior developer",
    "senior engineer",
    "lead developer",
    "full stack",
    "full-stack",
    "backend developer",
    "frontend developer",
    "mobile developer",
    "machine learning",
    "artificial intelligence engineer",
    "blockchain",
    "devops",
    "cybersecurity",
    "penetration testing",
    "architect",
    "3d animation",
    "3d modeling",
    "legal advice",
    "medical diagnosis",
    "licensed professional",
    "five years experience",
    "5+ years",
    "senior entwickler",
]


RISK_KEYWORDS = [
    "telegram only",
    "contact on telegram",
    "whatsapp only",
    "gift card",
    "gift cards",
    "crypto payment",
    "cryptocurrency payment",
    "pay a fee",
    "registration fee",
    "security deposit",
    "send money first",
    "purchase equipment",
    "bank account access",
    "bank login",
    "identity verification payment",
    "outside the platform",
    "payment outside",
    "western union",
    "moneygram",
    "easy money",
    "guaranteed income",
    "urgent investment",
    "внесите залог",
    "оплатите комиссию",
    "купите подарочную карту",
    "оплата криптовалютой",
    "доступ к банковскому счёту",
    "перейдите в telegram",
    "только telegram",
    "предоплата исполнителем",
]


CURRENCY_PATTERN = re.compile(
    r"""
    (?:
        (?P<symbol>[$€£])\s*
        (?P<amount1>\d{1,7}(?:[.,]\d{1,2})?)
        (?:\s*(?:-|–|—|to|до)\s*
        (?P<amount2>\d{1,7}(?:[.,]\d{1,2})?))?
    )
    |
    (?:
        (?P<amount3>\d{1,7}(?:[.,]\d{1,2})?)
        (?:\s*(?:-|–|—|to|до)\s*
        (?P<amount4>\d{1,7}(?:[.,]\d{1,2})?))?
        \s*(?P<code>USD|EUR|GBP|доллар(?:ов|а)?|евро)
    )
    """,
    flags=re.I | re.X,
)


def utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
    )


def load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def save_json(path: Path, data: Any) -> None:
    temporary_path = path.with_suffix(path.suffix + ".tmp")

    temporary_path.write_text(
        json.dumps(
            data,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    temporary_path.replace(path)


def get_config() -> dict[str, Any]:
    data = load_json(CONFIG_PATH, {})

    if isinstance(data, dict):
        return data

    return {}


def stable_id(source: str, link: str, title: str) -> str:
    raw_value = f"{source}|{link}|{title}".strip().lower()

    return hashlib.sha256(
        raw_value.encode("utf-8")
    ).hexdigest()[:20]


def normalize_spaces(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def strip_html(value: str) -> str:
    if not value:
        return ""

    value = html.unescape(value)

    value = re.sub(
        r"<(?:br|p|div|li|h[1-6])[^>]*>",
        "\n",
        value,
        flags=re.I,
    )

    value = re.sub(r"<[^>]+>", " ", value)
    value = html.unescape(value)

    lines = [
        normalize_spaces(line)
        for line in value.splitlines()
    ]

    cleaned = "\n".join(
        line for line in lines if line
    )

    return cleaned[:MAX_DESCRIPTION_LENGTH]


def detect_language(text: str) -> str:
    lowered = text.lower()

    if re.search(r"[іїєґ]", lowered):
        return "uk"

    if re.search(r"[а-яё]", lowered):
        return "ru"

    german_markers = [
        " der ",
        " die ",
        " das ",
        " und ",
        " mit ",
        " für ",
        " aufgabe",
        "übersetzung",
        "deutsch",
        "kenntnisse",
    ]

    padded = f" {lowered} "

    german_score = sum(
        marker in padded
        for marker in german_markers
    )

    if german_score >= 2 or re.search(
        r"[äöüß]",
        lowered,
    ):
        return "de"

    return "en"


def extract_budget(text: str) -> str:
    match = CURRENCY_PATTERN.search(text or "")

    if not match:
        return "not stated"

    symbol = match.group("symbol")
    code = match.group("code")

    amount1 = (
        match.group("amount1")
        or match.group("amount3")
    )

    amount2 = (
        match.group("amount2")
        or match.group("amount4")
    )

    amount1 = amount1.replace(",", ".")

    if amount2:
        amount2 = amount2.replace(",", ".")

    if symbol:
        currency = symbol
    else:
        normalized_code = str(code).upper()

        if normalized_code == "USD" or "ДОЛЛАР" in normalized_code:
            currency = "$"
        elif normalized_code == "GBP":
            currency = "£"
        else:
            currency = "€"

    if amount2:
        return f"{currency}{amount1}–{currency}{amount2}"

    return f"{currency}{amount1}"


def get_budget_values(text: str) -> list[float]:
    match = CURRENCY_PATTERN.search(text or "")

    if not match:
        return []

    raw_values = [
        match.group("amount1") or match.group("amount3"),
        match.group("amount2") or match.group("amount4"),
    ]

    values: list[float] = []

    for raw_value in raw_values:
        if not raw_value:
            continue

        try:
            values.append(
                float(raw_value.replace(",", "."))
            )
        except ValueError:
            continue

    return values


def contains_any(
    text: str,
    keywords: list[str],
) -> list[str]:
    lowered = text.lower()

    return [
        keyword
        for keyword in keywords
        if keyword.lower() in lowered
    ]


def classify_task(text: str) -> str:
    lowered = text.lower()

    if any(
        keyword in lowered
        for keyword in TRANSLATION_KEYWORDS
    ):
        return "translation"

    if any(
        keyword in lowered
        for keyword in [
            "transcription",
            "transcribe",
            "транскрибация",
            "расшифровка",
            "transkription",
            "транскрипція",
        ]
    ):
        return "transcription"

    if any(
        keyword in lowered
        for keyword in [
            "data entry",
            "dateneingabe",
            "ввод данных",
            "введення даних",
            "copy paste",
        ]
    ):
        return "data_entry"

    if any(
        keyword in lowered
        for keyword in [
            "proofreading",
            "proofreader",
            "korrekturlesen",
            "проверка текста",
            "перевірка тексту",
        ]
    ):
        return "proofreading"

    if any(
        keyword in lowered
        for keyword in [
            "virtual assistant",
            "virtuelle assistenz",
            "виртуальный помощник",
            "віртуальний помічник",
        ]
    ):
        return "virtual_assistant"

    if any(
        keyword in lowered
        for keyword in [
            "writing",
            "copywriting",
            "product description",
            "text editing",
            "описание товара",
            "опис товару",
        ]
    ):
        return "writing"

    return "other"


def score_job(
    title: str,
    description: str,
    config: dict[str, Any],
) -> tuple[int, list[str], list[str], str]:
    full_text = normalize_spaces(
        f"{title} {description}"
    ).lower()

    configured_keywords = config.get(
        "search_keywords",
        [],
    )

    if not isinstance(configured_keywords, list):
        configured_keywords = []

    positive_keywords = list(
        dict.fromkeys(
            SIMPLE_KEYWORDS
            + [
                str(item).lower()
                for item in configured_keywords
                if str(item).strip()
            ]
        )
    )

    matched = contains_any(
        full_text,
        positive_keywords,
    )

    complex_matches = contains_any(
        full_text,
        COMPLEX_KEYWORDS,
    )

    risks = contains_any(
        full_text,
        RISK_KEYWORDS,
    )

    score = 20

    score += min(len(matched) * 9, 45)
    score -= min(len(complex_matches) * 12, 40)
    score -= min(len(risks) * 18, 60)

    task_type = classify_task(full_text)

    if task_type == "translation":
        score += 20
    elif task_type in {
        "transcription",
        "data_entry",
        "proofreading",
    }:
        score += 15
    elif task_type in {
        "virtual_assistant",
        "writing",
    }:
        score += 8

    budget_values = get_budget_values(full_text)

    if budget_values:
        minimum_budget = min(budget_values)
        maximum_budget = max(budget_values)

        if maximum_budget >= 5 and minimum_budget <= 50:
            score += 15
        elif minimum_budget > 200:
            score -= 5

    if len(description) < 3500:
        score += 5

    score = max(0, min(100, score))

    if risks:
        risk = "high" if len(risks) >= 2 else "medium"
    elif complex_matches:
        risk = "medium"
    else:
        risk = "low"

    return score, matched, risks, risk


def http_get(
    url: str,
    *,
    accept: str,
    timeout: int = DEFAULT_TIMEOUT,
) -> bytes:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": accept,
        },
    )

    with urllib.request.urlopen(
        request,
        timeout=timeout,
    ) as response:
        return response.read()


def make_job(
    *,
    source: str,
    title: str,
    link: str,
    description: str,
    published: str,
    company: str = "",
    location: str = "",
    category: str = "",
    salary: str = "",
    config: dict[str, Any],
) -> dict[str, Any]:
    cleaned_title = normalize_spaces(
        strip_html(title)
    )

    cleaned_description = strip_html(description)

    combined_text = (
        f"{cleaned_title}\n"
        f"{cleaned_description}\n"
        f"{salary}"
    )

    score, matched, risks, risk = score_job(
        cleaned_title,
        combined_text,
        config,
    )

    budget_text = extract_budget(
        f"{salary} {combined_text}"
    )

    return {
        "id": stable_id(
            source,
            link,
            cleaned_title,
        ),
        "source": source,
        "title": cleaned_title or "Без названия",
        "link": link.strip(),
        "description": cleaned_description,
        "published": published or "",
        "scanned_at": utc_now(),
        "company": normalize_spaces(company),
        "location": normalize_spaces(location),
        "category": normalize_spaces(category),
        "language_hint": detect_language(
            combined_text
        ),
        "budget_text": budget_text,
        "score": score,
        "risk": risk,
        "task_type": classify_task(
            combined_text
        ),
        "is_simple": bool(matched),
        "matched_keywords": matched[:30],
        "risk_keywords": risks[:20],
        "status": "new",
    }


def fetch_remotive(
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    url = "https://remotive.com/api/remote-jobs"

    raw_data = http_get(
        url,
        accept="application/json",
    )

    payload = json.loads(
        raw_data.decode("utf-8")
    )

    source_jobs = payload.get("jobs", [])

    if not isinstance(source_jobs, list):
        return []

    jobs: list[dict[str, Any]] = []

    for item in source_jobs:
        if not isinstance(item, dict):
            continue

        salary = str(item.get("salary", ""))

        jobs.append(
            make_job(
                source="Remotive",
                title=str(
                    item.get("title", "")
                ),
                link=str(
                    item.get("url", "")
                ),
                description=str(
                    item.get("description", "")
                ),
                published=str(
                    item.get(
                        "publication_date",
                        "",
                    )
                ),
                company=str(
                    item.get(
                        "company_name",
                        "",
                    )
                ),
                location=str(
                    item.get(
                        "candidate_required_location",
                        "",
                    )
                ),
                category=str(
                    item.get(
                        "category",
                        "",
                    )
                ),
                salary=salary,
                config=config,
            )
        )

    return jobs


def fetch_remote_ok(
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    url = "https://remoteok.com/api"

    raw_data = http_get(
        url,
        accept="application/json",
    )

    payload = json.loads(
        raw_data.decode("utf-8")
    )

    if not isinstance(payload, list):
        return []

    jobs: list[dict[str, Any]] = []

    for item in payload:
        if not isinstance(item, dict):
            continue

        # Первый элемент API может содержать юридическую информацию,
        # а не вакансию.
        if not item.get("position"):
            continue

        tags = item.get("tags", [])

        if isinstance(tags, list):
            category = ", ".join(
                str(tag) for tag in tags
            )
        else:
            category = str(tags)

        salary_min = item.get("salary_min")
        salary_max = item.get("salary_max")

        salary_parts: list[str] = []

        if salary_min:
            salary_parts.append(str(salary_min))

        if salary_max:
            salary_parts.append(str(salary_max))

        salary = ""

        if salary_parts:
            salary = "$" + "–$".join(
                salary_parts
            )

        jobs.append(
            make_job(
                source="Remote OK",
                title=str(
                    item.get("position", "")
                ),
                link=str(
                    item.get("url", "")
                ),
                description=str(
                    item.get("description", "")
                ),
                published=str(
                    item.get(
                        "date",
                        item.get("epoch", ""),
                    )
                ),
                company=str(
                    item.get("company", "")
                ),
                location=str(
                    item.get("location", "")
                ),
                category=category,
                salary=salary,
                config=config,
            )
        )

    return jobs


def get_xml_text(
    element: ET.Element,
    names: list[str],
) -> str:
    for child in element.iter():
        local_name = child.tag.split("}")[-1]

        if local_name in names and child.text:
            return child.text.strip()

    return ""


def fetch_we_work_remotely(
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    url = "https://weworkremotely.com/remote-jobs.rss"

    raw_data = http_get(
        url,
        accept=(
            "application/rss+xml, "
            "application/xml, "
            "text/xml"
        ),
    )

    root = ET.fromstring(raw_data)

    jobs: list[dict[str, Any]] = []

    for item in root.iter():
        if item.tag.split("}")[-1] != "item":
            continue

        title = get_xml_text(
            item,
            ["title"],
        )

        link = get_xml_text(
            item,
            ["link"],
        )

        description = get_xml_text(
            item,
            [
                "description",
                "encoded",
                "content",
            ],
        )

        published = get_xml_text(
            item,
            [
                "pubDate",
                "published",
                "date",
            ],
        )

        category = get_xml_text(
            item,
            ["category"],
        )

        jobs.append(
            make_job(
                source="We Work Remotely",
                title=title,
                link=link,
                description=description,
                published=published,
                category=category,
                config=config,
            )
        )

    return jobs


def source_enabled(
    config: dict[str, Any],
    source_name: str,
    default: bool = True,
) -> bool:
    sources = config.get("sources", [])

    if not isinstance(sources, list):
        return default

    normalized_name = source_name.lower()

    for source in sources:
        if not isinstance(source, dict):
            continue

        configured_name = str(
            source.get(
                "id",
                source.get("name", ""),
            )
        ).lower()

        if configured_name == normalized_name:
            return bool(
                source.get("enabled", True)
            )

    return default


def filter_jobs(
    jobs: list[dict[str, Any]],
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    scanner_config = config.get(
        "scanner",
        {},
    )

    if not isinstance(scanner_config, dict):
        scanner_config = {}

    minimum_score = int(
        scanner_config.get(
            "minimum_score",
            15,
        )
    )

    only_simple = bool(
        scanner_config.get(
            "only_simple",
            False,
        )
    )

    allowed_risks = scanner_config.get(
        "allowed_risks",
        ["low", "medium"],
    )

    if not isinstance(allowed_risks, list):
        allowed_risks = [
            "low",
            "medium",
        ]

    filtered: list[dict[str, Any]] = []

    for job in jobs:
        if int(job.get("score", 0)) < minimum_score:
            continue

        if job.get("risk") not in allowed_risks:
            continue

        if only_simple and not job.get(
            "is_simple",
            False,
        ):
            continue

        filtered.append(job)

    return filtered


def deduplicate_jobs(
    jobs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_links: set[str] = set()

    for job in jobs:
        job_id = str(job.get("id", ""))
        link = str(job.get("link", "")).strip()

        if job_id and job_id in seen_ids:
            continue

        if link and link in seen_links:
            continue

        if job_id:
            seen_ids.add(job_id)

        if link:
            seen_links.add(link)

        result.append(job)

    return result


def merge_with_existing(
    new_jobs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    existing_jobs = load_json(
        JOBS_PATH,
        [],
    )

    if not isinstance(existing_jobs, list):
        existing_jobs = []

    existing_by_id = {
        str(job.get("id")): job
        for job in existing_jobs
        if isinstance(job, dict)
        and job.get("id")
    }

    merged: list[dict[str, Any]] = []

    for job in new_jobs:
        job_id = str(job.get("id", ""))

        old_job = existing_by_id.get(job_id)

        if old_job:
            # Сохраняем пользовательский статус,
            # например избранное или выполненное.
            job["status"] = old_job.get(
                "status",
                job.get("status", "new"),
            )

        merged.append(job)

    merged_ids = {
        str(job.get("id"))
        for job in merged
    }

    # Сохраняем старые объявления, если источник временно
    # не ответил, но ограничиваем общий размер файла.
    for old_job in existing_jobs:
        if not isinstance(old_job, dict):
            continue

        old_id = str(old_job.get("id", ""))

        if old_id and old_id not in merged_ids:
            merged.append(old_job)

    merged.sort(
        key=lambda job: (
            int(job.get("score", 0)),
            str(job.get("published", "")),
        ),
        reverse=True,
    )

    return merged[:1000]


def run_scan() -> dict[str, Any]:
    config = get_config()

    collected_jobs: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    source_counts: dict[str, int] = {}

    source_functions = [
        (
            "Remotive",
            "remotive",
            fetch_remotive,
        ),
        (
            "Remote OK",
            "remote_ok",
            fetch_remote_ok,
        ),
        (
            "We Work Remotely",
            "we_work_remotely",
            fetch_we_work_remotely,
        ),
    ]

    started_at = utc_now()

    for display_name, source_id, function in source_functions:
        if not source_enabled(
            config,
            source_id,
            default=True,
        ):
            source_counts[display_name] = 0
            continue

        try:
            source_jobs = function(config)

            source_counts[display_name] = len(
                source_jobs
            )

            collected_jobs.extend(
                source_jobs
            )

        except (
            urllib.error.URLError,
            urllib.error.HTTPError,
            TimeoutError,
            json.JSONDecodeError,
            ET.ParseError,
            ValueError,
        ) as exc:
            errors.append(
                {
                    "source": display_name,
                    "error": str(exc),
                }
            )

            source_counts[display_name] = 0

        except Exception as exc:
            errors.append(
                {
                    "source": display_name,
                    "error": (
                        f"{type(exc).__name__}: {exc}"
                    ),
                }
            )

            source_counts[display_name] = 0

        # Небольшая пауза между официальными источниками.
        time.sleep(1)

    unique_jobs = deduplicate_jobs(
        collected_jobs
    )

    filtered_jobs = filter_jobs(
        unique_jobs,
        config,
    )

    final_jobs = merge_with_existing(
        filtered_jobs
    )

    save_json(
        JOBS_PATH,
        final_jobs,
    )

    status = {
        "started_at": started_at,
        "finished_at": utc_now(),
        "sources": source_counts,
        "received_total": len(
            collected_jobs
        ),
        "unique_total": len(
            unique_jobs
        ),
        "passed_filters": len(
            filtered_jobs
        ),
        "saved_total": len(
            final_jobs
        ),
        "errors": errors,
    }

    save_json(
        STATUS_PATH,
        status,
    )

    return status


def main() -> None:
    status = run_scan()

    print(
        json.dumps(
            status,
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
