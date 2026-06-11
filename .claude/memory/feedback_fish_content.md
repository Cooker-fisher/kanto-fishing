# 魚種ページ固定文（fish_content）執筆ルール

ユーザー確定 2026/06/11。

1. 文章は「固定/月1更新パート」と「日次自動更新パート」に分離する。
2. 数値はすべて自サイトB層データ（data/V2 CSV集計）から差し込む。出典明記不要。
3. **定性記述（系統B＝ドメイン知識由来）は必ず外部サイトで裏取りしてから採用する。**
   - WebSearch で2ソース以上確認。確認できない表現（通称・「標準」断定等）は落とすか弱める。
   - 文章はコピペ禁止・完全に独自文に書き直す。出典はページに表示しない（内部記録のみ）。
4. 自前データと外部定説が食い違う場合は自前データ優先で表現を分岐させる
   （例: マルイカ出船時間帯は三浦・葉山=日中 / 沼津・鹿島=夜便中心、と time_slot 集計で判明）。
5. **執筆前にエリア別分解チェック必須**（月別件数・水深・サイズ・time_slot をエリアグループ別に集計）。
   タックル・シーズン・サイズがエリアで異なる場合は省略せず書き分ける
   （例: マルイカは三浦=春〜初夏・日中多点スッテ / 沼津=冬+真夏・夜イカメタル / 鹿島=夏半夜・型40cm）。
6. emoji は Unicode でなく既存の魚種別画像 `assets/fish/{slug}/{slug}_emoji.webp` を使う。
7. 月報が実在する魚種のみシーズン解説末尾に最新月報リンク（空リンク・「準備中」は出さない）。

## 実装済みインフラ（2026-06-11 Phase 1・マルイカ pilot）

- `normalize/fish_content.json`: 固定文6セクション（howto/tackle_detail/season/areas/food/beginner）
- `normalize/fish_content_stats.json` ← `crawl/build_fish_content_stats.py`（**月1実行**・数値スナップショット）
- crawler.py `load_fish_content()` / `build_fish_guide_html()` 全タックルバリアント表示 / FAQ Q3 拡充
- validate_output 不変条件 #45（4ブロック・800字・プレースホルダ解決）
- 魚種追加手順: 外部裏取り → エリア別分解チェック → fish_content.json 追記 →
  `python crawl/build_fish_content_stats.py` → `python crawler.py --fish-index-only`（fish/ のみ commit）→
  `python crawl/validate_output.py`
- 残り: 薄ページ約20種（25KB以下）→ 全60種。fish_tackle.json の他魚種も裏取り見直し対象
