"""
diag_failures.py — BL-2負け・高wMAPEコンボの根本診断（読み取り専用）

Phase 1 (D): 失敗事例の根本診断
目的: BL-2勝率 95.9% の残4.1%（約10コンボ）と高wMAPEコンボ（>70%）の
      共通要因を特定し、後続Phase（C/B/A'）の優先順位付けに使う。

注記:
  - combo_backtest に max_r 列はない。r（OOS相関係数）列を使用。
  - combo_meta に transition_risk 列はない（PRAGMA確認済み）。
  - combo_wx_params は H 列を持たない（粒度: fish×ship×metric×factor）。
  - 記述統計のみ。多重検定補正は不要（仮説生成段階）。

実行方法:
    cd analysis/V2/methods
    python diag_failures.py
"""

import os
import sys
import sqlite3
import json
import statistics
from collections import defaultdict
from datetime import datetime

# パス解決
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _paths import RESULTS_DIR, ROOT_DIR

DB_PATH = os.path.join(RESULTS_DIR, "analysis.sqlite")
SHIPS_JSON = os.path.join(ROOT_DIR, "crawl", "ships.json")
OUT_DIR = os.path.join(ROOT_DIR, "analysis", "V2", "analysis-improvement")
OUT_MD = os.path.join(OUT_DIR, "diag_failures_2026-04-26.md")

# 除外船宿（ships.json の exclude:true / boat_only:true）
EXCLUDED_SHIPS = {
    "岩崎レンタルボート(岩崎つり具店)",
    "岩崎レンタルボート",
    "海上つり堀まるや",
    "ふじや釣舟店",
    "青木丸",
    "第三幸栄丸",
    "山本釣船店",
    "村松釣具店",
}

WMAPE_HIGH_THR = 70.0  # 高wMAPE閾値（%）
HORIZONS = [0, 7, 14]  # 評価水準


def _load_excluded_ships(ships_json: str) -> set:
    """ships.json から除外船宿名を動的に取得してセットに追加"""
    excluded = set(EXCLUDED_SHIPS)
    try:
        with open(ships_json, encoding="utf-8") as f:
            ships = json.load(f)
        for s in ships:
            if s.get("exclude") or s.get("boat_only"):
                name = s.get("name") or s.get("ship_name", "")
                if name:
                    excluded.add(name)
    except Exception as e:
        print(f"[warn] ships.json読み込みエラー: {e}")
    return excluded


def _format_pct(v):
    if v is None:
        return "N/A"
    return f"{v:.1f}%"


def _format_r(v):
    if v is None:
        return "N/A"
    return f"{v:+.3f}"


