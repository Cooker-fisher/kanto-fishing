# ポイント別最適化メソッド

**対象ロール**: analyst / stat-reviewer / domain  
**最終更新**: 2026/04/22  
**ステータス**: 実装完了（ポイント別・便別・ポイント×水深帯・水色の4軸セグメント全55種展開済み）

---

## なぜポイント別に分けるか

船宿は複数のポイントを持つ。「タチウオ×吉野屋」なら走水沖・観音崎沖・猿島沖を季節によって使い分ける。

**混合モデルの問題**: 「夏=走水沖（SST高）」「冬=観音崎沖（SST低）」が海況変数と混合されると、季節バイアスを気象相関として誤検出する。

**実証結果（タチウオ×吉野屋、N=609）**:

| 対象 | N | H=0 wMAPE | OOS r |
|------|---|-----------|-------|
| 全体（混合） | 609 | 44.7% | — |
| 走水沖 | 259 | **35.8%** | +0.516 |
| 観音崎沖 | 98 | **35.4%** | +0.756 |
| 猿島沖 | 83 | **28.9%** | +0.713 |

平均 **-11.3pt** の wMAPE 改善。

---

## ⚠️ 重要: point_place1 が空の場合のフォールバックルール（必ず守ること）

`point_place1` が空でも **3段階フォールバックでポイント名を確定してから** `r["point"]` に格納すること。

| 優先度 | 条件 | 割当 |
|--------|------|------|
| ① | `depth_min` あり | 水深帯仮想ポイント（「浅場(~40m)」等） |
| ② | `ship_fish_point.json` に船宿×魚種の登録あり | `point1` の地名（例: 「平塚沖」） |
| ③ | `ships.json` の `area` あり | エリア名（例: 「相模湾」） |

**なぜ必須か**: `deep_dive_by_point()` は `if pt and n >= MIN_N_COMBO` で空文字列を除外する。フォールバックせずに `r["point"] = ""` のままにすると、point_place1 未記載のレコードが全て `viable_points` から脱落し、コンボ別最適化が動かない。

**実装済み箇所**: `load_records()` 内の `# point_place1 が空 → 3段階フォールバックでポイント名を確定` ブロック（2026/04/22 修正）。このロジックを変更・移動する際は必ずフォールバックを維持すること。

---

## ポイント抽出ルール（確定）

### 分析単位: `point_place1`

CSVの `point_place1` 列を使う。`point_place2/3` は使わない（副ポイント）。

### 複合ポイントの処理

| CSV値 | point_place1 として使う値 |
|-------|------------------------|
| `観音崎沖～猿島沖` | `観音崎沖` |
| `走水沖水深50m` | `走水沖`（depth_min=50 に分離済み） |
| `前後`・`付近` | 除去（地名として使わない） |
| `25〜40m`（数値のみ） | 地名としない（depth_minに格納） |

実装: `crawler.py` の `_split_point_places_depth()`

### N≥30 閾値

ポイント別モデルはN≥30のみ。MIN_N_COMBO=30と同じ基準。N<30のポイントはコンボ全体モデルにフォールバック。

---

## 実装構造

### combo_deep_dive.py

```python
def deep_dive(fish, ship):
    records = load_records(fish, ship_filter=ship)
    ...
    save_decadal(fish, ship, records)   # ← ここで直接更新（season_detail.py不要）
    save_combo_meta(...)
    deep_dive_by_point(fish, ship)      # ← ポイント別CV

def deep_dive_by_point(fish, ship):
    all_records = load_records(fish, ship_filter=ship)
    pt_counts = Counter(r["point"] for r in all_records)
    viable_points = [pt for pt, n in pt_counts.most_common() if pt and n >= MIN_N_COMBO]
    for pt in viable_points:
        pt_records = [r for r in all_records if r["point"] == pt]
        pt_decadal = _build_decadal_from_records(pt_records)
        decadal = pt_decadal if len(pt_decadal) >= 6 else decadal_global
        bt_lines, bt_data, ... = section_backtest_rolling(pt_records, decadal, ...)
        save_point_backtest(fish, ship, pt, bt_data)
        save_point_wx_params(fish, ship, pt, wx_params_data, lat, lon)
```

### predict_count.py

```python
def predict_combo(fish, ship, target_date, ...):
    ...
    # コンボレベルの予測
    cnt_predicted = _apply_wx_correction(...)

    # ポイントレベルの上書き
    predicted_point = _predict_point(conn, fish, ship, month)
    if predicted_point:
        pt_cnt = _apply_point_wx_correction(
            conn, fish, ship, predicted_point, target_date, avg_cnt, lat, lon, 'cnt_avg'
        )
        if pt_cnt is not None:
            cnt_predicted = pt_cnt   # ポイントモデル優先

    return {..., "predicted_point": predicted_point}
```

### ポイント予測ロジック

