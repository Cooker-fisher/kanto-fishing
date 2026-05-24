# 釣果価値チェッカー アプリ本体デザイン依頼書（ChatGPT 用）

## 0. 依頼概要

`docs/fish-value/index.html` + `app.js` + `style.css` の3ファイルを作成してください。

これは「釣果価値チェッカー」という独立アプリで、釣り人が **釣果（魚種・匹数・サイズ or 重量）** を入力すると、**卸売換算と小売換算の金額レンジ** を表示するツールです。

**既存サイト**: https://funatsuri-yoso.com（船釣り予想・関東の船宿釣果情報サイト）
**配置**: `docs/fish-value/`（既存サイト内の独立サブディレクトリ・URL は `/fish-value/`）
**コンセプト**: 1ページ完結・スマホ縦持ち最優先・派手にしない・実用カード

---

## 1. 既存サイトのデザインシステム（必ず踏襲）

以下のCSS変数を `:root` にそのままコピーして使ってください。`style.css` の最上部に配置。

```css
:root {
  /* 背景 */
  --bg:       #f5f7fa;
  --card:     #fff;
  --border:   #d0d8e0;
  --nav:      #f0f3f7;

  /* テキスト */
  --text:     #1a2332;
  --sub:      #5a6a7a;
  --muted:    #8a96a4;

  /* アクセント */
  --accent:   #0d2b4a;
  --cta:      #e85d04;
  --cta2:     #d04e00;

  /* セマンティック */
  --pos:      #1a9d56;
  --neg:      #d43333;
  --warn:     #d4a017;
  --prem:     #7c3aed;

  /* ヘッダー / LINE */
  --hdr:      #0d2b4a;

  /* サイズ */
  --r:        10px;     /* border-radius 標準 */
  --mx:       900px;    /* max-width */

  /* Hero グラデーション */
  --hero-grad-end: #163d5c;

  /* ドロップシャドウ */
  --shadow-bn:      rgba(0,0,0,.06);
}
```

### 1.1 フォント / 基本スタイル

```css
body {
  font-family: system-ui, -apple-system, "Hiragino Sans", sans-serif;
  background: var(--bg);
  color: var(--text);
  line-height: 1.6;
  margin: 0;
  padding-bottom: 60px;
}
```

### 1.2 ヘッダー（既存サイトと同じ形式）

```html
<header>
  <div class="hd-inner">
    <a href="../" class="hd-logo">船釣り予想</a>
    <div class="hd-title">釣果価値チェッカー</div>
  </div>
</header>
```

```css
header {
  background: var(--hdr);
  color: #fff;
  padding: 12px 20px;
  border-bottom: 3px solid var(--cta);
}
.hd-inner {
  max-width: var(--mx);
  margin: 0 auto;
  display: flex;
  align-items: center;
  gap: 12px;
}
.hd-logo {
  color: #fff;
  text-decoration: none;
  font-size: 13px;
  opacity: .85;
}
.hd-logo::before { content: "←"; margin-right: 4px; }
.hd-title {
  font-weight: 700;
  font-size: 16px;
}
```

### 1.3 カード

```css
.card {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: var(--r);
  padding: 16px;
  margin-bottom: 12px;
  box-shadow: 0 1px 3px var(--shadow-bn);
}
.card h2.st {
  font-size: 14px;
  font-weight: 700;
  color: var(--sub);
  margin: 0 0 12px;
  padding-bottom: 6px;
  border-bottom: 1px solid var(--border);
}
```

### 1.4 CTA ボタン

```css
.btn-primary {
  background: var(--cta);
  color: #fff;
  border: none;
  border-radius: var(--r);
  padding: 14px 20px;
  font-size: 16px;
  font-weight: 700;
  cursor: pointer;
  width: 100%;
}
.btn-primary:hover { background: var(--cta2); }
.btn-primary:disabled { background: var(--muted); cursor: not-allowed; }
```

### 1.5 メインコンテナ

```css
.wrap {
  max-width: var(--mx);
  margin: 0 auto;
  padding: 12px;
}
```

---

## 2. 画面仕様

