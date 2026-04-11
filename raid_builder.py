import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "characters.db")
PARTY_LABELS = ['R', 'Y', 'G']


# ─────────────────────────────────────────
# 메인 진입점
# ─────────────────────────────────────────
def build_raids():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    settings = {r['key']: r['value'] for r in conn.execute("SELECT key, value FROM settings")}

    raid_count = int(settings.get('raid_count', 4))
    min_fame   = int(settings.get('min_fame', 0))
    dealer_cut = settings.get('dealer_cut', 300)   # 억 단위 (DB와 동일)
    buffer_cut = settings.get('buffer_cut', 400)   # 만 단위 (DB와 동일)
    party_cut  = settings.get('clear_dps', 1500) * settings.get('clear_buff', 680)  # 억×만

    # 참여 모험단(active=1)의 active 캐릭터 중 명성컷 이상만 로드
    rows = conn.execute("""
        SELECT c.key, c.adven_name, c.name, c.job, c.dundam_dps, c.buff_score, c.fame
        FROM characters c
        JOIN adventurers a ON c.adven_name = a.adven_name
        WHERE c.active = 1 AND a.active = 1 AND c.fame >= ?
    """, (min_fame,)).fetchall()
    conn.close()

    chars = [_classify(dict(r), dealer_cut, buffer_cut) for r in rows]

    # 회차별 캐릭터 배분 (역할 균등 분배)
    runs = _assign_to_runs(chars, raid_count, party_cut)

    return [_compose_run(run_chars, party_cut, i + 1)
            for i, run_chars in enumerate(runs)]


# ─────────────────────────────────────────
# 회차별 캐릭터 배분
# ─────────────────────────────────────────
def _assign_to_runs(chars, raid_count, party_cut):
    """
    회차 0부터 순서대로 최대 12명씩 채움.
    한 번 배정된 캐릭터는 이후 회차에서 제외.
    같은 모험단은 회차당 1캐릭터만 허용.

    회차 내 배정 우선순위:
      1. 약한 버퍼 3명 (파티당 1명)
      2. 파티컷 달성에 필요한 딜러만 (시뮬레이션)
      3. 업둥 (남은 슬롯)
    """
    buffers   = sorted([c for c in chars if c['role'] == 'buffer'], key=lambda c: c['combat'])
    dealers   = sorted([c for c in chars if c['role'] == 'dealer'], key=lambda c: -c['combat'])
    underdogs = sorted([c for c in chars if c['role'] == '업둥'],   key=lambda c: -c['combat'])

    used_keys = set()   # 전체 회차에서 이미 배정된 캐릭터 key

    def pick(pool, used_advens, limit):
        """pool에서 used_advens와 used_keys에 걸리지 않는 캐릭터를 최대 limit명 뽑기."""
        picked = []
        for c in pool:
            if len(picked) >= limit:
                break
            if c['key'] not in used_keys and c['adven_name'] not in used_advens:
                picked.append(c)
                used_advens.add(c['adven_name'])
        return picked

    runs = []
    for _ in range(raid_count):
        used_advens = set()
        run_chars   = []

        # 1. 버퍼 최대 3명 (약한 버퍼부터)
        bufs = pick(buffers, used_advens, 3)
        run_chars.extend(bufs)

        # 2. 이번 회차 파티컷 달성에 필요한 딜러 수 시뮬레이션
        avail_dealers = [d for d in dealers if d['key'] not in used_keys]
        buf_scores    = [b['combat'] for b in bufs]
        dealer_limit  = _simulate_dealer_count(buf_scores, avail_dealers, party_cut)

        # 3. 딜러 (파티컷 달성에 필요한 수만큼)
        deas = pick(dealers, used_advens, dealer_limit)
        run_chars.extend(deas)

        # 4. 남은 슬롯: 버퍼(여분) + 딜러(초과) + 업둥 전부 합쳐서 combat 낮은 순으로 채우기
        filler_pool = sorted(buffers + dealers + underdogs, key=lambda c: c['combat'])
        filler = pick(filler_pool, used_advens, 12 - len(run_chars))
        run_chars.extend(filler)

        # 이번 회차에 배정된 캐릭터를 전체 used에 등록
        for c in run_chars:
            used_keys.add(c['key'])

        runs.append(run_chars)

    return runs


