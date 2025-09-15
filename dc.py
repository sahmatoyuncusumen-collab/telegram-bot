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
    if not DATABASE_URL or not TOKEN:
        logger.critical("--- XƏTA ---")
        logger.critical("DATABASE_URL və ya TELEGRAM_TOKEN tapılmadı. Proqram dayandırılır.")
        sys.exit(1)
    logger.info("Bütün konfiqurasiya dəyişənləri mövcuddur. Bot başladılır...")

# --- BAZA FUNKSİYALARI ---
def init_db():
    conn, cur = None, None
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cur = conn.cursor()
        cur.execute("CREATE TABLE IF NOT EXISTS message_counts (id SERIAL PRIMARY KEY, chat_id BIGINT NOT NULL, user_id BIGINT NOT NULL, username TEXT, message_timestamp TIMESTAMPTZ NOT NULL );")
        cur.execute("CREATE TABLE IF NOT EXISTS premium_users (user_id BIGINT PRIMARY KEY, added_date TIMESTAMPTZ NOT NULL);")
        conn.commit()
        logger.info("Verilənlər bazası cədvəlləri hazırdır.")
    except Exception as e:
        logger.error(f"Baza yaradılarkən xəta: {e}")
        sys.exit(1)
    finally:
        if cur: cur.close()
        if conn: conn.close()

def is_user_premium(user_id: int) -> bool:
    conn, cur = None, None
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
        if cur: cur.close()
        if conn: conn.close()

def add_premium_user(user_id: int) -> bool:
    conn, cur = None, None
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cur = conn.cursor()
        cur.execute("INSERT INTO premium_users (user_id, added_date) VALUES (%s, %s) ON CONFLICT (user_id) DO NOTHING;", 
                    (user_id, datetime.datetime.now(datetime.timezone.utc)))
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"Premium istifadəçi əlavə edərkən xəta: {e}")
        return False
    finally:
        if cur: cur.close()
        if conn: conn.close()

def remove_premium_user(user_id: int) -> bool:
    conn, cur = None, None
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
        if cur: cur.close()
        if conn: conn.close()

# --- MƏZMUN SİYAHILARI ---
ABOUT_TEXT = "🤖 **Bot Haqqında**\n\nMən qruplar üçün nəzərdə tutulmuş əyləncə və statistika botuyam. Mənimlə viktorina, tapmaca və digər oyunları oynaya, həmçinin qrupdakı aktivliyinizə görə rütbə qazana bilərsiniz."
RULES_TEXT = "📜 **Qrup Qaydaları**\n\n1. Reklam etmək qəti qadağandır.\n2. Təhqir, söyüş və aqressiv davranışlara icazə verilmir.\n3. Dini və siyasi mövzuları müzakirə etmək olmaz.\n4. Qaydalara riayət etməyən istifadəçilər xəbərdarlıqsız uzaqlaşdırılacaq."

# VIKTORINA SUALLARI
SADE_QUIZ_QUESTIONS = [
    {'question': 'Azərbaycanın paytaxtı haradır?', 'options': ['Gəncə', 'Sumqayıt', 'Bakı', 'Naxçıvan'], 'correct': 'Bakı'},
]
PREMIUM_QUIZ_QUESTIONS = [
    {'question': 'Əsərlərini Nizami Gəncəvi imzası ilə yazan şairin əsl adı nədir?', 'options': ['İlyas Yusif oğlu', 'Məhəmməd Füzuli', 'İmadəddin Nəsimi', 'Əliağa Vahid'], 'correct': 'İlyas Yusif oğlu'},
]

