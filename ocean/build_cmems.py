#!/usr/bin/env python3
"""
build_cmems.py — CMEMS から海洋データを取得して cmems_data.sqlite に保存

[Phase 1] cmems_daily テーブル（表層・日次）
  sla  Sea Level Anomaly (m)         黒潮位置指標
  chl  Chlorophyll-a (mg/m³)         ベイトフィッシュ指標
  sss  Sea Surface Salinity (PSU)    水塊識別

[Phase 2] cmems_depth テーブル（深度別・日次）
  temp  水温 (°C)                    深場魚生息推定（キンメ・アマダイ等）
  do    溶存酸素 (mmol/m³)           青潮検出（<62 で危険）
  no3   硝酸塩 (mmol/m³)             ベイト先行指標

[使い方]
  python ocean/build_cmems.py                        # 全変数・全期間
  python ocean/build_cmems.py --start 2026-01-01     # 差分更新
  python ocean/build_cmems.py --test                 # 直近30日のみ
  python ocean/build_cmems.py --phase 1              # Phase 1 のみ
  python ocean/build_cmems.py --phase 2              # Phase 2 のみ
  python ocean/build_cmems.py --workers 5            # 並列数指定（デフォルト3）
"""

import os
import sys
import sqlite3
import argparse
import tempfile
import uuid
from datetime import date, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.stdout.reconfigure(encoding="utf-8")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH  = os.path.join(BASE_DIR, "cmems_data.sqlite")

START_DATE_DEFAULT = "2023-01-01"

BBOX = dict(
    minimum_latitude=33.0,
    maximum_latitude=37.0,
    minimum_longitude=138.0,
    maximum_longitude=141.5,
)

# 深度取得レベル (m) — サーバー側の最近傍グリッドに丸められる
DEPTH_LEVELS = [0.49, 5.08, 10.0, 20.0, 50.0, 100.0, 200.0, 500.0]

# ─── Phase 1: 表層データセット ─────────────────────────────────────────────
DATASETS_SURFACE = {
    "sla": {
        "my":  "cmems_obs-sl_glo_phy-ssh_my_allsat-l4-duacs-0.125deg_P1D",
        "nrt": "cmems_obs-sl_glo_phy-ssh_nrt_allsat-l4-duacs-0.125deg_P1D",
        "var": "sla",
    },
    "chl": {
        "my":  "cmems_obs-oc_glo_bgc-plankton_my_l4-gapfree-multi-4km_P1D",
        "nrt": "cmems_obs-oc_glo_bgc-plankton_nrt_l4-gapfree-multi-4km_P1D",
        "var": "CHL",
    },
    "sss": {
        "my":  None,
        "nrt": "cmems_obs-mob_glo_phy-sss_nrt_multi_P1D",
        "var": "sos",
    },
}

# ─── Phase 2: 深度別データセット ───────────────────────────────────────────
DATASETS_DEPTH = {
    "temp": {
        # GLORYS12 水温（potential temperature）
        "my":  "cmems_mod_glo_phy_my_0.083deg_P1D-m",
        "nrt": "cmems_mod_glo_phy_anfc_0.083deg_P1D-m",
        "var": "thetao",
    },
    "do": {
        # 溶存酸素 (o2)
        "my":  "cmems_mod_glo_bgc_my_0.25deg_P1D-m",
        "nrt": "cmems_mod_glo_bgc-bio_anfc_0.25deg_P1D-m",
        "var": "o2",
    },
    "no3": {
        # 硝酸塩
        "my":  "cmems_mod_glo_bgc_my_0.25deg_P1D-m",
        "nrt": "cmems_mod_glo_bgc-nut_anfc_0.25deg_P1D-m",
        "var": "no3",
    },
}


# ─── DB 初期化 ───────────────────────────────────────────────────────────────

