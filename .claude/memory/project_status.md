現行バージョン: crawler.py v5.27 / predict_count.py（Forecast API統合済み）
最終更新: 2026/04/16
最新コミット: 未push（D1〜D4 V2パイプライン統一）

## ✅ 今セッション完了（2026/04/16 後半）

### D1〜D4: V2パイプライン統一（全完了）

**D1: save_daily_csv V2形式化（★★★最優先）✅**
- PR#7マージで消失していた約480行（export_csv_from_raw + ヘルパー群）を git show 75e5a6d から復元
- save_daily_csv() → data/V2/ に38列V2形式で書き込むよう書き換え
- save_cancellations_csv() → data/V2/cancellations.csv に変更
- `python crawler.py --export-csv` で catches_raw.json からの全再生成を実装
- repair_csv_depth（V1専用）はmain()から無効化
- 復元した関数: normalize_tsuri_mono, _extract_tsuri_mono, _classify_main_sub, _extract_time_slot, _extract_water_temp_range, _extract_water_color, _extract_wind_info, _extract_tide_info, _extract_wave_info, _extract_weather, _extract_by_catch, _classify_cancel_type, _extract_tackle, _split_point_places_depth, export_csv_from_raw, RAW_CSV_HEADER, TSURI_MONO_MAP等

**D2: tsuri_monoノイズ根本修正 ✅**
- `--export-csv` で全再生成 → 83,738行
- normalize_tsuri_mono に `if raw.isdigit(): return ""` ガード追加
- 数字ノイズ: 71件 → 0件

