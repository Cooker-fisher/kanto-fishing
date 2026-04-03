#!/usr/bin/env python3
"""
ship_peaks.py — 船宿 × 釣り物 × 旬 のピーク分析

combo_decadal（fish × ship × decade_no）を読み、
各コンボの旬別指数・ピーク旬を集計して ship_peaks テーブルに保存する。

[出力] analysis.sqlite:
  ship_peaks     : (fish, ship) ごとのピーク旬・指数まとめ
  ship_decadal   : (fish, ship, decade_no) ごとの指数付き旬別データ

[使い方]
  python ship_peaks.py                  # 計算・保存
  python ship_peaks.py --query アジ     # アジの船宿別旬ピーク一覧
  python ship_peaks.py --grid アジ      # アジの船宿×旬グリッド表示
  python ship_peaks.py --area アジ      # アジをエリア別にまとめた旬カレンダー
"""

import os, sqlite3, sys
from collections import defaultdict
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH  = os.path.join(BASE_DIR, "analysis.sqlite")

# エリア分類（area_analysis.py と同じ定義）
AREAS = [
    ("東京湾奥",        lambda lat, lon: lat > 35.5  and lon < 140.0),
    ("東京湾中部",      lambda lat, lon: 35.35 < lat <= 35.5 and lon < 140.0),
    ("金沢八景・久里浜", lambda lat, lon: 35.2 < lat <= 35.35 and lon >= 139.5 and lon < 140.0),
    ("相模湾西",        lambda lat, lon: lat <= 35.35 and lon < 139.5),
    ("相模湾東・三浦",   lambda lat, lon: lat <= 35.35 and 139.5 <= lon < 140.0),
    ("外房・茨城",      lambda lat, lon: lon >= 140.0),
    ("静岡",           lambda lat, lon: lon < 139.0),
]

def classify_area(lat, lon):
    if lat is None or lon is None:
        return None
    for name, fn in AREAS:
        try:
            if fn(lat, lon):
                return name
        except Exception:
            pass
    return None

DECADE_LABEL = []
for _m in range(1, 13):
    for _p in ["上", "中", "下"]:
        DECADE_LABEL.append(f"{_m}月{_p}旬")


def init_tables(conn):
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS ship_decadal (
        fish        TEXT,
        ship        TEXT,
        area        TEXT,
        decade_no   INTEGER,
        n           INTEGER,
        avg_cnt     REAL,
        avg_size    REAL,
        cnt_index   REAL,
        size_index  REAL,
        updated_at  TEXT,
        PRIMARY KEY (fish, ship, decade_no)
    );
    CREATE TABLE IF NOT EXISTS ship_peaks (
        fish               TEXT,
        ship               TEXT,
        area               TEXT,
        peak_cnt_decade    INTEGER,
        max_cnt            REAL,
        cnt_index_peak     REAL,
        peak_size_decade   INTEGER,
        max_size           REAL,
        top3_cnt_decades   TEXT,
        total_n            INTEGER,
        updated_at         TEXT,
        PRIMARY KEY (fish, ship)
    );
    CREATE INDEX IF NOT EXISTS idx_ship_dec_fish  ON ship_decadal (fish);
    CREATE INDEX IF NOT EXISTS idx_ship_dec_area  ON ship_decadal (area);
    CREATE INDEX IF NOT EXISTS idx_ship_peaks_fish ON ship_peaks (fish);
    CREATE INDEX IF NOT EXISTS idx_ship_peaks_area ON ship_peaks (area);
    """)
    conn.commit()


def build_ship_decadal(conn):
    """combo_decadal + combo_meta から ship_decadal を生成。"""
    # エリアマップ
    area_map = {}
    for fish, ship, lat, lon in conn.execute(
        "SELECT fish, ship, lat, lon FROM combo_meta"
    ).fetchall():
        if ship not in area_map and lat and lon:
            area_map[ship] = classify_area(lat, lon)

    # combo_decadal を全件取得
    rows = conn.execute(
        "SELECT fish, ship, decade_no, n, avg_cnt, avg_size FROM combo_decadal"
    ).fetchall()

    # (fish, ship) ごとに grand_avg を計算してから index 付与
    combo_cnts  = defaultdict(list)
    combo_sizes = defaultdict(list)
    for fish, ship, dec, n, avg_cnt, avg_size in rows:
        if avg_cnt:
            combo_cnts[(fish, ship)].append(avg_cnt)
        if avg_size:
            combo_sizes[(fish, ship)].append(avg_size)

    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    out = []
    for fish, ship, dec, n, avg_cnt, avg_size in rows:
        area = area_map.get(ship)
        key = (fish, ship)
        gc = sum(combo_cnts[key]) / len(combo_cnts[key]) if combo_cnts[key] else None
        gs = sum(combo_sizes[key]) / len(combo_sizes[key]) if combo_sizes[key] else None
        cnt_idx  = round(avg_cnt  / gc * 100, 1) if (avg_cnt  and gc) else None
        size_idx = round(avg_size / gs * 100, 1) if (avg_size and gs) else None
        out.append((
            fish, ship, area, dec, n,
            round(avg_cnt,  2) if avg_cnt  else None,
            round(avg_size, 2) if avg_size else None,
            cnt_idx, size_idx, now,
        ))

    conn.executemany(
        "INSERT OR REPLACE INTO ship_decadal VALUES (?,?,?,?,?,?,?,?,?,?)", out
    )
    conn.commit()
    print(f"保存: ship_decadal {len(out)}件")
    return out


def build_ship_peaks(conn):
    """ship_decadal から ship_peaks を生成。"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    combos = conn.execute(
        "SELECT DISTINCT fish, ship, area FROM ship_decadal ORDER BY fish, ship"
    ).fetchall()

    rows = []
    for fish, ship, area in combos:
        # 数量ピーク
        cnt_rows = conn.execute(
            "SELECT decade_no, avg_cnt, cnt_index FROM ship_decadal "
            "WHERE fish=? AND ship=? AND avg_cnt IS NOT NULL ORDER BY avg_cnt DESC",
            (fish, ship)
        ).fetchall()
        # 型ピーク
        size_row = conn.execute(
            "SELECT decade_no, avg_size FROM ship_decadal "
            "WHERE fish=? AND ship=? AND avg_size IS NOT NULL ORDER BY avg_size DESC LIMIT 1",
            (fish, ship)
        ).fetchone()
        # 総件数
        total_n = conn.execute(
            "SELECT SUM(n) FROM ship_decadal WHERE fish=? AND ship=?", (fish, ship)
        ).fetchone()[0]

        if not cnt_rows:
            continue
        peak_dec, max_cnt, cnt_idx = cnt_rows[0]
        top3 = ",".join(str(r[0]) for r in cnt_rows[:3])
        peak_size_dec = size_row[0] if size_row else None
        max_size      = size_row[1] if size_row else None

        rows.append((
            fish, ship, area,
            peak_dec, round(max_cnt, 2), cnt_idx,
            peak_size_dec, round(max_size, 2) if max_size else None,
            top3, total_n, now,
        ))

    conn.executemany(
        "INSERT OR REPLACE INTO ship_peaks VALUES (?,?,?,?,?,?,?,?,?,?,?)", rows
    )
    conn.commit()
    print(f"保存: ship_peaks {len(rows)}件")


