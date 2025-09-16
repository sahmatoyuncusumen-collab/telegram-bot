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

# --- DÜYMƏ VƏ MESAJ HANDLERLƏRİ ---
# ... (Bütün bu funksiyalar olduğu kimi qalır, ona görə yer tutmasın deyə qısaltdım)
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE): pass
async def handle_all_messages(update: Update, context: ContextTypes.DEFAULT_TYPE): pass
async def word_filter_handler(update: Update, context: ContextTypes.DEFAULT_TYPE): pass

# --- ƏSAS MAIN FUNKSİYASI ---
async def main() -> None:
    run_pre_flight_checks()
    init_db()
    application = Application.builder().token(TOKEN).build()
    
    commands = [
        BotCommand("start", "Əsas menyunu açmaq"),
        BotCommand("qaydalar", "İstifadə təlimatı və qaydalar"),
        BotCommand("haqqinda", "Bot haqqında məlumat"),
        BotCommand("menim_rutbem", "Şəxsi rütbəni yoxlamaq"),
        BotCommand("viktorina", "Viktorina oyununu başlatmaq"),
        BotCommand("zer", "1-6 arası zər atmaq"),
        BotCommand("liderler", "Aylıq liderlər cədvəli"),
        BotCommand("dcoyun", "Doğruluq/Cəsarət oyununu başlatmaq (Admin)"),
        BotCommand("adminpanel", "Admin idarəetmə paneli (Admin)"),
    ]
    
    # Handlerlərin əlavə edilməsi
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("qaydalar", qaydalar_command))
    application.add_handler(CommandHandler("haqqinda", haqqinda_command))
    application.add_handler(CommandHandler("menim_rutbem", my_rank_command))
    application.add_handler(CommandHandler("liderler", liderler_command))
    application.add_handler(CommandHandler("dcoyun", dcoyun_command))
    application.add_handler(CommandHandler("zer", zer_command))
    application.add_handler(CommandHandler("adminpanel", adminpanel_command))
    application.add_handler(CommandHandler("addpremium", add_premium_command))
    application.add_handler(CommandHandler("removepremium", remove_premium_command))
    application.add_handler(CommandHandler("addword", addword_command))
    application.add_handler(CommandHandler("delword", delword_command))
    application.add_handler(CommandHandler("listwords", listwords_command))
    application.add_handler(CommandHandler("warn", warn_command))
    application.add_handler(CommandHandler("warnings", warnings_command))
    application.add_handler(CommandHandler("delwarn", delwarn_command))
    application.add_handler(CommandHandler("mute", mute_command))
    application.add_handler(CommandHandler("unmute", unmute_command))
    application.add_handler(CommandHandler("addquestions", addquestions_command))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, welcome_new_members))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, word_filter_handler), group=0)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_all_messages), group=1)
    
    await application.run_polling()

if __name__ == '__main__':
    asyncio.run(main())
