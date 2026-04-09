#!/usr/bin/env python3
"""
predict_count.py — 匹数・サイズ絶対値予測

analysis.sqlite の旬別ベースライン + 精度指標から
指定日の魚種・船宿別予測を行う。

気象補正はv1では行わない（旬別平均 ± MAE のみ）。
気象は Open-Meteo から取得してコンテキスト表示のみに使用。

使い方:
  python insights/predict_count.py                   # 全魚種・来週土曜・★3以上
  python insights/predict_count.py --fish アジ       # アジのみ
  python insights/predict_count.py --fish アジ --date 2026/04/12
  python insights/predict_count.py --min-stars 4     # ★4以上のみ
  python insights/predict_count.py --json-out        # JSON出力
"""

import argparse, json, os, sqlite3, sys, urllib.request
from datetime import datetime, timedelta

sys.stdout.reconfigure(encoding="utf-8")

import sys as _sys; _sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _paths import ROOT_DIR, RESULTS_DIR, DATA_DIR, NORMALIZE_DIR, OCEAN_DIR
DB_PATH  = os.path.join(RESULTS_DIR, "analysis.sqlite")

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
MARINE_URL   = "https://marine-api.open-meteo.com/v1/marine"


# ── 旬番号 ───────────────────────────────────────────────────────────────────

def decade_of(date_str: str) -> int:
    """YYYY/MM/DD または YYYY-MM-DD → 旬番号 1-36"""
    date_str = date_str.replace("-", "/")
    try:
        d = datetime.strptime(date_str, "%Y/%m/%d")
        dec = 1 if d.day <= 10 else (2 if d.day <= 20 else 3)
        return (d.month - 1) * 3 + dec
    except Exception:
        return 0


def next_saturday() -> str:
    today = datetime.today()
    days_ahead = (5 - today.weekday()) % 7
    if days_ahead == 0:
        days_ahead = 7
    return (today + timedelta(days=days_ahead)).strftime("%Y/%m/%d")


# ── ★評価 ────────────────────────────────────────────────────────────────────

def calc_stars(mape: float, n: int) -> int:
    """cnt_avg の H=7d MAPE + サンプル数 → ★1〜5"""
    if   mape < 25 and n >= 50: return 5
    elif mape < 35 and n >= 30: return 4
    elif mape < 50 and n >= 20: return 3
    elif mape < 65 and n >= 10: return 2
    else:                        return 1


# ── 気象取得（表示用のみ・予測には使わない） ────────────────────────────────

def fetch_weather_context(lat: float, lon: float, date_str: str) -> dict:
    """Open-Meteo から表示用の気象サマリーを取得。失敗時は空 dict。"""
    d     = datetime.strptime(date_str.replace("-", "/"), "%Y/%m/%d")
    start = d.strftime("%Y-%m-%d")
    wx    = {}
    try:
        params = "&".join([
            f"latitude={lat}", f"longitude={lon}",
            f"start_date={start}", f"end_date={start}",
            "hourly=wind_speed_10m,temperature_2m",
            "daily=precipitation_sum,wind_speed_10m_max",
            "timezone=Asia%2FTokyo",
        ])
        with urllib.request.urlopen(f"{FORECAST_URL}?{params}", timeout=8) as resp:
            data = json.loads(resp.read())
        daily = data.get("daily", {})
        wx["wind_max"]  = (daily.get("wind_speed_10m_max") or [None])[0]
        wx["precip"]    = (daily.get("precipitation_sum")  or [None])[0]
        hourly = data.get("hourly", {})
        temps  = [v for i, v in enumerate(hourly.get("temperature_2m", [])) if 6 <= i <= 9 and v is not None]
        wx["temp_morning"] = round(sum(temps) / len(temps), 1) if temps else None
    except Exception:
        pass
    try:
        params = "&".join([
            f"latitude={lat}", f"longitude={lon}",
            f"start_date={start}", f"end_date={start}",
            "hourly=wave_height,sea_surface_temperature",
            "timezone=Asia%2FTokyo",
        ])
        with urllib.request.urlopen(f"{MARINE_URL}?{params}", timeout=8) as resp:
            data = json.loads(resp.read())
        hourly = data.get("hourly", {})
        waves  = [v for i, v in enumerate(hourly.get("wave_height", [])) if 6 <= i <= 9 and v is not None]
        ssts   = [v for i, v in enumerate(hourly.get("sea_surface_temperature", [])) if 6 <= i <= 9 and v is not None]
        wx["wave_height"] = round(sum(waves) / len(waves), 2) if waves else None
        wx["sst"]         = round(sum(ssts)  / len(ssts),  1) if ssts  else None
    except Exception:
        pass
    return wx


# ── 1コンボ予測 ───────────────────────────────────────────────────────────────

