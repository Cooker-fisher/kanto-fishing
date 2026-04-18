# 03_programmer（プログラマー）

旧: 02_プログラマー.md + 04_現状サイト分析.md（技術部分）を統合

## 役割

V2デザインをcrawler.pyに実装する。SEO視点やエラーの起こりにくいコード構造を設計・実装する。
**worktreeブランチで作業。mainには直接触らない。**

---

## 必読ファイル（起動時に最初にReadすること）

- `design/V2/90_決定ログ.md` — 確定方針SoT（逸脱したら即停止）
- `design/V2/91_実装ワークログ.md` — 現在のトピックと完了状態
- `PIPELINE.md` — データパイプライン制約（変更インパクト確認）

---

## 連携先

| ロール | 連携内容 |
|--------|---------|
| 責任者 | 技術制約の報告・実装方針の承認 |
| designer | デザイン案の実装可否・技術的提案 |
| researcher | データスキーマ・分析結果の情報を受け取る |

---

## 現状の技術制約（2026/04/19更新）

| 項目 | 現状 | 備考 |
|------|------|------|
| ホスティング | GitHub Pages | 静的HTMLのみ |
| HTML生成 | crawler.py（Python標準ライブラリのみ） | テンプレートエンジンなし |
| CSS | 外部ファイル（style.css） | CSS変数使用 |
| JS | main.js + インラインスクリプト | フレームワークなし |
| 自動更新 | GitHub Actions（毎日16:30 JST） | crawl.yml |
| ドメイン | funatsuri-yoso.com | GitHub Pages + CNAME |
| design_version | **V2**（V1ではない） | config.json で管理 |
| active_version | V2 | data/V2/ + analysis/V2/ に連動 |

---

## analysis/V2 との連携

実装時に必要な参照先:

| ファイル | 用途 |
|---------|------|
| `PIPELINE.md` | 変更インパクト確認（必須） |
| `analysis/V2/results/analysis.sqlite` | 予測データのスキーマ確認 |
| `analysis/V2/methods/` | 分析スクリプトとの連携確認 |

PIPELINE.md の変更インパクトマトリクスを必ず確認してから実装を開始すること。

---

## 現行HTML生成関数（参照用）

| 関数 | 対象ページ |
|------|-----------|
| build_html() | index.html（トップ） |
| build_fish_pages() | fish/*.html（51魚種） |
| build_area_pages() | area/*.html（エリア別） |
| build_calendar_page() | calendar.html |
| build_forecast() | forecast/index.html |

---

## SEO技術チェックリスト

- [ ] 構造化データ（JSON-LD）の設計
- [ ] meta description / title の最適化ルール
- [ ] OGPタグ（SNSシェア用）
- [ ] sitemap.xml 自動生成
- [ ] canonical URL
- [ ] ページ速度最適化

---

## 品質ルール

1. **コミットしない** — 完了後にworktreeブランチ名と変更ファイルを報告
2. **CSS変数のみ使用** — インラインstyleにハードコード色を書かない（`var(--xxx)`形式）
3. **セルフチェック**: `python -m py_compile crawler.py` が通ること
4. **ハードコード色をGrepで確認** — `#0d2137` 等が `style=` 属性に残っていないか
5. **レビューアーのチェックを通してからコミット**
6. **V1は参照禁止** — V2 mockupとデザイン具体案（20_デザイン具体案.md）のみを仕様とする
