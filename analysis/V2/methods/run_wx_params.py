#!/usr/bin/env python3
"""
run_wx_params.py — 全魚種の combo_wx_params を生成するための combo_deep_dive 一括実行

combo_backtest に存在する魚種を対象に combo_deep_dive を再実行し、
新たに追加された combo_wx_params テーブルを埋める。
"""
import io, os, sqlite3, subprocess, sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)
from _paths import RESULTS_DIR

db = sqlite3.connect(os.path.join(RESULTS_DIR, "analysis.sqlite"))
fish_list = [r[0] for r in db.execute(
    "SELECT DISTINCT fish FROM combo_backtest ORDER BY fish"
).fetchall()]
db.close()

print(f"対象: {len(fish_list)}種 先頭3: {fish_list[:3]}", flush=True)

ok = 0; ng = 0
for fish in fish_list:
    result = subprocess.run(
        [sys.executable, os.path.join(SCRIPT_DIR, "combo_deep_dive.py"), "--fish", fish],
        capture_output=True,
        cwd=SCRIPT_DIR,
    )
    if result.returncode == 0:
        ok += 1
        print(f"  [OK] {fish} ({ok}/{len(fish_list)})", flush=True)
    else:
        ng += 1
        print(f"  [NG] {fish} returncode={result.returncode}", flush=True)

print(f"\n完了: {ok}成功 / {ng}失敗", flush=True)

# combo_wx_params の件数確認
db = sqlite3.connect(os.path.join(RESULTS_DIR, "analysis.sqlite"))
n = db.execute("SELECT COUNT(*) FROM combo_wx_params").fetchone()
fish_saved = db.execute(
    "SELECT COUNT(DISTINCT fish) FROM combo_wx_params WHERE factor='_meta'"
).fetchone()
db.close()
print(f"combo_wx_params: {n[0]}行 / {fish_saved[0]}魚種", flush=True)
