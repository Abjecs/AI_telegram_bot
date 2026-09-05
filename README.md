# 🤖 AI Telegram Bot

Умный Telegram-бот на базе **GigaChat**. Сейчас идёт оптимизация и разбиение на модули.

## ✨ Возможности

- Стили общения (Стандартный, Шутник, Нейрохам, Философ, Поэт, Эксперт)
- Переводчик, напоминания, новости, погода, валюты, крипта
- Викторина, казино, крестики-нолики
- Облачное хранилище файлов
- Групповые функции (триггеры, статистика)
- Админ-панель

## 📁 Новая структура (в процессе)

```
AI_telegram_bot/
├── bot.py                 # Главный файл (пока ещё большой)
├── config.py              # Все настройки и токены
├── styles.py              # Стили общения
├── services/
│   ├── __init__.py
│   └── gigachat.py        # Хелпер для GigaChat
├── database/
│   ├── __init__.py
│   └── connection.py      # Подключение к БД
├── handlers/
│   ├── __init__.py
│   └── start.py           # Команды /start и /help
├── admin_app.py
├── requirements.txt
└── Procfile
```

## 🚀 Запуск

```bash
pip install -r requirements.txt
python bot.py
```

Нужны переменные окружения: `TELEGRAM_TOKEN`, `GIGACHAT_CREDENTIALS`, `DATABASE_URL`.

---

Оптимизация продолжается...
