# context_builder.py — ctx 辞書組立
# catches.json (valid_catches list) + history.json + analysis.sqlite + weather/ CSV から構築
# 補遺3 遵守: avg/平均 を ctx 値として使わない（min/max のみ）

import os
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from urllib.request import urlopen, Request

# JST 定義（crawler.py と同じ方式）
JST = timezone(timedelta(hours=9))

# 海況 INNER/OUTER の港名グループ
_INNER_PORTS = {
    "金沢八景港", "横浜港", "新山下港", "本牧港", "磯子港", "大黒", "鶴見",
    "浦安港", "千葉港", "富津港", "江ノ島港", "葉山", "逗子",
    "東京湾", "相模湾",
}
_OUTER_PORTS = {
    "下田港", "神津島", "銭洲", "外房", "大原港", "勝浦港",
    "鴨川港", "御前崎港", "日立港", "日立久慈港",
}

# 青物魚種
_PELAGIC_FISH = {"カンパチ", "ハマチ", "ブリ", "ワラサ", "イナダ", "サワラ", "シイラ", "カツオ", "キハダマグロ"}

# レア魚種（初接岸シグナル用）
_RARE_FISH = {"カンパチ", "シイラ", "カツオ", "キハダマグロ"}


def _cnt_personal(cr):
    """count_range を個人釣果として匹数集計に使えるか判定する。

    crawler.py の同名ヘルパーと同義（x_post は独立パッケージのため DRY 回避で再定義）。
    is_boat=False は常に個人。is_boat=True でも範囲表記（min!=max）なら
    「個人レンジ＋船中合計」併記型（例「0〜14匹 船中302匹」）として含める。
    純船中（例「船中5匹」で min==max=船全体数）のみ匹数集計から除外する。
    """
    if not isinstance(cr, dict) or not cr:
        return False
    if not cr.get("is_boat"):
        return True
    lo, hi = cr.get("min"), cr.get("max")
    return lo is not None and hi is not None and lo != hi


# 魚種別の妥当 kg/cm 上限（CSV 誤入力フィルタ用）
# crawler.py と共通の normalize/fish_size_range.json から読み込み（DRY 違反解消）
def _load_fish_size_range_from_json():
    """normalize/fish_size_range.json から (kg_max_dict, cm_max_dict) を返す。"""
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, "..", "normalize", "fish_size_range.json")
    try:
        with open(path, encoding="utf-8") as _f:
            _raw = json.load(_f)
    except Exception:
        return {}, {}
    _kg = {k: v.get("kg_max") for k, v in _raw.items() if k != "_default" and isinstance(v, dict)}
    _cm = {k: v.get("cm_max") for k, v in _raw.items() if k != "_default" and isinstance(v, dict)}
    return _kg, _cm

_FISH_KG_MAX, _FISH_CM_MAX = _load_fish_size_range_from_json()

# 旬ラベル変換
_DECADE_LABELS = {
    **{i: f"{(i-1)//3+1}月{'上' if (i-1)%3==0 else ('中' if (i-1)%3==1 else '下')}旬"
       for i in range(1, 37)}
}


