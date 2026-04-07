"""
_paths.py — analysis/V2/methods/ 内スクリプト共通パス定義

CLAUDE.md を目印にプロジェクトルートを自動検出するため、
スクリプトをどの深さに置いても ROOT_DIR が正しく解決される。

DATA_DIR は config.json の active_version に連動する。
  例: active_version = "V2" → ROOT_DIR/data/V2/
バージョンアップ時（CSV列追加等）は config.json の active_version を上げるだけ。

使い方:
    from _paths import ROOT_DIR, RESULTS_DIR, DATA_DIR, NORMALIZE_DIR, OCEAN_DIR
"""
import json as _json
import os as _os

def _find_root() -> str:
    p = _os.path.dirname(_os.path.abspath(__file__))
    while True:
        if _os.path.exists(_os.path.join(p, "CLAUDE.md")):
            return p
        parent = _os.path.dirname(p)
        if parent == p:
            raise RuntimeError("project root not found (CLAUDE.md missing)")
        p = parent

ROOT_DIR      = _find_root()
RESULTS_DIR   = _os.path.normpath(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "results"))
NORMALIZE_DIR = _os.path.join(ROOT_DIR, "normalize")
OCEAN_DIR     = _os.path.join(ROOT_DIR, "ocean")

# data/ はバージョン管理。config.json の active_version に連動。
try:
    with open(_os.path.join(ROOT_DIR, "config.json"), encoding="utf-8") as _f:
        _active_ver = _json.load(_f)["active_version"]
except Exception:
    _active_ver = "V2"
DATA_DIR = _os.path.join(ROOT_DIR, "data", _active_ver)
