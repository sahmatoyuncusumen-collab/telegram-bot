import logging
import random
import os
import psycopg2
import datetime
import sys
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters
from telegram.constants import ChatType
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
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cur = conn.cursor()
        cur.execute("CREATE TABLE IF NOT EXISTS message_counts (id SERIAL PRIMARY KEY, chat_id BIGINT NOT NULL, user_id BIGINT NOT NULL, username TEXT, message_timestamp TIMESTAMPTZ NOT NULL );")
        cur.execute("CREATE TABLE IF NOT EXISTS premium_users (user_id BIGINT PRIMARY KEY, added_date TIMESTAMPTZ NOT NULL);")
        conn.commit()
        cur.close()
        conn.close()
        logger.info("Verilənlər bazası cədvəlləri hazırdır.")
    except Exception as e:
        logger.error(f"Baza yaradılarkən xəta: {e}")

def is_user_premium(user_id: int) -> bool:
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM premium_users WHERE user_id = %s;", (user_id,))
        result = cur.fetchone()
        return result is not None
    finally:
        if cur: cur.close()
        if conn: conn.close()

def add_premium_user(user_id: int) -> bool:
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

# --- MƏZMUN SİYAHILARI ---
ABOUT_TEXT = "🤖 **Bot Haqqında**\n\nMən qruplar üçün nəzərdə tutulmuş əyləncə və statistika botuyam. Mənimlə viktorina, tapmaca və digər oyunları oynaya, həmçinin qrupdakı aktivliyinizə görə rütbə qazana bilərsiniz."
RULES_TEXT = "📜 **Qrup Qaydaları**\n\n1. Reklam etmək qəti qadağandır.\n2. Təhqir, söyüş və aqressiv davranışlara icazə verilmir.\n3. Dini və siyasi mövzuları müzakirə etmək olmaz.\n4. Qaydalara riayət etməyən istifadəçilər xəbərdarlıqsız uzaqlaşdırılacaq."

# --- VIKTORINA SUALLARI ---
SADE_QUIZ_QUESTIONS = [
    {'question': 'Azərbaycanın paytaxtı haradır?', 'options': ['Gəncə', 'Sumqayıt', 'Bakı', 'Naxçıvan'], 'correct': 'Bakı'},
    {'question': 'Dünyanın ən hündür dağı hansıdır?', 'options': ['K2', 'Everest', 'Elbrus', 'Monblan'], 'correct': 'Everest'},
    {'question': 'Hansı planet "Qırmızı Planet" kimi tanınır?', 'options': ['Venera', 'Mars', 'Yupiter', 'Saturn'], 'correct': 'Mars'},
    {'question': 'Suyun kimyəvi formulu nədir?', 'options': ['CO2', 'O2', 'H2O', 'NaCl'], 'correct': 'H2O'},
    {'question': '"Apple" şirkətinin qurucusu kimdir?', 'options': ['Bill Gates', 'Mark Zuckerberg', 'Steve Jobs', 'Jeff Bezos'], 'correct': 'Steve Jobs'},
]

PREMIUM_QUIZ_QUESTIONS = [
    {'question': 'Əsərlərini Nizami Gəncəvi imzası ilə yazan şairin əsl adı nədir?', 'options': ['İlyas Yusif oğlu', 'Məhəmməd Füzuli', 'İmadəddin Nəsimi', 'Əliağa Vahid'], 'correct': 'İlyas Yusif oğlu'},
    {'question': 'Azərbaycan Xalq Cümhuriyyətinin ilk baş naziri kim olmuşdur?', 'options': ['Məmməd Əmin Rəsulzadə', 'Nəsib bəy Yusifbəyli', 'Fətəli Xan Xoyski', 'Əlimərdan bəy Topçubaşov'], 'correct': 'Fətəli Xan Xoyski'},
    {'question': 'Leonardo da Vinçinin şah əsəri olan "Mona Liza" tablosu hazırda hansı muzeydə sərgilənir?', 'options': ['Britaniya Muzeyi', 'Vatikan Muzeyi', 'Ermitaj', 'Luvr Muzeyi'], 'correct': 'Luvr Muzeyi'},
    {'question': '"Formula 1" yarışlarının ən çox dünya çempionu olmuş pilotu kimdir?', 'options': ['Ayrton Senna', 'Michael Schumacher', 'Lewis Hamilton', 'Hər ikisi (Schumacher və Hamilton)'], 'correct': 'Hər ikisi (Schumacher və Hamilton)'},
    {'question': 'İşıq sürəti saniyədə təxminən nə qədərdir?', 'options': ['150,000 km', '300,000 km', '500,000 km', '1,000,000 km'], 'correct': '300,000 km'},
]

