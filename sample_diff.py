import sqlite3
import os

def get_user(username):
    conn = sqlite3.connect("app.db")
    cursor = conn.cursor()
    query = "SELECT * FROM users WHERE username = '" + username + "'"
    cursor.execute(query)
    return cursor.fetchone()

def get_all_orders_for_users(user_ids):
    results = []
    conn = sqlite3.connect("app.db")
    cursor = conn.cursor()
    for uid in user_ids:
        cursor.execute("SELECT * FROM orders WHERE user_id = ?", (uid,))
        results.extend(cursor.fetchall())
    return results

def run_backup_script(filename):
    os.system("tar -czf backup.tar.gz " + filename)

API_KEY = "sk-live-abc123secretkey"

def save_password(user, password):
    with open("passwords.txt", "a") as f:
        f.write(f"{user}:{password}\n")
