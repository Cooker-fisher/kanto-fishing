#!/usr/bin/env python3
"""
season_analysis.py — 船宿×釣り物ごとの「旬カレンダー」分析

[入力]
  data/YYYY-MM.csv  (cnt_avg, size_min, size_max, kg_min, kg_max)

[出力] analysis.sqlite への追加テーブル:
  combo_monthly   : コンボ × 月 の 平均釣果数 / 平均サイズ / 平均重量
  combo_season    : コンボ の ピーク月(数量) / ピーク月(型) / 出船月リスト
  season_calendar : 月 × 魚種 の旬強度マップ（全船宿集計）

[使い方]
  python season_analysis.py            # 全件
  python season_analysis.py --fish アジ
  python season_analysis.py --query アジ
  python season_analysis.py --calendar  # 月×魚種の一覧を表示
"""

import csv, json, math, os, sqlite3, sys
from collections import defaultdict
from datetime import datetime

BASE_DIR      = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR      = os.path.dirname(BASE_DIR)
DATA_DIR      = os.path.join(ROOT_DIR, "data")
DB_PATH       = os.path.join(BASE_DIR, "analysis.sqlite")
NORMALIZE_DIR = os.path.join(ROOT_DIR, "normalize")

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

MIN_MONTH_N = 5   # 月別最小件数（これ未満は除外）
MIN_COMBO_N = 20  # コンボ最小総件数

