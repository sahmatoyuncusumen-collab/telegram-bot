import logging
import random
import os
import psycopg2
import asyncio
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.enums import ChatType

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- BAZA VƏ ƏSAS DƏYİŞƏNLƏR ---
DATABASE_URL = os.environ.get("DATABASE_URL")
TOKEN = os.environ.get("TELEGRAM_TOKEN")
BOT_OWNER_ID = 6751376199

# Aiogram obyektləri
bot = Bot(token=TOKEN, parse_mode="HTML")
dp = Dispatcher()

# --- BAZA FUNKSİYALARI ---
def init_db():
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cur = conn.cursor()
        cur.execute("CREATE TABLE IF NOT EXISTS premium_users (user_id BIGINT PRIMARY KEY);")
        cur.execute("CREATE TABLE IF NOT EXISTS message_counts (id SERIAL PRIMARY KEY, chat_id BIGINT NOT NULL, user_id BIGINT NOT NULL, message_timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW());")
        conn.commit()
        logger.info("Verilənlər bazası cədvəlləri hazırdır.")
    except Exception as e:
        logger.error(f"Baza yaradılarkən xəta: {e}")
        sys.exit(1)
    finally:
        if conn: conn.close()

def is_user_premium(user_id: int) -> bool:
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
        if conn: conn.close()

def add_premium_user(user_id: int):
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cur = conn.cursor()
        cur.execute("INSERT INTO premium_users (user_id) VALUES (%s) ON CONFLICT (user_id) DO NOTHING;", (user_id,))
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"Premium istifadəçi əlavə edərkən xəta: {e}")
        return False
    finally:
        if conn: conn.close()

def remove_premium_user(user_id: int):
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
        if conn: conn.close()

# --- KÖMƏKÇİ FUNKSİYALAR ---
def get_rank_title(count: int, is_premium: bool = False) -> str:
    if is_premium and count > 5000:
        return "Qızıl Tac ⚜️"
    if count <= 50: return "Yeni Gələn 🐣"
    elif count <= 250: return "Daimi Sakin 🏠"
    elif count <= 750: return "Söhbətcil 🗣️"
    elif count <= 2000: return "Qrup Ağsaqqalı 👴"
    elif count <= 5000: return "Söhbət Baronu 👑"
    else: return "Qrupun Əfsanəsi ⚡️"


# --- ƏSAS ƏMRLƏR ---
@dp.message(CommandStart())
async def start_command(message: Message):
    await message.answer("Salam! Mən Oyun və Moderasiya Botuyam. 🤖\nBütün əmrləri görmək üçün menyuya baxa bilərsiniz.")

@dp.message(Command("menim_rutbem"))
async def my_rank_command(message: Message):
    if message.chat.type == 'private':
        await message.reply("Bu əmr yalnız qruplarda işləyir.")
        return

    user = message.from_user
    chat_id = message.chat.id
    raw_message_count = 0
    
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM message_counts WHERE user_id = %s AND chat_id = %s;", (user.id, chat_id))
        result = cur.fetchone()
        if result:
            raw_message_count = result[0]
    except Exception as e:
        logger.error(f"Rütbə yoxlanarkən xəta: {e}")
        await message.reply("❌ Rütbənizi yoxlayarkən xəta baş verdi.")
        return
    finally:
        if conn: conn.close()

    user_is_premium = is_user_premium(user.id)
    
    # Premium Sürətləndirici
    effective_message_count = int(raw_message_count * 1.5) if user_is_premium else raw_message_count
    
    rank_title = get_rank_title(effective_message_count, user_is_premium)
    
    # Premium Status Nişanı
    premium_icon = " 👑" if user_is_premium else ""
    
    reply_text = (
        f"📊 <b>Sənin Statistikaların, {user.full_name}{premium_icon}!</b>\n\n"
        f"💬 Bu qrupdakı real mesaj sayın: <b>{raw_message_count}</b>\n"
    )
    if user_is_premium:
        reply_text += f"🚀 Premium ilə hesablanmış xalın: <b>{effective_message_count}</b>\n"
    
    reply_text += f"🏆 Rütbən: <b>{rank_title}</b>"
    await message.answer(reply_text)

# --- ADMİN ƏMRLƏRİ ---
@dp.message(Command("addpremium"))
async def add_premium(message: Message):
    if message.from_user.id != BOT_OWNER_ID:
        return await message.reply("⛔ Bu əmrdən yalnız bot sahibi istifadə edə bilər.")
    
    try:
        target_user_id = int(message.text.split()[1])
        if add_premium_user(target_user_id):
            await message.reply(f"✅ <code>{target_user_id}</code> ID-li istifadəçi uğurla premium siyahısına əlavə edildi.")
        else:
            await message.reply("❌ Xəta baş verdi.")
    except (IndexError, ValueError):
        await message.reply("⚠️ Düzgün istifadə: <code>/addpremium &lt;user_id&gt;</code>")

@dp.message(Command("removepremium"))
async def remove_premium(message: Message):
    if message.from_user.id != BOT_OWNER_ID:
        return await message.reply("⛔ Bu əmrdən yalnız bot sahibi istifadə edə bilər.")
    
    try:
        target_user_id = int(message.text.split()[1])
        if remove_premium_user(target_user_id):
            await message.reply(f"✅ <code>{target_user_id}</code> ID-li istifadəçinin premium statusu geri alındı.")
        else:
            await message.reply("❌ Belə bir premium istifadəçi tapılmadı.")
    except (IndexError, ValueError):
        await message.reply("⚠️ Düzgün istifadə: <code>/removepremium &lt;user_id&gt;</code>")

# --- BÜTÜN MESAJLARI QEYDƏ ALAN HANDLER ---
@dp.message(F.text & ~F.via_bot)
async def handle_all_messages(message: Message):
    # Bu funksiya yalnız qruplarda işləməlidir
    if message.chat.type in ('group', 'supergroup'):
        user = message.from_user
        chat_id = message.chat.id
        
        try:
            conn = psycopg2.connect(DATABASE_URL, sslmode='require')
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO message_counts (chat_id, user_id) VALUES (%s, %s);",
                (chat_id, user.id)
            )
            conn.commit()
        except Exception as e:
            logger.error(f"Mesajı bazaya yazarkən xəta: {e}")
        finally:
            if conn: conn.close()

# --- ƏSAS MAIN FUNKSİYASI ---
async def main() -> None:
    if not TOKEN:
        logger.critical("TELEGRAM_TOKEN tapılmadı! Bot dayandırılır.")
        return
    
    # Bot işə düşəndə bazanı yoxlayır/yaradır
    init_db()
    
    # Bot menyusunu quraşdırırıq
    await bot.set_my_commands([
        BotCommand(command="start", description="Əsas menyunu açmaq"),
        BotCommand(command="menim_rutbem", description="Şəxsi rütbəni yoxlamaq"),
    ])
    
    logger.info("Bot işə düşür...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
