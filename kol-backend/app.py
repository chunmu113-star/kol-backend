import os
import sqlite3
from datetime import datetime, timedelta
from flask import Flask, request, jsonify
from flask_cors import CORS
import requests

app = Flask(__name__)
# 允許跨網域存取
CORS(app, resources={r"/api/*": {"origins": "*"}})

DB_FILE = "campaigns.db"

# 填入你的 LINE 官方帳號憑證
LINE_TOKEN = os.getenv("LINE_TOKEN", "U149614527cd27dc66efb13afb8bd2b63")
LINE_USER_ID = os.getenv("LINE_USER_ID", "YOUR_LINE_USER_ID")

def send_line_push(text):
    if "YOUR_LINE" in LINE_TOKEN:
        print("[推播略過] 未設定 Token:", text)
        return
    url = "https://api.line.me/v2/bot/message/push"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LINE_TOKEN}"
    }
    payload = {
        "to": LINE_USER_ID,
        "messages": [{"type": "text", "text": text}]
    }
    try:
        res = requests.post(url, json=payload, headers=headers, timeout=10)
        print(f"[LINE 推播] 狀態碼: {res.status_code}")
    except Exception as e:
        print(f"[LINE 推播失敗]: {e}")

def get_db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as conn:
        # 建立開團案件表
        conn.execute("""
            CREATE TABLE IF NOT EXISTS campaigns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                vendor TEXT NOT NULL,
                kol TEXT NOT NULL,
                launch_date TEXT NOT NULL,
                d30_date TEXT NOT NULL,
                d7_date TEXT NOT NULL,
                status TEXT DEFAULT '進行中'
            )
        """)
        # 建立廠商名單表
        conn.execute("""
            CREATE TABLE IF NOT EXISTS vendors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL
            )
        """)
        # 寫入預設廠商
        conn.execute("INSERT OR IGNORE INTO vendors (name) VALUES ('品牌A')")
        conn.execute("INSERT OR IGNORE INTO vendors (name) VALUES ('優質生活家')")
        conn.commit()

init_db()

# --- 案件 API ---
@app.route("/api/campaigns", methods=["GET"])
def get_campaigns():
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM campaigns ORDER BY launch_date ASC").fetchall()
        return jsonify([dict(r) for r in rows])

@app.route("/api/campaigns", methods=["POST"])
def add_campaign():
    data = request.json
    launch_dt = datetime.strptime(data["launch_date"], "%Y-%m-%d")
    d30 = (launch_dt - timedelta(days=30)).strftime("%Y-%m-%d")
    d7 = (launch_dt - timedelta(days=7)).strftime("%Y-%m-%d")
    with get_db() as conn:
        conn.execute("""
            INSERT INTO campaigns (vendor, kol, launch_date, d30_date, d7_date)
            VALUES (?, ?, ?, ?, ?)
        """, (data["vendor"], data["kol"], data["launch_date"], d30, d7))
        conn.commit()
    return jsonify({"success": True})

@app.route("/api/campaigns/<int:cid>/status", methods=["PATCH"])
def update_campaign_status(cid):
    data = request.json
    with get_db() as conn:
        conn.execute("UPDATE campaigns SET status = ? WHERE id = ?", (data["status"], cid))
        conn.commit()
    return jsonify({"success": True})

@app.route("/api/campaigns/<int:cid>", methods=["DELETE"])
def delete_campaign(cid):
    with get_db() as conn:
        conn.execute("DELETE FROM campaigns WHERE id = ?", (cid,))
        conn.commit()
    return jsonify({"success": True})

# --- 廠商名單庫 API (關鍵路由) ---
@app.route("/api/vendors", methods=["GET"])
def get_vendors():
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM vendors ORDER BY id ASC").fetchall()
        return jsonify([r["name"] for r in rows])

@app.route("/api/vendors", methods=["POST"])
def add_vendor():
    name = request.json.get("name", "").strip()
    if not name:
        return jsonify({"error": "請提供廠商名稱"}), 400
    with get_db() as conn:
        try:
            conn.execute("INSERT INTO vendors (name) VALUES (?)", (name,))
            conn.commit()
            return jsonify({"success": True})
        except sqlite3.IntegrityError:
            return jsonify({"error": "廠商已存在"}), 400

@app.route("/api/vendors/<string:name>", methods=["DELETE"])
def delete_vendor(name):
    with get_db() as conn:
        conn.execute("DELETE FROM vendors WHERE name = ?", (name,))
        conn.commit()
    return jsonify({"success": True})

# --- 排程檢核 API ---
@app.route("/api/cron-check", methods=["GET"])
def cron_check():
    today_str = datetime.now().strftime("%Y-%m-%d")
    with get_db() as conn:
        cursor = conn.cursor()
        
        # D-30 提醒
        cursor.execute("SELECT * FROM campaigns WHERE d30_date = ? AND status = '進行中'", (today_str,))
        for c in cursor.fetchall():
            msg = (
                f"🔔【開團倒數 30 天｜廠商確認提醒】\n\n"
                f"• 合作：{c['vendor']} × {c['kol']}\n"
                f"• 開團日：{c['launch_date']}\n\n"
                f"📝 待辦確認：\n"
                f"1. 現貨庫存與活動分潤確認\n"
                f"2. 廠商專屬導購連結生成\n"
                f"3. 樣品寄送追蹤"
            )
            send_line_push(msg)

        # D-7 提醒
        cursor.execute("SELECT * FROM campaigns WHERE d7_date = ? AND status = '進行中'", (today_str,))
        for c in cursor.fetchall():
            msg = (
                f"⚠️【開團倒數 7 天｜KOL 上線確認】\n\n"
                f"• 合作：{c['vendor']} × {c['kol']}\n"
                f"• 開團日：{c['launch_date']}\n\n"
                f"📝 待辦確認：\n"
                f"1. 樣品體驗照片確認\n"
                f"2. 開箱圖文/限動文案審查\n"
                f"3. 實測專屬連結轉單"
            )
            send_line_push(msg)

    return jsonify({"status": "ok", "checked_date": today_str})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)