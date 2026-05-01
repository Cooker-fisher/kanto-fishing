---
name: 破壊防止規約 (gatekeeper 11 不変条件)
description: HTML/CSV 生成変更時は必ず crawl/validate_output.py を通してから commit。閾値を緩めて gatekeeper を黙らせるのは禁止。
type: feedback
---

## ⚠️ 重要: HTML/CSV 生成系を触る前に必読

過去にデータ消失・レイアウト破壊の regression が複数回発生し、3層 gatekeeper を導入した。
**新しい変更を加える前に以下を必ず読む:**

1. `design/V2/REGRESSION_PREVENTION.md` — クイックリファレンス
2. `design/V2/90_決定ログ.md` の「2026-05-01 データ消失 regression 防止策」セクション

## ローカル検証フロー（必須）

```bash
python crawl/validate_output.py    # 11 不変条件全 PASS であること（errors=0）
```

エラーが出たらコードを直す。**閾値を緩めて gatekeeper を黙らせる修正は禁止。**

## 11 不変条件の概要

| # | チェック対象 | 違反すると |
|---|---|---|
| 1〜4 | docs/{index,fish,area,calendar}.html の最低件数 | トップ・一覧ページが空 |
| 5 | 当月 CSV 鮮度 | 前日データ消失 |
| 6 | catches_raw.json 件数 | データ破損 |
| 7 | area 旬カレンダー塗り | 全セル白 |
| 8 | area fia-grid card 内容 | 件数·船宿のみで sparse |
| 9 | fish 7日チャート | 今日1本のみ |
| 10 | fish HERO 構造統一 | マダイとワラサで別レイアウト |
| 11 | ネストアンカー | `<a>` の中に `<a>` |

## 設計契約（守らないと regression）

- `data/V2/*.csv` は append-only。手動再生成は `FORCE_EXPORT=1` 必須
- `catches.json` の data は HTML 生成元として使うな（today-only sparse）
- `_load_recent_catches_for_index()` は dict (`count_range={min,max}`) で返す
- fish HERO は `<div class="fish-hero"><h2>...</h2><div class="fh-r">...</div><div class="fh-m">...</div></div>` の1種類のみ
- `<a>` 内に `<a>` をネストするな
- 当日 sparse (< 30件) → 7日窓フォールバック・ラベル「直近1週間」

## 新しい regression 発見時の手順

1. コード修正
2. `crawl/validate_output.py` に新規不変条件を追加
3. `design/V2/90_決定ログ.md` に追記
4. `design/V2/REGRESSION_PREVENTION.md` のテーブル更新
5. ローカル検証 → commit
