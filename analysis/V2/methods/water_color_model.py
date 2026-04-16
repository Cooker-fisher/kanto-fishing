#!/usr/bin/env python3
"""
water_color_model.py — 降水ラグ＋風＋潮流＋水深から水色スコアを予測するモデル

[目的]
  実測水色が取れない日・ポイントでも水色状態を推定する。
  「すべての日×すべてのポイントで濁り/澄みを把握できる」を目指す。

[モデル概要]
  特徴量:
    - precip_sum1〜7: 降水ラグ1〜7日（主因: 雨後の濁りラグ）
    - wind_speed_avg: 当日平均風速（波＋底荒れ）
    - wave_height_avg: 波高（巻き上げ）
    - current_speed_avg: 潮流速度（撹拌 or 換水）
    - depth_avg: 水深（浅=濁りやすい、深=影響遅延）
    - dist_shore: 沿岸距離プロキシ（lat/lonから）
    - month: 季節

  目的変数: water_color_n（-2〜+1 スコア）

[バックテスト]
  leave-one-month-out CV（combo_deep_dive.py と同方式）
  評価: RMSE, sign_accuracy（正/負の一致率）

[出力]
  analysis.sqlite → water_color_daily テーブル（全ポイント×全日付）
  コンソール: per-depth/offshore バックテスト結果

[使い方]
  python analysis/V2/methods/water_color_model.py           # 分析+予測
  python analysis/V2/methods/water_color_model.py --predict # 予測のみ（全点×全日）
"""

import argparse, csv, json, math, os, sqlite3, sys
from collections import defaultdict
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _paths import ROOT_DIR, RESULTS_DIR, DATA_DIR, NORMALIZE_DIR, OCEAN_DIR

DB_WX   = os.path.join(OCEAN_DIR, "weather_cache.sqlite")
DB_ANA  = os.path.join(RESULTS_DIR, "analysis.sqlite")

# ─── 定数 ────────────────────────────────────────────────────────────────────
# 降水ラグ重み（分析で判明: 5〜7日前が最大影響）
PRECIP_LAGS = [1, 2, 3, 4, 5, 6, 7]

# 水深区分: 浅場(shallow) < 15m ≤ 中間(mid) < 30m ≤ 深場(deep)
DEPTH_BINS = [15.0, 30.0]

# 陸からの距離プロキシ: 緯度0.5度≈55km を境に沿岸/沖合判定
# 東京湾中心 35.5N/139.9E からの距離で近似
BAY_CENTER = (35.5, 139.9)

CUTOFF = "2023/01/01"


# ─── ユーティリティ ────────────────────────────────────────────────────────────
def _float(v):
    try:
        return float(v) if v not in (None, "", "None") else None
    except Exception:
        return None


def _dist_from_bay_center(lat, lon):
    """東京湾中心からの角度距離（近似）"""
    if lat is None or lon is None:
        return None
    dlat = lat - BAY_CENTER[0]
    dlon = lon - BAY_CENTER[1]
    return (dlat**2 + dlon**2) ** 0.5


def _depth_group(depth_avg):
    """水深グループ: 'shallow' / 'mid' / 'deep'"""
    if depth_avg is None:
        return "unknown"
    if depth_avg < DEPTH_BINS[0]:
        return "shallow"
    elif depth_avg < DEPTH_BINS[1]:
        return "mid"
    return "deep"


def _nearest_wx_coord(lat, lon, wx_coords):
    """最近傍の weather_cache 座標を返す"""
    best = None
    best_d = 9999.0
    for (wlat, wlon) in wx_coords:
        d = (lat - wlat)**2 + (lon - wlon)**2
        if d < best_d:
            best_d = d
            best = (wlat, wlon)
    return best


def load_wx_coords(conn_wx):
    rows = conn_wx.execute("SELECT DISTINCT lat, lon FROM weather").fetchall()
    return [(r[0], r[1]) for r in rows]


