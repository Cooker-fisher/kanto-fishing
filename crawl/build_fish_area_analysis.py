#!/usr/bin/env python3
"""build_fish_area_analysis.py — C層 analysis.sqlite を fish_area/ship 向けに蒸留（2026-07-03 新設）

背景・設計:
  - analysis.sqlite は .gitignore（CI 不在）。E層 crawler.py は直接読めない。
  - fish_content.json / predict_params.sqlite と同じく「蒸留スナップショットをコミット→crawler が読む」方式。
  - 出力: normalize/fish_area_analysis.json（魚種×エリア）+ normalize/ship_analysis.json（船宿）
  - 数値は月1程度の再分析でしか動かないため daily drift しない（不変条件でも鮮度は問わない）。

蒸留する信号（読者向け「海況と釣期の傾向」セクション用）:
  - factors: surface 可能な海況/水温/黒潮/潮汐因子で、エリア内船宿が「方向（r符号）で一致」するもの上位3。
             方向（多い/少ない）は r 符号から機械生成（因果は断定せず観測相関の記述）。
  - peaks:   旬別（10日）平均釣果のピーク上位2（decade_no → 月・上中下旬）。
  - accuracy: cnt_avg backtest の wMAPE 中央値 + BL2（平年ベースライン）を上回った船宿数。
  - n_ships / n_records: 分析済み船宿数・総レコード数（コンテンツの厚みの根拠）。

方針:
  - MIN_N_COMBO=30 未満のコンボは分析対象外（母数不足）。
  - factor は |r|>=R_MIN(0.30) かつ factor_labels.json で surface=true のもののみ。
  - 複数船宿で符号が割れる因子は「多数派の方向 + 一致船宿数>=majority」のときのみ採用。

使い方:
  python crawl/build_fish_area_analysis.py            # 生成
  python crawl/build_fish_area_analysis.py --dry-run  # 集計サマリーのみ表示
"""
import argparse
import json
import os
import re
import sqlite3
import sys
from collections import defaultdict

sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, "analysis", "V2", "results", "analysis.sqlite")
SHIPS = os.path.join(ROOT, "crawl", "ships.json")
LABELS = os.path.join(ROOT, "normalize", "factor_labels.json")
OUT_FA = os.path.join(ROOT, "normalize", "fish_area_analysis.json")
OUT_SHIP = os.path.join(ROOT, "normalize", "ship_analysis.json")

MIN_N_COMBO = 30      # コンボの母数下限
R_MIN = 0.30          # |r| 下限（弱すぎる相関は出さない）
MAX_FACTORS = 3       # ページに出す因子数上限
SEASON_SUFFIX = re.compile(r"_(spring|summer|autumn|winter)$")


def _load_labels():
    with open(LABELS, encoding="utf-8") as f:
        return json.load(f)["factors"]


def _base_factor(factor):
    return SEASON_SUFFIX.sub("", factor)


def _decade_label(decade_no):
    """decade_no(1-36) → '7月上旬' 等。"""
    try:
        d = int(decade_no)
    except (TypeError, ValueError):
        return None
    if not (1 <= d <= 36):
        return None
    month = (d - 1) // 3 + 1
    jun = ["上旬", "中旬", "下旬"][(d - 1) % 3]
    return f"{month}月{jun}"


def _strength_word(absr):
    if absr >= 0.55:
        return "強く"
    if absr >= 0.42:
        return "やや強く"
    return "ゆるやかに"


def _collect_factors(rows, labels):
    """rows=[(ship, factor, r), ...] → surface 可能因子を方向一致で集約し上位を返す。

    戻り: [{base, label, kind, direction('多い'/'少ない'), strength, n_ships, avg_absr}, ...]
    """
    by_base = defaultdict(lambda: {"pos": [], "neg": [], "ships": set()})
    for ship, factor, r in rows:
        if r is None or abs(r) < R_MIN:
            continue
        base = _base_factor(factor)
        meta = labels.get(base)
        if not meta or not meta.get("surface"):
            continue
        slot = by_base[base]
        slot["ships"].add(ship)
        (slot["pos"] if r > 0 else slot["neg"]).append(abs(r))

    out = []
    for base, slot in by_base.items():
        npos, nneg = len(slot["pos"]), len(slot["neg"])
        if npos == 0 and nneg == 0:
            continue
        # 方向が割れる場合は多数派を採用。同数なら不採用（矛盾信号を出さない）。
        if npos == nneg:
            continue
        if npos > nneg:
            direction, absrs, agree = "多い", slot["pos"], npos
        else:
            direction, absrs, agree = "少ない", slot["neg"], nneg
        meta = labels[base]
        avg_absr = sum(absrs) / len(absrs)
        out.append({
            "base": base,
            "label": meta["label"],
            "kind": meta.get("kind", "other"),
            "flag": bool(meta.get("flag")),
            "direction": direction,
            "strength": _strength_word(avg_absr),
            "n_ships": agree,
            "avg_absr": round(avg_absr, 3),
        })
    # 一致船宿数 → 相関強度 で順位付け
    out.sort(key=lambda x: (x["n_ships"], x["avg_absr"]), reverse=True)
    return out[:MAX_FACTORS]


