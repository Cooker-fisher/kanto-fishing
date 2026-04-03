#!/usr/bin/env python3
"""
enrich_catches.py — 釣果CSV × 海況SQLite → enriched_catches.csv

[入力]
  data/YYYY-MM.csv          釣果データ（82,481行）
  weather_cache.sqlite       海況キャッシュ（3時間ごと × 153座標）
  point_coords.json / ship_fish_point.json / area_coords.json

[出力]
  enriched_catches.csv      釣果 + lat/lon + 海況 + 潮汐

[出船時刻]
  06:00 のデータを使用（早朝出船が多いため）

[使い方]
  python enrich_catches.py
  python enrich_catches.py --fish アジ       # 特定魚種のみ
  python enrich_catches.py --ship 忠彦丸     # 特定船宿のみ
"""

import csv, json, math, os, sqlite3, sys
from datetime import datetime

BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR    = os.path.dirname(BASE_DIR)

def _build_raw_to_tsuri_map():
    path = os.path.join(ROOT_DIR, "tsuri_mono_map_draft.json")
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    mapping = data.get("TSURI_MONO_MAP", {})
    raw_to_tsuri = {}
    for tsuri_mono, raw_list in mapping.items():
        if tsuri_mono.startswith("_"):
            continue
        for raw in raw_list:
            raw_to_tsuri[raw] = tsuri_mono
    return raw_to_tsuri

RAW_TO_TSURI = _build_raw_to_tsuri_map()
DB_PATH     = os.path.join(ROOT_DIR, "weather_cache.sqlite")
DATA_DIR    = os.path.join(ROOT_DIR, "data")
OUTPUT_FILE = os.path.join(BASE_DIR, "enriched_catches.csv")

DEPART_HOUR = "06:00"  # 出船時刻帯

OUTPUT_HEADER = [
    # 釣果
    "ship", "area", "date", "tsuri_mono", "main_sub", "fish_raw",
    "cnt_min", "cnt_max", "cnt_avg", "is_boat",
    "point_place1", "lat", "lon", "resolve_src",
    # 気象（Open-Meteo Weather）
    "wind_speed", "wind_dir", "temp", "pressure", "weather_code",
    # 波浪（Open-Meteo Marine）
    "wave_height", "wave_period", "wave_dir",
    "swell_height", "swell_period", "sst",
    "current_spd", "current_dir",
    # 潮汐（tide736.net）
    "tide_type", "tide_range", "moon_age",
    "flood1", "flood1_cm", "ebb1", "ebb1_cm",
]

# ── 潮位港（座標→最寄り港） ───────────────────────────────────────────────
TIDE_PORTS = {
    "ibaraki":    {"lat": 36.32, "lon": 140.57},
    "outer_boso": {"lat": 35.14, "lon": 140.30},
    "tokyo_bay":  {"lat": 35.66, "lon": 139.78},
    "sagami_bay": {"lat": 35.16, "lon": 139.61},
    "shizuoka":   {"lat": 34.60, "lon": 138.22},
}

def coord_to_port(lat, lon):
    best, best_d = None, float("inf")
    for code, p in TIDE_PORTS.items():
        d = math.hypot(lat - p["lat"], lon - p["lon"])
        if d < best_d:
            best_d, best = d, code
    return best


# ── resolve_point のための依存関数をインポート ────────────────────────────
sys.path.insert(0, ROOT_DIR)
from crawler import (
    resolve_point, _load_area_coords, _load_ship_area_map,
    _split_point_places_depth, _extract_point_from_kanso,
)

def load_support_data():
    with open(os.path.join(ROOT_DIR, "ship_fish_point.json"), encoding="utf-8") as f:
        sfp = json.load(f)
    with open(os.path.join(ROOT_DIR, "point_coords.json"), encoding="utf-8") as f:
        pc = json.load(f)
    area_coords   = _load_area_coords()
    ship_area_map = _load_ship_area_map()
    return sfp, pc, area_coords, ship_area_map


# ── SQLite クエリ ─────────────────────────────────────────────────────────
def build_weather_index(conn):
    """(round(lat,2), round(lon,2), date) → weather row のインメモリキャッシュ構築は重いので
    都度クエリ。インデックスが効くので十分速い。"""
    pass  # インデックスはinit_db済み

def get_weather(conn, lat, lon, date_str):
    """出船時刻帯（06:00）の海況を返す。なければ None。"""
    dt = f"{date_str}T{DEPART_HOUR}"
    # ROUND(lat,2) / ROUND(lon,2) でマッチ（浮動小数点誤差を回避）
    row = conn.execute("""
        SELECT wind_speed, wind_dir, temp, pressure, weather_code,
               wave_height, wave_period, wave_dir,
               swell_height, swell_period, sst,
               current_spd, current_dir
        FROM weather
        WHERE ROUND(lat,2)=ROUND(?,2) AND ROUND(lon,2)=ROUND(?,2) AND dt=?
        LIMIT 1
    """, (lat, lon, dt)).fetchone()
    return row

def get_tide(conn, port_code, date_str):
    """潮汐データを返す。なければ None。"""
    row = conn.execute("""
        SELECT tide_type, tide_range, moon_age,
               flood1, flood1_cm, ebb1, ebb1_cm
        FROM tide
        WHERE port_code=? AND date=?
        LIMIT 1
    """, (port_code, date_str)).fetchone()
    return row


