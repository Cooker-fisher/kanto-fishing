#!/usr/bin/env python3
"""
釣りポイント名 -> 緯度経度 自動推定スクリプト

[処理フロー]
1. data/YYYY-MM.csv の point_place を全集計
2. ポイント名を正規化（先頭地名を抽出）
3. Nominatim (OpenStreetMap) で緯度経度を自動検索
4. point_coords.json に保存（未解決は lat/lon を null で出力）

[手動確認]
- point_coords.json を開いて lat/lon が null のものや
  明らかにおかしいものを修正する
- 修正後はそのまま weather_history_points.py で利用される

[実行]
  python build_point_coords.py
"""

import csv, json, os, re, time
from urllib.request import urlopen, Request
from urllib.parse import quote
from collections import Counter

# ── 固定漁場名・主要ポイント（座標既知のもの） ───────────────────────
KNOWN_COORDS = {
    # 漁場名（住所検索不可）
    "中ノ瀬":       {"lat": 35.40, "lon": 139.78},  # 東京湾中央
    "中の瀬":       {"lat": 35.40, "lon": 139.78},
    "沖ノ瀬":       {"lat": 34.95, "lon": 139.55},  # 相模湾外
    "カンネコ根":   {"lat": 35.15, "lon": 139.90},  # 東京湾口
    "第二海堡沖":   {"lat": 35.32, "lon": 139.78},
    "第2海堡沖":    {"lat": 35.32, "lon": 139.78},
    "第一海堡沖":   {"lat": 35.35, "lon": 139.75},
    "海堡沖":       {"lat": 35.32, "lon": 139.78},
    "盤洲沖":       {"lat": 35.44, "lon": 139.90},
    "盤津沖":       {"lat": 35.44, "lon": 139.90},
    "相模湾":       {"lat": 35.05, "lon": 139.40},
    "東京湾":       {"lat": 35.40, "lon": 139.75},
    # 神奈川東京湾
    "横浜沖":       {"lat": 35.42, "lon": 139.65},
    "川崎沖":       {"lat": 35.50, "lon": 139.73},
    "鶴見沖":       {"lat": 35.51, "lon": 139.70},
    "本牧沖":       {"lat": 35.41, "lon": 139.67},
    "南本牧沖":     {"lat": 35.40, "lon": 139.67},
    "八景沖":       {"lat": 35.37, "lon": 139.62},
    "小柴沖":       {"lat": 35.36, "lon": 139.63},
    "鴨居沖":       {"lat": 35.34, "lon": 139.64},
    "観音崎沖":     {"lat": 35.28, "lon": 139.73},
    "走水沖":       {"lat": 35.30, "lon": 139.76},
    "久里浜沖":     {"lat": 35.24, "lon": 139.71},
    "横須賀沖":     {"lat": 35.28, "lon": 139.68},
    "猿島沖":       {"lat": 35.30, "lon": 139.68},
    "富岡沖":       {"lat": 35.36, "lon": 139.62},
    "羽田沖":       {"lat": 35.55, "lon": 139.76},
    "浦安沖":       {"lat": 35.65, "lon": 139.90},
    "千葉沖":       {"lat": 35.61, "lon": 140.05},
    "千葉市沖":     {"lat": 35.61, "lon": 140.05},
    "長浦沖":       {"lat": 35.37, "lon": 139.84},
    # 千葉内房
    "木更津沖":     {"lat": 35.37, "lon": 139.88},
    "富津沖":       {"lat": 35.32, "lon": 139.82},
    "竹岡沖":       {"lat": 35.22, "lon": 139.79},
    "金谷沖":       {"lat": 35.19, "lon": 139.77},
    "金谷沖浅場":   {"lat": 35.20, "lon": 139.79},
    "大貫沖":       {"lat": 35.27, "lon": 139.79},
    "保田沖":       {"lat": 35.08, "lon": 139.73},
    "富浦沖":       {"lat": 34.97, "lon": 139.74},
    "館山沖":       {"lat": 34.96, "lon": 139.85},
    "洲崎沖":       {"lat": 34.94, "lon": 139.80},
    # 神奈川相模湾
    "剣崎沖":       {"lat": 35.14, "lon": 139.65},
    "三戸浜沖":     {"lat": 35.19, "lon": 139.61},
    "長井沖":       {"lat": 35.19, "lon": 139.60},
    "秋谷沖":       {"lat": 35.22, "lon": 139.55},
    "城ヶ島沖":     {"lat": 35.12, "lon": 139.61},
    "城ヶ島西沖":   {"lat": 35.12, "lon": 139.57},
    "鎌倉沖":       {"lat": 35.27, "lon": 139.55},
    "小坪沖":       {"lat": 35.28, "lon": 139.57},
    "江の島沖":     {"lat": 35.28, "lon": 139.49},
    "茅ヶ崎沖":     {"lat": 35.30, "lon": 139.39},
    "二宮沖":       {"lat": 35.29, "lon": 139.27},
    "下浦沖":       {"lat": 35.18, "lon": 139.67},
    # 茨城
    "北沖30":       {"lat": 36.30, "lon": 140.70},
}

# ── 抽象的で位置不明なポイント名（スキップ） ─────────────────────────
SKIP_NAMES = {"近場", "深場", "東京湾一帯"}

# ── ポイント名正規化 ─────────────────────────────────────────────────

