# セグメント別モデル（4軸）

**対象ロール**: analyst / stat-reviewer / engineer  
**最終更新**: 2026/04/22  
**ステータス**: 実装完了（全55種展開済み）。predict_count.py への統合も実装完了（2026/04/22・コミット 16b0c7f0）

---

## 概要・設計思想

ポイント別モデル（`10_point_optimization.md`）で確立した「分割→個別CV」アプローチを3軸に拡張した。

**根本的な問題意識**: コンボ全体モデルは異質なサブグループを混合するため気象相関の推定が歪む。

| 混合の例 | 具体的なバイアス |
|---------|---------------|
| 午前便と午後便を混合 | 朝マズメ効果が時間帯変数でなく気象変数に誤帰属する |
| 浅場と深場を混合 | 深度依存の気温・DO相関が打ち消しあう |
| 澄み潮と濁り潮を混合 | 水色の good/bad 条件が魚種によって逆転する |

**設計共通ルール（全3軸）:**
- 分割後 N≥30 かつ 月数≥6 のセグメントのみモデルを持つ
- セグメントモデルが存在しない場合はコンボ全体モデルにフォールバック
- `section_backtest_rolling()` を各セグメントに独立して適用（leave-one-month-out CV）

---

## ① 便別モデル (deep_dive_by_trip)

### 設計

| 項目 | 内容 |
|------|------|
| 分割キー | `trip_no`（CSVの `trip_no` 列・整数） |
| 有効条件 | N≥30 かつ 月数≥6 |
| 除外条件 | 1便が全体の90%超を占めるコンボはスキップ（単一便集中型） |
| 新テーブル | `combo_trip_backtest` / `combo_trip_wx_params` |

### combo_trip_backtest スキーマ

```sql
CREATE TABLE combo_trip_backtest (
    fish        TEXT,
    ship        TEXT,
    trip_no     INTEGER,
    horizon     INTEGER,
    n           INTEGER,
    wmape       REAL,
    r           REAL,
    mae         REAL,
    bl0_wmape   REAL,
    bl2_wmape   REAL,
    PRIMARY KEY (fish, ship, trip_no, horizon)
)
```

### 全55種実行結果（2026/04/22）

- 有効セグメント数: **333件**
- 有効コンボ数: **36コンボ**

**TOP改善例:**

| コンボ | 便 | 全体wMAPE | 便別wMAPE | 改善 |
|--------|---|----------|----------|------|
| カワハギ×吉野屋 | 6便 | — | — | **+29.8pt** |
| シーバス×喜新丸 | 2便 | — | — | **+25.1pt** |
| マルイカ×喜平治丸 | 2便 | — | — | **+25.3pt** |

### 物理的な解釈

- 午前便と午後便では朝マズメ・夕マズメの影響が異なる
- 夜便は月齢・潮汐の相関が昼便より強い傾向がある
- 複数便を持つ船宿ほど改善幅が大きい（カワハギ系・マルイカ系）

---

## ② ポイント×水深帯複合モデル (deep_dive_by_point_depth)

### 設計

| 項目 | 内容 |
|------|------|
| 分割キー | `{point_place1}_{depth_band}` （両方が存在する場合のみ） |
| depth_band の区分 | 浅場(~40m) / 中深場(41-80m) / 深場(81-150m) / 超深場(151m~) |
| 有効条件 | N≥30 かつ 月数≥6 |
| 除外条件 | 仮想水深帯（浅場/中深場/深場/超深場）を `point_place1` に持つレコードは複合キー化しない（`_VIRTUAL_BANDS` guard） |
| 新テーブル | `combo_point_depth_backtest` / `combo_point_depth_wx_params` |

### _VIRTUAL_BANDS guard の意図

`deep_dive_by_point()` は depth_min ≥ 50% カバレッジのコンボに対して仮想ポイント（「浅場(~40m)」等）を自動付与する。これをそのまま point_depth 複合キーとすると「浅場(~40m)_浅場(~40m)」という冗長な二重分割が生まれる。この場合は除外する。

