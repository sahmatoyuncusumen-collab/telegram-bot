import logging
import random
import os
import psycopg2
import datetime
import sys
import asyncio
import json
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters
from telegram.constants import ChatType
from collections import deque

# Logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# --- BAZA VƏ ƏSAS DƏYİŞƏNLƏR ---
DATABASE_URL = os.environ.get("DATABASE_URL")
TOKEN = os.environ.get("TELEGRAM_TOKEN")

# --- TƏHLÜKƏSİZLİK YOXLAMASI ---
def run_pre_flight_checks():
    if not DATABASE_URL or not TOKEN:
        logger.critical("--- XƏTA ---")
        logger.critical("DATABASE_URL və ya TELEGRAM_TOKEN tapılmadı. Proqram dayandırılır.")
        sys.exit(1)
    logger.info("Bütün konfiqurasiya dəyişənləri mövcuddur. Bot başladılır...")

# --- BAZA FUNKSİYASI ---
def init_db():
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cur = conn.cursor()
        cur.execute("CREATE TABLE IF NOT EXISTS message_counts (id SERIAL PRIMARY KEY, chat_id BIGINT NOT NULL, user_id BIGINT NOT NULL, username TEXT NOT NULL, message_timestamp TIMESTAMPTZ NOT NULL );")
        conn.commit()
        cur.close()
        conn.close()
        logger.info("Verilənlər bazası cədvəli hazırdır.")
    except Exception as e:
        logger.error(f"Baza yaradılarkən xəta: {e}")

# --- SUALLARI YÜKLƏMƏ FUNKSİYASI ---
def load_questions_from_json(file_path: str):
    """JSON faylından sualları yükləyir."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            questions = json.load(f)
        logger.info(f"{len(questions)} sual {file_path} faylından uğurla yükləndi.")
        return questions
    except FileNotFoundError:
        logger.error(f"XƏTA: {file_path} faylı tapılmadı. Viktorina oyunu işləməyəcək.")
        return []
    except json.JSONDecodeError:
        logger.error(f"XƏTA: {file_path} faylında JSON formatı səhvdir. Viktorina oyunu işləməyəcək.")
        return []

# --- MƏZMUN SİYAHILARI ---
ABOUT_TEXT = "🤖 **Bot Haqqında Məlumat** 🤖\n\nMən Azərbaycan dilində müxtəlif oyunlar təklif edən bir əyləncə botuyam.\n\nMənimlə aşağıdakı oyunları oynaya bilərsiniz:\n- Doğruluq yoxsa Cəsarət?\n- Tapmaca\n- Viktorina (Quiz)\n- Mətn-əsaslı Macəra\n\nHəmçinin, qruplardakı aktivliyi izləyən reytinq sistemim var.\n\nƏyləncəli vaxt keçirməyiniz diləyi ilə!"
RULES_TEXT = """📜 **Oyun Botunun Qaydaları** 📜

🎲 **Doğruluq yoxsa Cəsarət?**
- `/oyun`: Yeni oyun üçün qeydiyyat başladır.
- `/baslat`: (Admin) Oyunu başladır.
- `/novbeti`: (Admin) Sıranı dəyişir.
- `/dayandir`: (Admin) Oyunu bitirir.

💡 **Tapmaca Oyunu**
- `/tapmaca`: Təsadüfi tapmaca göndərir.

🧠 **Viktorina Oyunu**
- `/viktorina`: Yeni bir viktorina sualı göndərir.

🗺️ **Macəra Oyunu**
- `/macera`: Hər kəsin fərdi oynaması üçün şəxsi söhbətə dəvət göndərir.

