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
        conn.commit()
        logger.info("Verilənlər bazası cədvəlləri hazırdır.")
    except Exception as e:
        logger.error(f"Baza yaradılarkən xəta: {e}")
        sys.exit(1)
    finally:
        if cur: cur.close()
        if conn: conn.close()

def is_user_premium(user_id: int) -> bool:
    # ... (dəyişməz qalır)
    pass

def add_premium_user(user_id: int) -> bool:
    # ... (dəyişməz qalır)
    pass

def remove_premium_user(user_id: int) -> bool:
    # ... (dəyişməz qalır)
    pass

# YENİLİK: Son xəbərdarlığı silmək üçün funksiya
def delete_last_warning(chat_id: int, user_id: int) -> bool:
    conn, cur = None, None
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cur = conn.cursor()
        # Ən son xəbərdarlığın ID-sini tapıb silir
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
ABOUT_TEXT = "🤖 **Bot Haqqında**\n\nMən qruplar üçün nəzərdə tutulmuş əyləncə və statistika botuyam..."

# DƏYİŞİKLİK: Təlimat mətni sadələşdirilib, admin hissəsi çıxarılıb
RULES_TEXT = """
📜 **Bot İstifadə Təlimatı və Qrup Qaydaları**

Aşağıda botun ümumi funksiyaları və oyunları haqqında məlumatlar qeyd olunub.

---

### 👤 **Ümumi İstifadəçilər Üçün Əmrlər**

- `/start` - Botu başlatmaq və əsas menyunu görmək.
- `/menim_rutbem` - Qrupdakı mesaj sayınızı və rütbənizi yoxlamaq.
- `/liderler` - Bu ay ən çox mesaj yazan 10 nəfərin siyahısı.
- `/zer` - 1-dən 6-ya qədər təsadüfi zər atmaq.
- `/haqqinda` - Bot haqqında qısa məlumat.
- `/qaydalar` - Bu təlimatı yenidən görmək.

### 🎮 **Oyun Əmrləri**

- `/viktorina` - Bilik yarışması olan viktorina oyununu başladır.
- `/dcoyun` - "Doğruluq yoxsa Cəsarət?" oyununu başladır. **(Yalnız adminlər başlada bilər)**

---
### 📌 **Əsas Qrup Qaydaları**

1. Reklam etmək qəti qadağandır.
2. Təhqir, söyüş və aqressiv davranışlara icazə verilmir.
3. Dini və siyasi mövzuları müzakirə etmək olmaz.
"""

# VIKTORINA VƏ DC SUALLARI
# ... (sual siyahıları dəyişməz qalır)

