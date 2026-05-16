"""
register_b_group.py — B群16船宿を ships.json に一括登録するスクリプト

設計:
    - 既存 ships.json に同名で別船宿（別エリア）がある場合は別エントリで追加
      （稲荷丸: 既存 由比/静岡 + 新規 江見/千葉）
    - chowari_id 持つ16隻 + 釣りビジョン経由 1隻（坂口丸 sid=249）= 計17隻
    - 取込不可 3隻（源泉丸・寿々木丸・美智丸）はスキップ
    - 冪等: 既に登録済みなら何もしない

実行:
    python direct-crawl/register_b_group.py [--dry-run]
"""

import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHIPS = os.path.join(ROOT, "crawl", "ships.json")
TODAY = "2026-05-16"


# B群登録対象: (name, area, prefecture, chowari_id, sid, romaji_slug, official_url, source_priority, fishing_v_zero, notes)
B_GROUP = [
    # chowari 経由 16隻（ひろの丸は既登録のため除外）
    ("政勝丸",   "外川港",    "千葉",   "01495", None, "masakatsu-maru", "https://masakatsumaru.com/",            ["chowari"], True,  "アラ五目・沖メバル便。アラ実績11日/60日。Kansoにサメ要素あり"),
    ("清勝丸",   "飯岡港",    "千葉",   "00958", None, "seisho-maru",    "https://www.papipopo.com/SEISHOMARU/",  ["chowari"], True,  "アジ+ハナダイ五目 / 沖根魚(アラ・オニカサゴ)複合便"),
    ("丸天丸",   "波崎新港",  "茨城",   "01375", None, "marutenmaru",    "https://hasaki-0ten0.com/",             ["chowari"], True,  "深場専門。メヌケ船=メヌケ+アブラボウズ / アラ五目=アラ+オニカサゴ。サメ被害多"),
    ("浜べ丸",   "波崎港",    "茨城",   "00938", None, "hamabemaru",     "http://hamabehome.web.fc2.com/",        ["chowari"], True,  "鬼五目=オニカサゴ+アラ / ジギング青物=ワラサ+イナダ / ジギング五目=ヒラメ"),
    ("登喜丸",   "平塚港",    "神奈川", "01377", None, "toki-maru",      None,                                     ["chowari"], True,  "アカムツ専門(中深場ムツ系)"),
    ("孝漁丸",   "長井新宿港","神奈川", "00872", None, "koryo-maru",     None,                                     ["chowari"], True,  "ティップラン/SLJ/ファミリー/シロアマダイ/アカアマダイ"),
    ("山本丸",   "真鶴港",    "神奈川", "01368", None, "yamamoto-maru",  None,                                     ["chowari"], True,  "クロムツ・キンメ(直近休業中・FAQでは深場系)"),
    ("健海丸",   "長井新宿港","神奈川", "01466", None, "kenkai-maru",    None,                                     ["chowari"], True,  "キハダキャスティング+ティプラン / キャスティング青物 / カワハギ / アオリ / トラフグ"),
    ("治久丸",   "宇佐美港",  "静岡",   "00746", None, "haruhisa-maru",  "http://www.haruhisamaru.com/",          ["chowari"], True,  "カイワリ・イサキ(リレー) / マダイ / ヒラメ / アカハタ / 1日2便制"),
    ("かろうや丸","熱海港",   "静岡",   "00139", None, "karouya-maru",   None,                                     ["chowari"], True,  "マダイ / イサキ / ハナダイ / カンパチ / メジナ単独便"),
    ("稲荷丸-江見","江見漁港","千葉",   "00999", None, "inari-maru-emi", "https://inarimaru.jp/",                 ["chowari"], True,  "★アラ4日/60日 アラ釣り+アマダイ五目リレー・マダイ五目+アマダイ五目リレー。サメ被害多。既存「稲荷丸(由比)」と別船宿"),
    ("まなぶ丸", "片瀬漁港",  "神奈川", "01030", None, "manabu-maru",    None,                                     ["chowari"], True,  "アマダイ五目船 / 根魚五目船(深場五目)"),
    ("かりゆし丸","平塚新港", "神奈川", "00908", None, "kariyushi-maru", "https://kariyusimaru.com/",             ["chowari"], True,  "五目(アジ・アマダイ・サバ・カサゴ) / ショートルアー"),
    ("裕海丸",   "熱海港",    "静岡",   "00179", None, "hiromi-maru",    "http://hiromimaru-atami.com/",          ["chowari"], True,  "イサキ乗合船 / 根魚乗合船"),
    ("第八緑龍丸","真鶴岩漁港","神奈川","01689", None, "ryokuryu-8maru", "https://ryokuryu2.com/",                ["chowari"], True,  "アオリイカ / アカハタ / カワハギ / キハダ / アジ / カサゴ(浅~中場マルチ)"),

    # 釣りビジョン経由 1隻（chowari 専用ページなし・電話予約のみ）
    ("坂口丸",   "小田原早川港","神奈川", None,  249,  "sakaguchi-maru", "https://sakaguchimaru.com/",            ["fishing_v"], False, "釣りビジョン経由。直近2024/9更新停止状態だが全62件の過去データあり。キハダマグロ・アマダイ・イナダ"),
]

