import os
import logging
from io import BytesIO

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

from openai import OpenAI
import google.generativeai as genai

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# --- Config from environment -------------------------------------------------
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

MAX_HISTORY_TURNS = 8  # how many past exchanges to keep per user

openai_client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

# --- In-memory per-user state -------------------------------------------------
# user_id -> "chatgpt" | "gemini"
user_model: dict[int, str] = {}
# user_id -> list of {"role": "user"/"assistant", "content": str}
user_history: dict[int, list] = {}


def get_model(user_id: int) -> str:
    return user_model.get(user_id, "chatgpt")


def get_history(user_id: int) -> list:
    return user_history.setdefault(user_id, [])


def trim_history(user_id: int) -> None:
    hist = user_history.get(user_id, [])
    if len(hist) > MAX_HISTORY_TURNS * 2:
        user_history[user_id] = hist[-MAX_HISTORY_TURNS * 2 :]


# --- AI calls ------------------------------------------------------------------
async def ask_chatgpt(user_id: int, prompt: str) -> str:
    if not openai_client:
        return "ChatGPT не настроен: отсутствует OPENAI_API_KEY."
    history = get_history(user_id)
    messages = [{"role": "system", "content": "Ты — полезный ассистент в Telegram. Отвечай кратко и по делу на русском языке, если пользователь не просит иначе."}]
    messages += history
    messages.append({"role": "user", "content": prompt})

    resp = openai_client.chat.completions.create(
        model="gpt-4o-mini",
        messages=messages,
    )
    answer = resp.choices[0].message.content
    history.append({"role": "user", "content": prompt})
    history.append({"role": "assistant", "content": answer})
    trim_history(user_id)
    return answer


async def ask_gemini(user_id: int, prompt: str) -> str:
    if not GEMINI_API_KEY:
        return "Gemini не настроен: отсутствует GEMINI_API_KEY."
    history = get_history(user_id)

    model = genai.GenerativeModel("gemini-2.0-flash")
    # Convert stored OpenAI-style history to Gemini format
    gemini_history = []
    for msg in history:
        role = "user" if msg["role"] == "user" else "model"
        gemini_history.append({"role": role, "parts": [msg["content"]]})

    chat = model.start_chat(history=gemini_history)
    resp = chat.send_message(prompt)
    answer = resp.text

    history.append({"role": "user", "content": prompt})
    history.append({"role": "assistant", "content": answer})
    trim_history(user_id)
    return answer


async def generate_image(prompt: str) -> bytes:
    """Generate an image using DALL-E 3 and return raw bytes."""
    if not openai_client:
        raise RuntimeError("OPENAI_API_KEY не настроен, генерация фото недоступна.")
    resp = openai_client.images.generate(
        model="dall-e-3",
        prompt=prompt,
        size="1024x1024",
        n=1,
    )
    import requests

    url = resp.data[0].url
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    return r.content


# --- Handlers --------------------------------------------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    model = get_model(user_id)
    await update.message.reply_text(
        f"Привет! Я AI-бот.\n\n"
        f"Текущая модель: *{model}*\n\n"
        "Команды:\n"
        "/model — выбрать ChatGPT или Gemini\n"
        "/image <описание> — сгенерировать картинку\n"
        "/reset — очистить историю диалога\n\n"
        "Просто напиши сообщение — я отвечу как обычный AI-чат.",
        parse_mode="Markdown",
    )


async def model_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [
            InlineKeyboardButton("🤖 ChatGPT", callback_data="set_model:chatgpt"),
            InlineKeyboardButton("✨ Gemini", callback_data="set_model:gemini"),
        ]
    ]
    await update.message.reply_text(
        "Выбери модель:", reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def model_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _, model = query.data.split(":")
    user_model[query.from_user.id] = model
    await query.edit_message_text(f"Модель переключена на: *{model}*", parse_mode="Markdown")


async def reset_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_history.pop(update.effective_user.id, None)
    await update.message.reply_text("История диалога очищена.")


async def image_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    prompt = " ".join(context.args)
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
    model = get_model(user_id)

    await update.message.chat.send_action(ChatAction.TYPING)
    try:
        if model == "gemini":
            answer = await ask_gemini(user_id, text)
        else:
            answer = await ask_chatgpt(user_id, text)
    except Exception as e:
        logger.exception("AI call failed")
        answer = f"Произошла ошибка при обращении к {model}: {e}"

    await update.message.reply_text(answer)


def main():
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("model", model_command))
    app.add_handler(CommandHandler("reset", reset_command))
    app.add_handler(CommandHandler("image", image_command))
    app.add_handler(CallbackQueryHandler(model_callback, pattern=r"^set_model:"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    logger.info("Bot started, polling...")
    app.run_polling()


if __name__ == "__main__":
    main()
