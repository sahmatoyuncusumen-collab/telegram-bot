import logging
import random
import os
import psycopg2
import datetime
import sys
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters
from telegram.constants import ChatType
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

# --- VIKTORINA SUALLARI (GENİŞLƏNDİRİLMİŞ BAZA) ---
SADE_QUIZ_QUESTIONS = [
    # Köhnə 20 sual
    {'question': 'İkinci Dünya Müharibəsi hansı ildə başlamışdır?', 'options': ['1935', '1939', '1941', '1945'], 'correct': '1939'},
    {'question': 'Qədim Misirdə hökmdarlar necə adlanırdı?', 'options': ['İmperator', 'Sultan', 'Firon', 'Kral'], 'correct': 'Firon'},
    {'question': 'Amerikanı kim kəşf etmişdir?', 'options': ['Vasco da Gama', 'Ferdinand Magellan', 'Xristofor Kolumb', 'James Cook'], 'correct': 'Xristofor Kolumb'},
    {'question': 'Roma İmperiyasının ilk imperatoru kim olmuşdur?', 'options': ['Yuli Sezar', 'Oktavian Avqust', 'Neron', 'Mark Antoni'], 'correct': 'Oktavian Avqust'},
    {'question': 'Azərbaycan Xalq Cümhuriyyəti neçənci ildə qurulmuşdur?', 'options': ['1920', '1918', '1991', '1905'], 'correct': '1918'},
    {'question': 'Aşağıdakılardan hansı məməli heyvan deyil?', 'options': ['Balina', 'Yarasa', 'Pinqvin', 'Delfin'], 'correct': 'Pinqvin'},
    {'question': 'İnsanın bədənində neçə sümük var?', 'options': ['186', '206', '226', '256'], 'correct': '206'},
    {'question': 'Günəş sistemində Günəşə ən yaxın planet hansıdır?', 'options': ['Venera', 'Mars', 'Merkuri', 'Yer'], 'correct': 'Merkuri'},
    {'question': 'Kimyəvi elementlərin dövri sistem cədvəlini kim yaratmışdır?', 'options': ['İsaak Nyuton', 'Albert Eynşteyn', 'Dmitri Mendeleyev', 'Mariya Küri'], 'correct': 'Dmitri Mendeleyev'},
    {'question': 'Qravitasiya (cazibə qüvvəsi) qanununu kim kəşf etmişdir?', 'options': ['Qalileo Qaliley', 'İsaak Nyuton', 'Nikola Tesla', 'Arximed'], 'correct': 'İsaak Nyuton'},
    {'question': 'İlk uğurlu təyyarəni kimlər icad etmişdir?', 'options': ['Lumiere qardaşları', 'Wright qardaşları', 'Montgolfier qardaşları', 'Grimm qardaşları'], 'correct': 'Wright qardaşları'},
    {'question': '"Facebook" sosial şəbəkəsinin qurucusu kimdir?', 'options': ['Bill Gates', 'Steve Jobs', 'Larry Page', 'Mark Zuckerberg'], 'correct': 'Mark Zuckerberg'},
    {'question': 'Hansı şirkət "Windows" əməliyyat sistemini hazırlayır?', 'options': ['Apple', 'Google', 'Microsoft', 'IBM'], 'correct': 'Microsoft'},
    {'question': 'Telefonu kim icad etmişdir?', 'options': ['Tomas Edison', 'Nikola Tesla', 'Aleksandr Bell', 'Samuel Morze'], 'correct': 'Aleksandr Bell'},
    {'question': 'Kompüterdə məlumatın ən kiçik ölçü vahidi nədir?', 'options': ['Bayt', 'Bit', 'Meqabayt', 'Geqabayt'], 'correct': 'Bit'},
    {'question': 'Futbol üzrə Dünya Çempionatı neçə ildən bir keçirilir?', 'options': ['2', '3', '4', '5'], 'correct': '4'},
    {'question': 'Olimpiya oyunlarının simvolu olan halqaların sayı neçədir?', 'options': ['4', '5', '6', '7'], 'correct': '5'},
    {'question': '"Dəmir Mayk" ləqəbli məşhur boksçu kimdir?', 'options': ['Məhəmməd Əli', 'Mayk Tayson', 'Floyd Mayweather', 'Rokki Marçiano'], 'correct': 'Mayk Tayson'},
    {'question': 'Basketbolda bir komanda meydanda neçə oyunçu ilə təmsil olunur?', 'options': ['5', '6', '7', '11'], 'correct': '5'},
    {'question': 'Ən çox "Qızıl Top" (Ballon d\'Or) mükafatını kim qazanıb?', 'options': ['Kriştiano Ronaldo', 'Lionel Messi', 'Mişel Platini', 'Yohan Kroyf'], 'correct': 'Lionel Messi'},
    
    # Yeni 20 sual
    {'question': 'Hansı ölkə "Gündoğan ölkə" kimi tanınır?', 'options': ['Çin', 'Hindistan', 'Yaponiya', 'Vyetnam'], 'correct': 'Yaponiya'},
    {'question': 'Leonardo da Vinçi hansı ölkədə anadan olub?', 'options': ['Fransa', 'İspaniya', 'Yunanıstan', 'İtaliya'], 'correct': 'İtaliya'},
    {'question': 'İlk insan Aya neçənci ildə ayaq basıb?', 'options': ['1965', '1969', '1972', '1961'], 'correct': '1969'},
    {'question': 'Azadlıq Heykəli ABŞ-a hansı ölkə tərəfindən hədiyyə edilib?', 'options': ['Böyük Britaniya', 'Almaniya', 'Fransa', 'İspaniya'], 'correct': 'Fransa'},
    {'question': 'Hansı şəhər su üzərində qurulub?', 'options': ['Florensiya', 'Verona', 'Roma', 'Venesiya'], 'correct': 'Venesiya'},
    {'question': 'Hansı okean dünyanın ən böyüyüdür?', 'options': ['Atlantik Okeanı', 'Hind Okeanı', 'Sakit Okean', 'Şimal Buzlu Okeanı'], 'correct': 'Sakit Okean'},
    {'question': 'Bir ildə neçə gün var (uzun il nəzərə alınmır)?', 'options': ['360', '365', '355', '370'], 'correct': '365'},
    {'question': 'İnsan bədəninin ən böyük orqanı hansıdır?', 'options': ['Qaraciyər', 'Ağciyərlər', 'Beyin', 'Dəri'], 'correct': 'Dəri'},
    {'question': 'Yer kürəsi öz oxu ətrafında tam bir dövrəni nə qədər vaxta başa vurur?', 'options': ['12 saat', '36 saat', '24 saat', '48 saat'], 'correct': '24 saat'},
    {'question': 'Havanın əsas tərkib hissəsi hansı qazdır?', 'options': ['Oksigen', 'Karbon qazı', 'Azot', 'Hidrogen'], 'correct': 'Azot'},
    {'question': 'Hansı sosial şəbəkənin loqosu quş şəklindədir?', 'options': ['Facebook', 'Instagram', 'Twitter (X)', 'LinkedIn'], 'correct': 'Twitter (X)'},
    {'question': '"iPhone" smartfonlarını hansı şirkət istehsal edir?', 'options': ['Samsung', 'Google', 'Apple', 'Huawei'], 'correct': 'Apple'},
    {'question': 'Klaviatura üzərində ən uzun düymə hansıdır?', 'options': ['Enter', 'Shift', 'Space (Boşluq)', 'Caps Lock'], 'correct': 'Space (Boşluq)'},
    {'question': 'URL-də "www" nə deməkdir?', 'options': ['World Wide Web', 'Web World Wide', 'World Web Wide', 'Wide World Web'], 'correct': 'World Wide Web'},
    {'question': 'PDF formatının tam adı nədir?', 'options': ['Portable Document Format', 'Printable Document File', 'Personal Data File', 'Public Document Format'], 'correct': 'Portable Document Format'},
    {'question': 'Futbolda bir komandada neçə oyunçu olur?', 'options': ['9', '10', '11', '12'], 'correct': '11'},
    {'question': 'Hansı idman növündə topu səbətə atmaq lazımdır?', 'options': ['Voleybol', 'Həndbol', 'Basketbol', 'Su polosu'], 'correct': 'Basketbol'},
    {'question': 'Şahmatda ən güclü fiqur hansıdır?', 'options': ['At', 'Fil', 'Vəzir', 'Top'], 'correct': 'Vəzir'},
    {'question': 'ABŞ-ın milli idman növü nə hesab olunur?', 'options': ['Basketbol', 'Reqbi', 'Beysbol', 'Amerika futbolu'], 'correct': 'Beysbol'},
    {'question': 'Hansı ölkə futbol üzrə ən çox Dünya Çempionu olub?', 'options': ['Almaniya', 'İtaliya', 'Argentina', 'Braziliya'], 'correct': 'Braziliya'},
]

