#!/usr/bin/env python3
"""
build_open_tier.py — T47a: 公開ティア蒸留（analysis.sqlite → normalize/open_tier.json）

「サイトをオープンできるか」を「どのコンボをオープンするか」に変換する選別基盤。
analysis.sqlite は gitignore（ローカル限定）のため、build_fish_area_analysis.py と
同じパターンでコミット可能な軽量 JSON に蒸留し、D層（predict_daily.py）/将来のE層が読む。

ティア判定（90_決定ログ 2026/07/17 T45・正直値ベース）:
  none : タイ五目（五目は魚種構成が便ごとに変わり単一数量予測の対象として構造的に不適）
  star : KAIYU_FISH かつ kaiyu_promoted=0（★チャンス評価のみ・匹数レンジは出さない）
  A    : cnt_bz（ボウズ込み・本番経路）で promise_break<=0.10 かつ n>=50 かつ
         use_fallback=0（＝実測されたモデルがそのまま本番配信されるコンボのみ）
  none : 上記以外（レンジ非公開。★・実績表示は E層の裁量）

実行（ローカルのみ・analysis.sqlite 必須）:
  python crawl/build_open_tier.py
"""

import json
import os
import sqlite3
import sys
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DB = os.path.join(ROOT, "analysis", "V2", "results", "analysis.sqlite")
OUT_JSON = os.path.join(ROOT, "normalize", "open_tier.json")

# 確定した設計方針（CLAUDE.md / combo_deep_dive.py KAIYU_FISH と同一。変更時は両方更新）
KAIYU_FISH = {"シイラ", "カツオ", "キハダマグロ", "ブリ", "ワラサ", "イナダ",
              "サワラ", "カンパチ", "ムギイカ"}
EXCLUDED_FISH = {"タイ五目"}

PB_THR = 0.10   # promise_break 上限（cnt_bz・ボウズ込み正直値）
N_THR = 50      # バックテスト評価行数の下限


def main():
    if not os.path.exists(SRC_DB):
        print(f"ERROR: {SRC_DB} がありません。analysis.sqlite のあるローカルで実行してください。")
        sys.exit(1)
    conn = sqlite3.connect(f"file:{SRC_DB}?mode=ro", uri=True)

    # combo_meta 全コンボ + 判定材料を JOIN
    rows = conn.execute("""
        SELECT m.fish, m.ship, m.n_records,
               (SELECT use_fallback FROM combo_wx_params w
                 WHERE w.fish=m.fish AND w.ship=m.ship
                   AND w.metric='cnt_avg' AND w.factor='_meta') AS use_fallback,
               (SELECT kaiyu_promoted FROM combo_wx_params w
                 WHERE w.fish=m.fish AND w.ship=m.ship
                   AND w.metric='cnt_avg' AND w.factor='_meta') AS kaiyu_promoted,
               rb.promise_break_rate, rb.n, rb.coverage, rb.winkler, rb.updated_at,
               bt.wmape, bt.bl2_wmape
        FROM combo_meta m
        LEFT JOIN combo_range_backtest rb
               ON rb.fish=m.fish AND rb.ship=m.ship AND rb.metric='cnt_bz' AND rb.horizon=0
        LEFT JOIN combo_backtest bt
               ON bt.fish=m.fish AND bt.ship=m.ship AND bt.metric='cnt_avg' AND bt.horizon=0
    """).fetchall()

    # 週次ホライズン（H=14/21/28）の cnt_bz 成績（週次ページ表示ゲート用・domain指摘#1:
    # tier A は H=0 で判定しており、週次への外挿は無検証だったため horizon 別に確認する）
    weekly_pb = {}
    for f, s, h, pb, n in conn.execute(
            "SELECT fish, ship, horizon, promise_break_rate, n FROM combo_range_backtest "
            "WHERE metric='cnt_bz' AND horizon IN (14, 21, 28)"):
        weekly_pb.setdefault((f, s), {})[h] = (pb, n)

    print(f"対象: {len(rows)}コンボ 先頭3: {[(r[0], r[1]) for r in rows[:3]]}")

    tiers = {}
    counts = {"A": 0, "star": 0, "none": 0}
    for (fish, ship, n_rec, use_fb, kaiyu_p, pb, n_bt, cov, wink,
         rb_updated, wmape, bl2w) in rows:
        reason = ""
        if fish in EXCLUDED_FISH:
            tier, reason = "none", "gomoku_excluded"
        elif fish in KAIYU_FISH and not kaiyu_p:
            tier, reason = "star", "kaiyu_not_promoted"
        elif (pb is not None and pb <= PB_THR and n_bt is not None and n_bt >= N_THR
              and not use_fb):
            tier = "A"
        else:
            tier = "none"
            if pb is None:
                reason = "no_backtest"
            elif use_fb:
                reason = "fallback_served"       # 本番は BL2 配信＝モデル実測値の対象外
            elif pb > PB_THR:
                reason = "pb_over"
            else:
                reason = "n_under"
        counts[tier] += 1
        entry = {"tier": tier}
        if reason:
            entry["reason"] = reason
        if pb is not None:
            entry["pb"] = round(pb, 4)
            entry["n"] = n_bt
        if wmape is not None:
            entry["wmape"] = round(wmape, 1)
        if tier == "A":
            # 週次ページ（H=14/21/28）にレンジを出してよいか: 全週次ホライズンで
            # pb<=閾値 かつ n>=閾値 を満たす場合のみ True（未計測ホライズンがあれば False）
            wpb = weekly_pb.get((fish, ship), {})
            entry["weekly_ok"] = all(
                h in wpb and wpb[h][0] is not None and wpb[h][0] <= PB_THR
                and wpb[h][1] is not None and wpb[h][1] >= N_THR
                for h in (14, 21, 28))
        tiers[f"{fish}|{ship}"] = entry

    payload = {
        "_meta": {
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "criteria": {"metric": "cnt_bz", "horizon": 0, "pb_max": PB_THR,
                         "n_min": N_THR, "require_no_fallback": True},
            "counts": counts,
            "note": "tier A のみ匹数レンジ公開可 / star は★のみ / none はレンジ非公開",
        },
        "tiers": tiers,
    }
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)

    fishes = {k.split("|")[0] for k, v in tiers.items() if v["tier"] == "A"}
    ships = {k.split("|")[1] for k, v in tiers.items() if v["tier"] == "A"}
    n_weekly = sum(1 for v in tiers.values() if v.get("weekly_ok"))
    print(f"完了: {OUT_JSON}")
    print(f"  tier A: {counts['A']}コンボ / {len(fishes)}魚種 / {len(ships)}船宿"
          f"（うち週次ページ表示可 {n_weekly}）")
    print(f"  star: {counts['star']} / none: {counts['none']}")


if __name__ == "__main__":
    main()
