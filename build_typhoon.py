#!/usr/bin/env python3
"""
build_typhoon.py — 気象庁 besttrack CSV から台風データを取得し typhoon.sqlite に保存

[データソース]
  気象庁 台風ベストトラック (BestTrack)
  https://www.jma.go.jp/jma/jma-eng/jma-center/rsmc-hp-pub-eg/besttrack.html
  日本語: https://www.data.jma.go.jp/yoho/typhoon/route_map/bsttrack.html

  BST形式 (RSMC Best Track) ダウンロード:
  https://www.jma.go.jp/jma/jma-eng/jma-center/rsmc-hp-pub-eg/Besttracks/bst{YY}.txt

[出力: typhoon.sqlite]
  typhoons テーブル: 台風番号・名前・期間
  typhoon_track テーブル: 6時間毎の台風位置・強度

[使い方]
  python build_typhoon.py            # 2023〜今年分を取得
  python build_typhoon.py --year 2024  # 特定年のみ
"""

import csv, io, json, math, os, re, sqlite3, sys, time, zipfile
from datetime import datetime, date
from urllib.request import urlopen, Request
from urllib.error import URLError

sys.stdout.reconfigure(encoding="utf-8")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH  = os.path.join(BASE_DIR, "typhoon.sqlite")

UA = "Mozilla/5.0 (compatible; funatsuri-yoso/1.0)"

# 関東釣り海域の代表座標（台風との距離計算用）
TARGET_COORDS = {
    "ibaraki":    (36.31, 140.57),
    "outer_boso": (35.14, 140.30),
    "tokyo_bay":  (35.30, 139.70),
    "sagami_bay": (35.00, 139.40),
}


def fetch(url, retries=3):
    for i in range(retries):
        try:
            req = Request(url, headers={"User-Agent": UA})
            with urlopen(req, timeout=30) as r:
                return r.read().decode("latin-1", errors="replace")
        except (URLError, OSError) as e:
            if i < retries - 1:
                time.sleep(3)
    return None


def fetch_bytes(url, retries=3):
    for i in range(retries):
        try:
            req = Request(url, headers={"User-Agent": UA})
            with urlopen(req, timeout=60) as r:
                return r.read()
        except (URLError, OSError) as e:
            if i < retries - 1:
                time.sleep(3)
    return None


def fetch_all_years_from_zip():
    """bst_all.zip の bst_all.txt を年ごとに分割して dict {year: text} で返す"""
    url = "https://www.jma.go.jp/jma/jma-eng/jma-center/rsmc-hp-pub-eg/Besttracks/bst_all.zip"
    print(f"  bst_all.zip 取得中... {url}")
    data = fetch_bytes(url)
    if not data:
        return {}
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        # bst_all.txt を読む（ファイル名に関わらず最初のtxtを使用）
        txt_names = [n for n in zf.namelist() if n.endswith(".txt")]
        if not txt_names:
            return {}
        all_text = zf.read(txt_names[0]).decode("latin-1", errors="replace")

    # ヘッダー行（66666）から年を判定して年ごとにブロックを収集
    result = {}
    current_year = None
    current_lines = []
    for line in all_text.split("\n"):
        stripped = line.rstrip()
        if stripped.startswith("66666"):
            parts = stripped.split()
            if len(parts) >= 2:
                ty_id = parts[1]
                try:
                    yr = int(ty_id[:2]) + 2000
                    if current_year is not None and yr != current_year:
                        result[current_year] = "\n".join(current_lines)
                        current_lines = []
                    current_year = yr
                except ValueError:
                    pass
        if current_year is not None:
            current_lines.append(stripped)
    if current_year is not None and current_lines:
        result[current_year] = "\n".join(current_lines)

    for yr, txt in sorted(result.items()):
        print(f"    → {yr}年 ({len(txt.splitlines())} lines)")
    return result


def haversine_km(lat1, lon1, lat2, lon2):
    """2点間の距離(km)"""
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
    return R * 2 * math.asin(math.sqrt(a))


def parse_bst(text, year):
    """
    JMA BestTrack テキストをパースして台風リスト・トラックを返す。
    フォーマット: https://www.jma.go.jp/jma/jma-eng/jma-center/rsmc-hp-pub-eg/Besttracks/format.txt
    """
    typhoons = []
    tracks   = []

    lines = text.strip().split("\n")
    current_ty = None

    for line in lines:
        line = line.rstrip()
        if not line:
            continue

        # ヘッダー行: 66666 で始まる
        if line.startswith("66666"):
            parts = line.split()
            if len(parts) < 7:
                continue
            # 台風番号: 年2桁+連番2桁 (例: 2301)
            ty_id  = parts[1]          # YYNN
            season = int(ty_id[:2]) + 2000
            number = int(ty_id[2:])
            name   = parts[7] if len(parts) > 7 else ""
            current_ty = {
                "year":   season,
                "number": number,
                "name":   name.strip(),
                "ty_id":  ty_id,
            }
            typhoons.append(current_ty)
            continue

        # 99999 (終端)
        if line.startswith("99999"):
            current_ty = None
            continue

        # データ行 (8桁日時で始まる)
        # フォーマット: AAAAAAAA BBB C DDD EEEE FFFF     GGG
        #  col 0-7:   time (yymmddhh)
        #  col 9-11:  indicator (002)
        #  col 13:    grade
        #  col 15-17: latitude * 10 (0.1 degree)
        #  col 19-22: longitude * 10 (0.1 degree)
        #  col 24-27: central pressure (hPa)
        #  col 33-35: max wind speed (kt)
        if current_ty and len(line) >= 24 and re.match(r'^\d{8}', line):
            try:
                yymmddhh = line[0:8]
                dt_str = f"20{yymmddhh[:2]}-{yymmddhh[2:4]}-{yymmddhh[4:6]}T{yymmddhh[6:8]}:00"

                # 緯度: col 15-17, 0.1度単位
                lat = int(line[15:18].strip()) / 10.0
                # 経度: col 19-22, 0.1度単位
                lon = int(line[19:23].strip()) / 10.0

                # 中心気圧: col 24-27
                pressure = None
                if len(line) >= 28:
                    try:
                        pressure = int(line[24:28].strip())
                    except ValueError:
                        pass

                # 最大風速: col 33-35 (kt)
                wind_kt = None
                if len(line) >= 36:
                    try:
                        wind_kt = int(line[33:36].strip())
                    except ValueError:
                        pass

                # 各釣り海域からの距離
                distances = {}
                for area, (alat, alon) in TARGET_COORDS.items():
                    distances[area] = round(haversine_km(lat, lon, alat, alon))

                min_dist = min(distances.values())

                tracks.append({
                    "ty_id":      current_ty["ty_id"],
                    "year":       current_ty["year"],
                    "number":     current_ty["number"],
                    "dt":         dt_str,
                    "lat":        lat,
                    "lon":        lon,
                    "pressure":   pressure,
                    "wind_kt":    wind_kt,
                    "dist_ibaraki":    distances.get("ibaraki"),
                    "dist_outer_boso": distances.get("outer_boso"),
                    "dist_tokyo_bay":  distances.get("tokyo_bay"),
                    "dist_sagami_bay": distances.get("sagami_bay"),
                    "min_dist":   min_dist,
                })
            except (ValueError, IndexError):
                continue

    return typhoons, tracks


