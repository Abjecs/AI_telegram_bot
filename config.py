import os


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Required environment variable is missing: {name}")
    return value


def _int_env(name: str, default: int, minimum: int = 0) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer") from exc
    if value < minimum:
        raise RuntimeError(f"{name} must be >= {minimum}")
    return value


def _float_env(name: str, default: float, minimum: float = 0.0) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except ValueError as exc:
        raise RuntimeError(f"{name} must be a number") from exc
    if value < minimum:
        raise RuntimeError(f"{name} must be >= {minimum}")
    return value


TELEGRAM_TOKEN = _required("TELEGRAM_TOKEN")
GIGACHAT_CREDENTIALS = _required("GIGACHAT_CREDENTIALS")
DATABASE_URL = _required("DATABASE_URL")

PORT = _int_env("PORT", 8080, 1)
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "").strip()
RENDER_EXTERNAL_HOSTNAME = os.getenv("RENDER_EXTERNAL_HOSTNAME", "").strip()
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "").strip()

GIGACHAT_MODEL = os.getenv("GIGACHAT_MODEL", "GigaChat-2").strip()
GIGACHAT_BASE_URL = os.getenv("GIGACHAT_BASE_URL", "https://api.giga.chat/v1").strip()
GIGACHAT_SCOPE = os.getenv("GIGACHAT_SCOPE", "GIGACHAT_API_PERS").strip()
GIGACHAT_VERIFY_SSL_CERTS = os.getenv("GIGACHAT_VERIFY_SSL_CERTS", "true").lower() in {
    "1", "true", "yes", "on"
}
GIGACHAT_CA_BUNDLE_FILE = os.getenv("GIGACHAT_CA_BUNDLE_FILE", "").strip()
AI_TIMEOUT = _float_env("AI_TIMEOUT", 60.0, 1.0)
AI_MAX_RETRIES = _int_env("AI_MAX_RETRIES", 2, 0)
AI_RETRY_BACKOFF = _float_env("AI_RETRY_BACKOFF", 1.0, 0.1)
AI_MAX_INPUT_CHARS = _int_env("AI_MAX_INPUT_CHARS", 12000, 100)
AI_MAX_OUTPUT_CHARS = _int_env("AI_MAX_OUTPUT_CHARS", 12000, 100)
AI_HISTORY_MESSAGES = _int_env("AI_HISTORY_MESSAGES", 8, 0)
AI_MAX_CONCURRENT = _int_env("AI_MAX_CONCURRENT", 3, 1)
AI_RATE_LIMIT = _int_env("AI_RATE_LIMIT", 10, 1)
AI_RATE_WINDOW_SECONDS = _int_env("AI_RATE_WINDOW_SECONDS", 60, 1)

REMINDER_POLL_SECONDS = _float_env("REMINDER_POLL_SECONDS", 5.0, 1.0)
MAX_USER_FILES = _int_env("MAX_USER_FILES", 50, 1)
MAX_FILE_NAME_CHARS = _int_env("MAX_FILE_NAME_CHARS", 255, 32)

NEWS_API_KEY = os.getenv("NEWS_API_KEY", "").strip()
TGSTAT_TOKEN = os.getenv("TGSTAT_API_TOKEN", "").strip()
STORAGE_CHANNEL_ID = os.getenv("STORAGE_CHANNEL_ID", "").strip()
IMGFLIP_USERNAME = os.getenv("IMGFLIP_USERNAME", "").strip()
IMGFLIP_PASSWORD = os.getenv("IMGFLIP_PASSWORD", "").strip()

if WEBHOOK_SECRET and not 1 <= len(WEBHOOK_SECRET) <= 256:
    raise RuntimeError("WEBHOOK_SECRET must contain 1-256 characters")
