# プロジェクト現在地

**最終更新: 2026/08/30**（このファイルは「現在地」のみ。履歴は書かない）

> 履歴・意思決定の経緯 → `design/V2/90_決定ログ.md`（SoT）
> 2026/07/27 以前の旧 project_status 全文 → `.claude/memory/archive/project_status_full_2026-07-27.md`

---

## 稼働中

| 系統 | 状態 |
|---|---|
| crawl.yml（毎日16:30 JST） | ✅ 稼働。8月は欠損なし |
| direct-crawl | ✅ chowari 日次 + gyo（一之瀬丸）。2026/08/02 復旧・不変条件 #63 で監視 |
| weather/*.csv | ✅ 日次追記。2026/08/01 復旧・不変条件 #60（鮮度7日）で監視 |
| C層分析 | combo_deep_dive.py / Phase C composite_hit_rate / ALL_FISH 59種 |
| D層予測 | forecast ページは検証済みモデル（前日CI の forecast_daily.json × open_tier tier A） |
| 釣果価値チェッカー | ✅ 月報 wholesale.yml 月次 + 日報 fish-value-daily.yml 週次 |
| x_post 日次まとめ | ✅ 数値根拠のみの本文。予想は出船24日/30以上に限定（不変条件 #64） |

## 正直なKPI（BL-1リーク解消後・T45 で確定）

- cnt_avg wMAPE P50 = **47.1%**（公表していた 38.1% の約9pt はリークだった）
- **公表KPIは cnt_bz（ボウズ込み）が正**: レンジ的中率 P50 = **90.0%**
- open_tier **tier A = 109コンボ / 23魚種 / 62船宿**（pb≤10% & n≥50 & fallback除外）
- H=28 で model 47.6% vs BL2 51.0%・ペア勝率 69.1% ＝ 主戦場（1〜4週先）の優位は本物

---

## SEO 現在地（2026-08 実測）

**GSC 月次**: 8月 120click / 6,263impr（7月 94 / 4,606）。
種別内訳は `python analytics/gsc/trend.py --monthly` で再計算できる。

| 種別 | 8月 impr | click | CTR |
|---|---:|---:|---:|
| area | 3,992 | 92 | 2.30% |
| fish | 941 | 13 | 1.38% |
| **ship** | 807 | **1** | **0.12%** |
| fish_area | 287 | 11 | 3.83% |

**インデックス（GSC 実測 2026-08-30）**: 登録済み **774** / 未登録 **992**
（2026-07-24 は 779 / 922）。**登録済みが微減・未登録が +70。手動投入（月20本前後）では
母数の増加に追いつかない規模**。手動投入の進捗と残リストは
`analytics/gsc/manual_index_requests.md`（SoT）。残 26本・次回は `fish/fugu.html` から。
枠は 1日 3〜11本と日によって大きくぶれる。

### 2026-08-29 に出荷した3本（効果判定は 9月中旬）

1. **#67 船宿ハブ `docs/ship/` 新設 + ship ページのナビ統一**
   `area/index` `fish/index` `x_post/index` はあるのに ship だけハブが無く、
   indexable 163本が内部リンクグラフから半ば孤立していた。ship ページのヘッダも
   別実装の旧5項目 gnav で双方向に孤立。→ ハブ生成・gnav に「船宿」追加・
   `_v2_header_nav('ship')` に統一・sitemap に `/ship/` 追加。
2. **#68 area の H1 に別称+県名**
   SERP 実査で **Google が title を捨てて H1 を SERP タイトルに使う**のを確認
   （title 維持 5.14% 対 H1 差し替え 1.51%・n=6 で例外なし）。差し替えが起きると
   #65（title に別称）の効果が丸ごと消える。→ H1 を
   `{エリア}（{別称全件}・{県名}）の船釣り釣果[【毎日更新】]`（30文字上限）に。
3. **`analytics/serp/` SERP 実査ログ**
   robots.txt が `/search?` の自動取得を禁止しているのでスクレイパは書かない。
   手動実査を構造化して蓄積する。`report.py` / `--suggest` / `--diff`。

**判定方法は `analytics/gsc/trend.py` の INTERVENTIONS に固定済み**:
- #67 … ship の imp 加重 pos が 10 を切るか（投入前は10週連続で 10.6〜17.8）
- #68 … `analytics/serp/report.py --diff` で title_source が h1→title に変わるか

⚠ **どちらも因果は未証明**。効かなければクロール頻度（SERP 表示日付の鮮度）側に戻る。

### 未計測の露出

Yahoo の AI回答で funatsuri-yoso.com が引用されている（「金谷漁港 釣り」で2回）。
**GSC の impression/click には一切出ない**。`analytics/serp/observations.json` に記録開始。
⚠ Yahoo の AI回答が Google AI Overview と同一かは未確認。

---

## E-E-A-T（AdSense 対応）

第三者 AdSense 診断で NG は C（E-E-A-T）の3項目のみ。A/B/D は全 OK。

| 項目 | 対応 |
|---|---|
| C4 コンテンツ品質 | ✅ 旬ピークの母数下限＋定義併記＋海況実勢（不変条件 #57） |
| C1 Experience | ✅ 運営者の一次体験 **19魚種・13,500字** + 共通FAQ 4問（不変条件 #58） |
| C2 Expertise | 一部。fish_area_notes はパイロット5本のまま |

- 一次体験は `normalize/field_reports.json`（書き方は `normalize/FIELD_REPORTS_GUIDE.md`）
- **「体感→サイトの実データで裏取り」の組み合わせが、自動収集にも体験ブログにも
  単独では書けない独自性**（該当10件）
- **残**: 港・船宿の体験（fish_area 近重複135本に最も効く・未着手）／C2 の
  fish_area_notes 拡大／魚種は19種で一旦終了（残りは未釣行）

---

## 次の候補（未着手・優先度順）

1. **ブランチ掃除** — ローカル **44本** / リモート **72本**（main 未マージ 28本）。
   `claude/unregistered-status-issue-149a5d` は **2026-08-30 に「取り込まない」と判断済み**
   （fish_area noindex 閾値 80→50 は、律速がクロールバジェットである以上、未登録の山を
   高くするだけ。決定ログ 2026-08-30 参照）。**削除は未実行＝要ユーザー判断**
2. **GSC 推奨事項の警告**: `area/iioka.html` のインプレッション **-58%**。
   8月 1,134impr で最大の流入源。#68 の効果判定と切り分けが要る（警告は改修前から出ている）
3. **Tier2 拡大** — パイロット5 の GSC 反応を見て残り約29ページへ展開
4. **fish_area 薄ページの物理削除/統合** — 現在 noindex 止まり（676本）。
   noindex は巡回される。母集団を変えるなら削除が要る。※AdSense 判定は外から検証不可＝仮説
5. **T46** — Hurdle + log1p + recency加重（アブレーション → 全再実行1回に同梱）
6. **T48** — プール学習PoC（⚠ C層への外部ライブラリ解禁の可否＝**要ユーザー判断**）

## ブロック中

- AdSense 4連敗（「有用性の低いコンテンツ」）
- 決済（Stripe等）未着手 — 「予測は当面無料・月間数千〜1万UU後に再検討」
- crawl.yml Node.js 20→24
- X自動投稿（アカウントロック解除待ち・全部手動投稿で運用中）

---

## 恒久ルール（破ると事故る）

- ローカル `crawler.py` フル実行の前に **必ず `git pull`**（未実施だと HERO 日付が巻き戻る）
  → PreToolUse フックで強制済み
- `crawl/validate_output.py` errors=0 を通してから push。**閾値を緩めて黙らせるのは禁止**
- **部分実行（`--ships-only` / `--area-only`）の出力を commit しない。**
  ship ページを `--ships-only` で再生成すると 163→155 船宿に減り、sitemap も 809→803 に
  変わる（2026-08-29 に再現）。ナビ等の一括変更はコミット済み HTML へのテキスト置換で行い、
  データ再生成は CI のフル実行に任せる
- 全再実行後は `build_predict_params.py` と `build_open_tier.py` の**両方**をローカル実行してコミット
- 分析実行はメイン repo（worktree 不可）
- **検索エンジンの SERP は自動取得しない**（robots.txt で `/search?` が Disallow）。
  実査は人がブラウザで開いて `analytics/serp/observations.json` に手で記録する
