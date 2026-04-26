"""
diag_delta_factors.py — Phase 2 (C) 転換点検知 delta系特徴量の有効性診断（読み取り専用）

目的:
    04/24 に combo_deep_dive.py へ追加した5特徴量が高wMAPEコンボでどの程度
    採用されているか・採用コンボでの相関を定量化する。
    強制適用シミュレーションは禁止（p-hacking回避）。

対象特徴量:
    - sst_delta_3d         (SLOW: SLOW_FACTORS)
    - pressure_delta_48h   (FAST: FAST_FACTORS)
    - kuroshio_sla_delta_1m (SLOW: SLOW_FACTORS)
    - sss_delta_7d         (SLOW: SLOW_FACTORS)
    - day_of_decade        (SLOW/CALENDAR: SLOW_FACTORS + CALENDAR_FACTORS)

注記:
    - combo_wx_params に H 列なし（粒度: fish×ship×metric×factor）
    - alpha_scale が NULL の行が約95% → 寄与度評価は |r| 単体
    - ships.json で exclude:true / boat_only:true の船宿は除外

実行方法:
    python analysis/V2/methods/diag_delta_factors.py
"""

import os
import sys
import sqlite3
import json
import statistics
from collections import defaultdict
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _paths import RESULTS_DIR, ROOT_DIR

DB_PATH    = os.path.join(RESULTS_DIR, "analysis.sqlite")
SHIPS_JSON = os.path.join(ROOT_DIR, "crawl", "ships.json")
OUT_DIR    = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                           "..", "analysis-improvement"))
OUT_FILE   = os.path.join(OUT_DIR, "diag_delta_factors_2026-04-26.md")

DELTA_FACTORS = [
    "sst_delta_3d",
    "pressure_delta_48h",
    "kuroshio_sla_delta_1m",
    "sss_delta_7d",
    "day_of_decade",
]

# Phase 2 で確認した FAST/SLOW 分類（combo_deep_dive.py より）
FACTOR_CLASSIFICATION = {
    "sst_delta_3d":          "SLOW (SLOW_FACTORS)",
    "pressure_delta_48h":    "FAST (FAST_FACTORS)",
    "kuroshio_sla_delta_1m": "SLOW (SLOW_FACTORS)",
    "sss_delta_7d":          "SLOW (SLOW_FACTORS / CMEMS_FACTORS)",
    "day_of_decade":         "SLOW + CALENDAR (SLOW_FACTORS + CALENDAR_FACTORS)",
}

# Phase 1 で判明した高wMAPE・BL-2負けコンボリスト
PHASE1_BL2_FAIL_H0 = [
    ("キハダマグロ", "ちがさき丸"),
    ("キハダマグロ", "はら丸"),
    ("キハダマグロ", "翔太丸"),
    ("カツオ",       "博栄丸"),
    ("マダイ",       "庄治郎丸"),
    ("泳がせ五目",   "大盛丸"),
    ("マハタ",       "幸栄丸"),
    ("マダコ",       "こなや丸"),
]
PHASE1_HIGH_WMAPE = [
    ("タイ五目",   "大盛丸"),
    ("サワラ",     "こなや丸"),
    ("カツオ",     "幸丸"),
    ("イナダ",     "庄治郎丸"),
    ("タイ五目",   "ちがさき丸"),
    ("イサキ",     "勘栄丸"),
    ("タイ五目",   "庄治郎丸"),
    ("シイラ",     "共栄丸"),
]
PHASE1_FAST_MISUSE = [
    ("メバル",   "幸栄丸"),
    ("イシダイ", "平作丸"),
    ("ヒラメ",   "弘漁丸"),
    ("クロダイ", "平作丸"),
]


def load_excluded_ships(ships_json: str) -> set:
    with open(ships_json, encoding="utf-8") as f:
        ships = json.load(f)
    return {s["name"] for s in ships if s.get("exclude") or s.get("boat_only")}


def pragma_table_info(conn, table: str):
    cur = conn.cursor()
    cur.execute(f"PRAGMA table_info({table})")
    return cur.fetchall()


def fetch_delta_adoptions(conn, excluded: set) -> list:
    """delta系5特徴量の採用行を全取得（除外船宿フィルタ済み）"""
    placeholders = ",".join("?" * len(excluded))
    exc_clause = f"AND ship NOT IN ({placeholders})" if excluded else ""
    sql = f"""
        SELECT fish, ship, metric, factor, alpha_scale, r, updated_at
        FROM combo_wx_params
        WHERE factor IN ({','.join('?' * len(DELTA_FACTORS))})
        {exc_clause}
        ORDER BY factor, ABS(r) DESC
    """
    params = list(DELTA_FACTORS) + list(excluded)
    cur = conn.cursor()
    cur.execute(sql, params)
    return cur.fetchall()


