#!/usr/bin/env python3
"""
crawl_history_raw.py - 過去釣果データを catches_raw.json に一括取得（Layer 1）

全船宿の全ページを遡り、catches_raw.json に差分追記する。
history_crawl.py と同じクロールロジックだが、出力先が CSV/history.json ではなく
catches_raw.json（Layer 1 生データ）になっている。

実行方法:
    python crawl_history_raw.py               # 全船宿
    python crawl_history_raw.py --skip-done   # 既取得日付が多い船宿をスキップ
"""
import os, sys, time, random, json
from datetime import datetime, timedelta
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import crawler

CUTOFF   = "2023/01/01"   # 取得下限（3年分・統計的推奨値）
MAX_PAGE = 300           # 上限ページ数（1船宿773件÷5件/page ≒ 155p → 余裕を持って300）
BASE_URL = "https://www.fishing-v.jp/choka/choka_detail.php?s={sid}&pageID={page}"


def sleep_page():
    time.sleep(random.uniform(0.8, 1.5))


def sleep_ship():
    time.sleep(random.uniform(4.0, 9.0))


def load_existing_ship_dates():
    """catches_raw.json から 船宿→日付セット のマップを返す（スキップ判定用）"""
    path = "catches_raw.json"
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        try:
            records = json.load(f)
        except Exception:
            return {}
    ship_dates = defaultdict(set)
    for r in records:
        ship_dates[r["ship"]].add(r["date"])
    return ship_dates


def crawl_ship_all_pages(ship, year):
    """1船宿の全ページを遡って取得し、catch レコードのリストを返す。"""
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
            break  # データなし = 最終ページ超え

        # カットオフより古いレコードは除外
        new_catches = [c for c in catches if c.get("date", "") >= CUTOFF]
        all_catches.extend(new_catches)

        # このページの最古日付がカットオフを超えたら終了
        dates_on_page = [c["date"] for c in catches if c.get("date")]
        if dates_on_page and min(dates_on_page) < CUTOFF:
            break

        # 同じ日付しか出てこない（ページ送りが止まった）なら終了
        page_dates = set(dates_on_page)
        if page_dates and page_dates.issubset(seen_dates):
            break
        seen_dates |= page_dates

        # 「次へ」リンクがなければ終了
        if "次</a>" not in html and ">次<" not in html:
            break

        sleep_page()

    return all_catches


def main():
    skip_done = "--skip-done" in sys.argv

    ships = [s for s in crawler.SHIPS if s.get("source", "fishing-v") == "fishing-v" and not s.get("exclude")]
    year  = datetime.now().year

    print(f"=== 過去データ取得 → catches_raw.json ===", flush=True)
    print(f"対象: {len(ships)}船宿（釣りビジョン）", flush=True)
    print(f"カットオフ: {CUTOFF}（3年分）", flush=True)
    print(f"開始: {datetime.now().strftime('%Y/%m/%d %H:%M:%S')}\n", flush=True)

    existing_ship_dates = load_existing_ship_dates() if skip_done else {}

    random.shuffle(ships)
    total_new = 0

    for i, ship in enumerate(ships, 1):
        name = ship["name"]
        area = ship["area"]

        # --skip-done: 既に20日分以上取得済みの船宿は省略
        if skip_done and len(existing_ship_dates.get(name, set())) >= 20:
            print(f"[{i:03d}/{len(ships)}] {area} {name} → スキップ（取得済み）", flush=True)
            continue

        print(f"[{i:03d}/{len(ships)}] {area} {name} ...", end=" ", flush=True)
        catches  = crawl_ship_all_pages(ship, year)
        print(f"{len(catches)}件 → ", end="", flush=True)
        added    = crawler.append_raw_json(catches)
        total_new += added

        if i < len(ships):
            sleep_ship()

    print(f"\n=== 完了 ===", flush=True)
    print(f"新規追記合計: {total_new}件", flush=True)
    print(f"終了: {datetime.now().strftime('%Y/%m/%d %H:%M:%S')}", flush=True)


if __name__ == "__main__":
    main()
