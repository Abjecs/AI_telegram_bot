import os
import sys
import logging

# Настройка логирования в консоль (Render увидит)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

logging.info("=== Starting admin_app.py ===")
logging.info(f"Python version: {sys.version}")
logging.info(f"Current directory: {os.getcwd()}")
logging.info(f"Files in current dir: {os.listdir('.')}")

# Проверяем переменные окружения
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    logging.error("DATABASE_URL not set!")
    sys.exit(1)
else:
    # Скрываем пароль для безопасности
    masked = DATABASE_URL.split('@')[0].replace(DATABASE_URL.split(':')[2], '***') + '@' + DATABASE_URL.split('@')[1]
    logging.info(f"DATABASE_URL found (masked): {masked}")

ADMIN_USER = os.getenv("ADMIN_USER")
ADMIN_PASS = os.getenv("ADMIN_PASS")
if not ADMIN_USER or not ADMIN_PASS:
    logging.warning("ADMIN_USER or ADMIN_PASS not set, using defaults")
    ADMIN_USER = "admin"
    ADMIN_PASS = "admin"

# Пробуем импортировать необходимые библиотеки
try:
    logging.info("Importing fastapi...")
    from fastapi import FastAPI
    logging.info("FastAPI imported")
except Exception as e:
    logging.error(f"Failed to import fastapi: {e}")
    sys.exit(1)

try:
    logging.info("Importing sqlalchemy...")
    from sqlalchemy import create_engine, Column, Integer, String, Text, BigInteger
    from sqlalchemy.ext.declarative import declarative_base
    from sqlalchemy.orm import sessionmaker
    logging.info("SQLAlchemy imported")
except Exception as e:
    logging.error(f"Failed to import sqlalchemy: {e}")
    sys.exit(1)

try:
    logging.info("Importing sqladmin...")
    from sqladmin import Admin, ModelView
    logging.info("SQLAdmin imported")
except Exception as e:
    logging.error(f"Failed to import sqladmin: {e}")
    sys.exit(1)

try:
    logging.info("Importing psycopg2...")
    import psycopg2
    logging.info("psycopg2 imported")
except Exception as e:
    logging.error(f"Failed to import psycopg2 (psycopg2-binary?): {e}")
    sys.exit(1)

# Конвертируем DATABASE_URL для SQLAlchemy (синхронный драйвер)
try:
    SYNC_DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg2://")
    logging.info(f"Creating engine for: {SYNC_DATABASE_URL.split('@')[0].split(':')[0]}://...")
    engine = create_engine(SYNC_DATABASE_URL)
    SessionLocal = sessionmaker(bind=engine)
    Base = declarative_base()
    logging.info("Engine created")
except Exception as e:
    logging.error(f"Failed to create engine: {e}")
    sys.exit(1)

# Определяем модели (должны совпадать с ботом)
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

# Создаём таблицы (если нет)
try:
    Base.metadata.create_all(bind=engine)
    logging.info("Tables created/checked")
except Exception as e:
    logging.error(f"Failed to create tables: {e}")
    sys.exit(1)

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
app = FastAPI(title="Bot Admin")
admin = Admin(app, engine)
admin.register_view(UserStyleAdmin)
admin.register_view(MessageAdmin)
admin.register_view(BlockedUserAdmin)

# Простой эндпоинт для проверки
@app.get("/health")
async def health():
    return {"status": "ok"}

logging.info("Admin app initialized successfully")
