# プロジェクト現在地

**最終更新: 2026/07/27**（このファイルは「現在地」のみ。履歴は書かない）

> 履歴・意思決定の経緯 → `design/V2/90_決定ログ.md`（SoT）
> 2026/07/27 以前の旧 project_status 全文 → `.claude/memory/archive/project_status_full_2026-07-27.md`

---

## 稼働中

| 系統 | 状態 |
|---|---|
| crawl.yml（毎日16:30 JST） | ✅ 稼働。実行 1h20m〜2h45m。直近8回で fail 1（7/25・修正済 7f98d032e） |
| C層分析 | combo_deep_dive.py / Phase C composite_hit_rate / ALL_FISH 59種 |
| D層予測 | forecast ページは **検証済みモデル**（前日CI の forecast_daily.json × open_tier tier A）を配信中 |
| 釣果価値チェッカー | ✅ リリース済（月報 wholesale.yml 月次 + 日報 fish-value-daily.yml 週次） |
| x_post 日次まとめ | ✅ 数値根拠のみの本文（insights.py / narrative.py） |

## 正直なKPI（BL-1リーク解消後・T45 で確定した値）

- cnt_avg wMAPE P50 = **47.1%**（公表していた 38.1% の約9pt はリークだった）
- **公表KPIは cnt_bz（ボウズ込み）が正**: レンジ的中率 P50 = **90.0%**
- open_tier **tier A = 109コンボ / 23魚種 / 62船宿**（pb≤10% & n≥50 & fallback除外）
- H=28 で model 47.6% vs BL2 51.0%・ペア勝率 69.1% ＝ 主戦場（1〜4週先）の優位は本物

## 出荷済み（詳細は決定ログの各日付）

T44/T44b（因子供給率 33.6→79.6%）/ T45（リーク解消・正直化）/ T47a・T47b（選別公開・
ペイウォール完全撤去）/ Tier2 fish_area 編集部ノート パイロット5 / x_post 本文刷新 /
釣果価値チェッカー / 不変条件 #53〜#56

---

## 次の候補（未着手・優先度順）

1. **Tier2 拡大** — パイロット5 の GSC 反応を見て、残り約29ページへ同方式を展開
2. **fish_area 薄ページの物理削除/統合の検討** — 現在 noindex 止まり（676本）。
   noindex は巡回される。母集団を変えるなら削除が要る。※AdSense 判定は外から検証不可＝仮説
3. **T46** — Hurdle + log1p + recency加重（アブレーション → 全再実行1回に同梱）
4. **T48** — プール学習PoC（⚠ C層への外部ライブラリ解禁の可否＝**要ユーザー判断**）

## ブロック中 / 未着手

- AdSense 4連敗（「有用性の低いコンテンツ」）
- 決済（Stripe等）未着手 — マネタイズ方針は「予測は当面無料・月間数千〜1万UU後に再検討」
- crawl.yml Node.js 20→24

## 未マージブランチ

- `claude/unregistered-status-issue-149a5d`（3 commits・7/18）— GSC 診断ドキュメント中心。
  コード差分は fish_area noindex 閾値 80→50 の段階開放。**取り込むか破棄か判断が要る**
- 3月〜5月の残骸5本（confident-bose / sleepy-goldstine / pr-38 / pr-39 / redesign-update）は掃除対象

---

## 恒久ルール（破ると事故る）

- ローカル `crawler.py` フル実行の前に **必ず `git pull`**（未実施だと HERO 日付が巻き戻る）
  → PreToolUse フックで強制済み
- `crawl/validate_output.py` errors=0 を通してから push。**閾値を緩めて黙らせるのは禁止**
- 全再実行後は `build_predict_params.py` と `build_open_tier.py` の**両方**をローカル実行してコミット
- 分析実行はメイン repo（worktree 不可）
