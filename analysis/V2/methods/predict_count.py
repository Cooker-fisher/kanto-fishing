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

import argparse, json, math, os, sqlite3, sys, time, urllib.request
from datetime import datetime, timedelta, date as _date

sys.stdout.reconfigure(encoding="utf-8")

import sys as _sys; _sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _paths import ROOT_DIR, RESULTS_DIR, DATA_DIR, NORMALIZE_DIR, OCEAN_DIR
DB_PATH  = os.path.join(RESULTS_DIR, "analysis.sqlite")
# D層クラウド実行（2026-06-10）: analysis.sqlite（ローカルのみ・gitignore）が無い環境では
# build_predict_params.py が書き出した蒸留 DB（コミット対象）に自動フォールバックする。
# 蒸留 DB はコンボレベルモデルのみ収録。ポイント/水色/水深/便別チェーンのテーブルは
# 欠落するが、各補正関数は try/except で安全にスキップする（確認済み）。
PARAMS_DB_PATH = os.path.join(RESULTS_DIR, "predict_params.sqlite")
if not os.path.exists(DB_PATH) and os.path.exists(PARAMS_DB_PATH):
    DB_PATH = PARAMS_DB_PATH
    try:
        _c = sqlite3.connect(PARAMS_DB_PATH)
        _meta = dict(_c.execute("SELECT key, value FROM export_meta").fetchall())
        _c.close()
        print(f"[predict_count] 蒸留パラメータ DB を使用: exported_at={_meta.get('exported_at')} mode={_meta.get('mode')}")
    except Exception:
        print("[predict_count] 蒸留パラメータ DB を使用（export_meta 読込不可）")
DB_WX    = os.path.join(OCEAN_DIR, "weather_cache.sqlite")
DB_TIDE  = os.path.join(OCEAN_DIR, "tide_moon.sqlite")
DB_TYPHOON = os.path.join(OCEAN_DIR, "typhoon.sqlite")   # T44b: コミット済み・CI でも参照可

TIDE_TYPE_MAP = {"大潮": 4, "中潮": 3, "小潮": 2, "長潮": 1, "若潮": 1}

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
MARINE_URL   = "https://marine-api.open-meteo.com/v1/marine"

# 予測ログ出力先
LOG_PATH = os.path.join(RESULTS_DIR, "predict_log.jsonl")

# Forecast API インメモリキャッシュ: (lat3, lon3, date_iso) -> wx_dict (wave_clamp除く)
_FORECAST_CACHE: dict = {}
# 範囲取得済み座標: (lat3, lon3) -> 取得済み end_date_iso（同一座標の再取得を防ぐ）
_FORECAST_RANGE_DONE: dict = {}
# Open-Meteo Forecast/Marine API の予報上限（当日 + 15日 = 16日分）
_FORECAST_MAX_DAYS = 16


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
KAIYU_FISH = {"シイラ", "カツオ", "キハダマグロ", "ブリ", "ワラサ", "イナダ", "サワラ", "カンパチ", "ムギイカ",
              "タイ五目", "LT五目", "ニ目五目", "シマアジ", "泳がせ五目"}

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


def _forecast_hour_idxs_by_date(h: dict) -> dict:
    """hourly.time から date_iso -> 釣り時間帯（5〜12時）のインデックス列を作る。
    単日取得時の `range(5, 13)` と同じ時間帯を、複数日レスポンスでも日別に切り出す。
    """
    out: dict = {}
    for i, t in enumerate(h.get("time", [])):
        d, _, hm = str(t).partition("T")
        try:
            hour = int(hm[:2])
        except ValueError:
            continue
        if 5 <= hour <= 12:
            out.setdefault(d, []).append(i)
    return out


def _agg_forecast_atmo(h: dict, idxs: list) -> dict:
    """Forecast API の hourly から1日分（釣り時間帯）の大気系サマリーを集計。"""
    result = {}
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
    return result


def _agg_forecast_marine(h: dict, idxs: list) -> dict:
    """Marine API の hourly から1日分（釣り時間帯）の海況サマリーを集計。
    wave_clamp は閾値がコンボ依存のため、ここでは作らず呼び出し側で付ける。"""
    result = {}
    waves  = [h["wave_height"][i]              for i in idxs if i < len(h.get("wave_height", [])) and h["wave_height"][i] is not None]
    wpers  = [h["wave_period"][i]              for i in idxs if i < len(h.get("wave_period", [])) and h["wave_period"][i] is not None]
    swels  = [h["swell_wave_height"][i]        for i in idxs if i < len(h.get("swell_wave_height", [])) and h["swell_wave_height"][i] is not None]
    ssts   = [h["sea_surface_temperature"][i]  for i in idxs if i < len(h.get("sea_surface_temperature", [])) and h["sea_surface_temperature"][i] is not None]
    curspd = [h["ocean_current_velocity"][i]   for i in idxs if i < len(h.get("ocean_current_velocity", [])) and h["ocean_current_velocity"][i] is not None]
    curdir = [h["ocean_current_direction"][i]  for i in idxs if i < len(h.get("ocean_current_direction", [])) and h["ocean_current_direction"][i] is not None]
    if waves:
        result["wave_height_avg"] = sum(waves) / len(waves)
        result["wave_height_max"] = max(waves)
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
    return result


def _get_json_retry(url: str, timeout: int = 15, attempts: int = 3) -> dict:
    """Open-Meteo を叩いて JSON を返す。429/一時障害は指数バックオフで再試行。
    範囲取得は1リクエストで座標×16日分を賄うため、単発失敗の損失が大きい。"""
    last = None
    for i in range(attempts):
        try:
            with urllib.request.urlopen(url, timeout=timeout) as resp:
                return json.loads(resp.read())
        except Exception as e:
            last = e
            if i < attempts - 1:
                time.sleep(2 ** i)
    raise last


