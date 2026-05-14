# T38: 2層アーキテクチャ設計（SEO/内部リンク改善）v2

## 0. 背景

Google Search Console データ（funatsuri-yoso.com・3か月）:
- 全7クエリ・19表示・**0クリック**
- 平均掲載順位 **12位**（2ページ目トップ）
- 検索クエリは全て想定ターゲット直撃: 「ヤリイカ 釣果 関東」「マルイカ 釣果 関東」「真鯛 船釣り 関東」「アジ 関東 釣果」等

researcher 調査結果:
- **fish_area: 258本**
- 内部リンク: index→fish_area 3件・fish/index→fish_area **0件**・area/index→fish_area **0件**
- fa-related: **199本（77%）が閾値≥3で非表示**
- パンくず: area/ ページへのリンクなし
- fish ページ: h1 タグなし・「船釣り」キーワード無し

**ユーザー指摘の本質:**
> 釣果情報が無いコンボや魚種に対してリンクが生成されない・内容が無い。固定情報と生成情報の2段階にして、リンクが常にある状況を作る方が重要。

## 1. 設計原則

### 2層アーキテクチャ
- **層1: 固定セクション（常駐・データ非依存）** ← Google が常に同じ内部リンク・コンテンツを見られる骨格
- **層2: 生成セクション（データから肉付け）** ← 当日釣果・ランキング・チャート

### 廃止する条件付き非表示
- `fa-related` の ≥3件閾値（→ 廃止：1件以上で常駐）
- fish の「エリア別の釣果」chip-wrap が実績ある時だけ生成（→ 全 fish_area 一覧を常駐）
- area の fia-grid が実績ある魚種だけ表示（→ 補強：area-all-fish で全魚種常駐）
- area の T29 past_fish_section_html（→ area-all-fish に統合・廃止）
- FAQ がデータ次第でチープ化（→ 固定文章を必ず先に置き、データは追記形式）

### 実績あり/無し折り畳み機構
全ての固定セクション内 chip リストは以下構造:
- **上段（実績あり）**: 直近7日 catches に該当 chip が存在するもの
- **下段（折り畳み）**: 過去実績はあるが直近7日にはないもの → `<details class="fold-chips">` で隠す

**理由:** 全件常駐で SEO クロール性は確保しつつ、UX として「いま釣れている」と「過去実績」を視覚分離。

### 表記ルール
- **件 → 便** 統一（chip括弧内・description・件数表現すべて）
  - 例: `金沢八景（3,042便）`, `今週24便・15船宿`
- 釣り船は「便」が出船単位として自然・「件」は釣行報告件数と誤解されやすいため

### 県emoji slot
- エリアchip に `<img class="chip-pref">` を魚種emoji と同形式で挿入
- 画像: `docs/assets/area/{県}_emoji.webp`（4県: kanagawa/tokyo/chiba/shizuoka・既配置済み）
- エリア→県マッピング辞書を crawler.py 定数として持つ

## 2. ページ別仕様

### 2.1 fish/{魚種}.html

**層1（固定セクション）:**
- fish-hero（既存・h2維持・絵emoji付き）
- 旬カレンダー（既存）
- area-cmp（既存・T27で全51種展開済み）
- **fish-all-areas（新規・折り畳み付き）** ★
- **fish-related（新規・同港共起ベース）** ★
- 釣り方ガイド（既存）
- FAQ固定文（既存・T24-T26で hist_rows ベース固定化済み）
- 主要船宿TOP-N（既存）

**層2:** 当日N便・船宿ランキング・直近7日チャート

#### fish-all-areas

```html
<section class="fish-areas-all">
  <h2 class="st">エリア別の{魚種}釣果情報</h2>
  <p class="faa-note">{魚種}の釣果情報が確認できる関東の船釣りエリア一覧です。便数は過去3年の実績報告数。</p>

  <p class="tier-label">★ 今週実績あり（N便）</p>
  <div class="chip-wrap">
    <a href="../fish_area/aji-kanazawa-hakkei.html" class="chip-link chip-area">
      <img src="../assets/area/kanagawa_emoji.webp" alt="" class="chip-pref" width="14" height="14" loading="lazy" onerror="this.style.display='none'">
      金沢八景（3,042便）
    </a>
    <!-- 直近7日 catches に該当エリアが存在するものを件数降順 -->
  </div>

  <details class="fold-chips">
    <summary>過去実績あり（今週ゼロ・N便）を表示</summary>
    <div class="chip-wrap">
      <a href="../fish_area/aji-kanaya.html" class="chip-link chip-area">
        <img src="../assets/area/chiba_emoji.webp" alt="" class="chip-pref" width="14" height="14" loading="lazy" onerror="this.style.display='none'">
        金谷港（1,639便）
      </a>
      <!-- hist_rows 件数降順 全件 · 上段に含まれないもの全て -->
    </div>
  </details>
</section>
```

**データソース:** `hist_rows` の `tsuri_mono=fish` を `area` 別集計 → 件数降順
**対象:** `docs/fish_area/{fish_slug}-{area_slug}.html` が存在するもの**全件**（件数下限なし）
**上段判定:** 直近7日 catches に該当エリアが含まれる
**下段（折り畳み）:** 上段に含まれないもの全て

