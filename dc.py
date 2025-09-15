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

# --- MƏZMUN SİYAHILARI ---
ABOUT_TEXT = "🤖 **Bot Haqqında**\n\nMən qruplar üçün nəzərdə tutulmuş əyləncə və statistika botuyam."
RULES_TEXT = "📜 **Qrup Qaydaları**\n\n1. Reklam etmək qəti qadağandır.\n2. Təhqir, söyüş və aqressiv davranışlara icazə verilmir."

# DOĞRULUQ VƏ CƏSARƏT SUALLARI
SADE_TRUTH_QUESTIONS = ["Uşaqlıqda ən böyük qorxun nə olub?", "Heç kimin bilmədiyi bir bacarığın var?"]
SADE_DARE_TASKS = ["Qrupdakı son mesajı əlifbanın hər hərfi ilə tərsinə yaz.", "Profil şəklini 5 dəqiqəlik bir meyvə şəkli ilə dəyişdir."]
PREMIUM_TRUTH_QUESTIONS = ["Həyatının geri qalanını yalnız bir filmi izləyərək keçirməli olsaydın, hansı filmi seçərdin?", "Sənə ən çox təsir edən kitab hansı olub?"]
PREMIUM_DARE_TASKS = ["Qrupdakı adminlərdən birinə 10 dəqiqəlik \"Ən yaxşı admin\" statusu yaz.", "Səsini dəyişdirərək bir nağıl personajı kimi danış və səsli mesaj göndər."]

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

# --- ADMİN ƏMRLƏRİ ---
async def add_premium_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != BOT_OWNER_ID: await update.message.reply_text("⛔ Bu əmrdən yalnız bot sahibi istifadə edə bilər."); return
    try:
        target_user_id = int(context.args[0])
        if add_premium_user(target_user_id): await update.message.reply_text(f"✅ `{target_user_id}` ID-li istifadəçi premium siyahısına əlavə edildi.", parse_mode='Markdown')
    except (IndexError, ValueError): await update.message.reply_text("⚠️ Düzgün istifadə: `/addpremium <user_id>`", parse_mode='Markdown')

async def remove_premium_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != BOT_OWNER_ID: await update.message.reply_text("⛔ Bu əmrdən yalnız bot sahibi istifadə edə bilər."); return
    try:
        target_user_id = int(context.args[0])
        if remove_premium_user(target_user_id): await update.message.reply_text(f"✅ `{target_user_id}` ID-li istifadəçinin premium statusu geri alındı.", parse_mode='Markdown')
    except (IndexError, ValueError): await update.message.reply_text("⚠️ Düzgün istifadə: `/removepremium <user_id>`", parse_mode='Markdown')

# --- OYUN MƏNTİQİ ---
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
            context.chat_data['recently_asked_quiz_ids'] = []
            cur.execute(query, (is_premium, [0]))
            question_data = cur.fetchone()
        if not question_data:
            await message.edit_text("Bu kateqoriya üçün sual tapılmadı. Adminə bildirin."); return
        q_id, q_text, q_options, q_correct = question_data
        context.chat_data.setdefault('recently_asked_quiz_ids', []).append(q_id)
        context.chat_data['correct_quiz_answer'] = q_correct; context.chat_data['current_question_text'] = q_text
        random.shuffle(q_options)
        keyboard = [[InlineKeyboardButton(option, callback_data=f"quiz_{option}")] for option in q_options]
        keyboard.append([InlineKeyboardButton("Oyunu Bitir ⏹️", callback_data="quiz_stop")])
        quiz_title = "Premium Viktorina 👑" if is_premium else "Sadə Viktorina 🌱"
        lives_text = "❤️" * context.chat_data.get('quiz_lives', 3); score = context.chat_data.get('quiz_score', 0)
        await message.edit_text(f"{quiz_title}\n\n**Xalınız:** {score} ⭐\n**Qalan can:** {lives_text}\n\n**Sual:** {q_text}", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard))
    except Exception as e:
        logger.error(f"Viktorina sualı çəkilərkən xəta: {e}"); await message.edit_text("❌ Viktorina sualını yükləyərkən xəta baş verdi.")
    finally:
        if cur: cur.close()
        if conn: conn.close()
    
