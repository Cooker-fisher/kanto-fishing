"""
build_analysis_map.py — 海洋環境データ可視化（分析精度向上ツール）

用途: ローカル分析専用。GitHub Pages には上げない。
分析の主ツールは kuroshio_map.html（インタラクティブ）。
本スクリプトは以下3用途に特化：
  1. CHL 解像度比較（1/24° vs 0.25° 集約）
  2. 水色補間品質チェック（153観測点→正則グリッドのアーティファクト確認）
  3. 4レイヤ同時比較スナップショット（SLA/CHL/水色/DO）

使い方:
  python ocean/build_analysis_map.py --date 2026-04-03       # 4パネルスナップショット
  python ocean/build_analysis_map.py --compare-chl           # CHL解像度比較（最新日）
  python ocean/build_analysis_map.py --compare-chl --date 2026-04-03  # CHL比較（指定日）
"""

import os, sys, sqlite3, json, argparse, shutil
from datetime import date, timedelta
from collections import defaultdict

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from scipy.interpolate import griddata

sys.stdout.reconfigure(encoding="utf-8")

SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR    = os.path.dirname(SCRIPT_DIR)
DB_CMEMS    = os.path.join(SCRIPT_DIR, "cmems_data.sqlite")
DB_WEATHER  = os.path.join(SCRIPT_DIR, "weather_cache.sqlite")
DB_ANALYSIS = os.path.join(ROOT_DIR, "analysis", "V2", "results", "analysis.sqlite")
SHIPS_JSON  = os.path.join(ROOT_DIR, "crawl", "ships.json")
OUT_DIR     = os.path.join(SCRIPT_DIR, "maps")

# 地図の範囲（関東沿岸）
LAT_MIN, LAT_MAX = 33.0, 37.5
LON_MIN, LON_MAX = 138.0, 141.5

# 補間用正則グリッド（水色・DO用）
GRID_LAT = np.linspace(LAT_MIN, LAT_MAX, 120)
GRID_LON = np.linspace(LON_MIN, LON_MAX, 100)
GRID_LON2, GRID_LAT2 = np.meshgrid(GRID_LON, GRID_LAT)

# 主要河口（水色の参照点として表示）
RIVER_MOUTHS = {
    "多摩川": (35.55, 139.78),
    "相模川": (35.32, 139.37),
    "利根川": (35.76, 140.83),
    "江戸川": (35.68, 139.89),
}


# ─── データロード ─────────────────────────────────────────────────────────────

def load_ships():
    """有効船宿の座標を返す {name: (lat, lon)}（combo_metaから取得）。"""
    if not os.path.exists(DB_ANALYSIS):
        return {}
    conn = sqlite3.connect(DB_ANALYSIS)
    rows = conn.execute(
        "SELECT DISTINCT ship, lat, lon FROM combo_meta "
        "WHERE lat IS NOT NULL AND lon IS NOT NULL"
    ).fetchall()
    conn.close()
    result = {}
    for ship, lat, lon in rows:
        if lat and lon and LAT_MIN <= lat <= LAT_MAX and LON_MIN <= lon <= LON_MAX:
            result[ship] = (float(lat), float(lon))
    return result


def load_sla(conn, start_iso, end_iso):
    """SLA: 0.125° / 日次。{date_str: [(lat,lon,val), ...]}"""
    rows = conn.execute(
        "SELECT date, lat, lon, sla FROM cmems_daily "
        "WHERE date >= ? AND date <= ? AND sla IS NOT NULL "
        "AND lat BETWEEN ? AND ? AND lon BETWEEN ? AND ?",
        (start_iso, end_iso, LAT_MIN, LAT_MAX, LON_MIN, LON_MAX),
    ).fetchall()
    data = defaultdict(list)
    for d, lat, lon, v in rows:
        data[d].append((float(lat), float(lon), float(v)))
    return dict(data)


def load_chl_hires(conn, start_iso, end_iso):
    """CHL 高解像度（1/24°）。{date_str: [(lat,lon,val), ...]}"""
    rows = conn.execute(
        "SELECT date, lat, lon, chl FROM cmems_daily "
        "WHERE date >= ? AND date <= ? AND chl IS NOT NULL "
        "AND lat BETWEEN ? AND ? AND lon BETWEEN ? AND ?",
        (start_iso, end_iso, LAT_MIN, LAT_MAX, LON_MIN, LON_MAX),
    ).fetchall()
    data = defaultdict(list)
    for d, lat, lon, v in rows:
        data[d].append((float(lat), float(lon), float(v)))
    return dict(data)


