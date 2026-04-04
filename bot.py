import logging
import asyncio
import os
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes
from gigachat import GigaChat

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GIGACHAT_CREDENTIALS = os.getenv("GIGACHAT_CREDENTIALS")

if not TELEGRAM_TOKEN:
    raise ValueError("Переменная TELEGRAM_TOKEN не установлена!")
if not GIGACHAT_CREDENTIALS:
    raise ValueError("Переменная GIGACHAT_CREDENTIALS не установлена!")

logging.basicConfig(level=logging.INFO)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_message = update.message.text
    chat_id = update.effective_chat.id
    await context.bot.send_chat_action(chat_id=chat_id, action="typing")
    try:
        async with GigaChat(
            credentials=GIGACHAT_CREDENTIALS,
            verify_ssl_certs=False,
            model="GigaChat:latest"
        ) as giga:
            response = await giga.achat(user_message)
            ai_reply = response.choices[0].message.content
            await update.message.reply_text(ai_reply)
    except Exception as e:
        logging.error(f"Ошибка GigaChat: {e}")
        await update.message.reply_text("❌ Ошибка при обращении к GigaChat. Попробуйте позже.")

async def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("✅ Бот запущен и работает через GigaChat!")
    await app.initialize()
    await app.start()
    await app.updater.start_polling()
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())
