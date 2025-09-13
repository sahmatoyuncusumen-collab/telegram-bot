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
ABOUT_TEXT = """🤖 **Bot Haqqında Məlumat** 🤖

Mən Azərbaycan dilində müxtəlif oyunlar təklif edən bir əyləncə botuyam.

Mənimlə aşağıdakı oyunları oynaya bilərsiniz:
- Doğruluq yoxsa Cəsarət?
- Tapmaca
- Viktorina (Quiz)
- Mətn-əsaslı Macəra

Həmçinin, qruplardakı aktivliyi izləyən reytinq sistemim var. Əyləncəli vaxt keçirməyiniz diləyi ilə!
"""
RULES_TEXT = """📜 **Oyun Botunun Qaydaları** 📜

🎲 **Doğruluq yoxsa Cəsarət?**
- `/oyun`: Yeni oyun üçün qeydiyyat başladır.
- `/baslat`: (Admin) Oyunu başladır.
- `/novbeti`: (Admin) Sıranı dəyişir.
- `/dayandir`: (Admin) Oyunu bitirir.

💡 **Tapmaca Oyunu**
- `/tapmaca`: Təsadüfi tapmaca göndərir.

🧠 **Viktorina Oyunu**
- `/viktorina`: 3 can ilə viktorina sualı göndərir.

🗺️ **Macəra Oyunu**
- `/macera`: Hər kəs üçün fərdi macəra oyunu başladır.

📊 **Reytinq Sistemi**
- `/reyting [dövr]`: Mesaj statistikasını göstərir.
- `/menim_rutbem`: Şəxsi rütbənizi göstərir."""
STORY_DATA = {'start': {'text': "Siz qədim bir məbədin girişində dayanmısınız. Hava qaralır. İki yol var: soldakı mamırlı daşlarla örtülmüş cığır və sağdakı qaranlıq mağara girişi.",'choices': [{'text': "🌳 Sol cığırla get", 'goto': 'forest_path'}, {'text': "🦇 Mağaraya daxil ol", 'goto': 'cave_entrance'}]}, 'treasure_found': {'text': "Əfsanəvi qılıncı əldə etdiniz! Macəranız uğurla başa çatdı. Qələbə! 🏆\n\nYeni macəra üçün /macera yazın.",'choices': []}}
QUIZ_QUESTIONS = [{'question': 'Azərbaycanın paytaxtı haradır?', 'options': ['Gəncə', 'Sumqayıt', 'Bakı', 'Naxçıvan'], 'correct': 'Bakı'}]
RIDDLES = [{'riddle': 'Ağzı var, dili yox, danışdıqca cana gəlir. Bu nədir?', 'answers': ['kitab']}]
NORMAL_TRUTH_QUESTIONS = ["Uşaqlıqda ən böyük qorxun nə idi?"]
NORMAL_DARE_TASKS = ["Profil şəklini 1 saatlıq qrupdakı ən son göndərilən şəkil ilə dəyişdir."]

# --- ƏSAS FUNKSİYALAR ---
def get_rank_title(count: int) -> str:
    # ... (kod eyni qalır)
    pass
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
    user = update.message.from_user
    if context.args and len(context.args) > 0 and context.args[0] == 'macera':
        context.user_data['rpg_inventory'] = set()
        await update.message.reply_text("Sənin şəxsi macəran başlayır! ⚔️")
        await show_rpg_node(update, context, 'start'); return

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
    await update.message.reply_text("⛔ Bu oyun yalnız qruplarda oynanıla bilər. Zəhmət olmasa, məni bir qrupa əlavə edib orada yenidən cəhd edin.")

async def haqqinda_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(ABOUT_TEXT, parse_mode='Markdown')

async def qaydalar_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(RULES_TEXT, parse_mode='Markdown')

