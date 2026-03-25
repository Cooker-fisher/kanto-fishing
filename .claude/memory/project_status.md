<!-- 最終更新: 2026-03-25 -->
---
name: プロジェクト現状
description: funatsuri-yoso.com の実装状況と未実装タスク（2026/03/25時点）
type: project
---

現行バージョン: crawler.py v5.7

最終更新: 2026/03/25

実装済み（主要なもの）:
- 釣果自動収集・魚種別/エリア別ページ・狙い目TOP5
- 昨年同週比較（history.json連携）
- HTTPS有効化済み
- AdSense審査送信済み（2026/03/21）
- 船宿数を26→89に拡大（discover_ships.py + ships.json自動読み込み）
- discover_ships.py: 釣りビジョンから神奈川・東京・千葉・茨城の船宿SIDを月1自動収集
- crawl.yml: 月1日に discover_ships.py を実行するcron追加
- エリアFrom探すドロップダウンを都道府県グループ別に整理
- 最新釣果のエリアフィルターボタンも都道府県グループ別に変更 + 港ページへリンク化
- 魚種ページ生成閾値を3件→1件に変更（メバル・カンパチも生成済み）
- .claude/launch.json 作成（Static File Server + Crawler build設定）
- 魚種クイック検索・釣果数順ソート・NEWバッジ追加
- 最新の釣果をdate desc順に修正（build_catch_table内でsorted適用）
- ✅ サイズカラムを「大きさ(cm)」「重量(kg)」に分割（2026/03/24）
- ✅ 不明・空欄行の薄表示（class="dim" opacity:0.45）（2026/03/24）
- ✅ 全ページに「データについて」折りたたみフッター追加（2026/03/24）
- ✅ SEO改善: fish・areaページのtitle/H1最適化（2026/03/25）
- ✅ SEO改善: canonical / OGP / BreadcrumbList schema 全ページ追加（2026/03/25）
- ✅ SEO改善: 内部リンク強化（2026/03/25）
- ✅ 推薦コメント整合性（2026/03/25）
  - build_reason_tagsに先週比タグ追加（📈先週比UP / 📉先週比DOWN）
  - _render_tagsでwow-upを正方向として扱う
  - build_commentでWoW矛盾注記: top/highでwow≦-30%→「直近は急減傾向・注意」
- ✅ 魚種×港ページ（fish_area/）新設（2026/03/25）
  - build_fish_area_pages(): ≥5件の(fish,area)組み合わせのみ生成
  - fish pageに「エリア別の釣果」セクション追加（fish_area/へのリンク）
  - main()に呼び出し追加
  - URL: fish_area/{fish}_{area}.html
  - 100〜200ページ増見込み

## 次チャットでやること（優先順）

### ① sitemap.xml の自動生成
- fish_area/ ページが増えたため、sitemap.xml をクロール時に自動生成する
- fish/*.html / area/*.html / fish_area/*.html を全列挙

### ② 魚種ページに「今週vs昨年同週比較」テーブル表示
- すでに実装済み（yoy_html）だが fish_area ページには未追加

## 未実装タスク（中長期）:
- AdSense審査結果待ち
- staleデータ（30日超）のトップ除外フィルタ未実装
- X自動投稿（アカウントロック解除待ち）
- じゃらんアフィリエイト
- history_crawl.pyで過去2年分一括取得
- crawl.ymlのNode.js 20→24アップグレード

**Why:** 推薦コメント整合性・魚種×港ページを2026/03/25に実装完了。次はsitemap.xml自動生成が最優先。
