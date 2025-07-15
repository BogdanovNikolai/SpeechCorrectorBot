import asyncio
from telegram_bot import dp, bot

async def main():
    print("🚀 Запуск Telegram-бота...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())