#!/usr/bin/env python3
"""
A: Search Console データ取得（検索クエリ・表示回数・クリック・掲載順位）

ソース   : Google Search Console API（searchanalytics.query）
認証     : サービスアカウント（GOOGLE_SA_KEY）。GSC プロパティに閲覧権限付与が前提。
出力     : analytics/gsc/YYYY-MM.csv（date+query+page をキーに upsert）
実行     : python analytics/fetch_gsc.py [--days 30]

GSC データは最終確定まで 2〜3 日かかるため、毎回直近 N 日を再取得し既存行を上書きする。
未確定日は後日の再実行で正しい値に収束する。

環境変数:
  GOOGLE_SA_KEY       サービスアカウント JSON 文字列（必須・GitHub Actions Secret）
  GSC_SITE_URL        対象プロパティ。既定 'https://funatsuri-yoso.com/'
                      ドメインプロパティの場合は 'sc-domain:funatsuri-yoso.com' を指定
  GSC_FETCH_DAYS      取得日数（既定 30）

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
DIMENSIONS = ["date", "query", "page"]
ROW_LIMIT = 25000  # 1 リクエスト上限。超える日は startRow ページングで取り切る

FIELDNAMES = ["date", "query", "page", "clicks", "impressions", "ctr", "position"]
KEY_FIELDS = ["date", "query", "page"]


def fetch_range(service, site_url, start_date, end_date):
    """指定期間の検索パフォーマンス行を全件取得して dict のリストで返す。"""
    rows = []
    start_row = 0
    while True:
        body = {
            "startDate": start_date,
            "endDate": end_date,
            "dimensions": DIMENSIONS,
            "rowLimit": ROW_LIMIT,
            "startRow": start_row,
            "dataState": "all",  # 未確定（fresh）データも含める
        }
        resp = service.searchanalytics().query(siteUrl=site_url, body=body).execute()
        batch = resp.get("rows", [])
        for r in batch:
            keys = r.get("keys", [])
            rows.append({
                "date": keys[0] if len(keys) > 0 else "",
                "query": keys[1] if len(keys) > 1 else "",
                "page": keys[2] if len(keys) > 2 else "",
                "clicks": r.get("clicks", 0),
                "impressions": r.get("impressions", 0),
                "ctr": round(r.get("ctr", 0.0), 6),
                "position": round(r.get("position", 0.0), 2),
            })
        if len(batch) < ROW_LIMIT:
            break
        start_row += ROW_LIMIT
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int,
                        default=int(os.environ.get("GSC_FETCH_DAYS", "30")))
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
    rows = fetch_range(service, site_url, start.isoformat(), end.isoformat())
    print(f"[fetch_gsc] 取得 {len(rows)} 行")

    total_add = total_upd = 0
    for ym, grp in ac.group_rows_by_month(rows).items():
        out = os.path.join(ac.ANALYTICS_DIR, "gsc", f"{ym}.csv")
        a, u = ac.upsert_csv(out, FIELDNAMES, KEY_FIELDS, grp)
        total_add += a
        total_upd += u
        print(f"  {ym}: +{a} 追加 / {u} 更新 → {os.path.relpath(out, ac.ANALYTICS_DIR)}")
    print(f"[fetch_gsc] 完了 追加{total_add} / 更新{total_upd}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
