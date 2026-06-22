#!/usr/bin/env python3
"""
A: GA4 データ取得（UU・PV・セッション・流入元・ページ別）

ソース   : Google Analytics Data API v1beta（properties.runReport）
認証     : サービスアカウント（GOOGLE_SA_KEY）。GA4 プロパティに閲覧者権限付与が前提。
出力     : analytics/ga4/YYYY-MM.csv（date+channel+pagePath をキーに upsert）
実行     : python analytics/fetch_ga4.py [--days 30]

環境変数:
  GOOGLE_SA_KEY       サービスアカウント JSON 文字列（必須・GitHub Actions Secret）
  GA4_PROPERTY_ID     GA4 の数値プロパティ ID（必須）。例 '123456789'
                      ※ 計測ID（G-LS469BTBBX）ではない。GA4 管理→プロパティ設定で確認
  GA4_FETCH_DAYS      取得日数（既定 30）

GA4 は当日データが暫定値なので毎回直近 N 日を再取得し既存行を上書きする。

google-api-python-client / google-auth 未導入、または認証情報未設定・
GA4_PROPERTY_ID 未設定の場合は graceful skip（exit 0）。
"""
import argparse
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import analytics_common as ac

SCOPES = ["https://www.googleapis.com/auth/analytics.readonly"]

# 次元: 日付 / 流入チャネル / ページパス、指標: UU / PV / セッション / エンゲージ率
DIMENSIONS = ["date", "sessionDefaultChannelGroup", "pagePath"]
METRICS = ["activeUsers", "screenPageViews", "sessions", "engagementRate"]

FIELDNAMES = ["date", "channel", "pagePath",
              "activeUsers", "screenPageViews", "sessions", "engagementRate"]
KEY_FIELDS = ["date", "channel", "pagePath"]

ROW_LIMIT = 100000


def _fmt_date(ga_date):
    """GA4 の 'YYYYMMDD' を 'YYYY-MM-DD' に整形。"""
    if len(ga_date) == 8 and ga_date.isdigit():
        return f"{ga_date[:4]}-{ga_date[4:6]}-{ga_date[6:]}"
    return ga_date


def fetch_range(service, property_id, start_date, end_date):
    """指定期間の GA4 レポート行を全件取得して dict のリストで返す。"""
    rows = []
    offset = 0
    while True:
        body = {
            "dateRanges": [{"startDate": start_date, "endDate": end_date}],
            "dimensions": [{"name": d} for d in DIMENSIONS],
            "metrics": [{"name": m} for m in METRICS],
            "limit": ROW_LIMIT,
            "offset": offset,
        }
        resp = service.properties().runReport(
            property=f"properties/{property_id}", body=body).execute()
        batch = resp.get("rows", [])
        for r in batch:
            dv = [d.get("value", "") for d in r.get("dimensionValues", [])]
            mv = [m.get("value", "") for m in r.get("metricValues", [])]
            rows.append({
                "date": _fmt_date(dv[0]) if len(dv) > 0 else "",
                "channel": dv[1] if len(dv) > 1 else "",
                "pagePath": dv[2] if len(dv) > 2 else "",
                "activeUsers": mv[0] if len(mv) > 0 else "",
                "screenPageViews": mv[1] if len(mv) > 1 else "",
                "sessions": mv[2] if len(mv) > 2 else "",
                "engagementRate": (round(float(mv[3]), 6) if len(mv) > 3 and mv[3] else ""),
            })
        row_count = resp.get("rowCount", len(batch))
        offset += len(batch)
        if not batch or offset >= row_count:
            break
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int,
                        default=int(os.environ.get("GA4_FETCH_DAYS", "30")))
    args = parser.parse_args()

    property_id = os.environ.get("GA4_PROPERTY_ID", "").strip()
    if not ac.has_credentials():
        print("[fetch_ga4] GOOGLE_SA_KEY 未設定 → スキップ（Secret 登録後に有効化）")
        return 0
    if not property_id:
        print("[fetch_ga4] GA4_PROPERTY_ID 未設定 → スキップ（数値プロパティ ID を設定）")
        return 0
    try:
        from googleapiclient.discovery import build
    except ImportError:
        print("[fetch_ga4] google-api-python-client 未導入 → スキップ")
        return 0

    end = dt.date.today()
    start = end - dt.timedelta(days=args.days)

    creds = ac.load_credentials(SCOPES)
    service = build("analyticsdata", "v1beta", credentials=creds, cache_discovery=False)

    print(f"[fetch_ga4] property={property_id} range={start}..{end}")
    rows = fetch_range(service, property_id, start.isoformat(), end.isoformat())
    print(f"[fetch_ga4] 取得 {len(rows)} 行")

    total_add = total_upd = 0
    for ym, grp in ac.group_rows_by_month(rows).items():
        out = os.path.join(ac.ANALYTICS_DIR, "ga4", f"{ym}.csv")
        a, u = ac.upsert_csv(out, FIELDNAMES, KEY_FIELDS, grp)
        total_add += a
        total_upd += u
        print(f"  {ym}: +{a} 追加 / {u} 更新 → {os.path.relpath(out, ac.ANALYTICS_DIR)}")
    print(f"[fetch_ga4] 完了 追加{total_add} / 更新{total_upd}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
