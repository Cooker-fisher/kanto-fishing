#!/usr/bin/env python3
"""
ヤリイカ×儀兵衛丸 単独/複数ポイント別分析
n_points_visited で分割して各グループにポイントモデルを適用する。

point名の命名規則:
  '長井沖_単独'   : point_place1='長井沖' かつ n_points_visited=1
  '城ヶ島沖_単独' : point_place1='城ヶ島沖' かつ n_points_visited=1
  '複数ポイント'  : n_points_visited>=2

実行:
  python analysis/V2/methods/analyze_yaruka_gihei.py
"""

import csv, os, sqlite3, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _paths import ROOT_DIR, RESULTS_DIR, DATA_DIR, NORMALIZE_DIR, OCEAN_DIR

# combo_deep_dive から必要な関数をすべてインポート
from combo_deep_dive import (
    load_records,
    load_ship_coords, load_wx_coords_list, load_ship_area, load_decadal,
    _build_decadal_from_records,
    section_backtest_rolling,
    save_point_backtest, save_point_wx_params,
    DB_WX, DB_TIDE, DB_TYPHOON, DB_CMEMS, DB_ANA,
)

FISH = "ヤリイカ"
SHIP = "儀兵衛丸"
RESULT_FILE = os.path.join(ROOT_DIR, "tmp_yaruka_result.txt")


