# ocean/ — A2〜A4層: 気象・台風・潮汐データ

## 役割

Open-Meteo・気象庁・天文計算から海況データを取得し、SQLite として提供する。
analysis/V2/methods/ が参照する前工程。

---

## 入力

| ファイル | 提供元 | 内容 |
|---------|--------|------|
| normalize/point_coords.json | normalize/ | 座標一覧（気象取得先の決定に使用） |
| normalize/area_coords.json | normalize/ | エリア代表座標 |

---

## 出力

| ファイル | 利用先 | 内容 | 更新頻度 |
|---------|--------|------|---------|
| weather_cache.sqlite | analysis/V2/methods/ | 気象・海況（153座標×145万行）| 手動（約30分） |
| tide_moon.sqlite | analysis/V2/methods/ | 月齢・潮汐（1,190日分） | 手動（5秒） |
| typhoon.sqlite | analysis/V2/methods/ | 台風トラック（70台風） | 手動（年次） |

> weather_cache.sqlite は約400MB のため `.gitignore` 対象（ローカルのみ）

---

## スクリプト

| ファイル | 実行タイミング | 内容 |
|---------|-------------|------|
| rebuild_weather_cache.py | 手動 | Open-Meteo から気象・海況を取得（約30分） |
| build_tide_moon.py | 手動 | 天文計算で月齢・潮汐を算出（5秒） |
| build_typhoon.py | 手動（年次） | 気象庁 BestTrack から台風データ取得 |

---

## バージョン管理

ocean/ 内のファイルは**バージョン管理しない**。
- SQLite は常に最新状態を維持（上書き再生成）
- スキーマ変更が必要な場合は analysis バージョンアップと同時に対応

---

## 前後工程との関係

```
Open-Meteo API / 気象庁
  ↓
ocean/ (A2〜A4)
  weather_cache.sqlite
  tide_moon.sqlite
  typhoon.sqlite
  ↓
analysis/V2/methods/（C層: 相関分析・バックテスト）
```
