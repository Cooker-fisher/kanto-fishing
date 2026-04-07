#!/usr/bin/env python3
"""
run.py — 分析スクリプトランチャー（crawl.yml から呼ばれる）

使い方:
    python3 analysis/run.py season_analysis.py
    python3 analysis/run.py weekly_analysis.py --query アジ

config.json の active_version を見て、対応する methods/ 以下のスクリプトを実行する。
バージョン切替は config.json の active_version を変えるだけ。run.py 自体は変更不要。
"""
import json, os, subprocess, sys

_DIR  = os.path.dirname(os.path.abspath(__file__))   # analysis/
_ROOT = os.path.dirname(_DIR)                         # project root

with open(os.path.join(_ROOT, "config.json"), encoding="utf-8") as f:
    ver = json.load(f)["active_version"]

if len(sys.argv) < 2:
    print("Usage: python3 analysis/run.py <script.py> [args...]", file=sys.stderr)
    sys.exit(1)

script_name = sys.argv[1]
extra_args  = sys.argv[2:]
script_path = os.path.join(_DIR, ver, "methods", script_name)

if not os.path.exists(script_path):
    print(f"ERROR: {script_path} not found", file=sys.stderr)
    sys.exit(1)

result = subprocess.run([sys.executable, script_path] + extra_args)
sys.exit(result.returncode)
