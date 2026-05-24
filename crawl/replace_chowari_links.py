"""docs/**/*.html 内の旧 chowari-NNNNN リンクを新 slug に一括置換。

crawler.py 全体再実行を回避し、HTML文字列置換のみで内部リンクを更新する。
（feedback_crawler_local_rerun.md 準拠: HTML 置換が目的なら crawler.py を回さない）

入力: crawl/chowari_slug_redirect_map.json
出力: docs/**/*.html の chowari-XXX 出現箇所を新 slug に置換
ただし docs/ship/chowari-NNNNN.html ファイル自体は redirect HTML として残す
"""
import json
import os
import re
from glob import glob

REDIRECT_MAP_PATH = "crawl/chowari_slug_redirect_map.json"
DOCS_DIR = "docs"


def main():
    with open(REDIRECT_MAP_PATH, encoding="utf-8") as f:
        redirect_map = json.load(f)
    print(f"redirect_map: {len(redirect_map)} エントリ読込")

    # 置換パターン: chowari-NNNNN (slug 文字列として独立した形)
    # 単純な文字列 replace で OK（slug は html 内では `/ship/chowari-00453.html` 形式）
    files = sorted(glob(os.path.join(DOCS_DIR, "**", "*.html"), recursive=True))
    print(f"対象HTMLファイル: {len(files)}件")

    total_replaced = 0
    touched_files = 0
    for fp in files:
        # ship/chowari-NNNNN.html 自体は redirect HTML（中身に chowari- なし）なのでスキップ
        bn = os.path.basename(fp)
        if bn.startswith("chowari-") and bn.endswith(".html"):
            continue
        try:
            with open(fp, encoding="utf-8") as f:
                txt = f.read()
        except Exception:
            continue
        if "chowari-" not in txt:
            continue
        orig = txt
        for old_slug, new_slug in redirect_map.items():
            if old_slug in txt:
                txt = txt.replace(old_slug, new_slug)
        if txt != orig:
            with open(fp, "w", encoding="utf-8") as f:
                f.write(txt)
            replaced = sum(1 for old in redirect_map if old in orig)
            total_replaced += replaced
            touched_files += 1

    print(f"[OK] {touched_files} ファイル更新 / 合計 {total_replaced} 件置換")


if __name__ == "__main__":
    main()
