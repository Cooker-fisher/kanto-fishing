"""
特定船宿の過去データを全ページ取得して catches_raw.json に追記するスクリプト。
V2形式（count_raw, kanso_raw, point_raw 等）で保存する。

使い方:
  python crawl/history_crawl_single.py --sid 146 --name 吉野屋 --area 浦安
  python crawl/history_crawl_single.py --sid 146 --name 吉野屋 --area 浦安 --max-pages 50
"""
import sys, os, json, time, argparse
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawler import fetch, parse_catches_from_html
from datetime import datetime

RAW_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "crawl", "catches_raw.json")
BASE_URL = "https://www.fishing-v.jp/choka/choka_detail.php?s={sid}&pageID={page}"

V2_KEYS = ("ship", "area", "date", "trip_no", "is_cancellation", "reason_text",
           "fish_raw", "count_raw", "size_raw", "weight_raw", "tokki_raw",
           "point_raw", "kanso_raw", "suion_raw", "suishoku_raw")

def to_v2_record(c):
    return {
        "ship":            c.get("ship", ""),
        "area":            c.get("area", ""),
        "date":            c.get("date", ""),
        "trip_no":         c.get("trip_no"),
        "is_cancellation": c.get("is_cancellation", False),
        "reason_text":     c.get("reason_text", ""),
        "fish_raw":        c.get("fish_raw", ""),
        "count_raw":       c.get("count_raw", ""),
        "size_raw":        c.get("size_raw", ""),
        "weight_raw":      c.get("weight_raw", ""),
        "tokki_raw":       c.get("tokki_raw", ""),
        "point_raw":       c.get("point_raw", ""),
        "kanso_raw":       c.get("kanso_raw") or c.get("trip_comment", ""),
        "suion_raw":       c.get("suion_raw"),
        "suishoku_raw":    c.get("suishoku_raw"),
    }

def is_v2(r):
    return "count_raw" in r

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sid",       type=int, required=True)
    ap.add_argument("--name",      required=True)
    ap.add_argument("--area",      required=True)
    ap.add_argument("--max-pages", type=int, default=200)
    ap.add_argument("--start-page",type=int, default=2, help="取得開始ページ（デフォルト2）")
    ap.add_argument("--sleep",     type=float, default=1.0)
    args = ap.parse_args()

    # 既存データ読み込み（V2のみ）
    all_records = json.load(open(RAW_PATH, encoding="utf-8"))
    v1_count = sum(1 for r in all_records if not is_v2(r) and r.get("ship") == args.name)
    if v1_count > 0:
        print(f"警告: {args.name} のV1レコード {v1_count}件 を除去します")
        all_records = [r for r in all_records if not (r.get("ship") == args.name and not is_v2(r))]

    existing_keys = {
        (r["ship"], r["area"], r["date"], r.get("fish_raw",""), str(r.get("trip_no","")))
        for r in all_records if is_v2(r)
    }
    print(f"既存V2レコード: {len(all_records)}件")
    print(f"対象: {args.name} (SID={args.sid}) ページ{args.start_page}〜{args.max_pages}")

    year = datetime.now().year
    added_total = 0
    new_records = []
    consecutive_zero = 0
    MAX_CONSECUTIVE_ZERO = 5  # 連続5ページ重複でも、最古日付が閾値以前になるまで続行

    for page in range(args.start_page, args.max_pages + 1):
        url = BASE_URL.format(sid=args.sid, page=page)
        html = fetch(url)
        if not html:
            print(f"  page {page}: fetch失敗、終了")
            break

        catches = parse_catches_from_html(html, args.name, args.area, year)
        if not catches:
            print(f"  page {page}: 0件 → 終了")
            break

        added = 0
        for c in catches:
            if c.get("is_cancellation"):
                continue
            if not c.get("fish_raw"):
                continue
            rec = to_v2_record(c)
            key = (rec["ship"], rec["area"], rec["date"], rec.get("fish_raw",""), str(rec.get("trip_no","")))
            if key not in existing_keys:
                existing_keys.add(key)
                new_records.append(rec)
                added += 1

        dates = [c["date"] for c in catches if c.get("date")]
        oldest = min(dates) if dates else "?"
        print(f"  page {page}: {len(catches)}件取得 / {added}件新規 / 最古={oldest}")

        if added == 0:
            consecutive_zero += 1
            # 最古日付が既存V2範囲より前になっていれば完了
            if oldest != "?" and oldest < "2026/01/06":
                print(f"  最古={oldest}、既存範囲外まで到達 → 終了")
                break
            if consecutive_zero >= MAX_CONSECUTIVE_ZERO:
                print(f"  {MAX_CONSECUTIVE_ZERO}ページ連続重複 → 通過中（既存範囲）")
                consecutive_zero = 0  # リセットして継続
        else:
            consecutive_zero = 0

        added_total += added
        time.sleep(args.sleep)

    if new_records:
        all_records.extend(new_records)
        all_records.sort(key=lambda r: (r.get("ship",""), r.get("date",""), r.get("trip_no") or 0))
        with open(RAW_PATH, "w", encoding="utf-8") as f:
            json.dump(all_records, f, ensure_ascii=False, indent=2)
        print(f"\n完了: {added_total}件追加 → {RAW_PATH}")
    else:
        print("\n新規レコードなし")

if __name__ == "__main__":
    main()
