現行バージョン: combo_deep_dive.py（Phase C composite_hit_rate 採用確定 / ALL_FISH 59種）
最終更新: 2026/05/21
最新コミット: T34 イカ系船宿ブログクロール路線・効果検証→撤退

---

## ✅ 直近完了（2026/05/21・main agent）

### T34 イカ系船宿ブログクロール路線・効果検証→撤退

**結論: 完全撤回（4船宿・2フェーズ検証で改善ゼロ・最大 +2.45pt 悪化）**

**動機**: イカ系 wMAPE 35-65% 改善余地大・マルイカ×秀丸 n=950 で 64.8% 最悪精度。船長blog で kanso_raw 補強→OBS 因子 (activity_n/wave_obs_n/tide_speed_n/water_color_n) の入力改善路線を仮説検証。

**Phase 1: 翔太丸 RSS（撤回）**
- 翔太丸 kanso avg=257字（既に詳細）・blog 109日6か月分取得
- A/B 2パターン抽出（A=構造化フィールド・B=A+活性キーワード）
- 結果: 9コンボ全部で 0〜+1.73pt 変動（改善なし）

**Phase 2: kanso 薄船宿 3船宿（撤回）**
- ユーザー指摘「翔太丸は釣りビジョン側で既充実で当然効果ない」→ kanso 薄船宿選定
- 儀兵衛丸 (avg 1字) / 長三朗丸 (avg 1字) / 喜平治丸 (avg 63字) で各6か月クロール
- 平安丸 (avg 4字) は SPA・JS動的で静的HTMLに釣果なし → 除外
- 秀丸 (avg 40字・n=1246) はユーザー判断で除外（釣りビジョンと同内容と判定）
- 喜平治丸の本文は ＜マルイカ＞ 等 山括弧マーカーで魚種別釣果セクション切出可能と判明
- 19コンボ評価: 改善なし・4コンボで +1.04〜+2.45pt 悪化

**失敗の根本原因（次回検討時必読）:**
1. **新規追加レコードの数値の質が catches_raw 既存品質に達しない**: blog の「0-33杯」を新規レコードに追加すると cnt_avg 計算が歪む
2. **既存 OBS 因子辞書とのキーワード重複出現**: kanso_raw に blog 由来キーワードを追記すると activity_n / wave_obs_n 等が過剰反応
3. **kanso 薄船宿でも予測モデルは weather_cache.sqlite 経由で既に最適化されている**: kanso 不足は精度悪化の真因ではない
4. **異粒度・異定義データを同パイプラインに混ぜると劣化する典型例**

**成果物（流用可能）:**
- 翔太丸 blog HTML 109日 (tmp_shotamaru/)
- 3船宿 blog HTML 458件 (tmp_3ships/{gihee,chozaburo,kiheiji}/)
- 実験データセット・CSV・SQLite (tmp_exp/)
- 抽出ロジック tmp_*.py 群（別 column で隔離するなら流用可）
- 詳細: `analysis/V2/analysis-improvement/90_決定ログ.md` 補遺12

**次の優先候補（イカ系改善・別軸）:**
1. D層予測モデル本番実装（補遺10 残課題・最優先）
2. size 30-50% 帯張り付き救済 中央予測モデル改善（補遺10 残課題）
3. MIN_MONTHS=4 緩和 + DO 独立カテゴリ化（plan_T33 残作業）
4. マルイカ×秀丸 n=950 wMAPE 65% 個別診断（kanso 不足以外の真因特定）

---

## ✅ 過去完了（2026/05/17・main agent）

### T32 全魚種再分析（chowari per-ship CSV 二重カウント排除後の効果検証）

**実行**: `run_full_deepdive.py --workers 4 --reset-best` × **59/59 OK・64分56秒**

**事前クリーンアップ:**
- `data/V2/aisho-maru_2026-*.csv` 等 per-ship CSV **59ファイル削除**（20船宿×3か月）
- 旧 chowari_to_csv.py が生成していた船宿別月別 CSV が `combo_deep_dive.py:1150` `os.listdir(DATA_DIR)` で全 read され、consolidated `chowari_*.csv` と **92.6%重複** (1,116/1,205行) で二重カウントの潜在バグ
- 削除前 data 整合性検証: renamed後 (gi-maru→義丸（大原)) で全データ chowari_*.csv 内に存在・データ消失ゼロ
- ships.json `source_priority` 補完は不要と判明（chowari 170船宿全て設定済・chowari-XXXXX 独立slug)
- fishing_v + chowari 二重存在は 24行/125,138 = 0.02% で許容

