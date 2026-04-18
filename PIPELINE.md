# データパイプライン設計図 v2.3（2026/04/19）

このファイルはパイプラインの構造と変更インパクトを記録するリファレンスです。
**何かを変更する前に必ずこのファイルを確認すること。**

---

## ⚠️ CSV列追加時の必須手順

**crawler.py に新しいCSV列を追加したら、必ず以下を行うこと。**

### 1. `normalize/obs_fields.json` にエントリを追加

combo_deep_dive.py はこのファイルを読んで自動適用する。コードは触らない。

```jsonc
// 追加例: 新列 "bait_type" を外道スコアとして使う場合
"bait_type_n": {
  "source": "bait_type",
  "compute": "map",
  "map": {"イワシ": 1.0, "サバ": 0.5, "アジ": 0.0},
  "role": "obs_factor",
  "desc": "餌種スコア"
}
```

| compute 種別 | 使い方 |
|---|---|
| `direct` | CSV数値をそのまま使う |
| `avg` | 複数列の平均（例: depth_min + depth_max） |
| `map` | 文字列→数値の辞書（完全一致、先着優先） |
| `keyword_score` | テキスト内キーワードにスコア割り当て（先着優先） |
| `split_count` | カンマ/スラッシュ区切りで要素数を数える |
| `text_concat` | テキスト結合（`text_all` に自動追加） |

| role 種別 | 効果 |
|---|---|
| `obs_factor` | OBS相関分析セクションに自動表示（予報不可・バックテスト対象外） |
| `text_field` | `text_all` に結合、キーワード検索の対象になる |

### 2. CSV再生成が必要な場合

新列が既存レコードにも遡及的に適用される場合:
```bash
python crawler.py --export-csv   # data/V2/ を全再生成
```

CSV列追加はスキーマバージョンアップ（V2→V3）が必要になるケースもある。
PIPELINE.md 変更インパクトマトリクスで確認すること。

---

## 全体構成

```
【A: データ収集層】→【B: 正規化・CSV化層】→【C: 分析・集計層】→【D: 予測層】→【E: 表示層】
```

---

## A: データ収集層

| レイヤ | スクリプト | 出力ファイル | 実行タイミング |
|--------|-----------|------------|--------------|
| A1 釣果クロール | crawler.py | crawl/catches_raw.json | 毎日16:30 JST（GitHub Actions） |
| A1b 直接クロール | direct-crawl/gyo_crawler.py | direct-crawl/catches_raw_direct.json | 毎日（A1後・crawl.yml） |
| A2 気象データ | ocean/rebuild_weather_cache.py | ocean/weather_cache.sqlite | 手動（約30分）|
| A3 台風データ | ocean/build_typhoon.py | ocean/typhoon.sqlite | 手動（年次更新）|
| A4 潮汐・月齢 | ocean/build_tide_moon.py | ocean/tide_moon.sqlite | 手動（5秒）|
| A5 海況CSV | crawler.py (fetch_weather_csv) | weather/YYYY-MM.csv（153座標＝weather_cache と同一） | 毎日自動（A1後）|
| A6 CMEMSデータ | ocean/build_cmems.py | ocean/cmems_data.sqlite | 手動（随時）|
| A7 海況マップJSON | ocean/build_ocean_map.py | ocean_map_data.json | 手動（随時）|
| A8 分析可視化 | ocean/build_analysis_map.py | PNG（ローカル専用） | 手動（分析時）|
| A9 潮汐詳細 | ocean/tide_fetch.py | tide/YYYY-MM.csv（4エリア毎時） | 手動 |

### A2 weather_cache.sqlite 詳細
- **ソース**: Open-Meteo Archive API + Marine API
- **テーブル名**: `weather`（※`weather_cache`ではない）
- **対象**: 153座標 × 2023-01-01〜2026-04-04 × 3時間毎
- **規模**: 1,456,560行
- **スキーマ**: `(lat, lon, dt, wind_speed, wind_dir, temp, pressure, wave_height, wave_period, swell_height, sst, precipitation, current_speed, current_dir)`
- **座標ソース**: point_coords.json（152座標） + area_coords.json（フォールバック）

