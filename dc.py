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
        print("--- XƏTA ---"); print("DATABASE_URL və ya TELEGRAM_TOKEN tapılmadı."); print("Bu skript yalnız düzgün konfiqurasiya edilmiş Render serverində işləməlidir."); sys.exit(1)
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
QUIZ_QUESTIONS = [
    {'question': 'Azərbaycanın paytaxtı haradır?', 'options': ['Gəncə', 'Sumqayıt', 'Bakı', 'Naxçıvan'], 'correct': 'Bakı'},
    {'question': 'Hansı planet "Qırmızı Planet" kimi tanınır?', 'options': ['Venera', 'Mars', 'Yupiter', 'Saturn'], 'correct': 'Mars'},
    {'question': 'Dünyanın ən hündür dağı hansıdır?', 'options': ['K2', 'Everest', 'Makalu', 'Lhotse'], 'correct': 'Everest'},
    {'question': 'Əsərlərini Nizami Gəncəvi imzası ilə yazan şairin əsl adı nədir?', 'options': ['İlyas Yusif oğlu', 'Məhəmməd Füzuli', 'İmadəddin Nəsimi', 'Əliağa Vahid'], 'correct': 'İlyas Yusif oğlu'},
    {'question': 'Bir il ərzində neçə ayda 31 gün var?', 'options': ['6', '7', '8', '5'], 'correct': '7'},
    {'question': 'Leonardo da Vinçinin şah əsəri olan "Mona Liza" tablosu hazırda hansı muzeydə sərgilənir?', 'options': ['Britaniya Muzeyi', 'Vatikan Muzeyi', 'Ermitaj', 'Luvr Muzeyi'], 'correct': 'Luvr Muzeyi'}
]
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
    #... (kod eyni qalır)
    pass
# Bütün köhnə funksiyalar aşağıdakı tam kodda mövcuddur

