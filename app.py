import os
import json
import base64
import sqlite3
from datetime import datetime, timedelta
from flask import Flask, request, jsonify
from flask_cors import CORS
import requests

app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": "*"}})

DB_FILE = "campaigns.db"

# --- LINE 推播設定 ---
LINE_TOKEN = os.getenv("LINE_TOKEN", "NsKFLWsiaXW9sS4GW7RgpPbAqxjRZWNGBDEFxFqujB3UIbQmmxFzwBHBTa8pVLq6CVAGkwgjbygQWzC3VFw86vPXRIEFlC3//ygPVG+Tp/fu+UiUAQzlj+wsqtjvtJNSqP6eFH7ZMJN3VGjmlS43xQdB04t89/1O/w1cDnyilFU=")

# --- GitHub 自動備份設定 ---
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
GITHUB_REPO = os.getenv("GITHUB_REPO", "") # 格式: "你的帳號/kol-backend"
BACKUP_FILENAME = "backup_data.json"

def sync_to_github():
    """每次資料異動時，將資料庫導出為 JSON 並自動 commit 到 GitHub"""
    if not GITHUB_TOKEN or not GITHUB_REPO:
        return
    try:
        with get_db() as conn:
            vendors = [r["name"] for r in conn.execute("SELECT name FROM vendors").fetchall()]
            campaigns = [dict(r) for r in conn.execute("SELECT * FROM campaigns").fetchall()]
            members = [dict(r) for r in conn.execute("SELECT * FROM members").fetchall()]
        
        backup_content = json.dumps({
            "vendors": vendors, 
            "campaigns": campaigns,
            "members": members
        }, ensure_ascii=False, indent=2)
        
        url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{BACKUP_FILENAME}"
        headers = {
            "Authorization": f"token {GITHUB_TOKEN}",
            "Accept": "application/vnd.github.v3+json"
        }
        
        sha = None
        get_res = requests.get(url, headers=headers)
        if get_res.status_code == 200:
            sha = get_res.json().get("sha")
            
        payload = {
            "message": f"🤖 [自動備份] 更新開團資料庫 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "content": base64.b64encode(backup_content.encode("utf-8")).decode("utf-8")
        }
        if sha:
            payload["sha"] = sha
            
        put_res = requests.put(url, headers=headers, json=payload)
        if put_res.status_code in [200, 201]:
            print("✅ 成功備份至 GitHub！")
        else:
            print("❌ GitHub 備份失敗:", put_res.text)
    except Exception as e:
        print("❌ 備份過程發生錯誤:", e)