async def show_dc_registration_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.callback_query.message; players = context.chat_data.get('dc_players', [])
    player_list_text = "\n\n**Qeydiyyatdan keçənlər:**\n" + ("Heç kim qoşulmayıb." if not players else "\n".join([f"- [{p['name']}](tg://user?id={p['id']})" for p in players]))
    keyboard = [[InlineKeyboardButton("Qeydiyyatdan Keç ✅", callback_data="dc_register")], [InlineKeyboardButton("Oyunu Başlat ▶️", callback_data="dc_start_game")], [InlineKeyboardButton("Oyunu Ləğv Et ⏹️", callback_data="dc_stop_game")]]
    await message.edit_text("**Doğruluq yoxsa Cəsarət?**\n\nOyuna qoşulmaq üçün 'Qeydiyyatdan Keç' düyməsinə basın." + player_list_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)

async def dc_next_turn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.callback_query.message; players = context.chat_data.get('dc_players', [])
    current_index = context.chat_data.get('dc_current_player_index', -1)
    next_index = (current_index + 1) % len(players); context.chat_data['dc_current_player_index'] = next_index
    current_player = players[next_index]; is_premium = context.chat_data.get('dc_is_premium', False)
    truth_callback = "dc_ask_truth_premium" if is_premium else "dc_ask_truth_sade"; dare_callback = "dc_ask_dare_premium" if is_premium else "dc_ask_dare_sade"
    keyboard = [[InlineKeyboardButton("Doğruluq 🤔", callback_data=truth_callback)], [InlineKeyboardButton("Cəsarət 😈", callback_data=dare_callback)], [InlineKeyboardButton("Sıranı Ötür ⏭️", callback_data="dc_skip_turn")]]
    await message.edit_text(f"Sıra sənə çatdı, [{current_player['name']}](tg://user?id={current_player['id']})! Seçimini et:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)

# DÜYMƏLƏRİ İDARƏ EDƏN FUNKSİYA
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; user = query.from_user; data = query.data; chat_id = query.message.chat.id
    await query.answer()

    if data.startswith("start_info") or data == "back_to_start":
        if data == "start_info_about": await query.message.edit_text(text=ABOUT_TEXT, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(" geri", callback_data="back_to_start")]]))
        elif data == "start_info_qaydalar": await query.message.edit_text(text=RULES_TEXT, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(" geri", callback_data="back_to_start")]]))
        elif data == "back_to_start":
            keyboard = [ [InlineKeyboardButton("ℹ️ Bot Haqqında", callback_data="start_info_about")], [InlineKeyboardButton("📜 Qaydalar", callback_data="start_info_qaydalar")] ]
            await query.message.edit_text("Salam! Mən Oyun Botuyam. 🤖\nMenyudan seçin:", reply_markup=InlineKeyboardMarkup(keyboard))
    
    elif data.startswith("viktorina_") or data.startswith("quiz_"):
        quiz_starter_id = context.chat_data.get('quiz_starter_id')
        if quiz_starter_id and user.id != quiz_starter_id: await query.answer("⛔ Bu, sizin başlatdığınız oyun deyil.", show_alert=True); return
        if data == 'viktorina_sade' or data == 'viktorina_premium':
            is_premium_choice = (data == 'viktorina_premium')
            if is_premium_choice and not is_user_premium(user.id): await query.message.edit_text(f"⛔ Bu funksiya yalnız premium istifadəçilər üçündür.", parse_mode='Markdown'); return
            context.chat_data.clear()
            context.chat_data.update({ 'quiz_active': True, 'quiz_is_premium': is_premium_choice, 'quiz_lives': 3, 'quiz_score': 0, 'quiz_message_id': query.message.message_id, 'quiz_starter_id': user.id })
            await ask_next_quiz_question(update, context)
        elif context.chat_data.get('quiz_active'):
            if data == 'quiz_stop':
                score = context.chat_data.get('quiz_score', 0)
                await query.message.edit_text(f"Oyun dayandırıldı! ✅\n\nYekun xalınız: **{score}** ⭐", parse_mode='Markdown'); context.chat_data.clear()
            elif data.startswith("quiz_"):
                chosen_answer = data.split('_', 1)[1]; correct_answer = context.chat_data['correct_quiz_answer']
                if chosen_answer == correct_answer:
                    context.chat_data['quiz_score'] += 1
                    await query.answer(text="✅ Düzdür! Növbəti sual gəlir...", show_alert=False); await asyncio.sleep(2); await ask_next_quiz_question(update, context)
                else:
                    context.chat_data['quiz_lives'] -= 1; lives_left = context.chat_data['quiz_lives']
                    await query.answer(text=f"❌ Səhv cavab! {lives_left} canınız qaldı.", show_alert=True)
                    if lives_left == 0:
                        score = context.chat_data.get('quiz_score', 0)
                        await query.message.edit_text(f"Canlarınız bitdi! 😔\nDüzgün cavab: **{correct_answer}**\nYekun xalınız: **{score}** ⭐", parse_mode='Markdown'); context.chat_data.clear()
                    else:
                        is_premium_mode = context.chat_data.get('quiz_is_premium', False)
                        quiz_title = "Premium Viktorina 👑" if is_premium_mode else "Sadə Viktorina 🌱"
                        lives_text = "❤️" * lives_left; score = context.chat_data.get('quiz_score', 0)
                        question = context.chat_data.get('current_question_text', '')
                        await query.message.edit_text(f"{quiz_title}\n\n**Xalınız:** {score} ⭐\n**Qalan can:** {lives_text}\n\n**Sual:** {question}", parse_mode='Markdown', reply_markup=query.message.reply_markup)
    
    elif data.startswith('dc_'):
        game_starter_id = context.chat_data.get('dc_game_starter_id')
        is_admin_or_starter = user.id == game_starter_id or await is_user_admin(chat_id, user.id, context)
        if data in ['dc_select_sade', 'dc_select_premium', 'dc_start_game', 'dc_stop_game', 'dc_next_turn', 'dc_skip_turn', 'dc_end_game_session']:
            if not is_admin_or_starter: await query.answer("⛔ Bu düymədən yalnız oyunu başladan şəxs və ya adminlər istifadə edə bilər.", show_alert=True); return
        if data in ['dc_select_sade', 'dc_select_premium']:
            is_premium_choice = (data == 'dc_select_premium')
            if is_premium_choice and not is_user_premium(user.id): await query.answer("⛔ Bu rejimi yalnız premium statuslu adminlər başlada bilər.", show_alert=True); return
            context.chat_data.update({'dc_game_active': True, 'dc_is_premium': is_premium_choice, 'dc_players': [], 'dc_current_player_index': -1, 'dc_game_starter_id': user.id})
            await show_dc_registration_message(update, context)
        elif data == 'dc_register':
            if not context.chat_data.get('dc_game_active'): await query.answer("Artıq aktiv oyun yoxdur.", show_alert=True); return
            players = context.chat_data.get('dc_players', [])
            if any(p['id'] == user.id for p in players): await query.answer("Siz artıq qeydiyyatdan keçmisiniz.", show_alert=True)
            else:
                players.append({'id': user.id, 'name': user.first_name})
                await query.answer("Uğurla qoşuldunuz!", show_alert=False)
                await show_dc_registration_message(update, context)
        elif data == 'dc_start_game':
            players = context.chat_data.get('dc_players', [])
            if len(players) < 2: await query.answer("⛔ Oyunun başlaması üçün minimum 2 nəfər qeydiyyatdan keçməlidir.", show_alert=True); return
            random.shuffle(players)
            await dc_next_turn(update, context)
        elif data == 'dc_stop_game':
            await query.message.edit_text("Oyun admin tərəfindən ləğv edildi.")
            for key in list(context.chat_data):
                if key.startswith('dc_'): del context.chat_data[key]
        elif data.startswith('dc_ask_'):
            players = context.chat_data.get('dc_players', [])
            current_player = players[context.chat_data.get('dc_current_player_index', -1)]
            if user.id != current_player['id']: await query.answer("⛔ Bu sənin sıran deyil!", show_alert=True); return
            is_premium = context.chat_data.get('dc_is_premium', False)
            text_to_show = ""
            if 'truth' in data: question = random.choice(PREMIUM_TRUTH_QUESTIONS if is_premium else SADE_TRUTH_QUESTIONS); text_to_show = f"🤔 **Doğruluq:**\n\n`{question}`"
            else: task = random.choice(PREMIUM_DARE_TASKS if is_premium else SADE_DARE_TASKS); text_to_show = f"😈 **Cəsarət:**\n\n`{task}`"
            keyboard = [[InlineKeyboardButton("Növbəti Oyunçu ➡️", callback_data="dc_next_turn"), InlineKeyboardButton("Oyunu Bitir ⏹️", callback_data="dc_end_game_session")]]
            await query.message.edit_text(text_to_show, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)
        elif data == 'dc_next_turn' or data == 'dc_skip_turn':
            if data == 'dc_skip_turn': await query.answer("Sıra ötürülür...", show_alert=False)
            await dc_next_turn(update, context)
        elif data == 'dc_end_game_session':
            players = context.chat_data.get('dc_players', [])
            player_names = ", ".join([p['name'] for p in players])
            end_text = f"**Doğruluq yoxsa Cəsarət** oyunu [{user.first_name}](tg://user?id={user.id}) tərəfindən bitirildi!\n\nİştirak etdiyiniz üçün təşəkkürlər: {player_names}"
            await query.message.edit_text(end_text, parse_mode=ParseMode.MARKDOWN)
            for key in list(context.chat_data):
                if key.startswith('dc_'): del context.chat_data[key]

