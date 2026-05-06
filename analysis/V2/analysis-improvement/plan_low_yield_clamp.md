# Plan: ボウズ率高コンボ向けレンジクランプ機能（**不採用**）

作成日: 2026-05-06
担当: analyst
ステータス: **不採用（2026/05/07 セッションでクローズ）**

---

## ⚠ 不採用理由（2026/05/07 追記）

3並列レビュー（code-reviewer / stat-reviewer / data-reviewer）で **Critical 4件・Major 7件** の指摘。
特に Critical C-1 が致命的で、本Plan は構造的に動作しない設計だった。

### Critical C-1（致命）
`load_records` は `if not cnt_avg or cnt_avg <= 0: continue`（`combo_deep_dive.py:1170-1172`）でボウズ日を完全除外する。
本Plan の擬似コードは `save_combo_meta` に渡された `records` から `cnts = [r.get("cnt_avg") ...]` を作って bowzu_rate を計算するが、**records にボウズ日（cnt_avg=0）は1件も含まれない**ため `bowzu_rate = sum(v==0)/len(cnts) = 0/N = 0.0` で常にクランプ未発動になる。
analyst・stat-reviewer・code-reviewer の3者が見落とし、data-reviewer のみが指摘。

### その他の Critical
- C-2: combo_meta テーブルに ALTER TABLE パターンが既存しない（Plan の参照先 4029-4034 は別テーブル用） → INSERT で OperationalError
- C-3: p75 計算式の矛盾（Section 2: numpy.percentile 線形補間 vs Section 4-A: floor インデックス）
- C-4: クランプ後の OOS 検証（promise_break_rate before/after）スクリプト未定義

### 採用しない判断の根拠
1. C-1 修正には load_records 設計の見直しが必要で、影響範囲が他コンボの集計全体に及ぶ
2. cnt_max クランプは「カツオ×庄治郎丸 max=11 の爆釣日を完全切り捨て」という副作用が大きい
3. Major 7件の積み残し（閾値感度分析・命名衝突など）が多すぎる

### 次セッション候補（決定ログ参照）
- log1p 学習 / Hurdle モデル / キハダマグロを KAIYU_FISH 集合へ追加（D案）

**本ドキュメントは学習材料・アンチパターン記録として保持。実装には進めない。**

---

---

## 1. 概要

### 目的・期待効果

キハダマグロ×ちがさき丸（ボウズ率60.7%）、マダイ×つね丸（55.4%）、カツオ×庄治郎丸（51.9%）
の3コンボは、実績の過半がボウズであるにもかかわらず現状の cnt_hi が数匹〜十数匹に膨らむ
ケースがある。これは「期待させて釣れなかった」promise_break_rate を高め、ユーザー信頼を損なう。

シミュレーション（キハダマグロ×ちがさき丸 n=122 全データ）では [0, 1] クランプで
coverage 95.9%・promise_break_rate 0% と実用域に達することが確認済み。

期待効果:
- 対象3コンボの promise_break_rate をほぼ 0 に抑制
- cnt_hi の過大表示を防ぎ、ユーザー視点での「当たった率」向上
- 他コンボへの副作用なし（bowzu_rate < 50% のコンボはクランプ未発動）

### 非ゴール

- 学習段（section_backtest_rolling / 相関分析）は一切変更しない
- combo_backtest テーブルの評価軸（wMAPE, BL-2 勝率, OOS r）は変更しない
- crawler.py・HTML テンプレートは変更しない（cnt_lo/cnt_hi の既存出力経路を使う）
- 全体 wMAPE の改善を目的としない（このコンボはノイズ上限外の構造問題）

---

## 2. データ仕様

### bowzu_rate 計算式

```
bowzu_rate = count(cnt_avg == 0) / count(cnt_avg IS NOT NULL AND is_cancellation == 0)
```

フィルタ条件:
- `is_cancellation = 0`（欠航除外）
- `cnt_avg IS NOT NULL`（欠損除外）
- `main_sub = 'メイン'`（load_records と同じフィルタ）
- 全期間（計算窓の選択肢の議論は後述）

