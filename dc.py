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
- `/menim_rutbem` - Qrupdakı mesaj sayınızı və rütbənizi yoxlamaq.
- `/liderler` - Bu ay ən çox mesaj yazan 10 nəfərin siyahısı.
- `/zer` - 1-dən 6-ya qədər təsadüfi zər atmaq.
- `/haqqinda` - Bot haqqında qısa məlumat.
- `/qaydalar` - Bu təlimatı yenidən görmək.

---
### 🎮 **Oyun Əmrləri**
- `/viktorina` - Bilik yarışması olan viktorina oyununu başladır.
- `/dcoyun` - "Doğruluq yoxsa Cəsarət?" oyununu başladır. **(Yalnız adminlər başlada bilər)**

---
### 🛡️ **Adminlər Üçün İdarəetmə Əmrləri**
- `/adminpanel` - Bütün admin əmrlərini görmək üçün bu əmri istifadə edin.
---
"""
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
    if user_is_premium: reply_text += f"🚀 Premium ilə hesablanmış xalın: **{effective_message_count}**\n"
    reply_text += f"🏆 Rütbən: **{rank_title}**\n\nDaha çox mesaj yazaraq yeni rütbələr qazan!"
    await update.message.reply_text(reply_text, parse_mode='Markdown')

async def zer_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    dice_roll = random.randint(1, 6)
    await update.message.reply_text(f"🎲 Zər atıldı və düşən rəqəm: **{dice_roll}**", parse_mode='Markdown')

async def liderler_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type == ChatType.PRIVATE: await update.message.reply_text("Bu əmr yalnız qruplarda işləyir."); return
    chat_id = update.message.chat.id
    leaderboard_text = f"🏆 **'{update.message.chat.title}'**\nBu ayın ən aktiv 10 istifadəçisi:\n\n"
    conn, cur = None, None
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cur = conn.cursor()
        cur.execute(""" SELECT user_id, COUNT(*) as msg_count FROM message_counts WHERE chat_id = %s AND message_timestamp >= date_trunc('month', NOW()) GROUP BY user_id ORDER BY msg_count DESC LIMIT 10; """, (chat_id,))
        leaders = cur.fetchall()
        if not leaders: await update.message.reply_text("Bu ay hələ heç kim mesaj yazmayıb. İlk sən ol!"); return
        leader_lines = []
        for i, (user_id, msg_count) in enumerate(leaders):
            try:
                member = await context.bot.get_chat_member(chat_id, user_id)
                user_name = member.user.first_name
            except Exception: user_name = f"İstifadəçi ({user_id})"
            premium_icon = " 👑" if is_user_premium(user_id) else ""
            place_icon = ["🥇", "🥈", "🥉"][i] if i < 3 else f"**{i+1}.**"
            leader_lines.append(f"{place_icon} {user_name}{premium_icon} - **{msg_count}** mesaj")
        await update.message.reply_text(leaderboard_text + "\n".join(leader_lines), parse_mode='Markdown')
    except Exception as e: logger.error(f"Liderlər cədvəli göstərilərkən xəta: {e}"); await update.message.reply_text("❌ Liderlər cədvəlini göstərərkən xəta baş verdi.")
    finally:
        if cur: cur.close()
        if conn: conn.close()
        
async def dcoyun_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id; chat_id = update.message.chat.id
    if update.message.chat.type == ChatType.PRIVATE: await update.message.reply_text("Bu oyunu yalnız qruplarda oynamaq olar."); return
    if not await is_user_admin(chat_id, user_id, context): await update.message.reply_text("⛔ Bu oyunu yalnız qrup adminləri başlada bilər."); return
    if context.chat_data.get('dc_game_active'): await update.message.reply_text("Artıq aktiv bir 'Doğruluq yoxsa Cəsarət?' oyunu var."); return
    context.chat_data['dc_game_starter_id'] = user_id
    keyboard = [[InlineKeyboardButton("Doğruluq Cəsarət (sadə)", callback_data="dc_select_sade")], [InlineKeyboardButton("Doğruluq Cəsarət (Premium👑)", callback_data="dc_select_premium")]]
    await update.message.reply_text("Doğruluq Cəsarət oyununa xoş gəlmisiniz👋", reply_markup=InlineKeyboardMarkup(keyboard))

# --- ADMİN VƏ MODERASİYA ƏMRLƏRİ ---
async def adminpanel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user; chat_id = update.message.chat.id
    if not await is_user_admin(chat_id, user.id, context): return
    admin_help_text = """🛡️ **Admin İdarəetmə Paneli**\n\n**Söz Filtrasiyası:**\n- `/addword <söz>` - Filtrə söz əlavə edir.\n- `/delword <söz>` - Filtrdən söz silir.\n- `/listwords` - Filtr siyahısına baxır.\n\n**İstifadəçi İdarəetməsi:**\n- `/warn <səbəb>` - Mesaja cavab verərək xəbərdarlıq edir.\n- `/warnings` - Mesaja cavab verərək xəbərdarlıqlara baxır.\n- `/delwarn` - Mesaja cavab verərək son xəbərdarlığı silir.\n- `/mute <müddət> [səbəb]` - Mesaja cavab verərək səssizləşdirir (`30m`, `2h`, `1d`).\n- `/unmute` - Mesaja cavab verərək səssiz rejimini ləğv edir."""
    if user.id == BOT_OWNER_ID:
        admin_help_text += "\n\n---\n👑 **Bot Sahibi Paneli**\n- `/addpremium <user_id>` - İstifadəçiyə premium status verir.\n- `/removepremium <user_id>` - İstifadəçidən premium statusu geri alır."
    await update.message.reply_text(admin_help_text, parse_mode=ParseMode.MARKDOWN)

async def add_premium_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != BOT_OWNER_ID: await update.message.reply_text("⛔ Bu əmrdən yalnız bot sahibi istifadə edə bilər."); return
    try:
        target_user_id = int(context.args[0])
        if add_premium_user(target_user_id): await update.message.reply_text(f"✅ `{target_user_id}` ID-li istifadəçi uğurla premium siyahısına əlavə edildi.", parse_mode='Markdown')
        else: await update.message.reply_text("❌ İstifadəçini əlavə edərkən xəta baş verdi.")
    except (IndexError, ValueError): await update.message.reply_text("⚠️ Düzgün istifadə: `/addpremium <user_id>`", parse_mode='Markdown')

async def remove_premium_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != BOT_OWNER_ID: await update.message.reply_text("⛔ Bu əmrdən yalnız bot sahibi istifadə edə bilər."); return
    try:
        target_user_id = int(context.args[0])
        if remove_premium_user(target_user_id): await update.message.reply_text(f"✅ `{target_user_id}` ID-li istifadəçinin premium statusu uğurla geri alındı.", parse_mode='Markdown')
        else: await update.message.reply_text("❌ Belə bir premium istifadəçi tapılmadı və ya xəta baş verdi.", parse_mode='Markdown')
    except (IndexError, ValueError): await update.message.reply_text("⚠️ Düzgün istifadə: `/removepremium <user_id>`", parse_mode='Markdown')

async def addword_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id; chat_id = update.message.chat.id
    if not await is_user_admin(chat_id, user_id, context): await update.message.reply_text("⛔ Bu əmrdən yalnız adminlər istifadə edə bilər."); return
    if not context.args: await update.message.reply_text("⚠️ İstifadə qaydası: `/addword <söz>`"); return
    word_to_add = " ".join(context.args).lower()
    conn, cur = None, None
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cur = conn.cursor()
        cur.execute("INSERT INTO filtered_words (chat_id, word) VALUES (%s, %s) ON CONFLICT DO NOTHING;", (chat_id, word_to_add))
        conn.commit()
        context.chat_data.pop('filtered_words', None)
        await update.message.reply_text(f"✅ `{word_to_add}` sözü/ifadəsi filtr siyahısına əlavə edildi.")
    except Exception as e: logger.error(f"Söz əlavə edərkən xəta: {e}"); await update.message.reply_text("❌ Xəta baş verdi.")
    finally:
        if cur: cur.close()
        if conn: conn.close()

async def delword_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id; chat_id = update.message.chat.id
    if not await is_user_admin(chat_id, user_id, context): await update.message.reply_text("⛔ Bu əmrdən yalnız adminlər istifadə edə bilər."); return
    if not context.args: await update.message.reply_text("⚠️ İstifadə qaydası: `/delword <söz>`"); return
    word_to_del = " ".join(context.args).lower()
    conn, cur = None, None
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cur = conn.cursor()
        cur.execute("DELETE FROM filtered_words WHERE chat_id = %s AND word = %s;", (chat_id, word_to_del))
        conn.commit()
        context.chat_data.pop('filtered_words', None)
        if cur.rowcount > 0: await update.message.reply_text(f"✅ `{word_to_del}` sözü/ifadəsi filtr siyahısından silindi.")
        else: await update.message.reply_text(f"ℹ️ Bu söz/ifadə siyahıda tapılmadı.")
    except Exception as e: logger.error(f"Söz silinərkən xəta: {e}"); await update.message.reply_text("❌ Xəta baş verdi.")
    finally:
        if cur: cur.close()
        if conn: conn.close()

async def listwords_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id; chat_id = update.message.chat.id
    if not await is_user_admin(chat_id, user_id, context): await update.message.reply_text("⛔ Bu əmrdən yalnız adminlər istifadə edə bilər."); return
    conn, cur = None, None
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cur = conn.cursor()
        cur.execute("SELECT word FROM filtered_words WHERE chat_id = %s ORDER BY word;", (chat_id,))
        words = cur.fetchall()
        if not words: await update.message.reply_text("Bu qrup üçün filtr siyahısı boşdur.")
        else:
            word_list = ", ".join([f"`{w[0]}`" for w in words])
            await update.message.reply_text(f"🚫 **Qadağan olunmuş sözlər:**\n{word_list}", parse_mode=ParseMode.MARKDOWN)
    except Exception as e: logger.error(f"Söz siyahısı göstərilərkən xəta: {e}"); await update.message.reply_text("❌ Xəta baş verdi.")
    finally:
        if cur: cur.close()
        if conn: conn.close()

async def warn_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    admin = update.message.from_user; chat_id = update.message.chat.id
    if not await is_user_admin(chat_id, admin.id, context): await update.message.reply_text("⛔ Bu əmrdən yalnız adminlər istifadə edə bilər."); return
    if not update.message.reply_to_message: await update.message.reply_text("⚠️ Xəbərdarlıq etmək üçün bir mesaja cavab verməlisiniz."); return
    user_to_warn = update.message.reply_to_message.from_user
    if user_to_warn.id == context.bot.id or await is_user_admin(chat_id, user_to_warn.id, context):
        await update.message.reply_text("ℹ️ Adminlərə xəbərdarlıq etmək olmaz."); return
    reason = " ".join(context.args) if context.args else "Qayda pozuntusu"
    conn, cur = None, None
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cur = conn.cursor()
        cur.execute("INSERT INTO warnings (chat_id, user_id, admin_id, reason) VALUES (%s, %s, %s, %s);", (chat_id, user_to_warn.id, admin.id, reason))
        cur.execute("SELECT COUNT(*) FROM warnings WHERE chat_id = %s AND user_id = %s;", (chat_id, user_to_warn.id))
        warn_count = cur.fetchone()[0]
        conn.commit()
        await update.message.reply_text(f"❗️ [{user_to_warn.first_name}](tg://user?id={user_to_warn.id}) admin [{admin.first_name}](tg://user?id={admin.id}) tərəfindən xəbərdarlıq aldı.\n**Səbəb:** {reason}\n**Ümumi xəbərdarlıq:** {warn_count}/{WARN_LIMIT}", parse_mode=ParseMode.MARKDOWN)
        if warn_count >= WARN_LIMIT:
            mute_duration = datetime.timedelta(days=1)
            until_date = datetime.datetime.now(datetime.timezone.utc) + mute_duration
            await context.bot.restrict_chat_member(chat_id, user_to_warn.id, ChatPermissions(can_send_messages=False), until_date=until_date)
            await update.message.reply_text(f"🚫 [{user_to_warn.first_name}](tg://user?id={user_to_warn.id}) {WARN_LIMIT} xəbərdarlığa çatdığı üçün 24 saatlıq səssizləşdirildi.", parse_mode=ParseMode.MARKDOWN)
    except Exception as e: logger.error(f"Xəbərdarlıq zamanı xəta: {e}"); await update.message.reply_text("❌ Xəta baş verdi.")
    finally:
        if cur: cur.close()
        if conn: conn.close()

async def warnings_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    admin = update.message.from_user; chat_id = update.message.chat.id
    if not await is_user_admin(chat_id, admin.id, context): await update.message.reply_text("⛔ Bu əmrdən yalnız adminlər istifadə edə bilər."); return
    if not update.message.reply_to_message: await update.message.reply_text("⚠️ Bir istifadəçinin xəbərdarlıqlarını görmək üçün onun mesajına cavab verməlisiniz."); return
    user_to_check = update.message.reply_to_message.from_user
    conn, cur = None, None
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cur = conn.cursor()
        cur.execute("SELECT reason, timestamp FROM warnings WHERE chat_id = %s AND user_id = %s ORDER BY timestamp DESC;", (chat_id, user_to_check.id))
        user_warnings = cur.fetchall()
        keyboard = None
        if not user_warnings:
            response_text = f"✅ [{user_to_check.first_name}](tg://user?id={user_to_check.id}) adlı istifadəçinin heç bir xəbərdarlığı yoxdur."
        else:
            response_text = f"📜 [{user_to_check.first_name}](tg://user?id={user_to_check.id}) adlı istifadəçinin xəbərdarlıqları ({len(user_warnings)}/{WARN_LIMIT}):\n\n"
            for i, (reason, ts) in enumerate(user_warnings): response_text += f"**{i+1}. Səbəb:** {reason}\n   *Tarix:* {ts.strftime('%Y-%m-%d %H:%M')}\n"
            keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🗑️ Son xəbərdarlığı sil", callback_data=f"delwarn_{user_to_check.id}")]])
        await update.message.reply_text(response_text, parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard)
    except Exception as e: logger.error(f"Xəbərdarlıqlar göstərilərkən xəta: {e}"); await update.message.reply_text("❌ Xəta baş verdi.")
    finally:
        if cur: cur.close()
        if conn: conn.close()

async def delwarn_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    admin = update.message.from_user; chat_id = update.message.chat.id
    if not await is_user_admin(chat_id, admin.id, context): await update.message.reply_text("⛔ Bu əmrdən yalnız adminlər istifadə edə bilər."); return
    if not update.message.reply_to_message: await update.message.reply_text("⚠️ Xəbərdarlığı silmək üçün bir istifadəçinin mesajına cavab verməlisiniz."); return
    user_to_clear = update.message.reply_to_message.from_user
    if delete_last_warning(chat_id, user_to_clear.id):
        await update.message.reply_text(f"✅ [{user_to_clear.first_name}](tg://user?id={user_to_clear.id}) adlı istifadəçinin son xəbərdarlığı [{admin.first_name}](tg://user?id={admin.id}) tərəfindən silindi.", parse_mode=ParseMode.MARKDOWN)
    else:
        await update.message.reply_text(f"ℹ️ [{user_to_clear.first_name}](tg://user?id={user_to_clear.id}) adlı istifadəçinin aktiv xəbərdarlığı tapılmadı.", parse_mode=ParseMode.MARKDOWN)

async def mute_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    admin = update.message.from_user; chat_id = update.message.chat.id
    if not await is_user_admin(chat_id, admin.id, context): await update.message.reply_text("⛔ Bu əmrdən yalnız adminlər istifadə edə bilər."); return
    if not update.message.reply_to_message or len(context.args) < 1:
        await update.message.reply_text("⚠️ İstifadə: Bir mesaja cavab olaraq `/mute <müddət> [səbəb]`\nNümunə: `/mute 1h spam`"); return
    user_to_mute = update.message.reply_to_message.from_user
    if user_to_mute.id == context.bot.id or await is_user_admin(chat_id, user_to_mute.id, context):
        await update.message.reply_text("ℹ️ Adminləri səssizləşdirmək olmaz."); return
    duration = parse_duration(context.args[0])
    if not duration: await update.message.reply_text("⚠️ Yanlış müddət formatı. Nümunələr: `30m`, `2h`, `1d`"); return
    until_date = datetime.datetime.now(datetime.timezone.utc) + duration
    try:
        await context.bot.restrict_chat_member(chat_id, user_to_mute.id, ChatPermissions(can_send_messages=False), until_date=until_date)
        await update.message.reply_text(f"🚫 [{user_to_mute.first_name}](tg://user?id={user_to_mute.id}) {context.args[0]} müddətinə səssizləşdirildi.", parse_mode=ParseMode.MARKDOWN)
    except Exception as e: logger.error(f"Mute zamanı xəta: {e}"); await update.message.reply_text("❌ Xəta baş verdi. Botun admin olduğundan və səlahiyyəti olduğundan əmin olun.")

async def unmute_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    admin = update.message.from_user; chat_id = update.message.chat.id
    if not await is_user_admin(chat_id, admin.id, context): await update.message.reply_text("⛔ Bu əmrdən yalnız adminlər istifadə edə bilər."); return
    if not update.message.reply_to_message: await update.message.reply_text("⚠️ Səssiz rejimini ləğv etmək üçün bir mesaja cavab verməlisiniz."); return
    user_to_unmute = update.message.reply_to_message.from_user
    try:
        await context.bot.restrict_chat_member(chat_id, user_to_unmute.id, ChatPermissions(can_send_messages=True, can_send_media_messages=True, can_send_other_messages=True, can_add_web_page_previews=True))
        await update.message.reply_text(f"✅ [{user_to_unmute.first_name}](tg://user?id={user_to_unmute.id}) üçün səssiz rejimi ləğv edildi.", parse_mode=ParseMode.MARKDOWN)
    except Exception as e: logger.error(f"Unmute zamanı xəta: {e}"); await update.message.reply_text("❌ Xəta baş verdi.")

async def addquestions_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != BOT_OWNER_ID:
        await update.message.reply_text("⛔ Bu əmrdən yalnız bot sahibi istifadə edə bilər."); return
    await update.message.reply_text("⏳ Suallar bazaya əlavə edilir, bu bir neçə saniyə çəkə bilər...")
    
    all_simple_questions = [
        {'question': 'Azərbaycanın paytaxtı haradır?', 'options': ['Gəncə', 'Sumqayıt', 'Bakı', 'Naxçıvan'], 'correct': 'Bakı'},
        {'question': 'Bir ildə neçə fəsil var?', 'options': ['2', '3', '4', '5'], 'correct': '4'},
        {'question': 'Göy qurşağında neçə rəng var?', 'options': ['5', '6', '7', '8'], 'correct': '7'},
        {'question': 'İngilis əlifbasında neçə hərf var?', 'options': ['24', '25', '26', '27'], 'correct': '26'},
        {'question': 'Bir saatda neçə dəqiqə var?', 'options': ['30', '60', '90', '100'], 'correct': '60'},
        {'question': 'Hansı heyvan meşələrin kralı sayılır?', 'options': ['Pələng', 'Ayı', 'Canavar', 'Şir'], 'correct': 'Şir'},
        {'question': 'Qırmızı və sarı rəngləri qarışdırdıqda hansı rəng alınır?', 'options': ['Yaşıl', 'Bənövşəyi', 'Narıncı', 'Qəhvəyi'], 'correct': 'Narıncı'},
        {'question': 'Yeni il hansı ayda başlayır?', 'options': ['Dekabr', 'Yanvar', 'Fevral', 'Mart'], 'correct': 'Yanvar'},
        {'question': 'Üçbucağın neçə tərəfi var?', 'options': ['2', '3', '4', '5'], 'correct': '3'},
        {'question': 'Ən böyük materik hansıdır?', 'options': ['Afrika', 'Avropa', 'Asiya', 'Şimali Amerika'], 'correct': 'Asiya'},
        {'question': 'İnsan bədənində ən çox rast gəlinən element hansıdır?', 'options': ['Dəmir', 'Kalsium', 'Oksigen', 'Karbon'], 'correct': 'Oksigen'},
        {'question': 'Hansı ölkənin bayrağında aypara və ulduz var?', 'options': ['Yaponiya', 'Kanada', 'Türkiyə', 'İtaliya'], 'correct': 'Türkiyə'},
        {'question': 'Qədim Misirdə hökmdarlar necə adlanırdı?', 'options': ['İmperator', 'Sultan', 'Firon', 'Kral'], 'correct': 'Firon'},
        {'question': 'İlk insan Aya neçənci ildə ayaq basıb?', 'options': ['1965', '1969', '1972', '1961'], 'correct': '1969'},
        {'question': 'Azadlıq Heykəli ABŞ-a hansı ölkə tərəfindən hədiyyə edilib?', 'options': ['Böyük Britaniya', 'Almaniya', 'Fransa', 'İspaniya'], 'correct': 'Fransa'},
        {'question': 'Yazını ilk dəfə hansı sivilizasiya icad etmişdir?', 'options': ['Qədim Misir', 'Qədim Yunanıstan', 'Şumerlər', 'Qədim Çin'], 'correct': 'Şumerlər'},
        {'question': 'Amerikanı kim kəşf etmişdir?', 'options': ['Vasco da Gama', 'Ferdinand Magellan', 'Xristofor Kolumb', 'James Cook'], 'correct': 'Xristofor Kolumb'},
        {'question': 'İkinci Dünya Müharibəsi neçənci ildə başlamışdır?', 'options': ['1935', '1939', '1941', '1945'], 'correct': '1939'},
        {'question': 'ABŞ-ın ilk prezidenti kim olmuşdur?', 'options': ['Abraham Lincoln', 'Tomas Cefferson', 'Corc Vaşqton', 'Con Adams'], 'correct': 'Corc Vaşqton'},
        {'question': 'Azərbaycan neçənci ildə müstəqilliyini bərpa etmişdir?', 'options': ['1989', '1990', '1991', '1993'], 'correct': '1991'},
        {'question': 'Hansı şəhər su üzərində qurulub?', 'options': ['Florensiya', 'Verona', 'Roma', 'Venesiya'], 'correct': 'Venesiya'},
        {'question': 'Roma İmperiyasının ilk imperatoru kim olmuşdur?', 'options': ['Yuli Sezar', 'Oktavian Avqust', 'Neron', 'Mark Antoni'], 'correct': 'Oktavian Avqust'},
        {'question': 'Azərbaycan Xalq Cümhuriyyəti neçənci ildə qurulmuşdur?', 'options': ['1920', '1918', '1991', '1905'], 'correct': '1918'},
        {'question': 'Hansı sərkərdə "Gəldim, Gördüm, Qələbə Çaldım" sözlərini demişdir?', 'options': ['Böyük İskəndər', 'Yuli Sezar', 'Napoleon Bonapart', 'Atilla'], 'correct': 'Yuli Sezar'},
        {'question': 'Suyun kimyəvi formulu nədir?', 'options': ['CO2', 'O2', 'H2O', 'NaCl'], 'correct': 'H2O'},
        {'question': 'Hansı planet "Qırmızı Planet" kimi tanınır?', 'options': ['Venera', 'Mars', 'Yupiter', 'Saturn'], 'correct': 'Mars'},
        {'question': 'İnsan bədənində neçə sümük var?', 'options': ['186', '206', '226', '256'], 'correct': '206'},
        {'question': 'Yerin təbii peyki hansıdır?', 'options': ['Mars', 'Venera', 'Ay', 'Fobos'], 'correct': 'Ay'},
        {'question': 'Qravitasiya qanununu kim kəşf etmişdir?', 'options': ['Qalileo Qaliley', 'İsaak Nyuton', 'Nikola Tesla', 'Arximed'], 'correct': 'İsaak Nyuton'},
        {'question': 'Hansı vitamin günəş şüası vasitəsilə bədəndə yaranır?', 'options': ['Vitamin C', 'Vitamin A', 'Vitamin B12', 'Vitamin D'], 'correct': 'Vitamin D'},
        {'question': 'Səs hansı mühitdə yayıla bilmir?', 'options': ['Suda', 'Havada', 'Metalda', 'Vakuumda'], 'correct': 'Vakuumda'},
        {'question': 'Atmosferin Yer kürəsini qoruyan təbəqəsi necə adlanır?', 'options': ['Troposfer', 'Stratosfer', 'Ozon təbəqəsi', 'Mezosfer'], 'correct': 'Ozon təbəqəsi'},
        {'question': 'Fotosintez zamanı bitkilər hansı qazı udur?', 'options': ['Oksigen', 'Azot', 'Karbon qazı', 'Hidrogen'], 'correct': 'Karbon qazı'},
        {'question': 'Dünyanın ən hündür dağı hansıdır?', 'options': ['K2', 'Everest', 'Elbrus', 'Monblan'], 'correct': 'Everest'},
        {'question': 'Günəş sistemində ən böyük planet hansıdır?', 'options': ['Saturn', 'Yupiter', 'Neptun', 'Uran'], 'correct': 'Yupiter'},
        {'question': 'Havanın əsas tərkib hissəsi hansı qazdır?', 'options': ['Oksigen', 'Karbon qazı', 'Azot', 'Hidrogen'], 'correct': 'Azot'},
        {'question': 'Kompüterin "beyni" adlanan hissəsi hansıdır?', 'options': ['Monitor', 'RAM', 'Prosessor (CPU)', 'Sərt Disk'], 'correct': 'Prosessor (CPU)'},
        {'question': 'Telefonu kim icad etmişdir?', 'options': ['Tomas Edison', 'Nikola Tesla', 'Aleksandr Bell', 'Samuel Morze'], 'correct': 'Aleksandr Bell'},
        {'question': '"Facebook" sosial şəbəkəsinin qurucusu kimdir?', 'options': ['Bill Gates', 'Steve Jobs', 'Larry Page', 'Mark Zuckerberg'], 'correct': 'Mark Zuckerberg'},
        {'question': '"iPhone" smartfonlarını hansı şirkət istehsal edir?', 'options': ['Samsung', 'Google', 'Apple', 'Huawei'], 'correct': 'Apple'},
        {'question': 'PDF formatının tam adı nədir?', 'options': ['Portable Document Format', 'Printable Document File', 'Personal Data File', 'Public Document Format'], 'correct': 'Portable Document Format'},
        {'question': 'İlk elektrik lampasını kim icad edib?', 'options': ['Nikola Tesla', 'Aleksandr Bell', 'Tomas Edison', 'Benjamin Franklin'], 'correct': 'Tomas Edison'},
        {'question': 'URL-də "www" nə deməkdir?', 'options': ['World Wide Web', 'Web World Wide', 'World Web Wide', 'Wide World Web'], 'correct': 'World Wide Web'},
        {'question': 'Hansı şirkət "Windows" əməliyyat sistemini hazırlayır?', 'options': ['Apple', 'Google', 'Microsoft', 'IBM'], 'correct': 'Microsoft'},
        {'question': 'İlk uğurlu təyyarəni kimlər icad etmişdir?', 'options': ['Lumiere qardaşları', 'Wright qardaşları', 'Montgolfier qardaşları', 'Grimm qardaşları'], 'correct': 'Wright qardaşları'},
        {'question': 'Kompüterdə məlumatın ən kiçik ölçü vahidi nədir?', 'options': ['Bayt', 'Bit', 'Meqabayt', 'Geqabayt'], 'correct': 'Bit'},
        {'question': 'Hansı proqram cədvəllər və hesablamalar üçün istifadə olunur?', 'options': ['Word', 'PowerPoint', 'Photoshop', 'Excel'], 'correct': 'Excel'},
        {'question': 'Hansı sosial şəbəkənin loqosu quş şəklindədir?', 'options': ['Facebook', 'Instagram', 'Twitter (X)', 'LinkedIn'], 'correct': 'Twitter (X)'},
        {'question': 'Futbolda bir komandada neçə oyunçu olur?', 'options': ['9', '10', '11', '12'], 'correct': '11'},
        {'question': 'Olimpiya oyunlarının simvolu olan halqaların sayı neçədir?', 'options': ['4', '5', '6', '7'], 'correct': '5'},
        {'question': 'Futbol üzrə Dünya Çempionatı neçə ildən bir keçirilir?', 'options': ['2', '3', '4', '5'], 'correct': '4'},
        {'question': 'Hansı idman növündə topu səbətə atmaq lazımdır?', 'options': ['Voleybol', 'Həndbol', 'Basketbol', 'Su polosu'], 'correct': 'Basketbol'},
        {'question': 'Şahmat taxtasında neçə xana var?', 'options': ['36', '49', '64', '81'], 'correct': '64'},
        {'question': 'Hansı ölkə futbol üzrə ən çox Dünya Çempionu olub?', 'options': ['Almaniya', 'İtaliya', 'Argentina', 'Braziliya'], 'correct': 'Braziliya'},
        {'question': 'Boks rinqi hansı həndəsi fiqurdadır?', 'options': ['Dairə', 'Kvadrat', 'Üçbucaq', 'Romb'], 'correct': 'Kvadrat'},
        {'question': '"Dəmir Mayk" ləqəbli məşhur boksçu kimdir?', 'options': ['Məhəmməd Əli', 'Mayk Tayson', 'Floyd Mayweather', 'Rokki Marçiano'], 'correct': 'Mayk Tayson'},
        {'question': 'Şahmatda ən güclü fiqur hansıdır?', 'options': ['At', 'Fil', 'Vəzir', 'Top'], 'correct': 'Vəzir'},
        {'question': 'Tour de France nə yarışıdır?', 'options': ['Qaçış marafonu', 'Avtomobil yarışı', 'Velosiped turu', 'At yarışı'], 'correct': 'Velosiped turu'},
        {'question': '2022-ci il Futbol üzrə Dünya Çempionatının qalibi hansı ölkə oldu?', 'options': ['Fransa', 'Xorvatiya', 'Argentina', 'Braziliya'], 'correct': 'Argentina'},
        {'question': 'Müasir Olimpiya Oyunlarının banisi kim hesab olunur?', 'options': ['Pyerr de Kuberten', 'Juan Antonio Samaranch', 'Avery Brundage', 'Herakl'], 'correct': 'Pyerr de Kuberten'},
    ]
    
    all_premium_questions = [
        # Mədəniyyət və İncəsənət (20 sual)
        {'question': 'Əsərlərini Nizami Gəncəvi imzası ilə yazan şairin əsl adı nədir?', 'options': ['İlyas Yusif oğlu', 'Məhəmməd Füzuli', 'İmadəddin Nəsimi', 'Əliağa Vahid'], 'correct': 'İlyas Yusif oğlu'},
        {'question': 'Leonardo da Vinçinin "Mona Liza" tablosu hansı muzeydədir?', 'options': ['Britaniya Muzeyi', 'Vatikan Muzeyi', 'Ermitaj', 'Luvr Muzeyi'], 'correct': 'Luvr Muzeyi'},
        {'question': 'Üzeyir Hacıbəyovun "Koroğlu" operası neçə pərdədən ibarətdir?', 'options': ['3', '4', '5', '6'], 'correct': '5'},
        {'question': '"The Beatles" qrupu hansı şəhərdə yaranıb?', 'options': ['London', 'Mançester', 'Liverpul', 'Birminhem'], 'correct': 'Liverpul'},
        {'question': 'Dahi ispan rəssam Pablo Pikassonun tam adı neçə sözdən ibarətdir?', 'options': ['5', '11', '17', '23'], 'correct': '23'},
        {'question': '"Don Kixot" əsərinin müəllifi kimdir?', 'options': ['Uilyam Şekspir', 'Migel de Servantes', 'Dante Aligyeri', 'Françesko Petrarka'], 'correct': 'Migel de Servantes'},
        {'question': 'Hansı bəstəkar "Ay işığı sonatası" ilə məşhurdur?', 'options': ['Motsart', 'Bax', 'Bethoven', 'Şopen'], 'correct': 'Bethoven'},
        {'question': 'Azərbaycanın xalq artisti Rəşid Behbudov hansı ölkədə anadan olub?', 'options': ['Azərbaycan', 'İran', 'Türkiyə', 'Gürcüstan'], 'correct': 'Gürcüstan'},
        {'question': 'Fridrix Şillerin "Qaçaqlar" dramı əsasında Üzeyir Hacıbəyov hansı operettanı bəstələyib?', 'options': ['Leyli və Məcnun', 'O olmasın, bu olsun', 'Arşın mal alan', 'Əsli və Kərəm'], 'correct': 'O olmasın, bu olsun'},
        {'question': '"Rokki" filminin baş rol ifaçısı kimdir?', 'options': ['Arnold Şvartsenegger', 'Silvestr Stallone', 'Brüs Uillis', 'Jan-Klod Van Damm'], 'correct': 'Silvestr Stallone'},
        {'question': '"Sehrli fleyta" operasının müəllifi kimdir?', 'options': ['Vivaldi', 'Hendel', 'Motsart', 'Haydn'], 'correct': 'Motsart'},
        {'question': 'Səttar Bəhlulzadə yaradıcılığında əsasən hansı janra üstünlük verirdi?', 'options': ['Portret', 'Natürmort', 'Mənzərə', 'Abstrakt'], 'correct': 'Mənzərə'},
        {'question': 'Hansı yazıçı "Cinayət və Cəza" romanının müəllifidir?', 'options': ['Lev Tolstoy', 'Anton Çexov', 'Fyodor Dostoyevski', 'İvan Turgenev'], 'correct': 'Fyodor Dostoyevski'},
        {'question': 'Meksikalı rəssam Frida Kahlo əsasən hansı üslubda rəsmlər çəkirdi?', 'options': ['Kubizm', 'İmpressionizm', 'Sürrealizm', 'Realizm'], 'correct': 'Sürrealizm'},
        {'question': 'Müslüm Maqomayev hansı məşhur opera teatrının solisti olmuşdur?', 'options': ['La Skala', 'Böyük Teatr', 'Metropoliten-opera', 'Vyana Dövlət Operası'], 'correct': 'Böyük Teatr'},
        {'question': '"Səfillər" romanının müəllifi kimdir?', 'options': ['Aleksandr Düma', 'Jül Vern', 'Viktor Hüqo', 'Onore de Balzak'], 'correct': 'Viktor Hüqo'},
        {'question': 'Hansı memarlıq abidəsi "Məhəbbət abidəsi" kimi tanınır?', 'options': ['Kolizey', 'Eyfel qülləsi', 'Tac Mahal', 'Azadlıq heykəli'], 'correct': 'Tac Mahal'},
        {'question': 'Azərbaycan muğam sənəti UNESCO-nun qeyri-maddi mədəni irs siyahısına neçənci ildə daxil edilib?', 'options': ['2003', '2005', '2008', '2010'], 'correct': '2008'},
        {'question': 'Vinsent van Qoqun "Ulduzlu gecə" əsəri hazırda hansı şəhərin muzeyindədir?', 'options': ['Paris', 'Amsterdam', 'London', 'Nyu-York'], 'correct': 'Nyu-York'},
        {'question': 'Caz musiqisinin vətəni haradır?', 'options': ['Braziliya', 'Kuba', 'ABŞ (Nyu-Orlean)', 'Argentina'], 'correct': 'ABŞ (Nyu-Orlean)'},
        # Tarix (20 sual)
        {'question': '100 illik müharibə hansı iki dövlət arasında olmuşdur?', 'options': ['İngiltərə və Fransa', 'İspaniya və Portuqaliya', 'Roma və Karfagen', 'Prussiya və Avstriya'], 'correct': 'İngiltərə və Fransa'},
        {'question': 'Tarixdə "Atilla" adı ilə tanınan hökmdar hansı imperiyanı idarə edirdi?', 'options': ['Roma İmperiyası', 'Hun İmperiyası', 'Monqol İmperiyası', 'Osmanlı İmperiyası'], 'correct': 'Hun İmperiyası'},
        {'question': 'Səfəvi dövlətinin banisi kimdir?', 'options': ['Şah Abbas', 'Sultan Hüseyn', 'Şah İsmayıl Xətai', 'Nadir Şah'], 'correct': 'Şah İsmayıl Xətai'},
        {'question': 'Berlin divarı neçənci ildə yıxılmışdır?', 'options': ['1985', '1989', '1991', '1993'], 'correct': '1989'},
        {'question': 'Troya müharibəsi haqqında məlumat verən Homerin məşhur əsəri hansıdır?', 'options': ['Odisseya', 'Teoqoniya', 'İliada', 'Eneida'], 'correct': 'İliada'},
        {'question': 'Azərbaycan Xalq Cümhuriyyətinin ilk baş naziri kim olmuşdur?', 'options': ['Məmməd Əmin Rəsulzadə', 'Nəsib bəy Yusifbəyli', 'Fətəli Xan Xoyski', 'Əlimərdan bəy Topçubaşov'], 'correct': 'Fətəli Xan Xoyski'},
        {'question': 'Misir ehramları hansı məqsədlə tikilmişdir?', 'options': ['Rəsədxana', 'Məbəd', 'Fironlar üçün məqbərə', 'Taxıl anbarı'], 'correct': 'Fironlar üçün məqbərə'},
        {'question': 'Soyuq müharibə əsasən hansı iki supergüc arasında gedirdi?', 'options': ['Çin və Yaponiya', 'Almaniya və Fransa', 'ABŞ və SSRİ', 'Böyük Britaniya və ABŞ'], 'correct': 'ABŞ və SSRİ'},
        {'question': 'Napoleon Bonapart Vaterloo döyüşündə neçənci ildə məğlub oldu?', 'options': ['1805', '1812', '1815', '1821'], 'correct': '1815'},
        {'question': 'Osmanlı Sultanı Fateh Sultan Mehmet İstanbulu neçənci ildə fəth etmişdir?', 'options': ['1451', '1453', '1461', '1481'], 'correct': '1453'},
        {'question': 'ABŞ-da köləliyi ləğv edən 13-cü düzəlişi hansı prezident imzalamışdır?', 'options': ['Corc Vaşqton', 'Tomas Cefferson', 'Abraham Linkoln', 'Franklin Ruzvelt'], 'correct': 'Abraham Linkoln'},
        {'question': 'Makedoniyalı İskəndərin müəllimi olmuş məşhur yunan filosofu kimdir?', 'options': ['Platon', 'Sokrat', 'Aristotel', 'Diogen'], 'correct': 'Aristotel'},
        {'question': 'Hansı hadisə Orta Əsrlərin başlanğıcı hesab olunur?', 'options': ['Şərqi Roma İmperiyasının yaranması', 'Qərbi Roma İmperiyasının süqutu', 'Xaç yürüşlərinin başlaması', 'Amerikanın kəşfi'], 'correct': 'Qərbi Roma İmperiyasının süqutu'},
        {'question': 'Babək hansı xilafətə qarşı mübarizə aparmışdır?', 'options': ['Əməvilər', 'Abbasilər', 'Osmanlılar', 'Fatimilər'], 'correct': 'Abbasilər'},
        {'question': 'Qara ölüm (Taun) pandemiyası Avropada hansı əsrdə geniş yayılmışdı?', 'options': ['12-ci əsr', '13-cü əsr', '14-cü əsr', '15-ci əsr'], 'correct': '14-cü əsr'},
        {'question': 'Xirosimaya atılan atom bombasının adı nə idi?', 'options': ['"Fat Man"', '"Little Boy"', '"Tsar Bomba"', '"Trinity"'], 'correct': '"Little Boy"'},
        {'question': '"Gülüstan" və "Türkmənçay" müqavilələri hansı imperiyalar arasında imzalanıb?', 'options': ['Osmanlı və Rusiya', 'Qacarlar və Osmanlı', 'Rusiya və Qacarlar', 'Britaniya və Rusiya'], 'correct': 'Rusiya və Qacarlar'},
        {'question': 'Vikinqlər əsasən hansı regiondan dünyaya yayılmışdılar?', 'options': ['Aralıq dənizi', 'Skandinaviya', 'Balkanlar', 'Britaniya adaları'], 'correct': 'Skandinaviya'},
        {'question': 'ABŞ-ın müstəqillik bəyannaməsi neçənci ildə qəbul edilib?', 'options': ['1776', '1789', '1812', '1865'], 'correct': '1776'},
        {'question': 'Monqol imperiyasının qurucusu kimdir?', 'options': ['Atilla', 'Batı xan', 'Çingiz xan', 'Əmir Teymur'], 'correct': 'Çingiz xan'},
        # Elm (20 sual)
        {'question': 'Eynşteynin məşhur Nisbilik Nəzəriyyəsinin düsturu hansıdır?', 'options': ['F=ma', 'E=mc²', 'a²+b²=c²', 'V=IR'], 'correct': 'E=mc²'},
        {'question': 'İlk dəfə Aya ayaq basan insan kimdir?', 'options': ['Yuri Qaqarin', 'Con Glenn', 'Maykl Kollins', 'Nil Armstronq'], 'correct': 'Nil Armstronq'},
        {'question': 'Çernobıl AES-də qəza neçənci ildə baş vermişdir?', 'options': ['1982', '1986', '1988', '1991'], 'correct': '1986'},
        {'question': 'Hansı kimyəvi elementin simvolu "Au"-dur?', 'options': ['Gümüş', 'Mis', 'Qızıl', 'Dəmir'], 'correct': 'Qızıl'},
        {'question': 'İnsan DNT-si neçə xromosomdan ibarətdir?', 'options': ['23 cüt (46)', '21 cüt (42)', '25 cüt (50)', '32 cüt (64)'], 'correct': '23 cüt (46)'},
        {'question': 'İşıq sürəti saniyədə təxminən nə qədərdir?', 'options': ['150,000 km', '300,000 km', '500,000 km', '1,000,000 km'], 'correct': '300,000 km'},
        {'question': 'Böyük Partlayış (Big Bang) nəzəriyyəsi nəyi izah edir?', 'options': ['Ulduzların yaranmasını', 'Qara dəliklərin formalaşmasını', 'Kainatın yaranmasını', 'Günəş sisteminin yaranmasını'], 'correct': 'Kainatın yaranmasını'},
        {'question': 'Hansı alim penisilini kəşf etmişdir?', 'options': ['Lui Paster', 'Aleksandr Fleminq', 'Robert Kox', 'Mariya Küri'], 'correct': 'Aleksandr Fleminq'},
        {'question': 'Higgs bozonu elmi dairələrdə daha çox hansı adla tanınır?', 'options': ['Tanrı hissəciyi', 'Foton', 'Neytrino', 'Qraviton'], 'correct': 'Tanrı hissəciyi'},
        {'question': 'Yerin maqnit sahəsi bizi nədən qoruyur?', 'options': ['Meteoritlərdən', 'Günəş küləyindən', 'Ultrabənövşəyi şüalardan', 'Soyuq kosmosdan'], 'correct': 'Günəş küləyindən'},
        {'question': 'Albert Eynşteyn Nobel mükafatını hansı kəşfinə görə almışdır?', 'options': ['Nisbilik nəzəriyyəsi', 'Fotoelektrik effekti', 'Brown hərəkəti', 'E=mc²'], 'correct': 'Fotoelektrik effekti'},
        {'question': 'Kimya elmində pH şkalası nəyi ölçmək üçün istifadə olunur?', 'options': ['Temperaturu', 'Təzyiqi', 'Turşuluq və qələviliyi', 'Sıxlığı'], 'correct': 'Turşuluq və qələviliyi'},
        {'question': 'Halley kometası Yer kürəsindən təxminən neçə ildən bir görünür?', 'options': ['25-26 il', '50-51 il', '75-76 il', '100-101 il'], 'correct': '75-76 il'},
        {'question': '"Dolly" adlı qoyun hansı elmi nailiyyətin simvoludur?', 'options': ['Gen modifikasiyası', 'İlk klonlanmış məməli', 'Süni intellekt', 'Kök hüceyrə tədqiqatı'], 'correct': 'İlk klonlanmış məməli'},
        {'question': 'Qırmızı qan hüceyrələrinə rəngini verən dəmir tərkibli zülal hansıdır?', 'options': ['Mioqlobin', 'Albumin', 'Hemoqlobin', 'Fibrinogen'], 'correct': 'Hemoqlobin'},
        {'question': 'Hansı planetin peyki olan Titanın sıx atmosferi var?', 'options': ['Yupiter', 'Mars', 'Uran', 'Saturn'], 'correct': 'Saturn'},
        {'question': 'İnsanın eşitmə diapazonundan daha yüksək tezlikli səslər necə adlanır?', 'options': ['İnfrasəs', 'Rezonans', 'Ultrasəs', 'Subsonik'], 'correct': 'Ultrasəs'},
        {'question': 'Təkamül nəzəriyyəsini "Növlərin Mənşəyi" kitabında irəli sürən alim kimdir?', 'options': ['Qreqor Mendel', 'Alfred Uolles', 'Jan-Batist Lamark', 'Çarlz Darvin'], 'correct': 'Çarlz Darvin'},
        {'question': 'Fermatın Böyük Teoremi riyaziyyatda neçə əsrdən sonra sübut edilmişdir?', 'options': ['Təxminən 100 il', 'Təxminən 250 il', 'Təxminən 358 il', 'Hələ sübut edilməyib'], 'correct': 'Təxminən 358 il'},
        {'question': 'Mariana çökəkliyi hansı okeanda yerləşir?', 'options': ['Atlantik', 'Hind', 'Şimal Buzlu', 'Sakit'], 'correct': 'Sakit'},
        # Texnologiya (20 sual)
        {'question': 'İlk kosmik peyk olan "Sputnik 1" hansı ölkə tərəfindən orbitə buraxılmışdır?', 'options': ['ABŞ', 'Çin', 'SSRİ', 'Böyük Britaniya'], 'correct': 'SSRİ'},
        {'question': '"World Wide Web" (WWW) konsepsiyasını kim yaratmışdır?', 'options': ['Steve Jobs', 'Linus Torvalds', 'Tim Berners-Lee', 'Vint Cerf'], 'correct': 'Tim Berners-Lee'},
        {'question': 'Hansı proqramlaşdırma dili Google tərəfindən yaradılmışdır?', 'options': ['Swift', 'Kotlin', 'Go', 'Rust'], 'correct': 'Go'},
        {'question': 'Kriptovalyuta olan Bitcoin-in yaradıcısının ləqəbi nədir?', 'options': ['Vitalik Buterin', 'Satoshi Nakamoto', 'Elon Musk', 'Charlie Lee'], 'correct': 'Satoshi Nakamoto'},
        {'question': 'Kompüter elmlərində "Turing maşını" nəzəriyyəsini kim irəli sürmüşdür?', 'options': ['Con fon Neyman', 'Alan Turinq', 'Ada Lavleys', 'Çarlz Bebbic'], 'correct': 'Alan Turinq'},
        {'question': 'İnternetin sələfi hesab olunan ilk kompüter şəbəkəsi necə adlanırdı?', 'options': ['NSFNET', 'ETHERNET', 'ARPANET', 'İNTRANET'], 'correct': 'ARPANET'},
        {'question': 'Hansı şirkət ilk "Walkman" portativ kaset pleyerini istehsal etmişdir?', 'options': ['Panasonic', 'Sony', 'Philips', 'Aiwa'], 'correct': 'Sony'},
        {'question': '"Moore Qanunu" nə ilə bağlıdır?', 'options': ['Prosessorların sürətinin artması', 'İnteqral sxemlərdəki tranzistorların sayının ikiqat artması', 'İnternet sürətinin artması', 'Batareya ömrünün uzanması'], 'correct': 'İnteqral sxemlərdəki tranzistorların sayının ikiqat artması'},
        {'question': 'Açıq mənbəli (open-source) əməliyyat sistemi olan Linux-un ləpəsini (kernel) kim yaratmışdır?', 'options': ['Riçard Stallman', 'Stiv Voznyak', 'Linus Torvalds', 'Bill Geyts'], 'correct': 'Linus Torvalds'},
        {'question': 'Hansı alqoritm Google-un axtarış sisteminin əsasını təşkil edirdi?', 'options': ['A*', 'Dijkstra', 'PageRank', 'Bubble Sort'], 'correct': 'PageRank'},
        {'question': 'Deep Blue adlı superkompüter hansı məşhur şahmatçını məğlub etmişdir?', 'options': ['Maqnus Karlsen', 'Bobi Fişer', 'Harri Kasparov', 'Anatoli Karpov'], 'correct': 'Harri Kasparov'},
        {'question': 'Hansı şirkət ilk kommersiya məqsədli mikroprosessoru (Intel 4004) təqdim etmişdir?', 'options': ['IBM', 'AMD', 'Intel', 'Motorola'], 'correct': 'Intel'},
        {'question': '"Virtual Reality" (VR) nə deməkdir?', 'options': ['Genişləndirilmiş Reallıq', 'Süni İntellekt', 'Sanal Reallıq', 'Maşın Təlimi'], 'correct': 'Sanal Reallıq'},
        {'question': 'C++ proqramlaşdırma dilinin yaradıcısı kimdir?', 'options': ['Dennis Ritçi', 'Ceyms Qoslinq', 'Byarne Stroustrup', 'Qvido van Rossum'], 'correct': 'Byarne Stroustrup'},
        {'question': 'Blokçeyn (Blockchain) texnologiyası ilk dəfə hansı tətbiqdə istifadə edilib?', 'options': ['Ethereum', 'Ripple', 'Litecoin', 'Bitcoin'], 'correct': 'Bitcoin'},
        {'question': 'Hansı cihaz alternativ cərəyanı (AC) sabit cərəyana (DC) çevirir?', 'options': ['Transformator', 'Generator', 'Düzləndirici (Rectifier)', 'İnverter'], 'correct': 'Düzləndirici (Rectifier)'},
        {'question': 'Kompüterə qoşulan xarici cihazları idarə edən proqram təminatı necə adlanır?', 'options': ['Əməliyyat sistemi', 'Drayver', 'Utilit', 'Tətbiqi proqram'], 'correct': 'Drayver'},
        {'question': 'İlk video paylaşım saytı olan YouTube neçənci ildə yaradılıb?', 'options': ['2003', '2005', '2007', '2009'], 'correct': '2005'},
        {'question': '3D printerin iş prinsipi nəyə əsaslanır?', 'options': ['Materialı kəsməyə', 'Materialı əritməyə', 'Materialı qat-qat əlavə etməyə', 'Materialı pressləməyə'], 'correct': 'Materialı qat-qat əlavə etməyə'},
        {'question': 'İstifadəçiyə saxta e-poçt göndərərək həssas məlumatları oğurlama cəhdi necə adlanır?', 'options': ['Virus', 'Spam', 'Fişinq', 'Troyan'], 'correct': 'Fişinq'},
        # İdman (20 sual)
        {'question': '"Formula 1" tarixində ən çox yarış qazanan pilot kimdir?', 'options': ['Mixael Şumaxer', 'Sebastian Vettel', 'Ayrton Senna', 'Lüis Hemilton'], 'correct': 'Lüis Hemilton'},
        {'question': 'Bir marafon yarışının rəsmi məsafəsi nə qədərdir?', 'options': ['26.2 km', '42.195 km', '50 km', '35.5 km'], 'correct': '42.195 km'},
        {'question': 'Ağır atletika üzrə 3 qat Olimpiya çempionu olmuş "Cib Heraklisi" ləqəbli türk idmançı kimdir?', 'options': ['Halil Mutlu', 'Naim Süleymanoğlu', 'Taner Sağır', 'Hafiz Süleymanoğlu'], 'correct': 'Naim Süleymanoğlu'},
        {'question': 'Şahmatda "Sitsiliya müdafiəsi" hansı gedişlə başlayır?', 'options': ['1. e4 c5', '1. d4 Nf6', '1. e4 e5', '1. c4 e5'], 'correct': '1. e4 c5'},
        {'question': 'Tennisdə "Böyük Dəbilqə" (Grand Slam) turnirlərinə hansı daxil deyil?', 'options': ['Uimbldon', 'ABŞ Açıq', 'Fransa Açıq (Roland Garros)', 'Indian Wells Masters'], 'correct': 'Indian Wells Masters'},
        {'question': 'Futbol tarixində yeganə qapıçı olaraq "Qızıl Top" mükafatını kim qazanıb?', 'options': ['Canluici Buffon', 'Oliver Kan', 'Lev Yaşin', 'İker Kasilyas'], 'correct': 'Lev Yaşin'},
        {'question': 'Hansı komanda ən çox UEFA Çempionlar Liqası kubokunu qazanıb?', 'options': ['Barselona', 'Milan', 'Bavariya Münhen', 'Real Madrid'], 'correct': 'Real Madrid'},
        {'question': 'Məhəmməd Əli məşhur "Rumble in the Jungle" döyüşündə kimə qalib gəlmişdir?', 'options': ['Sonny Liston', 'Joe Frazier', 'George Foreman', 'Ken Norton'], 'correct': 'George Foreman'},
        {'question': 'Maykl Cordan karyerasının böyük hissəsini hansı NBA komandasında keçirib?', 'options': ['Los Angeles Lakers', 'Boston Celtics', 'Chicago Bulls', 'New York Knicks'], 'correct': 'Chicago Bulls'},
        {'question': 'Hansı üzgüçü ən çox Olimpiya qızıl medalı qazanıb?', 'options': ['Mark Spitz', 'Maykl Felps', 'Ryan Lochte', 'Ian Thorpe'], 'correct': 'Maykl Felps'},
        {'question': 'İlk Futbol üzrə Dünya Çempionatı hansı ölkədə keçirilmişdir?', 'options': ['Braziliya', 'İtaliya', 'Uruqvay', 'İngiltərə'], 'correct': 'Uruqvay'},
        {'question': 'Hansı tennisçi "Torpağın Kralı" (King of Clay) ləqəbi ilə tanınır?', 'options': ['Rocer Federer', 'Novak Cokoviç', 'Rafael Nadal', 'Pit Sampras'], 'correct': 'Rafael Nadal'},
        {'question': '"New Zealand All Blacks" hansı idman növü üzrə məşhur milli komandadır?', 'options': ['Futbol', 'Kriket', 'Reqbi', 'Basketbol'], 'correct': 'Reqbi'},
        {'question': 'Snuker oyununda ən yüksək xal verən rəngli top hansıdır?', 'options': ['Mavi', 'Çəhrayı', 'Qara', 'Sarı'], 'correct': 'Qara'},
        {'question': 'Yelena İsinbayeva hansı yüngül atletika növündə dünya rekordçusu idi?', 'options': ['Hündürlüyə tullanma', 'Üçtəkanla tullanma', 'Şüvüllə tullanma', 'Uzunluğa tullanma'], 'correct': 'Şüvüllə tullanma'},
        {'question': 'Hansı döyüş sənəti "yumşaq yol" mənasını verir?', 'options': ['Karate', 'Taekvondo', 'Cüdo', 'Kunq-fu'], 'correct': 'Cüdo'},
        {'question': 'Formula 1-də "Hat-trick" nə deməkdir?', 'options': ['Eyni yarışda 3 dəfə pit-stop etmək', 'Pole mövqeyi, ən sürətli dövrə və qələbə', 'Bir mövsümdə 3 qələbə qazanmaq', 'Podiumda 3 komanda yoldaşının olması'], 'correct': 'Pole mövqeyi, ən sürətli dövrə və qələbə'},
        {'question': 'NBA tarixində ən çox xal qazanan basketbolçu kimdir?', 'options': ['Maykl Cordan', 'Kərim Əbdül-Cabbar', 'Kobi Brayant', 'LeBron Ceyms'], 'correct': 'LeBron Ceyms'},
        {'question': 'Hansı idman növündə "Albatros" termini istifadə olunur?', 'options': ['Futbol', 'Qolf', 'Reqbi', 'Kriket'], 'correct': 'Qolf'},
        {'question': '"Qarabağ" FK öz ev oyunlarını hazırda hansı stadionda keçirir?', 'options': ['Tofiq Bəhramov adına Respublika Stadionu', 'Bakı Olimpiya Stadionu', 'Dalğa Arena', 'Azərsun Arena'], 'correct': 'Tofiq Bəhramov adına Respublika Stadionu'},
        # Ümumi Bilik (20 sual)
        {'question': 'Hansı ölkə həm Avropada, həm də Asiyada yerləşir?', 'options': ['Misir', 'Rusiya', 'İran', 'Qazaxıstan'], 'correct': 'Rusiya'},
        {'question': 'Dünyanın ən uzun çayı hansıdır?', 'options': ['Amazon', 'Nil', 'Yantszı', 'Missisipi'], 'correct': 'Nil'},
        {'question': 'Hansı şəhər İtaliyanın paytaxtıdır?', 'options': ['Milan', 'Neapol', 'Roma', 'Venesiya'], 'correct': 'Roma'},
        {'question': 'Avstraliya qitəsinin ən məşhur heyvanı hansıdır?', 'options': ['Zürafə', 'Kenquru', 'Panda', 'Zebra'], 'correct': 'Kenquru'},
        {'question': 'İnsan bədənindəki ən güclü əzələ hansıdır?', 'options': ['Biceps', 'Ürək', 'Dil', 'Çeynəmə əzələsi'], 'correct': 'Çeynəmə əzələsi'},
        {'question': 'Hansı dənizdə duzluluq səviyyəsi ən yüksəkdir və batmaq demək olar ki, mümkün deyil?', 'options': ['Aralıq dənizi', 'Qırmızı dəniz', 'Ölü dəniz', 'Qara dəniz'], 'correct': 'Ölü dəniz'},
        {'question': '"Şərqin Parisi" adlandırılan şəhər hansıdır?', 'options': ['İstanbul', 'Dubay', 'Bakı', 'Beyrut'], 'correct': 'Bakı'},
        {'question': 'Hansı ölkənin bayrağı düzbucaqlı formada olmayan yeganə bayraqdır?', 'options': ['İsveçrə', 'Vatikan', 'Nepal', 'Yaponiya'], 'correct': 'Nepal'},
        {'question': 'Bir əsrdə neçə il var?', 'options': ['10', '50', '100', '1000'], 'correct': '100'},
        {'question': 'Hansı ölkə özünün pendir və şokoladı ilə məşhurdur?', 'options': ['Fransa', 'Belçika', 'İsveçrə', 'İtaliya'], 'correct': 'İsveçrə'},
        {'question': 'Sahara səhrası hansı qitədə yerləşir?', 'options': ['Asiya', 'Avstraliya', 'Afrika', 'Cənubi Amerika'], 'correct': 'Afrika'},
        {'question': 'Hansı şəhər həm də bir ölkədir?', 'options': ['Monako', 'Vatikan', 'Sinqapur', 'Hamısı'], 'correct': 'Hamısı'},
        {'question': 'Dünyanın ən çox əhalisi olan ölkəsi hansıdır (2024-cü il məlumatlarına görə)?', 'options': ['Çin', 'Hindistan', 'ABŞ', 'İndoneziya'], 'correct': 'Hindistan'},
        {'question': '"Qızıl Qapı" körpüsü (Golden Gate Bridge) hansı şəhərdə yerləşir?', 'options': ['Nyu-York', 'Los Anceles', 'San-Fransisko', 'Çikaqo'], 'correct': 'San-Fransisko'},
        {'question': 'Termometr nəyi ölçmək üçün istifadə olunur?', 'options': ['Təzyiq', 'Rütubət', 'Temperatur', 'Sürət'], 'correct': 'Temperatur'},
        {'question': 'Hansı metal otaq temperaturunda maye halında olur?', 'options': ['Qalay', 'Qurğuşun', 'Civə', 'Alüminium'], 'correct': 'Civə'},
        {'question': 'Bir sutkada neçə saniyə var?', 'options': ['3600', '64800', '86400', '1440'], 'correct': '86400'},
        {'question': 'Hansı ölkə özünün ağcaqayın siropu (maple syrup) ilə tanınır?', 'options': ['ABŞ', 'Rusiya', 'Norveç', 'Kanada'], 'correct': 'Kanada'},
        {'question': 'Böyük Bariyer Rifi hansı ölkənin sahillərində yerləşir?', 'options': ['Braziliya', 'Meksika', 'Avstraliya', 'İndoneziya'], 'correct': 'Avstraliya'},
        {'question': 'Hansı yazıçı "Harri Potter" seriyasının müəllifidir?', 'options': ['J.R.R. Tolkien', 'George R.R. Martin', 'C.S. Lewis', 'J.K. Rowling'], 'correct': 'J.K. Rowling'},
    ]

    conn, cur = None, None
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cur = conn.cursor()
        
        added_count = 0
        all_questions = all_simple_questions + all_premium_questions
        is_premium_flag = [False] * len(all_simple_questions) + [True] * len(all_premium_questions)

        for i, q in enumerate(all_questions):
            cur.execute(
                "INSERT INTO quiz_questions (question_text, options, correct_answer, is_premium) VALUES (%s, %s, %s, %s) ON CONFLICT (question_text) DO NOTHING;",
                (q['question'], q['options'], q['correct'], is_premium_flag[i])
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

# OYUN FUNKSİYALARI
async def viktorina_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.chat_data.get('quiz_active'): await update.message.reply_text("Artıq aktiv bir viktorina var!"); return
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
            context.chat_data['recently_asked_quiz_ids'] = []
            cur.execute(query, (is_premium, [0]))
            question_data = cur.fetchone()

        if not question_data:
            await message.edit_text("Bu kateqoriya üçün heç bir sual tapılmadı. Adminə bildirin ki, /addquestions əmrini işlətsin."); return

        q_id, q_text, q_options, q_correct = question_data
        context.chat_data.setdefault('recently_asked_quiz_ids', []).append(q_id)
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
# ... (Bütün digər funksiyalar olduğu kimi qalır)

# --- ƏSAS MAIN FUNKSİYASI ---
async def main() -> None:
    run_pre_flight_checks()
    init_db()
    application = Application.builder().token(TOKEN).build()
    
    #... (Bütün handler-lərin əlavə edilməsi olduğu kimi qalır)
    application.add_handler(CommandHandler("addquestions", addquestions_command))
    
    await application.run_polling()

if __name__ == '__main__':
    asyncio.run(main())