# ─────────────────────────────────────────
# 회차 딜러 수 시뮬레이션
# ─────────────────────────────────────────
def _simulate_dealer_count(buf_scores, avail_dealers, party_cut):
    """
    3개 파티 각각에 파티컷 달성까지 필요한 딜러 수를 합산.
    avail_dealers: 강한 순 정렬.
    """
    total     = 0
    remaining = list(avail_dealers)
    for buf_score in buf_scores:
        if not remaining or not buf_score:
            continue
        running_dps = 0
        count       = 0
        for d in remaining:
            running_dps += d['combat']
            count       += 1
            if running_dps * buf_score >= party_cut or count == 3:
                break
        total    += count
        remaining = remaining[count:]
    return total


# ─────────────────────────────────────────
# 캐릭터 분류
# ─────────────────────────────────────────
def _classify(c, dealer_cut, buffer_cut):
    """dundam_dps / buff_score 중 기록된 컬럼으로 역할 결정."""
    if c['buff_score']:
        c['char_type'] = 'buffer'
        c['role']      = 'buffer' if c['buff_score'] >= buffer_cut else '업둥'
        c['combat']    = c['buff_score']
    else:
        dps = c['dundam_dps'] or 0
        c['char_type'] = 'dealer'
        c['role']      = 'dealer' if dps >= dealer_cut else '업둥'
        c['combat']    = dps
    return c


# ─────────────────────────────────────────
# 회차 내 파티 구성
# ─────────────────────────────────────────
def _compose_run(run_chars, party_cut, run_num):
    """
    파티 구성:
    1. 버퍼컷 통과 버퍼를 약한 순으로 파티당 1명
    2. 각 파티: 딜러컷 통과 딜러를 강한 순으로 파티컷 달성까지 배치 (최대 3명)
    3. 남은 슬롯: combat 낮은 캐릭터부터 (동일 모험단 제외) → 없으면 야생
    """
    buffers = sorted([c for c in run_chars if c['role'] == 'buffer'], key=lambda c: c['combat'])
    dealers = sorted([c for c in run_chars if c['role'] == 'dealer'], key=lambda c: -c['combat'])

    assigned_keys = set()
    parties       = []

    for i in range(3):
        party_advens = set()
        slots        = []

        # 1. 버퍼 배치 (약한 순)
        buf = buffers[i] if i < len(buffers) else None
        if buf:
            slots.append(buf)
            party_advens.add(buf['adven_name'])
            assigned_keys.add(buf['key'])
        else:
            slots.append(_wild())

        # 2. 딜러 배치: 강한 순으로 파티컷 달성까지
        if buf:
            for d in dealers:
                if len(slots) >= 4:
                    break
                if d['key'] in assigned_keys or d['adven_name'] in party_advens:
                    continue
                slots.append(d)
                party_advens.add(d['adven_name'])
                assigned_keys.add(d['key'])
                dealer_dps = sum(s['combat'] for s in slots if s['role'] == 'dealer')
                if dealer_dps * buf['combat'] >= party_cut:
                    break  # 파티컷 달성

        # 3. 남은 슬롯: combat 낮은 캐릭터부터 채우기
        remaining = sorted(
            [c for c in run_chars if c['key'] not in assigned_keys],
            key=lambda c: c['combat']
        )
        while len(slots) < 4:
            placed = False
            for c in remaining:
                if c['adven_name'] not in party_advens:
                    slots.append(c)
                    party_advens.add(c['adven_name'])
                    assigned_keys.add(c['key'])
                    remaining.remove(c)
                    placed = True
                    break
            if not placed:
                slots.append(_wild())

        parties.append({'label': PARTY_LABELS[i], 'slots': slots})

    return {'run': run_num, 'parties': parties}


# ─────────────────────────────────────────
# 야생 슬롯
# ─────────────────────────────────────────
def _wild():
    return {'key': None, 'adven_name': None, 'name': '야생',
            'job': '-', 'role': '야생', 'combat': 0}


# ─────────────────────────────────────────
# 콘솔 실행
# ─────────────────────────────────────────
if __name__ == '__main__':
    raids = build_raids()
    for raid in raids:
        print(f"\n{'='*44}")
        print(f"  {raid['run']}회차")
        for party in raid['parties']:
            print(f"\n  [{party['label']}파티]")
            for s in party['slots']:
                if s.get('char_type') == 'buffer':
                    stat = f"버프력 {s['combat']}만" if s['combat'] else '-'
                else:
                    stat = f"딜 {s['combat']}억" if s['combat'] else '-'
                print(f"    {s['name']:12s}  {s['role']:5s}  {stat}")
