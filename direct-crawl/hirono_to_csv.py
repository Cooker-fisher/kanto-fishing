"""
hirono_to_csv.py — catches_raw_hirono.json → data/V2/hirono_YYYY-MM.csv 月別生成

出力:
    data/V2/hirono_YYYY-MM.csv  ← 月別に分割

CSV列（既存V2 39列 + source = 40列）:
    既存V2スキーマと完全一致 + 末尾に source 列を追加。
    拡張海況（pressure/moon_age/bi/sunrise/sunset/temp_high/low/wave_height_m 等）は
    CSVに出さず、Raw JSON の weather_detail に保持（PIPELINE.md A2層と統合時に参照）。

NULL/空文字の使い分け:
    "NULL" : HTML/ソース側に項目自体が存在しない（chowari にも無い列）
    ""    : HTML項目は存在するが値が空（外道で数値未報告など）
"""

import csv
import json
import os
import re
import sys
from collections import defaultdict

sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IN_PATH  = os.path.join(ROOT, "direct-crawl", "catches_raw_hirono.json")
OUT_DIR  = os.path.join(ROOT, "data", "V2")
MAP_PATH = os.path.join(ROOT, "normalize", "tsuri_mono_map_draft.json")

NULL = "NULL"


def load_tsuri_map():
    with open(MAP_PATH, encoding="utf-8") as f:
        return json.load(f).get("TSURI_MONO_MAP", {})


def normalize_tsuri_mono(raw, tmap):
    if not raw:
        return ""
    if raw in tmap:
        return raw
    for canon, patterns in tmap.items():
        if raw in patterns:
            return canon
    for canon, patterns in tmap.items():
        if any(p in raw for p in patterns):
            return canon
    return ""


_NUM_RE = re.compile(r'\d+(?:\.\d+)?')


def parse_range(text, want_unit=None):
    if not text:
        return None, None
    nums = _NUM_RE.findall(text)
    if not nums:
        return None, None
    if want_unit:
        if want_unit == "匹" and "匹" not in text:
            return None, None
        if want_unit == "cm" and "cm" not in text.lower():
            return None, None
        if want_unit == "kg" and "kg" not in text.lower():
            return None, None
    lo = float(nums[0])
    hi = float(nums[1]) if len(nums) >= 2 else lo
    return lo, hi


def _v(d, key):
    """weather_detail から取得：キー無 → NULL / キー有り空文字 → "" / 値あり → 値"""
    if key not in d:
        return NULL
    v = d[key]
    return v if v != "" else ""


def _num(text, fallback=NULL):
    if not text:
        return fallback
    m = _NUM_RE.search(text)
    return m.group() if m else fallback


# data/V2/YYYY-MM.csv と完全一致する39列 + source = 40列
COLUMNS = [
    "ship", "area", "date", "trip_no", "is_cancellation",
    "tsuri_mono_raw", "tsuri_mono", "main_sub", "fish_raw",
    "time_slot",
    "cnt_min", "cnt_max", "cnt_avg",
    "is_boat",
    "size_min", "size_max",
    "kg_min", "kg_max",
    "tackle",
    "point_place1", "point_place2", "point_place3", "n_points_visited",
    "depth_min", "depth_max",
    "water_temp_min", "water_temp_max",
    "water_color",
    "wind_direction", "wind_speed",
    "tide_info", "wave_info", "weather",
    "by_catch",
    "cancel_reason", "cancel_type",
    "kanso_raw", "suion_raw", "suishoku_raw",
    # 追加: データソース識別
    "source",
]


def extract_points(kanso_raw, point_raw):
    """kanso_raw から地名抽出（○○沖・○○礁・○○海域）。なければ point_raw を point_place1 に。"""
    points = []
    if kanso_raw:
        points = re.findall(r'([一-龥ァ-ヶー]+(?:沖|礁|沿岸|海域))', kanso_raw)
    if points:
        pp1 = points[0]
        pp2 = points[1] if len(points) >= 2 else NULL
        pp3 = points[2] if len(points) >= 3 else NULL
        n = min(len(points), 3)
    else:
        pp1 = point_raw or NULL
        pp2 = NULL
        pp3 = NULL
        n = 1 if point_raw else 0
    return pp1, pp2, pp3, n


