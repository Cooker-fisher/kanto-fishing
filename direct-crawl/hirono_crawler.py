"""
hirono_crawler.py — ひろの丸 釣果サイト専用クローラー（chowari.jp 経由・Pattern α）

ソース: https://www.chowari.jp/ship/00941/catch/?page=N （HTMLスクレイプ）
出力:  direct-crawl/catches_raw_hirono.json（catches_raw.json 互換 + 拡張フィールド）

スキーマ:
    ship, area, date, trip_no, fish_raw, count_raw, size_raw, weight_raw,
    tokki_raw, point_raw, kanso_raw, suion_raw, suishoku_raw, color_raw,
    tide_label, weather_text, weather_detail (dict), source

ひろの丸HTML構造:
    <div class="catch_item_layout">                ← 1釣行（=1trip）
      <div class="catch_item_date">釣行日：...</div>
      <table class="catch_item_fish">
        <tr><th><h2>魚種</h2></th>  ← メイン魚種マーカー (h2 が付くものが主役)
            <td>大きさ</td><td>匹数</td></tr>
        <tr><th><span>魚種</span></th> ← 外道（数値空）
            <td></td><td></td></tr>
      </table>
      <p class="catch_item_comment_txt">Kansoテキスト</p>
    </div>

実行:
    python direct-crawl/hirono_crawler.py            # デフォルト: 直近7日のみ
    python direct-crawl/hirono_crawler.py --days 60  # 直近60日
    python direct-crawl/hirono_crawler.py --full     # 全ページ遡及（約26ヶ月・初回専用）
    python direct-crawl/hirono_crawler.py --dry-run  # 書き込みスキップ
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

sys.stdout.reconfigure(encoding="utf-8")

ROOT_DIR    = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_PATH    = os.path.join(ROOT_DIR, "direct-crawl", "catches_raw_hirono.json")
BASE_URL    = "https://www.chowari.jp/ship/00941/catch/"
SHIP_NAME   = "ひろの丸"
AREA_NAME   = "波崎港"
SOURCE      = "chowari/ひろの丸"
SLEEP_SEC   = 2.0
UA          = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
# 全ページ遡及時の上限（26ヶ月 ≈ chowari は1ページ約30件・実質 10〜15ページで底に届く）
FULL_PAGE_MAX = 50


def fetch_page(page: int) -> str:
    url = f"{BASE_URL}?page={page}" if page > 1 else BASE_URL
    req = Request(url, headers={"User-Agent": UA, "Accept-Language": "ja-JP,ja"})
    with urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", errors="replace")


# 釣行ブロックは catch_item_layout + 同日 catch_item_information を一体扱い
# catch_item_layout から次の catch_item_layout / footer / pagenation 直前まで
# catch_item_layout + 同日 catch_item_information を一体として切り出す
# (各釣行は catch_item_layout → catch_item_information の順で出現)
_RE_ITEM = re.compile(
    r'(<div class="catch_item_layout">.*?</div><!-- /catch_item_weather -->.*?)'
    r'(?=<div class="catch_item_layout">|<footer|<div class="common__main_pagenation)',
    re.DOTALL,
)
# 気象が無い日のフォールバック（layout単独）
_RE_ITEM_FALLBACK = re.compile(
    r'<div class="catch_item_layout">(.*?)(?=<div class="catch_item_layout">|<footer|<div class="common__main_pagenation)',
    re.DOTALL,
)
_RE_DATE = re.compile(r'<div class="catch_item_date">釣行日：(\d{4})年(\d{1,2})月(\d{1,2})日（[^）]*）([^<]*)</div>')
_RE_FISH_TABLE = re.compile(r'<table class="catch_item_fish">(.*?)</table>', re.DOTALL)
_RE_ROW = re.compile(r'<tr>\s*<th>(.*?)</th>\s*<td>(.*?)</td>\s*<td>(.*?)</td>\s*</tr>', re.DOTALL)
_RE_H2 = re.compile(r'<h2>([^<]+)</h2>')
_RE_SPAN = re.compile(r'<span>([^<]+)</span>')
_RE_COMMENT = re.compile(r'<p class="catch_item_comment_txt">(.*?)<span', re.DOTALL)
_RE_WEATHER_BLOCK = re.compile(
    r'<div class="catch_item_weather">(.*?)</div><!-- /catch_item_weather -->', re.DOTALL
)
_RE_WEATHER_LI = re.compile(r'<li class="([^"]+)">(.*?)</li>', re.DOTALL)
_RE_WEATHER_P = re.compile(r'<p>(.*?)</p>', re.DOTALL)
_RE_LOCATION = re.compile(r'<div class="catch_item_location">(.*?)</div>', re.DOTALL)
_RE_TAG = re.compile(r'<[^>]+>')


def _clean(s: str) -> str:
    s = unescape(s)
    s = _RE_TAG.sub("", s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s


def parse_weather(block_html: str) -> dict:
    """catch_item_weather 内の <li class="X"> から気象詳細を抽出"""
    if not block_html:
        return {}
    out = {}
    for li_m in _RE_WEATHER_LI.finditer(block_html):
        cls = li_m.group(1).split()[0]  # "weather weather_bg110" → "weather"
        inner = li_m.group(2)
        ps = _RE_WEATHER_P.findall(inner)
        # ps は通常 [label, value] または sunrise/moonrise は [label1, time1, label2, time2]
        if cls == "sunrise" and len(ps) >= 4:
            out["sunrise"] = _clean(ps[1])
            out["sunset"]  = _clean(ps[3])
        elif cls == "moonrise" and len(ps) >= 4:
            out["moonrise"] = _clean(ps[1])
            out["moonset"]  = _clean(ps[3])
        elif cls == "weather" and len(ps) >= 2:
            out["weather"] = _clean(ps[1])
        elif cls == "temperature" and len(ps) >= 2:
            # 値内に <span>23℃</span>/<span>15℃</span>
            spans = re.findall(r'<span>([^<]+)</span>', ps[1])
            if len(spans) >= 2:
                out["temp_high"] = _clean(spans[0])
                out["temp_low"]  = _clean(spans[1])
            else:
                out["temp"] = _clean(ps[1])
        elif cls == "pressure" and len(ps) >= 2:
            out["pressure"] = _clean(ps[1])
        elif cls == "wind" and len(ps) >= 2:
            # 値内に "北北西<br>2.9m/s" 形式
            raw_val = ps[1]
            parts = re.split(r'<br\s*/?>', raw_val)
            if len(parts) >= 2:
                out["wind_dir"]   = _clean(parts[0])
                out["wind_speed"] = _clean(parts[1])
            else:
                out["wind"] = _clean(raw_val)
        elif cls == "wave" and len(ps) >= 2:
            raw_val = ps[1]
            parts = re.split(r'<br\s*/?>', raw_val)
            if len(parts) >= 2:
                out["wave_dir"]    = _clean(parts[0])
                out["wave_height"] = _clean(parts[1])
            else:
                out["wave"] = _clean(raw_val)
        elif cls == "water_temperature" and len(ps) >= 2:
            out["water_temp"] = _clean(ps[1])
        elif cls == "tide" and len(ps) >= 2:
            out["tide"] = _clean(ps[1])
        elif cls == "moon" and len(ps) >= 2:
            out["moon_age"] = _clean(ps[1])
        elif cls == "bi" and len(ps) >= 2:
            out["bi"] = _clean(ps[1])
    return out


def parse_item(html_block: str, trip_no: int) -> list:
    """1つの catch_item_layout + catch_item_information ブロックから釣果レコード配列を返す"""
    m = _RE_DATE.search(html_block)
    if not m:
        return []
    y, mo, d, tide_header = m.group(1), m.group(2).zfill(2), m.group(3).zfill(2), m.group(4).strip()
    date_str = f"{y}/{mo}/{d}"

    fish_table_m = _RE_FISH_TABLE.search(html_block)
    if not fish_table_m:
        return []
    table_html = fish_table_m.group(1)

    comment_m = _RE_COMMENT.search(html_block)
    kanso = _clean(comment_m.group(1)) if comment_m else ""

    # 気象詳細ブロック
    weather_m = _RE_WEATHER_BLOCK.search(html_block)
    weather_detail = parse_weather(weather_m.group(1)) if weather_m else {}

    location_m = _RE_LOCATION.search(html_block)
    location = _clean(location_m.group(1)) if location_m else ""

    # 既存スキーマ列への分配
    suion = weather_detail.get("water_temp", "")
    weather_text = weather_detail.get("weather", "")
    # tide は気象ブロック側を優先（ヘッダの潮ラベルとは別物の可能性）
    tide_label = weather_detail.get("tide") or tide_header

    rows = []
    for row_m in _RE_ROW.finditer(table_html):
        th_html, size_td, count_td = row_m.group(1), row_m.group(2), row_m.group(3)
        h2 = _RE_H2.search(th_html)
        span = _RE_SPAN.search(th_html)
        if h2:
            fish_name = _clean(h2.group(1))
            is_main = True
        elif span:
            fish_name = _clean(span.group(1))
            is_main = False
        else:
            fish_name = _clean(th_html)
            is_main = False
        size_raw = _clean(size_td)
        count_raw = _clean(count_td)
        tokki = "メイン" if is_main else "外道"
        rows.append({
            # 既存 catches_raw.json と互換のスキーマ
            "ship": SHIP_NAME,
            "area": AREA_NAME,
            "date": date_str,
            "trip_no": trip_no,
            "fish_raw": fish_name,
            "count_raw": count_raw,
            "size_raw": size_raw,
            "weight_raw": "",
            "tokki_raw": tokki,
            "point_raw": location,
            "kanso_raw": kanso,
            "suion_raw": suion,
            "suishoku_raw": "",
            "color_raw": "",
            # データソース識別（catches_raw.json 統合後も取得元が分かる）
            "source": SOURCE,
            # 拡張フィールド（ひろの丸独自の海況Raw・後段はJSONから参照）
            "tide_label":     tide_label,           # 大潮/中潮/長潮/若潮 等
            "weather_text":   weather_text,         # 天気文字列
            "weather_detail": weather_detail,       # 詳細dict（sunrise/moon_age/bi/wind/wave 等15項目）
        })
    return rows


def _parse_date_to_obj(date_str: str):
    """'2026/04/26' → date オブジェクト"""
    try:
        return datetime.strptime(date_str, "%Y/%m/%d").date()
    except ValueError:
        return None


def crawl(page_max: int, cutoff_date=None) -> list:
    """ひろの丸の釣果を最大 page_max ページまで取得。
    cutoff_date が指定されたら、そのページに cutoff_date より古い日付のみ含まれた時点で打ち切り。
    """
    all_records = []
    seen_dates = {}  # date -> 当日の trip_no カウンタ
    for page in range(1, page_max + 1):
        print(f"  page={page} 取得中...", file=sys.stderr)
        html = fetch_page(page)
        items = _RE_ITEM.findall(html)
        if not items:
            items = _RE_ITEM_FALLBACK.findall(html)
        if not items:
            print(f"  page={page}: 釣行アイテム0件 → 終了", file=sys.stderr)
            break

        # このページに含まれる最新・最古日付を把握
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

        # cutoff_date より古いページしか含まれていなければ終了
        if cutoff_date and page_dates:
            page_max_date = max(_parse_date_to_obj(d) or date.min for d in page_dates)
            if page_max_date < cutoff_date:
                print(f"  page={page}: 全レコードが cutoff_date({cutoff_date}) より古い → 終了", file=sys.stderr)
                break
        time.sleep(SLEEP_SEC)
    return all_records


def filter_by_days(records: list, days: int) -> list:
    """date 列が今日から days 日以内のレコードのみ抽出"""
    cutoff = date.today() - timedelta(days=days)
    return [r for r in records if (_parse_date_to_obj(r["date"]) or date.min) >= cutoff]


def main():
    p = argparse.ArgumentParser(description="ひろの丸 chowari.jp クローラ")
    p.add_argument("--days", type=int, default=7,
                   help="直近N日のレコードのみ保持（デフォルト7日）")
    p.add_argument("--full", action="store_true",
                   help="全ページ遡及（約26ヶ月分・初回専用）")
    p.add_argument("--dry-run", action="store_true",
                   help="JSONファイルへの書き込みをスキップ")
    args = p.parse_args()

    if args.full:
        page_max = FULL_PAGE_MAX
        cutoff_date = None
        mode = f"--full (page_max={page_max})"
    else:
        # --days N の場合、ページ取得は cutoff_date でショートサーキット
        page_max = max(3, (args.days // 30) + 2)  # 余裕を持って取る
        cutoff_date = date.today() - timedelta(days=args.days)
        mode = f"--days {args.days} (cutoff={cutoff_date}, page_max={page_max})"

    print(f"=== ひろの丸クローラ (chowari.jp HTMLスクレイプ) ===")
    print(f"mode: {mode} dry_run={args.dry_run}")
    print(f"source: {SOURCE}")
    records = crawl(page_max, cutoff_date=cutoff_date)
    print(f"取得レコード数（フィルタ前）: {len(records)}")

    # --days N によるフィルタリング（--full の時はスキップ）
    if not args.full:
        records = filter_by_days(records, args.days)
        print(f"取得レコード数（直近{args.days}日フィルタ後）: {len(records)}")

    # 集計表示
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
    print(f"メイン魚種別件数 TOP10:")
    for f, n in main_fish.most_common(10):
        print(f"  {f}: {n}件")
    ara_count = sum(1 for r in records if r["fish_raw"] == "アラ")
    print(f"アラ釣果レコード（メイン+外道計）: {ara_count}件")

    if not args.dry_run:
        with open(OUT_PATH, "w", encoding="utf-8") as f:
            json.dump(records, f, ensure_ascii=False, indent=2)
        print(f"保存: {OUT_PATH}")
    else:
        print("(dry-run: 書き込みスキップ)")


if __name__ == "__main__":
    main()