#### fish-related（同港共起ベース）

```html
<section class="fish-related-species">
  <h2 class="st">{魚種}と合わせて釣れる魚</h2>

  <p class="tier-label">★ 今週実績あり（N便）</p>
  <div class="chip-wrap">
    <a href="madai.html" class="chip-link">
      <img src="../assets/fish/madai/madai_emoji.webp" alt="" class="chip-emoji" width="14" height="14" loading="lazy" onerror="this.style.display='none'">
      マダイ（512便）
    </a>
    <!-- 同港共起 TOP-N（直近7日含む）-->
  </div>

  <details class="fold-chips">
    <summary>過去実績あり（今週ゼロ・N便）を表示</summary>
    <div class="chip-wrap">
      <!-- 同港共起 過去実績 -->
    </div>
  </details>
</section>
```

**データソース:**
1. `{魚種}` の主要エリア（hist_rows 件数降順 TOP-N エリア）を取得
2. それらエリアの fish_area から、`{魚種}` 以外の魚種を抽出
3. 共起便数を集計 → 件数降順 → fish/{slug}.html が存在するもののみ
4. 上段=直近7日 catches に共起ある魚種、下段=過去実績のみの魚種

**廃止する設計:** `FISH_RELATED_GROUPS` 手書き辞書（domain agent 指摘・10グループ中5グループに違和感）

**理由:**
- 「アジ→タチウオ」のようなタックル別系統の組合せが手書き辞書では避けられない
- 同港共起ベースなら「現場で本当に同船で釣れる魚種」が自動的に並ぶ
- fish/ ページが存在する魚種のみリンク化されるため emoji 必ず表示・55種内自動収束
- 新魚種追加時の手動メンテ不要

### 2.2 area/{エリア}.html

**層1:**
- area-hero（既存）
- 旬カレンダー（既存）
- fia-grid（既存・今週データあり魚種・層2）
- **area-all-fish（新規・折り畳み付き）** ★
- エリアガイド（既存）
- アクセス情報（既存・T31）
- 主要船宿リンク（既存）
- FAQ固定文（既存・T31）

#### area-all-fish

```html
<section class="area-all-fish">
  <h2 class="st">{エリア}で釣れる魚（全実績）</h2>

  <p class="tier-label">★ 今週実績あり（N便）</p>
  <div class="chip-wrap">
    <a href="../fish_area/aji-kanazawa-hakkei.html" class="chip-link">
      <img src="../assets/fish/aji/aji_emoji.webp" alt="" class="chip-emoji" width="14" height="14" loading="lazy" onerror="this.style.display='none'">
      アジ（3,042便）
    </a>
    <!-- 直近7日 catches に該当魚種ある -->
  </div>

  <details class="fold-chips">
    <summary>過去実績あり（今週ゼロ・N便）を表示</summary>
    <div class="chip-wrap"><!-- 過去実績のみ --></div>
  </details>
</section>
```

**データソース:** `hist_rows` の `area={エリア}` を `tsuri_mono` 別集計 → 件数降順
**T29 past_fish_section_html との関係:** **廃止**し本セクションに統合（不変条件22 は維持・area_cmp の ar-fa は別箇所）

### 2.3 fish_area/{コンボ}.html

**層1:**
- **fa-breadcrumb-3axis（改修・パンくず2軸）** ★
- fa-intro（既存）
- stat-cards・旬カレンダー・combo-comment・船宿ランキング（既存）
- 最近の釣果（既存・層2）
- **fa-related-3axis（改修・閾値廃止・全件常駐・折り畳み付き）** ★
- FAQ固定文（既存・T30）

#### fa-related-3axis

```html
<section class="fa-related">
  <!-- 軸1: 同魚種・他エリア -->
  <h2 class="st">{魚種}を他のエリアで探す</h2>
  <p class="tier-label">★ 今週実績あり（N便）</p>
  <div class="chip-wrap">
    <a class="chip-link chip-area"><img class="chip-pref">{エリア}（N便）</a>
  </div>
  <details class="fold-chips">
    <summary>過去実績あり（今週ゼロ・N便）を表示</summary>
    <div class="chip-wrap"><!-- 過去実績 --></div>
  </details>

  <!-- 軸2: 同エリア・他魚種 -->
  <h2 class="st">{エリア}で実績のある他の魚種</h2>
  <p class="tier-label">★ 今週実績あり（N便）</p>
  <div class="chip-wrap"><!-- 直近7日 --></div>
  <details class="fold-chips"><summary>過去実績あり（今週ゼロ・N便）を表示</summary>
    <div class="chip-wrap"><!-- 過去実績 --></div>
  </details>

  <!-- 軸3: 関連魚種（同港共起） -->
  <h2 class="st">{魚種}と合わせて釣れる魚</h2>
  <div class="chip-wrap">
    <a href="../fish/{slug}.html" class="chip-link"><img class="chip-emoji">{魚種}（N便）</a>
    <!-- 同港共起 TOP-4-6 (fish-related と同じロジック) -->
  </div>
</section>
```

