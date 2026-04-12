# データパイプライン設計図 v2.2（2026/04/09）

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

---

## 全体構成

```
【A: データ収集層】→【B: 正規化・CSV化層】→【C: 分析・集計層】→【D: 予測層】→【E: 表示層】
```

---

## A: データ収集層

| レイヤ | スクリプト | 出力ファイル | 実行タイミング |
|--------|-----------|------------|--------------|
| A1 釣果クロール | crawler.py | crawl/catches_raw.json (84,757件) | 毎日16:30 JST（GitHub Actions） |
| A1b 直接クロール | direct-crawl/gyo_crawler.py | direct-crawl/catches_raw_direct.json | 毎日（A1後・crawl.yml） |
| A2 気象データ | ocean/rebuild_weather_cache.py | ocean/weather_cache.sqlite | 手動（約30分）|
| A3 台風データ | ocean/build_typhoon.py | ocean/typhoon.sqlite | 手動（年次更新）|
| A4 潮汐・月齢 | ocean/build_tide_moon.py | ocean/tide_moon.sqlite | 手動（5秒）|
| A5 海況CSV | crawler.py (fetch_weather_csv) | weather/YYYY-MM.csv | 毎日自動（A1後）|

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

> **data/ はバージョン管理される。** 現行: `data/V2/`（config.json active_version に連動）
> CSV 列追加時は active_version を上げ `export_csv_from_raw()` で全期間再生成すること。

| スクリプト | 入力 | 出力 | 実行タイミング |
|-----------|------|------|--------------|
| crawler.py (save_daily_csv) | catches_raw.json | data/V2/YYYY-MM.csv | crawl後自動 |
| crawler.py (export_csv_from_raw) | catches_raw.json | data/V2/YYYY-MM.csv | 全再生成時（手動） |

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

### analysis.sqlite テーブル一覧

| テーブル | 内容 |
|---------|------|
| combo_decadal | 魚種×船宿×旬(10日)の平均値 ← **ベースライン** |
| combo_backtest | H=0,1,3,7,14,21,28日前予測精度（r, MAE, MAPE） |
| combo_meta | 座標・件数サマリー |
| combo_keywords | kanso_rawキーワード相関 |
| cancel_thresholds | 船宿別欠航波高・風速閾値 |
| cancel_thresholds_seasonal | 季節別欠航閾値 |

### バックテスト CV 設計（2026/04/13 確定）

**方式: leave-one-month-out CV**

```
各テスト月 m に対して:
  train = 全レコード の うち date[:7] != m  （前後含む全データ）
  test  = 全レコード の うち date[:7] == m
```

**採用理由:**
- 実運用では3年分の蓄積データ全体で学習してから翌日を予測する
- バックテストも同じ条件にすることで、実運用精度を正しく反映する
- walk-forward（過去のみ学習）だと初期foldが「未熟期モデル」になり wMAPE が悲観的かつ不正確

**「未来データを学習に含む」問題について:**
- 気象×釣果の相関（SST高い日はアジが多い等）は時期によらず安定した自然法則
- 金融データと異なり、2025年のデータが2023年の予測精度を歪めることはない
- テスト月のアウトカムは train から除外されているため情報汚染なし

**最低条件:** 全月数 ≥ 2（MIN_TRAIN_N=15件 も満たすこと）

**最終パラメータ（wx_params）:** 全件で学習（TRAIN_END廃止）

**実績（2026/04/13, 全55魚種）:**
- H=0 wMAPE 中央値: **39.9%**（旧walk-forward比 -2.9pt）
- BL-2 勝率: **90.8%**（旧 83%）
- H=0 と H=7 の差: **2.0pt**（前後データで学習するため当然の縮小）

