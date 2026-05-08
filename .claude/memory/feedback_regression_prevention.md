---
name: 破壊防止規約 (gatekeeper 11 不変条件)
description: HTML/CSV 生成変更時は必ず crawl/validate_output.py を通してから commit。閾値を緩めて gatekeeper を黙らせるのは禁止。
type: feedback
---

## ⚠️ HTML/CSV 生成系を触る前に必読

過去にデータ消失・レイアウト破壊の regression が複数回発生し、3層 gatekeeper を導入。

**SoT（詳細）:**
1. `design/V2/REGRESSION_PREVENTION.md` — クイックリファレンス + 11 不変条件 + 設計契約
2. `design/V2/90_決定ログ.md`「2026-05-01 データ消失 regression 防止策」

## ローカル検証（必須）

```bash
python crawl/validate_output.py    # 11 不変条件全 PASS（errors=0）
```

エラーが出たらコードを直す。**閾値を緩めて gatekeeper を黙らせる修正は禁止。**

## 新規 regression 発見時

1. コード修正
2. `crawl/validate_output.py` に新規不変条件追加
3. `design/V2/90_決定ログ.md` に追記
4. `design/V2/REGRESSION_PREVENTION.md` のテーブル更新
5. ローカル検証 → commit
