import logging
import random
import os
import psycopg2
import asyncio
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

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

# Oyunların vəziyyətini saxlamaq üçün (sadə variant)
chat_data = {}

# --- BAZA FUNKSİYALARI ---
def init_db():
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cur = conn.cursor()
        cur.execute("CREATE TABLE IF NOT EXISTS premium_users (user_id BIGINT PRIMARY KEY);")
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
        if conn: conn.close()

async def is_user_admin(chat_id: int, user_id: int) -> bool:
    if user_id == BOT_OWNER_ID: return True
    try:
        chat_admins = await bot.get_chat_administrators(chat_id)
        return user_id in [admin.user.id for admin in chat_admins]
    except Exception:
        return False

# ... (Digər baza funksiyaları ehtiyac olduqda əlavə ediləcək)

# --- MƏZMUN SİYAHILARI ---
SADE_TRUTH_QUESTIONS = ["Uşaqlıqda ən böyük qorxun nə olub?", "Heç kimin bilmədiyi bir bacarığın var?"]
SADE_DARE_TASKS = ["Qrupdakı son mesajı əlifbanın hər hərfi ilə tərsinə yaz.", "Profil şəklini 5 dəqiqəlik bir meyvə şəkli ilə dəyişdir."]
PREMIUM_TRUTH_QUESTIONS = ["Həyatının geri qalanını yalnız bir filmi izləyərək keçirməli olsaydın, hansı filmi seçərdin?", "Sənə ən çox təsir edən kitab hansı olub?"]
PREMIUM_DARE_TASKS = ["Qrupdakı adminlərdən birinə 10 dəqiqəlik \"Ən yaxşı admin\" statusu yaz.", "Səsini dəyişdirərək bir nağıl personajı kimi danış və səsli mesaj göndər."]


# --- ƏSAS ƏMRLƏR ---
@dp.message(CommandStart())
async def start_command(message: Message):
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="ℹ️ Bot Haqqında", callback_data="start_info_about"))
    builder.row(types.InlineKeyboardButton(text="📜 Qaydalar", callback_data="start_info_qaydalar"))
    await message.answer("Salam! Mən Oyun Botuyam. 🤖\nMenyudan seçin:", reply_markup=builder.as_markup())

@dp.message(Command("viktorina"))
async def viktorina_command(message: Message):
    chat_id = message.chat.id
    if chat_id in chat_data and chat_data[chat_id].get('quiz_active'):
        await message.reply("Artıq aktiv bir viktorina var!")
        return
    
    chat_data[chat_id] = {'quiz_starter_id': message.from_user.id}
    
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="Viktorina (Sadə) 🌱", callback_data="viktorina_sade"))
    builder.row(types.InlineKeyboardButton(text="Viktorina (Premium) 👑", callback_data="viktorina_premium"))
    await message.answer(f"Salam, {message.from_user.full_name}! Viktorina növünü seçin:", reply_markup=builder.as_markup())

@dp.message(Command("dcoyun"))
async def dcoyun_command(message: Message):
    if message.chat.type == 'private':
        await message.reply("Bu oyunu yalnız qruplarda oynamaq olar.")
        return
    if not await is_user_admin(message.chat.id, message.from_user.id):
        await message.reply("⛔ Bu oyunu yalnız qrup adminləri başlada bilər.")
        return
    
    # ... (Oyun məntiqi düymələrdədir)
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="Doğruluq Cəsarət (sadə)", callback_data="dc_select_sade"))
    builder.row(types.InlineKeyboardButton(text="Doğruluq Cəsarət (Premium👑)", callback_data="dc_select_premium"))
    await message.answer("Doğruluq Cəsarət oyununa xoş gəlmisiniz👋", reply_markup=builder.as_markup())

# --- ADMİN ƏMRİ ---
@dp.message(Command("addquestions"))
async def addquestions_command(message: Message):
    if message.from_user.id != BOT_OWNER_ID:
        await message.reply("⛔ Bu əmrdən yalnız bot sahibi istifadə edə bilər.")
        return
    await message.reply("⏳ Suallar bazaya əlavə edilir...")
    
    simple_questions = [
        {'question': 'Azərbaycanın paytaxtı haradır?', 'options': ['Gəncə', 'Sumqayıt', 'Bakı', 'Naxçıvan'], 'correct': 'Bakı'},
        {'question': 'Bir ildə neçə fəsil var?', 'options': ['2', '3', '4', '5'], 'correct': '4'},
        # ... (Digər 23 sadə sual)
    ]
    premium_questions = [
        {'question': 'Əsərlərini Nizami Gəncəvi imzası ilə yazan şairin əsl adı nədir?', 'options': ['İlyas Yusif oğlu', 'Məhəmməd Füzuli', 'İmadəddin Nəsimi', 'Əliağa Vahid'], 'correct': 'İlyas Yusif oğlu'},
        {'question': 'Leonardo da Vinçinin "Mona Liza" tablosu hansı muzeydədir?', 'options': ['Britaniya Muzeyi', 'Vatikan Muzeyi', 'Ermitaj', 'Luvr Muzeyi'], 'correct': 'Luvr Muzeyi'},
        # ... (Digər 23 premium sual)
    ]
    
    # ... (Bazaya yazma məntiqi)
    await message.answer("✅ Baza yoxlanıldı. Yeni suallar uğurla əlavə edildi.")


# --- DÜYMƏ HANDLERİ ---
@dp.callback_query()
async def button_handler(query: CallbackQuery):
    data = query.data
    
    if data == "start_info_about":
        await query.message.edit_text("🤖 **Bot Haqqında**\n\nMən qruplar üçün nəzərdə tutulmuş əyləncə botuyam.")
    elif data == "start_info_qaydalar":
         await query.message.edit_text("📜 **Qrup Qaydaları**\n\n1. Reklam etmək qəti qadağandır.")
    
    # Viktorina və DC məntiqi burada olacaq
    # ...
    
    await query.answer()

# --- ƏSAS MAIN FUNKSİYASI ---
async def main() -> None:
    if not TOKEN:
        logger.critical("TELEGRAM_TOKEN tapılmadı! Bot dayandırılır.")
        return
    
    # Bot işə düşəndə bazanı yoxlayır/yaradır
    init_db()
    
    # Telegram-dan gələn sorğuları qəbul etməyə başlayır
    await dp.start_polling(bot)

if __name__ == "__main__":
    logging.info("Aiogram botu işə düşür...")
    asyncio.run(main())

