# データパイプライン設計図 v2.0（2026/04/04）

このファイルはパイプラインの構造と変更インパクトを記録するリファレンスです。
**何かを変更する前に必ずこのファイルを確認すること。**

---

## 全体構成

```
【A: データ収集層】→【B: 正規化・CSV化層】→【C: 分析・集計層】→【D: 予測層】→【E: 表示層】
```

---

## A: データ収集層

| レイヤ | スクリプト | 出力ファイル | 実行タイミング |
|--------|-----------|------------|--------------|
| A1 釣果クロール | crawler.py | catches_raw.json (84,757件) | 毎日16:30 JST（GitHub Actions） |
| A2 気象データ | rebuild_weather_cache.py | weather_cache.sqlite | 手動（約30分）|
| A3 台風データ | build_typhoon.py | typhoon.sqlite | 手動（年次更新）|
| A4 潮汐・月齢 | build_tide_moon.py | tide_moon.sqlite | 手動（5秒）|

### A2 weather_cache.sqlite 詳細
- **ソース**: Open-Meteo Archive API + Marine API
- **対象**: 153座標 × 2023-01-01〜今日 × 3時間毎
- **規模**: 約145万行
- **スキーマ**: `(lat, lon, dt, wind_speed, wind_dir, temp, pressure, wave_height, wave_period, swell_height, sst, precipitation)`
- **座標ソース**: point_coords.json（152座標） + area_coords.json（フォールバック）

### A3 typhoon.sqlite 詳細
- **ソース**: 気象庁 BestTrack (bst_all.zip / bst{YYYY}.txt)
- **対象**: 2023〜現在 70台風 2,475トラックポイント（6時間毎）
- **スキーマ**: `typhoons(ty_id, year, number, name)` + `typhoon_track(ty_id, dt, lat, lon, pressure, wind_kt, dist_ibaraki, dist_outer_boso, dist_tokyo_bay, dist_sagami_bay, min_dist)`

### A4 tide_moon.sqlite 詳細
- **計算式**: 基準新月JD 2451550.259722 / 朔望月 29.530588853日
- **出力**: 日ベース（tide_type, moon_age, tide_coeff 0〜100, moon_phase）
- **潮汐区分**: 大潮/中潮/小潮/長潮/若潮

---

## B: 正規化・CSV化層

| スクリプト | 入力 | 出力 | 実行タイミング |
|-----------|------|------|--------------|
| crawler.py (generate_csv_all) | catches_raw.json | data/YYYY-MM.csv | crawl後自動 |

### CSV列一覧（B1）

| 列名 | 内容 | 正規化ロジック |
|------|------|-------------|
| ship | 船宿名 | そのまま |
| area | 港名 | そのまま |
| date | 釣行日 | YYYY/MM/DD |
| trip_no | 1日の何便目 | 整数 |
| is_cancellation | 欠航フラグ | 0/1 |
| tsuri_mono_raw | 釣り物生テキスト | そのまま（LTアジ等） |
| tsuri_mono | 正規化魚種名 | tsuri_mono_map_draft.json (58種) |
| main_sub | メイン/サブ/不明 | fish_raw中の順位 |
| fish_raw | 釣果生テキスト全文 | そのまま |
| time_slot | 午前/午後/夜/朝/夕/ショート | fish_rawから抽出 |
| cnt_min/max/avg | 釣果数 | 数値抽出 |
| size_min/max | サイズ(cm) | 数値抽出 |
| kg_min/max | 重量(kg) | 数値抽出 |
| point_place1/2/3 | ポイント名 | kanso_rawから抽出 |
| lat, lon | 座標 | ポイント解決（3段階フォールバック） |
| cancel_reason | 欠航理由生テキスト | reason_textから |
| cancel_type | 欠航種別 | 定休日/荒天/台風/中止/不明 |
| kanso_raw | 感想生テキスト | そのまま |

### ポイント解決（3段階フォールバック）

```
① point_place1 → point_coords.json（306ポイント）→ lat/lon
② 空/航程系    → ship_fish_point.json（73船宿）→ ポイント名 → lat/lon
③ ② も未登録  → area_coords.json（58エリア）→ lat/lon
解決率: 94.9%（除外船宿を除く）
```

### tsuri_mono 正規化ロジック（3段階優先）

```python
# 1. 完全一致キー
if raw in TSURI_MONO_MAP: return raw
# 2. パターン完全一致
for tsuri_mono, patterns in TSURI_MONO_MAP.items():
    if raw in patterns: return tsuri_mono
# 3. 前方部分一致（p in raw のみ。raw in p は禁止）
for tsuri_mono, patterns in TSURI_MONO_MAP.items():
    if any(p in raw for p in patterns): return tsuri_mono
```

⚠️ **`raw in p`（逆方向）は禁止** — アマダイ→マダイ誤分類の原因だった

---

## C: 分析・集計層

> **スクリプトは `analysis/V2/methods/`、出力は `analysis/V2/results/` に配置。**
> バージョンは `config.json` の `active_version` で管理。

