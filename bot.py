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

# --- CONFIG ADMIN ---
ADMIN_IDS = [1076068580]

# --- DATABASE SETUP (SQLite) ---
DB_FILE = "bot_database.db"

def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    # Tabel users dengan kolom keamanan lengkap
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            gender TEXT DEFAULT NULL,
            is_premium INTEGER DEFAULT 0,
            premium_expired TEXT,
            is_banned INTEGER DEFAULT 0,
            is_muted INTEGER DEFAULT 0,
            mute_expired TEXT,
            is_shadowbanned INTEGER DEFAULT 0,
            total_sessions INTEGER DEFAULT 0,
            total_messages_sent INTEGER DEFAULT 0,
            last_active_at TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # Tabel sessions (riwayat pasangan)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY,
            user1_id INTEGER,
            user2_id INTEGER,
            started_at TEXT,
            ended_at TEXT,
            message_count_user1 INTEGER DEFAULT 0,
            message_count_user2 INTEGER DEFAULT 0,
            terminated_by_admin INTEGER DEFAULT 0
        )
    """)
    # Tabel reports
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS reports (
            id INTEGER PRIMARY KEY,
            reporter_id INTEGER,
            reported_id INTEGER,
            session_id INTEGER,
            reason TEXT,
            status TEXT DEFAULT 'open',
            created_at TEXT
        )
    """)
    conn.commit()
    conn.close()
    logging.info("Database SQLite dengan skema keamanan lengkap berhasil diinisialisasi!")

init_db()

def get_or_create_user(user_id, username):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, gender, is_premium, premium_expired, is_banned, is_muted, mute_expired, is_shadowbanned FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    
    if not row:
        cursor.execute("INSERT INTO users (user_id, username, gender, is_premium) VALUES (?, ?, NULL, 0)", (user_id, username))
        conn.commit()
        row = (user_id, None, 0, None, 0, 0, None, 0)
    
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

def get_user_status(user_id):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT is_banned, is_muted, mute_expired, is_shadowbanned FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    
    if not row:
        return {"banned": False, "muted": False, "shadowbanned": False}
    
    banned, muted, mute_expired, shadowbanned = row
    
    # Cek apakah mute sudah expired
    if muted and mute_expired:
        try:
            expired_date = datetime.strptime(mute_expired, "%Y-%m-%d %H:%M:%S")
            if datetime.now() > expired_date:
                conn = sqlite3.connect(DB_FILE)
                c = conn.cursor()
                c.execute("UPDATE users SET is_muted = 0, mute_expired = NULL WHERE user_id = ?", (user_id,))
                conn.commit()
                conn.close()
                muted = 0
        except:
            pass
    
    return {"banned": bool(banned), "muted": bool(muted), "shadowbanned": bool(shadowbanned)}

def get_all_users_stats():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM users")
    total_users = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM users WHERE gender = 'cowok'")
    total_cowok = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM users WHERE gender = 'cewek'")
    total_cewek = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM users WHERE is_premium = 1")
    total_vip = cursor.fetchone()[0]

    cursor.execute("SELECT username, gender, is_premium FROM users ORDER BY user_id DESC LIMIT 10")
    recent_users = cursor.fetchall()
    
    conn.close()
    return total_users, total_cowok, total_cewek, total_vip, recent_users

def get_active_sessions_detail():
    """Ambil detail sesi aktif untuk admin"""
    sessions = []
    for user_id, partner_id in active_chats.items():
        if user_id < partner_id:  # Hindari duplikat (hanya tampilkan satu arah)
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()
            cursor.execute("SELECT username, gender FROM users WHERE user_id = ?", (user_id,))
            u1 = cursor.fetchone()
            cursor.execute("SELECT username, gender FROM users WHERE user_id = ?", (partner_id,))
            u2 = cursor.fetchone()
            conn.close()
            
            u1_name = f"@{u1[0]}" if u1 and u1[0] else f"ID:{user_id}"
            u1_gender = u1[1].capitalize() if u1 and u1[1] else "?"
            u2_name = f"@{u2[0]}" if u2 and u2[0] else f"ID:{partner_id}"
            u2_gender = u2[1].capitalize() if u2 and u2[1] else "?"
            
            sessions.append({
                "user1_id": user_id,
                "user2_id": partner_id,
                "user1_display": f"{u1_name} ({u1_gender})",
                "user2_display": f"{u2_name} ({u2_gender})"
            })
    return sessions