### p75_cnt_avg 計算式

```
p75_cnt_avg = numpy.percentile([r["cnt_avg"] for r in records], 75)
```

同一フィルタで cnt_avg のソート済みリストの 75 パーセンタイル（線形補間）を使う。

### 計算窓の選択: 全期間 vs. leave-one-month-out 学習データのみ

**全期間で計算する（推奨）:**
- メリット: 計算が単純。save_combo_meta は全レコードを受け取るタイミングで計算できる。
- デメリット: 「未来のデータを含む」という意味で OOS バックテストへの直接リークになる。
  ただし bowzu_rate / p75 はクランプ上限の設定に使うのみであり、
  モデル係数の学習には使わない。予測値を上書きするだけなので実質的な情報漏洩は限定的。
- 判断: combo_decadal（旬別ベースライン）も全データで計算しており、同レベルの「リーク」は
  既に許容されている。bowzu_rate のリーク度合いはそれと同等以下と見なせる。

**leave-one-month-out 学習データのみで計算する（代替案）:**
- メリット: 厳密にリークなし。各テスト月の予測時点で「その月を除いた」bowzu_rate を使う。
- デメリット: section_backtest_rolling の内側ループで月ごとに bowzu_rate を再計算する必要があり、
  実装コストが大幅増加。現状の save_combo_meta はバックテスト完了後に呼ばれるため、
  バックテスト内部での参照は構造的に困難。
- 判断: 実用上の差は小さい（3コンボとも3年以上のデータで bowzu_rate は安定している）。
  全期間計算で進める。

### リーク懸念の結論

combo_meta は学習から分離した「集計テーブル」であり、combo_backtest の wMAPE 計算に
bowzu_rate は使われない。クランプは predict_count.py の出力段でのみ適用されるため、
バックテスト評価値（wMAPE / BL-2 勝率）に数値的な影響は生じない。
ユーザー向け表示と promise_break_rate に絞った機能追加と位置づける。

### MIN_N_COMBO=30 未満コンボの扱い

n_records < 30 のコンボは bowzu_rate / p75_cnt_avg を NULL で保存する。
predict_count.py はこれを IS NULL チェックで検出しクランプを無条件スキップする。

---

## 3. DB スキーマ変更

### combo_meta テーブルへの列追加

追加する列:
- `bowzu_rate REAL`（NULL = n<30 または未集計）
- `p75_cnt_avg REAL`（NULL = 同上）

### ALTER TABLE のタイミング

`save_combo_meta` 関数内の `CREATE TABLE IF NOT EXISTS` ブロックの直後、
既存の他テーブルと同じパターン（`PRAGMA table_info` で既存列確認 → 不在なら ALTER）を踏襲する。

参照パターン（combo_deep_dive.py 行 4029〜4034）:
```python
existing = {r[1] for r in conn.execute("PRAGMA table_info(combo_meta)").fetchall()}
for col, typ in [("bowzu_rate", "REAL"), ("p75_cnt_avg", "REAL")]:
    if col not in existing:
        conn.execute(f"ALTER TABLE combo_meta ADD COLUMN {col} {typ}")
```

### 既存データへの遡及適用方針

全種再分析（`run_full_deepdive.py --workers 4`）を 1 回実行すれば全コンボに bowzu_rate /
p75_cnt_avg が埋まる。updated_at が今日でない古い行は次回再分析まで NULL のままとなるが、
その間クランプは発動せず既存の cnt_lo/cnt_hi がそのまま返る（安全方向）。

---

## 4. ファイル変更箇所

### 4-A. combo_deep_dive.py — save_combo_meta 関数（行 4603〜4645）

変更内容: bowzu_rate と p75_cnt_avg の計算・保存を追加する。

変更位置: `save_combo_meta` 関数内、`avg_cnt = ...` の直後（行 4612 付近）。

