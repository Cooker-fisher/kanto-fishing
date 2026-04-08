#!/usr/bin/env python3
"""
area_analysis.py — エリア × 釣り物 の旬・海況傾向分析

[エリア区分（lat/lonから自動分類）]
  東京湾奥        lat > 35.5,  lon < 140
  東京湾中部      lat 35.35-35.5, lon < 140
  金沢八景・久里浜  lat 35.2-35.35, lon 139.5-140
  相模湾西        lat < 35.35, lon < 139.5
  相模湾東・三浦   lat < 35.35, lon 139.5-140
  外房・茨城      lon >= 140
  静岡           lon < 139

[出力] analysis.sqlite:
  area_season     : エリア × 魚種 × 月 の集計
  area_decadal    : エリア × 魚種 × 旬 の集計

[使い方]
  python area_analysis.py                   # 計算・保存
  python area_analysis.py --calendar        # 全エリア × 全魚種 旬カレンダー
  python area_analysis.py --query アジ      # アジのエリア別旬比較
  python area_analysis.py --matrix          # 魚種 × エリア のピーク月マトリクス
"""

import csv, json, os, sqlite3, sys
from collections import defaultdict
from datetime import datetime

import sys as _sys; _sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _paths import ROOT_DIR, RESULTS_DIR, DATA_DIR, NORMALIZE_DIR, OCEAN_DIR
DB_PATH       = os.path.join(RESULTS_DIR, "analysis.sqlite")

def _build_raw_to_tsuri_map():
    path = os.path.join(NORMALIZE_DIR, "tsuri_mono_map_draft.json")
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    mapping = data.get("TSURI_MONO_MAP", {})
    raw_to_tsuri = {}
    for tsuri_mono, raw_list in mapping.items():
        if tsuri_mono.startswith("_"):
            continue
        for raw in raw_list:
            raw_to_tsuri[raw] = tsuri_mono
    return raw_to_tsuri

RAW_TO_TSURI = _build_raw_to_tsuri_map()

# ── エリア定義 ────────────────────────────────────────────────────────────
AREAS = [
    ("東京湾奥",        lambda lat, lon: lat > 35.5  and lon < 140.0),
    ("東京湾中部",      lambda lat, lon: 35.35 < lat <= 35.5 and lon < 140.0),
    ("金沢八景・久里浜", lambda lat, lon: 35.2 < lat <= 35.35 and lon >= 139.5 and lon < 140.0),
    ("相模湾西",        lambda lat, lon: lat <= 35.35 and lon < 139.5),
    ("相模湾東・三浦",   lambda lat, lon: lat <= 35.35 and 139.5 <= lon < 140.0),
    ("外房・茨城",      lambda lat, lon: lon >= 140.0),
    ("静岡",           lambda lat, lon: lon < 139.0),
]
AREA_NAMES = [a[0] for a in AREAS]

def classify_area(lat, lon):
    if lat is None or lon is None:
        return None
    for name, fn in AREAS:
        if fn(lat, lon):
            return name
    return None

