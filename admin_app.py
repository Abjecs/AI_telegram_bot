import os
import sys
import logging
from fastapi import FastAPI
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response
import base64
from sqlalchemy import create_engine, Column, Integer, String, Text, BigInteger
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqladmin import Admin, ModelView

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logging.info("=== Starting admin_app.py with authentication ===")

# Переменные окружения
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    logging.error("DATABASE_URL not set!")
    sys.exit(1)

ADMIN_USER = os.getenv("ADMIN_USER", "admin")
ADMIN_PASS = os.getenv("ADMIN_PASS", "admin")
if ADMIN_USER == "admin" and ADMIN_PASS == "admin":
    logging.warning("Using default admin credentials! Change them via ADMIN_USER/ADMIN_PASS env vars.")

# Подключение к БД
SYNC_DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg2://")
engine = create_engine(SYNC_DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()

# Модели
class UserStyle(Base):
    __tablename__ = "user_styles"
    user_id = Column(BigInteger, primary_key=True)
    style = Column(String, default="standart")

class Message(Base):
    __tablename__ = "messages"
    id = Column(Integer, primary_key=True)
    user_id = Column(BigInteger)
    username = Column(String)
    user_message = Column(Text)
    bot_reply = Column(Text)
    style_used = Column(String)
    timestamp = Column(String)

class BlockedUser(Base):
    __tablename__ = "blocked_users"
    user_id = Column(BigInteger, primary_key=True)
    blocked_at = Column(String)

Base.metadata.create_all(bind=engine)
logging.info("Tables created/checked")

# Админ-представления
class UserStyleAdmin(ModelView, model=UserStyle):
    column_list = [UserStyle.user_id, UserStyle.style]
    column_searchable_list = [UserStyle.user_id]
    name = "Пользователь"
    name_plural = "Пользователи"

class MessageAdmin(ModelView, model=Message):
    column_list = [Message.id, Message.user_id, Message.username, Message.user_message, Message.bot_reply, Message.style_used, Message.timestamp]
    column_searchable_list = [Message.username, Message.user_message]
    name = "Сообщение"
    name_plural = "Сообщения"

class BlockedUserAdmin(ModelView, model=BlockedUser):
    column_list = [BlockedUser.user_id, BlockedUser.blocked_at]
    name = "Заблокированный"
    name_plural = "Заблокированные"

# FastAPI приложение
app = FastAPI(title="Bot Admin Panel")

# Middleware для Basic Authentication
class BasicAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        # Эндпоинты /health и / не требуют аутентификации (можно оставить открытыми)
        if request.url.path in ["/health", "/"]:
            return await call_next(request)
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Basic "):
            return Response("Unauthorized", status_code=401, headers={"WWW-Authenticate": "Basic"})
        try:
            encoded = auth_header.split(" ")[1]
            decoded = base64.b64decode(encoded).decode("utf-8")
            username, password = decoded.split(":", 1)
            if username != ADMIN_USER or password != ADMIN_PASS:
                return Response("Unauthorized", status_code=401, headers={"WWW-Authenticate": "Basic"})
        except:
            return Response("Unauthorized", status_code=401, headers={"WWW-Authenticate": "Basic"})
        return await call_next(request)

app.add_middleware(BasicAuthMiddleware)

# Подключаем админку SQLAdmin
admin = Admin(app, engine)
admin.add_view(UserStyleAdmin)
admin.add_view(MessageAdmin)
admin.add_view(BlockedUserAdmin)

# Эндпоинт для проверки здоровья
@app.get("/health")
async def health():
    return {"status": "ok"}

logging.info("Admin app with authentication initialized successfully")