擬似コード:
```python
# 既存行（変更なし）
cnts = [r.get("cnt_avg") for r in records if r.get("cnt_avg") is not None]
n_records = len(records)
avg_cnt = round(sum(cnts) / len(cnts), 3) if cnts else None

# 追加: bowzu_rate と p75_cnt_avg（MIN_N_COMBO=30 以上のみ）
MIN_N_META = 30
if len(cnts) >= MIN_N_META:
    bowzu_rate = sum(1 for v in cnts if v == 0) / len(cnts)
    cnts_sorted = sorted(cnts)
    p75_idx = int(len(cnts_sorted) * 0.75)
    p75_cnt_avg = cnts_sorted[min(p75_idx, len(cnts_sorted) - 1)]
else:
    bowzu_rate = None
    p75_cnt_avg = None
```

スキーマ追加位置: `CREATE TABLE IF NOT EXISTS combo_meta` ブロック後、conn.execute 前に
上記の ALTER TABLE パターンを挿入（行 4614〜4615 の間）。

INSERT/UPDATE 文への追加（行 4634〜4643）:
```python
conn.execute("""
    INSERT INTO combo_meta (fish, ship, n_records, avg_cnt, lat, lon, updated_at,
                            bowzu_rate, p75_cnt_avg)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(fish, ship) DO UPDATE SET
        n_records   = excluded.n_records,
        avg_cnt     = excluded.avg_cnt,
        lat         = excluded.lat,
        lon         = excluded.lon,
        updated_at  = excluded.updated_at,
        bowzu_rate  = excluded.bowzu_rate,
        p75_cnt_avg = excluded.p75_cnt_avg
""", (fish, ship, n_records, avg_cnt, modal_lat, modal_lon, now, bowzu_rate, p75_cnt_avg))
```

### 4-B. predict_count.py — predict_combo 関数（行 1331〜1340 付近）

変更内容: cnt_lo/cnt_hi のガード直後（行 1333 の swap 後）に `_clamp_low_yield()` を呼ぶ。

変更位置: 行 1333 と行 1335 の間（kaiyu ★評価の前）。

```python
# ガード: 独立計算で min > max になるケースをswapで修正（既存・変更なし）
if cnt_lo > cnt_hi:
    cnt_lo, cnt_hi = cnt_hi, cnt_lo

# 追加: ボウズ率高コンボのレンジクランプ
cnt_lo, cnt_hi = _clamp_low_yield(conn, fish, ship, cnt_lo, cnt_hi)

# 回遊魚★チャンス評価（既存・変更なし）
if is_kaiyu:
    ...
```

### 4-C. predict_count.py — _clamp_low_yield 関数（新規追加）

追加位置: `predict_combo` 関数の直前（行 1056 より前の適切な位置）。

関数シグネチャと擬似コード:
```python
BOWZU_CLAMP_THR = 0.50   # bowzu_rate >= この値でクランプ発動

def _clamp_low_yield(conn, fish: str, ship: str,
                     cnt_lo: float, cnt_hi: float) -> tuple[float, float]:
    """
    ボウズ率 >= 50% のコンボに対し cnt_min=0, cnt_max=max(1, p75_observed) でクランプする。
    combo_meta.bowzu_rate が NULL または < 閾値の場合は入力値をそのまま返す。
    """
    row = conn.execute(
        "SELECT bowzu_rate, p75_cnt_avg FROM combo_meta WHERE fish=? AND ship=?",
        (fish, ship)
    ).fetchone()

    if row is None:
        return cnt_lo, cnt_hi

    bowzu_rate, p75 = row

    # bowzu_rate が NULL（n<30 または未集計）の場合はスキップ
    if bowzu_rate is None or bowzu_rate < BOWZU_CLAMP_THR:
        return cnt_lo, cnt_hi

    # p75 が NULL または 0 以下の場合も安全にスキップ
    if p75 is None or p75 <= 0:
        return cnt_lo, cnt_hi

    clamped_lo = 0.0
    clamped_hi = float(max(1, p75))
    return clamped_lo, clamped_hi
```

