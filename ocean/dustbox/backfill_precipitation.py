#!/usr/bin/env python3
"""
backfill_precipitation.py — precipitation カラムを既存 weather_cache に追加取得

weather_cache.sqlite の precipitation IS NULL な座標×期間を対象に
Open-Meteo archive API から precipitation だけ取得して UPDATE する。

[使い方]
  python backfill_precipitation.py          # 全座標バックフィル
  python backfill_precipitation.py --test   # 最初の3座標だけテスト実行
"""

import json, os, sqlite3, sys, time
from datetime import datetime, timedelta
from urllib.request import urlopen, Request
from urllib.error import URLError

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH  = os.path.join(BASE_DIR, "weather_cache.sqlite")
UA = "Mozilla/5.0 (compatible; funatsuri-yoso/1.0)"

def fetch(url, retries=5):
    for i in range(retries):
        try:
            req = Request(url, headers={"User-Agent": UA})
            with urlopen(req, timeout=60) as r:
                return r.read().decode("utf-8")
        except (URLError, OSError) as e:
            print(f"  fetch error: {e}")
            if i < retries - 1:
                time.sleep(3 * (i + 1))
    return None

def fetch_precipitation(lat, lon, start, end):
    """Open-Meteo archive から precipitation だけ取得"""
    url = (
        f"https://archive-api.open-meteo.com/v1/archive"
        f"?latitude={lat}&longitude={lon}"
        f"&start_date={start}&end_date={end}"
        f"&hourly=precipitation"
        f"&timezone=Asia%2FTokyo"
    )
    txt = fetch(url)
    if not txt:
        return {}
    try:
        data = json.loads(txt).get("hourly", {})
        times = data.get("time", [])
        vals  = data.get("precipitation", [])
        # dt → precipitation の辞書（3時間おきのみ）
        result = {}
        for dt, v in zip(times, vals):
            hour = int(dt[11:13])
            if hour % 3 == 0:
                result[dt] = v   # 例: "2023-01-01T06:00" → 0.2
        return result
    except Exception as e:
        print(f"  parse error: {e}")
        return {}

def main():
    test_mode = "--test" in sys.argv
    conn = sqlite3.connect(DB_PATH)

    # NULL な座標×期間を取得
    rows = conn.execute("""
        SELECT lat, lon,
               MIN(substr(dt,1,10)) AS start_date,
               MAX(substr(dt,1,10)) AS end_date
        FROM weather
        WHERE precipitation IS NULL
        GROUP BY lat, lon
        ORDER BY lat, lon
    """).fetchall()

    total_coords = len(rows)
    if test_mode:
        rows = rows[:3]
        print(f"=== テストモード（{len(rows)}/全{total_coords}座標） ===")
    else:
        print(f"=== precipitation バックフィル開始（{total_coords}座標） ===")

    total_updated = 0

    for idx, (lat, lon, start, end) in enumerate(rows, 1):
        print(f"  [{idx}/{len(rows)}] ({lat},{lon}) {start}〜{end}", end=" ", flush=True)

        precip = fetch_precipitation(lat, lon, start, end)
        if not precip:
            print("データなし")
            continue

        # UPDATE（dt が一致する行のみ）
        update_rows = [(v, lat, lon, dt) for dt, v in precip.items()]
        conn.executemany(
            "UPDATE weather SET precipitation=? WHERE lat=? AND lon=? AND dt=?",
            update_rows
        )
        conn.commit()
        total_updated += len(update_rows)
        print(f"→ {len(update_rows)}行 UPDATE")
        time.sleep(0.4)  # API負荷対策

    conn.close()
    print(f"\n=== 完了: {total_updated:,}行 UPDATE ===")

if __name__ == "__main__":
    main()
