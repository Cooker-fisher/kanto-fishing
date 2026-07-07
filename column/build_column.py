# -*- coding: utf-8 -*-
"""/column/ コラム記事ジェネレータ（独立運用・fish-value/komase-sim と同型）

column/articles/*.md（frontmatter + Markdown）を読み、サイト共通の chrome
（ヘッダ/gnav/フッタ/bnナビ/GA/AdSense/favicon/OGP/Article JSON-LD）で包んで
docs/column/{slug}.html と docs/column/index.html を生成する。

方針（AdSense フェーズ2・E-E-A-T）:
  - 記事は「AI下書き → 運営者が確認・加筆 → 運営者名義（釣り予想管理人）で公開」。
    about.html の人手キュレーション宣言と整合。自動生成テンプレとは別カテゴリ。
  - このサイトの3年12万件データからしか書けない独自コンテンツ（＝"有用性の低い"の対極）。

crawler.py は触らない（gnav リンク・sitemap 収録は別途）。標準ライブラリのみ。
使い方: python column/build_column.py
"""
import os, re, html, glob

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = os.path.join(ROOT, "docs")
ART_DIR = os.path.join(ROOT, "column", "articles")
OUT_DIR = os.path.join(DOCS, "column")
SITE = "https://funatsuri-yoso.com"
AUTHOR = "釣り予想管理人"

GA = ('<script async src="https://www.googletagmanager.com/gtag/js?id=G-LS469BTBBX"></script>'
      '<script>window.dataLayer=window.dataLayer||[];function gtag(){dataLayer.push(arguments);}'
      'gtag("js",new Date());gtag("config","G-LS469BTBBX");</script>')
ADSENSE = ('<script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js'
           '?client=ca-pub-7406401300491553" crossorigin="anonymous"></script>')
FAVICON = ('<link rel="icon" href="/favicon.ico" sizes="48x48">'
           '<link rel="apple-touch-icon" href="/apple-touch-icon.png">')