def build_npv_map():
    """data/V2/*.csv から (date, trip_no) → n_points_visited のマップを構築"""
    npv_map = {}
    for fn in sorted(os.listdir(DATA_DIR)):
        if not fn.endswith(".csv") or fn == "cancellations.csv":
            continue
        with open(os.path.join(DATA_DIR, fn), encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                if row.get("ship", "").strip() != SHIP:
                    continue
                if row.get("tsuri_mono", "").strip() != FISH:
                    continue
                date_str = row.get("date", "").strip()
                trip_no = int(row.get("trip_no") or 0)
                npv = row.get("n_points_visited", "").strip()
                try:
                    npv_int = int(npv) if npv else 0
                except ValueError:
                    npv_int = 0
                npv_map[(date_str, trip_no)] = npv_int
    return npv_map


def run():
    print(f"[analyze_yaruka_gihei] {FISH}×{SHIP} 単独/複数ポイント別分析開始", flush=True)

    # 全レコードをロード（load_records は main_sub=メイン・cnt_avg>0 フィルタ済み）
    all_records = load_records(FISH, ship_filter=SHIP)
    if not all_records:
        print("ERROR: レコードが0件です。", flush=True)
        return

    # 乗合フィルタ（deep_dive と同じロジック）
    _noboat = [r for r in all_records if r.get("is_boat", 0) == 0]
    if len(_noboat) >= 30 and len(_noboat) < len(all_records):
        all_records = _noboat

    print(f"  全レコード数: {len(all_records)}", flush=True)

    # n_points_visited を join
    npv_map = build_npv_map()
    for r in all_records:
        key = (r["date"], r.get("trip_no", 0))
        r["n_points_visited"] = npv_map.get(key, 0)

    # グループ分割
    nagai_single   = [r for r in all_records
                      if r.get("point") == "長井沖" and r.get("n_points_visited") == 1]
    shiroga_single = [r for r in all_records
                      if r.get("point") == "城ヶ島沖" and r.get("n_points_visited") == 1]
    multi_pt       = [r for r in all_records
                      if r.get("n_points_visited", 0) >= 2]

    groups = [
        ("長井沖_単独",   nagai_single),
        ("城ヶ島沖_単独", shiroga_single),
        ("複数ポイント",  multi_pt),
    ]

    print("  グループ件数:", flush=True)
    for name, grp in groups:
        months = sorted(set(r["date"][:7] for r in grp))
        print(f"    {name}: N={len(grp)}, 月数={len(months)}", flush=True)

    # 共通リソース
    ship_coords  = load_ship_coords()
    wx_coords    = load_wx_coords_list()
    ship_area    = load_ship_area()
    conn_wx      = sqlite3.connect(DB_WX)      if (os.path.exists(DB_WX)      and os.path.getsize(DB_WX)      > 0) else None
    conn_tide    = sqlite3.connect(DB_TIDE)    if (os.path.exists(DB_TIDE)    and os.path.getsize(DB_TIDE)    > 0) else None
    conn_typhoon = sqlite3.connect(DB_TYPHOON) if (os.path.exists(DB_TYPHOON) and os.path.getsize(DB_TYPHOON) > 0) else None
    conn_cmems   = sqlite3.connect(DB_CMEMS)   if (os.path.exists(DB_CMEMS)   and os.path.getsize(DB_CMEMS)   > 0) else None

    decadal_global = load_decadal(FISH, SHIP)

    results = {}  # {name: (N, wmape, r, bl2)}

    for name, grp in groups:
        n = len(grp)
        months = sorted(set(r["date"][:7] for r in grp))
        print(f"\n  [{name}] N={n}, 月数={len(months)}", flush=True)

        if n < 30:
            print(f"    スキップ: N={n} < MIN_N_COMBO=30", flush=True)
            results[name] = (n, None, None, None)
            continue
        if len(months) < 6:
            print(f"    スキップ: 月数={len(months)} < MIN_MONTHS=6", flush=True)
            results[name] = (n, None, None, None)
            continue

        # ポイント固有デカダル（N>=6旬分あれば使う、足りなければ全体で補完）
        pt_decadal = _build_decadal_from_records(grp)
        decadal = pt_decadal if len(pt_decadal) >= 6 else decadal_global

        try:
            bt_lines, bt_data, range_bt_data, star_bt_data, season_thr, wx_params_data, modal_lat, modal_lon, best_cmems = \
                section_backtest_rolling(
                    grp, ship_coords, wx_coords, conn_wx, ship_area, decadal,
                    conn_tide=conn_tide, conn_typhoon=conn_typhoon,
                    fish=FISH, conn_cmems=conn_cmems
                )
        except Exception as e:
            import traceback
            print(f"    ERROR: {e}", flush=True)
            traceback.print_exc()
            results[name] = (n, None, None, None)
            continue

        # H=0 cnt_avg 結果を抽出
        h0_row = None
        for row in bt_data:
            if row[0] == "cnt_avg" and row[1] == 0:
                h0_row = row
                break

        if h0_row is not None:
            metric, H, rv, mae, mape, smape, wmape, rmse, dacc, \
                good_r, bad_r, gprec, grec, gf1, bprec, brec, bf1, acc3, n_valid, r_own, \
                bl0w, bl0m, bl0r, bl1w, bl1m, bl1r, bl2w, bl2m, bl2r = h0_row
            results[name] = (n_valid, wmape, rv, bl2w)
            print(f"    H=0 cnt_avg: N={n_valid}, wMAPE={wmape:.1f}%, r={rv:+.3f}, BL2={bl2w:.1f}%", flush=True)
        else:
            results[name] = (n, None, None, None)
            print(f"    H=0 cnt_avg: 結果なし", flush=True)

        # DB保存
        if bt_data:
            save_point_backtest(FISH, SHIP, name, bt_data)
            print(f"    combo_point_backtest に保存: {name}", flush=True)
        if wx_params_data:
            save_point_wx_params(FISH, SHIP, name, wx_params_data, modal_lat, modal_lon)
            print(f"    combo_point_wx_params に保存: {name}", flush=True)

    # 接続クローズ
    for c in [conn_wx, conn_tide, conn_typhoon, conn_cmems]:
        if c is not None:
            try:
                c.close()
            except Exception:
                pass

    # 結果テキスト出力
    lines = [f"ヤリイカ×儀兵衛丸 単独/複数ポイント別バックテスト結果 (H=0, cnt_avg)"]
    lines.append("=" * 60)
    for name, (n_val, wmape, rv, bl2) in results.items():
        if wmape is None:
            lines.append(f"{name}: N={n_val}, スキップ（サンプル不足）")
        else:
            lines.append(
                f"{name}: N={n_val}, wmape={wmape:.1f}%, r={rv:+.3f}, bl2={bl2:.1f}%"
            )
    lines.append("")
    lines.append("参考（旧ポイントモデル）:")
    lines.append("  長井沖 (全): N=70, wmape=35.4%, r=+0.538, bl2=48.1%")
    lines.append("  城ヶ島沖(全): N=93, wmape=42.9%, r=+0.523, bl2=65.0%")

    result_text = "\n".join(lines)
    print("\n" + result_text, flush=True)

    with open(RESULT_FILE, "w", encoding="utf-8") as f:
        f.write(result_text + "\n")
    print(f"\n結果を {RESULT_FILE} に保存しました。", flush=True)

    return results


if __name__ == "__main__":
    run()
