#!/usr/bin/env python3
"""
crawl_cancellations.py - 欠航データのみを差分追記（対象船宿を絞って実行）

前回クロールで「取得件数 > 追記件数」だった35船宿に限定して再クロール。
釣果レコードはdedup済みのためスキップ、欠航レコード（is_cancellation=True）のみ追記される。

実行方法:
    python crawl_cancellations.py
"""
import os, sys, time, random
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import crawler

CUTOFF   = "2023/01/01"
MAX_PAGE = 300
BASE_URL = "https://www.fishing-v.jp/choka/choka_detail.php?s={sid}&pageID={page}"

# 前回クロールで差分があった35船宿（取得件数 > 追記件数）
TARGET_SHIPS = {
    "釣船 五郎丸",
    "庄治郎丸",
    "第八幸松丸",
    "長崎屋",
    "たいぞう丸",
    "幸栄丸",
    "第三幸栄丸",
    "北山丸",
    "石田丸",
    "秀丸",
    "こなや丸",
    "博栄丸",
    "林遊船",
    "平安丸",
    "恒丸",
    "鶴丸",
    "明進丸",
    "勇盛丸",
    "明広丸",
    "幸丸",
    "船宿 まる八",
    "福よし丸",
    "仁徳丸",
    "吉久",
    "つる丸",
    "渡辺釣船店",
    "ふじや釣舟店",
    "日正丸",
    "ちがさき丸",
    "宮田丸",
    "喜平治丸",
    "伊達丸",
    "岩崎レンタルボート(岩崎つり具店)",
    "敷嶋丸",
    "龍正丸",
    "吉野屋",   # page13でタイムアウト→データ不足のため追加
}


def sleep_page():
    time.sleep(random.uniform(0.8, 1.2))


def sleep_ship():
    time.sleep(random.uniform(2.0, 4.0))


def crawl_ship_all_pages(ship, year):
    all_catches = []
    seen_dates  = set()

    for page in range(1, MAX_PAGE + 1):
        url  = BASE_URL.format(sid=ship["sid"], page=page)
        html = crawler.fetch(url)
        if not html:
            print(f"    page{page}: fetch失敗 → 打ち切り", flush=True)
            break

        catches = crawler.parse_catches_from_html(html, ship["name"], ship["area"], year)
        if not catches:
            break

        new_catches = [c for c in catches if c.get("date", "") >= CUTOFF]
        all_catches.extend(new_catches)

        dates_on_page = [c["date"] for c in catches if c.get("date")]
        if dates_on_page and min(dates_on_page) < CUTOFF:
            break

        page_dates = set(dates_on_page)
        if page_dates and page_dates.issubset(seen_dates):
            break
        seen_dates |= page_dates

        if "次</a>" not in html and ">次<" not in html:
            break

        sleep_page()

    return all_catches


def main():
    all_ships = [s for s in crawler.SHIPS if s.get("source", "fishing-v") == "fishing-v" and not s.get("exclude")]
    target    = [s for s in all_ships if s["name"] in TARGET_SHIPS]
    year      = datetime.now().year

    print(f"=== 欠航データ追記クロール ===", flush=True)
    print(f"対象: {len(target)}船宿（差分あり船宿のみ）", flush=True)
    print(f"カットオフ: {CUTOFF}（3年分）", flush=True)
    print(f"開始: {datetime.now().strftime('%Y/%m/%d %H:%M:%S')}\n", flush=True)

    random.shuffle(target)
    total_new = 0

    for i, ship in enumerate(target, 1):
        print(f"[{i:03d}/{len(target)}] {ship['area']} {ship['name']} ...", end=" ", flush=True)
        catches  = crawl_ship_all_pages(ship, year)
        print(f"{len(catches)}件 → ", end="", flush=True)
        added    = crawler.append_raw_json(catches)
        total_new += added

        if i < len(target):
            sleep_ship()

    print(f"\n=== 完了 ===", flush=True)
    print(f"新規追記合計: {total_new}件（欠航レコード）", flush=True)
    print(f"終了: {datetime.now().strftime('%Y/%m/%d %H:%M:%S')}", flush=True)


if __name__ == "__main__":
    main()
