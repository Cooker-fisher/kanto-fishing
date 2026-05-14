"""
HTML / CSV 出力の整合性を検証する gatekeeper スクリプト。
crawler.py 実行後に CI で実行し、不変条件違反があれば非0終了して push を阻止する。

検証する不変条件（過去に発生した regression を全てカバー）:

  1. docs/index.html
     - 魚種カード（class="fc"）が 5枚以上
     - HERO カウント > 0

  2. docs/fish/index.html
     - 「今週釣果あり N種」が 5以上 OR
     - 「今週釣れている魚種 N種」かつ N >= 30 OR
     - 「今週釣果X件」のうち X>0 が 5件以上

  3. docs/area/index.html
     - 「今週釣果あり Nエリア」が 5以上
     - ai-card エレメントが 10以上

  4. docs/calendar.html
     - 「月別」セクションが存在（mc-card クラス）

  5. data/V2/YYYY-MM.csv
     - 当月CSVの最新日付が today-2日以内（ただし当月切替直後の3日間は緩和）

  6. catches_raw.json
     - 件数 > 50,000（これより少ない = ファイル破損）

  13. docs/forecast/index.html
     - <meta name="robots" content="noindex"> が存在（T22-H1 暫定対応の維持）

  14. docs/ship/*.html
     - noindex 付与ページが 1件以上（T22-H2 が動作している証拠）

  15. docs/pages/faq.html
     - ファイル存在 + 本文 800字以上（T22-M1 共通FAQ切り出し）

  16. docs/fish/*.html サンプル
     - 共通FAQ固定文言「船酔い防止」「ライフジャケット」が消滅（T22-M1）
     - /pages/faq.html へのリンクが存在（T22-M1）

  17. docs/fish_area/*.html サンプル
     - intro 冒頭にエリア固有文（10字以上）が含まれる（T22-H3）

  18. docs/sitemap.xml
     - forecast/ URL が含まれない（T22-H1 sitemap 除外）

  19. OGP / twitter:card 全ページ整備（X 流入施策・手動投稿運用）
     - index / calendar / fish/* / area/* / fish_area/* / ship/* / fish/index / area/index に
       og:image / twitter:card / twitter:site が全て出力されている

  20. X シェアボタン設置（手動投稿でユーザー側拡散経路を保証）
     - index / fish/* / area/* / fish_area/* / ship/* / x_post/YYYY-MM-DD に
       class="share-bar" + twitter.com/intent/tweet リンクが設置されている

  21. docs/area/*.html サンプル（T31 2026/05/12 共通FAQ切り出し）
     - 共通FAQ見出し『船釣り共通の基礎知識』が消滅
     - /pages/faq.html へのリンクが存在
     - Q2 アクセス文章に「最寄りIC」「最寄り駅」キーワードが含まれる
       （hist_rows ベース固定文章化 + area_description.json access フィールド使用）

  24. docs/fish/*.html サンプル（T38-A4）
     - class="fish-areas-all" セクションが存在する（全歴エリア固定 Layer 1）

  25. docs/fish/*.html サンプル（T38-A6）
     - class="fish-related-species" セクションが存在する（共起関連魚種）

  26. docs/area/*.html サンプル（T38-A5）
     - class="area-all-fish" セクションが存在する（全歴魚種固定 Layer 1）

  27. docs/fish/*.html サンプル（T38-A8）
     - class="page-h1" の h1 タグが存在する（SEO h1 明示）

  28. docs/fish_area/*.html サンプル（T38-A3）
     - パンくず内に ../area/ リンクが存在する（2軸パンくず）

使用方法:
  python crawl/validate_output.py             # 全検証実行
  python crawl/validate_output.py --warn-only # warning のみ（失敗しない）

CI 組込: crawler.py の直後に呼び、非0終了時は git push をスキップ。
"""
import sys, os, json, re, argparse
from datetime import datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = os.path.join(ROOT, "docs")
DATA_V2 = os.path.join(ROOT, "data", "V2")
RAW_JSON = os.path.join(ROOT, "crawl", "catches_raw.json")

errors = []
warnings = []

def fail(msg):
    errors.append(msg)
    print(f"  [FAIL] {msg}")

def warn(msg):
    warnings.append(msg)
    print(f"  [WARN] {msg}")

def ok(msg):
    print(f"  [OK] {msg}")


def validate_index_html():
    print("\n[1] docs/index.html")
    path = os.path.join(DOCS, "index.html")
    if not os.path.isfile(path):
        fail("index.html が存在しない")
        return
    content = open(path, encoding="utf-8").read()
    fc_count = content.count('class="fc"')
    if fc_count < 5:
        fail(f"魚種カード（fc）が {fc_count} 枚しかない（5以上必要）")
    else:
        ok(f"魚種カード: {fc_count} 枚")
    m = re.search(r'<div class="n">(\d+)<u>件</u>', content)
    if not m:
        fail("HERO カウントが見つからない")
    elif int(m.group(1)) <= 0:
        fail(f"HERO カウントが 0（{m.group(0)}）")
    else:
        ok(f"HERO カウント: {m.group(1)} 件")


def validate_fish_index():
    print("\n[2] docs/fish/index.html")
    path = os.path.join(DOCS, "fish", "index.html")
    if not os.path.isfile(path):
        fail("fish/index.html が存在しない")
        return
    content = open(path, encoding="utf-8").read()
    counts = [int(m) for m in re.findall(r'今週釣果(\d+)[件便]', content)]
    if not counts:
        fail("「今週釣果X便」のラベルが見つからない")
        return
    nonzero = sum(1 for c in counts if c > 0)
    total = len(counts)
    ok(f"魚種総数: {total} / 釣果ありの魚種: {nonzero}")
    if nonzero < 5:
        fail(f"釣果ありの魚種が {nonzero} 種しかない（5種以上必要）")
    if total < 20:
        fail(f"魚種総数が {total} 種しかない（20種以上必要）")
    if nonzero / total < 0.10:
        warn(f"釣果ありの魚種が全体の {nonzero/total:.1%} と少ない")


