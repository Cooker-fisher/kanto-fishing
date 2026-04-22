"""
海洋環境マップ用JSONデータ生成。
SLA/CHL from cmems_daily, SST/水色 from weather_cache/water_color_daily.
釣果ドット from data/V2/*.csv + analysis.sqlite (combo_meta/combo_wx_params/combo_decadal).
出力: ocean_map_data.json (kuroshio_map.html が fetch で読む)
"""
import csv, glob, hashlib, json, math, os, sqlite3
from collections import defaultdict
from datetime import date, datetime, timedelta

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR   = os.path.dirname(SCRIPT_DIR)

DB_CMEMS   = os.path.join(SCRIPT_DIR, "cmems_data.sqlite")
DB_WEATHER = os.path.join(SCRIPT_DIR, "weather_cache.sqlite")
DB_ANALYSIS= os.path.join(ROOT_DIR, "analysis", "V2", "results", "analysis.sqlite")
CSV_DIR    = os.path.join(ROOT_DIR, "data", "V2")
OUT_JSON   = os.path.join(ROOT_DIR, "ocean_map_data.json")

DAYS = 30   # 直近N日分（ファイルサイズ最適化）

# 釣果ドット: 相関上位 factor → レイヤキー マッピング
FACTOR_TO_LAYER = {
    # SLA 系 → "sla"
    "kuroshio_sla_monthly": "sla", "sla_pelagic_monthly": "sla",
    "sla_approach_idx": "sla", "sla_delta": "sla", "sla_avg": "sla",
    "sla_lag30": "sla", "sla_monthly": "sla", "kuroshio_score": "sla",
    # CHL 系 → "chl"
    "chl_avg": "chl", "chl_monthly": "chl", "chl_delta": "chl",
    "nutrient_score": "chl",
    # SST / 深度水温 → "sst"
    "sst_avg": "sst", "sst_delta": "sst", "sst_gradient": "sst",
    "temp_50m": "sst", "temp_100m": "sst", "temp_100m_spring": "sst",
    "temp_100m_summer": "sst", "temp_200m": "sst", "deepwater_score": "sst",
    # 水色 → "wc"
    "water_color_pred_n": "wc", "water_color_prev_n": "wc",
}
R_THRESHOLD  = 0.30   # 採用する強相関の下限
ANOMALY_HIGH = 1.50   # 好漁日（平年比+50%以上）の閾値。HTML側で参照


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


def _decade_no(d: date) -> int:
    """日付 → 旬番号 1〜36。combo_deep_dive.py:decade_of() と同じ定義。
    月×3 + 旬（上旬/中旬/下旬）。例: 1/31 → 3（1月下旬）、12/21 → 36。"""
    dec = 1 if d.day <= 10 else (2 if d.day <= 20 else 3)
    return (d.month - 1) * 3 + dec


def _jitter(fish: str) -> tuple:
    """魚種名ハッシュで方向決定論化した ±0.002° 前後のジッタ。
    hashlib.md5 で PYTHONHASHSEED 非依存の決定論ハッシュを使う。"""
    h = int(hashlib.md5(fish.encode("utf-8")).hexdigest()[:8], 16)
    angle = (h % 360) * math.pi / 180.0
    r = 0.002
    return (round(r * math.cos(angle), 5), round(r * math.sin(angle), 5))