def _fetch_forecast_range(lat: float, lon: float, start_iso: str, end_iso: str) -> None:
    """start_iso〜end_iso を1リクエスト（大気/海況の2本）で取得し、
    _FORECAST_CACHE を日別に充填する。

    Open-Meteo は start_date/end_date の範囲取得に対応しており、1日ずつ叩くのと
    レスポンス以外のコストは変わらない。日付ごとに個別リクエストしていた頃は
    予測1回あたり「ユニーク座標 × ホライズン数 × 2」本の逐次 HTTP が発生し、
    predict_daily（10ホライズン）で約85分かかっていた（2026-07-21）。
    """
    ckey = (round(lat, 3), round(lon, 3))
    per_date: dict = {}

    def _mark_error(field: str, msg: str) -> None:
        # 範囲全体が失敗した場合、日別エントリを作れないので座標単位の
        # フォールバックに委ねる（キャッシュを汚さない）。
        per_date.setdefault("_error", {})[field] = msg

    try:
        params = "&".join([
            f"latitude={lat}", f"longitude={lon}",
            f"start_date={start_iso}", f"end_date={end_iso}",
            "hourly=wind_speed_10m,wind_direction_10m,temperature_2m,"
            "pressure_msl,precipitation",
            "timezone=Asia%2FTokyo",
        ])
        data = _get_json_retry(f"{FORECAST_URL}?{params}")
        h = data.get("hourly", {})
        for d, idxs in _forecast_hour_idxs_by_date(h).items():
            per_date.setdefault(d, {}).update(_agg_forecast_atmo(h, idxs))
    except Exception as e:
        _mark_error("_forecast_atmo_error", str(e))

    try:
        params = "&".join([
            f"latitude={lat}", f"longitude={lon}",
            f"start_date={start_iso}", f"end_date={end_iso}",
            "hourly=wave_height,wave_period,swell_wave_height,"
            "sea_surface_temperature,ocean_current_velocity,ocean_current_direction",
            "timezone=Asia%2FTokyo",
        ])
        data = _get_json_retry(f"{MARINE_URL}?{params}")
        h = data.get("hourly", {})
        for d, idxs in _forecast_hour_idxs_by_date(h).items():
            per_date.setdefault(d, {}).update(_agg_forecast_marine(h, idxs))
    except Exception as e:
        _mark_error("_forecast_marine_error", str(e))

    errs = per_date.pop("_error", {})
    for d, res in per_date.items():
        _FORECAST_CACHE[(ckey[0], ckey[1], d)] = dict(res, **errs)
    _FORECAST_RANGE_DONE[ckey] = end_iso


def _fetch_forecast_wx(lat: float, lon: float, date_iso: str,
                        wave_clamp_thr: float = 2.0) -> dict:
    """Open-Meteo Forecast/Marine API から翌日〜16日先の気象を取得。
    _get_daily_wx() と同じキー形式で返す。失敗時は空 dict。
    対象: 今日以降の日付（weather_cache.sqlite に存在しない将来日）

    実体は座標単位の範囲取得キャッシュ（_fetch_forecast_range）。予報上限
    （当日+15日）を超える日付は API 側が受け付けないため、範囲取得の対象外。
    """
    key = (round(lat, 3), round(lon, 3), date_iso)
    if key not in _FORECAST_CACHE:
        ckey = key[:2]
        today = _date.today()
        limit_iso = (today + timedelta(days=_FORECAST_MAX_DAYS - 1)).strftime("%Y-%m-%d")
        # 予報上限内なら座標ごとに1回だけ全期間をまとめ取り
        if date_iso <= limit_iso and _FORECAST_RANGE_DONE.get(ckey) != limit_iso:
            _fetch_forecast_range(lat, lon, today.strftime("%Y-%m-%d"), limit_iso)

    cached = _FORECAST_CACHE.get(key)
    if cached is None:
        # 予報上限外 or 範囲取得失敗。空 dict を返す（呼び出し側は部分補正に落ちる）
        return {}
    out = dict(cached)
    if "wave_height_avg" in out:
        out["wave_clamp"] = min(out["wave_height_avg"], wave_clamp_thr)
    return out


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


# ══════════════════════════════════════════════════════════════════════════════
# T44b: 学習(combo_deep_dive.enrich)と本番の因子供給ギャップ解消
#
# 背景（90_決定ログ 2026/07/16 T44）: _build_all_wx が気象・潮汐しか供給せず、
# 採用因子の実効重み供給率が中央値 33.6%（供給100%のコンボ 0件）だった。
# 以下は combo_deep_dive.py の学習側と【同一式】で計算する serve 側実装。
# ⚠ 定義がズレると z-score が狂い黙って精度が壊れる。変更時は必ず両側同時に更新し、
#    analysis/V2/analysis-improvement/t44b_parity_check.py でパリティ検証すること。
# ══════════════════════════════════════════════════════════════════════════════

# 祝日リスト（combo_deep_dive._JP_HOLIDAYS の複製。パリティチェックで同一性を検証）
_JP_HOLIDAYS = frozenset([
    # 2023
    "2023/01/01","2023/01/02","2023/01/09","2023/02/23","2023/03/21",
    "2023/04/29","2023/05/03","2023/05/04","2023/05/05",
    "2023/07/17","2023/08/11","2023/09/18","2023/09/23","2023/10/09",
    "2023/11/03","2023/11/23",
    # 2024
    "2024/01/01","2024/01/08","2024/02/12","2024/02/23","2024/03/20",
    "2024/04/29","2024/05/03","2024/05/06","2024/07/15","2024/08/12",
    "2024/09/16","2024/09/22","2024/09/23","2024/10/14",
    "2024/11/04","2024/11/23",
    # 2025
    "2025/01/01","2025/01/13","2025/02/11","2025/02/24","2025/03/20",
    "2025/04/29","2025/05/05","2025/05/06","2025/07/21","2025/08/11",
    "2025/09/15","2025/09/23","2025/10/13",
    "2025/11/03","2025/11/24",
    # 2026
    "2026/01/01","2026/01/12","2026/02/11","2026/02/23","2026/03/20",
    "2026/04/29","2026/05/04","2026/05/05","2026/05/06",
    "2026/07/20","2026/08/11","2026/09/21","2026/09/23",
    "2026/10/12","2026/11/03","2026/11/23",
])


def _build_consec_holiday_set() -> frozenset:
    """GW/盆/年末年始で3日以上連続する土日祝の日付セット（combo_deep_dive と同一実装）。"""
    from datetime import date as _date, timedelta as _td
    seasons = []
    for y in range(2023, 2027):
        seasons += [
            (_date(y, 4, 29), _date(y, 5, 6)),
            (_date(y, 8, 10), _date(y, 8, 16)),
            (_date(y - 1, 12, 28), _date(y, 1, 4)),
        ]
    result = set()
    for start, end in seasons:
        block = []
        dd = start
        while dd <= end:
            ds = dd.strftime("%Y/%m/%d")
            if dd.weekday() >= 5 or ds in _JP_HOLIDAYS:
                block.append(ds)
            dd += _td(days=1)
        if len(block) >= 3:
            result.update(block)
    return frozenset(result)


