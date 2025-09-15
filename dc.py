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
# ... (dəyişməz qalır)

# --- BAZA FUNKSİYALARI ---
# ... (bütün baza funksiyaları dəyişməz qalır)

# --- MƏZMUN SİYAHILARI ---
ABOUT_TEXT = "..."
RULES_TEXT = "..."

# VIKTORINA SUALLARI (40 Sadə + 80 Premium)
SADE_QUIZ_QUESTIONS = [
    # ... (sual siyahılarınız burada tam şəkildə qalır) ...
]
PREMIUM_QUIZ_QUESTIONS = [
    # ... (sual siyahılarınız burada tam şəkildə qalır) ...
]

# DOĞRULUQ VƏ CƏSARƏT SUALLARI (Başlanğıc Paketi)
SADE_TRUTH_QUESTIONS = ["Uşaqlıqda ən böyük qorxun nə olub?", "Heç kimin bilmədiyi bir bacarığın var?", "Ən son nə vaxt ağlamısan və niyə?", "Əgər bir gün görünməz olsaydın, nə edərdin?", "Telefonunda ən utancverici proqram hansıdır?"]
SADE_DARE_TASKS = ["Qrupdakı son mesajı əlifbanın hər hərfi ilə tərsinə yaz.", "Telefonundakı son şəkli qrupa göndər (uyğun deyilsə, ondan əvvəlkini).", "Qrupdakı birinə kompliment de.", "Profil şəklini 5 dəqiqəlik bir meyvə şəkli ilə dəyişdir.", "Ən sevdiyin mahnıdan bir hissəni səsli mesajla göndər."]
PREMIUM_TRUTH_QUESTIONS = ["Həyatının geri qalanını yalnız bir filmi izləyərək keçirməli olsaydın, hansı filmi seçərdin?", "Əgər zaman maşının olsaydı, keçmişə yoxsa gələcəyə gedərdin? Niyə?", "Sənə ən çox təsir edən kitab hansı olub?", "Münasibətdə sənin üçün ən vacib 3 şey nədir?", "Özündə dəyişdirmək istədiyin bir xüsusiyyət hansıdır?"]
PREMIUM_DARE_TASKS = ["Qrupdakı adminlərdən birinə 10 dəqiqəlik \"Ən yaxşı admin\" statusu yaz.", "Səni ən yaxşı təsvir edən bir \"meme\" tap və qrupa göndər.", "Səsini dəyişdirərək bir nağıl personajı kimi danış və səsli mesaj göndər.", "Google-da \"Mən niyə bu qədər möhtəşəməm\" yazıb axtarış nəticələrinin şəklini göndər.", "Profil bioqrafiyanı 15 dəqiqəlik \"Bu qrupun premium üzvü\" olaraq dəyişdir."]


