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
import random
from datetime import date, datetime, timedelta
from html import unescape
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

# hirono_crawler.py からパーサー群を import 流用
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hirono_crawler import (
    parse_item, parse_weather,
    _RE_ITEM, _RE_ITEM_FALLBACK, _RE_DATE,
    SLEEP_SEC, UA, FULL_PAGE_MAX,
    _parse_date_to_obj, filter_by_days,
)

# === 検知対策強化 (2026-05-23 ユーザー指示) ===
# 1. SLEEP ランダム化 (機械的な等間隔を排除)
SLEEP_MIN = 3.0
SLEEP_MAX = 5.0

# 2. 隻間 wait ランダム化
SHIP_INTERVAL_MIN = 8.0
SHIP_INTERVAL_MAX = 15.0

# 3. UA ローテーション (一般的ブラウザの実在 UA を複数用意)
UA_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:131.0) Gecko/20100101 Firefox/131.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
]

# 4. リトライ設定
RETRY_MAX = 2
RETRY_BACKOFF_SEC = 30.0

def _rand_sleep(mn=SLEEP_MIN, mx=SLEEP_MAX):
    """ランダム sleep (検知対策)"""
    time.sleep(random.uniform(mn, mx))

def _pick_ua():
    """UA をランダム選択"""
    return random.choice(UA_POOL)

sys.stdout.reconfigure(encoding="utf-8")

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def fetch_page_chowari(chowari_id: str, page: int = 1, dt: str = None) -> str:
    """chowari.jp /ship/{id}/catch/ を取得。
    dt が指定されていれば ?dt=YYMM 形式で過去月にアクセス可能 (chowari.jp 公式 UI が使う形式)。
    dt 無しの場合は最新60日の page-based 表示。

    検知対策:
    - UA ローテーション (UA_POOL からランダム)
    - Referer (前ページから来たフリ)
    - リトライ + 指数バックオフ (拒否時)
    - 注: Accept-Encoding は付けない (urllib は自動解凍しないため gzip 文字化けする)
    """
    base = f"https://www.chowari.jp/ship/{chowari_id}/catch/"
    if dt:
        url = f"{base}?dt={dt}" + (f"&page={page}" if page > 1 else "")
    elif page > 1:
        url = f"{base}?page={page}"
    else:
        url = base

    last_err = None
    for attempt in range(RETRY_MAX + 1):
        headers = {
            "User-Agent": _pick_ua(),  # 毎回ランダム UA
            "Accept-Language": "ja-JP,ja;q=0.9,en;q=0.8",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Referer": base if page > 1 or dt else "https://www.chowari.jp/",
            "DNT": "1",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "same-origin" if (page > 1 or dt) else "none",
        }
        req = Request(url, headers=headers)
        try:
            with urlopen(req, timeout=30) as r:
                return r.read().decode("utf-8", errors="replace")
        except (URLError, HTTPError, TimeoutError) as e:
            last_err = e
            if attempt < RETRY_MAX:
                # 指数バックオフ: 30秒, 60秒
                backoff = RETRY_BACKOFF_SEC * (2 ** attempt)
                print(f"  [retry] {url} attempt {attempt+1} failed ({e}), waiting {backoff}s", file=sys.stderr)
                time.sleep(backoff)
            else:
                raise
    if last_err:
        raise last_err


