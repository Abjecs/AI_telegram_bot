# Админ-команды отключены.
# Управление доступом теперь делается через настройки Telegram бота
# (Restrict bot usage) или вручную владельцем.

from telegram import Update
from telegram.ext import ContextTypes

async def setrole(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Система ролей отключена.")

async def ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Система ролей отключена. Используй настройки Telegram для ограничения доступа.")

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Статистика временно недоступна.")