# スキップ（chowari未登録・独自サイトECONNREFUSED）
SKIPPED = [
    "源泉丸（川津・千葉）: chowari 未登録・独自サイト ECONNREFUSED → Ameba 経由要",
    "寿々木丸（天津小湊・千葉）: chowari 未登録・独自サイト ECONNREFUSED",
    "美智丸（和田・千葉）: chowari 未登録",
]


def main():
    dry_run = "--dry-run" in sys.argv

    with open(SHIPS, encoding="utf-8") as f:
        ships = json.load(f)

    # 既存登録チェック
    existing_pairs = {(s.get("name"), s.get("area")) for s in ships}

    added = []
    skipped = []
    for name, area, pref, chowari_id, sid, slug, url, src_pri, fv_zero, notes in B_GROUP:
        # 表示用 name は「稲荷丸-江見」のような区別なし版に正規化
        display_name = name.split("-")[0]
        key = (display_name, area)
        if key in existing_pairs:
            skipped.append(f"{display_name} ({area}): 既存登録")
            continue
        entry = {
            "sid":           sid,
            "name":          display_name,
            "area":          area,
            "chowari_id":    chowari_id,
            "castingnet_id": None,
            "official_url":  url,
            "romaji_slug":   slug,
            "phone":         "",
            "address":       f"{pref}{area}",
            "business_hours": "記載なし",
            "closed_days":   "記載なし",
            "source_priority": src_pri,
            "notes":         notes,
        }
        if fv_zero:
            entry["fishing_v_zero"] = True
            entry["fishing_v_zero_verified_at"] = TODAY
        added.append(entry)

    print(f"=== B群一括登録 (dry_run={dry_run}) ===")
    print(f"追加対象: {len(added)}件 / スキップ(既存): {len(skipped)}件")
    print()
    print("--- 追加対象 ---")
    for e in added:
        sid_str = f"fishing_v={e['sid']}" if e['sid'] else "fishing_v=未登録"
        cid_str = f"chowari={e['chowari_id']}" if e['chowari_id'] else "chowari=なし"
        print(f"  {e['name']} ({e['area']}): {sid_str} / {cid_str}")
    if skipped:
        print()
        print("--- スキップ ---")
        for s in skipped:
            print(f"  {s}")
    print()
    print("--- スキップ船宿（chowari未登録）---")
    for s in SKIPPED:
        print(f"  {s}")

    if not dry_run:
        ships.extend(added)
        with open(SHIPS, "w", encoding="utf-8") as f:
            json.dump(ships, f, ensure_ascii=False, indent=2)
        print()
        print(f"ships.json 更新: 総数 {len(ships)} 隻")


if __name__ == "__main__":
    main()