def get_user_detail(user_id):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT username, gender, is_premium, premium_expired, is_banned, is_muted, mute_expired, 
               is_shadowbanned, total_sessions, total_messages_sent, last_active_at, created_at
        FROM users WHERE user_id = ?
    """, (user_id,))
    row = cursor.fetchone()
    
    # Ambil riwayat partner (5 terakhir)
    cursor.execute("""
        SELECT user1_id, user2_id, started_at, ended_at FROM sessions 
        WHERE user1_id = ? OR user2_id = ? ORDER BY started_at DESC LIMIT 5
    """, (user_id, user_id))
    sessions = cursor.fetchall()
    conn.close()
    
    if not row:
        return None
    
    username, gender, is_premium, premium_expired, is_banned, is_muted, mute_expired, is_shadowbanned, total_sessions, total_messages, last_active, created_at = row
    
    partner_history = []
    for s in sessions:
        partner_id = s[1] if s[0] == user_id else s[0]
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("SELECT username, gender FROM users WHERE user_id = ?", (partner_id,))
        p = c.fetchone()
        conn.close()
        p_name = f"@{p[0]}" if p and p[0] else f"ID:{partner_id}"
        p_gender = p[1].capitalize() if p and p[1] else "?"
        partner_history.append(f"{p_name} ({p_gender}) - {s[2]}")
    
    return {
        "user_id": user_id,
        "username": f"@{username}" if username else "-",
        "gender": gender.capitalize() if gender else "Belum set",
        "is_premium": bool(is_premium),
        "premium_expired": premium_expired or "-",
        "is_banned": bool(is_banned),
        "is_muted": bool(is_muted),
        "mute_expired": mute_expired or "-",
        "is_shadowbanned": bool(is_shadowbanned),
        "total_sessions": total_sessions,
        "total_messages": total_messages,
        "last_active": last_active or "-",
        "created_at": created_at,
        "partner_history": partner_history
    }

# --- STATE APPS ---
waiting_queue = []
active_chats = {}

# Keyboard Menu
menu_idle = ReplyKeyboardMarkup([["🔍 Cari Partner", "💎 Cek Status VIP"]], resize_keyboard=True)
menu_chat = ReplyKeyboardMarkup([["⏭️ Next Partner", "❌ Keluar / Stop"]], resize_keyboard=True)

app = FastAPI()
telegram_app = None

@app.get("/")
def home():
    return {"status": "Bot Anonymous Chat with Safety Core is alive!"}

# --- HELPER: CEK KEAMANAN SEBELUM PROSES ---
async def check_safety(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Cek apakah user dibanned/muted/shadowbanned. Return True jika aman, False jika diblokir."""
    user_id = update.effective_user.id
    status = get_user_status(user_id)
    
    if status["banned"]:
        await update.message.reply_text("🚫 Akun kamu telah dibanned secara permanen. Hubungi admin jika ini kesalahan.")
        return False
    
    if status["muted"]:
        await update.message.reply_text("🔇 Kamu sedang di-mute. Tidak bisa mengirim pesan atau mencari partner.")
        return False
    
    # Shadowban: user tidak tahu dia dibanned, tapi tidak akan pernah dapet partner asli
    if status["shadowbanned"]:
        # Biarkan user "ngira-ngira" bisa pakai bot, tapi jangan proses apa-apa
        return False
    
    return True

# --- HELPER: UPDATE ACTIVITY ---
def update_user_activity(user_id):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET last_active_at = ? WHERE user_id = ?", (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), user_id))
    conn.commit()
    conn.close()

# --- START & GENDER ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_data = get_or_create_user(user.id, user.username)
    gender = user_data[1]
    status = get_user_status(user.id)
    
    if status["banned"]:
        await update.message.reply_text("🚫 Akun kamu telah dibanned.")
        return
    
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

