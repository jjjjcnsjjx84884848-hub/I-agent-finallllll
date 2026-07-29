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
    # ---------------------------------------------------------
# ВЕРХНЯЯ ЧАСТЬ ИНТЕРФЕЙСА
# ---------------------------------------------------------

st.markdown(
    """
    <div class="hero-card">
        <div class="main-title">✨ Фриланс-Агент</div>
        <div class="main-subtitle">
            Поиск простых удалённых заданий, подготовка откликов,
            помощь с перепиской и выполнение текстовых заказов.
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)


# ---------------------------------------------------------
# БОКОВАЯ ПАНЕЛЬ
# ---------------------------------------------------------

with st.sidebar:
    st.markdown("## ✨ Фриланс-Агент")

    if ai.available():
        st.success("OpenAI подключён")
    else:
        st.warning(
            "OpenAI не подключён. "
            "Доступны только базовые шаблоны."
        )

    st.divider()
    st.markdown("### 📊 Состояние")

    st.metric(
        "Всего заказов",
        len(repo_jobs),
    )

    st.metric(
        "Простых заданий",
        sum(
            is_simple_task(job)
            for job in repo_jobs
        ),
    )

    st.metric(
        "Низкий риск",
        sum(
            str(job.get("risk")) == "low"
            for job in repo_jobs
        ),
    )

    st.metric(
        "В избранном",
        len(favorites),
    )

    if scan_status:
        st.divider()
        st.markdown("### 🔄 Последнее сканирование")

        finished_at = str(
            scan_status.get(
                "finished_at",
                "Неизвестно",
            )
        )

        st.caption(
            f"Завершено: {finished_at}"
        )

        saved_total = scan_status.get(
            "saved_total",
            scan_status.get(
                "received_total",
                "—",
            ),
        )

        st.caption(
            f"Сохранено заданий: {saved_total}"
        )

        errors = scan_status.get(
            "errors",
            [],
        )

        if errors:
            st.warning(
                "Некоторые источники вернули ошибку."
            )

    st.divider()

    if st.button(
        "🔄 Обновить страницу",
        use_container_width=True,
    ):
        st.rerun()

    st.caption(
        "Приложение не отправляет заявки автоматически "
        "и не обходит ограничения площадок."
    )


# ---------------------------------------------------------
# ВКЛАДКИ
# ---------------------------------------------------------

(
    overview_tab,
    jobs_tab,
    favorites_tab,
    proposal_tab,
    chat_tab,
    work_tab,
    history_tab,
    diagnostics_tab,
) = st.tabs(
    [
        "🏠 Главная",
        "🔎 Заказы",
        "❤️ Избранное",
        "✉️ Отклик",
        "💬 Переписка",
        "💼 Работа",
        "📚 История",
        "⚙️ Диагностика",
    ]
)


# ---------------------------------------------------------
# ВКЛАДКА: ГЛАВНАЯ
# ---------------------------------------------------------

with overview_tab:
    st.subheader("Обзор")

    metric_1, metric_2, metric_3, metric_4 = st.columns(4)

    metric_1.metric(
        "Найдено заказов",
        len(repo_jobs),
    )

    metric_2.metric(
        "Подходящих",
        sum(
            calculate_opportunity_score(job) >= 65
            for job in repo_jobs
        ),
    )

    metric_3.metric(
        "Простых",
        sum(
            is_simple_task(job)
            for job in repo_jobs
        ),
    )

    metric_4.metric(
        "Высокий риск",
        sum(
            str(job.get("risk")) == "high"
            for job in repo_jobs
        ),
    )

    st.divider()

    left_column, right_column = st.columns(
        [1.6, 1]
    )

    with left_column:
        st.subheader("🔥 Лучшие найденные задания")

        best_jobs = sorted(
            repo_jobs,
            key=lambda job: (
                calculate_opportunity_score(job),
                int(job.get("score", 0)),
            ),
            reverse=True,
        )

        best_jobs = [
            job
            for job in best_jobs
            if str(job.get("risk")) != "high"
        ][:6]

        if not best_jobs:
            st.info(
                "Пока нет подходящих заданий. "
                "Дождись сканирования или добавь объявление вручную."
            )

        for index, job in enumerate(best_jobs):
            with st.expander(
                job_option_label(job),
                expanded=index == 0,
            ):
                render_job_card(
                    job,
                    expanded_description=True,
                    card_key=f"overview_{index}_{job.get('id', '')}",
                )

    with right_column:
        st.subheader("🎯 Что искать в первую очередь")

        st.markdown(
            """
            <div class="hero-card">
                <b>Лучшие простые категории:</b><br><br>
                🌍 перевод коротких текстов;<br>
                ✍️ проверка и исправление текста;<br>
                🎧 расшифровка аудио;<br>
                📋 ввод и перенос данных;<br>
                📄 PDF в Word;<br>
                🔎 простой поиск информации;<br>
                💬 письма и сообщения на немецком.
            </div>
            """,
            unsafe_allow_html=True,
        )

        st.subheader("🛡️ Основные правила безопасности")

        st.markdown(
            """
            <div class="hero-card">
                Не плати заказчику за получение работы.<br><br>
                Не покупай подарочные карты.<br><br>
                Не передавай доступ к банковскому счёту.<br><br>
                Не отправляй паспорт без понятной и законной причины.<br><br>
                Оплату лучше получать через безопасную систему площадки.
            </div>
            """,
            unsafe_allow_html=True,
        )

        st.subheader("📌 Быстрый статус")

        openai_status = (
            "Подключён"
            if ai.available()
            else "Не подключён"
        )

        st.write(
            f"**ИИ:** {openai_status}"
        )

        st.write(
            f"**Источников включено:** "
            f"{sum(bool(source.get('enabled')) for source in cfg.get('sources', []))}"
        )

        st.write(
            f"**Записей в истории:** {len(history)}"
        )


# ---------------------------------------------------------
# ВКЛАДКА: ЗАКАЗЫ
# ---------------------------------------------------------

with jobs_tab:
    st.subheader("🔎 Поиск и фильтрация заказов")

    with st.expander(
        "➕ Добавить объявление вручную",
        expanded=False,
    ):
        with st.form(
            "manual_job_form",
            clear_on_submit=True,
        ):
            manual_title = st.text_input(
                "Название задания",
                placeholder=(
                    "Например: Перевести короткий текст "
                    "с немецкого на русский"
                ),
            )

            manual_link = st.text_input(
                "Ссылка на объявление",
                placeholder="Необязательно",
            )

            manual_description = st.text_area(
                "Описание задания",
                height=220,
                placeholder=(
                    "Вставь сюда полное описание объявления."
                ),
            )

            manual_budget = st.text_input(
                "Бюджет",
                placeholder=(
                    "Например: $20 или $10–$30"
                ),
            )

            manual_submit = st.form_submit_button(
                "Добавить объявление",
                use_container_width=True,
            )

        if manual_submit:
            if not manual_title.strip():
                st.error(
                    "Нужно указать название задания."
                )

            elif not manual_description.strip():
                st.error(
                    "Нужно добавить описание задания."
                )

            else:
                combined_manual_text = (
                    f"{manual_title} "
                    f"{manual_description} "
                    f"{manual_budget}"
                )

                (
                    manual_score,
                    manual_matched,
                    manual_risks,
                    manual_risk,
                ) = score_job(
                    manual_title,
                    combined_manual_text,
                    cfg,
                )

                created_time = utc_now()

                manual_job = {
                    "id": stable_id(
                        "manual",
                        manual_link,
                        manual_title,
                    ),
                    "source": "Добавлено вручную",
                    "title": manual_title.strip(),
                    "link": manual_link.strip(),
                    "description": manual_description.strip(),
                    "published": created_time,
                    "scanned_at": created_time,
                    "company": "",
                    "location": "",
                    "category": "",
                    "language_hint": detect_language(
                        combined_manual_text
                    ),
                    "budget_text": (
                        manual_budget.strip()
                        or extract_budget(
                            combined_manual_text
                        )
                    ),
                    "score": manual_score,
                    "risk": manual_risk,
                    "task_type": classify_task_local(
                        {
                            "title": manual_title,
                            "description": manual_description,
                        }
                    ),
                    "is_simple": True,
                    "matched_keywords": manual_matched,
                    "risk_keywords": manual_risks,
                    "status": "new",
                }

                manual_jobs.insert(
                    0,
                    manual_job,
                )

                st.success(
                    "Объявление добавлено в текущую сессию."
                )

    st.divider()
    st.markdown("### Фильтры")

    filter_row_1 = st.columns(
        [1.1, 1.3, 1.1]
    )

    with filter_row_1[0]:
        minimum_score_filter = st.slider(
            "Минимальная выгодность",
            min_value=0,
            max_value=100,
            value=25,
            step=5,
        )

    with filter_row_1[1]:
        budget_filter = st.slider(
            "Бюджет задания, $",
            min_value=0,
            max_value=500,
            value=(5, 50),
            step=5,
            help=(
                "Показывает задания, бюджет которых "
                "пересекается с выбранным диапазоном."
            ),
        )

    with filter_row_1[2]:
        sorting_option = st.selectbox(
            "Сортировка",
            [
                "По выгодности",
                "По рейтингу сканера",
                "Сначала простые",
                "Сначала новые",
            ],
        )

    filter_row_2 = st.columns(
        [1.3, 1.1, 1.1]
    )

    with filter_row_2[0]:
        search_query = st.text_input(
            "Поиск по словам",
            placeholder=(
                "Например: перевод, немецкий, data entry"
            ),
        ).strip().lower()

    with filter_row_2[1]:
        risk_labels_selected = st.multiselect(
            "Допустимый риск",
            options=[
                "Низкий",
                "Средний",
                "Высокий",
            ],
            default=[
                "Низкий",
                "Средний",
            ],
        )

    with filter_row_2[2]:
        task_labels_selected = st.multiselect(
            "Тип задания",
            options=list(
                TASK_LABELS.values()
            ),
            default=[],
            placeholder="Все категории",
        )

    filter_row_3 = st.columns(3)

    with filter_row_3[0]:
        only_simple_filter = st.checkbox(
            "Только простые задания",
            value=True,
        )

    with filter_row_3[1]:
        include_without_budget_filter = st.checkbox(
            "Показывать без бюджета",
            value=True,
        )

    with filter_row_3[2]:
        only_favorites_filter = st.checkbox(
            "Только избранное",
            value=False,
        )

    selected_risk_values = {
        key
        for key, value in RISK_LABELS.items()
        if value in risk_labels_selected
    }

    filtered_jobs: list[dict[str, Any]] = []

    for job in all_jobs:
        opportunity_score = calculate_opportunity_score(
            job
        )

        if opportunity_score < minimum_score_filter:
            continue

        if (
            selected_risk_values
            and str(job.get("risk")) not in selected_risk_values
        ):
            continue

        if only_simple_filter and not is_simple_task(job):
            continue

        if only_favorites_filter and not is_favorite(
            str(job.get("id", ""))
        ):
            continue

        if task_labels_selected:
            current_task_label = task_display(job)

            if current_task_label not in task_labels_selected:
                continue

        if not budget_in_range(
            job,
            float(budget_filter[0]),
            float(budget_filter[1]),
            include_without_budget_filter,
        ):
            continue

        if search_query:
            searchable_text = job_full_text(job)

            if search_query not in searchable_text:
                continue

        filtered_jobs.append(job)

    if sorting_option == "По рейтингу сканера":
        filtered_jobs.sort(
            key=lambda job: int(
                job.get("score", 0)
            ),
            reverse=True,
        )

    elif sorting_option == "Сначала простые":
        filtered_jobs.sort(
            key=lambda job: (
                simple_task_score(job),
                calculate_opportunity_score(job),
            ),
            reverse=True,
        )

    elif sorting_option == "Сначала новые":
        filtered_jobs.sort(
            key=lambda job: str(
                job.get(
                    "published",
                    job.get("scanned_at", ""),
                )
            ),
            reverse=True,
        )

    else:
        filtered_jobs.sort(
            key=lambda job: calculate_opportunity_score(
                job
            ),
            reverse=True,
        )

    st.divider()

    result_header_1, result_header_2 = st.columns(
        [3, 1]
    )

    result_header_1.markdown(
        f"### Найдено: {len(filtered_jobs)}"
    )

    result_header_2.caption(
        f"Всего в базе: {len(all_jobs)}"
    )

    if not filtered_jobs:
        st.info(
            "По выбранным фильтрам ничего не найдено. "
            "Попробуй включить объявления без бюджета, "
            "расширить диапазон цены или отключить "
            "фильтр простых заданий."
        )

    jobs_to_show = filtered_jobs[:100]

    for index, job in enumerate(jobs_to_show):
        with st.expander(
            job_option_label(job),
            expanded=False,
        ):
            render_job_card(
                job,
                expanded_description=True,
                card_key=(
                    f"jobs_{index}_"
                    f"{job.get('id', '')}"
                ),
            )

    if len(filtered_jobs) > 100:
        st.caption(
            "Показаны первые 100 заданий. "
            "Используй фильтры, чтобы сузить результаты."
        )


# ---------------------------------------------------------
# ВКЛАДКА: ИЗБРАННОЕ
# ---------------------------------------------------------

with favorites_tab:
    st.subheader("❤️ Избранные задания")

    favorite_ids = set(
        get_favorites()
    )

    favorite_jobs = [
        job
        for job in all_jobs
        if str(job.get("id", "")) in favorite_ids
    ]

    favorite_jobs.sort(
        key=lambda job: calculate_opportunity_score(
            job
        ),
        reverse=True,
    )

    if not favorite_jobs:
        st.info(
            "В избранном пока ничего нет. "
            "Добавляй интересные задания кнопкой "
            "«В избранное»."
        )

    for index, job in enumerate(favorite_jobs):
        with st.expander(
            job_option_label(job),
            expanded=index == 0,
        ):
            render_job_card(
                job,
                expanded_description=True,
                card_key=(
                    f"favorites_{index}_"
                    f"{job.get('id', '')}"
                ),
            )
            # ---------------------------------------------------------
# УНИВЕРСАЛЬНЫЙ ВЫЗОВ OPENAI
# ---------------------------------------------------------

def get_openai_secret(
    secret_name: str,
    default: str = "",
) -> str:
    try:
        value = st.secrets.get(
            secret_name,
            default,
        )

        return str(value).strip()

    except Exception:
        return default


def extract_response_text(
    response: Any,
) -> str:
    direct_text = getattr(
        response,
        "output_text",
        None,
    )

    if direct_text:
        return str(direct_text).strip()

    output = getattr(
        response,
        "output",
        None,
    )

    if not output:
        return ""

    collected_parts: list[str] = []

    for output_item in output:
        content_items = getattr(
            output_item,
            "content",
            [],
        )

        for content_item in content_items:
            text_value = getattr(
                content_item,
                "text",
                None,
            )

            if text_value:
                collected_parts.append(
                    str(text_value)
                )

    return "\n".join(
        collected_parts
    ).strip()


def call_openai(
    instructions: str,
    user_content: str,
    *,
    max_output_tokens: int = 2200,
) -> str:
    api_key = get_openai_secret(
        "OPENAI_API_KEY"
    )

    model = get_openai_secret(
        "OPENAI_MODEL",
        "gpt-5-mini",
    )

    if not api_key:
        raise RuntimeError(
            "В Streamlit Secrets отсутствует "
            "OPENAI_API_KEY."
        )

    try:
        from openai import OpenAI
    except Exception as exc:
        raise RuntimeError(
            "Библиотека OpenAI не установлена. "
            "Добавь openai>=1.0.0 в requirements.txt."
        ) from exc

    client = OpenAI(
        api_key=api_key
    )

    response = client.responses.create(
        model=model,
        instructions=instructions,
        input=user_content,
        max_output_tokens=max_output_tokens,
    )

    result = extract_response_text(
        response
    )

    if not result:
        raise RuntimeError(
            "OpenAI вернул пустой результат."
        )

    return result


def ai_action(
    instructions: str,
    user_content: str,
    *,
    spinner_text: str,
    max_output_tokens: int = 2200,
) -> str | None:
    if not ai.available():
        st.error(
            "OpenAI не подключён. Проверь "
            "OPENAI_API_KEY в Streamlit Secrets."
        )
        return None

    try:
        with st.spinner(
            spinner_text
        ):
            return call_openai(
                instructions,
                user_content,
                max_output_tokens=max_output_tokens,
            )

    except Exception as exc:
        st.error(
            f"Не удалось выполнить запрос: {exc}"
        )
        return None


def selected_job_by_session(
    jobs: list[dict[str, Any]],
) -> dict[str, Any] | None:
    selected_job_id = str(
        st.session_state.get(
            "selected_proposal_job_id",
            "",
        )
    )

    if not selected_job_id:
        return None

    for job in jobs:
        if str(job.get("id", "")) == selected_job_id:
            return job

    return None


def proposal_fallback(
    job: dict[str, Any],
    style: str,
    language: str,
) -> str:
    title = str(
        job.get(
            "title",
            "your project",
        )
    )

    task_type = task_display(job)

    language_names = {
        "English": "English",
        "German": "German",
        "Russian": "Russian",
        "Ukrainian": "Ukrainian",
    }

    selected_language = language_names.get(
        language,
        "English",
    )

    if selected_language == "German":
        return (
            f"Guten Tag,\n\n"
            f"ich habe Ihre Aufgabe „{title}“ gelesen und "
            f"kann Sie dabei zuverlässig unterstützen. "
            f"Ich habe Erfahrung im Bereich {task_type.lower()} "
            f"und arbeite sorgfältig, verständlich und termingerecht.\n\n"
            f"Ich kann kurzfristig beginnen. Vor dem Start würde ich "
            f"gern den genauen Umfang, das gewünschte Format und die "
            f"Abgabefrist bestätigen.\n\n"
            f"Freundliche Grüße\n"
            f"{profile.get('display_name', 'Olha')}"
        )

    if selected_language == "Russian":
        return (
            f"Здравствуйте!\n\n"
            f"Я ознакомилась с заданием «{title}» и могу аккуратно "
            f"выполнить эту работу. У меня есть опыт в категории "
            f"«{task_type}», я внимательно соблюдаю инструкции "
            f"и сроки.\n\n"
            f"Могу начать в ближайшее время. Перед началом предлагаю "
            f"уточнить объём, формат результата и срок сдачи.\n\n"
            f"С уважением,\n"
            f"{profile.get('display_name', 'Olha')}"
        )

    if selected_language == "Ukrainian":
        return (
            f"Вітаю!\n\n"
            f"Я ознайомилася із завданням «{title}» і можу акуратно "
            f"виконати цю роботу. Маю досвід у категорії "
            f"«{task_type}», уважно дотримуюся інструкцій "
            f"і термінів.\n\n"
            f"Можу розпочати найближчим часом. Перед початком варто "
            f"уточнити обсяг, формат результату та кінцевий термін.\n\n"
            f"З повагою,\n"
            f"{profile.get('display_name', 'Olha')}"
        )

    return (
        f"Hello,\n\n"
        f"I reviewed your project “{title}” and I can help you "
        f"complete it carefully and on time. I have relevant "
        f"experience with {task_type.lower()} and I pay close "
        f"attention to instructions, formatting, and quality.\n\n"
        f"I am available to start soon. Before beginning, I would "
        f"like to confirm the exact scope, required format, and deadline.\n\n"
        f"Best regards,\n"
        f"{profile.get('display_name', 'Olha')}"
    )


# ---------------------------------------------------------
# ВКЛАДКА: ОТКЛИК
# ---------------------------------------------------------

with proposal_tab:
    st.subheader("✉️ Создание отклика")

    st.info(
        "Приложение создаёт текст отклика, но не отправляет "
        "его на площадку автоматически."
    )

    session_selected_job = selected_job_by_session(
        all_jobs
    )

    default_job_index = 0

    if session_selected_job:
        for index, job in enumerate(all_jobs):
            if str(job.get("id", "")) == str(
                session_selected_job.get("id", "")
            ):
                default_job_index = index
                break

    if all_jobs:
        selected_proposal_index = st.selectbox(
            "Заказ для отклика",
            options=list(range(len(all_jobs))),
            index=min(
                default_job_index,
                len(all_jobs) - 1,
            ),
            format_func=lambda index: job_option_label(
                all_jobs[index]
            ),
            key="proposal_job_selector",
        )

        proposal_job = all_jobs[
            selected_proposal_index
        ]

        st.session_state[
            "selected_proposal_job_id"
        ] = str(
            proposal_job.get("id", "")
        )

        render_job_card(
            proposal_job,
            expanded_description=False,
            card_key="proposal_selected_job",
        )

        st.divider()

        proposal_settings_1 = st.columns(3)

        with proposal_settings_1[0]:
            proposal_language = st.selectbox(
                "Язык отклика",
                [
                    "English",
                    "German",
                    "Russian",
                    "Ukrainian",
                ],
                index=0,
            )

        with proposal_settings_1[1]:
            proposal_style = st.selectbox(
                "Стиль",
                [
                    "Короткий",
                    "Профессиональный",
                    "Дружелюбный",
                    "Уверенный",
                ],
                index=1,
            )

        with proposal_settings_1[2]:
            proposal_length = st.selectbox(
                "Длина",
                [
                    "Очень короткий",
                    "Обычный",
                    "Подробный",
                ],
                index=1,
            )

        proposal_settings_2 = st.columns(2)

        with proposal_settings_2[0]:
            proposed_price = st.text_input(
                "Предлагаемая цена",
                value=recommended_price(
                    proposal_job
                ),
                help=(
                    "Укажи только число или сумму так, "
                    "как она должна выглядеть в отклике."
                ),
            )

        with proposal_settings_2[1]:
            proposed_deadline = st.text_input(
                "Срок выполнения",
                value=estimated_time(
                    proposal_job
                ),
            )

        relevant_experience = st.text_area(
            "Опыт или важная информация о себе",
            value=(
                "I speak Ukrainian, Russian, German and English. "
                "I work carefully, follow instructions and communicate clearly."
            ),
            height=110,
        )

        extra_proposal_instruction = st.text_area(
            "Дополнительные пожелания",
            placeholder=(
                "Например: не писать слишком официально, "
                "не обещать невозможного, задать один важный вопрос."
            ),
            height=100,
        )

        proposal_buttons = st.columns(
            [1, 1, 1]
        )

        generate_proposal_clicked = proposal_buttons[0].button(
            "✨ Создать отклик",
            type="primary",
            use_container_width=True,
        )

        fallback_proposal_clicked = proposal_buttons[1].button(
            "📝 Создать без ИИ",
            use_container_width=True,
        )

        clear_proposal_clicked = proposal_buttons[2].button(
            "🗑️ Очистить",
            use_container_width=True,
        )

        if clear_proposal_clicked:
            st.session_state.pop(
                "generated_proposal",
                None,
            )
            st.rerun()

        if fallback_proposal_clicked:
            st.session_state[
                "generated_proposal"
            ] = proposal_fallback(
                proposal_job,
                proposal_style,
                proposal_language,
            )

        if generate_proposal_clicked:
            proposal_prompt = f"""
JOB TITLE:
{proposal_job.get("title", "")}

JOB DESCRIPTION:
{proposal_job.get("description", "")[:12000]}

JOB CATEGORY:
{task_display(proposal_job)}

JOB BUDGET:
{budget_display(proposal_job)}

PROPOSED PRICE:
{proposed_price}

PROPOSED DELIVERY TIME:
{proposed_deadline}

FREELANCER NAME:
{profile.get("display_name", "Olha")}

FREELANCER LANGUAGES:
{", ".join(profile.get("languages", []))}

FREELANCER SERVICES:
{", ".join(profile.get("services", []))}

RELEVANT EXPERIENCE:
{relevant_experience}

REQUESTED STYLE:
{proposal_style}

REQUESTED LENGTH:
{proposal_length}

OUTPUT LANGUAGE:
{proposal_language}

EXTRA INSTRUCTIONS:
{extra_proposal_instruction}
"""

            generated_proposal = ai_action(
                instructions=(
                    "Create a realistic freelance proposal for the job. "
                    "Do not invent qualifications, previous clients, ratings, "
                    "certificates, or completed projects. Do not guarantee "
                    "results that cannot be guaranteed. Make the proposal "
                    "specific to the job description. Mention price and "
                    "delivery time only when they are useful. Include no more "
                    "than two relevant questions. Output only the finished "
                    "proposal without analysis, headings, or quotation marks."
                ),
                user_content=proposal_prompt,
                spinner_text="Создаю отклик…",
                max_output_tokens=1400,
            )

            if generated_proposal:
                st.session_state[
                    "generated_proposal"
                ] = generated_proposal

                add_history_entry(
                    "proposal",
                    str(
                        proposal_job.get(
                            "title",
                            "Отклик",
                        )
                    ),
                    generated_proposal,
                    str(
                        proposal_job.get(
                            "id",
                            "",
                        )
                    ),
                )

        generated_proposal_value = str(
            st.session_state.get(
                "generated_proposal",
                "",
            )
        )

        if generated_proposal_value:
            st.divider()
            st.markdown("### Готовый отклик")

            edited_proposal = st.text_area(
                "Текст можно отредактировать",
                value=generated_proposal_value,
                height=320,
                key="proposal_editor",
            )

            proposal_result_buttons = st.columns(3)

            if proposal_result_buttons[0].button(
                "✨ Улучшить текст",
                use_container_width=True,
            ):
                improved_proposal = ai_action(
                    instructions=(
                        "Improve the freelance proposal while preserving "
                        "all true facts. Make it specific, natural, concise, "
                        "and persuasive. Remove repetition and generic filler. "
                        "Do not invent experience or achievements. Output only "
                        "the improved proposal."
                    ),
                    user_content=edited_proposal,
                    spinner_text="Улучшаю отклик…",
                    max_output_tokens=1400,
                )

                if improved_proposal:
                    st.session_state[
                        "generated_proposal"
                    ] = improved_proposal

                    add_history_entry(
                        "proposal_improved",
                        str(
                            proposal_job.get(
                                "title",
                                "Улучшенный отклик",
                            )
                        ),
                        improved_proposal,
                        str(
                            proposal_job.get(
                                "id",
                                "",
                            )
                        ),
                    )

                    st.rerun()

            proposal_result_buttons[1].download_button(
                "⬇️ Скачать TXT",
                data=edited_proposal,
                file_name="proposal.txt",
                mime="text/plain",
                use_container_width=True,
            )

            if proposal_result_buttons[2].button(
                "💾 Сохранить в историю",
                use_container_width=True,
            ):
                if add_history_entry(
                    "proposal_saved",
                    str(
                        proposal_job.get(
                            "title",
                            "Отклик",
                        )
                    ),
                    edited_proposal,
                    str(
                        proposal_job.get(
                            "id",
                            "",
                        )
                    ),
                ):
                    st.success(
                        "Отклик сохранён в историю."
                    )
                else:
                    st.error(
                        "Не удалось сохранить историю."
                    )

            st.caption(
                "Для копирования нажми внутри поля, затем "
                "используй стандартную команду копирования."
            )

    else:
        st.info(
            "В базе пока нет заказов. Добавь объявление "
            "вручную во вкладке «Заказы»."
        )


# ---------------------------------------------------------
# ВКЛАДКА: ПЕРЕПИСКА
# ---------------------------------------------------------

with chat_tab:
    st.subheader("💬 Помощник для переписки")

    chat_columns = st.columns(
        [1.2, 1]
    )

    with chat_columns[0]:
        client_message = st.text_area(
            "Сообщение клиента",
            height=240,
            placeholder=(
                "Вставь сюда сообщение, которое прислал клиент."
            ),
        )

        reply_context = st.text_area(
            "Что ты хочешь ответить",
            height=140,
            placeholder=(
                "Например: я могу закончить завтра вечером, "
                "но мне нужен исходный файл в DOCX."
            ),
        )

    with chat_columns[1]:
        reply_language = st.selectbox(
            "Язык ответа",
            [
                "English",
                "German",
                "Russian",
                "Ukrainian",
            ],
            key="chat_reply_language",
        )

        reply_tone = st.selectbox(
            "Тон ответа",
            [
                "Вежливый",
                "Дружелюбный",
                "Профессиональный",
                "Короткий и прямой",
            ],
        )

        reply_goal = st.selectbox(
            "Цель",
            [
                "Ответить на сообщение",
                "Уточнить детали",
                "Согласовать цену",
                "Согласовать срок",
                "Вежливо отказаться",
                "Сообщить о готовности работы",
            ],
        )

        include_translation = st.checkbox(
            "Показать перевод сообщения клиента на русский",
            value=True,
        )

    chat_action_columns = st.columns(3)

    generate_reply_clicked = chat_action_columns[0].button(
        "✨ Создать ответ",
        type="primary",
        use_container_width=True,
    )

    translate_only_clicked = chat_action_columns[1].button(
        "🌍 Только перевести",
        use_container_width=True,
    )

    clear_chat_clicked = chat_action_columns[2].button(
        "🗑️ Очистить результат",
        use_container_width=True,
    )

    if clear_chat_clicked:
        st.session_state.pop(
            "chat_result",
            None,
        )
        st.session_state.pop(
            "chat_translation",
            None,
        )
        st.rerun()

    if translate_only_clicked:
        if not client_message.strip():
            st.warning(
                "Сначала вставь сообщение клиента."
            )
        else:
            translated_message = ai_action(
                instructions=(
                    "Translate the supplied message into Russian. "
                    "Preserve meaning, prices, dates, names, and formatting. "
                    "Do not add explanations. Output only the translation."
                ),
                user_content=client_message,
                spinner_text="Перевожу сообщение…",
                max_output_tokens=1600,
            )

            if translated_message:
                st.session_state[
                    "chat_translation"
                ] = translated_message

    if generate_reply_clicked:
        if not client_message.strip():
            st.warning(
                "Сначала вставь сообщение клиента."
            )

        elif not reply_context.strip():
            st.warning(
                "Коротко напиши, что именно ты хочешь ответить."
            )

        else:
            chat_prompt = f"""
CLIENT MESSAGE:
{client_message}

WHAT I WANT TO SAY:
{reply_context}

REPLY LANGUAGE:
{reply_language}

TONE:
{reply_tone}

GOAL:
{reply_goal}

FREELANCER NAME:
{profile.get("display_name", "Olha")}
"""

            generated_reply = ai_action(
                instructions=(
                    "Write a natural message to a freelance client. "
                    "Use only the facts provided by the user. Do not invent "
                    "completed work, deadlines, prices, attachments, or "
                    "agreements. Keep the reply clear and appropriate for "
                    "professional communication. Output only the message."
                ),
                user_content=chat_prompt,
                spinner_text="Готовлю ответ клиенту…",
                max_output_tokens=1200,
            )

            if generated_reply:
                st.session_state[
                    "chat_result"
                ] = generated_reply

                add_history_entry(
                    "client_reply",
                    "Ответ клиенту",
                    generated_reply,
                )

            if include_translation:
                translated_message = ai_action(
                    instructions=(
                        "Translate the supplied client message into Russian. "
                        "Preserve its meaning and details. Output only the "
                        "translation."
                    ),
                    user_content=client_message,
                    spinner_text="Перевожу сообщение клиента…",
                    max_output_tokens=1400,
                )

                if translated_message:
                    st.session_state[
                        "chat_translation"
                    ] = translated_message

    saved_translation = str(
        st.session_state.get(
            "chat_translation",
            "",
        )
    )

    saved_reply = str(
        st.session_state.get(
            "chat_result",
            "",
        )
    )

    if saved_translation:
        st.divider()
        st.markdown("### Перевод сообщения клиента")

        st.text_area(
            "Перевод",
            value=saved_translation,
            height=180,
            key="chat_translation_editor",
        )

    if saved_reply:
        st.markdown("### Готовый ответ")

        edited_reply = st.text_area(
            "Ответ можно отредактировать",
            value=saved_reply,
            height=220,
            key="chat_reply_editor",
        )

        reply_download_columns = st.columns(2)

        reply_download_columns[0].download_button(
            "⬇️ Скачать ответ",
            data=edited_reply,
            file_name="client_reply.txt",
            mime="text/plain",
            use_container_width=True,
        )

        if reply_download_columns[1].button(
            "💾 Сохранить ответ",
            use_container_width=True,
        ):
            if add_history_entry(
                "client_reply_saved",
                "Сохранённый ответ клиенту",
                edited_reply,
            ):
                st.success(
                    "Ответ сохранён в историю."
                )


# ---------------------------------------------------------
# ВКЛАДКА: РАБОТА
# ---------------------------------------------------------

with work_tab:
    st.subheader("💼 Выполнение текстового задания")

    st.warning(
        "Перед отправкой клиенту обязательно проверь результат. "
        "ИИ может неправильно понять инструкцию, числа или термины."
    )

    work_mode = st.selectbox(
        "Что нужно сделать",
        [
            "Выполнить задание по инструкции",
            "Перевести текст",
            "Проверить и исправить текст",
            "Сделать краткое содержание",
            "Переписать более профессионально",
            "Извлечь данные в таблицу",
            "Проверить готовый результат",
        ],
    )

    uploaded_files = st.file_uploader(
        "Загрузить файлы",
        type=[
            "txt",
            "md",
            "csv",
            "json",
            "docx",
            "pdf",
        ],
        accept_multiple_files=True,
        help=(
            "Поддерживаются TXT, MD, CSV, JSON, DOCX и PDF "
            "с обычным текстовым слоем."
        ),
    )

    extracted_file_text, file_messages = extract_uploaded_files(
        uploaded_files
    )

    for message in file_messages:
        if message.startswith("✅"):
            st.success(message)
        elif message.startswith("❌"):
            st.error(message)
        else:
            st.warning(message)

    work_instruction = st.text_area(
        "Инструкция клиента",
        height=180,
        placeholder=(
            "Вставь полное задание клиента. Например: "
            "перевести текст на немецкий, сохранить структуру "
            "и не переводить названия брендов."
        ),
    )

    manual_work_text = st.text_area(
        "Исходный текст",
        height=260,
        placeholder=(
            "Можно вставить текст вручную или загрузить файл выше."
        ),
    )

    combined_work_input = "\n\n".join(
        part
        for part in [
            manual_work_text.strip(),
            extracted_file_text.strip(),
        ]
        if part
    )

    work_options = st.columns(3)

    with work_options[0]:
        work_output_language = st.selectbox(
            "Язык результата",
            [
                "Согласно инструкции",
                "English",
                "German",
                "Russian",
                "Ukrainian",
            ],
        )

    with work_options[1]:
        work_quality = st.selectbox(
            "Уровень обработки",
            [
                "Обычный",
                "Тщательный",
                "Максимально тщательный",
            ],
            index=1,
        )

    with work_options[2]:
        preserve_formatting = st.checkbox(
            "Сохранять структуру",
            value=True,
        )

    additional_work_rules = st.text_area(
        "Дополнительные правила",
        placeholder=(
            "Например: не изменять числа, названия компаний, "
            "ссылки и медицинские термины."
        ),
        height=100,
    )

    work_buttons = st.columns(3)

    perform_work_clicked = work_buttons[0].button(
        "🤖 Выполнить",
        type="primary",
        use_container_width=True,
    )

    check_work_clicked = work_buttons[1].button(
        "🔍 Проверить результат",
        use_container_width=True,
    )

    clear_work_clicked = work_buttons[2].button(
        "🗑️ Очистить результат",
        use_container_width=True,
    )

    if clear_work_clicked:
        st.session_state.pop(
            "work_result",
            None,
        )
        st.session_state.pop(
            "quality_report",
            None,
        )
        st.rerun()

    if perform_work_clicked:
        if not work_instruction.strip():
            st.warning(
                "Добавь инструкцию клиента."
            )

        elif not combined_work_input.strip():
            st.warning(
                "Добавь исходный текст или загрузи файл."
            )

        else:
            work_prompt = f"""
TASK TYPE:
{work_mode}

CLIENT INSTRUCTIONS:
{work_instruction}

REQUESTED OUTPUT LANGUAGE:
{work_output_language}

QUALITY LEVEL:
{work_quality}

PRESERVE STRUCTURE:
{preserve_formatting}

ADDITIONAL RULES:
{additional_work_rules}

SOURCE CONTENT:
{combined_work_input[:85000]}
"""

            completed_work = ai_action(
                instructions=(
                    "Complete the supplied text-based freelance task. "
                    "Follow the client's instructions exactly. Do not invent "
                    "missing information. Preserve numbers, names, links, "
                    "technical terms, and document structure unless the user "
                    "explicitly asks to change them. If essential information "
                    "is missing, clearly mark what could not be completed "
                    "instead of guessing. Output only the finished deliverable."
                ),
                user_content=work_prompt,
                spinner_text="Выполняю задание…",
                max_output_tokens=5000,
            )

            if completed_work:
                st.session_state[
                    "work_result"
                ] = completed_work

                add_history_entry(
                    "completed_work",
                    work_mode,
                    completed_work,
                )

    current_work_result = str(
        st.session_state.get(
            "work_result",
            "",
        )
    )

    if check_work_clicked:
        if not current_work_result.strip():
            st.warning(
                "Сначала выполни задание или вставь результат."
            )
        else:
            quality_prompt = f"""
CLIENT INSTRUCTIONS:
{work_instruction}

SOURCE CONTENT:
{combined_work_input[:45000]}

RESULT TO CHECK:
{current_work_result[:45000]}
"""

            quality_report = ai_action(
                instructions=(
                    "Act as a quality-control reviewer. Compare the result "
                    "against the client instructions and source content. "
                    "Check for missing information, invented facts, changed "
                    "numbers, incorrect names, translation errors, formatting "
                    "problems, and unclear wording. Respond in Russian. "
                    "Provide: 1) overall verdict, 2) specific issues, "
                    "3) corrected version only when corrections are needed. "
                    "Be precise and do not claim certainty when source "
                    "information is insufficient."
                ),
                user_content=quality_prompt,
                spinner_text="Проверяю качество…",
                max_output_tokens=4000,
            )

            if quality_report:
                st.session_state[
                    "quality_report"
                ] = quality_report

                add_history_entry(
                    "quality_check",
                    "Проверка выполненной работы",
                    quality_report,
                )

    current_work_result = str(
        st.session_state.get(
            "work_result",
            "",
        )
    )

    if current_work_result:
        st.divider()
        st.markdown("### Готовый результат")

        edited_work_result = st.text_area(
            "Проверь и при необходимости отредактируй",
            value=current_work_result,
            height=480,
            key="work_result_editor",
        )

        work_result_actions = st.columns(3)

        if work_result_actions[0].button(
            "✨ Исправить и улучшить",
            use_container_width=True,
        ):
            improved_work = ai_action(
                instructions=(
                    "Improve and correct the supplied work result according "
                    "to the client instructions. Preserve correct content, "
                    "facts, numbers, names, and formatting. Fix only genuine "
                    "issues. Do not add invented information. Output only the "
                    "final corrected deliverable."
                ),
                user_content=(
                    f"CLIENT INSTRUCTIONS:\n{work_instruction}\n\n"
                    f"RESULT:\n{edited_work_result}"
                ),
                spinner_text="Исправляю результат…",
                max_output_tokens=5000,
            )

            if improved_work:
                st.session_state[
                    "work_result"
                ] = improved_work
                st.rerun()

        work_result_actions[1].download_button(
            "⬇️ Скачать TXT",
            data=edited_work_result,
            file_name="completed_work.txt",
            mime="text/plain",
            use_container_width=True,
        )

        if work_result_actions[2].button(
            "💾 Сохранить в историю",
            use_container_width=True,
        ):
            if add_history_entry(
                "completed_work_saved",
                work_mode,
                edited_work_result,
            ):
                st.success(
                    "Результат сохранён."
                )

    quality_report_value = str(
        st.session_state.get(
            "quality_report",
            "",
        )
    )

    if quality_report_value:
        st.divider()
        st.markdown("### 🔍 Отчёт о проверке")

        st.text_area(
            "Результат проверки",
            value=quality_report_value,
            height=380,
            key="quality_report_editor",
        )
        # ---------------------------------------------------------
# ВКЛАДКА: ИСТОРИЯ
# ---------------------------------------------------------

with history_tab:
    st.subheader("📚 История работы")

    current_history = get_history()

    if not current_history:
        st.info(
            "История пока пустая. Здесь появятся созданные отклики, "
            "ответы клиентам, выполненные задания и проверки качества."
        )

    else:
        history_statistics = st.columns(4)

        history_statistics[0].metric(
            "Всего записей",
            len(current_history),
        )

        history_statistics[1].metric(
            "Отклики",
            sum(
                str(item.get("type", "")).startswith("proposal")
                for item in current_history
            ),
        )

        history_statistics[2].metric(
            "Выполненные работы",
            sum(
                str(item.get("type", "")).startswith("completed_work")
                for item in current_history
            ),
        )

        history_statistics[3].metric(
            "Ответы клиентам",
            sum(
                str(item.get("type", "")).startswith("client_reply")
                for item in current_history
            ),
        )

        st.divider()

        history_filter_columns = st.columns(
            [1.2, 1.2, 1]
        )

        with history_filter_columns[0]:
            history_type_filter = st.selectbox(
                "Тип записи",
                [
                    "Все",
                    "Отклики",
                    "Ответы клиентам",
                    "Выполненные работы",
                    "Проверки качества",
                    "Другое",
                ],
                key="history_type_filter",
            )

        with history_filter_columns[1]:
            history_search = st.text_input(
                "Поиск в истории",
                placeholder="Название или текст",
                key="history_search",
            ).strip().lower()

        with history_filter_columns[2]:
            history_limit = st.selectbox(
                "Показывать записей",
                [
                    20,
                    50,
                    100,
                    300,
                ],
                index=1,
                key="history_limit",
            )

        def history_category(
            history_item: dict[str, Any],
        ) -> str:
            item_type = str(
                history_item.get("type", "")
            )

            if item_type.startswith("proposal"):
                return "Отклики"

            if item_type.startswith("client_reply"):
                return "Ответы клиентам"

            if item_type.startswith("completed_work"):
                return "Выполненные работы"

            if item_type.startswith("quality"):
                return "Проверки качества"

            return "Другое"

        filtered_history: list[dict[str, Any]] = []

        for history_item in current_history:
            item_category = history_category(
                history_item
            )

            if (
                history_type_filter != "Все"
                and item_category != history_type_filter
            ):
                continue

            if history_search:
                history_searchable_text = (
                    f"{history_item.get('title', '')} "
                    f"{history_item.get('content', '')} "
                    f"{history_item.get('type', '')}"
                ).lower()

                if history_search not in history_searchable_text:
                    continue

            filtered_history.append(
                history_item
            )

        filtered_history = filtered_history[
            :history_limit
        ]

        st.caption(
            f"Показано записей: {len(filtered_history)}"
        )

        history_export_data = json.dumps(
            current_history,
            ensure_ascii=False,
            indent=2,
        )

        export_columns = st.columns(
            [1, 1, 2]
        )

        export_columns[0].download_button(
            "⬇️ Скачать историю JSON",
            data=history_export_data,
            file_name="freelance_agent_history.json",
            mime="application/json",
            use_container_width=True,
        )

        history_csv_buffer = io.StringIO()

        history_csv_writer = csv.writer(
            history_csv_buffer
        )

        history_csv_writer.writerow(
            [
                "Дата",
                "Тип",
                "Название",
                "Содержание",
                "ID заказа",
            ]
        )

        for history_item in current_history:
            history_csv_writer.writerow(
                [
                    history_item.get(
                        "created_at",
                        "",
                    ),
                    history_item.get(
                        "type",
                        "",
                    ),
                    history_item.get(
                        "title",
                        "",
                    ),
                    history_item.get(
                        "content",
                        "",
                    ),
                    history_item.get(
                        "job_id",
                        "",
                    ),
                ]
            )

        export_columns[1].download_button(
            "⬇️ Скачать историю CSV",
            data=history_csv_buffer.getvalue(),
            file_name="freelance_agent_history.csv",
            mime="text/csv",
            use_container_width=True,
        )

        if export_columns[2].button(
            "🗑️ Очистить всю историю",
            use_container_width=True,
        ):
            st.session_state[
                "confirm_clear_history"
            ] = True

        if st.session_state.get(
            "confirm_clear_history",
            False,
        ):
            st.warning(
                "Все записи истории будут удалены без возможности "
                "восстановления."
            )

            confirm_history_columns = st.columns(
                [1, 1, 2]
            )

            if confirm_history_columns[0].button(
                "Да, удалить",
                type="primary",
                use_container_width=True,
                key="confirm_clear_history_yes",
            ):
                if save_json(
                    HISTORY_PATH,
                    [],
                ):
                    st.session_state[
                        "confirm_clear_history"
                    ] = False

                    st.success(
                        "История очищена."
                    )

                    st.rerun()

                else:
                    st.error(
                        "Не удалось очистить историю."
                    )

            if confirm_history_columns[1].button(
                "Отмена",
                use_container_width=True,
                key="confirm_clear_history_no",
            ):
                st.session_state[
                    "confirm_clear_history"
                ] = False

                st.rerun()

        st.divider()

        history_type_labels = {
            "proposal": "✉️ Отклик",
            "proposal_saved": "💾 Сохранённый отклик",
            "proposal_improved": "✨ Улучшенный отклик",
            "client_reply": "💬 Ответ клиенту",
            "client_reply_saved": "💾 Сохранённый ответ",
            "completed_work": "💼 Выполненная работа",
            "completed_work_saved": "💾 Сохранённая работа",
            "quality_check": "🔍 Проверка качества",
        }

        for history_index, history_item in enumerate(
            filtered_history
        ):
            history_item_id = str(
                history_item.get(
                    "id",
                    history_index,
                )
            )

            history_item_type = str(
                history_item.get(
                    "type",
                    "other",
                )
            )

            history_item_title = str(
                history_item.get(
                    "title",
                    "Без названия",
                )
            )

            history_item_content = str(
                history_item.get(
                    "content",
                    "",
                )
            )

            history_item_created = str(
                history_item.get(
                    "created_at",
                    "",
                )
            )

            history_item_label = history_type_labels.get(
                history_item_type,
                "📄 Запись",
            )

            expander_title = (
                f"{history_item_label} · "
                f"{history_item_title[:90]}"
            )

            with st.expander(
                expander_title,
                expanded=False,
            ):
                st.caption(
                    f"Создано: {history_item_created or 'Неизвестно'}"
                )

                if history_item.get("job_id"):
                    st.caption(
                        f"ID заказа: {history_item.get('job_id')}"
                    )

                edited_history_content = st.text_area(
                    "Содержание",
                    value=history_item_content,
                    height=280,
                    key=(
                        f"history_content_"
                        f"{history_index}_"
                        f"{history_item_id}"
                    ),
                )

                history_item_actions = st.columns(
                    [1, 1, 1]
                )

                history_item_actions[0].download_button(
                    "⬇️ Скачать TXT",
                    data=edited_history_content,
                    file_name=(
                        f"history_{history_index + 1}.txt"
                    ),
                    mime="text/plain",
                    use_container_width=True,
                    key=(
                        f"history_download_"
                        f"{history_index}_"
                        f"{history_item_id}"
                    ),
                )

                if history_item_actions[1].button(
                    "💾 Сохранить изменения",
                    use_container_width=True,
                    key=(
                        f"history_save_"
                        f"{history_index}_"
                        f"{history_item_id}"
                    ),
                ):
                    complete_history = get_history()
                    history_updated = False

                    for complete_item in complete_history:
                        if str(
                            complete_item.get(
                                "id",
                                "",
                            )
                        ) == history_item_id:
                            complete_item[
                                "content"
                            ] = edited_history_content

                            complete_item[
                                "updated_at"
                            ] = utc_now()

                            history_updated = True
                            break

                    if history_updated and save_json(
                        HISTORY_PATH,
                        complete_history,
                    ):
                        st.success(
                            "Изменения сохранены."
                        )

                    else:
                        st.error(
                            "Не удалось сохранить изменения."
                        )

                if history_item_actions[2].button(
                    "🗑️ Удалить запись",
                    use_container_width=True,
                    key=(
                        f"history_delete_"
                        f"{history_index}_"
                        f"{history_item_id}"
                    ),
                ):
                    complete_history = get_history()

                    new_history = [
                        item
                        for item in complete_history
                        if str(
                            item.get(
                                "id",
                                "",
                            )
                        ) != history_item_id
                    ]

                    if save_json(
                        HISTORY_PATH,
                        new_history,
                    ):
                        st.success(
                            "Запись удалена."
                        )

                        st.rerun()

                    else:
                        st.error(
                            "Не удалось удалить запись."
                        )


# ---------------------------------------------------------
# ВКЛАДКА: ДИАГНОСТИКА
# ---------------------------------------------------------

with diagnostics_tab:
    st.subheader("⚙️ Диагностика приложения")

    st.caption(
        "Здесь можно проверить подключение OpenAI, файлы проекта, "
        "источники заданий и основные настройки."
    )

    diagnostic_openai_key = get_openai_secret(
        "OPENAI_API_KEY"
    )

    diagnostic_openai_model = get_openai_secret(
        "OPENAI_MODEL",
        "gpt-5-mini",
    )

    diagnostic_columns = st.columns(4)

    diagnostic_columns[0].metric(
        "OpenAI API",
        (
            "Подключён"
            if ai.available()
            else "Не подключён"
        ),
    )

    diagnostic_columns[1].metric(
        "API-ключ",
        (
            "Найден"
            if diagnostic_openai_key
            else "Не найден"
        ),
    )

    diagnostic_columns[2].metric(
        "Модель",
        diagnostic_openai_model,
    )

    diagnostic_columns[3].metric(
        "Заданий в базе",
        len(repo_jobs),
    )

    st.divider()

    diagnostic_section_1, diagnostic_section_2 = st.columns(
        2
    )

    with diagnostic_section_1:
        st.markdown("### 🤖 OpenAI")

        if ai.available():
            st.success(
                "Модуль ИИ сообщает, что OpenAI доступен."
            )
        else:
            st.error(
                "OpenAI недоступен. Проверь Streamlit Secrets "
                "и файл requirements.txt."
            )

        if diagnostic_openai_key:
            masked_key = (
                diagnostic_openai_key[:7]
                + "..."
                + diagnostic_openai_key[-4:]
                if len(diagnostic_openai_key) >= 15
                else "Ключ найден"
            )

            st.code(
                f"OPENAI_API_KEY = {masked_key}"
            )
        else:
            st.code(
                "OPENAI_API_KEY = не найден"
            )

        st.code(
            f"OPENAI_MODEL = {diagnostic_openai_model}"
        )

        if st.button(
            "🧪 Проверить запрос к OpenAI",
            type="primary",
            use_container_width=True,
            key="test_openai_connection",
        ):
            test_result = ai_action(
                instructions=(
                    "Answer in Russian with one short sentence. "
                    "Confirm that the API request works. "
                    "Do not add headings or explanations."
                ),
                user_content=(
                    "Проверка подключения приложения к OpenAI."
                ),
                spinner_text="Проверяю OpenAI…",
                max_output_tokens=100,
            )

            if test_result:
                st.success(
                    "Запрос выполнен успешно."
                )

                st.code(
                    test_result
                )

    with diagnostic_section_2:
        st.markdown("### 📁 Файлы проекта")

        required_files = {
            "app.py": ROOT / "app.py",
            "ai.py": ROOT / "ai.py",
            "scanner.py": ROOT / "scanner.py",
            "config.json": CONFIG_PATH,
            "jobs.json": JOBS_PATH,
            "scan_status.json": STATUS_PATH,
            "requirements.txt": ROOT / "requirements.txt",
        }

        optional_files = {
            "favorites.json": FAVORITES_PATH,
            "history.json": HISTORY_PATH,
        }

        for file_name, file_path in required_files.items():
            if file_path.exists():
                file_size = file_path.stat().st_size

                st.success(
                    f"{file_name}: найден, {file_size} байт"
                )
            else:
                st.error(
                    f"{file_name}: отсутствует"
                )

        for file_name, file_path in optional_files.items():
            if file_path.exists():
                file_size = file_path.stat().st_size

                st.success(
                    f"{file_name}: найден, {file_size} байт"
                )
            else:
                st.info(
                    f"{file_name}: будет создан автоматически "
                    "при первом сохранении"
                )

    st.divider()

    diagnostic_section_3, diagnostic_section_4 = st.columns(
        2
    )

    with diagnostic_section_3:
        st.markdown("### 🌐 Источники заказов")

        configured_sources = cfg.get(
            "sources",
            [],
        )

        if not isinstance(
            configured_sources,
            list,
        ):
            configured_sources = []

        if not configured_sources:
            st.warning(
                "В config.json не найдены источники."
            )

        for source_index, source in enumerate(
            configured_sources
        ):
            if not isinstance(source, dict):
                continue

            source_name = str(
                source.get(
                    "name",
                    source.get(
                        "id",
                        f"Источник {source_index + 1}",
                    ),
                )
            )

            source_enabled = bool(
                source.get(
                    "enabled",
                    False,
                )
            )

            source_status_icon = (
                "✅"
                if source_enabled
                else "⏸️"
            )

            st.write(
                f"{source_status_icon} **{source_name}**"
            )

            source_type = source.get(
                "type",
                source.get(
                    "id",
                    "",
                ),
            )

            if source_type:
                st.caption(
                    f"Тип: {source_type}"
                )

            if source.get("url"):
                st.caption(
                    f"Адрес: {source.get('url')}"
                )

        if scan_status:
            with st.expander(
                "Последний отчёт сканера",
                expanded=False,
            ):
                st.json(
                    scan_status
                )

    with diagnostic_section_4:
        st.markdown("### 👤 Профиль")

        profile_display_name = str(
            profile.get(
                "display_name",
                "Не указано",
            )
        )

        profile_languages = profile.get(
            "languages",
            [],
        )

        profile_services = profile.get(
            "services",
            [],
        )

        st.write(
            f"**Имя:** {profile_display_name}"
        )

        if isinstance(
            profile_languages,
            list,
        ):
            st.write(
                "**Языки:** "
                + ", ".join(
                    str(language)
                    for language in profile_languages
                )
            )

        if isinstance(
            profile_services,
            list,
        ):
            st.write(
                "**Услуги:**"
            )

            for service in profile_services:
                st.write(
                    f"• {service}"
                )

        st.write(
            f"**Минимальная цена:** "
            f"{profile.get('minimum_price_eur', '—')} €"
        )

        st.write(
            f"**Предпочтительная цена:** "
            f"{profile.get('preferred_price_eur', '—')} €"
        )

        st.write(
            f"**Часовой пояс:** "
            f"{profile.get('timezone', '—')}"
        )

    st.divider()
    st.markdown("### 📦 Проверка библиотек")

    library_checks: dict[str, tuple[str, bool]] = {}

    try:
        import openai as openai_library

        library_checks["openai"] = (
            str(
                getattr(
                    openai_library,
                    "__version__",
                    "установлена",
                )
            ),
            True,
        )
    except Exception:
        library_checks["openai"] = (
            "не установлена",
            False,
        )

    try:
        import streamlit as streamlit_library

        library_checks["streamlit"] = (
            str(
                getattr(
                    streamlit_library,
                    "__version__",
                    "установлена",
                )
            ),
            True,
        )
    except Exception:
        library_checks["streamlit"] = (
            "не установлена",
            False,
        )

    try:
        import docx as docx_library

        library_checks["python-docx"] = (
            str(
                getattr(
                    docx_library,
                    "__version__",
                    "установлена",
                )
            ),
            True,
        )
    except Exception:
        library_checks["python-docx"] = (
            "не установлена",
            False,
        )

    try:
        import pypdf as pypdf_library

        library_checks["pypdf"] = (
            str(
                getattr(
                    pypdf_library,
                    "__version__",
                    "установлена",
                )
            ),
            True,
        )
    except Exception:
        library_checks["pypdf"] = (
            "не установлена",
            False,
        )

    library_columns = st.columns(
        len(library_checks)
    )

    for library_index, (
        library_name,
        library_information,
    ) in enumerate(
        library_checks.items()
    ):
        library_version, library_available = (
            library_information
        )

        library_columns[
            library_index
        ].metric(
            library_name,
            (
                library_version
                if library_available
                else "Отсутствует"
            ),
        )

    missing_libraries = [
        library_name
        for library_name, (
            _,
            library_available,
        ) in library_checks.items()
        if not library_available
    ]

    if missing_libraries:
        st.warning(
            "Не установлены библиотеки: "
            + ", ".join(missing_libraries)
        )
    else:
        st.success(
            "Все основные библиотеки установлены."
        )

    with st.expander(
        "Показать рекомендуемый requirements.txt",
        expanded=False,
    ):
        st.code(
            """streamlit>=1.36.0
openai>=1.0.0
python-docx>=1.1.0
pypdf>=4.0.0
feedparser>=6.0.11
requests>=2.31.0
""",
            language="text",
        )

    st.divider()
    st.markdown("### 🧹 Служебные действия")

    service_action_columns = st.columns(3)

    if service_action_columns[0].button(
        "Создать пустой favorites.json",
        use_container_width=True,
    ):
        if save_json(
            FAVORITES_PATH,
            get_favorites(),
        ):
            st.success(
                "favorites.json готов."
            )

    if service_action_columns[1].button(
        "Создать пустой history.json",
        use_container_width=True,
    ):
        if save_json(
            HISTORY_PATH,
            get_history(),
        ):
            st.success(
                "history.json готов."
            )

    if service_action_columns[2].button(
        "Перезагрузить приложение",
        use_container_width=True,
    ):
        st.rerun()


# ---------------------------------------------------------
# НИЖНЯЯ ЧАСТЬ СТРАНИЦЫ
# ---------------------------------------------------------

st.divider()

st.caption(
    "Фриланс-Агент помогает искать задания, создавать отклики, "
    "работать с текстами и проверять результат. Перед отправкой "
    "заказчику всегда самостоятельно проверяй готовую работу."
)
            
