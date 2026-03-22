# 船釣り予想 (funatsuri-yoso.com) プロジェクト

## プロジェクト概要

**サイト名**: 関東船釣り釣果情報「船釣り予想」  
**URL**: https://funatsuri-yoso.com  
**旧URL**: https://cooker-fisher.github.io/kanto-fishing/  
**コンセプト**: 「来週末、何を狙えば一番釣れるか」がわかるサイト  
**GitHubリポジトリ**: https://github.com/Cooker-fisher/kanto-fishing

### 競合との差別化
- 釣りビジョン = 個別船宿の詳細記録
- 船釣り.jp (funaduri.jp) = 船宿・口コミのデータベース＋年間傾向グラフ
- **funatsuri-yoso.com = 横断集計＋予測で意思決定を助ける（ここが独自価値）**

---

## インフラ・デプロイ

| 項目 | 内容 |
|------|------|
| ホスティング | GitHub Pages |
| 独自ドメイン | funatsuri-yoso.com（お名前.comで取得・初年度0円） |
| DNS | お名前.com（01〜04.dnsv.jp）→ AレコードはGitHub Pages IP |
| HTTPS | Enforce HTTPS 有効化済み |
| 自動更新 | GitHub Actions（毎日16:30 JST / cron: '30 7 * * *'） |
| 手動実行 | GitHub ActionsタブのRun workflowボタン（workflow_dispatch設定済み） |

---

## ファイル構成

```
kanto-fishing/
├── crawler.py          # メインクローラー・HTML生成
├── discover_ships.py   # 釣りビジョンから船宿SIDを自動収集（月1実行）
├── ships.json          # 収集済み船宿一覧（discover_ships.py が生成）
├── catches.json        # 最新釣果データ（毎日上書き）
├── history.json        # 週次・月次集計データ（蓄積）
├── history_crawl.py    # 過去データ一括取得スクリプト（全ページ遡り）
├── index.html          # トップページ（自動生成）
├── calendar.html       # 釣りものカレンダーページ（自動生成）
├── fish/               # 魚種別ページ（自動生成・1件以上の魚種）
│   ├── アジ.html
│   ├── マダイ.html
│   └── ...
├── area/               # エリア別ページ（自動生成）
├── CNAME               # funatsuri-yoso.com
├── .claude/
│   └── launch.json     # 開発サーバー設定（Static File Server / Crawler build）
└── .github/workflows/
    └── crawl.yml       # GitHub Actions定義（毎日+月1日に船宿発見）
```

---

## データソース・クロール仕様

**データソース**: 釣りビジョン (fishing-v.jp)  
**URL形式**: `https://www.fishing-v.jp/choka/choka_detail.php?s={sid}&pageID={page}`

| 項目 | 内容 |
|------|------|
| pageID=1 | 最新データ（通常クロール） |
| pageID増加 | 過去に遡る |
| 1船宿あたり | 約77ページ・768件のデータが存在 |
| pageID=5 | 約2ヶ月前 |
| pageID=20 | 約8ヶ月前（2025年7月） |
| pageID=77 | 約2年前（2024年8月） |
| 全取得時間 | 120船宿 × 全ページ ≒ 80〜120分 |

**クロール対象**: 神奈川・東京・千葉・茨城の約89船宿（ships.jsonから自動読み込み）
**船宿自動発見**: discover_ships.py が月1回 fishing-v.jp をスクレイプして ships.json を更新
**対応エリア**: 茨城（日立久慈港・波崎港・鹿島港）、千葉外房（外川・飯岡・片貝・大原・御宿・勝浦）、千葉内房（勝山・保田・金谷・富津）、千葉東京湾奥（浦安）、東京（羽田・平和島）、神奈川東京湾（金沢八景・久比里・久里浜）、神奈川相模湾（松輪・長井・葉山・茅ヶ崎・平塚）

---

## crawler.pyの主要関数

