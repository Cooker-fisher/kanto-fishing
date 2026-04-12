#!/usr/bin/env python3
"""
backtest_oos.py — Out-of-Sample バックテスト

[設計]
  学習期間: 2023-01-01 〜 2024-12-31  → r値・hist_mean/std を計算
  検証期間: 2025-01-01 〜 2026-04-02  → 予測精度を評価

  in-sample（backtest.py）との数字を比較することで
  「モデルが過学習しているか」「本当に汎化しているか」を確認する。

[出力]
  insights/backtest_oos.txt
"""
import csv, math, os, sqlite3
from collections import defaultdict
from datetime import datetime, timedelta, date

import sys as _sys; _sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _paths import ROOT_DIR, RESULTS_DIR, DATA_DIR, NORMALIZE_DIR, OCEAN_DIR
DB_ANA   = os.path.join(RESULTS_DIR, "analysis.sqlite")
DB_WX    = os.path.join(OCEAN_DIR, "weather_cache.sqlite")
OUT_TXT  = os.path.join(RESULTS_DIR, "backtest_oos.txt")

# 学習/検証の分割: 実行日から90日前を境界とする（データが増えるたびに自動拡大）
_today = date.today()
_cutoff = _today - timedelta(days=90)
TRAIN_END  = _cutoff.strftime("%Y-%m-%d")                    # 学習期間の終わり
TEST_START = (_cutoff + timedelta(days=1)).strftime("%Y-%m-%d")  # 検証期間の始まり

FACTORS = ["sst", "temp", "wave_height", "wind_speed", "pressure", "current_speed"]
MIN_R   = 0.15   # 採用するr値の最小値（build_wx_params と同じ）
MIN_N_TRAIN = 20  # 学習サンプル数の下限
MIN_N_TEST  = 5   # 検証サンプル数の下限

# ── ユーティリティ ──────────────────────────────────────────────────────────
def nearest_coord(lat, lon, coords):
    return min(coords, key=lambda c: (c[0]-lat)**2 + (c[1]-lon)**2)

def pearson(xs, ys):
    n = len(xs)
    if n < 5:
        return None, None
    mx = sum(xs)/n; my = sum(ys)/n
    num = sum((x-mx)*(y-my) for x,y in zip(xs,ys))
    dx  = math.sqrt(sum((x-mx)**2 for x in xs))
    dy  = math.sqrt(sum((y-my)**2 for y in ys))
    if dx == 0 or dy == 0:
        return None, None
    r = num / (dx * dy)
    if abs(r) >= 1.0:
        return r, 0.0
    t = r * math.sqrt(n-2) / math.sqrt(1-r**2)
    p = 2 * (1 - _norm_cdf(abs(t)))
    return r, p

def _norm_cdf(x):
    t = 1/(1+0.2316419*abs(x))
    poly = t*(0.319381530+t*(-0.356563782+t*(1.781477937+t*(-1.821255978+t*1.330274429))))
    return 1 - (1/math.sqrt(2*math.pi))*math.exp(-0.5*x**2)*poly if x>=0 else (1/math.sqrt(2*math.pi))*math.exp(-0.5*x**2)*poly

def isoweek(date_str):
    try:
        d = datetime.strptime(date_str, "%Y/%m/%d")
        return d.isocalendar()[:2]
    except Exception:
        return None, None

def date_to_iso(date_str):
    """'YYYY/MM/DD' → 'YYYY-MM-DD'"""
    return date_str.replace("/", "-")

# ── データロード ────────────────────────────────────────────────────────────
def load_ship_coords():
    conn = sqlite3.connect(DB_ANA)
    coords = {ship: (lat, lon) for ship, lat, lon in conn.execute(
        "SELECT ship, AVG(lat), AVG(lon) FROM combo_meta WHERE lat IS NOT NULL GROUP BY ship"
    ).fetchall()}
    conn.close()
    return coords

def load_wx_coords():
    conn = sqlite3.connect(DB_WX)
    coords = conn.execute("SELECT DISTINCT lat, lon FROM weather").fetchall()
    conn.close()
    return coords

def get_daily_wx(conn_wx, lat, lon, date_iso):
    row = conn_wx.execute("""
        SELECT wave_height, wind_speed
        FROM weather WHERE lat=? AND lon=? AND dt LIKE ?
        ORDER BY ABS(CAST(substr(dt,12,2) AS INT) - 6) LIMIT 1
    """, (lat, lon, f"{date_iso}%")).fetchone()
    return row