# --- ADMIN: STATS ---
async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("⛔ Akses ditolak.")
        return

    total_users, total_cowok, total_cewek, total_vip, recent_users = get_all_users_stats()
    # Hitung antrean
    queue_cowok = 0
    queue_cewek = 0
    for uid in waiting_queue:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("SELECT gender FROM users WHERE user_id = ?", (uid,))
        r = c.fetchone()
        conn.close()
        if r and r[0] == "cowok": queue_cowok += 1
        elif r and r[0] == "cewek": queue_cewek += 1

    stats_msg = (
        "📊 STATISTIK BOT ANONYMOUS CHAT 📊\n\n"
        f"👥 Total Pengguna: {total_users}\n"
        f"👨 Cowok: {total_cowok} | 👩 Cewek: {total_cewek}\n"
        f"💎 Member VIP: {total_vip}\n\n"
        f"⏳ Antrean Saat Ini: {len(waiting_queue)} (👨{queue_cowok} | 👩{queue_cewek})\n"
        f"💬 Sesi Aktif: {len(active_chats)//2}\n\n"
        "🕒 10 Pengguna Terbaru:\n"
    )
    for idx, (uname, gender, is_vip) in enumerate(recent_users, 1):
        username_str = f"@{uname}" if uname else "-"
        gender_str = gender.capitalize() if gender else "Belum set"
        vip_badge = "👑 VIP" if is_vip else "🌱 Free"
        stats_msg += f"{idx}. {username_str} | {gender_str} | {vip_badge}\n"

    await update.message.reply_text(stats_msg)

# --- ADMIN: BAN / UNBAN ---
async def ban_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("⛔ Akses ditolak.")
        return

    args = context.args
    if not args:
        await update.message.reply_text("Format: /ban <user_id> [alasan]")
        return
    
    try:
        target_id = int(args[0])
        reason = " ".join(args[1:]) if len(args) > 1 else "Pelanggaran aturan"
    except ValueError:
        await update.message.reply_text("User ID harus berupa angka.")
        return

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET is_banned = 1 WHERE user_id = ?", (target_id,))
    conn.commit()
    conn.close()

    # Putus sesi aktif jika ada
    if target_id in active_chats:
        partner_id = active_chats[target_id]
        del active_chats[target_id]
        del active_chats[partner_id]
        try:
            await context.bot.send_message(chat_id=partner_id, text="⚠️ Partner telah dibanned oleh admin. Sesi diakhiri.", reply_markup=menu_idle)
        except: pass

    # Hapus dari antrean
    if target_id in waiting_queue:
        waiting_queue.remove(target_id)

    try:
        await context.bot.send_message(chat_id=target_id, text=f"🚫 Kamu telah dibanned oleh admin.\nAlasan: {reason}")
    except: pass

    await update.message.reply_text(f"✅ User {target_id} berhasil dibanned.\nAlasan: {reason}")

async def unban_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("⛔ Akses ditolak.")
        return

    args = context.args
    if not args:
        await update.message.reply_text("Format: /unban <user_id>")
        return
    
    try:
        target_id = int(args[0])
    except ValueError:
        await update.message.reply_text("User ID harus berupa angka.")
        return

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET is_banned = 0 WHERE user_id = ?", (target_id,))
    conn.commit()
    conn.close()

    try:
        await context.bot.send_message(chat_id=target_id, text="✅ Ban kamu telah dicabut. Kamu bisa menggunakan bot kembali.")
    except: pass

    await update.message.reply_text(f"✅ User {target_id} berhasil di-unban.")

# --- ADMIN: SHADOWBAN ---
async def shadowban_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("⛔ Akses ditolak.")
        return

    args = context.args
    if not args:
        await update.message.reply_text("Format: /shadowban <user_id> [on/off]")
        return
    
    try:
        target_id = int(args[0])
        action = args[1].lower() if len(args) > 1 else "on"
    except ValueError:
        await update.message.reply_text("User ID harus berupa angka.")
        return

    val = 1 if action == "on" else 0
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET is_shadowbanned = ? WHERE user_id = ?", (val, target_id))
    conn.commit()
    conn.close()

    status = "diaktifkan" if val else "dicabut"
    await update.message.reply_text(f"✅ Shadowban untuk user {target_id} {status}.")

