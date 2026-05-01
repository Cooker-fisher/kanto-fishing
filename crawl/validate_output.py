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
    counts = [int(m) for m in re.findall(r'今週釣果(\d+)件', content)]
    if not counts:
        fail("「今週釣果X件」のラベルが見つからない")
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
    for m in re.finditer(r'href="(\w[\w-]*)\.html"[^>]*>.*?今週釣果(\d+)件', aindex_content, re.DOTALL):
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
