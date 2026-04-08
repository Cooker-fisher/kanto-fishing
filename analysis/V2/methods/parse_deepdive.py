#!/usr/bin/env python3
"""
parse_deepdive.py — deep_dive/*.txt → deepdive_params.json

deep_diveテキストから旬別ベースライン・精度指標・海況因子を抽出し、
予測スクリプト(predict_count.py)が読める構造化JSONを生成する。

使い方:
  python insights/parse_deepdive.py
出力:
  insights/deepdive_params.json
"""

import json, os, re, sys
sys.stdout.reconfigure(encoding="utf-8")

import sys as _sys; _sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _paths import ROOT_DIR, RESULTS_DIR, DATA_DIR, NORMALIZE_DIR, OCEAN_DIR
DIVE_DIR  = os.path.join(RESULTS_DIR, "deep_dive")
OUT_FILE  = os.path.join(RESULTS_DIR, "deepdive_params.json")


# ── パーサー ────────────────────────────────────────────────────────────────

def parse_file(path: str) -> dict | None:
    """1つの deep_dive テキストを解析して dict を返す。失敗時 None。"""
    with open(path, encoding="utf-8") as f:
        text = f.read()

    # --- ヘッダー: 魚種 × 船宿 ---
    m = re.search(r'([^\s×]+)\s*×\s*(.+)', text)
    if not m:
        return None
    fish = m.group(1).strip()
    ship = m.group(2).strip()

    result = {"fish": fish, "ship": ship}

    # --- 基本統計 ---
    stats = {}
    m = re.search(r'件数:\s*(\d+)件', text)
    if m:
        stats["n"] = int(m.group(1))

    m = re.search(r'cnt_avg\s*:\s*平均\s*([\d.]+)匹.*?std\s*([\d.]+)\s*\[([\d.]+)\s*〜\s*([\d.]+)\]', text)
    if m:
        stats["cnt_avg_mean"] = float(m.group(1))
        stats["cnt_avg_std"]  = float(m.group(2))
        stats["cnt_avg_min"]  = float(m.group(3))
        stats["cnt_avg_max"]  = float(m.group(4))

    m = re.search(r'size_avg\s*:\s*平均\s*([\d.]+)cm\s*std\s*([\d.]+)\s*\[([\d.]+)\s*〜\s*([\d.]+)\]', text)
    if m:
        stats["size_avg_mean"] = float(m.group(1))
        stats["size_avg_std"]  = float(m.group(2))
        stats["size_avg_min"]  = float(m.group(3))
        stats["size_avg_max"]  = float(m.group(4))

    # size が cm でなく kg の魚（タチウオ等）
    m = re.search(r'size_avg\s*:\s*平均\s*([\d.]+)cm', text)
    if not m:
        # kg 表記を探す
        m2 = re.search(r'size_avg\s*:\s*平均\s*([\d.]+)kg', text)
        if m2:
            stats["size_unit"] = "kg"

    result["stats"] = stats

    # --- 旬別ベースライン ---
    dekad_section = re.search(
        r'【旬別ベースライン.*?】\n.*?-+\n(.*?)(?=\n【|\Z)',
        text, re.DOTALL
    )
    dekads = {}
    if dekad_section:
        for line in dekad_section.group(1).splitlines():
            # 旬番号  期待  実績  偏差  n
            m = re.match(r'\s*(\d+)\s+([\d.]+)\s+([\d.]+)\s+([+\-][\d.]+)\s+(\d+)', line)
            if m:
                dekad_no = int(m.group(1))
                dekads[dekad_no] = {
                    "expected": float(m.group(2)),
                    "actual":   float(m.group(3)),
                    "n":        int(m.group(5)),
                }
    result["baseline_by_dekad"] = dekads

    # --- 因子相関 ---
    factors = {"cnt_avg": [], "cnt_max": [], "size_avg": []}
    current_target = None
    in_factor_section = False

    for line in text.splitlines():
        if "【因子相関" in line:
            in_factor_section = True
            continue
        if in_factor_section and line.startswith("【"):
            in_factor_section = False
            continue
        if not in_factor_section:
            continue

        m = re.match(r'\s*\[(cnt_avg|cnt_max|size_avg)\]', line)
        if m:
            current_target = m.group(1)
            continue

        if current_target:
            # factor_name  r=±X.XXX*  p=X.XXX  n=XX  ↑/↓
            m = re.match(
                r'\s*(\w+)\s+r=([+\-][\d.]+)(\*{0,2})\s+p=([\d.]+)\s+n=(\d+)\s+([↑↓])',
                line
            )
            if m:
                r_val = float(m.group(2))
                p_val = float(m.group(4))
                if p_val < 0.1:  # p<0.1 のみ保持
                    factors[current_target].append({
                        "factor":    m.group(1),
                        "r":         r_val,
                        "p":         p_val,
                        "sig":       m.group(3),   # "*" or "**" or ""
                        "direction": m.group(6),
                    })

    result["weather_factors"] = factors

    # --- マルチホライズン精度（H=7dを基準に保存） ---
    accuracy = {}

    def _parse_horizon_block(target_label: str, acc_key: str, unit: str):
        """Ave匹数 / Min匹数 / Max匹数 / Ave型 ブロックをパース"""
        pat = (
            rf'─\s*{re.escape(target_label)}\s*─.*?'
            rf'H=\s*0\(実測\)\s+([+\-][\d.]+)[\*\s]+\s*([\d.]+){re.escape(unit)}\s+([\d.]+)%.*?\n'
            rf'.*?H=\s*1d\s+前\s+([+\-][\d.]+)[\*\s]+\s*([\d.]+){re.escape(unit)}\s+([\d.]+)%.*?\n'
            rf'.*?H=\s*3d\s+前\s+([+\-][\d.]+)[\*\s]+\s*([\d.]+){re.escape(unit)}\s+([\d.]+)%.*?\n'
            rf'.*?H=\s*7d\s+前\s+([+\-][\d.]+)[\*\s]+\s*([\d.]+){re.escape(unit)}\s+([\d.]+)%'
        )
        m = re.search(pat, text, re.DOTALL)
        if m:
            accuracy[acc_key] = {
                "h0":  {"r": float(m.group(1)),  "mae": float(m.group(2)),  "mape": float(m.group(3))},
                "h1":  {"r": float(m.group(4)),  "mae": float(m.group(5)),  "mape": float(m.group(6))},
                "h3":  {"r": float(m.group(7)),  "mae": float(m.group(8)),  "mape": float(m.group(9))},
                "h7":  {"r": float(m.group(10)), "mae": float(m.group(11)), "mape": float(m.group(12))},
            }

    # ホライズンブロックをシンプルな行パースに切り替え
    def _parse_horizon_simple(section_label: str) -> dict | None:
        """
        '─ Ave匹数 ─' 等のブロックから H=0,1,3,7d のデータを取得。
        単位（匹/cm/kg）はそのまま読む。
        """
        # ブロック開始
        pat_start = re.escape(section_label)
        sec_m = re.search(pat_start + r'(.*?)(?=─\s|\Z)', text, re.DOTALL)
        if not sec_m:
            return None
        block = sec_m.group(1)

        horizons = {}
        for h_label, h_key in [("0(実測)", "h0"), ("1d 前", "h1"), ("3d 前", "h3"),
                                 ("7d 前", "h7"), ("14d 前", "h14"), ("21d 前", "h21"),
                                 ("28d 前", "h28")]:
            lm = re.search(
                rf'H=\s*{re.escape(h_label)}\s+([+\-][\d.]+)[\*\s]+\s*([\d.]+)(?:匹|cm|kg)\s+([\d.]+)%',
                block
            )
            if lm:
                horizons[h_key] = {
                    "r":    float(lm.group(1)),
                    "mae":  float(lm.group(2)),
                    "mape": float(lm.group(3)),
                }
        return horizons if horizons else None

    for label, key in [
        ("─ Ave匹数 ─", "cnt_avg"),
        ("─ Min匹数 ─", "cnt_min"),
        ("─ Max匹数 ─", "cnt_max"),
        ("─ Ave型   ─", "size_avg"),
    ]:
        h = _parse_horizon_simple(label)
        if h:
            accuracy[key] = h

    result["accuracy"] = accuracy

    # --- ポイント別集計（参考） ---
    point_section = re.search(
        r'【ポイント別集計】\n(.*?)(?=\n【|\Z)',
        text, re.DOTALL
    )
    points = {}
    if point_section:
        for line in point_section.group(1).splitlines():
            # ポイント名  n  平均  最大  最小
            m = re.match(r'\s*(.+?)\s{2,}(\d+)\s+([\d.]+)\s+(\d+)\s+(\d+)', line)
            if m:
                pt = m.group(1).strip()
                if pt and not pt.startswith("-") and pt != "ポイント":
                    points[pt] = {
                        "n":    int(m.group(2)),
                        "avg":  float(m.group(3)),
                        "max":  int(m.group(4)),
                        "min":  int(m.group(5)),
                    }
    result["points"] = points

    return result


