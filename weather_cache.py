#!/usr/bin/env python3
"""
weather_cache.py — 海況データ一括取得・SQLiteキャッシュ

[データソース]
  Open-Meteo Historical Weather API : 風・気温・気圧・天気コード（3時間ごと）
  Open-Meteo Marine API             : 波・うねり・水温・海流（3時間ごと）
  tide736.net                       : 満干潮・大中小潮・月齢（1日1回・港別）

[出力] weather_cache.sqlite
  weather テーブル: 3時間ごと × ユニーク座標（153件）
  tide    テーブル: 1日1回   × 潮位港（5港）

[使い方]
  python weather_cache.py           # 差分取得（初回は2023-01-01〜昨日）
  python weather_cache.py --full    # 全期間強制再取得
"""

import json, math, os, sqlite3, sys, time
from datetime import date, datetime, timedelta
from urllib.request import urlopen, Request
from urllib.error import URLError

BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
DB_PATH    = os.path.join(BASE_DIR, "weather_cache.sqlite")
DATA_START = "2023-01-01"

# ── 潮位港（座標から最寄り港を自動割り当て） ─────────────────────────────
TIDE_PORTS = {
    "ibaraki":    {"pc": 8,  "hc": "0005", "name": "大洗",  "lat": 36.32, "lon": 140.57},
    "outer_boso": {"pc": 12, "hc": "0005", "name": "勝浦",  "lat": 35.14, "lon": 140.30},
    "tokyo_bay":  {"pc": 13, "hc": "0001", "name": "築地",  "lat": 35.66, "lon": 139.78},
    "sagami_bay": {"pc": 14, "hc": "0015", "name": "諸磯",  "lat": 35.16, "lon": 139.61},
    "shizuoka":   {"pc": 22, "hc": "0013", "name": "御前崎", "lat": 34.60, "lon": 138.22},
}

def coord_to_port(lat, lon):
    """最寄り潮位港コードを返す。"""
    best, best_dist = None, float("inf")
    for code, p in TIDE_PORTS.items():
        d = math.hypot(lat - p["lat"], lon - p["lon"])
        if d < best_dist:
            best_dist = d
            best = code
    return best


# ── HTTP ──────────────────────────────────────────────────────────────────
UA = "Mozilla/5.0 (compatible; funatsuri-yoso/1.0)"

def fetch(url, retries=5):
    for i in range(retries):
        try:
            req = Request(url, headers={"User-Agent": UA})
            with urlopen(req, timeout=60) as r:
                return r.read().decode("utf-8")
        except (URLError, OSError, ConnectionError) as e:
            print(f"  fetch error [{url[:80]}]: {e}")
            if i < retries - 1:
                time.sleep(3 * (i + 1))  # 3s, 6s, 9s, 12s
    return None


