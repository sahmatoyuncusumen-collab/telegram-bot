import logging
import random
import os
import psycopg2
import datetime
import sys
import asyncio
import re
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand, ChatPermissions
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
WARN_LIMIT = 3

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
        cur.execute("CREATE TABLE IF NOT EXISTS message_counts (id SERIAL PRIMARY KEY, chat_id BIGINT NOT NULL, user_id BIGINT NOT NULL, username TEXT, message_timestamp TIMESTAMPTZ NOT NULL );")
        cur.execute("CREATE TABLE IF NOT EXISTS premium_users (user_id BIGINT PRIMARY KEY, added_date TIMESTAMPTZ NOT NULL);")
        cur.execute("CREATE TABLE IF NOT EXISTS filtered_words (id SERIAL PRIMARY KEY, chat_id BIGINT NOT NULL, word TEXT NOT NULL, UNIQUE(chat_id, word));")
        cur.execute("CREATE TABLE IF NOT EXISTS warnings (id SERIAL PRIMARY KEY, chat_id BIGINT NOT NULL, user_id BIGINT NOT NULL, admin_id BIGINT NOT NULL, reason TEXT, timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW());")
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
    conn, cur = None, None
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM premium_users WHERE user_id = %s;", (user_id,))
        result = cur.fetchone()
        return result is not None
    except Exception as e:
        logger.error(f"Premium status yoxlanarkən xəta: {e}")
        return False
    finally:
        if cur: cur.close()
        if conn: conn.close()

def add_premium_user(user_id: int) -> bool:
    conn, cur = None, None
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cur = conn.cursor()
        cur.execute("INSERT INTO premium_users (user_id, added_date) VALUES (%s, %s) ON CONFLICT (user_id) DO NOTHING;", 
                    (user_id, datetime.datetime.now(datetime.timezone.utc)))
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"Premium istifadəçi əlavə edərkən xəta: {e}")
        return False
    finally:
        if cur: cur.close()
        if conn: conn.close()

def remove_premium_user(user_id: int) -> bool:
    conn, cur = None, None
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cur = conn.cursor()
        cur.execute("DELETE FROM premium_users WHERE user_id = %s;", (user_id,))
        conn.commit()
        return cur.rowcount > 0
    except Exception as e:
        logger.error(f"Premium istifadəçi silinərkən xəta: {e}")
        return False
    finally:
        if cur: cur.close()
        if conn: conn.close()

def delete_last_warning(chat_id: int, user_id: int) -> bool:
    conn, cur = None, None
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cur = conn.cursor()
        cur.execute(
            """DELETE FROM warnings WHERE id = (SELECT id FROM warnings 
               WHERE chat_id = %s AND user_id = %s 
               ORDER BY timestamp DESC LIMIT 1);""",
            (chat_id, user_id)
        )
        conn.commit()
        return cur.rowcount > 0
    except Exception as e:
        logger.error(f"Xəbərdarlıq silinərkən xəta: {e}")
        return False
    finally:
        if cur: cur.close()
        if conn: conn.close()

# --- MƏZMUN SİYAHILARI ---
ABOUT_TEXT = "🤖 **Bot Haqqında**\n\nMən qruplar üçün nəzərdə tutulmuş əyləncə və statistika botuyam. Mənimlə viktorina, tapmaca və digər oyunları oynaya, həmçinin qrupdakı aktivliyinizə görə rütbə qazana bilərsiniz."
RULES_TEXT = """
📜 **Bot İstifadə Təlimatı və Qrup Qaydaları**

Aşağıda botun bütün funksiyalarından necə istifadə edəcəyiniz barədə məlumatlar və əsas qrup qaydaları qeyd olunub.
---
### 👤 **Ümumi İstifadəçilər Üçün Əmrlər**
- `/start` - Botu başlatmaq və əsas menyunu görmək.
- `/menim_rutbem` - Qrupdakı mesaj sayınızı və rütbənizi yoxlamaq. Premium üzvlər üçün mesajlar 1.5x sürətlə hesablanır və adlarının yanında 👑 nişanı görünür.
- `/liderler` - Bu ay ən çox mesaj yazan 10 nəfərin siyahısı.
- `/zer` - 1-dən 6-ya qədər təsadüfi zər atmaq.
- `/haqqinda` - Bot haqqında qısa məlumat.
- `/qaydalar` - Bu təlimatı yenidən görmək.
---
### 🎮 **Oyun Əmrləri**
- `/viktorina` - Bilik yarışması olan viktorina oyununu başladır.
---
### 🛡️ **Adminlər Üçün İdarəetmə Əmrləri**
- `/adminpanel` - Bütün admin əmrlərini görmək üçün bu əmri istifadə edin.
---
### 📌 **Əsas Qrup Qaydaları**
1. Reklam etmək qəti qadağandır.
2. Təhqir, söyüş və aqressiv davranışlara icazə verilmir.
3. Dini və siyasi mövzuları müzakirə etmək olmaz.
"""

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

