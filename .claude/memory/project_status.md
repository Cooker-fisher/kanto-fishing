現行バージョン: combo_deep_dive.py（Phase C composite_hit_rate 採用確定 / ALL_FISH 59種）
最終更新: 2026/07/16
最新コミット: a2bfcdfe2（fish-value リリース 3コミット・push済み）

---

## 📋 次の主作業（2026/07/16 段取り完了・未着手）— 公開準備ロードマップ T44〜T48

**段取り書（自己完結・これだけで着手可能）**: `analysis/V2/analysis-improvement/plan_T44_T48_openready_2026-07-16.md`

背景の4大発見（Fable分析・コード/DB実確認済み）:
① **公表KPIが本番と違う経路を測っている**（バックテスト=ratio上書き / 本番 predict_count=直接モデル優先）
② バックテストは**ボウズ除外**（load_records で cnt_avg<=0 を落とす・ボウズ率P50=16.9%）で楽観的
③ 誤差はタイ五目(4コンボ・n加重wMAPE73%)と回遊魚に集中。cnt pb P50=6.4%は既に商品水準
④ 「pb≤10% & BL2勝ち & n≥50」で**180コンボ(42魚種74船宿)が pb P50=2.73%** → 選別すれば公開可能

- T44: 測り直し（経路統一+ボウズ込み評価）← 最初にやる・全判定の土台
- T45: 回収（ポイントモデルkey不一致修正・BL-1リーク解消・fallback診断）
- T46: Hurdle+log1p+recency加重（フラグ化・全再実行1回に同梱）
- T47: 選別公開（open_tier.json 蒸留・KAIYU★一本化・タイ五目除外・E層配線+不変条件）
- T48: プール学習PoC（**要ユーザー判断**: C層外部ライブラリ解禁の可否）

⚠️ 分析実行は必ずメインrepo（worktree不可）。行番号アンカーは実装前に現物確認。

---

## ✅ 直近完了（2026/07/12・main agent）— CI 4日fail 復旧 + GSC起点SEO施策

1. **CI復旧（最重要）**: crawl.yml が 7/8〜11 の4日連続 fail・サイト7/7で凍結していた。
   根本原因 = 7/7 の #52 対応が docs/pages/ と design/V2/ にだけ適用され、**実際の同期元
   root `pages/` が未修正**（毎日 sync が古い版で上書き→#52 fail→push スキップ）。
   docs/pages の修正済み5ファイルを pages/ に書き戻して解消。静的ページの SoT は root pages/
   （CLAUDE.md の「design/Vn から同期」記述は実装と不一致・統合は別タスク chip 発行済み）
2. **GSC起点SEO**（ユーザー指定 ②③⑤⑥+x_post・④fish_content prose は不要と裁定）:
   - area/index/fish の title・description に更新日と最新日実釣果を動的注入（CTR 0% 対策）
   - ship 予約セクション→「予約・料金案内」拡張（料金額は出さない方針維持）+ 実績月 title に「直近」
   - fish_area: GSC表示実績 slug は hist 閾値未満でも index 維持（normalize/fa_gsc_proven_slugs.json
     13 slug・analytics/build_fa_gsc_slugs.py で月1再生成）
   - x_post: title/h1/description に当日の魚種・船宿名注入 + 過去68ページ backfill 済み
3. **残**: コラムテーマ GSC 逆引き（ハナダイ旬・大原シマアジシーズン等）は決定ログ (B)-5。
   GSC表示実績があるのにページ消失の fish_area 2件（onikasago-hiratsuka/magochi-kashima-port）要観察。
   詳細: 決定ログ「2026-07-12」

---

## ✅ 直近完了（2026/07/05・main agent）— 釣果価値チェッカー リリース

ユーザー確定方針: 既存サイト内の独立アプリとして公開（新サイト・アプリ化なし）／毎日クロールなし（月1マニフェスト追記で鮮度維持）。

1. **月報202605取込＋マスタ再生成**（aeb5ab3a9）: 6/21 の wholesale cron はマニフェスト未追記で
   空振りしていた→手動追記で解消。70pfid・override 3魚種（madai/shirogisu/mebaru）維持
2. **季節補正**（c1ebeb23e）: 蓄積17か月の月報から魚種別 暦月相場指数を算出しマスタ `seasonal`
   ブロックに埋込み。app.js が idx[利用月]/idx[データ月]（0.5〜2.0クランプ）で公開ラグ約1.5〜2か月分の
   季節ズレのみ補正（水準は最新月のまま）。60魚種=魚種別＋10魚種=カテゴリfallback。
   ドメイン照合済み（寒ブリ1月2.05/6月0.80・カツオ冬1.58・アジ平坦）。code-reviewer 検証済（CRITICAL/MAJOR 0）
3. **リリース**（a2bfcdfe2）: noindex解除・OGP・「算出方法」セクション／gnav「💰 釣果価値(NEW)」＋
   トップカード（crawler.py 恒久＋docs 遡及・T39パターン）／sitemap 収録／**不変条件 #51 追加**
   （リリース3点整合＋マスタ鮮度ラグ3か月超 warn=マニフェスト追記漏れ検知）。validate errors=0/warnings=0

**鮮度運用（月1・毎月20日頃）**: urls_manifest.json に新月報URL追記 → cron（毎月21日 wholesale.yml）が
crawl_wholesale.py → **generate_price_master.py まで自動実行しマスタもコミット**（2ab74e6ba で #2 修正済み）。
新データ無しの週は git diff --quiet で検知しスキップ（空コミット防止）。手動追記だけが残る人手作業。
**残（バックログ）**: urls_manifest 自動追記（Actionsで同意ページ回避が必要・難度中）／X 告知は運用側で実施

**卸値クロールは釣果と完全独立**: wholesale.yml（毎月21日）は crawl.yml（毎日16:30）と別ワークフロー・別ソース・
別出力（wholesale-prices.json/fish-price-master.json のみ触る）。相互に影響しない。

**日報ハイブリッド価格補正（2026/07/05・コミット 08301019c）**: 月報ベース＋豊洲**日報**（毎営業日）で
当月実勢を週次補正。`crawl_daily.py`（直近20営業日の中値median）→`daily-prices.json`→generate が
`daily_correction`（中値median/月報avg・clamp0.5-2.0・中値≥8観測の9魚種）→app.js `effectiveFactor` が
日報優先・無ければ季節fallback。`fish-value-daily.yml` 週次土曜で自動。日報は決定的URLで自動クロール可
＝手動manifest不要（月報側の手作業とは別）。品名マップの部分文字列誤爆（あまだい→madai）と冷凍混入
（きわだ（冷凍））を実データ監査で修正済。詳細: 決定ログ「2026-07-05」+ [[project-fish-value-status]]

---

## ✅ 直近完了（2026/07/03・main agent）— ②再分析反映 → ①chowari 修正（ユーザー指定順 2→1→3）

