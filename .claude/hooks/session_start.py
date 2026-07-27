#!/usr/bin/env python3
"""SessionStart hook: セッション開始時に repo の現在地を注入する。

stdout に書いた内容がそのまま Claude のコンテキストに入る。
「今どこ？」の往復をゼロにするのが目的。ネットワークアクセスはしない（起動を遅くしないため）。
"""
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
    branch = git("rev-parse", "--abbrev-ref", "HEAD", default="?")
    recent = git("log", "-3", "--format=%h %ad %s", "--date=short")
    dirty = [l for l in git("status", "--porcelain").splitlines() if l.strip()]

    # upstream 比較（fetch はしない＝ローカルが知っている範囲での ahead/behind）
    ahead = behind = "?"
    counts = git("rev-list", "--left-right", "--count", "@{u}...HEAD")
    if counts and "\t" in counts:
        behind, ahead = counts.split("\t")[:2]

    lines = ["[repo 現在地]", f"branch: {branch}"]
    if recent:
        lines.append("直近コミット:")
        lines.extend(f"  {l}" for l in recent.splitlines())

    if dirty:
        shown = "\n".join(f"  {l.strip()}" for l in dirty[:8])
        more = f"\n  ...他 {len(dirty) - 8} 件" if len(dirty) > 8 else ""
        lines.append(f"未コミットの変更 {len(dirty)} 件:\n{shown}{more}")
    else:
        lines.append("未コミットの変更: なし")

    if ahead not in ("?", "0"):
        lines.append(f"⚠ 未push のコミットが {ahead} 件ある")
    if behind not in ("?", "0"):
        lines.append(
            f"⚠ origin より {behind} コミット遅れている"
            "（crawler.py を回す前に git pull が要る）"
        )

    print("\n".join(lines))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass  # フックの失敗でセッションを壊さない
    sys.exit(0)
