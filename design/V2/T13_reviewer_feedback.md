# T13: reviewer フィードバック（条件付き承認）

**作成日**: 2026/05/07
**作成者**: reviewer (Agent)
**対象ドキュメント**: `design/V2/T13_designer_proposal.md`
**判定**: 条件付き承認 — 修正4点 + 追加検討3点

---

## 読了確認

- T13_designer_proposal.md（266行）
- 90_決定ログ.md 2026/04/04・04/09・04/10・05/01 T10 該当セクション
- REGRESSION_PREVENTION.md（11不変条件 + 12不変条件）
- docs/forecast/2026-05-07.html / area/tokyo.html（既存ティザー実態）

---

## ✅ OK（妥当と判定）

### 観点1: mockup の踏襲度
mockup 構造を変更する提案なし。URL対応表確認のみで過剰仕様なし。

### 観点2: URL命名規則の準拠
決定ログ L238「ローマ字（ヘボン式）」「区切りハイフン」に準拠。`forecast/area/{area}.html` は決定ログ L279 と整合。

### 観点5: plan.html の配置判断（論拠）
3点の論拠（watermark不要・静的コピーで十分・`/premium/` は有料コンテンツ配信ゾーン）は決定ログ L253 と整合。

### 観点7: SEO・JSON-LD
Product + Offer 2種は妥当。canonical は `/premium/` 単一パスのみで重複なし。AdSense 審査への影響もなし。

### 観点9: 実装ブロッカー分類（大枠）
D層・認証・決済の3分類は妥当。`actual_*未完` を独立した4分類目として明示しているのは適切。

---

## ⚠ NEEDS REVISION（修正推奨・4点）

### 修正1: LP 的中率集計クエリの境界違反

**指摘**: 提案クエリが `actual_cnt_avg IS NOT NULL` で is_good_hit の分母を絞っている。`actual_cnt_avg` は決定ログ 2026/04/09 L186 で **有料境界**列。LP（無料側）の集計クエリで分母フィルタに使うのは無料/有料境界の越境にあたる。

**修正方針**: `actual_pct IS NOT NULL` に変更（L185 で `actual_pct` は無料境界）。
```diff
- AND actual_cnt_avg IS NOT NULL
+ AND actual_pct IS NOT NULL
```

**実害確認（PM追加）**: prediction_log 現状で actual_pct=266件 / actual_cnt_avg=276件 → 数値に大差なし。境界遵守の修正で実用的影響は無視可能。

### 修正2: サンプル TOP3 選択の単一コンボ連続表示問題

**指摘**: 「is_good_hit=1 かつ target_date が最も近い過去日付」だけだと、同一コンボが連続的中していた場合に同じ魚種・船宿が3件並ぶ。LP の訴求「複数魚種・複数エリアで的中」が単一コンボ反復になりUX悪化。

**修正方針**: サンプル選択条件に「異なる tsuri_mono から1件ずつ」制約を仕様として明記。programmer 実装時に DISTINCT または GROUP BY tsuri_mono を使う。

### 修正3: ティザー統一案C の実装認識ズレ

**指摘**: T13 は「`blur-text` クラス内に実データ存在」と記述しているが、実ファイル（docs/forecast/2026-05-07.html）を確認すると以下のとおり:

- `.blur-text {filter:blur(6px)}` は CSS定義のみで未使用（dead code）
- `.teaser-dummy {filter:blur(1.5px)}` も CSS定義のみで未使用
- 実装は **インライン `style="filter:blur(5px);user-select:none;pointer-events:none;opacity:0.75"` の `<div>` ラッパー** で `.detail-card` 全体（実データ込み）を包む方式

