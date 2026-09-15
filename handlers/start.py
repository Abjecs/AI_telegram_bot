from telegram import Update
from telegram.ext import ContextTypes
from styles import STYLES

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Привет! Я бот на базе GigaChat.\n"
        "Используй /help чтобы увидеть все команды.\n"
        "Можешь просто написать мне сообщение — я отвечу."
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "/start — приветствие\n"
        "/help — справка\n"
        "/style — выбрать стиль общения\n"
        "/quiz — викторина\n"
        "/casino — казино\n"
        "/ttt — крестики-нолики\n"
        "/weather <город> — погода\n"
        "/crypto <символ> — курс крипты\n"
        "/currency <код> — курс валюты\n"
        "/translate <текст> — перевод\n"
        "/lang <код> — язык перевода\n"
        "/remind <время> <текст> — напоминание\n"
        "/myreminds — список напоминаний\n"
        "/files — мои файлы\n"
        "\nПросто напиши сообщение — я отвечу в выбранном стиле."
    )
    await update.message.reply_text(text)
