import os

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GIGACHAT_CREDENTIALS = os.getenv("GIGACHAT_CREDENTIALS")
DATABASE_URL = os.getenv("DATABASE_URL")
AUTH_PASSWORD = os.getenv("AUTH_PASSWORD", "default123")
NEWS_API_KEY = os.getenv("NEWS_API_KEY", "")
TGSTAT_TOKEN = os.getenv("TGSTAT_API_TOKEN", "")
STORAGE_CHANNEL_ID = os.getenv("STORAGE_CHANNEL_ID")
IMGFLIP_USERNAME = os.getenv("IMGFLIP_USERNAME", "")
IMGFLIP_PASSWORD = os.getenv("IMGFLIP_PASSWORD", "")
PORT = int(os.environ.get("PORT", 8080))

if not TELEGRAM_TOKEN or not GIGACHAT_CREDENTIALS or not DATABASE_URL:
    raise ValueError("Ошибка: необходимые переменные окружения не установлены!")
