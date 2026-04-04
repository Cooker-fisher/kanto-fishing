#!/usr/bin/env python3
"""
combo_deep_dive.py — 船宿×魚種ペア 深掘り分析

[方針]
  1ペアずつ丁寧に分析し、精度向上のための知見を積み上げる。
  バックテストは「予報で取れる情報のみ」を使って評価する。

[分析内容]
  1. 基本統計（cnt_avg/min/max, size_avg, kg_avg）
  2. 旬別ベースライン（combo_decadal 引用）
  3. 因子相関（予報可能9因子 × cnt_avg/cnt_max/size_avg/kg_avg）
  4. コメント解析（kanso_raw / fish_raw）
  5. ポイント別集計（point_place1）
  6. マルチホライズン バックテスト（H=0,1,3,7,14,21,28日前の海況で予測）

[予報可能因子（バックテスト制約）]
  ○ sst, temp, pressure, wind_speed, wind_dir,
    wave_height, wave_period, swell_height  ← forecast_cache にある
  ○ tide_range, moon_age, tide_type          ← 天文計算で未来も確定
  × current_spd, wave_dir, swell_period      ← 予報APIに含まれない

[使い方]
  python insights/combo_deep_dive.py --fish アジ --ship かめだや
  python insights/combo_deep_dive.py --fish アジ          # 全船宿

[出力]
  insights/deep_dive/{魚種}_{船宿}.txt
  insights/analysis.sqlite  → combo_deep_params テーブル
"""

import argparse, csv, json, math, os, sqlite3, sys
from collections import defaultdict
from datetime import datetime, timedelta

BASE_DIR      = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR      = os.path.dirname(BASE_DIR)
DATA_DIR      = os.path.join(ROOT_DIR, "data")
DB_WX         = os.path.join(ROOT_DIR, "weather_cache.sqlite")
DB_TIDE       = os.path.join(ROOT_DIR, "tide_moon.sqlite")
DB_ANA        = os.path.join(BASE_DIR, "analysis.sqlite")
OUT_DIR       = os.path.join(BASE_DIR, "deep_dive")
OVERRIDE_FILE = os.path.join(ROOT_DIR, "ship_wx_coord_override.json")
SHIPS_FILE    = os.path.join(ROOT_DIR, "ships.json")

TRAIN_END  = "2024/12/31"   # この日以前 = 学習データ
HORIZONS   = [0, 1, 3, 7, 14, 21, 28]
MIN_N_COMBO = 10            # 分析最小件数

# ── 変数の予報有効ホライズン ────────────────────────────────────────────
# 「遅い変数」: 日々の変化が小さく、N日前の値≒当日値 → 長期予報でも有効
# 「速い変数」: 数日で激変 → 短期予報（〜7日）以外は当日値と無関係
#
# 実測例（東京湾 2024-08）:
#   SST: 27.0〜29.1℃（月次変動±1℃） → 28日前でもほぼ同じ値
#   wave: 0.16〜1.30m（台風日に急変） → 7日前は全く参考にならない
#   wind: 8.2〜44.5m/s（台風日に急変）→ 同上
#
# ∴ バックテストで H=N の海況を使うとき、速い変数は H>FAST_MAX_H で無効化

# ── 予報有効ホライズン分類 ────────────────────────────────────────────────
# 遅い変数（SST・気温・気圧水準）：変化が緩やか → H=28 でも有効
SLOW_FACTORS = {
    "sst",
    "temp", "temp_max", "temp_min",        # 気温（06:00・日内max/min）
    "pressure", "pressure_min",            # 気圧水準
    "pressure_delta",                      # 気圧変化傾向（低気圧接近シグナル）
    "tide_range", "moon_age", "tide_type_n",
}
# 速い変数（風・波・降水・急変動）：数日で激変 → H>7 では無効化
FAST_FACTORS = {
    "wind_speed", "wind_dir", "wind_speed_max",
    "wave_height", "wave_height_max",
    "wave_period", "wave_period_min",      # 波周期（最短=荒れた海）
    "swell_height", "swell_height_max",
    "temp_range",                          # 日較差（晴天シグナル、急変しやすい）
    "pressure_range",                      # 日内変動幅（前線通過強度）
    "precip_sum",                          # 当日合計降水量
    "precip_sum1",                         # 前日合計（翌日の濁り）
    "precip_sum2",                         # 前々日合計（2日遅れ濁りピーク）
    "prev_week_cnt",                       # 前週釣果（自己相関）H>7では2週以上前の情報になるため無効化
}
FAST_MAX_H = 7   # 速い変数は H>7 では予報精度ゼロとみなして使わない

# ── 全因子リスト（相関計算・バックテスト対象）──────────────────────────────
WX_FACTORS = [
    # 水温・気温（遅い変数）
    "sst",
    "temp", "temp_max", "temp_min", "temp_range",
    # 気圧（水準 + 変化）
    "pressure", "pressure_min",
    "pressure_delta",   # 当日min - 前日min（低気圧接近/通過シグナル）
    "pressure_range",   # 日内変動幅（前線通過強度 → 全魚種で活性化）
    # 風（06:00瞬間値 + 日内最大）
    "wind_speed", "wind_dir", "wind_speed_max",
    # 波浪（06:00瞬間値 + 日内max/min）
    "wave_height", "wave_height_max",
    "wave_period", "wave_period_min",
    "swell_height", "swell_height_max",
    # 降水量（日次合計 + ラグ）
    # 【重要】雨の2日後に濁りが最大 → precip_sum2 が負相関（全魚種共通シグナル）
    "precip_sum",    # 当日合計：低気圧通過シグナル（正相関の可能性）
    "precip_sum1",   # 前日合計：翌日の濁り（負相関の可能性）
    "precip_sum2",   # 前々日合計：2日遅れ濁りピーク（負相関 → 全魚種適用）
]
# 潮汐（tide テーブルから取る）
TIDE_FACTORS = ["tide_range", "moon_age", "tide_type_n"]

# 釣果自己相関因子（前週釣果 → H≤7で有効、H>7では2週以上前の情報で精度低下）
CATCH_FACTORS = ["prev_week_cnt"]

# 全因子（相関計算対象）
ALL_FACTORS = WX_FACTORS + TIDE_FACTORS + CATCH_FACTORS

TIDE_TYPE_MAP = {"大潮": 4, "中潮": 3, "小潮": 2, "長潮": 1, "若潮": 1}

