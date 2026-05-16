"""
register_chiba_sotobo.py — 千葉外房26隻を ships.json に一括登録

調査結果:
    - 全 26 隻ともアラ実績ゼロ
    - 価値: 出船頻度・複合主役（リレー船・五目）便の蓄積に貢献
    - 複合主役候補 11隻 / 単独 15隻

実行:
    python direct-crawl/register_chiba_sotobo.py [--dry-run]
"""

import json, os, sys
sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHIPS = os.path.join(ROOT, "crawl", "ships.json")
TODAY = "2026-05-17"


# (name, area, prefecture, chowari_id, romaji_slug, official_url, notes)
CHIBA_SOTOBO = [
    # 飯岡漁港 (旭市) - 3隻
    ("隆正丸", "飯岡漁港", "千葉", "00629", "ryusho-maru-iioka", None,
     "18号フグ五目便/コマセアジ船。ショウサイフグ・アジ・トラフグ。浅〜中場10-30m"),
    ("龍鳳丸", "飯岡漁港", "千葉", "00952", "ryuho-maru-iioka", None,
     "ハナダイ便/フグ/アジ。ハナダイメインのコマセ系"),
    ("優光丸", "飯岡漁港", "千葉", "00953", "yuko-maru-iioka", None,
     "一つテンヤ真鯛 朝便+午後便。マダイ専門"),

    # 大原港 (いすみ市) - 9隻
    ("富士丸", "大原港", "千葉", "00136", "fuji-maru-oohara", None,
     "マダイ船 午前午後便。マダイ・ハタ・カサゴ"),
    ("長福丸", "大原港", "千葉", "00534", "chofuku-maru", None,
     "マダイ便/イサキ便。イサキ・マダイ・ワラサ"),
    ("板倉丸", "大原港", "千葉", "00765", "itakura-maru", None,
     "青物+根魚五目。マハタ・ハマチ/ワラサ・ヒラマサ"),
    ("加幸丸", "大原港", "千葉", "00773", "kako-maru", None,
     "ハタ釣り・五目釣り。ハタ・マハタ・ヒラメ"),
    ("松栄丸", "大原港", "千葉", "00779", "shoei-maru-oohara", None,
     "イサキ・ヤリイカ。イサキ.シマアジ狙い複合便"),
    ("春栄丸", "大原港", "千葉", "00788", "shunei-maru", None,
     "午前イサキ(シマアジ)・午後マダイ。2部制 trip 分割"),
    ("利永丸", "大原港", "千葉", "00789", "rieiei-maru", None,
     "イサキ専門。大原沖25m浅場"),
    ("隆光丸", "大原港", "千葉", "01344", "ryuko-maru-oohara", None,
     "ヤリイカ・ハタ・ヒラメ。深場根魚五目"),
    ("義丸", "大原港", "千葉", "01718", "yoshi-maru-oohara", None,
     "マダイ・イサキ・ヤリイカ・ヒラマサ・マハタ。多魚種"),

    # 館山市 - 6隻
    ("早川丸", "洲崎栄ノ浦港", "千葉", "00293", "hayakawa-maru-sunosaki", None,
     "イサキ専門。2隻並行運航・カワハギ・スルメイカ"),
    ("赤沼丸", "洲崎栄ノ浦港", "千葉", "01418", "akanuma-maru", None,
     "近海スロー船+テンヤルアー船。ハチビキ・メダイ・ムツ系深場"),
    ("九左衛門丸", "伊戸漁港", "千葉", "00983", "kuzaemon-maru", None,
     "マダイ専門。シマアジ・ワラサ・カンパチ"),
    ("竜一丸", "川名漁港", "千葉", "00987", "ryuichi-maru-kawana", None,
     "イサキ専門。マダイ・ウマズラハギ"),
    ("第2美吉丸", "洲崎漁港", "千葉", "00989", "miyoshi-maru-2", None,
     "午前午後根魚+タイ。マダイ・カサゴ・マハタ。サメ被害言及あり(5/12)"),
    ("安田丸", "相浜港", "千葉", "01047", "yasuda-maru-aihama", None,
     "シマアジ乗合。シマアジ・マダイ・イサキ"),

    # 勝浦市 - 4隻
    ("作栄丸", "浜行川港", "千葉", "00125", "sakuei-maru", None,
     "ヤリイカ・マダイ・カンパチ"),
    ("With-Ocean", "勝浦マリンハーバー", "千葉", "00696", "with-ocean", None,
     "イサキ専門。ウマヅラハギ・カサゴ"),
    ("勝丸-勝浦-", "勝浦港", "千葉", "01002", "katsu-maru-katsuura", None,
     "ヤリイカ専門。スルメイカ・サバ"),
    ("新勝丸", "川津港", "千葉", "01167", "shinkatsu-maru", None,
     "ヒラマサ・サンパク・ワラサ"),

    # 片貝旧港 (山武市) - 3隻
    ("幸辰丸", "片貝旧港", "千葉", "00626", "kotatsu-maru", None,
     "★イサキハナダイリレー船。複合主役 {イサキ, ハナダイ}"),
    ("第1二三丸", "片貝旧港", "千葉", "00628", "dai1-fumi-maru", None,
     "イサキ・キンメ・ハナダイ。キンメ実績あり深場系"),
    ("第三孝徳丸", "片貝旧港", "千葉", "00763", "dai3-kotoku-maru", None,
     "★イサキ花鯛リレー釣り。複合主役 {イサキ, ハナダイ}"),

    # 江見漁港 (鴨川市) - 1隻
    ("新栄丸", "江見漁港", "千葉", "00476", "shinei-maru-emi", None,
     "★黒ムツ・マダイ五目 リレー船。複合主役 {クロムツ, マダイ}。深場系"),
]


def main():
    dry_run = "--dry-run" in sys.argv
    with open(SHIPS, encoding="utf-8") as f:
        ships = json.load(f)
    existing = {(s.get("name"), s.get("area")) for s in ships}

    added = []
    skipped = []
    for name, area, pref, cid, slug, url, notes in CHIBA_SOTOBO:
        if (name, area) in existing:
            skipped.append(f"{name} ({area}) 既存")
            continue
        entry = {
            "sid": None,
            "name": name,
            "area": area,
            "chowari_id": cid,
            "castingnet_id": None,
            "official_url": url,
            "romaji_slug": slug,
            "phone": "",
            "address": f"{pref}{area}",
            "business_hours": "記載なし",
            "closed_days": "記載なし",
            "fishing_v_zero": True,
            "fishing_v_zero_verified_at": TODAY,
            "source_priority": ["chowari"],
            "notes": notes,
        }
        added.append(entry)

    print(f"=== 千葉外房26隻 一括登録 (dry={dry_run}) ===")
    print(f"追加: {len(added)} / スキップ: {len(skipped)}")
    if skipped:
        print("--- スキップ ---")
        for s in skipped:
            print(f"  {s}")
    print()
    print("--- 追加対象 ---")
    for e in added:
        print(f"  {e['name']} ({e['area']}) chowari={e['chowari_id']}")
    if not dry_run:
        ships.extend(added)
        with open(SHIPS, "w", encoding="utf-8") as f:
            json.dump(ships, f, ensure_ascii=False, indent=2)
        print(f"\nships.json 更新: 総数 {len(ships)} 隻")


if __name__ == "__main__":
    main()