STYLE = """
:root{--bg:#f5f7fa;--card:#fff;--border:#d0d8e0;--text:#1a2332;--sub:#5a6a7a;--muted:#8a96a4;--accent:#0d2b4a;--cta:#e85d04;--nav:#f0f3f7;--r:10px;--mx:760px}
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
body{font-family:system-ui,-apple-system,"Hiragino Sans",sans-serif;background:var(--bg);color:var(--text);line-height:1.85;padding-bottom:64px}
a{color:var(--cta);text-decoration:none}a:hover{text-decoration:underline}
header{background:var(--accent);color:#fff;padding:12px 20px;border-bottom:3px solid var(--cta)}
header .inner{max-width:var(--mx);margin:0 auto;display:flex;justify-content:space-between;align-items:center}
header .site-logo{color:#fff}header .brand{font-size:18px;font-weight:700}header .brand span{color:var(--cta)}
.domain{font-size:11px;opacity:.5}
nav.gnav{background:var(--nav);padding:7px 20px;display:flex;gap:6px;flex-wrap:wrap;justify-content:center;border-bottom:1px solid var(--border)}
nav.gnav a{color:var(--sub);font-size:12px;font-weight:600;padding:5px 12px;border-radius:16px}
nav.gnav a:hover,nav.gnav a.on{background:var(--accent);color:#fff}
.nav-new{font-size:9px;background:var(--cta);color:#fff;border-radius:6px;padding:1px 4px;margin-left:3px;vertical-align:top}
.wrap{max-width:var(--mx);margin:0 auto;padding:22px 16px 40px}
.bread{font-size:12px;color:var(--muted);margin-bottom:14px}.bread a{color:var(--sub)}
article h1{font-size:25px;font-weight:800;color:var(--accent);line-height:1.45;margin-bottom:14px}
.byline{font-size:12.5px;color:var(--muted);border-bottom:1px solid var(--border);padding-bottom:14px;margin-bottom:22px}
.byline b{color:var(--sub)}
article h2{font-size:18px;font-weight:800;color:var(--accent);margin:30px 0 12px;padding-left:11px;border-left:4px solid var(--cta)}
article h3{font-size:15px;font-weight:700;color:var(--accent);margin:22px 0 8px}
article p{font-size:15px;margin-bottom:15px}
article ul,article ol{font-size:15px;margin:6px 0 16px 22px}article li{margin-bottom:6px}
article strong{color:var(--accent)}
article em{font-style:normal;color:var(--muted);font-size:13px}
.tbl-wrap{overflow-x:auto;margin:14px 0 20px}
table{border-collapse:collapse;width:100%;font-size:13.5px;min-width:340px}
th,td{border:1px solid var(--border);padding:7px 10px;text-align:left}
th{background:var(--accent);color:#fff;font-weight:600}
tr:nth-child(even) td{background:#f5f7fa}
.note{background:var(--nav);border:1px solid var(--border);border-radius:var(--r);padding:13px 15px;font-size:12.5px;color:var(--sub);margin:22px 0}
.note h3{font-size:13px;margin:0 0 6px}
.ad-slot{margin:22px 0;text-align:center;min-height:1px}
.share-bar{display:flex;gap:8px;align-items:center;margin:24px 0 6px;font-size:12px;color:var(--muted)}
.share-bar a{display:inline-flex;align-items:center;gap:5px;background:var(--card);border:1px solid var(--border);border-radius:16px;padding:5px 12px;font-size:12px;font-weight:600;color:var(--sub)}
.col-related{margin-top:26px;border-top:1px solid var(--border);padding-top:16px}
.col-related h2{font-size:14px;border:none;padding:0;margin:0 0 8px}
.col-related a{display:inline-block;background:var(--card);border:1px solid var(--border);border-radius:16px;padding:5px 12px;font-size:12px;margin:0 5px 6px 0;color:var(--sub)}
.card-list{display:grid;grid-template-columns:1fr;gap:14px;margin-top:6px}
.col-card{background:var(--card);border:1px solid var(--border);border-radius:var(--r);padding:16px 18px}
.col-card .d{font-size:11px;color:var(--muted)}
.col-card h2{font-size:17px;color:var(--accent);margin:5px 0 7px;border:none;padding:0}
.col-card p{font-size:13px;color:var(--sub);margin:0}
.col-card .tags{margin-top:9px}.col-card .tags span{font-size:10.5px;background:var(--nav);color:var(--sub);border-radius:5px;padding:2px 7px;margin-right:5px}
footer{background:var(--accent);color:rgba(255,255,255,.6);padding:22px 14px;text-align:center;font-size:11px;margin-top:30px}
footer a{color:rgba(255,255,255,.8)}.fl{margin-top:8px;display:flex;gap:10px;justify-content:center;flex-wrap:wrap}
.bn{position:fixed;bottom:0;left:0;right:0;background:var(--card);border-top:1px solid var(--border);display:flex;z-index:100;box-shadow:0 -2px 8px rgba(0,0,0,.06)}
.bn a{flex:1;text-align:center;padding:8px 0 6px;font-size:10px;color:var(--muted);display:flex;flex-direction:column;align-items:center;gap:2px;font-weight:600}
.bn a svg{width:22px;height:22px;stroke:var(--muted);stroke-width:1.8;fill:none;stroke-linecap:round;stroke-linejoin:round}
.bn a.on{color:var(--cta)}.bn a.on svg{stroke:var(--cta)}
@media(min-width:769px){.bn{display:none}body{padding-bottom:0}}
@media(max-width:600px){article h1{font-size:21px}}
"""

GNAV = ('<nav class="gnav">'
        '<a href="/">今日の釣果</a><a href="/x_post/">釣果速報</a>'
        '<a href="/fish/">魚種</a><a href="/area/">エリア</a>'
        '<a href="/calendar.html">カレンダー</a><a href="/monthly/">月報</a>'
        '<a href="/column/" class="on">📖 コラム</a>'
        '<a href="/komase-sim/">🎣 コマセsim</a>'
        '<a href="/fish-value/">💰 釣果価値</a>'
        '</nav>')
HEADER = ('<header><div class="inner">'
          '<a href="/" class="site-logo"><span class="brand">船釣り<span>予想</span></span></a>'
          '<span class="domain">funatsuri-yoso.com</span></div></header>' + GNAV)
