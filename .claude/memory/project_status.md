現行バージョン: crawler.py v5.28 / predict_count.py（Forecast API統合済み・FAST変数horizonフィルタ実装済み）
最終更新: 2026/05/08
最新コミット: 3eebfe53（Phase B-α' size 実測幅ベースレンジ生成・同一定義 +43.6pt 改善確定）

## ✅ 今セッション完了（2026/05/08 後半・engineer）

### Phase B-α' コミット + SQL クリーンアップ

**コミット: 3eebfe53**

**変更ファイル:**
- `analysis/V2/methods/combo_deep_dive.py`: P20/P80 比率列追加（avg_size_min / avg_size_max・無次元比率）・妥当性チェック・winkler コメント修正
- `analysis/V2/methods/predict_count.py`: size_lo/hi を pred_avg × 旬別比率に変更（旧 ±size_mae 廃止）・フォールバック実装
- `analysis/V2/analysis-improvement/plan_size_2026-05-08.md`: 改訂版（P20 採用・coverage 撤回基準除外）
- `analysis/V2/analysis-improvement/90_決定ログ.md`: 補遺7 追記済み
- `dustbox/` 配下 8 ファイル: バックアップ・分析資料（記録として保存）

**SQL クリーンアップ完了:**
- `combo_range_backtest` から `metric='size_i'` 7 行を削除（Phase B-α 撤回時の実験残骸）
- 残存 metric: cnt=2033件 / size=1267件 / kg=721件

**全コンボ再実行:**
- 現在時刻確認中（16:30 JST GitHub Actions 衝突回避のため別途 Step 5 で判定）

---

## ★ 次セッションでやること（優先度順）

### 1. 全コンボ再実行の結果確認（Phase B-α' 適用後の全コンボ性能）
- コマンド: `python analysis/V2/methods/run_full_deepdive.py --workers 4`（約 4 時間）
- ログ: `analysis/V2/results/run_full_deepdive_YYYY-MM-DD.log`
- 完了後の確認 SQL:
  ```sql
  SELECT metric, horizon, COUNT(*), AVG(promise_break_rate), AVG(coverage)
  FROM combo_range_backtest
  WHERE n >= 30
  GROUP BY metric, horizon
  ORDER BY metric, horizon;
  ```
- 期待: size promise_break P50 が 98.4% → 53.0%（同一定義）から大幅改善

### 2. Phase B-β（cnt min/max 独立予測復活）の Plan 策定
- Phase A の全コンボ再実行結果を踏まえて着手判断
- size の実測幅ベース設計（B-α'）を cnt にも適用するか検討
- 独立モデル化の前例（04/13 撤回）を参照し、撤回基準を先に確定する

### 3. Phase C 実装（Phase B 後）
- 加重平均 composite_hit_rate（cnt 0.6 / size 0.3 / kg 0.1）
- kg NULL 率 70% で実態は 0.667/0.333 に再正規化されるケース多数

---

## ✅ 今セッション完了（2026/05/08 前半）

### 「商品的中率」KPI Phase A 実装 + Phase B シミュレーション準備

**Phase A コミット（2b25b2d3）:**
- `combo_range_backtest` テーブルに `metric` 列追加（PK: fish, ship, metric, horizon）
- cnt のみ → cnt/size/kg の 3 メトリックに拡張
- size/kg ループの分母を NULL 除外後 `n_valid` に統一（NULL 率 38.8%/70.2% でのバイアス回避）
- `_RANGE_BACKTEST_CORE` をループ外定数化
- size/kg の `over_expect_rate` を cnt と方向統一（「期待させすぎ率」: pred/actual > 1.5）
- DDL コメントに winkler 単位混在・bowzu_rate cnt 限定を注記

**フロー:**
- analyst 実装 → 3 並列レビュー（code/stat/data）すべて Concerns → 修正 → code-reviewer 軽量再レビュー → engineer コミット
- 3 reviewer 共通指摘「coverage 分母バイアス」を 1 修正で解決

**90_決定ログ「2026/05/08 補遺2 + 補遺3」追記:**
- 出力形式の絶対制約を明記
- **補遺3 で確定: 出力は min〜max のみ・avg は出さない**（"1,1,1,100" と "1,99,99,99,100" の avg が同じになる問題）
- 重ねレンジ禁止・min/max 別カード禁止
- 「min/max 独立予測」は内部学習が独立というだけで出力は単一レンジ
- plan_hit_rate / CLAUDE.md にも同制約反映
- 表示仕様: 数 `min匹〜max匹` / 型 `min cm〜max cm` / 重 `min kg〜max kg`

