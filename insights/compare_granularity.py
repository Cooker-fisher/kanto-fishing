#!/usr/bin/env python3
"""
compare_granularity.py — 日次 vs 週次平均 の相関係数比較

[目的]
  同じ (fish, ship) コンボについて、
  (A) 日次生データ（1行=1釣果レコード）
  (B) 週次平均（週ごとに cnt_avg・海況を平均してから相関）
  の両方でPearson rを計算し、差異を比較する。

[見どころ]
  - r_daily >> r_weekly → 疑似反復による水増し（n が多いだけ）
  - r_daily ≈ r_weekly  → 堅牢なシグナル（本物の関係）
  - sig_daily=True, sig_weekly=False → 過信シグナル（要注意）

[出力]
  insights/granularity_comparison.txt  コンボ別詳細
  insights/granularity_summary.txt     因子ごとの堅牢性集計

[使い方]
  python insights/compare_granularity.py
  python insights/compare_granularity.py --fish アジ
"""

import csv, math, os, sys
from collections import defaultdict
from datetime import datetime

BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
INPUT_CSV  = os.path.join(BASE_DIR, "enriched_catches.csv")
DETAIL_TXT = os.path.join(BASE_DIR, "granularity_comparison.txt")
SUMMARY_TXT= os.path.join(BASE_DIR, "granularity_summary.txt")

MIN_DAILY_N  = 30   # コンボ最小レコード数
MIN_WEEKLY_N = 10   # 週次集計後の最小週数

# ── 統計 ─────────────────────────────────────────────────────────────────
def to_float(v):
    try:
        return float(v) if v not in ("", None) else None
    except (ValueError, TypeError):
        return None

def parse_time(t):
    if not t:
        return None
    try:
        h, m = t.split(":")
        return int(h) + int(m) / 60
    except Exception:
        return None

TIDE_TYPE_MAP = {"大潮": 4, "中潮": 3, "小潮": 2, "長潮": 1, "若潮": 1}

FEATURES = [
    ("wind_speed",  "風速(m/s)",        lambda r: to_float(r.get("wind_speed"))),
    ("wind_dir",    "風向(度)",          lambda r: to_float(r.get("wind_dir"))),
    ("temp",        "気温(℃)",          lambda r: to_float(r.get("temp"))),
    ("pressure",    "気圧(hPa)",        lambda r: to_float(r.get("pressure"))),
    ("wave_height", "波高(m)",          lambda r: to_float(r.get("wave_height"))),
    ("wave_period", "波周期(s)",        lambda r: to_float(r.get("wave_period"))),
    ("swell_height","うねり高(m)",      lambda r: to_float(r.get("swell_height"))),
    ("sst",         "水温(℃)",         lambda r: to_float(r.get("sst"))),
    ("current_spd", "海流速(km/h)",     lambda r: to_float(r.get("current_spd"))),
    ("tide_range",  "潮差(cm)",         lambda r: to_float(r.get("tide_range"))),
    ("moon_age",    "月齢(日)",         lambda r: to_float(r.get("moon_age"))),
    ("flood1_cm",   "満潮1水位(cm)",    lambda r: to_float(r.get("flood1_cm"))),
    ("ebb1_cm",     "干潮1水位(cm)",    lambda r: to_float(r.get("ebb1_cm"))),
]

def _norm_cdf(z):
    a1,a2,a3,a4,a5 = 0.319381530,-0.356563782,1.781477937,-1.821255978,1.330274429
    p_c = 0.2316419
    k = 1 / (1 + p_c * z)
    poly = k*(a1+k*(a2+k*(a3+k*(a4+k*a5))))
    return 1 - (1/math.sqrt(2*math.pi))*math.exp(-z**2/2)*poly

def pearson(xs, ys):
    pairs = [(x,y) for x,y in zip(xs,ys) if x is not None and y is not None]
    n = len(pairs)
    if n < 5:
        return None, None, n
    sx = [p[0] for p in pairs]; sy = [p[1] for p in pairs]
    mx,my = sum(sx)/n, sum(sy)/n
    num = sum((x-mx)*(y-my) for x,y in pairs)
    dx = math.sqrt(sum((x-mx)**2 for x in sx))
    dy = math.sqrt(sum((y-my)**2 for y in sy))
    if dx==0 or dy==0:
        return None, None, n
    r = max(-1.0, min(1.0, num/(dx*dy)))
    if abs(r)==1.0:
        p = 0.0
    else:
        t = r*math.sqrt(n-2)/math.sqrt(1-r**2)
        p = 2*(1-_norm_cdf(abs(t)))
    return r, p, n