def get_precip_lags(conn_wx, lat, lon, date_iso, lags=PRECIP_LAGS, _cache={}):
    """指定座標・日付の降水ラグ1〜7日を返す {precip_sum1: x, ...}"""
    result = {}
    d = datetime.strptime(date_iso, "%Y-%m-%d")
    for lag in lags:
        lag_date = (d - timedelta(days=lag)).strftime("%Y-%m-%d")
        k = (lat, lon, lag_date)
        if k not in _cache:
            row = conn_wx.execute("""
                SELECT SUM(precipitation) FROM weather
                WHERE lat=? AND lon=? AND dt LIKE ?
            """, (lat, lon, f"{lag_date}%")).fetchone()
            _cache[k] = float(row[0]) if row and row[0] is not None else None
        result[f"precip_sum{lag}"] = _cache[k]
    return result


def get_wx_day(conn_wx, lat, lon, date_iso, _cache={}):
    """日次風速・波高・潮流を取得"""
    k = (lat, lon, date_iso)
    if k in _cache:
        return _cache[k]
    rows = conn_wx.execute("""
        SELECT wind_speed, wave_height, current_speed
        FROM weather WHERE lat=? AND lon=? AND dt LIKE ?
    """, (lat, lon, f"{date_iso}%")).fetchall()
    if not rows:
        _cache[k] = {}
        return {}
    ws = [r[0] for r in rows if r[0] is not None]
    wh = [r[1] for r in rows if r[1] is not None]
    cs = [r[2] for r in rows if r[2] is not None]
    res = {}
    if ws:
        res["wind_speed_avg"] = sum(ws) / len(ws)
        res["wind_speed_max"] = max(ws)
    if wh:
        res["wave_height_avg"] = sum(wh) / len(wh)
    if cs:
        res["current_speed_avg"] = sum(cs) / len(cs)
    _cache[k] = res
    return res