# --- ADMIN: MUTE / UNMUTE ---
async def mute_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("⛔ Akses ditolak.")
        return

    args = context.args
    if len(args) < 1:
        await update.message.reply_text("Format: /mute <user_id> [durasi_menit] [alasan]")
        return
    
    try:
        target_id = int(args[0])
        duration = int(args[1]) if len(args) > 1 else 60
        reason = " ".join(args[2:]) if len(args) > 2 else "Pelanggaran aturan"
    except ValueError:
        await update.message.reply_text("User ID dan durasi harus berupa angka.")
        return

    expired = datetime.now().replace(microsecond=0)
    from datetime import timedelta
    expired = expired + timedelta(minutes=duration)
    expired_str = expired.strftime("%Y-%m-%d %H:%M:%S")

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET is_muted = 1, mute_expired = ? WHERE user_id = ?", (expired_str, target_id))
    conn.commit()
    conn.close()

    try:
        await context.bot.send_message(chat_id=target_id, text=f"🔇 Kamu di-mute selama {duration} menit.\nAlasan: {reason}")
    except: pass

    # Putus sesi aktif
    if target_id in active_chats:
        partner_id = active_chats[target_id]
        del active_chats[target_id]
        del active_chats[partner_id]
        try:
            await context.bot.send_message(chat_id=partner_id, text="⚠️ Partner di-mute oleh admin. Sesi diakhiri.", reply_markup=menu_idle)
        except: pass

    if target_id in waiting_queue:
        waiting_queue.remove(target_id)

    await update.message.reply_text(f"✅ User {target_id} di-mute selama {duration} menit.")

async def unmute_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("⛔ Akses ditolak.")
        return

    args = context.args
    if not args:
        await update.message.reply_text("Format: /unmute <user_id>")
        return
    
    try:
        target_id = int(args[0])
    except ValueError:
        await update.message.reply_text("User ID harus angka.")
        return

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET is_muted = 0, mute_expired = NULL WHERE user_id = ?", (target_id,))
    conn.commit()
    conn.close()

    try:
        await context.bot.send_message(chat_id=target_id, text="✅ Mute kamu telah dicabut.")
    except: pass

    await update.message.reply_text(f"✅ User {target_id} berhasil di-unmute.")

# --- ADMIN: ACTIVE SESSIONS ---
async def active_sessions_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("⛔ Akses ditolak.")
        return

    sessions = get_active_sessions_detail()
    if not sessions:
        await update.message.reply_text("📭 Tidak ada sesi aktif saat ini.")
        return

    msg = "🟢 SESI AKTIF SAAT INI:\n\n"
    for idx, s in enumerate(sessions, 1):
        msg += f"{idx}. {s['user1_display']} 💬 {s['user2_display']}\n   IDs: {s['user1_id']} ↔ {s['user2_id']}\n\n"
    
    msg += "\nGunakan /terminate <user_id> untuk memutus sesi spesifik."
    await update.message.reply_text(msg)

