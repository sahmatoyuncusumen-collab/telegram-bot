import logging
import random
import os
import psycopg2
import datetime
import sys
import asyncio
import re
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand, ChatPermissions
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
WARN_LIMIT = 3

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
        cur.execute("CREATE TABLE IF NOT EXISTS filtered_words (id SERIAL PRIMARY KEY, chat_id BIGINT NOT NULL, word TEXT NOT NULL, UNIQUE(chat_id, word));")
        cur.execute("CREATE TABLE IF NOT EXISTS warnings (id SERIAL PRIMARY KEY, chat_id BIGINT NOT NULL, user_id BIGINT NOT NULL, admin_id BIGINT NOT NULL, reason TEXT, timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW());")
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

def delete_last_warning(chat_id: int, user_id: int) -> bool:
    conn, cur = None, None
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cur = conn.cursor()
        cur.execute(
            """DELETE FROM warnings WHERE id = (SELECT id FROM warnings 
               WHERE chat_id = %s AND user_id = %s 
               ORDER BY timestamp DESC LIMIT 1);""",
            (chat_id, user_id)
        )
        conn.commit()
        return cur.rowcount > 0
    except Exception as e:
        logger.error(f"Xəbərdarlıq silinərkən xəta: {e}")
        return False
    finally:
        if cur: cur.close()
        if conn: conn.close()

# --- MƏZMUN SİYAHILARI ---
ABOUT_TEXT = "🤖 **Bot Haqqında**\n\nMən qruplar üçün nəzərdə tutulmuş əyləncə və statistika botuyam. Mənimlə viktorina, tapmaca və digər oyunları oynaya, həmçinin qrupdakı aktivliyinizə görə rütə qazana bilərsiniz."
RULES_TEXT = """
📜 **Bot İstifadə Təlimatı və Qrup Qaydaları**

Aşağıda botun bütün funksiyalarından necə istifadə edəcəyiniz barədə məlumatlar və əsas qrup qaydaları qeyd olunub.

---

### 👤 **Ümumi İstifadəçilər Üçün Əmrlər**

- `/start` - Botu başlatmaq və əsas menyunu görmək.
- `/menim_rutbem` - Qrupdakı mesaj sayınızı və rütbənizi yoxlamaq. Premium üzvlər üçün mesajlar 1.5x sürətlə hesablanır və adlarının yanında 👑 nişanı görünür.
- `/liderler` - Bu ay ən çox mesaj yazan 10 nəfərin siyahısı.
- `/zer` - 1-dən 6-ya qədər təsadüfi zər atmaq.
- `/haqqinda` - Bot haqqında qısa məlumat.
- `/qaydalar` - Bu təlimatı yenidən görmək.

---

### 🎮 **Oyun Əmrləri**

- `/viktorina` - Bilik yarışması olan viktorina oyununu başladır. Oyunu başladan şəxs cavab verə bilər.
- `/dcoyun` - "Doğruluq yoxsa Cəsarət?" oyununu başladır. **(Yalnız adminlər başlada bilər)**

---

### 🛡️ **Adminlər Üçün İdarəetmə Əmrləri**

- `/adminpanel` - Bütün admin əmrlərini görmək üçün bu əmri istifadə edin.

---

### 📌 **Əsas Qrup Qaydaları**

1.  Reklam etmək qəti qadağandır.
2.  Təhqir, söyüş və aqressiv davranışlara icazə verilmir.
3.  Dini və siyasi mövzuları müzakirə etmək olmaz.
"""

