import aiohttp
from telegram import Update
from telegram.ext import ContextTypes

async def get_currency_rate(currency_code: str) -> str:
    try:
        async with aiohttp.ClientSession() as session:
            url = f"https://api.exchangerate-api.com/v4/latest/{currency_code.upper()}"
            async with session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    rub = data["rates"].get("RUB")
                    if rub:
                        return f"1 {currency_code.upper()} = {rub:.2f} RUB"
                return "Не удалось получить курс."
    except Exception as e:
        return f"Ошибка: {e}"

async def currency_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Использование: /currency <код валюты>\nПример: /currency USD")
        return
    code = context.args[0]
    result = await get_currency_rate(code)
    await update.message.reply_text(result)
