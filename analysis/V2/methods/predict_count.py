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
from datetime import datetime, timedelta, date as _date

sys.stdout.reconfigure(encoding="utf-8")

import sys as _sys; _sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _paths import ROOT_DIR, RESULTS_DIR, DATA_DIR, NORMALIZE_DIR, OCEAN_DIR
DB_PATH  = os.path.join(RESULTS_DIR, "analysis.sqlite")
DB_WX    = os.path.join(OCEAN_DIR, "weather_cache.sqlite")
DB_TIDE  = os.path.join(OCEAN_DIR, "tide_moon.sqlite")

TIDE_TYPE_MAP = {"大潮": 4, "中潮": 3, "小潮": 2, "長潮": 1, "若潮": 1}

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
MARINE_URL   = "https://marine-api.open-meteo.com/v1/marine"

# 予測ログ出力先
LOG_PATH = os.path.join(RESULTS_DIR, "predict_log.jsonl")

# Forecast API インメモリキャッシュ: (lat3, lon3, date_iso) -> wx_dict (wave_clamp除く)
_FORECAST_CACHE: dict = {}


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
KAIYU_FISH = {"シイラ", "カツオ", "キハダマグロ", "ブリ", "ワラサ", "イナダ", "サワラ", "カンパチ", "ムギイカ"}

# ── FAST変数 horizon フィルタ ─────────────────────────────────────────────────
# combo_deep_dive.py の FAST_FACTORS と一致させること（変更時は両方更新）
# H>7 の予測では Forecast API の速い変数（風・波・潮流等）が気候値に収束するため補正に使わない。
# ※ temp_range/pressure_range は「日較差・日内変動幅」であり、絶対値（temp_avg/pressure_avg）
#   とは別の短期変動指標。後者は SLOW 扱い（H=28 まで有効）。
FAST_MAX_H = 7   # 速い変数は H>7 では予報精度ゼロとみなして補正に使わない
_FAST_FACTORS: frozenset = frozenset({
    "wind_speed_avg", "wind_speed_max", "wind_dir_mode", "wind_dir_n", "wind_dir_e",
    "wave_height_avg", "wave_height_max", "wave_clamp",
    "wave_period_avg", "wave_period_min",
    "swell_height_avg", "swell_height_max",
    "temp_range", "temp_delta", "pressure_range",   # 日較差・変化量 = 短期指標
    "precip_sum", "precip_sum1", "precip_sum2", "precip_sum3",
    "precip_sum4", "precip_sum5", "precip_sum6", "precip_sum7",
    "water_color_prev_n", "prev_week_cnt",
    "typhoon_dist", "typhoon_wind",
    "current_speed_avg", "current_speed_max", "current_dir_mode",
})


def _h_days(target_date: str) -> int:
    """target_date（YYYY/MM/DD or YYYY-MM-DD）から今日までの差分日数を返す。当日=0。
    過去日付は負値（例: 昨日=-1）を返す。負値は FAST_MAX_H を超えないため、
    過去日付の呼び出しでは FAST変数が除外されない（意図通り: 過去検証では実測値が使える）。
    """
    try:
        td = datetime.strptime(target_date.replace("-", "/"), "%Y/%m/%d").date()
        return (td - datetime.today().date()).days
    except Exception:
        return 0

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