def validate_area_index():
    print("\n[3] docs/area/index.html")
    path = os.path.join(DOCS, "area", "index.html")
    if not os.path.isfile(path):
        fail("area/index.html が存在しない")
        return
    content = open(path, encoding="utf-8").read()
    m = re.search(r'今週釣果あり (\d+)エリア', content)
    if not m:
        fail("「今週釣果あり Nエリア」のラベルが見つからない")
    else:
        n = int(m.group(1))
        if n < 5:
            fail(f"釣果ありエリアが {n} だけ（5以上必要）")
        else:
            ok(f"釣果ありエリア: {n}")
    ai_count = content.count('class="ai-card"')
    if ai_count < 10:
        fail(f"ai-card が {ai_count} 個しかない（10以上必要）")
    else:
        ok(f"ai-card: {ai_count} 個")


def validate_area_season_heatmap():
    """個別エリアページの「魚種別 旬カレンダー」が空セルだらけでないか検証。
    過去 analysis.sqlite gitignore で全セル data-v=-1 になる事故が複数回発生。
    SEASON_DATA フォールバックで各セルが 0〜4 のいずれかに塗られているはず。
    """
    print("\n[7] docs/area/*.html 旬カレンダーヒートマップ")
    area_dir = os.path.join(DOCS, "area")
    if not os.path.isdir(area_dir):
        warn("docs/area/ ディレクトリが無い")
        return
    sample_files = [f for f in os.listdir(area_dir)
                    if f.endswith(".html") and f != "index.html"][:10]
    if not sample_files:
        warn("検証対象の area HTML が無い")
        return
    bad_pages = []
    for fn in sample_files:
        with open(os.path.join(area_dir, fn), encoding="utf-8") as f:
            content = f.read()
        # 旬カレンダーが含まれているページのみ対象
        if 'as-cell' not in content:
            continue
        cells = re.findall(r'data-v="(-?\d+)"', content)
        if not cells:
            continue
        empty_cells = sum(1 for c in cells if c == "-1")
        if empty_cells / len(cells) > 0.5:
            bad_pages.append((fn, empty_cells, len(cells)))
    if bad_pages:
        for fn, e, t in bad_pages[:5]:
            fail(f"area/{fn}: 旬カレンダー {e}/{t} セルが空（>50%）")
    else:
        ok(f"area 旬カレンダー: {len(sample_files)} 件サンプル全て塗りつぶし正常")


def validate_area_sea_section():
    """area ページの「海況データ」セクションを検証。
    - 潮汐は名称（大潮/中潮/小潮/長潮/若潮）であって数値ではないこと
    - 月相は名称（満月/新月/三日月 等）であって数値ではないこと
    - 海況1行コメントが含まれていること（水温平年比 or 出船判定）
    """
    print("\n[12] docs/area/*.html 海況セクション")
    area_dir = os.path.join(DOCS, "area")
    if not os.path.isdir(area_dir):
        warn("docs/area/ ディレクトリが無い")
        return
    sample = [f for f in os.listdir(area_dir)
              if f.endswith(".html") and f != "index.html"][:10]
    if not sample:
        warn("検証対象の area HTML が無い")
        return
    tide_names = {"大潮", "中潮", "小潮", "長潮", "若潮", "—"}
    moon_names = {"満月", "新月", "三日月", "上弦の月", "下弦の月", "十三夜", "十六夜", "有明月", "—"}
    bad = []
    for fn in sample:
        content = open(os.path.join(area_dir, fn), encoding="utf-8").read()
        if "海況データ" not in content or "sea-grid" not in content:
            continue
        # sea-item の sv 値を抽出（順番: 水温/波高/風/潮汐/月相/気圧）
        m = re.search(r'<div class="sea-grid">(.*?)</div>\s*\)?', content, re.DOTALL)
        if not m:
            continue
        # 潮汐 sea-item 抽出
        items = re.findall(r'<div class="sv">([^<]+)</div><div class="sl2">([^<]+)</div>', m.group(1))
        for val, lbl in items:
            val = val.strip()
            if "潮汐" in lbl and val not in tide_names:
                # 数値（小数点 or 数字のみ）なら NG
                if re.fullmatch(r'[\d.]+', val):
                    bad.append((fn, f"潮汐が数値: {val}"))
            if ("月相" in lbl or "月齢" in lbl) and val not in moon_names:
                if re.fullmatch(r'[\d.]+', val):
                    bad.append((fn, f"月相が数値: {val}"))
        # 海況コメント: 水温/波/風 のいずれかを言及する <p> が sea-grid 直前にあること
        if "海況データ" in content and "sea-grid" in content:
            # 「平年」「出船」「欠航リスク」「穏やか」のいずれかが海況セクション付近にある
            section_idx = content.find("海況データ")
            sea_segment = content[section_idx:section_idx+800]
            has_comment = any(kw in sea_segment for kw in (
                "平年", "出船日和", "出船注意", "欠航警戒", "荒れ"
            ))
            if not has_comment:
                bad.append((fn, "海況1行コメントが無い"))
            # 内部用語（外海/内海/基準）が表示文言に漏れていないか
            for ng_word in ("外海基準", "内海基準", "外海的", "内海的"):
                if ng_word in sea_segment:
                    bad.append((fn, f"内部用語「{ng_word}」が文言に漏出"))
                    break
    if bad:
        for fn, reason in bad[:5]:
            fail(f"area/{fn}: {reason}")
    else:
        ok(f"area 海況セクション: {len(sample)} 件サンプル正常（潮汐・月相が名称・コメントあり）")


