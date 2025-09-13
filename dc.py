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

# Logging, Baza və s. olduğu kimi qalır
# ... (aşağıdakı tam kodda mövcuddur)

# --- YENİ OYUN: İKİ DÜZ, BİR YALAN ---
# ConversationHandler üçün mərhələlər
STATEMENT_1, STATEMENT_2, STATEMENT_3, WHICH_IS_LIE = range(4)

async def two_truths_one_lie_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Oyunçuya şəxsidə yazaraq məlumatları toplamağa başlayır."""
    user = update.message.from_user
    chat_id = update.message.chat_id
    
    # Əgər qrupda artıq bu oyun aktivdirsə, yenisini başlatma
    if context.chat_data.get('ttol_active'):
        await update.message.reply_text("Artıq qrupda aktiv 'İki Düz, Bir Yalan' oyunu var. Lütfən onun bitməsini gözləyin.")
        return

    try:
        # Bota şəxsidə yazmaq üçün linkli düymə
        bot_username = context.bot.username
        start_link = f"https://t.me/{bot_username}?start=ttol_{chat_id}"
        
        keyboard = [[InlineKeyboardButton("Hazırsan? Mənə Şəxsidə Yaz!", url=start_link)]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            f"Salam, {user.first_name}! 'İki Düz, Bir Yalan' oyununa başlamaq üçün aşağıdakı düyməyə basaraq mənə şəxsidə yaz.",
            reply_markup=reply_markup
        )
    except Exception as e:
        logger.error(f"İki Düz Bir Yalan oyununu başlatarkən xəta: {e}")
    return ConversationHandler.END # Qrupdakı söhbət burada bitir

async def ttol_start_in_private(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """İstifadəçi şəxsidə oyuna başladıqda ilk sualı verir."""
    try:
        # Qrup ID-sini start linkindən götürürük
        group_id = int(context.args[0].split('_')[1])
        context.user_data['ttol_group_id'] = group_id
    except (IndexError, ValueError):
        await update.message.reply_text("Xəta baş verdi. Zəhmət olmasa, oyunu qrupdan yenidən başladın.")
        return ConversationHandler.END

    await update.message.reply_text("Əla! İndi özün haqqında 1-ci iddianı yaz (doğru və ya yalan ola bilər).")
    return STATEMENT_1

async def receive_statement1(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['ttol_s1'] = update.message.text
    await update.message.reply_text("Gözəl! İndi 2-ci iddianı yaz.")
    return STATEMENT_2

async def receive_statement2(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['ttol_s2'] = update.message.text
    await update.message.reply_text("Super! Və nəhayət, 3-cü iddianı yaz.")
    return STATEMENT_3

async def receive_statement3(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['ttol_s3'] = update.message.text
    keyboard = [
        [InlineKeyboardButton("1-ci iddia yalandır", callback_data="ttol_lie_1")],
        [InlineKeyboardButton("2-ci iddia yalandır", callback_data="ttol_lie_2")],
        [InlineKeyboardButton("3-cü iddia yalandır", callback_data="ttol_lie_3")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Mükəmməl! İndi isə bunlardan hansının yalan olduğunu düyməyə basaraq seç.", reply_markup=reply_markup)
    return WHICH_IS_LIE

async def receive_which_is_lie(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    lie_index = int(query.data.split('_')[-1])
    
    s1 = context.user_data['ttol_s1']
    s2 = context.user_data['ttol_s2']
    s3 = context.user_data['ttol_s3']
    group_id = context.user_data['ttol_group_id']
    
    statements = [s1, s2, s3]
    random.shuffle(statements) # İddiaların yerini qarışdırırıq
    
    # Yalanın yeni yerini tapırıq
    lie_statement_text = context.user_data[f'ttol_s{lie_index}']
    new_lie_index = statements.index(lie_statement_text) + 1
    
    context.chat_data['ttol_active'] = True
    context.chat_data['ttol_author'] = query.from_user.first_name
    context.chat_data['ttol_lie_index'] = new_lie_index
    context.chat_data['ttol_votes'] = {} # Səsləri saxlamaq üçün

    keyboard = [
        [InlineKeyboardButton(f"1-ci İddia", callback_data="ttol_vote_1")],
        [InlineKeyboardButton(f"2-ci İddia", callback_data="ttol_vote_2")],
        [InlineKeyboardButton(f"3-cü İddia", callback_data="ttol_vote_3")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text("Məlumatlar qəbul edildi! İndi oyunu qrupda yayımlayıram...")
    
    game_text = (
        f"Yeni oyun başladı! 🤔\n\n**{query.from_user.first_name}** adlı istifadəçi özü haqqında 3 iddia göndərdi. Sizcə bunlardan hansı yalandır?\n\n"
        f"1. {statements[0]}\n"
        f"2. {statements[1]}\n"
        f"3. {statements[2]}\n\n"
        "Yalan olanı tapmaq üçün 60 saniyəniz var!"
    )
    
    sent_message = await context.bot.send_message(chat_id=group_id, text=game_text, reply_markup=reply_markup)
    
    # 60 saniyə sonra nəticələri elan et
    context.job_queue.run_once(finish_ttol_game, 60, chat_id=group_id, name=f'ttol_{group_id}')
    
    # Məlumatları təmizlə
    for key in ['ttol_group_id', 'ttol_s1', 'ttol_s2', 'ttol_s3']:
        context.user_data.pop(key, None)
        
    return ConversationHandler.END

async def finish_ttol_game(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    chat_id = job.chat_id
    
    chat_data = context.chat_data
    if not chat_data.get('ttol_active'): return

    author = chat_data['ttol_author']
    lie_index = chat_data['ttol_lie_index']
    votes = chat_data['ttol_votes']
    
    # Səsvermə nəticələrini formatlayırıq
    results_text = "\n\n**Nəticələr:**\n"
    if not votes:
        results_text += "Heç kim səs vermədi."
    else:
        for user_name, vote in votes.items():
            emoji = "✅" if vote == lie_index else "❌"
            results_text += f"- {user_name}: {vote}-ci iddianı seçdi {emoji}\n"
            
    await context.bot.send_message(
        chat_id=chat_id,
        text=f"Vaxt bitdi! ⌛️\n\n**{author}** haqqında yalan olan iddia **{lie_index}-ci** idi!" + results_text
    )
    
    # Oyun statusunu təmizlə
    for key in ['ttol_active', 'ttol_author', 'ttol_lie_index', 'ttol_votes']:
        chat_data.pop(key, None)


async def ttol_vote_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    
    if not context.chat_data.get('ttol_active'):
        await query.answer("Bu oyun artıq bitib.", show_alert=True)
        return

    # İstifadəçinin artıq səs verib-vermədiyini yoxlayırıq
    if user.id in context.chat_data['ttol_votes']:
        await query.answer("Siz artıq səs vermisiniz.", show_alert=True)
        return
        
    vote = int(query.data.split('_')[-1])
    context.chat_data['ttol_votes'][user.first_name] = vote
    await query.answer(f"Səsiniz qəbul edildi! {vote}-ci iddianı seçdiniz.", show_alert=False)

# ... (qalan bütün köhnə funksiyalar olduğu kimi qalır)

def main() -> None:
    # ...
    # YENİ CONVERSATION HANDLER
    ttol_conv_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex('^/start ttol_'), ttol_start_in_private)],
        states={
            STATEMENT_1: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_statement1)],
            STATEMENT_2: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_statement2)],
            STATEMENT_3: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_statement3)],
            WHICH_IS_LIE: [CallbackQueryHandler(receive_which_is_lie, pattern='^ttol_lie_')]
        },
        fallbacks=[]
    )
    application.add_handler(ttol_conv_handler)
    application.add_handler(CommandHandler("yalan_tap", two_truths_one_lie_command, filters=group_filter))
    # ...
    # YENİ CALLBACK HANDLER
    application.add_handler(CallbackQueryHandler(ttol_vote_callback, pattern='^ttol_vote_'))
    # ...
