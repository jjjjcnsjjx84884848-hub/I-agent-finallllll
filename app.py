from __future__ import annotations

import json
import re
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

st.set_page_config(
    page_title="Агент вакансий",
    page_icon="🧭",
    layout="wide",
)


# Простые типы заданий, которые легче выполнять с помощью ИИ.
SIMPLE_TASK_KEYWORDS = [
    # Английский
    "translation",
    "translate",
    "translator",
    "proofreading",
    "proofread",
    "data entry",
    "copy paste",
    "copy-paste",
    "transcription",
    "transcribe",
    "subtitle",
    "subtitles",
    "typing",
    "retyping",
    "rewrite",
    "rewriting",
    "text editing",
    "content editing",
    "product description",
    "short description",
    "email writing",
    "virtual assistant",
    "web research",
    "internet research",
    "simple research",
    "document formatting",
    "pdf to word",
    "image to text",
    "audio to text",

    # Немецкий
    "übersetzung",
    "übersetzen",
    "korrekturlesen",
    "korrektur",
    "dateneingabe",
    "abschreiben",
    "transkription",
    "untertitel",
    "texterfassung",
    "text bearbeiten",
    "produktbeschreibung",
    "internetrecherche",
    "virtuelle assistenz",

    # Русский
    "перевод",
    "перевести",
    "переводчик",
    "расшифровка",
    "транскрибация",
    "набор текста",
    "копирование данных",
    "ввод данных",
    "проверка текста",
    "редактирование текста",
    "описание товара",
    "субтитры",
    "поиск информации",
    "виртуальный помощник",

    # Украинский
    "переклад",
    "перекласти",
    "перекладач",
    "розшифровка",
    "транскрипція",
    "набір тексту",
    "введення даних",
    "редагування тексту",
    "опис товару",
    "субтитри",
    "пошук інформації",
    "віртуальний помічник",
]

COMPLEX_TASK_KEYWORDS = [
    "senior",
    "expert",
    "advanced",
    "blockchain",
    "machine learning",
    "full stack",
    "full-stack",
    "backend developer",
    "frontend developer",
    "mobile app",
    "legal advice",
    "medical diagnosis",
    "architectural design",
    "3d modeling",
    "3d animation",
    "complex automation",
    "сложная автоматизация",
    "юридическая консультация",
    "медицинская консультация",
    "senior entwickler",
]

RISK_LABELS = {
    "low": "низкий",
    "medium": "средний",
    "high": "высокий",
}

LANGUAGE_LABELS = {
    "en": "английский",
    "de": "немецкий",
    "ru": "русский",
    "uk": "украинский",
    "auto": "автоматически",
}


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


def text_for_job(job: dict[str, Any]) -> str:
    return (
        f"{job.get('title', '')} "
        f"{job.get('description', '')}"
    ).lower()


def simple_task_score(job: dict[str, Any]) -> int:
    """
    Возвращает оценку простоты задания.

    Чем выше значение, тем больше признаков простой задачи.
    Сложные технические задания получают штраф.
    """
    text = text_for_job(job)

    score = 0

    for keyword in SIMPLE_TASK_KEYWORDS:
        if keyword in text:
            score += 2

    for keyword in COMPLEX_TASK_KEYWORDS:
        if keyword in text:
            score -= 3

    description_length = len(str(job.get("description", "")))

    # Очень длинные описания чаще означают более сложный проект.
    if description_length > 6000:
        score -= 2
    elif description_length < 2500:
        score += 1

    return score


def is_simple_task(job: dict[str, Any]) -> bool:
    return simple_task_score(job) >= 1


def extract_budget_numbers(job: dict[str, Any]) -> list[float]:
    """
    Извлекает числа из budget_text.

    Например:
    "$10 - $30" -> [10, 30]
    "20 USD" -> [20]
    """
    budget_text = str(job.get("budget_text", "")).strip().lower()

    if not budget_text or budget_text in {
        "not stated",
        "not_stated",
        "unknown",
        "none",
        "—",
    }:
        return []

    clean_text = (
        budget_text
        .replace(",", ".")
        .replace("€", " ")
        .replace("$", " ")
    )

    matches = re.findall(r"\d+(?:\.\d+)?", clean_text)

    values: list[float] = []

    for match in matches:
        try:
            value = float(match)

            # Отсекаем числа, похожие на годы и другие нерелевантные данные.
            if 0 < value < 100_000:
                values.append(value)
        except ValueError:
            continue

    return values