**閾値廃止:** ≥3件 → 1件以上で常駐（199本/77% の孤立解消）
**軸2 ラベル変更:** 「{エリア}の他の魚種」→「**{エリア}で実績のある他の魚種**」（domain指摘C・「合わせて」誤解回避）
**軸3:** 同港共起 fish-related と同一ロジック・リンク先 fish/{slug}.html

#### fa-breadcrumb-3axis

```html
<p class="bread">
  <a href="../index.html">トップ</a> ›
  <a href="../fish/aji.html">アジ</a> ›
  横浜本牧港
  <span class="bread-sep"> ／ </span>
  <a href="../area/yokohama-honmoku.html">横浜本牧港エリア</a> ›
  アジ
</p>
```

**区切り文字:** `|` → `／` に変更（domain指摘D・スマホ折り返し時の誤読防止）
**JSON-LD BreadcrumbList:** 不変（直線階層維持・JSON-LD は構造化データの優先源・Google公式仕様準拠）

## 3. 県emoji slot 仕様

### 配置
- mockup レビュー用: `design/V2/area_{県}_emoji.webp`
- プロダクション用: `docs/assets/area/{県}_emoji.webp`
- 4県: kanagawa, tokyo, chiba, shizuoka（128px webp・既配置）

### CSS
```css
.chip-pref { width: 14px; height: 14px; object-fit: contain; flex-shrink: 0; }
```

### エリア→県マッピング（crawler.py 定数）

```python
AREA_TO_PREFECTURE = {
    # 神奈川
    '金沢八景': 'kanagawa', '横浜本牧港': 'kanagawa', '川崎': 'kanagawa',
    '久里浜': 'kanagawa', '茅ヶ崎': 'kanagawa', '小田原': 'kanagawa',
    '下浦': 'kanagawa', '葉山': 'kanagawa', '平塚': 'kanagawa',
    '剣崎': 'kanagawa', '佐島': 'kanagawa', '横須賀': 'kanagawa',
    # 東京
    '羽田': 'tokyo', '深川': 'tokyo', '江戸川': 'tokyo',
    # 千葉
    '金谷港': 'chiba', '浦安': 'chiba', '大原': 'chiba', '勝山': 'chiba',
    '館山': 'chiba', '洲崎': 'chiba', '勝浦': 'chiba', '片貝': 'chiba',
    '飯岡': 'chiba', '鴨川': 'chiba', '和田浦': 'chiba',
    '富津': 'chiba', '木更津': 'chiba', '千倉': 'chiba',
    # 静岡
    '伊東': 'shizuoka', '熱海': 'shizuoka', '網代': 'shizuoka',
    '下田': 'shizuoka', '稲取': 'shizuoka', '沼津': 'shizuoka',
    '御前崎': 'shizuoka', '南伊豆': 'shizuoka',
    # 茨城（県emoji 未作成・将来追加）
    '鹿島': None, '日立': None, '波崎': None, '大洗': None,
}
```

未マッピング・None のエリアは `chip-pref` img を出力しない（onerror で隠す or 出力スキップ）。

### 実装時の追加対応
- 茨城県 emoji の作成依頼（mockup段階では None で省略）
- area_description.json に `prefecture` フィールド追加して一元管理する案も検討

## 4. データソース整理

### hist_rows 集計の共有戦略

**reviewer C-2 指摘:** `_load_historical_catches()` を build_fish/area/fish_area_pages で個別呼び出ししている問題。

**改善:**
1. `hist_rows` を crawler.py のメインスコープで1回ロード
2. `fish_area_summary = {(fish, area): cnt}` を派生集計（1回計算）
3. 各 build_*_pages 関数に引数として渡す
4. CSV全件読み込みは1回のみ・計算量 O(N) → O(1) クエリ参照

```python
# crawler.py メイン
hist_rows = _load_historical_catches()  # 1回のみ
fish_area_summary = compute_fish_area_summary(hist_rows)
fish_top_areas = compute_fish_top_areas(hist_rows)  # fish-related 用
area_top_fishes = compute_area_top_fishes(hist_rows)  # area-all-fish 用

build_fish_pages(hist_rows, fish_area_summary, fish_top_areas, ...)
build_area_pages(hist_rows, fish_area_summary, area_top_fishes, ...)
build_fish_area_pages(hist_rows, fish_area_summary, ...)
```

### 同港共起算出ロジック（fish-related）

```python
def compute_fish_related_via_cooccurrence(hist_rows, fish, top_n=6):
    """
    {fish} の主要エリアで同時期に釣れている魚種を共起便数降順で返す。
    """
    # Step 1: {fish} の主要エリア（件数 TOP-3）
    fish_areas = Counter()
    for r in hist_rows:
        if r['tsuri_mono'] == fish:
            fish_areas[r['area']] += 1
    top_areas = [a for a, _ in fish_areas.most_common(3)]

    # Step 2: それらエリアの他魚種を集計
    co_fish = Counter()
    for r in hist_rows:
        if r['area'] in top_areas and r['tsuri_mono'] != fish:
            co_fish[r['tsuri_mono']] += 1

    # Step 3: fish/{slug}.html 存在するもののみ・件数降順 TOP-N
    return [(f, n) for f, n in co_fish.most_common()
            if fish_html_exists(f)][:top_n]
```

## 5. 不変条件への影響

