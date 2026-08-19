import os
import logging
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
from fastapi import FastAPI, Request
import uvicorn
import asyncio
from threading import Thread

# Logging
logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)

TOKEN = os.environ.get("TELEGRAM_TOKEN")
PORT = int(os.environ.get("PORT", 7860))

waiting_queue = []
active_chats = {}

main_menu_keyboard = ReplyKeyboardMarkup(
    [["🔍 Cari Partner", "❌ Keluar / Stop"]],
    resize_keyboard=True
)

app = FastAPI()

@app.get("/")
def home():
    return {"status": "Bot is alive!"}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await update.message.reply_text(
        f"Halo, {user.first_name}! Selamat datang di Bot Anonymous Chat.\n\n"
        "Tekan tombol di bawah untuk mulai mencari teman ngobrol secara anonim.",
        reply_markup=main_menu_keyboard
    )

async def search_partner(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id in active_chats:
        await update.message.reply_text("Kamu sedang mengobrol dengan seseorang!")
        return
    if user_id in waiting_queue:
        await update.message.reply_text("Kamu sudah berada di antrean...")
        return

    if waiting_queue:
        partner_id = waiting_queue.pop(0)
        active_chats[user_id] = partner_id
        active_chats[partner_id] = user_id
        await context.bot.send_message(chat_id=user_id, text="🎉 Partner ditemukan!")
        await context.bot.send_message(chat_id=partner_id, text="🎉 Partner ditemukan!")
    else:
        waiting_queue.append(user_id)
        await update.message.reply_text("🔍 Mencari partner...")

async def stop_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id in waiting_queue:
        waiting_queue.remove(user_id)
        await update.message.reply_text("Pencarian dibatalkan.", reply_markup=main_menu_keyboard)
        return
    if user_id in active_chats:
        partner_id = active_chats[user_id]
        del active_chats[user_id]
        del active_chats[partner_id]
        await update.message.reply_text("🛑 Percakapan diakhiri.", reply_markup=main_menu_keyboard)
        await context.bot.send_message(chat_id=partner_id, text="⚠️ Partner meninggalkan percakapan.", reply_markup=main_menu_keyboard)
    else:
        await update.message.reply_text("Kamu tidak sedang terhubung dengan siapa pun.", reply_markup=main_menu_keyboard)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text
    if text == "🔍 Cari Partner":
        await search_partner(update, context)
        return
    elif text == "❌ Keluar / Stop":
        await stop_chat(update, context)
        return

    if user_id in active_chats:
        partner_id = active_chats[user_id]
        await context.bot.send_message(chat_id=partner_id, text=text)
    else:
        await update.message.reply_text("Ketik 'Cari Partner' untuk mulai!")

def run_bot():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    application = ApplicationBuilder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    logging.info("Bot starting polling...")
    application.run_polling()

if __name__ == "__main__":
    # Jalankan bot di background thread agar FastAPI tetap hidup (cocok untuk Hugging Face / Render Web Service)
    t = Thread(target=run_bot)
    t.start()
    uvicorn.run(app, host="0.0.0.0", port=PORT)
