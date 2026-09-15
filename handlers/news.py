from telegram import Update
from telegram.ext import ContextTypes

from services.gigachat import ask_gigachat
from services.text import reply_in_chunks


async def news_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Использование: /news <запрос>")
        return
    query = " ".join(context.args).strip()
    await update.message.reply_text("📰 Ищу новости...")
    result = await ask_gigachat(
        "Ты — новостной агрегатор. Кратко перескажи известные тебе новости по запросу пользователя. "
        "Не выдумывай факты и явно предупреждай, если у тебя нет доступа к актуальным данным.",
        query,
        user_id=update.effective_user.id,
    )
    await reply_in_chunks(update.message, result or "Не удалось получить новости.")
