#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""GSC 実績のある fish_area slug リストを生成する（2026/07/12 SEO）。

analytics/gsc/pages/*.csv（fetch_gsc.py が毎日蓄積・**ページ次元**）から
/fish_area/ ページの表示・クリック実績を集計し、閾値を超えた slug を
normalize/fa_gsc_proven_slugs.json に書き出す。

⚠ 2026-09-03: 参照先を gsc/*.csv（クエリ次元）から gsc/pages/*.csv に変えた。
   クエリ次元は GSC の匿名化で click の約 1/3 しか含まず、露出痕跡のある
   fish_area slug を 75本しか拾えていなかった（ページ次元では 574本）。
   「実需要が証明されたページを noindex で殺さない」という本機構の目的に対し、
   証拠側が 1/8 に欠けていた。
   同時に閾値を impressions>=2 → **clicks>=1 or impressions>=10** に上げた。
   真値で impr>=2 を適用すると 451 slug が該当し、AdSense「有用性の低い
   コンテンツ」対策として付けた noindex がほぼ無力化されるため。
   新基準で復帰するのは 46本（実績 384impr / 39click ＝ CTR 10.2%）で、
   「実需要が証明された」と言える水準だけが通る。

crawler.py の build_fish_area_pages() はこの JSON を読み、収載 slug を
hist 閾値（_FA_NOINDEX_HIST_THRESHOLD=80）未満でも index 復帰させる。
検索需要が実際に観測されたページを noindex で殺さないための機構。

実行（月1・GSC CSV 更新後）:
    python analytics/build_fa_gsc_slugs.py
生成された JSON を確認してコミットする。減少方向（既存 slug の削除）は
手動確認のこと（インデックス済みページの noindex 化は SEO 上の後退）。
"""
import argparse
import csv
import glob
import json
import os
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GSC_DIR = os.path.join(ROOT, "analytics", "gsc", "pages")
OUT_PATH = os.path.join(ROOT, "normalize", "fa_gsc_proven_slugs.json")

# clicks>=1 or impressions>=MIN_IMPRESSIONS。ページ次元＝真値に合わせた水準。
MIN_IMPRESSIONS = 10
MIN_CLICKS = 1
# True にすると既存 slug の削除を許す（＝インデックス済みページの noindex 化）。
# 既定 False。--allow-shrink で上書きする。
ALLOW_SHRINK = False


def main():
    global ALLOW_SHRINK
    ap = argparse.ArgumentParser()
    ap.add_argument("--allow-shrink", action="store_true",
                    help="既存 slug の削除を許す（インデックス済みページの noindex 化）")
    ALLOW_SHRINK = ap.parse_args().allow_shrink

    stats = {}  # slug -> [clicks, impressions]
    files = sorted(glob.glob(os.path.join(GSC_DIR, "*.csv")))
    if not files:
        raise SystemExit(
            f"ページ次元 CSV が無い: {GSC_DIR}"
            + chr(10) + "  python analytics/fetch_gsc.py --days 130 でバックフィルする。"
            + chr(10) + "  クエリ次元（analytics/gsc/*.csv）で代用しないこと"
            "（匿名化で露出痕跡が 1/8 に欠ける）")
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

    qualified = {slug for slug, (c, i) in stats.items()
                 if i >= MIN_IMPRESSIONS or c >= MIN_CLICKS}

    # 既存 slug は落とさない（単調増加）。
    # docstring は当初から「減少方向は手動確認のこと」と書いていたが、機構が無く
    # 人の記憶に頼っていた。閾値を上げた 2026-09-03 に実際 3 slug
    # （hanadai-kuryo / kihada-maguro-hiratsuka / madako-koshiba）が落ちかけた。
    # インデックス済みページを noindex に戻すのは SEO 上の純粋な後退で、
    # 取り戻すのに再クロール待ちが要る。落とすなら --allow-shrink を明示する。
    prev = set()
    if os.path.isfile(OUT_PATH):
        try:
            prev = set(json.load(open(OUT_PATH, encoding="utf-8")).get("slugs", []))
        except Exception:
            prev = set()
    dropped = sorted(prev - qualified)
    if dropped and not ALLOW_SHRINK:
        print(f"[keep] 新基準では外れるが既存なので残す {len(dropped)} 件: {dropped[:5]}")
    slugs = sorted(qualified if ALLOW_SHRINK else (qualified | prev))
    out = {
        "updated": date.today().isoformat(),
        "source": ["pages/" + os.path.basename(p) for p in files],
        "dimension": "date+page（ページ次元＝真値。クエリ次元は匿名化で欠測する）",
        "criteria": f"impressions>={MIN_IMPRESSIONS} or clicks>={MIN_CLICKS}",
        "slugs": slugs,
    }
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"対象: {len(slugs)}件 先頭3: {slugs[:3]}"
          f"（新基準該当 {len(qualified)} / 既存維持 {len(prev - qualified)}）")
    print(f"→ {OUT_PATH}")


if __name__ == "__main__":
    main()
