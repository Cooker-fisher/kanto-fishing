# 差別化戦略 3案（2026-05-10・designer）

## 0. 前提整理（読んだ資料・理解した制約）

読んだ資料: `2sites_audit_2026-05-10.md`（kd-fishing/funazuri-no1 実見監査・340行）、`調査レポート.md`（釣りビジョン/船釣り.jp/釣割/ANGLERS 等5競合）、`90_決定ログ.md`（確定方針SoT・補遺3 avg禁止）、`91_実装ワークログ.md`（T22完了・T23 forecast/実コンテンツ化が次予定）、`REGRESSION_PREVENTION.md`（18不変条件）、`mockup-index-v3.html`（現行トップ構造）。

制約5点: (1)補遺3 — avg/平均/ave を出力に含む設計案は禁止。(2)無料=事実のみ・有料=分析+予測の境界維持。(3)11+7=18不変条件を破る変更は禁止。(4)kd-fishing と表面的に同じ設計（ものさしマスターの直接コピー・月間レポートの追随）は禁止。(5)V1 参照禁止。

競合状況の核心: kd-fishing は「データ規模 2.5倍・船宿数 7.7倍・12年蓄積」であり短期での追随は不可能。「ものさしマスター」評価は下位25%/中央50%/上位25%/上位10%の分位基準で avg/中央値を明示併記 — 我々の補遺3思想と真逆。T23（forecast/実コンテンツ化）が次の予定タスクであり、差別化策はT23と接続できるものが実装効率上有利。

---

## 1. 案A. 「予測の透明性」軸

### コンセプト（1段落）

kd-fishing の「ものさしマスター」は「下位25%=渋い、中央50%=普通」という統計分位ラベルで評価を公開し、avg/中央値を即時表示する。これはユーザーに「数値の出元」を提示する透明性設計であり有効だが、「avg を出す」思想で補遺3と真逆。我々は promise_break_rate（"期待を下回らなかった率"）という別の軸を透明性の核に据える — 「予測した min〜max レンジを実際の釣果が下回らなかった割合」を全予測に開示し、予測精度の誠実な開示で信頼を構築する。釣り人（週末アングラー・ガチ勢両方）に響くコンセプトは「外れたときも、なぜ外れたかを公開するサイト」。

### ワイヤーフレーム（言葉ベース）

**新規ページ: `pages/methodology.html`**
- URL: `/pages/methodology.html`（既存 pages/ ディレクトリ、design/V2/methodology.html から自動同期）
- H1: 「予測の仕組みと精度について」
- Section 1: promise_break_rate の定義（「予測した釣果レンジ min〜max を、実際の釣果が下回らなかった割合」）。数式ではなく例示ベースで説明。「アジ×東京湾 昨月: 期待を下回らなかった率 89%」のように実値を埋め込む。
- Section 2: 予測に使うデータの説明（気象・潮汐・月齢・過去3年釣果データ。ソースは自社収集・Open-Meteo・気象庁）
- Section 3: 「外れるとき」のパターン（台風接近・急激な水温変化・前例なしの超爆釣日）を3パターンで事実ベース記述
- Section 4: 答え合わせ ZONE B' への導線（「毎日、前日の予測 vs 実績を公開しています」）
- JSON-LD: WebPage + FAQPage（「promise_break_rate とは何ですか」等3問）
- 文字数目標: 1,200字以上（AdSense 品質基準）

**既存ページ改変: `index.html` ZONE B'（答え合わせセクション）強化**
- 現行: 一昨日の最良結果1件を無料チラ見せ（90_決定ログ 2026/04/04確定）
- 追加: チラ見せカードの下に「このサイトの予測精度は？」リンク → methodology.html
- 追加: ZONE B' の見出しを「予測 vs 実績（答え合わせ）」に変更し、「promise_break_rate とは」tooltip 的な注釈を小テキストで追加（無料ユーザーへの信頼訴求）

**既存ページ改変: `fish/{slug}.html` 魚種別ページ**
- 有料ティザーの直下に「この魚種の直近30日 promise_break_rate: XX%」を1行追加（有料コンテンツへの信頼訴求。数値は prediction_log から集計）
- 「詳細はこちら」→ methodology.html リンク

**`about.html` 追記**
- 「予測精度について」セクション追加（methodology.html への誘導と3行概要）

### 実装スケッチ