FOOTER = ('<footer><div>© 2026 船釣り予想 (funatsuri-yoso.com)</div><div class="fl">'
          '<a href="/pages/about.html">サイトについて</a>'
          '<a href="/pages/privacy.html">プライバシーポリシー</a>'
          '<a href="/pages/terms.html">利用規約</a>'
          '<a href="/pages/contact.html">お問い合わせ</a>'
          '<a href="/pages/faq.html">よくある質問</a></div></footer>')
def _bn(active):
    def a(k,href,svg,label):
        on=' class="on"' if k==active else ''
        return f'<a href="{href}"{on}>{svg}<span>{label}</span></a>'
    s_catch='<svg viewBox="0 0 24 24"><path d="M2 12c3-5 8-7 13-5 2 1 4 3 5 5-1 2-3 4-5 5-5 2-10 0-13-5z"/><circle cx="16" cy="11" r=".8" fill="currentColor" stroke="none"/><path d="M20 12l2-2M20 12l2 2"/></svg>'
    s_fish='<svg viewBox="0 0 24 24"><line x1="4" y1="7" x2="20" y2="7"/><line x1="4" y1="12" x2="20" y2="12"/><line x1="4" y1="17" x2="20" y2="17"/></svg>'
    s_area='<svg viewBox="0 0 24 24"><path d="M12 2c-4 0-7 3-7 7 0 5 7 13 7 13s7-8 7-13c0-4-3-7-7-7z"/><circle cx="12" cy="9" r="2.5"/></svg>'
    s_col='<svg viewBox="0 0 24 24"><path d="M4 5h16v14H4z"/><line x1="8" y1="9" x2="16" y2="9"/><line x1="8" y1="13" x2="16" y2="13"/></svg>'
    s_cal='<svg viewBox="0 0 24 24"><rect x="4" y="5" width="16" height="16" rx="2"/><line x1="4" y1="10" x2="20" y2="10"/></svg>'
    return ('<nav class="bn">'
            + a('index','/',s_catch,'釣果') + a('fish','/fish/',s_fish,'魚種')
            + a('column','/column/',s_col,'コラム') + a('area','/area/',s_area,'エリア')
            + a('cal','/calendar.html',s_cal,'カレンダー') + '</nav>')

# ── frontmatter + Markdown パーサ（使用サブセットのみ・標準ライブラリ） ──
def parse_front(text):
    meta = {}
    if text.startswith("---"):
        end = text.find("\n---", 3)
        block = text[3:end].strip()
        body = text[end+4:].lstrip("\n")
        for line in block.splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                meta[k.strip()] = v.strip()
        return meta, body
    return meta, text

def _inline(s):
    s = html.escape(s, quote=False)
    s = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<a href="\2">\1</a>', s)
    s = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', s)
    s = re.sub(r'(?<!\*)\*([^*]+)\*(?!\*)', r'<em>\1</em>', s)
    return s

def md_to_html(md):
    lines = md.split("\n")
    out = []; i = 0
    while i < len(lines):
        ln = lines[i]
        if not ln.strip():
            i += 1; continue
        # table
        if ln.lstrip().startswith("|") and i+1 < len(lines) and set(lines[i+1].replace("|","").replace(":","").strip()) <= {"-"," "}:
            header = [c.strip() for c in ln.strip().strip("|").split("|")]
            i += 2; rows = []
            while i < len(lines) and lines[i].lstrip().startswith("|"):
                rows.append([c.strip() for c in lines[i].strip().strip("|").split("|")]); i += 1
            t = '<div class="tbl-wrap"><table><thead><tr>' + "".join(f"<th>{_inline(h)}</th>" for h in header) + "</tr></thead><tbody>"
            for r in rows:
                t += "<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in r) + "</tr>"
            out.append(t + "</tbody></table></div>"); continue
        if ln.startswith("### "):
            out.append(f"<h3>{_inline(ln[4:])}</h3>"); i += 1; continue
        if ln.startswith("## "):
            out.append(f"<h2>{_inline(ln[3:])}</h2>"); i += 1; continue
        if ln.startswith("# "):
            i += 1; continue  # H1 は frontmatter title を使う
        if ln.lstrip().startswith(("- ", "* ")):
            items = []
            while i < len(lines) and lines[i].lstrip().startswith(("- ", "* ")):
                items.append(f"<li>{_inline(lines[i].lstrip()[2:])}</li>"); i += 1
            out.append("<ul>" + "".join(items) + "</ul>"); continue
        # paragraph (gather until blank)
        para = [ln]; i += 1
        while i < len(lines) and lines[i].strip() and not lines[i].lstrip().startswith(("#","- ","* ","|")):
            para.append(lines[i]); i += 1
        out.append(f"<p>{_inline(' '.join(para))}</p>")
    return "\n".join(out)