# ── SQLite ────────────────────────────────────────────────────────────────
def init_db(conn):
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS weather (
        lat          REAL,
        lon          REAL,
        dt           TEXT,
        wind_speed   REAL,
        wind_dir     INTEGER,
        temp         REAL,
        pressure     REAL,
        weather_code INTEGER,
        wave_height  REAL,
        wave_period  REAL,
        wave_dir     INTEGER,
        swell_height REAL,
        swell_period REAL,
        sst          REAL,
        current_spd  REAL,
        current_dir  INTEGER,
        PRIMARY KEY (lat, lon, dt)
    );
    CREATE TABLE IF NOT EXISTS tide (
        port_code  TEXT,
        date       TEXT,
        flood1     TEXT,
        flood1_cm  REAL,
        flood2     TEXT,
        flood2_cm  REAL,
        ebb1       TEXT,
        ebb1_cm    REAL,
        ebb2       TEXT,
        ebb2_cm    REAL,
        tide_range REAL,
        tide_type  TEXT,
        moon_age   REAL,
        PRIMARY KEY (port_code, date)
    );
    CREATE INDEX IF NOT EXISTS idx_weather_latlon ON weather (lat, lon);
    CREATE INDEX IF NOT EXISTS idx_weather_dt     ON weather (dt);
    CREATE INDEX IF NOT EXISTS idx_tide_date      ON tide (date);
    """)
    conn.commit()

def get_latest_weather_dt(conn, lat, lon):
    row = conn.execute(
        "SELECT MAX(dt) FROM weather WHERE lat=? AND lon=?", (lat, lon)
    ).fetchone()
    return row[0] if row and row[0] else None

def get_latest_tide_date(conn, port_code):
    row = conn.execute(
        "SELECT MAX(date) FROM tide WHERE port_code=?", (port_code,)
    ).fetchone()
    return row[0] if row and row[0] else None


# ── Open-Meteo Weather ────────────────────────────────────────────────────
WEATHER_VARS = (
    "wind_speed_10m,wind_direction_10m,"
    "temperature_2m,surface_pressure,weather_code"
)

def fetch_weather(lat, lon, start, end):
    url = (
        f"https://archive-api.open-meteo.com/v1/archive"
        f"?latitude={lat}&longitude={lon}"
        f"&start_date={start}&end_date={end}"
        f"&hourly={WEATHER_VARS}"
        f"&timezone=Asia%2FTokyo"
    )
    txt = fetch(url)
    if not txt:
        return {}
    try:
        return json.loads(txt).get("hourly", {})
    except Exception as e:
        print(f"  Weather parse error: {e}")
        return {}


# ── Open-Meteo Marine ─────────────────────────────────────────────────────
MARINE_VARS = (
    "wave_height,wave_period,wave_direction,"
    "swell_wave_height,swell_wave_period,"
    "sea_surface_temperature,"
    "ocean_current_velocity,ocean_current_direction"
)

def fetch_marine(lat, lon, start, end):
    url = (
        f"https://marine-api.open-meteo.com/v1/marine"
        f"?latitude={lat}&longitude={lon}"
        f"&start_date={start}&end_date={end}"
        f"&hourly={MARINE_VARS}"
        f"&timezone=Asia%2FTokyo"
    )
    txt = fetch(url)
    if not txt:
        return {}
    try:
        data = json.loads(txt)
        if "error" in data:
            # 沿岸浅海域など Marine API 非対応の座標はスキップ
            return {}
        return data.get("hourly", {})
    except Exception as e:
        print(f"  Marine parse error: {e}")
        return {}

def merge_and_insert_weather(conn, lat, lon, w, m):
    """Weather + Marine を3時間ごとにフィルタしてINSERT OR IGNORE。"""
    times = w.get("time") or m.get("time") or []
    if not times:
        return 0

    def g(d, key, i):
        arr = d.get(key)
        if arr and i < len(arr):
            return arr[i]
        return None

    rows = []
    for i, dt in enumerate(times):
        hour = int(dt[11:13])
        if hour % 3 != 0:
            continue
        rows.append((
            lat, lon, dt,
            g(w, "wind_speed_10m",        i),
            g(w, "wind_direction_10m",    i),
            g(w, "temperature_2m",        i),
            g(w, "surface_pressure",      i),
            g(w, "weather_code",          i),
            g(m, "wave_height",           i),
            g(m, "wave_period",           i),
            g(m, "wave_direction",        i),
            g(m, "swell_wave_height",     i),
            g(m, "swell_wave_period",     i),
            g(m, "sea_surface_temperature", i),
            g(m, "ocean_current_velocity",  i),
            g(m, "ocean_current_direction", i),
        ))

    if rows:
        conn.executemany(
            "INSERT OR IGNORE INTO weather VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            rows
        )
        conn.commit()
    return len(rows)


# ── tide736.net ───────────────────────────────────────────────────────────
def fetch_tide(port_code, date_str):
    """1日分の満干潮・月齢を取得。成功時dict、失敗時None。"""
    p = TIDE_PORTS[port_code]
    d = datetime.strptime(date_str, "%Y-%m-%d")
    url = (
        f"https://tide736.net/api/get_tide.php"
        f"?pc={p['pc']}&hc={p['hc']}"
        f"&yr={d.year}&mn={d.month:02d}&dy={d.day:02d}&rg=day"
    )
    txt = fetch(url)
    if not txt:
        return None
    try:
        data   = json.loads(txt)
        day    = data["tide"]["chart"][date_str]
        floods = day.get("flood", [])
        ebbs   = day.get("edd",   [])
        moon   = day.get("moon",  {})

        def _t(lst, i): return lst[i]["time"] if len(lst) > i else None
        def _c(lst, i): return lst[i]["cm"]   if len(lst) > i else None

        flood_cms = [f["cm"] for f in floods if f.get("cm") is not None]
        ebb_cms   = [e["cm"] for e in ebbs   if e.get("cm") is not None]
        tide_range = round(max(flood_cms) - min(ebb_cms), 1) if flood_cms and ebb_cms else None

        return {
            "port_code":  port_code,
            "date":       date_str,
            "flood1":     _t(floods, 0), "flood1_cm": _c(floods, 0),
            "flood2":     _t(floods, 1), "flood2_cm": _c(floods, 1),
            "ebb1":       _t(ebbs,   0), "ebb1_cm":   _c(ebbs,   0),
            "ebb2":       _t(ebbs,   1), "ebb2_cm":   _c(ebbs,   1),
            "tide_range": tide_range,
            "tide_type":  moon.get("title", ""),
            "moon_age":   moon.get("age",   ""),
        }
    except Exception as e:
        print(f"  tide736 parse error [{date_str}]: {e}")
        return None

def insert_tide(conn, row):
    conn.execute(
        "INSERT OR IGNORE INTO tide VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (row["port_code"], row["date"],
         row["flood1"],   row["flood1_cm"],
         row["flood2"],   row["flood2_cm"],
         row["ebb1"],     row["ebb1_cm"],
         row["ebb2"],     row["ebb2_cm"],
         row["tide_range"], row["tide_type"], row["moon_age"])
    )
    conn.commit()


# ── ユニーク座標ロード ────────────────────────────────────────────────────
def load_unique_coords():
    """point_coords.json + area_coords.json からユニーク座標を返す。"""
    coords = {}  # (lat_r, lon_r) → (lat, lon)
    for fname in ("point_coords.json", "area_coords.json"):
        path = os.path.join(BASE_DIR, fname)
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        for name, v in data.items():
            if name.startswith("_"):
                continue
            lat = v.get("lat")
            lon = v.get("lon")
            if lat is None or lon is None:
                continue
            key = (round(lat, 2), round(lon, 2))
            if key not in coords:
                coords[key] = (lat, lon)
    return list(coords.values())


# ── メイン ────────────────────────────────────────────────────────────────
def main():
    full      = "--full" in sys.argv
    yesterday = (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")

    print(f"=== weather_cache.py 開始 {'（全期間）' if full else '（差分）'} ===")
    print(f"対象期間: {DATA_START} 〜 {yesterday}")

    coords = load_unique_coords()
    print(f"ユニーク座標: {len(coords)}件")

    conn = sqlite3.connect(DB_PATH)
    init_db(conn)

    # ── Weather / Marine ──────────────────────────────────────────────────
    print(f"\n[1/2] Weather + Marine 取得")
    for i, (lat, lon) in enumerate(coords, 1):
        latest = None if full else get_latest_weather_dt(conn, lat, lon)
        if latest:
            start = (
                datetime.strptime(latest[:10], "%Y-%m-%d") + timedelta(days=1)
            ).strftime("%Y-%m-%d")
        else:
            start = DATA_START

        if start > yesterday:
            continue  # 最新状態、スキップ

        print(f"  [{i}/{len(coords)}] ({lat:.2f},{lon:.2f}) {start}〜{yesterday}", end=" ")
        w = fetch_weather(lat, lon, start, yesterday)
        time.sleep(0.3)
        m = fetch_marine(lat, lon, start, yesterday)
        time.sleep(0.3)
        n = merge_and_insert_weather(conn, lat, lon, w, m)
        print(f"→ {n}行")

    # ── Tide ──────────────────────────────────────────────────────────────
    print(f"\n[2/2] 潮汐データ取得（{len(TIDE_PORTS)}港）")
    start_d = date.fromisoformat(DATA_START)
    end_d   = date.fromisoformat(yesterday)

    for port_code, port in TIDE_PORTS.items():
        latest = None if full else get_latest_tide_date(conn, port_code)
        if latest:
            cur = date.fromisoformat(latest) + timedelta(days=1)
        else:
            cur = start_d

        count, errors = 0, 0
        while cur <= end_d:
            row = fetch_tide(port_code, cur.strftime("%Y-%m-%d"))
            if row:
                insert_tide(conn, row)
                count += 1
            else:
                errors += 1
            cur += timedelta(days=1)
            time.sleep(0.15)

        print(f"  {port['name']}: {count}日分挿入 / エラー{errors}日")

    conn.close()

    db_size = os.path.getsize(DB_PATH) / 1024 / 1024
    print(f"\n=== 完了 === weather_cache.sqlite: {db_size:.1f} MB")


if __name__ == "__main__":
    main()
