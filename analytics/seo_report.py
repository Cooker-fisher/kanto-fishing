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
REPO_ROOT = os.path.dirname(ANALYTICS_DIR)
GSC_GLOB = os.path.join(ANALYTICS_DIR, "gsc", "*.csv")
GA4_GLOB = os.path.join(ANALYTICS_DIR, "ga4", "*.csv")
REPORT_DIR = os.path.join(ANALYTICS_DIR, "report")
DATA_GLOB = os.path.join(REPO_ROOT, "data", "V2", "*.csv")
FISH_ROMAJI = os.path.join(REPO_ROOT, "normalize", "fish_romaji_map.json")

# 検索順位→平均CTR の経験則カーブ（organic・日本語SERP想定の保守値）
CTR_CURVE = {1: 0.27, 2: 0.15, 3: 0.10, 4: 0.07, 5: 0.05,
             6: 0.04, 7: 0.032, 8: 0.026, 9: 0.022, 10: 0.019}
CTR_TAIL = 0.012   # 11位以下
TARGET_POS = 3     # 「あと一歩」クエリの目標順位（ここまで上げたら何クリック増えるか）

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


def ctr_for_pos(pos):
    """順位→期待CTR。小数順位は四捨五入してカーブ参照。"""
    p = int(round(pos))
    if p < 1:
        p = 1
    return CTR_CURVE.get(p, CTR_TAIL)


def _agg_query(gsc, start, end):
    """クエリ別に impr/clicks/加重順位/代表ページ を集約。"""
    a = defaultdict(lambda: {"impr": 0, "clicks": 0, "pos_w": 0.0, "pages": defaultdict(int)})
    for r in gsc:
        if not within(r.get("date", ""), start, end):
            continue
        q = r.get("query", "")
        if not q:
            continue
        m = _i(r.get("impressions"))
        a[q]["impr"] += m
        a[q]["clicks"] += _i(r.get("clicks"))
        a[q]["pos_w"] += _f(r.get("position")) * m
        a[q]["pages"][r.get("page", "")] += m
    return a


# ---------- ① クリック増分試算 ----------
def click_uplift(gsc, start, end):
    out = []
    for q, v in _agg_query(gsc, start, end).items():
        if v["impr"] < SD_MIN_IMPR:
            continue
        pos = v["pos_w"] / v["impr"]
        if pos <= TARGET_POS:   # 既に目標以上は対象外
            continue
        gain = v["impr"] * (ctr_for_pos(TARGET_POS) - ctr_for_pos(pos))
        if gain < 1:
            continue
        top_page = max(v["pages"].items(), key=lambda kv: kv[1])[0] if v["pages"] else ""
        out.append({"query": q, "impr": v["impr"], "pos": round(pos, 1),
                    "clicks": v["clicks"], "gain": round(gain, 1), "page": top_page})
    out.sort(key=lambda d: -d["gain"])
    return out


# ---------- ② CTR異常ページ ----------
def ctr_anomaly_pages(gsc, start, end):
    a = defaultdict(lambda: {"impr": 0, "clicks": 0, "pos_w": 0.0})
    for r in gsc:
        if not within(r.get("date", ""), start, end):
            continue
        pg = r.get("page", "")
        m = _i(r.get("impressions"))
        a[pg]["impr"] += m
        a[pg]["clicks"] += _i(r.get("clicks"))
        a[pg]["pos_w"] += _f(r.get("position")) * m
    out = []
    for pg, v in a.items():
        if v["impr"] < 20:   # 母数の少ないページは除外
            continue
        pos = v["pos_w"] / v["impr"]
        actual = v["clicks"] / v["impr"]
        expect = ctr_for_pos(pos)
        # 期待CTRの半分未満＝snippet/title が弱い疑い
        if actual < expect * 0.5:
            out.append({"page": pg, "impr": v["impr"], "pos": round(pos, 1),
                        "actual": actual, "expect": expect,
                        "lost": round(v["impr"] * (expect - actual), 1)})
    out.sort(key=lambda d: -d["lost"])
    return out


# ---------- ③ 釣果 × 集客 突合 ----------
def catch_vs_traffic(ga4, start, end):
    try:
        romaji = __import__("json").load(open(FISH_ROMAJI, encoding="utf-8"))
    except Exception:
        return None
    # 直近の釣果件数（data/V2/*.csv・対象期間と前後を含む当月+前月）
    months = set()
    d = dt.date.fromisoformat(end)
    for k in range(2):
        months.add((d - dt.timedelta(days=30 * k)).isoformat()[:7])
    catch = defaultdict(int)
    for p in glob.glob(DATA_GLOB):
        if not any(m in os.path.basename(p) for m in months):
            continue
        try:
            for r in _read_csv(p):
                t = r.get("tsuri_mono", "")
                if t and t not in ("NULL", "不明", ""):
                    catch[t] += 1
        except Exception:
            continue
    if not catch:
        return None
    # GA4 魚種ページ UU（slug 単位）
    uu = defaultdict(int)
    for r in ga4:
        if not within(r.get("date", ""), start, end):
            continue
        path = r.get("pagePath", "")
        if path.startswith("/fish/") and path.rstrip("/").count("/") >= 2:
            slug = unquote(path.split("/")[-1]).replace(".html", "")
            uu[slug] += _i(r.get("activeUsers"))
    rows = []
    for jp, cnt in catch.items():
        slug = romaji.get(jp)
        if not slug:
            continue
        rows.append({"fish": jp, "catch": cnt, "uu": uu.get(slug, 0)})
    if not rows:
        return None
    # 釣果ランクと集客ランクの乖離で「鉱脈（釣れてるのに未集客）」を判定
    by_catch = sorted(rows, key=lambda x: -x["catch"])
    catch_rank = {r["fish"]: i for i, r in enumerate(by_catch)}
    by_uu = sorted(rows, key=lambda x: -x["uu"])
    uu_rank = {r["fish"]: i for i, r in enumerate(by_uu)}
    n = len(rows)
    for r in rows:
        cr, ur = catch_rank[r["fish"]], uu_rank[r["fish"]]
        # 釣果は上位30%なのに集客は下位50%＝強化候補
        if cr < n * 0.3 and ur > n * 0.5:
            r["flag"] = "🔥強化候補"
        elif ur < n * 0.3 and cr > n * 0.5:
            r["flag"] = "集客先行"
        else:
            r["flag"] = ""
    return by_catch


