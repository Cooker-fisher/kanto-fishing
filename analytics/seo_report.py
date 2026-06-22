#!/usr/bin/env python3
"""
C/E: SEO・集客レポート生成（GSC + GA4 の蓄積 CSV から）

入力 : analytics/gsc/*.csv（fetch_gsc.py 出力）+ analytics/ga4/*.csv（fetch_ga4.py 出力）
出力 : analytics/report/latest.md（最新・上書き）+ analytics/report/YYYY-MM-DD.md（日付スナップショット）
実行 : python analytics/seo_report.py [--window 28]

標準ライブラリのみ（追加依存なし）。データが無い指標はセクションごと skip。

含まれる分析:
  ①惜しいクエリ（striking distance）: 6〜20位で表示はあるがクリックが伸びてない検索語
       → 該当ページの title/見出し強化で1ページ目を狙う SEO 即効ネタ
  ②週次サマリー: 直近7日 vs その前7日のクリック/UU 増減
  ③集客ページ TOP: GA4 ページ別 UU/PV（魚種/エリア/予報… 種別ラベル付き）
  ④魚種別・エリア別 集客: pagePath を魚種/エリアに集約した UU ランキング
"""
import argparse
import csv
import datetime as dt
import glob
import os
from collections import defaultdict
from urllib.parse import unquote

ANALYTICS_DIR = os.path.dirname(os.path.abspath(__file__))
GSC_GLOB = os.path.join(ANALYTICS_DIR, "gsc", "*.csv")
GA4_GLOB = os.path.join(ANALYTICS_DIR, "ga4", "*.csv")
REPORT_DIR = os.path.join(ANALYTICS_DIR, "report")

# 惜しいクエリの抽出基準
SD_POS_MIN = 5.0     # これより上位（=数字が小さい）は既に1ページ目上位なので対象外
SD_POS_MAX = 20.0    # これより下位は伸びしろが薄い
SD_MIN_IMPR = 5      # 最低表示回数（ノイズ除去）