def _peaks(decadal_rows):
    """decadal_rows=[(decade_no, n, avg_cnt), ...] → 旬ピーク上位2ラベル。"""
    agg = defaultdict(lambda: [0.0, 0])  # decade -> [weighted_sum, n]
    for dno, n, avg_cnt in decadal_rows:
        if avg_cnt is None or n is None or n <= 0:
            continue
        agg[dno][0] += avg_cnt * n
        agg[dno][1] += n
    scored = []
    for dno, (ws, ntot) in agg.items():
        if ntot <= 0:
            continue
        lbl = _decade_label(dno)
        if lbl:
            scored.append((ws / ntot, lbl))
    scored.sort(reverse=True)
    # ラベル重複除去（同月上中下旬が並ぶことがある）
    seen, peaks = set(), []
    for _, lbl in scored:
        if lbl in seen:
            continue
        seen.add(lbl)
        peaks.append(lbl)
        if len(peaks) >= 2:
            break
    return peaks


def build(dry_run=False):
    ships = json.load(open(SHIPS, encoding="utf-8"))
    name2area = {s["name"]: s.get("area") for s in ships if s.get("name")}
    labels = _load_labels()
    c = sqlite3.connect(DB)

    combos = [(f, s, n) for f, s, n in
              c.execute("SELECT fish, ship, n_records FROM combo_meta").fetchall()]

    # --- fish_area: (fish, area) 集約 ---
    fa_ships = defaultdict(list)  # (fish, area) -> [ship, ...]
    for fish, ship, n in combos:
        if n is None or n < MIN_N_COMBO:
            continue
        area = name2area.get(ship)
        if not area:
            continue
        fa_ships[(fish, area)].append(ship)

    fa_out = {}
    for (fish, area), shiplist in fa_ships.items():
        qs = "(" + ",".join("?" * len(shiplist)) + ")"
        wx = c.execute(
            f"""SELECT ship, factor, r FROM combo_wx_params
                WHERE fish=? AND metric='cnt_avg' AND r IS NOT NULL AND ship IN {qs}""",
            [fish, *shiplist]).fetchall()
        factors = _collect_factors(wx, labels)
        dec = c.execute(
            f"""SELECT decade_no, n, avg_cnt FROM combo_decadal
                WHERE fish=? AND ship IN {qs}""", [fish, *shiplist]).fetchall()
        peaks = _peaks(dec)
        bt = c.execute(
            f"""SELECT wmape, bl2_wmape FROM combo_backtest
                WHERE fish=? AND metric='cnt_avg' AND horizon=0 AND ship IN {qs}""",
            [fish, *shiplist]).fetchall()
        wmapes = sorted(w for w, _ in bt if w is not None)
        beat = sum(1 for w, b in bt if w is not None and b is not None and w < b)
        n_records = sum(
            c.execute("SELECT n_records FROM combo_meta WHERE fish=? AND ship=?",
                      (fish, ship)).fetchone()[0] or 0 for ship in shiplist)
        wmape_med = round(wmapes[len(wmapes) // 2], 1) if wmapes else None

        # 何も語れない（因子ゼロ かつ ピークゼロ）なら出さない
        if not factors and not peaks:
            continue
        fa_out[f"{fish}|{area}"] = {
            "fish": fish, "area": area,
            "n_ships": len(shiplist), "n_records": n_records,
            "peaks": peaks,
            "factors": factors,
            "wmape_median": wmape_med,
            "model_beats_baseline": beat,
            "n_backtested": len(wmapes),
        }

    # --- ship: 船宿 集約（魚種横断） ---
    ship_out = {}
    ship_fish = defaultdict(list)
    for fish, ship, n in combos:
        if n is None or n < MIN_N_COMBO:
            continue
        ship_fish[ship].append((fish, n))
    for ship, fishlist in ship_fish.items():
        area = name2area.get(ship)
        fishes = sorted(fishlist, key=lambda x: x[1], reverse=True)
        per_fish = []
        for fish, n in fishes[:6]:
            wx = c.execute(
                """SELECT ship, factor, r FROM combo_wx_params
                   WHERE fish=? AND ship=? AND metric='cnt_avg' AND r IS NOT NULL""",
                (fish, ship)).fetchall()
            factors = _collect_factors(wx, labels)
            dec = c.execute(
                "SELECT decade_no, n, avg_cnt FROM combo_decadal WHERE fish=? AND ship=?",
                (fish, ship)).fetchall()
            peaks = _peaks(dec)
            if not factors and not peaks:
                continue
            per_fish.append({
                "fish": fish, "n_records": n,
                "peaks": peaks, "factors": factors,
            })
        if not per_fish:
            continue
        ship_out[ship] = {
            "ship": ship, "area": area,
            "n_fish_analyzed": len(per_fish),
            "fish": per_fish,
        }

    c.close()

    print(f"fish_area: {len(fa_out)} ペア（因子/ピークあり）")
    print(f"  うち factors>=1: {sum(1 for v in fa_out.values() if v['factors'])}")
    print(f"  うち n_ships>=2: {sum(1 for v in fa_out.values() if v['n_ships'] >= 2)}")
    print(f"ship: {len(ship_out)} 船宿")
    # サンプル
    for k in list(fa_out)[:3]:
        print("  例:", k, "→", json.dumps(fa_out[k], ensure_ascii=False)[:240])

    if dry_run:
        print("\n[dry-run] ファイル未書き込み")
        return

    with open(OUT_FA, "w", encoding="utf-8") as f:
        json.dump(fa_out, f, ensure_ascii=False, indent=1)
    with open(OUT_SHIP, "w", encoding="utf-8") as f:
        json.dump(ship_out, f, ensure_ascii=False, indent=1)
    print(f"\n書き込み: {OUT_FA} ({len(fa_out)}) / {OUT_SHIP} ({len(ship_out)})")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    build(dry_run=args.dry_run)
