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

### フェーズC（複数セッション）
- fish/index.html 全fish_area一覧（魚種別グルーピング）
- area/index.html 全fish_area一覧（エリア別グルーピング）

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
