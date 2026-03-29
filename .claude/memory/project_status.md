<!-- 最終更新: 2026-03-27 -->
---
name: プロジェクト現状
description: funatsuri-yoso.com の実装状況と未実装タスク（2026/03/27時点）
type: project
---

現行バージョン: crawler.py v5.14

最終更新: 2026/03/29 (セッション2)

実装済み（主要なもの）:
- 釣果自動収集・魚種別/エリア別ページ・狙い目TOP5
- 昨年同週比較（history.json連携）
- HTTPS有効化済み
- AdSense審査送信済み（2026/03/21）
- 船宿数を26→89に拡大（discover_ships.py + ships.json自動読み込み）
- discover_ships.py: 釣りビジョンから神奈川・東京・千葉・茨城の船宿SIDを月1自動収集
- crawl.yml: 月1日に discover_ships.py を実行するcron追加
- エリアFrom探すドロップダウンを都道府県グループ別に整理
- 最新釣果のエリアフィルターボタンも都道府県グループ別に変更 + 港ページへリンク化
- 魚種ページ生成閾値を3件→1件に変更（メバル・カンパチも生成済み）
- .claude/launch.json 作成（Static File Server + Crawler build設定）
- 魚種クイック検索・釣果数順ソート・NEWバッジ追加
- 最新の釣果をdate desc順に修正（build_catch_table内でsorted適用）
- ✅ サイズカラムを「大きさ(cm)」「重量(kg)」に分割（2026/03/24）
- ✅ 不明・空欄行の薄表示（class="dim" opacity:0.45）（2026/03/24）
- ✅ 全ページに「データについて」折りたたみフッター追加（2026/03/24）
- ✅ SEO改善: fish・areaページのtitle/H1最適化（2026/03/25）
- ✅ SEO改善: canonical / OGP / BreadcrumbList schema 全ページ追加（2026/03/25）
- ✅ SEO改善: 内部リンク強化（2026/03/25）
- ✅ 推薦コメント整合性（2026/03/25）
  - build_reason_tagsに先週比タグ追加（📈先週比UP / 📉先週比DOWN）
  - _render_tagsでwow-upを正方向として扱う
  - build_commentでWoW矛盾注記: top/highでwow≦-30%→「直近は急減傾向・注意」
- ✅ 魚種×港ページ（fish_area/）新設（2026/03/25）
  - build_fish_area_pages(): ≥5件の(fish,area)組み合わせのみ生成
  - fish pageに「エリア別の釣果」セクション追加（fish_area/へのリンク）
  - main()に呼び出し追加
  - URL: fish_area/{fish}_{area}.html
  - 100〜200ページ増見込み
- ✅ sitemap.xml 自動生成（2026/03/27 ※v5.9で実装済みだった）
  - build_sitemap(): index/fish/area/fish_area 全URL列挙
- ✅ fish_area ページに昨年同週比較テーブル追加（2026/03/27 v5.10）
  - build_fish_area_pages に history 引数追加
  - yoy-table CSS追加
  - 出船数は「関東全体」として表示

## 次チャットでやること（優先順）

### ① 次の施策を検討・実装
- staleデータ（30日超）のトップ除外フィルタ
- X自動投稿（アカウントロック解除後）

## 未実装タスク（中長期）:
- AdSense審査結果待ち
- staleデータ（30日超）のトップ除外フィルタ未実装
- X自動投稿（アカウントロック解除待ち）
- じゃらんアフィリエイト
- history_crawl.pyで過去2年分一括取得
- crawl.ymlのNode.js 20→24アップグレード

- ✅ staleデータフィルタ（v5.11）: 30日超の魚種をTOP5除外・カード薄表示
- ✅ 魚種ページデザイン改善（v5.12）: サマリーカード・メダル絵文字・縞模様テーブル
- ✅ 毎日データ活用（v5.13）: 爆釣アラート・旬の突入検出・週末予測確率

- ✅ GA4カスタムイベント（v5.14）: 魚種カードクリック・狙い目クリック・エリアフィルター・魚種検索にgtag()イベント送信
- ✅ 釣果予測エンジン（v5.14）: 海況予報×過去2年31,752件の実績から釣果予測
  - Open-Meteo Marine/Forecast APIで7日先の海況予報取得
  - 偏差ベース予測: エリア×魚種の平常値を基準に予報海況の偏差で補正
  - join_catch_weather.pyの3段階ポイント解決（point_coords→ship_fish_point→area_weather_map）で98.8%マッチ
  - 全6要素偏差補正: 波高・風速・SST・波周期・潮差・月齢
  - 魚種別予測プロファイル（FISH_PREDICT_PROFILE）: 生態に基づく重み付け
    - 凪感応型（カサゴ・メバル）, SST感応型（カワハギ）, 潮感応型（タチウオ・フグ）
    - 月齢感応型（マルイカ）, 回遊型（ワラサ・サワラ）, 季節型（マダイ・ヒラメ）
  - 精度不足の11魚種は予測非表示（show=False）
  - 表示対象9魚種: アジ(11%)・イサキ(24%)・アマダイ(24%)・マルイカ(28%)・マダイ(30%)・シロギス(33%)・クロムツ(35%)・ヒラメ(41%)・カワハギ(43%)
  - forecast.json出力 + JS日付切替UI
- ✅ crawl.ymlにweather_fetch.py追加（毎日の海況予報更新）
- ✅ ship_fish_point.json 14船宿追加（81船宿カバー）
- ✅ point_normalize_map.json 68件修正（weatherポイント名に正規化）
- ✅ エリア別代表ポイント8エリア固有化（_GROUP_TO_WX_POINT）

## 次チャットでやること（優先順）

### ① 予測精度改善
- 非表示11魚種のうちデータ蓄積で改善見込みのある魚種を再評価
- バックテスト期間を3月以外にも拡大して汎化性を確認

### ② その他
- X自動投稿（アカウントロック解除後）
- AdSense審査結果確認

**Why:** history_crawl.py完了で過去2年分蓄積。毎日データを活かした独自機能を追加。
