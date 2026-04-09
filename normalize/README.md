# normalize/ — B層: 正規化ルール（マスターデータ）

## 役割

釣果生データを正規化するためのマスター JSON 群を管理する。
crawler.py (B層) がこれらを参照して `data/Vn/YYYY-MM.csv` を生成する。

---

## 管理ファイル一覧

| ファイル | 内容 | 規模 |
|---------|------|------|
| tsuri_mono_map_draft.json | 釣り物名正規化マップ | 58魚種 |
| point_coords.json | ポイント名→座標（① フォールバック） | 306ポイント |
| ship_fish_point.json | 船宿×魚種→デフォルトポイント（② フォールバック） | 73船宿 |
| area_coords.json | エリア代表座標（③ フォールバック） | 58エリア |
| ship_wx_coord_override.json | 気象座標の船宿別上書き | 複数船宿 |

> `point_coords.json` / `area_coords.json` は ocean/rebuild_weather_cache.py も参照する

---

## 利用元

| スクリプト | 参照ファイル |
|-----------|------------|
| crawler.py (B層) | 全ファイル |
| ocean/rebuild_weather_cache.py | point_coords.json, area_coords.json |
| analysis/V2/methods/combo_deep_dive.py 等 | ship_wx_coord_override.json |
| analysis/V2/methods/enrich_catches.py 等 | tsuri_mono_map_draft.json, point_coords.json, ship_fish_point.json |

---

## バージョン管理方針

normalize/ 自体は**バージョン管理しない**。

| 変更の種類 | 対応方法 |
|-----------|---------|
| 魚種・ポイントの**追加** | 後ろ互換。normalize/ をその場で更新 |
| 座標の**微修正** | 同上 |
| 分類体系の**刷新**（魚種定義の大幅変更等） | `data/` バージョンアップ（V3→）と同時に実施。全期間 CSV を再生成 |

---

## ポイント解決の3段階フォールバック

```
① point_place1 → point_coords.json（306ポイント）→ lat/lon
② 空/航程系    → ship_fish_point.json（73船宿）  → ポイント名 → lat/lon
③ ② も未登録  → area_coords.json（58エリア）    → lat/lon
解決率: 94.9%
```

---

## 前後工程との関係

```
crawl/catches_raw.json
  ↓
crawler.py (B層) ← normalize/*.json（正規化ルール）
  ↓
data/V2/YYYY-MM.csv → analysis/V2/methods/（C層）
                    → crawler.py (E層: HTML生成)
```
