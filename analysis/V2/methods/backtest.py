#!/usr/bin/env python3
"""
backtest.py — 欠航予測・釣果スコア予測の後付け精度検証

[検証1: 欠航予測バックテスト]
  cancel_thresholds（船宿別波高・風速閾値） × weather_cache（実測値）
  → 予測: wave >= thr OR wind >= thr → 欠航 / それ以外 → 出船
  → 実際: is_cancellation フラグと照合
  → precision / recall / F1 を船宿別・全体で出力

[検証2: 釣果スコアバックテスト]
  combo_wx_params（r値・hist_mean/std） × weather_cache（週次平均） → wx_score
  → 実際: data/*.csv の週次 cnt_avg との方向一致率・Pearson r

[出力]
  insights/backtest.txt
"""
import csv, math, os, sqlite3
from collections import defaultdict
from datetime import datetime, timedelta

import sys as _sys; _sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _paths import ROOT_DIR, RESULTS_DIR, DATA_DIR, NORMALIZE_DIR, OCEAN_DIR
DB_ANA   = os.path.join(RESULTS_DIR, "analysis.sqlite")
DB_WX    = os.path.join(OCEAN_DIR, "weather_cache.sqlite")
OUT_TXT  = os.path.join(RESULTS_DIR, "backtest.txt")

# ── ユーティリティ ─────────────────────────────────────────────────────────
def nearest_coord(lat, lon, coords):
    return min(coords, key=lambda c: (c[0]-lat)**2 + (c[1]-lon)**2)

def pearson(xs, ys):
    n = len(xs)
    if n < 3:
        return None, None
    mx = sum(xs)/n; my = sum(ys)/n
    num = sum((x-mx)*(y-my) for x,y in zip(xs,ys))
    dx  = math.sqrt(sum((x-mx)**2 for x in xs))
    dy  = math.sqrt(sum((y-my)**2 for y in ys))
    if dx==0 or dy==0:
        return None, None
    r = num/(dx*dy)
    # t検定でp値
    if abs(r) >= 1.0:
        return r, 0.0
    t = r * math.sqrt(n-2) / math.sqrt(1-r**2)
    # 正規近似（簡易）
    p = 2*(1 - _norm_cdf(abs(t)))
    return r, p

def _norm_cdf(x):
    """標準正規分布の累積分布関数（近似）"""
    t = 1/(1+0.2316419*abs(x))
    poly = t*(0.319381530+t*(-0.356563782+t*(1.781477937+t*(-1.821255978+t*1.330274429))))
    return 1 - (1/math.sqrt(2*math.pi))*math.exp(-0.5*x**2)*poly if x>=0 else (1/math.sqrt(2*math.pi))*math.exp(-0.5*x**2)*poly

def isoweek(date_str):
    """'YYYY/MM/DD' → (year, week_no)"""
    try:
        d = datetime.strptime(date_str, "%Y/%m/%d")
        return d.isocalendar()[:2]  # (year, week)
    except Exception:
        return None, None

# ── データロード ──────────────────────────────────────────────────────────
def load_ship_info():
    """ship -> {lat, lon, wave_thr, wind_thr, has_real_thr}"""
    conn = sqlite3.connect(DB_ANA)
    coords = {ship: (lat, lon) for ship, lat, lon in conn.execute(
        "SELECT ship, AVG(lat), AVG(lon) FROM combo_meta WHERE lat IS NOT NULL GROUP BY ship"
    ).fetchall()}
    thresholds = {ship: (wave_thr, wind_thr) for ship, wave_thr, wind_thr in conn.execute(
        "SELECT ship, wave_threshold, wind_threshold FROM cancel_thresholds WHERE wave_threshold IS NOT NULL"
    ).fetchall()}
    conn.close()
    result = {}
    for ship, (lat, lon) in coords.items():
        wt, wnd = thresholds.get(ship, (None, None))
        result[ship] = {
            "lat": lat, "lon": lon,
            "wave_thr": wt, "wind_thr": wnd,
            "has_real_thr": ship in thresholds
        }
    return result

def load_wx_coords():
    conn = sqlite3.connect(DB_WX)
    coords = conn.execute("SELECT DISTINCT lat, lon FROM weather").fetchall()
    conn.close()
    return coords

