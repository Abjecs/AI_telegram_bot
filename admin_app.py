import os
from fastapi import FastAPI, Request, Depends
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import create_engine, Column, Integer, String, Text, BigInteger, select, func
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from sqladmin import Admin, ModelView, expose
from sqladmin.models import ModelView as BaseModelView
from starlette.middleware import Middleware
from starlette.middleware.authentication import AuthenticationMiddleware
import asyncpg
import logging

# ==================== КОНФИГУРАЦИЯ ====================
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("DATABASE_URL не установлен")

# Для SQLAlchemy (синхронный доступ)
# Render PostgreSQL использует asyncpg, но SQLAdmin работает с синхронными драйверами.
# Преобразуем asyncpg URL в синхронный для SQLAlchemy (заменим "postgresql://" на "postgresql+psycopg2://")
# Но у нас нет psycopg2, установим asyncpg и будем использовать sync-совместимый движок с asyncpg? Проще использовать psycopg2-binary.
# Для простоты: добавим psycopg2-binary в requirements.txt.
SYNC_DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg2://")

engine = create_engine(SYNC_DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()

logging.basicConfig(level=logging.INFO)

# ==================== МОДЕЛИ ====================
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

# ==================== SQLADMIN ПРЕДСТАВЛЕНИЯ ====================
class UserStyleAdmin(ModelView, model=UserStyle):
    column_list = [UserStyle.user_id, UserStyle.style]
    column_searchable_list = [UserStyle.user_id]
    column_sortable_list = [UserStyle.user_id]
    name = "Пользователь"
    name_plural = "Пользователи"
    icon = "fa-solid fa-user"

class MessageAdmin(ModelView, model=Message):
    column_list = [Message.id, Message.user_id, Message.username, Message.user_message, Message.bot_reply, Message.style_used, Message.timestamp]
    column_searchable_list = [Message.username, Message.user_message]
    column_sortable_list = [Message.timestamp]
    name = "Сообщение"
    name_plural = "Сообщения"
    icon = "fa-solid fa-message"

class BlockedUserAdmin(ModelView, model=BlockedUser):
    column_list = [BlockedUser.user_id, BlockedUser.blocked_at]
    column_searchable_list = [BlockedUser.user_id]
    name = "Заблокированный"
    name_plural = "Заблокированные"
    icon = "fa-solid fa-ban"

# ==================== FASTAPI ПРИЛОЖЕНИЕ ====================
app = FastAPI(title="Admin Panel for Telegram Bot")

# Добавляем простую аутентификацию (логин/пароль)
# Задайте переменные окружения ADMIN_USER и ADMIN_PASS на Render
ADMIN_USER = os.getenv("ADMIN_USER", "admin")
ADMIN_PASS = os.getenv("ADMIN_PASS", "admin")

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response, JSONResponse
import base64

class BasicAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Пропускаем статические файлы и корень (редирект)
        if request.url.path in ["/", "/health"]:
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

# Админка SQLAdmin
admin = Admin(app, engine, title="Telegram Bot Admin")
admin.register_view(UserStyleAdmin)
admin.register_view(MessageAdmin)
admin.register_view(BlockedUserAdmin)

# ==================== ДОПОЛНИТЕЛЬНЫЕ ЭНДПОИНТЫ ====================
@app.get("/health")
async def health():
    return {"status": "ok"}

@app.get("/stats")
async def get_stats():
    # Асинхронное подключение для получения статистики (через asyncpg)
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        total_users = await conn.fetchval("SELECT COUNT(*) FROM user_styles")
        total_messages = await conn.fetchval("SELECT COUNT(*) FROM messages")
        blocked = await conn.fetchval("SELECT COUNT(*) FROM blocked_users")
        return {"total_users": total_users, "total_messages": total_messages, "blocked": blocked}
    finally:
        await conn.close()

# ==================== ЗАПУСК ====================
if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
