import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "characters.db")

# ─────────────────────────────────────────
# DB에서 설정값 로드
# ─────────────────────────────────────────
def load_settings():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT key, value FROM settings")
    rows = cursor.fetchall()
    conn.close()
    return {row["key"]: row["value"] for row in rows}

# ─────────────────────────────────────────
# DB에서 캐릭터 로드
# ─────────────────────────────────────────
def load_characters(min_fame=63257):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM characters WHERE fame >= ?", (min_fame,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

# ─────────────────────────────────────────
# 역할 분류
# ─────────────────────────────────────────
def classify(characters, dealer_threshold, buffer_threshold):
    buffers = []
    dealers = []
    underdogs = []

    for c in characters:
        is_buffer = c["buff_score"] and c["buff_score"] >= buffer_threshold
        is_dealer = c["dundam_dps"] and c["dundam_dps"] >= dealer_threshold

        if is_buffer:
            c["role"] = "buffer"
            buffers.append(c)
        elif is_dealer:
            c["role"] = "dealer"
            dealers.append(c)
        else:
            c["role"] = "underdog"
            underdogs.append(c)

    return buffers, dealers, underdogs

# ─────────────────────────────────────────
# 파티 전투력 계산
# ─────────────────────────────────────────
def calc_party_power(party):
    buffer = next((c for c in party if c["role"] == "buffer"), None)
    if not buffer or not buffer["buff_score"]:
        return 0
    dps_sum = sum(c["dundam_dps"] or 0 for c in party if c["role"] == "dealer")
    return dps_sum * buffer["buff_score"]

# ─────────────────────────────────────────
# 공격대 편성
# ─────────────────────────────────────────
UNDERDOG_SLOT = {"role": "업둥", "name": "업둥", "adven_name": "", "job": "", "dundam_dps": 0, "buff_score": 0}

def build_parties(buffers, dealers, underdogs, clear_threshold):
    if len(buffers) < 3:
        return None, f"버퍼가 부족합니다. (현재 {len(buffers)}명, 필요 3명)"

    # 버퍼 약한 순서로 정렬 (약한 버퍼 파티에 강한 딜러를 먼저 배정하기 위해)
    buffers_sorted = sorted(buffers, key=lambda c: c["buff_score"] or 0)[:3]

    # 파티 초기화
    parties = [[b] for b in buffers_sorted]
    party_dps = [0.0, 0.0, 0.0]
    remaining = [3, 3, 3]
    met = [False, False, False]  # 파티컷 달성 여부
    used_keys = {b["key"] for b in buffers_sorted}  # 이미 배정된 캐릭터 key

    # 딜러 강한 순서부터 1명씩, 파티컷 미달 파티 중 버프력이 가장 낮은 파티에 배정
    dealers_sorted = sorted(dealers, key=lambda c: c["dundam_dps"] or 0, reverse=True)

    for dealer in dealers_sorted:
        if dealer["key"] in used_keys:
            continue
        candidates = [i for i in range(3) if not met[i] and remaining[i] > 0]
        if not candidates:
            break
        # 파티컷 미달 파티 중 버프력이 가장 낮은 곳에 배정
        target = min(candidates, key=lambda i: buffers_sorted[i]["buff_score"] or 0)
        parties[target].append(dealer)
        used_keys.add(dealer["key"])
        party_dps[target] += dealer["dundam_dps"] or 0
        remaining[target] -= 1
        if party_dps[target] * (buffers_sorted[target]["buff_score"] or 0) >= clear_threshold:
            met[target] = True

    # 남은 슬롯은 전부 업둥 슬롯으로 채우기
    for i in range(3):
        while remaining[i] > 0:
            parties[i].append(dict(UNDERDOG_SLOT))
            remaining[i] -= 1

    return parties, None

# ─────────────────────────────────────────
# 숫자 → 한글 단위 변환
# ─────────────────────────────────────────
def format_korean(n):
    n = int(n)
    gyeong = n // 10_000_000_000_000_000
    n %= 10_000_000_000_000_000
    jo = n // 1_000_000_000_000
    n %= 1_000_000_000_000
    eok = n // 100_000_000
    n %= 100_000_000
    man = n // 10_000

    parts = []
    if gyeong: parts.append(f"{gyeong}경")
    if jo:     parts.append(f"{jo}조")
    if eok:    parts.append(f"{eok}억")
    if man:    parts.append(f"{man}만")
    return " ".join(parts) if parts else "0"

# ─────────────────────────────────────────
# 결과 출력
# ─────────────────────────────────────────
def print_result(parties, clear_threshold):
    print("\n========== 공격대 편성 결과 ==========")
    for i, party in enumerate(parties):
        power = calc_party_power(party)
        cleared = "✅ 클리어 가능" if power >= clear_threshold else "❌ 클리어 불가"
        print(f"\n[ 파티 {i+1} ] 전투력: {format_korean(power)}  {cleared}")
        for c in party:
            if c["role"] == "업둥":
                print(f"  [업둥]")
            elif c["role"] == "buffer":
                print(f"  [버퍼] {c['adven_name']} / {c['name']} / {c['job']} | 버프력: {c['buff_score']:,}")
            else:
                print(f"  [딜러] {c['adven_name']} / {c['name']} / {c['job']} | 딜량: {format_korean(c['dundam_dps'] or 0)}")
    print("\n=====================================")

# ─────────────────────────────────────────
# 메인
# ─────────────────────────────────────────
if __name__ == "__main__":
    s = load_settings()

    MIN_FAME         = int(s.get("min_fame", 63257))
    DEALER_THRESHOLD = int(s.get("dealer_cut", 300)) * 100_000_000
    BUFFER_THRESHOLD = int(s.get("buffer_cut", 400)) * 10_000
    CLEAR_THRESHOLD  = int(s.get("clear_dps", 1500)) * 100_000_000 * int(s.get("clear_buff", 680)) * 10_000

    print(f"=== 설정값 ===")
    print(f"명성컷: {MIN_FAME:,}")
    print(f"딜러컷: {DEALER_THRESHOLD // 100_000_000}억")
    print(f"버퍼컷: {BUFFER_THRESHOLD // 10_000}만")
    print(f"파티컷: {format_korean(CLEAR_THRESHOLD)}")

    characters = load_characters(MIN_FAME)
    print(f"\n명성 {MIN_FAME:,} 이상 캐릭터: {len(characters)}명")

    buffers, dealers, underdogs = classify(characters, DEALER_THRESHOLD, BUFFER_THRESHOLD)
    print(f"버퍼: {len(buffers)}명 / 딜러: {len(dealers)}명 / 업둥이: {len(underdogs)}명")

    parties, error = build_parties(buffers, dealers, underdogs, CLEAR_THRESHOLD)
    if error:
        print(f"\n오류: {error}")
    else:
        print_result(parties, CLEAR_THRESHOLD)
