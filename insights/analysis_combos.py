#!/usr/bin/env python3
"""
analysis_combos.py — 釣り物 × 船宿コンボ × 海況 多次元因果分析

[入力]
  enriched_catches.csv

[出力]
  analysis_report.txt       コンボ別 全因果レポート
  analysis_summary.csv      コンボ × 因子 相関係数一覧
  fish_cooccurrence.csv     魚種間共起行列（週次）

[コンボ定義]
  (tsuri_mono, ship) でグループ化
  n < 30 は除外

[分析軸]
  1. 単変量相関（全海況因子 vs cnt_avg）
  2. 出船数 × 海況（サバイバルバイアス確認）
  3. 海況変化トレンド（Δsst, Δwave）
  4. 複合効果（荒天複合, 大潮+水温上昇等）
  5. 魚種間共起

[使い方]
  python analysis_combos.py
  python analysis_combos.py --fish アジ   # 特定魚種のみ
"""

import csv, math, os, re, sys
from collections import defaultdict
from datetime import datetime, timedelta

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INPUT_CSV = os.path.join(BASE_DIR, "enriched_catches.csv")
REPORT_TXT = os.path.join(BASE_DIR, "analysis_report.txt")
SUMMARY_CSV = os.path.join(BASE_DIR, "analysis_summary.csv")
COOCCUR_CSV = os.path.join(BASE_DIR, "fish_cooccurrence.csv")

MIN_COMBO_N = 30  # コンボ最小件数

# ── 統計ユーティリティ ────────────────────────────────────────────────────
def mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None

def stdev(xs):
    xs = [x for x in xs if x is not None]
    if len(xs) < 2:
        return None
    m = sum(xs) / len(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))

def pearson(xs, ys):
    """Pearson相関係数 + t検定p値（近似）を返す。(r, p, n)"""
    pairs = [(x, y) for x, y in zip(xs, ys) if x is not None and y is not None]
    n = len(pairs)
    if n < 5:
        return None, None, n
    sx = [p[0] for p in pairs]
    sy = [p[1] for p in pairs]
    mx, my = sum(sx) / n, sum(sy) / n
    num = sum((x - mx) * (y - my) for x, y in pairs)
    dx = math.sqrt(sum((x - mx) ** 2 for x in sx))
    dy = math.sqrt(sum((y - my) ** 2 for y in sy))
    if dx == 0 or dy == 0:
        return None, None, n
    r = num / (dx * dy)
    r = max(-1.0, min(1.0, r))
    # t近似p値（両側）
    if abs(r) == 1.0:
        p = 0.0
    else:
        t = r * math.sqrt(n - 2) / math.sqrt(1 - r ** 2)
        # 正規近似（n>30では十分）
        z = abs(t)
        p = 2 * (1 - _norm_cdf(z))
    return r, p, n

def _norm_cdf(z):
    """標準正規分布CDF（Abramowitz & Stegun近似）"""
    a1, a2, a3, a4, a5 = 0.319381530, -0.356563782, 1.781477937, -1.821255978, 1.330274429
    p_const = 0.2316419
    k = 1 / (1 + p_const * z)
    poly = k * (a1 + k * (a2 + k * (a3 + k * (a4 + k * a5))))
    return 1 - (1 / math.sqrt(2 * math.pi)) * math.exp(-z ** 2 / 2) * poly

def p_star(p):
    if p is None:
        return "   "
    if p < 0.001:
        return "***"
    if p < 0.01:
        return "** "
    if p < 0.05:
        return "*  "
    return "   "

def to_float(v):
    try:
        return float(v) if v not in ("", None) else None
    except (ValueError, TypeError):
        return None

def parse_time(t):
    """'HH:MM' → 時刻の数値（例: 6.5 = 06:30）"""
    if not t:
        return None
    try:
        h, m = t.split(":")
        return int(h) + int(m) / 60
    except Exception:
        return None

TIDE_TYPE_MAP = {"大潮": 4, "中潮": 3, "小潮": 2, "長潮": 1, "若潮": 1}

