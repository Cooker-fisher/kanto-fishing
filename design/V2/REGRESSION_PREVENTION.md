# 破壊防止規約（gatekeeper 11不変条件）

このドキュメントは `90_決定ログ.md` の「2026-05-01 データ消失 regression 防止策」
セクションのクイックリファレンスです。詳細・経緯は決定ログを参照。

**SoT（唯一の真実）:** `design/V2/90_決定ログ.md` の該当セクション

---

## 過去発生した regression（同じことを繰り返さない）

| 症状 | 根本原因 | commit |
|---|---|---|
| fish/index.html が 1〜2 種だけ | `--html-only` が catches.json (sparse) で全 HTML 再生成 | 既修正 |
| area/index.html が 2 エリアだけ | 同上 | 既修正 |
| data/V2/2026-04.csv が 4/24 で停止（4/25〜30 喪失） | `--export-csv` が stale catches_raw.json から CSV 全再生成 → save_daily_csv 追記分を毎日 wipe | adb48efb |
| ホームページ ZONE B ミニバー 7日中 6日空 | `_load_recent_catches_for_index` が count_range 返さず | fabe3704 |
| area 旬カレンダーが全セル空 | `build_area_season_map_html` が analysis.sqlite (gitignore) に依存 | 88ad038f |
| area fia-grid card に 匹数·サイズ無し | CSV 列名 (`cnt_min` スカラー) で読んでた・実際は dict | cff3e67a |
| fish ページ 7日チャート 今日1本のみ | `build_fish_pages` が当日 sparse data のみ使用 | c8921178 |
| マダイとワラサで HERO レイアウト分岐 | placeholder が `<div class="c">` wrapper / `fh-sub` で別構造 | f53abba9 |
| 「◎弁天屋」が phantom card 化 | fia (`<a>`) 内に `_ship_link()` (`<a>`) ネスト → 自動分離 | 1f79de90 |

---

## 11 不変条件（CI で必ず検証）

実体: `crawl/validate_output.py` / 違反時 push 阻止

| # | チェック | 閾値 |
|---|---|---|
| 1 | `index.html` | 魚種カード ≥ 5・HERO 件数 > 0 |
| 2 | `fish/index.html` | 釣果あり魚種 ≥ 5・総数 ≥ 20 |
| 3 | `area/index.html` | 釣果ありエリア ≥ 5・ai-card ≥ 10 |
| 4 | `calendar.html` | 月別カード ≥ 12 |
| 5 | 当月 `data/V2/YYYY-MM.csv` | 最新日付 today-2日以内（月初3日緩和） |
| 6 | `catches_raw.json` | ≥ 50,000件 |
| 7 | `area/*.html` 旬カレンダー | 空セル(`data-v=-1`) < 50% |
| 8 | `area/*.html` fia-grid | card あり・匹数 or サイズ含む |
| 9 | `fish/*.html` 直近7日チャート | 7本中 6本以上 height≤8% でない |
| 10 | `fish/*.html` HERO 統一 | fish-hero 直下が `<h2>`・古い `fh-sub` / `<div class="c">` 無し |
| 11 | 全 `docs/*/*.html` | ネストアンカー (`<a>...<a>`) 無し |
| 12 | `area/*.html` 海況セクション | 潮汐が名称（大潮/中潮等）・月相が名称（満月/新月等）・1行コメント有り |
| 13 | `forecast/index.html` | `<meta name="robots" content="noindex">` 存在（T22-H1 暫定対応・T23 で実コンテンツ化後に解除） |
| 14 | `ship/*.html` | noindex 付与ページが 1 件以上（T22-H2 が動作している証拠） |
| 15 | `pages/faq.html` | ファイル存在 + 本文 800 字以上（T22-M1 共通 FAQ 切り出し先） |
| 16 | `fish/*.html` サンプル | 共通 FAQ 見出し『船釣り共通の基礎知識』が消滅 + `/pages/faq.html` リンク存在（T22-M1） |
| 17 | `fish_area/*.html` サンプル | intro 冒頭にエリア固有文（位置/県/湾/外房/内房/面し/市/町 のいずれか含む 10 字以上）（T22-H3） |
| 18 | `sitemap.xml` | `forecast/` URL が含まれない（T22-H1 sitemap 除外） |
| 19 | 全主要HTML（index・calendar・fish/\*・area/\*・fish_area/\*・ship/\*・fish/index・area/index） | `og:image` + `twitter:card` + `twitter:site` 全て存在（X 手動投稿時のリッチカード描画保証） |
| 20 | index・fish/\*・area/\*・fish_area/\*・ship/\*・x_post/YYYY-MM-DD | `class="share-bar"` + `twitter.com/intent/tweet` リンクあり（ユーザー側拡散経路） |
| 21 | `area/*.html` サンプル（T31） | 共通 FAQ 見出し『船釣り共通の基礎知識』が消滅 + `/pages/faq.html` リンク存在 + Q2 アクセス文章に「最寄りIC」「最寄り駅」キーワード含む（hist_rows ベース固定文章化） |
| 22 | `fish/*.html` サンプル（T29） | area_cmp が存在するページで `class="ar-fa"` リンクが含まれる（fish_area への内部リンクで孤立解消） |
| 23 | `fish_area/*.html` サンプル（T29） | FAQ 直前に `class="fa-related"` セクション存在 + 内部に `chip-link` 1件以上（fish_area 同士の相互リンクで孤立解消） |

