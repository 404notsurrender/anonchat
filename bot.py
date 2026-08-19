import os
import logging
import sqlite3
from datetime import datetime
from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)
from fastapi import FastAPI
import uvicorn

# Logging
logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)

TOKEN = os.environ.get("TELEGRAM_TOKEN")
PORT = int(os.environ.get("PORT", 7860))

# --- DATABASE SETUP (SQLite) ---
DB_FILE = "bot_database.db"

def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    # Tabel User dengan tambahan kolom gender
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            gender TEXT DEFAULT NULL,
            is_premium INTEGER DEFAULT 0,
            premium_expired TEXT
        )
    """)
    conn.commit()
    conn.close()
    logging.info("Database SQLite (bot_database.db) dengan kolom gender berhasil diinisialisasi!")

init_db()

def get_or_create_user(user_id, username):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, gender, is_premium, premium_expired FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    
    if not row:
        cursor.execute("INSERT INTO users (user_id, username, gender, is_premium) VALUES (?, ?, NULL, 0)", (user_id, username))
        conn.commit()
        row = (user_id, None, 0, None)
    
    conn.close()
    return row

def update_user_gender(user_id, gender):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET gender = ? WHERE user_id = ?", (gender, user_id))
    conn.commit()
    conn.close()

def check_user_premium(user_id):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT is_premium, premium_expired FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    
    if row and row[0] == 1:
        if row[1]:
            expired_date = datetime.strptime(row[1], "%Y-%m-%d %H:%M:%S")
            if datetime.now() > expired_date:
                conn = sqlite3.connect(DB_FILE)
                c = conn.cursor()
                c.execute("UPDATE users SET is_premium = 0, premium_expired = NULL WHERE user_id = ?", (user_id,))
                conn.commit()
                conn.close()
                return False
        return True
    return False

# --- STATE APPS ---
waiting_queue = [] # List berisi user_id yang sedang mencari partner
active_chats = {}  # Mapping user_id <-> partner_id

# Keyboard Menu
menu_idle = ReplyKeyboardMarkup([["🔍 Cari Partner", "💎 Cek Status VIP"]], resize_keyboard=True)
menu_chat = ReplyKeyboardMarkup([["⏭️ Next Partner", "❌ Keluar / Stop"]], resize_keyboard=True)

app = FastAPI()
telegram_app = None

@app.get("/")
def home():
    return {"status": "Bot Anonymous Chat with Gender & SQLite is alive!"}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_data = get_or_create_user(user.id, user.username)
    gender = user_data[1]

    # Jika belum set gender, tampilkan pilihan gender via Inline Keyboard
    if not gender:
        keyboard = [
            [
                InlineKeyboardButton("👨 Cowok", callback_data="gender_cowok"),
                InlineKeyboardButton("👩 Cewek", callback_data="gender_cewek")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            f"Halo, {user.first_name}! Selamat datang di Bot Anonymous Chat.\n\n"
            "Sebelum mulai, pilih jenis kelamin kamu terlebih dahulu ya:",
            reply_markup=reply_markup
        )
        return

    is_vip = check_user_premium(user.id)
    badge = "👑 [VIP Member]" if is_vip else "🌱 [Free User]"
    
    await update.message.reply_text(
        f"Halo, {user.first_name}! {badge}\nJenis Kelamin: **{gender.capitalize()}**\n\n"
        "Tekan tombol di bawah untuk mulai mencari teman ngobrol secara anonim.",
        reply_markup=menu_idle
    )

async def gender_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    selected_gender = "cowok" if query.data == "gender_cowok" else "cewek"
    
    update_user_gender(user_id, selected_gender)
    
    await query.edit_message_text(
        text=f"✅ Berhasil! Jenis kelamin kamu diset sebagai: **{selected_gender.capitalize()}**.\n\n"
             "Sekarang ketik /start atau gunakan tombol di bawah untuk mulai mencari partner!"
    )
    await context.bot.send_message(
        chat_id=user_id,
        text="Silakan tekan tombol di bawah untuk mulai:",
        reply_markup=menu_idle
    )

async def status_vip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT is_premium, premium_expired FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()

    if row and row[0] == 1:
        await update.message.reply_text(f"💎 Status Kamu: **VIP MEMBER**\n⏳ Berakhir pada: {row[1]}", parse_mode="Markdown")
    else:
        await update.message.reply_text(
            "🌱 Status Kamu: **Free User**\n\n"
            "Nikmati fitur prioritas antrean, bebas pilih filter gender, dan keuntungan eksklusif lainnya dengan upgrade ke VIP! 🚀"
        )

async def search_partner(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    # Pastikan user sudah set gender
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT gender FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    
    if not row or not row[0]:
        await update.message.reply_text("⚠️ Silakan kirim /start terlebih dahulu untuk memilih jenis kelamin kamu.")
        return

    my_gender = row[0]

    if user_id in active_chats:
        await update.message.reply_text("Kamu sedang mengobrol dengan seseorang!", reply_markup=menu_chat)
        return
    if user_id in waiting_queue:
        await update.message.reply_text("Kamu sudah berada di antrean. Mohon tunggu...", reply_markup=menu_idle)
        return

    is_vip = check_user_premium(user_id)

    # Sistem Matching Lawan Jenis (Free User prioritaskan lawan jenis jika ada di queue)
    matched_partner_id = None
    for queued_id in waiting_queue:
        # Cek gender user yang ada di antrean
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("SELECT gender FROM users WHERE user_id = ?", (queued_id,))
        q_row = c.fetchone()
        conn.close()

        if q_row and q_row[0] != my_gender:
            matched_partner_id = queued_id
            break

    # Jika tidak ketemu lawan jenis atau antrean kosong, ambil antrean pertama (atau random)
    if not matched_partner_id and waiting_queue:
        matched_partner_id = waiting_queue[0]

    if matched_partner_id:
        waiting_queue.remove(matched_partner_id)
        
        active_chats[user_id] = matched_partner_id
        active_chats[matched_partner_id] = user_id

        await context.bot.send_message(chat_id=user_id, text="🎉 Partner ditemukan! Silakan mulai mengobrol.", reply_markup=menu_chat)
        await context.bot.send_message(chat_id=matched_partner_id, text="🎉 Partner ditemukan! Silakan mulai mengobrol.", reply_markup=menu_chat)
    else:
        if is_vip:
            waiting_queue.insert(0, user_id)
            await update.message.reply_text("👑 [VIP Priority] Mencari partner...", reply_markup=menu_idle)
        else:
            waiting_queue.append(user_id)
            await update.message.reply_text("🔍 Sedang mencari partner (diutamakan lawan jenis)... Mohon tunggu.", reply_markup=menu_idle)

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

    if user_id in active_chats:
        partner_id = active_chats[user_id]
        del active_chats[user_id]
        if partner_id in active_chats:
            del active_chats[partner_id]

        await context.bot.send_message(
            chat_id=partner_id,
            text="⚠️ Partner meninggalkan percakapan (Skip).",
            reply_markup=menu_idle
        )

    if user_id in waiting_queue:
        waiting_queue.remove(user_id)

    await update.message.reply_text("🔄 Mencari partner baru...", reply_markup=menu_idle)
    await search_partner(update, context)

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text
    get_or_create_user(user_id, update.effective_user.username)

    if text == "🔍 Cari Partner":
        await search_partner(update, context)
        return
    elif text == "💎 Cek Status VIP":
        await status_vip(update, context)
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

async def handle_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in active_chats:
        await update.message.reply_text("Kamu sedang tidak terhubung dengan siapa pun.", reply_markup=menu_idle)
        return

    partner_id = active_chats[user_id]
    msg = update.message

    try:
        if msg.photo:
            await context.bot.send_photo(chat_id=partner_id, photo=msg.photo[-1].file_id, caption=msg.caption or "")
        elif msg.sticker:
            await context.bot.send_sticker(chat_id=partner_id, sticker=msg.sticker.file_id)
        elif msg.voice:
            await context.bot.send_voice(chat_id=partner_id, voice=msg.voice.file_id, caption=msg.caption or "")
        elif msg.video:
            await context.bot.send_video(chat_id=partner_id, video=msg.video.file_id, caption=msg.caption or "")
        elif msg.document:
            await context.bot.send_document(chat_id=partner_id, document=msg.document.file_id, caption=msg.caption or "")
        elif msg.audio:
            await context.bot.send_audio(chat_id=partner_id, audio=msg.audio.file_id, caption=msg.caption or "")
        elif msg.animation:
            await context.bot.send_animation(chat_id=partner_id, animation=msg.animation.file_id, caption=msg.caption or "")
    except Exception as e:
        logging.error(f"Gagal forward media: {e}")
        await update.message.reply_text("⚠️ Gagal mengirim media.")

@app.on_event("startup")
async def startup_event():
    global telegram_app
    if not TOKEN:
        logging.error("TELEGRAM_TOKEN tidak ditemukan!")
        return
    
    telegram_app = ApplicationBuilder().token(TOKEN).build()
    telegram_app.add_handler(CommandHandler("start", start))
    telegram_app.add_handler(CallbackQueryHandler(gender_callback, pattern="^gender_"))
    telegram_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    
    media_filter = filters.PHOTO | filters.Sticker.ALL | filters.VOICE | filters.VIDEO | filters.Document.ALL | filters.AUDIO | filters.ANIMATION
    telegram_app.add_handler(MessageHandler(media_filter, handle_media))
    
    await telegram_app.initialize()
    await telegram_app.start()
    await telegram_app.updater.start_polling()
    logging.info("Telegram Bot started with Gender Selection & Smart Cross-Gender Matching!")

@app.on_event("shutdown")
async def shutdown_event():
    if telegram_app:
        await telegram_app.updater.stop()
        await telegram_app.stop()
        await telegram_app.shutdown()
        logging.info("Telegram Bot stopped.")

if __name__ == "__main__":
    uvicorn.run("bot:app", host="0.0.0.0", port=PORT, reload=False)
