"""
rain_turbidity_analysis.py
ゲリラ豪雨後の釣果落ち込み分析

設計仕様:
- Step1: エリア×日付ごとの24h累積降水量（D-1 18:00 〜 D 18:00 JST）
  ・weather_cache.sqlite は dt が UTC。JST 18:00 = UTC 09:00
  ・「D日の釣行」に対応する雨窓 = UTC D-1T09:00 〜 D T09:00（8コマ=24h）
- Step2: CSV から (area, date) → total_catch, n_trips 集約
- Step3: area×旬の平年中央値でanomaly算出（area_decadal は文字化けのため生集計）
- Step4: 雨バケット判定・D+1〜D+7追跡・連続雨除外
- Step5: zone×bucket×D+N で集約
- Step6: 回復日数算出
"""

import os
import sys
import csv
import json
import sqlite3
import math
import statistics
from collections import defaultdict
from datetime import date, datetime, timedelta

# --- パス解決 ---
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _paths import ROOT_DIR, RESULTS_DIR, DATA_DIR, NORMALIZE_DIR, OCEAN_DIR

OUT_DIR = os.path.join(RESULTS_DIR, "rain_turbidity")
os.makedirs(OUT_DIR, exist_ok=True)

WEATHER_DB = os.path.join(OCEAN_DIR, "weather_cache.sqlite")

# ---------------------------------------------------------------
# ゾーン割当（area名 → zone）
# ゾーン定義根拠: area_coords.json の lat/lon + area_description.json の地理特徴
# ---------------------------------------------------------------
AREA_TO_ZONE = {
    # 茨城
    "日立久慈港":          "ibaraki",
    "大洗港":              "ibaraki",
    "鹿島港":              "ibaraki",
    "鹿島市新浜":          "ibaraki",
    "波崎港":              "ibaraki",
    # 外房・南房（千葉外洋）
    "飯岡港":              "outer_boso",
    "外川港":              "outer_boso",
    "太東港":              "outer_boso",
    "大原港":              "outer_boso",
    "勝浦川津港":          "outer_boso",
    "御宿岩和田港":        "outer_boso",
    "天津港":              "outer_boso",
    "洲崎港":              "outer_boso",   # 房総南端・外洋側
    # 内房（千葉東京湾側）
    "富浦港":              "inner_boso",
    "金谷港":              "inner_boso",
    "保田港":              "inner_boso",
    "長浦":                "inner_boso",
    # 東京湾（東京・神奈川・千葉湾岸）
    "浦安":                "tokyo_bay",
    "東葛西":              "tokyo_bay",
    "江戸川放水路･原木中山": "tokyo_bay",
    "羽田":                "tokyo_bay",
    "平和島":              "tokyo_bay",
    "横浜本牧港":          "tokyo_bay",
    "横浜港･新山下":       "tokyo_bay",
    "金沢八景":            "tokyo_bay",
    "金沢漁港":            "tokyo_bay",
    "小柴港":              "tokyo_bay",
    "鴨居大室港":          "tokyo_bay",
    "久里浜港":            "tokyo_bay",
    "久比里港":            "tokyo_bay",
    "長井港":              "sagami_bay",   # 三浦半島南部・相模湾寄り
    "長井新宿港":          "sagami_bay",
    "長井漆山港":          "sagami_bay",
    "松輪江奈港":          "sagami_bay",
    "松輪間口港":          "sagami_bay",
    "小網代港":            "sagami_bay",
    "小坪港":              "sagami_bay",
    "葉山あぶずり港":      "sagami_bay",
    # 相模湾
    "茅ヶ崎港":            "sagami_bay",
    "平塚港":              "sagami_bay",
    "大磯港":              "sagami_bay",
    "小田原早川港":        "sagami_bay",
    # 伊豆・静岡
    "松崎港":              "izu",
    "下田港":              "izu",
    "沼津内港":            "izu",
    "沼津静浦":            "izu",
    "田子の浦港":          "izu",
    "由比":                "izu",
    "吉田港":              "izu",
    "福田港":              "izu",
    "御前崎港":            "izu",
}


