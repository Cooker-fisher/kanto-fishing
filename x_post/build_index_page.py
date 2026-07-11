# build_index_page.py — docs/x_post/index.html 生成
# 上部: 最新日の釣果速報コンテンツをそのまま表示
# 下部: 直近30日アーカイブリスト
# canonical: /x_post/{最新日付}.html（duplicate content 回避）

import os
import re


# GA + AdSense ローダー（head 用）と広告ユニット（body 用）。
# f-string 内の brace 衝突を避けるためモジュール定数として保持する。
_ANALYTICS_HEAD = (
    '<script async src="https://www.googletagmanager.com/gtag/js?id=G-LS469BTBBX"></script>'
    '<script>window.dataLayer=window.dataLayer||[];function gtag(){dataLayer.push(arguments);}'
    'gtag("js",new Date());gtag("config","G-LS469BTBBX");</script>'
    '<script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js'
    '?client=ca-pub-7406401300491553" crossorigin="anonymous"></script>'
)
_AD_UNIT = (
    '<ins class="adsbygoogle" style="display:block;min-height:0;height:auto" '
    'data-ad-client="ca-pub-7406401300491553" data-ad-slot="auto" data-ad-format="auto" '
    'data-full-width-responsive="true"></ins>'
    '<script>(adsbygoogle=window.adsbygoogle||[]).push({});</script>'
)


# ── CSS 追加（アーカイブセクション用） ──
_ARCHIVE_CSS = """
.archive-section {
  margin-top: 40px;
  padding-top: 28px;
  border-top: 2px solid var(--border);
}
.archive-section h2 {
  font-size: 16px;
  font-weight: 800;
  color: var(--accent);
  margin-bottom: 14px;
}
.archive-list {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 10px;
}
.archive-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 14px;
  background: var(--bg-alt);
  border: 1px solid var(--border);
  border-radius: 8px;
  text-decoration: none;
  color: var(--text);
  transition: border-color .15s;
}
.archive-item:hover { border-color: var(--port); }
.archive-item .ai-date { font-size: 13px; font-weight: 800; color: var(--port); min-width: 76px; }
.archive-item .ai-meta { font-size: 12px; color: var(--sub); }
.archive-item .ai-meta b { color: var(--accent); }
"""

# 曜日ラベル
_WEEKDAYS = ["月", "火", "水", "木", "金", "土", "日"]


def _date_label(date_iso: str) -> str:
    """YYYY-MM-DD → M/D(曜)"""
    try:
        from datetime import date as _date
        d = _date.fromisoformat(date_iso)
        return f"{d.month}/{d.day}({_WEEKDAYS[d.weekday()]})"
    except Exception:
        return date_iso


def _find_existing_dates(docs_x_post_dir: str) -> list[str]:
    """docs/x_post/ から YYYY-MM-DD.html のファイルを探し、日付を降順で返す"""
    dates = []
    if not os.path.isdir(docs_x_post_dir):
        return dates
    for fname in os.listdir(docs_x_post_dir):
        m = re.match(r"^(\d{4}-\d{2}-\d{2})\.html$", fname)
        if m:
            dates.append(m.group(1))
    dates.sort(reverse=True)
    return dates


def _extract_page_meta(html_path: str) -> dict:
    """既存の YYYY-MM-DD.html から簡易メタ情報を抽出"""
    meta = {"n_ships": 0, "n_records": 0, "top_fish": ""}
    try:
        with open(html_path, encoding="utf-8") as f:
            content = f.read()
        # 船宿数: <b>XX</b>船宿出船
        m = re.search(r"<b>(\d+)</b>船宿出船", content)
        if m:
            meta["n_ships"] = int(m.group(1))
        # 件数: <b>XX</b>件の釣果報告
        m = re.search(r"<b>(\d+)</b>件の釣果報告", content)
        if m:
            meta["n_records"] = int(m.group(1))
        # 大物魚種: <div class="label">大物記録</div>\s*<div class="target">(.+?)</div>
        m = re.search(r'class="label">大物記録</div>\s*<div class="target">([^<]+)</div>', content)
        if m:
            meta["top_fish"] = m.group(1).strip()
        else:
            # 数の好調
            m = re.search(r'class="label">数の好調</div>\s*<div class="target">([^<]+)</div>', content)
            if m:
                meta["top_fish"] = m.group(1).strip()
    except Exception:
        pass
    return meta


def _extract_body_content(html_path: str) -> str:
    """YYYY-MM-DD.html の <body> 内から main コンテンツ部分を抽出する。
    <header class="gnav">...</header> と <footer> は除いて、
    <body> 内の残り全部を返す（ネスト div の正しい処理）。"""
    try:
        with open(html_path, encoding="utf-8") as f:
            content = f.read()
        body_m = re.search(r"<body>(.*?)</body>", content, re.DOTALL)
        if body_m:
            body = body_m.group(1)
            body = re.sub(r"<header class=\"gnav\">.*?</header>", "", body, flags=re.DOTALL)
            body = re.sub(r"<header>\s*<div class=\"inner\">.*?</header>\s*<nav class=\"gnav\">.*?</nav>", "", body, flags=re.DOTALL)
            body = re.sub(r"<footer>.*?</footer>", "", body, flags=re.DOTALL)
            return body.strip()
    except Exception:
        pass
    return ""


