# 公開準備ロードマップ T44〜T48 実行計画（段取り書）

- 作成: 2026-07-16（Fable設計・Sonnet×5調査。コードアンカー・数値は全て実読/実クエリで確認済み）
- 実行想定: Opus（別セッション）。本ファイルだけで着手できるよう自己完結で書く
- SoT: 実行結果・採否の記録は `90_決定ログ.md` に追記し、`.claude/memory/project_status.md` を更新すること
- ⚠️ 行番号は 2026-07-16 時点。**実装前に必ず現物で再確認**（コードが動けばズレる）

---

## 0. 背景と目的

「精度が低くて予測を公開できない」の実態は4つに分解された:

1. **公表KPIが本番と違う予測経路を測っている**（バックテスト=ratio上書き経路 / 本番 predict_count.py=直接モデル優先）
2. **バックテストがボウズ（cnt=0）を評価から除外**しており実運用より楽観的（ボウズ率 P50=16.9%）
3. **誤差はタイ五目（n加重wMAPE 73%・4コンボのみ）と回遊魚系に集中**。cnt の promise_break P50 は 6.4% で既に商品水準
4. **公開判定の単位が粗い**。「pb≤10% & BL2勝ち & n≥50」で絞ると **180コンボ（42魚種74船宿）が pb P50=2.73%** — 選別すれば今すぐ公開できる

→ T44〜T47 で「正しく測る → 落ちている精度を回収 → モデル強化 → 選別公開」の順に進め、T48（プール学習）は中期PoCとする。

## 1. 実行者（Opus）向け共通ルール

### 環境・実行
- **分析実行・DB生成は必ずメインrepo** `C:\Users\newsh\Desktop\kanto-fishing` で行う（worktreeでのデータ生成禁止 → [[feedback_worktree_data]]）。実行前に `git pull`
- 全魚種再実行: `python analysis/V2/methods/run_full_deepdive.py --workers 4 --reset-best`（約40分・59魚種）。**逐次ループ禁止**
- Bashで日本語を含むPython出力は必ず `open('out.txt','w',encoding='utf-8')` ファイル経由（[[feedback_bash_encoding]]）
- SQLite の列名・JSONキーは PRAGMA / 直接確認。エージェント要約を信用しない。ループ前に `print(f'対象: {len(x)}件 先頭3: {x[:3]}')`

### KPI・判定
- 各フェーズ開始前に `analysis/V2/analysis-improvement/_kpi_baseline_<phase>.json` としてスナップショット保存（既存の `_kpi_baseline_T32.json` / `_kpi_reanalysis_2026-06-23.json` と同形式）
- **撤回基準は同一定義1つに絞る**（[[feedback_plan_numerical_basis]]）。定義を変えた指標は旧データも新定義で再計算してから比較（[[feedback_definition_consistency]]）
- T33の教訓: 期待効果 -2pt 未満の統計改善には着手しない。複数改善は1回の全再実行にまとめる。前処理コスト（weather/cmems鮮度）を見積りに含める
- T34の教訓: 新規データソース追加は原則禁止（船宿ブログクロールで改善ゼロを実証済み）

### 鮮度前提（全再実行の前に確認）
- `ocean/rebuild_weather_cache.py --update`（増分モード・通常運用はこれ）で weather_cache を最新化
- cmems が2週間以上 stale なら `build_cmems.py` 更新を先に（6/23 に stale cmems で headline 悪化した実績）

### レビュー体制
- 各フェーズとも: 着手時に本書該当節を元に**短い実装プラン**（変更diff方針・撤回基準）を書き、**stat-reviewer / data-reviewer / code-reviewer の3並列レビュー**を通してから実装（[[feedback_analysis_team_review]]。E層を触る T47 は domain も追加）
- 完了時: 90_決定ログ.md 追記 + project_status.md 更新 + （E層に触れた場合）`python crawl/validate_output.py` errors=0

## 2. 現状KPI基準（2026-07-16 実測・H=0, n≥30, 402コンボ）

