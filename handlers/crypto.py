from telegram import Update
from telegram.ext import ContextTypes

from services.http import get_json


async def crypto_price(symbol: str) -> str:
    clean_symbol = symbol.strip().upper()
    if not clean_symbol.isalnum() or len(clean_symbol) > 20:
        return "Некорректный символ криптовалюты."
    data = await get_json(
        f"https://api.binance.com/api/v3/ticker/price?symbol={clean_symbol}USDT"
    )
    try:
        price = float(data["price"]) if data else None
    except (KeyError, TypeError, ValueError):
        price = None
    return f"{clean_symbol}: {price:.8f} USDT" if price is not None else "Монета не найдена."


async def crypto_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Использование: /crypto <символ>\nПример: /crypto BTC")
        return
    await update.message.reply_text(await crypto_price(context.args[0]))