```python
def _predict_point(conn, fish, ship, month):
    # combo_point_events の月別集計から最頻ポイントを返す
    row = conn.execute(
        "SELECT point_normalized FROM combo_point_events "
        "WHERE fish=? AND ship=? AND month=? AND is_named=1 "
        "GROUP BY point_normalized ORDER BY COUNT(*) DESC LIMIT 1",
        (fish, ship, month)
    ).fetchone()
    return row[0] if row else None
```

---

## DBテーブル

| テーブル | 粒度 | 主要列 |
|---------|------|-------|
| `combo_point_stats` | fish×ship×point | n, avg_cnt, pct |
| `combo_point_events` | fish×ship×point×date | date, wx_*, tide_*, month, is_named |
| `combo_point_backtest` | fish×ship×point×H | wmape, r, mae, n |
| `combo_point_wx_params` | fish×ship×point×factor | alpha, corr, n_valid |

---

## combo_decadal 同期問題と根本解決

**問題（解決済み）**: `season_detail.py` を別途実行しないと `combo_decadal` が古いまま → `predict_combo` が None を返す。

**根本解決**: `deep_dive()` 内の `save_decadal()` が直接 `combo_decadal` を更新する。`season_detail.py` への依存なし。

**教訓**: 分析スクリプトが依存する集計テーブルは、そのスクリプト自身が更新すべき。別スクリプトへの依存は同期漏れを生む。

---

## ポイント選択パターン（タチウオ×吉野屋の例）

| 月 | 最頻ポイント | 理由 |
|----|------------|------|
| 7〜10月（SST≥22.7℃） | 走水沖 | タチウオの夏場回遊。浮き上がり |
| 11〜2月（大潮偏重） | 観音崎沖 | 冬場の深場移動。潮流が速い |
| 3〜6月（小潮偏重） | 猿島沖 | 春先産卵前の回遊経路 |

精度: 月+SST+tide_coeff で 75〜90% のポイント予測精度。

---

## 次のアクション

1. ~~**全55種で `run_full_deepdive.py` 再実行**~~ → 完了（2026/04/22）
2. **ポイント選択モデルをSST実測値ベースに改善**（現状は月別集計のみ）
3. **ポイント選択確率を predict_combo の戻り値に追加**（HTML表示用）
4. **セグメント別モデル（便/ポイント×水深帯/水色）の predict_count.py への統合**（未実装・TODO）

### 全4軸セグメント展開結果（2026/04/22 全55種完了）

| 軸 | テーブル | 有効レコード数 | TOP改善例 |
|----|---------|-------------|---------|
| ポイント別 | `combo_point_backtest` | 209件 | カワハギ×山天丸 剣崎沖 +42.1pt |
| 便別 | `combo_trip_backtest` | 333件 / 36コンボ | カワハギ×吉野屋 6便 +29.8pt |
| ポイント×水深帯 | `combo_point_depth_backtest` | 146件 / 11コンボ | マルイカ×喜平治丸 剣崎沖_浅場 +16.9pt |
| 水色別 | `combo_water_color_backtest` | 55件 / 42コンボ | アマダコ×幸新丸 澄み +15.7pt |

詳細仕様は `11_segment_models.md` を参照。

---

## 参照先

- `analysis/V2/methods/combo_deep_dive.py` — `deep_dive_by_point()`, `save_decadal()`
- `analysis/V2/methods/predict_count.py` — `_predict_point()`, `_apply_point_wx_correction()`
- `90_決定ログ.md` — 2026/04/20 ポイント別分析の実装・設計確定
- `.claude/memory/project_point_optimization.md` — 詳細メモリ
- `domain_knowledge_幸栄丸.md` — 鹿島港漁場構造・ドメイン妥当性チェック

---

## ポイントデータ補完メソッド（2026/04/22追加）

point_rawが空のレコードに対するポイント補完の方法論。**個別船宿の調査結果はcombo_tuning JSONの `point_source` フィールドに記録する。**

### 意思決定フロー

```
船宿のAPIにポイント情報がある？
  ├─ Yes: ship_name フィールド → 直接使用（庄治郎丸: shojiro_crawler.py, 1,634件補完）
  │        コメントにキーワード → キーワード抽出（幸栄丸①: koueimaru_crawler.py）
  └─ No:
       depth_min のカバレッジが高い（>50%）？
         ├─ Yes → 水深帯を仮想ポイントとして使用（幸丸: combo_deep_dive.py自動適用）
         └─ No:
              魚種ごとに支配的ポイントがある（≥65%）？
                ├─ Yes → 魚種デフォルト割当（幸栄丸②）
                └─ No → 気象条件（wave/SST/wind）で推定（幸栄丸③ ※ローカル専用）
```

### 手法別実績

