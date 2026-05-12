"""
T31 でクロールしてもゼロ件だった66隻について、
fishing-v.jp の choka_detail.php ページから「全 N件」表記を抽出して
「釣果0件の正常船宿」と「パースバグ疑い」を分類する。

使い方:
  python crawl/verify_zero_ships.py
  python crawl/verify_zero_ships.py --sleep 2.0
"""
import sys, os, re, time, json, argparse
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawler import fetch

URL = "https://www.fishing-v.jp/choka/choka_detail.php?s={sid}&pageID=1"

# T31 ゼロ件66隻 (sid, name, area)
ZERO_SHIPS = [
    (244, "庄三郎丸", "平塚港"),
    (11322, "湘南海成丸", "茅ヶ崎港"),
    (1482, "一俊丸", "茅ヶ崎港"),
    (1697, "又衛丸", "小田原早川港"),
    (808, "おおもり丸", "小田原早川港"),
    (692, "はやぶさ丸釣船店", "小柴港"),
    (10055, "アイランドクルーズ", "横浜港･新山下"),
    (212, "ムツ六釣船店", "久里浜港"),
    (689, "大正丸", "久里浜港"),
    (1684, "丸又丸", "松輪間口港"),
    (1962, "鈴茂丸", "松輪間口港"),
    (1963, "松雄丸", "松輪間口港"),
    (1959, "一郎丸", "松輪間口港"),
    (12222, "尚二郎丸", "松輪間口港"),
    (1685, "徳盛丸", "松輪間口港"),
    (1950, "勝洋丸", "長井新宿港"),
    (1936, "鈴清丸", "長井新宿港"),
    (1911, "かねい丸", "長井漆山港"),
    (1691, "岩田屋本店", "浦安"),
    (145, "たかはし遊船", "江戸川放水路･原木中山"),
    (153, "高常遊船", "江戸川放水路･原木中山"),
    (164, "かみや", "羽田"),
    (166, "えさ政釣船店", "羽田"),
    (724, "東丸", "保田港"),
    (122, "弥生丸", "保田港"),
    (125, "国丸", "保田港"),
    (2032, "ひらの丸", "富津港"),
    (12173, "みや川丸", "富津港"),
    (141, "川崎丸", "富津港"),
    (138, "鹿島丸", "富津港"),
    (135, "加平丸", "富津港"),
    (12126, "フィッシュオン大勝", "富津港"),
    (75, "義丸", "御宿岩和田港"),
    (74, "長栄丸", "御宿岩和田港"),
    (11411, "とみ丸", "勝浦川津港"),
    (82, "基吉丸", "勝浦川津港"),
    (83, "宏昌丸", "勝浦川津港"),
    (11937, "長岡丸", "鹿島港"),
    (11518, "宗和丸", "鹿島港"),
    (1678, "桜井丸", "鹿島港"),
    (20, "山正丸", "大洗港"),
    (22, "きよ丸", "大洗港"),
    (23, "福重丸", "大洗港"),
    (24, "第一東海丸", "大洗港"),
    (25, "弘清丸", "大洗港"),
    (787, "藤富丸", "大洗港"),
    (788, "昭栄丸", "大洗港"),
    (282, "勘七丸", "沼津内港"),
    (279, "潮丸", "沼津静浦"),
    (990, "海渡", "田子の浦港"),
    (1303, "つり正丸", "田子の浦港"),
    (989, "第五裕丸", "田子の浦港"),
    (991, "晴丸", "田子の浦港"),
    (1088, "大政丸", "由比"),
    (309, "稲荷丸", "由比"),
    (1087, "元吉丸", "由比"),
    (310, "第三龍神丸", "由比"),
    (1086, "福徳丸", "福田港"),
    (302, "勝栄丸", "福田港"),
    (1028, "龍栄丸", "福田港"),
    (303, "福寿丸", "福田港"),
    (1072, "フィッシングショップつり道場", "御前崎港"),
    (1051, "博洋丸", "御前崎港"),
    (1516, "海栄丸", "御前崎港"),
    (1666, "権助丸", "松崎港"),
    (801, "大喜丸", "網代"),
]


def extract_total(html):
    """HTMLから「全 N件」表記の N を抽出。見つからなければ None。"""
    if not html:
        return None
    # 「全 0件」「全 12件」「全1234件」など複数表記に対応
    m = re.search(r"全\s*([0-9,]+)\s*件", html)
    if m:
        try:
            return int(m.group(1).replace(",", ""))
        except ValueError:
            return None
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sleep", type=float, default=2.0)
    args = ap.parse_args()

    print(f"=== T31 ゼロ件 {len(ZERO_SHIPS)}隻 検証（fishing-v.jp 「全 N件」表記）===")
    print(f"  sleep={args.sleep}s")
    print(f"  対象先頭3: {ZERO_SHIPS[:3]}")
    print()

    results = []  # (sid, name, area, total, status)
    for i, (sid, name, area) in enumerate(ZERO_SHIPS, 1):
        url = URL.format(sid=sid)
        html = fetch(url)
        total = extract_total(html)
        if html is None:
            status = "FETCH_FAIL"
        elif total is None:
            status = "PARSE_FAIL"
        elif total == 0:
            status = "OK_ZERO"
        else:
            status = f"PARSE_BUG (page says {total})"
        results.append((sid, name, area, total, status))
        print(f"  [{i:3d}/{len(ZERO_SHIPS)}] sid={sid:6d} {name:20s} / {area:15s} → {status}")
        time.sleep(args.sleep)

    print()
    print("=== サマリー ===")
    from collections import Counter
    counter = Counter(r[4].split(" ")[0] for r in results)
    for k, v in counter.most_common():
        print(f"  {k}: {v}隻")

    # JSON 保存
    out = [{"sid": sid, "name": name, "area": area, "total": total, "status": status}
           for sid, name, area, total, status in results]
    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "verify_zero_ships_result.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"\n結果保存: {out_path}")

    # PARSE_BUG 一覧
    bugs = [r for r in results if r[4].startswith("PARSE_BUG")]
    if bugs:
        print(f"\n=== パースバグ疑い {len(bugs)}隻 ===")
        for sid, name, area, total, status in bugs:
            print(f"  sid={sid} {name} / {area} / ページ表記={total}件 / 取得=0件")


if __name__ == "__main__":
    main()
