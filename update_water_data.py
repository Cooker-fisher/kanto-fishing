#!/usr/bin/env python3
"""
update_water_data.py - 水色/水温タグを持つ船宿を特定し、過去データを更新する

ステップ:
  1. 全船宿のpage1をスキャン → 【水色】【水温】タグがある船宿を特定
  2. 対象船宿の全ページをクロール → (date → suion/suishoku) マップ構築
  3. catches_raw.json の suion_raw/suishoku_raw を更新
  4. python crawler.py --export-csv でCSV全再生成

使い方:
  python update_water_data.py              # 実行
  python update_water_data.py --scan-only  # スキャンのみ（どの船宿が対象か確認）
"""
import os, sys, json, time, re, random
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import crawler

CUTOFF   = "2023/01/01"
MAX_PAGE = 200
BASE_URL = "https://www.fishing-v.jp/choka/choka_detail.php?s={sid}&pageID={page}"
RAW_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "crawl", "catches_raw.json")


def has_water_tags(html):
    return "【水色】" in html or "【水温】" in html


def extract_water_from_page(html, ship_name, ship_area, year):
    """ページHTMLから date → (suion_raw, suishoku_raw) マップを返す"""
    water_map = {}
    catches = crawler.parse_catches_from_html(html, ship_name, ship_area, year)
    for c in catches:
        date = c.get("date", "")
        if not date or date < CUTOFF:
            continue
        suion    = c.get("suion_raw") or ""
        suishoku = c.get("suishoku_raw") or ""
        if (suion or suishoku) and date not in water_map:
            water_map[date] = (suion, suishoku)
    return water_map


def crawl_ship_all_water(ship, year):
    """1船宿の全ページから water_map を構築"""
    water_map = {}
    seen_dates = set()

    for page in range(1, MAX_PAGE + 1):
        url  = BASE_URL.format(sid=ship["sid"], page=page)
        html = crawler.fetch(url)
        if not html:
            print(f"      page{page}: fetch失敗 → 打ち切り", flush=True)
            break

        wm = extract_water_from_page(html, ship["name"], ship["area"], year)
        water_map.update({k: v for k, v in wm.items() if k not in water_map})

        # ページ内の日付を確認してカットオフ判定
        all_dates = [m.group(1) for m in re.finditer(r'"date[^"]*"[^>]*>(\d{4}/\d{2}/\d{2})', html)]
        if not all_dates:
            # choka_boxのli.dateから抽出
            box_dates = re.findall(r'<li[^>]+class="[^"]*date[^"]*"[^>]*>[^<]+</li>', html)
            # fallback: just check if oldest date is before cutoff
            pass

        # catches を使ってカットオフ確認
        catches = crawler.parse_catches_from_html(html, ship["name"], ship["area"], year)
        if not catches:
            break

        page_dates = {c["date"] for c in catches if c.get("date")}
        if page_dates and min(page_dates) < CUTOFF:
            break
        if page_dates and page_dates.issubset(seen_dates):
            break
        seen_dates |= page_dates

        if "次</a>" not in html and ">次<" not in html:
            break

        time.sleep(random.uniform(0.8, 1.5))

    return water_map


def main():
    scan_only = "--scan-only" in sys.argv

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    # crawl/ships.json から直接読む（exclude/boat_only を確実に反映）
    _ships_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "crawl", "ships.json")
    with open(_ships_path, encoding="utf-8") as _f:
        _all_ships = json.load(_f)
    all_ships = [s for s in _all_ships
                 if s.get("source", "fishing-v") == "fishing-v"
                 and not s.get("exclude")
                 and not s.get("boat_only")
                 and s.get("sid")]

    year = datetime.now().year

    print(f"=== 水色/水温データ更新スクリプト ===")

    # ---------- Step 1: scan（--scan-only のときのみ全船宿スキャン） ----------
    if scan_only:
        print(f"ステップ1: 全{len(all_ships)}船宿をスキャン（page1のみ）...\n")
        water_ships = []
        for i, s in enumerate(all_ships, 1):
            url  = BASE_URL.format(sid=s["sid"], page=1)
            html = crawler.fetch(url)
            has_wt = has_water_tags(html) if html else False
            status = "有" if has_wt else "無"
            print(f"  [{i:02d}/{len(all_ships)}] {s['area']} {s['name']}: {status}", flush=True)
            if has_wt:
                water_ships.append(s)
            time.sleep(0.8)
        print(f"\n--- スキャン結果 ---")
        print(f"水色/水温タグあり: {len(water_ships)}船宿")
        for s in water_ships:
            print(f"  - {s['name']} ({s['area']})")
        print("\n[--scan-only] ここで終了")
        return

    # スキャン済み結果を直接使用（2026-04-16 スキャン確認済み）
    WATER_SHIP_NAMES = {
        "日正丸", "明進丸", "信栄丸", "仁徳丸", "幸栄丸", "豊丸",
        "ARCADIA SALTWATER SERVICE", "光佑丸", "幸丸", "梅花丸", "三次郎丸",
        "勇幸丸", "敷嶋丸", "明広丸", "新幸丸", "不動丸", "村井丸",
        "共栄丸", "佐衛美丸", "浜新丸", "こなや丸", "吉久", "かめだや",
        "船宿 まる八", "渡辺釣船店", "荒川屋", "長崎屋", "山下丸", "巳之助丸",
        "山天丸", "太郎丸", "翔太丸", "瀬戸丸", "たいぞう丸", "とうふや丸",
        "秀正丸",
    }
    water_ships = [s for s in all_ships if s["name"] in WATER_SHIP_NAMES]
    print(f"対象: {len(water_ships)}船宿（スキャン済みリストより）")
    for s in water_ships:
        print(f"  - {s['name']} ({s['area']})")

    if not water_ships:
        print("対象船宿なし → 終了")
        return

    # ---------- Step 2: full crawl ----------
    print(f"\nステップ2: 対象{len(water_ships)}船宿の全ページクロール...\n")
    all_water = {}  # {ship_name: {date: (suion, suishoku)}}
    for i, s in enumerate(water_ships, 1):
        print(f"  [{i:02d}/{len(water_ships)}] {s['name']} クロール中...", end=" ", flush=True)
        wm = crawl_ship_all_water(s, year)
        print(f"{len(wm)}日分 水色/水温あり")
        all_water[s["name"]] = wm
        if i < len(water_ships):
            time.sleep(random.uniform(4.0, 8.0))

    # ---------- Step 3: update catches_raw.json ----------
    print(f"\nステップ3: catches_raw.json 更新...")
    with open(RAW_PATH, encoding="utf-8") as f:
        records = json.load(f)

    updated_suion = 0
    updated_suishoku = 0
    for r in records:
        ship = r.get("ship", "")
        date = r.get("date", "")
        if ship not in all_water or date not in all_water[ship]:
            continue
        suion, suishoku = all_water[ship][date]
        if suion and not r.get("suion_raw"):
            r["suion_raw"] = suion
            updated_suion += 1
        if suishoku and not r.get("suishoku_raw"):
            r["suishoku_raw"] = suishoku
            updated_suishoku += 1

    print(f"  suion_raw 更新: {updated_suion}件")
    print(f"  suishoku_raw 更新: {updated_suishoku}件")

    with open(RAW_PATH, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)
    print("  catches_raw.json 保存完了")

    # ---------- Step 4: re-export CSV ----------
    print(f"\nステップ4: CSV全再生成 (--export-csv)...")
    crawler.export_csv_from_raw()
    print("\n=== 完了 ===")


if __name__ == "__main__":
    main()
