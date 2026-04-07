# 船釣り予想 (funatsuri-yoso.com) プロジェクト

## プロジェクト概要

**サイト名**: 関東船釣り釣果情報「船釣り予想」
**URL**: https://funatsuri-yoso.com
**旧URL**: https://cooker-fisher.github.io/kanto-fishing/
**コンセプト**: 無料ページ：当日の釣果実績。何が釣れたか。客集め。　有料ページ：先１週間の日毎の釣果予想と、先2、3、4週間後の釣果予想。収益
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
├── CLAUDE.md                   # このファイル（Claude Codeへの指示）
├── PIPELINE.md                 # データパイプライン設計図（変更前に必読）
│
├── config.json                 # 分析バージョン管理（active_version: "V2"）
│
├── # ── データ収集・変換スクリプト ──
├── crawler.py                  # メインクローラー＋CSV生成＋HTML生成（毎日自動実行）
│
├── # ── データ収集サブモジュール ──
├── crawl/                      # A1: 釣果クロール関連
│   ├── discover_ships.py       # 船宿SID自動収集（月1実行）
│   └── ships.json              # 収集済み船宿一覧
├── ocean/                      # A2〜A4: 海況・気象・台風・潮汐データ
│   ├── rebuild_weather_cache.py  # 気象・海況データ取得（手動・約30分）
│   ├── build_typhoon.py          # 台風データ取得（手動・年次）
│   ├── build_tide_moon.py        # 潮汐・月齢算出（手動・5秒）
│   ├── weather_cache.sqlite      # 気象・海況（153座標×145万行）※gitignore
│   ├── tide_moon.sqlite          # 月齢・潮汐（1,190日分）
│   └── typhoon.sqlite            # 台風トラック（70台風）
│
├── # ── マスターデータ（JSON）— normalize/ 管理 ──
├── normalize/
│   ├── tsuri_mono_map_draft.json  # 魚種正規化マップ（58魚種）
│   │                              #   ⚠ 構造: m["TSURI_MONO_MAP"]["アジ"] = [...]
│   ├── point_coords.json          # ポイント名→座標（306ポイント）
│   ├── ship_fish_point.json       # 船宿×魚種→ポイント（73船宿）
│   ├── area_coords.json           # エリア代表座標（58エリア）
│   └── ship_wx_coord_override.json # 気象座標上書き
│
├── # ── 釣果データ ──
├── catches_raw.json            # 釣果生データ（84,757件・毎日更新）
├── catches.json                # 当日釣果スナップショット（index.html生成用）
├── history.json                # 週次・月次集計データ（蓄積）
├── data/                       # 月別正規化CSV（data/YYYY-MM.csv・82,650行）
│
├── # ── 分析（バージョン管理） ──
├── analysis/
│   ├── README.md               # バージョン一覧・切替ルール
│   ├── analysis_config.py      # 後工程が results/ を参照するユーティリティ
│   ├── run.py                  # crawl.yml ランチャー（バージョン自動解決）
│   ├── V1/                     # 旧分析（〜2026-03・参照専用）
│   └── V2/                     # 現行分析（2026-04〜）
│       ├── methods/            # 分析スクリプト群（16本）
│       │   ├── _paths.py       # パス自動解決（CLAUDE.md 目印）
│       │   ├── combo_deep_dive.py  # 相関分析（手動実行・51魚種）
│       │   └── ...
│       └── results/            # 分析結果出力先
│           ├── analysis.sqlite # 分析結果DB（combo_decadal等）
│           ├── risk_weekend.txt # 来週末リスクサマリー
│           └── deep_dive/      # 船宿別テキストサマリー
│
├── # ── 自動生成HTML ──
├── index.html
├── calendar.html
├── fish/                       # 魚種別ページ（51魚種）
├── area/                       # エリア別ページ
│
├── CNAME                       # funatsuri-yoso.com
├── .github/workflows/
│   └── crawl.yml               # GitHub Actions定義（毎日+月1日）
└── .claude/
    └── memory/                 # Claude Codeの記憶（会話をまたいで保持）
```

---

## データパイプライン

詳細は **PIPELINE.md** を参照。概要：

```
【A: データ収集】→【B: 正規化・CSV化】→【C: 分析・集計】→【D: 予測（未実装）】→【E: HTML表示】
```

| 層 | 主スクリプト | 出力 | タイミング |
|----|------------|------|----------|
| A1 釣果 | crawler.py | catches_raw.json | 毎日自動 |
| A2 気象 | rebuild_weather_cache.py | weather_cache.sqlite | 手動（約30分） |
| A3 台風 | build_typhoon.py | typhoon.sqlite | 手動（年次） |
| A4 潮汐 | build_tide_moon.py | tide_moon.sqlite | 手動（5秒） |
| B CSV化 | crawler.py | data/YYYY-MM.csv | A1後自動 |
| C 分析 | analysis/V2/methods/combo_deep_dive.py | analysis/V2/results/analysis.sqlite | 手動 |
| D 予測 | 未実装 | - | - |
| E 表示 | crawler.py | *.html | A1後自動 |

**変更前に PIPELINE.md の変更インパクトマトリクスを必ず確認すること。**

---

## データソース・クロール仕様

**データソース**: 釣りビジョン (fishing-v.jp)
**URL形式**: `https://www.fishing-v.jp/choka/choka_detail.php?s={sid}&pageID={page}`

