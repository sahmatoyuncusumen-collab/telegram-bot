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
# ... (Bütün köhnə sual/tapmaca/macəra siyahıları olduğu kimi qalır)
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
- Sonda nəticələr elan olunur.

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

# --- YENİ OYUN: İKİ DÜZ, BİR YALAN ---
STATEMENT_1, STATEMENT_2, STATEMENT_3, WHICH_IS_LIE = range(4)
async def yalan_tap_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    chat_id = update.message.chat_id
    if context.chat_data.get(f'ttol_active_{chat_id}'):
        await update.message.reply_text("Artıq qrupda aktiv 'İki Düz, Bir Yalan' oyunu var. Lütfən onun bitməsini gözləyin.")
        return ConversationHandler.END
    try:
        bot_username = (await context.bot.get_me()).username
        start_link = f"https://t.me/{bot_username}?start=ttol_{chat_id}"
        keyboard = [[InlineKeyboardButton("Hazırsan? Mənə Şəxsidə Yaz!", url=start_link)]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(f"Salam, {user.first_name}! 'İki Düz, Bir Yalan' oyununa başlamaq üçün aşağıdakı düyməyə basaraq mənə şəxsidə yaz.", reply_markup=reply_markup)
    except Exception as e:
        logger.error(f"İki Düz Bir Yalan oyununu başlatarkən xəta: {e}")
    return ConversationHandler.END

async def ttol_start_in_private(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        group_id = int(context.args[0].split('_')[1])
        context.user_data['ttol_group_id'] = group_id
    except (IndexError, ValueError):
        await update.message.reply_text("Xəta baş verdi. Zəhmət olmasa, oyunu qrupdan yenidən başladın."); return ConversationHandler.END
    await update.message.reply_text("Əla! İndi özün haqqında 1-ci iddianı yaz (doğru və ya yalan ola bilər)."); return STATEMENT_1

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
    keyboard = [[InlineKeyboardButton(f"{i+1}-ci İddia", callback_data=f"ttol_vote_{i+1}")] for i in range(3)]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text("Məlumatlar qəbul edildi! İndi oyunu qrupda yayımlayıram...")
    game_text = (f"Yeni oyun başladı! 🤔\n\n**{query.from_user.first_name}** özü haqqında 3 iddia göndərdi. Sizcə hansı yalandır?\n\n"
                 f"1. {statements[0]}\n2. {statements[1]}\n3. {statements[2]}\n\nYalan olanı tapmaq üçün 60 saniyəniz var!")
    message = await context.bot.send_message(chat_id=group_id, text=game_text, reply_markup=reply_markup)
    context.application.chat_data[group_id]['ttol_message_id'] = message.message_id
    context.job_queue.run_once(finish_ttol_game, 60, chat_id=group_id, name=f'ttol_{group_id}')
    for key in ['ttol_group_id', 'ttol_s1', 'ttol_s2', 'ttol_s3']: context.user_data.pop(key, None)
    return ConversationHandler.END

async def finish_ttol_game(context: ContextTypes.DEFAULT_TYPE):
    job = context.job; chat_id = job.chat_id
    chat_data = context.application.chat_data[chat_id]
    if not chat_data.get('ttol_active'): return
    author, lie_index, votes, message_id = chat_data['ttol_author'], chat_data['ttol_lie_index'], chat_data['ttol_votes'], chat_data['ttol_message_id']
    results_text = "\n\n**Nəticələr:**\n"
    winners = []
    if not votes:
        results_text += "Heç kim səs vermədi."
    else:
        for user_name, vote in votes.items():
            if vote == lie_index:
                winners.append(user_name)
    if winners:
        results_text += f"Düzgün tapanlar: {', '.join(winners)} 🥳"
    else:
        results_text += "Heç kim düzgün tapa bilmədi. 😔"
    try:
        original_message = await context.bot.edit_message_reply_markup(chat_id=chat_id, message_id=message_id, reply_markup=None)
        await original_message.reply_text(f"Vaxt bitdi! ⌛️\n\n**{author}** haqqında yalan olan iddia **{lie_index}-ci** idi!" + results_text)
    except Exception as e:
        logger.error(f"TTOL nəticəsini göndərərkən xəta: {e}")
        await context.bot.send_message(chat_id=chat_id, text=f"Vaxt bitdi! ⌛️\n\n**{author}** haqqında yalan olan iddia **{lie_index}-ci** idi!" + results_text)
    for key in ['ttol_active', 'ttol_author', 'ttol_lie_index', 'ttol_votes', 'ttol_message_id']:
        chat_data.pop(key, None)

async def ttol_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Proses ləğv edildi.")
    return ConversationHandler.END

# --- KÖHNƏ FUNKSİYALAR ---
# ... (Bütün köhnə funksiyalar olduğu kimi qalır, qısalıq üçün kəsdim)
def get_rank_title(count: int) -> str: #...
    pass
async def welcome_new_members(update: Update, context: ContextTypes.DEFAULT_TYPE): #...
    pass
#... və s.

# --- MAIN FUNKSİYASI ---
def main() -> None:
    run_pre_flight_checks()
    init_db()
    application = Application.builder().token(TOKEN).build()
    group_filter = ~filters.ChatType.PRIVATE
    
    # YENİ "İki Düz, Bir Yalan" oyunu üçün ConversationHandler
    ttol_conv_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex('^/start ttol_'), ttol_start_in_private)],
        states={
            STATEMENT_1: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_statement1)],
            STATEMENT_2: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_statement2)],
            STATEMENT_3: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_statement3)],
            WHICH_IS_LIE: [CallbackQueryHandler(receive_which_is_lie, pattern='^ttol_lie_')]
        },
        fallbacks=[CommandHandler("cancel", ttol_cancel)],
        conversation_timeout=300 # 5 dəqiqə ərzində cavab verməsə, proses ləğv olunur
    )
    application.add_handler(ttol_conv_handler)
    application.add_handler(CommandHandler("yalan_tap", yalan_tap_command, filters=group_filter))
    
    # Bütün köhnə handler-lər
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("qaydalar", qaydalar_command))
    application.add_handler(CommandHandler("macera", macera_command, filters=group_filter))
    # ... və digərləri
    
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(CallbackQueryHandler(ttol_vote_callback, pattern='^ttol_vote_'))
    # ...
    
    print("Bot işə düşdü...")
    application.run_polling()

if __name__ == '__main__':
    main()
