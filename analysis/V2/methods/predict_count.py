#!/usr/bin/env python3
"""
predict_count.py — 匹数・サイズ絶対値予測

analysis.sqlite の旬別ベースライン + 天候補正から指定日の魚種・船宿別予測を行う。
天候補正: combo_wx_params（combo_deep_dive.py が学習データから保存）を参照し、
          weather_cache.sqlite + tide_moon.sqlite の当日気象で補正を適用。

使い方:
  python insights/predict_count.py                   # 全魚種・来週土曜・★3以上
  python insights/predict_count.py --fish アジ       # アジのみ
  python insights/predict_count.py --fish アジ --date 2026/04/12
  python insights/predict_count.py --min-stars 4     # ★4以上のみ
  python insights/predict_count.py --json-out        # JSON出力
"""

import argparse, json, math, os, sqlite3, sys, urllib.request
from datetime import datetime, timedelta

sys.stdout.reconfigure(encoding="utf-8")

import sys as _sys; _sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _paths import ROOT_DIR, RESULTS_DIR, DATA_DIR, NORMALIZE_DIR, OCEAN_DIR
DB_PATH  = os.path.join(RESULTS_DIR, "analysis.sqlite")
DB_WX    = os.path.join(OCEAN_DIR, "weather_cache.sqlite")
DB_TIDE  = os.path.join(OCEAN_DIR, "tide_moon.sqlite")

TIDE_TYPE_MAP = {"大潮": 4, "中潮": 3, "小潮": 2, "長潮": 1, "若潮": 1}

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


def month_of(date_str: str) -> int:
    """YYYY/MM/DD または YYYY-MM-DD → 月番号 1-12"""
    try:
        return datetime.strptime(date_str.replace("-", "/"), "%Y/%m/%d").month
    except Exception:
        return 0


def next_saturday() -> str:
    today = datetime.today()
    days_ahead = (5 - today.weekday()) % 7
    if days_ahead == 0:
        days_ahead = 7
    return (today + timedelta(days=days_ahead)).strftime("%Y/%m/%d")


# 回遊魚: レンジ予測の代わりに★チャンス評価を使う魚種（combo_deep_dive.py と一致させる）
KAIYU_FISH = {"シイラ", "カツオ", "キハダマグロ", "ブリ", "ワラサ", "イナダ", "サワラ", "カンパチ"}

# ── ★評価 ────────────────────────────────────────────────────────────────────

def calc_stars(wmape: float, n: int) -> int:
    """cnt_avg の H=7d wMAPE + サンプル数 → ★1〜5
    wMAPE（加重平均絶対誤差率）を基準とする。
    MAPEより外れ値の影響を受けにくく、イカ等バラつきが大きい魚種でも適切に評価できる。
    wmape が None の場合は呼び出し側で mape にフォールバックすること。
    """
    if   wmape < 20 and n >= 50: return 5
    elif wmape < 30 and n >= 30: return 4
    elif wmape < 50 and n >= 20: return 3
    elif wmape < 65 and n >= 10: return 2
    else:                        return 1


def calc_stars_kaiyu(conn, fish: str, ship: str, cnt_predicted: float) -> dict | None:
    """回遊魚専用★評価: combo_star_backtest の分位数閾値で cnt_predicted を★に変換。
    good_line <= 3 のコンボ（釣れない日が大半）は None を返して★非表示。
    戻り値: {"stars": 1〜5, "hit_rate": float, "good_line": float} or None
    """
    row = conn.execute("""
        SELECT p20, p40, p60, p80, hit_rate5, hit_rate1, good_line
        FROM combo_star_backtest
        WHERE fish=? AND ship=? AND horizon=7
    """, (fish, ship)).fetchone()
    if row is None:
        return None
    p20, p40, p60, p80, hr5, hr1, good_line = row
    # 良日ラインが低すぎる（ほぼ常に釣れる or ほぼ釣れない）コンボは評価不能
    if good_line is None or good_line <= 3:
        return None
    # 予測値 → ★
    if   cnt_predicted >= p80: stars = 5
    elif cnt_predicted >= p60: stars = 4
    elif cnt_predicted >= p40: stars = 3
    elif cnt_predicted >= p20: stars = 2
    else:                      stars = 1
    return {
        "stars":     stars,
        "hit_rate5": round(hr5, 3) if hr5 is not None else None,
        "hit_rate1": round(hr1, 3) if hr1 is not None else None,
        "good_line": round(good_line, 1),
    }


