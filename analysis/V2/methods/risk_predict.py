#!/usr/bin/env python3
"""
risk_predict.py — 今後7日間の釣りリスク予測

[リスク種別]
  出船中止リスク  船宿別実閾値（cancel_thresholds）を使用
  釣りづらさ      閾値の50%超過で判定
  不漁リスク      combo_wx_params × 予報値 → 負方向

[データ]
  forecast_cache.sqlite : 153座標×8日間の予報（weather_forecast.py が生成）
  insights/analysis.sqlite: cancel_thresholds, combo_wx_params, combo_meta

[出力]
  insights/risk_forecast.txt  魚種×日付別リスクサマリー
  insights/risk_weekend.txt   来週末（土日）フォーカス版

[使い方]
  python insights/risk_predict.py
"""
import json, os, sqlite3, math
from collections import defaultdict
from datetime import datetime, timedelta, date

BASE_DIR      = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR      = os.path.dirname(BASE_DIR)
DB_FORECAST   = os.path.join(ROOT_DIR, "forecast_cache.sqlite")
DB_ANA        = os.path.join(BASE_DIR, "analysis.sqlite")
OUT_ALL       = os.path.join(BASE_DIR, "risk_forecast.txt")
OUT_WEEKEND   = os.path.join(BASE_DIR, "risk_weekend.txt")
NORMALIZE_DIR = os.path.join(ROOT_DIR, "normalize")
OVERRIDE_FILE = os.path.join(NORMALIZE_DIR, "ship_wx_coord_override.json")

# グローバルフォールバック閾値（cancel_thresholds に該当船宿がない場合）
DEFAULT_CANCEL_WAVE  = 1.64   # 全船宿中央値
DEFAULT_CANCEL_WIND  = 20.0   # 全船宿中央値近傍
DEFAULT_HARD_WAVE    = DEFAULT_CANCEL_WAVE * 0.6
DEFAULT_HARD_WIND    = DEFAULT_CANCEL_WIND * 0.6

FACTORS = ["sst", "temp", "wave_height", "wind_speed", "pressure"]

# ── ユーティリティ ─────────────────────────────────────────────────────────
def nearest_coord(lat, lon, coords):
    return min(coords, key=lambda c: (c[0]-lat)**2 + (c[1]-lon)**2)

# ── データロード ──────────────────────────────────────────────────────────
def load_forecast_coords():
    """forecast_cache の全座標リスト（新形式 lat_lon のみ）"""
    conn = sqlite3.connect(DB_FORECAST)
    try:
        # area が "lat_lon" 形式のレコードのみ対象（旧エリア名形式を除外）
        coords = conn.execute(
            "SELECT DISTINCT lat, lon FROM forecast WHERE area LIKE '__.__%' OR area LIKE '_.__%'"
        ).fetchall()
        if not coords:
            # フォールバック：全座標
            coords = conn.execute("SELECT DISTINCT lat, lon FROM forecast").fetchall()
    except Exception:
        coords = []
    conn.close()
    return coords  # [(lat, lon), ...]

def load_forecast_by_coord(lat, lon):
    """指定座標の全日程予報 {date: {factor: value}}"""
    conn = sqlite3.connect(DB_FORECAST)
    rows = conn.execute("""
        SELECT date, wind_speed, wind_dir, temp, pressure,
               wave_height, wave_period, swell_height, sst
        FROM forecast WHERE lat=? AND lon=? ORDER BY date
    """, (lat, lon)).fetchall()
    conn.close()
    result = {}
    for d, wind_spd, wind_dir, temp, pres, wave_h, wave_p, swell, sst in rows:
        result[d] = {
            "wind_speed":   wind_spd,
            "wind_dir":     wind_dir,
            "temp":         temp,
            "pressure":     pres,
            "wave_height":  wave_h,
            "wave_period":  wave_p,
            "swell_height": swell,
            "sst":          sst,
        }
    return result

