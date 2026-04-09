#!/usr/bin/env python3
"""
season_detail.py — 旬（上旬/中旬/下旬）単位の釣果カレンダー

[単位]
  旬 = 1月上旬〜12月下旬 の 36期間
  decade_no: 1=1月上旬, 2=1月中旬, 3=1月下旬, 4=2月上旬, ..., 36=12月下旬

[出力] analysis.sqlite への追加テーブル:
  combo_decadal   : コンボ × 旬 (fish, ship, decade_no)
  decadal_calendar: 魚種 × 旬 の旬強度（全船宿集計）

[使い方]
  python season_detail.py                  # 全件計算・保存
  python season_detail.py --calendar       # 旬カレンダー表示（数量）
  python season_detail.py --size           # 旬カレンダー表示（型）
  python season_detail.py --query アジ     # アジ船宿別旬詳細
  python season_detail.py --fish アジ      # アジのみ再計算
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

MIN_DECADE_N = 3    # 旬別最小件数（コンボ単位）
MIN_FLEET_N  = 10   # 旬別最小件数（全船宿集計）

# ── 旬ラベル ──────────────────────────────────────────────────────────────
DECADE_LABELS = []
for m in range(1, 13):
    for p in ["上旬", "中旬", "下旬"]:
        DECADE_LABELS.append(f"{m}月{p}")
# DECADE_LABELS[0] = "1月上旬", ..., DECADE_LABELS[35] = "12月下旬"

def decade_no(d):
    """datetime → 旬番号 (1-36)"""
    return (d.month - 1) * 3 + (0 if d.day <= 10 else 1 if d.day <= 20 else 2) + 1

def decade_label(n):
    return DECADE_LABELS[n - 1]

# ── DB 初期化 ─────────────────────────────────────────────────────────────
def init_tables(conn):
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS combo_decadal (
        fish        TEXT,
        ship        TEXT,
        decade_no   INTEGER,
        n           INTEGER,
        avg_cnt     REAL,
        avg_size    REAL,
        avg_kg      REAL,
        updated_at  TEXT,
        avg_cnt_min REAL,
        avg_cnt_max REAL,
        PRIMARY KEY (fish, ship, decade_no)
    );
    CREATE TABLE IF NOT EXISTS decadal_calendar (
        fish           TEXT,
        decade_no      INTEGER,
        n_records      INTEGER,
        avg_cnt        REAL,
        avg_cnt_index  REAL,
        avg_size       REAL,
        avg_size_index REAL,
        peak_ships     TEXT,
        updated_at     TEXT,
        PRIMARY KEY (fish, decade_no)
    );
    CREATE INDEX IF NOT EXISTS idx_decadal_fish ON combo_decadal (fish);
    CREATE INDEX IF NOT EXISTS idx_dcal_fish    ON decadal_calendar (fish);
    """)
    conn.commit()

# ── データロード ─────────────────────────────────────────────────────────
def _float(v):
    try:
        return float(v) if v not in ("", None) else None
    except (ValueError, TypeError):
        return None

def _avg_size(row):
    lo, hi = _float(row.get("size_min")), _float(row.get("size_max"))
    return (lo + hi) / 2 if lo and hi else lo or hi

def _avg_kg(row):
    lo, hi = _float(row.get("kg_min")), _float(row.get("kg_max"))
    return (lo + hi) / 2 if lo and hi else lo or hi

def load_data(fish_filter=None):
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
                records.append({
                    "fish":    fish,
                    "ship":    row.get("ship", ""),
                    "dec":     decade_no(d),
                    "cnt":     cnt,
                    "cnt_min": _float(row.get("cnt_min")),
                    "cnt_max": _float(row.get("cnt_max")),
                    "size":    _avg_size(row),
                    "kg":      _avg_kg(row),
                })
    return records

