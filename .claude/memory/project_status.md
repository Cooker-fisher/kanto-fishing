現行バージョン: combo_deep_dive.py（Phase C composite_hit_rate 採用確定）
最終更新: 2026/05/09 早朝
最新コミット: 本コミット（Phase C 採用確定・composite_promise_break P50 13.94%）

---

## ✅ 直近完了（2026/05/09 早朝・main agent）

### Phase C composite_hit_rate 採用確定（補遺10 追記）

**実行**: `run_full_deepdive.py --workers 4 --reset-best` で 55/55 OK・43分51秒

**全コンボ適用後 backtest（H=0, n>=30）:**

| metric | n | promise_break P50 | coverage avg |
|---|---|---|---|
| cnt | 290 | 11.0% | 79.4% |
| **composite** | **290** | **13.94%** | **69.4%** |
| size | 181 | 31.8% | 40.4% |
| kg | 103 | 25.7% | 42.2% |

**設計**:
- 加重平均 cnt:size:kg = 0.6:0.3:0.1（線形加重和・行レベル集計）
- combo_range_backtest に metric='composite' 行追加（既存非破壊）
- component_count 列で 1/2/3 を記録（{1: 14, 2: 276, 3: 0}）
- HTML 表示なし・内部評価指標のみ（補遺3 整合）

**判定: 採用確定**
- 成功基準 9 項目全クリア（Plan §4）
- composite_promise_break P50=13.94% は cnt 11.0% に近く、重み 0.6 の cnt 支配が事業方針通り
- レビューサイクル v1→v1.5・5巡（CRITICAL 解消後 MINOR 連鎖）→ 実装着手判断

**詳細**: `analysis/V2/analysis-improvement/90_決定ログ.md` 補遺10 / `plan_C_2026-05-08.md` v1.5

### Phase B-β-4 全コンボ再実行・採用確定（補遺9 追記・前セッション分）

**実行**: 22:15 JST 開始 → 22:42 JST 完了・55/55 OK・26分59秒（`run_full_deepdive.py --workers 4 --reset-best`）

**全コンボ適用後 backtest（H=0, n>=30, 103コンボ）:**

| 指標 | Phase A 同一定義（旧）| Phase B-β-4（新）| 改善幅 |
|---|---|---|---|
| **kg promise_break P50** | 55.56% | **23.93%** | **+31.63pt** |
| kg coverage 平均 | 67.87% | 42.24% | -25.6pt（許容）|
| kg over_expect 平均 | 19.97% | 36.24% | +16.3pt（KPI 外）|
| kg winkler 平均 | 2.52 | 4.08 | +1.56（許容）|

**判定: A 採用確定**
- 同一定義基準 +31.63pt は plan_kg v2 撤回基準（+15pt）の **2.11倍改善**
- 副作用（winkler/coverage/over_expect 悪化）は数学的必然・補遺6/7/8 と同方針で許容
- MIN_N=5 採用維持（マダイ×ちがさき丸 非NULL率 5% でも改善幅大・グローバル比率効果が支配的）

**1コンボ動作確認結果:**
- マダイ×ちがさき丸（n=42）: 55.56% → 40.48%（+15.06pt・撤回基準ギリギリ）
- マハタ×幸丸（n=83）: 55.56% → 26.50%（+29.06pt・余裕クリア）

**詳細**: `analysis/V2/analysis-improvement/90_決定ログ.md` 補遺9

### Phase B-α' 全コンボ再実行・採用確定（補遺8 追記・前セッション分）

**実行**: 17:26 JST 開始 → 19:36 JST 完了・55/55 OK・130分52秒（`run_full_deepdive.py --workers 4 --reset-best`）

**全コンボ適用後 backtest（H=0, n>=30, 181コンボ）:**

| 指標 | Phase A 同一定義（旧）| Phase B-α' 全（新）| 改善幅 |
|---|---|---|---|
| **size promise_break P50** | 98.4% | **31.25%** | **+67.2pt** |
| size coverage 平均 | 高い | 0.40 | 大幅低下 |
| size over_expect 平均 | 0.02 | 0.32 | +30pt 増加 |
| size winkler 平均 | 5.8 | 23.2 | +17.4 増加 |

`combo_decadal.avg_size_min/max` 充足率: 81.4%（6598/8105）。残り 18.6% は旬別 n<10 で全期間グローバル比率にフォールバック（仕様通り）。

**判定: A 採用確定**
- 同一定義基準 +67.2pt は plan_size 期待値（+30pt）の **2.24倍改善**
- 副作用（winkler/coverage/over_expect 悪化）は数学的必然・補遺6/7 で許容ドメイン確定済み
- pb 30-50% 帯張り付き 98コンボ（54.1%）は pred_avg と actual_avg の系統的乖離が原因 → P20→P10 への比率変更では救えない・中央予測モデル別軸の改善要

**詳細**: `analysis/V2/analysis-improvement/90_決定ログ.md` 補遺8

---

## ★ 次セッションでやること（優先度順）