def predict_combo(conn, fish: str, ship: str, target_date: str) -> dict | None:
    """
    旬別ベースライン ± MAE で予測する。気象補正なし（v1）。
    データ不足なら None。
    """
    dekad = decade_of(target_date)
    if not dekad:
        return None

    # 旬別ベースライン（avg_cnt_min/max も取得）
    row = conn.execute(
        "SELECT avg_cnt, avg_size, avg_kg, n, avg_cnt_min, avg_cnt_max FROM combo_decadal "
        "WHERE fish=? AND ship=? AND decade_no=?",
        (fish, ship, dekad)
    ).fetchone()

    if row:
        avg_cnt, avg_size, avg_kg, n_dekad, avg_cnt_min, avg_cnt_max = row
        fallback = False
    else:
        # 最近傍旬（±3以内）にフォールバック
        near = conn.execute(
            "SELECT decade_no, avg_cnt, avg_size, avg_kg, n, avg_cnt_min, avg_cnt_max "
            "FROM combo_decadal "
            "WHERE fish=? AND ship=? ORDER BY ABS(decade_no - ?) LIMIT 1",
            (fish, ship, dekad)
        ).fetchone()
        if not near or abs(near[0] - dekad) > 3:
            return None
        avg_cnt, avg_size, avg_kg, n_dekad = near[1], near[2], near[3], near[4]
        avg_cnt_min, avg_cnt_max = near[5], near[6]
        fallback = True

    if not avg_cnt or avg_cnt <= 0:
        return None

    # 精度メトリクス (H=7d)
    bt = {r[0]: {"mae": r[1], "mape": r[2]} for r in conn.execute(
        "SELECT metric, mae, mape FROM combo_backtest WHERE fish=? AND ship=? AND horizon=7",
        (fish, ship)
    ).fetchall()}

    cnt_mae   = (bt.get("cnt_avg")  or {}).get("mae")  or avg_cnt * 0.35
    cnt_mape  = (bt.get("cnt_avg")  or {}).get("mape") or 999.0
    size_mae  = (bt.get("size_avg") or {}).get("mae")
    size_mape = (bt.get("size_avg") or {}).get("mape")
    kg_mae    = (bt.get("kg_avg")   or {}).get("mae")
    kg_mape   = (bt.get("kg_avg")   or {}).get("mape")

    # 座標・総件数
    meta = conn.execute(
        "SELECT n_records, lat, lon FROM combo_meta WHERE fish=? AND ship=?",
        (fish, ship)
    ).fetchone()
    n_total = meta[0] if meta else n_dekad
    lat     = meta[1] if meta else None
    lon     = meta[2] if meta else None

    if n_total < 30:  # サンプル不足コンボは予測しない（統計的に意味ある下限）
        return None

    stars = calc_stars(cnt_mape, n_total)

    # ── シーズン変動リスク（船長の知見: シーズンの変わり目はブレやすい） ────────
    # 対象旬 ±2 の avg_cnt を集め、変動係数（std/mean）を計算する。
    # CV > 0.3 = 季節変わり目の可能性高 → 信頼性が落ちるため stars を1下げる。
    nearby = conn.execute(
        "SELECT avg_cnt FROM combo_decadal WHERE fish=? AND ship=? "
        "AND decade_no BETWEEN ? AND ?",
        (fish, ship, max(1, dekad - 2), min(36, dekad + 2))
    ).fetchall()
    nearby_cnts = [r[0] for r in nearby if r[0] and r[0] > 0]
    if len(nearby_cnts) >= 2:
        mn = sum(nearby_cnts) / len(nearby_cnts)
        sd = (sum((x - mn) ** 2 for x in nearby_cnts) / len(nearby_cnts)) ** 0.5
        transition_risk = round(sd / mn, 3) if mn > 0 else 0.0
    else:
        transition_risk = 0.0
    # 変動リスクが高い場合、★を1つ下げる（最低1）
    if transition_risk > 0.3:
        stars = max(1, stars - 1)

    # ── min/max 予測（初心者〜ベテランレンジ） ───────────────────────────────
    # avg_cnt_min/max が旬別データにある場合: ratio法で予測（比率を cnt_predicted に適用）
    # ない場合: cnt_predicted ± cnt_mae で信頼区間フォールバック
    if avg_cnt_min is not None and avg_cnt > 0:
        min_ratio = avg_cnt_min / avg_cnt
        cnt_lo    = round(max(0, avg_cnt * min_ratio), 1)
    else:
        cnt_lo    = round(max(0, avg_cnt - cnt_mae), 1)

    if avg_cnt_max is not None and avg_cnt > 0:
        max_ratio = avg_cnt_max / avg_cnt
        cnt_hi    = round(avg_cnt * max_ratio, 1)
    else:
        cnt_hi    = round(avg_cnt + cnt_mae, 1)

    return {
        "fish":            fish,
        "ship":            ship,
        "target_date":     target_date,
        "dekad":           dekad,
        "fallback_dekad":  fallback,
        # 予測
        "cnt_predicted":   round(avg_cnt, 1),
        "cnt_lo":          cnt_lo,   # 初心者釣果（旬別min_ratio または avg-MAE）
        "cnt_hi":          cnt_hi,   # ベテラン釣果（旬別max_ratio または avg+MAE）
        "size_predicted":  round(avg_size, 1) if avg_size else None,
        "size_lo":         round(avg_size - size_mae, 1) if avg_size and size_mae else None,
        "size_hi":         round(avg_size + size_mae, 1) if avg_size and size_mae else None,
        "kg_predicted":    round(avg_kg, 2) if avg_kg else None,
        "kg_lo":           round(max(0.0, avg_kg - kg_mae), 2) if avg_kg and kg_mae else None,
        "kg_hi":           round(avg_kg + kg_mae, 2) if avg_kg and kg_mae else None,
        # 精度
        "cnt_mape":        round(cnt_mape, 1),
        "size_mape":       round(size_mape, 1) if size_mape else None,
        "kg_mape":         round(kg_mape, 1) if kg_mape else None,
        "stars":           stars,
        # シーズン変動リスク（0.0〜1.0+、0.3超で変動期判定）
        "transition_risk": transition_risk,
        # メタ
        "n_total":         n_total,
        "n_dekad":         n_dekad,
        "lat":             lat,
        "lon":             lon,
    }


