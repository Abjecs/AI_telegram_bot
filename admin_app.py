import os
import sys
import logging
from fastapi import FastAPI
from sqlalchemy import create_engine, Column, Integer, String, Text, BigInteger
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqladmin import Admin, ModelView

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logging.info("=== Starting admin_app.py ===")

# Переменные окружения
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    logging.error("DATABASE_URL not set!")
    sys.exit(1)

ADMIN_USER = os.getenv("ADMIN_USER", "admin")
ADMIN_PASS = os.getenv("ADMIN_PASS", "admin")

# Подключение к БД через SQLAlchemy (синхронное, с psycopg2)
# Преобразуем URL для SQLAlchemy (заменяем postgresql:// на postgresql+psycopg2://)
SYNC_DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg2://")
engine = create_engine(SYNC_DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()

# Модели (должны совпадать с таблицами бота)
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

# Создаём таблицы, если их нет
Base.metadata.create_all(bind=engine)
logging.info("Tables created/checked")

# ========== АДМИН-ПРЕДСТАВЛЕНИЯ (SQLAdmin) ==========
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

# ========== FASTAPI ПРИЛОЖЕНИЕ ==========
app = FastAPI(title="Bot Admin Panel")

# Подключаем админку (используем add_view, а не register_view)
admin = Admin(app, engine)
admin.add_view(UserStyleAdmin)
admin.add_view(MessageAdmin)
admin.add_view(BlockedUserAdmin)

# Эндпоинт для проверки работоспособности
@app.get("/health")
async def health():
    return {"status": "ok"}

logging.info("Admin app initialized successfully")
