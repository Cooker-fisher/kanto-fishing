#!/usr/bin/env python3
"""
backtest_v2.py - 日次バックテスト（気象×釣果）

[予測モデル]
  予測 = ベースライン × 気象係数 × シーズン係数

  ベースライン : history.json の昨年同週・同魚種の平均釣果
  気象係数     : 波高・風速・潮汐タイプ・水温の各ファクター（掛け算）
  シーズン係数 : SEASON_DATA のスコア（1〜5 → 0.6〜1.2 に変換）

[予測出力]
  魚種・エリア・匹数レンジ・サイズレンジ・重さレンジ・根拠説明

[バリデーション]
  data/YYYY-MM.csv の実績と比較し MAPE を計算
"""
import csv, json, os, sys
from datetime import datetime, timedelta
from collections import defaultdict

sys.stdout.reconfigure(encoding="utf-8")

BASE_DIR     = os.path.dirname(os.path.abspath(__file__))
HISTORY_FILE = os.path.join(BASE_DIR, "history.json")
AREA_MAP     = os.path.join(BASE_DIR, "area_weather_map.json")
WEATHER_DIR  = os.path.join(BASE_DIR, "weather_data")
DATA_DIR     = os.path.join(BASE_DIR, "data")

# ── シーズンデータ（crawler.py と同じ） ────────────────────────────
SEASON_DATA = {
    "アジ":     [3,3,3,4,4,5,5,4,4,4,4,3],
    "タチウオ": [1,1,1,1,2,3,5,5,5,4,3,2],
    "フグ":     [3,3,4,4,3,2,2,2,3,4,4,3],
    "カワハギ": [2,2,2,2,2,2,3,4,5,5,4,3],
    "マダイ":   [2,2,3,5,5,4,3,3,3,4,4,3],
    "シロギス": [1,1,2,3,5,5,5,4,3,2,1,1],
    "イサキ":   [1,1,2,3,4,5,5,4,3,2,1,1],
    "ヤリイカ": [4,4,3,2,2,2,2,2,2,3,4,5],
    "スルメイカ":[1,1,1,2,3,4,5,5,4,3,2,1],
    "マダコ":   [1,1,1,2,3,5,5,5,4,3,2,1],
    "カサゴ":   [4,4,4,3,3,2,2,2,3,3,4,4],
    "メバル":   [4,4,4,3,3,2,2,2,2,3,4,4],
    "ワラサ":   [2,2,2,2,3,3,4,4,5,5,4,3],
    "ヒラメ":   [4,4,3,3,3,3,3,3,4,5,5,4],
    "アマダイ": [3,3,3,3,3,3,3,3,4,4,4,4],
    "マゴチ":   [1,1,1,2,4,5,5,5,4,2,1,1],
    "キンメダイ":[4,4,4,3,3,3,3,3,3,4,4,4],
    "マルイカ": [2,3,4,5,5,3,1,1,1,1,1,2],
    "クロムツ": [4,4,3,3,3,3,3,3,3,3,4,4],
    "サワラ":   [1,1,2,4,5,3,2,2,4,5,4,2],
    "メダイ":   [4,5,5,4,3,2,1,1,1,2,3,4],
    "マハタ":   [3,3,3,3,4,4,4,4,4,3,3,3],
    "カンパチ": [1,1,1,2,3,4,5,5,4,3,2,1],
}

# ── 気象係数ルール ─────────────────────────────────────────────────

def wave_factor(wh):
    """波高(m) → 釣果係数 & 説明"""
    if wh is None:   return 1.0, "波高不明"
    if wh < 0.5:     return 1.05, f"波高{wh:.1f}m（べた凪・好条件）"
    if wh < 1.0:     return 1.0,  f"波高{wh:.1f}m（平水）"
    if wh < 1.5:     return 0.95, f"波高{wh:.1f}m（やや波あり）"
    if wh < 2.0:     return 0.80, f"波高{wh:.1f}m（波高め・釣果減）"
    if wh < 2.5:     return 0.65, f"波高{wh:.1f}m（荒れ気味・要注意）"
    return              0.45, f"波高{wh:.1f}m（出船困難クラス）"

def wind_factor(ws):
    """風速(m/s) → 釣果係数 & 説明"""
    if ws is None:   return 1.0, "風速不明"
    if ws < 5:       return 1.0,  f"風速{ws:.1f}m/s（微風）"
    if ws < 8:       return 1.0,  f"風速{ws:.1f}m/s（穏やか）"
    if ws < 12:      return 0.92, f"風速{ws:.1f}m/s（やや強風）"
    if ws < 15:      return 0.75, f"風速{ws:.1f}m/s（強風・釣りにくい）"
    return              0.55, f"風速{ws:.1f}m/s（出船困難クラス）"