- `crawler.py` 影響: `build_fish_pages()` に promise_break_rate 集計コード追加（analysis.sqlite の combo_range_backtest テーブルから `metric='cnt', horizon=0` の promise_break を fish/ship 別に集計）。新関数: `_get_promise_break_rate(fish, conn)` → 直近30日・n≥5 のコンボを対象に中央値算出
- `design/V2/methodology.html` 新規作成（手書き静的 HTML・crawler.py が数値を埋め込む形式か、完全静的かを選択。推奨: 実値埋め込みのため crawler.py の `build_pages_sync()` で動的生成）
- analysis 層: 既存 `combo_range_backtest` テーブル参照のみ。新規テーブル不要
- データソース: analysis.sqlite の `combo_range_backtest`（metric, horizon, promise_break 列）
- 新規ページ生成数: 1件（methodology.html）
- analysis スクリプト改修: 不要

### AdSense 対策上の有効性

- T22-H1（forecast/ noindex 暫定）: 本案は forecast/ を触らない。影響なし
- T22-M1（共通FAQ重複解消）: methodology.html が独立した「仕組み解説」ページとなるため、fish ページの FAQ から「予測はどのように計算しますか」問を methodology.html に誘導するリンクに置き換えられる → 重複 FAQ の更なる削減に貢献
- T22-M2（概況テンプレ感解消）: fish ページの「この魚種の promise_break_rate: XX%」が魚種固有の動的数値となりテンプレ感を薄める
- 「Low value content」却下理由への対処: methodology.html は 1,200字以上の独自コンテンツ。AdSense が評価する「コンテンツの独自性・専門性」に該当。競合他社が同種のページを持っていない（kd-fishingの「ものさしマスター」は UI 上の表示であって説明ページは別）

### 90_決定ログとの整合性

- 補遺3「avg は出さない」: methodology.html の記述で「平均的中率 XX%」等の表記は一切使わない。「promise_break_rate = 期待を下回らなかった率 XX%」の形式で統一。avg/平均の字句を含む文案は禁止。OK
- 「無料=事実 / 有料=分析+予測」境界: methodology.html 自体は「仕組みの説明」であり事実ベース記述が可能（無料）。promise_break_rate の数値（実績値）も事実。有料側は「今後の予測（明日の期待を下回らない確率）」に留まる。境界維持 OK
- 「的中率」は使わない（T15 で架空数値ごと削除済み）: 本案は「的中率」という語を使わず「promise_break_rate」/「期待を下回らなかった率」で統一。整合 OK
- 配色・フォント: 既存 V2 CSS 変数のみ使用。ハードコード色なし。整合 OK

### リスク

- **kd-fishing との類似リスク（中）**: 「評価ロジックを公開する」という方向性はものさしマスターと同方向。ただし我々は分位ではなく promise_break_rate という独自指標で差別化できる。UI 設計を「バッジ型評価」ではなく「継続率の折れ線」等にすれば表面的な類似を避けられる
- **ユーザー理解コスト（中）**: promise_break_rate は一般釣り人に直感的でない。「外れなかった率 89%」という日本語訳と例示を丁寧に設計しないと伝わらない
- **取り返しのつかない決定**: なし。methodology.html は新規ページ追加のみ。URL 構造変更なし

### 実装コスト見積もり

- crawler.py 修正規模: `_get_promise_break_rate()` 新関数（約30行）+ `build_fish_pages()` への1行挿入 + `build_pages_sync()` に methodology.html 生成呼び出し追加（約5行）
- 新規ページ生成: 1件（methodology.html）
- analysis スクリプト改修: 不要（既存 combo_range_backtest 参照）
- 実装コスト評価: **低**

---

## 2. 案B. 「魚種カバー」軸

### コンセプト（1段落）

kd-fishing が持つ魚種別ページは12件（sitemap 確認）であるのに対し、我々は51魚種のページを持つ — これは4.25倍の優位であり短期で逆転されない構造的強みだ。ただし現状この優位が「全魚種一覧」として一箇所に集約されておらず、ユーザーの目に見えていない。「関東の船釣りなら、この51魚種全部調べられる」というカバレッジの訴求を、トップページと新規ハブページで前面化する。funazuri-no1.jp が「はじめての船釣り」教育コンテンツで初心者を獲りに行っているのに対し、我々は「釣りたい魚が決まっている人」のハブとして立つポジションを選ぶ。

### ワイヤーフレーム（言葉ベース）

