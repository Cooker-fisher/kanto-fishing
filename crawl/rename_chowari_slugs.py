"""chowari-NNNNN 形式の暫定 romaji_slug を正しい英語 slug に書き換える。

実行: python crawl/rename_chowari_slugs.py [--dry-run]

- 対象: ships.json で romaji_slug が 'chowari-' で始まり exclude=False の船宿
- 手動辞書 MANUAL_OVERRIDE で 114件 全てに対応
- 旧→新 マッピングを crawl/chowari_slug_redirect_map.json に保存
- ships.json を更新（romaji_slug 列のみ）
"""
import json
import os
import sys

SHIPS_PATH = "crawl/ships.json"
REDIRECT_MAP_PATH = "crawl/chowari_slug_redirect_map.json"

# 114件の手動 slug マッピング（船宿名 → 新slug）
# 同名衝突は港 suffix（例: 鈴喜丸→suzuki-maru-ajiro）
MANUAL_OVERRIDE = {
    "直重丸": "naoshige-maru",
    "清栄丸": "seiei-maru",
    "日立丸": "hitachi-maru",
    "健清丸": "kensei-maru",
    "利喜丸": "riki-maru",
    "山千丸": "yamasen-maru",
    "大久丸": "daikyu-maru",
    "第五悌栄丸": "daigo-teiei-maru",
    "鬼澤丸": "kizawa-maru",
    "植田丸": "ueda-maru",
    "義心丸": "gishin-maru",
    "第二つれたか丸": "daini-tsuretaka-maru",
    "ことぶき丸": "kotobuki-maru",
    "英昇丸": "eisho-maru",
    "とも丸": "tomo-maru",
    "仙昇丸": "sensho-maru",
    "弁天丸": "benten-maru",
    "第六隆栄丸": "dairoku-ryuei-maru",
    "第二海神丸": "daini-kaijin-maru",
    "正八丸": "shohachi-maru",
    "ふじしめ丸": "fujishime-maru",
    "栄光丸": "eikou-maru",
    "軍司丸": "gunji-maru",
    "第二洋生丸": "daini-yosei-maru",
    "BLUE DRAGON": "blue-dragon",
    "黒一丸": "kuroichi-maru",
    "仁丸": "jin-maru",
    "金沢八景 黒川丸": "kanazawa-hakkei-kurokawa-maru",
    "政美丸": "masami-maru",
    "喜久丸": "kikyu-maru",
    "瀬戸丸": "seto-maru",
    "佐島海楽園": "sashima-kairakuen",
    "池田丸": "ikeda-maru",
    "成銀丸": "narigin-maru",
    "志平丸": "shihei-maru",
    "ゆうせい丸": "yusei-maru-katase",
    "大松丸": "omatsu-maru",
    "黒川本家 -久里浜-": "kurokawa-honke-kurihama",
    "祥福丸": "shofuku-maru",
    "邦丸 -大磯港-": "kuni-maru-oiso",
    "房丸": "bo-maru",
    "島きち丸": "shimakichi-maru",
    "忠彦丸": "tadahiko-maru",
    "深田正夫丸": "fukada-masao-maru",
    "勝美丸": "katsumi-maru",
    "野毛屋釣船店": "nogeya-tsuribuneten",
    "広島屋": "hiroshimaya",
    "はやぶさ丸": "hayabusa-maru-shiba",
    "佑幸丸": "yuko-maru-matsuwa",
    "伝五郎丸": "dengoro-maru",
    "新徳丸": "shintoku-maru",
    "優神丸": "yujin-maru",
    "哲夫丸": "tetsuo-maru",
    "海良丸": "umiryo-maru",
    "濱生丸": "hamasei-maru",
    "鴨下丸kawana": "kamoshita-maru-kawana",
    "村本海事": "muramoto-kaiji",
    "光義丸": "mitsuyoshi-maru",
    "第三かりゆし丸": "daisan-kariyushi-maru",
    "正海丸": "shokai-maru",
    "瀬川丸": "segawa-maru",
    "深川 吉野屋": "fukagawa-yoshinoya",
    "三河屋": "mikawaya",
    "ひらい丸": "hirai-maru",
    "釣り船小林": "tsuribune-kobayashi",
    "船宿 さわ浦": "funayado-sawaura",
    "小林丸": "kobayashi-maru",
    "深川冨士見": "fukagawa-fujimi",
    "丸裕": "maruyu",
    "船宿豆や": "funayado-mameya",
    "入舟": "irifune",
    "ミナミ釣船": "minami-tsuribune",
    "船宿いわた": "funayado-iwata",
    "PLAYFUL FISHING": "playful-fishing",
    "シーホース": "seahorse",
    "大山丸": "oyama-maru",
    "和彦丸": "kazuhiko-maru",
    "柊丸": "hiiragi-maru",
    "アップタイドクルーズ": "uptide-cruise",
    "船宿ウォッチかいと丸": "funayado-watch-kaito-maru",
    "釣り船鶴": "tsuribune-tsuru",
    "ゴーゴーガイドサービス": "gogo-guide-service",
    "政一丸": "masaichi-maru",
    "伊勝丸": "ikatsu-maru",
    "幸洋丸": "koyo-maru",
    "天陽丸": "tenyo-maru",
    "鈴喜丸": "suzuki-maru-ajiro",
    "久寿丸": "kyuju-maru",
    "南伊豆忠兵衛丸": "minamiizu-chubee-maru",
    "二階屋丸": "nikaiya-maru",
    "村正丸": "muramasa-maru",
    "千とせ丸": "sentose-maru",
    "第十五祥運丸": "daijugo-shoun-maru",
    "ふじなみ丸": "fujinami-maru",
    "魚磯丸": "uoiso-maru",
    "ふじ丸": "fuji-maru",
    "直正丸": "naomasa-maru",
    "山川丸": "yamakawa-maru",
    "嘉丸": "ka-maru",
    "SHINSEIMARU": "shinsei-maru",
    "米丸": "kome-maru",
    "釣華丸（SEEKERS）": "tsurihana-maru-seekers",
    "恵丸": "megumi-maru",
    "もき丸": "moki-maru",
    "山大丸": "yamadai-maru",
    "富八丸": "tomihachi-maru",
    "Extreme": "extreme",
    "安菜丸": "anna-maru",
    "増福丸": "zofuku-maru",
    "冲帆丸": "chuho-maru",
    "菊丸": "kiku-maru",
    "興栄丸": "koei-maru-yaizu",
    "風神丸": "fujin-maru",
    "橋安丸": "hashian-maru",
}