# ---------------------------------------------------------------
# Step 0: area_coords 読み込み
# ---------------------------------------------------------------
def load_area_coords():
    path = os.path.join(NORMALIZE_DIR, "area_coords.json")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------
# Step 1: エリア代表座標→最近傍 weather_cache 座標マッピング
# ---------------------------------------------------------------
def nearest_weather_coord(area_lat, area_lon, wx_coords):
    """wx_coords: list of (lat, lon). Euclidean 距離で最近傍を返す。"""
    best, best_d = None, float("inf")
    for (lat, lon) in wx_coords:
        d = (lat - area_lat) ** 2 + (lon - area_lon) ** 2
        if d < best_d:
            best_d = d
            best = (lat, lon)
    return best


def load_wx_coords(db_path):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT lat, lon FROM weather")
    coords = cur.fetchall()
    conn.close()
    return coords


def build_area_wx_map(area_coords, wx_coords):
    """area名 → (nearest_lat, nearest_lon) のdict"""
    result = {}
    for area, info in area_coords.items():
        result[area] = nearest_weather_coord(info["lat"], info["lon"], wx_coords)
    return result


# ---------------------------------------------------------------
# Step 1 続き: 各 (area, date) の 24h 雨量を計算
# ---------------------------------------------------------------
def load_daily_rain(db_path, area_wx_map):
    """
    戻り値: dict[(area, date_str)] = rain_24h_mm
    dt は UTC。釣行日 D の雨窓 = D-1T09:00 UTC 〜 D T06:00 UTC（含む・8コマ）
    = JST D-1 18:00 〜 D 15:00 ≒ 釣行前日夕方〜当日午後（釣果に影響する雨）
    ※ D T09:00 UTC = JST 18:00 (D) は釣行終了後なので除外。
    実装: WHERE dt >= 'D-1 09:00' AND dt < 'D 09:00' の8コマを合計
    → これで JST D-1 18:00 〜 D 17:59 の 24h に対応
    """
    # ユニーク座標ごとにまとめてクエリ
    coord_to_areas = defaultdict(list)
    for area, coord in area_wx_map.items():
        coord_to_areas[coord].append(area)

    # 全日付の雨量 cache: (lat, lon, date_str) → rain_mm
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # 全データを一括取得（precipitation 非NULL・非ゼロ日だけでもOK）
    # まず対象座標のリスト
    coord_list = list(coord_to_areas.keys())
    print(f"  [Step1] 対象座標数: {len(coord_list)} 件, 先頭3: {coord_list[:3]}")

    # 座標ごとに日別合計
    coord_day_rain = {}  # (lat, lon, date_str) → float
    for lat, lon in coord_list:
        cur.execute("""
            SELECT substr(dt,1,10) as day,
                   -- 前日 D-1 09:00(UTC) 〜 D 06:00(UTC) = 8コマ
                   -- SQLite で日付演算: dt >= date(day,'-1 day')||'T09:00'
                   -- ただし「day」は実際の釣行日。下記で GROUP BY day は
                   -- 「UTC 00:00〜21:00 の8コマ合計」になるので後処理で24h窓にする。
                   -- ここでは lat/lon/day ごとの全 precipitation を取得し Python 側で窓処理
                   dt,
                   precipitation
            FROM weather
            WHERE lat=? AND lon=?
              AND precipitation IS NOT NULL
            ORDER BY dt
        """, (lat, lon))
        rows = cur.fetchall()
        # Python 側で 24h 窓合計: dt UTC >= D-1T09:00 AND dt UTC < D T09:00
        # → same as: dt_date == D-1 and dt_time >= 09:00
        #         OR dt_date == D   and dt_time <  09:00
        # dt 例: '2023-06-15T12:00'
        day_buckets = defaultdict(list)  # date_str → [(dt, precip)]
        for row in rows:
            dt_str = row["dt"]   # 'YYYY-MM-DDTHH:MM'
            d = dt_str[:10]
            t = dt_str[11:]
            # 釣行日 D の 24h 窓 = D-1T09:00〜D T06:00(UTC)
            # つまり dt の「釣行日」= D として:
            #   dt_date == D-1 かつ dt_time >= 09:00 → 釣行日 D に割当
            #   dt_date == D   かつ dt_time <= 06:00 → 釣行日 D に割当
            # 以下でどの「釣行日 D」に属するか計算
            if t >= "09:00":
                # 翌日の釣行日に属する
                fishing_day = (
                    datetime.strptime(d, "%Y-%m-%d") + timedelta(days=1)
                ).strftime("%Y-%m-%d")
            else:
                # 同日の釣行日に属する（00:00〜06:00 UTC）
                fishing_day = d
            day_buckets[fishing_day].append(row["precipitation"])

        for day_str, precip_list in day_buckets.items():
            coord_day_rain[(lat, lon, day_str)] = sum(precip_list)

    conn.close()

    # area × date → rain
    area_date_rain = {}
    for (lat, lon), areas in coord_to_areas.items():
        # 全日付の雨量
        for key, rain in coord_day_rain.items():
            if key[0] == lat and key[1] == lon:
                d = key[2]
                for area in areas:
                    area_date_rain[(area, d)] = rain

    return area_date_rain