def tide_factor(tide_type):
    """潮汐タイプ → 釣果係数 & 説明"""
    table = {
        "大潮": (1.12, "大潮（魚の活性UP・期待大）"),
        "中潮": (1.05, "中潮（標準的な活性）"),
        "小潮": (0.92, "小潮（活性やや低め）"),
        "長潮": (0.88, "長潮（潮動かず・苦戦しやすい）"),
        "若潮": (0.92, "若潮（回復途上・やや低め）"),
    }
    if tide_type in table:
        return table[tide_type]
    return 1.0, f"潮汐不明({tide_type})"

def temp_factor(sst, month):
    """海水温 → 釣果係数 & 説明（季節平均との乖離で補正）"""
    # 東京湾・相模湾の月別平均水温（概算）
    MONTHLY_AVG = [15,14,15,17,19,22,25,27,26,23,20,17]
    if sst is None or month is None:
        return 1.0, "水温不明"
    avg = MONTHLY_AVG[month - 1]
    diff = sst - avg
    if diff > 3:     factor, note = 1.05, f"水温{sst:.1f}°C（平年+{diff:.1f}°・やや高め）"
    elif diff > 1:   factor, note = 1.02, f"水温{sst:.1f}°C（平年+{diff:.1f}°・適温域）"
    elif diff > -1:  factor, note = 1.0,  f"水温{sst:.1f}°C（平年並み）"
    elif diff > -3:  factor, note = 0.97, f"水温{sst:.1f}°C（平年{diff:.1f}°・やや低め）"
    else:            factor, note = 0.92, f"水温{sst:.1f}°C（平年{diff:.1f}°・低水温）"
    return factor, note

def season_factor(fish, month):
    """シーズンスコア(1〜5) → 釣果係数 & 説明"""
    scores = SEASON_DATA.get(fish, [3]*12)
    score  = scores[month - 1]
    table  = {5: (1.20, "旬（ピーク期）"), 4: (1.10, "好期"), 3: (1.0, "普通期"),
              2: (0.80, "やや低調期"), 1: (0.60, "オフシーズン")}
    f, note = table.get(score, (1.0, ""))
    return f, f"{fish} {note}"

# ── データ読み込み ─────────────────────────────────────────────────

def load_weather():
    """weather_data/*_history.csv → {area_code: {date_str: row}}"""
    idx = {}
    for fname in os.listdir(WEATHER_DIR):
        if not fname.endswith("_history.csv"):
            continue
        code = fname.replace("_history.csv", "")
        idx[code] = {}
        with open(os.path.join(WEATHER_DIR, fname), encoding="utf-8") as f:
            for row in csv.DictReader(f):
                idx[code][row["date"]] = row
    return idx

def load_area_map():
    raw = json.load(open(AREA_MAP, encoding="utf-8"))
    return {k: v for k, v in raw.items() if not k.startswith("_")}

def load_history():
    return json.load(open(HISTORY_FILE, encoding="utf-8"))

def load_daily_catches():
    """data/YYYY-MM.csv → {date: {area: {fish: [cnt_avg, ...]}}}"""
    result = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    if not os.path.isdir(DATA_DIR):
        return result
    for fname in os.listdir(DATA_DIR):
        if not fname.endswith(".csv"):
            continue
        with open(os.path.join(DATA_DIR, fname), encoding="utf-8") as f:
            for row in csv.DictReader(f):
                date = row.get("date", "")
                area = row.get("area", "")
                fish = row.get("fish", "")
                try:
                    avg = float(row["cnt_avg"])
                except (ValueError, KeyError):
                    continue
                if avg > 0 and date and area and fish:
                    result[date][area][fish].append(avg)
    return result

def date_to_week(date_str):
    """'2026/03/25' → '2026/W13'"""
    dt = datetime.strptime(date_str, "%Y/%m/%d")
    iso = dt.isocalendar()
    return f"{iso[0]}/W{iso[1]:02d}"

def date_to_weather_key(date_str):
    """'2026/03/25' → '2026-03-25'"""
    return date_str.replace("/", "-")

def prev_year_week(wk):
    y, w = wk.split("/W")
    return f"{int(y)-1}/W{w}"

def _float(s):
    try: return float(s)
    except: return None

# ── 予測エンジン ───────────────────────────────────────────────────