### 廃止・変更
| 不変条件 | 現状 | 変更方針 |
|---|---|---|
| 22 (fish/* area_cmp内 .ar-fa) | T29で追加済み | 維持（変更なし） |
| 23 (fish_area/* fa-related chip-link 1件以上) | T29で追加済み | 維持（閾値廃止後も常駐するので OK） |

### 新規追加（実装時に追加）
| 番号 | チェック対象 | 検証内容 |
|---|---|---|
| 24 | fish/{魚種}.html サンプル（aji・madai・shirogisu）| `.fish-areas-all` セクション存在 + `.chip-link.chip-area` 1件以上 |
| 25 | area/{エリア}.html サンプル（kanazawa-hakkei・urayasu）| `.area-all-fish` セクション存在 + `.chip-link` 1件以上 |
| 26 | fish/{魚種}.html サンプル | `.fish-related-species` セクション存在 + `.chip-link` 1件以上 |
| 27 | fish_area/{コンボ}.html サンプル | `.fa-related` セクション内の3軸全て存在（h2 3つ・各 chip-wrap 1件以上） |
| 28 | 全主要HTML（fish/area/fish_area） | 件→便への置換完了確認（`【今週\d+便】` パターン存在）|

### 不変条件2 への影響（reviewer m-2）
- 旧: `今週釣果(\d+)件` → 新: `今週釣果(\d+)便` or 新形式 `今週(\d+)便`
- validate_output.py の不変条件2 のパターン更新必要

## 6. title/description/h1 仕様

### title

**rich path:** `関東の{魚種}船釣り釣果【今週N便・M船宿】| 船釣り予想`
**placeholder path:** `関東の{魚種}船釣り釣果・シーズン・釣り方 | 船釣り予想`

### description

**rich path:** `関東エリアの{魚種}船釣り釣果情報。今週N便・M船宿。{top_area}エリアを中心に船宿別釣果ランキングを毎日更新。`
**placeholder path:** `関東の{魚種}船釣り情報。旬カレンダー・釣り方・タックル目安・主要エリアをまとめました。釣果報告は集まり次第更新。`

### h1（reviewer C-1）

```html
<h1 class="page-h1">関東の{魚種}船釣り釣果情報</h1>
<p class="bread">…</p>
<div class="fish-hero">
  <h2>{魚種}</h2>  <!-- 不変条件10維持 -->
  …
</div>
```

```css
.page-h1 {
  font-size: 14px; font-weight: 700; color: var(--sub);
  padding: 8px 0 0; margin: 0; line-height: 1.4;
}
```

**複数h1の判断根拠:** サイトロゴ `<h1>船釣り予想</h1>`（crawler.py:3912）と共存。Google は HTML5 で複数 h1 を許容（明示的にペナルティ無し）。アクセシビリティ的にもページ固有の h1 が役立つ。

**ロゴh1廃止案を採用しない理由:** 全ページのヘッダ構造を変える影響範囲が大きく、SEO 効果と引き換えに既存テンプレを破壊するリスクが大きい。

## 7. 実装フェーズ分割

### フェーズA（即効性高・1セッション完了可能・5〜8時間）

| # | 施策 | diff行数概算 |
|---|---|---|
| A-1 | fa-related 閾値廃止（≥3 → 1） | 5行 |
| A-2 | fa-related 3軸構造化（軸1/軸2 折り畳み・軸3 同港共起） | 80行 |
| A-3 | fa-breadcrumb 2軸化 | 15行 |
| A-4 | fish-all-areas セクション + 折り畳み | 70行 |
| A-5 | area-all-fish セクション + 折り畳み（T29 past_fish_section_html廃止） | 70行 |
| A-6 | fish-related セクション（同港共起ベース） + 折り畳み | 60行 |
| A-7 | title/description 改善（件→便） | 30行 |
| A-8 | h1 page-h1 追加 + CSS | 20行 |
| A-9 | hist_rows 共有・fish_area_summary キャッシュ | 50行 |
| A-10 | エリア→県マッピング辞書 + chip-pref 適用 | 60行 |
| A-11 | 不変条件 24-28 追加 | 60行 |

### フェーズB（次セッション・2〜4時間）
- 茨城県 emoji 作成・適用
- area_description.json への prefecture フィールド追加検討
- forecast/ noindex 解除（T22-H1 後始末・T23 完了時）

### フェーズC（2026/05/14 確定・詳細は §13）
→ **§13 Phase C 詳細仕様（2026/05/14 確定）を参照**

## 8. 想定 SEO 効果

### 短期（1〜4週間）
- クロール経路確立: パンくず area/ + fa-related 全件常駐 + fish/area→fish_area 常駐リンク
- インデックス増加: 199本（77%）→ ほぼ全 258本へ

### 中期（1〜3ヶ月）
- 掲載順位: 12位 → 10位以内入り
- CTR: 0% → 1〜2%

### 長期（3〜6ヶ月）
- 258本 × 月10〜50UU = **月2,580〜12,900UU ポテンシャル**
- AdSense 審査: コンテンツ充実度（FAQPage JSON-LD 付き 258ページ）

## 9. 「無料=事実」境界の遵守確認

| セクション | 表示内容 | 境界判定 |
|---|---|---|
| fish-all-areas chip | `{エリア名}（N便）` + 県emoji | 事実（便数・地理）✅ |
| area-all-fish chip | `{魚種}（N便）` + 魚emoji | 事実（便数）✅ |
| fish-related chip | `{魚種}（N便）` + 魚emoji | 事実（共起便数）✅ |
| fa-related chip | `{エリア/魚種}（N便）` | 事実 ✅ |
| パンくず2軸 | エリア名・魚種名のみ | 事実 ✅ |

固定セクションに予測・分析・評価は一切含まない。

## 10. 既存T30・T31の思想統一確認

T30（fish_area FAQ）・T31（area FAQ）は「当日スナップショット依存 → hist_rows 全期間固定」への移行だった。今回の2層設計は同じ思想を**内部リンク構造**に適用。FAQ固定化（コンテンツ）+ 内部リンク常駐化（リンク構造）の2本柱で「データなし時でも骨格が壊れないサイト」を実現する。

## 11. mockup 整合性確認

最終 mockup: `design/V2/mockup-T38-2layer-v2.html`
ユーザー承認済み（2026/05/14）:
- emoji 表示確認 OK
- 県emoji 4種ラベル/中身一致 確認 OK
- 折り畳み機構 確認 OK
- 同港共起ベース 確認 OK
- 件→便 確認 OK

### mockup レビュー用補助ファイル（実装時には不要）
- `design/V2/check_pref_emoji.html`（県emoji 検証用・実装後 dustbox/ 退避推奨）
- `design/V2/area_*.webp` `design/V2/fish_*.webp`（mockup 同階層 flat 配置・実装後 dustbox/ 退避推奨）

実装時は `docs/assets/area/{県}_emoji.webp`（既コピー済み）と `docs/assets/fish/{slug}/{slug}_emoji.webp`（既存）から参照する。

## 12. programmer 実装時の注意事項

- fish-hero の `<h2>` を `<h1>` に変えない（不変条件10・page-h1 は fish-hero の外）
- chip 内のネストアンカー禁止（不変条件11）
- A-1 の commit と A-2〜A-11 の commit を施策単位で分ける（rollback 容易性）
- 各施策完了時に `python crawl/validate_output.py` を実行
- 不変条件 24-28 は実装と同時に追加（gatekeeper 先行原則）
- `<base>` タグ使わない（mockup の経験で判明: 環境依存性が高い）

---

## 13. Phase C 詳細仕様（2026/05/14 確定）

本セクションは `design/V2/mockup-T38-phaseC-v1.html` のユーザー承認（2026/05/14）を
受けて確定した仕様。実装者は必ず mockup を Read してから着手すること。

### 13.1 fish/index.html 改修内容

#### 13.1.1 既存セクション見出し変更

| 変更箇所 | 変更前 | 変更後 |
|---|---|---|
| 既存 `<h2 class="st">` | `今週釣れている魚種（過去7日間）` | `今日の釣果` |

#### 13.1.2 fi-card 構造は変更しない

現行 build_fish_pages（line 8394 付近）で魚 emoji webp を表示している fi-card 構造は既に正しく実装済み。変更不要。

#### 13.1.3 新規セクション「魚種」の追加

fi-grid の直後に以下構造を追加する。

**セクション見出し:** `<h2 class="st">魚種</h2>`

**説明文:**
```html
<p class="faa-note">
  各魚種について、関東で釣れる<b>全エリアへの直リンク</b>を網羅。
  便数は過去3年の実績報告数。<b>★今週実績あり</b>を上段に、
  <b>過去実績のみ</b>を下段（折り畳み）に分離。
</p>
```

**コンテナ:** `<div class="idx-all-grid">`

**各魚種の idx-block 構造:**

```html
<div class="idx-block">
  <div class="idx-block-h">
    <img src="../assets/fish/{slug}/{slug}_emoji.webp" alt="{魚種}" class="ib-emoji"
         width="20" height="20" loading="lazy" onerror="this.style.display='none'">
    <a href="{fish_slug}.html">{魚種}</a>
    <span class="ib-cnt">今週{N}便・全{M}エリア</span>
  </div>

  <!-- 今週実績あり（上段） -->
  <p class="tier-label">★ 今週実績あり（{N}エリア）</p>
  <div class="chip-wrap">
    <a href="../fish_area/{fish_slug}-{area_slug}.html" class="chip-link chip-active">
      <img src="../assets/area/{pref}_emoji.webp" alt="" class="chip-pref"
           width="14" height="14" loading="lazy" onerror="this.style.display='none'">
      {エリア名}（{N}便）
    </a>
  </div>

  <!-- 今週実績なし（下段・折り畳み） -->
  <details class="fold-chips">
    <summary>過去実績あり（今週ゼロ・{M}エリア）を表示</summary>
    <div class="chip-wrap">
      <a href="../fish_area/{fish_slug}-{area_slug}.html" class="chip-link">...</a>
    </div>
  </details>
</div>
```

**今週実績ゼロ魚種のブロック（mockup ヒラメ例）:**

```html
<div class="idx-block">
  <div class="idx-block-h">...</div>
  <p class="tier-label" style="color:#aaa;">今週実績なし</p>
  <details class="fold-chips" open>
    <summary>過去実績あり（今週ゼロ・{M}エリア）を表示</summary>
    <div class="chip-wrap">...</div>
  </details>
</div>
```

### 13.2 area/index.html 改修内容

#### 13.2.1 AREA_GROUPS 見出しは変更しない

現行の「神奈川・東京湾」「神奈川・相模湾」「千葉・東京湾奥」「千葉・内房」「千葉・外房」「東京」「茨城」「静岡」「その他」の見出しはそのまま維持する。

#### 13.2.2 ai-card の構造変更（直リンク化・不変条件11対応）

現行の `<a class="ai-card">` を `<div class="ai-card">` に変更し、内部リンクを独立した `<a>` 要素に分離する。

**変更前（現行 line 9180-9184）:**
```html
<a class="ai-card" href="{area_slug}.html">
  <div class="ai-name">{area}</div>
  <div class="ai-fish">{"・".join(top_f)}</div>
  <div class="ai-cnt">今週釣果{len(catches)}便</div>
</a>
```

**変更後（新構造）:**
```html
<div class="ai-card">
  <a class="ai-name" href="{area_slug}.html">
    <img src="../assets/area/{pref}_emoji.webp" alt="" class="chip-pref"
         style="width:18px;height:18px;object-fit:contain;vertical-align:middle;margin-right:4px"
         onerror="this.style.display='none'">
    {area}
  </a>
  <div class="ai-fish">
    <a href="../fish_area/{fish_slug}-{area_slug}.html">{fish}</a><span class="ai-sep">・</span><a href="../fish_area/{...}.html">{...}</a>
  </div>
  <a class="ai-cnt" href="{area_slug}.html">今週釣果{N}便</a>
</div>
```

**ai-fish 内の魚種リンク生成ルール:**
- 当該エリアの今週実績魚種を件数降順で最大 3 件表示
- 各魚種のリンク先は `fish_area/{fish_slug}-{area_slug}.html` が存在する場合のみリンク化（存在しない場合はプレーンテキスト）
- 中黒 `<span class="ai-sep">・</span>` で連結

**chip 内 emoji の HTML 形式（reviewer MINOR-4 統一指示）:**
- mockup には `🐟 アジ` のような Unicode 絵文字テキストとの混在があるが、**実装は `<img class="chip-emoji">` / `<img class="chip-pref">` 形式に統一すること**
- 魚 emoji: `<img src="../assets/fish/{slug}/{slug}_emoji.webp" alt="{魚種}" class="chip-emoji" width="14" height="14" loading="lazy" onerror="this.style.display='none'">`
- 県 emoji: `<img src="../assets/area/{pref}_emoji.webp" alt="" class="chip-pref" width="14" height="14" loading="lazy" onerror="this.style.display='none'">`

#### 13.2.3 新規セクション「エリア」の追加

AREA_GROUPS 別ブロック全体の後（`area_index_sections` の末尾）に以下セクションを追加する。

**セクション見出し:** `<h2 class="st">エリア</h2>`

**各エリアの idx-block 構造:**

```html
<div class="idx-block">
  <div class="idx-block-h">
    <img src="../assets/area/{pref}_emoji.webp" alt="" class="ib-emoji"
         width="20" height="20" loading="lazy" onerror="this.style.display='none'">
    <a href="{area_slug}.html">{エリア名}</a>
    <span class="ib-cnt">今週{N}便・全{M}魚種</span>
  </div>
  <p class="tier-label">★ 今週実績あり（{M}魚種）</p>
  <div class="chip-wrap">
    <a href="../fish_area/{fish_slug}-{area_slug}.html" class="chip-link chip-active">
      <img src="../assets/fish/{fish_img_slug}/{fish_img_slug}_emoji.webp" alt="{魚種}" class="chip-emoji"
           width="14" height="14" loading="lazy" onerror="this.style.display='none'">
      {魚種}（{N}便）
    </a>
  </div>
  <details class="fold-chips">
    <summary>過去実績あり（今週ゼロ・{M}魚種）を表示</summary>
    <div class="chip-wrap">...</div>
  </details>
</div>
```

**今週実績ゼロエリアのブロック:**
- `<details class="fold-chips" open>` で展開済みにする
- `<p class="tier-label" style="color:#aaa;">今週実績なし</p>` を折り畳みの前に表示

### 13.3 共有データ要件

#### データソース

| セクション | データ | 取得元 |
|---|---|---|
| fish/index 今週実績判定 | 過去7日 catches | `_load_recent_catches_for_index(now, days=7)` 既存ロジック流用 |
| fish/index 全便数 | 過去3年 hist_rows | `hist_rows` メインスコープ共有変数（§4 共有戦略） |
| area/index 今週実績判定 | 過去7日 catches | `_recent7_area` 既存ロジック流用 |
| area/index 全便数 | 過去3年 hist_rows | `hist_rows` メインスコープ共有変数 |
| fish_area HTML 存在チェック | docs/fish_area/ | `os.path.exists(os.path.join(WEB_DIR, "fish_area", "{slug}.html"))` |

#### fish_area_html_exists の実装ヒント

```python
def _fa_exists(fish, area):
    """docs/fish_area/{fish_slug}-{area_slug}.html が存在するか確認。"""
    fname = f"{fish_slug(fish)}-{area_slug(area)}.html"
    return os.path.exists(os.path.join(WEB_DIR, "fish_area", fname))
```

#### ⚠ 実行順序の問題と解決策（2026/05/14 reviewer 指摘で判明）

**現行 main() の呼出順（crawler.py line 13310-13323）:**
1. `build_fish_pages` （fish/{魚種}.html + fish/index.html）
2. `build_fish_area_pages` （fish_area/{combo}.html）
3. `build_area_pages` （area/{エリア}.html + area/index.html）

**問題:** `build_fish_pages` 内で fish/index.html を生成する時点では fish_area HTML がまだ存在しない。`_fa_exists()` が全件 False を返し、Phase C の「魚種」セクションの chip リンクが全部スキップされる。

**解決策:** fish/index.html と area/index.html の生成を **別関数に切り出し**、build_fish_area_pages の後に呼び出す。

**新しい main() 呼出順（実装時に再構成）:**
1. `build_fish_pages`（fish/{魚種}.html のみ・fish/index 生成は分離）
2. `build_fish_area_pages`（fish_area/{combo}.html）
3. `build_area_pages`（area/{エリア}.html のみ・area/index 生成は分離）
4. **`build_fish_index_html(hist_rows, fish_area_summary, _recent7_data)`**（新規・fish/index 専用）
5. **`build_area_index_html(hist_rows, area_top_fishes, _recent7_data)`**（新規・area/index 専用）

build_fish_index_html / build_area_index_html は、必要なデータ（hist_rows, fish_area_summary, area_top_fishes, 直近7日 catches）を引数で受け取り、HTML を独立に生成する。これにより `_fa_exists()` がすべて True/False を正確に返せる。

### 13.4 並び順・折り畳み・フィルタ規則

#### fish/index.html「魚種」セクションの並び順

1. **ブロック順（魚種）:**
   - 今週実績あり魚種を先頭に配置（今週便数の降順）
   - 今週実績ゼロ魚種を末尾に配置（過去3年便数の降順）

2. **上段 chip 順（エリア）:** 過去3年便数の降順
3. **下段 chip 順（エリア）:** 過去3年便数の降順

#### area/index.html「エリア」セクションの並び順

1. **ブロック順（エリア）:**
   - **既存 `_group_order` リスト（crawler.py line 9169 付近）に従う**
   - 現行値: `["茨城", "千葉・外房", "千葉・内房", "千葉・東京湾奥", "東京", "神奈川・東京湾", "神奈川・相模湾", "静岡"]`
   - 順序を変更したい場合は build_area_pages 既存実装側の `_group_order` を変更（仕様書側はリスト参照を明記するに留める）
   - グループ内は今週便数の降順

2. **上段 chip 順（魚種）:** 過去3年便数の降順
3. **下段 chip 順（魚種）:** 過去3年便数の降順

#### 対象フィルタ

- chip リンクの生成条件: `docs/fish_area/{fish_slug}-{area_slug}.html` が存在すること（_fa_exists）
- 存在しないコンボはリンク生成をスキップ（404 防止）

#### 折り畳み既定

| 状態 | `<details>` の open 属性 |
|---|---|
| 今週実績あり魚種/エリアのブロック内「下段」| open なし（閉じる） |
| 今週実績ゼロ魚種/エリアのブロック内 | `open`（展開済み）|

**理由:** 今週実績ゼロのブロックは下段が実質的なメインコンテンツのため展開しておく。上段が有る場合は下段を閉じて「いま釣れている」を際立たせる。

#### 空ブロック禁止

今週実績ゼロ かつ 過去3年実績ゼロの魚種/エリアはブロック自体を生成しない。

### 13.5 CSS 追加要素

#### idx-all-grid 関連（両ページ共通）

> **⚠ 実装は CSS 変数を使用すること。** mockup-T38-phaseC-v1.html は `<style>` タグ内で `#1a3a52` 等ハードコード値を使っているが、これは mockup プレビュー用の簡易再現であり、実装時は必ず `var(--accent)` `var(--muted)` `var(--cta)` `var(--border)` `var(--card)` 等の CSS 変数を使う（V1 残存色を持ち込まないため）。

```css
.idx-all-grid {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: var(--r);
  padding: 12px 14px;
  margin: 8px 0 20px;
}
.idx-block {
  padding: 8px 0;
  border-bottom: 1px solid var(--border);
}
.idx-block:last-child { border-bottom: none; }
.idx-block-h {
  font-size: 14px;
  font-weight: 700;
  color: var(--accent);
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 0 4px;
}
.idx-block-h .ib-emoji { width: 20px; height: 20px; object-fit: contain; }
.idx-block-h .ib-cnt {
  font-size: 11px;
  color: var(--muted);
  font-weight: 400;
  margin-left: auto;
}
.idx-block-h a { color: var(--accent); text-decoration: none; }
.idx-block-h a:hover { text-decoration: underline; }
.chip-link.chip-active {
  background: #fff8e7;
  border-color: #f5c542;
}
.chip-link.chip-active:hover { background: #fff3d0; }
```

#### ai-card 変更に伴う CSS（area/index 専用）

```css
.ai-card { display: block; /* <a> から <div> に変わるため display:block を維持 */ }
.ai-name { display: block; font-size: 14px; font-weight: 700;
           color: var(--accent); text-decoration: none; }