# --- KÖMƏKÇİ FUNKSİYALAR ---
def get_rank_title(count: int) -> str:
    if count <= 50: return "Yeni Gələn 🐣"
    elif count <= 250: return "Daimi Sakin 🏠"
    elif count <= 750: return "Söhbətcil 🗣️"
    elif count <= 2000: return "Qrup Ağsaqqalı 👴"
    elif count <= 5000: return "Söhbət Baronu 👑"
    else: return "Qrupun Əfsanəsi ⚡️"

async def welcome_new_members(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.new_chat_members: return
    for member in update.message.new_chat_members:
        if member.id == context.bot.id: continue
        welcome_message = (f"Salam, [{member.first_name}](tg://user?id={member.id})! 👋\n"
                         f"**'{update.message.chat.title}'** qrupuna xoş gəlmisən!\n\n"
                         "Əmrləri görmək üçün /start yaz.")
        await update.message.reply_text(welcome_message, parse_mode='Markdown')

# --- ƏSAS ƏMRLƏR ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("ℹ️ Bot Haqqında Məlumat", callback_data="start_info_about")],
        [InlineKeyboardButton("📜 Bütün Qaydalar", callback_data="start_info_qaydalar")],
        [InlineKeyboardButton("👥 Oyun Qrupumuz", url="https://t.me/+0z5V-OvEMmgzZTFi")],
        [InlineKeyboardButton(f"👨‍💻 Admin ilə Əlaqə", url=f"https://t.me/{ADMIN_USERNAME}")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    start_text = "Salam! Mən Oyun Botuyam. 🤖\nAşağıdakı menyudan istədiyin bölməni seç:"
    await update.message.reply_text(start_text, reply_markup=reply_markup)
    
async def haqqinda_command(update: Update, context: ContextTypes.DEFAULT_TYPE): await update.message.reply_text(ABOUT_TEXT, parse_mode='Markdown')
async def qaydalar_command(update: Update, context: ContextTypes.DEFAULT_TYPE): await update.message.reply_text(RULES_TEXT, parse_mode='Markdown')

async def my_rank_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.chat.type in [ChatType.GROUP, ChatType.SUPERGROUP]:
        await update.message.reply_text("Bu əmr yalnız qruplarda işləyir.")
        return

    user = update.message.from_user
    chat_id = update.message.chat_id
    message_count = 0
    conn, cur = None, None
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cur = conn.cursor()
        cur.execute( "SELECT COUNT(*) FROM message_counts WHERE user_id = %s AND chat_id = %s;", (user.id, chat_id) )
        result = cur.fetchone()
        if result: message_count = result[0]
    except Exception as e:
        logger.error(f"Rütbə yoxlanarkən xəta: {e}")
        await update.message.reply_text("❌ Rütbənizi yoxlayarkən xəta baş verdi.")
        return
    finally:
        if cur: cur.close()
        if conn: conn.close()

    rank_title = get_rank_title(message_count)
    reply_text = (f"📊 **Sənin Statistikaların, {user.first_name}!**\n\n"
                  f"💬 Bu qrupdakı ümumi mesaj sayın: **{message_count}**\n"
                  f"🏆 Rütbən: **{rank_title}**\n\n"
                  "Daha çox mesaj yazaraq yeni rütbələr qazan!")
    await update.message.reply_text(reply_text, parse_mode='Markdown')

async def zer_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    dice_roll = random.randint(1, 6)
    await update.message.reply_text(f"🎲 Zər atıldı və düşən rəqəm: **{dice_roll}**", parse_mode='Markdown')

# --- ADMİN ƏMRİ ---
async def add_premium_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != BOT_OWNER_ID:
        await update.message.reply_text("⛔ Bu əmrdən yalnız bot sahibi istifadə edə bilər.")
        return
    try:
        target_user_id = int(context.args[0])
        if add_premium_user(target_user_id):
            await update.message.reply_text(f"✅ `{target_user_id}` ID-li istifadəçi uğurla premium siyahısına əlavə edildi.", parse_mode='Markdown')
        else:
            await update.message.reply_text("❌ İstifadəçini əlavə edərkən xəta baş verdi.")
    except (IndexError, ValueError):
        await update.message.reply_text("⚠️ Düzgün istifadə: `/addpremium <user_id>`", parse_mode='Markdown')

# --- VIKTORINA ƏMRİ VƏ OYUN MƏNTİQİ ---
async def viktorina_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.chat_data.get('quiz_active'):
        await update.message.reply_text("Artıq aktiv bir viktorina var!")
        return
    keyboard = [ [InlineKeyboardButton("Viktorina (Sadə) 🌱", callback_data="viktorina_sade")], [InlineKeyboardButton("Viktorina (Premium) 👑", callback_data="viktorina_premium")] ]
    await update.message.reply_text("Zəhmət olmasa, viktorina növünü seçin:", reply_markup=InlineKeyboardMarkup(keyboard))

async def start_quiz_game(update: Update, context: ContextTypes.DEFAULT_TYPE, is_premium: bool):
    message = update.callback_query.message
    question_pool = PREMIUM_QUIZ_QUESTIONS if is_premium else SADE_QUIZ_QUESTIONS
    if not question_pool:
        await message.edit_text("Bu kateqoriya üçün heç bir sual tapılmadı."); return

    recently_asked = context.chat_data.get('recently_asked_quiz', deque(maxlen=20))
    possible_questions = [q for q in question_pool if q['question'] not in recently_asked]
    if not possible_questions:
        possible_questions = question_pool; recently_asked.clear()

    question_data = random.choice(possible_questions)
    recently_asked.append(question_data['question'])
    context.chat_data['recently_asked_quiz'] = recently_asked
    
    question, correct_answer, options = question_data['question'], question_data['correct'], list(question_data['options'])
    random.shuffle(options)
    context.chat_data.update({'correct_quiz_answer': correct_answer, 'quiz_active': True, 'quiz_lives': 3})
    
    keyboard = [[InlineKeyboardButton(option, callback_data=f"quiz_{option}")] for option in options]
    quiz_title = "Premium Viktorina 👑" if is_premium else "Sadə Viktorina 🌱"
    sent_message = await message.edit_text(
        f"{quiz_title} başladı! 🧠\n\n**Sual:** {question}\n\nQalan cəhdlər: ❤️❤️❤️",
        parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard)
    )
    context.chat_data['quiz_message_id'] = sent_message.message_id
    
# --- DÜYMƏLƏRİ VƏ MESAJLARI İDARƏ EDƏN FUNKSİYALAR ---
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; user = query.from_user; data = query.data
    await query.answer()

    if data == "start_info_about":
        await query.message.edit_text(text=ABOUT_TEXT, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(" geri", callback_data="back_to_start")]]))
    elif data == "start_info_qaydalar":
        await query.message.edit_text(text=RULES_TEXT, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(" geri", callback_data="back_to_start")]]))
    elif data == "back_to_start":
        keyboard = [ [InlineKeyboardButton("ℹ️ Bot Haqqında Məlumat", callback_data="start_info_about")], [InlineKeyboardButton("📜 Bütün Qaydalar", callback_data="start_info_qaydalar")], [InlineKeyboardButton("👥 Oyun Qrupumuz", url="https://t.me/+0z5V-OvEMmgzZTFi")], [InlineKeyboardButton(f"👨‍💻 Admin ilə Əlaqə", url=f"https://t.me/{ADMIN_USERNAME}")] ]
        await query.message.edit_text("Salam! Mən Oyun Botuyam. 🤖\nAşağıdakı menyudan istədiyin bölməni seç:", reply_markup=InlineKeyboardMarkup(keyboard))
    elif data == 'viktorina_sade':
        await start_quiz_game(update, context, is_premium=False)
    elif data == 'viktorina_premium':
        if is_user_premium(user.id):
            await start_quiz_game(update, context, is_premium=True)
        else:
            await query.message.edit_text(f"⛔ Bu funksiya yalnız premium istifadəçilər üçündür.\n\nPremium status əldə etmək üçün bot sahibi ilə əlaqə saxlayın: [Admin](https://t.me/{ADMIN_USERNAME})", parse_mode='Markdown')
    elif data.startswith("quiz_"):
        if not context.chat_data.get('quiz_active'):
            await query.answer("Bu viktorina artıq bitib.", show_alert=True); return
        chosen_answer = data.split('_', 1)[1]; correct_answer = context.chat_data['correct_quiz_answer']
        if chosen_answer == correct_answer:
            await query.answer("Düzdür!", show_alert=False)
            original_text = query.message.text.split('\n\nQalan cəhdlər:')[0].strip()
            await context.bot.edit_message_text(chat_id=query.message.chat_id, message_id=context.chat_data['quiz_message_id'], text=f"{original_text}\n\n---\n🥳 Qalib: {user.first_name}!\n✅ Düzgün cavab: **{correct_answer}**", parse_mode='Markdown')
            context.chat_data.clear()
        else:
            context.chat_data['quiz_lives'] -= 1; lives_left = context.chat_data['quiz_lives']
            await query.answer(f"Səhv cavab! {lives_left} cəhdiniz qaldı.", show_alert=True)
            if lives_left == 0:
                original_text = query.message.text.split('\n\nQalan cəhdlər:')[0].strip()
                await context.bot.edit_message_text(chat_id=query.message.chat_id, message_id=context.chat_data['quiz_message_id'], text=f"{original_text}\n\n---\n😔 Məğlub oldunuz! Bütün cəhdlər bitdi.\n✅ Düzgün cavab: **{correct_answer}**", parse_mode='Markdown')
                context.chat_data.clear()
            else:
                lives_text = "❤️" * lives_left + "🖤" * (3 - lives_left)
                original_text = query.message.text.split('\n\nQalan cəhdlər:')[0].strip()
                await context.bot.edit_message_text(chat_id=query.message.chat_id, message_id=context.chat_data['quiz_message_id'], text=f"{original_text}\n\nQalan cəhdlər: {lives_text}", reply_markup=query.message.reply_markup, parse_mode='Markdown')

