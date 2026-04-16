"""
全魚種 combo_deep_dive 再実行スクリプト
wave_clamp=2.0（確定値）で全55魚種を順次処理
"""
import subprocess, sys, os, json, sqlite3, time

BASE_DIR = os.path.dirname(__file__)
SCRIPT = os.path.join(BASE_DIR, "analysis", "V2", "methods", "combo_deep_dive.py")
DB_PATH = os.path.join(BASE_DIR, "analysis", "V2", "results", "analysis.sqlite")
LOG_PATH = os.path.join(BASE_DIR, "run_full_deepdive.log")

# 全魚種を analysis.sqlite から取得
conn = sqlite3.connect(DB_PATH)
fish_list = [r[0] for r in conn.execute("SELECT DISTINCT fish FROM combo_decadal ORDER BY fish")]
conn.close()

print(f"対象: {len(fish_list)}件 先頭3: {fish_list[:3]}", flush=True)

results = {}
start_all = time.time()

with open(LOG_PATH, "w", encoding="utf-8") as log:
    for i, fish in enumerate(fish_list):
        print(f"[{i+1}/{len(fish_list)}] {fish} 処理中...", flush=True)
        log.write(f"[{i+1}/{len(fish_list)}] {fish}\n")
        log.flush()

        t0 = time.time()
        try:
            r = subprocess.run(
                [sys.executable, SCRIPT, "--fish", fish, "--wave-clamp", "2.0"],
                capture_output=True,
                timeout=300,
                cwd=BASE_DIR,
            )
            elapsed = round(time.time() - t0, 1)
            ok = r.returncode == 0
            results[fish] = {"ok": ok, "sec": elapsed, "returncode": r.returncode}
            status = "OK" if ok else f"NG(rc={r.returncode})"
            print(f"  → {status} ({elapsed}s)", flush=True)
            log.write(f"  {status} ({elapsed}s)\n")
            if not ok and r.stderr:
                err_line = r.stderr.strip().splitlines()[-1] if r.stderr.strip() else ""
                log.write(f"  stderr: {err_line}\n")
        except subprocess.TimeoutExpired:
            results[fish] = {"ok": False, "sec": 300, "returncode": -1}
            print(f"  → TIMEOUT", flush=True)
            log.write("  TIMEOUT\n")
        log.flush()

elapsed_all = round(time.time() - start_all, 1)
ok_count = sum(1 for v in results.values() if v["ok"])
ng_list = [f for f, v in results.items() if not v["ok"]]

print(f"\n完了: {ok_count}/{len(fish_list)} OK  所要時間: {elapsed_all}s", flush=True)
if ng_list:
    print(f"NG: {ng_list}", flush=True)

# wMAPE H=0,7 中央値を集計
conn = sqlite3.connect(DB_PATH)
rows_h0 = [r[0] for r in conn.execute(
    "SELECT wmape FROM combo_backtest WHERE horizon=0 AND wmape IS NOT NULL"
)]
rows_h7 = [r[0] for r in conn.execute(
    "SELECT wmape FROM combo_backtest WHERE horizon=7 AND wmape IS NOT NULL"
)]
conn.close()

def median(lst):
    if not lst: return None
    s = sorted(lst)
    n = len(s)
    return round((s[n//2-1] + s[n//2]) / 2 if n % 2 == 0 else s[n//2], 1)

print(f"wMAPE中央値: H=0={median(rows_h0)}% H=7={median(rows_h7)}%  (n_h0={len(rows_h0)} n_h7={len(rows_h7)})", flush=True)
print(f"LOG: {LOG_PATH}", flush=True)