async def macera_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bot_username = (await context.bot.get_me()).username
    start_link = f"https://t.me/{bot_username}?start=macera"
    keyboard = [[InlineKeyboardButton("⚔️ Macəranı Şəxsidə Başlat", url=start_link)]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Hər kəs öz şəxsi macərasını yaşaya bilər!\n\nAşağıdakı düyməyə basaraq mənimlə şəxsi söhbətə başla və öz fərdi oyununu oyna:", reply_markup=reply_markup)

async def show_rpg_node(update: Update, context: ContextTypes.DEFAULT_TYPE, node_key: str):
    message = update.message if update.message else update.callback_query.message
    node = STORY_DATA.get(node_key)
    if not node: return
    inventory = context.user_data.get('rpg_inventory', set())
    if node.get('get_item'):
        inventory.add(node.get('get_item'))
        context.user_data['rpg_inventory'] = inventory
    text, choices = node['text'], node['choices']
    keyboard_buttons = []
    for choice in choices:
        if 'requires_item' in choice:
            if choice['requires_item'] in inventory:
                keyboard_buttons.append([InlineKeyboardButton(choice['text'], callback_data=f"rpg_{choice['goto']}")])
        else:
            keyboard_buttons.append([InlineKeyboardButton(choice['text'], callback_data=f"rpg_{choice['goto']}")])
    reply_markup = InlineKeyboardMarkup(keyboard_buttons) if keyboard_buttons else None
    if update.callback_query:
        await update.callback_query.edit_message_text(text=text, reply_markup=reply_markup)
    else:
        await message.reply_text(text, reply_markup=reply_markup)

# ... (game_command, start_game_command, next_turn_command, stop_game_command, join_command, leave_command, tapmaca_command, viktorina_command, rating_command, my_rank_command, handle_message olduğu kimi qalır)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query, user, data = update.callback_query, update.callback_query.from_user, update.callback_query.data
    await query.answer()

    if data.startswith("start_info_"):
        command_name = data.split('_')[-1]
        
        # 'Bütün Qaydalar' və 'Bot Haqqında' düymələrini idarə edirik
        if command_name == 'qaydalar':
            await query.message.reply_text(RULES_TEXT, parse_mode='Markdown')
        elif command_name == 'about':
            await query.message.reply_text(ABOUT_TEXT, parse_mode='Markdown')
        return

    if data.startswith("rpg_"):
        node_key = data.split('_', 1)[1]
        await show_rpg_node(update, context, node_key); return
        
    # ... (qalan bütün köhnə button handler məntiqi, quiz, skip_riddle, register_join, game_ olduğu kimi qalır)

def main() -> None:
    run_pre_flight_checks()
    init_db()
    
    application = Application.builder().token(TOKEN).build()
    
    group_filter = ~filters.ChatType.PRIVATE
    private_filter = filters.ChatType.PRIVATE
    
    # Bütün əmrlər
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("qaydalar", qaydalar_command))
    application.add_handler(CommandHandler("haqqinda", haqqinda_command))
    
    # Qrup oyunları üçün handler-lər
    application.add_handler(CommandHandler("oyun", game_command, filters=group_filter))
    application.add_handler(CommandHandler("tapmaca", tapmaca_command, filters=group_filter))
    application.add_handler(CommandHandler("viktorina", viktorina_command, filters=group_filter))
    application.add_handler(CommandHandler("macera", macera_command, filters=group_filter))
    #... (bütün digər qrup əmrləri)

    # Şəxsi söhbət üçün xəbərdarlıq
    game_warning_commands = ["oyun", "tapmaca", "viktorina", "reyting", "menim_rutbem", "baslat", "novbeti", "dayandir", "qosul", "cix"]
    application.add_handler(CommandHandler(game_warning_commands, private_game_warning, filters=private_filter))
    
    # Bütün mesajları və hadisələri idarə edənlər
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND) & group_filter, handle_message))
    application.add_handler(MessageHandler(filters.StatusUpdate.ALL & group_filter, welcome_new_members))
    application.add_handler(MessageHandler(filters.ChatType.PRIVATE & (~filters.COMMAND), start_command))
    application.add_handler(CallbackQueryHandler(button_handler))

    print("Bot işə düşdü...")
    application.run_polling()

if __name__ == '__main__':
    main()
