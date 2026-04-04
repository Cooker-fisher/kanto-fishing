#!/usr/bin/env python3
"""
rebuild_weather_cache.py — weather_cache.sqlite を Open-Meteo から全件再取得

[データソース]
  Open-Meteo Archive API  → wind_speed, wind_dir, temp, pressure, precipitation
  Open-Meteo Marine API   → wave_height, wave_period, swell_height, sst

[対象座標]
  area_coords.json の58エリア

[期間]
  2023-01-01 〜 今日

[出力]
  weather_cache.sqlite（3時間ごと × 58エリア × 3年 ≒ 50万行）

[使い方]
  python rebuild_weather_cache.py          # 全エリア取得（約30分）
  python rebuild_weather_cache.py --test   # 最初の3エリアのみテスト
  python rebuild_weather_cache.py --resume # 未取得エリアのみ取得（再開）
"""

import json, os, sqlite3, sys, time
from datetime import datetime, timedelta
from urllib.request import urlopen, Request
from urllib.error import URLError

sys.stdout.reconfigure(encoding="utf-8")

BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
DB_PATH     = os.path.join(BASE_DIR, "weather_cache.sqlite")
AREA_FILE   = os.path.join(BASE_DIR, "area_coords.json")
POINT_FILE  = os.path.join(BASE_DIR, "point_coords.json")

START_DATE = "2023-01-01"
END_DATE   = datetime.today().strftime("%Y-%m-%d")

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
MARINE_URL  = "https://marine-api.open-meteo.com/v1/marine"
UA = "Mozilla/5.0 (compatible; funatsuri-yoso-rebuild/1.0)"


def fetch(url, retries=5):
    for i in range(retries):
        try:
            req = Request(url, headers={"User-Agent": UA})
            with urlopen(req, timeout=90) as r:
                return json.loads(r.read())
        except (URLError, OSError, json.JSONDecodeError) as e:
            print(f"  fetch error ({i+1}/{retries}): {e}")
            if i < retries - 1:
                time.sleep(5 * (i + 1))
    return None


def fetch_weather(lat, lon, start, end):
    """Open-Meteo Archive → 気象データ（3時間ごと）"""
    url = (
        f"{ARCHIVE_URL}?latitude={lat}&longitude={lon}"
        f"&start_date={start}&end_date={end}"
        f"&hourly=wind_speed_10m,wind_direction_10m,temperature_2m,"
        f"surface_pressure,precipitation"
        f"&timezone=Asia%2FTokyo"
    )
    data = fetch(url)
    if not data:
        return {}
    hourly = data.get("hourly", {})
    times  = hourly.get("time", [])
    ws     = hourly.get("wind_speed_10m", [])
    wd     = hourly.get("wind_direction_10m", [])
    tp     = hourly.get("temperature_2m", [])
    pr     = hourly.get("surface_pressure", [])
    pc     = hourly.get("precipitation", [])

    result = {}
    for i, t in enumerate(times):
        hour = int(t[11:13]) if len(t) >= 13 else -1
        if hour % 3 != 0:
            continue
        dt = t[:16]  # "2023-01-01T06:00"
        result[dt] = {
            "wind_speed":  ws[i]  if i < len(ws)  else None,
            "wind_dir":    wd[i]  if i < len(wd)  else None,
            "temp":        tp[i]  if i < len(tp)  else None,
            "pressure":    pr[i]  if i < len(pr)  else None,
            "precipitation": pc[i] if i < len(pc) else None,
        }
    return result


def fetch_marine(lat, lon, start, end):
    """Open-Meteo Marine → 海況データ（3時間ごと）"""
    url = (
        f"{MARINE_URL}?latitude={lat}&longitude={lon}"
        f"&start_date={start}&end_date={end}"
        f"&hourly=wave_height,wave_period,swell_wave_height,sea_surface_temperature"
        f"&timezone=Asia%2FTokyo"
    )
    data = fetch(url)
    if not data:
        return {}
    hourly = data.get("hourly", {})
    times  = hourly.get("time", [])
    wh     = hourly.get("wave_height", [])
    wp     = hourly.get("wave_period", [])
    sw     = hourly.get("swell_wave_height", [])
    st     = hourly.get("sea_surface_temperature", [])

    result = {}
    for i, t in enumerate(times):
        hour = int(t[11:13]) if len(t) >= 13 else -1
        if hour % 3 != 0:
            continue
        dt = t[:16]
        result[dt] = {
            "wave_height":  wh[i] if i < len(wh) else None,
            "wave_period":  wp[i] if i < len(wp) else None,
            "swell_height": sw[i] if i < len(sw) else None,
            "sst":          st[i] if i < len(st) else None,
        }
    return result


