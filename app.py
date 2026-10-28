import os
import sqlite3
from datetime import datetime, timedelta
from flask import Flask, render_template, request, jsonify
from apscheduler.schedulers.background import BackgroundScheduler
import requests

app = Flask(__name__)
DB_FILE = "campaigns.db"

# ==========================================
# 1. LINE Messaging API 設定
# 請在 LINE Developers 後台建立 Channel 並取得以下資訊
# ==========================================
LINE_CHANNEL_ACCESS_TOKEN = "U149614527cd27dc66efb13afb8bd2b63"
YOUR_LINE_USER_ID = "YOUR_LINE_USER_ID"  # 你的個人 LINE User ID (格式為 U 開頭字串)

def send_line_push(message_text):
    """主動推播訊息至指定 LINE 帳號"""
    if LINE_CHANNEL_ACCESS_TOKEN == "U149614527cd27dc66efb13afb8bd2b63":
        print("[LINE 推播略過] 尚未填入 LINE Token。訊息內容：\n", message_text)
        return

    url = "https://api.line.me/v2/bot/message/push"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}"
    }
    payload = {
        "to": YOUR_LINE_USER_ID,
        "messages": [{"type": "text", "text": message_text}]
    }
    try:
        res = requests.post(url, json=payload, headers=headers, timeout=10)
        print(f"[LINE 推播發送] 狀態碼: {res.status_code}")
    except Exception as e:
        print(f"[LINE 推播錯誤] {e}")

# ==========================================
# 2. 資料庫初始化
# ==========================================
def get_db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS campaigns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                vendor TEXT NOT NULL,
                kol TEXT NOT NULL,
                launch_date TEXT NOT NULL,
                sales_url TEXT,
                d30_date TEXT NOT NULL,
                d7_date TEXT NOT NULL,
                status TEXT DEFAULT '進行中',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()

init_db()

# ==========================================
# 3. 每日自動排程檢查 (D-30 與 D-7)
# ==========================================
def check_and_notify_daily():
    today_str = datetime.now().strftime("%Y-%m-%d")
    print(f"[{today_str}] 執行開團案件排程檢核...")
    
    with get_db() as conn:
        cursor = conn.cursor()
        
        # 1. 檢查開團前 30 天 (廠商確認)
        cursor.execute("SELECT * FROM campaigns WHERE d30_date = ? AND status = '進行中'", (today_str,))
        d30_cases = cursor.fetchall()
        for c in d30_cases:
            msg = (
                f"🔔【開團倒數 30 天｜廠商確認提醒】\n\n"
                f"• 專案：{c['title']}\n"
                f"• 廠商：{c['vendor']} ｜ KOL：{c['kol']}\n"
                f"• 預計開團日：{c['launch_date']}\n"
                f"• 專屬導購連結：{c['sales_url'] or '未填寫'}\n\n"
                f"📝 待辦確認清單：\n"
                f"1. 核對庫存量與分潤合約\n"
                f"2. 廠商專屬導購連結是否已生成\n"
                f"3. 確認 KOL 評測樣品寄送進度"
            )
            send_line_push(msg)

        # 2. 檢查開團前 7 天 (KOL 確認)
        cursor.execute("SELECT * FROM campaigns WHERE d7_date = ? AND status = '進行中'", (today_str,))
        d7_cases = cursor.fetchall()
        for c in d7_cases:
            msg = (
                f"⚠️【開團倒數 7 天｜KOL 上線確認】\n\n"
                f"• 專案：{c['title']}\n"
                f"• 廠商：{c['vendor']} ｜ KOL：{c['kol']}\n"
                f"• 開團日：{c['launch_date']}\n"
                f"• 專屬導購連結：{c['sales_url'] or '未填寫'}\n\n"
                f"📝 待辦確認清單：\n"
                f"1. 審核開箱圖文/限動文案與授權標籤\n"
                f"2. 實測專屬導購轉單連結是否正常運作\n"
                f"3. 敲定開團當日發文時間點"
            )
            send_line_push(msg)

# 啟動排程：設定每天早上 09:30 執行
scheduler = BackgroundScheduler(daemon=True)
scheduler.add_job(check_and_notify_daily, 'cron', hour=9, minute=30)
scheduler.start()

# ==========================================
# 4. Web API 路由
# ==========================================
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/campaigns", methods=["GET"])
def list_campaigns():
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM campaigns ORDER BY launch_date ASC")
        rows = cursor.fetchall()
        result = [dict(row) for row in rows]
    return jsonify(result)

@app.route("/api/campaigns", methods=["POST"])
def add_campaign():
    data = request.json
    title = data.get("title", "").strip()
    vendor = data.get("vendor", "").strip()
    kol = data.get("kol", "").strip()
    launch_date_str = data.get("launch_date", "").strip()
    sales_url = data.get("sales_url", "").strip()

    if not (title and vendor and kol and launch_date_str):
        return jsonify({"error": "請填寫完整必要欄位"}), 400

    # 計算 D-30 與 D-7 日期
    launch_dt = datetime.strptime(launch_date_str, "%Y-%m-%d")
    d30_str = (launch_dt - timedelta(days=30)).strftime("%Y-%m-%d")
    d7_str = (launch_dt - timedelta(days=7)).strftime("%Y-%m-%d")

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO campaigns (title, vendor, kol, launch_date, sales_url, d30_date, d7_date)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (title, vendor, kol, launch_date_str, sales_url, d30_str, d7_str))
        conn.commit()

    return jsonify({"success": True})

@app.route("/api/campaigns/<int:cid>/status", methods=["PATCH"])
def update_status(cid):
    data = request.json
    new_status = data.get("status", "進行中")
    with get_db() as conn:
        conn.execute("UPDATE campaigns SET status = ? WHERE id = ?", (new_status, cid))
        conn.commit()
    return jsonify({"success": True})

@app.route("/api/campaigns/<int:cid>", methods=["DELETE"])
def delete_campaign(cid):
    with get_db() as conn:
        conn.execute("DELETE FROM campaigns WHERE id = ?", (cid,))
        conn.commit()
    return jsonify({"success": True})

if __name__ == "__main__":
    # 本地啟動在 5000 埠
    app.run(host="0.0.0.0", port=5000, debug=False)