### T22 関連の設計契約（H1 noindex 解除手順）

T23（forecast/index.html 実コンテンツ化）完了時に以下をセットで反転する。手順を T23 着手前に必ず確認すること:

1. `crawler.py` `_forecast_page_head()` の `<meta name="robots" content="noindex, follow">` 削除
2. `build_sitemap()` に forecast/ URL 列挙を追加（現状未収録）
3. `validate_output.py` 不変条件 13・18 を反転（noindex タグが **存在しない** こと、sitemap に forecast/ が **含まれる** ことを検証）
4. `REGRESSION_PREVENTION.md` の本テーブル 13・18 を更新
5. `90_決定ログ.md` に T23 完了記録を追記

---

## 設計契約（破ってはいけないルール）

### データフロー
- `data/V2/*.csv` は append-only。`save_daily_csv()` が dedup 追記する
- 手動再生成は `FORCE_EXPORT=1 python crawler.py --export-csv`（鮮度ガード解除）
- `catches.json` の `data` はスナップショット (today-only sparse)。**HTML 生成元として使うな**
- `_load_recent_catches_for_index()` は valid_catches 互換（dict）で返す。CSV スカラー禁止

### HTML レイアウト
- fish ページ HERO は1種類のみ:
  ```html
  <div class="fish-hero">
    <h2>{魚種}</h2>
    <div class="fh-r">{今週N件範囲 or 過去1年N件}</div>
    <div class="fh-m">{今日 N件・M船宿 or 本日の釣果報告は集計待ち}</div>
  </div>
  ```
- `<div class="c">` wrapper / `fh-sub` クラスは禁止（古い placeholder 形式）
- `<a>` 内部に `<a>` をネストするな（HTML5 invalid）
- fia card 内の船宿名はプレーンテキスト（`_ship_link` を呼ばない）

### 当日 sparse 時の振る舞い
- 当日 fish 認識済 < 30件 のとき:
  - ホームページ ZONE B/B2 → 7日窓に切替・ラベル「直近1週間」
  - fish ページ 7日チャート → CSV 由来の過去6日を merge
- HERO 件数 / LIVE ティッカーは当日セマンティクス維持
- area「魚種別 旬カレンダー」は analysis.sqlite 無くても SEASON_DATA フォールバックで描画

### CI
- `crawl/validate_output.py` の crawl.yml 組込を外すな
- gatekeeper を回避する変更は禁止
- 新規 regression 検出時: 修正 + 新不変条件追加 + 決定ログ更新 を必ずセットで行う

---

## 開発者向けチェックリスト

新しい HTML 生成・改修を行う前に:

- [ ] `design/V2/90_決定ログ.md` の該当セクションを読んだ
- [ ] 本ドキュメントの設計契約を読んだ

実装後・コミット前に:

- [ ] `python crawl/validate_output.py` がローカルで全 PASS（errors=0）
- [ ] 「閾値を緩めて gatekeeper を黙らせる」修正をしていない
- [ ] 新しい regression を発見したら不変条件を追加し決定ログを更新
- [ ] 失敗を抑制する `--warn-only` を CI に組み込もうとしていない

---

## 主要ファイル

| ファイル | 役割 |
|---|---|
| `crawl/validate_output.py` | 11 不変条件の検証 gatekeeper |
| `.github/workflows/crawl.yml` | CI に validate_output 組込・`--export-csv` を含めない |
| `crawler.py` `_load_recent_catches_for_index` | 過去7日 records を CSV から復元（dict 形式・count_range/size_cm 含む） |
| `crawler.py` `build_html` / `build_fish_pages` | sparse 検知 + 7日窓フォールバック |
| `crawler.py` `build_area_season_map_html` | SEASON_DATA フォールバック |
| `crawler.py` `export_csv_from_raw` | 鮮度ガード（FORCE_EXPORT で override） |
| `design/V2/90_決定ログ.md` | SoT・経緯・不変条件契約 |
| `design/V2/REGRESSION_PREVENTION.md` | 本ファイル（クイックリファレンス） |