def predict(fish, area, date_str, history_weekly, weather_row):
    """
    1日・1魚種・1エリアの予測を返す。

    Returns:
        dict:
            baseline    : 昨年同週の avg (None なら予測不可)
            predicted   : 予測 avg
            cnt_min     : 予測下限
            cnt_max     : 予測上限
            factors     : [(factor_name, coefficient, description), ...]
            reasons     : 説明文リスト
    """
    wk      = date_to_week(date_str)
    py_wk   = prev_year_week(wk)
    month   = int(date_str[5:7])

    # ベースライン
    baseline_data = history_weekly.get(py_wk, {}).get(fish)
    if not baseline_data or baseline_data.get("avg", 0) == 0:
        return None
    baseline  = baseline_data["avg"]
    size_base = baseline_data.get("size_avg", 0)
    wt_base   = baseline_data.get("weight_avg", 0)

    # 気象係数
    wh  = _float(weather_row.get("wave_height"))   if weather_row else None
    ws  = _float(weather_row.get("wind_speed"))    if weather_row else None
    sst = _float(weather_row.get("sea_surface_temp")) if weather_row else None
    tt  = weather_row.get("tide_type", "")         if weather_row else ""
    ma  = _float(weather_row.get("moon_age"))      if weather_row else None

    f_wave,   d_wave   = wave_factor(wh)
    f_wind,   d_wind   = wind_factor(ws)
    f_tide,   d_tide   = tide_factor(tt)
    f_temp,   d_temp   = temp_factor(sst, month)
    f_season, d_season = season_factor(fish, month)

    factors = [
        ("wave",   f_wave,   d_wave),
        ("wind",   f_wind,   d_wind),
        ("tide",   f_tide,   d_tide),
        ("temp",   f_temp,   d_temp),
        ("season", f_season, d_season),
    ]

    wx_coef   = f_wave * f_wind * f_tide * f_temp * f_season
    predicted = round(baseline * wx_coef, 1)
    cnt_min   = round(predicted * 0.60)
    cnt_max   = round(predicted * 1.40)

    # サイズ・重さレンジ（気象係数は適用せず、ベースラインのまま）
    size_min = round(size_base * 0.85) if size_base > 0 else None
    size_max = round(size_base * 1.15) if size_base > 0 else None
    wt_min   = round(wt_base  * 0.75, 2) if wt_base > 0 else None
    wt_max   = round(wt_base  * 1.25, 2) if wt_base > 0 else None

    # 根拠文
    reasons = [
        f"昨年同週({py_wk})の {fish} 平均: {baseline:.1f}匹",
        f"気象補正 ×{wx_coef:.2f} = {predicted:.1f}匹 予測",
    ]
    for name, coef, desc in factors:
        sign = "↑" if coef > 1.0 else ("↓" if coef < 1.0 else "→")
        reasons.append(f"  {sign} {desc} (×{coef:.2f})")
    if ma is not None:
        reasons.append(f"  ℹ 月齢: {ma:.1f}")

    return {
        "baseline":  baseline,
        "predicted": predicted,
        "cnt_min":   cnt_min,
        "cnt_max":   cnt_max,
        "size_min":  size_min,
        "size_max":  size_max,
        "wt_min":    wt_min,
        "wt_max":    wt_max,
        "wx_coef":   round(wx_coef, 3),
        "factors":   [(n, c, d) for n, c, d in factors],
        "reasons":   reasons,
    }

# ── MAPE 計算 ─────────────────────────────────────────────────────

def mape(pred, actual):
    if actual == 0: return None
    return abs(pred - actual) / actual * 100

# ── メイン ────────────────────────────────────────────────────────