| 指標 | 値 |
|---|---|
| cnt_avg wMAPE P25/50/75/90 | 30.9 / 37.2 / 45.4 / 53.7 % |
| BL2勝率 | 96.3%（負け15件） |
| promise_break P50: cnt / composite / kg / size | 6.4 / 13.5 / 25.0 / 30.8 % |
| size pb 30-50%帯 | 123/235件 = 52.3% |
| bowzu_rate P25/50/75 | 4.8 / 16.9 / 24.9 % |
| ホライズン劣化 H0→28 | +0.6pt のみ |
| モデル化率 | 439 / 4,470 fish×shipペア = 9.8% |

⚠️ 上記 cnt 系のレンジKPIは「ratio上書き経路」の測定値であり、本番経路とは異なる（T44で解消）。

---

## 3. T44: 測り直し — 検証/本番経路の統一 + ボウズ込み評価

**目的**: KPIを「本番がユーザーに見せている予測」の精度にする。全後続フェーズの判定土台。

### 根拠（確認済みの不一致）
- バックテスト: `combo_deep_dive.py:3408-3419`（`section_backtest_rolling()` 内）で cnt_max/cnt_min の予測を「cnt_avg予測×旬別比率」で**無条件上書き**して評価
- 本番: `predict_count.py:1330-1379`（`predict_combo()`）は trip優先 → **combo直接モデル**（`_apply_wx_correction(metric='cnt_min'/'cnt_max')`、パラメータは `combo_deep_dive.py:4081-4121` で全データフィット→`save_wx_params()` 保存）→ ratioフォールバック
- ボウズ除外: `combo_deep_dive.py:1171`（`load_records()`）で `cnt_avg <= 0` を読込段階で除外。学習・評価とも一切含まれない

### 実装手順
1. **二重経路バックテスト**: CVテストループで cnt_max/cnt_min について、上書き前の直接モデル予測 `pred_direct` と上書き後の `pred_ratio` を両方保持。既存 `combo_range_backtest`（PK: fish,ship,metric,horizon）に **metric='cnt_direct' の行を追加**して direct 経路を記録（既存 metric='cnt'=ratio の定義は不変更 → 過去比較を壊さない。スキーマ変更不要）
2. **ボウズ込み評価**: `load_records()` に `keep_bouzu=False` 引数を追加し、ボウズ行を**評価専用**に別リストで取得（学習配列には入れない）。テスト月に属するボウズ行を評価に合流させ、metric='cnt_bz' として promise_break（actual=0 の日に pred_lo>0 なら break）・bouzu見逃し率・ボウズ込みwMAPE を記録
3. メインrepoで全再実行（40分）→ `_kpi_T44_truth.json` 保存: {ratio, direct, bz} × {pb P50, coverage avg, winkler avg, wMAPE P50}
4. **経路統一の判定**（同一定義: cnt promise_break P50、tiebreak は coverage→winkler）:
   - ratio勝ち → `predict_count.py:1353-1366` の combo直接モデル優先を外し ratio を正とする（本番変更・低リスク）
   - direct勝ち → バックテスト側の上書き（3410-3413）を撤去し direct を正とする。以後の公表KPIは metric='cnt_direct'
5. 90_決定ログ追記。**注意書き必須**: この統一でheadline KPIが動いても regression ではなく「初めて本当の値になった」

### 撤回基準・留意
- 撤回なし（測定の追加のみ）。ただし cnt_bz 実装が学習配列を汚染していないこと（train 側の n が変わらないこと）を data-reviewer で必ず確認
- trip優先経路（`predict_count.py:1340-1351`）は本フェーズでは測定対象外。既知の限界として決定ログに明記
- 見積: 実装1〜2h + 再実行40分 + 判定30分

---

## 4. T45: 回収 — ポイントモデルkey修正 + BL-1リーク解消 + fallback診断

**目的**: 「タダで落ちている精度」の回収と、KPIの楽観バイアス除去。

