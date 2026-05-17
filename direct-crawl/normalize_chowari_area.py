"""
normalize_chowari_area.py — chowari 経由船宿の area 名を既存釣りビジョン経由と整合させる

問題:
    register_chiba_sotobo.py / register_other_chowari.py で「飯岡漁港」「神栖市波崎港」
    のように chowari 上の正式名称で登録したため、既存 ships.json の「飯岡港」「波崎港」
    と area が一致せず、HTML 上で分断（area/iioka.html に新規船宿が出ない）

対応:
    既存 fv area を優先正規化。chowari 側を rename。
    手動マッピング辞書 + 自動部分一致 で対応。

実行:
    python direct-crawl/normalize_chowari_area.py [--dry-run]
"""

import json
import os
import sys
import re
import glob
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHIPS = os.path.join(ROOT, "crawl", "ships.json")

# 手動マッピング: chowari area → 既存 fv area
# 自動マッピングでカバーできない特殊ケース
MANUAL_MAP = {
    "飯岡漁港": "飯岡港",
    "外川漁港": "外川港",
    "波崎新港": "波崎新港",  # そのまま（既存にあるか確認後）
    "鹿嶋旧港": "鹿島",
    "鹿嶋新港": "鹿島",
    "大洗町大洗港": "大洗",
    "大洗町大洗河口": "大洗",
    "鉾田港": "鉾田",
    "涸沼": "涸沼",
    "久慈漁港": "久慈",
    "日立港": "日立",
    "平潟港": "平潟",
    "大津港": "大津",
    "河原子港": "河原子",
    "葉山町葉山鐙摺港": "葉山あぶずり港",
    "佐島港": "佐島",
    "長井漆山港": "長井漆山",
    "長井新宿港": "長井新宿港",  # 既存と一致
    "長井八幡": "長井",
    "横須賀市鴨居八景": "鴨居八景",
    "横浜港": "横浜",
    "横浜本牧港": "本牧",
    "湘南片瀬港": "片瀬漁港",
    "片瀬漁港": "片瀬漁港",   # 既存と一致
    "湘南江の島港": "江の島",
    "新安浦港": "新安浦",
    "走水港": "走水",
    "金沢八景": "金沢八景",   # 既存と一致
    "野毛屋八景": "金沢八景",
    "保土ヶ谷新山下": "新山下",
    "羽田": "羽田",           # 既存と一致
    "潮見運河": "潮見",
    "辰巳運河": "辰巳",
    "新木場運河": "新木場",
    "船橋大橋": "船橋",
    "勝浦マリンハーバー": "勝浦",
    "勝浦港": "勝浦",
    "川津港": "川津",
    "浜行川港": "浜行川",
    "天津小湊港": "天津小湊",
    "和田港": "和田",
    "江見漁港": "江見",
    "館山港": "館山",
    "洲崎栄ノ浦港": "洲崎",
    "洲崎漁港": "洲崎",
    "伊戸漁港": "伊戸",
    "川名漁港": "川名",
    "相浜港": "相浜",
    "片貝旧港": "片貝",
    "宇佐美港": "宇佐美港",   # 既存と一致
    "熱海港": "熱海港",       # 既存と一致
    "網代港": "網代港",       # 既存と一致
    "伊東港": "伊東",
    "下田港": "下田港",       # 既存と一致
    "下田須崎港": "下田",
    "東伊豆稲取港": "稲取",
    "南伊豆中木港": "南伊豆",
    "南伊豆雲見港": "雲見",
    "御前崎港": "御前崎港",   # 既存と一致
    "焼津漁港": "焼津",
    "清水港": "清水港",        # 既存「清水港」と統合
    "清水": "清水港",
    "大洗": "大洗港",          # 既存「大洗港」と統合（slug衝突回避）
    "片貝": "片貝港",          # 既存「片貝港」と統合
    "腰越漁港": "腰越港",      # 既存「腰越港」と統合
    "沼津港": "沼津港",       # 既存と一致
    "真鶴港": "真鶴港",       # 既存と一致
    "真鶴岩漁港": "真鶴港",   # 真鶴岩港 を真鶴港に統合
    "真鶴岩港": "真鶴港",
    "小田原早川港": "小田原港",
    "小田原港": "小田原港",   # 既存と一致
    "石巻牡蠣まる": "石巻",
    "横浜あみ平マリーナ": "横浜",
    "東京湾": "東京湾",
    "津久井浜": "津久井浜",
    "三崎漁港": "三崎",
    "松輪": "松輪間口",       # 既存「松輪間口」へ
    "剣崎": "剣崎",
    "久里浜港": "久里浜港",   # 既存と一致
    "茅ヶ崎漁港": "茅ヶ崎",
    "平塚漁港": "平塚港",     # 既存「平塚港」に統合
    "平塚新港": "平塚港",
    "湘南片瀬漁港": "片瀬漁港",
    "鎌倉腰越港": "腰越港",
    "鎌倉材木座": "材木座",
    "葉山あぶずり港": "葉山あぶずり港",   # 既存と一致
}

