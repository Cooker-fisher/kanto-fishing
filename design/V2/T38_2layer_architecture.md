# T38: 2層アーキテクチャ設計（SEO/内部リンク改善）

## 0. 背景・ユーザー指摘

Google Search Console データ（funatsuri-yoso.com・3か月）:
- 全7クエリ・19表示・**0クリック**
- 平均掲載順位 **12位**（2ページ目トップ）
- 検索クエリは全て想定ターゲット直撃: 「ヤリイカ 釣果 関東」「マルイカ 釣果 関東」「真鯛 船釣り 関東」「アジ 関東 釣果」等

researcher 調査結果（事実ベース）:
- **fish_area: 258本**
- 内部リンク: index→fish_area 3件・fish/index→fish_area 0件・area/index→fish_area 0件
- fa-related: **199本（77%）が閾値≥3で非表示**
- パンくず: area/ ページへのリンクなし
- fish ページ:
  - h1 タグが全ページに無い（h2のみ）
  - title に「船釣り」キーワード無し
  - placeholder path で「関東」「釣果」も消える

**ユーザー指摘の本質:**
> 毎回サイトを生成するため、釣果情報が無いコンボや魚種に対して、リンクが生成されない、内容が無いという根本問題。よくある質問なども、生成ベースでやっているため、ネタが少ない場合は、内容がチープになる。固定情報と生成情報という2段階にして、リンクが常にある状況を作り出すほうが重要。

## 1. 設計原則

### 全ページ共通: 2層アーキテクチャ
- **層1: 固定セクション（常駐・データ非依存）** ← Google が常に同じ内部リンク・コンテンツを見られる骨格
- **層2: 生成セクション（データから肉付け）** ← 当日釣果・ランキング・チャート等

### 廃止すべき「条件付き非表示」
- `fa-related` の ≥3件閾値（→ 廃止：固定リンク常駐に置換）
- fish の「エリア別の釣果」chip-wrap が実績ある時だけ生成（→ 廃止：全 fish_area 一覧を常駐）
- area の fia-grid が実績ある魚種だけ表示（→ 補強：固定セクションで全fish_area一覧追加）
- FAQ がデータ次第でチープ化（→ 固定文章を必ず先に置き、データは追記形式）

## 2. ページ別仕様

### 2.1 fish/{魚種}.html

**層1（固定セクション）:**
- fish-hero（既存・hist_rows ベース）
- 旬カレンダー（既存・hist_rows フォールバック済み）
- area-cmp（既存・T27で全51種展開済み）
- **fish-all-areas（新規）**: 全エリア×{魚種} fish_area 一覧（常駐）★
- **fish-related（新規）**: 関連魚種リンク（常駐）★
- 釣り方ガイド（既存・fish_tackle.json ベース）
- FAQ固定文（既存・hist_rows ベース固定化済み）
- 主要船宿TOP-N（既存）

**層2（生成セクション）:**
- 当日N件・船宿ランキング・直近7日チャート

#### fish-all-areas HTML

```html
<section class="fish-areas-all">
  <h2 class="st">エリア別の{魚種}釣果情報</h2>
  <p class="faa-note">{魚種}の釣果情報が確認できる関東の船釣りエリア一覧です。</p>
  <div class="chip-wrap">
    <a href="../fish_area/aji-kanazawa-hakkei.html" class="chip-link">金沢八景（3,042件）</a>
    <a href="../fish_area/aji-kanaya.html" class="chip-link">金谷港（1,639件）</a>
    <!-- hist_rows 件数降順 全件 · fish_area/*.html 存在するもの全て -->
  </div>
</section>
```

データソース: `hist_rows` の `tsuri_mono=fish` を `area` 別集計 → 件数降順
対象: `docs/fish_area/{fish_slug}-{area_slug}.html` が存在するもの**全件**（件数下限なし）

#### fish-related HTML

```html
<section class="fish-related-species">
  <h2 class="st">{魚種}と合わせて狙える魚</h2>
  <div class="chip-wrap">
    <a href="madai.html" class="chip-link">マダイ</a>
    <a href="isaki.html" class="chip-link">イサキ</a>
    <!-- FISH_RELATED_GROUPS マップから生成 -->
  </div>
</section>
```

#### FISH_RELATED_GROUPS 定数（手書きマスタ）