### A3 typhoon.sqlite 詳細
- **ソース**: 気象庁 BestTrack (bst_all.zip / bst{YYYY}.txt)
- **対象**: 2023〜2025年 70台風 2,475トラックポイント（6時間毎）
- **期間**: 2023-04-19〜2025-12-03
- **スキーマ**: `typhoons(ty_id, year, number, name)` + `typhoon_track(ty_id, dt, lat, lon, pressure, wind_kt, dist_ibaraki, dist_outer_boso, dist_tokyo_bay, dist_sagami_bay, min_dist)`

### A4 tide_moon.sqlite 詳細
- **計算式**: 基準新月JD 2451550.259722 / 朔望月 29.530588853日
- **規模**: 37,985行
- **期間**: 2023-01-01〜2126-12-31（天文計算で超長期生成済み）
- **出力**: 日ベース（tide_type, moon_age, tide_coeff 0〜100, moon_phase）
- **潮汐区分**: 大潮/中潮/小潮/長潮/若潮

### A6 cmems_data.sqlite 詳細
- **ソース**: Copernicus Marine Service (CMEMS) API
- **テーブル1**: `cmems_daily`
  - **列**: `(lat, lon, date, sla, chl, sss)`
  - **内容**: SLA（黒潮位置）・CHL（クロロフィル=ベイト密度）・SSS（塩分）
  - **規模**: 9,651,712行
  - **期間**: 2023-01-01〜2026-04-18
- **テーブル2**: `cmems_depth`
  - **列**: `(lat, lon, date, depth_m, temp, do, no3)`
  - **内容**: 深度別水温・DO（溶存酸素=青潮リスク）・NO3（硝酸塩=栄養塩）
  - **規模**: 4,158,088行
  - **期間**: 2023-01-01〜2026-04-18

### A7 build_ocean_map.py 詳細
- **入力**: cmems_data.sqlite + weather_cache.sqlite + analysis.sqlite(water_color_daily)
- **出力**: `ocean_map_data.json`（kuroshio_map.html 用データ）
- **内容**: SLA/CHL/SST/水色 × 直近30日分
- **GitHub Pages非対象**: ローカル分析ツール

### A8 build_analysis_map.py 詳細
- **目的**: 分析者向け3ショット専用ツール（CHL解像度比較・水色補間品質・4レイヤスナップショット）
- **GitHub Pages非対象**: ローカル専用

---

## B: 正規化・CSV化層

> **data/ はバージョン管理される。** 現行: `data/V2/`（config.json active_version に連動）
> CSV 列追加時は active_version を上げ `export_csv_from_raw()` で全期間再生成すること。

| スクリプト | 入力 | 出力 | 実行タイミング |
|-----------|------|------|--------------|
| crawler.py (save_daily_csv) | crawl/catches_raw.json | data/V2/YYYY-MM.csv | crawl後自動 |
| crawler.py (export_csv_from_raw) | crawl/catches_raw.json | data/V2/YYYY-MM.csv | 全再生成時（手動） |

### CSV列一覧（B1・V2スキーマ・38列）

| 列名 | 内容 | 正規化ロジック |
|------|------|-------------|
| ship | 船宿名 | そのまま |
| area | 港名 | そのまま |
| date | 釣行日 | YYYY/MM/DD |
| trip_no | 1日の何便目 | 整数 |
| is_cancellation | 欠航フラグ | 0/1 |
| tsuri_mono_raw | 釣り物生テキスト | そのまま（LTアジ等） |
| tsuri_mono | 正規化魚種名 | tsuri_mono_map_draft.json |
| main_sub | メイン/サブ/不明 | fish_raw中の順位 |
| fish_raw | 釣果生テキスト全文 | そのまま |
| time_slot | 午前/午後/夜/朝/夕/ショート | fish_rawから抽出 |
| cnt_min/max/avg | 釣果数 | 数値抽出 |
| is_boat | 乗合/仕立フラグ | 0/1 |
| size_min/max | サイズ(cm) | 数値抽出 |
| kg_min/max | 重量(kg) | 数値抽出 |
| tackle | 仕掛け種別 | テキスト抽出 |
| point_place1/2/3 | ポイント名 | kanso_rawから抽出 |
| depth_min/max | 水深(m) | 数値抽出 |
| water_temp_min/max | 水温(℃) | 数値抽出 |
| water_color | 水色テキスト | そのまま |
| wind_direction | 風向 | テキスト抽出 |
| wind_speed | 風速 | テキスト抽出 |
| tide_info | 潮情報テキスト | そのまま |
| wave_info | 波情報テキスト | そのまま |
| weather | 天気テキスト | そのまま |
| by_catch | 外道テキスト | そのまま |
| cancel_reason | 欠航理由生テキスト | reason_textから |
| cancel_type | 欠航種別 | 定休日/荒天/台風/中止/不明 |
| kanso_raw | 感想生テキスト | そのまま |
| suion_raw | 水温生テキスト | そのまま |
| suishoku_raw | 水色生テキスト | そのまま |