def _head(title, desc, canonical, og_image=None):
    ttl = html.escape(title); d = html.escape(desc)
    ogimg = og_image or f"{SITE}/ogp-default.png"
    return (f'<!DOCTYPE html><html lang="ja"><head><meta charset="UTF-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1">{FAVICON}'
            f'<title>{ttl} | 船釣り予想</title>'
            f'<meta name="description" content="{d}">'
            f'<link rel="canonical" href="{canonical}">'
            f'<meta property="og:title" content="{ttl}"><meta property="og:description" content="{d}">'
            f'<meta property="og:url" content="{canonical}"><meta property="og:type" content="article">'
            f'<meta property="og:site_name" content="船釣り予想"><meta property="og:image" content="{ogimg}">'
            f'<meta name="twitter:card" content="summary_large_image"><meta name="twitter:site" content="@funatsuri_yoso">'
            f'<meta name="twitter:title" content="{ttl}"><meta name="twitter:image" content="{ogimg}">'
            f'{GA}{ADSENSE}<style>{STYLE}</style></head><body>')

def _share(url, title):
    u = html.escape(url); t = html.escape(title)
    x = f"https://twitter.com/intent/tweet?text={t}&url={u}"
    return (f'<div class="share-bar"><span>シェア:</span>'
            f'<a href="{x}" target="_blank" rel="noopener">𝕏 でポスト</a></div>')

def build_article(meta, body_html):
    slug = meta["slug"]; title = meta["title"]; date = meta.get("date","")
    desc = meta.get("description","")
    tags = [t.strip() for t in meta.get("tags","").split(",") if t.strip()]
    url = f"{SITE}/column/{slug}.html"
    jsonld = (
        '<script type="application/ld+json">{"@context":"https://schema.org","@type":"Article",'
        f'"headline":{_json(title)},"datePublished":"{date}","dateModified":"{date}",'
        f'"author":{{"@type":"Person","name":{_json(AUTHOR)}}},'
        f'"publisher":{{"@type":"Organization","name":"船釣り予想","url":"{SITE}"}},'
        f'"mainEntityOfPage":{_json(url)},"description":{_json(desc)}}}</script>'
        '<script type="application/ld+json">{"@context":"https://schema.org","@type":"BreadcrumbList",'
        '"itemListElement":[{"@type":"ListItem","position":1,"name":"トップ","item":"' + SITE + '/"},'
        '{"@type":"ListItem","position":2,"name":"コラム","item":"' + SITE + '/column/"},'
        f'{{"@type":"ListItem","position":3,"name":{_json(title)},"item":{_json(url)}}}]}}</script>'
    )
    related = ('<div class="col-related"><h2>関連ページ</h2>'
               '<a href="/">今日の釣果</a><a href="/fish/">魚種別ページ</a>'
               '<a href="/area/">エリア別ページ</a><a href="/calendar.html">釣りものカレンダー</a>'
               '<a href="/column/">コラム一覧</a></div>')
    tag_html = ""
    head = _head(title, desc, url, meta.get("og_image")).replace("</head>", jsonld + "</head>")
    parts = [head]
    parts.append(HEADER)
    parts.append('<div class="wrap"><div class="bread"><a href="/">トップ</a> › <a href="/column/">コラム</a> › ' + html.escape(title) + '</div>')
    parts.append("<article>")
    parts.append(f"<h1>{html.escape(title)}</h1>")
    byd = f"{date}" if date else ""
    parts.append(f'<div class="byline">文・データ集計: <b>{AUTHOR}</b>{" ・ " + byd if byd else ""}</div>')
    parts.append(body_html)
    parts.append(_share(url, title))
    parts.append(related)
    parts.append("</article></div>")
    parts.append(FOOTER)
    parts.append(_bn("column"))
    parts.append("</body></html>")
    return "".join(parts)

