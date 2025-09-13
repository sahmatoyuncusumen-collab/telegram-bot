import logging
import random
import os
import psycopg2
import datetime
import sys
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters
from telegram.constants import ChatType

# Logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# --- BAZA VƏ ƏSAS DƏYİŞƏNLƏR ---
DATABASE_URL = os.environ.get("DATABASE_URL")
TOKEN = os.environ.get("TELEGRAM_TOKEN")

# --- TƏHLÜKƏSİZLİK YOXLAMASI ---
def run_pre_flight_checks():
    if not DATABASE_URL or not TOKEN:
        print("--- XƏTA ---"); print("DATABASE_URL və ya TELEGRAM_TOKEN tapılmadı."); sys.exit(1)
    print("Bütün konfiqurasiya dəyişənləri mövcuddur. Bot başladılır...")

# --- BAZA FUNKSİYASI ---
def init_db():
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cur = conn.cursor()
        cur.execute("CREATE TABLE IF NOT EXISTS message_counts (id SERIAL PRIMARY KEY, chat_id BIGINT NOT NULL, user_id BIGINT NOT NULL, username TEXT NOT NULL, message_timestamp TIMESTAMPTZ NOT NULL );")
        conn.commit(); cur.close(); conn.close()
        print("Verilənlər bazası cədvəli hazırdır.")
    except Exception as e:
        print(f"Baza yaradılarkən xəta: {e}")

# --- MƏZMUN SİYAHILARI ---
# ... (Bütün sual, tapmaca və macəra siyahıları olduğu kimi qalır, qısalıq üçün göstərilmir)
STORY_DATA = {
    'start': {'text': "Siz qədim bir məbədin girişində dayanmısınız...", 'choices': [{'text': "🌳 Meşə cığırı ilə get", 'goto': 'forest_entrance'}, {'text': "🦇 Qaranlıq mağaraya daxil ol", 'goto': 'cave_entrance'}]},
    # ... Hekayənin qalan hissələri ...
    'treasure_found': {'text': "Əfsanəvi qılıncı əldə etdiniz! Macəranız uğurla başa çatdı. Qələbə! 🏆\n\nYeni macəra üçün /macera yazın.",'choices': []},
    'go_back': {'text': "Açarınız olmadığı üçün geri qayıtmaqdan başqa çarəniz yoxdur...",'choices': [{'text': "🦇 Mağaraya daxil ol", 'goto': 'cave_entrance'}, {'text': "🌳 Meşə cığırı ilə get", 'goto': 'forest_path'}]}
}
RULES_TEXT = "📜 **Oyun Botunun Qaydaları** 📜\n\n(Qaydalar mətni burada yerləşir...)"
ABOUT_TEXT = "🤖 **Bot Haqqında Məlumat** 🤖\n\nMən Azərbaycan dilində müxtəlif oyunlar təklif edən bir əyləncə botuyam.\n\nMənimlə aşağıdakı oyunları oynaya bilərsiniz:\n- Doğruluq yoxsa Cəsarət?\n- Tapmaca\n- Viktorina (Quiz)\n- Mətn-əsaslı Macəra\n\nHəmçinin, qruplardakı aktivliyi izləyən reytinq sistemim var.\n\nƏyləncəli vaxt keçirməyiniz diləyi ilə!"

# --- FUNKSİYALAR ---
# ... (get_rank_title, welcome_new_members, is_user_admin, və s. olduğu kimi qalır)

# --- ƏSAS ƏMRLƏR (YENİLƏNİB VƏ YENİLƏRİ ƏLAVƏ EDİLİB) ---

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Bota /start yazıldıqda yenilənmiş interaktiv menyu göndərir."""
    keyboard = [
        [InlineKeyboardButton("ℹ️ Bot Haqqında Məlumat", callback_data="start_info_about")],
        [InlineKeyboardButton("📜 Bütün Qaydalar", callback_data="start_info_qaydalar")],
        [InlineKeyboardButton("👥 Oyun Qrupumuz", url="https://t.me/+0z5V-OvEMmgzZTFi")],
        [InlineKeyboardButton("👨‍💻 Admin ilə Əlaqə", url="https://t.me/tairhv")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    start_text = "Salam! Mən Oyun Botuyam. 🤖\nAşağıdakı menyudan istədiyin bölməni seç:"
    
    await update.message.reply_text(start_text, reply_markup=reply_markup)

async def private_game_warning(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Şəxsi söhbətdə oyun əmrləri yazıldıqda xəbərdarlıq edir."""
    await update.message.reply_text("⛔ Bu oyun yalnız qruplarda oynanıla bilər. Zəhmət olmasa, məni bir qrupa əlavə edib orada yenidən cəhd edin.")

async def haqqinda_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Bot haqqında məlumatı göndərir."""
    await update.message.reply_text(ABOUT_TEXT, parse_mode='Markdown')

async def macera_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Macəra oyununu hər kəsin şəxsi söhbətdə oynaması üçün link göndərir."""
    bot_username = (await context.bot.get_me()).username
    start_link = f"https://t.me/{bot_username}?start=macera"
    
    keyboard = [[InlineKeyboardButton("⚔️ Macəranı Şəxsidə Başlat", url=start_link)]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "Hər kəs öz şəxsi macərasını yaşaya bilər!\n\nAşağıdakı düyməyə basaraq mənimlə şəxsi söhbətə başla və öz fərdi oyununu oyna:",
        reply_markup=reply_markup
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if data.startswith("start_info_"):
        command_name = data.split('_')[-1]
        
        # 'Bütün Qaydalar' və 'Bot Haqqında' düymələrini idarə edirik
        if command_name == 'qaydalar':
            await query.message.reply_text(RULES_TEXT, parse_mode='Markdown')
        elif command_name == 'about':
            await query.message.reply_text(ABOUT_TEXT, parse_mode='Markdown')
        return
        
    # ... (qalan bütün köhnə button handler məntiqi olduğu kimi qalır)
    # ...

def main() -> None:
    run_pre_flight_checks()
    init_db()
    
    application = Application.builder().token(TOKEN).build()
    
    group_filter = ~filters.ChatType.PRIVATE
    private_filter = filters.ChatType.PRIVATE

    # Bütün əmrlər
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("qaydalar", qaydalar_command))
    application.add_handler(CommandHandler("haqqinda", haqqinda_command)) # YENİ
    
    # Qrup oyunları üçün handler-lər
    application.add_handler(CommandHandler("oyun", game_command, filters=group_filter))
    application.add_handler(CommandHandler("tapmaca", tapmaca_command, filters=group_filter))
    application.add_handler(CommandHandler("viktorina", viktorina_command, filters=group_filter))
    application.add_handler(CommandHandler("macera", macera_command, filters=group_filter))
    # ... (bütün digər qrup əmrləri)
    
    # Şəxsi söhbətdə oyun əmrləri üçün xəbərdarlıq
    game_commands = ["oyun", "tapmaca", "viktorina", "reyting", "menim_rutbem", "baslat", "novbeti", "dayandir", "qosul", "cix"]
    application.add_handler(CommandHandler(game_commands, private_game_warning, filters=private_filter))
    
    # ... (qalan bütün handler-lər)

    print("Bot işə düşdü...")
    application.run_polling()

if __name__ == '__main__':
    main()

# --- Tam Kod ---
# (Yuxarıdakı izahla birlikdə, kodun tam versiyası çox uzun olduğu üçün,
# zəhmət olmasa, bu yeni funksiyaları öz kodunuza inteqrasiya edin.
# Əgər tam kodu istəsəniz, yenidən göndərə bilərəm.)
