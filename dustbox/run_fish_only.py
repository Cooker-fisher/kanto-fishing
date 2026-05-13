"""build_fish_pages のみ実行するドライバ（シーバス形式廃止 動作確認用）。
catches.json (スナップショット) + history.json を読んで docs/fish/*.html を再生成する。
catches.json の data は当日スナップショット = sparse だが、
build_fish_pages 内部で _load_recent_catches_for_index / _hist_rows_for_fish が
data/V2/*.csv から過去データを補完するため問題ない。
"""
import json, sys, os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

import crawler
from datetime import datetime

print("=== run_fish_only.py: fish ページ再生成 ===")

with open("catches.json", encoding="utf-8") as f:
    snap = json.load(f)
valid_catches = snap.get("data", snap) if isinstance(snap, dict) else snap
print(f"  catches.json data: {len(valid_catches)} 件")

with open("history.json", encoding="utf-8") as f:
    history = json.load(f)

crawled_at = datetime.now(crawler.JST).replace(tzinfo=None).strftime("%Y/%m/%d %H:%M")

print("build_fish_pages 実行中...")
crawler.build_fish_pages(valid_catches, history, crawled_at)
print("=== 完了 ===")
