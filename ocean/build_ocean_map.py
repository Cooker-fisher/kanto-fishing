"""
海洋環境マップ用JSONデータ生成。
SLA/CHL from cmems_daily, SST/水色 from weather_cache/water_color_daily.
出力: ocean_map_data.json (kuroshio_map.html が fetch で読む)
"""
import json, os, sqlite3
from collections import defaultdict
from datetime import date, timedelta

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR   = os.path.dirname(SCRIPT_DIR)

DB_CMEMS   = os.path.join(SCRIPT_DIR, "cmems_data.sqlite")
DB_WEATHER = os.path.join(SCRIPT_DIR, "weather_cache.sqlite")
DB_ANALYSIS= os.path.join(ROOT_DIR, "analysis", "V2", "results", "analysis.sqlite")
OUT_JSON   = os.path.join(ROOT_DIR, "ocean_map_data.json")

DAYS = 30   # 直近N日分（ファイルサイズ最適化）


def _round4(v):
    return round(float(v), 4)


def _grid_key(lat, lon, step=0.25):
    """0.25°グリッドのキー（nearest center）。"""
    return (round(round(lat / step) * step, 4), round(round(lon / step) * step, 4))


def build_sla(conn_cmems, start_iso: str, end_iso: str):
    """SLA: cmems_daily (0.25°, 610点)。座標リスト + 日別値配列 形式で返す。"""
    # SLA coords (固定610点)
    coord_rows = conn_cmems.execute(
        "SELECT DISTINCT lat, lon FROM cmems_daily WHERE sla IS NOT NULL ORDER BY lat, lon"
    ).fetchall()
    coords = [(_round4(r[0]), _round4(r[1])) for r in coord_rows]
    coord_idx = {(lat, lon): i for i, (lat, lon) in enumerate(coords)}

    daily: dict[str, list] = {}
    rows = conn_cmems.execute(
        "SELECT date, lat, lon, sla FROM cmems_daily "
        "WHERE date >= ? AND date <= ? AND sla IS NOT NULL",
        (start_iso, end_iso),
    ).fetchall()
    for date_str, lat, lon, sla in rows:
        k = (_round4(lat), _round4(lon))
        if k in coord_idx:
            day = daily.setdefault(date_str, [None] * len(coords))
            day[coord_idx[k]] = round(float(sla), 3)
    return coords, daily


def build_chl(conn_cmems, start_iso: str, end_iso: str):
    """CHL: cmems_daily (1/24°, ~5000点) を 0.25°グリッドに集約して返す。"""
    # 0.25°グリッドに集約
    agg: dict[str, dict[tuple, list]] = {}  # date -> gridkey -> [vals]
    rows = conn_cmems.execute(
        "SELECT date, lat, lon, chl FROM cmems_daily "
        "WHERE date >= ? AND date <= ? AND chl IS NOT NULL",
        (start_iso, end_iso),
    ).fetchall()
    for date_str, lat, lon, chl in rows:
        key = _grid_key(lat, lon)
        agg.setdefault(date_str, {}).setdefault(key, []).append(float(chl))

    # 座標リスト (全日付のunion)
    all_keys: set = set()
    for day_dict in agg.values():
        all_keys.update(day_dict.keys())
    coords = sorted(all_keys)
    coord_idx = {k: i for i, k in enumerate(coords)}

    daily: dict[str, list] = {}
    for date_str, day_dict in agg.items():
        vals = [None] * len(coords)
        for key, vlist in day_dict.items():
            vals[coord_idx[key]] = round(sum(vlist) / len(vlist), 4)
        daily[date_str] = vals

    return [(lat, lon) for lat, lon in coords], daily