### 2.1 全体構成（1ページ完結・タブなし）

```
┌──────────────────────────────────┐
│ <header>                        │  既存サイト準拠（紺背景・オレンジ下線）
├──────────────────────────────────┤
│ ① 入力カード                    │  魚種・匹数・サイズ or 重量
│   - 魚種ドロップダウン           │
│   - 匹数 数値入力                │
│   - 平均サイズ(cm) または重量(kg) │  魚種選択で自動切替
│   - [計算する] ボタン            │
├──────────────────────────────────┤
│ ② 結果カード（計算後表示）       │
│   ▼ サイズ帯ラベル "中" 等       │
│   推定総重量                     │
│   ─────                          │
│   小売換算 (大きく強調)          │
│   約 X,XXX 〜 X,XXX 円           │
│   1匹あたり 約 XXX 〜 XXX 円     │
│   ─────                          │
│   卸売換算                       │
│   約 X,XXX 〜 X,XXX 円           │
│   1匹あたり 約 XXX 〜 XXX 円     │
├──────────────────────────────────┤
│ ③ 計算根拠（折りたたみ・閉じ初期）│
│   - 入力サイズ → 推定重量        │
│   - 該当サイズ帯                 │
│   - 卸売単価レンジ・出典         │
│   - 倍率カテゴリ                 │
├──────────────────────────────────┤
│ ④ 注意文（必須）                 │
│   薄グレー文字                  │
├──────────────────────────────────┤
│ <footer>                        │
│   船釣り予想に戻る ←リンク      │
└──────────────────────────────────┘
```

### 2.2 レイアウトルール

- 375px〜（スマホ縦持ち）最優先
- PC でも常に縦1列・最大幅 `var(--mx)` = 900px センタリング
- 横スクロール禁止
- カード間マージン 12px
- セクション見出しは `.st` クラスで統一

### 2.3 入力カード詳細

```html
<section class="card input-card">
  <h2 class="st">釣果を入力</h2>

  <div class="form-row">
    <label for="fish">魚種</label>
    <select id="fish">
      <option value="">▼ 魚種を選択</option>
      <!-- fish-species-map.json の species[] を JS で展開 -->
    </select>
  </div>

  <div class="form-row">
    <label for="count">匹数</label>
    <input type="number" id="count" inputmode="numeric" min="1" max="999" placeholder="例: 35" />
  </div>

  <!-- cm 入力魚種のとき表示 -->
  <div class="form-row" id="size-row">
    <label for="size">平均サイズ (cm)</label>
    <input type="number" id="size" inputmode="numeric" min="1" max="200" placeholder="例: 25" />
  </div>

  <!-- kg 入力魚種のとき表示 -->
  <div class="form-row" id="weight-row" hidden>
    <label for="weight">平均重量 (kg)</label>
    <input type="number" id="weight" inputmode="decimal" min="0.05" max="100" step="0.1" placeholder="例: 1.2" />
  </div>

  <button id="calc-btn" class="btn-primary">計算する</button>

  <p class="err" id="err-msg" hidden></p>
</section>
```

```css
.form-row {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-bottom: 14px;
}
.form-row label {
  font-size: 13px;
  font-weight: 600;
  color: var(--sub);
}
.form-row select,
.form-row input {
  padding: 10px 12px;
  border: 1px solid var(--border);
  border-radius: var(--r);
  font-size: 16px; /* iOS でズームしないよう 16px 以上 */
  background: #fff;
  color: var(--text);
}
.form-row select:focus,
.form-row input:focus {
  outline: 2px solid var(--accent);
  outline-offset: -1px;
}
.err {
  color: var(--neg);
  font-size: 13px;
  margin: 8px 0 0;
}
```

### 2.4 結果カード詳細

