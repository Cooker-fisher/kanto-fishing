#!/usr/bin/env python3
"""
analysis_config.py — 後工程（crawler.py 等）が active_version の results/ を参照するためのユーティリティ

使い方:
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from analysis.analysis_config import get_results_dir, get_active_version
"""
import json, os

_DIR     = os.path.dirname(os.path.abspath(__file__))   # analysis/
_ROOT    = os.path.dirname(_DIR)                         # project root

def get_active_version() -> str:
    with open(os.path.join(_ROOT, "config.json"), encoding="utf-8") as f:
        return json.load(f)["active_version"]

def get_results_dir() -> str:
    ver = get_active_version()
    return os.path.join(_DIR, ver, "results")

def get_db_path(filename: str = "analysis.sqlite") -> str:
    return os.path.join(get_results_dir(), filename)
