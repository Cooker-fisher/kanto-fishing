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
# ページ次元 CSV（date+page）を使う。クエリ次元 CSV（gsc/*.csv）は GSC の匿名化で
# **click の約 1/3 しか含まず、しかも欠測率がページごとに 9〜71% とばらつく**
# （2026-09-03 に API の次元なし合計と突き合わせて実測）。種別×週次の比較を
# クエリ次元でやると、母数も CTR も種別ごとに違う倍率で歪む。詳細は fetch_gsc.py。
GSC_GLOB = os.path.join(ROOT, "analytics", "gsc", "pages", "*.csv")
GSC_QUERY_GLOB = os.path.join(ROOT, "analytics", "gsc", "*.csv")
SITE = "https://funatsuri-yoso.com/"

# 施策の投入日と判定基準。効果判定はここを見て行う。
# 「いつ・何を・どうなれば成功か」を先に書いておかないと、後から都合よく読める。
INTERVENTIONS = [
    {
        "date": "2026-08-29",
        "name": "#67 船宿ハブ新設 + ship ナビ統一",
        "section": "ship",
        "baseline": "投入直前（ページ次元・真値）: 2026-07〜08 で 4,156impr / 28click"
                    " / CTR 0.67% / pos 11.7。全ページ page2 圏で固定",
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
        "baseline": "2026-07〜08（ページ次元・真値）: katsuura 1.28%(pos8.3) /"
                    " iioka 2.22%(6.7) / amatsu 0.53%(7.5) 対 金谷 4.21%(7.6) /"
                    " 静浦 4.05%(8.5)。⚠ 旧ベースラインはクエリ次元 CSV 由来で"
                    " katsuura 1.11% / 金谷 5.24% としていた（click 欠測 48%）。"
                    " 差は 4.8倍→3.3倍に縮んだがギャップ自体は健在",
        "criterion": "SERP 実査（analytics/serp/report.py --recheck → --diff）で"
                     " title_source が h1 → title に変わり、CTR が上がる。"
                     "⚠ 主指標は katsuura。iioka と amatsu は 2026-08-10 週に"
                     " imp が約70%落ちており（順位は不変・原因未特定）判定に使えない。"
                     "⚠⚠ 2026-09-03 追記: 投入前 n=6 の area 観測では title_source と"
                     " SERP日付表記が**完全交絡**していた（title維持=日付なし=CTR4.8% /"
                     " h1差し替え=日付あり=CTR1.5%。report.py の「交絡チェック」を見よ）。"
                     " 再実査で両方が同時に動いたら CTR が上がっても #68 の効果とは言えない。"
                     " 片方だけ動いたケースを見つけるまでは因果を主張しない。"
                     "✅ 2026-09-03: 交絡のうち「クロール鮮度」側は棄却した。"
                     " URL Inspection の lastCrawlTime で shizuura が最古（08-17）"
                     " なのに CTR 4.05% で2位、katsuura は 08-31 と新しいのに 1.28%。"
                     " クロール頻度は CTR を説明しないので、残るのは"
                     "「Google が日付つき扱いする理由」= SERP 再実査に一本化する",
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
    files = sorted(glob.glob(GSC_GLOB))
    if not files:
        # 黙って空を返すと「実績ゼロ」と読める。取り違えの再発を防ぐため落とす。
        sys.exit(
            f"[trend] ページ次元 CSV が無い: {GSC_GLOB}" + chr(10)
            + "        python analytics/fetch_gsc.py --days 130 でバックフィルする。" + chr(10)
            + "        クエリ次元 CSV（gsc/*.csv）で代用しないこと"
              "（匿名化で click の約1/3・欠測はページごとに 9〜71%）")
    for p in files:
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


def partial_periods(rows, monthly):
    """日数が揃っていない期間（=未確定）を返す（2026-09-03 追加）。

    GSC は直近 2〜3 日ぶんが未確定で、fetch_gsc.py も直近30日を毎回上書きする。
    そのため最新の週/月はほぼ必ず日数が欠ける。印を付けずに並べると
    「2026-08-31 週 100imp（前週 954imp）」が暴落に見える。実際は 1日ぶんしかない。
    施策の判定を月初に回すとここで必ず読み違えるので、行に日数を出す。
    最古の期間が欠けるのは GSC 計測開始前で、こちらは後から埋まらない。
    どちらも「この行は他の行と同じ土俵ではない」という意味では同じ。
    """
    days = defaultdict(set)
    for r in rows:
        k = r["date"][:7] if monthly else week_of(r["date"])
        days[k].add(r["date"])
    out = {}
    for k, ds in days.items():
        if monthly:
            y, m = int(k[:4]), int(k[5:7])
            nm = date(y + (m == 12), (m % 12) + 1, 1)
            full = (nm - date(y, m, 1)).days
        else:
            full = 7
        if len(ds) < full:
            out[k] = (len(ds), full)
    return out


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
    partial = partial_periods(rows, monthly)
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
            if p in partial:
                n, full = partial[p]
                mark = f"  ※{n}/{full}日ぶんのみ" + mark
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
