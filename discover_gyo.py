#!/usr/bin/env python3
"""
discover_gyo.py
関東沖釣り情報(gyo.ne.jp)から関東エリアの船宿CIDを収集し gyo_ships.json に保存する
標準ライブラリのみ / GitHub Actions から月1回実行される

使い方:
    python discover_gyo.py          # gyo_ships.json を更新
    python discover_gyo.py --dry    # 変更せずに結果だけ表示
"""
import re, time, sys, json, os
from urllib.request import urlopen, Request
from urllib.error import URLError

HEADERS = {
    "User-Agent":      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ja,en-US;q=0.7,en;q=0.3",
    "Referer":         "https://www.gyo.ne.jp/",
}
SLEEP      = 0.8
BASE       = "https://www.gyo.ne.jp"
OUTPUT     = os.path.join(os.path.dirname(__file__), "gyo_ships.json")
SHIPS_JSON = os.path.join(os.path.dirname(__file__), "ships.json")

# 収集対象のページ（トップページの地図画像マップに全船宿リンクが埋め込まれている）
FETCH_PAGES = [
    BASE + "/",
]

# エリアフィルタなし（全船宿を対象）
NON_KANTO_PORTS = []
# 除外する施設タイプ
EXCLUDE_KW = ["フィッシングピア", "かかり釣り", "海釣り施設", "釣り公園"]


def fetch_sjis(url):
    req = Request(url, headers=HEADERS)
    try:
        with urlopen(req, timeout=15) as r:
            raw = r.read()
    except Exception as e:
        print(f"  FETCH ERROR {url}: {e}", flush=True)
        return ""
    # cp932 = Windows版Shift-JIS（より広い文字カバレッジ）
    for enc in ("cp932", "shift_jis", "euc-jp", "utf-8"):
        try:
            return raw.decode(enc)
        except Exception:
            pass
    return raw.decode("utf-8", errors="replace")


def extract_ships(html):
    """
    gyo.ne.jp のトップページから CID・船名・エリアを抽出する。
    CID リンクは <area> タグの画像マップに埋め込まれており、
    title="エリア名 船名" の形式でエリアと船名を持つ。
    """
    ships = []
    seen  = set()

    # <area> タグ: href に CID、title に "エリア名 船名"
    area_tag_pat = re.compile(
        r'<area[^>]+href="[^"]*?/rep_tsuri_view\|CID-([^."]+)\.htm[^"]*"[^>]*title="([^"]*)"',
        re.S
    )

    for m in area_tag_pat.finditer(html):
        cid   = m.group(1).strip()
        title = m.group(2).strip()
        if not cid or not title or cid in seen:
            continue

        # title = "エリア名 船名"（スペースまたは全角スペースで区切り）
        parts = re.split(r'[\s\u3000]+', title, maxsplit=1)
        if len(parts) == 2:
            area, name = parts[0].strip(), parts[1].strip()
        else:
            area, name = "", title

        # 非関東港を除外
        if any(p in area for p in NON_KANTO_PORTS):
            continue
        if any(kw in name for kw in EXCLUDE_KW):
            continue

        seen.add(cid)
        ships.append({
            "cid":    cid,
            "name":   name,
            "area":   area,
            "source": "gyo",
        })

    return ships


def load_existing_names():
    """ships.json（fishing-v.jp由来）から既存の船名セットを返す。"""
    if not os.path.exists(SHIPS_JSON):
        return set()
    try:
        with open(SHIPS_JSON, encoding="utf-8") as f:
            return {s["name"] for s in json.load(f)}
    except Exception:
        return set()


def main():
    dry = "--dry" in sys.argv

    existing_names = load_existing_names()
    print(f"既存 ships.json（fishing-v.jp）: {len(existing_names)} 船宿", flush=True)

    all_ships = {}  # cid → ship dict

    for url in FETCH_PAGES:
        print(f"Fetching {url} ...", flush=True)
        html = fetch_sjis(url)
        if not html:
            continue
        found = extract_ships(html)
        new_count = 0
        for s in found:
            if s["cid"] not in all_ships:
                all_ships[s["cid"]] = s
                new_count += 1
        print(f"  → +{new_count} CID（累計 {len(all_ships)}）", flush=True)
        time.sleep(SLEEP)

    # fishing-v.jp との重複を除去（船名で照合）
    new_ships = [s for s in all_ships.values() if s["name"] not in existing_names]
    skipped   = len(all_ships) - len(new_ships)

    print(f"\n合計: {len(all_ships)} 船宿発見", flush=True)
    print(f"  重複（fishing-v.jp と一致）: {skipped} 船宿 → スキップ", flush=True)
    print(f"  新規追加: {len(new_ships)} 船宿", flush=True)

    if dry:
        for s in sorted(new_ships, key=lambda x: (x["area"], x["name"])):
            print(f'  {s["area"]:20} {s["name"]:20} cid={s["cid"]}')
        return

    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump(
            sorted(new_ships, key=lambda x: (x["area"], x["name"])),
            f, ensure_ascii=False, indent=2
        )
    print(f"→ {OUTPUT} に保存しました", flush=True)


if __name__ == "__main__":
    main()