def crawl_ship(ship_name: str, chowari_id: str, area_name: str,
               page_max: int, cutoff_date=None, months_back: int = 0) -> list:
    """指定船宿の釣果を取得。hirono_crawler.parse_item を流用するため、
    一時的にモジュールグローバルの SHIP_NAME/AREA_NAME/SOURCE を差し替える。

    months_back > 0 の場合: ?dt=YYMM 形式で今月から months_back ヶ月分を遡及取得。
    chowari.jp 公式 UI と同じアクセスパターンで、page-based では届かない過去2年程度のデータも取れる。
    """
    import hirono_crawler as hc
    original = (hc.SHIP_NAME, hc.AREA_NAME, hc.SOURCE)
    hc.SHIP_NAME = ship_name
    hc.AREA_NAME = area_name
    hc.SOURCE    = f"chowari/{ship_name}"
    try:
        all_records = []
        seen_dates = {}

        def _process_html(html, ship_name, seen_dates_dict, all_records_list):
            """HTML をパースして records に追加。アイテム数を返す"""
            items = _RE_ITEM.findall(html)
            if not items:
                items = _RE_ITEM_FALLBACK.findall(html)
            if not items:
                return 0
            for item_html in items:
                date_m = _RE_DATE.search(item_html)
                if not date_m:
                    continue
                date_str = f"{date_m.group(1)}/{date_m.group(2).zfill(2)}/{date_m.group(3).zfill(2)}"
                seen_dates_dict[date_str] = seen_dates_dict.get(date_str, 0) + 1
                trip_no = seen_dates_dict[date_str]
                rows = parse_item(item_html, trip_no)
                all_records_list.extend(rows)
            return len(items)

        if months_back > 0:
            # 月別アクセスモード: ?dt=YYMM で過去N月分
            # 終了条件: 返ってきたレコードの日付が target 月より「新しい」場合
            # = 過去データ枯渇で chowari が最新を返している → 船宿打ち切り
            today = date.today()
            for delta in range(months_back):
                y = today.year
                m = today.month - delta
                while m <= 0:
                    m += 12
                    y -= 1
                dt = f"{y % 100:02d}{m:02d}"
                target_ym = (y, m)
                # ページネーション無し: 月ごとに page=1 のみ (chowari の月別UIは1ページに全件)
                print(f"  [{ship_name}] dt={dt} (={y}/{m:02d}) 取得中...", file=sys.stderr)
                try:
                    html = fetch_page_chowari(chowari_id, page=1, dt=dt)
                except Exception as e:
                    print(f"  [{ship_name}] dt={dt} fetch error: {e}", file=sys.stderr)
                    _rand_sleep()
                    continue
                # 取得日付を確認: target 月より新しい年月のレコードがあれば「過去データ枯渇」
                items = _RE_ITEM.findall(html)
                if not items:
                    items = _RE_ITEM_FALLBACK.findall(html)
                if not items:
                    print(f"  [{ship_name}] dt={dt}: 0件 → 船宿打ち切り", file=sys.stderr)
                    _rand_sleep()
                    break
                # 取得 items の最初の日付を確認
                first_ym = None
                for item_html in items:
                    date_m = _RE_DATE.search(item_html)
                    if date_m:
                        first_ym = (int(date_m.group(1)), int(date_m.group(2)))
                        break
                if first_ym and first_ym > target_ym:
                    # target より新しい年月が返った → 過去データ枯渇
                    print(f"  [{ship_name}] dt={dt}: 最新({first_ym[0]}/{first_ym[1]:02d}) が返った → 過去データ枯渇・船宿打ち切り", file=sys.stderr)
                    _rand_sleep()
                    break
                # 正常: target 月以内のレコード → 集計に追加
                n = _process_html(html, ship_name, seen_dates, all_records)
                print(f"  [{ship_name}] dt={dt}: {n}件", file=sys.stderr)
                _rand_sleep()
        else:
            # 既存 page-based モード (最新60日)
            for page in range(1, page_max + 1):
                print(f"  [{ship_name}] page={page} 取得中...", file=sys.stderr)
                html = fetch_page_chowari(chowari_id, page=page)
                n_before = len(all_records)
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
                _rand_sleep()
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
    p.add_argument("--months", type=int, default=0,
                   help="?dt=YYMM で過去N月分を遡及取得（最大約24ヶ月・chowari の月別UI流用）")
    p.add_argument("--dry-run", action="store_true",
                   help="JSON書き込みをスキップ")
    args = p.parse_args()

    if args.months > 0:
        # 月別モード: --days/--full の cutoff/page_max は無効
        page_max = 0
        cutoff_date = None
    elif args.full:
        page_max = FULL_PAGE_MAX
        cutoff_date = None
    else:
        page_max = max(3, (args.days // 30) + 2)
        cutoff_date = date.today() - timedelta(days=args.days)

    if args.from_ships_json:
        targets = load_chowari_ships()
        print(f"=== ships.json から chowari_id 持つ船宿: {len(targets)}件 ===")
        # 検知対策: 隻間 3秒 wait (一括処理時)
        for i, s in enumerate(targets):
            if i > 0:
                _rand_sleep(SHIP_INTERVAL_MIN, SHIP_INTERVAL_MAX)
            print(f"\n--- [{i+1}/{len(targets)}] {s['name']} (chowari_id={s['chowari_id']}, area={s.get('area','')}) ---")
            try:
                records = crawl_ship(s["name"], s["chowari_id"], s.get("area",""),
                                      page_max, cutoff_date, months_back=args.months)
                if not args.full and args.months == 0:
                    records = filter_by_days(records, args.days)
                print(f"  取得: {len(records)}件")
                save_records(records, s["name"], args.dry_run)
            except Exception as e:
                # 1隻失敗で全体停止しない
                print(f"  [ERROR] {s['name']}: {e}")
                continue
        return

    if not (args.ship and args.chowari_id and args.area):
        p.error("--ship / --chowari-id / --area の3点指定が必須（--from-ships-json 使用時は不要）")

    print(f"=== chowari クローラ: {args.ship} (chowari_id={args.chowari_id}, area={args.area}) ===")
    print(f"mode: days={args.days} full={args.full} months={args.months} dry_run={args.dry_run}")
    records = crawl_ship(args.ship, args.chowari_id, args.area, page_max, cutoff_date, months_back=args.months)
    if not args.full and args.months == 0:
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