def init_db(conn: sqlite3.Connection):
    conn.executescript("""
        -- Phase 1: 表層日次
        CREATE TABLE IF NOT EXISTS cmems_daily (
            lat   REAL    NOT NULL,
            lon   REAL    NOT NULL,
            date  TEXT    NOT NULL,
            sla   REAL,
            chl   REAL,
            sss   REAL,
            PRIMARY KEY (lat, lon, date)
        );
        CREATE INDEX IF NOT EXISTS idx_cmems_latlon ON cmems_daily(lat, lon);
        CREATE INDEX IF NOT EXISTS idx_cmems_date   ON cmems_daily(date);

        -- Phase 2: 深度別日次
        CREATE TABLE IF NOT EXISTS cmems_depth (
            lat     REAL    NOT NULL,
            lon     REAL    NOT NULL,
            date    TEXT    NOT NULL,
            depth_m REAL    NOT NULL,
            temp    REAL,
            do      REAL,
            no3     REAL,
            PRIMARY KEY (lat, lon, date, depth_m)
        );
        CREATE INDEX IF NOT EXISTS idx_cdepth_latlon ON cmems_depth(lat, lon);
        CREATE INDEX IF NOT EXISTS idx_cdepth_date   ON cmems_depth(date);
        CREATE INDEX IF NOT EXISTS idx_cdepth_depth  ON cmems_depth(depth_m);
    """)
    conn.commit()


# ─── チャンク生成 ────────────────────────────────────────────────────────────

def _month_chunks(start: str, end: str):
    """(chunk_start, chunk_end) のリストを月単位で返す。"""
    chunks = []
    cur = date.fromisoformat(start)
    end_d = date.fromisoformat(end)
    while cur <= end_d:
        if cur.month == 12:
            chunk_end = date(cur.year + 1, 1, 1) - timedelta(days=1)
        else:
            chunk_end = date(cur.year, cur.month + 1, 1) - timedelta(days=1)
        chunk_end = min(chunk_end, end_d)
        chunks.append((cur.isoformat(), chunk_end.isoformat()))
        cur = chunk_end + timedelta(days=1)
    return chunks


# ─── CMEMS 取得（1チャンク） ─────────────────────────────────────────────────

def _fetch_chunk(cfg: dict, start: str, end: str, tmp_dir: str,
                 depth_range: tuple = None) -> str | None:
    """MY → NRT の順で 1チャンク取得。失敗したら None。"""
    try:
        import copernicusmarine
    except ImportError:
        print("[ERROR] pip install copernicusmarine 'xarray>=2024.7.0' netCDF4 h5py pandas")
        sys.exit(1)

    out_path = os.path.join(tmp_dir, f"cmems_{uuid.uuid4().hex}.nc")
    extra = {}
    if depth_range:
        extra["minimum_depth"] = depth_range[0]
        extra["maximum_depth"] = depth_range[1]

    for which in ("my", "nrt"):
        dataset_id = cfg.get(which)
        if not dataset_id:
            continue
        try:
            copernicusmarine.subset(
                dataset_id=dataset_id,
                variables=[cfg["var"]],
                start_datetime=f"{start}T00:00:00",
                end_datetime=f"{end}T23:59:59",
                output_filename=out_path,
                **BBOX,
                **extra,
            )
            return out_path
        except Exception as e:
            msg = str(e)
            if os.path.exists(out_path):
                os.remove(out_path)
            # 時間範囲超過は WARN、それ以外は ERROR
            level = "WARN" if "exceed the dataset coordinates" in msg or "No data" in msg else "ERROR"
            print(f"    [{level}] {which.upper()} {dataset_id[:50]}: {msg[:80]}", flush=True)

    return None


# ─── NetCDF → rows 変換 ───────────────────────────────────────────────────────

def _nc_to_surface_rows(nc_path: str, var_name: str) -> list:
    """表層 NetCDF → [(lat, lon, date_str, value), ...]"""
    try:
        import xarray as xr
        import numpy as np
    except ImportError:
        print("[ERROR] pip install 'xarray>=2024.7.0' netCDF4 h5py")
        sys.exit(1)

    ds = xr.open_dataset(nc_path)
    actual_var = _find_var(ds, var_name)
    if not actual_var:
        ds.close()
        return []

    da = ds[actual_var]
    lat_dim, lon_dim, time_dim = _find_dims(da)
    if not (lat_dim and lon_dim and time_dim):
        ds.close()
        return []

    # depth 次元があれば最表層を選択
    for edim in [d for d in da.dims if d not in (lat_dim, lon_dim, time_dim)]:
        da = da.isel({edim: 0})

    rows = []
    for ti, t in enumerate(da[time_dim].values):
        date_str = str(t)[:10]
        for li, lat in enumerate(da[lat_dim].values):
            for loi, lon in enumerate(da[lon_dim].values):
                val = float(da.isel({time_dim: ti, lat_dim: li, lon_dim: loi}).values)
                if np.isnan(val):
                    val = None
                rows.append((round(float(lat), 4), round(float(lon), 4), date_str, val))
    ds.close()
    return rows