def normalize_point(raw):
    """
    「鎌倉沖～城ヶ島沖タナ57～108m」->「鎌倉沖」（先頭地名を返す）
    「相模湾タナ5～40m」->「相模湾」
    「木更津沖～横浜沖」->「木更津沖」
    """
    # 「タナ」以降を除去
    s = re.sub(r'タナ.*', '', raw)
    # 「〜」「～」以降を除去（複合ポイント->先頭のみ）
    s = re.split(r'[〜～~・]', s)[0].strip()
    # 末尾の「タナ」「m」等を除去
    s = re.sub(r'[\s　]+.*', '', s)
    return s.strip()


def extract_place(normalized):
    """
    「木更津沖」->「木更津」（地名部分を抽出）
    「城ヶ島沖」->「城ヶ島」
    「相模湾」->「相模湾」（そのまま）
    """
    m = re.match(r'^(.+?)[沖前漁場ポイント根]', normalized)
    return m.group(1) if m else normalized


# ── Nominatim 検索 ────────────────────────────────────────────────────

def geocode_nominatim(place, region_hint="神奈川 千葉 東京 茨城"):
    """
    Nominatim で地名を検索して (lat, lon) を返す。
    見つからなければ None を返す。
    利用規約: 1リクエスト/秒 厳守
    """
    query = f"{place} {region_hint} 日本"
    url = (
        "https://nominatim.openstreetmap.org/search"
        f"?q={quote(query)}&format=json&limit=3"
        "&countrycodes=jp"
    )
    try:
        req = Request(url, headers={
            "User-Agent": "kanto-fishing-point-geocoder/1.0"
        })
        with urlopen(req, timeout=10) as r:
            results = json.loads(r.read().decode("utf-8"))
        # 海・湾・岬・岸・市区町村を優先
        for res in results:
            lat = float(res["lat"])
            lon = float(res["lon"])
            # 関東沿岸エリア内に絞る（緯度35〜37、経度139〜141）
            if 34.5 <= lat <= 37.0 and 138.5 <= lon <= 141.5:
                return round(lat, 4), round(lon, 4)
    except Exception as e:
        print(f"    geocode error [{place}]: {e}")
    return None, None


# ── メイン ────────────────────────────────────────────────────────────

def main():
    # 1. 全CSVからpoint_placeを集計
    counter = Counter()
    for fname in sorted(os.listdir("data")):
        if not fname.endswith(".csv"):
            continue
        with open(f"data/{fname}", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                p = row.get("point_place", "").strip()
                if p:
                    counter[p] += 1

    print(f"ユニークポイント数: {len(counter)}")

    # 2. 正規化 -> ユニーク地名リストを作成
    norm_map = {}   # raw -> normalized
    for raw in counter:
        norm_map[raw] = normalize_point(raw)

    unique_norm = sorted(set(norm_map.values()))
    print(f"正規化後ユニーク数: {len(unique_norm)}")

    # 3. 既存 point_coords.json を読み込む（差分更新）
    coords_path = "point_coords.json"
    if os.path.exists(coords_path):
        with open(coords_path, encoding="utf-8") as f:
            point_coords = json.load(f)
        print(f"既存エントリ: {len(point_coords)} 件")
    else:
        point_coords = {}

    # 4. 未解決ポイントだけ Nominatim に問い合わせ
    todo = [n for n in unique_norm if n not in point_coords and n not in SKIP_NAMES]
    print(f"Nominatim 検索対象: {len(todo)} 件\n")

    for i, norm in enumerate(todo, 1):
        # KNOWN_COORDS にあれば直接設定
        if norm in KNOWN_COORDS:
            point_coords[norm] = KNOWN_COORDS[norm]
            print(f"[{i:3d}] {norm} -> 固定値 {KNOWN_COORDS[norm]}")
            continue

        place = extract_place(norm)
        lat, lon = geocode_nominatim(place)

        if lat is not None:
            point_coords[norm] = {"lat": lat, "lon": lon}
            print(f"[{i:3d}] {norm} ({place}) -> {lat}, {lon}")
        else:
            point_coords[norm] = {"lat": None, "lon": None, "note": "要手動設定"}
            print(f"[{i:3d}] {norm} ({place}) -> 未解決 [要手動]")

        time.sleep(1.1)  # Nominatim 利用規約: 1req/sec

    # スキップ対象も記録
    for name in SKIP_NAMES:
        if name not in point_coords:
            point_coords[name] = {"lat": None, "lon": None, "note": "抽象的なポイント名・スキップ"}

    # 5. 保存
    with open(coords_path, "w", encoding="utf-8") as f:
        json.dump(point_coords, f, ensure_ascii=False, indent=2)

    # 6. サマリー
    resolved   = sum(1 for v in point_coords.values() if v.get("lat") is not None)
    unresolved = sum(1 for v in point_coords.values() if v.get("lat") is None)
    print(f"\n=== 完了 ===")
    print(f"解決済み: {resolved} 件")
    print(f"未解決(要手動): {unresolved} 件")
    print(f"-> point_coords.json に保存")

    # 7. raw->normalized のマッピングも保存（join時に使用）
    norm_path = "point_normalize_map.json"
    with open(norm_path, "w", encoding="utf-8") as f:
        json.dump(norm_map, f, ensure_ascii=False, indent=2)
    print(f"-> point_normalize_map.json に保存（正規化マップ）")


if __name__ == "__main__":
    main()
