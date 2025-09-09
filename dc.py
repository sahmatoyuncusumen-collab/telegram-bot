import logging
import random
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters
from telegram.constants import ChatType

# Logging (xətaları və botun fəaliyyətini görmək üçün)
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Oyun üçün suallar və tapşırıqlar
TRUTH_QUESTIONS = [
    "Uşaqlıqda ən böyük qorxun nə idi?", "Həyatında ən çox peşman olduğun şey?", "Heç kimin bilmədiyi bir bacarığın varmı?",
    "Bu qrupda ən çox güvəndiyin insan kimdir?", "Bir günlük görünməz olsaydın nə edərdin?", "Telefonunda ən son axtardığın 5 şey nədir?"
]
DARE_TASKS = [
    "Profil şəklini 1 saatlıq qrupdakı ən son göndərilən şəkil ilə dəyişdir.", "Qrupdakı birinə səsli mesajla mahnı oxu.",
    "Əlifbanı sondan əvvələ doğru sürətli şəkildə say.", "Son zəng etdiyin adama zəng edib 'Səni sevirəm' de.",
    "2 dəqiqə ərzində ancaq sual cümlələri ilə danış."
]

async def is_user_admin(chat_id: int, user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if chat_id == user_id:
        return True
    try:
        chat_admins = await context.bot.get_chat_administrators(chat_id)
        return user_id in [admin.user.id for admin in chat_admins]
    except Exception as e:
        logger.error(f"Admin yoxlanarkən xəta: {e}")
        return False

async def ask_next_player(chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    chat_data = context.chat_data
    chat_data['current_player_index'] += 1
    if chat_data['current_player_index'] >= len(chat_data['player_list']):
        chat_data['current_player_index'] = 0
    current_player = chat_data['player_list'][chat_data['current_player_index']]
    user_id, first_name = current_player['id'], current_player['name']
    keyboard = [[
        InlineKeyboardButton("Doğruluq ✅", callback_data=f"game_truth_{user_id}"),
        InlineKeyboardButton("Cəsarət 😈", callback_data=f"game_dare_{user_id}")
    ]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await context.bot.send_message(
        chat_id,
        text=f"Sıra sənə çatdı, [{first_name}](tg://user?id={user_id})! Seçimini et:",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_text = """
Salam! Mən "Doğruluq yoxsa Cəsarət?" botuyam. 🤖

Dostlarınla əyləncəli vaxt keçirmək üçün məni qrupuna əlavə et!

**Oyunun Qaydaları:**
1. Məni qrupa əlavə et.
2. Kimlərsə `/qeydiyyat` yazaraq qeydiyyat menyusunu açsın.
3. Bütün iştirakçılar "Oyuna Qoşul" düyməsinə bassın.
4. Adminlərdən biri `/baslat` yazaraq oyunu başlatsın.
5. Hər turdan sonra admin `/novbeti` yazaraq sıranı növbəti oyunçuya keçirsin.

**Əsas Əmrlər:**
- `/start` - Bu məlumat mesajını göstərər.
- `/qeydiyyat` - Oyun üçün qeydiyyatı başladar.
- `/qosul` - Başlamış oyuna qoşulmaq üçün.
- `/cix` - Oyundan ayrılmaq üçün.

**Admin Əmrləri:**
- `/baslat` - Qeydiyyatdan keçənlərlə oyunu başladar.
- `/novbeti` - Sıranı növbəti oyunçuya keçirər.
- `/dayandir` - Aktiv oyunu dayandırar və hər şeyi sıfırlayar.

Gəl başlayaq! 🚀
    """
    await update.message.reply_text(welcome_text)

async def registration_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.chat_data.get('game_active', False):
        await update.message.reply_text("Oyun artıq başlayıb. Yeni oyunçular /qosul əmri ilə qatıla bilər.")
        return
    keyboard = [[InlineKeyboardButton("Oyuna Qoşul 🙋‍♂️", callback_data="register_join")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    if 'reg_message_id' not in context.chat_data:
        message = await update.message.reply_text(
            "Oyun üçün qeydiyyat başladı! Qoşulmaq üçün düyməyə basın.",
            reply_markup=reply_markup
        )
        context.chat_data['reg_message_id'] = message.message_id
    else:
        await update.message.reply_text("Qeydiyyat onsuz da aktivdir. Qoşulmaq üçün yuxarıdakı mesaja baxın.")

async def start_game_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id, user_id = update.message.chat_id, update.message.from_user.id
    if not await is_user_admin(chat_id, user_id, context):
        await update.message.reply_text("⛔ Bu əmri yalnız qrup adminləri istifadə edə bilər.")
        return
    players = context.chat_data.get('players', {})
    if len(players) < 2:
        await update.message.reply_text("Oyunun başlaması üçün ən az 2 nəfər qeydiyyatdan keçməlidir.")
        return
    context.chat_data['game_active'] = True
    player_list = list(players.values())
    random.shuffle(player_list)
    context.chat_data['player_list'], context.chat_data['current_player_index'] = player_list, -1
    player_names = ", ".join([p['name'] for p in player_list])
    await update.message.reply_text(f"Oyun başladı! 🚀\n\nİştirakçılar: {player_names}\n\nİlk oyunçu üçün hazırlaşın...")
    await ask_next_player(chat_id, context)

# --- YENİ ƏMR ---
async def next_turn_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sıranı növbəti oyunçuya keçirir (yalnız admin)."""
    chat_id, user_id = update.message.chat_id, update.message.from_user.id

    if not context.chat_data.get('game_active', False):
        await update.message.reply_text("Hazırda aktiv oyun yoxdur.")
        return

    if not await is_user_admin(chat_id, user_id, context):
        await update.message.reply_text("⛔ Sıranı yalnız qrup adminləri dəyişə bilər.")
        return
    
    await update.message.reply_text("Sıra növbəti oyunçuya keçir...")
    await ask_next_player(chat_id, context)

async def stop_game_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id, user_id = update.message.chat_id, update.message.from_user.id
    if not await is_user_admin(chat_id, user_id, context):
        await update.message.reply_text("⛔ Bu əmri yalnız qrup adminləri istifadə edə bilər.")
        return
    context.chat_data.clear()
    await update.message.reply_text("Oyun admin tərəfindən dayandırıldı. Bütün qeydiyyat sıfırlandı. Yenidən başlamaq üçün /qeydiyyat yazın.")

async def join_mid_game_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    if not context.chat_data.get('game_active', False):
        await update.message.reply_text("Hazırda aktiv oyun yoxdur. /qeydiyyat yazaraq yeni oyuna qoşula bilərsiniz.")
        return
    context.chat_data.setdefault('players', {})[user.id] = {'id': user.id, 'name': user.first_name}
    if 'player_list' in context.chat_data:
        context.chat_data['player_list'].append({'id': user.id, 'name': user.first_name})
    await update.message.reply_text(f"Xoş gəldin, {user.first_name}! Sən də oyuna qoşuldun.")

async def leave_game_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    players = context.chat_data.get('players', {})
    if user_id not in players:
        await update.message.reply_text("Siz onsuz da oyunda deyilsiniz.")
        return
    del players[user_id]
    if 'player_list' in context.chat_data:
        context.chat_data['player_list'] = [p for p in context.chat_data['player_list'] if p['id'] != user_id]
    await update.message.reply_text(f"{update.message.from_user.first_name} oyundan ayrıldı.")
    if len(players) < 2 and context.chat_data.get('game_active', False):
        await update.message.reply_text("Oyunçu sayı 2-dən az olduğu üçün oyun dayandırıldı.")
        context.chat_data.clear()

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query, user, data = update.callback_query, update.callback_query.from_user, update.callback_query.data
    await query.answer()
    
    if data == "register_join":
        #... (bu hissə dəyişməyib)
        if context.chat_data.get('game_active', False):
            await query.answer("Oyun artıq başlayıb, /qosul əmri ilə qoşula bilərsiniz.", show_alert=True)
            return
        players = context.chat_data.setdefault('players', {})
        if user.id not in players:
            players[user.id] = {'id': user.id, 'name': user.first_name}
            await query.answer("Uğurla qeydiyyatdan keçdiniz!", show_alert=True)
            player_names = ", ".join([p['name'] for p in players.values()])
            keyboard = [[InlineKeyboardButton("Oyuna Qoşul 🙋‍♂️", callback_data="register_join")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(
                f"Oyun üçün qeydiyyat davam edir!\n\n**Qoşulanlar:** {player_names}\n\nAdminin oyunu başlatmasını gözləyin (/baslat).",
                reply_markup=reply_markup
            )
        else:
            await query.answer("Siz onsuz da qeydiyyatdan keçmisiniz.", show_alert=True)

    elif data.startswith("game_"):
        parts = data.split('_')
        action, target_user_id = parts[1], int(parts[2])
        if user.id != target_user_id:
            await query.answer("⛔ Bu sənin sıran deyil!", show_alert=True)
            return
        
        # --- ƏSAS DƏYİŞİKLİK BURADADIR ---
        command_suggestion = "\n\n*Cavab verildikdən sonra admin növbəti tura keçmək üçün /novbeti yazsın.*"
        response_text = ""

        if action == 'truth':
            response_text = f"📜 {user.first_name} üçün **Doğruluq**:\n\n> {random.choice(TRUTH_QUESTIONS)}"
        elif action == 'dare':
            response_text = f"🔥 {user.first_name} üçün **Cəsarət**:\n\n> {random.choice(DARE_TASKS)}"
        
        # Mesajın sonuna /novbeti təklifini əlavə edirik
        await query.edit_message_text(text=response_text + command_suggestion, parse_mode='Markdown')
        
        # Növbəti oyunçunu avtomatik çağıran kodu isə buradan SİLİRİK.
        # await ask_next_player(query.message.chat_id, context) # <-- BU SƏTİR SİLİNDİ

def main() -> None:
    # ------------------------------------------------------------------
    TOKEN = "7307803335:AAEJhAvvXYYrrVWCfLXwYVI_FI-4pZrY8Gw"
    # ------------------------------------------------------------------
    
    application = Application.builder().token(TOKEN).build()
    
    group_filter = ~filters.ChatType.PRIVATE

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("qeydiyyat", registration_command, filters=group_filter))
    application.add_handler(CommandHandler("baslat", start_game_command, filters=group_filter))
    # YENİ ƏMRİN HANDLER-i ƏLAVƏ EDİLİR
    application.add_handler(CommandHandler("novbeti", next_turn_command, filters=group_filter))
    application.add_handler(CommandHandler("dayandir", stop_game_command, filters=group_filter))
    application.add_handler(CommandHandler("qosul", join_mid_game_command, filters=group_filter))
    application.add_handler(CommandHandler("cix", leave_game_command, filters=group_filter))

    application.add_handler(MessageHandler(filters.ChatType.PRIVATE & (~filters.COMMAND), start_command))
    application.add_handler(CallbackQueryHandler(button_handler))

    print("Bot işə düşdü...")
    application.run_polling()

if __name__ == '__main__':
    main()