不明点（実装前に要確認）:
- `conn` は `predict_combo` の引数として渡されている analysis.sqlite 接続か、
  それとも別途開く必要があるか。現在 `predict_combo` は `conn` を引数で受け取っており
  (行 1056)、`combo_meta` は analysis.sqlite に存在するため同一接続で参照できると見込む。
  実装時にコネクション対象DBを確認すること。

---

## 5. 検証手順

### 5-1. DB 確認（再分析後）

```sql
-- 対象3コンボの bowzu_rate / p75 が埋まっているか
SELECT fish, ship, n_records, avg_cnt, bowzu_rate, p75_cnt_avg
FROM combo_meta
WHERE (fish='キハダマグロ' AND ship='ちがさき丸')
   OR (fish='マダイ'       AND ship='つね丸')
   OR (fish='カツオ'       AND ship='庄治郎丸');
-- 期待値: bowzu_rate 0.607/0.554/0.519、p75 1.0/1.0/2.0
```

### 5-2. predict_count.py 動作確認（コマンドライン）

```python
import sqlite3
from analysis.V2.methods.predict_count import predict_combo

conn = sqlite3.connect('analysis/V2/results/analysis.sqlite')

# キハダマグロ×ちがさき丸: cnt_hi が 1 になること
r = predict_combo(conn, 'キハダマグロ', 'ちがさき丸', '2026-07-18')
assert r['cnt_lo'] == 0.0, f"expected 0.0 got {r['cnt_lo']}"
assert r['cnt_hi'] == 1.0, f"expected 1.0 got {r['cnt_hi']}"

# マダイ×つね丸: cnt_hi が 1 になること
r = predict_combo(conn, 'マダイ', 'つね丸', '2026-05-10')
assert r['cnt_hi'] == 1.0

# カツオ×庄治郎丸: cnt_hi が 2 になること
r = predict_combo(conn, 'カツオ', '庄治郎丸', '2026-08-02')
assert r['cnt_hi'] == 2.0

conn.close()
print('PASS')
```

### 5-3. ユーザー視点 wMAPE の改善幅（手動確認）

クランプ前後で n=122（キハダマグロ×ちがさき丸 全データ）の wMAPE を比較する。
期待: ボウズ日に cnt_hi=1 を予測 → 実績0との乖離が0 → wMAPE 大幅改善。
ただし wMAPE は cnt_avg>0 の行のみで計算するため、combo_backtest の数値は変わらない。

### 5-4. 既存 combo_backtest の wMAPE が悪化していないことの確認

```sql
-- 再分析前後（--reset-best なし）で wMAPE が変動しないこと
SELECT fish, ship, horizon, wmape
FROM combo_backtest
WHERE (fish='キハダマグロ' AND ship='ちがさき丸')
   OR (fish='マダイ'       AND ship='つね丸')
   OR (fish='カツオ'       AND ship='庄治郎丸')
ORDER BY fish, horizon;
```

クランプは学習段に触らないため、この数値は変化しないことが期待される。

### 5-5. 同魚種他コンボへの副作用なし確認

```sql
-- bowzu_rate < 0.50 の全コンボが bowzu_rate IS NULL または < 0.50 であること
SELECT fish, ship, bowzu_rate, p75_cnt_avg
FROM combo_meta
WHERE bowzu_rate >= 0.50;
-- 上記3コンボのみが返ること（他コンボが含まれていたら要確認）
```

実行時に対象3コンボ以外が bowzu_rate >= 0.50 の閾値を超えていないか確認する。

### 5-6. HTML 目視確認

`python crawler.py --html-only` 実行後:
- `docs/fish/キハダマグロ.html`: ちがさき丸の予測欄が「0〜1匹」表示
- `docs/fish/マダイ.html`: つね丸の予測欄が「0〜1匹」表示
- `docs/fish/カツオ.html`: 庄治郎丸の予測欄が「0〜2匹」表示
- 同魚種他船宿の予測欄に変化がないこと

---

## 6. ロールバック

### 即時無効化（DB 操作のみ）