_CONSEC_HOLIDAY_SET = _build_consec_holiday_set()

# 季節マップ（combo_deep_dive._season_of と同一。suffix は enrich の因子名に対応）
_SEASON_OF_MONTH = {3: "春", 4: "春", 5: "春", 6: "夏", 7: "夏", 8: "夏",
                    9: "秋", 10: "秋", 11: "秋", 12: "冬", 1: "冬", 2: "冬"}
_SEASON_SUFFIX = (("spring", "春"), ("summer", "夏"), ("autumn", "秋"), ("winter", "冬"))


def _calendar_factors(d: datetime) -> dict:
    """日付だけで確定するカレンダー因子（enrich の load_records 側 1274-1290 と同一式）。"""
    ds = d.strftime("%Y/%m/%d")
    day = d.day
    if day <= 10:
        dod = day
    elif day <= 20:
        dod = day - 10
    else:
        dod = day - 20
    return {
        "is_holiday":         1 if (d.weekday() >= 5 or ds in _JP_HOLIDAYS) else 0,
        "is_consec_holiday":  1 if ds in _CONSEC_HOLIDAY_SET else 0,
        "is_summer_vacation": 1 if (d.month == 7 and d.day >= 21) or d.month == 8 else 0,
        "spawn_season_n":     1 if d.month in (2, 3, 4, 5) else 0,
        "day_of_decade":      dod,
    }


_TYPHOON_CACHE: dict = {}   # date_iso -> {"typhoon_dist":…, "typhoon_wind":…}


def _get_typhoon_serve(date_iso: str) -> dict:
    """combo_deep_dive.get_typhoon と同一: 台風なし日・DB なしは None（因子スキップ）。
    ⚠ typhoon.sqlite は年次更新（現在 2025-12 まで）。未収録年の台風日は None になるが、
    学習データも同じ制約のため train/serve は整合する。"""
    if date_iso in _TYPHOON_CACHE:
        return _TYPHOON_CACHE[date_iso]
    result = {"typhoon_dist": None, "typhoon_wind": None}
    if os.path.exists(DB_TYPHOON):
        try:
            c = sqlite3.connect(DB_TYPHOON)
            row = c.execute(
                "SELECT min_dist, wind_kt FROM typhoon_track "
                "WHERE date(dt) = ? ORDER BY min_dist ASC LIMIT 1", (date_iso,)).fetchone()
            c.close()
            if row:
                result = {"typhoon_dist": row[0], "typhoon_wind": row[1]}
        except Exception:
            pass
    _TYPHOON_CACHE[date_iso] = result
    return result


_SLA_MONTHLY_CACHE: dict = {}   # ym -> dict / "_no_table" マーカー


def _get_sla_monthly_serve(conn, date_iso: str) -> dict:
    """CMEMS 月次 SLA 指標（座標非依存・月単位）を serve_sla_monthly 蒸留テーブルから取得。
    テーブルは build_predict_params.py が cmems_data.sqlite（ローカル）から
    combo_deep_dive の _get_kuroshio_sla_monthly 等【本物の関数】で計算して書き出す。
    テーブル未整備・月未収録は None（従来どおり因子スキップ）。"""
    if _SLA_MONTHLY_CACHE.get("_no_table"):
        return {}
    ym = date_iso[:7]
    if ym in _SLA_MONTHLY_CACHE:
        return _SLA_MONTHLY_CACHE[ym]
    try:
        row = conn.execute(
            "SELECT kuroshio_sla_monthly, sla_pelagic_monthly, sla_approach_idx "
            "FROM serve_sla_monthly WHERE ym=?", (ym,)).fetchone()
        # 前月差分（combo_deep_dive._get_kuroshio_sla_delta_1m と同一定義: 当月 - 前月）
        y, m = int(ym[:4]), int(ym[5:7])
        prev_ym = f"{y - (m == 1):04d}-{(m - 1) or 12:02d}"
        prow = conn.execute(
            "SELECT kuroshio_sla_monthly FROM serve_sla_monthly WHERE ym=?", (prev_ym,)).fetchone()
    except Exception:
        _SLA_MONTHLY_CACHE["_no_table"] = True
        return {}
    result = {}
    if row:
        result = {"kuroshio_sla_monthly": row[0], "sla_pelagic_monthly": row[1],
                  "sla_approach_idx": row[2]}
        if row[0] is not None and prow and prow[0] is not None:
            result["kuroshio_sla_delta_1m"] = row[0] - prow[0]
        else:
            result["kuroshio_sla_delta_1m"] = None
    _SLA_MONTHLY_CACHE[ym] = result
    return result


# SST勾配の固定参照座標（combo_deep_dive.SST_GRAD_* と同一値）
_SST_GRAD_OFFSHORE = (35.65, 140.87)   # 外房沖（黒潮ライン上）
_SST_GRAD_INSHORE  = (35.3,  139.68)   # 東京湾内（沿岸代表）
_SST_GRAD_CACHE: dict = {}             # date_iso -> float|None


def _get_sst_gradient_serve(date_iso: str, is_future: bool, wave_clamp_thr: float):
    """sst_gradient = 外房沖SST - 東京湾内SST（enrich 2142-2150 と同一定義）。
    過去日=weather_cache（ローカルのみ）/ 未来日=Forecast API（固定2座標・日付キャッシュ）。"""
    if date_iso in _SST_GRAD_CACHE:
        return _SST_GRAD_CACHE[date_iso]
    off = ins = None
    try:
        if is_future:
            off = _fetch_forecast_wx(*_SST_GRAD_OFFSHORE, date_iso, wave_clamp_thr).get("sst_avg")
            ins = _fetch_forecast_wx(*_SST_GRAD_INSHORE,  date_iso, wave_clamp_thr).get("sst_avg")
        elif os.path.exists(DB_WX) and os.path.getsize(DB_WX) > 0:
            c = sqlite3.connect(DB_WX)
            for (la, lo), tgt in ((_SST_GRAD_OFFSHORE, "off"), (_SST_GRAD_INSHORE, "ins")):
                wla, wlo = _nearest_wx_coord(c, la, lo)
                v = _get_daily_wx(c, wla, wlo, date_iso, wave_clamp_thr).get("sst_avg")
                if tgt == "off":
                    off = v
                else:
                    ins = v
            c.close()
    except Exception:
        pass
    result = (off - ins) if (off is not None and ins is not None) else None
    _SST_GRAD_CACHE[date_iso] = result
    return result


