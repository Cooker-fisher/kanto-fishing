# x_post 日付ジャンプ UI 4案（2026-05-10・designer）

## 0. 前提

ユーザー要望:「過去リンクだけど、これだと前後の日しか飛べないよ。最新から最古にとべたりできない？三日前とか一気に飛ぶ方法。なにか良い方法」

現状:
- `x_post/build_daily_page.py` L587-598: 前日/翌日 ±1日のみ
- `x_post/build_index_page.py`: `/x_post/index.html` に既に「直近30日アーカイブリスト」が実装済（資産活用可能）
- 5/1〜5/9 の9日分が遡及生成済み（コミット df3c6005）

---

## 案A. ±N日ジャンプボタン拡張

### コンセプト

現 day-nav の2ボタンを5ボタンに拡張、「7日前」「翌7日」を追加、中央に「全アーカイブ」CTA。「3日前に一気」要望には「7日前」で上位互換として応える。

### ワイヤー

モバイル 360px（2行レイアウト）:
```
行1: [← 7日前]    [全アーカイブ一覧]    [7日後 →]
行2: [← 前日 5/9(金)]            [翌日 5/11(日) →]
```

PC 600px超（1行5列）:
```
[← 7日前][← 前日][全一覧][翌日 →][7日後 →]
```

HTMLサンプル:
```html
<nav class="day-nav day-nav-5" aria-label="日付ナビゲーション">
  <a class="prev7" href="./2026-05-03.html"><small>← 7日前</small>5/3(土)</a>
  <a class="prev" href="./2026-05-09.html"><small>← 前日</small>5/9(金)</a>
  <a class="archive-cta" href="./index.html"><small>全日程</small>一覧へ</a>
  <a class="next" href="./2026-05-11.html"><small>翌日 →</small>5/11(日)</a>
  <span class="next7 disabled"><small>7日後 →</small>記録なし</span>
</nav>
```

### 実装スケッチ

- L587-598: prev7/next7 の日付計算を ctx に追加
- ctx 追加: `prev7_date_iso/label/exists`, `next7_date_iso/label/exists`
- L236 CSS: `grid-template-columns: 1fr 1fr` → `repeat(5, 1fr)`、モバイル `@media (max-width:480px)` で2行化
- main.js 不要

### モバイル UX

2行レイアウトで行1=3列（各 111px）、行2=2列（各 167px）。タップ領域 `padding: 10px 0; min-height: 44px`。

### アクセシビリティ

`<nav aria-label>` 囲み、disable は `<span aria-disabled="true">`。

### 実装コスト

- build_daily_page.py: +20行 / crawler.py 側 ctx 計算 +10行
- CSS: +15行
- ctx 追加 6フィールド
- 計: 約 50 行

### リスク

- 7日前が記録なし日連続だと disabled 多発でユーザー混乱
- 「最新→最古」要求は未解決（一覧経由が必要）
- REGRESSION_PREVENTION [11] ネストアンカー: `<nav>` 直下フラット配置で問題なし

### メリット・デメリット

✅ JS 不要・SSR 完結
✅ 「7日前」で「3日前・5日前」要求を包含
❌ 最古端への到達は繰り返しタップが必要
❌ 「最新→最古」一発ジャンプ未対応

---

## 案B. `<input type="date">` カレンダーピッカー

### コンセプト

HTML5 ネイティブ picker を中央に配置、JS で選択日付ファイルへ遷移。「3日前」「最古」どちらも 1 操作。記録なし日のハンドリングが要。

### ワイヤー

```
[← 前日]  [ 日付選択 📅 2026-05-10 ▼ ]  [翌日 →]
```

HTMLサンプル:
```html
<nav class="day-nav day-nav-picker" aria-label="日付ナビゲーション">
  <a class="prev" href="./2026-05-09.html"><small>← 前日</small>5/9(金)</a>
  <div class="picker-wrap">
    <label class="picker-label" for="date-jump">日付を選択</label>
    <input type="date" id="date-jump" class="date-picker"
           value="2026-05-10" min="2026-05-01" max="2026-05-10"
           aria-label="日付を選んでジャンプ">
    <p class="picker-note">記録なし日は空ページになります</p>
  </div>
  <a class="next" href="...">翌日 →</a>
</nav>
```

JS (main.js):
```javascript
document.getElementById('date-jump')?.addEventListener('change', function() {
  const v = this.value;
  if (v) window.location.href = `/x_post/${v}.html`;
});
```

### 実装スケッチ

