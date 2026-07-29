# Установка Job Agent на iPad

## Что действительно проверено

- Python-синтаксис всех файлов.
- Автоматические тесты сканера, дедупликации, рейтинга и шаблонов.
- Запуск Streamlit-приложения в headless-режиме.
- Валидность JSON и YAML-файлов.

Сетевой ответ конкретных внешних сайтов нельзя гарантировать навсегда: сайт может изменить или отключить feed. Сканер при этом не падает целиком, а записывает ошибку в `scan_status.json`.

## Файлы, которые должны быть в репозитории

Обычные файлы:

- `app.py`
- `ai.py`
- `scanner.py`
- `config.json`
- `jobs.json`
- `scan_status.json`
- `requirements.txt`
- `README.md`
- `SETUP_IPAD_RU.md`
- `.gitignore`

Скрытые пути:

- `.github/workflows/scan.yml`
- `.streamlit/config.toml`

## 1. Загрузка обычных файлов

В GitHub открой репозиторий → `Add file` → `Upload files`. Выбери обычные файлы из распакованной папки и нажми `Commit changes`.

## 2. Создание workflow

В репозитории нажми `Add file` → `Create new file`.

В поле имени введи:

`.github/workflows/scan.yml`

Открой одноимённый файл в папке проекта на iPad, скопируй весь текст, вставь в GitHub и нажми `Commit changes`.

## 3. Создание Streamlit config

Повтори `Add file` → `Create new file`.

Имя:

`.streamlit/config.toml`

Скопируй содержимое локального файла и сохрани.

## 4. Проверка GitHub Actions

Открой `Actions` → `Scan job sources` → `Run workflow` → `Run workflow`.

Зелёная галочка означает, что тесты и сканер завершились. Если источник недоступен, workflow всё равно обычно завершится, а ошибка будет записана в `scan_status.json`.

## 5. Gemini API key

Создай ключ в Google AI Studio. Не добавляй его в GitHub-файлы.

## 6. Streamlit Community Cloud

Открой Streamlit Community Cloud и войди через GitHub.

- `Create app`
- Repository: твой репозиторий
- Branch: `main`
- Main file: `app.py`
- Advanced settings → Python 3.12
- Secrets:

```toml
GEMINI_API_KEY = "ТВОЙ_КЛЮЧ"
GEMINI_MODEL = "gemini-2.5-flash-lite"
```

Нажми `Deploy`.

## 7. Добавление на экран iPad

Открой ссылку приложения в Safari → Поделиться → На экран «Домой».

## 8. Как пользоваться

- `Заказы`: смотри найденные предложения или вставляй объявление вручную.
- `Отклик`: анализируй объявление и создавай ответ.
- `Переписка`: вставляй историю и последнее сообщение клиента.
- `Выполнение`: вставляй материалы и требования клиента.
- `Диагностика`: проверяй ключ, источники и последнюю работу сканера.

Перед отправкой всегда проверяй текст, цену, срок и требования площадки.
