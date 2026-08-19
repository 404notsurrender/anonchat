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
from fastapi import FastAPI
import uvicorn

# Logging
logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)

TOKEN = os.environ.get("TELEGRAM_TOKEN")
PORT = int(os.environ.get("PORT", 7860))

waiting_queue = []
active_chats = {}

# Keyboard Menu
menu_idle = ReplyKeyboardMarkup([["🔍 Cari Partner"]], resize_keyboard=True)
menu_chat = ReplyKeyboardMarkup([["⏭️ Next Partner", "❌ Keluar / Stop"]], resize_keyboard=True)

app = FastAPI()
telegram_app = None

@app.get("/")
def home():
    return {"status": "Bot Anonymous Chat (Next Feature) is alive!"}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await update.message.reply_text(
        f"Halo, {user.first_name}! Selamat datang di Bot Anonymous Chat.\n\n"
        "Tekan tombol di bawah untuk mulai mencari teman ngobrol secara anonim.",
        reply_markup=menu_idle
    )

async def search_partner(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id in active_chats:
        await update.message.reply_text("Kamu sedang mengobrol dengan seseorang!", reply_markup=menu_chat)
        return
    if user_id in waiting_queue:
        await update.message.reply_text("Kamu sudah berada di antrean. Mohon tunggu...", reply_markup=menu_idle)
        return

    if waiting_queue:
        partner_id = waiting_queue.pop(0)
        
        active_chats[user_id] = partner_id
        active_chats[partner_id] = user_id

        await context.bot.send_message(chat_id=user_id, text="🎉 Partner ditemukan! Silakan mulai mengobrol.", reply_markup=menu_chat)
        await context.bot.send_message(chat_id=partner_id, text="🎉 Partner ditemukan! Silakan mulai mengobrol.", reply_markup=menu_chat)
    else:
        waiting_queue.append(user_id)
        await update.message.reply_text("🔍 Sedang mencari partner... Mohon tunggu sampai ada yang terhubung.", reply_markup=menu_idle)

async def stop_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id in waiting_queue:
        waiting_queue.remove(user_id)
        await update.message.reply_text("Pencarian dibatalkan.", reply_markup=menu_idle)
        return

    if user_id in active_chats:
        partner_id = active_chats[user_id]

        del active_chats[user_id]
        del active_chats[partner_id]

        await update.message.reply_text("🛑 Percakapan diakhiri.", reply_markup=menu_idle)
        await context.bot.send_message(
            chat_id=partner_id, 
            text="⚠️ Partner telah meninggalkan percakapan.",
            reply_markup=menu_idle
        )
    else:
        await update.message.reply_text("Kamu tidak sedang terhubung dengan siapa pun.", reply_markup=menu_idle)

async def next_partner(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    # 1. Putus dulu dengan partner lama jika ada
    if user_id in active_chats:
        partner_id = active_chats[user_id]
        del active_chats[user_id]
        if partner_id in active_chats:
            del active_chats[partner_id]

        # Beritahu partner lama
        await context.bot.send_message(
            chat_id=partner_id,
            text="⚠️ Partner meninggalkan percakapan (Skip).",
            reply_markup=menu_idle
        )

    # 2. Hapus dari antrean jika kebetulan ada
    if user_id in waiting_queue:
        waiting_queue.remove(user_id)

    # 3. Langsung cari partner baru
    await update.message.reply_text("🔄 Mencari partner baru...", reply_markup=menu_idle)
    await search_partner(update, context)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text

    if text == "🔍 Cari Partner":
        await search_partner(update, context)
        return
    elif text == "❌ Keluar / Stop":
        await stop_chat(update, context)
        return
    elif text == "⏭️ Next Partner":
        await next_partner(update, context)
        return

    if user_id in active_chats:
        partner_id = active_chats[user_id]
        await context.bot.send_message(chat_id=partner_id, text=text)
    else:
        await update.message.reply_text("Ketik 'Cari Partner' untuk mulai mencari teman ngobrol!", reply_markup=menu_idle)

@app.on_event("startup")
async def startup_event():
    global telegram_app
    if not TOKEN:
        logging.error("TELEGRAM_TOKEN tidak ditemukan!")
        return
    
    telegram_app = ApplicationBuilder().token(TOKEN).build()
    telegram_app.add_handler(CommandHandler("start", start))
    telegram_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    await telegram_app.initialize()
    await telegram_app.start()
    await telegram_app.updater.start_polling()
    logging.info("Telegram Bot started with Next Partner feature!")

@app.on_event("shutdown")
async def shutdown_event():
    if telegram_app:
        await telegram_app.updater.stop()
        await telegram_app.stop()
        await telegram_app.shutdown()
        logging.info("Telegram Bot stopped.")

if __name__ == "__main__":
    uvicorn.run("bot:app", host="0.0.0.0", port=PORT, reload=False)
