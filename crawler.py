import requests
import sqlite3
import os
import re
from urllib.parse import quote

DB_PATH = os.path.join(os.path.dirname(__file__), "characters.db")

# ─────────────────────────────────────────
# DB 초기화
# ─────────────────────────────────────────
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS characters (
            key         TEXT PRIMARY KEY,
            adven_name  TEXT,
            name        TEXT,
            server      TEXT,
            job         TEXT,
            base_job    TEXT,
            fame        INTEGER,
            dundam_dps  INTEGER,
            buff_score  INTEGER,
            cri         REAL,
            set_name    TEXT,
            active      INTEGER DEFAULT 1
        )
    """)
    # 기존 DB에 active 컬럼이 없으면 추가
    try:
        cursor.execute("ALTER TABLE characters ADD COLUMN active INTEGER DEFAULT 1")
    except sqlite3.OperationalError:
        pass
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key     TEXT PRIMARY KEY,
            value   REAL
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS raid_roster (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            run_num  INTEGER DEFAULT 1,
            char_key TEXT,
            name     TEXT,
            job      TEXT,
            role     TEXT,
            combat   INTEGER,
            party    TEXT
        )
    """)
    try:
        cursor.execute("ALTER TABLE raid_roster ADD COLUMN run_num INTEGER DEFAULT 1")
    except sqlite3.OperationalError:
        pass
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS adventurers (
            adven_name  TEXT PRIMARY KEY,
            nickname    TEXT DEFAULT '',
            active      INTEGER DEFAULT 1
        )
    """)
    try:
        cursor.execute("ALTER TABLE adventurers ADD COLUMN active INTEGER DEFAULT 1")
    except sqlite3.OperationalError:
        pass
    # 단위 마이그레이션 (최초 1회)
    cursor.execute("SELECT value FROM settings WHERE key = 'units_migrated'")
    if not cursor.fetchone():
        cursor.execute("UPDATE characters SET dundam_dps = dundam_dps / 100000000 WHERE dundam_dps IS NOT NULL")
        cursor.execute("UPDATE characters SET buff_score  = buff_score  / 10000      WHERE buff_score  IS NOT NULL")
        cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('units_migrated', 1)")

    # 기존 characters에서 모험단명 자동 동기화
    cursor.execute("""
        INSERT OR IGNORE INTO adventurers (adven_name)
        SELECT DISTINCT adven_name FROM characters WHERE adven_name IS NOT NULL
    """)
    # 기본값 (없을 때만 삽입)
    defaults = {
        "min_fame":    63257,  # 명성컷
        "dealer_cut":  300,    # 딜러컷 (억 단위)
        "buffer_cut":  400,    # 버퍼컷 (만 단위)
        "clear_dps":   1500,   # 딜합컷 딜량 (억 단위)
        "clear_buff":  680,    # 딜합컷 버프력 (만 단위)
        "raid_count":  4,      # 레이드 횟수
    }
    for k, v in defaults.items():
        cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (k, v))
    conn.commit()
    conn.close()

# ─────────────────────────────────────────
# 숫자 변환 함수
# ─────────────────────────────────────────
def parse_dps(text):
    # "4115 억 4065 만" → 4115 (억 단위 정수)
    if not text:
        return None
    uk = re.search(r"([\d,]+)\s*억", text)
    man = re.search(r"([\d,]+)\s*만", text)
    result = 0
    if uk:
        result += int(uk.group(1).replace(",", ""))
    if man:
        result += int(man.group(1).replace(",", "")) / 10000
    return int(result) if result > 0 else None

def parse_buff(text):
    # "5,741,184" → 574 (만 단위 정수)
    if not text:
        return None
    return int(text.replace(",", "")) // 10_000

# ─────────────────────────────────────────
# 던담 API 호출
# ─────────────────────────────────────────
def fetch_characters(adven_name):
    url = "https://dundam.xyz/dat/searchData.jsp"
    params = {
        "name": adven_name,
        "server": "adven"
    }
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36",
        "Referer": "https://dundam.xyz/search?server=adven&name=" + quote(adven_name),
        "Origin": "https://dundam.xyz",
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json"
    }

    response = requests.post(url, params=params, headers=headers, json={})

    if response.status_code != 200:
        print(f"요청 실패: {response.status_code}")
        return []

    data = response.json()
    return data.get("characters", [])

# ─────────────────────────────────────────
# DB 저장
# ─────────────────────────────────────────
def save_characters(characters):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    for c in characters:
        cursor.execute("""
            INSERT OR REPLACE INTO characters
            (key, adven_name, name, server, job, base_job, fame, dundam_dps, buff_score, cri, set_name)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            c.get("key"),
            c.get("adventrueName"),
            c.get("name"),
            c.get("server"),
            c.get("job"),
            c.get("baseJob"),
            c.get("fame"),
            parse_dps(c.get("ozma")),
            parse_buff(c.get("buffScore")),
            c.get("cri"),
            c.get("setname")
        ))

    # 모험단 자동 등록 (닉네임은 건드리지 않음)
    adven_names = {c.get("adventrueName") for c in characters if c.get("adventrueName")}
    for adven in adven_names:
        cursor.execute("INSERT OR IGNORE INTO adventurers (adven_name) VALUES (?)", (adven,))

    conn.commit()
    conn.close()
    print(f"{len(characters)}개의 캐릭터를 저장했습니다.")

# ─────────────────────────────────────────
# 메인 실행
# ─────────────────────────────────────────
def main():
    adven_name = input("모험단명을 입력하세요: ")

    print(f"'{adven_name}' 모험단 정보를 가져오는 중...")
    characters = fetch_characters(adven_name)

    if not characters:
        print("캐릭터를 찾지 못했습니다.")
        return

    print(f"{len(characters)}개의 캐릭터를 찾았습니다.")
    for c in characters:
        adven = c.get("adventrueName", "")
        name  = c.get("name", "")
        job   = c.get("job", "")
        fame  = c.get("fame", "")
        if c.get("buffScore"):
            print(f"  {adven} | {name} | {job} | {fame} | {c['buffScore']}")
        else:
            dps = c.get("ozma", "정보없음")
            print(f"  {adven} | {name} | {job} | {fame} | {dps}")

    save_characters(characters)

if __name__ == "__main__":
    init_db()
    main()
