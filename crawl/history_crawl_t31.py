"""
T31 (2026/05/12) で追加した未取得 active 船宿の過去3年データを一括取得するスクリプト。

ships.json から exclude/boat_only でない active 船宿を読み込み、
catches_raw.json に未登録の船宿のみを対象に history_crawl_single.py を順次呼ぶ。

CUTOFF（取得下限）は history_crawl_single.py の "2023/04/04" を使用（既存船宿と同期間）。

使い方:
  python crawl/history_crawl_t31.py                       # 自動抽出・本実行
  python crawl/history_crawl_t31.py --dry-run             # 対象船宿一覧のみ表示
  python crawl/history_crawl_t31.py --limit 5             # 先頭5隻だけテスト
  python crawl/history_crawl_t31.py --max-pages 10        # 1隻あたり10page まで
  python crawl/history_crawl_t31.py --sleep 2.0 --gap 6.0 # 既存デフォルト
"""
import subprocess, sys, time, argparse, os, json

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHIPS_JSON = os.path.join(ROOT, "crawl", "ships.json")
RAW_JSON = os.path.join(ROOT, "crawl", "catches_raw.json")
SINGLE_SCRIPT = os.path.join(ROOT, "crawl", "history_crawl_single.py")


def collect_target_ships():
    """ships.json から active かつ catches_raw.json に未登録の船宿を抽出。
    既存 (sid, name, area) タプル形式で返す。"""
    with open(SHIPS_JSON, encoding="utf-8") as f:
        ships = json.load(f)
    with open(RAW_JSON, encoding="utf-8") as f:
        raw = json.load(f)
    existing_ships = {r.get("ship", "") for r in raw if r.get("ship")}

    targets = []
    for s in ships:
        if s.get("exclude") or s.get("boat_only"):
            continue
        sid = s.get("sid")
        name = s.get("name")
        area = s.get("area")
        if not (isinstance(sid, int) and name and area):
            continue
        if name in existing_ships:
            continue
        targets.append((sid, name, area))
    return targets


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sleep", type=float, default=2.0, help="1ページあたりリクエスト間隔(秒)")
    ap.add_argument("--gap", type=float, default=6.0, help="船宿間の待機(秒)")
    ap.add_argument("--max-pages", type=int, default=200, help="1隻あたり最大ページ数")
    ap.add_argument("--limit", type=int, default=None, help="先頭N隻だけ（テスト用）")
    ap.add_argument("--dry-run", action="store_true", help="対象船宿一覧のみ表示")
    args = ap.parse_args()

    targets = collect_target_ships()
    if args.limit:
        targets = targets[: args.limit]

    print(f"=== T31 過去クロール: 対象 {len(targets)}隻 ===")
    print(f"  sleep={args.sleep}s / gap={args.gap}s / max-pages={args.max_pages}")
    print(f"  先頭3隻: {targets[:3]}")
    if args.dry_run:
        for i, (sid, name, area) in enumerate(targets, 1):
            print(f"  [{i:3d}] sid={sid:6d} {name} / {area}")
        return

    failures = []
    for i, (sid, name, area) in enumerate(targets, 1):
        print(f"\n[{i:3d}/{len(targets)}] {name} (SID={sid}, {area})")
        cmd = [
            sys.executable, SINGLE_SCRIPT,
            "--sid", str(sid),
            "--name", name,
            "--area", area,
            "--sleep", str(args.sleep),
            "--max-pages", str(args.max_pages),
        ]
        result = subprocess.run(cmd, cwd=ROOT)
        if result.returncode != 0:
            print(f"  ! WARN: subprocess returncode={result.returncode}")
            failures.append((sid, name, area, result.returncode))
        if i < len(targets):
            print(f"  -> 次の船宿まで {args.gap:.0f}s 待機")
            time.sleep(args.gap)

    print(f"\n=== 全 {len(targets)}隻 完了 ===")
    if failures:
        print(f"失敗 {len(failures)}件:")
        for sid, name, area, rc in failures:
            print(f"  sid={sid} {name} / {area} returncode={rc}")


if __name__ == "__main__":
    main()