def init_db(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS weather (
            lat          REAL,
            lon          REAL,
            dt           TEXT,
            wind_speed   REAL,
            wind_dir     REAL,
            temp         REAL,
            pressure     REAL,
            wave_height  REAL,
            wave_period  REAL,
            swell_height REAL,
            sst          REAL,
            precipitation REAL,
            PRIMARY KEY (lat, lon, dt)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_wx_latlon ON weather(lat, lon)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_wx_dt    ON weather(dt)")
    conn.commit()


def already_fetched(conn, lat, lon):
    """この座標のデータが1行でも存在するか"""
    r = conn.execute(
        "SELECT COUNT(*) FROM weather WHERE lat=? AND lon=?", (lat, lon)
    ).fetchone()
    return r[0] > 0


def upsert_rows(conn, lat, lon, wx_dict, ma_dict):
    """気象+海況を結合してDBにUPSERT"""
    all_dts = sorted(set(wx_dict) | set(ma_dict))
    rows = []
    for dt in all_dts:
        wx = wx_dict.get(dt, {})
        ma = ma_dict.get(dt, {})
        rows.append((
            lat, lon, dt,
            wx.get("wind_speed"),
            wx.get("wind_dir"),
            wx.get("temp"),
            wx.get("pressure"),
            ma.get("wave_height"),
            ma.get("wave_period"),
            ma.get("swell_height"),
            ma.get("sst"),
            wx.get("precipitation"),
        ))
    conn.executemany("""
        INSERT OR REPLACE INTO weather
        (lat, lon, dt, wind_speed, wind_dir, temp, pressure,
         wave_height, wave_period, swell_height, sst, precipitation)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
    """, rows)
    conn.commit()
    return len(rows)


def main():
    test_mode   = "--test"   in sys.argv
    resume_mode = "--resume" in sys.argv

    # point_coords.json（152座標）+ area_coords.json（フォールバック）を結合
    unique_coords = {}

    # 1. point_coords.json（実際の釣り場ポイント座標）
    with open(POINT_FILE, encoding="utf-8") as f:
        point_coords = json.load(f)
    for name, v in point_coords.items():
        lat = v.get("lat")
        lon = v.get("lon")
        if lat and lon:
            key = (round(float(lat), 2), round(float(lon), 2))
            if key not in unique_coords:
                unique_coords[key] = name

    # 2. area_coords.json（フォールバック用エリア代表座標）
    with open(AREA_FILE, encoding="utf-8") as f:
        area_coords = json.load(f)
    for area, v in area_coords.items():
        lat = v.get("lat")
        lon = v.get("lon")
        if lat and lon:
            key = (round(float(lat), 2), round(float(lon), 2))
            if key not in unique_coords:
                unique_coords[key] = f"[エリア]{area}"

    coords = list(unique_coords.items())  # [((lat,lon), name), ...]
    if test_mode:
        coords = coords[:3]
        print(f"=== テストモード（{len(coords)}座標） ===")
    else:
        print(f"=== weather_cache.sqlite 再構築（{len(coords)}座標）===")
        print(f"  期間: {START_DATE} 〜 {END_DATE}")
        print(f"  出力: {DB_PATH}")

    conn = sqlite3.connect(DB_PATH)
    init_db(conn)

    total_rows = 0
    failed = []

    for idx, ((lat, lon), area_name) in enumerate(coords, 1):
        if resume_mode and already_fetched(conn, lat, lon):
            print(f"  [{idx}/{len(coords)}] ({lat},{lon}) {area_name} → スキップ（取得済み）")
            continue

        print(f"  [{idx}/{len(coords)}] ({lat},{lon}) {area_name}", end=" ... ", flush=True)

        wx = fetch_weather(lat, lon, START_DATE, END_DATE)
        time.sleep(0.8)
        ma = fetch_marine(lat, lon, START_DATE, END_DATE)
        time.sleep(0.8)

        if not wx and not ma:
            print("データ取得失敗")
            failed.append((lat, lon, area_name))
            continue

        n = upsert_rows(conn, lat, lon, wx, ma)
        total_rows += n
        print(f"{n}行")

    conn.close()

    print(f"\n=== 完了: {total_rows:,}行 ===")
    if failed:
        print(f"失敗 {len(failed)}座標:")
        for lat, lon, name in failed:
            print(f"  ({lat},{lon}) {name}")


if __name__ == "__main__":
    main()