PREMIUM_QUIZ_QUESTIONS = [
    # Köhnə 20 sual
    {'question': 'Tarixdə "Atilla" adı ilə tanınan hökmdar hansı imperiyanı idarə edirdi?', 'options': ['Roma İmperiyası', 'Hun İmperiyası', 'Monqol İmperiyası', 'Osmanlı İmperiyası'], 'correct': 'Hun İmperiyası'},
    {'question': '100 illik müharibə hansı iki dövlət arasında olmuşdur?', 'options': ['İngiltərə və Fransa', 'İspaniya və Portuqaliya', 'Roma və Karfagen', 'Prussiya və Avstriya'], 'correct': 'İngiltərə və Fransa'},
    {'question': 'Troya müharibəsi haqqında məlumat verən Homerin məşhur əsəri hansıdır?', 'options': ['Odisseya', 'Teoqoniya', 'İliada', 'Eneida'], 'correct': 'İliada'},
    {'question': 'Berlin divarı neçənci ildə yıxılmışdır?', 'options': ['1985', '1989', '1991', '1993'], 'correct': '1989'},
    {'question': 'Səfəvi dövlətinin banisi kimdir?', 'options': ['Şah Abbas', 'Sultan Hüseyn', 'Şah İsmayıl Xətai', 'Nadir Şah'], 'correct': 'Şah İsmayıl Xətai'},
    {'question': 'Eynşteynin məşhur Nisbilik Nəzəriyyəsinin düsturu hansıdır?', 'options': ['F=ma', 'E=mc²', 'a²+b²=c²', 'V=IR'], 'correct': 'E=mc²'},
    {'question': 'İnsan DNT-si neçə xromosomdan ibarətdir?', 'options': ['23 cüt (46)', '21 cüt (42)', '25 cüt (50)', '32 cüt (64)'], 'correct': '23 cüt (46)'},
    {'question': 'İlk dəfə Aya ayaq basan insan kimdir?', 'options': ['Yuri Qaqarin', 'Con Glenn', 'Maykl Kollins', 'Nil Armstronq'], 'correct': 'Nil Armstronq'},
    {'question': 'Hansı kimyəvi elementin simvolu "Au"-dur?', 'options': ['Gümüş', 'Mis', 'Qızıl', 'Dəmir'], 'correct': 'Qızıl'},
    {'question': 'Çernobıl AES-də qəza neçənci ildə baş vermişdir?', 'options': ['1982', '1986', '1988', '1991'], 'correct': '1986'},
    {'question': '"World Wide Web" (WWW) konsepsiyasını kim yaratmışdır?', 'options': ['Steve Jobs', 'Linus Torvalds', 'Tim Berners-Lee', 'Vint Cerf'], 'correct': 'Tim Berners-Lee'},
    {'question': 'İlk kosmik peyk olan "Sputnik 1" hansı ölkə tərəfindən orbitə buraxılmışdır?', 'options': ['ABŞ', 'Çin', 'SSRİ', 'Böyük Britaniya'], 'correct': 'SSRİ'},
    {'question': 'Kriptovalyuta olan Bitcoin-in yaradıcısının ləqəbi nədir?', 'options': ['Vitalik Buterin', 'Satoshi Nakamoto', 'Elon Musk', 'Charlie Lee'], 'correct': 'Satoshi Nakamoto'},
    {'question': 'Hansı proqramlaşdırma dili Google tərəfindən yaradılmışdır?', 'options': ['Swift', 'Kotlin', 'Go', 'Rust'], 'correct': 'Go'},
    {'question': 'Kompüter elmlərində "Turing maşını" nəzəriyyəsini kim irəli sürmüşdür?', 'options': ['Con fon Neyman', 'Alan Turinq', 'Ada Lavleys', 'Çarlz Bebbic'], 'correct': 'Alan Turinq'},
    {'question': 'Ağır atletika üzrə 3 qat Olimpiya, 5 qat Dünya və 10 qat Avropa çempionu olmuş "Cib Heraklisi" ləqəbli türk idmançı kimdir?', 'options': ['Halil Mutlu', 'Naim Süleymanoğlu', 'Taner Sağır', 'Hafiz Süleymanoğlu'], 'correct': 'Naim Süleymanoğlu'},
    {'question': '"Formula 1" tarixində ən çox yarış qazanan pilot kimdir?', 'options': ['Mixael Şumaxer', 'Sebastian Vettel', 'Ayrton Senna', 'Lüis Hemilton'], 'correct': 'Lüis Hemilton'},
    {'question': 'Şahmatda "Sitsiliya müdafiəsi" hansı gedişlə başlayır?', 'options': ['1. e4 c5', '1. d4 Nf6', '1. e4 e5', '1. c4 e5'], 'correct': '1. e4 c5'},
    {'question': 'Bir marafon yarışının rəsmi məsafəsi nə qədərdir?', 'options': ['26.2 km', '42.195 km', '50 km', '35.5 km'], 'correct': '42.195 km'},
    {'question': 'Tennisdə "Böyük Dəbilqə" (Grand Slam) turnirlərinə hansı daxil deyil?', 'options': ['Uimbldon', 'ABŞ Açıq', 'Fransa Açıq (Roland Garros)', 'Indian Wells Masters'], 'correct': 'Indian Wells Masters'},
    
    # Yeni 60 sual
    {'question': 'Janna d`Ark 100 illik müharibədə hansı ölkə üçün vuruşurdu?', 'options': ['İngiltərə', 'Fransa', 'İspaniya', 'Müqəddəs Roma İmperiyası'], 'correct': 'Fransa'},
    {'question': 'Böyük Çin Səddi hansı məqsədlə tikilmişdir?', 'options': ['Ticarət yolunu qorumaq', 'Seldən qorunmaq', 'Köçəri tayfaların hücumlarından qorunmaq', 'İmperatorun sarayını qorumaq'], 'correct': 'Köçəri tayfaların hücumlarından qorunmaq'},
    {'question': 'Qədim Spartada sağlam olmayan körpələr hansı dağdan atılırdı?', 'options': ['Olimp dağı', 'Parnas dağı', 'Tayget dağı', 'Pindus dağı'], 'correct': 'Tayget dağı'},
    {'question': 'ABŞ-da köləliyi ləğv edən 13-cü düzəlişi hansı prezident imzalamışdır?', 'options': ['Corc Vaşinqton', 'Tomas Cefferson', 'Abraham Linkoln', 'Franklin Ruzvelt'], 'correct': 'Abraham Linkoln'},
    {'question': 'Vikinqlər əsasən hansı regiondan dünyaya yayılmışdılar?', 'options': ['Aralıq dənizi', 'Skandinaviya', 'Balkanlar', 'Britaniya adaları'], 'correct': 'Skandinaviya'},
    {'question': 'Monqol imperiyasının qurucusu kimdir?', 'options': ['Atilla', 'Batı xan', 'Çingiz xan', 'Əmir Teymur'], 'correct': 'Çingiz xan'},
    {'question': 'Hansı sülh müqaviləsi Birinci Dünya Müharibəsini rəsmən bitirmişdir?', 'options': ['Yalta müqaviləsi', 'Versal sülh müqaviləsi', 'Potsdam müqaviləsi', 'Brest-Litovsk sülhü'], 'correct': 'Versal sülh müqaviləsi'},
    {'question': '"Dəmir Ledi" ləqəbi ilə tanınan Böyük Britaniyanın baş naziri kim olmuşdur?', 'options': ['Kraliça Viktoriya', 'Marqaret Tetçer', 'Tereza Mey', 'İndira Qandi'], 'correct': 'Marqaret Tetçer'},
    {'question': 'Qədim Romada senatın toplandığı əsas forum necə adlanırdı?', 'options': ['Kolizey', 'Panteon', 'Roma Forumu', 'Kapitoli təpəsi'], 'correct': 'Roma Forumu'},
    {'question': 'Xirosimaya atılan atom bombasının adı nə idi?', 'options': ['"Fat Man"', '"Little Boy"', '"Tsar Bomba"', '"Trinity"'], 'correct': '"Little Boy"'},
    {'question': 'Babək hansı xilafətə qarşı mübarizə aparmışdır?', 'options': ['Əməvilər', 'Abbasilər', 'Osmanlılar', 'Fatimilər'], 'correct': 'Abbasilər'},
    {'question': 'Məşhur "İpək Yolu" ticarət marşrutu hansı iki sivilizasiyanı birləşdirirdi?', 'options': ['Roma və Misir', 'Yunanıstan və Hindistan', 'Çin və Aralıq dənizi', 'Farslar və Hindistan'], 'correct': 'Çin və Aralıq dənizi'},
    {'question': 'Kristofer Kolumbun gəmilərindən birinin adı nə idi?', 'options': ['Mayflower', 'Viktoriya', 'Santa Mariya', 'Endeavour'], 'correct': 'Santa Mariya'},
    {'question': '"Qarabağ" FK UEFA Avropa Liqasının qrup mərhələsinə ilk dəfə neçənci ildə vəsiqə qazanıb?', 'options': ['2009', '2011', '2014', '2017'], 'correct': '2014'},
    {'question': 'Osmanlı Sultanı Fateh Sultan Mehmet İstanbulu neçənci ildə fəth etmişdir?', 'options': ['1451', '1453', '1461', '1481'], 'correct': '1453'},
    {'question': 'Mariana çökəkliyi hansı okeanda yerləşir?', 'options': ['Atlantik', 'Hind', 'Şimal Buzlu', 'Sakit'], 'correct': 'Sakit'},
    {'question': 'İnsanın eşitmə diapazonundan daha yüksək tezlikli səslər necə adlanır?', 'options': ['İnfrasəs', 'Rezonans', 'Ultrasəs', 'Subsonik'], 'correct': 'Ultrasəs'},
    {'question': 'Hansı alim ilk dəfə radioaktivliyi kəşf etmişdir?', 'options': ['Mariya Küri', 'Anri Bekkerel', 'Ernest Rezerford', 'Nils Bor'], 'correct': 'Anri Bekkerel'},
    {'question': 'Qırmızı qan hüceyrələrinə rəngini verən dəmir tərkibli zülal hansıdır?', 'options': ['Mioqlobin', 'Albumin', 'Hemoqlobin', 'Fibrinogen'], 'correct': 'Hemoqlobin'},
    {'question': 'Normal atmosfer təzyiqində su neçə dərəcə Selsidə qaynayır?', 'options': ['90°C', '100°C', '110°C', '120°C'], 'correct': '100°C'},
    {'question': 'Yerdən görünən ən parlaq ulduz hansıdır (Günəş istisna olmaqla)?', 'options': ['Qütb ulduzu', 'Sirius', 'Vega', 'Betelgeyze'], 'correct': 'Sirius'},
    {'question': 'Kimya elmində pH şkalası nəyi ölçmək üçün istifadə olunur?', 'options': ['Temperaturu', 'Təzyiqi', 'Turşuluq və qələviliyi', 'Sıxlığı'], 'correct': 'Turşuluq və qələviliyi'},
    {'question': 'Yerin maqnit sahəsi bizi nədən qoruyur?', 'options': ['Meteoritlərdən', 'Günəş küləyindən', 'Ultrabənövşəyi şüalardan', 'Soyuq kosmosdan'], 'correct': 'Günəş küləyindən'},
    {'question': 'Hansı planetin peyki olan Titanın sıx atmosferi var?', 'options': ['Yupiter', 'Mars', 'Uran', 'Saturn'], 'correct': 'Saturn'},
    {'question': 'Albert Eynşteyn Nobel mükafatını hansı kəşfinə görə almışdır?', 'options': ['Nisbilik nəzəriyyəsi', 'Fotoelektrik effekti', 'Brown hərəkəti', 'E=mc²'], 'correct': 'Fotoelektrik effekti'},
    {'question': 'Canlı orqanizmləri öyrənən elm sahəsi necə adlanır?', 'options': ['Kimya', 'Fizika', 'Geologiya', 'Biologiya'], 'correct': 'Biologiya'},
    {'question': 'Pi (π) ədədinin təxmini qiyməti nə qədərdir?', 'options': ['2.71', '1.61', '3.14', '9.81'], 'correct': '3.14'},
    {'question': 'Süni şəkildə yaradılmış ilk kimyəvi element hansıdır?', 'options': ['Plutonium', 'Texnesium', 'Prometium', 'Neptunium'], 'correct': 'Texnesium'},
    {'question': 'Təkamül nəzəriyyəsini "Növlərin Mənşəyi" kitabında irəli sürən alim kimdir?', 'options': ['Qreqor Mendel', 'Alfred Uolles', 'Jan-Batist Lamark', 'Çarlz Darvin'], 'correct': 'Çarlz Darvin'},
    {'question': 'Halley kometası Yer kürəsindən təxminən neçə ildən bir görünür?', 'options': ['25-26 il', '50-51 il', '75-76 il', '100-101 il'], 'correct': '75-76 il'},
    {'question': '"Ethernet" nə üçün istifadə olunan bir texnologiyadır?', 'options': ['Simsiz internet', 'Naqilli lokal şəbəkə (LAN)', 'Bluetooth', 'Mobil rabitə'], 'correct': 'Naqilli lokal şəbəkə (LAN)'},
    {'question': 'Hansı şirkət ilk "Walkman" portativ kaset pleyerini istehsal etmişdir?', 'options': ['Panasonic', 'Sony', 'Philips', 'Aiwa'], 'correct': 'Sony'},
    {'question': 'Kompüter klaviaturasının standart düzülüşü necə adlanır?', 'options': ['AZERTY', 'QWERTY', 'DVORAK', 'COLEMAK'], 'correct': 'QWERTY'},
    {'question': 'Hansı texnologiya iki cihaz arasında qısa məsafəli simsiz rabitə üçün istifadə olunur?', 'options': ['NFC', 'Wi-Fi', 'GPS', 'LTE'], 'correct': 'NFC'},
    {'question': '"Virtual Reality" (VR) nə deməkdir?', 'options': ['Genişləndirilmiş Reallıq', 'Süni İntellekt', 'Sanal Reallıq', 'Maşın Təlimi'], 'correct': 'Sanal Reallıq'},
    {'question': 'İlk video paylaşım saytı olan YouTube neçənci ildə yaradılıb?', 'options': ['2003', '2005', '2007', '2009'], 'correct': '2005'},
    {'question': '3D printerin iş prinsipi nəyə əsaslanır?', 'options': ['Materialı kəsməyə', 'Materialı əritməyə', 'Materialı qat-qat əlavə etməyə', 'Materialı pressləməyə'], 'correct': 'Materialı qat-qat əlavə etməyə'},
    {'question': 'İstifadəçiyə saxta e-poçt göndərərək həssas məlumatları (şifrə, kart nömrəsi) oğurlama cəhdi necə adlanır?', 'options': ['Virus', 'Spam', 'Fişinq', 'Troyan'], 'correct': 'Fişinq'},
    {'question': 'C++ proqramlaşdırma dilinin yaradıcısı kimdir?', 'options': ['Dennis Ritçi', 'Ceyms Qoslinq', 'Byarne Stroustrup', 'Qvido van Rossum'], 'correct': 'Byarne Stroustrup'},
    {'question': 'Hansı cihaz alternativ cərəyanı (AC) sabit cərəyana (DC) çevirir?', 'options': ['Transformator', 'Generator', 'Düzləndirici (Rectifier)', 'İnverter'], 'correct': 'Düzləndirici (Rectifier)'},
    {'question': '"CAPTCHA" testlərinin əsas məqsədi nədir?', 'options': ['Saytın sürətini yoxlamaq', 'İstifadəçinin yaşını təyin etmək', 'İstifadəçinin insan olduğunu təsdiqləmək', 'Reklam göstərmək'], 'correct': 'İstifadəçinin insan olduğunu təsdiqləmək'},
    {'question': 'Bulud texnologiyaları (Cloud Computing) nəyi ifadə edir?', 'options': ['Hava proqnozu modelləşdirməsi', 'Kompüterdə faylların saxlanması', 'İnternet üzərindən server xidmətlərindən istifadə', 'Simsiz enerji ötürülməsi'], 'correct': 'İnternet üzərindən server xidmətlərindən istifadə'},
    {'question': 'Hansı şirkət "PlayStation" oyun konsolunu istehsal edir?', 'options': ['Nintendo', 'Microsoft', 'Sega', 'Sony'], 'correct': 'Sony'},
    {'question': 'Açıq mənbəli proqram təminatı nə deməkdir?', 'options': ['Pulsuz proqram', 'İstifadəsi asan proqram', 'Mənbə kodu hər kəsə açıq olan proqram', 'Reklamsız proqram'], 'correct': 'Mənbə kodu hər kəsə açıq olan proqram'},
    {'question': 'Kompüterə qoşulan xarici cihazları idarə edən proqram təminatı necə adlanır?', 'options': ['Əməliyyat sistemi', 'Drayver', 'Utilit', 'Tətbiqi proqram'], 'correct': 'Drayver'},
    {'question': 'Futbol tarixində yeganə qapıçı olaraq "Qızıl Top" mükafatını kim qazanıb?', 'options': ['Canluici Buffon', 'Oliver Kan', 'Lev Yaşin', 'İker Kasilyas'], 'correct': 'Lev Yaşin'},
    {'question': 'Hansı şəhər daha çox Yay Olimpiya Oyunlarına ev sahibliyi edib?', 'options': ['Afina', 'Paris', 'London', 'Los Anceles'], 'correct': 'London'},
    {'question': '"Qarabağ" FK öz ev oyunlarını hazırda hansı stadionda keçirir?', 'options': ['Tofiq Bəhramov adına Respublika Stadionu', 'Bakı Olimpiya Stadionu', 'Dalğa Arena', 'Azərsun Arena'], 'correct': 'Tofiq Bəhramov adına Respublika Stadionu'},
    {'question': 'Maykl Cordan karyerasının böyük hissəsini hansı NBA komandasında keçirib?', 'options': ['Los Angeles Lakers', 'Boston Celtics', 'Chicago Bulls', 'New York Knicks'], 'correct': 'Chicago Bulls'},
    {'question': 'Hansı idman növü "Kralların İdmanı" adlandırılır?', 'options': ['Futbol', 'Şahmat', 'At yarışı', 'Qolf'], 'correct': 'At yarışı'},
    {'question': 'Bir futbol oyununun standart müddəti nə qədərdir (əlavə vaxt nəzərə alınmır)?', 'options': ['80 dəqiqə', '90 dəqiqə', '100 dəqiqə', '120 dəqiqə'], 'correct': '90 dəqiqə'},
    {'question': 'Üsain Bolt 100 metr məsafəyə qaçışda dünya rekordunu hansı nəticə ilə müəyyənləşdirib?', 'options': ['9.69 s', '9.58 s', '9.72 s', '9.63 s'], 'correct': '9.58 s'},
    {'question': 'Hansı komanda ən çox UEFA Çempionlar Liqası kubokunu qazanıb?', 'options': ['Barselona', 'Milan', 'Bavariya Münhen', 'Real Madrid'], 'correct': 'Real Madrid'},
    {'question': 'Hokkeydə oyun hansı cisimlə oynanılır?', 'options': ['Top', 'Şayba', 'Disk', 'Kürə'], 'correct': 'Şayba'},
    {'question': 'Məhəmməd Əli məşhur "Rumble in the Jungle" döyüşündə kimə qalib gəlmişdir?', 'options': ['Sonny Liston', 'Joe Frazier', 'George Foreman', 'Ken Norton'], 'correct': 'George Foreman'},
    {'question': 'Krallıq yürüşü (checkers) və şahmat eyni taxtada oynanılırmı?', 'options': ['Bəli', 'Xeyr', 'Krallıq yürüşünün taxtası daha böyükdür', 'Şahmat taxtası daha böyükdür'], 'correct': 'Bəli'},
    {'question': '"New Zealand All Blacks" hansı idman növü üzrə məşhur milli komandadır?', 'options': ['Futbol', 'Kriket', 'Reqbi', 'Basketbol'], 'correct': 'Reqbi'},
    {'question': 'Yelena İsinbayeva hansı yüngül atletika növündə dünya rekordçusu idi?', 'options': ['Hündürlüyə tullanma', 'Üçtəkanla tullanma', 'Şüvüllə tullanma', 'Uzunluğa tullanma'], 'correct': 'Şüvüllə tullanma'},
    {'question': 'Snuker oyununda ən yüksək xal verən rəngli top hansıdır?', 'options': ['Mavi', 'Çəhrayı', 'Qara', 'Sarı'], 'correct': 'Qara'},
    {'question': 'Hansı döyüş sənəti "yumşaq yol" mənasını verir?', 'options': ['Karate', 'Taekvondo', 'Cüdo', 'Kunq-fu'], 'correct': 'Cüdo'},
]

