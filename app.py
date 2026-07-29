from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import streamlit as st

import ai
from scanner import detect_language, extract_budget, score_job, stable_id

ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config.json"
JOBS_PATH = ROOT / "jobs.json"
STATUS_PATH = ROOT / "scan_status.json"

st.set_page_config(page_title="Job Agent", page_icon="🧭", layout="wide")


def load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def get_config() -> dict[str, Any]:
    data = load_json(CONFIG_PATH, {})
    return data if isinstance(data, dict) else {}


def get_jobs() -> list[dict[str, Any]]:
    data = load_json(JOBS_PATH, [])
    return data if isinstance(data, list) else []


def job_label(job: dict[str, Any]) -> str:
    return f"{int(job.get('score', 0)):>3}/100 · {job.get('risk', '?')} · {str(job.get('title', 'Untitled'))[:95]}"


def select_job(all_jobs: list[dict[str, Any]], key: str) -> dict[str, Any] | None:
    if not all_jobs:
        st.info("Пока нет заказов. Добавь объявление вручную или дождись сканирования.")
        return None
    options = [(job_label(job), index) for index, job in enumerate(all_jobs)]
    selected_label = st.selectbox("Выбери заказ", [item[0] for item in options], key=key)
    selected_index = dict(options)[selected_label]
    return all_jobs[selected_index]


def render_job(job: dict[str, Any]) -> None:
    st.write(str(job.get("description", ""))[:5000])
    st.caption(
        f"Источник: {job.get('source', '—')} · Бюджет: {job.get('budget_text', '—')} · "
        f"Язык: {job.get('language_hint', '—')} · Опубликовано: {job.get('published', '—')}"
    )
    if job.get("risk_keywords"):
        st.warning("Риск-фразы: " + ", ".join(job["risk_keywords"]))
    if job.get("link"):
        st.link_button("Открыть оригинал", job["link"])


cfg = get_config()
profile = cfg.get("profile", {})
repo_jobs = get_jobs()
manual_jobs = st.session_state.setdefault("manual_jobs", [])
all_jobs = manual_jobs + repo_jobs
scan_status = load_json(STATUS_PATH, {})

st.title("🧭 Job Agent")
st.caption("Ищет объявления, оценивает их, готовит отклики, ответы и черновики работы. Финальные действия на площадке подтверждаешь ты.")

with st.sidebar:
    st.subheader("Состояние")
    st.metric("Заказов", len(repo_jobs))
    st.metric("Рейтинг 70+", sum(int(job.get("score", 0)) >= 70 for job in repo_jobs))
    st.write("ИИ:", "✅ подключён" if ai.available() else "⚠️ без ключа — только шаблон")
    if scan_status:
        st.caption(f"Последняя проверка: {scan_status.get('finished_at', '—')}")
        if scan_status.get("errors"):
            st.warning("Некоторые источники дали ошибку. Открой вкладку диагностики.")
    if st.button("Обновить страницу"):
        st.rerun()

overview, jobs_tab, proposal_tab, chat_tab, work_tab, diagnostics = st.tabs(
    ["Обзор", "Заказы", "Отклик", "Переписка", "Выполнение", "Диагностика"]
)

with overview:
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Всего", len(repo_jobs))
    c2.metric("Низкий риск", sum(job.get("risk") == "low" for job in repo_jobs))
    c3.metric("С бюджетом", sum(job.get("budget_text") != "not stated" for job in repo_jobs))
    c4.metric("Рейтинг 80+", sum(int(job.get("score", 0)) >= 80 for job in repo_jobs))
    st.subheader("Лучшие предложения")
    for job in sorted(repo_jobs, key=lambda row: int(row.get("score", 0)), reverse=True)[:10]:
        with st.expander(job_label(job)):
            render_job(job)

with jobs_tab:
    st.subheader("Добавить объявление вручную")
    with st.form("manual_job"):
        title = st.text_input("Название")
        link = st.text_input("Ссылка, необязательно")
        description = st.text_area("Полное описание", height=230)
        add_manual = st.form_submit_button("Добавить")
    if add_manual:
        if not title.strip() or not description.strip():
            st.error("Заполни название и описание.")
        else:
            score, matched, risks, risk = score_job(title, description, cfg)
            manual_jobs.insert(
                0,
                {
                    "id": stable_id("manual", link, title),
                    "source": "manual",
                    "title": title.strip(),
                    "link": link.strip(),
                    "description": description.strip(),
                    "published": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
                    "scanned_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
                    "language_hint": detect_language(f"{title} {description}"),
                    "budget_text": extract_budget(f"{title} {description}"),
                    "score": score,
                    "risk": risk,
                    "matched_keywords": matched,
                    "risk_keywords": risks,
                    "status": "new",
                },
            )
            st.success("Добавлено в текущую сессию.")
    st.divider()
    min_score = st.slider("Минимальный рейтинг", 0, 100, 35)
    allowed_risks = st.multiselect("Риски", ["low", "medium", "high"], default=["low", "medium"])
    filtered = [job for job in all_jobs if int(job.get("score", 0)) >= min_score and job.get("risk") in allowed_risks]
    st.write(f"Показано: **{len(filtered)}**")
    for job in filtered[:100]:
        with st.expander(job_label(job)):
            render_job(job)