# DOĞRULUQ VƏ CƏSARƏT SUALLARI (Başlanğıc Paketi)
SADE_TRUTH_QUESTIONS = ["Uşaqlıqda ən böyük qorxun nə olub?", "Heç kimin bilmədiyi bir bacarığın var?", "Ən son nə vaxt ağlamısan və niyə?", "Əgər bir gün görünməz olsaydın, nə edərdin?", "Telefonunda ən utancverici proqram hansıdır?", "Həyatında ən çox peşman olduğun şey nədir?", "Heç yalan danışıb yaxalanmısan?", "Birinə aşiq olub amma deməmisən?", "Ən qəribə yuxun nə olub?", "Hamamda mahnı oxuyursan?"]
SADE_DARE_TASKS = ["Qrupdakı son mesajı əlifbanın hər hərfi ilə tərsinə yaz.", "Telefonundakı son şəkli qrupa göndər (uyğun deyilsə, ondan əvvəlkini).", "Qrupdakı birinə kompliment de.", "Elə indicə pəncərədən çölə \"Mən dünyanı sevirəm!\" deyə qışqır.", "Profil şəklini 5 dəqiqəlik bir meyvə şəkli ilə dəyişdir.", "Ən sevdiyin mahnıdan bir hissəni səsli mesajla göndər.", "Bir stəkan suyu birnəfəsə iç.", "İki fərqli corab geyin və şəklini çəkib göndər.", "Telefonunun klaviaturasında gözüyumulu \"Mən ən yaxşı oyunçuyam\" yazmağa çalış.", "Emojilərlə bir film adı təsvir et, qoy qrup tapsın."]
PREMIUM_TRUTH_QUESTIONS = ["Həyatının geri qalanını yalnız bir filmi izləyərək keçirməli olsaydın, hansı filmi seçərdin?", "Əgər zaman maşının olsaydı, keçmişə yoxsa gələcəyə gedərdin? Niyə?", "Sənə ən çox təsir edən kitab hansı olub?", "Münasibətdə sənin üçün ən vacib 3 şey nədir?", "Özündə dəyişdirmək istədiyin bir xüsusiyyət hansıdır?", "Heç sosial mediada birini gizlicə izləmisən (stalk)?", "İnsanların sənin haqqında bilmədiyi qəribə bir vərdişin var?", "Ən böyük xəyalın nədir?", "Valideynlərindən gizlətdiyin bir şey olub?", "Məşhur birindən xoşun gəlir?"]
PREMIUM_DARE_TASKS = ["Qrupdakı adminlərdən birinə 10 dəqiqəlik \"Ən yaxşı admin\" statusu yaz.", "Səni ən yaxşı təsvir edən bir \"meme\" tap və qrupa göndər.", "Son 1 saat içində telefonla danışdığın son insana zəng edib \"Səni indicə cəsarət oyununda seçdilər\" de.", "Səsini dəyişdirərək bir nağıl personajı kimi danış və səsli mesaj göndər.", "Google-da \"Mən niyə bu qədər möhtəşəməm\" yazıb axtarış nəticələrinin şəklini göndər.", "Qrupdakı onlayn olan birinə şəxsi mesajda qəribə bir emoji göndər və heç nə yazma.", "Profil bioqrafiyanı 15 dəqiqəlik \"Bu qrupun premium üzvü\" olaraq dəyişdir.", "Bir qaşıq limon suyu iç.", "Bir dəsmalı başına papaq kimi qoy və şəklini çəkib göndər.", "Qrup söhbətinin adını 1 dəqiqəlik \"Ən yaxşı söhbət qrupu\" olaraq dəyişdir (əgər icazən varsa)."]