def restore_from_github():
    """容器啟動時，自動從 GitHub 讀取備份資料還原至 SQLite"""
    if not GITHUB_TOKEN or not GITHUB_REPO:
        return
    try:
        url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{BACKUP_FILENAME}"
        headers = {"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"}
        res = requests.get(url, headers=headers)
        if res.status_code == 200:
            content = base64.b64decode(res.json()["content"]).decode("utf-8")
            data = json.loads(content)
            with get_db() as conn:
                for v in data.get("vendors", []):
                    conn.execute("INSERT OR IGNORE INTO vendors (name) VALUES (?)", (v,))
                for c in data.get("campaigns", []):
                    conn.execute("""
                        INSERT OR IGNORE INTO campaigns (id, vendor, kol, launch_date, d30_date, d7_date, status)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (c.get("id"), c["vendor"], c["kol"], c["launch_date"], c["d30_date"], c["d7_date"], c["status"]))
                for m in data.get("members", []):
                    conn.execute("""
                        INSERT OR REPLACE INTO members (user_id, name, is_active)
                        VALUES (?, ?, ?)
                    """, (m["user_id"], m["name"], m["is_active"]))
                conn.commit()
            print("🚀 已成功從 GitHub 備份檔還原資料！")
    except Exception as e:
        print("❌ 還原 GitHub 資料失敗:", e)

def send_line_push(text):
    if "YOUR_LINE" in LINE_TOKEN:
        return
    url = "https://api.line.me/v2/bot/message/push"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LINE_TOKEN}"
    }
    
    # 僅查詢勾選開啟 (is_active = 1) 的對象
    with get_db() as conn:
        active_members = conn.execute("SELECT user_id, name FROM members WHERE is_active = 1").fetchall()
        
    for m in active_members:
        uid = m["user_id"]
        payload = {
            "to": uid,
            "messages": [{"type": "text", "text": text}]
        }
        try:
            res = requests.post(url, json=payload, headers=headers, timeout=10)
            print(f"[LINE 推播] 對象: {m['name']} ({uid[:8]}...) 狀態碼: {res.status_code}")
        except Exception as e:
            print(f"[LINE 推播失敗] 對象: {m['name']} 錯誤: {e}")

def get_db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as conn:
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
        conn.execute("""
            CREATE TABLE IF NOT EXISTS vendors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS members (
                user_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                is_active INTEGER DEFAULT 1
            )
        """)
        # 預設兩位成員
        conn.execute("INSERT OR IGNORE INTO members (user_id, name, is_active) VALUES ('U149614527cd27dc66efb13afb8bd2b63', '成員 1', 1)")
        conn.execute("INSERT OR IGNORE INTO members (user_id, name, is_active) VALUES ('U305610710cb46cd6613fc45bbc15f8a4', '成員 2', 1)")
        
        conn.execute("INSERT OR IGNORE INTO vendors (name) VALUES ('品牌A')")
        conn.execute("INSERT OR IGNORE INTO vendors (name) VALUES ('優質生活家')")
        conn.commit()
    restore_from_github()

init_db()

@app.route("/", methods=["GET", "HEAD"])
def index():
    return jsonify({"status": "running", "service": "KOL Secretary API"})

# --- 推播成員管理 API ---
@app.route("/api/members", methods=["GET"])
def get_members():
    with get_db() as conn:
        rows = conn.execute("SELECT user_id, name, is_active FROM members ORDER BY rowid ASC").fetchall()
        return jsonify([dict(r) for r in rows])

@app.route("/api/members/<string:uid>/toggle", methods=["PATCH"])
def toggle_member(uid):
    data = request.json or {}
    is_active = 1 if data.get("is_active") else 0
    with get_db() as conn:
        conn.execute("UPDATE members SET is_active = ? WHERE user_id = ?", (is_active, uid))
        conn.commit()
        sync_to_github()
    return jsonify({"success": True})

# --- 廠商名單庫 API ---
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
            sync_to_github()
            return jsonify({"success": True})
        except sqlite3.IntegrityError:
            return jsonify({"error": "該廠商已存在"}), 400

@app.route("/api/vendors/<string:name>", methods=["DELETE"])
def delete_vendor(name):
    with get_db() as conn:
        conn.execute("DELETE FROM vendors WHERE name = ?", (name,))
        conn.commit()
        sync_to_github()
    return jsonify({"success": True})

# --- 案件管理 API ---
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
        sync_to_github()
    return jsonify({"success": True})

@app.route("/api/campaigns/<int:cid>/status", methods=["PATCH"])
def update_campaign_status(cid):
    data = request.json
    with get_db() as conn:
        conn.execute("UPDATE campaigns SET status = ? WHERE id = ?", (data["status"], cid))
        conn.commit()
        sync_to_github()
    return jsonify({"success": True})

@app.route("/api/campaigns/<int:cid>", methods=["DELETE"])
def delete_campaign(cid):
    with get_db() as conn:
        conn.execute("DELETE FROM campaigns WHERE id = ?", (cid,))
        conn.commit()
        sync_to_github()
    return jsonify({"success": True})

# --- 排程檢核 API ---
@app.route("/api/cron-check", methods=["GET"])
def cron_check():
    today_str = datetime.now().strftime("%Y-%m-%d")
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM campaigns WHERE d7_date = ? AND status = '進行中'", (today_str,))
        d7_items = cursor.fetchall()

        cursor.execute("SELECT * FROM campaigns WHERE d30_date = ? AND status = '進行中'", (today_str,))
        d30_items = cursor.fetchall()

        cursor.execute("""
            SELECT * FROM campaigns 
            WHERE launch_date >= ? AND status = '進行中' 
            ORDER BY launch_date ASC
            LIMIT 8
        """, (today_str,))
        upcoming_items = cursor.fetchall()

    has_today_task = bool(d7_items or d30_items)
    lines = [f"📅【KOL 開團管家日報｜{today_str}】\n"]

    if not has_today_task:
        lines.append("🎉 今日無到期的 D-7 / D-30 待辦事項！\n")
    else:
        if d7_items:
            lines.append("⚠️【開團倒數 7 天｜KOL 上線確認】")
            for c in d7_items:
                lines.append(f"• {c['vendor']} × {c['kol']} (開團: {c['launch_date']})")
            lines.append("  ↳ 待辦：樣品體驗圖、開箱文案審核、連結轉單測試\n")

        if d30_items:
            lines.append("🔔【開團倒數 30 天｜廠商確認提醒】")
            for c in d30_items:
                lines.append(f"• {c['vendor']} × {c['kol']} (開團: {c['launch_date']})")
            lines.append("  ↳ 待辦：庫存與分潤確認、導購連結生成、樣品寄送\n")

    if upcoming_items:
        lines.append("📌【近期排程預告 (依日期排序)】")
        for c in upcoming_items:
            lines.append(f"• {c['launch_date']}｜{c['vendor']} × {c['kol']}")
    else:
        lines.append("📌【近期排程預告】：目前無排程中案件")

    full_message = "\n".join(lines)
    send_line_push(full_message)

    return jsonify({
        "status": "ok", 
        "checked_date": today_str,
        "d7_count": len(d7_items),
        "d30_count": len(d30_items)
    })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