| 関数 | 役割 |
|------|------|
| `crawl(ship)` | 1船宿のpageID=1を取得 |
| `update_history(catches, history)` | 当週・当月データをhistory.jsonに集計・書き込み |
| `build_html(data, ts, n)` | index.htmlを生成 |
| `build_fish_pages(data)` | fish/*.htmlを生成（1件以上の魚種） |
| `build_calendar_page(data)` | calendar.htmlを生成 |
| `calc_targets(data)` | 今週末の狙い目TOP5を複合スコアで計算 |
| `calc_composite_score(...)` | 6要素複合スコア（0〜100）を算出 |
| `build_reason_tags(...)` | おすすめ理由タグ（最大3個）を生成 |
| `build_comment(...)` | 100パターンコメントを生成 |
| `build_target_section(targets)` | 狙い目セクションのHTMLを生成（★評価＋タグ） |
| `get_yoy_data(history, fish, year, week)` | 今週・昨年同週のhistoryデータを取得 |
| `get_prev_week_data(history, fish, year, week)` | 前週のhistoryデータを取得 |
| `main()` | 全体の実行フロー |

---

## データ構造

### catches.json
```json
{
  "crawled_at": "2026/03/15 16:30",
  "total": 493,
  "errors": [],
  "data": [
    {
      "ship": "忠彦丸",
      "area": "金沢八景",
      "date": "2026/03/15",
      "fish": ["アジ"],
      "count_range": {"min": 39, "max": 74},
      "size_range": {"min": 17, "max": 28},
      "catch_raw": "午前ライトアジ 39〜74匹 17〜28cm"
    }
  ]
}
```

### history.json（週次・月次集計）
```json
{
  "weekly": {
    "2026/W11": {
      "アジ": {"ships": 53, "avg": 32.4, "max": 116, "size_avg": 24.5}
    }
  },
  "monthly": {
    "2026/03": {
      "アジ": {"ships": 103, "avg": 28.1, "max": 116, "size_avg": 23.8}
    }
  }
}
```

---

## FISH_MASTER（魚種マスターデータ）

crawler.py内に定義済み。各魚種の以下の情報を持つ：
- `season`: 出船期間の月リスト
- `peak_num`: 数狙いピーク月
- `peak_size`: 型狙いピーク月
- `axis`: 狙いの軸（「数◎」「型◎」「数＆型」など）
- `comment`: 説明文

---

## 実装済み機能

1. ✅ 釣果自動収集（釣りビジョンHTMLパース・毎日更新）
2. ✅ 魚種カードをタップでランキング表示（船宿別TOP10・バーグラフ）
3. ✅ 今週末の狙い目セクション（★評価＋理由タグ＋100パターンコメント）
4. ✅ 複合スコアリング（件数25%・匹数20%・昨年比20%・先週比15%・シーズン15%・サイズ5%）
5. ✅ 魚種カードに昨年比バッジ・平均匹数・前週比トレンド表示
6. ✅ 魚種別ページ（fish/*.html・SEOタイトル・metadescription・1件以上で生成）
7. ✅ history.jsonへの自動集計（毎クロール時に当週・当月データ更新）
8. ✅ SEASON_DATAに20魚種以上（マルイカ・クロムツ・サワラ・メダイ・マハタ・カンパチ追加済み）
9. ✅ 釣りものカレンダー（calendar.html・14魚種×12ヶ月）
10. ✅ GitHub Actions手動実行ボタン（workflow_dispatch）
11. ✅ ナビゲーションの「エリアから探す」をドロップダウンメニュー化（都道府県グループ別）
12. ✅ 最新釣果エリアフィルターを都道府県グループ別 + 港ページへリンク化
13. ✅ discover_ships.py による船宿SID自動収集（26→89船宿に拡大）
14. ✅ ships.json 自動読み込み（crawler.py起動時に上書き）
15. ✅ crawl.yml 月1日に discover_ships.py 実行（船宿リスト自動更新）

---

## 今後の実装予定

### 優先度高
- [ ] history_crawl.pyで過去2年分のデータ一括取得（history.jsonを充実させる）
- [ ] 魚種別ページに「今週vs昨年同週比較」テーブル表示（出船数・平均匹数・Max匹数）
- [ ] Google AdSense審査結果確認・承認後の動作確認（申請済み 2026/03/21）

### 優先度中
- [ ] X（Twitter）自動投稿（毎日16:30に狙い目を投稿）
  - X APIキー取得済み（アカウントロック解除待ち）
  - `tweet_poster.py` の作成
  - GitHub Secrets: X_API_KEY / X_API_SECRET / X_ACCESS_TOKEN / X_ACCESS_SECRET
- [ ] じゃらんアフィリエイト設置（ランキングの船宿横に予約リンク）
- [ ] 地図でエリア選択UI

### 優先度低
- [ ] crawl.yml Node.js 20→24 upgrade
- [ ] 魚種別ページのデザイン改善
- [ ] 関西・九州など全国展開（釣りビジョンは全国対応済み）

---

## 比較データの設計方針

「出船件数が多いか少ないか」の判断は絶対数ではなく**相対比較**が必要：
- アジは通年コンスタントに出るため、単純な件数では判断できない
- 同じ週・同じ魚種の**昨年比・過去平均**と比較することで意味が生まれる
- 船釣り.jpは「過去5年平均を100%とした相対値」で表示している

### 表示イメージ
```
アジ  今週53隻（昨年同週45隻 → 平年比+18% 🔥）
      今週平均32匹（昨年同週28匹 → +14%）
      今週Max116匹（昨年同週98匹 → +18%）
```

---

## 開発環境（ローカル）

| ツール | バージョン |
|--------|----------|
| OS | Windows 11 |
| Git | 2.53.0 |
| Python | 3.14.3 |
| Node.js | 25.8.1 |
| VS Code | 最新版 |
| Claude Code | v2.1.76 |

### ローカル確認手順
```powershell
cd $env:USERPROFILE\Desktop\kanto-fishing
python crawler.py          # データ取得・HTML生成
python -m http.server 8000 # ローカルサーバー起動
# → http://localhost:8000 で確認
```

### Gitプッシュ手順
```powershell
git add -A
git commit -m "変更内容"
git push
```

---

## 注意事項

- crawler.pyは**標準ライブラリのみ**（外部依存なし）
- history_crawl.pyも同様に標準ライブラリのみで動作する
- 釣りビジョンへのリクエストは0.8秒待機（サーバー負荷対策）
- GitHub ActionsのタイムゾーンはUTC（16:30 JSTは07:30 UTC）
- fish/*.htmlのファイル名は日本語（URLエンコードされる）

---

@.claude/memory/project_status.md
@.claude/memory/feedback_crawler_editing.md