📊 **Reytinq Sistemi**
- `/reyting [dövr]`: Mesaj statistikasını göstərir.
- `/menim_rutbem`: Şəxsi rütbənizi göstərir."""
STORY_DATA = {'start_temple': {'text': "Siz qədim və unudulmuş bir məbədin girişində dayanmısınız. Hava qaralır. Məbədin dərinliklərində 'Dağın Ürəyi' adlı bir almazın olduğu deyilir.",'choices': [{'text': "📚 İçəridəki kitabxanaya keç", 'goto': 'temple_library'}, {'text': "🗝️ Bağlı qapını yoxla", 'goto': 'temple_locked_door'}]}, 'temple_library': {'text': "Tozlu kitabxanaya daxil olursunuz. Rəflərdən birində köhnə bir kitab diqqətinizi çəkir. Kitabı götürürsünüz.",'get_item': 'köhnə kitab','choices': [{'text': "Kitabı oxu", 'goto': 'read_book'}, {'text': "Qapıya tərəf qayıt", 'goto': 'temple_locked_door'}]}, 'read_book': {'text': "Kitabı vərəqləyirsiniz. İçində yazılıb: 'Gözətçi yalnız doğru sözləri deyənə yol verər.' Bir səhifədə 'İşıq' sözü parıldayır.",'choices': [{'text': "Qapıya get", 'goto': 'temple_locked_door'}]}, 'temple_locked_door': {'text': "Böyük bir daş qapının qarşısındasınız. Qapının üzərində bir yazı var: 'Doğru sözü pıçılda'.",'choices': [{'text': "Parolu de ('İşıq')", 'goto': 'guardian_chamber', 'requires_item': 'köhnə kitab'}, {'text': "Qapını güclə açmağa çalış", 'goto': 'fail_door'}]}, 'fail_door': {'text': "Qapını itələməyə çalışsanız da, yerindən tərpənmir. Məbəd silkələnir və tavan çökür. Məğlub oldunuz. 😔\n\nYeni macəra üçün /macera yazın.",'choices': []}, 'guardian_chamber': {'text': "Qapı açılır. İçəridə 'Dağın Ürəyi' almazını qoruyan bir Gözətçi dayanır. O, sizə bir tapmaca verir: 'Məni alarsan, amma görməzsən. Mən nəyəm?'",'choices': [{'text': "Cavab: 'Nəfəs'", 'goto': 'win_temple'}, {'text': "Cavab: 'Xəyal'", 'goto': 'fail_guardian'}]}, 'fail_guardian': {'text': "Gözətçi 'Səhv cavab!' deyərək sizi məbəddən çölə atır. Məğlub oldunuz. 😔\n\nYeni macəra üçün /macera yazın.",'choices': []}, 'win_temple': {'text': "Gözətçi gülümsəyir: 'Doğrudur'. O, kənara çəkilir və siz 'Dağın Ürəyi' almazını götürürsünüz. Qələbə! 🏆\n\nYeni macəra üçün /macera yazın.",'choices': []}, 'start_shipwreck': {'text': "Fırtınalı bir gecədən sonra naməlum bir adanın sahilində oyanırsınız. Yanınızda qəzaya uğramış gəminizin qalıqları var.",'choices': [{'text': "🏝️ Sahili araşdır", 'goto': 'explore_beach'}, {'text': "🌳 Cəngəlliyə daxil ol", 'goto': 'enter_jungle'}]}, 'explore_beach': {'text': "Sahili araşdırarkən qumun içində köhnə bir butulka tapırsınız. İçində yarısı cırılmış bir xəritə var. Həmçinin gəminin qalıqlarından möhkəm bir taxta parçası götürürsünüz.",'get_item': 'xəritə parçası 1', 'get_item_2': 'möhkəm taxta','choices': [{'text': "Cəngəlliyə daxil ol", 'goto': 'enter_jungle'}]}, 'enter_jungle': {'text': "Sıx cəngəlliyə daxil olursunuz. Bir az irəlilədikdən sonra qarşınıza timsahlarla dolu bir çay çıxır.",'choices': [{'text': "🛶 Sal düzəlt", 'goto': 'build_raft', 'requires_item': 'möhkəm taxta'}, {'text': "🏊‍♂️ Üzərək keçməyə çalış", 'goto': 'swim_fail'}, {'text': "Geri qayıt", 'goto': 'start_shipwreck'}]}, 'swim_fail': {'text': "Çayı üzərək keçməyə çalışırsınız, lakin timsahlar sizi tutur. Məğlub oldunuz. 😔\n\nYeni macəra üçün /macera yazın.",'choices': []}, 'build_raft': {'text': "Möhkəm taxta parçasından və sarmaşıqlardan istifadə edərək kiçik bir sal düzəldirsiniz və çayı təhlükəsiz şəkildə keçirsiniz. O biri sahildə köhnə bir daxma tapırsınız.",'choices': [{'text': "Daxmanı araşdır", 'goto': 'explore_hut'}]}, 'explore_hut': {'text': "Köhnə daxmanın içində bir sandıq tapırsınız. Sandığın içindən xəritənin ikinci yarısını tapırsınız!",'get_item': 'xəritə parçası 2','choices': [{'text': "Xəritəni birləşdir", 'goto': 'map_complete'}]}, 'map_complete': {'text': "Xəritənin iki parçasını birləşdirirsiniz. Xəritə adadakı gizli bir pirat xəzinəsinin yerini göstərir. Xəzinəni tapırsınız. Qələbə! 🏆\n\nYeni macəra üçün /macera yazın.",'choices': []}}

# Viktorina sualları JSON faylından yüklənir
QUIZ_QUESTIONS = load_questions_from_json('questions.json')

RIDDLES = [{'riddle': 'Ağzı var, dili yox, danışdıqca cana gəlir. Bu nədir?', 'answers': ['kitab']},{'riddle': 'Gecə yaranar, səhər itər. Bu nədir?', 'answers': ['yuxu', 'röya']},{'riddle': 'Bir qalaçam var, içi dolu qızılca. Bu nədir?', 'answers': ['nar']},{'riddle': 'Nə qədər çox olsa, o qədər az görərsən. Bu nədir?', 'answers': ['qaranlıq']},{'riddle': 'Mənim şəhərlərim var, amma evim yoxdur. Meşələrim var, amma ağacım yoxdur. Sularım var, amma balığım yoxdur. Mən nəyəm?', 'answers': ['xəritə']},{'riddle': 'Hər zaman gəlir, amma heç vaxt gəlib çatmır. Bu nədir?', 'answers': ['sabah']},{'riddle': 'Hər kəsin sahib olduğu, amma heç kimin itirə bilmədiyi şey nədir?', 'answers': ['kölgə']}]
NORMAL_TRUTH_QUESTIONS = ["Uşaqlıqda ən böyük qorxun nə idi?","Həyatında ən çox peşman olduğun şey?","Heç kimin bilmədiyi bir bacarığın varmı?","Bu qrupda ən çox güvəndiyin insan kimdir?","Bir günlük görünməz olsaydın nə edərdin?","Ən çox sevdiyin film hansıdır və niyə?","Ən utancverici ləqəbin nə olub?","Valideynlərinə dediyin ən böyük yalan nə olub?","Heç hovuzun içinə kiçik tualetini etmisən?","Telefonundakı ən son şəkil nədir? (Düzünü de!)","Əgər heyvan olsaydın, hansı heyvan olardın və niyə?","İndiyə qədər aldığın ən pis hədiyyə nə olub?","Heç kimə demədiyin bir sirrin nədir?","Qrupdakı birinin yerində olmaq istəsəydin, bu kim olardı?","Ən qəribə yemək vərdişin nədir?","Heç sosial media profilini gizlicə izlədiyin (stalk etdiyin) biri olub?","Səni nə ağlada bilər?","Bir günə 1 milyon dollar xərcləməli olsaydın, nəyə xərcləyərdin?"]
NORMAL_DARE_TASKS = ["Profil şəklini 1 saatlıq qrupdakı ən son göndərilən şəkil ilə dəyişdir.","Qrupdakı birinə səsli mesajla mahnı oxu.","Əlifbanı sondan əvvələ doğru sürətli şəkildə say.","Otağındakı ən qəribə əşyanın şəklini çəkib qrupa göndər.","Telefonunun klaviaturasını 10 dəqiqəlik tərs düz (sağdan sola) istifadə et.","Qrupdakı birinə icazə ver, sənin üçün İnstagram-da bir status paylaşsın.","Ən yaxın pəncərədən çölə \"Mən robotam!\" deyə qışqır.","Qrupa telefonunun ekran şəklini (screenshot) göndər.","Bir qaşıq qəhvə və ya duz ye.","Növbəti 3 dəqiqə ərzində ancaq şeir dili ilə danış.","Ən çox zəhlən gedən mahnını qrupa göndər.","Gözlərin bağlı halda öz portretini çəkməyə çalış və qrupa at.","Qrupdan birinə zəng et və ona qəribə bir lətifə danış.","İki fərqli içkini (məsələn, kola və süd) qarışdırıb bir qurtum iç.","Hər kəsin görə biləcəyi bir yerdə 30 saniyə robot kimi rəqs et.","Ən son aldığın mesaja \"OK, ancaq əvvəlcə kartofları soy\" deyə cavab yaz."]

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
    if context.args and len(context.args) > 0 and context.args[0] == 'macera':
        context.user_data.clear()
        context.user_data['rpg_inventory'] = set()
        await update.message.reply_text("Sənin şəxsi macəran başlayır! ⚔️")
        await show_rpg_node(update, context, 'start_temple'); return # Düzəliş: Konkret başlanğıc
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
    if 'get_item' in node: inventory.add(node['get_item'])
    if 'get_item_2' in node: inventory.add(node['get_item_2'])
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
    
    if not QUIZ_QUESTIONS:
        await update.message.reply_text("Viktorina üçün heç bir sual tapılmadı. Zəhmət olmasa, adminlə əlaqə saxlayın."); return

    recently_asked = context.chat_data.get('recently_asked_quiz', deque(maxlen=10))
    possible_questions = [q for q in QUIZ_QUESTIONS if q['question'] not in recently_asked]
    if not possible_questions:
        possible_questions = QUIZ_QUESTIONS
        recently_asked.clear()

    question_data = random.choice(possible_questions)
    recently_asked.append(question_data['question'])
    context.chat_data['recently_asked_quiz'] = recently_asked
    
    question, correct_answer, options = question_data['question'], question_data['correct'], list(question_data['options'])
    random.shuffle(options); context.chat_data['correct_quiz_answer'] = correct_answer; context.chat_data['quiz_active'] = True; context.chat_data['quiz_lives'] = 3
    keyboard = [[InlineKeyboardButton(option, callback_data=f"quiz_{option}")] for option in options]
    reply_markup = InlineKeyboardMarkup(keyboard)
    lives_text = "❤️❤️❤️"; message = await update.message.reply_text(f"Viktorina başladı! 🧠\n\n**Sual:** {question}\n\nQalan cəhdlər: {lives_text}", parse_mode='Markdown', reply_markup=reply_markup)
    context.chat_data['quiz_message_id'] = message.message_id
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query, user, data = update.callback_query, update.callback_query.from_user, update.callback_query.data
    await query.answer()
    
    if data.startswith("start_info_"):
        command_name = data.split('_')[-1]
        if command_name == 'qaydalar':
            await query.message.reply_text(RULES_TEXT, parse_mode='Markdown')
        elif command_name == 'about':
            await query.message.reply_text(ABOUT_TEXT, parse_mode='Markdown')
        return
        
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
    if not args: await update.message.reply_text("Zəhmət olmasa, dövrü təyin edin:\n`/reyting gunluk`\n`/reyting heftelik`\n`/reyting ayliq`", parse_mode='Markdown'); return
    period = args[0].lower()
    if period == "gunluk": interval, title = "1 day", "Son 24 Saatın Ən Aktiv Üzvləri ☀️"
    elif period == "heftelik": interval, title = "7 days", "Son 7 Günün Ən Aktiv Üzvləri 🗓️"
    elif period == "ayliq": interval, title = "1 month", "Son 30 Günün Ən Aktiv Üzvləri 🌙"
    else: await update.message.reply_text("Yanlış dövr. Mümkün seçimlər: `gunluk`, `heftelik`, `ayliq`", parse_mode='Markdown'); return
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require'); cur = conn.cursor()
        query = f"SELECT user_id, username, COUNT(*) as msg_count FROM message_counts WHERE chat_id = %s AND message_timestamp >= NOW() - INTERVAL '{interval}' GROUP BY user_id, username ORDER BY msg_count DESC LIMIT 10;"
        cur.execute(query, (chat_id,)); results = cur.fetchall(); cur.close(); conn.close()
        if not results: await update.message.reply_text("Bu dövr üçün heç bir məlumat tapılmadı. Statistikalar toplanır..."); return
        leaderboard = f"📊 **{title}**\n\n"
        for i, (user_id, username, msg_count) in enumerate(results):
            medal = "🥇" if i == 0 else "🥈" if i == 1 else "🥉" if i == 2 else f"**{i+1}.**"
            rank_title = get_rank_title(msg_count)
            leaderboard += f"{medal} [{username}](tg://user?id={user_id}) - `{msg_count}` msj ({rank_title})\n"
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
    private_filter = filters.ChatType.PRIVATE
    
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("qaydalar", qaydalar_command))
    application.add_handler(CommandHandler("haqqinda", haqqinda_command))
    
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
    
    game_warning_commands = ["oyun", "tapmaca", "viktorina", "reyting", "menim_rutbem", "baslat", "novbeti", "dayandir", "qosul", "cix"]
    application.add_handler(CommandHandler(game_warning_commands, private_game_warning, filters=private_filter))
    
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND) & group_filter, handle_message))
    application.add_handler(MessageHandler(filters.StatusUpdate.ALL & group_filter, welcome_new_members))
    application.add_handler(CallbackQueryHandler(button_handler))
    
    logger.info("Bot işə düşdü...")
    application.run_polling()

if __name__ == '__main__':
    main()