| スクリプト | 入力 | 出力 | 実行タイミング |
|-----------|------|------|--------------|
| analysis/V2/methods/combo_deep_dive.py | data/*.csv + ocean/*.sqlite | analysis/V2/results/analysis.sqlite | 手動（全51魚種） |
| analysis/V2/methods/parse_deepdive.py | analysis/V2/results/analysis.sqlite | analysis/V2/results/deepdive_params.json | C1後に実行 |
| analysis/run.py {script} | — | — | crawl.yml 経由で自動 |

### analysis.sqlite テーブル一覧

| テーブル | 内容 |
|---------|------|
| combo_decadal | 魚種×船宿×旬(10日)の平均値 ← **ベースライン** |
| combo_backtest | H=0,1,3,7,14,21,28日前予測精度（r, MAE, MAPE） |
| combo_meta | 座標・件数サマリー |
| combo_keywords | kanso_rawキーワード相関 |
| cancel_thresholds | 船宿別欠航波高・風速閾値 |
| cancel_thresholds_seasonal | 季節別欠航閾値 |

### バックテスト：予報有効ホライズン分類

| 変数 | 分類 | 有効H |
|------|------|-------|
| SST, temp, pressure | 遅い変数（週単位で変化） | H≤28 |
| tide_type, moon_age | 天文計算（確定値） | H≤∞ |
| wave_height, wave_period, swell | 速い変数（数日で急変） | H≤7 |
| wind_speed, wind_dir | 速い変数 | H≤7 |
| typhoon_dist | イベント変数 | H≤5（進路予報限界） |

---

## D: 予測層（設計済み・実装待ち）

### D1: 短期予測 H=1〜7日

- **使用変数**: wave, wind, SST, tide_type, moon_age, typhoon_dist（全変数）
- **ベースライン**: combo_decadal（旬別）
- **出力**: 平年比±% + ★1〜5評価 + 理由テキスト

### D2: 中期予測 H=8〜14日

- **使用変数**: SST, temp, pressure, tide_type, moon_age（速い変数は使わない）
- **ベースライン**: combo_decadal

### D3: 長期予測 H=15〜28日

- **使用変数**: tide_type, moon_age, decade_no（潮汐・月齢・旬のみ）
- **ベースライン**: combo_decadal

### D4: 欠航リスク予測

- **使用変数**: wave_height, wind_speed, typhoon_dist, cancel_thresholds
- **出力**: 欠航確率 P=0〜1（閾値: P≥0.8 で「欠航リスク高」）

---

## E: 表示・配信層

| ページ | 生成スクリプト | 自動更新 |
|--------|--------------|---------|
| index.html | crawler.py: build_html | ✅ 毎日 |
| fish/*.html (51魚種) | crawler.py: build_fish_pages | ✅ 毎日 |
| area/*.html | crawler.py: build_area_pages | ✅ 毎日 |
| calendar.html | crawler.py: build_calendar_page | ✅ 毎日 |

---

## 変更インパクトマトリクス

**何かを変更する前にこの表を確認すること。**

| 変更対象 | 影響する層 | 必要な再実行 | コスト |
|---------|-----------|------------|------|
| tsuri_mono_map_draft.json | B→C→D→E | CSV再生成 + C全実行 | ★★★ 高 |
| point_coords.json | B→C→D→E | CSV再生成 + C全実行 | ★★★ 高 |
| ship_fish_point.json | B→C→D→E | CSV再生成 + C全実行 | ★★★ 高 |
| weather_cache 座標追加 | A2→C→D1-2 | rebuild_weather_cache (30分) + C実行 | ★★ 中 |
| tide_moon 計算式変更 | A4→C→D3 | rebuild_tide_moon (5秒) + C実行 | ★ 低 |
| 台風データ年次更新 | A3→D4 | build_typhoon のみ (1分) | ★ 低 |
| cancel_threshold変更 | D4→E | D4再計算のみ | ★ 低 |
| HTML/テンプレ変更 | E のみ | crawler.py再実行のみ | ★ 低 |
| catches_raw.json更新（日次） | B→C→D→E | CSV再生成 + C増分実行 | ★★ 中（自動） |

---

## 現在のデータ状態（2026/04/04）

| レイヤ | 状態 | 件数・規模 |
|--------|------|---------|
| A1 catches_raw.json | ✅ 最新 | 84,757件 |
| A2 weather_cache.sqlite | ✅ 完成 | 153座標×145万行 |
| A3 typhoon.sqlite | ✅ 完成 | 70台風 2,475ポイント |
| A4 tide_moon.sqlite | ✅ 完成 | 1,190日分 |
| B1 data/*.csv | ✅ 最新 | 82,650行 |
| C1 analysis.sqlite | ⏳ 要再実行（weather有効化後） | 51魚種 |
| C2 deepdive_params.json | ⏳ C1後に実行 | - |
| D1-4 予測モデル | 🔲 未実装 | - |

---

## ノート（意思決定ログ）

### 2026/04/04
- normalize_tsuri_mono バグ修正（`raw in p` → `p in raw` のみ）。17,701件の誤分類を解消
- time_slot / cancel_reason / cancel_type をCSVに追加
- rebuild_weather_cache.py: 新規作成（point_coords.json 152座標ベース）
- build_typhoon.py: 新規作成（JMA BestTrack、bst_all.zipから2023-2025年取得）
- build_tide_moon.py: 新規作成（stdlib天文計算、tide_coeff = (cos+1)/2×100）
