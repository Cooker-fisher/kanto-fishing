# 20_Phase計画 — 段階的移行ロードマップ

> **管理者**: 工事責任者

---

## Phase一覧

| Phase | 内容 | リスク | 状態 |
|-------|------|--------|------|
| 0 | dustbox/作成 + 不要ファイル退避 | ★ 極低 | 未着手 |
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
- [ ] 掃除屋が4条件チェック完了
- [ ] 監視員がレビュー合格
- [ ] 責任者がユーザー承認取得
- [ ] GitHub担当者が参照ゼロを確認

### 完了条件
- [ ] dustbox/フォルダ作成済み
- [ ] dustbox/README.mdに全移動ファイルの記録がある
- [ ] 移動後にcrawler.pyが正常動作
- [ ] 引き渡し責任者の検証合格

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

## Phase 4: analysis/ バージョン管理構造への移行

### 概要（2026/04/08 再設計）

分析をバージョン管理する。旧 `analysis/` と現行 `insights/` を統合し、
`analysis/V1/`（旧）・`analysis/V2/`（現行）として再編成する。

```
analysis/
├── README.md         ← バージョン管理の説明・現行バージョン明示
├── V1/
│   ├── README.md     ← V1の分析条件・データ期間・V2との差分
│   ├── methods/      ← 旧 analysis/ のスクリプト・方法論文書
│   └── results/      ← 旧 analysis/ の出力物
└── V2/
    ├── README.md     ← V2の条件・出力先・参照先の明示
    ├── methods/      ← 現行 insights/*.py (14本)
    └── results/      ← analysis.sqlite, deep_dive/, weekly/, *.txt
```

### 段階（4a → 4b → 4c → 4d）

---

### Phase 4a: analysis/V1/ 作成（低リスク）

**対象ファイル:**

| ファイル | 移動先 |
|---------|--------|
| analyze.py | analysis/V1/methods/ |
| analysis_guide.md | analysis/V1/methods/ |
| discovery_process.md | analysis/V1/methods/ |
| analysis/README.md（旧） | analysis/V1/methods/ |
| analysis_results.md | analysis/V1/results/ |
| folklore_analysis.md | analysis/V1/results/ |
| catch_weather.csv | analysis/V1/results/ |
| report.html | analysis/V1/results/ |
| master_dataset.csv | dustbox/（5.8MB・要gitignore確認） |

**パス修正:** なし（旧ファイルはどこからも参照されていない）

**前提条件:**
- [ ] 掃除屋: master_dataset.csv の4条件チェック + gitignore確認
- [ ] GitHub担当者: analysis/ 内ファイルの参照元ゼロ確認

---

### Phase 4b: analysis/V2/ 作成（高リスク）

**最大リスク: ROOT_DIR パターンの書き換え**

現行の insights/*.py は全て:
```python
BASE_DIR = os.path.dirname(os.path.abspath(__file__))  # insights/
ROOT_DIR = os.path.dirname(BASE_DIR)                    # プロジェクトルート ✅
DB_ANA   = os.path.join(BASE_DIR, "analysis.sqlite")
OUT_DIR  = os.path.join(BASE_DIR, "deep_dive")
```

移動後の analysis/V2/methods/*.py は:
```python
BASE_DIR    = os.path.dirname(os.path.abspath(__file__))        # analysis/V2/methods/
ROOT_DIR    = os.path.abspath(os.path.join(BASE_DIR, "../../.."))  # プロジェクトルート ✅
RESULTS_DIR = os.path.abspath(os.path.join(BASE_DIR, "../results"))  # analysis/V2/results/
DB_ANA      = os.path.join(RESULTS_DIR, "analysis.sqlite")
OUT_DIR     = os.path.join(RESULTS_DIR, "deep_dive")
NORMALIZE_DIR = os.path.join(ROOT_DIR, "normalize")             # 変わらない
```

**修正対象スクリプト（14本）:**
combo_deep_dive.py / cancel_threshold.py / risk_predict.py / enrich_catches.py /
area_analysis.py / season_analysis.py / season_detail.py / weekly_analysis.py /
backtest.py / backtest_oos.py / analysis_combos.py / compare_granularity.py /
parse_deepdive.py / predict_count.py / ship_peaks.py / save_insights.py

**移動対象:**

| 移動元 | 移動先 |
|--------|--------|
| insights/*.py (14本) | analysis/V2/methods/ |
| insights/deep_dive/ | analysis/V2/results/deep_dive/ |
| insights/weekly/ | analysis/V2/results/weekly/ |
| insights/analysis.sqlite | analysis/V2/results/analysis.sqlite |
| insights/*.txt (6本) | analysis/V2/results/ |

**外部からの参照修正:**

| ファイル | 修正箇所 | 内容 |
|---------|---------|------|
| crawler.py | L3644, L6183 | insights/analysis.sqlite → analysis/V2/results/analysis.sqlite |
| crawler.py | L3741 | insights/risk_weekend.txt → analysis/V2/results/risk_weekend.txt |
| crawl.yml | L73-88 | insights/*.py → analysis/V2/methods/*.py |
| crawl.yml | L83 | insights/analysis.sqlite → analysis/V2/results/analysis.sqlite |

**前提条件:**
- [ ] Phase 4a 完了
- [ ] GitHub担当者: 全参照箇所リスト確定
- [ ] py_compile で全スクリプト事前確認

---

### Phase 4c: README 作成

| ファイル | 内容 |
|---------|------|
| analysis/README.md | バージョン一覧・現行バージョン・切り替えルール |
| analysis/V1/README.md | V1の分析条件・データ期間・主要ファイル説明 |
| analysis/V2/README.md | **出力先・参照先の明示**（コラボレーターの要件） |

**analysis/V2/README.md の必須セクション:**
```markdown
## 出力先（書く側へ）
→ 分析結果は必ず `analysis/V2/results/` に出力すること

## 参照先（読む側へ）
→ 分析結果を使う場合は `analysis/V2/results/` を参照すること
→ 旧バージョンとの比較は `analysis/V1/results/` を参照
```

---

### Phase 4d: ドキュメント更新

- [ ] PIPELINE.md: C層の記載を analysis/V2/methods/ に更新
- [ ] CLAUDE.md: ファイル構成セクション全更新
- [ ] 12_入出力契約.md: insights/ → analysis/V2/ に更新
- [ ] insights/ フォルダ: 空になったら削除

---

### 完了条件

- [ ] analysis/V1/ と analysis/V2/ にファイルが整理済み
- [ ] insights/ フォルダが削除済み
- [ ] 旧パス残存ゼロ（crawler.py / crawl.yml 含む）
- [ ] py_compile 全スクリプトOK
- [ ] crawl.yml が新パスで正常動作
- [ ] 引き渡し責任者の検証合格

---

## 全Phase完了後

- [ ] PIPELINE.md を新構成に合わせて更新
- [ ] CLAUDE.md のファイル構成セクションを更新
- [ ] 90_決定ログ.mdに完了記録
- [ ] ユーザーに最終報告