```html
<section class="card result-card" id="result" hidden>
  <h2 class="st">計算結果</h2>

  <div class="result-meta">
    <span class="size-badge" data-class="standard">中</span>
    <span class="weight">推定総重量 5.6 kg</span>
  </div>

  <div class="result-price retail">
    <div class="price-label">小売換算</div>
    <div class="price-range">約 1,800 〜 4,500 円</div>
    <div class="price-per">1匹あたり 約 180 〜 450 円</div>
  </div>

  <div class="result-price wholesale">
    <div class="price-label">卸売換算</div>
    <div class="price-range">約 900 〜 1,800 円</div>
    <div class="price-per">1匹あたり 約 90 〜 180 円</div>
  </div>
</section>
```

```css
.result-meta {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 14px;
}
.size-badge {
  padding: 4px 10px;
  border-radius: 14px;
  font-size: 12px;
  font-weight: 700;
  background: var(--accent);
  color: #fff;
}
.size-badge[data-class="large"]    { background: var(--cta); }
.size-badge[data-class="premium"]  { background: var(--prem); }
.size-badge[data-class="small"]    { background: var(--sub); }
.weight {
  font-size: 14px;
  color: var(--sub);
}

.result-price {
  padding: 14px 0;
  border-bottom: 1px dashed var(--border);
}
.result-price:last-child { border-bottom: none; }

.result-price.retail .price-range {
  font-size: 26px;       /* 小売はメイン・大きく */
  font-weight: 800;
  color: var(--cta);
}
.result-price.wholesale .price-range {
  font-size: 20px;       /* 卸売はサブ・やや小さく */
  font-weight: 700;
  color: var(--text);
}
.price-label {
  font-size: 13px;
  color: var(--sub);
  margin-bottom: 4px;
}
.price-per {
  font-size: 12px;
  color: var(--muted);
  margin-top: 4px;
}
```

### 2.5 計算根拠（折りたたみ）

```html
<details class="basis-details">
  <summary>計算根拠を表示</summary>
  <ul class="basis-list">
    <li>入力: 平均サイズ 25cm → 推定重量 0.16 kg/尾</li>
    <li>サイズ帯: 中 (kg_max: 0.30)</li>
    <li>卸売単価: 540 〜 1,057 円/kg（出典: 東京都中央卸売市場 月報 2026/04・まあじ）</li>
    <li>倍率: 大衆魚カテゴリ × 標準サイズ → 卸→小売 2.0 〜 3.0倍</li>
  </ul>
</details>
```

```css
.basis-details {
  margin-top: 12px;
  background: var(--nav);
  border: 1px solid var(--border);
  border-radius: var(--r);
  padding: 10px 14px;
  font-size: 12px;
  color: var(--sub);
}
.basis-details summary {
  cursor: pointer;
  font-weight: 600;
  color: var(--accent);
}
.basis-list {
  margin: 8px 0 0;
  padding-left: 18px;
  line-height: 1.7;
}
```

### 2.6 注意文（必須・結果カード直下）

```html
<p class="caution">
  ※ 表示価格は概算です。市場価格・鮮度・産地・季節で大きく変動するため、
  実際の取引価格を保証するものではありません。
</p>
```

```css
.caution {
  font-size: 12px;
  color: var(--muted);
  line-height: 1.7;
  margin: 8px 12px 16px;
}
```

### 2.7 フッター

```html
<footer class="ft">
  <a href="../" class="ft-back">← 船釣り予想に戻る</a>
</footer>
```

```css
.ft {
  max-width: var(--mx);
  margin: 24px auto 0;
  padding: 20px 12px;
  border-top: 1px solid var(--border);
  text-align: center;
}
.ft-back {
  color: var(--accent);
  text-decoration: none;
  font-size: 14px;
}
.ft-back:hover { text-decoration: underline; }
```

---

## 3. データ仕様

`docs/fish-value/` 配下に既に2ファイルあります。`fetch` で読み込んでください。

### 3.1 `fish-species-map.json`（魚種マスタ）

```json
{
  "version": "v1",
  "species": [
    {
      "site_fish_id": "aji",
      "site_display_name": "アジ",
      "price_fish_id": "maaji",
      "input_modes": ["cm"],
      "category": "target"
    },
    {
      "site_fish_id": "madai",
      "site_display_name": "マダイ",
      "price_fish_id": "madai",
      "input_modes": ["kg"],
      "category": "target"
    }
    // ... 72魚種
  ]
}
```