def job_matches_budget(
    job: dict[str, Any],
    minimum: float,
    maximum: float,
    include_unspecified: bool,
) -> bool:
    values = extract_budget_numbers(job)

    if not values:
        return include_unspecified

    detected_min = min(values)
    detected_max = max(values)

    # Диапазоны пересекаются.
    return detected_max >= minimum and detected_min <= maximum


def budget_label(job: dict[str, Any]) -> str:
    value = str(job.get("budget_text", "")).strip()

    if not value or value.lower() in {
        "not stated",
        "not_stated",
        "unknown",
        "none",
    }:
        return "не указан"

    return value


def risk_label(job: dict[str, Any]) -> str:
    risk = str(job.get("risk", "unknown"))
    return RISK_LABELS.get(risk, "не определён")


def language_label(job: dict[str, Any]) -> str:
    language = str(job.get("language_hint", "—"))
    return LANGUAGE_LABELS.get(language, language)


def job_label(job: dict[str, Any]) -> str:
    title = str(job.get("title", "Без названия"))[:90]
    score = int(job.get("score", 0))
    simple_mark = " · простое" if is_simple_task(job) else ""

    return (
        f"{score}/100 · риск: {risk_label(job)}"
        f"{simple_mark} · {title}"
    )


def select_job(
    all_jobs: list[dict[str, Any]],
    key: str,
) -> dict[str, Any] | None:
    if not all_jobs:
        st.info(
            "Пока нет заказов. Добавь объявление вручную "
            "или дождись следующего сканирования."
        )
        return None

    selected_index = st.selectbox(
        "Выбери заказ",
        options=list(range(len(all_jobs))),
        format_func=lambda index: job_label(all_jobs[index]),
        key=key,
    )

    return all_jobs[selected_index]


def render_job(job: dict[str, Any]) -> None:
    if is_simple_task(job):
        st.success("Подходит под категорию простых заданий")

    st.write(str(job.get("description", ""))[:5000])

    st.caption(
        f"Источник: {job.get('source', '—')} · "
        f"Бюджет: {budget_label(job)} · "
        f"Язык: {language_label(job)} · "
        f"Риск: {risk_label(job)} · "
        f"Опубликовано: {job.get('published', '—')}"
    )

    matched_keywords = job.get("matched_keywords", [])

    if matched_keywords:
        st.caption(
            "Совпавшие ключевые слова: "
            + ", ".join(str(item) for item in matched_keywords)
        )

    risk_keywords = job.get("risk_keywords", [])

    if risk_keywords:
        st.warning(
            "Подозрительные слова или фразы: "
            + ", ".join(str(item) for item in risk_keywords)
        )

    link = str(job.get("link", "")).strip()

    if link:
        st.link_button("Открыть оригинальное объявление", link)


def render_analysis(analysis: dict[str, Any]) -> None:
    """
    Показывает результат анализа с русскими названиями полей.
    """
    c1, c2, c3 = st.columns(3)

    c1.metric(
        "Соответствие",
        f"{analysis.get('fit_score', '—')}/100",
    )

    c2.metric(
        "Примерное время",
        f"{analysis.get('estimated_minutes', '—')} мин.",
    )

    suggested_price = analysis.get("suggested_price_eur", "—")

    c3.metric(
        "Предлагаемая цена",
        f"{suggested_price} €",
    )

    recommended = analysis.get("recommended")

    if recommended is True:
        st.success("ИИ рекомендует рассмотреть этот заказ.")
    elif recommended is False:
        st.warning("ИИ не считает этот заказ оптимальным.")

    st.write(
        "**Тип задачи:**",
        analysis.get("task_type", "не определён"),
    )

    st.write(
        "**Язык объявления:**",
        analysis.get("detected_language", "не определён"),
    )

    st.write(
        "**Оценка срока:**",
        analysis.get("deadline_assessment", "не указана"),
    )

    st.write(
        "**Причина оценки:**",
        analysis.get("reason", "не указана"),
    )

    missing_information = analysis.get("missing_information", [])

    if missing_information:
        st.info(
            "**Что нужно уточнить:**\n\n"
            + "\n".join(
                f"- {item}" for item in missing_information
            )
        )

    risks = analysis.get("risks", [])

    if risks:
        st.warning(
            "**Возможные риски:**\n\n"
            + "\n".join(f"- {item}" for item in risks)
        )


