"""
chowari_crawler.py — chowari.jp 汎用クローラー（B群18船宿への流用基盤）

hirono_crawler.py を引数化して任意の船宿に対応:
    python direct-crawl/chowari_crawler.py --ship "船宿名" --chowari-id "00941" --area "波崎港" [--days 7]

設計:
    chowari.jp の URL 構造は /ship/{chowari_id}/catch/ で統一。
    HTML 構造（catch_item_layout / catch_item_fish / catch_item_weather）も
    船宿によらず同一なので、hirono_crawler.py のパーサーをそのまま流用可能。

    出力ファイルは船宿別: direct-crawl/catches_raw_chowari_{slug}.json
    （catches_raw_hirono.json と並立）

ships.json 連携:
    --from-ships-json オプションで chowari_id を持つ船宿全件を一括処理。
    各船宿の出力ファイルが個別生成される。

実行例:
    # 単一船宿
    python direct-crawl/chowari_crawler.py --ship "政勝丸" --chowari-id "01495" --area "外川港"

    # ships.json から chowari_id を持つ全船宿
    python direct-crawl/chowari_crawler.py --from-ships-json --days 7

    # 既存ひろの丸を chowari 汎用化版で取り直す（動作確認）
    python direct-crawl/chowari_crawler.py --ship "ひろの丸" --chowari-id "00941" --area "波崎港" --days 7
"""

import argparse
import json
import os
import re
import sys
import time
from datetime import date, datetime, timedelta
from html import unescape
from urllib.request import Request, urlopen

# hirono_crawler.py からパーサー群を import 流用
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hirono_crawler import (
    parse_item, parse_weather,
    _RE_ITEM, _RE_ITEM_FALLBACK, _RE_DATE,
    SLEEP_SEC, UA, FULL_PAGE_MAX,
    _parse_date_to_obj, filter_by_days,
)

sys.stdout.reconfigure(encoding="utf-8")

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def fetch_page_chowari(chowari_id: str, page: int) -> str:
    """chowari.jp /ship/{id}/catch/?page=N を取得"""
    base = f"https://www.chowari.jp/ship/{chowari_id}/catch/"
    url  = f"{base}?page={page}" if page > 1 else base
    req  = Request(url, headers={"User-Agent": UA, "Accept-Language": "ja-JP,ja"})
    with urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", errors="replace")


def crawl_ship(ship_name: str, chowari_id: str, area_name: str,
               page_max: int, cutoff_date=None) -> list:
    """指定船宿の釣果を取得。hirono_crawler.parse_item を流用するため、
    一時的にモジュールグローバルの SHIP_NAME/AREA_NAME/SOURCE を差し替える。"""
    import hirono_crawler as hc
    original = (hc.SHIP_NAME, hc.AREA_NAME, hc.SOURCE)
    hc.SHIP_NAME = ship_name
    hc.AREA_NAME = area_name
    hc.SOURCE    = f"chowari/{ship_name}"
    try:
        all_records = []
        seen_dates = {}
        for page in range(1, page_max + 1):
            print(f"  [{ship_name}] page={page} 取得中...", file=sys.stderr)
            html = fetch_page_chowari(chowari_id, page)
            items = _RE_ITEM.findall(html)
            if not items:
                items = _RE_ITEM_FALLBACK.findall(html)
            if not items:
                print(f"  [{ship_name}] page={page}: 0件 → 終了", file=sys.stderr)
                break
            page_dates = []
            for item_html in items:
                date_m = _RE_DATE.search(item_html)
                if not date_m:
                    continue
                date_str = f"{date_m.group(1)}/{date_m.group(2).zfill(2)}/{date_m.group(3).zfill(2)}"
                page_dates.append(date_str)
                seen_dates[date_str] = seen_dates.get(date_str, 0) + 1
                trip_no = seen_dates[date_str]
                rows = parse_item(item_html, trip_no)
                all_records.extend(rows)
            if cutoff_date and page_dates:
                page_max_date = max(_parse_date_to_obj(d) or date.min for d in page_dates)
                if page_max_date < cutoff_date:
                    print(f"  [{ship_name}] page={page}: cutoff_date {cutoff_date} より古い → 終了",
                          file=sys.stderr)
                    break
            time.sleep(SLEEP_SEC)
        return all_records
    finally:
        hc.SHIP_NAME, hc.AREA_NAME, hc.SOURCE = original