def load_chl_agg(conn, start_iso, end_iso, step=0.25):
    """CHL を 0.25° に集約。{date_str: [(lat,lon,val), ...]}"""
    hires = load_chl_hires(conn, start_iso, end_iso)
    agg = {}
    for d, pts in hires.items():
        cell = defaultdict(list)
        for lat, lon, v in pts:
            key = (round(round(lat / step) * step, 4),
                   round(round(lon / step) * step, 4))
            cell[key].append(v)
        agg[d] = [(k[0], k[1], sum(vl) / len(vl)) for k, vl in cell.items()]
    return agg


def load_do(conn, start_iso, end_iso):
    """DO 表層（depth_m <= 10）。{date_str: [(lat,lon,val), ...]}"""
    rows = conn.execute(
        "SELECT date, lat, lon, do FROM cmems_depth "
        "WHERE date >= ? AND date <= ? AND do IS NOT NULL "
        "AND depth_m <= 10 "
        "AND lat BETWEEN ? AND ? AND lon BETWEEN ? AND ?",
        (start_iso, end_iso, LAT_MIN, LAT_MAX, LON_MIN, LON_MAX),
    ).fetchall()
    # 同座標の複数深度を平均
    data_raw = defaultdict(lambda: defaultdict(list))
    for d, lat, lon, v in rows:
        data_raw[d][(float(lat), float(lon))].append(float(v))
    data = {}
    for d, coord_vals in data_raw.items():
        data[d] = [(lat, lon, sum(vl) / len(vl)) for (lat, lon), vl in coord_vals.items()]
    return data


def load_wc(conn_analysis, start_iso, end_iso):
    """水色スコア（weather_cache 非正則格子）。{date_str: [(lat,lon,val), ...]}"""
    try:
        rows = conn_analysis.execute(
            "SELECT date, lat, lon, wc_pred FROM water_color_daily "
            "WHERE date >= ? AND date <= ? "
            "AND lat BETWEEN ? AND ? AND lon BETWEEN ? AND ?",
            (start_iso, end_iso, LAT_MIN, LAT_MAX, LON_MIN, LON_MAX),
        ).fetchall()
    except Exception:
        return {}
    data = defaultdict(list)
    for d, lat, lon, v in rows:
        data[d].append((float(lat), float(lon), float(v)))
    return dict(data)


# ─── 補間ユーティリティ ─────────────────────────────────────────────────────

def scatter_to_grid(pts, method="linear"):
    """非正則座標リスト [(lat,lon,val)] → 正則グリッド (120×100)。"""
    if not pts:
        return None
    lats = np.array([p[0] for p in pts])
    lons = np.array([p[1] for p in pts])
    vals = np.array([p[2] for p in pts])
    try:
        grid = griddata(
            np.column_stack([lats, lons]),
            vals,
            (GRID_LAT2, GRID_LON2),
            method=method,
        )
    except Exception:
        return None
    return grid


# ─── 描画ユーティリティ ─────────────────────────────────────────────────────

def _base_ax(fig, ax, title, ships=None, rivers=False):
    """地図の基本設定（タイトル・軸・船宿プロット）。"""
    ax.set_xlim(LON_MIN, LON_MAX)
    ax.set_ylim(LAT_MIN, LAT_MAX)
    ax.set_xlabel("経度", fontsize=7)
    ax.set_ylabel("緯度", fontsize=7)
    ax.set_title(title, fontsize=9, fontweight="bold")
    ax.tick_params(labelsize=6)
    ax.set_facecolor("#d0e8f5")  # 海色背景
    # 船宿
    if ships:
        slats = [v[0] for v in ships.values()]
        slons = [v[1] for v in ships.values()]
        ax.scatter(slons, slats, s=12, c="red", marker="^",
                   zorder=5, linewidths=0.5, edgecolors="white", label="船宿")
    # 河口
    if rivers:
        for name, (rlat, rlon) in RIVER_MOUTHS.items():
            ax.plot(rlon, rlat, "bs", markersize=6, zorder=6)
            ax.annotate(name, (rlon, rlat), fontsize=5, color="navy",
                        xytext=(2, 2), textcoords="offset points")


