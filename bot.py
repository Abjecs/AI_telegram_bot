import logging
import asyncio
import os
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes

# ========== ВАШ ТОКЕН ==========
TELEGRAM_TOKEN = "8653192866:AAHOc_4RhUDHtRzfDRzk-QKNSrcdvBlGotE"
# ===============================

logging.basicConfig(level=logging.INFO)

async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_message = update.message.text
    await update.message.reply_text(f"Вы сказали: {user_message}")

async def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo))
    print("Бот запущен и работает...")
    await app.initialize()
    await app.start()
    await app.updater.start_polling()
    # Бесконечное ожидание, чтобы бот работал постоянно
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())