# --- KÖMƏKÇİ FUNKSİYALAR ---
async def is_user_admin(chat_id: int, user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    # ... (dəyişməz qalır)
    pass
def get_rank_title(count: int, is_premium: bool = False) -> str:
    # ... (dəyişməz qalır)
    pass
async def welcome_new_members(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ... (dəyişməz qalır)
    pass

# --- ƏSAS ƏMRLƏR ---
# ... (start, haqqinda, qaydalar, my_rank_command, zer, liderler dəyişməz qalır)

# YENİLİK: Doğruluq/Cəsarət oyunu
async def dcoyun_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    chat_id = update.message.chat.id
    
    if update.message.chat.type == ChatType.PRIVATE:
        await update.message.reply_text("Bu oyunu yalnız qruplarda oynamaq olar.")
        return
        
    if not await is_user_admin(chat_id, user_id, context):
        await update.message.reply_text("⛔ Bu oyunu yalnız qrup adminləri başlada bilər.")
        return
    
    if context.chat_data.get('dc_game_active'):
        await update.message.reply_text("Artıq aktiv bir 'Doğruluq yoxsa Cəsarət?' oyunu var.")
        return
        
    # Oyunu başladan şəxsi yadda saxlayaq
    context.chat_data['dc_game_starter_id'] = user_id
        
    keyboard = [
        [InlineKeyboardButton("Doğruluq Cəsarət (sadə)", callback_data="dc_select_sade")],
        [InlineKeyboardButton("Doğruluq Cəsarət (Premium👑)", callback_data="dc_select_premium")]
    ]
    await update.message.reply_text(
        "Doğruluq Cəsarət oyununa xoş gəlmisiniz👋",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# --- ADMİN ƏMRLƏRİ ---
# ... (addpremium, removepremium dəyişməz qalır)

# --- VIKTORINA ƏMRİ VƏ OYUN MƏNTİQİ ---
# ... (viktorina_command və ask_next_quiz_question dəyişməz qalır)
    
# DÜYMƏLƏRİ VƏ MESAJLARI İDARƏ EDƏN FUNKSİYALAR
async def show_dc_registration_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Qeydiyyat mesajını göstərən və yeniləyən köməkçi funksiya"""
    message = update.callback_query.message
    players = context.chat_data.get('dc_players', [])
    player_list_text = "\n\n**Qeydiyyatdan keçənlər:**\n"
    if not players:
        player_list_text += "Heç kim qoşulmayıb."
    else:
        for player in players:
            player_list_text += f"- [{player['name']}](tg://user?id={player['id']})\n"
            
    keyboard = [
        [InlineKeyboardButton("Qeydiyyatdan Keç ✅", callback_data="dc_register")],
        [InlineKeyboardButton("Oyunu Başlat ▶️", callback_data="dc_start_game")],
        [InlineKeyboardButton("Oyunu Ləğv Et ⏹️", callback_data="dc_stop_game")]
    ]
    
    await message.edit_text(
        "**Doğruluq yoxsa Cəsarət?**\n\nOyun başlayır! Oyuna qoşulmaq üçün 'Qeydiyyatdan Keç' düyməsinə basın." + player_list_text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN
    )

async def dc_next_turn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Oyun zamanı növbəti oyunçuya keçidi təmin edən funksiya"""
    message = update.callback_query.message
    
    current_index = context.chat_data.get('dc_current_player_index', -1)
    players = context.chat_data.get('dc_players', [])
    
    next_index = (current_index + 1) % len(players)
    context.chat_data['dc_current_player_index'] = next_index
    
    current_player = players[next_index]
    player_id = current_player['id']
    player_name = current_player['name']
    
    is_premium = context.chat_data.get('dc_is_premium', False)
    
    truth_callback = "dc_ask_truth_premium" if is_premium else "dc_ask_truth_sade"
    dare_callback = "dc_ask_dare_premium" if is_premium else "dc_ask_dare_sade"
    
    keyboard = [
        [InlineKeyboardButton("Doğruluq 🤔", callback_data=truth_callback)],
        [InlineKeyboardButton("Cəsarət 😈", callback_data=dare_callback)]
    ]
    
    await message.edit_text(
        f"Sıra sənə çatdı, [{player_name}](tg://user?id={player_id})! Seçimini et:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN
    )


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; user = query.from_user; data = query.data
    chat_id = query.message.chat.id
    await query.answer()

    # Viktorina kilidi...
    if data.startswith("viktorina_") or data.startswith("quiz_"):
        # ... (viktorina məntiqi dəyişməz qalır)
        pass

    # Start menyusu...
    elif data in ["start_info_about", "start_info_qaydalar", "back_to_start"]:
        # ... (dəyişməz qalır)
        pass
    
    # --- YENİ: DOĞRULUQ/CƏSARƏT OYUN MƏNTİQİ ---
    elif data.startswith('dc_select_'):
        game_starter_id = context.chat_data.get('dc_game_starter_id')
        if user.id != game_starter_id:
            await query.answer("⛔ Yalnız oyunu başladan admin rejim seçə bilər.", show_alert=True)
            return

        is_premium_choice = (data == 'dc_select_premium')
        if is_premium_choice and not is_user_premium(user.id):
            await query.answer("⛔ Bu rejimi yalnız premium statuslu adminlər başlada bilər.", show_alert=True)
            return

        context.chat_data.update({
            'dc_game_active': True,
            'dc_is_premium': is_premium_choice,
            'dc_players': [],
            'dc_current_player_index': -1,
        })
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
        game_starter_id = context.chat_data.get('dc_game_starter_id')
        if user.id != game_starter_id:
            await query.answer("⛔ Oyunu yalnız onu başladan admin başlada bilər.", show_alert=True)
            return
            
        players = context.chat_data.get('dc_players', [])
        if len(players) < 2:
            await query.answer("⛔ Oyunun başlaması üçün minimum 2 nəfər qeydiyyatdan keçməlidir.", show_alert=True)
            return
            
        random.shuffle(players) # Oyunçuları qarışdır
        context.chat_data['dc_players'] = players
        await dc_next_turn(update, context)
        
    elif data == 'dc_stop_game':
        game_starter_id = context.chat_data.get('dc_game_starter_id')
        if user.id != game_starter_id:
            await query.answer("⛔ Oyunu yalnız onu başladan admin ləğv edə bilər.", show_alert=True)
            return
            
        await query.message.edit_text("Oyun admin tərəfindən ləğv edildi.")
        # dc_ ilə başlayan bütün datanı təmizlə
        for key in list(context.chat_data):
            if key.startswith('dc_'):
                del context.chat_data[key]
                
    elif data.startswith('dc_ask_'):
        players = context.chat_data.get('dc_players', [])
        current_index = context.chat_data.get('dc_current_player_index', -1)
        current_player = players[current_index]
        
        if user.id != current_player['id']:
            await query.answer("⛔ Bu sənin sıran deyil!", show_alert=True)
            return
            
        is_premium = context.chat_data.get('dc_is_premium', False)
        
        if 'truth' in data:
            question = random.choice(PREMIUM_TRUTH_QUESTIONS if is_premium else SADE_TRUTH_QUESTIONS)
            text = f"🤔 **Doğruluq:**\n\n`{question}`"
        else: # dare
            task = random.choice(PREMIUM_DARE_TASKS if is_premium else SADE_DARE_TASKS)
            text = f"😈 **Cəsarət:**\n\n`{task}`"
            
        keyboard = [[InlineKeyboardButton("Növbəti Oyunçu ➡️", callback_data="dc_next_turn")]]
        await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)

    elif data == 'dc_next_turn':
        game_starter_id = context.chat_data.get('dc_game_starter_id')
        if not await is_user_admin(chat_id, user.id, context):
             await query.answer("⛔ Növbəti sıraya yalnız adminlər keçirə bilər.", show_alert=True)
             return
        await dc_next_turn(update, context)

    # Viktorina oyunu...
    elif data == 'viktorina_sade' or data == 'viktorina_premium':
        # ... (dəyişməz qalır)
        pass
    elif context.chat_data.get('quiz_active'):
        # ... (viktorina məntiqi dəyişməz qalır)
        pass

# --- Bütün digər funksiyalar (handle_all_messages, main, if __name__...) dəyişməz qalır ---
