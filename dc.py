import logging
import random
import os
import psycopg2
import datetime
import sys
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters, ConversationHandler
from telegram.constants import ChatType
from telegram.error import Forbidden

# Logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# --- BAZA VƏ ƏSAS DƏYİŞƏNLƏR ---
DATABASE_URL = os.environ.get("DATABASE_URL")
TOKEN = os.environ.get("TELEGRAM_TOKEN")
BOT_OWNER_ID = int(os.environ.get("BOT_OWNER_ID", 0))

# --- "İKİ DÜZ, BİR YALAN" OYUNU ÜÇÜN MƏRHƏLƏLƏR ---
STATEMENT_1, STATEMENT_2, STATEMENT_3, WHICH_IS_LIE = range(4)

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
        cur.execute("CREATE TABLE IF NOT EXISTS bot_users (user_id BIGINT PRIMARY KEY, first_name TEXT, date_added TIMESTAMPTZ NOT NULL);")
        cur.execute("CREATE TABLE IF NOT EXISTS active_chats (chat_id BIGINT PRIMARY KEY, chat_title TEXT, date_added TIMESTAMPTZ NOT NULL);")
        conn.commit(); cur.close(); conn.close()
        print("Verilənlər bazası cədvəli hazırdır.")
    except Exception as e:
        print(f"Baza yaradılarkən xəta: {e}")

# --- MƏZMUN SİYAHILARI ---
STORY_DATA = { 'start_temple': {'text': "Siz qədim və unudulmuş bir məbədin girişində dayanmısınız...", 'choices': [{'text': "📚 İçəridəki kitabxanaya keç", 'goto': 'temple_library'}, {'text': "🗝️ Bağlı qapını yoxla", 'goto': 'temple_locked_door'}]}, 'temple_library': {'text': "Tozlu kitabxanaya daxil olursunuz...", 'get_item': 'köhnə kitab', 'choices': [{'text': "Kitabı oxu", 'goto': 'read_book'}, {'text': "Qapıya tərəf qayıt", 'goto': 'temple_locked_door'}]}, 'read_book': {'text': "Kitabı vərəqləyirsiniz. İçində yazılıb: 'Gözətçi yalnız doğru sözləri deyənə yol verər.'...", 'choices': [{'text': "Qapıya get", 'goto': 'temple_locked_door'}]}, 'temple_locked_door': {'text': "Böyük bir daş qapının qarşısındasınız...", 'choices': [{'text': "Parolu de ('İşıq')", 'goto': 'guardian_chamber', 'requires_item': 'köhnə kitab'}, {'text': "Qapını güclə açmağa çalış", 'goto': 'fail_door'}]}, 'fail_door': {'text': "Qapını itələməyə çalışsanız da, yerindən tərpənmir...", 'choices': []}, 'guardian_chamber': {'text': "Qapı açılır. İçəridə 'Dağın Ürəyi' almazını qoruyan bir Gözətçi dayanır...", 'choices': [{'text': "Cavab: 'Nəfəs'", 'goto': 'win_temple'}, {'text': "Cavab: 'Xəyal'", 'goto': 'fail_guardian'}]}, 'fail_guardian': {'text': "Gözətçi 'Səhv cavab!' deyərək sizi məbəddən çölə atır...", 'choices': []}, 'win_temple': {'text': "Gözətçi gülümsəyir: 'Doğrudur'. O, kənara çəkilir və siz 'Dağın Ürəyi' almazını götürürsünüz...", 'choices': []}, 'start_shipwreck': {'text': "Fırtınalı bir gecədən sonra naməlum bir adanın sahilində oyanırsınız...", 'choices': [{'text': "🏝️ Sahili araşdır", 'goto': 'explore_beach'}, {'text': "🌳 Cəngəlliyə daxil ol", 'goto': 'enter_jungle'}]}, 'explore_beach': {'text': "Sahili araşdırarkən qumun içində köhnə bir butulka tapırsınız...", 'get_item': 'xəritə parçası 1', 'get_item_2': 'möhkəm taxta', 'choices': [{'text': "Cəngəlliyə daxil ol", 'goto': 'enter_jungle'}]}, 'enter_jungle': {'text': "Sıx cəngəlliyə daxil olursunuz. Qarşınıza timsahlarla dolu bir çay çıxır.",'choices': [{'text': "🛶 Sal düzəlt", 'goto': 'build_raft', 'requires_item': 'möhkəm taxta'}, {'text': "🏊‍♂️ Üzərək keçməyə çalış", 'goto': 'swim_fail'}, {'text': "Geri qayıt", 'goto': 'start_shipwreck'}]}, 'swim_fail': {'text': "Çayı üzərək keçməyə çalışırsınız, lakin timsahlar sizi tutur...", 'choices': []}, 'build_raft': {'text': "Möhkəm taxta parçasından istifadə edərək kiçik bir sal düzəldirsiniz...", 'choices': [{'text': "Daxmanı araşdır", 'goto': 'explore_hut'}]}, 'explore_hut': {'text': "Köhnə daxmanın içində bir sandıq tapırsınız...", 'get_item': 'xəritə parçası 2', 'choices': [{'text': "Xəritəni birləşdir", 'goto': 'map_complete'}]}, 'map_complete': {'text': "Xəritənin iki parçasını birləşdirirsiniz. Xəzinəni tapırsınız...", 'choices': []}}
QUIZ_QUESTIONS = [{'question': 'Azərbaycanın paytaxtı haradır?', 'options': ['Gəncə', 'Sumqayıt', 'Bakı', 'Naxçıvan'], 'correct': 'Bakı'}]
RIDDLES = [{'riddle': 'Ağzı var, dili yox, danışdıqca cana gəlir. Bu nədir?', 'answers': ['kitab']}]
NORMAL_TRUTH_QUESTIONS = ["Uşaqlıqda ən böyük qorxun nə idi?"]
NORMAL_DARE_TASKS = ["Profil şəklini 1 saatlıq qrupdakı ən son göndərilən şəkil ilə dəyişdir."]
RULES_TEXT = "📜 **Oyun Botunun Qaydaları** 📜\n\n(Bura qaydalar mətni daxil ediləcək...)"
ABOUT_TEXT = "🤖 **Bot Haqqında Məlumat** 🤖\n\n(Bura bot haqqında məlumat mətni daxil ediləcək...)"

