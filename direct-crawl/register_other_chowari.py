"""
register_other_chowari.py — 茨城・神奈川・東京・静岡 chowari 未登録 160隻を ships.json に一括登録

tmp_titles.json から船宿名・港情報を読み取り、ships.json エントリ生成。
複合主役ルールは後付け（クロール結果見てから）。
重複（既存 (name, area) ペア）はスキップ。

slug 命名: 既存と衝突しないよう chowari-{chowari_id} 形式（chowari-00166 等）

実行:
    python direct-crawl/register_other_chowari.py [--dry-run]
"""

import json, os, sys, re
sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHIPS_PATH = os.path.join(ROOT, "crawl", "ships.json")
TITLES = os.path.join(ROOT, "tmp_titles.json")
TODAY = "2026-05-17"


def main():
    dry_run = "--dry-run" in sys.argv
    with open(SHIPS_PATH, encoding="utf-8") as f:
        ships = json.load(f)
    existing_pairs = {(s.get("name"), s.get("area")) for s in ships}

    titles = json.load(open(TITLES, encoding="utf-8"))
    pref_map = {"茨城": "茨城", "神奈川": "神奈川", "東京": "東京", "静岡": "静岡"}

    added = []
    skipped = []
    for area_label, ship_list in titles.items():
        pref = pref_map[area_label]
        for s in ship_list:
            cid = s["chowari_id"]
            name = s["name"]
            port = s["port"]
            location = s["location"]
            # ERROR / "?" は除外
            if name.startswith("ERROR") or name == "?":
                skipped.append(f"{cid} ({area_label}) - 名前取得失敗")
                continue
            # area = 港名（取れない場合は location 末尾）
            area = port if port and port != "?" else location.split()[-1] if location else "?"
            key = (name, area)
            if key in existing_pairs:
                skipped.append(f"{name} ({area}) - 既存")
                continue
            existing_pairs.add(key)
            slug = f"chowari-{cid}"
            entry = {
                "sid": None,
                "name": name,
                "area": area,
                "chowari_id": cid,
                "castingnet_id": None,
                "official_url": None,
                "romaji_slug": slug,
                "phone": "",
                "address": location,
                "business_hours": "記載なし",
                "closed_days": "記載なし",
                "fishing_v_zero": True,
                "fishing_v_zero_verified_at": TODAY,
                "source_priority": ["chowari"],
                "notes": f"{pref}/{area_label} chowari 自動登録（複合主役ルールは後付け）",
            }
            added.append(entry)

    print(f"=== 4都県 chowari 一括登録 (dry={dry_run}) ===")
    print(f"追加: {len(added)} / スキップ: {len(skipped)}")
    print()
    by_area = {}
    for e in added:
        by_area.setdefault(e["address"][:8] if e["address"] else "?", 0)
        by_area[e["address"][:8] if e["address"] else "?"] = by_area.get(e["address"][:8] if e["address"] else "?", 0) + 1
    print("=== 追加先頭10 ===")
    for e in added[:10]:
        print(f"  {e['name']} ({e['area']}) chowari={e['chowari_id']} slug={e['romaji_slug']}")
    print()
    print("=== スキップ ===")
    for s in skipped[:20]:
        print(f"  {s}")

    if not dry_run:
        ships.extend(added)
        with open(SHIPS_PATH, "w", encoding="utf-8") as f:
            json.dump(ships, f, ensure_ascii=False, indent=2)
        print(f"\nships.json 更新: {len(ships)} 隻")


if __name__ == "__main__":
    main()
