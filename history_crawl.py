#!/usr/bin/env python3
"""
history_crawl.py - 過去データ一括取得

crawler.py の fetch / parse_catches_from_html / parse_catches_gyo / save_daily_csv を
そのまま使い、pageID を増やしながら過去ページを取得して data/YYYY-MM.csv に追記する。

日次クロール（crawler.py）との違い:
  - pageID=1 だけでなく pageID=2, 3, ... と遡る
  - 2年前より古い日付が出たら打ち切り
  - ページ間・船宿間にランダムスリープ（stealth）

実行方法:
  python history_crawl.py
"""
import os, sys, time, random
from datetime import datetime, timedelta

# crawler.py の関数をそのまま借用
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import crawler

CUTOFF = (datetime.now() - timedelta(days=365 * 2)).strftime("%Y/%m/%d")
BASE_URL = "https://www.fishing-v.jp/choka/choka_detail.php?s={sid}&pageID={page}"


def sleep_page():
    time.sleep(random.uniform(1.5, 3.0))


def sleep_ship():
    time.sleep(random.uniform(5.0, 12.0))


def crawl_ship_history(ship, year):
    """
    1船宿の全ページを遡って取得し、catch レコードのリストを返す。
    crawler.py の parse_catches_from_html をそのまま使う。
    """
    all_catches = []
    seen_dates = set()

    for page in range(1, 100):
        url = BASE_URL.format(sid=ship["sid"], page=page)
        html = crawler.fetch(url)
        if not html:
            print(f"    page{page}: fetch失敗 → 打ち切り")
            break

        catches = crawler.parse_catches_from_html(html, ship["name"], ship["area"], year)
        if not catches:
            break  # データなし = 最終ページ超え

        # カットオフより古いレコードを除外
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
    fv_ships  = [s for s in crawler.SHIPS if s.get("source", "fishing-v") == "fishing-v"]
    gyo_ships = [s for s in crawler.SHIPS if s.get("source") == "gyo"]
    year = datetime.now().year

    print(f"=== 過去データ取得 ===")
    print(f"釣りビジョン: {len(fv_ships)}船宿 / gyo.ne.jp: {len(gyo_ships)}船宿")
    print(f"カットオフ: {CUTOFF}（2年前）")
    print(f"開始: {datetime.now().strftime('%Y/%m/%d %H:%M:%S')}\n")

    all_catches = []

    # ── 釣りビジョン ──────────────────────────────────────────────
    random.shuffle(fv_ships)
    for i, ship in enumerate(fv_ships, 1):
        print(f"[FV {i:03d}/{len(fv_ships)}] {ship['area']} {ship['name']} ...", end=" ", flush=True)
        catches = crawl_ship_history(ship, year)
        all_catches.extend(catches)
        print(f"{len(catches)} 件")

        # 20船宿ごとに中間保存
        if i % 20 == 0:
            added = crawler.save_daily_csv(all_catches)
            crawler.update_history(all_catches, crawler.load_history())
            print(f">>> 中間保存: {added}件追記")

        if i < len(fv_ships):
            sleep_ship()

    # ── gyo.ne.jp ──────────────────────────────────────────────────
    # gyo は1ページ=1日なので crawler.py と同じ fetch + parse で全日分取得済み
    random.shuffle(gyo_ships)
    for i, ship in enumerate(gyo_ships, 1):
        print(f"[GYO {i:03d}/{len(gyo_ships)}] {ship['area']} {ship['name']} ...", end=" ", flush=True)
        url  = crawler.GYO_BASE_URL.format(cid=ship["cid"])
        html = crawler.fetch_gyo(url)
        if not html:
            print("エラー")
            continue
        catches = crawler.parse_catches_gyo(html, ship["name"], ship["area"], year)
        catches = [c for c in catches if c.get("date", "") >= CUTOFF]
        all_catches.extend(catches)
        print(f"{len(catches)} 件")

        if i % 10 == 0:
            added = crawler.save_daily_csv(all_catches)
            print(f">>> 中間保存: {added}件追記")

        if i < len(gyo_ships):
            sleep_ship()

    # ── 最終保存 ──────────────────────────────────────────────────
    csv_added = crawler.save_daily_csv(all_catches)
    history = crawler.load_history()
    crawler.update_history(all_catches, history)

    print(f"\n=== 完了 ===")
    print(f"取得レコード: {len(all_catches)} 件")
    print(f"CSV追記: {csv_added} 件 → data/")
    print(f"終了: {datetime.now().strftime('%Y/%m/%d %H:%M:%S')}")


if __name__ == "__main__":
    main()
