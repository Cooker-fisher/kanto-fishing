#!/usr/bin/env python3
"""
water_color_model.py — 降水ラグ＋風＋潮流＋水深から水色スコアを予測するモデル

[目的]
  実測水色が取れない日・ポイントでも水色状態を推定する。
  「すべての日×すべてのポイントで濁り/澄みを把握できる」を目指す。

[モデル詳細]
  特徴量:
    - precip_sum1〜7      : 降水ラグ1〜7日（主因: 雨後の濁りラグ）
    - precip_cumW7        : 7日間加重累積降水量（ラグ重みを最適化）
    - days_since_rain     : 直近の有意降水（>2mm/日）からの経過日数
    - wind_speed_avg/max  : 当日平均・最大風速（底荒れ）
    - wave_height_avg     : 波高（巻き上げ）
    - current_speed_avg   : 潮流速度（撹拌 or 換水）
    - depth_bin_n         : 水深区分 (0=浅/1=中/2=深)
    - dist_shore          : 沿岸距離プロキシ
    - month_sin/cos       : 季節性

  目的変数: water_color_n（-2〜+1スコア）

[深掘り分析]
  1. 水深グループ別（<15m / 15-30m / 30m+）降水ラグ最適日
  2. 雨後の濁り継続日数モデル（澄→濁: 4.2日, 濁→澄: 3.7日 を検証）
  3. 風・波・潮流の水色への寄与分析
  4. 水深グループ別の独立モデル（per-depth regression）
  5. 全ポイント×全日付の水色予測 → water_color_daily テーブル

[バックテスト]
  leave-one-month-out CV（combo_deep_dive.py と同方式）
  評価: RMSE, MAE, 符号一致率(澄/濁の正解率)

[使い方]
  python analysis/V2/methods/water_color_model.py           # 分析のみ
  python analysis/V2/methods/water_color_model.py --predict # 全点×全日予測も実行
  python analysis/V2/methods/water_color_model.py --predict --start 2023-01-01 --end 2026-12-31
"""

import argparse, csv, json, math, os, sqlite3, sys
from collections import defaultdict
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _paths import ROOT_DIR, RESULTS_DIR, DATA_DIR, NORMALIZE_DIR, OCEAN_DIR

DB_WX   = os.path.join(OCEAN_DIR, "weather_cache.sqlite")
DB_TIDE = os.path.join(OCEAN_DIR, "tide_moon.sqlite")
DB_ANA  = os.path.join(RESULTS_DIR, "analysis.sqlite")

# ─── 定数 ────────────────────────────────────────────────────────────────────
PRECIP_LAGS = [1, 2, 3, 4, 5, 6, 7]

# 水深区分
DEPTH_BINS  = [15.0, 30.0]   # shallow < 15 <= mid < 30 <= deep

# 有意降水閾値（mm/day）: これ以上の日を「雨の日」とする
RAIN_THR = 2.0

# 東京湾中心（沿岸距離プロキシ用）
BAY_CENTER = (35.5, 139.9)

CUTOFF = "2023/01/01"

# 河口座標（weather_cache 最近傍格子点を直接使用）
RIVER_MOUTHS = {
    "tone":   (35.71, 140.87),  # 利根川（銚子）
    "sagami": (35.30, 139.32),  # 相模川
    "tama":   (35.55, 139.76),  # 多摩川
}
RIVER_PROXIMITY_SCALE = 0.4   # 指数減衰スケール（度数）≈ 40km at 35°N

# 主要岬座標（潮流衝突による地形起因の濁り）
# 岬先端 = 異方向の潮流が衝突 → 上昇流で底質攪拌 → 構造的濁り（降水と無関係）
CAPES = {
    "inubozaki":  (35.71, 140.87),  # 犬吠埼（銚子）
    "nojimakzaki":(34.90, 139.87),  # 野島崎（館山）
    "irouzaki":   (34.60, 138.83),  # 石廊崎（南伊豆）
    "omaezaki":   (34.60, 138.21),  # 御前崎（静岡）
}
CAPE_PROXIMITY_SCALE = 0.5   # 指数減衰スケール（度数）≈ 50km at 35°N

# 空間ラグ: この半径（度）以内の近傍ポイントの水色を平均する
SPATIAL_LAG_RADIUS = 0.3   # ≈ 30km

# ─── ユーティリティ ────────────────────────────────────────────────────────────
def _float(v):
    try:
        return float(v) if v not in (None, "", "None") else None
    except Exception:
        return None

def _dist_from_bay_center(lat, lon):
    if lat is None or lon is None:
        return None
    return ((lat - BAY_CENTER[0])**2 + (lon - BAY_CENTER[1])**2) ** 0.5

def _river_proximity(fishing_lat, fishing_lon, river_lat, river_lon,
                     scale_deg=RIVER_PROXIMITY_SCALE):
    """河口からの指数減衰プロキシ (0〜1)。scale_deg ≈ 40km at 35°N。"""
    dist = ((fishing_lat - river_lat)**2 + (fishing_lon - river_lon)**2) ** 0.5
    return math.exp(-dist / scale_deg)

def _cape_proximity(lat, lon):
    """主要岬への最近傍指数減衰スコア (0〜1)。岬に近いほど高スコア。
    岬先端 = 潮流衝突による上昇流 → 底質攪拌 → 栄養塩豊富な「良い濁り」の代理変数。
    """
    if lat is None or lon is None:
        return 0.0
    return max(
        math.exp(-((lat - clat)**2 + (lon - clon)**2)**0.5 / CAPE_PROXIMITY_SCALE)
        for clat, clon in CAPES.values()
    )

