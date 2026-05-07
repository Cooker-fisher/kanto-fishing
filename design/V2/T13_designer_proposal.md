# T13: /premium/ ページ構成と即時実装範囲（designer 提案・reviewer指摘反映版）

**作成日**: 2026/05/07
**作成者**: designer (Agent) → reviewer 条件付き承認 → PM 修正反映
**ステータス**: 修正反映済（決定ログ追記前の最終ドラフト）
**スコープ**: ユーザー確定 = A（URL構造とページ責務確定）+ B（今すぐ実装可能な範囲の仕様化）

**改訂履歴**
- v1.0 designer 初稿（2026/05/07 16:30）
- v1.1 reviewer 指摘 4点 + 追加検討 3点を反映（2026/05/07 PM編集）
  - 修正1: LP的中率クエリ `actual_cnt_avg IS NOT NULL` → `actual_pct IS NOT NULL`（境界遵守）
  - 修正2: サンプル TOP3 に「異なる tsuri_mono」制約追加
  - 修正3: ティザー実装認識（インライン `style="filter:blur(5px)"` div ラッパー方式）を訂正
  - 修正4: history.html を「条件付き実装可」に格下げ（直近7日 prediction_log データ密度未検証）
  - 検討1-3: 末尾「実装フェーズ申し送り」に取り込み
- **v1.2 ユーザー指摘 + analyst 確認による訂正**（2026/05/07 後半 PM編集）
  - **訂正1**: v1.1 で「LP の予測サンプルは pred_pct のみ・pred_cnt_min/max は表示禁止」と書いたが、これは reviewer 指摘 #1（actual_cnt_avg 境界の話）を ZONE B' 答え合わせから LP のチラ見せまで過剰一般化したもの。決定ログ 04/04 ペイウォールUI（1件完全 + 残blur）+ 04/07 匹数レンジ表示が正解。pred_cnt_min/max は LP の有料機能デモとして表示可能。actual_cnt_min/max のみ非表示
  - **訂正2**: LP 訴求を「明日のチラ見せ」→「過去の自信予測 的中 TOP3」に切替（analyst Q4: prediction_log の最新 pred_date が 2026/04/27 で止まっており未来日予測データなし）
  - **訂正3**: 1件目に `actual_pct` + `is_good_hit` の的中バッジを追加（analyst 推奨表示形式）
  - **新規発見**: `target_date` のスラッシュ区切り問題（全予測クエリに `REPLACE(...,'/','-')` 必須）
  - **新規発見**: predict_count.py が10日前から停止（別タスク起票）
- **v1.3 リモート決定との整合（2026/05/07 push 直前 PM 編集）**
  - **訂正4**: `plan.html` 配置を `/pages/plan.html` 推奨 → **`/premium/plan.html` 採用** に変更
  - **理由**: リモート edf60cc5（別セッションの先行実装）で「`docs/premium/plan.html` 本番化 + 認証方式案A（Stripe + Cloudflare Workers + Firebase Auth）確定」が既にマージ済み。`design/V2/research/paid_mockup_audit_2026-05-06.md` と `auth_payment_options_2026-05-06.md` で根拠が記録されている
  - 影響範囲: T13_designer_proposal.md / T13_reviewer_feedback.md / mockup-plan-v2.html / mockup-premium-v2.html の 4ファイルで `/pages/plan.html` リテラルを全て `/premium/plan.html` に一括置換
  - 私の v1.2 「`/pages/` 配下の静的コピー手法」推奨は撤回。`/premium/` 配下に `build_premium_plan_page()` で生成する方針が確定済み

## 読了確認

- mockup-premium / mockup-plan / mockup-paid-dashboard / mockup-paid-forecast / mockup-paid-calendar / mockup-paid-fish-calendar / mockup-history / mockup-mypage / mockup-forecast-area: 全9ファイル読了
- 90_決定ログ.md 2026/04/10 URL命名規則・URL全体設計セクション: 読了
- 11_有料ページデザイン.md: 読了
- docs/forecast/index.html / docs/forecast/2026-05-07.html / docs/forecast/area/tokyo.html: 読了

---

## Section 1: /premium/ URL ツリー全体図

mockup 9ファイルを URL に対応させた確定案。決定ログ 2026/04/10 の構造を基準に、未追加の系統を補完。