```html
<!-- 既存実装（L282 以降）-->
<div style="filter:blur(5px);user-select:none;pointer-events:none;opacity:0.75">
  <div class="detail-card high-conf">
    <div class="dc-header"><span class="dc-fish">アジ × 千葉・東京湾奥</span><span class="conf-badge conf-A">A</span></div>
    <div class="dc-range">予測 34〜225匹 / 15〜38cm　型狙い</div>
    <div class="dc-factors">...</div>
    <div class="dc-analysis">...（分析テキスト全文）...</div>
    <div class="dc-ships">📍 吉野屋 / 須原屋 / 林遊船</div>
  </div>
</div>
```

開発者ツールでこの `style` 属性を消せば全件閲覧可能 → 案Aの漏洩問題そのもの。

**修正方針**:
- T13 内の「`blur-text` クラス内に実データ存在」を「インライン `style="filter:blur(5px)"` div ラッパー内に `detail-card` 実データ存在」と訂正
- 改修対象を「`crawler.py` の forecast 出力ループにおいて、**2件目以降のレコード時に `detail-card` を実データではなくダミー文字列で生成する**」と明示
- ダミー化の具体: `dc-fish` を `??? × ???`、`dc-range` を `予測 ??〜??匹 / ??〜??cm`、`dc-analysis` をプレースホルダー文、`dc-ships` を「📍 ???」に置換

### 修正4: history.html「7日分は無料で実装可」の根拠不足

**指摘**: 「無料7日 + 有料30日」の根拠が「決定ログの『1件の答え合わせは無料』原則と整合」のみで、prediction_log の現行データ密度を未検証。

**実態確認（PM追加）**: 
```
prediction_log 直近7日（target_date 2026/04/30〜05/06）レコード数 = 0件
（target_date は予測対象「未来日」のため過去日付は皆無）

actual_pct 入りレコード総数 = 266件
is_good_hit=1 = 102件
```

→ history.html を「target_date が直近7日の予測×実績」で構築するなら、データ自体が存在しない。`prediction_log` の `pred_date` で絞るべきか、設計再検討必須。

**修正方針**:
- 「7日分は無料で実装可」断言を取り下げ、「**条件付き実装可（pred_date 基準でクエリ調整 + データ不足時のフォールバック表示が必要）**」に変更
- 設計時点で programmer 実装前に「直近7日に相当する pred_date 範囲のレコード数」「カバーコンボ数」を確認するステップを追加
- 不足時のフォールバック「直近の答え合わせ済み3件のみ表示」を明示

---

## 🚨 CRITICAL（差し戻し相当）

なし

---

## 📝 追加検討項目（3点・将来検討）

### 検討1: plan.html の canonical 移行コスト

`/pages/plan.html` 配置は妥当だが、将来 `/premium/plan.html` へ統合した時に canonical 変更 + 旧URL 301 リダイレクトが発生。設計時点で `/premium/plan.html` にして `/pages/` に置かない判断もあり得る。決定ログ追記時に「将来 `/premium/plan.html` への移行可能性」を注記しておくと運用が楽。

### 検討2: LP description の動的化

提案 `<meta name="description" content="...的中率72%。">` の「72%」が固定値。LP を `build_premium_index()` で毎日再生成するなら description も実集計値（`{hit_rate}%`）で動的生成すべき。検索結果の description として古い数値が半永久的に出るリスク。

### 検討3: forecast/ 改修後の不変条件#11 検査

案C では「1件目を実データで完全表示」のため `detail-card` 内 `<a>`（船宿リンク等）の構造が維持される。`paywall` 内の `<a>` との入れ子が発生しないか事前確認が必要。**改修後 `python crawl/validate_output.py` で 11不変条件 PASS を確認するステップを T13 実装フェーズに明記すべき**。

---

## 全体判断: **条件付き承認**

修正4点（特に修正1=境界違反 / 修正3=実装認識 / 修正4=データ密度確認）が反映されれば、本提案は決定ログに取り込んで良い。修正後の T13_designer_proposal.md を再読してから programmer 実装フェーズへ。

---

## 追記（2026/05/07・ユーザー指摘 + analyst 確認）

ユーザーから「自信予測的中率ってなに？ Min Maxの予測だろ？ /分析」と指摘を受け、analyst で分析チーム方針との整合を再確認した結果、本フィードバック修正1の **PM による反映方法に誤り** が判明した。