def init_db(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS typhoons (
            ty_id    TEXT PRIMARY KEY,
            year     INTEGER,
            number   INTEGER,
            name     TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS typhoon_track (
            ty_id           TEXT,
            dt              TEXT,
            lat             REAL,
            lon             REAL,
            pressure        INTEGER,
            wind_kt         INTEGER,
            dist_ibaraki    INTEGER,
            dist_outer_boso INTEGER,
            dist_tokyo_bay  INTEGER,
            dist_sagami_bay INTEGER,
            min_dist        INTEGER,
            PRIMARY KEY (ty_id, dt)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ty_dt ON typhoon_track(dt)")
    conn.commit()


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, default=None)
    args = parser.parse_args()

    current_year = date.today().year
    years = [args.year] if args.year else list(range(2023, current_year + 1))

    conn = sqlite3.connect(DB_PATH)
    init_db(conn)

    total_ty = 0
    total_tr = 0

    # まず年別ファイルを試み、404なら bst_all.zip にフォールバック
    year_texts = {}
    zip_fetched = False
    for year in years:
        url = f"https://www.jma.go.jp/jma/jma-eng/jma-center/rsmc-hp-pub-eg/Besttracks/bst{year}.txt"
        text = fetch(url)
        if text:
            year_texts[year] = text
        else:
            if not zip_fetched:
                all_texts = fetch_all_years_from_zip()
                zip_fetched = True
                year_texts.update(all_texts)
            # year_texts から再確認（zip済み）
            if year not in year_texts:
                print(f"  {year}年: データなし（スキップ）")

    for year in years:
        text = year_texts.get(year)
        if not text:
            continue
        print(f"  {year}年 パース中...")

        typhoons, tracks = parse_bst(text, year)

        # 同年分を一旦削除して再挿入
        ty_ids = [t["ty_id"] for t in typhoons]
        if ty_ids:
            conn.execute(f"DELETE FROM typhoons WHERE ty_id IN ({','.join(['?']*len(ty_ids))})", ty_ids)
            conn.execute(f"DELETE FROM typhoon_track WHERE ty_id IN ({','.join(['?']*len(ty_ids))})", ty_ids)

        conn.executemany(
            "INSERT OR REPLACE INTO typhoons(ty_id, year, number, name) VALUES(?,?,?,?)",
            [(t["ty_id"], t["year"], t["number"], t["name"]) for t in typhoons]
        )
        conn.executemany(
            "INSERT OR REPLACE INTO typhoon_track"
            "(ty_id, dt, lat, lon, pressure, wind_kt, "
            " dist_ibaraki, dist_outer_boso, dist_tokyo_bay, dist_sagami_bay, min_dist) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            [(t["ty_id"], t["dt"], t["lat"], t["lon"], t["pressure"], t["wind_kt"],
              t["dist_ibaraki"], t["dist_outer_boso"], t["dist_tokyo_bay"],
              t["dist_sagami_bay"], t["min_dist"]) for t in tracks]
        )
        conn.commit()

        print(f"  → {year}年: {len(typhoons)}台風, {len(tracks)}ポイント")
        total_ty += len(typhoons)
        total_tr += len(tracks)
        time.sleep(1)

    conn.close()
    print(f"\n=== 完了: {total_ty}台風, {total_tr}トラックポイント ===")

    # 関東に500km以内に接近した台風を表示
    conn = sqlite3.connect(DB_PATH)
    print("\n関東500km以内に接近した台風（min_dist <= 500km）:")
    rows = conn.execute("""
        SELECT t.year, t.number, t.name,
               MIN(tr.min_dist) as closest_km,
               MIN(tr.pressure) as min_pressure,
               COUNT(*) as n_points
        FROM typhoons t
        JOIN typhoon_track tr ON t.ty_id = tr.ty_id
        WHERE tr.min_dist <= 500
        GROUP BY t.ty_id
        ORDER BY t.year, t.number
    """).fetchall()
    for r in rows:
        print(f"  {r[0]}年 台風{r[1]}号 {r[2]:<15} 最接近{r[3]:>4}km  最低気圧{r[4]}hPa  {r[5]}ポイント")
    conn.close()


if __name__ == "__main__":
    main()
