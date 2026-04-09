# crawl/ — A1層: 釣果クロール

## 役割

釣りビジョン (fishing-v.jp) から釣果生データを収集し、`catches_raw.json` として蓄積する。

---

## 入力

| ファイル | 提供元 | 内容 |
|---------|--------|------|
| ships.json（本フォルダ内） | discover_ships.py が生成 | クロール対象船宿一覧 |

---

## 出力

| ファイル | 利用先 | 内容 | 更新頻度 |
|---------|--------|------|---------|
| catches_raw.json（ルート） | crawler.py (B層) | 釣果生データ（84,757件〜） | 毎日自動 |
| catches.json（ルート） | crawler.py (E層) | 当日スナップショット | 毎日自動 |
| catches_all.json（ルート） | crawler.py (E層) | 全釣果差分追記 | 毎日自動 |
| ships.json（本フォルダ内） | crawler.py (B/E層) | 船宿一覧 | 月1回自動 |

---

## スクリプト

| ファイル | 実行タイミング | 内容 |
|---------|-------------|------|
| discover_ships.py | 月1日 自動（crawl.yml） | 釣りビジョンをスクレイプして ships.json を更新 |

---

## バージョン管理

catches_raw.json は**バージョン管理しない**。
- 常に生データの最新状態
- CSV への変換・スキーマ変更は `data/Vn/` 側でバージョン管理する
- ships.json の構造変更は crawler.py と同時に対応

---

## 前後工程との関係

```
crawl/ (A1)
  ↓ catches_raw.json
crawler.py (B層) → data/V2/YYYY-MM.csv
                 → index.html / fish/*.html (E層)
```
