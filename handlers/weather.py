import aiohttp
from telegram import Update
from telegram.ext import ContextTypes

async def get_weather(city: str) -> str:
    # Упрощённая версия (можно заменить на OpenWeatherMap API)
    try:
        async with aiohttp.ClientSession() as session:
            # Здесь должен быть реальный API-ключ
            url = f"https://wttr.in/{city}?format=3"
            async with session.get(url) as resp:
                if resp.status == 200:
                    return await resp.text()
                return "Не удалось получить погоду."
    except Exception as e:
        return f"Ошибка: {e}"

async def weather_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Использование: /weather <город>")
        return
    city = " ".join(context.args)
    await update.message.reply_text("🌤 Узнаю погоду...")
    result = await get_weather(city)
    await update.message.reply_text(result)
