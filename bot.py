import logging
import os
import asyncio
from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart

# Logging-i quraşdırırıq
logging.basicConfig(level=logging.INFO)

# Render/Railway-dən tokeni götürürük
TOKEN = os.environ.get("TELEGRAM_TOKEN")

# Bot və dispatcher obyektlərini yaradırıq
bot = Bot(token=TOKEN)
dp = Dispatcher()

# /start əmri üçün handler
@dp.message(CommandStart())
async def send_welcome(message: types.Message):
    """Bu handler /start əmrinə cavab verir."""
    user_name = message.from_user.full_name
    await message.reply(f"Salam, {user_name}! Aiogram ilə test uğurludur! Bot işləyir!")

async def main() -> None:
    """Botu işə salır."""
    if not TOKEN:
        logging.critical("TELEGRAM_TOKEN tapılmadı! Bot dayandırılır.")
        return

    # Telegram-dan gələn sorğuları qəbul etməyə başlayır
    await dp.start_polling(bot)

if __name__ == "__main__":
    logging.info("Aiogram botu işə düşür...")
    asyncio.run(main())
