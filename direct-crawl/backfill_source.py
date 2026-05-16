"""
backfill_source.py — 既存 Raw JSON / V2 CSV に source 列を遡及付与する1回限りの補修スクリプト

source 値:
    "釣りビジョン"         : crawler.py 本流（A1）が釣りビジョン choka API から取得
    "直サイト/gyo"         : gyo_crawler.py が船宿独自サイトから取得（一之瀬丸・忠彦丸・米元・大栄丸）
    "chowari/ひろの丸"     : hirono_crawler.py が chowari.jp から取得

実行:
    python direct-crawl/backfill_source.py [--dry-run]

冪等性: 既に source が付いているレコードはスキップ。
"""

import csv
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_FISHING_V = os.path.join(ROOT, "crawl",        "catches_raw.json")
RAW_DIRECT    = os.path.join(ROOT, "direct-crawl", "catches_raw_direct.json")
RAW_HIRONO    = os.path.join(ROOT, "direct-crawl", "catches_raw_hirono.json")
V2_DIR        = os.path.join(ROOT, "data", "V2")

# 各 Raw JSON ファイルのデフォルト source
SOURCE_OF_RAW = {
    RAW_FISHING_V: "釣りビジョン",
    RAW_DIRECT:    "直サイト/gyo",
    RAW_HIRONO:    "chowari/ひろの丸",
}

# 船宿名 → source の判定（CSV側で使用・ship名から推定）
SHIP_SOURCE_OVERRIDE = {
    "一之瀬丸": "直サイト/gyo",
    "忠彦丸":   "直サイト/gyo",
    "米元":     "直サイト/gyo",
    "大栄丸":   "直サイト/gyo",
    "ひろの丸": "chowari/ひろの丸",
}
DEFAULT_SHIP_SOURCE = "釣りビジョン"


def backfill_raw(path: str, default_source: str, dry_run: bool):
    """Raw JSON の source 欠損レコードに既定値を付与"""
    if not os.path.exists(path):
        print(f"  SKIP: {path}（存在しない）")
        return 0, 0
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        print(f"  SKIP: {path}（リスト形式ではない）")
        return 0, 0
    total = len(data)
    missing = 0
    for r in data:
        if not r.get("source"):
            r["source"] = default_source
            missing += 1
    print(f"  {os.path.basename(path)}: 総数={total} / source欠損={missing} → 付与=「{default_source}」")
    if not dry_run and missing > 0:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"    上書き保存")
    return total, missing


def backfill_csv(path: str, dry_run: bool):
    """V2 CSV の末尾に source 列を追加（既存39列 → 40列化）。既に40列なら何もしない。"""
    with open(path, encoding="utf-8", newline="") as f:
        rdr = csv.DictReader(f)
        cols = rdr.fieldnames or []
        rows = list(rdr)
    if "source" in cols:
        return len(rows), 0   # 既に列あり → スキップ
    # 各行に source 列追加（ship 名で推定）
    new_cols = list(cols) + ["source"]
    added = 0
    for r in rows:
        ship = r.get("ship", "")
        r["source"] = SHIP_SOURCE_OVERRIDE.get(ship, DEFAULT_SHIP_SOURCE)
        added += 1
    if not dry_run:
        with open(path, "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=new_cols)
            w.writeheader()
            for r in rows:
                w.writerow(r)
    return len(rows), added


def main():
    dry_run = "--dry-run" in sys.argv
    print(f"=== backfill_source.py (dry_run={dry_run}) ===")
    print()

    # 1. Raw JSON の補修
    print("--- Raw JSON ---")
    total_raw = 0
    total_missing = 0
    for path, default in SOURCE_OF_RAW.items():
        t, m = backfill_raw(path, default, dry_run)
        total_raw += t
        total_missing += m
    print(f"  合計: {total_raw}レコード / source欠損補修={total_missing}件")

    # 2. data/V2/*.csv の補修
    print()
    print("--- data/V2/*.csv ---")
    csv_total = 0
    csv_added = 0
    files_modified = 0
    if os.path.isdir(V2_DIR):
        for fname in sorted(os.listdir(V2_DIR)):
            if not fname.endswith(".csv"):
                continue
            path = os.path.join(V2_DIR, fname)
            t, a = backfill_csv(path, dry_run)
            csv_total += t
            csv_added += a
            if a > 0:
                files_modified += 1
                print(f"  {fname}: {t}行 → source列追加={a}行")
    print(f"  合計: {csv_total}行 / 列追加={csv_added}行 / 更新ファイル={files_modified}個")

    if dry_run:
        print()
        print("(dry-run: 書き込みスキップ)")


if __name__ == "__main__":
    main()