# ---------- ④ 順位トレンド（今週 vs 前週） ----------
def rank_trend(gsc, end_date):
    end = end_date
    cur = (end - dt.timedelta(days=6)).isoformat(), end.isoformat()
    prev = (end - dt.timedelta(days=13)).isoformat(), (end - dt.timedelta(days=7)).isoformat()

    def wpos(s, e):
        a = defaultdict(lambda: [0.0, 0])  # pos_w, impr
        for r in gsc:
            if within(r.get("date", ""), s, e):
                q = r.get("query", "")
                m = _i(r.get("impressions"))
                a[q][0] += _f(r.get("position")) * m
                a[q][1] += m
        return {q: (pw / im) for q, (pw, im) in a.items() if im >= SD_MIN_IMPR}

    cp, pp = wpos(*cur), wpos(*prev)
    rows = []
    for q in set(cp) & set(pp):
        delta = cp[q] - pp[q]   # 負=順位上昇（数字が小さくなった）
        if abs(delta) < 0.5:
            continue
        rows.append({"query": q, "now": round(cp[q], 1), "prev": round(pp[q], 1),
                     "delta": round(delta, 1)})
    rows.sort(key=lambda d: d["delta"])  # 上昇（負）が先頭
    return rows


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

    # ① クリック増分試算
    up = click_uplift(gsc, start, end)
    L.append(f"\n## 📈 上げたら効くクエリ（{TARGET_POS}位まで上げた時のクリック増分試算）")
    L.append("「表示は多いが順位が低くて取りこぼし中」を増分クリックの大きい順に。h1/title強化の横展開先。\n")
    if up:
        L.append("| 検索クエリ | 表示 | 現順位 | 現クリック | 推定+クリック/月 | 対象ページ |")
        L.append("|---|---:|---:|---:|---:|---|")
        for d in up[:15]:
            pg = unquote(d["page"]).replace("https://funatsuri-yoso.com", "") or "/"
            L.append(f"| {d['query']} | {d['impr']} | {d['pos']} | {d['clicks']} | +{d['gain']} | {pg} |")
    else:
        L.append("_該当なし_")

    # ② CTR異常ページ
    an = ctr_anomaly_pages(gsc, start, end)
    L.append("\n## 🔧 CTR不足ページ（表示は多いのにクリックされない＝title/説明文が弱い疑い）")
    if an:
        L.append("| ページ | 表示 | 順位 | 実CTR | 期待CTR | 取りこぼし |")
        L.append("|---|---:|---:|---:|---:|---:|")
        for d in an[:12]:
            pg = unquote(d["page"]).replace("https://funatsuri-yoso.com", "") or "/"
            L.append(f"| {pg} | {d['impr']} | {d['pos']} | {d['actual']*100:.1f}% | {d['expect']*100:.1f}% | {d['lost']} |")
    else:
        L.append("_該当なし（CTRは概ね順位相応）_")

    # ③ 釣果 × 集客 突合
    cvt = catch_vs_traffic(ga4, start, end)
    L.append("\n## 🐟×🔍 釣果 × 集客 突合（釣れてるのに検索集客できてない鉱脈）")
    if cvt:
        L.append("「🔥強化候補」= 釣果は上位なのに検索UUが下位。コンテンツ/SEO強化の優先魚種。\n")
        L.append("| 魚種 | 釣果件数 | 検索UU | 判定 |")
        L.append("|---|---:|---:|---|")
        for d in cvt[:20]:
            L.append(f"| {d['fish']} | {d['catch']} | {d['uu']} | {d.get('flag','')} |")
    else:
        L.append("_釣果データ未取得（data/V2 か fish_romaji_map.json が見つからない）_")

    # ④ 順位トレンド
    rt = rank_trend(gsc, dt.date.fromisoformat(end))
    L.append("\n## 🔼 順位トレンド（今週 vs 前週・上昇順）")
    L.append("施策の効果測定用。▲=上昇 / ▼=下降。\n")
    if rt:
        L.append("| 検索クエリ | 前週順位 | 今週順位 | 変化 |")
        L.append("|---|---:|---:|---|")
        for d in rt[:8]:
            mark = f"▲{abs(d['delta'])}" if d["delta"] < 0 else f"▼{d['delta']}"
            L.append(f"| {d['query']} | {d['prev']} | {d['now']} | {mark} |")
        if len(rt) > 8:
            L.append("\n下降が大きいもの:")
            L.append("| 検索クエリ | 前週順位 | 今週順位 | 変化 |")
            L.append("|---|---:|---:|---|")
            for d in sorted(rt, key=lambda x: -x["delta"])[:5]:
                if d["delta"] > 0:
                    L.append(f"| {d['query']} | {d['prev']} | {d['now']} | ▼{d['delta']} |")
    else:
        L.append("_2週分のデータが揃うと表示_")

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
