"""
water_color_analysis.py  v2
船宿報告 water_color フィールドを直接使った「濁り分析」

v2 改善点 (stat-reviewer 指摘対応):
  改善1: turbidity_score 中央値 → turbid_rate / clear_rate (連続0-1値)
  改善2: event_type 2系統 ("rain" 基準 / "turbid_actual" 基準)
  改善3: 魚種別 anomaly を月内比較ベース (turbid_mean / clear_mean) に置換
  改善4: 連続雨除外件数 月別内訳を report に出力
  改善5: recovery 分析で n < 10 の offset は N/A 扱い

標準ライブラリのみ + sqlite3 + csv
"""

import os
import sys
import csv
import json
import sqlite3
import statistics
import math
from collections import defaultdict
from datetime import date, datetime, timedelta

# --- パス解決 ---
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _paths import ROOT_DIR, RESULTS_DIR, DATA_DIR, NORMALIZE_DIR, OCEAN_DIR

OUT_DIR = os.path.join(RESULTS_DIR, "water_color")
os.makedirs(OUT_DIR, exist_ok=True)

WEATHER_DB = os.path.join(OCEAN_DIR, "weather_cache.sqlite")

# ---------------------------------------------------------------
# 定数
# ---------------------------------------------------------------
# turbid 判定閾値 (>= 4: やや濁り・濁り)
TURBID_THR  = 4
# clear 判定閾値  (<= 2: 澄み・やや澄み)
CLEAR_THR   = 2

# turbidity_score 変換（trip レベルの water_color → 整数スコア）
TURBIDITY_SCORE = {
    "澄み":     1,
    "やや澄み": 2,
    "薄濁り":   3,
    "やや濁り": 4,
    "濁り":     5,
}
# "普通"・"青潮"・"赤潮" は除外

# 魚種別分析用の water_color 3バケット
WC_BUCKET = {
    "澄み":     "clear",
    "やや澄み": "clear",
    "薄濁り":   "normal",
    "やや濁り": "turbid",
    "濁り":     "turbid",
}

# 雨バケット定義
RAIN_BUCKETS = [
    ("no",  0,    5),
    ("lo",  5,   20),
    ("mid", 20,  50),
    ("hi",  50, float("inf")),
]

# 改善2: 濁りイベント判定用閾値（baseline + この値を超えたら濁りイベント）
TURBID_EVENT_DELTA = 0.20   # turbid_rate が baseline より 20%pt 超

# 改善5: recovery 分析の最低サンプル数
MIN_N_RECOVERY = 10

# 改善3: 月内比較の最低日数
MIN_TURBID_DAYS_PER_MONTH = 5
MIN_CLEAR_DAYS_PER_MONTH  = 5
MIN_N_MONTHS_FISH         = 3   # 魚種ごとに最低 3 ヶ月分のレシオが必要

# エリア → ゾーン
AREA_TO_ZONE = {
    "日立久慈港":              "ibaraki",
    "大洗港":                  "ibaraki",
    "鹿島港":                  "ibaraki",
    "鹿島市新浜":              "ibaraki",
    "波崎港":                  "ibaraki",
    "飯岡港":                  "outer_boso",
    "外川港":                  "outer_boso",
    "太東港":                  "outer_boso",
    "大原港":                  "outer_boso",
    "勝浦川津港":              "outer_boso",
    "御宿岩和田港":            "outer_boso",
    "天津港":                  "outer_boso",
    "洲崎港":                  "outer_boso",
    "富浦港":                  "inner_boso",
    "金谷港":                  "inner_boso",
    "保田港":                  "inner_boso",
    "長浦":                    "inner_boso",
    "富津港":                  "inner_boso",
    "片貝港":                  "outer_boso",
    "浦安":                    "tokyo_bay",
    "東葛西":                  "tokyo_bay",
    "江戸川放水路･原木中山":   "tokyo_bay",
    "羽田":                    "tokyo_bay",
    "平和島":                  "tokyo_bay",
    "横浜本牧港":              "tokyo_bay",
    "横浜港･新山下":           "tokyo_bay",
    "金沢八景":                "tokyo_bay",
    "金沢漁港":                "tokyo_bay",
    "小柴港":                  "tokyo_bay",
    "鴨居大室港":              "tokyo_bay",
    "久里浜港":                "tokyo_bay",
    "久比里港":                "tokyo_bay",
    "長井港":                  "sagami_bay",
    "長井新宿港":              "sagami_bay",
    "長井漆山港":              "sagami_bay",
    "松輪江奈港":              "sagami_bay",
    "松輪間口港":              "sagami_bay",
    "小網代港":                "sagami_bay",
    "小坪港":                  "sagami_bay",
    "佐島":                    "sagami_bay",
    "葉山あぶずり港":          "sagami_bay",
    "茅ヶ崎港":                "sagami_bay",
    "平塚港":                  "sagami_bay",
    "大磯港":                  "sagami_bay",
    "小田原早川港":            "sagami_bay",
    "松崎港":                  "izu",
    "下田港":                  "izu",
    "沼津内港":                "izu",
    "沼津静浦":                "izu",
    "田子の浦港":              "izu",
    "由比":                    "izu",
    "吉田港":                  "izu",
    "福田港":                  "izu",
    "御前崎港":                "izu",
    "網代":                    "izu",
}

# area_coords 未登録 4 エリアの代替座標
EXTRA_AREA_COORDS = {
    "佐島":    (35.12, 139.61),
    "富津港":  (35.37, 139.84),
    "片貝港":  (35.66, 140.64),
    "網代":    (35.04, 139.07),
}


# ---------------------------------------------------------------
# ユーティリティ
# ---------------------------------------------------------------
def percentile(data, p):
    if not data:
        return None
    s = sorted(data)
    n = len(s)
    if n == 1:
        return s[0]
    idx = (p / 100.0) * (n - 1)
    lo = int(idx)
    hi = min(lo + 1, n - 1)
    return s[lo] + (s[hi] - s[lo]) * (idx - lo)

def month_of(date_str):
    """YYYY-MM-DD → 'YYYY-MM'"""
    return date_str[:7]

