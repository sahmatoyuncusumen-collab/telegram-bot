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
        # Mövcud cədvəllər
        cur.execute("CREATE TABLE IF NOT EXISTS message_counts (id SERIAL PRIMARY KEY, chat_id BIGINT NOT NULL, user_id BIGINT NOT NULL, username TEXT, message_timestamp TIMESTAMPTZ NOT NULL );")
        cur.execute("CREATE TABLE IF NOT EXISTS premium_users (user_id BIGINT PRIMARY KEY, added_date TIMESTAMPTZ NOT NULL);")
        cur.execute("CREATE TABLE IF NOT EXISTS filtered_words (id SERIAL PRIMARY KEY, chat_id BIGINT NOT NULL, word TEXT NOT NULL, UNIQUE(chat_id, word));")
        cur.execute("CREATE TABLE IF NOT EXISTS warnings (id SERIAL PRIMARY KEY, chat_id BIGINT NOT NULL, user_id BIGINT NOT NULL, admin_id BIGINT NOT NULL, reason TEXT, timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW());")
        # YENİ CƏDVƏL: Viktorina sualları üçün
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
# ... (digər baza funksiyaları dəyişməz qalır)

# --- MƏZMUN SİYAHILARI ---
ABOUT_TEXT = "..."
RULES_TEXT = """..."""

# DƏYİŞİKLİK: Sual siyahıları artıq boşdur, çünki bazadan oxunacaq
SADE_QUIZ_QUESTIONS = []
PREMIUM_QUIZ_QUESTIONS = []

# DOĞRULUQ VƏ CƏSARƏT SUALLARI
SADE_TRUTH_QUESTIONS = ["..."]
SADE_DARE_TASKS = ["..."]
PREMIUM_TRUTH_QUESTIONS = ["..."]
PREMIUM_DARE_TASKS = ["..."]

# --- KÖMƏKÇİ FUNKSİYALAR ---
# ... (is_user_admin, get_rank_title, parse_duration, welcome_new_members dəyişməz qalır)

# --- ƏSAS ƏMRLƏR ---
# ... (start, haqqinda, qaydalar, my_rank, zer, liderler, dcoyun dəyişməz qalır)

# --- ADMİN VƏ MODERASİYA ƏMRLƏRİ ---
# ... (adminpanel, addpremium, removepremium, addword, delword, listwords, warn, warnings, delwarn, mute, unmute dəyişməz qalır)

# YENİLİK: Sualları bazaya birdəfəlik əlavə etmək üçün admin əmri
async def addquestions_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != BOT_OWNER_ID:
        await update.message.reply_text("⛔ Bu əmrdən yalnız bot sahibi istifadə edə bilər."); return

    # Bütün 160 sual bu funksiyanın içindədir. Yalnız bir dəfə işə düşüb bazanı dolduracaq.
    all_simple_questions = [
        {'question': 'Azərbaycanın paytaxtı haradır?', 'options': ['Gəncə', 'Sumqayıt', 'Bakı', 'Naxçıvan'], 'correct': 'Bakı'},
        # ... (burada 60 sadə sualın hamısı olmalıdır) ...
    ]
    all_premium_questions = [
        {'question': 'Əsərlərini Nizami Gəncəvi imzası ilə yazan şairin əsl adı nədir?', 'options': ['İlyas Yusif oğlu', 'Məhəmməd Füzuli', 'İmadəddin Nəsimi', 'Əliağa Vahid'], 'correct': 'İlyas Yusif oğlu'},
        # ... (burada 100 premium sualın hamısı olmalıdır) ...
    ]

    conn, cur = None, None
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cur = conn.cursor()
        
        added_count = 0
        for q in all_simple_questions:
            cur.execute(
                "INSERT INTO quiz_questions (question_text, options, correct_answer, is_premium) VALUES (%s, %s, %s, %s) ON CONFLICT (question_text) DO NOTHING;",
                (q['question'], q['options'], q['correct'], False)
            )
            added_count += cur.rowcount
        
        for q in all_premium_questions:
            cur.execute(
                "INSERT INTO quiz_questions (question_text, options, correct_answer, is_premium) VALUES (%s, %s, %s, %s) ON CONFLICT (question_text) DO NOTHING;",
                (q['question'], q['options'], q['correct'], True)
            )
            added_count += cur.rowcount
            
        conn.commit()
        await update.message.reply_text(f"✅ Baza yoxlanıldı. {added_count} yeni sual uğurla əlavə edildi.")
    except Exception as e:
        logger.error(f"Sualları bazaya yazarkən xəta: {e}")
        await update.message.reply_text("❌ Sualları bazaya yazarkən xəta baş verdi.")
    finally:
        if cur: cur.close()
        if conn: conn.close()


