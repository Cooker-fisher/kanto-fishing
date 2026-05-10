"""明日の主要エリア海況予報を X 投稿用テキストとして生成する。

USAGE:
    python tools/x_post_forecast.py                 # 明日(JST)の予報を stdout 出力
    python tools/x_post_forecast.py 2026-05-12      # 指定日(YYYY-MM-DD)の予報
    python tools/x_post_forecast.py --save          # docs/x_post/ocean_forecast_{date}.txt に保存

データソース:
    - Open-Meteo Forecast API   (天気コード/気温/風)
    - Open-Meteo Marine API     (波高/うねり/SST)
    - ocean/tide_moon.sqlite    (潮汐/月齢)

対象エリア (7):
    AREAS 定数を参照。主要7エリアの代表座標。
    area_coords.json に全58エリアあるが、X(140字制限)に収めるため代表7点に絞る。

CRON 設計メモ:
    crawl.yml に組み込む場合の追加 step 案:

        - name: build ocean forecast for X post (06:00 JST)
          if: github.event.schedule == '0 21 * * *'   # UTC 21:00 = 翌 06:00 JST
          run: python3 tools/x_post_forecast.py --save

    cron 候補:
        '0 21 * * *'    毎朝 06:00 JST に翌日予報を生成
        '0 12 * * *'    毎夕 21:00 JST に翌日予報を生成（夜投稿用）

    出力先: docs/x_post/ocean_forecast_{YYYY-MM-DD}.txt
    GitHub Pages で配信されるので X 自動投稿スクリプト側から fetch 可能。

    ⚠ Open-Meteo API は無料枠 1万コール/日。1日2回 × 7エリア × 2 API = 28 コール/日 で余裕。
    ⚠ X 自動投稿は別途未実装(アカウントロック解除待ち・CLAUDE.md 参照)。
    ⚠ validate_output.py の不変条件には未追加。本機能を本番化する際は不変条件追加を検討。
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sqlite3
import sys
import urllib.request
from datetime import date, datetime, timedelta, timezone

# プロジェクトルート(このスクリプトの 1 階層上)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
MARINE_URL   = "https://marine-api.open-meteo.com/v1/marine"
TIDE_DB      = os.path.join(ROOT, "ocean", "tide_moon.sqlite")

# 主要 7 エリア (label, lat, lon, area_coords.json での近接エントリ)
AREAS = [
    ("茨城",   35.97, 140.70),  # 鹿島港
    ("外房",   35.17, 140.38),  # 勝浦川津港
    ("内房",   34.97, 139.74),  # 富浦港
    ("湾奥",   35.65, 139.90),  # 浦安
    ("横浜",   35.41, 139.67),  # 横浜本牧港
    ("三浦",   35.24, 139.71),  # 久里浜港
    ("相模湾", 35.30, 139.39),  # 茅ヶ崎港
]

# Open-Meteo weathercode → 短縮和名
WCODE = {
    0: "快晴", 1: "晴", 2: "晴/曇", 3: "曇",
    45: "霧", 48: "霧",
    51: "小雨", 53: "小雨", 55: "雨",
    56: "霙", 57: "霙",
    61: "雨", 63: "雨", 65: "強雨",
    66: "凍雨", 67: "凍雨",
    71: "雪", 73: "雪", 75: "大雪", 77: "雪",
    80: "にわか雨", 81: "にわか雨", 82: "強雨",
    85: "にわか雪", 86: "大雪",
    95: "雷雨", 96: "雷雨雹", 99: "雷雨雹",
}

DIR16 = ["北", "北北東", "北東", "東北東", "東", "東南東", "南東", "南南東",
         "南", "南南西", "南西", "西南西", "西", "西北西", "北西", "北北西"]


def deg_to_dir(deg: float) -> str:
    return DIR16[int((deg % 360) / 22.5 + 0.5) % 16]


def _hourly_window(arr, idxs):
    return [arr[i] for i in idxs if i < len(arr) and arr[i] is not None]


def fetch_atmo(lat: float, lon: float, date_iso: str) -> dict:
    url = (f"{FORECAST_URL}?latitude={lat}&longitude={lon}"
           f"&start_date={date_iso}&end_date={date_iso}"
           "&daily=weathercode,temperature_2m_max,temperature_2m_min"
           "&hourly=wind_speed_10m,wind_direction_10m,weathercode"
           "&windspeed_unit=ms&timezone=Asia%2FTokyo")
    with urllib.request.urlopen(url, timeout=15) as r:
        d = json.loads(r.read())
    daily = d.get("daily", {})
    hourly = d.get("hourly", {})
    idxs = list(range(5, 13))                # 釣り時間帯 5〜12時
    winds = _hourly_window(hourly.get("wind_speed_10m", []), idxs)
    wdirs = _hourly_window(hourly.get("wind_direction_10m", []), idxs)
    wcs   = _hourly_window(hourly.get("weathercode", []), idxs)
    wdir_mode_deg = None
    if wdirs:
        binned = [round(x / 22.5) * 22.5 for x in wdirs]
        wdir_mode_deg = max(set(binned), key=binned.count)
    return {
        "wcode": (max(set(wcs), key=wcs.count) if wcs else daily["weathercode"][0]),
        "tmax": daily["temperature_2m_max"][0],
        "tmin": daily["temperature_2m_min"][0],
        "wind_avg": (sum(winds) / len(winds)) if winds else None,
        "wind_max": max(winds) if winds else None,
        "wdir_mode_deg": wdir_mode_deg,
    }


def fetch_marine(lat: float, lon: float, date_iso: str) -> dict:
    url = (f"{MARINE_URL}?latitude={lat}&longitude={lon}"
           f"&start_date={date_iso}&end_date={date_iso}"
           "&hourly=wave_height,swell_wave_height,sea_surface_temperature"
           "&timezone=Asia%2FTokyo")
    with urllib.request.urlopen(url, timeout=15) as r:
        d = json.loads(r.read())
    h = d.get("hourly", {})
    idxs = list(range(5, 13))
    waves = _hourly_window(h.get("wave_height", []), idxs)
    swels = _hourly_window(h.get("swell_wave_height", []), idxs)
    ssts  = _hourly_window(h.get("sea_surface_temperature", []), idxs)
    return {
        "wave_avg": (sum(waves) / len(waves)) if waves else None,
        "swell_avg": (sum(swels) / len(swels)) if swels else None,
        "sst": (sum(ssts) / len(ssts)) if ssts else None,
    }


def fetch_tide(date_iso: str) -> tuple[str, float, str] | None:
    if not os.path.exists(TIDE_DB):
        return None
    con = sqlite3.connect(TIDE_DB)
    row = con.execute(
        "SELECT tide_type, moon_age, moon_phase FROM tide_moon WHERE date=?",
        (date_iso,),
    ).fetchone()
    con.close()
    return row


def build_text(target_date: str) -> str:
    rows = []
    for name, lat, lon in AREAS:
        a = fetch_atmo(lat, lon, target_date)
        m = fetch_marine(lat, lon, target_date)
        rows.append((name, a, m))

    tide = fetch_tide(target_date)
    md = target_date[5:].replace("-", "/")

    lines = [f"【明日の海況 {md}】"]
    if tide:
        tide_type, moon_age, moon_phase = tide
        lines.append(f"潮汐:{tide_type} 月齢{moon_age:.1f}({moon_phase})")
    lines.append("")
    for name, a, m in rows:
        wc = WCODE.get(a["wcode"], "曇")
        wdir = deg_to_dir(a["wdir_mode_deg"]) if a["wdir_mode_deg"] is not None else "-"
        w_avg = a["wind_avg"] or 0
        w_max = a["wind_max"] or 0
        wave = m["wave_avg"]
        swell = m["swell_avg"]
        sst = m["sst"]
        wave_s = f"{wave:.1f}" if wave is not None else "-"
        swell_s = f"{swell:.1f}" if swell is not None else "-"
        sst_s = f"{sst:.1f}" if sst is not None else "-"
        lines.append(f"■{name} {wc} {a['tmin']:.0f}/{a['tmax']:.0f}℃")
        lines.append(f"  風{wdir}{w_avg:.0f}m(最大{w_max:.0f}) 波{wave_s}m うねり{swell_s}m SST{sst_s}℃")
    lines.append("")
    lines.append("#船釣り予想 #funatsuriyoso")
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("date", nargs="?", help="YYYY-MM-DD (default: tomorrow JST)")
    parser.add_argument("--save", action="store_true",
                        help="docs/x_post/ocean_forecast_{date}.txt に保存")
    args = parser.parse_args(argv)

    if args.date:
        target = args.date
    else:
        jst = timezone(timedelta(hours=9))
        target = (datetime.now(jst).date() + timedelta(days=1)).isoformat()

    text = build_text(target)
    print(text)

    if args.save:
        out_dir = os.path.join(ROOT, "docs", "x_post")
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, f"ocean_forecast_{target}.txt")
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(text + "\n")
        print(f"\n[saved] {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
