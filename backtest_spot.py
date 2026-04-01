# -*- coding: utf-8 -*-
"""
backtest_spot.py  特定1日のスポットバックテスト（2軸評価対応）
  avg_hit    : actual_avg が予測レンジ内
  overlap_hit: 実績min〜maxと予測レンジが重なるか
"""
import csv, sys, os
from collections import defaultdict

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import backtest_v2 as bt

TARGET_DATE = "2026/03/29"   # テスト日

all_rows = bt.load_master_records()
train_rows = [r for r in all_rows if r["date"] < TARGET_DATE]
test_rows  = [r for r in all_rows if r["date"] == TARGET_DATE]

print(f"テスト日: {TARGET_DATE}  ({len(test_rows)}件)")
print(f"学習データ: {len(train_rows)}件\n")

idx_area5, idx_all, doy_area5, doy_all, longterm_avg = bt.build_daily_index(train_rows)
bucket_avg, overall_avg = bt.build_depth_lookup(bt.DATA_DIR)

def get_depth(row):
    dm_s = row.get("point_depth_min", "").strip()
    dx_s = row.get("point_depth_max", "").strip()
    try:   dm = float(dm_s) if dm_s else None
    except: dm = None
    try:   dx = float(dx_s) if dx_s else None
    except: dx = None
    return (dm + dx) / 2 if (dm and dx) else (dm or dx)

results = []
for row in test_rows:
    fish  = row.get("fish", "").strip()
    area  = row.get("area", "").strip()
    if not fish or fish == "不明": continue
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

    res = bt.predict(fish, area, TARGET_DATE,
                     idx_area5, idx_all, doy_area5, doy_all, longterm_avg,
                     wx_row, depth_m=depth_m,
                     bucket_avg=bucket_avg, overall_avg=overall_avg)
    if res is None:
        continue

    e = bt.mape(res["predicted"], actual)
    pmin, pmax = res["cnt_min"], res["cnt_max"]
    avg_hit = pmin <= actual <= pmax if e is not None else None
    if actual_min is not None and actual_max is not None and e is not None:
        overlap_hit = actual_max >= pmin and actual_min <= pmax
    else:
        overlap_hit = avg_hit

    results.append({
        "fish": fish, "area": area, "area5": res["area5"] or "不明",
        "actual": actual, "actual_min": actual_min, "actual_max": actual_max,
        "predicted": res["predicted"],
        "cnt_min": pmin, "cnt_max": pmax,
        "error": round(e, 1) if e is not None else None,
        "avg_hit": avg_hit, "overlap_hit": overlap_hit,
        "baseline_src": res["baseline_src"],
        "reasons": res["reasons"],
    })

# ── 全件表示 ───────────────────────────────────────────────────────
print(f"{'魚種':<8} {'エリア(港)':<16} {'予測レンジ':<14} {'実績レンジ':<14} {'avg':>5} {'誤差':>7}  avg  重複  src")
print("-" * 100)
for r in sorted(results, key=lambda x: (x["fish"], x["area5"])):
    rng_p = f"{r['cnt_min']}〜{r['cnt_max']}"
    if r["actual_min"] is not None and r["actual_max"] is not None:
        rng_a = f"{int(r['actual_min'])}〜{int(r['actual_max'])}"
    else:
        rng_a = "―"
    err   = f"{r['error']}%" if r["error"] is not None else "N/A"
    ma = "✓" if r["avg_hit"] else "✗"
    mo = "✓" if r["overlap_hit"] else "✗"
    print(f"  {r['fish']:<6} {r['area']:<18} {rng_p:<14} {rng_a:<14} {r['actual']:>4.0f}匹 {err:>7}  {ma}    {mo}   [{r['baseline_src']}]")

print("-" * 100)
n = len(results)
if n:
    errs    = [r["error"]       for r in results if r["error"]       is not None]
    avg_hits   = [r["avg_hit"]     for r in results if r["avg_hit"]     is not None]
    ovlp_hits  = [r["overlap_hit"] for r in results if r["overlap_hit"] is not None]
    mape_all   = round(sum(errs)/len(errs), 1) if errs else None
    avg_pct    = round(sum(avg_hits)/len(avg_hits)*100, 1) if avg_hits else 0
    ovlp_pct   = round(sum(ovlp_hits)/len(ovlp_hits)*100, 1) if ovlp_hits else 0
    print(f"合計 {n}件  MAPE: {mape_all}%  avg的中: {sum(avg_hits)}/{n}({avg_pct}%)  重複的中: {sum(ovlp_hits)}/{n}({ovlp_pct}%)\n")

# ── コンボ別サマリ ──────────────────────────────────────────────
combo = defaultdict(list)
for r in results:
    combo[(r["fish"], r["area5"])].append(r)

print(f"\n{'コンボ':<22} {'n':>4}  {'avg的中':>8}  {'重複的中':>8}  {'MAPE':>8}")
print("-" * 58)
for k, rs in sorted(combo.items(), key=lambda x: (-len(x[1]), x[0])):
    fish, a5 = k
    ah = sum(1 for r in rs if r["avg_hit"])
    oh = sum(1 for r in rs if r["overlap_hit"])
    errs = [r["error"] for r in rs if r["error"] is not None]
    m = round(sum(errs)/len(errs), 1) if errs else None
    n2 = len(rs)
    mstr = f"{m:>6.1f}%" if m else "  N/A"
    print(f"  {fish}×{a5:<12} {n2:>4}  {ah}/{n2}({round(ah/n2*100):.0f}%)   {oh}/{n2}({round(oh/n2*100):.0f}%)  {mstr}")
