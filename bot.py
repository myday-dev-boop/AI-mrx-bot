import os
import logging
import psycopg2
import psycopg2.extras
from io import BytesIO
from datetime import datetime, timezone, timedelta
from urllib.parse import quote

import requests
from dotenv import load_dotenv

load_dotenv()

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

from openai import OpenAI  # Groq's API is OpenAI-compatible, so we reuse this client

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# --- Config from environment -------------------------------------------------
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")

# Your Telegram user ID(s) — only these people can use /stats and /recent.
# Comma-separated if you want more than one admin, e.g. "123456,987654"
ADMIN_IDS = {
    int(x) for x in os.environ.get("ADMIN_IDS", "").split(",") if x.strip().isdigit()
}

# Postgres connection string. On Railway, link the Postgres service to this
# one (Variables -> New Variable -> reference ${{Postgres.DATABASE_URL}}),
# or Railway will auto-provide DATABASE_URL if the services are linked.
DATABASE_URL = os.environ["DATABASE_URL"]

MAX_HISTORY_TURNS = 8  # how many past exchanges to keep per user

groq_client = (
    OpenAI(api_key=GROQ_API_KEY, base_url="https://api.groq.com/openai/v1")
    if GROQ_API_KEY
    else None
)

# Two free Groq models the user can switch between
MODELS = {
    "smart": "llama-3.3-70b-versatile",   # more capable, a bit slower
    "fast": "llama-3.1-8b-instant",       # faster, lighter
}

# --- In-memory per-user state -------------------------------------------------
user_model: dict[int, str] = {}          # user_id -> "smart" | "fast"
user_history: dict[int, list] = {}       # user_id -> [{"role":..., "content":...}, ...]


def get_model_key(user_id: int) -> str:
    return user_model.get(user_id, "smart")


def get_history(user_id: int) -> list:
    return user_history.setdefault(user_id, [])


def trim_history(user_id: int) -> None:
    hist = user_history.get(user_id, [])
    if len(hist) > MAX_HISTORY_TURNS * 2:
        user_history[user_id] = hist[-MAX_HISTORY_TURNS * 2 :]


# --- Database (usage logging, Postgres) ----------------------------------------
def db_connect():
    return psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)