# ── 表示モード ────────────────────────────────────────────────────────────────

def query_fish(conn, fish):
    """指定魚種の船宿別ピーク旬一覧。"""
    rows = conn.execute(
        "SELECT ship, area, peak_cnt_decade, max_cnt, cnt_index_peak, "
        "peak_size_decade, max_size, top3_cnt_decades, total_n "
        "FROM ship_peaks WHERE fish=? ORDER BY max_cnt DESC",
        (fish,)
    ).fetchall()
    if not rows:
        print(f"{fish} のデータなし")
        return

    print(f"\n{'='*75}")
    print(f"=== {fish} 船宿別 旬ピーク ===")
    print(f"{'='*75}")
    print(f"  {'船宿':<12} {'エリア':<14} {'数量ピーク旬':<12} {'最大匹':<7} {'index':<7} {'型ピーク旬':<12} {'最大cm':<7} {'件数'}")
    print("  " + "-" * 75)
    for ship, area, pd, mc, ci, psd, ms, top3, n in rows:
        pd_s  = DECADE_LABEL[pd-1]  if pd  else "-"
        psd_s = DECADE_LABEL[psd-1] if psd else "-"
        mc_s  = f"{mc:.0f}匹" if mc else "-"
        ci_s  = f"{ci:.0f}"   if ci else "-"
        ms_s  = f"{ms:.1f}cm" if ms else "-"
        area_s = area or "-"
        print(f"  {ship:<12} {area_s:<14} {pd_s:<12} {mc_s:<7} {ci_s:<7} {psd_s:<12} {ms_s:<7} {n}")


