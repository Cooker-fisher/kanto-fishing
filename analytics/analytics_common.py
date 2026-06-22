"""
analytics 共通モジュール（Search Console / GA4 取得スクリプト共用）

- 認証: 環境変数 GOOGLE_SA_KEY（サービスアカウント JSON 文字列）から読み込む。
  ローカルではファイルパス GOOGLE_SA_KEY_FILE でも可。
- 蓄積: 月別 CSV（analytics/gsc/YYYY-MM.csv 等）に append-only で upsert。
  GSC データは数日かけて確定するため、同一キー（date+次元）の再取得は上書きする。
- google ライブラリ未導入 / 認証情報未設定でも import 自体は失敗させない。
  fetch スクリプト側で has_credentials() を見て graceful skip する。
"""
import csv
import json
import os

# このファイルの場所 = analytics/ をルートに
ANALYTICS_DIR = os.path.dirname(os.path.abspath(__file__))


def has_credentials():
    """サービスアカウント認証情報が利用可能かを返す（JSON 文字列 or ファイル）。"""
    return bool(os.environ.get("GOOGLE_SA_KEY") or os.environ.get("GOOGLE_SA_KEY_FILE"))


def load_credentials(scopes):
    """
    サービスアカウント認証情報を生成して返す。

    GOOGLE_SA_KEY        = JSON 文字列（GitHub Actions Secret 用・推奨）
    GOOGLE_SA_KEY_FILE   = JSON ファイルパス（ローカル開発用）

    google-auth が未導入の場合は ImportError をそのまま投げる
    （呼び出し側は has_credentials() で事前に弾く想定）。
    """
    from google.oauth2 import service_account  # 遅延 import（未導入環境での import 崩壊回避）

    raw = os.environ.get("GOOGLE_SA_KEY")
    if raw:
        info = json.loads(raw)
        return service_account.Credentials.from_service_account_info(info, scopes=scopes)

    path = os.environ.get("GOOGLE_SA_KEY_FILE")
    if path:
        return service_account.Credentials.from_service_account_file(path, scopes=scopes)

    raise RuntimeError("認証情報がありません（GOOGLE_SA_KEY / GOOGLE_SA_KEY_FILE 未設定）")


def upsert_csv(out_path, fieldnames, key_fields, rows):
    """
    月別 CSV に対し key_fields をキーとして upsert（既存は上書き・新規は追加）。

    out_path    : 出力先 CSV パス（ディレクトリは自動作成）
    fieldnames  : CSV の列順
    key_fields  : 重複判定に使う列名のリスト（例: ["date", "query", "page"]）
    rows        : dict のリスト（各 dict は fieldnames を網羅）

    戻り値: (追加件数, 更新件数)
    """
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    def keyof(d):
        return tuple(str(d.get(k, "")) for k in key_fields)

    existing = {}
    if os.path.exists(out_path):
        with open(out_path, "r", encoding="utf-8", newline="") as f:
            for r in csv.DictReader(f):
                existing[keyof(r)] = r

    added = updated = 0
    for r in rows:
        k = keyof(r)
        # fieldnames に揃える（欠損は空文字）
        norm = {fn: r.get(fn, "") for fn in fieldnames}
        if k in existing:
            updated += 1
        else:
            added += 1
        existing[k] = norm

    # date 昇順 → 残りキー昇順で安定ソート
    def sortkey(item):
        d = item[1]
        return tuple(str(d.get(k, "")) for k in key_fields)

    ordered = [v for _, v in sorted(existing.items(), key=sortkey)]

    with open(out_path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in ordered:
            w.writerow({fn: r.get(fn, "") for fn in fieldnames})

    return added, updated


def month_path(subdir, date_str):
    """date_str(YYYY-MM-DD) → analytics/<subdir>/YYYY-MM.csv のパスを返す。"""
    ym = date_str[:7]
    return os.path.join(ANALYTICS_DIR, subdir, f"{ym}.csv")


def group_rows_by_month(rows, date_key="date"):
    """rows を YYYY-MM ごとに分割した dict を返す。"""
    out = {}
    for r in rows:
        ym = str(r.get(date_key, ""))[:7]
        out.setdefault(ym, []).append(r)
    return out