- ドロップダウンには `species` 配列の順番で表示（並び替え不要）
- 表示名は `site_display_name`
- 内部参照キーは `site_fish_id`（URL パラメータ用）
- `input_modes` が `["cm"]` ならサイズ入力欄、`["kg"]` なら重量入力欄
- 価格参照キーは `price_fish_id`（fish-price-master.json への索引）

### 3.2 `fish-price-master.json`（価格マスタ）

```json
{
  "version": "v1",
  "updated_at": "2026-05-24",
  "prices": {
    "maaji": {
      "category_tag": "大衆魚",
      "input_modes": ["cm"],
      "size_weight_curve": [
        {"cm": 10, "kg": 0.010},
        {"cm": 15, "kg": 0.035},
        {"cm": 20, "kg": 0.080},
        {"cm": 25, "kg": 0.160},
        {"cm": 30, "kg": 0.280},
        {"cm": 40, "kg": 0.650},
        {"cm": 50, "kg": 1.200}
      ],
      "wholesale_avg": 705,
      "wholesale_source": "月報最新月: 202604",
      "size_bands": [
        {"kg_max": 0.05, "label": "豆アジ", "size_class": "small",
         "wholesale_low": 226, "wholesale_high": 678,
         "retail_low": 429, "retail_high": 1932},
        {"kg_max": 0.15, "label": "中小", "size_class": "small",
         "wholesale_low": 226, "wholesale_high": 678,
         "retail_low": 429, "retail_high": 1932},
        {"kg_max": 0.30, "label": "中", "size_class": "standard",
         "wholesale_low": 493, "wholesale_high": 1057,
         "retail_low": 986, "retail_high": 3171},
        {"kg_max": null, "label": "大・尺", "size_class": "large",
         "wholesale_low": 705, "wholesale_high": 1762,
         "retail_low": 1692, "retail_high": 6343}
      ],
      "related_species": ["アジ", "ビシアジ"]
    }
    // ... 70 pfid
  }
}
```

**重要**: `wholesale_low/high` と `retail_low/high` は **すでに計算済み** です。JS で再計算する必要はなく、入力 kg が該当する `size_bands[i]` を選んで直接使ってください。

---

## 4. 計算ロジック（JS 実装）

### 4.1 入力受け取り

```js
const fish    = document.getElementById('fish').value;        // "aji"
const count   = parseInt(document.getElementById('count').value, 10);  // 35
const sizeCm  = parseFloat(document.getElementById('size').value);     // 25 (cm入力時)
const weightKg = parseFloat(document.getElementById('weight').value);  // 1.2 (kg入力時)
```

### 4.2 fish_id → pfid 解決

```js
const species = SPECIES_MAP.species.find(s => s.site_fish_id === fish);
const pfid = species.price_fish_id;
const priceEntry = PRICE_MASTER.prices[pfid];
```

### 4.3 cm入力時 → kg換算（線形補間）

```js
function cmToKg(curve, cm) {
  if (cm <= curve[0].cm) return curve[0].kg;
  if (cm >= curve[curve.length-1].cm) return curve[curve.length-1].kg;
  for (let i = 0; i < curve.length - 1; i++) {
    if (cm >= curve[i].cm && cm <= curve[i+1].cm) {
      const ratio = (cm - curve[i].cm) / (curve[i+1].cm - curve[i].cm);
      return curve[i].kg + (curve[i+1].kg - curve[i].kg) * ratio;
    }
  }
}
```

### 4.4 該当 band 選択（kg_max 昇順検索）

```js
function findBand(bands, kg) {
  for (const band of bands) {
    if (band.kg_max === null || kg <= band.kg_max) return band;
  }
  return bands[bands.length - 1];
}
```

### 4.5 金額計算

```js
const perFishKg = (input_modes === 'cm') ? cmToKg(curve, sizeCm) : weightKg;
const totalKg = perFishKg * count;
const band = findBand(priceEntry.size_bands, perFishKg);

const wholesaleLow  = totalKg * band.wholesale_low;
const wholesaleHigh = totalKg * band.wholesale_high;
const retailLow     = totalKg * band.retail_low;
const retailHigh    = totalKg * band.retail_high;
```

