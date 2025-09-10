import logging
import random
import os
import psycopg2
import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters
from telegram.constants import ChatType

# Logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# --- BAZA İLƏ BAĞLI FUNKSİYALAR ---
DATABASE_URL = os.environ.get("DATABASE_URL")

def init_db():
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS message_counts (
                id SERIAL PRIMARY KEY, chat_id BIGINT NOT NULL, user_id BIGINT NOT NULL,
                username TEXT NOT NULL, message_timestamp TIMESTAMPTZ NOT NULL );
        """)
        conn.commit()
        cur.close()
        conn.close()
        print("Verilənlər bazası cədvəli hazırdır.")
    except Exception as e:
        print(f"Baza yaradılarkən xəta: {e}")

# --- SUAL VƏ TAPŞIRIQ SİYAHILARI ---
NORMAL_TRUTH_QUESTIONS = [
    "Uşaqlıqda ən böyük qorxun nə idi?", "Həyatında ən çox peşman olduğun şey?", "Heç kimin bilmədiyi bir bacarığın varmı?", "Bu qrupda ən çox güvəndiyin insan kimdir?", "Bir günlük görünməz olsaydın nə edərdin?", "Ən çox sevdiyin film hansıdır və niyə?", "Ən utancverici ləqəbin nə olub?", "Valideynlərinə dediyin ən böyük yalan nə olub?", "Heç hovuzun içinə kiçik tualetini etmisən?", "Telefonundakı ən son şəkil nədir? (Düzünü de!)", "Əgər heyvan olsaydın, hansı heyvan olardın və niyə?", "İndiyə qədər aldığın ən pis hədiyyə nə olub?", "Heç kimə demədiyin bir sirrin nədir?", "Qrupdakı birinin yerində olmaq istəsəydin, bu kim olardı?", "Ən qəribə yemək vərdişin nədir?", "Heç sosial media profilini gizlicə izlədiyin (stalk etdiyin) biri olub?", "Səni nə ağlada bilər?", "Bir günə 1 milyon dollar xərcləməli olsaydın, nəyə xərcləyərdin?"
]
NORMAL_DARE_TASKS = [
    "Profil şəklini 1 saatlıq qrupdakı ən son göndərilən şəkil ilə dəyişdir.", "Qrupdakı birinə səsli mesajla mahnı oxu.", "Əlifbanı sondan əvvələ doğru sürətli şəkildə say.", "Otağındakı ən qəribə əşyanın şəklini çəkib qrupa göndər.", "Telefonunun klaviaturasını 10 dəqiqəlik tərs düz (sağdan sola) istifadə et.", "Qrupdakı birinə icazə ver, sənin üçün İnstagram-da bir status paylaşsın.", "Ən yaxın pəncərədən çölə \"Mən robotam!\" deyə qışqır.", "Qrupa telefonunun ekran şəklini (screenshot) göndər.", "Bir qaşıq qəhvə və ya duz ye.", "Növbəti 3 dəqiqə ərzində ancaq şeir dili ilə danış.", "Ən çox zəhlən gedən mahnını qrupa göndər.", "Gözlərin bağlı halda öz portretini çəkməyə çalış və qrupa at.", "Qrupdan birinə zəng et və ona qəribə bir lətifə danış.", "İki fərqli içkini (məsələn, kola və süd) qarışdırıb bir qurtum iç.", "Hər kəsin görə biləcəyi bir yerdə 30 saniyə robot kimi rəqs et.", "Ən son aldığın mesaja \"OK, ancaq əvvəlcə kartofları soy\" deyə cavab yaz."
]

# --- YENİ FUNKSİYA: RÜTBƏ SİSTEMİ ---
def get_rank_title(count: int) -> str:
    """Mesaj sayına görə rütbəni və emojini qaytarır."""
    if count <= 100:
        return "Yeni Üzv 👶"
    elif count <= 500:
        return "Daimi Sakin 👨‍💻"
    elif count <= 1000:
        return "Qrup Söhbətçili 🗣️"
    elif count <= 2500:
        return "Qrup Əfsanəsi 👑"
    else:
        return "Söhbət Tanrısı ⚡️"

# --- XOŞ GƏLDİN VƏ DİGƏR KÖMƏKÇİ FUNKSİYALAR ---
async def welcome_new_members(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ... (kod eyni qalır)
    pass
async def is_user_admin(chat_id: int, user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    # ... (kod eyni qalır)
    pass
async def ask_next_player(chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    # ... (kod eyni qalır)
    pass

# --- ƏSAS ƏMRLƏR (YENİLƏNİB VƏ YENİSİ ƏLAVƏ EDİLİB) ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Salam! 🤖\n\nOyun başlatmaq üçün /oyun yazın.\nMesaj reytinqinə baxmaq üçün /reyting [dövr] yazın.\nÖz rütbənizi görmək üçün /menim_rutbem yazın.")

# YENİ ƏMR
async def my_rank_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """İstifadəçinin şəxsi mesaj sayını və rütbəsini göstərir."""
    user_id = update.message.from_user.id
    user_name = update.message.from_user.first_name
    chat_id = update.message.chat_id

    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cur = conn.cursor()
        query = "SELECT COUNT(*) FROM message_counts WHERE user_id = %s AND chat_id = %s;"
        cur.execute(query, (user_id, chat_id))
        result = cur.fetchone()
        cur.close()
        conn.close()

        total_count = result[0] if result else 0
        rank_title = get_rank_title(total_count)

        await update.message.reply_text(
            f"Salam, {user_name}!\n\n"
            f"Bu qrupdakı ümumi mesaj sayınız: **{total_count}**\n"
            f"Hazırkı rütbəniz: **{rank_title}**"
        , parse_mode='Markdown')

    except Exception as e:
        logger.error(f"Şəxsi rütbə alınarkən xəta: {e}")
        await update.message.reply_text("Rütbənizi hesablayarkən bir xəta baş verdi.")

# YENİLƏNMİŞ ƏMR
async def rating_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ... (kodun əksəriyyəti eyni qalır, sadəcə çıxış dəyişir)
    chat_id = update.message.chat_id
    args = context.args
    if not args:
        await update.message.reply_text("Zəhmət olmasa, dövrü təyin edin:\n`/reyting gunluk`\n`/reyting heftelik`\n`/reyting ayliq`", parse_mode='Markdown')
        return
    
    period = args[0].lower()
    if period == "gunluk": interval, title = "1 day", "Son 24 Saatın Ən Aktiv Üzvləri ☀️"
    elif period == "heftelik": interval, title = "7 days", "Son 7 Günün Ən Aktiv Üzvləri 🗓️"
    elif period == "ayliq": interval, title = "1 month", "Son 30 Günün Ən Aktiv Üzvləri 🌙"
    else:
        await update.message.reply_text("Yanlış dövr. Mümkün seçimlər: gunluk, heftelik, ayliq")
        return

    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cur = conn.cursor()
        query = f"SELECT user_id, username, COUNT(*) as msg_count FROM message_counts WHERE chat_id = %s AND message_timestamp >= NOW() - INTERVAL '{interval}' GROUP BY user_id, username ORDER BY msg_count DESC LIMIT 10;"
        cur.execute(query, (chat_id,))
        results = cur.fetchall()
        cur.close()
        conn.close()

        if not results:
            await update.message.reply_text(f"Bu dövr üçün heç bir mesaj tapılmadı.")
            return

        leaderboard = f"📊 **{title}**\n\n"
        for i, (user_id, username, msg_count) in enumerate(results):
            medal = ""
            if i == 0: medal = "🥇"
            elif i == 1: medal = "🥈"
            elif i == 2: medal = "🥉"
            
            # RÜTBƏNİ ƏLAVƏ EDİRİK
            rank_title = get_rank_title(msg_count)
            
            leaderboard += f"{i+1}. {medal} [{username}](tg://user?id={user_id}) - `{msg_count}` msj ({rank_title})\n"
        
        await update.message.reply_text(leaderboard, parse_mode='Markdown', disable_web_page_preview=True)

    except Exception as e:
        logger.error(f"Reytinq alınarkən xəta: {e}")
        await update.message.reply_text("Reytinq cədvəlini hazırlayarkən bir xəta baş verdi.")

# ... (qalan bütün köhnə funksiyalar olduğu kimi qalır, aşağıdakı tam kodda mövcuddur) ...

def main() -> None:
    # ...
    # YENİ HANDLER ƏLAVƏ EDİLİR
    application.add_handler(CommandHandler("menim_rutbem", my_rank_command, filters=group_filter))
    # ...