# --- YENİ ƏMR FUNKSİYASI ---
async def viktorina_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Yeni viktorina oyununu başladır."""
    chat_id = update.message.chat_id
    if context.chat_data.get('quiz_active'):
        await update.message.reply_text("Artıq aktiv bir viktorina var! Zəhmət olmasa, əvvəlcə onu cavablandırın.")
        return

    question_data = random.choice(QUIZ_QUESTIONS)
    question = question_data['question']
    options = question_data['options']
    correct_answer = question_data['correct']

    random.shuffle(options) # Cavabların yerini hər dəfə dəyişir

    context.chat_data['correct_quiz_answer'] = correct_answer
    context.chat_data['quiz_active'] = True
    
    keyboard = [[InlineKeyboardButton(option, callback_data=f"quiz_{option}")] for option in options]
    reply_markup = InlineKeyboardMarkup(keyboard)

    message = await update.message.reply_text(f"Viktorina başladı! 🧠\n\n**Sual:** {question}", parse_mode='Markdown', reply_markup=reply_markup)
    context.chat_data['quiz_message_id'] = message.message_id


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query, user, data = update.callback_query, update.callback_query.from_user, update.callback_query.data
    await query.answer()

    # YENİ: Viktorina cavablarını yoxlayan məntiq
    if data.startswith("quiz_"):
        if not context.chat_data.get('quiz_active'):
            await query.answer("Bu viktorina artıq bitib.", show_alert=True)
            return

        chosen_answer = data.split('_', 1)[1]
        correct_answer = context.chat_data['correct_quiz_answer']

        if chosen_answer == correct_answer:
            await query.answer("Düzdür!", show_alert=False)
            await context.bot.edit_message_text(
                chat_id=query.message.chat_id,
                message_id=context.chat_data['quiz_message_id'],
                text=f"{query.message.text}\n\n---\n🥳 Qalib: {user.first_name}!\n✅ Düzgün cavab: **{correct_answer}**",
                parse_mode='Markdown'
            )
            # Oyun statusunu təmizləyirik
            del context.chat_data['quiz_active']
            del context.chat_data['correct_quiz_answer']
            del context.chat_data['quiz_message_id']
        else:
            await query.answer("Səhv cavab! Başqası cəhd etsin. 😥", show_alert=True)
        return

    # Tapmaca və "Doğruluq Cəsarət" məntiqi olduğu kimi qalır
    # ... (aşağıdakı tam kodda mövcuddur)

def main() -> None:
    #...
    application.add_handler(CommandHandler("viktorina", viktorina_command, filters=group_filter))
    #...

# --- Bütün Dəyişikliklərlə Birlikdə Tam Kod (BUNU KOPYALAYIN) ---
import logging, random, os, psycopg2, datetime, sys
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters
from telegram.constants import ChatType

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

DATABASE_URL = os.environ.get("DATABASE_URL")
TOKEN = os.environ.get("TELEGRAM_TOKEN")

def run_pre_flight_checks():
    if not DATABASE_URL or not TOKEN:
        print("--- XƏTA ---"); print("DATABASE_URL və ya TELEGRAM_TOKEN tapılmadı."); sys.exit(1)
    print("Bütün konfiqurasiya dəyişənləri mövcuddur. Bot başladılır...")

def init_db():
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cur = conn.cursor()
        cur.execute("CREATE TABLE IF NOT EXISTS message_counts (id SERIAL PRIMARY KEY, chat_id BIGINT NOT NULL, user_id BIGINT NOT NULL, username TEXT NOT NULL, message_timestamp TIMESTAMPTZ NOT NULL );")
        conn.commit(); cur.close(); conn.close()
        print("Verilənlər bazası cədvəli hazırdır.")
    except Exception as e:
        print(f"Baza yaradılarkən xəta: {e}")

QUIZ_QUESTIONS = [{'question': 'Azərbaycanın paytaxtı haradır?', 'options': ['Gəncə', 'Sumqayıt', 'Bakı', 'Naxçıvan'], 'correct': 'Bakı'},{'question': 'Hansı planet "Qırmızı Planet" kimi tanınır?', 'options': ['Venera', 'Mars', 'Yupiter', 'Saturn'], 'correct': 'Mars'},{'question': 'Dünyanın ən hündür dağı hansıdır?', 'options': ['K2', 'Everest', 'Makalu', 'Lhotse'], 'correct': 'Everest'},{'question': 'Əsərlərini Nizami Gəncəvi imzası ilə yazan şairin əsl adı nədir?', 'options': ['İlyas Yusif oğlu', 'Məhəmməd Füzuli', 'İmadəddin Nəsimi', 'Əliağa Vahid'], 'correct': 'İlyas Yusif oğlu'},{'question': 'Bir il ərzində neçə ayda 31 gün var?', 'options': ['6', '7', '8', '5'], 'correct': '7'},{'question': 'Leonardo da Vinçinin şah əsəri olan "Mona Liza" tablosu hazırda hansı muzeydə sərgilənir?', 'options': ['Britaniya Muzeyi', 'Vatikan Muzeyi', 'Ermitaj', 'Luvr Muzeyi'], 'correct': 'Luvr Muzeyi'}]
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
                         "Mən bu qrupun əyləncə və statistika botuyam. /oyun, /tapmaca və ya /viktorina yaza bilərsiniz.\n\n"
                         "Qrupun ən aktiv üzvlərini görmək üçün isə /reyting gunluk əmrini istifadə et.")
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
    await update.message.reply_text("Salam! 🤖\n\nQrupda əyləncə üçün əmrlər:\n`/oyun` - Doğruluq yoxsa Cəsarət?\n`/tapmaca` - Tapmaca oyunu\n`/viktorina` - Viktorina oyunu\n\nStatistika üçün:\n`/reyting [dövr]`\n`/menim_rutbem`")
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
    context.chat_data['game_active'] = True
    player_list = list(players.values()); random.shuffle(player_list)
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
    chosen_riddle = random.choice(RIDDLES)
    context.chat_data['riddle_answer'] = [ans.lower() for ans in chosen_riddle['answers']]
    context.chat_data['riddle_active'] = True
    keyboard = [[InlineKeyboardButton("Cavabı Göstər 💡", callback_data="skip_riddle")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(f"Tapmaca gəldi! 🕵️‍♂️\n\n**{chosen_riddle['riddle']}**", parse_mode='Markdown', reply_markup=reply_markup)
async def viktorina_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    if context.chat_data.get('quiz_active'):
        await update.message.reply_text("Artıq aktiv bir viktorina var! Zəhmət olmasa, əvvəlcə onu cavablandırın."); return
    question_data = random.choice(QUIZ_QUESTIONS)
    question, correct_answer, options = question_data['question'], question_data['correct'], question_data['options']
    random.shuffle(options)
    context.chat_data['correct_quiz_answer'] = correct_answer
    context.chat_data['quiz_active'] = True
    keyboard = [[InlineKeyboardButton(option, callback_data=f"quiz_{option}")] for option in options]
    reply_markup = InlineKeyboardMarkup(keyboard)
    message = await update.message.reply_text(f"Viktorina başladı! 🧠\n\n**Sual:** {question}", parse_mode='Markdown', reply_markup=reply_markup)
    context.chat_data['quiz_message_id'] = message.message_id
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query, user, data = update.callback_query, update.callback_query.from_user, update.callback_query.data
    await query.answer()
    if data.startswith("quiz_"):
        if not context.chat_data.get('quiz_active'):
            await query.answer("Bu viktorina artıq bitib.", show_alert=True); return
        chosen_answer = data.split('_', 1)[1]; correct_answer = context.chat_data['correct_quiz_answer']
        if chosen_answer == correct_answer:
            await query.answer("Düzdür!", show_alert=False)
            await context.bot.edit_message_text(
                chat_id=query.message.chat_id, message_id=context.chat_data['quiz_message_id'],
                text=f"{query.message.text}\n\n---\n🥳 Qalib: {user.first_name}!\n✅ Düzgün cavab: **{correct_answer}**",
                parse_mode='Markdown'
            )
            del context.chat_data['quiz_active']; del context.chat_data['correct_quiz_answer']; del context.chat_data['quiz_message_id']
        else:
            await query.answer("Səhv cavab! Başqası cəhd etsin. 😥", show_alert=True)
        return
    if data == "skip_riddle":
        if not context.chat_data.get('riddle_active'):
            await query.answer("Bu tapmaca artıq bitib.", show_alert=True); return
        correct_answers = context.chat_data.get('riddle_answer', [])
        correct_answer_text = ", ".join(correct_answers).capitalize()
        await query.edit_message_text(text=f"{query.message.text}\n\n---\n😥 Heç kim tapa bilmədi!\n✅ **Düzgün cavab:** {correct_answer_text}\n\nYeni tapmaca üçün /tapmaca yazın.", parse_mode='Markdown')
        del context.chat_data['riddle_active']; del context.chat_data['riddle_answer']
        return
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
        question = random.choice(NORMAL_TRUTH_QUESTIONS) if action == 'truth' else random.choice(NORMAL_DARE_TASKS)
        response_text = f"📜 {user.first_name} üçün **Doğruluq**:\n\n> {question}" if action == 'truth' else f"🔥 {user.first_name} üçün **Cəsarət**:\n\n> {random.choice(NORMAL_DARE_TASKS)}"
        command_suggestion = "\n\n*Cavab verildikdən sonra admin növbəti tura keçmək üçün /novbeti yazsın.*"
        await query.edit_message_text(text=response_text + command_suggestion, parse_mode='Markdown')
async def rating_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id, args = update.message.chat_id, context.args
    if not args: await update.message.reply_text("Zəhmət olmasa, dövrü təyin edin:\n`/reyting gunluk`\n`/reyting heftelik`\n`/reyting ayliq`", parse_mode='Markdown'); return
    period = args[0].lower()
    if period == "gunluk": interval, title = "1 day", "Son 24 Saatın Ən Aktiv Üzvləri ☀️"
    elif period == "heftelik": interval, title = "7 days", "Son 7 Günün Ən Aktiv Üzvləri 🗓️"
    elif period == "ayliq": interval, title = "1 month", "Son 30 Günün Ən Aktiv Üzvləri 🌙"
    else: await update.message.reply_text("Yanlış dövr. Mümkün seçimlər: gunluk, heftelik, ayliq"); return
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cur = conn.cursor()
        query = f"SELECT user_id, username, COUNT(*) as msg_count FROM message_counts WHERE chat_id = %s AND message_timestamp >= NOW() - INTERVAL '{interval}' GROUP BY user_id, username ORDER BY msg_count DESC LIMIT 10;"
        cur.execute(query, (chat_id,)); results = cur.fetchall(); cur.close(); conn.close()
        if not results: await update.message.reply_text("Bu dövr üçün heç bir mesaj tapılmadı."); return
        leaderboard = f"📊 **{title}**\n\n"
        for i, (user_id, username, msg_count) in enumerate(results):
            medal = ""
            if i == 0: medal = "🥇"
            elif i == 1: medal = "🥈"
            elif i == 2: medal = "🥉"
            rank_title = get_rank_title(msg_count)
            leaderboard += f"{i+1}. {medal} [{username}](tg://user?id={user_id}) - `{msg_count}` msj ({rank_title})\n"
        await update.message.reply_text(leaderboard, parse_mode='Markdown', disable_web_page_preview=True)
    except Exception as e:
        logger.error(f"Reytinq alınarkən xəta: {e}"); await update.message.reply_text("Reytinq cədvəlini hazırlayarkən bir xəta baş verdi.")
async def my_rank_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id, user_name, chat_id = update.message.from_user.id, update.message.from_user.first_name, update.message.chat_id
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cur = conn.cursor(); query = "SELECT COUNT(*) FROM message_counts WHERE user_id = %s AND chat_id = %s;"
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
            del context.chat_data['riddle_active']; del context.chat_data['riddle_answer']
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cur = conn.cursor()
        cur.execute("INSERT INTO message_counts (chat_id, user_id, username, message_timestamp) VALUES (%s, %s, %s, %s)",
                    (chat_id, user.id, user.first_name, datetime.datetime.now(datetime.timezone.utc)))
        conn.commit(); cur.close(); conn.close()
    except Exception as e:
        logger.error(f"Mesajı bazaya yazarkən xəta: {e}")
def main() -> None:
    run_pre_flight_checks()
    init_db()
    application = Application.builder().token(TOKEN).build()
    group_filter = ~filters.ChatType.PRIVATE
    application.add_handler(CommandHandler("start", start_command))
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
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND) & group_filter, handle_message))
    application.add_handler(MessageHandler(filters.StatusUpdate.ALL & group_filter, welcome_new_members))
    application.add_handler(MessageHandler(filters.ChatType.PRIVATE & (~filters.COMMAND), start_command))
    application.add_handler(CallbackQueryHandler(button_handler))
    print("Bot işə düşdü...")
    application.run_polling()
if __name__ == '__main__':
    main()