### 4a. ポイント別モデルのキー不一致修正（優秀モデルが永久不使用）
- **保存側**: `load_records()` が `combo_deep_dive.py:1263` で生の `point_place1` を格納 → `deep_dive_by_point()`（5222〜）が生値でグルーピング → `save_point_wx_params()`（定義4675）が `combo_point_wx_params.point` に**生値**で保存
- **推論側**: `predict_count.py:734 _predict_point()` は `combo_point_events.point_normalized`（`combo_deep_dive.py:4948` で `_strip_depth_suffix(_normalize_point_name(...))` 正規化済み）を返し、`predict_count.py:942` が `WHERE point=?` でその**正規化値**を検索 → 不一致で rows=0 → ポイントモデル不使用
- **修正方針**: 保存側で正規化（`deep_dive_by_point()` のグルーピングキーを `_strip_depth_suffix(_normalize_point_name(pt))` に統一）。表記ゆれ統合でポイントあたり n も増える副次効果。**combo_point 系5テーブル（stats/events/backtest/wx_params/…）すべて同じキーになることを確認**
- **検証**: 修正後、`combo_point_wx_params.point` と `combo_point_events.point_normalized` の JOIN 一致率が ~100% になるワンショットスクリプトで確認。シロギス×長崎屋（旧 wMAPE 19-21% のポイントモデル群）が実際に推論で使われることを predict_count のログで確認

### 4b. BL-1リーク解消（cnt_avg のみの非対称リーク）
- **現状**: `combo_deep_dive.py:3273-3276`（学習側α/β推定）と `3352-3353`（テスト評価）で、cnt_avg のみ base に `combo_decadal`（**テスト月を含む全期間**の旬別平均）を使用。他metricは `metric_decadal_m`（3086-3093・**train のみ**から計算）を使っており、cnt_avg だけ将来情報が混入
- **修正方針**: バックテスト内の cnt_avg base を train-only の `metric_decadal_m['cnt_avg']` に統一。**本番（predict_count.py）は全期間 decadal のままで正しい**（未来を予測する分にはリークでない）— 触らない
- **期待される影響**: 公表 wMAPE は**悪化方向に動く**（リーク除去の必然）。P50 +2pt 以内なら想定内として受容。+5pt 超なら実装ミスを疑い調査（撤回ではなくデバッグ）

### 4c. BL2負けコンボの fallback 診断・整備
- **重要な事前知識**: use_fallback に手動追加の仕組みは**存在しない**。`combo_wx_params._meta` 行の `use_fallback` 列に、自動判定（`combo_deep_dive.py:6219-6265`: ①BL-0より10pt悪 ②BL-2より5pt悪 ③OOS r<0.15）の結果が保存されるのみ。再実行のたびに再計算される
- **手順**:
  1. まず診断: BL2負け15件（付録A-1）の現在の `use_fallback` 値をクエリ。**差分+5pt超の8件は自動判定②で既に True のはず**。True なら本番は既にベースラインを出しており「BL2負け」はバックテスト表示上の問題 → T44 の「本番経路KPI」に fallback 反映（fallback コンボの実効wMAPE = BL2値として集計する `effective` 列/集計を導入）
  2. False のものがあれば自動判定がなぜ漏れたかを特定（条件のAND/OR・評価データの差）
  3. 恒久機構: `FORCE_FALLBACK: frozenset[(fish, ship)]` を combo_deep_dive.py に追加し自動判定と OR。初期値は診断の結果 False だった負けコンボのみ
- **因子0コンボ45件**（付録A-2・combo_meta基準）は診断のみ（タイムボックス30分）: BASE_FACTORS が常時採用のはずなのに0件の理由を特定して決定ログに記録。修正はしない（それらは実質ベースライン予測＝低リスク）

### まとめ実行
- 4a+4b+4c を**1回の全再実行に同梱**（40分）→ `_kpi_T45.json` → T44基準と同一定義比較
- 判定: 4a はポイントモデル保有コンボの wMAPE 改善で評価 / 4b は「悪化してよい」/ 4c は effective KPI の整備が成果物
- 見積: 実装3〜4h + 再実行40分 + 検証1h

---

## 5. T46: モデル強化 — Hurdle + log1p + recency加重（フラグ化・1回再実行同梱）

**目的**: ボウズ・外れ値・レジーム変化という3つの構造要因に対処。決定ログのバックログ上位3件を一括消化。

### 設計（全て独立フラグ・stdlibのみで実装）
C層も事実上標準ライブラリ縛り（numpy/pandas/sklearn の import は water_color_model.py の関数内ローカルのみ）。以下すべて math モジュールで書ける。