- L587-598: HTML 追加 + ctx の min/max 渡し
- main.js: +5行
- CSS: +10行
- ctx 追加 2フィールド（archive_min_date, archive_max_date）
- 404.html 整備推奨（記録なし日選択時の対策）

### モバイル UX

OS ネイティブ picker 起動。タップ領域はブラウザ制御で 44px 問題なし。

### アクセシビリティ

`<label for>` で SR 対応、キーボードで Enter→矢印→Enter→change イベント。

### 実装コスト

- build_daily_page.py: +15行
- main.js: +5行
- CSS: +10行
- ctx +2フィールド（または固定値で 0）
- 404.html: +20行（任意）
- 計: 約 30 行

### リスク

- 記録なし日選択 → 404 のUX破綻リスク
- min〜max 範囲内に空き日多数 → ピッカー上では選べる見えで期待値ミスマッチ
- JS 依存（無効環境でも前日/翌日は残る）

### メリット・デメリット

✅ 「最新→最古」「3日前」どちらも1操作
✅ min/max でブラウザがグレーアウト
❌ 記録なし日の取り扱いが明快に解決しない
❌ JS 必須（main.js 修正）

---

## 案C. 「全アーカイブへ」ボタンを目立たせる

### コンセプト

±1日ナビは維持、3列目に「全30日一覧へ」CTA を追加。`/x_post/index.html`（既存30日アーカイブ）が「ジャンプハブ」として機能する役割分担。

### ワイヤー

モバイル 360px（3列グリッド）:
```
行1: [← 前日 5/9]   [全一覧 30日分]   [翌日 5/11 →]
```
中央 CTA を `var(--cta-soft)` 配色で強調。

HTMLサンプル:
```html
<nav class="day-nav" aria-label="日付ナビゲーション">
  <a class="prev" href="...">...</a>
  <a class="archive-hub" href="./index.html"
     aria-label="全30日の釣果速報一覧を見る">
    <small>30日分一覧</small>全アーカイブ
  </a>
  <a class="next" href="...">...</a>
</nav>
```

CSS:
```css
.day-nav { grid-template-columns: 1fr 1.2fr 1fr; }
.archive-hub {
  text-align: center;
  background: var(--cta-soft);
  border-color: var(--cta);
  color: var(--cta);
  font-weight: 800;
}
```

### 実装スケッチ

- L236 CSS: grid を 2列 → 3列に変更
- L592-598: prev_html + archive_hub + next_html の3要素化
- ctx 追加なし
- main.js / build_index_page.py 変更なし

### モバイル UX

3列で各 100/120/100px 程度。`padding: 10px 14px; min-height: 44px`。

### アクセシビリティ

`<a href aria-label>` で SR 対応、Tab 遷移自然。

### 実装コスト

- build_daily_page.py: 3行修正 + CSS 5行
- crawler.py / ctx / main.js / build_index_page.py 変更なし
- 計: **約 10 行未満**（4案中最小）

### リスク

- 「3日前へ一気」が2ステップ（個別 → index → 3日前）
- index.html を「ハブ」と認識させる視覚誘導要

### メリット・デメリット

✅ 実装コスト最小
✅ 既存資産（30日アーカイブ）を直接活用
❌ 「3日前へ一気」が2ステップ
❌ index.html 側のハブ性強化が別途必要

---

## 案D. タイムラインバー（ドット型）

### コンセプト

直近30日のドットを横一列に。記録あり=塗り・記録なし=白抜き・現在地=ハイライト。「最新→最古」も「3日前」も1タップ。日付の相対位置感覚を提供。

### ワイヤー

```
PC: ◀ 5/1● 5/2○ 5/3● 5/4● 5/5● 5/6○ 5/7● [★5/10] 5/11○ ... ▶
モバイル: ←  ●●●○● ★ ○●●  → （横スクロール・スナップ）
```

HTMLサンプル:
```html
<div class="timeline-nav" role="navigation" aria-label="日付タイムライン">
  <div class="tl-track" role="list">
    <a class="tl-dot has-record" href="/x_post/2026-05-09.html"
       role="listitem" aria-label="5/9(金) の釣果速報">
      <span class="tl-label">5/9</span>
    </a>
    <span class="tl-dot current" role="listitem"
          aria-current="page" aria-label="5/10(土) 現在地">
      <span class="tl-label">5/10</span>
    </span>
    <span class="tl-dot no-record" role="listitem"
          aria-label="5/11(日) 記録なし" aria-disabled="true" tabindex="-1">
      <span class="tl-label">5/11</span>
    </span>
  </div>
</div>
```