# ── 集計 ─────────────────────────────────────────────────────────────────
def aggregate_combo(records):
    """(fish, ship, decade_no) → avg_cnt/size/kg + avg_cnt_min/max"""
    buckets = defaultdict(lambda: {"cnt": [], "cnt_min": [], "cnt_max": [], "size": [], "kg": []})
    for r in records:
        key = (r["fish"], r["ship"], r["dec"])
        buckets[key]["cnt"].append(r["cnt"])
        # cnt_min/max: 単一値報告（min=avg=max）は除外し、実レンジのあるデータのみ集計
        cm = r.get("cnt_min")
        cx = r.get("cnt_max")
        if cm is not None and cx is not None and cm < r["cnt"] and cx > r["cnt"]:
            buckets[key]["cnt_min"].append(cm)
            buckets[key]["cnt_max"].append(cx)
        if r["size"] is not None: buckets[key]["size"].append(r["size"])
        if r["kg"]   is not None: buckets[key]["kg"].append(r["kg"])
    result = {}
    for key, d in buckets.items():
        if len(d["cnt"]) < MIN_DECADE_N:
            continue
        result[key] = {
            "n":          len(d["cnt"]),
            "avg_cnt":    sum(d["cnt"]) / len(d["cnt"]),
            "avg_cnt_min": sum(d["cnt_min"]) / len(d["cnt_min"]) if len(d["cnt_min"]) >= 3 else None,
            "avg_cnt_max": sum(d["cnt_max"]) / len(d["cnt_max"]) if len(d["cnt_max"]) >= 3 else None,
            "avg_size":   sum(d["size"]) / len(d["size"]) if d["size"] else None,
            "avg_kg":     sum(d["kg"])   / len(d["kg"])   if d["kg"]   else None,
        }
    return result

def aggregate_fleet(records):
    """(fish, decade_no) → 全船宿集計"""
    buckets = defaultdict(lambda: {"cnt": [], "size": [], "ships": []})
    for r in records:
        key = (r["fish"], r["dec"])
        buckets[key]["cnt"].append(r["cnt"])
        if r["size"] is not None: buckets[key]["size"].append(r["size"])
        buckets[key]["ships"].append(r["ship"])
    result = {}
    for key, d in buckets.items():
        if len(d["cnt"]) < MIN_FLEET_N:
            continue
        from collections import Counter
        top_ships = [s for s, _ in Counter(d["ships"]).most_common(3)]
        result[key] = {
            "n":         len(d["cnt"]),
            "avg_cnt":   sum(d["cnt"]) / len(d["cnt"]),
            "avg_size":  sum(d["size"]) / len(d["size"]) if d["size"] else None,
            "peak_ships": str(top_ships),
        }
    return result

def make_indices(fleet):
    """全旬の全体平均を100として指数化。"""
    # 魚種ごとに全旬の平均を計算
    fish_all_cnt  = defaultdict(list)
    fish_all_size = defaultdict(list)
    for (fish, dec), d in fleet.items():
        fish_all_cnt[fish].append(d["avg_cnt"])
        if d["avg_size"]: fish_all_size[fish].append(d["avg_size"])

    result = {}
    for (fish, dec), d in fleet.items():
        grand_cnt  = sum(fish_all_cnt[fish]) / len(fish_all_cnt[fish])
        grand_size = sum(fish_all_size[fish]) / len(fish_all_size[fish]) if fish_all_size[fish] else None
        cnt_idx  = round(d["avg_cnt"] / grand_cnt * 100, 1) if grand_cnt else None
        size_idx = round(d["avg_size"] / grand_size * 100, 1) if (d["avg_size"] and grand_size) else None
        result[(fish, dec)] = {**d, "cnt_index": cnt_idx, "size_index": size_idx}
    return result

# ── DB 保存 ───────────────────────────────────────────────────────────────
def save(conn, combo_data, fleet_data):
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    # マイグレーション: 既存テーブルに avg_cnt_min/max 列がなければ追加
    for col in ("avg_cnt_min", "avg_cnt_max"):
        try:
            conn.execute(f"ALTER TABLE combo_decadal ADD COLUMN {col} REAL")
        except Exception:
            pass

    rows = [(fish, ship, dec, d["n"], round(d["avg_cnt"], 2),
             round(d["avg_size"], 2) if d["avg_size"] else None,
             round(d["avg_kg"], 3) if d["avg_kg"] else None, now,
             round(d["avg_cnt_min"], 2) if d["avg_cnt_min"] else None,
             round(d["avg_cnt_max"], 2) if d["avg_cnt_max"] else None)
            for (fish, ship, dec), d in combo_data.items()]
    conn.executemany(
        "INSERT OR REPLACE INTO combo_decadal "
        "(fish, ship, decade_no, n, avg_cnt, avg_size, avg_kg, updated_at, avg_cnt_min, avg_cnt_max) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)", rows)

    rows = [(fish, dec, d["n"], round(d["avg_cnt"], 2), d["cnt_index"],
             round(d["avg_size"], 2) if d["avg_size"] else None,
             d["size_index"], d["peak_ships"], now)
            for (fish, dec), d in fleet_data.items()]
    conn.executemany("INSERT OR REPLACE INTO decadal_calendar VALUES (?,?,?,?,?,?,?,?,?)", rows)

    conn.commit()
    print(f"保存: combo_decadal {len(combo_data)}件 / decadal_calendar {len(fleet_data)}件")

