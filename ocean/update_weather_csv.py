#!/usr/bin/env python3
"""
update_weather_csv.py — weather/YYYY-MM.csv の日次増分追記（CI用・標準ライブラリのみ）

weather/ の最終日の翌日〜昨日(JST) を Open-Meteo (marine + archive) から取得し、
月別CSVに追記する。

背景（決定ログ 2026-08-01）:
  2026-04-04/08 の大掃除で旧 weather_fetch.py（日次追記）が「不要」と誤判定されて
  削除され、weather/*.csv が 2026-04-13 で無言停止。消費側3系統
  （crawler.py 海況表示 / x_post/insights.py 平年値比較 / crawl/build_fish_area_analysis.py）
  は生きていたため、4か月間古いCSVを読み続けた。本スクリプトはその恒久対策。
  鮮度は crawl/validate_output.py の不変条件 [60] が監視する。

設計:
  - 出力形式は export_weather_csv.py / 旧 weather_fetch.py と同一
    （1座標=1行、複数座標が同じ代表ポイント名に写像されうる、JST 3時間粒度）
  - 座標・代表名は export_weather_csv.build_coord_to_name() を共用
    （normalize/point_coords.json + data/V2 出現回数）
  - 全座標のフェッチ完了後に一括追記。部分書き込みで「日はあるが座標が欠けた」
    CSVを作らない（次回実行は最終日+1から始まるため、欠けは恒久欠損になる）
  - 成功座標が9割未満なら追記せず非0終了（無言の部分劣化を防ぐ）
  - Archive API は end=today だと 400（前日まで）。end は必ず JST 昨日

使い方:
  python ocean/update_weather_csv.py            # 増分追記（追記対象なしなら即終了）
  python ocean/update_weather_csv.py --dry-run  # 取得のみ・CSVに書かない
  python ocean/update_weather_csv.py --limit 3  # 座標数を制限（動作確認用）
"""
import csv, glob, json, os, sys, time, urllib.error, urllib.parse, urllib.request
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WX_DIR = os.path.join(BASE_DIR, "weather")
JST = timezone(timedelta(hours=9))

TARGET_HOURS = {0, 3, 6, 9, 12, 15, 18, 21}  # JST 3時間粒度
HEADERS = ["point", "date", "hour", "wave_height", "wave_period",
           "wind_speed", "wind_dir", "sst", "weather_code"]

# 代表名ロジックは export_weather_csv.py と共用（形式の分岐を作らない）
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from export_weather_csv import build_coord_to_name  # noqa: E402

MIN_SUCCESS_RATIO = 0.9  # 成功座標がこれ未満なら追記しない


def fetch_url(url, retries=3):
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < retries - 1:
                print(" 429→60s待機...", end="", flush=True)
                time.sleep(60)
                continue
            if e.code == 400:
                raise  # 範囲指定ミス等。リトライしても直らない
            if attempt == retries - 1:
                raise
            time.sleep(3)
        except Exception:
            if attempt == retries - 1:
                raise
            time.sleep(3)


def fetch_marine(lat, lon, start, end):
    params = {
        "latitude": lat, "longitude": lon,
        "hourly": "wave_height,wave_period,sea_surface_temperature",
        "start_date": start.isoformat(), "end_date": end.isoformat(),
        "timezone": "Asia/Tokyo",
    }
    return fetch_url("https://marine-api.open-meteo.com/v1/marine?" + urllib.parse.urlencode(params))


def fetch_archive(lat, lon, start, end):
    params = {
        "latitude": lat, "longitude": lon,
        "hourly": "wind_speed_10m,wind_direction_10m,weather_code",
        "start_date": start.isoformat(), "end_date": end.isoformat(),
        "timezone": "Asia/Tokyo",
        "wind_speed_unit": "ms",
    }
    return fetch_url("https://archive-api.open-meteo.com/v1/archive?" + urllib.parse.urlencode(params))


def fmt(v):
    if v is None:
        return ""
    if isinstance(v, float):
        return round(v, 1)
    return v


