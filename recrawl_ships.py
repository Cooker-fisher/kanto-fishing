#!/usr/bin/env python3
"""
指定船宿のデータを再クロールして CSV を上書き更新するスクリプト。
FISH_MAP 拡張後の不明レコード回収に使用。

手順:
  1. 対象船宿の既存レコードを CSV から全削除
  2. FV を全ページ再クロール（新 FISH_MAP 適用済み）
  3. 新スキーマで CSV に保存
"""

import csv, glob, os, re, sys, time, random
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import crawler
from migrate_csv import parse_point_place

BASE_URL = "https://www.fishing-v.jp/choka/choka_detail.php?s={sid}&pageID={page}"
CUTOFF   = (datetime.now() - timedelta(days=365 * 2)).strftime("%Y/%m/%d")

NEW_HEADER = [
    "ship", "area", "date", "fish",
    "cnt_min", "cnt_max", "cnt_avg",
    "size_min", "size_max",
    "kg_min", "kg_max",
    "is_boat", "point_place", "point_place2",
    "point_depth_min", "point_depth_max",
]

TARGET_SHIPS = [
    {"sid": 11364, "name": "洋征丸",   "area": "小坪港"},
    {"sid": 1700,  "name": "平安丸",   "area": "小田原早川港"},
    {"sid": 218,   "name": "はら丸",   "area": "長井港"},
]


def remove_ship_records(ship_name):
    """全 CSV から指定船宿のレコードを削除して件数を返す。"""
    removed = 0
    for filepath in sorted(glob.glob("data/*.csv")):
        rows = []
        with open(filepath, encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames or NEW_HEADER
            for row in reader:
                if row.get("ship") == ship_name:
                    removed += 1
                else:
                    rows.append(row)
        # 変更があれば書き戻す
        if removed > 0:
            with open(filepath, "w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)
    return removed


def crawl_all_pages(ship):
    """船宿の全ページをクロールして catches リストを返す。"""
    all_catches = []
    year = datetime.now().year
    for page in range(1, 100):
        url = BASE_URL.format(sid=ship["sid"], page=page)
        html = None
        for attempt in range(3):
            html = crawler.fetch(url)
            if html:
                break
            print(f"    page{page}: fetch失敗 (試行{attempt+1}/3) → リトライ待機...")
            time.sleep(10)
        if not html:
            print(f"    page{page}: 3回失敗 → 終了")
            break
        catches = crawler.parse_catches_from_html(html, ship["name"], ship["area"], year)
        if not catches:
            break
        dates = [c.get("date", "") for c in catches if c.get("date")]
        new_catches = [c for c in catches if c.get("date", "") >= CUTOFF]
        all_catches.extend(new_catches)
        oldest = min(dates) if dates else "9999"
        print(f"    page{page}: {len(catches)} 件  最古={oldest}")
        if oldest < CUTOFF:
            break
        time.sleep(random.uniform(1.5, 3.0))
    return all_catches


def save_catches(catches):
    """catches を新スキーマで月別 CSV に追記する。"""
    by_month = {}
    for c in catches:
        date = c.get("date", "")
        if not date or len(date) < 7:
            continue
        ym = date[:7].replace("/", "-")
        by_month.setdefault(ym, []).append(c)

    total = 0
    for ym, month_catches in sorted(by_month.items()):
        filepath = os.path.join("data", f"{ym}.csv")

        # 既存データ読み込み（他船宿のデータを保持）
        existing = []
        if os.path.exists(filepath):
            with open(filepath, encoding="utf-8", newline="") as f:
                existing = list(csv.DictReader(f))

        new_rows = []
        for c in month_catches:
            cr  = c.get("count_range") or {}
            sc  = c.get("size_cm")     or {}
            wk  = c.get("weight_kg")   or {}
            raw_point = c.get("point_place") or ""
            p1, p2, dmin, dmax = parse_point_place(raw_point)
            for fish in (c.get("fish") or ["不明"]):
                cnt_min = cr.get("min", "")
                cnt_max = cr.get("max", "")
                cnt_avg = ""
                if cnt_min != "" and cnt_max != "":
                    try:
                        cnt_avg = round((float(cnt_min) + float(cnt_max)) / 2, 1)
                    except (ValueError, TypeError):
                        cnt_avg = ""
                new_rows.append({
                    "ship":           c["ship"],
                    "area":           c["area"],
                    "date":           c["date"],
                    "fish":           fish,
                    "cnt_min":        cnt_min,
                    "cnt_max":        cnt_max,
                    "cnt_avg":        cnt_avg,
                    "size_min":       sc.get("min", ""),
                    "size_max":       sc.get("max", ""),
                    "kg_min":         wk.get("min", ""),
                    "kg_max":         wk.get("max", ""),
                    "is_boat":        1 if cr.get("is_boat") else 0,
                    "point_place":    p1,
                    "point_place2":   p2 or "",
                    "point_depth_min": dmin or "",
                    "point_depth_max": dmax or "",
                })

        with open(filepath, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=NEW_HEADER)
            writer.writeheader()
            writer.writerows(existing + new_rows)

        total += len(new_rows)
        print(f"    CSV保存: {ym} +{len(new_rows)} 件")

    return total


def main():
    print(f"=== 指定船宿再クロール ===")
    print(f"対象: {[s['name'] for s in TARGET_SHIPS]}")
    print(f"カットオフ: {CUTOFF}\n")

    for ship in TARGET_SHIPS:
        print(f"\n[{ship['name']}] SID={ship['sid']}")

        # Step 1: 既存レコード削除
        removed = remove_ship_records(ship["name"])
        print(f"  削除: {removed} 件")

        # Step 2: 再クロール
        print(f"  クロール開始...")
        catches = crawl_all_pages(ship)
        print(f"  取得: {len(catches)} 件")

        # Step 3: CSV 保存
        saved = save_catches(catches)
        print(f"  保存: {saved} 件")

        time.sleep(random.uniform(8, 15))

    print("\n=== 完了 ===")


if __name__ == "__main__":
    main()
