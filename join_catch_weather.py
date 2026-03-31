#!/usr/bin/env python3
"""
釣果×気象データ結合スクリプト join_catch_weather.py

[入力]
  data/YYYY-MM.csv          — 釣果データ（月別）
  weather_data/*_history.csv — 気象データ（エリア別・日次）
  point_coords.json          — ポイント緯度経度
  ship_fish_point.json       — ③船宿×魚種→ポイント フォールバック表
  area_weather_map.json      — 港エリア → 気象エリアのマッピング

[ポイント解決ロジック（3段階）]
  1. point_place が point_coords.json に存在 → そのまま使う
  2. それ以外（空白/航程/近場/浅場/不明など）
     → ship_fish_point.json の ship × fish → point1 を使う
  3. ③にも未登録 → 船宿のエリア代表の気象エリアを使う

[出力]
  analysis/master_dataset.csv
"""

import csv, json, os, re, sys

sys.stdout.reconfigure(encoding="utf-8")

BASE_DIR     = os.path.dirname(os.path.abspath(__file__))
DATA_DIR     = os.path.join(BASE_DIR, "data")
WEATHER_DIR  = os.path.join(BASE_DIR, "weather_data")
OUTPUT_DIR   = os.path.join(BASE_DIR, "analysis")
OUTPUT_FILE  = os.path.join(OUTPUT_DIR, "master_dataset.csv")

OUTPUT_HEADER = [
    "date", "ship", "area", "fish",
    "cnt_min", "cnt_max", "cnt_avg",
    "size_min", "size_max",
    "kg_min", "kg_max",
    "is_boat",
    "point_place", "point_place2",
    "point_depth_min", "point_depth_max",
    "resolved_point",       # 実際に気象を引いたポイント名
    "resolve_method",       # "direct" / "fallback_fish" / "fallback_area"
    "wave_height", "wave_period", "swell_height",
    "wind_speed", "wind_dir", "temp", "sea_surface_temp", "pressure",
    "tide_type", "tide_range", "moon_age",
    "flood1", "flood1_cm", "ebb1", "ebb1_cm",
]

# ── 不明扱いのポイント表記パターン ───────────────────────────────────
_UNRESOLVABLE_RE = re.compile(r'^(航程|近場|浅場|深場|東京湾一帯|湾内|南沖|東沖|西沖|北沖|赤灯沖|観音沖).*')

def is_unresolvable(point_place):
    if not point_place:
        return True
    return bool(_UNRESOLVABLE_RE.match(point_place))


# ── データ読み込み ────────────────────────────────────────────────────

def load_point_coords():
    path = os.path.join(BASE_DIR, "point_coords.json")
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    # lat/lon が null のものは除外
    return {k: v for k, v in data.items() if v.get("lat") is not None}


def load_ship_fish_point():
    path = os.path.join(BASE_DIR, "ship_fish_point.json")
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_area_weather_map():
    path = os.path.join(BASE_DIR, "area_weather_map.json")
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    # _comment / _areas キーを除いた実マッピング
    return {k: v for k, v in data.items() if not k.startswith("_")}


def load_weather_index():
    """weather_data/*_history.csv → {area_code: {date: row}}"""
    index = {}
    for fname in os.listdir(WEATHER_DIR):
        if not fname.endswith("_history.csv"):
            continue
        area_code = fname.replace("_history.csv", "")
        with open(os.path.join(WEATHER_DIR, fname), encoding="utf-8") as f:
            index[area_code] = {row["date"]: row for row in csv.DictReader(f)}
    return index


def load_catch_csv():
    """data/YYYY-MM.csv を全て読み込んでリストで返す。"""
    rows = []
    for fname in sorted(os.listdir(DATA_DIR)):
        if not fname.endswith(".csv"):
            continue
        with open(os.path.join(DATA_DIR, fname), encoding="utf-8") as f:
            rows.extend(list(csv.DictReader(f)))
    return rows


# ── ポイント解決 ─────────────────────────────────────────────────────

# エリア → 気象エリアコードのハードコードフォールバック
_AREA_WEATHER_FALLBACK = {
    "東京湾": "tokyo_bay",
    "相模湾": "sagami_bay",
    "外房":   "outer_boso",
    "茨城":   "ibaraki",
}

def area_to_weather_code(area, area_map):
    """港名 → 気象エリアコード"""
    code = area_map.get(area)
    if code:
        return code
    # 部分一致フォールバック
    for key, val in _AREA_WEATHER_FALLBACK.items():
        if key in area:
            return val
    return "tokyo_bay"  # 最終デフォルト