# ── メイン ────────────────────────────────────────────────────────────────
def main():
    # コマンドライン引数
    fish_filter = None
    ship_filter = None
    args = sys.argv[1:]
    for i, a in enumerate(args):
        if a == "--fish" and i + 1 < len(args):
            fish_filter = args[i + 1]
        if a == "--ship" and i + 1 < len(args):
            ship_filter = args[i + 1]

    print(f"=== enrich_catches.py 開始 ===")
    if fish_filter:
        print(f"  魚種フィルタ: {fish_filter}")
    if ship_filter:
        print(f"  船宿フィルタ: {ship_filter}")

    sfp, pc, area_coords, ship_area_map = load_support_data()
    conn = sqlite3.connect(DB_PATH)

    # CSVファイル一覧
    csv_files = sorted(
        f for f in os.listdir(DATA_DIR) if f.endswith(".csv")
    )

    total_in = 0
    total_out = 0
    weather_hit = 0
    tide_hit = 0

    with open(OUTPUT_FILE, "w", encoding="utf-8", newline="") as out_f:
        writer = csv.DictWriter(out_f, fieldnames=OUTPUT_HEADER)
        writer.writeheader()

        for fn in csv_files:
            path = os.path.join(DATA_DIR, fn)
            with open(path, encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                rows_in_file = 0

                for row in reader:
                    total_in += 1

                    # フィルタ
                    if fish_filter and row.get("fish_raw") != fish_filter:
                        continue
                    if ship_filter and row.get("ship") != ship_filter:
                        continue
                    if row.get("is_cancellation") == "1":
                        continue

                    ship        = row.get("ship", "")
                    date_str_ym = row.get("date", "")           # "2024/03/15"
                    fish_raw_v  = row.get("fish_raw", "").strip()
                    if fish_raw_v in RAW_TO_TSURI:
                        tsuri_mono = RAW_TO_TSURI[fish_raw_v]
                    else:
                        tsuri_mono = row.get("tsuri_mono", "") or row.get("tsuri_mono_raw", "")

                    # 日付を SQLite フォーマット（YYYY-MM-DD）に変換
                    try:
                        date_iso = datetime.strptime(date_str_ym, "%Y/%m/%d").strftime("%Y-%m-%d")
                    except ValueError:
                        continue

                    # ── ポイント解決 ──────────────────────────────────────
                    pp_raw = row.get("point_place1", "") or ""
                    places, _ = _split_point_places_depth(pp_raw) if pp_raw else ([], {})
                    if not places:
                        places = [""]
                    if not places[0]:
                        kanso = row.get("kanso_raw", "") or ""
                        pp_k  = _extract_point_from_kanso(kanso)
                        if pp_k:
                            places = [pp_k]
                    pp = places[0] if places else ""

                    lat, lon, resolve_src = resolve_point(
                        pp, ship, tsuri_mono, sfp, ship_area_map, pc, area_coords
                    )

                    # ── 海況取得 ──────────────────────────────────────────
                    wx_row  = None
                    tide_row = None
                    port_code = None

                    if lat is not None:
                        wx_row = get_weather(conn, lat, lon, date_iso)
                        if wx_row:
                            weather_hit += 1
                        port_code = coord_to_port(lat, lon)
                        tide_row  = get_tide(conn, port_code, date_iso)
                        if tide_row:
                            tide_hit += 1

                    # ── 出力行 ───────────────────────────────────────────
                    def wx(i):
                        return wx_row[i] if wx_row else ""
                    def td(i):
                        return tide_row[i] if tide_row else ""

                    out_row = {
                        "ship":         ship,
                        "area":         row.get("area", ""),
                        "date":         date_str_ym,
                        "tsuri_mono":   tsuri_mono,
                        "main_sub":     row.get("main_sub", ""),
                        "fish_raw":     row.get("fish_raw", ""),
                        "cnt_min":      row.get("cnt_min", ""),
                        "cnt_max":      row.get("cnt_max", ""),
                        "cnt_avg":      row.get("cnt_avg", ""),
                        "is_boat":      row.get("is_boat", ""),
                        "point_place1": pp,
                        "lat":          lat if lat else "",
                        "lon":          lon if lon else "",
                        "resolve_src":  resolve_src or "",
                        # 気象
                        "wind_speed":   wx(0),
                        "wind_dir":     wx(1),
                        "temp":         wx(2),
                        "pressure":     wx(3),
                        "weather_code": wx(4),
                        # 波浪
                        "wave_height":  wx(5),
                        "wave_period":  wx(6),
                        "wave_dir":     wx(7),
                        "swell_height": wx(8),
                        "swell_period": wx(9),
                        "sst":          wx(10),
                        "current_spd":  wx(11),
                        "current_dir":  wx(12),
                        # 潮汐
                        "tide_type":    td(0),
                        "tide_range":   td(1),
                        "moon_age":     td(2),
                        "flood1":       td(3),
                        "flood1_cm":    td(4),
                        "ebb1":         td(5),
                        "ebb1_cm":      td(6),
                    }
                    writer.writerow(out_row)
                    total_out += 1
                    rows_in_file += 1

            print(f"  {fn}: {rows_in_file}行")

    conn.close()

    size_mb = os.path.getsize(OUTPUT_FILE) / 1024 / 1024
    print(f"\n=== 完了 ===")
    print(f"入力: {total_in:,}行 → 出力: {total_out:,}行")
    print(f"海況ヒット: {weather_hit:,}行 ({weather_hit/total_out*100:.1f}%)" if total_out else "")
    print(f"潮汐ヒット: {tide_hit:,}行 ({tide_hit/total_out*100:.1f}%)" if total_out else "")
    print(f"enriched_catches.csv: {size_mb:.1f} MB")


if __name__ == "__main__":
    main()