**② cmems/weather 更新 → C層フル再分析 → サイト反映（完了・push 済み b750cfe4a）**
- cmems 04-28→07-01（表層+深度・7/1 まで）/ weather_cache 〜07-01 全192座標完全
- 再分析 59/59 OK・39m37s。**headline 全回復**: wMAPE P50 **37.17**（T32 37.27 超え）/
  BL2 **96.3%** / OOS r **0.503** / combo 439 維持 → 6/23 の悪化は stale cmems 原因と実証
- **predict_params.sqlite（D層蒸留DB）初回コミット** → crawl.yml predict_daily が mode=available 化
- `rebuild_weather_cache.py` 恒久対策: **--update 増分モード**（通常運用はこれ・リクエスト1/100）+
  429 長バックオフ + 終端自動リペア統合。手動 _repair_marine 原則不要
- 6/23 監視項目「マダコ×秀漁丸」: 当該コンボは今回 backtest に不存在（船名要再確認・非ブロッキング）

**① chowari NULL 再正規化（完了・詳細は決定ログ 2026-07-03）**
- **重大 regression 発見・修正**: chowari 月次CSVが「直近7日窓」で日次破壊されていた
  （2026-06 が475行/6日分に縮小）。git 履歴から **+16,482行復元**・chowari_to_csv を
  dedup union 方式に修正・**不変条件 #49（窓化検知）追加**
- 7魚種昇格（サバ/イトヨリ/メジナ/ウマヅラハギ/ソイ/タカベ/ウメイロ・domainレビュー裁定）+
  変種6件。NULL/空 7,424→3,557（-3,867行）。NULL行のみインプレース再正規化
  （--export-csv 全再生成は fishing-v 履歴消失のため不採用）
- **残課題**: ⑴昇格7種の fish_content prose（Tier2 で・外部2ソース裏取り必須）⑵ALL_FISH への
  昇格種追加+C層フル再実行（+16k行復元の効果込み・出世魚統合の size promise_break 監視必須）
  ⑶ソウダ系・無印「ソーダ」据置

**次: ③ Tier2（fish_area/ship/forecast 本物化→index復帰）に着手**

---

## ⚠️ 直近作業（2026/06/21・branch claude/github-actions-ci-logs-dnavf5・未マージ）— CI fail 恒久対策（#45）

crawl.yml が validate_output #45 で fail（ホウボウ/メバル/ヒラマサ/カレイ 800字未満）。
**根本原因**: build_fish_pages のエリア解説固定文 lead が週次 chip 有無に依存して消えていた
（chip ゼロ週に 50-120字目減り）。固定文 full 800-820字台の42/63魚種が時限爆弾だった。
**修正**: ① crawler.py で `fc["areas"]` を chip から切り離し常時出力（恒久・本丸）。
② fish_content.json の薄い18魚種にプローズ追記し最小 full=816字。
詳細: 90_決定ログ「2026-06-21 CI fail 恒久対策」。残リスク=areas placeholder drop は月次チェックで #45 が捕捉。

---

## ⚠️ 直近作業（2026/06/16・branch claude/dameda-yda6k4・未マージ）— AdSense 再対策 Tier1

AdSense が再び「有用性の低いコンテンツ」で却下（再審査は **6/23 以降**・AdSense管理画面は本人のみ確認可）。
ユーザー方針=ハイブリッド（充実＋整理）。本セッションは **Tier1（整理＋品質）** を実装・検証済み。

- **広告ゲート**: noindex ページ（forecast 全件・空 ship・薄 fish_area）に広告コードを出さない（crawler.py + 遡及 sweep）。noindex 998 ページすべて広告ゼロ。
- **fish_area index 閾値 30→80**（`_FA_NOINDEX_HIST_THRESHOLD`）: index 維持 199 / noindex 676・sitemap fish_area 382→199。
- **自己矛盾の解消**: fish_area の hero/intro/title を今週→過去3年hist（FAQ と一致）に統一（`_fa_hist_stats` 新設）。
- **不変条件 #47 追加**（noindex に広告なし）。validate_output errors=0/warnings=0（49条件）。
- 詳細: `design/V2/90_決定ログ.md`「2026-06-16 AdSense…Tier1」。sweep は `dustbox/`。

**次（Tier2・要ユーザー判断）**: index 維持 fish_area/エリアの「予測・相関入り」本物化。
C層 analysis.sqlite はローカル限定（〜6/24不可）。fish_content 型 curated 蒸留で横展開。
**未マージ**: 本ブランチを main へ反映すると日次 regen で活性ページにも順次適用される。

---

## ⚠️ 現在の制約・環境（2026/06/10 確定・次セッション必読）

1. ~~**ローカルマシン使用不可（〜2026-06-24 頃まで約2週間）**~~ → **2026/06/23 解除済み**
   - weather_cache を 06-22 まで rebuild 済 + C層フル再分析 完了（下記「✅ 直近完了 2026/06/23」）
   - 未実施のローカル専用作業: koueimaru ③気象推定 / cmems 更新（04-28 で停止中・headline 改善余地）
2. **X は投稿可能になった**（アカウントロック解除済み）。ただし認知はまだ低い。
   x_post/ の日次生成物を実際に配信する運用が次の一手。
3. **マネタイズ戦略修正（ユーザー確定 2026/06/10）**: D層予測は有料ティザーではなく
   **当面無料公開**で集客に使う。的中実績が蓄積し月間数千〜1万UU 到達後に一部有料化を再検討。
   詳細: 90_決定ログ.md「2026-06-10 マネタイズ戦略の修正」

---

## ✅ 直近完了（2026/06/23・main agent）— ローカル復帰→C層フル再分析

ローカル使用不可（〜6/24）解除に伴い、止まっていたC層パイプラインを実行。釣果は自動クロールで
6/22まで最新（128,104件・CSV 129,162行）だが、分析は 5/22 の T32 状態で約1ヶ月停止していた。

**手順**: ① ローカル同期（リモートより **164コミット遅れ**→最新化）② weather_cache rebuild
（193座標・2023〜06-22）③ `run_full_deepdive --workers 6 --reset-best`（**59/59 OK・36分11秒**）

**⚠️ `rebuild_weather_cache.py` のバグ2件を発見・修正**（詳細: [[feedback_weather_rebuild_pitfalls]]）:
- `END_DATE=today` → Archive API 範囲外 **400**（archive は前日まで）→ `END_DATE=前日` に修正
- 片側フェッチ失敗時に `INSERT OR REPLACE` が反対側の列を **NULL破壊** → COALESCE保存型 upsert に修正
- marine API **429**（192座標連続で枯渇）で14座標 marine 欠落 → `ocean/_repair_marine.py` で全復旧

**結果（H=0, n>=30・T32比）**:

| 指標 | T32 | 再分析 | 差分 |
|---|---|---|---|
| combo_meta | 384 | **439** | **+55** ✅ |
| H=0 cnt_avg wMAPE P50 | 37.27% | 38.56% | +1.29pt ⚠️ |
| BL2 勝率 | 95.8% | 90.9% | -4.9pt ⚠️ |
| OOS r 平均 | 0.500 | 0.459 | -0.041 ⚠️ |
| promise_break cnt/size/kg/composite | 6/32/24/14% | 6/31/24/14% | ほぼ横ばい ✅ |