```
funatsuri-yoso.com/
├── premium/
│   ├── index.html           ← mockup-premium.html（LP・無料閲覧可能）
│   ├── dashboard.html       ← mockup-paid-dashboard.html（会員Home・認証必須）
│   ├── history.html         ← mockup-history.html（予測履歴・30日分は有料）
│   ├── mypage.html          ← mockup-mypage.html（マイページ・認証必須）
│   ├── forecast/
│   │   ├── index.html       ← mockup-paid-forecast.html（12魚種×7日マトリクス）
│   │   └── area/
│   │       └── {area}.html  ← mockup-forecast-area.html（エリア別詳細）
│   └── calendar/
│       ├── index.html       ← mockup-paid-calendar.html（12魚種カード一覧）
│       └── {fish}.html      ← mockup-paid-fish-calendar.html（8エリア×52週）
├── forecast/
│   ├── index.html           ← 既存・無料ティザー入口（維持）
│   ├── {YYYY-MM-DD}.html    ← 既存・日次ティザー（1件完全表示+残blur・改修対象）
│   └── area/
│       └── {area}.html      ← 既存・エリアティザー（統一後: 1件完全+残ダミー）
└── pages/
    ├── about.html / contact.html / privacy.html / terms.html
    └── plan.html            ← mockup-plan.html（プラン比較・推奨配置）
```

### plan.html の配置判断: `/premium/plan.html`

理由3点:
1. mockup-plan.html のスタイルには watermark-text が含まれず、有料会員機能（購入ボタン）が入っているがページ自体は誰でも閲覧する説明ページ
2. `pages/` 配下の about.html や privacy.html と同様に「静的コピーでデプロイ可能」な性質
3. 決定ログ 2026/04/10 で `/premium/` は「有料コンテンツ配信ゾーン」と定義されており、「プランを説明するだけのページ」は有料コンテンツではない

`/premium/index.html`（LP）から `/premium/plan.html` への誘導動線は必要。

### history.html の位置付け（reviewer修正4反映: 条件付き実装可に格下げ）

mockup-history.html は無料・有料の混在ページ（無料7日 + 有料30日）の構想。`/premium/history.html` 配置自体は適切。

ただし **「7日分は無料で実装可」と即断できない**。prediction_log の現状確認結果:
- target_date 直近7日（2026/04/30〜05/06）のレコード = **0件**（target_date は予測対象「未来日」のため過去日付は皆無）
- actual_pct 入りレコード総数 = 266件 / 1,151件
- is_good_hit=1 = 102件

→ history.html の表示条件は **target_date でなく `pred_date` 基準**で絞るべき。実装前に `pred_date` 基準のクエリで「直近7日に予測した過去レコードのうち answer 済み」のカバーコンボ数を確認する必要がある。

**実装方針**:
- pred_date 基準でクエリ調整（programmer 担当）
- データ密度不足時は「直近の答え合わせ済み 3 件のみ表示」にフォールバック
- 仕様凍結扱いではないが、history.html の即時実装は本セッションのスコープから外し、後続トピック（T14以降）で扱う

---

## Section 2: ページ別「実装可否」マトリクス

