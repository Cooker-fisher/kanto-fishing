#!/usr/bin/env python3
"""
釣果×気象データ結合スクリプト join_catch_weather.py

catches.json × weather_data/{area}_history.csv を
日付・エリアでJOINして analysis/catch_weather.csv に出力する。

出力カラム:
  date, ship, area, weather_area, fish, count_min, count_max, count_avg,
  size_min, size_max, weight_min, weight_max,
  wave_height, wave_period, swell_height,
  wind_speed, wind_dir, temp, sea_surface_temp,
  flood1, flood1_cm, flood2, flood2_cm,
  ebb1, ebb1_cm, ebb2, ebb2_cm,
  tide_range, tide_type, moon_age
"""
import json, csv, os, sys
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8")

BASE_DIR      = os.path.dirname(os.path.abspath(__file__))
CATCHES_FILE  = os.path.join(BASE_DIR, "catches.json")
MAP_FILE      = os.path.join(BASE_DIR, "area_weather_map.json")
WEATHER_DIR   = os.path.join(BASE_DIR, "weather_data")
OUTPUT_DIR    = os.path.join(BASE_DIR, "analysis")
OUTPUT_FILE   = os.path.join(OUTPUT_DIR, "catch_weather.csv")

OUTPUT_HEADER = [
    "date", "ship", "area", "weather_area", "fish",
    "count_min", "count_max", "count_avg",
    "size_min", "size_max", "weight_min", "weight_max",
    "wave_height", "wave_period", "swell_height",
    "wind_speed", "wind_dir", "temp", "sea_surface_temp",
    "flood1", "flood1_cm", "flood2", "flood2_cm",
    "ebb1", "ebb1_cm", "ebb2", "ebb2_cm",
    "tide_range", "tide_type", "moon_age",
]


def load_weather_index():
    """weather_data/{area}_history.csv を読み込んで {area: {date: row}} の辞書を返す。"""
    index = {}
    for fname in os.listdir(WEATHER_DIR):
        if not fname.endswith("_history.csv"):
            continue
        area_code = fname.replace("_history.csv", "")
        path = os.path.join(WEATHER_DIR, fname)
        index[area_code] = {}
        with open(path, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                index[area_code][row["date"]] = row
    return index


def normalize_date(date_str):
    """'2026/03/15' → '2026-03-15'"""
    return date_str.replace("/", "-") if date_str else ""


def main():
    # データ読み込み
    with open(CATCHES_FILE, encoding="utf-8") as f:
        catches = json.load(f)["data"]

    with open(MAP_FILE, encoding="utf-8") as f:
        area_map = json.load(f)

    weather = load_weather_index()

    print(f"釣果レコード: {len(catches)}件")
    print(f"気象エリア:   {list(weather.keys())}")

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    joined = 0
    no_weather = 0
    rows = []

    for c in catches:
        date_norm = normalize_date(c.get("date", ""))
        area      = c.get("area", "")
        weather_area = area_map.get(area)

        # 気象データ取得
        w = {}
        if weather_area and date_norm:
            w = weather.get(weather_area, {}).get(date_norm, {})

        if w:
            joined += 1
        else:
            no_weather += 1

        # 魚種は複数あることがある → 1魚種1行に展開
        fish_list = c.get("fish", [])
        if not fish_list:
            fish_list = ["不明"]

        cr = c.get("count_range", {}) or {}
        sr = c.get("size_range",  {}) or {}
        wr_data = c.get("weight_range", {}) or {}

        for fish in fish_list:
            row = {
                "date":         date_norm,
                "ship":         c.get("ship", ""),
                "area":         area,
                "weather_area": weather_area or "",
                "fish":         fish,
                "count_min":    cr.get("min", ""),
                "count_max":    cr.get("max", ""),
                "count_avg":    c.get("count_avg", ""),
                "size_min":     sr.get("min", ""),
                "size_max":     sr.get("max", ""),
                "weight_min":   wr_data.get("min", ""),
                "weight_max":   wr_data.get("max", ""),
                # 気象（なければ空欄）
                "wave_height":      w.get("wave_height",      ""),
                "wave_period":      w.get("wave_period",      ""),
                "swell_height":     w.get("swell_height",     ""),
                "wind_speed":       w.get("wind_speed",       ""),
                "wind_dir":         w.get("wind_dir",         ""),
                "temp":             w.get("temp",             ""),
                "sea_surface_temp": w.get("sea_surface_temp", ""),
                "flood1":           w.get("flood1",           ""),
                "flood1_cm":        w.get("flood1_cm",        ""),
                "flood2":           w.get("flood2",           ""),
                "flood2_cm":        w.get("flood2_cm",        ""),
                "ebb1":             w.get("ebb1",             ""),
                "ebb1_cm":          w.get("ebb1_cm",          ""),
                "ebb2":             w.get("ebb2",             ""),
                "ebb2_cm":          w.get("ebb2_cm",          ""),
                "tide_range":       w.get("tide_range",       ""),
                "tide_type":        w.get("tide_type",        ""),
                "moon_age":         w.get("moon_age",         ""),
            }
            rows.append(row)

    with open(OUTPUT_FILE, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=OUTPUT_HEADER)
        w.writeheader()
        w.writerows(rows)

    print(f"\n結合結果:")
    print(f"  気象データあり: {joined}件")
    print(f"  気象データなし: {no_weather}件")
    print(f"  出力行数:       {len(rows)}行（1魚種1行に展開）")
    print(f"  → {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
