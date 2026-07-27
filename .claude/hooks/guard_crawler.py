#!/usr/bin/env python3
"""PreToolUse(Bash) hook: 古い状態での crawler.py 実行を止める。

背景: 2026-05-21 に古い catches.json のままローカルで crawler.py を再実行し、
docs/index.html の HERO 表示日が 5/21 → 5/19 に巻き戻った（決定ログ 2026-05-22）。
CLAUDE.md に「必ず git pull」と書いてあっても守られない可能性があるので、
ここで機械的に落とす。

判定: origin/main より遅れている状態で crawler.py を実行しようとしたら deny。
      fetch できない（オフライン等）場合は allow して警告だけ出す。
"""
import json
import re
import subprocess
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# `python crawler.py ...` 形式の「実行」だけを拾う。
# `grep foo crawler.py` や `wc -l crawler.py` は対象外。
EXEC_RE = re.compile(r"(?:^|[|;&]|\s)(?:python3?|py)\s+[^|;&]*\bcrawler\.py\b")

# heredoc 本文とクォート文字列は「コマンド」ではないので照合前に落とす。
# （テストコードや説明文に python crawler.py と書いただけでブロックされるのを防ぐ）
HEREDOC_RE = re.compile(r"<<-?\s*'?\"?(\w+)'?\"?.*?^\1\s*$", re.S | re.M)
QUOTED_RE = re.compile(r"'[^']*'|\"[^\"]*\"")


def strip_noncommand(cmd):
    cmd = HEREDOC_RE.sub(" ", cmd)
    return QUOTED_RE.sub(" ", cmd)


def git(*args, timeout=15):
    try:
        return subprocess.run(
            ["git", *args],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=timeout,
        )
    except Exception:
        return None


def deny(reason):
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }))
    sys.exit(0)


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return

    cmd = (payload.get("tool_input") or {}).get("command") or ""
    if not EXEC_RE.search(strip_noncommand(cmd)):
        return

    fetched = git("fetch", "--quiet", "origin", timeout=30)
    if fetched is None or fetched.returncode != 0:
        print("[guard_crawler] git fetch に失敗（オフライン？）。"
              "pull 済みか自分で確認してから実行すること。")
        return

    r = git("rev-list", "--count", "HEAD..origin/main")
    if r is None or r.returncode != 0:
        return

    try:
        behind = int(r.stdout.strip())
    except ValueError:
        return

    if behind > 0:
        deny(
            f"ローカルが origin/main より {behind} コミット遅れている状態で "
            f"crawler.py を実行しようとした。\n"
            f"古い catches.json で HTML を再生成すると docs/index.html の HERO 日付が"
            f"巻き戻る（2026-05-21 に実害あり・決定ログ 2026-05-22）。\n"
            f"先に `git pull` してから実行し直すこと。\n"
            f"※ HTML の文字列置換だけが目的なら crawler.py は回さず、"
            f"docs/ を直接書き換える独立スクリプトを使う。"
        )


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass  # フックの失敗でツール呼び出しを壊さない
    sys.exit(0)
