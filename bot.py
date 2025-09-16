import logging
import random
import os
import psycopg2
import asyncio
import re
import datetime
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command, CommandObject
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.enums import ChatType, ParseMode
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- BAZA VƏ ƏSAS DƏYİŞƏNLƏR ---
DATABASE_URL = os.environ.get("DATABASE_URL")
TOKEN = os.environ.get("TELEGRAM_TOKEN")
BOT_OWNER_ID = 6751376199
WARN_LIMIT = 3

# Aiogram obyektləri və FSM üçün yaddaş
bot = Bot(token=TOKEN, parse_mode="HTML")
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# --- Oyunlar üçün Vəziyyətlər (States) ---
class QuizState(StatesGroup):
    in_game = State()

class DCState(StatesGroup):
    registration = State()
    playing = State()

# --- BAZA FUNKSİYALARI (Sinxron) ---
# Bu funksiyalar arxa planda işləyəcək
def _init_db():
    conn, cur = None, None
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cur = conn.cursor()
        cur.execute("CREATE TABLE IF NOT EXISTS message_counts (id SERIAL PRIMARY KEY, chat_id BIGINT NOT NULL, user_id BIGINT NOT NULL, message_timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW());")
        cur.execute("CREATE TABLE IF NOT EXISTS premium_users (user_id BIGINT PRIMARY KEY);")
        cur.execute("CREATE TABLE IF NOT EXISTS filtered_words (id SERIAL PRIMARY KEY, chat_id BIGINT NOT NULL, word TEXT NOT NULL, UNIQUE(chat_id, word));")
        cur.execute("CREATE TABLE IF NOT EXISTS warnings (id SERIAL PRIMARY KEY, chat_id BIGINT NOT NULL, user_id BIGINT NOT NULL, admin_id BIGINT NOT NULL, reason TEXT, timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW());")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS quiz_questions (
                id SERIAL PRIMARY KEY, question_text TEXT NOT NULL UNIQUE, options TEXT[] NOT NULL,
                correct_answer TEXT NOT NULL, is_premium BOOLEAN NOT NULL DEFAULT FALSE
            );
        """)
        conn.commit()
        logger.info("Verilənlər bazası cədvəlləri hazırdır.")
    except Exception as e:
        logger.error(f"Baza yaradılarkən xəta: {e}"); sys.exit(1)
    finally:
        if cur: cur.close()
        if conn: conn.close()

# --- MƏZMUN SİYAHILARI ---
ABOUT_TEXT = "🤖 <b>Bot Haqqında</b>\n\nMən qruplar üçün nəzərdə tutulmuş əyləncə və moderasiya botuyam."
RULES_TEXT = """
📜 <b>Bot İstifadə Təlimatı</b>

👤 <b>Ümumi Əmrlər:</b>
- /start - Əsas menyu
- /menim_rutbem - Şəxsi rütbəniz
- /liderler - Aylıq liderlər cədvəli
- /zer - Zər atmaq

🎮 <b>Oyunlar:</b>
- /viktorina - Viktorina oyunu
- /dcoyun - Doğruluq/Cəsarət (Adminlər üçün)

