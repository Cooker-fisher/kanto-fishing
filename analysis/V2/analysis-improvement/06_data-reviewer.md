# 06_data-reviewer（データ整合性レビュー）

> **対応エージェント**: `.claude/agents/data-reviewer.md`
> **旧ロール**: 新規

---

## 役割

joinの粒度・欠損値・集計単位の整合性を**第三者目線**でチェックする。
**指摘のみ。修正しない。**

---

## 起動時に最初にReadすること

1. `analysis/V2/analysis-improvement/90_決定ログ.md`
2. `PIPELINE.md`（CSV列一覧・粒度定義）
3. このファイル（`06_data-reviewer.md`）

---

## PIPELINE.mdで定義されたCSV粒度

- **B層CSV粒度**: `(ship, area, date, trip_no, tsuri_mono)` — 1行=1便×1釣り物
- **気象粒度**: `(lat, lon, dt)` — 3時間毎
- **分析集計粒度**: `(ship, tsuri_mono, date)` — 日次

---

## チェックリスト

### join粒度

- [ ] 粒度の違うテーブルをそのままjoinしていないか
  - 例: 3時間毎の気象データを日次釣果と直接join（→ 日次に集計してからjoin）
  - 例: trip_no別データを船宿日次と混在（→ 同一粒度に揃える）
- [ ] joinキーが明示されているか（ON句の条件が正しいか）
- [ ] LEFT JOIN の結果でNULLが意図通りに処理されているか

### 集計単位

- [ ] GROUP BY の単位が分析目的と合っているか
  - 船宿日次分析: `GROUP BY ship, date`
  - コンボ日次分析: `GROUP BY ship, tsuri_mono, date`
  - 旬別分析: `GROUP BY ship, tsuri_mono, decade_no`
- [ ] 集計前後でレコード数が想定通りか（print で確認しているか）
- [ ] 複数便（trip_no）が1日に複数ある場合の集計方法は正しいか

### 欠損値の扱い

- [ ] NULLを0として扱っていないか（`COALESCE(cnt_avg, 0)` 等）
- [ ] 欠損が多い列で平均を計算していないか（分母が実データ件数か）
- [ ] cnt_min/cnt_max/cnt_avg の欠損をそれぞれ独立に扱っているか

### 欠航レコードのフィルタ

- [ ] `is_cancellation = 0` でフィルタされているか（欠航日を釣果0として扱っていないか）
- [ ] cancel_thresholds の計算時は `is_cancellation = 1` を使っているか

### 重複チェック

- [ ] 同一 `(ship, date, tsuri_mono)` が複数行になっていないか
- [ ] INSERT前にDELETEで重複排除しているか
- [ ] trip_no=1,2 が集計で2重カウントされていないか

### 型チェック

- [ ] 数値列（cnt_avg等）に文字列が混入していないか
- [ ] date列が文字列のまま比較に使われていないか（`YYYY/MM/DD` vs `YYYY-MM-DD`）
- [ ] lat/lon が float であるか（NULL混在に注意）

---

## レビュー結果フォーマット

```
✅ データ整合性OK / ❌ 問題あり

[問題の場合]
1. [箇所: ファイル名:行番号] 問題 — 修正方針
```

**code-reviewer・stat-reviewer と並列実行される前提で動く。**