def resolve_point(row, point_coords, ship_fish_point, area_map):
    """
    釣果行からポイント名と気象エリアコードを解決する。
    戻り値: (resolved_point, weather_area_code, method)
    """
    ship  = row.get("ship", "")
    fish  = row.get("fish", "")
    area  = row.get("area", "")

    # migrate後のカラム名に対応（migrate前はpoint_place/point_depth）
    point_place = row.get("point_place", "")

    # ── Step 1: point_place が直接解決できる ──
    if point_place and not is_unresolvable(point_place) and point_place in point_coords:
        return point_place, None, "direct"

    # ── Step 2: ③ ship_fish_point.json フォールバック ──
    ship_entry = ship_fish_point.get(ship, {})
    fish_entry = ship_entry.get(fish, {})
    if fish_entry and fish_entry.get("point1"):
        fallback_point = fish_entry["point1"]
        if fallback_point in point_coords:
            return fallback_point, None, "fallback_fish"

    # ── Step 3: エリア代表の気象エリア ──
    weather_code = area_to_weather_code(area, area_map)
    return None, weather_code, "fallback_area"


# ── 気象データ取得 ───────────────────────────────────────────────────

# point_coords のポイント名 → 気象エリアコードの対応（簡易）
# Open-Meteo の経度から東京湾/相模湾/外房/茨城を判定
def coords_to_weather_code(lat, lon):
    if lon >= 140.4:
        return "outer_boso" if lat < 36.0 else "ibaraki"
    if lat >= 36.0:
        return "ibaraki"
    if lon >= 139.65 and lat >= 35.15:
        return "tokyo_bay"
    return "sagami_bay"


def get_weather(date_str, resolved_point, weather_code, point_coords, weather_index):
    """
    日付とポイント/エリアから気象行を返す。
    date_str: "YYYY/MM/DD" → "YYYY-MM-DD" に変換
    """
    date_norm = date_str.replace("/", "-")
    target_code = weather_code

    if resolved_point and resolved_point in point_coords:
        coords = point_coords[resolved_point]
        target_code = coords_to_weather_code(coords["lat"], coords["lon"])

    return weather_index.get(target_code, {}).get(date_norm, {})


# ── メイン ────────────────────────────────────────────────────────────

def main():
    print("=== join_catch_weather.py ===")

    point_coords    = load_point_coords()
    ship_fish_point = load_ship_fish_point()
    area_map        = load_area_weather_map()
    weather_index   = load_weather_index()
    catch_rows      = load_catch_csv()

    print(f"釣果: {len(catch_rows)}行")
    print(f"気象エリア: {list(weather_index.keys())}")
    print(f"ポイント座標: {len(point_coords)}件")

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    stats = {"direct": 0, "fallback_fish": 0, "fallback_area": 0}
    out_rows = []

    for row in catch_rows:
        resolved_point, weather_code, method = resolve_point(
            row, point_coords, ship_fish_point, area_map
        )
        stats[method] += 1

        w = get_weather(
            row.get("date", ""),
            resolved_point, weather_code,
            point_coords, weather_index
        )

        # migrate後カラムとmigrate前カラムの両対応
        out_rows.append({
            "date":           row.get("date", ""),
            "ship":           row.get("ship", ""),
            "area":           row.get("area", ""),
            "fish":           row.get("fish", ""),
            "cnt_min":        row.get("cnt_min", ""),
            "cnt_max":        row.get("cnt_max", ""),
            "cnt_avg":        row.get("cnt_avg", ""),
            "size_min":       row.get("size_min", ""),
            "size_max":       row.get("size_max", ""),
            "kg_min":         row.get("kg_min", ""),
            "kg_max":         row.get("kg_max", ""),
            "is_boat":        row.get("is_boat", ""),
            "point_place":    row.get("point_place", row.get("point", "")),
            "point_place2":   row.get("point_place2", ""),
            "point_depth_min":row.get("point_depth_min", ""),
            "point_depth_max":row.get("point_depth_max", ""),
            "resolved_point": resolved_point or "",
            "resolve_method": method,
            "wave_height":        w.get("wave_height", ""),
            "wave_period":        w.get("wave_period", ""),
            "swell_height":       w.get("swell_height", ""),
            "wind_speed":         w.get("wind_speed", ""),
            "wind_dir":           w.get("wind_dir", ""),
            "temp":               w.get("temp", ""),
            "sea_surface_temp":   w.get("sea_surface_temp", ""),
            "pressure":           w.get("pressure", ""),
            "tide_type":          w.get("tide_type", ""),
            "tide_range":         w.get("tide_range", ""),
            "moon_age":           w.get("moon_age", ""),
            "flood1":             w.get("flood1", ""),
            "flood1_cm":          w.get("flood1_cm", ""),
            "ebb1":               w.get("ebb1", ""),
            "ebb1_cm":            w.get("ebb1_cm", ""),
        })

    with open(OUTPUT_FILE, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_HEADER)
        writer.writeheader()
        writer.writerows(out_rows)

    print(f"\n[ポイント解決結果]")
    print(f"  直接解決 (direct):        {stats['direct']:5d}件")
    print(f"  ③フォールバック (fish):   {stats['fallback_fish']:5d}件")
    print(f"  エリア代表 (area):        {stats['fallback_area']:5d}件")
    print(f"\n出力: {OUTPUT_FILE}（{len(out_rows)}行）")


if __name__ == "__main__":
    main()