# ── 表示 ─────────────────────────────────────────────────────────────────
def _bar(idx, scale=200):
    """指数をバーグラフに変換。"""
    n = max(0, int(idx / scale * 20))
    return "#" * n

def show_fleet_calendar(conn, mode="cnt"):
    """全魚種 × 旬 のカレンダー表示。"""
    field = "avg_cnt_index" if mode == "cnt" else "avg_size_index"
    title = "数量指数" if mode == "cnt" else "型指数"

    fish_list = [r[0] for r in conn.execute(
        f"SELECT DISTINCT fish FROM decadal_calendar WHERE {field} IS NOT NULL ORDER BY fish"
    ).fetchall()]

    print(f"\n{'='*80}")
    print(f"=== 旬カレンダー（{title}、全旬平均=100） ===")
    print(f"{'='*80}")

    # ヘッダ行（月だけ表示、上中下旬は記号で）
    header = f"{'魚種':<10}"
    for m in range(1, 13):
        header += f"  {m}月"
        header += " " * 8  # 上中下旬3列分のスペース
    print(header[:82])

    sub_header = " " * 12
    for m in range(1, 13):
        sub_header += "上  中  下  "
    print(sub_header[:82])
    print("-" * 82)

    for fish in fish_list:
        row_data = {r[0]: r[1] for r in conn.execute(
            f"SELECT decade_no, {field} FROM decadal_calendar WHERE fish=? AND {field} IS NOT NULL ORDER BY decade_no",
            (fish,)
        ).fetchall()}
        if not row_data:
            continue
        peak_dec = max(row_data, key=row_data.get)
        cells = []
        for dec in range(1, 37):
            idx = row_data.get(dec)
            if idx is None:
                cells.append("  - ")
            elif dec == peak_dec:
                cells.append(f"[{idx:>3.0f}]"[:4])
            elif idx >= 130:
                cells.append(f"{idx:>3.0f}*")
            else:
                cells.append(f"{idx:>4.0f}")
        # 月ごとに3つまとめて表示
        line = f"  {fish:<10}"
        for i in range(0, 36, 3):
            line += " " + cells[i] + cells[i+1] + cells[i+2]
        print(line[:90])

    peak_sym = "[最大月旬]" if mode == "cnt" else "[最大月旬]"
    print(f"\n  [xxx] = 最大旬  xxx* = 指数130以上")


def show_combo_query(conn, fish):
    """船宿別の旬詳細（数量・型）。"""
    combos = conn.execute(
        "SELECT ship FROM combo_season WHERE fish=? ORDER BY n_total DESC LIMIT 15",
        (fish,)
    ).fetchall()
    if not combos:
        # combo_seasonにない場合はcombo_decadalから
        combos = conn.execute(
            "SELECT DISTINCT ship FROM combo_decadal WHERE fish=? ORDER BY ship",
            (fish,)
        ).fetchall()

    print(f"\n{'='*70}")
    print(f"=== {fish} 旬別釣果（船宿別） ===")
    print(f"{'='*70}")

    # ヘッダ
    PERIODS = ["1上","1中","1下","2上","2中","2下","3上","3中","3下",
               "4上","4中","4下","5上","5中","5下","6上","6中","6下",
               "7上","7中","7下","8上","8中","8下","9上","9中","9下",
               "10上","10中","10下","11上","11中","11下","12上","12中","12下"]

    print(f"\n--- 数量（平均匹数）---")
    _print_combo_grid(conn, fish, [s[0] for s in combos], PERIODS, "avg_cnt")

    print(f"\n--- 型（平均サイズcm）---")
    _print_combo_grid(conn, fish, [s[0] for s in combos], PERIODS, "avg_size")