```sql
UPDATE combo_meta SET bowzu_rate = NULL, p75_cnt_avg = NULL
WHERE (fish='キハダマグロ' AND ship='ちがさき丸')
   OR (fish='マダイ'       AND ship='つね丸')
   OR (fish='カツオ'       AND ship='庄治郎丸');
```

predict_count.py の `_clamp_low_yield` は `bowzu_rate IS NULL` の場合スキップするため、
これだけでクランプが即時無効化される。コード変更不要。

### コード変更のロールバック

対象ファイルの変更は2箇所のみ（combo_deep_dive.py / predict_count.py）であり、
いずれも既存処理の「後」に追記する形のため `git revert` 一発で戻せる範囲に保つ。

### 防御コード（実装に必ず含める）

`_clamp_low_yield` 内で以下の防御を設ける:
- `row is None` → スキップ
- `bowzu_rate is None` → スキップ
- `bowzu_rate < BOWZU_CLAMP_THR` → スキップ
- `p75 is None or p75 <= 0` → スキップ

これにより combo_meta に bowzu_rate 列が存在しない旧バージョンの DB でも安全に動作する。

---

## 7. 段階的実装ステップ（推奨工順）

### Step 1: スキーマ追加 + combo_meta 集計拡張（combo_deep_dive.py）

- `save_combo_meta` に ALTER TABLE パターン追加（2行）
- CREATE TABLE 定義には列を追加しない（既存行との互換性保持のため ALTER TABLE で追加）
- INSERT/UPDATE 文に bowzu_rate / p75_cnt_avg を追加
- bowzu_rate / p75_cnt_avg 計算ロジック追加

### Step 2: 対象3コンボだけ単体再分析で動作確認

```bash
python analysis/V2/methods/combo_deep_dive.py キハダマグロ ちがさき丸
python analysis/V2/methods/combo_deep_dive.py マダイ つね丸
python analysis/V2/methods/combo_deep_dive.py カツオ 庄治郎丸
```

SQL で bowzu_rate / p75_cnt_avg が期待値で埋まっていることを確認してから Step 3 へ進む。

### Step 3: predict_count.py にクランプロジック追加

- `_clamp_low_yield` 関数を追加（predict_combo より前の位置）
- predict_combo の cnt_lo/cnt_hi swap 直後に呼び出し行を 1 行追加

### Step 4: 全種再分析（全コンボの bowzu_rate を埋める）

```bash
python analysis/V2/methods/run_full_deepdive.py --workers 4
```

所要時間 25〜30 分。

### Step 5: HTML 確認 → 検証

```bash
python crawler.py --html-only
python crawl/validate_output.py   # 11 不変条件全 PASS を確認
```

対象3コンボの HTML 表示を目視確認（Section 5-6 参照）。

---

## 8. 既知のリスクと懸念

### サービス価値と情報量のトレードオフ

cnt_hi をクランプすることで「爆釣日を予測できない」情報量の損失が生じる。
カツオ×庄治郎丸では実績 max が 11 匹あり、[0, 2] クランプは 100% の過小予測となる。
ただし同コンボの bowzu 率は 51.9%（約半分がボウズ）であり、
過大予測による promise_break_rate の悪化が過小予測より深刻と判断する。

ユーザーへの伝え方として「参考値（ボウズ多め）」などの注釈表示を検討してもよいが、
これは HTML テンプレートの変更を要するため本 Plan のスコープ外とする。

### 自動適用の範囲拡大リスク

将来的に bowzu_rate >= 50% のコンボが新たに出現した場合、自動でクランプが適用される。
意図的な設計だが、予期せず適用されるリスクがある。定期的に `SELECT fish, ship, bowzu_rate FROM combo_meta WHERE bowzu_rate >= 0.50` で該当コンボを監視する運用が望ましい。

### p75 が 0 のコンボへの対応

p75_cnt_avg = 0 のコンボ（全期間の 75% がボウズのような極端なケース）では
`max(1, p75) = 1` になるが、cnt_hi = 1 をユーザーに提示することが適切か要検討。
現状の `p75 <= 0 → スキップ` ガードで保守側に倒している。

---

## 9. レビュー観点（3並列レビュー時の観点ヒント）

