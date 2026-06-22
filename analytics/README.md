# analytics — Search Console / GA4 データ取得

Google Search Console（検索クエリ・順位）と GA4（UU・PV・流入）を API で毎日取得し、
月別 CSV に蓄積する。SEO 改善・集客分析の材料にする。

> AdSense は本ディレクトリ未対応（サービスアカウント非対応で OAuth が必要なため後回し）。

## 構成

```
analytics/
├── fetch_gsc.py          # Search Console 取得 → analytics/gsc/YYYY-MM.csv
├── fetch_ga4.py          # GA4 取得 → analytics/ga4/YYYY-MM.csv
├── seo_report.py         # GSC+GA4 → SEO・集客レポート（標準ライブラリのみ）
├── analytics_common.py   # 認証・CSV upsert 共通処理
├── requirements.txt      # google-api-python-client / google-auth
├── gsc/YYYY-MM.csv       # date,query,page,clicks,impressions,ctr,position
├── ga4/YYYY-MM.csv       # date,channel,pagePath,activeUsers,screenPageViews,sessions,engagementRate
└── report/
    ├── latest.md         # 最新レポート（上書き）
    └── YYYY-MM-DD.md     # 日付スナップショット
```

## レポート（seo_report.py）

`fetch_*` の蓄積 CSV から SEO・集客レポートを生成する（追加依存なし）。
ワークフローで毎日 fetch 後に自動再生成され `analytics/report/latest.md` に出力。

```bash
python analytics/seo_report.py --window 28
```

含む分析:
- **週次サマリー**: 直近7日 vs 前7日のクリック/表示/UU/PV 増減
- **惜しいクエリ**: 6〜20位で表示はあるがクリックが伸びてない検索語（title/見出し強化で1ページ目を狙う SEO 即効ネタ）+ 対象ページ
- **集客ページ TOP20**: GA4 ページ別 UU/PV（魚種/エリア/予報 種別ラベル付き）
- **魚種別・エリア別 集客**: pagePath を集約した UU ランキング

自動実行: `.github/workflows/analytics.yml`（毎日 06:00 JST + 手動 workflow_dispatch）。
Secret 未登録のうちは graceful skip するので、コードを先に入れても CI は壊れない。

---

## セットアップ（所要 15〜20 分・ブラウザ作業）

### 1. GCP プロジェクト + API 有効化
1. https://console.cloud.google.com/ でプロジェクト作成（例: `funatsuri-analytics`）
2. 「API とサービス」→「ライブラリ」で以下 2 つを有効化:
   - **Google Search Console API**
   - **Google Analytics Data API**

### 2. サービスアカウント + 鍵作成
1. 「API とサービス」→「認証情報」→「認証情報を作成」→「サービスアカウント」
2. 名前を付けて作成（ロール付与は不要・スキップ可）
3. 作成したサービスアカウントを開く →「キー」→「鍵を追加」→「JSON」
4. JSON ファイルがダウンロードされる。中の `client_email`
   （`xxx@xxx.iam.gserviceaccount.com`）を控える

### 3. 各プロパティに閲覧権限を付与
- **Search Console**: https://search.google.com/search-console
  → 対象プロパティ → 設定 → ユーザーと権限 → ユーザーを追加
  → サービスアカウントのメール / 権限「制限付き」
- **GA4**: https://analytics.google.com → 管理（歯車）→ プロパティのアクセス管理
  → 「+」→ サービスアカウントのメール / 役割「閲覧者」
  → 同じく管理画面でプロパティ設定を開き **プロパティ ID（数値）** を控える
  （計測 ID `G-LS469BTBBX` とは別物）

### 4. GitHub Secrets 登録
リポジトリ → Settings → Secrets and variables → Actions → New repository secret

| Secret 名 | 値 | 必須 |
|---|---|---|
| `GOOGLE_SA_KEY` | ダウンロードした JSON ファイルの**中身全文** | ✅ |
| `GA4_PROPERTY_ID` | GA4 の数値プロパティ ID（例 `123456789`） | ✅（GA4 用） |
| `GSC_SITE_URL` | 既定 `https://funatsuri-yoso.com/`。ドメインプロパティなら `sc-domain:funatsuri-yoso.com` | 任意 |

### 5. 動作確認
Actions タブ →「analytics」→「Run workflow」で手動実行。
ログに `取得 N 行` が出て `analytics/gsc/`・`analytics/ga4/` に CSV がコミットされれば成功。

---

## ローカル実行（任意）

```bash
pip install -r analytics/requirements.txt
export GOOGLE_SA_KEY_FILE=/path/to/key.json   # ローカルはファイルパスで可
export GA4_PROPERTY_ID=123456789
python analytics/fetch_gsc.py --days 30
python analytics/fetch_ga4.py --days 30
```

## 仕様メモ
- GSC/GA4 とも直近データは数日かけて確定するため、毎回直近 30 日を再取得し
  同一キー（date+次元）の行を上書き（`upsert_csv`）。未確定日は後日の実行で収束する。
- `GOOGLE_SA_KEY` 未設定・ライブラリ未導入時は両スクリプトとも exit 0 でスキップ。
- 鍵 JSON は **絶対にコミットしない**（Secret / 環境変数経由のみ）。