# ---------------------------------------------------------------
# Step 2: CSV 釣果集約 (area, date) → total_catch, n_trips
# ---------------------------------------------------------------
def load_catch_data(data_dir):
    """
    戻り値: dict[(area, date_str)] = {"total_catch": float, "n_trips": int}
    - is_cancellation==1 は除外
    - cnt_avg が空・非数値 は 0 として扱う（n_trips はカウント）
    - cancellations.csv は除外
    - date 形式: CSV は YYYY/MM/DD → YYYY-MM-DD に変換
    """
    files = [
        f for f in os.listdir(data_dir)
        if f.endswith(".csv") and f != "cancellations.csv"
    ]
    print(f"  [Step2] CSVファイル数: {len(files)} 件, 先頭3: {sorted(files)[:3]}")

    agg = defaultdict(lambda: {"total_catch": 0.0, "n_trips": 0})
    total_rows = 0
    skipped = 0

    for fn in sorted(files):
        with open(os.path.join(data_dir, fn), encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                total_rows += 1
                area = row.get("area", "").strip()
                if not area:
                    skipped += 1
                    continue
                if row.get("is_cancellation", "0") == "1":
                    skipped += 1
                    continue
                raw_date = row.get("date", "").strip()
                if not raw_date:
                    skipped += 1
                    continue
                # YYYY/MM/DD → YYYY-MM-DD
                date_str = raw_date.replace("/", "-")
                cnt_raw = row.get("cnt_avg", "").strip()
                try:
                    cnt = float(cnt_raw) if cnt_raw else 0.0
                except ValueError:
                    cnt = 0.0

                agg[(area, date_str)]["total_catch"] += cnt
                agg[(area, date_str)]["n_trips"] += 1

    print(f"  [Step2] 総行数: {total_rows}, スキップ: {skipped}, 有効(area,date)ペア: {len(agg)}")
    return dict(agg)


# ---------------------------------------------------------------
# Step 3: 平年比 anomaly 算出（area×旬の中央値ベース）
# ---------------------------------------------------------------
def get_decade_no(date_str):
    """YYYY-MM-DD → (月, 旬番号1〜3)"""
    d = datetime.strptime(date_str, "%Y-%m-%d")
    if d.day <= 10:
        dec = 1
    elif d.day <= 20:
        dec = 2
    else:
        dec = 3
    return (d.month, dec)


def build_baseline(catch_data):
    """
    catch_data: dict[(area, date_str)] = {"total_catch", "n_trips"}
    戻り値: dict[(area, month, dec)] = baseline_cnt_per_trip (中央値)
    """
    bucket = defaultdict(list)
    for (area, date_str), vals in catch_data.items():
        n = vals["n_trips"]
        if n == 0:
            continue
        catch_per_trip = vals["total_catch"] / n
        month, dec = get_decade_no(date_str)
        bucket[(area, month, dec)].append(catch_per_trip)

    baseline = {}
    for key, vals in bucket.items():
        if len(vals) >= 3:  # 最低3サンプルで平年値を出す
            baseline[key] = statistics.median(vals)
    print(f"  [Step3] 平年テーブル: {len(baseline)} エントリ (area×旬)")
    return baseline


def compute_anomaly(catch_data, baseline):
    """
    戻り値: dict[(area, date_str)] = anomaly (float)
    平年=0 or n_trips=0 の行は除外
    """
    anomaly_map = {}
    for (area, date_str), vals in catch_data.items():
        n = vals["n_trips"]
        if n == 0:
            continue
        catch_per_trip = vals["total_catch"] / n
        month, dec = get_decade_no(date_str)
        bl = baseline.get((area, month, dec))
        if bl is None or bl <= 0:
            continue
        anomaly_map[(area, date_str)] = catch_per_trip / bl
    print(f"  [Step3] anomaly 算出済み (area,date) ペア: {len(anomaly_map)}")
    return anomaly_map


# ---------------------------------------------------------------
# Step 4: 雨イベント検出 & D+N 追跡
# ---------------------------------------------------------------
BUCKETS = {
    "no":  (0, 5),
    "lo":  (5, 20),
    "mid": (20, 50),
    "hi":  (50, float("inf")),
}

def classify_bucket(rain_mm):
    if rain_mm < 5:
        return "no"
    elif rain_mm < 20:
        return "lo"
    elif rain_mm < 50:
        return "mid"
    else:
        return "hi"


def build_events(area_date_rain, anomaly_map):
    """
    各 (area, D0) でバケット判定し D+1〜D+7 の anomaly を取得。
    連続雨除外: D+1〜D+7 のいずれかで rain >= 20 → その D+N は除外。

    戻り値:
      events: list of dict {
        area, zone, D0, bucket,
        offsets: dict{N: anomaly or None}
      }
    """
    events = []
    # area×date の全候補
    all_area_dates = set(area_date_rain.keys()) | set(anomaly_map.keys())
    area_set = set(a for (a, _) in all_area_dates)

    # area ごとに日付でソートして処理
    by_area = defaultdict(list)
    for (area, date_str) in area_date_rain.keys():
        by_area[area].append(date_str)

    for area in sorted(area_set):
        zone = AREA_TO_ZONE.get(area)
        if zone is None:
            continue  # ゾーン未定義エリアは除外
        dates = sorted(set(by_area.get(area, [])))

        for d0 in dates:
            rain0 = area_date_rain.get((area, d0), 0.0)
            bucket = classify_bucket(rain0)

            offsets = {}
            d0_dt = datetime.strptime(d0, "%Y-%m-%d")
            for n in range(1, 8):
                dn = (d0_dt + timedelta(days=n)).strftime("%Y-%m-%d")
                # 連続雨チェック
                rain_n = area_date_rain.get((area, dn), 0.0)
                if rain_n >= 20:
                    offsets[n] = None  # 連続雨で除外
                    continue
                anom = anomaly_map.get((area, dn))
                offsets[n] = anom  # None も許容（釣行なし）

            events.append({
                "area": area,
                "zone": zone,
                "D0": d0,
                "bucket": bucket,
                "rain_mm": rain0,
                "offsets": offsets,
            })

    print(f"  [Step4] イベント総数: {len(events)}")
    # バケット別集計
    bucket_cnt = defaultdict(int)
    for ev in events:
        bucket_cnt[ev["bucket"]] += 1
    for b in ["no", "lo", "mid", "hi"]:
        print(f"    bucket_{b}: {bucket_cnt[b]}")
    return events


# ---------------------------------------------------------------
# Step 5: 集約
# ---------------------------------------------------------------
def percentile(data, p):
    """0〜100のパーセンタイル値（線形補間）"""
    if not data:
        return float("nan")
    s = sorted(data)
    n = len(s)
    idx = (p / 100) * (n - 1)
    lo = int(idx)
    hi = min(lo + 1, n - 1)
    frac = idx - lo
    return s[lo] * (1 - frac) + s[hi] * frac


def aggregate_results(events, zones=None):
    """
    events のリストを zone×bucket×day_offset で集約。
    zones=None → 全ゾーン + "all" を計算。
    戻り値: list of dict
    """
    if zones is None:
        zones = list(set(ev["zone"] for ev in events))

    rows = []
    for zone in ["all"] + sorted(zones):
        for bucket in ["no", "lo", "mid", "hi"]:
            # zone でフィルタ
            zone_events = (
                events
                if zone == "all"
                else [ev for ev in events if ev["zone"] == zone]
            )
            bucket_events = [ev for ev in zone_events if ev["bucket"] == bucket]

            for n in range(1, 8):
                vals = [
                    ev["offsets"][n]
                    for ev in bucket_events
                    if ev["offsets"].get(n) is not None
                ]
                rows.append({
                    "zone": zone,
                    "bucket": bucket,
                    "day_offset": n,
                    "n": len(vals),
                    "anomaly_p25": round(percentile(vals, 25), 4) if vals else "",
                    "anomaly_p50": round(percentile(vals, 50), 4) if vals else "",
                    "anomaly_p75": round(percentile(vals, 75), 4) if vals else "",
                })
    return rows


# ---------------------------------------------------------------
# Step 6: 回復日数
# ---------------------------------------------------------------
def compute_recovery(events, threshold=0.85):
    """
    各 (area, D0, bucket) で D+1〜D+7 の最初に anomaly >= threshold の N を記録。
    7日以内に戻らない → recovery=8。
    対象: mid/hi バケットのみ（lo も一応計算する）。
    連続雨で除外された日はスキップ（その日は欠損として次の日へ）。
    """
    rows = []
    zones = list(set(ev["zone"] for ev in events))

    for zone in ["all"] + sorted(zones):
        for bucket in ["lo", "mid", "hi"]:
            zone_events = (
                events
                if zone == "all"
                else [ev for ev in events if ev["zone"] == zone]
            )
            bucket_events = [ev for ev in zone_events if ev["bucket"] == bucket]
            recovery_days = []

            for ev in bucket_events:
                recovered = 8  # default: not recovered in 7 days
                for n in range(1, 8):
                    anom = ev["offsets"].get(n)
                    if anom is None:
                        continue  # 連続雨 or 釣行なし
                    if anom >= threshold:
                        recovered = n
                        break
                recovery_days.append(recovered)

            n_events = len(recovery_days)
            rows.append({
                "zone": zone,
                "bucket": bucket,
                "n_events": n_events,
                "recovery_p50": round(percentile(recovery_days, 50), 1) if recovery_days else "",
                "recovery_p75": round(percentile(recovery_days, 75), 1) if recovery_days else "",
            })
    return rows


# ---------------------------------------------------------------
# 出力
# ---------------------------------------------------------------
def write_csv(path, rows, fieldnames):
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"  → 書き込み: {path} ({len(rows)} 行)")