def build_index(output_path: str, docs_x_post_dir: str | None = None) -> None:
    """
    docs/x_post/index.html を生成。

    output_path: 保存先（例: docs/x_post/index.html）
    docs_x_post_dir: 日付ページが格納されるディレクトリ（None の場合は output_path と同ディレクトリ）
    """
    if docs_x_post_dir is None:
        docs_x_post_dir = os.path.dirname(output_path)

    dates = _find_existing_dates(docs_x_post_dir)
    latest_date = dates[0] if dates else None

    # ── 最新日のコンテンツを抽出 ──
    latest_body = ""
    latest_label = ""
    canonical_url = "https://funatsuri-yoso.com/x_post/index.html"
    if latest_date:
        latest_html_path = os.path.join(docs_x_post_dir, f"{latest_date}.html")
        latest_body = _extract_body_content(latest_html_path)
        latest_label = _date_label(latest_date)
        canonical_url = f"https://funatsuri-yoso.com/x_post/{latest_date}.html"

    # ── アーカイブリスト（直近30日） ──
    archive_items = []
    for d in dates[:30]:
        d_label = _date_label(d)
        html_path = os.path.join(docs_x_post_dir, f"{d}.html")
        meta = _extract_page_meta(html_path)
        meta_text_parts = []
        if meta["n_ships"]:
            meta_text_parts.append(f"<b>{meta['n_ships']}</b>船宿")
        if meta["n_records"]:
            meta_text_parts.append(f"<b>{meta['n_records']}</b>件")
        if meta["top_fish"]:
            meta_text_parts.append(meta["top_fish"])
        meta_text = " · ".join(meta_text_parts) if meta_text_parts else "—"
        archive_items.append(
            f'<a class="archive-item" href="/x_post/{d}.html">'
            f'<span class="ai-date">{d_label}</span>'
            f'<span class="ai-meta">{meta_text}</span>'
            f"</a>"
        )
    archive_html = "\n".join(archive_items) if archive_items else "<p>まだ釣果速報はありません。</p>"

    # ── タイトル ──
    # SEO (2026/07/12): 「関東」「船釣り」を title に含め検索キーワードと一致させる
    page_title = "関東 船釣り釣果速報"
    if latest_label:
        page_title = f"関東 船釣り釣果速報｜最新: {latest_label}"

    html = f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
{_ANALYTICS_HEAD}
<title>{page_title}｜船釣り予想</title>
<meta name="description" content="関東5県（神奈川・東京・千葉・茨城・静岡）の船釣り釣果速報。今日釣れた魚と船宿を毎日まとめ・30日アーカイブ。">
<link rel="canonical" href="{canonical_url}">
<meta property="og:title" content="{page_title}｜船釣り予想">
<meta property="og:description" content="関東5県の船釣り釣果速報。毎日の釣果まとめと30日アーカイブ。">
<meta property="og:type" content="website">
<meta property="og:url" content="{canonical_url}">
<meta property="og:image" content="{('https://funatsuri-yoso.com/x_post/' + latest_date + '.png') if latest_date else 'https://funatsuri-yoso.com/ogp-default.png'}">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:site" content="@funatsuri_yoso">
<meta name="twitter:image" content="{('https://funatsuri-yoso.com/x_post/' + latest_date + '.png') if latest_date else 'https://funatsuri-yoso.com/ogp-default.png'}">
<script type="application/ld+json">{{"@context":"https://schema.org","@type":"BreadcrumbList","itemListElement":[{{"@type":"ListItem","position":1,"name":"トップ","item":"https://funatsuri-yoso.com/"}},{{"@type":"ListItem","position":2,"name":"釣果速報","item":"https://funatsuri-yoso.com/x_post/index.html"}}]}}</script>
<script type="application/ld+json">{{"@context":"https://schema.org","@type":"CollectionPage","name":"{page_title}","description":"関東5県の船釣り釣果速報。毎日の釣果まとめと30日アーカイブ。","url":"{canonical_url}","isPartOf":{{"@type":"WebSite","name":"船釣り予想","url":"https://funatsuri-yoso.com/"}}}}</script>
</head>
<body>

<header>
  <div class="inner">
    <a href="/" class="site-logo"><span class="brand">船釣り<span>予想</span></span></a>
    <span class="domain">funatsuri-yoso.com</span>
  </div>
</header>
<nav class="gnav">
  <a href="/">今日の釣果</a>
  <a href="/x_post/" class="on">釣果速報</a>
  <a href="/fish/">魚種</a>
  <a href="/area/">エリア</a>
  <a href="/calendar.html">カレンダー</a>
</nav>

{latest_body}

<div class="wrap">
  <section class="archive-section">
    <h2>過去の釣果速報</h2>
    <div class="archive-list">
{archive_html}
    </div>
  </section>
</div>

<div style="margin:24px 0;text-align:center">{_AD_UNIT}</div>
<footer>
  &copy; 2026 船釣り予想 | funatsuri-yoso.com — データ集計・出典: 本サイト独自集計
  <div style="margin-top:8px;line-height:1.9">
    <a href="/pages/about.html" style="color:#cfe8f5;text-decoration:underline">サイトについて</a> ·
    <a href="/pages/privacy.html" style="color:#cfe8f5;text-decoration:underline">プライバシーポリシー</a> ·
    <a href="/pages/terms.html" style="color:#cfe8f5;text-decoration:underline">利用規約</a> ·
    <a href="/pages/contact.html" style="color:#cfe8f5;text-decoration:underline">お問い合わせ</a> ·
    <a href="/pages/faq.html" style="color:#cfe8f5;text-decoration:underline">よくある質問</a>
  </div>
</footer>

</body>
</html>"""

    # CSS を <head> に注入（build_daily_page.py の _PAGE_CSS + _ARCHIVE_CSS）
    from x_post.build_daily_page import _PAGE_CSS as _daily_css
    full_css = _daily_css + _ARCHIVE_CSS
    html = html.replace("</head>", f"<style>{full_css}</style>\n</head>", 1)

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[build_index_page] HTML 保存: {output_path}")
