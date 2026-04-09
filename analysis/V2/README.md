# analysis/V2/ — 分析バージョン2（現行）

> **バージョン**: V2
> **期間**: 2026年4月〜
> **状態**: 現行（アクティブ）

---

## このバージョンの分析条件

| 項目 | 内容 |
|------|------|
| データ期間 | 2024年4月〜（継続更新） |
| 釣果データ | data/YYYY-MM.csv（82,650行〜） |
| 気象データ | ocean/weather_cache.sqlite（153座標×145万行） |
| 潮汐データ | ocean/tide_moon.sqlite（1,190日分） |
| 台風データ | ocean/typhoon.sqlite（70台風） |
| 対応魚種 | 51魚種 |
| ポイント解決 | 3段階フォールバック（94.9%解決率） |

**V1 との主な差分:**
- 気象データ: CSV（V1）→ weather_cache.sqlite（V2〜）
- 対応魚種: 限定的（V1）→ 51魚種（V2〜）
- ポイント解決: 未整備（V1）→ 3段階フォールバック（V2〜）

---

## 出力先（書く側へ）

**分析結果は必ず `analysis/V2/results/` に出力すること。**

| ファイル | 内容 |
|---------|------|
| results/analysis.sqlite | 分析結果DB（combo_decadal・cancel_thresholds 等） |
| results/risk_weekend.txt | 来週末リスクサマリー（crawler.py が参照） |
| results/risk_forecast.txt | 全期間リスクサマリー |
| results/deep_dive/ | 船宿別テキストサマリー |
| results/weekly/ | 週次グリッド出力 |
| results/backtest.txt | バックテスト結果（in-sample） |
| results/backtest_oos.txt | バックテスト結果（out-of-sample） |
| results/cancel_threshold.txt | 欠航閾値レポート |

---

## 参照先（読む側へ）

- **後工程（crawler.py 等）** が分析結果を使う場合 → `analysis/V2/results/` を参照すること
  - `analysis/analysis_config.py` 経由で参照すること（バージョン切替時に修正不要）
- **旧バージョンとの比較** → `analysis/V1/results/` を参照

---

## 入力（前工程との契約）

| ファイル | 提供元 | 内容 |
|---------|--------|------|
| data/YYYY-MM.csv | normalize/ → data/ | 正規化済み釣果データ |
| ocean/weather_cache.sqlite | ocean/ | 気象・海況データ |
| ocean/tide_moon.sqlite | ocean/ | 月齢・潮汐データ |
| ocean/typhoon.sqlite | ocean/ | 台風トラックデータ |
| normalize/tsuri_mono_map_draft.json | normalize/ | 魚種正規化マップ |
| normalize/ship_wx_coord_override.json | normalize/ | 気象座標上書き |
| crawl/ships.json | crawl/ | 船宿一覧 |

---

## フォルダ構成

```
analysis/V2/
├── methods/             # C層: 分析スクリプト群（16本）
├── predict/             # D層: 予測スクリプト群
│   ├── prediction_log.py    # 予測ログ蓄積・答え合わせ（毎日自動実行）
│   └── README.md
├── results/             # 分析・予測結果出力先
└── analysis-improvement/  # ロール定義・決定ログ（V2専用）
```

- **methods/**: 分析（C層）。`_paths.py` のインポート必須。
- **predict/**: 予測（D層）。`_paths.py` は `sys.path.insert(..., "../methods")` 経由で参照。
- 新スクリプト追加時は `analysis/run.py` 経由で実行できることを確認すること（run.py は methods/ → predict/ の順でスクリプトを検索）。

---

## methods/ ファイル一覧

| ファイル | 内容 |
|---------|------|
| _paths.py | パス自動解決（CLAUDE.md 目印でルート検出） |
| combo_deep_dive.py | 船宿×魚種×気象 深掘り分析（主力・手動実行） |
| season_analysis.py | 旬カレンダー分析 |
| season_detail.py | 旬詳細分析 |
| area_analysis.py | エリア×魚種旬分析 |
| ship_peaks.py | 船宿別ピーク旬分析 |
| weekly_analysis.py | 週次分析（crawl.yml 自動実行） |
| cancel_threshold.py | 欠航閾値計算（crawl.yml 自動実行） |
| risk_predict.py | 来週末リスク予測（crawl.yml 自動実行） |
| backtest.py | 欠航・釣果予測精度バックテスト（in-sample） |
| backtest_oos.py | バックテスト（out-of-sample） |
| enrich_catches.py | 釣果CSV × 海況 結合 |
| analysis_combos.py | コンボ多次元因果分析 |
| compare_granularity.py | 日次 vs 週次相関比較 |
| save_insights.py | 分析結果 DB 保存 |
| parse_deepdive.py | deep_dive テキスト → deepdive_params.json |
| predict_count.py | 釣果数予測 |

---

## 他バージョンとの関係

- **V1（旧）**: `analysis/V1/` を参照。旧CSVフォーマット・限定魚種
- **V3（将来）**: 作成時は `config.json` の `active_version` を `"V3"` に変更するだけ
