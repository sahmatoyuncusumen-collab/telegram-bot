import logging
import random
import os
import psycopg2
import datetime
import sys
import asyncio
import re
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters
from telegram.constants import ChatType, ParseMode
from collections import deque

# Logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# --- BAZA VƏ ƏSAS DƏYİŞƏNLƏR ---
DATABASE_URL = os.environ.get("DATABASE_URL")
TOKEN = os.environ.get("TELEGRAM_TOKEN")
BOT_OWNER_ID = 6751376199
ADMIN_USERNAME = "tairhv"

# --- TƏHLÜKƏSİZLİK YOXLAMASI ---
def run_pre_flight_checks():
    if not DATABASE_URL or not TOKEN:
        logger.critical("--- XƏTA ---")
        logger.critical("DATABASE_URL və ya TELEGRAM_TOKEN tapılmadı. Proqram dayandırılır.")
        sys.exit(1)
    logger.info("Bütün konfiqurasiya dəyişənləri mövcuddur. Bot başladılır...")

# --- BAZA FUNKSİYALARI ---
def init_db():
    conn, cur = None, None
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cur = conn.cursor()
        cur.execute("CREATE TABLE IF NOT EXISTS premium_users (user_id BIGINT PRIMARY KEY, added_date TIMESTAMPTZ NOT NULL);")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS quiz_questions (
                id SERIAL PRIMARY KEY,
                question_text TEXT NOT NULL UNIQUE,
                options TEXT[] NOT NULL,
                correct_answer TEXT NOT NULL,
                is_premium BOOLEAN NOT NULL DEFAULT FALSE
            );
        """)
        conn.commit()
        logger.info("Verilənlər bazası cədvəlləri hazırdır.")
    except Exception as e:
        logger.error(f"Baza yaradılarkən xəta: {e}")
        sys.exit(1)
    finally:
        if cur: cur.close()
        if conn: conn.close()

def is_user_premium(user_id: int) -> bool:
    # ... (Bu funksiya və digər baza funksiyaları əvvəlki koddakı kimi tam şəkildə olmalıdır)
    pass

def add_premium_user(user_id: int) -> bool:
    # ...
    pass

def remove_premium_user(user_id: int) -> bool:
    # ...
    pass

# --- MƏZMUN SİYAHILARI ---
ABOUT_TEXT = "🤖 **Bot Haqqında**\n\nMən qruplar üçün nəzərdə tutulmuş əyləncə və statistika botuyam."
RULES_TEXT = "📜 **Qrup Qaydaları**\n\n1. Reklam etmək qəti qadağandır.\n2. Təhqir, söyüş və aqressiv davranışlara icazə verilmir."
SADE_TRUTH_QUESTIONS = ["Uşaqlıqda ən böyük qorxun nə olub?"]
SADE_DARE_TASKS = ["Qrupdakı son mesajı əlifbanın hər hərfi ilə tərsinə yaz."]
PREMIUM_TRUTH_QUESTIONS = ["Həyatının geri qalanını yalnız bir filmi izləyərək keçirməli olsaydın, hansı filmi seçərdin?"]
PREMIUM_DARE_TASKS = ["Qrupdakı adminlərdən birinə 10 dəqiqəlik \"Ən yaxşı admin\" statusu yaz."]

# --- KÖMƏKÇİ FUNKSİYALAR ---
async def is_user_admin(chat_id: int, user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if user_id == BOT_OWNER_ID: return True
    if user_id == chat_id: return True
    try:
        chat_admins = await context.bot.get_chat_administrators(chat_id)
        return user_id in [admin.user.id for admin in chat_admins]
    except Exception as e:
        logger.error(f"Admin yoxlanarkən xəta: {e}")
        return False

# --- ƏSAS ƏMRLƏR ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton("ℹ️ Bot Haqqında", callback_data="start_info_about")], [InlineKeyboardButton("📜 Qaydalar", callback_data="start_info_qaydalar")]]
    await update.message.reply_text("Salam! Mən Oyun Botuyam. 🤖\nMenyudan seçin:", reply_markup=InlineKeyboardMarkup(keyboard))
    
async def haqqinda_command(update: Update, context: ContextTypes.DEFAULT_TYPE): await update.message.reply_text(ABOUT_TEXT, parse_mode='Markdown')
async def qaydalar_command(update: Update, context: ContextTypes.DEFAULT_TYPE): await update.message.reply_text(RULES_TEXT, parse_mode=ParseMode.MARKDOWN)

# --- OYUN ƏMRLƏRİ ---
async def viktorina_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.chat_data.get('quiz_active'): await update.message.reply_text("Artıq aktiv bir viktorina var!"); return
    context.chat_data['quiz_starter_id'] = update.message.from_user.id
    keyboard = [[InlineKeyboardButton("Viktorina (Sadə) 🌱", callback_data="viktorina_sade")], [InlineKeyboardButton("Viktorina (Premium) 👑", callback_data="viktorina_premium")]]
    await update.message.reply_text(f"Salam, {update.message.from_user.first_name}! Viktorina növünü seçin:", reply_markup=InlineKeyboardMarkup(keyboard))
        
async def dcoyun_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id; chat_id = update.message.chat.id
    if update.message.chat.type == ChatType.PRIVATE: await update.message.reply_text("Bu oyunu yalnız qruplarda oynamaq olar."); return
    if not await is_user_admin(chat_id, user_id, context): await update.message.reply_text("⛔ Bu oyunu yalnız qrup adminləri başlada bilər."); return
    if context.chat_data.get('dc_game_active'): await update.message.reply_text("Artıq aktiv bir 'Doğruluq yoxsa Cəsarət?' oyunu var."); return
    context.chat_data['dc_game_starter_id'] = user_id
    keyboard = [[InlineKeyboardButton("Doğruluq Cəsarət (sadə)", callback_data="dc_select_sade")], [InlineKeyboardButton("Doğruluq Cəsarət (Premium👑)", callback_data="dc_select_premium")]]
    await update.message.reply_text("Doğruluq Cəsarət oyununa xoş gəlmisiniz👋", reply_markup=InlineKeyboardMarkup(keyboard))

# ... (Digər bütün oyun, admin, düymə və s. funksiyaları əvvəlki tam kodda olduğu kimidir) ...
# ... (Mən onları qısaltdım ki, bu mesaj çox uzun olmasın, amma siz tam versiyanı istifadə edin) ...

# --- ƏSAS MAIN FUNKSİYASI ---
async def main() -> None:
    run_pre_flight_checks()
    init_db()
    application = Application.builder().token(TOKEN).build()
    
    commands = [
        BotCommand("start", "Əsas menyunu açmaq"),
        BotCommand("qaydalar", "Qaydaları görmək"),
        BotCommand("haqqinda", "Bot haqqında məlumat"),
        BotCommand("viktorina", "Viktorina oyununu başlatmaq"),
        BotCommand("dcoyun", "Doğruluq/Cəsarət oyununu başlatmaq (Admin)"),
    ]
    await application.bot.set_my_commands(commands)
    
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("qaydalar", qaydalar_command))
    application.add_handler(CommandHandler("haqqinda", haqqinda_command))
    application.add_handler(CommandHandler("viktorina", viktorina_command))
    application.add_handler(CommandHandler("dcoyun", dcoyun_command))
    application.add_handler(CommandHandler("addpremium", add_premium_command))
    application.add_handler(CommandHandler("removepremium", remove_premium_command))
    
    application.add_handler(CallbackQueryHandler(button_handler))
    
    logger.info("Bot işə düşür...")
    await application.run_polling()

if __name__ == '__main__':
    asyncio.run(main())
