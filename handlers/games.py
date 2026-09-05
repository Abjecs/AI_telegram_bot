import random
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from database.connection import get_pool

# ==================== ВИКТОРИНА ====================
QUIZ_QUESTIONS = [
    {"q": "Столица России?", "options": ["Москва", "Санкт-Петербург", "Казань", "Новосибирск"], "correct": 0},
    {"q": "Сколько планет в Солнечной системе?", "options": ["7", "8", "9", "10"], "correct": 1},
    {"q": "Самый большой океан?", "options": ["Атлантический", "Индийский", "Тихий", "Северный Ледовитый"], "correct": 2},
    {"q": "Автор 'Войны и мира'?", "options": ["Достоевский", "Толстой", "Пушкин", "Чехов"], "correct": 1},
    {"q": "Химический символ золота?", "options": ["Ag", "Au", "Fe", "Cu"], "correct": 1},
]

async def quiz_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    question = random.choice(QUIZ_QUESTIONS)
    context.user_data["quiz"] = question
    keyboard = [[InlineKeyboardButton(opt, callback_data=f"quiz_{i}")] for i, opt in enumerate(question["options"])]
    await update.message.reply_text(
        f"❓ {question['q']}",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def quiz_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    question = context.user_data.get("quiz")
    if not question:
        await query.edit_message_text("Вопрос устарел. Напиши /quiz")
        return
    chosen = int(query.data.split("_")[1])
    if chosen == question["correct"]:
        pool = get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO quiz_scores (user_id, score) VALUES ($1, 1) "
                "ON CONFLICT (user_id) DO UPDATE SET score = quiz_scores.score + 1",
                query.from_user.id
            )
        await query.edit_message_text(f"✅ Правильно! {question['options'][chosen]}")
    else:
        correct = question["options"][question["correct"]]
        await query.edit_message_text(f"❌ Неправильно. Правильный ответ: {correct}")

async def quiz_score_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT score FROM quiz_scores WHERE user_id = $1", update.effective_user.id)
    score = row["score"] if row else 0
    await update.message.reply_text(f"🏆 Твой счёт в викторине: {score}")

# ==================== КАЗИНО ====================
async def casino_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🎲 Кости", callback_data="casino_dice")],
        [InlineKeyboardButton("🎡 Рулетка", callback_data="casino_roulette")],
    ]
    await update.message.reply_text("Выбери игру:", reply_markup=InlineKeyboardMarkup(keyboard))

async def casino_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    if data == "casino_dice":
        dice = random.randint(1, 6)
        await query.edit_message_text(f"🎲 Выпало: {dice}")
    elif data == "casino_roulette":
        number = random.randint(0, 36)
        color = "🔴" if number % 2 == 1 else "⚫" if number > 0 else "🟢"
        await query.edit_message_text(f"🎡 Рулетка: {number} {color}")

# ==================== КРЕСТИКИ-НОЛИКИ ====================
async def ttt_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    board = [" "] * 9
    context.user_data["ttt_board"] = board
    await update.message.reply_text("❌⭕ Крестики-нолики\nТы ходишь первым (X)", reply_markup=_ttt_keyboard(board))

def _ttt_keyboard(board):
    buttons = []
    for i in range(0, 9, 3):
        row = [InlineKeyboardButton(board[j] if board[j] != " " else "·", callback_data=f"ttt_{j}") for j in range(i, i+3)]
        buttons.append(row)
    return InlineKeyboardMarkup(buttons)

async def ttt_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    board = context.user_data.get("ttt_board", [" "] * 9)
    pos = int(query.data.split("_")[1])
    if board[pos] != " ":
        return
    board[pos] = "X"
    # Ход бота
    empty = [i for i, v in enumerate(board) if v == " "]
    if empty:
        bot_pos = random.choice(empty)
        board[bot_pos] = "O"
    context.user_data["ttt_board"] = board
    await query.edit_message_text("Ход сделан", reply_markup=_ttt_keyboard(board))