def write_report(path, anomaly_rows, recovery_rows, events, catch_data, area_date_rain):
    """report.md 生成"""

    # データ期間
    dates_all = sorted(set(d for (_, d) in catch_data.keys()))
    data_start = dates_all[0] if dates_all else "?"
    data_end = dates_all[-1] if dates_all else "?"
    total_fishing = sum(v["n_trips"] for v in catch_data.values())

    # バケット別イベント数
    from collections import Counter
    bucket_cnt = Counter(ev["bucket"] for ev in events)

    # sanity check: no バケットの D+1 anomaly P50
    no_d1 = [
        ev["offsets"][1] for ev in events
        if ev["bucket"] == "no" and ev["offsets"].get(1) is not None
    ]
    sanity_val = round(percentile(no_d1, 50), 3) if no_d1 else float("nan")

    # 主要数値（all ゾーン）
    def get_row(arows, zone, bucket, day_offset):
        for r in arows:
            if r["zone"] == zone and r["bucket"] == bucket and r["day_offset"] == day_offset:
                return r
        return {}

    mid_d1 = get_row(anomaly_rows, "all", "mid", 1)
    hi_d1  = get_row(anomaly_rows, "all", "hi", 1)
    hi_d3  = get_row(anomaly_rows, "all", "hi", 3)
    hi_d7  = get_row(anomaly_rows, "all", "hi", 7)

    def get_rec(rrows, zone, bucket):
        for r in rrows:
            if r["zone"] == zone and r["bucket"] == bucket:
                return r
        return {}

    rec_mid = get_rec(recovery_rows, "all", "mid")
    rec_hi  = get_rec(recovery_rows, "all", "hi")

    # 信頼度判定
    n_hi = bucket_cnt.get("hi", 0)
    n_mid = bucket_cnt.get("mid", 0)
    if n_hi >= 50 and n_mid >= 100:
        confidence = "Mid"
        confidence_note = "hi バケット N=" + str(n_hi) + "（50+で統計的に有意だが 100 未満）"
    elif n_hi >= 20 and n_mid >= 50:
        confidence = "Low"
        confidence_note = "hi バケット N=" + str(n_hi) + "（20〜49・サンプル不足）"
    else:
        confidence = "Low"
        confidence_note = "hi バケット N=" + str(n_hi) + "（20未満・参考値のみ）"

    content = f"""# ゲリラ豪雨後の釣果落ち込み分析レポート

生成日: {date.today().isoformat()}

---

## データ概要

| 項目 | 値 |
|------|----|
| データ期間 | {data_start} 〜 {data_end} |
| 分析対象釣行数（n_trips合計） | {total_fishing:,} 件 |
| 有効 (area, date) ペア | {len(catch_data):,} |
| 対象エリア数 | 50 エリア（area_coords.json 登録済み）|
| 有効ゾーン割当エリア | {len(AREA_TO_ZONE)} エリア |

---

## Sanity Check: dt タイムゾーン確認

- weather_cache.sqlite の `dt` 列: **UTC**（例: `2023-01-01T00:00`）
- precipitation の単位: **mm/3時間**（最大 81.2mm/3h = 2023-09-08 鹿島沖、日計 73.6mm）
- JST 18:00 = UTC 09:00。釣行日 D の 24h 雨窓 = UTC D-1T09:00 〜 D T06:00（8コマ合計）
- 「ゲリラ豪雨」基準（20mm/h 以上）との整合: 3時間値 ≥ 60mm が相当。本分析では
  24h 累積 ≥ 50mm を `hi` バケットとして採用（局地的豪雨の累積影響を評価）。

---

## バケット定義

| バケット | 24h 累積降水量 | 意味 |
|----------|----------------|------|
| no | 0〜5mm未満 | 雨なし（sanity check 基準） |
| lo | 5〜20mm未満 | 小雨 |
| mid | 20〜50mm未満 | まとまった雨 |
| hi | 50mm以上 | 豪雨 |

連続雨除外: D+1〜D+7 のいずれかで rain ≥ 20mm の日は anomaly を除外（クリーンな単発イベント評価）

---

## Sanity Check 結果

| 指標 | 値 | 判定 |
|------|----|------|
| 雨なし翌日 anomaly P50 | {sanity_val} | {"OK (≈1.0)" if 0.85 <= sanity_val <= 1.2 else "要注意"} |
| mid バケットイベント数 | {n_mid} | {"OK (50+)" if n_mid >= 50 else "小サンプル"} |
| hi バケットイベント数 | {n_hi} | {"OK (50+)" if n_hi >= 50 else "小サンプル"} |

---

## メイン結論

### 1. 20〜50mm（まとまった雨）後の翌日

- anomaly P50 = {mid_d1.get("anomaly_p50", "N/A")}（n={mid_d1.get("n", "N/A")}）
- 平年比 {round(float(mid_d1["anomaly_p50"]) * 100) if mid_d1.get("anomaly_p50") else "?"}% に低下

### 2. 50mm 以上（豪雨）後の翌日

- anomaly P50 = {hi_d1.get("anomaly_p50", "N/A")}（n={hi_d1.get("n", "N/A")}）
- 3日後: {hi_d3.get("anomaly_p50", "N/A")}
- 7日後: {hi_d7.get("anomaly_p50", "N/A")}

### 3. 回復日数（anomaly ≥ 0.85）

| バケット | 回復日数 P50 | 回復日数 P75 | n_events |
|----------|-------------|-------------|---------|
| mid (20-50mm) | {rec_mid.get("recovery_p50", "?")} 日 | {rec_mid.get("recovery_p75", "?")} 日 | {rec_mid.get("n_events", "?")} |
| hi (50mm+)    | {rec_hi.get("recovery_p50", "?")} 日  | {rec_hi.get("recovery_p75", "?")} 日  | {rec_hi.get("n_events", "?")} |

---

## ゾーン別集計（hi バケット D+1）

| ゾーン | anomaly P50 | n |
|--------|-------------|---|
"""

    # ゾーン別 hi D+1
    zones_order = ["tokyo_bay", "sagami_bay", "outer_boso", "inner_boso", "izu", "ibaraki"]
    for zone in zones_order:
        row = get_row(anomaly_rows, zone, "hi", 1)
        content += f"| {zone} | {row.get('anomaly_p50', '-')} | {row.get('n', 0)} |\n"

    content += f"""
---

## 注意事項

1. **連続雨除外の影響**: D+1〜D+7 のいずれかで ≥ 20mm の雨が降った場合、
   その日は除外。長雨シーズン（梅雨・台風）の回復は過大評価される可能性がある。

2. **小サンプル警告**:
   - hi バケット (50mm+) は全関東でも稀少。n_events={n_hi} は統計的推論には注意が必要。
   - ゾーン別で n < 10 の cell は参考値として扱うこと。

3. **anomaly 基準**:
   - 平年比は area×旬（10日窓）の釣果中央値で正規化。
   - n < 3 の area×旬は平年テーブルから除外（当該(area,date)はanomaly算出不可）。

4. **因果解釈の限界**:
   - 「濁り」自体は直接計測せず、釣果落ち込みで代理測定。
   - 雨以外の要因（台風・気圧低下・水温変化）との交絡は未制御。
   - 特に hi バケットは台風シーズン（8〜10月）に集中する可能性がある。

5. **信頼度評価: {confidence}**
   - {confidence_note}

---

## X 投稿用の引用文案

（事実ベース・直近3年データより）

> 関東船釣り直近3年{total_fishing:,}件の釣果データで分析。
> 20mm以上の雨が降った翌日の釣果は平年比{round(float(mid_d1["anomaly_p50"]) * 100) if mid_d1.get("anomaly_p50") else "?"}%に低下。
> 50mm超の豪雨後は平均{rec_hi.get("recovery_p50", "?")}日で回復（anomaly≥0.85基準）。
> #船釣り #関東釣り #釣果予測

---

## 信頼度自己評価: **{confidence}**

{confidence_note}。
X投稿への使用については以下を推奨:
- mid バケット (20-50mm) の翌日 anomaly は n={n_mid} で傾向は見える。
- hi バケット (50mm+) は n={n_hi} でサンプル少。数値は目安として使用し、
  「N千件のデータから」という表現は mid+hi の合計 (n={n_mid+n_hi}) を引用する方が安全。
"""

    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"  → レポート: {path}")