# --- KÖMƏKÇİ FUNKSİYALAR ---
async def is_user_admin(chat_id: int, user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if user_id == chat_id: return True
    try:
        chat_admins = await context.bot.get_chat_administrators(chat_id)
        return user_id in [admin.user.id for admin in chat_admins]
    except Exception as e:
        logger.error(f"Admin yoxlanarkən xəta: {e}")
        return False

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
    if not update.message or not update.message.new_chat_members: return
    for member in update.message.new_chat_members:
        if member.id == context.bot.id: continue
        welcome_message = (f"Salam, [{member.first_name}](tg://user?id={member.id})! 👋\n"
                         f"**'{update.message.chat.title}'** qrupuna xoş gəlmisən!\n\n"
                         "Əmrləri görmək üçün /start yaz.")
        await update.message.reply_text(welcome_message, parse_mode='Markdown')

# --- ƏSAS ƏMRLƏR ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("ℹ️ Bot Haqqında Məlumat", callback_data="start_info_about")],
        [InlineKeyboardButton("📜 Bütün Qaydalar", callback_data="start_info_qaydalar")],
        [InlineKeyboardButton("👥 Oyun Qrupumuz", url="https://t.me/+0z5V-OvEMmgzZTFi")],
        [InlineKeyboardButton(f"👨‍💻 Admin ilə Əlaqə", url=f"https://t.me/{ADMIN_USERNAME}")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    start_text = "Salam! Mən Oyun Botuyam. 🤖\nAşağıdakı menyudan istədiyin bölməni seç:"
    await update.message.reply_text(start_text, reply_markup=reply_markup)
    
async def haqqinda_command(update: Update, context: ContextTypes.DEFAULT_TYPE): await update.message.reply_text(ABOUT_TEXT, parse_mode='Markdown')
async def qaydalar_command(update: Update, context: ContextTypes.DEFAULT_TYPE): await update.message.reply_text(RULES_TEXT, parse_mode='Markdown')

async def my_rank_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.chat.type in [ChatType.GROUP, ChatType.SUPERGROUP]:
        await update.message.reply_text("Bu əmr yalnız qruplarda işləyir.")
        return

    user = update.message.from_user; chat_id = update.message.chat.id
    raw_message_count = 0; conn, cur = None, None
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
    effective_message_count = int(raw_message_count * 1.5) if user_is_premium else raw_message_count
    rank_title = get_rank_title(effective_message_count, user_is_premium)
    premium_icon = " 👑" if user_is_premium else ""
    
    reply_text = f"📊 **Sənin Statistikaların, {user.first_name}{premium_icon}!**\n\n💬 Bu qrupdakı real mesaj sayın: **{raw_message_count}**\n"
    if user_is_premium:
        reply_text += f"🚀 Premium ilə hesablanmış xalın: **{effective_message_count}**\n"
    reply_text += f"🏆 Rütbən: **{rank_title}**\n\nDaha çox mesaj yazaraq yeni rütbələr qazan!"
    await update.message.reply_text(reply_text, parse_mode='Markdown')

async def zer_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    dice_roll = random.randint(1, 6)
    await update.message.reply_text(f"🎲 Zər atıldı və düşən rəqəm: **{dice_roll}**", parse_mode='Markdown')

async def liderler_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.chat.type in [ChatType.GROUP, ChatType.SUPERGROUP]:
        await update.message.reply_text("Bu əmr yalnız qruplarda işləyir."); return

    chat_id = update.message.chat.id
    leaderboard_text = f"🏆 **'{update.message.chat.title}'**\nBu ayın ən aktiv 10 istifadəçisi:\n\n"
    conn, cur = None, None
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cur = conn.cursor()
        cur.execute(
            """ SELECT user_id, COUNT(*) as msg_count FROM message_counts 
                WHERE chat_id = %s AND message_timestamp >= date_trunc('month', NOW())
                GROUP BY user_id ORDER BY msg_count DESC LIMIT 10; """, (chat_id,)
        )
        leaders = cur.fetchall()
        
        if not leaders:
            await update.message.reply_text("Bu ay hələ heç kim mesaj yazmayıb. İlk sən ol!"); return

        leader_lines = []
        for i, (user_id, msg_count) in enumerate(leaders):
            try:
                member = await context.bot.get_chat_member(chat_id, user_id)
                user_name = member.user.first_name
            except Exception: user_name = f"İstifadəçi ({user_id})"
            
            premium_icon = " 👑" if is_user_premium(user_id) else ""
            place_icon = ["🥇", "🥈", "🥉"][i] if i < 3 else f"{i+1}."
            leader_lines.append(f"{place_icon} {user_name}{premium_icon} - **{msg_count}** mesaj")
            
        await update.message.reply_text(leaderboard_text + "\n".join(leader_lines), parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Liderlər cədvəli göstərilərkən xəta: {e}")
        await update.message.reply_text("❌ Liderlər cədvəlini göstərərkən xəta baş verdi.")
    finally:
        if cur: cur.close()
        if conn: conn.close()
        
async def dcoyun_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    chat_id = update.message.chat.id
    if update.message.chat.type == ChatType.PRIVATE:
        await update.message.reply_text("Bu oyunu yalnız qruplarda oynamaq olar."); return
    if not await is_user_admin(chat_id, user_id, context):
        await update.message.reply_text("⛔ Bu oyunu yalnız qrup adminləri başlada bilər."); return
    if context.chat_data.get('dc_game_active'):
        await update.message.reply_text("Artıq aktiv bir 'Doğruluq yoxsa Cəsarət?' oyunu var."); return
    
    context.chat_data['dc_game_starter_id'] = user_id
    keyboard = [[InlineKeyboardButton("Doğruluq Cəsarət (sadə)", callback_data="dc_select_sade")], [InlineKeyboardButton("Doğruluq Cəsarət (Premium👑)", callback_data="dc_select_premium")]]
    await update.message.reply_text("Doğruluq Cəsarət oyununa xoş gəlmisiniz👋", reply_markup=InlineKeyboardMarkup(keyboard))

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
async def show_dc_registration_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.callback_query.message
    players = context.chat_data.get('dc_players', [])
    player_list_text = "\n\n**Qeydiyyatdan keçənlər:**\n"
    if not players: player_list_text += "Heç kim qoşulmayıb."
    else:
        player_list_text += "\n".join([f"- [{p['name']}](tg://user?id={p['id']})" for p in players])
    keyboard = [[InlineKeyboardButton("Qeydiyyatdan Keç ✅", callback_data="dc_register")], [InlineKeyboardButton("Oyunu Başlat ▶️", callback_data="dc_start_game")], [InlineKeyboardButton("Oyunu Ləğv Et ⏹️", callback_data="dc_stop_game")]]
    await message.edit_text("**Doğruluq yoxsa Cəsarət?**\n\nOyuna qoşulmaq üçün 'Qeydiyyatdan Keç' düyməsinə basın." + player_list_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)

async def dc_next_turn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.callback_query.message
    current_index = context.chat_data.get('dc_current_player_index', -1)
    players = context.chat_data.get('dc_players', [])
    next_index = (current_index + 1) % len(players)
    context.chat_data['dc_current_player_index'] = next_index
    current_player = players[next_index]
    is_premium = context.chat_data.get('dc_is_premium', False)
    truth_callback = "dc_ask_truth_premium" if is_premium else "dc_ask_truth_sade"
    dare_callback = "dc_ask_dare_premium" if is_premium else "dc_ask_dare_sade"
    keyboard = [[InlineKeyboardButton("Doğruluq 🤔", callback_data=truth_callback)], [InlineKeyboardButton("Cəsarət 😈", callback_data=dare_callback)]]
    await message.edit_text(f"Sıra sənə çatdı, [{current_player['name']}](tg://user?id={current_player['id']})! Seçimini et:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; user = query.from_user; data = query.data; chat_id = query.message.chat.id
    await query.answer()

    if data.startswith("viktorina_") or data.startswith("quiz_"):
        quiz_starter_id = context.chat_data.get('quiz_starter_id')
        if quiz_starter_id and user.id != quiz_starter_id:
            await query.answer("⛔ Bu, sizin başlatdığınız oyun deyil.", show_alert=True); return
        # ... (Viktorina logic davam edir)
        pass # Bu hissəni öz kodunuzdan götürün
    
    elif data in ["start_info_about", "start_info_qaydalar", "back_to_start"]:
        # ... (Start menyusu logic)
        pass # Bu hissəni öz kodunuzdan götürün

    elif data.startswith('dc_'):
        game_starter_id = context.chat_data.get('dc_game_starter_id')
        if data in ['dc_select_sade', 'dc_select_premium', 'dc_start_game', 'dc_stop_game', 'dc_next_turn']:
            # Admin və ya oyunu başladan yoxlamaları
            is_admin = await is_user_admin(chat_id, user.id, context)
            if user.id != game_starter_id and not is_admin:
                await query.answer("⛔ Bu düymədən yalnız oyunu başladan şəxs və ya adminlər istifadə edə bilər.", show_alert=True); return
        
        if data in ['dc_select_sade', 'dc_select_premium']:
            is_premium_choice = (data == 'dc_select_premium')
            if is_premium_choice and not is_user_premium(user.id):
                await query.answer("⛔ Bu rejimi yalnız premium statuslu adminlər başlada bilər.", show_alert=True); return
            context.chat_data.update({'dc_game_active': True, 'dc_is_premium': is_premium_choice, 'dc_players': [], 'dc_current_player_index': -1})
            await show_dc_registration_message(update, context)
        
        elif data == 'dc_register':
            if not context.chat_data.get('dc_game_active'):
                await query.answer("Artıq aktiv oyun yoxdur.", show_alert=True); return
            players = context.chat_data.get('dc_players', [])
            if any(p['id'] == user.id for p in players):
                await query.answer("Siz artıq qeydiyyatdan keçmisiniz.", show_alert=True)
            else:
                players.append({'id': user.id, 'name': user.first_name})
                context.chat_data['dc_players'] = players
                await query.answer("Uğurla qoşuldunuz!", show_alert=False)
                await show_dc_registration_message(update, context)

        elif data == 'dc_start_game':
            players = context.chat_data.get('dc_players', [])
            if len(players) < 2:
                await query.answer("⛔ Oyunun başlaması üçün minimum 2 nəfər qeydiyyatdan keçməlidir.", show_alert=True); return
            random.shuffle(players)
            context.chat_data['dc_players'] = players
            await dc_next_turn(update, context)

        elif data == 'dc_stop_game':
            await query.message.edit_text("Oyun admin tərəfindən ləğv edildi.")
            for key in list(context.chat_data):
                if key.startswith('dc_'): del context.chat_data[key]
        
        elif data.startswith('dc_ask_'):
            players = context.chat_data.get('dc_players', [])
            current_player = players[context.chat_data.get('dc_current_player_index', -1)]
            if user.id != current_player['id']:
                await query.answer("⛔ Bu sənin sıran deyil!", show_alert=True); return
            
            is_premium = context.chat_data.get('dc_is_premium', False)
            text_to_show = ""
            if 'truth' in data:
                question = random.choice(PREMIUM_TRUTH_QUESTIONS if is_premium else SADE_TRUTH_QUESTIONS)
                text_to_show = f"🤔 **Doğruluq:**\n\n`{question}`"
            else: # dare
                task = random.choice(PREMIUM_DARE_TASKS if is_premium else SADE_DARE_TASKS)
                text_to_show = f"😈 **Cəsarət:**\n\n`{task}`"
            await query.message.edit_text(text_to_show, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Növbəti Oyunçu ➡️", callback_data="dc_next_turn")]]), parse_mode=ParseMode.MARKDOWN)

        elif data == 'dc_next_turn':
            await dc_next_turn(update, context)

    # ... (Viktorina logic tam kodunu bura əlavə edin)

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
        logger.info("Bot səliqəli şəkildə dayandırılır...")
        if application.updater and application.updater.is_running():
            await application.updater.stop()
        if application.running:
            await application.stop()
        await application.shutdown()

if __name__ == '__main__':
    asyncio.run(main())