def main():
    history   = load_history()
    weekly    = history["weekly"]
    weather   = load_weather()
    area_map  = load_area_map()
    catches   = load_daily_catches()

    n_dates = len(catches)
    print(f"釣果データ: {n_dates}日分")
    print(f"気象エリア: {list(weather.keys())}")
    print()

    # ── バリデーション ────────────────────────────────────────────
    # 各 (date, area, fish) の予測と実績を比較
    records = []   # {date, area, fish, pred, actual, error, result}

    for date_str in sorted(catches.keys()):
        wkey = date_to_weather_key(date_str)
        month = int(date_str[5:7])

        for area, fish_dict in catches[date_str].items():
            wx_code = area_map.get(area)
            wx_row  = weather.get(wx_code, {}).get(wkey) if wx_code else None

            for fish, avgs in fish_dict.items():
                if not avgs:
                    continue
                actual_avg = sum(avgs) / len(avgs)

                result = predict(fish, area, date_str, weekly, wx_row)
                if result is None:
                    continue

                e = mape(result["predicted"], actual_avg)
                records.append({
                    "date":       date_str,
                    "area":       area,
                    "fish":       fish,
                    "actual":     round(actual_avg, 1),
                    "predicted":  result["predicted"],
                    "cnt_min":    result["cnt_min"],
                    "cnt_max":    result["cnt_max"],
                    "error":      round(e, 1) if e is not None else None,
                    "in_range":   result["cnt_min"] <= actual_avg <= result["cnt_max"] if e is not None else None,
                    "wx_coef":    result["wx_coef"],
                    "result":     result,
                })

    if not records:
        print("バリデーション対象データなし")
        return

    # ── 魚種別集計 ────────────────────────────────────────────────
    from collections import defaultdict
    fish_stats = defaultdict(lambda: {"errors": [], "in_range": [], "n": 0})
    for r in records:
        if r["error"] is not None:
            fish_stats[r["fish"]]["errors"].append(r["error"])
            fish_stats[r["fish"]]["in_range"].append(r["in_range"])
            fish_stats[r["fish"]]["n"] += 1

    print(f"{'魚種':<12} {'件数':>5} {'MAPE':>8} {'レンジ的中':>10}  精度")
    print("-" * 50)
    all_errors = []
    all_in_range = []
    for fish in sorted(fish_stats, key=lambda f: -len(fish_stats[f]["errors"])):
        st = fish_stats[fish]
        errs = st["errors"]
        inr  = st["in_range"]
        mape_val = round(sum(errs) / len(errs), 1)
        hit_rate = round(sum(inr) / len(inr) * 100, 1)
        label = "A" if mape_val < 30 else "B" if mape_val < 50 else "C" if mape_val < 80 else "D"
        print(f"{fish:<12} {len(errs):>5}件  {mape_val:>6.1f}%  {hit_rate:>8.1f}%  [{label}]")
        all_errors.extend(errs)
        all_in_range.extend(inr)

    print("-" * 50)
    if all_errors:
        ov_mape = round(sum(all_errors) / len(all_errors), 1)
        ov_hit  = round(sum(all_in_range) / len(all_in_range) * 100, 1)
        print(f"{'全体':<12} {len(all_errors):>5}件  {ov_mape:>6.1f}%  {ov_hit:>8.1f}%")

    # ── 予測例（最新5日分・上位魚種） ─────────────────────────────
    print(f"\n{'='*60}")
    print("予測例（直近データ）")
    print("="*60)

    recent = sorted(records, key=lambda r: r["date"], reverse=True)
    shown = set()
    count = 0
    for r in recent:
        key = (r["date"], r["fish"])
        if key in shown or count >= 10:
            break
        shown.add(key)
        count += 1
        res = r["result"]
        hit = "✓ 的中" if r["in_range"] else "✗ 外れ"
        print(f"\n📅 {r['date']} | {r['area']} | {r['fish']}")
        print(f"   予測: {r['cnt_min']}〜{r['cnt_max']}匹 (avg {r['predicted']})")
        if res["size_min"]:
            print(f"   サイズ: {res['size_min']}〜{res['size_max']}cm")
        if res["wt_min"]:
            print(f"   重さ: {res['wt_min']}〜{res['wt_max']}kg")
        print(f"   実績: {r['actual']}匹  誤差: {r['error']}%  {hit}")
        print(f"   気象補正: ×{r['wx_coef']}")
        for reason in res["reasons"]:
            print(f"   {reason}")

    # ── JSON出力 ─────────────────────────────────────────────────
    out = {
        "generated_at": datetime.now().strftime("%Y/%m/%d %H:%M"),
        "validation_days": n_dates,
        "total_records": len(records),
        "overall_mape": round(sum(all_errors)/len(all_errors), 1) if all_errors else None,
        "overall_hit_rate": round(sum(all_in_range)/len(all_in_range)*100, 1) if all_in_range else None,
        "fish_stats": {
            f: {
                "n": s["n"],
                "mape": round(sum(s["errors"])/len(s["errors"]),1) if s["errors"] else None,
                "hit_rate": round(sum(s["in_range"])/len(s["in_range"])*100,1) if s["in_range"] else None,
            }
            for f, s in fish_stats.items()
        },
        "records": [
            {k: v for k, v in r.items() if k != "result"}
            for r in records
        ],
    }
    with open("backtest_v2_result.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"\n詳細 → backtest_v2_result.json")


if __name__ == "__main__":
    main()
