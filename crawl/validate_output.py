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

  13. docs/forecast/ index/個別ページの noindex（T23・2026-07-03 反転）
     - forecast/index.html（ハブ）は noindex なし = index 解除
     - 日付/週の個別ページは noindex 維持

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
     - forecast ハブ /forecast/ を収録・日付/エリア個別ページは非収録（T23・2026-07-03 反転）

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

  34. 全 docs/**/*.html（2026-05-21 追加）
     - href="/index.html" / href="../index.html" の出現が 0件
     - GitHub Pages Fastly CDN が / と /index.html を別キャッシュキーで管理し
       最大10分間表示がズレる現象への対策。サイト内導線から /index.html を完全排除

使用方法:
  python crawl/validate_output.py             # 全検証実行
  python crawl/validate_output.py --warn-only # warning のみ（失敗しない）

CI 組込: crawler.py の直後に呼び、非0終了時は git push をスキップ。
"""
import sys, os, json, re, csv, argparse, subprocess, collections, unicodedata
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


# --static-only（validate.yml = push 時の軽量チェック）で True になる。
# 「docs が今日再生成されているか」という**壁時計依存**の判定だけを warn に落とす。
#
# ⚠ これは gatekeeper の緩和ではない。crawl.yml は従来どおりフラグ無しで実行するので、
#   「生成した docs を push する直前」という鮮度が本当に意味を持つ文脈では
#   ブロッキングのまま。push 時の検証は docs が前回の日次生成のままなのが正常であり、
#   そこで鮮度を fail にすると「日次 run 前に push すると必ず落ちる」ノイズになり、
#   結果として閾値を緩める圧力になる（＝禁止事項に抵触する）ため分離した。
#   構造チェック（ネスト <a>・デッドリンク・欠損ファイル等）は静的モードでも全て fail。
STALENESS_IS_WARNING = False


def fail_staleness(msg):
    """壁時計依存の鮮度違反。静的モードでは warn に落ちる。構造違反には使わないこと。"""
    if STALENESS_IS_WARNING:
        warn(f"{msg} ※--static-only のため warn（鮮度は crawl.yml が判定）")
    else:
        fail(msg)


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
                "平年", "出船日和", "出船注意", "欠航警戒", "荒れ", "そよ風", "強風", "暴風", "好海況"
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

    # エリア別海況の多様性チェック（2026-08-01・エリア別予報導入 / 2026-08-05 改訂）。
    #
    # 検出したい事故: crawler.py の forecast_area 取得が全滅し、全 area ページが
    # グループ代表値（8グループ）にフォールバックすること。
    #
    # 旧実装は「先頭40ファイルの水温が8種類以下なら warn」だったが、2026-08-04 に
    # 誤検知した。理由は2つ:
    #   1. 先頭40ファイル（a〜h）は area_coords.json に載っていない＝そもそも
    #      グループ代表にフォールバックする設計のページが多数を占める
    #   2. 台風8/3の攪拌で沿岸水温が実際に均質化し 8種類まで縮んだ
    #      （同 run のログは「エリア別海況予報: 46/46座標 OK」＝取得は正常）
    # → 検査対象を area_coords.json に座標があるページに限定し、判定を水温単独から
    #   (水温, 波高, 風) の組に変える。水温が自然に均質化しても波・風まで
    #   一致することはない。全滅時は組の種類が最大8（グループ数）に落ちる。
    _ac_path = os.path.join(ROOT, "normalize", "area_coords.json")
    _rm_path = os.path.join(ROOT, "normalize", "area_romaji_map.json")
    try:
        with open(_ac_path, encoding="utf-8") as f:
            _area_coords = json.load(f)
        with open(_rm_path, encoding="utf-8") as f:
            _slug_to_area = {v: k for k, v in json.load(f).items()}
    except Exception as e:
        warn(f"[12] area_coords.json / area_romaji_map.json が読めず多様性チェック不可: {e}")
        return
    _sea_tuples = set()
    _sea_coords = set()
    _sea_ssts = set()
    _sea_pages = 0
    for fn in [f for f in os.listdir(area_dir) if f.endswith(".html") and f != "index.html"]:
        _area_name = _slug_to_area.get(fn[:-5])
        _coord = _area_coords.get(_area_name) if _area_name else None
        if not _coord or _coord.get("lat") is None or _coord.get("lon") is None:
            continue   # 座標が無い＝設計上グループ代表にフォールバックするページ
        c = open(os.path.join(area_dir, fn), encoding="utf-8").read()
        m_sst = re.search(r'<div class="sv">([\d.]+)℃</div><div class="sl2">水温</div>', c)
        if not m_sst:
            continue
        m_wave = re.search(r'<div class="sv">([\d.]+)m</div><div class="sl2">波高</div>', c)
        m_wind = re.search(r'<div class="sv">([^<]+)</div><div class="sl2">風</div>', c)
        _sea_pages += 1
        _sea_ssts.add(m_sst.group(1))
        _sea_tuples.add((m_sst.group(1),
                         m_wave.group(1) if m_wave else None,
                         m_wind.group(1) if m_wind else None))
        _sea_coords.add((_coord["lat"], _coord["lon"]))
    # 健全時は「組の種類 ≒ 座標の種類」（同一座標を共有するエリアは同値で正常）。
    # 全滅時は 8 以下に落ちる。座標数の 60% を下回ったら疑う。
    _min_tuples = max(9, int(len(_sea_coords) * 0.6))
    if _sea_pages >= 15 and len(_sea_tuples) < _min_tuples:
        warn(f"[12] area 海況（座標ありエリア {_sea_pages} ページ・座標 {len(_sea_coords)}種）の"
             f"(水温,波高,風) が {len(_sea_tuples)} 種類（下限 {_min_tuples}）"
             "＝エリア別予報が全滅しグループ代表にフォールバックしている疑い")
    elif _sea_pages >= 15:
        ok(f"[12] area 海況の多様性: 座標ありエリア {_sea_pages} ページ・"
           f"(水温,波高,風) {len(_sea_tuples)} 種類 / 座標 {len(_sea_coords)}種・"
           f"水温 {len(_sea_ssts)} 種類（エリア別が有効）")


_NESTED_A_TAG_RE = re.compile(r"<a\b[^>]*>|</a\s*>", re.IGNORECASE)
_NESTED_A_SKIP_RE = re.compile(r"<script\b.*?</script>|<!--.*?-->", re.DOTALL | re.IGNORECASE)


def _nested_anchor_scan(text, source):
    """depth を数えて最初のネスト位置のスニペットを返す。無ければ None。

    depth 方式なので `<a>`（属性なし）や `<b>` を跨ぐ交差ケースも捕まえる。
    オフセットは text と source で一致している前提（scrub は等長スペース置換）。
    """
    depth = 0
    for m in _NESTED_A_TAG_RE.finditer(text):
        if m.group(0).startswith("</"):
            depth = max(0, depth - 1)
            continue
        depth += 1
        if depth > 1:
            return source[max(0, m.start() - 60):m.start() + 60].replace("\n", " ")
    return None


def _nested_anchor_snippet(content):
    """ネスト <a> を検出したら 前後スニペット を返す。無ければ None。

    <script> 内の文字列と HTML コメントは走査対象外（誤検知防止）。ただし
    `<!--.*?-->` の DOTALL 走査は 1,900 ファイルで 80 秒級に効くため、
    **まず生の content を走査し、ヒットした場合のみ** scrub して再判定する
    （正常時はゼロコスト・違反時のみ精査）。scrub は等長スペース置換なので
    オフセットは content と一致する。
    """
    if _nested_anchor_scan(content, content) is None:
        return None
    scrubbed = _NESTED_A_SKIP_RE.sub(lambda m: " " * len(m.group(0)), content)
    return _nested_anchor_scan(scrubbed, content)


def validate_no_nested_anchors():
    """11: ネストした <a> タグ（HTML5 invalid）が無いか検証。docs 配下の全 HTML が対象。

    過去 area ページの fia カード内部に <a class="fia">...<div class="fb">◎<a>船宿</a></div></a>
    という構造があり、ブラウザが自動的に anchor を分離して「◎船宿名」が
    独立カードとして表示される事故が発生した。

    2026-07-30 拡張: 対象を area/fish/fish_area/ship の**先頭30ファイルのみ**から
    **docs 全体・全ファイル**へ広げ、正規表現の1発マッチから depth カウント方式に変更した。
    旧実装では x_post が対象外・かつ30件で打ち切りだったため、
    x_post 日次まとめの船宿名リンク化が作っていた
    <a href="…taiko-maru…">太<a href="…ko-maru…">幸丸</a></a>（部分文字列「幸丸」の再リンク）を
    4か月間検知できなかった。生成側は x_post/text_generator._linkify_ship_names で修復済み。
    """
    print("\n[11] ネストした <a> タグ検出（docs 全体）")
    targets = []
    for root, _dirs, files in os.walk(DOCS):
        for fn in files:
            if fn.endswith(".html"):
                targets.append(os.path.join(root, fn))
    if not targets:
        warn("検証対象 HTML が無い")
        return
    bad = []
    for path in sorted(targets):
        try:
            content = open(path, encoding="utf-8").read()
        except Exception:
            continue
        snippet = _nested_anchor_snippet(content)
        if snippet:
            bad.append((os.path.relpath(path, DOCS), snippet))
    if bad:
        for p, snippet in bad[:5]:
            fail(f"[11] {p}: ネストした <a> タグを検出 … {snippet}")
        if len(bad) > 5:
            fail(f"[11] ... 他 {len(bad)-5} ファイルも同問題")
    else:
        ok(f"[11] ネストアンカー: docs 配下 {len(targets)} ファイル全てクリア")


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
        fail_staleness(f"{ym}.csv 最新日付 {latest} が古すぎる（cutoff: {cutoff}）")
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
    """13: forecast ハブは index・日付/週/エリア個別ページは noindex（T23・2026-07-03 反転）

    背景: T22-H1 では forecast/index.html を含む全 forecast ページを noindex にしていた
    （実コンテンツ未整備のため）。T23 で D層予測が distilled_full（439コンボ）化し、
    ハブが「今週の海況＋魚種別予測」の実コンテンツになったためハブのみ index 解除。
    日付/週/エリアの個別ページは変動が激しく薄いため noindex 維持。
    検証:
      - forecast/index.html に noindex が **無い**（index 解除済み）
      - 日付ページ（YYYY-MM-DD.html）のサンプルは noindex が **残っている**
    """
    print("\n[13] forecast ハブ index 解除・日付ページ noindex 維持（T23）")
    fc_dir = os.path.join(DOCS, "forecast")
    path = os.path.join(fc_dir, "index.html")
    if not os.path.isfile(path):
        fail("forecast/index.html が存在しない")
        return
    content = open(path, encoding="utf-8").read()
    if 'name="robots"' in content and "noindex" in content:
        fail("forecast/index.html に noindex が残存（T23 でハブは index 解除すべき）")
    else:
        ok("forecast/index.html: noindex なし（index 解除済み）")
    # 日付/週の個別ページは noindex 維持を確認（サンプル・最大5件）
    import re as _re13
    dated = sorted(fn for fn in os.listdir(fc_dir)
                   if _re13.match(r"^(\d{4}-\d{2}-\d{2}|\d{4}-W\d+)\.html$", fn))
    checked = 0
    for fn in dated[:5]:
        c = open(os.path.join(fc_dir, fn), encoding="utf-8").read(2048)
        if 'name="robots"' in c and "noindex" in c:
            checked += 1
        else:
            fail(f"forecast/{fn}: noindex が無い（個別ページは noindex 維持すべき）")
    if dated:
        ok(f"[13] 日付/週ページ {checked}/{min(5, len(dated))} 件 noindex 維持を確認")


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


def validate_fish_area_noindex():
    """T39 (2026/05/25): 薄 fish_area ページが noindex 付与され
    かつ sitemap.xml から除外されていることを検証する。
    AdSense「有用性の低いコンテンツ」対策の動作確認。
    2026/06/16: hist_count しきい値を 30→80 に引上げ（薄判定対象を拡大）。"""
    print("\n[35] docs/fish_area/*.html noindex 付与 + sitemap 除外（T39）")
    fa_dir = os.path.join(DOCS, "fish_area")
    if not os.path.isdir(fa_dir):
        fail("docs/fish_area/ ディレクトリが存在しない")
        return
    files = [f for f in os.listdir(fa_dir) if f.endswith(".html") and f != "index.html"]
    noindex_slugs = set()
    for fn in files:
        content = open(os.path.join(fa_dir, fn), encoding="utf-8").read()
        if 'name="robots"' in content and "noindex" in content:
            noindex_slugs.add(fn[:-5])
    if len(noindex_slugs) < 10:
        fail(f"fish_area/*.html で noindex 付与ページが {len(noindex_slugs)} 件（最低 10 件・薄ページ判定が動作している証拠）")
        return
    # sitemap.xml で noindex 付与ページが含まれていないこと
    sitemap_path = os.path.join(DOCS, "sitemap.xml")
    if not os.path.isfile(sitemap_path):
        fail("sitemap.xml が存在しない")
        return
    sitemap_content = open(sitemap_path, encoding="utf-8").read()
    leaked = [s for s in noindex_slugs if f"/fish_area/{s}.html" in sitemap_content]
    if leaked:
        fail(f"sitemap.xml に noindex 付与 fish_area が {len(leaked)} 件混入: {leaked[:3]}...")
    else:
        ok(f"fish_area/*.html noindex 付与: {len(noindex_slugs)} 件 / 全 {len(files)} 件・sitemap 除外 OK")


def validate_no_ads_on_noindex():
    """2026/06/16 AdSense「有用性の低いコンテンツ」再対策: noindex を付与した薄ページ
    （fish_area hist<80 / forecast 全件 / 空 ship 等）に AdSense 広告コードが残っていない
    ことを検証する。「インデックスされないページは収益化しない」= AdSense が薄判定する
    広告掲載ページの母集団を縮小する施策の動作確認。
    crawler.py の広告ゲート（noindex 時に ADSENSE_TAG を出さない）と
    遡及 sweep の両方が効いている証拠。"""
    print("\n[47] noindex ページに AdSense 広告コードが無いこと（2026/06/16）")
    bad = []
    noindex_total = 0
    for root, _dirs, fnames in os.walk(DOCS):
        for fn in fnames:
            if not fn.endswith(".html"):
                continue
            path = os.path.join(root, fn)
            try:
                content = open(path, encoding="utf-8").read()
            except Exception:
                continue
            if 'name="robots"' in content and "noindex" in content:
                noindex_total += 1
                # CSS 定義（.ad-slot{} / ins.adsbygoogle{}）は無害なので除外し、
                # 実際にアドを読み込む loader script と ad ユニット要素のみを検出する。
                if ("pagead2.googlesyndication.com/pagead/js/adsbygoogle.js" in content
                        or '<ins class="adsbygoogle"' in content):
                    bad.append(os.path.relpath(path, DOCS))
    if bad:
        fail(f"noindex ページに広告コード残存 {len(bad)} 件: {bad[:5]}...")
    else:
        ok(f"noindex {noindex_total} ページすべて広告コードなし")


def validate_brand_not_h1():
    """2026/06/16 SEO: ヘッダのサイト名「船釣り予想」を <h1> にしない（ロゴは非見出し要素）。
    各ページの <h1> はそのページの主題であるべきで、ブランド名が全ページの H1 を占有すると
    トピックの伝達が弱まる。crawler.py（_v2_header_nav / ship ヘッダ / x_post / 静的 pages）で
    ブランドを <span class="brand"> に変更済み。本条件は全公開 HTML にブランド H1 が
    再混入していないことを担保する。"""
    print("\n[48] ヘッダのブランド名が <h1> でないこと（SEO・2026/06/16）")
    bad = []
    for root, _dirs, fnames in os.walk(DOCS):
        for fn in fnames:
            if not fn.endswith(".html"):
                continue
            path = os.path.join(root, fn)
            try:
                content = open(path, encoding="utf-8").read()
            except Exception:
                continue
            # <h1> 直下（任意で <a> 包含）にブランド「船釣り<span>予想」が来る形を検出
            if re.search(r'<h1[^>]*>\s*(<a[^>]*>)?\s*船釣り<span>予想', content):
                bad.append(os.path.relpath(path, DOCS))
    if bad:
        fail(f"ブランド名が <h1> のページ {len(bad)} 件（ロゴは span.brand にする）: {bad[:5]}...")
    else:
        ok("全公開 HTML でブランド名は <h1> ではない（各ページ H1 は主題）")


def validate_area_point_noindex():
    """T40 (2026/05/26): build_point_pages() 生成のポイント系 area ページが
    noindex 付与され、かつ sitemap.xml から除外されていることを検証する。
    AdSense「有用性の低いコンテンツ」対策（fia-grid/season-map を持たない構造的薄ページ）。"""
    print("\n[36] docs/area/*.html point ページ noindex 付与 + sitemap 除外（T40）")
    area_dir = os.path.join(DOCS, "area")
    if not os.path.isdir(area_dir):
        fail("docs/area/ ディレクトリが存在しない")
        return
    files = [f for f in os.listdir(area_dir) if f.endswith(".html") and f != "index.html"]
    noindex_slugs = set()
    for fn in files:
        content = open(os.path.join(area_dir, fn), encoding="utf-8").read(2048)
        if 'name="robots"' in content and "noindex" in content:
            noindex_slugs.add(fn[:-5])
    if len(noindex_slugs) < 5:
        fail(f"area/*.html で noindex 付与ページが {len(noindex_slugs)} 件（最低 5 件・ポイントページ判定が動作している証拠）")
        return
    # sitemap.xml で noindex 付与ページが含まれていないこと
    sitemap_path = os.path.join(DOCS, "sitemap.xml")
    if not os.path.isfile(sitemap_path):
        fail("sitemap.xml が存在しない")
        return
    sitemap_content = open(sitemap_path, encoding="utf-8").read()
    leaked = [s for s in noindex_slugs if f"/area/{s}.html" in sitemap_content]
    if leaked:
        fail(f"sitemap.xml に noindex 付与 area point ページが {len(leaked)} 件混入: {leaked[:3]}...")
    else:
        ok(f"area/*.html point noindex 付与: {len(noindex_slugs)} 件 / 全 {len(files)} 件・sitemap 除外 OK")


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
    """18: sitemap は forecast ハブのみ収録・日付ページは非収録（T23・2026-07-03 反転）

    背景: T22-H1 では forecast/ を sitemap から全除外していた。T23 でハブを index 解除した
    ため、sitemap には `/forecast/`（ハブ）のみを収録し、日付/週/エリアの個別ページ
    （noindex 維持）は収録しない。build_sitemap の forecast 走査は head の noindex 検出で
    ハブだけを拾う実装。
    検証:
      - sitemap に `<loc>…/forecast/</loc>`（ハブ）が 1 件存在
      - sitemap に日付ページ（forecast/YYYY-MM-DD.html）が 0 件
    """
    print("\n[18] sitemap は forecast ハブのみ収録・日付ページ非収録（T23）")
    path = os.path.join(DOCS, "sitemap.xml")
    if not os.path.isfile(path):
        fail("sitemap.xml が存在しない")
        return
    content = open(path, encoding="utf-8").read()
    import re as _re18
    hub = "/forecast/</loc>" in content
    dated_urls = _re18.findall(r"/forecast/\d{4}-(?:\d{2}-\d{2}|W\d+)\.html", content)
    area_urls = _re18.findall(r"/forecast/area/", content)
    if not hub:
        fail("sitemap.xml に forecast ハブ URL（/forecast/）が無い（T23 で収録すべき）")
    else:
        ok("sitemap.xml: forecast ハブ URL 収録済み")
    if dated_urls or area_urls:
        fail(f"sitemap.xml に forecast 個別ページが残存（日付{len(dated_urls)}・エリア{len(area_urls)}件・noindex 維持のため非収録すべき）")
    else:
        ok("sitemap.xml: forecast 日付/エリア個別ページ 0 件")


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


def validate_fish_index_phaseC():
    """30: fish/index.html の .idx-all-grid 内に .chip-link.chip-active が 1件以上存在
    （Phase C「魚種」セクションが全件展開され、今週実績ありの chip が出力されている）"""
    print("\n[30] fish/index.html - .idx-all-grid 内に .chip-link.chip-active（Phase C）")
    path = os.path.join(DOCS, "fish", "index.html")
    if not os.path.isfile(path):
        fail("fish/index.html が存在しない")
        return
    content = open(path, encoding="utf-8").read()
    # idx-all-grid セクション内を抽出
    m = re.search(r'class="idx-all-grid"(.*)', content, re.DOTALL)
    if not m:
        fail("fish/index.html: .idx-all-grid セクションが存在しない（Phase C「魚種」セクション未生成）")
        return
    idx_section = m.group(1)
    active_count = idx_section.count('class="chip-link chip-active"')
    if active_count < 1:
        fail(f"fish/index.html: .idx-all-grid 内に chip-active が {active_count} 件（1件以上必要）")
    else:
        ok(f"fish/index .idx-all-grid chip-active: {active_count} 件")


def validate_area_index_phaseC():
    """31: area/index.html の .idx-all-grid 内に .chip-link が 1件以上存在
    （Phase C「エリア」セクションが全件展開されている）"""
    print("\n[31] area/index.html - .idx-all-grid 内に .chip-link（Phase C）")
    path = os.path.join(DOCS, "area", "index.html")
    if not os.path.isfile(path):
        fail("area/index.html が存在しない")
        return
    content = open(path, encoding="utf-8").read()
    m = re.search(r'class="idx-all-grid"(.*)', content, re.DOTALL)
    if not m:
        fail("area/index.html: .idx-all-grid セクションが存在しない（Phase C「エリア」セクション未生成）")
        return
    idx_section = m.group(1)
    chip_count = idx_section.count('class="chip-link')
    if chip_count < 1:
        fail(f"area/index.html: .idx-all-grid 内に chip-link が {chip_count} 件（1件以上必要）")
    else:
        ok(f"area/index .idx-all-grid chip-link: {chip_count} 件")


def validate_area_index_pref_emoji():
    """32: area/index.html の <div class="ai-card"> 内に class="chip-pref" img が 1件以上存在
    （ai-card の直リンク化 + 県emoji 表示が動作している）"""
    print("\n[32] area/index.html - ai-card 内に chip-pref img（県emoji）")
    path = os.path.join(DOCS, "area", "index.html")
    if not os.path.isfile(path):
        fail("area/index.html が存在しない")
        return
    content = open(path, encoding="utf-8").read()
    # ai-card div の存在確認
    ai_card_count = content.count('<div class="ai-card">')
    if ai_card_count < 1:
        fail(f"area/index.html: <div class='ai-card'> が {ai_card_count} 件（旧 <a class='ai-card'> が残存している可能性）")
        return
    # chip-pref の存在確認（ai-grid 内）
    m = re.search(r'class="ai-grid"(.*?)(?=class="idx-all-grid"|</div>\s*</div>\s*{DATA_NOTE|$)', content, re.DOTALL)
    if m:
        ai_grid_section = m.group(1)
    else:
        ai_grid_section = content  # フォールバック: 全体を対象
    pref_count = ai_grid_section.count('class="chip-pref"')
    if pref_count < 1:
        fail(f"area/index.html: ai-card 内に chip-pref img が {pref_count} 件（県emoji 未出力）")
    else:
        ok(f"area/index ai-card chip-pref: {pref_count} 件")


def validate_area_index_fish_links():
    """33: area/index.html の <div class="ai-fish"> 内に <a href="../fish_area/..."> が 1件以上存在
    （ai-fish 内の魚種が fish_area 直リンク化されている）"""
    print("\n[33] area/index.html - ai-fish 内に fish_area 直リンク")
    path = os.path.join(DOCS, "area", "index.html")
    if not os.path.isfile(path):
        fail("area/index.html が存在しない")
        return
    content = open(path, encoding="utf-8").read()
    # ai-fish div ブロックを全て収集
    ai_fish_blocks = re.findall(r'<div class="ai-fish">(.*?)</div>', content, re.DOTALL)
    if not ai_fish_blocks:
        fail("area/index.html: ai-fish div が存在しない")
        return
    fish_link_count = sum(
        1 for block in ai_fish_blocks
        if re.search(r'href="../fish_area/', block)
    )
    if fish_link_count < 1:
        fail(f"area/index.html: ai-fish 内に fish_area リンクを持つブロックが {fish_link_count} 件（1件以上必要）")
    else:
        ok(f"area/index ai-fish fish_area links: {fish_link_count} ブロックに存在")


_HREF_INDEX_HTML_RE = re.compile(r'''href=["'][^"']*index\.html["']''')

def validate_no_index_html_internal_link():
    """34: 全 docs/**/*.html で href の値が "...index.html" で終わる内部リンクが 0件
    （GitHub Pages Fastly CDN の root + subdir 全レベルでキャッシュキー別問題対策・2026-05-21）

    背景:
    - / と /index.html、/forecast/ と /forecast/index.html 等、同じファイルを指す URL ペアは
      GitHub Pages Fastly CDN で別キャッシュキーとして管理され、Cache-Control: max-age=600
      のため最大10分間表示がズレる現象が確認された。
    - サイト内クリック導線から末尾 "index.html" 付き URL を完全排除して、ズレ遭遇経路を断つ。
    - 対象: ルートトップ / 全 subdir（forecast/ x_post/ fish/ area/ fish_area/ ship/ pages/
      komase-sim/ premium/ 等）の全レベル。
    """
    print("\n[34] 内部リンクの href 値末尾に index.html が残存していないこと")
    violating = []
    walked = 0
    for root, dirs, files in os.walk(DOCS):
        for f in files:
            if not f.endswith(".html"):
                continue
            walked += 1
            p = os.path.join(root, f)
            try:
                text = open(p, encoding="utf-8", errors="ignore").read()
            except Exception as e:
                fail(f"{os.path.relpath(p, DOCS)}: 読み込み失敗 {e}")
                continue
            matches = _HREF_INDEX_HTML_RE.findall(text)
            if matches:
                # 1ファイル先頭3件まで報告（複数種類混在のケースも見えるように）
                seen = []
                for m in matches:
                    if m not in seen:
                        seen.append(m)
                    if len(seen) >= 3:
                        break
                violating.append((os.path.relpath(p, DOCS), ", ".join(seen)))
    if violating:
        for relp, m in violating[:10]:
            fail(f"内部リンク index.html 残存: {relp} ({m})")
        if len(violating) > 10:
            fail(f"残存ファイル: あと {len(violating)-10} 件")
    else:
        ok(f"全 {walked} 個 docs/*.html で href の index.html 内部リンク消滅")


def validate_fish_guide_no_cross_contamination():
    """37: 魚種ガイド（docs/fish/*.html）の仕掛け説明に他魚種の道具混入が無いこと（2026-06-07）

    背景: fish_tackle.json の泳がせ系魚種で「キハダマグロ針」が一律テンプレ流用され、
    ヒラメページに『キハダマグロ針・ウキ・ウレタン』が表示される誤情報が発生した。
    マグロ専用の道具名がマグロ系以外の魚種ガイドに出たら誤情報として弾く。
    """
    print("\n[37] docs/fish/*.html: 仕掛け説明に他魚種の道具混入が無いこと")
    fish_dir = os.path.join(DOCS, "fish")
    if not os.path.isdir(fish_dir):
        fail("docs/fish/ ディレクトリが存在しない")
        return
    # マグロ専用語が出てよいのはマグロ系ページのみ
    tuna_slugs = {"kihadamaguro", "kimeji", "katsuo", "meji", "binnaga", "maguro"}
    forbidden = ["キハダマグロ針", "マグロ針"]
    violating = []
    checked = 0
    for fn in os.listdir(fish_dir):
        if not fn.endswith(".html") or fn == "index.html":
            continue
        slug = fn[:-5]
        if slug in tuna_slugs:
            continue
        checked += 1
        content = open(os.path.join(fish_dir, fn), encoding="utf-8").read()
        hit = [w for w in forbidden if w in content]
        # ヒラメ系（フラットフィッシュ）ページにウキ釣り混入も誤り
        if slug == "hirame" and "ウキ（状況で可変）" in content:
            hit.append("ウキ（状況で可変）")
        if hit:
            violating.append(f"{fn}: {', '.join(hit)}")
    if violating:
        for v in violating[:10]:
            fail(f"[37] 魚種ガイドに他魚種の道具混入: {v}")
    else:
        ok(f"[37] fish ガイド {checked} 件すべて他魚種道具の混入なし")


# 「最高N匹」「最大匹数 N匹」「平均N匹」「平均X〜N匹」等、釣果数を表す表現を網羅。
# 数字とのあいだに <strong> 等のタグが挟まるケース（ship ページ）も拾う。
# 値は float もありうる（平均507.2匹）ので小数を許容して捕捉する。
_IMPLAUSIBLE_CNT_RES = [
    re.compile(r"最高(?:実績は)?\s*([\d.]+)\s*匹"),
    re.compile(r"最大匹数\s*(?:<[^>]+>)*\s*([\d.]+)\s*匹"),
    re.compile(r"平均(?:釣果)?\s*(?:<[^>]+>)*\s*(?:[\d.]+\s*〜\s*)?([\d.]+)\s*匹"),
]


def validate_implausible_catch_count():
    """38: fish/fish_area/ship ページの釣果数表示が非現実値でないこと（2026-06-07）

    背景: 釣果数の数値抽出で西暦（例: ヒラメ「2025匹」）や桁化けが混入する事故があった。
    fish/fish_area の「最高N匹」だけでなく、ship ページの「最大匹数 N匹」も公開生成物
    なので対象に含める（PR#51 レビュー指摘・docs/ship/riki-maru.html で 2025匹 が残存）。
    実在の最大は数物（アジ713・スジイカ702）でも 1000 未満。よって
    - N が西暦域 [1990, 2035] の整数
    - または N > 1500
    を非現実値として弾く（crawler.py の _FISH_CNT_CAP による除外が効いている証拠）。
    """
    print("\n[38] fish/fish_area/ship ページの釣果数が非現実値でないこと")
    targets = []
    for sub in ("fish", "fish_area", "ship"):
        d = os.path.join(DOCS, sub)
        if os.path.isdir(d):
            for fn in os.listdir(d):
                if fn.endswith(".html") and fn != "index.html":
                    targets.append(os.path.join(d, fn))
    if not targets:
        fail("[38] fish/fish_area/ship ページが存在しない")
        return
    violating = []
    for p in targets:
        content = open(p, encoding="utf-8").read()
        found = None
        for rgx in _IMPLAUSIBLE_CNT_RES:
            for m in rgx.finditer(content):
                try:
                    fv = float(m.group(1))
                except ValueError:
                    continue
                n = int(fv)
                if (1990 <= n <= 2035) or fv > 1500:
                    found = m.group(1)
                    break
            if found is not None:
                break
        if found is not None:
            violating.append(f"{os.path.relpath(p, DOCS)}: {found}匹")
    if violating:
        for v in violating[:10]:
            fail(f"[38] 非現実的な釣果数: {v}")
        if len(violating) > 10:
            fail(f"[38] 他 {len(violating)-10} 件")
    else:
        ok(f"[38] {len(targets)} ページすべて釣果数は現実的な範囲")


_UPDATED_DATE_RE = re.compile(r"最終更新:\s*(\d{4})/(\d{2})/(\d{2})")
_BANNER_BUILD_RE = re.compile(r'id="stale-banner".*?var b="(\d{4})-(\d{2})-(\d{2})"', re.DOTALL)


def validate_page_freshness():
    """39: 生成ページの鮮度（更新遅延・ページ種別ごとの更新分裂を検知）（2026-06-07）

    背景: トップ/魚種/魚種×エリア/船宿 ページで「表示対象日」がバラつく事故への対策
    （PR レビュー指摘）。
    - index.html の「最終更新: YYYY/MM/DD」が today-2 以内であること（生成停止の検知）。
    - 全ページ共通ヘッダのビルド日付バナー（var b="YYYY-MM-DD"）が today-2 以内である
      こと（ページ種別ごとの再生成漏れ＝更新分裂の検知）。バナー未導入の旧 docs では
      該当行が無いため skip（次回再生成後に有効化）。
    TZ ずれ・cron 遅延を考慮し許容は today-2 日。
    """
    print("\n[39] 生成ページの鮮度（更新遅延・ページ種別の更新分裂）")
    today = datetime.now()
    cutoff = today - timedelta(days=2)

    # (1) index.html の最終更新
    idx = os.path.join(DOCS, "index.html")
    if os.path.isfile(idx):
        content = open(idx, encoding="utf-8").read()
        m = _UPDATED_DATE_RE.search(content)
        if not m:
            warn("[39] index.html に『最終更新: YYYY/MM/DD』が見つからない")
        else:
            d = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            if d < cutoff:
                fail_staleness(f"[39] index.html 最終更新 {d.date()} が古い（cutoff {cutoff.date()}）= トップの更新遅延")
            else:
                ok(f"[39] index.html 最終更新: {d.date()}")
    else:
        fail("[39] index.html が存在しない")

    # (2) ページ種別ごとのビルド日付バナー（更新分裂の検知）
    samples = [
        ("index", "index.html"),
        ("fish", "madai.html"), ("fish", "aji.html"), ("fish", "hirame.html"),
        ("fish_area", "aji-yokohama-honmoku.html"),
        ("area", "kanazawa-hakkei.html"),
        ("ship", "riki-maru.html"),
    ]
    stale = []
    checked = 0
    for sub, fn in samples:
        p = idx if sub == "index" else os.path.join(DOCS, sub, fn)
        if not os.path.isfile(p):
            continue
        content = open(p, encoding="utf-8").read()
        bm = _BANNER_BUILD_RE.search(content)
        if not bm:
            continue  # バナー未導入の旧 docs は skip（次回再生成後に有効化）
        checked += 1
        d = datetime(int(bm.group(1)), int(bm.group(2)), int(bm.group(3)))
        if d < cutoff:
            rel = "index.html" if sub == "index" else f"{sub}/{fn}"
            stale.append(f"{rel}: 生成日 {d.date()}")
    if stale:
        for s in stale:
            fail_staleness(f"[39] ページ更新分裂（生成日が古い）: {s}")
    elif checked:
        ok(f"[39] ビルド日付バナー {checked} ページすべて today-2 以内")
    else:
        warn("[39] ビルド日付バナー未検出（旧 docs・次回再生成で有効化）")


def validate_favicon():
    """40: favicon 配信の検証（2026-06-10）

    - docs/favicon.ico と docs/apple-touch-icon.png が存在すること
      （既存画像流用: フグ emoji → favicon.ico / アオリイカ illustration → apple-touch-icon）。
    - 主要ページ（index / calendar / fish / area / fish_area / ship / forecast / pages）に
      rel="icon" リンクタグが存在すること（crawler.py の全 head テンプレート 15 箇所に
      挿入済み。テンプレート追加・改修時の favicon 落ちを検知）。
    """
    print("\n[40] favicon（ブラウザタブ・ブックマーク・Google SERP アイコン）")
    for fn in ("favicon.ico", "apple-touch-icon.png"):
        p = os.path.join(DOCS, fn)
        if not os.path.exists(p) or os.path.getsize(p) == 0:
            fail(f"[40] docs/{fn} が存在しない（または 0 byte）")
            return
    samples = [
        "index.html", "calendar.html",
        os.path.join("fish", "index.html"), os.path.join("area", "index.html"),
        os.path.join("forecast", "index.html"), os.path.join("pages", "faq.html"),
    ]
    for sub in ("fish", "area", "fish_area", "ship"):
        d = os.path.join(DOCS, sub)
        if os.path.isdir(d):
            htmls = sorted(f for f in os.listdir(d) if f.endswith(".html") and f != "index.html")
            if htmls:
                samples.append(os.path.join(sub, htmls[0]))
    missing = []
    checked = 0
    for rel in samples:
        p = os.path.join(DOCS, rel)
        if not os.path.exists(p):
            continue
        checked += 1
        content = open(p, encoding="utf-8", errors="replace").read()
        if 'rel="icon"' not in content.split("</head>", 1)[0]:
            missing.append(rel)
    if missing:
        for m in missing:
            fail(f"[40] rel=\"icon\" タグ欠落: {m}")
    else:
        ok(f"[40] favicon ファイル 2 件 + サンプル {checked} ページすべてにタグあり")


def validate_no_null_fish_display():
    """41: 魚種名「NULL」が公開ページに露出していないこと（2026-06-10）

    背景: chowari 系 CSV の tsuri_mono に文字列 "NULL"（正規化失敗の sentinel）が
    4,477 行あり、area ページの fia-grid / 旬カレンダー / meta description / FAQ に
    魚種「NULL」として露出した。crawler.py は読み込み時に "NULL"→"不明" 正規化 +
    各表示系 skip set に "NULL" を追加して対策済み。本チェックは再発を検知する。
    """
    print("\n[41] 魚種名 NULL の露出（正規化失敗 sentinel の表示漏れ）")
    bad = []
    for sub in ("", "area", "fish", "fish_area", "ship"):
        d = os.path.join(DOCS, sub) if sub else DOCS
        if not os.path.isdir(d):
            continue
        for fn in sorted(os.listdir(d)):
            if not fn.endswith(".html"):
                continue
            p = os.path.join(d, fn)
            if not os.path.isfile(p):
                continue
            content = open(p, encoding="utf-8", errors="replace").read()
            # 「>NULL<」（要素テキスト）・「NULL（」（FAQ/description 文中）・
            # alt="NULL"・assets/fish/NULL/ のいずれかで検知
            if (">NULL<" in content or "NULL（" in content
                    or 'alt="NULL"' in content or "assets/fish/NULL/" in content):
                rel = f"{sub}/{fn}" if sub else fn
                bad.append(rel)
    if bad:
        for b in bad[:10]:
            fail(f"[41] 魚種名 NULL が露出: {b}")
        if len(bad) > 10:
            fail(f"[41] 他 {len(bad)-10} 件")
    else:
        ok("[41] 公開ページに NULL 露出なし")


def validate_ship_slug_uniqueness():
    """42: 船宿 romaji_slug の一意性 + sitemap URL 重複なし（2026-06-10）

    背景: 弘漁丸と孝漁丸が両方 romaji_slug="koryo-maru" で docs/ship/koryo-maru.html
    を相互上書きし、片方の船宿ページが消失 + sitemap に同一 URL が重複していた。
    """
    print("\n[42] 船宿 slug 一意性・sitemap URL 重複")
    import json as _json
    from collections import Counter as _Counter
    ships_path = os.path.join(ROOT, "crawl", "ships.json")
    try:
        ships = _json.load(open(ships_path, encoding="utf-8"))
    except Exception as e:
        fail(f"[42] ships.json 読み込み失敗: {e}")
        return
    slugs = _Counter(s.get("romaji_slug") for s in ships if s.get("romaji_slug"))
    dups = {k: v for k, v in slugs.items() if v > 1}
    if dups:
        for k, v in dups.items():
            names = [s.get("name") for s in ships if s.get("romaji_slug") == k]
            fail(f"[42] romaji_slug 重複: {k} x{v} {names}（ship ページ相互上書き）")
    else:
        ok(f"[42] ships.json romaji_slug {len(slugs)} 件すべて一意")
    sm_path = os.path.join(DOCS, "sitemap.xml")
    if os.path.exists(sm_path):
        locs = re.findall(r"<loc>([^<]+)</loc>", open(sm_path, encoding="utf-8").read())
        loc_dups = {k: v for k, v in _Counter(locs).items() if v > 1}
        if loc_dups:
            for k, v in list(loc_dups.items())[:5]:
                fail(f"[42] sitemap URL 重複: {k} x{v}")
        else:
            ok(f"[42] sitemap.xml {len(locs)} URL 重複なし")


def validate_tel_links():
    """43: tel: リンクの電話番号が単一の有効長であること（2026-06-10）

    背景: ships.json の phone「0463-21-1312 / 070-4486-7173」等の複数番号文字列を
    区切り文字ごと数字化して連結し、23 船宿ページで無効な tel: リンクになっていた。
    crawler.py は _first_phone_for_tel() で先頭 1 番号のみを使うよう修正済み。
    日本の電話番号は最大 11 桁（国際形式 +81 でも 12 桁以内）。
    """
    print("\n[43] tel: リンクの電話番号長")
    bad = []
    ship_dir = os.path.join(DOCS, "ship")
    if os.path.isdir(ship_dir):
        for fn in sorted(os.listdir(ship_dir)):
            if not fn.endswith(".html"):
                continue
            content = open(os.path.join(ship_dir, fn), encoding="utf-8", errors="replace").read()
            for m in re.finditer(r'href="tel:([^"]+)"', content):
                digits = re.sub(r"\D", "", m.group(1))
                # 13 桁以上 = 確実に複数番号の連結（日本の番号は最大 11 桁・+81 国際形式
                # でも 12 桁）。12 桁以下に収まる短番号同士の連結は理論上見逃すが、
                # 実データの番号は 10〜11 桁のため 2 番号連結は必ず 13 桁を超える。
                if len(digits) > 12:
                    bad.append(f"ship/{fn}: tel:{m.group(1)}")
                    break
    if bad:
        for b in bad[:10]:
            fail(f"[43] 連結電話番号の tel: リンク: {b}")
        if len(bad) > 10:
            fail(f"[43] 他 {len(bad)-10} 件")
    else:
        ok("[43] ship ページの tel: リンクすべて有効長")


def validate_no_dead_internal_links():
    """44: fish/ fish_area/ ship/ への内部リンクが実在ファイルを指すこと（2026-06-10）

    背景: build_fish_area_pages の孤児パージが fish_area HTML を削除しても、
    リンク元の stale ページ（直近 7 日に釣果が無いと再生成されない）が残り
    デッドリンク化していた（244 ターゲット・550 参照）。crawler.py は生成完了後に
    _sweep_dead_internal_links() で毎回 unlink する。本チェックは掃引漏れを検知する。
    """
    print("\n[44] fish/fish_area/ship への内部デッドリンク")
    from urllib.parse import unquote as _unquote
    dir_files = {}
    for sub in ("fish", "fish_area", "ship"):
        d = os.path.join(DOCS, sub)
        dir_files[sub] = (
            {f for f in os.listdir(d) if f.endswith(".html")} if os.path.isdir(d) else set()
        )
    # プレフィックス（../ 連続 or /）は省略可能なので bare 相対リンク（"fish/..."）も
    # 本パターン1本でカバーする（code-reviewer 指摘で重複パターンを削除 2026-06-10）
    href_re = re.compile(
        r'href=(["\'])(?:(?:\.\./)+|/)?(fish|fish_area|ship)/([^"\'/#?]+\.html)\1'
    )
    dead = []
    checked = 0
    for root, _dirs, files in os.walk(DOCS):
        for fn in files:
            if not fn.endswith(".html"):
                continue
            p = os.path.join(root, fn)
            content = open(p, encoding="utf-8", errors="replace").read()
            checked += 1
            rel = os.path.relpath(p, DOCS)
            for m in href_re.finditer(content):
                _q, kind, fname = m.groups()
                if _unquote(fname) not in dir_files[kind]:
                    dead.append(f"{rel} -> {kind}/{fname}")
    dead = sorted(set(dead))
    if dead:
        for d_ in dead[:10]:
            fail(f"[44] デッドリンク: {d_}")
        if len(dead) > 10:
            fail(f"[44] 他 {len(dead)-10} 件")
    else:
        ok(f"[44] {checked} ページの fish/fish_area/ship リンクすべて実在")


def validate_no_mass_page_deletion():
    """59: 公開済み HTML が一度に大量削除されていないこと（T49・2026-07-31）

    背景: GSC「見つかりませんでした(404)」287件を調査したところ、fish_area は
    2,141本中 573本(26.8%) が削除→再追加を繰り返していた（2026-05 だけで 1,268本削除）。
    URL が 404 と 200 を往復すると Google はその URL 空間のクロール優先度を落とし、
    実在ページ 118本が「検出 - インデックス未登録」のまま一度もクロールされない状態を招いた。

    crawler.py 側は孤児を削除せず noindex 墓標にする方式へ変更済み（T49）だが、
    hist_rows の部分ロード（data/V2 CSV の truncate・CI 途中失敗）で大量削除が
    再発しうるため、push 前に HEAD と比較して検知する。

    保証すること: HEAD からの HTML 削除数が、各ディレクトリの現存数の 5%
    （最低 30 本）を超えないこと。意図的な大量削除時は --allow-mass-deletion で解除。
    """
    print("\n[59] 公開 HTML の大量削除ガード（T49・2026-07-31）")

    if "--allow-mass-deletion" in sys.argv:
        ok("[59] --allow-mass-deletion 指定のため skip（意図的な大量削除）")
        return

    try:
        out = subprocess.run(
            ["git", "diff", "--diff-filter=D", "--name-only", "HEAD", "--", "docs"],
            cwd=ROOT, capture_output=True, text=True, timeout=60,
        )
    except Exception as e:
        warn(f"[59] git 実行失敗のため skip: {e}")
        return
    if out.returncode != 0:
        warn(f"[59] git diff 失敗のため skip: {(out.stderr or '').strip()[:200]}")
        return

    deleted = collections.Counter()
    for line in out.stdout.splitlines():
        line = line.strip()
        if not line.endswith(".html"):
            continue
        parts = line.split("/")
        # docs/<sub>/<name>.html → <sub>、docs/<name>.html → "(root)"
        deleted[parts[1] if len(parts) >= 3 else "(root)"] += 1

    if not deleted:
        ok("[59] HEAD からの HTML 削除なし")
        return

    RATIO, ABS_MIN = 0.05, 30
    flagged = False
    for sub, n in sorted(deleted.items(), key=lambda x: -x[1]):
        d = DOCS if sub == "(root)" else os.path.join(DOCS, sub)
        alive = len([f for f in os.listdir(d) if f.endswith(".html")]) if os.path.isdir(d) else 0
        cap = max(ABS_MIN, int(alive * RATIO))
        if n > cap:
            flagged = True
            fail(f"[59] docs/{sub}: {n} 本削除（現存 {alive} 本・上限 {cap} 本）。"
                 f"data/V2 CSV の欠損や hist_rows 部分ロードを疑うこと。"
                 f"意図的なら --allow-mass-deletion")
        else:
            ok(f"[59] docs/{sub}: {n} 本削除（上限 {cap} 本以内）")
    if not flagged:
        ok(f"[59] 削除 {sum(deleted.values())} 本すべて上限内")


def validate_fish_content_sections():
    """45: fish_content.json 収載魚種の固定文セクションが描画されていること（2026-06-11）

    背景: 魚種ページ固定文プロジェクト。normalize/fish_content.json（固定文・月1見直し）+
    fish_content_stats.json（数値スナップショット・月1更新）から crawler.py が
    釣り方/タックル補足/シーズン/エリア/食味/初心者向けのプローズを差し込む。
    検証:
      - 収載魚種のページに class="fish-content-text" ブロックが 4 つ以上
      - 固定文の合計テキストが 800 字以上（AdSense 薄判定対策の本旨）
      - 未解決プレースホルダ（{xxx}）が本文に残っていない
    """
    print("\n[45] fish_content.json 収載魚種の固定文セクション")
    content_path = os.path.join(ROOT, "normalize", "fish_content.json")
    if not os.path.exists(content_path):
        ok("[45] fish_content.json なし（固定文未導入）→ skip")
        return
    try:
        with open(content_path, encoding="utf-8") as f:
            content = json.load(f)
    except Exception as e:
        fail(f"[45] fish_content.json 読み込み失敗: {e}")
        return
    fishes = [k for k in content.keys() if not k.startswith("_")]
    if not fishes:
        ok("[45] fish_content.json 収載魚種 0 件 → skip")
        return
    fish_dir = os.path.join(DOCS, "fish")
    pages = {}
    for fn in os.listdir(fish_dir):
        if fn.endswith(".html") and fn != "index.html":
            pages[fn] = open(os.path.join(fish_dir, fn), encoding="utf-8").read()
    ph_re = re.compile(r"\{[a-z][a-z0-9_]*\}")
    text_re = re.compile(
        r'class="[^"]*fish-content-text[^"]*"[^>]*>(.*?)</(?:span|p)>', re.S
    )
    for fish in fishes:
        # ページ特定: h1 に魚種名を含むファイル
        page = None
        marker = f'<h1 class="page-h1">{fish}の船釣り釣果情報'
        for fn, c in pages.items():
            if marker in c:
                page = fn
                break
        if page is None:
            fail(f"[45] {fish}: 対応する fish ページが見つからない")
            continue
        c = pages[page]
        blocks = text_re.findall(c)
        if len(blocks) < 4:
            fail(f"[45] {fish} ({page}): fish-content-text ブロックが {len(blocks)} 個（4 個以上必要）")
            continue
        plain = re.sub(r"<[^>]+>", "", "".join(blocks))
        if len(plain) < 800:
            fail(f"[45] {fish} ({page}): 固定文合計 {len(plain)} 字（800 字以上必要）")
            continue
        leftover = ph_re.findall(plain)
        if leftover:
            fail(f"[45] {fish} ({page}): 未解決プレースホルダ {leftover[:3]}")
            continue
        ok(f"[45] {fish} ({page}): 固定文 {len(blocks)} ブロック・{len(plain)} 字・プレースホルダ解決済み")


def validate_xpost_no_operator_drafts():
    """46: docs/x_post/*.html に運営者専用の X 投稿文ドラフトが公開されていないこと（2026-06-13）

    背景: build_daily_page.py が「X投稿文（コピー用・発見型）」ブロック（下書きツイート＋
    投稿時刻・リーチ戦略の運用メモ）を公開 HTML に埋め込み、funatsuri-yoso.com 上で
    一般公開されていた不具合。運営者専用ドラフトは x_post/drafts/（GitHub Pages 非配信・
    .gitignore）にのみ出力し、公開ページには絶対に含めない。
    検証: 公開 x_post HTML に下記マーカーが 1 つでも出たら fail。
    """
    print("\n[46] x_post 公開ページに運営者ドラフトが混入していないこと")
    xpost_dir = os.path.join(DOCS, "x_post")
    if not os.path.isdir(xpost_dir):
        ok("[46] docs/x_post なし → skip")
        return
    forbidden = [
        "X投稿文", "x-drafts", "コピー用・発見型", "翌朝8時投稿想定",
        "リーチを抑制", "リンクあり版で誘導", "リンクなしをコピー", "xd-copy",
    ]
    hit = []
    for fn in os.listdir(xpost_dir):
        if not fn.endswith(".html"):
            continue
        p = os.path.join(xpost_dir, fn)
        content = open(p, encoding="utf-8", errors="replace").read()
        found = [m for m in forbidden if m in content]
        if found:
            hit.append((fn, found))
    if hit:
        for fn, found in hit[:5]:
            fail(f"[46] {fn} に運営者ドラフトのマーカーが公開されている: {found}")
        if len(hit) > 5:
            fail(f"[46] ほか {len(hit) - 5} ファイルにも混入")
    else:
        ok(f"[46] x_post 公開ページに運営者ドラフトの混入なし（{xpost_dir}）")


def validate_chowari_monthly_coverage():
    """2026/07/03: chowari 月次 CSV の「直近7日窓化」regression 検知。
    chowari_crawler は per-ship raw JSON を直近7日窓で全上書きするため、旧 chowari_to_csv
    （全上書き方式）は月が経過すると月初〜中旬の蓄積行を毎日破壊していた
    （実害: 2026-06 が月末に 475行/6日分に縮小・2026-03〜06 で計 16,482 行を git 履歴から復元）。
    chowari_to_csv は 2026-07-03 に既存 CSV との dedup union 方式に修正済み。
    本条件は「完了した直近月の chowari CSV が月の広い範囲をカバーしていること」を検証し、
    全上書き方式への退行を検知する。"""
    print("\n[49] chowari 月次 CSV の窓化（蓄積行の消失）検知（2026/07/03）")
    import csv as _csv
    from datetime import date as _date, timedelta as _td
    data_dir = os.path.join(ROOT, "data", "V2")
    today = _date.today()
    # 直近の「完了した」2か月分を対象（当月は蓄積途中なので対象外）
    targets = []
    y, m = today.year, today.month
    for _ in range(2):
        m -= 1
        if m == 0:
            y, m = y - 1, 12
        targets.append(f"{y:04d}-{m:02d}")
    bad = []
    checked = 0
    for ym in targets:
        p = os.path.join(data_dir, f"chowari_{ym}.csv")
        if not os.path.isfile(p):
            continue
        with open(p, encoding="utf-8", newline="") as f:
            dates = {r.get("date", "") for r in _csv.DictReader(f) if r.get("date")}
        n_dates = len(dates)
        min_day = min((int(d[8:10]) for d in dates if len(d) >= 10), default=99)
        checked += 1
        # 200行以上の月で「日付が15日未満 or 月初(5日以内)のデータが無い」= 窓化の兆候
        with open(p, encoding="utf-8", newline="") as f:
            n_rows = sum(1 for _ in f) - 1
        if n_rows >= 200 and (n_dates < 15 or min_day > 5):
            bad.append(f"{ym}: {n_rows}行 / 日付{n_dates}種 / 最小日={min_day}")
    if bad:
        fail(f"chowari 月次 CSV が窓化している疑い（全上書き方式への退行）: {bad}")
    elif checked == 0:
        warn("chowari 直近完了月の CSV が見つからない（対象なし）")
    else:
        ok(f"chowari 直近完了 {checked} か月分のカバレッジ正常（窓化なし）")


def validate_fish_area_analysis_sections():
    """50: fish_area/ship の C層蒸留『海況と釣期の傾向（データ分析）』の整合（T43・2026-07-03）

    背景: normalize/fish_area_analysis.json / ship_analysis.json（build_fish_area_analysis.py が
    analysis.sqlite から蒸留・コミット）を crawler.py が読み、fish_area/ship に海況相関・釣期・
    予測精度の独自集約セクションを描画する。複数船宿分析を持つ薄hist ページは index 復帰。
    検証（過大表現＝AdSense/信頼リスクの防止が主眼）:
      - 蒸留 JSON が存在し 1件以上
      - fish_area で分析セクション（見出し『海況と釣期の傾向（データ分析）』）が一定数レンダされている
      - 分析セクションを持つページは必ず免責注記（『釣果を保証するものではありません』＋
        『この海域のデータに基づく』）を含む（過大表現ガード）
      - 禁止表現（『必ず釣れ』『確実に釣れ』）が分析セクション近傍に出ない
    """
    print("\n[50] fish_area/ship C層蒸留セクションの整合（T43）")
    fa_json = os.path.join(ROOT, "normalize", "fish_area_analysis.json")
    if not os.path.isfile(fa_json):
        ok("[50] fish_area_analysis.json なし → skip（蒸留未導入）")
        return
    try:
        with open(fa_json, encoding="utf-8") as f:
            fa_data = json.load(f)
    except Exception as e:
        fail(f"[50] fish_area_analysis.json 読み込み失敗: {e}")
        return
    if not fa_data:
        ok("[50] fish_area_analysis.json 収載 0 件 → skip")
        return

    MARK = "海況と釣期の傾向（データ分析）"
    DISC1 = "釣果を保証するものではありません"
    DISC2 = "この海域のデータに基づく"
    FORBIDDEN = ["必ず釣れ", "確実に釣れ", "絶対に釣れ"]
    fa_dir = os.path.join(DOCS, "fish_area")
    rendered = 0
    missing_disc = []
    forbidden_hit = []
    if os.path.isdir(fa_dir):
        for fn in os.listdir(fa_dir):
            if not fn.endswith(".html"):
                continue
            c = open(os.path.join(fa_dir, fn), encoding="utf-8").read()
            if MARK not in c:
                continue
            rendered += 1
            if DISC1 not in c or DISC2 not in c:
                missing_disc.append(fn)
            if any(fb in c for fb in FORBIDDEN):
                forbidden_hit.append(fn)
    # レンダ件数はデータ次第だが、蒸留 JSON が十分ある場合は最低限描画されているはず
    expect_min = min(30, max(1, len(fa_data) // 6))
    if rendered < expect_min:
        fail(f"[50] fish_area 分析セクションのレンダが {rendered} 件（>= {expect_min} 期待・蒸留JSON {len(fa_data)}件）")
    else:
        ok(f"[50] fish_area 分析セクション {rendered} 件レンダ（蒸留JSON {len(fa_data)}件）")
    if missing_disc:
        fail(f"[50] 分析セクションに免責注記が欠落（過大表現リスク）: {missing_disc[:5]}（計{len(missing_disc)}）")
    else:
        ok("[50] 分析セクション全件に免責注記あり")
    if forbidden_hit:
        fail(f"[50] 分析ページに禁止表現（断定的な釣果保証）: {forbidden_hit[:5]}")
    else:
        ok("[50] 禁止表現なし")

    # ── 57: 旬ピークの母数・定義（2026-07-27）──────────────────────────
    # 旬ピークに母数下限が無く、278便中10便の旬が「釣果が伸びやすい時期」として採用され、
    # 同一ページ FAQ の月別ピーク（件数ベース）と食い違って見えていた。
    # 蒸留側に母数下限を入れ、表示側で母数と定義の違いを必ず出す。
    MIN_ABS, FRAC = 12, 0.05
    bad_n, peak_pairs = [], 0
    for k, v in fa_data.items():
        peaks = v.get("peaks") or []
        if not peaks:
            continue
        peak_pairs += 1
        total = sum(b.get("n") or 0 for b in (v.get("busy_months") or [])) or v.get("n_records") or 0
        floor = max(MIN_ABS, int(total * FRAC)) if total else MIN_ABS
        for p in peaks:
            if not isinstance(p, dict):
                bad_n.append(f"{k}(旧スキーマ)")
                break
            if (p.get("n") or 0) < MIN_ABS:
                bad_n.append(f'{k}:{p.get("label")}(n={p.get("n")}<{MIN_ABS})')
                break
    if bad_n:
        fail(f"[57] 旬ピークが母数下限({MIN_ABS}便)未満 or 母数なし: {bad_n[:5]}（計{len(bad_n)}）")
    else:
        ok(f"[57] 旬ピーク {peak_pairs} ペアすべて母数下限を満たし母数付き")

    # 表示側: ピークを出しているページは「別の指標である」旨と母数を必ず併記
    PEAK_MARK = "1便あたりの釣果が多かった旬"
    DEF_MARK = "この2つは別の指標です"
    no_def = []
    peak_pages = 0
    if os.path.isdir(fa_dir):
        for fn in os.listdir(fa_dir):
            if not fn.endswith(".html"):
                continue
            c = open(os.path.join(fa_dir, fn), encoding="utf-8").read()
            if PEAK_MARK not in c:
                continue
            peak_pages += 1
            if DEF_MARK not in c or "便・平均" not in c:
                no_def.append(fn)
    if peak_pages == 0:
        ok("[57] 旬ピーク描画ページなし（docs 未再生成）→ skip")
    elif no_def:
        fail(f"[57] 旬ピークに定義説明/母数が欠落: {no_def[:5]}（計{len(no_def)}）")
    else:
        ok(f"[57] 旬ピーク描画 {peak_pages} 件すべてに定義説明+母数あり")

    # ── 58: 一次体験レポートの出典（2026-07-27）────────────────────────
    # AdSense 診断で Experience=NG。運営者本人の一次記録を載せる器（field_reports.json）。
    # 出典（執筆者・実施日）が無い体験談は「体験を装った文章」になるので描画させない。
    fr_path = os.path.join(ROOT, "normalize", "field_reports.json")
    reports = {}
    if os.path.exists(fr_path):
        try:
            with open(fr_path, encoding="utf-8") as f:
                reports = json.load(f).get("reports", {}) or {}
        except Exception as e:
            fail(f"[58] field_reports.json 読み込み失敗: {e}")
    missing_src = []
    n_reports = 0
    # 日本語本文に混ざってはいけない文字体系（キリル・ギリシャ・ハングル）。
    # 執筆支援中に「замена」「как」等が実際に紛れ込んだため機械検知する。
    FOREIGN = re.compile(r"[Ѐ-ӿͰ-Ͽ가-힯]")
    foreign_hit = []
    for k, entries in reports.items():
        for e in (entries if isinstance(entries, list) else [entries]):
            n_reports += 1
            if not (e.get("author") or "").strip() or not (e.get("date") or "").strip() \
                    or not (e.get("html") or "").strip():
                missing_src.append(k)
            blob = (e.get("html") or "") + " ".join(e.get("takeaways") or []) + (e.get("title") or "")
            m = FOREIGN.search(blob)
            if m:
                foreign_hit.append(f"{k}:{blob[max(0, m.start()-8):m.start()+10]!r}")
    if foreign_hit:
        fail(f"[58] 本文に日本語以外の文字体系が混入: {foreign_hit[:5]}")
    else:
        ok("[58] 本文の文字体系チェック OK（キリル/ギリシャ/ハングル混入なし）")

    # 日本語の地の文に英単語が紛れる事故も起きたため（"一緒に record されていた"）、
    # 許可語以外の ASCII 語は warn で洗い出す。単位や固有名詞は許可。
    ASCII_OK = {"LT", "YouTube", "cm", "kg", "m", "PE", "SNS", "GPS", "IC", "JR"}
    ascii_hit = set()
    for k, entries in reports.items():
        for e in (entries if isinstance(entries, list) else [entries]):
            blob = re.sub(r"<[^>]+>", " ",
                          (e.get("html") or "") + (e.get("title") or "")
                          + " ".join(e.get("takeaways") or []))
            for w in re.findall(r"[A-Za-z]{2,}", blob):
                if w not in ASCII_OK:
                    ascii_hit.add(f"{k}:{w}")
    if ascii_hit:
        warn(f"[58] 本文に未登録の英単語（誤混入の可能性・許可語なら ASCII_OK に追加）: {sorted(ascii_hit)[:8]}")
    else:
        ok("[58] 本文の英単語チェック OK")
    if missing_src:
        fail(f"[58] 一次体験レポートに執筆者/日付/本文の欠落: {sorted(set(missing_src))[:5]}")
    elif n_reports == 0:
        ok("[58] 一次体験レポート 0 件（器のみ・Experience は未充足）")
    else:
        ok(f"[58] 一次体験レポート {n_reports} 件すべてに執筆者・実施日あり")

    # 描画済みページは必ず「自動集計ではない」旨を明示していること
    FR_MARK = 'class="field-report"'
    FR_DISC = "自動集計データではなく"
    fr_bad = []
    if os.path.isdir(fa_dir):
        for fn in os.listdir(fa_dir):
            if not fn.endswith(".html"):
                continue
            c = open(os.path.join(fa_dir, fn), encoding="utf-8").read()
            if FR_MARK in c and FR_DISC not in c:
                fr_bad.append(fn)
    if fr_bad:
        fail(f"[58] 体験レポート描画ページに一次情報の明示が欠落: {fr_bad[:5]}")
    else:
        ok("[58] 体験レポート描画ページの出典表示 OK")


def validate_fish_area_notes():
    """54: fish_area 編集部ノート（非count 固有文）の整合（Tier2・2026-07-18）

    背景: count 分析が原理的に立たない fish_area（外道主体/ソースに釣果数値なし）は、
    データ充実（hist>=80）でも近重複テンプレとして GSC に品質拒否される。normalize/
    fish_area_notes.json に便レベル共起（主対象か外道か）と旬から導いた honest な固有文を
    置き、crawler.py `_build_fish_area_notes_section` が『この海域の{fish}釣り』を描画する。
    検証（過大表現・断定ガード＝AdSense/信頼リスク防止）:
      - notes JSON が存在し 1件以上（無ければ skip）
      - 各ノート: html 非空・キーが "魚種|エリア" 形式・禁止表現/匹数断定が html に無い
      - 描画済み docs（class="fa-note" を含む fish_area ページ）は免責注記を必ず含み、
        禁止表現が無い（docs 未再生成時は vacuous pass・日次 crawl 後に実効）
    """
    print("\n[54] fish_area 編集部ノート（非count 固有文）の整合（Tier2）")
    notes_json = os.path.join(ROOT, "normalize", "fish_area_notes.json")
    if not os.path.isfile(notes_json):
        ok("[54] fish_area_notes.json なし → skip（未導入）")
        return
    try:
        with open(notes_json, encoding="utf-8") as f:
            notes = (json.load(f) or {}).get("notes", {}) or {}
    except Exception as e:
        fail(f"[54] fish_area_notes.json 読み込み失敗: {e}")
        return
    if not notes:
        ok("[54] fish_area_notes.json 収載 0 件 → skip")
        return

    FORBIDDEN = ["必ず釣れ", "確実に釣れ", "絶対に釣れ", "保証します"]
    bad_key = []
    empty_html = []
    forbidden_json = []
    for key, d in notes.items():
        if "|" not in key or len(key.split("|")) != 2 or not all(key.split("|")):
            bad_key.append(key)
        body = (d.get("html") or "").strip() if isinstance(d, dict) else ""
        if not body:
            empty_html.append(key)
        if any(fb in body for fb in FORBIDDEN):
            forbidden_json.append(key)
    if bad_key:
        fail(f"[54] ノートキーが「魚種|エリア」形式でない: {bad_key[:5]}")
    else:
        ok(f"[54] ノート {len(notes)} 件・キー形式OK")
    if empty_html:
        fail(f"[54] html 空のノート: {empty_html[:5]}")
    else:
        ok("[54] 全ノートに本文あり")
    if forbidden_json:
        fail(f"[54] ノート本文に禁止表現（断定的な釣果保証）: {forbidden_json[:5]}")
    else:
        ok("[54] ノート本文に禁止表現なし")

    MARK = 'class="fa-note"'
    DISC = "釣果を保証するものではなく"
    fa_dir = os.path.join(DOCS, "fish_area")
    rendered = 0
    missing_disc = []
    forbidden_doc = []
    if os.path.isdir(fa_dir):
        for fn in os.listdir(fa_dir):
            if not fn.endswith(".html"):
                continue
            c = open(os.path.join(fa_dir, fn), encoding="utf-8").read()
            if MARK not in c:
                continue
            rendered += 1
            if DISC not in c:
                missing_disc.append(fn)
            if any(fb in c for fb in FORBIDDEN):
                forbidden_doc.append(fn)
    if missing_disc:
        fail(f"[54] ノートセクションに免責注記が欠落: {missing_disc[:5]}")
    elif rendered:
        ok(f"[54] ノートセクション {rendered} 件レンダ・全件免責注記あり")
    else:
        ok("[54] docs 未再生成（ノート未描画）→ 日次 crawl で反映（vacuous pass）")
    if forbidden_doc:
        fail(f"[54] ノート描画ページに禁止表現: {forbidden_doc[:5]}")


def validate_xpost_no_zero_catch():
    """55: x_post 日次まとめに「0匹」矛盾表示が無いこと（2026-07-19）

    背景: 釣果があった魚（型=cm/kg が記録されている＝釣れている）でも匹数が未抽出だと
    cnt_max=0 になり、テーブル/散文が「0匹」と矛盾表示していた（例: シイラ 0匹 113〜122cm）。
    build_daily_page / context_builder は cnt_max 未記録時に「—」/空セグメントへ切替済み。
    検証: docs/x_post/*.html に禁止パターンが無いこと。
      - `<div class="catch">0匹</div>`（テーブル匹数セル）
      - `<span class="xc">0匹</span>`（画像プレビュー表）
      - `で0匹`（散文の「…で0匹・kg」「方面で0匹。」等）
      - `0匹台`（seasonal_max=0 の破綻文）
    """
    print("\n[55] x_post 「0匹」矛盾表示の排除（2026-07-19）")
    xp_dir = os.path.join(DOCS, "x_post")
    if not os.path.isdir(xp_dir):
        ok("[55] docs/x_post なし → skip")
        return
    pats = ['<div class="catch">0匹</div>', '<span class="xc">0匹</span>', "で0匹", "0匹台"]
    hit = []
    for fn in os.listdir(xp_dir):
        if not (fn.endswith(".html") and fn[:4].isdigit()):
            continue
        c = open(os.path.join(xp_dir, fn), encoding="utf-8").read()
        found = [p for p in pats if p in c]
        if found:
            hit.append((fn, found))
    if hit:
        fail(f"[55] x_post に「0匹」矛盾表示: {hit[:5]}（計{len(hit)}ページ）")
    else:
        ok("[55] x_post に「0匹」矛盾表示なし")


def validate_xpost_evidence_prose():
    """56: x_post 日次まとめの散文が「数値根拠つき」であること（2026-07-22）

    背景: ハイライト／魚種別報告が templates.py の H/F 文型に依存し、
    「今期は好海況が観測されています」「再現性が高いと推察されます」
    「ローテーション釣行に組み込みやすい魚種です」といった**根拠のない断定風フィラー**が
    本文の大半だった（ユーザー指摘 2026-07-22「ハイライトが薄っぺらい・魚種別報告も薄っぺらい」）。
    裁定 = フィラー全廃・数値根拠のみ。x_post/narrative.py が data/V2 CSV 由来の
    平年比（過去3年の同旬中央値比）・船宿別内訳・記録性・検証済み予測（tier A）で散文を生成する。

    検証（**最新の x_post ページ1枚のみ**。過去ページは旧文型のまま残るため対象外）:
      (a) 禁止フィラー表現が無い
      (b) 平年比の記述には必ず母数「同じ旬（N便）」が併記されている
      (c) 魚種別セクションに船宿名つきの「最多は…」記述がある（テーブルの反復でない）
    narrative が動かない日（insights 空・0件日）はフォールバックするので (b)(c) は warn 止まり。
    """
    print("\n[56] x_post 散文の数値根拠（2026-07-22）")
    xp_dir = os.path.join(DOCS, "x_post")
    if not os.path.isdir(xp_dir):
        ok("[56] docs/x_post なし → skip")
        return
    dates = sorted(fn for fn in os.listdir(xp_dir)
                   if fn.endswith(".html") and fn[:4].isdigit())
    if not dates:
        ok("[56] x_post 日次ページなし → skip")
        return
    latest = dates[-1]
    c = open(os.path.join(xp_dir, latest), encoding="utf-8").read()

    # narrative.py 製の散文は class="commentary evidence" を持つ。
    # 2026-07-22 以前に生成された既存ページは旧 H/F 文型のままなので対象外
    # （過去ページの遡及再生成は CSV 由来データで数値が変わるため行わない）。
    if 'class="commentary evidence"' not in c:
        warn(f"[56] {latest} は旧文型で生成済み（次回 crawl 再生成で有効化）→ skip")
        return

    # (a) 根拠なしフィラー
    banned = ["と推察されます", "好海況が観測されています", "再現性が高い",
              "組み込みやすい魚種です", "好スコア", "予定通り運航しました"]
    hit = [b for b in banned if b in c]
    if hit:
        fail(f"[56] {latest} に根拠なしフィラー表現: {hit}")
    else:
        ok(f"[56] {latest} に禁止フィラー表現なし")

    # (b) 読者に通じない内部用語（ユーザー指摘 2026-07-22 第2ラウンド）
    jargon = ["tier A", "tier a", "同旬", "母数", "平年比", "promise_break", "wMAPE", "open_tier"]
    jhit = [j for j in jargon if j in c]
    if jhit:
        fail(f"[56] {latest} に内部用語が露出: {jhit}")
    else:
        ok("[56] 内部用語（tier A・同旬・母数・平年比 等）の露出なし")

    # (c) 「例年」を使うなら、その定義を1か所で説明していること
    if "例年" in c:
        if "過去3年の同じ時期" in c:
            ok("[56] 「例年」の定義（過去3年の同じ時期）を明示している")
        else:
            fail("[56] 「例年」を使っているのに定義の説明が無い")
    else:
        warn(f"[56] {latest} に例年比較の記述なし（データ不足日ならフォールバック仕様）")

    # (d) テーブルの反復ではなく船宿別の内訳が書かれていること
    if "最多は" in c:
        ok("[56] 魚種別報告に船宿別の最多記述あり")
    else:
        warn(f"[56] {latest} に「最多は…」の船宿別記述なし（0件日/フォールバック時は正常）")

    # (e) 考察セクション（本日の条件 × これまでの傾向）を出すなら因果断定の否認が必須。
    #     方向（多い/少ない）は C層 r 符号由来なので、#50 と同じく相関である旨を明示する。
    if "本日の条件と、これまでの傾向" in c:
        if "原因を特定したものではありません" in c:
            ok("[56] 考察セクションに相関である旨の注記あり")
        else:
            fail("[56] 考察セクションに「原因を特定したものではありません」の注記が無い")
        ng = [w for w in ("必ず釣れ", "確実に釣れ", "絶対に釣れ", "が原因で", "によって釣れた") if w in c]
        if ng:
            fail(f"[56] 考察セクションに因果断定/誇大表現: {ng}")
    else:
        warn(f"[56] {latest} に考察セクションなし（海況の平年値が作れない日は正常）")

    # (f) ひらがな幼稚表現の再発防止（ユーザー指摘 2026-07-22）
    childish = ["きょういちばん", "ふだんは", "あすの予想", "いちばん出た"]
    chit = [w for w in childish if w in c]
    if chit:
        fail(f"[56] {latest} にひらがな主体の表現が再発: {chit}")
    else:
        ok("[56] 語調チェック OK（きょう/ふだん/あす 等の平仮名表現なし）")


def validate_fish_value_release():
    """51: 釣果価値チェッカー（/fish-value/）のリリース整合（2026-07-05）

    fish-value は crawler.py 非生成の独立アプリ（docs/fish-value/ 静的配置）。
    リリースで3点セット（noindex 解除・トップ導線・sitemap 収録）を導入したため、
    どれかが将来の再生成・改修で欠けると「導線のないリリース済みアプリ」に退行する。
    検証:
      - docs/fish-value/index.html が存在し noindex メタタグが無い
      - docs/index.html に /fish-value/ への内部リンクがある（gnav + トップカード）
      - docs/sitemap.xml に /fish-value/ が収録されている
      - 価格マスタの鮮度: fish-price-master.json seasonal.data_month のラグが
        3か月超で warn（urls_manifest.json への新月報追記漏れ = 更新運用停止の検知。
        月報公開ラグにより正常時ラグは 1.5〜2.5 か月）
    """
    print("\n[51] 釣果価値チェッカー（/fish-value/）リリース整合（2026-07-05）")
    fv_index = os.path.join(DOCS, "fish-value", "index.html")
    if not os.path.isfile(fv_index):
        fail("docs/fish-value/index.html が存在しない")
        return
    with open(fv_index, encoding="utf-8") as f:
        fv_html = f.read()
    head = fv_html[:4096]
    if 'name="robots"' in head and "noindex" in head:
        fail("fish-value/index.html に noindex が残っている（リリース済みのはず）")
    else:
        ok("fish-value/index.html は noindex なし（index 対象）")

    idx_path = os.path.join(DOCS, "index.html")
    if os.path.isfile(idx_path):
        with open(idx_path, encoding="utf-8") as f:
            idx_html = f.read()
        n_links = idx_html.count('href="/fish-value/"')
        if n_links == 0:
            fail("docs/index.html に /fish-value/ への導線が無い")
        else:
            ok(f"docs/index.html に /fish-value/ 導線 {n_links} 件")

    sm_path = os.path.join(DOCS, "sitemap.xml")
    if os.path.isfile(sm_path):
        with open(sm_path, encoding="utf-8") as f:
            sm = f.read()
        if "/fish-value/</loc>" not in sm:
            fail("sitemap.xml に /fish-value/ が収録されていない")
        else:
            ok("sitemap.xml に /fish-value/ 収録")

    # 価格マスタ鮮度（月報の手動マニフェスト更新が止まっていないか）
    pm_path = os.path.join(DOCS, "fish-value", "fish-price-master.json")
    try:
        with open(pm_path, encoding="utf-8") as f:
            pm = json.load(f)
        dm = str(pm.get("seasonal", {}).get("data_month") or
                 pm.get("source", {}).get("wholesale", ""))
        m = re.search(r"(\d{4})(\d{2})", dm)
        if m:
            from datetime import date as _date
            dy, dmn = int(m.group(1)), int(m.group(2))
            today = _date.today()
            lag = (today.year - dy) * 12 + (today.month - dmn)
            if lag > 3:
                warn(f"価格マスタのデータ月 {dy}-{dmn:02d} がラグ {lag} か月"
                     f"（urls_manifest.json への新月報追記漏れの疑い・毎月20日頃公開）")
            else:
                ok(f"価格マスタ鮮度 OK（データ月 {dy}-{dmn:02d}・ラグ {lag} か月）")
        else:
            warn("fish-price-master.json からデータ月を特定できない")

        # 日報ハイブリッド鮮度（週次 fish-value-daily.yml が止まっていないか）
        dc = pm.get("daily_correction")
        if dc and dc.get("by_pfid"):
            asof = str(dc.get("asof") or "")
            am = re.search(r"(\d{4})(\d{2})(\d{2})", asof)
            if am:
                from datetime import date as _date2
                a = _date2(int(am.group(1)), int(am.group(2)), int(am.group(3)))
                age = (_date2.today() - a).days
                n = len(dc["by_pfid"])
                if age > 14:
                    warn(f"日報補正が {age} 日前で古い（週次 fish-value-daily 停止の疑い・asof {asof}）")
                else:
                    ok(f"日報補正 鮮度OK（asof {asof}・{age}日前・{n}魚種）")
            else:
                warn("daily_correction.asof を解釈できない")
        else:
            ok("日報補正ブロックなし（未導入 or 全魚fallback・非ブロッキング）")
    except Exception as e:
        warn(f"fish-price-master.json 読込失敗: {e}")


def validate_no_paywall_signal_and_operator_info():
    """52: 未完成ペイウォールシグナルの排除 + 運営者情報（AdSense フェーズ1・2026-07-07）

    背景: AdSense「有用性の低いコンテンツ」4連敗。公式の審査範囲は「サイトのすべてのページ」で、
    未完成の課金機能（有料プランナビ・月額500円・公開準備中）は「site under construction」シグナル。
    マネタイズ方針（2026-06-10）も「予測は当面無料公開」なので、これらは方針とも矛盾していた。
    SHOW_PAID_TEASER=False の間、以下を保証（有料オープン時に True へ戻せばナビは復活する）:
      (a) 全 docs にナビの有料リンク（href="/forecast/" class="prem"）が無い
      (b) index/fish/area/fish_area/ship の indexed 主要ページに「月額500円」「公開準備中」が無い
      (c) x_post 公開ページに機械文バグ「以降以降」「kgkg」が無い
      (d) about ページに運営者プロフィール（人手のレビュー/キュレーション明示 = E-E-A-T）がある
    注: 「有料駐車場」「有料道路」等はアクセス解説の正当表現なので対象外（ナビ/課金 CTA のみ検知）。
    注: forecast 日付ページ（noindex・広告なし）の blur teaser は Phase2 で別途対応（本条件の対象外）。
    """
    import glob as _glob
    print("\n[52] 未完成ペイウォールsignal排除 + 運営者情報（AdSense フェーズ1・2026-07-07）")

    # (a) ナビの有料リンクが全 docs で 0
    nav_hits = []
    for p in _glob.glob(os.path.join(DOCS, "**", "*.html"), recursive=True):
        c = open(p, encoding="utf-8", errors="replace").read()
        if 'href="/forecast/" class="prem"' in c:
            nav_hits.append(os.path.relpath(p, DOCS))
    if nav_hits:
        fail(f"[52] ナビの有料リンク（class=prem）が {len(nav_hits)} ページに残存: {nav_hits[:5]}")
    else:
        ok("[52] ナビの有料リンク（class=prem）は全 docs で 0（SHOW_PAID_TEASER ゲート動作）")

    # (b) 主要 indexed ページ種に「月額500円」「公開準備中」が無い
    #     forecast ハブ index.html を含む（date ページ noindex は Phase2 対象外）
    paywall_targets = ["index.html", "calendar.html",
                       os.path.join("forecast", "index.html")]
    for sub in ("fish", "area", "fish_area", "ship", "monthly", "pages"):
        d = os.path.join(DOCS, sub)
        if os.path.isdir(d):
            paywall_targets += [os.path.relpath(p, DOCS)
                                for p in _glob.glob(os.path.join(d, "*.html"))]
    paywall_hits = []
    for rel in paywall_targets:
        p = os.path.join(DOCS, rel)
        if not os.path.isfile(p):
            continue
        c = open(p, encoding="utf-8", errors="replace").read()
        if "月額500円" in c or "公開準備中" in c:
            paywall_hits.append(rel)
    if paywall_hits:
        fail(f"[52] 主要indexedページに未完成課金文言（月額500円/公開準備中）{len(paywall_hits)}件: {paywall_hits[:5]}")
    else:
        ok(f"[52] 主要indexedページ {len(paywall_targets)} 種に月額500円/公開準備中なし")

    # (c) x_post 機械文バグ
    xp_bug = []
    xp_dir = os.path.join(DOCS, "x_post")
    if os.path.isdir(xp_dir):
        for p in _glob.glob(os.path.join(xp_dir, "*.html")):
            c = open(p, encoding="utf-8", errors="replace").read()
            if "以降以降" in c or "kgkg" in c:
                xp_bug.append(os.path.basename(p))
    if xp_bug:
        fail(f"[52] x_post に機械文バグ（以降以降/kgkg）{len(xp_bug)}件: {xp_bug[:5]}")
    else:
        ok("[52] x_post に機械文バグ（以降以降/kgkg）なし")

    # (d) about 運営者プロフィール（E-E-A-T）
    about_p = os.path.join(DOCS, "pages", "about.html")
    if os.path.isfile(about_p):
        ac = open(about_p, encoding="utf-8", errors="replace").read()
        has_profile = ("運営者について" in ac) and ("運営者本人が設計・確認" in ac)
        if has_profile:
            ok("[52] about に運営者プロフィール（人手キュレーション明示）あり")
        else:
            fail("[52] about に運営者プロフィール（『運営者について』＋人手キュレーション明示）が無い")
    else:
        warn("[52] docs/pages/about.html が無い")


def validate_verified_predictions_tier():
    """53: forecast 日付/週次ページの予測レンジは open_tier tier A のみ（T47b・2026-07-17）

    背景: 予測カードを crawler.py 内蔵モデル（精度未検証・ペイウォール付き）から
    検証済みモデル（forecast_daily.json × normalize/open_tier.json tier A）へ差し替えた。
    保証すること:
      (a) normalize/open_tier.json が存在し tier A が 30 組以上（蒸留漏れ検知）
      (b) forecast/YYYY-MM-DD.html のレンジ行（vp-table 内の「N〜M匹/人」を持つ fish×ship）が
          すべて open_tier の tier A に含まれる（選別のバイパス検知）
      (c) forecast 日付ページに旧ペイウォール文言（月額500円/有料プラン）が無い（#52 Phase2 完了）
      (d) 全日付ページが vp-section を持たない（=全ページ更新待ち）なら warn（JSON 鮮度切れ検知）
    """
    import glob as _glob
    import re as _re
    print("\n[53] 検証済み予測のティア整合（T47b・2026-07-17）")

    ot_path = os.path.join(ROOT, "normalize", "open_tier.json")
    if not os.path.isfile(ot_path):
        fail("[53] normalize/open_tier.json が存在しない（crawl/build_open_tier.py 未実行）")
        return
    try:
        tiers = json.load(open(ot_path, encoding="utf-8")).get("tiers") or {}
    except Exception as e:
        fail(f"[53] open_tier.json が読めない: {e}")
        return
    tier_a = {k for k, v in tiers.items() if v.get("tier") == "A"}
    if len(tier_a) < 30:
        fail(f"[53] tier A が {len(tier_a)} 組（<30）— 蒸留漏れ/基準異常の疑い")
    else:
        ok(f"[53] open_tier.json tier A = {len(tier_a)} 組")

    date_pages = sorted(_glob.glob(os.path.join(DOCS, "forecast", "2*.html")))
    if not date_pages:
        warn("[53] forecast 日付ページが無い")
        return
    # レンジ行: <tr><td>魚種</td><td><a ...>船宿</a>… or 船宿プレーン …<td class="rg">N〜M匹/人</td>
    row_re = _re.compile(
        r'<tr><td>([^<]+)</td><td>(?:<a[^>]*>)?([^<]+)(?:</a>)?'
        r'<small>[^<]*</small></td><td class="rg">\d+〜\d+匹/人</td>')
    bad_rows, paywall_hits, n_vp = [], [], 0
    for p in date_pages:
        c = open(p, encoding="utf-8", errors="replace").read()
        if "月額500円" in c or "有料プラン" in c:
            paywall_hits.append(os.path.basename(p))
        if 'class="vp-section"' in c and 'vp-table' in c:
            n_vp += 1
            for fish, ship in row_re.findall(c):
                if f"{fish.strip()}|{ship.strip()}" not in tiers or \
                        tiers.get(f"{fish.strip()}|{ship.strip()}", {}).get("tier") != "A":
                    bad_rows.append(f"{os.path.basename(p)}:{fish}×{ship}")
    if bad_rows:
        fail(f"[53] tier A 外のコンボがレンジ表示されている {len(bad_rows)}件: {bad_rows[:5]}")
    else:
        ok(f"[53] レンジ表示コンボはすべて tier A（日付ページ {len(date_pages)}枚・レンジあり {n_vp}枚）")
    if paywall_hits:
        fail(f"[53] forecast 日付ページに旧ペイウォール文言が残存 {len(paywall_hits)}件: {paywall_hits[:5]}")
    else:
        ok("[53] forecast 日付ページに月額500円/有料プランなし（#52 Phase2 完了）")
    if n_vp == 0:
        warn("[53] 全日付ページが予測更新待ち表示（forecast_daily.json の鮮度切れ/未生成の疑い）")


def validate_weather_csv_freshness():
    """60: weather/*.csv の鮮度（海況CSV 日次追記の無言停止検知・2026-08-01）

    背景: 2026-04-04/08 の大掃除で旧 weather_fetch.py（日次追記）が「不要」と
    誤判定されて削除され、weather/*.csv が 2026-04-13 で無言停止。消費側3系統
    （crawler.py 海況表示 / x_post/insights.py 平年値比較 /
    crawl/build_fish_area_analysis.py）は生きていたため、4か月間
    古いCSVを読み続けた。日次追記は ocean/update_weather_csv.py（crawl.yml）。
    保証すること:
      (a) weather/YYYY-MM.csv が1つ以上存在する
      (b) 最新月CSVの最大日付が7日以上古くない（Open-Meteo 障害等の数日は許容。
          鮮度なので --static-only では warn）
    """
    import glob as _glob
    print("\n[60] weather/*.csv 鮮度（海況CSV 日次追記）")
    files = sorted(_glob.glob(os.path.join(ROOT, "weather", "[0-9]" * 4 + "-" + "[0-9]" * 2 + ".csv")))
    if not files:
        fail("[60] weather/YYYY-MM.csv が1つも無い")
        return
    latest_file = files[-1]
    max_d = ""
    try:
        import csv as _csv
        with open(latest_file, encoding="utf-8", newline="") as f:
            for row in _csv.DictReader(f):
                d = row.get("date") or ""
                if d > max_d:
                    max_d = d
    except Exception as e:
        fail(f"[60] {os.path.basename(latest_file)} が読めない: {e}")
        return
    if not max_d:
        fail(f"[60] {os.path.basename(latest_file)} に date 行が無い（空ファイル）")
        return
    cutoff = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    if max_d < cutoff:
        fail_staleness(
            f"[60] weather/ 最新日付 {max_d} が7日以上古い（cutoff: {cutoff}）"
            "— ocean/update_weather_csv.py の日次追記が止まっている")
    else:
        ok(f"[60] weather/ 最新日付: {max_d}（{os.path.basename(latest_file)}）")


def validate_area_title_serp_width():
    """66: area title は SERP 幅に入らない `／N船宿` を載せない（2026-08-09）

    背景: GSC 実測（analytics/gsc/*.csv・直近28日）で 3〜6位帯の CTR が 2.05%
    （順位カーブの目安 8%）と大きく下振れしていた。原因調査で area の title 154本中
    **54本(35%)** が SERP 表示幅 600px を超過し、超過分は表示されない＝CTR に
    寄与していないことが判明。特に魚種名が途中で切れる（勝浦「スル…メイカ」・
    江戸川放水路「シ…ーバス」）と壊れた表示になる。

    `／N船宿` は「{港名} 釣果」型クエリの検索意図に無く（GSC 実クエリに船宿数を
    含むものは 0 件）、常に 5〜6字を消費して魚種名を truncate 側へ押し出していた。
    → crawler.py `build_area_title_body` で**幅が余っている時だけ**付ける方式に変更。

    ここで固定するのは「入らないのに載せない」という契約そのもの。
    幅の上限（600px）を緩めれば通る類のチェックではない（緩めると載る本数が増える＝
    契約違反が増える方向に働くため、閾値いじりでは黙らせられない）。

    ⚠ 魚種の件数は**チェックしない**。モバイルの SERP は2行折り返しで desktop より
    広く、GSC/GA4 とも device 次元を取っていないためモバイル比率が不明
    （analytics/fetch_gsc.py DIMENSIONS）。「削る」方向の最適化は device 別データを
    取ってから判断する。

    ⚠ 判定対象は **docs/ ではなく crawler.py の生成関数**。2026-08-06 の教訓と同じで、
    docs は CI のフル実行でしか正しく再生成できない（`--area-only` は全履歴を
    valid_catches に渡すため full/thin 判定が本番と変わり、出力を commit できない）。
    docs 側を fail 条件にすると新 title で再生成される前に CI が赤くなるため、
    ここでは**関数の契約**を実データ（現行 docs の title から復元した入力）で固定し、
    docs 側の件数は warn で可視化するに留める。docs 側の fail 化は、保留中の
    不変条件 #65（別称露出）と合わせて CI 再生成後に投入する。
    """
    print("\n[66] area title の SERP 表示幅と ／N船宿")
    area_dir = os.path.join(DOCS, "area")
    if not os.path.isdir(area_dir):
        warn("[66] docs/area が無い")
        return
    try:
        import importlib.util
        _spec = importlib.util.spec_from_file_location(
            "_crawler_for_v66", os.path.join(ROOT, "crawler.py"))
        _cr = importlib.util.module_from_spec(_spec)
        _spec.loader.exec_module(_cr)
        build_body = _cr.build_area_title_body
        _px = _cr.serp_title_px
        brand = _cr._AREA_TITLE_BRAND
        limit = _cr._SERP_TITLE_PX
    except Exception as e:
        fail(f"[66] crawler.py から title 生成関数を読めない: {e}")
        return

    # 現行 docs の title を「エリア名 / 魚種 / 船宿数」に分解し、生成関数の入力に戻す。
    # 新旧どちらの形式でも分解できる（船宿数は任意）。
    pat = re.compile(r"^(?P<name>.+?)の船釣り釣果【毎日更新】"
                     r"(?P<fish>[^／|]*?)(?:／(?P<n>\d+)船宿)?"
                     + re.escape(brand) + r"$")
    checked = bad_tail = bad_fish = 0
    samples = []
    docs_over = 0
    for fn in sorted(os.listdir(area_dir)):
        if not fn.endswith(".html") or fn == "index.html":
            continue
        try:
            html = open(os.path.join(area_dir, fn), encoding="utf-8").read()
        except Exception:
            continue
        m = re.search(r"<title>(.*?)</title>", html, re.S)
        if not m:
            continue
        title = m.group(1).strip()
        if _px(title) > limit:
            docs_over += 1
        g = pat.match(title)
        if not g:
            continue  # thin テンプレ・魚種なし版は対象外
        checked += 1
        fish = [f for f in g["fish"].split("・") if f]
        out = build_body(g["name"], fish, int(g["n"] or 0)) + brand
        # 契約1: ／N船宿 が載るのは幅に収まる時だけ
        if re.search(r"／\d+船宿", out) and _px(out) > limit:
            bad_tail += 1
            if len(samples) < 5:
                samples.append(f"{fn}({_px(out)}px)")
        # 契約2: 入力の魚種は1件も落とさない
        if any(f not in out for f in fish):
            bad_fish += 1
            if len(samples) < 5:
                samples.append(f"{fn}(魚種欠落)")
    if not checked:
        warn("[66] 分解できた area title が0本（title 形式が変わった可能性）")
        return
    if bad_tail or bad_fish:
        fail(f"[66] title 生成契約違反 {bad_tail + bad_fish}本"
             f"（幅超過なのに ／N船宿: {bad_tail} / 魚種欠落: {bad_fish}）: "
             + ", ".join(samples))
    else:
        ok(f"[66] title 生成関数の契約OK（{checked}本の実入力で検証・魚種欠落0）")
    if docs_over:
        warn(f"[66] 配信中の docs/area title で {limit}px 超過が {docs_over}本 "
             f"（CI フル実行で新 title に再生成されると減る見込み。"
             f"docs 側の fail 化は #65 と同時に投入）")


def validate_area_description_quality():
    """61: normalize/area_description.json の文章品質（2026-08-01）

    背景: area ページ「このエリアについて」の元データ（AI生成・113港）に
    (a) 尻切れ（文末が句点でない・7件） (b) 季節語と括弧内の月の矛盾
    （「秋から冬（7月・8月・12月）」等・19件） (c) 修復時の重ね置換による
    「夏と夏と冬」型の重複連結、が存在した。一括修復済み（決定ログ 2026-08-01）。
    このファイルは再生成・追記されうるため、静的品質チェックとして固定する。
    判定は「括弧内の月の過半が季節語の範囲外」のみ fail（軽微な1か月ズレは
    自然な文章表現として許容）。季節範囲は冬跨ぎ循環（冬=12〜2月）で判定する。
    """
    print("\n[61] normalize/area_description.json 文章品質")
    path = os.path.join(ROOT, "normalize", "area_description.json")
    if not os.path.isfile(path):
        warn("[61] area_description.json が無い")
        return
    try:
        ad = json.load(open(path, encoding="utf-8"))
    except Exception as e:
        fail(f"[61] area_description.json が読めない: {e}")
        return
    season = {"春先": (2, 4), "春": (3, 5), "初夏": (5, 7), "初秋": (9, 10), "秋初頭": (9, 10),
              "夏": (6, 8), "晩夏": (8, 8), "秋": (9, 11), "晩秋": (10, 11), "初冬": (11, 12), "冬": (12, 2)}
    sw = "春先|初夏|初秋|秋初頭|晩夏|晩秋|初冬|[春夏秋冬]"

    def _circ(a, b):
        return set(range(a, b + 1)) if b >= a else set(range(a, 13)) | set(range(1, b + 1))

    def _rng(phrase):
        parts = re.split("と", phrase)
        if len(parts) >= 2 and all(re.fullmatch(sw, x) for x in parts):
            s = set()
            for x in parts:
                s |= _circ(*season[x])
            return s
        m = re.match(rf"({sw})(?:から|〜)({sw})へ?$", phrase)
        if m:
            return _circ(season[m.group(1)][0], season[m.group(2)][1])
        m = re.match(rf"({sw})$", phrase)
        if m:
            return _circ(*season[m.group(1)])
        return None

    pat = re.compile(rf"((?:{sw})(?:と(?:{sw}))*(?:(?:から|〜)(?:{sw})へ?)?)（([0-9月〜・]+)）")
    bad = []
    for area, v in ad.items():
        d = (v or {}).get("description") or ""
        if not d:
            continue
        if not re.search(r"[。．！？」]$", d.strip()):
            bad.append(f"{area}: 尻切れ（文末: …{d.strip()[-15:]}）")
        if re.search(rf"(?:{sw})と(?:{sw})と", d) and re.search(r"([春夏秋冬])と\1", d):
            bad.append(f"{area}: 季節語の重複連結")
        for m in pat.finditer(d):
            r = _rng(m.group(1))
            if not r:
                continue
            months = set()
            for mm in re.finditer(r"(\d+)月(?:〜(\d+)月)?", m.group(2)):
                a2 = int(mm.group(1))
                b2 = int(mm.group(2)) if mm.group(2) else a2
                if 1 <= a2 <= 12 and 1 <= b2 <= 12:
                    months |= _circ(a2, b2)
            outside = months - r
            if outside and len(outside) * 2 >= len(months):
                bad.append(f"{area}: 「{m.group(0)}」の月の過半が季節範囲外 {sorted(outside)}")
    if bad:
        for b in bad[:8]:
            fail(f"[61] {b}")
    else:
        ok(f"[61] area_description {len(ad)}港: 尻切れ・季節×月矛盾・重複連結なし")


def validate_no_address_points():
    """62: 主要ポイント表示に住所型の値が出ていないこと（2026-08-01）

    背景: chowari 系の point_place に「千葉県 旭市 飯岡漁港」のような母港住所
    （釣り場ではない）が 85種・42,324行混入し、area/ship ページの
    「主要ポイント（TOP3）」・船宿一覧の sl-detail にポイント名として露出していた。
    crawler.py は読み込み時に _strip_address_points() で除去する（CSV は append-only
    のため書き換えない）。あわせて TOP3 の死にリンク <a href="#"> を span 化。
    判定は #54 と同じ「再生成前は vacuous pass」方式: ビルドバナー日付が today-2
    以内のページのみ検査（旧 docs に対する誤検知で push を塞がない）。
    """
    print("\n[62] area/ship 主要ポイントの住所型混入")
    addr_re = re.compile(r'>\S{2,4}[都道府県][\s　]\S+?[市町村郡]')
    banner_re = re.compile(r'var b="(\d{4}-\d{2}-\d{2})"')
    cutoff = (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d")
    bad, checked = [], 0
    for sub in ("area", "ship"):
        d = os.path.join(DOCS, sub)
        if not os.path.isdir(d):
            continue
        for fn in sorted(os.listdir(d)):
            if not fn.endswith(".html") or fn == "index.html":
                continue
            c = open(os.path.join(d, fn), encoding="utf-8", errors="replace").read()
            bm = banner_re.search(c)
            if not bm or bm.group(1) < cutoff:
                continue  # 再生成前の旧ページは対象外（vacuous pass）
            checked += 1
            # 主要ポイント・船宿詳細行の周辺のみ検査（本文のアクセス住所等は正当）
            for seg_pat in (r'<div class="point-list">.*?</div>',
                            r'<div class="sl-detail">.*?</div>'):
                for seg in re.findall(seg_pat, c, re.DOTALL):
                    if addr_re.search(seg):
                        bad.append(f"{sub}/{fn}")
                        break
                if bad and bad[-1] == f"{sub}/{fn}":
                    break
    if bad:
        fail(f"[62] 住所型ポイントが露出 {len(bad)}件: {bad[:5]}")
    elif checked:
        ok(f"[62] 主要ポイントに住所型なし（検査 {checked} ページ）")
    else:
        ok("[62] 対象ページ未再生成（vacuous pass・日次 crawl 後に実効）")


def validate_direct_crawl_json():
    """63: direct-crawl/catches_raw_direct.json の鮮度と内容水増し（2026-08-02）

    背景: gyo_crawler.py はどの workflow からも呼ばれておらず 2026-04-25 で無言停止。
    さらに旧実装は history URL を7日ぶん叩いて「同じ内容に URL の日付を貼る」設計で、
    373件中237件(63%)が同一内容の別日付コピーだった。CSV マージ側のパスも
    crawl/direct-crawl/... という存在しない場所を見ていて一度も効いていなかったため、
    3つの不具合が互いを隠していた。
    保証すること:
      (a) ファイルが存在し、レコードが1件以上ある
      (b) 最新日付が14日以上古くない（direct-crawl.yml の gyo ステップ停止検知。
          一之瀬丸は週数回の出船があるので14日で十分。鮮度なので --static-only では warn）
      (c) 同一内容（ship/fish_raw/count_raw/size_raw/weight_raw）が
          複数の日付に散らばっていない（= 日付の貼り直しによる水増し）
    """
    print("\n[63] direct-crawl/catches_raw_direct.json 鮮度・水増し")
    path = os.path.join(ROOT, "direct-crawl", "catches_raw_direct.json")
    if not os.path.exists(path):
        fail("[63] catches_raw_direct.json が無い")
        return
    try:
        with open(path, encoding="utf-8") as f:
            recs = json.load(f)
    except Exception as e:
        fail(f"[63] catches_raw_direct.json が読めない: {e}")
        return
    if not recs:
        fail("[63] catches_raw_direct.json が空")
        return

    max_d = max((r.get("date") or "") for r in recs)
    cutoff = (datetime.now() - timedelta(days=14)).strftime("%Y/%m/%d")
    if max_d < cutoff:
        fail_staleness(
            f"[63] catches_raw_direct.json 最新日付 {max_d} が14日以上古い"
            f"（cutoff: {cutoff}）— direct-crawl.yml の gyo ステップが止まっている")
    else:
        ok(f"[63] 最新日付: {max_d}（{len(recs)}件）")

    dates_by_content = {}
    for r in recs:
        key = (r.get("ship", ""), r.get("fish_raw", ""), r.get("count_raw", ""),
               r.get("size_raw", ""), r.get("weight_raw", ""))
        dates_by_content.setdefault(key, set()).add(r.get("date", ""))
    dup = {k: v for k, v in dates_by_content.items() if len(v) > 1}
    if dup:
        sample = list(dup.items())[:3]
        fail(f"[63] 同一内容が複数日付に存在 {len(dup)}種 "
             f"（水増し）: {[(k[0], k[1], sorted(v)[:3]) for k, v in sample]}")
    else:
        ok(f"[63] 内容重複なし（ユニーク内容 {len(dates_by_content)}種）")


def validate_xpost_forecast_sail_rate():
    """64: x_post の予想段落に載せる船宿は「ほぼ必ず出船する」ものだけ（2026-08-03）

    背景: 8/2 の投稿は tier A（レンジ精度は検証済み）からレンジ上限の大きい順に
    3件選んでおり、出船頻度を見ていなかった。結果ちがさき丸のカツオ（直近30日で
    出船1日）を名指しし、翌日は出船せず読者が答え合わせできない予想になった。
    広島屋のシロギス（16日/30）も同様。
    保証すること: 予想段落で名指しした (船宿, 魚種) が、投稿日を末端とする直近30日で
    24日以上（8割）出船していること。
    対象は新ルール適用後（_SINCE 以降）に生成された投稿のみ。それ以前は旧ルールで
    生成済みなので遡って fail させない。
    """
    import glob as _glob
    # 新ルールで生成される最初の投稿日。
    # 2026-08-04 に修正: 8/4 の crawl run はフィルタ実装(447b36d17)より前の
    # コミット(4699f40)でチェックアウトされたため、8/4 の投稿は旧ロジックで生成された
    # （こなや丸のアジ=出船1日/30・広島屋のシロギス=14日/30 を掲載）。
    # 投稿側を後から直すには crawler.py のフル再実行が要る（HERO 日付巻き戻しリスク）ので、
    # 検査開始日を新コードが実際に効く 8/5 に合わせる。
    _SINCE   = "2026-08-05"
    _WINDOW  = 30
    _MIN_DAY = 24
    print("\n[64] x_post 予想段落の出船頻度")

    posts = [p for p in sorted(_glob.glob(os.path.join(ROOT, "docs", "x_post", "20*.html")))
             if os.path.basename(p)[:10] >= _SINCE]
    if not posts:
        ok(f"[64] 対象投稿なし（{_SINCE} 以降が未生成・vacuous pass）")
        return

    # data/V2/*.csv から (魚種, 船宿) -> 出船日集合
    sail = {}
    data_dir = os.path.join(ROOT, "data", "V2")
    for fn in sorted(os.listdir(data_dir)) if os.path.isdir(data_dir) else []:
        if not fn.endswith(".csv") or fn == "cancellations.csv":
            continue
        try:
            with open(os.path.join(data_dir, fn), encoding="utf-8", newline="") as f:
                for r in csv.DictReader(f):
                    if r.get("is_cancellation") == "1":
                        continue
                    fish, ship = (r.get("tsuri_mono") or "").strip(), (r.get("ship") or "").strip()
                    d = (r.get("date") or "").replace("/", "-")
                    if fish and ship and len(d) == 10:
                        sail.setdefault((fish, ship), set()).add(d)
        except Exception as e:
            fail(f"[64] {fn} が読めない: {e}")
            return

    pat = re.compile(r'([^、。<>]+?)の([^、。<>]+?)が<b>\d+〜\d+匹</b>')
    bad, checked = [], 0
    for p in posts:
        post_date = os.path.basename(p)[:10]
        try:
            html = open(p, encoding="utf-8").read()
        except Exception:
            continue
        seg = re.search(r'の予想</b>は、(.{0,600}?)。', html, re.S)
        if not seg:
            continue
        body = re.sub(r'</?a[^>]*>', '', seg.group(1))   # 船宿リンクのタグを外す
        start = (datetime.strptime(post_date, "%Y-%m-%d")
                 - timedelta(days=_WINDOW - 1)).strftime("%Y-%m-%d")
        for ship, fish in pat.findall(body):
            checked += 1
            n = sum(1 for d in sail.get((fish, ship.strip()), ()) if start <= d <= post_date)
            if n < _MIN_DAY:
                bad.append(f"{post_date} {ship}×{fish} 出船{n}日/{_WINDOW}")

    if bad:
        fail(f"[64] 出船頻度が {_MIN_DAY}日未満の予想を掲載 {len(bad)}件: {bad[:5]}")
    else:
        ok(f"[64] 予想段落 {checked}件すべて出船{_MIN_DAY}日以上（{len(posts)}投稿を検査）")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--warn-only", action="store_true",
                    help="エラーでも非0終了しない（rollout 用）")
    ap.add_argument("--allow-mass-deletion", action="store_true",
                    help="不変条件 [59] の大量削除ガードを解除（意図的な一括削除時のみ）")
    ap.add_argument("--static-only", action="store_true",
                    help="壁時計依存の鮮度違反のみ warn 化（push 時の validate.yml 用）。"
                         "構造チェックは全て fail のまま。crawl.yml では使わないこと")
    args = ap.parse_args()

    if args.static_only:
        global STALENESS_IS_WARNING
        STALENESS_IS_WARNING = True

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
    validate_fish_area_noindex()
    validate_area_point_noindex()
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
    validate_fish_index_phaseC()
    validate_area_index_phaseC()
    validate_area_index_pref_emoji()
    validate_area_index_fish_links()
    validate_no_index_html_internal_link()
    validate_fish_guide_no_cross_contamination()
    validate_implausible_catch_count()
    validate_page_freshness()
    validate_favicon()
    validate_no_null_fish_display()
    validate_ship_slug_uniqueness()
    validate_tel_links()
    validate_no_dead_internal_links()
    validate_no_mass_page_deletion()
    validate_fish_content_sections()
    validate_xpost_no_operator_drafts()
    validate_no_ads_on_noindex()
    validate_brand_not_h1()
    validate_chowari_monthly_coverage()
    validate_fish_area_analysis_sections()
    validate_fish_area_notes()
    validate_xpost_no_zero_catch()
    validate_xpost_evidence_prose()
    validate_fish_value_release()
    validate_no_paywall_signal_and_operator_info()
    validate_verified_predictions_tier()
    validate_weather_csv_freshness()
    validate_area_title_serp_width()
    validate_area_description_quality()
    validate_no_address_points()
    validate_direct_crawl_json()
    validate_xpost_forecast_sail_rate()

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
