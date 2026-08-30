#!/usr/bin/env python
"""GSC 実績をページ種別×週次で集計する。施策の効果判定用。

`analytics/gsc/*.csv` だけを読む。ネットワークアクセスなし・標準ライブラリのみ。

使い方:
    python analytics/gsc/trend.py                 # 種別×週次（既定）
    python analytics/gsc/trend.py --section ship  # ship のページ別内訳
    python analytics/gsc/trend.py --monthly       # 種別×月次
    python analytics/gsc/trend.py --weeks 16      # 表示する週数

なぜ作ったか:
    #67（船宿ハブ）#68（area H1）の効果判定は「2週間後に GSC を見る」で終わらせると
    毎回その場で集計コードを書き直すことになる。判定基準（下の INTERVENTIONS）ごと
    残しておかないと、数週間後の自分が何と比べればいいのか分からなくなる。
"""
import sys, os, csv, glob, argparse, collections
from collections import defaultdict
from datetime import date, timedelta

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
GSC_GLOB = os.path.join(ROOT, "analytics", "gsc", "*.csv")
SITE = "https://funatsuri-yoso.com/"

# 施策の投入日と判定基準。効果判定はここを見て行う。
# 「いつ・何を・どうなれば成功か」を先に書いておかないと、後から都合よく読める。
INTERVENTIONS = [
    {
        "date": "2026-08-29",
        "name": "#67 船宿ハブ新設 + ship ナビ統一",
        "section": "ship",
        "baseline": "投入直前10週: imp 65〜225 / click 0〜1 / pos 10.6〜17.8（page2 圏で固定）",
        "criterion": "imp 加重平均 pos が 10 を切る。切らなければ内部リンク以外が律速。"
                     "⚠ 2026-08-30 の SERP 実査で、ship の指名検索（庄治郎丸 釣果 等）は"
                     " 1位2位が船宿の公式サイトだと判明した。title は差し替えられておらず"
                     " 説明文もそのまま採用されているのに 0click ＝ 構造的に勝てない。"
                     "#67 の価値は「指名検索でクリックを取る」ではなく"
                     "「内部リンクグラフの修復とクロール到達性」。click 増は期待値に入れない",
    },
    {
        "date": "2026-08-29",
        "name": "#68 area H1 に別称+県名",
        "section": "area",
        "baseline": "2026-08: katsuura 1.11% / iioka 2.03% / amatsu 0.49%"
                    "（対 金谷 5.24% / 静浦 5.01%・pos はどれも 6.6〜8.2）",
        "criterion": "SERP 実査（analytics/serp/report.py --diff）で title_source が"
                     " h1 → title に変わり、CTR が上がる。"
                     "⚠ 主指標は katsuura。iioka と amatsu は 2026-08-10 週に"
                     " imp が約70%落ちており（順位は不変・原因未特定）判定に使えない",
    },
]

SECTIONS = ["area", "fish", "fish_area", "ship", "x_post", "monthly", "column", "forecast"]


def section_of(url):
    rel = url.replace(SITE, "")
    if rel in ("", "index.html"):
        return "(top)"
    head = rel.split("/")[0]
    if head in SECTIONS:
        return head
    return rel if "/" not in rel else head


def week_of(d):
    x = date.fromisoformat(d)
    return (x - timedelta(days=x.weekday())).isoformat()


def load():
    rows = []
    for p in sorted(glob.glob(GSC_GLOB)):
        with open(p, encoding="utf-8", newline="") as f:
            rdr = csv.DictReader(f)
            if not rdr.fieldnames or "impressions" not in rdr.fieldnames:
                continue
            for r in rdr:
                try:
                    r["clicks"] = int(r["clicks"])
                    r["impressions"] = int(r["impressions"])
                    r["position"] = float(r["position"])
                except (ValueError, KeyError):
                    continue
                rows.append(r)
    return rows


def agg(bucket):
    clk = sum(b[0] for b in bucket)
    imp = sum(b[1] for b in bucket)
    if not imp:
        return 0, 0, 0.0, 0.0
    pos = sum(b[2] for b in bucket) / imp
    return clk, imp, clk / imp * 100, pos


def fmt_row(label, clk, imp, ctr, pos, mark="", w=12):
    return f'{label:{w}s} {imp:6d}imp {clk:4d}clk {ctr:6.2f}% pos={pos:5.1f} {mark}'


def bucket_rows(rows, keyfn, filt=None):
    b = defaultdict(list)
    for r in rows:
        if filt and not filt(r):
            continue
        b[keyfn(r)].append((r["clicks"], r["impressions"], r["position"] * r["impressions"]))
    return b


def print_interventions(section=None):
    rel = [i for i in INTERVENTIONS if section is None or i["section"] == section]
    if not rel:
        return
    print("\n" + "=" * 78)
    print("投入済み施策と判定基準")
    print("=" * 78)
    for i in rel:
        print(f'  [{i["date"]}] {i["name"]}  → 対象: {i["section"]}')
        print(f'      投入前: {i["baseline"]}')
        print(f'      判定  : {i["criterion"]}')