# ── 全コンボ予測（外部から呼ぶ用） ──────────────────────────────────────────

def predict_all(fish: str = None, target_date: str = None,
                min_stars: int = 1) -> list[dict]:
    """
    全コンボ（または指定魚種）の予測リストを返す。
    crawler.py から呼び出す用。
    """
    if not target_date:
        target_date = next_saturday()

    conn = sqlite3.connect(DB_PATH)
    try:
        if fish:
            combos = conn.execute(
                "SELECT DISTINCT fish, ship FROM combo_decadal WHERE fish=? ORDER BY ship",
                (fish,)
            ).fetchall()
        else:
            combos = conn.execute(
                "SELECT DISTINCT fish, ship FROM combo_decadal ORDER BY fish, ship"
            ).fetchall()

        results = []
        for f, s in combos:
            r = predict_combo(conn, f, s, target_date)
            if r and r["stars"] >= min_stars:
                results.append(r)
    finally:
        conn.close()

    results.sort(key=lambda x: (-x["stars"], x["cnt_mape"]))
    return results


# ── メイン（CLI） ─────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="匹数・サイズ絶対値予測")
    parser.add_argument("--fish",      help="魚種名（省略=全魚種）")
    parser.add_argument("--date",      help="予測日 YYYY/MM/DD（省略=来週土曜）")
    parser.add_argument("--min-stars", type=int, default=3, help="最小★（デフォルト3）")
    parser.add_argument("--json-out",  action="store_true", help="JSON出力")
    parser.add_argument("--with-wx",   action="store_true", help="気象コンテキストも表示")
    args = parser.parse_args()

    target_date = args.date or next_saturday()
    print(f"予測日: {target_date}  旬{decade_of(target_date)}")
    print()

    results = predict_all(
        fish=args.fish,
        target_date=target_date,
        min_stars=args.min_stars,
    )

    # 気象コンテキスト取得（--with-wx 指定時）
    wx_cache = {}
    if args.with_wx:
        print("気象取得中...")
        for r in results:
            if r["lat"] and r["lon"]:
                key = (round(r["lat"], 1), round(r["lon"], 1))
                if key not in wx_cache:
                    wx_cache[key] = fetch_weather_context(r["lat"], r["lon"], target_date)

    if args.json_out:
        print(json.dumps(results, ensure_ascii=False, indent=2))
        return

    # テーブル表示
    header = f"{'魚種':<10}{'船宿':<14}{'★':<7}{'予測匹数レンジ':>13}{'サイズ':>11}{'n':>6}  MAPE"
    print(header)
    print("─" * 75)
    for r in results:
        cnt_str = f"{r['cnt_lo']:.0f}〜{r['cnt_hi']:.0f}匹"
        if r["size_predicted"] and r["size_lo"] and r["size_hi"]:
            sz_str = f"{r['size_lo']:.0f}〜{r['size_hi']:.0f}cm"
        elif r["size_predicted"]:
            sz_str = f"{r['size_predicted']:.0f}cm"
        else:
            sz_str = "---"
        stars = "★" * r["stars"] + "☆" * (5 - r["stars"])
        fb    = "~" if r["fallback_dekad"] else " "
        print(f"{r['fish']:<10}{r['ship']:<14}{stars:<7}{cnt_str:>13}{sz_str:>11}"
              f"{r['n_total']:>6}  {r['cnt_mape']:.0f}%{fb}")
        if args.with_wx and r["lat"]:
            key = (round(r["lat"], 1), round(r["lon"], 1))
            wx  = wx_cache.get(key, {})
            if wx:
                parts = []
                if wx.get("wave_height") is not None: parts.append(f"波{wx['wave_height']:.1f}m")
                if wx.get("wind_max")    is not None: parts.append(f"風{wx['wind_max']:.0f}m/s")
                if wx.get("sst")         is not None: parts.append(f"水温{wx['sst']:.1f}℃")
                if parts:
                    print(f"  {'':10}{'':14}  [{' '.join(parts)}]")

    print()
    print(f"表示: {len(results)} コンボ（★{args.min_stars}以上）  "
          f"★5:{sum(1 for r in results if r['stars']==5)}  "
          f"★4:{sum(1 for r in results if r['stars']==4)}  "
          f"★3:{sum(1 for r in results if r['stars']==3)}")


if __name__ == "__main__":
    main()
