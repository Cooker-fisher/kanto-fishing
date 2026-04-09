# analysis/V1/ — 分析バージョン1（旧フォーマット期）

> **バージョン**: V1
> **期間**: 〜2026年3月
> **状態**: アーカイブ（参照専用）

---

## このバージョンの分析条件

| 項目 | 内容 |
|------|------|
| データ期間 | 2024年4月〜2026年3月（約2年） |
| 釣果データ | data/YYYY-MM.csv（34,280行） |
| 気象データ | weather/YYYY-MM.csv（CSV形式・96座標） |
| 潮汐データ | tide/YYYY-MM.csv（CSV形式） |
| 月齢データ | moon.csv |
| 台風データ | typhoon.csv |
| 結合方法 | catch_weather.csv に手動JOIN |

**V2 との主な差分:**
- 気象データが CSV → weather_cache.sqlite に移行（V2〜）
- 対象魚種が限定的 → 51魚種対応（V2〜）
- ポイント解決が未整備 → 3段階フォールバック（V2〜）

---

## 入力（前工程との契約）

| ファイル | 提供元 | 内容 |
|---------|--------|------|
| data/YYYY-MM.csv | normalize/ | 正規化済み釣果データ |
| weather/YYYY-MM.csv | （旧）ocean/ | 気象データ（CSV形式） |
| moon.csv | （旧）ocean/ | 月齢データ |
| typhoon.csv | （旧）ocean/ | 台風データ |

---

## 出力（後工程との契約）

| ファイル | 利用先 | 内容 |
|---------|--------|------|
| results/catch_weather.csv | （参照のみ） | 釣果×気象の結合データ |
| results/analysis_results.md | （参照のみ） | 分析結果サマリー |
| results/report.html | （参照のみ） | HTMLレポート |

---

## methods/ ファイル一覧

| ファイル | 内容 |
|---------|------|
| analyze.py | 釣果×気象 相関分析スクリプト（master_dataset.csv を読み込む） |
| analysis_guide.md | 分析手順ガイド |
| discovery_process.md | 分析発見プロセスのノート |
| README.md（旧） | V1時点のデータ仕様書 |

## results/ ファイル一覧

| ファイル | 内容 |
|---------|------|
| analysis_results.md | 分析結果サマリー（旧データ期間） |
| folklore_analysis.md | 釣り場の経験則・パターン分析 |
| catch_weather.csv | 釣果×気象の結合データ（107KB） |
| report.html | HTMLレポート（analyze.pyの出力） |

---

## 他バージョンとの関係

- **V2（現行）**: `analysis/V2/` を参照。weather_cache.sqlite 導入・51魚種対応
- このV1の結果と比較したい場合は `results/` を直接参照すること