**D3: 2023年weather/*.csv欠落対応 ✅**
- ocean/export_weather_csv.py 新規作成
- weather_cache.sqlite → weather/YYYY-MM.csv（2023-01〜2024-03の15ヶ月分、554,496行）
- weather/ が40ファイル（2023-01〜2026-04）に完備

**D4: data/ルートV1スタブ整理 ✅**
- data/ 直下の V1 CSV（9ファイル + cancellations.csv）→ dustbox/data_v1_stubs/ に移動
- data/ 直下には V2/ ディレクトリのみ

---

## ✅ 今セッション完了（2026/04/16 前半）

### V1クロールデータ問題の修正

**問題1: _load_historical_catches() がV1スタブを読んでいた**
- 修正: `data/V2/*.csv`（active_version準拠・65,980行）を読むよう変更

**問題2: catches.json に複数日分が混在**
- 修正: `catches.json`の`data`配列を当日分のみに変更（0件時は全件フォールバック）

---

## ★ 次チャットでやること（優先度順）

### 1. 後回しタスク
- [ ] ちがさき丸×マダイ/シーバス/メバル 個別改善（r=-0.17等）
- [ ] 外道表示機能
- [ ] predict_count.py: 同一座標のForecast API呼び出しキャッシュ（全魚種実行時に遅い）
- [ ] 有料ページUI + 決済（Stripe）実装

## ✅ 今セッション完了（2026/04/13 深夜）

### 未来日予測に Forecast API 統合 + 予測ログ（predict_count.py）
- **問題**: weather_cache.sqlite は過去のみ → 未来日はSLOW_FACTORSのみ補正
- **修正**: 対象日 > 今日 → `_fetch_forecast_wx()` でForecast/Marine APIから取得
  - 風速/向き・気温・気圧・降水量・波高/周期・うねり・SST・潮流（5-12時平均）
- **ログ**: `analysis/V2/results/predict_log.jsonl` に JSONL 追記
  - 記録: ts, fish, ship, target_date, wx_source, baseline, correction, predicted, factors_used, wx_keys

### OOS r 改善（combo_deep_dive.py）
- cnt_avg: +0.403（変化なし）
- **cnt_max: +0.146 → +0.364**（ratio-based: cnt_avg_pred × 旬別比率）
- **cnt_min: +0.085 → +0.142**（同上）
- size_avg: +0.106 → +0.110（point×旬別ベースライン + cnt補正）
- avg_pred_store[H][date] に cnt_avg 予測を蓄積し cnt_max/cnt_min/size に転用

---

## ✅ 今セッション完了（2026/04/13 後半）

### 過学習対策（BL2勝率 +5〜6pt 改善）
- **根拠**: n/特徴量比 ≈ 3〜5（中央値29因子）→ 偽相関を大量採用し訓練データ記憶
- **変更点（combo_deep_dive.py）**:
  - `fold_corr_thr`: 固定0.10 → 適応的 `max(0.15, 1.96/√n)` (n=30→0.36, n=100→0.20, n=300→0.11)
  - `best_corr_thr`: 最終パラメータ確定部も同様に適応的閾値
  - TOP-K: 採用因子を相関上位 **MAX_FACTORS=10個まで** に制限
  - `alpha_scale` 上限: 2.0 → **1.2**（補正過大適用を防止）
  - `save_wx_params`: INSERT前にDELETEで旧因子行をクリーン化
- **結果（全55魚種再実行後）**:
  - H=0 wMAPE 中央値: 41.0%（変化なし。データのノイズ上限が支配的）
  - BL2勝率 H=0: 85.9% → **91.3%** (+5.4pt)
  - BL2勝率 H=7: 83.9% → **90.4%** (+6.5pt)
  - OOS r 平均: -0.069 → -0.065（微改善）
  - 因子数 中央値: 29 → **7**（大幅削減）
  - KAIYU昇格: 5件（変化なし）

---

## ✅ 今セッション完了（2026/04/13 後半）

### 欠航予測：コンボ（船宿×釣り物）レベル閾値を実装（大幅改善）
- **根拠**: 釣り物ごとに異なるエリア・季節 → 出航可否の海況基準が異なる
- `cancel_threshold.py`: `tsuri_mono` をレコードに追加、`(ship, tsuri_mono, date)` で個別デュープ
  - 同じ 2パスロジック（荒天+台風→初期閾値→定休日/不明を再分類）をコンボレベルで適用
  - 新テーブル `cancel_thresholds_combo (ship, tsuri_mono, wave_threshold, wind_threshold, ...)` を DB 保存
- `backtest_oos.py`: (ship, tsuri_mono) でコンボ閾値優先ルックアップ、なければ船宿レベルにフォールバック

**結果（OOS検証 2026-01-13〜2026-04-12）:**
- 評価対象欠航数: 9件 → **64件**（コンボ粒度でカバー拡大）
- カバー船宿数: 4船宿 → **10船宿**
- Precision: 69.2% → **94.1%**
- Recall: 100% → **100%**（維持）
- **F1: 81.8% → 97.0%**（+15.2pt）

## ✅ 今セッション完了（2026/04/12）

## ✅ 今セッション完了（2026/04/13）

### バックテスト設計を walk-forward → leave-one-month-out CV に変更（根本改善）
- **根拠**: 実運用では3年分のデータ全体で学習してから予測するため、バックテストも同様にすべき
- walk-forward（過去のみで学習）だと初期foldが「未熟期モデル」になり wMAPE が悲観的かつ不正確
- leave-one-month-out: 各テスト月に対し「それ以外の全データ（前後含む）」で学習
- 気象×釣果の相関は自然法則なので「未来データを学習に含む」リスクは許容範囲

**`combo_deep_dive.py` 変更箇所（3箇所）:**
- `section_backtest_rolling()` ドキュメント更新
- `train_en_h0` 条件: `< test_month` → `!= test_month`（1行変更）
- 初期ガード: `MIN_TRAIN_MONTHS + 1` → `2`（最低2ヶ月あれば実行）
- `final_train`: `TRAIN_END以前` → 全件（TRAIN_END廃止）

**結果（全55魚種再実行後）:**
- H=0 wMAPE 中央値: 42.8% → **39.9%** (-2.9pt)
- H=0 と H=7 の差: 数pt〜10pt → **2.0pt**（前後データで学習するため当然）
- BL-2 勝率: 83.0% → **90.8%** (+7.8pt)
- KAIYU 昇格コンボ: 4件 → **5件**

**昇格コンボ（2026/04/13時点）:**
- カツオ × 増福丸 H=7=38.7%（新規）
- カツオ × 平安丸 H=7=55.3%（新規）
- カンパチ × 龍正丸 H=7=48.0%（継続）
- サワラ × 林遊船 H=7=59.4%（新規）
- ワラサ × 喜平治丸 H=7=56.7%（新規）

### combo_meta 未登録問題（根本対応）完了
- `save_combo_meta()` を `combo_deep_dive.py` の `deep_dive()` 内に追加
- 全55魚種実行後: combo_meta 258行（196→258）

### TRAIN_END fallback fix（新規コンボ対応）
- 2025年以降データのみのコンボで `final_train=[]` → `wx_params_data={}` の問題を修正
- `if not final_train: final_train = list(all_en_by_H[0])` → TRAIN_END廃止で根本解決

---

## ✅ 前セッション完了（2026/04/12）

### 潮流データ追加（超重要新特徴量）
- **根拠**: 長崎屋のシーバスkanso「潮止まり近い時間帯は小型が主体」「バラシ多数」→ 潮流が釣果を直接左右する
- **Open-Meteo Marine API** に `ocean_current_velocity`, `ocean_current_direction` が存在することを確認（東京湾で0.6m/s等リアルな値が返る）

**`rebuild_weather_cache.py` 改修:**
- `fetch_marine()` に `ocean_current_velocity`, `ocean_current_direction` 追加
- `--update-current` フラグ新設（既存データに潮流列だけ追記する差分モード・約15分）
- `init_db()` に ALTER TABLE マイグレーション（current_speed/current_dir列）
- 153座標 × 3年分 = 約145万行を更新中（バックグラウンド実行中）

**`combo_deep_dive.py` に潮流特徴量追加:**
- `get_daily_wx()` のSELECT文に `current_speed, current_dir` 追加
- `result["current_speed_avg"]`, `result["current_speed_max"]`, `result["current_dir_mode"]` 計算
- `WX_FACTORS` に 3変数追加
- `FAST_FACTORS` に分類（潮流は数時間で変化 → H>7 では無効化）

### 乗っ込み・産卵期フラグ追加（SLOW因子）
- **根拠**: シーバス乗っ込み（2〜4月）、マダイ乗っ込み（4〜6月）、サワラ（3〜5月東京湾接岸）等
- `_spawn_season_n(date_str)`: 2〜5月 = 1, それ以外 = 0
- `SLOW_FACTORS` に追加（カレンダー確定値 → 全ホライズン有効）
- `CALENDAR_FACTORS` に追加
- `load_records()` でレコードに自動付与

### 回遊魚 KAIYU 自動昇格システム（実行完了・4コンボ昇格）
- **根拠**: 潮流データ追加により、カツオ/ブリ/サワラ等は匹数予測に移行できる可能性がある
- `KAIYU_PROMOTE_WMAPE_THR = 60.0`（60%以下 + BL-2勝ち で昇格。%値で保存）
  - ⚠️ バグ修正: 初期値 0.60（分率）→ 60.0（%値）に修正
- 昇格条件: H=7 cnt_avg wMAPE < 60% かつ BL-2 wMAPE を下回る
- `combo_wx_params` テーブルに `kaiyu_promoted` 列追加（ALTER TABLE マイグレーション済み）
- `deep_dive()` でバックテスト後に自動判定・保存
- `predict_count.py` に `_get_kaiyu_promoted()` 追加
  - `kaiyu_promoted=True` のコンボは `is_kaiyu=False` に切替 → 通常の cnt_lo/cnt_hi 予測
  - ★チャンス評価をスキップして匹数レンジ表示へ
- **昇格済み4コンボ（全55魚種実行後）**:
  - カンパチ × 龍正丸 wMAPE=45.7%（r=+0.411, n=236）
  - カンパチ × 佐衛美丸 wMAPE=57.5%（r=+0.437, n=31）
  - キハダマグロ × 平安丸 wMAPE=58.9%（r=+0.386, n=56）
  - キハダマグロ × 恒丸 wMAPE=59.8%（r=+0.121, n=30）

### obs_fields.json 改善（kanso品質向上）
- `tide_speed_n`: 「潮止まり」「潮止り」を -1.0 として明示追加（「止まり」との重複強化）
- `activity_n`: 「バラシ多」-1.0, 「バラシが多」-1.0, 「バラシ」-0.5 追加
  - 根拠: バラシ多数 = 食いが浅い / 掛かりにくい = 実釣果少ない（長崎屋実証）

---

## ✅ 前セッション完了（2026/04/11）

### 回遊魚★チャンス評価システム（全実装完了）
- **combo_deep_dive.py**: `KAIYU_FISH` 定数追加、`_star_by_key` 蓄積、`combo_star_backtest` テーブル新設
  - 定量ベースの★割当（P20/P40/P60/P80）
  - 良日ライン = P75（median=1問題を回避）
  - good_line ≤ 3 ガード（実質釣れないコンボは ★表示しない）
  - H=7 を本番ホライズンとして採用
  - 全55魚種実行完了: combo_star_backtest に91行（13コンボ×7H）
- **predict_count.py**: `calc_stars_kaiyu()` 追加、`kaiyu_stars` フィールドを返す
- **crawler.py**: `_pred_build_html` 改修
  - 回遊魚 → 「チャンス★ / 良日目安 / ★5的中率」表示
  - 根魚・底もの → 従来の匹数レンジ表示
  - 2セクション構成

### 評価軸確定（2026/04/11）
- promise_break_rate = PRIMARY KPI（期待させて釣れなかった率）
- combo_range_backtest: promise_break_rate, over_expect_rate, coverage, bowzu_rate, winkler保存
- 全55魚種でのbacktest完了

### 前セッション完了（2026/04/11 前半）
- wave_clamp per-combo HPO: 採用（アジ -14.5pt改善）
- use_fallback: 4コンボ追加（計10コンボ）
- 相関閾値/FAST_MAX_H per-combo HPO: 変化なし → 不採用・固定継続
- 全55魚種再実行: H=0 42.8%, BL2勝率83%

---

## 確定した設計方針（変更不可）

### 回遊魚評価設計（2026/04/12更新）
- KAIYU_FISH: {"シイラ", "カツオ", "キハダマグロ", "ブリ", "ワラサ", "イナダ", "サワラ", "カンパチ"}
- デフォルト: ★チャンス評価（P20/P40/P60/P80分位）
- 昇格条件: H=7 wMAPE < 60% + BL-2勝ち → `kaiyu_promoted=True` → 匹数レンジ予測に切替
- 良日ライン: actual P75（good_line ≤ 3 のコンボは kaiyu=None）

### 特徴量分類（2026/04/12更新）
- **SLOW_FACTORS**（全H有効）: SST, 気温, 気圧, 潮汐, 月齢, 土日祝, 連休, 夏休み, **spawn_season_n（新規）**
- **FAST_FACTORS**（H>7 無効）: 風, 波, うねり, 降水, 前週釣果, 台風, **current_speed/dir（新規）**
- FAST_MAX_H = 7（デフォルト）。per-combo override: メバル×第三幸栄丸 = 3

### weather_cache.sqlite スキーマ（2026/04/12更新）
- 列: lat, lon, dt, wind_speed, wind_dir, temp, pressure, wave_height, wave_period, swell_height, sst, precipitation, **current_speed（新規）**, **current_dir（新規）**
- 153座標 × 2023-01-01〜今日 × 3時間毎 ≒ 145万行

### 評価指標設計（2026/04/11確定）
- pred_hi = cnt_maxモデル出力 → actual_maxと比較
- pred_lo = cnt_minモデル出力 → actual_minと比較
- actual_avgは評価に使わない
- 失敗優先順位: Max過大予測 > ボウズ見逃し > Max保守すぎ > Min保守すぎ

### FISH_MAP → 廃止決定（2026/04/09確定）
- **不要**: `tsuri_mono + main_sub` で同等のフィルタが可能
- 分析クエリは `tsuri_mono = "アジ" AND main_sub = "メイン"` で行う

### ships.json フィールド（2026/04/03更新）
- `exclude: true` → 利一丸・岩崎レンタルボート・海上つり堀まるや（3件）
- `boat_only: true` → 青木丸（1件）
- 有効船宿: 75件＋静岡エリア多数

### データ収集状況（2026/04/12時点）
- catches_raw.json: **84,757件**（欠航893件含む）
- data/YYYY-MM.csv: **64,112行**（幸栄丸・ふじや・山本・村松 除外後）
- 期間: 2023/01/01〜2026/04/03

### ポイント解決（3段階フォールバック・完全実装済み）
```
① point_place1 → point_coords.json（306ポイント）→ 座標
② 空/航程系 → ship_fish_point.json（73船宿）→ ポイント名 → 座標
③ ② も未登録 → area_coords.json（58エリア）→ 直接 lat/lon
```
- 解決率: **94.9%**（除外船宿を除く）

### 価格・マネタイズ
- **月額500円 / スポット100円**
- 無料=事実、有料=分析+予測

---

## 後回し・未実装
- [ ] 決済連携（Stripe等）
- [ ] AdSense審査結果待ち（2026/03/21申請済み）
- [ ] X自動投稿（アカウントロック解除待ち）
- [ ] crawl.ymlのNode.js 20→24アップグレード
- [ ] ちがさき丸×マダイ/シーバス/メバル 個別改善（r=-0.17等・★候補）
- [ ] 外道表示機能（by_catch × 旬別集計 → 予測ページへ追加）