1. **log1p 学習**（`ENABLE_LOG1P`）: met値配列の構築点 `combo_deep_dive.py:3224 / 3235 / 4082 / 4087` で cnt系metricに `math.log1p()`、予測後 `math.expm1()` で復元。**保存パラメータ（met_mean/met_std）が対数空間になるため、`combo_wx_params._meta` にtransformマーカーを保存し `predict_count.py` 側 `_apply_wx_correction()` も対応させる**（本番と学習の空間不一致は即バグ。code-reviewer 重点確認事項）
2. **recency加重**（`RECENCY_HALFLIFE_M = None|12|18`）: 重み `w=0.5^(経過月/半減期)` を (a) `pearson()`（定義842-868）の重み付き版 (b) `mean_std()`（870-876） (c) α/β OLS ループ `3266-3306` (d) alpha_scale グリッドの `_wmape` 評価 `3318-3323` に適用
3. **Hurdle v1**（`ENABLE_HURDLE`）: T44 の keep_bouzu データを使い、コンボ×旬別ボウズ率（ベータ平滑・事前=コンボ全体率）を算出。`bouzu_p > θ`（θ初期値0.5）の日は pred_lo を 0 に落とす（レンジ下限の正直化）。気象条件付きロジスティックは v2 送り — v1 は頻度ベースで小さく入れる

### プロトコル（T33の教訓: 全再実行の固定コスト40-70分を無駄打ちしない）
1. 代表10コンボでアブレーション（wMAPE四分位から各2 + KAIYU 1 + イカ系1）: 8構成（フラグ2^3）を単魚種実行で比較
2. 勝ち構成のみ全再実行1回 → `_kpi_T46.json`
3. **採用基準（同一定義・T45比）**: ボウズ込み promise_break（cnt_bz）P50 **-2pt 以上改善** かつ ratio/direct 経路の cnt pb P50 悪化 +0.5pt 以内
4. 撤回はフラグ単位（全部Falseに戻すだけ。コード削除不要）

- 見積: 実装1日 + アブレーション2h + 再実行40分

---

## 6. T47: 選別公開 — 公開ティア + 回遊魚★一本化 + タイ五目除外

**目的**:「サイトを開けるか」を「どのコンボを開けるか」に変換し、実際に公開状態を作る。

### 6-0. 【必須の前提調査】E層データフローの解明
確認済みの事実: `crawler.py build_forecast_json()`（crawler.py:2009〜）は独自集計で forecast ページを作っており、**D層出力（`forecast_daily.json` / `predict_params.sqlite`）を一切読んでいない**。一方 crawl.yml は日次で `predict_daily.py` を実行し `forecast_daily.json` を出力している（predict_daily.py:161-178 は cnt_lo/hi と kaiyu_stars を両方出力）。
→ researcher に「forecast_daily.json の現在の消費者は誰か（どのHTMLに何が表示されているか）」を調査させてから配線設計をする。**ここが不明なまま実装に入らない**。

### 6-1. 公開ティア蒸留（`crawl/build_open_tier.py` 新設）
- 既存パターン踏襲: `crawl/build_fish_area_analysis.py`（analysis.sqlite→コミット可能JSON→crawler.py が読む・不変条件#50 と同型）
- 入力: analysis.sqlite（T46後の値・**T44で正とした経路の metric を使う**） / 出力: `normalize/open_tier.json`
- **Tier A 基準（初期値・案A）**: cnt promise_break ≤ 0.10 AND BL2勝ち AND n ≥ 50 → 現データで **180コンボ・42魚種・74船宿・pb P50 2.73%**（変種: 案B n≥30 → 230コンボ / 案C pb≤0.15 → 219コンボ。付録A-3）
- JSONフィールド: fish, ship, tier(A/star/none), pb, n, wmape, updated_at

### 6-2. 回遊魚の★一本化
- KAIYU 9魚種は combo_meta に41コンボ（promoted=25 / not=12 / 未評価4。付録A-5）
- 方針: **非昇格コンボはレンジを出さず★のみ**。predict_daily.py:161-178 で `kaiyu_stars` が非None のとき cnt_lo/hi を JSON から落とす + open_tier.json 上で tier='star'
- 昇格済み25コンボは通常のレンジ経路（既存動作どおり `predict_count.py:1201-1205` で is_kaiyu=False）