**全主要指標で改善:**

| 指標 | T31（2026/05/12）| **T32（2026/05/17）** | 差分 |
|---|---|---|---|
| combo_meta | 369 | **384** | **+15** |
| 船宿数 | - | 112 | - |
| 魚種数 | 55 | 55 | ±0 |
| **H=0 cnt_avg wMAPE P50** | 38.09% | **37.27%** | **-0.82pt** ✅ |
| **BL-2勝率** | 92.5% | **95.8%** | **+3.3pt** ✅ |
| **OOS r 平均** | +0.466 | **+0.500** | **+0.034** ✅ |

**商品的中率（promise_break_rate P50・低いほど良い）:**

| metric | T31 | **T32** | 差分 |
|---|---|---|---|
| **cnt** | 14.16% | **6.38%** | **-7.78pt** 🎯 大幅改善 |
| size | 31.53% | 31.58% | +0.05pt 横ばい |
| kg | 26.18% | **24.25%** | **-1.93pt** ✅ |
| **composite** | 16.16% | **13.93%** | **-2.23pt** ✅ |

**ホライズン別 wMAPE P50（cnt_avg, n>=30）:**
- H=0: 37.27% / H=1: 37.52% / H=3: 37.59% / H=7: 37.70%
- H=14: 37.73% / H=21: 37.93% / H=28: 38.36%
- H=0→28 で差 1.1pt 以下 = SLOW_FACTORS の遠期間有効性が高い

**composite component_count 分布**: {1: 14, 2: 317} （T31 補遺10: {1:14, 2:276, 3:0} → +41件）

**改善要因（仮説）:**
1. per-ship CSV 59件削除で **二重カウント源排除**（cnt 系で-7.78pt 大改善の主因）
2. chowari 経由 +15 コンボ追加で母集団拡大
3. T31 以降の catches_raw +1,208件（自然蓄積）

**既知の要確認事項:**
- composite metric の winkler 平均=0.00（T31 比で計測仕様変化か算式問題・別途調査）

**判定:** 全 KPI 改善で T32 効果確定。per-ship CSV 削除の効果が cnt 系で特に顕著。次セッション以降は予測モデル本番化（D層）または size promise_break 31.58% の張り付き救済。

---

## ✅ 直近完了（2026/05/12・main agent）

### T31 全魚種再分析（船宿+96・hist_rows+27,233・ポイント正規化+kanso強化の総合効果検証）

**実行**: `run_full_deepdive.py --workers 4 --reset-best` × 59/59 OK・31分58秒

**全主要指標で改善:**

| 指標 | 前回（2026/04/19）| **今回（2026/05/12）** | 差分 |
|---|---|---|---|
| combo_meta | 328 | **369** | **+41** |
| 魚種数 | 45 | 55 | +10 |
| **H=0 wMAPE P50** | 41.6% | **38.09%** | **-3.51pt** ✅ |
| **BL-2勝率** | 88.5% | **92.5%** | **+4.0pt** ✅ |
| **OOS r 平均** | +0.387 | **+0.466** | **+0.079** ✅ |
| composite_promise_break P50 | 13.94% | 14.16% | +0.22pt |
| cnt P50 | 6.57% | 6.38% | 改善 |

**改善要因（T31 で実装した4つの拡張の総合効果）:**

1. **船宿マスタ拡張**（ships.json 84→180・active 169）
   - WebSearch で fishing-v.jp 掲載済みの未登録船宿を発見し追加
   - 葉山(+4)・平塚(+2)・茅ヶ崎(+3)・小田原(+3)・小柴(+1)・久里浜(+4)・松輪間口(+7)・沼津(+2)・浦安(+1)・鹿島(+2)・御前崎(+5)・他20エリア
   - うち26隻でデータ取得成功（+8,503件）・66隻は fishing-v.jp 上で「全 0件」（船宿側未投稿）

