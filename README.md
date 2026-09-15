# 🤖 AI Telegram Bot

Умный Telegram-бот на базе **GigaChat** (модульная версия).

## 🚀 Запуск

```bash
python bot_main.py
```

## 📁 Структура

```
AI_telegram_bot/
├── bot_main.py            # Главный файл
├── config.py              # Настройки
├── styles.py              # Стили общения
├── services/
│   └── gigachat.py
├── database/
│   └── connection.py
├── handlers/              # Все команды
├── requirements.txt
└── Procfile
```

## Переменные окружения

- `TELEGRAM_TOKEN` (обязательно)
- `GIGACHAT_CREDENTIALS` (обязательно)
- `DATABASE_URL` (обязательно)

---

Система ролей и админ-панель удалены.