```python
FISH_RELATED_GROUPS = {
    "アジ":     ["サバ", "イワシ", "シロギス", "タチウオ"],
    "マダイ":   ["イサキ", "ハナダイ", "ワラサ", "カワハギ"],
    "タチウオ": ["アジ", "サバ", "スルメイカ"],
    "シロギス": ["アジ", "マダコ", "ハゼ"],
    "マルイカ": ["ヤリイカ", "スルメイカ", "アオリイカ"],
    "ヤリイカ": ["マルイカ", "スルメイカ", "ムギイカ", "アオリイカ"],
    "ムギイカ": ["ヤリイカ", "マルイカ", "スルメイカ"],
    "ワラサ":   ["イナダ", "カンパチ", "サワラ"],
    "イナダ":   ["ワラサ", "カンパチ", "シイラ"],
    "カサゴ":   ["メバル", "クロムツ", "マハタ"],
    # フェーズB で全51種展開
}
```

### 2.2 area/{エリア}.html

**層1（固定セクション）:**
- area-hero（既存）
- 旬カレンダー（既存・SEASON_DATA フォールバック済み）
- fia-grid（既存・今週データあり魚種・層2）
- **area-all-fish（新規）**: 全{エリア}×魚種 fish_area 一覧（常駐）★
- エリアガイド（既存・area_description.json ベース）
- アクセス情報（既存・T31実装済み: 最寄りIC/駅）
- 主要船宿リンク（既存）
- FAQ固定文（既存・hist_rows ベース固定化済み）

#### area-all-fish HTML

```html
<section class="area-all-fish">
  <h2 class="st">{エリア}で釣れる魚（全実績）</h2>
  <div class="chip-wrap">
    <a href="../fish_area/aji-kanazawa-hakkei.html" class="chip-link">アジ（3,042件）</a>
    <a href="../fish_area/tachiuo-kanazawa-hakkei.html" class="chip-link">タチウオ（1,516件）</a>
    <!-- hist_rows 件数降順 全件 · fish_area/*.html 存在するもの全て -->
  </div>
</section>
```

データソース: `hist_rows` の `area=area` を `tsuri_mono` 別集計 → 件数降順
対象: `docs/fish_area/{fish_slug}-{area_slug}.html` が存在するもの**全件**

T29「過去実績チップ補完」と統合:
- T29 の chip 補完セクション（今週ゼロ件のみ表示）を廃止し、本セクションに統合
- fia-grid（今週データあり魚種）と area-all-fish（全実績 chip）が並立 = 「現在の活況」と「歴史的な豊富さ」の両方を伝える

### 2.3 fish_area/{コンボ}.html

**層1（固定セクション）:**
- **fa-breadcrumb-3axis（改修）**: 魚種軸・エリア軸の2軸表示★
- fa-intro（既存・area_description ベース）
- stat-cards（既存）
- 旬カレンダー（既存）
- combo-comment（既存）
- 船宿ランキング（既存）
- 最近の釣果（既存・層2: データから肉付け）
- **fa-related-3axis（改修）**: 閾値廃止・全件常駐★
- FAQ固定文（既存・hist_rows ベース固定化済み）

#### fa-related-3axis HTML（閾値廃止・全件常駐）

T29 のフォールバック条件（≥3件）を完全廃止。存在する fish_area ページへのリンクを件数に関わらず全件表示する。

```html
<section class="fa-related">
  <!-- 軸1: 同魚種・他エリア（全件・件数降順） -->
  <h2 class="st">アジを他のエリアで探す</h2>
  <div class="chip-wrap">
    <a href="../fish_area/aji-kanazawa-hakkei.html" class="chip-link">金沢八景（3,042件）</a>
    <a href="../fish_area/aji-kanaya.html" class="chip-link">金谷港（1,639件）</a>
    <!-- 件数1件でも存在するもの全件 · 自コンボ除外 -->
  </div>
  <!-- 軸2: 同エリア・他魚種（全件・件数降順） -->
  <h2 class="st">横浜本牧港の他の魚種</h2>
  <div class="chip-wrap">
    <a href="../fish_area/shirogisu-yokohama-honmoku.html" class="chip-link">シロギス（748件）</a>
    <!-- 全件 · 自コンボ除外 -->
  </div>
  <!-- 軸3: 関連魚種（FISH_RELATED_GROUPS から生成） -->
  <h2 class="st">アジと合わせて狙える魚</h2>
  <div class="chip-wrap">
    <a href="../fish/tachiuo.html" class="chip-link">タチウオ</a>
    <a href="../fish/shirogisu.html" class="chip-link">シロギス</a>
    <!-- fish/ ページへのリンク（fish_area でなく fish） -->
  </div>
</section>
```