CSS（主要部分）:
```css
.tl-track { display: flex; gap: 4px; overflow-x: auto;
  scroll-snap-type: x mandatory; padding: 8px 4px; }
.tl-dot { flex: 0 0 36px; height: 36px; border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  position: relative; scroll-snap-align: center; text-decoration: none; }
.tl-dot .tl-label { position: absolute; top: 38px; font-size: 9px;
  opacity: 0; transition: opacity .15s; }
.tl-dot:hover .tl-label, .tl-dot:focus .tl-label { opacity: 1; }
.tl-dot.has-record { background: var(--port); }
.tl-dot.current { background: var(--cta); border: 3px solid var(--accent); }
.tl-dot.no-record { background: #fff; border: 2px solid var(--border); cursor: default; }
```

JS (main.js): 現在地ドットへ自動スクロール
```javascript
const cur = document.querySelector('.tl-dot.current');
if (cur) cur.scrollIntoView({ inline: 'center', behavior: 'smooth', block: 'nearest' });
```

### 実装スケッチ

- build_daily_page.py: `_build_timeline_html(archive_dates, current_date)` 関数 +40行、呼び出し +5行
- CSS: +30行
- main.js: +3行
- ctx 追加 1フィールド（archive_dates_list）
- crawler.py: archive_dates_list を ctx に渡す処理 +10行
- 計: 約 90 行

### モバイル UX

ドット 36px + gap 4px = 40px。30ドット = 1200px → 横スクロール必須。`scroll-snap-type` で 1ドット単位スナップ。`scrollIntoView` で現在地自動センタリング。

### アクセシビリティ

`role="list/listitem"`、現在地に `aria-current="page"`、記録なしに `aria-disabled="true" tabindex="-1"`。

### 実装コスト

4案中最大（約 90 行）

### リスク

- 30日超蓄積後の UI 肥大化（横スクロール量増加・直近30日に固定する設計推奨）
- ドットサイズと文字ラベル可読性のトレードオフ
- index.html 埋め込み時の相対パス: 絶対パス `/x_post/...` を使い回避
- REGRESSION_PREVENTION [11] ネストアンカー: `<a>` 内の `<span>` は問題なし

### メリット・デメリット

✅ 「どの日付が存在するか」が視覚的に一目瞭然
✅ 「最新→最古」「3日前」どちらも1タップ
✅ 日付の相対位置感覚を提供
❌ 4案中で実装コスト最大
❌ ラベル非表示時のタップ精度

---

## 比較表

| 観点 | 案A | 案B | 案C | 案D |
|---|---|---|---|---|
| 実装コスト | 中（+50行） | 中（+30行 + JS 5行） | **小（+10行未満）** | 大（+90行） |
| 「3日前へ一気」充足度 | 中（7日前ボタン・欠け日 disabled） | **高**（任意日直指定） | 低（2ステップ経由） | **高**（ドット1タップ） |
| 「最新→最古」充足度 | 低（連打必要） | **高**（任意日直指定） | 中（一覧から選択） | **高**（端ドットタップ） |
| モバイル UX | 中（2行レイアウト要） | **高**（OS ネイティブ） | **高**（3列で余裕） | 中（スクロール・タップ領域注意） |
| 既存30日アーカイブ活用 | 低 | 低（404 補完程度） | **高**（直接ハブ化） | 低（並立） |
| 保守コスト | 低 | 中（JS+404+min/max） | **低**（変更箇所最小） | 中（dates 同期） |

---

## designer 推奨

**最推奨: 案C（即時）+ 案A（次ステップ）の段階実装**

案C はコスト最小（10行未満）で既存の30日アーカイブを「ジャンプハブ」として即座に活用できる。`/x_post/index.html` はすでに `auto-fill minmax(260px,1fr)` グリッドで30日分を一覧表示しており、そこへの導線を day-nav に明確に追加するだけでユーザーの「任意の日に飛びたい」要求を実質的に満たす。

その後、蓄積日数が増えてきた段階（30日超・2か月後）で案A の「7日前/後ボタン」を追加すれば、よく使う「直近1週間内の移動」が個別ページ内で完結する。案B（picker）は記録なし日の 404 問題解決にコストがかかる割に、案C+A の2段階で同等の UX が達成可能。案D は UI 完成度が高いが実装コストと dot タップ領域問題があり、蓄積日数が60日を超えてから検討するのが妥当。

---

## 付録: pm 注記

- designer ロール（Write 含まず）が会話に出力した内容を pm が代理書き出し
