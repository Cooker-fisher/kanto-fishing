# 「商品的中率」KPI 実装 Plan（2026-05-08）

作成: analyst
ステータス: Plan 作成完了・3並列レビュー待ち（Phase B は必須）

---

## 背景・意思決定の根拠

`90_決定ログ.md` §「2026/05/08 後半」確定事項より:

- 主指標: **1 − promise_break_rate（"期待を下回らなかった率"・平均 87.4%）**
- 防御策3点セット（①pred_lo下限・②区間幅上限・③bowzu_rate併記）
- 評価軸: min/max 独立予測に戻す（04/13 ratio 法撤回）
- size/kg: 加重平均 cnt:0.6 / size:0.3 / kg:0.1

### ⚠ 出力形式の絶対制約（2026/05/08 補遺2 で明記）

**出力は「単一レンジ + 中央値」の3値のみ。重ねレンジ禁止。**

| 要素 | 出力形式 | 禁止例 |
|---|---|---|
| 数 | `min匹 〜 max匹、avg匹`（3値・レンジ1つ）| `min: A匹〜B匹` のように pred_lo/pred_hi 各々に区間予測をつけない |
| 型 | `min cm 〜 max cm、avg cm`（3値・レンジ1つ）| 同上 |
| 重 | `min kg 〜 max kg、avg kg`（3値・レンジ1つ）| 同上 |

**「min/max 独立予測」が指す範囲（誤解防止のため厳密に定義）:**

- 内部学習: cnt_min と cnt_max を**別々の回帰モデル**で学習（独立）
- 内部出力: 各モデルから**点予測値1つ**を取得（cnt_min_pred = 単一スカラー / cnt_max_pred = 単一スカラー）
- ユーザー表示: `cnt_min_pred 〜 cnt_max_pred` の**1本のレンジ**として提示
- 中央値: avg（cnt_avg モデルの点予測値1つ）

**実装で禁止する事項:**

1. cnt_min に予測区間（confidence interval / prediction interval）を被せて `[lo_of_lo, hi_of_lo]` を出力する
2. cnt_max に同様の予測区間を被せて `[lo_of_hi, hi_of_hi]` を出力する
3. レンジを階層化する（meta-interval）
4. min と max を別々のレンジ・別カードで表示する

参照: CLAUDE.md「予測の出力形式: 数要素　min匹～max匹、ave匹、型要素（cm kgはデータ次第）min cm～max cm、ave cm、minkg～maxkg、avekg」

### 04/13 ratio 法の撤回経緯

04/13 実装当時の判断:
- actual_cnt_avg ↔ actual_cnt_max の相関 r=0.976
- ratio（cnt_max/cnt_avg）の旬別 CV=0.18 で安定
- 独立モデル(cnt_min)の BL-2 勝率が 51.9% と低く「独立予測は BL-2 に負ける」と判断
- → ratio 法採用 / 独立モデル廃止

撤回理由（2026/05/08確定）:
- 04/11 設計「pred_hi = cnt_max モデル出力 vs actual_max」が現実装（actual_avg ベースの range_backtest）と 3層で不整合
- ratio 法では pred_lo が独立した根拠を持たない → ゲーム化（pred_lo=0 で promise_break=0）が容易
- 防御策①②で当時の BL-2負け懸念を吸収できる

---

## 現状データ確認（実 SQLite クエリ結果）

### combo_range_backtest（2348行）

```
列: fish, ship, horizon, promise_break_rate, over_expect_rate, coverage, bowzu_rate, winkler, n, updated_at
metric 列: なし（現在は cnt のみ・1メトリック固定）
H=0 件数: 335 コンボ（n>=30 フィルタ後）
```

promise_break_rate の実分布（H=0, n>=30, 335コンボ）:
- 平均: 12.6%（= "期待を下回らなかった率" 87.4%）
- P25: 2.0% / P50: 7.5% / P75: 16.8%
- 最悪: クロダイ×山本釣船店 84.8% / シイラ×共栄丸 70.7%

### combo_backtest（現状の metric 別 wMAPE・BL2勝率）