def _imshow(ax, grid, cmap, vmin, vmax, label, date_str, ships, rivers=False):
    """補間グリッドをimshowで描画。"""
    if grid is None:
        ax.text(0.5, 0.5, "データなし", transform=ax.transAxes,
                ha="center", va="center", fontsize=10)
        return
    im = ax.imshow(
        grid,
        origin="lower",
        extent=[LON_MIN, LON_MAX, LAT_MIN, LAT_MAX],
        cmap=cmap, vmin=vmin, vmax=vmax,
        aspect="auto", interpolation="bilinear",
    )
    plt.colorbar(im, ax=ax, fraction=0.03, pad=0.01, label=label)
    _base_ax(None, ax, f"{label}  {date_str}", ships, rivers)


def _scatter_raw(ax, pts, cmap, vmin, vmax, label, date_str, ships, s=4):
    """生座標をscatterで描画（高解像度用）。"""
    if not pts:
        ax.text(0.5, 0.5, "データなし", transform=ax.transAxes,
                ha="center", va="center", fontsize=10)
        return
    lats = [p[0] for p in pts]
    lons = [p[1] for p in pts]
    vals = [p[2] for p in pts]
    sc = ax.scatter(lons, lats, c=vals, s=s, cmap=cmap,
                    vmin=vmin, vmax=vmax, linewidths=0, zorder=3)
    plt.colorbar(sc, ax=ax, fraction=0.03, pad=0.01, label=label)
    _base_ax(None, ax, f"{label}  {date_str}", ships)


# ─── 出力：CHL 解像度比較 ───────────────────────────────────────────────────

def compare_chl(conn_cmems, date_str, ships):
    """CHL 1/24° vs 0.25° の比較図を出力。"""
    out_dir = os.path.join(OUT_DIR, "chl_compare")
    os.makedirs(out_dir, exist_ok=True)

    hires = load_chl_hires(conn_cmems, date_str, date_str)
    agg   = load_chl_agg(conn_cmems, date_str, date_str)

    pts_hi  = hires.get(date_str, [])
    pts_agg = agg.get(date_str, [])

    fig, axes = plt.subplots(1, 2, figsize=(14, 6))
    fig.suptitle(f"CHL 解像度比較  {date_str}", fontsize=12, fontweight="bold")

    vmin, vmax = 0.0, 3.0

    # 左: 1/24° 高解像度（scatter）
    _scatter_raw(axes[0], pts_hi, "YlGn", vmin, vmax,
                 f"CHL 1/24°（{len(pts_hi)}点）", date_str, ships, s=3)
    axes[0].set_facecolor("#d0e8f5")

    # 右: 0.25° 集約（scatter）
    _scatter_raw(axes[1], pts_agg, "YlGn", vmin, vmax,
                 f"CHL 0.25°集約（{len(pts_agg)}点）", date_str, ships, s=20)
    axes[1].set_facecolor("#d0e8f5")

    plt.tight_layout()
    out_path = os.path.join(out_dir, f"{date_str}.png")
    plt.savefig(out_path, dpi=120, bbox_inches="tight")
    plt.close()
    print(f"  CHL比較: {out_path}")
    return out_path


# ─── 出力：日次4パネル（全レイヤ） ─────────────────────────────────────────

def daily_panel(date_str, sla_data, chl_data, wc_data, do_data, ships):
    """1日分の SLA/CHL/水色/DO 4パネルを PNG に出力。"""
    out_dir = os.path.join(OUT_DIR, "daily")
    os.makedirs(out_dir, exist_ok=True)

    fig, axes = plt.subplots(2, 2, figsize=(16, 12))
    fig.suptitle(f"海洋環境マップ  {date_str}", fontsize=13, fontweight="bold")

    # SLA
    pts_sla = sla_data.get(date_str, [])
    grid_sla = scatter_to_grid(pts_sla)
    _imshow(axes[0, 0], grid_sla, "RdBu_r", -0.4, 0.4,
            "SLA 海面高度偏差 (m)  ← 黒潮位置", date_str, ships)

    # CHL 高解像度（tricontourf 的な scatter）
    pts_chl = chl_data.get(date_str, [])
    _scatter_raw(axes[0, 1], pts_chl, "YlGn", 0.0, 3.0,
                 "CHL クロロフィル (mg/m³)  ← ベイト密度", date_str, ships, s=2)
    axes[0, 1].set_facecolor("#d0e8f5")

    # 水色（補間）
    pts_wc = wc_data.get(date_str, [])
    grid_wc = scatter_to_grid(pts_wc, method="nearest")
    _imshow(axes[1, 0], grid_wc, "Blues_r", 0.0, 1.0,
            "水色スコア  0=濁り 1=澄み", date_str, ships, rivers=True)

    # DO 表層
    pts_do = do_data.get(date_str, [])
    grid_do = scatter_to_grid(pts_do)
    _imshow(axes[1, 1], grid_do, "RdYlGn", 50, 350,
            "DO 溶存酸素 (mmol/m³)  ← <62で青潮危険", date_str, ships)

    plt.tight_layout()
    out_path = os.path.join(out_dir, f"{date_str}.png")
    plt.savefig(out_path, dpi=100, bbox_inches="tight")
    plt.close()
    return out_path


