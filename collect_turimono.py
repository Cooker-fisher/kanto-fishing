#!/usr/bin/env python3
"""
collect_turimono.py
釣りビジョン detail.php?s={SID} から turimono_list を収集し
ships.json に turimono_list フィールドを追記する。

使い方:
  python collect_turimono.py
"""
import json, re, time, sys, urllib.request, urllib.error, os

sys.stdout.reconfigure(encoding="utf-8")

BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
SHIPS_FILE = os.path.join(BASE_DIR, "ships.json")
SLEEP_SEC  = 0.8   # サーバー負荷対策
TIMEOUT    = 12

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"


def fetch_turimono(sid: int) -> list[str]:
    url = f"https://www.fishing-v.jp/choka/detail.php?s={sid}"
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        html = urllib.request.urlopen(req, timeout=TIMEOUT).read().decode("utf-8", errors="replace")
    except Exception as e:
        return None  # None = 取得失敗

    match = re.search(r'<ul class="turimono_list">(.*?)</ul>', html, re.DOTALL)
    if not match:
        return []   # [] = ページあるがリストなし

    items = re.findall(r"<li>(.*?)</li>", match.group(1), re.DOTALL)
    return [re.sub(r"<[^>]+>", "", i).strip() for i in items
            if re.sub(r"<[^>]+>", "", i).strip()]


def main():
    ships = json.load(open(SHIPS_FILE, encoding="utf-8"))

    # 有効船宿のみ対象（exclude/boat_only は除く）
    targets = [s for s in ships if not s.get("exclude") and not s.get("boat_only")]
    print(f"対象船宿: {len(targets)} 件")

    errors   = []
    empty    = []

    for i, ship in enumerate(targets, 1):
        sid  = ship["sid"]
        name = ship["name"]
        result = fetch_turimono(sid)
        if result is None:
            print(f"  [{i:2d}/{len(targets)}] {name}(SID={sid}) → ❌ 取得失敗")
            errors.append(sid)
        elif result == []:
            print(f"  [{i:2d}/{len(targets)}] {name}(SID={sid}) → ⚠️  リストなし")
            empty.append(sid)
            ship["turimono_list"] = []
        else:
            print(f"  [{i:2d}/{len(targets)}] {name}(SID={sid}) → {result}")
            ship["turimono_list"] = result

        time.sleep(SLEEP_SEC)

    # 書き戻し
    json.dump(ships, open(SHIPS_FILE, "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    print(f"\n✅ ships.json 更新完了")
    print(f"   成功: {len(targets)-len(errors)-len(empty)} 件")
    print(f"   リストなし: {len(empty)} 件 → SID={empty}")
    print(f"   取得失敗: {len(errors)} 件 → SID={errors}")


if __name__ == "__main__":
    main()
