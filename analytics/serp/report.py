#!/usr/bin/env python
"""SERP 実査ログ（observations.json）を GSC 実績と突き合わせて表示する。

自動取得は一切しない（analytics/serp/README.md 参照・robots.txt で禁止）。
入力は人が手で書いた observations.json と analytics/gsc/*.csv だけ。

使い方:
    python analytics/serp/report.py              # 実査結果 + GSC 突合
    python analytics/serp/report.py --suggest    # 次に実査すべきクエリを GSC から提案
    python analytics/serp/report.py --diff       # 同一クエリの前回観測との差分

標準ライブラリのみ。
"""
import sys, os, json, csv, glob, argparse, urllib.parse
from collections import defaultdict

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OBS_PATH = os.path.join(ROOT, "analytics", "serp", "observations.json")
GSC_GLOB = os.path.join(ROOT, "analytics", "gsc", "*.csv")
SITE = "https://funatsuri-yoso.com/"


def load_obs():
    with open(OBS_PATH, encoding="utf-8") as f:
        return json.load(f).get("observations", [])


def load_gsc():
    rows = []
    for p in sorted(glob.glob(GSC_GLOB)):
        with open(p, encoding="utf-8", newline="") as f:
            for r in csv.DictReader(f):
                try:
                    r["clicks"] = int(r["clicks"])
                    r["impressions"] = int(r["impressions"])
                    r["position"] = float(r["position"])
                except (ValueError, KeyError):
                    continue
                rows.append(r)
    return rows


def agg(rows):
    """[(clicks, impressions, imp加重position)] を集計して (clk, imp, ctr, pos) にする。"""
    clk = sum(r["clicks"] for r in rows)
    imp = sum(r["impressions"] for r in rows)
    if not imp:
        return 0, 0, None, None
    pos = sum(r["position"] * r["impressions"] for r in rows) / imp
    return clk, imp, clk / imp * 100, pos


def month_of(date_str):
    return date_str[:7]


def cmd_report(obs, gsc):
    by_src = defaultdict(list)
    print("=" * 96)
    print("SERP 実査 × GSC 実績")
    print("=" * 96)
    print(f'{"観測日":11s} {"title元":9s} {"日付表記":10s} {"抜粋元":7s} {"AI引用":6s} '
          f'{"imp":>6s} {"clk":>4s} {"CTR":>7s} {"pos":>5s}  クエリ / ページ')
    for o in obs:
        ym = month_of(o["date"])
        page_url = SITE + o["page"] if o.get("page") else None
        # 同月・同クエリ・同ページの GSC 実績
        rows = [r for r in gsc
                if r["date"][:7] == ym and r["query"] == o["query"]
                and (page_url is None or r["page"] == page_url)]
        clk, imp, ctr, pos = agg(rows)
        src = o.get("title_source") or "-"
        ai = o.get("ai_answer_cited")
        ai_s = "あり" if ai is True else ("なし" if ai is False else "未確認")
        ctr_s = f"{ctr:6.2f}%" if ctr is not None else "     -"
        pos_s = f"{pos:5.1f}" if pos is not None else "    -"
        print(f'{o["date"]:11s} {src:9s} {str(o.get("serp_date_label") or "-"):10s} '
              f'{str(o.get("snippet_source") or "-"):7s} {ai_s:6s} '
              f'{imp:6d} {clk:4d} {ctr_s} {pos_s}  {o["query"]} / {o.get("page") or "-"}')
        if src in ("title", "h1") and imp:
            by_src[src].append((o, clk, imp, pos))

    print()
    print("-" * 96)
    print("title_source 別（ページ月次実績・観測クエリ単位ではなくページ全体で集計）")
    print("-" * 96)
    for src in ("title", "h1"):
        items = by_src.get(src, [])
        if not items:
            continue
        pages = {}
        for o, _clk, _imp, _pos in items:
            ym = month_of(o["date"])
            key = (o["page"], ym)
            if key in pages:
                continue
            rows = [r for r in gsc if r["date"][:7] == ym and r["page"] == SITE + o["page"]]
            pages[key] = agg(rows)
        tot_c = sum(v[0] for v in pages.values())
        tot_i = sum(v[1] for v in pages.values())
        label = "title 維持" if src == "title" else "h1 に差し替え"
        print(f'\n{label}（{len(pages)} ページ）: 計 {tot_i}impr / {tot_c}click / '
              f'CTR {tot_c/tot_i*100:.2f}%' if tot_i else f'\n{label}: 実績なし')
        for (page, ym), (c, i, ctr, pos) in sorted(pages.items(), key=lambda x: -x[1][1]):
            print(f'    {ym} {page:26s} {i:6d}impr {c:4d}click '
                  f'{ctr:6.2f}%  pos={pos:5.1f}')

    print()
    print("-" * 96)
    print("AI回答での引用")
    print("-" * 96)
    cited = [o for o in obs if o.get("ai_answer_cited") is True]
    unknown = [o for o in obs if o.get("ai_answer_cited") is None]
    print(f'引用あり {len(cited)} / 引用なし '
          f'{len([o for o in obs if o.get("ai_answer_cited") is False])} / 未確認 {len(unknown)}')
    for o in cited:
        print(f'  [{o["date"]}] 「{o["query"]}」 → {o.get("page")}')
        for q in o.get("ai_answer_quotes", []):
            print(f'      - {q}')
    if unknown:
        print(f'  未確認: {", ".join(sorted(set(o["query"] for o in unknown)))}')
    print("\n※ Yahoo の AI回答が Google AI Overview と同一システムかは未確認。"
          "ここでの「引用あり」は Yahoo の AI回答での引用を指す。")


