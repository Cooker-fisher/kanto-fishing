#!/usr/bin/env python3
"""
analysis.sqlite の prediction_log から「答え合わせ済み」上位5件を抽出し、
analysis/V2/results/prediction_log_recent.json に書き出すスクリプト。

R5 (2026/05/06): crawler.py の build_teaser_rotator_html() が CI 環境で
analysis.sqlite を参照できないため、JSON にエクスポートして commit する経路。

実行:
    python analysis/V2/predict/export_prediction_log_recent.py

CI 推奨タイミング: weekly_insights ジョブの match_actuals 実行後。
"""
import json
import os
import sqlite3
import sys
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
SQLITE_PATH = os.path.join(ROOT, "analysis", "V2", "results", "analysis.sqlite")
OUT_PATH = os.path.join(ROOT, "analysis", "V2", "results", "prediction_log_recent.json")


def main():
    if not os.path.exists(SQLITE_PATH):
        print(f"ERROR: analysis.sqlite が見つからない: {SQLITE_PATH}", file=sys.stderr)
        sys.exit(1)
    conn = sqlite3.connect(SQLITE_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("""
        SELECT target_date, fish, ship, pred_pct, actual_pct, is_good_hit,
               fcast_wave, actual_wave, fcast_wind, actual_wind, fcast_sst, fcast_temp,
               pred_cnt_min, pred_cnt_max, actual_cnt_min, actual_cnt_max, horizon
        FROM prediction_log
        WHERE is_good_hit IS NOT NULL AND pred_pct IS NOT NULL AND actual_pct IS NOT NULL
          AND ABS(pred_pct) > 1.0 AND ABS(actual_pct) > 1.0
        ORDER BY
            CASE WHEN is_good_hit=1 THEN 0 ELSE 1 END,
            ABS(pred_pct - actual_pct) ASC,
            target_date DESC
        LIMIT 5
    """)
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    out = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source": "analysis/V2/results/analysis.sqlite prediction_log",
        "records": rows,
    }
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"exported {len(rows)} records → {OUT_PATH}")


if __name__ == "__main__":
    main()
