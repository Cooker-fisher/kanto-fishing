#!/usr/bin/env python3
"""
過去気象データ一括取得スクリプト weather_history.py

catches.json に含まれる日付×エリアの組み合わせに対し、
過去の気象・波浪・潮汐データを取得して
weather_data/{area}_history.csv に保存する。

[データソース]
- Open-Meteo Historical Weather: 風速・風向・気温
  URL: https://archive-api.open-meteo.com/v1/archive
- Open-Meteo Marine Historical: 波高・波周期・うねり・海面水温
  URL: https://marine-api.open-meteo.com/v1/marine (start_date/end_date 指定)
- tide736.net: 満干潮時刻・大潮小潮・月齢
  URL: https://tide736.net/api/get_tide.php?pc={pc}&hc={hc}&yr=...

[時刻]
  06:00 JST の値を使用（出船時刻帯）

[実行方法]
  python weather_history.py
  python weather_history.py --start 2025-01-01 --end 2026-03-25  # 期間指定
"""
import json, os, csv, time, sys, re
from datetime import datetime, date, timedelta
from urllib.request import urlopen, Request
from urllib.error import URLError

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Safari/537.36"

# ── 海域設定（weather_crawl.py と同じ） ───────────────────────────────
SEA_AREAS = {
    "tokyo_bay": {
        "name":      "東京湾",
        "lat":       35.3, "lon": 139.7,
        "tide_pc":   13,   "tide_hc": "0001",
    },
    "sagami_bay": {
        "name":      "相模湾",
        "lat":       35.0, "lon": 139.4,
        "tide_pc":   14,   "tide_hc": "0015",
    },
    "outer_boso": {
        "name":      "外房",
        "lat":       35.4, "lon": 140.6,
        "tide_pc":   12,   "tide_hc": "0005",
    },
    "ibaraki": {
        "name":      "茨城沖",
        "lat":       36.2, "lon": 140.7,
        "tide_pc":   8,    "tide_hc": "0005",
    },
}

CSV_HEADER = ["date", "wave_height", "wave_period", "swell_height",
              "wind_speed", "wind_dir", "temp", "sea_surface_temp",
              "pressure",
              "flood1", "flood1_cm", "flood2", "flood2_cm",
              "ebb1", "ebb1_cm", "ebb2", "ebb2_cm",
              "tide_range", "tide_type", "moon_age",
              "area"]


def fetch(url, retries=2):
    for attempt in range(retries + 1):
        try:
            req = Request(url, headers={"User-Agent": USER_AGENT})
            with urlopen(req, timeout=30) as r:
                return r.read().decode("utf-8", errors="replace")
        except URLError as e:
            if attempt < retries:
                time.sleep(2)
            else:
                print(f"  fetch error [{url[:80]}]: {e}")
    return None


# ── 日付範囲の収集 ────────────────────────────────────────────────────

def load_date_range_from_catches():
    """catches.json から日付範囲（start, end）を取得する。"""
    with open("catches.json", encoding="utf-8") as f:
        data = json.load(f)
    dates = [datetime.strptime(d["date"], "%Y/%m/%d").date()
             for d in data["data"] if d.get("date")]
    return min(dates), max(dates)


# ── Open-Meteo Historical Weather ────────────────────────────────────

def fetch_openmeteo_weather(lat, lon, start_date, end_date):
    """
    風速・風向・気温を日付→06:00JSTの値でdict返却。
    戻り値: {date_str: {"wind_speed": x, "wind_dir": x, "temp": x}}
    """
    url = (
        "https://archive-api.open-meteo.com/v1/archive"
        f"?latitude={lat}&longitude={lon}"
        "&hourly=wind_speed_10m,wind_direction_10m,temperature_2m,surface_pressure"
        f"&start_date={start_date}&end_date={end_date}"
        "&timezone=Asia/Tokyo&wind_speed_unit=ms"
    )
    txt = fetch(url)
    if not txt:
        return {}
    try:
        data = json.loads(txt)
        times     = data["hourly"]["time"]
        speeds    = data["hourly"]["wind_speed_10m"]
        dirs      = data["hourly"]["wind_direction_10m"]
        temps     = data["hourly"]["temperature_2m"]
        pressures = data["hourly"]["surface_pressure"]
        result = {}
        for i, t in enumerate(times):
            if t.endswith("T06:00"):
                d = t[:10]
                result[d] = {
                    "wind_speed": round(speeds[i], 1)    if speeds[i]    is not None else "",
                    "wind_dir":   round(dirs[i])          if dirs[i]      is not None else "",
                    "temp":       round(temps[i], 1)      if temps[i]     is not None else "",
                    "pressure":   round(pressures[i], 1) if pressures[i] is not None else "",
                }
        return result
    except Exception as e:
        print(f"  Open-Meteo Weather parse error: {e}")
        return {}


