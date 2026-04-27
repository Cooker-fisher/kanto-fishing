"""
build_wc_map.py  —  water_color_map.html 用 JSON 生成（検証用）

出力: tmp_wc_map_data.json
  各ポイント×日付に src フィールドを追加:
    "obs"  : その日その座標（船宿）で実際に水色テキストが記録されていた
    "imp"  : 直接観測なし、0.3° 以内の別ポイントに実測値があり補間した
    "pred" : モデル予測値 (water_color_daily) のみ

使い方:
  python ocean/build_wc_map.py [--days 90]
"""

import csv, glob, json, math, os, sqlite3, sys, argparse
from collections import defaultdict
from datetime import datetime, timedelta

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_ANA   = os.path.join(BASE, "analysis", "V2", "results", "analysis.sqlite")
SHIPS_JSON = os.path.join(BASE, "crawl", "ships.json")
SHIP_FISH_POINT = os.path.join(BASE, "normalize", "ship_fish_point.json")
AREA_COORDS     = os.path.join(BASE, "normalize", "area_coords.json")
POINT_COORDS    = os.path.join(BASE, "normalize", "point_coords.json")
OBS_FIELDS      = os.path.join(BASE, "normalize", "obs_fields.json")
DATA_DIR        = os.path.join(BASE, "data", "V2")
OUT_JSON        = os.path.join(BASE, "tmp_wc_map_data.json")

IMP_MAX_DIST = 0.3  # ° — 補間半径（enrich() と同一）

# ── 水色テキスト → スコア変換 ─────────────────────────────────────────
def _load_wc_scores():
    with open(OBS_FIELDS, encoding="utf-8") as f:
        obs = json.load(f)
    return obs["fields"]["water_color_n"]["scores"]  # {keyword: score}

def text_to_wc_score(text, scores):
    """水色テキストをスコア化。複数キーワードがあれば最初にマッチしたものを採用（先着）。"""
    if not text:
        return None
    for kw, sc in scores.items():
        if kw in text:
            return sc
    return None

# ── 座標ロード ────────────────────────────────────────────────────────
def _load_area_coords():
    with open(AREA_COORDS, encoding="utf-8") as f:
        return json.load(f)

def _load_ship_area():
    with open(SHIPS_JSON, encoding="utf-8") as f:
        ships = json.load(f)
    return {s["name"]: s.get("area", "") for s in ships if not s.get("exclude")}

def _resolve_ship_coord(ship, ship_area, area_coords):
    """船宿 → (lat, lon)。エリア代表座標にフォールバック。"""
    area = ship_area.get(ship, "")
    coord = area_coords.get(area)
    if coord:
        return (coord["lat"], coord["lon"])
    return None

def nearest_grid(lat, lon, grid_coords):
    """最近傍グリッド座標を返す。"""
    best, best_d = None, float("inf")
    for (glat, glon) in grid_coords:
        d = (lat - glat) ** 2 + (lon - glon) ** 2
        if d < best_d:
            best_d = d
            best = (glat, glon)
    return best

