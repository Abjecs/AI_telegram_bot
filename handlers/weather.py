from urllib.parse import quote

from telegram import Update
from telegram.ext import ContextTypes

from services.http import get_text


async def get_weather(city: str) -> str:
    city = city.strip()[:100]
    if not city:
        return "Не указан город."
    result = await get_text(f"https://wttr.in/{quote(city)}?format=3")
    return result.strip() if result else "Не удалось получить погоду."


async def weather_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Использование: /weather <город>")
        return
    city = " ".join(context.args)
    await update.message.reply_text("🌤 Узнаю погоду...")
    await update.message.reply_text(await get_weather(city))