### 1. 30-50% 帯張り付き救済（中央予測モデル改善）

- size: 31.8% で帯張り付き残存（kg は 25.7% / composite 13.94% で解消気味）
- pred_avg と actual_avg の系統的乖離が原因
- 中央予測モデル（size_avg）の精度向上が本質的解決
- Phase B/C 系とは別軸の Plan 化が必要

### 2. D 層予測モデル本番実装

- Phase B/C で評価指標が揃った（cnt/size/kg/composite の promise_break P50 確定）
- D 層は予測モデルの本番化（cnt P50=11.0%・composite P50=13.94% を維持して実装）
- 設計済み・実装待ち（CLAUDE.md 「未実装・ブロック中」）

### 3. キハダマグロ winkler 高止まり時の E 層フィルタ（plan_kg v2 リスク 7・覚書）

- キハダマグロ winkler=21.0（kg 改善後も高止まり懸念）
- E 層で winkler 閾値フィルタが必要なケース判定

### 4. cnt 系の改善検討（優先度低）

**現状値（H=0, n>=30, 290コンボ）:**
- cnt promise_break P50 = **6.57%**（既に十分低い）
- cnt coverage 平均 = 0.79 / over_expect 平均 = 0.32

| 案 | 内容 | リスク評価 | 期待効果 |
|---|---|---|---|
| B-β-1 | バックテストから ratio override 撤去（独立予測評価）| 04/13 撤回パターン高リスク | 不明 |
| B-β-2' | 実測幅ベース cnt 版（Phase B-α' 同型・P50 → P20/P80）| 低リスク | 限定的（既に良好）|
| 保留 | cnt は良好で改善余地少 | 無リスク | - |

---

## ✅ 直近完了（2026/05/08 前半）

### 「商品的中率」KPI Phase A 実装（コミット 2b25b2d3）

- combo_range_backtest に metric 列追加（PK: fish, ship, metric, horizon）
- cnt → cnt/size/kg の 3 メトリックに拡張
- size/kg ループ分母を NULL 除外後 n_valid に統一

**90_決定ログ「補遺2 + 補遺3」追記:**
- 出力形式の絶対制約: min〜max のみ・avg は出さない
- 重ねレンジ禁止・min/max 別カード禁止
- 表示: 数 `min匹〜max匹` / 型 `min cm〜max cm` / 重 `min kg〜max kg`

**Phase A 全コンボ再実行（H=0, n>=30）:**

| metric | コンボ数 | promise_break P50 | coverage | over_expect | bowzu | winkler |
|---|---|---|---|---|---|---|
| cnt  | 290 | 6.7%  | 79.3% | 32.1% | 16.2% | 18.33 |
| size | 181 | 52.9% | 90.6% | 2.0%  | N/A   | 5.67  |
| kg   | 103 | 55.6% | 67.9% | 20.0% | N/A   | 2.52  |

**重要発見:**
- cnt 精度安定
- size/kg promise_break ≈ 53-56% で系統的に過大予測
- 構造的問題: size_avg=(min+max)/2 で actual_avg より高めに張りつく → Phase B-α' で対処

---

## ✅ 過去セッション要約（2026/04/11〜04/22）

**2026/04/22: 過去データ補完（コミット 3146af3a）**
- catches_raw.json: 89,612 → 96,697件（+7,085件）
- CSV再生成: 74,966行
- 全種再分析後精度: H=0 wMAPE P50 39.4% / BL-2勝率 94.0% / combo_meta 252 / kaiyu_promoted 14

**2026/04/22: FAST変数 horizon フィルタ**
- _FAST_FACTORS frozenset + FAST_MAX_H=7 + _h_days() 追加
- H>7 で波/風/潮流等を correction から除外

**2026/04/19: BL2負けコンボ診断・改善**
- MIN_MONTHS=6 ガード追加（タチウオ×吉野屋 wMAPE=404% 対策）
- use_fallback 自動判定 + 手動追加: 19件
- ムギイカ KAIYU_FISH 追加・KAIYU_PROMOTE_WMAPE_THR 60→62 緩和

**2026/04/19: SLA特徴量追加**
- kuroshio_sla_monthly / sla_pelagic_monthly を SLOW_FACTORS に追加
- 169コンボ採用・強相関: イナダ avg|r|=0.616 等

**2026/04/19: CSV正規化修正**
- 「数匹」→ 0〜2匹変換（cnt_avg=1）
- normalize_tsuri_mono 数字ノイズ除去（71件→0件）
- マハタ5船宿 30件超え

**2026/04/13: バックテスト方式変更（根本改善）**
- walk-forward → leave-one-month-out CV
- H=0 wMAPE 中央値: 42.8% → 39.9% (-2.9pt)
- BL-2勝率: 83.0% → 90.8% (+7.8pt)

**2026/04/13: 過学習対策**
- fold_corr_thr 適応的化 max(0.15, 1.96/√n)
- TOP-K MAX_FACTORS=10
- alpha_scale 上限 2.0 → 1.2
- BL2勝率 +5〜6pt 改善