def validate_no_nested_anchors():
    """ネストした <a> タグ（HTML5 invalid）が無いか検証。
    過去 area ページの fia カード内部に <a class="fia">...<div class="fb">◎<a>船宿</a></div></a>
    という構造があり、ブラウザが自動的に anchor を分離して「◎船宿名」が
    独立カードとして表示される事故が発生した。
    """
    print("\n[11] ネストした <a> タグ検出")
    targets = []
    for sub in ("area", "fish", "fish_area", "ship"):
        d = os.path.join(DOCS, sub)
        if os.path.isdir(d):
            for fn in os.listdir(d):
                if fn.endswith(".html"):
                    targets.append(os.path.join(d, fn))
    if not targets:
        warn("検証対象 HTML が無い")
        return
    bad = []
    # 簡易検出: <a で始まり </a> で閉じるまでの間にもう1つ <a が出現
    pattern = re.compile(r'<a\s[^>]*>(?:(?!</a>).)*?<a\s', re.DOTALL)
    for path in targets[:30]:  # 先頭30ファイルのみサンプル（速度のため）
        try:
            content = open(path, encoding="utf-8").read()
        except Exception:
            continue
        if pattern.search(content):
            bad.append(os.path.relpath(path, DOCS))
    if bad:
        for p in bad[:5]:
            fail(f"{p}: ネストした <a> タグを検出")
        if len(bad) > 5:
            fail(f"... 他 {len(bad)-5} ファイルも同問題")
    else:
        ok(f"ネストアンカー: {len(targets[:30])} 件サンプル全てクリア")


def validate_fish_hero_uniformity():
    """全 fish/*.html ページが同じ HERO 構造を持つか検証。
    過去マダイ（rich）と ワラサ（placeholder）で .fh-sub と .c wrapper の有無で
    レイアウトが分岐していた事故を再発させない。
    """
    print("\n[10] docs/fish/*.html HERO 構造の統一")
    fish_dir = os.path.join(DOCS, "fish")
    if not os.path.isdir(fish_dir):
        warn("docs/fish/ ディレクトリが無い")
        return
    files = [f for f in os.listdir(fish_dir)
             if f.endswith(".html") and f != "index.html"]
    if not files:
        warn("検証対象 fish HTML が無い")
        return
    bad = []
    for fn in files:
        with open(os.path.join(fish_dir, fn), encoding="utf-8") as f:
            content = f.read()
        # fish-hero div の直下が h2 であること（.c wrapper を許容しない）
        m = re.search(r'<div class="fish-hero">(\s*<!--[^-]*-->)?\s*(<[^>]+>)', content)
        if not m:
            bad.append((fn, "fish-hero div が無い"))
            continue
        first_tag = m.group(2)
        if not first_tag.startswith("<h2"):
            bad.append((fn, f"fish-hero 直下が <h2> ではない（{first_tag[:30]}）"))
            continue
        # 古い fh-sub が混入していないこと
        if re.search(r'<div class="fish-hero">[\s\S]*?<div class="fh-sub">', content):
            bad.append((fn, "古い fh-sub が残存（placeholder 旧形式）"))
    if bad:
        for fn, reason in bad[:5]:
            fail(f"fish/{fn}: {reason}")
        if len(bad) > 5:
            fail(f"... 他 {len(bad)-5} ファイルも同種の問題")
    else:
        ok(f"fish HERO 統一: {len(files)} ファイル全て同構造")


def validate_fish_7day_chart():
    """個別魚種ページ docs/fish/{slug}.html の「直近7日間の釣果推移」チャートが
    今日の1本だけになっていないか検証。
    chart-bars 内の <div class="cb..."> が height:8% 以下なのは「データなし」相当。
    7 本中 6 本以上が「データなし」なら、過去日が空（今日だけしか描画されてない）。
    """
    print("\n[9] docs/fish/*.html 直近7日チャート")
    fish_dir = os.path.join(DOCS, "fish")
    if not os.path.isdir(fish_dir):
        warn("docs/fish/ ディレクトリが無い")
        return
    # 主要魚種（aji, madai, hirame, etc.）のうち 5件サンプル
    candidates = ["aji", "madai", "hirame", "tachiuo", "kawahagi",
                  "kasago", "shirogisu", "warasa", "marika", "mebaru"]
    sample = [c for c in candidates if os.path.isfile(os.path.join(fish_dir, f"{c}.html"))][:5]
    if not sample:
        warn("検証対象の主要 fish HTML が見つからない")
        return
    bad = []
    for slug in sample:
        path = os.path.join(fish_dir, f"{slug}.html")
        content = open(path, encoding="utf-8").read()
        if "直近7日間の釣果推移" not in content:
            continue
        # chart-bars 内の cb 要素を抽出（chart-labels 直前まで）
        m = re.search(r'<div class="chart-bars">(.*?)<div class="chart-labels"', content, re.DOTALL)
        if not m:
            bad.append((slug, "chart-bars 要素が無い"))
            continue
        heights = re.findall(r'class="cb[^"]*"\s+style="height:(\d+)%"', m.group(1))
        if len(heights) != 7:
            bad.append((slug, f"バー数 {len(heights)} != 7"))
            continue
        empty = sum(1 for h in heights if int(h) <= 8)
        if empty >= 6:
            bad.append((slug, f"7本中 {empty} 本が height≤8%（過去日空）"))
    if bad:
        for slug, reason in bad[:5]:
            fail(f"fish/{slug}.html: {reason}")
    else:
        ok(f"fish 7日チャート: {len(sample)} 件サンプル正常")