def sig(p, r):
    """有意かつ|r|>=0.1"""
    return p is not None and p < 0.05 and abs(r) >= 0.1

# ── データロード ─────────────────────────────────────────────────────────
def load_combos(fish_filter=None):
    """enriched_catches.csv → {(fish,ship): [rows]} に整理"""
    combos = defaultdict(list)
    with open(INPUT_CSV, encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            cnt = to_float(row.get("cnt_avg"))
            if not cnt or cnt <= 0:
                continue
            if row.get("main_sub") != "メイン":
                continue
            fish = row.get("tsuri_mono", "").strip()
            if not fish:
                continue
            if fish_filter and fish != fish_filter:
                continue
            combos[(fish, row.get("ship",""))].append(row)
    return {k: v for k, v in combos.items() if len(v) >= MIN_DAILY_N}

# ── 週次集計 ─────────────────────────────────────────────────────────────
def to_weekly(rows):
    """
    1コンボの行リストを週次平均に集約。
    戻り値: [{cnt_avg, wind_speed, sst, ...}] (週単位の擬似行)
    """
    week_buckets = defaultdict(lambda: defaultdict(list))
    for r in rows:
        try:
            d = datetime.strptime(r["date"], "%Y/%m/%d")
        except ValueError:
            continue
        week = d.strftime("%G/W%V")
        cnt = to_float(r.get("cnt_avg"))
        if cnt:
            week_buckets[week]["cnt_avg"].append(cnt)
        for key, _, fn in FEATURES:
            v = fn(r)
            if v is not None:
                week_buckets[week][key].append(v)

    result = []
    for week, d in sorted(week_buckets.items()):
        if not d.get("cnt_avg"):
            continue
        rec = {"cnt_avg": sum(d["cnt_avg"]) / len(d["cnt_avg"])}
        for key, _, _ in FEATURES:
            vals = d.get(key, [])
            rec[key] = sum(vals)/len(vals) if vals else None
        result.append(rec)
    return result

# ── 1コンボ比較 ──────────────────────────────────────────────────────────
def compare_combo(fish, ship, rows):
    """
    日次・週次両方でPearson計算。
    戻り値: [(key, label, r_d, p_d, n_d, r_w, p_w, n_w), ...]
    """
    weekly_rows = to_weekly(rows)
    n_daily  = len(rows)
    n_weekly = len(weekly_rows)

    cnt_daily  = [to_float(r["cnt_avg"]) for r in rows]
    cnt_weekly = [r["cnt_avg"] for r in weekly_rows]

    results = []
    for key, label, fn in FEATURES:
        x_d = [fn(r) for r in rows]
        x_w = [r.get(key) for r in weekly_rows]

        r_d, p_d, nd = pearson(x_d, cnt_daily)
        r_w, p_w, nw = pearson(x_w, cnt_weekly)
        results.append((key, label, r_d, p_d, nd, r_w, p_w, nw))

    return results, n_daily, n_weekly

# ── 出力 ─────────────────────────────────────────────────────────────────
def fmt_r(r, p):
    if r is None:
        return "    -   "
    star = "***" if p < 0.001 else "** " if p < 0.01 else "*  " if p < 0.05 else "   "
    return f"{r:+.3f}{star}"

def robustness_label(r_d, p_d, r_w, p_w):
    """堅牢性判定"""
    if r_d is None:
        return "-"
    s_d = sig(p_d, r_d)
    s_w = sig(p_w, r_w) if r_w is not None else False
    if s_d and s_w:
        dr = abs(abs(r_d) - abs(r_w))
        if dr < 0.05:
            return "★★★ 堅牢"
        elif dr < 0.10:
            return "★★  やや堅牢"
        else:
            return "★   r差大"
    if s_d and not s_w:
        return "△   週次で消滅（疑似反復の疑い）"
    if not s_d and s_w:
        return "◇   週次のみ有意"
    return "－   非有意"

def write_detail(combos, fish_filter, out_path):
    lines = ["# 日次 vs 週次平均 相関係数比較", ""]
    lines.append(f"{'因子':<18} {'日次r':>10} {'n_日':>6}  {'週次r':>10} {'n_週':>6}  堅牢性")
    lines.append("-"*80)

    for (fish, ship), rows in sorted(combos.items()):
        if fish_filter and fish != fish_filter:
            continue
        result, n_d, n_w = compare_combo(fish, ship, rows)
        if n_w < MIN_WEEKLY_N:
            continue

        lines.append(f"\n=== {fish} × {ship}  (日次n={n_d}, 週次n={n_w}) ===")
        for key, label, r_d, p_d, nd, r_w, p_w, nw in result:
            rob = robustness_label(r_d, p_d, r_w, p_w)
            r_d_s = fmt_r(r_d, p_d) if r_d is not None else "    -   "
            r_w_s = fmt_r(r_w, p_w) if r_w is not None else "    -   "
            lines.append(f"  {label:<18} {r_d_s:>10} {nd:>6}  {r_w_s:>10} {nw:>6}  {rob}")

    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"保存: {out_path}")