def _fetch_forecast_wx(lat: float, lon: float, date_iso: str,
                        wave_clamp_thr: float = 2.0) -> dict:
    """Open-Meteo Forecast/Marine API から翌日〜16日先の気象を取得。
    _get_daily_wx() と同じキー形式で返す。失敗時は空 dict。
    対象: 今日以降の日付（weather_cache.sqlite に存在しない将来日）
    """
    key = (round(lat, 3), round(lon, 3), date_iso)
    if key in _FORECAST_CACHE:
        out = dict(_FORECAST_CACHE[key])
        out["wave_clamp"] = min(out.get("wave_height_avg", 0.0), wave_clamp_thr)
        return out

    result = {}
    try:
        params = "&".join([
            f"latitude={lat}", f"longitude={lon}",
            f"start_date={date_iso}", f"end_date={date_iso}",
            "hourly=wind_speed_10m,wind_direction_10m,temperature_2m,"
            "pressure_msl,precipitation",
            "timezone=Asia%2FTokyo",
        ])
        with urllib.request.urlopen(f"{FORECAST_URL}?{params}", timeout=10) as resp:
            data = json.loads(resp.read())
        h = data.get("hourly", {})
        # 釣り時間帯（5〜12時）に絞る
        idxs = list(range(5, 13))
        winds  = [h["wind_speed_10m"][i]      for i in idxs if i < len(h.get("wind_speed_10m", [])) and h["wind_speed_10m"][i] is not None]
        wdirs  = [h["wind_direction_10m"][i]  for i in idxs if i < len(h.get("wind_direction_10m", [])) and h["wind_direction_10m"][i] is not None]
        temps  = [h["temperature_2m"][i]      for i in idxs if i < len(h.get("temperature_2m", [])) and h["temperature_2m"][i] is not None]
        press  = [h["pressure_msl"][i]        for i in idxs if i < len(h.get("pressure_msl", [])) and h["pressure_msl"][i] is not None]
        prec   = [h["precipitation"][i]       for i in idxs if i < len(h.get("precipitation", [])) and h["precipitation"][i] is not None]
        if winds:
            result["wind_speed_avg"] = sum(winds) / len(winds)
            result["wind_speed_max"] = max(winds)
        if wdirs:
            binned = [round(d / 22.5) % 16 * 22.5 for d in wdirs]
            wdm = max(set(binned), key=binned.count)
            result["wind_dir_mode"] = wdm
            result["wind_dir_n"]    = math.cos(math.radians(wdm))
            result["wind_dir_e"]    = math.sin(math.radians(wdm))
        if temps:
            result["temp_avg"]   = sum(temps) / len(temps)
            result["temp_max"]   = max(temps)
            result["temp_min"]   = min(temps)
            result["temp_range"] = max(temps) - min(temps)
        if press:
            result["pressure_avg"]   = sum(press) / len(press)
            result["pressure_min"]   = min(press)
            result["pressure_range"] = max(press) - min(press)
        if prec:
            result["precip_sum"] = sum(prec)
    except Exception as e:
        result["_forecast_atmo_error"] = str(e)

    try:
        params = "&".join([
            f"latitude={lat}", f"longitude={lon}",
            f"start_date={date_iso}", f"end_date={date_iso}",
            "hourly=wave_height,wave_period,swell_wave_height,"
            "sea_surface_temperature,ocean_current_velocity,ocean_current_direction",
            "timezone=Asia%2FTokyo",
        ])
        with urllib.request.urlopen(f"{MARINE_URL}?{params}", timeout=10) as resp:
            data = json.loads(resp.read())
        h = data.get("hourly", {})
        idxs = list(range(5, 13))
        waves  = [h["wave_height"][i]              for i in idxs if i < len(h.get("wave_height", [])) and h["wave_height"][i] is not None]
        wpers  = [h["wave_period"][i]              for i in idxs if i < len(h.get("wave_period", [])) and h["wave_period"][i] is not None]
        swels  = [h["swell_wave_height"][i]        for i in idxs if i < len(h.get("swell_wave_height", [])) and h["swell_wave_height"][i] is not None]
        ssts   = [h["sea_surface_temperature"][i]  for i in idxs if i < len(h.get("sea_surface_temperature", [])) and h["sea_surface_temperature"][i] is not None]
        curspd = [h["ocean_current_velocity"][i]   for i in idxs if i < len(h.get("ocean_current_velocity", [])) and h["ocean_current_velocity"][i] is not None]
        curdir = [h["ocean_current_direction"][i]  for i in idxs if i < len(h.get("ocean_current_direction", [])) and h["ocean_current_direction"][i] is not None]
        if waves:
            result["wave_height_avg"] = sum(waves) / len(waves)
            result["wave_height_max"] = max(waves)
            result["wave_clamp"]      = min(result["wave_height_avg"], wave_clamp_thr)
        if wpers:
            result["wave_period_avg"] = sum(wpers) / len(wpers)
            result["wave_period_min"] = min(wpers)
        if swels:
            result["swell_height_avg"] = sum(swels) / len(swels)
            result["swell_height_max"] = max(swels)
        if ssts:
            result["sst_avg"] = sum(ssts) / len(ssts)
        if curspd:
            result["current_speed_avg"] = sum(curspd) / len(curspd)
            result["current_speed_max"] = max(curspd)
        if curdir:
            binned = [round(d / 22.5) % 16 * 22.5 for d in curdir]
            result["current_dir_mode"] = max(set(binned), key=binned.count)
    except Exception as e:
        result["_forecast_marine_error"] = str(e)

    _FORECAST_CACHE[key] = {k: v for k, v in result.items() if k != "wave_clamp"}
    return result


