import os
import dotenv
from aiogram import Bot, Dispatcher, types
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram import Router, F
from aiogram.filters import Command
from ai import AIGrammarChecker
import re

# === Utility to load dictionary terms and wrap them in text ===
def load_dictionary_terms(path='словарь.txt') -> list:
    try:
        with open(path, encoding='utf-8') as f:
            content = f.read()
        terms = [w.strip(' "\'') for w in re.split(r',\s*', content)]
        return [t for t in terms if t]
    except Exception as e:
        return []

def wrap_terms(text: str, terms: list) -> str:
    # Sort by length descending to avoid partial overlaps
    for term in sorted(terms, key=len, reverse=True):
        if not term:
            continue
        # Escape for regex, allow matching inside text
        pattern = re.escape(term)
        # Only wrap if not already wrapped
        text = re.sub(rf'(?<!\{{\{{\{{)({pattern})(?!\}}\}}\}})', r'{{{{{\1}}}}}', text)
    return text

# Utility to unwrap {{{ }}} wrappers from text
def unwrap_terms(text: str) -> str:
    return re.sub(r'\{\{\{(.*?)\}\}\}', r'\1', text)

dotenv.load_dotenv()

# === Настройки бота ===
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN is not set in environment variables!")
bot = Bot(token=TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
router = Router()
dp.include_router(router)

# === Инициализация AI-модуля ===
checker = AIGrammarChecker()

# === FSM состояния ===
class CorrectionState(StatesGroup):
    waiting_for_text = State()
    correcting = State()


# === Хранение данных пользователей ===
user_sessions = {}  # {chat_id: {"original_text": ..., "errors": [...], "current_idx": 0}}


@router.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await message.answer("Привет! Отправь мне любой текст, и я помогу найти и исправить ошибки.")
    await state.set_state(CorrectionState.waiting_for_text)


@router.message(F.text, CorrectionState.waiting_for_text)
async def process_user_text(message: types.Message, state: FSMContext):
    user_text = message.text or ""
    chat_id = message.chat.id

    # Load and wrap dictionary terms
    terms = load_dictionary_terms()
    wrapped_text = wrap_terms(user_text, terms)

    await message.answer("🔍 Анализируем ваш текст на наличие ошибок...")

    results = checker.check_text_with_explanations(wrapped_text or "")  # [(orig, fixed, explanation), ...]
    error_sentences = [item for item in results if item[0] != item[1]]

    if not error_sentences:
        await message.answer("✅ Ошибок не найдено!")
        await state.clear()
        return

    # Сохраняем данные
    user_sessions[chat_id] = {
        "original_text": user_text,
        "errors": error_sentences,
        "current_idx": 0,
    }

    await state.set_state(CorrectionState.correcting)
    await send_next_error(chat_id)


async def send_next_error(chat_id: int):
    session = user_sessions.get(chat_id)
    if not session or session.get("current_idx") is None or session["current_idx"] >= len(session["errors"]):
        await finish_correction(chat_id)
        return

    orig, corrected, explanation = session["errors"][session["current_idx"]]
    # Unwrap for user display
    orig = unwrap_terms(orig)
    corrected = unwrap_terms(corrected)
    explanation = unwrap_terms(explanation)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛠️ Исправить", callback_data="suggest"),
         InlineKeyboardButton(text="➡️ Пропустить", callback_data="skip")]
    ])

    await bot.send_message(
        chat_id,
        f"📌 Найдена ошибка:\n\n"
        f"<b>Было:</b> <code>{orig}</code>\n\n"
        f"<b>Объяснение:</b> {explanation}\n\n"
        f"<b>Как будет:</b> <code>{corrected}</code>",
        reply_markup=kb,
        parse_mode="HTML"
    )


@router.callback_query(F.data.in_({"suggest", "skip"}))
async def handle_choice(callback: CallbackQuery, state: FSMContext):
    if not callback.message:
        await callback.answer("⚠️ Нет сообщения.")
        return
    chat_id = callback.message.chat.id
    choice = callback.data
    session = user_sessions.get(chat_id)

    if not session:
        await callback.answer("⚠️ Сессия истекла.")
        return

    orig, corrected, _ = session["errors"][session["current_idx"]]
    # Unwrap for user display
    orig = unwrap_terms(orig)
    corrected = unwrap_terms(corrected)

    if choice == "suggest":
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Принять", callback_data="accept"),
             InlineKeyboardButton(text="❌ Оставить", callback_data="reject")]
        ])

        await bot.send_message(
            chat_id,
            f"🛠️ Вот предложенное исправление:\n\n"
            f"➡️ <b>Было:</b> <code>{orig}</code>\n"
            f"🟰 <b>Стало:</b> <code>{corrected}</code>",
            reply_markup=kb,
            parse_mode="HTML"
        )

        session["last_correction"] = (orig, corrected)
    else:
        session["current_idx"] += 1
        await send_next_error(chat_id)

    await callback.answer()


@router.callback_query(F.data.in_({"accept", "reject"}))
async def handle_correction(callback: CallbackQuery, state: FSMContext):
    if not callback.message:
        await callback.answer("⚠️ Нет сообщения.")
        return
    chat_id = callback.message.chat.id
    choice = callback.data
    session = user_sessions.get(chat_id)

    if not session or "last_correction" not in session:
        await callback.answer("⚠️ Нет доступного исправления.")
        return

    original, corrected = session["last_correction"]
    # Unwrap for user display
    original = unwrap_terms(original)
    corrected = unwrap_terms(corrected)

    if choice == "accept":
        session["original_text"] = session["original_text"].replace(original, corrected, 1)

    session["current_idx"] += 1
    del session["last_correction"]

    await callback.answer()
    await send_next_error(chat_id)


async def finish_correction(chat_id: int):
    session = user_sessions.pop(chat_id, None)
    if not session:
        return

    edited_text = session["original_text"]
    # Unwrap for user display
    edited_text = unwrap_terms(edited_text)

    await bot.send_message(
        chat_id,
        "🎉 Все предложения проверены!\n\n"
        "📄 <b>Итоговый текст:</b>\n\n"
        f"<code>{edited_text}</code>",
        parse_mode="HTML"
    )


# === Запуск бота ===
async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())