**2026/04/13: 欠航予測コンボレベル化**
- F1: 81.8% → 97.0% (+15.2pt)
- カバー船宿 4→10 / 評価対象欠航 9→64件

**2026/04/13: Forecast API 統合（predict_count.py）**
- 未来日 → Forecast/Marine API から気象取得（風/温/圧/降水/波/うねり/SST/潮流）
- predict_log.jsonl に予測ログ追記
- cnt_max OOS r: 0.146 → 0.364（ratio-based）

**2026/04/12: 潮流・乗っ込みフラグ追加**
- weather_cache に current_speed/current_dir 列（Open-Meteo Marine API）
- spawn_season_n（2〜5月=1）SLOW_FACTORS に追加
- KAIYU 自動昇格システム実装

**2026/04/11: 回遊魚★チャンス評価システム**
- KAIYU_FISH 定数・combo_star_backtest テーブル新設
- 定量ベース★割当（P20/P40/P60/P80）
- 良日ライン = actual P75
- promise_break_rate を PRIMARY KPI に確定

---

## 確定した設計方針（変更不可）

### 回遊魚評価設計
- KAIYU_FISH: {"シイラ", "カツオ", "キハダマグロ", "ブリ", "ワラサ", "イナダ", "サワラ", "カンパチ", "ムギイカ"}
- デフォルト: ★チャンス評価（P20/P40/P60/P80分位）
- 昇格条件: H=7 wMAPE < **62%** + BL-2勝ち → kaiyu_promoted=True → 匹数レンジ予測
- 良日ライン: actual P75（good_line ≤ 3 のコンボは kaiyu=None）

### 特徴量分類
- **SLOW_FACTORS**（全H有効）: SST, 気温, 気圧, 潮汐, 月齢, 土日祝, 連休, 夏休み, spawn_season_n, kuroshio_sla_monthly, sla_pelagic_monthly
- **FAST_FACTORS**（H>7 無効）: 風, 波, うねり, 降水, 前週釣果, 台風, current_speed/dir
- FAST_MAX_H = 7（per-combo override: メバル×第三幸栄丸 = 3）

### バックテスト CV 設計
- leave-one-month-out: 各テスト月以外の全データで学習
- MIN_MONTHS=6 ガード（短期データの偽相関防止）

### 過学習対策
- fold_corr_thr 適応的: max(0.15, 1.96/√n)
- TOP-K MAX_FACTORS=10
- alpha_scale 上限 1.2

### weather_cache.sqlite スキーマ
- 列: lat, lon, dt, wind_speed, wind_dir, temp, pressure, wave_height, wave_period, swell_height, sst, precipitation, current_speed, current_dir
- 153座標 × 2023-01-01〜今日 × 3時間毎 ≒ 145万行

### 評価指標設計
- promise_break_rate = PRIMARY KPI
- pred_hi = cnt_max モデル出力 → actual_max と比較
- pred_lo = cnt_min モデル出力 → actual_min と比較
- 失敗優先順位: Max過大予測 > ボウズ見逃し > Max保守すぎ > Min保守すぎ
- 出力は min〜max のみ・avg は出さない

### FISH_MAP → 廃止
- tsuri_mono + main_sub で代替

### ships.json
- exclude: true → 利一丸・岩崎レンタルボート・海上つり堀まるや
- boat_only: true → 青木丸
- 有効船宿: 75件 + 静岡多数

### データ収集状況（2026/04/22 時点）
- catches_raw.json: 96,697件
- data/V2/*.csv: 75,553行
- 期間: 2023/01/01〜2026/04/03

### ポイント解決（3段階フォールバック）
```
① point_place1 → point_coords.json（306ポイント）→ 座標
② 空/航程系 → ship_fish_point.json（73船宿）→ ポイント名 → 座標
③ ② 未登録 → area_coords.json（58エリア）→ 直接 lat/lon
```
解決率: 94.9%

### 価格・マネタイズ
- 月額500円 / スポット100円
- 無料=事実、有料=分析+予測

---

## 後回し・未実装
- [ ] 決済（Stripe等）
- [ ] AdSense審査待ち（2026/03/21申請）
- [ ] X自動投稿（アカウントロック解除待ち）
- [ ] crawl.yml Node.js 20→24
- [ ] ちがさき丸×マダイ/シーバス/メバル 個別改善（r=-0.17等・★候補）
- [ ] 外道表示機能（by_catch × 旬別集計 → 予測ページ）
- [ ] 有料ページUI 実装
- [ ] predict_count.py: 同一座標 Forecast API キャッシュ
- [ ] サワラ・イナダ・タイ五目（wMAPE 70-78%）の診断
- [ ] クロムツ（68%）の特徴量見直し
- [ ] tsuri_mono 空 363件の正規化失敗レコード調査
- [ ] カツオ×幸丸（29件）・たいぞう丸（28件）: 30件突破待ち
