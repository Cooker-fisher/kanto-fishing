#!/usr/bin/env python3
"""
rebuild_weather_cache.py — weather_cache.sqlite を Open-Meteo から全件再取得

[データソース]
  Open-Meteo Archive API  → wind_speed, wind_dir, temp, pressure, precipitation
  Open-Meteo Marine API   → wave_height, wave_period, swell_height, sst,
                             current_speed, current_dir

[対象座標]
  point_coords.json（152座標）+ area_coords.json（58エリア）重複排除

[期間]
  2023-01-01 〜 今日

[出力]
  weather_cache.sqlite（3時間ごと × 153座標 × 3年 ≒ 145万行）

[使い方]
  python rebuild_weather_cache.py --update       # 増分更新（推奨・数分）
                                                 #   座標ごとに DB の最終取得日から差分のみ取得。
                                                 #   リクエスト量が全取得の約1/100になり 429 を回避できる
  python rebuild_weather_cache.py                # 全座標・全期間取得（約30分・スキーマ変更時のみ）
  python rebuild_weather_cache.py --test         # 最初の3座標のみテスト
  python rebuild_weather_cache.py --resume       # 未取得座標のみ取得（再開）
  python rebuild_weather_cache.py --update-current  # 潮流列のみ全座標再取得

  ※ 失敗座標（429等）は実行末尾で自動リペア（最大2パス・低速ペース）される。
    手動 _repair_marine.py は原則不要。
"""

import json, os, sqlite3, sys, time
from datetime import datetime, timedelta
from urllib.request import urlopen, Request
from urllib.error import URLError

sys.stdout.reconfigure(encoding="utf-8")

BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
DB_PATH     = os.path.join(BASE_DIR, "weather_cache.sqlite")
AREA_FILE   = os.path.join(os.path.dirname(BASE_DIR), "normalize", "area_coords.json")
POINT_FILE  = os.path.join(os.path.dirname(BASE_DIR), "normalize", "point_coords.json")

START_DATE = "2023-01-01"
# Archive API（ERA5）は当日分が未提供で end_date=today だと 400
# （allowed range は前日まで）。weather と marine を揃えて取得するため
# 両 API とも前日までを終端にする。
END_DATE   = (datetime.today() - timedelta(days=1)).strftime("%Y-%m-%d")

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
            code = getattr(e, "code", None)
            print(f"  fetch error ({i+1}/{retries}): {e}")
            if code == 400:
                # 範囲外（end_date=当日等）の恒久エラー。リトライしても変わらない
                return None
            if i < retries - 1:
                # 429（レート制限）は実測60-90秒で回復するため長めに待つ
                time.sleep(min(120, 60 * (i + 1)) if code == 429 else 5 * (i + 1))
    return None


def _delta_start(max_dt):
    """既存最終 dt から2日重ねた再取得開始日（データ確定遅れ・補正の取りこぼし対策）"""
    d = datetime.strptime(max_dt[:10], "%Y-%m-%d") - timedelta(days=2)
    return d.strftime("%Y-%m-%d")


def _coord_starts(conn, lat, lon):
    """座標ごとの増分開始日を (気象, 海況) で返す。データが無い側は全期間。"""
    r = conn.execute(
        "SELECT MAX(CASE WHEN temp IS NOT NULL THEN dt END),"
        "       MAX(CASE WHEN sst  IS NOT NULL THEN dt END)"
        "  FROM weather WHERE lat=? AND lon=?", (lat, lon)).fetchone()
    wx_s = _delta_start(r[0]) if r and r[0] else START_DATE
    ma_s = _delta_start(r[1]) if r and r[1] else START_DATE
    return wx_s, ma_s


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