# エリア → 潮汐ポートコード マッピング
AREA_PORT = {
    # 東京湾
    "平和島":           "tokyo_bay",
    "東葛西":           "tokyo_bay",
    "浦安":             "tokyo_bay",
    "羽田":             "tokyo_bay",
    "横浜本牧港":       "tokyo_bay",
    "横浜港･新山下":    "tokyo_bay",
    "江戸川放水路･原木中山": "tokyo_bay",
    "金沢八景":         "tokyo_bay",
    "鴨居大室港":       "tokyo_bay",
    "長浦":             "tokyo_bay",
    "金谷港":           "tokyo_bay",
    "富浦港":           "tokyo_bay",
    # 相模湾
    "久比里港":         "sagami_bay",
    "大津港":           "sagami_bay",
    "小田原早川港":     "sagami_bay",
    "小網代港":         "sagami_bay",
    "大磯港":           "sagami_bay",
    "茅ヶ崎港":         "sagami_bay",
    "葉山あぶずり港":   "sagami_bay",
    "松輪江奈港":       "sagami_bay",
    "松輪間口港":       "sagami_bay",
    "長井港":           "sagami_bay",
    "保田港":           "sagami_bay",
    "洲崎港":           "sagami_bay",
    # 外房
    "外川港":           "outer_boso",
    "大原港":           "outer_boso",
    "勝浦川津港":       "outer_boso",
    "御宿岩和田港":     "outer_boso",
    "天津港":           "outer_boso",
    "太東港":           "outer_boso",
    "飯岡港":           "outer_boso",
    # 茨城
    "大洗港":           "ibaraki",
    "日立久慈港":       "ibaraki",
    "波崎港":           "ibaraki",
    "鹿島港":           "ibaraki",
    "鹿島市新浜":       "ibaraki",
    # 静岡
    "下田港":           "shizuoka",
    "松崎港":           "shizuoka",
    "沼津内港":         "shizuoka",
    "沼津静浦":         "shizuoka",
    "清水港(巴川)":     "shizuoka",
    "田子の浦港":       "shizuoka",
    "由比":             "shizuoka",
    "吉田港":           "shizuoka",
    "大井川港":         "shizuoka",
    "福田港":           "shizuoka",
    "御前崎港":         "shizuoka",
    "網代":             "shizuoka",
}

KEYWORDS = {
    "潮":   ["上げ潮", "下げ潮", "潮止まり", "二枚潮", "潮が澄", "潮が濁"],
    "活性": ["群れ", "ムラ", "単発", "入れ食い", "渋い", "活性"],
    "深度": ["深場", "浅場", "底", "中層", "表層"],
    "色":   ["澄み", "濁り", "青潮", "赤潮"],
    "流れ": ["潮流", "速潮", "潮が走", "二枚潮"],
}


# ═══════════════════════════════════════════════════════════════════════════
# ユーティリティ
# ═══════════════════════════════════════════════════════════════════════════

def _float(v):
    try:
        f = float(v)
        return f if math.isfinite(f) else None
    except (TypeError, ValueError):
        return None

def pearson(xs, ys):
    """Pearson r + p値（t近似）を返す。n < 5 なら None"""
    pairs = [(x, y) for x, y in zip(xs, ys) if x is not None and y is not None]
    n = len(pairs)
    if n < 5:
        return None, None, n
    xv = [p[0] for p in pairs]
    yv = [p[1] for p in pairs]
    mx = sum(xv) / n
    my = sum(yv) / n
    sx = math.sqrt(sum((x-mx)**2 for x in xv) / (n-1))
    sy = math.sqrt(sum((y-my)**2 for y in yv) / (n-1))
    if sx == 0 or sy == 0:
        return 0.0, 1.0, n
    r = sum((x-mx)*(y-my) for x, y in zip(xv, yv)) / ((n-1) * sx * sy)
    r = max(-1.0, min(1.0, r))
    if abs(r) >= 1.0:
        return r, 0.0, n
    t = r * math.sqrt(n-2) / math.sqrt(1-r**2)
    # 簡易p値（Abramowitz & Stegun 7.1.26 近似）
    at = abs(t)
    z  = 1 / (1 + 0.2316419 * at)
    poly = z * (0.319381530 + z * (-0.356563782
                + z * (1.781477937 + z * (-1.821255978 + z * 1.330274429))))
    phi = math.exp(-t*t/2) / math.sqrt(2*math.pi) * poly if at < 30 else 0.0
    p = max(0.0, min(1.0, 2 * phi))
    return r, p, n

def mean_std(vals):
    vals = [v for v in vals if v is not None]
    if len(vals) < 2:
        return None, None
    m = sum(vals) / len(vals)
    s = math.sqrt(sum((v-m)**2 for v in vals) / (len(vals)-1))
    return m, (s if s > 0 else None)

def decade_of(date_str):
    """YYYY/MM/DD → 旬番号 1-36"""
    try:
        d = datetime.strptime(date_str, "%Y/%m/%d")
        dec = 1 if d.day <= 10 else (2 if d.day <= 20 else 3)
        return (d.month - 1) * 3 + dec
    except Exception:
        return None


# ═══════════════════════════════════════════════════════════════════════════
# 設定ロード
# ═══════════════════════════════════════════════════════════════════════════

def load_exclude_ships():
    try:
        with open(SHIPS_FILE, encoding="utf-8") as f:
            ships = json.load(f)
        return {s["name"] for s in ships if s.get("exclude") or s.get("boat_only")}
    except Exception:
        return set()

def load_ship_area():
    """ship → area マップ"""
    try:
        with open(SHIPS_FILE, encoding="utf-8") as f:
            ships = json.load(f)
        return {s["name"]: s.get("area", "") for s in ships}
    except Exception:
        return {}

