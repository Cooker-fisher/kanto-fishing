"""
chowari_to_csv.py — chowari クロール出力（catches_raw_chowari_*.json）を data/V2 月別CSV化

hirono_to_csv.py の汎用版。船宿スラッグごとに別 CSV を生成。

入力:
    direct-crawl/catches_raw_chowari_{slug}.json
出力:
    data/V2/{slug}_YYYY-MM.csv

実行:
    # 全16隻分一括変換
    python direct-crawl/chowari_to_csv.py

    # 単一船宿
    python direct-crawl/chowari_to_csv.py --slug masakatsu-maru
"""

import argparse
import csv
import glob
import json
import os
import re
import sys
from collections import defaultdict

sys.stdout.reconfigure(encoding="utf-8")
# hirono_to_csv.py から共通ロジック流用
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hirono_to_csv import (
    NULL, normalize_tsuri_mono, parse_range,
    _v, _num, extract_points, COLUMNS,
)
# crawler.py の複合主役ルール（SHIP_KANSO_MULTI_MAIN / SHIP_TRIP_FISHSET_MULTI_MAIN / _get_multi_main）を import
# chowari クロール由来のレコードに対しても複合主役判定を適用する
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    from crawler import _get_multi_main as _crawler_get_multi_main
except ImportError:
    _crawler_get_multi_main = None

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "data", "V2")
MAP_PATH = os.path.join(ROOT, "normalize", "tsuri_mono_map_draft.json")


def load_tsuri_map():
    with open(MAP_PATH, encoding="utf-8") as f:
        return json.load(f).get("TSURI_MONO_MAP", {})


def convert(records, tmap):
    """JSON Raw → CSV行 (hirono_to_csv.convert と同等。ship 名は record 内のものを使う)"""
    trip_fish = defaultdict(list)
    for r in records:
        key = (r["ship"], r["date"], r["trip_no"])
        trip_fish[key].append(r["fish_raw"])

    rows = []
    for r in records:
        wd = r.get("weather_detail", {})
        tsuri_mono = normalize_tsuri_mono(r["fish_raw"], tmap) or NULL

        # 2026/05/16: 複合主役船ルールを適用
        # 1次判定: HTML <h2> 由来の tokki_raw='メイン'
        # 2次判定: _get_multi_main で複合主役セットに含まれる魚種を「メイン」に昇格
        key = (r["ship"], r["date"], r["trip_no"])
        trip_fish_set = frozenset(trip_fish[key])
        multi_mains = None
        if _crawler_get_multi_main is not None:
            multi_mains = _crawler_get_multi_main(r["ship"], r.get("kanso_raw", "") or "", trip_fish_set)
        if multi_mains:
            # 複合主役船便: ルールセットに含まれる正規化魚種なら「メイン」
            fish_norm = normalize_tsuri_mono(r["fish_raw"], tmap)
            main_sub = "メイン" if fish_norm in multi_mains else "サブ"
        else:
            # 通常便: HTML <h2> 由来の tokki_raw を採用
            main_sub = "メイン" if r.get("tokki_raw") == "メイン" else "サブ"

        if main_sub == "メイン":
            others = [f for f in trip_fish[key] if f != r["fish_raw"]]
            by_catch_list = "・".join(others) if others else ""
        else:
            by_catch_list = NULL

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

        water_t   = _num(wd["water_temp"], "") if "water_temp" in wd else NULL
        wind_dir  = _v(wd, "wind_dir")
        wind_sp   = _v(wd, "wind_speed")
        weather   = _v(wd, "weather")
        if "tide" in wd:
            tide_info = wd["tide"]
        elif r.get("tide_label"):
            tide_info = r["tide_label"]
        else:
            tide_info = NULL
        if "wave_dir" in wd or "wave_height" in wd:
            wave_info = f"{wd.get('wave_dir','')} {wd.get('wave_height','')}".strip() or ""
        else:
            wave_info = NULL

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
            "cnt_min": cnt_min, "cnt_max": cnt_max, "cnt_avg": cnt_avg,
            "is_boat": 0,
            "size_min": size_min, "size_max": size_max,
            "kg_min": kg_min, "kg_max": kg_max,
            "tackle":          NULL,
            "point_place1": pp1, "point_place2": pp2, "point_place3": pp3,
            "n_points_visited": n_pts,
            "depth_min": NULL, "depth_max": NULL,
            "water_temp_min":  water_t, "water_temp_max": water_t,
            "water_color":     NULL,
            "wind_direction":  wind_dir, "wind_speed": wind_sp,
            "tide_info":       tide_info, "wave_info": wave_info, "weather": weather,
            "by_catch":        by_catch_list,
            "cancel_reason":   NULL, "cancel_type": NULL,
            "kanso_raw":       r.get("kanso_raw") or NULL,
            "suion_raw":       r.get("suion_raw") or NULL,
            "suishoku_raw":    NULL,
            "source":          r.get("source") or NULL,
        })
    return rows


def process_one(in_path: str, slug: str, tmap: dict):
    """1ファイルを処理して月別CSVを出力"""
    records = json.load(open(in_path, encoding="utf-8"))
    if not records:
        print(f"  [{slug}] 0件 → スキップ")
        return 0, 0
    rows = convert(records, tmap)

    by_month = defaultdict(list)
    for r in rows:
        d = r["date"]
        if not d or len(d) < 7:
            continue
        yyyymm = d[:4] + "-" + d[5:7]
        by_month[yyyymm].append(r)

    os.makedirs(OUT_DIR, exist_ok=True)
    files_written = 0
    rows_written = 0
    for yyyymm, mrows in sorted(by_month.items()):
        out_path = os.path.join(OUT_DIR, f"{slug}_{yyyymm}.csv")
        with open(out_path, "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=COLUMNS)
            w.writeheader()
            for r in mrows:
                w.writerow(r)
        files_written += 1
        rows_written += len(mrows)
        print(f"    {out_path}: {len(mrows)}行")
    return files_written, rows_written


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--slug", help="特定slugのみ処理")
    args = p.parse_args()

    tmap = load_tsuri_map()
    pattern = "catches_raw_chowari_*.json"
    if args.slug:
        files = [os.path.join(ROOT, "direct-crawl", f"catches_raw_chowari_{args.slug}.json")]
    else:
        files = sorted(glob.glob(os.path.join(ROOT, "direct-crawl", pattern)))

    print(f"=== chowari_to_csv: {len(files)}ファイル処理 ===")
    total_files = 0
    total_rows = 0
    for in_path in files:
        if not os.path.exists(in_path):
            continue
        slug = os.path.basename(in_path).replace("catches_raw_chowari_", "").replace(".json", "")
        print(f"  [{slug}] 処理中...")
        f, r = process_one(in_path, slug, tmap)
        total_files += f
        total_rows += r
    print(f"=== 完了: 月別CSV {total_files}ファイル / {total_rows}行 ===")


if __name__ == "__main__":
    main()