# ── 天候補正用 気象ユーティリティ ────────────────────────────────────────────

def _nearest_wx_coord(conn_wx, lat, lon):
    """weather_cache.sqlite から最近傍の格納済み座標を返す"""
    coords = conn_wx.execute("SELECT DISTINCT lat, lon FROM weather").fetchall()
    if not coords:
        return lat, lon
    return min(coords, key=lambda c: (c[0] - lat) ** 2 + (c[1] - lon) ** 2)


def _get_daily_wx(conn_wx, lat, lon, date_iso, wave_clamp_thr: float = 2.0):
    """日次気象集計。combo_deep_dive.get_daily_wx と同等ロジック。"""
    rows = conn_wx.execute("""
        SELECT wind_speed, wind_dir, temp, pressure,
               wave_height, wave_period, swell_height, sst, precipitation
        FROM weather WHERE lat=? AND lon=? AND dt LIKE ?
        ORDER BY dt
    """, (lat, lon, f"{date_iso}%")).fetchall()
    if not rows:
        return {}
    result = {}
    wind_speeds   = [r[0] for r in rows if r[0] is not None]
    wind_dirs     = [r[1] for r in rows if r[1] is not None]
    temps         = [r[2] for r in rows if r[2] is not None]
    pressures     = [r[3] for r in rows if r[3] is not None]
    wave_heights  = [r[4] for r in rows if r[4] is not None]
    wave_periods  = [r[5] for r in rows if r[5] is not None]
    swell_heights = [r[6] for r in rows if r[6] is not None]
    ssts          = [r[7] for r in rows if r[7] is not None]
    precips       = [r[8] for r in rows if r[8] is not None]
    if wind_speeds:
        result["wind_speed_avg"] = sum(wind_speeds) / len(wind_speeds)
        result["wind_speed_max"] = max(wind_speeds)
    if wind_dirs:
        binned = [round(d / 22.5) % 16 * 22.5 for d in wind_dirs]
        wdm = max(set(binned), key=binned.count)
        result["wind_dir_mode"] = wdm
        result["wind_dir_n"] = math.cos(math.radians(wdm))
        result["wind_dir_e"] = math.sin(math.radians(wdm))
    if temps:
        result["temp_avg"]   = sum(temps) / len(temps)
        result["temp_max"]   = max(temps)
        result["temp_min"]   = min(temps)
        result["temp_range"] = max(temps) - min(temps)
    if pressures:
        result["pressure_avg"]   = sum(pressures) / len(pressures)
        result["pressure_min"]   = min(pressures)
        result["pressure_range"] = max(pressures) - min(pressures)
    if wave_heights:
        result["wave_height_avg"] = sum(wave_heights) / len(wave_heights)
        result["wave_height_max"] = max(wave_heights)
        result["wave_clamp"]      = min(result["wave_height_avg"], wave_clamp_thr)
    if wave_periods:
        result["wave_period_avg"] = sum(wave_periods) / len(wave_periods)
        result["wave_period_min"] = min(wave_periods)
    if swell_heights:
        result["swell_height_avg"] = sum(swell_heights) / len(swell_heights)
        result["swell_height_max"] = max(swell_heights)
    if ssts:
        result["sst_avg"] = sum(ssts) / len(ssts)
    if precips:
        result["precip_sum"] = sum(precips)
    return result


