#!/usr/bin/env python3
"""
A: Search Console データ取得（検索クエリ・表示回数・クリック・掲載順位）

ソース   : Google Search Console API（searchanalytics.query）
認証     : サービスアカウント（GOOGLE_SA_KEY）。GSC プロパティに閲覧権限付与が前提。
出力     : analytics/gsc/YYYY-MM.csv          （date+query+page キー・クエリ分析用）
           analytics/gsc/pages/YYYY-MM.csv    （date+page キー・ページ/サイト実績用）
           analytics/gsc/discover/YYYY-MM.csv （date+page キー・Discover 実績用）
           ⚠ query 次元を入れると GSC は低頻度クエリを匿名化して落とすため、
             gsc/*.csv の合計は真値の約 1/3 にしかならない（2026-09-05 実測）。
             ページ別 CTR・サイト KPI は必ず gsc/pages/*.csv から出すこと。
実行     : python analytics/fetch_gsc.py [--days 30]

GSC データは最終確定まで 2〜3 日かかるため、毎回直近 N 日を再取得し既存行を上書きする。
未確定日は後日の再実行で正しい値に収束する。

Discover（2026-10-03 追加）:
  GSC の検索パフォーマンスは type を指定しないと web のみを返す。Discover は
  別 type で取らないと**存在が一切見えない**（GA4 側では Discover 流入が
  Organic Search や Unassigned に混ざるため切り分けられない）。
  Discover は仕様上 query 次元・掲載順位を持たないので、次元は date+page のみ、
  CSV も position 列を持たない。Discover 対象外のサイトは 0 行が返る
  （エラーではない）。API が type 不正等で失敗した場合は web の取得結果を
  捨てないよう warn だけ出して続行する。

環境変数:
  GOOGLE_SA_KEY       サービスアカウント JSON 文字列（必須・GitHub Actions Secret）
  GSC_SITE_URL        対象プロパティ。既定 'https://funatsuri-yoso.com/'
                      ドメインプロパティの場合は 'sc-domain:funatsuri-yoso.com' を指定
  GSC_FETCH_DAYS      取得日数（既定 30）
  GSC_DISCOVER_DAYS   Discover の取得日数（既定は --days と同じ）。初回の存在確認は
                      `--discover-days 480`（16か月＝GSC の保持上限）で遡る

google-api-python-client / google-auth 未導入、または認証情報未設定の場合は
graceful skip（exit 0）。GitHub Actions で Secret 未登録のうちはスキップされる。
"""
import argparse
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import analytics_common as ac

SCOPES = ["https://www.googleapis.com/auth/webmasters.readonly"]
DEFAULT_SITE = "https://funatsuri-yoso.com/"
ROW_LIMIT = 25000  # 1 リクエスト上限。超える日は startRow ページングで取り切る

# ── 2つの次元セットを別ファイルに蓄積する（2026-09-05） ──
# query 次元を入れると GSC は**低頻度クエリの行を匿名化して落とす**。
# 実測（API で次元なしの合計と突き合わせ）:
#     2026-07  真値 292click / 11,933impr  →  date+query+page は  94click /  4,597impr（click 捕捉 32%）
#     2026-08  真値 424click / 21,970impr  →  date+query+page は 132click /  7,002impr（click 捕捉 31%）
#     date+page なら 2か月とも 100% 一致
# しかも捕捉率はページごとに 9%〜71% とばらつく＝**非ランダムな欠測**。
# クエリ次元の CSV だけでページ別 CTR を比べると順位が入れ替わる
# （例 area/futtsu.html は真値 1.99% なのにクエリ次元では 0.41%）。
#   gsc/YYYY-MM.csv        … クエリ分析用（何で来たか）。合計値としては使えない
#   gsc/pages/YYYY-MM.csv  … ページ/サイトの実績（どれだけ来たか）。KPI はこちら
QUERY_DIMENSIONS = ["date", "query", "page"]
QUERY_FIELDNAMES = ["date", "query", "page", "clicks", "impressions", "ctr", "position"]
QUERY_KEY_FIELDS = ["date", "query", "page"]

PAGE_DIMENSIONS = ["date", "page"]
PAGE_FIELDNAMES = ["date", "page", "clicks", "impressions", "ctr", "position"]
PAGE_KEY_FIELDS = ["date", "page"]

# ── Discover（type=discover・2026-10-03） ──
# Discover は検索結果ではないので query も掲載順位も存在しない。
# API に query 次元を渡すと 400 になるため date+page 固定。position 列も作らない
# （upsert_csv が fieldnames で絞るので API が 0 を返しても CSV には入らない）。
DISCOVER_DIMENSIONS = ["date", "page"]
DISCOVER_FIELDNAMES = ["date", "page", "clicks", "impressions", "ctr"]
DISCOVER_KEY_FIELDS = ["date", "page"]

# 後方互換（外部から参照されていた場合のため）
DIMENSIONS = QUERY_DIMENSIONS
FIELDNAMES = QUERY_FIELDNAMES
KEY_FIELDS = QUERY_KEY_FIELDS


