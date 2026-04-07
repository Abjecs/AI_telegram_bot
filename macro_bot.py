import asyncio
import logging
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes

TOKEN = "YOUR_MACRO_BOT_TOKEN"      # токен короткого бота
TARGET_BOT_USERNAME = "Abjecs_bot"  # юзернейм основного бота (без @)
PREFIX = "Кай"                     # команда-триггер

logging.basicConfig(level=logging.INFO)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    chat_id = update.effective_chat.id
    text = update.message.text.strip()
    if text.startswith(PREFIX):
        # Извлекаем текст после префикса
        query = text[len(PREFIX):].strip()
        if not query:
            await update.message.reply_text("Напишите что-нибудь после !бот")
            return
        # Отправляем в тот же чат упоминание основного бота
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"@{TARGET_BOT_USERNAME} {query}"
        )

async def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("Макрос-бот запущен...")
    await app.initialize()
    await app.start()
    await app.updater.start_polling()
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())
