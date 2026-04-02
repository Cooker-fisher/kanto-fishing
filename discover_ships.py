#!/usr/bin/env python3
"""
discover_ships.py
釣りビジョンから神奈川・東京・千葉・茨城の船宿SIDを自動収集し ships.json に保存する
標準ライブラリのみ使用 / GitHub Actions から月1回実行される

使い方:
    python discover_ships.py          # ships.json を更新
    python discover_ships.py --dry    # ships.json を変えずに結果だけ表示
"""
import re, time, sys, json, os
from urllib.request import urlopen, Request
from urllib.error import URLError

PREFS = {"8": "茨城", "12": "千葉", "13": "東京", "14": "神奈川", "22": "静岡"}

# 船釣りサイトに不要な施設（海釣り公園・かかり釣り等）を除外
EXCLUDE_KEYWORDS = ["フィッシングピアーズ", "かかり釣りセンター", "海釣り施設"]

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; kanto-fishing-bot/1.0)"}
SLEEP   = 0.8
OUTPUT  = os.path.join(os.path.dirname(__file__), "ships.json")

def fetch(url):
    req = Request(url, headers=HEADERS)
    with urlopen(req, timeout=15) as r:
        return r.read().decode("utf-8", errors="replace")

def parse_ships(html):
    ships = []
    for block in re.split(r'<div class="choka[^"]*clearfix">', html)[1:]:
        sid_m  = re.search(r'detail\.php\?s=(\d+)', block)
        name_m = re.search(r'shop_name02">([^<]+)<', block)
        port_m = re.search(r'point_link\d+">\s*([^<]+?)\s*</a>', block)
        if not sid_m or not name_m:
            continue
        name = name_m.group(1).strip()
        if any(kw in name for kw in EXCLUDE_KEYWORDS):
            continue
        ships.append({
            "sid":  int(sid_m.group(1)),
            "name": name,
            "area": (port_m.group(1).strip() if port_m else ""),
        })
    return ships

def discover_pref(pref_id, pref_name):
    found, page = {}, 1
    while True:
        url = f"https://www.fishing-v.jp/choka/detail.php?s_flg=0&pref%5B%5D={pref_id}&pageID={page}"
        try:
            ships = parse_ships(fetch(url))
        except Exception as e:
            print(f"  p{page} ERROR: {e}", flush=True)
            break
        if not ships:
            break
        new = sum(1 for s in ships if s["sid"] not in found)
        for s in ships:
            found[s["sid"]] = s
        print(f"  {pref_name} p{page}: +{new} (累計{len(found)})", flush=True)
        if new == 0:
            break
        page += 1
        time.sleep(SLEEP)
    return list(found.values())

def main():
    dry = "--dry" in sys.argv
    all_ships = {}
    for pref_id, pref_name in PREFS.items():
        for s in discover_pref(pref_id, pref_name):
            all_ships[s["sid"]] = s

    result = sorted(all_ships.values(), key=lambda x: (x["area"], x["name"]))
    print(f"\n合計: {len(result)}隻発見", flush=True)

    if dry:
        for s in result:
            print(f'  {s["area"]:20} {s["name"]:20} sid={s["sid"]}')
        return

    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"→ {OUTPUT} に保存しました", flush=True)

if __name__ == "__main__":
    main()