def _read_csv(path):
    with open(path, "r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def load_rows(pattern):
    rows = []
    for p in sorted(glob.glob(pattern)):
        rows.extend(_read_csv(p))
    return rows


def _f(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _i(v, default=0):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return default


def within(date_str, start, end):
    return start <= date_str <= end


def page_label(path):
    """pagePath → (種別, 表示名)。日本語スラッグは URL デコードして読みやすく。"""
    p = unquote(path or "")
    seg = p.strip("/").split("/")
    if p in ("/", ""):
        return ("トップ", "/")
    head = seg[0]
    name = unquote(seg[-1]).replace(".html", "") if len(seg) > 1 else head
    kind = {
        "fish": "魚種", "area": "エリア", "fish_area": "魚種×エリア",
        "forecast": "予報", "ship": "船宿", "pages": "固定", "calendar": "カレンダー",
    }.get(head, "その他")
    return (kind, name)


# ---------- ① 惜しいクエリ ----------
def striking_distance(gsc, start, end):
    agg = defaultdict(lambda: {"impr": 0, "clicks": 0, "pos_w": 0.0, "pages": defaultdict(int)})
    for r in gsc:
        if not within(r.get("date", ""), start, end):
            continue
        q = r.get("query", "")
        if not q:
            continue
        impr = _i(r.get("impressions"))
        a = agg[q]
        a["impr"] += impr
        a["clicks"] += _i(r.get("clicks"))
        a["pos_w"] += _f(r.get("position")) * impr  # 表示回数で加重
        a["pages"][r.get("page", "")] += impr
    out = []
    for q, a in agg.items():
        if a["impr"] < SD_MIN_IMPR:
            continue
        pos = a["pos_w"] / a["impr"] if a["impr"] else 0
        if not (SD_POS_MIN <= pos <= SD_POS_MAX):
            continue
        top_page = max(a["pages"].items(), key=lambda kv: kv[1])[0] if a["pages"] else ""
        out.append({
            "query": q, "impr": a["impr"], "clicks": a["clicks"],
            "pos": round(pos, 1), "page": top_page,
        })
    # 表示回数が多く・順位が惜しい順（impr 降順, pos 昇順）
    out.sort(key=lambda d: (-d["impr"], d["pos"]))
    return out


# ---------- ② 週次サマリー ----------
def weekly_summary(gsc, ga4, end_date):
    end = end_date
    cur_s = (end - dt.timedelta(days=6)).isoformat()
    prev_s = (end - dt.timedelta(days=13)).isoformat()
    prev_e = (end - dt.timedelta(days=7)).isoformat()
    end_s = end.isoformat()

    def sum_gsc(s, e):
        c = i = 0
        for r in gsc:
            if within(r.get("date", ""), s, e):
                c += _i(r.get("clicks"))
                i += _i(r.get("impressions"))
        return c, i

    def sum_ga4(s, e):
        u = pv = 0
        for r in ga4:
            if within(r.get("date", ""), s, e):
                u += _i(r.get("activeUsers"))
                pv += _i(r.get("screenPageViews"))
        return u, pv

    return {
        "cur_range": (cur_s, end_s), "prev_range": (prev_s, prev_e),
        "gsc_cur": sum_gsc(cur_s, end_s), "gsc_prev": sum_gsc(prev_s, prev_e),
        "ga4_cur": sum_ga4(cur_s, end_s), "ga4_prev": sum_ga4(prev_s, prev_e),
    }


# ---------- ③④ 集客ページ / 魚種・エリア ----------
def page_traffic(ga4, start, end):
    pages = defaultdict(lambda: {"users": 0, "pv": 0})
    fish = defaultdict(int)
    area = defaultdict(int)
    for r in ga4:
        if not within(r.get("date", ""), start, end):
            continue
        path = r.get("pagePath", "")
        u = _i(r.get("activeUsers"))
        pages[path]["users"] += u
        pages[path]["pv"] += _i(r.get("screenPageViews"))
        kind, name = page_label(path)
        # 一覧ページ（/fish/ ・/area/ 自体）は個別魚種/エリアではないので除外
        is_detail = path.rstrip("/").count("/") >= 2
        if is_detail and kind == "魚種":
            fish[name] += u
        elif is_detail and kind == "エリア":
            area[name] += u
    top_pages = sorted(pages.items(), key=lambda kv: -kv[1]["users"])
    return top_pages, sorted(fish.items(), key=lambda kv: -kv[1]), \
        sorted(area.items(), key=lambda kv: -kv[1])


def _delta(cur, prev):
    d = cur - prev
    sign = "▲" if d > 0 else ("▼" if d < 0 else "→")
    pct = f"{(d/prev*100):+.0f}%" if prev else "—"
    return f"{cur}（{sign}{abs(d)} / {pct}）"


def build_markdown(gsc, ga4, window):
    dates = [r.get("date", "") for r in gsc] + [r.get("date", "") for r in ga4]
    dates = [d for d in dates if d]
    if not dates:
        return "# SEO・集客レポート\n\nデータがありません。\n", None
    end_date = dt.date.fromisoformat(max(dates))
    start = (end_date - dt.timedelta(days=window - 1)).isoformat()
    end = end_date.isoformat()

    L = []
    L.append(f"# SEO・集客レポート（{start} 〜 {end}・直近{window}日）")
    L.append(f"\n_生成: {dt.date.today().isoformat()} / データ最新日: {end}_\n")

    # ② 週次
    w = weekly_summary(gsc, ga4, end_date)
    cc, ci = w["gsc_cur"]; pc, pi = w["gsc_prev"]
    cu, cpv = w["ga4_cur"]; pu, ppv = w["ga4_prev"]
    L.append("## 📊 週次サマリー（直近7日 vs 前7日）")
    L.append(f"- 期間: {w['cur_range'][0]}〜{w['cur_range'][1]}（前: {w['prev_range'][0]}〜{w['prev_range'][1]}）")
    L.append(f"- 検索クリック: {_delta(cc, pc)}")
    L.append(f"- 検索表示回数: {_delta(ci, pi)}")
    L.append(f"- UU（ユーザー）: {_delta(cu, pu)}")
    L.append(f"- PV: {_delta(cpv, ppv)}")

    # ① 惜しいクエリ
    sd = striking_distance(gsc, start, end)
    L.append(f"\n## 🎯 惜しいクエリ（{SD_POS_MIN:.0f}〜{SD_POS_MAX:.0f}位・表示{SD_MIN_IMPR}回以上）")
    L.append("title/見出し強化で1ページ目を狙える検索語。表示が多く順位が惜しい順。\n")
    if sd:
        L.append("| 検索クエリ | 表示 | クリック | 平均順位 | 対象ページ |")
        L.append("|---|---:|---:|---:|---|")
        for d in sd[:25]:
            pg = unquote(d["page"]).replace("https://funatsuri-yoso.com", "") or "/"
            L.append(f"| {d['query']} | {d['impr']} | {d['clicks']} | {d['pos']} | {pg} |")
    else:
        L.append("_該当なし（データ蓄積待ち）_")

    # ③ 集客ページ
    top_pages, fish, area = page_traffic(ga4, start, end)
    L.append("\n## 🏆 集客ページ TOP20（UU 順）")
    if top_pages:
        L.append("| ページ | 種別 | UU | PV |")
        L.append("|---|---|---:|---:|")
        for path, v in top_pages[:20]:
            kind, name = page_label(path)
            L.append(f"| {name} | {kind} | {v['users']} | {v['pv']} |")
    else:
        L.append("_該当なし_")

    # ④ 魚種・エリア
    L.append("\n## 🐟 魚種別 集客 TOP10（UU）")
    if fish:
        L.append("| 魚種 | UU |\n|---|---:|")
        for name, u in fish[:10]:
            L.append(f"| {name} | {u} |")
    else:
        L.append("_該当なし_")
    L.append("\n## 📍 エリア別 集客 TOP10（UU）")
    if area:
        L.append("| エリア | UU |\n|---|---:|")
        for name, u in area[:10]:
            L.append(f"| {name} | {u} |")
    else:
        L.append("_該当なし_")

    L.append("\n---\n_自動生成: analytics/seo_report.py_")
    return "\n".join(L) + "\n", end


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--window", type=int, default=28, help="集計対象の日数（既定28）")
    args = parser.parse_args()

    gsc = load_rows(GSC_GLOB)
    ga4 = load_rows(GA4_GLOB)
    print(f"[seo_report] GSC {len(gsc)} 行 / GA4 {len(ga4)} 行")

    md, end = build_markdown(gsc, ga4, args.window)
    os.makedirs(REPORT_DIR, exist_ok=True)
    latest = os.path.join(REPORT_DIR, "latest.md")
    with open(latest, "w", encoding="utf-8") as f:
        f.write(md)
    out_paths = [latest]
    if end:
        snap = os.path.join(REPORT_DIR, f"{end}.md")
        with open(snap, "w", encoding="utf-8") as f:
            f.write(md)
        out_paths.append(snap)
    for p in out_paths:
        print(f"  → {os.path.relpath(p, ANALYTICS_DIR)}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