def _log_predict(entry: dict) -> None:
    """予測ログを JSONL 形式で追記。失敗しても予測は止めない。"""
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass


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


def _get_kaiyu_promoted(conn, fish: str, ship: str) -> bool:
    """combo_wx_params._meta の kaiyu_promoted フラグを返す。
    kaiyu_promoted=True の回遊魚コンボは★評価をスキップして通常の匹数レンジ予測を使う。
    条件: H=7 cnt_avg wMAPE < 60% かつ BL-2 勝ち（combo_deep_dive.py で自動判定）
    """
    row = conn.execute(
        "SELECT kaiyu_promoted FROM combo_wx_params "
        "WHERE fish=? AND ship=? AND metric='cnt_avg' AND factor='_meta'",
        (fish, ship)
    ).fetchone()
    return bool(row and row[0])


def _build_all_wx(wx_lat: float, wx_lon: float, target_date: str,
                   wave_clamp_thr: float) -> tuple[dict, bool, str]:
    """当日・前日・7日前の気象データを構築して返す。
    戻り値: (all_wx dict, is_future bool, wx_source str)
    combo/ポイント両モデルで共用する。
    """
    d = datetime.strptime(target_date.replace("-", "/"), "%Y/%m/%d")
    date_iso = d.strftime("%Y-%m-%d")
    d1_iso   = (d - timedelta(days=1)).strftime("%Y-%m-%d")
    d7_iso   = (d - timedelta(days=7)).strftime("%Y-%m-%d")

    all_wx = {}
    wx_source = "none"
    today_iso = datetime.today().strftime("%Y-%m-%d")
    is_future = date_iso > today_iso

    if is_future:
        wx = _fetch_forecast_wx(wx_lat, wx_lon, date_iso, wave_clamp_thr)
        all_wx.update({k: v for k, v in wx.items() if not k.startswith("_")})
        wx_d1 = _fetch_forecast_wx(wx_lat, wx_lon, d1_iso, wave_clamp_thr) if d1_iso >= today_iso else {}
        wx_d7 = {}
        if not wx_d1 and os.path.exists(DB_WX):
            try:
                conn_wx = sqlite3.connect(DB_WX)
                wlat, wlon = _nearest_wx_coord(conn_wx, wx_lat, wx_lon)
                wx_d1 = _get_daily_wx(conn_wx, wlat, wlon, d1_iso, wave_clamp_thr)
                wx_d7 = _get_daily_wx(conn_wx, wlat, wlon, d7_iso, wave_clamp_thr)
                conn_wx.close()
            except Exception:
                pass
        wx_source = "forecast_api"
        if wx.get("_forecast_atmo_error") or wx.get("_forecast_marine_error"):
            wx_source = "forecast_api_partial"
    elif os.path.exists(DB_WX) and os.path.getsize(DB_WX) > 0:
        try:
            conn_wx = sqlite3.connect(DB_WX)
            wlat, wlon = _nearest_wx_coord(conn_wx, wx_lat, wx_lon)
            wx    = _get_daily_wx(conn_wx, wlat, wlon, date_iso, wave_clamp_thr)
            wx_d1 = _get_daily_wx(conn_wx, wlat, wlon, d1_iso, wave_clamp_thr)
            wx_d7 = _get_daily_wx(conn_wx, wlat, wlon, d7_iso, wave_clamp_thr)
            conn_wx.close()
            all_wx.update(wx)
            wx_source = "weather_cache"
        except Exception:
            wx_d1 = {}; wx_d7 = {}
    else:
        wx_d1 = {}; wx_d7 = {}

    if wx_d1:
        if wx_d1.get("precip_sum") is not None:
            all_wx["precip_sum1"] = wx_d1["precip_sum"]
        if all_wx.get("pressure_min") is not None and wx_d1.get("pressure_min") is not None:
            all_wx["pressure_delta"] = all_wx["pressure_min"] - wx_d1["pressure_min"]
        if all_wx.get("temp_avg") is not None and wx_d1.get("temp_avg") is not None:
            all_wx["temp_delta"] = all_wx["temp_avg"] - wx_d1["temp_avg"]
    if wx_d7 and all_wx.get("sst_avg") is not None and wx_d7.get("sst_avg") is not None:
        all_wx["sst_delta"] = all_wx["sst_avg"] - wx_d7["sst_avg"]

    tide    = _get_tide(date_iso)
    tide_d1 = _get_tide(d1_iso)
    all_wx.update(tide)
    if tide.get("tide_range") is not None and tide_d1.get("tide_range") is not None:
        all_wx["tide_delta"] = tide["tide_range"] - tide_d1["tide_range"]

    return all_wx, is_future, wx_source