# --- ƏSAS FUNKSİYALAR ---
def get_rank_title(count: int) -> str:
    if count <= 100: return "Yeni Üzv 👶"
    elif count <= 500: return "Daimi Sakin 👨‍💻"
    # ... (digər rütbələr)
    else: return "Söhbət Tanrısı ⚡️"
async def welcome_new_members(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ... (kod eyni qalır)
    pass
async def is_user_admin(chat_id: int, user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    # ... (kod eyni qalır)
    pass
async def ask_next_player(chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    # ... (kod eyni qalır)
    pass
# --- ƏSAS ƏMRLƏR ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ... (kod eyni qalır)
    pass
async def qaydalar_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ... (kod eyni qalır)
    pass
async def haqqinda_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ... (kod eyni qalır)
    pass
async def macera_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ... (kod eyni qalır)
    pass
async def show_rpg_node(update: Update, context: ContextTypes.DEFAULT_TYPE, node_key: str):
    # ... (kod eyni qalır)
    pass
async def game_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ... (kod eyni qalır)
    pass
async def start_game_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ... (kod eyni qalır)
    pass
async def next_turn_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ... (kod eyni qalır)
    pass
async def stop_game_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ... (kod eyni qalır)
    pass
async def join_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ... (kod eyni qalır)
    pass
async def leave_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ... (kod eyni qalır)
    pass
async def tapmaca_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ... (kod eyni qalır)
    pass
async def viktorina_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ... (kod eyni qalır)
    pass
async def rating_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ... (kod eyni qalır)
    pass
async def my_rank_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ... (kod eyni qalır)
    pass
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ... (kod eyni qalır)
    pass
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ... (kod eyni qalır)
    pass

# --- MAIN FUNKSİYASI ---
def main() -> None:
    run_pre_flight_checks()
    init_db()
    
    application = Application.builder().token(TOKEN).build()
    
    group_filter = ~filters.ChatType.PRIVATE
    private_filter = filters.ChatType.PRIVATE
    
    # ... (Bütün CommandHandler və digər handler-lər burada əlavə olunur)

    print("Bot işə düşdü...")
    application.run_polling()

if __name__ == '__main__':
    main()