| 手法 | 対象 | 件数 | 実装場所 |
|------|------|------|---------|
| API直接（ship_name） | 庄治郎丸 | 1,634件 | `direct-crawl/shojiro_crawler.py`（手動） |
| コメントキーワード | 幸栄丸① | 158件 | `direct-crawl/koueimaru_crawler.py`（手動） |
| 魚種デフォルト（≥65%） | 幸栄丸② | 1,571件 | 同上 |
| 気象推定（wave/SST/wind） | 幸栄丸③ | 323件 | 同上（weather_cache.sqlite必須・ローカル専用） |
| 水深帯仮想ポイント | 幸丸 | 自動 | `combo_deep_dive.py` load_records()（全船宿自動適用） |

### 幸栄丸ポイント別バックテスト結果

| コンボ | N | wMAPE | BL2 | 改善 |
|--------|---|-------|-----|------|
| マダコ×鹿島真沖 | 266 | 31.2% | 49.8% | **+18.7pt** |
| マダイ×鹿島南沖 | 512 | 47.0% | 59.4% | **+12.4pt** |
| フグ×鹿島南沖 | 225 | 62.3% | 69.9% | **+7.6pt** |
| ヒラメ×鹿島北沖 | 301 | 33.4% | 40.3% | **+6.9pt** |
| ヤリイカ×鹿島真沖 | 90 | 63.0% | 69.3% | **+6.2pt** |
| ワラサ×鹿島北沖 | 76 | 67.4% | 69.6% | +2.2pt |

### 幸丸 水深帯バックテスト結果

| コンボ | depth_band | N | wMAPE | BL2 | 改善 |
|--------|-----------|---|-------|-----|------|
| ヒラメ×幸丸 | 浅場(~40m) | 602 | 30.4% | 38.1% | **+7.7pt** |
| マダイ×幸丸 | 浅場(~40m) | 939 | 42.4% | 47.0% | **+4.6pt** |
| マハタ×幸丸 | 浅場(~40m) | 55 | 31.0% | 42.0% | **+11.0pt** |
| ヤリイカ×幸丸 | 深場(81-150m) | 57 | 51.3% | 62.5% | **+11.2pt** |

---

## 船宿別ポイント調査記録規約

### combo_tuning JSONの `point_source` フィールド

**個別船宿のポイント補完調査は combo_tuning JSON に記録する。** 船宿レベルの情報だが、魚種ごとに異なる場合もあるため per-combo で管理。

```json
"point_source": {
  "method": "depth_band",
  "coverage_pct": 93,
  "investigated": "2026-04-22",
  "notes": "depth_min 93%カバー → 水深帯仮想ポイント自動適用"
}
```

**method の選択肢:**

| method値 | 意味 |
|----------|------|
| `釣りビジョン` | 釣りビジョンの point_raw をそのまま使用（カバレッジ高） |
| `chowari_api` | chowari.jp API から直接取得（船宿サイト独自クロール） |
| `depth_band` | depth_min から水深帯仮想ポイントを割当 |
| `fish_default` | 魚種デフォルト（実績データから支配的ポイント≥65%） |
| `weather_est` | 気象推定（wave/SST/wind_dir から分岐） |
| `none` | 補完不可（釣りビジョンのみ・depth_min 0%・API未確認） |
| `not_investigated` | 未調査（デフォルト。省略可） |

### ポイントデータなし船宿リスト（2026/04/22時点）

以下はpoint% < 10% かつ depth% = 0% の主要船宿。優先度の高い順（N数）に調査する。

| 船宿 | N | 現状 | 調査優先度 |
|------|---|------|---------|
| 林遊船 | 2,779 | point=0%, depth=0% | ★★★ |
| 第三幸栄丸 | 2,536 | point=0.7%, depth=0% | ★★★ |
| 山本釣船店 | 4,234 | point=0.1%, depth=0% | ★★（除外候補確認要） |
| 博栄丸 | 1,741 | point=0.7%, depth=0% | ★★ |
| つる丸 | 1,371 | point=2.0%, depth=0% | ★★ |
| 石田丸 | 1,158 | point=0.3%, depth=0% | ★★ |
| 第八幸松丸 | 1,088 | point=3.3%, depth=0% | ★★ |
| 梅花丸 | 904 | point=0%, depth=0% | ★ |
| 大貫丸 | 843 | point=0.4%, depth=0% | ★ |

**調査手順（新セッション向け）:**
1. 船宿のWebサイトを確認し chowari.jp バックエンドか確認（URLに `chowari.jp` が含まれるか）
2. `jsonget.php` エンドポイントに POST してみる（gyo_crawler.py 参照）
3. `ship_name` フィールドにポイント名があれば shojiro_crawler.py 方式で実装可
4. コメントのみの場合は koueimaru_crawler.py 方式（キーワード→魚種デフォルト）
5. 結果を各コンボの combo_tuning JSON に `point_source` フィールドで記録
