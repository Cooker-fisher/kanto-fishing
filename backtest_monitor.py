"""バックテスト進捗ライブモニタ（コンボ単位）。
実行中の run_full_deepdive.py の進捗を analysis.sqlite の updated_at から読み取り表示。
使い方:  python backtest_monitor.py
"""
import sqlite3, time, os, sys, io
from datetime import datetime, timedelta

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", line_buffering=True)

DB = "analysis/V2/results/analysis.sqlite"
START_STR = (datetime.now() - timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M:%S")


def snapshot():
    if not os.path.exists(DB):
        return []
    c = sqlite3.connect(DB)
    # コンボ単位（fish, ship）で updated_at を取得
    rows = c.execute(
        "SELECT fish, ship, updated_at FROM combo_meta "
        "WHERE updated_at > ? ORDER BY updated_at",
        (START_STR,),
    ).fetchall()
    c.close()
    return rows


def fish_progress():
    """魚種単位の完了数（参考表示用）"""
    if not os.path.exists(DB):
        return 0
    c = sqlite3.connect(DB)
    n = c.execute(
        "SELECT COUNT(DISTINCT fish) FROM combo_meta WHERE updated_at > ?",
        (START_STR,),
    ).fetchone()[0]
    c.close()
    return n


def main():
    seen = set()
    t0 = time.time()
    while True:
        rows = snapshot()
        new = [(f, s, t) for f, s, t in rows if (f, s) not in seen]
        for fish, ship, ts in new:
            elapsed = int(time.time() - t0)
            m, sec = divmod(elapsed, 60)
            fn = fish_progress()
            print(
                f"[combo {len(seen)+1} / fish {fn}/55] {ts}  {fish} × {ship}  (elapsed {m}m{sec:02d}s)",
                flush=True,
            )
            seen.add((fish, ship))
        time.sleep(10)


if __name__ == "__main__":
    main()
