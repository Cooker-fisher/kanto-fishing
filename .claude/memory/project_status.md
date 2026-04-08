現行バージョン: crawler.py v5.23（design_version 同期・pages/ 移行）
最終更新: 2026/04/08
最新コミット: eb904ba（pages/: 静的HTML移動・crawler.py リンク更新）

## ★ 大掃除完了状況（全フェーズ完了）
- Phase 0（dustbox/作成）: 完了
- Phase 1（ocean/分離）: 完了 コミット 5286a28
- Phase 2（crawl/分離）: 完了 コミット 9c494f9
- Phase 3（normalize/分離）: 完了 コミット 5b2a5ff
- Phase 4a（analysis/V1/作成）: 完了 コミット 237ade2
- Phase 4b（analysis/V2/移行）: 完了 コミット 520bbf8
- Phase 4c（README作成）: 完了（4b と同コミット）
- Phase 4d（ドキュメント更新）: 完了
- Phase 5（ルート整理・design/・pages/）: 完了 コミット eb904ba

---

## ★ 次チャットでやること（優先度順）

### 1. combo_deep_dive.py を全51魚種で実行（ユーザー許可が必要）
- tide fix済み（tide_moon.sqlite参照に変更・コミット済み `72b7743`）
- 実行前にユーザーに確認してから走らせること

### 2. parse_deepdive.py → deepdive_params.json
- combo_deep_dive 完了後に実行

### 3. 売り物設計（予測の出力形式）
- 現状MAPE 27〜55%（CVが低い船宿）→ 匹数絶対値ではなく「平年比±%」「★評価」で出す
- 「来週末アジは平年比+25%（★★★★）」の形式が現実的
- 要実装: 旬別ベースラインからの偏差率を★5段階に変換するロジック

---

## ✅ 今セッション完了（2026/04/08 後半）

### ルート整理・フォルダ構成
- **design/ フォルダ整備**（コミット `5d410b0`）
  - redesign/ → design/V2/ に移動（ロールMD体制・モックアップ全保持）
  - design/V1/ 作成: style.css / main.js のアーカイブコピー
  - design/README.md / design/V1/README.md 追加
- **design/V1/ に静的HTMLアーカイブ追加**（コミット `d2a9a1f`）
  - about / contact / privacy / terms の V1 スナップショット保存
- **ルートのゴミファイル3本 dustbox 退避**（コミット `30edffb`）
  - crawl.yml（旧ワークフロー）/ fish_raw_list.txt / turimono_list_raw.txt
- **crawler.py: design_version 自動同期**（コミット `106ab37`）
  - config.json に `"design_version": "V1"` 追加
  - crawler.py 実行時に design/{design_version}/ の HTML/CSS/JS をルートへコピー
  - V2 移行は config.json の design_version を変えるだけで完結
- **pages/ フォルダ新設・静的HTML移動**（コミット `eb904ba`）
  - about / contact / privacy / terms → pages/ へ移動
  - 各HTML: 相対パスを ../ 補正
  - crawler.py: フッター/ナビ/サイトマップのリンクを pages/ 向けに更新
  - デザイン同期の HTML 出力先を pages/ に変更（CSS/JS はルート維持）

### 現在のルート構成
```
kanto-fishing/
├── CLAUDE.md / PIPELINE.md / README.md / CNAME / config.json / .gitignore
├── crawler.py
├── catches_raw.json / catches.json / history.json / forecast.json
├── index.html / calendar.html / sitemap.xml / robots.txt
├── main.js / style.css
├── pages/          ← 静的ページ（about/contact/privacy/terms）
├── fish/ / area/ / forecast/
└── [フォルダ] crawl/ ocean/ normalize/ data/ analysis/ design/ dustbox/
```

### config.json 現状
```json
{
  "active_version": "V2",       ← data/V2/ CSV に連動
  "design_version": "V1",       ← design/V1/ → pages/ & root に同期
  "versions": { ... }
}
```

### デザイン移行フロー（V2 移行時）
1. design/V2/ に全ファイル完成させる（style.css / main.js / about.html 等）
2. config.json の `"design_version": "V2"` に変更
3. crawler.py 実行 → 自動でルート・pages/ に反映

---

## ✅ 前セッション完了（2026/04/08 前半）
- **catches_raw_direct.json → CSV 統合**（crawler.py v5.22 / `ce35b3d`）
- **大掃除 Phase 3〜4d 完了**（normalize/・analysis/ 整備）

---

## 確定した設計方針（変更不可）

### FISH_MAP → 廃止決定（2026/04/09確定）
- **不要**: `tsuri_mono + main_sub` で同等のフィルタが可能
- 分析クエリは `tsuri_mono = "アジ" AND main_sub = "メイン"` で行う
- サブ魚種クロス集計が必要になったときに再検討

### ships.json フィールド（2026/04/03更新）
- `exclude: true` → 利一丸・岩崎レンタルボート・海上つり堀まるや（3件）
- `boat_only: true` → 青木丸（1件）
- 有効船宿: 75件＋静岡エリア多数

### データ収集状況（2026/04/03時点）
- catches_raw.json: **84,757件**（欠航893件含む）
- data/YYYY-MM.csv: **82,481行**
- point_place1あり: **36,553件（44.8%）** kanso補完後
- 期間: 2023/01/01〜2026/04/03

### ポイント解決（3段階フォールバック・完全実装済み）
```
① point_place1 → point_coords.json（306ポイント）→ 座標
② 空/航程系 → ship_fish_point.json（73船宿）→ ポイント名 → 座標
③ ② も未登録 → area_coords.json（58エリア）→ 直接 lat/lon
```
- resolve_point() 関数で実装済み（crawler.py）
- _extract_point_from_kanso() で kanso_raw からもポイント名補完（+630件）
- 解決率: **94.9%**（除外船宿を除く）

### ポイント解決ファイル現状
| ファイル | 件数 | 内容 |
|---------|------|------|
| point_coords.json | **306ポイント** | ポイント名→座標（エイリアス含む） |
| ship_fish_point.json | **73船宿** | 船宿×魚種→ポイント名（②フォールバック） |
| area_coords.json | **58エリア** | 港エリア名→代表沖合座標（③フォールバック） |

### 価格・マネタイズ
- **月額500円 / スポット100円**
- 無料=事実、有料=分析+予測

---

## 後回し・未実装
- [ ] 決済連携（Stripe等）
- [ ] AdSense審査結果待ち（2026/03/21申請済み）
- [ ] X自動投稿（アカウントロック解除待ち）
- [ ] crawl.ymlのNode.js 20→24アップグレード