def tide_type_num(t):
    return TIDE_TYPE_MAP.get(t, None)

# ── フィーチャー定義 ──────────────────────────────────────────────────────
FEATURES = [
    ("wind_speed",    "風速(m/s)",           lambda r: to_float(r["wind_speed"])),
    ("wind_dir",      "風向(度)",             lambda r: to_float(r["wind_dir"])),
    ("temp",          "気温(℃)",             lambda r: to_float(r["temp"])),
    ("pressure",      "気圧(hPa)",           lambda r: to_float(r["pressure"])),
    ("weather_code",  "天気コード",           lambda r: to_float(r["weather_code"])),
    ("wave_height",   "波高(m)",             lambda r: to_float(r["wave_height"])),
    ("wave_period",   "波周期(s)",           lambda r: to_float(r["wave_period"])),
    ("wave_dir",      "波向(度)",            lambda r: to_float(r["wave_dir"])),
    ("swell_height",  "うねり高(m)",         lambda r: to_float(r["swell_height"])),
    ("swell_period",  "うねり周期(s)",       lambda r: to_float(r["swell_period"])),
    ("sst",           "水温(℃)",            lambda r: to_float(r["sst"])),
    ("current_spd",   "海流速(km/h)",        lambda r: to_float(r["current_spd"])),
    ("current_dir",   "海流向(度)",          lambda r: to_float(r["current_dir"])),
    ("tide_type_n",   "潮型(大4〜若1)",      lambda r: tide_type_num(r["tide_type"])),
    ("tide_range",    "潮差(cm)",            lambda r: to_float(r["tide_range"])),
    ("moon_age",      "月齢(日)",            lambda r: to_float(r["moon_age"])),
    ("flood1_t",      "満潮1時刻(h)",        lambda r: parse_time(r["flood1"])),
    ("flood1_cm",     "満潮1水位(cm)",       lambda r: to_float(r["flood1_cm"])),
    ("ebb1_t",        "干潮1時刻(h)",        lambda r: parse_time(r["ebb1"])),
    ("ebb1_cm",       "干潮1水位(cm)",       lambda r: to_float(r["ebb1_cm"])),
]


