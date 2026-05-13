# T29_designer_proposal.md

## 0. 読了確認

Read 済みファイル:
- `design/V2/91_実装ワークログ.md` L1161-1204（T29 起票内容）
- `design/V2/REGRESSION_PREVENTION.md`（不変条件 #11 ネストアンカー禁止）
- `docs/fish/aji.html`（area_cmp・chip-wrap の既存 HTML 構造）
- `docs/area/yokohama-honmoku.html`（fia-grid の既存 HTML 構造）
- `docs/fish_area/aji-yokohama-honmoku.html`（リレーション追加先・FAQ 周辺構造）

## 1. 現状分析（調査ベース）

Read で確認した現状のリンク状態：

| 経路 | 現状 | 評価 |
|---|---|---|
| fish/* → fish_area/* | chip-wrap「エリア別の釣果」に chip-link として存在（L117） | あり・ただしページ下部で視認性低 |
| area/* → fish_area/* | fia-grid の `<a class="fia">` が fish_area へのリンクとして実装済み（L87） | あり・今週データがある魚種のみ |
| fish_area/* → 他 fish_area/* | リンクなし | 完全欠如（孤立の本質的原因） |
| fish/* area_cmp → fish_area/* | リンクなし | 欠如・自然なコンテキストで追加余地あり |

**真因の再整理**: area/* fia-grid は今週釣果がある魚種のみリンクを張る。今週釣果ゼロのコンボ（例：冬季のタコ）の fish_area は fia-grid に出現しない。また fish/* の chip-wrap はページ最下部付近にあり Google のページランク評価が薄い。fish_area/* 同士のリンクが皆無なため、クロールグラフ上でクラスタが分断されている。

**優先順位の再評価**:
1. 🔴 fish_area/* 下部リレーションセクション（fish_area 同士のリンクは完全欠如・最大インパクト）
2. 🔴 fish/* area_cmp 内リンク化（自然なコンテキストで fish_area へ誘導・追加実装が必要）
3. 🟡 area/* fia-grid の補完（今週データなし魚種への fish_area リンクが欠落）
4. 🟢 パンくず確認・index/calendar の深掘りリンク

---

## 2. fish/* area_cmp 内リンク化（🔴）

### 2-1. 既存 HTML 構造

fish/aji.html の area_cmp セクション（L111）を展開すると、各 `.ar` 行は以下の構造：

```html
<div class="area-cmp">
  <h3>エリア別の5/12(火)の釣果</h3>

  <div class="ar">
    <a class="ar-name" href="../area/koshiba.html">小柴港</a>
    <span class="ar-range">16〜107匹</span>
    <span class="ar-size">17〜26cm</span>
    <span class="ar-trips">1便</span>
    <span class="ar-ships">
      <a href="../ship/miki-maru-tsuribuneten.html">三喜丸釣船店</a>
    </span>
  </div>

  <div class="ar">
    <a class="ar-name" href="../area/yokohama-honmoku.html">横浜本牧港</a>
    <span class="ar-range">12〜92匹</span>
    <span class="ar-size">17〜32cm</span>
    <span class="ar-trips">1便</span>
    <span class="ar-ships">
      <a href="../ship/nagasakiya.html">長崎屋</a>
    </span>
  </div>
</div>
```

CSS（同ファイル L27-37）：

```css
.ar { display:flex; align-items:center; padding:9px 0;
      border-bottom:1px solid var(--bg); gap:8px; flex-wrap:wrap; }
.ar .ar-name { flex:0 0 90px; font-size:13px; font-weight:700;
               color:var(--cta); text-decoration:none; }
.ar .ar-range { flex:0 0 80px; ... }
.ar .ar-size  { flex:0 0 80px; ... }
.ar .ar-trips { flex:0 0 48px; ... }
.ar .ar-ships { flex:1 1 200px; ... }
.ar .ar-more  { color:var(--muted); font-size:11px; }
```

### 2-2. リンクを張る箇所とネストアンカー回避

`.ar` 行に新たな `<a>` を追加する際、**既存の `.ar-name`（`<a>`）・`.ar-ships` 内（`<a>`）との `<a>` のネストは禁止**（不変条件 #11）。

回避策: `.ar-ships` の後ろに新しい `<span class="ar-fa">` を追加し、その中に独立した `<a>` を置く。

```html
<!-- 変更前 -->
<div class="ar">
  <a class="ar-name" href="../area/koshiba.html">小柴港</a>
  <span class="ar-range">16〜107匹</span>
  <span class="ar-size">17〜26cm</span>
  <span class="ar-trips">1便</span>
  <span class="ar-ships"><a href="../ship/miki-maru-tsuribuneten.html">三喜丸釣船店</a></span>
</div>

<!-- 変更後 -->
<div class="ar">
  <a class="ar-name" href="../area/koshiba.html">小柴港</a>
  <span class="ar-range">16〜107匹</span>
  <span class="ar-size">17〜26cm</span>
  <span class="ar-trips">1便</span>
  <span class="ar-ships"><a href="../ship/miki-maru-tsuribuneten.html">三喜丸釣船店</a></span>
  <span class="ar-fa"><a href="../fish_area/aji-koshiba.html">小柴港のアジ釣果</a></span>
</div>
```

`<a>` 要素は `.ar` の直下ではなく `<span class="ar-fa">` の子として存在するため、`<a>` 内に `<a>` のネストは生じない。`.ar-name`（`<a>`）と `.ar-fa > a` は並列 `<a>` であり HTML5 valid。

### 2-3. リンクテキスト案と推奨

| 案 | テキスト | 文字数 | 評価 |
|---|---|---|---|
| A | `詳細 →` | 4字 | 汎用的・SEO 寄与なし |
| B | `{エリア}の{魚種}釣果`（例「小柴港のアジ釣果」）| 12字前後 | SEO 強化・キーワード明示 |
| C | `詳細を見る` | 6字 | 自然だが SEO 寄与なし |

**採用: 案 B「{エリア}の{魚種}釣果」（ユーザー判断・2026/05/13）**

理由: Search Console 出現クエリが全て「{魚種} 釣果 {関東}」型（ヤリイカ釣果関東・マルイカ釣果関東等）。アンカーテキストにも同型キーワードを含めることで Google にリンク先 fish_area ページのテーマを明示する。タップターゲット問題（後述 MAJOR-5）は padding を `8px 12px` に拡大して 36-40px 確保。情報密度の懸念はモバイル `flex-wrap` で 2 段折り返し許容。

### 2-4. リンク先 URL 生成ロジック

`{fish_slug}-{area_slug}.html` の形式。例：
- fish=「アジ」（slug: `aji`）× area=「小柴港」（slug: `koshiba`）→ `../fish_area/aji-koshiba.html`
- fish=「アジ」× area=「横浜本牧港」（slug: `yokohama-honmoku`）→ `../fish_area/aji-yokohama-honmoku.html`

fish_slug は既存の `build_fish_pages()` で使用している slug 変換ロジックと同一。area_slug は各 area/*.html のファイル名（拡張子除く）と同一。

**存在チェック方針**: `os.path.exists(f"docs/fish_area/{fish_slug}-{area_slug}.html")` で存在確認し、存在する場合のみ `ar-fa` スパンを出力する。存在しない場合は `ar-fa` 自体を出力しない（空リンクを作らない）。

### 2-5. CSS 追記

`fish_extra_css` に追記（既存 CSS に追加、上書き不要）：

```css
.ar .ar-fa { flex:0 0 auto; }
.ar .ar-fa a { font-size:11px; color:var(--cta); text-decoration:none;
               padding:2px 6px; border:1px solid var(--cta);
               border-radius:10px; white-space:nowrap; }
.ar .ar-fa a:hover { background:var(--cta); color:#fff; }
```

モバイル（`max-width:520px`）では既存の `@media` 内に `.ar .ar-fa { flex:0 0 auto; }` を追加するだけでよい（他の flex:0 0 auto 要素と同様に折り返す）。

---

## 3. area/* 魚種カードの状況確認と補完（🔴）

### 3-1. 既存構造の確認結果

`docs/area/yokohama-honmoku.html` L87 の fia-grid を確認：

```html
<div class="fia-grid">
  <a class="fia" href="../fish_area/shirogisu-yokohama-honmoku.html">
    <div class="fn">シロギス</div>
    <div class="fr">10〜180匹</div>
    <div class="fs">13〜24cm | 6件・1船宿</div>
    <div class="fb">◎長崎屋</div>
  </a>
  <a class="fia" href="../fish_area/aji-yokohama-honmoku.html">
    <div class="fn">アジ</div>
    ...
  </a>
</div>
```

**重要**: `<a class="fia">` 自体が fish_area へのリンクになっている。カード全体がリンクであり、内部に別の `<a>` はない。これは不変条件 #11 に違反しない正しい構造。

### 3-2. 現状の問題点

fia-grid は「今週釣果がある魚種のみ」表示している。今週ゼロ件のコンボ（例：冬季のシーバス、夏場のカレイ）は fia-grid に出現せず、対応する fish_area ページへの内部リンクが途切れる。

### 3-3. 補完設計

fia-grid の下に「過去の実績魚種」セクションを追加し、今週データはないが過去3年で釣果実績がある魚種 × エリアの fish_area ページへのリンクを chip-link 形式で列挙する。

```html
<!-- 追加セクション（今週ゼロ件の魚種がある場合のみ出力） -->
<h2 class="st">過去に釣れた魚（今週データなし）</h2>
<div class="chip-wrap">
  <a href="../fish_area/madako-yokohama-honmoku.html" class="chip-link">マダコ（578件）</a>
  <a href="../fish_area/seabass-yokohama-honmoku.html" class="chip-link">シーバス（42件）</a>
</div>
```

この追加により、年間の全魚種×エリアコンボが通年でリンクされる。fish_area ファイルが存在する場合のみ出力（存在チェック必須）。

CSS は既存 `.chip-wrap` / `.chip-link` を流用（追加 CSS 不要）。

---

## 4. fish_area/* 下部リレーションセクション（🟡・最大インパクト）

### 4-1. 挿入位置

`docs/fish_area/aji-yokohama-honmoku.html` の構造を確認した結果：

```
[fa-intro]
[stat-cards]
[旬カレンダー]
[combo-comment]
[船宿ランキング]
[最近の釣果]
[よくある質問]  ← ここの直前に挿入
```

FAQ の直前（`<h2 class="st">よくある質問</h2>` の前）にリレーションセクションを挿入する。FAQは固定コンテンツで末尾を締めるため、データ由来のリレーションリンクはその手前に置くのが自然。

### 4-2. HTML 構造案

```html
<!-- fish_area 下部リレーション（FAQ の直前に挿入） -->
<div class="fa-related">
  <h2 class="st">アジを他のエリアで探す</h2>
  <div class="chip-wrap">
    <a href="../fish_area/aji-kanazawa-hakkei.html" class="chip-link">金沢八景（3042件）</a>
    <a href="../fish_area/aji-kanaya.html" class="chip-link">金谷港（1639件）</a>
    <a href="../fish_area/aji-yokohama-shinyamashita.html" class="chip-link">横浜港・新山下（1414件）</a>
    <!-- 最大 TOP-6 件表示 -->
  </div>
  <h2 class="st">横浜本牧港の他の魚種</h2>
  <div class="chip-wrap">
    <a href="../fish_area/shirogisu-yokohama-honmoku.html" class="chip-link">シロギス（748件）</a>
    <a href="../fish_area/madako-yokohama-honmoku.html" class="chip-link">マダコ（578件）</a>
    <a href="../fish_area/seabass-yokohama-honmoku.html" class="chip-link">シーバス（42件）</a>
    <!-- 最大 TOP-6 件表示 -->
  </div>
</div>
```

### 4-3. 並び順と件数上限

| セクション | 並び順 | 上限 | フォールバック |
|---|---|---|---|
| 同魚種の他エリア | hist件数降順（全期間） | TOP-6 | 3件未満なら非表示 |
| 同エリアの他魚種 | hist件数降順（全期間） | TOP-6 | 3件未満なら非表示 |

表示件数を TOP-6 にする理由：chip-wrap は `flex-wrap:wrap` なので、モバイルでは 2〜3 列に自然に折り返す。それ以上は scroll が必要になり UX が悪化する。

データソース：`build_fish_area_pages()` がすでに `fish_area_summary`（魚種×エリアの全期間件数）を計算して HTML に使っているはずなので、同じデータを再利用する。追加の SQL クエリは不要（programmer 確認事項）。

### 4-4. CSS 追記

```css
/* fa_extra_css に追記 */
.fa-related { margin-bottom: 16px; }
```

既存の `.chip-wrap` / `.chip-link` を流用するため、追加 CSS は最小限（margin の調整のみ）。

---

## 5. パンくず確認（🟢）

### 5-1. 確認結果

`docs/fish_area/aji-yokohama-honmoku.html` L8 の JSON-LD を確認：

```json
{
  "@context":"https://schema.org",
  "@type":"BreadcrumbList",
  "itemListElement":[
    {"@type":"ListItem","position":1,"name":"トップ","item":"https://funatsuri-yoso.com/"},
    {"@type":"ListItem","position":2,"name":"魚種一覧","item":"https://funatsuri-yoso.com/fish/"},
    {"@type":"ListItem","position":3,"name":"アジの釣果","item":"https://funatsuri-yoso.com/fish/aji.html"},
    {"@type":"ListItem","position":4,"name":"横浜本牧港のアジ釣果","item":"https://funatsuri-yoso.com/fish_area/aji-yokohama-honmoku.html"}
  ]
}
```

**判定: BreadcrumbList JSON-LD は実装済み。4階層で正しい構造。追加作業不要。**

ページ上部のビジュアルパンくず（L59）も確認：

```html
<p class="bread">
  <a href="../index.html">トップ</a> &rsaquo;
  <a href="../fish/aji.html">アジ</a> &rsaquo;
  横浜本牧港
