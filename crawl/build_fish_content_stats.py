"""fish_content.json のプレースホルダ用統計スナップショットを生成する（月1実行）。

normalize/fish_content.json に収載された魚種について、data/V2/*.csv から
標準統計キーを集計し normalize/fish_content_stats.json に書き出す。
crawler.py の load_fish_content() がこのスナップショットを読んで固定文に差し込む。

設計（2026-06-11 決定・90_決定ログ参照）:
- 数値を毎日再計算すると固定プローズと数値が乖離し文意がズレるリスクがあるため、
  月1スナップショット方式とする。数値更新と文章の整合チェックを同じ月1セッションで行う。
- 集計フィルタは crawler.py の FAQ Q3 と同一（_cnt_personal_csv / _is_plausible_cnt）。
  ページ内で FAQ と固定文の数値が矛盾しないことを優先する。

実行:
    python crawl/build_fish_content_stats.py
"""
import os
import sys
import json
import statistics
from collections import Counter
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import crawler  # noqa: E402  （_load_historical_catches / _is_plausible_cnt / _cnt_personal_csv を流用）

CONTENT_PATH = os.path.join(ROOT, "normalize", "fish_content.json")
STATS_PATH = os.path.join(ROOT, "normalize", "fish_content_stats.json")


def _fnum(v):
    try:
        f = float(v)
        return f if f > 0 else None
    except (ValueError, TypeError):
        return None


def _pct(sorted_vals, q):
    """単純分位（FAQ Q3 の int(n*q) 方式と同じ流儀）"""
    if not sorted_vals:
        return None
    idx = min(int(len(sorted_vals) * q), len(sorted_vals) - 1)
    return sorted_vals[idx]


def build_stats_for_fish(fish, rows):
    rs = [r for r in rows if r.get("tsuri_mono") == fish and not crawler._hist_is_cancelled(r)]
    if not rs:
        return None
    st = {}
    st["n_total"] = f"{len(rs):,}"
    st["n_ships"] = f"{len(set(r.get('ship') for r in rs if r.get('ship'))):,}"
    # 匹数: FAQ Q3 と同一フィルタ（個人釣果のみ・cnt_max・非現実値除外・ボウズ便除外）
    maxes = []
    for r in rs:
        if not crawler._cnt_personal_csv(r):
            continue
        v = _fnum(r.get("cnt_max"))
        if v is None:
            continue
        v = int(v)
        if crawler._is_plausible_cnt(fish, v) and v > 0:
            maxes.append(v)
    if maxes:
        sm = sorted(maxes)
        st["cnt_median"] = f"{int(statistics.median(sm)):,}"
        st["cnt_p90"] = f"{_pct(sm, 0.90):,}"
        st["cnt_max"] = f"{sm[-1]:,}"
    # サイズ（cm）: size_max の中央値
    sizes = [v for r in rs for v in [_fnum(r.get("size_max"))]
             if v is not None and crawler._is_plausible_size_cm(v, v)]
    if sizes:
        st["size_p50"] = f"{int(statistics.median(sizes))}"
    # 月別件数
    mon = Counter(r["date"][5:7] for r in rs if len(r.get("date", "")) >= 7)
    if mon:
        ranked = sorted(mon.items(), key=lambda x: -x[1])
        st["month_top1"] = f"{int(ranked[0][0])}月"
        st["month_top1_n"] = f"{ranked[0][1]:,}"
        if len(ranked) >= 2:
            st["month_top2"] = f"{int(ranked[1][0])}月"
            st["month_top2_n"] = f"{ranked[1][1]:,}"
        low = min(mon.items(), key=lambda x: x[1])
        st["month_low"] = f"{int(low[0])}月"
        st["month_low_n"] = f"{low[1]:,}"
    # ポイント TOP3
    pts = Counter(r.get("point_place1") for r in rs
                  if r.get("point_place1") and r.get("point_place1") != "NULL")
    for i, (p, n) in enumerate(pts.most_common(3), start=1):
        st[f"point{i}"] = p
        st[f"point{i}_n"] = f"{n:,}"
    # 港エリア TOP3
    areas = Counter(r.get("area") for r in rs if r.get("area"))
    for i, (a, n) in enumerate(areas.most_common(3), start=1):
        st[f"area{i}"] = a
        st[f"area{i}_n"] = f"{n:,}"
    # 水深（depth_min の P20/P80）
    deps = sorted(v for r in rs for v in [_fnum(r.get("depth_min"))] if v is not None)
    if len(deps) >= 10:
        st["depth_p20"] = f"{int(_pct(deps, 0.20))}"
        st["depth_p80"] = f"{int(_pct(deps, 0.80))}"
    return st


def main():
    with open(CONTENT_PATH, encoding="utf-8") as f:
        content = json.load(f)
    fishes = [k for k in content.keys() if not k.startswith("_")]
    print(f"対象: {len(fishes)}件 先頭3: {fishes[:3]}")
    rows = crawler._load_historical_catches()
    print(f"hist_rows: {len(rows):,}行")
    out = {"generated": date.today().isoformat(), "fish": {}}
    for fish in fishes:
        st = build_stats_for_fish(fish, rows)
        if st is None:
            print(f"  WARN: {fish} レコード0件・スキップ")
            continue
        out["fish"][fish] = st
        print(f"  {fish}: {len(st)}キー (n_total={st.get('n_total')})")
    with open(STATS_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"書き出し: {STATS_PATH}")


if __name__ == "__main__":
    main()