# ── DB 初期化 ─────────────────────────────────────────────────────────────
def init_tables(conn):
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS area_season (
        area       TEXT,
        fish       TEXT,
        month      INTEGER,
        n          INTEGER,
        avg_cnt    REAL,
        avg_size   REAL,
        cnt_index  REAL,
        size_index REAL,
        updated_at TEXT,
        PRIMARY KEY (area, fish, month)
    );
    CREATE TABLE IF NOT EXISTS area_decadal (
        area       TEXT,
        fish       TEXT,
        decade_no  INTEGER,
        n          INTEGER,
        avg_cnt    REAL,
        avg_size   REAL,
        cnt_index  REAL,
        size_index REAL,
        updated_at TEXT,
        PRIMARY KEY (area, fish, decade_no)
    );
    CREATE TABLE IF NOT EXISTS area_peaks (
        area              TEXT,
        fish              TEXT,
        peak_cnt_month    INTEGER,
        max_cnt_month     REAL,
        peak_size_month   INTEGER,
        max_size_month    REAL,
        peak_cnt_decade   INTEGER,
        max_cnt_decade    REAL,
        peak_size_decade  INTEGER,
        max_size_decade   REAL,
        total_n           INTEGER,
        updated_at        TEXT,
        PRIMARY KEY (area, fish)
    );
    CREATE INDEX IF NOT EXISTS idx_area_season_fish ON area_season (fish);
    CREATE INDEX IF NOT EXISTS idx_area_dec_fish    ON area_decadal (fish);
    CREATE INDEX IF NOT EXISTS idx_area_peaks_fish  ON area_peaks (fish);
    """)
    conn.commit()

# ── データロード（coord_mapはanalysis.sqlite combo_metaから） ──────────────
def _float(v):
    try:
        return float(v) if v not in ("", None) else None
    except (ValueError, TypeError):
        return None

def _avg_size(row):
    lo, hi = _float(row.get("size_min")), _float(row.get("size_max"))
    return (lo + hi) / 2 if lo and hi else lo or hi

def decade_no(d):
    return (d.month - 1) * 3 + (0 if d.day <= 10 else 1 if d.day <= 20 else 2) + 1

def load_records(conn, fish_filter=None):
    """data/YYYY-MM.csv を読み、各レコードにエリアを付与して返す。"""
    # ship → (lat, lon) マップ（combo_meta から）
    ship_coords = {}
    for fish, ship, lat, lon in conn.execute("SELECT fish, ship, lat, lon FROM combo_meta").fetchall():
        if lat and lon and ship not in ship_coords:
            ship_coords[ship] = (lat, lon)

    records = []
    for fn in sorted(os.listdir(DATA_DIR)):
        if not fn.endswith(".csv") or fn == "cancellations.csv":
            continue
        with open(os.path.join(DATA_DIR, fn), encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                if row.get("is_cancellation") == "1":
                    continue
                fish_raw = row.get("fish_raw", "").strip()
                if fish_raw in RAW_TO_TSURI:
                    fish = RAW_TO_TSURI[fish_raw]
                else:
                    fish = row.get("tsuri_mono", "").strip()
                if not fish or row.get("main_sub") != "メイン":
                    continue
                if fish_filter and fish != fish_filter:
                    continue
                cnt = _float(row.get("cnt_avg"))
                if not cnt or cnt <= 0:
                    continue
                try:
                    d = datetime.strptime(row["date"], "%Y/%m/%d")
                except ValueError:
                    continue
                ship = row.get("ship", "")
                lat, lon = ship_coords.get(ship, (None, None))
                area = classify_area(lat, lon)
                if not area:
                    continue
                records.append({
                    "fish":  fish,
                    "area":  area,
                    "ship":  ship,
                    "month": d.month,
                    "dec":   decade_no(d),
                    "cnt":   cnt,
                    "size":  _avg_size(row),
                })
    return records

# ── 集計 ─────────────────────────────────────────────────────────────────
def aggregate(records, key_fn, min_n=5):
    buckets = defaultdict(lambda: {"cnt": [], "size": []})
    for r in records:
        key = key_fn(r)
        buckets[key]["cnt"].append(r["cnt"])
        if r["size"] is not None:
            buckets[key]["size"].append(r["size"])
    result = {}
    for key, d in buckets.items():
        if len(d["cnt"]) < min_n:
            continue
        result[key] = {
            "n":       len(d["cnt"]),
            "avg_cnt": sum(d["cnt"]) / len(d["cnt"]),
            "avg_size":sum(d["size"]) / len(d["size"]) if d["size"] else None,
        }
    return result

def add_indices(data, fish_key_fn):
    """魚種×エリアごとの全期間平均を100として指数化。"""
    # (fish, area) → 全期間の全値
    fish_area_cnts  = defaultdict(list)
    fish_area_sizes = defaultdict(list)
    for key, d in data.items():
        fa = fish_key_fn(key)
        fish_area_cnts[fa].append(d["avg_cnt"])
        if d["avg_size"]: fish_area_sizes[fa].append(d["avg_size"])

    result = {}
    for key, d in data.items():
        fa = fish_key_fn(key)
        gc = sum(fish_area_cnts[fa]) / len(fish_area_cnts[fa])
        gs = sum(fish_area_sizes[fa]) / len(fish_area_sizes[fa]) if fish_area_sizes[fa] else None
        result[key] = {
            **d,
            "cnt_index":  round(d["avg_cnt"] / gc * 100, 1) if gc else None,
            "size_index": round(d["avg_size"] / gs * 100, 1) if (d["avg_size"] and gs) else None,
        }
    return result

# ── DB 保存 ───────────────────────────────────────────────────────────────
def save(conn, monthly, decadal):
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    rows = [(area, fish, month, d["n"], round(d["avg_cnt"],2),
             round(d["avg_size"],2) if d["avg_size"] else None,
             d["cnt_index"], d["size_index"], now)
            for (area, fish, month), d in monthly.items()]
    conn.executemany("INSERT OR REPLACE INTO area_season VALUES (?,?,?,?,?,?,?,?,?)", rows)

    rows = [(area, fish, dec, d["n"], round(d["avg_cnt"],2),
             round(d["avg_size"],2) if d["avg_size"] else None,
             d["cnt_index"], d["size_index"], now)
            for (area, fish, dec), d in decadal.items()]
    conn.executemany("INSERT OR REPLACE INTO area_decadal VALUES (?,?,?,?,?,?,?,?,?)", rows)
    conn.commit()
    print(f"保存: area_season {len(monthly)}件 / area_decadal {len(decadal)}件")


def save_peaks(conn):
    """area_season / area_decadal からピーク値を集約して area_peaks に保存。"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    rows = []
    for area, fish in conn.execute(
        "SELECT DISTINCT area, fish FROM area_season ORDER BY area, fish"
    ).fetchall():
        # 月ピーク
        r_cnt  = conn.execute(
            "SELECT month, avg_cnt  FROM area_season WHERE area=? AND fish=? ORDER BY avg_cnt  DESC LIMIT 1",
            (area, fish)
        ).fetchone()
        r_size = conn.execute(
            "SELECT month, avg_size FROM area_season WHERE area=? AND fish=? AND avg_size IS NOT NULL ORDER BY avg_size DESC LIMIT 1",
            (area, fish)
        ).fetchone()
        # 旬ピーク
        d_cnt  = conn.execute(
            "SELECT decade_no, avg_cnt  FROM area_decadal WHERE area=? AND fish=? ORDER BY avg_cnt  DESC LIMIT 1",
            (area, fish)
        ).fetchone()
        d_size = conn.execute(
            "SELECT decade_no, avg_size FROM area_decadal WHERE area=? AND fish=? AND avg_size IS NOT NULL ORDER BY avg_size DESC LIMIT 1",
            (area, fish)
        ).fetchone()
        # 総件数
        total_n = conn.execute(
            "SELECT SUM(n) FROM area_season WHERE area=? AND fish=?", (area, fish)
        ).fetchone()[0]

        rows.append((
            area, fish,
            r_cnt[0]  if r_cnt  else None, r_cnt[1]  if r_cnt  else None,
            r_size[0] if r_size else None, r_size[1] if r_size else None,
            d_cnt[0]  if d_cnt  else None, d_cnt[1]  if d_cnt  else None,
            d_size[0] if d_size else None, d_size[1] if d_size else None,
            total_n, now,
        ))

    conn.executemany(
        "INSERT OR REPLACE INTO area_peaks VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", rows
    )
    conn.commit()
    print(f"保存: area_peaks {len(rows)}件")

