#!/usr/bin/env python3
"""
CSVスキーマ変換スクリプト migrate_csv.py

[変換内容]
- point_place: 複合表記を分割
    「観音崎沖～走水沖タナ50～60m・」
    -> point_place=観音崎沖, point_place2=走水沖, depth_min=50, depth_max=60

- point_depth: 既存の水深列を min/max に分割
    「20m」   -> depth_min=20, depth_max=20
    「5～10m」 -> depth_min=5,  depth_max=10
    「13m前後」-> depth_min=13, depth_max=13

[優先順位]
    point_place 内の タナ が最優先
    なければ point_depth を使用

[旧スキーマ]
    ..., point_place, point_depth

[新スキーマ]
    ..., point_place, point_place2, point_depth_min, point_depth_max

[実行]
    python migrate_csv.py          # data/*.csv を全て変換（上書き）
    python migrate_csv.py --dry-run  # 変換結果を確認のみ（上書きしない）
"""

import csv, os, re, sys
from copy import deepcopy

OLD_HEADER = [
    "ship", "area", "date", "fish",
    "cnt_min", "cnt_max", "cnt_avg",
    "size_min", "size_max",
    "kg_min", "kg_max",
    "is_boat", "point_place", "point_depth",
]

NEW_HEADER = [
    "ship", "area", "date", "fish",
    "cnt_min", "cnt_max", "cnt_avg",
    "size_min", "size_max",
    "kg_min", "kg_max",
    "is_boat", "point_place", "point_place2",
    "point_depth_min", "point_depth_max",
]


def parse_depth(text):
    """
    水深文字列から (min, max) を返す。取れなければ (None, None)。
    例: "20m" -> (20, 20)
        "5～10m" -> (5, 10)
        "13m前後" -> (13, 13)
        "50～60m・" -> (50, 60)
    """
    if not text:
        return None, None
    text = text.strip().rstrip('・').strip()
    # 範囲: N～Mm
    m = re.search(r'(\d+)\s*[〜~～]\s*(\d+)\s*m', text)
    if m:
        return int(m.group(1)), int(m.group(2))
    # 単一: Nm
    m = re.search(r'(\d+)\s*m', text)
    if m:
        v = int(m.group(1))
        return v, v
    return None, None


def parse_point_place(raw):
    """
    point_place の生テキストを分解して返す。
    戻り値: (point1, point2, depth_min, depth_max)

    例:
        「観音崎沖～走水沖タナ50～60m・」-> (観音崎沖, 走水沖, 50, 60)
        「鎌倉沖～城ヶ島沖タナ57～108m」-> (鎌倉沖, 城ヶ島沖, 57, 108)
        「相模湾タナ5～40m」            -> (相模湾, None, 5, 40)
        「木更津沖」                    -> (木更津沖, None, None, None)
        「横浜沖～観音崎沖」            -> (横浜沖, 観音崎沖, None, None)
    """
    if not raw:
        return "", None, None, None

    text = raw.strip().rstrip('・').strip()

    # タナ・水深以降を分離して水深を取得
    depth_min = depth_max = None
    for keyword in ('タナ', '水深'):
        if keyword in text:
            idx = text.index(keyword)
            depth_str = text[idx + len(keyword):]
            depth_min, depth_max = parse_depth(depth_str + 'm' if 'm' not in depth_str else depth_str)
            text = text[:idx].strip()
            break

    # 残りの地名部分を「〜」または「・」で分割
    text = text.rstrip('・').strip()
    parts = re.split(r'[〜～~・]', text)
    point1 = parts[0].strip() if len(parts) > 0 else ""
    point2 = parts[1].strip() if len(parts) > 1 else None

    # point1 == point2 の重複は除去
    if point2 == point1:
        point2 = None

    # 空文字は None に統一
    if not point1: point1 = ""
    if point2 == "": point2 = None

    return point1, point2, depth_min, depth_max


def migrate_row(row):
    """旧スキーマのrowを新スキーマに変換して返す。
    旧スキーマAの point_place/point_depth 形式と
    旧スキーマB（古い日次クローラー）の point 形式の両方に対応。
    """
    # 旧スキーマB: point列（古い日次クローラー）
    if "point_place" not in row:
        raw_place = row.get("point", "")
        raw_depth = ""
    else:
        raw_place = row.get("point_place", "")
        raw_depth = row.get("point_depth", "")

    point1, point2, d_min, d_max = parse_point_place(raw_place)

    # タナからdepthが取れなければ point_depth 列を使用
    if d_min is None:
        d_min, d_max = parse_depth(raw_depth)

    return {
        "ship":            row["ship"],
        "area":            row["area"],
        "date":            row["date"],
        "fish":            row["fish"],
        "cnt_min":         row.get("cnt_min", ""),
        "cnt_max":         row.get("cnt_max", ""),
        "cnt_avg":         row.get("cnt_avg", ""),
        "size_min":        row["size_min"],
        "size_max":        row["size_max"],
        "kg_min":          row["kg_min"],
        "kg_max":          row["kg_max"],
        "is_boat":         row["is_boat"],
        "point_place":     point1,
        "point_place2":    point2 or "",
        "point_depth_min": d_min if d_min is not None else "",
        "point_depth_max": d_max if d_max is not None else "",
    }


def migrate_file(filepath, dry_run=False):
    with open(filepath, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    if not rows:
        return 0

    new_rows = [migrate_row(r) for r in rows]

    if not dry_run:
        with open(filepath, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=NEW_HEADER)
            writer.writeheader()
            writer.writerows(new_rows)

    return len(new_rows)


def main():
    dry_run = "--dry-run" in sys.argv

    if dry_run:
        print("=== DRY RUN（上書きしません）===")
    else:
        print("=== migrate_csv.py 実行 ===")

    # 動作確認サンプル
    samples = [
        "観音崎沖～走水沖タナ50～60m・",
        "鎌倉沖～城ヶ島沖タナ57～108m",
        "相模湾タナ5～40m",
        "木更津沖",
        "横浜沖～観音崎沖",
        "南沖",
        "",
    ]
    print("\n[パース確認]")
    for s in samples:
        p1, p2, dmin, dmax = parse_point_place(s)
        print(f"  {repr(s):45s} -> point1={p1!r:15} point2={p2!r:15} depth={dmin}~{dmax}")

    print()
    total = 0
    for fname in sorted(os.listdir("data")):
        if not fname.endswith(".csv"):
            continue
        fpath = f"data/{fname}"
        n = migrate_file(fpath, dry_run=dry_run)
        total += n
        print(f"  {fname}: {n}行{'（変換済み）' if not dry_run else '（確認のみ）'}")

    print(f"\n合計: {total}行")
    if not dry_run:
        print("スキーマ変換完了。旧カラム point_depth を削除し、point_place2 / point_depth_min / point_depth_max を追加しました。")


if __name__ == "__main__":
    main()
