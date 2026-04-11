現行バージョン: crawler.py v5.24（回遊魚★チャンス評価表示追加）
最終更新: 2026/04/11
最新コミット: 18d62dc（_pred_build_html: 回遊魚★チャンス評価表示）

## ★ 次チャットでやること（優先度順）

### 1. シイラ×庄治郎丸 combo_meta 欠損問題
- predict_combo が None を返すのは combo_meta にエントリがないため
- save_insights.py を実行するか、combo_meta なしでも 回遊魚★が動く経路を確認
- （低優先: 今は表示があるコンボのみ機能する状態で問題なし）

### 2. crawler.py を実行して forecast HTML を実際に確認
- `python crawler.py` を実行して forecast/index.html を再生成
- ブラウザで回遊魚セクションの表示を確認

### 3. git push（本番反映）
- ローカルコミット4件まとめて push

---

## ✅ 今セッション完了（2026/04/11）

### 回遊魚★チャンス評価システム（全実装完了）
- **combo_deep_dive.py**: `KAIYU_FISH` 定数追加、`_star_by_key` 蓄積、`combo_star_backtest` テーブル新設
  - 定量ベースの★割当（P20/P40/P60/P80）
  - 良日ライン = P75（median=1問題を回避）
  - good_line ≤ 3 ガード（実質釣れないコンボは ★表示しない）
  - H=7 を本番ホライズンとして採用
  - 全55魚種実行完了: combo_star_backtest に91行（13コンボ×7H）
- **predict_count.py**: `calc_stars_kaiyu()` 追加、`kaiyu_stars` フィールドを返す
- **crawler.py**: `_pred_build_html` 改修
  - 回遊魚 → 「チャンス★ / 良日目安 / ★5的中率」表示
  - 根魚・底もの → 従来の匹数レンジ表示
  - 2セクション構成

### 評価軸確定（2026/04/11）
- promise_break_rate = PRIMARY KPI（期待させて釣れなかった率）
- combo_range_backtest: promise_break_rate, over_expect_rate, coverage, bowzu_rate, winkler保存
- 全55魚種でのbacktest完了

### 前セッション完了（2026/04/11 前半）
- wave_clamp per-combo HPO: 採用（アジ -14.5pt改善）
- use_fallback: 4コンボ追加（計10コンボ）
- 相関閾値/FAST_MAX_H per-combo HPO: 変化なし → 不採用・固定継続
- 全55魚種再実行: H=0 42.8%, BL2勝率83%

---

## 確定した設計方針（変更不可）

### 回遊魚★評価設計（2026/04/11確定）
- KAIYU_FISH: {"シイラ", "カツオ", "キハダマグロ", "ブリ", "ワラサ", "イナダ", "サワラ", "カンパチ"}
- ★割当: 各コンボ予測値分布のP20/P40/P60/P80で分位
- 良日ライン: actual P75（good_line ≤ 3 のコンボは kaiyu=None）
- H=7 を本番ホライズンとして採用

### 評価指標設計（2026/04/11確定）
- pred_hi = cnt_maxモデル出力 → actual_maxと比較
- pred_lo = cnt_minモデル出力 → actual_minと比較
- actual_avgは評価に使わない
- 失敗優先順位: Max過大予測 > ボウズ見逃し > Max保守すぎ > Min保守すぎ

### FISH_MAP → 廃止決定（2026/04/09確定）
- **不要**: `tsuri_mono + main_sub` で同等のフィルタが可能
- 分析クエリは `tsuri_mono = "アジ" AND main_sub = "メイン"` で行う

### ships.json フィールド（2026/04/03更新）
- `exclude: true` → 利一丸・岩崎レンタルボート・海上つり堀まるや（3件）
- `boat_only: true` → 青木丸（1件）
- 有効船宿: 75件＋静岡エリア多数

### データ収集状況（2026/04/03時点）
- catches_raw.json: **84,757件**（欠航893件含む）
- data/YYYY-MM.csv: **82,481行**
- 期間: 2023/01/01〜2026/04/03

### ポイント解決（3段階フォールバック・完全実装済み）
```
① point_place1 → point_coords.json（306ポイント）→ 座標
② 空/航程系 → ship_fish_point.json（73船宿）→ ポイント名 → 座標
③ ② も未登録 → area_coords.json（58エリア）→ 直接 lat/lon
```
- 解決率: **94.9%**（除外船宿を除く）

### 価格・マネタイズ
- **月額500円 / スポット100円**
- 無料=事実、有料=分析+予測

---

## 後回し・未実装
- [ ] 決済連携（Stripe等）
- [ ] AdSense審査結果待ち（2026/03/21申請済み）
- [ ] X自動投稿（アカウントロック解除待ち）
- [ ] crawl.ymlのNode.js 20→24アップグレード
