import logging
import random
import os
import psycopg2
import datetime
import sys
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
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
    conn, cur = None, None
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cur = conn.cursor()
        cur.execute("CREATE TABLE IF NOT EXISTS message_counts (id SERIAL PRIMARY KEY, chat_id BIGINT NOT NULL, user_id BIGINT NOT NULL, username TEXT, message_timestamp TIMESTAMPTZ NOT NULL );")
        cur.execute("CREATE TABLE IF NOT EXISTS premium_users (user_id BIGINT PRIMARY KEY, added_date TIMESTAMPTZ NOT NULL);")
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

# --- MƏZMUN SİYAHILARI ---
ABOUT_TEXT = "🤖 **Bot Haqqında**\n\nMən qruplar üçün nəzərdə tutulmuş əyləncə və statistika botuyam. Mənimlə viktorina, tapmaca və digər oyunları oynaya, həmçinin qrupdakı aktivliyinizə görə rütbə qazana bilərsiniz."
RULES_TEXT = "📜 **Qrup Qaydaları**\n\n1. Reklam etmək qəti qadağandır.\n2. Təhqir, söyüş və aqressiv davranışlara icazə verilmir.\n3. Dini və siyasi mövzuları müzakirə etmək olmaz.\n4. Qaydalara riayət etməyən istifadəçilər xəbərdarlıqsız uzaqlaşdırılacaq."

# --- VIKTORINA SUALLARI (GENİŞLƏNDİRİLMİŞ BAZA) ---
# ... (Sizin sual siyahılarınız burada olduğu kimi qalır) ...
SADE_QUIZ_QUESTIONS = [
    # Cəmi 40 sadə sual...
]
PREMIUM_QUIZ_QUESTIONS = [
    # Cəmi 80 premium sual...
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
    user = update.message.from_user; chat_id = update.message.chat_id; message_count = 0
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

# --- ADMİN ƏMRLƏRİ ---
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

async def remove_premium_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != BOT_OWNER_ID:
        await update.message.reply_text("⛔ Bu əmrdən yalnız bot sahibi istifadə edə bilər.")
        return
    try:
        target_user_id = int(context.args[0])
        if remove_premium_user(target_user_id):
            await update.message.reply_text(f"✅ `{target_user_id}` ID-li istifadəçinin premium statusu uğurla geri alındı.", parse_mode='Markdown')
        else:
            await update.message.reply_text("❌ Belə bir premium istifadəçi tapılmadı və ya xəta baş verdi.", parse_mode='Markdown')
    except (IndexError, ValueError):
        await update.message.reply_text("⚠️ Düzgün istifadə: `/removepremium <user_id>`", parse_mode='Markdown')

# --- VIKTORINA ƏMRİ VƏ OYUN MƏNTİQİ ---
async def viktorina_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.chat_data.get('quiz_active'):
        await update.message.reply_text("Artıq aktiv bir viktorina var!")
        return
    context.chat_data['quiz_starter_id'] = update.message.from_user.id
    keyboard = [ [InlineKeyboardButton("Viktorina (Sadə) 🌱", callback_data="viktorina_sade")], [InlineKeyboardButton("Viktorina (Premium) 👑", callback_data="viktorina_premium")] ]
    await update.message.reply_text(f"Salam, {update.message.from_user.first_name}! Zəhmət olmasa, viktorina növünü seçin:", reply_markup=InlineKeyboardMarkup(keyboard))

async def ask_next_quiz_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.callback_query.message
    is_premium = context.chat_data.get('quiz_is_premium', False)
    question_pool = PREMIUM_QUIZ_QUESTIONS if is_premium else SADE_QUIZ_QUESTIONS
    if not question_pool: await message.edit_text("Bu kateqoriya üçün heç bir sual tapılmadı."); return

    recently_asked = context.chat_data.get('recently_asked_quiz', deque(maxlen=100))
    possible_questions = [q for q in question_pool if q['question'] not in recently_asked]
    if not possible_questions: possible_questions = question_pool; recently_asked.clear()
    
    question_data = random.choice(possible_questions)
    recently_asked.append(question_data['question'])
    context.chat_data['recently_asked_quiz'] = recently_asked
    
    question, correct_answer, options = question_data['question'], question_data['correct'], list(question_data['options'])
    random.shuffle(options)
    context.chat_data['correct_quiz_answer'] = correct_answer
    # YENİLİK: Hazırkı sualın mətnini yadda saxlamaq
    context.chat_data['current_question_text'] = question
    
    keyboard = [[InlineKeyboardButton(option, callback_data=f"quiz_{option}")] for option in options]
    keyboard.append([InlineKeyboardButton("Oyunu Bitir ⏹️", callback_data="quiz_stop")])
    
    quiz_title = "Premium Viktorina 👑" if is_premium else "Sadə Viktorina 🌱"
    lives_text = "❤️" * context.chat_data.get('quiz_lives', 3)
    score = context.chat_data.get('quiz_score', 0)
    
    await message.edit_text(
        f"{quiz_title}\n\n"
        f"**Xalınız:** {score} ⭐\n"
        f"**Qalan can:** {lives_text}\n\n"
        f"**Sual:** {question}",
        parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard)
    )
    
