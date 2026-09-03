#!/usr/bin/env python
"""GSC URL Inspection API で「なぜインデックスされていないか」を URL 単位で取る。

なぜ作ったか:
    project_status には長く「登録済み 774 / 未登録 992・手動投入では追いつかない」と
    書いてあったが、これは GSC UI の合計を読んだだけで**内訳が分かっていなかった**。
    実際に数えると docs/ の HTML 2,187本のうち 1,363本は意図的な noindex で、
    indexable は 824本。つまり「未登録 992」の大半は狙いどおりの noindex だった。

    残る問題は「indexable なのに検索露出がゼロ」のページで、これは
    ① Google がまだ URL を知らない ② クロール済みだが未登録 ③ 別 URL に正規化された
    のどれかで打ち手が全く違う。手動投入（1日3〜11本の枠）をどれに使うかは
    この区別が付かないと決められない。

使い方:
    python analytics/gsc/inspect_urls.py --zero-impression   # 露出ゼロの indexable を実査
    python analytics/gsc/inspect_urls.py --section fish      # 種別を絞る
    python analytics/gsc/inspect_urls.py --url <URL>         # 1本だけ
    python analytics/gsc/inspect_urls.py --report            # 前回結果を読み直すだけ

出力: analytics/gsc/inspection.json（URL -> 実査結果。次回は --refresh するまで再利用）

⚠ URL Inspection API のクォータは 1日 2,000 / 1分 600。既定で 0.15 秒待つ。
"""
import sys, os, json, csv, glob, re, time, argparse, collections

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "analytics"))
DOCS = os.path.join(ROOT, "docs")
SITE = "https://funatsuri-yoso.com/"
OUT = os.path.join(ROOT, "analytics", "gsc", "inspection.json")
GSC_PAGES_GLOB = os.path.join(ROOT, "analytics", "gsc", "pages", "*.csv")
SCOPES = ["https://www.googleapis.com/auth/webmasters.readonly"]

NOINDEX_RE = re.compile(r'<meta[^>]+name=["\']robots["\'][^>]*noindex', re.I)

# coverageState は日本語の自由文で返る。打ち手ごとにまとめるための分類。
BUCKETS = [
    ("未発見",   ["認識されていません", "not known", "Discovered"],
     "Google が URL 自体を知らない。sitemap にあっても発見されないので"
     "内部リンクを増やすか手動投入する"),
    ("クロール済み未登録", ["クロール済み", "Crawled - currently not indexed"],
     "取得はされたが載せる価値なしと判断された。中身を厚くする以外に手がない。"
     "手動投入しても再び落ちる"),
    ("発見のみ未クロール", ["検出", "Discovered - currently not indexed"],
     "発見済みだがクロール予算が回っていない。内部リンク/更新頻度で優先度を上げる"),
    ("正規化で別URL", ["正規", "canonical", "Duplicate", "重複"],
     "別 URL に統合された。canonical か中身の重複を疑う"),
    ("登録済み",  ["登録されています", "Submitted and indexed", "インデックスに登録済み"],
     "インデックス済み。露出ゼロなら順位が低いだけで、打ち手は中身か内部リンク"),
]


def bucket_of(state):
    s = state or ""
    for name, keys, _ in BUCKETS:
        if any(k in s for k in keys):
            return name
    return f"その他({s})"


def local_urls():
    """docs/ 配下の URL を indexable / noindex に分けて返す。"""
    idxable, noindex = set(), set()
    for f in glob.glob(os.path.join(DOCS, "**", "*.html"), recursive=True):
        rel = os.path.relpath(f, DOCS).replace(os.sep, "/")
        url = SITE + (rel[: -len("index.html")] if rel.endswith("index.html") else rel)
        head = open(f, encoding="utf-8", errors="replace").read(4000)
        (noindex if NOINDEX_RE.search(head) else idxable).add(url)
    return idxable, noindex


def impressions_by_url():
    seen = collections.defaultdict(int)
    for p in sorted(glob.glob(GSC_PAGES_GLOB)):
        with open(p, encoding="utf-8", newline="") as f:
            for r in csv.DictReader(f):
                try:
                    seen[r["page"]] += int(r["impressions"])
                except (ValueError, KeyError):
                    continue
    return seen


