from telegram import Update
from telegram.ext import ContextTypes
from styles import STYLES

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Временно упрощённая версия
    await update.message.reply_text(
        "Привет! Бот в процессе оптимизации.\n"
        "Используй /help для справки."
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "/start — приветствие\n"
        "/help — справка\n"
        "/style — выбрать стиль\n"
        "Бот сейчас оптимизируется..."
    )
    await update.message.reply_text(text)
