import os
import sqlite3

DB_FILE = "bot_database.db"

def list_users():
    if not os.path.exists(DB_FILE):
        print("Database belum ada!")
        return

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    cursor.execute("SELECT user_id, username, gender, is_premium, premium_expired FROM users")
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        print("Belum ada pengguna yang terdaftar di database.")
        return

    print(f"\n📊 TOTAL PENGGUNA TERDAFTAR: {len(rows)} orang\n")
    print(f"{'User ID':<15} | {'Username':<20} | {'Gender':<10} | {'Status VIP':<10}")
    print("-" * 65)
    
    for row in rows:
        uid, uname, gender, is_vip, expired = row
        username_str = f"@{uname}" if uname else "-"
        gender_str = gender.capitalize() if gender else "Belum set"
        if is_vip == 1:
            vip_str = "VIP 👑"
        else:
            vip_str = "Free 🌱"
            
        print(f"{uid:<15} | {username_str:<20} | {gender_str:<10} | {vip_str:<10}")
    print("\n")

if __name__ == "__main__":
    list_users()
