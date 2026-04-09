#!/usr/bin/env python3
"""
backfill_depth.py - 既存CSVのpoint_depth_min/maxを埋めるため、
水深報告のある船宿だけ再クロールしてポイント列を取得する。

- catches.jsonから水深報告率>0の船宿を特定
- fishing-v.jpの各ページを遡ってポイント列だけ抽出
- (ship, date, fish) をキーにCSVのdepth列を更新
- 新規行の追加はしない（既存行のdepthパッチのみ）

実行:
  python backfill_depth.py
"""
import os, sys, csv, json, time, random
from datetime import datetime, timedelta
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import crawler

CUTOFF = (datetime.now() - timedelta(days=365 * 2)).strftime("%Y/%m/%d")
BASE_URL = "https://www.fishing-v.jp/choka/choka_detail.php?s={sid}&pageID={page}"


def get_depth_ships():
    """catches.jsonから水深報告ありの船宿SIDを返す"""
    cj_path = os.path.join(os.path.dirname(__file__), "catches.json")
    if not os.path.exists(cj_path):
        return set()
    with open(cj_path, encoding="utf-8") as f:
        data = json.load(f).get("data", [])

    ship_stats = defaultdict(lambda: {"total": 0, "depth": 0})
    for c in data:
        ship_stats[c["ship"]]["total"] += 1
        if c.get("point_depth"):
            ship_stats[c["ship"]]["depth"] += 1

    return {s for s, st in ship_stats.items() if st["depth"] > 0}


def load_csv_keys_needing_depth():
    """CSVからdepth空の行のキー (ship, date, fish) セットを返す"""
    data_dir = os.path.join(os.path.dirname(__file__), "data")
    keys = set()
    if not os.path.isdir(data_dir):
        return keys
    for fname in os.listdir(data_dir):
        if not fname.endswith(".csv"):
            continue
        with open(os.path.join(data_dir, fname), encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                dmin = (row.get("point_depth_min") or "").strip()
                if not dmin:
                    keys.add((row["ship"], row["date"], row["fish"]))
    return keys


def crawl_depth_for_ship(ship, year, needed_keys):
    """1船宿の全ページを遡り、ポイント+水深データを収集。
    needed_keysにマッチするレコードのみ返す。
    """
    depth_map = {}  # (ship, date, fish) -> (place, depth)
    seen_dates = set()
    ship_name = ship["name"]

    for page in range(1, 100):
        url = BASE_URL.format(sid=ship["sid"], page=page)
        html = crawler.fetch(url)
        if not html:
            break

        catches = crawler.parse_catches_from_html(html, ship_name, ship["area"], year)
        if not catches:
            break

        new_in_page = 0
        for c in catches:
            if not c.get("date"):
                continue
            pd = c.get("point_depth")
            pp = c.get("point_place")
            if pd:
                for fish in c["fish"]:
                    key = (ship_name, c["date"], fish)
                    if key in needed_keys and key not in depth_map:
                        depth_map[key] = (pp or "", pd)
                        new_in_page += 1

        # カットオフチェック
        dates = [c["date"] for c in catches if c.get("date")]
        if dates and min(dates) < CUTOFF:
            break

        # ページ送り停止チェック
        page_dates = set(dates)
        if page_dates and page_dates.issubset(seen_dates):
            break
        seen_dates |= page_dates

        if "次</a>" not in html and ">次<" not in html:
            break

        time.sleep(random.uniform(1.0, 2.0))

    return depth_map


def patch_csvs(depth_map):
    """CSVファイルのdepth列をdepth_mapで更新"""
    data_dir = os.path.join(os.path.dirname(__file__), "data")
    total_patched = 0

    for fname in sorted(os.listdir(data_dir)):
        if not fname.endswith(".csv"):
            continue
        filepath = os.path.join(data_dir, fname)
        with open(filepath, encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            header = next(reader)
            rows = list(reader)

        patched = 0
        for row in rows:
            while len(row) < 16:
                row.append("")
            # depth空の行だけ対象
            if row[14] or row[15]:
                continue
            key = (row[0], row[2], row[3])  # ship, date, fish
            info = depth_map.get(key)
            if info:
                pp, pd = info
                d_min, d_max = crawler._split_depth(pd)
                if d_min:
                    # point_placeも更新（parse_point済みのクリーンな値）
                    if pp:
                        row[12] = pp
                    row[14] = str(d_min)
                    row[15] = str(d_max)
                    patched += 1

        if patched > 0:
            with open(filepath, "w", encoding="utf-8", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(crawler.CSV_HEADER)
                writer.writerows(rows)
            total_patched += patched

    return total_patched


def main():
    year = datetime.now().year
    depth_ships = get_depth_ships()
    print(f"=== 水深バックフィル ===")
    print(f"水深報告あり船宿: {len(depth_ships)}隻")

    # SHIPSから対象船宿を絞り込み（fishing-v のみ）
    target_ships = [
        s for s in crawler.SHIPS
        if s.get("source", "fishing-v") == "fishing-v" and s["name"] in depth_ships
    ]
    print(f"クロール対象: {len(target_ships)}隻")

    needed_keys = load_csv_keys_needing_depth()
    print(f"depth空のCSV行: {len(needed_keys)}件")

    # 対象船宿のキーだけに絞る
    target_names = {s["name"] for s in target_ships}
    needed_keys = {k for k in needed_keys if k[0] in target_names}
    print(f"対象船宿のdepth空行: {len(needed_keys)}件")
    print(f"カットオフ: {CUTOFF}")
    print()

    all_depth_map = {}
    random.shuffle(target_ships)

    for i, ship in enumerate(target_ships, 1):
        print(f"[{i:02d}/{len(target_ships)}] {ship['area']} {ship['name']} ...", end=" ", flush=True)
        dm = crawl_depth_for_ship(ship, year, needed_keys)
        all_depth_map.update(dm)
        print(f"水深取得: {len(dm)}件")

        # 10船宿ごとに中間パッチ
        if i % 10 == 0 and all_depth_map:
            patched = patch_csvs(all_depth_map)
            print(f"  >>> 中間パッチ: {patched}行更新")

        if i < len(target_ships):
            time.sleep(random.uniform(3.0, 6.0))

    # 最終パッチ
    patched = patch_csvs(all_depth_map)

    print(f"\n=== 完了 ===")
    print(f"水深データ取得: {len(all_depth_map)}件")
    print(f"CSVパッチ: {patched}行更新")


if __name__ == "__main__":
    main()
