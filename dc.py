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
BOT_OWNER_ID = 123456789  # <--- BURAYA ÖZ TELEGRAM ID-NİZİ YAZIN!

# --- TƏHLÜKƏSİZLİK YOXLAMASI ---
def run_pre_flight_checks():
    if not DATABASE_URL or not TOKEN:
        logger.critical("--- XƏTA ---")
        logger.critical("DATABASE_URL və ya TELEGRAM_TOKEN tapılmadı. Proqram dayandırılır.")
        sys.exit(1)
    if BOT_OWNER_ID == 123456789:
        logger.warning("XƏBƏRDARLIQ: BOT_OWNER_ID dəyişdirilməyib! Admin əmrləri işləməyəcək.")
    logger.info("Bütün konfiqurasiya dəyişənləri mövcuddur. Bot başladılır...")

# --- BAZA FUNKSİYALARI ---
def init_db():
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cur = conn.cursor()
        # Mövcud mesaj sayğacı cədvəli
        cur.execute("CREATE TABLE IF NOT EXISTS message_counts (id SERIAL PRIMARY KEY, chat_id BIGINT NOT NULL, user_id BIGINT NOT NULL, username TEXT NOT NULL, message_timestamp TIMESTAMPTZ NOT NULL );")
        # YENİ: Premium istifadəçilər üçün cədvəl
        cur.execute("CREATE TABLE IF NOT EXISTS premium_users (user_id BIGINT PRIMARY KEY, added_date TIMESTAMPTZ NOT NULL);")
        conn.commit()
        cur.close()
        conn.close()
        logger.info("Verilənlər bazası cədvəlləri hazırdır.")
    except Exception as e:
        logger.error(f"Baza yaradılarkən xəta: {e}")

# YENİ: Premium statusu yoxlamaq üçün funksiyalar
def is_user_premium(user_id: int) -> bool:
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM premium_users WHERE user_id = %s;", (user_id,))
        result = cur.fetchone()
        cur.close()
        conn.close()
        return result is not None
    except Exception as e:
        logger.error(f"Premium status yoxlanarkən xəta: {e}")
        return False

def add_premium_user(user_id: int) -> bool:
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cur = conn.cursor()
        cur.execute("INSERT INTO premium_users (user_id, added_date) VALUES (%s, %s) ON CONFLICT (user_id) DO NOTHING;", 
                    (user_id, datetime.datetime.now(datetime.timezone.utc)))
        conn.commit()
        cur.close()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"Premium istifadəçi əlavə edərkən xəta: {e}")
        return False

# --- MƏZMUN SİYAHILARI ---
ABOUT_TEXT = "..." # (Qısa olması üçün məzmunu gizlətdim, sizin kodunuzda tamdır)
RULES_TEXT = """...""" # (Qısa olması üçün məzmunu gizlətdim, sizin kodunuzda tamdır)
STORY_DATA = {...} # (Qısa olması üçün məzmunu gizlətdim, sizin kodunuzda tamdır)

# --- VIKTORINA SUALLARI (SADƏ VƏ PREMIUM) ---
SADE_QUIZ_QUESTIONS = [
    {'question': 'Azərbaycanın paytaxtı haradır?', 'options': ['Gəncə', 'Sumqayıt', 'Bakı', 'Naxçıvan'], 'correct': 'Bakı'},
    {'question': 'Hansı planet "Qırmızı Planet" kimi tanınır?', 'options': ['Venera', 'Mars', 'Yupiter', 'Saturn'], 'correct': 'Mars'},
    {'question': 'Suyun kimyəvi formulu nədir?', 'options': ['CO2', 'O2', 'H2O', 'NaCl'], 'correct': 'H2O'},
    # ... Bura bir neçə sadə sual daha əlavə edə bilərsiniz ...
]