| URL | mockup | 実装ブロッカー | 今すぐ実装可? | データソース |
|-----|--------|--------------|------------|------------|
| /premium/index.html | mockup-premium | なし（LP・静的テキスト + prediction_log集計） | 即時 | prediction_log（的中率集計）+ 静的テキスト |
| /premium/plan.html | mockup-plan | なし（決済ボタン先は `#` で可） | 即時 | 静的HTML |
| /premium/forecast/index.html | mockup-paid-forecast | D層（予測モデル未実装） | 後回し | analysis.sqlite + predict_count.py |
| /premium/forecast/area/{area}.html | mockup-forecast-area | D層（エリア別予測未実装） | 後回し | analysis.sqlite + weather |
| /premium/calendar/index.html | mockup-paid-calendar | actual_*未完（D層なしでも旬データは出せる） | 条件付き | combo_decadal + decadal_calendar |
| /premium/calendar/{fish}.html | mockup-paid-fish-calendar | actual_*未完（同上） | 条件付き | combo_decadal（エリア別旬） |
| /premium/dashboard.html | mockup-paid-dashboard | 認証必須 + D層 | 後回し | 認証セッション + 全テーブル |
| /premium/history.html | mockup-history | actual_*未完 + データ密度未検証 | **条件付き実装可** ※ pred_date クエリ調整 + フォールバック必須 | prediction_log + data/V2/*.csv |
| /premium/mypage.html | mockup-mypage | 認証必須 + 決済 | 後回し | 認証セッション + 決済テーブル |
| forecast/{YYYY-MM-DD}.html | 既存（日次ティザー改修対象） | blur漏洩問題（今すぐ修正） | 修正必須 | data/V2/*.csv + prediction_log |
| forecast/area/{area}.html | 既存（エリアティザー改修対象） | 不統一（今すぐ修正） | 修正必須 | data/V2/*.csv |

### ブロッカー分類の補足

- `D層`: predict_count.py が将来日付に対して実用精度の予測を出せる状態でないと、マトリクスのセルが埋まらない
- `認証`: GitHub Pages は静的ホスティングのため、サーバーサイドセッション不可。Stripe + 外部認証サービス（Supabase等）連携が必要
- `actual_*未完`: prediction_log に is_good_hit 等のフィールドは存在するが、実際の答え合わせが全コンボで出揃っていない
- `条件付き`: D層なしでも combo_decadal（旬別平均）を使えば「過去実績ベースの旬マップ」として表示可能。ただし「予測」ではなく「過去傾向」の表現になる

---

## Section 3: 今すぐ実装可能な3ページの詳細仕様

### A. /premium/index.html（LP）

**生成方法**: crawler.py に `build_premium_index()` 関数を追加し、毎日自動再生成。静的コンテンツは大半だが、「直近30日の的中率」と「予測サンプル TOP3」の2箇所だけをデータ連動。

**watermark の取り扱い**: mockup-premium.html には `watermark-text` が実装されているが、LPは未ログイン・未課金ユーザーが閲覧する。ウォーターマークは「課金済み会員の流出防止」が目的でありLPには不要。`watermark-text` ブロックと印刷用 `@media print` のウォーターマーク強調は削除。`-webkit-user-select: none` も削除（LPでのテキストコピー禁止はUX上マイナス）。

**データ連動箇所**:

的中率ボックス（`acc-box`）:
```sql
-- prediction_log テーブルから集計（reviewer修正1反映: 境界遵守）
SELECT COUNT(*) AS total,
       SUM(CASE WHEN is_good_hit=1 THEN 1 ELSE 0 END) AS hits
FROM prediction_log
WHERE target_date >= date('now', '-30 days')
  AND target_date < date('now')
  AND actual_pct IS NOT NULL
```

この集計値を `build_premium_index()` で取得し `72%` の部分を実データに差し替える。is_good_hit 定義は決定ログ 2026/04/09 に従う。`actual_cnt_avg` は決定ログ L186 で **有料境界**列のため、無料側の集計クエリでは使わない。`actual_pct` （無料境界・L185）でフィルタする。

予測サンプル（`pred-item` × 3件、**チラ見せ方式: 1件完全表示 + 残2件blur+ダミー**）:

**ユーザー指摘 + analyst 確認後の最終仕様（2026/05/07・第三改訂）**:

LP の予測サンプルは「ZONE B' 答え合わせ」とは別物で、決定ログ 2026/04/04「ペイウォールUI: 1件完全表示・残4件CSSブラー」+ 決定ログ 2026/04/07「予測出力形式: XX〜XX匹のレンジ表示。前年比%は使わない」に従う。**有料コンテンツ（pred_cnt_min/max 匹数レンジ）のチラ見せ表示**として 1件目で価値訴求する。

**訴求アングルは「過去の的中実績」**（analyst Q4 確認）: prediction_log の現状（最新 pred_date=2026/04/27、target_date max=2026/05/04）では「明日の予測」用データが存在しないため、「過去の自信予測 的中 TOP3」訴求に切替。

#### 1件目（完全表示）の表示フィールド（境界遵守）

| フィールド | LP表示 | 根拠 |
|---|---|---|
| `pred_cnt_min/max`（匹数レンジ） | ✅ 表示 | 04/04 ペイウォールUI 1件完全表示 + 04/07 レンジ表示 |
| `pred_size_lo/hi`（サイズcm・あれば） | ✅ 表示 | 上記同 |
| `pred_pct`（平年比%） | ✅ 表示 | 無料境界（04/09 L185） |
| `actual_pct`（実績%） | ✅ 表示 | 無料境界（04/09 L185） |
| `is_good_hit`（的中バッジ） | ✅ 表示 | 無料境界（04/09 L185） |
| `actual_cnt_min/max`（実績匹数） | ❌ 非表示 | 有料境界・答え合わせ文脈（04/09 L187） |
| 信頼度★（pred_stars） | ✅ 表示 | チラ見せ価値訴求 |
| 推奨船宿、簡易理由 | ✅ 表示 | コンテンツ識別子・SEO |

例：
```
[アジ × 金沢八景] 信頼度 ★★★★★
予測 22〜48匹 (平年比 +25%)
→ 実績 +28% ✓ 的中
◎忠彦丸 / ◎荒川屋
水温が好条件帯に入り、大潮2日目で潮通し良好
```

#### 2件目以降（blur + ダミー文字列）

漏洩対策のためダミー（`??? × ???` `??〜??匹` `??〜??%`）に置換し `<div style="filter:blur(5px);..." aria-hidden="true">` で包む。

#### サンプル選択クエリ（analyst 提供・修正版）

**重要**: `target_date` は `2026/MM/DD`（スラッシュ区切り）で格納されており、SQLite `date('now')`（ハイフン区切り）と直接比較すると `/` > `-` で全件未来日判定される。`REPLACE(target_date,'/','-')` で正規化必須。

```sql
SELECT fish, ship, target_date, pred_cnt_min, pred_cnt_max, pred_pct, actual_pct, is_good_hit
FROM (
  SELECT *,
         ROW_NUMBER() OVER (PARTITION BY fish ORDER BY REPLACE(pred_date,'/','-') DESC) AS rn
  FROM prediction_log
  WHERE is_good_hit = 1
    AND actual_pct IS NOT NULL
    AND pred_cnt_min IS NOT NULL
    AND REPLACE(target_date,'/','-') < date('now')
)
WHERE rn = 1
ORDER BY REPLACE(pred_date,'/','-') DESC
LIMIT 3
```

異なる魚種から直近の的中実績を3件取得。analyst 確認時点で **5魚種**（アジ・アオリイカ・イサキ・オニカサゴ・カサゴ）から TOP3 取得可能。

#### データ不足時のフォールバック

3件未満の場合、サンプルセクション全体を「準備中」プレースホルダーに切替。

#### 改訂経緯

- v1.0 初稿（designer）: 元 mockup-premium 構造ベース
- v1.1 reviewer 修正反映: 「pred_pct のみ・pred_cnt_min/max 表示禁止」と過剰制限
- **v1.2 ユーザー指摘 + analyst 確認**: v1.1 の制限は ZONE B' の境界を LP に誤適用した過剰一般化。本来は決定ログ 04/04 ペイウォールUI（1件完全 + 残blur）+ 04/07 匹数レンジ表示が正解。actual_cnt_min/max のみ非表示。「明日の予測」→「過去の的中実績」訴求に切替（データ充足の現実解）

**SEO**:
```html
<title>釣果予測 有料プラン — 船釣り予想</title>
<!-- reviewer 検討2反映: description は実集計値で動的生成（{hit_rate} は build_premium_index() で差し込み） -->
<meta name="description" content="明日〜4週間後の釣果予測。月額500円・的中率{hit_rate}%。水温・潮汐・月齢から算出、関東全域の船宿別ランキング付き。">
<link rel="canonical" href="https://funatsuri-yoso.com/premium/">
```

`{hit_rate}` のフォールバック: prediction_log の集計が成立しない場合は固定 `72%` 等を使わず、「直近の答え合わせ実績から」など数値を含まない文言に置き換える。古い数値が検索結果に残るリスクを排除する。

JSON-LD `Product` + `Offer` 2種類:
```html
<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "Product",
  "name": "船釣り予想 有料プラン",
  "description": "明日から4週間後の釣果予測、魚種別信頼度評価",
  "offers": [
    {"@type": "Offer", "name": "月額プラン", "price": "500", "priceCurrency": "JPY", "availability": "https://schema.org/InStock"},
    {"@type": "Offer", "name": "スポット",   "price": "100", "priceCurrency": "JPY", "availability": "https://schema.org/InStock"}
  ]
}
</script>
```

**ナビ・動線**:
無料側の既存グローバルナビ（`nav.gnav`）に「有料プラン」リンクを追加（`href="/premium/"`）。LPから `plan.html` へは「プランを比較する →」リンクで誘導。forecast/index.html / forecast/{date}.html のティザーCTA「月額500円で全て見る」は `/premium/` に向ける。

**規約セクションの取り扱い**: mockup-plan.html 末尾の「ご利用規約（抜粋）」（スクレイピング禁止・API非公開・ウォーターマーク・1日200ページ上限）はLPには載せない。plan.html に集約。

---

### B. /premium/plan.html（プラン比較）

**配置根拠**: `pages/` 配下は design/V2/ から静的コピーでデプロイされる（crawler.py の design sync）既存の仕組みと完全に同じ扱い。about.html と同じ手法で `design/V2/plan.html` を作成し、毎日の crawler.py 実行時に `docs/premium/plan.html` へコピー。追加するコード変更は crawler.py の design_sync リストに `plan.html` を1行追加するのみ。

**決済ボタン先**: 現時点では `href="#"` のまま。「月額で始める →」「スポット購入」ボタンはクリックしても動作しないことを `aria-disabled="true"` と class `disabled` で明示し、テキストを「近日公開」に変更。決済実装後にURL差し替え。

**友達紹介プログラム**: 「準備中」として表示。mockup の紹介コードブロックをそのまま残しつつ、CTAボタンを「近日公開」に差し替え。決済が稼働しないと紹介コードも意味を持たないため。削除はしない（将来のUI継続性のため）。

**規約抜粋**: mockup-plan.html にある「ご利用規約（抜粋）」セクション（スクレイピング禁止・API非公開・ウォーターマーク・1日200ページ上限・予測の免責）は plan.html に置く。「利用規約 全文を見る →」は `/pages/terms.html` にリンク。

**`terms.html` への転記**: plan.html の規約抜粋をより詳細な形で `design/V2/terms.html` に追記することを programmer ロールへ申し送りする（デザイナー範囲外）。

---

### C. forecast/ ティザー方式の統一

#### 現状の2形式（reviewer修正3反映: 実装認識を訂正）

**日次ファイル（2026-05-07.html）の実際の実装**:
- CSS定義: `.blur-text {filter:blur(6px)}` `.teaser-dummy {filter:blur(1.5px)}` の両方が定義されているが、**いずれも本体HTMLでは未使用（dead code）**
- 実装は **インライン `style="filter:blur(5px);user-select:none;pointer-events:none;opacity:0.75"` の `<div>` ラッパー**で `.detail-card` 全体を包む方式
- 1件目（最高信頼度）は ラッパー無しで完全表示。2件目以降は実データを含む `.detail-card` を上記ラッパーで覆っている
- 実データ（魚種・エリア・予測匹数・船宿名・分析コメント全文）が **HTMLソースに完全に含まれている** → 開発者ツールでこの style 属性を消せば全件閲覧可能（案A の漏洩問題）
- 末尾に `.paywall` セクション（CTA「月額500円で全て見る」+ 「決済システム準備中」）

```html
<!-- 既存実装抜粋（docs/forecast/2026-05-07.html L282 以降）-->
<div style="filter:blur(5px);user-select:none;pointer-events:none;opacity:0.75">
  <div class="detail-card high-conf">
    <div class="dc-header"><span class="dc-fish">アジ × 千葉・東京湾奥</span><span class="conf-badge conf-A">A</span></div>
    <div class="dc-range">予測 34〜225匹 / 15〜38cm　型狙い</div>
    <div class="dc-factors">...</div>
    <div class="dc-analysis">...（分析テキスト全文）...</div>
    <div class="dc-ships">📍 吉野屋 / 須原屋 / 林遊船</div>
  </div>
</div>
```

**エリアファイル（area/tokyo.html）の実装**:
同一CSSが読み込まれているが、エリアページは `teaser-dummy` クラスと `coming-soon-panel` オーバーレイ方式で「準備中」を表示し、**実データはHTMLソースに存在しない**。（こちらは案B 相当）

#### 3案の比較

- **案A**（全ページ実データblur統一）: 現在の日次方式を全ページに適用。CSSバイパスで全件盗み見可能。決定ログ「1件完全表示・残りはブラー」の原則には合致するが、データ保護が皆無のため**採用不可**
- **案B**（全ページ「準備中」placeholder統一）: 現在のエリア方式を全ページに適用。データ漏洩ゼロだが、「いくら釣れるか全く分からない」状態になりチラ見せの価値訴求が弱い
- **案C**（1件完全表示 + 残はダミー文字列のblur）: 1位コンボ（信頼度最高のもの）だけ実データを完全表示し、2件目以降はダミーテキスト（「★？？」「??〜??匹」「??〜??cm」等）をblurで見せる

#### 推奨: 案C

理由3点:

1. 決定ログ 2026/04/04「5件表示、1件目は完全無料、2〜5件目はCSSブラー」の原則に最も近い実装になる。1件目は実データ完全表示という原則は維持
2. ダミー文字列（`??〜??匹`等）を使うことで、CSSバイパスでも実データが漏洩しない。案Aで発生していた「開発者ツールでblur解除→全件取得」が原理的に不可能になる
3. 「数字が並んでいる様子だけ見える」という視覚的チラ見せ効果は案A同等。ブラーの中に形があることで「見えそうで見えない」UXが成立

#### 既存 forecast/2026-05-07.html の改修方針（reviewer修正3反映）

改修対象は `crawler.py` の `build_forecast_pages()` (L2250) 周辺、`build_forecast_section()` (L2294) または `build_forecast()` (L5371) のいずれかで forecast/{date}.html を生成しているループ。実装担当が grep で正確な出力箇所を特定する。

**改修ロジック**:
2件目以降のコンボを出力する際、現状の「`<div style="filter:blur(5px);...">` で `.detail-card` 全体を包む（実データ含む）」方式から、「`.detail-card` の中身を **ダミー文字列で生成**してから blur ラッパーで覆う」方式に変更する。

```html
<!-- 改修前: 実データが含まれる（盗み見可能）-->
<div style="filter:blur(5px);user-select:none;pointer-events:none;opacity:0.75">
  <div class="detail-card high-conf">
    <div class="dc-header"><span class="dc-fish">アジ × 千葉・東京湾奥</span><span class="conf-badge conf-A">A</span></div>
    <div class="dc-range">予測 34〜225匹 / 15〜38cm　型狙い</div>
    <div class="dc-factors">...</div>
    <div class="dc-analysis">...（実分析テキスト）...</div>
    <div class="dc-ships">📍 吉野屋 / 須原屋 / 林遊船</div>
  </div>
</div>

<!-- 改修後: ダミー文字列に置換（漏洩なし）-->
<div style="filter:blur(5px);user-select:none;pointer-events:none;opacity:0.75" aria-hidden="true">
  <div class="detail-card high-conf">
    <div class="dc-header"><span class="dc-fish">??? × ???</span><span class="conf-badge conf-A">?</span></div>
    <div class="dc-range">予測 ??〜??匹 / ??〜??cm</div>
    <div class="dc-factors"><span class="dc-factor good">🌊 ?</span><span class="dc-factor good">💨 ?</span><span class="dc-factor good">🌡️ ?</span></div>
    <div class="dc-analysis">海況条件と過去実績から予測。詳細は有料プランで閲覧できます。</div>
    <div class="dc-ships">📍 ???</div>
  </div>
</div>
```

ダミーカードのレイアウト（行数・要素数）は実データカードと近いものを維持し、blur後の視覚的「数字が並んでいる感」を保つ。`aria-hidden="true"` を追加してアクセシビリティ的にも非表示扱いにする。

既存ファイルは毎日再生成されるため、一度ロジックを直せば全日付ファイル（2026-04-25 〜 2026-05-12 の日次 + W19〜W23 の週次）に波及する。

#### 既存 forecast/area/tokyo.html の改修方針

現在は `teaser-dummy` + `coming-soon-panel` で「準備中」を表示している。これを案Cに合わせて「1件完全表示 + 2件以降ダミーblur」に変更する。mockup-forecast-area.html の `paid-content` ブロックが参考実装。同 mockup の `paid-overlay` はそのまま流用可能。

#### CSSバイパス対策の限界について

CSS blur はあくまでユーザー体験上の障壁であり、技術的に完全な保護にはならない。正式な保護は認証と決済実装後にサーバーサイドで行う。案Cで実データをダミーに置換することは「静的サイトでできる現実的な最大限の対策」。この事実を programmer ロールとの共有事項として明記しておく。

---

## Section 4: 決定ログ追記案（reviewer指摘反映版）

`design/V2/90_決定ログ.md` の末尾に以下を追記する想定。

---

```
### 2026/05/07 — T13: /premium/ ページ構成と即時実装範囲確定

**URL ツリー確定（mockup 9ファイルの対応完了）**

| URL | mockup | 備考 |
|-----|--------|------|
| /premium/index.html | mockup-premium.html | LP・無料閲覧可 |
| /premium/plan.html | mockup-plan.html | 静的コピー・about.html と同じ手法・将来 /premium/plan.html 移行余地 |
| /premium/dashboard.html | mockup-paid-dashboard.html | 認証・D層ブロック |
| /premium/history.html | mockup-history.html | 条件付き実装可・要 pred_date 基準クエリ + データ密度確認 |
| /premium/mypage.html | mockup-mypage.html | 認証・決済ブロック |
| /premium/forecast/index.html | mockup-paid-forecast.html | D層ブロック |
| /premium/forecast/area/{area}.html | mockup-forecast-area.html | D層ブロック |
| /premium/calendar/index.html | mockup-paid-calendar.html | 条件付き実装可（過去旬データ）・スコープ外 |
| /premium/calendar/{fish}.html | mockup-paid-fish-calendar.html | 条件付き実装可（過去旬データ）・スコープ外 |

決定ログ 2026/04/10 の `premium/forecast/daily/{date}.html` は、現行実装では
`forecast/{YYYY-MM-DD}.html`（無料側ティザー）として既に存在する。有料会員向けの
フルデータ版は `/premium/forecast/daily/{date}.html` として別途作成する（D層実装後）。

**実装ブロッカー（4分類）の明示**
- D層（予測モデル）: predict_count.py の実用精度到達まで予測マトリクスは生成不可
- 認証: GitHub Pages = 静的。Stripe + 外部認証（Supabase等）の選定が前提
- 決済: Stripe未連携。plan.html の購入ボタンは近日公開として無効化
- actual_*未完: prediction_log の actual_pct 入りは 266/1,151件（23%）。直近7日の target_date レコードは0件（仕様上 future date のみ）

**今すぐ実装可能な3スコープ（reviewer 指摘反映版）**

1. `/premium/index.html`（LP）
   - 関数追加: `build_premium_index()` を crawler.py に新設
   - 的中率: prediction_log から `WHERE actual_pct IS NOT NULL`（actual_cnt_avg は有料境界のため使用禁止）で集計
   - サンプル TOP3: 「**異なる tsuri_mono から1件ずつ**」を仕様化（単一コンボ反復回避）
   - 表示フィールド: pred_pct / actual_pct / is_good_hit / fcast_* のみ（pred_cnt_min/max は表示禁止）
   - watermark / user-select:none は LP では削除
   - JSON-LD: Product + Offer 2種（月額500円・スポット100円）
   - meta description: `{hit_rate}` を動的差し込み（固定72%は禁止）。集計不成立時は数値含まない文言

2. `/premium/plan.html`（プラン比較）
   - design/V2/plan.html を追加し crawler.py の design_sync リストに登録
   - 決済ボタン: `aria-disabled="true"` + class `disabled` + 文言「近日公開」
   - 友達紹介: 紹介コードブロックは残し CTA を「近日公開」に
   - 規約抜粋（スクレイピング禁止・API非公開・watermark・1日200ページ上限・予測免責）を集約
   - 将来 `/premium/plan.html` への移行余地を残す（canonical / 301 リダイレクト計画）

3. forecast/ ティザー統一（案C: 1件完全 + 残ダミー文字列blur）
   - 改修対象: `crawler.py` の build_forecast_pages (L2250) / build_forecast_section (L2294) / build_forecast (L5371)
   - 改修箇所: 2件目以降のコンボを出力するループで、`detail-card` の中身（dc-fish/dc-range/dc-factors/dc-analysis/dc-ships）を **ダミー文字列**で生成（`???`/`??〜??匹`/`??〜??cm`/`📍 ???`）
   - 既存実装の問題: `<div style="filter:blur(5px);...">` 内に実データを含む `.detail-card` が生成されており、CSS バイパスで漏洩可能
   - .blur-text / .teaser-dummy CSS 定義は dead code（削除候補だが本トピックではスコープ外）
   - `aria-hidden="true"` をダミーラッパー div に追加
   - area/{area}.html も同方式に統一（teaser-dummy + coming-soon-panel から切替）
   - **改修後 `python crawl/validate_output.py` で 11不変条件 + 12不変条件 PASS を確認**（特に #11 ネストアンカー：1件目 detail-card 内 `<a>` と paywall 内 `<a>` の入れ子発生を確認）

**plan.html の配置理由**
`/premium/` は有料コンテンツ配信ゾーンであり、「プランを説明するだけのページ」は該当しない。
`/pages/` 配下の静的ページ群（about/contact/privacy/terms）と同種の扱いが適切。
将来的に `/premium/plan.html` へ統合する選択肢は残す（canonical 変更 + 301 リダイレクトコスト）。

**関連ロール**: pm / programmer / designer / reviewer
```

---

## 関連ファイル

- `/design/V2/mockup-premium.html`
- `/design/V2/mockup-plan.html`
- `/design/V2/mockup-paid-dashboard.html`
- `/design/V2/mockup-paid-forecast.html`
- `/design/V2/mockup-paid-calendar.html`
- `/design/V2/mockup-paid-fish-calendar.html`
- `/design/V2/mockup-history.html`
- `/design/V2/mockup-mypage.html`
- `/design/V2/mockup-forecast-area.html`
- `/design/V2/90_決定ログ.md`
- `/design/V2/11_有料ページデザイン.md`
- `/design/V2/T13_reviewer_feedback.md`（reviewer 指摘事項詳細）
- `/docs/forecast/2026-05-07.html`（インラインstyle実データblur・改修対象）
- `/docs/forecast/area/tokyo.html`（準備中placeholder・案C統一対象）

---

## 実装フェーズ申し送り（programmer 向け・reviewer指摘反映）

### 必須検証手順

1. **改修前データ密度確認**:
   - `prediction_log` で `pred_date` 基準直近7日のレコード数とカバーコンボ数を SQL 確認
   - actual_pct 入り行の比率（現状 23%）を踏まえてフォールバック条件を実装

2. **改修後 validate_output.py 実行**:
   - `python crawl/validate_output.py` で 11不変条件 + 12不変条件 PASS を確認（不変条件 #11 ネストアンカー が特に重要）
   - 失敗したらコード修正。**閾値を緩めて gatekeeper を黙らせる修正は禁止**（feedback_regression_prevention.md）

3. **forecast/ 改修の確認項目**:
   - 1件目 `detail-card` 内 `<a>` と外側 `paywall` 内 `<a>` の入れ子が発生しないか目視確認
   - ダミーカード `aria-hidden="true"` が SEO に negative impact 与えないか（aria-hidden=true は indexed されるべきでない部分のため OK だが念のため Lighthouse 確認）

4. **LP 動的データのフォールバック**:
   - `actual_pct IS NOT NULL` のレコード総数 < 30 の場合は的中率セクション全体を「集計準備中」に切り替え
   - サンプル TOP3 が `tsuri_mono` 制約で3件揃わない場合は静的サンプル（mockup-premium のまま）にフォールバック

5. **target_date 日付比較の正規化（analyst 発見・必須）**:
   - `prediction_log.target_date` は `2026/MM/DD`（スラッシュ区切り）で格納されている
   - SQLite の `date('now')` は `YYYY-MM-DD`（ハイフン区切り）
   - 直接比較すると `/`(ASCII 47) > `-`(ASCII 45) で **全件が未来日判定** → クエリが0件返却
   - **必ず `REPLACE(target_date,'/','-')` で正規化**してから `date('now')` と比較
   - 影響範囲: T13 designer_proposal v1.0 で記載した ZONE B' クエリ「`WHERE target_date = date('now','-2 days')`」も同じバグあり。LP/forecast の全予測関連クエリで要修正
   - **修正例**:
     ```sql
     -- NG（全件未来日扱い）
     WHERE target_date < date('now')
     -- OK
     WHERE REPLACE(target_date,'/','-') < date('now')
     ```

6. **predict_count.py 停止問題の解消（analyst 発見・別タスク）**:
   - prediction_log の最新 `pred_date` が `2026/04/27`（10日前）で停止している
   - `target_date` の max が `2026/05/04` のため、現時点（2026/05/07）では「明日以降の予測レコード」が存在しない
   - 原因候補: crawl.yml の predict_count.py 実行ステップが停止 / 予測バッチエラー
   - LP の「明日の自信予測」訴求はデータ充足が前提。本トピックでは **「過去の的中実績」訴求に切替**で当面回避
   - **別タスクとして起票推奨**: `crawl.yml` の predict_count.py 実行ステップ確認・最終実行ログ確認・必要なら手動再起動

### 命名規則・パス整合

- `build_premium_index()` の出力先: `docs/premium/index.html`（新規ディレクトリ）
- `docs/premium/` ディレクトリは crawler.py 起動時に `os.makedirs(..., exist_ok=True)` で作成
- sitemap.xml に `/premium/` URL を追加
- `_load_recent_catches_for_index()` 等の既存ヘルパーは LP では使わない（LP 専用ロジック）

### 後続タスク（T14 以降）

- `/premium/calendar/*` — combo_decadal 過去傾向ベースの実装（D層なしでも作れる条件付き実装可）
- `/premium/history.html` — pred_date 基準クエリ確定後に実装
- D層実装完了後の `/premium/dashboard.html` `/premium/forecast/index.html`
- Stripe + 外部認証選定（C トピック扱い）
