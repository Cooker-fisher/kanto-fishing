#!/usr/bin/env python3
"""
weekly_analysis.py — 船宿 × 釣り物 × 週（ISO week）の旬より細かい季節分析

[出力] analysis.sqlite:
  combo_weekly      : (fish, ship, week_no) ごとの週別集計＋index
  ship_weekly_peaks : (fish, ship) ごとの週ピーク・TOP3

[ファイル出力]
  weekly_grid_{魚種}.txt  : 船宿×週グリッド
  weekly_peaks_{魚種}.txt : 船宿別ピーク週一覧

[使い方]
  python insights/weekly_analysis.py                  # 全件計算・保存
  python insights/weekly_analysis.py --query アジ     # アジ一覧
  python insights/weekly_analysis.py --grid  アジ     # 船宿×週グリッド表示＋ファイル保存
"""

import csv, json, os, sqlite3, sys
from collections import defaultdict
from datetime import datetime, date

BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR   = os.path.dirname(BASE_DIR)
DATA_DIR   = os.path.join(ROOT_DIR, "data")
DB_PATH    = os.path.join(BASE_DIR, "analysis.sqlite")
WEEKLY_DIR = os.path.join(BASE_DIR, "weekly")

def _load_exclude_ships():
    """ships.json から exclude:true / boat_only:true の船宿名セットを返す"""
    path = os.path.join(ROOT_DIR, "crawl", "ships.json")
    try:
        with open(path, encoding="utf-8") as f:
            ships = json.load(f)
        return {s["name"] for s in ships if s.get("exclude") or s.get("boat_only")}
    except Exception:
        return set()

EXCLUDE_SHIPS = _load_exclude_ships()

def _build_raw_to_tsuri_map():
    """tsuri_mono_map_draft.json から fish_raw → tsuri_mono の逆引き辞書を生成。"""
    path = os.path.join(ROOT_DIR, "tsuri_mono_map_draft.json")
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

# 週ラベル（W01〜W53）
def week_label(w):
    return f"W{w:02d}"

