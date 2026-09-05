from telegram import Update
from telegram.ext import ContextTypes

async def quiz_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🎮 Викторина пока в процессе переноса в модули.")

async def casino_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🎰 Казино пока в процессе переноса в модули.")

async def ttt_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌⭕ Крестики-нолики пока в процессе переноса в модули.")