# --- KÖMƏKÇİ FUNKSİYALAR ---
def get_rank_title(count: int) -> str:
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
    user = update.message.from_user; chat_id = update.message.chat_id; message_count = 0
    conn, cur = None, None
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cur = conn.cursor()
        cur.execute( "SELECT COUNT(*) FROM message_counts WHERE user_id = %s AND chat_id = %s;", (user.id, chat_id) )
        result = cur.fetchone()
        if result: message_count = result[0]
    except Exception as e:
        logger.error(f"Rütbə yoxlanarkən xəta: {e}")
        await update.message.reply_text("❌ Rütbənizi yoxlayarkən xəta baş verdi.")
        return
    finally:
        if cur: cur.close()
        if conn: conn.close()
    rank_title = get_rank_title(message_count)
    reply_text = (f"📊 **Sənin Statistikaların, {user.first_name}!**\n\n"
                  f"💬 Bu qrupdakı ümumi mesaj sayın: **{message_count}**\n"
                  f"🏆 Rütbən: **{rank_title}**\n\n"
                  "Daha çox mesaj yazaraq yeni rütbələr qazan!")
    await update.message.reply_text(reply_text, parse_mode='Markdown')

async def zer_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    dice_roll = random.randint(1, 6)
    await update.message.reply_text(f"🎲 Zər atıldı və düşən rəqəm: **{dice_roll}**", parse_mode='Markdown')

