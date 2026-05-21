# index.html 内部リンク統一・監査＋設計（2026-05-21）

主担当: PM 自身（researcher/designer サブエージェントが grep 段階で停止したため統合実施）
スコープ: 「/ と /index.html がズレる」現象に対する内部リンクからの `/index.html` 完全排除

---

## 0. 背景・前提

- 観測現象: `/` は 5/20(水)・74件、`/index.html` は 5/19(火)・65件 と表示がズレた
- 調査結果（curl -sI 比較）:
  - 両URLとも **ETag `"6a0e35ee-1398e"`・Last-Modified `Wed, 20 May 2026 22:30:06 GMT`・Content-Length 80270 一致**
  - ファイル自体は同一（GitHub Pages 仕様で `/` リクエストは `index.html` を返す）
- 原因: GitHub Pages の Fastly CDN が `/` と `/index.html` を別キャッシュキー管理、`Cache-Control: max-age=600`（10分・サーバー側固定で変更不可）のため最大10分間表示が乖離し得る
- 対応方針: 内部リンクから `/index.html` を全排除し、サイト内クリック導線でズレに遭遇する経路を断つ

---

## 1. サマリ

- crawler.py 内に `/index.html` および `../index.html` の内部リンク **15箇所** が存在
- うち1箇所（line 10604 第2リンク）は別バグ：「有料プラン」のリンク先が誤って `../index.html`（＝トップ）を指している。本来 `../forecast/` を指すべき → 合わせて修正
- 全15箇所を `/` または `../`（有料プランのみ `../forecast/`）に置換
- validate_output.py に不変条件 24 を追加し regression 防止
- mockup-*.html 内の同パターンは後追い（不変条件は docs/ 配下のみ検査対象）

---

## 2. 修正テーブル

### 2-A. 絶対パス `/index.html` → `/`（7箇所）

| line | コンテキスト | 修正前 | 修正後 |
|---|---|---|---|
| 2160 | forecast/ パンくず「トップ」 | `<a href="/index.html">トップ</a>` | `<a href="/">トップ</a>` |
| 4152 | 共通ヘッダ site-logo | `<a href="/index.html" class="site-logo">` | `<a href="/" class="site-logo">` |
| 4157 | 共通ナビ「今日の釣果」 | `<a href="/index.html"{...}>今日の釣果</a>` | `<a href="/"{...}>今日の釣果</a>` |
| 4187 | nav config 配列 | `("index", "/index.html", "釣果", "")` | `("index", "/", "釣果", "")` |
| 12603 | ship/*.html ヘッダ site-logo | `<h1><a href="/index.html">船釣り<span>予想</span></a></h1>` | `<h1><a href="/">船釣り<span>予想</span></a></h1>` |
| 12607 | ship/*.html ナビ「今日の釣果」 | `<a href="/index.html">今日の釣果</a>` | `<a href="/">今日の釣果</a>` |
| 12616 | ship/*.html モバイル下部ナビ「釣果」 | `<a href="/index.html"><span class="i">🎣</span>釣果</a>` | `<a href="/"><span class="i">🎣</span>釣果</a>` |

### 2-B. 相対パス `../index.html` → `../`（8箇所）

| line | コンテキスト | 修正前 | 修正後 |
|---|---|---|---|
| 8211 | fish/*.html パンくず「トップ」 | `<a href="../index.html">トップ</a>` | `<a href="../">トップ</a>` |
| 8464 | fish/index.html パンくず「トップ」 | `<a href="../index.html">トップ</a>` | `<a href="../">トップ</a>` |
| 8795 | area/*.html パンくず「トップ」 | `<a href="../index.html">トップ</a>` | `<a href="../">トップ</a>` |
| 9195 | area/*.html パンくず別箇所 | `<a href="../index.html">トップ</a>` | `<a href="../">トップ</a>` |
| 9534 | area/index.html パンくず「トップ」 | `<a href="../index.html">トップ</a>` | `<a href="../">トップ</a>` |
| 10370 | fish_area/*.html パンくず「トップ」 | `<a href="../index.html">トップ</a>` | `<a href="../">トップ</a>` |
| 10604 第1 | pages/plan.html パンくず「トップ」 | `<a href="../index.html">トップ</a>` | `<a href="../">トップ</a>` |
| 10633 | pages/plan.html plan-cta「無料で使う」 | `<a class="plan-cta" href="../index.html">無料で使う</a>` | `<a class="plan-cta" href="../">無料で使う</a>` |

### 2-C. 副次バグ修正（スコープに含める）

| line | コンテキスト | 修正前 | 修正後 | 理由 |
|---|---|---|---|---|
| 10604 第2 | pages/plan.html パンくず「有料プラン」 | `<a href="../index.html">有料プラン</a>` | `<a href="../forecast/">有料プラン</a>` | 他箇所（line 4163, 12611, 4435, 13828, 13837）では全て「有料プラン」リンクが `/forecast/...` を指している。プラン比較ページのパンくずだけ誤って `../index.html`（トップ）を指していた。/index.html → / 統一だけ行うと「トップ」「有料プラン」が同じ URL に着地する UX バグになるので併せて修正 |

**合計: 16箇所**

### 2-D. 除外（サブディレクトリ index.html・置換対象外）

これらは別ページなので**置換しない**:
- `/forecast/index.html`（line 2160 2つ目, 2263, 4163, 4192, 4435, 12611, 12620, 13828, 13837）
- `/x_post/index.html`（line 4158）
- 内部参照 `fish/index.html`・`area/index.html`（line 8447, 8473, 9517, 9542, 12961, 12969 等）

---

## 3. 不変条件 24（提案）

### REGRESSION_PREVENTION.md 表追加分

| # | チェック | 閾値 |
|---|---|---|
| 24 | 全 `docs/**/*.html`（`index.html`・`fish/*.html`・`area/*.html`・`fish_area/*.html`・`ship/*.html`・`forecast/*.html`・`calendar.html`・`x_post/*.html`・`pages/*.html`・`komase-sim/*.html` 全部） | `href="/index.html"`・`href='/index.html'`・`href="../index.html"`・`href='../index.html'` の出現が**0件**。例外なし。サブディレクトリ index（`/forecast/index.html` 等）はパス文字列が異なるためパターンに該当しない |

### validate_output.py 追加コード（提案）

```python
# 不変条件24: 内部リンクから /index.html を排除（CDNキャッシュズレ対策）
print("\n[24] 全 docs/**/*.html で /index.html 内部リンクが消滅していること")
violating = []
walked = 0
for root, dirs, files in os.walk(DOCS):
    for f in files:
        if not f.endswith(".html"):
            continue
        walked += 1
        p = os.path.join(root, f)
        with open(p, encoding="utf-8", errors="ignore") as fh:
            text = fh.read()
        for pat in ('href="/index.html"', "href='/index.html'",
                    'href="../index.html"', "href='../index.html'"):
            if pat in text:
                violating.append((os.path.relpath(p, DOCS), pat))
                break  # 1ファイル1報告