.ai-name:hover { text-decoration: underline; }
.ai-fish { font-size: 11px; color: var(--sub); margin-top: 4px; line-height: 1.7; }
.ai-fish a { color: #1a4a72; text-decoration: none;
             white-space: nowrap; padding: 0 2px; border-radius: 3px; }
.ai-fish a:hover { background: #eaf2fa; text-decoration: underline; }
.ai-sep { color: #aaa; }
.ai-cnt { display: block; font-size: 11px; color: var(--cta);
          font-weight: 600; margin-top: 4px; text-decoration: none; }
.ai-cnt:hover { text-decoration: underline; }
```

**モバイル対応 (`@media(max-width:480px)`):**
```css
.idx-block-h .ib-cnt { display: none; }
```

### 13.6 不変条件追加

reviewer 指摘により、複合検証は粒度別に分離する（regression 原因特定の精度向上のため）。

| 番号 | チェック対象 | 検証内容 |
|---|---|---|
| 30 | `fish/index.html` | `.idx-all-grid` 内に `.chip-link.chip-active` が 1件以上存在する（「魚種」セクションの全件展開が機能している） |
| 31 | `area/index.html` | `.idx-all-grid` 内に `.chip-link` が 1件以上存在する（「エリア」セクションの全件展開が機能している） |
| 32 | `area/index.html` | `<div class="ai-card">` 内に `<img class="chip-pref">` または `class="chip-pref"` 属性を持つ img が 1件以上存在する（県emoji 表示） |
| 33 | `area/index.html` | `<div class="ai-fish">` 内に `<a href="../fish_area/...">` が 1件以上存在する（魚種 → fish_area 直リンク化） |

#### 既存不変条件 2 への影響（reviewer MINOR-6 確認結果）

不変条件 2（fish/index.html 検証）は以下を見ている:
- `今週釣果(\d+)[件便]` パターン（fi-card 内 `<div class="fi-cnt">今週釣果N便</div>`）

**Phase C では fi-card 構造を変更しないため、不変条件 2 は壊れない。** validate_output.py の更新不要。

「今週釣れている魚種（過去7日間）」→「今日の釣果」の見出し変更は h2 セクションの見出しテキストのみ変更。fi-card 内のラベル「今週釣果N便」は維持されるため、validate_output line 134 の正規表現は機能継続。

### 13.7 ネストアンカー回避（不変条件11）の明記

**ai-card は必ず `<div>` ラッパーで実装すること。**

現行の `<a class="ai-card">` ラッパーに内部リンク（`ai-name`・`ai-fish` 各 `<a>`・`ai-cnt`）をネストすると HTML5 invalid になる（不変条件11違反）。

- `<div class="ai-card">` の直下に複数の独立した `<a>` 要素を並列に配置
- `ai-name`・`ai-cnt` はそれぞれ独立した `<a>` として href を持つ
- `ai-fish` 内の各魚種名も個別の `<a>` として fish_area ページに直リンク
- `chip-wrap` 内の `<a class="chip-link">` は単独要素なのでネスト問題なし

### 13.8 SEO 効果想定

#### 直リンク経路の追加

| 経路 | Phase A 以前 | Phase C 以後 |
|---|---|---|
| fish/index → fish_area | 0件 | 258本全件（常駐） |
| area/index → fish_area | 0件 | 258本全件（常駐） |

#### ハブページ経由のクロール短縮

- 従来: `fish/index` → `fish/{魚種}` → `fish_area/` （3ステップ）
- 追加: `fish/index` → `fish_area/` （2ステップ）
- 従来: `area/index` → `area/{エリア}` → `fish_area/` （3ステップ）
- 追加: `area/index` → `fish_area/` （2ステップ）

258 本の fish_area が 2ステップ短縮で到達可能になる。「参照元ページが検出されませんでした」問題の根本解消が期待できる。

#### 重複リンク SEO 影響

fish/index の「今日の釣果」セクション（fi-card）と「魚種」セクション（chip-link）で、同じ fish/{slug}.html へのリンクが重複する可能性がある。これは同一ページ内での重複リンクであり、Google は同一 href を 1 リンクとして評価するため SEO ペナルティはない。

### 13.9 実装上の注意事項（programmer 向け）

- `ai-card` の `<a>` → `<div>` 変更は area_index_css の `.ai-card` セレクタも調整が必要（`display:block` 維持・`text-decoration:none` の継承が消えるため ai-name・ai-cnt に個別付与）
- `idx-all-grid` 関連 CSS は `fish_index_css` / `area_index_css` 変数に追記する
- `_fa_exists(fish, area)` はモジュールレベルのヘルパーとして定義し、build_fish_pages と build_area_pages 両方から参照
- Phase C 実装前に `python crawl/validate_output.py` を実行し errors=0 を確認
- 実装後も `python crawl/validate_output.py` で全不変条件 PASS を確認（不変条件 30・31 は実装と同時に追加）
- `build_fish_area_pages` → `build_fish_pages` → `build_area_pages` の実行順序を維持（_fa_exists が動作するため）