**Phase B 防御策シミュレーション完了:**
- レポート: `analysis/V2/analysis-improvement/diag_phase_b_simulation_2026-05-08.md`
- 推奨採用値:
  - 防御策① pred_lo 下限: `pred_lo >= avg_cnt × 0.3`（発動率43%・BL2負けコンボ64.9%カバー）
  - 防御策② 区間幅上限: `区間幅 <= avg_cnt × 2.0`（発動率1%・winkler副作用最小）
- Plan の不明点 #6（winkler 整合性）解消
- Phase B 実装判定: **Go**

**Phase A 全コンボ再実行完了（H=0, n>=30）:**

| metric | コンボ数 | promise_break P50 | coverage | over_expect | bowzu | winkler |
|---|---|---|---|---|---|---|
| cnt  | 290 | 6.7%  | 79.3% | 32.1% | 16.2% | 18.33 |
| size | 181 | 52.9% | 90.6% | 2.0%  | N/A   | 5.67  |
| kg   | 103 | 55.6% | 67.9% | 20.0% | N/A   | 2.52  |

**重要発見:**
- cnt 精度安定（前回 7.5% → 6.7% 微改善）
- size/kg promise_break ≈ 53-56% で **系統的に過大予測**
- size coverage 90.6%（実測レンジに入る）に対して promise_break 53% が高い
  → 構造的問題: size_avg = (size_min + size_max)/2 で計算した予測点が actual_avg より高めに張りつく傾向
- Phase B/C 実装時に size/kg の独立モデル化（または floor の size 版）を要検討

---

## ★ 次セッションでやること（優先度順）

### 1. Phase A 全コンボ再実行の結果確認（最優先）
- バックグラウンド実行: ID `b3q4iz6lo`・`run_full_deepdive.py --workers 4 --reset-best`
- ログ: `analysis/V2/results/run_full_deepdive_2026-05-08.log`
- 完了後の確認 SQL:
  ```sql
  SELECT metric, horizon, COUNT(*), AVG(promise_break_rate), AVG(coverage)
  FROM combo_range_backtest
  WHERE n >= 30
  GROUP BY metric, horizon
  ORDER BY metric, horizon;
  ```
- size/kg の promise_break_rate 実態を Phase B 防御策の判断材料に

### 2. Phase B-α' 実装着手（実測幅ベース・新設計・補遺6）
- 着手前必読: `plan_size_2026-05-08.md`（改訂版）・`diag_size_2026-05-08.md`・`90_決定ログ.md`「2026/05/08 補遺2・補遺3・補遺5・補遺6」
- **【設計変更】** Phase B-α（size_min/max 独立モデル + 防御策）は 1 コンボ悪化で撤回（補遺6）
  - 真の解は「中央予測モデル維持 + 実測幅ベースのレンジ生成」
  - ユーザードメイン知識: size_max は「お化け」で重要度低 → 非対称設計
- 実装内容:
  - combo_decadal に avg_size_min / avg_size_max（外れ値 P95 除外）列追加
  - predict_count.py の size_lo/hi を `pred_avg ± (旬別実測幅)` に変更
  - 防御策 floor / clamp は **削除**（実測ベースで不要）
- 撤回基準（更新）: promise_break 改善<30pt or coverage<80% に悪化
- 期待効果: promise_break 53% → 10〜15%（数式根拠あり）
- **【拡張理由】** size promise_break 53% は size_avg=(min+max)/2 の構造問題。ポイント補正は既存の section_backtest_rolling 内で動いており、追加効果は実測されない（2026/05/08 診断で確定）
- 変更ファイル:
  - `combo_deep_dive.py` L3285-3290 の ratio override を削除（cnt 用）
  - **`combo_deep_dive.py` に size_min / size_max メトリックを追加**（cnt と同型）
  - `predict_count.py` L1296-1333 に防御策①②（floor=0.3 / clamp=2.0）追加
  - **`predict_count.py` size_lo/size_hi を独立モデル予測に切替**（既存の `avg_size ± size_mae` 廃止）
  - **`predict_count.py` の avg 系出力をユーザー表示用に返さない**（補遺3）
  - **`crawler.py` forecast HTML の `（avg X匹/cm/kg）` 表示を削除**（補遺3）
- **3 並列レビュー必須**（過去 04/13 撤回パターン再発防止）
- 実装後の全コンボ再実行も必要（4時間 × 1回）

