# FAQ セクション拡張 — 設計案（2026-05-02）

## 前提
- 現状: fish/*.html / area/*.html に自動生成FAQ 4問（データ駆動）
- 追加: `normalize/fixed_faq.json` の固定FAQ（共通7問 + 魚種6種×2-3問 + エリア5箇所×2-3問）

## 1. 表示構造（推奨）
**2ブロック分離・同一セクション内・自動生成を上、固定を下**

```
[既存 FAQ ブロック .faq-data]   ← 自動生成 4問（データ由来）
[固定 FAQ ブロック .faq-static] ← キュレーション済み (固有 + common)
```

順序根拠: 自動生成は即時性のある数値（匹数・件数）でページ核心。固定は背景知識でいつ見ても同じ。
共通FAQ: 全ページ表示。固定FAQ無い魚種・エリアは common 7問のみ。

| ページ | 自動生成 | 固定FAQ |
|---|---|---|
| fish (6魚種対象) | 4問 | 魚種固有 2-3問 + common 7問 |
| fish (対象外) | 4問 | common 7問のみ |
| area (5エリア対象) | 4問 | エリア固有 2-3問 + common 7問 |
| area (対象外) | 4問 | common 7問のみ |

## 2. 出典表示
**回答末尾インライン・`<small>` タグ・`rel="nofollow noopener noreferrer"` + `target="_blank"`**

```html
<p class="faq-ans">
  前日にしっかり睡眠を取り……。
  <small class="faq-src">出典:
    <a href="..." target="_blank" rel="nofollow noopener noreferrer" class="faq-src-link">石黒G</a>、
    <a href="..." target="_blank" rel="nofollow noopener noreferrer" class="faq-src-link">釣りハック</a>
  </small>
</p>
```

URLテキストはサイト名で短縮表示。

## 3. SEO・JSON-LD
**固定FAQも FAQPage JSON-LD に統合・1ページ1FAQPage**

- schema.org は同一ページに複数 FAQPage 非推奨。Google は最初の1つしか処理しない傾向
- `build_fish_faq_html()` の戻り値を `(html, faq_pairs)` に変更し、JSON-LD組み立てをページビルダー側に移す
- 共通FAQの大量重複は通常ペナルティなし（船酔い等は自然な共通コンテンツ）。`data-scope` 属性で将来対応の識別子保持
- sources URL は HTML のみ表示・JSON-LDには含めない（GoogleのAnswer.url使用は限定的）

## 4. CSS 差分（追記のみ）

```css
/* ── FAQ ブロック内小見出し ── */
.faq-block-ttl{
  font-size:11px;font-weight:700;color:var(--muted);
  text-transform:uppercase;letter-spacing:.06em;
  padding:10px 0 6px;border-bottom:1px solid var(--border);margin-bottom:2px
}
.faq-block-ttl:first-child{padding-top:2px}
.faq-block-ttl--common{margin-top:10px}

/* ── FAQ 出典リンク ── */
.faq-src{display:block;font-size:10px;color:var(--muted);margin-top:6px;line-height:1.5}
.faq-src-link{color:var(--muted);text-decoration:underline;text-decoration-style:dotted}
.faq-src-link:hover{color:var(--sub)}
.faq-src-link::after{content:" ↗";font-size:9px}
```

既存 `.faq-list` / `.faq-ans` は変更なし。`faq-data` / `faq-static` は modifier クラス（現時点で追加スタイル不要）。

## 5. HTML出力例（fish/aji.html）

```html
<h2 class="st">よくある質問 <span class="tag free">無料</span></h2>

<div class="faq-list faq-data">
  <h3 class="faq-block-ttl">アジ釣果データから分かること</h3>
  <details><summary>アジの旬はいつですか？</summary>
    <p class="faq-ans">直近のデータでは6月・7月・8月が実績が多い…</p></details>
  <!-- 残3問 -->
</div>

<div class="faq-list faq-static" data-scope="fish-アジ">
  <h3 class="faq-block-ttl">アジ船釣りの基礎知識</h3>
  <details><summary>ライトアジとビシアジの違いは？</summary>
    <p class="faq-ans">ビシアジは120〜130号の重いビシで…
      <small class="faq-src">出典:
        <a href="..." target="_blank" rel="nofollow noopener noreferrer" class="faq-src-link">仕掛け大全</a>
      </small>
    </p></details>
  <!-- 魚種固有残問 -->

  <h3 class="faq-block-ttl faq-block-ttl--common">船釣り共通の基礎知識</h3>
  <details><summary>船釣り初心者は何を持っていけばいいですか？</summary>
    <p class="faq-ans">酔い止め薬・タオル…<small class="faq-src">出典: ...</small></p></details>
  <!-- common 残6問 -->
</div>
```

## 6. アクセシビリティ
- `<details>/<summary>` はSR対応OK
- 出典リンクの `::after { content:" ↗" }` で外部リンク視覚化（WCAG 2.4.4）
- ネストアンカー禁止（不変条件#11）— `<details>` 内 `<a>` は問題ない（`<details>` は anchor ではない）

## 7. 実装フロー（programmer 向け）

1. `normalize/fixed_faq.json` を読み込むローダー追加（`_load_fixed_faq()`）
2. `build_fish_faq_html()` を `(html, faq_pairs_list)` 返すよう変更
3. 新関数 `build_fixed_faq_html(scope_type, scope_key)` を追加（fish/area対応）
4. ページビルダー（`build_fish_pages` / `build_area_pages`）で:
   - 既存FAQ html + 固定FAQ html を連結
   - 全 q/a を統合した FAQPage JSON-LD を `<head>` に出力
5. CSS差分を `V2_COMMON_CSS` 末尾または `design/V2/style.css` に追記
6. `crawl/validate_output.py` 既存不変条件への影響なし

## 8. 文言案
- 魚種: `{魚種}釣果データから分かること` / `{魚種}船釣りの基礎知識` / `船釣り共通の基礎知識`
- エリア: `{エリア}釣果データから分かること` / `{エリア}を釣り場として知る` / `船釣り共通の基礎知識`
