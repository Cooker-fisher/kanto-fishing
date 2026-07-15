#!/usr/bin/env python3
"""
build_predict_params.py — 予測パラメータ蒸留 DB のエクスポート（ローカル実行・D層 Phase 2）

analysis.sqlite（400MB 級・gitignore・ローカルのみ）から、predict_count.py の
日次予測に必要なテーブルだけを predict_params.sqlite（数MB・コミット対象）へ抽出する。
これにより GitHub Actions（クラウド）だけで毎日のD層予測が完結する。

設計（90_決定ログ.md 2026-06-10「D層無料公開の確定仕様」）:
- 予測エンジンは predict_count.py をそのまま使う（新規エンジンは書かない）。
  predict_count.py は analysis.sqlite が無い環境では本 DB に自動フォールバックする。
- 抽出対象はコンボレベルモデルのみ。ポイント/水色/水深/便別の追加補正チェーンは
  対象外（テーブル欠落時は predict_count.py 側が try/except で安全にスキップする
  ことを確認済み 2026-06-10）。バックテスト検証済み精度（cnt promise_break P50 6.4%）
  はコンボレベルモデルの数値なので、蒸留版の精度表示と整合する。

使い方（ローカル・analysis.sqlite が存在するマシンで）:
  python analysis/V2/methods/build_predict_params.py
  → analysis/V2/results/predict_params.sqlite を生成 → git commit して push

実行タイミング: run_full_deepdive.py での全コンボ再分析のたびに再実行・再コミット。
"""

import os
import sqlite3
import sys
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _paths import RESULTS_DIR

SRC_DB = os.path.join(RESULTS_DIR, "analysis.sqlite")
DST_DB = os.path.join(RESULTS_DIR, "predict_params.sqlite")

# 蒸留対象テーブル（predict_count.py の EXPOSED クエリ先 + E層ゲーティング用）
# 各エントリ: (テーブル名, 必須か, (fish, ship) インデックスを張るか)
#
# 行フィルタ（任意）: テーブル名 → WHERE 句。ローカル診断専用の行を配布DBから除く。
# combo_range_backtest の T44 系列（cnt_direct/cnt_prod/cnt_bz/cnt_prod_bz）は
# 経路比較のための評価専用行なので配布しない（code-reviewer 指摘）。
ROW_FILTERS = {
    "combo_range_backtest": "metric IN ('cnt','size','kg','composite')",
}
EXPORT_TABLES = [
    ("combo_decadal",            True,  True),   # 旬別ベースライン（予測の土台）
    ("combo_wx_params",          True,  True),   # 気象補正係数 + _meta（lat/lon/use_fallback/kaiyu_promoted/wave_clamp）
    ("combo_backtest",           True,  True),   # wMAPE/MAE（★算出・model_reliable 判定）
    ("combo_meta",               True,  True),   # n_records / 座標
    ("combo_star_backtest",      True,  True),   # 回遊魚★チャンス評価の分位点（P20/40/60/80・good_line）
    ("combo_slot_ratio",         False, True),   # 時間帯補正比率
    ("combo_range_backtest",     True,  True),   # promise_break/winkler（E層の表示ゲーティング用・winkler 極端コンボの数レンジ非表示）
    ("cancel_thresholds",        False, False),  # 欠航閾値（D4）
    ("cancel_thresholds_combo",  False, True),   # コンボ別欠航閾値（D4）
    ("combo_multi_point_factors", False, True),  # 複数ポイント移動補正（bad）
    ("combo_multi_point_context", False, True),  # 複数ポイント移動補正（bad+good）
]


def main():
    if not os.path.exists(SRC_DB):
        print(f"ERROR: {SRC_DB} が見つかりません。analysis.sqlite のあるローカルマシンで実行してください。")
        sys.exit(1)

    src = sqlite3.connect(SRC_DB)
    src_tables = {r[0] for r in src.execute(
        "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}

    missing_required = [t for t, req, _ in EXPORT_TABLES if req and t not in src_tables]
    if missing_required:
        print(f"ERROR: 必須テーブルが analysis.sqlite にありません: {missing_required}")
        sys.exit(1)

    if os.path.exists(DST_DB):
        os.remove(DST_DB)
    dst = sqlite3.connect(DST_DB)
    dst.execute(f"ATTACH DATABASE ? AS src", (SRC_DB,))

    counts = {}
    for table, required, want_index in EXPORT_TABLES:
        if table not in src_tables:
            print(f"  skip（任意・ソースに無し）: {table}")
            continue
        _where = ROW_FILTERS.get(table)
        dst.execute(f"CREATE TABLE {table} AS SELECT * FROM src.{table}"
                    + (f" WHERE {_where}" if _where else ""))
        n = dst.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        if _where:
            print(f"  行フィルタ適用: {table} … WHERE {_where}")
        counts[table] = n
        if want_index:
            cols = {r[1] for r in dst.execute(f"PRAGMA table_info({table})").fetchall()}
            if {"fish", "ship"} <= cols:
                dst.execute(f"CREATE INDEX idx_{table}_fs ON {table}(fish, ship)")
        print(f"  export: {table:<28} {n:>7} 行")

    # 由来メタデータ（predict_count.py が起動ログに出す・鮮度検証用）
    dst.execute("CREATE TABLE export_meta (key TEXT PRIMARY KEY, value TEXT)")
    dst.executemany("INSERT INTO export_meta VALUES (?, ?)", [
        ("exported_at", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        ("source_db", SRC_DB),
        ("mode", "full"),  # full = combo_wx_params あり（気象補正つきフルモデル）
        ("table_counts", repr(counts)),
    ])
    dst.commit()
    dst.execute("DETACH DATABASE src")
    dst.close()
    src.close()

    size_mb = os.path.getsize(DST_DB) / 1024 / 1024
    print(f"\n完了: {DST_DB}（{size_mb:.1f} MB）")
    if size_mb > 40:
        print("WARNING: 40MB 超。コミット前にテーブル構成を見直してください。")
    print("次の手順: git add analysis/V2/results/predict_params.sqlite → commit → push")


if __name__ == "__main__":
    main()