async def handle_all_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.chat.type in [ChatType.GROUP, ChatType.SUPERGROUP]: return
    user = update.message.from_user; chat_id = update.message.chat_id
    conn, cur = None, None
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cur = conn.cursor()
        cur.execute("INSERT INTO message_counts (chat_id, user_id, username, message_timestamp) VALUES (%s, %s, %s, %s);", (chat_id, user.id, user.username or user.first_name, datetime.datetime.now(datetime.timezone.utc)))
        conn.commit()
    except Exception as e:
        logger.error(f"Mesajı bazaya yazarkən xəta: {e}")
    finally:
        if cur: cur.close()
        if conn: conn.close()

# --- ƏSAS MAIN FUNKSİYASI ---
def main() -> None:
    run_pre_flight_checks()
    init_db()
    application = Application.builder().token(TOKEN).build()
    
    # Handler-lərin əlavə edilməsi
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("qaydalar", qaydalar_command))
    application.add_handler(CommandHandler("haqqinda", haqqinda_command))
    application.add_handler(CommandHandler("menim_rutbem", my_rank_command))
    application.add_handler(CommandHandler("addpremium", add_premium_command))
    application.add_handler(CommandHandler("viktorina", viktorina_command, filters=~filters.ChatType.PRIVATE))
    application.add_handler(CommandHandler("zer", zer_command)) # Yeni əmr
    
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, welcome_new_members))
    # Bütün mesajları tutan handler (rütbə sistemi üçün)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_all_messages))
    
    logger.info("Bot işə düşdü...")
    application.run_polling()

if __name__ == '__main__':
    main()

