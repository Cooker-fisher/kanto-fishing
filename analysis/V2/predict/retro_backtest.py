#!/usr/bin/env python3
"""
retro_backtest.py — 過去データを使った予測パイプライン統合テスト

TRAIN_END(2024/12/31)以降の実績データを「未来」として扱い、
predict_combo() の予測値と比較することで予測精度を事前検証する。

注意: combo_decadal は全期間データで作成済みのため、2025年データに対して
わずかな情報リークが発生する。あくまで「パイプライン動作確認 + 精度上限の見積もり」
として使用すること（真のOOSはフェーズ2の prediction_log で実施）。

使い方:
  python retro_backtest.py              # デフォルト: 2025/01/01〜2025/12/31
  python retro_backtest.py --start 2025/07/01 --end 2025/12/31
  python retro_backtest.py --stats      # 保存済み結果のサマリー表示
  python retro_backtest.py --dry-run    # 対象件数のみ確認
"""

import argparse, csv, os, sqlite3, sys
from datetime import datetime, timedelta
from collections import defaultdict

sys.stdout.reconfigure(encoding="utf-8")

import sys as _sys
_sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "methods"))
from _paths import ROOT_DIR, RESULTS_DIR, DATA_DIR

DB_PATH    = os.path.join(RESULTS_DIR, "analysis.sqlite")
TRAIN_END  = "2024/12/31"


# ── ユーティリティ ────────────────────────────────────────────────────────────

def _wmape(preds, acts):
    num = sum(abs(p - a) for p, a in zip(preds, acts))
    den = sum(abs(a) for a in acts)
    return round(num / den * 100, 2) if den > 0 else None

def _rmse(errs):
    return (sum(e**2 for e in errs) / len(errs)) ** 0.5 if errs else None

def _skill_score(pred_errs, clim_errs):
    """Skill Score = 1 - RMSE_model / RMSE_climatology"""
    rm = _rmse(pred_errs)
    rc = _rmse(clim_errs)
    if rm is None or rc is None or rc == 0:
        return None
    return round(1 - rm / rc, 3)


# ── 実績データ読み込み ─────────────────────────────────────────────────────────

def load_actuals(start: str, end: str) -> dict:
    """
    CSV から (fish, ship, date) → actual_cnt_avg を返す辞書を作成。
    TRAIN_END より後のデータのみ。
    """
    actuals = {}
    for fn in sorted(os.listdir(DATA_DIR)):
        if not fn.endswith(".csv") or fn == "cancellations.csv":
            continue
        with open(os.path.join(DATA_DIR, fn), encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                if row.get("is_cancellation") == "1":
                    continue
                if row.get("main_sub") != "メイン":
                    continue
                date = row.get("date", "").strip()
                if not (start <= date <= end):
                    continue
                if date <= TRAIN_END:
                    continue
                cnt_avg = row.get("cnt_avg", "").strip()
                if not cnt_avg:
                    continue
                try:
                    cnt = float(cnt_avg)
                    if cnt <= 0:
                        continue
                except ValueError:
                    continue
                fish = row.get("tsuri_mono", "").strip()
                ship = row.get("ship", "").strip()
                if not fish or not ship:
                    continue
                key = (fish, ship, date)
                # 同日複数便は平均
                if key in actuals:
                    actuals[key] = (actuals[key][0] + cnt, actuals[key][1] + 1)
                else:
                    actuals[key] = (cnt, 1)

    # 平均化
    return {k: round(v[0] / v[1], 2) for k, v in actuals.items()}


# ── テーブル初期化 ────────────────────────────────────────────────────────────

def init_table(conn):
    conn.execute("""
    CREATE TABLE IF NOT EXISTS retro_backtest (
        fish         TEXT,
        ship         TEXT,
        target_date  TEXT,
        pred_cnt     REAL,   -- predict_combo の予測値
        actual_cnt   REAL,   -- 実績
        baseline_cnt REAL,   -- 旬別ベースライン（climatology）
        abs_err      REAL,   -- |pred - actual|
        pred_stars   INTEGER,
        transition_risk REAL,
        run_date     TEXT,   -- この retro_backtest を実行した日
        PRIMARY KEY (fish, ship, target_date)
    )
    """)
    conn.commit()


# ── メイン実行 ────────────────────────────────────────────────────────────────

def run(start: str, end: str, dry_run: bool = False):
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "predict_count",
        os.path.join(os.path.dirname(__file__), "..", "methods", "predict_count.py")
    )
    pc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pc)

    conn = sqlite3.connect(DB_PATH)
    init_table(conn)

    # 対象コンボ: combo_meta から ★3以上
    combos = conn.execute("""
        SELECT bt.fish, bt.ship, cm.n_records
        FROM combo_backtest bt
        JOIN combo_meta cm ON bt.fish=cm.fish AND bt.ship=cm.ship
        WHERE bt.metric='cnt_avg' AND bt.horizon=7
          AND bt.wmape IS NOT NULL
    """).fetchall()
    combo_set = {(r[0], r[1]) for r in combos}
    print(f"対象コンボ: {len(combo_set)}件 先頭3: {list(combo_set)[:3]}")

    # 実績データ読み込み
    actuals = load_actuals(start, end)
    print(f"実績レコード: {len(actuals)}件 ({start} 〜 {end})")

    # コンボ×日付でマッチするものだけ抽出
    targets = [(fish, ship, date, cnt)
               for (fish, ship, date), cnt in actuals.items()
               if (fish, ship) in combo_set]
    targets.sort(key=lambda x: x[2])
    print(f"予測対象: {len(targets)}件")

    if dry_run:
        print("[dry-run] ここで終了")
        conn.close()
        return

    run_date = datetime.now().strftime("%Y-%m-%d")
    inserted = skipped = 0

    for fish, ship, date, actual_cnt in targets:
        pred = pc.predict_combo(conn, fish, ship, date)
        if pred is None:
            skipped += 1
            continue

        pred_cnt     = pred["cnt_predicted"]
        baseline_cnt = pred.get("baseline_cnt") or pred_cnt  # baseline_cnt は predict_combo が返す

        conn.execute("""
            INSERT OR REPLACE INTO retro_backtest
                (fish, ship, target_date, pred_cnt, actual_cnt, baseline_cnt,
                 abs_err, pred_stars, transition_risk, run_date)
            VALUES (?,?,?,?,?,?,?,?,?,?)
        """, (
            fish, ship, date,
            pred_cnt, actual_cnt, baseline_cnt,
            round(abs(pred_cnt - actual_cnt), 2),
            pred.get("stars"),
            pred.get("transition_risk"),
            run_date
        ))
        inserted += 1
        if inserted % 500 == 0:
            conn.commit()
            print(f"  {inserted}件処理済み...", flush=True)

    conn.commit()
    print(f"\n完了: {inserted}件 INSERT / {skipped}件スキップ")

    # 精度サマリー
    _print_stats(conn)
    conn.close()