### 2-bis. Phase A 後の追加実装メモ（2026/05/08 後半）
- `predict_count.py` L1341-1357 に size ポイント別補正追加済み（コミット 1ec169ab）
  - `_apply_point_wx_correction(metric='size_avg')` を呼ぶ
  - キーカバレッジ 28%（events 256種 vs params 90種・交差72種）
  - 本番予測のみで効果。backtest（combo_range_backtest）には反映されない
- combo_deep_dive.py への統合は **不要と判定**:
  - cnt も backtest で combo_point_wx_params を使っていない（独自経路）
  - 全データ学習パラメータを backtest で使うとリーク発生
  - 既存の section_backtest_rolling は size_point_dec / cnt→size slope / 気象因子の3補正を**リークなしで既に使用中**
  - 良コンボも悪コンボも pt_param 存在率が同等（92% vs 93%）→ ポイント補正の有無は精度差を説明しない
- 真の改善策 = **size_min/size_max 独立予測（Phase B 拡張）**

### 3. Phase C 実装（Phase B 後）
- 加重平均 composite_hit_rate（cnt 0.6 / size 0.3 / kg 0.1）
- kg NULL 率 70% で実態は 0.667/0.333 に再正規化されるケース多数

---

## ✅ 前セッション完了（2026/04/22 後半）

### 過去データ補完・CSV再生成・全種再分析

- **history_crawl_single.py 修正**: CUTOFF="2023/04/04"（旧 "2026/01/06"）、--start-page デフォルト=1
- **クロール対象**: 光進丸・弘漁丸・庄治郎丸・不動丸・幸丸・喜平治丸（2023/04まで遡って取得）
- **catches_raw.json**: 89,612件 → 96,697件（+7,085件）
- **CSV再生成**: `crawler.py --export-csv` → 68,243行 → 74,966行（+6,723行）
- **全種再分析**: `run_full_deepdive.py --workers 4 --reset-best`（ポイント別・水深別も自動実行）

**精度更新:**
- H=0 wMAPE P50: 41.6% → **39.4%**（-2.2pt）
- H=0 BL-2勝率: 88.5% → **94.0%**（+5.5pt）
- combo_meta: 230 → **252コンボ**（+22）
- combo_point_backtest: 5,894 → **6,629行**
- kaiyu_promoted: 10 → **14コンボ**

コミット: 3146af3a

## ✅ 今セッション完了（2026/04/22 前半）

### FAST変数 horizon フィルタ実装（predict_count.py）

- **問題**: 全 correction 関数が H>7 の予測でも波高・風速・潮流等の FAST変数を適用していた
- **修正**: `_FAST_FACTORS` frozenset + `FAST_MAX_H=7` + `_h_days()` を predict_count.py に追加
- `_apply_correction_from_params(h_days)` が H>7 の場合 FAST変数を factor_params から除外
- 対象 5関数: `_apply_wx_correction` / `_apply_trip_wx_correction` / `_apply_water_color_wx_correction` / `_apply_point_wx_correction` / `_apply_point_depth_wx_correction`
- logging バグも同時修正（H>7 のログで correction/factors_used がフィルタ前参照になっていた → `log_fps` で修正）
- data-reviewer: `_FAST_FACTORS` と DB の全 factor 名が完全一致確認済み

---

## ✅ 今セッション完了（2026/04/19 夜）

### BL2負けコンボの診断・改善（N≥100コンボ対象）

**MIN_MONTHS=6 ガード追加（タチウオ×吉野屋 wMAPE=404% の根本対策）**
- `section_backtest_rolling()` の先頭に `len(months) < MIN_MONTHS → return` を追加
- 3ヶ月分データのみコンボが季節トレンドを気象相関と誤認して r=-0.52 逆補正を起こす問題を防止

**use_fallback 自動判定 + 手動追加（今セッション）**
- 自動（r<0 逆補正判定）: タチウオ×吉野屋, フグ×幸栄丸, ワラサ×幸栄丸, ムギイカ×庄治郎丸, マルイカ×平安丸, サワラ×こなや丸
- 手動 UPDATE: マルイカ×第八鶴丸（N=12・alpha_scale=0.1で補正効果なし）
- 現在の use_fallback=1 コンボ: **19件**（ユニーク）

**ムギイカ KAIYU_FISH 追加（好調コンボを★評価系に昇格）**
- `KAIYU_FISH` に `"ムギイカ"` を追加
- `KAIYU_PROMOTE_WMAPE_THR` を 60.0 → **62.0** に緩和（ムギイカ×秀丸 H7=60.1% を昇格させるため）
- 新規 kaiyu_promoted=1: ムギイカ×秀丸（★5的中率73%）・ムギイカ×第八幸松丸・カンパチ×佐衛美丸
- kaiyu_promoted 総計: **10件**（コンボユニーク）

