#!/usr/bin/env python3
"""
typhoon.py - 気象庁ベストトラックから台風接近データを生成
出力: typhoon.csv (全期間・1日1行)

データソース: JMA RSMC Best Track (bst_all.zip)
  https://www.jma.go.jp/jma/jma-eng/jma-center/rsmc-hp-pub-eg/Besttracks/bst_all.zip

カラム: date, typhoon_flag, min_dist_km, typhoon_name
  typhoon_flag: 1=500km以内に台風あり, 0=なし
  min_dist_km : 関東中心(35.5N,139.7E)からの最短距離(km)
"""
import csv, os, sys, io, math, zipfile, urllib.request
from datetime import date, timedelta, datetime, timezone
from collections import defaultdict

START_DATE = date(2024, 4, 1)
END_DATE   = date.today()

# 関東中心座標
KANTO_LAT = 35.5
KANTO_LON = 139.7

# 台風とみなす最低グレード (3=台風 TD以上, 2=TD含む)
MIN_GRADE = 3   # 3=Tropical Storm以上（熱帯低気圧は除外）

OUT_FILE = 'typhoon.csv'
BST_URL  = ('https://www.jma.go.jp/jma/jma-eng/jma-center/'
            'rsmc-hp-pub-eg/Besttracks/bst_all.zip')


def dist_km(lat1, lon1, lat2, lon2):
    """2点間の距離(km) - Haversine公式"""
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
         * math.sin(dlon / 2) ** 2)
    return R * 2 * math.asin(math.sqrt(a))


def parse_bst(text):
    """
    ベストトラックをパースして {date: [(dist_km, name)]} を返す。
    dateはdate型（JST近似でUTC+9換算）。
    """
    date_dists = defaultdict(list)
    current_name = ''

    for line in text.splitlines():
        line = line.rstrip()
        if not line:
            continue

        # ヘッダー行 (66666 で始まる)
        if line.startswith('66666'):
            current_name = line[43:63].strip() or line[22:42].strip()
            continue

        # データ行: yymmddhh (positions 0-7)
        if len(line) < 19:
            continue

        try:
            yymmddhh = line[0:8].strip()
            if len(yymmddhh) != 8:
                continue
            yy = int(yymmddhh[0:2])
            mm = int(yymmddhh[2:4])
            dd = int(yymmddhh[4:6])
            hh = int(yymmddhh[6:8])
            year = 1900 + yy if yy >= 51 else 2000 + yy

            grade = int(line[13:14].strip()) if line[13:14].strip() else 0
            lat_raw = line[15:18].strip()
            lon_raw = line[19:23].strip()

            if not lat_raw or not lon_raw:
                continue

            lat = int(lat_raw) * 0.1
            lon = int(lon_raw) * 0.1

        except (ValueError, IndexError):
            continue

        # グレードフィルタ（台風以上）
        if grade < MIN_GRADE:
            continue

        # UTC→JST（+9h）近似: hh+9で日付をずらす場合あり
        dt_utc = datetime(year, mm, dd, hh, tzinfo=timezone.utc)
        dt_jst = dt_utc + timedelta(hours=9)
        d = dt_jst.date()

        # 対象期間外はスキップ
        if d < START_DATE or d > END_DATE:
            continue

        d_km = dist_km(KANTO_LAT, KANTO_LON, lat, lon)
        date_dists[d].append((d_km, current_name))

    return date_dists


def main():
    print(f'ベストトラックダウンロード中...')
    req = urllib.request.Request(BST_URL, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=60) as r:
        zip_bytes = r.read()
    print(f'  {len(zip_bytes) // 1024}KB ダウンロード完了')

    # ZIP解凍
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        txt_name = z.namelist()[0]
        text = z.read(txt_name).decode('ascii', errors='replace')
    print(f'  {txt_name}: {len(text)}文字')

    # パース
    date_dists = parse_bst(text)
    print(f'台風接近データ: {len(date_dists)}日分')

    # 全日付リストを生成して出力
    rows = []
    d = START_DATE
    while d <= END_DATE:
        entries = date_dists.get(d, [])
        if entries:
            min_dist, closest_name = min(entries, key=lambda x: x[0])
            flag = 1 if min_dist <= 500 else 0
            rows.append([d.isoformat(), flag, round(min_dist), closest_name])
        else:
            rows.append([d.isoformat(), 0, '', ''])
        d += timedelta(days=1)

    with open(OUT_FILE, 'w', encoding='utf-8', newline='') as f:
        w = csv.writer(f)
        w.writerow(['date', 'typhoon_flag', 'min_dist_km', 'typhoon_name'])
        w.writerows(rows)

    # 統計表示
    flagged = sum(1 for r in rows if r[1] == 1)
    print(f'\n{OUT_FILE} 書き出し完了: {len(rows)}行 (台風接近日: {flagged}日)')
    print('\n接近イベント（500km以内）:')
    for r in rows:
        if r[1] == 1:
            print(f'  {r[0]} {r[3]} {r[2]}km')


if __name__ == '__main__':
    main()