**閾値廃止の根拠:**
- 現状77%(199本)が非表示 = Google から見て孤立
- 「1件しかない」コンボも fish_area ページが存在すれば SEO クロールの経路になる
- ユーザーへの価値: 隣接コンボを知るナビとして件数の少なさは妨げにならない
- ページ肥大化懸念: chip-wrap の `flex-wrap` で自然に折り返し、高さは自動調整

#### fa-breadcrumb-3axis HTML（パンくず2軸化）

```html
<!-- 現状（魚種軸のみ） -->
<p class="bread">
  <a href="../index.html">トップ</a> ›
  <a href="../fish/aji.html">アジ</a> ›
  横浜本牧港
</p>

<!-- 改修後（魚種軸 + エリア軸の2軸） -->
<p class="bread">
  <a href="../index.html">トップ</a> ›
  <a href="../fish/aji.html">アジ</a> ›
  横浜本牧港
  <span class="bread-sep"> | </span>
  <a href="../area/yokohama-honmoku.html">横浜本牧港エリア</a> ›
  アジ
</p>
```

BreadcrumbList JSON-LD は変更しない（構造化データは直線階層が前提・現状の fish 軸 4階層を維持）。ビジュアルパンくずのみ2軸表示。

### 2.4 fish/index.html（フェーズC）

**層1追加セクション: 全 fish_area 一覧（魚種別グルーピング）**

```html
<section class="all-fisharea-index">
  <h2 class="st">魚種×エリア別の釣果情報</h2>
  <p class="afi-note">エリアを絞って釣果情報を確認できます。魚種を選んでエリアを絞り込んでください。</p>
  <div class="afi-group">
    <h3 class="afi-fish">アジ</h3>
    <div class="chip-wrap">
      <a href="../fish_area/aji-kanazawa-hakkei.html" class="chip-link">金沢八景</a>
      <a href="../fish_area/aji-kanaya.html" class="chip-link">金谷港</a>
      <!-- 件数上位8件 -->
    </div>
  </div>
  <!-- 全魚種繰り返し -->
</section>
```

魚種順: ALL_FISH リスト順（または hist_rows 件数降順）
エリアの表示件数上限: 各魚種 TOP-8

### 2.5 area/index.html（フェーズC）

**層1追加セクション: 全 fish_area 一覧（エリア別グルーピング）**

エリアごとにグルーピング・各エリア TOP-8

## 3. 不変条件への影響

### 廃止・変更すべき条件

