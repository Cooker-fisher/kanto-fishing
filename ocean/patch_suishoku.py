"""
patch_suishoku.py

catches_raw.json の各レコードに color_raw フィールドを追加する。
div.color の生テキストをそのまま格納するだけ。パースはしない。
他の既存フィールドは一切変更しない。

使い方:
  python ocean/patch_suishoku.py --dry-run          # 件数確認のみ
  python ocean/patch_suishoku.py --ship 喜平治丸    # 1船宿だけ
  python ocean/patch_suishoku.py                    # 全対象船宿
"""

import json, re, sys, time, os, argparse
from urllib.request import urlopen, Request
from collections import defaultdict

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CATCHES_PATH = os.path.join(BASE, "crawl", "catches_raw.json")
SHIPS_PATH   = os.path.join(BASE, "crawl", "ships.json")

SLEEP = 0.8
UA    = "Mozilla/5.0"


def fetch_html(sid, page_id):
    url = f"https://www.fishing-v.jp/choka/choka_detail.php?s={sid}&pageID={page_id}"
    req = Request(url, headers={"User-Agent": UA})
    try:
        return urlopen(req, timeout=15).read().decode("utf-8", errors="replace")
    except Exception as e:
        print(f"  fetch error page={page_id}: {e}")
        return ""


def parse_date_from_box(box_html):
    m = re.search(r'<li[^>]+class="date"[^>]*>(\d{4})年(\d{1,2})月(\d{1,2})日', box_html)
    if m:
        return f"{m.group(1)}/{int(m.group(2)):02d}/{int(m.group(3)):02d}"
    return None


def extract_color_raw(box_html):
    """div.color の中身を生テキストとして返す。タグだけ除去、内容は加工しない。"""
    m = re.search(r'<div[^>]+class="color"[^>]*>([\s\S]*?)</div>', box_html)
    if not m:
        return None
    text = re.sub(r"<[^>]+>", "", m.group(1))  # タグだけ除去
    text = re.sub(r"\s+", " ", text).strip()    # 連続空白を1つに
    return text if text else None


def split_boxes(html):
    starts = [m.start() for m in re.finditer(r'<div[^>]+class="[^"]*choka_box[^"]*"', html)]
    boxes = []
    for i, s in enumerate(starts):
        e = starts[i + 1] if i + 1 < len(starts) else len(html)
        boxes.append(html[s:e])
    return boxes


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--ship", default="")
    args = parser.parse_args()

    with open(CATCHES_PATH, encoding="utf-8") as f:
        data = json.load(f)

    with open(SHIPS_PATH, encoding="utf-8") as f:
        ships = json.load(f)
    sid_map = {s["name"]: s["sid"] for s in ships if s.get("sid")}

    # color_raw が未設定のレコードを船宿×date でインデックス化
    need_update = defaultdict(list)
    for i, r in enumerate(data):
        if r.get("color_raw") is None and not r.get("is_cancellation"):
            need_update[(r["ship"], r["date"])].append(i)

    ships_todo = sorted(set(k[0] for k in need_update))
    if args.ship:
        ships_todo = [s for s in ships_todo if s == args.ship]

    print(f"対象船宿: {len(ships_todo)}件")
    total_updated = 0

    for ship in ships_todo:
        sid = sid_map.get(ship)
        if not sid:
            print(f"[SKIP] {ship}: sid 不明")
            continue

        dates_needed = set(d for (s, d) in need_update if s == ship)
        print(f"\n{ship}(sid={sid}): {len(dates_needed)}日分")

        updated_ship = 0
        page_id = 1
        consecutive_empty = 0

        while dates_needed and consecutive_empty < 3:
            html = fetch_html(sid, page_id)
            if not html:
                consecutive_empty += 1
                page_id += 1
                time.sleep(SLEEP)
                continue

            boxes = split_boxes(html)
            if not boxes:
                consecutive_empty += 1
                page_id += 1
                time.sleep(SLEEP)
                continue

            consecutive_empty = 0
            page_hit = 0

            for box in boxes:
                date = parse_date_from_box(box)
                if not date or date not in dates_needed:
                    continue

                color_raw = extract_color_raw(box)
                idxs = need_update.get((ship, date), [])

                for idx in idxs:
                    if not args.dry_run:
                        # color_raw だけ追加。他フィールドは一切触らない
                        data[idx]["color_raw"] = color_raw
                    updated_ship += 1
                    page_hit += 1

                dates_needed.discard(date)

            print(f"  page={page_id}: {page_hit}件")
            page_id += 1
            time.sleep(SLEEP)

        print(f"  → {ship}: 計{updated_ship}件{'（dry-run）' if args.dry_run else ''}")
        total_updated += updated_ship

    print(f"\n合計: {total_updated}件")

    if not args.dry_run and total_updated > 0:
        with open(CATCHES_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
        print(f"保存: {CATCHES_PATH}")


if __name__ == "__main__":
    main()