# --- ADMIN: TERMINATE SESSION ---
async def terminate_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("⛔ Akses ditolak.")
        return

    args = context.args
    if not args:
        await update.message.reply_text("Format: /terminate <user_id>")
        return
    
    try:
        target_id = int(args[0])
    except ValueError:
        await update.message.reply_text("User ID harus angka.")
        return

    if target_id not in active_chats:
        await update.message.reply_text("User tidak sedang dalam sesi aktif.")
        return

    partner_id = active_chats[target_id]
    del active_chats[target_id]
    del active_chats[partner_id]

    # Catat di DB sessions sebagai terminated_by_admin
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE sessions SET ended_at = ?, terminated_by_admin = 1 
        WHERE (user1_id = ? OR user2_id = ?) AND ended_at IS NULL
    """, (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), target_id, target_id))
    conn.commit()
    conn.close()

    try:
        await context.bot.send_message(chat_id=target_id, text="⚠️ Sesi kamu dipaksa diakhiri oleh admin.", reply_markup=menu_idle)
    except: pass
    try:
        await context.bot.send_message(chat_id=partner_id, text="⚠️ Sesi dipaksa diakhiri oleh admin.", reply_markup=menu_idle)
    except: pass

    await update.message.reply_text(f"✅ Sesi user {target_id} (partner: {partner_id}) berhasil diputus oleh admin.")

# --- ADMIN: USER DETAIL ---
async def user_detail_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("⛔ Akses ditolak.")
        return

    args = context.args
    if not args:
        await update.message.reply_text("Format: /user <user_id>")
        return
    
    try:
        target_id = int(args[0])
    except ValueError:
        await update.message.reply_text("User ID harus angka.")
        return

    detail = get_user_detail(target_id)
    if not detail:
        await update.message.reply_text("User tidak ditemukan di database.")
        return

    msg = (
        f"👤 DETAIL USER {detail['user_id']}\n\n"
        f"👤 Username: {detail['username']}\n"
        f"🚻 Gender: {detail['gender']}\n"
        f"💎 VIP: {'Ya' if detail['is_premium'] else 'Tidak'} ({detail['premium_expired']})\n"
        f"🚫 Banned: {'Ya' if detail['is_banned'] else 'Tidak'}\n"
        f"🔇 Muted: {'Ya' if detail['is_muted'] else 'Tidak'} ({detail['mute_expired']})\n"
        f"👻 Shadowban: {'Ya' if detail['is_shadowbanned'] else 'Tidak'}\n"
        f"📊 Total Sesi: {detail['total_sessions']}\n"
        f"📨 Total Pesan: {detail['total_messages']}\n"
        f"🕒 Terakhir Aktif: {detail['last_active']}\n"
        f"📅 Bergabung: {detail['created_at']}\n\n"
        f"🕒 Riwayat Partner (5 terakhir):\n"
    )
    
    if detail['partner_history']:
        for i, p in enumerate(detail['partner_history'], 1):
            msg += f"  {i}. {p}\n"
    else:
        msg += "  (Belum ada riwayat)"

    await update.message.reply_text(msg)

# --- ADMIN: QUEUE STATUS ---
async def queue_status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("⛔ Akses ditolak.")
        return

    if not waiting_queue:
        await update.message.reply_text("📭 Antrean kosong.")
        return

    msg = f"⏳ ANTREAN SAAT INI ({len(waiting_queue)} orang):\n\n"
    for idx, uid in enumerate(waiting_queue, 1):
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("SELECT username, gender, is_premium FROM users WHERE user_id = ?", (uid,))
        r = c.fetchone()
        conn.close()
        
        uname = f"@{r[0]}" if r and r[0] else "-"
        gender = r[1].capitalize() if r and r[1] else "?"
        vip = "👑" if r and r[2] else "🌱"
        msg += f"{idx}. {uname} | {gender} | {vip} | ID: {uid}\n"

    await update.message.reply_text(msg)

# --- BROADCAST ---
async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("⛔ Akses ditolak.")
        return

    message_text = " ".join(context.args)
    if not message_text:
        await update.message.reply_text("Format: /broadcast <pesan>")
        return

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users WHERE is_banned = 0")
    user_ids = [row[0] for row in cursor.fetchall()]
    conn.close()

    success = 0
    fail = 0
    await update.message.reply_text(f"📢 Broadcast ke {len(user_ids)} user...")

    for uid in user_ids:
        try:
            await context.bot.send_message(chat_id=uid, text=f"📢 PENGUMUMAN\n\n{message_text}")
            success += 1
        except:
            fail += 1

    await update.message.reply_text(f"✅ Broadcast selesai.\n✅ Berhasil: {success}\n❌ Gagal: {fail}")

# --- USER COMMANDS ---
async def status_vip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT is_premium, premium_expired FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()

    if row and row[0] == 1:
        await update.message.reply_text(f"💎 Status: VIP MEMBER\n⏳ Berakhir: {row[1]}")
    else:
        await update.message.reply_text("🌱 Status: Free User\n\nUpgrade ke VIP untuk prioritas antrean & fitur eksklusif! 🚀")

# --- SEARCH PARTNER (DENGAN CEK KEAMANAN) ---
async def search_partner(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    # Cek keamanan
    if not await check_safety(update, context):
        return

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT gender FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    
    if not row or not row[0]:
        await update.message.reply_text("⚠️ Pilih gender dulu via /start.")
        return

    my_gender = row[0]

    if user_id in active_chats:
        await update.message.reply_text("Kamu sudah dalam sesi!", reply_markup=menu_chat)
        return
    if user_id in waiting_queue:
        await update.message.reply_text("Sudah di antrean...", reply_markup=menu_idle)
        return

    is_vip = check_user_premium(user_id)

    # Cari lawan jenis
    matched = None
    for qid in waiting_queue:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("SELECT gender FROM users WHERE user_id = ?", (qid,))
        r = c.fetchone()
        conn.close()
        if r and r[0] != my_gender:
            matched = qid
            break

    if not matched and waiting_queue:
        matched = waiting_queue[0]

    if matched:
        waiting_queue.remove(matched)
        active_chats[user_id] = matched
        active_chats[matched] = user_id

        # Catat session baru
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("INSERT INTO sessions (user1_id, user2_id, started_at) VALUES (?, ?, ?)", (user_id, matched, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        session_id = c.lastrowid
        # Update total sessions
        c.execute("UPDATE users SET total_sessions = total_sessions + 1 WHERE user_id IN (?, ?)", (user_id, matched))
        conn.commit()
        conn.close()

        await context.bot.send_message(chat_id=user_id, text="🎉 Partner ditemukan!", reply_markup=menu_chat)
        await context.bot.send_message(chat_id=matched, text="🎉 Partner ditemukan!", reply_markup=menu_chat)
    else:
        if is_vip:
            waiting_queue.insert(0, user_id)
            await update.message.reply_text("👑 [VIP Priority] Mencari...", reply_markup=menu_idle)
        else:
            waiting_queue.append(user_id)
            await update.message.reply_text("🔍 Mencari partner (prioritas lawan jenis)...", reply_markup=menu_idle)

# --- STOP CHAT ---
async def stop_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id in waiting_queue:
        waiting_queue.remove(user_id)
        await update.message.reply_text("Dibatalkan.", reply_markup=menu_idle)
        return

    if user_id in active_chats:
        partner_id = active_chats[user_id]
        del active_chats[user_id]
        del active_chats[partner_id]

        # Update session ended
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("UPDATE sessions SET ended_at = ? WHERE (user1_id = ? OR user2_id = ?) AND ended_at IS NULL", 
                  (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), user_id, user_id))
        conn.commit()
        conn.close()

        await update.message.reply_text("🛑 Sesi diakhiri.", reply_markup=menu_idle)
        try:
            await context.bot.send_message(chat_id=partner_id, text="⚠️ Partner keluar.", reply_markup=menu_idle)
        except: pass
    else:
        await update.message.reply_text("Tidak dalam sesi.", reply_markup=menu_idle)

# --- NEXT PARTNER ---
async def next_partner(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if not await check_safety(update, context):
        return

    if user_id in active_chats:
        partner_id = active_chats[user_id]
        del active_chats[user_id]
        del active_chats[partner_id]
        try:
            await context.bot.send_message(chat_id=partner_id, text="⚠️ Partner skip.", reply_markup=menu_idle)
        except: pass

    if user_id in waiting_queue:
        waiting_queue.remove(user_id)

    await update.message.reply_text("🔄 Mencari baru...", reply_markup=menu_idle)
    await search_partner(update, context)

# --- HANDLE TEXT ---
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text
    get_or_create_user(user_id, update.effective_user.username)
    update_user_activity(user_id)

    # Cek keamanan untuk perintah non-admin
    if text not in ["🔍 Cari Partner", "💎 Cek Status VIP", "❌ Keluar / Stop", "⏭️ Next Partner"]:
        if not await check_safety(update, context):
            return

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

    # Forward pesan ke partner
    if user_id in active_chats:
        partner_id = active_chats[user_id]
        status = get_user_status(user_id)
        if status["shadowbanned"]:
            # Shadowban: pesan tidak dikirim, tapi user tidak tau
            return
        if status["muted"]:
            await update.message.reply_text("🔇 Kamu di-mute, tidak bisa kirim pesan.")
            return
        
        await context.bot.send_message(chat_id=partner_id, text=text)
        # Update message count
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("UPDATE users SET total_messages_sent = total_messages_sent + 1 WHERE user_id = ?", (user_id,))
        # Update session message count
        c.execute("UPDATE sessions SET message_count_user1 = message_count_user1 + 1 WHERE user1_id = ? AND ended_at IS NULL", (user_id,))
        c.execute("UPDATE sessions SET message_count_user2 = message_count_user2 + 1 WHERE user2_id = ? AND ended_at IS NULL", (user_id,))
        conn.commit()
        conn.close()
        
        await context.bot.send_message(chat_id=partner_id, text=text)
    else:
        await update.message.reply_text("Ketik 'Cari Partner' untuk mulai.", reply_markup=menu_idle)

# --- HANDLE MEDIA ---
async def handle_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if not await check_safety(update, context):
        return
    
    status = get_user_status(user_id)
    if status["muted"] or status["shadowbanned"]:
        return

    if user_id not in active_chats:
        await update.message.reply_text("Tidak dalam sesi.", reply_markup=menu_idle)
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
        
        # Update count
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("UPDATE users SET total_messages_sent = total_messages_sent + 1 WHERE user_id = ?", (user_id,))
        c.execute("UPDATE sessions SET message_count_user1 = message_count_user1 + 1 WHERE user1_id = ? AND ended_at IS NULL", (user_id,))
        c.execute("UPDATE sessions SET message_count_user2 = message_count_user2 + 1 WHERE user2_id = ? AND ended_at IS NULL", (user_id,))
        conn.commit()
        conn.close()
    except Exception as e:
        logging.error(f"Gagal forward media: {e}")

# --- STARTUP ---
@app.on_event("startup")
async def startup_event():
    global telegram_app
    if not TOKEN:
        logging.error("TELEGRAM_TOKEN tidak ditemukan!")
        return
    
    telegram_app = ApplicationBuilder().token(TOKEN).build()
    
    # Command Handlers (Admin + User)
    telegram_app.add_handler(CommandHandler("start", start))
    telegram_app.add_handler(CommandHandler("broadcast", broadcast_command))
    telegram_app.add_handler(CommandHandler("stats", stats_command))
    telegram_app.add_handler(CommandHandler("ban", ban_command))
    telegram_app.add_handler(CommandHandler("unban", unban_command))
    telegram_app.add_handler(CommandHandler("shadowban", shadowban_command))
    telegram_app.add_handler(CommandHandler("mute", mute_command))
    telegram_app.add_handler(CommandHandler("unmute", unmute_command))
    telegram_app.add_handler(CommandHandler("active", active_sessions_command))
    telegram_app.add_handler(CommandHandler("terminate", terminate_command))
    telegram_app.add_handler(CommandHandler("user", user_detail_command))
    telegram_app.add_handler(CommandHandler("queue", queue_status_command))
    telegram_app.add_handler(CommandHandler("mute", mute_command))
    telegram_app.add_handler(CommandHandler("unmute", unmute_command))
    
    telegram_app.add_handler(CallbackQueryHandler(gender_callback, pattern="^gender_"))
    telegram_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    
    media_filter = filters.PHOTO | filters.Sticker.ALL | filters.VOICE | filters.VIDEO | filters.Document.ALL | filters.AUDIO | filters.ANIMATION
    telegram_app.add_handler(MessageHandler(media_filter, handle_media))
    
    await telegram_app.initialize()
    await telegram_app.start()
    await telegram_app.updater.start_polling()
    logging.info("Telegram Bot started with Safety Core Admin Panel!")

@app.on_event("shutdown")
async def shutdown_event():
    if telegram_app:
        await telegram_app.updater.stop()
        await telegram_app.stop()
        await telegram_app.shutdown()
        logging.info("Telegram Bot stopped.")

if __name__ == "__main__":
    uvicorn.run("bot:app", host="0.0.0.0", port=PORT, reload=False)