# --- ADMİN ƏMRLƏRİ ---
async def add_premium_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != BOT_OWNER_ID:
        await update.message.reply_text("⛔ Bu əmrdən yalnız bot sahibi istifadə edə bilər.")
        return
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
        await update.message.reply_text("⛔ Bu əmrdən yalnız bot sahibi istifadə edə bilər.")
        return
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
        await update.message.reply_text("Artıq aktiv bir viktorina var!")
        return
        
    context.chat_data['quiz_starter_id'] = update.message.from_user.id
    
    keyboard = [ [InlineKeyboardButton("Viktorina (Sadə) 🌱", callback_data="viktorina_sade")], [InlineKeyboardButton("Viktorina (Premium) 👑", callback_data="viktorina_premium")] ]
    await update.message.reply_text(f"Salam, {update.message.from_user.first_name}! Zəhmət olmasa, viktorina növünü seçin:", reply_markup=InlineKeyboardMarkup(keyboard))

async def ask_next_quiz_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if hasattr(update, 'callback_query') and update.callback_query: message = update.callback_query.message
    else: message = update.message
    is_premium = context.chat_data.get('quiz_is_premium', False)
    question_pool = PREMIUM_QUIZ_QUESTIONS if is_premium else SADE_QUIZ_QUESTIONS
    if not question_pool: await message.edit_text("Bu kateqoriya üçün heç bir sual tapılmadı."); return
    recently_asked = context.chat_data.get('recently_asked_quiz', deque(maxlen=100))
    possible_questions = [q for q in question_pool if q['question'] not in recently_asked]
    if not possible_questions: possible_questions = question_pool; recently_asked.clear()
    question_data = random.choice(possible_questions)
    recently_asked.append(question_data['question'])
    context.chat_data['recently_asked_quiz'] = recently_asked
    question, correct_answer, options = question_data['question'], question_data['correct'], list(question_data['options'])
    random.shuffle(options)
    context.chat_data['correct_quiz_answer'] = correct_answer
    context.chat_data['current_question_text'] = question
    
    keyboard = [[InlineKeyboardButton(option, callback_data=f"quiz_{option}")] for option in options]
    keyboard.append([InlineKeyboardButton("Oyunu Bitir ⏹️", callback_data="quiz_stop")])
    quiz_title = "Premium Viktorina 👑" if is_premium else "Sadə Viktorina 🌱"
    lives_text = "❤️" * context.chat_data.get('quiz_lives', 3)
    score = context.chat_data.get('quiz_score', 0)
    await message.edit_text(
        f"{quiz_title}\n\n" f"**Xalınız:** {score} ⭐\n" f"**Qalan can:** {lives_text}\n\n" f"**Sual:** {question}",
        parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard)
    )
    
