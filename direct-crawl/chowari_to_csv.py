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
# crawler.py の複合主役ルール + kanso 抽出関数群を import
# chowari クロール由来のレコードに対しても釣りビジョン側と同等の正規化を適用
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    from crawler import (
        _get_multi_main as _crawler_get_multi_main,
        _extract_water_temp_range as _ext_water_temp,
        _extract_water_color as _ext_water_color,
        _extract_tide_info as _ext_tide_info,
        _extract_wave_info as _ext_wave_info,
        _extract_by_catch as _ext_by_catch,
    )
except ImportError:
    _crawler_get_multi_main = None
    _ext_water_temp = None
    _ext_water_color = None
    _ext_tide_info = None
    _ext_wave_info = None
    _ext_by_catch = None

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

        # by_catch: メイン行のみ。trip 内の他魚種 + kanso 由来「他に○○・ゲストに○○」を統合
        if main_sub == "メイン":
            others = [f for f in trip_fish[key] if f != r["fish_raw"]]
            trip_others = "・".join(others) if others else ""
            kanso_text = r.get("kanso_raw", "") or ""
            kanso_others = ""
            if _ext_by_catch and kanso_text:
                kanso_others = _ext_by_catch(kanso_text) or ""
            # 重複除去
            all_others = set()
            for s in (trip_others, kanso_others):
                if s:
                    for piece in s.replace("、", "・").split("・"):
                        piece = piece.strip()
                        if piece and piece != r["fish_raw"]:
                            all_others.add(piece)
            by_catch_list = "・".join(sorted(all_others)) if all_others else ""
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

        # 海況: HTML構造化データ（weather_detail）を1次ソース、kanso由来を2次として補完
        kanso = r.get("kanso_raw", "") or ""

        # 水温: HTML優先 → なければ kanso 内「水温15℃」「15-17℃」抽出
        if "water_temp" in wd:
            water_t_min = water_t_max = _num(wd["water_temp"], "")
        elif _ext_water_temp and kanso:
            wt = _ext_water_temp(kanso)
            water_t_min = wt.get("min", NULL) if wt else NULL
            water_t_max = wt.get("max", NULL) if wt else NULL
        else:
            water_t_min = water_t_max = NULL

        # 水色: chowari HTML には項目なし → kanso 由来のみ
        if _ext_water_color and kanso:
            wc = _ext_water_color(kanso)
            water_color = wc if wc else NULL
        else:
            water_color = NULL

        wind_dir  = _v(wd, "wind_dir")
        wind_sp   = _v(wd, "wind_speed")
        weather   = _v(wd, "weather")

        # 潮: HTML優先 → kanso 由来補完（「二枚潮」「潮流速い」等）
        if "tide" in wd:
            tide_html = wd["tide"]
            tide_kanso = _ext_tide_info(kanso) if (_ext_tide_info and kanso) else ""
            tide_info = (tide_html + ("・" + tide_kanso if tide_kanso else "")).strip("・")
        elif r.get("tide_label"):
            tide_info = r["tide_label"]
        elif _ext_tide_info and kanso:
            t = _ext_tide_info(kanso)
            tide_info = t if t else NULL
        else:
            tide_info = NULL

        # 波: HTML優先 → kanso 由来補完（「ベタ凪」「シケ」等）
        if "wave_dir" in wd or "wave_height" in wd:
            wave_html = f"{wd.get('wave_dir','')} {wd.get('wave_height','')}".strip()
            wave_kanso = _ext_wave_info(kanso) if (_ext_wave_info and kanso) else ""
            wave_info = (wave_html + ("・" + wave_kanso if wave_kanso else "")).strip("・")
        elif _ext_wave_info and kanso:
            w = _ext_wave_info(kanso)
            wave_info = w if w else NULL
        else:
            wave_info = NULL

        pp1, pp2, pp3, n_pts = extract_points(kanso, r.get("point_raw"))

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
            "water_temp_min":  water_t_min, "water_temp_max": water_t_max,
            "water_color":     water_color,
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


def main():
    """全 catches_raw_chowari_*.json を読み込み、月別1ファイルに統合出力。
    出力: data/V2/chowari_YYYY-MM.csv （釣りビジョン側の YYYY-MM.csv と同じ設計）
    """
    p = argparse.ArgumentParser()
    p.add_argument("--slug", help="（旧互換・無視される。全船宿統合出力のみ対応）")
    args = p.parse_args()

    tmap = load_tsuri_map()
    pattern = "catches_raw_chowari_*.json"
    files = sorted(glob.glob(os.path.join(ROOT, "direct-crawl", pattern)))
    print(f"=== chowari_to_csv: {len(files)}ファイル → 月別統合出力 ===")

    all_rows = []
    for in_path in files:
        if not os.path.exists(in_path):
            continue
        slug = os.path.basename(in_path).replace("catches_raw_chowari_", "").replace(".json", "")
        records = json.load(open(in_path, encoding="utf-8"))
        if not records:
            continue
        rows = convert(records, tmap)
        all_rows.extend(rows)

    # 月別グループ化
    by_month = defaultdict(list)
    for r in all_rows:
        d = r["date"]
        if not d or len(d) < 7:
            continue
        yyyymm = d[:4] + "-" + d[5:7]
        by_month[yyyymm].append(r)

    os.makedirs(OUT_DIR, exist_ok=True)
    files_written = 0
    rows_written = 0
    for yyyymm, mrows in sorted(by_month.items()):
        # ship, date, trip_no, fish_raw でソート（再現性確保）
        mrows.sort(key=lambda r: (r.get("ship", ""), r.get("date", ""),
                                   r.get("trip_no") or 0, r.get("fish_raw", "")))
        out_path = os.path.join(OUT_DIR, f"chowari_{yyyymm}.csv")
        with open(out_path, "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=COLUMNS)
            w.writeheader()
            for r in mrows:
                w.writerow(r)
        files_written += 1
        rows_written += len(mrows)
        print(f"  data/V2/chowari_{yyyymm}.csv: {len(mrows)}行")
    print(f"=== 完了: 月別統合CSV {files_written}ファイル / {rows_written}行 ===")


if __name__ == "__main__":
    main()
