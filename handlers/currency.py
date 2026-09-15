from telegram import Update
from telegram.ext import ContextTypes

from services.http import get_json


async def get_currency_rate(currency_code: str) -> str:
    code = currency_code.strip().upper()
    if not code.isalpha() or len(code) != 3:
        return "Код валюты должен состоять из 3 букв, например USD."
    data = await get_json(f"https://api.exchangerate-api.com/v4/latest/{code}")
    try:
        rub = float(data["rates"]["RUB"]) if data else None
    except (KeyError, TypeError, ValueError):
        rub = None
    return f"1 {code} = {rub:.2f} RUB" if rub is not None else "Не удалось получить курс."


async def currency_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Использование: /currency <код валюты>\nПример: /currency USD")
        return
    await update.message.reply_text(await get_currency_rate(context.args[0]))
