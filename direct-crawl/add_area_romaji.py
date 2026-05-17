"""
add_area_romaji.py — normalize/area_romaji_map.json に
  (1) chowari 未登録船宿 area
  (2) Kanso由来主要ポイント
を一括追加

実行:
    python direct-crawl/add_area_romaji.py [--dry-run]
"""

import json, os, sys
sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATH = os.path.join(ROOT, "normalize", "area_romaji_map.json")

# 手動マッピング: 港・地名 → ASCII slug
# 既存 area_romaji_map.json と衝突しないよう、登録前にチェック
NEW_AREAS = {
    # === chowari 未登録 area ===
    "久慈":         "kuji",
    "久料港":       "kuryo",
    "伊戸":         "ito-tateyama",
    "伊東":         "ito-shi",
    "会瀬漁港":     "ose",
    "勝浦":         "katsuura",
    "南伊豆町手石港": "teishi",
    "品川区品川堀": "shinagawa-bori",
    "品川区立会川勝島運河": "tachiaigawa-katsushima",
    "品川区鮫洲勝島運河":   "samezu-katsushima",
    "大洗":         "oarai",
    "大田区六郷水門": "rokugo-suimon",
    "大田区呑川":   "nomigawa",
    "大田区海老取川": "ebitorigawa",
    "宇佐美港":     "usami",
    "寸座マリーナ": "sunza-marina",
    "小田原新港":   "odawara-shinko",
    "川名":         "kawana",
    "平潟":         "hiragata",
    "戸又港":       "tomata",
    "戸田港":       "toda-shizuoka",
    "日立":         "hitachi",
    "早川漁港":     "hayakawa",
    "柴漁港":       "shiba",
    "横浜":         "yokohama",
    "横浜市八幡橋": "hachimanbashi",
    "横浜市金沢八景乙舳": "kanazawa-hakkei-otomo",
    "横浜市金沢八景平潟": "kanazawa-hakkei-hirakata",
    "江戸川区今井水門": "imai-suimon",
    "江戸川区新今井橋": "shin-imaibashi",
    "江戸川区鹿本橋":   "shikamotobashi",
    "江東区夢の島桟橋": "yumenoshima",
    "江東区小名木川":   "onagigawa",
    "江東区木場":       "kiba",
    "江東区東京湾マリーナ": "tokyowan-marina",
    "江東区釣船橋":     "tsuribashi",
    "江見":         "emi",
    "沼津市江の浦港": "enoura",
    "波崎新港":     "hasaki-shinko",
    "洲崎":         "sunosaki",
    "浜行川":       "hamanamegawa",
    "清水":         "shimizu",
    "港区京浜運河": "keihin",
    "湯河原町福浦港": "fukuura-yugawara",
    "焼津小川港":   "yaizu-ogawa",
    "焼津港":       "yaizu",
    "熱海港":       "atami-port",
    "片瀬漁港":     "katase-gyoko",
    "片貝":         "katakai",
    "相浜":         "aihama",
    "真鶴町真鶴港": "manazuru-port",
    "網代港":       "ajiro-port",
    "腰越漁港":     "koshigoe",
    "西伊豆町安良里港": "arari",
    "足立区千住大橋": "senju-ohashi",
    "那珂湊港":     "nakaminato",
    "静浦漁港":     "shizuura",
    "須崎港":       "suzaki",
    "鹿島":         "kashima-port",

    # === Kanso由来 主要ポイント (頻出50超・釣り場別ページ生成) ===
    "剣崎沖":       "kenzaki-oki",
    "久里浜沖":     "kurihama-oki",
    "観音崎沖":     "kannonzaki-oki",
    "横浜沖":       "yokohama-oki",
    "城ヶ島沖":     "jogashima-oki",
    "木更津沖":     "kisarazu-oki",
    "竹岡沖":       "takeoka-oki",
    "茅ヶ崎沖":     "chigasaki-oki",
    "走水沖":       "hashirimizu-oki",
    "平塚沖":       "hiratsuka-oki",
    "富岡沖":       "tomioka-oki",
    "金谷沖":       "kanaya-oki",
    "猿島沖":       "sarushima-oki",
    "沼津沖":       "numazu-oki",
    "鴨居沖":       "kamoi-oki",
    "本牧沖":       "honmoku-oki",
    "小柴沖":       "koshiba-oki",
    "大貫沖":       "onuki-oki",
    "長井沖":       "nagai-oki",
    "小田原沖":     "odawara-oki",
    "葉山沖":       "hayama-oki",
    "八景沖":       "hakkei-oki",
    "太東沖":       "futo-oki",
    "中ノ瀬":       "nakanose",
    "大原沖":       "oohara-oki",
    "下浦沖":       "shimoura-oki",
    "浦安湾内":     "urayasu-bay",
    "鹿島南沖":     "kashima-minami-oki",
    "富津沖":       "futtsu-oki",
    "横須賀沖":     "yokosuka-oki",
    "飯岡沖":       "iioka-oki",
    "鹿島沖":       "kashima-oki",
    "洲崎沖":       "sunosaki-oki",
    "鹿島北沖":     "kashima-kita-oki",
    "相模湾":       "sagamiwan",
    "赤灯沖":       "akato-oki",
    "佐島沖":       "sajima-oki",
    "保田沖":       "hota-oki",
    "二宮沖":       "ninomiya-oki",
    "川崎沖":       "kawasaki-oki",
    "波崎沖":       "hasaki-oki",
    "神津島":       "kozushima",
    "鹿島真沖":     "kashima-maoki",
    "勝浦沖":       "katsuura-oki",
    "亀城根":       "kamejone",
}


def main():
    dry_run = "--dry-run" in sys.argv
    with open(PATH, encoding="utf-8") as f:
        existing = json.load(f)
    before = len(existing)
    added = []
    conflicts = []
    used_slugs = set(existing.values())
    for name, slug in NEW_AREAS.items():
        if name in existing:
            continue  # 既存と同名 → スキップ
        if slug in used_slugs:
            conflicts.append((name, slug, [k for k, v in existing.items() if v == slug]))
            continue
        existing[name] = slug
        used_slugs.add(slug)
        added.append((name, slug))

    print(f"=== area_romaji_map.json 拡張 (dry={dry_run}) ===")
    print(f"既存: {before} → 追加候補: {len(NEW_AREAS)} → 新規追加: {len(added)} (衝突スキップ: {len(conflicts)})")
    print()
    print("--- 衝突（slug 重複・追加スキップ）---")
    for name, slug, existing_keys in conflicts:
        print(f"  「{name}」 → slug={slug!r} は既に {existing_keys} で使用中")
    print()
    print("--- 追加 ---")
    for name, slug in added:
        print(f"  「{name}」 → {slug}")
    print(f"\n総数: {before + len(added)}")

    if not dry_run:
        with open(PATH, "w", encoding="utf-8") as f:
            json.dump(existing, f, ensure_ascii=False, indent=2, sort_keys=True)
        print("\narea_romaji_map.json 更新")


if __name__ == "__main__":
    main()