---

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
| calendar.html | crawler.py: build_calendar_page | ✅ 毎日 |
| fish/*.html (51魚種) | crawler.py: build_fish_pages | ✅ 毎日 |
| area/*.html | crawler.py: build_area_pages | ✅ 毎日 |
| fish_area/*.html | crawler.py: build_fish_area_pages | ✅ 毎日 |
| forecast/index.html | crawler.py: build_forecast | ✅ 毎日 |
| sitemap.xml | crawler.py: build_sitemap | ✅ 毎日 |
| pages/*.html | crawler.py: design sync | ✅ 毎日（design/Vn/ から自動コピー） |
| style.css / main.js | crawler.py: design sync | ✅ 毎日（design/Vn/ から自動コピー） |

### デザインバージョン管理（E層）

```
config.json
  "design_version": "V1"  ← ここを V2 に変えるだけで全デザイン切替
        ↓
crawler.py 実行時
  design/V1/*.html → pages/（about/contact/privacy/terms）
  design/V1/style.css → ルート
  design/V1/main.js   → ルート
```

- **HTML構造（fish/*.html等）**: crawler.py が毎日再生成 → design_version 変更で自動反映
- **静的ページ（pages/）**: design/Vn/ からコピー → URL は `/pages/about.html` 等
- **注意**: fish/ area/ 等の URL 構造変更は SEO リセットを伴う → V2 設計時に要決定

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

## 現在のデータ状態（2026/04/08）

| レイヤ | 状態 | 件数・規模 |
|--------|------|---------|
| A1 catches_raw.json | ✅ 最新 | 84,757件 |
| A1b catches_raw_direct.json | ✅ 稼働中 | 108件（忠彦丸・一之瀬丸・米元） |
| A2 weather_cache.sqlite | ✅ 完成 | 153座標×145万行 |
| A3 typhoon.sqlite | ✅ 完成 | 70台風 2,475ポイント |
| A4 tide_moon.sqlite | ✅ 完成 | 1,190日分 |
| A5 weather/YYYY-MM.csv | ✅ 毎日更新 | 96地点×月別 |
| B1 data/V2/*.csv | ✅ 最新 | 82,650行 |
| C1 analysis.sqlite | ⏳ 要再実行 | 51魚種 |
| C2 deepdive_params.json | ⏳ C1後に実行 | - |
| D1-4 予測モデル | 🔲 未実装 | - |
| E デザイン | ✅ V1稼働中 | design_version: "V1" |

---

## 変更インパクトマトリクス（追記）

| 変更対象 | 影響する層 | 必要な再実行 | コスト |
|---------|-----------|------------|------|
| config.json design_version | E | crawler.py 実行のみ | ★ 低 |
| design/Vn/*.html/css/js | E | crawler.py 実行のみ | ★ 低 |
| fish/ area/ のURL構造変更 | E + SEO | crawler.py + 全インデックス再取得 | ★★★ 高（SEOリセット） |
| weather/YYYY-MM.csv スキーマ変更 | E | 全CSV再生成 + crawler.py修正 | ★★ 中 |
| direct-crawl/gyo_crawler.py | A1b→B | CSV再統合 | ★ 低 |

---

## ノート（意思決定ログ）

### 2026/04/04
- normalize_tsuri_mono バグ修正（`raw in p` → `p in raw` のみ）。17,701件の誤分類を解消
- time_slot / cancel_reason / cancel_type をCSVに追加
- rebuild_weather_cache.py: 新規作成（point_coords.json 152座標ベース）
- build_typhoon.py: 新規作成（JMA BestTrack、bst_all.zipから2023-2025年取得）
- build_tide_moon.py: 新規作成（stdlib天文計算、tide_coeff = (cos+1)/2×100）

### 2026/04/08
- フォルダ大掃除完了: crawl/ ocean/ normalize/ data/V2/ analysis/V2/ design/ pages/ dustbox/ 整備
- config.json に design_version 追加（デザイン切替を1行で完結）
- direct-crawl/ 新設: gyo_crawler.py（忠彦丸・一之瀬丸・米元）→ catches_raw_direct.json → CSV統合
- pages/ 新設: 静的HTMLをルートから分離（about/contact/privacy/terms）
- weather/ の位置: ルート直下に残留（A5: E層向け海況CSV、crawler.py が毎日追記）
- fish/ forecast/ のURL構造: V2設計時に要決定（SEOリセット覚悟で英語URL化の方向）
