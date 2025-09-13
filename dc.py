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
        print("Verilənlər bazası cədvəlləri hazırdır.")
    except Exception as e:
        print(f"Baza yaradılarkən xəta: {e}")

# --- MƏZMUN SİYAHILARI ---
STORY_DATA = { 'start': {'text': "Siz qədim bir məbədin girişində dayanmısınız...", 'choices': [{'text': "🌳 Sol cığırla get", 'goto': 'forest_path'}, {'text': "🦇 Mağaraya daxil ol", 'goto': 'cave_entrance'}]}, 'forest_path': {'text': "Cığırla irəliləyərək üzərində qədim işarələr olan böyük bir daş qapıya çatırsınız...", 'choices': [{'text': "🔑 Qədim açarı istifadə et", 'goto': 'open_door', 'requires_item': 'qədim açar'}, {'text': " geri dön", 'goto': 'start'}]}, 'cave_entrance': {'text': "Qaranlıq mağaraya daxil olursunuz. Divardan asılmış köhnə bir açar gözünüzə dəyir...", 'get_item': 'qədim açar','choices': [{'text': "Açarla birlikdə geri dön", 'goto': 'get_key'}]}, 'get_key': {'text': "Artıq inventarınızda köhnə, paslı bir açar var...", 'choices': [{'text': "🌳 Meşədəki qapını yoxla", 'goto': 'forest_path'}, {'text': "🧭 Məbədin girişinə qayıt", 'goto': 'start'}]}, 'open_door': {'text': "Açarı istifadə edirsiniz. Qədim mexanizm işə düşür...", 'get_item': 'əfsanəvi qılınc','choices': [{'text': "⚔️ Qılıncı götür!", 'goto': 'treasure_found'}]}, 'treasure_found': {'text': "Əfsanəvi qılıncı əldə etdiniz! Macəranız uğurla başa çatdı. Qələbə! 🏆\n\nYeni macəra üçün /macera yazın.",'choices': []}, 'go_back': {'text': "Açarınız olmadığı üçün geri qayıtmaqdan başqa çarəniz yoxdur...",'choices': [{'text': "🦇 Mağaraya daxil ol", 'goto': 'cave_entrance'}, {'text': "🌳 Meşə cığırı ilə get", 'goto': 'forest_path'}]}}
QUIZ_QUESTIONS = [{'question': 'Azərbaycanın paytaxtı haradır?', 'options': ['Gəncə', 'Sumqayıt', 'Bakı', 'Naxçıvan'], 'correct': 'Bakı'}]
RIDDLES = [{'riddle': 'Ağzı var, dili yox, danışdıqca cana gəlir. Bu nədir?', 'answers': ['kitab']}]
NORMAL_TRUTH_QUESTIONS = ["Uşaqlıqda ən böyük qorxun nə idi?"]
NORMAL_DARE_TASKS = ["Profil şəklini 1 saatlıq qrupdakı ən son göndərilən şəkil ilə dəyişdir."]
RULES_TEXT = """📜 **Oyun Botunun Qaydaları** 📜

🤥 **İki Düz, Bir Yalan (YENİ)**
- `/yalan_tap`: Oyunu başladır. Bot sizə şəxsidə yazıb 3 iddia istəyir.
- İddiaları və yalanın nömrəsini şəxsidə bota göndərirsiniz.
- Bot iddiaları qrupda yayımlayır və 60 saniyəlik səsvermə başladır.

🎲 **Doğruluq yoxsa Cəsarət?**
- `/oyun`: Yeni oyun üçün qeydiyyat başladır.
- `/baslat` & `/novbeti` & `/dayandir`: (Admin) Oyunu idarə edir.

💡 **Tapmaca və 🧠 Viktorina**
- `/tapmaca`: Təsadüfi tapmaca göndərir.
- `/viktorina`: 3 can ilə viktorina sualı göndərir.

🗺️ **Macəra Oyunu**
- `/macera`: Fərdi macəra oyunu başladır.

📊 **Reytinq Sistemi**
- `/reyting [dövr]` & `/menim_rutbem`: Mesaj statistikası."""

