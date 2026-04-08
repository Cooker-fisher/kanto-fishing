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
  ○ sst_avg, temp_avg/max/min, pressure_avg/min,
    wind_speed_avg/max, wind_dir_mode,
    wave_height_avg/max, wave_period_avg/min,
    swell_height_avg/max              ← 全変数を日次集計（min/max/avg）に統一
  ○ tide_range, moon_age, tide_type   ← 天文計算で未来も確定
  × current_spd, wave_dir, swell_period ← 予報APIに含まれない

[使い方]
  python insights/combo_deep_dive.py --fish アジ --ship かめだや
  python insights/combo_deep_dive.py --fish アジ          # 全船宿

[出力]
  insights/deep_dive/{魚種}_{船宿}.txt
  insights/analysis.sqlite  → combo_deep_params テーブル
"""

import argparse, bisect, csv, json, math, os, re, sqlite3, sys
from collections import defaultdict
from datetime import datetime, timedelta

import sys as _sys; _sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _paths import ROOT_DIR, RESULTS_DIR, DATA_DIR, NORMALIZE_DIR, OCEAN_DIR
DB_WX         = os.path.join(OCEAN_DIR, "weather_cache.sqlite")
DB_TIDE       = os.path.join(OCEAN_DIR, "tide_moon.sqlite")
DB_TYPHOON    = os.path.join(OCEAN_DIR, "typhoon.sqlite")
DB_ANA        = os.path.join(RESULTS_DIR, "analysis.sqlite")
OUT_DIR       = os.path.join(RESULTS_DIR, "deep_dive")
OVERRIDE_FILE  = os.path.join(NORMALIZE_DIR, "ship_wx_coord_override.json")
SHIPS_FILE     = os.path.join(ROOT_DIR, "crawl", "ships.json")
OBS_FIELDS_FILE = os.path.join(NORMALIZE_DIR, "obs_fields.json")

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
    "sst_avg",                             # SST日次平均（日内変動極小）
    "temp_avg", "temp_max", "temp_min",    # 気温（日次avg/max/min）
    "pressure_avg", "pressure_min",        # 気圧水準（日次avg/min）
    "pressure_delta",                      # 気圧変化傾向（低気圧接近シグナル）
    "tide_range", "moon_age", "tide_type_n",
}
# 速い変数（風・波・降水・急変動）：数日で激変 → H>7 では無効化
FAST_FACTORS = {
    "wind_speed_avg", "wind_speed_max",    # 風速（日次avg/max）
    "wind_dir_mode",                       # 風向（最頻方角）
    "wave_height_avg", "wave_height_max",  # 波高（日次avg/max）
    "wave_period_avg", "wave_period_min",  # 波周期（日次avg/min）
    "swell_height_avg", "swell_height_max",# うねり（日次avg/max）
    "temp_range",                          # 日較差（晴天シグナル、急変しやすい）
    "pressure_range",                      # 日内変動幅（前線通過強度）
    "precip_sum",                          # 当日合計降水量
    "precip_sum1",                         # 前日合計（翌日の濁り）
    "precip_sum2",                         # 前々日合計（2日遅れ濁りピーク）
    "prev_week_cnt",                       # 前週釣果（自己相関）H>7では2週以上前の情報になるため無効化
    "typhoon_dist", "typhoon_wind",        # 台風接近距離・最大風速（イベント変数 H≤5が有効限界）
}
FAST_MAX_H = 7   # 速い変数は H>7 では予報精度ゼロとみなして使わない

# ── 全因子リスト（相関計算・バックテスト対象）──────────────────────────────
# 06:00スナップショットを廃止し、全変数を日次集計（min/max/avg）に統一。
WX_FACTORS = [
    # 水温（日内変動極小 → avg のみ）
    "sst_avg",
    # 気温（日次 avg/max/min/range）
    "temp_avg", "temp_max", "temp_min", "temp_range",
    # 気圧（日次 avg/min + 変化 + 変動幅）
    "pressure_avg", "pressure_min",
    "pressure_delta",   # 当日min - 前日min（低気圧接近/通過シグナル）
    "pressure_range",   # 日内変動幅（前線通過強度 → 全魚種で活性化）
    # 風（日次 avg/max + 最頻風向）
    "wind_speed_avg", "wind_speed_max",
    "wind_dir_mode",    # 最頻風向（16方位に丸めて mode）
    # 波浪（日次 avg/max + 周期 avg/min）
    "wave_height_avg", "wave_height_max",
    "wave_period_avg", "wave_period_min",
    # うねり（日次 avg/max）
    "swell_height_avg", "swell_height_max",
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

# 台風因子（イベント変数 → FAST扱いで H>7 は無効化）
TYPHOON_FACTORS = ["typhoon_dist", "typhoon_wind"]

# 全因子（相関計算対象）
ALL_FACTORS = WX_FACTORS + TIDE_FACTORS + CATCH_FACTORS + TYPHOON_FACTORS

# 観測因子リストは normalize/obs_fields.json から動的に取得する。
# → OBS_FACTORS は _get_obs_factors() で取得。新CSV列追加時は obs_fields.json だけ変更。
_OBS_CONFIG_CACHE = None

def _get_obs_config():
    global _OBS_CONFIG_CACHE
    if _OBS_CONFIG_CACHE is None:
        try:
            with open(OBS_FIELDS_FILE, encoding="utf-8") as f:
                _OBS_CONFIG_CACHE = json.load(f)
        except Exception:
            _OBS_CONFIG_CACHE = {"fields": {}}
    return _OBS_CONFIG_CACHE

def _get_obs_factors():
    """obs_fields.json の role=obs_factor なフィールド名リストを返す"""
    cfg = _get_obs_config()
    return [name for name, spec in cfg.get("fields", {}).items()
            if spec.get("role") == "obs_factor"]

def _compute_obs_fields(row):
    """obs_fields.json の定義に従い CSV 行から全OBS/TEXTフィールドを計算する。
    戻り値: {field_name: value, ..., 'text_all': '...'}
    新CSV列追加時はこの関数ではなく obs_fields.json にエントリを追加する。
    """
    cfg = _get_obs_config()
    result = {}
    text_parts = []

    for name, spec in cfg.get("fields", {}).items():
        role    = spec.get("role", "obs_factor")
        compute = spec.get("compute", "direct")
        src     = spec.get("source", name)
        srcs    = [src] if isinstance(src, str) else list(src)

        val = None
        if compute == "direct":
            val = _float(row.get(srcs[0]))
        elif compute == "binary":
            v = (row.get(srcs[0]) or "").strip()
            val = float(v) if v in ("0", "1") else None
        elif compute == "avg":
            nums = [_float(row.get(s)) for s in srcs]
            nums = [n for n in nums if n is not None]
            val  = sum(nums) / len(nums) if nums else None
        elif compute == "map":
            raw = (row.get(srcs[0]) or "").strip()
            val = spec.get("map", {}).get(raw)
        elif compute == "keyword_score":
            combined = " ".join((row.get(s) or "") for s in srcs)
            for kw, score in spec.get("scores", {}).items():
                if kw in combined:
                    val = score
                    break
        elif compute == "split_count":
            raw = (row.get(srcs[0]) or "").strip()
            if raw:
                parts = re.split(r'[,、/・\s]+', raw)
                val   = float(len([p for p in parts if len(p) >= 2]))
        elif compute == "text_concat":
            raw = " ".join(filter(None, ((row.get(s) or "").strip() for s in srcs)))
            val = raw if raw else None

        result[name] = val
        if role == "text_field" and val:
            text_parts.append(val)

    result["text_all"] = " ".join(text_parts)
    return result

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
    "潮":   ["上げ潮", "下げ潮", "潮止まり", "二枚潮", "潮が澄", "潮が濁", "潮が速", "潮かわり"],
    "活性": ["群れ", "ムラ", "単発", "入れ食い", "渋い", "活性", "食い渋", "反応"],
    "深度": ["深場", "浅場", "底", "中層", "表層"],
    "色":   ["澄み", "濁り", "青潮", "赤潮", "笹濁"],
    "流れ": ["潮流", "速潮", "潮が走", "二枚潮"],
    "外道": ["外道", "ゲスト", "サメ", "フグ", "ハモ"],
    "海況": ["ウネリ", "うねり", "時化", "シケ", "べた凪", "ナギ"],
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

# ── ポイント解決（crawler.py の resolve_point と同ロジック） ─────────────────
_UNRESOLVABLE_POINT_RE = re.compile(
    r'^(航程|近場|浅場|深場|東京湾一帯|湾内|湾奥|港前|南沖|東沖|西沖|北沖|赤灯沖|観音沖|水深\d|^[0-9]+$|前後$)'
)

def _is_航程系(pp):
    return not pp or bool(_UNRESOLVABLE_POINT_RE.match(pp))

def _load_point_coords():
    path = os.path.join(NORMALIZE_DIR, "point_coords.json")
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def _load_ship_fish_point():
    path = os.path.join(NORMALIZE_DIR, "ship_fish_point.json")
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return {k: v for k, v in data.items() if not k.startswith("_")}
    except Exception:
        return {}

def _load_area_coords():
    path = os.path.join(NORMALIZE_DIR, "area_coords.json")
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def _resolve_point(point_place1, ship, tsuri_mono, sfp, ship_area_map, point_coords, area_coords):
    """point_place1 + 船宿 + 魚種 → (lat, lon)。解決不能なら (None, None)。"""
    pp = (point_place1 or "").strip()
    # ① point_place1 直接解決
    if pp and not _is_航程系(pp):
        entry = point_coords.get(pp)
        if entry and entry.get("lat") is not None:
            return entry["lat"], entry["lon"]
    # ② ship_fish_point フォールバック
    ship_data = sfp.get(ship, {})
    fish_entry = ship_data.get(tsuri_mono) or ship_data.get("_default")
    if fish_entry and isinstance(fish_entry, dict):
        for key in ("point1", "point2"):
            pname = fish_entry.get(key, "") or ""
            if pname:
                entry = point_coords.get(pname)
                if entry and entry.get("lat") is not None:
                    return entry["lat"], entry["lon"]
    # ③ area_coords フォールバック
    area = ship_area_map.get(ship, "")
    if area:
        ac = area_coords.get(area)
        if ac and ac.get("lat") is not None:
            return ac["lat"], ac["lon"]
    return None, None


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
    """combo_meta から avg lat/lon + オーバーライド適用（レコードに lat/lon がない場合の保険）"""
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
    """data/YYYY-MM.csv から指定魚種のレコードをロード。
    point_place1 → point_coords.json → lat/lon を per-record で解決する。
    """
    exclude      = load_exclude_ships()
    ship_area    = load_ship_area()
    point_coords = _load_point_coords()
    sfp          = _load_ship_fish_point()
    area_coords  = _load_area_coords()

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

                # per-record 座標解決（3段階フォールバック）
                point_place1 = row.get("point_place1", "").strip()
                lat, lon = _resolve_point(
                    point_place1, ship, tsuri, sfp, ship_area, point_coords, area_coords
                )

                # OBS/TEキストフィールドを obs_fields.json から一括計算
                obs = _compute_obs_fields(row)

                records.append({
                    "ship":    ship,
                    "area":    row.get("area", "").strip(),
                    "date":    date_str,
                    "decade":  decade_of(date_str),
                    "cnt_avg": cnt_avg,
                    "cnt_min": _float(row.get("cnt_min")),
                    "cnt_max": _float(row.get("cnt_max")),
                    "size_avg": size_avg,
                    "kg_avg":  kg_avg,
                    "point":   point_place1,
                    "lat":     lat,
                    "lon":     lon,
                    # 参照用（obs_fields.json 外）
                    "trip_no": int(row.get("trip_no") or 1),
                    "is_train": date_str <= TRAIN_END,
                    **obs,   # OBS因子 + テキストフィールド + text_all
                })
    records.sort(key=lambda r: r["date"])
    return records

def get_daily_wx(conn_wx, lat, lon, date_iso):
    """その日の全3時間データ（最大8点）を日次集計して返す。
    06:00スナップショットを廃止し、全変数を min/max/avg で統一。
    wind_dir は最頻風向（mode）を使用。
    """
    if conn_wx is None:
        return {}
    rows = conn_wx.execute("""
        SELECT wind_speed, wind_dir, temp, pressure,
               wave_height, wave_period, swell_height, sst,
               precipitation
        FROM weather
        WHERE lat=? AND lon=? AND dt LIKE ?
        ORDER BY dt
    """, (lat, lon, f"{date_iso}%")).fetchall()
    if not rows:
        return None

    wind_speeds   = [r[0] for r in rows if r[0] is not None]
    wind_dirs     = [r[1] for r in rows if r[1] is not None]
    temps         = [r[2] for r in rows if r[2] is not None]
    pressures     = [r[3] for r in rows if r[3] is not None]
    wave_heights  = [r[4] for r in rows if r[4] is not None]
    wave_periods  = [r[5] for r in rows if r[5] is not None]
    swell_heights = [r[6] for r in rows if r[6] is not None]
    ssts          = [r[7] for r in rows if r[7] is not None]
    precips       = [r[8] for r in rows if r[8] is not None]

    result = {}

    # ── 風速: avg, max ──
    if wind_speeds:
        result["wind_speed_avg"] = sum(wind_speeds) / len(wind_speeds)
        result["wind_speed_max"] = max(wind_speeds)

    # ── 風向: 最頻方角（16方位に丸めて mode）──
    if wind_dirs:
        # 16方位（22.5°刻み）に丸めて最頻値を取る
        binned = [round(d / 22.5) % 16 * 22.5 for d in wind_dirs]
        result["wind_dir_mode"] = max(set(binned), key=binned.count)

    # ── 気温: avg, max, min ──
    if temps:
        result["temp_avg"]   = sum(temps) / len(temps)
        result["temp_max"]   = max(temps)
        result["temp_min"]   = min(temps)
        result["temp_range"] = max(temps) - min(temps)

    # ── 気圧: avg, min ──
    if pressures:
        result["pressure_avg"]   = sum(pressures) / len(pressures)
        result["pressure_min"]   = min(pressures)
        result["pressure_range"] = max(pressures) - min(pressures)

    # ── 波高: avg, max ──
    if wave_heights:
        result["wave_height_avg"] = sum(wave_heights) / len(wave_heights)
        result["wave_height_max"] = max(wave_heights)

    # ── 波周期: avg, min ──
    if wave_periods:
        result["wave_period_avg"] = sum(wave_periods) / len(wave_periods)
        result["wave_period_min"] = min(wave_periods)

    # ── うねり: avg, max ──
    if swell_heights:
        result["swell_height_avg"] = sum(swell_heights) / len(swell_heights)
        result["swell_height_max"] = max(swell_heights)

    # ── SST: avg のみ（日内変動極小）──
    if ssts:
        result["sst_avg"] = sum(ssts) / len(ssts)

    # ── 降水量: 日次合計 ──
    if precips:
        result["precip_sum"] = sum(precips)

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

def get_typhoon(conn_ty, date_iso):
    """台風接近データを返す（typhoon.sqlite から取得）。
    台風なし日は None を返す（相関計算から除外するため 9999 は使わない）。
    """
    if conn_ty is not None:
        row = conn_ty.execute("""
            SELECT min_dist, wind_kt
            FROM typhoon_track
            WHERE date(dt) = ?
            ORDER BY min_dist ASC
            LIMIT 1
        """, (date_iso,)).fetchone()
        if row:
            return {"typhoon_dist": row[0], "typhoon_wind": row[1]}
    return {"typhoon_dist": None, "typhoon_wind": None}


def enrich(records, ship_coords, wx_coords, conn_wx, ship_area, horizon=0, all_records=None, conn_tide=None, conn_typhoon=None):
    """全レコードに海況・潮汐・前週釣果を付与（horizon 日前の weather を使用）。

    all_records: 前週釣果(prev_week_cnt)の参照用に全期間レコードを渡す。
    Noneのとき records 内のみで探索。
    horizon=H のとき、prediction_date = D - H 以前の最新釣果を prev_week_cnt とする。
    H=0〜7: 先週以内の釣果 → 有効  |  H>7: 2週以上前 → FAST_FACTORS により無効化
    """
    wx_cache      = {}
    tide_cache    = {}
    typhoon_cache = {}
    result = []

    # 前週釣果の参照先（日付昇順ソート済み）
    _ref_records = sorted(all_records or records, key=lambda r: r["date"])
    # bisect 用の日付リスト（O(log n) 検索）
    _ref_dates = [r["date"] for r in _ref_records]

    for r in records:
        ship = r["ship"]
        # 座標優先順: ①レコード個別lat/lon（CSV 3段階フォールバック済み）→ ②ship_coords（保険）
        rlat, rlon = r.get("lat"), r.get("lon")
        if rlat and rlon:
            wlat, wlon = nearest_coord(rlat, rlon, wx_coords)
        elif ship in ship_coords:
            slat, slon = ship_coords[ship]
            wlat, wlon = nearest_coord(slat, slon, wx_coords)
        else:
            continue

        try:
            d = datetime.strptime(r["date"], "%Y/%m/%d")
        except ValueError:
            continue
        wx_date   = (d - timedelta(days=horizon)).strftime("%Y-%m-%d")
        tide_date = d.strftime("%Y-%m-%d")  # 潮汐は当日固定（天文計算で確定）

        # 海況（horizon 日前）── 全変数を日次集計（min/max/avg）で取得
        wk = (wlat, wlon, wx_date)
        if wk not in wx_cache:
            wx_cache[wk] = get_daily_wx(conn_wx, wlat, wlon, wx_date)
        wx = wx_cache[wk]
        if not wx:
            continue
        wx = dict(wx)  # 元キャッシュを破壊しないようコピー

        # 前日（D-1）の日次集計
        prev_date1 = (d - timedelta(days=horizon+1)).strftime("%Y-%m-%d")
        if (wlat, wlon, prev_date1) not in wx_cache:
            wx_cache[(wlat, wlon, prev_date1)] = get_daily_wx(conn_wx, wlat, wlon, prev_date1)
        dagg1 = wx_cache[(wlat, wlon, prev_date1)] or {}
        wx["precip_sum1"]      = dagg1.get("precip_sum")       # 前日合計降水量
        wx["pressure_min1"]    = dagg1.get("pressure_min")     # 前日最低気圧

        # 前々日（D-2）の日次集計
        prev_date2 = (d - timedelta(days=horizon+2)).strftime("%Y-%m-%d")
        if (wlat, wlon, prev_date2) not in wx_cache:
            wx_cache[(wlat, wlon, prev_date2)] = get_daily_wx(conn_wx, wlat, wlon, prev_date2)
        dagg2 = wx_cache[(wlat, wlon, prev_date2)] or {}
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
        # bisect で pred_date_str 未満の最新レコードを O(log n) で取得
        idx = bisect.bisect_left(_ref_dates, pred_date_str) - 1
        prev_cnt = None
        while idx >= 0:
            if _ref_records[idx].get("cnt_avg") is not None:
                prev_cnt = _ref_records[idx]["cnt_avg"]
                break
            idx -= 1
        wx["prev_week_cnt"] = prev_cnt

        # 台風（wx_date = D-H の台風接近距離）
        if wx_date not in typhoon_cache:
            typhoon_cache[wx_date] = get_typhoon(conn_typhoon, wx_date)

        rec = dict(r)
        rec.update(wx)
        rec.update(tide)
        rec.update(typhoon_cache[wx_date])
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

def _period_key(date_str, period):
    """日付文字列 → 集計キー（week/decade/month）"""
    d = datetime.strptime(date_str, "%Y/%m/%d")
    if period == "week":
        iso = d.isocalendar()
        return f"{iso[0]}-W{iso[1]:02d}"
    elif period == "decade":
        decade = min((d.day - 1) // 10, 2)  # 0=上旬, 1=中旬, 2=下旬
        return f"{d.year}-{d.month:02d}-D{decade}"
    elif period == "month":
        return f"{d.year}-{d.month:02d}"


def aggregate_by_period(enriched_recs, period):
    """enriched records を週/旬/月単位で集計（数値フィールドの平均）"""
    buckets = defaultdict(list)
    for r in enriched_recs:
        buckets[_period_key(r["date"], period)].append(r)

    num_keys = {k for r in enriched_recs for k, v in r.items() if isinstance(v, (int, float))}

    result = []
    for key in sorted(buckets.keys()):
        recs = buckets[key]
        agg = {"date": key, "_n": len(recs)}
        for k in num_keys:
            vals = [r[k] for r in recs if r.get(k) is not None]
            agg[k] = sum(vals) / len(vals) if vals else None
        result.append(agg)
    return result


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
            if abs(rv) >= 0.15 and pv < 0.10:
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
            hits = [r for r in records if kw in r.get("text_all","")]
            miss = [r for r in records if kw not in r.get("text_all","")]
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

def section_obs_corr(records):
    """観測因子（obs_fields.json role=obs_factor）の相関分析。
    予報不可だが釣果パターン把握に使う。フィールド定義は normalize/obs_fields.json を参照。
    """
    obs_factors = _get_obs_factors()
    targets = ["cnt_avg", "cnt_max", "size_avg", "kg_avg"]
    lines   = []
    fill_rates = {}
    for fac in obs_factors:
        vals = [r.get(fac) for r in records]
        n_filled = sum(1 for v in vals if v is not None)
        fill_rates[fac] = n_filled / len(records) * 100 if records else 0
    lines.append(f"  {'因子':<16} {'fill%':>5}  cnt_avg     cnt_max     size_avg    kg_avg")
    lines.append("  " + "-"*75)
    any_result = False
    for fac in obs_factors:
        fill = fill_rates[fac]
        if fill < 1.0:
            lines.append(f"  {fac:<16} {fill:>4.1f}%  (データ不足・スキップ)")
            continue
        row_parts = [f"  {fac:<16} {fill:>4.1f}%"]
        has_sig = False
        for tgt in targets:
            xs = [r.get(fac) for r in records]
            ys = [r.get(tgt) for r in records]
            r_val, p_val, nn = pearson(xs, ys)
            if r_val is None:
                row_parts.append(f"  {'—':>10}")
            else:
                star = "**" if (p_val is not None and p_val < 0.05) else ("*" if (p_val is not None and p_val < 0.10) else "  ")
                row_parts.append(f"  {r_val:+.3f}{star}(n={nn})")
                if p_val is not None and p_val < 0.10:
                    has_sig = True
        if has_sig:
            any_result = True
        lines.append("".join(row_parts))
    if not any_result:
        lines.append("  (有意な観測因子相関なし)")
    return lines

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

def _season_of(month):
    """月 → 季節（春/夏/秋/冬）"""
    if month in (3, 4, 5):  return "春"
    if month in (6, 7, 8):  return "夏"
    if month in (9, 10, 11): return "秋"
    return "冬"

def _percentile(vals, p):
    """vals（ソート済み想定なし）の p パーセンタイルを返す。線形補間なし。"""
    sv = sorted(v for v in vals if v is not None)
    if not sv:
        return None
    idx = int(len(sv) * p / 100)
    return sv[min(idx, len(sv)-1)]

def _season_thresholds(records, metric):
    """records から季節別 (p33, p67) を計算。5件未満の季節は overall で補完。"""
    by_season = {"春": [], "夏": [], "秋": [], "冬": []}
    for r in records:
        v = r.get(metric)
        m = int(r["date"][5:7])
        if v is not None:
            by_season[_season_of(m)].append(v)
    overall = [v for vs in by_season.values() for v in vs]
    ov_p33 = _percentile(overall, 33)
    ov_p67 = _percentile(overall, 67)
    result = {}
    for s, vals in by_season.items():
        if len(vals) >= 5:
            result[s] = (_percentile(vals, 33), _percentile(vals, 67))
        else:
            result[s] = (ov_p33, ov_p67)
    return result  # {season: (p33, p67)}

def _classify3(val, p33, p67):
    """val を (p33, p67) で 0=釣れない / 1=普通 / 2=釣れる に分類"""
    if val is None or p33 is None or p67 is None:
        return None
    if val >= p67: return 2
    if val >= p33: return 1
    return 0

def _prf1_multi(y_true, y_pred, target_cls):
    """target_cls を陽性として Precision / Recall / F1 を計算"""
    tp = fp = fn = 0
    for t, p in zip(y_true, y_pred):
        if t is None or p is None:
            continue
        if p == target_cls:
            if t == target_cls: tp += 1
            else:               fp += 1
        elif t == target_cls:   fn += 1
    prec = tp / (tp + fp) if (tp + fp) > 0 else None
    rec  = tp / (tp + fn) if (tp + fn) > 0 else None
    f1   = 2*prec*rec / (prec+rec) if (prec and rec) else None
    return prec, rec, f1

def _mape(preds, acts):
    pairs = [(p, a) for p, a in zip(preds, acts) if a and a > 0]
    if not pairs:
        return None
    return sum(abs(p-a)/a for p, a in pairs) / len(pairs) * 100

def _smape(preds, acts):
    """対称MAPE: 分母に予測値も混ぜる → ゼロ実績での爆発を抑制。上限200%"""
    pairs = [(p, a) for p, a in zip(preds, acts)
             if a is not None and p is not None and (p + a) > 0]
    if not pairs:
        return None
    return sum(abs(p-a) / ((p+a) / 2) for p, a in pairs) / len(pairs) * 100

def _wmape(preds, acts):
    """重み付きMAPE: 合計誤差 ÷ 合計実績 → 釣れた日の誤差を重視"""
    pairs = [(p, a) for p, a in zip(preds, acts) if a is not None and a > 0]
    if not pairs:
        return None
    total_act = sum(a for _, a in pairs)
    return sum(abs(p-a) for p, a in pairs) / total_act * 100 if total_act else None

def _rmse(preds, acts):
    """RMSE: 大外し事故の検出指標（外れ値に敏感）"""
    pairs = [(p, a) for p, a in zip(preds, acts) if a is not None and p is not None]
    if not pairs:
        return None
    return math.sqrt(sum((p - a) ** 2 for p, a in pairs) / len(pairs))

def _good_bad_acc(preds, acts, threshold):
    """良日（actual≥threshold）と不漁日（actual<threshold）の的中率を返す。
    良日的中率: 実際に良い日に予測も良日判定できた割合
    不漁的中率: 実際に悪い日に予測も不漁判定できた割合
    """
    if threshold is None or not preds:
        return None, None
    good_c = good_t = bad_c = bad_t = 0
    for p, a in zip(preds, acts):
        if a is None:
            continue
        if a >= threshold:
            good_t += 1
            if p >= threshold:
                good_c += 1
        else:
            bad_t += 1
            if p < threshold:
                bad_c += 1
    return (good_c / good_t if good_t else None,
            bad_c  / bad_t  if bad_t  else None)

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

def section_backtest_rolling(records, ship_coords, wx_coords, conn_wx, ship_area, decadal, conn_tide=None, conn_typhoon=None):
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
        return ["  データ不足（ローリングCV最低月数に達しない）"], [], {}

    # 全ホライズン分を一括 enrich（SQL クエリを事前に全発行してキャッシュ活用）
    all_en_by_H = {}
    for H in HORIZONS:
        all_en_by_H[H] = enrich(
            records, ship_coords, wx_coords, conn_wx, ship_area,
            horizon=H, all_records=records, conn_tide=conn_tide, conn_typhoon=conn_typhoon
        )

    METRICS_LIST = ["cnt_avg", "cnt_min", "cnt_max", "size_avg"]
    # 各月・各ホライズンの予測と実測を蓄積
    all_preds    = {met: {H: [] for H in HORIZONS} for met in METRICS_LIST}
    all_acts     = {met: {H: [] for H in HORIZONS} for met in METRICS_LIST}
    # 3分類ラベル（季節別閾値で分類）
    all_cls_pred = {met: {H: [] for H in HORIZONS} for met in METRICS_LIST}
    all_cls_true = {met: {H: [] for H in HORIZONS} for met in METRICS_LIST}
    # 季節別閾値（学習データから fold ごとに更新）
    season_thr   = {met: {} for met in METRICS_LIST}  # {met: {season: (p33,p67)}}
    # ── ベースライン予測蓄積 ───────────────────────────────────────────────────
    # BL-0: 学習データ全体平均（combo全体のナイーブ予測）
    # BL-1: 旬別平均（現モデルのbase部分のみ）
    # BL-2: H日前時点の直近最大7件平均（短期自己相関ベースライン）
    bl0_preds = {met: {H: [] for H in HORIZONS} for met in METRICS_LIST}
    bl0_acts  = {met: {H: [] for H in HORIZONS} for met in METRICS_LIST}
    bl1_preds = {met: {H: [] for H in HORIZONS} for met in METRICS_LIST}
    bl1_acts  = {met: {H: [] for H in HORIZONS} for met in METRICS_LIST}
    bl2_preds = {met: {H: [] for H in HORIZONS} for met in METRICS_LIST}
    bl2_acts  = {met: {H: [] for H in HORIZONS} for met in METRICS_LIST}

    for test_month in months:
        train_en_h0 = [r for r in all_en_by_H[0] if r["date"][:7] < test_month]
        if len(train_en_h0) < MIN_TRAIN_N:
            continue

        # 季節別分類閾値（学習データのみから計算 → テストデータを汚染しない）
        for met in METRICS_LIST:
            season_thr[met] = _season_thresholds(train_en_h0, met)

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

        # train_sorted_m の日付リスト（bisect用）
        train_dates_m = [r["date"] for r in train_sorted_m]

        for met in METRICS_LIST:
            tr_ys = [r.get(met) for r in train_en_h0]
            factor_r_m = {}
            for fac in ALL_FACTORS:
                xs = [r.get(fac) for r in train_en_h0]
                rv, _, _ = pearson(xs, tr_ys)
                if rv is not None and abs(rv) >= 0.10:
                    factor_r_m[fac] = rv
            if not factor_r_m:
                continue

            met_vals = [r.get(met) for r in train_en_h0 if r.get(met) is not None]
            met_mean_m, met_std_m = mean_std(met_vals)
            if met_mean_m is None or not met_std_m:
                continue

            m_dec = metric_decadal_m.get(met, {})

            # ⑦ 自己相関 r_own（前回値 → 当回値）を学習データから計算
            own_pairs = [(train_sorted_m[i-1].get(met), train_sorted_m[i].get(met))
                         for i in range(1, len(train_sorted_m))]
            own_pairs = [(x, y) for x, y in own_pairs if x is not None and y is not None]
            r_own_m, _, _ = pearson([x for x, y in own_pairs], [y for x, y in own_pairs])
            r_own_m = r_own_m if r_own_m is not None else 0.0

            for H in HORIZONS:
                te_en_h = [r for r in all_en_by_H[H] if r["date"][:7] == test_month]
                usable  = {fac: rv for fac, rv in factor_r_m.items()
                           if fac in SLOW_FACTORS or H <= FAST_MAX_H}
                w_h = sum(abs(rv) for rv in usable.values()) or 1.0

                for r in te_en_h:
                    act = r.get(met)
                    if act is None:
                        continue

                    dn = r.get("decade")
                    if met == "cnt_avg" and decadal and dn in decadal:
                        base = decadal[dn].get("avg_cnt", met_mean_m)
                    else:
                        base = m_dec.get(dn, met_mean_m)

                    # ⑤ 予測式: rv * z（線形加重和）に修正
                    num_wx = 0.0
                    for fac, rv in usable.items():
                        val = r.get(fac)
                        if val is None or fac not in hist_params_m:
                            continue
                        fm, fs = hist_params_m[fac]
                        z = (val - fm) / fs
                        num_wx += rv * z

                    # ⑦ 自己相関項を追加（H日前の時点で知っている最新値）
                    d_obj   = datetime.strptime(r["date"], "%Y/%m/%d")
                    cutoff  = (d_obj - timedelta(days=H)).strftime("%Y/%m/%d")
                    idx     = bisect.bisect_left(train_dates_m, cutoff) - 1
                    last_own_val = None
                    while idx >= 0:
                        if train_sorted_m[idx].get(met) is not None:
                            last_own_val = train_sorted_m[idx].get(met)
                            break
                        idx -= 1

                    if last_own_val is not None and abs(r_own_m) >= 0.10:
                        own_z   = (last_own_val - met_mean_m) / met_std_m
                        num_own = r_own_m * own_z
                        w_total = w_h + abs(r_own_m)
                        pred = base + ((num_wx + num_own) / w_total) * met_std_m * 0.5
                    else:
                        pred = base + (num_wx / w_h) * met_std_m * 0.5

                    all_preds[met][H].append(pred)
                    all_acts[met][H].append(act)
                    # 3分類ラベル（季節別閾値）
                    s = _season_of(int(r["date"][5:7]))
                    p33, p67 = season_thr[met].get(s, (None, None))
                    all_cls_true[met][H].append(_classify3(act,  p33, p67))
                    all_cls_pred[met][H].append(_classify3(pred, p33, p67))
                    # ── ベースライン予測 ────────────────────────────────────────
                    # BL-0: 学習データ全体平均
                    bl0_preds[met][H].append(met_mean_m)
                    bl0_acts[met][H].append(act)
                    # BL-1: 旬別平均
                    bl1_preds[met][H].append(m_dec.get(dn, met_mean_m))
                    bl1_acts[met][H].append(act)
                    # BL-2: H日前時点の直近最大7件平均
                    _bl2_idx = bisect.bisect_left(train_dates_m, cutoff) - 1
                    _bl2_recent = []
                    _bi = _bl2_idx
                    while _bi >= 0 and len(_bl2_recent) < 7:
                        v = train_sorted_m[_bi].get(met)
                        if v is not None:
                            _bl2_recent.append(v)
                        _bi -= 1
                    _bl2_p = sum(_bl2_recent) / len(_bl2_recent) if _bl2_recent else met_mean_m
                    bl2_preds[met][H].append(_bl2_p)
                    bl2_acts[met][H].append(act)

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
        # 良日閾値: met の全実績値の中央値（学習・テスト合算 - 評価目的のみ）
        all_act_vals = sorted(
            a for a in all_acts[met].get(0, []) if a is not None
        )
        threshold = all_act_vals[len(all_act_vals) // 2] if all_act_vals else None

        for H in HORIZONS:
            ps = all_preds[met][H]; acs = all_acts[met][H]
            if len(acs) < 3:
                continue
            rv, _, n = pearson(ps, acs)
            if rv is None:
                continue
            mae_v         = sum(abs(p-a) for p,a in zip(ps,acs)) / len(ps)
            mape_v        = _mape(ps, acs)
            smape_v       = _smape(ps, acs)
            wmape_v       = _wmape(ps, acs)
            rmse_v        = _rmse(ps, acs)
            dacc_v        = _dir_acc(ps, acs)
            good_r, bad_r = _good_bad_acc(ps, acs, threshold)
            # 3分類 Precision/Recall/F1
            ct = all_cls_true[met][H]
            cp = all_cls_pred[met][H]
            _, good_rec2, good_f1 = _prf1_multi(ct, cp, 2)   # 釣れる
            good_prec2, _, _      = _prf1_multi(ct, cp, 2)
            bad_prec,  bad_rec, bad_f1 = _prf1_multi(ct, cp, 0)  # 釣れない
            n_valid = sum(1 for t in ct if t is not None)
            acc3 = sum(1 for t, p in zip(ct, cp)
                       if t is not None and p is not None and t == p) / n_valid if n_valid else None
            n_f    = sum(1 for fac in ALL_FACTORS
                         if fac in SLOW_FACTORS or H <= FAST_MAX_H)
            # ベースラインメトリクス（各H・各metで計算）
            def _bl_metrics(bps, bas):
                if not bps:
                    return None, None, None
                bm = sum(abs(p-a) for p,a in zip(bps,bas)) / len(bps)
                bw = _wmape(bps, bas)
                br = _rmse(bps, bas)
                return bw, bm, br
            bl0w, bl0m, bl0r = _bl_metrics(bl0_preds[met][H], bl0_acts[met][H])
            bl1w, bl1m, bl1r = _bl_metrics(bl1_preds[met][H], bl1_acts[met][H])
            bl2w, bl2m, bl2r = _bl_metrics(bl2_preds[met][H], bl2_acts[met][H])
            rows.append((H, rv, mae_v, mape_v, smape_v, wmape_v, rmse_v,
                         dacc_v, good_r, bad_r,
                         good_prec2, good_rec2, good_f1,
                         bad_prec, bad_rec, bad_f1, acc3, n, n_f,
                         bl0w, bl0m, bl0r, bl1w, bl1m, bl1r, bl2w, bl2m, bl2r))

        if not rows:
            lines.append(f"\n  ─ {label} : データ不足 ─")
            continue

        thr_s = f"{threshold:.1f}{unit}" if threshold is not None else "-"
        lines.append(f"\n  ─ {label} ─  良日閾値:{thr_s}（季節別P33/P67を使用）")
        lines.append(
            f"  {'ホライズン':>10}  {'r':>7}  {'MAE':>7}  {'RMSE':>7}  "
            f"{'wMAPE':>7}  {'sMAPE':>7}  "
            f"{'釣良F1':>7}  {'釣良Prec':>8}  {'釣良Rec':>7}  "
            f"{'不漁F1':>7}  {'3分類Acc':>8}  {'n':>4}"
        )
        lines.append("  " + "-"*108)
        for H, rv, mae, mape, smape, wmape, rmse, dacc, good_r, bad_r, \
                gprec, grec, gf1, bprec, brec, bf1, acc3, n, n_f, \
                bl0w, bl0m, bl0r, bl1w, bl1m, bl1r, bl2w, bl2m, bl2r in rows:
            lh   = "H=  0(実測)" if H == 0 else f"H={H:>3}d 前"
            star = "**" if rv >= 0.4 else ("*" if rv >= 0.2 else " ")
            rs   = f"{rmse:>6.1f}"   if rmse  is not None else "     -"
            ws   = f"{wmape:>6.1f}%" if wmape is not None else "     -"
            ss   = f"{smape:>6.1f}%" if smape is not None else "     -"
            gf   = f"{gf1:>6.1%}"   if gf1   is not None else "     -"
            gp   = f"{gprec:>7.1%}" if gprec  is not None else "      -"
            gr   = f"{grec:>6.1%}"  if grec   is not None else "     -"
            bf   = f"{bf1:>6.1%}"   if bf1    is not None else "     -"
            ac   = f"{acc3:>7.1%}"  if acc3   is not None else "      -"
            fn   = f"({n_f}/{len(ALL_FACTORS)}因子)" if n_f < len(ALL_FACTORS) else ""
            lines.append(
                f"  {lh:>12}  {rv:>+6.3f}{star}  {mae:>6.1f}{unit}  {rs}  "
                f"{ws}  {ss}  {gf}  {gp}  {gr}  {bf}  {ac}  {n:>4}  {fn}"
            )
            bt_data.append((met, H, rv, mae, mape, smape, wmape, rmse, dacc,
                            good_r, bad_r, gprec, grec, gf1,
                            bprec, brec, bf1, acc3, n, 0.0,
                            bl0w, bl0m, bl0r, bl1w, bl1m, bl1r, bl2w, bl2m, bl2r))
        # ── ベースライン比較サマリー（H=1d, H=7d）──────────────────────────
        bl_rows = {row[0]: row for row in rows}  # H → row
        lines.append(f"\n  【ベースライン比較】  wMAPE / MAE / RMSE")
        lines.append(f"  {'':>14}  {'wMAPE':>7}  {'MAE':>7}  {'RMSE':>7}   H=1d | H=7d")
        lines.append("  " + "-"*60)
        for h_label, H in [("H=1d 前", 1), ("H=7d 前", 7)]:
            row = bl_rows.get(H)
            if row is None:
                continue
            _, rv, mae, mape, smape, wmape, rmse, dacc, *_, bl0w, bl0m, bl0r, bl1w, bl1m, bl1r, bl2w, bl2m, bl2r = row
            def _fmt3(w, m, r):
                ws = f"{w:.1f}%" if w is not None else "-"
                ms = f"{m:.1f}" if m is not None else "-"
                rs = f"{r:.1f}" if r is not None else "-"
                return f"{ws:>7}  {ms:>7}  {rs:>7}"
            lines.append(f"  {'モデル':>14}  {_fmt3(wmape, mae, rmse)}   ({h_label})")
            lines.append(f"  {'BL-0 全体平均':>14}  {_fmt3(bl0w, bl0m, bl0r)}")
            lines.append(f"  {'BL-1 旬別平均':>14}  {_fmt3(bl1w, bl1m, bl1r)}")
            lines.append(f"  {'BL-2 直近7件':>14}  {_fmt3(bl2w, bl2m, bl2r)}")
            lines.append("  " + "-"*60)

    return lines, bt_data, season_thr


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
            smape       REAL,
            wmape       REAL,
            dir_acc     REAL,
            good_recall REAL,
            bad_recall  REAL,
            n           INTEGER,
            r_own       REAL,
            updated_at  TEXT,
            PRIMARY KEY (fish, ship, metric, horizon)
        )
    """)
    # 既存テーブルへの列追加（マイグレーション）
    existing = {r[1] for r in conn.execute("PRAGMA table_info(combo_backtest)").fetchall()}
    for col, typ in [
        ("smape","REAL"), ("wmape","REAL"),
        ("good_recall","REAL"), ("bad_recall","REAL"),
        ("good_prec","REAL"), ("good_rec","REAL"), ("good_f1","REAL"),
        ("bad_prec","REAL"),  ("bad_rec","REAL"),  ("bad_f1","REAL"),
        ("acc3","REAL"),
        ("rmse","REAL"),
        ("bl0_wmape","REAL"), ("bl0_mae","REAL"), ("bl0_rmse","REAL"),
        ("bl1_wmape","REAL"), ("bl1_mae","REAL"), ("bl1_rmse","REAL"),
        ("bl2_wmape","REAL"), ("bl2_mae","REAL"), ("bl2_rmse","REAL"),
    ]:
        if col not in existing:
            conn.execute(f"ALTER TABLE combo_backtest ADD COLUMN {col} {typ}")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rows = [
        (fish, ship, metric, H, rv, mae, mape, smape, wmape, dacc,
         good_r, bad_r, gprec, grec, gf1, bprec, brec, bf1, acc3, n, r_own, now,
         rmse, bl0w, bl0m, bl0r, bl1w, bl1m, bl1r, bl2w, bl2m, bl2r)
        for metric, H, rv, mae, mape, smape, wmape, rmse, dacc,
            good_r, bad_r, gprec, grec, gf1, bprec, brec, bf1, acc3, n, r_own,
            bl0w, bl0m, bl0r, bl1w, bl1m, bl1r, bl2w, bl2m, bl2r in bt_data
    ]
    conn.executemany("""
        INSERT OR REPLACE INTO combo_backtest
        (fish, ship, metric, horizon, r, mae, mape, smape, wmape, dir_acc,
         good_recall, bad_recall, good_prec, good_rec, good_f1,
         bad_prec, bad_rec, bad_f1, acc3, n, r_own, updated_at, rmse,
         bl0_wmape, bl0_mae, bl0_rmse,
         bl1_wmape, bl1_mae, bl1_rmse,
         bl2_wmape, bl2_mae, bl2_rmse)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, rows)
    conn.commit()
    conn.close()


def save_thresholds(fish, ship, season_thr_final):
    """季節別分類閾値を combo_thresholds テーブルに保存"""
    if not season_thr_final:
        return
    conn = sqlite3.connect(DB_ANA)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS combo_thresholds (
            fish    TEXT,
            ship    TEXT,
            metric  TEXT,
            season  TEXT,
            p33     REAL,
            p67     REAL,
            updated_at TEXT,
            PRIMARY KEY (fish, ship, metric, season)
        )
    """)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rows = []
    for met, sthr in season_thr_final.items():
        for season, (p33, p67) in sthr.items():
            if p33 is not None and p67 is not None:
                rows.append((fish, ship, met, season, p33, p67, now))
    conn.executemany(
        "INSERT OR REPLACE INTO combo_thresholds VALUES (?,?,?,?,?,?,?)", rows
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

    conn_wx      = sqlite3.connect(DB_WX)      if (os.path.exists(DB_WX)      and os.path.getsize(DB_WX)      > 0) else None
    conn_tide    = sqlite3.connect(DB_TIDE)    if (os.path.exists(DB_TIDE)    and os.path.getsize(DB_TIDE)    > 0) else None
    conn_typhoon = sqlite3.connect(DB_TYPHOON) if (os.path.exists(DB_TYPHOON) and os.path.getsize(DB_TYPHOON) > 0) else None
    en0     = enrich(records, ship_coords, wx_coords, conn_wx, ship_area, horizon=0, all_records=records, conn_tide=conn_tide, conn_typhoon=conn_typhoon)
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

    out.append(f"\n【因子相関（日次: {len(en0)}件）】")
    corr_lines, corr_results = section_corr(en0)
    out += corr_lines

    for period, label in [("week", "週"), ("decade", "旬"), ("month", "月")]:
        agg = aggregate_by_period(en0, period)
        out.append(f"\n【因子相関（{label}集計: n={len(agg)}{label}）】")
        agg_lines, _ = section_corr(agg)
        out += agg_lines

    out.append("\n【観測因子相関（予報不可・パターン把握用）】")
    out += section_obs_corr(records)

    out.append("\n【コメントキーワード解析】")
    kw_lines, kw_data = section_keywords(records)
    out += kw_lines

    out.append("\n【ポイント別集計】")
    out += section_points(records)

    out.append("\n【マルチホライズン バックテスト（ローリング月次CV）】")
    bt_lines, bt_data, season_thr_final = section_backtest_rolling(records, ship_coords, wx_coords, conn_wx, ship_area, decadal, conn_tide=conn_tide, conn_typhoon=conn_typhoon)
    out += bt_lines

    if conn_wx is not None:
        conn_wx.close()
    if conn_tide is not None:
        conn_tide.close()
    if conn_typhoon is not None:
        conn_typhoon.close()

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
    save_thresholds(fish, ship, season_thr_final)


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