_PREV_CNT_INDEX: dict | None = None   # (fish, ship) -> [(date, cnt_avg), ...] 日付昇順


_PREV_CNT_MIN_N_COMBO = 30   # combo_deep_dive.MIN_N_COMBO と同値（is_boat フィルタ発火条件）


def _load_prev_cnt_index() -> dict:
    """全 CSV を1回だけスキャンして (fish, ship) → 日付昇順 [(date, cnt_avg)] の索引を作る。
    per-combo で毎回全スキャンすると predict_daily（439コンボ）で分単位の性能事故になるため。

    学習側の参照集合を完全再現する（data-reviewer CRITICAL 指摘対応）:
    1. load_records と同じ行フィルタ（メイン・非欠航・cnt_avg>0）
    2. deep_dive の is_boat 条件付き除外（非仕立て >= MIN_N_COMBO かつ縮小するときのみ除外）
    3. deep_dive の Tukey 外れ値キャップ（Q3 + 3×IQR 超を上限に丸め・len>=4）
    ※ prev_week_cnt は学習時この前処理【後】の値を参照している。生CSVのままだと
      仕立て便の異常値を「直近釣果」として拾い z-score が狂う。
    ※ exclude 船宿は除外しない: (fish, ship) キー構造上、除外船が照会されることは
      ないため無害（意図的差分）。
    ⚠ _get_bl2 はこのフィルタを掛けていない（別用途）ので流用しない。"""
    global _PREV_CNT_INDEX
    if _PREV_CNT_INDEX is not None:
        return _PREV_CNT_INDEX
    import csv as _csv, glob as _glob
    raw: dict = {}   # (fish, ship) -> [(date, cnt, is_boat)] CSV読み込み順
    for path in sorted(_glob.glob(os.path.join(DATA_DIR, "*.csv"))):
        if os.path.basename(path) == "cancellations.csv":   # load_records と同一
            continue
        try:
            with open(path, encoding="utf-8") as f:
                for row in _csv.DictReader(f):
                    if row.get("is_cancellation") == "1" or row.get("main_sub") != "メイン":
                        continue
                    dd = row.get("date", "")
                    if not dd:
                        continue
                    try:
                        v = float(row.get("cnt_avg", ""))
                    except (ValueError, TypeError):
                        continue
                    if v <= 0:
                        continue
                    b = 1 if (row.get("is_boat") or "").strip() == "1" else 0
                    key = ((row.get("tsuri_mono") or "").strip(), (row.get("ship") or "").strip())
                    raw.setdefault(key, []).append((dd, v, b))
        except (OSError, UnicodeDecodeError, _csv.Error):
            continue
    idx: dict = {}
    for k, rows in raw.items():
        # deep_dive 6107-6111 と同一: 非仕立てが MIN_N_COMBO 以上かつ縮小するときのみ除外
        noboat = [(dd, v) for dd, v, b in rows if b == 0]
        use = noboat if (len(noboat) >= _PREV_CNT_MIN_N_COMBO and len(noboat) < len(rows)) \
            else [(dd, v) for dd, v, _ in rows]
        # deep_dive 6114-6125 と同一: Tukey 法（Q3 + 3×IQR）で上限キャップ
        cnts = sorted(v for _, v in use)
        if len(cnts) >= 4:
            q1 = cnts[len(cnts) // 4]
            q3 = cnts[3 * len(cnts) // 4]
            cap = q3 + 3 * (q3 - q1)
            use = [(dd, min(v, cap)) for dd, v in use]
        # enrich 2018 と同一の安定ソート（date キーのみ）。タプル比較でソートすると
        # 同日複数便の並びが「値順」になり、学習側の「CSV読み込み順で最後の便」と食い違う
        # （パリティ検証で 5/75 不一致・max差43 を実測 → 本方式で解消）
        use.sort(key=lambda x: x[0])
        idx[k] = ([dd for dd, _ in use], [v for _, v in use])
    _PREV_CNT_INDEX = idx
    return idx


def _get_prev_week_cnt(fish: str, ship: str, before_date: str | None = None):
    """prediction 時点で知っている同コンボ最新の cnt_avg（enrich 2180-2191 と同一定義）。
    before_date: 省略時=今日（本番）。パリティ検証時に過去日を指定する。"""
    if before_date is None:
        before_date = datetime.today().strftime("%Y/%m/%d")
    entry = _load_prev_cnt_index().get((fish, ship))
    if not entry:
        return None
    dates, vals = entry
    import bisect as _bisect
    i = _bisect.bisect_left(dates, before_date) - 1
    return vals[i] if i >= 0 else None


def _augment_all_wx(all_wx: dict, d: datetime, date_iso: str, is_future: bool,
                    wave_clamp_thr: float, conn=None, fish=None, ship=None) -> None:
    """_build_all_wx の結果に enrich 相当の派生・外部因子を追記する（in-place）。
    ベース値（wave_clamp/sst_avg/tide_type_n）が確定した後に呼ぶこと。"""
    # ── カレンダー因子（SLOW・日付のみで確定）───────────────────────────────
    all_wx.update(_calendar_factors(d))
    _ssn = _SEASON_OF_MONTH[d.month]
    # ── wave_clamp / sst × 季節交互作用（enrich 2301-2313: None は 0.0 扱い）──
    _wc_val = all_wx.get("wave_clamp") or 0.0
    _sst_val = all_wx.get("sst_avg") or 0.0
    for _sfx, _jp in _SEASON_SUFFIX:
        all_wx[f"wave_clamp_{_sfx}"] = _wc_val if _ssn == _jp else 0.0
        all_wx[f"sst_{_sfx}"]        = _sst_val if _ssn == _jp else 0.0
    # ── 潮汐×季節（enrich 2341-2358: tide_type_n 欠損時は None）──────────────
    _ttn = all_wx.get("tide_type_n")
    for _grp, _flag in (("oshio",   None if _ttn is None else (1 if _ttn == 4 else 0)),
                        ("chusho",  None if _ttn is None else (1 if _ttn in (2, 3) else 0)),
                        ("chowaka", None if _ttn is None else (1 if _ttn == 1 else 0))):
        for _sfx, _jp in _SEASON_SUFFIX:
            all_wx[f"tide_grp_{_grp}_{_sfx}"] = (
                None if _flag is None else (_flag if _ssn == _jp else 0))
    # ── 台風（FAST・H>7 は _apply_correction_from_params 側で除外される）──────
    all_wx.update(_get_typhoon_serve(date_iso))
    # ── CMEMS 月次 SLA（SLOW・蒸留テーブル経由）────────────────────────────
    if conn is not None:
        all_wx.update(_get_sla_monthly_serve(conn, date_iso))
    # ── SST 勾配（SLOW・固定2座標）─────────────────────────────────────────
    all_wx["sst_gradient"] = _get_sst_gradient_serve(date_iso, is_future, wave_clamp_thr)
    # ── 前週釣果（FAST・fish/ship 固有。コンボ横断キャッシュ厳禁）────────────
    if fish and ship:
        all_wx["prev_week_cnt"] = _get_prev_week_cnt(fish, ship)


def _get_multi_point_factors(fish: str, ship: str) -> list:
    """combo_multi_point_factors から有意因子を取得。なければ空リスト。"""
    if not os.path.exists(DB_PATH):
        return []
    try:
        con = sqlite3.connect(DB_PATH)
        rows = con.execute(
            """SELECT factor, r, threshold, direction, n_multi, n_single
               FROM combo_multi_point_factors
               WHERE fish=? AND ship=?
               ORDER BY ABS(r) DESC""",
            (fish, ship)
        ).fetchall()
        con.close()
        return [{"factor": r[0], "r": r[1], "threshold": r[2],
                 "direction": r[3], "n_multi": r[4], "n_single": r[5]}
                for r in rows]
    except Exception:
        return []


def _get_multi_point_context(fish: str, ship: str) -> dict:
    """
    combo_multi_point_context から good/bad 両方向の因子を取得。
    {"bad": [...], "good": [...]} を返す。
    テーブルがなければ / 該当行なければ空リストを含む dict を返す。
    """
    result = {"bad": [], "good": []}
    if not os.path.exists(DB_PATH):
        return result
    try:
        con = sqlite3.connect(DB_PATH)
        rows = con.execute(
            """SELECT factor, r_bad, r_good, threshold_bad, threshold_good,
                      dir_bad, dir_good, n_multi_bad, n_multi_good, n_single
               FROM combo_multi_point_context
               WHERE fish=? AND ship=?
               ORDER BY ABS(r_bad) DESC""",
            (fish, ship)
        ).fetchall()
        con.close()
        for r in rows:
            base = {"factor": r[0], "n_bad": r[7], "n_good": r[8], "n_single": r[9]}
            if r[1] is not None and r[3] is not None and r[5] is not None:
                result["bad"].append({**base, "r": r[1], "threshold": r[3], "direction": r[5]})
            if r[2] is not None and r[4] is not None and r[6] is not None:
                result["good"].append({**base, "r": r[2], "threshold": r[4], "direction": r[6]})
    except Exception:
        pass
    return result


def _calc_multi_point_risk(wx_vals: dict, factors: list) -> tuple:
    """
    予報値 wx_vals と combo_multi_point_factors を照合し、
    複数ポイント移動リスクスコア（0.0〜1.0）と補正係数を返す。

    ロジック:
      各因子について、threshold を越えているか判定:
        high_is_multi: wx_val >= threshold → multi寄り
        low_is_multi:  wx_val <= threshold → multi寄り
      ヒット数と |r| の加重平均でスコアを算出。
      スコア 0.0=リスクなし / 1.0=全因子がmulti方向。

    返す補正係数:
      risk < 0.3  → 1.0（補正なし）
      0.3〜0.6   → 線形補間 1.0〜0.75
      0.6〜1.0   → 線形補間 0.75〜0.55

    戻り値: (補正係数 float, リスクスコア float)
    """
    if not factors or not wx_vals:
        return 1.0, 0.0

    hits = []
    weights = []
    for f in factors:
        val = wx_vals.get(f["factor"])
        if val is None:
            continue
        thr = f["threshold"]
        is_multi = (f["direction"] == "high_is_multi" and val >= thr) or \
                   (f["direction"] == "low_is_multi"  and val <= thr)
        hits.append(1.0 if is_multi else 0.0)
        weights.append(abs(f["r"]))

    if not hits:
        return 1.0, 0.0

    # 加重平均リスクスコア
    risk = sum(h * w for h, w in zip(hits, weights)) / sum(weights)

    # 補正係数
    if risk < 0.3:
        correction = 1.0
    elif risk < 0.6:
        correction = 1.0 - (risk - 0.3) / 0.3 * 0.25   # 1.0→0.75
    else:
        correction = 0.75 - (risk - 0.6) / 0.4 * 0.20  # 0.75→0.55

    return max(0.55, correction), risk


def _calc_multi_point_context_correction(wx_vals: dict, context: dict) -> tuple:
    """
    combo_multi_point_context の good/bad 両方向因子から補正係数を算出。

    bad方向: 複数移動 = 不漁探索 → 下方補正 (0.55〜1.0)
    good方向: 複数移動 = 積極追い → 上方補正 (1.0〜1.25)
    最終補正 = bad補正 × good補正、上限1.4 / 下限0.55

    戻り値: (最終補正係数, bad_risk, good_risk)
    """
    def _score(factors, high_key: str, low_key: str):
        if not factors or not wx_vals:
            return 0.0
        hits, weights = [], []
        for f in factors:
            val = wx_vals.get(f["factor"])
            if val is None:
                continue
            thr = f["threshold"]
            is_hit = (f["direction"] == high_key and val >= thr) or \
                     (f["direction"] == low_key   and val <= thr)
            hits.append(1.0 if is_hit else 0.0)
            weights.append(abs(f["r"]))
        if not hits:
            return 0.0
        return sum(h * w for h, w in zip(hits, weights)) / sum(weights)

    bad_risk  = _score(context.get("bad",  []), "high_is_bad",  "low_is_bad")
    good_risk = _score(context.get("good", []), "high_is_good", "low_is_good")

    # bad補正: risk<0.3→1.0, 0.3〜0.6→1.0〜0.75, 0.6〜1.0→0.75〜0.55
    if bad_risk < 0.3:
        bad_corr = 1.0
    elif bad_risk < 0.6:
        bad_corr = 1.0 - (bad_risk - 0.3) / 0.3 * 0.25
    else:
        bad_corr = 0.75 - (bad_risk - 0.6) / 0.4 * 0.20

    # good補正: risk<0.3→1.0, 0.3〜0.6→1.0〜1.15, 0.6〜1.0→1.15〜1.25
    if good_risk < 0.3:
        good_corr = 1.0
    elif good_risk < 0.6:
        good_corr = 1.0 + (good_risk - 0.3) / 0.3 * 0.15
    else:
        good_corr = 1.15 + (good_risk - 0.6) / 0.4 * 0.10

    final_corr = max(0.55, min(1.40, bad_corr * good_corr))
    return final_corr, round(bad_risk, 3), round(good_risk, 3)


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
                   wave_clamp_thr: float,
                   conn=None, fish: str | None = None, ship: str | None = None) -> tuple[dict, bool, str]:
    """当日・前日・7日前の気象データを構築して返す。
    戻り値: (all_wx dict, is_future bool, wx_source str)
    combo/ポイント両モデルで共用する。
    T44b: conn/fish/ship を渡すとカレンダー・季節交互作用・台風・CMEMS月次・SST勾配・
    前週釣果も enrich と同一式で追記する（因子供給ギャップ解消）。
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

    # T44b: enrich 相当の派生・外部因子を追記（ベース値確定後・最後に実行）
    _augment_all_wx(all_wx, d, date_iso, is_future, wave_clamp_thr,
                    conn=conn, fish=fish, ship=ship)

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
    all_wx, is_future, wx_source = _build_all_wx(wx_lat, wx_lon, target_date, wave_clamp_thr, conn=conn, fish=fish, ship=ship)
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


def _slot_group_for_predict(time_slot: str) -> str:
    """time_slot → PDT モデルのスロットグループに変換。"""
    if time_slot in ("夜",):
        return "夜"
    if time_slot in ("朝", "午前", "ショート"):
        return "朝系"
    if time_slot in ("午後",):
        return "午後"
    return ""


def _predict_pdt_key(conn, fish: str, ship: str, point: str, time_slot: str):
    """combo_pdt_backtest から (point, depth_band, slot) の最良キーを返す。
    BL2比 5pt 以上改善するキーのみ採用。slot 一致 > 全便 の順で探す。
    """
    sl = _slot_group_for_predict(time_slot)
    try:
        # slot が一致するキーを優先
        for slot_q in ([sl, ""] if sl else [""]):
            row = conn.execute(
                """SELECT point, depth_band, slot, (bl2_wmape - wmape) as imp
                   FROM combo_pdt_backtest
                   WHERE fish=? AND ship=? AND point=? AND slot=?
                     AND horizon=0 AND metric='cnt_avg'
                     AND bl2_wmape IS NOT NULL AND wmape IS NOT NULL
                   ORDER BY imp DESC LIMIT 1""",
                (fish, ship, point, slot_q)
            ).fetchone()
            if row and row[3] is not None and row[3] >= 5.0:
                return (row[0], row[1], row[2])
    except Exception:
        pass
    return None


def _apply_pdt_wx_correction(conn, fish: str, ship: str,
                              point: str, depth_band: str, slot: str,
                              target_date: str, baseline_cnt: float,
                              lat: float, lon: float,
                              metric: str = 'cnt_avg') -> float | None:
    """combo_pdt_wx_params の PDT モデルで補正を計算。パラメータなければ None。"""
    try:
        rows = conn.execute(
            "SELECT factor, mean, std, r, alpha_scale, met_mean, met_std, lat, lon "
            "FROM combo_pdt_wx_params "
            "WHERE fish=? AND ship=? AND point=? AND depth_band=? AND slot=? AND metric=?",
            (fish, ship, point, depth_band, slot, metric)
        ).fetchall()
    except Exception:
        return None
    if not rows:
        return None
    meta = None; factor_params = {}; wx_lat = lat; wx_lon = lon
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
    all_wx, _, _ = _build_all_wx(wx_lat, wx_lon, target_date, wave_clamp_thr, conn=conn, fish=fish, ship=ship)
    return _apply_correction_from_params(factor_params, meta, all_wx, baseline_cnt, _h_days(target_date))


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
    all_wx, _, _ = _build_all_wx(wx_lat, wx_lon, target_date, wave_clamp_thr, conn=conn, fish=fish, ship=ship)
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
    all_wx, _, _ = _build_all_wx(wx_lat, wx_lon, target_date, wave_clamp_thr, conn=conn, fish=fish, ship=ship)
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
    all_wx, _, _ = _build_all_wx(wx_lat, wx_lon, target_date, wave_clamp_thr, conn=conn, fish=fish, ship=ship)
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
    all_wx, _, _ = _build_all_wx(wx_lat, wx_lon, target_date, wave_clamp_thr, conn=conn, fish=fish, ship=ship)
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

    # 旬別ベースライン（avg_cnt_min/max + avg_size_min/max も取得）
    # avg_size_min / avg_size_max は Phase B-α' で追加（旬別実測幅ベースのレンジ生成用）
    row = conn.execute(
        "SELECT avg_cnt, avg_size, avg_kg, n, avg_cnt_min, avg_cnt_max, "
        "avg_size_min, avg_size_max, avg_kg_min, avg_kg_max FROM combo_decadal "
        "WHERE fish=? AND ship=? AND decade_no=?",
        (fish, ship, dekad)
    ).fetchone()

    if row:
        avg_cnt, avg_size, avg_kg, n_dekad, avg_cnt_min, avg_cnt_max, \
            avg_size_min_dec, avg_size_max_dec, avg_kg_min_dec, avg_kg_max_dec = row
        fallback = False
    else:
        # 最近傍旬（±3以内）にフォールバック
        near = conn.execute(
            "SELECT decade_no, avg_cnt, avg_size, avg_kg, n, avg_cnt_min, avg_cnt_max, "
            "avg_size_min, avg_size_max, avg_kg_min, avg_kg_max "
            "FROM combo_decadal "
            "WHERE fish=? AND ship=? ORDER BY ABS(decade_no - ?) LIMIT 1",
            (fish, ship, dekad)
        ).fetchone()
        if not near or abs(near[0] - dekad) > 3:
            return None
        avg_cnt, avg_size, avg_kg, n_dekad = near[1], near[2], near[3], near[4]
        avg_cnt_min, avg_cnt_max = near[5], near[6]
        avg_size_min_dec, avg_size_max_dec = near[7], near[8]
        avg_kg_min_dec, avg_kg_max_dec = near[9], near[10]   # Phase B-β-4 追加
        fallback = True

    # Phase B-β-4: 旬別 avg_kg_min/max が NULL の場合に使う魚種別グローバル比率（案 A）
    # combo_decadal から当該魚種の全旬平均を計算（非 NULL 旬のみ）
    if avg_kg_min_dec is None or avg_kg_max_dec is None:
        _fish_global = conn.execute(
            "SELECT AVG(avg_kg_min), AVG(avg_kg_max) FROM combo_decadal "
            "WHERE fish=? AND avg_kg_min IS NOT NULL",
            (fish,)
        ).fetchone()
        if _fish_global and _fish_global[0] is not None:
            if avg_kg_min_dec is None:
                avg_kg_min_dec = _fish_global[0]
            if avg_kg_max_dec is None:
                avg_kg_max_dec = _fish_global[1]

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

    # ── PDT補正（ポイント×水深帯×時間帯 combo_pdt_wx_params があれば優先） ──────
    # 優先チェーン: combo < point < water_color < point_depth < PDT < trip（最高優先）
    predicted_pdt = None
    if lat and lon and not use_fb and predicted_point:
        pdt_key = _predict_pdt_key(conn, fish, ship, predicted_point, time_slot)
        if pdt_key:
            pdt_cnt = _apply_pdt_wx_correction(
                conn, fish, ship, pdt_key[0], pdt_key[1], pdt_key[2],
                target_date, avg_cnt, lat, lon, 'cnt_avg'
            )
            if pdt_cnt is not None:
                cnt_predicted = pdt_cnt
                predicted_pdt = pdt_key

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

    # ── 複数ポイント移動補正（bad下方 + good上方）────────────────────────────
    # combo_multi_point_context に登録がある場合:
    #   bad方向: 不漁探索移動パターン → 下方補正 (最小0.55)
    #   good方向: 積極追い移動パターン → 上方補正 (最大1.25)
    # use_fallback=True のコンボはスキップ。
    multi_point_risk      = 0.0
    multi_point_good_risk = 0.0
    multi_point_corr      = 1.0
    if lat and lon and not use_fb:
        mp_context = _get_multi_point_context(fish, ship)
        if mp_context["bad"] or mp_context["good"]:
            wave_clamp_thr_mp = _get_wave_clamp_thr(conn, fish, ship)
            all_wx_mp, _, _ = _build_all_wx(lat, lon, target_date, wave_clamp_thr_mp, conn=conn, fish=fish, ship=ship)
            mp_correction, mp_bad_risk, mp_good_risk = _calc_multi_point_context_correction(
                all_wx_mp, mp_context)
            if mp_correction != 1.0:
                cnt_predicted = round(cnt_predicted * mp_correction, 1)
                multi_point_risk      = mp_bad_risk
                multi_point_good_risk = mp_good_risk
                multi_point_corr      = round(mp_correction, 3)
        else:
            # context テーブルなし → 旧テーブル（bad のみ）にフォールバック
            mp_factors = _get_multi_point_factors(fish, ship)
            if mp_factors:
                wave_clamp_thr_mp = _get_wave_clamp_thr(conn, fish, ship)
                all_wx_mp, _, _ = _build_all_wx(lat, lon, target_date, wave_clamp_thr_mp, conn=conn, fish=fish, ship=ship)
                mp_correction, mp_risk = _calc_multi_point_risk(all_wx_mp, mp_factors)
                if mp_correction < 1.0:
                    cnt_predicted = round(cnt_predicted * mp_correction, 1)
                    multi_point_risk = round(mp_risk, 3)
                    multi_point_corr = round(mp_correction, 3)

    # ── min/max 予測（trip 優先 → ratio 法） ────────────────────────────────
    # 優先1 (trip): predicted_trip_no が確定している場合は便別 cnt_min/cnt_max モデルを使用
    #               （便別補正は cnt_avg と同様に最高優先チェーンの末尾）
    # 標準 (ratio): avg_cnt_min/max の旬別比率を cnt_predicted に適用
    #       → 旬別データもない場合は ±cnt_mae で信頼区間
    #
    # T44 判定（2026/07/16・90_決定ログ）: 旧「優先2 (combo直接モデル)」は全コンボ実測で
    # ratio 法に敗北したため無効化（promise_break P50 11.1% vs 6.1% / coverage 66.9% vs 79.3%）。
    # 旧コメントの「ratio法より Coverage が良い可能性が高い」は誤りと実証された。
    # winkler は直接モデル勝ちだが「レンジが狭い＝約束を破りやすい」の裏返しで、
    # PRIMARY KPI（約束割れ回避）に反するため採用しない。再評価する場合は下のフラグを戻し
    # combo_range_backtest の metric='cnt_direct' 系列で同一定義比較すること。
    _CNT_RANGE_USE_DIRECT = False
    cnt_lo = cnt_hi = None

    if lat and lon and not use_fb and predicted_trip_no:
        # trip 優先: 便別モデルで cnt_min / cnt_max を直接予測
        bl_min = avg_cnt_min if avg_cnt_min is not None else avg_cnt * 0.5
        bl_max = avg_cnt_max if avg_cnt_max is not None else avg_cnt * 1.5
        trip_lo = _apply_trip_wx_correction(
            conn, fish, ship, predicted_trip_no, target_date, bl_min, lat, lon, 'cnt_min')
        trip_hi = _apply_trip_wx_correction(
            conn, fish, ship, predicted_trip_no, target_date, bl_max, lat, lon, 'cnt_max')
        if trip_lo is not None:
            cnt_lo = round(max(0, trip_lo * slot_ratio), 1)
        if trip_hi is not None:
            cnt_hi = round(trip_hi * slot_ratio, 1)

    if _CNT_RANGE_USE_DIRECT and (cnt_lo is None or cnt_hi is None) and lat and lon and not use_fb:
        # combo直接モデル（T44 で無効化・再評価用に保持）
        bl_min = avg_cnt_min if avg_cnt_min is not None else avg_cnt * 0.5
        bl_max = avg_cnt_max if avg_cnt_max is not None else avg_cnt * 1.5
        pred_lo_direct = _apply_wx_correction(conn, fish, ship, target_date, bl_min, lat, lon,
                                              metric='cnt_min')
        pred_hi_direct = _apply_wx_correction(conn, fish, ship, target_date, bl_max, lat, lon,
                                              metric='cnt_max')
        # _apply_wx_correction はパラメータなければ baseline をそのまま返す
        # → trip 経路で片方だけ None になったケースも両方 combo で統一する
        if cnt_lo is None:
            cnt_lo = round(max(0, pred_lo_direct * slot_ratio), 1)
        if cnt_hi is None:
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

    # ── size ポイント別補正（combo_point_wx_params metric='size_avg' を利用） ──
    # 学習側（combo_deep_dive.py）は既に size_avg のポイント別パラメータを保存済み。
    # cnt 補正で決定した predicted_point を再利用して size を補正する。
    # point=None / lat=None / パラメータなし の場合は avg_size のまま（フォールバック）。
    # キーカバレッジ: combo_point_events 256種 vs combo_point_wx_params(size_avg) 90種 → 交差 72種（28%）。
    #   交差外は _apply_point_wx_correction が None を返し、avg_size baseline のまま使用される。
    # n ガードは学習側の alpha_scale clip [0,1.2] に委譲（明示的 n_min なし）。
    size_avg_corrected = avg_size
    if avg_size and lat and lon and not use_fb and predicted_point:
        pt_size = _apply_point_wx_correction(
            conn, fish, ship, predicted_point, target_date, avg_size, lat, lon, 'size_avg'
        )
        if pt_size is not None:
            size_avg_corrected = max(0.0, pt_size)  # サイズは負値にならない（cnt 側 max(0,...) と同型ガード）

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
        "size_predicted":  round(size_avg_corrected, 1) if size_avg_corrected else None,
        # Phase B-α': 実測比率ベースのレンジ生成 (2026-05-08 補遺7 確定)
        # avg_size_min_dec = 旬別 (size_min/size_avg) の P20 比率（combo_decadal に格納）
        # avg_size_max_dec = 旬別 (size_max/size_avg) の P80 比率（combo_decadal に格納）
        # size_lo = pred_avg × avg_size_min_dec  （≡ pred_avg × P20_ratio）
        # size_hi = pred_avg × avg_size_max_dec  （≡ pred_avg × P80_ratio）
        # → promise_break(actual_size_min < pred_lo) の期待値 ≈ 20%
        # → pred_avg はポイント別補正済みの値を使用（比率なので補正量は比例して維持）
        # フォールバック: avg_size_min/max_dec が NULL または 0（combo_deep_dive 再実行前等）は ±size_mae
        # ゼロガード: avg_size_min_dec=0 は ratio=0 で pred_lo=0cm（物理的に不正）→ フォールバック
        # ゼロガード: avg_size_max_dec=0 は ratio=0 で pred_hi=0cm（物理的に不正）→ フォールバック
        "size_lo": (
            round(size_avg_corrected * avg_size_min_dec, 1)
            if size_avg_corrected and avg_size_min_dec is not None and avg_size_min_dec > 0
            else (round(size_avg_corrected - size_mae, 1) if size_avg_corrected and size_mae else None)
        ),
        "size_hi": (
            round(size_avg_corrected * avg_size_max_dec, 1)
            if size_avg_corrected and avg_size_max_dec is not None and avg_size_max_dec > 0
            else (round(size_avg_corrected + size_mae, 1) if size_avg_corrected and size_mae else None)
        ),
        "kg_predicted":    round(avg_kg, 2) if avg_kg else None,
        # Phase B-β-4: 比率ベース（avg_kg × 旬別 P20/P80 比率）
        # フォールバック: 旬別・魚種別グローバルとも NULL なら旧設計（±kg_mae）
        "kg_lo": (
            round(avg_kg * avg_kg_min_dec, 2)
            if avg_kg and avg_kg_min_dec is not None and avg_kg_min_dec > 0
            else (round(max(0.0, avg_kg - kg_mae), 2) if avg_kg and kg_mae else None)
        ),
        "kg_hi": (
            round(avg_kg * avg_kg_max_dec, 2)
            if avg_kg and avg_kg_max_dec is not None and avg_kg_max_dec > 0
            else (round(avg_kg + kg_mae, 2) if avg_kg and kg_mae else None)
        ),
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
        # 複数ポイント移動補正（bad下方 / good上方。補正係数1.0=補正なし）
        "multi_point_risk":        multi_point_risk,       # 0.0〜1.0 bad方向リスクスコア
        "multi_point_good_risk":   multi_point_good_risk,  # 0.0〜1.0 good方向チャンススコア
        "multi_point_correction":  multi_point_corr,       # 0.55〜1.40 統合補正係数
        # メタ
        "n_total":         n_total,
        "n_dekad":         n_dekad,
        "lat":                    lat,
        "lon":                    lon,
        "predicted_point":        predicted_point,
        "predicted_point_depth":  predicted_point_depth,   # {point}_{depth_band} or None
        "predicted_water_color":  predicted_water_color,   # 澄み/濁り/"" (water_color_daily予測)
        "predicted_pdt":          predicted_pdt,           # (point, depth_band, slot) or None
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

    # ⚠ _FORECAST_CACHE はここでクリアしない（2026-07-21）。
    # キャッシュキーに date_iso が入っているため日付違いの取り違えは起こらず、
    # クリアすると predict_daily のように predict_all を複数ホライズン分
    # 連続で呼ぶ経路で毎回全座標を取り直してしまう（CI で約85分）。
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

        # 便別最良モデルマップ: (fish, ship) -> trip_no（H=0, n>=30, wmape 最小便）
        # combo_trip_backtest が存在しない場合は空 dict（trip_no=0 フォールバックへ）
        best_trip_map: dict = {}
        try:
            trip_rows = conn.execute(
                """SELECT fish, ship, trip_no, wmape
                   FROM combo_trip_backtest
                   WHERE metric='cnt_avg' AND horizon=0 AND n >= 30
                     AND wmape IS NOT NULL"""
            ).fetchall()
            for f, s, tn, wm in trip_rows:
                if (f, s) not in best_trip_map or wm < best_trip_map[(f, s)][1]:
                    best_trip_map[(f, s)] = (tn, wm)
            # (fish, ship) -> trip_no だけを残す
            best_trip_map = {k: v[0] for k, v in best_trip_map.items()}
        except Exception:
            best_trip_map = {}

        print(f"best_trip_map: {len(best_trip_map)}件 先頭3: {list(best_trip_map.items())[:3]}")

        results = []
        for f, s in combos:
            best_tn = best_trip_map.get((f, s), 0)
            r = predict_combo(conn, f, s, target_date, trip_no=best_tn)
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
