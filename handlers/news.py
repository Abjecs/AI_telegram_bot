from telegram import Update
from telegram.ext import ContextTypes
from services.gigachat import ask_gigachat

async def news_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Использование: /news <запрос>")
        return
    query = " ".join(context.args)
    await update.message.reply_text("📰 Ищу новости...")
    result = await ask_gigachat(
        "Ты — новостной агрегатор. Кратко перескажи последние новости по запросу пользователя. Если не знаешь актуальных новостей — скажи об этом.",
        query
    )
    await update.message.reply_text(result or "Не удалось получить новости.")