# ─── 水色専用：最新1日の詳細ヒートマップ ──────────────────────────────────

def wc_detail(date_str, wc_data, ships):
    """水色ヒートマップ詳細図（河口影響パターン確認用）。"""
    out_dir = os.path.join(OUT_DIR, "wc_detail")
    os.makedirs(out_dir, exist_ok=True)

    pts = wc_data.get(date_str, [])
    if not pts:
        print(f"  水色詳細: {date_str} データなし")
        return

    fig, axes = plt.subplots(1, 2, figsize=(16, 7))
    fig.suptitle(f"水色スコア詳細  {date_str}\n（0=濁り=茶色 / 1=澄み=青）",
                 fontsize=11, fontweight="bold")

    # 左: nearest-neighbor 補間（輪郭線あり）
    grid = scatter_to_grid(pts, method="nearest")
    if grid is not None:
        im = axes[0].imshow(
            grid, origin="lower",
            extent=[LON_MIN, LON_MAX, LAT_MIN, LAT_MAX],
            cmap="BrBG", vmin=0.0, vmax=1.0,
            aspect="auto", interpolation="nearest",
        )
        plt.colorbar(im, ax=axes[0], label="水色スコア")
    _base_ax(None, axes[0], f"Nearest-neighbor補間（{len(pts)}点）", ships, rivers=True)
    axes[0].set_facecolor("#d0e8f5")

    # 右: 生データ scatter（密度確認）
    lats = [p[0] for p in pts]
    lons = [p[1] for p in pts]
    vals = [p[2] for p in pts]
    sc = axes[1].scatter(lons, lats, c=vals, s=6, cmap="BrBG",
                         vmin=0.0, vmax=1.0, linewidths=0)
    plt.colorbar(sc, ax=axes[1], label="水色スコア")
    _base_ax(None, axes[1], f"生データ scatter（{len(pts)}点・グリッド密度確認）",
             ships, rivers=True)
    axes[1].set_facecolor("#d0e8f5")

    plt.tight_layout()
    out_path = os.path.join(out_dir, f"{date_str}.png")
    plt.savefig(out_path, dpi=120, bbox_inches="tight")
    plt.close()
    print(f"  水色詳細: {out_path}")
    return out_path


# ─── メイン ─────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="海洋環境データ可視化（分析ツール）")
    ap.add_argument("--date", default=date.today().isoformat(),
                    help="対象日 YYYY-MM-DD（デフォルト=今日）")
    ap.add_argument("--compare-chl", action="store_true", help="CHL 解像度比較図を生成")
    args = ap.parse_args()

    os.makedirs(OUT_DIR, exist_ok=True)
    target_date = args.date
    print(f"対象日: {target_date}")

    conn_c = sqlite3.connect(DB_CMEMS)
    conn_a = sqlite3.connect(DB_ANALYSIS)
    ships  = load_ships()
    print(f"船宿: {len(ships)}件")

    # CHL 解像度比較
    if args.compare_chl:
        print("\n[CHL解像度比較]")
        compare_chl(conn_c, target_date, ships)

    # 4パネルスナップショット + 水色詳細（常に実行）
    print(f"\n[4パネルスナップショット: {target_date}]")
    sla_data = load_sla(conn_c, target_date, target_date)
    chl_data = load_chl_hires(conn_c, target_date, target_date)
    wc_data  = load_wc(conn_a, target_date, target_date)
    do_data  = load_do(conn_c, target_date, target_date)
    out = daily_panel(target_date, sla_data, chl_data, wc_data, do_data, ships)
    print(f"  出力: {out}")

    print(f"\n[水色詳細: {target_date}]")
    wc_detail(target_date, wc_data, ships)

    conn_c.close(); conn_a.close()
    print(f"\n完了。出力先: {OUT_DIR}")


if __name__ == "__main__":
    main()