| 不変条件 | 現状 | 変更方針 |
|---|---|---|
| 22 (fish/* area_cmp内 .ar-fa) | T29で追加済み | 維持（変更なし） |
| 23 (fish_area/* fa-related chip-link 1件以上) | T29で追加済み | 維持（閾値廃止後もゼロ件は発生しない見込み）|

### 新規追加すべき条件

| 番号 | チェック対象 | 検証内容 |
|---|---|---|
| 24 | fish/{魚種}.html サンプル（aji・madai・shirogisu）| `.fish-areas-all` セクション存在 + `.chip-link` 1件以上 |
| 25 | area/{エリア}.html サンプル（kanazawa-hakkei・urayasu）| `.area-all-fish` セクション存在 + `.chip-link` 1件以上 |
| 26 | fish/index.html | `.all-fisharea-index` セクション存在 + `.afi-group` 3件以上（フェーズC後）|
| 27 | area/index.html | `.all-fisharea-area-index` セクション存在 + `.afi-group` 3件以上（フェーズC後）|

## 4. データソース整理

| 固定セクション | データソース | 既存/新規 |
|---|---|---|
| fish-all-areas | hist_rows（data/V2/*.csv 全件集計）| 既存データ・新規集計 |
| fish-related | FISH_RELATED_GROUPS 定数（crawler.py 内手書き）| 新規定数 |
| area-all-fish | hist_rows（data/V2/*.csv 全件集計）| 既存データ・新規集計 |
| fa-related-3axis 軸1・2 | fish_area_summary（build_fish_area_pages が既ロード）| 既存データ・閾値廃止 |
| fa-related-3axis 軸3 | FISH_RELATED_GROUPS 定数 | 新規定数（fish-related と共有） |

## 5. title/description 改善（前回 P1・P2 継承）

### rich path（直近7日データあり）

```
Before: 関東の{魚種}釣果・船宿ランキング【今週N件】| 船釣り予想
After:  関東の{魚種}船釣り釣果【今週N件・M船宿】| 船釣り予想
```

### placeholder path（シーズンオフ）

```
Before: {魚種}の船釣り情報・実績・釣り方 | 船釣り予想
After:  関東の{魚種}船釣り釣果・シーズン・釣り方 | 船釣り予想
```

### description（rich path）

```
Before: 関東エリアの{魚種}釣果情報。今週N件・最高M匹。船宿別ランキング・昨年同週比をリアルタイム更新。
After:  関東エリアの{魚種}船釣り釣果情報。今週N件・M船宿。{top_area}エリアを中心に船宿別釣果ランキングを毎日更新。
```

### h1 タグ追加

fish-hero の `<h2>` は維持（不変条件10との整合）。パンくず直前に `<h1 class="page-h1">関東の{魚種}船釣り釣果情報</h1>` を追加。

```css
.page-h1 {
  font-size: 14px;
  font-weight: 700;
  color: var(--sub);
  padding: 8px 0 0;
  margin: 0;
  line-height: 1.4;
}
```

## 6. 実装フェーズ分割

### フェーズA（即効性高・1セッション完了可能・4〜6時間）

| 施策 | 詳細 | diff行数概算 |
|---|---|---|
| A-1 | fa-related 閾値廃止（≥3 → ≥1） | 2行 |
| A-2 | fa-related 軸3追加（FISH_RELATED_GROUPS 主要15種） | 約50行 |
| A-3 | fa-breadcrumb エリア軸追加 | 約10行 |
| A-4 | fish-all-areas セクション | 約40行 |
| A-5 | area-all-fish セクション | 約40行 |
| A-6 | 不変条件 24・25 追加 | 約30行 |
| A-7 | title/description 改善（P1・P2） | 約20行 |
| A-8 | h1 page-h1 追加 | 約15行 |

**実装着手順（SEO 効果の大きさ順）:**
1. A-1（最小変更で最大効果: 199本の孤立解消）
2. A-4・A-5（fish・area ページから fish_area への常駐リンク新設）
3. A-2（3軸目・fish 間の相互リンク）
4. A-3（パンくず・視認性改善）
5. A-7・A-8（title/description/h1 改善）
6. A-6（gatekeeper 追加）

### フェーズB（次セッション・6〜10時間）

- B-1: FISH_RELATED_GROUPS 全51種定義
- B-2: fish-related セクション（fish/{魚種}.html に常駐）
- B-3: fish_area パンくず JSON-LD 2軸化の検討

### フェーズC（複数セッション・8〜12時間）

- C-1: fish/index 全fish_area一覧（P6'）
- C-2: area/index 全fish_area一覧（P7'）
- C-3: 不変条件 26・27 追加

## 7. 「無料=事実」境界の遵守確認

| セクション | 表示内容 | 境界判定 |
|---|---|---|
| fish-all-areas chip | `{エリア名}（N件）` | 事実（件数）✅ |
| area-all-fish chip | `{魚種}（N件）` | 事実（件数）✅ |
| fish-related chip | 魚種名のみ | 事実（存在）✅ |
| fa-related chip | `{エリア/魚種}（N件）` | 事実（件数）✅ |
| パンくず2軸 | エリア名・魚種名のみ | 事実（名称）✅ |

固定セクションに予測・分析・評価は一切含まない。

## 8. 既存T30・T31の思想統一確認

T30（fish_area FAQ）・T31（area FAQ）は「当日スナップショット依存 → hist_rows 全期間固定」への移行だった。今回の2層設計は同じ思想を**内部リンク構造**に適用。FAQ固定化（コンテンツ）+ 内部リンク常駐化（リンク構造）の2本柱で「データなし時でも骨格が壊れないサイト」を実現する。

## 9. 想定 SEO 効果

### 短期（1〜4週間）
- クロール増加: パンくず area/ リンク + fa-related 緩和により Google が fish_area ページへの参照元を「検出あり」に更新
- インデックス増加: 「Discovered - currently not indexed」→「Indexed」のパスを辿れる

### 中期（1〜3ヶ月）
- 掲載順位改善: 12位 → 10位以内入り
- CTR 改善: 0% → 1〜2%

### 長期（3〜6ヶ月）
- 258本 × 月10〜50UU = **月2,580〜12,900UU ポテンシャル**
- AdSense 審査: コンテンツ充実度（FAQPage JSON-LD 付き 258ページ）

## 10. 実装時の注意事項（regression リスク）

- fish-hero の `<h2>` タグを `<h1>` に変えない（不変条件10・page-h1 は fish-hero の外）
- fi-areas / fi-areas-chip の `<a>` は必ず `<a class="fi-card">` の外に置く（不変条件11）
- fa-related 閾値緩和後に `python crawl/validate_output.py` を実行して不変条件23 を確認
- A-1 の commit と A-2〜A-8 の commit を分ける（rollback 容易性）
