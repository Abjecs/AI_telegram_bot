# 🤖 AI Telegram Bot

Умный Telegram-бот на базе **GigaChat**.

## 🔄 Статус оптимизации

Бот активно разбивается на модули. Сейчас есть две точки входа:

- `bot.py` — старая монолитная версия (полный функционал)
- `bot_main.py` — новая модульная версия (пока не все функции перенесены)

## 📁 Текущая структура

```
AI_telegram_bot/
├── bot.py                 # Старая полная версия
├── bot_main.py            # Новая модульная точка входа
├── config.py              # Настройки и токены
├── styles.py              # Стили общения
├── services/
│   └── gigachat.py        # Хелпер GigaChat
├── database/
│   └── connection.py      # Подключение к БД
├── handlers/
│   ├── start.py
│   ├── reminders.py
│   ├── translate.py
│   ├── styles.py
│   ├── games.py
│   ├── groups.py
│   ├── files.py
│   └── admin.py
├── admin_app.py
├── requirements.txt
└── Procfile
```

## 🚀 Запуск

Пока рекомендуется запускать старую версию:

```bash
python bot.py
```

Новая модульная версия (когда будет готова):

```bash
python bot_main.py
```

## Переменные окружения

- `TELEGRAM_TOKEN`
- `GIGACHAT_CREDENTIALS`
- `DATABASE_URL`

---

Оптимизация продолжается.