def _apply_correction_from_params(factor_params: dict, meta: tuple,
                                   all_wx: dict, baseline_cnt: float,
                                   h_days: int = 0) -> float | None:
    """factor_params + meta から気象補正値を計算。因子が0件なら None を返す。
    h_days > FAST_MAX_H の場合は FAST変数を除外する（Forecast API の精度限界）。"""
    # H>7 の場合 FAST変数を factor_params から除外
    if h_days > FAST_MAX_H:
        factor_params = {k: v for k, v in factor_params.items()
                         if k not in _FAST_FACTORS}
    alpha_scale, met_mean, met_std = meta
    w_total = sum(abs(r) for _, _, r in factor_params.values())
    if w_total == 0:
        return None
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
        return None
    correction = (num_wx / w_total) * met_std * alpha_scale
    return round(max(0.0, baseline_cnt + correction), 1)


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
    wx_lat = lat; wx_lon = lon
    for row in rows:
        fac, mean, std, r, alpha_scale, met_mean, met_std, rlat, rlon = row
        if fac == "_meta":
            meta = (alpha_scale, met_mean, met_std)
            if rlat and rlon:
                wx_lat, wx_lon = rlat, rlon
        elif r is not None and abs(r) >= 0.10 and mean is not None and std is not None:
            factor_params[fac] = (mean, std, r)

    if meta is None or not factor_params:
        return baseline_cnt

    wave_clamp_thr = _get_wave_clamp_thr(conn, fish, ship)
    all_wx, is_future, wx_source = _build_all_wx(wx_lat, wx_lon, target_date, wave_clamp_thr)
    h_days = _h_days(target_date)

    predicted = _apply_correction_from_params(factor_params, meta, all_wx, baseline_cnt, h_days)
    if predicted is None:
        return baseline_cnt

    # 予測ログ（H>7 の場合 FAST変数を除外した後の factor_params で計算）
    log_fps = ({k: v for k, v in factor_params.items() if k not in _FAST_FACTORS}
               if h_days > FAST_MAX_H else factor_params)
    alpha_scale, met_mean, met_std = meta
    w_total = sum(abs(r) for _, _, r in log_fps.values())
    num_wx = sum(r * (all_wx[fac] - mean) / std
                 for fac, (mean, std, r) in log_fps.items()
                 if all_wx.get(fac) is not None)
    correction = (num_wx / w_total) * met_std * alpha_scale if w_total else 0.0
    _log_predict({
        "ts":           datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "fish":         fish,
        "ship":         ship,
        "target_date":  target_date,
        "metric":       metric,
        "wx_source":    wx_source,
        "is_future":    is_future,
        "baseline":     round(baseline_cnt, 2),
        "correction":   round(correction, 2),
        "predicted":    predicted,
        "factors_used": sum(1 for fac in log_fps if all_wx.get(fac) is not None),
        "factors_avail": len(log_fps),
        "wx_keys":      [k for k in all_wx if not k.startswith("_")],
    })

    return predicted


def _predict_point(conn, fish: str, ship: str, month: int) -> str | None:
    """combo_point_events の月別集計から最頻ポイントを返す。登録なければ None。"""
    try:
        row = conn.execute(
            "SELECT point_normalized FROM combo_point_events "
            "WHERE fish=? AND ship=? AND month=? AND is_named=1 "
            "GROUP BY point_normalized ORDER BY COUNT(*) DESC LIMIT 1",
            (fish, ship, month)
        ).fetchone()
        if row:
            return row[0]
        # 月別データなし → 全体で最多ポイント
        row = conn.execute(
            "SELECT point_normalized FROM combo_point_events "
            "WHERE fish=? AND ship=? AND is_named=1 "
            "GROUP BY point_normalized ORDER BY COUNT(*) DESC LIMIT 1",
            (fish, ship)
        ).fetchone()
        return row[0] if row else None
    except Exception:
        return None