def load_wx_overrides():
    try:
        with open(OVERRIDE_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return {ship: (info["lat"], info["lon"])
                for ship, info in data.get("overrides", {}).items()}
    except Exception:
        return {}

def load_ship_coords():
    """combo_meta から avg lat/lon + オーバーライド適用"""
    conn = sqlite3.connect(DB_ANA)
    rows = conn.execute(
        "SELECT ship, AVG(lat), AVG(lon) FROM combo_meta WHERE lat IS NOT NULL GROUP BY ship"
    ).fetchall()
    conn.close()
    coords = {ship: (round(lat,4), round(lon,4)) for ship, lat, lon in rows}
    for ship, (lat, lon) in load_wx_overrides().items():
        coords[ship] = (lat, lon)
    return coords

def load_wx_coords_list():
    if not os.path.exists(DB_WX) or os.path.getsize(DB_WX) == 0:
        return []
    try:
        conn = sqlite3.connect(DB_WX)
        coords = conn.execute("SELECT DISTINCT lat, lon FROM weather").fetchall()
        conn.close()
        return list(coords)
    except Exception:
        return []

def nearest_coord(lat, lon, coords):
    if not coords:
        return (lat, lon)
    return min(coords, key=lambda c: (c[0]-lat)**2 + (c[1]-lon)**2)

def load_decadal(fish, ship):
    conn = sqlite3.connect(DB_ANA)
    rows = conn.execute(
        "SELECT decade_no, avg_cnt, avg_size, n FROM combo_decadal WHERE fish=? AND ship=?",
        (fish, ship)
    ).fetchall()
    conn.close()
    return {r[0]: {"avg_cnt": r[1], "avg_size": r[2], "n": r[3]} for r in rows}


# ═══════════════════════════════════════════════════════════════════════════
# データ読み込み（CSV + weather + tide）
# ═══════════════════════════════════════════════════════════════════════════

def load_records(fish, ship_filter=None):
    """data/YYYY-MM.csv から指定魚種のレコードをロード"""
    exclude = load_exclude_ships()
    records = []
    for fn in sorted(os.listdir(DATA_DIR)):
        if not fn.endswith(".csv") or fn == "cancellations.csv":
            continue
        with open(os.path.join(DATA_DIR, fn), encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                if row.get("is_cancellation") == "1":
                    continue
                if row.get("main_sub") != "メイン":
                    continue
                ship = row.get("ship", "").strip()
                if ship in exclude:
                    continue
                if ship_filter and ship != ship_filter:
                    continue
                tsuri = row.get("tsuri_mono", "").strip()
                if tsuri != fish:
                    continue
                date_str = row.get("date", "").strip()
                if not date_str:
                    continue
                cnt_avg = _float(row.get("cnt_avg"))
                if not cnt_avg or cnt_avg <= 0:
                    continue

                sz_min = _float(row.get("size_min"))
                sz_max = _float(row.get("size_max"))
                size_avg = ((sz_min + sz_max) / 2) if sz_min and sz_max else (sz_min or sz_max)

                kg_min = _float(row.get("kg_min"))
                kg_max = _float(row.get("kg_max"))
                kg_avg  = ((kg_min + kg_max) / 2) if kg_min and kg_max else (kg_min or kg_max)

                records.append({
                    "ship":     ship,
                    "area":     row.get("area", "").strip(),
                    "date":     date_str,
                    "decade":   decade_of(date_str),
                    "cnt_avg":  cnt_avg,
                    "cnt_min":  _float(row.get("cnt_min")),
                    "cnt_max":  _float(row.get("cnt_max")),
                    "size_avg": size_avg,
                    "kg_avg":   kg_avg,
                    "point":    row.get("point_place1", "").strip(),
                    "kanso":    (row.get("kanso_raw") or row.get("fish_raw") or "").strip(),
                    "is_train": date_str <= TRAIN_END,
                })
    records.sort(key=lambda r: r["date"])
    return records

def get_wx(conn_wx, lat, lon, date_iso):
    """指定座標・日付の 06:00 前後の海況を返す（瞬間値：波高・風速・SST など）"""
    if conn_wx is None:
        return {}
    row = conn_wx.execute("""
        SELECT wind_speed, wind_dir, temp, pressure,
               wave_height, wave_period, swell_height, sst
        FROM weather
        WHERE lat=? AND lon=? AND dt LIKE ?
        ORDER BY ABS(CAST(substr(dt,12,2) AS INT) - 6)
        LIMIT 1
    """, (lat, lon, f"{date_iso}%")).fetchone()
    if not row:
        return None
    keys = ["wind_speed","wind_dir","temp","pressure",
            "wave_height","wave_period","swell_height","sst"]
    return dict(zip(keys, row))

def get_daily_agg(conn_wx, lat, lon, date_iso):
    """その日の全3時間データ（最大8点）を日次集計して返す。"""
    if conn_wx is None:
        return {}
    rows = conn_wx.execute("""
        SELECT pressure, precipitation, wind_speed, wave_height,
               temp, swell_height, wave_period
        FROM weather
        WHERE lat=? AND lon=? AND dt LIKE ?
        ORDER BY dt
    """, (lat, lon, f"{date_iso}%")).fetchall()
    if not rows:
        return {}

    pressures     = [r[0] for r in rows if r[0] is not None]
    precips       = [r[1] for r in rows if r[1] is not None]
    wind_speeds   = [r[2] for r in rows if r[2] is not None]
    wave_heights  = [r[3] for r in rows if r[3] is not None]
    temps         = [r[4] for r in rows if r[4] is not None]
    swell_heights = [r[5] for r in rows if r[5] is not None]
    wave_periods  = [r[6] for r in rows if r[6] is not None]

    result = {}
    # 降水量：日次合計（ラグ付きで濁り判定に使用）
    if precips:
        result["precip_sum"] = sum(precips)

    # 気圧：最低値（低気圧の深さ）＋変動幅（前線通過強度）
    if pressures:
        result["pressure_min"]   = min(pressures)
        result["pressure_range"] = max(pressures) - min(pressures)

    # 風速：日内最大（最悪条件・出船判断に関与）
    if wind_speeds:
        result["wind_speed_max"] = max(wind_speeds)

    # 波高：日内最大（06:00より実態を反映）
    if wave_heights:
        result["wave_height_max"] = max(wave_heights)

    # 気温：日内最高・最低・変動幅
    if temps:
        result["temp_max"]   = max(temps)
        result["temp_min"]   = min(temps)
        result["temp_range"] = max(temps) - min(temps)  # 日較差大=晴天/移動性高気圧

    # うねり：日内最大（沖あわせ・出船可否に影響）
    if swell_heights:
        result["swell_height_max"] = max(swell_heights)

    # 波周期：日内最短（最短=短周期波が混在=荒れた海）
    if wave_periods:
        result["wave_period_min"] = min(wave_periods)

    return result

def get_tide(conn_tide, date_iso):
    """潮汐データを返す（tide_moon.sqlite から取得）"""
    if conn_tide is None:
        return None
    row = conn_tide.execute("""
        SELECT tide_coeff, moon_age, tide_type
        FROM tide_moon WHERE date=?
    """, (date_iso,)).fetchone()
    if not row:
        return None
    tide_coeff, moon_age, tide_type = row
    return {
        "tide_range":  tide_coeff,   # tide_coeff(0-100) を tide_range の代替として使用
        "moon_age":    moon_age,
        "tide_type_n": TIDE_TYPE_MAP.get(tide_type, 2),
    }

def enrich(records, ship_coords, wx_coords, conn_wx, ship_area, horizon=0, all_records=None, conn_tide=None):
    """全レコードに海況・潮汐・前週釣果を付与（horizon 日前の weather を使用）。

    all_records: 前週釣果(prev_week_cnt)の参照用に全期間レコードを渡す。
    Noneのとき records 内のみで探索。
    horizon=H のとき、prediction_date = D - H 以前の最新釣果を prev_week_cnt とする。
    H=0〜7: 先週以内の釣果 → 有効  |  H>7: 2週以上前 → FAST_FACTORS により無効化
    """
    wx_cache   = {}
    tide_cache = {}
    result = []

    # 前週釣果の参照先（日付昇順ソート済み）
    _ref_records = sorted(all_records or records, key=lambda r: r["date"])
    # 日付→cnt_avg の高速参照用インデックス（先頭から順に走査）
    _ref_dates = [r["date"] for r in _ref_records]

    for r in records:
        ship = r["ship"]
        if ship not in ship_coords:
            continue
        slat, slon = ship_coords[ship]
        wlat, wlon = nearest_coord(slat, slon, wx_coords)

        try:
            d = datetime.strptime(r["date"], "%Y/%m/%d")
        except ValueError:
            continue
        wx_date   = (d - timedelta(days=horizon)).strftime("%Y-%m-%d")
        tide_date = d.strftime("%Y-%m-%d")  # 潮汐は当日固定（天文計算で確定）

        # 海況（horizon 日前）
        wk = (wlat, wlon, wx_date)
        if wk not in wx_cache:
            wx_cache[wk] = get_wx(conn_wx, wlat, wlon, wx_date)
        wx = wx_cache[wk]
        if not wx:
            continue

        # ── 日次集計（3時間×8点を横断）──────────────────────────────────
        # 当日の日次集計（precip_sum0, pressure_min, pressure_range など）
        dagg_key = (wlat, wlon, wx_date, "dagg")
        if dagg_key not in wx_cache:
            wx_cache[dagg_key] = get_daily_agg(conn_wx, wlat, wlon, wx_date)
        dagg = wx_cache[dagg_key]
        wx.update(dagg)  # precip_sum0, pressure_min, pressure_range, wind_speed_max, wave_height_max

        # 前日（D-1）の日次集計
        prev_date1 = (d - timedelta(days=horizon+1)).strftime("%Y-%m-%d")
        dagg1_key = (wlat, wlon, prev_date1, "dagg")
        if dagg1_key not in wx_cache:
            wx_cache[dagg1_key] = get_daily_agg(conn_wx, wlat, wlon, prev_date1)
        dagg1 = wx_cache[dagg1_key]
        wx["precip_sum1"]      = dagg1.get("precip_sum")       # 前日合計降水量
        wx["pressure_min1"]    = dagg1.get("pressure_min")     # 前日最低気圧

        # 前々日（D-2）の日次集計
        prev_date2 = (d - timedelta(days=horizon+2)).strftime("%Y-%m-%d")
        dagg2_key = (wlat, wlon, prev_date2, "dagg")
        if dagg2_key not in wx_cache:
            wx_cache[dagg2_key] = get_daily_agg(conn_wx, wlat, wlon, prev_date2)
        dagg2 = wx_cache[dagg2_key]
        wx["precip_sum2"]      = dagg2.get("precip_sum")       # 前々日合計降水量

        # pressure_delta: 当日最低気圧 - 前日最低気圧（気圧変化の方向・速度）
        p_today = wx.get("pressure_min")
        p_prev  = wx.get("pressure_min1")
        wx["pressure_delta"] = (p_today - p_prev) if (p_today and p_prev) else None

        # 潮汐（当日）: tide_moon.sqlite から日付ベースで取得
        tk = tide_date
        if tk not in tide_cache:
            tide_cache[tk] = get_tide(conn_tide, tide_date)
        tide = tide_cache[tk] or {}

        # ── 前週釣果（prev_week_cnt）────────────────────────────────────────
        # prediction_date = D - horizon の時点で知っている最新の釣果を取得
        # 同船宿の直近釣果が最良の事前情報（自己相関 r=0.4〜0.5）
        pred_date_str = (d - timedelta(days=horizon)).strftime("%Y/%m/%d")
        prev_cnt = None
        # _ref_dates は昇順済み → 後ろから走査して最初に pred_date_str 未満を見つける
        for _pr in reversed(_ref_records):
            if _pr["date"] < pred_date_str and _pr.get("cnt_avg") is not None:
                prev_cnt = _pr["cnt_avg"]
                break
        wx["prev_week_cnt"] = prev_cnt

        rec = dict(r)
        rec.update(wx)
        rec.update(tide)
        result.append(rec)

    return result


# ═══════════════════════════════════════════════════════════════════════════
# 分析関数
# ═══════════════════════════════════════════════════════════════════════════

def section_basic(records):
    cnts = [r["cnt_avg"] for r in records if r["cnt_avg"] is not None]
    n = len(cnts)
    if not cnts:
        return ["  (釣果数データなし)"]
    m, s = mean_std(cnts)
    if m is None:
        m = sum(cnts) / len(cnts)
    if s is None:
        s = 0.0
    med = sorted(cnts)[n//2]

    cnt_mins = [r["cnt_min"] for r in records if r["cnt_min"]]
    cnt_maxs = [r["cnt_max"] for r in records if r["cnt_max"]]
    sizes    = [r["size_avg"] for r in records if r["size_avg"]]
    kgs      = [r["kg_avg"]   for r in records if r["kg_avg"]]

    lines = [
        f"  件数: {n}件 / 期間: {records[0]['date']} 〜 {records[-1]['date']}",
        f"  cnt_avg  : 平均 {m:.1f}匹  中央値 {med:.1f}  std {s:.1f}  "
        f"[{min(cnts):.0f} 〜 {max(cnts):.0f}]",
    ]
    if cnt_mins:
        lines.append(
            f"  cnt_min  : 平均 {sum(cnt_mins)/len(cnt_mins):.1f}  "
            f"cnt_max 平均 {sum(cnt_maxs)/len(cnt_maxs):.1f}"
            f"  ({len(cnt_mins)}/{n}件, {len(cnt_mins)/n*100:.0f}%)"
        )
    if sizes:
        ms, ss = mean_std(sizes)
        if ms is not None:
            ss_s = f"{ss:.1f}" if ss is not None else "-"
            lines.append(
                f"  size_avg : 平均 {ms:.1f}cm  std {ss_s}"
                f"  [{min(sizes):.0f} 〜 {max(sizes):.0f}]"
                f"  ({len(sizes)}/{n}件, {len(sizes)/n*100:.0f}%)"
            )
    if kgs:
        mk, sk = mean_std(kgs)
        if mk is not None:
            sk_s = f"{sk:.2f}" if sk is not None else "-"
            lines.append(
                f"  kg_avg   : 平均 {mk:.2f}kg  std {sk_s}"
                f"  ({len(kgs)}/{n}件, {len(kgs)/n*100:.0f}%)"
            )
    return lines

def section_decadal(records, decadal):
    if not decadal:
        return ["  (combo_decadal データなし)"]
    buckets = defaultdict(list)
    for r in records:
        if r["decade"]:
            buckets[r["decade"]].append(r["cnt_avg"])

    lines = [f"  {'旬':>4}  {'期待':>7}  {'実績':>7}  {'偏差':>7}  {'n':>4}  "]
    lines.append("  " + "-"*45)
    for dn in sorted(decadal):
        exp  = decadal[dn]["avg_cnt"]
        acts = buckets.get(dn, [])
        if not acts or not exp:
            continue
        act = sum(acts)/len(acts)
        dev = act - exp
        lines.append(f"  {dn:>4}  {exp:>7.1f}  {act:>7.1f}  {dev:>+7.1f}  {len(acts):>4}")
    return lines[:22]

def section_corr(enriched_recs, metrics=None):
    if metrics is None:
        metrics = ["cnt_avg", "cnt_max", "size_avg", "kg_avg"]
    lines = []
    all_results = {}
    for metric in metrics:
        ys = [r.get(metric) for r in enriched_recs]
        if sum(1 for y in ys if y is not None) < 10:
            continue
        sig = []
        for fac in ALL_FACTORS:
            xs = [r.get(fac) for r in enriched_recs]
            rv, pv, nn = pearson(xs, ys)
            if rv is None:
                continue
            all_results[(metric, fac)] = (rv, pv, nn)
            if abs(rv) >= 0.08 and pv < 0.10:
                sig.append((fac, rv, pv, nn))
        if not sig:
            continue
        sig.sort(key=lambda x: -abs(x[1]))
        lines.append(f"\n  [{metric}]")
        for fac, rv, pv, nn in sig[:12]:
            star = "**" if pv < 0.01 else ("*" if pv < 0.05 else " ")
            arrow = "↑" if rv > 0 else "↓"
            lines.append(
                f"    {fac:<16} r={rv:+.3f}{star}  p={pv:.3f}  n={nn}  {arrow}"
            )
    return lines or ["  (有意な相関なし)"], all_results

def section_keywords(records):
    """コメントキーワード解析。(lines, kw_data) を返す。
    kw_data: list of (category, keyword, n, avg_in, avg_out, pct_diff)
    """
    lines = []
    kw_data = []
    for cat, kws in KEYWORDS.items():
        cat_rows = []
        for kw in kws:
            hits = [r for r in records if kw in r.get("kanso","")]
            miss = [r for r in records if kw not in r.get("kanso","")]
            if len(hits) < 3:
                continue
            ah = sum(r["cnt_avg"] for r in hits) / len(hits)
            am = sum(r["cnt_avg"] for r in miss) / len(miss) if miss else 0
            pct = (ah - am) / am * 100 if am else 0
            cat_rows.append((cat, kw, len(hits), ah, am, pct))
        if not cat_rows:
            continue
        lines.append(f"\n  [{cat}]")
        for cat_, kw, nh, ah, am, pct in sorted(cat_rows, key=lambda x: -abs(x[5])):
            sign = "+" if pct >= 0 else ""
            lines.append(
                f"    「{kw}」 n={nh:>3}  {ah:.1f}匹  vs 通常 {am:.1f}匹  "
                f"({sign}{pct:.0f}%)"
            )
            kw_data.append((cat_, kw, nh, ah, am, pct))
    return (lines or ["  (有意なキーワードなし)"]), kw_data

def section_points(records):
    buckets = defaultdict(list)
    for r in records:
        pt = r["point"]
        if pt:
            buckets[pt].append(r["cnt_avg"])
    if not buckets:
        return ["  (ポイントデータなし)"]
    lines = [f"  {'ポイント':<22}  {'n':>4}  {'平均':>7}  {'最大':>7}  {'最小':>7}"]
    lines.append("  " + "-"*55)
    for pt, cnts in sorted(buckets.items(), key=lambda x: -sum(x[1])/len(x[1])):
        if len(cnts) < 2:
            continue
        avg = sum(cnts)/len(cnts)
        lines.append(
            f"  {pt:<22}  {len(cnts):>4}  {avg:>7.1f}  {max(cnts):>7.0f}  {min(cnts):>7.0f}"
        )
    return lines[:16]

def _mape(preds, acts):
    pairs = [(p, a) for p, a in zip(preds, acts) if a and a > 0]
    if not pairs:
        return None
    return sum(abs(p-a)/a for p, a in pairs) / len(pairs) * 100

def _dir_acc(preds, acts):
    dc = dt = 0
    for i in range(1, len(acts)):
        pd_ = preds[i] - preds[i-1]
        ad_ = acts[i]  - acts[i-1]
        if pd_ != 0 and ad_ != 0:
            if (pd_ > 0) == (ad_ > 0):
                dc += 1
            dt += 1
    return dc / dt if dt else None

def _backtest_metric(metric, train_en, test_en_by_H, hist_params, decadal,
                     global_mean, global_std, train_sorted, factor_r_all,
                     metric_decadal=None):
    """1メトリクス分のバックテスト行を返す"""
    # メトリクス専用の factor_r を計算
    tr_ys = [r.get(metric) for r in train_en]
    factor_r = {}
    for fac in ALL_FACTORS:
        xs = [r.get(fac) for r in train_en]
        rv, _, _ = pearson(xs, tr_ys)
        if rv is not None and abs(rv) >= 0.05:
            factor_r[fac] = rv
    if not factor_r:
        return None, None, []

    met_vals = [r.get(metric) for r in train_en if r.get(metric) is not None]
    met_mean, met_std = mean_std(met_vals)
    if met_mean is None or not met_std:
        return None, None, []

    # 自船前回の自己相関（cnt_avg ベース → メトリクス本体で）
    own_pairs = [(train_sorted[i-1].get(metric), train_sorted[i].get(metric))
                 for i in range(1, len(train_sorted))]
    own_pairs = [(x, y) for x, y in own_pairs if x is not None and y is not None]
    r_own, _, n_own = pearson([x for x,y in own_pairs], [y for x,y in own_pairs])
    r_own = r_own if r_own is not None else 0.0
    r_own_sq = r_own ** 2

    # メトリクス専用の旬別ベースライン（metric_decadal[decade_no] = mean_val）
    # → 渡されなければ met_mean で代用
    m_dec = metric_decadal or {}

    rows = []
    for H, te_en in sorted(test_en_by_H.items()):
        usable = {fac: rv for fac, rv in factor_r.items()
                  if fac in SLOW_FACTORS or H <= FAST_MAX_H}
        w_h = sum(rv**2 for rv in usable.values()) or 1.0

        preds, acts = [], []
        for r in te_en:
            act = r.get(metric)
            if act is None:
                continue
            d_obj  = datetime.strptime(r["date"], "%Y/%m/%d")
            cutoff = (d_obj - timedelta(days=H)).strftime("%Y/%m/%d")
            last_own = None
            for tr in reversed(train_sorted):
                if tr["date"] < cutoff:
                    last_own = tr
                    break

            dn   = r.get("decade")
            # 全メトリクスで旬別ベースラインを使用（季節成分を除去して因子効果を分離）
            # cnt_avg: combo_decadal テーブル優先、なければ学習データ内旬別平均
            # cnt_min/cnt_max/size_avg: 学習データ内旬別平均を使用
            if metric == "cnt_avg" and decadal and dn in decadal:
                base = decadal[dn].get("avg_cnt", met_mean)
            else:
                base = m_dec.get(dn, met_mean)

            num_wx = 0.0
            for fac, rv in usable.items():
                val = r.get(fac)
                if val is None or fac not in hist_params:
                    continue
                m, s = hist_params[fac]
                z = (val - m) / s
                num_wx += rv**2 * z * (1.0 if rv > 0 else -1.0)

            if last_own and r_own_sq > 0 and met_std:
                own_val = last_own.get(metric)
                if own_val is not None:
                    own_z   = (own_val - met_mean) / met_std
                    num_own = r_own_sq * own_z * (1.0 if r_own > 0 else -1.0)
                    w_total = w_h + r_own_sq
                    pred = base + ((num_wx + num_own) / w_total) * met_std * 0.5
                else:
                    pred = base + (num_wx / w_h) * met_std * 0.5
            else:
                pred = base + (num_wx / w_h) * met_std * 0.5

            preds.append(pred)
            acts.append(act)

        if len(acts) < 3:
            continue
        rv_t, _, n = pearson(preds, acts)
        if rv_t is None:
            continue
        mae  = sum(abs(p-a) for p, a in zip(preds, acts)) / len(preds)
        mape = _mape(preds, acts)
        dacc = _dir_acc(preds, acts)
        n_f  = len(usable)
        rows.append((H, rv_t, mae, mape, dacc, n, n_f, len(factor_r)))

    fac_desc = ", ".join(
        f"{k}({v:+.2f})"
        for k, v in sorted(factor_r.items(), key=lambda x: -abs(x[1]))[:4]
    )
    return fac_desc, (r_own, n_own), rows


def section_backtest_rolling(records, ship_coords, wx_coords, conn_wx, ship_area, decadal, conn_tide=None):
    """ローリング月次クロスバリデーション

    各月をテスト期として、それ以前の全データを学習に使う拡張ウィンドウCV。
    固定分割（≤2024/12 = train）より本番運用に近い評価方法。
    本番では「全期間でパラメータ推定 → 来週を予測」するため、
    rolling CV がその流れを最も正確にシミュレートする。
    """
    MIN_TRAIN_N = 15
    MIN_TRAIN_MONTHS = 4

    months = sorted(set(r["date"][:7] for r in records))
    if len(months) < MIN_TRAIN_MONTHS + 1:
        return ["  データ不足（ローリングCV最低月数に達しない）"], []

    # 全ホライズン分を一括 enrich（SQL クエリを事前に全発行してキャッシュ活用）
    all_en_by_H = {}
    for H in HORIZONS:
        all_en_by_H[H] = enrich(
            records, ship_coords, wx_coords, conn_wx, ship_area,
            horizon=H, all_records=records, conn_tide=conn_tide
        )

    METRICS_LIST = ["cnt_avg", "cnt_min", "cnt_max", "size_avg"]
    # 各月・各ホライズンの予測と実測を蓄積
    all_preds = {met: {H: [] for H in HORIZONS} for met in METRICS_LIST}
    all_acts  = {met: {H: [] for H in HORIZONS} for met in METRICS_LIST}

    for test_month in months:
        train_en_h0 = [r for r in all_en_by_H[0] if r["date"][:7] < test_month]
        if len(train_en_h0) < MIN_TRAIN_N:
            continue

        # 学習データからパラメータ推定
        hist_params_m = {}
        for fac in ALL_FACTORS:
            vals = [r.get(fac) for r in train_en_h0 if r.get(fac) is not None]
            m2, s2 = mean_std(vals)
            if m2 is not None and s2:
                hist_params_m[fac] = (m2, s2)

        train_sorted_m = sorted(train_en_h0, key=lambda r: r["date"])

        # メトリクス別 旬別ベースライン（学習データから）
        metric_decadal_m = {}
        for met in METRICS_LIST:
            _db = defaultdict(list)
            for r in train_en_h0:
                dn = r.get("decade"); val = r.get(met)
                if dn is not None and val is not None:
                    _db[dn].append(val)
            metric_decadal_m[met] = {dn: sum(v)/len(v) for dn, v in _db.items()}

        for met in METRICS_LIST:
            tr_ys = [r.get(met) for r in train_en_h0]
            factor_r_m = {}
            for fac in ALL_FACTORS:
                xs = [r.get(fac) for r in train_en_h0]
                rv, _, _ = pearson(xs, tr_ys)
                if rv is not None and abs(rv) >= 0.05:
                    factor_r_m[fac] = rv
            if not factor_r_m:
                continue

            met_vals = [r.get(met) for r in train_en_h0 if r.get(met) is not None]
            met_mean_m, met_std_m = mean_std(met_vals)
            if met_mean_m is None or not met_std_m:
                continue

            m_dec = metric_decadal_m.get(met, {})

            for H in HORIZONS:
                te_en_h = [r for r in all_en_by_H[H] if r["date"][:7] == test_month]
                usable  = {fac: rv for fac, rv in factor_r_m.items()
                           if fac in SLOW_FACTORS or H <= FAST_MAX_H}
                w_h = sum(rv**2 for rv in usable.values()) or 1.0

                for r in te_en_h:
                    act = r.get(met)
                    if act is None:
                        continue

                    dn = r.get("decade")
                    if met == "cnt_avg" and decadal and dn in decadal:
                        base = decadal[dn].get("avg_cnt", met_mean_m)
                    else:
                        base = m_dec.get(dn, met_mean_m)

                    num_wx = 0.0
                    for fac, rv in usable.items():
                        val = r.get(fac)
                        if val is None or fac not in hist_params_m:
                            continue
                        fm, fs = hist_params_m[fac]
                        z = (val - fm) / fs
                        num_wx += rv**2 * z * (1.0 if rv > 0 else -1.0)

                    pred = base + (num_wx / w_h) * met_std_m * 0.5
                    all_preds[met][H].append(pred)
                    all_acts[met][H].append(act)

    # 結果出力
    total_n = len(all_acts["cnt_avg"].get(0, []))
    lines = [
        f"  ローリング月次CV  全{len(months)}ヶ月  テスト総計: {total_n}件",
    ]

    METRIC_LABEL = {"cnt_avg": "Ave匹数", "cnt_min": "Min匹数",
                    "cnt_max": "Max匹数", "size_avg": "Ave型  "}
    METRIC_UNIT  = {"cnt_avg": "匹", "cnt_min": "匹", "cnt_max": "匹", "size_avg": "cm"}
    bt_data = []

    for met in METRICS_LIST:
        label = METRIC_LABEL[met]
        unit  = METRIC_UNIT[met]
        rows  = []
        for H in HORIZONS:
            ps = all_preds[met][H]; acs = all_acts[met][H]
            if len(acs) < 3:
                continue
            rv, _, n = pearson(ps, acs)
            if rv is None:
                continue
            mae_v  = sum(abs(p-a) for p,a in zip(ps,acs)) / len(ps)
            mape_v = _mape(ps, acs)
            dacc_v = _dir_acc(ps, acs)
            n_f    = sum(1 for fac in ALL_FACTORS
                         if fac in SLOW_FACTORS or H <= FAST_MAX_H)
            rows.append((H, rv, mae_v, mape_v, dacc_v, n, n_f))

        if not rows:
            lines.append(f"\n  ─ {label} : データ不足 ─")
            continue

        lines.append(f"\n  ─ {label} ─")
        lines.append(f"  {'ホライズン':>10}  {'r':>7}  {'MAE':>7}  {'MAPE':>7}  {'方向一致':>9}  {'n':>4}")
        lines.append("  " + "-"*55)
        for H, rv, mae, mape, dacc, n, n_f in rows:
            lh    = "H=  0(実測)" if H == 0 else f"H={H:>3}d 前"
            star  = "**" if rv >= 0.4 else ("*" if rv >= 0.2 else " ")
            ms    = f"{mape:>6.1f}%" if mape else "     -"
            ds    = f"{dacc:>9.1%}" if dacc is not None else "        -"
            fn    = f"({n_f}/{len(ALL_FACTORS)}因子)" if n_f < len(ALL_FACTORS) else ""
            lines.append(
                f"  {lh:>12}  {rv:>+6.3f}{star}  {mae:>6.1f}{unit}  {ms}  {ds}  {n:>4}  {fn}"
            )
            bt_data.append((met, H, rv, mae, mape, dacc, n, 0.0))

    return lines, bt_data


def section_backtest(records, ship_coords, wx_coords, conn_wx, ship_area, decadal):
    train = [r for r in records if r["is_train"]]
    test  = [r for r in records if not r["is_train"]]
    if len(train) < 15:
        return [f"  学習データ不足 ({len(train)}件)"], []
    if len(test) < 5:
        return [f"  テストデータ不足 ({len(test)}件)"], []

    tr_en = enrich(train, ship_coords, wx_coords, conn_wx, ship_area, horizon=0, all_records=records)
    if len(tr_en) < 10:
        return ["  学習データの海況マッチ不足"], []

    # 共通: 海況因子の hist_params（z正規化用）
    hist_params = {}
    for fac in ALL_FACTORS:
        vals = [r.get(fac) for r in tr_en if r.get(fac) is not None]
        m, s = mean_std(vals)
        if m is not None and s:
            hist_params[fac] = (m, s)

    global_mean, global_std = mean_std([r["cnt_avg"] for r in tr_en])
    train_sorted = sorted(train, key=lambda r: r["date"])

    # メトリクス専用の旬別ベースライン（学習データから計算）
    # 全メトリクスで季節成分を除去 → Min/Max の負r問題を解消
    METRICS_LIST = ["cnt_avg", "cnt_min", "cnt_max", "size_avg"]
    metric_decadal_all = {}
    for _met in METRICS_LIST:
        _db = defaultdict(list)
        for r in tr_en:
            dn = r.get("decade")
            val = r.get(_met)
            if dn is not None and val is not None:
                _db[dn].append(val)
        metric_decadal_all[_met] = {dn: sum(v)/len(v) for dn, v in _db.items()}

    # テストデータを全ホライズン分 enrich（1回ずつ）
    test_en_by_H = {}
    for H in HORIZONS:
        te = enrich(test, ship_coords, wx_coords, conn_wx, ship_area, horizon=H, all_records=records)
        if len(te) >= 3:
            test_en_by_H[H] = te

    lines = [
        f"  学習: 〜{TRAIN_END}  ({len(tr_en)}件マッチ)  "
        f"テスト: {TRAIN_END[:4]}以降 ({len(test)}件)",
    ]

    METRICS = [
        ("cnt_avg",  "匹"),
        ("cnt_min",  "匹"),
        ("cnt_max",  "匹"),
        ("size_avg", "cm"),
    ]
    METRIC_LABEL = {
        "cnt_avg":  "Ave匹数",
        "cnt_min":  "Min匹数",
        "cnt_max":  "Max匹数",
        "size_avg": "Ave型  ",
    }

    # ── 逆転バックテスト用: テストデータ(2025+)を学習として使う ──────────────
    # 逆転チェック: 2025+ = 訓練、〜2024 = テスト
    # 両方向で r > 0 なら因子が真に頑健、片方が負なら分布シフトあり
    te_rev_en = tr_en  # 〜2024 の H=0 データをテストとして使用
    tr_rev_en = test_en_by_H.get(0, [])  # 2025+ の H=0 データを訓練として使用
    rev_available = len(tr_rev_en) >= 5 and len(te_rev_en) >= 5
    if rev_available:
        hist_params_rev = {}
        for fac in ALL_FACTORS:
            vals = [r.get(fac) for r in tr_rev_en if r.get(fac) is not None]
            m2, s2 = mean_std(vals)
            if m2 is not None and s2:
                hist_params_rev[fac] = (m2, s2)
        train_sorted_rev = sorted(
            [r for r in records if not r["is_train"]], key=lambda r: r["date"]
        )
        metric_decadal_rev = {}
        for _met in METRICS_LIST:
            _db2 = defaultdict(list)
            for r in tr_rev_en:
                dn = r.get("decade")
                val = r.get(_met)
                if dn is not None and val is not None:
                    _db2[dn].append(val)
            metric_decadal_rev[_met] = {dn: sum(v)/len(v) for dn, v in _db2.items()}

    bt_data = []  # (metric, H, rv, mae, mape, dacc, n, r_own)
    for metric, unit in METRICS:
        fac_desc, own_info, rows = _backtest_metric(
            metric, tr_en, test_en_by_H, hist_params, decadal,
            global_mean, global_std, train_sorted, {},
            metric_decadal=metric_decadal_all.get(metric)
        )
        if not rows:
            lines.append(f"\n  ─ {METRIC_LABEL[metric]} : データ不足 ─")
            continue

        # 逆転チェック（H=0のみ）: 因子の頑健性を確認
        rev_r_str = ""
        if rev_available:
            _, _, rev_rows = _backtest_metric(
                metric, tr_rev_en, {0: te_rev_en}, hist_params_rev, decadal,
                *mean_std([r["cnt_avg"] for r in tr_rev_en]),
                train_sorted_rev, {},
                metric_decadal=metric_decadal_rev.get(metric)
            )
            if rev_rows:
                rv_rev = rev_rows[0][1]  # H=0 の r
                mark = "✓" if rv_rev > 0 else "⚠"
                rev_r_str = f"  逆転r={rv_rev:+.3f}{mark}"

        r_own, n_own = own_info
        lines.append(f"\n  ─ {METRIC_LABEL[metric]}  因子: {fac_desc}  自己相関r={r_own:+.3f}(n={n_own}){rev_r_str} ─")
        lines.append(
            f"  {'ホライズン':>10}  {'r':>7}  {'MAE':>7}  {'MAPE':>7}  {'方向一致':>9}  {'n':>4}"
        )
        lines.append("  " + "-"*55)
        for H, rv, mae, mape, dacc, n, n_f, n_f_all in rows:
            label    = "H=  0(実測)" if H == 0 else f"H={H:>3}d 前"
            star     = "**" if rv >= 0.4 else ("*" if rv >= 0.2 else " ")
            mape_s   = f"{mape:>6.1f}%" if mape else "     -"
            dacc_s   = f"{dacc:>9.1%}" if dacc is not None else "        -"
            fac_note = f"({n_f}/{n_f_all}因子)" if n_f < n_f_all else ""
            lines.append(
                f"  {label:>12}  {rv:>+6.3f}{star}  {mae:>6.1f}{unit}  {mape_s}  {dacc_s}  {n:>4}  {fac_note}"
            )
            bt_data.append((metric, H, rv, mae, mape, dacc, n, r_own))

    return lines, bt_data


# ═══════════════════════════════════════════════════════════════════════════
# DB 保存
# ═══════════════════════════════════════════════════════════════════════════

def save_params(fish, ship, corr_results):
    conn = sqlite3.connect(DB_ANA)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS combo_deep_params (
            fish    TEXT,
            ship    TEXT,
            factor  TEXT,
            metric  TEXT,
            r       REAL,
            p       REAL,
            n       INTEGER,
            PRIMARY KEY (fish, ship, factor, metric)
        )
    """)
    rows = [(fish, ship, fac, metric, rv, pv, nn)
            for (metric, fac), (rv, pv, nn) in corr_results.items()]
    conn.executemany(
        "INSERT OR REPLACE INTO combo_deep_params VALUES (?,?,?,?,?,?,?)", rows
    )
    conn.commit()
    conn.close()


def save_keywords(fish, ship, kw_data):
    """コメントキーワード解析結果を combo_keywords テーブルに保存"""
    if not kw_data:
        return
    conn = sqlite3.connect(DB_ANA)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS combo_keywords (
            fish        TEXT,
            ship        TEXT,
            category    TEXT,
            keyword     TEXT,
            n           INTEGER,
            avg_in      REAL,
            avg_out     REAL,
            pct_diff    REAL,
            updated_at  TEXT,
            PRIMARY KEY (fish, ship, keyword)
        )
    """)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rows = [(fish, ship, cat, kw, n, avg_in, avg_out, pct, now)
            for cat, kw, n, avg_in, avg_out, pct in kw_data]
    conn.executemany(
        "INSERT OR REPLACE INTO combo_keywords VALUES (?,?,?,?,?,?,?,?,?)", rows
    )
    conn.commit()
    conn.close()


def save_backtest(fish, ship, bt_data):
    """バックテスト結果を combo_backtest テーブルに保存"""
    if not bt_data:
        return
    conn = sqlite3.connect(DB_ANA)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS combo_backtest (
            fish        TEXT,
            ship        TEXT,
            metric      TEXT,
            horizon     INTEGER,
            r           REAL,
            mae         REAL,
            mape        REAL,
            dir_acc     REAL,
            n           INTEGER,
            r_own       REAL,
            updated_at  TEXT,
            PRIMARY KEY (fish, ship, metric, horizon)
        )
    """)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rows = [(fish, ship, metric, H, rv, mae, mape, dacc, n, r_own, now)
            for metric, H, rv, mae, mape, dacc, n, r_own in bt_data]
    conn.executemany(
        "INSERT OR REPLACE INTO combo_backtest VALUES (?,?,?,?,?,?,?,?,?,?,?)", rows
    )
    conn.commit()
    conn.close()


# ═══════════════════════════════════════════════════════════════════════════
# メイン
# ═══════════════════════════════════════════════════════════════════════════

def deep_dive(fish, ship, verbose=True):
    os.makedirs(OUT_DIR, exist_ok=True)

    ship_coords = load_ship_coords()
    wx_coords   = load_wx_coords_list()
    ship_area   = load_ship_area()

    records = load_records(fish, ship_filter=ship)
    if len(records) < MIN_N_COMBO:
        print(f"  {fish} × {ship}: データ不足 ({len(records)}件)")
        return

    conn_wx   = sqlite3.connect(DB_WX)   if (os.path.exists(DB_WX)   and os.path.getsize(DB_WX)   > 0) else None
    conn_tide = sqlite3.connect(DB_TIDE) if (os.path.exists(DB_TIDE) and os.path.getsize(DB_TIDE) > 0) else None
    en0     = enrich(records, ship_coords, wx_coords, conn_wx, ship_area, horizon=0, all_records=records, conn_tide=conn_tide)
    decadal = load_decadal(fish, ship)

    SEP  = "=" * 72
    sep2 = "-" * 60

    out = []
    out.append(SEP)
    out.append(f"  {fish} × {ship}")
    out.append(SEP)

    out.append("\n【基本統計】")
    out += section_basic(records)

    out.append(f"\n【旬別ベースライン（n={len(records)}件）】")
    out += section_decadal(records, decadal)

    out.append(f"\n【因子相関（海況マッチ: {len(en0)}件, 予報可能因子のみ）】")
    corr_lines, corr_results = section_corr(en0)
    out += corr_lines

    out.append("\n【コメントキーワード解析】")
    kw_lines, kw_data = section_keywords(records)
    out += kw_lines

    out.append("\n【ポイント別集計】")
    out += section_points(records)

    out.append("\n【マルチホライズン バックテスト（ローリング月次CV）】")
    bt_lines, bt_data = section_backtest_rolling(records, ship_coords, wx_coords, conn_wx, ship_area, decadal, conn_tide=conn_tide)
    out += bt_lines

    if conn_wx is not None:
        conn_wx.close()
    if conn_tide is not None:
        conn_tide.close()

    text = "\n".join(out)
    out_path = os.path.join(OUT_DIR, f"{fish}_{ship}.txt")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(text)

    if verbose:
        print(text)
    print(f"\n  → 保存: {out_path}", flush=True)

    save_params(fish, ship, corr_results)
    save_keywords(fish, ship, kw_data)
    save_backtest(fish, ship, bt_data)


def main():
    parser = argparse.ArgumentParser(description="船宿×魚種 深掘り分析")
    parser.add_argument("--fish", required=True, help="魚種名（例: アジ）")
    parser.add_argument("--ship", default=None,  help="船宿名（省略時は全船宿）")
    args = parser.parse_args()

    if args.ship:
        deep_dive(args.fish, args.ship)
    else:
        recs_all = load_records(args.fish)
        counts = defaultdict(int)
        for r in recs_all:
            counts[r["ship"]] += 1
        ships = sorted(s for s, n in counts.items() if n >= MIN_N_COMBO)
        print(f"{args.fish}: {len(ships)}船宿（各{MIN_N_COMBO}件以上）\n")
        for ship in ships:
            deep_dive(args.fish, ship, verbose=False)


if __name__ == "__main__":
    main()