### PM の過剰一般化（訂正必要）

reviewer 修正1「`actual_cnt_avg` は有料境界（04/09 L186）」は **的中率ボックスの集計クエリ限定**で正しかった。しかし PM が T13_designer_proposal.md v1.1 に反映する際、

> 「LP の予測サンプルは pred_pct / actual_pct / is_good_hit / fcast_* のみ。pred_cnt_min/max は表示禁止」

と書いてしまった。これは **ZONE B' 答え合わせの境界を LP のチラ見せ表示まで誤適用** した過剰一般化。

### analyst による正しい解釈

| 場所 | 表示すべきもの | 根拠 |
|---|---|---|
| **ZONE B' 答え合わせ**（無料） | `pred_pct / actual_pct / is_good_hit` のみ | 04/04 「無料=前年比の予想vs実績」+ 04/09 L185 |
| **LP 予測サンプル**（チラ見せ） | `pred_cnt_min/max` 匹数レンジ + `pred_pct` + `actual_pct` + `is_good_hit` バッジ。**`actual_cnt_min/max` のみ非表示** | 04/04 ペイウォールUI 1件完全 + 04/07 匹数レンジ表示 |
| **forecast/{date}.html 1件目**（無料ティザー） | `pred_cnt_min/max` 匹数レンジ表示 OK | 同上（既存実装が正解） |
| **LP 的中率ボックス集計** | `actual_pct IS NOT NULL` でフィルタ | reviewer 修正1 通り（妥当） |

### analyst が新発見した重大問題（2件）

**A. `target_date` スラッシュ区切り問題（クエリバグ）**
- prediction_log の `target_date` は `2026/MM/DD` 形式で格納
- SQLite `date('now')` は `YYYY-MM-DD` 形式
- 文字列比較で `/`(ASCII 47) > `-`(ASCII 45) のため **全件が未来日判定**
- T13 内の全予測クエリで `REPLACE(target_date,'/','-')` 正規化必須
- 影響範囲: ZONE B' クエリ（決定ログ 04/09 L176）も同バグあり。programmer 実装時に要修正

**B. predict_count.py 停止疑い**
- prediction_log の最新 pred_date = `2026/04/27`（10日前）
- target_date max = `2026/05/04`
- 2026/05/07 時点で「明日以降の予測レコード」が **0件**
- LP の「明日の自信予測」訴求はデータ充足が前提のため不可能
- **対応**: LP 訴求を「過去の自信予測 的中 TOP3」に切替（actual_pct + is_good_hit が揃う過去レコード）。crawl.yml の predict_count.py 実行ステップ確認は別タスク起票

### v1.2 反映済み修正

T13_designer_proposal.md v1.2 で以下を反映:

1. Section 3.A 「予測サンプル」段落を全面書き直し（境界マトリクス + サンプル選択クエリ + 改訂経緯）
2. 末尾「実装フェーズ申し送り」に項目5（target_date 正規化）と項目6（predict_count.py 停止）を追加
3. 改訂履歴 v1.2 を追加

### mockup 修正済み

- `mockup-premium-v2.html`: 1件目アジ表示を `予測 22〜48匹 (平年比 +25%)` + `→ 実績 +28% ✓ 的中` に修正、h2/h3 ラベルを「過去の的中実績」訴求に変更、CSS `.pi-result` `.pi-hit` 追加
- `mockup-forecast-day-v2.html`: 1件目アジ×東京表示を `予測 41〜164匹 / 16〜33cm 型狙い` に戻す（既存 `docs/forecast/2026-05-07.html` と整合）

### 全体判断（最終）: **条件付き承認 → v1.2 で訂正反映済み**

PM が境界の理解を誤り、設計案を狭めすぎたが、ユーザー指摘 + analyst 確認で訂正完了。programmer 実装時は `target_date` 正規化と predict_count.py 状態確認を必須項目とする。