cfg = get_config()
profile = cfg.get("profile", {})
repo_jobs = get_jobs()

manual_jobs = st.session_state.setdefault("manual_jobs", [])
all_jobs = manual_jobs + repo_jobs

scan_status = load_json(STATUS_PATH, {})


st.title("🧭 Агент вакансий")

st.caption(
    "Ищет объявления, оценивает их, готовит отклики, "
    "ответы клиентам и черновики работы. "
    "Финальную отправку на площадке подтверждаешь ты."
)


with st.sidebar:
    st.subheader("Состояние")

    st.metric("Найдено заказов", len(repo_jobs))

    st.metric(
        "Рейтинг 70 и выше",
        sum(
            int(job.get("score", 0)) >= 70
            for job in repo_jobs
        ),
    )

    st.metric(
        "Простых заданий",
        sum(is_simple_task(job) for job in repo_jobs),
    )

    st.write(
        "ИИ:",
        "✅ подключён"
        if ai.available()
        else "⚠️ ключ не подключён — доступен только шаблон",
    )

    if scan_status:
        st.caption(
            "Последняя проверка: "
            f"{scan_status.get('finished_at', '—')}"
        )

        if scan_status.get("errors"):
            st.warning(
                "Некоторые источники вернули ошибку. "
                "Открой вкладку «Диагностика»."
            )

    if st.button("Обновить страницу"):
        st.rerun()


overview, jobs_tab, proposal_tab, chat_tab, work_tab, diagnostics = st.tabs(
    [
        "Обзор",
        "Заказы",
        "Отклик",
        "Переписка",
        "Выполнение",
        "Диагностика",
    ]
)


with overview:
    c1, c2, c3, c4 = st.columns(4)

    c1.metric("Всего", len(repo_jobs))

    c2.metric(
        "Низкий риск",
        sum(
            job.get("risk") == "low"
            for job in repo_jobs
        ),
    )

    c3.metric(
        "Простых",
        sum(is_simple_task(job) for job in repo_jobs),
    )

    c4.metric(
        "Рейтинг 80 и выше",
        sum(
            int(job.get("score", 0)) >= 80
            for job in repo_jobs
        ),
    )

    st.subheader("Лучшие простые предложения")

    best_jobs = sorted(
        repo_jobs,
        key=lambda row: (
            simple_task_score(row),
            int(row.get("score", 0)),
        ),
        reverse=True,
    )

    for job in best_jobs[:10]:
        with st.expander(job_label(job)):
            render_job(job)