# VIKTORINA SUALLARI (YENİ BAZA: 60 SADƏ, 100 PREMIUM)
SADE_QUIZ_QUESTIONS = [
    # Ümumi Bilik (12 sual)
    {'question': 'Azərbaycanın paytaxtı haradır?', 'options': ['Gəncə', 'Sumqayıt', 'Bakı', 'Naxçıvan'], 'correct': 'Bakı'},
    {'question': 'Bir ildə neçə fəsil var?', 'options': ['2', '3', '4', '5'], 'correct': '4'},
    {'question': 'Göy qurşağında neçə rəng var?', 'options': ['5', '6', '7', '8'], 'correct': '7'},
    {'question': 'İngilis əlifbasında neçə hərf var?', 'options': ['24', '25', '26', '27'], 'correct': '26'},
    {'question': 'Bir saatda neçə dəqiqə var?', 'options': ['30', '60', '90', '100'], 'correct': '60'},
    {'question': 'Hansı heyvan meşələrin kralı sayılır?', 'options': ['Pələng', 'Ayı', 'Canavar', 'Şir'], 'correct': 'Şir'},
    {'question': 'Qırmızı və sarı rəngləri qarışdırdıqda hansı rəng alınır?', 'options': ['Yaşıl', 'Bənövşəyi', 'Narıncı', 'Qəhvəyi'], 'correct': 'Narıncı'},
    {'question': 'Yeni il hansı ayda başlayır?', 'options': ['Dekabr', 'Yanvar', 'Fevral', 'Mart'], 'correct': 'Yanvar'},
    {'question': 'Üçbucağın neçə tərəfi var?', 'options': ['2', '3', '4', '5'], 'correct': '3'},
    {'question': 'Ən böyük materik hansıdır?', 'options': ['Afrika', 'Avropa', 'Asiya', 'Şimali Amerika'], 'correct': 'Asiya'},
    {'question': 'İnsan bədənində ən çox rast gəlinən element hansıdır?', 'options': ['Dəmir', 'Kalsium', 'Oksigen', 'Karbon'], 'correct': 'Oksigen'},
    {'question': 'Hansı ölkənin bayrağında aypara və ulduz var?', 'options': ['Yaponiya', 'Kanada', 'Türkiyə', 'İtaliya'], 'correct': 'Türkiyə'},
    # Tarix (12 sual)
    {'question': 'Qədim Misirdə hökmdarlar necə adlanırdı?', 'options': ['İmperator', 'Sultan', 'Firon', 'Kral'], 'correct': 'Firon'},
    {'question': 'İlk insan Aya neçənci ildə ayaq basıb?', 'options': ['1965', '1969', '1972', '1961'], 'correct': '1969'},
    {'question': 'Azadlıq Heykəli ABŞ-a hansı ölkə tərəfindən hədiyyə edilib?', 'options': ['Böyük Britaniya', 'Almaniya', 'Fransa', 'İspaniya'], 'correct': 'Fransa'},
    {'question': 'Yazını ilk dəfə hansı sivilizasiya icad etmişdir?', 'options': ['Qədim Misir', 'Qədim Yunanıstan', 'Şumerlər', 'Qədim Çin'], 'correct': 'Şumerlər'},
    {'question': 'Amerikanı kim kəşf etmişdir?', 'options': ['Vasco da Gama', 'Ferdinand Magellan', 'Xristofor Kolumb', 'James Cook'], 'correct': 'Xristofor Kolumb'},
    {'question': 'İkinci Dünya Müharibəsi neçənci ildə başlamışdır?', 'options': ['1935', '1939', '1941', '1945'], 'correct': '1939'},
    {'question': 'ABŞ-ın ilk prezidenti kim olmuşdur?', 'options': ['Abraham Lincoln', 'Tomas Cefferson', 'Corc Vaşqton', 'Con Adams'], 'correct': 'Corc Vaşqton'},
    {'question': 'Azərbaycan neçənci ildə müstəqilliyini bərpa etmişdir?', 'options': ['1989', '1990', '1991', '1993'], 'correct': '1991'},
    {'question': 'Hansı şəhər su üzərində qurulub?', 'options': ['Florensiya', 'Verona', 'Roma', 'Venesiya'], 'correct': 'Venesiya'},
    {'question': 'Roma İmperiyasının ilk imperatoru kim olmuşdur?', 'options': ['Yuli Sezar', 'Oktavian Avqust', 'Neron', 'Mark Antoni'], 'correct': 'Oktavian Avqust'},
    {'question': 'Azərbaycan Xalq Cümhuriyyəti neçənci ildə qurulmuşdur?', 'options': ['1920', '1918', '1991', '1905'], 'correct': '1918'},
    {'question': 'Hansı sərkərdə "Gəldim, Gördüm, Qələbə Çaldım" sözlərini demişdir?', 'options': ['Böyük İskəndər', 'Yuli Sezar', 'Napoleon Bonapart', 'Atilla'], 'correct': 'Yuli Sezar'},
    # Elm (12 sual)
    {'question': 'Suyun kimyəvi formulu nədir?', 'options': ['CO2', 'O2', 'H2O', 'NaCl'], 'correct': 'H2O'},
    {'question': 'Hansı planet "Qırmızı Planet" kimi tanınır?', 'options': ['Venera', 'Mars', 'Yupiter', 'Saturn'], 'correct': 'Mars'},
    {'question': 'İnsan bədənində neçə sümük var?', 'options': ['186', '206', '226', '256'], 'correct': '206'},
    {'question': 'Yerin təbii peyki hansıdır?', 'options': ['Mars', 'Venera', 'Ay', 'Fobos'], 'correct': 'Ay'},
    {'question': 'Qravitasiya qanununu kim kəşf etmişdir?', 'options': ['Qalileo Qaliley', 'İsaak Nyuton', 'Nikola Tesla', 'Arximed'], 'correct': 'İsaak Nyuton'},
    {'question': 'Hansı vitamin günəş şüası vasitəsilə bədəndə yaranır?', 'options': ['Vitamin C', 'Vitamin A', 'Vitamin B12', 'Vitamin D'], 'correct': 'Vitamin D'},
    {'question': 'Səs hansı mühitdə yayıla bilmir?', 'options': ['Suda', 'Havada', 'Metalda', 'Vakuumda'], 'correct': 'Vakuumda'},
    {'question': 'Atmosferin Yer kürəsini qoruyan təbəqəsi necə adlanır?', 'options': ['Troposfer', 'Stratosfer', 'Ozon təbəqəsi', 'Mezosfer'], 'correct': 'Ozon təbəqəsi'},
    {'question': 'Fotosintez zamanı bitkilər hansı qazı udur?', 'options': ['Oksigen', 'Azot', 'Karbon qazı', 'Hidrogen'], 'correct': 'Karbon qazı'},
    {'question': 'Dünyanın ən hündür dağı hansıdır?', 'options': ['K2', 'Everest', 'Elbrus', 'Monblan'], 'correct': 'Everest'},
    {'question': 'Günəş sistemində ən böyük planet hansıdır?', 'options': ['Saturn', 'Yupiter', 'Neptun', 'Uran'], 'correct': 'Yupiter'},
    {'question': 'Havanın əsas tərkib hissəsi hansı qazdır?', 'options': ['Oksigen', 'Karbon qazı', 'Azot', 'Hidrogen'], 'correct': 'Azot'},
    # Texnologiya (12 sual)
    {'question': 'Kompüterin "beyni" adlanan hissəsi hansıdır?', 'options': ['Monitor', 'RAM', 'Prosessor (CPU)', 'Sərt Disk'], 'correct': 'Prosessor (CPU)'},
    {'question': 'Telefonu kim icad etmişdir?', 'options': ['Tomas Edison', 'Nikola Tesla', 'Aleksandr Bell', 'Samuel Morze'], 'correct': 'Aleksandr Bell'},
    {'question': '"Facebook" sosial şəbəkəsinin qurucusu kimdir?', 'options': ['Bill Gates', 'Steve Jobs', 'Larry Page', 'Mark Zuckerberg'], 'correct': 'Mark Zuckerberg'},
    {'question': '"iPhone" smartfonlarını hansı şirkət istehsal edir?', 'options': ['Samsung', 'Google', 'Apple', 'Huawei'], 'correct': 'Apple'},
    {'question': 'PDF formatının tam adı nədir?', 'options': ['Portable Document Format', 'Printable Document File', 'Personal Data File', 'Public Document Format'], 'correct': 'Portable Document Format'},
    {'question': 'İlk elektrik lampasını kim icad edib?', 'options': ['Nikola Tesla', 'Aleksandr Bell', 'Tomas Edison', 'Benjamin Franklin'], 'correct': 'Tomas Edison'},
    {'question': 'URL-də "www" nə deməkdir?', 'options': ['World Wide Web', 'Web World Wide', 'World Web Wide', 'Wide World Web'], 'correct': 'World Wide Web'},
    {'question': 'Hansı şirkət "Windows" əməliyyat sistemini hazırlayır?', 'options': ['Apple', 'Google', 'Microsoft', 'IBM'], 'correct': 'Microsoft'},
    {'question': 'İlk uğurlu təyyarəni kimlər icad etmişdir?', 'options': ['Lumiere qardaşları', 'Wright qardaşları', 'Montgolfier qardaşları', 'Grimm qardaşları'], 'correct': 'Wright qardaşları'},
    {'question': 'Kompüterdə məlumatın ən kiçik ölçü vahidi nədir?', 'options': ['Bayt', 'Bit', 'Meqabayt', 'Geqabayt'], 'correct': 'Bit'},
    {'question': 'Hansı proqram cədvəllər və hesablamalar üçün istifadə olunur?', 'options': ['Word', 'PowerPoint', 'Photoshop', 'Excel'], 'correct': 'Excel'},
    {'question': 'Hansı sosial şəbəkənin loqosu quş şəklindədir?', 'options': ['Facebook', 'Instagram', 'Twitter (X)', 'LinkedIn'], 'correct': 'Twitter (X)'},
    # İdman (12 sual)
    {'question': 'Futbolda bir komandada neçə oyunçu olur?', 'options': ['9', '10', '11', '12'], 'correct': '11'},
    {'question': 'Olimpiya oyunlarının simvolu olan halqaların sayı neçədir?', 'options': ['4', '5', '6', '7'], 'correct': '5'},
    {'question': 'Futbol üzrə Dünya Çempionatı neçə ildən bir keçirilir?', 'options': ['2', '3', '4', '5'], 'correct': '4'},
    {'question': 'Hansı idman növündə topu səbətə atmaq lazımdır?', 'options': ['Voleybol', 'Həndbol', 'Basketbol', 'Su polosu'], 'correct': 'Basketbol'},
    {'question': 'Şahmat taxtasında neçə xana var?', 'options': ['36', '49', '64', '81'], 'correct': '64'},
    {'question': 'Hansı ölkə futbol üzrə ən çox Dünya Çempionu olub?', 'options': ['Almaniya', 'İtaliya', 'Argentina', 'Braziliya'], 'correct': 'Braziliya'},
    {'question': 'Boks rinqi hansı həndəsi fiqurdadır?', 'options': ['Dairə', 'Kvadrat', 'Üçbucaq', 'Romb'], 'correct': 'Kvadrat'},
    {'question': '"Dəmir Mayk" ləqəbli məşhur boksçu kimdir?', 'options': ['Məhəmməd Əli', 'Mayk Tayson', 'Floyd Mayweather', 'Rokki Marçiano'], 'correct': 'Mayk Tayson'},
    {'question': 'Şahmatda ən güclü fiqur hansıdır?', 'options': ['At', 'Fil', 'Vəzir', 'Top'], 'correct': 'Vəzir'},
    {'question': 'Tour de France nə yarışıdır?', 'options': ['Qaçış marafonu', 'Avtomobil yarışı', 'Velosiped turu', 'At yarışı'], 'correct': 'Velosiped turu'},
    {'question': '2022-ci il Futbol üzrə Dünya Çempionatının qalibi hansı ölkə oldu?', 'options': ['Fransa', 'Xorvatiya', 'Argentina', 'Braziliya'], 'correct': 'Argentina'},
    {'question': 'Müasir Olimpiya Oyunlarının banisi kim hesab olunur?', 'options': ['Pyerr de Kuberten', 'Juan Antonio Samaranch', 'Avery Brundage', 'Herakl'], 'correct': 'Pyerr de Kuberten'},
]
PREMIUM_QUIZ_QUESTIONS = [
    # Mədəniyyət və İncəsənət (20 sual)
    {'question': 'Əsərlərini Nizami Gəncəvi imzası ilə yazan şairin əsl adı nədir?', 'options': ['İlyas Yusif oğlu', 'Məhəmməd Füzuli', 'İmadəddin Nəsimi', 'Əliağa Vahid'], 'correct': 'İlyas Yusif oğlu'},
    {'question': 'Leonardo da Vinçinin "Mona Liza" tablosu hansı muzeydədir?', 'options': ['Britaniya Muzeyi', 'Vatikan Muzeyi', 'Ermitaj', 'Luvr Muzeyi'], 'correct': 'Luvr Muzeyi'},
    {'question': 'Üzeyir Hacıbəyovun "Koroğlu" operası neçə pərdədən ibarətdir?', 'options': ['3', '4', '5', '6'], 'correct': '5'},
    {'question': '"The Beatles" qrupu hansı şəhərdə yaranıb?', 'options': ['London', 'Mançester', 'Liverpul', 'Birminhem'], 'correct': 'Liverpul'},
    {'question': 'Dahi ispan rəssam Pablo Pikassonun tam adı neçə sözdən ibarətdir?', 'options': ['5', '11', '17', '23'], 'correct': '23'},
    {'question': '"Don Kixot" əsərinin müəllifi kimdir?', 'options': ['Uilyam Şekspir', 'Migel de Servantes', 'Dante Aligyeri', 'Françesko Petrarka'], 'correct': 'Migel de Servantes'},
    {'question': 'Hansı bəstəkar "Ay işığı sonatası" ilə məşhurdur?', 'options': ['Motsart', 'Bax', 'Bethoven', 'Şopen'], 'correct': 'Bethoven'},
    {'question': 'Azərbaycanın xalq artisti Rəşid Behbudov hansı ölkədə anadan olub?', 'options': ['Azərbaycan', 'İran', 'Türkiyə', 'Gürcüstan'], 'correct': 'Gürcüstan'},
    {'question': 'Fridrix Şillerin "Qaçaqlar" dramı əsasında Üzeyir Hacıbəyov hansı operettanı bəstələyib?', 'options': ['Leyli və Məcnun', 'O olmasın, bu olsun', 'Arşın mal alan', 'Əsli və Kərəm'], 'correct': 'O olmasın, bu olsun'},
    {'question': '"Rokki" filminin baş rol ifaçısı kimdir?', 'options': ['Arnold Şvartsenegger', 'Silvestr Stallone', 'Brüs Uillis', 'Jan-Klod Van Damm'], 'correct': 'Silvestr Stallone'},
    {'question': '"Sehrli fleyta" operasının müəllifi kimdir?', 'options': ['Vivaldi', 'Hendel', 'Motsart', 'Haydn'], 'correct': 'Motsart'},
    {'question': 'Səttar Bəhlulzadə yaradıcılığında əsasən hansı janra üstünlük verirdi?', 'options': ['Portret', 'Natürmort', 'Mənzərə', 'Abstrakt'], 'correct': 'Mənzərə'},
    {'question': 'Hansı yazıçı "Cinayət və Cəza" romanının müəllifidir?', 'options': ['Lev Tolstoy', 'Anton Çexov', 'Fyodor Dostoyevski', 'İvan Turgenev'], 'correct': 'Fyodor Dostoyevski'},
    {'question': 'Meksikalı rəssam Frida Kahlo əsasən hansı üslubda rəsmlər çəkirdi?', 'options': ['Kubizm', 'İmpressionizm', 'Sürrealizm', 'Realizm'], 'correct': 'Sürrealizm'},
    {'question': 'Müslüm Maqomayev hansı məşhur opera teatrının solisti olmuşdur?', 'options': ['La Skala', 'Böyük Teatr', 'Metropoliten-opera', 'Vyana Dövlət Operası'], 'correct': 'Böyük Teatr'},
    {'question': '"Səfillər" romanının müəllifi kimdir?', 'options': ['Aleksandr Düma', 'Jül Vern', 'Viktor Hüqo', 'Onore de Balzak'], 'correct': 'Viktor Hüqo'},
    {'question': 'Hansı memarlıq abidəsi "Məhəbbət abidəsi" kimi tanınır?', 'options': ['Kolizey', 'Eyfel qülləsi', 'Tac Mahal', 'Azadlıq heykəli'], 'correct': 'Tac Mahal'},
    {'question': 'Azərbaycan muğam sənəti UNESCO-nun qeyri-maddi mədəni irs siyahısına neçənci ildə daxil edilib?', 'options': ['2003', '2005', '2008', '2010'], 'correct': '2008'},
    {'question': 'Vinsent van Qoqun "Ulduzlu gecə" əsəri hazırda hansı şəhərin muzeyindədir?', 'options': ['Paris', 'Amsterdam', 'London', 'Nyu-York'], 'correct': 'Nyu-York'},
    {'question': 'Caz musiqisinin vətəni haradır?', 'options': ['Braziliya', 'Kuba', 'ABŞ (Nyu-Orlean)', 'Argentina'], 'correct': 'ABŞ (Nyu-Orlean)'},
    # Tarix (20 sual)
    {'question': '100 illik müharibə hansı iki dövlət arasında olmuşdur?', 'options': ['İngiltərə və Fransa', 'İspaniya və Portuqaliya', 'Roma və Karfagen', 'Prussiya və Avstriya'], 'correct': 'İngiltərə və Fransa'},
    {'question': 'Tarixdə "Atilla" adı ilə tanınan hökmdar hansı imperiyanı idarə edirdi?', 'options': ['Roma İmperiyası', 'Hun İmperiyası', 'Monqol İmperiyası', 'Osmanlı İmperiyası'], 'correct': 'Hun İmperiyası'},
    {'question': 'Səfəvi dövlətinin banisi kimdir?', 'options': ['Şah Abbas', 'Sultan Hüseyn', 'Şah İsmayıl Xətai', 'Nadir Şah'], 'correct': 'Şah İsmayıl Xətai'},
    {'question': 'Berlin divarı neçənci ildə yıxılmışdır?', 'options': ['1985', '1989', '1991', '1993'], 'correct': '1989'},
    {'question': 'Troya müharibəsi haqqında məlumat verən Homerin məşhur əsəri hansıdır?', 'options': ['Odisseya', 'Teoqoniya', 'İliada', 'Eneida'], 'correct': 'İliada'},
    {'question': 'Azərbaycan Xalq Cümhuriyyətinin ilk baş naziri kim olmuşdur?', 'options': ['Məmməd Əmin Rəsulzadə', 'Nəsib bəy Yusifbəyli', 'Fətəli Xan Xoyski', 'Əlimərdan bəy Topçubaşov'], 'correct': 'Fətəli Xan Xoyski'},
    {'question': 'Misir ehramları hansı məqsədlə tikilmişdir?', 'options': ['Rəsədxana', 'Məbəd', 'Fironlar üçün məqbərə', 'Taxıl anbarı'], 'correct': 'Fironlar üçün məqbərə'},
    {'question': 'Soyuq müharibə əsasən hansı iki supergüc arasında gedirdi?', 'options': ['Çin və Yaponiya', 'Almaniya və Fransa', 'ABŞ və SSRİ', 'Böyük Britaniya və ABŞ'], 'correct': 'ABŞ və SSRİ'},
    {'question': 'Napoleon Bonapart Vaterloo döyüşündə neçənci ildə məğlub oldu?', 'options': ['1805', '1812', '1815', '1821'], 'correct': '1815'},
    {'question': 'Osmanlı Sultanı Fateh Sultan Mehmet İstanbulu neçənci ildə fəth etmişdir?', 'options': ['1451', '1453', '1461', '1481'], 'correct': '1453'},
    {'question': 'ABŞ-da köləliyi ləğv edən 13-cü düzəlişi hansı prezident imzalamışdır?', 'options': ['Corc Vaşqton', 'Tomas Cefferson', 'Abraham Linkoln', 'Franklin Ruzvelt'], 'correct': 'Abraham Linkoln'},
    {'question': 'Makedoniyalı İskəndərin müəllimi olmuş məşhur yunan filosofu kimdir?', 'options': ['Platon', 'Sokrat', 'Aristotel', 'Diogen'], 'correct': 'Aristotel'},
    {'question': 'Hansı hadisə Orta Əsrlərin başlanğıcı hesab olunur?', 'options': ['Şərqi Roma İmperiyasının yaranması', 'Qərbi Roma İmperiyasının süqutu', 'Xaç yürüşlərinin başlaması', 'Amerikanın kəşfi'], 'correct': 'Qərbi Roma İmperiyasının süqutu'},
    {'question': 'Babək hansı xilafətə qarşı mübarizə aparmışdır?', 'options': ['Əməvilər', 'Abbasilər', 'Osmanlılar', 'Fatimilər'], 'correct': 'Abbasilər'},
    {'question': 'Qara ölüm (Taun) pandemiyası Avropada hansı əsrdə geniş yayılmışdı?', 'options': ['12-ci əsr', '13-cü əsr', '14-cü əsr', '15-ci əsr'], 'correct': '14-cü əsr'},
    {'question': 'Xirosimaya atılan atom bombasının adı nə idi?', 'options': ['"Fat Man"', '"Little Boy"', '"Tsar Bomba"', '"Trinity"'], 'correct': '"Little Boy"'},
    {'question': '"Gülüstan" və "Türkmənçay" müqavilələri hansı imperiyalar arasında imzalanıb?', 'options': ['Osmanlı və Rusiya', 'Qacarlar və Osmanlı', 'Rusiya və Qacarlar', 'Britaniya və Rusiya'], 'correct': 'Rusiya və Qacarlar'},
    {'question': 'Vikinqlər əsasən hansı regiondan dünyaya yayılmışdılar?', 'options': ['Aralıq dənizi', 'Skandinaviya', 'Balkanlar', 'Britaniya adaları'], 'correct': 'Skandinaviya'},
    {'question': 'ABŞ-ın müstəqillik bəyannaməsi neçənci ildə qəbul edilib?', 'options': ['1776', '1789', '1812', '1865'], 'correct': '1776'},
    {'question': 'Monqol imperiyasının qurucusu kimdir?', 'options': ['Atilla', 'Batı xan', 'Çingiz xan', 'Əmir Teymur'], 'correct': 'Çingiz xan'},
    # Elm (20 sual)
    {'question': 'Eynşteynin məşhur Nisbilik Nəzəriyyəsinin düsturu hansıdır?', 'options': ['F=ma', 'E=mc²', 'a²+b²=c²', 'V=IR'], 'correct': 'E=mc²'},
    {'question': 'İlk dəfə Aya ayaq basan insan kimdir?', 'options': ['Yuri Qaqarin', 'Con Glenn', 'Maykl Kollins', 'Nil Armstronq'], 'correct': 'Nil Armstronq'},
    {'question': 'Çernobıl AES-də qəza neçənci ildə baş vermişdir?', 'options': ['1982', '1986', '1988', '1991'], 'correct': '1986'},
    {'question': 'Hansı kimyəvi elementin simvolu "Au"-dur?', 'options': ['Gümüş', 'Mis', 'Qızıl', 'Dəmir'], 'correct': 'Qızıl'},
    {'question': 'İnsan DNT-si neçə xromosomdan ibarətdir?', 'options': ['23 cüt (46)', '21 cüt (42)', '25 cüt (50)', '32 cüt (64)'], 'correct': '23 cüt (46)'},
    {'question': 'İşıq sürəti saniyədə təxminən nə qədərdir?', 'options': ['150,000 km', '300,000 km', '500,000 km', '1,000,000 km'], 'correct': '300,000 km'},
    {'question': 'Böyük Partlayış (Big Bang) nəzəriyyəsi nəyi izah edir?', 'options': ['Ulduzların yaranmasını', 'Qara dəliklərin formalaşmasını', 'Kainatın yaranmasını', 'Günəş sisteminin yaranmasını'], 'correct': 'Kainatın yaranmasını'},
    {'question': 'Hansı alim penisilini kəşf etmişdir?', 'options': ['Lui Paster', 'Aleksandr Fleminq', 'Robert Kox', 'Mariya Küri'], 'correct': 'Aleksandr Fleminq'},
    {'question': 'Higgs bozonu elmi dairələrdə daha çox hansı adla tanınır?', 'options': ['Tanrı hissəciyi', 'Foton', 'Neytrino', 'Qraviton'], 'correct': 'Tanrı hissəciyi'},
    {'question': 'Yerin maqnit sahəsi bizi nədən qoruyur?', 'options': ['Meteoritlərdən', 'Günəş küləyindən', 'Ultrabənövşəyi şüalardan', 'Soyuq kosmosdan'], 'correct': 'Günəş küləyindən'},
    {'question': 'Albert Eynşteyn Nobel mükafatını hansı kəşfinə görə almışdır?', 'options': ['Nisbilik nəzəriyyəsi', 'Fotoelektrik effekti', 'Brown hərəkəti', 'E=mc²'], 'correct': 'Fotoelektrik effekti'},
    {'question': 'Kimya elmində pH şkalası nəyi ölçmək üçün istifadə olunur?', 'options': ['Temperaturu', 'Təzyiqi', 'Turşuluq və qələviliyi', 'Sıxlığı'], 'correct': 'Turşuluq və qələviliyi'},
    {'question': 'Halley kometası Yer kürəsindən təxminən neçə ildən bir görünür?', 'options': ['25-26 il', '50-51 il', '75-76 il', '100-101 il'], 'correct': '75-76 il'},
    {'question': '"Dolly" adlı qoyun hansı elmi nailiyyətin simvoludur?', 'options': ['Gen modifikasiyası', 'İlk klonlanmış məməli', 'Süni intellekt', 'Kök hüceyrə tədqiqatı'], 'correct': 'İlk klonlanmış məməli'},
    {'question': 'Qırmızı qan hüceyrələrinə rəngini verən dəmir tərkibli zülal hansıdır?', 'options': ['Mioqlobin', 'Albumin', 'Hemoqlobin', 'Fibrinogen'], 'correct': 'Hemoqlobin'},
    {'question': 'Hansı planetin peyki olan Titanın sıx atmosferi var?', 'options': ['Yupiter', 'Mars', 'Uran', 'Saturn'], 'correct': 'Saturn'},
    {'question': 'İnsanın eşitmə diapazonundan daha yüksək tezlikli səslər necə adlanır?', 'options': ['İnfrasəs', 'Rezonans', 'Ultrasəs', 'Subsonik'], 'correct': 'Ultrasəs'},
    {'question': 'Təkamül nəzəriyyəsini "Növlərin Mənşəyi" kitabında irəli sürən alim kimdir?', 'options': ['Qreqor Mendel', 'Alfred Uolles', 'Jan-Batist Lamark', 'Çarlz Darvin'], 'correct': 'Çarlz Darvin'},
    {'question': 'Fermatın Böyük Teoremi riyaziyyatda neçə əsrdən sonra sübut edilmişdir?', 'options': ['Təxminən 100 il', 'Təxminən 250 il', 'Təxminən 358 il', 'Hələ sübut edilməyib'], 'correct': 'Təxminən 358 il'},
    {'question': 'Mariana çökəkliyi hansı okeanda yerləşir?', 'options': ['Atlantik', 'Hind', 'Şimal Buzlu', 'Sakit'], 'correct': 'Sakit'},
    # Texnologiya (20 sual)
    {'question': 'İlk kosmik peyk olan "Sputnik 1" hansı ölkə tərəfindən orbitə buraxılmışdır?', 'options': ['ABŞ', 'Çin', 'SSRİ', 'Böyük Britaniya'], 'correct': 'SSRİ'},
    {'question': '"World Wide Web" (WWW) konsepsiyasını kim yaratmışdır?', 'options': ['Steve Jobs', 'Linus Torvalds', 'Tim Berners-Lee', 'Vint Cerf'], 'correct': 'Tim Berners-Lee'},
    {'question': 'Hansı proqramlaşdırma dili Google tərəfindən yaradılmışdır?', 'options': ['Swift', 'Kotlin', 'Go', 'Rust'], 'correct': 'Go'},
    {'question': 'Kriptovalyuta olan Bitcoin-in yaradıcısının ləqəbi nədir?', 'options': ['Vitalik Buterin', 'Satoshi Nakamoto', 'Elon Musk', 'Charlie Lee'], 'correct': 'Satoshi Nakamoto'},
    {'question': 'Kompüter elmlərində "Turing maşını" nəzəriyyəsini kim irəli sürmüşdür?', 'options': ['Con fon Neyman', 'Alan Turinq', 'Ada Lavleys', 'Çarlz Bebbic'], 'correct': 'Alan Turinq'},
    {'question': 'İnternetin sələfi hesab olunan ilk kompüter şəbəkəsi necə adlanırdı?', 'options': ['NSFNET', 'ETHERNET', 'ARPANET', 'İNTRANET'], 'correct': 'ARPANET'},
    {'question': 'Hansı şirkət ilk "Walkman" portativ kaset pleyerini istehsal etmişdir?', 'options': ['Panasonic', 'Sony', 'Philips', 'Aiwa'], 'correct': 'Sony'},
    {'question': '"Moore Qanunu" nə ilə bağlıdır?', 'options': ['Prosessorların sürətinin artması', 'İnteqral sxemlərdəki tranzistorların sayının ikiqat artması', 'İnternet sürətinin artması', 'Batareya ömrünün uzanması'], 'correct': 'İnteqral sxemlərdəki tranzistorların sayının ikiqat artması'},
    {'question': 'Açıq mənbəli (open-source) əməliyyat sistemi olan Linux-un ləpəsini (kernel) kim yaratmışdır?', 'options': ['Riçard Stallman', 'Stiv Voznyak', 'Linus Torvalds', 'Bill Geyts'], 'correct': 'Linus Torvalds'},
    {'question': 'Hansı alqoritm Google-un axtarış sisteminin əsasını təşkil edirdi?', 'options': ['A*', 'Dijkstra', 'PageRank', 'Bubble Sort'], 'correct': 'PageRank'},
    {'question': 'Deep Blue adlı superkompüter hansı məşhur şahmatçını məğlub etmişdir?', 'options': ['Maqnus Karlsen', 'Bobi Fişer', 'Harri Kasparov', 'Anatoli Karpov'], 'correct': 'Harri Kasparov'},
    {'question': 'Hansı şirkət ilk kommersiya məqsədli mikroprosessoru (Intel 4004) təqdim etmişdir?', 'options': ['IBM', 'AMD', 'Intel', 'Motorola'], 'correct': 'Intel'},
    {'question': '"Virtual Reality" (VR) nə deməkdir?', 'options': ['Genişləndirilmiş Reallıq', 'Süni İntellekt', 'Sanal Reallıq', 'Maşın Təlimi'], 'correct': 'Sanal Reallıq'},
    {'question': 'C++ proqramlaşdırma dilinin yaradıcısı kimdir?', 'options': ['Dennis Ritçi', 'Ceyms Qoslinq', 'Byarne Stroustrup', 'Qvido van Rossum'], 'correct': 'Byarne Stroustrup'},
    {'question': 'Blokçeyn (Blockchain) texnologiyası ilk dəfə hansı tətbiqdə istifadə edilib?', 'options': ['Ethereum', 'Ripple', 'Litecoin', 'Bitcoin'], 'correct': 'Bitcoin'},
    {'question': 'Hansı cihaz alternativ cərəyanı (AC) sabit cərəyana (DC) çevirir?', 'options': ['Transformator', 'Generator', 'Düzləndirici (Rectifier)', 'İnverter'], 'correct': 'Düzləndirici (Rectifier)'},
    {'question': 'Kompüterə qoşulan xarici cihazları idarə edən proqram təminatı necə adlanır?', 'options': ['Əməliyyat sistemi', 'Drayver', 'Utilit', 'Tətbiqi proqram'], 'correct': 'Drayver'},
    {'question': 'İlk video paylaşım saytı olan YouTube neçənci ildə yaradılıb?', 'options': ['2003', '2005', '2007', '2009'], 'correct': '2005'},
    {'question': '3D printerin iş prinsipi nəyə əsaslanır?', 'options': ['Materialı kəsməyə', 'Materialı əritməyə', 'Materialı qat-qat əlavə etməyə', 'Materialı pressləməyə'], 'correct': 'Materialı qat-qat əlavə etməyə'},
    {'question': 'İstifadəçiyə saxta e-poçt göndərərək həssas məlumatları oğurlama cəhdi necə adlanır?', 'options': ['Virus', 'Spam', 'Fişinq', 'Troyan'], 'correct': 'Fişinq'},
    # İdman (20 sual)
    {'question': '"Formula 1" tarixində ən çox yarış qazanan pilot kimdir?', 'options': ['Mixael Şumaxer', 'Sebastian Vettel', 'Ayrton Senna', 'Lüis Hemilton'], 'correct': 'Lüis Hemilton'},
    {'question': 'Bir marafon yarışının rəsmi məsafəsi nə qədərdir?', 'options': ['26.2 km', '42.195 km', '50 km', '35.5 km'], 'correct': '42.195 km'},
    {'question': 'Ağır atletika üzrə 3 qat Olimpiya çempionu olmuş "Cib Heraklisi" ləqəbli türk idmançı kimdir?', 'options': ['Halil Mutlu', 'Naim Süleymanoğlu', 'Taner Sağır', 'Hafiz Süleymanoğlu'], 'correct': 'Naim Süleymanoğlu'},
    {'question': 'Şahmatda "Sitsiliya müdafiəsi" hansı gedişlə başlayır?', 'options': ['1. e4 c5', '1. d4 Nf6', '1. e4 e5', '1. c4 e5'], 'correct': '1. e4 c5'},
    {'question': 'Tennisdə "Böyük Dəbilqə" (Grand Slam) turnirlərinə hansı daxil deyil?', 'options': ['Uimbldon', 'ABŞ Açıq', 'Fransa Açıq (Roland Garros)', 'Indian Wells Masters'], 'correct': 'Indian Wells Masters'},
    {'question': 'Futbol tarixində yeganə qapıçı olaraq "Qızıl Top" mükafatını kim qazanıb?', 'options': ['Canluici Buffon', 'Oliver Kan', 'Lev Yaşin', 'İker Kasilyas'], 'correct': 'Lev Yaşin'},
    {'question': 'Hansı komanda ən çox UEFA Çempionlar Liqası kubokunu qazanıb?', 'options': ['Barselona', 'Milan', 'Bavariya Münhen', 'Real Madrid'], 'correct': 'Real Madrid'},
    {'question': 'Məhəmməd Əli məşhur "Rumble in the Jungle" döyüşündə kimə qalib gəlmişdir?', 'options': ['Sonny Liston', 'Joe Frazier', 'George Foreman', 'Ken Norton'], 'correct': 'George Foreman'},
    {'question': 'Maykl Cordan karyerasının böyük hissəsini hansı NBA komandasında keçirib?', 'options': ['Los Angeles Lakers', 'Boston Celtics', 'Chicago Bulls', 'New York Knicks'], 'correct': 'Chicago Bulls'},
    {'question': 'Hansı üzgüçü ən çox Olimpiya qızıl medalı qazanıb?', 'options': ['Mark Spitz', 'Maykl Felps', 'Ryan Lochte', 'Ian Thorpe'], 'correct': 'Maykl Felps'},
    {'question': 'İlk Futbol üzrə Dünya Çempionatı hansı ölkədə keçirilmişdir?', 'options': ['Braziliya', 'İtaliya', 'Uruqvay', 'İngiltərə'], 'correct': 'Uruqvay'},
    {'question': 'Hansı tennisçi "Torpağın Kralı" (King of Clay) ləqəbi ilə tanınır?', 'options': ['Rocer Federer', 'Novak Cokoviç', 'Rafael Nadal', 'Pit Sampras'], 'correct': 'Rafael Nadal'},
    {'question': '"New Zealand All Blacks" hansı idman növü üzrə məşhur milli komandadır?', 'options': ['Futbol', 'Kriket', 'Reqbi', 'Basketbol'], 'correct': 'Reqbi'},
    {'question': 'Snuker oyununda ən yüksək xal verən rəngli top hansıdır?', 'options': ['Mavi', 'Çəhrayı', 'Qara', 'Sarı'], 'correct': 'Qara'},
    {'question': 'Yelena İsinbayeva hansı yüngül atletika növündə dünya rekordçusu idi?', 'options': ['Hündürlüyə tullanma', 'Üçtəkanla tullanma', 'Şüvüllə tullanma', 'Uzunluğa tullanma'], 'correct': 'Şüvüllə tullanma'},
    {'question': 'Hansı döyüş sənəti "yumşaq yol" mənasını verir?', 'options': ['Karate', 'Taekvondo', 'Cüdo', 'Kunq-fu'], 'correct': 'Cüdo'},
    {'question': 'Formula 1-də "Hat-trick" nə deməkdir?', 'options': ['Eyni yarışda 3 dəfə pit-stop etmək', 'Pole mövqeyi, ən sürətli dövrə və qələbə', 'Bir mövsümdə 3 qələbə qazanmaq', 'Podiumda 3 komanda yoldaşının olması'], 'correct': 'Pole mövqeyi, ən sürətli dövrə və qələbə'},
    {'question': 'NBA tarixində ən çox xal qazanan basketbolçu kimdir?', 'options': ['Maykl Cordan', 'Kərim Əbdül-Cabbar', 'Kobi Brayant', 'LeBron Ceyms'], 'correct': 'LeBron Ceyms'},
    {'question': 'Hansı idman növündə "Albatros" termini istifadə olunur?', 'options': ['Futbol', 'Qolf', 'Reqbi', 'Kriket'], 'correct': 'Qolf'},
    {'question': '"Qarabağ" FK öz ev oyunlarını hazırda hansı stadionda keçirir?', 'options': ['Tofiq Bəhramov adına Respublika Stadionu', 'Bakı Olimpiya Stadionu', 'Dalğa Arena', 'Azərsun Arena'], 'correct': 'Tofiq Bəhramov adına Respublika Stadionu'},
    # Ümumi Bilik (20 sual)
    {'question': 'Hansı ölkə həm Avropada, həm də Asiyada yerləşir?', 'options': ['Misir', 'Rusiya', 'İran', 'Qazaxıstan'], 'correct': 'Rusiya'},
    {'question': 'Dünyanın ən uzun çayı hansıdır?', 'options': ['Amazon', 'Nil', 'Yantszı', 'Missisipi'], 'correct': 'Nil'},
    {'question': 'Hansı şəhər İtaliyanın paytaxtıdır?', 'options': ['Milan', 'Neapol', 'Roma', 'Venesiya'], 'correct': 'Roma'},
    {'question': 'Avstraliya qitəsinin ən məşhur heyvanı hansıdır?', 'options': ['Zürafə', 'Kenquru', 'Panda', 'Zebra'], 'correct': 'Kenquru'},
    {'question': 'İnsan bədənindəki ən güclü əzələ hansıdır?', 'options': ['Biceps', 'Ürək', 'Dil', 'Çeynəmə əzələsi'], 'correct': 'Çeynəmə əzələsi'},
    {'question': 'Hansı dənizdə duzluluq səviyyəsi ən yüksəkdir və batmaq demək olar ki, mümkün deyil?', 'options': ['Aralıq dənizi', 'Qırmızı dəniz', 'Ölü dəniz', 'Qara dəniz'], 'correct': 'Ölü dəniz'},
    {'question': '"Şərqin Parisi" adlandırılan şəhər hansıdır?', 'options': ['İstanbul', 'Dubay', 'Bakı', 'Beyrut'], 'correct': 'Bakı'},
    {'question': 'Hansı ölkənin bayrağı düzbucaqlı formada olmayan yeganə bayraqdır?', 'options': ['İsveçrə', 'Vatikan', 'Nepal', 'Yaponiya'], 'correct': 'Nepal'},
    {'question': 'Bir əsrdə neçə il var?', 'options': ['10', '50', '100', '1000'], 'correct': '100'},
    {'question': 'Hansı ölkə özünün pendir və şokoladı ilə məşhurdur?', 'options': ['Fransa', 'Belçika', 'İsveçrə', 'İtaliya'], 'correct': 'İsveçrə'},
    {'question': 'Sahara səhrası hansı qitədə yerləşir?', 'options': ['Asiya', 'Avstraliya', 'Afrika', 'Cənubi Amerika'], 'correct': 'Afrika'},
    {'question': 'Hansı şəhər həm də bir ölkədir?', 'options': ['Monako', 'Vatikan', 'Sinqapur', 'Hamısı'], 'correct': 'Hamısı'},
    {'question': 'Dünyanın ən çox əhalisi olan ölkəsi hansıdır (2024-cü il məlumatlarına görə)?', 'options': ['Çin', 'Hindistan', 'ABŞ', 'İndoneziya'], 'correct': 'Hindistan'},
    {'question': '"Qızıl Qapı" körpüsü (Golden Gate Bridge) hansı şəhərdə yerləşir?', 'options': ['Nyu-York', 'Los Anceles', 'San-Fransisko', 'Çikaqo'], 'correct': 'San-Fransisko'},
    {'question': 'Termometr nəyi ölçmək üçün istifadə olunur?', 'options': ['Təzyiq', 'Rütubət', 'Temperatur', 'Sürət'], 'correct': 'Temperatur'},
    {'question': 'Hansı metal otaq temperaturunda maye halında olur?', 'options': ['Qalay', 'Qurğuşun', 'Civə', 'Alüminium'], 'correct': 'Civə'},
    {'question': 'Bir sutkada neçə saniyə var?', 'options': ['3600', '64800', '86400', '1440'], 'correct': '86400'},
    {'question': 'Hansı ölkə özünün ağcaqayın siropu (maple syrup) ilə tanınır?', 'options': ['ABŞ', 'Rusiya', 'Norveç', 'Kanada'], 'correct': 'Kanada'},
    {'question': 'Böyük Bariyer Rifi hansı ölkənin sahillərində yerləşir?', 'options': ['Braziliya', 'Meksika', 'Avstraliya', 'İndoneziya'], 'correct': 'Avstraliya'},
    {'question': 'Hansı yazıçı "Harri Potter" seriyasının müəllifidir?', 'options': ['J.R.R. Tolkien', 'George R.R. Martin', 'C.S. Lewis', 'J.K. Rowling'], 'correct': 'J.K. Rowling'},
]

# ... (Qalan bütün funksiyalar və main bloku olduğu kimi qalır) ...

async def main() -> None:
    run_pre_flight_checks()
    init_db()
    
    application = Application.builder().token(TOKEN).build()
    
    commands = [
        BotCommand("start", "Əsas menyunu açmaq"),
        BotCommand("qaydalar", "İstifadə təlimatı və qaydalar"),
        BotCommand("haqqinda", "Bot haqqında məlumat"),
        BotCommand("menim_rutbem", "Şəxsi rütbəni yoxlamaq"),
        BotCommand("viktorina", "Viktorina oyununu başlatmaq"),
        BotCommand("zer", "1-6 arası zər atmaq"),
        BotCommand("liderler", "Aylıq liderlər cədvəli"),
        BotCommand("dcoyun", "Doğruluq/Cəsarət oyununu başlatmaq (Admin)"),
        BotCommand("adminpanel", "Admin idarəetmə paneli (Admin)"),
    ]
    
    # Handlerlərin əlavə edilməsi...
    # ... (Bütün handlerlər əvvəlki kodda olduğu kimi qalır) ...
    
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
