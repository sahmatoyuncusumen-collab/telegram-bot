import logging
import random
import os
import psycopg2
import datetime
import sys
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters, PollHandler
from telegram.constants import ChatType

# Logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# --- BAZA VƏ ƏSAS DƏYİŞƏNLƏR ---
DATABASE_URL = os.environ.get("DATABASE_URL")
TOKEN = os.environ.get("TELEGRAM_TOKEN")

# ... (init_db, sual siyahıları, get_rank_title və s. köhnə funksiyalar olduğu kimi qalır)

# --- YENİLƏNMİŞ MACƏRA HEKAYƏSİ (İnventar ilə) ---
STORY_DATA = {
    'start': {
        'text': "Siz qədim bir məbədin girişində dayanmısınız. Hava qaralır. İki yol var: soldakı mamırlı daşlarla örtülmüş cığır və sağdakı qaranlıq mağara girişi. Qrup olaraq qərar verin:",
        'choices': [
            {'text': "🌳 Sol cığırla gedək", 'goto': 'forest_path'},
            {'text': "🦇 Mağaraya daxil olaq", 'goto': 'cave_entrance'}
        ]
    },
    'forest_path': {
        'text': "Cığırla irəliləyərək üzərində qədim işarələr olan böyük bir daş qapıya çatırsınız. Qapı bağlıdır və ortasında böyük bir açar yeri var. Nə edirsiniz?",
        'choices': [
            {'text': "🔑 Qədim açarı istifadə edək", 'goto': 'open_door', 'requires_item': 'qədim açar'},
            {'text': " geri dönək", 'goto': 'go_back'}
        ]
    },
    'cave_entrance': {
        'text': "Qaranlıq mağaraya daxil olursunuz. Divardan asılmış köhnə bir açar gözünüzə dəyir. Onu götürürsünüz.",
        'get_item': 'qədim açar',
        'choices': [
            {'text': "Açarla birlikdə geri dönək", 'goto': 'get_key'}
        ]
    },
    'get_key': {
        'text': "Artıq qrupun inventarında köhnə, paslı bir açar var. Bu, bəzi qapıları aça bilər. İndi hara gedirsiniz?",
        'choices': [
            {'text': "🌳 Meşədəki qapını yoxlayaq", 'goto': 'forest_path'},
            {'text': "🧭 Məbədin girişinə qayıdaq", 'goto': 'start'}
        ]
    },
    'open_door': {
        'text': "Açarı istifadə edirsiniz. Qədim mexanizm işə düşür və daş qapı yavaşca açılır. İçəridə parlayan bir qılıncın olduğu xəzinə otağı görünür! Qrup olaraq qılıncı götürürsünüz.",
        'get_item': 'əfsanəvi qılınc',
        'choices': [
            {'text': "⚔️ Qılıncı götürək!", 'goto': 'treasure_found'}
        ]
    },
    'treasure_found': {
        'text': "Əfsanəvi qılıncı əldə etdiniz! Macəranız uğurla başa çatdı. Qrup olaraq qalib gəldiniz! 🏆\n\nYeni macəra üçün /macera yazın.",
        'choices': []
    },
    'go_back': {
        'text': "Açarınız olmadığı üçün geri qayıtmaqdan başqa çarəniz yoxdur. Bəlkə də başqa yerdə bir ipucu taparsınız. Məbədin girişinə qayıtdınız.",
        'choices': [
            {'text': "🦇 Mağaraya daxil olaq", 'goto': 'cave_entrance'}
        ]
    }
}

# --- YENİ VƏ YENİLƏNMİŞ FUNKSİYALAR ---