```python
_VIRTUAL_BANDS = {"浅場(~40m)", "中深場(41-80m)", "深場(81-150m)", "超深場(151m~)"}
if point in _VIRTUAL_BANDS:
    continue  # 仮想ポイントはpoint_depth複合の対象外
```

### combo_point_depth_backtest スキーマ

```sql
CREATE TABLE combo_point_depth_backtest (
    fish             TEXT,
    ship             TEXT,
    point_depth_key  TEXT,   -- "{point_place1}_{depth_band}"
    horizon          INTEGER,
    n                INTEGER,
    wmape            REAL,
    r                REAL,
    mae              REAL,
    bl0_wmape        REAL,
    bl2_wmape        REAL,
    PRIMARY KEY (fish, ship, point_depth_key, horizon)
)
```

### 全55種実行結果（2026/04/22）

- 有効セグメント数: **146件**
- 有効コンボ数: **11コンボ**

**TOP改善例:**

| コンボ | セグメント | 全体wMAPE | 改善 |
|--------|----------|----------|------|
| マルイカ×喜平治丸 | 剣崎沖_浅場 | — | **+16.9pt** |

### 物理的な解釈

- 同じポイントでも水深が違うと対象魚の行動・反応が変わる
- タチウオ・マルイカ等の中層魚は水深帯で釣法も異なる
- 深場ほど SST の日変動が小さく、長期変数（SLA/CHL）の寄与が大きくなる傾向

---

## ③ 水色セグメントモデル (deep_dive_by_water_color)

### 設計

| 項目 | 内容 |
|------|------|
| 分割キー | `water_color_cat`（澄み / 濁り） |
| カテゴリ基準 | `water_color_n ≥ 0.3` → 澄み / `water_color_n ≤ -0.3` → 濁り |
| 中間領域（-0.3 < n < 0.3）| セグメント対象外（全体モデルのみ） |
| 有効条件 | N≥30 かつ 月数≥6 |
| 新テーブル | `combo_water_color_backtest` / `combo_water_color_wx_params` |

### water_color_n の出処

`obs_fields.json` で定義された `keyword_score` 型特徴量。CSV の `water_color` 列のテキストをスコア化：

```jsonc
"water_color_n": {
  "source": "water_color",
  "compute": "keyword_score",
  "map": {"澄み": 1.0, "青": 0.8, "やや澄み": 0.5, "普通": 0.0, "やや濁り": -0.5, "濁り": -1.0, ...}
}
```

### combo_water_color_backtest スキーマ

```sql
CREATE TABLE combo_water_color_backtest (
    fish             TEXT,
    ship             TEXT,
    water_color_cat  TEXT,   -- "澄み" or "濁り"
    horizon          INTEGER,
    n                INTEGER,
    wmape            REAL,
    r                REAL,
    mae              REAL,
    bl0_wmape        REAL,
    bl2_wmape        REAL,
    PRIMARY KEY (fish, ship, water_color_cat, horizon)
)
```

### 全55種実行結果（2026/04/22）

- 有効セグメント数: **55件**
- 有効コンボ数: **42コンボ**

**TOP改善例:**

| コンボ | 水色 | 全体wMAPE | 改善 |
|--------|------|----------|------|
| アマダコ×幸新丸 | 澄み | — | **+15.7pt** |
| フグ×吉野屋 | 濁り | — | **+13.0pt** |
| カワハギ×吉野屋 | 澄み | — | **+10.7pt** |

### 物理的な解釈

- 澄み潮はシャローの視覚捕食魚（シーバス・フグ等）に有利 / 透明度が高すぎると底物は不利になる魚種もある
- 濁り潮はタコ・マダコ系や夜行性魚種が好む傾向
- 水色と SST/CHL の相関が強いため、セグメントを分けることで気象変数との混在を排除できる

---

## 精度サマリー（2026/04/22 時点）

| 評価基準 | 全体モデルのみ | 個別最適化込み（全4軸） | 差 |
|---------|-------------|---------------------|---|
| H=0 wMAPE P50 | 38.7% | **33.8%** | -4.9pt |
| H=0 BL-2勝率 | 97.4% | **98.7%** | +1.3pt |
| OOS r | — | +0.510 | — |