def run_diagnosis():
    excluded = _load_excluded_ships(SHIPS_JSON)

    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    cur = db.cursor()

    # ── 1. 事前確認 ────────────────────────────────────────────────
    print("=== 事前確認 ===")

    bt_cols = [r[1] for r in cur.execute("PRAGMA table_info(combo_backtest)")]
    meta_cols = [r[1] for r in cur.execute("PRAGMA table_info(combo_meta)")]
    wx_cols = [r[1] for r in cur.execute("PRAGMA table_info(combo_wx_params)")]
    print(f"combo_backtest columns: {bt_cols}")
    print(f"combo_meta columns: {meta_cols}")
    print(f"combo_wx_params columns: {wx_cols}")
    print(f"transition_risk in meta: {'transition_risk' in meta_cols}")
    print(f"max_r in backtest: {'max_r' in bt_cols}  -> r列を使用")

    # 行数確認
    for tbl in ["combo_backtest", "combo_meta", "combo_wx_params"]:
        n = cur.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
        print(f"{tbl}: {n}行")

    # 先頭3サンプル目視
    print("\ncombo_backtest 先頭3 (metric=cnt_avg, H=0):")
    rows = cur.execute(
        'SELECT fish, ship, horizon, wmape, bl2_wmape, n, r '
        'FROM combo_backtest WHERE metric="cnt_avg" AND horizon=0 LIMIT 3'
    ).fetchall()
    for r in rows:
        print(f"  fish={r['fish']}, ship={r['ship']}, wmape={r['wmape']:.1f}%, "
              f"bl2={r['bl2_wmape']:.1f}%, n={r['n']}, r={r['r']:.3f}")

    # ── 2. 除外フィルタ条件文の生成 ────────────────────────────────
    # IN句は可変長なのでプレースホルダを使う
    excl_placeholders = ",".join(["?" for _ in excluded])
    excl_params = list(excluded)

    # ── 3. BL-2 負けコンボ抽出（H=0/7/14） ─────────────────────────
    bl2_loss = {}  # horizon -> list of dicts
    for h in HORIZONS:
        rows = cur.execute(
            f"""
            SELECT b.fish, b.ship, b.horizon, b.wmape, b.bl2_wmape,
                   b.n, b.r,
                   (b.wmape - b.bl2_wmape) AS gap,
                   m.n_records, m.cv_pct, m.seasonality_pct, m.avg_cnt
            FROM combo_backtest b
            LEFT JOIN combo_meta m ON b.fish=m.fish AND b.ship=m.ship
            WHERE b.metric='cnt_avg'
              AND b.horizon=?
              AND b.wmape > b.bl2_wmape
              AND b.wmape IS NOT NULL
              AND b.bl2_wmape IS NOT NULL
              AND b.ship NOT IN ({excl_placeholders})
            ORDER BY gap DESC
            """,
            [h] + excl_params,
        ).fetchall()
        bl2_loss[h] = [dict(r) for r in rows]
        print(f"\nH={h} BL2負け: {len(rows)}件")
        for i, r in enumerate(rows[:5], 1):
            print(f"  {i}. {r['fish']}×{r['ship']}  "
                  f"wmape={r['wmape']:.1f}% bl2={r['bl2_wmape']:.1f}% "
                  f"gap={r['gap']:.1f}pt n={r['n']} r={r['r']:+.3f}")

    # ── 4. 高wMAPEコンボ抽出（H=0, >70%） ──────────────────────────
    high_wmape = cur.execute(
        f"""
        SELECT b.fish, b.ship, b.wmape, b.bl2_wmape, b.n, b.r,
               m.n_records, m.cv_pct, m.avg_cnt
        FROM combo_backtest b
        LEFT JOIN combo_meta m ON b.fish=m.fish AND b.ship=m.ship
        WHERE b.metric='cnt_avg'
          AND b.horizon=0
          AND b.wmape > ?
          AND b.wmape IS NOT NULL
          AND b.ship NOT IN ({excl_placeholders})
        ORDER BY b.wmape DESC
        """,
        [WMAPE_HIGH_THR] + excl_params,
    ).fetchall()
    high_wmape = [dict(r) for r in high_wmape]
    print(f"\n高wMAPEコンボ (H=0, >{WMAPE_HIGH_THR}%): {len(high_wmape)}件")
    for r in high_wmape:
        print(f"  {r['fish']}×{r['ship']}  wmape={r['wmape']:.1f}% "
              f"bl2={r['bl2_wmape']:.1f}% n={r['n']} r={r['r']:+.3f}")

    # ── 5. FAST変数誤適用候補: H=0で勝つがH=7で負け ─────────────────
    fast_candidates = cur.execute(
        f"""
        SELECT b0.fish, b0.ship,
               b0.wmape AS wmape_h0, b0.bl2_wmape AS bl2_h0,
               b7.wmape AS wmape_h7, b7.bl2_wmape AS bl2_h7,
               b0.n,
               (b7.wmape - b7.bl2_wmape) AS gap_h7
        FROM combo_backtest b0
        JOIN combo_backtest b7
          ON b0.fish=b7.fish AND b0.ship=b7.ship AND b0.metric=b7.metric
        WHERE b0.metric='cnt_avg'
          AND b0.horizon=0 AND b7.horizon=7
          AND b0.wmape <= b0.bl2_wmape
          AND b7.wmape > b7.bl2_wmape
          AND b0.wmape IS NOT NULL AND b7.wmape IS NOT NULL
          AND b0.ship NOT IN ({excl_placeholders})
        ORDER BY gap_h7 DESC
        """,
        excl_params,
    ).fetchall()
    fast_candidates = [dict(r) for r in fast_candidates]
    print(f"\nFAST誤適用候補 (H=0勝ちかつH=7負け): {len(fast_candidates)}件")
    for r in fast_candidates:
        print(f"  {r['fish']}×{r['ship']}  "
              f"H0: wmape={r['wmape_h0']:.1f}%(<bl2={r['bl2_h0']:.1f}%)  "
              f"H7: wmape={r['wmape_h7']:.1f}%(>bl2={r['bl2_h7']:.1f}%)")

    # ── 6. 採用因子数クロス集計 ──────────────────────────────────────
    # combo_wx_params から fish×ship×metric=cnt_avg の因子数を取得
    factor_count_map = {}  # (fish, ship) -> int
    rows = cur.execute(
        f"""
        SELECT fish, ship, COUNT(*) - 1 AS n_factors
        FROM combo_wx_params
        WHERE metric='cnt_avg'
          AND factor != '_meta'
          AND ship NOT IN ({excl_placeholders})
        GROUP BY fish, ship
        """,
        excl_params,
    ).fetchall()
    for r in rows:
        factor_count_map[(r["fish"], r["ship"])] = r["n_factors"]

    # ── 7. クロス集計: BL2負け vs データ量 / 因子数 / r ─────────────
    def _n_band(n):
        if n is None:
            return "不明"
        if n < 60:
            return "30-60"
        elif n < 150:
            return "60-150"
        else:
            return ">150"

    def _fac_band(nf):
        if nf is None:
            return "不明"
        if nf == 0:
            return "0"
        elif nf <= 3:
            return "1-3"
        elif nf <= 7:
            return "4-7"
        else:
            return ">7"

    # H=0 BL2負けについてクロス集計
    bl2_h0 = bl2_loss[0]
    cross_n_band = defaultdict(int)
    cross_fac_band = defaultdict(int)
    r_vals = []
    for row in bl2_h0:
        cross_n_band[_n_band(row["n"])] += 1
        nf = factor_count_map.get((row["fish"], row["ship"]))
        cross_fac_band[_fac_band(nf)] += 1
        if row["r"] is not None:
            r_vals.append(row["r"])

    # 全H=0コンボとの比較用
    all_h0 = cur.execute(
        f"""
        SELECT b.fish, b.ship, b.n, b.r, b.wmape
        FROM combo_backtest b
        WHERE b.metric='cnt_avg' AND b.horizon=0
          AND b.wmape IS NOT NULL
          AND b.ship NOT IN ({excl_placeholders})
        """,
        excl_params,
    ).fetchall()
    all_n_band = defaultdict(int)
    all_r_vals = []
    for row in all_h0:
        all_n_band[_n_band(row["n"])] += 1
        if row["r"] is not None:
            all_r_vals.append(row["r"])

    # ── 8. H=7/14 との一致確認 ──────────────────────────────────────
    # 3水準全部で負けているコンボ
    loss_sets = {h: {(r["fish"], r["ship"]) for r in bl2_loss[h]} for h in HORIZONS}
    loss_all3 = loss_sets[0] & loss_sets[7] & loss_sets[14]
    loss_any = loss_sets[0] | loss_sets[7] | loss_sets[14]
    print(f"\nH=0/7/14全部で負け: {len(loss_all3)}件 {sorted(loss_all3)}")
    print(f"H=0/7/14いずれかで負け: {len(loss_any)}件")

    db.close()

    # ── 9. Markdown レポート出力 ──────────────────────────────────────
    os.makedirs(OUT_DIR, exist_ok=True)

    lines = []
    lines.append(f"# Phase 1 失敗事例診断レポート")
    lines.append(f"")
    lines.append(f"生成日: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"DB: {DB_PATH}")
    lines.append(f"")
    lines.append(f"> **注記**: 記述統計のみ（仮説生成段階）。多重検定補正は適用しない。")
    lines.append(f"> `max_r` 列は combo_backtest に存在しないため `r`（OOS相関係数）を使用。")
    lines.append(f"> `transition_risk` 列は combo_meta に存在しないためスキップ。")
    lines.append(f"")

    # ── セクション1: 概要 ──────────────────────────────────────────
    lines.append(f"## 1. 概要")
    lines.append(f"")
    lines.append(f"| 指標 | 値 |")
    lines.append(f"|------|-----|")
    lines.append(f"| H=0 全コンボ数 | {len(all_h0)}件 |")
    lines.append(f"| H=0 BL-2負け | {len(bl2_loss[0])}件 ({len(bl2_loss[0])/len(all_h0)*100:.1f}%) |")
    lines.append(f"| H=7 BL-2負け | {len(bl2_loss[7])}件 |")
    lines.append(f"| H=14 BL-2負け | {len(bl2_loss[14])}件 |")
    lines.append(f"| 高wMAPE (H=0, >70%) | {len(high_wmape)}件 |")
    lines.append(f"| H=0/7/14 全水準で負け | {len(loss_all3)}件 |")
    lines.append(f"| FAST誤適用候補 (H=0勝ちかつH=7負け) | {len(fast_candidates)}件 |")
    lines.append(f"")

    # ── セクション2: BL-2負けコンボ一覧 ──────────────────────────────
    lines.append(f"## 2. BL-2負けコンボ (H別)")
    lines.append(f"")

    for h in HORIZONS:
        rows = bl2_loss[h]
        lines.append(f"### H={h} BL-2負け ({len(rows)}件)")
        lines.append(f"")
        if rows:
            lines.append(f"| # | fish | ship | wMAPE | BL2 | gap | n | r(OOS) | n帯 | 因子数 | 推定原因 |")
            lines.append(f"|---|------|------|-------|-----|-----|---|--------|-----|--------|----------|")
            for i, row in enumerate(rows, 1):
                nf = factor_count_map.get((row["fish"], row["ship"]))
                n_b = _n_band(row["n"])
                f_b = _fac_band(nf)
                # 推定原因の簡易判定
                reasons = []
                if row["n"] is not None and row["n"] < 60:
                    reasons.append("少データ")
                if row["r"] is not None and row["r"] < 0.15:
                    reasons.append("低相関(r<0.15)")
                if row["r"] is not None and row["r"] < 0:
                    reasons.append("逆相関")
                gap = row["wmape"] - row["bl2_wmape"]
                if gap > 15:
                    reasons.append("大幅負け")
                if (row["fish"], row["ship"]) in {(r["fish"], r["ship"]) for r in fast_candidates}:
                    reasons.append("FAST誤適用候補")
                reason_str = "/".join(reasons) if reasons else "—"
                lines.append(
                    f"| {i} | {row['fish']} | {row['ship']} | "
                    f"{_format_pct(row['wmape'])} | {_format_pct(row['bl2_wmape'])} | "
                    f"+{gap:.1f}pt | {row['n']} | {_format_r(row['r'])} | "
                    f"{n_b} | {nf if nf is not None else '?'} | {reason_str} |"
                )
            lines.append(f"")
        else:
            lines.append(f"（負けコンボなし）")
            lines.append(f"")

    # ── セクション3: 高wMAPEクラスタ ──────────────────────────────────
    lines.append(f"## 3. 高wMAPEクラスタ (H=0, wMAPE > {WMAPE_HIGH_THR}%)")
    lines.append(f"")
    if high_wmape:
        lines.append(f"| fish | ship | wMAPE | BL2 | n | r(OOS) | BL2勝ち？ | 因子数 |")
        lines.append(f"|------|------|-------|-----|---|--------|-----------|--------|")
        for row in high_wmape:
            beats_bl2 = "勝ち" if row["wmape"] <= row["bl2_wmape"] else "負け"
            nf = factor_count_map.get((row["fish"], row["ship"]))
            lines.append(
                f"| {row['fish']} | {row['ship']} | "
                f"{_format_pct(row['wmape'])} | {_format_pct(row['bl2_wmape'])} | "
                f"{row['n']} | {_format_r(row['r'])} | {beats_bl2} | "
                f"{nf if nf is not None else '?'} |"
            )
        lines.append(f"")

        # 典型例コメント（上位3件）
        lines.append(f"### 高wMAPEクラスタの典型例")
        lines.append(f"")
        for i, row in enumerate(high_wmape[:3], 1):
            nf = factor_count_map.get((row["fish"], row["ship"]))
            notes = []
            if row["r"] is not None and row["r"] < 0.1:
                notes.append("気象特徴量の相関が極めて弱い（r<0.1）→ 釣果が気象ではなく他要因支配")
            if row["n"] is not None and row["n"] < 60:
                notes.append(f"データ量不足（n={row['n']}）→ ベースラインの安定化が先決")
            if row["wmape"] is not None and row["bl2_wmape"] is not None and row["wmape"] > row["bl2_wmape"]:
                notes.append("BL-2にも負けており「何もしない予測」以下")
            lines.append(f"**{i}. {row['fish']}×{row['ship']}**")
            lines.append(f"- wMAPE={_format_pct(row['wmape'])}, BL2={_format_pct(row['bl2_wmape'])}, "
                         f"n={row['n']}, r={_format_r(row['r'])}, 因子数={nf if nf is not None else '?'}")
            for note in notes:
                lines.append(f"- {note}")
            lines.append(f"")
    else:
        lines.append(f"（高wMAPEコンボなし）")
        lines.append(f"")

    # ── セクション4: FAST変数誤適用候補 ──────────────────────────────
    lines.append(f"## 4. FAST変数誤適用候補（H=0勝ちかつH=7負け）")
    lines.append(f"")
    lines.append(f"> H=0（当日予測）では BL-2に勝つが H=7（7日前予測）では負けるコンボ。")
    lines.append(f"> 波高・風速・潮流等の FAST変数が H>7 でも効いてしまっている可能性がある。")
    lines.append(f"> ただし H=7の wMAPE上昇が 3pt以内のものはノイズの可能性あり（仮説段階）。")
    lines.append(f"")
    if fast_candidates:
        lines.append(f"| fish | ship | H0 wMAPE | H0 BL2 | H7 wMAPE | H7 BL2 | H7 gap | n |")
        lines.append(f"|------|------|----------|--------|----------|--------|--------|---|")
        for row in fast_candidates:
            lines.append(
                f"| {row['fish']} | {row['ship']} | "
                f"{_format_pct(row['wmape_h0'])} | {_format_pct(row['bl2_h0'])} | "
                f"{_format_pct(row['wmape_h7'])} | {_format_pct(row['bl2_h7'])} | "
                f"+{row['gap_h7']:.1f}pt | {row['n']} |"
            )
        lines.append(f"")
    else:
        lines.append(f"（候補なし）")
        lines.append(f"")

    # ── セクション5: クロス集計（BL2負け vs データ量 / 因子数 / r分布） ──
    lines.append(f"## 5. クロス集計（H=0 BL-2負けコンボ）")
    lines.append(f"")
    lines.append(f"> 記述統計のみ。比較対象の分布と並べて提示する。")
    lines.append(f"")

    lines.append(f"### 5-1. データ量帯別分布")
    lines.append(f"")
    lines.append(f"| n帯 | BL2負け件数 | 全コンボ件数 | BL2負け率 |")
    lines.append(f"|-----|------------|------------|----------|")
    for band in ["30-60", "60-150", ">150", "不明"]:
        n_loss = cross_n_band.get(band, 0)
        n_all = all_n_band.get(band, 0)
        rate = f"{n_loss/n_all*100:.0f}%" if n_all > 0 else "—"
        lines.append(f"| {band} | {n_loss} | {n_all} | {rate} |")
    lines.append(f"")

    lines.append(f"### 5-2. 採用因子数帯別分布（H=0 BL2負け）")
    lines.append(f"")
    lines.append(f"| 因子数帯 | 件数 |")
    lines.append(f"|---------|------|")
    for band in ["0", "1-3", "4-7", ">7", "不明"]:
        lines.append(f"| {band} | {cross_fac_band.get(band, 0)} |")
    lines.append(f"")

    lines.append(f"### 5-3. r（OOS相関係数）の分布")
    lines.append(f"")
    if r_vals:
        r_med = statistics.median(r_vals)
        r_min = min(r_vals)
        r_max = max(r_vals)
        lines.append(f"- BL2負けコンボ: n={len(r_vals)}, 中央値={r_med:+.3f}, 最小={r_min:+.3f}, 最大={r_max:+.3f}")
    if all_r_vals:
        r_med_all = statistics.median(all_r_vals)
        lines.append(f"- 全H=0コンボ: n={len(all_r_vals)}, 中央値={r_med_all:+.3f}")
    lines.append(f"")
    lines.append(f"BL2負けコンボ の r 一覧（H=0）:")
    for row in bl2_h0:
        lines.append(f"  - {row['fish']}×{row['ship']}: r={_format_r(row['r'])}")
    lines.append(f"")

    # ── セクション6: H=0/7/14 全水準で負けるコンボ ──────────────────
    lines.append(f"## 6. H=0/7/14 全水準で BL-2負けのコンボ（{len(loss_all3)}件）")
    lines.append(f"")
    if loss_all3:
        lines.append(f"| fish | ship | H=0 gap | H=7 gap | H=14 gap |")
        lines.append(f"|------|------|---------|---------|----------|")
        # loss_all3 に含まれるコンボの各H情報をまとめる
        for (fish, ship) in sorted(loss_all3):
            def _gap(h):
                for row in bl2_loss[h]:
                    if row["fish"] == fish and row["ship"] == ship:
                        return row["wmape"] - row["bl2_wmape"]
                return None
            g0 = _gap(0)
            g7 = _gap(7)
            g14 = _gap(14)
            lines.append(
                f"| {fish} | {ship} | "
                f"+{g0:.1f}pt | +{g7:.1f}pt | +{g14:.1f}pt |"
            )
        lines.append(f"")
    else:
        lines.append(f"（なし）")
        lines.append(f"")

    # ── セクション7: Phase A'/B/C の優先度示唆 ──────────────────────
    lines.append(f"## 7. 後続 Phase の優先度示唆")
    lines.append(f"")

    # 集計データから傾向判断
    n_small_data = cross_n_band.get("30-60", 0)
    n_low_r = sum(1 for r in bl2_h0 if r["r"] is not None and r["r"] < 0.15)
    n_fast_cand = len(fast_candidates)

    lines.append(f"| Phase | 優先度 | 根拠 |")
    lines.append(f"|-------|--------|------|")

    # FAST変数誤適用候補が多いとPhase C（転換点検知）との関連も深い
    fast_priority = "高" if n_fast_cand >= 2 else "中"
    lines.append(
        f"| C（転換点検知 delta特徴量） | {fast_priority} | "
        f"FAST誤適用候補が{n_fast_cand}件存在。H=7でのパフォーマンス低下が確認された。"
        f"delta系特徴量の採用状況をPhase 2で確認する価値がある |"
    )

    b_priority = "中"
    lines.append(
        f"| B（cnt_max/cnt_min精度改善） | {b_priority} | "
        f"combo_range_backtest に既存の promise_break_rate / bowzu_rate あり。"
        f"predict_count.py の優先チェーン統合確認のみ残っている |"
    )

    ap_priority = "高" if n_small_data >= 2 else "中"
    lines.append(
        f"| A'（林遊船 time_slot補完） | {ap_priority} | "
        f"データ量不足コンボが{n_small_data}件（n=30-60帯）。"
        f"time_slot補完でサワラ×林遊船等のデータ品質向上が期待できる。"
        f"他Phaseとは独立して並行実施可能 |"
    )
    lines.append(f"")

    lines.append(f"### コンボ別の推奨対処")
    lines.append(f"")

    # H=0/7/14全部で負けるコンボへの具体的提案
    if loss_all3:
        lines.append(f"**全水準で負けるコンボ（{len(loss_all3)}件）**: 気象補正が逆効果の可能性。")
        lines.append(f"combo_wx_params の use_fallback=1 設定、または因子数ゼロへのリセットを検討。")
        lines.append(f"")

    if fast_candidates:
        lines.append(f"**FAST誤適用候補（{len(fast_candidates)}件）**:")
        for row in fast_candidates:
            lines.append(f"- {row['fish']}×{row['ship']}: H7での gap={row['gap_h7']:.1f}pt。"
                         f"FAST_FACTORS の per-combo FAST_MAX_H を 7 → 3 等に引き下げて再実行を検討。")
        lines.append(f"")

    # 高wMAPEかつBL2負けコンボ（最優先改善対象）
    worst = [r for r in high_wmape if r["wmape"] > r["bl2_wmape"]]
    if worst:
        lines.append(f"**高wMAPE かつ BL2負け（{len(worst)}件）**: 最優先改善対象。")
        for row in worst:
            lines.append(f"- {row['fish']}×{row['ship']}: wMAPE={_format_pct(row['wmape'])}, "
                         f"r={_format_r(row['r'])}")
        lines.append(f"")

    lines.append(f"---")
    lines.append(f"")
    lines.append(f"*自動生成: diag_failures.py (Phase 1 / D 失敗事例診断)*")
    lines.append(f"")

    md_content = "\n".join(lines)
    with open(OUT_MD, "w", encoding="utf-8") as f:
        f.write(md_content)
    print(f"\nレポート出力: {OUT_MD}")
    return {
        "bl2_loss_h0": len(bl2_loss[0]),
        "bl2_loss_h7": len(bl2_loss[7]),
        "bl2_loss_h14": len(bl2_loss[14]),
        "high_wmape": len(high_wmape),
        "loss_all3": len(loss_all3),
        "fast_candidates": len(fast_candidates),
        "max_gap_h0": bl2_loss[0][0]["wmape"] - bl2_loss[0][0]["bl2_wmape"] if bl2_loss[0] else 0,
    }


if __name__ == "__main__":
    result = run_diagnosis()
    print("\n=== 完了サマリー ===")
    for k, v in result.items():
        print(f"  {k}: {v}")
