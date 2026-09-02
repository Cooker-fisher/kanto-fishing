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
from datetime import date, timedelta

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OBS_PATH = os.path.join(ROOT, "analytics", "serp", "observations.json")
GSC_GLOB = os.path.join(ROOT, "analytics", "gsc", "*.csv")                 # クエリ次元
GSC_PAGES_GLOB = os.path.join(ROOT, "analytics", "gsc", "pages", "*.csv")  # ページ次元
SITE = "https://funatsuri-yoso.com/"


def load_obs():
    with open(OBS_PATH, encoding="utf-8") as f:
        return json.load(f).get("observations", [])


def load_gsc(pattern=None):
    """GSC CSV を読む。既定はクエリ次元（gsc/*.csv）。

    **ページ別の実績にクエリ次元を使ってはいけない**: GSC は query 次元を付けると
    低頻度クエリの行を匿名化して落とすため、合計が真値の約 1/3 になり、
    欠測率はページごとに 9〜71% とばらつく（2026-09-02 実測・fetch_gsc.py 参照）。
    ページ別 CTR の比較は必ず load_gsc(GSC_PAGES_GLOB) を使う。
    """
    rows = []
    for p in sorted(glob.glob(pattern or GSC_GLOB)):
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


def cmd_report(obs, gsc, gsc_q=None):
    """obs を GSC と突き合わせて表示する。

    gsc   = ページ次元（date+page）。ページ別の impr/click/CTR はこちらが真値。
    gsc_q = クエリ次元（date+query+page）。一覧行の「そのクエリでの実績」用。
            匿名化で欠測するので、そう明記して出す。
    """
    gsc_q = gsc if gsc_q is None else gsc_q
    by_src = defaultdict(list)
    print("=" * 96)
    print("SERP 実査 × GSC 実績")
    print("=" * 96)
    print("※ クエリ別 impr/clk はクエリ次元（匿名化で欠測あり）。"
          "ページ別集計は下段のページ次元＝真値")
    print(f'{"観測日":11s} {"title元":9s} {"日付表記":10s} {"抜粋元":7s} {"AI引用":6s} '
          f'{"imp":>6s} {"clk":>4s} {"CTR":>7s} {"pos":>5s}  クエリ / ページ')
    for o in obs:
        ym = month_of(o["date"])
        page_url = SITE + o["page"] if o.get("page") else None
        # 同月・同クエリ・同ページの GSC 実績
        rows = [r for r in gsc_q
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
    print("title_source 別（ページ種別ごと・ページ月次実績で集計）")
    print("-" * 96)
    print("※ 種別をまたいで足さない。ship の指名検索は公式サイトが上位、fish は横断集計サイトが")
    print("   競合と、SERP の構造がまるで違う。混ぜると title 維持/差し替えの比較が意味を失う")
    sections = []
    for src in ("title", "h1"):
        for o, _c, _i, _p in by_src.get(src, []):
            sec = (o.get("page") or "").split("/")[0]
            if sec not in sections:
                sections.append(sec)
    for sec in sections:
        print("")
        print(f"[{sec}]")
        for src in ("title", "h1"):
            items = [x for x in by_src.get(src, [])
                     if (x[0].get("page") or "").split("/")[0] == sec]
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
            if tot_i:
                print(f'  {label}（{len(pages)} ページ）: 計 {tot_i}impr / {tot_c}click / '
                      f'CTR {tot_c/tot_i*100:.2f}%')
            else:
                print(f'  {label}: 実績なし')
            for (page, ym), (c, i, ctr, pos) in sorted(pages.items(), key=lambda x: -x[1][1]):
                print(f'      {ym} {page:30s} {i:6d}impr {c:4d}click '
                      f'{ctr:6.2f}%  pos={pos:5.1f}')

    print_confound(obs, gsc)

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


def print_confound(obs, gsc):
    """title_source × SERP日付表記 のクロス集計（2026-09-02 追加）。

    なぜ必要か: 2026-08-29 の area 6観測では、この2つが完全に一致して動いていた。
      title 維持 = 日付表記なし = CTR 4.8%（kanaya / shizuura）
      h1 差し替え = 日付表記あり = CTR 1.5%（iioka / katsuura / amatsu）
    つまり #68（H1 に別称+県名）の効果と「SERP に出る日付の鮮度」の効果は、
    いまのデータでは **原理的に分離できない**（完全交絡）。
    これを明示せずに 9月中旬の判定に入ると、
      ・CTR が上がった → 「#68 が効いた」と誤帰属する
      ・CTR が動かない → 「title は関係ない」と誤って棄却する
    のどちらにも転べてしまう。分離には片方だけが違うセルの実査が要る。
    """
    print()
    print("-" * 96)
    print("交絡チェック: title_source × SERP日付表記")
    print("-" * 96)
    print("※ この2つが同じ向きに動いていると、CTR 差をどちらの要因にも帰属できない")

    def has_date(o):
        v = o.get("serp_date_label")
        return "日付あり" if v else "日付なし"

    secs = []
    for o in obs:
        if o.get("title_source") not in ("title", "h1"):
            continue
        sec = (o.get("page") or "").split("/")[0]
        if sec not in secs:
            secs.append(sec)

    for sec in secs:
        items = [o for o in obs
                 if o.get("title_source") in ("title", "h1")
                 and (o.get("page") or "").split("/")[0] == sec]
        cells = defaultdict(dict)   # (title_source, 日付) -> {(page, ym): (clk, imp, ctr, pos)}
        for o in items:
            ym = month_of(o["date"])
            k = (o["title_source"], has_date(o))
            if (o["page"], ym) in cells[k]:
                continue
            rows = [r for r in gsc if r["date"][:7] == ym and r["page"] == SITE + o["page"]]
            cells[k][(o["page"], ym)] = agg(rows)
        print("")
        print(f"[{sec}]")
        print(f'  {"":14s}{"日付なし":>22s}{"日付あり":>22s}')
        filled = []
        for src in ("title", "h1"):
            line = f'  {("title 維持" if src == "title" else "h1 差し替え"):14s}'
            for d in ("日付なし", "日付あり"):
                v = cells.get((src, d), {})
                if not v:
                    line += f'{"—":>20s}  '
                    continue
                filled.append((src, d))
                ti = sum(x[1] for x in v.values())
                tc = sum(x[0] for x in v.values())
                ctr = f"{tc/ti*100:.2f}%" if ti else "-"
                line += f'{f"{len(v)}p {ti}imp {ctr}":>20s}  '
            print(line)
        for (src, d), v in sorted(cells.items(), key=lambda x: -sum(y[1] for y in x[1].values())):
            for (page, ym), (c, i, ctr, pos) in sorted(v.items(), key=lambda x: -x[1][1]):
                if not i:
                    continue
                print(f'      [{src:5s}/{d}] {ym} {page:28s} {i:6d}impr {c:4d}click '
                      f'{ctr:6.2f}%  pos={pos:5.1f}')
        if len(filled) == 2 and filled[0][0] != filled[1][0] and filled[0][1] != filled[1][1]:
            print(f'  ⚠ {sec}: 対角2セルしか埋まっていない = title_source と日付表記が完全交絡。')
            print(f'    どちらが CTR 差の原因かは、この観測群だけでは判定できない。')
            print(f'    分離するには「h1 差し替え × 日付なし」か「title 維持 × 日付あり」の実査が要る。')
        elif len(filled) < 2:
            print(f'  （{sec}: セルが {len(filled)} 個しか埋まっていない。比較不能）')


def _window_rows(gsc, days):
    """GSC 最新日から遡って days 日ぶんの行を返す。

    以前は「最新の暦月」で切っていたが、月初は数日ぶんしか無く（GSC は 2〜3日遅延）
    impr>=20 のクエリが 0 件になって --suggest が空を返した（2026-09-02 に実測）。
    施策の判定は月初にこそ回すので、暦月ではなく移動窓で切る。
    """
    if not gsc:
        return [], None, None
    last = max(r["date"] for r in gsc)
    first = (date.fromisoformat(last) - timedelta(days=days - 1)).isoformat()
    return [r for r in gsc if first <= r["date"] <= last], first, last


def cmd_suggest(obs, gsc, top=15, days=28):
    """直近 days 日の impression 上位クエリのうち、まだ実査していないものを出す。"""
    rows, first, last = _window_rows(gsc, days)
    if not rows:
        print("GSC データがない")
        return
    q = defaultdict(list)
    for r in rows:
        q[(r["query"], r["page"])].append(r)
    done = {(o["query"], SITE + o["page"]) for o in obs if o.get("page")}
    cand = []
    for (query, page), rs in q.items():
        clk, imp, ctr, pos = agg(rs)
        if (query, page) in done or imp < 20:
            continue
        cand.append((imp, clk, ctr, pos, query, page))
    cand.sort(reverse=True)
    print(f"=== 未実査クエリ（{first}〜{last} の {days}日・impr>=20・上位 {top}）===")
    print("robots.txt により自動取得は不可。ブラウザで1本ずつ開いて README の手順で記録する。")
    if not cand:
        print("  該当なし（この窓の impr>=20 クエリは実査済み）")
    for imp, clk, ctr, pos, query, page in cand[:top]:
        rel = page.replace(SITE, "") or "/"
        url = "https://search.yahoo.co.jp/search?p=" + urllib.parse.quote_plus(query)
        print(f'  {imp:5d}impr {clk:3d}clk {ctr:5.2f}% pos={pos:5.1f}  「{query}」 → {rel}')
        print(f'      {url}')


def cmd_recheck(obs, gsc, days=28):
    """実査済みクエリの「再実査待ち」を出す。

    --suggest は未実査クエリしか出さないので、施策の効果判定（同じクエリを
    投入前後で比べる）には使えない。#68 の判定は katsuura の再実査そのものなので、
    再実査すべき対象を明示的に並べる用途を分ける（2026-09-02 追加）。
    """
    rows, first, last = _window_rows(gsc, days)
    seen = defaultdict(list)
    for o in obs:
        if o.get("page"):
            seen[(o["query"], o["page"])].append(o)
    print(f"=== 再実査待ち（実査済み {len(seen)} 件・GSC は {first}〜{last} の {days}日）===")
    print("同じクエリを再度ブラウザで開き、title_source と日付表記の変化を記録する。")
    out = []
    for (query, page), lst in seen.items():
        lst.sort(key=lambda x: x["date"])
        rs = [r for r in rows if r["page"] == SITE + page and r["query"] == query]
        clk, imp, ctr, pos = agg(rs)
        out.append((imp, clk, ctr, pos, query, page, lst[-1]))
    out.sort(reverse=True)
    for imp, clk, ctr, pos, query, page, lastobs in out:
        gap = (date.fromisoformat(last) - date.fromisoformat(lastobs["date"])).days if last else 0
        ctr_s = f"{ctr:5.2f}%" if ctr is not None else "    -"
        pos_s = f"{pos:5.1f}" if pos is not None else "    -"
        print(f'  前回{lastobs["date"]}({gap}日前) {imp:5d}impr {clk:3d}clk {ctr_s} pos={pos_s}'
              f'  「{query}」 → {page}')
        print(f'      前回: title_source={lastobs.get("title_source")} / '
              f'日付={lastobs.get("serp_date_label") or "なし"}')
        print(f'      https://search.yahoo.co.jp/search?p='
              f'{urllib.parse.quote_plus(query)}')


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
        # title_source だけでなく SERP日付表記の変化も追う（2026-09-02）。
        # 両者は 2026-08-29 時点で完全交絡していた（print_confound 参照）ので、
        # どちらが動いたのかを毎回並べて見ないと #68 の効果を誤帰属する。
        moved = (a.get("title_source") != b.get("title_source")
                 or a.get("serp_date_label") != b.get("serp_date_label"))
        (changed if moved else same).append(rec)
    print("=== 前回観測との差分 ===")
    if not changed and not same:
        print(f"2回以上観測したクエリがまだ無い（1回のみ {single} 件）。"
              "同じクエリを再実査すると差分が出る。")
        return
    for (query, page), a, b in changed:
        print(f'  [変化] 「{query}」 {page}')
        for x in (a, b):
            print(f'      {x["date"]}: title_source={x.get("title_source")} / '
                  f'日付={x.get("serp_date_label") or "なし"} / {x.get("serp_title")}')
        if (a.get("title_source") != b.get("title_source")
                and a.get("serp_date_label") != b.get("serp_date_label")):
            print(f'      ⚠ title_source と日付表記が同時に動いた。CTR が変わっても'
                  f'どちらの効果かは分離できない')
    for (query, page), a, b in same:
        print(f'  [不変] 「{query}」 {page} = {b.get("title_source")} / '
              f'日付={b.get("serp_date_label") or "なし"}（{a["date"]} → {b["date"]}）')
    if single:
        print(f'  （1回しか観測していないクエリ {single} 件）')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--suggest", action="store_true", help="次に実査すべきクエリを GSC から提案")
    ap.add_argument("--diff", action="store_true", help="同一クエリの前回観測との差分")
    ap.add_argument("--recheck", action="store_true", help="実査済みクエリの再実査待ちを出す")
    ap.add_argument("--days", type=int, default=28, help="GSC の集計窓（日数・既定 28）")
    args = ap.parse_args()
    obs = load_obs()
    if args.diff:
        cmd_diff(obs)
        return
    if args.recheck:
        cmd_recheck(obs, load_gsc(), days=args.days)
    elif args.suggest:
        cmd_suggest(obs, load_gsc(), days=args.days)
    else:
        # ページ別の実績はページ次元から。クエリ次元は匿名化欠測で比較に使えない。
        # 一覧行のクエリ別 impr/click はクエリ次元にしか無いので両方渡す。
        pages = load_gsc(GSC_PAGES_GLOB)
        if not pages:
            sys.exit(
                f"[serp] ページ次元 CSV が無い: {GSC_PAGES_GLOB}" + chr(10)
                + "       python analytics/fetch_gsc.py --days 130 でバックフィルする。" + chr(10)
                + "       クエリ次元で代用するとページ別 CTR の順位が入れ替わる")
        cmd_report(obs, pages, load_gsc())


if __name__ == "__main__":
    main()
