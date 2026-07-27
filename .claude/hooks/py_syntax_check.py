#!/usr/bin/env python3
"""PostToolUse(Edit|Write) hook: 編集した .py の構文エラーを即座に検出する。

背景: crawler.py は 19,000 行。構文エラーに気づかず push すると CI が回り、
1時間20分後に fail が返ってくる。編集直後に落とせば1秒で分かる。

__pycache__ を作らないよう py_compile ではなく compile() を使う。
"""
import ast
import json
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0

    path_str = (payload.get("tool_input") or {}).get("file_path") or ""
    if not path_str.endswith(".py"):
        return 0

    path = Path(path_str)
    if not path.is_file():
        return 0

    try:
        source = path.read_text(encoding="utf-8")
    except Exception:
        return 0

    try:
        ast.parse(source, filename=str(path))
    except SyntaxError as e:
        print(
            f"[構文エラー] {path.name}:{e.lineno}: {e.msg}\n"
            f"  {(e.text or '').rstrip()}\n"
            f"直前の編集で壊れている。CI に投げる前に直すこと。",
            file=sys.stderr,
        )
        return 2  # exit 2 = Claude にフィードバックされる
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)  # フックの失敗で編集を壊さない
