#!/usr/bin/env python3
"""
build_wx_params.py — コンボ別 海況スコアパラメータ構築

analysis_summary.csv の r値 + enriched_catches.csv の歴史平均/std を
combo_wx_params テーブルに保存する。

crawler.py がこのテーブルを読んで「今週の海況は有利か不利か」を判定する。

使い方:
  python insights/build_wx_params.py
"""
import csv, math, os, sqlite3
from collections import defaultdict

BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
DB_PATH    = os.path.join(BASE_DIR, "analysis.sqlite")
SUMMARY    = os.path.join(BASE_DIR, "analysis_summary.csv")
ENRICHED   = os.path.join(BASE_DIR, "enriched_catches.csv")

# 堅牢率50%以上の因子のみ使う（granularity_summary.txtより）
ROBUST_FACTORS = ["sst", "temp", "wave_height", "wind_speed", "pressure", "current_spd"]
MIN_R = 0.15   # この絶対値未満は無視

def mean_std(vals):
    n = len(vals)
    if n < 10:
        return None, None
    m = sum(vals) / n
    s = math.sqrt(sum((v - m)**2 for v in vals) / (n - 1))
    return m, s if s > 0 else None

def main():
    # ── 1. r値ロード ─────────────────────────────────────────────────────
    r_map = {}  # (fish, ship, factor) -> r
    with open(SUMMARY, encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            fish, ship = row["fish"], row["ship"]
            for fac in ROBUST_FACTORS:
                v = row.get(fac, "")
                if not v:
                    continue
                r = float(v)
                if abs(r) >= MIN_R:
                    r_map[(fish, ship, fac)] = r
    print(f"r値（|r|>={MIN_R}）: {len(r_map)}件")

    # ── 2. 歴史平均/std ──────────────────────────────────────────────────
    buckets = defaultdict(lambda: defaultdict(list))
    with open(ENRICHED, encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            if row.get("main_sub") != "メイン":
                continue
            fish = row.get("tsuri_mono", "").strip()
            ship = row.get("ship", "").strip()
            if not fish or not ship:
                continue
            for fac in ROBUST_FACTORS:
                v = row.get(fac, "")
                try:
                    buckets[(fish, ship)][fac].append(float(v))
                except (ValueError, TypeError):
                    pass

    # ── 3. DB保存 ────────────────────────────────────────────────────────
    conn = sqlite3.connect(DB_PATH)
    conn.execute("DROP TABLE IF EXISTS combo_wx_params")
    conn.execute("""
        CREATE TABLE combo_wx_params (
            fish      TEXT,
            ship      TEXT,
            factor    TEXT,
            r         REAL,
            hist_mean REAL,
            hist_std  REAL,
            PRIMARY KEY (fish, ship, factor)
        )
    """)

    rows = []
    for (fish, ship, fac), r in r_map.items():
        vals = buckets[(fish, ship)].get(fac, [])
        m, s = mean_std(vals)
        if m is None or s is None:
            continue
        rows.append((fish, ship, fac, round(r, 4), round(m, 4), round(s, 4)))

    conn.executemany("INSERT INTO combo_wx_params VALUES (?,?,?,?,?,?)", rows)

    # ── 4. 魚種単位に集約（crawler.py用） ────────────────────────────────
    # コンボnで重み付き平均r、全レコードの歴史平均/stdを計算
    n_map = {(row["fish"], row["ship"]): int(row["n"])
             for row in csv.DictReader(open(SUMMARY, encoding="utf-8"))}

    fish_r_sum   = defaultdict(lambda: defaultdict(float))
    fish_r_w     = defaultdict(lambda: defaultdict(float))
    fish_vals    = defaultdict(lambda: defaultdict(list))

    for (fish, ship, fac), r in r_map.items():
        n = n_map.get((fish, ship), 1)
        fish_r_sum[fish][fac] += r * n
        fish_r_w[fish][fac]   += n
        fish_vals[fish][fac].extend(buckets[(fish, ship)].get(fac, []))

    conn.execute("DROP TABLE IF EXISTS fish_wx_params")
    conn.execute("""
        CREATE TABLE fish_wx_params (
            fish      TEXT,
            factor    TEXT,
            r         REAL,
            hist_mean REAL,
            hist_std  REAL,
            PRIMARY KEY (fish, factor)
        )
    """)
    fish_rows = []
    for fish, fac_r in fish_r_sum.items():
        for fac, rsum in fac_r.items():
            w = fish_r_w[fish][fac]
            if w == 0:
                continue
            r_avg = rsum / w
            m, s = mean_std(fish_vals[fish][fac])
            if m is None or s is None:
                continue
            fish_rows.append((fish, fac, round(r_avg, 4), round(m, 4), round(s, 4)))

    conn.executemany("INSERT INTO fish_wx_params VALUES (?,?,?,?,?)", fish_rows)
    conn.commit()
    conn.close()

    combos = len({(r[0], r[1]) for r in rows})
    print(f"保存: {len(rows)}件 / {combos}コンボ → combo_wx_params")
    print(f"保存: {len(fish_rows)}件 → fish_wx_params")

if __name__ == "__main__":
    main()
