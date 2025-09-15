import logging
import os
import asyncio
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# Logging-i quraşdırırıq
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logger = logging.getLogger(__name__)

# Render-dən tokeni götürürük
TOKEN = os.environ.get("TELEGRAM_TOKEN")

# Çox sadə bir /start funksiyası
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/start əmri göndəriləndə cavab verir"""
    user_name = update.message.from_user.first_name
    await update.message.reply_text(f'Salam, {user_name}! Test uğurludur, mən işləyirəm!')

async def main() -> None:
    """ Əsas funksiya: botu işə salır """
    if not TOKEN:
        logger.critical("TELEGRAM_TOKEN tapılmadı! Bot dayandırılır.")
        return
        
    # Əsas proqramı qururuq
    application = Application.builder().token(TOKEN).build()

    # Yalnız bir əmri qeydiyyatdan keçiririk
    application.add_handler(CommandHandler("start", start_command))

    logger.info("Minimal test botu işə düşür...")
    
    # Botu işə salırıq
    await application.run_polling()

if __name__ == '__main__':
    asyncio.run(main())