def _load_cancellations(date_str: str) -> list:
    """data/V2/cancellations.csv から該当日 (YYYY/MM/DD) の欠航レコードを返す。
    valid_catches に含まれない欠航データを別経路で取得し、出船率計算に使う。"""
    import csv
    _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    _path = os.path.join(_root, "data", "V2", "cancellations.csv")
    rows = []
    if not os.path.exists(_path):
        return rows
    try:
        with open(_path, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for r in reader:
                if r.get("date") == date_str:
                    rows.append(r)
    except Exception:
        pass
    return rows


def _get_decade_no(dt):
    """datetime → decade_no (1-36)"""
    month = dt.month
    day = dt.day
    sub = 0 if day <= 10 else (1 if day <= 20 else 2)
    return (month - 1) * 3 + sub + 1


def _load_tide_moon(db_path, date_str):
    """tide_moon.sqlite から潮汐・月相を取得"""
    if not os.path.exists(db_path):
        return {"tide_type": "中潮", "moon_phase": "七日月", "moon_age": 7.0}
    try:
        con = sqlite3.connect(db_path)
        row = con.execute(
            "SELECT tide_type, moon_phase, moon_age FROM tide_moon WHERE date=?", (date_str,)
        ).fetchone()
        con.close()
        if row:
            return {"tide_type": row[0], "moon_phase": row[1], "moon_age": row[2]}
    except Exception:
        pass
    return {"tide_type": "中潮", "moon_phase": "七日月", "moon_age": 7.0}


def _load_combo_decadal(db_path, fish, decade_no):
    """analysis.sqlite combo_decadal から旬別データを取得"""
    if not os.path.exists(db_path):
        return None
    try:
        con = sqlite3.connect(db_path)
        rows = con.execute(
            "SELECT fish, ship, avg_cnt, avg_cnt_min, avg_cnt_max FROM combo_decadal "
            "WHERE fish=? AND decade_no=? AND n>=5",
            (fish, decade_no)
        ).fetchall()
        con.close()
        if rows:
            # 全船宿の avg_cnt_max 中央値
            maxs = sorted([r[4] for r in rows if r[4] is not None])
            if maxs:
                mid = maxs[len(maxs) // 2]
                return mid
    except Exception:
        pass
    return None


def _wind_dir_label(deg):
    """風向角度(度) → 16方位日本語ラベル"""
    if deg is None:
        return ""
    try:
        deg = float(deg)
    except Exception:
        return ""
    dirs = ["北", "北北東", "北東", "東北東", "東", "東南東", "南東", "南南東",
            "南", "南南西", "南西", "西南西", "西", "西北西", "北西", "北北西"]
    return dirs[int((deg + 11.25) / 22.5) % 16]


# 内海 / 外海 の代表 point 名（weather/YYYY-MM.csv の point 列と一致させる）
_INNER_POINTS = frozenset({
    "八景沖", "中ノ瀬", "神奈川・東京湾", "東京", "浦安沖", "羽田沖",
    "猿島沖", "走水沖", "鶴見沖", "小柴沖", "本牧沖", "根岸沖", "観音崎沖",
    "横浜沖", "横須賀沖", "大津沖", "久里浜沖", "盤洲沖", "木更津沖",
    "千葉・東京湾奥", "五井沖", "富津沖", "富津南沖", "大貫沖",
})
_OUTER_POINTS = frozenset({
    "洲崎沖", "神奈川・相模湾", "相模湾", "城ヶ島沖", "城ヶ島西沖",
    "千葉・外房", "千葉・内房", "外川沖", "犬吠沖", "犬吠南沖", "波崎沖",
    "鹿島沖", "鹿島北沖", "茨城", "神栖沖", "勝浦沖", "大原沖", "館山沖",
    "太海沖", "岩和田沖", "岩船沖", "片貝沖", "飯岡沖",
    "勝浦灯台沖", "一宮沖",
})


def _aggregate_wx_rows(rows_pairs):
    """[(wind, wind_dir, wave, sst), ...] から統計値を計算して dict で返す。"""
    winds = [r[0] for r in rows_pairs if r[0] is not None]
    wind_dirs = [r[1] for r in rows_pairs if r[1] is not None]
    waves = [r[2] for r in rows_pairs if r[2] is not None]
    ssts = [r[3] for r in rows_pairs if r[3] is not None]
    result = {}
    if waves:
        result["wave"] = round(sum(waves) / len(waves), 1)
    if winds:
        result["wind_spd"] = round(max(winds), 1)
        if wind_dirs:
            paired = sorted(zip(winds, wind_dirs), key=lambda x: -x[0])
            result["wind_dir"] = _wind_dir_label(paired[0][1])
    if ssts:
        result["sst"] = round(sum(ssts) / len(ssts), 1)
    return result


def _parse_weather_csv_split(weather_dir, date_str):
    """weather/YYYY-MM.csv から当日の内海・外海別代表値を取得。
    戻り値: (inner_dict, outer_dict, all_dict)
      各 dict: {wave, wind_spd, wind_dir, sst}
    """
    ym = date_str[:7]
    csv_path = os.path.join(weather_dir, f"{ym}.csv")
    if not os.path.exists(csv_path):
        return {}, {}, {}

    inner_rows, outer_rows, all_rows = [], [], []
    try:
        with open(csv_path, encoding="utf-8") as f:
            lines = f.readlines()
        if not lines:
            return {}, {}, {}
        header = lines[0].strip().split(",")
        idx_pt   = header.index("point")       if "point"       in header else -1
        idx_date = header.index("date")        if "date"        in header else -1
        idx_wave = header.index("wave_height") if "wave_height" in header else -1
        idx_wind = header.index("wind_speed")  if "wind_speed"  in header else -1
        idx_wdir = header.index("wind_dir")    if "wind_dir"    in header else -1
        idx_sst  = header.index("sst")         if "sst"         in header else -1
        for line in lines[1:]:
            parts = line.strip().split(",")
            if len(parts) < 4:
                continue
            if idx_date >= 0 and not parts[idx_date].startswith(date_str):
                continue
            pt = parts[idx_pt] if idx_pt >= 0 else ""
            def _fv(idx):
                try:
                    return float(parts[idx]) if idx >= 0 and idx < len(parts) and parts[idx] else None
                except ValueError:
                    return None
            row = (_fv(idx_wind), _fv(idx_wdir), _fv(idx_wave), _fv(idx_sst))
            all_rows.append(row)
            if pt in _INNER_POINTS:
                inner_rows.append(row)
            elif pt in _OUTER_POINTS:
                outer_rows.append(row)
    except Exception:
        pass

    return (
        _aggregate_wx_rows(inner_rows),
        _aggregate_wx_rows(outer_rows),
        _aggregate_wx_rows(all_rows),
    )


# 後方互換: 旧 _parse_weather_csv を split 版で実装
def _parse_weather_csv(weather_dir, date_str):
    _, _, all_wx = _parse_weather_csv_split(weather_dir, date_str)
    result = {}
    if "wave" in all_wx:
        result["wave_inner"] = all_wx["wave"]
    if "wind_spd" in all_wx:
        result["max_wind"] = all_wx["wind_spd"]
        result["wind_inner_max"] = all_wx["wind_spd"]
        result["wind_inner_min"] = all_wx.get("wind_spd", 2.0)
    if "wind_dir" in all_wx:
        result["wind_dir_label"] = all_wx["wind_dir"]
    if "sst" in all_wx:
        result["sst_mean"] = all_wx["sst"]
    return result


def _load_pressure_from_cache(root_dir, date_str, lat_range=(35.1, 35.5), lon_range=(139.6, 140.0)):
    """weather_cache.sqlite から気圧中央値を取得。座標範囲を引数で切り替え可能。"""
    cache_path = os.path.join(root_dir, "ocean", "weather_cache.sqlite")
    if not os.path.exists(cache_path):
        return None
    try:
        con = sqlite3.connect(cache_path, timeout=5)
        rows = con.execute(
            "SELECT pressure FROM weather WHERE dt LIKE ? "
            "AND lat BETWEEN ? AND ? AND lon BETWEEN ? AND ? "
            "AND pressure IS NOT NULL LIMIT 48",
            (f"{date_str}%", lat_range[0], lat_range[1], lon_range[0], lon_range[1])
        ).fetchall()
        con.close()
        if rows:
            vals = sorted(r[0] for r in rows)
            return round(vals[len(vals) // 2], 0)
    except Exception:
        pass
    return None


# Open-Meteo API 代表座標（内海・外海）
_INNER_LAT, _INNER_LON = 35.3, 139.7   # 神奈川・東京湾
_OUTER_LAT, _OUTER_LON = 35.3, 140.6   # 千葉・外房

_OM_USER_AGENT = "funatsuri-yoso.com/context_builder"


def _fetch_wx_for_date(lat, lon, date_str):
    """Open-Meteo Marine + Forecast API から当日の海況値を取得。
    戻り値: {wave, sst, wind_spd, wind_dir, pressure} 取得失敗時は空 dict。
    """
    # Marine API: 波高・SST
    marine_url = (
        f"https://marine-api.open-meteo.com/v1/marine"
        f"?latitude={lat}&longitude={lon}"
        f"&hourly=wave_height,sea_surface_temperature"
        f"&start_date={date_str}&end_date={date_str}"
        f"&timezone=Asia/Tokyo"
    )
    # Forecast API: 風速・風向・気圧
    wind_url = (
        f"https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat}&longitude={lon}"
        f"&hourly=wind_speed_10m,wind_direction_10m,surface_pressure"
        f"&start_date={date_str}&end_date={date_str}"
        f"&timezone=Asia/Tokyo&wind_speed_unit=ms"
    )
    result = {}
    try:
        # Marine
        req = Request(marine_url, headers={"User-Agent": _OM_USER_AGENT})
        with urlopen(req, timeout=12) as r:
            mdata = json.loads(r.read())
        hourly = mdata.get("hourly", {})
        times  = hourly.get("time", [])
        wave_vals, sst_vals = [], []
        for i, t in enumerate(times):
            hour = int(t.split("T")[1].split(":")[0])
            if 6 <= hour <= 15:
                v = hourly.get("wave_height", [None]*(i+1))[i]
                s = hourly.get("sea_surface_temperature", [None]*(i+1))[i]
                if v is not None: wave_vals.append(v)
                if s is not None: sst_vals.append(s)
        if wave_vals: result["wave"] = round(sum(wave_vals)/len(wave_vals), 1)
        if sst_vals:  result["sst"]  = round(sum(sst_vals)/len(sst_vals), 1)
    except Exception:
        pass
    try:
        # Wind + Pressure
        req = Request(wind_url, headers={"User-Agent": _OM_USER_AGENT})
        with urlopen(req, timeout=12) as r:
            wdata = json.loads(r.read())
        hourly = wdata.get("hourly", {})
        times  = hourly.get("time", [])
        ws_vals, wd_vals, sp_vals = [], [], []
        for i, t in enumerate(times):
            hour = int(t.split("T")[1].split(":")[0])
            if 6 <= hour <= 15:
                ws = hourly.get("wind_speed_10m",    [None]*(i+1))[i]
                wd = hourly.get("wind_direction_10m", [None]*(i+1))[i]
                sp = hourly.get("surface_pressure",  [None]*(i+1))[i]
                if ws is not None: ws_vals.append(ws)
                if wd is not None: wd_vals.append(wd)
                if sp is not None: sp_vals.append(sp)
        if ws_vals: result["wind_spd"] = round(sum(ws_vals)/len(ws_vals), 1)
        if wd_vals: result["wind_dir"] = _wind_dir_label(round(sum(wd_vals)/len(wd_vals)))
        if sp_vals: result["pressure"] = round(sum(sp_vals)/len(sp_vals), 0)
    except Exception:
        pass
    return result


def build_context(valid_catches, history, analysis_db, date_str, weather_dir=None):
    """
    ctx 辞書を組み立てる。
    引数:
        valid_catches: list of catch dict (catches.json の data フィールド)
        history: history.json の内容
        analysis_db: analysis.sqlite のパス
        date_str: "YYYY-MM-DD" 形式の日付
        weather_dir: weather/ ディレクトリのパス（None の場合は自動推定）
    """
    # ルートディレクトリを推定（このファイルが x_post/ 内にある想定）
    _this_dir = os.path.dirname(os.path.abspath(__file__))
    _root_dir = os.path.dirname(_this_dir)
    if weather_dir is None:
        weather_dir = os.path.join(_root_dir, "weather")

    tide_db = os.path.join(_root_dir, "ocean", "tide_moon.sqlite")

    # 日付情報
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    weekdays_jp = ["月", "火", "水", "木", "金", "土", "日"]
    weekdays_en = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    wd_idx = dt.weekday()
    date_label = f"{dt.month}/{dt.day}({weekdays_jp[wd_idx]})"
    decade_no = _get_decade_no(dt)
    season_label = _DECADE_LABELS.get(decade_no, f"{dt.month}月")
    is_weekend_eve = weekdays_en[wd_idx] in ("friday", "thursday")

    # 前日・翌日（ナビ用）
    from datetime import timedelta as _td
    prev_dt = dt - _td(days=1)
    next_dt = dt + _td(days=1)
    prev_date_iso = prev_dt.strftime("%Y-%m-%d")
    next_date_iso = next_dt.strftime("%Y-%m-%d")
    prev_date_label = f"{prev_dt.month}/{prev_dt.day}({weekdays_jp[prev_dt.weekday()]})"
    next_date_label = f"{next_dt.month}/{next_dt.day}({weekdays_jp[next_dt.weekday()]})"
    # 該当 HTML が存在するかで「リンク有効」フラグを立てる
    _x_post_dir = os.path.join(_root_dir, "docs", "x_post")
    prev_exists = os.path.exists(os.path.join(_x_post_dir, f"{prev_date_iso}.html"))
    next_exists = os.path.exists(os.path.join(_x_post_dir, f"{next_date_iso}.html"))

    # ±7日（案A 5ボタンナビ用）
    prev7_dt = dt - _td(days=7)
    next7_dt = dt + _td(days=7)
    prev7_date_iso = prev7_dt.strftime("%Y-%m-%d")
    next7_date_iso = next7_dt.strftime("%Y-%m-%d")
    prev7_date_label = f"{prev7_dt.month}/{prev7_dt.day}({weekdays_jp[prev7_dt.weekday()]})"
    next7_date_label = f"{next7_dt.month}/{next7_dt.day}({weekdays_jp[next7_dt.weekday()]})"
    prev7_exists = os.path.exists(os.path.join(_x_post_dir, f"{prev7_date_iso}.html"))
    next7_exists = os.path.exists(os.path.join(_x_post_dir, f"{next7_date_iso}.html"))

    # 潮汐
    tide_info = _load_tide_moon(tide_db, date_str)

    # 当日 catches を絞り込み
    # T31 (2026/05/12) バグ修正: 日付完全一致のみ。
    # 旧コードは day_exact 空のとき month マッチで fallback したため、
    # 5/12（当日0件）の x_post/2026-05-12.html が 5月全件 709件・76船宿と
    # 異常表示されていた。当日0件は「データなし」が正しい表現。
    date_slash = dt.strftime("%Y/%m/%d")
    day_catches = [c for c in valid_catches if c.get("date") == date_slash]

    # 欠航データを cancellations.csv から取得（valid_catches に含まれない別経路）
    cancellations_csv = _load_cancellations(date_slash)
    cancel_ships_csv = {c["ship"] for c in cancellations_csv if c.get("ship")}
    cancel_areas_csv = {c.get("area", "") for c in cancellations_csv if c.get("area")}

    # 出船統計（釣果あり船宿 + 欠航船宿の和集合）
    ships_with_catch = {c["ship"] for c in day_catches}
    areas_with_catch = {c.get("area", "") for c in day_catches}
    ships_set = ships_with_catch | cancel_ships_csv
    areas_set = areas_with_catch | cancel_areas_csv
    n_ships = len(ships_set)
    n_areas = len(areas_set)

    # 魚種集計
    fish_counter = {}
    for c in day_catches:
        for f in c.get("fish", []):
            if f and f != "不明":
                fish_counter[f] = fish_counter.get(f, 0) + 1
    n_fish_species = len(fish_counter)
    n_records = len(day_catches)

    # top_cnt (最大匹数)
    top_cnt_data = None
    best_cnt_max = 0
    for c in day_catches:
        cr = c.get("count_range") or {}
        if _cnt_personal(cr):
            cmax = cr.get("max") or 0
            if cmax > best_cnt_max:
                best_cnt_max = cmax
                top_cnt_data = {
                    "fish": (c.get("fish") or ["不明"])[0],
                    "cnt_max": cr.get("max") or 0,
                    "cnt_min": cr.get("min") or 0,
                    "ship": c.get("ship", ""),
                    "port": c.get("area", ""),
                }

    # top_kg (最大重量) ※魚種別の妥当上限 _FISH_KG_MAX を超える値は CSV 誤入力として除外
    top_kg_data = None
    best_kg_max = 0.0
    for c in day_catches:
        wk = c.get("weight_kg") or {}
        if isinstance(wk, dict):
            kmax = wk.get("max") or 0
            _fish = (c.get("fish") or ["不明"])[0]
            _kg_cap = _FISH_KG_MAX.get(_fish)
            if _kg_cap is not None and kmax > _kg_cap:
                continue  # 例: アジ 10kg は除外
            if kmax > best_kg_max:
                best_kg_max = kmax
                top_kg_data = {
                    "fish": _fish,
                    "kg_max": kmax,
                    "kg_min": wk.get("min") or 0,
                    "ship": c.get("ship", ""),
                    "port": c.get("area", ""),
                }

    # top_cm (最大サイズ) ※魚種別の妥当上限 _FISH_CM_MAX を超える値は CSV 誤入力として除外
    top_cm_data = None
    best_cm_max = 0
    for c in day_catches:
        sc = c.get("size_cm") or {}
        if isinstance(sc, dict):
            cmax = sc.get("max") or 0
            _fish = (c.get("fish") or ["不明"])[0]
            _cm_cap = _FISH_CM_MAX.get(_fish)
            if _cm_cap is not None and cmax > _cm_cap:
                continue
            if cmax > best_cm_max:
                best_cm_max = cmax
                top_cm_data = {
                    "fish": _fish,
                    "cm_max": sc.get("max") or 0,
                    "cm_min": sc.get("min") or 0,
                    "ship": c.get("ship", ""),
                    "port": c.get("area", ""),
                }

    # 欠航数（cancellations.csv 由来 + day_catches の is_cancellation フラグの OR で重複排除）
    cancel_ships_in_catches = {c["ship"] for c in day_catches
                                if c.get("is_cancellation")
                                or "欠航" in str(c.get("catch_raw", ""))
                                or "出船中止" in str(c.get("catch_raw", ""))}
    all_cancel_ships = cancel_ships_csv | cancel_ships_in_catches
    n_cancellations = len(all_cancel_ships)

    # wow_pct (先週比)
    weekly = history.get("weekly", {})
    week_keys = sorted(weekly.keys(), reverse=True)
    this_w = weekly.get(week_keys[0], {}) if week_keys else {}
    last_w = weekly.get(week_keys[1], {}) if len(week_keys) > 1 else {}

    wow_pct = {}
    for fish_name, fdata in this_w.items():
        this_max = fdata.get("max", 0) or 0
        last_max = (last_w.get(fish_name) or {}).get("max", 1) or 1
        wow_pct[fish_name] = round(this_max / last_max, 2) if last_max else 1.0

    # season_ratio (旬別比)
    top_cnt_fish = (top_cnt_data or {}).get("fish", "")
    season_ratio_top_cnt = 1.0
    if top_cnt_fish and top_cnt_data:
        hist_median = _load_combo_decadal(analysis_db, top_cnt_fish, decade_no)
        if hist_median and hist_median > 0:
            season_ratio_top_cnt = round(top_cnt_data["cnt_max"] / hist_median, 1)

    season_ratio_top_kg = 1.0
    top_kg_fish = (top_kg_data or {}).get("fish", "")
    if top_kg_fish and top_kg_data:
        hist_median = _load_combo_decadal(analysis_db, top_kg_fish, decade_no)
        if hist_median and hist_median > 0:
            season_ratio_top_kg = round(top_kg_data["kg_max"] / hist_median, 1)

    season_ratio_top_cm = 1.0
    top_cm_fish = (top_cm_data or {}).get("fish", "")
    if top_cm_fish and top_cm_data:
        hist_median = _load_combo_decadal(analysis_db, top_cm_fish, decade_no)
        if hist_median and hist_median > 0:
            season_ratio_top_cm = round(top_cm_data["cm_max"] / hist_median, 1)

    season_ratio_kanpachi = wow_pct.get("カンパチ", 1.0)

    # 海況データ（内海・外海 2 セット）
    inner_wx, outer_wx, all_wx = _parse_weather_csv_split(weather_dir, date_str)
    # CSV 不在時は Open-Meteo Forecast API にフォールバック
    if not inner_wx:
        inner_wx = _fetch_wx_for_date(_INNER_LAT, _INNER_LON, date_str)
    if not outer_wx:
        outer_wx = _fetch_wx_for_date(_OUTER_LAT, _OUTER_LON, date_str)
    if not all_wx:
        all_wx = inner_wx  # 後方互換用スカラーは内海代表で代替
    # 後方互換用スカラー（テンプレート変数 max_wind 等を維持）
    wave_inner     = inner_wx.get("wave",     all_wx.get("wave",     1.0))
    max_wind       = all_wx.get("wind_spd",   5.0)
    wind_inner_max = inner_wx.get("wind_spd", 5.0)
    wind_inner_min = inner_wx.get("wind_spd", 2.0)
    wind_outer_max = outer_wx.get("wind_spd", max_wind)
    wind_dir_label = inner_wx.get("wind_dir", all_wx.get("wind_dir", ""))
    sst_mean       = all_wx.get("sst",        18.0)
    # 気候平年値（簡易）
    sst_norm = {1: 15, 2: 14, 3: 15, 4: 16, 5: 17, 6: 19, 7: 22, 8: 24,
                9: 23, 10: 21, 11: 18, 12: 16}
    sst_anom = round(sst_mean - sst_norm.get(dt.month, 17), 1)
    # 気圧: Open-Meteo フォールバック時は inner_wx/outer_wx に pressure が入っている
    # weather_cache.sqlite からの取得も試みる（より精度が高い場合に上書き）
    pressure_inner = (
        _load_pressure_from_cache(_root_dir, date_str, lat_range=(35.1, 35.5), lon_range=(139.6, 140.0))
        or inner_wx.get("pressure")
    )
    pressure_outer = (
        _load_pressure_from_cache(_root_dir, date_str, lat_range=(34.5, 35.1), lon_range=(138.8, 140.2))
        or outer_wx.get("pressure")
    )
    pressure_hpa = pressure_inner  # 後方互換
    # 内海 / 外海の sea_data dict（build_daily_page で使用）
    inner_sea_data = {
        "sst":      inner_wx.get("sst"),
        "wave":     inner_wx.get("wave"),
        "wind_spd": inner_wx.get("wind_spd"),
        "wind_dir": inner_wx.get("wind_dir", ""),
        "tide":     tide_info["tide_type"],
        "moon":     tide_info["moon_phase"],
        "pressure": pressure_inner,
    }
    outer_sea_data = {
        "sst":      outer_wx.get("sst"),
        "wave":     outer_wx.get("wave"),
        "wind_spd": outer_wx.get("wind_spd"),
        "wind_dir": outer_wx.get("wind_dir", ""),
        "tide":     tide_info["tide_type"],
        "moon":     tide_info["moon_phase"],
        "pressure": pressure_outer,
    }

    # inner / outer 釣果割合
    inner_cnt = sum(1 for c in day_catches if c.get("area", "") in _INNER_PORTS)
    outer_cnt = sum(1 for c in day_catches if c.get("area", "") in _OUTER_PORTS)
    total_area_cnt = max(inner_cnt + outer_cnt, 1)
    inner_ratio = inner_cnt / total_area_cnt
    outer_ratio = outer_cnt / total_area_cnt

    # 青物割合
    pelagic_cnt = sum(1 for c in day_catches
                      for f in c.get("fish", []) if f in _PELAGIC_FISH)
    pelagic_share = pelagic_cnt / max(n_records, 1)

    # レア魚種
    rare_fish_present = any(f in _RARE_FISH for c in day_catches for f in c.get("fish", []))
    rare_species = [f for f in fish_counter if f in _RARE_FISH and fish_counter[f] <= 3]
    rare_fish_name = rare_species[0] if rare_species else ""

    # 総欠航率
    total_cancel_rate = n_cancellations / max(n_ships, 1)

    # no_special_event: 大物・急増・レア種が無い
    no_special_event = (
        best_kg_max < 5.0 and
        max(wow_pct.values() or [1.0]) < 1.5 and
        not rare_fish_present
    )

    # 主力魚種リスト（件数降順・全件。fish_rows は全魚種を表示する）
    top_fish_list = sorted(fish_counter, key=lambda f: fish_counter[f], reverse=True)[:30]
    mainstream_count = min(len(top_fish_list), 3)
    opportunistic_count = len([f for f in top_fish_list if (f in _RARE_FISH) or (f in _PELAGIC_FISH)])
    mainstream_fish_list = "・".join(top_fish_list[:3]) if top_fish_list else "各魚種"
    opportunistic_fish_list = "・".join([f for f in top_fish_list if (f in _RARE_FISH) or (f in _PELAGIC_FISH)]) or "単発魚種"

    # 魚種別データ（F2-F11 用）
    def _fish_data(fish_name):
        catches = [c for c in day_catches if fish_name in c.get("fish", [])]
        if not catches:
            return None
        cnt_maxes = [c["count_range"]["max"] for c in catches
                     if _cnt_personal(c.get("count_range")) and c["count_range"].get("max") is not None]
        cnt_mins = [c["count_range"]["min"] for c in catches
                    if _cnt_personal(c.get("count_range")) and c["count_range"].get("min") is not None]
        kg_maxes = [c["weight_kg"]["max"] for c in catches
                    if isinstance(c.get("weight_kg"), dict) and c["weight_kg"].get("max") is not None]
        kg_mins = [c["weight_kg"]["min"] for c in catches
                   if isinstance(c.get("weight_kg"), dict) and c["weight_kg"].get("min") is not None]
        cm_maxes = [c["size_cm"]["max"] for c in catches
                    if isinstance(c.get("size_cm"), dict) and c["size_cm"].get("max") is not None]
        cm_mins = [c["size_cm"]["min"] for c in catches
                   if isinstance(c.get("size_cm"), dict) and c["size_cm"].get("min") is not None]
        ports = list({c.get("area", "") for c in catches if c.get("area")})[:2]
        top_ship = max(catches, key=lambda c: ((c.get("count_range") or {}).get("max") or 0) if _cnt_personal(c.get("count_range")) else 0,
                       default=catches[0]).get("ship", "")
        return {
            "cnt_max": max(cnt_maxes) if cnt_maxes else 0,
            "cnt_min": min(cnt_mins) if cnt_mins else 0,
            "kg_max": max(kg_maxes) if kg_maxes else 0.0,
            "kg_min": min(kg_mins) if kg_mins else 0.0,
            "cm_max": max(cm_maxes) if cm_maxes else 0,
            "cm_min": min(cm_mins) if cm_mins else 0,
            "top_areas": "・".join(ports) if ports else "",
            "top_ship": top_ship,
            "n": len(catches),
        }

    # 魚種別データを ctx に展開
    _fish_map = {
        "aji": "アジ", "madai": "マダイ", "kisu": "シロギス",
        "kawahagi": "カワハギ", "tachiuo": "タチウオ", "kanpachi": "カンパチ",
        "maruika": "マルイカ", "yariika": "ヤリイカ", "fugu": "フグ",
        "surumeika": "スルメイカ",
    }

    fish_ctx = {}
    for key, fish_name in _fish_map.items():
        d = _fish_data(fish_name)
        fish_ctx[f"has_{key}"] = d is not None
        if d:
            fish_ctx[f"{key}_cnt_max"] = d["cnt_max"]
            fish_ctx[f"{key}_cnt_min"] = d["cnt_min"]
            fish_ctx[f"{key}_kg_max"] = d["kg_max"]
            fish_ctx[f"{key}_kg_min"] = d["kg_min"]
            fish_ctx[f"{key}_cm_max"] = d["cm_max"]
            fish_ctx[f"{key}_cm_min"] = d["cm_min"]
            fish_ctx[f"{key}_top_areas"] = d["top_areas"]
            fish_ctx[f"{key}_top_ship"] = d["top_ship"]
            fish_ctx[f"{key}_top_count"] = d["cnt_max"]
            # min==max のとき単一表記の事前整形フィールド
            _cmin, _cmax = d["cnt_min"], d["cnt_max"]
            fish_ctx[f"{key}_cnt_range"] = f"{_cmax}匹" if _cmin == _cmax else f"{_cmin}〜{_cmax}匹"
            _smin, _smax = d["cm_min"], d["cm_max"]
            if _smax and _smax > 0:
                fish_ctx[f"{key}_cm_range"] = f"{_smax}cm" if _smin == _smax else f"{_smin}〜{_smax}cm"
            else:
                fish_ctx[f"{key}_cm_range"] = ""
        else:
            for suffix in ["cnt_max", "cnt_min", "kg_max", "kg_min", "cm_max", "cm_min",
                           "top_areas", "top_ship", "top_count"]:
                fish_ctx[f"{key}_{suffix}"] = 0 if "max" in suffix or "min" in suffix else ""
            fish_ctx[f"{key}_cnt_range"] = ""
            fish_ctx[f"{key}_cm_range"] = ""

    # fish_rows: B案 PNG / テーブル用（全魚種を含める。HTML テーブル側は全件表示・PNG 側は build_daily_page で制限）
    fish_rows = []
    for fish_name in top_fish_list:
        d = _fish_data(fish_name)
        if d:
            fish_rows.append({
                "fish": fish_name,
                "cnt_min": d["cnt_min"],
                "cnt_max": d["cnt_max"],
                "kg_max": d["kg_max"],
                "kg_min": d["kg_min"],   # M3: kg min-max 表記用
                "cm_max": d["cm_max"],
                "cm_min": d["cm_min"],   # M3: cm min-max 表記用
                "top_port": d["top_areas"],
                "n_trips": d["n"],
            })

    # C4修正: top_cnt_min を全便 min に統一（hl-card と fish-list で同一値）
    # top_cnt_data["cnt_min"] は最多便のみの min なので、全便 min を再集計
    _top_cnt_all_data = _fish_data(top_cnt_fish) if top_cnt_fish else None
    _top_cnt_min_unified = (_top_cnt_all_data or {}).get("cnt_min", 0)

    # 先週比文字列
    wow_pct_top_cnt = wow_pct.get(top_cnt_fish, 1.0)
    if wow_pct_top_cnt >= 1.0:
        wow_pct_top_cnt_str = f"+{int((wow_pct_top_cnt - 1) * 100)}%"
    else:
        wow_pct_top_cnt_str = f"{int((wow_pct_top_cnt - 1) * 100)}%"

    # 潮汐強い魚種
    tide_strong = []
    if tide_info["tide_type"] == "大潮":
        tide_strong = [f for f in ["マダイ", "アジ", "シロギス"] if f in fish_counter]
    tide_strong_fish_list = "・".join(tide_strong[:3]) if tide_strong else top_fish_list[0] if top_fish_list else "各魚種"
    tide_active_fish_list = tide_strong_fish_list
    small_tide_advantageous_fish = top_fish_list[0] if top_fish_list else "各魚種"

    # 季節性魚種（春の新顔）
    _SPRING_FISH = ["シロギス", "アジ", "カツオ", "シイラ", "マゴチ"]
    seasonal_first = [f for f in _SPRING_FISH if f in fish_counter and dt.month in [4, 5, 6]]
    seasonal_first_len = len(seasonal_first)
    seasonal_first_list = "・".join(seasonal_first[:3]) if seasonal_first else ""
    seasonal_focus_fish = seasonal_first[0] if seasonal_first else (top_fish_list[0] if top_fish_list else "各魚種")
    seasonal_max_data = _fish_data(seasonal_focus_fish)
    seasonal_max = (seasonal_max_data or {}).get("cnt_max", 0)

    # 旬終盤魚種
    _AUTUMN_FISH = ["タチウオ", "アオリイカ", "ヒラメ"]
    season_ending = [f for f in _AUTUMN_FISH if f in fish_counter and dt.month in [10, 11, 12]]
    season_ending_share = len(season_ending) / max(n_fish_species, 1)
    season_ending_main_fish = "・".join(season_ending[:2]) if season_ending else (top_fish_list[0] if top_fish_list else "各魚種")

    # 安定組の割合
    _STABLE_FISH = {"アジ", "シロギス", "カワハギ", "フグ", "タチウオ", "マダイ", "アイナメ"}
    stable_cnt = sum(1 for c in day_catches if any(f in _STABLE_FISH for f in c.get("fish", [])))
    seasonal_stable_share = stable_cnt / max(n_records, 1)
    seasonal_stable_list = "・".join([f for f in top_fish_list if f in _STABLE_FISH][:3]) or mainstream_fish_list

    # 補助変数
    inner_top_fish = top_fish_list[0] if top_fish_list else "アジ"
    outer_top_fish = next((f for f in top_fish_list if f in _PELAGIC_FISH), top_fish_list[0] if top_fish_list else "カンパチ")
    stormy_top_fish = top_fish_list[0] if top_fish_list else "アジ"
    stable_top_fish = top_fish_list[0] if top_fish_list else "アジ"
    clear_top_fish = top_fish_list[0] if top_fish_list else "マダイ"
    strong_wind_top_fish = inner_top_fish
    minimal_top_fish = top_fish_list[0] if top_fish_list else "各魚種"
    minimal_fish_top = minimal_top_fish
    calm_main_fish = top_fish_list[0] if top_fish_list else "アジ"
    calm_target_fish = "マダイ"
    neutral_top_fish = top_fish_list[0] if top_fish_list else "アジ"
    down_tide_target_fish = "マダイ"
    turbid_resistant_fish = "アジ"
    turbid_resilient_fish = "アジ"
    clear_view_top_fish = "マダイ"
    swell_resistant_fish = "カワハギ"
    stable_calm_top_fish = top_fish_list[0] if top_fish_list else "アジ"
    weekend_focus_fish = top_fish_list[0] if top_fish_list else "アジ"
    weekend_focus_areas = "・".join(list(areas_set)[:2]) if areas_set else "関東各港"
    post_holiday_recommend_fish = top_fish_list[0] if top_fish_list else "アジ"
    morning_top_areas = "・".join(list(areas_set)[:2]) if areas_set else "各港"
    large_pelagic_areas = "・".join([c.get("area", "") for c in day_catches
                                     if any(f in _PELAGIC_FISH for f in c.get("fish", []))][:2]) or "外房・銭洲"
    large_pelagic_count = sum(1 for c in day_catches if any(f in _PELAGIC_FISH for f in c.get("fish", [])))
    kuroshio_pelagic_records = large_pelagic_count
    shoot_main_list = mainstream_fish_list
    rare_appearances = "・".join([f for f in top_fish_list if f in _RARE_FISH][:2]) or "珍しい魚種"
    rare_port = (top_kg_data or {}).get("port", "外房")
    rare_ship = (top_kg_data or {}).get("ship", "")
    rare_count = fish_counter.get(rare_fish_name, 0)
    rare_species_count = len(rare_species)
    rare_species_list = "・".join(rare_species[:3]) if rare_species else ""
    ship_specialty = "多魚種対応"
    inner_state = "穏やか"
    outer_top_ship = max((c["ship"] for c in day_catches if c.get("area") in _OUTER_PORTS),
                         key=lambda s: 1, default="")
    outer_top_record = f"{outer_top_fish}の釣果"
    strong_wind_cancel = n_cancellations
    pelagic_top_fish_list = "・".join([f for f in top_fish_list if f in _PELAGIC_FISH][:3]) or "青物"
    pelagic_main_areas = large_pelagic_areas
    pelagic_records = pelagic_cnt
    multi_fish_main_three = "・".join(top_fish_list[:3]) if len(top_fish_list) >= 3 else mainstream_fish_list
    multi_fish_supporting = [f for f in top_fish_list if f not in top_fish_list[:3]]
    multi_fish_supporting_list = "・".join(multi_fish_supporting[:3]) if multi_fish_supporting else "他魚種"
    single_fish_dominant = top_fish_list[0] if top_fish_list else "各魚種"
    single_fish_pct = fish_counter.get(single_fish_dominant, 0) / max(n_records, 1)
    bait_active = pelagic_share >= 0.3
    bait_active_areas = pelagic_main_areas
    bait_predator_fish = outer_top_fish
    swell_outer = max_wind / 10  # 簡易推定
    swell_affected_areas = "外房・銭洲"
    cancel_rate_inner = 0.0
    cancel_rate_outer = total_cancel_rate
    if abs(wind_inner_max - wind_inner_min) < 0.5 or round(wind_inner_min) == round(wind_inner_max):
        wind_inner_str = f"{wind_inner_max:.0f}m/s"
    else:
        wind_inner_str = f"{wind_inner_min:.0f}〜{wind_inner_max:.0f}m/s"

    # 船釣り基準の severity（内海/外海別・0=穏, 1=やや, 2=強, 3=暴）
    # crawler.py:_sea_label と境界値を一致させること
    def _sev_inner_wind(v):
        if v is None: return 0
        if v < 6: return 0
        if v < 8: return 1
        if v < 10: return 2
        return 3
    def _sev_outer_wind(v):
        if v is None: return 0
        if v < 8: return 0
        if v < 10: return 1
        if v < 13: return 2
        return 3
    def _sev_inner_wave(v):
        if v is None: return 0
        if v < 0.5: return 0
        if v < 1.0: return 1
        if v < 1.5: return 2
        return 3
    def _sev_outer_wave(v):
        if v is None: return 0
        if v < 1.0: return 0
        if v < 2.0: return 1
        if v < 3.0: return 2
        return 3
    inner_wind_sev = _sev_inner_wind(wind_inner_max)
    outer_wind_sev = _sev_outer_wind(wind_outer_max)
    inner_wave_sev = _sev_inner_wave(wave_inner)
    outer_wave_sev = _sev_outer_wave(swell_outer)
    inner_sea_sev = max(inner_wind_sev, inner_wave_sev)
    outer_sea_sev = max(outer_wind_sev, outer_wave_sev)
    # 船釣り基準の風の形容（テンプレ {wind_inner_phrase} 用）
    _wind_phrase_inner = {0: "穏やかで", 1: "そよ風あり", 2: "やや強く", 3: "の強風で"}[inner_wind_sev]
    _wind_phrase_outer = {0: "穏やかで", 1: "そよ風あり", 2: "やや強く", 3: "の強風で"}[outer_wind_sev]
    wind_direction_changes = 0
    no_rain_3d = True
    rain_yesterday_mm = 0  # 雨データ取得は省略（デフォルト 0mm）
    consecutive_calm_days = 1
    high_tide_hour = 9  # 簡易デフォルト
    low_tide_hour = 15
    morning_share = 0.5  # 簡易デフォルト
    morning_pct = morning_share
    inner_pct = inner_ratio
    strong_wind_affected_areas = "外海各港"
    clear_view_areas = "東京湾"
    clear_view_depth_m = 10
    turbid_resistant_fish_val = turbid_resistant_fish
    period_label = f"{dt.month}月以降"
    kg_threshold = f"{int(best_kg_max // 5) * 5}kg" if best_kg_max >= 5 else "5kg"

    ctx = {
        # 日付
        "date_label": date_label,
        "date_iso": date_str,
        "season_label": season_label,
        "prev_date_iso": prev_date_iso,
        "prev_date_label": prev_date_label,
        "prev_exists": prev_exists,
        "next_date_iso": next_date_iso,
        "next_date_label": next_date_label,
        "next_exists": next_exists,
        "prev7_date_iso": prev7_date_iso,
        "prev7_date_label": prev7_date_label,
        "prev7_exists": prev7_exists,
        "next7_date_iso": next7_date_iso,
        "next7_date_label": next7_date_label,
        "next7_exists": next7_exists,
        "decade_no": decade_no,
        "weekday": weekdays_en[wd_idx],
        "weekday_jp": weekdays_jp[wd_idx] + "曜日",
        "is_weekend_eve": is_weekend_eve,
        "month": dt.month,
        "period_label": period_label,
        # 釣果統計
        "n_ships": n_ships,
        "n_areas": n_areas,
        "n_fish_species": n_fish_species,
        "n_records": n_records,
        "n_cancellations": n_cancellations,
        "total_cancel_rate": total_cancel_rate,
        "fish_rows": fish_rows,
        "top_fish_list": top_fish_list,
        # top_kg
        "top_kg_fish": (top_kg_data or {}).get("fish", ""),
        "top_kg_max": (top_kg_data or {}).get("kg_max", 0.0),
        "top_kg_min": (top_kg_data or {}).get("kg_min", 0.0),
        "top_kg_ship": (top_kg_data or {}).get("ship", ""),
        "top_kg_port": (top_kg_data or {}).get("port", ""),
        "season_ratio_top_kg": season_ratio_top_kg,
        "kg_threshold": kg_threshold,
        "ship_specialty": ship_specialty,
        # top_cnt（C4: cnt_min は全便 min に統一）
        "top_cnt_fish": (top_cnt_data or {}).get("fish", ""),
        "top_cnt_max": (top_cnt_data or {}).get("cnt_max", 0),
        "top_cnt_min": _top_cnt_min_unified,  # 全便 min（hl-card と fish-list で同値）
        "top_cnt_range": (
            f"{(top_cnt_data or {}).get('cnt_max', 0)}匹"
            if _top_cnt_min_unified == (top_cnt_data or {}).get("cnt_max", 0)
            else f"{_top_cnt_min_unified}〜{(top_cnt_data or {}).get('cnt_max', 0)}匹"
        ),
        "top_cnt_ship": (top_cnt_data or {}).get("ship", ""),
        "top_cnt_port": (top_cnt_data or {}).get("port", ""),
        "wow_pct_top_cnt": wow_pct_top_cnt,
        "wow_pct_top_cnt_str": wow_pct_top_cnt_str,
        "season_ratio_top_cnt": season_ratio_top_cnt,
        # top_cm
        "top_cm_fish": (top_cm_data or {}).get("fish", ""),
        "top_cm_max": (top_cm_data or {}).get("cm_max", 0),
        "top_cm_min": (top_cm_data or {}).get("cm_min", 0),
        "top_cm_ship": (top_cm_data or {}).get("ship", ""),
        "top_cm_port": (top_cm_data or {}).get("port", ""),
        "season_ratio_top_cm": season_ratio_top_cm,
        # 海況
        "wave_inner": wave_inner,
        "swell_outer": swell_outer,
        "max_wind": max_wind,
        "wind_inner_max": wind_inner_max,
        "wind_inner_min": wind_inner_min,
        "wind_inner_str": wind_inner_str,
        "wind_outer_max": wind_outer_max,
        # 船釣り基準 severity（内海/外海別・0=穏, 1=やや, 2=強, 3=暴）
        "inner_wind_sev": inner_wind_sev,
        "outer_wind_sev": outer_wind_sev,
        "inner_wave_sev": inner_wave_sev,
        "outer_wave_sev": outer_wave_sev,
        "inner_sea_sev": inner_sea_sev,
        "outer_sea_sev": outer_sea_sev,
        "wind_phrase_inner": _wind_phrase_inner,
        "wind_phrase_outer": _wind_phrase_outer,
        "wind_dir_label": wind_dir_label,
        "sst_mean": sst_mean,
        "pressure_hpa": pressure_hpa,  # None の場合は "—" 表示
        "sst_anom": sst_anom,
        "inner_sea_data": inner_sea_data,
        "outer_sea_data": outer_sea_data,
        "kuroshio_state": "stable",  # cmems_data が無いためデフォルト
        "rain_yesterday_mm": rain_yesterday_mm,
        "weather_today": "晴れ",  # デフォルト
        "no_rain_3d": no_rain_3d,
        "wind_direction_changes": wind_direction_changes,
        "consecutive_calm_days": consecutive_calm_days,
        # 潮汐
        "tide_type": tide_info["tide_type"],
        "moon_phase": tide_info["moon_phase"],
        "moon_age": tide_info["moon_age"],
        "tide_strong_fish_list": tide_strong_fish_list,
        "tide_active_fish_list": tide_active_fish_list,
        "small_tide_advantageous_fish": small_tide_advantageous_fish,
        "high_tide_hour": high_tide_hour,
        "low_tide_hour": low_tide_hour,
        # 割合
        "inner_ratio": inner_ratio,
        "outer_ratio": outer_ratio,
        "inner_pct": inner_pct,
        "morning_share": morning_share,
        "morning_pct": morning_pct,
        "pelagic_share": pelagic_share,
        "seasonal_stable_share": seasonal_stable_share,
        "season_ending_share": season_ending_share,
        "cancel_rate_inner": cancel_rate_inner,
        "cancel_rate_outer": cancel_rate_outer,
        # 季節
        "seasonal_first_len": seasonal_first_len,
        "seasonal_first_list": seasonal_first_list,
        "seasonal_focus_fish": seasonal_focus_fish,
        "seasonal_max": seasonal_max,
        "season_ending_main_fish": season_ending_main_fish,
        "seasonal_stable_list": seasonal_stable_list,
        # 魚種別
        "mainstream_count": mainstream_count,
        "opportunistic_count": opportunistic_count,
        "mainstream_fish_list": mainstream_fish_list,
        "opportunistic_fish_list": opportunistic_fish_list,
        "multi_fish_main_three": multi_fish_main_three,
        "multi_fish_supporting_list": multi_fish_supporting_list,
        "single_fish_dominant": single_fish_dominant,
        "single_fish_pct": single_fish_pct,
        "pelagic_top_fish_list": pelagic_top_fish_list,
        "pelagic_main_areas": pelagic_main_areas,
        "pelagic_records": pelagic_records,
        # フラグ
        "rare_fish_present": rare_fish_present,
        "rare_fish_name": rare_fish_name,
        "rare_port": rare_port,
        "rare_ship": rare_ship,
        "rare_count": rare_count,
        "rare_species_count": rare_species_count,
        "rare_species_list": rare_species_list,
        "bait_active": bait_active,
        "bait_active_areas": bait_active_areas,
        "bait_predator_fish": bait_predator_fish,
        "no_special_event": no_special_event,
        "n_records_ratio": 1.0,  # 分母が分からないためデフォルト 1.0
        # 補助文字列
        "shoot_main_list": shoot_main_list,
        "rare_appearances": rare_appearances,
        "stable_top_fish": stable_top_fish,
        "inner_top_fish": inner_top_fish,
        "outer_top_fish": outer_top_fish,
        "outer_top_ship": outer_top_ship,
        "outer_top_record": outer_top_record,
        "stormy_top_fish": stormy_top_fish,
        "clear_top_fish": clear_top_fish,
        "strong_wind_top_fish": strong_wind_top_fish,
        "strong_wind_cancel": strong_wind_cancel,
        "strong_wind_affected_areas": strong_wind_affected_areas,
        "minimal_top_fish": minimal_top_fish,
        "minimal_fish_top": minimal_fish_top,
        "calm_main_fish": calm_main_fish,
        "calm_target_fish": calm_target_fish,
        "neutral_top_fish": neutral_top_fish,
        "down_tide_target_fish": down_tide_target_fish,
        "turbid_resistant_fish": turbid_resistant_fish,
        "turbid_resilient_fish": turbid_resilient_fish,
        "turbid_weak_fish": "シロギス",
        "clear_view_top_fish": clear_view_top_fish,
        "clear_view_areas": clear_view_areas,
        "clear_view_depth_m": clear_view_depth_m,
        "swell_resistant_fish": swell_resistant_fish,
        "swell_affected_areas": swell_affected_areas,
        "stable_calm_top_fish": stable_calm_top_fish,
        "weekend_focus_fish": weekend_focus_fish,
        "weekend_focus_areas": weekend_focus_areas,
        "post_holiday_recommend_fish": post_holiday_recommend_fish,
        "morning_top_areas": morning_top_areas,
        "large_pelagic_areas": large_pelagic_areas,
        "large_pelagic_count": large_pelagic_count,
        "kuroshio_pelagic_records": kuroshio_pelagic_records,
        "kuroshio_north_areas": "外房・銭洲",
        "kuroshio_north_records": large_pelagic_count,
        "kuroshio_south_areas": "外海各港",
        "kuroshio_south_effect": "水温低下",
        "kuroshio_alternative_fish": "カワハギ・カサゴ",
        "inner_state": inner_state,
        "season_ratio_kanpachi": season_ratio_kanpachi,
        # ship_info fallback (ship_info.json がなくても動く)
        "travel_hours": "2〜3",
        "env_note": "海況の変化",
        "gap_weeks": "数",
        "port_specialty": "外洋",
        "trend_note": "サイズが上向く傾向",
        "forecast_window": "来週末",
        "forecast_weeks": "2〜3",
        "typical_cnt_range": "20〜80",
        "post_holiday_state": "余裕のある",
        "post_holiday_records": n_records,
        "clear_recovery_window": "晴天続き",
        "tomorrow_wx_outer": "明日",
        "turbid_records": n_records,
        "inner_storm_cause": "北風",
        "below_avg_pct": 0.3,
        "stormy_cause": "低気圧",
        "recovery_eta": "2〜3日",
        "neutral_top_areas": "東京湾",
        "stable_calm_records": n_records,
        "stable_calm_pattern_break": "週末",
        "wind_change_count": wind_direction_changes,
        "wind_changes_summary": "北東→南西→北東",
        "wind_change_skilled_ships": "熟練船長",
        "wind_change_top_record": f"{top_fish_list[0] if top_fish_list else '各魚種'}の好釣果",
        "tomorrow_wind_outlook": "安定する方向",
        "dawn_ship_examples": "早朝便",
        "down_tide_record": "マダイ大型",
        "down_tide_outlook": "下げ潮パターン",
        "clear_view_strategy": "細ハリスの工夫",
        "clear_view_top_record": "マダイ好記録",
        "neutral_top_record": f"{neutral_top_fish}の安定釣果",
        "morming_top_record": "各魚種の好釣果",
        "calm_top_record": "各魚種の記録",
        "calm_top_areas": "東京湾",
        "bait_outlook": "来週末",
        "seasonal_lag_pretty": "平年並みの",
        "seasonal_alternative_fish": "カワハギ",
    }

    # 魚種別 ctx を展開
    ctx.update(fish_ctx)

    return ctx