def fetch_marine(lat, lon, start, end, current_only=False):
    """Open-Meteo Marine → 海況データ（3時間ごと）
    current_only=True の場合は潮流列のみ取得（--update-current 用）
    """
    if current_only:
        fields = "ocean_current_velocity,ocean_current_direction"
    else:
        fields = "wave_height,wave_period,swell_wave_height,sea_surface_temperature,ocean_current_velocity,ocean_current_direction"
    url = (
        f"{MARINE_URL}?latitude={lat}&longitude={lon}"
        f"&start_date={start}&end_date={end}"
        f"&hourly={fields}"
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
    cv     = hourly.get("ocean_current_velocity", [])
    cd     = hourly.get("ocean_current_direction", [])

    result = {}
    for i, t in enumerate(times):
        hour = int(t[11:13]) if len(t) >= 13 else -1
        if hour % 3 != 0:
            continue
        dt = t[:16]
        result[dt] = {
            "wave_height":    wh[i] if i < len(wh) else None,
            "wave_period":    wp[i] if i < len(wp) else None,
            "swell_height":   sw[i] if i < len(sw) else None,
            "sst":            st[i] if i < len(st) else None,
            "current_speed":  cv[i] if i < len(cv) else None,
            "current_dir":    cd[i] if i < len(cd) else None,
        }
    return result


def init_db(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS weather (
            lat           REAL,
            lon           REAL,
            dt            TEXT,
            wind_speed    REAL,
            wind_dir      REAL,
            temp          REAL,
            pressure      REAL,
            wave_height   REAL,
            wave_period   REAL,
            swell_height  REAL,
            sst           REAL,
            precipitation REAL,
            current_speed REAL,
            current_dir   REAL,
            PRIMARY KEY (lat, lon, dt)
        )
    """)
    # 既存DBへの列追加（ALTER TABLE は列が存在する場合エラーになるのでtry/except）
    for col, typ in [("current_speed", "REAL"), ("current_dir", "REAL")]:
        try:
            conn.execute(f"ALTER TABLE weather ADD COLUMN {col} {typ}")
            print(f"  [schema] {col} 列を追加しました")
        except Exception:
            pass  # 既に存在する場合は無視
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
    """気象+海況を結合してDBにUPSERT。
    片側の取得失敗（空 dict）が反対側の既存列を NULL 上書きして破壊しないよう、
    INSERT OR REPLACE ではなく ON CONFLICT DO UPDATE + COALESCE を使う。
    新値が NULL の列は既存値を保持する（気象だけ取れた／海況だけ取れた、を安全に併合）。"""
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
            ma.get("current_speed"),
            ma.get("current_dir"),
        ))
    conn.executemany("""
        INSERT INTO weather
        (lat, lon, dt, wind_speed, wind_dir, temp, pressure,
         wave_height, wave_period, swell_height, sst, precipitation,
         current_speed, current_dir)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(lat, lon, dt) DO UPDATE SET
            wind_speed    = COALESCE(excluded.wind_speed,    weather.wind_speed),
            wind_dir      = COALESCE(excluded.wind_dir,      weather.wind_dir),
            temp          = COALESCE(excluded.temp,          weather.temp),
            pressure      = COALESCE(excluded.pressure,      weather.pressure),
            wave_height   = COALESCE(excluded.wave_height,   weather.wave_height),
            wave_period   = COALESCE(excluded.wave_period,   weather.wave_period),
            swell_height  = COALESCE(excluded.swell_height,  weather.swell_height),
            sst           = COALESCE(excluded.sst,           weather.sst),
            precipitation = COALESCE(excluded.precipitation, weather.precipitation),
            current_speed = COALESCE(excluded.current_speed, weather.current_speed),
            current_dir   = COALESCE(excluded.current_dir,   weather.current_dir)
    """, rows)
    conn.commit()
    return len(rows)


def update_current_rows(conn, lat, lon, ma_dict):
    """潮流列のみ UPDATE（--update-current 用）"""
    rows = []
    for dt, ma in ma_dict.items():
        rows.append((
            ma.get("current_speed"),
            ma.get("current_dir"),
            lat, lon, dt,
        ))
    conn.executemany("""
        UPDATE weather SET current_speed=?, current_dir=?
        WHERE lat=? AND lon=? AND dt=?
    """, rows)
    conn.commit()
    return len(rows)


def main():
    test_mode          = "--test"           in sys.argv
    resume_mode        = "--resume"         in sys.argv
    update_current     = "--update-current" in sys.argv
    update_mode        = "--update"         in sys.argv

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
    elif update_current:
        print(f"=== --update-current: 潮流列のみ追記（{len(coords)}座標）===")
        print(f"  期間: {START_DATE} 〜 {END_DATE}")
        print(f"  出力: {DB_PATH}")
    elif update_mode:
        print(f"=== --update: 増分更新（{len(coords)}座標・座標ごとに最終取得日から）===")
        print(f"  終端: {END_DATE}")
        print(f"  出力: {DB_PATH}")
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

        if update_current:
            # 潮流のみ再取得（Marine APIのみ・current_only=True）
            ma = fetch_marine(lat, lon, START_DATE, END_DATE, current_only=True)
            time.sleep(0.8)
            if not ma:
                print("データ取得失敗")
                failed.append((lat, lon, area_name))
                continue
            n = update_current_rows(conn, lat, lon, ma)
            total_rows += n
            print(f"{n}行更新")
            continue

        # 増分モード: 座標ごとに気象/海況それぞれの最終取得日から差分のみ取得
        wx_start, ma_start = (START_DATE, START_DATE)
        if update_mode:
            wx_start, ma_start = _coord_starts(conn, lat, lon)
            if wx_start > END_DATE and ma_start > END_DATE:
                print("最新（スキップ）")
                continue

        need_wx = wx_start <= END_DATE
        need_ma = ma_start <= END_DATE
        wx = fetch_weather(lat, lon, wx_start, END_DATE) if need_wx else {}
        time.sleep(0.8)
        ma = fetch_marine(lat, lon, ma_start, END_DATE) if need_ma else {}
        time.sleep(0.8)

        if (need_wx and not wx) and (need_ma and not ma):
            print("データ取得失敗")
            failed.append((lat, lon, area_name))
            continue

        # upsert_rows は COALESCE 併合なので、片側が空でも反対側の既存列は破壊しない。
        # ただし片側が欠落した座標は不完全なので failed に積んで再試行対象にする
        # （429 レート制限で marine だけ落ちる等。weather/marine の NULL 上書き破壊は無し）。
        n = upsert_rows(conn, lat, lon, wx, ma)
        total_rows += n
        miss = [lbl for lbl, ok, need in (("気象", wx, need_wx), ("海況", ma, need_ma))
                if need and not ok]
        if miss:
            print(f"{n}行（{'・'.join(miss)}欠落→自動リペア対象）")
            failed.append((lat, lon, area_name))
        else:
            print(f"{n}行")

    # ── 失敗座標の自動リペア（429対策・低速ペース・最大2パス） ──────────────
    # 欠落側だけを増分で再取得するのでリクエスト量は最小。
    if failed and not update_current:
        for pass_no in (1, 2):
            if not failed:
                break
            print(f"\n=== 自動リペア pass {pass_no}: {len(failed)}座標"
                  f"（60sクールダウン + 座標間10s） ===", flush=True)
            time.sleep(60)
            still = []
            for lat, lon, area_name in failed:
                print(f"  ({lat},{lon}) {area_name}", end=" ... ", flush=True)
                time.sleep(10)
                wx_s, ma_s = _coord_starts(conn, lat, lon)
                need_wx = wx_s <= END_DATE
                need_ma = ma_s <= END_DATE
                wx = fetch_weather(lat, lon, wx_s, END_DATE) if need_wx else {}
                time.sleep(1.5)
                ma = fetch_marine(lat, lon, ma_s, END_DATE) if need_ma else {}
                time.sleep(1.5)
                n = upsert_rows(conn, lat, lon, wx, ma) if (wx or ma) else 0
                total_rows += n
                miss = [lbl for lbl, ok, need in (("気象", wx, need_wx), ("海況", ma, need_ma))
                        if need and not ok]
                if miss:
                    print(f"{n}行（{'・'.join(miss)}欠落）")
                    still.append((lat, lon, area_name))
                else:
                    print(f"{n}行 完了")
            failed = still

    conn.close()

    print(f"\n=== 完了: {total_rows:,}行 ===")
    if failed:
        print(f"失敗 {len(failed)}座標（自動リペア2パス後も欠落・要手動再実行）:")
        for lat, lon, name in failed:
            print(f"  ({lat},{lon}) {name}")


if __name__ == "__main__":
    main()
