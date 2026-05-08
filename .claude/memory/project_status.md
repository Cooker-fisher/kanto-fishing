現行バージョン: crawler.py v5.28 / predict_count.py（Forecast API統合済み・FAST変数horizonフィルタ実装済み）
最終更新: 2026/05/08
最新コミット: 3eebfe53（Phase B-α' size 実測幅ベースレンジ生成・同一定義 +43.6pt 改善確定）

---

## ✅ 直近完了（2026/05/08 後半・engineer）

### Phase B-α' コミット + SQL クリーンアップ（コミット 3eebfe53）

**変更ファイル:**
- `combo_deep_dive.py`: P20/P80 比率列追加（avg_size_min / avg_size_max・無次元比率）
- `predict_count.py`: size_lo/hi を pred_avg × 旬別比率に変更（旧 ±size_mae 廃止）
- `plan_size_2026-05-08.md`: 改訂版（P20 採用）
- `90_決定ログ.md`: 補遺7 追記

**SQL クリーンアップ:**
- combo_range_backtest から metric='size_i' 7 行削除
- 残存 metric: cnt=2033 / size=1267 / kg=721

---

## ★ 次セッションでやること（優先度順）

### 1. 全コンボ再実行の結果確認（Phase B-α' 適用後）
- `python analysis/V2/methods/run_full_deepdive.py --workers 4`（約4時間）
- ログ: `analysis/V2/results/run_full_deepdive_YYYY-MM-DD.log`
- 確認 SQL:
  ```sql
  SELECT metric, horizon, COUNT(*), AVG(promise_break_rate), AVG(coverage)
  FROM combo_range_backtest WHERE n >= 30
  GROUP BY metric, horizon ORDER BY metric, horizon;
  ```
- 期待: size promise_break P50 53.0% → 大幅改善

### 2. Phase B-β（cnt min/max 独立予測復活）の Plan 策定
- 全コンボ再実行結果で着手判断
- size の実測幅ベース設計を cnt にも適用するか検討
- 撤回基準を先に確定（独立モデル化前例 04/13 撤回参照）

### 3. Phase C 実装（Phase B 後）
- 加重平均 composite_hit_rate（cnt 0.6 / size 0.3 / kg 0.1）
- kg NULL 率 70% → 実態は 0.667/0.333 に再正規化されるケース多

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
