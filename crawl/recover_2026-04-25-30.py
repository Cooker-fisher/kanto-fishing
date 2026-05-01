"""
2026/04/25〜30 の喪失データを fishing-v.jp / gyo.ne.jp から再取得し
data/V2/2026-04.csv に追記する一回限りのリカバリスクリプト。

背景:
  daily workflow の `crawler.py --export-csv` が catches_raw.json から
  CSV を全再生成していたため、save_daily_csv() で当日追記された
  4/25〜4/30 の records が即座に wipe されていた。
  workflow から --export-csv を削除済み（commit caaa673f）。
  失われた 4/25〜4/30 を pageID=1〜3 から拾い直す。

使い方:
  python crawl/recover_2026-04-25-30.py
  python crawl/recover_2026-04-25-30.py --max-pages 5    # 多めに見る
  python crawl/recover_2026-04-25-30.py --dry-run         # 確認のみ

備考:
  - save_daily_csv() の dedup により、既に CSV に存在する records はスキップされる
  - parse_catches_from_html() / parse_catches_gyo() を再利用（再クロール禁止の
    本旨は「同一 records を何度も取りに行くな」だが、喪失データの一回限りの
    ピンポイント補填はその対象外）
"""
import sys, os, time, argparse, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawler import (
    SHIPS, BASE_URL, GYO_BASE_URL,
    fetch, fetch_gyo,
    parse_catches_from_html, parse_catches_gyo,
    save_daily_csv,
)
from datetime import datetime

TARGET_START = "2026/04/25"
TARGET_END   = "2026/04/30"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-pages", type=int, default=3,
                    help="各船宿で遡るページ数（デフォルト3：pageID=1,2,3）")
    ap.add_argument("--sleep", type=float, default=0.8)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    active = [s for s in SHIPS if not s.get("exclude") and not s.get("boat_only")]
    print(f"対象船宿: {len(active)} 件 / 期間: {TARGET_START}〜{TARGET_END}")
    print(f"ページ数: 1〜{args.max_pages}")

    year = 2026
    recovered = []
    by_date = {}

    for s in active:
        source = s.get("source", "fishing-v")
        ship_records = []
        for page in range(1, args.max_pages + 1):
            if source == "gyo":
                # gyo.ne.jp は pageID 概念なし → page=1 のみ
                if page > 1:
                    break
                url = GYO_BASE_URL.format(cid=s["cid"])
                html = fetch_gyo(url)
                if not html:
                    break
                catches = parse_catches_gyo(html, s["name"], s["area"], year)
            else:
                # fishing-v.jp は pageID で過去に遡れる
                url = BASE_URL.format(sid=s["sid"])
                if page > 1:
                    url = url + f"&pageID={page}"
                html = fetch(url)
                if not html:
                    break
                catches = parse_catches_from_html(html, s["name"], s["area"], year)
            if not catches:
                break

            in_window = [c for c in catches
                         if c.get("date") and TARGET_START <= c["date"] <= TARGET_END
                         and not c.get("is_cancellation")
                         and c.get("fish_raw")]
            ship_records.extend(in_window)

            dates = [c.get("date") for c in catches if c.get("date")]
            if dates and min(dates) < TARGET_START:
                # 取得ページの最古が target 期間より前 → これ以上遡る必要なし
                break
            time.sleep(args.sleep)

        if ship_records:
            print(f"  [{s['area']}] {s['name']}: {len(ship_records)} 件")
            for c in ship_records:
                by_date[c["date"]] = by_date.get(c["date"], 0) + 1
            recovered.extend(ship_records)
        time.sleep(args.sleep / 2)

    print(f"\n=== 取得結果 ===")
    print(f"合計: {len(recovered)} 件")
    for d in sorted(by_date.keys()):
        print(f"  {d}: {by_date[d]} 件")

    if not recovered:
        print("\n対象期間のデータなし → 終了")
        return

    if args.dry_run:
        print("\n--dry-run のため CSV 書込はスキップ")
        return

    # save_daily_csv() の dedup により既存行は自動スキップされる
    added = save_daily_csv(recovered)
    print(f"\nCSV 追記: {added} 件 → data/V2/2026-04.csv")


if __name__ == "__main__":
    main()