# ── Open-Meteo Marine Historical ─────────────────────────────────────

def fetch_openmeteo_marine(lat, lon, start_date, end_date):
    """
    波高・波周期・うねり・海面水温を日付→06:00JSTの値でdict返却。
    戻り値: {date_str: {"wave_height": x, ...}}
    """
    url = (
        "https://marine-api.open-meteo.com/v1/marine"
        f"?latitude={lat}&longitude={lon}"
        "&hourly=wave_height,wave_period,swell_wave_height,sea_surface_temperature"
        f"&start_date={start_date}&end_date={end_date}"
        "&timezone=Asia/Tokyo"
    )
    txt = fetch(url)
    if not txt:
        return {}
    try:
        data = json.loads(txt)
        times  = data["hourly"]["time"]
        wh     = data["hourly"]["wave_height"]
        wp     = data["hourly"]["wave_period"]
        sw     = data["hourly"]["swell_wave_height"]
        sst    = data["hourly"]["sea_surface_temperature"]
        result = {}
        for i, t in enumerate(times):
            if t.endswith("T06:00"):
                d = t[:10]
                def _r(v, n=2): return round(v, n) if v is not None else ""
                result[d] = {
                    "wave_height":      _r(wh[i]),
                    "wave_period":      _r(wp[i]),
                    "swell_height":     _r(sw[i]),
                    "sea_surface_temp": _r(sst[i], 1),
                }
        return result
    except Exception as e:
        print(f"  Open-Meteo Marine parse error: {e}")
        return {}


# ── tide736.net（満干潮・大潮小潮・月齢） ────────────────────────────

def fetch_tide_day(pc, hc, yr, mn, dy):
    """1日分の潮汐データを取得して dict 返却。"""
    url = (
        f"https://tide736.net/api/get_tide.php"
        f"?pc={pc}&hc={hc}&yr={yr}&mn={mn:02d}&dy={dy:02d}&rg=day"
    )
    txt = fetch(url)
    if not txt:
        return {}
    try:
        data = json.loads(txt)
        date_key = f"{yr}-{mn:02d}-{dy:02d}"
        day    = data["tide"]["chart"][date_key]
        floods = day.get("flood", [])
        ebbs   = day.get("edd",   [])
        moon   = day.get("moon",  {})

        def _t(lst, i): return lst[i]["time"] if len(lst) > i else ""
        def _c(lst, i): return lst[i]["cm"]   if len(lst) > i else ""

        flood_cms = [f["cm"] for f in floods if f.get("cm") is not None]
        ebb_cms   = [e["cm"] for e in ebbs   if e.get("cm") is not None]
        tide_range = round(max(flood_cms) - min(ebb_cms), 1) if flood_cms and ebb_cms else ""

        return {
            "flood1": _t(floods, 0), "flood1_cm": _c(floods, 0),
            "flood2": _t(floods, 1), "flood2_cm": _c(floods, 1),
            "ebb1":   _t(ebbs,   0), "ebb1_cm":   _c(ebbs,   0),
            "ebb2":   _t(ebbs,   1), "ebb2_cm":   _c(ebbs,   1),
            "tide_range": tide_range,
            "tide_type":  moon.get("title", ""),
            "moon_age":   moon.get("age",   ""),
        }
    except Exception as e:
        print(f"  tide736 parse error ({yr}/{mn}/{dy}): {e}")
        return {}


# ── CSV保存 ─────────────────────────────────────────────────────────────

