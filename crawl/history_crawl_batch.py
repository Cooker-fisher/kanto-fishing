"""
復活させた21船宿の過去データを一括取得するスクリプト。
history_crawl_single.py を順番に呼び出す。

使い方:
  python crawl/history_crawl_batch.py
  python crawl/history_crawl_batch.py --sleep 2.5
"""
import subprocess, sys, time, argparse, os

SHIPS = [
    (35,    "信栄丸",     "波崎港"),
    (58,    "勇幸丸",     "片貝港"),
    (140,   "浜新丸",     "富津港"),
    (174,   "三喜丸釣船店", "小柴港"),
    (187,   "新修丸",     "金沢八景"),
    (188,   "米元釣船店",  "金沢八景"),
    (189,   "荒川屋",     "金沢八景"),
    (190,   "弁天屋",     "金沢八景"),
    (204,   "春盛丸",     "長井漆山港"),
    (219,   "栃木丸",     "長井新宿港"),
    (221,   "儀兵衛丸",   "長井港"),
    (224,   "つね丸",     "佐島"),
    (253,   "太郎丸",     "小坪港"),
    (671,   "棒面丸",     "松輪江奈港"),
    (690,   "平作丸",     "久里浜港"),
    (1005,  "とうふや丸",  "大磯港"),
    (1750,  "小柴丸",     "金沢八景"),
    (1778,  "大和丸",     "小網代港"),
    (1946,  "孝徳丸",     "片貝港"),
    (2006,  "美喜丸",     "松輪江奈港"),
    (11364, "洋征丸",     "小坪港"),
]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sleep", type=float, default=2.0, help="リクエスト間隔(秒)")
    ap.add_argument("--max-pages", type=int, default=200)
    args = ap.parse_args()

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    script = os.path.join(root, "crawl", "history_crawl_single.py")

    print(f"=== 21船宿 過去データ一括取得 sleep={args.sleep}s ===\n")

    for i, (sid, name, area) in enumerate(SHIPS, 1):
        print(f"[{i:2d}/{len(SHIPS)}] {name} (SID={sid}, {area})")
        cmd = [
            sys.executable, script,
            "--sid",       str(sid),
            "--name",      name,
            "--area",      area,
            "--sleep",     str(args.sleep),
            "--max-pages", str(args.max_pages),
        ]
        subprocess.run(cmd, cwd=root)
        if i < len(SHIPS):
            gap = args.sleep * 3
            print(f"  → 次の船宿まで {gap:.0f}s 待機\n")
            time.sleep(gap)

    print("\n=== 全船宿完了 ===")

if __name__ == "__main__":
    main()