def write_summary(combos, out_path):
    """
    全コンボを集計して因子ごとの堅牢性スコアを出す。
    堅牢率 = 日次有意 AND 週次有意 のコンボ数 / 日次有意コンボ数
    """
    # key → カウンター
    cnt_sig_d  = defaultdict(int)  # 日次で有意
    cnt_sig_w  = defaultdict(int)  # 週次でも有意
    cnt_infl   = defaultdict(int)  # 日次有意→週次消滅（水増し疑い）
    r_d_all    = defaultdict(list)
    r_w_all    = defaultdict(list)
    dr_all     = defaultdict(list)

    for (fish, ship), rows in combos.items():
        result, n_d, n_w = compare_combo(fish, ship, rows)
        if n_w < MIN_WEEKLY_N:
            continue
        for key, label, r_d, p_d, nd, r_w, p_w, nw in result:
            if r_d is None:
                continue
            r_d_all[key].append(abs(r_d))
            if r_w is not None:
                r_w_all[key].append(abs(r_w))
                dr_all[key].append(abs(r_d) - abs(r_w))
            s_d = sig(p_d, r_d)
            s_w = sig(p_w, r_w) if r_w is not None else False
            if s_d:
                cnt_sig_d[key] += 1
                if s_w:
                    cnt_sig_w[key] += 1
                else:
                    cnt_infl[key] += 1

    label_map = {key: label for key, label, _ in FEATURES}
    lines = [
        "# 因子別 堅牢性サマリー（全コンボ集計）",
        "",
        "「堅牢率」= 日次で有意なコンボのうち週次でも有意に残る割合",
        "「r差平均」= |r_日次| - |r_週次| の平均（大きいほど水増し傾向）",
        "",
        f"{'因子':<18} {'日次有意':>8} {'両方有意':>8} {'堅牢率':>7} {'r差平均':>8} {'水増し疑い':>10}  評価",
        "-"*85,
    ]

    # 堅牢率でソート
    keys = sorted(cnt_sig_d.keys(),
                  key=lambda k: cnt_sig_w[k]/cnt_sig_d[k] if cnt_sig_d[k] else 0,
                  reverse=True)

    for key in keys:
        sd = cnt_sig_d[key]
        sw = cnt_sig_w[key]
        infl = cnt_infl[key]
        rate = sw / sd * 100 if sd else 0
        dr_mean = sum(dr_all[key])/len(dr_all[key]) if dr_all[key] else 0
        label = label_map.get(key, key)
        if rate >= 70:
            eval_ = "★★★ 信頼できる"
        elif rate >= 40:
            eval_ = "★★  やや信頼"
        elif rate >= 20:
            eval_ = "★   弱い"
        else:
            eval_ = "×   疑似反復の疑い"
        lines.append(
            f"  {label:<18} {sd:>8} {sw:>8} {rate:>6.0f}% {dr_mean:>+8.3f} {infl:>10}  {eval_}"
        )

    lines += [
        "",
        "【解釈ガイド】",
        "  堅牢率高 + r差小: 日次でも週次でも同じ結論 → スコアに使ってOK",
        "  堅牢率低 + r差大: 日次はnが多いだけで週次では消える → スコアには週次rを使う",
        "  日次有意=0:       そもそも効いていない因子",
    ]

    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"保存: {out_path}")

# ── メイン ───────────────────────────────────────────────────────────────
def main():
    args = sys.argv[1:]
    fish_filter = None
    i = 0
    while i < len(args):
        if args[i] == "--fish" and i+1 < len(args):
            fish_filter = args[i+1]; i += 2
        else:
            i += 1

    print("=== compare_granularity.py 開始 ===")
    print("読み込み中...", end=" ", flush=True)
    combos = load_combos(fish_filter)
    print(f"{len(combos)}コンボ")

    write_detail(combos, fish_filter, DETAIL_TXT)
    write_summary(combos, SUMMARY_TXT)

    print("\n=== 完了 ===")
    print(f"  詳細: {DETAIL_TXT}")
    print(f"  集計: {SUMMARY_TXT}")

if __name__ == "__main__":
    main()