PREMIUM_QUIZ_QUESTIONS = [
    {'question': 'Əsərlərini Nizami Gəncəvi imzası ilə yazan şairin əsl adı nədir?', 'options': ['İlyas Yusif oğlu', 'Məhəmməd Füzuli', 'İmadəddin Nəsimi', 'Əliağa Vahid'], 'correct': 'İlyas Yusif oğlu'},
    {'question': 'Leonardo da Vinçinin şah əsəri olan "Mona Liza" tablosu hazırda hansı muzeydə sərgilənir?', 'options': ['Britaniya Muzeyi', 'Vatikan Muzeyi', 'Ermitaj', 'Luvr Muzeyi'], 'correct': 'Luvr Muzeyi'},
    {'question': 'Ən çox "Ən Yaxşı Rejissor" nominasiyasında Oskar alan kimdir?', 'options': ['Steven Spielberg', 'Martin Scorsese', 'James Cameron', 'John Ford'], 'correct': 'John Ford'},
    {'question': '"Formula 1" yarışlarının ən çox dünya çempionu olmuş pilotu kimdir?', 'options': ['Ayrton Senna', 'Michael Schumacher', 'Lewis Hamilton', 'Hər ikisi (Schumacher və Hamilton)'], 'correct': 'Hər ikisi (Schumacher və Hamilton)'},
    # ... Bura yüzlərlə premium, daha çətin və maraqlı sual əlavə edə bilərsiniz ...
]

RIDDLES = [...] # (Qısa olması üçün məzmunu gizlətdim)
NORMAL_TRUTH_QUESTIONS = [...] # (Qısa olması üçün məzmunu gizlətdim)
NORMAL_DARE_TASKS = [...] # (Qısa olması üçün məzmunu gizlətdim)

# ... (get_rank_title, welcome_new_members, is_user_admin, ask_next_player kimi köməkçi funksiyalar dəyişməz qalır) ...
def get_rank_title(count: int) -> str:
    if count <= 100: return "Yeni Üzv 👶"
    elif count <= 500: return "Daimi Sakin 👨‍💻"
    elif count <= 1000: return "Qrup Söhbətçili 🗣️"
    elif count <= 2500: return "Qrup Əfsanəsi 👑"
    else: return "Söhbət Tanrısı ⚡️"
