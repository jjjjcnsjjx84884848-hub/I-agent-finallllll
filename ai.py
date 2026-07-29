from __future__ import annotations

import json
import os
import re
from typing import Any

try:
    import streamlit as st
except Exception:  # pragma: no cover
    st = None

try:
    from openai import OpenAI
except Exception:  # pragma: no cover
    OpenAI = None


DEFAULT_MODEL = "gpt-5-mini"


def get_secret(name: str, default: str = "") -> str:
    """Получает секрет сначала из переменных окружения, затем из Streamlit Secrets."""
    env_value = os.getenv(name)

    if env_value:
        return env_value

    if st is not None:
        try:
            value = st.secrets.get(name, default)
            return str(value) if value is not None else default
        except Exception:
            pass

    return default


def available() -> bool:
    """Проверяет, установлен ли OpenAI и добавлен ли API-ключ."""
    return OpenAI is not None and bool(get_secret("OPENAI_API_KEY"))


def _client() -> Any:
    """Создаёт клиент OpenAI."""
    if OpenAI is None:
        raise RuntimeError(
            "Пакет openai не установлен. Добавьте openai в requirements.txt."
        )

    api_key = get_secret("OPENAI_API_KEY")

    if not api_key:
        raise RuntimeError(
            "OPENAI_API_KEY не настроен в Streamlit Secrets."
        )

    return OpenAI(api_key=api_key)


def _generate(prompt: str, *, temperature: float = 0.3) -> str:
    """
    Отправляет запрос в OpenAI.

    Аргумент temperature сохранён для совместимости с остальным кодом,
    но в запрос не передаётся, чтобы избежать проблем с моделями,
    которые могут не поддерживать его.
    """
    model = get_secret("OPENAI_MODEL", DEFAULT_MODEL)

    try:
        response = _client().responses.create(
            model=model,
            input=prompt,
        )
    except Exception as exc:
        raise RuntimeError(f"Ошибка OpenAI API: {exc}") from exc

    text = getattr(response, "output_text", None)

    if not text:
        raise RuntimeError("OpenAI вернул пустой ответ.")

    return text.strip()


def _extract_json(text: str) -> dict[str, Any]:
    """Извлекает JSON-объект из ответа модели."""
    cleaned = text.strip()

    fenced = re.search(
        r"```(?:json)?\s*(\{.*?\})\s*```",
        cleaned,
        flags=re.S,
    )

    if fenced:
        cleaned = fenced.group(1)
    else:
        start = cleaned.find("{")
        end = cleaned.rfind("}")

        if start >= 0 and end > start:
            cleaned = cleaned[start : end + 1]

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"ИИ вернул некорректный JSON: {cleaned[:500]}"
        ) from exc

    if not isinstance(data, dict):
        raise ValueError("Ожидался JSON-объект.")

    return data


def analyze_job(
    job: dict[str, Any],
    profile: dict[str, Any],
) -> dict[str, Any]:
    prompt = f"""
Ты — осторожный помощник фрилансера.

Проанализируй объявление без выдумывания опыта, навыков или квалификаций.

Профиль пользователя:
{json.dumps(profile, ensure_ascii=False)}

Объявление:
{json.dumps(job, ensure_ascii=False)}

Верни ТОЛЬКО корректный JSON без дополнительного текста:

{{
  "fit_score": 0,
  "recommended": false,
  "detected_language": "язык",
  "task_type": "тип задачи",
  "estimated_minutes": 0,
  "suggested_price_eur": 0,
  "deadline_assessment": "краткая оценка",
  "missing_information": ["что нужно уточнить"],
  "risks": ["возможный риск"],
  "reason": "краткое объяснение"
}}

Требования:
- fit_score должен быть числом от 0 до 100;
- recommended должен быть true или false;
- не предлагай обход правил площадки;
- не предлагай обход проверки личности или возраста;
- не выдумывай опыт пользователя;
- отмечай подозрительные способы оплаты и возможное мошенничество.
"""

    result = _generate(prompt, temperature=0.15)
    return _extract_json(result)