def get_daily_wx(conn_wx, lat, lon, date_iso):
    """指定日の06:00前後の海況を取得"""
    row = conn_wx.execute("""
        SELECT wave_height, wind_speed
        FROM weather
        WHERE lat=? AND lon=? AND dt LIKE ?
        ORDER BY ABS(CAST(substr(dt,12,2) AS INT) - 6)
        LIMIT 1
    """, (lat, lon, f"{date_iso}%")).fetchone()
    return row  # (wave_height, wind_speed) or None

def get_weekly_wx(conn_wx, lat, lon, year, week_no):
    """指定週（ISO週）の各因子の平均値を返す"""
    # その週の月曜〜日曜を計算
    d = datetime.strptime(f"{year}-W{week_no:02d}-1", "%G-W%V-%u")
    dates = [(d + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(7)]
    rows = []
    for date_iso in dates:
        r = conn_wx.execute("""
            SELECT sst, temp, wave_height, wind_speed, pressure, current_spd
            FROM weather
            WHERE lat=? AND lon=? AND dt LIKE ?
            ORDER BY ABS(CAST(substr(dt,12,2) AS INT) - 6)
            LIMIT 1
        """, (lat, lon, f"{date_iso}%")).fetchone()
        if r:
            rows.append(r)
    if not rows:
        return None
    n = len(rows)
    result = {}
    keys = ["sst","temp","wave_height","wind_speed","pressure","current_spd"]
    for i, k in enumerate(keys):
        vals = [r[i] for r in rows if r[i] is not None]
        if vals:
            result[k] = sum(vals)/len(vals)
    return result

def load_records():
    """全CSV → {(ship, date): is_cancel, tsuri_mono, cnt_avg}"""
    records = []
    for fn in sorted(os.listdir(DATA_DIR)):
        if not fn.endswith(".csv") or fn == "cancellations.csv":
            continue
        with open(os.path.join(DATA_DIR, fn), encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                ship = row.get("ship","").strip()
                date = row.get("date","").strip()
                if not ship or not date:
                    continue
                is_cancel = row.get("is_cancellation") == "1"
                tsuri_mono = row.get("tsuri_mono","").strip()
                try:
                    cnt_avg = float(row.get("cnt_avg") or 0)
                except ValueError:
                    cnt_avg = 0.0
                records.append({
                    "ship": ship, "date": date,
                    "is_cancel": is_cancel,
                    "tsuri_mono": tsuri_mono,
                    "cnt_avg": cnt_avg
                })
    return records

def load_combo_params():
    conn = sqlite3.connect(DB_ANA)
    rows = conn.execute(
        "SELECT fish, ship, factor, r, hist_mean, hist_std FROM combo_wx_params"
    ).fetchall()
    conn.close()
    combo_wx = defaultdict(list)
    for fish, ship, fac, r, m, s in rows:
        combo_wx[(fish, ship)].append((fac, r, m, s))
    return combo_wx

# ── バックテスト1: 欠航予測 ───────────────────────────────────────────────
def run_cancel_backtest(records, ship_info, wx_coords):
    print("  [1] 欠航予測バックテスト...")
    conn_wx = sqlite3.connect(DB_WX)
    wx_cache = {}

    # 船宿ごとに TP/FP/FN/TN を集計
    ship_stats = defaultdict(lambda: {"TP":0,"FP":0,"FN":0,"TN":0})

    # (ship, date) でユニーク化（欠航優先）
    ship_dates = {}
    for r in records:
        key = (r["ship"], r["date"])
        if key not in ship_dates or r["is_cancel"]:
            ship_dates[key] = r["is_cancel"]

    matched = 0
    for (ship, date_str), is_cancel in ship_dates.items():
        sinfo = ship_info.get(ship)
        if not sinfo or not sinfo["has_real_thr"]:
            continue  # 実閾値のある船宿のみ評価
        wave_thr = sinfo["wave_thr"]
        wind_thr = sinfo["wind_thr"]
        if wave_thr is None or wind_thr is None:
            continue
        slat, slon = sinfo["lat"], sinfo["lon"]
        wlat, wlon = nearest_coord(slat, slon, wx_coords)
        date_iso = date_str.replace("/", "-")
        cache_key = (wlat, wlon, date_iso)
        if cache_key not in wx_cache:
            wx_cache[cache_key] = get_daily_wx(conn_wx, wlat, wlon, date_iso)
        wx = wx_cache[cache_key]
        if not wx or wx[0] is None:
            continue
        matched += 1
        wave, wind = wx[0], wx[1]
        predicted_cancel = (wave is not None and wave >= wave_thr) or (wind is not None and wind >= wind_thr)
        if predicted_cancel and is_cancel:
            ship_stats[ship]["TP"] += 1
        elif predicted_cancel and not is_cancel:
            ship_stats[ship]["FP"] += 1
        elif not predicted_cancel and is_cancel:
            ship_stats[ship]["FN"] += 1
        else:
            ship_stats[ship]["TN"] += 1

    conn_wx.close()
    print(f"    海況マッチ: {matched}件 / {len(ship_dates)}件")
    return ship_stats

# ── バックテスト2: 釣果スコア ──────────────────────────────────────────────
def run_score_backtest(records, ship_info, wx_coords, combo_wx):
    print("  [2] 釣果スコアバックテスト...")
    conn_wx = sqlite3.connect(DB_WX)
    wx_cache = {}  # (wlat, wlon, year, week) -> wx_dict

    # 週次の実績集計 (fish, ship, year, week) -> [cnt_avg]
    weekly_actual = defaultdict(list)
    for r in records:
        if r["is_cancel"] or not r["tsuri_mono"] or r["cnt_avg"] <= 0:
            continue
        year, week = isoweek(r["date"])
        if year is None:
            continue
        weekly_actual[(r["tsuri_mono"], r["ship"], year, week)].append(r["cnt_avg"])

    # コンボごとに予測スコア × 実績を比較
    combo_results = {}
    total_combos = len(combo_wx)
    for idx, ((fish, ship), params) in enumerate(combo_wx.items(), 1):
        sinfo = ship_info.get(ship)
        if not sinfo:
            continue
        slat, slon = sinfo["lat"], sinfo["lon"]
        wlat, wlon = nearest_coord(slat, slon, wx_coords)

        scores = []
        actuals = []
        for (f, s, year, week), cnt_list in weekly_actual.items():
            if f != fish or s != ship:
                continue
            cache_key = (wlat, wlon, year, week)
            if cache_key not in wx_cache:
                wx_cache[cache_key] = get_weekly_wx(conn_wx, wlat, wlon, year, week)
            wx = wx_cache[cache_key]
            if not wx:
                continue
            # スコア計算
            contributions = []
            for fac, r, hist_mean, hist_std in params:
                val = wx.get(fac)
                if val is None or hist_std == 0:
                    continue
                z = (val - hist_mean) / hist_std
                contributions.append(r * z)
            if not contributions:
                continue
            score = sum(contributions) / len(contributions)
            actual = sum(cnt_list) / len(cnt_list)
            scores.append(score)
            actuals.append(actual)

        if len(scores) < 5:
            continue

        r_val, p_val = pearson(scores, actuals)
        # 方向一致率: スコアが平均より上の週 → 実績も平均より上
        mean_score = sum(scores)/len(scores)
        mean_actual = sum(actuals)/len(actuals)
        correct = sum(
            1 for s, a in zip(scores, actuals)
            if (s > mean_score) == (a > mean_actual)
        )
        dir_acc = correct / len(scores)
        combo_results[(fish, ship)] = {
            "n": len(scores),
            "r": r_val,
            "p": p_val,
            "dir_acc": dir_acc,
            "mean_score": mean_score,
            "mean_actual": mean_actual,
        }

    conn_wx.close()
    print(f"    評価コンボ数: {len(combo_results)}/{total_combos}")
    return combo_results

# ── 出力 ─────────────────────────────────────────────────────────────────
def write_results(ship_stats, combo_results):
    lines = [
        "# 釣り予測 バックテスト結果",
        f"# 生成: {datetime.now().strftime('%Y/%m/%d %H:%M')}",
        "",
        "=" * 70,
        "【1. 欠航予測バックテスト】",
        "   船宿別 cancel_thresholds × 実測気象 → 欠航フラグと照合",
        "=" * 70,
        "",
        f"  {'船宿':<14} {'欠航N':>6} {'出船N':>6} {'適中率(P)':>9} {'検出率(R)':>9} {'F1':>6} {'特異度':>7}",
        "-" * 65,
    ]

    all_tp = all_fp = all_fn = all_tn = 0
    for ship, s in sorted(ship_stats.items(), key=lambda x: -(x[1]["TP"]+x[1]["FN"])):
        tp, fp, fn, tn = s["TP"], s["FP"], s["FN"], s["TN"]
        if tp+fp+fn+tn == 0:
            continue
        prec = tp/(tp+fp) if tp+fp > 0 else 0
        rec  = tp/(tp+fn) if tp+fn > 0 else 0
        f1   = 2*prec*rec/(prec+rec) if prec+rec > 0 else 0
        spec = tn/(tn+fp) if tn+fp > 0 else 0
        lines.append(
            f"  {ship:<14} {tp+fn:>6} {tn+fp:>6}"
            f"  {prec:>7.1%}  {rec:>7.1%}  {f1:>5.1%}  {spec:>6.1%}"
        )
        all_tp += tp; all_fp += fp; all_fn += fn; all_tn += tn

    # 全体サマリー
    if all_tp+all_fp+all_fn+all_tn > 0:
        p = all_tp/(all_tp+all_fp) if all_tp+all_fp > 0 else 0
        r = all_tp/(all_tp+all_fn) if all_tp+all_fn > 0 else 0
        f1 = 2*p*r/(p+r) if p+r > 0 else 0
        sp = all_tn/(all_tn+all_fp) if all_tn+all_fp > 0 else 0
        lines += [
            "-" * 65,
            f"  {'【全体合計】':<14} {all_tp+all_fn:>6} {all_tn+all_fp:>6}"
            f"  {p:>7.1%}  {r:>7.1%}  {f1:>5.1%}  {sp:>6.1%}",
            "",
            "  [解説]",
            "  適中率(Precision): 欠航と予測したうち実際に欠航だった割合",
            "  検出率(Recall):    実際の欠航のうち予測できた割合",
            "  特異度:            実際の出船日のうち正しく出船と予測した割合",
        ]

    # バックテスト2: 釣果スコア
    lines += [
        "",
        "=" * 70,
        "【2. 釣果スコアバックテスト】",
        "   combo_wx_params × 週次実測気象 → 実際のcnt_avgと比較",
        "=" * 70,
        "",
        f"  {'魚種':<10} {'船宿':<14} {'週数':>5} {'相関r':>7} {'p値':>7} {'方向一致率':>9}",
        "-" * 60,
    ]

    # 相関r でソート
    sorted_combos = sorted(combo_results.items(), key=lambda x: -(x[1]["r"] or -99))
    for (fish, ship), res in sorted_combos:
        r_val = res["r"]
        p_val = res["p"]
        if r_val is None:
            continue
        sig = "*" if p_val is not None and p_val < 0.05 else " "
        lines.append(
            f"  {fish:<10} {ship:<14} {res['n']:>5}"
            f"  {r_val:>+6.3f}{sig}  {(p_val or 1):>6.3f}  {res['dir_acc']:>8.1%}"
        )

    # サマリー統計
    valid = [v for v in combo_results.values() if v["r"] is not None]
    if valid:
        rs = [v["r"] for v in valid]
        das = [v["dir_acc"] for v in valid]
        sig_count = sum(1 for v in valid if v["p"] is not None and v["p"] < 0.05)
        pos_count = sum(1 for r in rs if r > 0)
        lines += [
            "",
            "  【スコアバックテスト サマリー】",
            f"  評価コンボ数: {len(valid)}",
            f"  有意コンボ(p<0.05): {sig_count}件 ({sig_count/len(valid):.0%})",
            f"  正相関コンボ: {pos_count}件 ({pos_count/len(valid):.0%})",
            f"  相関r 平均:   {sum(rs)/len(rs):+.3f}  (中央値: {sorted(rs)[len(rs)//2]:+.3f})",
            f"  方向一致率 平均: {sum(das)/len(das):.1%}  (ランダム期待値: 50.0%)",
            f"  * = p<0.05 で統計的有意",
            "",
            "  [評価基準]",
            "  方向一致率 >60%: 実用レベル",
            "  方向一致率 >70%: 高精度",
            "  方向一致率 <55%: ランダムとほぼ同等",
        ]

    with open(OUT_TXT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"保存: {OUT_TXT}")

def main():
    print("=== backtest.py 開始 ===")
    ship_info  = load_ship_info()
    wx_coords  = load_wx_coords()
    records    = load_records()
    combo_wx   = load_combo_params()
    print(f"船宿: {len(ship_info)} / wx座標: {len(wx_coords)} / レコード: {len(records):,}")

    ship_stats    = run_cancel_backtest(records, ship_info, wx_coords)
    combo_results = run_score_backtest(records, ship_info, wx_coords, combo_wx)

    write_results(ship_stats, combo_results)
    print("=== 完了 ===")

if __name__ == "__main__":
    main()
