# 🤖 AI Telegram Bot

Модульный Telegram-бот на Python с **GigaChat**, PostgreSQL, напоминаниями, файлами, переводом, играми и групповыми функциями.

## Что улучшено

- 🧠 Контекст диалога: последние сообщения пользователя передаются в GigaChat.
- 🛡️ Защита AI: лимит входных/выходных данных, ограничение частоты и числа одновременных запросов.
- 🔁 Надёжность GigaChat: таймауты, экспоненциальные повторы, безопасное логирование и проверка TLS.
- ⏰ Рабочие напоминания: отдельный фоновой worker, блокировка `FOR UPDATE SKIP LOCKED`, повторная доставка при временной ошибке.
- 💾 PostgreSQL: идемпотентная инициализация, обратимые по смыслу миграции, индексы и проверка готовности.
- 🔐 Webhook: секретный заголовок Telegram, очередь `python-telegram-bot`, graceful shutdown.
- 👥 Группы: статистика сообщений, триггеры и проверка прав администратора для настроек.
- 📎 Файлы: корректное сохранение и повторная отправка документов, фото и видео.
- 🎮 Игры: защита callback-кнопок от использования другим пользователем, корректное завершение крестиков-ноликов.
- 🧪 CI: compile check, Ruff и pytest на Python 3.12/3.13.

## Быстрый запуск

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
python bot_main.py
```

На Windows вместо `source` активируй `.venv\\Scripts\\activate`.

## Переменные окружения

Обязательные:

- `TELEGRAM_TOKEN`
- `GIGACHAT_CREDENTIALS`
- `DATABASE_URL`

Для production желательно задать:

- `WEBHOOK_URL` или `RENDER_EXTERNAL_HOSTNAME`
- `WEBHOOK_SECRET`
- `APP_TIMEZONE`
- параметры `GIGACHAT_*` и `AI_*` из `.env.example`

### GigaChat и TLS

По умолчанию проверка TLS включена через `GIGACHAT_VERIFY_SSL_CERTS=true`. Отключать проверку сертификатов в production не рекомендуется.

## Основные команды

| Команда | Назначение |
|---|---|
| `/start`, `/help` | Старт и справка |
| `/style` | Стиль ответа |
| `/translate`, `/tr`, `/lang` | Перевод |
| `/remind`, `/myreminds`, `/delremind` | Напоминания |
| `/weather`, `/currency`, `/crypto`, `/news` | Информация |
| `/quiz`, `/score`, `/casino`, `/ttt` | Игры |
| `/files`, `/get`, `/delete` | Файлы |
| `/setwelcome` | Приветствие группы, только админ |
| `/addtrigger`, `/deltrigger` | Триггеры группы, только админ |
| `/triggers`, `/groupstats` | Групповые данные |

Обычные текстовые сообщения в личном чате обрабатываются GigaChat. В группах AI-ответы отключены, но работают статистика и триггеры.

## Health checks

- `GET /` — базовый статус сервиса.
- `GET /health` — статус сервиса и PostgreSQL.
- `GET /healthz` — тот же readiness/health ответ.
- `POST /webhook` — Telegram webhook; требуется заголовок `X-Telegram-Bot-Api-Secret-Token`.

## Deploy на Render

`Procfile` уже содержит:

```text
web: python bot_main.py
```

В Render добавь секреты `TELEGRAM_TOKEN`, `GIGACHAT_CREDENTIALS` и `DATABASE_URL`. Render автоматически предоставляет `RENDER_EXTERNAL_HOSTNAME`; бот использует его для webhook.

Для напоминаний желательно использовать один web-инстанс, чтобы не создавать конкурирующие worker-процессы без необходимости. Если запускаешь несколько экземпляров, PostgreSQL-блокировка защищает от двойной обработки одного напоминания, но каждый экземпляр всё равно создаёт собственный polling worker.

## Тесты

```bash
pytest -q
ruff check --select F .
python -m compileall -q .
```

CI выполняет эти проверки автоматически для push и pull request в `main`.

## Структура

```text
AI_telegram_bot/
├── bot_main.py
├── config.py
├── styles.py
├── handlers/
│   ├── files.py
│   ├── games.py
│   ├── groups.py
│   ├── message.py
│   ├── reminders.py
│   └── ...
├── services/
│   ├── gigachat.py
│   ├── rate_limit.py
│   ├── reminder_worker.py
│   └── text.py
├── database/
│   └── connection.py
├── tests/
├── .github/workflows/ci.yml
├── .env.example
├── requirements.txt
├── requirements-dev.txt
└── Procfile
```
