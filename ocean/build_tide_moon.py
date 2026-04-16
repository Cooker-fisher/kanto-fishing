#!/usr/bin/env python3
"""
build_tide_moon.py — 月齢・潮汐区分を天文計算で算出し tide_moon.sqlite に保存

[計算内容]
  ・月齢 (moon_age)        : 朔（新月）からの経過日数（0〜29.5）
  ・潮汐区分 (tide_type)   : 大潮/中潮/小潮/長潮/若潮
  ・潮位差係数 (tide_coeff): 0〜100（100=大潮ピーク, 0=小潮ピーク）
  ・月相 (moon_phase)      : 新月/上弦/満月/下弦

[対象期間]
  2023-01-01 〜 今日（日ベース）

[外部ライブラリ不要]
  標準ライブラリの math / datetime のみ使用

[使い方]
  python build_tide_moon.py
  python build_tide_moon.py --start 2023-01-01 --end 2026-12-31
"""

import math, os, sqlite3, sys
from datetime import date, timedelta

sys.stdout.reconfigure(encoding="utf-8")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH  = os.path.join(BASE_DIR, "tide_moon.sqlite")

# ── 基準新月（J2000.0に近い既知の新月）────────────────────────────────
# 2000-01-06 18:14 UTC → Julian Day Number
_BASE_NEW_MOON_JD = 2451550.259722   # 2000-01-06 18:14 UTC の JD
_SYNODIC_MONTH    = 29.530588853     # 朔望月（日）


def date_to_jd(d: date) -> float:
    """グレゴリオ暦 → ユリウス通日（正午基準）"""
    y, m, day = d.year, d.month, d.day
    if m <= 2:
        y -= 1
        m += 12
    A = int(y / 100)
    B = 2 - A + int(A / 4)
    return int(365.25 * (y + 4716)) + int(30.6001 * (m + 1)) + day + B - 1524.5


def calc_moon_age(d: date) -> float:
    """月齢を返す（0.0〜29.53）"""
    jd = date_to_jd(d) + 0.5  # 正午基準 → 0時基準補正
    # 基準新月からの経過日数を朔望月で割り余りを取る
    elapsed = jd - _BASE_NEW_MOON_JD
    age = elapsed % _SYNODIC_MONTH
    return round(age, 2)


def calc_tide_type(moon_age: float) -> str:
    """月齢 → 潮汐区分（日本式）"""
    # 月齢を 0〜29.53 の範囲に正規化
    age = moon_age % _SYNODIC_MONTH
    # 新月前後（0〜2, 27.5〜29.53）と満月前後（13〜16）が大潮
    for lo, hi, t in [
        (0.0,   2.5,  "大潮"),   # 新月大潮
        (12.5,  16.0, "大潮"),   # 満月大潮
        (27.0,  29.53,"大潮"),   # 新月前大潮
        (2.5,   4.5,  "中潮"),   # 新月後中潮
        (4.5,   7.0,  "小潮"),
        (7.0,   8.0,  "長潮"),
        (8.0,   9.5,  "若潮"),
        (9.5,   12.5, "中潮"),   # 満月前中潮
        (16.0,  18.0, "中潮"),   # 満月後中潮
        (18.0,  20.5, "小潮"),
        (20.5,  21.5, "長潮"),
        (21.5,  23.0, "若潮"),
        (23.0,  27.0, "中潮"),   # 新月前中潮
    ]:
        if lo <= age < hi:
            return t
    return "中潮"


def calc_tide_coeff(moon_age: float) -> int:
    """潮位差係数 0〜100（大潮=100, 小潮=0）
    新月(age=0)・満月(age=14.77)で100、上弦(age=7.38)・下弦(age=22.15)で0
    cos(2π×age/14.765) は新月・満月=+1、上弦・下弦=-1 → (cos+1)/2 で正規化
    """
    angle = 2 * math.pi * moon_age / (_SYNODIC_MONTH / 2)
    coeff = (math.cos(angle) + 1) / 2
    return round(coeff * 100)


def calc_moon_phase(moon_age: float) -> str:
    """月相ラベル"""
    age = moon_age % _SYNODIC_MONTH
    if age < 1.5 or age > 28.0:
        return "新月"
    elif age < 6.5:
        return "三日月"
    elif age < 8.5:
        return "上弦"
    elif age < 13.0:
        return "十三夜"
    elif age < 16.0:
        return "満月"
    elif age < 21.0:
        return "十六夜"
    elif age < 22.5:
        return "下弦"
    else:
        return "晦日前"


def init_db(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tide_moon (
            date        TEXT PRIMARY KEY,
            moon_age    REAL,
            tide_type   TEXT,
            tide_coeff  INTEGER,
            moon_phase  TEXT
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tm_date ON tide_moon(date)")
    conn.commit()


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2023-01-01")
    parser.add_argument("--end",   default=None)
    args = parser.parse_args()

    from datetime import datetime
    start = date.fromisoformat(args.start)
    end   = date.fromisoformat(args.end) if args.end else date.today()

    conn = sqlite3.connect(DB_PATH)
    init_db(conn)

    rows = []
    cur = start
    while cur <= end:
        age   = calc_moon_age(cur)
        ttype = calc_tide_type(age)
        coeff = calc_tide_coeff(age)
        phase = calc_moon_phase(age)
        rows.append((cur.isoformat(), age, ttype, coeff, phase))
        cur += timedelta(days=1)

    conn.executemany(
        "INSERT OR REPLACE INTO tide_moon(date, moon_age, tide_type, tide_coeff, moon_phase) "
        "VALUES (?,?,?,?,?)",
        rows
    )
    conn.commit()
    conn.close()

    print(f"tide_moon.sqlite: {len(rows)}日分 ({start} 〜 {end})")

    # サンプル表示
    conn = sqlite3.connect(DB_PATH)
    print("\nサンプル（直近10日）:")
    print(f"  {'日付':<12} {'月齢':>5}  {'潮汐区分':<6}  {'係数':>4}  月相")
    for row in conn.execute(
        "SELECT date, moon_age, tide_type, tide_coeff, moon_phase "
        "FROM tide_moon ORDER BY date DESC LIMIT 10"
    ):
        print(f"  {row[0]:<12} {row[1]:>5.1f}  {row[2]:<6}  {row[3]:>4}  {row[4]}")
    conn.close()


if __name__ == "__main__":
    main()
