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
    from google import genai
except Exception:  # pragma: no cover
    genai = None

DEFAULT_MODEL = "gemini-2.5-flash-lite"


def get_secret(name: str, default: str = "") -> str:
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
    return genai is not None and bool(get_secret("GEMINI_API_KEY"))


def _client() -> Any:
    if genai is None:
        raise RuntimeError("Пакет google-genai не установлен")
    api_key = get_secret("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY не настроен")
    return genai.Client(api_key=api_key)


def _generate(prompt: str, *, temperature: float = 0.3) -> str:
    model = get_secret("GEMINI_MODEL", DEFAULT_MODEL)
    response = _client().models.generate_content(
        model=model,
        contents=prompt,
        config={"temperature": temperature},
    )
    text = getattr(response, "text", None)
    if not text:
        raise RuntimeError("ИИ вернул пустой ответ")
    return text.strip()


def _extract_json(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, flags=re.S)
    if fenced:
        cleaned = fenced.group(1)
    else:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start >= 0 and end > start:
            cleaned = cleaned[start : end + 1]
    data = json.loads(cleaned)
    if not isinstance(data, dict):
        raise ValueError("Ожидался JSON-объект")
    return data


def analyze_job(job: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    prompt = f"""
Ты — осторожный помощник фрилансера. Проанализируй объявление без выдумывания опыта.
Профиль: {json.dumps(profile, ensure_ascii=False)}
Объявление: {json.dumps(job, ensure_ascii=False)}

Верни ТОЛЬКО JSON:
{{
  "fit_score": число 0-100,
  "recommended": true или false,
  "detected_language": "язык",
  "task_type": "тип задачи",
  "estimated_minutes": число,
  "suggested_price_eur": число,
  "deadline_assessment": "кратко",
  "missing_information": ["вопрос"],
  "risks": ["риск"],
  "reason": "краткое объяснение"
}}
Не предлагай обход правил площадки, проверок личности или возраста.
"""
    return _extract_json(_generate(prompt, temperature=0.15))


def create_proposal(
    job: dict[str, Any],
    profile: dict[str, Any],
    analysis: dict[str, Any],
    preferences: str = "",
) -> str:
    prompt = f"""
Напиши короткий персональный отклик на объявление.
Отвечай на языке объявления. Не утверждай навыки и опыт, которых нет в профиле.
Не обещай невозможное. Не упоминай ИИ. Не соглашайся на оплату вне правил площадки.
Профиль: {json.dumps(profile, ensure_ascii=False)}
Объявление: {json.dumps(job, ensure_ascii=False)}
Анализ: {json.dumps(analysis, ensure_ascii=False)}
Пожелания пользователя: {preferences}

Структура: приветствие, понимание задачи, что будет сделано, срок/цена только если обоснованы, 1-2 уточняющих вопроса, завершение.
Верни только готовый текст отклика.
"""
    return _generate(prompt, temperature=0.35)


def create_reply(history: str, incoming: str, facts: str, preferred_language: str = "auto") -> str:
    prompt = f"""
Подготовь ответ клиенту как исполнитель. Язык: {preferred_language}; если auto — язык последнего сообщения.
Сохраняй уже согласованные цену, срок и объём. Не выдумывай факты, не меняй условия самовольно.
Если клиент просит личные документы, предоплату от исполнителя, подарочные карты, доступ к банковскому счёту или обход правил — вежливо откажись.
Согласованные факты: {facts}
История: {history}
Новое сообщение: {incoming}
Верни только сообщение клиенту.
"""
    return _generate(prompt, temperature=0.25)


def fulfill_order(task: str, materials: str, requirements: str, output_language: str = "auto") -> str:
    prompt = f"""
Выполни легитимное текстовое/документное задание на основе данных клиента.
Не выдумывай отсутствующие имена, даты, квалификации, источники или цифры.
Если критически не хватает данных, создай максимально полезный черновик и в конце добавь раздел "Нужно уточнить".
Не выполняй мошеннические, опасные или запрещённые задания.
Язык результата: {output_language}
Задача: {task}
Требования: {requirements}
Материалы клиента:
{materials}

Верни готовый результат без лишних объяснений о процессе.
"""
    return _generate(prompt, temperature=0.25)


def quality_check(task: str, requirements: str, draft: str) -> str:
    prompt = f"""
Проверь черновик перед отправкой клиенту.
Задача: {task}
Требования: {requirements}
Черновик: {draft}

Проверь: соответствие требованиям, язык, логические ошибки, выдуманные данные, пропуски, тон и формат.
Верни краткий отчёт: "Готово", "Нужно исправить" и конкретные исправления.
"""
    return _generate(prompt, temperature=0.1)


def fallback_proposal(job: dict[str, Any], profile: dict[str, Any]) -> str:
    language = job.get("language_hint", "en")
    name = profile.get("display_name", "Olha")
    templates = {
        "de": f"Guten Tag,\n\nich kann Sie bei dieser Aufgabe unterstützen. Bitte senden Sie mir den vollständigen Umfang, das gewünschte Format und die Frist. Danach kann ich Preis und Lieferzeit verbindlich bestätigen.\n\nFreundliche Grüße\n{name}",
        "uk": f"Добрий день!\n\nЯ можу допомогти з цим завданням. Будь ласка, надішліть повний обсяг, потрібний формат і термін. Після цього я зможу точно підтвердити ціну та час виконання.\n\nЗ повагою,\n{name}",
        "ru": f"Здравствуйте!\n\nЯ могу помочь с этой задачей. Пришлите, пожалуйста, полный объём, нужный формат и срок. После этого я смогу точно подтвердить цену и время выполнения.\n\nС уважением,\n{name}",
        "en": f"Hello,\n\nI can help with this task. Please send the full scope, required format, and deadline, and I will confirm the price and delivery time.\n\nBest regards,\n{name}",
    }
    return templates.get(language, templates["en"])