def _nc_to_depth_rows(nc_path: str, var_name: str, col_name: str) -> list:
    """深度別 NetCDF → [(lat, lon, date_str, depth_m, col_name, value), ...]"""
    try:
        import xarray as xr
        import numpy as np
    except ImportError:
        sys.exit(1)

    ds = xr.open_dataset(nc_path)
    actual_var = _find_var(ds, var_name)
    if not actual_var:
        ds.close()
        return []

    da = ds[actual_var]
    lat_dim, lon_dim, time_dim = _find_dims(da)
    depth_dim = next((d for d in da.dims if "depth" in d.lower() or d == "elevation"), None)
    if not (lat_dim and lon_dim and time_dim):
        ds.close()
        return []

    rows = []
    if depth_dim:
        depths = da[depth_dim].values
        # 目的深度に最も近いインデックスを選択
        target_depths = DEPTH_LEVELS
        depth_indices = []
        for td in target_depths:
            idx = int(abs(depths - td).argmin())
            actual_d = float(depths[idx])
            if (idx, actual_d) not in [(i, d) for i, d in depth_indices]:
                depth_indices.append((idx, round(actual_d, 2)))

        for ti, t in enumerate(da[time_dim].values):
            date_str = str(t)[:10]
            for di, actual_d in depth_indices:
                for li, lat in enumerate(da[lat_dim].values):
                    for loi, lon in enumerate(da[lon_dim].values):
                        val = float(da.isel({time_dim: ti, depth_dim: di, lat_dim: li, lon_dim: loi}).values)
                        if np.isnan(val):
                            val = None
                        rows.append((round(float(lat), 4), round(float(lon), 4),
                                     date_str, actual_d, col_name, val))
    else:
        # depth なし → 表層として depth_m=0 で記録
        for ti, t in enumerate(da[time_dim].values):
            date_str = str(t)[:10]
            for li, lat in enumerate(da[lat_dim].values):
                for loi, lon in enumerate(da[lon_dim].values):
                    val = float(da.isel({time_dim: ti, lat_dim: li, lon_dim: loi}).values)
                    if np.isnan(val):
                        val = None
                    rows.append((round(float(lat), 4), round(float(lon), 4),
                                 date_str, 0.0, col_name, val))
    ds.close()
    return rows


def _find_var(ds, var_name: str):
    if var_name in ds:
        return var_name
    for v in ds.data_vars:
        if v.lower() == var_name.lower():
            return v
    print(f"    [WARN] 変数 '{var_name}' なし。利用可能: {list(ds.data_vars)}")
    return None


def _find_dims(da):
    lat_dim  = next((d for d in da.dims if "lat" in d.lower()), None)
    lon_dim  = next((d for d in da.dims if "lon" in d.lower()), None)
    time_dim = next((d for d in da.dims if "time" in d.lower()), None)
    return lat_dim, lon_dim, time_dim


# ─── 並列取得ワーカー ────────────────────────────────────────────────────────

def _worker_surface(args):
    """ThreadPoolExecutor から呼ばれる表層取得ワーカー。"""
    key, cfg, chunk_start, chunk_end, tmp_dir = args
    print(f"  [{key.upper()}] {chunk_start}〜{chunk_end}", flush=True)
    nc = _fetch_chunk(cfg, chunk_start, chunk_end, tmp_dir)
    if nc and os.path.exists(nc):
        rows = _nc_to_surface_rows(nc, cfg["var"])
        print(f"    → {len(rows)} rows", flush=True)
        os.remove(nc)
        return key, rows
    return key, []


def _worker_depth(args):
    """ThreadPoolExecutor から呼ばれる深度取得ワーカー。"""
    key, cfg, chunk_start, chunk_end, tmp_dir = args
    print(f"  [{key.upper()}] {chunk_start}〜{chunk_end}", flush=True)
    nc = _fetch_chunk(cfg, chunk_start, chunk_end, tmp_dir,
                      depth_range=(0.0, 550.0))
    if nc and os.path.exists(nc):
        rows = _nc_to_depth_rows(nc, cfg["var"], key)
        print(f"    → {len(rows)} rows", flush=True)
        os.remove(nc)
        return key, rows
    return key, []


# ─── DB 書き込み ─────────────────────────────────────────────────────────────

def upsert_surface(conn: sqlite3.Connection, key: str, rows: list):
    col = key  # sla / chl / sss
    for lat, lon, date_str, val in rows:
        conn.execute(
            f"INSERT INTO cmems_daily (lat, lon, date, {col}) VALUES (?,?,?,?) "
            f"ON CONFLICT(lat,lon,date) DO UPDATE SET {col}=excluded.{col}",
            (lat, lon, date_str, val),
        )
    conn.commit()
    print(f"  [{key.upper()}] {len(rows)} rows upsert 完了", flush=True)