# --- KÖMƏKÇİ FUNKSİYALAR ---
async def is_user_admin(chat_id: int, user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    # ... (dəyişməz qalır)
    pass
def get_rank_title(count: int, is_premium: bool = False) -> str:
    # ... (dəyişməz qalır)
    pass
def parse_duration(time_str: str) -> datetime.timedelta | None:
    # ... (dəyişməz qalır)
    pass
async def welcome_new_members(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ... (dəyişməz qalır)
    pass

# --- ƏSAS ƏMRLƏR ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton("ℹ️ Bot Haqqında Məlumat", callback_data="start_info_about")], [InlineKeyboardButton("📜 İstifadə Təlimatı", callback_data="start_info_qaydalar")], [InlineKeyboardButton("👥 Oyun Qrupumuz", url="https://t.me/+0z5V-OvEMmgzZTFi")], [InlineKeyboardButton(f"👨‍💻 Admin ilə Əlaqə", url=f"https://t.me/{ADMIN_USERNAME}")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Salam! Mən Oyun Botuyam. 🤖\nAşağıdakı menyudan istədiyin bölməni seç:", reply_markup=reply_markup)
    
# ... (haqqinda, qaydalar, my_rank, zer, liderler, dcoyun dəyişməz qalır)

# --- ADMİN VƏ MODERASİYA ƏMRLƏRİ ---
# ... (addpremium, removepremium, addword, delword, listwords, warn, mute, unmute dəyişməz qalır)

# DƏYİŞİKLİK: /warnings əmri artıq düymə əlavə edir
async def warnings_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    admin = update.message.from_user; chat_id = update.message.chat.id
    if not await is_user_admin(chat_id, admin.id, context):
        await update.message.reply_text("⛔ Bu əmrdən yalnız adminlər istifadə edə bilər."); return
    if not update.message.reply_to_message:
        await update.message.reply_text("⚠️ Bir istifadəçinin xəbərdarlıqlarını görmək üçün onun mesajına cavab verməlisiniz."); return
    
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
            for i, (reason, ts) in enumerate(user_warnings):
                response_text += f"**{i+1}. Səbəb:** {reason}\n   *Tarix:* {ts.strftime('%Y-%m-%d %H:%M')}\n"
            # Düyməni yalnız xəbərdarlıq varsa əlavə et
            keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🗑️ Son xəbərdarlığı sil", callback_data=f"delwarn_{user_to_check.id}")]])
            
        await update.message.reply_text(response_text, parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard)
    except Exception as e:
        logger.error(f"Xəbərdarlıqlar göstərilərkən xəta: {e}"); await update.message.reply_text("❌ Xəta baş verdi.")
    finally:
        if cur: cur.close()
        if conn: conn.close()

# YENİLİK: /delwarn əmri
async def delwarn_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    admin = update.message.from_user
    chat_id = update.message.chat.id
    if not await is_user_admin(chat_id, admin.id, context):
        await update.message.reply_text("⛔ Bu əmrdən yalnız adminlər istifadə edə bilər."); return
    if not update.message.reply_to_message:
        await update.message.reply_text("⚠️ Xəbərdarlığı silmək üçün bir istifadəçinin mesajına cavab verməlisiniz."); return

    user_to_clear = update.message.reply_to_message.from_user
    if delete_last_warning(chat_id, user_to_clear.id):
        await update.message.reply_text(f"✅ [{user_to_clear.first_name}](tg://user?id={user_to_clear.id}) adlı istifadəçinin son xəbərdarlığı [{admin.first_name}](tg://user?id={admin.id}) tərəfindən silindi.", parse_mode=ParseMode.MARKDOWN)
    else:
        await update.message.reply_text(f"ℹ️ [{user_to_clear.first_name}](tg://user?id={user_to_clear.id}) adlı istifadəçinin aktiv xəbərdarlığı tapılmadı.", parse_mode=ParseMode.MARKDOWN)

# YENİLİK: /adminpanel əmri
async def adminpanel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    chat_id = update.message.chat.id
    if not await is_user_admin(chat_id, user.id, context):
        # Admin olmayanlara heç bir mesaj göstərmirik ki, əmr gizli qalsın
        return

    admin_help_text = """
🛡️ **Admin İdarəetmə Paneli**

**Söz Filtrasiyası:**
- `/addword <söz>` - Filtrə söz əlavə edir.
- `/delword <söz>` - Filtrdən söz silir.
- `/listwords` - Filtr siyahısına baxır.

**İstifadəçi İdarəetməsi:**
- `/warn <səbəb>` - Mesaja cavab verərək xəbərdarlıq edir.
- `/warnings` - Mesaja cavab verərək xəbərdarlıqlara baxır.
- `/delwarn` - Mesaja cavab verərək son xəbərdarlığı silir.
- `/mute <müddət> [səbəb]` - Mesaja cavab verərək səssizləşdirir (`30m`, `2h`, `1d`).
- `/unmute` - Mesaja cavab verərək səssiz rejimini ləğv edir.
"""
    # Yalnız bot sahibi premium idarəetmə əmrlərini görür
    if user.id == BOT_OWNER_ID:
        admin_help_text += """
---
👑 **Bot Sahibi Paneli**
- `/addpremium <user_id>` - İstifadəçiyə premium status verir.
- `/removepremium <user_id>` - İstifadəçidən premium statusu geri alır.
"""
    await update.message.reply_text(admin_help_text, parse_mode=ParseMode.MARKDOWN)


# --- OYUN FUNKSİYALARI VƏ HANDLERLƏR ---
# ... (ask_next_quiz_question, show_dc_registration_message, dc_next_turn dəyişməz qalır)

# DƏYİŞİKLİK: button_handler-ə yeni məntiq əlavə edildi
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; user = query.from_user; data = query.data; chat_id = query.message.chat.id
    await query.answer()

    # Xəbərdarlıq silmə düyməsi
    if data.startswith("delwarn_"):
        if not await is_user_admin(chat_id, user.id, context):
            await query.answer("⛔ Bu əməliyyatı yalnız adminlər edə bilər.", show_alert=True)
            return
        
        user_id_to_clear = int(data.split("_")[1])
        if delete_last_warning(chat_id, user_id_to_clear):
            await query.message.edit_text(f"✅ İstifadəçinin son xəbərdarlığı [{user.first_name}](tg://user?id={user.id}) tərəfindən silindi.", parse_mode=ParseMode.MARKDOWN)
        else:
            await query.message.edit_text("ℹ️ İstifadəçinin aktiv xəbərdarlığı tapılmadı.")
        return

    # ... (qalan button_handler məntiqi dəyişməz qalır)
    pass


# ... (handle_all_messages, word_filter_handler dəyişməz qalır)

# --- ƏSAS MAIN FUNKSİYASI ---
async def main() -> None:
    run_pre_flight_checks()
    init_db()
    application = Application.builder().token(TOKEN).build()
    
    commands = [
        BotCommand("start", "Əsas menyunu açmaq"),
        BotCommand("qaydalar", "İstifadə təlimatı və qaydalar"),
        BotCommand("menim_rutbem", "Şəxsi rütbəni yoxlamaq"),
        BotCommand("viktorina", "Viktorina oyununu başlatmaq"),
        BotCommand("liderler", "Aylıq liderlər cədvəli"),
        BotCommand("dcoyun", "Doğruluq/Cəsarət oyununu başlatmaq (Admin)"),
        BotCommand("adminpanel", "Admin idarəetmə paneli (Admin)"),
    ]
    
    # Handler-lər
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("qaydalar", qaydalar_command))
    application.add_handler(CommandHandler("haqqinda", haqqinda_command))
    application.add_handler(CommandHandler("menim_rutbem", my_rank_command))
    application.add_handler(CommandHandler("liderler", liderler_command))
    application.add_handler(CommandHandler("dcoyun", dcoyun_command))
    application.add_handler(CommandHandler("zer", zer_command))
    # Admin
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
    
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, welcome_new_members))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, word_filter_handler), group=0)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_all_messages), group=1)
    
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