# ── ★評価 ────────────────────────────────────────────────────────────────────

def calc_stars(acc: dict, n: int) -> int:
    """cnt_avg の H=7d MAPE + サンプル数から ★1〜5 を返す。"""
    h7 = (acc.get("cnt_avg") or {}).get("h7")
    if not h7:
        return 1
    mape = h7["mape"]
    if   mape < 25 and n >= 50: return 5
    elif mape < 35 and n >= 30: return 4
    elif mape < 50 and n >= 20: return 3
    elif mape < 65 and n >= 10: return 2
    else:                        return 1


# ── メイン ───────────────────────────────────────────────────────────────────

def main():
    files = sorted(f for f in os.listdir(DIVE_DIR) if f.endswith(".txt"))
    print(f"対象ファイル: {len(files)} 件")

    results = []
    errors  = []

    for fname in files:
        path = os.path.join(DIVE_DIR, fname)
        try:
            rec = parse_file(path)
            if rec is None:
                errors.append((fname, "ヘッダー解析失敗"))
                continue
            n = rec["stats"].get("n", 0)
            rec["stars"] = calc_stars(rec["accuracy"], n)
            results.append(rec)
        except Exception as e:
            errors.append((fname, str(e)))

    # --- 出力 ---
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f"✅ 出力: {OUT_FILE}  ({len(results)} コンボ)")

    if errors:
        print(f"⚠️  エラー {len(errors)} 件:")
        for fname, msg in errors:
            print(f"  {fname}: {msg}")

    # --- サマリー表示 ---
    star_dist = {1:0, 2:0, 3:0, 4:0, 5:0}
    for r in results:
        star_dist[r["stars"]] += 1
    print("\n★分布:")
    for s in range(5, 0, -1):
        bar = "★" * s + "☆" * (5-s)
        print(f"  {bar} : {star_dist[s]:3d} コンボ")

    # MAPE分布
    mapes = []
    for r in results:
        h7 = (r["accuracy"].get("cnt_avg") or {}).get("h7")
        if h7:
            mapes.append(h7["mape"])
    if mapes:
        mapes.sort()
        print(f"\ncnt_avg MAPE@H=7d: 中央値 {mapes[len(mapes)//2]:.1f}%  "
              f"最小 {min(mapes):.1f}%  最大 {max(mapes):.1f}%")
        usable = sum(1 for m in mapes if m < 50)
        print(f"MAPE<50%(★★★以上): {usable}/{len(mapes)} コンボ ({100*usable/len(mapes):.0f}%)")


if __name__ == "__main__":
    main()
