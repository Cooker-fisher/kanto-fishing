# 20_Phase計画 — 段階的移行ロードマップ

> **管理者**: 工事責任者

---

## Phase一覧

| Phase | 内容 | リスク | 状態 |
|-------|------|--------|------|
| 0 | dustbox/作成 + 不要ファイル退避 | ★ 極低 | ✅ 完了 |
| 1 | ocean/ 分離 | ★ 低 | 未着手 |
| 2 | crawl/ 分離 | ★★ 中 | 未着手 |
| 3 | normalize/ 分離 | ★★★ 高 | 未着手 |
| 4 | insights/ 整理 + analysis/ 統合 | ★★ 中 | 未着手 |

---

## Phase 0: dustbox/作成 + 不要ファイル退避

### 概要
不要な一時スクリプト・レガシーデータをdustbox/に退避。
参照がゼロのファイルのみ対象。本番に影響なし。

### 対象ファイル（15件）
- 一時スクリプト: backfill_depth.py, backfill_precipitation.py, check_depth_ab.py, crawl_cancellations.py, crawl_history_raw.py, history_crawl.py, migrate_csv.py, recrawl_ships.py
- レガシー: moon.py, typhoon.py
- データ: moon.csv, typhoon.csv, fish_raw_list.txt, turimono_list_raw.txt, history_crawl_log.txt

### 前提条件
- [x] 掃除屋が4条件チェック完了
- [x] 監視員がレビュー合格
- [x] 責任者がユーザー承認取得
- [x] GitHub担当者が参照ゼロを確認

### 完了条件
- [x] dustbox/フォルダ作成済み
- [x] dustbox/README.mdに全移動ファイルの記録がある
- [x] 移動後にcrawler.pyが正常動作（moon.csvガード付きで影響なし）
- [x] 引き渡し責任者の検証合格

### 追加対応
- [x] crawl.ymlからbackfill_depthジョブ・inputを削除（参照解消）

---

## Phase 1: ocean/ 分離

### 概要
海況データ関連（A2/A3/A4層）をocean/フォルダに集約。
参照が比較的少なく、独立性が高い。

### 対象
- スクリプト: rebuild_weather_cache.py, build_typhoon.py, build_tide_moon.py, tide_fetch.py
- データ: tide_moon.sqlite, typhoon.sqlite, (weather_cache.sqlite)
- ディレクトリ: weather/, weather_data/, tide/

### 前提条件
- [ ] Phase 0 完了
- [ ] GitHub担当者がパス参照一覧作成

### 修正が必要な参照箇所（事前洗い出し）
- crawler.py内のsqliteパス
- crawl.yml内のステップ（build_tide_moon.py等の呼び出し）
- PIPELINE.md / CLAUDE.md の記載
- .gitignore（weather_cache.sqlite）
- insights/combo_deep_dive.py内のsqliteパス

### 完了条件
- [ ] ocean/フォルダにスクリプト・データが移動済み
- [ ] 旧パスのgrep残存ゼロ
- [ ] `python ocean/build_tide_moon.py` 正常実行
- [ ] 引き渡し責任者の検証合格

---

## Phase 2: crawl/ 分離

### 概要
釣果クロール関連（A1層）をcrawl/フォルダに集約。
catches_raw.jsonは参照が多いため慎重に。

### 対象
- スクリプト: discover_ships.py
- データ: ships.json, catches_raw.json, catches.json, history.json

### 前提条件
- [ ] Phase 1 完了
- [ ] GitHub担当者がパス参照一覧作成（catches_raw.jsonは参照多数）

### 注意事項
- catches_raw.jsonはcrawler.py内で多数参照 → パス修正箇所が多い
- crawl.ymlでcrawler.pyが直接catches_raw.jsonを読み書き → パス修正必須
- direct-crawl/からも参照される可能性 → 確認必要

### 完了条件
- [ ] crawl/フォルダにファイルが移動済み
- [ ] 旧パスのgrep残存ゼロ
- [ ] crawler.py正常動作（クロール+CSV+HTML）
- [ ] 引き渡し責任者の検証合格

---

## Phase 3: normalize/ 分離

### 概要
マスターデータJSON群とdata/ディレクトリをnormalize/に集約。
最も参照が多く、影響範囲が最大。最後に実施。

### 対象
- JSON: tsuri_mono_map_draft.json, point_coords.json, ship_fish_point.json, area_coords.json, point_normalize_map.json, ship_wx_coord_override.json
- ディレクトリ: data/

### 前提条件
- [ ] Phase 2 完了
- [ ] GitHub担当者がパス参照一覧作成（最多参照）

### 注意事項
- これらのJSONはcrawler.py内で集中的に参照 → 修正箇所が非常に多い
- insights/からもdata/*.csvを参照 → パス修正必須
- PIPELINE.mdの変更インパクトマトリクスでは★★★高影響

### 完了条件
- [ ] normalize/フォルダにJSON・data/が移動済み
- [ ] 旧パスのgrep残存ゼロ
- [ ] CSV行数が移行前と完全一致
- [ ] crawler.py正常動作
- [ ] 引き渡し責任者の検証合格

---

## Phase 4: insights/ 整理 + analysis/ 統合

### 概要
analysis/フォルダの有用物をinsights/に統合し、残りをdustbox/へ。

### 対象
- analysis/ 全体（9ファイル・6MB）
  - 統合候補: analyze.py, analysis_results.md
  - dustbox候補: master_dataset.csv（再生成可能）, report.html

### 前提条件
- [ ] Phase 3 完了
- [ ] 掃除屋がanalysis/の各ファイルを判定

### 完了条件
- [ ] analysis/フォルダが空になり削除済み
- [ ] 有用物がinsights/に統合済み
- [ ] 不要物がdustbox/に退避済み
- [ ] 引き渡し責任者の検証合格

---

## 全Phase完了後

- [ ] PIPELINE.md を新構成に合わせて更新
- [ ] CLAUDE.md のファイル構成セクションを更新
- [ ] 90_決定ログ.mdに完了記録
- [ ] ユーザーに最終報告