def load_wx_overrides():
    """ship_wx_coord_override.json から湾内船宿の座標オーバーライドを読み込む"""
    try:
        with open(OVERRIDE_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return {ship: (info["lat"], info["lon"])
                for ship, info in data.get("overrides", {}).items()}
    except Exception:
        return {}

def load_ship_info():
    """
    ship -> {lat, lon, wave_thr, wind_thr, cancel_wave_avg, ok_wave_avg, n_cancel}
    combo_meta から座標、cancel_thresholds から実閾値を結合
    湾内船宿は ship_wx_coord_override.json の座標を優先
    """
    conn = sqlite3.connect(DB_ANA)
    # 船宿ごとの代表座標
    coords = {}
    for ship, lat, lon in conn.execute(
        "SELECT ship, AVG(lat), AVG(lon) FROM combo_meta WHERE lat IS NOT NULL GROUP BY ship"
    ).fetchall():
        coords[ship] = {"lat": lat, "lon": lon}

    # 湾内船宿の座標オーバーライドを適用
    overrides = load_wx_overrides()
    for ship, (lat, lon) in overrides.items():
        if ship in coords:
            coords[ship] = {"lat": lat, "lon": lon}
        else:
            coords[ship] = {"lat": lat, "lon": lon}

    # 実閾値（cancel_thresholds）
    thresholds = {}
    try:
        for row in conn.execute(
            "SELECT ship, wave_threshold, wind_threshold, cancel_wave_avg, ok_wave_avg, n_cancel FROM cancel_thresholds"
        ).fetchall():
            ship, wave_thr, wind_thr, cw_avg, ok_avg, nc = row
            thresholds[ship] = {
                "wave_thr": wave_thr,
                "wind_thr": wind_thr,
                "cancel_wave_avg": cw_avg,
                "ok_wave_avg": ok_avg,
                "n_cancel": nc,
            }
    except Exception:
        pass

    conn.close()

    # 結合
    ships = {}
    for ship, cinfo in coords.items():
        tinfo = thresholds.get(ship, {})
        ships[ship] = {
            "lat": cinfo["lat"],
            "lon": cinfo["lon"],
            "wave_thr":   tinfo.get("wave_thr", DEFAULT_CANCEL_WAVE),
            "wind_thr":   tinfo.get("wind_thr", DEFAULT_CANCEL_WIND),
            "n_cancel":   tinfo.get("n_cancel", 0),
            "has_real_thr": ship in thresholds,
        }
    return ships

def load_combo_params():
    """combo_wx_params: {(fish, ship): [(factor, r, hist_mean, hist_std), ...]}"""
    conn = sqlite3.connect(DB_ANA)
    rows = conn.execute(
        "SELECT fish, ship, factor, r, hist_mean, hist_std FROM combo_wx_params"
    ).fetchall()
    conn.close()
    combo_wx = defaultdict(list)
    for fish, ship, fac, r, m, s in rows:
        combo_wx[(fish, ship)].append((fac, r, m, s))
    return combo_wx

# ── リスク計算 ─────────────────────────────────────────────────────────────
def sea_risk(wx, wave_thr, wind_thr):
    """
    海況リスクレベルを返す: (level, reason)  level=0-3
    wave_thr/wind_thr: 船宿別実閾値
    """
    wave = wx.get("wave_height") or 0
    wind = wx.get("wind_speed") or 0
    wave_thr = wave_thr or DEFAULT_CANCEL_WAVE
    wind_thr = wind_thr or DEFAULT_CANCEL_WIND
    hard_wave = wave_thr * 0.65
    hard_wind = wind_thr * 0.65

    if wave >= wave_thr or wind >= wind_thr:
        return 3, f"波高{wave:.1f}m/{wave_thr:.1f}m閾値 / 風速{wind:.1f}m/{wind_thr:.0f}m/s閾値 → 出船中止リスク"
    if wave >= hard_wave or wind >= hard_wind:
        return 2, f"波高{wave:.1f}m / 風速{wind:.1f}m/s → 釣りづらい"
    if wave >= hard_wave * 0.7:
        return 1, f"波高{wave:.1f}m → やや荒れ気味"
    return 0, f"波高{wave:.1f}m → 良好"

def catch_risk(params, wx):
    """
    combo_wx_params × 予報値 で不漁スコアを計算。
    負値が大きいほど不漁リスク高。
    """
    contributions = []
    for fac, r, hist_mean, hist_std in params:
        val = wx.get(fac)
        if val is None or hist_std == 0:
            continue
        z = (val - hist_mean) / hist_std
        contributions.append((fac, r, z, r * z))
    if not contributions:
        return 0.0, []
    score = sum(c[3] for c in contributions) / len(contributions)
    return score, contributions

def risk_label(sea_lv, catch_sc):
    """総合リスクラベル"""
    if sea_lv >= 3:
        return "🔴 出船中止", "出船中止"
    if sea_lv == 2 and catch_sc < -0.3:
        return "🔴 荒天×不漁", "荒天かつ不漁"
    if sea_lv == 2:
        return "🟠 釣りづらい", "荒天"
    if catch_sc < -0.4:
        return "🟠 不漁リスク", "海況不利"
    if catch_sc < -0.2:
        return "🟡 やや不利", "海況やや不利"
    if catch_sc > 0.3:
        return "🟢 好条件", "海況有利"
    return "⚪ 普通", ""

# ── 出力フォーマット ──────────────────────────────────────────────────────
def write_forecast(ships, combo_wx, forecast_coords, out_path, target_dates=None):
    """
    ships: {ship: {lat, lon, wave_thr, wind_thr, ...}}
    combo_wx: {(fish, ship): [(fac, r, mean, std), ...]}
    forecast_coords: [(lat, lon), ...]
    """
    # 全日程収集（最初の船宿の予報から取得）
    all_dates = set()
    if forecast_coords:
        sample_lat, sample_lon = forecast_coords[0]
        sample_fc = load_forecast_by_coord(sample_lat, sample_lon)
        all_dates = set(sample_fc.keys())

    if target_dates:
        all_dates = {d for d in all_dates if d in target_dates}
    all_dates = sorted(all_dates)

    if not all_dates:
        print(f"予報データなし: {out_path}")
        return

    # 船宿×日付のリスク辞書 & コンボキャッシュ
    # (fish, ship) -> {date: (sea_lv, catch_sc)}
    combo_risks = defaultdict(dict)

    print(f"  船宿ごとにリスク計算中（{len(ships)}船宿 × {len(all_dates)}日）...")
    for ship, sinfo in ships.items():
        slat, slon = sinfo["lat"], sinfo["lon"]
        wlat, wlon = nearest_coord(slat, slon, forecast_coords)
        fc = load_forecast_by_coord(wlat, wlon)

        wave_thr = sinfo["wave_thr"]
        wind_thr = sinfo["wind_thr"]

        # この船宿が参加するコンボを取得
        ship_combos = {fish: params for (fish, s), params in combo_wx.items() if s == ship}

        for d in all_dates:
            wx = fc.get(d, {})
            if not wx:
                continue
            sea_lv, _ = sea_risk(wx, wave_thr, wind_thr)
            for fish, params in ship_combos.items():
                catch_sc, _ = catch_risk(params, wx)
                combo_risks[(fish, ship)][d] = (sea_lv, catch_sc)

    # 日付別サマリー出力
    lines = [
        "# 釣りリスク予報（船宿別実閾値使用）",
        f"# 生成: {datetime.now().strftime('%Y/%m/%d %H:%M')}",
        f"# 対象日: {all_dates[0]} 〜 {all_dates[-1]}",
        f"# 実閾値適用船宿: {sum(1 for s in ships.values() if s['has_real_thr'])}件 / "
        f"フォールバック: {sum(1 for s in ships.values() if not s['has_real_thr'])}件",
        "",
    ]

    # 魚種×日付のリスク集計
    # 各日付について: 魚種ごとに全コンボのリスクを集約
    for d in all_dates:
        dt = datetime.strptime(d, "%Y-%m-%d")
        weekday = ["月","火","水","木","金","土","日"][dt.weekday()]
        is_weekend = dt.weekday() >= 5
        mark = " ★週末★" if is_weekend else ""
        lines.append(f"\n{'='*65}")
        lines.append(f"【{d}（{weekday}）{mark}】")

        # 魚種別集計
        fish_summary = defaultdict(lambda: {"cancel_ships": [], "bad_ships": [], "good_ships": [], "all_scores": []})
        for (fish, ship), day_risks in combo_risks.items():
            if d not in day_risks:
                continue
            sea_lv, catch_sc = day_risks[d]
            label, reason = risk_label(sea_lv, catch_sc)
            fish_summary[fish]["all_scores"].append(catch_sc)
            if sea_lv >= 3:
                fish_summary[fish]["cancel_ships"].append(ship)
            elif sea_lv >= 2 or catch_sc < -0.2:
                fish_summary[fish]["bad_ships"].append(ship)
            elif catch_sc > 0.3:
                fish_summary[fish]["good_ships"].append(ship)

        # 欠航リスク高い順
        cancel_fish = [(f, v) for f, v in fish_summary.items() if v["cancel_ships"]]
        bad_fish    = [(f, v) for f, v in fish_summary.items() if not v["cancel_ships"] and v["bad_ships"]]
        good_fish   = [(f, v) for f, v in fish_summary.items() if v["good_ships"] and not v["cancel_ships"]]

        cancel_fish.sort(key=lambda x: -len(x[1]["cancel_ships"]))
        bad_fish.sort(key=lambda x: -(len(x[1]["bad_ships"])))
        good_fish.sort(key=lambda x: (
            -len(x[1]["good_ships"]),
            -(sum(x[1]["all_scores"])/len(x[1]["all_scores"]) if x[1]["all_scores"] else 0)
        ))

        if cancel_fish:
            lines.append("  ▼ 出船中止リスク")
            for fish, v in cancel_fish[:8]:
                avg_sc = sum(v["all_scores"])/len(v["all_scores"]) if v["all_scores"] else 0
                lines.append(
                    f"    🔴 {fish:10} 中止リスク船宿{len(v['cancel_ships'])}件"
                    f" | 例:{','.join(v['cancel_ships'][:3])}"
                    f"  catch_sc={avg_sc:+.2f}"
                )

        if bad_fish:
            lines.append("  ▼ 釣りづらい / 不漁リスク")
            for fish, v in bad_fish[:8]:
                avg_sc = sum(v["all_scores"])/len(v["all_scores"]) if v["all_scores"] else 0
                lines.append(
                    f"    🟠 {fish:10} {len(v['bad_ships'])}船宿"
                    f" | 例:{','.join(v['bad_ships'][:3])}"
                    f"  catch_sc={avg_sc:+.2f}"
                )

        if good_fish:
            lines.append("  ▼ 好条件")
            for fish, v in good_fish[:5]:
                avg_sc = sum(v["all_scores"])/len(v["all_scores"]) if v["all_scores"] else 0
                lines.append(
                    f"    🟢 {fish:10} {len(v['good_ships'])}船宿好調"
                    f" | 例:{','.join(v['good_ships'][:3])}"
                    f"  catch_sc={avg_sc:+.2f}"
                )

        if not cancel_fish and not bad_fish and not good_fish:
            lines.append("  ⚪ 特筆すべきリスクなし（普通の海況）")

    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"保存: {out_path}")