with jobs_tab:
    st.subheader("Добавить объявление вручную")

    with st.form("manual_job"):
        title = st.text_input("Название задания")

        link = st.text_input(
            "Ссылка",
            placeholder="Необязательно",
        )

        description = st.text_area(
            "Полное описание",
            height=230,
        )

        add_manual = st.form_submit_button(
            "Добавить объявление"
        )

    if add_manual:
        if not title.strip() or not description.strip():
            st.error("Заполни название и описание.")
        else:
            score, matched, risks, risk = score_job(
                title,
                description,
                cfg,
            )

            now = (
                datetime.now(timezone.utc)
                .replace(microsecond=0)
                .isoformat()
            )

            manual_jobs.insert(
                0,
                {
                    "id": stable_id(
                        "manual",
                        link,
                        title,
                    ),
                    "source": "добавлено вручную",
                    "title": title.strip(),
                    "link": link.strip(),
                    "description": description.strip(),
                    "published": now,
                    "scanned_at": now,
                    "language_hint": detect_language(
                        f"{title} {description}"
                    ),
                    "budget_text": extract_budget(
                        f"{title} {description}"
                    ),
                    "score": score,
                    "risk": risk,
                    "matched_keywords": matched,
                    "risk_keywords": risks,
                    "status": "new",
                },
            )

            st.success(
                "Объявление добавлено в текущую сессию."
            )

    st.divider()
    st.subheader("Фильтры")

    min_score = st.slider(
        "Минимальный рейтинг",
        min_value=0,
        max_value=100,
        value=25,
        step=5,
    )

    budget_range = st.slider(
        "Бюджет задания, $",
        min_value=0,
        max_value=200,
        value=(5, 50),
        step=5,
        help=(
            "По умолчанию показываются задания "
            "с бюджетом от $5 до $50."
        ),
    )

    include_unspecified_budget = st.checkbox(
        "Показывать задания без указанного бюджета",
        value=True,
    )

    only_simple = st.checkbox(
        "Показывать только простые задания",
        value=True,
        help=(
            "Переводы, набор текста, транскрибация, "
            "копирование данных, лёгкие описания и поиск информации."
        ),
    )

    risk_options = {
        "Низкий": "low",
        "Средний": "medium",
        "Высокий": "high",
    }

    selected_risk_labels = st.multiselect(
        "Допустимый риск",
        options=list(risk_options.keys()),
        default=["Низкий", "Средний"],
    )

    selected_risks = {
        risk_options[label]
        for label in selected_risk_labels
    }

    search_text = st.text_input(
        "Поиск по словам",
        placeholder=(
            "Например: перевод, transcription, data entry"
        ),
    ).strip().lower()

    filtered_jobs: list[dict[str, Any]] = []

    for job in all_jobs:
        if int(job.get("score", 0)) < min_score:
            continue

        if job.get("risk") not in selected_risks:
            continue

        if only_simple and not is_simple_task(job):
            continue

        if not job_matches_budget(
            job,
            float(budget_range[0]),
            float(budget_range[1]),
            include_unspecified_budget,
        ):
            continue

        if search_text and search_text not in text_for_job(job):
            continue

        filtered_jobs.append(job)

    filtered_jobs.sort(
        key=lambda row: (
            simple_task_score(row),
            int(row.get("score", 0)),
        ),
        reverse=True,
    )

    st.write(f"Показано заказов: **{len(filtered_jobs)}**")

    if not filtered_jobs:
        st.info(
            "По выбранным фильтрам ничего не найдено. "
            "Попробуй включить задания без бюджета, "
            "снизить минимальный рейтинг или отключить "
            "фильтр простых заданий."
        )

    for job in filtered_jobs[:100]:
        with st.expander(job_label(job)):
            render_job(job)


with proposal_tab:
    job = select_job(all_jobs, "proposal_job")

    if job:
        render_job(job)

        preferences = st.text_input(
            "Дополнительные пожелания к отклику",
            placeholder=(
                "Например: коротко, могу закончить сегодня"
            ),
        )

        if ai.available():
            if st.button(
                "1. Проанализировать заказ",
                type="primary",
            ):
                try:
                    with st.spinner(
                        "ИИ анализирует объявление..."
                    ):
                        st.session_state[
                            f"analysis_{job['id']}"
                        ] = ai.analyze_job(job, profile)

                except Exception as exc:
                    st.error(f"Ошибка ИИ: {exc}")

            analysis_key = f"analysis_{job['id']}"

            if analysis_key in st.session_state:
                st.subheader("Результат анализа")

                render_analysis(
                    st.session_state[analysis_key]
                )

                if st.button("2. Создать отклик"):
                    try:
                        with st.spinner(
                            "ИИ готовит персональный отклик..."
                        ):
                            st.session_state[
                                f"proposal_{job['id']}"
                            ] = ai.create_proposal(
                                job,
                                profile,
                                st.session_state[analysis_key],
                                preferences,
                            )

                    except Exception as exc:
                        st.error(f"Ошибка ИИ: {exc}")

        else:
            st.info(
                "OpenAI не подключён. "
                "Можно использовать базовый шаблон."
            )

            if st.button("Создать базовый шаблон"):
                st.session_state[
                    f"proposal_{job['id']}"
                ] = ai.fallback_proposal(
                    job,
                    profile,
                )

        proposal_key = f"proposal_{job['id']}"

        if proposal_key in st.session_state:
            proposal = st.text_area(
                "Черновик отклика",
                st.session_state[proposal_key],
                height=280,
            )

            st.download_button(
                "Скачать отклик в формате TXT",
                proposal,
                file_name="otklik.txt",
            )

            if job.get("link"):
                st.link_button(
                    "Открыть сайт с объявлением",
                    job["link"],
                )