def convert(records, tmap):
    """JSON Raw → CSV行"""
    trip_fish = defaultdict(list)
    for r in records:
        key = (r["ship"], r["date"], r["trip_no"])
        trip_fish[key].append(r["fish_raw"])

    rows = []
    for r in records:
        wd = r.get("weather_detail", {})
        tsuri_mono = normalize_tsuri_mono(r["fish_raw"], tmap) or NULL
        main_sub = "メイン" if r.get("tokki_raw") == "メイン" else "サブ"

        # by_catch: メイン行のみ（同trip内の他魚種リスト）
        if main_sub == "メイン":
            key = (r["ship"], r["date"], r["trip_no"])
            others = [f for f in trip_fish[key] if f != r["fish_raw"]]
            by_catch_list = "・".join(others) if others else ""
        else:
            by_catch_list = NULL

        # 数値レンジ
        size_raw  = r.get("size_raw", "")
        count_raw = r.get("count_raw", "")
        if count_raw == "":
            cnt_min = cnt_max = cnt_avg = ""
        else:
            lo, hi = parse_range(count_raw, want_unit="匹")
            cnt_min = lo if lo is not None else ""
            cnt_max = hi if hi is not None else ""
            cnt_avg = (lo + hi) / 2 if (lo is not None and hi is not None) else ""
        if size_raw == "":
            size_min = size_max = kg_min = kg_max = ""
        else:
            s_lo, s_hi = parse_range(size_raw, want_unit="cm")
            k_lo, k_hi = parse_range(size_raw, want_unit="kg")
            size_min = s_lo if s_lo is not None else ""
            size_max = s_hi if s_hi is not None else ""
            kg_min   = k_lo if k_lo is not None else ""
            kg_max   = k_hi if k_hi is not None else ""

        # 海況（weather_detail から既存V2列に分配）
        water_t   = _num(wd["water_temp"], "") if "water_temp" in wd else NULL
        wind_dir  = _v(wd, "wind_dir")
        wind_sp   = _v(wd, "wind_speed")
        weather   = _v(wd, "weather")
        # tide_info: weather_detail.tide または tide_label（HTML上の潮ヘッダ）
        if "tide" in wd:
            tide_info = wd["tide"]
        elif r.get("tide_label"):
            tide_info = r["tide_label"]
        else:
            tide_info = NULL
        # wave_info: wave_dir + wave_height の組み合わせ
        if "wave_dir" in wd or "wave_height" in wd:
            wave_info = f"{wd.get('wave_dir','')} {wd.get('wave_height','')}".strip() or ""
        else:
            wave_info = NULL

        # ポイント
        pp1, pp2, pp3, n_pts = extract_points(r.get("kanso_raw", ""), r.get("point_raw"))

        rows.append({
            "ship":          r["ship"],
            "area":          r["area"],
            "date":          r["date"],
            "trip_no":       r["trip_no"],
            "is_cancellation": 0,
            "tsuri_mono_raw":  r.get("fish_raw") or NULL,
            "tsuri_mono":      tsuri_mono,
            "main_sub":        main_sub,
            "fish_raw":        r.get("fish_raw") or NULL,
            "time_slot":       NULL,
            "cnt_min":         cnt_min,
            "cnt_max":         cnt_max,
            "cnt_avg":         cnt_avg,
            "is_boat":         0,
            "size_min":        size_min,
            "size_max":        size_max,
            "kg_min":          kg_min,
            "kg_max":          kg_max,
            "tackle":          NULL,
            "point_place1":    pp1,
            "point_place2":    pp2,
            "point_place3":    pp3,
            "n_points_visited": n_pts,
            "depth_min":       NULL,
            "depth_max":       NULL,
            "water_temp_min":  water_t,
            "water_temp_max":  water_t,
            "water_color":     NULL,
            "wind_direction":  wind_dir,
            "wind_speed":      wind_sp,
            "tide_info":       tide_info,
            "wave_info":       wave_info,
            "weather":         weather,
            "by_catch":        by_catch_list,
            "cancel_reason":   NULL,
            "cancel_type":     NULL,
            "kanso_raw":       r.get("kanso_raw") or NULL,
            "suion_raw":       r.get("suion_raw") or NULL,
            "suishoku_raw":    NULL,
            "source":          r.get("source") or NULL,
        })
    return rows


def main():
    if not os.path.exists(IN_PATH):
        print(f"ERROR: {IN_PATH} が存在しません。先に hirono_crawler.py を実行してください。", file=sys.stderr)
        sys.exit(1)
    records = json.load(open(IN_PATH, encoding="utf-8"))
    tmap = load_tsuri_map()
    rows = convert(records, tmap)
    print(f"変換: {len(rows)}行")

    # 月別に分割（date='YYYY/MM/DD' → YYYY-MM）
    by_month = defaultdict(list)
    for r in rows:
        d = r["date"]
        if not d or len(d) < 7:
            continue
        yyyymm = d[:4] + "-" + d[5:7]
        by_month[yyyymm].append(r)

    os.makedirs(OUT_DIR, exist_ok=True)
    written = []
    for yyyymm, mrows in sorted(by_month.items()):
        out_path = os.path.join(OUT_DIR, f"hirono_{yyyymm}.csv")
        with open(out_path, "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=COLUMNS)
            w.writeheader()
            for r in mrows:
                w.writerow(r)
        written.append((yyyymm, len(mrows), out_path))
        print(f"  出力: {out_path} ({len(mrows)}行)")
    print(f"出力月別ファイル数: {len(written)}")


if __name__ == "__main__":
    main()
