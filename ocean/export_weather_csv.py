#!/usr/bin/env python3
"""
export_weather_csv.py — weather_cache.sqlite → weather/YYYY-MM.csv

weather/ に欠落している月の海況CSVを weather_cache.sqlite から生成する。
既存CSV（2024-04以降）は上書きしない。

使い方:
    python ocean/export_weather_csv.py              # 欠落月のみ生成
    python ocean/export_weather_csv.py --all        # 全月上書き再生成
"""
import csv, glob, json, os, sqlite3, sys
from collections import defaultdict
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "ocean", "weather_cache.sqlite")
PC_PATH = os.path.join(BASE_DIR, "normalize", "point_coords.json")
WX_DIR  = os.path.join(BASE_DIR, "weather")

HEADERS = ["point", "date", "hour", "wave_height", "wave_period",
           "wind_speed", "wind_dir", "sst", "weather_code"]


def build_coord_to_name():
    """point_coords.json → (lat,lon) → 代表ポイント名マップを構築。
    代表名は data/V2/*.csv のpoint_place1出現回数で決定（weather_fetch.py と同じロジック）。"""
    with open(PC_PATH, encoding="utf-8") as f:
        pc = json.load(f)

    # CSV件数でポイント代表名を決める
    point_count = defaultdict(int)
    data_dir = os.path.join(BASE_DIR, "data", "V2")
    for fpath in sorted(glob.glob(os.path.join(data_dir, "*.csv"))):
        try:
            with open(fpath, encoding="utf-8", newline="") as f:
                for row in csv.DictReader(f):
                    p = (row.get("point_place1") or "").strip()
                    if p:
                        point_count[p] += 1
        except Exception:
            continue

    # ユニーク座標グループ化
    coord_groups = defaultdict(list)
    for name, coord in pc.items():
        if coord and coord.get("lat") is not None:
            key = (float(coord["lat"]), float(coord["lon"]))
            coord_groups[key].append(name)

    # 代表名 = グループ内で最もCSV出現回数が多い名前
    coord_rep = {}
    for key, names in coord_groups.items():
        coord_rep[key] = max(names, key=lambda n: point_count.get(n, 0))

    return coord_rep


def export(force_all=False):
    if not os.path.exists(DB_PATH):
        print(f"ERROR: {DB_PATH} が見つかりません")
        return

    coord_rep = build_coord_to_name()
    print(f"座標→ポイント名マップ: {len(coord_rep)}件")

    # SQLite の lat/lon → 代表名マップ（小数第2位で丸めてマッチング）
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    # DB内の全座標を取得
    db_coords = conn.execute("SELECT DISTINCT lat, lon FROM weather ORDER BY lat, lon").fetchall()
    print(f"DB内座標: {len(db_coords)}件")

    # DB座標 → 代表名マッピング
    db_coord_to_name = {}
    unmatched = 0
    for row in db_coords:
        lat, lon = row["lat"], row["lon"]
        # 完全一致で探す
        key = (lat, lon)
        if key in coord_rep:
            db_coord_to_name[(lat, lon)] = coord_rep[key]
            continue
        # 小数第2位で丸めてマッチ
        key_r = (round(lat, 2), round(lon, 2))
        matched = False
        for ck, cn in coord_rep.items():
            if (round(ck[0], 2), round(ck[1], 2)) == key_r:
                db_coord_to_name[(lat, lon)] = cn
                matched = True
                break
        if not matched:
            unmatched += 1

    print(f"マッピング成功: {len(db_coord_to_name)}件, 未マッチ: {unmatched}件")

    # 既存月を確認
    os.makedirs(WX_DIR, exist_ok=True)
    existing_months = set()
    if not force_all:
        for f in os.listdir(WX_DIR):
            if f.endswith(".csv") and not f.startswith("."):
                existing_months.add(f.replace(".csv", ""))

    # DB内の月一覧を取得
    months_in_db = [r[0] for r in conn.execute(
        "SELECT DISTINCT substr(dt, 1, 7) FROM weather ORDER BY 1"
    ).fetchall()]

    target_months = [m for m in months_in_db if m not in existing_months]
    if not target_months:
        print("生成対象の月がありません")
        conn.close()
        return

    print(f"生成対象: {len(target_months)}月 ({target_months[0]}〜{target_months[-1]})")

    total_rows = 0
    for ym in target_months:
        # 月のデータを取得
        rows = conn.execute("""
            SELECT lat, lon, dt, wind_speed, wind_dir, sst,
                   wave_height, wave_period
            FROM weather
            WHERE substr(dt, 1, 7) = ?
            ORDER BY dt, lat, lon
        """, (ym,)).fetchall()

        csv_rows = []
        for r in rows:
            lat, lon = r["lat"], r["lon"]
            name = db_coord_to_name.get((lat, lon))
            if not name:
                continue

            # dt format: "2023-01-01T00:00" → date="2023-01-01", hour=0
            dt_str = r["dt"]
            try:
                dt = datetime.strptime(dt_str, "%Y-%m-%dT%H:%M")
            except ValueError:
                continue
            date_str = dt.strftime("%Y-%m-%d")
            hour = dt.hour

            csv_rows.append({
                "point":       name,
                "date":        date_str,
                "hour":        f"{hour:02d}",
                "wave_height": round(r["wave_height"], 2) if r["wave_height"] is not None else "",
                "wave_period": round(r["wave_period"], 1) if r["wave_period"] is not None else "",
                "wind_speed":  round(r["wind_speed"], 1) if r["wind_speed"] is not None else "",
                "wind_dir":    round(r["wind_dir"], 0) if r["wind_dir"] is not None else "",
                "sst":         round(r["sst"], 1) if r["sst"] is not None else "",
                "weather_code": "",
            })

        filepath = os.path.join(WX_DIR, f"{ym}.csv")
        with open(filepath, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=HEADERS)
            writer.writeheader()
            writer.writerows(csv_rows)
        total_rows += len(csv_rows)
        print(f"  {ym}.csv: {len(csv_rows)}行")

    conn.close()
    print(f"合計: {total_rows}行 → {WX_DIR}/")


if __name__ == "__main__":
    force = "--all" in sys.argv
    export(force_all=force)