# --- VIKTORINA ƏMRİ VƏ OYUN MƏNTİQİ ---
async def viktorina_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ... (dəyişməz qalır)
    pass

# DƏYİŞİKLİK: Bu funksiya artıq sualları bazadan oxuyur
async def ask_next_quiz_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.callback_query.message
    is_premium = context.chat_data.get('quiz_is_premium', False)
    
    conn, cur = None, None
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cur = conn.cursor()
        
        # Əvvəlki sualları ID ilə yadda saxlayaq
        recently_asked_ids = context.chat_data.get('recently_asked_quiz_ids', [])
        
        # Bazadan təsadüfi bir sual çək (əvvəl soruşulanlar xaric)
        query = "SELECT id, question_text, options, correct_answer FROM quiz_questions WHERE is_premium = %s AND id != ALL(%s) ORDER BY RANDOM() LIMIT 1;"
        cur.execute(query, (is_premium, recently_asked_ids))
        question_data = cur.fetchone()

        # Əgər bütün suallar soruşulubsa, siyahını təmizlə və yenidən çək
        if not question_data:
            recently_asked_ids = []
            context.chat_data['recently_asked_quiz_ids'] = []
            cur.execute(query, (is_premium, recently_asked_ids))
            question_data = cur.fetchone()

        if not question_data:
            await message.edit_text("Bu kateqoriya üçün heç bir sual tapılmadı (baza boşdur?)."); return

        q_id, q_text, q_options, q_correct = question_data
        
        recently_asked_ids.append(q_id)
        context.chat_data['recently_asked_quiz_ids'] = recently_asked_ids
        
        context.chat_data['correct_quiz_answer'] = q_correct
        context.chat_data['current_question_text'] = q_text
        
        random.shuffle(q_options)
        keyboard = [[InlineKeyboardButton(option, callback_data=f"quiz_{option}")] for option in q_options]
        keyboard.append([InlineKeyboardButton("Oyunu Bitir ⏹️", callback_data="quiz_stop")])
        
        quiz_title = "Premium Viktorina 👑" if is_premium else "Sadə Viktorina 🌱"
        lives_text = "❤️" * context.chat_data.get('quiz_lives', 3)
        score = context.chat_data.get('quiz_score', 0)
        
        await message.edit_text(
            f"{quiz_title}\n\n**Xalınız:** {score} ⭐\n**Qalan can:** {lives_text}\n\n**Sual:** {q_text}",
            parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard)
        )
    except Exception as e:
        logger.error(f"Viktorina sualı çəkilərkən xəta: {e}")
        await message.edit_text("❌ Viktorina sualını yükləyərkən xəta baş verdi.")
    finally:
        if cur: cur.close()
        if conn: conn.close()

# DÜYMƏLƏRİ VƏ MESAJLARI İDARƏ EDƏN FUNKSİYALAR
# ... (button_handler, handle_all_messages, word_filter_handler və digər oyun funksiyaları dəyişməz qalır)

# --- ƏSAS MAIN FUNKSİYASI ---
async def main() -> None:
    run_pre_flight_checks()
    init_db()
    application = Application.builder().token(TOKEN).build()
    
    # Bot menyusu...
    commands = [
        # ... (mövcud əmrlər)
        BotCommand("adminpanel", "Admin idarəetmə paneli (Admin)"),
    ]
    
    # Handler-lər
    # ... (mövcud handlerlər) ...
    application.add_handler(CommandHandler("addquestions", addquestions_command)) # YENİ ADMIN ƏMRİ
    # ... (qalan handlerlər) ...
    
    await application.run_polling()

if __name__ == '__main__':
    asyncio.run(main())