| metric   | H=0 avg wMAPE | コンボ数 | BL-2 勝率 |
|----------|--------------|---------|----------|
| cnt_avg  | （ゼロ除算爆発あり）| 319 | 97.2% |
| cnt_max  | （同上）       | 319    | 92.2%   |
| cnt_min  | （同上）       | 318    | **51.9%** |
| size_avg | 145%（正常域4件）| 201   | 44.8%   |
| kg_avg   | 高値          | 120    | 40.8%   |

⚠ wMAPE の avg が爆発しているのはゼロ除算。中央値で評価すること。cnt_min の BL-2 勝率 51.9% が 04/13 撤回の元凶。

### CSV NULL 率（data/V2/ 93,147行）

| 列       | NULL 率  | 備考 |
|---------|---------|-----|
| cnt_min | 41.6%   | ゼロ含む。実データに空欄が多い |
| cnt_max | 12.0%   | ゼロ含む |
| size_min| 44.1%   | NULL |
| kg_min  | 71.3%   | NULL（kg は非常に少ない） |

### combo_decadal での avg_cnt_min/max 比率（5,413 旬×コンボ）

cnt_min/cnt_avg 比率の分布:
- P10: 0.121 / P25: 0.211 / P50: 0.337 / P75: 0.462 / P90: 0.561

cnt_max/cnt_avg 比率の分布:
- P10: 1.462 / P25: 1.582 / P50: 1.752 / P75: 1.941 / P90: 2.140

→ 防御策①の下限比率 0.3 は P50 付近（中央値）と合致。
→ 防御策②の上限倍率 1.5 は cnt_max/cnt_avg P10=1.462 と近い（最小幅相当）。

### combo_wx_params の metric 別登録状況

| metric   | 登録コンボ数 | 登録因子数 |
|---------|-----------|---------|
| cnt_avg | 312        | 6,170   |
| cnt_max | 319        | 6,278   |
| cnt_min | 318        | 5,770   |
| size_avg| 204        | 4,070   |
| kg_avg  | 136        | 2,629   |

→ cnt_min / cnt_max はモデルパラメータが既存（全 318/319 コンボ）。  
→ predict_count.py の `_apply_wx_correction(metric='cnt_min')` ルートは既に整備済み。  
→ ratio 法の override（L3287-3290）を削除すれば独立予測に復帰する。

---

## 実装順序の根拠

**Phase A（size/kg range_backtest 拡張）先行の理由**:
- Phase B（min/max 独立予測）は combo_deep_dive.py と predict_count.py の変更を伴い、再分析（全コンボ 4時間）が必要
- Phase A は集計ロジックの追加のみ。影響テーブルが限定的でロールバックが容易
- Phase A のデータ（size/kg の実 NULL 率・distribution）が Phase B の防御策数値検証に必要
- Phase C は Phase A・B 完了後に合算する集計のみ

---

## Phase A: size/kg のレンジ評価整備

### A-1. combo_range_backtest 現状と拡張手順

**現状**: combo_range_backtest は `cnt_min/cnt_max/cnt_avg` の 3 指標のみを使用。
`_range_by_key[H][key][met]` に `size_min/size_max/size_avg` / `kg_min/kg_max/kg_avg` を
同様に格納し、size 版・kg 版の promise_break / over_expect / coverage / bowzu_rate / winkler を計算する。

**code で変更する箇所（行番号ベース）**:

1. `combo_deep_dive.py` L3316〜3320（`_range_by_key` への格納条件）:
   ```python
   # 現在: cnt_max / cnt_min / cnt_avg のみ
   if met in ("cnt_max", "cnt_min", "cnt_avg"):
       _range_by_key[H][_rk][met] = (pred, act)
   # 変更後: size / kg も追加
   if met in ("cnt_max", "cnt_min", "cnt_avg",
               "size_min", "size_max", "size_avg",
               "kg_min", "kg_max", "kg_avg"):
       _range_by_key[H][_rk][met] = (pred, act)
   ```