# ── 表示 ─────────────────────────────────────────────────────────────────
DECADE_SHORT = []
for m in range(1, 13):
    for p in ["上", "中", "下"]:
        DECADE_SHORT.append(f"{m}{p}")

def query_fish(conn, fish):
    """エリア別の旬グリッド（数量 + 型）を表示。"""
    print(f"\n{'='*70}")
    print(f"=== {fish} エリア別旬カレンダー ===")
    print(f"{'='*70}")

    # ヘッダ
    hdr = f"  {'エリア':<14}"
    for m in range(1, 13):
        hdr += f"|{m}上 {m}中 {m}下"
    print(hdr)
    print("  " + "-"*14 + ("|" + "-"*11)*12)

    print("--- 数量（平均匹数）---")
    for area in AREA_NAMES:
        rows = conn.execute(
            "SELECT decade_no, avg_cnt FROM area_decadal WHERE fish=? AND area=? ORDER BY decade_no",
            (fish, area)
        ).fetchall()
        if not rows:
            continue
        d = {r[0]: r[1] for r in rows}
        peak = max(d, key=d.get)
        line = f"  {area:<14}"
        for dec in range(1, 37):
            if (dec-1) % 3 == 0: line += "|"
            val = d.get(dec)
            if val is None:
                line += "   -"
            elif dec == peak:
                line += f"[{val:>2.0f}]"[:4]
            else:
                line += f"{val:>4.0f}"
        print(line)

    print("\n--- 型（平均サイズcm）---")
    for area in AREA_NAMES:
        rows = conn.execute(
            "SELECT decade_no, avg_size FROM area_decadal WHERE fish=? AND area=? AND avg_size IS NOT NULL ORDER BY decade_no",
            (fish, area)
        ).fetchall()
        if not rows:
            continue
        d = {r[0]: r[1] for r in rows}
        peak = max(d, key=d.get)
        line = f"  {area:<14}"
        for dec in range(1, 37):
            if (dec-1) % 3 == 0: line += "|"
            val = d.get(dec)
            if val is None:
                line += "    -"
            elif dec == peak:
                line += f"[{val:>3.0f}]"[:5]
            else:
                line += f"{val:>5.1f}"
        print(line)

    # サマリー
    print(f"\n--- エリア別ピークまとめ ---")
    print(f"  {'エリア':<14} {'数量ピーク旬':<14} {'最大匹数':>8}  {'型ピーク旬':<14} {'最大cm':>7}")
    print("  " + "-"*60)
    for area in AREA_NAMES:
        cnt_rows  = conn.execute("SELECT decade_no, avg_cnt  FROM area_decadal WHERE fish=? AND area=? ORDER BY avg_cnt  DESC LIMIT 1", (fish, area)).fetchone()
        size_rows = conn.execute("SELECT decade_no, avg_size FROM area_decadal WHERE fish=? AND area=? AND avg_size IS NOT NULL ORDER BY avg_size DESC LIMIT 1", (fish, area)).fetchone()
        if not cnt_rows:
            continue
        cnt_dec  = DECADE_SHORT[cnt_rows[0]-1]  if cnt_rows  else "-"
        size_dec = DECADE_SHORT[size_rows[0]-1] if size_rows else "-"
        cnt_val  = f"{cnt_rows[1]:.0f}匹"  if cnt_rows  else "-"
        size_val = f"{size_rows[1]:.1f}cm" if size_rows else "-"
        print(f"  {area:<14} {cnt_dec:<14} {cnt_val:>8}  {size_dec:<14} {size_val:>7}")