# MESAJ HANDLERLƏRİ
async def handle_all_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or update.message.chat.type == ChatType.PRIVATE: return
    user = update.message.from_user; chat_id = update.message.chat.id
    conn, cur = None, None
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cur = conn.cursor()
        cur.execute("INSERT INTO message_counts (chat_id, user_id, username, message_timestamp) VALUES (%s, %s, %s, %s);", (chat_id, user.id, user.username or user.first_name, datetime.datetime.now(datetime.timezone.utc)))
        conn.commit()
    except Exception as e: logger.error(f"Mesajı bazaya yazarkən xəta: {e}")
    finally:
        if cur: cur.close()
        if conn: conn.close()

async def word_filter_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text or update.message.chat.type == ChatType.PRIVATE: return
    chat_id = update.message.chat.id; user = update.message.from_user
    if await is_user_admin(chat_id, user.id, context): return
    filtered_words_cache = context.chat_data.get('filtered_words')
    if filtered_words_cache and (datetime.datetime.now() - filtered_words_cache[1]).total_seconds() < 300:
        filtered_words = filtered_words_cache[0]
    else:
        conn, cur = None, None
        try:
            conn = psycopg2.connect(DATABASE_URL, sslmode='require')
            cur = conn.cursor()
            cur.execute("SELECT word FROM filtered_words WHERE chat_id = %s;", (chat_id,))
            filtered_words = {word[0] for word in cur.fetchall()}
            context.chat_data['filtered_words'] = (filtered_words, datetime.datetime.now())
        except Exception as e: logger.error(f"Filtr sözləri çəkilərkən xəta: {e}"); return
        finally:
            if cur: cur.close()
            if conn: conn.close()
    message_text = update.message.text.lower()
    for word in filtered_words:
        if re.search(r'\b' + re.escape(word) + r'\b', message_text, re.IGNORECASE):
            try:
                await update.message.delete()
                warn_reason = f"Qadağan olunmuş sözdən istifadə: '{word}'"
                conn, cur = None, None
                try:
                    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
                    cur = conn.cursor()
                    cur.execute("INSERT INTO warnings (chat_id, user_id, admin_id, reason) VALUES (%s, %s, %s, %s);", (chat_id, user.id, context.bot.id, warn_reason))
                    conn.commit()
                except Exception as e: logger.error(f"Silent warn error: {e}")
                finally:
                    if cur: cur.close()
                    if conn: conn.close()
            except Exception as e: logger.error(f"Mesaj silinərkən xəta: {e}")
            break

# --- ƏSAS MAIN FUNKSİYASI ---
async def main() -> None:
    run_pre_flight_checks()
    init_db()
    application = Application.builder().token(TOKEN).build()
    
    commands = [
        BotCommand("start", "Əsas menyunu açmaq"),
        BotCommand("qaydalar", "İstifadə təlimatı və qaydalar"),
        BotCommand("haqqinda", "Bot haqqında məlumat"),
        BotCommand("viktorina", "Viktorina oyununu başlatmaq"),
        BotCommand("dcoyun", "Doğruluq/Cəsarət oyununu başlatmaq (Admin)"),
    ]
    
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("qaydalar", qaydalar_command))
    application.add_handler(CommandHandler("haqqinda", haqqinda_command))
    application.add_handler(CommandHandler("dcoyun", dcoyun_command))
    application.add_handler(CommandHandler("addpremium", add_premium_command))
    application.add_handler(CommandHandler("removepremium", remove_premium_command))
    application.add_handler(CommandHandler("viktorina", viktorina_command, filters=~filters.ChatType.PRIVATE))
    
    application.add_handler(CallbackQueryHandler(button_handler))
    
    await application.run_polling()

if __name__ == '__main__':
    asyncio.run(main())