# ── 精度サマリー ──────────────────────────────────────────────────────────────

def _print_stats(conn):
    rows = conn.execute("""
        SELECT pred_cnt, actual_cnt, baseline_cnt
        FROM retro_backtest
        WHERE pred_cnt IS NOT NULL AND actual_cnt IS NOT NULL
    """).fetchall()

    if len(rows) < 10:
        print("(サンプル不足)")
        return

    preds    = [r[0] for r in rows]
    acts     = [r[1] for r in rows]
    baselines = [r[2] for r in rows if r[2] is not None]

    pred_errs = [p - a for p, a in zip(preds, acts)]
    clim_errs = [b - a for b, a in zip(baselines, acts[:len(baselines)])]

    wm = _wmape(preds, acts)
    ss = _skill_score(pred_errs, clim_errs) if len(clim_errs) >= 10 else None

    print(f"\n=== レトロスペクティブ・バックテスト結果 ===")
    print(f"サンプル数: {len(rows)}件")
    print(f"wMAPE     : {wm}%")
    print(f"Skill Score: {ss}  (>0 = climatologyに勝ち)")

    # ★別集計
    star_rows = conn.execute("""
        SELECT pred_stars,
               COUNT(*),
               ROUND(AVG(abs_err), 2),
               ROUND(SUM(ABS(pred_cnt - actual_cnt)) * 100.0 / SUM(ABS(actual_cnt)), 1)
        FROM retro_backtest
        WHERE pred_cnt IS NOT NULL AND actual_cnt IS NOT NULL
        GROUP BY pred_stars ORDER BY pred_stars DESC
    """).fetchall()
    print(f"\n★別 wMAPE:")
    print(f"  {'★':>3}  {'n':>5}  {'MAE':>7}  {'wMAPE':>7}")
    for r in star_rows:
        print(f"  ★{r[0]}  {r[1]:>5}  {r[2]:>7}  {r[3]:>6}%")

    # transition_risk別
    tr_rows = conn.execute("""
        SELECT CASE WHEN transition_risk > 0.3 THEN '変動期' ELSE '安定期' END as period,
               COUNT(*),
               ROUND(SUM(ABS(pred_cnt - actual_cnt)) * 100.0 / SUM(ABS(actual_cnt)), 1)
        FROM retro_backtest
        WHERE pred_cnt IS NOT NULL AND actual_cnt IS NOT NULL
        GROUP BY period
    """).fetchall()
    print(f"\n変動期 vs 安定期:")
    for r in tr_rows:
        print(f"  {r[0]}: n={r[1]}  wMAPE={r[2]}%")


def stats_only():
    conn = sqlite3.connect(DB_PATH)
    n = conn.execute("SELECT COUNT(*) FROM retro_backtest").fetchone()[0]
    if n == 0:
        print("retro_backtest テーブルが空です。先に run を実行してください。")
    else:
        _print_stats(conn)
    conn.close()


# ── エントリーポイント ────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="レトロスペクティブ・バックテスト")
    parser.add_argument("--start",   default="2025/01/01", help="開始日 (YYYY/MM/DD)")
    parser.add_argument("--end",     default="2025/12/31", help="終了日 (YYYY/MM/DD)")
    parser.add_argument("--dry-run", action="store_true",  help="件数確認のみ")
    parser.add_argument("--stats",   action="store_true",  help="保存済み結果のサマリー表示")
    args = parser.parse_args()

    if args.stats:
        stats_only()
    else:
        run(args.start, args.end, dry_run=args.dry_run)

if __name__ == "__main__":
    main()