# --- ƏSAS FUNKSİYALAR ---
def get_rank_title(count: int) -> str:
    if count <= 100: return "Yeni Üzv 👶"
    elif count <= 500: return "Daimi Sakin 👨‍💻"
    elif count <= 1000: return "Qrup Söhbətçili 🗣️"
    elif count <= 2500: return "Qrup Əfsanəsi 👑"
    else: return "Söhbət Tanrısı ⚡️"

async def welcome_new_members(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.new_chat_members: return
    new_members, chat_title = update.message.new_chat_members, update.message.chat.title
    for member in new_members:
        if member.id == context.bot.id: continue
        welcome_message = (f"Salam, [{member.first_name}](tg://user?id={member.id})! 👋\n"
                         f"**'{chat_title}'** qrupuna xoş gəlmisən!\n\n"
                         "Mən bu qrupun əyləncə və statistika botuyam. Əmrləri görmək üçün /start yaz.")
        await update.message.reply_text(welcome_message, parse_mode='Markdown')
async def is_user_admin(chat_id: int, user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if chat_id == user_id: return True
    try: return user_id in [admin.user.id for admin in await context.bot.get_chat_administrators(chat_id)]
    except Exception: return False
async def ask_next_player(chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    chat_data = context.chat_data
    if not chat_data.get('player_list'):
        await context.bot.send_message(chat_id, "Oyunçu qalmadı. Oyun dayandırılır."); context.chat_data.clear(); return
    chat_data['current_player_index'] = (chat_data.get('current_player_index', -1) + 1) % len(chat_data['player_list'])
    current_player = chat_data['player_list'][chat_data['current_player_index']]
    user_id, first_name = current_player['id'], current_player['name']
    keyboard = [[InlineKeyboardButton("Doğruluq ✅", callback_data=f"game_truth_{user_id}"), InlineKeyboardButton("Cəsarət 😈", callback_data=f"game_dare_{user_id}")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await context.bot.send_message(chat_id, text=f"Sıra sənə çatdı, [{first_name}](tg://user?id={user_id})! Seçimini et:", reply_markup=reply_markup, parse_mode='Markdown')

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    if context.args and len(context.args) > 0 and context.args[0].startswith('ttol_'):
        return await ttol_start_in_private(update, context)
    if context.args and len(context.args) > 0 and context.args[0] == 'macera':
        context.user_data.clear() # Bütün köhnə oyun məlumatlarını təmizləyir
        context.user_data['rpg_inventory'] = set()
        await update.message.reply_text("Sənin şəxsi macəran başlayır! ⚔️")
        await show_rpg_node(update, context, 'start'); return
    keyboard = [[InlineKeyboardButton("📜 Bütün Qaydalar", callback_data="start_info_qaydalar")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    start_text = "Salam! Mən Oyun Botuyam. 🤖\nBütün oyunların qaydalarına baxmaq üçün düyməyə bas və ya əmrləri birbaşa yaz!"
    await update.message.reply_text(start_text, reply_markup=reply_markup)
async def qaydalar_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(RULES_TEXT, parse_mode='Markdown')
async def game_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.chat_data.get('game_active') or context.chat_data.get('players'):
        await update.message.reply_text("Artıq aktiv bir oyun var. Yeni oyun üçün /dayandir yazın."); return
    keyboard = [[InlineKeyboardButton("Oyuna Qoşul 🙋‍♂️", callback_data="register_join")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Oyun üçün qeydiyyat başladı! Qoşulmaq üçün düyməyə basın.", reply_markup=reply_markup)
async def start_game_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id, user_id = update.message.chat_id, update.message.from_user.id
    if not await is_user_admin(chat_id, user_id, context):
        await update.message.reply_text("⛔ Bu əmri yalnız qrup adminləri istifadə edə bilər."); return
    players = context.chat_data.get('players', {})
    if len(players) < 2:
        await update.message.reply_text("Oyunun başlaması üçün ən az 2 nəfər qeydiyyatdan keçməlidir."); return
    context.chat_data['game_active'] = True; player_list = list(players.values()); random.shuffle(player_list)
    context.chat_data['player_list'] = player_list
    player_names = ", ".join([p['name'] for p in player_list])
    await update.message.reply_text(f"Oyun başladı! 🚀\n\nİştirakçılar: {player_names}\n\nİlk oyunçu üçün hazırlaşın...")
    await ask_next_player(chat_id, context)
async def next_turn_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id, user_id = update.message.chat_id, update.message.from_user.id
    if not context.chat_data.get('game_active', False):
        await update.message.reply_text("Hazırda aktiv oyun yoxdur."); return
    if not await is_user_admin(chat_id, user_id, context):
        await update.message.reply_text("⛔ Sıranı yalnız qrup adminləri dəyişə bilər."); return
    await update.message.reply_text("Sıra növbəti oyunçuya keçir...")
    await ask_next_player(chat_id, context)
async def stop_game_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id, user_id = update.message.chat_id, update.message.from_user.id
    if not await is_user_admin(chat_id, user_id, context):
        await update.message.reply_text("⛔ Bu əmri yalnız qrup adminləri istifadə edə bilər."); return
    context.chat_data.clear()
    await update.message.reply_text("Oyun admin tərəfindən dayandırıldı. Bütün məlumatlar sıfırlandı. Yeni oyun üçün /oyun yazın.")
async def join_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    if not context.chat_data.get('game_active', False):
        await update.message.reply_text("Hazırda aktiv oyun yoxdur. Yeni oyun üçün /oyun əmrini gözləyin."); return
    context.chat_data.setdefault('players', {})[user.id] = {'id': user.id, 'name': user.first_name}
    if 'player_list' in context.chat_data: context.chat_data['player_list'].append({'id': user.id, 'name': user.first_name})
    await update.message.reply_text(f"Xoş gəldin, {user.first_name}! Sən də oyuna qoşuldun.")
async def leave_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    players = context.chat_data.get('players', {})
    if user_id not in players:
        await update.message.reply_text("Siz onsuz da oyunda deyilsiniz."); return
    del players[user_id]
    if 'player_list' in context.chat_data: context.chat_data['player_list'] = [p for p in context.chat_data['player_list'] if p['id'] != user_id]
    await update.message.reply_text(f"{update.message.from_user.first_name} oyundan ayrıldı.")
    if len(players) < 2 and context.chat_data.get('game_active', False):
        await update.message.reply_text("Oyunçu sayı 2-dən az olduğu üçün oyun dayandırıldı."); context.chat_data.clear()
async def tapmaca_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.chat_data.get('riddle_active'):
        await update.message.reply_text("Artıq aktiv bir tapmaca var! Zəhmət olmasa, əvvəlcə onu tapın."); return
    last_riddle_text = context.chat_data.get('last_riddle', None)
    if len(RIDDLES) > 1 and last_riddle_text:
        possible_riddles = [r for r in RIDDLES if r['riddle'] != last_riddle_text]
        chosen_riddle = random.choice(possible_riddles)
    else: chosen_riddle = random.choice(RIDDLES)
    context.chat_data['last_riddle'] = chosen_riddle['riddle']
    context.chat_data['riddle_answer'] = [ans.lower() for ans in chosen_riddle['answers']]
    context.chat_data['riddle_active'] = True
    keyboard = [[InlineKeyboardButton("Cavabı Göstər 💡", callback_data="skip_riddle")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(f"Tapmaca gəldi! 🕵️‍♂️\n\n**{chosen_riddle['riddle']}**", parse_mode='Markdown', reply_markup=reply_markup)
async def viktorina_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    if context.chat_data.get('quiz_active'):
        await update.message.reply_text("Artıq aktiv bir viktorina var! Zəhmət olmasa, əvvəlcə onu cavablandırın."); return
    question_data = random.choice(QUIZ_QUESTIONS); question, correct_answer, options = question_data['question'], question_data['correct'], list(question_data['options'])
    random.shuffle(options); context.chat_data['correct_quiz_answer'] = correct_answer; context.chat_data['quiz_active'] = True; context.chat_data['quiz_lives'] = 3
    keyboard = [[InlineKeyboardButton(option, callback_data=f"quiz_{option}")] for option in options]
    reply_markup = InlineKeyboardMarkup(keyboard)
    lives_text = "❤️❤️❤️"; message = await update.message.reply_text(f"Viktorina başladı! 🧠\n\n**Sual:** {question}\n\nQalan cəhdlər: {lives_text}", parse_mode='Markdown', reply_markup=reply_markup)
    context.chat_data['quiz_message_id'] = message.message_id
async def macera_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if context.chat_data.get(f'rpg_active_{user_id}'):
        await update.message.reply_text("Sənin artıq aktiv bir macəran var. Əvvəlcə onu bitir."); return
    context.user_data.clear()
    context.user_data['rpg_inventory'] = set()
    await show_rpg_node(update, context, 'start')
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
async def yalan_tap_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user; chat_id = update.message.chat_id
    if context.application.chat_data.get(chat_id, {}).get('ttol_active'):
        await update.message.reply_text("Artıq qrupda aktiv 'İki Düz, Bir Yalan' oyunu var."); return
    try:
        bot_username = (await context.bot.get_me()).username
        start_link = f"https://t.me/{bot_username}?start=ttol_{chat_id}"
        keyboard = [[InlineKeyboardButton("Hazırsan? Mənə Şəxsidə Yaz!", url=start_link)]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(f"Salam, {user.first_name}! 'İki Düz, Bir Yalan' oyununa başlamaq üçün düyməyə bas.", reply_markup=reply_markup)
    except Exception as e:
        logger.error(f"TTOL oyununu başlatarkən xəta: {e}")
async def ttol_start_in_private(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        group_id = int(context.args[0].split('_')[1])
        context.user_data['ttol_group_id'] = group_id
    except (IndexError, ValueError):
        await update.message.reply_text("Xəta baş verdi. Oyunu qrupdan /yalan_tap yazaraq yenidən başladın."); return ConversationHandler.END
    await update.message.reply_text("Əla! İndi özün haqqında 1-ci iddianı yaz. Prosesi ləğv etmək üçün /cancel yaz."); return STATEMENT_1
async def receive_statement1(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['ttol_s1'] = update.message.text
    await update.message.reply_text("Gözəl! İndi 2-ci iddianı yaz."); return STATEMENT_2
async def receive_statement2(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['ttol_s2'] = update.message.text
    await update.message.reply_text("Super! Və nəhayət, 3-cü iddianı yaz."); return STATEMENT_3
async def receive_statement3(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['ttol_s3'] = update.message.text
    keyboard = [[InlineKeyboardButton("1-ci iddia yalandır", callback_data="ttol_lie_1")], [InlineKeyboardButton("2-ci iddia yalandır", callback_data="ttol_lie_2")], [InlineKeyboardButton("3-cü iddia yalandır", callback_data="ttol_lie_3")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Mükəmməl! İndi isə bunlardan hansının yalan olduğunu düyməyə basaraq seç.", reply_markup=reply_markup); return WHICH_IS_LIE
async def receive_which_is_lie(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query; await query.answer()
    lie_index = int(query.data.split('_')[-1])
    s1, s2, s3, group_id = context.user_data['ttol_s1'], context.user_data['ttol_s2'], context.user_data['ttol_s3'], context.user_data['ttol_group_id']
    statements = [s1, s2, s3]; random.shuffle(statements)
    lie_statement_text = context.user_data[f'ttol_s{lie_index}']
    new_lie_index = statements.index(lie_statement_text) + 1
    context.application.chat_data[group_id]['ttol_active'] = True
    context.application.chat_data[group_id]['ttol_author'] = query.from_user.first_name
    context.application.chat_data[group_id]['ttol_lie_index'] = new_lie_index
    context.application.chat_data[group_id]['ttol_votes'] = {}
    keyboard = [[InlineKeyboardButton(f"{i+1}-ci İddia", callback_data=f"ttol_vote_{i+1}") for i in range(3)]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text("Məlumatlar qəbul edildi! İndi oyunu qrupda yayımlayıram...")
    game_text = (f"Yeni oyun başladı! 🤔\n\n**{query.from_user.first_name}** özü haqqında 3 iddia göndərdi. Sizcə hansı yalandır?\n\n"
                 f"1. {statements[0]}\n2. {statements[1]}\n3. {statements[2]}\n\nYalan olanı tapmaq üçün 60 saniyəniz var!")
    message = await context.bot.send_message(chat_id=group_id, text=game_text, reply_markup=reply_markup)
    context.application.chat_data[group_id]['ttol_message_id'] = message.message_id
    context.job_queue.run_once(finish_ttol_game, 60, chat_id=group_id, name=str(group_id))
    for key in ['ttol_group_id', 'ttol_s1', 'ttol_s2', 'ttol_s3']: context.user_data.pop(key, None)
    return ConversationHandler.END
async def finish_ttol_game(context: ContextTypes.DEFAULT_TYPE):
    job = context.job; chat_id = job.chat_id
    chat_data = context.application.chat_data[chat_id]
    if not chat_data.get('ttol_active'): return
    author, lie_index, votes, message_id = chat_data['ttol_author'], chat_data['ttol_lie_index'], chat_data.get('ttol_votes', {}), chat_data['ttol_message_id']
    results_text = "\n\n**Nəticələr:**\n"; winners = []
    if not votes:
        results_text += "Heç kim səs vermədi."
    else:
        for user_id, vote_info in votes.items():
            if vote_info['vote'] == lie_index: winners.append(vote_info['user_name'])
    if winners:
        results_text += f"Düzgün tapanlar: {', '.join(winners)} 🥳"
    else: results_text += "Heç kim düzgün tapa bilmədi. 😔"
    try:
        original_message = await context.bot.edit_message_reply_markup(chat_id=chat_id, message_id=message_id, reply_markup=None)
        await original_message.reply_text(f"Vaxt bitdi! ⌛️\n\n**{author}** haqqında yalan olan iddia **{lie_index}-ci** idi!" + results_text, parse_mode='Markdown')
    except Exception as e:
        logger.error(f"TTOL nəticəsini göndərərkən xəta: {e}")
        await context.bot.send_message(chat_id=chat_id, text=f"Vaxt bitdi! ⌛️\n\n**{author}** haqqında yalan olan iddia **{lie_index}-ci** idi!" + results_text, parse_mode='Markdown')
    for key in ['ttol_active', 'ttol_author', 'ttol_lie_index', 'ttol_votes', 'ttol_message_id']:
        chat_data.pop(key, None)
async def ttol_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    for key in ['ttol_group_id', 'ttol_s1', 'ttol_s2', 'ttol_s3']: context.user_data.pop(key, None)
    await update.message.reply_text("Proses ləğv edildi.")
    return ConversationHandler.END
async def ttol_vote_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; user = query.from_user; chat_id = query.message.chat_id
    chat_data = context.application.chat_data.get(chat_id, {})
    if not chat_data.get('ttol_active'):
        await query.answer("Bu oyun artıq bitib.", show_alert=True); return
    if user.id in chat_data.get('ttol_votes', {}):
        await query.answer("Siz artıq səs vermisiniz.", show_alert=True); return
    vote = int(query.data.split('_')[-1])
    chat_data.setdefault('ttol_votes', {})[user.id] = {'user_name': user.first_name, 'vote': vote}
    await query.answer(f"Səsiniz qəbul edildi! {vote}-ci iddianı seçdiniz.")
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query, user, data = update.callback_query, update.callback_query.from_user, update.callback_query.data
    await query.answer()
    if data == "back_to_start_menu":
        await start_command_menu(update, context, is_edit=True); return
    if data.startswith("start_info_"):
        await start_command_menu_handler(query, context); return
    if data.startswith("rpg_"):
        node_key = data.split('_', 1)[1]
        await show_rpg_node(update, context, node_key); return
    if data.startswith("quiz_"):
        if not context.chat_data.get('quiz_active'):
            await query.answer("Bu viktorina artıq bitib.", show_alert=True); return
        chosen_answer = data.split('_', 1)[1]; correct_answer = context.chat_data['correct_quiz_answer']
        if chosen_answer == correct_answer:
            await query.answer("Düzdür!", show_alert=False)
            original_text = query.message.text.split('Qalan cəhdlər:')[0].strip()
            await context.bot.edit_message_text(chat_id=query.message.chat_id, message_id=context.chat_data['quiz_message_id'],
                                                text=f"{original_text}\n\n---\n🥳 Qalib: {user.first_name}!\n✅ Düzgün cavab: **{correct_answer}**", parse_mode='Markdown')
            del context.chat_data['quiz_active']; del context.chat_data['correct_quiz_answer']; del context.chat_data['quiz_message_id']; del context.chat_data['quiz_lives']
        else:
            context.chat_data['quiz_lives'] -= 1; lives_left = context.chat_data['quiz_lives']
            await query.answer(f"Səhv cavab! {lives_left} cəhdiniz qaldı.", show_alert=True)
            if lives_left == 0:
                original_text = query.message.text.split('Qalan cəhdlər:')[0].strip()
                await context.bot.edit_message_text(chat_id=query.message.chat_id, message_id=context.chat_data['quiz_message_id'],
                                                    text=f"{original_text}\n\n---\n😔 Məğlub oldunuz! Bütün cəhdlər bitdi.\n✅ Düzgün cavab: **{correct_answer}**", parse_mode='Markdown')
                del context.chat_data['quiz_active']; del context.chat_data['correct_quiz_answer']; del context.chat_data['quiz_message_id']; del context.chat_data['quiz_lives']
            else:
                lives_text = "❤️" * lives_left; original_text = query.message.text.split('Qalan cəhdlər:')[0].strip()
                await context.bot.edit_message_text(chat_id=query.message.chat_id, message_id=context.chat_data['quiz_message_id'],
                                                    text=f"{original_text}\n\nQalan cəhdlər: {lives_text}", reply_markup=query.message.reply_markup, parse_mode='Markdown')
        return
    if data == "skip_riddle":
        if not context.chat_data.get('riddle_active'):
            await query.answer("Bu tapmaca artıq bitib.", show_alert=True); return
        correct_answers = context.chat_data.get('riddle_answer', []); correct_answer_text = ", ".join(correct_answers).capitalize()
        await query.edit_message_text(text=f"{query.message.text}\n\n---\n😥 Heç kim tapa bilmədi!\n✅ **Düzgün cavab:** {correct_answer_text}\n\nYeni tapmaca üçün /tapmaca yazın.", parse_mode='Markdown')
        del context.chat_data['riddle_active']; del context.chat_data['riddle_answer']; return
    if data == "register_join":
        players = context.chat_data.setdefault('players', {})
        if user.id not in players:
            players[user.id] = {'id': user.id, 'name': user.first_name}
            await query.answer("Uğurla qeydiyyatdan keçdiniz!", show_alert=True)
            player_names = ", ".join([p['name'] for p in players.values()])
            keyboard = [[InlineKeyboardButton("Oyuna Qoşul 🙋‍♂️", callback_data="register_join")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(f"Oyun üçün qeydiyyat davam edir!\n\n**Qoşulanlar:** {player_names}\n\nAdminin oyunu başlatmasını gözləyin (/baslat).", reply_markup=reply_markup, parse_mode='Markdown')
        else: await query.answer("Siz onsuz da qeydiyyatdan keçmisiniz.", show_alert=True)
    elif data.startswith("game_"):
        parts = data.split('_'); action, target_user_id = parts[1], int(parts[2])
        if user.id != target_user_id: await query.answer("⛔ Bu sənin sıran deyil!", show_alert=True); return
        if action == 'truth': question = random.choice(NORMAL_TRUTH_QUESTIONS)
        else: task = random.choice(NORMAL_DARE_TASKS)
        response_text = f"📜 {user.first_name} üçün **Doğruluq**:\n\n> {question}" if action == 'truth' else f"🔥 {user.first_name} üçün **Cəsarət**:\n\n> {task}"
        command_suggestion = "\n\n*Cavab verildikdən sonra admin növbəti tura keçmək üçün /novbeti yazsın.*"
        await query.edit_message_text(text=response_text + command_suggestion, parse_mode='Markdown')
async def rating_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id, args = update.message.chat_id, context.args
    if not args: await update.message.reply_text("Zəhmət olmasa, dövrü təyin edin:\n`/reyting gunluk`...", parse_mode='Markdown'); return
    period = args[0].lower()
    if period == "gunluk": interval, title = "1 day", "Son 24 Saatın Ən Aktiv Üzvləri ☀️"
    elif period == "heftelik": interval, title = "7 days", "Son 7 Günün Ən Aktiv Üzvləri 🗓️"
    elif period == "ayliq": interval, title = "1 month", "Son 30 Günün Ən Aktiv Üzvləri 🌙"
    else: await update.message.reply_text("Yanlış dövr. Mümkün seçimlər: gunluk, heftelik, ayliq"); return
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require'); cur = conn.cursor()
        query = f"SELECT user_id, username, COUNT(*) as msg_count FROM message_counts WHERE chat_id = %s AND message_timestamp >= NOW() - INTERVAL '{interval}' GROUP BY user_id, username ORDER BY msg_count DESC LIMIT 10;"
        cur.execute(query, (chat_id,)); results = cur.fetchall(); cur.close(); conn.close()
        if not results: await update.message.reply_text("Bu dövr üçün heç bir məlumat tapılmadı. Statistikalar toplanır..."); return
        leaderboard = f"📊 **{title}**\n\n"
        for i, (user_id, username, msg_count) in enumerate(results):
            medal = "🥇" if i == 0 else "🥈" if i == 1 else "🥉" if i == 2 else ""
            rank_title = get_rank_title(msg_count)
            leaderboard += f"{i+1}. {medal} [{username}](tg://user?id={user_id}) - `{msg_count}` msj ({rank_title})\n"
        await update.message.reply_text(leaderboard, parse_mode='Markdown', disable_web_page_preview=True)
    except Exception as e:
        logger.error(f"Reytinq alınarkən xəta: {e}"); await update.message.reply_text("Reytinq cədvəlini hazırlayarkən bir xəta baş verdi.")
async def my_rank_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id, user_name, chat_id = update.message.from_user.id, update.message.from_user.first_name, update.message.chat_id
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require'); cur = conn.cursor(); query = "SELECT COUNT(*) FROM message_counts WHERE user_id = %s AND chat_id = %s;"
        cur.execute(query, (user_id, chat_id)); result = cur.fetchone(); cur.close(); conn.close()
        total_count = result[0] if result else 0
        rank_title = get_rank_title(total_count)
        await update.message.reply_text(f"Salam, {user_name}!\n\nBu qrupdakı ümumi mesaj sayınız: **{total_count}**\nHazırkı rütbəniz: **{rank_title}**", parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Şəxsi rütbə alınarkən xəta: {e}"); await update.message.reply_text("Rütbənizi hesablayarkən bir xəta baş verdi.")
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.from_user or not update.message.chat.type in [ChatType.GROUP, ChatType.SUPERGROUP]: return
    user, chat_id, text = update.message.from_user, update.message.chat_id, update.message.text
    if context.chat_data.get('riddle_active'):
        correct_answers = context.chat_data.get('riddle_answer', [])
        if text and text.strip().lower() in correct_answers:
            await update.message.reply_text(f"Əhsən, [{user.first_name}](tg://user?id={user.id})! 🥳 Düzgün cavab tapıldı! ✅", parse_mode='Markdown', reply_to_message_id=update.message.message_id)
            if 'riddle_active' in context.chat_data: del context.chat_data['riddle_active']
            if 'riddle_answer' in context.chat_data: del context.chat_data['riddle_answer']
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require'); cur = conn.cursor()
        cur.execute("INSERT INTO message_counts (chat_id, user_id, username, message_timestamp) VALUES (%s, %s, %s, %s)",
                    (chat_id, user.id, user.first_name, datetime.datetime.now(datetime.timezone.utc)))
        conn.commit(); cur.close(); conn.close()
    except Exception as e: logger.error(f"Mesajı bazaya yazarkən xəta: {e}")

def main() -> None:
    run_pre_flight_checks()
    init_db()
    application = Application.builder().token(TOKEN).build()
    group_filter = ~filters.ChatType.PRIVATE
    
    ttol_conv_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex('^/start ttol_'), ttol_start_in_private)],
        states={
            STATEMENT_1: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_statement1)],
            STATEMENT_2: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_statement2)],
            STATEMENT_3: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_statement3)],
            WHICH_IS_LIE: [CallbackQueryHandler(receive_which_is_lie, pattern='^ttol_lie_')]
        },
        fallbacks=[CommandHandler("cancel", ttol_cancel)],
        conversation_timeout=300
    )
    application.add_handler(ttol_conv_handler)
    
    # Əmrlər
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("qaydalar", qaydalar_command))
    application.add_handler(CommandHandler("oyun", game_command, filters=group_filter))
    application.add_handler(CommandHandler("baslat", start_game_command, filters=group_filter))
    application.add_handler(CommandHandler("novbeti", next_turn_command, filters=group_filter))
    application.add_handler(CommandHandler("dayandir", stop_game_command, filters=group_filter))
    application.add_handler(CommandHandler("qosul", join_command, filters=group_filter))
    application.add_handler(CommandHandler("cix", leave_command, filters=group_filter))
    application.add_handler(CommandHandler("reyting", rating_command, filters=group_filter))
    application.add_handler(CommandHandler("menim_rutbem", my_rank_command, filters=group_filter))
    application.add_handler(CommandHandler("tapmaca", tapmaca_command, filters=group_filter))
    application.add_handler(CommandHandler("viktorina", viktorina_command, filters=group_filter))
    application.add_handler(CommandHandler("macera", macera_command, filters=group_filter))
    application.add_handler(CommandHandler("yalan_tap", yalan_tap_command, filters=group_filter))
    
    # Handler-lər
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND) & group_filter, handle_message))
    application.add_handler(MessageHandler(filters.StatusUpdate.ALL & group_filter, welcome_new_members))
    application.add_handler(MessageHandler(filters.ChatType.PRIVATE & (~filters.COMMAND), start_command))
    application.add_handler(CallbackQueryHandler(ttol_vote_callback, pattern='^ttol_vote_'))
    application.add_handler(CallbackQueryHandler(button_handler))
    
    print("Bot işə düşdü...")
    application.run_polling()

if __name__ == '__main__':
    main()
