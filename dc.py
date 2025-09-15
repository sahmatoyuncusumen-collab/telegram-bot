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
    # ... (Viktorina sualları burada tam şəkildə qalır) ...
]
PREMIUM_QUIZ_QUESTIONS = [
    # ... (Viktorina sualları burada tam şəkildə qalır) ...
]

# DOĞRULUQ VƏ CƏSARƏT SUALLARI (GENİŞLƏNDİRİLMİŞ BAZA)
SADE_TRUTH_QUESTIONS = [
    "Uşaqlıqda ən böyük qorxun nə olub?", "Heç kimin bilmədiyi bir bacarığın var?", "Ən son nə vaxt ağlamısan və niyə?", "Əgər bir gün görünməz olsaydın, nə edərdin?", "Telefonunda ən utancverici proqram hansıdır?", "Həyatında ən çox peşman olduğun şey nədir?", "Heç yalan danışıb yaxalanmısan?", "Birinə aşiq olub amma deməmisən?", "Ən qəribə yuxun nə olub?", "Hamamda mahnı oxuyursan?",
    "Ən çox bəyəndiyin, amma başqalarının bəyənmədiyi bir mahnı hansıdır?", "Uşaqlıqda ən sevdiyin cizgi filmi hansı idi?", "Heç kimə demədiyin qəribə bir yemək vərdişin var?", "Ən son kimin profilini gizlicə izləmisən?", "İnsanların ən çox hansı xüsusiyyəti səni əsəbiləşdirir?", "Həyatında bir şeyi dəyişə bilsəydin, bu nə olardı?", "Heç imtahanda köçürmüsən?", "Aldığın ən pis hədiyyə nə olub?", "Bir günə limitsiz pulun olsaydı, nəyə xərcləyərdin?", "Gizli bir istedadın var?", "Ən çox istifadə etdiyin emoji hansıdır?", "Telefonunun ekran şəkli nədir?", "Uşaqlıqda hansı ləqəblə çağırılırdın?", "Heç bir yerdə tək qalıb qorxmusan?", "Ən böyük səhvin nə olub?",
]
SADE_DARE_TASKS = [
    "Qrupdakı son mesajı əlifbanın hər hərfi ilə tərsinə yaz.", "Telefonundakı son şəkli qrupa göndər (uyğun deyilsə, ondan əvvəlkini).", "Qrupdakı birinə kompliment de.", "Elə indicə pəncərədən çölə \"Mən dünyanı sevirəm!\" deyə qışqır.", "Profil şəklini 5 dəqiqəlik bir meyvə şəkli ilə dəyişdir.", "Ən sevdiyin mahnıdan bir hissəni səsli mesajla göndər.", "Bir stəkan suyu birnəfəsə iç.", "İki fərqli corab geyin və şəklini çəkib göndər.", "Telefonunun klaviaturasında gözüyumulu \"Mən ən yaxşı oyunçuyam\" yazmağa çalış.", "Emojilərlə bir film adı təsvir et, qoy qrup tapsın.",
    "Qrupdakı birinə \"Sən mənim ən yaxşı dostumsan\" yaz.", "Növbəti 5 dəqiqə ərzində yalnız şeir dili ilə danış.", "Ən qəribə üz ifadəni göstərən bir selfie çəkib qrupa göndər.", "Sonuncu səsli mesajını qrupa yönləndir (forward et).", "Qrupdakı birinin adını tərifləyən bir cümlə qur.", "Ayaqqabını başına qoyub şəkil çəkdir.", "Google-da adını axtar və çıxan ilk şəkli göndər.", "Qrupdakı hər kəsə \"Günaydın\" yaz (gecə olsa belə).", "Gözlərini yum və klaviaturada təsadüfi hərflərə basaraq bir cümlə göndər.", "Bir heyvan səsi çıxarıb səsli mesaj olaraq göndər.", "Növbəti 3 mesajını böyük hərflərlə yaz.", "Telefonunda zəng səsi olaraq təyin etdiyin mahnının adını yaz.", "Qrupda ən az danışan adama bir sual ver.", "Bir qaşıq ketçup ye.", "Qrupdakı hər kəsə bir virtual gül (🌹) göndər.",
]
PREMIUM_TRUTH_QUESTIONS = [
    "Həyatının geri qalanını yalnız bir filmi izləyərək keçirməli olsaydın, hansı filmi seçərdin?", "Əgər zaman maşının olsaydı, keçmişə yoxsa gələcəyə gedərdin? Niyə?", "Sənə ən çox təsir edən kitab hansı olub?", "Münasibətdə sənin üçün ən vacib 3 şey nədir?", "Özündə dəyişdirmək istədiyin bir xüsusiyyət hansıdır?", "Heç sosial mediada birini gizlicə izləmisən (stalk)?", "İnsanların sənin haqqında bilmədiyi qəribə bir vərdişin var?", "Ən böyük xəyalın nədir?", "Valideynlərindən gizlətdiyin bir şey olub?", "Məşhur birindən xoşun gəlir?",
    "Həyatının bir soundtreki olsaydı, bu hansı mahnı olardı?", "Heç kimin sənin haqqında bilmədiyi bir müsbət xüsusiyyətin nədir?", "Ən son nə vaxt və niyə ürəkdən gülmüsən?", "İnsanlara güvənmək sənin üçün asandır, yoxsa çətin?", "Keçmişə qayıdıb özünə bir məsləhət verə bilsəydin, nə deyərdin?", "Hansısa bir qanunu pozmusan?", "Ən böyük qeyri-maddi qorxun nədir (tənha qalmaq, uğursuz olmaq kimi)?", "Səni həqiqətən nə xoşbəxt edir?", "Münasibətdə heç bağışlamayacağın şey nədir?", "Ən dəyərli əşyan nədir və niyə?", "Özünü 3 kəlmə ilə necə təsvir edərdin?", "Bu qrupda ən çox kiminlə dost olmaq istərdin?", "Heç bilərəkdən birinin qəlbini qırmısan?", "Sənin üçün ideal bir gün necə keçməlidir?", "Bir milyon dolların olsa, ilk nə edərdin?", "Həyat fəlsəfən nədir?", "Ən son kimə \"səni sevirəm\" demisən?", "Səncə, insanlar niyə yalan danışır?", "Ən utandığın an hansı olub?", "Bu həftə öyrəndiyin ən maraqlı şey nədir?", "Əgər bir supergücün olsaydı, bu nə olardı?", "Heç kəsin görmədiyi zaman etdiyin qəribə bir şey varmı?", "Telefonundakı kontaktlarda ən məşhur adam kimdir?", "Ölənədək yalnız bir növ yemək yeməli olsan, nə seçərdin?", "Səni nə motivasiya edir?", "Uğur sənin üçün nə deməkdir?", "Heç bir dostunun sirrini başqasına demisən?", "Ən son gördüyün kabus nə idi?", "Sənin üçün mükəmməl partner necə olmalıdır?", "İnsanlarda ilk nəyə diqqət edirsən?",
]
PREMIUM_DARE_TASKS = [
    "Qrupdakı adminlərdən birinə 10 dəqiqəlik \"Ən yaxşı admin\" statusu yaz.", "Səni ən yaxşı təsvir edən bir \"meme\" tap və qrupa göndər.", "Son 1 saat içində telefonla danışdığın son insana zəng edib \"Səni indicə cəsarət oyununda seçdilər\" de.", "Səsini dəyişdirərək bir nağıl personajı kimi danış və səsli mesaj göndər.", "Google-da \"Mən niyə bu qədər möhtəşəməm\" yazıb axtarış nəticələrinin şəklini göndər.", "Qrupdakı onlayn olan birinə şəxsi mesajda qəribə bir emoji göndər və heç nə yazma.", "Profil bioqrafiyanı 15 dəqiqəlik \"Bu qrupun premium üzvü\" olaraq dəyişdir.", "Bir qaşıq limon suyu iç.", "Bir dəsmalı başına papaq kimi qoy və şəklini çəkib göndər.", "Qrup söhbətinin adını 1 dəqiqəlik \"Ən yaxşı söhbət qrupu\" olaraq dəyişdir (əgər icazən varsa).",
    "Qrupdakı birinə zəng et və 1 dəqiqə ərzində gülməli bir lətifə danış.", "Sosial media hesablarından birində qrupun linkini paylaşıb \"Bura qoşulun\" yaz (10 dəqiqəlik).", "Gözlərini bağlayıb qarşındakı ilk əşyanın şəklini çək və göndər.", "Telefonundakı ən son zəng etdiyin adama \"Bağışlayın, səhv nömrə yığmışam\" deyə mesaj yaz.", "Qrupdakı birinin profil şəklinə 5 dəqiqə ərzində 5 fərqli reaksiya ver.", "İki fərqli içkini qarışdırıb iç (zərərli olmasın).", "Ən sevmədiyin mahnını zümzümə edərək səsli mesaj göndər.", "Qrupun bioqrafiyasını 5 dəqiqəlik \"Ən ağıllı insanların toplaşdığı məkan\" olaraq dəyişdir (icazən varsa).", "Sonuncu aldığın bir şeyin qəbzini (çekini) qrupa göndər.", "Qrupdakı birinə şəxsi mesajda sabahkı hava proqnozunu göndər.", "Bir kağıza öz adını sol əlinlə (sağ əlləsənsə) yazıb şəklini çək.", "Növbəti 10 dəqiqə ərzində bütün mesajlarına \"Miyau\" sözünü əlavə et.", "Kompüterinin və ya telefonunun əsas ekranının (homescreen) şəklini göndər.", "Ən çox istifadə etdiyin 3 emojini göndər və onların mənasını izah et.", "Bir şeir yaz və ilk sətri qrupdakı son mesaj olsun.", "Burnunun ucuna barmağını qoyub selfie çək.", "Qrupdakı birinə sabah üçün uğurlar arzula.", "Google-da \"ən gülməli heyvan videosu\" axtar və ilk çıxan videonu paylaş.", "Bir yemək resepti uydur və qrupda paylaş.", "Ən son dinlədiyin mahnını qrupda paylaş.", "Qrupdakı birinin mesajına cavab olaraq sadəcə \"Düzdür\" yaz.", "Bir stəkan süd içərkən şəkil çəkdir.", "Qrupdakı adminlərdən birinə təşəkkür mesajı yaz.", "Növbəti 5 dəqiqə ərzində hər mesajının sonuna 👻 emojisi qoy.", "Sonuncu getdiyin səyahətdən bir şəkil paylaş.", "Bir kağız parçasına bir ürək çək və üzərinə qrupun adını yaz, şəklini göndər.", "Ən sevdiyin yeməyin adını hərflərini alt-alta yazaraq göndər.", "Qrupda onlayn olan hər kəsi bir mesajda etiketlə (tag et).", "Bir cüt corabdan əlcək kimi istifadə edib şəkil çəkdir.", "Profil adının sonuna 10 dəqiqəlik 😜 emojisini əlavə et.",
]


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
        await update.message.reply_text("Bu əmr yalnız qruplarda işləyir."); return
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
        await update.message.reply_text("❌ Rütbənizi yoxlayarkən xəta baş verdi."); return
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
    if update.message.from_user.id != BOT_OWNER_ID:
        await update.message.reply_text("⛔ Bu əmrdən yalnız bot sahibi istifadə edə bilər."); return
    try:
        target_user_id = int(context.args[0])
        if add_premium_user(target_user_id):
            await update.message.reply_text(f"✅ `{target_user_id}` ID-li istifadəçi uğurla premium siyahısına əlavə edildi.", parse_mode='Markdown')
        else:
            await update.message.reply_text("❌ İstifadəçini əlavə edərkən xəta baş verdi.")
    except (IndexError, ValueError):
        await update.message.reply_text("⚠️ Düzgün istifadə: `/addpremium <user_id>`", parse_mode='Markdown')