# ─── データ読み込み ─────────────────────────────────────────────────────────
def load_water_color_records():
    """水色実測がある全レコードをロード（重複集約: 同日×同船×同ポイント）"""
    # normalize/ ファイル読み込み
    with open(os.path.join(NORMALIZE_DIR, "point_coords.json"), encoding="utf-8") as f:
        point_coords = json.load(f)
    with open(os.path.join(NORMALIZE_DIR, "area_coords.json"), encoding="utf-8") as f:
        area_coords_raw = json.load(f)
    # area_coords は {エリア名: {"lat": x, "lon": y}} or list 形式に対応
    if isinstance(area_coords_raw, list):
        area_coords = {e["area"]: e for e in area_coords_raw if "area" in e}
    else:
        area_coords = area_coords_raw

    try:
        with open(os.path.join(NORMALIZE_DIR, "ship_fish_point.json"), encoding="utf-8") as f:
            sfp_raw = json.load(f)
        # リスト形式 [{ship, tsuri_mono, points:[...]}, ...] に対応
        sfp = {}
        if isinstance(sfp_raw, list):
            for e in sfp_raw:
                s = e.get("ship", "")
                t = e.get("tsuri_mono", "")
                if s not in sfp:
                    sfp[s] = {}
                sfp[s][t] = e.get("points", [])
        else:
            sfp = sfp_raw
    except Exception:
        sfp = {}

    with open(os.path.join(ROOT_DIR, "crawl", "ships.json"), encoding="utf-8") as f:
        ships_list = json.load(f)
    ship_area = {s["name"]: s["area"] for s in ships_list if "name" in s and "area" in s}
    exclude   = {s["name"] for s in ships_list
                 if s.get("exclude") or s.get("boat_only")}

    # water_color スコアマップ（obs_fields.json から）
    with open(os.path.join(NORMALIZE_DIR, "obs_fields.json"), encoding="utf-8") as f:
        obs_cfg = json.load(f)
    wc_scores = obs_cfg["fields"]["water_color_n"]["scores"]

    def _wc_score(text):
        if not text:
            return None
        for kw, sc in wc_scores.items():
            if kw in text:
                return sc
        return None

    def _resolve_coord(row, ship):
        p1 = row.get("point_place1", "").strip()
        if p1 and p1 in point_coords:
            c = point_coords[p1]
            return c.get("lat"), c.get("lon")
        area = ship_area.get(ship, row.get("area", ""))
        if area and area in area_coords:
            c = area_coords[area]
            return c.get("lat"), c.get("lon")
        return None, None

    # 同日×同船の重複レコードは水色スコアを平均する
    seen = {}  # (ship, date) → record (最初のもので上書き)

    for fn in sorted(os.listdir(DATA_DIR)):
        if not fn.endswith(".csv") or fn == "cancellations.csv":
            continue
        with open(os.path.join(DATA_DIR, fn), encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                if row.get("is_cancellation") == "1":
                    continue
                ship = row.get("ship", "").strip()
                if ship in exclude:
                    continue
                date_str = row.get("date", "").strip()
                if not date_str or date_str < CUTOFF:
                    continue

                wc_raw = " ".join(filter(None, [
                    (row.get("water_color") or "").strip(),
                    (row.get("suishoku_raw") or "").strip(),
                ]))
                wc_n = _wc_score(wc_raw)
                if wc_n is None:
                    continue  # 水色なしレコードは学習から除外

                lat, lon = _resolve_coord(row, ship)
                if lat is None or lon is None:
                    continue  # 座標なしは気象取得できないのでスキップ

                depth_min = _float(row.get("depth_min"))
                depth_max = _float(row.get("depth_max"))
                depth_avg = ((depth_min + depth_max) / 2) if depth_min and depth_max \
                    else (depth_min or depth_max)

                key = (ship, date_str)
                if key in seen:
                    # 同日同船の重複: 水色スコアを蓄積して後で平均
                    seen[key]["_wc_list"].append(wc_n)
                    continue

                seen[key] = {
                    "ship":          ship,
                    "area":          row.get("area", "").strip(),
                    "date":          date_str,
                    "month":         date_str[:7],
                    "lat":           lat,
                    "lon":           lon,
                    "depth_avg":     depth_avg,
                    "water_color_n": wc_n,
                    "wc_raw":        wc_raw,
                    "_wc_list":      [wc_n],
                }

    records = list(seen.values())
    # 重複分の平均
    for r in records:
        wc_list = r.pop("_wc_list")
        r["water_color_n"] = sum(wc_list) / len(wc_list)

    records.sort(key=lambda r: r["date"])
    return records


# ─── 特徴量付与 ────────────────────────────────────────────────────────────────
def build_features(records, conn_wx, wx_coords):
    """各レコードに precip_lags + 風/波/潮流 + 深さ/沖合 特徴量を付与"""
    enriched = []
    for r in records:
        lat, lon = r.get("lat"), r.get("lon")
        if lat is None or lon is None:
            continue
        wlat, wlon = _nearest_wx_coord(lat, lon, wx_coords)
        date_iso = datetime.strptime(r["date"], "%Y/%m/%d").strftime("%Y-%m-%d")

        precips = get_precip_lags(conn_wx, wlat, wlon, date_iso)
        wxday   = get_wx_day(conn_wx, wlat, wlon, date_iso)

        feat = {**r, **precips, **wxday}
        feat["dist_shore"] = _dist_from_bay_center(lat, lon)
        feat["depth_grp"]  = _depth_group(r.get("depth_avg"))
        feat["month_n"]    = int(r["date"][5:7])
        enriched.append(feat)

    print(f"  特徴量付与: {len(enriched)}件 / 全{len(records)}件", flush=True)
    return enriched


# ─── 線形回帰（stdlib のみ） ────────────────────────────────────────────────────
def _mean(xs):
    return sum(xs) / len(xs) if xs else 0.0


def _pearson(xs, ys):
    n = len(xs)
    if n < 5:
        return 0.0
    mx, my = _mean(xs), _mean(ys)
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sx  = (sum((x - mx)**2 for x in xs)) ** 0.5
    sy  = (sum((y - my)**2 for y in ys)) ** 0.5
    if sx < 1e-9 or sy < 1e-9:
        return 0.0
    return cov / (sx * sy)


def _ols_single(xs, ys):
    """単変量 OLS: y = a*x + b"""
    n = len(xs)
    if n < 3:
        return 0.0, _mean(ys)
    mx, my = _mean(xs), _mean(ys)
    denom = sum((x - mx)**2 for x in xs)
    if denom < 1e-12:
        return 0.0, my
    a = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / denom
    b = my - a * mx
    return a, b


def fit_linear(records, target="water_color_n"):
    """多変量線形回帰 (正規方程式; stdlib のみ)"""
    feature_keys = [f"precip_sum{i}" for i in PRECIP_LAGS] + [
        "wind_speed_avg", "wave_height_avg", "current_speed_avg",
    ]
    # 月サイン/コサイン（季節性）
    feature_keys += ["month_sin", "month_cos"]

    rows_X, rows_y = [], []
    for r in records:
        y = r.get(target)
        if y is None:
            continue
        # 月のsin/cos
        m = r.get("month_n", 6)
        r["month_sin"] = math.sin(2 * math.pi * m / 12)
        r["month_cos"] = math.cos(2 * math.pi * m / 12)
        row = [r.get(k) for k in feature_keys]
        if any(v is None for v in row):
            continue
        rows_X.append(row)
        rows_y.append(y)

    if len(rows_X) < 20:
        return None, feature_keys

    n, p = len(rows_X), len(feature_keys)
    # バイアス列追加
    X = [[1.0] + list(row) for row in rows_X]
    y = list(rows_y)
    p1 = p + 1  # バイアス込み

    # X^T X
    XtX = [[sum(X[i][a] * X[i][b] for i in range(n)) for b in range(p1)] for a in range(p1)]
    # X^T y
    Xty = [sum(X[i][a] * y[i] for i in range(n)) for a in range(p1)]

    # Gaussian elimination (素朴実装)
    mat = [XtX[i] + [Xty[i]] for i in range(p1)]
    for col in range(p1):
        pivot = max(range(col, p1), key=lambda r: abs(mat[r][col]))
        mat[col], mat[pivot] = mat[pivot], mat[col]
        if abs(mat[col][col]) < 1e-12:
            continue
        scale = mat[col][col]
        mat[col] = [v / scale for v in mat[col]]
        for row in range(p1):
            if row == col:
                continue
            fac = mat[row][col]
            mat[row] = [mat[row][j] - fac * mat[col][j] for j in range(p1 + 1)]

    coeffs = [mat[i][-1] for i in range(p1)]  # [bias, c1, c2, ...]
    return coeffs, feature_keys


def predict_wc(coeffs, feature_keys, r):
    """係数ベクトルで水色スコアを予測"""
    if coeffs is None:
        return None
    m = r.get("month_n", 6)
    r["month_sin"] = math.sin(2 * math.pi * m / 12)
    r["month_cos"] = math.cos(2 * math.pi * m / 12)
    feats = [r.get(k) for k in feature_keys]
    if any(v is None for v in feats):
        return None
    val = coeffs[0] + sum(coeffs[i+1] * feats[i] for i in range(len(feats)))
    return max(-2.0, min(1.0, val))


# ─── バックテスト ──────────────────────────────────────────────────────────────
def backtest(records):
    """leave-one-month-out CV で水色予測精度を評価"""
    months = sorted({r["month"] for r in records})
    if len(months) < 3:
        print("  月数不足 → バックテスト不可")
        return

    all_errs = []
    sign_ok   = 0
    sign_total = 0
    group_errs = defaultdict(list)  # depth_grp 別

    for test_month in months:
        train = [r for r in records if r["month"] != test_month]
        test  = [r for r in records if r["month"] == test_month]
        if len(train) < 30 or len(test) < 5:
            continue

        coeffs, fkeys = fit_linear(train)
        if coeffs is None:
            continue

        for r in test:
            pred = predict_wc(coeffs, fkeys, r)
            actual = r.get("water_color_n")
            if pred is None or actual is None:
                continue
            err = pred - actual
            all_errs.append(err)
            grp = r.get("depth_grp", "unknown")
            group_errs[grp].append(err)
            sign_total += 1
            if (pred >= 0) == (actual >= 0):
                sign_ok += 1

    if not all_errs:
        print("  バックテスト結果なし")
        return

    rmse = (sum(e**2 for e in all_errs) / len(all_errs)) ** 0.5
    mae  = sum(abs(e) for e in all_errs) / len(all_errs)
    sign_acc = sign_ok / sign_total * 100 if sign_total else 0.0
    mean_err = sum(all_errs) / len(all_errs)

    print(f"\n=== 水色予測 leave-one-month-out CV ===")
    print(f"  n={len(all_errs)}  RMSE={rmse:.3f}  MAE={mae:.3f}  偏り={mean_err:+.3f}")
    print(f"  符号一致率: {sign_acc:.1f}% ({sign_ok}/{sign_total})")

    print(f"\n  水深グループ別:")
    for grp in ["shallow", "mid", "deep", "unknown"]:
        errs = group_errs.get(grp, [])
        if not errs:
            continue
        rmse_g = (sum(e**2 for e in errs) / len(errs)) ** 0.5
        print(f"    {grp:8s}: n={len(errs):4d}  RMSE={rmse_g:.3f}")


# ─── 因子寄与分析 ──────────────────────────────────────────────────────────────
def factor_correlation_analysis(records):
    """各因子と water_color_n の相関・回帰係数を出力"""
    print("\n=== 因子別相関（水色スコアとの Pearson r） ===")

    factor_groups = [
        ("降水ラグ", [f"precip_sum{i}" for i in PRECIP_LAGS]),
        ("風・波・潮流", ["wind_speed_avg", "wind_speed_max", "wave_height_avg", "current_speed_avg"]),
        ("水深・沖合",   ["depth_avg", "dist_shore"]),
    ]

    targets = [r.get("water_color_n") for r in records]

    for group_name, keys in factor_groups:
        print(f"\n  [{group_name}]")
        for k in keys:
            xs = []
            ys = []
            for r, y in zip(records, targets):
                x = r.get(k)
                if x is not None and y is not None:
                    xs.append(x)
                    ys.append(y)
            if len(xs) < 10:
                print(f"    {k:25s}: n={len(xs):4d} (データ不足)")
                continue
            r_val = _pearson(xs, ys)
            a, b  = _ols_single(xs, ys)
            print(f"    {k:25s}: n={len(xs):4d}  r={r_val:+.3f}  slope={a:+.4f}")


# ─── 深さ×ラグ 詳細分析 ──────────────────────────────────────────────────────
def depth_lag_analysis(records):
    """水深グループ別に降水ラグ相関を分析し、最適ラグを特定"""
    print("\n=== 水深グループ別 降水ラグ相関 ===")
    print("  (水深が浅いほど短ラグで濁り、深いほど長ラグ)")
    print(f"  {'':8s}", end="")
    for lag in PRECIP_LAGS:
        print(f"  D-{lag}", end="")
    print()

    groups = ["shallow", "mid", "deep", "unknown"]
    for grp in groups:
        grp_recs = [r for r in records if r.get("depth_grp") == grp]
        if len(grp_recs) < 10:
            continue
        targets = [r["water_color_n"] for r in grp_recs]
        print(f"  {grp:8s}(n={len(grp_recs):4d})", end="")
        for lag in PRECIP_LAGS:
            key = f"precip_sum{lag}"
            xs = [r.get(key) for r in grp_recs]
            pairs = [(x, y) for x, y in zip(xs, targets) if x is not None and y is not None]
            if len(pairs) < 5:
                print(f"  {'':4s}", end="")
                continue
            r_val = _pearson([p[0] for p in pairs], [p[1] for p in pairs])
            print(f"  {r_val:+.2f}", end="")
        print()

    # 沖合距離でも同様
    print(f"\n  [風・波・潮流との相関]")
    for key in ["wind_speed_avg", "wave_height_avg", "current_speed_avg"]:
        xs = [r.get(key) for r in records]
        ys = [r.get("water_color_n") for r in records]
        pairs = [(x, y) for x, y in zip(xs, ys) if x is not None and y is not None]
        if len(pairs) < 10:
            continue
        r_val = _pearson([p[0] for p in pairs], [p[1] for p in pairs])
        print(f"    {key:25s}: n={len(pairs):4d}  r={r_val:+.3f}")


# ─── 全点×全日 水色予測 ────────────────────────────────────────────────────────
def predict_all_points(conn_wx, wx_coords, coeffs, feature_keys, start_date=None, end_date=None):
    """全 weather_cache 座標×全日付で水色スコアを予測し analysis.sqlite に保存"""
    if coeffs is None:
        print("  係数なし → 予測スキップ")
        return

    conn_ana = sqlite3.connect(DB_ANA, timeout=30.0)
    conn_ana.execute("PRAGMA journal_mode=WAL")
    conn_ana.execute("""
        CREATE TABLE IF NOT EXISTS water_color_daily (
            lat   REAL,
            lon   REAL,
            date  TEXT,
            wc_pred REAL,
            PRIMARY KEY (lat, lon, date)
        )
    """)
    conn_ana.commit()

    # 日付範囲
    if start_date is None:
        start_date = "2023-01-01"
    if end_date is None:
        end_date = datetime.now().strftime("%Y-%m-%d")

    d = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")
    total_days = (end - d).days + 1
    written = 0
    batch = []

    print(f"  予測対象: {len(wx_coords)}座標 × {total_days}日 = {len(wx_coords)*total_days:,}点", flush=True)

    while d <= end:
        date_iso = d.strftime("%Y-%m-%d")
        m = d.month
        month_sin = math.sin(2 * math.pi * m / 12)
        month_cos = math.cos(2 * math.pi * m / 12)

        for (lat, lon) in wx_coords:
            precips = get_precip_lags(conn_wx, lat, lon, date_iso)
            wxday   = get_wx_day(conn_wx, lat, lon, date_iso)
            r = {**precips, **wxday, "month_n": m, "month_sin": month_sin, "month_cos": month_cos}
            pred = predict_wc(coeffs, feature_keys, r)
            if pred is None:
                continue
            batch.append((lat, lon, date_iso, pred))

        if len(batch) >= 10000:
            conn_ana.executemany(
                "INSERT OR REPLACE INTO water_color_daily VALUES (?,?,?,?)", batch)
            conn_ana.commit()
            written += len(batch)
            batch = []

        d += timedelta(days=1)

    if batch:
        conn_ana.executemany(
            "INSERT OR REPLACE INTO water_color_daily VALUES (?,?,?,?)", batch)
        conn_ana.commit()
        written += len(batch)

    conn_ana.close()
    print(f"  water_color_daily: {written:,}行 保存完了")


# ─── メイン ────────────────────────────────────────────────────────────────────
def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    ap = argparse.ArgumentParser()
    ap.add_argument("--predict", action="store_true", help="全点×全日予測も実行（時間かかる）")
    ap.add_argument("--start",   default=None, help="予測開始日 YYYY-MM-DD")
    ap.add_argument("--end",     default=None, help="予測終了日 YYYY-MM-DD")
    args = ap.parse_args()

    print("=== 水色予測モデル ===\n")

    # weather_cache 接続
    if not os.path.exists(DB_WX):
        print(f"[ERROR] weather_cache.sqlite が見つかりません: {DB_WX}")
        sys.exit(1)
    conn_wx = sqlite3.connect(DB_WX, timeout=30.0)
    conn_wx.execute("PRAGMA journal_mode=WAL")

    print("weather_cache 座標取得...", flush=True)
    wx_coords = load_wx_coords(conn_wx)
    print(f"  {len(wx_coords)}座標")

    print("\n水色実測レコード読込...", flush=True)
    try:
        raw_records = load_water_color_records()
    except Exception as e:
        print(f"[ERROR] load_water_color_records: {e}")
        import traceback; traceback.print_exc()
        sys.exit(1)
    print(f"  水色実測レコード: {len(raw_records)}件")

    if len(raw_records) < 30:
        print("[ERROR] 水色実測データが少なすぎます（30件未満）")
        sys.exit(1)

    print("\n特徴量付与...", flush=True)
    records = build_features(raw_records, conn_wx, wx_coords)

    if len(records) < 30:
        print("[ERROR] 特徴量付与後のレコードが少なすぎます")
        sys.exit(1)

    # ── 因子相関分析 ──
    factor_correlation_analysis(records)

    # ── 水深×ラグ詳細分析 ──
    depth_lag_analysis(records)

    # ── バックテスト ──
    print("\nバックテスト実行...", flush=True)
    backtest(records)

    # ── モデル学習（全データ）──
    print("\n全データでモデル学習...", flush=True)
    coeffs, feature_keys = fit_linear(records)
    if coeffs is not None:
        print(f"  係数: bias={coeffs[0]:+.3f}")
        for i, k in enumerate(feature_keys):
            print(f"    {k:25s}: {coeffs[i+1]:+.4f}")
    else:
        print("  [ERROR] モデル学習失敗")

    # ── 全点×全日予測 ──
    if args.predict:
        print("\n全点×全日 水色予測実行...", flush=True)
        predict_all_points(conn_wx, wx_coords, coeffs, feature_keys,
                           start_date=args.start, end_date=args.end)
    else:
        print("\n[ヒント] 全点×全日予測は --predict フラグで実行")

    conn_wx.close()
    print("\n=== 完了 ===")


if __name__ == "__main__":
    main()