def init_db() -> None:
    conn = db_connect()
    with conn, conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                username TEXT,
                first_name TEXT,
                kind TEXT NOT NULL DEFAULT 'text',
                message_text TEXT,
                created_at TIMESTAMPTZ NOT NULL
            )
            """
        )
    conn.close()
    logger.info("Database ready (Postgres)")


def log_event(update: Update, kind: str, text: str | None) -> None:
    user = update.effective_user
    conn = db_connect()
    with conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO messages (user_id, username, first_name, kind, message_text, created_at) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (
                user.id,
                user.username,
                user.first_name,
                kind,
                text,
                datetime.now(timezone.utc),
            ),
        )
    conn.close()


def is_admin(update: Update) -> bool:
    return update.effective_user.id in ADMIN_IDS


# --- AI call (Groq, free) -------------------------------------------------------
async def ask_groq(user_id: int, prompt: str) -> str:
    if not groq_client:
        return "Groq не настроен: отсутствует GROQ_API_KEY."

    model_key = get_model_key(user_id)
    model_name = MODELS[model_key]

    history = get_history(user_id)
    messages = [
        {
            "role": "system",
            "content": "Ты — полезный ассистент в Telegram. Отвечай кратко и по делу на русском языке, если пользователь не просит иначе.",
        }
    ]
    messages += history
    messages.append({"role": "user", "content": prompt})

    resp = groq_client.chat.completions.create(model=model_name, messages=messages)
    answer = resp.choices[0].message.content

    history.append({"role": "user", "content": prompt})
    history.append({"role": "assistant", "content": answer})
    trim_history(user_id)
    return answer


# --- Image generation (Pollinations.ai, free, no key needed) -------------------
async def generate_image(prompt: str) -> bytes:
    url = f"https://image.pollinations.ai/prompt/{quote(prompt)}?width=1024&height=1024&nologo=true"
    r = requests.get(url, timeout=90)
    r.raise_for_status()
    return r.content


# --- Handlers --------------------------------------------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    log_event(update, "command", "/start")
    user_id = update.effective_user.id
    model_key = get_model_key(user_id)
    await update.message.reply_text(
        f"Привет! Я AI-бот на бесплатных моделях.\n\n"
        f"Текущая модель: *{model_key}* ({MODELS[model_key]})\n\n"
        "Команды:\n"
        "/model — выбрать модель (умная/быстрая)\n"
        "/image <описание> — сгенерировать картинку\n"
        "/reset — очистить историю диалога\n\n"
        "Просто напиши сообщение — я отвечу как обычный AI-чат.",
        parse_mode="Markdown",
    )


async def model_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    log_event(update, "command", "/model")
    keyboard = [
        [
            InlineKeyboardButton("🧠 Умная (медленнее)", callback_data="set_model:smart"),
            InlineKeyboardButton("⚡ Быстрая", callback_data="set_model:fast"),
        ]
    ]
    await update.message.reply_text(
        "Выбери модель:", reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def model_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _, model_key = query.data.split(":")
    user_model[query.from_user.id] = model_key
    await query.edit_message_text(
        f"Модель переключена на: *{model_key}* ({MODELS[model_key]})", parse_mode="Markdown"
    )


async def reset_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    log_event(update, "command", "/reset")
    user_history.pop(update.effective_user.id, None)
    await update.message.reply_text("История диалога очищена.")


async def image_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    prompt = " ".join(context.args)
    log_event(update, "image", prompt or "/image (без описания)")
    if not prompt:
        await update.message.reply_text("Использование: /image описание картинки")
        return
    await update.message.chat.send_action(ChatAction.UPLOAD_PHOTO)
    try:
        image_bytes = await generate_image(prompt)
        await update.message.reply_photo(photo=BytesIO(image_bytes), caption=prompt)
    except Exception as e:
        logger.exception("Image generation failed")
        await update.message.reply_text(f"Не удалось сгенерировать изображение: {e}")


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text
    log_event(update, "text", text)

    await update.message.chat.send_action(ChatAction.TYPING)
    try:
        answer = await ask_groq(user_id, text)
    except Exception as e:
        logger.exception("AI call failed")
        answer = f"Произошла ошибка при обращении к AI: {e}"

    await update.message.reply_text(answer)


# --- Admin-only stats commands -------------------------------------------------
async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return  # silently ignore for non-admins

    conn = db_connect()
    since_today = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS c FROM messages")
        total_messages = cur.fetchone()["c"]

        cur.execute("SELECT COUNT(DISTINCT user_id) AS c FROM messages")
        total_users = cur.fetchone()["c"]

        cur.execute(
            "SELECT COUNT(*) AS c FROM messages WHERE created_at >= %s", (since_today,)
        )
        today_messages = cur.fetchone()["c"]

        cur.execute(
            "SELECT COUNT(DISTINCT user_id) AS c FROM messages WHERE created_at >= %s",
            (since_today,),
        )
        today_users = cur.fetchone()["c"]

        cur.execute(
            """
            SELECT user_id, username, first_name, COUNT(*) AS c
            FROM messages
            GROUP BY user_id, username, first_name
            ORDER BY c DESC
            LIMIT 5
            """
        )
        top_users = cur.fetchall()
    conn.close()

    lines = [
        "📊 *Статистика бота*",
        "",
        f"Всего пользователей: *{total_users}*",
        f"Всего сообщений: *{total_messages}*",
        "",
        f"Сегодня: *{today_users}* польз. / *{today_messages}* сообщ.",
        "",
        "*Топ по активности:*",
    ]
    for row in top_users:
        name = row["username"] and f"@{row['username']}" or row["first_name"] or str(row["user_id"])
        lines.append(f"— {name}: {row['c']}")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def recent_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return

    limit = 20
    if context.args and context.args[0].isdigit():
        limit = min(int(context.args[0]), 100)

    conn = db_connect()
    with conn.cursor() as cur:
        cur.execute(
            "SELECT user_id, username, first_name, kind, message_text, created_at "
            "FROM messages ORDER BY id DESC LIMIT %s",
            (limit,),
        )
        rows = cur.fetchall()
    conn.close()

    if not rows:
        await update.message.reply_text("Пока нет ни одного сообщения.")
        return

    lines = [f"🕒 *Последние {len(rows)} сообщений:*", ""]
    for row in reversed(rows):
        name = row["username"] and f"@{row['username']}" or row["first_name"] or str(row["user_id"])
        ts = row["created_at"].strftime("%H:%M")
        text = (row["message_text"] or "").replace("\n", " ")
        if len(text) > 80:
            text = text[:80] + "…"
        lines.append(f"`{ts}` *{name}*: {text}")

    message = "\n".join(lines)
    # Telegram messages are capped at 4096 chars
    if len(message) > 4000:
        message = message[:4000] + "\n…"

    await update.message.reply_text(message, parse_mode="Markdown")


def main():
    init_db()

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("model", model_command))
    app.add_handler(CommandHandler("reset", reset_command))
    app.add_handler(CommandHandler("image", image_command))
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(CommandHandler("recent", recent_command))
    app.add_handler(CallbackQueryHandler(model_callback, pattern=r"^set_model:"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    logger.info("Bot started, polling...")
    app.run_polling()


if __name__ == "__main__":
    main()