**判定: headline 悪化は構成効果（benign）・既存品質は維持**。apples-to-apples（共通358コンボ）では
wMAPE 37.27→37.92（**+0.65pt**）・BL2勝率 95.8→**95.5%**でほぼ不変・**324/358 安定**。全体悪化は
新規36コンボ（wMAPE P50=**47.85%**・n>=30 を新たに超えた marginal）が中央値と BL2 を引き下げたもので、
新規カバレッジであって既存劣化ではない。主要KPI(promise_break)は維持。共通コンボの +0.65pt 小幅劣化は
**stale cmems（04-28・recent 月の SLA/CHL 欠落）が一因の可能性**。

**成果物**: `analysis.sqlite`（439コンボ）/ バックアップ `analysis.sqlite.bak_pre_reanalysis_2026-06-23`（T32）/
`analysis/V2/analysis-improvement/_kpi_{baseline_T32,reanalysis_2026-06-23}.json`

**次（要ユーザー判断・サイト未反映で停止中）**:
1. **このままサイト反映**（crawler.py 再生成→validate_output→push）。カバレッジ+55 を本番化・AdSense Tier2 アンブロック
2. **cmems 更新**（build_cmems）→再分析で headline 回復を狙ってから反映
3. 保留
- 監視: マダコ×秀漁丸 wMAPE +23pt の個別劣化（要因未調査）

---

## ✅ 直近完了（2026/06/10・main agent）— PR#59 サイトバグ一斉修正

docs/ 全1,541ページの全数監査 → 修正 → 第三者レビュー2巡 → マージ済み。
- favicon 導入（既存画像流用: フグemoji=favicon.ico / アオリイカ水彩=apple-touch-icon）
- 魚種名「NULL」露出修正（CSV読込時 NULL→不明 正規化 + 表示系skip set 10箇所）
- 船宿slug衝突（弘漁丸→koryo-maru-hitachi）・tel連結（_first_phone_for_tel）
- デッドリンク 244ターゲット掃引 + `_sweep_dead_internal_links()` で毎回自己修復
- docs/404.html・不変条件 #40〜44 追加（validate_output.py 44条件 errors=0）
- 残課題: chowari CSV tsuri_mono="NULL" 4,054行の再正規化（tsuri_mono_map拡充・★★★）、
  画像アセット未作成 約24魚種（onerror非表示のため実害小）
- 要確認: 次回 Actions 実行（16:30 JST）後の validate_output 結果（新コード初回本番実行）

---

## ✅ 直近完了（2026/06/07・main agent）— T42 ユーザー再レビュー対応

PR#51/#52 マージ後のユーザー再確認に対応（branch `claude/fishing-forecast-quality-fixes-Wej3D`）。

### 調査結果（重要）
- **#1 / vs index.html・#2 更新遅延・マダイ5/23 はすべて main 上では解消済み**。
  main の全ページが 6/7 で整合（index 6/7 19:13、madai.html 今週64便、データもマダイ6/7あり、
  最新デプロイ 15cd8e7 success）。ユーザーが見た古い日付（トップ6/6・マダイ5/23）は
  **CDN/ブラウザキャッシュのページ種別ごと齟齬**（generation/deploy のバグではない）。

### 実装（CDN齟齬への根本的クライアント対策 + ゲート）
1. **全ページ鮮度バナー**: `_v2_header_nav` にビルド日付埋め込み + JS。CDN/ブラウザキャッシュで
   古い版を見ても、生成日 vs 当日を比較し2日以上古ければ「更新遅延」を全ページで自己申告。
   （index 限定だった hero_date ベースのバナーは撤去し、全ページ build-date ベースに統一）
2. **鮮度ゲート #39**: validate_output に追加。index「最終更新」が today-2 以内 + 全ページバナーの
   ビルド日付が today-2 以内（ページ種別の更新分裂を検知）。
3. **出船判定の見出し説明**: トップ「広域 出船リスク速報 ※最も荒れるエリア基準」、
   予報hub「出船判定は最も注意が必要なエリア基準」と明記（粒度の違いを可視化）。
4. **ヒラメ細部**: rod「底床感度」→「底取り感度重視」、line「リーダーPE1号」→「フロロ先糸」に修正
   （fish_tackle.json + docs/fish/hirame.html 遡及）。
5. **FAQ Q3 注記**: 「最高実績は…匹です」に「（個人釣果ベース・船全体の合計数は除く）」追記。

検証: validate_output.py errors=0（warning 1 = バナー未導入の現docs・次回再生成で解消）。

注: crawler.py 側の変更（バナー・出船見出し・FAQ注記・ヒラメ細部のソース）は次回 crawl 再生成で
全ページ反映。docs 遡及修正済みは hirame のみ。

---

## ✅ 直近完了（2026/06/07・main agent）— T41 集客前の信頼性品質修正

ユーザーレビュー「集客を強くかける前に止めるべき重大な不整合」への対応。
branch: `claude/fishing-forecast-quality-fixes-Wej3D`

### T41-1 魚種ガイド誤情報 + 異常釣果値（信頼性・最優先）
- **仕掛けテンプレ汚染**: `normalize/fish_tackle.json` の泳がせ系8魚種で「キハダマグロ針」が
  一律流用。特にヒラメは「ウレタン・キハダマグロ針・ウキ」というマグロ/カツオ仕掛けが混入。
  → ヒラメ=捨てオモリ式 親孫針、マゴチ/クロダイ/マハタ/ハタ/アラ/ブリ/ヒラマサ も target 別の正しい針へ修正。
- **西暦誤抽出**: `data/V2/chowari_2025-12.csv` の利喜丸ヒラメ「2025匹」（全データで唯一の年号異常）削除。
- **品質ゲート**: crawler.py に `_FISH_CNT_CAP`（魚種別現実的上限）+ `_is_plausible_cnt()` 追加。
  FAQ Q3 / fish_area Q2 の「最高実績」算出で非現実値を除外。ヒラメ等の低数量魚種は boat 誤集計も弾く。
- **デプロイ済み docs 遡及修正**: 汚染6件 + 異常値2件を文字列置換で live 即時是正。
- **validate_output #37**（ガイド他魚種道具混入検知）/ **#38**（最高N匹の西暦域/1500超検知）追加。

### T41-2 出船判定ロジック統一（#3 同一日・同一エリアで矛盾）
- 原因: 二重基準（`_risk_label`=海域別3段階 / `_fishing_ok_score`=海域非依存スコア）併存。
- 対策: `_sail_judge()`（海域別ベルトで severity 0-3 の単一ソース）新設し全判定を統一。
  `_risk_label` は薄ラッパ化、`_fishing_ok_score`/`_ok_label`/`_RISK_THR` 非推奨化。
  トップの内海/外海グリッドは「最も荒れるエリア基準」(MAX) と明記、日次も worst-case に統一。

