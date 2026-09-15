import random

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from database.connection import get_pool

QUIZ_QUESTIONS = [
    {"q": "Столица России?", "options": ["Москва", "Санкт-Петербург", "Казань", "Новосибирск"], "correct": 0},
    {"q": "Сколько планет в Солнечной системе?", "options": ["7", "8", "9", "10"], "correct": 1},
    {"q": "Самый большой океан?", "options": ["Атлантический", "Индийский", "Тихий", "Северный Ледовитый"], "correct": 2},
    {"q": "Автор 'Войны и мира'?", "options": ["Достоевский", "Толстой", "Пушкин", "Чехов"], "correct": 1},
    {"q": "Химический символ золота?", "options": ["Ag", "Au", "Fe", "Cu"], "correct": 1},
]


async def quiz_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    question = random.choice(QUIZ_QUESTIONS)
    user_id = update.effective_user.id
    context.user_data["quiz"] = question
    keyboard = [
        [InlineKeyboardButton(opt, callback_data=f"quiz_{user_id}_{i}")]
        for i, opt in enumerate(question["options"])
    ]
    await update.message.reply_text(
        f"❓ {question['q']}",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def quiz_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts = query.data.split("_")
    if len(parts) != 3 or int(parts[1]) != query.from_user.id:
        await query.answer("Это не твоя викторина.", show_alert=True)
        return
    question = context.user_data.get("quiz")
    if not question:
        await query.edit_message_text("Вопрос устарел. Напиши /quiz")
        return
    chosen = int(parts[2])
    if not 0 <= chosen < len(question["options"]):
        return
    if chosen == question["correct"]:
        pool = get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO quiz_scores (user_id, score) VALUES ($1, 1) "
                "ON CONFLICT (user_id) DO UPDATE SET score = quiz_scores.score + 1",
                query.from_user.id,
            )
        await query.edit_message_text(f"✅ Правильно! {question['options'][chosen]}")
    else:
        correct = question["options"][question["correct"]]
        await query.edit_message_text(f"❌ Неправильно. Правильный ответ: {correct}")
    context.user_data.pop("quiz", None)


async def quiz_score_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT score FROM quiz_scores WHERE user_id = $1", update.effective_user.id)
    score = row["score"] if row else 0
    await update.message.reply_text(f"🏆 Твой счёт в викторине: {score}")


async def casino_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🎲 Кости", callback_data="casino_dice")],
        [InlineKeyboardButton("🎡 Рулетка", callback_data="casino_roulette")],
    ]
    await update.message.reply_text("Выбери игру:", reply_markup=InlineKeyboardMarkup(keyboard))


async def casino_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "casino_dice":
        await query.edit_message_text(f"🎲 Выпало: {random.randint(1, 6)}")
    elif query.data == "casino_roulette":
        number = random.randint(0, 36)
        color = "🔴" if number % 2 else "⚫" if number > 0 else "🟢"
        await query.edit_message_text(f"🎡 Рулетка: {number} {color}")


WIN_LINES = (
    (0, 1, 2), (3, 4, 5), (6, 7, 8),
    (0, 3, 6), (1, 4, 7), (2, 5, 8),
    (0, 4, 8), (2, 4, 6),
)


def _winner(board):
    for a, b, c in WIN_LINES:
        if board[a] != " " and board[a] == board[b] == board[c]:
            return board[a]
    return None


def _ttt_keyboard(board, user_id: int):
    buttons = []
    for i in range(0, 9, 3):
        buttons.append([
            InlineKeyboardButton(
                board[j] if board[j] != " " else "·",
                callback_data=f"ttt_{user_id}_{j}",
            )
            for j in range(i, i + 3)
        ])
    return InlineKeyboardMarkup(buttons)


async def ttt_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    board = [" "] * 9
    user_id = update.effective_user.id
    context.user_data["ttt_board"] = board
    context.user_data["ttt_user_id"] = user_id
    await update.message.reply_text(
        "❌⭕ Крестики-нолики\nТы ходишь первым (X)",
        reply_markup=_ttt_keyboard(board, user_id),
    )


async def ttt_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts = query.data.split("_")
    if len(parts) != 3 or int(parts[1]) != query.from_user.id:
        await query.answer("Это не твоя игра.", show_alert=True)
        return
    board = context.user_data.get("ttt_board")
    if not board:
        await query.edit_message_text("Игра устарела. Напиши /ttt")
        return
    try:
        pos = int(parts[2])
    except ValueError:
        return
    if not 0 <= pos < 9 or board[pos] != " ":
        return

    board[pos] = "X"
    winner = _winner(board)
    if winner:
        await query.edit_message_text("🎉 Ты победил!", reply_markup=None)
        return
    if " " not in board:
        await query.edit_message_text("🤝 Ничья!", reply_markup=None)
        return

    empty = [i for i, value in enumerate(board) if value == " "]
    bot_pos = random.choice(empty)
    board[bot_pos] = "O"
    winner = _winner(board)
    if winner:
        await query.edit_message_text("🤖 Бот победил.", reply_markup=None)
        return
    if " " not in board:
        await query.edit_message_text("🤝 Ничья!", reply_markup=None)
        return

    context.user_data["ttt_board"] = board
    await query.edit_message_text("Твой ход", reply_markup=_ttt_keyboard(board, query.from_user.id))