def write_csv(path, fieldnames, rows):
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)


# ---------------------------------------------------------------
# Step 2: CSV から trip_records 構築（前回と同じ）
# ---------------------------------------------------------------
def load_trip_records(data_dir):
    files = sorted(
        f for f in os.listdir(data_dir)
        if f.endswith(".csv") and f != "cancellations.csv"
    )
    print(f"  [Step2] CSVファイル数: {len(files)} 件, 先頭3: {files[:3]}")

    trip_rows = defaultdict(lambda: {"rows": [], "main_row": None})
    total_rows = 0
    skip_cancel = 0

    for fn in files:
        path = os.path.join(data_dir, fn)
        with open(path, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                total_rows += 1
                if row.get("is_cancellation", "0").strip() == "1":
                    skip_cancel += 1
                    continue
                ship    = row.get("ship",    "").strip()
                area    = row.get("area",    "").strip()
                raw_d   = row.get("date",    "").strip()
                trip_no = row.get("trip_no", "").strip()
                if not (ship and area and raw_d):
                    continue
                date_str = raw_d.replace("/", "-")
                key = (ship, date_str, trip_no)
                trip_rows[key]["rows"].append(row)
                ms = row.get("main_sub", "").strip()
                if ms == "メイン" and trip_rows[key]["main_row"] is None:
                    trip_rows[key]["main_row"] = row

    print(f"  [Step2] 総行数: {total_rows}, 欠航スキップ: {skip_cancel}, "
          f"unique trip units: {len(trip_rows)}")

    conflict_count = 0
    for key, val in trip_rows.items():
        wcs = set(
            r.get("water_color", "").strip()
            for r in val["rows"]
            if r.get("water_color", "").strip() in TURBIDITY_SCORE
        )
        if len(wcs) > 1:
            conflict_count += 1
    print(f"  [Step2] water_color 競合 (同 trip 内で異なる値): {conflict_count} 件")

    trip_records = []
    for (ship, date_str, trip_no), val in trip_rows.items():
        ref_row = val["main_row"] if val["main_row"] is not None else val["rows"][0]
        area = ref_row.get("area", "").strip()
        wc_raw = ref_row.get("water_color", "").strip()
        if not wc_raw:
            for r in val["rows"]:
                wc_r = r.get("water_color", "").strip()
                if wc_r:
                    wc_raw = wc_r
                    break

        tscore = TURBIDITY_SCORE.get(wc_raw)

        fish_list = []
        for r in val["rows"]:
            tm = r.get("tsuri_mono", "").strip()
            if not tm:
                continue
            cnt_raw = r.get("cnt_avg", "").strip()
            try:
                cnt = float(cnt_raw) if cnt_raw else None
            except ValueError:
                cnt = None
            fish_list.append({"tsuri_mono": tm, "cnt_avg": cnt,
                              "water_color": wc_raw})

        trip_records.append({
            "ship":            ship,
            "area":            area,
            "date":            date_str,
            "trip_no":         trip_no,
            "water_color":     wc_raw,
            "turbidity_score": tscore,
            "fish_list":       fish_list,
        })

    print(f"  [Step2] trip_records 総数: {len(trip_records)}")
    wc_reports = sum(1 for t in trip_records if t["turbidity_score"] is not None)
    print(f"  [Step2] turbidity_score 非 None: {wc_reports}")
    return trip_records


# ---------------------------------------------------------------
# Step 3: 改善1 — (area, date) の turbid_rate / clear_rate
# ---------------------------------------------------------------
def build_daily_turbidity(trip_records):
    """
    旧: median(turbidity_score) → 離散値に固着
    新: turbid_rate = turbid 報告数 / 総報告数  (連続 0-1)
        clear_rate  = clear  報告数 / 総報告数

    戻り値: dict[(area, date_str)] = {
        "turbid_rate": float,
        "clear_rate":  float,
        "n_reports":   int,
        "scores":      [int],  # 個別スコア（turbid_actual 判定で使用）
    }
    """
    ad_scores = defaultdict(list)
    for t in trip_records:
        if t["turbidity_score"] is None:
            continue
        ad_scores[(t["area"], t["date"])].append(t["turbidity_score"])

    result = {}
    for (area, date_str), scores in ad_scores.items():
        n = len(scores)
        turbid_n = sum(1 for s in scores if s >= TURBID_THR)
        clear_n  = sum(1 for s in scores if s <= CLEAR_THR)
        result[(area, date_str)] = {
            "turbid_rate": turbid_n / n,
            "clear_rate":  clear_n  / n,
            "n_reports":   n,
            "scores":      scores,
        }
    print(f"  [Step3] daily_turbidity ペア数: {len(result)}")

    # sanity: turbid_rate の全体分布
    all_tr = [v["turbid_rate"] for v in result.values()]
    if all_tr:
        print(f"  [Step3] turbid_rate 全体: "
              f"P10={percentile(all_tr,10):.3f}, P25={percentile(all_tr,25):.3f}, "
              f"P50={percentile(all_tr,50):.3f}, P75={percentile(all_tr,75):.3f}, "
              f"P90={percentile(all_tr,90):.3f}")
    return result


# ---------------------------------------------------------------
# Step 4: 24h 雨量バケット（前回と同じ実装・改善4用に月別除外を追加）
# ---------------------------------------------------------------
def load_area_coords():
    path = os.path.join(NORMALIZE_DIR, "area_coords.json")
    with open(path, encoding="utf-8") as f:
        return json.load(f)

def nearest_weather_coord(area_lat, area_lon, wx_coords):
    best, best_d = None, float("inf")
    for (lat, lon) in wx_coords:
        d = (lat - area_lat) ** 2 + (lon - area_lon) ** 2
        if d < best_d:
            best_d = d
            best = (lat, lon)
    return best

def load_wx_coords(db_path):
    conn = sqlite3.connect(db_path)
    cur  = conn.cursor()
    cur.execute("SELECT DISTINCT lat, lon FROM weather")
    coords = cur.fetchall()
    conn.close()
    return coords

def build_area_wx_map(area_coords, wx_coords):
    result = {}
    for area, info in area_coords.items():
        result[area] = nearest_weather_coord(info["lat"], info["lon"], wx_coords)
    for area, (lat, lon) in EXTRA_AREA_COORDS.items():
        if area not in result:
            result[area] = nearest_weather_coord(lat, lon, wx_coords)
    return result

def load_daily_rain_for_areas(db_path, area_wx_map, target_areas):
    """
    24h 窓: UTC dt >= D-1T09:00 AND dt < DT09:00 (8 コマぴったり)
    precipitation NULL を含む日は None を返す → スキップ
    """
    coord_to_areas = defaultdict(list)
    for area in target_areas:
        coord = area_wx_map.get(area)
        if coord:
            coord_to_areas[coord].append(area)
        else:
            print(f"  [Step4] WARNING: {area!r} 座標マップ無し → スキップ")

    coord_list = list(coord_to_areas.keys())
    print(f"  [Step4] 対象座標数: {len(coord_list)} 件, 先頭3: {coord_list[:3]}")

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    coord_day = {}

    for lat, lon in coord_list:
        cur = conn.cursor()
        cur.execute(
            "SELECT dt, precipitation FROM weather WHERE lat=? AND lon=? ORDER BY dt",
            (lat, lon)
        )
        rows = cur.fetchall()

        day_data = defaultdict(lambda: {"sum": 0.0, "n": 0, "null": False})
        for row in rows:
            dt_str    = row["dt"]
            day_part  = dt_str[:10]
            time_part = dt_str[11:]
            if time_part >= "09:00":
                d_obj = datetime.strptime(day_part, "%Y-%m-%d") + timedelta(days=1)
                fishing_day = d_obj.strftime("%Y-%m-%d")
            else:
                fishing_day = day_part
            precip = row["precipitation"]
            rec    = day_data[fishing_day]
            rec["n"] += 1
            if precip is None:
                rec["null"] = True
            else:
                rec["sum"] += precip

        for fishing_day, rec in day_data.items():
            coord_day[(lat, lon, fishing_day)] = rec

    conn.close()

    area_date_rain = {}
    for (lat, lon), areas in coord_to_areas.items():
        for (clat, clon, day_str), rec in coord_day.items():
            if clat == lat and clon == lon:
                for area in areas:
                    if rec["null"]:
                        area_date_rain[(area, day_str)] = None
                    else:
                        area_date_rain[(area, day_str)] = rec["sum"]

    total     = len(area_date_rain)
    null_cnt  = sum(1 for v in area_date_rain.values() if v is None)
    print(f"  [Step4] area×date ペア: {total}, NULL スキップ: {null_cnt}, 有効: {total - null_cnt}")
    return area_date_rain

def rain_bucket(rain_mm):
    if rain_mm is None:
        return "skip"
    for name, lo, hi in RAIN_BUCKETS:
        if lo <= rain_mm < hi:
            return name
    return "hi"


# ---------------------------------------------------------------
# Step 5 & 6: 改善2 — event_type 2系統でイベント分類
# ---------------------------------------------------------------
def build_zone_baseline(daily_turbidity):
    """
    雨無し(bucket=no) の日を用いた ゾーン別 turbid_rate baseline
    ここでは area_date_rain が不要な簡易版として
    daily_turbidity 全体の P25 を使う
    （雨無し日が大多数なのでほぼ同値）
    """
    zone_vals = defaultdict(list)
    for (area, _), val in daily_turbidity.items():
        zone = AREA_TO_ZONE.get(area)
        if zone:
            zone_vals[zone].append(val["turbid_rate"])

    baseline = {}
    for zone, vals in zone_vals.items():
        baseline[zone] = percentile(vals, 25)   # P25 を「晴天基準」とする
    print(f"  [Step5] ゾーン別 turbid_rate P25 baseline: "
          + ", ".join(f"{z}={v:.3f}" for z, v in sorted(baseline.items())))
    return baseline


def build_turbidity_timeline(daily_turbidity, area_date_rain, zone_baseline):
    """
    改善2: event_type を 2 系統で構築
      "rain"          — 24h 雨量 bucket で分類したイベント
      "turbid_actual" — 実際に turbid_rate > baseline+DELTA な日が D0 のイベント

    戻り値:
        timeline: dict[(zone, event_type, bucket, offset)] → [turbid_rate]
        rain_events: list of {area, date, bucket, zone}  (rain 系)
        turbid_events: list of {area, date, zone}         (turbid_actual 系)
        excluded_by_prior_rain: list of {area, date, bucket, month}  (改善4用)
    """
    timeline        = defaultdict(list)
    rain_events     = []
    turbid_events   = []
    excluded_prior  = []   # 改善4: 連続雨除外のログ

    # --- rain 系 ---
    for (area, d0_str), rain in area_date_rain.items():
        bucket = rain_bucket(rain)
        if bucket == "skip":
            continue
        zone = AREA_TO_ZONE.get(area)
        if not zone:
            continue

        # 連続雨除外: bucket != no のとき D-3〜D-1 に 20mm+ があれば除外
        if bucket != "no":
            d0     = datetime.strptime(d0_str, "%Y-%m-%d")
            heavy  = False
            for off in range(-3, 0):
                prev = (d0 + timedelta(days=off)).strftime("%Y-%m-%d")
                pr   = area_date_rain.get((area, prev))
                if pr is not None and pr >= 20:
                    heavy = True
                    break
            if heavy:
                excluded_prior.append({
                    "area":   area,
                    "date":   d0_str,
                    "bucket": bucket,
                    "month":  d0_str[:7],
                })
                continue

        rain_events.append({"area": area, "date": d0_str,
                            "bucket": bucket, "zone": zone})

        d0 = datetime.strptime(d0_str, "%Y-%m-%d")
        for offset in range(-3, 11):
            ts = (d0 + timedelta(days=offset)).strftime("%Y-%m-%d")
            val = daily_turbidity.get((area, ts))
            if val is not None:
                timeline[(zone, "rain", bucket, offset)].append(val["turbid_rate"])

    # --- turbid_actual 系 ---
    for (area, d0_str), val in daily_turbidity.items():
        zone  = AREA_TO_ZONE.get(area)
        if not zone:
            continue
        bl    = zone_baseline.get(zone, 0.15)
        tr    = val["turbid_rate"]
        if tr < bl + TURBID_EVENT_DELTA:
            continue
        # 連続濁り除外: D-2〜D-1 にも turbid_actual イベントがあったら除外
        d0    = datetime.strptime(d0_str, "%Y-%m-%d")
        prior_turbid = False
        for off in range(-2, 0):
            prev   = (d0 + timedelta(days=off)).strftime("%Y-%m-%d")
            pv     = daily_turbidity.get((area, prev))
            if pv and pv["turbid_rate"] >= bl + TURBID_EVENT_DELTA:
                prior_turbid = True
                break
        if prior_turbid:
            continue

        turbid_events.append({"area": area, "date": d0_str, "zone": zone})

        for offset in range(-3, 11):
            ts  = (d0 + timedelta(days=offset)).strftime("%Y-%m-%d")
            pv2 = daily_turbidity.get((area, ts))
            if pv2 is not None:
                timeline[(zone, "turbid_actual", "turbid", offset)].append(
                    pv2["turbid_rate"]
                )

    print(f"  [Step5] rain_events: {len(rain_events)} (bucket別: "
          + str({b: sum(1 for e in rain_events if e['bucket']==b)
                 for b in ['no','lo','mid','hi']}) + ")")
    print(f"  [Step5] turbid_actual events: {len(turbid_events)}")
    print(f"  [Step5] 連続雨除外: {len(excluded_prior)} 件")
    return timeline, rain_events, turbid_events, excluded_prior


# ---------------------------------------------------------------
# Step 6: ピーク・回復（改善5: n<10 cell は N/A）
# ---------------------------------------------------------------
def build_recovery_stats(timeline, rain_events, turbid_events, zone_baseline):
    """
    改善5: offset ごとに n < MIN_N_RECOVERY の cell は peak / recovery 判定から除外
    """
    zones   = sorted(set(AREA_TO_ZONE.values()))
    buckets = ["lo", "mid", "hi"]

    recovery_rows = []

    def _recovery_for_events(event_list, event_type, bucket_label):
        zone_events = defaultdict(list)
        for e in event_list:
            zone_events[e["zone"]].append(e)

        for zone in zones:
            bl  = zone_baseline.get(zone, 0.15)
            thr = bl + TURBID_EVENT_DELTA

            evs       = zone_events.get(zone, [])
            n_events  = len(evs)
            if n_events == 0:
                continue

            # ピーク日: D+1〜D+3 で turbid_rate P50 が最大 (n>=MIN_N のみ)
            peak_day = None
            peak_val = -999.0
            for off in range(1, 4):
                k    = (zone, event_type, bucket_label, off)
                vals = timeline.get(k, [])
                if len(vals) < MIN_N_RECOVERY:
                    continue
                v = percentile(vals, 50)
                if v > peak_val:
                    peak_val = v
                    peak_day = off

            # 回復 offset を 2 基準で算出
            #   recovery_offset_p50  : p50 < thr (n>=MIN_N) — 旧主指標・参考値として残す
            #   recovery_offset_both : p50 < thr AND p75 < thr (n>=MIN_N) — 新主指標
            #     「半数だけでなく上位25%も収束した」ことを要求するため実態に近い
            rec_p50  = ">10"
            rec_both = ">10"
            if peak_day is not None:
                # p50 基準（参考）
                for off in range(peak_day, 11):
                    k    = (zone, event_type, bucket_label, off)
                    vals = timeline.get(k, [])
                    if len(vals) < MIN_N_RECOVERY:
                        continue
                    if percentile(vals, 50) < thr:
                        rec_p50 = off
                        break
                # p50 AND p75 両側基準（主指標）
                for off in range(peak_day, 11):
                    k    = (zone, event_type, bucket_label, off)
                    vals = timeline.get(k, [])
                    if len(vals) < MIN_N_RECOVERY:
                        continue
                    if percentile(vals, 50) < thr and percentile(vals, 75) < thr:
                        rec_both = off
                        break

            # peak 時の turbid_rate P50
            peak_tr = None
            if peak_day is not None:
                k = (zone, event_type, bucket_label, peak_day)
                v = timeline.get(k, [])
                if v:
                    peak_tr = round(percentile(v, 50), 4)

            recovery_rows.append({
                "zone":                   zone,
                "event_type":             event_type,
                "bucket":                 bucket_label,
                "n_events":               n_events,
                "peak_day":               peak_day if peak_day is not None else "N/A",
                "peak_turbid_rate":       peak_tr if peak_tr is not None else "N/A",
                "baseline_turbid_rate":   round(bl, 4),
                "recovery_thr":           round(thr, 4),
                "recovery_offset_p50":    rec_p50,
                "recovery_offset_both":   rec_both,
            })

    # rain 系（bucket 別）
    for bucket in buckets:
        evs = [e for e in rain_events if e["bucket"] == bucket]
        _recovery_for_events(evs, "rain", bucket)

    # turbid_actual 系
    _recovery_for_events(turbid_events, "turbid_actual", "turbid")

    return recovery_rows


# ---------------------------------------------------------------
# Step 7: 改善3 — 月内比較ベースの魚種別濁り嗜好
# ---------------------------------------------------------------
def build_fish_turbidity_preference(trip_records):
    """
    月内比較:
      各 (tsuri_mono, YYYY-MM) について:
        turbid 日の cnt_avg 平均 (turbid_mean_in_month)
        clear  日の cnt_avg 平均 (clear_mean_in_month)
        レシオ = turbid_mean / clear_mean
      全期間にわたるレシオの中央値 / P25 / P75 / n_months を集計。
      n_turbid_days >= 5 かつ n_clear_days >= 5 の月のみ採用。

    戻り値: (pref_rows, summary_rows)
    """
    # (tsuri_mono, YYYY-MM, water_color_bucket) → [cnt_avg]
    monthly_fish_wc = defaultdict(list)

    for t in trip_records:
        wc   = t["water_color"]
        wc_b = WC_BUCKET.get(wc)
        if not wc_b:
            continue
        ym = month_of(t["date"])
        for f in t["fish_list"]:
            tm  = f["tsuri_mono"]
            cnt = f["cnt_avg"]
            if cnt is None:
                continue
            monthly_fish_wc[(tm, ym, wc_b)].append(cnt)

    # 魚種一覧
    all_fish = sorted(set(tm for (tm, _, _) in monthly_fish_wc.keys()))
    print(f"  [Step7] 魚種ユニーク: {len(all_fish)}")

    # 月内レシオを収集
    fish_ratios = defaultdict(list)  # tsuri_mono → [ratio_per_month]

    # 月一覧
    all_months = sorted(set(ym for (_, ym, _) in monthly_fish_wc.keys()))

    for tm in all_fish:
        for ym in all_months:
            turbid_vals = monthly_fish_wc.get((tm, ym, "turbid"), [])
            clear_vals  = monthly_fish_wc.get((tm, ym, "clear"),  [])
            if (len(turbid_vals) < MIN_TURBID_DAYS_PER_MONTH or
                    len(clear_vals) < MIN_CLEAR_DAYS_PER_MONTH):
                continue
            turbid_mean = sum(turbid_vals) / len(turbid_vals)
            clear_mean  = sum(clear_vals)  / len(clear_vals)
            if clear_mean == 0:
                continue
            ratio = turbid_mean / clear_mean
            fish_ratios[tm].append(ratio)

    # 集計
    n_with_data = sum(1 for tm in all_fish if len(fish_ratios.get(tm, [])) >= MIN_N_MONTHS_FISH)
    print(f"  [Step7] n_months >= {MIN_N_MONTHS_FISH} 魚種数: {n_with_data}")

    # pref_rows (全バケットは月内比較なので turbid/clear のみ)
    pref_rows = []
    for tm in all_fish:
        ratios = fish_ratios.get(tm, [])
        n_months = len(ratios)
        pref_rows.append({
            "tsuri_mono":         tm,
            "water_color_bucket": "turbid_vs_clear",
            "ratio_p25":          round(percentile(ratios, 25), 4) if ratios else "",
            "ratio_p50":          round(percentile(ratios, 50), 4) if ratios else "",
            "ratio_p75":          round(percentile(ratios, 75), 4) if ratios else "",
            "n_months":           n_months,
        })

    # summary_rows (n_months >= MIN_N_MONTHS_FISH のみ)
    summary_rows = []
    for tm in all_fish:
        ratios   = fish_ratios.get(tm, [])
        n_months = len(ratios)
        if n_months < MIN_N_MONTHS_FISH:
            continue
        p50 = percentile(ratios, 50)
        if p50 >= 1.1:
            pom = "plus"
        elif p50 <= 0.9:
            pom = "minus"
        else:
            pom = "flat"

        # n_total_trips: この魚種の全 water_color 報告 trip 数
        n_total = sum(
            len(monthly_fish_wc.get((tm, ym, b), []))
            for ym in all_months
            for b in ["clear", "normal", "turbid"]
        )
        n_turbid_trips = sum(
            len(monthly_fish_wc.get((tm, ym, "turbid"), []))
            for ym in all_months
        )

        summary_rows.append({
            "tsuri_mono":           tm,
            "plus_minus_flat":      pom,
            "turbid_clear_ratio_p50": round(p50, 4),
            "n_months":             n_months,
            "n_turbid_trips":       n_turbid_trips,
            "n_total_trips":        n_total,
        })

    return pref_rows, summary_rows


# ---------------------------------------------------------------
# CSV 出力
# ---------------------------------------------------------------
def save_daily_turbidity_csv(daily_turbidity, out_dir):
    rows = []
    for (area, date_str), val in sorted(daily_turbidity.items()):
        rows.append({
            "area":        area,
            "date":        date_str,
            "turbid_rate": round(val["turbid_rate"], 4),
            "clear_rate":  round(val["clear_rate"],  4),
            "n_reports":   val["n_reports"],
        })
    path = os.path.join(out_dir, "daily_turbidity_by_area.csv")
    write_csv(path, ["area", "date", "turbid_rate", "clear_rate", "n_reports"], rows)
    print(f"  [出力] {path} ({len(rows)} 行)")

def save_timeline_csv(timeline, out_dir):
    rows = []
    for (zone, event_type, bucket, offset), vals in sorted(timeline.items()):
        rows.append({
            "zone":              zone,
            "event_type":        event_type,
            "bucket":            bucket,
            "day_offset":        offset,
            "turbid_rate_p25":   round(percentile(vals, 25), 4) if vals else "",
            "turbid_rate_p50":   round(percentile(vals, 50), 4) if vals else "",
            "turbid_rate_p75":   round(percentile(vals, 75), 4) if vals else "",
            "n":                 len(vals),
        })
    path = os.path.join(out_dir, "turbidity_timeline_by_bucket.csv")
    write_csv(path, ["zone", "event_type", "bucket", "day_offset",
                     "turbid_rate_p25", "turbid_rate_p50", "turbid_rate_p75", "n"], rows)
    print(f"  [出力] {path} ({len(rows)} 行)")

def save_recovery_csv(recovery_rows, out_dir):
    path = os.path.join(out_dir, "recovery_by_bucket.csv")
    write_csv(path, ["zone", "event_type", "bucket", "n_events",
                     "peak_day", "peak_turbid_rate", "baseline_turbid_rate",
                     "recovery_thr", "recovery_offset_p50", "recovery_offset_both"],
              recovery_rows)
    print(f"  [出力] {path} ({len(recovery_rows)} 行)")

def save_fish_pref_csv(pref_rows, summary_rows, out_dir):
    path1 = os.path.join(out_dir, "fish_turbidity_preference.csv")
    write_csv(path1, ["tsuri_mono", "water_color_bucket",
                      "ratio_p25", "ratio_p50", "ratio_p75", "n_months"], pref_rows)
    print(f"  [出力] {path1} ({len(pref_rows)} 行)")

    path2 = os.path.join(out_dir, "fish_turbidity_summary.csv")
    write_csv(path2, ["tsuri_mono", "plus_minus_flat", "turbid_clear_ratio_p50",
                      "n_months", "n_turbid_trips", "n_total_trips"], summary_rows)
    print(f"  [出力] {path2} ({len(summary_rows)} 行)")


# ---------------------------------------------------------------
# report.md 生成（改善4: 連続雨除外 月別内訳）
# ---------------------------------------------------------------
def generate_report(trip_records, daily_turbidity, rain_events, turbid_events,
                    excluded_prior, recovery_rows, summary_rows, zone_baseline, out_dir):

    all_dates = sorted(set(t["date"] for t in trip_records))
    date_from = all_dates[0]  if all_dates else "?"
    date_to   = all_dates[-1] if all_dates else "?"
    n_trip    = len(trip_records)
    n_wc_trip = sum(1 for t in trip_records if t["turbidity_score"] is not None)

    # バケット別 rain イベント数
    bcnt = defaultdict(int)
    for e in rain_events:
        bcnt[e["bucket"]] += 1

    # turbid_rate 全体の P50
    all_tr  = [v["turbid_rate"] for v in daily_turbidity.values()]
    tr_p50  = round(percentile(all_tr, 50), 3) if all_tr else None
    tr_p75  = round(percentile(all_tr, 75), 3) if all_tr else None

    # 改善4: 連続雨除外 月別内訳
    excl_by_month = defaultdict(int)
    for e in excluded_prior:
        excl_by_month[e["month"]] += 1
    total_excl    = len(excluded_prior)
    total_mid_hi  = sum(1 for e in rain_events if e["bucket"] in ("mid", "hi"))
    excl_rate     = total_excl / max(total_excl + total_mid_hi, 1)

    # turbid_actual 系 timeline から D+1 の代表数値（全ゾーン合算）
    def zone_repr_recovery(event_type, bucket):
        """tokyo_bay 優先で recovery_rows から取得"""
        for zone in ["ibaraki", "outer_boso", "sagami_bay", "tokyo_bay", "izu"]:
            for r in recovery_rows:
                if (r["zone"] == zone and r["event_type"] == event_type
                        and r["bucket"] == bucket and r["n_events"] > 0):
                    return r
        return None

    # + / - / flat の魚種
    plus_fish  = sorted(
        [r for r in summary_rows if r["plus_minus_flat"] == "plus"],
        key=lambda x: -x["turbid_clear_ratio_p50"]
    )
    minus_fish = sorted(
        [r for r in summary_rows if r["plus_minus_flat"] == "minus"],
        key=lambda x: x["turbid_clear_ratio_p50"]
    )
    flat_fish  = sorted(
        [r for r in summary_rows if r["plus_minus_flat"] == "flat"],
        key=lambda x: -x["n_months"]
    )

    # 信頼度評価
    n_mid = bcnt.get("mid", 0)
    n_hi  = bcnt.get("hi",  0)
    n_turbid_ev = len(turbid_events)
    if n_mid >= 30 and len(plus_fish) >= 1 and len(minus_fish) >= 1:
        confidence = "Mid"
        conf_reason = f"mid イベント {n_mid} 件は一定の数だが、hi={n_hi} 件が少ない。月内比較ベースの魚種嗜好は参考水準。"
    elif n_mid < 20:
        confidence = "Low"
        conf_reason = f"mid(20-50mm) イベントが {n_mid} 件と少なく、統計的推論は限定的。"
    else:
        confidence = "Mid-Low"
        conf_reason = f"mid={n_mid}, hi={n_hi}, turbid_actual={n_turbid_ev} 件。"

    lines = [
        "# water_color_analysis v2 結果レポート",
        "",
        "## データ概要",
        f"- 分析期間: {date_from} 〜 {date_to}",
        f"- trip_records 総数: {n_trip:,} 件",
        f"- water_color 有効報告 trip 数: {n_wc_trip:,} 件",
        f"- daily_turbidity ペア数: {len(daily_turbidity):,}",
        "",
        "## Sanity Check (turbid_rate 分布)",
        f"  turbid_rate P50 = {tr_p50}  P75 = {tr_p75}",
        f"  (0 = 濁り報告なし, 1 = 全便が濁り報告)",
        "  ゾーン別 baseline (P25):",
    ]
    for z, v in sorted(zone_baseline.items()):
        lines.append(f"    {z}: {v:.3f}")

    lines += [
        "",
        "## 雨イベント数 (rain 系)",
        f"  no (<5mm):    {bcnt.get('no', 0):,}",
        f"  lo (5-20mm):  {bcnt.get('lo', 0):,}",
        f"  mid (20-50mm):{bcnt.get('mid', 0):,}",
        f"  hi (50mm+):   {bcnt.get('hi', 0):,}",
        "",
        "## 濁りイベント数 (turbid_actual 系)",
        f"  turbid_actual: {n_turbid_ev:,} イベント",
        "  ゾーン別:",
    ]
    zone_turbid_cnt = defaultdict(int)
    for e in turbid_events:
        zone_turbid_cnt[e["zone"]] += 1
    for z in sorted(zone_turbid_cnt.keys()):
        lines.append(f"    {z}: {zone_turbid_cnt[z]}")

    lines += [
        "",
        "## 改善4: 連続雨除外件数",
        f"  除外総数: {total_excl} 件 / 除外率: {excl_rate*100:.1f}%",
    ]
    if excl_rate > 0.20:
        lines.append("  ⚠ 除外率 20% 超 → 梅雨・台風シーズンの seasonal bias に注意")
    lines.append("  月別内訳 (上位 10):")
    for m, cnt in sorted(excl_by_month.items(), key=lambda x: -x[1])[:10]:
        lines.append(f"    {m}: {cnt} 件")

    # 回復統計
    lines += [
        "",
        "## 雨後の濁りダイナミクス (recovery_by_bucket.csv より)",
        "(改善5: n<10 の offset は N/A 扱い)",
        "(recovery_offset_both が主指標: p50 AND p75 両側が baseline+0.2 を下回った最初の日)",
        "(recovery_offset_p50 は参考値: p50 のみ基準)",
        "両側基準は p50 だけでなく上位25%（p75）も収束したことを要求するため、",
        "「半数以上がまだ濁り継続」な状態を回復扱いにしない、より実態に近い回復日数を示す。",
        "",
    ]
    for r in recovery_rows:
        if r["n_events"] == 0:
            continue
        lines.append(
            f"  [{r['event_type']}] zone={r['zone']} bucket={r['bucket']}: "
            f"n_events={r['n_events']}, peak=D+{r['peak_day']}, "
            f"peak_rate={r['peak_turbid_rate']}, "
            f"recovery_both(主)={r['recovery_offset_both']}, "
            f"recovery_p50(参考)={r['recovery_offset_p50']}"
        )

    lines += [
        "",
        "## 魚種別濁り嗜好 (月内比較ベース)",
        f"採用条件: n_months >= {MIN_N_MONTHS_FISH}, "
        f"n_turbid_days >= {MIN_TURBID_DAYS_PER_MONTH}, "
        f"n_clear_days >= {MIN_CLEAR_DAYS_PER_MONTH}",
        "",
        "### 濁りで釣果が増える魚 (ratio_p50 >= 1.1)",
    ]
    if plus_fish:
        for r in plus_fish:
            lines.append(
                f"  + {r['tsuri_mono']}: ratio={r['turbid_clear_ratio_p50']:.3f} "
                f"(n_months={r['n_months']}, n_turbid_trips={r['n_turbid_trips']})"
            )
    else:
        lines.append("  (条件を満たす魚種なし)")

    lines += ["", "### 濁りで釣果が減る魚 (ratio_p50 <= 0.9)"]
    if minus_fish:
        for r in minus_fish:
            lines.append(
                f"  - {r['tsuri_mono']}: ratio={r['turbid_clear_ratio_p50']:.3f} "
                f"(n_months={r['n_months']}, n_turbid_trips={r['n_turbid_trips']})"
            )
    else:
        lines.append("  (条件を満たす魚種なし)")

    lines += ["", "### 平気な魚 (0.9 <= ratio_p50 < 1.1)"]
    if flat_fish:
        for r in flat_fish[:5]:
            lines.append(
                f"  = {r['tsuri_mono']}: ratio={r['turbid_clear_ratio_p50']:.3f} "
                f"(n_months={r['n_months']})"
            )
    else:
        lines.append("  (条件を満たす魚種なし)")

    lines += [
        "",
        "## 注意事項",
        "",
        "### M-4: 平年 leakage（月内比較は leakage を大幅軽減）",
        "月内比較では同月内の turbid 日と clear 日を比較するため、",
        "旬別平年ベースラインの leakage 問題は大幅に軽減されている。",
        "ただし同月内の季節変化（前半/後半）や天候系統の偏りは残存する。",
        "",
        "### 小サンプル警告",
        f"- hi (50mm+) バケット: n={n_hi} イベントで统計的推論は不可能",
        f"- n_months < {MIN_N_MONTHS_FISH} の魚種は fish_turbidity_summary から除外済み",
        f"- recovery_offset_both (主指標) / recovery_offset_p50 (参考値): n<{MIN_N_RECOVERY} の cell は N/A",
        "",
        "## X 投稿用引用文案",
        "",
    ]

    # 文案用の recovery 代表値:
    #   rain 系 mid は n 不足のためスキップ。
    #   turbid_actual 系の sagami_bay / tokyo_bay (n が多い) を使用。
    repr_turbid_sagami = None
    repr_turbid_tokyo  = None
    for r in recovery_rows:
        if r["event_type"] == "turbid_actual" and r["n_events"] >= 50:
            if r["zone"] == "sagami_bay" and repr_turbid_sagami is None:
                repr_turbid_sagami = r
            if r["zone"] == "tokyo_bay" and repr_turbid_tokyo is None:
                repr_turbid_tokyo  = r
    repr_turbid = repr_turbid_tokyo or repr_turbid_sagami

    # rain 系 mid の代表（n>=10 を満たすもの・参考用）
    repr_mid = None
    for r in recovery_rows:
        if (r["event_type"] == "rain" and r["bucket"] == "mid"
                and r["n_events"] >= 10):
            repr_mid = r
            break

    lines += ["【案1: ゲリラ豪雨後の濁り（turbid_actual 基準）】"]
    if repr_turbid and repr_turbid["peak_day"] != "N/A":
        both = repr_turbid["recovery_offset_both"]
        p50  = repr_turbid["recovery_offset_p50"]
        lines.append(
            f"関東船釣り、実際に濁りが発生したあと"
            f"（{repr_turbid['zone']} / n={repr_turbid['n_events']}イベント）"
            f"は翌日以降も継続。全便の濁り収束まで約{both}日（p50単独では{p50}日）。"
            f"3年分・船宿水色報告{n_wc_trip:,}件から。#船釣り #ゲリラ豪雨 #関東"
        )
    else:
        lines.append("  (代表ゾーンの recovery 計算不能)")

    lines += ["", "【案2: 濁りが得意な魚】"]
    if plus_fish:
        names = "・".join(r["tsuri_mono"] for r in plus_fish[:3])
        pct   = ", ".join(
            f"{r['tsuri_mono']} {int((r['turbid_clear_ratio_p50']-1)*100):+d}%"
            for r in plus_fish[:3]
        )
        lines.append(
            f"濁り潮でも釣れる魚は？3年間の船宿水色報告で分析。"
            f"濁り時の月内比較: {pct}。"
            f"大雨の翌日こそチャンスかも。#船釣り #濁り潮 #関東"
        )
    else:
        lines.append("  (有意な + 魚種なし → 信頼できる文案生成不可)")

    lines += ["", "【案3: 濁りが苦手な魚】"]
    if minus_fish:
        names = "・".join(r["tsuri_mono"] for r in minus_fish[:3])
        pct   = ", ".join(
            f"{r['tsuri_mono']} {int((r['turbid_clear_ratio_p50']-1)*100):+d}%"
            for r in minus_fish[:3]
        )
        lines.append(
            f"ゲリラ豪雨後は要注意の魚も。濁り時の月内比較で釣果が落ちやすい: {pct}。"
            f"水色が戻るまで待つのが正解かも。#船釣り #関東釣果 #濁り潮"
        )
    else:
        lines.append("  (有意な - 魚種なし → 信頼できる文案生成不可)")

    lines += [
        "",
        "## 信頼度自己評価",
        f"**{confidence}**",
        conf_reason,
        "",
        "### データの限界",
        "- water_color は船宿が自主的に報告する定性情報。報告率 30.6%（25,206 / 82,331 trip）",
        "- 報告バイアス: 濁りが目立つときに記載される可能性（過剰評価方向）",
        "- turbid_actual イベントは小さな連続イベントが除外されるため、長期濁り期間は過小評価",
        "- hi (50mm+) バケットは 11 件のみで統計的推論は不可能。X 投稿では使わないこと",
        "",
        "---",
        f"生成日時: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
    ]

    path = os.path.join(out_dir, "report.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"  [出力] {path}")

    return plus_fish, minus_fish, flat_fish, confidence, repr_mid, bcnt, n_wc_trip, tr_p50


# ---------------------------------------------------------------
# メイン
# ---------------------------------------------------------------
def main():
    print("=== water_color_analysis.py v2 開始 ===")
    print(f"DATA_DIR:   {DATA_DIR}")
    print(f"WEATHER_DB: {WEATHER_DB}")
    print(f"OUT_DIR:    {OUT_DIR}")

    # Step 2
    print("\n[Step 2] trip_records 読み込み...")
    trip_records = load_trip_records(DATA_DIR)

    # Step 3
    print("\n[Step 3] daily_turbidity (turbid_rate) 構築...")
    daily_turbidity = build_daily_turbidity(trip_records)

    # Step 4
    print("\n[Step 4] 24h 雨量マップ構築...")
    area_coords = load_area_coords()
    wx_coords   = load_wx_coords(WEATHER_DB)
    area_wx_map = build_area_wx_map(area_coords, wx_coords)
    target_areas = set(AREA_TO_ZONE.keys())
    area_date_rain = load_daily_rain_for_areas(WEATHER_DB, area_wx_map, target_areas)

    # Step 5
    print("\n[Step 5] ゾーン baseline 計算...")
    zone_baseline = build_zone_baseline(daily_turbidity)

    print("\n[Step 5] 時系列イベント構築 (event_type 2系統)...")
    timeline, rain_events, turbid_events, excluded_prior = (
        build_turbidity_timeline(daily_turbidity, area_date_rain, zone_baseline)
    )

    # Step 6
    print("\n[Step 6] 回復統計...")
    recovery_rows = build_recovery_stats(
        timeline, rain_events, turbid_events, zone_baseline
    )

    # Step 7
    print("\n[Step 7] 魚種別濁り嗜好 (月内比較)...")
    pref_rows, summary_rows = build_fish_turbidity_preference(trip_records)

    # CSV 出力
    print("\n[出力] CSV 書き出し...")
    save_daily_turbidity_csv(daily_turbidity, OUT_DIR)
    save_timeline_csv(timeline, OUT_DIR)
    save_recovery_csv(recovery_rows, OUT_DIR)
    save_fish_pref_csv(pref_rows, summary_rows, OUT_DIR)

    # report
    print("\n[出力] report.md 生成...")
    plus_fish, minus_fish, flat_fish, confidence, repr_mid, bcnt, n_wc_trip, tr_p50 = (
        generate_report(trip_records, daily_turbidity, rain_events, turbid_events,
                        excluded_prior, recovery_rows, summary_rows, zone_baseline, OUT_DIR)
    )

    # 標準出力サマリー
    all_dates = sorted(set(t["date"] for t in trip_records))
    date_from = all_dates[0]  if all_dates else "?"
    date_to   = all_dates[-1] if all_dates else "?"

    print("\n=== X投稿用の主要数値 ===")
    print(f"データ期間: {date_from} 〜 {date_to}")
    print(f"water_color 報告 trip 数: {n_wc_trip:,}")
    print(f"雨イベント mid (20-50mm): {bcnt.get('mid', 0)}, hi (50mm+): {bcnt.get('hi', 0)}")
    print(f"turbid_actual イベント: {len(turbid_events)}")
    print(f"turbid_rate 全体 P50: {tr_p50}")

    if repr_mid:
        print(f"mid バケット代表ゾーン: {repr_mid['zone']}")
        print(f"  peak D+{repr_mid['peak_day']} rate={repr_mid['peak_turbid_rate']}")
        print(f"  recovery_both(主)={repr_mid['recovery_offset_both']}, "
              f"recovery_p50(参考)={repr_mid['recovery_offset_p50']}")

    plus_str  = ", ".join(
        f"{r['tsuri_mono']}(ratio={r['turbid_clear_ratio_p50']:.2f},n={r['n_months']}mo)"
        for r in plus_fish
    ) if plus_fish else "該当なし"
    minus_str = ", ".join(
        f"{r['tsuri_mono']}(ratio={r['turbid_clear_ratio_p50']:.2f},n={r['n_months']}mo)"
        for r in minus_fish
    ) if minus_fish else "該当なし"
    flat_str  = ", ".join(
        f"{r['tsuri_mono']}(ratio={r['turbid_clear_ratio_p50']:.2f},n={r['n_months']}mo)"
        for r in flat_fish[:3]
    ) if flat_fish else "該当なし"

    print(f"+ になる魚 TOP3: [{plus_str}]")
    print(f"- になる魚 TOP3: [{minus_str}]")
    print(f"平気な魚 TOP3:   [{flat_str}]")
    print(f"信頼度: {confidence}")
    print("\n=== 完了 ===")


if __name__ == "__main__":
    main()
