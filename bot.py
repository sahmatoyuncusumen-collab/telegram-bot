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
TOKEN = os.environ.get("TELEGRAM_TOKEN")

# Aiogram obyektləri
bot = Bot(token=TOKEN, parse_mode="HTML")
dp = Dispatcher()

# --- MƏZMUN SİYAHILARI ---
ABOUT_TEXT = "🤖 **Bot Haqqında**\n\nMən qruplar üçün nəzərdə tutulmuş əyləncə və statistika botuyam."
RULES_TEXT = "📜 **Qrup Qaydaları**\n\n1. Reklam etmək qəti qadağandır.\n2. Təhqir, söyüş və aqressiv davranışlara icazə verilmir."

SADE_TRUTH_QUESTIONS = ["Uşaqlıqda ən böyük qorxun nə olub?", "Heç kimin bilmədiyi bir bacarığın var?"]
SADE_DARE_TASKS = ["Qrupdakı son mesajı əlifbanın hər hərfi ilə tərsinə yaz.", "Profil şəklini 5 dəqiqəlik bir meyvə şəkli ilə dəyişdir."]
SADE_QUIZ_QUESTIONS = [{'question': 'Azərbaycanın paytaxtı haradır?', 'options': ['Gəncə', 'Sumqayıt', 'Bakı', 'Naxçıvan'], 'correct': 'Bakı'}]

# --- ƏSAS ƏMRLƏR ---
@dp.message(CommandStart())
async def start_command(message: Message):
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="ℹ️ Bot Haqqında", callback_data="start_info_about"))
    builder.row(types.InlineKeyboardButton(text="📜 Qaydalar", callback_data="start_info_qaydalar"))
    await message.answer("Salam! Mən Oyun Botuyam. 🤖\nMenyudan seçin:", reply_markup=builder.as_markup())

# --- OYUN ƏMRLƏRİ ---
@dp.message(Command("viktorina"))
async def viktorina_command(message: Message):
    question_data = random.choice(SADE_QUIZ_QUESTIONS)
    question = question_data['question']
    options = question_data['options']
    
    builder = InlineKeyboardBuilder()
    for option in options:
        # Hər cavab üçün callback_data yaradırıq (düzgün və ya səhv olduğunu qeyd edirik)
        callback_text = "quiz_correct" if option == question_data['correct'] else "quiz_wrong"
        builder.add(types.InlineKeyboardButton(text=option, callback_data=callback_text))
    
    builder.adjust(2) # Düymələri 2-2 düzür
    await message.answer(f"<b>Viktorina:</b>\n{question}", reply_markup=builder.as_markup())

@dp.message(Command("dcoyun"))
async def dcoyun_command(message: Message):
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="Doğruluq 🤔", callback_data="dc_truth"))
    builder.row(types.InlineKeyboardButton(text="Cəsarət 😈", callback_data="dc_dare"))
    await message.answer("Doğruluq yoxsa Cəsarət? Seçim edin:", reply_markup=builder.as_markup())

# --- DÜYMƏ HANDLERİ ---
@dp.callback_query()
async def button_handler(query: CallbackQuery):
    data = query.data
    user_name = query.from_user.full_name
    
    if data == "start_info_about":
        await query.message.edit_text("<b>Bot Haqqında</b>\n\nMən qruplar üçün nəzərdə tutulmuş əyləncə botuyam.", parse_mode="HTML")
    elif data == "start_info_qaydalar":
        await query.message.edit_text("<b>Qrup Qaydaları</b>\n\n1. Reklam qadağandır.\n2. Təhqir qadağandır.", parse_mode="HTML")
        
    # Viktorina cavabları
    elif data == "quiz_correct":
        await query.message.edit_text(f"✅ Afərin, {user_name}! Düzgün cavab.")
    elif data == "quiz_wrong":
        await query.message.edit_text(f"❌ Təəssüf, {user_name}. Səhv cavab.")
        
    # Doğruluq/Cəsarət seçimləri
    elif data == "dc_truth":
        question = random.choice(SADE_TRUTH_QUESTIONS)
        await query.message.edit_text(f"🤔 <b>Doğruluq:</b>\n\n<i>{question}</i>")
    elif data == "dc_dare":
        task = random.choice(SADE_DARE_TASKS)
        await query.message.edit_text(f"😈 <b>Cəsarət:</b>\n\n<i>{task}</i>")
        
    await query.answer()

# --- ƏSAS MAIN FUNKSİYASI ---
async def main() -> None:
    if not TOKEN:
        logger.critical("TELEGRAM_TOKEN tapılmadı! Bot dayandırılır.")
        return
    
    logger.info("Sadələşdirilmiş Aiogram botu işə düşür...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
