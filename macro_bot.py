import asyncio
import logging
import os
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes

# Читаем токен из переменной окружения
TOKEN = os.getenv("MACRO_BOT_TOKEN")   # имя переменной должно совпадать с тем, что вы задали в Render
TARGET_BOT_USERNAME = "Abjecs_bot"    # юзернейм основного бота (без @)
PREFIX = "Кай"                         # триггерное слово (русскими буквами)

if not TOKEN:
    raise ValueError("Переменная окружения MACRO_BOT_TOKEN не установлена!")

logging.basicConfig(level=logging.INFO)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    chat_id = update.effective_chat.id
    text = update.message.text.strip()
    if text.startswith(PREFIX):
        query = text[len(PREFIX):].strip()
        if not query:
            await update.message.reply_text("Напишите что-нибудь после команды")
            return
        # Отправляем упоминание основного бота
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