# 月の目安（週→月概算）
WEEK_MONTH = {w: min(12, (w - 1) // 4 + 1) for w in range(1, 54)}


def init_tables(conn):
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS combo_weekly (
        fish       TEXT,
        ship       TEXT,
        week_no    INTEGER,
        n          INTEGER,
        avg_cnt    REAL,
        avg_size   REAL,
        cnt_index  REAL,
        size_index REAL,
        updated_at TEXT,
        PRIMARY KEY (fish, ship, week_no)
    );
    CREATE TABLE IF NOT EXISTS ship_weekly_peaks (
        fish              TEXT,
        ship              TEXT,
        area              TEXT,
        peak_cnt_week     INTEGER,
        max_cnt           REAL,
        cnt_index_peak    REAL,
        peak_size_week    INTEGER,
        max_size          REAL,
        top3_cnt_weeks    TEXT,
        total_n           INTEGER,
        updated_at        TEXT,
        PRIMARY KEY (fish, ship)
    );
    CREATE INDEX IF NOT EXISTS idx_combo_weekly_fish ON combo_weekly (fish);
    CREATE INDEX IF NOT EXISTS idx_ship_weekly_fish  ON ship_weekly_peaks (fish);
    """)
    conn.commit()


def _float(v):
    try:
        return float(v) if v not in ("", None) else None
    except (ValueError, TypeError):
        return None

def _avg_size(row):
    lo, hi = _float(row.get("size_min")), _float(row.get("size_max"))
    return (lo + hi) / 2 if lo and hi else lo or hi


def load_records(fish_filter=None):
    records = []
    for fn in sorted(os.listdir(DATA_DIR)):
        if not fn.endswith(".csv") or fn == "cancellations.csv":
            continue
        with open(os.path.join(DATA_DIR, fn), encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                if row.get("is_cancellation") == "1":
                    continue
                if row.get("main_sub") != "メイン":
                    continue
                # fish_raw を正として tsuri_mono を再解決（旧マップの誤分類を修正）
                fish_raw = row.get("fish_raw", "").strip()
                if fish_raw in RAW_TO_TSURI:
                    fish = RAW_TO_TSURI[fish_raw]
                else:
                    fish = row.get("tsuri_mono", "").strip()
                if not fish:
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
                week_no = d.isocalendar()[1]  # ISO週番号 1-53
                ship = row.get("ship", "")
                if ship in EXCLUDE_SHIPS:
                    continue
                records.append({
                    "fish":    fish,
                    "ship":    ship,
                    "week_no": week_no,
                    "cnt":     cnt,
                    "size":    _avg_size(row),
                })
    return records


def aggregate(records, min_n=1):
    buckets = defaultdict(lambda: {"cnt": [], "size": []})
    for r in records:
        key = (r["fish"], r["ship"], r["week_no"])
        buckets[key]["cnt"].append(r["cnt"])
        if r["size"] is not None:
            buckets[key]["size"].append(r["size"])
    result = {}
    for key, d in buckets.items():
        if len(d["cnt"]) < min_n:
            continue
        result[key] = {
            "n":        len(d["cnt"]),
            "avg_cnt":  sum(d["cnt"]) / len(d["cnt"]),
            "avg_size": sum(d["size"]) / len(d["size"]) if d["size"] else None,
        }
    return result


def add_indices(data):
    # (fish, ship) ごとの全週平均を100として指数化
    combo_cnts  = defaultdict(list)
    combo_sizes = defaultdict(list)
    for (fish, ship, week), d in data.items():
        combo_cnts[(fish, ship)].append(d["avg_cnt"])
        if d["avg_size"]:
            combo_sizes[(fish, ship)].append(d["avg_size"])

    result = {}
    for (fish, ship, week), d in data.items():
        gc = sum(combo_cnts[(fish, ship)]) / len(combo_cnts[(fish, ship)])
        gs_list = combo_sizes[(fish, ship)]
        gs = sum(gs_list) / len(gs_list) if gs_list else None
        result[(fish, ship, week)] = {
            **d,
            "cnt_index":  round(d["avg_cnt"] / gc * 100, 1) if gc else None,
            "size_index": round(d["avg_size"] / gs * 100, 1) if (d["avg_size"] and gs) else None,
        }
    return result


def save_combo_weekly(conn, data):
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    rows = [
        (fish, ship, week, d["n"],
         round(d["avg_cnt"], 2),
         round(d["avg_size"], 2) if d["avg_size"] else None,
         d["cnt_index"], d["size_index"], now)
        for (fish, ship, week), d in data.items()
    ]
    conn.executemany(
        "INSERT OR REPLACE INTO combo_weekly VALUES (?,?,?,?,?,?,?,?,?)", rows
    )
    conn.commit()
    print(f"保存: combo_weekly {len(rows)}件")


def save_ship_weekly_peaks(conn):
    # エリアは ship_peaks から引用
    area_map = {(fish, ship): area for fish, ship, area in conn.execute(
        "SELECT fish, ship, area FROM ship_peaks"
    ).fetchall()}

    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    combos = conn.execute(
        "SELECT DISTINCT fish, ship FROM combo_weekly ORDER BY fish, ship"
    ).fetchall()

    rows = []
    for fish, ship in combos:
        cnt_rows = conn.execute(
            "SELECT week_no, avg_cnt, cnt_index FROM combo_weekly "
            "WHERE fish=? AND ship=? AND avg_cnt IS NOT NULL ORDER BY avg_cnt DESC",
            (fish, ship)
        ).fetchall()
        size_row = conn.execute(
            "SELECT week_no, avg_size FROM combo_weekly "
            "WHERE fish=? AND ship=? AND avg_size IS NOT NULL ORDER BY avg_size DESC LIMIT 1",
            (fish, ship)
        ).fetchone()
        total_n = conn.execute(
            "SELECT SUM(n) FROM combo_weekly WHERE fish=? AND ship=?", (fish, ship)
        ).fetchone()[0]

        if not cnt_rows:
            continue
        peak_week, max_cnt, cnt_idx = cnt_rows[0]
        top3 = ",".join(str(r[0]) for r in cnt_rows[:3])
        area = area_map.get((fish, ship))

        rows.append((
            fish, ship, area,
            peak_week, round(max_cnt, 2), cnt_idx,
            size_row[0] if size_row else None,
            round(size_row[1], 2) if size_row else None,
            top3, total_n, now,
        ))

    conn.executemany(
        "INSERT OR REPLACE INTO ship_weekly_peaks VALUES (?,?,?,?,?,?,?,?,?,?,?)", rows
    )
    conn.commit()
    print(f"保存: ship_weekly_peaks {len(rows)}件")


# ── ファイル出力 ──────────────────────────────────────────────────────────────

def save_query_file(conn, fish):
    """船宿別ピーク週一覧をファイルに保存。"""
    rows = conn.execute(
        "SELECT ship, area, peak_cnt_week, max_cnt, cnt_index_peak, "
        "peak_size_week, max_size, top3_cnt_weeks, total_n "
        "FROM ship_weekly_peaks WHERE fish=? ORDER BY max_cnt DESC",
        (fish,)
    ).fetchall()
    if not rows:
        return

    os.makedirs(WEEKLY_DIR, exist_ok=True)
    path = os.path.join(WEEKLY_DIR, f"weekly_peaks_{fish}.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"=== {fish} 船宿別ピーク週（週単位旬より細かい） ===\n")
        f.write("-" * 105 + "\n")
        f.write(f"{'船宿':<16} {'エリア':<18} {'数量ピーク週':<12} {'最大(匹)':<9} {'index':<7} {'型ピーク週':<12} {'最大(cm)':<9} {'件数'}\n")
        f.write("-" * 105 + "\n")
        for ship, area, pw, mc, ci, psw, ms, top3, n in rows:
            pw_s  = week_label(pw)  if pw  else "-"
            psw_s = week_label(psw) if psw else "-"
            top3_labels = " / ".join(week_label(int(x)) for x in top3.split(",") if x.strip().isdigit())
            f.write(f"{ship:<16} {(area or '-'):<18} {pw_s:<12} {round(mc):<9} {round(ci):<7} {psw_s:<12} {round(ms,1) if ms else '-':<9} {n}\n")
            f.write(f"  TOP3: {top3_labels}\n")
    print(f"保存: {path}")
    return path


def save_grid_file(conn, fish):
    """船宿×週グリッド（index）をファイルに保存。"""
    ships = [r[0] for r in conn.execute(
        "SELECT DISTINCT ship FROM combo_weekly WHERE fish=? ORDER BY ship", (fish,)
    ).fetchall()]
    if not ships:
        return

    os.makedirs(WEEKLY_DIR, exist_ok=True)
    path = os.path.join(WEEKLY_DIR, f"weekly_grid_{fish}.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"=== {fish} 船宿×週グリッド（数量index、全期間平均=100） ===\n")
        # ヘッダ：月ごとにまとめ
        hdr = f"{'船宿':<16}"
        for m in range(1, 13):
            hdr += f"|--{m:2d}月({4}週)--"
        f.write(hdr + "\n")
        hdr2 = " " * 16
        for m in range(1, 13):
            ws = [w for w in range(1, 54) if WEEK_MONTH[w] == m][:4]
            for w in ws:
                hdr2 += f"W{w:02d} "
            # pad if needed
            if len(ws) < 4:
                hdr2 += "    " * (4 - len(ws))
        f.write(hdr2 + "\n")
        f.write("-" * 16 + ("-" * 16) * 12 + "\n")

        for ship in ships:
            d = {r[0]: r[1] for r in conn.execute(
                "SELECT week_no, cnt_index FROM combo_weekly WHERE fish=? AND ship=? ORDER BY week_no",
                (fish, ship)
            ).fetchall()}
            if not d:
                continue
            peak = max(d, key=lambda k: d[k] if d[k] else 0)
            line = f"{ship:<16}"
            for w in range(1, 54):
                if (w - 1) % 4 == 0 and w <= 49:
                    line += "|"
                val = d.get(w)
                if val is None:
                    line += "  - "
                elif w == peak:
                    line += f"[{int(val):3d}]"[:4]
                elif val >= 130:
                    line += f"{int(val):3d}*"
                else:
                    line += f"{int(val):4d}"
            f.write(line + "\n")
    print(f"保存: {path}")
    return path


# ── 表示 ────────────────────────────────────────────────────────────────────

def print_query(conn, fish):
    rows = conn.execute(
        "SELECT ship, area, peak_cnt_week, max_cnt, cnt_index_peak, "
        "peak_size_week, max_size, top3_cnt_weeks, total_n "
        "FROM ship_weekly_peaks WHERE fish=? ORDER BY max_cnt DESC",
        (fish,)
    ).fetchall()
    if not rows:
        print(f"{fish} のデータなし")
        return
    print(f"\n=== {fish} 船宿別ピーク週 ===")
    print(f"{'船宿':<14} {'エリア':<14} {'数量ピーク週':<10} {'最大(匹)':<9} {'index':<6} {'型ピーク週':<10} {'最大(cm)':<9} {'件数'}")
    print("-" * 80)
    for ship, area, pw, mc, ci, psw, ms, top3, n in rows:
        pw_s  = week_label(pw)  if pw  else "-"
        psw_s = week_label(psw) if psw else "-"
        top3_s = "/".join(week_label(int(x)) for x in top3.split(",") if x.strip().isdigit())
        print(f"{ship:<14} {(area or '-'):<14} {pw_s:<10} {round(mc):<9} {round(ci):<6} {psw_s:<10} {round(ms,1) if ms else '-':<9} {n}")
        print(f"  TOP3: {top3_s}")


# ── メイン ──────────────────────────────────────────────────────────────────

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
        else:
            i += 1

    conn = sqlite3.connect(DB_PATH)
    init_tables(conn)

    if mode == "query":
        print_query(conn, fish_arg)
        save_query_file(conn, fish_arg)
        conn.close()
        return
    if mode == "grid":
        save_grid_file(conn, fish_arg)
        conn.close()
        return

    print("=== weekly_analysis.py 開始 ===")
    records = load_records()
    print(f"レコード: {len(records):,}件")

    data = aggregate(records)
    data = add_indices(data)
    print(f"集計: {len(data)}件（fish × ship × week_no）")

    save_combo_weekly(conn, data)
    save_ship_weekly_peaks(conn)
    conn.close()

    print("\n=== 完了 ===")
    print("  python insights/weekly_analysis.py --query アジ   # 一覧＋ファイル保存")
    print("  python insights/weekly_analysis.py --grid  アジ   # グリッドファイル保存")


if __name__ == "__main__":
    main()
