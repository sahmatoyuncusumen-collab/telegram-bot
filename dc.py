import logging
import random
import os
import psycopg2
import datetime
import sys
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
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
    # ... (dəyişməz qalır)
    pass

# --- BAZA FUNKSİYALARI ---
def init_db():
    # ... (dəyişməz qalır)
    pass
def is_user_premium(user_id: int) -> bool:
    # ... (dəyişməz qalır)
    pass
def add_premium_user(user_id: int) -> bool:
    # ... (dəyişməz qalır)
    pass
def remove_premium_user(user_id: int) -> bool:
    # ... (dəyişməz qalır)
    pass

# --- MƏZMUN SİYAHILARI ---
ABOUT_TEXT = "🤖 **Bot Haqqında**\n\nMən qruplar üçün nəzərdə tutulmuş əyləncə və statistika botuyam..."
RULES_TEXT = "📜 **Qrup Qaydaları**\n\n1. Reklam etmək qəti qadağandır..."

# VIKTORINA SUALLARI (40 Sadə + 80 Premium)
SADE_QUIZ_QUESTIONS = [
    # ... (sual siyahılarınız burada tam şəkildə qalır) ...
]
PREMIUM_QUIZ_QUESTIONS = [
    # ... (sual siyahılarınız burada tam şəkildə qalır) ...
]

# YENİLİK: DOĞRULUQ VƏ CƏSARƏT SUALLARI (Başlanğıc Paketi)
SADE_TRUTH_QUESTIONS = [
    "Uşaqlıqda ən böyük qorxun nə olub?",
    "Heç kimin bilmədiyi bir bacarığın var?",
    "Ən son nə vaxt ağlamısan və niyə?",
    "Əgər bir gün görünməz olsaydın, nə edərdin?",
    "Telefonunda ən utancverici proqram hansıdır?",
    "Həyatında ən çox peşman olduğun şey nədir?",
    "Heç yalan danışıb yaxalanmısan?",
    "Birinə aşiq olub amma deməmisən?",
    "Ən qəribə yuxun nə olub?",
    "Hamamda mahnı oxuyursan?",
]
SADE_DARE_TASKS = [
    "Qrupdakı son mesajı əlifbanın hər hərfi ilə tərsinə yaz.",
    "Telefonundakı son şəkli qrupa göndər (uyğun deyilsə, ondan əvvəlkini).",
    "Qrupdakı birinə kompliment de.",
    "Elə indicə pəncərədən çölə \"Mən dünyanı sevirəm!\" deyə qışqır.",
    "Profil şəklini 5 dəqiqəlik bir meyvə şəkli ilə dəyişdir.",
    "Ən sevdiyin mahnıdan bir hissəni səsli mesajla göndər.",
    "Bir stəkan suyu birnəfəsə iç.",
    "İki fərqli corab geyin və şəklini çəkib göndər.",
    "Telefonunun klaviaturasında gözüyumulu \"Mən ən yaxşı oyunçuyam\" yazmağa çalış.",
    "Emojilərlə bir film adı təsvir et, qoy qrup tapsın.",
]
PREMIUM_TRUTH_QUESTIONS = [
    "Həyatının geri qalanını yalnız bir filmi izləyərək keçirməli olsaydın, hansı filmi seçərdin?",
    "Əgər zaman maşının olsaydı, keçmişə yoxsa gələcəyə gedərdin? Niyə?",
    "Sənə ən çox təsir edən kitab hansı olub?",
    "Münasibətdə sənin üçün ən vacib 3 şey nədir?",
    "Özündə dəyişdirmək istədiyin bir xüsusiyyət hansıdır?",
    "Heç sosial mediada birini gizlicə izləmisən (stalk)?",
    "İnsanların sənin haqqında bilmədiyi qəribə bir vərdişin var?",
    "Ən böyük xəyalın nədir?",
    "Valideynlərindən gizlətdiyin bir şey olub?",
    "Məşhur birindən xoşun gəlir?",
]
PREMIUM_DARE_TASKS = [
    "Qrupdakı adminlərdən birinə 10 dəqiqəlik \"Ən yaxşı admin\" statusu yaz.",
    "Səni ən yaxşı təsvir edən bir \"meme\" tap və qrupa göndər.",
    "Son 1 saat içində telefonla danışdığın son insana zəng edib \"Səni indicə cəsarət oyununda seçdilər\" de.",
    "Səsini dəyişdirərək bir nağıl personajı kimi danış və səsli mesaj göndər.",
    "Google-da \"Mən niyə bu qədər möhtəşəməm\" yazıb axtarış nəticələrinin şəklini göndər.",
    "Qrupdakı onlayn olan birinə şəxsi mesajda qəribə bir emoji göndər və heç nə yazma.",
    "Profil bioqrafiyanı 15 dəqiqəlik \"Bu qrupun premium üzvü\" olaraq dəyişdir.",
    "Bir qaşıq limon suyu iç.",
    "Bir dəsmalı başına papaq kimi qoy və şəklini çəkib göndər.",
    "Qrup söhbətinin adını 1 dəqiqəlik \"Ən yaxşı söhbət qrupu\" olaraq dəyişdir (əgər icazən varsa).",
]