def find_last_date():
    """weather/YYYY-MM.csv の最終日を返す。ファイルが無ければ None。"""
    files = sorted(glob.glob(os.path.join(WX_DIR, "[0-9]" * 4 + "-" + "[0-9]" * 2 + ".csv")))
    if not files:
        return None
    last = files[-1]
    max_d = ""
    with open(last, encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            d = row.get("date") or ""
            if d > max_d:
                max_d = d
    if not max_d:
        return None
    return date.fromisoformat(max_d)


def main():
    dry_run = "--dry-run" in sys.argv
    limit = None
    if "--limit" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--limit") + 1])

    last = find_last_date()
    if last is None:
        # 初期構築は export_weather_csv.py（weather_cache.sqlite→CSV）の仕事。
        # CIで全期間フェッチを始めてしまわないよう、ここは明示エラーにする。
        print("ERROR: weather/*.csv が見つからない。初期構築は ocean/export_weather_csv.py で行うこと")
        sys.exit(1)

    start = last + timedelta(days=1)
    end = datetime.now(JST).date() - timedelta(days=1)  # Archive API は前日まで（today は 400）
    if start > end:
        print(f"追記対象なし（最終日 {last} / 昨日 {end}）")
        return

    coord_rep = build_coord_to_name()
    coords = sorted(coord_rep.keys())
    if limit:
        coords = coords[:limit]

    print(f"対象: {len(coords)}座標 × {start}〜{end}（{(end - start).days + 1}日）")

    all_rows = defaultdict(list)  # (year, month) -> rows
    failed = []
    for i, (lat, lon) in enumerate(coords):
        rep = coord_rep[(lat, lon)]
        print(f"[{i + 1:3d}/{len(coords)}] {rep} ({lat},{lon})", end=" ", flush=True)
        try:
            marine = fetch_marine(lat, lon, start, end)
            time.sleep(0.5)
            archive = fetch_archive(lat, lon, start, end)
            time.sleep(0.5)
        except Exception as e:
            print(f"ERROR: {e}")
            failed.append((rep, str(e)))
            continue

        a = archive["hourly"]
        arch = {t: (a["wind_speed_10m"][j], a["wind_direction_10m"][j], a["weather_code"][j])
                for j, t in enumerate(a["time"])}

        n = 0
        m = marine["hourly"]
        for j, t in enumerate(m["time"]):
            dt = datetime.fromisoformat(t)
            if dt.hour not in TARGET_HOURS:
                continue
            if dt.date() <= last:  # 二重追記ガード（API が範囲外を返しても既存日は書かない）
                continue
            ws, wd, wc = arch.get(t, (None, None, None))
            all_rows[(dt.year, dt.month)].append([
                rep,
                dt.strftime("%Y-%m-%d"),
                f"{dt.hour:02d}",
                fmt(m["wave_height"][j]),
                fmt(m["wave_period"][j]),
                fmt(ws),
                "" if wd is None else int(wd),
                fmt(m["sea_surface_temperature"][j]),
                "" if wc is None else int(wc),
            ])
            n += 1
        print(f"OK ({n}行)")

    n_ok = len(coords) - len(failed)
    total = sum(len(v) for v in all_rows.values())
    print(f"\nフェッチ結果: 成功 {n_ok}/{len(coords)}座標・{total}行")
    if failed:
        for rep, msg in failed[:10]:
            print(f"  失敗: {rep}: {msg}")

    if n_ok < len(coords) * MIN_SUCCESS_RATIO:
        # 部分追記すると「日はあるが座標が欠けたCSV」が恒久化するため、書かずに落とす
        print(f"ERROR: 成功座標が9割未満（{n_ok}/{len(coords)}）→ 追記せず終了")
        sys.exit(1)

    if dry_run:
        print("--dry-run: 書き込みスキップ")
        return

    for (year, month), rows in sorted(all_rows.items()):
        fname = os.path.join(WX_DIR, f"{year:04d}-{month:02d}.csv")
        is_new = not os.path.exists(fname)
        with open(fname, "a", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            if is_new:
                w.writerow(HEADERS)
            w.writerows(rows)
        print(f"  {os.path.basename(fname)}: +{len(rows)}行{'（新規）' if is_new else ''}")

    print(f"完了: {total}行追記（{start}〜{end}）")


if __name__ == "__main__":
    main()