def _build_neighbor_map(wx_coords):
    """各座標の近傍座標リスト（SPATIAL_LAG_RADIUS 以内）を事前計算。O(n²)だがn=153なので即時。"""
    neighbors = {}
    for lat, lon in wx_coords:
        nbrs = [
            (nlat, nlon) for nlat, nlon in wx_coords
            if (nlat, nlon) != (lat, lon)
            and ((lat - nlat)**2 + (lon - nlon)**2)**0.5 <= SPATIAL_LAG_RADIUS
        ]
        neighbors[(lat, lon)] = nbrs
    return neighbors

# 近傍マップキャッシュ
_NEIGHBOR_MAP: dict = {}

def _lookup_wc_spatial_lag(lat, lon, date_iso):
    """近傍ポイントの前日 wc_pred 平均（空間的慣性）。
    近い海域が同じ水色状態を共有するパターンを捉える。
    """
    _load_wc_daily()
    if not _WC_DAILY_CACHE or (lat, lon) not in _NEIGHBOR_MAP:
        return None
    prev_date = (datetime.strptime(date_iso, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
    vals = [
        _WC_DAILY_CACHE[(round(nlat, 2), round(nlon, 2), prev_date)]
        for nlat, nlon in _NEIGHBOR_MAP[(lat, lon)]
        if (round(nlat, 2), round(nlon, 2), prev_date) in _WC_DAILY_CACHE
    ]
    return sum(vals) / len(vals) if vals else None

def _build_river_features(conn_wx, fishing_lat, fishing_lon, date_iso):
    """3河口の降水量×距離減衰の特徴量。build_precip_features の _precip_cache を共有。
    Returns: {"tone_impact": float, "sagami_impact": float, "tama_impact": float}
    """
    result = {}
    for river_name, (rlat, rlon) in RIVER_MOUTHS.items():
        rpf  = build_precip_features(conn_wx, rlat, rlon, date_iso)
        prox = _river_proximity(fishing_lat, fishing_lon, rlat, rlon)
        result[f"{river_name}_impact"] = prox * rpf.get("precip_cumW7", 0.0)
    return result

def _depth_group(depth_avg):
    if depth_avg is None:
        return "unknown"
    if depth_avg < DEPTH_BINS[0]:
        return "shallow"
    elif depth_avg < DEPTH_BINS[1]:
        return "mid"
    return "deep"

def _depth_bin_n(depth_avg):
    """水深区分を数値化: shallow=0, mid=1, deep=2, unknown=1（中間扱い）"""
    g = _depth_group(depth_avg)
    return {"shallow": 0, "mid": 1, "deep": 2}.get(g, 1)

def _nearest_wx_coord(lat, lon, wx_coords):
    best, best_d = None, 9999.0
    for (wlat, wlon) in wx_coords:
        d = (lat - wlat)**2 + (lon - wlon)**2
        if d < best_d:
            best_d = d
            best = (wlat, wlon)
    return best

def _mean(xs):
    return sum(xs) / len(xs) if xs else 0.0

def _pearson(xs, ys):
    n = len(xs)
    if n < 5: return 0.0
    mx, my = _mean(xs), _mean(ys)
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sx  = sum((x - mx)**2 for x in xs) ** 0.5
    sy  = sum((y - my)**2 for y in ys) ** 0.5
    return cov / (sx * sy) if sx > 1e-9 and sy > 1e-9 else 0.0

def _ols_single(xs, ys):
    n = len(xs)
    if n < 3: return 0.0, _mean(ys)
    mx, my = _mean(xs), _mean(ys)
    denom = sum((x - mx)**2 for x in xs)
    if denom < 1e-12: return 0.0, my
    a = sum((x - mx)*(y - my) for x, y in zip(xs, ys)) / denom
    return a, my - a * mx


# ─── weather_cache アクセス ───────────────────────────────────────────────────
_wx_coord_cache = None

def load_wx_coords(conn_wx):
    global _wx_coord_cache
    if _wx_coord_cache is None:
        rows = conn_wx.execute("SELECT DISTINCT lat, lon FROM weather").fetchall()
        _wx_coord_cache = [(r[0], r[1]) for r in rows]
    return _wx_coord_cache

# precip キャッシュ（{(lat,lon,date_iso): mm}）
_precip_cache = {}

def _get_precip_day(conn_wx, lat, lon, date_iso):
    k = (lat, lon, date_iso)
    if k not in _precip_cache:
        row = conn_wx.execute(
            "SELECT SUM(precipitation) FROM weather WHERE lat=? AND lon=? AND dt LIKE ?",
            (lat, lon, f"{date_iso}%")
        ).fetchone()
        _precip_cache[k] = float(row[0]) if row and row[0] is not None else 0.0
    return _precip_cache[k]

# wx day キャッシュ
_wx_day_cache = {}

def get_wx_day(conn_wx, lat, lon, date_iso):
    k = (lat, lon, date_iso)
    if k in _wx_day_cache:
        return _wx_day_cache[k]
    rows = conn_wx.execute("""
        SELECT wind_speed, wind_dir, wave_height, current_speed,
               sst, swell_height, temp, pressure
        FROM weather WHERE lat=? AND lon=? AND dt LIKE ?
    """, (lat, lon, f"{date_iso}%")).fetchall()
    res = {}
    if rows:
        ws   = [r[0] for r in rows if r[0] is not None]
        wh   = [r[2] for r in rows if r[2] is not None]
        cs   = [r[3] for r in rows if r[3] is not None]
        ssts = [r[4] for r in rows if r[4] is not None]
        sw   = [r[5] for r in rows if r[5] is not None]
        tm   = [r[6] for r in rows if r[6] is not None]
        pr   = [r[7] for r in rows if r[7] is not None]
        if ws:
            res["wind_speed_avg"] = _mean(ws)
            res["wind_speed_max"] = max(ws)
        if wh:
            res["wave_height_avg"] = _mean(wh)
        if cs:
            res["current_speed_avg"] = _mean(cs)
        if ssts:
            res["sst_avg"] = _mean(ssts)
        if sw:
            res["swell_height_avg"] = _mean(sw)
        if tm:
            res["temp_avg"] = _mean(tm)
        if pr:
            res["pressure_avg"] = _mean(pr)
    _wx_day_cache[k] = res
    return res


# ─── 潮汐・月齢キャッシュ ────────────────────────────────────────────────────
_tide_cache: dict = {}

def _load_tide_data():
    global _tide_cache
    if _tide_cache:
        return
    if not os.path.exists(DB_TIDE):
        print(f"  [WARN] tide_moon.sqlite が見つかりません: {DB_TIDE}")
        return
    conn = sqlite3.connect(DB_TIDE, timeout=10)
    rows = conn.execute("SELECT date, tide_coeff, moon_age FROM tide_moon").fetchall()
    conn.close()
    for date, tc, ma in rows:
        _tide_cache[date] = {
            "tide_coeff": float(tc) if tc is not None else None,
            "moon_age":   float(ma) if ma is not None else None,
        }
    print(f"  tide_moon キャッシュ: {len(_tide_cache)}日分", flush=True)

def get_tide_day(date_iso):
    _load_tide_data()
    return _tide_cache.get(date_iso, {})


# water_color_daily キャッシュ（AR(1)特徴量用）
# キー: (lat_r2, lon_r2, date_iso) → wc_pred
_WC_DAILY_CACHE: dict = {}
_WC_DAILY_LOADED: bool = False

def _load_wc_daily():
    """water_color_daily テーブルをメモリに一括ロード（初回のみ）。"""
    global _WC_DAILY_CACHE, _WC_DAILY_LOADED
    if _WC_DAILY_LOADED:
        return
    _WC_DAILY_LOADED = True
    if not os.path.exists(DB_ANA):
        return
    try:
        conn = sqlite3.connect(DB_ANA, timeout=30)
        rows = conn.execute(
            "SELECT lat, lon, date, wc_pred FROM water_color_daily"
        ).fetchall()
        conn.close()
        for lat, lon, date, wc_pred in rows:
            _WC_DAILY_CACHE[(round(lat, 2), round(lon, 2), date)] = wc_pred
        print(f"  water_color_daily キャッシュ: {len(_WC_DAILY_CACHE):,}件", flush=True)
    except Exception as e:
        print(f"  [WARN] water_color_daily ロード失敗: {e}")

def _lookup_wc_prev(wlat, wlon, date_iso):
    """weather_cache 格子点 (wlat, wlon) における前日の wc_pred を返す。
    水色テーブルが未生成・前日が範囲外の場合は None を返す。
    """
    _load_wc_daily()
    if not _WC_DAILY_CACHE:
        return None
    prev_date = (datetime.strptime(date_iso, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
    return _WC_DAILY_CACHE.get((round(wlat, 2), round(wlon, 2), prev_date))


def build_precip_features(conn_wx, lat, lon, date_iso):
    """降水ラグ特徴量を一括計算。
    - precip_sum1〜7: ラグN日合計
    - precip_cumW7: 7日間加重累積（ラグ5-6日に重点）
    - days_since_rain: 直近有意降水からの経過日数（最大14日）
    """
    d = datetime.strptime(date_iso, "%Y-%m-%d")
    feat = {}

    # ラグ別合計
    for lag in PRECIP_LAGS:
        ld = (d - timedelta(days=lag)).strftime("%Y-%m-%d")
        feat[f"precip_sum{lag}"] = _get_precip_day(conn_wx, lat, lon, ld)

    # 加重累積（分析で D-6 が最強 → 長ラグに重みをかける）
    # 重み: [D-1:0.5, D-2:0.7, D-3:0.8, D-4:0.9, D-5:1.0, D-6:1.0, D-7:0.8]
    lag_weights = {1: 0.5, 2: 0.7, 3: 0.8, 4: 0.9, 5: 1.0, 6: 1.0, 7: 0.8}
    feat["precip_cumW7"] = sum(
        feat.get(f"precip_sum{lag}", 0) * w for lag, w in lag_weights.items()
    )

    # 直近有意降水からの経過日数（清澄化速度の指標）
    days_since = 14  # デフォルト: 14日以上雨なし
    for lag in range(1, 15):
        ld = (d - timedelta(days=lag)).strftime("%Y-%m-%d")
        if _get_precip_day(conn_wx, lat, lon, ld) >= RAIN_THR:
            days_since = lag
            break
    feat["days_since_rain"] = days_since

    return feat


# ─── データ読み込み ─────────────────────────────────────────────────────────
def load_water_color_records():
    """水色実測がある全レコードをロード（重複集約）"""
    with open(os.path.join(NORMALIZE_DIR, "point_coords.json"), encoding="utf-8") as f:
        point_coords = json.load(f)
    with open(os.path.join(NORMALIZE_DIR, "area_coords.json"), encoding="utf-8") as f:
        area_raw = json.load(f)
    area_coords = {e["area"]: e for e in area_raw if "area" in e} if isinstance(area_raw, list) else area_raw

    with open(os.path.join(ROOT_DIR, "crawl", "ships.json"), encoding="utf-8") as f:
        ships_list = json.load(f)
    ship_area = {s["name"]: s["area"] for s in ships_list if "name" in s and "area" in s}
    exclude   = {s["name"] for s in ships_list if s.get("exclude") or s.get("boat_only")}

    with open(os.path.join(NORMALIZE_DIR, "obs_fields.json"), encoding="utf-8") as f:
        obs_cfg = json.load(f)
    wc_scores = obs_cfg["fields"]["water_color_n"]["scores"]

    def _wc_score(text):
        if not text: return None
        for kw, sc in wc_scores.items():
            if kw in text: return sc
        return None

    def _resolve_coord(row, ship):
        p1 = row.get("point_place1", "").strip()
        if p1 and p1 in point_coords:
            c = point_coords[p1]; return c.get("lat"), c.get("lon")
        area = ship_area.get(ship, row.get("area", ""))
        if area and area in area_coords:
            c = area_coords[area]; return c.get("lat"), c.get("lon")
        return None, None

    seen = {}
    for fn in sorted(os.listdir(DATA_DIR)):
        if not fn.endswith(".csv") or fn == "cancellations.csv":
            continue
        with open(os.path.join(DATA_DIR, fn), encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                if row.get("is_cancellation") == "1": continue
                ship = row.get("ship", "").strip()
                if ship in exclude: continue
                date_str = row.get("date", "").strip()
                if not date_str or date_str < CUTOFF: continue

                wc_raw = " ".join(filter(None, [
                    (row.get("water_color") or "").strip(),
                    (row.get("suishoku_raw") or "").strip(),
                ]))
                wc_n = _wc_score(wc_raw)
                if wc_n is None: continue

                lat, lon = _resolve_coord(row, ship)
                if lat is None or lon is None: continue

                d_min = _float(row.get("depth_min"))
                d_max = _float(row.get("depth_max"))
                depth_avg = ((d_min + d_max) / 2) if d_min and d_max else (d_min or d_max)

                key = (ship, date_str)
                if key in seen:
                    seen[key]["_wc_list"].append(wc_n)
                    continue
                seen[key] = {
                    "ship": ship, "area": row.get("area","").strip(),
                    "date": date_str, "month": date_str[:7],
                    "lat": lat, "lon": lon,
                    "depth_avg": depth_avg,
                    "water_color_n": wc_n,
                    "wc_raw": wc_raw,
                    "_wc_list": [wc_n],
                }

    records = list(seen.values())
    for r in records:
        wc_list = r.pop("_wc_list")
        r["water_color_n"] = sum(wc_list) / len(wc_list)
    records.sort(key=lambda r: r["date"])
    return records


# ─── 特徴量付与 ────────────────────────────────────────────────────────────────
def build_features(records, conn_wx, wx_coords):
    _load_wc_daily()   # water_color_daily を事前ロード（AR(1)用）
    global _NEIGHBOR_MAP
    if not _NEIGHBOR_MAP:
        _NEIGHBOR_MAP = _build_neighbor_map(wx_coords)
        print(f"  近傍マップ構築: {len(_NEIGHBOR_MAP)}座標", flush=True)
    enriched = []
    for i, r in enumerate(records):
        if i % 500 == 0:
            print(f"  特徴量付与 {i}/{len(records)} ...", flush=True)
        lat, lon = r["lat"], r["lon"]
        wlat, wlon = _nearest_wx_coord(lat, lon, wx_coords)
        date_iso = datetime.strptime(r["date"], "%Y/%m/%d").strftime("%Y-%m-%d")

        pf   = build_precip_features(conn_wx, wlat, wlon, date_iso)
        wxd  = get_wx_day(conn_wx, wlat, wlon, date_iso)
        riv  = _build_river_features(conn_wx, lat, lon, date_iso)
        tide = get_tide_day(date_iso)

        m = int(r["date"][5:7])
        feat = {
            **r, **pf, **wxd,
            **riv, **tide,
            "wc_prev1":         _lookup_wc_prev(wlat, wlon, date_iso),
            "wc_spatial_lag":   _lookup_wc_spatial_lag(wlat, wlon, date_iso),
            "cape_proximity_n": _cape_proximity(lat, lon),
            "dist_shore":       _dist_from_bay_center(lat, lon),
            "depth_grp":        _depth_group(r.get("depth_avg")),
            "depth_bin_n":      _depth_bin_n(r.get("depth_avg")),
            "month_n":          m,
            "month_sin":        math.sin(2 * math.pi * m / 12),
            "month_cos":        math.cos(2 * math.pi * m / 12),
        }
        enriched.append(feat)
    print(f"  特徴量付与完了: {len(enriched)}/{len(records)}件", flush=True)
    return enriched


# ─── 線形回帰（正規方程式; stdlib のみ） ──────────────────────────────────────
BASE_FEATURES = (
    [f"precip_sum{i}" for i in PRECIP_LAGS]
    + ["days_since_rain",
       "wind_speed_avg", "wave_height_avg", "swell_height_avg", "current_speed_avg",
       "sst_avg", "temp_avg", "pressure_avg",
       "tide_coeff", "moon_age",
       "depth_bin_n", "dist_shore",
       "tone_impact", "sagami_impact", "tama_impact",
       "wc_prev1", "wc_spatial_lag",
       "cape_proximity_n",
       "month_sin", "month_cos"]
)
# NOTE: precip_cumW7 を削除（河口3特徴量に置き換え）。
# precip_cumW7 ≈ tone/tama_impact / prox で多重共線性が発生するため。

def fit_ols(records, target="water_color_n", features=None):
    """多変量 OLS（正規方程式）。係数ベクトル [bias, c1, ...] と特徴量リストを返す。"""
    if features is None:
        features = BASE_FEATURES
    rows_X, rows_y = [], []
    for r in records:
        y = r.get(target)
        if y is None: continue
        row = [r.get(k) for k in features]
        if any(v is None for v in row): continue
        rows_X.append(row)
        rows_y.append(y)

    n, p = len(rows_X), len(features)
    if n < max(20, p * 3):
        return None, features

    X = [[1.0] + list(row) for row in rows_X]
    y = list(rows_y)
    p1 = p + 1

    # X^T X と X^T y
    XtX = [[sum(X[i][a] * X[i][b] for i in range(n)) for b in range(p1)] for a in range(p1)]
    Xty = [sum(X[i][a] * y[i] for i in range(n)) for a in range(p1)]

    # Gauss 消去
    mat = [XtX[i] + [Xty[i]] for i in range(p1)]
    for col in range(p1):
        pivot = max(range(col, p1), key=lambda r: abs(mat[r][col]))
        mat[col], mat[pivot] = mat[pivot], mat[col]
        if abs(mat[col][col]) < 1e-12: continue
        s = mat[col][col]
        mat[col] = [v / s for v in mat[col]]
        for row in range(p1):
            if row == col: continue
            f = mat[row][col]
            mat[row] = [mat[row][j] - f * mat[col][j] for j in range(p1 + 1)]

    coeffs = [mat[i][-1] for i in range(p1)]
    return coeffs, features


def predict_wc(coeffs, features, r):
    if coeffs is None: return None
    vals = [r.get(k) for k in features]
    if any(v is None for v in vals): return None
    return max(-2.0, min(1.5, coeffs[0] + sum(coeffs[i+1] * vals[i] for i in range(len(vals)))))


# ─── 深さ別モデル ─────────────────────────────────────────────────────────────
def fit_stratified_models(records):
    """水深グループ別に独立した OLS モデルを学習。グループ別係数を返す。"""
    # 浅場は短ラグに重点、深場は長ラグ + 波・潮流が主因
    group_features = {
        "shallow": [f"precip_sum{i}" for i in [1,2,3,4,5,6]] +
                   ["days_since_rain",
                    "wind_speed_avg", "wave_height_avg", "swell_height_avg", "current_speed_avg",
                    "sst_avg", "temp_avg", "pressure_avg",
                    "tide_coeff", "moon_age",
                    "tone_impact", "sagami_impact", "tama_impact",
                    "wc_prev1", "wc_spatial_lag", "cape_proximity_n",
                    "month_sin", "month_cos"],
        "mid":     [f"precip_sum{i}" for i in [2,3,4,5,6,7]] +
                   ["days_since_rain",
                    "wave_height_avg", "swell_height_avg", "current_speed_avg",
                    "sst_avg", "temp_avg", "pressure_avg",
                    "tide_coeff", "moon_age",
                    "tone_impact", "sagami_impact", "tama_impact",
                    "wc_prev1", "wc_spatial_lag", "cape_proximity_n",
                    "month_sin", "month_cos"],
        "deep":    [f"precip_sum{i}" for i in [4,5,6,7]] +
                   ["days_since_rain",
                    "wave_height_avg", "swell_height_avg", "current_speed_avg",
                    "sst_avg", "temp_avg", "pressure_avg",
                    "tide_coeff", "moon_age",
                    "tone_impact", "sagami_impact", "tama_impact",
                    "wc_prev1", "wc_spatial_lag", "cape_proximity_n",
                    "month_sin", "month_cos"],
        "unknown": BASE_FEATURES,
    }
    models = {}
    for grp, feats in group_features.items():
        grp_recs = [r for r in records if r.get("depth_grp") == grp]
        if len(grp_recs) < 30:
            continue
        coeffs, fkeys = fit_ols(grp_recs, features=feats)
        models[grp] = (coeffs, fkeys)
        status = "OK" if coeffs else "失敗(データ不足)"
        print(f"    {grp:8s}: n={len(grp_recs):4d} → {status}", flush=True)
    return models


def predict_wc_stratified(models, r, global_coeffs, global_features):
    """深さグループ別モデルで予測。グループモデルがなければグローバルモデルを使用。"""
    grp = r.get("depth_grp", "unknown")
    if grp in models:
        coeffs, fkeys = models[grp]
        pred = predict_wc(coeffs, fkeys, r)
        if pred is not None:
            return pred
    return predict_wc(global_coeffs, global_features, r)


# ─── バックテスト ─────────────────────────────────────────────────────────────
def backtest(records, use_stratified=True):
    """leave-one-month-out CV。グローバル / 水深別モデルを両方評価。"""
    months = sorted({r["month"] for r in records})
    if len(months) < 3:
        print("  月数不足 → バックテスト不可"); return

    results = {"global": [], "stratified": []}
    group_errs = defaultdict(list)

    for test_month in months:
        train = [r for r in records if r["month"] != test_month]
        test  = [r for r in records if r["month"] == test_month]
        if len(train) < 50 or len(test) < 5: continue

        # グローバルモデル
        g_coeffs, g_fkeys = fit_ols(train)

        # 深さ別モデル（訓練データのみで学習）
        s_models = {}
        if use_stratified:
            for grp in ["shallow", "mid", "deep", "unknown"]:
                g_tr = [r for r in train if r.get("depth_grp") == grp]
                if len(g_tr) < 30: continue
                feats = {
                    "shallow": [f"precip_sum{i}" for i in [1,2,3,4,5,6]] +
                               ["days_since_rain","wind_speed_avg",
                                "wave_height_avg","swell_height_avg","current_speed_avg",
                                "sst_avg","temp_avg","pressure_avg",
                                "tide_coeff","moon_age",
                                "tone_impact","sagami_impact","tama_impact",
                                "wc_prev1","wc_spatial_lag","cape_proximity_n",
                                "month_sin","month_cos"],
                    "mid":     [f"precip_sum{i}" for i in [2,3,4,5,6,7]] +
                               ["days_since_rain",
                                "wave_height_avg","swell_height_avg","current_speed_avg",
                                "sst_avg","temp_avg","pressure_avg",
                                "tide_coeff","moon_age",
                                "tone_impact","sagami_impact","tama_impact",
                                "wc_prev1","wc_spatial_lag","cape_proximity_n",
                                "month_sin","month_cos"],
                    "deep":    [f"precip_sum{i}" for i in [4,5,6,7]] +
                               ["days_since_rain",
                                "wave_height_avg","swell_height_avg","current_speed_avg",
                                "sst_avg","temp_avg","pressure_avg",
                                "tide_coeff","moon_age",
                                "tone_impact","sagami_impact","tama_impact",
                                "wc_prev1","wc_spatial_lag","cape_proximity_n",
                                "month_sin","month_cos"],
                }.get(grp, BASE_FEATURES)
                c, fk = fit_ols(g_tr, features=feats)
                if c: s_models[grp] = (c, fk)

        for r in test:
            actual = r.get("water_color_n")
            if actual is None: continue

            # グローバル
            pg = predict_wc(g_coeffs, g_fkeys, r)
            if pg is not None:
                results["global"].append(pg - actual)

            # 深さ別
            ps = predict_wc_stratified(s_models, r, g_coeffs, g_fkeys)
            if ps is not None:
                results["stratified"].append(ps - actual)
                group_errs[r.get("depth_grp","unknown")].append(ps - actual)

    def _stats(errs, label):
        if not errs:
            print(f"  {label}: データなし"); return
        rmse = (sum(e**2 for e in errs)/len(errs))**0.5
        mae  = sum(abs(e) for e in errs)/len(errs)
        sign = sum(1 for e in errs if abs(e) < 0.75) / len(errs) * 100  # ±0.75以内を「当たり」
        print(f"  {label}: n={len(errs)}  RMSE={rmse:.3f}  MAE={mae:.3f}  ±0.75以内={sign:.1f}%")

    print("\n=== バックテスト（leave-one-month-out CV）===")
    _stats(results["global"],     "グローバルモデル ")
    _stats(results["stratified"], "水深別モデル     ")

    print("\n  水深グループ別（水深別モデル）:")
    for grp in ["shallow", "mid", "deep", "unknown"]:
        _stats(group_errs.get(grp, []), f"    {grp:8s}")


# ─── 深掘り分析 ────────────────────────────────────────────────────────────────
def factor_correlation_analysis(records):
    print("\n=== 因子別相関（水色スコアとの Pearson r） ===")
    groups = [
        ("降水ラグ",     [f"precip_sum{i}" for i in PRECIP_LAGS] + ["precip_cumW7", "days_since_rain"]),
        ("河川影響",     ["tone_impact", "sagami_impact", "tama_impact"]),
        ("水色AR・空間", ["wc_prev1", "wc_spatial_lag"]),
        ("岬接近度",    ["cape_proximity_n"]),
        ("風・波・潮流", ["wind_speed_avg", "wind_speed_max", "wave_height_avg", "swell_height_avg", "current_speed_avg"]),
        ("海面・気象",   ["sst_avg", "temp_avg", "pressure_avg"]),
        ("潮汐・月齢",   ["tide_coeff", "moon_age"]),
        ("水深・沖合",   ["depth_avg", "depth_bin_n", "dist_shore"]),
        ("季節",         ["month_n", "month_sin", "month_cos"]),
    ]
    targets = [r.get("water_color_n") for r in records]
    for gname, keys in groups:
        print(f"\n  [{gname}]")
        for k in keys:
            xs = [r.get(k) for r in records]
            pairs = [(x,y) for x,y in zip(xs,targets) if x is not None and y is not None]
            if len(pairs) < 10:
                print(f"    {k:30s}: n={len(pairs):4d} (不足)"); continue
            r_val = _pearson([p[0] for p in pairs], [p[1] for p in pairs])
            a, b  = _ols_single([p[0] for p in pairs], [p[1] for p in pairs])
            print(f"    {k:30s}: n={len(pairs):5d}  r={r_val:+.3f}  slope={a:+.5f}")


def depth_lag_analysis(records):
    """水深別×降水ラグ最適日・遷移モデルの深掘り"""
    print("\n=== 水深グループ別 降水ラグ相関 ===")
    print(f"  {'':20s}", end="")
    for lag in PRECIP_LAGS:
        print(f"  D-{lag} ", end="")
    print("  cumW7  days_rain  wave   current")

    for grp in ["shallow", "mid", "deep", "unknown"]:
        grp_recs = [r for r in records if r.get("depth_grp") == grp]
        if len(grp_recs) < 10: continue
        targets = [r["water_color_n"] for r in grp_recs]
        n = len(grp_recs)
        print(f"  {grp:8s}(n={n:4d})   ", end="")
        for lag in PRECIP_LAGS:
            xs = [r.get(f"precip_sum{lag}") for r in grp_recs]
            pairs = [(x,y) for x,y in zip(xs,targets) if x is not None]
            rv = _pearson([p[0] for p in pairs],[p[1] for p in pairs]) if pairs else 0
            print(f"  {rv:+.2f}", end="")
        # cumW7
        xs = [r.get("precip_cumW7") for r in grp_recs]
        pairs = [(x,y) for x,y in zip(xs,targets) if x is not None]
        rv = _pearson([p[0] for p in pairs],[p[1] for p in pairs]) if pairs else 0
        print(f"  {rv:+.3f}", end="")
        # days_since_rain
        xs = [r.get("days_since_rain") for r in grp_recs]
        pairs = [(x,y) for x,y in zip(xs,targets) if x is not None]
        rv = _pearson([p[0] for p in pairs],[p[1] for p in pairs]) if pairs else 0
        print(f"  {rv:+.4f}  ", end="")
        # wave
        xs = [r.get("wave_height_avg") for r in grp_recs]
        pairs = [(x,y) for x,y in zip(xs,targets) if x is not None]
        rv = _pearson([p[0] for p in pairs],[p[1] for p in pairs]) if pairs else 0
        print(f"  {rv:+.3f}", end="")
        # current
        xs = [r.get("current_speed_avg") for r in grp_recs]
        pairs = [(x,y) for x,y in zip(xs,targets) if x is not None]
        rv = _pearson([p[0] for p in pairs],[p[1] for p in pairs]) if pairs else 0
        print(f"  {rv:+.3f}")


def transition_analysis(records):
    """澄→濁・濁→澄の遷移日数分析（同エリア連続レコードから推定）"""
    print("\n=== 水色遷移日数分析（澄↔濁） ===")

    # 船宿・日付でソート済みレコードを使い、連続する日付の水色変化を追う
    by_ship = defaultdict(list)
    for r in records:
        by_ship[r["ship"]].append(r)

    clear_to_turbid = []  # 澄み→薄濁以下になるまでの日数
    turbid_to_clear = []  # 薄濁以下→澄みになるまでの日数
    rain_to_turbid  = []  # 有意降水後→初めて濁りになるまでのラグ

    for ship, recs in by_ship.items():
        recs = sorted(recs, key=lambda r: r["date"])
        for i in range(1, len(recs)):
            r0, r1 = recs[i-1], recs[i]
            wc0 = r0.get("water_color_n")
            wc1 = r1.get("water_color_n")
            if wc0 is None or wc1 is None: continue
            try:
                d0 = datetime.strptime(r0["date"], "%Y/%m/%d")
                d1 = datetime.strptime(r1["date"], "%Y/%m/%d")
                gap = (d1 - d0).days
            except Exception:
                continue
            if gap <= 0 or gap > 14: continue  # 14日以上のギャップは除外

            # 澄み→濁り遷移
            if wc0 >= 0.5 and wc1 <= -0.5:
                clear_to_turbid.append(gap)
            # 濁り→澄み遷移
            if wc0 <= -0.5 and wc1 >= 0.5:
                turbid_to_clear.append(gap)

    def _summarize(vals, label):
        if not vals:
            print(f"  {label}: データなし"); return
        avg = _mean(vals)
        med = sorted(vals)[len(vals)//2]
        print(f"  {label}: n={len(vals)}  平均{avg:.1f}日  中央値{med:.0f}日  "
              f"[{min(vals)}〜{max(vals)}日]")

    _summarize(clear_to_turbid, "澄み→濁り遷移")
    _summarize(turbid_to_clear, "濁り→澄み遷移")

    # 降水ラグと水色変化の対応（全レコード）
    print("\n  降水後の水色劣化 days_since_rain 別 平均水色スコア:")
    by_dsr = defaultdict(list)
    for r in records:
        dsr = r.get("days_since_rain")
        wc  = r.get("water_color_n")
        if dsr is not None and wc is not None:
            by_dsr[min(dsr, 10)].append(wc)

    print(f"  {'days_since_rain':>18s}", end="")
    for d in sorted(by_dsr.keys()):
        print(f"  {d:>4d}", end="")
    print()
    print(f"  {'avg water_color_n':>18s}", end="")
    for d in sorted(by_dsr.keys()):
        avg = _mean(by_dsr[d])
        n   = len(by_dsr[d])
        print(f"  {avg:+.2f}", end="")
    print()
    print(f"  {'n':>18s}", end="")
    for d in sorted(by_dsr.keys()):
        print(f"  {len(by_dsr[d]):>4d}", end="")
    print()


# ─── 全点×全日 水色予測 ────────────────────────────────────────────────────────
def predict_all_points(conn_wx, wx_coords, global_model, stratified_models,
                       start_date=None, end_date=None):
    """全 weather_cache 座標×全日付で水色スコアを予測し analysis.sqlite に保存"""
    global_coeffs, global_fkeys = global_model
    if global_coeffs is None:
        print("  グローバルモデルなし → スキップ"); return

    conn_ana = sqlite3.connect(DB_ANA, timeout=60.0)
    conn_ana.execute("PRAGMA journal_mode=WAL")
    conn_ana.execute("""
        CREATE TABLE IF NOT EXISTS water_color_daily (
            lat      REAL,
            lon      REAL,
            date     TEXT,
            wc_pred  REAL,
            depth_grp TEXT,
            PRIMARY KEY (lat, lon, date)
        )
    """)
    # depth_grp 列が古いテーブルにない場合は追加
    try:
        conn_ana.execute("ALTER TABLE water_color_daily ADD COLUMN depth_grp TEXT")
    except Exception:
        pass
    conn_ana.commit()

    if start_date is None:
        start_date = "2023-01-01"
    if end_date is None:
        end_date = (datetime.now() + timedelta(days=14)).strftime("%Y-%m-%d")

    d = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")
    total_days = (end - d).days + 1
    print(f"  対象: {len(wx_coords)}座標 × {total_days}日 = {len(wx_coords)*total_days:,}点", flush=True)

    batch = []
    written = 0
    day_count = 0
    # AR(1): 前日の予測値を座標ごとに保持 {(lat, lon): wc_pred}
    # 初日は 0.0（全体平均の近似値）をデフォルトとする
    prev_day_preds: dict = {}

    while d <= end:
        date_iso = d.strftime("%Y-%m-%d")
        m = d.month
        month_sin = math.sin(2 * math.pi * m / 12)
        month_cos = math.cos(2 * math.pi * m / 12)

        # 河口降水量: 日付単位で1回計算（153座標で共有）
        river_precip_cumW7 = {}
        for rname, (rlat, rlon) in RIVER_MOUTHS.items():
            rpf = build_precip_features(conn_wx, rlat, rlon, date_iso)
            river_precip_cumW7[rname] = rpf.get("precip_cumW7", 0.0)

        current_day_preds: dict = {}  # 当日の予測値を収集（翌日の wc_prev1 用）

        # 近傍マップ（初回のみ構築）
        if not _NEIGHBOR_MAP:
            _NEIGHBOR_MAP.update(_build_neighbor_map(wx_coords))

        # 潮汐・月齢（日付単位で共通）
        tide = get_tide_day(date_iso)

        for (lat, lon) in wx_coords:
            pf  = build_precip_features(conn_wx, lat, lon, date_iso)
            wxd = get_wx_day(conn_wx, lat, lon, date_iso)

            # 近接度×降水量（座標ごとに計算）
            riv = {}
            for rname, (rlat, rlon) in RIVER_MOUTHS.items():
                prox = _river_proximity(lat, lon, rlat, rlon)
                riv[f"{rname}_impact"] = prox * river_precip_cumW7[rname]

            # AR(1): 前日予測値（なければ 0.0 = グローバル平均の近似）
            wc_prev1 = prev_day_preds.get((lat, lon), 0.0)

            # 空間ラグ: 近傍ポイントの前日予測値平均（_WC_DAILY_CACHEではなくprev_day_predsを使う）
            nbrs = _NEIGHBOR_MAP.get((lat, lon), [])
            nbr_vals = [prev_day_preds.get(nb, 0.0) for nb in nbrs]
            wc_spatial_lag_val = sum(nbr_vals) / len(nbr_vals) if nbr_vals else 0.0

            r = {**pf, **wxd, **riv, **tide,
                 "wc_prev1": wc_prev1,
                 "wc_spatial_lag": wc_spatial_lag_val,
                 "cape_proximity_n": _cape_proximity(lat, lon),
                 "month_n": m, "month_sin": month_sin, "month_cos": month_cos,
                 "depth_grp": "unknown", "depth_bin_n": 1,
                 "dist_shore": _dist_from_bay_center(lat, lon)}

            # グローバルモデルで予測（深さ情報なし）
            pred = predict_wc(global_coeffs, global_fkeys, r)
            if pred is None:
                continue
            batch.append((lat, lon, date_iso, pred, "unknown"))
            current_day_preds[(lat, lon)] = pred

        prev_day_preds = current_day_preds  # 翌日の wc_prev1 として引き継ぐ
        day_count += 1
        if len(batch) >= 20000:
            conn_ana.executemany(
                "INSERT OR REPLACE INTO water_color_daily VALUES (?,?,?,?,?)", batch)
            conn_ana.commit()
            written += len(batch)
            batch = []
            print(f"    {day_count}/{total_days}日処理 ({written:,}行保存済み)", flush=True)

        d += timedelta(days=1)

    if batch:
        conn_ana.executemany(
            "INSERT OR REPLACE INTO water_color_daily VALUES (?,?,?,?,?)", batch)
        conn_ana.commit()
        written += len(batch)

    conn_ana.close()
    print(f"  water_color_daily: 計{written:,}行 保存完了")


# ─── analysis.sqlite にモデル係数を保存 ──────────────────────────────────────
def save_model_coefficients(global_model, stratified_models):
    """学習済み係数を analysis.sqlite に保存（predict_count.py から参照用）"""
    coeffs, fkeys = global_model
    if coeffs is None:
        return

    conn = sqlite3.connect(DB_ANA, timeout=30.0)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS wc_model_coeffs (
            depth_grp TEXT,
            feature   TEXT,
            coeff     REAL,
            PRIMARY KEY (depth_grp, feature)
        )
    """)
    conn.execute("DELETE FROM wc_model_coeffs")

    rows = [("global", "__bias__", coeffs[0])]
    for i, fk in enumerate(fkeys):
        rows.append(("global", fk, coeffs[i+1]))

    for grp, (sc, sfk) in stratified_models.items():
        if sc is None: continue
        rows.append((grp, "__bias__", sc[0]))
        for i, fk in enumerate(sfk):
            rows.append((grp, fk, sc[i+1]))

    conn.executemany("INSERT OR REPLACE INTO wc_model_coeffs VALUES (?,?,?)", rows)
    conn.commit()
    conn.close()
    print(f"  wc_model_coeffs: {len(rows)}行 保存完了")


# ─── メイン ────────────────────────────────────────────────────────────────────
def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--predict", action="store_true", help="全点×全日予測も実行")
    ap.add_argument("--start",   default=None)
    ap.add_argument("--end",     default=None)
    args = ap.parse_args()

    print("=== 水色予測モデル（深掘り版）===\n")

    if not os.path.exists(DB_WX):
        print(f"[ERROR] weather_cache.sqlite が見つかりません: {DB_WX}"); sys.exit(1)
    conn_wx = sqlite3.connect(DB_WX, timeout=60.0)
    conn_wx.execute("PRAGMA journal_mode=WAL")

    print("weather_cache 座標取得 ...", flush=True)
    wx_coords = load_wx_coords(conn_wx)
    print(f"  {len(wx_coords)}座標")

    print("\n水色実測レコード読込 ...", flush=True)
    raw_records = load_water_color_records()
    print(f"  水色実測: {len(raw_records)}件 / 船宿数: {len({r['ship'] for r in raw_records})}")

    if len(raw_records) < 30:
        print("[ERROR] 水色実測データ不足"); sys.exit(1)

    print("\n特徴量付与 ...", flush=True)
    records = build_features(raw_records, conn_wx, wx_coords)

    # ── 因子相関分析 ──
    factor_correlation_analysis(records)

    # ── 水深別ラグ分析 ──
    depth_lag_analysis(records)

    # ── 遷移日数分析 ──
    transition_analysis(records)

    # ── バックテスト ──
    print("\nバックテスト実行 ...", flush=True)
    backtest(records, use_stratified=True)

    # ── 全データでモデル学習 ──
    print("\n全データでモデル学習 ...", flush=True)
    global_coeffs, global_fkeys = fit_ols(records)
    if global_coeffs:
        print(f"  グローバルモデル: bias={global_coeffs[0]:+.3f}")
        for i, k in enumerate(global_fkeys):
            print(f"    {k:30s}: {global_coeffs[i+1]:+.5f}")
    else:
        print("  [ERROR] グローバルモデル学習失敗")

    print("\n水深別モデル学習 ...", flush=True)
    stratified = fit_stratified_models(records)

    # ── モデル係数を DB 保存 ──
    print("\nモデル係数を analysis.sqlite に保存 ...", flush=True)
    save_model_coefficients((global_coeffs, global_fkeys), stratified)

    # ── 全点×全日予測 ──
    if args.predict:
        print("\n全点×全日 水色予測実行 ...", flush=True)
        predict_all_points(
            conn_wx, wx_coords,
            (global_coeffs, global_fkeys), stratified,
            start_date=args.start, end_date=args.end,
        )
    else:
        print("\n[ヒント] --predict で全点×全日水色予測テーブルを生成できます")

    conn_wx.close()
    print("\n=== 完了 ===")


if __name__ == "__main__":
    main()