### T41-3 データ鮮度バナー（#2）
- GitHub cron 遅延が常態（16:30 JST 予定が実際 09:30〜11:00 UTC = 数時間遅延）。
  index にクライアントサイド JS バナー追加: 最新データ日が2日以上古い時のみ遅延表示。

### #1 / と /index.html 不一致 → コード欠陥なしと判定
- docs/index.html は単一ファイル（GitHub Pages は / と /index.html に同一配信）。
- canonical=root・Service Worker 無し・index.html 内部リンク 0件（不変条件#34）・
  pages-build-deployment 全 success（6/7 10:38 UTC 含む）を確認。
- → 月単位で root のみ stale はこの構成では発生し得ず、**コード側の修正対象なし**。
  ブラウザ/DNS キャッシュ or Fastly エッジ一時事象の可能性大。
  推奨: incognito/ハードリロードで確認、再現するなら手動で Pages 再デプロイ（CDN purge）。

### 残（ユーザー優先度#5・機能追加のため後回し）
- 「今週末の結論」1カード追加 → 品質修正が live で検証できてから着手（ユーザー方針「今は機能追加を止める」）。

---

## ✅ 直近完了（2026/05/25・main agent）

### T39 fish_area noindex 拡大（AdSense 薄判定対策）

**動機**: AdSense 審査ステータス「要確認 / 有用性の低いコンテンツ」（2026/05/24 受信）。
ads.txt は承認済みだがコンテンツ判定で止まっている。666 本の fish_area ページのうち
hist_count（3年累計）が低いコンボは FAQ 固定文章も薄く、AdSense 薄判定の温床となるため
noindex で sitemap から除外する。

**threshold**: hist_count < 30
- 666 active ページ中 353 件（53%）が対象
- sitemap.xml: 1051 → 698 URL（353 件除外）

**実装内容:**
1. `crawler.py`:
   - `_FA_NOINDEX_SLUGS` モジュール変数 + `_FA_NOINDEX_HIST_THRESHOLD=30` 定数追加
   - `build_fish_area_pages()` 内で `fa_hist_count[(fish,area)]` を読み、閾値未満なら
     `fa_noindex_tag` を head に注入し slug を `_FA_NOINDEX_SLUGS` に蓄積
   - `build_sitemap()` で `_FA_NOINDEX_SLUGS` に含まれる fish_area URL を skip
2. `crawl/validate_output.py`:
   - 不変条件 #35 `validate_fish_area_noindex()` 追加（noindex 付与 10件以上 +
     sitemap 除外確認）
3. `design/V2/REGRESSION_PREVENTION.md`: 不変条件テーブルに #35 追加
4. 一回限りスクリプト `tmp_apply_fa_noindex.py` で既存 docs/ に遡及適用（dustbox 退避）

**検証**: `python crawl/validate_output.py` で errors=0 / warnings=0 全 PASS。
fish_area HTML 353 件に noindex meta タグ + sitemap.xml に 698 URL（除外 353 件）。

**未確認:**
- AdSense 再審査の結果（数日〜数週間後）
- 内部リンク経由でユーザー到達経路は維持（noindex は検索エンジンに対してのみ）
- 閾値 30 が適切か（再審査結果次第で 50 や 80 に上げる選択肢あり）

---

---

## ✅ 直近完了（2026/05/22・main agent）

### T33 DO魚種別+水色再predict+MIN_MONTHS=4 全コンボ再実行→撤回

**結論: 撤回（ユーザー判断「時間のわりに効果がほぼない」）**

**Plan v2-balanced 内容:**
- DO_FACTORS 独立カテゴリ化 + DO_EFFECTIVE_FISH 6魚種 / DO_INEFFECTIVE_FISH 6魚種の魚種別制御
- MAX_DO=1（多重共線性対策）
- MIN_MONTHS=4 緩和 + MIN_TRAIN_MONTHS_CMEMS=4 同期
- predict_count.py に DO=NULL フォールバック実装
- weather_cache rebuild + 水色再 predict 前処理

**Phase 6 全コンボ再実行結果 (T32 比):**

| 指標 | T32 | T33 | 撤回基準 | 判定 |
|---|---|---|---|---|
| H=0 cnt_avg wMAPE P50 | 37.27% | 37.71% | 38.0% | ⚠️ +0.44pt 微悪化 |
| BL-2 勝率 | 95.8% | 95.9% | 94.0% | ✅ 維持 |
| cnt promise_break P50 | 6.38% | 6.33% | 7.5% | ✅ -0.05pt |
| composite promise_break P50 | 13.93% | 13.80% | 15.0% | ✅ -0.13pt |
| size promise_break P50 | 31.58% | 31.25% | - | ✅ -0.33pt |
| **DO EFFECTIVE 採用** | 44 | 23 | ≥70 | ❌ **-21件 減少** |
| DO INEFFECTIVE 採用 | 99 | 2 | 0 | ⚠️ ほぼ達成 |

**撤回理由:**
1. promise_break 系の改善 (-0.05〜-0.33pt) は誤差範囲・wMAPE 微悪化を相殺できない
2. MAX_DO=1 制限で do_surface + do_bottom 両採用コンボが 1 因子に絞られ DO EFFECTIVE 採用 44→23 に減少（予期しない副作用）
3. 前処理 (weather rebuild + water_color predict) で 2 時間+ Phase 6 で 60-70 分 = **総計 3-4 時間** に対してリターン薄い
4. 質的改善（DO 過学習除去 99→2件・0-factor 31→26件）は KPI 化できず事業価値に直結しない

**撤回実施:**
- analysis.sqlite を bak_T33 から T32 状態に復元（wMAPE P50=37.29% で T32 一致）
- combo_deep_dive.py / predict_count.py を main HEAD 状態に戻し
- weather_cache.sqlite の更新 (2026-04-24→05-21) は valid なデータなので残す

**残す成果物（次回検討時の参考資料）:**
- diag_T33_2026-05-20.md / diag_T33_domain_2026-05-20.md
- plan_T33_2026-05-21_v2.md
- review_T33_{code,stat,data,domain}_2026-05-21.md
- ocean/weather_cache.sqlite（5/21 まで更新済み）

**T34 流用可能成果物の物理削除（2026-05-22）:**
- 補遺12 で「流用可能」と記述した tmp_3ships/ tmp_exp/ tmp_shotamaru/ tmp_survey/ tmp_hidemaru_rdf.xml を全削除（640MB 解放）
- 理由: T34 は「効果ゼロ」実証済みで再分析モチベーション低・SQLite/JSON は再生成可能
- 必要時は catches_raw.json (96,697件) + ships.json から再クロール可

**学んだこと（次回検討時必読）:**
1. **小幅な統計改善 (≤0.5pt) は事業価値に変換しにくい** → 次回は wMAPE/promise_break -2pt 以上が見込める改善のみ着手
2. **MAX_DO=1 制限の副作用を事前に試算すべき** → Plan 段階で「両採用→1採用への絞り込み」効果を計算していなかった
3. **前処理コストを所要時間見積もりに含めるべき** → 「30分」と書いたが実際は weather_cache rebuild が必須で 2 時間+
4. **Phase 6 全コンボ再実行は 60-70 分の固定コスト** → 小幅改善のために毎回実行は投資対効果悪い・複数改善を 1 実行にまとめる戦略が必要