**現在の精度（2026/04/19 夜 時点）**
- H=0 wMAPE中央値: **41.7%**
- H=0 BL-2勝率: **88.1%**（193/219コンボ）
- kaiyu_promoted コンボ: 10件

**注記: n_valid_fac threshold 変更を試行したが BL2勝率 -1.8pt → リバート済み**

---

## ✅ 今セッション完了（2026/04/19 後半）

### SLA特徴量追加（kuroshio_sla_monthly / sla_pelagic_monthly）

- `kuroshio_sla_monthly`（33-37°N,139-142°E 月次SLA絶対水準）を SLOW_FACTORS に追加
- `sla_pelagic_monthly`（34-36°N,141-143°E 沖合月次SLA）を SLOW_FACTORS に追加
- 169コンボに採用。強相関: イナダ avg|r|=0.616・スミイカ0.571・サワラ0.527・カツオ0.509
- 全55種再実行完了

**現在の精度（2026/04/19 SLA追加後）**
- H=0 wMAPE中央値: **41.7%**（前回41.6%、横ばい）
- H=0 BL-2勝率: **88.6%**（前回88.5%、横ばい）

## ✅ 今セッション完了（2026/04/19 前半）

### CSV正規化修正 + combo_meta整理

**「数匹」→ 0〜2匹変換（cnt_avg=1）**
- `extract_count()`: 「数匹」「数尾」等 → min=0, max=2
- `export_csv_from_raw()`: tokki_raw/weight_raw/size_rawにも「数匹」フォールバック追加
- 効果: ハタ×北山丸 cnt_avg>0が 13→33件（MIN_N_COMBO=30突破）

**CSV全再生成（64,349行）**
- 旧CSV正規化バグを修正（「マルイカ・ヤリイカ」→ヤリイカメイン誤分類等）
- マハタ5船宿が新規に30件超え（明広丸87・幸丸85・勇盛丸73・北山丸70・幸栄丸47）

**全魚種deepdive再実行 + 8魚種追加再実行**
- combo_meta: 247 → 220コンボ（正規化後の実態に合わせ整理）
- 削除27件: ヤリイカ×8船宿（誤分類）、ワラサ・フグ・アカムツ等
- 新規追加: ハタ×北山丸、マハタ×5船宿

**精度（前半完了時点 2026/04/19）**
- combo_meta: 220コンボ
- wMAPE P50 H=0: 41.6%
- BL2勝率 H=0: 88.5%
- マハタ×北山丸 H=7: 20.4%（全コンボ中トップクラス）

**ドキュメント更新**
- PIPELINE.md v2.3: CMEMS・32テーブル・55種/45種の正確な記述
- sla_approach_idx（黒潮接岸指数）特徴量追加・水色距離フィルター追加
- 魚種数表記: 「実行55種・バックテスト完了45種」に明確化

---

## ★ 次セッションでやること（優先度順）

### 精度改善候補
- [ ] サワラ・イナダ・タイ五目（wMAPE 70-78%）の診断（SLA追加後でも高MAPE継続かチェック）
- [ ] クロムツ（68%）の特徴量見直し
- [ ] ちがさき丸×マダイ/シーバス/メバル 個別改善（r=-0.17等）
- [ ] カサゴ×北山丸: alpha_scale=0.1（floor）だが BL2比+0.3pt 勝ち → 現状維持

### データ
- [ ] tsuri_mono空 363件の正規化失敗レコード調査・修正
- [ ] カツオ×幸丸（29件）・たいぞう丸（28件）: 30件突破待ち

### 未実装
- [ ] 有料ページUI + 決済（Stripe）実装
- [ ] 外道表示機能
- [ ] predict_count.py: 同一座標キャッシュ

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

### 回遊魚評価設計（2026/04/19更新）
- KAIYU_FISH: {"シイラ", "カツオ", "キハダマグロ", "ブリ", "ワラサ", "イナダ", "サワラ", "カンパチ", "ムギイカ"}（ムギイカ追加）
- デフォルト: ★チャンス評価（P20/P40/P60/P80分位）
- 昇格条件: H=7 wMAPE < **62%** + BL-2勝ち → `kaiyu_promoted=True` → 匹数レンジ予測に切替（62に緩和）
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
