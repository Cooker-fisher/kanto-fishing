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
| 13 | `forecast/index.html` + 日付ページ（T23 / 2026-07-03 反転） | ハブ `forecast/index.html` に noindex が **無い**（index 解除済み）+ 日付/週の個別ページ（サンプル最大5件）は noindex **維持**。D層予測が distilled_full（439コンボ）化しハブが「今週の海況＋魚種別予測」の実コンテンツになったため。個別ページは変動が激しく薄いので noindex 継続 |
| 14 | `ship/*.html` | noindex 付与ページが 1 件以上（T22-H2 が動作している証拠） |
| 15 | `pages/faq.html` | ファイル存在 + 本文 800 字以上（T22-M1 共通 FAQ 切り出し先） |
| 16 | `fish/*.html` サンプル | 共通 FAQ 見出し『船釣り共通の基礎知識』が消滅 + `/pages/faq.html` リンク存在（T22-M1） |
| 17 | `fish_area/*.html` サンプル | intro 冒頭にエリア固有文（位置/県/湾/外房/内房/面し/市/町 のいずれか含む 10 字以上）（T22-H3） |
| 18 | `sitemap.xml`（T23 / 2026-07-03 反転） | forecast ハブ `/forecast/` を **収録** + 日付/エリアの個別ページ（`forecast/YYYY-MM-DD.html`・`forecast/area/`）は **非収録**。build_sitemap の forecast 走査は head の noindex 検出でハブだけを拾う（area/fish_area と同パターン） |
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
| 45 | `docs/fish/*.html`（2026-06-11） | `normalize/fish_content.json` 収載魚種のページに固定文セクション（`class="fish-content-text"`）が 4 ブロック以上 + 合計 800 字以上 + 未解決プレースホルダ（`{xxx}`）なし。魚種ページ固定文プロジェクト（固定文=月1見直し・数値=`fish_content_stats.json` 月1スナップショット差し込み）。数値の毎日再計算は固定プローズとの乖離リスクがあるため月1方式（`crawl/build_fish_content_stats.py`） |
| 46 | `docs/x_post/*.html`（2026-06-13） | 公開ページに運営者専用の X 投稿文ドラフトが混入していないこと。マーカー（`X投稿文`・`x-drafts`・`コピー用・発見型`・`翌朝8時投稿想定`・`リーチを抑制`・`リンクなしをコピー`・`xd-copy`）が 1 つでも出たら fail。`x_post/build_daily_page.py` が下書きツイート＋投稿戦略の運用メモを公開 HTML に `<details class="x-drafts">` で埋め込み funatsuri-yoso.com 上で一般公開していた不具合の是正。運営者ドラフトは GitHub Pages 非配信かつ `.gitignore` 済みの `x_post/drafts/{date}.txt` にのみ出力する |
| 47 | 全 `docs/**/*.html`（2026-06-16） | noindex 付与ページに AdSense 実広告コード（loader script `pagead2.googlesyndication.com/pagead/js/adsbygoogle.js` / ad ユニット `<ins class="adsbygoogle"`）が無いこと（CSS 定義 `ins.adsbygoogle{}`・`.ad-slot{}` は無害なので除外）。AdSense「有用性の低いコンテンツ」再対策＝「インデックスされない薄ページは収益化しない」で AdSense bot が薄判定する広告掲載ページの母集団を縮小。crawler.py の広告ゲート（forecast/fish_area/ship head の `{'' if noindex else ADSENSE_TAG}` + ship body の `_SHIP_AD_RECT`/`_SHIP_AD_INS` 条件出力）と遡及 sweep の両方で担保。あわせて fish_area の noindex しきい値 `_FA_NOINDEX_HIST_THRESHOLD` を 30→80 に引上げ（#35 と連動） |
| 48 | 全 `docs/**/*.html`（2026-06-16・SEO） | ヘッダのサイト名「船釣り予想」が `<h1>` でないこと（`<h1>…船釣り<span>予想` 形を検出したら fail）。各ページの `<h1>` はそのページの主題にする方針。ロゴは `<span class="brand">`（CSS `header .brand`）。crawler.py `_v2_header_nav`・ship ヘッダ・x_post `build_daily_page.py`・静的 `pages/*` でブランドを非見出し化し、index/area/fish_area/calendar/各index/forecast に主題 H1 を付与（fish/ship/monthly/404 は既存維持） |
| 49 | `data/V2/chowari_*.csv`（2026-07-03） | 完了した直近2か月の chowari 月次 CSV が「窓化」していないこと（200行以上の月は 日付15種以上 + 月初5日以内のデータ必須）。chowari_crawler の per-ship raw JSON は直近7日窓で全上書きされるため、旧 chowari_to_csv（全上書き方式）が月初〜中旬の蓄積行を毎日破壊していた（2026-06 が月末に475行/6日分に縮小・2026-03〜06 で計16,482行を git 履歴から復元）。chowari_to_csv は既存 CSV との dedup union 方式（キー: ship/date/trip_no/fish_raw・縮小時 AssertionError）に修正済み。決定ログ「2026-07-03」参照 |
| 50 | `docs/fish_area/*.html`・`docs/ship/*.html`（T43 / 2026-07-03） | C層蒸留『海況と釣期の傾向（データ分析）』セクションの整合。`normalize/fish_area_analysis.json` が存在し 1件以上のとき、fish_area で見出し『海況と釣期の傾向（データ分析）』を持つページが最低数（min(30, JSON件数/6)）以上レンダされ、**分析セクションを持つ全ページに免責注記（『釣果を保証するものではありません』＋『この海域のデータに基づく』）がある**こと（過大表現＝AdSense/信頼リスクの防止）。禁止表現（『必ず釣れ』『確実に釣れ』『絶対に釣れ』）が出ないこと。蒸留元 analysis.sqlite は gitignore（CI不在）のため `crawl/build_fish_area_analysis.py` がコミット済み JSON に蒸留し crawler.py はそれを読む。方向（多い/少ない）は r 符号由来で因果は断定せず、「この海域の過去データでは」でコンボ限定。危険因子（typhoon_dist=生存バイアス/wave_clamp=逆U字/do系=疑似相関/moon_age=周期/tide_type_n=順序尺度）は `factor_labels.json` で surface=false（domain レビュー裁定）。複数船宿分析（n_ships>=2）かつ hist>=`_FA_RICH_HIST_MIN`(40) の薄hist ページは index 復帰（`_FA_RICH_INDEXED_SLUGS`）。決定ログ「2026-07-03 T43」参照 |
| 51 | `docs/fish-value/`＋`docs/index.html`＋`docs/sitemap.xml`（2026-07-05） | 釣果価値チェッカーのリリース整合。(1) `fish-value/index.html` に noindex が**無い**（リリース済み）(2) `docs/index.html` に `/fish-value/` 導線あり（gnav＋トップカード）(3) `sitemap.xml` に `/fish-value/` 収録 (4) 価格マスタ鮮度: `fish-price-master.json` の `seasonal.data_month` ラグが3か月超で warn（`urls_manifest.json` への新月報追記漏れ検知・月報公開ラグにより正常時1.5〜2.5か月）(5) **日報ハイブリッド鮮度**: `daily_correction` ブロックがあるとき `asof` が14日超で warn（週次 `fish-value-daily.yml` 停止検知・日報オンリーで全魚 fallback は非ブロッキング）。fish-value は crawler.py 非生成の独立アプリのため、導線・sitemap は crawler.py 側（gnav/カード/build_sitemap）が SoT。価格は月報（wholesale.yml 月次）＋日報（fish-value-daily.yml 週次）のハイブリッドで、両ワークフローとも crawl.yml（釣果）と独立。決定ログ「2026-07-05」参照 |
| 52 | 全 `docs/**/*.html`＋`docs/pages/about.html`（AdSense フェーズ1 / 2026-07-07） | 未完成ペイウォールシグナルの排除＋運営者情報。AdSense「有用性の低いコンテンツ」4連敗の一因＝未完成の課金機能（有料プランナビ・月額500円・公開準備中）が「site under construction」シグナルになり、かつマネタイズ方針（2026-06-10「予測は当面無料公開」）とも矛盾。`SHOW_PAID_TEASER=False` の間: (a) 全 docs にナビの有料リンク（`href="/forecast/" class="prem"`）が **0**（`_v2_bottom_nav`/ship系ヘッダ/`_page_nav`/x_post ナビの全ナビ出力をゲート）(b) index・fish・area・fish_area・ship・monthly・pages の主要 indexed ページに「月額500円」「公開準備中」が **無い**（forecast ハブ・about・contact・terms の課金文言を「現状すべて無料・将来未定」に統一）(c) x_post 公開ページに機械文バグ「以降以降」「kgkg」が **無い**（`x_post/templates.py` H1 の `{period_label}以降`→`{period_label}`・`{kg_threshold}kg超え`→`{kg_threshold}超え` 二重付与修正）(d) about に運営者プロフィール（見出し『運営者について』＋『運営者本人が設計・確認』の人手キュレーション明示＝E-E-A-T＋自動化利用の開示）がある。**除外**: 「有料駐車場」「有料道路」等はアクセス解説の正当表現（ナビ/課金 CTA のみ検知）。**Phase2 対象外**: forecast 日付ページ（noindex・広告なし・101件）の blur teaser（月額500円/有料プラン）は forecast 製品ページ別サブシステムのため未対応・`premium/plan.html`（製品ページ・1件）は意図的保持。決定ログ「2026-07-07」参照 |
| 53 | `docs/forecast/*.html`＋`normalize/open_tier.json`（T47b / 2026-07-17） | 検証済み予測のティア整合。(a) open_tier.json が存在し tier A ≥30組（蒸留漏れ検知） (b) 日付ページのレンジ表示コンボ ⊆ tier A（選別バイパス検知） (c) 日付ページに「月額500円」「有料プラン」が無い（旧ペイウォール teaser 撤去済み・#52 Phase2 完了） (d) 全日付ページが更新待ち表示なら warn（forecast_daily.json 鮮度切れ検知）。forecast 日付/週次ページの予測カードは crawler.py 内蔵モデル（精度未検証）から検証済みモデル（前日CIコミットの forecast_daily.json × open_tier tier A・週次は weekly_ok 必須）に差し替え。build_forecast_pages が過去の日付/週次ページを毎回掃引（旧文言・未検証予測の残留防止）。運用: 全再実行後は build_predict_params.py と build_open_tier.py の両方をローカル実行してコミット |
| 54 | `normalize/fish_area_notes.json`＋`docs/fish_area/*.html`（Tier2 / 2026-07-18） | fish_area 編集部ノート（非count 固有文）の整合。**背景**: count 分析が原理的に立たない fish_area（外道主体＝メイン釣果がほぼ無い／静岡ソースが魚種名のみで釣果数値なし）は、データ充実（hist>=80）でも近重複テンプレとして GSC に品質拒否される（決定ログ 2026-07-18 GSC 実査）。`normalize/fish_area_notes.json` に**便レベル共起**（主対象か外道か・どの乗合で交じるか＝`data/V2` CSV から検証）と旬から導いた honest な固有文を置き、`crawler.py _build_fish_area_notes_section` が『この海域の{魚種}釣り』を intro 直後に描画。検証: (a) notes JSON が存在し1件以上（無ければ skip）(b) 各ノート html 非空・キーが「魚種\|エリア」形式・禁止表現（『必ず釣れ』『確実に釣れ』『絶対に釣れ』『保証します』）が html に無い (c) `class="fa-note"` を含む描画済み docs は免責注記『釣果を保証するものではなく』を含み禁止表現が無い（docs 未再生成時は vacuous pass・日次 crawl 後に実効）。反映は日次 crawl.yml のフルクロールが本JSONを読んで再生成する経路（ローカル crawler.py フル実行は HERO 日付巻き戻しリスクで回避）。パイロット5＝ハナダイ×鹿島港・ハタ×御前崎港・カサゴ×大原港・アジ×福田港・マハタ×鹿島港。domain レビュー済み。決定ログ「2026-07-18 Tier2」参照 |
| 55 | `docs/x_post/*.html`（2026-07-19） | 日次まとめの「0匹」矛盾表示の排除。**背景**: 型（cm/kg）が記録されている＝釣れている魚でも匹数が未抽出だと cnt_max=0 になり、テーブル/散文が「0匹」と矛盾表示していた（例: シイラ 0匹 113〜122cm・カンパチ 0匹 3.5〜7.5kg）。`build_daily_page._fish_table_rows_html`/`_x_card_table_rows_html` は cnt_max 未記録時に「—」へ、`context_builder` は `{key}_cnt_range` を空にし型併記テンプレ用に `{key}_cnt_seg`（非空なら「…匹・」）を新設、`templates.py` の kanpachi/kawahagi/madai/fugu/tachiuo を cnt_seg 化。検証: docs/x_post/*.html に `<div class="catch">0匹</div>`・`<span class="xc">0匹</span>`・`で0匹`・`0匹台` が無いこと。過去75ページは再蒸留スイープ、データ欠落4ページは機械置換で是正。決定ログ「2026-07-19」参照 |
| 56 | `docs/x_post/*.html` 最新1枚（2026-07-22） | 日次まとめ散文の**数値根拠**。**背景**: ハイライト／魚種別報告が `templates.py` の H/F 文型依存で「今期は好海況が観測されています」「再現性が高いと推察されます」「組み込みやすい魚種です」等の根拠なしフィラーが本文の大半だった（ユーザー指摘「薄っぺらい」）。裁定＝フィラー全廃・数値根拠のみ。`x_post/insights.py` が **data/V2 CSV のみ**（analysis.sqlite は .gitignore で CI 不在）から平年比（過去3年の同旬 cnt_max 中央値比・母数併記）・船宿別上位3便・記録性（N日ぶり／直近60日で最多）を算出し、`x_post/narrative.py` が散文とカード（最大4枚）を生成。翌日の予測引用は #53 と同じ関門（tier A かつレンジ有り）のみ。検証（最新1枚のみ・`class="commentary evidence"` を持つページに限る。旧ページは CSV 由来だと数値が変わるため遡及再生成しない）: (a) 禁止フィラー（`と推察されます`/`好海況が観測されています`/`再現性が高い`/`組み込みやすい魚種です`/`好スコア`/`予定通り運航しました`）が無い (b) 「平年比」の記述には母数「同じ旬（N便）」が併記される (c) 「最多は…」の船宿別記述がある。(b)(c) はフォールバック日を考慮し warn 止まり。決定ログ「2026-07-22」参照 |

### T22 関連の設計契約（H1 noindex 解除手順）→ ✅ T23 完了（2026-07-03）

以下の5点セットを実施済み（詳細は `90_決定ログ.md`「2026-07-03 T23 forecast ハブ index 解除」）:

1. ✅ `crawler.py` `_forecast_page_head(noindex=True, canonical, description)` を追加。ハブのみ `noindex=False`
   で呼び出し（`_build_forecast_hub`）。日付/週/エリア個別ページは既定 `noindex=True` を維持
2. ✅ `build_sitemap()` に forecast 走査を追加（head の noindex 検出でハブ `/forecast/` のみ収録）
3. ✅ `validate_output.py` 不変条件 13・18 を反転（ハブは noindex なし＋日付ページは noindex 維持 / sitemap は
   ハブ収録＋個別ページ非収録）
4. ✅ 本テーブル 13・18 を更新
5. ✅ `90_決定ログ.md` に T23 完了記録を追記

**設計判断**: ハブ限定 index（日付/週/エリアは noindex 維持）。理由=(a) 個別ページは日次で変動し薄い、
(b) `_forecast_page_head` は ADSENSE_TAG を出さない → ハブは **indexed だが非収益化**（AdSense 薄収益化ページを
増やさない・再審査リスク最小）、(c) マネタイズ方針（2026-06-10）で予測は当面無料公開＝集客用途。

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