**次セッション以降の優先候補（事業価値 × 投資対効果ベース）:**
1. **D 層予測モデル本番化** - Phase B/C で評価指標が揃った状態を E 層に表示。実装で見える価値が最大
2. **size 30-50% 帯張り付き救済** - 中央予測モデル改善（size_avg 精度向上）
3. **マルイカ×秀丸 n=950 wMAPE 65% 個別診断** - 最悪精度コンボの真因特定
4. **域外改善**: E 層表示・SEO・コンテンツ拡充など全コンボ再実行を伴わない改善

T33 系（小幅統計改善）は **後回し or 棚上げ** が妥当。詳細: `analysis/V2/analysis-improvement/90_決定ログ.md` 補遺13

---

## ✅ 過去完了（2026/05/21・main agent）

### T34 イカ系船宿ブログクロール路線・効果検証→撤退

**結論: 完全撤回（4船宿・2フェーズ検証で改善ゼロ・最大 +2.45pt 悪化）**

**動機**: イカ系 wMAPE 35-65% 改善余地大・マルイカ×秀丸 n=950 で 64.8% 最悪精度。船長blog で kanso_raw 補強→OBS 因子 (activity_n/wave_obs_n/tide_speed_n/water_color_n) の入力改善路線を仮説検証。

**Phase 1: 翔太丸 RSS（撤回）**
- 翔太丸 kanso avg=257字（既に詳細）・blog 109日6か月分取得
- A/B 2パターン抽出（A=構造化フィールド・B=A+活性キーワード）
- 結果: 9コンボ全部で 0〜+1.73pt 変動（改善なし）

**Phase 2: kanso 薄船宿 3船宿（撤回）**
- ユーザー指摘「翔太丸は釣りビジョン側で既充実で当然効果ない」→ kanso 薄船宿選定
- 儀兵衛丸 (avg 1字) / 長三朗丸 (avg 1字) / 喜平治丸 (avg 63字) で各6か月クロール
- 平安丸 (avg 4字) は SPA・JS動的で静的HTMLに釣果なし → 除外
- 秀丸 (avg 40字・n=1246) はユーザー判断で除外（釣りビジョンと同内容と判定）
- 喜平治丸の本文は ＜マルイカ＞ 等 山括弧マーカーで魚種別釣果セクション切出可能と判明
- 19コンボ評価: 改善なし・4コンボで +1.04〜+2.45pt 悪化

**失敗の根本原因（次回検討時必読）:**
1. **新規追加レコードの数値の質が catches_raw 既存品質に達しない**: blog の「0-33杯」を新規レコードに追加すると cnt_avg 計算が歪む
2. **既存 OBS 因子辞書とのキーワード重複出現**: kanso_raw に blog 由来キーワードを追記すると activity_n / wave_obs_n 等が過剰反応
3. **kanso 薄船宿でも予測モデルは weather_cache.sqlite 経由で既に最適化されている**: kanso 不足は精度悪化の真因ではない
4. **異粒度・異定義データを同パイプラインに混ぜると劣化する典型例**

**成果物（流用可能）:**
- 翔太丸 blog HTML 109日 (tmp_shotamaru/)
- 3船宿 blog HTML 458件 (tmp_3ships/{gihee,chozaburo,kiheiji}/)
- 実験データセット・CSV・SQLite (tmp_exp/)
- 抽出ロジック tmp_*.py 群（別 column で隔離するなら流用可）
- 詳細: `analysis/V2/analysis-improvement/90_決定ログ.md` 補遺12

**次の優先候補（イカ系改善・別軸）:**
1. D層予測モデル本番実装（補遺10 残課題・最優先）
2. size 30-50% 帯張り付き救済 中央予測モデル改善（補遺10 残課題）
3. MIN_MONTHS=4 緩和 + DO 独立カテゴリ化（plan_T33 残作業）
4. マルイカ×秀丸 n=950 wMAPE 65% 個別診断（kanso 不足以外の真因特定）

---

## ✅ 過去完了（2026/05/17・main agent）

### T32 全魚種再分析（chowari per-ship CSV 二重カウント排除後の効果検証）

**実行**: `run_full_deepdive.py --workers 4 --reset-best` × **59/59 OK・64分56秒**

**事前クリーンアップ:**
- `data/V2/aisho-maru_2026-*.csv` 等 per-ship CSV **59ファイル削除**（20船宿×3か月）
- 旧 chowari_to_csv.py が生成していた船宿別月別 CSV が `combo_deep_dive.py:1150` `os.listdir(DATA_DIR)` で全 read され、consolidated `chowari_*.csv` と **92.6%重複** (1,116/1,205行) で二重カウントの潜在バグ
- 削除前 data 整合性検証: renamed後 (gi-maru→義丸（大原)) で全データ chowari_*.csv 内に存在・データ消失ゼロ
- ships.json `source_priority` 補完は不要と判明（chowari 170船宿全て設定済・chowari-XXXXX 独立slug)
- fishing_v + chowari 二重存在は 24行/125,138 = 0.02% で許容

**全主要指標で改善:**

| 指標 | T31（2026/05/12）| **T32（2026/05/17）** | 差分 |
|---|---|---|---|
| combo_meta | 369 | **384** | **+15** |
| 船宿数 | - | 112 | - |
| 魚種数 | 55 | 55 | ±0 |
| **H=0 cnt_avg wMAPE P50** | 38.09% | **37.27%** | **-0.82pt** ✅ |
| **BL-2勝率** | 92.5% | **95.8%** | **+3.3pt** ✅ |
| **OOS r 平均** | +0.466 | **+0.500** | **+0.034** ✅ |

**商品的中率（promise_break_rate P50・低いほど良い）:**

| metric | T31 | **T32** | 差分 |
|---|---|---|---|
| **cnt** | 14.16% | **6.38%** | **-7.78pt** 🎯 大幅改善 |
| size | 31.53% | 31.58% | +0.05pt 横ばい |
| kg | 26.18% | **24.25%** | **-1.93pt** ✅ |
| **composite** | 16.16% | **13.93%** | **-2.23pt** ✅ |

**ホライズン別 wMAPE P50（cnt_avg, n>=30）:**
- H=0: 37.27% / H=1: 37.52% / H=3: 37.59% / H=7: 37.70%
- H=14: 37.73% / H=21: 37.93% / H=28: 38.36%
- H=0→28 で差 1.1pt 以下 = SLOW_FACTORS の遠期間有効性が高い

**composite component_count 分布**: {1: 14, 2: 317} （T31 補遺10: {1:14, 2:276, 3:0} → +41件）

**改善要因（仮説）:**
1. per-ship CSV 59件削除で **二重カウント源排除**（cnt 系で-7.78pt 大改善の主因）
2. chowari 経由 +15 コンボ追加で母集団拡大
3. T31 以降の catches_raw +1,208件（自然蓄積）