def create_proposal(
    job: dict[str, Any],
    profile: dict[str, Any],
    analysis: dict[str, Any],
    preferences: str = "",
) -> str:
    prompt = f"""
Напиши короткий персональный отклик на объявление.

Отвечай на языке объявления.

Не утверждай, что у исполнителя есть навыки, опыт или квалификация,
если этого нет в профиле.

Не обещай невозможное.
Не упоминай использование ИИ.
Не соглашайся на оплату в обход правил площадки.

Профиль:
{json.dumps(profile, ensure_ascii=False)}

Объявление:
{json.dumps(job, ensure_ascii=False)}

Результат анализа:
{json.dumps(analysis, ensure_ascii=False)}

Дополнительные пожелания пользователя:
{preferences}

Структура отклика:
1. Приветствие.
2. Краткое понимание задачи.
3. Что именно исполнитель сможет сделать.
4. Срок и цена — только если они обоснованы.
5. Один или два уточняющих вопроса.
6. Вежливое завершение.

Верни только готовый текст отклика.
"""

    return _generate(prompt, temperature=0.35)


def create_reply(
    history: str,
    incoming: str,
    facts: str,
    preferred_language: str = "auto",
) -> str:
    prompt = f"""
Подготовь ответ клиенту от имени исполнителя.

Язык ответа: {preferred_language}.
Если указано auto, используй язык последнего сообщения клиента.

Сохраняй уже согласованные:
- цену;
- срок;
- объём работы;
- формат результата.

Не выдумывай факты и не меняй условия самостоятельно.

Если клиент просит:
- отправить личные документы без необходимости;
- внести предоплату от имени исполнителя;
- купить подарочные карты;
- предоставить доступ к банковскому счёту;
- перейти на подозрительную оплату;
- обойти правила площадки;

вежливо откажись и предложи использовать безопасный способ через площадку.

Согласованные факты:
{facts}

История переписки:
{history}

Новое сообщение клиента:
{incoming}

Верни только готовое сообщение клиенту.
"""

    return _generate(prompt, temperature=0.25)


def fulfill_order(
    task: str,
    materials: str,
    requirements: str,
    output_language: str = "auto",
) -> str:
    prompt = f"""
Выполни легитимное текстовое или документное задание
на основе материалов клиента.

Не выдумывай отсутствующие:
- имена;
- даты;
- квалификации;
- источники;
- результаты;
- цифры.

Если критически не хватает информации,
создай максимально полезный черновик и в конце добавь раздел:

Нужно уточнить

Не выполняй мошеннические, опасные или запрещённые задания.

Язык результата:
{output_language}

Задача:
{task}

Требования:
{requirements}

Материалы клиента:
{materials}

Верни готовый результат без объяснения внутреннего процесса.
"""

    return _generate(prompt, temperature=0.25)


def quality_check(
    task: str,
    requirements: str,
    draft: str,
) -> str:
    prompt = f"""
Проверь черновик перед отправкой клиенту.

Задача:
{task}

Требования:
{requirements}

Черновик:
{draft}

Проверь:
- соответствует ли результат задаче;
- выполнены ли требования;
- правильный ли язык;
- нет ли логических ошибок;
- нет ли выдуманных данных;
- нет ли пропущенной информации;
- подходит ли тон;
- соответствует ли формат.

Верни краткий отчёт в таком виде:

Статус: Готово

или:

Статус: Нужно исправить

После статуса перечисли конкретные исправления.
"""

    return _generate(prompt, temperature=0.1)


def fallback_proposal(
    job: dict[str, Any],
    profile: dict[str, Any],
) -> str:
    """Создаёт простой отклик без ИИ, если API недоступен."""
    language = job.get("language_hint", "en")
    name = profile.get("display_name", "Olha")

    templates = {
        "de": (
            "Guten Tag,\n\n"
            "ich kann Sie bei dieser Aufgabe unterstützen. "
            "Bitte senden Sie mir den vollständigen Umfang, "
            "das gewünschte Format und die Frist. Danach kann ich "
            "Preis und Lieferzeit verbindlich bestätigen.\n\n"
            f"Freundliche Grüße\n{name}"
        ),
        "uk": (
            "Добрий день!\n\n"
            "Я можу допомогти з цим завданням. Будь ласка, "
            "надішліть повний обсяг, потрібний формат і термін. "
            "Після цього я зможу точно підтвердити ціну "
            "та час виконання.\n\n"
            f"З повагою,\n{name}"
        ),
        "ru": (
            "Здравствуйте!\n\n"
            "Я могу помочь с этой задачей. Пришлите, пожалуйста, "
            "полный объём, нужный формат и срок. После этого я смогу "
            "точно подтвердить цену и время выполнения.\n\n"
            f"С уважением,\n{name}"
        ),
        "en": (
            "Hello,\n\n"
            "I can help with this task. Please send the full scope, "
            "required format, and deadline, and I will confirm "
            "the price and delivery time.\n\n"
            f"Best regards,\n{name}"
        ),
    }

    return templates.get(language, templates["en"])