2. L3466〜3502（`range_bt_data` 生成ループ）:
   - 現在は `"cnt_max" in d and "cnt_min" in d and "cnt_avg" in d` を条件に cnt のみ集計
   - metric_group = [("cnt", "cnt_max", "cnt_min", "cnt_avg"), ("size", ..."), ("kg", "...")] でループ化

3. `save_range_backtest()`（L4261〜4310）:
   - スキーマに `metric TEXT` 列を追加（下記 A-2 スキーマ案参照）
   - INSERT を `(fish, ship, metric, horizon, ...)` に変更

4. `section_backtest_range()` の bowzu_threshold 計算（L3454〜3457）:
   - cnt 版はそのまま。size/kg は bowzu_threshold = None（ボウズ概念が cnt にのみ適用）

### A-2. スキーマ変更案

**案 1: metric 列追加**（推奨）

```sql
CREATE TABLE combo_range_backtest (
    fish               TEXT,
    ship               TEXT,
    metric             TEXT,   -- 追加: "cnt" / "size" / "kg"
    horizon            INTEGER,
    promise_break_rate REAL,
    over_expect_rate   REAL,
    coverage           REAL,
    bowzu_rate         REAL,
    winkler            REAL,
    n                  INTEGER,
    updated_at         TEXT,
    PRIMARY KEY (fish, ship, metric, horizon)
);
```

既存データは `metric="cnt"` として保持。

メリット: 1テーブルで全メトリックを横断クエリできる。Promise_break の composite 集計が JOIN なし  
デメリット: 既存 `(fish, ship, horizon)` で参照しているコードを `(fish, ship, "cnt", horizon)` に修正が必要

**案 2: 別テーブル化**（`combo_range_backtest_size` / `combo_range_backtest_kg`）

メリット: 既存コードへの影響ゼロ  
デメリット: Phase C の composite_hit_rate 計算で 3テーブル JOIN が必要。管理コスト増

**推奨: 案 1（metric 列追加）**。  
predict_count.py が combo_range_backtest を参照しているか確認が必要（下記不明点参照）。

### A-3. 所要時間見積もり

combo_range_backtest の書き込みは `save_range_backtest()` 内で全コンボ一括保存。
重い処理は `section_backtest_rolling()` 全体（現状 4時間）。Phase A 単独では:
- combo_deep_dive.py の range_backtest 集計ロジックのみ変更
- 全コンボ再実行は必要（size/kg の _range_by_key を再生成するため）
- 所要: **4時間程度**（全55魚種 workers=4）

ただし size の NULL 率 44% / kg の NULL 率 71% のため、有効コンボ数は cnt より少ない。
事前確認: `SELECT COUNT(DISTINCT fish||ship) FROM combo_backtest WHERE horizon=0 AND metric='size_avg'` → 201 コンボ

### A-4. 影響テーブル

| テーブル | 変更内容 |
|---------|---------|
| combo_range_backtest | metric 列追加・行数増（2,348 × 3メトリック化で最大 7,044 行） |
| combo_range_backtest（既存参照） | PRIMARY KEY 変更により参照クエリの修正が必要 |

combo_range_backtest を参照しているファイル（要確認）:
- `combo_deep_dive.py` `save_range_backtest()`
- `predict_count.py` (`_get_range_backtest()` 等があれば)
- `crawler.py` の forecast HTML 生成部分

---

## Phase B: min/max 独立予測復活 + 防御策（3並列レビュー必須）

### B-1. combo_deep_dive.py の変更箇所

**削除対象**: L3285〜3290（ratio-based override）

```python
# 現在（削除予定）:
if met in ("cnt_max", "cnt_min"):
    _ap = avg_pred_store[H].get(r["date"])
    _ratio = decadal_ratio_m[met].get(dn, global_ratio_m[met])
    pred = (_ap if _ap is not None else base) * _ratio
```

これを削除すると、cnt_min / cnt_max は `_apply_wx_correction(metric='cnt_min'/'cnt_max')` で
独立学習されたパラメータ（combo_wx_params に登録済み）を使った独立予測に自動的に戻る。

**削除に伴い不要になるコード**:
- L2972〜2984: `decadal_ratio_m` / `global_ratio_m` の初期化（cnt_max ratio 計算）
- L2939: `# ratio-based予測` コメント
- L2935: `# range_backtest 用: cnt_max/cnt_min の (pred, act) を日付キーで保存` コメント（修正）

**avg_pred_store の継続使用**:
- `avg_pred_store[H]` は size_avg の cnt→size slope 補正（L3282〜3284）で引き続き必要
- cnt_min / cnt_max 向けの ratio 利用のみを削除。size 向けは残す

### B-2. predict_count.py の変更箇所

`predict_count.py` L1296〜1333（min/max 予測）の現在の挙動:

```
現在:
1. lat/lon あり + use_fb=False → _apply_wx_correction(metric='cnt_min') で直接予測 → cnt_lo
2. フォールバック → ratio 法 (avg_cnt_min / avg_cnt) × cnt_predicted

変更後:
- 上記の「1」を採用する（既に実装済み）
- フォールバック（ratio 法）は avg_cnt_min が存在する場合のみ適用のままでよい
- 防御策①②をここに追加（B-3 参照）
```

**追加変更点（防御策）**:

L1315 の `cnt_lo =` 計算後に防御策①を適用:
```python
# 防御策①: pred_lo 下限制約
floor_lo = avg_cnt * GUARD_LO_RATIO   # GUARD_LO_RATIO = 0.3 (仮)
cnt_lo = max(cnt_lo, floor_lo)
```

L1316 の `cnt_hi =` 計算後に防御策②を適用:
```python
# 防御策②: 区間幅上限制約
max_width = avg_cnt * GUARD_WIDTH_MAX  # GUARD_WIDTH_MAX = 1.5 (仮)
cnt_hi = min(cnt_hi, cnt_lo + max_width)
```

**size / kg の size_lo / size_hi 計算（L1353〜1357）**:
現状は `avg_size ± size_mae` の対称区間。Phase B では:
- size_lo = size_avg_model - size_mae（size_avg の独立モデルがある場合）
- size_hi = size_avg_model + size_mae
- 今回は size_min / size_max の独立モデルは作成しない（kg_avg も同様）
- → Phase A で size/kg range_backtest の実態を確認してから Phase C で判断

### B-3. 防御策数値根拠（シミュレーション計画）

**現在の問題**: 独立予測復活により cnt_min モデルが 0 を出力するリスクがある（BL-2 勝率 51.9%）

**シミュレーション対象データ**:
`combo_decadal` の `avg_cnt_min / avg_cnt` 比率（n=5,413）から防御策①の比率候補を評価。

#### 防御策①（pred_lo 下限）シミュレーション計画

候補比率: 0.3 / 0.5 / 0.7

**評価指標**:
- promise_break_rate（実データの actual_avg に対して、各 floor を適用した後の違反率）
- 区間幅の拡大率（floor によって cnt_lo が切り上げられた割合）
- ゲーム化耐性（cnt_lo が floor 以下になったコンボ数）

**根拠データ（実測値 recap）**:
- avg_cnt_min/avg_cnt の P50 = 0.337 → 0.3 は中央値をやや下回る水準（50% のコンボは floor 発動しない）
- 0.5 は P71 付近 → 約 29% のコンボで floor 発動（過剰か）
- 0.7 は P88 付近 → 約 88% のコンボで floor 発動（ゲーム化防止より区間狭窄が深刻）

**推奨候補: 0.3**（P50 水準。過半数のコンボでは floor 不発動。ゲーム化防止に必要最低限）

シミュレーション実施方法:
```python
import sqlite3
db = sqlite3.connect('analysis/V2/results/analysis.sqlite')
# combo_decadal で avg_cnt_min が baseline*ratio を下回るコンボ数
for ratio in [0.3, 0.5, 0.7]:
    cur.execute('''
        SELECT COUNT(*), AVG(CASE WHEN avg_cnt_min < avg_cnt*? THEN 1 ELSE 0 END)
        FROM combo_decadal WHERE avg_cnt IS NOT NULL AND avg_cnt_min IS NOT NULL''', (ratio,))
    print(ratio, cur.fetchone())
```

→ **実装前に必ずこのシミュレーションを実行し、比率を確定してから実装に入ること**

#### 防御策②（区間幅上限）シミュレーション計画

候補倍率: 1.0 / 1.5 / 2.0（baseline × 倍率が区間幅の上限）

**根拠データ（実測値 recap）**:
- cnt_max/cnt_avg の P10 = 1.462（幅下限の実態）
- 1.0 倍制限: 区間幅を avg_cnt 以内に制限。全コンボの 90%+ で発動 → 過度に狭窄
- 1.5 倍制限: P10 付近。発動は最上位ばらつきのみ
- 2.0 倍制限: P90 = 2.140 付近。ほぼ発動しない（上限として機能しない）

**推奨候補: 1.5**（P10=1.462 と近似。実態のレンジを尊重しつつ非現実的な幅を防ぐ）

**winkler スコアとのトレードオフ**:
- 現状 winkler 平均 17.7（H=0）。区間幅を狭めると約束割れは増えるが winkler は下がる
- 防御策②は over_expect_rate（31.8%）との兼ね合いで決める

#### 防御策③（bowzu_rate 併記）

実装変更なし。combo_range_backtest の `bowzu_rate` 列は既存。表示層での併記設計は Phase C 後。

### B-4. 過去 04/13 棄却理由との差異

**当時の棄却理由**:
「cnt_min の独立モデルが BL-2 勝率 51.9% で、ratio 法（BL-2 勝率 92.2%）に大きく劣る」

**今回との差異**:

1. **KPI の変更**: 04/13 は wMAPE / BL-2 勝率を直接最適化していた。今回は promise_break_rate が主指標。wMAPE が高くても pred_lo が適切ならば promise_break_rate は下がる
2. **防御策①②の追加**: cnt_lo の下限制約により、独立モデルが 0 を出力してもクリップされる → promise_break_rate の悪化を吸収
3. **評価軸の整合**: ratio 法では pred_lo が "cnt_avg × ratio" であり actual_min と比較されていない。独立予測に戻すことで pred_lo ↔ actual_min の比較が意味を持つ
4. **既存パラメータの再利用**: combo_wx_params に cnt_min（318コンボ）/ cnt_max（319コンボ）のパラメータが既存。ratio 法は学習結果を捨てていた

**残存リスク**: cnt_min の BL-2 勝率 51.9% は ratio 法削除後も変わらない。防御策①②の数値次第で promise_break_rate が悪化するシナリオがある。→ 実データシミュレーションで定量評価必須

### B-5. リスク評価: H=0 wMAPE への影響見積もり

現状（ratio法・cnt_avg 基準）:
- H=0 wMAPE P50: 39.4%（cnt_avg）

ratio 法削除後の見込み:
- cnt_avg は変化なし（ratio 削除は cnt_min / cnt_max のみに影響）
- cnt_min wMAPE: 現状 avg 69%（ゼロ除算爆発含む）。独立予測に戻しても大きな変化はない（既に独立モデルのパラメータで動いている部分が多い）
- combo_range_backtest の promise_break_rate 変化: 現在 avg 12.6% → 防御策①適用後は維持〜微増の見込み

**重要**: wMAPE の悪化より promise_break_rate の変化を主指標として評価する。

### B-6. データ要件確認（実測値）

cnt_min / cnt_max のデータ有無:
- CSV NULL 率: cnt_min 41.6% / cnt_max 12.0%（ゼロ含む）
- combo_decadal に avg_cnt_min 非 NULL: 5,413 / 8,104 旬（66.8%）
- combo_wx_params に cnt_min: 318 コンボ（全 combo_meta の 98%+）

→ cnt_min は 41.6% NULL だが、それでも combo_wx_params に 318 コンボの独立パラメータが存在。NULL 行は学習から除外されてパラメータ生成されているため、予測時は非 NULL 行で学習したモデルを全コンボに適用する形になる。問題なし。

---

## Phase C: 加重平均 composite_hit_rate

### C-1. 計算式

```
composite = 0.6 × is_cnt_in_range + 0.3 × is_size_in_range + 0.1 × is_kg_in_range
```

各フラグ:
- `is_cnt_in_range`: actual_avg ∈ [pred_lo, pred_hi] → 1, else 0
- `is_size_in_range`: actual_size ∈ [size_lo, size_hi] → 1, else 0（size NULL なら欠損）
- `is_kg_in_range`: actual_kg ∈ [kg_lo, kg_hi] → 1, else 0（kg NULL なら欠損）

ただし現状の range_backtest では actual_size / actual_kg を予測値と比較するロジックが未実装。
Phase A で size/kg の range_backtest を整備した後に Phase C を実装する。

### C-2. cm/kg 欠損時の重み再正規化

| 利用可能指標 | 重み合計 | composite 計算式 |
|------------|---------|----------------|
| cnt のみ | 0.6 | `composite = is_cnt_in_range`（= coverage と同じ）|
| cnt + size | 0.9 | `composite = (0.6 × is_cnt + 0.3 × is_size) / 0.9` |
| cnt + kg | 0.7 | `composite = (0.6 × is_cnt + 0.1 × is_kg) / 0.7` |
| 全揃い | 1.0 | `composite = 0.6 × is_cnt + 0.3 × is_size + 0.1 × is_kg` |

kg の NULL 率が 71.3% と高いため、実運用では cnt + size（0.9 正規化）がほとんどのケースを占める見込み。

### C-3. combo_range_backtest への列追加

Phase A で metric 列を追加した後、composite_hit_rate を集計する専用列として追加:

```sql
ALTER TABLE combo_range_backtest ADD COLUMN composite_hit_rate REAL;
```

もしくは metric='composite' として計算済み値を格納する行を追加。

### C-4. 重み (0.6/0.3/0.1) の固定か検証か

**推奨: 固定値で開始**。

根拠:
- kg の NULL 率 71.3% のため、コンボ間で有効重みが変わり重み最適化が困難
- stat-reviewer の「3指標一体メッセージ化は時期尚早」警告は防御策で吸収したが、
  重み自体を変動させると重み選択バイアスが生じる
- 重み変更は Phase A・B の実装後に実態を見て次セッションで判断する

---

## 共通要件

### 不明点リスト（実装前に解消が必要）

**🟢 不明点 1〜5 は 2026/05/08 補遺セッションで実データ解消済み。残は #6 のみ（Phase B シミュレーション時に決定）。詳細は 90_決定ログ.md「2026/05/08 補遺」セクション参照。**

| # | 不明点 | 解消結果（採用値） | ステータス |
|---|--------|------------------|----------|
| 1 | combo_range_backtest の caller | predict_count.py / crawler.py から参照なし（grep 0 件）→ スキーマ変更は安全 | ✅ 解消 |
| 2 | baseline 定義 | **combo_decadal.avg_cnt（旬別・8104 行・既存）** を採用。予測値依存にすると循環するため | ✅ 解消 |
| 3 | size の比較対象 | **size_lo ↔ actual_size_min, size_hi ↔ actual_size_max** を採用。04/11 設計のアナロジー + domain「思ったより小さい=外れ」体感 | ✅ 解消 |
| 4 | size/kg 有効コンボ数 (H=0, n≥30) | size_avg: 193 コンボ・kg_avg: 110 コンボ。**MIN_N=30 で評価可能**。NULL 率は size 38.8% / kg 70.2% | ✅ 解消 |
| 5 | 防御策① floor の分母 | **pred_lo ≥ combo_decadal.avg_cnt × 0.3** を採用。旬別 avg_cnt の方が安定 | ✅ 解消 |
| 6 | 防御策②の `max_width = avg_cnt × 1.5` は winkler と整合するか | Phase B シミュレーションで定量評価 | 🟡 保留（Phase B 実装時） |

### リスク評価: 過去設計の罠を再度踏むパターン

| パターン | 過去発生 | 対策 |
|---------|---------|------|
| ratio 法に戻す誘惑（BL-2 勝率が落ちた場合）| 04/09 → 04/13 で ratio 法採用 → 今回撤回 | promise_break_rate を主 KPI に固定。BL-2 勝率で判断しない |
| 防御策の数値をゆるめて promise_break=0 を達成 | 今回初 | stat-reviewer が「ゲーム化リスク」と警告済み。3並列レビューで検証 |
| size/kg の range_backtest で NULL 率高くコンボ数激減し「意味がない」と判断する誤り | なし | NULL 率が高くても有効コンボ内での評価として意味あり。N 閾値を下げる |
| combo_range_backtest スキーマ変更で crawler.py の forecast 表示が壊れる | 05/01 HTML regression | Phase A 前に caller 確認（不明点 #1）。validate_output.py を実行 |
| cnt_min wMAPE の爆発（ゼロ除算）を wMAPE ではなく promise_break_rate で評価し忘れる | 04/13 の BL-2 勝率依存 | 評価指標を promise_break_rate に明示的に切り替え |

### 実装順序

```
Phase A-1: caller 確認（grep）
Phase A-2: スキーマ変更（metric 列追加）
Phase A-3: combo_deep_dive.py range_backtest 拡張
Phase A-4: 全コンボ再実行（4時間）
Phase A-5: 結果確認（size/kg の promise_break 実態把握）

Phase B-1: 防御策①②のシミュレーション（実データ確認）→ 数値確定
Phase B-2: 3並列レビュー（stat-reviewer / data-reviewer / domain）
Phase B-3: combo_deep_dive.py ratio override 削除
Phase B-4: predict_count.py 防御策追加
Phase B-5: 全コンボ再実行（4時間）・promise_break_rate 変化確認

Phase C-1: composite_hit_rate 集計ロジック追加
Phase C-2: combo_range_backtest 列追加 / 計算
```

---

## 各 Phase で 3並列レビューに見てもらう内容

### Phase A（軽量・必須ではないが推奨）

- **data-reviewer**: size_min/size_max/kg_min/kg_max の NULL 率・コンボ別有効件数の確認。Phase B で独立予測を入れる前提として「学習に使えるデータが揃っているか」
- **stat-reviewer**: size の range_backtest で actual_size_avg と [size_lo, size_hi] を比較するのは適切か（actual_size_min/max と比較すべきか）
- **domain**: size の「小さい = 外れ」体感は cnt の「少ない = 外れ」と同じか。kg の重要度（0.1 は適切か）

### Phase B（必須・3並列レビュー）

- **stat-reviewer（最重要）**:
  - 防御策①の比率 0.3 で promise_break_rate と区間幅のトレードオフは許容範囲か
  - 防御策②の幅上限 1.5 で winkler スコアへの影響評価
  - cnt_min モデルのBL-2勝率51.9%が独立予測後もそのまま残ることへの懸念
  - α_scale clip [0, 1.2] と MAX_FACTORS=10 が引き続き過学習防止に有効か（cnt_min は n が少ないので cnt_avg より過学習しやすい）

- **data-reviewer**:
  - combo_wx_params の cnt_min が 318 コンボ存在することと、CSV の cnt_min NULL 率 41.6% の整合性確認（NULL 行が除外されて学習されたモデルが、NULL が多いコンボでも正しく動作するか）
  - `_apply_wx_correction(metric='cnt_min')` が use_fallback=True のコンボでどう動作するか

- **domain**:
  - 防御策①「pred_lo >= avg_cnt × 0.3」は釣り人体感として「最低でもこれくらいは釣れると言った」と解釈できるか
  - cnt_lo が floor に張り付くコンボ（実態として 0 匹が多い魚種）への対処（ボウズ多発コンボに対してfloorが「嘘」にならないか）

---

## 変更ファイル一覧（Phase 別）

### Phase A
- `analysis/V2/methods/combo_deep_dive.py`: _range_by_key 格納条件・range_backtest 集計ロジック・save_range_backtest スキーマ
- `analysis/V2/results/analysis.sqlite`: combo_range_backtest テーブル再作成（metric 列追加）

### Phase B
- `analysis/V2/methods/combo_deep_dive.py`: ratio override 削除（L3285〜3290）・decadal_ratio_m 初期化削除
- `analysis/V2/methods/predict_count.py`: 防御策①②定数追加・cnt_lo/cnt_hi 計算後のクリップ処理追加
- `analysis/V2/results/analysis.sqlite`: combo_range_backtest 全コンボ再集計（4時間）

### Phase C
- `analysis/V2/methods/combo_deep_dive.py`: composite_hit_rate 集計ロジック追加
- `analysis/V2/results/analysis.sqlite`: combo_range_backtest に composite_hit_rate 列追加

---

*作成: analyst / 2026-05-08*
*参照: 90_決定ログ.md §2026/05/08後半・PIPELINE.md C層*