def _apply_trip_wx_correction(conn, fish: str, ship: str, trip_no: int,
                               target_date: str, baseline_cnt: float,
                               lat: float, lon: float,
                               metric: str = 'cnt_avg') -> float | None:
    """combo_trip_wx_params の便別モデルで補正を計算。パラメータなければ None。"""
    try:
        rows = conn.execute(
            "SELECT factor, mean, std, r, alpha_scale, met_mean, met_std, lat, lon "
            "FROM combo_trip_wx_params WHERE fish=? AND ship=? AND trip_no=? AND metric=?",
            (fish, ship, trip_no, metric)
        ).fetchall()
    except Exception:
        return None
    if not rows:
        return None

    meta = None
    factor_params = {}
    wx_lat = lat; wx_lon = lon
    for row in rows:
        fac, mean, std, r, alpha_scale, met_mean, met_std, rlat, rlon = row
        if fac == "_meta":
            meta = (alpha_scale, met_mean, met_std)
            if rlat and rlon:
                wx_lat, wx_lon = rlat, rlon
        elif r is not None and abs(r) >= 0.10 and mean is not None and std is not None:
            factor_params[fac] = (mean, std, r)

    if meta is None or not factor_params:
        return None

    wave_clamp_thr = _get_wave_clamp_thr(conn, fish, ship)
    all_wx, _, _ = _build_all_wx(wx_lat, wx_lon, target_date, wave_clamp_thr)
    return _apply_correction_from_params(factor_params, meta, all_wx, baseline_cnt, _h_days(target_date))


_WC_MAX_DAYS = 7   # water_color は FAST 変数（遷移3.7〜4.2日）。7日超は情報価値なし
_WC_MAX_DIST  = 0.3  # combo_deep_dive.py の _WC_MAX_DIST と統一

def _predict_water_color_cat(conn, lat: float, lon: float, target_date: str) -> str:
    """water_color_daily から予測水色カテゴリ（澄み/濁り/""）を返す。
    water_color は FAST 変数（遷移3.7日）のため 7 日以内のデータのみ使用。
    データなし・距離 0.3 度超・7 日超の場合は ""（予測不可）を返す。
    """
    if lat is None or lon is None:
        return ""
    date_iso = target_date.replace("/", "-")
    try:
        row = conn.execute(
            "SELECT wc_pred, date FROM water_color_daily "
            "WHERE date <= ? AND date >= date(?, ?) "
            "AND ABS(lat - ?) < ? AND ABS(lon - ?) < ? "
            "ORDER BY (ABS(lat - ?) + ABS(lon - ?)) ASC, date DESC LIMIT 1",
            (date_iso, date_iso, f"-{_WC_MAX_DAYS} days",
             lat, _WC_MAX_DIST, lon, _WC_MAX_DIST,
             lat, lon)
        ).fetchone()
        if not row:
            return ""
        wc = row[0]
        if wc >= 0.3:
            return "澄み"
        elif wc <= -0.3:
            return "濁り"
        return ""
    except Exception:
        return ""


def _apply_water_color_wx_correction(conn, fish: str, ship: str, wc_cat: str,
                                      target_date: str, baseline_cnt: float,
                                      lat: float, lon: float,
                                      metric: str = 'cnt_avg') -> float | None:
    """combo_water_color_wx_params の水色別モデルで補正を計算。パラメータなければ None。"""
    if not wc_cat:
        return None
    try:
        rows = conn.execute(
            "SELECT factor, mean, std, r, alpha_scale, met_mean, met_std, lat, lon "
            "FROM combo_water_color_wx_params WHERE fish=? AND ship=? AND water_color_cat=? AND metric=?",
            (fish, ship, wc_cat, metric)
        ).fetchall()
    except Exception:
        return None
    if not rows:
        return None

    meta = None
    factor_params = {}
    wx_lat = lat; wx_lon = lon
    for row in rows:
        fac, mean, std, r, alpha_scale, met_mean, met_std, rlat, rlon = row
        if fac == "_meta":
            meta = (alpha_scale, met_mean, met_std)
            if rlat and rlon:
                wx_lat, wx_lon = rlat, rlon
        elif r is not None and abs(r) >= 0.10 and mean is not None and std is not None:
            factor_params[fac] = (mean, std, r)

    if meta is None or not factor_params:
        return None

    wave_clamp_thr = _get_wave_clamp_thr(conn, fish, ship)
    all_wx, _, _ = _build_all_wx(wx_lat, wx_lon, target_date, wave_clamp_thr)
    return _apply_correction_from_params(factor_params, meta, all_wx, baseline_cnt, _h_days(target_date))