def load_cache():
    if os.path.isfile(OUT):
        try:
            return json.load(open(OUT, encoding="utf-8"))
        except Exception:
            pass
    return {}


def inspect(urls, cache, delay=0.15, refresh=False):
    import analytics_common as ac
    if not ac.has_credentials():
        sys.exit("[inspect] GOOGLE_SA_KEY / GOOGLE_SA_KEY_FILE 未設定")
    from googleapiclient.discovery import build
    svc = build("searchconsole", "v1", credentials=ac.load_credentials(SCOPES),
                cache_discovery=False)
    todo = [u for u in urls if refresh or u not in cache]
    print(f"[inspect] 対象 {len(urls)} 本 / 今回問い合わせ {len(todo)} 本"
          f"（キャッシュ流用 {len(urls) - len(todo)} 本）")
    for n, u in enumerate(todo, 1):
        try:
            r = svc.urlInspection().index().inspect(body={
                "inspectionUrl": u, "siteUrl": SITE, "languageCode": "ja"}).execute()
            idx = r.get("inspectionResult", {}).get("indexStatusResult", {})
            cache[u] = {k: idx.get(k) for k in
                        ("verdict", "coverageState", "robotsTxtState", "indexingState",
                         "lastCrawlTime", "pageFetchState", "googleCanonical")}
        except Exception as e:
            cache[u] = {"error": f"{type(e).__name__}: {str(e)[:200]}"}
        if n % 25 == 0:
            print(f"  {n}/{len(todo)} …")
            json.dump(cache, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        time.sleep(delay)
    json.dump(cache, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return cache


def report(urls, cache, seen):
    got = {u: cache[u] for u in urls if u in cache and "error" not in cache[u]}
    err = [u for u in urls if u in cache and "error" in cache[u]]
    if not got:
        print("実査結果がない。--zero-impression などを付けて実行する")
        return
    by = collections.defaultdict(list)
    for u, v in got.items():
        by[bucket_of(v.get("coverageState"))].append(u)
    print("\n" + "=" * 78)
    print(f"URL Inspection 実査 {len(got)} 本" + (f"（エラー {len(err)} 本）" if err else ""))
    print("=" * 78)
    hints = {name: hint for name, _, hint in BUCKETS}
    for name, lst in sorted(by.items(), key=lambda x: -len(x[1])):
        print(f"\n■ {name}: {len(lst)} 本")
        if name in hints:
            print(f"   → {hints[name]}")
        sec = collections.Counter(
            (u.replace(SITE, "").split("/")[0] if "/" in u.replace(SITE, "") else "(root)")
            for u in lst)
        print("   種別: " + " / ".join(f"{k} {v}" for k, v in sec.most_common()))
        for u in sorted(lst)[:8]:
            crawl = (got[u].get("lastCrawlTime") or "未クロール")[:10]
            print(f"     {u.replace(SITE, ''):42s} 最終クロール {crawl}")
        if len(lst) > 8:
            print(f"     …ほか {len(lst) - 8} 本")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--zero-impression", action="store_true",
                    help="indexable なのに GSC 露出ゼロの URL を対象にする")
    ap.add_argument("--section", help="種別で絞る（fish / area / fish_area / ship …）")
    ap.add_argument("--url", help="1本だけ実査")
    ap.add_argument("--report", action="store_true", help="問い合わせず前回結果だけ出す")
    ap.add_argument("--refresh", action="store_true", help="キャッシュを無視して取り直す")
    ap.add_argument("--limit", type=int, default=400, help="1回の上限（既定400・クォータ2000/日）")
    args = ap.parse_args()

    cache = load_cache()
    if args.url:
        urls = [args.url if args.url.startswith("http") else SITE + args.url.lstrip("/")]
    else:
        idxable, _ = local_urls()
        seen = impressions_by_url()
        urls = sorted(idxable - {u for u, v in seen.items() if v > 0}) \
            if args.zero_impression else sorted(idxable)
        if args.section:
            urls = [u for u in urls
                    if u.replace(SITE, "").split("/")[0] == args.section]
        urls = urls[: args.limit]

    if not args.report:
        cache = inspect(urls, cache, refresh=args.refresh)
    report(urls, cache, impressions_by_url())


if __name__ == "__main__":
    main()