### 現在のデータ状態（2026/04/19）

| レイヤ | 状態 | 件数・規模 |
|--------|------|---------|
| A1 crawl/catches_raw.json | ✅ 最新 | **86,024件** |
| A1b catches_raw_direct.json | ✅ 稼働中 | 忠彦丸・一之瀬丸・米元 |
| A2 weather_cache.sqlite | ✅ 完成 | 153座標×1,456,560行（〜2026-04-04） |
| A3 typhoon.sqlite | ✅ 完成 | 70台風 2,475ポイント（〜2025-12） |
| A4 tide_moon.sqlite | ✅ 完成 | 37,985行（〜2126年）|
| A5 weather/YYYY-MM.csv | ✅ 毎日更新 | 153地点×月別 |
| A6 cmems_data.sqlite | ✅ 最新 | cmems_daily 9.6M行・cmems_depth 4.1M行（〜2026-04-18） |
| B1 data/V2/*.csv | ✅ 最新 | **64,991行**（37ファイル + cancellations.csv） |
| C1 analysis.sqlite | ✅ 最新（2026-04-19再実行） | 実行55種・バックテスト完了45種・32テーブル |
| D1-4 予測モデル | 🔲 未実装 | - |
| E デザイン | ✅ V2稼働中 | design_version: "V2" |

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
| analysis/V2/methods/run_full_deepdive.py | data/*.csv + ocean/*.sqlite | analysis/V2/results/analysis.sqlite | **手動（全魚種 並列実行）← 必ずこれを使う** |
| analysis/V2/methods/combo_deep_dive.py | data/*.csv + ocean/*.sqlite | analysis/V2/results/analysis.sqlite | 単体魚種のみ（デバッグ・個別再実行用） |
| analysis/run.py {script} | — | — | crawl.yml 経由で自動 |

> ⚠️ **全魚種実行は必ず `run_full_deepdive.py --workers 4` を使うこと**。逐次ループは禁止。
> SQLite WAL モード + timeout=30s により並列書き込みは安全にシリアライズされる。
>
> ```bash
> # 標準実行（ローカル・全魚種）
> python analysis/V2/methods/run_full_deepdive.py --workers 4
>
> # 特定魚種のみ再実行
> python analysis/V2/methods/run_full_deepdive.py アジ マダイ シーバス --workers 3
>
> # GitHub Actions（2CPU環境）
> python analysis/V2/methods/run_full_deepdive.py --workers 2
> ```

### analysis.sqlite テーブル一覧（32テーブル・2026/04/19現在）

| テーブル | 行数 | 内容 |
|---------|------|------|
| combo_decadal | 4,935 | 魚種×船宿×旬(10日)の平均値 ← **ベースライン** |
| combo_backtest | 6,129 | H=0,1,3,7,14,21,28日前予測精度（r, MAE, wMAPE等） |
| combo_meta | 246 | 座標・件数・精度サマリー（45魚種・246コンボ）※MIN_N_COMBO=30件以上のコンボのみ |
| combo_keywords | 1,513 | kanso_rawキーワード相関 |
| combo_deep_params | 93,916 | 気象×釣果の回帰パラメータ（50魚種）※combo_metaの45魚種＋データ不足でmeta未生成の5魚種（アユ・コハダ・ハタ・ムツゴロウイカ・ムラソイ）を含む |
| combo_wx_params | 8,434 | 採用気象因子・係数 |
| combo_range_backtest | 1,624 | cnt_min/max予測レンジ精度 |
| combo_star_backtest | 77 | 回遊魚★チャンス評価バックテスト |
| combo_thresholds | 4,720 | 欠航閾値・ベースライン閾値 |
| combo_monthly | 1,909 | 月別集計 |
| combo_weekly | 9,513 | 週別集計 |
| combo_season | 282 | 季節別集計 |
| combo_slot_ratio | 134 | 時間帯別釣果比率 |
| combo_notes | 0 | メモ（未使用） |
| cancel_thresholds | 11 | 船宿別欠航波高・風速閾値 |
| cancel_thresholds_combo | 11 | 船宿×魚種別欠航閾値 |
| cancel_thresholds_seasonal | 24 | 季節別欠航閾値 |
| water_color_daily | 181,611 | 153座標×日別水色予測値（〜2026-04-04） |
| wc_model_coeffs | 127 | 水色予測モデル係数 |
| area_decadal | 2,340 | エリア×旬別集計 |
| area_peaks | 126 | エリア別旬ピーク |
| area_season | 881 | エリア別季節集計 |
| ship_decadal | 5,056 | 船宿×旬別集計 |
| ship_peaks | 424 | 船宿別旬ピーク |
| ship_weekly_peaks | 682 | 船宿別週ピーク |
| cooccurrence | 807 | 魚種共出現集計 |
| decadal_calendar | 911 | 旬別カレンダー |
| season_calendar | 406 | 季節カレンダー |
| obs_keyword_corrections | 29 | キーワード補正テーブル |
| prediction_log | 799 | 予測ログ（JSONL形式） |
| retro_backtest | 10,540 | レトロスペクティブバックテスト |
| sqlite_sequence | 1 | SQLite内部 |

### バックテスト CV 設計（2026/04/13 確定）

**方式: leave-one-month-out CV**

```
各テスト月 m に対して:
  train = 全レコード の うち date[:7] != m  （前後含む全データ）
  test  = 全レコード の うち date[:7] == m
```

**実績（2026/04/19, 実行55種・バックテスト完了45種）:**
- H=0 wMAPE 中央値（コンボ単位P50）: **41.6%**
- BL-2 勝率 H=0: **88.5%**
- OOS r 平均 H=0: **+0.387**
- ※ 残10種（ハタ・クロムツ・キメジ等）はMIN_N_COMBO=30件未満のコンボのみで分析対象外

### バックテスト：予報有効ホライズン分類

| 変数 | 分類 | 有効H |
|------|------|-------|
| SST, temp, pressure | 遅い変数（週単位で変化） | H≤28 |
| tide_type, moon_age | 天文計算（確定値） | H≤∞ |
| SLA, CHL（CMEMS） | 遅い変数（週〜月単位） | H≤14 |
| wave_height, wave_period, swell | 速い変数（数日で急変） | H≤7 |
| wind_speed, wind_dir | 速い変数 | H≤7 |
| current_speed, current_dir | 速い変数 | H≤7 |
| typhoon_dist | イベント変数 | H≤5（進路予報限界） |

---

## D: 予測層（設計済み・実装待ち）

### D1: 短期予測 H=1〜7日

- **使用変数**: wave, wind, SST, tide_type, moon_age, typhoon_dist, current_speed（全変数）
- **ベースライン**: combo_decadal（旬別）
- **出力**: 平年比±% + ★1〜5評価 + 理由テキスト

### D2: 中期予測 H=8〜14日

- **使用変数**: SST, temp, pressure, tide_type, moon_age, SLA, CHL（速い変数は使わない）
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
| calendar.html | crawler.py: build_calendar_page | ✅ 毎日 |
| fish/*.html | crawler.py: build_fish_pages | ✅ 毎日 |
| area/*.html | crawler.py: build_area_pages | ✅ 毎日 |
| fish_area/*.html | crawler.py: build_fish_area_pages | ✅ 毎日 |
| forecast/index.html | crawler.py: build_forecast | ✅ 毎日 |
| sitemap.xml | crawler.py: build_sitemap | ✅ 毎日 |
| pages/*.html | crawler.py: design sync | ✅ 毎日（design/Vn/ から自動コピー） |
| style.css / main.js | crawler.py: design sync | ✅ 毎日（design/Vn/ から自動コピー） |

### デザインバージョン管理（E層）

```
config.json
  "design_version": "V2"  ← ここを変えるだけで全デザイン切替
        ↓
crawler.py 実行時
  design/V2/*.html → pages/（about/contact/privacy/terms）
  design/V2/style.css → ルート
  design/V2/main.js   → ルート
```

---

## 変更インパクトマトリクス

**何かを変更する前にこの表を確認すること。**

| 変更対象 | 影響する層 | 必要な再実行 | コスト |
|---------|-----------|------------|------|
| tsuri_mono_map_draft.json | B→C→D→E | CSV再生成 + C全実行 | ★★★ 高 |
| point_coords.json | B→C→D→E | CSV再生成 + C全実行 | ★★★ 高 |
| ship_fish_point.json | B→C→D→E | CSV再生成 + C全実行 | ★★★ 高 |
| weather_cache 座標追加 | A2→C→D1-2 | rebuild_weather_cache (30分) + C実行 | ★★ 中 |
| cmems_data 更新 | A6→C→D1-2 | build_cmems + C実行 | ★★ 中 |
| tide_moon 計算式変更 | A4→C→D3 | rebuild_tide_moon (5秒) + C実行 | ★ 低 |
| 台風データ年次更新 | A3→D4 | build_typhoon のみ (1分) | ★ 低 |
| cancel_threshold変更 | D4→E | D4再計算のみ | ★ 低 |
| HTML/テンプレ変更 | E のみ | crawler.py再実行のみ | ★ 低 |
| catches_raw.json更新（日次） | B→C→D→E | CSV再生成 + C増分実行 | ★★ 中（自動） |
| config.json design_version | E | crawler.py 実行のみ | ★ 低 |
| design/Vn/*.html/css/js | E | crawler.py 実行のみ | ★ 低 |
| fish/ area/ のURL構造変更 | E + SEO | crawler.py + 全インデックス再取得 | ★★★ 高（SEOリセット） |
| combo_deep_dive.py 特徴量追加 | C→D | run_full_deepdive.py 全魚種再実行 | ★★ 中 |

---

## ノート（意思決定ログ）

### 2026/04/04
- normalize_tsuri_mono バグ修正（`raw in p` → `p in raw` のみ）
- rebuild_weather_cache.py, build_typhoon.py, build_tide_moon.py 新規作成

### 2026/04/08
- フォルダ大掃除完了: crawl/ ocean/ normalize/ data/V2/ analysis/V2/ design/ pages/ dustbox/
- config.json に design_version 追加

### 2026/04/12
- weather_cache.sqlite に current_speed/current_dir 列追加（Open-Meteo Marine API）
- cmems_data.sqlite 新規作成（build_cmems.py）: SLA/CHL/SSS/水温/DO/NO3
- combo_deep_dive.py に潮流・乗っ込みフラグ特徴量追加
- 回遊魚KAIYU自動昇格システム実装

### 2026/04/13
- バックテスト方式を walk-forward → leave-one-month-out CV に変更
- 過学習対策（適応的相関閾値・MAX_FACTORS=10）
- 欠航予測をコンボレベル閾値に拡張（F1: 81.8% → 97.0%）

### 2026/04/19
- PIPELINE.md v2.3 に全面更新（researcher棚卸し結果反映）
- `_lookup_wc_pred()` に距離フィルター追加（0.3°超の外挿をNone化）
- build_analysis_map.py 新規作成（CHL解像度比較・水色補間品質・4レイヤスナップショット）
- design_version を V1 → V2 に切替済み
- 魚種数の整理:
  - run_full_deepdive.py 実行対象: **55種**（ALL_FISHリスト）
  - combo_meta/backtest 完了: **45種**（MIN_N_COMBO=30件以上のコンボが存在する種のみ）
  - 除外10種（データ不足）: ハタ・キメジ・コハダ・ブリ・キンメ・アユ・モンゴウイカ・イシダイ・クロムツ・ホウボウ
  - combo_deep_params: **50種**（コンボ不足でバックテスト未実施だがパラメータのみ存在する種を含む）
- ※ CLAUDE.md の一部記述（catches_raw件数/CSV行数/design_version/魚種数）は旧値のまま。本ファイル（PIPELINE.md）の値が正。