def _apply_point_wx_correction(conn, fish: str, ship: str, point: str,
                                 target_date: str, baseline_cnt: float,
                                 lat: float, lon: float,
                                 metric: str = 'cnt_avg') -> float | None:
    """combo_point_wx_params のポイント別モデルで補正を計算。
    パラメータなし or 因子0件なら None を返す（呼び出し側で combo モデルにフォールバック）。
    """
    try:
        rows = conn.execute(
            "SELECT factor, mean, std, r, alpha_scale, met_mean, met_std, lat, lon "
            "FROM combo_point_wx_params WHERE fish=? AND ship=? AND point=? AND metric=?",
            (fish, ship, point, metric)
        ).fetchall()
    except Exception:
        return None
    if not rows:
        return None

    meta = None
    factor_params = {}
    wx_lat = lat; wx_lon = lon
    for row in rows:
        fac, mean, std, r, alpha_scale, met_mean, met_std, rlat, rlon = row
        if fac == "_meta":
            meta = (alpha_scale, met_mean, met_std)
            if rlat and rlon:
                wx_lat, wx_lon = rlat, rlon
        elif r is not None and abs(r) >= 0.10 and mean is not None and std is not None:
            factor_params[fac] = (mean, std, r)

    if meta is None or not factor_params:
        return None

    wave_clamp_thr = _get_wave_clamp_thr(conn, fish, ship)
    all_wx, _, _ = _build_all_wx(wx_lat, wx_lon, target_date, wave_clamp_thr)
    return _apply_correction_from_params(factor_params, meta, all_wx, baseline_cnt, _h_days(target_date))


def _predict_point_depth(conn, fish: str, ship: str) -> str | None:
    """best-improvement の point_depth_key を返す。BL2比改善 < 5pt なら None。"""
    try:
        row = conn.execute(
            "SELECT point_depth_key, (bl2_wmape - wmape) as imp "
            "FROM combo_point_depth_backtest "
            "WHERE fish=? AND ship=? AND horizon=0 AND metric='cnt_avg' "
            "AND bl2_wmape IS NOT NULL AND wmape IS NOT NULL "
            "ORDER BY imp DESC LIMIT 1",
            (fish, ship)
        ).fetchone()
        if row and row[1] is not None and row[1] >= 5.0:
            return row[0]
        return None
    except Exception:
        return None


