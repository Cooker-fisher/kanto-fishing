#!/usr/bin/env python3
"""
generate_weather_history.py
weather/*.csv + tide/*.csv + moon.csv → weather_data/{area}_history.csv (過去分を補完)

既存の _history.csv は上書きせず、足りない日付だけ追記する。
"""
import csv, os, sys
from collections import defaultdict

sys.stdout.reconfigure(encoding="utf-8")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# エリアコード → 代表ポイント（weather/*.csv の point 値）
AREA_POINT = {
    "tokyo_bay":  "八景沖",
    "sagami_bay": "城ヶ島沖",
    "outer_boso": "大原沖",
    "ibaraki":    "鹿島沖",
}

# エリアコード → 潮汐港（tide/*.csv の port 値）
AREA_TIDE_PORT = {
    "tokyo_bay":  "羽田",
    "sagami_bay": "横須賀",
    "outer_boso": "銚子",
    "ibaraki":    "鹿島",
}

# エリアコード → 表示名（area フィールド用）
AREA_LABEL = {
    "tokyo_bay":  "東京湾",
    "sagami_bay": "相模湾",
    "outer_boso": "外房",
    "ibaraki":    "茨城",
}

HISTORY_COLS = [
    "date", "wave_height", "wave_period", "swell_height",
    "wind_speed", "wind_dir", "temp", "sea_surface_temp",
    "flood1", "flood1_cm", "flood2", "flood2_cm",
    "ebb1",  "ebb1_cm",  "ebb2",  "ebb2_cm",
    "tide_range", "tide_type", "moon_age", "area",
]


def _avg(lst):
    return round(sum(lst) / len(lst), 2) if lst else None


def load_weather_daily(point):
    """weather/*.csv から指定ポイントの日別平均（6-15時）を返す"""
    wx_dir = os.path.join(BASE_DIR, "weather")
    daily = {}  # date -> {wave, wave_period, wind_speed, wind_dir, sst}
    raw = defaultdict(lambda: defaultdict(list))

    for fname in sorted(os.listdir(wx_dir)):
        if not fname.endswith(".csv"):
            continue
        with open(os.path.join(wx_dir, fname), encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if row.get("point") != point:
                    continue
                try:
                    hr = int(row.get("hour", "0"))
                except ValueError:
                    continue
                if hr < 6 or hr > 15:
                    continue
                dt = row.get("date", "")
                if not dt:
                    continue
                for col in ("wave_height", "wave_period", "wind_speed", "wind_dir", "sst"):
                    try:
                        raw[dt][col].append(float(row[col]))
                    except (KeyError, ValueError):
                        pass

    for dt, cols in raw.items():
        daily[dt] = {
            "wave_height":    _avg(cols.get("wave_height", [])),
            "wave_period":    _avg(cols.get("wave_period", [])),
            "wind_speed":     _avg(cols.get("wind_speed", [])),
            "wind_dir":       _avg(cols.get("wind_dir", [])),
            "sea_surface_temp": _avg(cols.get("sst", [])),
        }
    return daily


def load_tide_daily(port):
    """tide/*.csv から指定港の日別潮差（6-15時 max-min）を返す"""
    tide_dir = os.path.join(BASE_DIR, "tide")
    raw = defaultdict(list)

    for fname in sorted(os.listdir(tide_dir)):
        if not fname.endswith(".csv"):
            continue
        with open(os.path.join(tide_dir, fname), encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if row.get("port") != port:
                    continue
                try:
                    hr = int(row.get("hour", "0"))
                except ValueError:
                    continue
                if hr < 6 or hr > 15:
                    continue
                dt = row.get("date", "")
                try:
                    raw[dt].append(float(row["tide_cm"]))
                except (KeyError, ValueError):
                    pass

    result = {}
    for dt, vals in raw.items():
        if len(vals) >= 2:
            result[dt] = round(max(vals) - min(vals), 1)
    return result


def load_moon():
    """moon.csv → {date: {moon_age, moon_title}}"""
    path = os.path.join(BASE_DIR, "moon.csv")
    result = {}
    if not os.path.exists(path):
        return result
    with open(path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            result[row["date"]] = {
                "moon_age":   row.get("moon_age", ""),
                "tide_type":  row.get("moon_title", ""),
            }
    return result


def load_existing_dates(area_code):
    """既存 _history.csv の日付セットを返す"""
    path = os.path.join(BASE_DIR, "weather_data", f"{area_code}_history.csv")
    if not os.path.exists(path):
        return set()
    with open(path, encoding="utf-8") as f:
        return {row["date"] for row in csv.DictReader(f)}


def generate(area_code):
    point = AREA_POINT[area_code]
    port  = AREA_TIDE_PORT[area_code]
    label = AREA_LABEL[area_code]

    print(f"\n[{area_code}] point={point}, port={port}")

    wx    = load_weather_daily(point)
    tide  = load_tide_daily(port)
    moon  = load_moon()

    existing = load_existing_dates(area_code)
    print(f"  既存: {len(existing)}日, weather: {len(wx)}日, tide: {len(tide)}日, moon: {len(moon)}日")

    # 対象日付: weather にある日 - 既存
    target_dates = sorted(set(wx.keys()) - existing)
    print(f"  新規追加対象: {len(target_dates)}日")
    if not target_dates:
        print("  → 追加不要")
        return 0

    out_path = os.path.join(BASE_DIR, "weather_data", f"{area_code}_history.csv")
    # 既存ファイルがあれば追記、なければ新規作成
    mode = "a" if existing else "w"
    with open(out_path, mode, encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=HISTORY_COLS)
        if not existing:
            writer.writeheader()
        for dt in target_dates:
            w = wx.get(dt, {})
            m = moon.get(dt, {})
            row = {col: "" for col in HISTORY_COLS}
            row["date"]             = dt
            row["wave_height"]      = w.get("wave_height", "") or ""
            row["wave_period"]      = w.get("wave_period", "") or ""
            row["wind_speed"]       = w.get("wind_speed", "")  or ""
            row["wind_dir"]         = w.get("wind_dir", "")    or ""
            row["sea_surface_temp"] = w.get("sea_surface_temp", "") or ""
            row["tide_range"]       = tide.get(dt, "")
            row["tide_type"]        = m.get("tide_type", "")
            row["moon_age"]         = m.get("moon_age", "")
            row["area"]             = label
            writer.writerow(row)

    print(f"  → {len(target_dates)}件追記: {out_path}")
    return len(target_dates)


def main():
    total = 0
    for area_code in AREA_POINT:
        total += generate(area_code)
    print(f"\n完了: 合計 {total} 件追加")


if __name__ == "__main__":
    main()