</p>
```

これも適切。`area/*.html` を経由しない設計（魚種 → エリア詳細の縦構造）で現状の JSON-LD と整合している。

**追加提案（任意）**: パンくずに area ページへのリンクも加えると「トップ → アジ → 横浜本牧港のアジ」だけでなく「エリア」軸からの文脈も強化できる。ただし BreadcrumbList は直線の階層を前提とするため、現状の魚種軸パンくずを変更すると JSON-LD の整合性が崩れる可能性がある。変更は不要と判断する。

---

## 6. index / calendar の深掘りリンク棚卸し（🟢）

### 6-1. index.html

`docs/index.html` は当日釣果の事実データを中心としたページ。fish_area への直接リンクは現時点で入れていない。HERO セクションのカード・ZONE B のエリア別は fish/* / area/* への誘導が主。

**追加余地**: 「今日の釣果」セクション内のエリア別サマリー行に「詳細」リンクを追加する案があるが、index は速報性を優先するページであり、fish_area への deep dive を促すより fish/* / area/* に誘導する現構造が適切。**追加不要と判断。**

### 6-2. calendar.html

calendar.html は月別・魚種別カレンダーで fish/* へのリンクが中心。fish_area への直接リンクを追加するとカレンダーの情報密度が高くなりすぎる懸念がある。

**追加不要と判断。** fish_area へのリンクは fish/* 内の chip-wrap（既存）と、今回追加する area_cmp 内リンク・fish_area 内リレーションセクションで十分にカバーできる。

---

## 7. CSS 設計まとめ

### 7-1. 変更対象ファイル（`crawler.py` 内のインライン CSS）

| CSS 変数 | 追加内容 | 行数見積 |
|---|---|---|
| `fish_extra_css` | `.ar .ar-fa` / `.ar .ar-fa a` / hover / media | 約 8 行 |
| `area_extra_css` | 追加なし（chip-wrap 流用） | 0 行 |
| `fa_extra_css` | `.fa-related` margin のみ | 約 2 行 |

### 7-2. style.css（共通）

変更なし。今回の追加は全て魚種・エリア・fish_area ページ固有のインライン `<style>` 内で完結する。共通 CSS を汚染しない。

---

## 8. 不変条件チェックポイント

### 8-1. #11 ネストアンカー禁止の回避確認

| 変更箇所 | 親要素 | 追加 `<a>` | 既存 `<a>` との関係 | 判定 |
|---|---|---|---|---|
| fish/* area_cmp 各行 | `<div class="ar">` | `<span class="ar-fa"><a>` | `.ar-name`（`<a>`）と並列 | OK |
| area/* 過去実績チップ | `<div class="chip-wrap">` | `<a class="chip-link">` | fia-grid 外に独立 | OK |
| fish_area/* リレーションセクション | `<div class="fa-related">` | `<a class="chip-link">` | FAQ 直前・独立 | OK |

全ての追加 `<a>` は既存 `<a>` と並列配置であり、ネストは生じない。

### 8-2. validate_output.py に追加すべき不変条件案

既存 21 条件に以下を追加することを推奨する（programmer・reviewer に判断を委ねる）：

```
不変条件 22（案）: fish/*.html サンプル（アジ・マダイ・シロギス）
  area_cmp 内の .ar 行のうち fish_area ページが存在するエリアの行に
  .ar-fa リンクが含まれること（T29 area_cmp リンク化の退行検知）

不変条件 23（案）: fish_area/*.html サンプル（aji-yokohama-honmoku 等）
  FAQ の直前に .fa-related セクションが存在し、
  chip-link が 1 件以上含まれること（T29 リレーションセクションの退行検知）
```

---

## 9. ユーザー判断ポイント

以下 3 点はユーザーが選択・承認してから実装に進むこと。

### 判断 A: area_cmp のリンクテキスト ✅ 確定（2026/05/13）

- 採用: **「{エリア}の{魚種}釣果」**（例「小柴港のアジ釣果」・12字前後）
- 採用理由: Search Console 出現クエリ「{魚種} 釣果 関東」型に合わせて anchor text にキーワードを含める SEO 強化
- 折り返し懸念: モバイル `flex-wrap` で 2 段許容
- タップターゲット: padding `2px 8px` → `8px 12px` 拡大で 36-40px 確保（MAJOR-5 対応）

### 判断 B: fish_area リレーションセクションの挿入位置

- 選択肢 1: FAQ の直前（推奨）
- 選択肢 2: 「最近の釣果」セクションの直後・FAQ の直前（同位置・セクション区切り変更なし）
- 選択肢 3: 旬カレンダーの直後

推奨は FAQ 直前。理由：旬カレンダーは当該コンボの主要コンテンツであり、その後に当該コンボ周辺のリンクを置くと「さらに調べる」の自然な導線になる。FAQ はページを締めるコンテンツとして最後に置くのが適切。

### 判断 C: 同魚種・同エリアのリレーション件数上限

- 選択肢: TOP-3 / TOP-6（推奨）/ TOP-10 / 全件
- 推奨: TOP-6。モバイルで chip が 2〜3 行に収まる適度な量。
- 懸念: 人気魚種（アジ・マダイ）は 39 エリア以上のコンボがあるため全件表示は過多。

---

## 10. programmer 作業量見積

### 変更ファイル

| ファイル | 変更内容 | 想定 diff 行数 |
|---|---|---|
| `crawler.py` `build_fish_pages()` | area_cmp ループ内に fish_area 存在チェック + `ar-fa` span 出力追加 | +30〜40 行 |
| `crawler.py` `build_fish_pages()` の `fish_extra_css` | `.ar-fa` スタイル追加 | +8 行 |
| `crawler.py` `build_area_pages()` | 過去実績魚種チップセクション追加（fish_area 存在チェック込み） | +25〜35 行 |
| `crawler.py` `build_fish_area_pages()` | FAQ 直前にリレーションセクション出力追加 | +30〜40 行 |
| `crawler.py` `build_fish_area_pages()` の `fa_extra_css` | `.fa-related` margin | +2 行 |
| `crawl/validate_output.py` | 不変条件 22・23 追加（任意） | +20 行 |

**合計**: 約 115〜145 diff 行。1 worktree で全変更を一括実装可能な規模。

### worktree 推奨

複数ファイルへの同時変更かつ validate_output.py の改修も伴うため、worktree 使用を推奨する。main ブランチを汚染せずに reviewer チェックを受けてからマージできる。

### 実装順序（退行リスク最小化）

1. `build_fish_area_pages()` リレーションセクション追加（影響範囲が fish_area/* に限定・最初に実装）
2. `build_fish_pages()` area_cmp リンク化（fish/* に影響・次に実装）
3. `build_area_pages()` 過去実績チップ追加（area/* に影響）
4. `validate_output.py` 不変条件追加
5. `python crawl/validate_output.py` 全 PASS 確認
6. commit・push

### 推奨テスト

```bash
python crawler.py --html-only
python crawl/validate_output.py
# 手動確認: docs/fish/aji.html の area_cmp 各行に .ar-fa リンク存在
# 手動確認: docs/area/yokohama-honmoku.html に今週ゼロ魚種へのチップ存在（あれば）
# 手動確認: docs/fish_area/aji-yokohama-honmoku.html の FAQ 直前に .fa-related 存在
```

---

## 11. AdSense 観点での優先度判断

T29 の目的はインデックス未登録の fish_area/* を Google に認識させること。

最大インパクト順：

1. **fish_area/* 内リレーションセクション**（section 4）: fish_area 同士が相互リンクになることで、クロールグラフ上のクラスタが形成される。1 ページから他の fish_area へ到達できるようになり、Googlebot が芋づる式に全 fish_area をクロールする可能性が高まる。
2. **fish/* area_cmp 内リンク**（section 2）: 既存の chip-wrap よりも「エリア別の当日釣果」というコンテキストで自然に fish_area へ誘導でき、ページランクの伝達効率が上がる。
3. **area/* 過去実績チップ補完**（section 3）: 今週データがない季節でも fish_area へのリンクが維持される。通年での内部リンク安定性を確保する。

3 点をセットで実装すること。部分実装でも効果はあるが、Google Search Console で「参照元ページ: 検出されませんでした」が解消するまでには実装後 1〜2 週間のクロールサイクルが必要。

---

**作成日**: 2026/05/13
**作成者**: designer (Agent) + pm
**ステータス**: ユーザー承認・判断待ち（判断 A/B/C の 3 点）
**次ステップ**: ユーザーが判断 A/B/C を選択 → programmer 実装 → reviewer 検証 → validate_output.py 全 PASS → commit