async def remove_premium_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != BOT_OWNER_ID:
        await update.message.reply_text("⛔ Bu əmrdən yalnız bot sahibi istifadə edə bilər."); return
    try:
        target_user_id = int(context.args[0])
        if remove_premium_user(target_user_id):
            await update.message.reply_text(f"✅ `{target_user_id}` ID-li istifadəçinin premium statusu uğurla geri alındı.", parse_mode='Markdown')
        else:
            await update.message.reply_text("❌ Belə bir premium istifadəçi tapılmadı və ya xəta baş verdi.", parse_mode='Markdown')
    except (IndexError, ValueError):
        await update.message.reply_text("⚠️ Düzgün istifadə: `/removepremium <user_id>`", parse_mode='Markdown')

# --- VIKTORINA ƏMRİ VƏ OYUN MƏNTİQİ ---
async def viktorina_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.chat_data.get('quiz_active'):
        await update.message.reply_text("Artıq aktiv bir viktorina var!"); return
    context.chat_data['quiz_starter_id'] = update.message.from_user.id
    keyboard = [ [InlineKeyboardButton("Viktorina (Sadə) 🌱", callback_data="viktorina_sade")], [InlineKeyboardButton("Viktorina (Premium) 👑", callback_data="viktorina_premium")] ]
    await update.message.reply_text(f"Salam, {update.message.from_user.first_name}! Zəhmət olmasa, viktorina növünü seçin:", reply_markup=InlineKeyboardMarkup(keyboard))