def build_sst(conn_weather, start_iso: str, end_iso: str):
    """SST: weather_cache 5〜12時平均。"""
    agg: dict[str, dict[tuple, list]] = defaultdict(lambda: defaultdict(list))
    rows = conn_weather.execute(
        """SELECT date(dt), lat, lon, sst FROM weather
           WHERE date(dt) >= ? AND date(dt) <= ?
             AND time(dt) >= '05:00' AND time(dt) <= '12:00'
             AND sst IS NOT NULL""",
        (start_iso, end_iso),
    ).fetchall()
    for date_str, lat, lon, sst in rows:
        agg[date_str][(_round4(lat), _round4(lon))].append(float(sst))

    coord_keys: set = set()
    for day_dict in agg.values():
        coord_keys.update(day_dict.keys())
    coords = sorted(coord_keys)
    coord_idx = {k: i for i, k in enumerate(coords)}

    daily: dict[str, list] = {}
    for date_str, day_dict in agg.items():
        vals = [None] * len(coords)
        for key, vlist in day_dict.items():
            vals[coord_idx[key]] = round(sum(vlist) / len(vlist), 2)
        daily[date_str] = vals

    return [(lat, lon) for lat, lon in coords], daily


def build_wc(conn_analysis, start_iso: str, end_iso: str):
    """水色スコア: water_color_daily。"""
    agg: dict[str, dict[tuple, float]] = {}
    rows = conn_analysis.execute(
        "SELECT date, lat, lon, wc_pred FROM water_color_daily WHERE date >= ? AND date <= ?",
        (start_iso, end_iso),
    ).fetchall()
    for date_str, lat, lon, wc in rows:
        agg.setdefault(date_str, {})[(_round4(lat), _round4(lon))] = round(float(wc), 3)

    coord_keys: set = set()
    for day_dict in agg.values():
        coord_keys.update(day_dict.keys())
    coords = sorted(coord_keys)
    coord_idx = {k: i for i, k in enumerate(coords)}

    daily: dict[str, list] = {}
    for date_str, day_dict in agg.items():
        vals = [None] * len(coords)
        for key, val in day_dict.items():
            vals[coord_idx[key]] = val
        daily[date_str] = vals

    return [(lat, lon) for lat, lon in coords], daily


def main():
    today = date.today()
    start = today - timedelta(days=DAYS)
    start_iso = start.isoformat()
    end_iso   = today.isoformat()

    print(f"期間: {start_iso} 〜 {end_iso}  ({DAYS}日)")

    conn_c = sqlite3.connect(DB_CMEMS)
    conn_w = sqlite3.connect(DB_WEATHER)
    conn_a = sqlite3.connect(DB_ANALYSIS)

    print("SLA 取得中...", flush=True)
    sla_coords, sla_daily = build_sla(conn_c, start_iso, end_iso)
    print(f"  SLA: {len(sla_coords)}座標  {len(sla_daily)}日")

    print("CHL 取得中...", flush=True)
    chl_coords, chl_daily = build_chl(conn_c, start_iso, end_iso)
    print(f"  CHL: {len(chl_coords)}座標  {len(chl_daily)}日")

    print("SST 取得中...", flush=True)
    sst_coords, sst_daily = build_sst(conn_w, start_iso, end_iso)
    print(f"  SST: {len(sst_coords)}座標  {len(sst_daily)}日")

    print("水色 取得中...", flush=True)
    wc_coords, wc_daily = build_wc(conn_a, start_iso, end_iso)
    print(f"  水色: {len(wc_coords)}座標  {len(wc_daily)}日")

    out = {
        "generated": end_iso,
        "days": DAYS,
        "layers": {
            "sla": {"coords": sla_coords, "daily": sla_daily},
            "chl": {"coords": chl_coords, "daily": chl_daily},
            "sst": {"coords": sst_coords, "daily": sst_daily},
            "wc":  {"coords": wc_coords,  "daily": wc_daily},
        },
    }
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))

    size_kb = os.path.getsize(OUT_JSON) // 1024
    print(f"出力: {OUT_JSON}  ({size_kb:,} KB)")

    conn_c.close(); conn_w.close(); conn_a.close()


if __name__ == "__main__":
    main()
