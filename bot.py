import logging
import random
import os
import psycopg2
import sys
import asyncio
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command, CommandObject
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.enums import ChatType, ParseMode
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

# Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- BAZA VƏ ƏSAS DƏYİŞƏNLƏR ---
DATABASE_URL = os.environ.get("DATABASE_URL")
TOKEN = os.environ.get("TELEGRAM_TOKEN")
BOT_OWNER_ID = 6751376199

# Aiogram obyektləri
bot = Bot(token=TOKEN, parse_mode="HTML")
dp = Dispatcher(storage=MemoryStorage())

# --- Oyunlar üçün Vəziyyətlər (States) ---
class QuizState(StatesGroup):
    in_game = State()

class DCState(StatesGroup):
    registration = State()
    playing = State()

# --- BAZA FUNKSİYALARI ---
def init_db():
    conn, cur = None, None
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
        if cur: cur.close()
        if conn: conn.close()

async def is_user_premium_async(user_id: int) -> bool:
    def sync_check():
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
    return await asyncio.to_thread(sync_check)

async def add_premium_user_async(user_id: int):
    def sync_add():
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
    return await asyncio.to_thread(sync_add)

async def remove_premium_user_async(user_id: int):
    def sync_remove():
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
    return await asyncio.to_thread(sync_remove)


# --- MƏZMUN SİYAHILARI ---
ABOUT_TEXT = "🤖 <b>Bot Haqqında</b>\n\nMən qruplar üçün nəzərdə tutulmuş əyləncə botuyam."
RULES_TEXT = "📜 <b>Qrup Qaydaları</b>\n\n1. Reklam etmək qəti qadağandır.\n2. Təhqir, söyüş və aqressiv davranışlara icazə verilmir."
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
    except Exception:
        return False

# --- ƏSAS ƏMRLƏR ---
@dp.message(CommandStart())
async def start_command(message: Message):
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="ℹ️ Bot Haqqında", callback_data="start_info_about"))
    builder.row(types.InlineKeyboardButton(text="📜 Qaydalar", callback_data="start_info_qaydalar"))
    await message.answer("Salam! Mən Oyun Botuyam. 🤖\nMenyudan seçin:", reply_markup=builder.as_markup())
    
# --- OYUN ƏMRLƏRİ ---
@dp.message(Command("viktorina"))
async def viktorina_command(message: Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state is not None:
        await message.reply("Artıq aktiv bir oyun var!")
        return
    
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="Viktorina (Sadə) 🌱", callback_data="viktorina_sade"))
    builder.row(types.InlineKeyboardButton(text="Viktorina (Premium) 👑", callback_data="viktorina_premium"))
    await message.answer(f"Salam, {message.from_user.full_name}! Viktorina növünü seçin:", reply_markup=builder.as_markup())

@dp.message(Command("dcoyun"))
async def dcoyun_command(message: Message, state: FSMContext):
    if message.chat.type == 'private':
        await message.reply("Bu oyunu yalnız qruplarda oynamaq olar.")
        return
    if not await is_user_admin(message.chat.id, message.from_user.id):
        await message.reply("⛔ Bu oyunu yalnız qrup adminləri başlada bilər.")
        return
    current_state = await state.get_state()
    if current_state is not None:
        await message.reply("Artıq aktiv bir oyun var.")
        return
    
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="Doğruluq Cəsarət (sadə)", callback_data="dc_select_sade"))
    builder.row(types.InlineKeyboardButton(text="Doğruluq Cəsarət (Premium👑)", callback_data="dc_select_premium"))
    await message.answer("Doğruluq Cəsarət oyununa xoş gəlmisiniz👋", reply_markup=builder.as_markup())

# --- ADMİN ƏMRLƏRİ ---
@dp.message(Command("addpremium"))
async def add_premium(message: Message, command: CommandObject):
    if message.from_user.id != BOT_OWNER_ID:
        return await message.reply("⛔ Bu əmrdən yalnız bot sahibi istifadə edə bilər.")
    if not command.args:
        return await message.reply("⚠️ Düzgün istifadə: <code>/addpremium &lt;user_id&gt;</code>")
    try:
        target_user_id = int(command.args)
        if await add_premium_user_async(target_user_id):
            await message.reply(f"✅ <code>{target_user_id}</code> ID-li istifadəçi uğurla premium siyahısına əlavə edildi.")
    except (IndexError, ValueError):
        await message.reply("⚠️ Düzgün istifadə: <code>/addpremium &lt;user_id&gt;</code> (ID rəqəm olmalıdır)")