### 4.6 表示用フォーマット（100円単位で丸める）

```js
function fmtYen(n) {
  const rounded = Math.round(n / 100) * 100;
  return rounded.toLocaleString('ja-JP');
}
// 例: fmtYen(6428) === "6,400"
```

### 4.7 URL パラメータ初期値受け取り

```js
const params = new URLSearchParams(location.search);
if (params.get('fish'))   document.getElementById('fish').value = params.get('fish');
if (params.get('count'))  document.getElementById('count').value = params.get('count');
if (params.get('size'))   document.getElementById('size').value = params.get('size');
if (params.get('weight')) document.getElementById('weight').value = params.get('weight');
// 全パラメータ揃ってたら自動計算
```

---

## 5. テスト用ケース（期待出力）

### ケース1: アジ 35匹 平均25cm
- 入力: fish=aji, count=35, size=25
- 期待:
  - 推定重量 0.16 kg/尾 × 35匹 = **5.6 kg**
  - サイズ帯: 中 (standard)
  - 卸売: 0.16×35×493 〜 0.16×35×1057 = **2,761 〜 5,919 円** → "約 2,800 〜 5,900 円"
  - 小売: 0.16×35×986 〜 0.16×35×3171 = **5,522 〜 17,758 円** → "約 5,500 〜 17,800 円"

### ケース2: マダイ 1匹 1.2kg
- 入力: fish=madai, count=1, weight=1.2
- 期待:
  - 重量 1.2 kg/尾 × 1匹 = **1.2 kg**
  - サイズ帯: 標準 (standard)
  - 卸売: 1.2×810 〜 1.2×1281 = **972 〜 1,537 円** → "約 1,000 〜 1,500 円"
  - 小売: 1.2×1458 〜 1.2×3202 = **1,750 〜 3,842 円** → "約 1,800 〜 3,800 円"

### ケース3: タチウオ 3匹 平均110cm（ドラゴン級）
- 入力: fish=tachiuo, count=3, size=110
- 期待:
  - 推定重量 ≈ 1.2 kg/尾 × 3匹 = **3.6 kg**（curve から補間）
  - サイズ帯: ドラゴン (premium)
  - 卸売: 3.6×5547 〜 3.6×7278 = **19,969 〜 26,201 円** → "約 20,000 〜 26,200 円"
  - 小売: 3.6×13673 〜 3.6×25327 = **49,223 〜 91,177 円** → "約 49,200 〜 91,200 円"

---

## 6. 制約・禁止事項

### やってはいけないこと
1. ✗ フレームワーク使用（React/Vue/Svelte 等）
2. ✗ ビルドツール（webpack/vite/parcel）使用
3. ✗ 外部 CDN リンク（jQuery / lodash / Tailwind 等）
4. ✗ 既存サイトの `docs/style.css` `docs/main.js` を読み込む
5. ✗ 単一価格表示（必ずレンジ low〜high）
6. ✗ avg/平均値の表示（low〜high のみ・1匹あたり も同様）
7. ✗ 加工済み価格（柵・切り身）の表示 — 「丸ごと小売換算」のみ
8. ✗ 派手なグラデーション・絵文字・金ピカ・カジノ風 UI

### 必ずやること
1. ✓ バニラ JavaScript（ES6+ OK）
2. ✓ `index.html` + `app.js` + `style.css` の3ファイルで完結
3. ✓ 既存サイトの CSS 変数を踏襲（§1 参照）
4. ✓ レンジ表示・100円単位で丸める
5. ✓ スマホ375px幅で横スクロール出ない
6. ✓ 入力 16px 以上（iOS ズーム防止）
7. ✓ `<label>` を全入力に紐付け（A11y）
8. ✓ エラーは赤テキストでインライン表示（モーダル禁止）
9. ✓ 注意文「※ 概算です」を結果直下に必ず表示
10. ✓ フッターに「船釣り予想に戻る」リンクのみ

---

## 7. レスポンシブ要件