async def show_rpg_node(context: ContextTypes.DEFAULT_TYPE, chat_id: int, node_key: str):
    """Verilmiş hekayə düyümünü (səsvermə və mətn) göstərir."""
    node = STORY_DATA.get(node_key)
    if not node: return

    inventory = context.chat_data.get('rpg_inventory', set())
    if node.get('get_item'):
        inventory.add(node['get_item'])
        context.chat_data['rpg_inventory'] = inventory

    text = node['text']
    choices = node['choices']
    
    # Əgər hekayə bitibsə, son mesajı göndər və bitir
    if not choices:
        await context.bot.send_message(chat_id, text)
        context.chat_data.pop('rpg_inventory', None)
        context.chat_data.pop('active_poll', None)
        return

    # Səsvermə üçün seçimləri hazırla (inventara görə)
    poll_options = []
    choices_map = {}
    for choice in choices:
        if 'requires_item' in choice:
            if choice['requires_item'] in inventory:
                poll_options.append(choice['text'])
                choices_map[choice['text']] = choice['goto']
        else:
            poll_options.append(choice['text'])
            choices_map[choice['text']] = choice['goto']

    if not poll_options:
        await context.bot.send_message(chat_id, "Görünür, davam etmək üçün doğru əşyanız yoxdur. Məğlub oldunuz. 😔")
        context.chat_data.pop('rpg_inventory', None)
        return
        
    poll_message = await context.bot.send_poll(
        chat_id=chat_id,
        question=text,
        options=poll_options,
        is_anonymous=False,
        allows_multiple_answers=False,
        open_period=60 # Səsvermə 60 saniyə davam edəcək
    )
    
    # Səsvermənin nəticəsini izləmək üçün məlumatları yadda saxlayırıq
    context.chat_data['active_poll'] = {
        'poll_id': poll_message.poll.id,
        'chat_id': chat_id,
        'choices_map': choices_map
    }

async def macera_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Macəra oyununu başladır və inventarı sıfırlayır."""
    context.chat_data.pop('rpg_inventory', None)
    context.chat_data.pop('active_poll', None)
    await show_rpg_node(context, update.message.chat_id, 'start')

async def receive_poll_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Səsvermə bitdikdə nəticəni emal edir."""
    poll_data = context.chat_data.get('active_poll')
    if not poll_data or update.poll.id != poll_data['poll_id']:
        return

    # Səsvermənin bitdiyini və nəticələrin olduğunu yoxlayırıq
    if update.poll.is_closed:
        winning_option = None
        max_votes = -1
        
        for option in update.poll.options:
            if option.voter_count > max_votes:
                max_votes = option.voter_count
                winning_option = option.text
        
        # Səsvermə bitdikdən sonra məlumatları təmizləyirik
        context.chat_data.pop('active_poll', None)

        if winning_option:
            next_node_key = poll_data['choices_map'].get(winning_option)
            await context.bot.send_message(poll_data['chat_id'], f"🗳️ Səsvermə bitdi! Ən çox səsi '{winning_option}' seçimi topladı. Hekayə davam edir...")
            await show_rpg_node(context, poll_data['chat_id'], next_node_key)
        else:
            await context.bot.send_message(poll_data['chat_id'], "Heç kim səs vermədiyi üçün macəra dayandırıldı.")
            context.chat_data.pop('rpg_inventory', None)


# --- Bütün Dəyişikliklərlə Birlikdə Tam Kod (BUNU KOPYALAYIN) ---
import logging, random, os, psycopg2, datetime, sys
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters, PollHandler
from telegram.constants import ChatType

# ... (yuxarıdakı bütün məzmun və funksiyalar)
def main() -> None:
    run_pre_flight_checks()
    init_db()
    application = Application.builder().token(TOKEN).build()
    group_filter = ~filters.ChatType.PRIVATE
    
    # Əmrlər
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("qaydalar", qaydalar_command))
    application.add_handler(CommandHandler("macera", macera_command, filters=group_filter)) # YENİ
    # ... (köhnə əmrlər)

    # Handler-lər
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(PollHandler(receive_poll_update)) # YENİ
    # ... (köhnə handler-lər)
    
    print("Bot işə düşdü...")
    application.run_polling()

if __name__ == '__main__':
    main()
