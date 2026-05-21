# T33 Plan v1 データ整合性レビュー

レビュアー: data-reviewer
対象: analysis/V2/analysis-improvement/plan_T33_2026-05-21.md
実施日: 2026-05-21

---

## 判定: NEEDS_FIX

CRITICAL 1件 / MAJOR 3件 / MINOR 2件

---

## CRITICAL

### C-1: DO グリッドのカバー率が極端に低い（1% / 61% の 2グループ混在）

[箇所: cmems_data.sqlite / cmems_depth テーブル]

cmems_depth の DO カラムの NULL 率を depth_m 別に集計した結果:

| depth_m グループ | 行数 | DO 非 NULL 率 |
|---|---|---|
| 0.5 / 5.1 / 9.6 / 18.5 / 47.4 / 92.3 / 186.1 / 541.1 m (GLORYS12 グリッド) | 465,701行 × 8深度 | **1.0%** |
| 0.5 / 5.1 / 9.8 / 19.4 / 47.2 / 97.0 / 199.8 / 508.6 m (BGC グリッド) | 54,060行 × 8深度 | **51〜62%** |

DO は BGC グリッド (54,060 行) にしか実質存在しない。GLORYS12 グリッド座標では 1.0% = ほぼ NULL。

DO 非 NULL の座標数は全 157 座標中 157 座標に存在するが、座標ごとのカバー率を確認すると 0.25° 刻み BGC グリッドに乗っている座標のみ 53〜62% カバー、0.0833° 刻み GLORYS12 座標では 0〜1%。

結果として:

- DO を採用済みの 60 コンボ (combo_meta join 後のユニーク fish×ship) のうち 1 件 (トラフグ×吉久 lat=35.65, lon=139.9) は DO グリッド 0.25° 圏外。相関 r は雑音由来の疑似相関である可能性がある。
- 残 59 コンボは 0.25° 以内に BGC グリッドが存在し、データとして有効。

**Plan の「204コンボ採用漏れ救済」の前提が揺らぐ。** DO_FACTORS を独立カテゴリ化した場合、追加採用される 204 コンボのうち GLORYS12 座標ベースのコンボ (全体の約 90%) は実質 DO=NULL で相関計算自体が成立しない可能性がある。_cmems_depth_nearest が BGC グリッドを優先的に返すか、GLORYS12 座標に誤って 1% データを返すかをコード確認が必須。

**修正方針:** Phase 2 着手前に `_cmems_depth_nearest(conn, lat, lon, date, 0.25, ["do","no3"])` の返り値を主要船宿座標（東京湾: lat=35.4, lon=139.7; 相模湾: lat=35.1, lon=139.2; 外房: lat=35.0, lon=140.1）で Bash 直接クエリし、DO 非 NULL 率を確認する。1% グリッドが返っている場合は採用漏れ 204 件の大半はノイズ相関であり、Phase 2 の期待効果 (350件採用) は過大評価となる。

---

## MAJOR

### M-1: 庄治郎丸 lat/lon (35.30, 139.32) は東京湾内座標だが、魚種によっては相模湾外房釣行あり

[箇所: analysis.sqlite / combo_meta — 庄治郎丸全コンボ]

combo_meta で庄治郎丸の全コンボが (lat=35.30, lon=139.32) を持つ。これは神奈川・三浦半島付近の東京湾寄り座標。しかし庄治郎丸は三崎港発着で相模湾〜外房も釣行する船宿。

既存の BLACKLIST に「タイ五目×ちがさき丸: do_surface は東京湾 DO 値が相模湾コンボに適用された疑似相関」が登録されている。同様のパターンが庄治郎丸の外房系魚種コンボ (カンパチ/クロムツ等) でも発生し得る。

Plan §2-2 の「アジ×大松丸 do_surface r=0.935」「マルイカ×棒切丸 do_bottom r=-0.918」はいずれも combo_meta に存在しない (DO 採用済みコンボのユニーク fish×ship=60 件に両者なし)。Plan の具体例として記載された船宿が現在の analysis.sqlite に存在しない点を確認が必要。

**修正方針:** DO_FACTORS 採用後、庄治郎丸の全コンボについて ship_wx_coord_override.json に正しい実釣座標を登録するか、DO を BLACKLIST 追加する。

### M-2: _find_best_cmems の MIN_TRAIN_MONTHS_CMEMS=6 が MIN_MONTHS=4 変更後も 6 のまま残り非整合

[箇所: combo_deep_dive.py:559]

```python
MIN_TRAIN_MONTHS_CMEMS = 6  # full backtest の MIN_MONTHS と揃える
```

コメントに「full backtest の MIN_MONTHS と揃える」と明記されている。MIN_MONTHS を 4 に変更した場合、_find_best_cmems が 4〜5 か月のコンボで CMEMS 最適化をスキップ (all skipped → best_cmems=2 fallback) する。