# ── 実測水色データ収集 ────────────────────────────────────────────────
def load_obs_wc(days, ship_area, area_coords, wc_scores):
    """
    CSV から実測水色を収集。
    返り値: {date_iso: {(lat_r2, lon_r2): score}}
    """
    today = datetime.today()
    cutoff = (today - timedelta(days=days)).strftime("%Y/%m/%d")

    obs_by_date = defaultdict(lambda: defaultdict(list))  # date -> (lat,lon) -> [score]

    csv_files = sorted(glob.glob(os.path.join(DATA_DIR, "*.csv")))
    for fpath in csv_files:
        with open(fpath, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get("date", "") < cutoff:
                    continue
                if row.get("is_cancellation") == "1":
                    continue
                wc_text = (row.get("water_color") or "").strip()
                if not wc_text:
                    continue
                score = text_to_wc_score(wc_text, wc_scores)
                if score is None:
                    continue
                ship = row.get("ship", "")
                coord = _resolve_ship_coord(ship, ship_area, area_coords)
                if coord is None:
                    continue
                lat_r2 = round(coord[0], 2)
                lon_r2 = round(coord[1], 2)
                date_iso = row["date"].replace("/", "-")
                obs_by_date[date_iso][(lat_r2, lon_r2)].append(score)

    # 平均化
    result = {}
    for date, coord_map in obs_by_date.items():
        result[date] = {coord: sum(v) / len(v) for coord, v in coord_map.items()}
    return result

# ── メイン ────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=90)
    args = parser.parse_args()

    print(f"期間: 直近 {args.days} 日")

    wc_scores  = _load_wc_scores()
    area_coords = _load_area_coords()
    ship_area   = _load_ship_area()

    # 実測水色
    print("実測水色データ読み込み中...")
    obs_wc = load_obs_wc(args.days, ship_area, area_coords, wc_scores)
    obs_dates = sorted(obs_wc.keys())
    print(f"  実測日数: {len(obs_dates)}, ユニーク座標数: {len(set(c for d in obs_wc.values() for c in d))}")

    # モデル予測水色
    print("モデル予測データ読み込み中...")
    db = sqlite3.connect(DB_ANA)
    today = datetime.today()
    since = (today - timedelta(days=args.days)).strftime("%Y-%m-%d")
    rows = db.execute(
        "SELECT lat, lon, date, wc_pred FROM water_color_daily WHERE date >= ? ORDER BY date, lat, lon",
        (since,)
    ).fetchall()
    db.close()

    # グリッド座標一覧
    grid_coords = list(set((round(r[0], 2), round(r[1], 2)) for r in rows))
    print(f"  グリッド座標数: {len(grid_coords)}, 行数: {len(rows)}")

    # coord → point 名のマッピング
    with open(POINT_COORDS, encoding="utf-8") as f:
        pt_coords = json.load(f)
    # point_coords.json の構造を確認して coord_to_name を構築
    coord_to_name = {}
    if isinstance(pt_coords, dict):
        # {name: {lat, lon}} 形式
        for name, v in pt_coords.items():
            if isinstance(v, dict) and v.get("lat") is not None and v.get("lon") is not None:
                try:
                    k = f"{round(float(v['lat']),2)},{round(float(v['lon']),2)}"
                    coord_to_name[k] = name
                except (TypeError, ValueError):
                    pass
    # エリア名でフォールバック
    for area, v in area_coords.items():
        k = f"{round(float(v['lat']),2)},{round(float(v['lon']),2)}"
        if k not in coord_to_name:
            coord_to_name[k] = area

    # pred マップ構築
    pred_by_date = defaultdict(dict)
    for lat, lon, date, wc_pred in rows:
        lat_r2 = round(lat, 2)
        lon_r2 = round(lon, 2)
        pred_by_date[date][(lat_r2, lon_r2)] = wc_pred

    # 全日付リスト
    all_dates = sorted(set(pred_by_date.keys()) | set(obs_wc.keys()))

    # ── pred/obs バイアス補正 ──────────────────────────────────────────
    # pred と obs が同日同座標に存在する日のペアから bias = mean(obs - pred) を推定し
    # pred に加算することで obs スケールに合わせる（per-coord ではなくグローバル補正）
    print("バイアス補正計算中...")
    bias_diffs = []
    for date in all_dates:
        pred_map = pred_by_date.get(date, {})
        obs_map  = obs_wc.get(date, {})
        for coord, ov in obs_map.items():
            pv = pred_map.get(coord)
            if pv is not None:
                bias_diffs.append(ov - pv)
    pred_bias = sum(bias_diffs) / len(bias_diffs) if bias_diffs else 0.0
    print(f"  pred バイアス補正値: {pred_bias:+.3f} (サンプル数: {len(bias_diffs)})")

    # ── ポイントごと × 日付ごとにソース判定 ─────────────────────────
    print("ソース判定中...")
    output_data = {}
    prev_day_map: dict = {}  # キャリーフォワード用（前日の全グリッド値）

    for date in all_dates:
        pred_map = pred_by_date.get(date, {})
        obs_map  = obs_wc.get(date, {})

        # obs=0 かつ pred=0 の日はキャリーフォワード（前日値をそのまま使う）
        # ただし src を "carry" としてマーク（mapでは pred と同じ見た目）
        use_carry = (not obs_map and not pred_map and prev_day_map)

        day_points = []

        for coord in grid_coords:
            lat_r2, lon_r2 = coord
            pred_v = pred_map.get(coord)
            if pred_v is not None:
                pred_v = pred_v + pred_bias  # バイアス補正

            # 実測チェック（同一座標）
            obs_v = obs_map.get(coord)
            if obs_v is not None:
                src = "obs"
                v   = obs_v
            else:
                # 補間チェック（0.3° 以内に実測あり）
                best_imp = None
                best_imp_d = IMP_MAX_DIST ** 2 + 1
                for (olat, olon), ov in obs_map.items():
                    d2 = (lat_r2 - olat) ** 2 + (lon_r2 - olon) ** 2
                    if d2 < IMP_MAX_DIST ** 2 and d2 < best_imp_d:
                        best_imp = ov
                        best_imp_d = d2
                if best_imp is not None:
                    src = "imp"
                    v   = best_imp
                elif pred_v is not None:
                    src = "pred"
                    v   = pred_v
                elif use_carry and coord in prev_day_map:
                    # obs も pred もない日 → 前日値をキャリーフォワード
                    src = "pred"  # 表示上は pred 扱い
                    v   = prev_day_map[coord]
                else:
                    continue  # データなし

            day_points.append({
                "lat": lat_r2,
                "lon": lon_r2,
                "v":   round(v, 3),
                "src": src,
            })

        if day_points:
            output_data[date] = day_points
            prev_day_map = {(p["lat"], p["lon"]): p["v"] for p in day_points}
        elif prev_day_map:
            # 完全データなし日もキャリーフォワードで埋める
            output_data[date] = [
                {"lat": lat, "lon": lon, "v": round(v, 3), "src": "pred"}
                for (lat, lon), v in prev_day_map.items()
            ]

    print(f"出力日数: {len(output_data)}")

    result = {"data": output_data, "coord_to_name": coord_to_name}
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, separators=(",", ":"))
    print(f"保存: {OUT_JSON}")

    # ソース内訳（最新日）
    if output_data:
        latest = sorted(output_data.keys())[-1]
        pts = output_data[latest]
        from collections import Counter
        cnt = Counter(p["src"] for p in pts)
        print(f"最新日 ({latest}) 内訳: obs={cnt['obs']}, imp={cnt['imp']}, pred={cnt['pred']}")

if __name__ == "__main__":
    main()
