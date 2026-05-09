# T22_designer_proposal.md

## 1. 概要

**ゴール**: AdSense「有用性の低いコンテンツ」却下（2026/05/09 8:50 JST）を解消し、再申請可能状態を作る。

**根本診断**: 全ページのナビゲーションに「有料プラン」リンクが存在し、Google クローラーが必然的に `docs/forecast/index.html` を中核機能として評価する。そのページが本文 200 字・coming soon のまま放置されていることが致命傷。HIGH 3 件（H1〜H3）を優先解消し、MID 3 件（M1〜M3）でコンテンツ密度を底上げする。

**前提制約**（変更不可）:
- 無料=事実の数値のみ、有料=分析+予測（90_決定ログ 2026/04/04）
- avg/平均を出さない（90_決定ログ 補遺3）
- 11 不変条件（REGRESSION_PREVENTION.md）を維持
- T19/T20/T21 の成果を無効化しない

---

## 2. H1: `docs/forecast/index.html` が coming soon 200 字

### 3 案比較表

| 評価軸 | 案A: noindex 化 | 案B: 実コンテンツ生成 | 案C: noindex 暫定 + 後続 T で実コンテンツ |
|---|---|---|---|
| AdSense 観点 | ◎ 審査対象から完全除外・即効 | ○ コンテンツ充実で好印象だが実装後の品質次第 | ◎ 再申請までは確実に除外 |
| マネタイズ方針整合 | △ 「有料機能の入口が存在しない」状態になる | ◎ 「無料=事実」方針の週次まとめとして成立 | ○ 暫定期間は整合が薄い・本番で回収 |
| 実装コスト | ◎ crawler.py の `_forecast_page_head()` に 1 行追加・sitemap 除外のみ | △ `build_forecast_pages()` に週次まとめ生成ロジック追加（約 100 行規模） | ◎ 即時は A と同コスト |
| 再申請までの時間 | ◎ 当日対応可 | △ 実装・検証・QA で最低 3〜5 日 | ◎ 当日対応可 |
| 長期 SEO 観点 | × noindex は永続するとサイトの有料機能導線がクロールされない・有料化後に戻し忘れリスク | ◎ index 化したまま価値あるページとして育てられる | ○ 暫定 noindex を外すタイミング管理が必要だが、計画が明確 |

### designer 推奨: 案 C（noindex 暫定 + T23 で実コンテンツ化）

**理由（100 字）**: AdSense 再申請を最速で可能にしつつ、「有料機能入口の恒久的消滅」を避ける。noindex 解除タイミングを T23 完了と紐付けることで戻し忘れリスクをゼロにする。案 A の永続 noindex は有料化後の SEO 損失が大きく却下。案 B は再申請を 3〜5 日遅らせるリスクがある。

**案 C の実装詳細**:

1. `crawler.py` の `_forecast_page_head()` 関数（L1947 付近）に `<meta name="robots" content="noindex, follow">` を追加する。`nofollow` ではなく `follow` とし、内部リンクのクロールは維持する。
2. `build_sitemap()` 関数内の forecast/ URL 列挙部分に条件分岐を追加し、`forecast/index.html` と `forecast/*.html`（日次・週次・エリア別）を sitemap.xml から除外する。ただし除外後も `docs/forecast/` ディレクトリは維持し、ナビリンクも残す（ユーザー誘導は継続）。
3. T23 を「forecast/index.html の実コンテンツ化（週次釣果まとめ + 今後の見どころ・無料事実ベース）」として起票し、T23 完了時に `noindex` を削除・sitemap 復帰の手順をセットで記録する。

**noindex タグの挿入位置**: `_forecast_page_head()` の `<meta name="viewport">` の直後。

```
<meta name="robots" content="noindex, follow">
```

**sitemap 除外**: **不要**。現行 `build_sitemap()` L10430〜L10500 を grep 確認（reviewer 検証済）した結果、forecast/ URL は sitemap.xml に未収録。実装対象は `_forecast_page_head()` への noindex タグ追加のみに絞る。T23 完了後に noindex 解除時 sitemap への追加が必要になる場合は T23 のスコープとする。

---

## 3. H2: 空 `docs/ship/*.html` の noindex 化

### 確定方針

**判定基準（OR 条件）**: 以下のいずれかに該当するページを「空ページ」と判定し noindex を付与する。