| 幅 | レイアウト |
|---|---|
| 375px | 縦1列・カード全幅・フォント本文 14px |
| 768px | 縦1列維持・最大幅 var(--mx) (900px) センタリング |
| 1366px | 同上 |

横スクロール禁止。フォントは本文 14-16px、見出し 16-18px、結果価格 20-26px。

---

## 8. アクセシビリティ

- WCAG AA コントラスト（メインテキスト 4.5:1 以上）
- Tab で全入力にフォーカス可能
- `<label>` 必須・`for` 属性付き
- エラー時は `aria-invalid="true"` `aria-describedby="err-msg"`
- 計算後の結果カードは `role="region"` + `aria-live="polite"` で読み上げ
- セレクトはネイティブ `<select>`（カスタムドロップダウン禁止）

---

## 9. 成果物

以下の3ファイルを返してください。Markdown コードブロックではなく、ファイル単位で。

```
docs/fish-value/index.html
docs/fish-value/app.js
docs/fish-value/style.css
```

合計コード行数の目安: HTML 100行 / JS 200行 / CSS 250行 程度。これより大きくなる場合は機能過剰の疑いあり、シンプル化を検討してください。

---

## 10. 提出物にどうしても含めてほしい要素チェックリスト

実装する側がコピペで確認できるよう、以下が満たされているか自己レビューしてから提出してください:

- [ ] `:root` に既存サイトの CSS 変数（§1）が完全に入っている
- [ ] `<header>` が紺背景 + オレンジ下線で「船釣り予想 ← / 釣果価値チェッカー」になっている
- [ ] 魚種ドロップダウンが `fish-species-map.json` の `species[]` から動的展開
- [ ] cm/kg 入力欄が `input_modes` で切替（両方同時表示しない）
- [ ] 結果に「小売換算」「卸売換算」が **両方**・それぞれ low〜high レンジ
- [ ] 100円単位で丸め
- [ ] avg/平均値の表示ゼロ
- [ ] 計算根拠が `<details>` で折りたたみ可能
- [ ] 注意文「※ 概算です」が結果直下に常時表示
- [ ] URL パラメータ `?fish=aji&count=35&size=25` で初期値セットされる
- [ ] フッターに「← 船釣り予想に戻る」リンクのみ
- [ ] バニラ JS・CDN 不使用・ビルド不要
- [ ] スマホ375px で横スクロール出ない

---

## 11. 参考: 計算サンプル全体フロー

```
[ユーザー入力]
fish = "aji" / count = 35 / size = 25 (cm)
     ↓
[fish-species-map.json 検索]
species.site_fish_id === "aji" → pfid = "maaji" / input_modes = ["cm"]
     ↓
[fish-price-master.json 検索]
prices["maaji"] = { size_weight_curve, size_bands, ... }
     ↓
[cm → kg 線形補間]
25cm → 0.16 kg/尾  ※curve: 20cm=0.08 / 25cm=0.16 / 30cm=0.28
     ↓
[band 選択 (kg_max 昇順)]
0.16 ≤ 0.30 → band="中" (standard)
band.wholesale_low=493 / high=1057 / retail_low=986 / high=3171
     ↓
[総量計算]
totalKg = 0.16 × 35 = 5.6 kg
     ↓
[金額計算]
wholesale: 5.6 × 493 = 2,761 〜 5.6 × 1057 = 5,919
retail   : 5.6 × 986 = 5,522 〜 5.6 × 3171 = 17,758
     ↓
[100円単位丸め]
wholesale: 約 2,800 〜 5,900 円
retail   : 約 5,500 〜 17,800 円
     ↓
[1匹あたり]
wholesale/35: 約 80 〜 170 円
retail/35   : 約 160 〜 510 円
     ↓
[画面表示]
size-badge: "中" / weight: "推定総重量 5.6 kg"
小売: "約 5,500 〜 17,800 円" / "1匹あたり 約 160 〜 510 円"
卸売: "約 2,800 〜 5,900 円" / "1匹あたり 約 80 〜 170 円"
```

---

以上。質問があれば「不明点ある？」と聞いてくれれば追補します。