### code-reviewer（04_code-reviewer.md）

- SQL: `SELECT bowzu_rate, p75_cnt_avg FROM combo_meta` のカラム順が ALTER TABLE 後も保証されるか（PRAGMA table_info で確認）
- NULL 処理: `row is None` / `bowzu_rate is None` の両方のケースが漏れなく処理されているか
- `_clamp_low_yield` の引数型と返り値型（float / tuple[float, float]）がコールサイトと一致しているか
- ALTER TABLE が `try/except` なしで書かれた場合、既に列が存在すると例外になる。既存パターン（`PRAGMA table_info` で確認してから ALTER）を使っているか
- INSERT 文の引数プレースホルダ数が列数と一致しているか（今回 9 引数）

### stat-reviewer（05_stat-reviewer.md）

- bowzu_rate 計算窓（全期間）の OOS バックテストへのリーク評価は Section 2 で論じたが、
  combo_backtest の wMAPE 計算式に bowzu_rate が入り込まないことを confirm すること
- p75 の計算に numpy.percentile（線形補間）を使う vs. ソート済みリストのインデックス参照のどちらが適切か（現提案はインデックス参照で floor 側に倒す簡易実装）
- BOWZU_CLAMP_THR = 0.50 の閾値根拠: データで確認済みの3コンボが全て >= 50% だが、
  将来コンボへの自動適用基準として 50% は適切か（40% や 60% との比較を要求してもよい）
- クランプ後の coverage / promise_break_rate の理論値（全コンボ中 bowzu 行が cnt_hi 以下に収まる割合）を Step 5 で数値として記録すること

### data-reviewer（06_data-reviewer.md）

- `save_combo_meta` が `records` として受け取るのは `load_records` の返り値か確認。`cnt_avg` キーの型（float / None）が期待通りか
- `combo_meta` の PRIMARY KEY は `(fish, ship)`（行 4631）。INSERT OR REPLACE ではなく ON CONFLICT DO UPDATE を使っているため既存行の NULL 列（cv_pct 等）を上書きしないことを confirm
- bowzu_rate 計算用の `cnts` は `cnt_avg IS NOT NULL` のみを含む（行 4610 の内包表記と同じフィルタ）。この cnts を bowzu_rate 計算にも再利用していることで `is_cancellation=0` / `main_sub='メイン'` フィルタが担保されているか（これらは `load_records` 内で既に除外されているため担保されているはずだが確認）
- combo_range_backtest.bowzu_rate（行 4288）と combo_meta.bowzu_rate（新規）は定義が異なる可能性がある: 前者は `ami == 0 and pl > bowzu_threshold` という条件（bowzu_threshold = hist_avg_min * 0.3 付近）を使うため単純な cnt_avg==0 比較ではない。混同しないよう命名か計算式を区別する必要があるか確認

---

## 不明点リスト（推測で埋めず記録）

1. `predict_combo` の引数 `conn` は analysis.sqlite への接続か（行 1056）。combo_meta は analysis.sqlite に存在するため同一接続で参照できると仮定しているが、接続先 DB を実装時に確認すること。
2. p75 計算に `numpy` を使うかネイティブ Python のみで行うか。`combo_deep_dive.py` で numpy がすでに `import numpy as np` されているか確認すること（predict_count.py はコンポーネント分離しているため単独インポート状況が異なる可能性）。
3. `combo_range_backtest.bowzu_rate` の計算式（行 3486〜3487）と今回新設する `combo_meta.bowzu_rate` の計算式は異なる（前者は bowzu_threshold を使う複雑定義）。将来的に統一が必要になる可能性があるが、現時点では別物として扱う。実装コメントに「combo_range_backtest.bowzu_rate とは定義が異なる。単純に cnt_avg==0 の割合」と明記すること。
4. `crawler.py --html-only` が forecast ページを生成する際に `predict_combo` 経由で cnt_lo/cnt_hi を使っているかを確認。クランプが HTML 生成時に正しく反映されるか、forecast/index.html のテンプレートも確認対象に含めること。