- 条件 1: `_ship_recent_fish_html()` が `'直近7日のデータがありません'` テキストを含む HTML を返した（L9900 付近の早期 return）
- 条件 2: `ship_info.get(ship_name)` が `None`（ship_info.json に登録がなく、住所・電話・基本情報が全欠如）

両条件を OR で評価する。AND 条件にすると「情報はあるがデータ空」のページが漏れるため OR が正しい。

**実装場所**: `_ship_build_page_html()` 関数（L10065 付近）内の HTML 生成部分。`_ship_recent_fish_html()`（L9872）の戻り値に `直近7日のデータがありません`（L9900）が含まれるかを文字列検索で判定する方式を主案とする（reviewer 指摘）。

注: `build_ship_pages()`（L10399）は呼び出し側で HTML 文字列を受け取るのみで、`fish_count` ローカル変数を直接参照できないため、判定処理は `_ship_build_page_html()` 内で完結させる。

実装イメージ（主案：文字列検索方式）:

```python
# _ship_build_page_html() 内の HTML 組み立て部分（L10065 付近）
recent_html = _ship_recent_fish_html(...)
has_recent_data = "直近7日のデータがありません" not in recent_html
has_ship_info = ship_name in _SHIP_INFO  # ship_info.json 登録有無
is_empty_page = (not has_recent_data) or (not has_ship_info)
noindex_tag = '<meta name="robots" content="noindex, follow">' if is_empty_page else ""
```

代替案として `_ship_recent_fish_html()` の戻り値に `has_data` フラグを含めるリファクタリングも可能だが、scope と影響範囲が広がるため programmer 裁量とする。

**sitemap.xml からの除外**: 現行 `build_sitemap()` L10484〜L10487 は「`romaji_slug` あり かつ `_SHIP_INFO` 登録あり」の AND 条件で船宿 URL を sitemap に追加している（reviewer grep 確認済）。本 T22 の noindex 判定（OR 条件: `_SHIP_INFO` 未登録 OR データ空）と組み合わせると、`_SHIP_INFO` 未登録分は既に sitemap から除外済みとなる。残るは「`_SHIP_INFO` 登録あり かつ データ空」のページであり、これは `build_sitemap()` 内に同等の文字列検索条件を追加するか、`_ship_build_page_html()` の判定結果をモジュールレベル set に蓄積して `build_sitemap()` 側で参照する方式とする。

programmer は実装前に「対象 10 件の内訳」と「sitemap.xml 現行収録数」を `grep` で先確認し、実態に基づいて実装方式を選ぶこと。