def _get_tide(date_iso: str) -> dict:
    """tide_moon.sqlite から潮汐・月齢データを取得。"""
    if not os.path.exists(DB_TIDE):
        return {}
    try:
        conn = sqlite3.connect(DB_TIDE)
        row = conn.execute(
            "SELECT tide_coeff, moon_age, tide_type FROM tide_moon WHERE date=?",
            (date_iso,)
        ).fetchone()
        conn.close()
    except Exception:
        return {}
    if not row:
        return {}
    tide_coeff, moon_age, tide_type = row
    phase = moon_age / 29.5 * 2 * math.pi if moon_age is not None else 0.0
    return {
        "tide_range":  tide_coeff,
        "moon_age":    moon_age,
        "moon_sin":    math.sin(phase),
        "moon_cos":    math.cos(phase),
        "tide_type_n": TIDE_TYPE_MAP.get(tide_type, 2),
    }


def _get_bl2(fish: str, ship: str, before_date: str, n: int = 7) -> float | None:
    """直近n件のcnt_avg平均（BL-2）をCSVから取得。before_date未満のレコードを対象。
    use_fallback=True のコンボで旬別ベースラインの代わりに使う。"""
    import csv, glob
    records = []
    for path in sorted(glob.glob(os.path.join(DATA_DIR, "*.csv"))):
        with open(path, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if row.get("tsuri_mono") == fish and row.get("ship") == ship:
                    d = row.get("date", "")
                    v = row.get("cnt_avg", "")
                    if d and v and d < before_date:
                        try:
                            records.append((d, float(v)))
                        except ValueError:
                            pass
    if not records:
        return None
    recent = sorted(records, key=lambda x: x[0], reverse=True)[:n]
    return sum(v for _, v in recent) / len(recent)


def _get_wave_clamp_thr(conn, fish: str, ship: str) -> float:
    """combo_wx_params から per-combo wave_clamp 閾値を取得。未保存なら 2.0m デフォルト。"""
    row = conn.execute(
        "SELECT mean FROM combo_wx_params "
        "WHERE fish=? AND ship=? AND metric='_combo' AND factor='_wave_clamp_thr'",
        (fish, ship)
    ).fetchone()
    return row[0] if row and row[0] is not None else 2.0


def _get_use_fallback(conn, fish: str, ship: str) -> bool:
    """combo_wx_params._meta の use_fallback フラグを返す。
    use_fallback=True のコンボは気象補正をスキップして旬別ベースラインをそのまま使う。
    例: ヒラメ×つる丸（model wMAPE が BL-0 より 10pt 以上悪い）
    """
    row = conn.execute(
        "SELECT use_fallback FROM combo_wx_params "
        "WHERE fish=? AND ship=? AND metric='cnt_avg' AND factor='_meta'",
        (fish, ship)
    ).fetchone()
    return bool(row and row[0])


def _apply_wx_correction(conn, fish: str, ship: str,
                          target_date: str, baseline_cnt: float,
                          lat: float, lon: float,
                          metric: str = 'cnt_avg') -> float:
    """
    combo_wx_params の学習パラメータ + 当日気象から補正値を計算。
    metric: 'cnt_avg' / 'cnt_min' / 'cnt_max' を指定可能。
    補正できない場合は baseline_cnt をそのまま返す。
    """
    rows = conn.execute(
        "SELECT factor, mean, std, r, alpha_scale, met_mean, met_std, lat, lon "
        "FROM combo_wx_params WHERE fish=? AND ship=? AND metric=?",
        (fish, ship, metric)
    ).fetchall()
    if not rows:
        return baseline_cnt

    meta = None
    factor_params = {}
    wx_lat = lat; wx_lon = lon  # デフォルト: combo_meta の座標
    for row in rows:
        fac, mean, std, r, alpha_scale, met_mean, met_std, rlat, rlon = row
        if fac == "_meta":
            meta = (alpha_scale, met_mean, met_std)
            if rlat and rlon:
                wx_lat, wx_lon = rlat, rlon  # 学習時の最頻ポイント座標を優先
        elif r is not None and abs(r) >= 0.10 and mean is not None and std is not None:
            factor_params[fac] = (mean, std, r)

    if meta is None or not factor_params:
        return baseline_cnt

    alpha_scale, met_mean, met_std = meta

    # 当日・前日・7日前の気象を取得
    d = datetime.strptime(target_date.replace("-", "/"), "%Y/%m/%d")
    date_iso = d.strftime("%Y-%m-%d")
    d1_iso   = (d - timedelta(days=1)).strftime("%Y-%m-%d")
    d7_iso   = (d - timedelta(days=7)).strftime("%Y-%m-%d")

    all_wx = {}

    wave_clamp_thr = _get_wave_clamp_thr(conn, fish, ship)
    if os.path.exists(DB_WX) and os.path.getsize(DB_WX) > 0:
        try:
            conn_wx = sqlite3.connect(DB_WX)
            wlat, wlon = _nearest_wx_coord(conn_wx, wx_lat, wx_lon)  # 最頻ポイント座標を使用
            wx    = _get_daily_wx(conn_wx, wlat, wlon, date_iso, wave_clamp_thr)
            wx_d1 = _get_daily_wx(conn_wx, wlat, wlon, d1_iso, wave_clamp_thr)
            wx_d7 = _get_daily_wx(conn_wx, wlat, wlon, d7_iso, wave_clamp_thr)
            conn_wx.close()
            all_wx.update(wx)
            if wx_d1:
                all_wx["precip_sum1"] = wx_d1.get("precip_sum")
            if wx.get("pressure_min") is not None and wx_d1.get("pressure_min") is not None:
                all_wx["pressure_delta"] = wx["pressure_min"] - wx_d1["pressure_min"]
            if wx.get("temp_avg") is not None and wx_d1.get("temp_avg") is not None:
                all_wx["temp_delta"] = wx["temp_avg"] - wx_d1["temp_avg"]
            if wx.get("sst_avg") is not None and wx_d7.get("sst_avg") is not None:
                all_wx["sst_delta"] = wx["sst_avg"] - wx_d7["sst_avg"]
        except Exception:
            pass

    # 潮汐・月齢（tide_moon.sqlite）
    tide    = _get_tide(date_iso)
    tide_d1 = _get_tide(d1_iso)
    all_wx.update(tide)
    if tide.get("tide_range") is not None and tide_d1.get("tide_range") is not None:
        all_wx["tide_delta"] = tide["tide_range"] - tide_d1["tide_range"]

    # 補正計算: Σ(r_i × z_i) / Σ|r_i| × met_std × alpha_scale
    w_total = sum(abs(r) for _, _, r in factor_params.values())
    if w_total == 0:
        return baseline_cnt

    num_wx = 0.0
    used = 0
    for fac, (mean, std, r) in factor_params.items():
        val = all_wx.get(fac)
        if val is None:
            continue
        z = (val - mean) / std
        num_wx += r * z
        used += 1

    if used == 0:
        return baseline_cnt

    correction = (num_wx / w_total) * met_std * alpha_scale
    return round(max(0.0, baseline_cnt + correction), 1)


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

def predict_combo(conn, fish: str, ship: str, target_date: str,
                  time_slot: str = "") -> dict | None:
    """
    旬別ベースライン + 天候補正 + time_slot補正で予測する。
    combo_wx_params があれば気象補正を適用、なければベースラインのみ。
    time_slot が指定され combo_slot_ratio に登録があれば ratio を乗じて補正。
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
    bt = {r[0]: {"mae": r[1], "mape": r[2], "wmape": r[3], "bl0_wmape": r[4]} for r in conn.execute(
        "SELECT metric, mae, mape, wmape, bl0_wmape FROM combo_backtest WHERE fish=? AND ship=? AND horizon=7",
        (fish, ship)
    ).fetchall()}

    cnt_mae      = (bt.get("cnt_avg")  or {}).get("mae")      or avg_cnt * 0.35
    cnt_mape     = (bt.get("cnt_avg")  or {}).get("mape")     or 999.0
    cnt_wmape    = (bt.get("cnt_avg")  or {}).get("wmape")
    bl0_wmape_cnt = (bt.get("cnt_avg") or {}).get("bl0_wmape")

    # モデル信頼性判定: H=7 で BL-0（旬別平均）を 1% 以上改善できていなければ不信頼
    # 不信頼コンボは予測を表示するが「精度参考値」として明示する
    if cnt_wmape is not None and bl0_wmape_cnt is not None:
        model_reliable = cnt_wmape < bl0_wmape_cnt * 0.99
    else:
        model_reliable = cnt_wmape is None or cnt_wmape < 65.0  # BL不明時は wMAPE < 65% を信頼
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

    # wMAPE 優先、None の場合は MAPE にフォールバック
    stars_metric = cnt_wmape if cnt_wmape is not None else cnt_mape
    stars = calc_stars(stars_metric, n_total)

    # ── シーズン変動リスク（船長の知見: シーズンの変わり目はブレやすい） ────────
    # 対象月 ±1 の avg_cnt を集め、変動係数（std/mean）を計算する。
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

    # 回遊魚は後で cnt_predicted 確定後に★を上書きする（フラグだけ立てておく）
    is_kaiyu = fish in KAIYU_FISH
    kaiyu_star_info = None  # predict後に calc_stars_kaiyu() で設定

    # ── 天候補正 ──────────────────────────────────────────────────────────────
    # combo_wx_params が存在すれば気象補正を適用し cnt_predicted を更新。
    # weather_cache.sqlite にデータがない将来日は tide/moon のみの部分補正。
    # use_fallback=True のコンボ（気象補正がノイズ化するコンボ）は補正をスキップ。
    baseline_cnt = avg_cnt  # 旬別ベースライン（補正前）
    use_fb = _get_use_fallback(conn, fish, ship)
    if lat and lon and not use_fb:
        cnt_predicted = _apply_wx_correction(conn, fish, ship, target_date, avg_cnt, lat, lon,
                                             metric='cnt_avg')
    else:
        # use_fallback=True: 気象補正がノイズ化するコンボ
        # BL-2（直近7件実績平均）を優先。取得できなければ旬別ベースライン(BL-1)
        bl2 = _get_bl2(fish, ship, target_date)
        cnt_predicted = round(bl2, 1) if bl2 is not None else round(avg_cnt, 1)

    # ── time_slot 補正 ────────────────────────────────────────────────────────
    # combo_slot_ratio に登録がある場合のみ適用。
    # 補正後 cnt_predicted に ratio を乗じる。
    slot_ratio = 1.0
    if time_slot:
        slot_row = conn.execute(
            "SELECT ratio FROM combo_slot_ratio WHERE fish=? AND ship=? AND time_slot=?",
            (fish, ship, time_slot)
        ).fetchone()
        if slot_row:
            slot_ratio = slot_row[0]
            cnt_predicted = round(cnt_predicted * slot_ratio, 1)

    # ── min/max 予測（直接モデル予測 → ratio フォールバック） ────────────────
    # 優先: cnt_min / cnt_max モデルが combo_wx_params にある場合は直接予測
    #       （ratio法より Coverage が良い可能性が高い）
    # フォールバック: モデルなし または use_fallback=True
    #       → avg_cnt_min/max の旬別比率を cnt_predicted に適用（従来方式）
    #       → 旬別データもない場合は ±cnt_mae で信頼区間
    cnt_lo = cnt_hi = None

    if lat and lon and not use_fb:
        # cnt_min モデルが存在するか確認してから直接予測
        bl_min = avg_cnt_min if avg_cnt_min is not None else avg_cnt * 0.5
        bl_max = avg_cnt_max if avg_cnt_max is not None else avg_cnt * 1.5
        pred_lo_direct = _apply_wx_correction(conn, fish, ship, target_date, bl_min, lat, lon,
                                              metric='cnt_min')
        pred_hi_direct = _apply_wx_correction(conn, fish, ship, target_date, bl_max, lat, lon,
                                              metric='cnt_max')
        # _apply_wx_correction はパラメータなければ baseline をそのまま返す
        # bl_min/bl_max と同値 = モデルなし（baseline返し）の判定は不要
        # → 直接予測値をそのまま採用（cnt_avgモデルがあれば cnt_min/maxモデルもある）
        cnt_lo = round(max(0, pred_lo_direct * slot_ratio), 1)
        cnt_hi = round(pred_hi_direct * slot_ratio, 1)

    if cnt_lo is None:
        # フォールバック: ratio法 または ±MAE
        if avg_cnt_min is not None and avg_cnt > 0:
            cnt_lo = round(max(0, cnt_predicted * (avg_cnt_min / avg_cnt)), 1)
        else:
            cnt_lo = round(max(0, cnt_predicted - cnt_mae), 1)

    if cnt_hi is None:
        if avg_cnt_max is not None and avg_cnt > 0:
            cnt_hi = round(cnt_predicted * (avg_cnt_max / avg_cnt), 1)
        else:
            cnt_hi = round(cnt_predicted + cnt_mae, 1)

    # ガード: 独立計算で min > max になるケースをswapで修正
    if cnt_lo > cnt_hi:
        cnt_lo, cnt_hi = cnt_hi, cnt_lo

    # 回遊魚★チャンス評価: cnt_predicted 確定後に分位数閾値で★を決定
    if is_kaiyu:
        kaiyu_star_info = calc_stars_kaiyu(conn, fish, ship, cnt_predicted)
        if kaiyu_star_info is not None:
            stars = kaiyu_star_info["stars"]  # wMAPEベースの★を上書き

    return {
        "fish":            fish,
        "ship":            ship,
        "target_date":     target_date,
        "dekad":           dekad,
        "fallback_dekad":  fallback,
        # 予測
        "cnt_predicted":   cnt_predicted,
        "baseline_cnt":    round(baseline_cnt, 1),  # 旬別ベースライン（補正前）
        "cnt_lo":          cnt_lo,   # 初心者釣果（旬別min_ratio または avg-MAE）
        "cnt_hi":          cnt_hi,   # ベテラン釣果（旬別max_ratio または avg+MAE）
        "size_predicted":  round(avg_size, 1) if avg_size else None,
        "size_lo":         round(avg_size - size_mae, 1) if avg_size and size_mae else None,
        "size_hi":         round(avg_size + size_mae, 1) if avg_size and size_mae else None,
        "kg_predicted":    round(avg_kg, 2) if avg_kg else None,
        "kg_lo":           round(max(0.0, avg_kg - kg_mae), 2) if avg_kg and kg_mae else None,
        "kg_hi":           round(avg_kg + kg_mae, 2) if avg_kg and kg_mae else None,
        # 精度・信頼性
        "model_reliable":  model_reliable,   # False = BL-0 を上回れない（HTML で「精度参考値」表示）
        "cnt_mape":        round(cnt_mape, 1),
        "cnt_wmape":       round(cnt_wmape, 1) if cnt_wmape is not None else None,
        "size_mape":       round(size_mape, 1) if size_mape else None,
        "kg_mape":         round(kg_mape, 1) if kg_mape else None,
        "stars":           stars,
        # 回遊魚★チャンス評価（good_line<=3 のコンボは None）
        "kaiyu_stars":     kaiyu_star_info,
        # シーズン変動リスク（0.0〜1.0+、0.3超で変動期判定）
        "transition_risk": transition_risk,
        # time_slot 補正（1.0 = 補正なし）
        "slot_ratio":      round(slot_ratio, 3),
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
    if not args.json_out:
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