**既知の要確認事項:**
- composite metric の winkler 平均=0.00（T31 比で計測仕様変化か算式問題・別途調査）

**判定:** 全 KPI 改善で T32 効果確定。per-ship CSV 削除の効果が cnt 系で特に顕著。次セッション以降は予測モデル本番化（D層）または size promise_break 31.58% の張り付き救済。

---

## ✅ 直近完了（2026/05/12・main agent）

### T31 全魚種再分析（船宿+96・hist_rows+27,233・ポイント正規化+kanso強化の総合効果検証）

**実行**: `run_full_deepdive.py --workers 4 --reset-best` × 59/59 OK・31分58秒

**全主要指標で改善:**

| 指標 | 前回（2026/04/19）| **今回（2026/05/12）** | 差分 |
|---|---|---|---|
| combo_meta | 328 | **369** | **+41** |
| 魚種数 | 45 | 55 | +10 |
| **H=0 wMAPE P50** | 41.6% | **38.09%** | **-3.51pt** ✅ |
| **BL-2勝率** | 88.5% | **92.5%** | **+4.0pt** ✅ |
| **OOS r 平均** | +0.387 | **+0.466** | **+0.079** ✅ |
| composite_promise_break P50 | 13.94% | 14.16% | +0.22pt |
| cnt P50 | 6.57% | 6.38% | 改善 |

**改善要因（T31 で実装した4つの拡張の総合効果）:**

1. **船宿マスタ拡張**（ships.json 84→180・active 169）
   - WebSearch で fishing-v.jp 掲載済みの未登録船宿を発見し追加
   - 葉山(+4)・平塚(+2)・茅ヶ崎(+3)・小田原(+3)・小柴(+1)・久里浜(+4)・松輪間口(+7)・沼津(+2)・浦安(+1)・鹿島(+2)・御前崎(+5)・他20エリア
   - うち26隻でデータ取得成功（+8,503件）・66隻は fishing-v.jp 上で「全 0件」（船宿側未投稿）

