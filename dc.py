import logging
import random
import os
import psycopg2
import datetime
import time # Gecikmə üçün yeni kitabxana
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters
from telegram.constants import ChatType
from telegram.error import Forbidden # Bloklayan istifadəçilər üçün xəta

# Logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# --- BAZA VƏ ƏSAS DƏYİŞƏNLƏR ---
DATABASE_URL = os.environ.get("DATABASE_URL")
# Mərhələ 1-də əlavə etdiyimiz BOT SAHİBİNİN ID-si
BOT_OWNER_ID = int(os.environ.get("BOT_OWNER_ID", 0))

def init_db():
    """Verilənlər bazasında cədvəlləri yoxlayır/yaradır."""
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cur = conn.cursor()
        # Mesaj sayları üçün cədvəl
        cur.execute("""
            CREATE TABLE IF NOT EXISTS message_counts (...);
        """) # Bu hissə eyni qalır, qısalıq üçün kəsdim
        
        # YENİ CƏDVƏL: Bota /start yazan istifadəçiləri saxlamaq üçün
        cur.execute("""
            CREATE TABLE IF NOT EXISTS bot_users (
                user_id BIGINT PRIMARY KEY,
                first_name TEXT,
                date_added TIMESTAMPTZ NOT NULL
            );
        """)
        conn.commit()
        cur.close()
        conn.close()
        print("Verilənlər bazası cədvəlləri hazırdır.")
    except Exception as e:
        print(f"Baza yaradılarkən xəta: {e}")

# ... (Oyun sualları və digər köməkçi funksiyalar eyni qalır) ...
# Aşağıdakı tam kodda hamısı olacaq.

# --- YENİ VƏ YENİLƏNMİŞ ƏMRLƏR ---

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/start əmrini idarə edir VƏ istifadəçini bazaya əlavə edir."""
    user = update.message.from_user
    
    # İstifadəçini bazaya əlavə edirik
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cur = conn.cursor()
        # ON CONFLICT (user_id) DO NOTHING: istifadəçi artıq varsa, xəta vermir, sadəcə heç nə etmir.
        cur.execute(
            "INSERT INTO bot_users (user_id, first_name, date_added) VALUES (%s, %s, %s) ON CONFLICT (user_id) DO NOTHING",
            (user.id, user.first_name, datetime.datetime.now(datetime.timezone.utc))
        )
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        logger.error(f"İstifadəçini bazaya yazarkən xəta: {e}")

    await update.message.reply_text("Salam! 🤖\n\nOyun başlatmaq üçün qrupda /oyun yazın.\nMesaj reytinqinə baxmaq üçün /reyting [dövr] yazın.")

# YENİ ƏMR: /broadcast
async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Yalnız bot sahibinə bütün istifadəçilərə mesaj göndərməyə icazə verir."""
    user = update.message.from_user
    
    if user.id != BOT_OWNER_ID:
        await update.message.reply_text("⛔ Bu əmrdən yalnız bot sahibi istifadə edə bilər.")
        return

    message_text = " ".join(context.args)
    if not message_text:
        await update.message.reply_text("İstifadə: /broadcast <mesajınız>")
        return

    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cur = conn.cursor()
        cur.execute("SELECT user_id FROM bot_users;")
        user_ids = [row[0] for row in cur.fetchall()]
        cur.close()
        conn.close()
        
        if not user_ids:
            await update.message.reply_text("Mesaj göndərmək üçün heç bir istifadəçi tapılmadı.")
            return

        await update.message.reply_text(f"Mesaj {len(user_ids)} istifadəçiyə göndərilməyə başlayır...")
        
        success_count = 0
        fail_count = 0
        
        # Mesajları yavaş-yavaş göndəririk ki, Telegram bloklamasın
        for user_id in user_ids:
            try:
                await context.bot.send_message(chat_id=user_id, text=message_text)
                success_count += 1
            except Forbidden:
                # İstifadəçi botu bloklayıbsa, bu xəta yaranır
                fail_count += 1
            except Exception as e:
                logger.error(f"Broadcast xətası ({user_id}): {e}")
                fail_count += 1
            
            time.sleep(0.1) # Hər mesaj arasında 0.1 saniyə gözləmə

        await update.message.reply_text(f"Mesaj göndərmə tamamlandı.\n\n✅ Uğurlu: {success_count}\n❌ Uğursuz (bloklayanlar): {fail_count}")

    except Exception as e:
        logger.error(f"Broadcast prosesində ümumi xəta: {e}")
        await update.message.reply_text("Mesajları göndərərkən xəta baş verdi.")

# ... (qalan bütün köhnə funksiyalar olduğu kimi qalır) ...