def romaji_slug(name: str) -> str:
    """船宿名から出力ファイル名用の slug を生成。ships.json の romaji_slug があれば優先。"""
    # ASCII safe な簡易 fallback
    return re.sub(r'[^\w-]', '_', name)


def save_records(records: list, ship_name: str, dry_run: bool):
    """直接 catches_raw_chowari_{slug}.json に保存"""
    slug = None
    try:
        with open(os.path.join(ROOT_DIR, "crawl", "ships.json"), encoding="utf-8") as f:
            for s in json.load(f):
                if s.get("name") == ship_name:
                    slug = s.get("romaji_slug")
                    break
    except Exception:
        pass
    if not slug:
        slug = romaji_slug(ship_name)
    out_path = os.path.join(ROOT_DIR, "direct-crawl", f"catches_raw_chowari_{slug}.json")
    if dry_run:
        print(f"  (dry-run) {len(records)}件 → {out_path} 書き込みスキップ")
        return out_path
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)
    print(f"  保存: {out_path} ({len(records)}件)")
    return out_path


def load_chowari_ships() -> list:
    """ships.json から「source_priority に chowari を含み chowari_id を持つ」船宿一覧を返す。
    既存 181 船宿（釣りビジョン経由・source_priority未設定）は対象外。
    B群として明示登録した船宿のみが対象になる。"""
    with open(os.path.join(ROOT_DIR, "crawl", "ships.json"), encoding="utf-8") as f:
        ships = json.load(f)
    return [s for s in ships
            if s.get("chowari_id")
            and "chowari" in (s.get("source_priority") or [])
            and not s.get("exclude") and not s.get("boat_only")]


def main():
    p = argparse.ArgumentParser(description="chowari.jp 汎用クローラー")
    p.add_argument("--ship",        help="船宿名（例: 政勝丸）")
    p.add_argument("--chowari-id",  help="chowari.jp の船宿ID（例: 01495）")
    p.add_argument("--area",        help="エリア名（例: 外川港）")
    p.add_argument("--from-ships-json", action="store_true",
                   help="ships.json の chowari_id 持つ全船宿を一括処理")
    p.add_argument("--days", type=int, default=7,
                   help="直近N日のみ保持（デフォルト7日）")
    p.add_argument("--full", action="store_true",
                   help="全ページ遡及（約60日上限・chowari制約）")
    p.add_argument("--dry-run", action="store_true",
                   help="JSON書き込みをスキップ")
    args = p.parse_args()

    if args.full:
        page_max = FULL_PAGE_MAX
        cutoff_date = None
    else:
        page_max = max(3, (args.days // 30) + 2)
        cutoff_date = date.today() - timedelta(days=args.days)

    if args.from_ships_json:
        targets = load_chowari_ships()
        print(f"=== ships.json から chowari_id 持つ船宿: {len(targets)}件 ===")
        for s in targets:
            print(f"\n--- {s['name']} (chowari_id={s['chowari_id']}, area={s.get('area','')}) ---")
            records = crawl_ship(s["name"], s["chowari_id"], s.get("area",""),
                                  page_max, cutoff_date)
            if not args.full:
                records = filter_by_days(records, args.days)
            print(f"  取得: {len(records)}件")
            save_records(records, s["name"], args.dry_run)
        return

    if not (args.ship and args.chowari_id and args.area):
        p.error("--ship / --chowari-id / --area の3点指定が必須（--from-ships-json 使用時は不要）")

    print(f"=== chowari クローラ: {args.ship} (chowari_id={args.chowari_id}, area={args.area}) ===")
    print(f"mode: days={args.days} full={args.full} dry_run={args.dry_run}")
    records = crawl_ship(args.ship, args.chowari_id, args.area, page_max, cutoff_date)
    if not args.full:
        records = filter_by_days(records, args.days)
    print(f"取得レコード数: {len(records)}件")

    from collections import Counter, defaultdict
    by_date = defaultdict(list)
    for r in records:
        by_date[r["date"]].append(r)
    print(f"釣行日数: {len(by_date)}")
    if by_date:
        print(f"期間: {min(by_date)} 〜 {max(by_date)}")
    main_fish = Counter()
    for r in records:
        if r.get("tokki_raw") == "メイン":
            main_fish[r["fish_raw"]] += 1
    print("メイン魚種 TOP10:")
    for f, n in main_fish.most_common(10):
        print(f"  {f}: {n}件")

    save_records(records, args.ship, args.dry_run)


if __name__ == "__main__":
    main()