### 6-3. タイ五目の予測除外
- 4コンボのみ（庄治郎丸 n=1432 wMAPE 72.6 / ちがさき丸 657・75.8 / 大盛丸 170・87.5 / 大洗丸 64・30.8）。「五目」は魚種構成が便ごとに変わり単一数量予測の対象として構造的に不適
- open_tier で tier='none' 固定（実績表示のみ・予測非表示）。分析（ALL_FISH）からは外さない。※大洗丸(30.8%)だけ良好だが、魚種として一貫した扱いを優先

### 6-4. E層配線 + gatekeeper
- 6-0 の調査結果に基づき「レンジ表示は open_tier.json の tier=A のみ / KAIYU は★表示 / タイ五目は実績のみ」を配線
- **不変条件追加（#53 目安・番号は validate_output.py の現況で採番）**: 「公開HTMLで予測レンジを表示するコンボ ⊆ open_tier.json tier=A」+ open_tier.json の鮮度チェック。REGRESSION_PREVENTION.md 表 + 決定ログ更新をセットで
- 表示文言は domain レビュー必須（min〜max のみ・avg 禁止の絶対制約を再確認）。マネタイズ方針（2026-06-10: 当面無料公開・的中実績で集客）と整合させる
- 推奨同時実装: 「先週の予測 vs 実績」ページ（predict_log.jsonl 起点の前向き検証）。信頼構築と真の精度計測の一石二鳥。ただしスコープ超過なら別タスク化可

- 見積: 調査0.5日 + 蒸留スクリプト0.5日 + E層配線1日 + validate/レビュー0.5日

---

## 7. T48: 中期PoC — プール学習 + 分位点/conformal（要ユーザー判断ゲート）

**着手前にユーザー判断が2つ必要**（勝手に進めない）:
1. **外部ライブラリ解禁の可否**: C層は事実上stdlib縛り（前例: water_color_model.py の関数内ローカル import のみ）。LightGBM/numpy をローカル分析限定で解禁するか。CI（crawl.yml）は蒸留済み predict_params.sqlite を読むだけなので**Actionsへの影響はない**構成にできる
2. **T44〜T47 の結果を見てから**: 選別公開で目的（オープン）が達成されていれば T48 の優先度は下がる

### PoC設計（解禁された場合）
- 全コンボプール1モデル: fish/ship/area をカテゴリ特徴量に、既存の気象・潮汐・CMEMS因子 + 旬 + recency。leave-one-month-out は現行と同一定義
- 対象: 5魚種（アジ・マダイ・マルイカ・タチウオ・キハダマグロ = 良/中/悪/KAIYU 混成）+ **コールドスタート評価**: 現在モデル化されていない n=10〜29 のペア50件で pb を測る（モデル化率9.8%→拡大の実証）
- 分位点: pinball loss で P10/P90 直接学習 + conformal 較正（目標カバレッジ85%）→ promise_break を設計で保証する路線の検証
- **成功基準**: 共通コンボで wMAPE P50 -3pt 以上 or コールドスタート50件で pb≤15%。未達なら撤退し記録（T33/T34 と同じ規律）
- stdlib縛り継続の場合: GBDTは断念し、分位点回帰（pinball loss の勾配降下・純Python）のみ小規模PoC

---

## 8. 実行順序と依存関係

```
T44（測り直し）──→ T45（回収）──→ T46（モデル強化）──→ T47（選別公開）
                                                    └→ T48（PoC・ユーザー判断後）
```
- T44 が全ての判定土台（スキップ不可）。T45/T46 は各1回の全再実行に改善を同梱
- T47 は T46 を待たずとも T45 完了時点の数値で開始可能（並行可・ただし open_tier.json の再生成を T46 後に1回行う）

## 9. 付録A: 確定数値（2026-07-16 analysis.sqlite 実測）

