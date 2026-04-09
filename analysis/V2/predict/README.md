# analysis/V2/predict/ — D層: 予測スクリプト

**役割**: C層（analysis.sqlite）の分析結果を使って予測を生成・蓄積するスクリプト群。

analysis/V2/methods/（C層）の分析スクリプトとは責任が異なるため分離。

---

## スクリプト一覧

| スクリプト | 内容 | 実行タイミング |
|-----------|------|--------------|
| prediction_log.py | 予測ログ蓄積・答え合わせ（フェーズ2） | 毎日自動（crawl.yml） |

---

## prediction_log.py

### 目的
- `daily_predict()`: 今日+7日の全★3以上コンボ（119件）の釣果を予測して analysis.sqlite の `prediction_log` テーブルに記録
- `match_actuals()`: target_date を過ぎた予測行に実績値を照合し、精度（wmape/mae/is_good_hit）を計算

### 出力テーブル: prediction_log

| 列 | 内容 |
|----|------|
| pred_pct | 予測値の旬別ベースライン比±%（design/V2 ZONE B' 無料表示用） |
| actual_pct | 実績のベースライン比±%（照合後に計算） |
| pred_cnt_avg/min/max | 予測匹数レンジ（有料表示用） |
| actual_cnt_avg/min/max | 実績匹数レンジ（照合後に計算） |
| fcast_wave/wind/sst/temp | 予報気象値（将来の予報誤差分析用） |
| is_good_hit | 3分類一致フラグ（的中バッジ用、0/1） |

### 使い方

```bash
python analysis/run.py prediction_log.py --both       # 予測 + 照合（通常）
python analysis/run.py prediction_log.py --predict    # 予測のみ
python analysis/run.py prediction_log.py --match      # 照合のみ
python analysis/run.py prediction_log.py --stats      # 蓄積状況サマリー
python analysis/run.py prediction_log.py --dry-run --predict  # 件数確認
```

### 依存関係

- `../methods/_paths.py` — パス解決
- `../methods/predict_count.py` — predict_combo() 関数
- `../../results/analysis.sqlite` — 入力（combo_decadal, combo_backtest, combo_thresholds）+ 出力（prediction_log）
- `../../../data/V2/YYYY-MM.csv` — 実績照合用

---

## 命名規則

- 予測生成スクリプト: `predict_*.py`
- ログ管理スクリプト: `*_log.py`
- 評価スクリプト: `eval_*.py`（将来）