def upsert_depth(conn: sqlite3.Connection, col: str, rows: list):
    """rows = [(lat, lon, date, depth_m, col_name, value), ...]"""
    for lat, lon, date_str, depth_m, _, val in rows:
        conn.execute(
            f"INSERT INTO cmems_depth (lat, lon, date, depth_m, {col}) VALUES (?,?,?,?,?) "
            f"ON CONFLICT(lat,lon,date,depth_m) DO UPDATE SET {col}=excluded.{col}",
            (lat, lon, date_str, depth_m, val),
        )
    conn.commit()
    print(f"  [{col.upper()}] {len(rows)} rows upsert 完了", flush=True)


# ─── メイン ──────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start",   default=START_DATE_DEFAULT)
    parser.add_argument("--end",     default=date.today().isoformat())
    parser.add_argument("--test",    action="store_true", help="直近30日のみ")
    parser.add_argument("--phase",   type=int, choices=[1, 2], help="1 or 2 のみ実行")
    parser.add_argument("--workers", type=int, default=3, help="並列取得数（デフォルト3）")
    args = parser.parse_args()

    if args.test:
        args.start = (date.today() - timedelta(days=30)).isoformat()
        args.end   = date.today().isoformat()
        print(f"[TEST] {args.start} 〜 {args.end}")

    print(f"期間: {args.start} 〜 {args.end}  workers={args.workers}")
    print(f"DB  : {DB_PATH}")

    conn = sqlite3.connect(DB_PATH)
    init_db(conn)

    run_phase1 = args.phase in (None, 1)
    run_phase2 = args.phase in (None, 2)

    with tempfile.TemporaryDirectory() as tmp_dir:

        # ── Phase 1: 表層データ（並列） ───────────────────────────────────
        if run_phase1:
            print("\n=== Phase 1: 表層データ取得（並列） ===", flush=True)
            tasks = []
            for key, cfg in DATASETS_SURFACE.items():
                for cs, ce in _month_chunks(args.start, args.end):
                    tasks.append((key, cfg, cs, ce, tmp_dir))

            print(f"チャンク数: {len(tasks)}  workers: {args.workers}", flush=True)
            all_rows = {k: [] for k in DATASETS_SURFACE}

            with ThreadPoolExecutor(max_workers=args.workers) as ex:
                futures = {ex.submit(_worker_surface, t): t for t in tasks}
                for fut in as_completed(futures):
                    key, rows = fut.result()
                    all_rows[key].extend(rows)

            for key, rows in all_rows.items():
                if rows:
                    upsert_surface(conn, key, rows)
                else:
                    print(f"  [{key.upper()}] データなし（スキップ）")

        # ── Phase 2: 深度別データ（並列） ─────────────────────────────────
        if run_phase2:
            print("\n=== Phase 2: 深度別データ取得（並列） ===", flush=True)
            tasks = []
            for key, cfg in DATASETS_DEPTH.items():
                for cs, ce in _month_chunks(args.start, args.end):
                    tasks.append((key, cfg, cs, ce, tmp_dir))

            print(f"チャンク数: {len(tasks)}  workers: {args.workers}", flush=True)
            all_rows = {k: [] for k in DATASETS_DEPTH}

            with ThreadPoolExecutor(max_workers=args.workers) as ex:
                futures = {ex.submit(_worker_depth, t): t for t in tasks}
                for fut in as_completed(futures):
                    key, rows = fut.result()
                    all_rows[key].extend(rows)

            for key, rows in all_rows.items():
                if rows:
                    upsert_depth(conn, key, rows)
                else:
                    print(f"  [{key.upper()}] データなし（スキップ）")

    # 最終確認
    r1 = conn.execute("SELECT COUNT(*), MIN(date), MAX(date) FROM cmems_daily").fetchone()
    r2 = conn.execute("SELECT COUNT(*), MIN(date), MAX(date) FROM cmems_depth").fetchone()
    print(f"\n完了:")
    print(f"  cmems_daily: {r1[0]} rows  ({r1[1]} 〜 {r1[2]})")
    print(f"  cmems_depth: {r2[0]} rows  ({r2[1]} 〜 {r2[2]})")
    conn.close()


if __name__ == "__main__":
    main()
