

# === ai.py ===

import os
import dotenv
import re
from typing import List, Tuple
from loguru import logger
from mistralai import Mistral
from mistralai.models import UserMessage

dotenv.load_dotenv()

# === Настройки Mistral ===
API_KEY = os.getenv("MISTRAL_API_KEY")
MODEL_NAME = "mistral-large-latest"

# Инициализируем клиент
client = Mistral(api_key=API_KEY)


async def analyze_text_errors_tagged(text: str) -> str:
    """
    Отправляет текст в Mistral для анализа на наличие ошибок.
    Возвращает исходный текст, где предложения с ошибками обрамлены в <ОШИБКА>.

    Args:
        text (str): исходный текст пользователя.

    Returns:
        str: текст с обрамлёнными ошибками.
    """

    prompt = f"""
Проанализируй следующий текст на наличие орфографических, пунктуационных и грамматических ошибок.
Если в предложении есть хотя бы одна ошибка — обрами его целиком в тег <ОШИБКА>.
Если ошибок нет — верни текст без изменений.

ТЕКСТ:
{text}
"""

    try:
        logger.info("Отправляем запрос к Mistral для выделения ошибок...")

        messages = [UserMessage(content=prompt)]

        chat_response = await client.chat.complete_async(
            model=MODEL_NAME,
            messages=messages
        )

        content = chat_response.choices[0].message.content.strip()
        return content

    except Exception as e:
        logger.error(f"Ошибка при обращении к Mistral: {e}")
        return text


async def suggest_correction(sentence: str) -> Tuple[str, str]:
    """
    Предлагает исправление для одного предложения.

    Args:
        sentence (str): предложение с ошибкой

    Returns:
        Tuple[str, str]: (оригинал, исправленный вариант)
    """

    prompt = f"""
Проанализируй это предложение и предложи правильный вариант:

ПРЕДЛОЖЕНИЕ:
{sentence}
"""

    try:
        logger.info("Отправляем запрос к Mistral для исправления предложения...")

        messages = [UserMessage(content=prompt)]

        chat_response = await client.chat.complete_async(
            model=MODEL_NAME,
            messages=messages
        )

        corrected = chat_response.choices[0].message.content.strip()
        return sentence, corrected

    except Exception as e:
        logger.error(f"Ошибка при обращении к Mistral: {e}")
        return sentence, sentence


def extract_tagged_sentences(tagged_text: str) -> List[str]:
    """
    Извлекает из строки все предложения, обрамлённые в <ОШИБКА>...</ОШИБКА>

    Args:
        tagged_text (str): текст с тегами

    Returns:
        List[str]: список предложений с ошибками
    """
    pattern = r"<ОШИБКА>(.*?)</ОШИБКА>"
    return [match.strip() for match in re.findall(pattern, tagged_text, re.DOTALL)]

# === telegram_bot.py ===

# telegram_bot.py

import os
import dotenv
from ai import analyze_text_errors_tagged, extract_tagged_sentences, suggest_correction
from aiogram import Bot, Dispatcher, types
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram import Router, F
from aiogram.filters import Command

dotenv.load_dotenv()

# === Настройки бота ===
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
bot = Bot(token=TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
router = Router()
dp.include_router(router)


# === FSM состояния ===
class CorrectionState(StatesGroup):
    waiting_for_text = State()
    correcting = State()


# === Хранение данных пользователей ===
user_sessions = {}  # {chat_id: {"original_text": ..., "error_sentences": [...], "current_idx": 0, "edited_text": ...}}


@router.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await message.answer("Привет! Отправь мне любой текст, и я помогу найти и исправить ошибки.")
    await state.set_state(CorrectionState.waiting_for_text)


@router.message(F.text, CorrectionState.waiting_for_text)
async def process_user_text(message: types.Message, state: FSMContext):
    user_text = message.text
    chat_id = message.chat.id

    await message.answer("🔍 Анализируем ваш текст на наличие ошибок...")

    tagged_text = await analyze_text_errors_tagged(user_text)  # ✅ await добавлен
    error_sentences = extract_tagged_sentences(tagged_text)

    if not error_sentences:
        await message.answer("✅ Ошибок не найдено!")
        await state.clear()
        return

    # Сохраняем данные
    user_sessions[chat_id] = {
        "original_text": user_text,
        "tagged_text": tagged_text,
        "error_sentences": error_sentences,
        "current_idx": 0,
        "edited_text": user_text,
    }

    await state.set_state(CorrectionState.correcting)
    await send_next_error_sentence(chat_id)


async def send_next_error_sentence(chat_id: int):
    session = user_sessions.get(chat_id)
    if not session or session["current_idx"] >= len(session["error_sentences"]):
        await finish_correction(chat_id)
        return

    current_sentence = session["error_sentences"][session["current_idx"]]

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛠️ Исправить", callback_data="suggest"),
         InlineKeyboardButton(text="➡️ Пропустить", callback_data="skip")]
    ])

    await bot.send_message(
        chat_id,
        f"📌 Найдено предложение с возможной ошибкой:\n\n"
        f"<code>{current_sentence}</code>",
        reply_markup=kb,
        parse_mode="HTML"
    )


@router.callback_query(F.data.in_({"suggest", "skip"}))
async def handle_choice(callback: CallbackQuery, state: FSMContext):
    chat_id = callback.message.chat.id
    choice = callback.data
    session = user_sessions.get(chat_id)

    if not session:
        await callback.answer("⚠️ Сессия истекла.")
        return

    current_sentence = session["error_sentences"][session["current_idx"]]

    if choice == "suggest":
        original, corrected = await suggest_correction(current_sentence)  # ✅ await добавлен
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Принять", callback_data="accept"),
             InlineKeyboardButton(text="❌ Оставить", callback_data="reject")]
        ])

        await bot.send_message(
            chat_id,
            f"🛠️ Вот предложенное исправление:\n\n"
            f"➡️ <b>Было:</b> <code>{original}</code>\n"
            f"🟰 <b>Стало:</b> <code>{corrected}</code>",
            reply_markup=kb,
            parse_mode="HTML"
        )

        session["last_correction"] = (original, corrected)
        await state.set_state(CorrectionState.correcting)
    else:
        session["current_idx"] += 1
        await send_next_error_sentence(chat_id)

    await callback.answer()


@router.callback_query(F.data.in_({"accept", "reject"}))
async def handle_correction(callback: CallbackQuery, state: FSMContext):
    chat_id = callback.message.chat.id
    choice = callback.data
    session = user_sessions.get(chat_id)

    if not session or "last_correction" not in session:
        await callback.answer("⚠️ Нет доступного исправления.")
        return

    original, corrected = session["last_correction"]

    if choice == "accept":
        session["edited_text"] = session["edited_text"].replace(original, corrected, 1)

    session["current_idx"] += 1
    del session["last_correction"]

    await callback.answer()
    await send_next_error_sentence(chat_id)


async def finish_correction(chat_id: int):
    session = user_sessions.pop(chat_id, None)
    if not session:
        return

    edited_text = session["edited_text"]

    await bot.send_message(
        chat_id,
        "🎉 Все предложения проверены!\n\n"
        "📄 <b>Итоговый текст:</b>\n\n"
        f"<code>{edited_text}</code>",
        parse_mode="HTML"
    )

# === main.py ===

import asyncio
from telegram_bot import dp, bot

async def main():
    print("🚀 Запуск Telegram-бота...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())