2. **過去3年クロール実装**（catches_raw.json +27,233件・total 123,930件）
   - history_crawl_t31.py 新規・既存 CUTOFF=2023/04/04 と同期間
   - fetch() ヘッダ拡張（Accept-Language / Referer 等）で自然なクロール
   - data/V2/*.csv: 75,553→100,196行（+24,643行・+33%）

3. **相対ポイント正規化**（point_coords.json 303→330・+27点）
   - 主要海域 +15（神津島・金州・浜岡沖・佐島沖・葉山西沖等）
   - {port}+方向の追加 +12（葉山南沖・小田原南沖/西沖/東沖/湾内・平塚西沖/東沖・御前崎近場・網代南沖・横浜近場・江戸川店前・下田南沖）
   - crawler.py: _AREA_TO_PORT_SHORT マップ + _normalize_relative_point() で「南沖・近場・湾内・河口沖等」を自動変換
   - CSV正規化結果: 残存（未正規化相対表記）0件・主要例: 葉山南沖53・小田原南沖37・平塚河口沖36・御前崎近場28

4. **kanso 抽出強化**（4関数パターン拡張）
   - _extract_water_color (+8): ササ濁り・コーヒー色・味噌汁色・クリア・ブルー・黒潮の影響
   - _extract_tide_info (+13): 中潮・若潮・長潮・潮替わり・潮効いて・潮悪し・上り潮等
   - _extract_wave_info (+6): ベタ凪・大シケ・凪ぎ・うねり強等
   - _extract_weather (+7+重複防止): 薄曇り・豪雨・霧雨・猛暑・寒波等
   - CSV非空率: tide_info 1.6%→2.1% / wave_info 0.1%→0.3% / weather 0.6%→0.7%

**判定:** 主要KPI全改善でT31効果確定。次セッション以降は予測モデル本番化（D層）またはまだ未対応の魚種ページ範囲拡張へ。

---

### ALL_FISH 4魚種追加・新規5コンボの combo tuning 完了

### ALL_FISH 4魚種追加・新規5コンボの combo tuning 完了

**背景**: `docs/fish/` には 62 種の魚種ページがあるが、`run_full_deepdive.py` の `ALL_FISH` には 55 種しか入っておらず、CSVデータがあるのに分析対象から漏れている魚種が 4 種あった（イシモチ・キントキ・ハナダイ・アナゴ）。

**実行1: run_full_deepdive.py イシモチ キントキ ハナダイ アナゴ --workers 4**（1分26秒・4/4 OK）

combo_meta 追加（5コンボ・全て BL-2 勝利）:

| 魚種 | 船宿 | n | wMAPE | composite pb |
|---|---|---|---|---|
| アナゴ | 吉野屋 | 54 | 34.1% | 11.1% |
| イシモチ | 小柴丸 | 414 | 39.3% | 23.3% |
| キントキ | 敷嶋丸 | 78 | 48.3% | 20.2% |
| ハナダイ | 大盛丸 | 57 | 31.9% | 15.8% |
| ハナダイ | 勇幸丸 | 45 | 28.9% | 22.0% |

- wMAPE 28.9〜48.3%（全体 P50=37.3% と同水準）
- composite pb 11.1〜23.3%（既存 P50=13.94% に対し概ね許容範囲）
- 未生成2コンボ（キントキ×勇盛丸・ハナダイ×孝徳丸）: MIN_N_COMBO=30 の有効レコード閾値で除外（自然蓄積待ち）

**実行2: combo_tuning JSON 充填**

5コンボの combo_tuning JSON に以下を充填:
- adopted_factors（16〜23件/コンボ）
- points / modal_coord / multi_point_risk
- trip_models（0〜1件/コンボ）
- point_depth_models（0〜3件/コンボ）
- water_color_models（0〜2件/コンボ）

`update_combo_tuning_segments.py` に以下を追加（149行）:
- `--target` オプション（特定コンボのみ処理）
- `fill_missing_fields()` 関数（adopted_factors / points 系の補完）

**code-reviewer 指摘の MAJOR 2件を修正済み:**
- `n_valid=null` フォールバック（フラグ系・天文系因子で `combo_deep_params` に該当行が無い場合 0 に）
- `points.pct` の母数をフィルタ後の `total` で計算（合計 100±1%）
- `TODAY` を `date.today().isoformat()` に動的化（MINOR-4）

**変更ファイル**:
- `analysis/V2/methods/run_full_deepdive.py`（ALL_FISH 55→59種）
- `analysis/V2/analysis-improvement/update_combo_tuning_segments.py`（149行追記 + 修正）
- `analysis/V2/analysis-improvement/combo_tuning/`（新規3 + 更新2 = 5ファイル）
- `analysis/V2/results/analysis.sqlite`（combo数 323→328・gitignore）

---

## ✅ 直近完了（2026/05/09 早朝・main agent）

### Phase C composite_hit_rate 採用確定（補遺10 追記）

**実行**: `run_full_deepdive.py --workers 4 --reset-best` で 55/55 OK・43分51秒

**全コンボ適用後 backtest（H=0, n>=30）:**

| metric | n | promise_break P50 | coverage avg |
|---|---|---|---|
| cnt | 290 | 11.0% | 79.4% |
| **composite** | **290** | **13.94%** | **69.4%** |
| size | 181 | 31.8% | 40.4% |
| kg | 103 | 25.7% | 42.2% |

**設計**:
- 加重平均 cnt:size:kg = 0.6:0.3:0.1（線形加重和・行レベル集計）
- combo_range_backtest に metric='composite' 行追加（既存非破壊）
- component_count 列で 1/2/3 を記録（{1: 14, 2: 276, 3: 0}）
- HTML 表示なし・内部評価指標のみ（補遺3 整合）

**判定: 採用確定**
- 成功基準 9 項目全クリア（Plan §4）
- composite_promise_break P50=13.94% は cnt 11.0% に近く、重み 0.6 の cnt 支配が事業方針通り
- レビューサイクル v1→v1.5・5巡（CRITICAL 解消後 MINOR 連鎖）→ 実装着手判断

**詳細**: `analysis/V2/analysis-improvement/90_決定ログ.md` 補遺10 / `plan_C_2026-05-08.md` v1.5

### Phase B-β-4 全コンボ再実行・採用確定（補遺9 追記・前セッション分）

**実行**: 22:15 JST 開始 → 22:42 JST 完了・55/55 OK・26分59秒（`run_full_deepdive.py --workers 4 --reset-best`）

**全コンボ適用後 backtest（H=0, n>=30, 103コンボ）:**

| 指標 | Phase A 同一定義（旧）| Phase B-β-4（新）| 改善幅 |
|---|---|---|---|
| **kg promise_break P50** | 55.56% | **23.93%** | **+31.63pt** |
| kg coverage 平均 | 67.87% | 42.24% | -25.6pt（許容）|
| kg over_expect 平均 | 19.97% | 36.24% | +16.3pt（KPI 外）|
| kg winkler 平均 | 2.52 | 4.08 | +1.56（許容）|

**判定: A 採用確定**
- 同一定義基準 +31.63pt は plan_kg v2 撤回基準（+15pt）の **2.11倍改善**
- 副作用（winkler/coverage/over_expect 悪化）は数学的必然・補遺6/7/8 と同方針で許容
- MIN_N=5 採用維持（マダイ×ちがさき丸 非NULL率 5% でも改善幅大・グローバル比率効果が支配的）

**1コンボ動作確認結果:**
- マダイ×ちがさき丸（n=42）: 55.56% → 40.48%（+15.06pt・撤回基準ギリギリ）
- マハタ×幸丸（n=83）: 55.56% → 26.50%（+29.06pt・余裕クリア）

**詳細**: `analysis/V2/analysis-improvement/90_決定ログ.md` 補遺9

### Phase B-α' 全コンボ再実行・採用確定（補遺8 追記・前セッション分）

**実行**: 17:26 JST 開始 → 19:36 JST 完了・55/55 OK・130分52秒（`run_full_deepdive.py --workers 4 --reset-best`）

**全コンボ適用後 backtest（H=0, n>=30, 181コンボ）:**

| 指標 | Phase A 同一定義（旧）| Phase B-α' 全（新）| 改善幅 |
|---|---|---|---|
| **size promise_break P50** | 98.4% | **31.25%** | **+67.2pt** |
| size coverage 平均 | 高い | 0.40 | 大幅低下 |
| size over_expect 平均 | 0.02 | 0.32 | +30pt 増加 |
| size winkler 平均 | 5.8 | 23.2 | +17.4 増加 |

`combo_decadal.avg_size_min/max` 充足率: 81.4%（6598/8105）。残り 18.6% は旬別 n<10 で全期間グローバル比率にフォールバック（仕様通り）。

**判定: A 採用確定**
- 同一定義基準 +67.2pt は plan_size 期待値（+30pt）の **2.24倍改善**
- 副作用（winkler/coverage/over_expect 悪化）は数学的必然・補遺6/7 で許容ドメイン確定済み
- pb 30-50% 帯張り付き 98コンボ（54.1%）は pred_avg と actual_avg の系統的乖離が原因 → P20→P10 への比率変更では救えない・中央予測モデル別軸の改善要

**詳細**: `analysis/V2/analysis-improvement/90_決定ログ.md` 補遺8

---

## ★ 次セッションでやること（優先度順）

### 1. 30-50% 帯張り付き救済（中央予測モデル改善）

- size: 31.8% で帯張り付き残存（kg は 25.7% / composite 13.94% で解消気味）
- pred_avg と actual_avg の系統的乖離が原因
- 中央予測モデル（size_avg）の精度向上が本質的解決
- Phase B/C 系とは別軸の Plan 化が必要

### 2. D 層予測モデル本番実装

- Phase B/C で評価指標が揃った（cnt/size/kg/composite の promise_break P50 確定）
- D 層は予測モデルの本番化（cnt P50=11.0%・composite P50=13.94% を維持して実装）
- 設計済み・実装待ち（CLAUDE.md 「未実装・ブロック中」）

### 3. キハダマグロ winkler 高止まり時の E 層フィルタ（plan_kg v2 リスク 7・覚書）

- キハダマグロ winkler=21.0（kg 改善後も高止まり懸念）
- E 層で winkler 閾値フィルタが必要なケース判定

### 4. cnt 系の改善検討（優先度低）

**現状値（H=0, n>=30, 290コンボ）:**
- cnt promise_break P50 = **6.57%**（既に十分低い）
- cnt coverage 平均 = 0.79 / over_expect 平均 = 0.32

| 案 | 内容 | リスク評価 | 期待効果 |
|---|---|---|---|
| B-β-1 | バックテストから ratio override 撤去（独立予測評価）| 04/13 撤回パターン高リスク | 不明 |
| B-β-2' | 実測幅ベース cnt 版（Phase B-α' 同型・P50 → P20/P80）| 低リスク | 限定的（既に良好）|
| 保留 | cnt は良好で改善余地少 | 無リスク | - |

---

## ✅ 直近完了（2026/05/08 前半）

### 「商品的中率」KPI Phase A 実装（コミット 2b25b2d3）

- combo_range_backtest に metric 列追加（PK: fish, ship, metric, horizon）
- cnt → cnt/size/kg の 3 メトリックに拡張
- size/kg ループ分母を NULL 除外後 n_valid に統一

**90_決定ログ「補遺2 + 補遺3」追記:**
- 出力形式の絶対制約: min〜max のみ・avg は出さない
- 重ねレンジ禁止・min/max 別カード禁止
- 表示: 数 `min匹〜max匹` / 型 `min cm〜max cm` / 重 `min kg〜max kg`

**Phase A 全コンボ再実行（H=0, n>=30）:**

| metric | コンボ数 | promise_break P50 | coverage | over_expect | bowzu | winkler |
|---|---|---|---|---|---|---|
| cnt  | 290 | 6.7%  | 79.3% | 32.1% | 16.2% | 18.33 |
| size | 181 | 52.9% | 90.6% | 2.0%  | N/A   | 5.67  |
| kg   | 103 | 55.6% | 67.9% | 20.0% | N/A   | 2.52  |

**重要発見:**
- cnt 精度安定
- size/kg promise_break ≈ 53-56% で系統的に過大予測
- 構造的問題: size_avg=(min+max)/2 で actual_avg より高めに張りつく → Phase B-α' で対処

---

## ✅ 過去セッション要約（2026/04/11〜04/22）

**2026/04/22: 過去データ補完（コミット 3146af3a）**
- catches_raw.json: 89,612 → 96,697件（+7,085件）
- CSV再生成: 74,966行
- 全種再分析後精度: H=0 wMAPE P50 39.4% / BL-2勝率 94.0% / combo_meta 252 / kaiyu_promoted 14

**2026/04/22: FAST変数 horizon フィルタ**
- _FAST_FACTORS frozenset + FAST_MAX_H=7 + _h_days() 追加
- H>7 で波/風/潮流等を correction から除外

**2026/04/19: BL2負けコンボ診断・改善**
- MIN_MONTHS=6 ガード追加（タチウオ×吉野屋 wMAPE=404% 対策）
- use_fallback 自動判定 + 手動追加: 19件
- ムギイカ KAIYU_FISH 追加・KAIYU_PROMOTE_WMAPE_THR 60→62 緩和

**2026/04/19: SLA特徴量追加**
- kuroshio_sla_monthly / sla_pelagic_monthly を SLOW_FACTORS に追加
- 169コンボ採用・強相関: イナダ avg|r|=0.616 等

**2026/04/19: CSV正規化修正**
- 「数匹」→ 0〜2匹変換（cnt_avg=1）
- normalize_tsuri_mono 数字ノイズ除去（71件→0件）
- マハタ5船宿 30件超え

**2026/04/13: バックテスト方式変更（根本改善）**
- walk-forward → leave-one-month-out CV
- H=0 wMAPE 中央値: 42.8% → 39.9% (-2.9pt)
- BL-2勝率: 83.0% → 90.8% (+7.8pt)

**2026/04/13: 過学習対策**
- fold_corr_thr 適応的化 max(0.15, 1.96/√n)
- TOP-K MAX_FACTORS=10
- alpha_scale 上限 2.0 → 1.2
- BL2勝率 +5〜6pt 改善

**2026/04/13: 欠航予測コンボレベル化**
- F1: 81.8% → 97.0% (+15.2pt)
- カバー船宿 4→10 / 評価対象欠航 9→64件

**2026/04/13: Forecast API 統合（predict_count.py）**
- 未来日 → Forecast/Marine API から気象取得（風/温/圧/降水/波/うねり/SST/潮流）
- predict_log.jsonl に予測ログ追記
- cnt_max OOS r: 0.146 → 0.364（ratio-based）

**2026/04/12: 潮流・乗っ込みフラグ追加**
- weather_cache に current_speed/current_dir 列（Open-Meteo Marine API）
- spawn_season_n（2〜5月=1）SLOW_FACTORS に追加
- KAIYU 自動昇格システム実装

**2026/04/11: 回遊魚★チャンス評価システム**
- KAIYU_FISH 定数・combo_star_backtest テーブル新設
- 定量ベース★割当（P20/P40/P60/P80）
- 良日ライン = actual P75
- promise_break_rate を PRIMARY KPI に確定

---

## 確定した設計方針（変更不可）

### 回遊魚評価設計
- KAIYU_FISH: {"シイラ", "カツオ", "キハダマグロ", "ブリ", "ワラサ", "イナダ", "サワラ", "カンパチ", "ムギイカ"}
- デフォルト: ★チャンス評価（P20/P40/P60/P80分位）
- 昇格条件: H=7 wMAPE < **62%** + BL-2勝ち → kaiyu_promoted=True → 匹数レンジ予測
- 良日ライン: actual P75（good_line ≤ 3 のコンボは kaiyu=None）

### 特徴量分類
- **SLOW_FACTORS**（全H有効）: SST, 気温, 気圧, 潮汐, 月齢, 土日祝, 連休, 夏休み, spawn_season_n, kuroshio_sla_monthly, sla_pelagic_monthly
- **FAST_FACTORS**（H>7 無効）: 風, 波, うねり, 降水, 前週釣果, 台風, current_speed/dir
- FAST_MAX_H = 7（per-combo override: メバル×第三幸栄丸 = 3）

### バックテスト CV 設計
- leave-one-month-out: 各テスト月以外の全データで学習
- MIN_MONTHS=6 ガード（短期データの偽相関防止）

### 過学習対策
- fold_corr_thr 適応的: max(0.15, 1.96/√n)
- TOP-K MAX_FACTORS=10
- alpha_scale 上限 1.2

### weather_cache.sqlite スキーマ
- 列: lat, lon, dt, wind_speed, wind_dir, temp, pressure, wave_height, wave_period, swell_height, sst, precipitation, current_speed, current_dir
- 153座標 × 2023-01-01〜今日 × 3時間毎 ≒ 145万行

### 評価指標設計
- promise_break_rate = PRIMARY KPI
- pred_hi = cnt_max モデル出力 → actual_max と比較
- pred_lo = cnt_min モデル出力 → actual_min と比較
- 失敗優先順位: Max過大予測 > ボウズ見逃し > Max保守すぎ > Min保守すぎ
- 出力は min〜max のみ・avg は出さない

### FISH_MAP → 廃止
- tsuri_mono + main_sub で代替

### ships.json
- exclude: true → 利一丸・岩崎レンタルボート・海上つり堀まるや
- boat_only: true → 青木丸
- 有効船宿: 75件 + 静岡多数

### データ収集状況（2026/04/22 時点）
- catches_raw.json: 96,697件
- data/V2/*.csv: 75,553行
- 期間: 2023/01/01〜2026/04/03

### ポイント解決（3段階フォールバック）
```
① point_place1 → point_coords.json（306ポイント）→ 座標
② 空/航程系 → ship_fish_point.json（73船宿）→ ポイント名 → 座標
③ ② 未登録 → area_coords.json（58エリア）→ 直接 lat/lon
```
解決率: 94.9%

### 価格・マネタイズ
- 月額500円 / スポット100円
- 無料=事実、有料=分析+予測

---

## 後回し・未実装
- [ ] 決済（Stripe等）
- [ ] AdSense審査待ち（2026/03/21申請）
- [ ] X自動投稿（アカウントロック解除待ち）
- [ ] crawl.yml Node.js 20→24
- [ ] ちがさき丸×マダイ/シーバス/メバル 個別改善（r=-0.17等・★候補）
- [ ] 外道表示機能（by_catch × 旬別集計 → 予測ページ）
- [ ] 有料ページUI 実装
- [ ] predict_count.py: 同一座標 Forecast API キャッシュ
- [ ] サワラ・イナダ・タイ五目（wMAPE 70-78%）の診断
- [ ] クロムツ（68%）の特徴量見直し
- [ ] tsuri_mono 空 363件の正規化失敗レコード調査
- [ ] カツオ×幸丸（29件）・たいぞう丸（28件）: 30件突破待ち