# DÜYMƏLƏRİ VƏ MESAJLARI İDARƏ EDƏN FUNKSİYALAR
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; user = query.from_user; data = query.data
    await query.answer()

    if data.startswith("viktorina_") or data.startswith("quiz_"):
        quiz_starter_id = context.chat_data.get('quiz_starter_id')
        if quiz_starter_id and user.id != quiz_starter_id:
            await query.answer("⛔ Bu, sizin başlatdığınız oyun deyil.", show_alert=True)
            return

    if data == "start_info_about":
        await query.message.edit_text(text=ABOUT_TEXT, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(" geri", callback_data="back_to_start")]]))
    elif data == "start_info_qaydalar":
        await query.message.edit_text(text=RULES_TEXT, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(" geri", callback_data="back_to_start")]]))
    elif data == "back_to_start":
        keyboard = [ [InlineKeyboardButton("ℹ️ Bot Haqqında Məlumat", callback_data="start_info_about")], [InlineKeyboardButton("📜 Bütün Qaydalar", callback_data="start_info_qaydalar")], [InlineKeyboardButton("👥 Oyun Qrupumuz", url="https://t.me/+0z5V-OvEMmgzZTFi")], [InlineKeyboardButton(f"👨‍💻 Admin ilə Əlaqə", url=f"https://t.me/{ADMIN_USERNAME}")] ]
        await query.message.edit_text("Salam! Mən Oyun Botuyam. 🤖\nAşağıdakı menyudan istədiyin bölməni seç:", reply_markup=InlineKeyboardMarkup(keyboard))
    elif data == 'viktorina_sade' or data == 'viktorina_premium':
        is_premium_choice = (data == 'viktorina_premium')
        if is_premium_choice and not is_user_premium(user.id):
            await query.message.edit_text(f"⛔ Bu funksiya yalnız premium istifadəçilər üçündür.\n\nPremium status əldə etmək üçün bot sahibi ilə əlaqə saxlayın: [Admin](https://t.me/{ADMIN_USERNAME})", parse_mode='Markdown')
            return
        context.chat_data.clear()
        context.chat_data.update({ 'quiz_active': True, 'quiz_is_premium': is_premium_choice, 'quiz_lives': 3, 'quiz_score': 0, 'quiz_message_id': query.message.message_id, 'quiz_starter_id': user.id })
        await ask_next_quiz_question(update, context)
    elif context.chat_data.get('quiz_active'):
        if data == 'quiz_stop':
            score = context.chat_data.get('quiz_score', 0)
            await query.message.edit_text(f"Oyun dayandırıldı! ✅\n\nSizin yekun xalınız: **{score}** ⭐\n\nYeni oyun üçün /viktorina yazın.", parse_mode='Markdown')
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
                    await query.message.edit_text(f"Canlarınız bitdi və oyun başa çatdı! 😔\n\nDüzgün cavab: **{correct_answer}**\nSizin yekun xalınız: **{score}** ⭐\n\nYeni oyun üçün /viktorina yazın.", parse_mode='Markdown')
                    context.chat_data.clear()
                else:
                    is_premium = context.chat_data.get('quiz_is_premium', False)
                    quiz_title = "Premium Viktorina 👑" if is_premium else "Sadə Viktorina 🌱"
                    lives_text = "❤️" * lives_left
                    score = context.chat_data.get('quiz_score', 0)
                    question = context.chat_data.get('current_question_text', '')
                    await query.message.edit_text(
                        f"{quiz_title}\n\n"
                        f"**Xalınız:** {score} ⭐\n"
                        f"**Qalan can:** {lives_text}\n\n"
                        f"**Sual:** {question}",
                        parse_mode='Markdown', reply_markup=query.message.reply_markup
                    )
    else:
        await query.answer("Bu oyun artıq bitib.", show_alert=True)

async def handle_all_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.chat.type in [ChatType.GROUP, ChatType.SUPERGROUP]: return
    user = update.message.from_user; chat_id = update.message.chat_id
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
        BotCommand("zer", "1-6 arası zər atmaq")
    ]
    
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("qaydalar", qaydalar_command))
    application.add_handler(CommandHandler("haqqinda", haqqinda_command))
    application.add_handler(CommandHandler("menim_rutbem", my_rank_command))
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