def show_matrix(conn):
    """魚種 × エリア のピーク月マトリクス。"""
    print(f"\n{'='*80}")
    print(f"=== 魚種 × エリア ピーク月マトリクス（数量） ===")
    print(f"{'='*80}")
    print(f"  {'魚種':<10}" + "".join(f" {a[:5]:>7}" for a in AREA_NAMES))
    print("  " + "-"*80)

    fish_list = [r[0] for r in conn.execute(
        "SELECT DISTINCT fish FROM area_season ORDER BY fish"
    ).fetchall()]

    for fish in fish_list:
        cells = []
        for area in AREA_NAMES:
            row = conn.execute(
                "SELECT month FROM area_season WHERE fish=? AND area=? ORDER BY avg_cnt DESC LIMIT 1",
                (fish, area)
            ).fetchone()
            cells.append(f"{row[0]}月" if row else " -")
        print(f"  {fish:<10}" + "".join(f" {c:>7}" for c in cells))


def show_area_calendar(conn):
    """全エリア × 全魚種の旬カレンダー（エリアごとに表示）。"""
    for area in AREA_NAMES:
        fish_list = [r[0] for r in conn.execute(
            "SELECT DISTINCT fish FROM area_decadal WHERE area=? ORDER BY fish", (area,)
        ).fetchall()]
        if not fish_list:
            continue
        print(f"\n{'='*70}")
        print(f"=== {area} ===")
        print(f"  {'魚種':<10}", end="")
        for m in range(1, 13):
            print(f" {m}月", end="")
            print("      ", end="")
        print()
        print("  " + "-"*10 + ("|上 中 下")*12)

        for fish in fish_list:
            rows = conn.execute(
                "SELECT decade_no, cnt_index FROM area_decadal WHERE fish=? AND area=? ORDER BY decade_no",
                (fish, area)
            ).fetchall()
            d = {r[0]: r[1] for r in rows}
            if not d: continue
            peak = max(d, key=d.get)
            line = f"  {fish:<10}"
            for dec in range(1, 37):
                if (dec-1) % 3 == 0: line += "|"
                idx = d.get(dec)
                if idx is None:
                    line += "  -"
                elif dec == peak:
                    line += f"[{idx:>3.0f}]"[:4]
                elif idx >= 130:
                    line += f"{idx:>3.0f}*"
                else:
                    line += f"{idx:>4.0f}"
            print(line)