**新規ページ: `fish/index.html`（全魚種ハブ）**
- URL: `/fish/index.html`（既存ディレクトリ内。現在は存在しない）
- H1: 「関東で釣れる魚 51種 — 魚種別釣果情報」
- 構成:
  - 旬ピーク魚種（今月 旬カレンダーで score 最高の6種を大きく表示。サムネイル + 代表ポイント + 直近 min〜max 匹数）
  - 50音順全魚種グリッド（51種。各カードに魚種名・直近件数・代表エリア）
  - 魚種クロス比較ウィジェット（「この2魚種、どちらが今週釣れてる？」式の簡易比較 — 無料・事実のみ）
  - 旬カレンダーハブ（年間12ヶ月×上中下旬の「狙い目魚種」一覧表。旬 peak 魚種に色付け）
- JSON-LD: BreadcrumbList + ItemList（51魚種の ListItem）
- 文字数: 魚種グリッド + 説明テキストで 1,000字以上見込み

**既存ページ改変: `index.html` gnav・ZONE E**
- gnav の「魚種」リンクを `/fish/index.html` に変更（現状は fish のセクション内リンクか未設定）
- ZONE E（ナビセクション）に「全51魚種を見る →」ボタンを追加

**既存ページ改変: `fish/{slug}.html` 各魚種ページ**
- HERO 直下に「関連魚種」チップを追加（共外道・同ポイント魚種3種 → fish_area ページへの誘導）
- パンくずを「トップ &gt; 魚種一覧 &gt; アジ」形式に統一（現状「トップ &gt; アジ」になっているケースがある）

**既存ページ改変: `calendar.html`**
- カレンダー上部に「今月の旬魚種TOP5」サマリーバナーを追加（事実ベース）

### 実装スケッチ

- `crawler.py` 影響:
  - 新関数 `build_fish_index_page(valid_catches, decadal_calendar, fish_list)` → `/fish/index.html` 生成
  - 既存 `build_fish_pages()` のパンくず修正（深さ=1 の場合 fish/index.html を中間に挟む）
  - 既存 `_v2_header_nav()` の gnav リンク修正（「魚種」→ `/fish/index.html`）