# --- KÖMƏKÇİ FUNKSİYALAR ---
async def is_user_admin(chat_id: int, user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if user_id == chat_id: return True # Şəxsi söhbətdə hər kəs admindir
    try:
        chat_admins = await context.bot.get_chat_administrators(chat_id)
        return user_id in [admin.user.id for admin in chat_admins]
    except Exception as e:
        logger.error(f"Admin yoxlanarkən xəta: {e}")
        return False

# DƏYİŞİKLİK: Rütbə adı funksiyası premium statusu nəzərə alır
def get_rank_title(count: int, is_premium: bool = False) -> str:
    if is_premium and count > 5000:
        return "Qızıl Tac ⚜️"
    
    if count <= 50: return "Yeni Gələn 🐣"
    elif count <= 250: return "Daimi Sakin 🏠"
    elif count <= 750: return "Söhbətcil 🗣️"
    elif count <= 2000: return "Qrup Ağsaqqalı 👴"
    elif count <= 5000: return "Söhbət Baronu 👑"
    else: return "Qrupun Əfsanəsi ⚡️"

async def welcome_new_members(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ... (dəyişməz qalır)
    pass

# --- ƏSAS ƏMRLƏR ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ... (dəyişməz qalır)
    pass
async def haqqinda_command(update: Update, context: ContextTypes.DEFAULT_TYPE): await update.message.reply_text(ABOUT_TEXT, parse_mode='Markdown')
async def qaydalar_command(update: Update, context: ContextTypes.DEFAULT_TYPE): await update.message.reply_text(RULES_TEXT, parse_mode='Markdown')

# DƏYİŞİKLİK: my_rank_command premium xüsusiyyətlərini dəstəkləyir
async def my_rank_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.chat.type in [ChatType.GROUP, ChatType.SUPERGROUP]:
        await update.message.reply_text("Bu əmr yalnız qruplarda işləyir.")
        return

    user = update.message.from_user
    chat_id = update.message.chat_id
    raw_message_count = 0
    conn, cur = None, None
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cur = conn.cursor()
        cur.execute( "SELECT COUNT(*) FROM message_counts WHERE user_id = %s AND chat_id = %s;", (user.id, chat_id) )
        result = cur.fetchone()
        if result: raw_message_count = result[0]
    except Exception as e:
        logger.error(f"Rütbə yoxlanarkən xəta: {e}")
        await update.message.reply_text("❌ Rütbənizi yoxlayarkən xəta baş verdi.")
        return
    finally:
        if cur: cur.close()
        if conn: conn.close()

    user_is_premium = is_user_premium(user.id)
    
    # Premium Sürətləndirici
    effective_message_count = int(raw_message_count * 1.5) if user_is_premium else raw_message_count
    
    rank_title = get_rank_title(effective_message_count, user_is_premium)
    
    # Premium Status Nişanı
    premium_icon = " 👑" if user_is_premium else ""
    
    reply_text = (
        f"📊 **Sənin Statistikaların, {user.first_name}{premium_icon}!**\n\n"
        f"💬 Bu qrupdakı real mesaj sayın: **{raw_message_count}**\n"
    )
    if user_is_premium:
        reply_text += f"🚀 Premium ilə hesablanmış xalın: **{effective_message_count}**\n"
    
    reply_text += (
        f"🏆 Rütbən: **{rank_title}**\n\n"
        "Daha çox mesaj yazaraq yeni rütbələr qazan!"
    )
    await update.message.reply_text(reply_text, parse_mode='Markdown')

async def zer_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ... (dəyişməz qalır)
    pass

# YENİLİK: Liderlər Cədvəli
async def liderler_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.chat.type in [ChatType.GROUP, ChatType.SUPERGROUP]:
        await update.message.reply_text("Bu əmr yalnız qruplarda işləyir.")
        return

    chat_id = update.message.chat.id
    leaderboard_text = f"🏆 **'{update.message.chat.title}'**\nBu ayın ən aktiv 10 istifadəçisi:\n\n"
    conn, cur = None, None
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cur = conn.cursor()
        # Bu ayın ilk gününü tapır
        cur.execute(
            """
            SELECT user_id, COUNT(*) as msg_count 
            FROM message_counts 
            WHERE chat_id = %s AND message_timestamp >= date_trunc('month', NOW())
            GROUP BY user_id 
            ORDER BY msg_count DESC 
            LIMIT 10;
            """,
            (chat_id,)
        )
        leaders = cur.fetchall()
        
        if not leaders:
            await update.message.reply_text("Bu ay hələ heç kim mesaj yazmayıb. İlk sən ol!")
            return

        for i, (user_id, msg_count) in enumerate(leaders):
            try:
                member = await context.bot.get_chat_member(chat_id, user_id)
                user_name = member.user.first_name
            except Exception:
                user_name = f"İstifadəçi ({user_id})"
            
            premium_icon = " 👑" if is_user_premium(user_id) else ""
            place_icon = ["🥇", "🥈", "🥉"][i] if i < 3 else f"{i+1}."
            
            leaderboard_text += f"{place_icon} {user_name}{premium_icon} - **{msg_count}** mesaj\n"
            
        await update.message.reply_text(leaderboard_text, parse_mode='Markdown')

    except Exception as e:
        logger.error(f"Liderlər cədvəli göstərilərkən xəta: {e}")
        await update.message.reply_text("❌ Liderlər cədvəlini göstərərkən xəta baş verdi.")
    finally:
        if cur: cur.close()
        if conn: conn.close()
        
# YENİLİK: Doğruluq/Cəsarət oyunu
async def dcoyun_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    chat_id = update.message.chat.id
    
    if not await is_user_admin(chat_id, user_id, context):
        await update.message.reply_text("⛔ Bu oyunu yalnız qrup adminləri başlada bilər.")
        return
        
    keyboard = [
        [InlineKeyboardButton("Doğruluq Cəsarət (sadə)", callback_data="dc_sade")],
        [InlineKeyboardButton("Doğruluq Cəsarət (Premium👑)", callback_data="dc_premium")]
    ]
    await update.message.reply_text(
        "Doğruluq Cəsarət oyununa xoş gəlmisiniz👋",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# --- ADMİN ƏMRLƏRİ ---
async def add_premium_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ... (dəyişməz qalır)
    pass
async def remove_premium_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ... (dəyişməz qalır)
    pass

# --- VIKTORINA ƏMRİ VƏ OYUN MƏNTİQİ ---
async def viktorina_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ... (dəyişməz qalır)
    pass
async def ask_next_quiz_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ... (dəyişməz qalır)
    pass
    
# DÜYMƏLƏRİ VƏ MESAJLARI İDARƏ EDƏN FUNKSİYALAR
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; user = query.from_user; data = query.data
    chat_id = query.message.chat.id
    await query.answer()

    # Viktorina kilidi
    if data.startswith("viktorina_") or data.startswith("quiz_"):
        # ... (dəyişməz qalır)
        pass

    # Start menyusu...
    if data in ["start_info_about", "start_info_qaydalar", "back_to_start"]:
        # ... (dəyişməz qalır)
        pass
        
    # YENİLİK: Doğruluq/Cəsarət düymələri
    elif data == 'dc_sade':
        if not await is_user_admin(chat_id, user.id, context):
            await query.answer("⛔ Bu oyunu yalnız qrup adminləri başlada bilər.", show_alert=True)
            return
        keyboard = [[InlineKeyboardButton("Doğruluq 🤔", callback_data="dc_truth_sade"), InlineKeyboardButton("Cəsarət 😈", callback_data="dc_dare_sade")]]
        await query.message.edit_text("Seçim edin:", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data == 'dc_premium':
        if not (await is_user_admin(chat_id, user.id, context) and is_user_premium(user.id)):
            await query.answer("⛔ Bu rejimi yalnız premium statuslu adminlər başlada bilər.", show_alert=True)
            return
        keyboard = [[InlineKeyboardButton("Premium Doğruluq 🤫", callback_data="dc_truth_premium"), InlineKeyboardButton("Premium Cəsarət 🔥", callback_data="dc_dare_premium")]]
        await query.message.edit_text("Premium seçim edin:", reply_markup=InlineKeyboardMarkup(keyboard))
        
    elif data.startswith("dc_truth_"):
        is_premium = "premium" in data
        question = random.choice(PREMIUM_TRUTH_QUESTIONS if is_premium else SADE_TRUTH_QUESTIONS)
        await query.message.edit_text(f"🤔 **Doğruluq:**\n\n`{question}`")

    elif data.startswith("dc_dare_"):
        is_premium = "premium" in data
        task = random.choice(PREMIUM_DARE_TASKS if is_premium else SADE_DARE_TASKS)
        await query.message.edit_text(f"😈 **Cəsarət:**\n\n`{task}`")

    # Viktorina oyunu...
    elif data == 'viktorina_sade' or data == 'viktorina_premium':
        # ... (dəyişməz qalır)
        pass
    elif context.chat_data.get('quiz_active'):
        # ... (viktorina məntiqi dəyişməz qalır)
        pass
    else:
        await query.answer()

async def handle_all_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ... (dəyişməz qalır)
    pass

# --- ƏSAS MAIN FUNKSİYASI ---
async def main() -> None:
    run_pre_flight_checks()
    init_db()
    
    application = Application.builder().token(TOKEN).build()
    
    commands = [
        BotCommand("start", "Əsas menyunu açmaq"),
        BotCommand("qaydalar", "Qrup qaydalarını göstərmək"),
        BotCommand("haqqinda", "Bot haqqında məlumat"),
        BotCommand("menim_rutbem", "Şəxsi rütbəni yoxlamaq"),
        BotCommand("viktorina", "Viktorina oyununu başlatmaq"),
        BotCommand("zer", "1-6 arası zər atmaq"),
        BotCommand("liderler", "Aylıq liderlər cədvəli"),
        BotCommand("dcoyun", "Doğruluq/Cəsarət oyununu başlatmaq (Admin)"),
    ]
    
    # Handler-lər
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("qaydalar", qaydalar_command))
    application.add_handler(CommandHandler("haqqinda", haqqinda_command))
    application.add_handler(CommandHandler("menim_rutbem", my_rank_command))
    application.add_handler(CommandHandler("liderler", liderler_command))
    application.add_handler(CommandHandler("dcoyun", dcoyun_command))
    application.add_handler(CommandHandler("addpremium", add_premium_command))
    application.add_handler(CommandHandler("removepremium", remove_premium_command))
    application.add_handler(CommandHandler("viktorina", viktorina_command, filters=~filters.ChatType.PRIVATE))
    application.add_handler(CommandHandler("zer", zer_command))
    
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, welcome_new_members))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_all_messages))
    
    try:
        logger.info("Bot işə düşür...")
        await application.initialize()
        await application.bot.set_my_commands(commands)
        await application.updater.start_polling()
        await application.start()
        while True:
            await asyncio.sleep(3600)
    finally:
        # ... (dayandırma məntiqi dəyişməz qalır)
        pass

if __name__ == '__main__':
    asyncio.run(main())
