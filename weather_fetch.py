#!/usr/bin/env python3
"""
weather_fetch.py - Open-Meteo から気象データを取得
出力: weather/YYYY-MM.csv (3時間粒度 JST / 96ポイント)

使い方:
    python weather_fetch.py            # 全期間取得
    python weather_fetch.py --resume   # 中断再開

カラム: point, date, hour, wave_height, wave_period, wind_speed, wind_dir, sst, weather_code
"""
import json, csv, os, sys, time, glob, urllib.request, urllib.parse
from datetime import date, timedelta, datetime
from collections import defaultdict

START_DATE = date(2024, 4, 1)
END_DATE   = date.today() - timedelta(days=1)

TARGET_HOURS = {0, 3, 6, 9, 12, 15, 18, 21}  # JST 3時間粒度
PROGRESS_FILE = 'weather/.progress.json'

HEADERS = ['point', 'date', 'hour', 'wave_height', 'wave_period',
           'wind_speed', 'wind_dir', 'sst', 'weather_code', 'pressure']


def fetch_url(url, retries=3):
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                return json.loads(r.read())
        except Exception as e:
            if attempt == retries - 1:
                raise
            print(f' retry{attempt+1}...', end='', flush=True)
            time.sleep(3)


def fetch_marine(lat, lon):
    params = {
        'latitude': lat, 'longitude': lon,
        'hourly': 'wave_height,wave_period,sea_surface_temperature',
        'start_date': START_DATE.isoformat(),
        'end_date': END_DATE.isoformat(),
        'timezone': 'Asia/Tokyo',
    }
    url = 'https://marine-api.open-meteo.com/v1/marine?' + urllib.parse.urlencode(params)
    return fetch_url(url)


def fetch_archive(lat, lon):
    params = {
        'latitude': lat, 'longitude': lon,
        'hourly': 'wind_speed_10m,wind_direction_10m,weather_code,surface_pressure',
        'start_date': START_DATE.isoformat(),
        'end_date': END_DATE.isoformat(),
        'timezone': 'Asia/Tokyo',
        'wind_speed_unit': 'ms',
    }
    url = 'https://archive-api.open-meteo.com/v1/archive?' + urllib.parse.urlencode(params)
    return fetch_url(url)


def fmt(v):
    if v is None:
        return ''
    if isinstance(v, float):
        return round(v, 1)
    return v


def load_progress():
    if os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE, encoding='utf-8') as f:
            return set(tuple(x) for x in json.load(f))
    return set()


def save_progress(done):
    with open(PROGRESS_FILE, 'w', encoding='utf-8') as f:
        json.dump([list(k) for k in done], f)


def main():
    with open('point_coords.json', encoding='utf-8') as f:
        point_data = json.load(f)

    # CSV件数でポイント代表名を決める
    point_count = defaultdict(int)
    for fpath in glob.glob('data/*.csv'):
        with open(fpath, encoding='utf-8') as f:
            for row in csv.DictReader(f):
                p = (row.get('point_place') or '').strip()
                if p:
                    point_count[p] += 1

    # ユニーク座標グループ化
    coord_groups = defaultdict(list)
    for name, coord in point_data.items():
        if coord and coord.get('lat') is not None:
            key = (float(coord['lat']), float(coord['lon']))
            coord_groups[key].append(name)

    # 代表名 = グループ内で最も件数が多い名前
    coord_rep = {key: max(names, key=lambda n: point_count.get(n, 0))
                 for key, names in coord_groups.items()}

    coords = sorted(coord_groups.keys())
    os.makedirs('weather', exist_ok=True)

    # --resume: 完了済みをスキップ
    resume = '--resume' in sys.argv
    done = load_progress() if resume else set()
    if resume:
        print(f'再開モード: {len(done)}/{len(coords)} 完了済み')

    # 既存CSVファイルはヘッダー書き込み済みとみなす
    header_written = {os.path.basename(p).replace('.csv', '') for p in glob.glob('weather/*.csv')}

    print(f'取得対象: {len(coords)}座標 / {START_DATE} ~ {END_DATE}')
    print()

    errors = []

    for i, (lat, lon) in enumerate(coords):
        key = (lat, lon)
        if resume and key in done:
            continue

        rep = coord_rep[key]
        print(f'[{i+1:3d}/{len(coords)}] {rep} ({lat},{lon})', end=' ', flush=True)

        try:
            marine  = fetch_marine(lat, lon)
            time.sleep(0.5)
            archive = fetch_archive(lat, lon)
            time.sleep(0.5)
        except Exception as e:
            print(f'ERROR: {e}')
            errors.append((rep, str(e)))
            continue

        # archive を時刻→値の辞書に
        a = archive['hourly']
        arch = {t: (a['wind_speed_10m'][j], a['wind_direction_10m'][j], a['weather_code'][j],
                    a.get('surface_pressure', [None]*len(a['time']))[j])
                for j, t in enumerate(a['time'])}

        # marine をなめて3時間粒度のみ抽出・月別に追記
        m = marine['hourly']
        month_rows = defaultdict(list)
        for j, t in enumerate(m['time']):
            dt = datetime.fromisoformat(t)
            if dt.hour not in TARGET_HOURS:
                continue
            ws, wd, wc, sp = arch.get(t, (None, None, None, None))
            month_rows[(dt.year, dt.month)].append([
                rep,
                dt.strftime('%Y-%m-%d'),
                f'{dt.hour:02d}',
                fmt(m['wave_height'][j]),
                fmt(m['wave_period'][j]),
                fmt(ws),
                '' if wd is None else int(wd),
                fmt(m['sea_surface_temperature'][j]),
                '' if wc is None else int(wc),
                fmt(sp),
            ])

        # 月別CSVに追記（新規ファイルはヘッダー付き）
        total_rows = 0
        for (year, month), rows in month_rows.items():
            fname  = f'weather/{year:04d}-{month:02d}.csv'
            ym_key = f'{year:04d}-{month:02d}'
            mode = 'a' if ym_key in header_written else 'w'
            with open(fname, mode, encoding='utf-8', newline='') as f:
                w = csv.writer(f)
                if mode == 'w':
                    w.writerow(HEADERS)
                    header_written.add(ym_key)
                w.writerows(rows)
            total_rows += len(rows)

        done.add(key)
        save_progress(done)
        print(f'OK ({total_rows}行)')

    if errors:
        print(f'\nエラー {len(errors)}件:')
        for name, msg in errors:
            print(f'  {name}: {msg}')

    print(f'\n完了: {len(done)}/{len(coords)}座標')


if __name__ == '__main__':
    main()