def validate_area_fia_cards():
    """個別エリアページの「このエリアで今週釣れている魚」fia-grid を検証。
    - 過去複数回、fia card が空（< 3 cards）になる事故が発生
    - card 内の cnt_str（匹数）/sz_str（サイズ）が空ばかりだとレイアウト sparse
    """
    print("\n[8] docs/area/*.html 今週釣れている魚 fia-grid")
    area_dir = os.path.join(DOCS, "area")
    if not os.path.isdir(area_dir):
        warn("docs/area/ ディレクトリが無い")
        return
    # データのある area_index.html から area_summary に登場するエリアを取得
    aindex_path = os.path.join(area_dir, "index.html")
    if not os.path.isfile(aindex_path):
        warn("area/index.html が無い → fia-grid 検証 skip")
        return
    aindex_content = open(aindex_path, encoding="utf-8").read()
    # area_index で「今週釣果X件」と表示されているエリア（X >= 5）のページのみ検証
    target_slugs = []
    for m in re.finditer(r'href="(\w[\w-]*)\.html"[^>]*>.*?今週釣果(\d+)[件便]', aindex_content, re.DOTALL):
        slug, n = m.group(1), int(m.group(2))
        if n >= 5:
            target_slugs.append(slug)
    if not target_slugs:
        warn("検証対象エリア（週5件以上）が無い")
        return
    sample = target_slugs[:5]
    bad = []
    sparse = []
    for slug in sample:
        path = os.path.join(area_dir, f"{slug}.html")
        if not os.path.isfile(path):
            continue
        content = open(path, encoding="utf-8").read()
        if "このエリアで今週釣れている魚" not in content:
            continue
        # fia card 数
        fia_count = len(re.findall(r'<a class="fia"', content))
        if fia_count < 1:
            bad.append((slug, "fia card が 0"))
            continue
        # サイズ・匹数の有無を確認（"15〜30匹" や "20〜40cm" 形式）
        m = re.search(r'<a class="fia"[^>]*>(.*?)</a>', content, re.DOTALL)
        if m:
            card = m.group(1)
            has_count = bool(re.search(r'\d+〜\d+匹|\d+匹', card))
            has_size = bool(re.search(r'\d+〜\d+cm|\d+cm', card))
            if not (has_count or has_size):
                sparse.append(slug)
    if bad:
        for slug, reason in bad:
            fail(f"area/{slug}.html: {reason}")
    elif len(sparse) >= len(sample) // 2:
        warn(f"area/*.html fia card に 匹数/サイズ が無いページが多い: {sparse[:3]}")
    else:
        ok(f"area fia-grid: {len(sample)} 件サンプル正常（card あり・匹数orサイズあり）")


def validate_calendar_html():
    print("\n[4] docs/calendar.html")
    path = os.path.join(DOCS, "calendar.html")
    if not os.path.isfile(path):
        fail("calendar.html が存在しない")
        return
    content = open(path, encoding="utf-8").read()
    mc_count = content.count('class="mc-card')
    if mc_count < 12:
        warn(f"月別カード（mc-card）が {mc_count} 個（12個期待）")
    else:
        ok(f"月別カード: {mc_count} 個")


