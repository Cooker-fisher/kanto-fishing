#!/usr/bin/env python3
"""
tide_fetch.py - tide736.net API から潮汐データを取得
出力: tide/YYYY-MM.csv (毎時・4エリア)

4エリア:
  神奈川: 横須賀 (pc=14, hc=7)
  東京  : 羽田   (pc=13, hc=3)
  千葉  : 銚子漁港 (pc=12, hc=2)
  茨城  : 鹿島   (pc=8,  hc=4)

カラム: port, date, hour, tide_cm
"""
import json, csv, os, sys, time, urllib.request, urllib.parse
from datetime import date, timedelta
from collections import defaultdict

START_DATE = date(2024, 4, 1)
END_DATE   = date.today() - timedelta(days=1)

PORTS = [
    {'name': '横須賀', 'pc': 14, 'hc': 7},
    {'name': '羽田',   'pc': 13, 'hc': 3},
    {'name': '銚子',   'pc': 12, 'hc': 2},
    {'name': '鹿島',   'pc': 8,  'hc': 4},
]

OUT_DIR = 'tide'
SLEEP_SEC = 1.0  # API間インターバル（アクセス制限対策）


def fetch_tide_month(pc, hc, yr, mn, retries=3):
    params = {
        'pc': str(pc), 'hc': str(hc),
        'yr': str(yr), 'mn': f'{mn:02d}',
        'dy': '01', 'rg': 'month',
    }
    url = 'https://api.tide736.net/get_tide.php?' + urllib.parse.urlencode(params)
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                return json.loads(r.read())
        except Exception as e:
            if attempt == retries - 1:
                raise
            print(f' retry{attempt+1}...', end='', flush=True)
            time.sleep(3)


def main():
    os.makedirs(OUT_DIR, exist_ok=True)

    # 月リストを生成
    months = []
    d = START_DATE.replace(day=1)
    while d <= END_DATE:
        months.append((d.year, d.month))
        # 翌月へ
        if d.month == 12:
            d = d.replace(year=d.year + 1, month=1)
        else:
            d = d.replace(month=d.month + 1)

    total = len(PORTS) * len(months)
    count = 0

    print(f'取得開始: {len(PORTS)}港 × {len(months)}ヶ月 = {total}リクエスト')
    print()

    errors = []

    # 月別バッファ: {(year,month): [rows]}
    month_buf = defaultdict(list)

    for port in PORTS:
        for (yr, mn) in months:
            count += 1
            print(f'[{count:3d}/{total}] {port["name"]} {yr}-{mn:02d}', end=' ', flush=True)

            try:
                d = fetch_tide_month(port['pc'], port['hc'], yr, mn)
                time.sleep(SLEEP_SEC)
            except Exception as e:
                print(f'ERROR: {e}')
                errors.append((port['name'], yr, mn, str(e)))
                continue

            chart = d['tide'].get('chart', {})
            row_count = 0
            for date_str, day_data in chart.items():
                tide_list = day_data.get('tide', [])
                for t in tide_list:
                    time_str = t['time']  # "06:00", "24:00" など
                    if not time_str.endswith(':00'):
                        continue
                    hour = int(time_str.split(':')[0])
                    if hour == 24:
                        continue  # 翌日00:00と重複するためスキップ
                    month_buf[(yr, mn)].append([
                        port['name'],
                        date_str,
                        f'{hour:02d}',
                        t['cm'],
                    ])
                    row_count += 1

            print(f'OK ({row_count}行)')

    # 月別CSVに書き出し
    print('\nCSV書き出し中...')
    header = ['port', 'date', 'hour', 'tide_cm']

    for (year, month), rows in sorted(month_buf.items()):
        fname = f'{OUT_DIR}/{year:04d}-{month:02d}.csv'
        with open(fname, 'w', encoding='utf-8', newline='') as f:
            w = csv.writer(f)
            w.writerow(header)
            w.writerows(rows)
        print(f'  {fname} ({len(rows)}行)')

    if errors:
        print(f'\nエラー {len(errors)}件:')
        for name, yr, mn, msg in errors:
            print(f'  {name} {yr}-{mn:02d}: {msg}')

    print(f'\n完了')


if __name__ == '__main__':
    main()