def summarize_by_factor(rows: list) -> dict:
    """因子ごとの採用コンボ数・|r| 統計・alpha_scale統計"""
    by_factor = defaultdict(list)
    for fish, ship, metric, factor, alpha, r, upd in rows:
        if r is not None:
            by_factor[factor].append({
                "fish": fish, "ship": ship, "metric": metric,
                "alpha": alpha, "r": r, "upd": upd
            })
    result = {}
    for fac, items in by_factor.items():
        abs_r = [abs(d["r"]) for d in items]
        alpha_items = [d for d in items if d["alpha"] is not None]
        alpha_r = [abs(d["alpha"] * d["r"]) for d in alpha_items]
        combos = {(d["fish"], d["ship"]) for d in items}
        # cnt_avg 専用 TOP10（セクション3の表示用）
        cnt_avg_items = [d for d in items if d["metric"] == "cnt_avg"]
        top10_cnt_avg = sorted(cnt_avg_items, key=lambda x: abs(x["r"]), reverse=True)[:10]
        result[fac] = {
            "n_rows": len(items),
            "n_combos": len(combos),
            "abs_r_median": statistics.median(abs_r) if abs_r else None,
            "abs_r_q25": sorted(abs_r)[int(len(abs_r)*0.25)] if len(abs_r) >= 4 else None,
            "abs_r_q75": sorted(abs_r)[int(len(abs_r)*0.75)] if len(abs_r) >= 4 else None,
            "abs_r_max": max(abs_r) if abs_r else None,
            "n_alpha_nonnull": len(alpha_items),
            "alpha_r_median": statistics.median(alpha_r) if alpha_r else None,
            "top10_cnt_avg": top10_cnt_avg,
        }
    return result


def check_combo_adoption(rows: list, combo_list: list, label: str) -> list:
    """指定コンボリストに対して、各 delta因子の採用有無を返す"""
    adopted = defaultdict(set)  # (fish,ship) -> set of factors
    for fish, ship, metric, factor, alpha, r, upd in rows:
        if metric == "cnt_avg":
            adopted[(fish, ship)].add(factor)

    results = []
    for fish, ship in combo_list:
        facs = adopted.get((fish, ship), set())
        for fac in DELTA_FACTORS:
            results.append({
                "group": label,
                "fish": fish, "ship": ship,
                "factor": fac,
                "adopted": "採用" if fac in facs else "未採用",
            })
    return results


def check_aji_konaya(conn) -> dict:
    """アジ×こなや丸 の delta因子採用状況と updated_at を確認"""
    cur = conn.cursor()
    cur.execute("""
        SELECT factor, r, alpha_scale, updated_at
        FROM combo_wx_params
        WHERE fish='アジ' AND ship='こなや丸'
          AND factor IN ({})
        ORDER BY factor
    """.format(",".join("?" * len(DELTA_FACTORS))), DELTA_FACTORS)
    rows = cur.fetchall()
    return {r[0]: {"r": r[1], "alpha": r[2], "updated_at": r[3]} for r in rows}


def count_total_combos(conn, excluded: set) -> int:
    """除外後の全コンボ数（fish×ship ユニーク、metric=cnt_avg）"""
    placeholders = ",".join("?" * len(excluded))
    exc_clause = f"AND ship NOT IN ({placeholders})" if excluded else ""
    sql = f"""
        SELECT COUNT(DISTINCT fish||'|'||ship)
        FROM combo_wx_params
        WHERE metric='cnt_avg' {exc_clause}
    """
    cur = conn.cursor()
    cur.execute(sql, list(excluded))
    return cur.fetchone()[0]