def validate_csv_freshness():
    print("\n[5] data/V2/YYYY-MM.csv 鮮度")
    today = datetime.now()
    ym = today.strftime("%Y-%m")
    path = os.path.join(DATA_V2, f"{ym}.csv")
    if not os.path.isfile(path):
        # 当月初日〜2日目は許容
        if today.day <= 2:
            warn(f"{ym}.csv 未生成（当月初日〜2日目のため許容）")
            return
        fail(f"{ym}.csv が存在しない")
        return
    import csv
    with open(path, encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        fail(f"{ym}.csv が空")
        return
    dates = sorted(r["date"] for r in rows if r.get("date"))
    if not dates:
        fail(f"{ym}.csv に date 列が無い")
        return
    latest = dates[-1]
    cutoff = (today - timedelta(days=2)).strftime("%Y/%m/%d")
    # 当月切替後3日間は緩和（先月CSVが正でも今月CSVに新規が入る前）
    if today.day <= 3:
        ok(f"{ym}.csv 最新日付: {latest}（当月初日〜3日目のため緩和）")
        return
    if latest < cutoff:
        fail(f"{ym}.csv 最新日付 {latest} が古すぎる（cutoff: {cutoff}）")
    else:
        ok(f"{ym}.csv 最新日付: {latest}")


def validate_catches_raw():
    print("\n[6] crawl/catches_raw.json 件数")
    if not os.path.isfile(RAW_JSON):
        warn("catches_raw.json が存在しない（CI 環境では skip）")
        return
    try:
        size = os.path.getsize(RAW_JSON)
        if size < 1_000_000:
            fail(f"catches_raw.json が {size:,} bytes（1MB未満 = 破損疑い）")
            return
        # 件数チェック（行数で代用：1レコード ≈ 数百バイト）
        # 50,000件 < 件数（小さいと破損疑い）
        with open(RAW_JSON, encoding="utf-8") as f:
            d = json.load(f)
        if not isinstance(d, list):
            fail("catches_raw.json が list ではない")
            return
        if len(d) < 50_000:
            fail(f"catches_raw.json が {len(d)} 件しかない（50,000件以上必要）")
        else:
            ok(f"catches_raw.json: {len(d):,} 件")
    except Exception as e:
        fail(f"catches_raw.json 読込失敗: {e}")


def validate_forecast_noindex():
    print("\n[13] docs/forecast/index.html noindex タグ存在（T22-H1）")
    path = os.path.join(DOCS, "forecast", "index.html")
    if not os.path.isfile(path):
        fail("forecast/index.html が存在しない")
        return
    content = open(path, encoding="utf-8").read()
    if 'name="robots"' not in content or "noindex" not in content:
        fail("forecast/index.html に noindex タグが存在しない（T23 で実コンテンツ化するまでは必須）")
    else:
        ok("forecast/index.html: noindex タグ確認")


def validate_ship_noindex():
    print("\n[14] docs/ship/*.html noindex 付与（T22-H2）")
    ship_dir = os.path.join(DOCS, "ship")
    if not os.path.isdir(ship_dir):
        fail("docs/ship/ ディレクトリが存在しない")
        return
    files = [f for f in os.listdir(ship_dir) if f.endswith(".html") and f != "index.html"]
    noindex_count = 0
    for fn in files:
        content = open(os.path.join(ship_dir, fn), encoding="utf-8").read()
        if 'name="robots"' in content and "noindex" in content:
            noindex_count += 1
    if noindex_count < 1:
        fail(f"ship/*.html で noindex 付与ページが {noindex_count} 件（最低 1 件・空ship判定が動作している証拠）")
    else:
        ok(f"ship/*.html noindex 付与: {noindex_count} 件 / 全 {len(files)} 件")


def validate_pages_faq():
    print("\n[15] docs/pages/faq.html 存在＋本文 800字以上（T22-M1）")
    path = os.path.join(DOCS, "pages", "faq.html")
    if not os.path.isfile(path):
        fail("docs/pages/faq.html が存在しない（pages/faq.html の design sync 漏れ）")
        return
    content = open(path, encoding="utf-8").read()
    text_only = re.sub(r"<[^>]+>", "", content)
    text_only = re.sub(r"\s+", "", text_only)
    if len(text_only) < 800:
        fail(f"pages/faq.html 本文が {len(text_only)} 字（800字以上必要）")
    else:
        ok(f"pages/faq.html: {len(text_only)} 字（HTMLタグ除く）")


def validate_fish_no_common_faq():
    print("\n[16] docs/fish/*.html サンプル: 共通FAQ消滅 + faq.html リンク存在（T22-M1）")
    fish_dir = os.path.join(DOCS, "fish")
    if not os.path.isdir(fish_dir):
        fail("docs/fish/ ディレクトリが存在しない")
        return
    samples = ["aji.html", "madai.html", "tachiuo.html", "shirogisu.html", "kawahagi.html"]
    samples = [s for s in samples if os.path.isfile(os.path.join(fish_dir, s))]
    if not samples:
        fail("fish サンプル 5 種が一つも存在しない")
        return
    bad_residual = []
    bad_link = []
    for fn in samples:
        content = open(os.path.join(fish_dir, fn), encoding="utf-8").read()
        # 共通FAQ固定文言（船釣り共通の 7 問本文の特徴的フレーズ）
        if "船釣り共通の基礎知識" in content:
            bad_residual.append(fn)
        # faq.html リンク
        if "/pages/faq.html" not in content:
            bad_link.append(fn)
    if bad_residual:
        fail(f"共通FAQ見出し『船釣り共通の基礎知識』残存: {', '.join(bad_residual)}")
    if bad_link:
        fail(f"/pages/faq.html リンク欠如: {', '.join(bad_link)}")
    if not bad_residual and not bad_link:
        ok(f"fish サンプル {len(samples)} 種全て共通FAQ消滅 + faq.htmlリンクあり")


def validate_area_no_common_faq():
    print("\n[21] docs/area/*.html サンプル: 共通FAQ消滅 + faq.html リンク + アクセスQ2に最寄りIC/駅（T31）")
    area_dir = os.path.join(DOCS, "area")
    if not os.path.isdir(area_dir):
        fail("docs/area/ ディレクトリが存在しない")
        return
    samples = ["kanazawa-hakkei.html", "urayasu.html", "hiratsuka.html", "iioka.html", "kanaya.html"]
    samples = [s for s in samples if os.path.isfile(os.path.join(area_dir, s))]
    if not samples:
        fail("area サンプル 5 種が一つも存在しない")
        return
    bad_residual = []
    bad_link = []
    bad_access = []
    for fn in samples:
        content = open(os.path.join(area_dir, fn), encoding="utf-8").read()
        if "船釣り共通の基礎知識" in content:
            bad_residual.append(fn)
        if "/pages/faq.html" not in content:
            bad_link.append(fn)
        # Q2 アクセス文章: 「最寄りIC」「最寄り駅」が含まれていること（hist_rows ベース固定文章化の証拠）
        if "最寄りIC" not in content or "最寄り駅" not in content:
            bad_access.append(fn)
    if bad_residual:
        fail(f"[21] 共通FAQ見出し『船釣り共通の基礎知識』残存: {', '.join(bad_residual)}")
    if bad_link:
        fail(f"[21] /pages/faq.html リンク欠如: {', '.join(bad_link)}")
    if bad_access:
        fail(f"[21] アクセスQ2に最寄りIC/駅キーワード欠如: {', '.join(bad_access)}")
    if not bad_residual and not bad_link and not bad_access:
        ok(f"area サンプル {len(samples)} 種全て共通FAQ消滅 + faq.htmlリンク + 最寄りIC/駅あり")


def validate_fish_area_intro():
    print("\n[17] docs/fish_area/*.html サンプル: エリア固有 intro 冒頭文（T22-H3）")
    fa_dir = os.path.join(DOCS, "fish_area")
    if not os.path.isdir(fa_dir):
        fail("docs/fish_area/ ディレクトリが存在しない")
        return
    samples = ["madai-iioka.html", "aji-kanazawa-hakkei.html", "shirogisu-kanazawa-hakkei.html"]
    samples = [s for s in samples if os.path.isfile(os.path.join(fa_dir, s))]
    if not samples:
        warn("fish_area サンプル候補が一つも存在しない（skip）")
        return
    failed = []
    for fn in samples:
        content = open(os.path.join(fa_dir, fn), encoding="utf-8").read()
        # intro セクション抽出（fa-intro-text または最初の <p>）
        m = re.search(r'<p[^>]*>([^<]{10,})</p>', content)
        if not m:
            failed.append(f"{fn}（intro <p> タグが見つからない）")
            continue
        first_para = m.group(1)
        # area_description.json 由来文の典型: 「〇〇は〜に位置する/にある」「〇〇県」「〇〇湾」「外房」「内房」「東京湾」等
        keywords = ["位置", "県", "湾", "港は", "外房", "内房", "面し", "市", "町"]
        if not any(k in first_para for k in keywords):
            failed.append(f"{fn}（冒頭文にエリア地理特徴語なし: {first_para[:50]}）")
    if failed:
        fail(f"fish_area intro エリア固有文未挿入: {'; '.join(failed)}")
    else:
        ok(f"fish_area サンプル {len(samples)} 件全て intro 冒頭にエリア固有文あり")


def validate_sitemap_no_forecast():
    print("\n[18] docs/sitemap.xml に forecast/ URL なし（T22-H1）")
    path = os.path.join(DOCS, "sitemap.xml")
    if not os.path.isfile(path):
        fail("sitemap.xml が存在しない")
        return
    content = open(path, encoding="utf-8").read()
    fc_count = content.count("forecast/")
    if fc_count > 0:
        fail(f"sitemap.xml に forecast/ URL が {fc_count} 件残存（T22-H1 暫定除外要）")
    else:
        ok("sitemap.xml: forecast/ URL 0 件")


def _collect_ogp_share_targets():
    """主要HTMLサンプルを集める。各サブディレクトリから 1 件ずつ。"""
    targets = []
    for label, rel in [("index", "index.html"), ("calendar", "calendar.html"),
                       ("fish/index", "fish/index.html"), ("area/index", "area/index.html")]:
        p = os.path.join(DOCS, rel)
        if os.path.isfile(p):
            targets.append((label, p))
    for sub in ("fish", "area", "fish_area", "ship"):
        d = os.path.join(DOCS, sub)
        if not os.path.isdir(d):
            continue
        files = sorted(f for f in os.listdir(d) if f.endswith(".html") and f != "index.html")
        if files:
            targets.append((f"{sub}/{files[0]}", os.path.join(d, files[0])))
    return targets


def validate_ogp_meta():
    """[19] 主要ページに og:image / twitter:card / twitter:site が出力されているか。

    手動 X 投稿時に URL を貼った瞬間にリッチカードが描画される条件。
    forecast/ は noindex 維持のため対象外（T22-H1）。
    """
    print("\n[19] OGP / twitter:card 全ページ整備")
    targets = _collect_ogp_share_targets()
    if not targets:
        fail("OGP 検証対象の HTML が 1 件も見つからない")
        return
    for label, path in targets:
        try:
            html = open(path, encoding="utf-8").read()
        except Exception as e:
            fail(f"{label}: 読み込み失敗 {e}")
            continue
        missing = []
        if 'property="og:image"' not in html:
            missing.append("og:image")
        if 'name="twitter:card"' not in html:
            missing.append("twitter:card")
        if 'name="twitter:site"' not in html:
            missing.append("twitter:site")
        if missing:
            fail(f"{label}: メタタグ欠落 → {', '.join(missing)}")
            # DEBUG: head 部分を出力して原因特定（CI でローカル不在の事象を診断するため）
            head_start = html.find('<head>')
            head_end = html.find('</head>')
            if head_start >= 0 and head_end >= 0:
                head_excerpt = html[head_start:head_end+7]
                print(f"  [DEBUG] {label} <head> ({len(head_excerpt)} chars):")
                for line in head_excerpt.splitlines()[:30]:
                    print(f"    {line[:200]}")
        else:
            ok(f"{label}: og:image / twitter:card / twitter:site OK")


def validate_fish_area_cmp_link():
    """[22] docs/fish/*.html サンプル: area_cmp 内に fish_area への「{エリア}の{魚種}釣果」リンク（T29）

    AdSense 観点で fish_area/* を内部リンクで包囲し、Google クロール経路を確保するため。
    既存 fish_area ページが存在するエリアで .ar 行に span.ar-fa リンクが出力されている
    ことを確認する。全サンプルが area_cmp なしの場合は warn。
    """
    print("\n[22] docs/fish/*.html サンプル: area_cmp に fish_area リンク（T29 孤立解消）")
    fish_dir = os.path.join(DOCS, "fish")
    if not os.path.isdir(fish_dir):
        fail("docs/fish/ ディレクトリが存在しない")
        return
    samples = ["aji.html", "shirogisu.html", "tachiuo.html", "madai.html"]
    samples = [s for s in samples if os.path.isfile(os.path.join(fish_dir, s))]
    if not samples:
        warn("fish サンプル候補が一つも存在しない（skip）")
        return
    failed = []
    skipped = 0
    for fn in samples:
        content = open(os.path.join(fish_dir, fn), encoding="utf-8").read()
        # area-cmp セクションがある場合のみ .ar-fa を要求（area_cmp 自体がなければ skip）
        if 'class="area-cmp"' not in content:
            skipped += 1
            continue
        if 'class="ar-fa"' not in content:
            failed.append(fn)
    if failed:
        fail(f"[22] fish/*.html area_cmp 内 .ar-fa リンク欠如: {', '.join(failed)}")
    elif skipped == len(samples):
        warn(f"[22] サンプル {len(samples)} 件全て area_cmp なしで skip（要確認）")
    else:
        ok(f"fish サンプル {len(samples)} 件で area_cmp に .ar-fa リンクあり（または area_cmp なし skip={skipped}）")


def validate_fish_area_related():
    """[23] docs/fish_area/*.html サンプル: FAQ 直前に fa-related セクション存在（T29）

    fish_area/* 同士の相互リンクを確保するため、データ件数が一定以上ある主要コンボの
    fish_area ページに fa-related セクションが出力されていることを確認する。
    """
    print("\n[23] docs/fish_area/*.html サンプル: fa-related 相互リンク（T29 孤立解消）")
    fa_dir = os.path.join(DOCS, "fish_area")
    if not os.path.isdir(fa_dir):
        fail("docs/fish_area/ ディレクトリが存在しない")
        return
    # 主要・多データのコンボ（同魚種他エリア・同エリア他魚種共に十分にある想定）
    samples = ["aji-yokohama-honmoku.html", "madai-iioka.html", "aji-kanazawa-hakkei.html"]
    samples = [s for s in samples if os.path.isfile(os.path.join(fa_dir, s))]
    if not samples:
        warn("fish_area サンプル候補が一つも存在しない（skip）")
        return
    failed = []
    for fn in samples:
        content = open(os.path.join(fa_dir, fn), encoding="utf-8").read()
        if 'class="fa-related"' not in content:
            failed.append(f"{fn}（fa-related セクション欠如）")
            continue
        # fa-related ブロック全体（FAQ 見出しまで）に chip-link が 1 件以上あること
        m = re.search(r'<div class="fa-related">(.+?)<h2 class="st">よくある質問', content, re.DOTALL)
        block = m.group(1) if m else ""
        if block.count('class="chip-link"') < 1:
            failed.append(f"{fn}（fa-related 内に chip-link なし）")
    if failed:
        fail(f"[23] fish_area/*.html fa-related 不備: {'; '.join(failed)}")
    else:
        ok(f"fish_area サンプル {len(samples)} 件全て fa-related + chip-link あり")


def validate_share_buttons():
    """[20] 主要ページに X シェアボタン（class="share-bar"）が設置されているか。

    手動投稿でユーザー側拡散経路を保証する不変条件。
    fish/index・area/index は一覧ページでありシェア対象外（個別ページに導線あり）。
    """
    print("\n[20] X シェアボタン設置")
    targets = []
    for label, rel in [("index", "index.html")]:
        p = os.path.join(DOCS, rel)
        if os.path.isfile(p):
            targets.append((label, p))
    for sub in ("fish", "area", "fish_area", "ship"):
        d = os.path.join(DOCS, sub)
        if not os.path.isdir(d):
            continue
        files = sorted(f for f in os.listdir(d) if f.endswith(".html") and f != "index.html")
        if files:
            targets.append((f"{sub}/{files[0]}", os.path.join(d, files[0])))
    # x_post 日次ページは date_str ファイル名のため別途サンプル
    xp_dir = os.path.join(DOCS, "x_post")
    if os.path.isdir(xp_dir):
        xp_files = sorted(f for f in os.listdir(xp_dir)
                          if f.endswith(".html") and re.match(r"^\d{4}-\d{2}-\d{2}\.html$", f))
        if xp_files:
            targets.append((f"x_post/{xp_files[-1]}", os.path.join(xp_dir, xp_files[-1])))
    if not targets:
        fail("シェアボタン検証対象の HTML が 1 件も見つからない")
        return
    for label, path in targets:
        try:
            html = open(path, encoding="utf-8").read()
        except Exception as e:
            fail(f"{label}: 読み込み失敗 {e}")
            continue
        if 'class="share-bar"' not in html:
            fail(f"{label}: share-bar 欠落（X シェアボタン未設置）")
            # DEBUG: body 部分の冒頭を出力
            body_start = html.find('<body>')
            if body_start >= 0:
                body_excerpt = html[body_start:body_start+1500]
                print(f"  [DEBUG] {label} <body> 冒頭:")
                for line in body_excerpt.splitlines()[:20]:
                    print(f"    {line[:200]}")
        elif "twitter.com/intent/tweet" not in html:
            fail(f"{label}: share-bar はあるが twitter.com/intent/tweet リンク不在")
        else:
            ok(f"{label}: share-bar OK")


_T38_FISH_SAMPLES = ["aji.html", "madai.html", "shirogisu.html"]
_T38_AREA_SAMPLES = ["yokohama-honmoku.html", "kanazawa-hakkei.html"]
_T38_FA_SAMPLES = ["aji-yokohama-honmoku.html", "madai-iioka.html", "aji-kanazawa-hakkei.html"]


def _t38_pick_samples(base_dir, sample_list):
    """固定サンプルリストから実在ファイルのみ返す（reviewer M-2 対策）"""
    return [fn for fn in sample_list if os.path.exists(os.path.join(base_dir, fn))]


def validate_fish_areas_all_section():
    """24: fish/*.html に fish-areas-all セクション存在（T38-A4 Layer 1 固定エリア）"""
    print("\n[24] fish/*.html - fish-areas-all セクション")
    fish_dir = os.path.join(DOCS, "fish")
    if not os.path.isdir(fish_dir):
        fail("fish/ ディレクトリが存在しない")
        return
    samples = _t38_pick_samples(fish_dir, _T38_FISH_SAMPLES)
    if not samples:
        warn("fish/ 固定サンプルが存在しない → skip")
        return
    found = 0
    for fn in samples:
        html = open(os.path.join(fish_dir, fn), encoding="utf-8").read()
        if 'class="fish-areas-all"' in html:
            found += 1
    if found < len(samples):
        fail(f"fish/ 固定サンプル {len(samples)} 件中 fish-areas-all が {found} 件のみ（全件必須）")
    else:
        ok(f"fish-areas-all: {found}/{len(samples)} 全件存在")


def validate_fish_related_species_section():
    """25: fish/*.html に fish-related-species セクション存在（T38-A6 共起関連魚種）"""
    print("\n[25] fish/*.html - fish-related-species セクション")
    fish_dir = os.path.join(DOCS, "fish")
    if not os.path.isdir(fish_dir):
        fail("fish/ ディレクトリが存在しない")
        return
    samples = _t38_pick_samples(fish_dir, _T38_FISH_SAMPLES)
    if not samples:
        warn("fish/ 固定サンプルが存在しない → skip")
        return
    found = 0
    for fn in samples:
        html = open(os.path.join(fish_dir, fn), encoding="utf-8").read()
        if 'class="fish-related-species"' in html:
            found += 1
    if found < len(samples):
        fail(f"fish/ 固定サンプル {len(samples)} 件中 fish-related-species が {found} 件のみ（全件必須）")
    else:
        ok(f"fish-related-species: {found}/{len(samples)} 全件存在")


def validate_area_all_fish_section():
    """26: area/*.html に area-all-fish セクション存在（T38-A5 Layer 1 固定魚種）"""
    print("\n[26] area/*.html - area-all-fish セクション")
    area_dir = os.path.join(DOCS, "area")
    if not os.path.isdir(area_dir):
        fail("area/ ディレクトリが存在しない")
        return
    samples = _t38_pick_samples(area_dir, _T38_AREA_SAMPLES)
    if not samples:
        warn("area/ 固定サンプルが存在しない → skip")
        return
    found = 0
    for fn in samples:
        html = open(os.path.join(area_dir, fn), encoding="utf-8").read()
        if 'class="area-all-fish"' in html:
            found += 1
    if found < len(samples):
        fail(f"area/ 固定サンプル {len(samples)} 件中 area-all-fish が {found} 件のみ（全件必須）")
    else:
        ok(f"area-all-fish: {found}/{len(samples)} 全件存在")


def validate_fish_page_h1():
    """27: fish/*.html に class="page-h1" の h1 タグが存在（T38-A8 SEO h1）"""
    print("\n[27] fish/*.html - page-h1 存在")
    fish_dir = os.path.join(DOCS, "fish")
    if not os.path.isdir(fish_dir):
        fail("fish/ ディレクトリが存在しない")
        return
    samples = _t38_pick_samples(fish_dir, _T38_FISH_SAMPLES)
    if not samples:
        warn("fish/ 固定サンプルが存在しない → skip")
        return
    found = 0
    for fn in samples:
        html = open(os.path.join(fish_dir, fn), encoding="utf-8").read()
        if 'class="page-h1"' in html:
            found += 1
    if found < len(samples):
        fail(f"fish/ 固定サンプル {len(samples)} 件中 page-h1 が {found} 件のみ（全件必須）")
    else:
        ok(f"page-h1: {found}/{len(samples)} 全件存在")


def validate_fish_area_breadcrumb_2axis():
    """28: fish_area/*.html パンくずに area ページへのリンクが存在（T38-A3 2軸パンくず）"""
    print("\n[28] fish_area/*.html - 2軸パンくず（area/ リンク）")
    fa_dir = os.path.join(DOCS, "fish_area")
    if not os.path.isdir(fa_dir):
        fail("fish_area/ ディレクトリが存在しない")
        return
    samples = _t38_pick_samples(fa_dir, _T38_FA_SAMPLES)
    if not samples:
        warn("fish_area/ 固定サンプルが存在しない → skip")
        return
    found = 0
    for fn in samples:
        html = open(os.path.join(fa_dir, fn), encoding="utf-8").read()
        bread_m = re.search(r'<p class="bread">(.*?)</p>', html, re.DOTALL)
        if bread_m and '../area/' in bread_m.group(1):
            found += 1
    if found < len(samples):
        fail(f"fish_area/ 固定サンプル {len(samples)} 件中 2軸パンくずが {found} 件のみ（全件必須）")
    else:
        ok(f"2軸パンくず: {found}/{len(samples)} 全件存在")


def validate_fa_related_3axis():
    """29: fish_area/*.html fa-related が3軸構造（reviewer C-2 対応・T38-A2 検証）"""
    print("\n[29] fish_area/*.html - fa-related 3軸構造（軸1+軸2+軸3 各 chip-wrap 必須）")
    fa_dir = os.path.join(DOCS, "fish_area")
    if not os.path.isdir(fa_dir):
        fail("fish_area/ ディレクトリが存在しない")
        return
    samples = _t38_pick_samples(fa_dir, _T38_FA_SAMPLES)
    if not samples:
        warn("fish_area/ 固定サンプルが存在しない → skip")
        return
    found = 0
    detail = []
    for fn in samples:
        html = open(os.path.join(fa_dir, fn), encoding="utf-8").read()
        # fa-related の class 開始位置を起点に、次の主要セクション（FAQ等）までを範囲とする
        m_start = re.search(r'class="fa-related"', html)
        if not m_start:
            detail.append(f"{fn}: fa-related セクション無し")
            continue
        start = m_start.end()
        # 終端: よくある質問 (FAQ) の見出し or </body>
        m_end = re.search(r'<h2[^>]*>よくある質問|</body>', html[start:])
        end = start + (m_end.start() if m_end else 5000)
        fa_html = html[start:end]
        h2_count = len(re.findall(r'<h2[^>]*>', fa_html))
        chip_wrap_count = len(re.findall(r'<div class="chip-wrap">', fa_html))
        if h2_count >= 3 and chip_wrap_count >= 3:
            found += 1
        else:
            detail.append(f"{fn}: h2={h2_count}・chip-wrap={chip_wrap_count}（3+3 必須）")
    if found < len(samples):
        fail(f"fish_area/ 固定サンプル {len(samples)} 件中 fa-related 3軸が {found} 件のみ: {'; '.join(detail)}")
    else:
        ok(f"fa-related 3jiku: {found}/{len(samples)} all present (h2>=3 + chip-wrap>=3)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--warn-only", action="store_true",
                    help="エラーでも非0終了しない（rollout 用）")
    args = ap.parse_args()

    print("=" * 60)
    print("HTML / CSV 出力 整合性検証")
    print("=" * 60)

    validate_index_html()
    validate_fish_index()
    validate_area_index()
    validate_calendar_html()
    validate_csv_freshness()
    validate_catches_raw()
    validate_area_season_heatmap()
    validate_area_fia_cards()
    validate_fish_7day_chart()
    validate_fish_hero_uniformity()
    validate_no_nested_anchors()
    validate_area_sea_section()
    validate_forecast_noindex()
    validate_ship_noindex()
    validate_pages_faq()
    validate_fish_no_common_faq()
    validate_area_no_common_faq()
    validate_fish_area_intro()
    validate_sitemap_no_forecast()
    validate_ogp_meta()
    validate_fish_area_cmp_link()
    validate_fish_area_related()
    validate_share_buttons()
    validate_fish_areas_all_section()
    validate_fish_related_species_section()
    validate_area_all_fish_section()
    validate_fish_page_h1()
    validate_fish_area_breadcrumb_2axis()
    validate_fa_related_3axis()

    print("\n" + "=" * 60)
    print(f"結果: errors={len(errors)} / warnings={len(warnings)}")
    print("=" * 60)

    if errors:
        print("\nERRORS:")
        for e in errors:
            print(f"  - {e}")
    if warnings:
        print("\nWARNINGS:")
        for w in warnings:
            print(f"  - {w}")

    if errors and not args.warn_only:
        sys.exit(1)


if __name__ == "__main__":
    main()