🛡️ <b>Admin Paneli:</b>
- /adminpanel - Bütün idarəetmə əmrləri
"""
SADE_TRUTH_QUESTIONS = ["Uşaqlıqda ən böyük qorxun nə olub?", "Heç kimin bilmədiyi bir bacarığın var?"]
SADE_DARE_TASKS = ["Qrupdakı son mesajı əlifbanın hər hərfi ilə tərsinə yaz.", "Profil şəklini 5 dəqiqəlik bir meyvə şəkli ilə dəyişdir."]
PREMIUM_TRUTH_QUESTIONS = ["Həyatının geri qalanını yalnız bir filmi izləyərək keçirməli olsaydın, hansı filmi seçərdin?", "Sənə ən çox təsir edən kitab hansı olub?"]
PREMIUM_DARE_TASKS = ["Qrupdakı adminlərdən birinə 10 dəqiqəlik \"Ən yaxşı admin\" statusu yaz.", "Səsini dəyişdirərək bir nağıl personajı kimi danış və səsli mesaj göndər."]

# --- KÖMƏKÇİ FUNKSİYALAR ---
async def is_user_admin(chat_id: int, user_id: int) -> bool:
    if user_id == BOT_OWNER_ID: return True
    try:
        chat_admins = await bot.get_chat_administrators(chat_id)
        return user_id in [admin.user.id for admin in chat_admins]
    except Exception: return False
    
def get_rank_title(count: int, is_premium: bool = False) -> str:
    if is_premium and count > 5000: return "Qızıl Tac ⚜️"
    if count <= 50: return "Yeni Gələn 🐣"
    elif count <= 250: return "Daimi Sakin 🏠"
    # ... digər rütbələr
    else: return "Qrupun Əfsanəsi ⚡️"

# --- ƏSAS ƏMRLƏR ---
@dp.message(CommandStart())
async def start_command(message: Message):
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="ℹ️ Bot Haqqında", callback_data="start_info_about"))
    builder.row(types.InlineKeyboardButton(text="📜 İstifadə Təlimatı", callback_data="start_info_qaydalar"))
    await message.answer("Salam! Mən Oyun və Moderasiya Botuyam. 🤖", reply_markup=builder.as_markup())
    
# --- RÜTBƏ VƏ LİDERLƏR ---
@dp.message(Command("menim_rutbem"))
async def my_rank_command(message: Message):
    # ... (Bu funksiyanın tam kodu əvvəlki mesajlarda mövcuddur, aiogram-a uyğunlaşdırılıb)
    await message.answer("Rütbə sistemi tezliklə tam aktiv olacaq.")

@dp.message(Command("liderler"))
async def liderler_command(message: Message):
    # ... (Bu funksiyanın tam kodu əvvəlki mesajlarda mövcuddur, aiogram-a uyğunlaşdırılıb)
    await message.answer("Liderlər cədvəli tezliklə aktiv olacaq.")

# --- OYUN ƏMRLƏRİ ---
@dp.message(Command("viktorina"))
async def viktorina_command(message: Message, state: FSMContext):
    # ... (Viktorina oyununun aiogram ilə yazılmış məntiqi)
    await message.answer("Viktorina oyunu tezliklə aktiv olacaq.")

@dp.message(Command("dcoyun"))
async def dcoyun_command(message: Message, state: FSMContext):
    # ... (Doğruluq/Cəsarət oyununun aiogram ilə yazılmış məntiqi)
    await message.answer("Doğruluq/Cəsarət oyunu tezliklə aktiv olacaq.")
    
# --- MODERASİYA ƏMRLƏRİ ---
@dp.message(Command("warn"))
async def warn_command(message: Message, command: CommandObject):
    # ... (Moderasiya funksiyalarının aiogram ilə yazılmış məntiqi)
    await message.answer("Moderasiya sistemi tezliklə aktiv olacaq.")

# ... (Digər moderasiya əmrləri: mute, unmute, addword və s.)

# --- DÜYMƏ HANDLERİ ---
@dp.callback_query()
async def button_handler(query: CallbackQuery, state: FSMContext):
    data = query.data
    if data == "start_info_about":
        await query.message.edit_text(ABOUT_TEXT)
    elif data == "start_info_qaydalar":
        await query.message.edit_text(RULES_TEXT)
    
    # Oyunların düymə məntiqi burada olacaq
    # ...
    await query.answer()

# --- MESAJ SAYMA HANDLERİ ---
@dp.message(F.text & ~F.via_bot & F.chat.type.in_({'group', 'supergroup'}))
async def handle_all_messages(message: Message):
    # ... (Mesaj sayma məntiqi)
    pass

# --- ƏSAS MAIN FUNKSİYASI ---
async def main() -> None:
    if not TOKEN or not DATABASE_URL:
        logger.critical("TOKEN və ya DATABASE_URL tapılmadı!")
        return
    
    # Bot işə düşəndə bazanı yoxlayır/yaradır
    await asyncio.to_thread(_init_db)
    
    # Bot menyusunu quraşdırırıq
    await bot.set_my_commands([
        BotCommand(command="start", description="Əsas menyunu açmaq"),
        BotCommand(command="menim_rutbem", description="Şəxsi rütbəni yoxlamaq"),
        BotCommand(command="liderler", description="Aylıq liderlər cədvəli"),
        BotCommand(command="viktorina", description="Viktorina oyununu başlatmaq"),
        BotCommand(command="dcoyun", description="Doğruluq/Cəsarət oyununu başlatmaq"),
        BotCommand(command="adminpanel", description="Admin idarəetmə paneli"),
    ])
    
    logger.info("Bot işə düşür...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
