# -*- coding: utf-8 -*-
"""
backtest_holdout.py  ホールドアウト・バックテスト
  学習期間 : CUTOFF_DATE 以前のデータでベースラインインデックスを構築
  テスト期間: CUTOFF_DATE 以降のデータで predict() を実行
  → インサンプル評価（backtest_v2.py）より現実に近い精度測定
"""
import csv, sys, os, json
from datetime import datetime
from collections import defaultdict

sys.stdout.reconfigure(encoding='utf-8')

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import backtest_v2 as bt

CUTOFF_DATE = "2025/07/01"   # これ以前 = 学習、以降 = テスト

# ── データ読み込み ────────────────────────────────────────────────────
all_rows = bt.load_master_records()
train_rows = [r for r in all_rows if r["date"] <  CUTOFF_DATE]
test_rows  = [r for r in all_rows if r["date"] >= CUTOFF_DATE]

print(f"学習: {len(train_rows)}件 (〜{CUTOFF_DATE}前日)")
print(f"テスト: {len(test_rows)}件 ({CUTOFF_DATE}〜)")

# ── 学習データのみでインデックス構築 ─────────────────────────────────
idx_area5, idx_all, doy_area5, doy_all, longterm_avg = bt.build_daily_index(train_rows)
bucket_avg, overall_avg = bt.build_depth_lookup(bt.DATA_DIR)

# ── 全テスト行で予測 ─────────────────────────────────────────────────
def get_depth(row):
    dm_s = row.get("point_depth_min", "").strip()
    dx_s = row.get("point_depth_max", "").strip()
    try:   dm = float(dm_s) if dm_s else None
    except: dm = None
    try:   dx = float(dx_s) if dx_s else None
    except: dx = None
    return (dm + dx) / 2 if (dm and dx) else (dm or dx)

records = []
for row in test_rows:
    date_str = row.get("date", "")
    area     = row.get("area", "")
    fish     = row.get("fish", "")
    if not date_str or not fish or fish == "不明":
        continue
    try:
        actual = float(row["cnt_avg"])
    except:
        continue
    if actual <= 0:
        continue
    try:    actual_min = float(row["cnt_min"]) if row.get("cnt_min") else None
    except: actual_min = None
    try:    actual_max = float(row["cnt_max"]) if row.get("cnt_max") else None
    except: actual_max = None

    wx_row = {k: row.get(k, "") for k in
              ["wave_height","wind_speed","sea_surface_temp","tide_type","moon_age"]}
    depth_m = get_depth(row)

    result = bt.predict(fish, area, date_str,
                        idx_area5, idx_all, doy_area5, doy_all, longterm_avg,
                        wx_row, depth_m=depth_m,
                        bucket_avg=bucket_avg, overall_avg=overall_avg)
    if result is None:
        continue

    baseline = result["baseline"]
    e = bt.mape(result["predicted"], actual)
    area5 = result["area5"] or "不明"
    pmin, pmax = result["cnt_min"], result["cnt_max"]

    pred_dir   = "up"   if result["predicted"] > baseline * 1.05 else \
                 "down" if result["predicted"] < baseline * 0.95 else "flat"
    actual_dir = "up"   if actual > baseline * 1.05 else \
                 "down" if actual < baseline * 0.95 else "flat"

    avg_hit = pmin <= actual <= pmax if e is not None else None
    if actual_min is not None and actual_max is not None and e is not None:
        overlap_hit = actual_max >= pmin and actual_min <= pmax
    else:
        overlap_hit = avg_hit

    records.append({
        "date":         date_str,
        "fish":         fish,
        "area5":        area5,
        "actual":       round(actual, 1),
        "actual_min":   actual_min,
        "actual_max":   actual_max,
        "predicted":    result["predicted"],
        "baseline":     round(baseline, 1),
        "baseline_src": result["baseline_src"],
        "cnt_min":      pmin,
        "cnt_max":      pmax,
        "error":        round(e, 1) if e is not None else None,
        "avg_hit":      avg_hit,
        "overlap_hit":  overlap_hit,
        "dir_correct":  pred_dir == actual_dir,
    })

print(f"予測件数: {len(records)}件\n")

# ── 集計 ─────────────────────────────────────────────────────────────
def stat(recs):
    errs  = [r["error"]       for r in recs if r["error"]       is not None]
    avgs  = [r["avg_hit"]     for r in recs if r["avg_hit"]     is not None]
    ovlps = [r["overlap_hit"] for r in recs if r["overlap_hit"] is not None]
    dirs  = [r["dir_correct"] for r in recs]
    if not errs:
        return None, None, None, None, 0
    return (round(sum(errs)/len(errs),   1),
            round(sum(avgs)/len(avgs)*100,  1) if avgs  else 0,
            round(sum(ovlps)/len(ovlps)*100,1) if ovlps else 0,
            round(sum(dirs)/len(dirs)*100,  1) if dirs  else 0,
            len(errs))

combo_stats = defaultdict(list)
fish_stats  = defaultdict(list)
for r in records:
    combo_stats[(r["fish"], r["area5"])].append(r)
    fish_stats[r["fish"]].append(r)

AREAS = ["東京湾奥", "東京湾口", "相模湾", "外房", "茨城", "不明"]

print(f"{'魚種':<12} {'エリア':<8} {'n':>5} {'MAPE':>7} {'avg的中':>8} {'重複的中':>8} {'方向%':>7}  精度")
print("-" * 75)
prev_fish = None
for fish in sorted(fish_stats, key=lambda f: -len(fish_stats[f])):
    for a5 in AREAS:
        recs = combo_stats.get((fish, a5), [])
        if not recs:
            continue
        m, ha, ho, d, n = stat(recs)
        if m is None:
            continue
        grade = "A" if m < 40 else "B" if m < 60 else "C" if m < 90 else "D"
        if fish != prev_fish:
            prev_fish = fish
        print(f"  {fish:<10} {a5:<8} {n:>5}  {m:>6.1f}%  {ha:>7.1f}%  {ho:>7.1f}%  {d:>6.1f}%  [{grade}]")
    m, ha, ho, d, n = stat(fish_stats[fish])
    if m is not None:
        print(f"  {'  └'+fish+'計':<18} {n:>5}  {m:>6.1f}%  {ha:>7.1f}%  {ho:>7.1f}%  {d:>6.1f}%")
    print()

print("-" * 75)
m, ha, ho, d, n = stat(records)
if m:
    print(f"  {'全体（ホールドアウト）':<18} {n:>5}  {m:>6.1f}%  {ha:>7.1f}%  {ho:>7.1f}%  {d:>6.1f}%")

# ベースラインソース内訳
src_count = defaultdict(int)
for r in records:
    src_count[r["baseline_src"]] += 1
print(f"\nベースラインソース: " +
      ", ".join(f"{k}:{v}件" for k, v in sorted(src_count.items())))

# JSON保存
out = {
    "cutoff_date":        CUTOFF_DATE,
    "train_records":      len(train_rows),
    "test_records":       len(test_rows),
    "predicted_count":    len(records),
    "overall_mape":       m,
    "overall_avg_hit":    ha,
    "overall_overlap_hit": ho,
    "combo_stats": {
        f"{fish}×{a5}": {"n": n, "mape": m2, "avg_hit": ha2, "overlap_hit": ho2, "dir_rate": d2}
        for (fish, a5), recs in combo_stats.items()
        for m2, ha2, ho2, d2, n in [stat(recs)] if m2 is not None
    },
}
with open("backtest_holdout_result.json", "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=2)
print("\n詳細 → backtest_holdout_result.json")
