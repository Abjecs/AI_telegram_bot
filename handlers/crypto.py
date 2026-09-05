import aiohttp
from telegram import Update
from telegram.ext import ContextTypes

async def crypto_price(symbol: str) -> str:
    try:
        async with aiohttp.ClientSession() as session:
            url = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol.upper()}USDT"
            async with session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return f"{symbol.upper()}: {float(data['price']):.4f} USDT"
                return "Монета не найдена."
    except Exception as e:
        return f"Ошибка: {e}"

async def crypto_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Использование: /crypto <символ>\nПример: /crypto BTC")
        return
    symbol = context.args[0]
    result = await crypto_price(symbol)
    await update.message.reply_text(result)