**内部リンクは維持**: index.html・area/*.html・fish/*.html の船宿リンク（`_ship_link()` が生成するアンカー）は残す。ユーザーが船宿名をクリックしてページに辿りつける経路は変えない。データが蓄積されれば翌日の自動生成で自動的に noindex が外れる。

**対象規模の見積もり**: researcher 監査で「推定 10 件」とされている。`ishida-maru.html`（大津港・直近データなし）・`aoki-maru.html` 等が該当。

---

## 4. H3: `docs/fish_area/*.html` 22-25KB 帯にエリア固有説明文

### 確定方針: ハイブリッド方式（上位 10 件手書き + 残りは既存自動生成維持）

**現状分析**: T11 で実装した `_build_fa_intro_html()` は既に全 54 件に 200 字以上の説明文を生成している（L8077〜L8127）。researcher が指摘した「22-25KB 帯にエリア固有説明文ゼロ」は T11 実装前の状態に基づく可能性が高い。ただし自動生成テキストは「N 件記録されています」「中央値は X 匹で」という数値羅列型で、エリアの地理的特性・釣り場の雰囲気・ポイントの特徴といった固有情報がゼロの状態は続いている。

**改善方針**: `normalize/area_description.json`（エリア別説明文・手書き済み・全港カバー）を fish_area ページに活用する。現状の `_build_fa_intro_html()` は `area_description.json` を参照していない。

**実装**: `_build_fa_intro_html()` 関数（L8077）に `area_description` 引数を追加し、冒頭にエリア固有の 1 文を差し込む。

```python
def _build_fa_intro_html(fish, area, fa_catches, decadal_calendar, area_description=None):
    # 冒頭: area_description.json からエリア特性の1文を抽出
    area_intro = ""
    if area_description and area in area_description:
        desc_full = area_description[area].get("description", "")
        # description の第1段落（改行前）の先頭1文を使う
        first_para = desc_full.split("\n\n")[0] if desc_full else ""
        first_sentence = first_para.split("。")[0] + "。" if first_para else ""
        if first_sentence and len(first_sentence) >= 20:
            area_intro = first_sentence
    # 以降は既存ロジック（数値ベース）
    lines = []
    if area_intro:
        lines.append(area_intro)
    lines.append(f"{area}での{fish}の釣果データは{N}件記録されています{years_str}。")
    # ... 以下既存
```

これにより「大津港は横須賀市の東京湾に位置し、湾内でも外洋の影響を受けやすい好漁場として知られている。大津港でのマダイの釣果データは〜」という形の固有性ある文章になる。

**対象**: `build_fish_area_pages()` 内で `_build_fa_intro_html()` を呼ぶ際に `area_description=load_area_description()` を渡す。`load_area_description()` は既存関数（L3267 付近に参照あり）。

**呼び出し元**: `_build_fa_intro_html()` の呼び出しは `build_fish_area_pages()` L8366 の **一箇所のみ**（reviewer grep 確認済）。引数 `area_description=None` をデフォルト値付きで追加するため後方互換性は維持され、既存テストへの影響はゼロ。

**上位 10 件の手書き補強（後続作業）**: アクセス上位の fish_area ページ（アジ×金沢八景・マダイ×走水等）については `normalize/fish_area_description.json` を新設し、エリア×魚種固有の 2〜3 文（ポイント名・有名な釣り場情報・釣り方特性）を手書きで追加することを推奨するが、これは T22 の必須スコープではなく T23 以降に委ねる。

---

## 5. M1: 共通 FAQ 9 問の重複解消

### 確定方針

**問題の構造**: `normalize/fixed_faq.json` の「船釣り共通の基礎知識」ブロック（船酔い防止・服装・予約方法・集合時間・ライフジャケット・マナー等 9 問）が `build_fixed_faq_html()` によって全 51 魚種ページに完全一致で出力されている。JSON-LD の FAQPage も同内容を 51 回複製している。

**対応方針**: 共通 9 問を `docs/pages/faq.html` に切り出す。各魚種ページには固有の 3 問（データ駆動型：`build_fish_faq_html()` が生成する Q1〜Q3 相当）のみ残し、末尾に「船釣り共通の Q&A はこちら → /pages/faq.html」リンクを設ける。

**faq.html のページ構成**:

- タイトル: 「船釣りよくある質問 | 船釣り予想」
- カテゴリ分け: 2 カテゴリ（「初めての船釣り」6 問・「当日の注意事項」3 問）
- JSON-LD: FAQPage（9 問を全掲載、1 ページに集約）
- BreadcrumbList: トップ > よくある質問
- レイアウト: 既存の `<details>/<summary>` アコーディオン、V2 CSS 適用、about.html と同等の構成
- 分量: 9 問 × 平均 150 字 = 約 1350 字 + ページ固有説明 200 字 = 合計 1500 字以上でコンテンツ量は十分

**各魚種ページ（fish/*.html）の変更**:

`build_fixed_faq_html()` の呼び出し結果を HTML に挿入する箇所（`build_fish_pages()` 内）において、共通ブロックの出力を「リンクのみ」に差し替える。

```python
# 変更前: 共通FAQ9問をそのまま出力
fixed_html, fixed_pairs = build_fixed_faq_html("fish", fish, fixed_faq_data)

# 変更後: 共通FAQ9問の代わりにリンクブロックを出力
common_faq_link = (
    '<div class="faq-list" style="margin-top:12px">'
    '<p style="font-size:13px;color:var(--sub)">'
    '船釣り初心者向けの共通Q&A（服装・船酔い・予約方法・マナー等）は'
    '<a href="/pages/faq.html">こちらの専用ページ</a>にまとめています。</p></div>'
)
```

JSON-LD の FAQPage も固有 Q のみで構成し、9 問の重複スキーママークアップを削除する。

**faq.html の生成場所**: `design/V2/faq.html` に静的ファイルを作成し、crawler.py の design sync 機構（`config.json design_version` 連動）で `docs/pages/faq.html` に自動コピーさせる。これは既存の about.html・contact.html と同一フロー。

---

## 6. M2: 「今週の概況」3 文テンプレのバリエーション化

### 確定方針

**現状**: `docs/fish/aji.html` 行 291-293 にある概況テキストは「好シーズン中のまずまずの状況。今週は N 件の釣果報告があり、平均 X 匹・最高 Y 匹と〜。平均サイズは Z cm と標準的なサイズ感。安定感はある。」というパターンが全魚種でほぼ同型。`build_index_overview_text()` または `build_fish_pages()` 内の概況テキスト生成関数が対象（crawler.py の概況テキスト生成は `build_index_overview_text` 系と fish ページの overview_text 生成が別関数）。

**fish/*.html の概況テキストは `build_fish_pages()` 内で直接 f-string 生成されている**（L7131 付近の `fish_extra_css` 定義後のセクション）。

**6 パターン文型の定義**（季節×状況で分岐、魚種名と数値は動的埋め込み）:

パターン 1「シーズン最盛期・数釣り好調」: 今週は{N}件と多くの釣果報告が集まり、活性が高い状態が続いています。{area_top}を中心に{max_val}匹超えの実績も出ており、{fish}のシーズンが本格化しています。

パターン 2「シーズン中・平常運転」: {fish}は今週{N}件の釣果報告がありました。釣果レンジは{lo}〜{hi}匹で、潮回りや時合によって差が出やすい時期です。

パターン 3「シーズン序盤・立ち上がり期」: {fish}の釣果報告が増え始めており、今週は{N}件を記録しました。水温の上昇とともに本格的なシーズン到来が期待されます。

パターン 4「シーズン終盤・終了間近」: {fish}は今週{N}件の釣果報告がありましたが、先週比で減少傾向にあります。シーズン終盤に入りつつある状況で、出かけるなら早めが得策です。

パターン 5「閑散期・データ少」: {fish}の釣果報告は今週{N}件と少なめです。本格的なシーズンに向けてデータを注視中です。

パターン 6「大型実績・型狙い期」: 今週は{N}件の釣果報告の中に{max_val}匹超えの好実績が含まれています。型狙いのチャンスで、{area_top}エリアに注目です。

**分岐ロジック**:

- パターン 1: `N >= 30` かつ `wow_ratio >= 1.2`（先週比 +20% 以上）
- パターン 2: `N >= 10` かつ `0.8 <= wow_ratio < 1.2`
- パターン 3: `N >= 5` かつ `wow_ratio >= 1.5`（先週比 +50% 以上・急増）→ P3 が P1 より優先
- パターン 4: `N >= 5` かつ `wow_ratio < 0.7`（先週比 -30% 以下）
- パターン 5: `N < 5`
- パターン 6: `N >= 10` かつ `max_val >= p75 * 2`（最高値が P75 の 2 倍以上）→ P6 は P1/P2 と排他でなく末文として付加

**実装場所**: **主改修対象は `build_comment()` 関数（L5211）**（reviewer 指摘）。現行 `build_comment()` の L5284 に `s2 += f"があり、平均{avg_v:.0f}匹"` 、L5293 に `s2 += f"。平均サイズは{size_v:.0f}cmと"` が残存しており、これは **補遺3 に既に抵触している**。M2 ではこれらの平均値表記を min〜max レンジ表記に置換しつつ、6 パターン分岐を実装する。

`build_fish_pages()` 内には `build_comment()` の呼び出しが存在し、その呼び出し箇所で 6 パターン分岐の引数（season_phase / wow_ratio / N / max_val / area_top）を渡す形で実装する。`wow_ratio` は `this_w` と `last_w`（history.json の weekly データ）から計算可能。`area_top` は既存の `top_area` 変数流用。

**制約遵守**: 「平均 X 匹」「平均サイズ Z cm」表記は出さない（補遺 3）。レンジ（lo〜hi）のみ使用。**現状残存している平均値出力は本 T22 で除去する**。

---

## 7. M3: インライン CSS 200 行を style.css に統合

### 確定方針

**現状の構造**: `crawler.py` L3553 に `V2_COMMON_CSS` 定数（約 200 行）が定義されており、これが全自動生成 HTML の `<head>` 内 `<style>` タグに毎回インラインで出力される。対象ファイルは `docs/index.html`・`docs/fish/*.html`（51 件）・`docs/area/*.html`・`docs/fish_area/*.html`（54 件）・`docs/ship/*.html`（37 件）等、200 件以上。

**移管方針**: `V2_COMMON_CSS` の全内容を `docs/style.css`（`design/V2/style.css` が同期元）に移管し、HTML 側の `<style>{V2_COMMON_CSS}</style>` を `<link rel="stylesheet" href="{depth_prefix}style.css">` に置換する。

**ページ固有 CSS の扱い**: 各ページビルダーには `V2_COMMON_CSS` の他にページ固有の追加 CSS（`index_extra_css`・`fish_extra_css`・`area_extra_css`・`fa_extra_css`）がある。これらは引き続きインライン `<style>` で出力する（ページ種別ごとに異なり、共通化するとセレクタ爆発のリスクがあるため）。

**具体的な変更箇所**（V2_COMMON_CSS が挿入されている全箇所）:

| 箇所 | 現行 | 変更後 |
|---|---|---|
| `_forecast_page_head()` L1954 | `<style>{V2_COMMON_CSS}{...extra}</style>` | `<link rel="stylesheet" href="/style.css">` + `<style>{...extra}</style>` |
| `build_html()` L6507 | `<style>{V2_COMMON_CSS}{index_extra_css}</style>` | `<link rel="stylesheet" href="style.css">` + `<style>{index_extra_css}</style>` |
| `build_fish_pages()` L7189 | `<style>{V2_COMMON_CSS}{fish_extra_css}</style>` | `<link rel="stylesheet" href="../style.css">` + `<style>{fish_extra_css}</style>` |
| `build_fish_pages()` fish/index.html L7266 | `<style>{V2_COMMON_CSS}{fish_index_css}</style>` | `<link rel="stylesheet" href="style.css">` + `<style>{fish_index_css}</style>` |
| `build_area_pages()` L7570 | `<style>{V2_COMMON_CSS}{area_extra_css}...</style>` | `<link rel="stylesheet" href="../style.css">` + `<style>{area_extra_css}...</style>` |
| `build_area_pages()` area/index.html L7925 | 同上 | 同上（`href="style.css"`） |
| `build_area_pages()` area/index.html L8023 | `<style>{V2_COMMON_CSS}{area_index_css}</style>` | `<link rel="stylesheet" href="style.css">` + `<style>{area_index_css}</style>` |
| `build_fish_area_pages()` L8386 | `<style>{V2_COMMON_CSS}{fa_extra_css}...</style>` | `<link rel="stylesheet" href="../style.css">` + `<style>{fa_extra_css}...</style>` |
| `build_calendar_page()` L8502 | `<style>{V2_COMMON_CSS}{cal_extra_css}</style>` | `<link rel="stylesheet" href="style.css">` + `<style>{cal_extra_css}</style>` |
| `build_ship_pages()` | `<style>{V2_COMMON_CSS}{ship_css}</style>` | `<link rel="stylesheet" href="../style.css">` + `<style>{ship_css}</style>` |

**深さ別 href の使い分け**: ルート直下（index.html/calendar.html）は `style.css`、サブディレクトリ（fish/・area/・fish_area/・ship/）は `../style.css`、forecast/ 以下の日次・週次ページは `../style.css`（forecast/area/ 内は `../../style.css`）。

**実装手順の推奨**（reviewer 指摘・二重修正漏れ防止）: 実装時はまず `grep -n 'V2_COMMON_CSS' crawler.py` で全出現箇所を確認（reviewer は 10 箇所と確認済）、文字列パターンを統一した上で一括置換方式で進める。`build_area_pages()` の area/index.html 周辺は L7925 と L8023 の 2 箇所に登場するため特に注意。

**design/V2/style.css の更新**: 現行の `design/V2/style.css` には既に一部スタイルが存在する。`V2_COMMON_CSS` の内容を末尾に追記し、crawler.py の design sync で `docs/style.css` に反映させる。

**リスク**: M3 は CSS の出力先変更という性質上、キャッシュ・HTTP レスポンスの差異でレイアウト崩れを起こしうる唯一の箇所。詳細はリスクセクション参照。

---

## 8. 影響ファイル一覧

| ファイル | 変更内容 | 関数・行 |
|---|---|---|
| `crawler.py` | H1: noindex タグ追加 | `_forecast_page_head()` L1947 付近 |
| `crawler.py` | H1: sitemap から forecast/ 除外 | `build_sitemap()` 内 forecast URL ループ |
| `crawler.py` | H2: 空 ship ページ判定 + noindex | `build_ship_pages()` L10399 付近 |
| `crawler.py` | H2: sitemap から空 ship 除外 | `build_sitemap()` 内 ship URL ループ |
| `crawler.py` | H3: `_build_fa_intro_html()` に area_description 引数追加 | L8077 |
| `crawler.py` | H3: `build_fish_area_pages()` で area_description を渡す | L8222 付近 |
| `crawler.py` | M1: `build_fish_pages()` で共通 FAQ を リンクに差し替え | `build_fish_pages()` 内の fixed_faq 挿入箇所 |
| `crawler.py` | M2: overview_comment 生成を 6 パターン分岐に変更 | `build_fish_pages()` 内 overview 生成箇所 |
| `crawler.py` | M3: V2_COMMON_CSS のインライン出力を link タグ参照に変更 | 上記 10 箇所 |
| `design/V2/style.css` | M3: V2_COMMON_CSS の内容を追記 | 全体 |
| `design/V2/faq.html` | M1: 共通 FAQ ページ新規作成（静的） | 新規 |
| `docs/pages/faq.html` | M1: design sync で自動生成 | 自動コピー |
| `docs/forecast/index.html` 他 | H1: noindex メタタグ付与・sitemap 除外（自動生成） | 自動 |
| `docs/ship/*.html` 該当分 | H2: noindex メタタグ付与・sitemap 除外（自動生成） | 自動 |
| `docs/fish_area/*.html` | H3: intro 先頭 1 文がエリア固有に変化（自動生成） | 自動 |
| `docs/fish/*.html` | M1: 共通 FAQ → リンク化・M2: 概況テキスト多様化 | 自動生成 51 件 |
| `docs/style.css` | M3: V2_COMMON_CSS 内容を受け取る | design sync |

---

## 9. 検証チェックリスト

### 既存 11 不変条件への影響

| 不変条件 | H1 | H2 | H3 | M1 | M2 | M3 |
|---|---|---|---|---|---|---|
| 1: index.html 魚種カード ≥ 5 | 無影響 | 無影響 | 無影響 | 無影響 | 無影響 | 要確認 |
| 2: fish/index.html ≥ 5 種・≥ 20 件 | 無影響 | 無影響 | 無影響 | 無影響 | 無影響 | 要確認 |
| 3: area/index.html ≥ 5 エリア | 無影響 | 無影響 | 無影響 | 無影響 | 無影響 | 要確認 |
| 4: calendar.html 月別カード ≥ 12 | 無影響 | 無影響 | 無影響 | 無影響 | 無影響 | 要確認 |
| 5: 当月 CSV 最新日付 today-2 以内 | 無影響 | 無影響 | 無影響 | 無影響 | 無影響 | 無影響 |
| 6: catches_raw.json ≥ 50,000 件 | 無影響 | 無影響 | 無影響 | 無影響 | 無影響 | 無影響 |
| 7: area/*.html 旬カレンダー空セル < 50% | 無影響 | 無影響 | 無影響 | 無影響 | 無影響 | 要確認 |
| 8: area/*.html fia-grid card あり | 無影響 | 無影響 | 無影響 | 無影響 | 無影響 | 要確認 |
| 9: fish/*.html 7 日チャート 6 本以上 | 無影響 | 無影響 | 無影響 | 無影響 | 無影響 | 要確認 |
| 10: fish/*.html HERO 統一 | 無影響 | 無影響 | 無影響 | 無影響 | 無影響 | 要確認 |
| 11: 全 docs/*/*.html ネストアンカーなし | 無影響 | 無影響 | 無影響 | 要確認 | 無影響 | 無影響 |
| 12: area/*.html 海況セクション潮汐・月相名称 | 無影響 | 無影響 | 無影響 | 無影響 | 無影響 | 要確認 |

M3 は全 HTML の `<head>` 構造を変更するため、全不変条件をローカル実行で確認必須。

### 追加を推奨する不変条件（T22 完了後に validate_output.py に追加）

**追加不変条件 T22-a**: `docs/forecast/index.html` に `noindex` タグが存在すること（H1 暫定対応の維持確認）

**追加不変条件 T22-b**: `docs/pages/faq.html` が存在し、本文 ≥ 800 字であること（M1）

**追加不変条件 T22-c**: `docs/fish/*.html` から共通 FAQ 9 問の固定文言（例: `船酔い防止`・`ライフジャケット`・`服装の目安`等、`normalize/fixed_faq.json` の共通質問本文）が消えていること（M1 リンク化の検証・reviewer 指摘で定義修正）

**追加不変条件 T22-d**: `docs/style.css` が `:root` CSS 変数ブロックを含むこと（M3 の style.css 統合が壊れていないことを確認）

### AdSense 観点の追加検証

- `forecast/index.html`: noindex メタタグの存在確認・sitemap.xml に forecast/ URL が含まれないこと
- `ship/*.html`: noindex 対象ページが sitemap.xml に含まれないこと（grep で確認）
- `fish_area/*.html`: 全 54 件で intro テキスト先頭にエリア名固有の地理情報が含まれること（抽出判定は省略可・目視サンプル 5 件）
- `fish/*.html`: 共通 FAQ 9 問テキストが消えて `pages/faq.html` へのリンクが存在すること
- `docs/style.css`: `V2_COMMON_CSS` の全変数定義（`--bg`・`--accent` 等）が含まれること

---

## 10. 実装順序の推奨

**原則**: regression リスクの低いものから着手し、M3 を最後にする。

| 順序 | ID | 作業 | リスク | 前提 |
|---|---|---|---|---|
| 1 | H1 | forecast/ noindex + sitemap 除外 | 低 | なし |
| 2 | H2 | 空 ship/ noindex + sitemap 除外 | 低 | なし |
| 3 | M1 | faq.html 新設 + fish ページ共通 FAQ リンク化 | 中（ネストアンカー確認） | faq.html 手書き完成後 |
| 4 | H3 | fish_area intro にエリア固有 1 文追加 | 低 | なし |
| 5 | M2 | 概況テキスト 6 パターン化 | 低 | なし |
| 6 | M3 | V2_COMMON_CSS → style.css 統合 | 高 | H1〜M2 完了後・単独コミット必須 |

H1 と H2 は独立しており並行作業可能だが、コミットは別々にすること（regression 原因の切り分けのため）。M3 は他の変更と絶対に同一コミットにしない。

---

## 11. リスク

### M3 の CSS 統合リスク（最重要）

`V2_COMMON_CSS` をインラインから外部ファイル参照に変更する場合、以下のリスクが存在する。

**リスク 1: link タグの href パス誤り**。サブディレクトリの深さを誤ると CSS が 404 になり全ページのレイアウトが崩壊する。forecast/area/ 配下は `../../style.css`、forecast/ 直下は `../style.css` と異なる。ビルダー関数ごとに depth 変数を確認する必要がある。

**リスク 2: design/V2/style.css の上書き**。現行の `design/V2/style.css` には既存スタイルが存在する可能性がある。`V2_COMMON_CSS` を追記する際、既存定義との重複・衝突を確認しないと CSS カスケードが意図しない挙動になる。事前に `docs/style.css` の現在の内容を確認してから統合すること。

**リスク 3: GitHub Pages のキャッシュ**。インラインから外部ファイルへの移行直後、CDN キャッシュが旧インライン CSS を持つページと新 link タグのページが混在する可能性がある。軽微で自然解消するが、再申請直後のクロールで発生すると評価に影響する。対策として M3 は H1〜M2 の再申請結果を見てから別タイミングで実施することも選択肢とする。

**リスク 4: validate_output.py の全条件再確認**。M3 後の `python crawl/validate_output.py` で errors=0 を必ず確認すること。CSS が外部化されてもコンテンツの DOM 構造は変わらないため、不変条件の判定ロジック自体への影響はないが、念のため全 12 条件を通過させる。

### M1 のネストアンカーリスク

共通 FAQ を削除した後に追加する「共通 FAQ はこちら」リンクが、既存の `faq-list` ブロック内 `<details>` 内に入ると、`<a>` 内 `<a>` のネスト（不変条件 11）が発生しうる。リンクブロックは `faq-list` の外部に独立した `<p>` として配置すること。

### H3 の area_description.json 未登録エリアのリスク

`area_description.json` に登録のないエリア名が `fish_area` ページに存在する場合、`area_intro` が空文字になり既存の数値ベース説明文のみになる（劣化なし）。`area_description` が `None` の場合のガードは既存コードパターン（T6 の `build_area_faq_html` バグ修正と同様）で対処する。
