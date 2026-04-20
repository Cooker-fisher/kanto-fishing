# ポイント別最適化メソッド

**対象ロール**: analyst / stat-reviewer / domain  
**最終更新**: 2026/04/20  
**ステータス**: 実装完了（タチウオ×吉野屋で実証。全コンボ展開は次回run_full_deepdiveで適用）

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

1. **全55種で `run_full_deepdive.py` 再実行** → 全コンボにポイント別モデルを展開
2. **ポイント選択モデルをSST実測値ベースに改善**（現状は月別集計のみ）
3. **ポイント選択確率を predict_combo の戻り値に追加**（HTML表示用）

---

## 参照先

- `analysis/V2/methods/combo_deep_dive.py` — `deep_dive_by_point()`, `save_decadal()`
- `analysis/V2/methods/predict_count.py` — `_predict_point()`, `_apply_point_wx_correction()`
- `90_決定ログ.md` — 2026/04/20 ポイント別分析の実装・設計確定
- `.claude/memory/project_point_optimization.md` — 詳細メモリ
