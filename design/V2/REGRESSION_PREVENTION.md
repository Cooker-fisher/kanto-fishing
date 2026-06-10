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
| 22 | `fish/*.html` サンプル（aji/shirogisu/tachiuo/madai）（T29） | area_cmp 内に `class="ar-fa"` を持つ fish_area への詳細リンク存在。全件 area_cmp なしの場合は warn 格上げ |
| 23 | `fish_area/*.html` サンプル（aji-yokohama-honmoku/madai-iioka/aji-kanazawa-hakkei）（T29） | FAQ 直前に `class="fa-related"` セクション + 内部に `class="chip-link"` 1件以上（fish_area 同士の相互リンク） |
| ※ | — | #24〜#33 は T38 系で `validate_output.py` 側に存在（実装先行・本表未掲載・別タスクで追記予定） |
| 34 | 全 `docs/**/*.html`（2026-05-21） | `href` の値が `index.html` で終わる内部リンクが 0件（正規表現 `href=["'][^"']*index\.html["']`）。GitHub Pages Fastly CDN の root + 全 subdir レベルキャッシュキー別問題対策・内部リンクから `index.html` 末尾を完全排除 |
| 35 | `fish_area/*.html`（T39 / 2026-05-25） | noindex 付与ページが 10 件以上（薄判定が動作している証拠）+ noindex 付与済ページの URL が `sitemap.xml` に含まれない（AdSense「有用性の低いコンテンツ」対策・hist_count < 30 のコンボを noindex） |
| 36 | `area/*.html`（T40 / 2026-05-26） | build_point_pages() 生成ポイントページ（釣り場ポイント情報マーカー）の noindex 付与が 5 件以上 + noindex 付与済ページの URL が `sitemap.xml` に含まれない（fia-grid/season-map を持たない構造的薄ページ・40件全件 noindex） |
| 37 | `docs/fish/*.html`（T41 / 2026-06-07） | 魚種ガイドの仕掛け説明に他魚種の道具混入が無いこと。マグロ系以外のページに「キハダマグロ針」「マグロ針」が出たら誤情報として fail。ヒラメページに「ウキ（状況で可変）」混入も fail（`fish_tackle.json` 泳がせ系テンプレ汚染対策・ヒラメ等の活き餌仕掛けがマグロ用道具で生成されていた） |
| 38 | `docs/fish/*.html`・`docs/fish_area/*.html`・`docs/ship/*.html`（T41 / 2026-06-07） | 「最高(実績は)N匹」「最大匹数 N匹」「平均(釣果)N匹」「平均X〜N匹」の N が西暦域 [1990,2035] または 1500 超でないこと（小数可）。実在最大は数物でも 1000 未満（アジ713・スジイカ702）。西暦誤抽出（ヒラメ「2025匹」）・桁化け・外れ値混入の平均（ヒラメ「平均507.2匹」）を弾く。ship ページも公開生成物なので対象（PR#51/#52 レビュー指摘で追加）。crawler.py `_FISH_CNT_CAP` を ship 集計の全経路（`_ship_load_yearly_summary`/`_ship_load_seasonal_fish`/`_ship_load_monthly_archive` の cnt_max・cnt_avg 収集）に `_is_plausible_cnt` 適用して担保（外れ値が max/avg を汚染しない） |
| 39 | `docs/index.html` + 全ページ共通バナー（T42 / 2026-06-07） | (1) index.html の「最終更新: YYYY/MM/DD」が today-2 以内（トップの更新遅延検知）。(2) 全ページ共通ヘッダ（`_v2_header_nav`）のビルド日付バナー `var b="YYYY-MM-DD"` が today-2 以内（ページ種別ごとの再生成漏れ＝更新分裂の検知）。バナーは CDN/ブラウザキャッシュで古い版を見た閲覧者にもクライアント側 JS で「更新遅延」を表示する（生成日 vs 当日を比較、2日以上で表示）。旧 docs はバナー未導入のため skip（次回再生成で有効化） |
| 40 | `docs/favicon.ico` + `docs/apple-touch-icon.png` + 主要ページ（2026-06-10） | favicon ファイル 2 件が存在（0 byte 不可）+ 主要ページ（index/calendar/fish/area/fish_area/ship/forecast/pages サンプル）の `<head>` 内に `rel="icon"` タグ存在。既存画像流用（フグ emoji → favicon.ico 16/32/48px・アオリイカ illustration → apple-touch-icon 180px・新規作画なし）。crawler.py の全 head テンプレート 15 箇所 + pages/*.html 5 件に挿入済み・テンプレート追加/改修時の favicon 落ちを検知 |
| 41 | `docs/` `area/` `fish/` `fish_area/` `ship/` 全 HTML（2026-06-10） | 魚種名「NULL」が露出していないこと（`>NULL<`・`NULL（`・`alt="NULL"`・`assets/fish/NULL/` を検知）。chowari 系 CSV の tsuri_mono="NULL"（正規化失敗 sentinel）が area ページの fia-grid/旬カレンダー/meta description/FAQ に魚種として露出したバグ対策。crawler.py は `_load_historical_catches()` で読み込み時 "NULL"→"不明" 正規化 + 表示系 skip set に "NULL" 追加で担保 |
| 42 | `crawl/ships.json` + `docs/sitemap.xml`（2026-06-10） | ships.json の `romaji_slug` が全船宿で一意 + sitemap.xml に重複 URL なし。弘漁丸/孝漁丸が同一 slug "koryo-maru" で ship ページを相互上書きし片方が消失していたバグ対策（弘漁丸 → koryo-maru-hitachi に変更） |
| 43 | `docs/ship/*.html`（2026-06-10） | `tel:` リンクの数字が 12 桁以下であること。ships.json の複数番号入り phone（"0463-... / 070-..."）を区切り文字ごと数字化して連結し、23 船宿ページで無効な発信先になっていたバグ対策。crawler.py `_first_phone_for_tel()` で先頭 1 番号のみ使用 |
| 44 | 全 `docs/**/*.html`（2026-06-10） | `fish/` `fish_area/` `ship/` への内部リンクが実在ファイルを指すこと。fish_area 孤児パージ後にリンク元 stale ページが残留しデッドリンク化（244 ターゲット・550 参照）していたバグ対策。crawler.py は生成完了後に `_sweep_dead_internal_links()` で毎回 `<a>`→`<span>` 変換（属性保持・href 除去） |

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

### ローカル crawler.py 再実行（2026-05-22 追加）
- **ローカルで `python crawler.py` を実行する前に必ず `git pull` する。**
- 理由: GitHub Actions が catches.json / docs/ を更新した後にローカル古い catches.json で `crawler.py` を再実行すると、`_resolve_display_dataset` が `max(dates)` フォールバックで古い日付を選び、`docs/index.html` の HERO 表示日が**巻き戻る**。実例: 5/21 23:11 の手動 commit が、5/21 20:01 Actions の「5/21(木) 釣果」表示を「5/19(火) 釣果」に上書きした（決定ログ 2026-05-22）。
- **HTML の文字列置換だけが目的**（リンク変換・URL置換など）なら `crawler.py` を実行せず、`sed` または独立した Python script で `docs/` を直接書き換える。
- crawler.py のロジック変更を反映したいケースでは: `git pull` → `python crawler.py` → `python crawl/validate_output.py` → commit & push の順を厳守。
- クロール結果だけ最新化したいケースは GitHub Actions の workflow_dispatch を使う（ローカル `crawler.py` を回さない）。

---

## 開発者向けチェックリスト

新しい HTML 生成・改修を行う前に:

- [ ] `design/V2/90_決定ログ.md` の該当セクションを読んだ
- [ ] 本ドキュメントの設計契約を読んだ
- [ ] **ローカルで `crawler.py` を実行する場合は事前に `git pull` した**（2026-05-22 追加）

実装後・コミット前に:

- [ ] `python crawl/validate_output.py` がローカルで全 PASS（errors=0）
- [ ] 「閾値を緩めて gatekeeper を黙らせる」修正をしていない
- [ ] 新しい regression を発見したら不変条件を追加し決定ログを更新
- [ ] 失敗を抑制する `--warn-only` を CI に組み込もうとしていない
- [ ] **`crawler.py` 再実行を伴う commit の場合、`docs/index.html` の `<div class="updated">` 日時が現在時刻に近い・HERO 日付ラベルが catches_raw 最新日に近いことを目視確認**（2026-05-22 追加）

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