def get_rank_title(count: int, is_premium: bool = False) -> str:
    if is_premium and count > 5000: return "Qızıl Tac ⚜️"
    if count <= 50: return "Yeni Gələn 🐣"
    elif count <= 250: return "Daimi Sakin 🏠"
    elif count <= 750: return "Söhbətcil 🗣️"
    elif count <= 2000: return "Qrup Ağsaqqalı 👴"
    elif count <= 5000: return "Söhbət Baronu 👑"
    else: return "Qrupun Əfsanəsi ⚡️"
    
def parse_duration(time_str: str) -> datetime.timedelta | None:
    match = re.match(r"(\d+)([mhd])", time_str.lower())
    if not match: return None
    value, unit = int(match.group(1)), match.group(2)
    if unit == 'm': return datetime.timedelta(minutes=value)
    elif unit == 'h': return datetime.timedelta(hours=value)
    elif unit == 'd': return datetime.timedelta(days=value)
    return None

async def welcome_new_members(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.new_chat_members: return
    for member in update.message.new_chat_members:
        if member.id == context.bot.id: continue
        welcome_message = (f"Salam, [{member.first_name}](tg://user?id={member.id})! 👋\n**'{update.message.chat.title}'** qrupuna xoş gəlmisən!\nƏmrləri görmək üçün /start yaz.")
        await update.message.reply_text(welcome_message, parse_mode='Markdown')

# --- ƏSAS ƏMRLƏR ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton("ℹ️ Bot Haqqında Məlumat", callback_data="start_info_about")], [InlineKeyboardButton("📜 İstifadə Təlimatı", callback_data="start_info_qaydalar")], [InlineKeyboardButton("👥 Oyun Qrupumuz", url="https://t.me/+0z5V-OvEMmgzZTFi")], [InlineKeyboardButton(f"👨‍💻 Admin ilə Əlaqə", url=f"https://t.me/{ADMIN_USERNAME}")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Salam! Mən Oyun Botuyam. 🤖\nAşağıdakı menyudan istədiyin bölməni seç:", reply_markup=reply_markup)
    
async def haqqinda_command(update: Update, context: ContextTypes.DEFAULT_TYPE): await update.message.reply_text(ABOUT_TEXT, parse_mode='Markdown')
async def qaydalar_command(update: Update, context: ContextTypes.DEFAULT_TYPE): await update.message.reply_text(RULES_TEXT, parse_mode=ParseMode.MARKDOWN)

async def my_rank_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type == ChatType.PRIVATE: await update.message.reply_text("Bu əmr yalnız qruplarda işləyir."); return
    user = update.message.from_user; chat_id = update.message.chat.id
    raw_message_count = 0; conn, cur = None, None
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cur = conn.cursor()
        cur.execute( "SELECT COUNT(*) FROM message_counts WHERE user_id = %s AND chat_id = %s;", (user.id, chat_id) )
        result = cur.fetchone()
        if result: raw_message_count = result[0]
    except Exception as e: logger.error(f"Rütbə yoxlanarkən xəta: {e}"); await update.message.reply_text("❌ Rütbənizi yoxlayarkən xəta baş verdi."); return
    finally:
        if cur: cur.close()
        if conn: conn.close()
    user_is_premium = is_user_premium(user.id)
    effective_message_count = int(raw_message_count * 1.5) if user_is_premium else raw_message_count
    rank_title = get_rank_title(effective_message_count, user_is_premium)
    premium_icon = " 👑" if user_is_premium else ""
    reply_text = f"📊 **Sənin Statistikaların, {user.first_name}{premium_icon}!**\n\n💬 Bu qrupdakı real mesaj sayın: **{raw_message_count}**\n"