with proposal_tab:
    job = select_job(all_jobs, "proposal_job")
    if job:
        render_job(job)
        preferences = st.text_input("Пожелания", placeholder="Например: коротко, могу закончить сегодня")
        if ai.available():
            if st.button("1. Проанализировать", type="primary"):
                try:
                    st.session_state[f"analysis_{job['id']}"] = ai.analyze_job(job, profile)
                except Exception as exc:
                    st.error(f"Ошибка ИИ: {exc}")
            analysis_key = f"analysis_{job['id']}"
            if analysis_key in st.session_state:
                st.json(st.session_state[analysis_key])
                if st.button("2. Создать отклик"):
                    try:
                        st.session_state[f"proposal_{job['id']}"] = ai.create_proposal(
                            job, profile, st.session_state[analysis_key], preferences
                        )
                    except Exception as exc:
                        st.error(f"Ошибка ИИ: {exc}")
        else:
            st.info("Gemini не подключён. Можно использовать безопасный базовый шаблон.")
            if st.button("Создать базовый шаблон"):
                st.session_state[f"proposal_{job['id']}"] = ai.fallback_proposal(job, profile)
        proposal_key = f"proposal_{job['id']}"
        if proposal_key in st.session_state:
            proposal = st.text_area("Черновик отклика", st.session_state[proposal_key], height=280)
            st.download_button("Скачать TXT", proposal, file_name="proposal.txt")
            if job.get("link"):
                st.link_button("Открыть площадку", job["link"])

with chat_tab:
    st.info("Вставь историю и последнее сообщение клиента. Проверь ответ перед отправкой.")
    facts = st.text_area("Согласованные факты", placeholder="Цена 30 €, срок сегодня 18:00, формат DOCX")
    history = st.text_area("История переписки", height=230)
    incoming = st.text_area("Новое сообщение", height=130)
    language = st.selectbox("Язык ответа", ["auto", "English", "Deutsch", "Українська", "Русский"])
    if st.button("Подготовить ответ"):
        if not ai.available():
            st.error("Для переписки подключи Gemini API key.")
        elif not incoming.strip():
            st.error("Вставь сообщение клиента.")
        else:
            try:
                st.session_state["client_reply"] = ai.create_reply(history, incoming, facts, language)
            except Exception as exc:
                st.error(f"Ошибка ИИ: {exc}")
    if "client_reply" in st.session_state:
        st.text_area("Ответ", st.session_state["client_reply"], height=220)

with work_tab:
    job = select_job(all_jobs, "work_job")
    default_task = str(job.get("title", "")) if job else ""
    task = st.text_area("Задача", value=default_task, height=100)
    materials = st.text_area("Материалы клиента", height=320)
    requirements = st.text_area("Точные требования", height=140)
    output_language = st.selectbox("Язык результата", ["auto", "Deutsch", "English", "Українська", "Русский"])
    if st.button("Создать полный черновик", type="primary"):
        if not ai.available():
            st.error("Для выполнения заказа подключи Gemini API key.")
        elif not task.strip() or not materials.strip():
            st.error("Заполни задачу и материалы.")
        else:
            try:
                st.session_state["work_draft"] = ai.fulfill_order(task, materials, requirements, output_language)
            except Exception as exc:
                st.error(f"Ошибка ИИ: {exc}")
    if "work_draft" in st.session_state:
        draft = st.text_area("Черновик результата", st.session_state["work_draft"], height=520)
        c1, c2 = st.columns(2)
        c1.download_button("Скачать TXT", draft, file_name="finished_work.txt")
        if c2.button("Проверить качество"):
            try:
                st.session_state["qa_report"] = ai.quality_check(task, requirements, draft)
            except Exception as exc:
                st.error(f"Ошибка ИИ: {exc}")
    if "qa_report" in st.session_state:
        st.text_area("Проверка", st.session_state["qa_report"], height=260)

with diagnostics:
    st.subheader("Проверка системы")
    st.json(
        {
            "config_loaded": bool(cfg),
            "jobs_loaded": isinstance(repo_jobs, list),
            "gemini_library": ai.genai is not None,
            "gemini_key": bool(ai.get_secret("GEMINI_API_KEY")),
            "gemini_model": ai.get_secret("GEMINI_MODEL", ai.DEFAULT_MODEL),
            "enabled_sources": sum(bool(source.get("enabled")) for source in cfg.get("sources", [])),
            "last_scan": scan_status,
        }
    )
    st.warning("Система специально не отправляет заявки сама, не обходит CAPTCHA и не скрывает автоматизацию. Это защищает аккаунт от блокировки.")