# DÜYMƏLƏRİ VƏ MESAJLARI İDARƏ EDƏN FUNKSİYALAR
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; user = query.from_user; data = query.data
    await query.answer()

    if data.startswith("viktorina_") or data.startswith("quiz_"):
        quiz_starter_id = context.chat_data.get('quiz_starter_id')
        if quiz_starter_id and user.id != quiz_starter_id:
            await query.answer("⛔ Bu, sizin başlatdığınız oyun deyil.", show_alert=True)
            return

    if data == "start_info_about":
        await query.message.edit_text(text=ABOUT_TEXT, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(" geri", callback_data="back_to_start")]]))
    elif data == "start_info_qaydalar":
        await query.message.edit_text(text=RULES_TEXT, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(" geri", callback_data="back_to_start")]]))
    elif data == "back_to_start":
        keyboard = [ [InlineKeyboardButton("ℹ️ Bot Haqqında Məlumat", callback_data="start_info_about")], [InlineKeyboardButton("📜 Bütün Qaydalar", callback_data="start_info_qaydalar")], [InlineKeyboardButton("👥 Oyun Qrupumuz", url="https://t.me/+0z5V-OvEMmgzZTFi")], [InlineKeyboardButton(f"👨‍💻 Admin ilə Əlaqə", url=f"https://t.me/{ADMIN_USERNAME}")] ]
        await query.message.edit_text("Salam! Mən Oyun Botuyam. 🤖\nAşağıdakı menyudan istədiyin bölməni seç:", reply_markup=InlineKeyboardMarkup(keyboard))
    elif data == 'viktorina_sade' or data == 'viktorina_premium':
        is_premium_choice = (data == 'viktorina_premium')
        if is_premium_choice and not is_user_premium(user.id):
            await query.message.edit_text(f"⛔ Bu funksiya yalnız premium istifadəçilər üçündür.\n\nPremium status əldə etmək üçün bot sahibi ilə əlaqə saxlayın: [Admin](https://t.me/{ADMIN_USERNAME})", parse_mode='Markdown')
            return
        context.chat_data.clear()
        context.chat_data.update({ 'quiz_active': True, 'quiz_is_premium': is_premium_choice, 'quiz_lives': 3, 'quiz_score': 0, 'quiz_message_id': query.message.message_id, 'quiz_starter_id': user.id })
        await ask_next_quiz_question(update, context)
    elif context.chat_data.get('quiz_active'):
        if data == 'quiz_stop':
            score = context.chat_data.get('quiz_score', 0)
            await query.message.edit_text(f"Oyun dayandırıldı! ✅\n\nSizin yekun xalınız: **{score}** ⭐\n\nYeni oyun üçün /viktorina yazın.", parse_mode='Markdown')
            context.chat_data.clear()
        elif data.startswith("quiz_"):
            chosen_answer = data.split('_', 1)[1]; correct_answer = context.chat_data['correct_quiz_answer']
            if chosen_answer == correct_answer:
                context.chat_data['quiz_score'] += 1
                await query.answer(text="✅ Düzdür! Növbəti sual gəlir...", show_alert=False)
                await asyncio.sleep(2)
                await ask_next_quiz_question(update, context)
            else:
                context.chat_data['quiz_lives'] -= 1
                lives_left = context.chat_data['quiz_lives']
                await query.answer(text=f"❌ Səhv cavab! {lives_left} canınız qaldı.", show_alert=True)
                if lives_left == 0:
                    score = context.chat_data.get('quiz_score', 0)
                    await query.message.edit_text(f"Canlarınız bitdi və oyun başa çatdı! 😔\n\nDüzgün cavab: **{correct_answer}**\nSizin yekun xalınız: **{score}** ⭐\n\nYeni oyun üçün /viktorina yazın.", parse_mode='Markdown')
                    context.chat_data.clear()
                else:
                    # DƏYİŞİKLİK: Yeni sual çağırmaq əvəzinə, sadəcə mesajı yeniləmək
                    is_premium = context.chat_data.get('quiz_is_premium', False)
                    quiz_title = "Premium Viktorina 👑" if is_premium else "Sadə Viktorina 🌱"
                    lives_text = "❤️" * lives_left
                    score = context.chat_data.get('quiz_score', 0)
                    question = context.chat_data.get('current_question_text', '')
                    await query.message.edit_text(
                        f"{quiz_title}\n\n"
                        f"**Xalınız:** {score} ⭐\n"
                        f"**Qalan can:** {lives_text}\n\n"
                        f"**Sual:** {question}",
                        parse_mode='Markdown', reply_markup=query.message.reply_markup
                    )
    else:
        await query.answer("Bu oyun artıq bitib.", show_alert=True)

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
async def main() -> None:
    run_pre_flight_checks()
    init_db()
    
    application = Application.builder().token(TOKEN).build()
    
    commands = [
        BotCommand("start", "Əsas menyunu açmaq"),
        BotCommand("qaydalar", "Qrup qaydalarını göstərmək"),
        BotCommand("haqqinda", "Bot haqqında məlumat"),
        BotCommand("menim_rutbem", "Şəxsi rütbəni yoxlamaq"),
        BotCommand("viktorina", "Viktorina oyununu başlatmaq"),
        BotCommand("zer", "1-6 arası zər atmaq")
    ]
    
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("qaydalar", qaydalar_command))
    application.add_handler(CommandHandler("haqqinda", haqqinda_command))
    application.add_handler(CommandHandler("menim_rutbem", my_rank_command))
    application.add_handler(CommandHandler("addpremium", add_premium_command))
    application.add_handler(CommandHandler("removepremium", remove_premium_command))
    application.add_handler(CommandHandler("viktorina", viktorina_command, filters=~filters.ChatType.PRIVATE))
    application.add_handler(CommandHandler("zer", zer_command))
    
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, welcome_new_members))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_all_messages))
    
    try:
        logger.info("Bot işə düşür...")
        await application.initialize()
        await application.bot.set_my_commands(commands)
        await application.updater.start_polling()
        await application.start()
        while True:
            await asyncio.sleep(3600)
    finally:
        logger.info("Bot səliqəli şəkildə dayandırılır...")
        if application.updater and application.updater.is_running():
            await application.updater.stop()
        if application.running:
            await application.stop()
        await application.shutdown()

if __name__ == '__main__':
    asyncio.run(main())