def save_history_csv(area_code, rows, area_name):
    os.makedirs("weather_data", exist_ok=True)
    path = os.path.join("weather_data", f"{area_code}_history.csv")
    # 既存データを読み込んで重複日をスキップ
    existing_dates = set()
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                existing_dates.add(row["date"])
    new_rows = [r for r in rows if r["date"] not in existing_dates]
    if not new_rows:
        print(f"  スキップ（すべて取得済み）")
        return 0
    write_header = not os.path.exists(path)
    with open(path, "a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_HEADER)
        if write_header:
            w.writeheader()
        w.writerows(new_rows)
    return len(new_rows)


# ── メイン ───────────────────────────────────────────────────────────────

def main():
    # 期間の決定
    if "--start" in sys.argv and "--end" in sys.argv:
        si = sys.argv.index("--start")
        ei = sys.argv.index("--end")
        start = date.fromisoformat(sys.argv[si + 1])
        end   = date.fromisoformat(sys.argv[ei + 1])
    else:
        start, end = load_date_range_from_catches()

    start_str = start.isoformat()
    end_str   = end.isoformat()
    days = (end - start).days + 1

    print(f"=== weather_history.py 開始 ===")
    print(f"期間: {start_str} 〜 {end_str} ({days}日間)")
    print(f"エリア: {len(SEA_AREAS)}海域")
    print()

    for area_code, area in SEA_AREAS.items():
        print(f"[{area['name']}] 取得中...")

        # Open-Meteo Weather（1回で全期間）
        print(f"  気象データ取得中...")
        weather = fetch_openmeteo_weather(area["lat"], area["lon"], start_str, end_str)
        print(f"  → {len(weather)}日分")
        time.sleep(0.5)

        # Open-Meteo Marine（1回で全期間）
        print(f"  波浪・水温データ取得中...")
        marine = fetch_openmeteo_marine(area["lat"], area["lon"], start_str, end_str)
        print(f"  → {len(marine)}日分")
        time.sleep(0.5)

        # tide736.net（1日ずつ）
        print(f"  潮汐データ取得中（{days}日分）...")
        tides = {}
        cur = start
        while cur <= end:
            d_str = cur.isoformat()
            tp = fetch_tide_day(area["tide_pc"], area["tide_hc"],
                                cur.year, cur.month, cur.day)
            tides[d_str] = tp
            cur += timedelta(days=1)
            time.sleep(0.3)
        print(f"  → {len(tides)}日分")

        # 行を組み立て
        rows = []
        cur = start
        while cur <= end:
            d_str = cur.isoformat()
            w  = weather.get(d_str, {})
            m  = marine.get(d_str, {})
            tp = tides.get(d_str, {})
            row = {
                "date":             d_str,
                "wave_height":      m.get("wave_height",      ""),
                "wave_period":      m.get("wave_period",      ""),
                "swell_height":     m.get("swell_height",     ""),
                "wind_speed":       w.get("wind_speed",       ""),
                "wind_dir":         w.get("wind_dir",         ""),
                "temp":             w.get("temp",             ""),
                "sea_surface_temp": m.get("sea_surface_temp", ""),
                "pressure":         w.get("pressure",         ""),
                "flood1":           tp.get("flood1",          ""),
                "flood1_cm":        tp.get("flood1_cm",       ""),
                "flood2":           tp.get("flood2",          ""),
                "flood2_cm":        tp.get("flood2_cm",       ""),
                "ebb1":             tp.get("ebb1",            ""),
                "ebb1_cm":          tp.get("ebb1_cm",         ""),
                "ebb2":             tp.get("ebb2",            ""),
                "ebb2_cm":          tp.get("ebb2_cm",         ""),
                "tide_range":       tp.get("tide_range",      ""),
                "tide_type":        tp.get("tide_type",       ""),
                "moon_age":         tp.get("moon_age",        ""),
                "area":             area["name"],
            }
            rows.append(row)
            cur += timedelta(days=1)

        n = save_history_csv(area_code, rows, area["name"])
        print(f"  → weather_data/{area_code}_history.csv に{n}行追加")
        print()

    print("=== 完了 ===")


if __name__ == "__main__":
    main()