def main():
    print("=== risk_predict.py 開始 ===")

    # 予報データ確認
    try:
        conn = sqlite3.connect(DB_FORECAST)
        n_fc = conn.execute("SELECT COUNT(*) FROM forecast").fetchone()[0]
        fc_coords = conn.execute("SELECT DISTINCT lat, lon FROM forecast").fetchall()
        conn.close()
        print(f"予報データ: {n_fc}件 / {len(fc_coords)}座標")
    except Exception as e:
        print(f"予報DBエラー: {e}")
        print("→ weather_forecast.py を先に実行してください")
        return

    if n_fc == 0:
        print("予報データが空です。weather_forecast.py を先に実行してください。")
        return

    ships     = load_ship_info()
    combo_wx  = load_combo_params()
    print(f"船宿: {len(ships)}件 / コンボ: {len(combo_wx)}件")
    print(f"実閾値あり: {sum(1 for s in ships.values() if s['has_real_thr'])}船宿")

    # 全日程版
    write_forecast(ships, combo_wx, fc_coords, OUT_ALL)

    # 来週末版（今週の土日 or 来週の土日）
    today = date.today()
    weekends = []
    for i in range(1, 10):
        d = today + timedelta(days=i)
        if d.weekday() >= 5:
            weekends.append(d.strftime("%Y-%m-%d"))
        if len(weekends) == 4:  # 2週末分
            break
    write_forecast(ships, combo_wx, fc_coords, OUT_WEEKEND, target_dates=set(weekends))
    print(f"来週末対象日: {weekends}")

if __name__ == "__main__":
    main()