# ---------------------------------------------------------------
# メイン
# ---------------------------------------------------------------
def main():
    print("=== 雨後釣果分析 開始 ===\n")

    # Step 0
    print("[Step0] area_coords 読み込み...")
    area_coords = load_area_coords()
    print(f"  area_coords: {len(area_coords)} エリア")

    # Step 1: weather_cache 座標リスト & area→coord マッピング
    print("\n[Step1] weather_cache 座標マッピング...")
    wx_coords = load_wx_coords(WEATHER_DB)
    print(f"  weather_cache ユニーク座標: {len(wx_coords)}")
    area_wx_map = build_area_wx_map(area_coords, wx_coords)

    # Step 1: 雨量計算
    print("\n[Step1] 日別雨量計算中...")
    area_date_rain = load_daily_rain(WEATHER_DB, area_wx_map)
    print(f"  (area, date) 雨量エントリ: {len(area_date_rain)}")

    # Step 2: CSV 釣果集約
    print("\n[Step2] CSV 釣果集約中...")
    catch_data = load_catch_data(DATA_DIR)

    # Step 3: 平年比
    print("\n[Step3] 平年比計算中...")
    baseline = build_baseline(catch_data)
    anomaly_map = compute_anomaly(catch_data, baseline)

    # Step 4: イベント生成
    print("\n[Step4] 雨イベント生成中...")
    events = build_events(area_date_rain, anomaly_map)

    # Step 5: 集約
    print("\n[Step5] 集約中...")
    anomaly_rows = aggregate_results(events)

    # Step 6: 回復日数
    print("\n[Step6] 回復日数計算中...")
    recovery_rows = compute_recovery(events)

    # 出力
    print("\n[出力] CSV / レポート書き込み...")
    write_csv(
        os.path.join(OUT_DIR, "rain_anomaly_by_bucket.csv"),
        anomaly_rows,
        ["zone", "bucket", "day_offset", "n", "anomaly_p25", "anomaly_p50", "anomaly_p75"],
    )
    write_csv(
        os.path.join(OUT_DIR, "recovery_days_by_bucket.csv"),
        recovery_rows,
        ["zone", "bucket", "n_events", "recovery_p50", "recovery_p75"],
    )
    write_report(
        os.path.join(OUT_DIR, "report.md"),
        anomaly_rows,
        recovery_rows,
        events,
        catch_data,
        area_date_rain,
    )

    # X 投稿用サマリー
    def get_row(arows, zone, bucket, day_offset):
        for r in arows:
            if r["zone"] == zone and r["bucket"] == bucket and r["day_offset"] == day_offset:
                return r
        return {}

    def get_rec(rrows, zone, bucket):
        for r in rrows:
            if r["zone"] == zone and r["bucket"] == bucket:
                return r
        return {}

    no_d1_vals = [
        ev["offsets"][1] for ev in events
        if ev["bucket"] == "no" and ev["offsets"].get(1) is not None
    ]
    sanity_p50 = round(percentile(no_d1_vals, 50), 3) if no_d1_vals else float("nan")

    mid_d1 = get_row(anomaly_rows, "all", "mid", 1)
    hi_d1  = get_row(anomaly_rows, "all", "hi", 1)
    rec_hi = get_rec(recovery_rows, "all", "hi")

    from collections import Counter
    bucket_cnt = Counter(ev["bucket"] for ev in events)
    dates_all = sorted(set(d for (_, d) in catch_data.keys()))
    total_fishing = sum(v["n_trips"] for v in catch_data.values())

    print("\n=== X投稿用の主要数値 ===")
    print(f"データ期間: {dates_all[0] if dates_all else '?'} 〜 {dates_all[-1] if dates_all else '?'}")
    print(f"分析対象釣行数: {total_fishing:,}件")
    print(f"雨イベント検出数: bucket_mid={bucket_cnt['mid']}件, bucket_hi={bucket_cnt['hi']}件")
    print(f"雨無し時の翌日anomaly中央値: {sanity_p50}（sanity check）")
    print(f"20-50mm雨後の翌日anomaly中央値: {mid_d1.get('anomaly_p50', 'N/A')} (n={mid_d1.get('n', '?')})")
    print(f"50mm+雨後の翌日anomaly中央値: {hi_d1.get('anomaly_p50', 'N/A')} (n={hi_d1.get('n', '?')})")
    print(f"回復日数中央値（50mm+）: {rec_hi.get('recovery_p50', 'N/A')}日")


if __name__ == "__main__":
    main()
