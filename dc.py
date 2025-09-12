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
STORY_DATA = {
    'start': {
        'text': "Siz qədim bir məbədin girişində dayanmısınız. Hava qaralır. İki yol var: soldakı mamırlı daşlarla örtülmüş cığır və sağdakı qaranlıq mağara girişi.",
        'choices': [{'text': "🌳 Sol cığırla get", 'goto': 'forest_path'}, {'text': "🦇 Mağaraya daxil ol", 'goto': 'cave_entrance'}]
    },
    'forest_path': {
        'text': "Cığırla irəliləyərək üzərində qədim işarələr olan böyük bir daş qapıya çatırsınız. Qapı bağlıdır və ortasında böyük bir açar yeri var.",
        'choices': [{'text': "🔑 Qədim açarı istifadə et", 'goto': 'open_door', 'requires_item': 'qədim açar'}, {'text': " geri dön", 'goto': 'go_back'}]
    },
    'cave_entrance': {
        'text': "Qaranlıq mağaraya daxil olursunuz. Divardan asılmış köhnə bir açar gözünüzə dəyir. Onu götürürsünüz.",
        'get_item': 'qədim açar',
        'choices': [{'text': "Açarla birlikdə geri dön", 'goto': 'get_key'}]
    },
    'get_key': {
        'text': "Artıq inventarınızda köhnə, paslı bir açar var. Bu, bəzi qapıları aça bilər. İndi nə edirsiniz?",
        'choices': [{'text': "🌳 Meşədəki qapını yoxla", 'goto': 'forest_path'}, {'text': "🧭 Məbədin girişinə qayıt", 'goto': 'start'}]
    },
    'open_door': {
        'text': "Açarı istifadə edirsiniz. Qədim mexanizm işə düşür və daş qapı yavaşca açılır. İçəridə parlayan bir qılıncın olduğu xəzinə otağı görünür! Qılıncı götürürsünüz.",
        'get_item': 'əfsanəvi qılınc',
        'choices': [{'text': "⚔️ Qılıncı götür!", 'goto': 'treasure_found'}]
    },
    'treasure_found': {
        'text': "Əfsanəvi qılıncı əldə etdiniz! Macəranız uğurla başa çatdı. Qələbə! 🏆\n\nYeni macəra üçün /macera yazın.",
        'choices': []
    },
    'go_back': {
        'text': "Açarınız olmadığı üçün geri qayıtmaqdan başqa çarəniz yoxdur. Məbədin girişinə qayıtdınız.",
        'choices': [{'text': "🦇 Mağaraya daxil ol", 'goto': 'cave_entrance'}]
    }
}
QUIZ_QUESTIONS = [{'question': 'Azərbaycanın paytaxtı haradır?', 'options': ['Gəncə', 'Sumqayıt', 'Bakı', 'Naxçıvan'], 'correct': 'Bakı'},{'question': 'Hansı planet "Qırmızı Planet" kimi tanınır?', 'options': ['Venera', 'Mars', 'Yupiter', 'Saturn'], 'correct': 'Mars'},{'question': 'Dünyanın ən hündür dağı hansıdır?', 'options': ['K2', 'Everest', 'Makalu', 'Lhotse'], 'correct': 'Everest'},{'question': 'Əsərlərini Nizami Gəncəvi imzası ilə yazan şairin əsl adı nədir?', 'options': ['İlyas Yusif oğlu', 'Məhəmməd Füzuli', 'İmadəddin Nəsimi', 'Əliağa Vahid'], 'correct': 'İlyas Yusif oğlu'},{'question': 'Bir il ərzində neçə ayda 31 gün var?', 'options': ['6', '7', '8', '5'], 'correct': '7'},{'question': 'Leonardo da Vinçinin şah əsəri olan "Mona Liza" tablosu hazırda hansı muzeydə sərgilənir?', 'options': ['Britaniya Muzeyi', 'Vatikan Muzeyi', 'Ermitaj', 'Luvr Muzeyi'], 'correct': 'Luvr Muzeyi'}, {'question': 'İnsan bədənində ən böyük orqan hansıdır?', 'options': ['Qaraciyər', 'Dəri', 'Ağciyər', 'Beyin'], 'correct': 'Dəri'}, {'question': 'Dünyanın ən böyük okeanı hansıdır?', 'options': ['Atlantik okeanı', 'Hind okeanı', 'Sakit okean', 'Şimal Buzlu okeanı'], 'correct': 'Sakit okean'}, {'question': 'İkinci Dünya Müharibəsi hansı ildə başlayıb?', 'options': ['1941', '1945', '1939', '1914'], 'correct': '1939'}, {'question': 'Məşhur "Bohemian Rhapsody" mahnısı hansı rok qrupuna aiddir?', 'options': ['The Beatles', 'Led Zeppelin', 'Queen', 'Pink Floyd'], 'correct': 'Queen'}, {'question': 'Novruz bayramının əsas atributlarından olan səməni nəyin rəmzidir?', 'options': ['Odun', 'Suyun', 'Torpağın oyanışı', 'Küləyin'], 'correct': 'Torpağın oyanışı'}, {'question': 'Hansı kimyəvi element qızılın simvoludur?', 'options': ['Ag', 'Au', 'Fe', 'Cu'], 'correct': 'Au'}, {'question': 'İlk mobil telefon zəngi hansı ildə edilib?', 'options': ['1985', '1991', '1973', '1969'], 'correct': '1973'}]
RIDDLES = [{'riddle': 'Ağzı var, dili yox, danışdıqca cana gəlir. Bu nədir?', 'answers': ['kitab']},{'riddle': 'Gecə yaranar, səhər itər. Bu nədir?', 'answers': ['yuxu', 'röya']},{'riddle': 'Bir qalaçam var, içi dolu qızılca. Bu nədir?', 'answers': ['nar']},{'riddle': 'Nə qədər çox olsa, o qədər az görərsən. Bu nədir?', 'answers': ['qaranlıq']},{'riddle': 'Mənim şəhərlərim var, amma evim yoxdur. Meşələrim var, amma ağacım yoxdur. Sularım var, amma balığım yoxdur. Mən nəyəm?', 'answers': ['xəritə']},{'riddle': 'Hər zaman gəlir, amma heç vaxt gəlib çatmır. Bu nədir?', 'answers': ['sabah']},{'riddle': 'Hər kəsin sahib olduğu, amma heç kimin itirə bilmədiyi şey nədir?', 'answers': ['kölgə']}]
NORMAL_TRUTH_QUESTIONS = ["Uşaqlıqda ən böyük qorxun nə idi?","Həyatında ən çox peşman olduğun şey?","Heç kimin bilmədiyi bir bacarığın varmı?","Bu qrupda ən çox güvəndiyin insan kimdir?","Bir günlük görünməz olsaydın nə edərdin?","Ən çox sevdiyin film hansıdır və niyə?","Ən utancverici ləqəbin nə olub?","Valideynlərinə dediyin ən böyük yalan nə olub?","Heç hovuzun içinə kiçik tualetini etmisən?","Telefonundakı ən son şəkil nədir? (Düzünü de!)","Əgər heyvan olsaydın, hansı heyvan olardın və niyə?","İndiyə qədər aldığın ən pis hədiyyə nə olub?","Heç kimə demədiyin bir sirrin nədir?","Qrupdakı birinin yerində olmaq istəsəydin, bu kim olardı?","Ən qəribə yemək vərdişin nədir?","Heç sosial media profilini gizlicə izlədiyin (stalk etdiyin) biri olub?","Səni nə ağlada bilər?","Bir günə 1 milyon dollar xərcləməli olsaydın, nəyə xərcləyərdin?"]
NORMAL_DARE_TASKS = ["Profil şəklini 1 saatlıq qrupdakı ən son göndərilən şəkil ilə dəyişdir.","Qrupdakı birinə səsli mesajla mahnı oxu.","Əlifbanı sondan əvvələ doğru sürətli şəkildə say.","Otağındakı ən qəribə əşyanın şəklini çəkib qrupa göndər.","Telefonunun klaviaturasını 10 dəqiqəlik tərs düz (sağdan sola) istifadə et.","Qrupdakı birinə icazə ver, sənin üçün İnstagram-da bir status paylaşsın.","Ən yaxın pəncərədən çölə \"Mən robotam!\" deyə qışqır.","Qrupa telefonunun ekran şəklini (screenshot) göndər.","Bir qaşıq qəhvə və ya duz ye.","Növbəti 3 dəqiqə ərzində ancaq şeir dili ilə danış.","Ən çox zəhlən gedən mahnını qrupa göndər.","Gözlərin bağlı halda öz portretini çəkməyə çalış və qrupa at.","Qrupdan birinə zəng et və ona qəribə bir lətifə danış.","İki fərqli içkini (məsələn, kola və süd) qarışdırıb bir qurtum iç.","Hər kəsin görə biləcəyi bir yerdə 30 saniyə robot kimi rəqs et.","Ən son aldığın mesaja \"OK, ancaq əvvəlcə kartofları soy\" deyə cavab yaz."]
RULES_TEXT = "📜 **Oyun Botunun Qaydaları** 📜\n\n🎲 **Doğruluq yoxsa Cəsarət?**\n- `/oyun`: Yeni oyun üçün qeydiyyat başladır...\n\n💡 **Tapmaca Oyunu**\n- `/tapmaca`: Təsadüfi bir tapmaca göndərir...\n\n🧠 **Viktorina Oyunu**\n- `/viktorina`: 3 can ilə yeni bir viktorina sualı göndərir...\n\n🗺️ **Macəra Oyunu**\n- `/macera`: Fərdi macəra oyunu başladır.\n\n📊 **Reytinq Sistemi**\n- `/reyting [dövr]`: Mesaj statistikasını göstərir...\n- `/menim_rutbem`: Şəxsi mesaj sayınızı və rütbənizi göstərir."

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
    """Macəra oyununu başladır."""
    if context.chat_data.get('rpg_active'):
        await update.message.reply_text("Artıq qrupda aktiv bir macəra oyunu var. Lütfən onun bitməsini gözləyin.")
        return

    user = update.message.from_user
    context.chat_data['rpg_active'] = True
    context.chat_data['rpg_owner_id'] = user.id
    context.chat_data['rpg_inventory'] = set()

    node = STORY_DATA['start']
    text, choices = node['text'], node['choices']
    keyboard = [[InlineKeyboardButton(choice['text'], callback_data=f"rpg_{choice['goto']}")] for choice in choices]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(text, reply_markup=reply_markup)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query, user, data = update.callback_query, update.callback_query.from_user, update.callback_query.data
    await query.answer()

    if data.startswith("rpg_"):
        owner_id = context.chat_data.get('rpg_owner_id')
        if owner_id and user.id != owner_id:
            await query.answer("⛔ Bu macəranı yalnız oyunu başlayan şəxs idarə edə bilər!", show_alert=True)
            return

        node_key = data.split('_', 1)[1]
        node = STORY_DATA.get(node_key)
        if not node: await query.edit_message_text("Xəta baş verdi, hekayə tapılmadı."); return

        inventory = context.chat_data.setdefault('rpg_inventory', set())
        if node.get('get_item'):
            inventory.add(node['get_item'])
            
        text, choices = node['text'], node['choices']
        keyboard_buttons = []
        for choice in choices:
            if 'requires_item' in choice:
                if choice['requires_item'] in inventory:
                    keyboard_buttons.append([InlineKeyboardButton(choice['text'], callback_data=f"rpg_{choice['goto']}")])
            else:
                keyboard_buttons.append([InlineKeyboardButton(choice['text'], callback_data=f"rpg_{choice['goto']}")])
        
        reply_markup = InlineKeyboardMarkup(keyboard_buttons) if keyboard_buttons else None

        if not choices: # Hekayə bitibsə
            await query.edit_message_text(text=text, reply_markup=None)
            context.chat_data.pop('rpg_active', None)
            context.chat_data.pop('rpg_owner_id', None)
            context.chat_data.pop('rpg_inventory', None)
        else:
            await query.edit_message_text(text=text, reply_markup=reply_markup)
        return

    #... (qalan button handler kodu)
    if data == "back_to_start_menu": #...
        pass
    if data.startswith("start_info_"): #...
        pass
    if data.startswith("quiz_"): #...
        pass
    if data == "skip_riddle": #...
        pass
    if data == "register_join": #...
        pass
    elif data.startswith("game_"): #...
        pass

async def rating_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    #... (kod eyni qalır)
    pass
async def my_rank_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    #... (kod eyni qalır)
    pass
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    #... (kod eyni qalır)
    pass

def main() -> None:
    run_pre_flight_checks()
    init_db()
    application = Application.builder().token(TOKEN).build()
    group_filter = ~filters.ChatType.PRIVATE
    
    # Əmrlər
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("qaydalar", qaydalar_command))
    application.add_handler(CommandHandler("macera", macera_command, filters=group_filter))
    # ... (qalan handler-lər)

    # Handler-lər
    application.add_handler(CallbackQueryHandler(button_handler))
    # PollHandler artıq lazım deyil
    
    print("Bot işə düşdü...")
    application.run_polling()
if __name__ == '__main__':
    main()