# ── DB テーブル初期化 ─────────────────────────────────────────────────────
def init_tables(conn):
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS combo_monthly (
        fish       TEXT,
        ship       TEXT,
        month      INTEGER,
        n          INTEGER,
        avg_cnt    REAL,
        avg_size   REAL,
        avg_kg     REAL,
        updated_at TEXT,
        PRIMARY KEY (fish, ship, month)
    );
    CREATE TABLE IF NOT EXISTS combo_season (
        fish           TEXT,
        ship           TEXT,
        n_total        INTEGER,
        avg_cnt_all    REAL,
        active_months  TEXT,      -- JSON: [1,2,3,...]
        peak_cnt_month INTEGER,   -- 数量ピーク月
        peak_cnt_val   REAL,
        peak_size_month INTEGER,  -- 型ピーク月
        peak_size_val  REAL,
        peak_kg_month  INTEGER,   -- 重量ピーク月
        peak_kg_val    REAL,
        lat            REAL,
        lon            REAL,
        updated_at     TEXT,
        PRIMARY KEY (fish, ship)
    );
    CREATE TABLE IF NOT EXISTS season_calendar (
        fish           TEXT,
        month          INTEGER,
        n_combos       INTEGER,   -- 分析対象コンボ数
        avg_cnt_index  REAL,      -- 平均釣果指数（全月平均=100）
        avg_size_index REAL,      -- 平均型指数
        peak_combos    TEXT,      -- JSON: 代表船宿リスト
        updated_at     TEXT,
        PRIMARY KEY (fish, month)
    );
    CREATE INDEX IF NOT EXISTS idx_monthly_fish  ON combo_monthly (fish);
    CREATE INDEX IF NOT EXISTS idx_season_fish   ON combo_season (fish);
    CREATE INDEX IF NOT EXISTS idx_calendar_fish ON season_calendar (fish);
    """)
    conn.commit()


# ── データロード ─────────────────────────────────────────────────────────
def load_data(fish_filter=None):
    """data/YYYY-MM.csv を全部読んで (fish, ship, month) 別に集計。"""
    records = []
    for fn in sorted(os.listdir(DATA_DIR)):
        if not fn.endswith(".csv") or fn == "cancellations.csv":
            continue
        path = os.path.join(DATA_DIR, fn)
        with open(path, encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                if row.get("is_cancellation") == "1":
                    continue
                fish_raw = row.get("fish_raw", "").strip()
                if fish_raw in RAW_TO_TSURI:
                    fish = RAW_TO_TSURI[fish_raw]
                else:
                    fish = row.get("tsuri_mono", "").strip()
                if not fish:
                    continue
                if fish_filter and fish != fish_filter:
                    continue
                if row.get("main_sub") != "メイン":
                    continue
                cnt = _float(row.get("cnt_avg"))
                if not cnt or cnt <= 0:
                    continue
                try:
                    d = datetime.strptime(row["date"], "%Y/%m/%d")
                except ValueError:
                    continue
                records.append({
                    "fish":  fish,
                    "ship":  row.get("ship", ""),
                    "month": d.month,
                    "cnt":   cnt,
                    "size":  _avg_size(row),
                    "kg":    _avg_kg(row),
                })
    return records

def _float(v):
    try:
        return float(v) if v not in ("", None) else None
    except (ValueError, TypeError):
        return None

def _avg_size(row):
    lo = _float(row.get("size_min"))
    hi = _float(row.get("size_max"))
    if lo and hi:
        return (lo + hi) / 2
    return lo or hi

def _avg_kg(row):
    lo = _float(row.get("kg_min"))
    hi = _float(row.get("kg_max"))
    if lo and hi:
        return (lo + hi) / 2
    return lo or hi


# ── 月別集計 ───────────────────────────────────────────────────────────
def aggregate(records):
    """(fish, ship, month) → {cnt, size, kg} の集計。"""
    buckets = defaultdict(lambda: {"cnt": [], "size": [], "kg": []})
    for r in records:
        key = (r["fish"], r["ship"], r["month"])
        buckets[key]["cnt"].append(r["cnt"])
        if r["size"] is not None:
            buckets[key]["size"].append(r["size"])
        if r["kg"] is not None:
            buckets[key]["kg"].append(r["kg"])

    result = {}
    for key, d in buckets.items():
        if len(d["cnt"]) < MIN_MONTH_N:
            continue
        result[key] = {
            "n":        len(d["cnt"]),
            "avg_cnt":  sum(d["cnt"]) / len(d["cnt"]),
            "avg_size": sum(d["size"]) / len(d["size"]) if d["size"] else None,
            "avg_kg":   sum(d["kg"])   / len(d["kg"])   if d["kg"]   else None,
        }
    return result


# ── コンボ旬まとめ ────────────────────────────────────────────────────────
def make_combo_season(monthly, coord_map):
    """combo_season テーブル用データを生成。"""
    # (fish, ship) → 月別データ
    combo_months = defaultdict(dict)
    for (fish, ship, month), d in monthly.items():
        combo_months[(fish, ship)][month] = d

    seasons = {}
    for (fish, ship), mdata in combo_months.items():
        total_n   = sum(d["n"] for d in mdata.values())
        if total_n < MIN_COMBO_N:
            continue
        all_cnts  = [v for d in mdata.values() for v in [d["avg_cnt"]]]
        avg_all   = sum(all_cnts) / len(all_cnts)
        active    = sorted(mdata.keys())

        # ピーク月（数量）
        peak_cnt_m   = max(mdata, key=lambda m: mdata[m]["avg_cnt"])
        peak_cnt_val = mdata[peak_cnt_m]["avg_cnt"]

        # ピーク月（型）
        size_months = {m: d["avg_size"] for m, d in mdata.items() if d["avg_size"]}
        peak_size_m   = max(size_months, key=size_months.get) if size_months else None
        peak_size_val = size_months.get(peak_size_m)

        # ピーク月（重量）
        kg_months = {m: d["avg_kg"] for m, d in mdata.items() if d["avg_kg"]}
        peak_kg_m   = max(kg_months, key=kg_months.get) if kg_months else None
        peak_kg_val = kg_months.get(peak_kg_m)

        lat, lon = coord_map.get((fish, ship), (None, None))

        seasons[(fish, ship)] = {
            "n_total":        total_n,
            "avg_cnt_all":    avg_all,
            "active_months":  str(active),
            "peak_cnt_month": peak_cnt_m,
            "peak_cnt_val":   peak_cnt_val,
            "peak_size_month":peak_size_m,
            "peak_size_val":  peak_size_val,
            "peak_kg_month":  peak_kg_m,
            "peak_kg_val":    peak_kg_val,
            "lat":            lat,
            "lon":            lon,
        }
    return seasons


# ── 旬カレンダー集計 ──────────────────────────────────────────────────────
def make_calendar(monthly, seasons):
    """season_calendar テーブル用データ（月×魚種の旬強度）。"""
    # 魚種 × 月 で全コンボの avg_cnt を平均（全月の全体平均=100換算）
    fish_month_cnts = defaultdict(lambda: defaultdict(list))
    fish_month_sizes = defaultdict(lambda: defaultdict(list))
    fish_month_combos = defaultdict(lambda: defaultdict(list))

    for (fish, ship, month), d in monthly.items():
        if (fish, ship) not in seasons:
            continue  # 件数不足コンボは除外
        fish_month_cnts[fish][month].append(d["avg_cnt"])
        if d["avg_size"]:
            fish_month_sizes[fish][month].append(d["avg_size"])
        fish_month_combos[fish][month].append(ship)

    calendar = {}
    for fish in fish_month_cnts:
        # 魚種全月の全体平均
        all_vals = [v for ms in fish_month_cnts[fish].values() for v in ms]
        grand_avg = sum(all_vals) / len(all_vals) if all_vals else 1

        for month in range(1, 13):
            cnts  = fish_month_cnts[fish].get(month, [])
            sizes = fish_month_sizes[fish].get(month, [])
            combos = fish_month_combos[fish].get(month, [])
            if not cnts:
                continue
            cnt_index  = (sum(cnts) / len(cnts)) / grand_avg * 100
            size_index = None
            if sizes:
                all_sizes = [v for ms in fish_month_sizes[fish].values() for v in ms]
                grand_size = sum(all_sizes) / len(all_sizes) if all_sizes else 1
                size_index = (sum(sizes) / len(sizes)) / grand_size * 100

            # 代表船宿（上位3）
            from collections import Counter
            top_ships = [s for s, _ in Counter(combos).most_common(3)]

            calendar[(fish, month)] = {
                "n_combos":       len(cnts),
                "avg_cnt_index":  round(cnt_index, 1),
                "avg_size_index": round(size_index, 1) if size_index else None,
                "peak_combos":    str(top_ships),
            }
    return calendar


# ── DB 書き込み ────────────────────────────────────────────────────────────
def save(conn, monthly, seasons, calendar):
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    # combo_monthly
    rows = [
        (fish, ship, month, d["n"], round(d["avg_cnt"], 2),
         round(d["avg_size"], 2) if d["avg_size"] else None,
         round(d["avg_kg"], 3) if d["avg_kg"] else None, now)
        for (fish, ship, month), d in monthly.items()
    ]
    conn.executemany("INSERT OR REPLACE INTO combo_monthly VALUES (?,?,?,?,?,?,?,?)", rows)

    # combo_season
    rows = [
        (fish, ship, d["n_total"], round(d["avg_cnt_all"], 2),
         d["active_months"], d["peak_cnt_month"], round(d["peak_cnt_val"], 2) if d["peak_cnt_val"] else None,
         d["peak_size_month"], round(d["peak_size_val"], 2) if d["peak_size_val"] else None,
         d["peak_kg_month"], round(d["peak_kg_val"], 3) if d["peak_kg_val"] else None,
         d["lat"], d["lon"], now)
        for (fish, ship), d in seasons.items()
    ]
    conn.executemany("INSERT OR REPLACE INTO combo_season VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)

    # season_calendar
    rows = [
        (fish, month, d["n_combos"], d["avg_cnt_index"], d["avg_size_index"], d["peak_combos"], now)
        for (fish, month), d in calendar.items()
    ]
    conn.executemany("INSERT OR REPLACE INTO season_calendar VALUES (?,?,?,?,?,?,?)", rows)

    conn.commit()
    print(f"保存: combo_monthly {len(monthly)}件 / combo_season {len(seasons)}件 / calendar {len(calendar)}件")


# ── クエリ表示 ────────────────────────────────────────────────────────────
MONTHS_JP = ["", "1月", "2月", "3月", "4月", "5月", "6月",
             "7月", "8月", "9月", "10月", "11月", "12月"]

def query_fish(conn, fish):
    rows = conn.execute(
        "SELECT ship, n_total, active_months, peak_cnt_month, peak_cnt_val, peak_size_month, peak_size_val FROM combo_season WHERE fish=? ORDER BY n_total DESC",
        (fish,)
    ).fetchall()
    if not rows:
        print(f"{fish}: データなし")
        return

    print(f"\n{'='*60}")
    print(f"=== {fish} の旬カレンダー（船宿別） ===")
    print(f"{'='*60}")
    print(f"{'船宿':<14} {'n':>5}  {'出船月':<20} {'数量ピーク':<10} {'型ピーク':<10}")
    print("-" * 65)
    for ship, n, active, peak_cnt_m, peak_cnt_v, peak_size_m, peak_size_v in rows:
        months_str = active.strip("[]").replace(" ", "")
        cnt_str    = f"{MONTHS_JP[peak_cnt_m]}({peak_cnt_v:.0f}匹)" if peak_cnt_m else "-"
        size_str   = f"{MONTHS_JP[peak_size_m]}({peak_size_v:.1f}cm)" if peak_size_m and peak_size_v else "-"
        print(f"  {ship:<14} {n:>5}  {months_str:<20} {cnt_str:<12} {size_str}")

    # 月別詳細
    print(f"\n--- 月別平均（全船宿集計） ---")
    cal = conn.execute(
        "SELECT month, n_combos, avg_cnt_index, avg_size_index FROM season_calendar WHERE fish=? ORDER BY month",
        (fish,)
    ).fetchall()
    for month, n_c, cnt_idx, size_idx in cal:
        bar_cnt  = "#" * int(cnt_idx / 10)
        bar_size = "#" * int((size_idx or 0) / 10)
        size_str = f"型:{size_idx:.0f}" if size_idx else ""
        print(f"  {MONTHS_JP[month]:>4}: 数量指数={cnt_idx:>6.1f} {bar_cnt:<12} {size_str}")


def show_calendar(conn):
    """全魚種 × 月 の旬カレンダーを表示。"""
    fish_list = [r[0] for r in conn.execute(
        "SELECT DISTINCT fish FROM season_calendar ORDER BY fish"
    ).fetchall()]

    print(f"\n{'='*80}")
    print(f"=== 旬カレンダー（数量指数、全月平均=100） ===")
    print(f"{'='*80}")
    header = f"{'魚種':<10}" + "".join(f"{m:>6}" for m in ["1月","2月","3月","4月","5月","6月","7月","8月","9月","10月","11月","12月"])
    print(header)
    print("-" * 82)

    for fish in fish_list:
        row_data = {r[0]: r[1] for r in conn.execute(
            "SELECT month, avg_cnt_index FROM season_calendar WHERE fish=? ORDER BY month", (fish,)
        ).fetchall()}
        peak_m = max(row_data, key=row_data.get) if row_data else None
        cells = []
        for m in range(1, 13):
            idx = row_data.get(m)
            if idx is None:
                cells.append("     -")
            elif m == peak_m:
                cells.append(f"[{idx:>4.0f}]")
            elif idx >= 120:
                cells.append(f" {idx:>4.0f}*")
            else:
                cells.append(f" {idx:>5.0f}")
        print(f"  {fish:<10}" + "".join(cells))

    print("\n  [] = 最大月  * = 指数120以上")


def show_calendar_size(conn):
    """型ピーク版。"""
    fish_list = [r[0] for r in conn.execute(
        "SELECT DISTINCT fish FROM season_calendar WHERE avg_size_index IS NOT NULL ORDER BY fish"
    ).fetchall()]

    print(f"\n{'='*80}")
    print(f"=== 型カレンダー（サイズ指数、全月平均=100） ===")
    print(f"{'='*80}")
    header = f"{'魚種':<10}" + "".join(f"{m:>6}" for m in ["1月","2月","3月","4月","5月","6月","7月","8月","9月","10月","11月","12月"])
    print(header)
    print("-" * 82)

    for fish in fish_list:
        row_data = {r[0]: r[1] for r in conn.execute(
            "SELECT month, avg_size_index FROM season_calendar WHERE fish=? AND avg_size_index IS NOT NULL ORDER BY month", (fish,)
        ).fetchall()}
        if not row_data:
            continue
        peak_m = max(row_data, key=row_data.get)
        cells = []
        for m in range(1, 13):
            idx = row_data.get(m)
            if idx is None:
                cells.append("     -")
            elif m == peak_m:
                cells.append(f"[{idx:>4.0f}]")
            elif idx >= 110:
                cells.append(f" {idx:>4.0f}*")
            else:
                cells.append(f" {idx:>5.0f}")
        print(f"  {fish:<10}" + "".join(cells))

    print("\n  [] = 最大月  * = 指数110以上")


# ── 座標マップ読み込み（combo_meta から） ─────────────────────────────────
def load_coord_map(conn):
    rows = conn.execute("SELECT fish, ship, lat, lon FROM combo_meta").fetchall()
    return {(fish, ship): (lat, lon) for fish, ship, lat, lon in rows}


# ── メイン ────────────────────────────────────────────────────────────────
def main():
    args = sys.argv[1:]
    fish_filter = None
    mode = "save"

    i = 0
    while i < len(args):
        if args[i] == "--fish" and i + 1 < len(args):
            fish_filter = args[i + 1]
            i += 2
        elif args[i] == "--query" and i + 1 < len(args):
            mode = "query"
            fish_filter = args[i + 1]
            i += 2
        elif args[i] == "--calendar":
            mode = "calendar"
            i += 1
        else:
            i += 1

    conn = sqlite3.connect(DB_PATH)
    init_tables(conn)

    if mode == "query":
        query_fish(conn, fish_filter)
        conn.close()
        return

    if mode == "calendar":
        show_calendar(conn)
        show_calendar_size(conn)
        conn.close()
        return

    # 保存モード
    print(f"=== season_analysis.py 開始 ===")
    if fish_filter:
        print(f"  魚種フィルタ: {fish_filter}")

    records = load_data(fish_filter)
    print(f"レコード数: {len(records):,}")

    monthly = aggregate(records)
    print(f"月別集計: {len(monthly)}件（fish×ship×month）")

    coord_map = load_coord_map(conn)
    seasons   = make_combo_season(monthly, coord_map)
    print(f"コンボ旬: {len(seasons)}件")

    calendar  = make_calendar(monthly, seasons)
    print(f"カレンダー: {len(calendar)}件（fish×month）")

    save(conn, monthly, seasons, calendar)
    conn.close()
    print(f"\n=== 完了 ===")
    print(f"  python season_analysis.py --calendar    # 全魚種カレンダー表示")
    print(f"  python season_analysis.py --query アジ  # 船宿別旬を表示")


if __name__ == "__main__":
    main()