def build_catches(conn_analysis, csv_dir: str, start_iso: str, end_iso: str):
    """釣果ドット: data/V2/*.csv × combo_meta × combo_wx_params × combo_decadal。
    出力: {date: [{fish, ship, lat, lon, cnt_avg, cnt_min, cnt_max,
                  trip_label, top_factor, r, layer, anomaly}, ...]}
    """
    # 1. combo_meta → (fish, ship) → (lat, lon)
    meta: dict[tuple, tuple] = {}
    for f, s, lat, lon in conn_analysis.execute(
        "SELECT fish, ship, lat, lon FROM combo_meta WHERE lat IS NOT NULL AND lon IS NOT NULL"
    ):
        meta[(f, s)] = (float(lat), float(lon))

    # 2. combo_wx_params → (fish, ship) → (factor, r, layer) （海況系のみ・|r|最大1件）
    factor_keys = list(FACTOR_TO_LAYER.keys())
    placeholders = ",".join("?" * len(factor_keys))
    top: dict[tuple, tuple] = {}
    for f, s, factor, r in conn_analysis.execute(
        f"SELECT fish, ship, factor, r FROM combo_wx_params "
        f"WHERE metric='cnt_avg' AND r IS NOT NULL AND ABS(r) >= ? "
        f"AND factor IN ({placeholders})",
        (R_THRESHOLD, *factor_keys),
    ):
        key = (f, s)
        prev = top.get(key)
        if prev is None or abs(float(r)) > abs(prev[1]):
            top[key] = (factor, float(r), FACTOR_TO_LAYER[factor])

    # 3. combo_decadal → (fish, ship, decade_no) → avg_cnt
    dec: dict[tuple, float] = {}
    for f, s, dn, avg in conn_analysis.execute(
        "SELECT fish, ship, decade_no, avg_cnt FROM combo_decadal WHERE avg_cnt IS NOT NULL"
    ):
        dec[(f, s, int(dn))] = float(avg)

    # 4. CSV 走査対象月を列挙（標準パターン: start_month〜end_month を月次インクリメント）
    start_d = datetime.strptime(start_iso, "%Y-%m-%d").date()
    end_d   = datetime.strptime(end_iso, "%Y-%m-%d").date()
    months: list = []
    y, m = start_d.year, start_d.month
    while (y, m) <= (end_d.year, end_d.month):
        months.append(f"{y:04d}-{m:02d}")
        m += 1
        if m > 12:
            m = 1; y += 1
    print(f"  対象月: {len(months)}件 {months}")

    # (date, ship, fish) → best record (max cnt_avg)
    agg: dict[tuple, dict] = {}
    miss_meta = 0
    rows_read = 0
    skip_empty_cnt = 0
    for ym in months:
        path = os.path.join(csv_dir, f"{ym}.csv")
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                if str(row.get("is_cancellation", "")).strip() == "1":
                    continue
                fish = (row.get("tsuri_mono") or "").strip()
                ship = (row.get("ship") or "").strip()
                date_raw = (row.get("date") or "").strip()
                if not fish or not ship or not date_raw:
                    continue
                # 日付正規化 YYYY/MM/DD → YYYY-MM-DD
                ds = date_raw.replace("/", "-")
                if not (start_iso <= ds <= end_iso):
                    continue
                rows_read += 1
                if (fish, ship) not in meta:
                    miss_meta += 1
                    continue
                # cnt_avg が空文字列の行はスキップ（数報告なし・釣果不明）
                cnt_avg_raw = (row.get("cnt_avg") or "").strip()
                if not cnt_avg_raw:
                    skip_empty_cnt += 1
                    continue
                try:
                    cnt_avg = float(cnt_avg_raw)
                except ValueError:
                    skip_empty_cnt += 1
                    continue
                cnt_min_raw = (row.get("cnt_min") or "").strip()
                cnt_max_raw = (row.get("cnt_max") or "").strip()
                try:
                    cnt_min = float(cnt_min_raw) if cnt_min_raw else cnt_avg
                except ValueError:
                    cnt_min = cnt_avg
                try:
                    cnt_max = float(cnt_max_raw) if cnt_max_raw else cnt_avg
                except ValueError:
                    cnt_max = cnt_avg
                trip_no = (row.get("trip_no") or "").strip()
                time_slot = (row.get("time_slot") or "").strip()
                trip_label = time_slot or (f"{trip_no}便" if trip_no else "")
                key = (ds, ship, fish)
                prev = agg.get(key)
                if prev is None or cnt_avg > prev["cnt_avg"]:
                    agg[key] = {
                        "cnt_avg": cnt_avg, "cnt_min": cnt_min, "cnt_max": cnt_max,
                        "trip_label": trip_label,
                    }

    # 5. decade_no / anomaly / ジッタ付与 → catches[date]
    catches: dict[str, list] = defaultdict(list)
    jitter_cache: dict[str, tuple] = {}
    for (ds, ship, fish), rec in agg.items():
        lat, lon = meta[(fish, ship)]
        dn = _decade_no(datetime.strptime(ds, "%Y-%m-%d").date())
        avg_base = dec.get((fish, ship, dn))
        anomaly = None
        if avg_base and avg_base > 0:
            anomaly = round(rec["cnt_avg"] / avg_base, 2)
        tf = top.get((fish, ship))
        if fish not in jitter_cache:
            jitter_cache[fish] = _jitter(fish)
        dlat, dlon = jitter_cache[fish]
        catches[ds].append({
            "fish": fish, "ship": ship,
            "lat": round(lat + dlat, 5), "lon": round(lon + dlon, 5),
            "cnt_avg": round(rec["cnt_avg"], 1),
            "cnt_min": round(rec["cnt_min"], 1),
            "cnt_max": round(rec["cnt_max"], 1),
            "trip_label": rec["trip_label"],
            "top_factor": tf[0] if tf else None,
            "r": round(tf[1], 3) if tf else None,
            "layer": tf[2] if tf else None,
            "anomaly": anomaly,
        })

    n_points = sum(len(v) for v in catches.values())
    print(f"  catches: {len(catches)}日 / 合計 {n_points}ポイント  "
          f"(CSV読み {rows_read}行 / meta欠損 {miss_meta}行 / "
          f"cnt_avg空スキップ {skip_empty_cnt}行 / top_factor有 {len(top)}コンボ)")
    return dict(catches)


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

    print("釣果 取得中...", flush=True)
    catches_data = build_catches(conn_a, CSV_DIR, start_iso, end_iso)

    out = {
        "generated": end_iso,
        "days": DAYS,
        "r_threshold": R_THRESHOLD,
        "anomaly_high": ANOMALY_HIGH,
        "layers": {
            "sla": {"coords": sla_coords, "daily": sla_daily},
            "chl": {"coords": chl_coords, "daily": chl_daily},
            "sst": {"coords": sst_coords, "daily": sst_daily},
            "wc":  {"coords": wc_coords,  "daily": wc_daily},
        },
        "catches": catches_data,
    }
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))

    size_kb = os.path.getsize(OUT_JSON) // 1024
    print(f"出力: {OUT_JSON}  ({size_kb:,} KB)")

    conn_c.close(); conn_w.close(); conn_a.close()


if __name__ == "__main__":
    main()