async def ask_next_quiz_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ... (Bu funksiya əvvəlki tam kodda olduğu kimi qalır)
    pass
    
# DÜYMƏLƏRİ VƏ MESAJLARI İDARƏ EDƏN FUNKSİYALAR
async def show_dc_registration_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.callback_query.message
    players = context.chat_data.get('dc_players', [])
    player_list_text = "\n\n**Qeydiyyatdan keçənlər:**\n"
    if not players: player_list_text += "Heç kim qoşulmayıb."
    else: player_list_text += "\n".join([f"- [{p['name']}](tg://user?id={p['id']})" for p in players])
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
        
        # Viktorina logic
        if data == 'viktorina_sade' or data == 'viktorina_premium':
            is_premium_choice = (data == 'viktorina_premium')
            if is_premium_choice and not is_user_premium(user.id):
                await query.message.edit_text(f"⛔ Bu funksiya yalnız premium istifadəçilər üçündür.\n\nPremium status üçün adminlə əlaqə saxlayın: [Admin](https://t.me/{ADMIN_USERNAME})", parse_mode='Markdown'); return
            context.chat_data.clear()
            context.chat_data.update({ 'quiz_active': True, 'quiz_is_premium': is_premium_choice, 'quiz_lives': 3, 'quiz_score': 0, 'quiz_message_id': query.message.message_id, 'quiz_starter_id': user.id })
            await ask_next_quiz_question(update, context)
        elif context.chat_data.get('quiz_active'):
            if data == 'quiz_stop':
                score = context.chat_data.get('quiz_score', 0)
                await query.message.edit_text(f"Oyun dayandırıldı! ✅\n\nYekun xalınız: **{score}** ⭐", parse_mode='Markdown')
                context.chat_data.clear()
            elif data.startswith("quiz_"):
                chosen_answer = data.split('_', 1)[1]; correct_answer = context.chat_data['correct_quiz_answer']
                if chosen_answer == correct_answer:
                    context.chat_data['quiz_score'] += 1
                    await query.answer(text="✅ Düzdür! Növbəti sual gəlir...", show_alert=False)
                    await asyncio.sleep(2)
                    await ask_next_quiz_question(update, context)
                else:
                    context.chat_data['quiz_lives'] -= 1
                    lives_left = context.chat_data['quiz_lives']
                    await query.answer(text=f"❌ Səhv cavab! {lives_left} canınız qaldı.", show_alert=True)
                    if lives_left == 0:
                        score = context.chat_data.get('quiz_score', 0)
                        await query.message.edit_text(f"Canlarınız bitdi! 😔\nDüzgün cavab: **{correct_answer}**\nYekun xalınız: **{score}** ⭐", parse_mode='Markdown')
                        context.chat_data.clear()
                    else:
                        is_premium = context.chat_data.get('quiz_is_premium', False)
                        quiz_title = "Premium Viktorina 👑" if is_premium else "Sadə Viktorina 🌱"
                        lives_text = "❤️" * lives_left
                        score = context.chat_data.get('quiz_score', 0)
                        question = context.chat_data.get('current_question_text', '')
                        await query.message.edit_text(f"{quiz_title}\n\n**Xalınız:** {score} ⭐\n**Qalan can:** {lives_text}\n\n**Sual:** {question}", parse_mode='Markdown', reply_markup=query.message.reply_markup)
        return

    elif data in ["start_info_about", "start_info_qaydalar", "back_to_start"]:
        if data == "start_info_about":
            await query.message.edit_text(text=ABOUT_TEXT, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(" geri", callback_data="back_to_start")]]))
        elif data == "start_info_qaydalar":
            await query.message.edit_text(text=RULES_TEXT, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(" geri", callback_data="back_to_start")]]))
        elif data == "back_to_start":
            keyboard = [ [InlineKeyboardButton("ℹ️ Bot Haqqında Məlumat", callback_data="start_info_about")], [InlineKeyboardButton("📜 Bütün Qaydalar", callback_data="start_info_qaydalar")], [InlineKeyboardButton("👥 Oyun Qrupumuz", url="https://t.me/+0z5V-OvEMmgzZTFi")], [InlineKeyboardButton(f"👨‍💻 Admin ilə Əlaqə", url=f"https://t.me/{ADMIN_USERNAME}")] ]
            await query.message.edit_text("Salam! Mən Oyun Botuyam. 🤖\nAşağıdakı menyudan istədiyin bölməni seç:", reply_markup=InlineKeyboardMarkup(keyboard))
        return
        
    elif data.startswith('dc_'):
        game_starter_id = context.chat_data.get('dc_game_starter_id')
        is_admin_check_needed = data in ['dc_select_sade', 'dc_select_premium', 'dc_start_game', 'dc_stop_game', 'dc_next_turn']
        
        if is_admin_check_needed:
            is_admin = await is_user_admin(chat_id, user.id, context)
            if user.id != game_starter_id and not is_admin:
                await query.answer("⛔ Bu düymədən yalnız oyunu başladan şəxs və ya adminlər istifadə edə bilər.", show_alert=True); return

        if data in ['dc_select_sade', 'dc_select_premium']:
            is_premium_choice = (data == 'dc_select_premium')
            if is_premium_choice and not is_user_premium(user.id):
                await query.answer("⛔ Bu rejimi yalnız premium statuslu adminlər başlada bilər.", show_alert=True); return
            context.chat_data.update({'dc_game_active': True, 'dc_is_premium': is_premium_choice, 'dc_players': [], 'dc_current_player_index': -1, 'dc_game_starter_id': user.id})
            await show_dc_registration_message(update, context)
        
        elif data == 'dc_register':
            if not context.chat_data.get('dc_game_active'):
                await query.answer("Artıq aktiv oyun yoxdur.", show_alert=True); return
            players = context.chat_data.get('dc_players', [])
            if any(p['id'] == user.id for p in players):
                await query.answer("Siz artıq qeydiyyatdan keçmisiniz.", show_alert=True)
            else:
                players.append({'id': user.id, 'name': user.first_name})
                await query.answer("Uğurla qoşuldunuz!", show_alert=False)
                await show_dc_registration_message(update, context)

        elif data == 'dc_start_game':
            players = context.chat_data.get('dc_players', [])
            if len(players) < 2:
                await query.answer("⛔ Oyunun başlaması üçün minimum 2 nəfər qeydiyyatdan keçməlidir.", show_alert=True); return
            random.shuffle(players)
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
            else:
                task = random.choice(PREMIUM_DARE_TASKS if is_premium else SADE_DARE_TASKS)
                text_to_show = f"😈 **Cəsarət:**\n\n`{task}`"
            await query.message.edit_text(text_to_show, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Növbəti Oyunçu ➡️", callback_data="dc_next_turn")]]), parse_mode=ParseMode.MARKDOWN)

        elif data == 'dc_next_turn':
            await dc_next_turn(update, context)
        return

    else:
        await query.answer()

async def handle_all_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.chat.type in [ChatType.GROUP, ChatType.SUPERGROUP]: return
    user = update.message.from_user; chat_id = update.message.chat.id
    conn, cur = None, None
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cur = conn.cursor()
        cur.execute("INSERT INTO message_counts (chat_id, user_id, username, message_timestamp) VALUES (%s, %s, %s, %s);", (chat_id, user.id, user.username or user.first_name, datetime.datetime.now(datetime.timezone.utc)))
        conn.commit()
    except Exception as e:
        logger.error(f"Mesajı bazaya yazarkən xəta: {e}")
    finally:
        if cur: cur.close()
        if conn: conn.close()

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
