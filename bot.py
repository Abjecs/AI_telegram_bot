import logging
import asyncio
import os
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes
from openai import AsyncOpenAI

TELEGRAM_TOKEN = "8653192866:AAHOc_4RhUDHtRzfDRzk-QKNSrcdvBlGotE"
DEEPSEEK_API_KEY = "sk-8cccc3a7daa74255b44a1d5906ee86d6"

logging.basicConfig(level=logging.INFO)

deepseek_client = AsyncOpenAI(
    api_key=DEEPSEEK_API_KEY,
    base_url="https://api.deepseek.com/v1",
)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_message = update.message.text
    chat_id = update.effective_chat.id
    await context.bot.send_chat_action(chat_id=chat_id, action="typing")
    try:
        response = await deepseek_client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": "Ты — полезный, дружелюбный и остроумный помощник. Отвечай кратко и по существу."},
                {"role": "user", "content": user_message}
            ],
            max_tokens=300,
            temperature=0.7
        )
        ai_reply = response.choices[0].message.content
        await update.message.reply_text(ai_reply)
    except Exception as e:
        logging.error(f"Ошибка DeepSeek: {e}")
        await update.message.reply_text("Извините, я сейчас занят. Попробуйте позже.")

async def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("Бот запущен...")
    await app.initialize()
    await app.start()
    await app.updater.start_polling()
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())
