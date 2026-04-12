---
name: プロジェクト現状
description: funatsuri-yoso.com の実装状況と次のアクション
type: project
---

現行バージョン: crawler.py v5.17（V2リデザイン計画中）
最終更新: 2026/04/12

---

## ★ 次チャットでやること（優先度順）

### 1. V2 無料ページ実装（最優先）

Design V2 × Analysis V2 合同検討で方針確定。以下の順で実装する。

#### フェーズ2: 共通ファイル新設（V2出発点）
- [ ] `build_style_css()` 関数を crawler.py に追加（style.css 生成）
- [ ] `build_main_js()` 関数を crawler.py に追加（main.js 生成）
- [ ] `_page_head()` / `_page_nav()` / `_page_foot()` 共通関数を crawler.py に新設
- 参照: design/V2/20_デザイン具体案.md セクション8（CSS構造）・セクション3（ナビ）

#### フェーズ3: index.html V2 構築
- [ ] HERO ゾーン（今日の件数・更新時刻）
- [ ] ZONE B 魚種カード（匹数レンジXX〜XX匹・前年比%・船宿数・代表エリア・シーズンバー）
- [ ] ZONE B 釣果テーブル（日付・船宿・エリア・魚種・匹数レンジ・前年比）
- [ ] ZONE C 海況予報（波高・風速・出船リスク）
- [ ] ZONE A 有料チラ見せ（1件無料+4件ブラー）
- [ ] ZONE B' テンプレート枠（`<!-- D層実装後に有効化 -->`）
- [ ] ZONE D 有料集約 CTAバナー
- 参照: design/V2/20_デザイン具体案.md セクション4（レイアウト）

#### フェーズ4: URL リファクタリング
- [ ] `fish_area/` → `fish-area/` ハイフン化
- [ ] ローマ字変換テーブル `ROMAJI_TABLE` 実装（58魚種+58エリア）
- [ ] sitemap.xml 更新

#### フェーズ5: 法定ページ＋SEO
- [ ] pages/privacy.html / terms.html / about.html 新設
- [ ] robots.txt 新設
- [ ] meta description 動的生成
- [ ] JSON-LD BreadcrumbList 実装

### 2. 分析フォルダ分離（analysis/V2 整理）

現状: `methods/` に純粋分析スクリプトと実稼働スクリプトが混在。

推奨移行先:
- `analysis/V2/research/` ← 手動実行（combo_deep_dive.py, backtest.py 等）
- `analysis/V2/production/` ← crawl.yml が毎日呼ぶ（predict_count.py, risk_predict.py, weekly_analysis.py, prediction_log.py）
- `analysis/V2/results/analysis.sqlite` ← 移動なし（crawler.py がここを直接読む）

### 3. 決済連携（後回しでOK）
- Stripe Payment Links か codoc を使う方向

---

## V2 確定設計方針（2026/04/12 合同検討で確定）

### 無料/有料 境界（最終確定）

| 情報 | 無料/有料 | 備考 |
|------|---------|------|
| 釣果件数レンジ（XX〜XX匹） | **無料** | ユーザー確定 2026/04/12 |
| 前年比（%） | **無料** | ユーザー確定 2026/04/12（旧 04/11 決定を上書き） |
| サイズ（cm） | **有料** | ユーザー確定 2026/04/12 |
| 重量（kg） | **有料** | ユーザー確定 2026/04/12 |
| 船宿別ランキング | **無料** | 事実の集計（04/11 確定を維持） |
| 今週の狙い目 ★評価 | **有料** | 分析コンテンツ |
| 理由タグ・期待度バー・コメント | **有料** | 分析コンテンツ |
| 海況予報（波高・風速・出船リスク） | **無料** | 集客優先（04/04 確定を維持） |
| 予測の答え合わせ（1件チラ見せ） | **無料一部** | ZONE B'（D層実装後に有効化） |
| 予測詳細（cm/kg レンジ） | **有料** | ZONE B' の有料部分 |

### データ供給ルール（Design×Analysis 合意）

| 用途 | データソース | フィールド |
|------|------------|----------|
| ZONE B 匹数レンジ | catches.json | count_range.min/max |
| ZONE B 前年比 | history.json | weekly[YYYY/WXX][魚種].avg 比較 |
| ZONE C 海況 | Open-Meteo API（load_weather_data()） | 波高・風速・天気コード |
| ZONE A/D チラ見せ | analysis.sqlite:combo_decadal | C層から直接 sqlite 参照 |
| ZONE B' 答え合わせ | analysis.sqlite:prediction_log | D層実装後に有効化 |

### 確定した配色・レイアウト（V2）
- テーマ: ライトテーマ（白背景＋濃紺ヘッダ＋オレンジCTA）
- 最大幅: 900px（`--mx: 900px`）
- ボトムナビ: 5アイコン（釣果/魚種/エリア/カレンダー/有料）
- フォント: system-ui
- V1 は参照禁止。V2成果物のみを仕様とする

### URL設計（確定）
```
/fish/aji.html           ← ヘボン式ローマ字・ハイフン区切り
/area/yokohama.html
/fish-area/aji-yokohama.html   ← アンダースコア廃止
/calendar/index.html
/pages/about.html 等
/premium/forecast/       ← 有料ゾーン
```

---

## 実装済み機能（v5.15〜v5.17）

### 有料予測ページ群（forecast/）※ V2では premium/forecast/ へ移行予定
- ✅ forecast/index.html: ハブページ（予測結果レポート＋チラ見せ＋料金）
- ✅ forecast/YYYY-MM-DD.html: 日次ページ×7
- ✅ forecast/YYYY-WXX.html: 週次ページ×3
- ✅ forecast/area/エリア名.html: エリア別ページ×8
- ✅ 価格表示: 月額500円/スポット100円

### データ取得・予測エンジン
- ✅ weather_code・surface_pressure を Open-Meteo Forecast API から取得
- ✅ 潮差・月齢は天文計算で算出
- ✅ predict_catches: 偏差ベース×6要素
- ✅ 確信度A/B/C/D
- ✅ SST傾向軸（v5.17）

### 変更不可の設計方針
- 価格: **月額500円 / スポット100円**
- 2〜5件目: HTMLソースにコンボ名を書き出さない（blur解除対策）
- 分析テキスト: 閾値・係数は非公開、定性表現のみ
- LLMによるテキスト生成は採用しない

---

## 後回し・未実装
- [ ] エリアごとの海況閾値最適化
- [ ] 決済連携（Stripe等）
- [ ] サーバーサイド認証
- [ ] prediction_history.json
- [ ] AdSense審査結果待ち（2026/03/21申請済み）
- [ ] X自動投稿（アカウントロック解除待ち）
- [ ] crawl.ymlのNode.js 20→24アップグレード

---

## ブランチ情報
- 作業ブランチ: `claude/plan-free-content-launch-An3cq`
- リポジトリ: cooker-fisher/kanto-fishing