def _print_combo_grid(conn, fish, ships, periods, field):
    """旬 × 船宿 のグリッド表示。"""
    # データ取得
    data = {}
    for ship in ships:
        rows = conn.execute(
            f"SELECT decade_no, {field} FROM combo_decadal WHERE fish=? AND ship=? AND {field} IS NOT NULL ORDER BY decade_no",
            (fish, ship)
        ).fetchall()
        if rows:
            data[ship] = {r[0]: r[1] for r in rows}

    if not data:
        print("  データなし")
        return

    # 全旬の全体最大値（正規化用）
    all_vals = [v for d in data.values() for v in d.values()]
    if not all_vals:
        return
    grand_max = max(all_vals)
    grand_avg = sum(all_vals) / len(all_vals)

    # ヘッダ
    header = f"  {'船宿':<14}"
    for i, p in enumerate(periods):
        if i % 3 == 0:  # 月の境界で区切り
            header += "|"
        header += f"{p:>4}"
    print(header)
    print("  " + "-" * 14 + ("|" + "-" * 12) * 12)

    for ship in ships:
        if ship not in data:
            continue
        d = data[ship]
        # ピーク旬を特定
        if d:
            peak_dec = max(d, key=d.get)
        else:
            peak_dec = None

        line = f"  {ship:<14}"
        for i, dec in enumerate(range(1, 37), 1):
            if (dec - 1) % 3 == 0:
                line += "|"
            val = d.get(dec)
            if val is None:
                line += "   -"
            elif dec == peak_dec:
                # ピーク旬は強調
                if field == "avg_cnt":
                    line += f"[{val:>2.0f}]"[:4]
                else:
                    line += f"[{val:>3.1f}]"[:5]
            else:
                if field == "avg_cnt":
                    line += f"{val:>4.0f}"
                else:
                    line += f"{val:>4.1f}"
        print(line)

    # 全船宿集計行
    if field == "avg_cnt":
        fleet_data = conn.execute(
            "SELECT decade_no, avg_cnt FROM decadal_calendar WHERE fish=? ORDER BY decade_no",
            (fish,)
        ).fetchall()
    else:
        fleet_data = conn.execute(
            "SELECT decade_no, avg_size FROM decadal_calendar WHERE fish=? AND avg_size IS NOT NULL ORDER BY decade_no",
            (fish,)
        ).fetchall()

    fleet_map = {}
    for row in fleet_data:
        fleet_map[row[0]] = row[1]

    if fleet_map:
        peak_dec = max(fleet_map, key=fleet_map.get)
        line = f"  {'【全船宿平均】':<14}"
        for dec in range(1, 37):
            if (dec - 1) % 3 == 0:
                line += "|"
            val = fleet_map.get(dec)
            if val is None:
                line += "   -"
            elif dec == peak_dec:
                if field == "avg_cnt":
                    line += f"[{val:>2.0f}]"[:4]
                else:
                    line += f"[{val:>3.1f}]"[:5]
            else:
                if field == "avg_cnt":
                    line += f"{val:>4.0f}"
                else:
                    line += f"{val:>4.1f}"
        print(line)


# ── メイン ────────────────────────────────────────────────────────────────
def main():
    args = sys.argv[1:]
    mode = "save"
    fish_filter = None
    size_mode = False

    i = 0
    while i < len(args):
        if args[i] == "--fish" and i + 1 < len(args):
            fish_filter = args[i + 1]; i += 2
        elif args[i] == "--query" and i + 1 < len(args):
            mode = "query"; fish_filter = args[i + 1]; i += 2
        elif args[i] == "--calendar":
            mode = "calendar"; i += 1
        elif args[i] == "--size":
            mode = "calendar"; size_mode = True; i += 1
        else:
            i += 1

    conn = sqlite3.connect(DB_PATH)
    init_tables(conn)

    if mode == "query":
        show_combo_query(conn, fish_filter)
        conn.close()
        return

    if mode == "calendar":
        show_fleet_calendar(conn, "size" if size_mode else "cnt")
        conn.close()
        return

    # 保存モード
    print(f"=== season_detail.py 開始 ===")
    if fish_filter:
        print(f"  魚種フィルタ: {fish_filter}")

    records = load_data(fish_filter)
    print(f"レコード: {len(records):,}件")

    combo_data = aggregate_combo(records)
    fleet_raw  = aggregate_fleet(records)
    fleet_data = make_indices(fleet_raw)
    print(f"コンボ旬: {len(combo_data)}件 / 全船宿旬: {len(fleet_data)}件")

    save(conn, combo_data, fleet_data)
    conn.close()

    print(f"\n=== 完了 ===")
    print(f"  python season_detail.py --calendar        # 旬カレンダー（数量）")
    print(f"  python season_detail.py --size            # 旬カレンダー（型）")
    print(f"  python season_detail.py --query アジ      # 船宿別旬詳細")


if __name__ == "__main__":
    main()
