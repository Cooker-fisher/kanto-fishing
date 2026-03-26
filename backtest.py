#!/usr/bin/env python3
"""
backtest.py v2 - history.json ベースライン + 気象係数バックテスト

[手法]
1. history.json から (年, 週, 魚種) の実績を取得
2. 予測 = 昨年同週の値（ベースライン）
3. 誤差 = |予測 - 実績| / 実績 × 100 (MAPE)
4. 気象係数（wave_height, wind_speed, tide_range）を回帰で推定し、
   気象補正後の誤差も計算

[出力]
- コンソール: 魚種別MAPE（ベースライン vs 気象補正）
- backtest_result.json: 詳細結果
"""
import json, csv, os, sys, math
from datetime import datetime, timedelta
from collections import defaultdict

sys.stdout.reconfigure(encoding="utf-8")

BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
HISTORY    = os.path.join(BASE_DIR, "history.json")
WEATHER_DIR = os.path.join(BASE_DIR, "weather_data")
OUTPUT     = os.path.join(BASE_DIR, "backtest_result.json")

# ── 評価対象魚種 ────────────────────────────────────────────────
TARGET_FISH = [
    "アジ", "タチウオ", "フグ", "カワハギ", "マダイ", "シロギス",
    "イサキ", "ヤリイカ", "スルメイカ", "マダコ", "カサゴ",
    "ワラサ", "アマダイ", "ヒラメ", "マゴチ", "イシモチ",
    "サワラ", "マルイカ", "メダイ", "クロムツ", "キンメダイ",
]

