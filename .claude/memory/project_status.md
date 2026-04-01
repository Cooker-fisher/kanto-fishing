---
name: プロジェクト現状
description: funatsuri-yoso.com の実装状況と次のアクション
type: project
---

現行バージョン: crawler.py v5.17
最終更新: 2026/04/01

---

## ★ 次チャットでやること（優先度順）

### 1. 有料予測ページの動作確認・改善
有料ページ機能はv5.15〜v5.17で実装済み。ただし実際のHTMLを目視確認できていない。
`python3 crawler.py` で生成してブラウザ確認が必要。

確認ポイント:
- forecast/index.html: 予測結果レポート（1件完全＋4件ぼかし）＋日付ナビ＋エリアリンク
- forecast/2026-04-01.html（等）: 6指標海況ダッシュボード＋TODAY'S PICK＋予測一覧テーブル＋詳細カード
- forecast/2026-W15.html（等）: 週次潮汐スケジュール＋予測テーブル
- forecast/area/東京湾奥.html（等）: 7日間サマリー＋エリア別予測
- 確信度C/Dのカードに「予測のブレ要因」が出ていること
- 詳細カードのSST傾向ファクター（🌡️水温推移 → 上昇/低下）が出ていること

### 2. 分析テキスト（テンプレート軸）の充実
現状の`_build_analysis_text`は5軸程度。以下の追加軸が議論済みで未実装:

| 軸 | 実装方法 | データ |
|----|---------|--------|
| シーズンスコア定性表現 | season_score→「旬」「端境期」等 | SEASON_DATA |
| 前週比 (WoW) | history.jsonの直前週と比較 | history.json |
| 風向き影響 | 魚種×エリアで有利/不利の風向をマップ | 固定マップ |
| サイズ傾向 | 直近catches vs history.size_avg | history.json |
| 来月展望 | SEASON_DATAで来月スコアと比較 | SEASON_DATA |
| 船数トレンド | history.shipsの増減 | history.json |

### 3. 決済連携（後回しでOK）
- Stripe Payment Links か codoc を使う方向
- サーバーサイド認証なし（GitHub Pages静的）
- DevToolsで突破可能だが500円なので許容範囲と判断済み

---

## 実装済み機能（v5.15〜v5.17）

### 有料予測ページ群（forecast/）
- ✅ forecast/index.html: ハブページ（予測結果レポート＋チラ見せ＋料金）
- ✅ forecast/YYYY-MM-DD.html: 日次ページ×7（海況ダッシュボード6指標＋TODAY'S PICK＋予測一覧＋詳細カード）
- ✅ forecast/YYYY-WXX.html: 週次ページ×3（2〜4週後、潮汐スケジュール＋予測テーブル）
- ✅ forecast/area/エリア名.html: エリア別ページ×8（7日間サマリー＋詳細カード）
- ✅ 無料/有料境界: 1件目完全表示、2〜5件目はコンボ名blur（HTMLソースにコンボ名なし）
- ✅ 価格表示: 月額500円/スポット100円

### データ取得・予測エンジン
- ✅ weather_code（天気）・surface_pressure（気圧）をOpen-Meteo Forecast APIから取得
- ✅ 潮差・月齢は天文計算で算出（Conway法、sine近似）→ 無限先の日付に対応
- ✅ predict_catches: 偏差ベース×6要素（波高・風速・SST・波周期・潮差・月齢）
- ✅ _enrich_forecast_combos: サイズ範囲・船宿TOP3をcatches.jsonから付与
- ✅ 確信度A/B/C/D: samples×adjustment×season_scoreで算出
- ✅ 詳細カード: A/B=通常、C/D=「予測のブレ要因」テキスト追加
- ✅ TODAY'S PICK選出: compositeスコア最高、前日同魚種なら2位採用
- ✅ SST傾向軸（v5.17）: 7日間予報の前半/後半比較→上昇/安定/低下を分析テキスト＋ファクター表示に反映

### 確定した設計方針（変更不可）
- 価格: **月額500円 / スポット100円**（380円ではない）
- 無料で見せるのは1件目のみ（魚種名・エリア名・匹数すべて表示）
- 2〜5件目: 匹数・型・確信度は見える、コンボ名（魚種×エリア）はblur
- HTMLソースにぼかし行のコンボ名は書き出さない（blur解除対策）
- 予想屋スタイル（◎○▲△✕・出馬表）は採用しない
- 分析テキスト: 閾値・係数は非公開、定性表現のみ（パクリ防止）
- LLMによるテキスト生成は採用しない（ハルシネーション防止）

---

## 実装済み機能（v5.11〜v5.14）
- ✅ staleデータフィルタ（v5.11）
- ✅ 魚種ページデザイン改善（v5.12）
- ✅ 爆釣アラート・旬の突入検出・週末予測確率（v5.13）
- ✅ 海況カード・GA4カスタムイベント（v5.14）
- ✅ 釣果予測エンジン初版（v5.14）

---

## 後回し・未実装
- [ ] エリアごとの海況閾値最適化（東京湾と外房で波の影響が違う）
- [ ] 決済連携（Stripe等）
- [ ] サーバーサイド認証
- [ ] prediction_history.json（予測精度の蓄積・表示）
- [ ] AdSense審査結果待ち（2026/03/21申請済み）
- [ ] X自動投稿（アカウントロック解除待ち）
- [ ] crawl.ymlのNode.js 20→24アップグレード

---

## ブランチ情報
- 作業ブランチ: `claude/review-fishing-forecast-UenjU`
- リポジトリ: cooker-fisher/kanto-fishing
