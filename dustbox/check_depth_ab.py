# -*- coding: utf-8 -*-
"""水深補正あり/なし A/B テスト（深さデータがある行のみ対象）"""
import csv, sys, os, math
from collections import defaultdict
sys.stdout.reconfigure(encoding='utf-8')

# backtest_v2 から関数を直接インポート
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import backtest_v2 as bt

master_rows = bt.load_master_records()
idx_area5, idx_all, doy_area5, doy_all, longterm_avg = bt.build_daily_index(master_rows)
bucket_avg, overall_avg = bt.build_depth_lookup(bt.DATA_DIR)

print(f"水深補正ルックアップ: {len(bucket_avg)}エントリ")

# 水深ありかつDEPTH_RULESコンボの行だけ抽出
results_with = []     # 水深補正あり
results_without = []  # 水深補正なし（同じ行）

def get_area5(area_str):
    for k, v in bt.PORT_TO_AREA5.items():
        if k in area_str:
            return v
    return None

depth_applied = 0
for row in master_rows:
    date_str = row.get("date", "")
    area     = row.get("area", "")
    fish     = row.get("fish", "").strip()
    if not date_str or not fish:
        continue
    area5 = get_area5(area)
    if (fish, area5) not in bt.DEPTH_RULES:
        continue

    # 水深取得
    dm_s = row.get("point_depth_min", "").strip()
    dx_s = row.get("point_depth_max", "").strip()
    try:   dm = float(dm_s) if dm_s else None
    except: dm = None
    try:   dx = float(dx_s) if dx_s else None
    except: dx = None
    depth_m = (dm + dx) / 2 if (dm and dx) else (dm or dx)
    if depth_m is None:
        continue  # 水深なし行は除外（比較対象外）

    try:
        actual = float(row["cnt_avg"])
    except:
        continue
    if actual <= 0:
        continue

    wx_row = {k: row.get(k, "") for k in
              ["wave_height","wind_speed","sea_surface_temp","tide_type","moon_age"]}

    # 水深補正あり
    res_w = bt.predict(fish, area, date_str, idx_area5, idx_all, doy_area5, doy_all,
                       longterm_avg, wx_row, depth_m=depth_m,
                       bucket_avg=bucket_avg, overall_avg=overall_avg)
    # 水深補正なし
    res_wo = bt.predict(fish, area, date_str, idx_area5, idx_all, doy_area5, doy_all,
                        longterm_avg, wx_row, depth_m=None,
                        bucket_avg=None, overall_avg=None)

    if res_w is None or res_wo is None:
        continue

    # 水深補正が実際に効いたか確認
    if abs(res_w["predicted"] - res_wo["predicted"]) > 0.01:
        depth_applied += 1

    e_w  = abs(res_w["predicted"]  - actual) / actual * 100
    e_wo = abs(res_wo["predicted"] - actual) / actual * 100
    results_with.append((fish, area5, actual, res_w["predicted"],  e_w,  row["date"]))
    results_without.append((fish, area5, actual, res_wo["predicted"], e_wo, row["date"]))

print(f"対象行: {len(results_with)}件（うち水深補正が実際に効いた: {depth_applied}件）\n")

# コンボ別 MAPE 比較
from collections import defaultdict
combo_w  = defaultdict(list)
combo_wo = defaultdict(list)
for (fish, area5, actual, pred, err, date), (_, _, _, _, err_wo, _) in zip(results_with, results_without):
    combo_w[(fish,area5)].append(err)
    combo_wo[(fish,area5)].append(err_wo)

print(f"{'コンボ':<28} {'n':>5}  {'補正なし':>8}  {'補正あり':>8}  {'改善':>7}")
print("-"*60)
total_w = []; total_wo = []
for k in sorted(combo_w.keys(), key=lambda x: -len(combo_w[x])):
    vs_w  = combo_w[k]
    vs_wo = combo_wo[k]
    n = len(vs_w)
    mape_w  = round(sum(vs_w) /n, 1)
    mape_wo = round(sum(vs_wo)/n, 1)
    diff    = round(mape_wo - mape_w, 1)
    mark = "◎" if diff >= 3 else ("○" if diff >= 1 else ("△" if diff >= 0 else "×"))
    fish, area5 = k
    print(f"  {fish}×{area5:<16} {n:>5}  {mape_wo:>7.1f}%  {mape_w:>7.1f}%  {diff:>+5.1f}pt {mark}")
    total_w.extend(vs_w); total_wo.extend(vs_wo)

print("-"*60)
n_total = len(total_w)
mape_w_all  = round(sum(total_w) /n_total, 1)
mape_wo_all = round(sum(total_wo)/n_total, 1)
print(f"  {'合計':<26} {n_total:>5}  {mape_wo_all:>7.1f}%  {mape_w_all:>7.1f}%  {round(mape_wo_all-mape_w_all,1):>+5.1f}pt")