def _apply_point_depth_wx_correction(conn, fish: str, ship: str, point_depth_key: str,
                                      target_date: str, baseline_cnt: float,
                                      lat: float, lon: float,
                                      metric: str = 'cnt_avg') -> float | None:
    """combo_point_depth_wx_params のポイント×水深帯モデルで補正を計算。パラメータなければ None。"""
    try:
        rows = conn.execute(
            "SELECT factor, mean, std, r, alpha_scale, met_mean, met_std, lat, lon "
            "FROM combo_point_depth_wx_params WHERE fish=? AND ship=? AND point_depth_key=? AND metric=?",
            (fish, ship, point_depth_key, metric)
        ).fetchall()
    except Exception:
        return None
    if not rows:
        return None

    meta = None
    factor_params = {}
    wx_lat = lat; wx_lon = lon
    for row in rows:
        fac, mean, std, r, alpha_scale, met_mean, met_std, rlat, rlon = row
        if fac == "_meta":
            meta = (alpha_scale, met_mean, met_std)
            if rlat and rlon:
                wx_lat, wx_lon = rlat, rlon
        elif r is not None and abs(r) >= 0.10 and mean is not None and std is not None:
            factor_params[fac] = (mean, std, r)

    if meta is None or not factor_params:
        return None

    wave_clamp_thr = _get_wave_clamp_thr(conn, fish, ship)
    all_wx, _, _ = _build_all_wx(wx_lat, wx_lon, target_date, wave_clamp_thr)
    return _apply_correction_from_params(factor_params, meta, all_wx, baseline_cnt, _h_days(target_date))


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
                  time_slot: str = "", trip_no: int = 0) -> dict | None:
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
    if meta:
        n_total = meta[0]
        lat     = meta[1]
        lon     = meta[2]
    else:
        # combo_meta 未登録（save_insights.py 未実行コンボ）: combo_decadal の合計を使用
        n_sum_row = conn.execute(
            "SELECT SUM(n) FROM combo_decadal WHERE fish=? AND ship=?", (fish, ship)
        ).fetchone()
        n_total = n_sum_row[0] if n_sum_row and n_sum_row[0] else n_dekad
        # lat/lon は combo_wx_params._meta から取得
        wp = conn.execute(
            "SELECT lat, lon FROM combo_wx_params WHERE fish=? AND ship=? AND factor='_meta' LIMIT 1",
            (fish, ship)
        ).fetchone()
        lat = wp[0] if wp else None
        lon = wp[1] if wp else None

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
    # ただし kaiyu_promoted=True のコンボは昇格済み → 通常の匹数レンジ予測を使う
    is_kaiyu = fish in KAIYU_FISH
    kaiyu_promoted = _get_kaiyu_promoted(conn, fish, ship) if is_kaiyu else False
    if kaiyu_promoted:
        is_kaiyu = False  # 昇格コンボは通常の cnt_lo/cnt_hi 予測で処理
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

    # ── ポイント別補正（combo_point_wx_params があれば優先） ──────────────────
    # 月 → 最頻ポイント → ポイント別モデルで補正。モデルなければ combo モデルを維持。
    predicted_point = None
    if lat and lon and not use_fb:
        predicted_point = _predict_point(conn, fish, ship, month_of(target_date))
        if predicted_point:
            pt_cnt = _apply_point_wx_correction(
                conn, fish, ship, predicted_point, target_date, avg_cnt, lat, lon, 'cnt_avg'
            )
            if pt_cnt is not None:
                cnt_predicted = pt_cnt

    # ── 水色別補正（water_color_daily → 澄み/濁り → combo_water_color_wx_params） ─
    # water_color_daily から予測水色カテゴリを取得。モデルがあれば現在の予測を上書き。
    predicted_water_color = ""
    if lat and lon and not use_fb:
        predicted_water_color = _predict_water_color_cat(conn, lat, lon, target_date)
        if predicted_water_color:
            wc_cnt = _apply_water_color_wx_correction(
                conn, fish, ship, predicted_water_color, target_date, avg_cnt, lat, lon, 'cnt_avg'
            )
            if wc_cnt is not None:
                cnt_predicted = wc_cnt

    # ── ポイント×水深帯別補正（combo_point_depth_wx_params があれば優先） ───────
    # BL2比 5pt 以上改善する point_depth_key があれば、water_color モデルを上書き。
    # 優先チェーン: combo < point < water_color < point_depth < trip（最高優先）
    predicted_point_depth = None
    if lat and lon and not use_fb:
        predicted_point_depth = _predict_point_depth(conn, fish, ship)
        if predicted_point_depth:
            pd_cnt = _apply_point_depth_wx_correction(
                conn, fish, ship, predicted_point_depth, target_date, avg_cnt, lat, lon, 'cnt_avg'
            )
            if pd_cnt is not None:
                cnt_predicted = pd_cnt

    # ── 便別補正（trip_no 指定時に combo_trip_wx_params があれば最優先） ─────────
    # 便番号が判明している場合（予約情報等）に便別モデルを適用。最も高精度なため最優先。
    predicted_trip_no = None
    if lat and lon and not use_fb and trip_no:
        trip_cnt = _apply_trip_wx_correction(
            conn, fish, ship, trip_no, target_date, avg_cnt, lat, lon, 'cnt_avg'
        )
        if trip_cnt is not None:
            cnt_predicted = trip_cnt
            predicted_trip_no = trip_no

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
        "lat":                    lat,
        "lon":                    lon,
        "predicted_point":        predicted_point,
        "predicted_point_depth":  predicted_point_depth,   # {point}_{depth_band} or None
        "predicted_water_color":  predicted_water_color,   # 澄み/濁り/"" (water_color_daily予測)
        "predicted_trip_no":      predicted_trip_no,       # trip_no指定時のみ
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

    _FORECAST_CACHE.clear()
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