# fishing_v_zero 残しのため、area が "?" は触らない


def main():
    dry_run = "--dry-run" in sys.argv
    with open(SHIPS, encoding="utf-8") as f:
        ships = json.load(f)

    # 1) fv 側 area 一覧（chowari 以外）
    fv_areas = set(s.get("area") for s in ships
                   if not s.get("source_priority") or
                   "chowari" not in (s.get("source_priority") or []))

    # 2) chowari 側 area 一覧
    ch_ships = [s for s in ships if "chowari" in (s.get("source_priority") or [])
                and not s.get("exclude")]

    # 3) 自動マッピング: chowari area が "○○港" で、 fv に "○○港" あれば一致
    #    なければ "○○漁港" → "○○港" などの末尾置換で再試行
    auto_map = {}
    for s in ch_ships:
        ca = s.get("area", "")
        if not ca or ca == "?":
            continue
        # 既に一致
        if ca in fv_areas:
            continue
        # 手動マッピング適用
        if ca in MANUAL_MAP:
            auto_map[ca] = MANUAL_MAP[ca]
            continue
        # 末尾「漁港」「新港」「マリーナ」「ハーバー」「マリンハーバー」を「港」に置換
        candidates = [
            re.sub(r"(漁港|新港|マリンハーバー|マリーナ|ハーバー)$", "港", ca),
            re.sub(r"(漁港|新港|マリンハーバー|マリーナ|ハーバー|港)$", "", ca),  # 末尾全削除
            re.sub(r"^.*?市", "", ca),  # 市町村名を取り除く
            re.sub(r"^.*?町", "", ca),
            re.sub(r"^.*?村", "", ca),
        ]
        for cand in candidates:
            if cand and cand in fv_areas:
                auto_map[ca] = cand
                break

    # 4) マッピングがある場合のみ適用
    changes = 0
    print(f"=== area 正規化マッピング ===")
    print(f"対象 chowari 船宿: {len(ch_ships)}")
    print(f"  既に fv area 一致: {sum(1 for s in ch_ships if s.get('area') in fv_areas)}")
    print(f"  手動マッピング適用: {sum(1 for s in ch_ships if s.get('area') in MANUAL_MAP)}")
    print(f"  自動マッピング検出: {len(auto_map) - sum(1 for s in ch_ships if s.get('area') in MANUAL_MAP)}")
    print()
    print("=== 適用マッピング詳細 ===")
    applied = Counter()
    for s in ch_ships:
        ca = s.get("area", "")
        new = auto_map.get(ca) or MANUAL_MAP.get(ca)
        if new and new != ca:
            applied[(ca, new)] += 1
    for (old, new), n in sorted(applied.items(), key=lambda x: -x[1]):
        marker = "(既存一致)" if new in fv_areas else "(新規・既存になし)"
        print(f"  「{old}」→「{new}」 {n}隻 {marker}")

    # 5) 適用
    for s in ch_ships:
        ca = s.get("area", "")
        new = auto_map.get(ca) or MANUAL_MAP.get(ca)
        if new and new != ca:
            s["area"] = new
            changes += 1

    print()
    print(f"=== 変更: {changes}隻 ===")
    if not dry_run:
        with open(SHIPS, "w", encoding="utf-8") as f:
            json.dump(ships, f, ensure_ascii=False, indent=2)
        print("ships.json 更新")


if __name__ == "__main__":
    main()
