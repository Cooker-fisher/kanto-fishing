現行バージョン: crawler.py v5.22（catches_raw_direct.json → CSV統合）
最終更新: 2026/04/08
最新コミット: ce35b3d

---

## ★ 次チャットでやること（優先度順）

### 1. combo_deep_dive.py を全51魚種で実行（ユーザー許可が必要）
- tide fix済み（tide_moon.sqlite参照に変更・コミット済み `72b7743`）
- 実行前にユーザーに確認してから走らせること

### 3. parse_deepdive.py → deepdive_params.json
- combo_deep_dive 完了後に実行

### 4. 売り物設計（予測の出力形式）
- 現状MAPE 27〜55%（CVが低い船宿）→ 匹数絶対値ではなく「平年比±%」「★評価」で出す
- 「来週末アジは平年比+25%（★★★★）」の形式が現実的
- 要実装: 旬別ベースラインからの偏差率を★5段階に変換するロジック

## ✅ 今セッション完了（2026/04/08）
- **catches_raw_direct.json → CSV 統合**（crawler.py v5.22 / `9087b76`）
  - `export_csv_from_raw()` 冒頭で `direct-crawl/catches_raw_direct.json` をマージ
  - trip_no を ship+date 内で連番付与（same_trip_records 分離）
  - size_raw / weight_raw を count_raw から補完（full-width ｃｍ/ｋｇ 対応）
  - `_extract_time_slot()`: 「午前・午後」併記 → ""（時間帯不定）
  - テスト結果: 108件→108行CSV出力、tsuri_mono/cnt/size/kg すべて正常抽出

## ✅ 前セッション完了（2026/04/07）
- **gyo_crawler.py 新規作成** (`direct-crawl/gyo_crawler.py`)
  - 忠彦丸（table形式）・一之瀬丸・米元釣船店（freetext形式）対応
  - 出力: `direct-crawl/catches_raw_direct.json`（15フィールド・catches_raw.jsonと同一構造）
  - 初回108件取得（忠彦丸5 / 一之瀬丸82 / 米元21）
  - FISH_MAP不使用・stdlib only・dedup: (ship, date, fish_raw)
  - Table B（タックル情報）→ kanso_rawに連結済み
  - 非釣果セクション（お知らせ・アクセス・BBQ等）→ _NON_FISHINGフィルターで除外済み
  - 日付はhistory URLのhdtパラメータから確定（HTMLコンテンツ内日付パース不要）
- **crawl.yml に統合**
  - `crawler.py` の後に `gyo direct crawl` ステップ追加（`continue-on-error: true`）

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
- 最新コミット: `8a2fb00`

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