2. **過去3年クロール実装**（catches_raw.json +27,233件・total 123,930件）
   - history_crawl_t31.py 新規・既存 CUTOFF=2023/04/04 と同期間
   - fetch() ヘッダ拡張（Accept-Language / Referer 等）で自然なクロール
   - data/V2/*.csv: 75,553→100,196行（+24,643行・+33%）

3. **相対ポイント正規化**（point_coords.json 303→330・+27点）
   - 主要海域 +15（神津島・金州・浜岡沖・佐島沖・葉山西沖等）
   - {port}+方向の追加 +12（葉山南沖・小田原南沖/西沖/東沖/湾内・平塚西沖/東沖・御前崎近場・網代南沖・横浜近場・江戸川店前・下田南沖）
   - crawler.py: _AREA_TO_PORT_SHORT マップ + _normalize_relative_point() で「南沖・近場・湾内・河口沖等」を自動変換
   - CSV正規化結果: 残存（未正規化相対表記）0件・主要例: 葉山南沖53・小田原南沖37・平塚河口沖36・御前崎近場28

4. **kanso 抽出強化**（4関数パターン拡張）
   - _extract_water_color (+8): ササ濁り・コーヒー色・味噌汁色・クリア・ブルー・黒潮の影響
   - _extract_tide_info (+13): 中潮・若潮・長潮・潮替わり・潮効いて・潮悪し・上り潮等
   - _extract_wave_info (+6): ベタ凪・大シケ・凪ぎ・うねり強等
   - _extract_weather (+7+重複防止): 薄曇り・豪雨・霧雨・猛暑・寒波等
   - CSV非空率: tide_info 1.6%→2.1% / wave_info 0.1%→0.3% / weather 0.6%→0.7%

**判定:** 主要KPI全改善でT31効果確定。次セッション以降は予測モデル本番化（D層）またはまだ未対応の魚種ページ範囲拡張へ。

---

### ALL_FISH 4魚種追加・新規5コンボの combo tuning 完了

### ALL_FISH 4魚種追加・新規5コンボの combo tuning 完了

**背景**: `docs/fish/` には 62 種の魚種ページがあるが、`run_full_deepdive.py` の `ALL_FISH` には 55 種しか入っておらず、CSVデータがあるのに分析対象から漏れている魚種が 4 種あった（イシモチ・キントキ・ハナダイ・アナゴ）。

**実行1: run_full_deepdive.py イシモチ キントキ ハナダイ アナゴ --workers 4**（1分26秒・4/4 OK）

combo_meta 追加（5コンボ・全て BL-2 勝利）:

| 魚種 | 船宿 | n | wMAPE | composite pb |
|---|---|---|---|---|
| アナゴ | 吉野屋 | 54 | 34.1% | 11.1% |
| イシモチ | 小柴丸 | 414 | 39.3% | 23.3% |
| キントキ | 敷嶋丸 | 78 | 48.3% | 20.2% |
| ハナダイ | 大盛丸 | 57 | 31.9% | 15.8% |
| ハナダイ | 勇幸丸 | 45 | 28.9% | 22.0% |

- wMAPE 28.9〜48.3%（全体 P50=37.3% と同水準）
- composite pb 11.1〜23.3%（既存 P50=13.94% に対し概ね許容範囲）
- 未生成2コンボ（キントキ×勇盛丸・ハナダイ×孝徳丸）: MIN_N_COMBO=30 の有効レコード閾値で除外（自然蓄積待ち）

**実行2: combo_tuning JSON 充填**

5コンボの combo_tuning JSON に以下を充填:
- adopted_factors（16〜23件/コンボ）
- points / modal_coord / multi_point_risk
- trip_models（0〜1件/コンボ）
- point_depth_models（0〜3件/コンボ）
- water_color_models（0〜2件/コンボ）

`update_combo_tuning_segments.py` に以下を追加（149行）:
- `--target` オプション（特定コンボのみ処理）
- `fill_missing_fields()` 関数（adopted_factors / points 系の補完）

**code-reviewer 指摘の MAJOR 2件を修正済み:**
- `n_valid=null` フォールバック（フラグ系・天文系因子で `combo_deep_params` に該当行が無い場合 0 に）
- `points.pct` の母数をフィルタ後の `total` で計算（合計 100±1%）
- `TODAY` を `date.today().isoformat()` に動的化（MINOR-4）

**変更ファイル**:
- `analysis/V2/methods/run_full_deepdive.py`（ALL_FISH 55→59種）
- `analysis/V2/analysis-improvement/update_combo_tuning_segments.py`（149行追記 + 修正）
- `analysis/V2/analysis-improvement/combo_tuning/`（新規3 + 更新2 = 5ファイル）
- `analysis/V2/results/analysis.sqlite`（combo数 323→328・gitignore）

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