def main():
    print(f"DB: {DB_PATH}")
    conn = sqlite3.connect(DB_PATH)
    excluded = load_excluded_ships(SHIPS_JSON)
    print(f"除外船宿: {len(excluded)}件: {sorted(excluded)}")

    # 1. PRAGMA確認
    cols = pragma_table_info(conn, "combo_wx_params")
    col_names = [c[1] for c in cols]
    print(f"\ncombo_wx_params 列: {col_names}")
    assert "r" in col_names, "r列が存在しない"
    assert "alpha_scale" in col_names, "alpha_scale列が存在しない"
    # H列が存在しないことを明示的に確認
    has_h_col = "horizon" in col_names or "h" in col_names
    print(f"H/horizon列の存在: {'あり（要確認）' if has_h_col else 'なし（確認済み）'}")

    # 2. 全採用行の取得
    rows = fetch_delta_adoptions(conn, excluded)
    print(f"\ndelta系5因子の採用行数: {len(rows)}件")
    print(f"先頭3: {rows[:3]}")

    # alpha_scale NULL率を確認
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*), SUM(CASE WHEN alpha_scale IS NULL THEN 1 ELSE 0 END) FROM combo_wx_params")
    total, null_cnt = cur.fetchone()
    print(f"\nalpha_scale NULL率: {null_cnt}/{total} = {null_cnt/total*100:.1f}%")

    # 3. 因子別統計
    summary = summarize_by_factor(rows)

    # 4. 全コンボ数（採用率の分母）
    total_combos = count_total_combos(conn, excluded)
    print(f"\n全コンボ数（metric=cnt_avg, 除外後）: {total_combos}件")

    # 5. Phase1 コンボ採用チェック
    bl2_checks   = check_combo_adoption(rows, PHASE1_BL2_FAIL_H0, "BL-2負け(H0)")
    wmape_checks = check_combo_adoption(rows, PHASE1_HIGH_WMAPE,  "高wMAPE")
    fast_checks  = check_combo_adoption(rows, PHASE1_FAST_MISUSE, "FAST誤適用候補")

    # 6. アジ×こなや丸の確認
    aji_konaya = check_aji_konaya(conn)

    conn.close()

    # ── レポート生成 ──────────────────────────────────────────────────────────
    lines = []
    lines.append("# Phase 2: delta系特徴量（転換点検知）有効性診断レポート")
    lines.append("")
    lines.append(f"生成日: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"DB: {DB_PATH}")
    lines.append("")
    lines.append("> **注記**: 読み取り専用診断。強制適用シミュレーション禁止（p-hacking回避）。")
    lines.append("> `|r|` 単体評価（alpha_scale NULL率確認済み）。")
    lines.append("")

    # セクション0: PRAGMA確認結果
    lines.append("## 0. 事前確認")
    lines.append("")
    lines.append("### combo_wx_params 列構成")
    lines.append("")
    lines.append(f"列名: `{', '.join(col_names)}`")
    lines.append("")
    lines.append(f"- H/horizon 列: {'あり（要確認）' if has_h_col else '**なし（確認済み）** — 粒度は fish×ship×metric×factor'}")
    lines.append(f"- alpha_scale NULL率: **{null_cnt}/{total} = {null_cnt/total*100:.1f}%** → 寄与度評価は |r| 単体を使用")
    lines.append("")

    # セクション1: FAST/SLOW分類
    lines.append("## 1. 5特徴量の FAST/SLOW 分類（combo_deep_dive.py 確認結果）")
    lines.append("")
    lines.append("| 特徴量 | 分類 | 問題の有無 |")
    lines.append("|--------|------|------------|")
    for fac in DELTA_FACTORS:
        cls = FACTOR_CLASSIFICATION[fac]
        if "FAST" in cls:
            issue = "⚠️ H>7 で自動無効化（FAST_MAX_H=7）— 設計通り"
        elif "CALENDAR" in cls:
            issue = "全Hで有効（カレンダー確定値）"
        else:
            issue = "全Hで有効（SLOW）"
        lines.append(f"| `{fac}` | {cls} | {issue} |")
    lines.append("")
    lines.append("**FAST_FACTORS登録漏れ**: なし。`pressure_delta_48h` は正しく FAST_FACTORS に登録済み。H>7 では自動無効化される。")
    lines.append("")

    # セクション2: 採用カバー率
    lines.append("## 2. 採用カバー率")
    lines.append("")
    lines.append(f"全コンボ数（metric=cnt_avg, 除外後）: **{total_combos}件**")
    lines.append("")
    lines.append("| 特徴量 | 採用コンボ数 | カバー率 | 採用行数 | |r| 中央値 | |r| Q25 | |r| Q75 | |r| 最大 |")
    lines.append("|--------|------------|---------|---------|-----------|--------|--------|--------|")
    for fac in DELTA_FACTORS:
        if fac not in summary:
            lines.append(f"| `{fac}` | 0 | 0.0% | 0 | — | — | — | — |")
            continue
        s = summary[fac]
        cover = s['n_combos'] / total_combos * 100 if total_combos > 0 else 0
        med   = f"{s['abs_r_median']:.3f}" if s['abs_r_median'] is not None else "—"
        q25   = f"{s['abs_r_q25']:.3f}" if s['abs_r_q25'] is not None else "—"
        q75   = f"{s['abs_r_q75']:.3f}" if s['abs_r_q75'] is not None else "—"
        mx    = f"{s['abs_r_max']:.3f}" if s['abs_r_max'] is not None else "—"
        lines.append(f"| `{fac}` | {s['n_combos']} | {cover:.1f}% | {s['n_rows']} | {med} | {q25} | {q75} | {mx} |")
    lines.append("")

    # セクション3: |r| 分布 TOP10（因子ごと）
    lines.append("## 3. 採用コンボ |r| 分布 — TOP10（metric=cnt_avg）")
    lines.append("")
    for fac in DELTA_FACTORS:
        lines.append(f"### {fac}")
        lines.append("")
        if fac not in summary or summary[fac]["n_rows"] == 0:
            lines.append("採用なし")
            lines.append("")
            continue
        s = summary[fac]
        cnt_avg_top = s["top10_cnt_avg"]
        lines.append("| fish | ship | |r| | r(符号) | alpha_scale | updated_at |")
        lines.append("|------|------|----|---------|-------------|-----------|")
        for d in cnt_avg_top[:10]:
            abs_r = abs(d["r"])
            sign  = f"{d['r']:+.3f}"
            alpha = f"{d['alpha']:.3f}" if d["alpha"] is not None else "NULL"
            upd   = d["upd"] or "—"
            lines.append(f"| {d['fish']} | {d['ship']} | {abs_r:.3f} | {sign} | {alpha} | {upd} |")
        lines.append("")
        # alpha_scale 非NULL 行での |alpha×r|
        if s["n_alpha_nonnull"] > 0:
            lines.append(f"alpha_scale 非NULL行: {s['n_alpha_nonnull']}件  |alpha×r| 中央値: {s['alpha_r_median']:.3f}" if s["alpha_r_median"] else "")
            lines.append("")

    # セクション4: Phase1 高wMAPE・BL2負けコンボでの採用有無
    lines.append("## 4. Phase 1 特定コンボでの採用有無（metric=cnt_avg）")
    lines.append("")

    def render_combo_check(check_list, group_label, description):
        lines.append(f"### {group_label}")
        lines.append(f"*{description}*")
        lines.append("")
        lines.append("| fish | ship | sst_delta_3d | pressure_delta_48h | kuroshio_sla_delta_1m | sss_delta_7d | day_of_decade |")
        lines.append("|------|------|:----------:|:----------------:|:-----------------:|:----------:|:-----------:|")
        # group by (fish, ship)
        combo_rows = defaultdict(dict)
        for item in check_list:
            combo_rows[(item["fish"], item["ship"])][item["factor"]] = item["adopted"]
        for fish, ship in [(c["fish"], c["ship"]) for c in check_list]:
            key = (fish, ship)
            if key not in combo_rows:
                continue
            fmap = combo_rows.pop(key, {})
            cells = [fmap.get(f, "N/A") for f in DELTA_FACTORS]
            mark = lambda v: "O" if v == "採用" else ("x" if v == "未採用" else "—")
            row = " | ".join(mark(c) for c in cells)
            lines.append(f"| {fish} | {ship} | {row} |")
        lines.append("")
        lines.append("凡例: O=採用, x=未採用, —=N/A")
        lines.append("")

    render_combo_check(bl2_checks,   "4-1. H=0 BL-2負けコンボ（8件）",
                       "H=0で気象補正がベースライン以下のコンボ。delta特徴量が採用されているか確認。")
    render_combo_check(wmape_checks, "4-2. 高wMAPEコンボ（8件, >70%）",
                       "wMAPE>70%だがBL-2には勝っているコンボ。ノイズが多い釣り物かの確認。")
    render_combo_check(fast_checks,  "4-3. FAST誤適用候補（4件）",
                       "H=0勝ちかつH=7負けのコンボ。pressure_delta_48h（FAST因子）の採用有無に注目。")

    # セクション5: アジ×こなや丸の確認
    lines.append("## 5. 検証ケース: アジ×こなや丸")
    lines.append("")
    lines.append("04/24 実装時に deep_params N=4 が確認されたコンボ。delta因子の updated_at が 2026-04-24 以降かを確認。")
    lines.append("")
    if aji_konaya:
        lines.append("| factor | r | alpha_scale | updated_at | 最新か(>=04-24) |")
        lines.append("|--------|---|-------------|-----------|----------------|")
        for fac in DELTA_FACTORS:
            if fac in aji_konaya:
                d = aji_konaya[fac]
                upd = d["updated_at"] or "—"
                is_new = "YES" if (d["updated_at"] and d["updated_at"] >= "2026-04-24") else "NO (旧)"
                r_val = f"{d['r']:.3f}" if d["r"] is not None else "NULL"
                alpha = f"{d['alpha']:.3f}" if d["alpha"] is not None else "NULL"
                lines.append(f"| `{fac}` | {r_val} | {alpha} | {upd} | {is_new} |")
            else:
                lines.append(f"| `{fac}` | — | — | — | 未採用 |")
    else:
        lines.append("アジ×こなや丸 に対して delta因子の採用なし（combo_wx_params に行なし）。")
    lines.append("")

    # セクション6: 結論
    lines.append("## 6. 結論")
    lines.append("")

    # 採用カバー率集計
    adoption_summary = []
    for fac in DELTA_FACTORS:
        if fac in summary:
            cover = summary[fac]['n_combos'] / total_combos * 100 if total_combos > 0 else 0
            med   = summary[fac]['abs_r_median'] or 0
            adoption_summary.append((fac, summary[fac]['n_combos'], cover, med))
        else:
            adoption_summary.append((fac, 0, 0.0, 0.0))

    lines.append("### 採用カバー率サマリー")
    lines.append("")
    for fac, n_c, cov, med in adoption_summary:
        lines.append(f"- `{fac}`: 採用{n_c}コンボ / {total_combos}件 = **{cov:.1f}%**, |r| 中央値 = **{med:.3f}**")
    lines.append("")

    lines.append("### FAST_FACTORS登録漏れの有無")
    lines.append("")
    lines.append("- `pressure_delta_48h`: FAST_FACTORS に正しく登録済み。H>7 では FAST_MAX_H=7 により自動無効化される。登録漏れなし。")
    lines.append("- その他4件はすべて SLOW_FACTORS（または CALENDAR_FACTORS）。全H有効。設計通り。")
    lines.append("")

    lines.append("### delta特徴量が「効いている」と言える事例")
    lines.append("")
    # |r| 中央値が0.2以上で採用数が10以上のものを有効と判定
    effective = [(fac, n_c, cov, med) for fac, n_c, cov, med in adoption_summary if med >= 0.2 and n_c >= 10]
    marginal  = [(fac, n_c, cov, med) for fac, n_c, cov, med in adoption_summary if 0.1 <= med < 0.2 and n_c >= 5]
    ineffective = [(fac, n_c, cov, med) for fac, n_c, cov, med in adoption_summary
                   if not any(f == fac for f, *_ in effective) and not any(f == fac for f, *_ in marginal)]

    if effective:
        for fac, n_c, cov, med in effective:
            lines.append(f"- **`{fac}`** (採用{n_c}コンボ, |r| 中央値={med:.3f}): 転換点検知として**有効**。")
    if marginal:
        for fac, n_c, cov, med in marginal:
            lines.append(f"- **`{fac}`** (採用{n_c}コンボ, |r| 中央値={med:.3f}): **部分的に有効**（シグナル弱め）。")
    if ineffective:
        for fac, n_c, cov, med in ineffective:
            lines.append(f"- **`{fac}`** (採用{n_c}コンボ, |r| 中央値={med:.3f}): **効果限定的** または採用なし。")
    lines.append("")

    lines.append("### 後続アクション示唆")
    lines.append("")
    lines.append("- **採用カバーが低い因子**: 04/24 実装後にまだ全種再分析が実行されていない可能性あり。")
    lines.append("  Phase A' 完了後に `run_full_deepdive.py --workers 4` を再実行して updated_at を更新することが先決。")
    lines.append("- **FAST誤適用候補4件** (メバル×幸栄丸等): `pressure_delta_48h` の採用有無を確認。")
    lines.append("  H=7 での wMAPE 悪化が FAST因子由来かどうかは、採用されているコンボ限定で判断可能。")
    lines.append("- **wind_dir_change（domain推薦）**: 既存 wind_dir 列から計算可能。Phase C 完了後の追加候補。")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("*自動生成: diag_delta_factors.py (Phase 2 / C 転換点検知診断)*")

    # ファイル出力
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"\nレポート出力: {OUT_FILE}")


if __name__ == "__main__":
    main()