@dp.message(Command("removepremium"))
async def remove_premium(message: Message, command: CommandObject):
    if message.from_user.id != BOT_OWNER_ID:
        return await message.reply("⛔ Bu əmrdən yalnız bot sahibi istifadə edə bilər.")
    if not command.args:
        return await message.reply("⚠️ Düzgün istifadə: <code>/removepremium &lt;user_id&gt;</code>")
    try:
        target_user_id = int(command.args)
        if await remove_premium_user_async(target_user_id):
            await message.reply(f"✅ <code>{target_user_id}</code> ID-li istifadəçinin premium statusu geri alındı.")
        else:
            await message.reply("❌ Belə bir premium istifadəçi tapılmadı.")
    except (IndexError, ValueError):
        await message.reply("⚠️ Düzgün istifadə: <code>/removepremium &lt;user_id&gt;</code> (ID rəqəm olmalıdır)")

@dp.message(Command("addquestions"))
async def addquestions_command(message: Message):
    if message.from_user.id != BOT_OWNER_ID:
        return await message.reply("⛔ Bu əmrdən yalnız bot sahibi istifadə edə bilər.")
    await message.reply("⏳ Suallar bazaya əlavə edilir...")
    
    simple_questions = [ {'question': 'Azərbaycanın paytaxtı haradır?', 'options': ['Gəncə', 'Sumqayıt', 'Bakı', 'Naxçıvan'], 'correct': 'Bakı'}, {'question': 'Bir ildə neçə fəsil var?', 'options': ['2', '3', '4', '5'], 'correct': '4'},]
    premium_questions = [ {'question': 'Əsərlərini Nizami Gəncəvi imzası ilə yazan şairin əsl adı nədir?', 'options': ['İlyas Yusif oğlu', 'Məhəmməd Füzuli', 'İmadəddin Nəsimi', 'Əliağa Vahid'], 'correct': 'İlyas Yusif oğlu'}, {'question': 'Leonardo da Vinçinin "Mona Liza" tablosu hansı muzeydədir?', 'options': ['Britaniya Muzeyi', 'Vatikan Muzeyi', 'Ermitaj', 'Luvr Muzeyi'], 'correct': 'Luvr Muzeyi'},]
    
    def sync_add_questions():
        conn, cur = None, None
        try:
            conn = psycopg2.connect(DATABASE_URL, sslmode='require')
            cur = conn.cursor()
            added_count = 0
            for q in simple_questions:
                cur.execute("INSERT INTO quiz_questions (question_text, options, correct_answer, is_premium) VALUES (%s, %s, %s, %s) ON CONFLICT (question_text) DO NOTHING;", (q['question'], q['options'], q['correct'], False))
                added_count += cur.rowcount
            for q in premium_questions:
                cur.execute("INSERT INTO quiz_questions (question_text, options, correct_answer, is_premium) VALUES (%s, %s, %s, %s) ON CONFLICT (question_text) DO NOTHING;", (q['question'], q['options'], q['correct'], True))
                added_count += cur.rowcount
            conn.commit()
            return added_count
        except Exception as e:
            logger.error(f"Sualları bazaya yazarkən xəta: {e}"); return -1
        finally:
            if cur: cur.close()
            if conn: conn.close()

    count = await asyncio.to_thread(sync_add_questions)
    if count != -1:
        await message.answer(f"✅ Baza yoxlanıldı. {count} yeni sual uğurla əlavə edildi.")
    else:
        await message.answer("❌ Sualları bazaya yazarkən xəta baş verdi.")

# --- DÜYMƏ HANDLERİ ---
@dp.callback_query()
async def button_handler(query: CallbackQuery):
    data = query.data
    
    if data == "start_info_about":
        await query.message.edit_text(ABOUT_TEXT, parse_mode="HTML")
    elif data == "start_info_qaydalar":
        await query.message.edit_text(RULES_TEXT, parse_mode="HTML")
    
    await query.answer()

# --- ƏSAS MAIN FUNKSİYASI ---
async def main() -> None:
    if not TOKEN:
        logger.critical("TELEGRAM_TOKEN tapılmadı! Bot dayandırılır.")
        return
    
    _init_db() # Bot işə düşəndə bazanı sinxron olaraq yoxlayır/yaradır
    
    await bot.set_my_commands([
        BotCommand(command="start", description="Əsas menyunu açmaq"),
        BotCommand(command="viktorina", description="Viktorina oyununu başlatmaq"),
        BotCommand(command="dcoyun", description="Doğruluq/Cəsarət oyununu başlatmaq"),
    ])
    
    logger.info("Sadələşdirilmiş Aiogram botu işə düşür...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
