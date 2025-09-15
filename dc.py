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
ABOUT_TEXT = "🤖 **Bot Haqqında**\n\nMən qruplar üçün nəzərdə tutulmuş əyləncə və statistika botuyam. Mənimlə viktorina, tapmaca və digər oyunları oynaya, həmçinin qrupdakı aktivliyinizə görə rütə qazana bilərsiniz."
RULES_TEXT = """
📜 **Bot İstifadə Təlimatı və Qrup Qaydaları**
... (Təlimat mətni olduğu kimi qalır) ...
"""

# VIKTORINA SUALLARI ARTIQ BAZADAN OXUNACAQ, BU SİYAHILAR BOŞ QALMALIDIR
SADE_QUIZ_QUESTIONS = []
PREMIUM_QUIZ_QUESTIONS = []

# DOĞRULUQ VƏ CƏSARƏT SUALLARI
SADE_TRUTH_QUESTIONS = ["Uşaqlıqda ən böyük qorxun nə olub?", "Heç kimin bilmədiyi bir bacarığın var?"]
SADE_DARE_TASKS = ["Qrupdakı son mesajı əlifbanın hər hərfi ilə tərsinə yaz.", "Telefonundakı son şəkli qrupa göndər."]
PREMIUM_TRUTH_QUESTIONS = ["Həyatının geri qalanını yalnız bir filmi izləyərək keçirməli olsaydın, hansı filmi seçərdin?", "Əgər zaman maşının olsaydı, keçmişə yoxsa gələcəyə gedərdin? Niyə?"]
PREMIUM_DARE_TASKS = ["Qrupdakı adminlərdən birinə 10 dəqiqəlik \"Ən yaxşı admin\" statusu yaz.", "Səni ən yaxşı təsvir edən bir \"meme\" tap və qrupa göndər."]


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
    # ... (Bu funksiya tam şəkildə əvvəlki koddadır)
    pass

async def zer_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ... (Bu funksiya tam şəkildə əvvəlki koddadır)
    pass

async def liderler_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ... (Bu funksiya tam şəkildə əvvəlki koddadır)
    pass
        
async def dcoyun_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ... (Bu funksiya tam şəkildə əvvəlki koddadır)
    pass

# --- ADMİN VƏ MODERASİYA ƏMRLƏRİ ---
async def adminpanel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ... (Bu funksiya tam şəkildə əvvəlki koddadır)
    pass

async def add_premium_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ... (Bu funksiya tam şəkildə əvvəlki koddadır)
    pass

async def remove_premium_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ... (Bu funksiya tam şəkildə əvvəlki koddadır)
    pass

async def addword_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ... (Bu funksiya tam şəkildə əvvəlki koddadır)
    pass

async def delword_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ... (Bu funksiya tam şəkildə əvvəlki koddadır)
    pass

async def listwords_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ... (Bu funksiya tam şəkildə əvvəlki koddadır)
    pass

async def warn_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ... (Bu funksiya tam şəkildə əvvəlki koddadır)
    pass

async def warnings_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ... (Bu funksiya tam şəkildə əvvəlki koddadır)
    pass

async def delwarn_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ... (Bu funksiya tam şəkildə əvvəlki koddadır)
    pass

async def mute_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ... (Bu funksiya tam şəkildə əvvəlki koddadır)
    pass

async def unmute_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ... (Bu funksiya tam şəkildə əvvəlki koddadır)
    pass

async def addquestions_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != BOT_OWNER_ID:
        await update.message.reply_text("⛔ Bu əmrdən yalnız bot sahibi istifadə edə bilər."); return

    await update.message.reply_text("⏳ Suallar bazaya əlavə edilir, bu bir neçə saniyə çəkə bilər...")
    
    # 60 Sadə Sual
    all_simple_questions = [
        {'question': 'Azərbaycanın paytaxtı haradır?', 'options': ['Gəncə', 'Sumqayıt', 'Bakı', 'Naxçıvan'], 'correct': 'Bakı'},
        # ... (buraya 59 ədəd daha sadə sual əlavə olunacaq)
    ]
    # 100 Premium Sual
    all_premium_questions = [
        {'question': 'Əsərlərini Nizami Gəncəvi imzası ilə yazan şairin əsl adı nədir?', 'options': ['İlyas Yusif oğlu', 'Məhəmməd Füzuli', 'İmadəddin Nəsimi', 'Əliağa Vahid'], 'correct': 'İlyas Yusif oğlu'},
        # ... (buraya 99 ədəd daha premium sual əlavə olunacaq)
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
    if context.chat_data.get('quiz_active'):
        await update.message.reply_text("Artıq aktiv bir viktorina var!"); return
    context.chat_data['quiz_starter_id'] = update.message.from_user.id
    keyboard = [ [InlineKeyboardButton("Viktorina (Sadə) 🌱", callback_data="viktorina_sade")], [InlineKeyboardButton("Viktorina (Premium) 👑", callback_data="viktorina_premium")] ]
    await update.message.reply_text(f"Salam, {update.message.from_user.first_name}! Zəhmət olmasa, viktorina növünü seçin:", reply_markup=InlineKeyboardMarkup(keyboard))

async def ask_next_quiz_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.callback_query.message
    is_premium = context.chat_data.get('quiz_is_premium', False)
    conn, cur = None, None
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cur = conn.cursor()
        recently_asked_ids = context.chat_data.get('recently_asked_quiz_ids', [])
        query = "SELECT id, question_text, options, correct_answer FROM quiz_questions WHERE is_premium = %s AND id != ALL(%s) ORDER BY RANDOM() LIMIT 1;"
        cur.execute(query, (is_premium, recently_asked_ids if recently_asked_ids else [0]))
        question_data = cur.fetchone()

        if not question_data:
            recently_asked_ids = []
            context.chat_data['recently_asked_quiz_ids'] = []
            cur.execute(query, (is_premium, [0]))
            question_data = cur.fetchone()

        if not question_data:
            await message.edit_text("Bu kateqoriya üçün heç bir sual tapılmadı. Adminə bildirin ki, /addquestions əmrini işlətsin."); return

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

# DÜYMƏLƏR VƏ MESAJ HANDLERLƏRİ
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ... (Bu funksiya tam şəkildə əvvəlki koddadır)
    pass

async def handle_all_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ... (Bu funksiya tam şəkildə əvvəlki koddadır)
    pass

async def word_filter_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ... (Bu funksiya tam şəkildə əvvəlki koddadır)
    pass

# --- ƏSAS MAIN FUNKSİYASI ---
async def main() -> None:
    run_pre_flight_checks()
    init_db()
    application = Application.builder().token(TOKEN).build()
    
    commands = [
        BotCommand("start", "Əsas menyunu açmaq"),
        BotCommand("qaydalar", "İstifadə təlimatı və qaydalar"),
        BotCommand("adminpanel", "Admin idarəetmə paneli (Admin)"),
        # ... (qalan menyu əmrləri)
    ]
    
    # Handler-lər
    # ... (Bütün handlerlər əvvəlki koddadır)
    application.add_handler(CommandHandler("addquestions", addquestions_command))
    
    await application.run_polling()

if __name__ == '__main__':
    asyncio.run(main())