with chat_tab:
    st.info(
        "Вставь историю переписки и последнее сообщение клиента. "
        "Обязательно проверь ответ перед отправкой."
    )

    facts = st.text_area(
        "Уже согласованные условия",
        placeholder=(
            "Цена $30, срок сегодня до 18:00, формат DOCX"
        ),
    )

    history = st.text_area(
        "История переписки",
        height=230,
    )

    incoming = st.text_area(
        "Новое сообщение клиента",
        height=130,
    )

    language = st.selectbox(
        "Язык ответа",
        [
            "auto",
            "Русский",
            "Українська",
            "Deutsch",
            "English",
        ],
        format_func=lambda value: (
            "Определить автоматически"
            if value == "auto"
            else value
        ),
    )

    if st.button("Подготовить ответ"):
        if not ai.available():
            st.error(
                "Для создания ответа подключи OpenAI API."
            )

        elif not incoming.strip():
            st.error(
                "Сначала вставь сообщение клиента."
            )

        else:
            try:
                with st.spinner(
                    "ИИ готовит ответ клиенту..."
                ):
                    st.session_state[
                        "client_reply"
                    ] = ai.create_reply(
                        history,
                        incoming,
                        facts,
                        language,
                    )

            except Exception as exc:
                st.error(f"Ошибка ИИ: {exc}")

    if "client_reply" in st.session_state:
        st.text_area(
            "Готовый ответ",
            st.session_state["client_reply"],
            height=220,
        )


with work_tab:
    job = select_job(all_jobs, "work_job")

    default_task = (
        str(job.get("title", ""))
        if job
        else ""
    )

    task = st.text_area(
        "Что нужно выполнить",
        value=default_task,
        height=100,
    )

    materials = st.text_area(
        "Материалы от клиента",
        height=320,
        placeholder=(
            "Вставь текст, данные, ссылки или другую "
            "информацию от клиента."
        ),
    )

    requirements = st.text_area(
        "Точные требования клиента",
        height=140,
    )

    output_language = st.selectbox(
        "Язык готового результата",
        [
            "auto",
            "Русский",
            "Українська",
            "Deutsch",
            "English",
        ],
        format_func=lambda value: (
            "Определить автоматически"
            if value == "auto"
            else value
        ),
    )

    if st.button(
        "Создать полный черновик",
        type="primary",
    ):
        if not ai.available():
            st.error(
                "Для выполнения заказа подключи OpenAI API."
            )

        elif not task.strip():
            st.error(
                "Сначала заполни поле с задачей."
            )

        elif not materials.strip():
            st.error(
                "Добавь материалы клиента."
            )

        else:
            try:
                with st.spinner(
                    "ИИ выполняет задание..."
                ):
                    st.session_state[
                        "work_draft"
                    ] = ai.fulfill_order(
                        task,
                        materials,
                        requirements,
                        output_language,
                    )

            except Exception as exc:
                st.error(f"Ошибка ИИ: {exc}")

    if "work_draft" in st.session_state:
        draft = st.text_area(
            "Черновик готовой работы",
            st.session_state["work_draft"],
            height=520,
        )

        c1, c2 = st.columns(2)

        c1.download_button(
            "Скачать результат в формате TXT",
            draft,
            file_name="gotovaya_rabota.txt",
        )

        if c2.button("Проверить качество"):
            try:
                with st.spinner(
                    "ИИ проверяет качество результата..."
                ):
                    st.session_state[
                        "qa_report"
                    ] = ai.quality_check(
                        task,
                        requirements,
                        draft,
                    )

            except Exception as exc:
                st.error(f"Ошибка ИИ: {exc}")

    if "qa_report" in st.session_state:
        st.text_area(
            "Отчёт о проверке",
            st.session_state["qa_report"],
            height=260,
        )


with diagnostics:
    st.subheader("Проверка системы")

    diagnostic_data = {
        "Конфигурация загружена": bool(cfg),
        "Список заказов загружен": isinstance(
            repo_jobs,
            list,
        ),
        "Библиотека OpenAI установлена": (
            ai.OpenAI is not None
        ),
        "Ключ OpenAI найден": bool(
            ai.get_secret("OPENAI_API_KEY")
        ),
        "Модель OpenAI": ai.get_secret(
            "OPENAI_MODEL",
            ai.DEFAULT_MODEL,
        ),
        "Включено источников": sum(
            bool(source.get("enabled"))
            for source in cfg.get("sources", [])
        ),
        "Последнее сканирование": scan_status,
    }

    st.json(diagnostic_data)

    st.warning(
        "Система специально не отправляет заявки сама, "
        "не обходит CAPTCHA и не скрывает автоматизацию. "
        "Это снижает риск блокировки аккаунта."
    )
