from flask import Flask, render_template, request, jsonify
from crawler import fetch_characters, save_characters, init_db
from raid_builder import build_raids
import sqlite3
import os

app = Flask(__name__)
init_db()

DB_PATH = os.path.join(os.path.dirname(__file__), "characters.db")

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/settings", methods=["GET"])
def get_settings():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT key, value FROM settings")
    rows = cursor.fetchall()
    conn.close()
    return jsonify({row["key"]: row["value"] for row in rows})

@app.route("/settings", methods=["POST"])
def save_settings():
    data = request.json
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    for k, v in data.items():
        cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (k, float(v)))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})

@app.route("/characters")
def get_characters():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM characters ORDER BY adven_name, fame DESC")
    rows = cursor.fetchall()
    conn.close()

    grouped = {}
    for row in rows:
        adven = row["adven_name"] or "알 수 없음"
        if adven not in grouped:
            grouped[adven] = []
        grouped[adven].append(dict(row))

    return jsonify(grouped)

@app.route("/adventurers", methods=["GET"])
def get_adventurers():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT adven_name, nickname FROM adventurers ORDER BY adven_name").fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route("/adventurers/<adven_name>", methods=["PATCH"])
def update_adventurer(adven_name):
    data = request.json
    conn = sqlite3.connect(DB_PATH)
    if "nickname" in data:
        conn.execute("UPDATE adventurers SET nickname = ? WHERE adven_name = ?", (data["nickname"], adven_name))
    if "active" in data:
        conn.execute("UPDATE adventurers SET active = ? WHERE adven_name = ?", (1 if data["active"] else 0, adven_name))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})

@app.route("/characters/<key>/active", methods=["PATCH"])
def toggle_active(key):
    data = request.json
    active = 1 if data.get("active") else 0
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE characters SET active = ? WHERE key = ?", (active, key))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})

@app.route("/roster", methods=["GET"])
def get_roster():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM raid_roster ORDER BY party, id").fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route("/roster", methods=["POST"])
def save_roster():
    entries = request.json  # list of {run_num, char_key, name, job, role, combat, party}
    conn = sqlite3.connect(DB_PATH)
    conn.execute("DELETE FROM raid_roster")
    conn.executemany(
        "INSERT INTO raid_roster (run_num, char_key, name, job, role, combat, party) VALUES (?,?,?,?,?,?,?)",
        [(e["run_num"], e["char_key"], e["name"], e["job"], e["role"], e["combat"], e["party"]) for e in entries]
    )
    conn.commit()
    conn.close()
    return jsonify({"ok": True})

@app.route("/build_raid", methods=["GET"])
def build_raid():
    try:
        raids = build_raids()
        return jsonify(raids)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/roster", methods=["DELETE"])
def clear_roster():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("DELETE FROM raid_roster")
    conn.commit()
    conn.close()
    return jsonify({"ok": True})

@app.route("/search", methods=["POST"])
def search():
    adven_name = request.json.get("adven_name", "").strip()
    if not adven_name:
        return jsonify({"error": "모험단명을 입력해주세요."}), 400

    characters = fetch_characters(adven_name)
    if not characters:
        return jsonify({"error": "캐릭터를 찾지 못했습니다."}), 404

    save_characters(characters)
    return jsonify({"characters": characters})

if __name__ == "__main__":
    init_db()
    app.run(debug=True)