これは DO_FACTORS 独立化と組み合わさると「4〜5 か月の新規コンボで CMEMS=0 のまま DO だけが採用される」ケースが発生する。DO 採用に MIN_TRAIN_MONTHS_CMEMS チェックが掛かっているかを確認していない。

combo_monthly から推計: MIN_MONTHS=4 緩和で新規救済候補 19 件 (n>=30 かつ combo_meta 未登録) が追加される。ただしこのうち「海上つり堀まるや」は ships.json の exclude:true が疑われる (CLAUDE.md 参照)。

**修正方針:** MIN_MONTHS=4 に変更するなら `MIN_TRAIN_MONTHS_CMEMS = MIN_MONTHS` に合わせて変更する。または DO_FACTORS に対しても同様の月数ガードを追加する。

### M-3: cv_pct が 357/384 = 93% のコンボで NULL — 計算バグ (設計仕様)

[箇所: combo_deep_dive.py:5176 save_combo_meta]

コードコメントに「既存行は UPDATE しない列 (cv_pct 等) は NULL のまま残す」と明記されている。cv_pct を書き込むルートが save_combo_meta には存在しない。つまり cv_pct は別スクリプト (save_insights.py 等) が書き込む想定だが、現行パイプラインで呼ばれていないため 93% が NULL。

Plan §2-3 で「0-factor 31 件全件で cv_pct=NULL」と記載されているが、実際には 0-factor に限らず全体の 93% が NULL であり、0-factor 固有の問題ではない。cv_pct を使った判定ロジック (T33 内で cv_pct に依存する処理) があれば全滅する。

**修正方針:** T33 スコープ内に cv_pct を使う処理がなければ現状維持で許容。ただし「0-factor コンボの診断に cv_pct を使う」設計を入れるなら save_combo_meta に cv_pct 計算を追加する必要がある。

---

## MINOR

### N-1: cmems_depth MAX(date) = 2026-04-18 — DO の直近 5 週間が未取り込み

[箇所: ocean/cmems_data.sqlite / cmems_depth]

water_color_daily は 2026-04-24 まで学習済み (Plan §2-4) だが、cmems_depth の MAX(date) = 2026-04-18 で 5 週間 (2026-04-19 〜 2026-05-21) の DO データが欠落。Phase 2 で DO 採用を拡大しても直近 5 週の釣果レコードに DO=NULL が続く。直近データへの DO 効果がゼロになるため、short-term なコンボほど DO 係数の推定がノイズを拾いやすい。

**修正方針:** build_cmems.py を Phase 4 前に実行して 2026-04-19 以降を取り込む。所要時間は PIPELINE.md に「手動・随時」と記載されており T33 スコープに入れられる。

### N-2: water_color_daily は INSERT OR REPLACE で既存行を上書き — バックアップ推奨

[箇所: water_color_model.py:1103, 1113]

```python
"INSERT OR REPLACE INTO water_color_daily VALUES (?,?,?,?,?)", batch
```

PK=(lat, lon, date, depth_grp) の完全一致行のみ上書き。既存行の削除ではないため破壊リスクは低い。Plan §5 リスク4「バックアップ取得後実行」の方針は適切。追加される行 (2026-04-25 以降) に限れば既存値への影響はない。

---

## 確認済み事項 (問題なし)

| 項目 | 結果 |
|---|---|
| per-ship CSV 残存 (data/V2/) | 0 件 — T32 削除済み。再生成なし |
| chowari_*.csv との粒度整合 | chowari_2026-03/04/05.csv のみ存在。B層粒度 (ship, area, date, trip_no, tsuri_mono) と一致 |
| combo_wx_params PRIMARY KEY 重複 | DO を独立カテゴリ化しても既存行の factor 値は変わらないため PK 重複なし |
| water_color_daily INSERT OR REPLACE | 安全。既存行はPK完全一致時のみ上書き |
| FACTOR_BLACKLIST の DO 2件 | タイ五目×ちがさき丸 / マルイカ×秀丸 — 独立化後も維持される設計 |

---

## 総括

CRITICAL C-1 が最重要。DO グリッドの 1% / 61% 二層構造を確認しないまま Phase 2 を実装すると、追加採用 204 コンボの大半が NULL ベースの疑似相関採用になるリスクがある。Phase 2 着手前に `_cmems_depth_nearest` の BGC グリッド返却確認 (主要3エリア座標でのクエリ検証) を必須とする。

MAJOR M-2 (MIN_TRAIN_MONTHS_CMEMS 非整合) は MIN_MONTHS=4 変更と同時に 1 行修正で解消できる。

MAJOR M-3 (cv_pct NULL 93%) はT33スコープ内で cv_pct を使わなければ影響ゼロだが、既存の問題として記録する。