| 項目 | 内容 |
|------|------|
| pageID=1 | 最新データ（通常クロール） |
| pageID増加 | 過去に遡る |
| 全取得時間 | 全ページ取得時 80〜120分 |

**クロール対象**: 神奈川・東京・千葉・茨城・静岡の船宿（ships.jsonから自動読み込み）
**船宿自動発見**: discover_ships.py が月1回 fishing-v.jp をスクレイプして ships.json を更新
**対応エリア・港一覧**: ships.json が正（有効75件）

---

## マネタイズ方針（2026/04/04 確定）

- **無料 = 事実**: 今日どの魚が釣れたか、釣果一覧表示
- **有料 = 分析＋予測**: なぜ釣れたか（海況相関）、特定日の釣果予測
- **月額500円 / スポット100円**
- 予測の出力形式: 数要素　min匹～max匹、ave匹、型要素（cm kgはデータ次第）min cm～max cm、ave cm、minkg～maxkg、avekg、
- 現状MAPE 27〜55%（CVが低い船宿）→ MAPEを改善する方法を船宿ｘ魚種単位、エリア船宿ｘ魚種単位で検討していく
- 決済連携・UI設計は未決定

---

## 実装済み機能

### 釣果収集・表示（Layer A/B/E）
1. ✅ 釣果自動収集（釣りビジョンHTMLパース・毎日更新）
2. ✅ 魚種カードをタップでランキング表示（船宿別TOP10・バーグラフ）
3. ✅ 今週末の狙い目セクション（★評価＋理由タグ＋100パターンコメント）
4. ✅ 魚種別ページ（fish/*.html・SEOタイトル・metadescription）
5. ✅ エリア別ページ・釣りものカレンダーページ
6. ✅ discover_ships.py による船宿SID自動収集（89船宿）

### データ収集・分析（Layer A/C）
7. ✅ 気象・海況データ（weather_cache.sqlite・153座標×145万行）
8. ✅ 台風トラックデータ（typhoon.sqlite・70台風・2,475ポイント）
9. ✅ 月齢・潮汐データ（tide_moon.sqlite・1,190日分）
10. ✅ 釣果×気象相関分析（combo_deep_dive.py・51魚種）
11. ✅ 欠航閾値計算（cancel_thresholds・cancel_thresholds_seasonal）
12. ✅ 匹数・サイズの予測精度バックテスト（H=0,1,3,7,14,21,28）

---

## 未実装・ブロック中

- [ ] 予測モデル実装（D層・設計済み・PIPELINE.md参照）
- [ ] parse_deepdive.py → deepdive_params.json（C完了後に実行）
- [ ] 決済連携（Stripe等）
- [ ] AdSense審査結果待ち（2026/03/21申請済み）
- [ ] X自動投稿（アカウントロック解除待ち）
- [ ] crawl.yml Node.js 20→24 upgrade

---

## 開発環境

| ツール | バージョン |
|--------|----------|
| OS | Windows 11 |
| Git | 2.53.0 |
| Python | 3.14.3 |
| Node.js | 25.8.1 |

### ローカル確認手順
```bash
python crawler.py          # データ取得・HTML生成
python -m http.server 8000 # ローカルサーバー起動
# → http://localhost:8000 で確認
```

---

## 注意事項・開発ルール

- crawler.py は**標準ライブラリのみ**（外部依存なし）
- 釣りビジョンへのリクエストは0.8秒待機（サーバー負荷対策）
- GitHub ActionsのタイムゾーンはUTC（16:30 JSTは07:30 UTC）
- fish/*.htmlのファイル名は日本語（URLエンコードされる）
- **weather_cache.sqlite は .gitignore 対象**（約400MB・ローカルのみ）
- **変更前に PIPELINE.md の変更インパクトマトリクスを確認すること**

### ルール
- 推測で join しない
- 過去の会話内容を仕様として扱わない
- 不明点は不明点として列挙する
- 実装前に、今回の変更対象・目的・影響範囲を要約する
- 仕様にない補完はしない
- 粒度の違うデータを混ぜない
- 勝手に実装しない
- **JSONのキー取得はエージェント要約を信頼せず必ずBashで直接確認する**
- **ループ実行前に `print(f'対象: {len(list)}件 先頭3: {list[:3]}')` で件数・内容を目視確認してから実行する**

---

@.claude/memory/project_status.md
@.claude/memory/feedback_crawler_editing.md

@PIPELINE.md