def get_weekly_wx(conn_wx, lat, lon, year, week_no):
    d = datetime.strptime(f"{year}-W{week_no:02d}-1", "%G-W%V-%u")
    dates = [(d + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(7)]
    rows = []
    for date_iso in dates:
        r = conn_wx.execute("""
            SELECT sst, temp, wave_height, wind_speed, pressure, current_speed
            FROM weather WHERE lat=? AND lon=? AND dt LIKE ?
            ORDER BY ABS(CAST(substr(dt,12,2) AS INT) - 6) LIMIT 1
        """, (lat, lon, f"{date_iso}%")).fetchone()
        if r:
            rows.append(r)
    if not rows:
        return None
    result = {}
    for i, k in enumerate(FACTORS):
        vals = [r[i] for r in rows if r[i] is not None]
        if vals:
            result[k] = sum(vals)/len(vals)
    return result

def load_records_split():
    """全レコードを train/test に分割"""
    train, test = [], []
    for fn in sorted(os.listdir(DATA_DIR)):
        if not fn.endswith(".csv") or fn == "cancellations.csv":
            continue
        with open(os.path.join(DATA_DIR, fn), encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                ship = row.get("ship","").strip()
                date = row.get("date","").strip()
                if not ship or not date:
                    continue
                date_iso = date_to_iso(date)
                is_cancel = row.get("is_cancellation") == "1"
                tsuri_mono = row.get("tsuri_mono","").strip()
                try:
                    cnt_avg = float(row.get("cnt_avg") or 0)
                except ValueError:
                    cnt_avg = 0.0
                rec = {"ship": ship, "date": date, "date_iso": date_iso,
                       "is_cancel": is_cancel, "tsuri_mono": tsuri_mono, "cnt_avg": cnt_avg,
                       "cancel_type": (row.get("cancel_type") or "").strip()}
                if date_iso <= TRAIN_END:
                    train.append(rec)
                elif date_iso >= TEST_START:
                    test.append(rec)
    return train, test

# ── 学習: r値・hist_mean/std を計算 ─────────────────────────────────────────
def build_params_from_train(train_records, ship_coords, wx_coords):
    """
    学習データから combo_wx_params 相当を計算。
    {(fish, ship): [(factor, r, hist_mean, hist_std), ...]}
    """
    print(f"  学習データ: {len(train_records):,}件 → 週次集計中...")
    conn_wx = sqlite3.connect(DB_WX)
    wx_cache = {}

    # 週次の (fish, ship) → [(wx_dict, cnt_avg), ...]
    weekly = defaultdict(list)
    for r in train_records:
        if r["is_cancel"] or not r["tsuri_mono"] or r["cnt_avg"] <= 0:
            continue
        sc = ship_coords.get(r["ship"])
        if not sc:
            continue
        slat, slon = sc
        wlat, wlon = nearest_coord(slat, slon, wx_coords)
        year, week = isoweek(r["date"])
        if year is None:
            continue
        cache_key = (wlat, wlon, year, week)
        if cache_key not in wx_cache:
            wx_cache[cache_key] = get_weekly_wx(conn_wx, wlat, wlon, year, week)
        wx = wx_cache[cache_key]
        if not wx:
            continue
        weekly[(r["tsuri_mono"], r["ship"], year, week)].append((wx, r["cnt_avg"]))

    conn_wx.close()
    print(f"  週次ペア: {len(weekly)}件")

    # コンボ × 因子の相関計算
    # (fish, ship) → {factor: [(wx_val, cnt_avg), ...]}
    combo_factor_data = defaultdict(lambda: defaultdict(list))
    for (fish, ship, year, week), recs in weekly.items():
        wx_avg = {}
        for fac in FACTORS:
            vals = [r[0].get(fac) for r in recs if r[0].get(fac) is not None]
            if vals:
                wx_avg[fac] = sum(vals)/len(vals)
        cnt_avg = sum(r[1] for r in recs) / len(recs)
        for fac, val in wx_avg.items():
            combo_factor_data[(fish, ship)][fac].append((val, cnt_avg))

    # Pearson r + hist_mean/std
    combo_params = {}
    for (fish, ship), fac_data in combo_factor_data.items():
        params = []
        for fac, pairs in fac_data.items():
            if len(pairs) < MIN_N_TRAIN:
                continue
            xs = [p[0] for p in pairs]
            ys = [p[1] for p in pairs]
            r, p = pearson(xs, ys)
            if r is None or abs(r) < MIN_R:
                continue
            mean = sum(xs)/len(xs)
            std  = math.sqrt(sum((x-mean)**2 for x in xs)/len(xs))
            if std == 0:
                continue
            params.append((fac, r, mean, std))
        if params:
            combo_params[(fish, ship)] = params

    print(f"  学習済みコンボ: {len(combo_params)}件")
    return combo_params

# ── 検証: スコア精度 ──────────────────────────────────────────────────────
def run_score_backtest_oos(test_records, combo_params, ship_coords, wx_coords):
    print(f"  検証データ: {len(test_records):,}件 → スコア精度計算中...")
    conn_wx = sqlite3.connect(DB_WX)
    wx_cache = {}

    # 週次の実績集計
    weekly_actual = defaultdict(list)
    for r in test_records:
        if r["is_cancel"] or not r["tsuri_mono"] or r["cnt_avg"] <= 0:
            continue
        year, week = isoweek(r["date"])
        if year is None:
            continue
        weekly_actual[(r["tsuri_mono"], r["ship"], year, week)].append(r["cnt_avg"])

    combo_results = {}
    for (fish, ship), params in combo_params.items():
        sc = ship_coords.get(ship)
        if not sc:
            continue
        slat, slon = sc
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

        if len(scores) < MIN_N_TEST:
            continue

        r_val, p_val = pearson(scores, actuals)
        mean_score  = sum(scores)/len(scores)
        mean_actual = sum(actuals)/len(actuals)
        correct = sum(1 for s, a in zip(scores, actuals) if (s > mean_score) == (a > mean_actual))
        dir_acc = correct / len(scores)
        combo_results[(fish, ship)] = {
            "n": len(scores), "r": r_val, "p": p_val, "dir_acc": dir_acc
        }

    conn_wx.close()
    print(f"  評価コンボ数: {len(combo_results)}")
    return combo_results

# ── 欠航検証 ─────────────────────────────────────────────────────────────
def run_cancel_backtest_oos(test_records, ship_coords, wx_coords):
    """天候欠航に絞った欠航予測 OOS 検証。

    評価スコープ:
      - 海況が閾値を超えた日（荒天候補日）のみ評価する
      - 定休日/中止でも海況が悪ければ評価対象に含める
      - 海況が閾値以下の欠航（定休日・中止）は FN に計上しない（スコープ外）

    判定:
      TP: 海況 >= 閾値 かつ 欠航あり
      FP: 海況 >= 閾値 かつ 出船した（予測外れ）
      FN: 海況 < 閾値 かつ 天候欠航（荒天/台風ラベル）※見逃し
      TN: 海況 < 閾値 かつ 出船 → スコープ外（カウントしない）
          海況 < 閾値 かつ 非天候欠航 → スコープ外（カウントしない）
    """
    # 天候欠航ラベル
    WEATHER_LABELS = {"荒天", "台風"}

    print("  欠航予測検証中（天候欠航スコープ）...")
    conn_ana = sqlite3.connect(DB_ANA)
    thresholds = {ship: (wt, wnd) for ship, wt, wnd in conn_ana.execute(
        "SELECT ship, wave_threshold, wind_threshold FROM cancel_thresholds WHERE wave_threshold IS NOT NULL"
    ).fetchall()}
    conn_ana.close()

    conn_wx = sqlite3.connect(DB_WX)
    wx_cache = {}

    # (ship, date) でユニーク化: 欠航レコード優先、cancel_type も保持
    ship_dates = {}
    for r in test_records:
        key = (r["ship"], r["date"])
        if key not in ship_dates or r["is_cancel"]:
            ship_dates[key] = r

    stats = defaultdict(lambda: {"TP":0,"FP":0,"FN":0,"TN":0,"skipped":0})
    matched = 0
    for (ship, date_str), r in ship_dates.items():
        if ship not in thresholds:
            continue
        wave_thr, wind_thr = thresholds[ship]
        sc = ship_coords.get(ship)
        if not sc:
            continue
        slat, slon = sc
        wlat, wlon = nearest_coord(slat, slon, wx_coords)
        date_iso = date_to_iso(date_str)
        cache_key = (wlat, wlon, date_iso)
        if cache_key not in wx_cache:
            wx_cache[cache_key] = get_daily_wx(conn_wx, wlat, wlon, date_iso)
        wx = wx_cache[cache_key]
        if not wx or wx[0] is None:
            continue
        matched += 1
        wave, wind = wx[0], wx[1]
        is_cancel   = r["is_cancel"]
        cancel_type = r.get("tsuri_mono", "")   # backtest_oos では cancel_type を tsuri_mono に持たせていない
        # cancel_type は test_records に含まれていないので海況のみで判定
        wx_bad = (wave_thr is not None and wave is not None and wave >= wave_thr) or \
                 (wind_thr is not None and wind is not None and wind >= wind_thr)

        if wx_bad:
            # 海況が悪い日: 出欠を評価する
            if is_cancel:
                stats[ship]["TP"] += 1
            else:
                stats[ship]["FP"] += 1
        else:
            # 海況が良い日
            if is_cancel:
                # 天候と無関係の欠航（定休日等）→ スコープ外
                stats[ship]["skipped"] += 1
            # 出船日 → TN（評価しない）

    conn_wx.close()
    print(f"  欠航マッチ: {matched}件")
    return stats

# ── 出力 ─────────────────────────────────────────────────────────────────
def write_results(combo_params, score_results, cancel_stats):
    # in-sample 結果を読み込んで比較
    is_summary = {}
    try:
        with open(os.path.join(RESULTS_DIR, "backtest.txt"), encoding="utf-8") as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 6 and parts[-1].endswith('%') and parts[-3].startswith(('+','-')):
                    try:
                        fish = parts[0]; ship = parts[1]
                        n = int(parts[-4])
                        r = float(parts[-3].rstrip('*'))
                        da = float(parts[-1].rstrip('%')) / 100
                        is_summary[(fish, ship)] = {"n": n, "r": r, "dir_acc": da}
                    except:
                        pass
    except Exception:
        pass

    lines = [
        "# Out-of-Sample バックテスト結果",
        f"# 生成: {datetime.now().strftime('%Y/%m/%d %H:%M')}",
        f"# 学習期間: 2023-01-01 〜 {TRAIN_END}",
        f"# 検証期間: {TEST_START} 〜 {_today.strftime('%Y-%m-%d')}",
        f"# 学習済みコンボ数: {len(combo_params)}",
        "",
        "=" * 75,
        "【1. 釣果スコア Out-of-Sample 検証】",
        "=" * 75,
        "",
        f"  {'魚種':<10} {'船宿':<14} {'週数':>5} {'OOS r':>7} {'IS r':>7} {'r差':>6} {'OOS方向':>8} {'IS方向':>8}",
        "-" * 72,
    ]

    sorted_res = sorted(score_results.items(), key=lambda x: -(x[1]["r"] or -99))
    for (fish, ship), res in sorted_res:
        r_oos = res["r"]
        da_oos = res["dir_acc"]
        if r_oos is None:
            continue
        is_data = is_summary.get((fish, ship), {})
        r_is  = is_data.get("r")
        da_is = is_data.get("dir_acc")
        r_diff = (r_oos - r_is) if r_is is not None else None
        sig = "*" if res["p"] is not None and res["p"] < 0.05 else " "
        r_diff_str = f"{r_diff:+.3f}" if r_diff is not None else "  n/a"
        r_is_str   = f"{r_is:+.3f}" if r_is is not None else "   n/a"
        da_is_str  = f"{da_is:.1%}" if da_is is not None else "  n/a"
        lines.append(
            f"  {fish:<10} {ship:<14} {res['n']:>5}"
            f"  {r_oos:>+6.3f}{sig}  {r_is_str}  {r_diff_str}"
            f"  {da_oos:>7.1%}  {da_is_str}"
        )

    # サマリー比較
    valid = [(k, v) for k, v in score_results.items() if v["r"] is not None]
    if valid:
        rs_oos = [v["r"] for _, v in valid]
        das_oos = [v["dir_acc"] for _, v in valid]
        sig_count = sum(1 for _, v in valid if v["p"] is not None and v["p"] < 0.05)
        pos_count = sum(1 for r in rs_oos if r > 0)
        # IS との比較
        is_rs  = [is_summary[k]["r"] for k, _ in valid if k in is_summary and is_summary[k].get("r") is not None]
        is_das = [is_summary[k]["dir_acc"] for k, _ in valid if k in is_summary and is_summary[k].get("dir_acc") is not None]
        lines += [
            "",
            "  【スコアバックテスト OOS サマリー】",
            f"  評価コンボ数:       {len(valid)}",
            f"  有意(p<0.05):       {sig_count}件 ({sig_count/len(valid):.0%})",
            f"  正相関コンボ:       {pos_count}件 ({pos_count/len(valid):.0%})",
            "",
            f"  {'指標':<20} {'OOS（未知データ）':>16} {'IS（学習データ）':>16} {'差分':>8}",
            f"  {'-'*62}",
            f"  {'r 平均':<20} {sum(rs_oos)/len(rs_oos):>+15.3f}"
            + (f"  {sum(is_rs)/len(is_rs):>+15.3f}  {(sum(rs_oos)/len(rs_oos))-(sum(is_rs)/len(is_rs)):>+7.3f}" if is_rs else ""),
            f"  {'r 中央値':<20} {sorted(rs_oos)[len(rs_oos)//2]:>+15.3f}"
            + (f"  {sorted(is_rs)[len(is_rs)//2]:>+15.3f}  {sorted(rs_oos)[len(rs_oos)//2]-sorted(is_rs)[len(is_rs)//2]:>+7.3f}" if is_rs else ""),
            f"  {'方向一致率 平均':<20} {sum(das_oos)/len(das_oos):>15.1%}"
            + (f"  {sum(is_das)/len(is_das):>15.1%}  {(sum(das_oos)/len(das_oos))-(sum(is_das)/len(is_das)):>+7.1%}" if is_das else ""),
            "",
            "  ★ OOS > IS なら汎化できている、OOS << IS なら過学習",
        ]

    # 欠航バックテスト OOS（天候欠航スコープ）
    lines += [
        "",
        "=" * 75,
        "【2. 欠航予測 Out-of-Sample 検証（天候欠航スコープ）】",
        "=" * 75,
        "  ※ 評価対象: 海況が閾値を超えた日のみ（定休日等の非天候欠航は除外）",
        "  TP=荒天予測かつ欠航, FP=荒天予測かつ出船, FN=荒天見逃し, skipped=非天候欠航（除外）",
        "",
        f"  {'船宿':<14} {'欠航(TP+FN)':>10} {'出船(FP)':>8} {'Precision':>10} {'Recall':>8} {'F1':>6} {'除外':>6}",
        "-" * 70,
    ]
    all_tp = all_fp = all_fn = 0
    all_skipped = 0
    for ship, s in sorted(cancel_stats.items(), key=lambda x: -(x[1]["TP"]+x[1]["FN"])):
        tp, fp, fn = s["TP"], s["FP"], s["FN"]
        skipped = s.get("skipped", 0)
        if tp+fp+fn == 0:
            continue
        prec = tp/(tp+fp) if tp+fp > 0 else 0
        rec  = tp/(tp+fn) if tp+fn > 0 else 0
        f1   = 2*prec*rec/(prec+rec) if prec+rec > 0 else 0
        lines.append(f"  {ship:<14} {tp+fn:>10} {fp:>8}  {prec:>8.1%}  {rec:>7.1%}  {f1:>5.1%}  {skipped:>5}")
        all_tp += tp; all_fp += fp; all_fn += fn; all_skipped += skipped
    if all_tp+all_fp+all_fn > 0:
        p  = all_tp/(all_tp+all_fp) if all_tp+all_fp > 0 else 0
        r  = all_tp/(all_tp+all_fn) if all_tp+all_fn > 0 else 0
        f1 = 2*p*r/(p+r) if p+r > 0 else 0
        lines += [
            "-" * 70,
            f"  {'【OOS全体合計】':<14} {all_tp+all_fn:>10} {all_fp:>8}  {p:>8.1%}  {r:>7.1%}  {f1:>5.1%}  {all_skipped:>5}",
            f"  （除外: 非天候欠航 {all_skipped}件 → 天候予測スコープ外）",
        ]

    with open(OUT_TXT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"保存: {OUT_TXT}")

def main():
    print("=== backtest_oos.py 開始 ===")
    print(f"  学習: 2023-01-01 〜 {TRAIN_END}")
    print(f"  検証: {TEST_START} 〜 {_today.strftime('%Y-%m-%d')}")
    ship_coords = load_ship_coords()
    wx_coords   = load_wx_coords()
    train, test = load_records_split()
    print(f"  学習: {len(train):,}件 / 検証: {len(test):,}件")

    print("\n[学習フェーズ]")
    combo_params = build_params_from_train(train, ship_coords, wx_coords)

    print("\n[検証フェーズ: スコア]")
    score_results = run_score_backtest_oos(test, combo_params, ship_coords, wx_coords)

    print("\n[検証フェーズ: 欠航]")
    cancel_stats = run_cancel_backtest_oos(test, ship_coords, wx_coords)

    write_results(combo_params, score_results, cancel_stats)
    print("=== 完了 ===")

if __name__ == "__main__":
    main()