async def welcome_new_members(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.new_chat_members: return
    new_members, chat_title = update.message.new_chat_members, update.message.chat.title
    for member in new_members:
        if member.id == context.bot.id: continue
        welcome_message = (f"Salam, [{member.first_name}](tg://user?id={member.id})! 👋\n"
                         f"**'{chat_title}'** qrupuna xoş gəlmisən!\n\n"
                         "Mən bu qrupun əyləncə və statistika botuyam. Əmrləri görmək üçün /start yaz.")
        await update.message.reply_text(welcome_message, parse_mode='Markdown')
async def is_user_admin(chat_id: int, user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if chat_id == user_id: return True
    try: return user_id in [admin.user.id for admin in await context.bot.get_chat_administrators(chat_id)]
    except Exception: return False
async def ask_next_player(chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    chat_data = context.chat_data
    if not chat_data.get('player_list'):
        await context.bot.send_message(chat_id, "Oyunçu qalmadı. Oyun dayandırılır."); context.chat_data.clear(); return
    chat_data['current_player_index'] = (chat_data.get('current_player_index', -1) + 1) % len(chat_data['player_list'])
    current_player = chat_data['player_list'][chat_data['current_player_index']]
    user_id, first_name = current_player['id'], current_player['name']
    keyboard = [[InlineKeyboardButton("Doğruluq ✅", callback_data=f"game_truth_{user_id}"), InlineKeyboardButton("Cəsarət 😈", callback_data=f"game_dare_{user_id}")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await context.bot.send_message(chat_id, text=f"Sıra sənə çatdı, [{first_name}](tg://user?id={user_id})! Seçimini et:", reply_markup=reply_markup, parse_mode='Markdown')

# --- ƏSAS ƏMRLƏR ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ... (start_command dəyişməz qalır) ...
    user = update.message.from_user
    if context.args and len(context.args) > 0 and context.args[0] == 'macera':
        context.user_data.clear()
        context.user_data['rpg_inventory'] = set()
        await update.message.reply_text("Sənin şəxsi macəran başlayır! ⚔️")
        await show_rpg_node(update, context, 'start_temple'); return
    keyboard = [
        [InlineKeyboardButton("ℹ️ Bot Haqqında Məlumat", callback_data="start_info_about")],
        [InlineKeyboardButton("📜 Bütün Qaydalar", callback_data="start_info_qaydalar")],
        [InlineKeyboardButton("👥 Oyun Qrupumuz", url="https://t.me/+0z5V-OvEMmgzZTFi")],
        [InlineKeyboardButton("👨‍💻 Admin ilə Əlaqə", url="https://t.me/tairhv")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    start_text = "Salam! Mən Oyun Botuyam. 🤖\nAşağıdakı menyudan istədiyin bölməni seç:"
    await update.message.reply_text(start_text, reply_markup=reply_markup)
    
async def haqqinda_command(update: Update, context: ContextTypes.DEFAULT_TYPE): await update.message.reply_text(ABOUT_TEXT, parse_mode='Markdown')
async def qaydalar_command(update: Update, context: ContextTypes.DEFAULT_TYPE): await update.message.reply_text(RULES_TEXT, parse_mode='Markdown')

# --- YENİ ADMIN ƏMRİ ---
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
        await update.message.reply_text("⚠️ Düzgün istifadə: `/addpremium <user_id>`\n*İstifadəçinin rəqəmlərdən ibarət ID-sini daxil edin.*", parse_mode='Markdown')

# --- DƏYİŞDİRİLMİŞ VIKTORINA ƏMRİ ---
async def viktorina_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.chat_data.get('quiz_active'):
        await update.message.reply_text("Artıq aktiv bir viktorina var! Zəhmət olmasa, əvvəlcə onu cavablandırın.")
        return

    keyboard = [
        [InlineKeyboardButton("Viktorina (Sadə) 🌱", callback_data="viktorina_sade")],
        [InlineKeyboardButton("Viktorina (Premium) 👑", callback_data="viktorina_premium")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Zəhmət olmasa, viktorina növünü seçin:", reply_markup=reply_markup)

# --- VIKTORINA OYUNUNU BAŞLADAN FUNKSİYA ---
async def start_quiz_game(update: Update, context: ContextTypes.DEFAULT_TYPE, is_premium: bool):
    message = update.callback_query.message
    
    question_pool = PREMIUM_QUIZ_QUESTIONS if is_premium else SADE_QUIZ_QUESTIONS
    
    if not question_pool:
        await message.edit_text("Bu kateqoriya üçün heç bir sual tapılmadı.")
        return

    # Təkrar sualların qarşısını almaq üçün məntiq
    recently_asked = context.chat_data.get('recently_asked_quiz', deque(maxlen=10))
    possible_questions = [q for q in question_pool if q['question'] not in recently_asked]
    if not possible_questions:
        possible_questions = question_pool
        recently_asked.clear()

    question_data = random.choice(possible_questions)
    recently_asked.append(question_data['question'])
    context.chat_data['recently_asked_quiz'] = recently_asked
    
    question, correct_answer, options = question_data['question'], question_data['correct'], list(question_data['options'])
    random.shuffle(options)
    context.chat_data['correct_quiz_answer'] = correct_answer
    context.chat_data['quiz_active'] = True
    context.chat_data['quiz_lives'] = 3
    
    keyboard = [[InlineKeyboardButton(option, callback_data=f"quiz_{option}")] for option in options]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    quiz_title = "Premium Viktorina 👑" if is_premium else "Sadə Viktorina 🌱"
    lives_text = "❤️❤️❤️"
    
    sent_message = await message.edit_text(
        f"{quiz_title} başladı! 🧠\n\n**Sual:** {question}\n\nQalan cəhdlər: {lives_text}",
        parse_mode='Markdown',
        reply_markup=reply_markup
    )
    context.chat_data['quiz_message_id'] = sent_message.message_id
    
# --- DÜYMƏLƏRİ İDARƏ EDƏN FUNKSİYA (BUTTON HANDLER) ---
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    data = query.data
    await query.answer()

    # YENİ: Viktorina menyusu
    if data == 'viktorina_sade':
        await start_quiz_game(update, context, is_premium=False)
        return
        
    if data == 'viktorina_premium':
        if is_user_premium(user.id):
            await start_quiz_game(update, context, is_premium=True)
        else:
            await query.message.edit_text(
                "⛔ Bu funksiya yalnız premium istifadəçilər üçündür.\n\n"
                "Premium status əldə etmək və daha maraqlı suallarla oynamaq üçün "
                "bot sahibi ilə əlaqə saxlayın: [Admin](tg://user?id={BOT_OWNER_ID})",
                parse_mode='Markdown'
            )
        return

    # ... (qalan button_handler məntiqi dəyişməz qalır) ...
    if data.startswith("start_info_"):
        # ...
        pass # Bu hissə sizin kodunuzda olduğu kimi qalır
        
    if data.startswith("rpg_"):
        # ...
        pass # Bu hissə sizin kodunuzda olduğu kimi qalır

    if data.startswith("quiz_"):
        if not context.chat_data.get('quiz_active'):
            await query.answer("Bu viktorina artıq bitib.", show_alert=True); return
        chosen_answer = data.split('_', 1)[1]; correct_answer = context.chat_data['correct_quiz_answer']
        if chosen_answer == correct_answer:
            await query.answer("Düzdür!", show_alert=False)
            original_text = query.message.text.split('Qalan cəhdlər:')[0].strip()
            await context.bot.edit_message_text(chat_id=query.message.chat_id, message_id=context.chat_data['quiz_message_id'],
                                                text=f"{original_text}\n\n---\n🥳 Qalib: {user.first_name}!\n✅ Düzgün cavab: **{correct_answer}**", parse_mode='Markdown')
            del context.chat_data['quiz_active']; del context.chat_data['correct_quiz_answer']; del context.chat_data['quiz_message_id']; del context.chat_data['quiz_lives']
        else:
            context.chat_data['quiz_lives'] -= 1; lives_left = context.chat_data['quiz_lives']
            await query.answer(f"Səhv cavab! {lives_left} cəhdiniz qaldı.", show_alert=True)
            if lives_left == 0:
                original_text = query.message.text.split('Qalan cəhdlər:')[0].strip()
                await context.bot.edit_message_text(chat_id=query.message.chat_id, message_id=context.chat_data['quiz_message_id'],
                                                    text=f"{original_text}\n\n---\n😔 Məğlub oldunuz! Bütün cəhdlər bitdi.\n✅ Düzgün cavab: **{correct_answer}**", parse_mode='Markdown')
                del context.chat_data['quiz_active']; del context.chat_data['correct_quiz_answer']; del context.chat_data['quiz_message_id']; del context.chat_data['quiz_lives']
            else:
                lives_text = "❤️" * lives_left; original_text = query.message.text.split('Qalan cəhdlər:')[0].strip()
                await context.bot.edit_message_text(chat_id=query.message.chat_id, message_id=context.chat_data['quiz_message_id'],
                                                    text=f"{original_text}\n\nQalan cəhdlər: {lives_text}", reply_markup=query.message.reply_markup, parse_mode='Markdown')
        return

# ... (rating_command, my_rank_command, handle_message kimi digər funksiyalar dəyişməz qalır) ...
async def rating_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    #...
    pass
async def my_rank_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    #...
    pass
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    #...
    pass

# --- ƏSAS MAIN FUNKSİYASI ---
def main() -> None:
    run_pre_flight_checks()
    init_db()
    application = Application.builder().token(TOKEN).build()
    
    # Handler-lərin əlavə edilməsi
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("qaydalar", qaydalar_command))
    application.add_handler(CommandHandler("haqqinda", haqqinda_command))
    
    # YENİ admin əmri
    application.add_handler(CommandHandler("addpremium", add_premium_command))

    # Oyun əmrləri
    # ... (oyun, baslat, novbeti, tapmaca və s. handler-lər olduğu kimi qalır)
    application.add_handler(CommandHandler("viktorina", viktorina_command, filters=~filters.ChatType.PRIVATE))
    
    application.add_handler(CallbackQueryHandler(button_handler))
    # ... (qalan handler-lər olduğu kimi qalır) ...
    
    logger.info("Bot işə düşdü...")
    application.run_polling()

if __name__ == '__main__':
    main()