def fetch_range(service, site_url, start_date, end_date, dimensions=None,
                search_type="web"):
    """指定期間の検索パフォーマンス行を全件取得して dict のリストで返す。

    search_type: "web"（既定・従来挙動）/ "discover" / "news" など。
                 API の body["type"]。省略時は web 相当。
    """
    dimensions = dimensions or QUERY_DIMENSIONS
    rows = []
    start_row = 0
    while True:
        body = {
            "startDate": start_date,
            "endDate": end_date,
            "dimensions": dimensions,
            "rowLimit": ROW_LIMIT,
            "startRow": start_row,
            "dataState": "all",  # 未確定（fresh）データも含める
            "type": search_type,
        }
        resp = service.searchanalytics().query(siteUrl=site_url, body=body).execute()
        batch = resp.get("rows", [])
        for r in batch:
            keys = r.get("keys", [])
            row = {d: (keys[i] if len(keys) > i else "") for i, d in enumerate(dimensions)}
            row.update({
                "clicks": r.get("clicks", 0),
                "impressions": r.get("impressions", 0),
                "ctr": round(r.get("ctr", 0.0), 6),
                "position": round(r.get("position", 0.0), 2),
            })
            rows.append(row)
        if len(batch) < ROW_LIMIT:
            break
        start_row += ROW_LIMIT
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int,
                        default=int(os.environ.get("GSC_FETCH_DAYS") or "30"))
    parser.add_argument("--discover-days", type=int,
                        default=int(os.environ.get("GSC_DISCOVER_DAYS") or "0"),
                        help="Discover の取得日数（0=--days と同じ）。"
                             "初回の存在確認は 480（16か月）")
    args = parser.parse_args()

    if not ac.has_credentials():
        print("[fetch_gsc] GOOGLE_SA_KEY 未設定 → スキップ（Secret 登録後に有効化）")
        return 0
    try:
        from googleapiclient.discovery import build
    except ImportError:
        print("[fetch_gsc] google-api-python-client 未導入 → スキップ")
        return 0

    site_url = os.environ.get("GSC_SITE_URL", DEFAULT_SITE)
    end = dt.date.today()
    # GSC は当日・前日が未確定なので余裕を持って今日まで要求（dataState=all）
    start = end - dt.timedelta(days=args.days)

    creds = ac.load_credentials(SCOPES)
    service = build("searchconsole", "v1", credentials=creds, cache_discovery=False)

    print(f"[fetch_gsc] site={site_url} range={start}..{end}")

    total_add = total_upd = 0
    for label, dims, fields, keys, subdir in (
        ("query", QUERY_DIMENSIONS, QUERY_FIELDNAMES, QUERY_KEY_FIELDS, ""),
        ("page", PAGE_DIMENSIONS, PAGE_FIELDNAMES, PAGE_KEY_FIELDS, "pages"),
    ):
        rows = fetch_range(service, site_url, start.isoformat(), end.isoformat(), dims)
        clk = sum(r["clicks"] for r in rows)
        imp = sum(r["impressions"] for r in rows)
        print(f"[fetch_gsc] {label:5s} 次元 {'+'.join(dims):18s} "
              f"取得 {len(rows)} 行 / {clk} click / {imp} impr")
        for ym, grp in ac.group_rows_by_month(rows).items():
            out = os.path.join(ac.ANALYTICS_DIR, "gsc", subdir, f"{ym}.csv")
            os.makedirs(os.path.dirname(out), exist_ok=True)
            a, u = ac.upsert_csv(out, fields, keys, grp)
            total_add += a
            total_upd += u
            print(f"  {ym}: +{a} 追加 / {u} 更新 → {os.path.relpath(out, ac.ANALYTICS_DIR)}")
    # ── Discover（2026-10-03） ──
    # web とは期間を分けられる（初回だけ 16か月遡って存在確認したいため）。
    # Discover 非対象サイトは 0 行。type 未対応等で API が落ちても web の成果は
    # すでに書き込み済みなので、ここでは warn のみで exit 0 を維持する。
    d_days = args.discover_days or args.days
    d_start = end - dt.timedelta(days=d_days)
    try:
        d_rows = fetch_range(service, site_url, d_start.isoformat(), end.isoformat(),
                             DISCOVER_DIMENSIONS, search_type="discover")
    except Exception as e:
        print(f"[fetch_gsc] ⚠ discover 取得失敗（web は取得済み）: {type(e).__name__}: {e}")
        d_rows = None

    if d_rows is not None:
        d_clk = sum(r["clicks"] for r in d_rows)
        d_imp = sum(r["impressions"] for r in d_rows)
        print(f"[fetch_gsc] disc. 次元 {'+'.join(DISCOVER_DIMENSIONS):18s} "
              f"取得 {len(d_rows)} 行 / {d_clk} click / {d_imp} impr "
              f"（range={d_start}..{end}）")
        if not d_rows:
            print("[fetch_gsc] → Discover の実績なし。"
                  "この期間に Discover に掲載されていない（エラーではない）")
        for ym, grp in ac.group_rows_by_month(d_rows).items():
            out = os.path.join(ac.ANALYTICS_DIR, "gsc", "discover", f"{ym}.csv")
            os.makedirs(os.path.dirname(out), exist_ok=True)
            a, u = ac.upsert_csv(out, DISCOVER_FIELDNAMES, DISCOVER_KEY_FIELDS, grp)
            total_add += a
            total_upd += u
            print(f"  {ym}: +{a} 追加 / {u} 更新 → {os.path.relpath(out, ac.ANALYTICS_DIR)}")

    print(f"[fetch_gsc] 完了 追加{total_add} / 更新{total_upd}")
    print("[fetch_gsc] ※ gsc/*.csv は匿名化で click の約1/3しか含まない。"
          "ページ/サイトの実績は gsc/pages/*.csv を使うこと")
    return 0


if __name__ == "__main__":
    sys.exit(main())
