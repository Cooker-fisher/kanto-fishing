#!/usr/bin/env python3
"""
weather_forecast.py — Open-Meteo から7日間予報を取得→forecast_cache.sqlite に保存

[取得データ]
  気象: 風速・風向・気温・気圧（Open-Meteo Forecast API）
  海象: 波高・波周期・うねり・水温（Open-Meteo Marine API）

[代表座標]
  weather_cache.sqlite の全153座標を利用
  ※ area列 = "lat_lon" 形式（例: "35.6_139.8"）

[使い方]
  python weather_forecast.py        # 毎日実行（crawl.ymlから呼ばれる）
"""
import json, os, sqlite3, time, urllib.request, urllib.parse
from datetime import datetime

BASE_DIR  = os.path.dirname(os.path.abspath(__file__))
DB_PATH   = os.path.join(BASE_DIR, "forecast_cache.sqlite")
DB_CACHE  = os.path.join(BASE_DIR, "weather_cache.sqlite")

FORECAST_DAYS = 8   # 今日+7日
FETCH_HOUR    = "06:00"  # 出船時刻帯

def load_coords():
    """weather_cache.sqlite の全153座標を取得"""
    conn = sqlite3.connect(DB_CACHE)
    coords = conn.execute(
        "SELECT DISTINCT lat, lon FROM weather ORDER BY lat, lon"
    ).fetchall()
    conn.close()
    return coords  # [(lat, lon), ...]

def init_db(conn):
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS forecast (
        area          TEXT,
        lat           REAL,
        lon           REAL,
        date          TEXT,
        wind_speed    REAL,
        wind_dir      REAL,
        temp          REAL,
        pressure      REAL,
        wave_height   REAL,
        wave_period   REAL,
        swell_height  REAL,
        sst           REAL,
        updated_at    TEXT,
        precipitation REAL,
        PRIMARY KEY (area, date)
    );
    """)
    try:
        conn.execute("ALTER TABLE forecast ADD COLUMN precipitation REAL")
    except Exception:
        pass
    conn.commit()

def fetch(url, retries=3):
    for i in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                return json.loads(r.read())
        except Exception as e:
            if i == retries - 1:
                print(f"  fetch失敗: {e}")
                return None
            time.sleep(2)

def get_wx_forecast(lat, lon):
    """Open-Meteo Forecast API → 日別気象予報"""
    params = {
        "latitude": lat, "longitude": lon,
        "hourly": "wind_speed_10m,wind_direction_10m,temperature_2m,surface_pressure,precipitation",
        "forecast_days": FORECAST_DAYS,
        "timezone": "Asia/Tokyo",
        "wind_speed_unit": "ms",
    }
    url = "https://api.open-meteo.com/v1/forecast?" + urllib.parse.urlencode(params)
    data = fetch(url)
    if not data:
        return {}
    times = data["hourly"]["time"]
    result = {}
    for i, t in enumerate(times):
        if not t.endswith(FETCH_HOUR):
            continue
        d = t[:10]
        result[d] = {
            "wind_speed":   data["hourly"]["wind_speed_10m"][i],
            "wind_dir":     data["hourly"]["wind_direction_10m"][i],
            "temp":         data["hourly"]["temperature_2m"][i],
            "pressure":     data["hourly"]["surface_pressure"][i],
            "precipitation": data["hourly"]["precipitation"][i],
        }
    return result

def get_marine_forecast(lat, lon):
    """Open-Meteo Marine API → 日別海象予報"""
    params = {
        "latitude": lat, "longitude": lon,
        "hourly": "wave_height,wave_period,swell_wave_height,sea_surface_temperature",
        "forecast_days": FORECAST_DAYS,
        "timezone": "Asia/Tokyo",
    }
    url = "https://marine-api.open-meteo.com/v1/marine?" + urllib.parse.urlencode(params)
    data = fetch(url)
    if not data:
        return {}
    times = data["hourly"]["time"]
    result = {}
    for i, t in enumerate(times):
        if not t.endswith(FETCH_HOUR):
            continue
        d = t[:10]
        result[d] = {
            "wave_height":  data["hourly"]["wave_height"][i],
            "wave_period":  data["hourly"]["wave_period"][i],
            "swell_height": data["hourly"]["swell_wave_height"][i],
            "sst":          data["hourly"]["sea_surface_temperature"][i],
        }
    return result

def main():
    print("=== weather_forecast.py 開始 ===")
    coords = load_coords()
    print(f"取得座標数: {len(coords)}件")

    conn = sqlite3.connect(DB_PATH)
    init_db(conn)
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    saved = 0
    errors = 0

    for idx, (lat, lon) in enumerate(coords, 1):
        area = f"{lat}_{lon}"
        print(f"  [{idx:3d}/{len(coords)}] ({lat},{lon})...", end=" ", flush=True)
        wx  = get_wx_forecast(lat, lon)
        mar = get_marine_forecast(lat, lon)
        dates = sorted(set(wx) | set(mar))
        if not dates:
            print("データなし")
            errors += 1
            continue
        for d in dates:
            row = wx.get(d, {})
            row.update(mar.get(d, {}))
            conn.execute("""
                INSERT OR REPLACE INTO forecast VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                area, lat, lon, d,
                row.get("wind_speed"), row.get("wind_dir"),
                row.get("temp"),       row.get("pressure"),
                row.get("wave_height"),row.get("wave_period"),
                row.get("swell_height"),row.get("sst"),
                now_str,
                row.get("precipitation"),
            ))
            saved += 1
        print(f"{len(dates)}日分")
        time.sleep(0.5)  # API負荷対策

    conn.commit()
    conn.close()
    print(f"保存: {saved}件 ({errors}座標エラー) → {DB_PATH}")

if __name__ == "__main__":
    main()
