現行バージョン: crawler.py v5.23（design_version 同期・pages/ 移行）
最終更新: 2026/04/11
最新コミット: eb904ba（pages/: 静的HTML移動・crawler.py リンク更新）

## ★ 次チャットでやること（優先度順）

### 1. combo_deep_dive.py に評価指標追加（実装未完）
以下を実装してから全55魚種再実行：

**評価軸の確定（2026/04/11）**
- 比較軸: `pred_hi vs actual_max`（cnt_max列）、`pred_lo vs actual_min`（cnt_min列）
- actual_avg は評価に使わない（ユーザーは見ない）
- KPI1: **Max過大予測率** = actual_max < pred_hi × 閾値 の割合（Primary・解約リスク）
- KPI2: **ボウズ見逃し率** = actual_min=0 なのに pred_lo > 0 だった割合（Secondary）
- KPI3: cnt_max wMAPE（既存・継続）

**失敗優先順位（重い順）**
1. pred_hi高い → actual_max低い（上級者が釣れると思って釣れなかった）
2. pred_lo>0 → actual_min=0（ボウズ、お金返せ案件）
3. pred_hi低すぎ → actual_max大（大当たりを外した、保守すぎ）
4. pred_lo低すぎ → actual_min高い（許せる、嬉しい誤算）

**実装内容**
- combo_range_backtest テーブル新設
- 比較: `pred_hi（cnt_maxモデル予測）vs actual_max（cnt_max列）`
- 比較: `pred_lo（cnt_minモデル予測）vs actual_min（cnt_min列）`
- Coverage/Winkler（非対称ペナルティ: 上振れ>下振れ）
- Max過大予測率・ボウズ見逃し率を保存

### 2. predict_count.py: 直接予測の動作確認（実装済み・未テスト完了）
- `_apply_wx_correction` に `metric` パラメータ追加済み（2026/04/11）
- cnt_lo = cnt_minモデルで直接予測、cnt_hi = cnt_maxモデルで直接予測
- ratio法は廃止（フォールバックとして残留）
- 軽い動作確認済み（アジ×光進丸: cnt_lo=15.2, cnt_hi=60.2）

### 3. 全55魚種再実行
- 上記実装完了後に実行

### 4. git commit（上記完了後）

---

## ✅ 今セッション完了（2026/04/11）

### predict_count.py: min/max直接予測実装
- `_apply_wx_correction(metric='cnt_avg'/'cnt_min'/'cnt_max')` 対応
- predict_combo: cnt_lo/cnt_hiをcnt_min/cnt_maxモデルで直接計算
- ratio法はuse_fallbackまたはモデルなし時のフォールバックとして残留

### 評価軸の設計確定（重要）
- **評価比較軸**: pred_hi vs actual_max、pred_lo vs actual_min（avgは不使用）
- **ビジネス価値**: 高いお金を払った釣行の「損」を最小化する意思決定支援
- **最重要KPI**: Max過大予測率（pred_hi高い→actual_max低い）= 解約リスク
- **改善の鍵**: 海況との組み合わせで「急に釣れなくなる転換点」を検出

### 前セッション完了（2026/04/11 前半）
- wave_clamp per-combo HPO: 採用（アジ -14.5pt改善）
- use_fallback: 4コンボ追加（計10コンボ）
- 相関閾値/FAST_MAX_H per-combo HPO: 変化なし → 不採用・固定継続
- 全55魚種再実行: H=0 42.8%, BL2勝率83%

---

## 確定した設計方針（変更不可）

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