if violating:
    for relp, pat in violating[:10]:
        fail(f"内部リンク /index.html 残存: {relp} ({pat})")
    if len(violating) > 10:
        fail(f"残存ファイル: あと {len(violating)-10} 件")
else:
    ok(f"全 {walked} 個の docs/*.html で /index.html 内部リンク消滅")
```

設置位置: `validate_output.py` 末尾（最終チェックブロック）。23 の次として追加。

---

## 4. mockup 系（後追い・本タスク外）

`design/V2/mockup-*.html` の以下にも同パターンが残存（本番ではないので不変条件対象外）:

- `mockup-forecast-day-v2.html`: line 95, 100, 107, 264
- `mockup-premium-v2.html`: line 147, 163, 282, 286
- `mockup-plan-v2.html`: line 90, 102, 132, 242, 246
- `mockup-T38-phaseC-v1.html`: line 127, 378

→ 別タスクで mockup も統一する（本実装後）。

---

## 5. 90_決定ログ 追記文面（提案）

`design/V2/90_決定ログ.md` 末尾追加:

```markdown
### 2026-05-21 — 「/ と /index.html がズレる」現象への対策

- **観測現象**: トップページの2つの URL `https://funatsuri-yoso.com/` と `https://funatsuri-yoso.com/index.html` が、同じ瞬間に異なるバージョン（前者 5/20・74件 / 後者 5/19・65件）を返す瞬間があった
- **調査結果**:
  - `curl -sI` で確認: 両URLとも **同一 ETag `"6a0e35ee-1398e"`・同一 Last-Modified `Wed, 20 May 2026 22:30:06 GMT`・同一 Content-Length 80270 bytes** → サーバー側にあるファイルは1つ
  - `crawler.py` は `docs/index.html` を1ファイルだけ生成しており、別経路で `/index.html` を生成していない
  - canonical はすでに両方とも `https://funatsuri-yoso.com/`（trailing slash）に統一済み（`crawler.py:7498`）
- **原因**: GitHub Pages の Fastly CDN は `/` と `/index.html` を別キャッシュキーで管理。`Cache-Control: max-age=600`（10分・GitHub 側固定で変更不可）のため、片方のキャッシュが先に invalidate されると最大10分間ズレが見える
- **決定**:
  1. **内部リンクから `/index.html` を完全排除**（`/` に統一・相対パス `../index.html` も `../` に統一）。`crawler.py` の15箇所を修正
  2. **副次バグ修正**: `pages/plan.html` パンくず「有料プラン」リンクが誤って `../index.html` を指していたのを `../forecast/` に修正（`crawler.py:10604`）
  3. **不変条件 24 追加**: 全 `docs/**/*.html` で `href="/index.html"` `href="../index.html"` が出現しないことを `validate_output.py` で検証
  4. mockup 系（`design/V2/mockup-*.html`）も追って統一（別タスク・docs 配下ではないので不変条件対象外）
- **残存リスク**: 外部ブクマ・古いSNSシェア・直URL貼り付けで `/index.html` に来た人は引き続き CDN TTL 10分の影響を受ける。GitHub Pages 側の仕様で対策不可。canonical で SEO 上は `/` に統一済みなので、検索流入は時間と共に `/` に寄る
- **関連ロール**: プログラマー、レビュー
```