### A-1. BL2負けコンボ全15件（cnt_avg, H=0, n≥30）
タチウオ×打木屋釣船店(39, +24.88) / キハダマグロ×ちがさき丸(48, +22.97) / アジ×深田家(32, +12.80) / カワハギ×深田家(80, +8.78) / カワハギ×長三朗丸(89, +8.49) / フグ×豊丸(46, +7.93) / キハダマグロ×翔太丸(57, +7.27) / マルイカ×長三朗丸(198, +5.88) / アマダイ×長三朗丸(74, +4.69) / キハダマグロ×はら丸(48, +3.65) / ムギイカ×はら丸(55, +1.49) / カツオ×博栄丸(32, +0.63) / マダイ×庄治郎丸(38, +0.42) / イシダイ×平作丸(76, +0.32) / マハタ×幸栄丸(37, +0.10)
※括弧は (n, model−BL2 wMAPE差pt)

### A-2. 採用因子0コンボ: 45件（定義: combo_meta 掲載かつ combo_wx_params の metric='cnt_avg' 非_meta行が0件）
上位: マダイ×つね丸(125) / オニカサゴ×三次郎丸(91) / マダイ×弁天丸(84) / マダイ×ことぶき丸(83) / マダコ×第二つれたか丸(83) / …（全リストは `_kpi` 集計スクリプトで再現可。マダイ系が12件と突出）
※注意: バックテスト対象402件との JOIN では9件になる。定義差（combo_meta 439 vs backtest n≥30 402）に留意

### A-3. 公開ティア試算（combo_range_backtest metric='cnt' × combo_backtest 結合・374件）

| 案 | 条件 | コンボ | 魚種 | 船宿 | pb P50 |
|---|---|---|---|---|---|
| A | pb≤0.10 ∧ BL2勝ち ∧ n≥50 | **180** | 42 | 74 | **2.73%** |
| B | 同上・n≥30 | 230 | 46 | 93 | 2.74% |
| C | pb≤0.15 ∧ BL2勝ち ∧ n≥50 | 219 | 43 | 88 | 3.59% |

### A-4. タイ五目: 4コンボ（§6-3 に記載）

### A-5. KAIYU 41コンボ内訳
promoted=25（カツオ7・キハダ6・ムギイカ4・カンパチ3・ワラサ3・サワラ2）/ not=12 / 未評価4（カツオ×信栄丸・キハダ×ちがさき丸・ワラサ×信栄丸・ワラサ×翔太丸）。ブリは combo_meta 該当0

## 10. 付録B: コードアンカー総覧（実装前に現物確認）

| 項目 | 位置 |
|---|---|
| ボウズ除外フィルタ | combo_deep_dive.py:1171（load_records） |
| ratio上書き（バックテスト） | combo_deep_dive.py:3408-3419 |
| min/max直接モデルの最終フィット | combo_deep_dive.py:4081-4121 → save_wx_params（定義4445） |
| combo_range_backtest 書込 | save_range_backtest（定義4713-4772・呼出6182）列: pb/over_expect/coverage/bowzu_rate/winkler/n/component_count |
| BL-1リーク（cnt_avgのみ） | combo_deep_dive.py:3273-3276（学習側）/ 3352-3353（評価側）。train-only側は metric_decadal_m 3086-3093 |
| ポイント保存キー（生値） | load_records 1263 → deep_dive_by_point 5222/5237 → save_point_wx_params 定義4675 |
| ポイント推論キー（正規化値） | predict_count.py:734 _predict_point / 942 _apply_point_wx_correction。正規化関数は combo_deep_dive.py:4948 |
| use_fallback 自動判定 | combo_deep_dive.py:6219-6265。読出: predict_count.py:392-402 |
| Pearson/mean_std/alphaグリッド | combo_deep_dive.py:842-868 / 870-876 / 3316-3327（_wmape 定義2685） |
| 配列構築点（log1p挿入候補） | combo_deep_dive.py:3224/3235/4082/4087 |
| OLS重み挿入候補（recency） | combo_deep_dive.py:3266-3306 |
| KAIYU判定・保存 | combo_deep_dive.py:6269-6277 → _meta行。分岐: predict_count.py:558-568 / 1201-1205 / 1386-1389 |
| 本番 min/max 優先順位 | predict_count.py:1330-1379（trip→combo直接→ratio） |
| D層→E層の断絶 | predict_daily.py:161-178 が forecast_daily.json 出力 / crawler.py build_forecast_json（2009〜）は未消費 |
| 蒸留パターン | crawl/build_fish_area_analysis.py（→normalize/*.json）/ analysis/V2/methods/build_predict_params.py（→predict_params.sqlite） |