def cmd_sections(rows, weeks, monthly):
    keyfn = (lambda r: r["date"][:7]) if monthly else (lambda r: week_of(r["date"]))
    periods = sorted({keyfn(r) for r in rows})[-weeks:]
    marks = {}
    for i in INTERVENTIONS:
        k = i["date"][:7] if monthly else week_of(i["date"])
        marks.setdefault(k, []).append(i["name"].split()[0])
    unit = "月次" if monthly else "週次"
    for sec in ["area", "fish", "ship", "fish_area", "(top)"]:
        sub = [r for r in rows if section_of(r["page"]) == sec]
        if not sub:
            continue
        b = bucket_rows(sub, keyfn)
        print("\n" + "-" * 78)
        print(f'{sec}  （{unit}）')
        print("-" * 78)
        for p in periods:
            if p not in b:
                continue
            clk, imp, ctr, pos = agg(b[p])
            mark = "  ← " + " / ".join(marks[p]) + " 投入" if p in marks else ""
            print(fmt_row(p, clk, imp, ctr, pos, mark))
    print_interventions()


def cmd_section_detail(rows, section, weeks, monthly):
    sub = [r for r in rows if section_of(r["page"]) == section]
    if not sub:
        print(f"{section} のデータが無い")
        return
    keyfn = (lambda r: r["date"][:7]) if monthly else (lambda r: week_of(r["date"]))
    periods = sorted({keyfn(r) for r in sub})[-weeks:]
    marks = {}
    for i in INTERVENTIONS:
        if i["section"] != section:
            continue
        marks.setdefault(i["date"][:7] if monthly else week_of(i["date"]), []).append(
            i["name"].split()[0])
    b = bucket_rows(sub, keyfn)
    print("=" * 78)
    print(f'{section} 全体（{"月次" if monthly else "週次"}）')
    print("=" * 78)
    for p in periods:
        if p not in b:
            continue
        clk, imp, ctr, pos = agg(b[p])
        mark = "  ← " + " / ".join(marks[p]) + " 投入" if p in marks else ""
        print(fmt_row(p, clk, imp, ctr, pos, mark))

    # 直近期間のページ別内訳
    last = periods[-1] if periods else None
    if last:
        print("\n" + "-" * 78)
        print(f'{last} のページ別（imp 降順・上位15）')
        print("-" * 78)
        pb = bucket_rows(sub, lambda r: r["page"], filt=lambda r: keyfn(r) == last)
        items = [(page, *agg(v)) for page, v in pb.items()]
        top = sorted(items, key=lambda x: -x[2])[:15]
        w = max([len(p.replace(SITE, "")) for p, *_ in top] + [12])
        for page, clk, imp, ctr, pos in top:
            print(fmt_row(page.replace(SITE, ""), clk, imp, ctr, pos, w=w))
    print_interventions(section)


def cmd_page_detail(rows, page, weeks, monthly):
    """1ページの週次推移 + クエリ別週次。急落の切り分け用。

    順位が変わらないのに imp だけ落ちている場合、順位・スニペットの問題ではなく
    「マッチするクエリが減った」か「検索需要が減った」。この2つは GSC だけでは
    切り分けられないので、ユニーククエリ数も併記する。
    """
    url = page if page.startswith("http") else SITE + page.lstrip("/")
    sub = [r for r in rows if r["page"] == url]
    if not sub:
        print(f"{page} のデータが無い")
        return
    keyfn = (lambda r: r["date"][:7]) if monthly else (lambda r: week_of(r["date"]))
    periods = sorted({keyfn(r) for r in sub})[-weeks:]
    b = bucket_rows(sub, keyfn)
    print("=" * 78)
    print(f'{url.replace(SITE, "")}（{"月次" if monthly else "週次"}）')
    print("=" * 78)
    for p in periods:
        if p not in b:
            continue
        clk, imp, ctr, pos = agg(b[p])
        qn = len({r["query"] for r in sub if keyfn(r) == p})
        print(fmt_row(p, clk, imp, ctr, pos, mark=f"クエリ{qn:3d}種"))

    top = collections.Counter()
    for r in sub:
        top[r["query"]] += r["impressions"]
    print(chr(10) + "-" * 78)
    print("クエリ別 imp（全期間 imp 上位8）")
    print("-" * 78)
    print("query".ljust(24) + "".join(p[5:].rjust(8) for p in periods))
    for q, _ in top.most_common(8):
        line = q.ljust(24)
        for p in periods:
            line += str(sum(r["impressions"] for r in sub
                            if r["query"] == q and keyfn(r) == p)).rjust(8)
        print(line)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--section", help="内訳を出すページ種別（area/fish/ship/fish_area/x_post）")
    ap.add_argument("--page", help="1ページの週次 + クエリ別内訳（例 area/iioka.html）")
    ap.add_argument("--monthly", action="store_true", help="週次でなく月次で集計")
    ap.add_argument("--weeks", type=int, default=12, help="表示する期間数（既定 12）")
    args = ap.parse_args()
    rows = load()
    if not rows:
        print("analytics/gsc/*.csv にデータが無い")
        return
    if args.page:
        cmd_page_detail(rows, args.page, args.weeks, args.monthly)
    elif args.section:
        cmd_section_detail(rows, args.section, args.weeks, args.monthly)
    else:
        cmd_sections(rows, args.weeks, args.monthly)


if __name__ == "__main__":
    main()