---

## deep_dive() 内の実行順（確定）

```python
def deep_dive(fish, ship):
    records = load_records(fish, ship_filter=ship)
    ...
    save_decadal(fish, ship, records)
    save_combo_meta(...)
    deep_dive_by_point(fish, ship)        # ポイント別（2026/04/20）
    deep_dive_by_trip(fish, ship)         # 便別（2026/04/22）
    deep_dive_by_point_depth(fish, ship)  # ポイント×水深帯（2026/04/22）
    deep_dive_by_water_color(fish, ship)  # 水色別（2026/04/22）
```

---

## combo_tuning JSON との連携

各コンボの `combo_tuning/` JSONに以下フィールドでセグメント情報を記録できる（任意）:

```json
"segment_notes": {
  "trip": "6便モデル有効（+29.8pt）。1-5便はN不足",
  "water_color": "澄みモデル有効（+15.7pt）。濁りはN=18で閾値未達"
}
```

---

## predict_count.py への統合（実装完了・2026/04/22）

**コミット: 16b0c7f0**

trip_no と water_color の2軸を `predict_combo()` に統合した。

### 実装済み関数

| 関数名 | 役割 |
|--------|------|
| `_apply_trip_wx_correction()` | `combo_trip_wx_params` を参照して便別補正を計算 |
| `_predict_water_color_cat()` | `water_color_daily` から澄み/濁り/"" を分類 |
| `_apply_water_color_wx_correction()` | `combo_water_color_wx_params` を参照して水色別補正を計算 |

### predict_combo() の変更点

- `trip_no: int = 0` パラメータを追加
- 優先チェーン（確定）: **trip > water_color > point > combo**
- 戻り値に `predicted_water_color`・`predicted_trip_no` を追加

### water_color FAST変数ガード

| 定数 | 値 | 理由 |
|------|---|------|
| `_WC_MAX_DAYS` | 7 | 水色遷移の時定数3.7日。7日超は情報価値なし |
| `_WC_MAX_DIST` | 0.3 | `combo_deep_dive.py` の距離閾値と統一。0.3度超の外挿はNone化 |

7日超の target_date に対しては `_predict_water_color_cat()` が `""` を返し、水色補正はスキップされる。

### 動作例（2026/04/10、アジ×吉野屋）

| 呼び出し条件 | cnt予測 | water_color | trip_used |
|-------------|---------|-------------|-----------|
| trip=0（デフォルト） | 64.28 | 濁り | — |
| trip=6 | 64.5 | 濁り | 6 |
| 将来日 2026/05/03（target_date 11日後）、trip=6 | 50.5 | ""（7日超でブロック） | 6 |

### stat-reviewer 指摘と対応状況

| 重要度 | 指摘内容 | 対応状況 |
|--------|---------|---------|
| Critical | water_color はFAST変数。7日超の予測に使うべきでない | 対応済み（`_WC_MAX_DAYS=7` ガード） |
| Critical | 距離閾値をcombo_deep_dive.pyと統一すべき | 対応済み（`_WC_MAX_DIST=0.3`） |
| High | セグメントベースラインの非対称（avg_cnt がコンボ全体平均） | **保留**。修正コスト高のため現行設計を維持。将来的にはセグメント別avg_cntへの変更を検討 |

### ポイント×水深帯（未統合）

`combo_point_depth_wx_params` はDBに保存済みだが、`predict_combo()` への統合は未実装。ポイント予測（`_predict_point()`）が成功した場合に depth_band を掛け合わせて参照する設計を将来実装予定。

---

## 参照先

- `analysis/V2/methods/combo_deep_dive.py` — `deep_dive_by_trip()`, `deep_dive_by_point_depth()`, `deep_dive_by_water_color()`
- `analysis/V2/methods/predict_count.py` — セグメント統合済み（trip/water_color 2軸・コミット 16b0c7f0）
- `10_point_optimization.md` — ポイント別モデル（元祖・4軸の起点）
- `90_決定ログ.md` — 2026/04/22 セグメント別モデル3軸の実装確定