# ── 気象データ読み込み ────────────────────────────────────────────
def load_weather_weekly():
    """weather_data/*_history.csv を週次に集計して返す。
    {week_str: {"wave_height": avg, "wind_speed": avg, "tide_range": avg}}
    """
    daily = {}  # date_str -> {wave_height, wind_speed, tide_range}
    for fname in os.listdir(WEATHER_DIR):
        if not fname.endswith("_history.csv"):
            continue
        path = os.path.join(WEATHER_DIR, fname)
        with open(path, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                d = row.get("date", "")
                if not d:
                    continue
                wh = _float(row.get("wave_height"))
                ws = _float(row.get("wind_speed"))
                tr = _float(row.get("tide_range"))
                if d not in daily:
                    daily[d] = {"wave_height": [], "wind_speed": [], "tide_range": []}
                if wh is not None: daily[d]["wave_height"].append(wh)
                if ws is not None: daily[d]["wind_speed"].append(ws)
                if tr is not None: daily[d]["tide_range"].append(tr)

    # 日次 → 週次に集計
    weekly = {}
    for d, vals in daily.items():
        try:
            dt = datetime.strptime(d, "%Y-%m-%d")
        except ValueError:
            continue
        iso = dt.isocalendar()
        wk = f"{iso[0]}/W{iso[1]:02d}"
        if wk not in weekly:
            weekly[wk] = {"wave_height": [], "wind_speed": [], "tide_range": []}
        for k in ("wave_height", "wind_speed", "tide_range"):
            weekly[wk][k].extend(vals[k])

    # 平均化
    result = {}
    for wk, vals in weekly.items():
        result[wk] = {
            k: round(sum(v)/len(v), 2) if v else None
            for k, v in vals.items()
        }
    return result


def _float(s):
    try: return float(s)
    except: return None


# ── ベースライン予測 ──────────────────────────────────────────────
def year_week(wk_str):
    """'2025/W13' -> (2025, 13)"""
    y, w = wk_str.split("/W")
    return int(y), int(w)


def prev_year_week(wk_str):
    y, w = year_week(wk_str)
    return f"{y-1}/W{w:02d}"


def mape(predicted, actual):
    if actual == 0:
        return None
    return abs(predicted - actual) / actual * 100


# ── 単純線形回帰（外部ライブラリなし） ────────────────────────────
def simple_regression(xs, ys):
    """xs, ys: float list. returns (slope, intercept)"""
    n = len(xs)
    if n < 3:
        return 0.0, sum(ys)/n if n else 0.0
    sx = sum(xs); sy = sum(ys)
    sxx = sum(x*x for x in xs); sxy = sum(x*y for x,y in zip(xs,ys))
    denom = n*sxx - sx*sx
    if denom == 0:
        return 0.0, sy/n
    slope = (n*sxy - sx*sy) / denom
    intercept = (sy - slope*sx) / n
    return slope, intercept


def weather_coefficient(weather_weekly, fish_records):
    """
    fish_records: list of {"week": str, "actual_ships": int, "pred_ships": int}
    気象係数（wave_height → 誤差の補正）を単純回帰で推定し、
    残差の MAPE を返す。
    """
    # wave_height と ratio (actual/pred) の回帰
    xs, ys = [], []
    for r in fish_records:
        wk = r["week"]
        w = weather_weekly.get(wk, {})
        wh = w.get("wave_height")
        if wh is None or r["pred_ships"] == 0:
            continue
        ratio = r["actual_ships"] / r["pred_ships"]
        xs.append(wh)
        ys.append(ratio)

    if len(xs) < 5:
        return None  # データ不足

    slope, intercept = simple_regression(xs, ys)

    errors = []
    for r in fish_records:
        wk = r["week"]
        w = weather_weekly.get(wk, {})
        wh = w.get("wave_height")
        if wh is None or r["pred_ships"] == 0:
            continue
        adj_ratio = slope * wh + intercept
        adj_ratio = max(0.3, min(3.0, adj_ratio))  # クリップ
        adj_pred = r["pred_ships"] * adj_ratio
        e = mape(adj_pred, r["actual_ships"])
        if e is not None:
            errors.append(e)

    return round(sum(errors)/len(errors), 1) if errors else None


# ── メイン ───────────────────────────────────────────────────────
def evaluate_fish(weekly, fish, year_filter=None, weather_weekly=None):
    """
    year_filter: 評価対象年リスト（例: [2026]）。None なら全年。
    主指標: avg（1トリップ平均匹数）/ 副指標: ships（出船数）

    NOTE: history.json の 2023年データは history_crawl.py バックフィル
    （全ページ→ships数3〜4倍）で蓄積されており、2024年以降の daily crawler
    データとは集計方法が異なるため、ships の昨年比比較は 2026 vs 2025 など
    同一手法の年ペアのみが信頼できる。avg は両手法間でも比較的安定。
    """
    fish_records = []
    errors_ships = []
    errors_avg = []

    target_weeks = [
        wk for wk in sorted(weekly.keys())
        if (year_filter is None or int(wk[:4]) in year_filter)
    ]

    for wk in target_weeks:
        py_wk = prev_year_week(wk)
        if py_wk not in weekly:
            continue
        if fish not in weekly[wk] or fish not in weekly[py_wk]:
            continue

        actual = weekly[wk][fish]
        pred   = weekly[py_wk][fish]

        e_ships = mape(pred["ships"], actual["ships"])
        e_avg   = mape(pred["avg"],   actual["avg"]) if actual["avg"] > 0 and pred["avg"] > 0 else None

        if e_ships is not None:
            errors_ships.append(e_ships)
        if e_avg is not None:
            errors_avg.append(e_avg)

        fish_records.append({
            "week":         wk,
            "actual_ships": actual["ships"],
            "pred_ships":   pred["ships"],
            "actual_avg":   actual["avg"],
            "pred_avg":     pred["avg"],
        })

    mape_ships = round(sum(errors_ships)/len(errors_ships), 1) if errors_ships else None
    mape_avg   = round(sum(errors_avg)/len(errors_avg), 1)     if errors_avg   else None
    mape_wx    = weather_coefficient(weather_weekly, fish_records) if weather_weekly else None

    return {
        "weeks":       len(fish_records),
        "mape_ships":  mape_ships,
        "mape_avg":    mape_avg,
        "mape_wx":     mape_wx,
        "records":     fish_records,
    }


def main():
    with open(HISTORY, encoding="utf-8") as f:
        history = json.load(f)

    weekly = history["weekly"]
    weather_weekly = load_weather_weekly()

    all_weeks = sorted(weekly.keys())
    years = sorted({int(w[:4]) for w in all_weeks})
    print(f"history.json: {len(all_weeks)}週 ({all_weeks[0]}〜{all_weeks[-1]})")
    print(f"気象週次データ: {len(weather_weekly)}週分")
    print(f"評価年: {years}")

    # ── 1. 全期間バックテスト（参考値：データ手法混在あり） ──────────
    print(f"\n[全期間 / ships MAPE ※2023年バックフィルデータ混在]")
    print(f"{'魚種':<12} {'週':>5} {'MAPE-ships':>11} {'MAPE-avg':>10}  精度(avg)")
    print("-" * 56)
    all_results = {}
    for fish in TARGET_FISH:
        r = evaluate_fish(weekly, fish, year_filter=None, weather_weekly=weather_weekly)
        if r["weeks"] == 0:
            continue
        all_results[fish] = r
        ref = r["mape_avg"] or r["mape_ships"] or 999
        label = "A" if ref < 20 else "B" if ref < 40 else "C" if ref < 70 else "D"
        s_str  = f"{r['mape_ships']:>9.1f}%" if r["mape_ships"] is not None else "       N/A"
        av_str = f"{r['mape_avg']:>8.1f}%"   if r["mape_avg"]   is not None else "      N/A"
        print(f"{fish:<12} {r['weeks']:>5}週  {s_str}  {av_str}  [{label}]")

    # ── 2. 同一手法年ペア（2025 vs 2024、2026 vs 2025） ─────────────
    # NOTE: 2023年データは history_crawl.py バックフィル（全ページ）のため
    # ships 数が 3〜4倍になっており 2024年以降と比較不可。
    # 2024/2025/2026 は daily crawler で統一されており信頼できる。
    # history_crawl.py 完了後は 2024年以前も正規化される予定。
    reliable_years = [2025, 2026]
    results_reliable = {}
    all_avg_e = []
    all_s_e = []

    print(f"\n[信頼性の高い年ペア（2025 vs 2024、2026 vs 2025）/ 同一手法]")
    print(f"{'魚種':<12} {'週':>5} {'MAPE-ships':>11} {'MAPE-avg':>10}  精度(avg)")
    print("-" * 56)

    for fish in TARGET_FISH:
        r = evaluate_fish(weekly, fish, year_filter=reliable_years, weather_weekly=weather_weekly)
        if r["weeks"] == 0:
            continue
        results_reliable[fish] = r
        ref = r["mape_avg"] or r["mape_ships"] or 999
        label = "A" if ref < 20 else "B" if ref < 40 else "C" if ref < 70 else "D"
        s_str  = f"{r['mape_ships']:>9.1f}%" if r["mape_ships"] is not None else "       N/A"
        av_str = f"{r['mape_avg']:>8.1f}%"   if r["mape_avg"]   is not None else "      N/A"
        wx_str = f" wx:{r['mape_wx']:.1f}%"  if r["mape_wx"]    is not None else ""
        print(f"{fish:<12} {r['weeks']:>5}週  {s_str}  {av_str}  [{label}]{wx_str}")
        if r["mape_avg"] is not None:
            all_avg_e.append(r["mape_avg"])
        if r["mape_ships"] is not None:
            all_s_e.append(r["mape_ships"])

    if all_avg_e:
        print("-" * 56)
        print(f"{'全体平均(avg)':<15}      {round(sum(all_s_e)/len(all_s_e),1):>9.1f}%  {round(sum(all_avg_e)/len(all_avg_e),1):>8.1f}%")

    # ── 出力 ──────────────────────────────────────────────────────
    output = {
        "generated_at":     datetime.now().strftime("%Y/%m/%d %H:%M"),
        "weeks_in_history": len(all_weeks),
        "weather_weeks":    len(weather_weekly),
        "note": (
            "ships MAPE は 2023年バックフィルデータ混在のため全期間値は参考値。"
            "信頼できる比較は 2025 vs 2024 / 2026 vs 2025（daily crawler 同一手法）。"
            "history_crawl.py 完了後に 2024年以前も正規化予定。"
        ),
        "all_years":      all_results,
        "reliable_years": results_reliable,
    }
    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n詳細 → {OUTPUT}")


if __name__ == "__main__":
    main()