- analysis 層: combo_decadal（旬別集計）・decadal_calendar を参照のみ。新規テーブル不要
- データソース: data/V2/*.csv（51魚種 × 直近件数）、decadal_calendar（旬ピーク）
- 新規ページ生成数: 1件（fish/index.html）
- analysis スクリプト改修: 不要

### AdSense 対策上の有効性

- T22-H1（forecast/ noindex 暫定）: 本案は forecast/ を触らない。影響なし
- T22-M1（FAQ重複）: fish/index.html は FAQ を持たない設計（グリッド主体）ので重複リスクなし
- 「Low value content」却下理由への対処: fish/index.html は51魚種データを集約した独自ハブページ。「網羅性のある構造化コンテンツ」として AdSense 評価対象。ただし、魚種グリッドがテーブル/グリッドのみで文章が少ない場合は薄コン判定リスクあり — 旬解説文（各月ごとの旬魚種説明 100字以上）を入れることで対処
- 「網羅性のある情報サイト」訴求として sitemap への fish/index.html 追加が必要

### 90_決定ログとの整合性

- 補遺3「avg は出さない」: 魚種ハブページで表示する数値は「直近 min〜max 匹数」「件数」「代表エリア」のみ。avg/平均 は一切使わない。整合 OK
- 「無料=事実 / 有料=分析+予測」境界: 魚種ハブの釣果数字（min〜max・件数）は事実。旬ピーク判定（score）は decadal_calendar の集計値なので事実の範囲。有料側（★評価・レンジ予測）とは接触しない。境界維持 OK
- REGRESSION_PREVENTION 不変条件 2「fish/index.html は釣果あり魚種 ≥5・総数 ≥20」: 現在この不変条件は `docs/fish/index.html` を想定しているが、これは「今日の釣果ありの魚種の fish/index.html リスト」用。新規 `fish/index.html` を全魚種ハブとして生成する場合、既存の不変条件 2 の対象がどちらを向くかを実装時に確認する必要がある。設計としては不変条件 2 を「全魚種ハブ」用に読み替えるか、ファイル名を `fish/all.html` にするかの選択が必要。**取り返しのつかない変更になる可能性がある（URLに関係）** — 実装時 programmer に確認させること

### リスク

- **URL 構造変更リスク（高）**: `/fish/index.html` は既存の不変条件 2 が参照しているファイル名と衝突する可能性がある。現在の validate_output.py が `/fish/index.html` をどう扱っているかを実装前に確認必須。代替として `/fish/all.html` を使えばリスク回避できる（ただし覚えにくいURL）
- **薄コンリスク（中）**: 魚種グリッドのみだと文章量が足りず薄コン判定されうる。旬解説文の追加が必須
- **競合との差別化薄さ（中）**: 「全魚種一覧」はどのサイトも持てる機能。kd-fishing が12魚種→30魚種に拡張した場合に優位が縮まる

### 実装コスト見積もり

- crawler.py 修正規模: `build_fish_index_page()` 新関数（約80行）+ gnav 修正（5行）+ パンくず修正（10行）
- 新規ページ生成: 1件（fish/index.html or fish/all.html）
- analysis スクリプト改修: 不要
- 実装コスト評価: **低〜中**（URLリスク確認コストを含む）

---

## 3. 案C. 「関東特化+構造化レポート」軸

### コンセプト（1段落）

kd-fishing の月間レポートは「先月の事実集計（平均・最多・エリア別）」のみで構成された約6,000字ページだが、「来月の予測」が存在しない。また「平均 6.0枚」「平均 8.1枚」という avg 表記を多用しており補遺3と真逆の設計だ。我々は「先月レビュー（事実）+ 来月予測（有料壁付き）」をセットにした月次レポートを `forecast/report/YYYY-MM/` に蓄積する — 先月の min〜max・船宿別実績・エリア傾向を事実として無料公開し、来月の予測レンジ（有料ペイウォール付き）をそこに続ける。「関東5県・75船宿に特化したデータを、月ごとに体系化する」という唯一のプレイヤーポジションを取る。これは T23（forecast/実コンテンツ化）と完全に接続するタスクでもある。

### ワイヤーフレーム（言葉ベース）

**新規ページ: `forecast/report/YYYY-MM.html`（月次レポート）**
- URL: `/forecast/report/2026-04.html`（毎月1件生成。T23でnoindex解除後 sitemap 収録）
- URL設計方針: `/forecast/report/` サブディレクトリ配下。forecast/index.html（noindex暫定）とは別ディレクトリに置くことで、T22-H1 の noindex 適用対象から外す（`_forecast_page_head()` の noindex は forecast/index.html 固有の対応であり、サブディレクトリは別途制御）
- ページ構成（H2 5本・約5,000〜6,000字）:
  - H1: 「関東船釣り 釣果レポート YYYY年MM月」
  - H2-1: 月間サマリー（今月釣果件数・出船船宿数・今月最多魚種・エリア別件数 — すべて無料・事実）
  - H2-2: 魚種別実績 TOP5（各魚種の min〜max 匹数・代表船宿・釣れたエリア — 無料・事実）
  - H2-3: エリア別状況（関東5エリア × 主力魚種 × 件数 — 無料・事実）
  - H2-4: 来月の予測（有料ペイウォール付き。今月の傾向から来月の旬魚種 min〜max レンジを提示。avg は一切使わない）
  - H2-5: 今月の海況メモ（水温・波高・台風影響等の事実記録。無料）
- 文字数目標: 無料部分のみで 3,500字以上（H2-1〜3・5）。有料ペイウォール部分（H2-4）は blur 表示で 1,500字相当を追加
- JSON-LD: Article（datePublished・author・headline）+ BreadcrumbList
- 「続報バナー」: kd-fishing 参考。「翌月N日更新予定」を掲載し、月中の重要釣果を追記できる設計
- avg 禁止の代替設計: kd-fishing が「平均 6.0枚」と書く箇所を、我々は「月間最多 21枚（〇〇丸 MM/DD）・最少 0枚（ボウズ含む）、報告件数 NN件」の形式で代替。情報密度は同水準を維持できる

**新規ページ: `forecast/report/index.html`（レポート一覧）**
- URL: `/forecast/report/index.html`
- 直近12ヶ月のレポートをカード一覧表示（月・件数・主力魚種・最大釣果）
- gnav の「有料プラン」の隣または有料プランページから誘導

**既存ページ改変: `forecast/index.html`（T23 対応 — noindex 解除とセット）**
- 現在: noindex 暫定 + coming soon
- T23完了時: noindex 解除 + 「最新月次レポートへ」サマリーと導線を追加（本案の forecast/report/YYYY-MM.html が実コンテンツとして機能するため）
- REGRESSION_PREVENTION 不変条件 13（noindex存在）・18（sitemap未収録）の反転手順は T22 確定ログ記載通りに実施

**既存ページ改変: `index.html`**
- gnav に「釣果レポート」タブを追加（現在6項目 → 7項目）は過多になるため、gnav 変更はしない
- 代わりに teaser-rotator の1スライドを「先月レポート公開中」に充て、forecast/report/最新号へリンク

### 実装スケッチ

- `crawler.py` 影響:
  - 新関数 `build_monthly_report(year, month, valid_catches, decadal_calendar, conn)` → `forecast/report/YYYY-MM.html` 生成（約150〜200行）
  - 新関数 `build_monthly_report_index(months_list)` → `forecast/report/index.html` 生成（約60行）
  - `main()` に月次レポート生成ブロック追加（毎日実行。前月分が未生成なら生成、生成済みなら skip）
  - `build_sitemap()` に `forecast/report/*.html` の URL 列挙を追加（noindex は付けない — forecast/index.html と異なり実コンテンツのため）
  - REGRESSION_PREVENTION 不変条件 18（sitemap に forecast/ URL なし）は `forecast/index.html` 固有の条件であり、`forecast/report/*.html` は別 URL なので違反しない
- analysis 層: `combo_decadal`（旬別集計）・`combo_monthly`（月別集計）・`area_decadal`（エリア×旬）を参照。新規テーブル不要。有料ページの予測レンジ生成には `combo_range_backtest` と `prediction_log` を参照
- データソース: data/V2/YYYY-MM.csv（月別釣果）、analysis.sqlite の combo_decadal/combo_monthly/area_decadal、tide_moon.sqlite（月間潮汐サマリー）
- 新規ページ生成数: 毎月1件（forecast/report/YYYY-MM.html）+ index.html 1件（合計13件目標）
- analysis スクリプト改修: 不要（既存テーブル参照のみ）

### AdSense 対策上の有効性

- T22-H1（forecast/ noindex 暫定）: 本案は `forecast/report/` サブディレクトリを新設。`forecast/index.html` の noindex 範囲を超えるため、T23 noindex 解除と並行して進められる。実質 T23 = 本案の実装と同義になる
- T22-M1・M2（FAQ重複・テンプレ感）: 月次レポートは魚種・エリア・月固有のデータで構成されるためテンプレ感が生まれにくい。FAQ はレポートページに追加しない（説明ページは methodology.html や faq.html で済む）
- 「Low value content」却下理由への最大解消: kd-fishing の月間レポート（6,218字）が AdSense 審査通過実績の根拠の一つと推定。我々の月次レポートも 5,000字以上を目標とすることで同様の評価が期待できる。「毎月蓄積される固有コンテンツ」は「Low value」の対義に最も近い設計
- 「続報バナー」設計: 公開後に月中の重要釣果を追記できる設計にすることで、ページの「鮮度」をGoogleに示す効果がある（kd-fishing が実践しているアプローチ）

### 90_決定ログとの整合性

- 補遺3「avg は出さない」: kd-fishing が「平均 6.0枚」と書く箇所を「最多 21枚（〇〇丸）・報告件数 NN件」の形式で代替。avg/平均の字句は一切使わない。文字数を稼ぐための代替表現として「min〜max の幅（0〜21枚）」「件数別分布（3枚以上は NN件中 NN件）」等を使う。設計段階で avg なしでも 3,500字が書けることを確認済み（エリア別記述・時系列記述・海況メモで補完可能）
- 「無料=事実 / 有料=分析+予測」境界: 月次レポートの H2-1〜3・5は無料（事実のみ）。H2-4「来月の予測」は有料ペイウォール付き。境界が 1 ページ内に明示されることでユーザーに無料/有料の価値差が伝わる設計。境界維持 OK
- ペイウォール方式「最初の1件は無料表示・残りはCSSブラー」: H2-4 の来月予測も同様に「最有力魚種1種は無料表示」→「残りはブラー」の形式で適用可能。整合 OK
- REGRESSION_PREVENTION 不変条件 13（forecast/index.html noindex 存在）・18（sitemap に forecast/ URL なし）: 本案が追加する `forecast/report/*.html` は `forecast/index.html` と別ファイル・別ディレクトリであるため、不変条件 13・18 の文言（「forecast/index.html」「forecast/ URL」の解釈）を T22 確定ログの T23 解除手順と照らし合わせて実装時に確認が必要。設計上は条件 13 は `forecast/index.html` 固有・条件 18 は `forecast/index.html` の URL が sitemap にない確認なので、`forecast/report/` は別扱いとして違反しない
- 配色・フォント: 既存 V2 CSS 変数のみ使用。整合 OK

### リスク

- **補遺3の誘惑（高）**: 月次レポートで文字数を確保しようとすると avg/平均 を使いたくなる。設計段階で avg なしの代替表現パターンを crawler.py のテンプレートに組み込んでおかなければ、programmer が実装時に avg を使ってしまうリスクがある。`x_post/templates.py` 同様の assert ガードを `build_monthly_report()` 内に仕込む必要がある
- **実装コスト（中）**: 月次レポートは最も多い関数追加量（約200〜260行）。また「続報バナー」等の運用面も設計が必要
- **kd-fishing との追随リスク（中）**: 月次レポート形式はkd-fishingが既に38件蓄積している。「先月事実のみ」なら追随に見える。「来月予測付き」という差別化を明確にした URL・H1 設計が必要（「釣果レポート」ではなく「釣果レビュー＋来月予測」等）
- **取り返しのつかない決定**: forecast/report/ の URL 構造は一度公開するとSEO上の変更コストが高い。`/forecast/report/YYYY-MM.html` は慎重に確定する必要がある

### 実装コスト見積もり

- crawler.py 修正規模: `build_monthly_report()` 新関数（約200行）+ `build_monthly_report_index()` 新関数（約60行）+ `main()` へのブロック追加（約20行）+ `build_sitemap()` 修正（約10行）。合計 約290行
- 新規ページ生成: forecast/report/YYYY-MM.html（毎月1件蓄積）+ index.html（1件固定）
- analysis スクリプト改修: 不要
- 実装コスト評価: **中**（3案中最大だが、T23と同義のため追加コストは T23 内で吸収できる）

---

## 4. 案間比較表

| 観点 | 案A 予測の透明性 | 案B 魚種カバー | 案C 関東+構造化レポート |
|------|----------------|--------------|----------------------|
| AdSense 通過効果（推定） | 中（methodology.html 1,200字 追加）| 中（fish/index.html 1,000字追加・薄コンリスクあり）| 高（月次5,000字×蓄積・最もLow value対策に効く）|
| 実装コスト | 低（約35行 + 1ページ）| 低〜中（約95行 + 1ページ・URL確認コスト）| 中（約290行 + 毎月1ページ生成）|
| kd-fishing との差別化度 | 高（promise_break_rate は独自・ものさしマスターのコピーではない）| 中（魚種数優位は実在するが、kd-fishingが増やせば縮まる）| 中〜高（「予測付き」が差別化の核。「事実のみ」なら中）|
| 90_決定ログ抵触リスク | 低（新ページ追加のみ・境界明確）| 低〜中（URL衝突確認が必要）| 中（補遺3誘惑あり・T23手順との照合必要）|
| ユーザーへの訴求力 | 中（「なぜこの予測か」を知りたいガチ勢向け）| 高（「釣りたい魚が決まっている人」全般）| 高（「先月どうだったか」「来月どう？」は全ユーザー）|
| 実装後の保守コスト | 低（月次更新不要・静的ページ）| 低（自動生成・手作業なし）| 中（月1件生成は自動だが、内容精度の継続確認が必要）|

---

## 5. designer 推奨と理由（200字以内）

**推奨: 案C（関東特化+構造化レポート）**

AdSense「Low value content」却下への最大解消効果があり、T23（forecast/実コンテンツ化）と完全に接続するため実装コストが T23 で吸収できる。月次 5,000字以上の固有コンテンツが毎月蓄積されることで、funazuri-no1.jp・kd-fishing の双方に対してコンテンツ深度で優位に立てる。補遺3制約下でも avg 不使用の代替表現設計が可能なことを確認済み。

---

## 付録: pm 注記

- 本ファイルは designer ロール（ツールセットに Write 含まず）が全文出力した内容を pm が代理書き出し
- designer の今後のタスクでは Write/Edit を含むツール権限の確認が必要（または成果物は pm 経由で書き出す運用に統一）