def _json(s):
    import json as _j
    return _j.dumps(s, ensure_ascii=False)

def build_index(articles):
    url = f"{SITE}/column/"
    desc = "関東・静岡の船釣り釣果 約12万件のデータから、旬・海況・エリアの傾向を読み解くコラム。運営者が自ら集計・分析して書いています。"
    parts = [_head("船釣りデータコラム", desc, url)]
    parts.append(HEADER)
    parts.append('<div class="wrap"><div class="bread"><a href="/">トップ</a> › コラム</div>')
    parts.append('<article><h1>船釣りデータコラム</h1>'
                 '<div class="byline">関東・静岡の船宿釣果 約12万件（2023〜）を、運営者 <b>' + AUTHOR + '</b> が自ら集計・分析して書いています。</div></article>')
    parts.append('<div class="card-list">')
    for meta in articles:
        slug=meta["slug"]; tags=[t.strip() for t in meta.get("tags","").split(",") if t.strip()]
        parts.append(
            f'<a class="col-card" href="/column/{slug}.html" style="display:block">'
            f'<div class="d">{html.escape(meta.get("date",""))}</div>'
            f'<h2>{html.escape(meta["title"])}</h2>'
            f'<p>{html.escape(meta.get("description",""))}</p>'
            f'<div class="tags">' + "".join(f"<span>{html.escape(t)}</span>" for t in tags) + '</div></a>')
    parts.append('</div>')
    parts.append(FOOTER)
    parts.append(_bn("column"))
    parts.append("</body></html>")
    return "".join(parts)

def inject_sitemap(slugs):
    """docs/sitemap.xml に /column/ と各記事 URL を注入（既存の column エントリは置換）。"""
    sm_path = os.path.join(DOCS, "sitemap.xml")
    if not os.path.isfile(sm_path):
        return 0
    sm = open(sm_path, encoding="utf-8").read()
    sm = re.sub(r'\s*<url>\s*<loc>' + re.escape(SITE) + r'/column/[^<]*</loc>.*?</url>', '', sm, flags=re.S)
    entries = [f'<url><loc>{SITE}/column/</loc><changefreq>weekly</changefreq><priority>0.7</priority></url>']
    for s in slugs:
        entries.append(f'<url><loc>{SITE}/column/{s}.html</loc><changefreq>monthly</changefreq><priority>0.6</priority></url>')
    sm = sm.replace("</urlset>", "\n" + "\n".join(entries) + "\n</urlset>")
    open(sm_path, "w", encoding="utf-8").write(sm)
    return len(slugs) + 1

def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    files = sorted(glob.glob(os.path.join(ART_DIR, "*.md")))
    metas = []
    for f in files:
        raw = open(f, encoding="utf-8").read()
        meta, body = parse_front(raw)
        if "slug" not in meta or "title" not in meta:
            print(f"  SKIP (frontmatter不足): {f}"); continue
        body_html = md_to_html(body)
        out = build_article(meta, body_html)
        open(os.path.join(OUT_DIR, meta["slug"] + ".html"), "w", encoding="utf-8").write(out)
        metas.append(meta)
        print(f"  記事生成: /column/{meta['slug']}.html （{len(body_html)}字HTML）")
    metas.sort(key=lambda m: m.get("date",""), reverse=True)
    open(os.path.join(OUT_DIR, "index.html"), "w", encoding="utf-8").write(build_index(metas))
    print(f"  index生成: /column/ （{len(metas)}記事）")
    n = inject_sitemap([m["slug"] for m in metas])
    print(f"  sitemap注入: {n} URL")

if __name__ == "__main__":
    main()
