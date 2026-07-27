#!/usr/bin/env python3
"""Stop hook: 応答を終える時点で「作った物が届いていない」状態を報告する。

背景: 完成した作業がブランチに残ったまま忘れられるケースが繰り返し発生していた
（未マージ 30 ブランチ・project_status.md の「未push」記述多数）。

ブロックはしない（push を強制すると事故る）。報告だけして判断は人に返す。
"""
import json
import subprocess
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def git(*args, default=""):
    try:
        r = subprocess.run(
            ["git", *args],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=10,
        )
        return r.stdout.strip() if r.returncode == 0 else default
    except Exception:
        return default


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        payload = {}

    # 無限ループ防止（ブロックしない実装なので理論上不要だが念のため）
    if payload.get("stop_hook_active"):
        return

    warnings = []

    dirty = [l for l in git("status", "--porcelain").splitlines() if l.strip()]
    if dirty:
        # porcelain は "XY path"。先頭行は git() の strip() で 1 文字ずれるので
        # 位置スライスではなく空白分割で取る。
        files = ", ".join(l.strip().split(None, 1)[-1] for l in dirty[:5])
        more = f" 他{len(dirty) - 5}件" if len(dirty) > 5 else ""
        warnings.append(f"未コミット {len(dirty)} 件: {files}{more}")

    counts = git("rev-list", "--left-right", "--count", "@{u}...HEAD")
    if counts and "\t" in counts:
        try:
            ahead = int(counts.split("\t")[1])
            if ahead > 0:
                branch = git("rev-parse", "--abbrev-ref", "HEAD", default="?")
                warnings.append(f"未push {ahead} 件（{branch}）")
        except (ValueError, IndexError):
            pass

    if warnings:
        print("[未着地の作業] " + " / ".join(warnings))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