def grid_fish(conn, fish):
    """指定魚種の船宿×旬グリッド（数量index）。"""
    ships = [r[0] for r in conn.execute(
        "SELECT DISTINCT ship FROM ship_decadal WHERE fish=? ORDER BY ship", (fish,)
    ).fetchall()]
    if not ships:
        print(f"{fish} のデータなし")
        return

    print(f"\n{'='*90}")
    print(f"=== {fish} 船宿×旬グリッド（数量index, 全期間平均=100） ===")
    print(f"{'='*90}")

    # ヘッダ
    hdr = f"  {'船宿':<12}"
    for m in range(1, 13):
        hdr += f"|{m:>2}上  中  下"
    print(hdr)
    print("  " + "-"*12 + ("|" + "-"*10)*12)

    for ship in ships:
        d = {r[0]: r[1] for r in conn.execute(
            "SELECT decade_no, cnt_index FROM ship_decadal WHERE fish=? AND ship=? ORDER BY decade_no",
            (fish, ship)
        ).fetchall()}
        if not d:
            continue
        peak = max(d, key=lambda k: d[k] if d[k] else 0)
        line = f"  {ship:<12}"
        for dec in range(1, 37):
            if (dec-1) % 3 == 0:
                line += "|"
            val = d.get(dec)
            if val is None:
                line += "   -"
            elif dec == peak:
                v = int(val)
                line += f"[{v:>3}]"[:4]
            elif val >= 130:
                line += f"{int(val):>3}*"
            else:
                line += f"{int(val):>4}"
        print(line)


def area_fish(conn, fish):
    """指定魚種のエリア別旬カレンダー（ship_decadal の加重平均）。"""
    rows = conn.execute(
        "SELECT area, decade_no, SUM(n*avg_cnt)/SUM(n) as wavg_cnt, "
        "SUM(CASE WHEN avg_size IS NOT NULL THEN n ELSE 0 END) as sn, "
        "SUM(CASE WHEN avg_size IS NOT NULL THEN n*avg_size ELSE 0 END) as wsize_sum "
        "FROM ship_decadal WHERE fish=? AND area IS NOT NULL "
        "GROUP BY area, decade_no HAVING SUM(n) >= 3",
        (fish,)
    ).fetchall()
    if not rows:
        print(f"{fish} のエリアデータなし")
        return

    # area × dec → wavg
    from collections import defaultdict
    area_dec = defaultdict(dict)
    area_size_dec = defaultdict(dict)
    for area, dec, wavg, sn, wsum in rows:
        area_dec[area][dec] = wavg
        if sn and sn > 0:
            area_size_dec[area][dec] = wsum / sn

    # 指数化
    area_dec_idx = {}
    for area, dec_map in area_dec.items():
        vals = list(dec_map.values())
        grand = sum(vals) / len(vals) if vals else 1
        area_dec_idx[area] = {dec: round(v/grand*100, 1) for dec, v in dec_map.items()}

    print(f"\n{'='*90}")
    print(f"=== {fish} エリア別旬カレンダー（船宿データから集計） ===")
    print(f"{'='*90}")
    hdr = f"  {'エリア':<14}"
    for m in range(1, 13):
        hdr += f"|{m:>2}上  中  下"
    print(hdr)
    print("  " + "-"*14 + ("|" + "-"*10)*12)

    for area in [a[0] for a in AREAS]:
        if area not in area_dec_idx:
            continue
        d = area_dec_idx[area]
        raw = area_dec[area]
        peak = max(d, key=lambda k: d[k] if d[k] else 0)
        line = f"  {area:<14}"
        for dec in range(1, 37):
            if (dec-1) % 3 == 0:
                line += "|"
            val = d.get(dec)
            if val is None:
                line += "   -"
            elif dec == peak:
                line += f"[{int(val):>3}]"[:4]
            elif val >= 130:
                line += f"{int(val):>3}*"
            else:
                line += f"{int(val):>4}"
        # ピークまとめ
        peak_label = DECADE_LABEL[peak-1]
        peak_cnt   = raw.get(peak, 0)
        print(f"{line}  <- {peak_label} {peak_cnt:.0f}匹")


# ── メイン ────────────────────────────────────────────────────────────────────

def main():
    args = sys.argv[1:]
    mode = "save"
    fish_arg = None
    i = 0
    while i < len(args):
        if args[i] == "--query" and i+1 < len(args):
            mode = "query"; fish_arg = args[i+1]; i += 2
        elif args[i] == "--grid" and i+1 < len(args):
            mode = "grid"; fish_arg = args[i+1]; i += 2
        elif args[i] == "--area" and i+1 < len(args):
            mode = "area"; fish_arg = args[i+1]; i += 2
        else:
            i += 1

    conn = sqlite3.connect(DB_PATH)
    init_tables(conn)

    if mode == "query":
        query_fish(conn, fish_arg)
        conn.close()
        return
    if mode == "grid":
        grid_fish(conn, fish_arg)
        conn.close()
        return
    if mode == "area":
        area_fish(conn, fish_arg)
        conn.close()
        return

    print("=== ship_peaks.py 開始 ===")
    build_ship_decadal(conn)
    build_ship_peaks(conn)
    conn.close()
    print("\n=== 完了 ===")
    print("  python ship_peaks.py --query アジ   # 船宿別ピーク旬一覧")
    print("  python ship_peaks.py --grid  アジ   # 船宿×旬グリッド（index）")
    print("  python ship_peaks.py --area  アジ   # エリア別旬カレンダー（船宿集計）")


if __name__ == "__main__":
    main()
