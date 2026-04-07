#!/usr/bin/env python3
"""
moon.py - 月齢と潮回りを計算してCSVに出力
出力: moon.csv (全期間・1日1行)

計算式:
  既知の新月: 2000年1月6日 18:14 UTC (ユリウス通日 2451550.259)
  朔望月: 29.53058867日
  月齢 = (当日JD - 基準JD) % 29.53058867

潮回り（moon_title）:
  大潮: 月齢 0-2 or 14-16 (新月・満月の前後2日)
  中潮: 月齢 3-4 or 11-13 or 17-18 or 25-26
  小潮: 月齢 5-8 or 19-22
  長潮: 月齢 9 or 23
  若潮: 月齢 10 or 24
"""
import csv, os, sys
from datetime import date, timedelta

START_DATE = date(2024, 4, 1)
END_DATE   = date.today()

# 既知の新月 (ユリウス通日)
NEW_MOON_JD = 2451550.259   # 2000-01-06 18:14 UTC
SYNODIC     = 29.53058867   # 朔望月（日）

OUT_FILE = 'moon.csv'


def date_to_jd(d):
    """日付をユリウス通日(正午)に変換"""
    a = (14 - d.month) // 12
    y = d.year + 4800 - a
    m = d.month + 12 * a - 3
    return d.day + (153 * m + 2) // 5 + 365 * y + y // 4 - y // 100 + y // 400 - 32045


def moon_age(d):
    """月齢を計算 (0.0 ～ 29.5)"""
    jd = date_to_jd(d) - 0.5   # 00:00 JST ≒ UTC前日15:00 → 近似で正午JD - 0.5
    age = (jd - NEW_MOON_JD) % SYNODIC
    return round(age, 1)


def moon_title(age):
    """月齢から潮回りを返す"""
    a = age % SYNODIC
    if a < 0:
        a += SYNODIC
    if   a <= 2.0 or a >= 27.5:   return '大潮'
    elif a <= 4.0 or (13.0 <= a <= 16.5):
        if 14.0 <= a <= 16.5:      return '大潮'
        return '中潮'
    elif 4.0 < a <= 5.5:           return '中潮'
    elif 5.5 < a <= 9.5:           return '小潮'
    elif 9.5 < a <= 10.5:          return '長潮'
    elif 10.5 < a <= 12.0:         return '若潮'
    elif 12.0 < a <= 13.0:         return '中潮'
    elif 13.0 < a <= 16.5:         return '大潮'
    elif 16.5 < a <= 18.0:         return '中潮'
    elif 18.0 < a <= 22.5:         return '小潮'
    elif 22.5 < a <= 23.5:         return '長潮'
    elif 23.5 < a <= 25.0:         return '若潮'
    elif 25.0 < a <= 27.5:         return '中潮'
    return '中潮'


def main():
    rows = []
    d = START_DATE
    while d <= END_DATE:
        age = moon_age(d)
        title = moon_title(age)
        rows.append([d.isoformat(), age, title])
        d += timedelta(days=1)

    with open(OUT_FILE, 'w', encoding='utf-8', newline='') as f:
        w = csv.writer(f)
        w.writerow(['date', 'moon_age', 'moon_title'])
        w.writerows(rows)

    print(f'{OUT_FILE} 書き出し完了: {len(rows)}行')
    # サンプル表示
    print('\nサンプル:')
    print('date,moon_age,moon_title')
    for r in rows[:5]:
        print(','.join(str(x) for x in r))


if __name__ == '__main__':
    main()