# ── データロード ─────────────────────────────────────────────────────────
def load_rows():
    with open(INPUT_CSV, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


# ── 週次集計（差分・共起用） ─────────────────────────────────────────────
def make_weekly_stats(rows):
    """週次の魚種別平均cnt_avg + 平均海況を返す。"""
    week_data = defaultdict(lambda: defaultdict(list))   # [week][fish] → [cnt_avg]
    week_wx   = defaultdict(lambda: defaultdict(list))   # [week][factor] → [vals]
    week_ships = defaultdict(set)                         # [week] → {ships}

    for r in rows:
        # enriched_catches.csv は欠航除外済み
        cnt = to_float(r["cnt_avg"])
        if not cnt or cnt <= 0:
            continue
        try:
            d = datetime.strptime(r["date"], "%Y/%m/%d")
        except ValueError:
            continue
        week = d.strftime("%G/W%V")  # ISO週
        fish = r["tsuri_mono"]
        if fish and r["main_sub"] == "メイン":
            week_data[week][fish].append(cnt)
        if r["lat"]:
            week_ships[week].add(r["ship"])
        for key, _, fn in FEATURES:
            v = fn(r)
            if v is not None:
                week_wx[week][key].append(v)

    # 週次平均化
    weekly = {}
    for week in sorted(set(week_data) | set(week_wx)):
        fish_avgs = {fish: sum(vs) / len(vs) for fish, vs in week_data[week].items() if vs}
        wx_avgs   = {key: sum(vs) / len(vs) for key, vs in week_wx[week].items() if vs}
        weekly[week] = {
            "fish_avgs": fish_avgs,
            "wx_avgs":   wx_avgs,
            "n_ships":   len(week_ships[week]),
        }
    return weekly


def add_delta_features(weekly):
    """前週との差分特徴量（Δsst, Δwave等）を週次データに追加。"""
    weeks = sorted(weekly.keys())
    for i, week in enumerate(weeks):
        if i == 0:
            continue
        prev_week = weeks[i - 1]
        for key in ["sst", "wave_height", "wind_speed", "swell_height"]:
            cur  = weekly[week]["wx_avgs"].get(key)
            prev = weekly[prev_week]["wx_avgs"].get(key)
            if cur is not None and prev is not None:
                weekly[week]["wx_avgs"][f"d_{key}"] = cur - prev


# ── コンボ分析 ──────────────────────────────────────────────────────────
def analyze_combo(fish, ship, rows, out_lines, summary_row):
    """1コンボを分析してレポートに書き出す。"""
    cnt_y = []
    feat_x = {key: [] for key, _, _ in FEATURES}

    for r in rows:
        cnt = to_float(r["cnt_avg"])
        if cnt is None or cnt <= 0:
            continue
        cnt_y.append(cnt)
        for key, _, fn in FEATURES:
            feat_x[key].append(fn(r))

    n = len(cnt_y)
    if n < MIN_COMBO_N:
        return

    avg_cnt  = sum(cnt_y) / n
    # 代表座標（最頻値の座標）
    lats = [to_float(r["lat"]) for r in rows if r["lat"]]
    lons = [to_float(r["lon"]) for r in rows if r["lon"]]
    lat_repr = round(sum(lats) / len(lats), 2) if lats else None
    lon_repr = round(sum(lons) / len(lons), 2) if lons else None

    lines = [f"\n{'='*60}"]
    lines.append(f"=== {fish} × {ship} ===")
    lines.append(f"件数: {n}行 / 平均cnt_avg: {avg_cnt:.1f}")
    if lat_repr:
        lines.append(f"代表座標: lat={lat_repr}, lon={lon_repr}")

    # 単変量相関
    sig_lines  = []
    nosig_lines = []
    for key, label, _ in FEATURES:
        r_val, p_val, n_pair = pearson(feat_x[key], cnt_y)
        if r_val is None:
            continue
        summary_row[key] = f"{r_val:+.3f}"
        star = p_star(p_val)
        line = f"  {label:<18s} r={r_val:+.3f} p={p_val:.3f} {star} n={n_pair}"
        if p_val is not None and p_val < 0.05 and abs(r_val) >= 0.1:
            sig_lines.append((abs(r_val), line))
        else:
            nosig_lines.append(line)

    if sig_lines:
        lines.append("\n--- 有意な相関（|r|≥0.1, p<0.05） ---")
        for _, ln in sorted(sig_lines, key=lambda x: -x[0]):
            lines.append(ln)

    if nosig_lines:
        lines.append("\n--- 非有意 / 弱い相関 ---")
        for ln in nosig_lines[:8]:  # 上位8件だけ表示
            lines.append(ln)

    # 複合効果
    lines.append("\n--- 複合効果 ---")
    compound_cases = [
        ("荒天(wind>7 & wave>1.5)",
            lambda r: to_float(r["wind_speed"]) is not None and to_float(r["wind_speed"]) > 7
                      and to_float(r["wave_height"]) is not None and to_float(r["wave_height"]) > 1.5),
        ("大潮(tide_range>130)",
            lambda r: to_float(r["tide_range"]) is not None and to_float(r["tide_range"]) > 130),
        ("小潮(tide_range<70)",
            lambda r: to_float(r["tide_range"]) is not None and to_float(r["tide_range"]) < 70),
        ("強海流(current_spd>0.5)",
            lambda r: to_float(r["current_spd"]) is not None and to_float(r["current_spd"]) > 0.5),
        ("水温高(sst>22℃)",
            lambda r: to_float(r["sst"]) is not None and to_float(r["sst"]) > 22),
        ("水温低(sst<16℃)",
            lambda r: to_float(r["sst"]) is not None and to_float(r["sst"]) < 16),
    ]
    for label_c, cond_fn in compound_cases:
        try:
            grp_in  = [to_float(r["cnt_avg"]) for r in rows if to_float(r["cnt_avg"]) and cond_fn(r)]
            grp_out = [to_float(r["cnt_avg"]) for r in rows if to_float(r["cnt_avg"]) and not cond_fn(r)]
        except Exception:
            continue
        if len(grp_in) < 5:
            continue
        avg_in  = sum(grp_in) / len(grp_in)
        avg_out = sum(grp_out) / len(grp_out) if grp_out else None
        if avg_out:
            diff_pct = (avg_in - avg_out) / avg_out * 100
            lines.append(f"  {label_c:<28s}: {avg_in:.1f}匹 vs 通常{avg_out:.1f}匹 → {diff_pct:+.0f}% (n={len(grp_in)})")

    out_lines.extend(lines)


# ── 魚種間共起 ───────────────────────────────────────────────────────────
def compute_cooccurrence(weekly):
    """週次の魚種別avg_cnt 相関行列を返す。"""
    # 対象魚種: 30週以上データがあるもの
    fish_weeks = defaultdict(list)
    all_weeks = sorted(weekly.keys())

    for week in all_weeks:
        for fish, avg in weekly[week]["fish_avgs"].items():
            fish_weeks[fish].append((week, avg))

    fish_list = [f for f, ws in fish_weeks.items() if len(ws) >= 30]
    fish_list = sorted(fish_list)

    # 共起週のペアごとに相関
    matrix = {}
    for i, f1 in enumerate(fish_list):
        f1_map = {w: v for w, v in fish_weeks[f1]}
        for f2 in fish_list[i:]:
            f2_map = {w: v for w, v in fish_weeks[f2]}
            common = sorted(set(f1_map) & set(f2_map))
            if len(common) < 10:
                matrix[(f1, f2)] = (None, None, len(common))
                matrix[(f2, f1)] = (None, None, len(common))
                continue
            xs = [f1_map[w] for w in common]
            ys = [f2_map[w] for w in common]
            r_val, p_val, n = pearson(xs, ys)
            matrix[(f1, f2)] = (r_val, p_val, n)
            matrix[(f2, f1)] = (r_val, p_val, n)

    return fish_list, matrix


# ── 出船数 × 海況 ────────────────────────────────────────────────────────
def analyze_departure_bias(weekly, out_lines):
    """荒天日に出船数が減るバイアスを確認。"""
    wx_keys = ["wave_height", "wind_speed"]
    n_ships_list = []
    wx_vals = {k: [] for k in wx_keys}
    for week, d in weekly.items():
        ns = d["n_ships"]
        if ns == 0:
            continue
        n_ships_list.append(ns)
        for k in wx_keys:
            wx_vals[k].append(d["wx_avgs"].get(k))

    out_lines.append("\n" + "="*60)
    out_lines.append("=== 出船数 × 海況（サバイバルバイアス確認）===")
    out_lines.append(f"分析期間: {len(n_ships_list)}週")
    for k in wx_keys:
        r_val, p_val, n = pearson(wx_vals[k], n_ships_list)
        if r_val is not None:
            out_lines.append(f"  出船数 vs {k}: r={r_val:+.3f} p={p_val:.3f} {p_star(p_val)}")


# ── メイン ───────────────────────────────────────────────────────────────
def main():
    fish_filter = None
    args = sys.argv[1:]
    for i, a in enumerate(args):
        if a == "--fish" and i + 1 < len(args):
            fish_filter = args[i + 1]

    print(f"=== analysis_combos.py 開始 ===")
    if fish_filter:
        print(f"  魚種フィルタ: {fish_filter}")

    rows = load_rows()
    print(f"enriched_catches.csv: {len(rows):,}行")

    # 欠航・cnt_avg空は除外
    valid = [
        r for r in rows
        if r.get("cnt_avg")
        and r.get("tsuri_mono")
        and r.get("main_sub") == "メイン"
    ]
    print(f"分析対象: {len(valid):,}行（メイン × cnt_avgあり × 欠航除外）")

    # 週次集計
    weekly = make_weekly_stats(rows)
    add_delta_features(weekly)
    print(f"週次集計: {len(weekly)}週")

    # コンボ集計
    combos = defaultdict(list)
    for r in valid:
        if fish_filter and r["tsuri_mono"] != fish_filter:
            continue
        combos[(r["tsuri_mono"], r["ship"])].append(r)
    combos = {k: v for k, v in combos.items() if len(v) >= MIN_COMBO_N}
    print(f"コンボ数(n>={MIN_COMBO_N}): {len(combos)}件")

    # レポート生成
    out_lines = [f"=== 分析レポート ===", f"生成日時: {datetime.now().strftime('%Y-%m-%d %H:%M')}"]
    summary_rows = []
    feat_keys = [key for key, _, _ in FEATURES]

    # コンボ別分析
    combos_sorted = sorted(combos.items(), key=lambda x: (-len(x[1]), x[0][0], x[0][1]))
    for (fish, ship), combo_rows in combos_sorted:
        summary_row = {"fish": fish, "ship": ship, "n": len(combo_rows)}
        analyze_combo(fish, ship, combo_rows, out_lines, summary_row)
        summary_rows.append(summary_row)

    # 出船数バイアス確認
    analyze_departure_bias(weekly, out_lines)

    # 魚種間共起
    out_lines.append("\n" + "="*60)
    out_lines.append("=== 魚種間共起行列（週次avg_cnt, n≥10共通週）===")
    fish_list, matrix = compute_cooccurrence(weekly)
    out_lines.append("  " + "  ".join(f"{f[:4]:<6}" for f in fish_list))
    for f1 in fish_list:
        row_str = f"{f1[:6]:<8}"
        for f2 in fish_list:
            rv, _, _ = matrix.get((f1, f2), (None, None, 0))
            if rv is None:
                row_str += "  N/A  "
            else:
                row_str += f" {rv:+.2f} "
        out_lines.append(row_str)

    # デルタ特徴量の週次相関（釣果への影響）
    out_lines.append("\n" + "="*60)
    out_lines.append("=== 海況変化トレンド（Δ前週差分 vs 週次平均釣果）===")
    delta_keys = ["d_sst", "d_wave_height", "d_wind_speed", "d_swell_height"]
    all_fish = sorted({r["tsuri_mono"] for r in valid})
    if fish_filter:
        all_fish = [f for f in all_fish if f == fish_filter]
    for fish in all_fish[:10]:
        dy = []
        dx_map = {k: [] for k in delta_keys}
        for week, d in weekly.items():
            cnt = d["fish_avgs"].get(fish)
            if cnt is None:
                continue
            dy.append(cnt)
            for k in delta_keys:
                dx_map[k].append(d["wx_avgs"].get(k))
        if len(dy) < 15:
            continue
        line_parts = []
        for k in delta_keys:
            rv, pv, n = pearson(dx_map[k], dy)
            if rv is not None:
                line_parts.append(f"{k}={rv:+.2f}({p_star(pv).strip() or '-'})")
        if line_parts:
            out_lines.append(f"  {fish}: " + "  ".join(line_parts))

    # 書き出し
    with open(REPORT_TXT, "w", encoding="utf-8") as f:
        f.write("\n".join(out_lines))
    print(f"→ {REPORT_TXT} 書き出し完了")

    # サマリーCSV
    with open(SUMMARY_CSV, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["fish", "ship", "n"] + feat_keys)
        writer.writeheader()
        for row in summary_rows:
            writer.writerow(row)
    print(f"→ {SUMMARY_CSV} 書き出し完了")

    # 共起行列CSV
    with open(COOCCUR_CSV, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["fish"] + fish_list)
        for f1 in fish_list:
            row = [f1]
            for f2 in fish_list:
                rv, _, _ = matrix.get((f1, f2), (None, None, 0))
                row.append(f"{rv:+.3f}" if rv is not None else "")
            writer.writerow(row)
    print(f"→ {COOCCUR_CSV} 書き出し完了")

    print(f"\n=== 完了 ===")
    print(f"コンボ数: {len(combos)}件 / 魚種: {len(set(k[0] for k in combos))}種 / 船宿: {len(set(k[1] for k in combos))}宿")


if __name__ == "__main__":
    main()