# ── メイン ────────────────────────────────────────────────────────────────
def main():
    args = sys.argv[1:]
    mode = "save"
    fish_filter = None
    i = 0
    while i < len(args):
        if args[i] == "--fish" and i+1 < len(args):
            fish_filter = args[i+1]; i += 2
        elif args[i] == "--query" and i+1 < len(args):
            mode = "query"; fish_filter = args[i+1]; i += 2
        elif args[i] == "--matrix":
            mode = "matrix"; i += 1
        elif args[i] == "--calendar":
            mode = "calendar"; i += 1
        else:
            i += 1

    conn = sqlite3.connect(DB_PATH)
    init_tables(conn)

    if mode == "query":
        query_fish(conn, fish_filter)
        conn.close()
        return
    if mode == "matrix":
        show_matrix(conn)
        conn.close()
        return
    if mode == "calendar":
        show_area_calendar(conn)
        conn.close()
        return

    print(f"=== area_analysis.py 開始 ===")
    if fish_filter: print(f"  魚種フィルタ: {fish_filter}")

    records = load_records(conn, fish_filter)
    print(f"レコード: {len(records):,}件（エリア付与済み）")

    # エリアごとの件数確認
    from collections import Counter
    area_cnt = Counter(r["area"] for r in records)
    for area in AREA_NAMES:
        print(f"  {area}: {area_cnt.get(area, 0):,}件")

    monthly = aggregate(records, lambda r: (r["area"], r["fish"], r["month"]))
    monthly = add_indices(monthly, lambda k: (k[0], k[1]))
    print(f"月別集計: {len(monthly)}件")

    decadal = aggregate(records, lambda r: (r["area"], r["fish"], r["dec"]), min_n=3)
    decadal = add_indices(decadal, lambda k: (k[0], k[1]))
    print(f"旬別集計: {len(decadal)}件")

    save(conn, monthly, decadal)
    save_peaks(conn)
    conn.close()
    print(f"\n=== 完了 ===")
    print(f"  python area_analysis.py --query アジ   # アジのエリア別旬比較")
    print(f"  python area_analysis.py --matrix        # 全魚種ピーク月マトリクス")
    print(f"  python area_analysis.py --calendar      # エリア別全魚種カレンダー")


if __name__ == "__main__":
    main()
