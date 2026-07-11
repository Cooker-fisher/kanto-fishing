#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""GSC 実績のある fish_area slug リストを生成する（2026/07/12 SEO）。

analytics/gsc/*.csv（fetch_gsc.py が毎日蓄積）から /fish_area/ ページの
表示・クリック実績を集計し、閾値（impressions>=2 or clicks>=1）を超えた
slug を normalize/fa_gsc_proven_slugs.json に書き出す。

crawler.py の build_fish_area_pages() はこの JSON を読み、収載 slug を
hist 閾値（_FA_NOINDEX_HIST_THRESHOLD=80）未満でも index 復帰させる。
検索需要が実際に観測されたページを noindex で殺さないための機構。

実行（月1・GSC CSV 更新後）:
    python analytics/build_fa_gsc_slugs.py
生成された JSON を確認してコミットする。減少方向（既存 slug の削除）は
手動確認のこと（インデックス済みページの noindex 化は SEO 上の後退）。
"""
import csv
import glob
import json
import os
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GSC_DIR = os.path.join(ROOT, "analytics", "gsc")
OUT_PATH = os.path.join(ROOT, "normalize", "fa_gsc_proven_slugs.json")

MIN_IMPRESSIONS = 2
MIN_CLICKS = 1


def main():
    stats = {}  # slug -> [clicks, impressions]
    files = sorted(glob.glob(os.path.join(GSC_DIR, "*.csv")))
    for path in files:
        with open(path, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                page = row.get("page", "")
                if "/fish_area/" not in page:
                    continue
                slug = page.rsplit("/fish_area/", 1)[1].replace(".html", "").strip("/")
                if not slug:
                    continue
                s = stats.setdefault(slug, [0, 0])
                s[0] += int(row.get("clicks") or 0)
                s[1] += int(row.get("impressions") or 0)

    slugs = sorted(
        slug for slug, (c, i) in stats.items()
        if i >= MIN_IMPRESSIONS or c >= MIN_CLICKS
    )
    out = {
        "updated": date.today().isoformat(),
        "source": [os.path.basename(p) for p in files],
        "criteria": f"impressions>={MIN_IMPRESSIONS} or clicks>={MIN_CLICKS}",
        "slugs": slugs,
    }
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"対象: {len(slugs)}件 先頭3: {slugs[:3]}")
    print(f"→ {OUT_PATH}")


if __name__ == "__main__":
    main()