def cmd_suggest(obs, gsc, top=15):
    """直近月の impression 上位クエリのうち、まだ実査していないものを出す。"""
    if not gsc:
        print("GSC データがない")
        return
    latest = max(r["date"] for r in gsc)[:7]
    q = defaultdict(list)
    for r in gsc:
        if r["date"][:7] == latest:
            q[(r["query"], r["page"])].append(r)
    done = {(o["query"], SITE + o["page"]) for o in obs if o.get("page")}
    cand = []
    for (query, page), rows in q.items():
        clk, imp, ctr, pos = agg(rows)
        if (query, page) in done or imp < 20:
            continue
        cand.append((imp, clk, ctr, pos, query, page))
    cand.sort(reverse=True)
    print(f"=== {latest} の未実査クエリ（impr>=20・上位 {top}）===")
    print("robots.txt により自動取得は不可。ブラウザで1本ずつ開いて README の手順で記録する。")
    for imp, clk, ctr, pos, query, page in cand[:top]:
        rel = page.replace(SITE, "") or "/"
        url = "https://search.yahoo.co.jp/search?p=" + urllib.parse.quote_plus(query)
        print(f'  {imp:5d}impr {clk:3d}clk {ctr:5.2f}% pos={pos:5.1f}  「{query}」 → {rel}')
        print(f'      {url}')


def cmd_diff(obs):
    """同一 (query, page) の観測を時系列に並べ、title_source の変化を出す。"""
    key = defaultdict(list)
    for o in obs:
        key[(o["query"], o.get("page"))].append(o)
    changed, same, single = [], [], 0
    for k, lst in key.items():
        lst.sort(key=lambda x: x["date"])
        if len(lst) < 2:
            single += 1
            continue
        a, b = lst[-2], lst[-1]
        rec = (k, a, b)
        (changed if a.get("title_source") != b.get("title_source") else same).append(rec)
    print("=== 前回観測との差分 ===")
    if not changed and not same:
        print(f"2回以上観測したクエリがまだ無い（1回のみ {single} 件）。"
              "同じクエリを再実査すると差分が出る。")
        return
    for (query, page), a, b in changed:
        print(f'  [変化] 「{query}」 {page}')
        print(f'      {a["date"]}: {a.get("title_source")} / {a.get("serp_title")}')
        print(f'      {b["date"]}: {b.get("title_source")} / {b.get("serp_title")}')
    for (query, page), a, b in same:
        print(f'  [不変] 「{query}」 {page} = {b.get("title_source")}'
              f'（{a["date"]} → {b["date"]}）')
    if single:
        print(f'  （1回しか観測していないクエリ {single} 件）')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--suggest", action="store_true", help="次に実査すべきクエリを GSC から提案")
    ap.add_argument("--diff", action="store_true", help="同一クエリの前回観測との差分")
    args = ap.parse_args()
    obs = load_obs()
    if args.diff:
        cmd_diff(obs)
        return
    gsc = load_gsc()
    if args.suggest:
        cmd_suggest(obs, gsc)
    else:
        cmd_report(obs, gsc)


if __name__ == "__main__":
    main()