def main():
    dry_run = "--dry-run" in sys.argv

    with open(SHIPS_PATH, encoding="utf-8") as f:
        ships = json.load(f)

    targets = [
        s
        for s in ships
        if str(s.get("romaji_slug", "")).startswith("chowari-")
        and not s.get("exclude")
    ]
    print(f"対象船宿: {len(targets)}件")

    # 既存slug（chowari-以外）と新slugの衝突チェック
    existing_slugs = {
        s["romaji_slug"]
        for s in ships
        if s.get("romaji_slug")
        and not str(s["romaji_slug"]).startswith("chowari-")
    }

    redirect_map = {}
    new_slug_seen = set()
    missing = []
    collisions = []

    for ship in targets:
        name = ship["name"]
        new_slug = MANUAL_OVERRIDE.get(name)
        if not new_slug:
            missing.append(name)
            continue
        if new_slug in existing_slugs:
            collisions.append((name, new_slug, "vs existing"))
            continue
        if new_slug in new_slug_seen:
            collisions.append((name, new_slug, "vs new batch"))
            continue
        new_slug_seen.add(new_slug)
        redirect_map[ship["romaji_slug"]] = new_slug

    if missing:
        print(f"\n[ERROR] 辞書漏れ {len(missing)}件:")
        for m in missing:
            print(f"  - {m}")
    if collisions:
        print(f"\n[ERROR] 衝突 {len(collisions)}件:")
        for name, slug, reason in collisions:
            print(f"  - {name} → {slug} ({reason})")
    if missing or collisions:
        print("\n中止。エラー解消してください。")
        sys.exit(1)

    print(f"\n=== 書き換え予定 {len(redirect_map)}件 ===")
    for old, new in list(redirect_map.items())[:10]:
        print(f"  {old:20s} -> {new}")
    print(f"  ... (残り {len(redirect_map)-10}件)")

    if dry_run:
        print("\n[DRY RUN] 書き込みスキップ")
        return

    # ships.json 更新
    for ship in ships:
        if ship.get("romaji_slug") in redirect_map:
            ship["romaji_slug"] = redirect_map[ship["romaji_slug"]]

    with open(SHIPS_PATH, "w", encoding="utf-8") as f:
        json.dump(ships, f, ensure_ascii=False, indent=2)
    print(f"\n[OK] ships.json 更新")

    with open(REDIRECT_MAP_PATH, "w", encoding="utf-8") as f:
        json.dump(redirect_map, f, ensure_ascii=False, indent=2)
    print(f"[OK] {REDIRECT_MAP_PATH} 出力 ({len(redirect_map)}件)")


if __name__ == "__main__":
    main()
