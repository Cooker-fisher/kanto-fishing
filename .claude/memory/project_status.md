# プロジェクト現在地

**最終更新: 2026/09/03**（このファイルは「現在地」のみ。履歴は書かない）

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

**GSC 月次（2026-09-03 に真値へ訂正）**: 8月 **424click / 21,970impr**（7月 292 / 11,933）。
旧記載「8月 120click / 6,263impr」は**クエリ次元 CSV の値で、GSC の匿名化により
真値の約 1/3 しか入っていなかった**。詳細は `analytics/README.md` と決定ログ 2026-09-03。
種別内訳は `python analytics/gsc/trend.py --monthly`（ページ次元＝真値を読む）。

| 種別 | 8月 impr | click | CTR |
|---|---:|---:|---:|
| area | 9,041 | 202 | 2.23% |
| fish | 5,883 | 111 | 1.89% |
| fish_area | 2,084 | 61 | 2.93% |
| **ship** | 2,944 | **14** | **0.48%** |

⚠ **クエリ次元 CSV（`analytics/gsc/*.csv`）の合計をサイト KPI に使わない。**
欠測率はページごとに 9〜71% とばらつくので、ページ別 CTR の比較も
`analytics/gsc/pages/*.csv` からでないと順位が入れ替わる。

**インデックス（2026-09-03 に内訳を実測して再解釈）**: docs/ の HTML **2,187本のうち
1,363本は意図的な noindex**、indexable は **824本**。GSC UI の「未登録 992」の大半は
狙いどおりの noindex で、**「手動投入では追いつかない」は読み違いだった**。
indexable 824本のうち 572本（69%）は GSC 露出実績あり。

露出ゼロの 252本を `python analytics/gsc/inspect_urls.py --zero-impression` で実査済み:

| coverageState | 本数 | 打ち手 |
|---|---:|---|
| 送信して登録されました | 99 | 載っている。順位が低いだけ |
| 検出 - インデックス未登録 | 81 | クロール予算。fish 6本を含む |
| noindex で除外 | 42 | 意図どおり |
| URL が認識されていません | 16 | komase-sim 5本は noindex 済み |
| 404 / クロール済み未登録 | 14 | 5月のクロール結果。sitemap 収載済み |

**fish の魚種ページ 14本が未登録**。内部リンクでも sitemap でもない（fugu は被リンク 636・
sitemap 収載済み）。本文字数が露出ゼロ 14本＝平均 2,682字 / 露出あり 58本＝3,300字 で、
H2 構成は同一＝**データ量が足りないだけ**。一次体験は未釣行なので当面手が無い。

手動投入の進捗と残リストは `analytics/gsc/manual_index_requests.md`（SoT）。
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

**判定はまだできない**（2026-09-03 時点で GSC は 09-01 まで・08-31 週は 2日ぶん）。
効果判定は 9月中旬。`python analytics/gsc/trend.py` の行末に「※n/N日ぶんのみ」が
出ている期間は他の行と同じ土俵ではない。

**判定方法は `analytics/gsc/trend.py` の INTERVENTIONS に固定済み**:
- #67 … ship の imp 加重 pos が 10 を切るか（投入前は10週連続で 10.6〜17.8）
- #68 … `analytics/serp/report.py --diff` で title_source が h1→title に変わるか。
  **主指標は katsuura**（iioka と amatsu は 08-10 週の原因不明 -70% で判定に使えない）

⚠ **どちらも因果は未証明**。

### ✅ 「クロール頻度が原因」は棄却済み（2026-09-03）

フォールバック仮説として置いていた「SERP に古い日付が出る＝クロールが遅い」は、
URL Inspection の `lastCrawlTime` で否定された:

| ページ | 最終クロール | CTR | pos |
|---|---|---:|---:|
| shizuura | **2026-08-17（16日前・最古）** | **4.05%** | 8.5 |
| kanaya | 2026-09-02 | 4.21% | 7.6 |
| katsuura | 2026-08-31 | 1.28% | 8.3 |
| amatsu | 2026-08-29 | 0.53% | 7.5 |

**最もクロールが古い shizuura が CTR 2位**。クロール頻度に投資しても戻らない。
判定は SERP 再実査（`analytics/serp/report.py --recheck`）に一本化する。

### ⚠ #68 の判定は交絡している（2026-09-03 に判明）

投入前 n=6 の area 実査で、**title_source と SERP日付表記が完全に一致して動いていた**:

|  | 日付なし | 日付あり |
|---|---|---|
| title 維持 | 2ページ 1,943impr **3.91%** | — |
| h1 に差し替え | — | 3ページ 3,632impr **1.62%** |

対角2セルしか無い＝CTR 差をどちらにも帰属できない。再実査で両方が同時に動いたら
「#68 が効いた」とは言えない。`python analytics/serp/report.py` の「交絡チェック」が
毎回この警告を出す。分離には「h1 × 日付なし」か「title × 日付あり」の実査が要る。

**再実査の手順**: `python analytics/serp/report.py --recheck`（実査済みクエリの一覧・
前回の title_source と日付表記つき）→ ブラウザで開いて `observations.json` に追記 →
`--diff` で変化を見る。`--suggest` は未実査クエリ専用なので判定には使えない。

### area の CTR はページ単位で固定（位置では説明できない）

2026-07〜08（ページ次元＝真値）: katsuura 1.28%（pos 8.3）に対し kanaya 4.21%（pos 7.6）。
**ほぼ同じ順位で 3.3倍**。iioka(2.22%/4,458impr) + katsuura(1.28%/2,106) +
amatsu(0.53%/756) が kanaya/shizuura 並みになれば **+150click / 2か月**
＝ 同期間のサイト全体 716click に対し +21%。ここが最大の一点。

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
  fish_area_notes 拡大
- **2026-09-03: 19種 → 23種**。未インデックスだった サワラ・イトヨリ・マハタ・アカイカ に
  釣行メモを追加（本文 +880〜980字）。年が分からない釣行用に `date_note` を新設
  （年を推測して `date` に書かない／`経験メモ` にすると単発釣行を誤って説明するため）

---

## 次の候補（未着手・優先度順）

1. **リモートの未評価ブランチ 26本** — 2026-08-30 の掃除でローカルは main + worktree 分のみ、
   リモートはマージ済み42本+確認済み2本を削除した。残る26本は**中身未確認なので残してある**
   （redesign-update から競合調査19行を救出した実績があるため機械的削除はしない）。
   評価して残すか消すかは別タスク。決定ログ 2026-08-30 参照
2. ~~GSC 推奨事項の警告 area/iioka.html -58%~~ → **2026-08-30 に切り分け済み**。
   iioka と amatsu だけが 08-10 週に -70%（順位・CTR は不変・別称固有でもない・
   サイト全体は横ばい）。需要減とマッチ喪失は GSC だけでは分離できないので、
   **#68 の主指標を katsuura に変更**した。9月に iioka が戻らなければ SERP 実査へ
3. **Tier2 拡大** — パイロット5 の GSC 反応を見て残り約29ページへ展開
4. ~~fish_area 薄ページの物理削除/統合~~ → **2026-09-03 に一部着手**。
   `_FA_GSC_PROVEN_SLUGS`（実需要が証明されたページの noindex 免除）が
   クエリ次元 CSV 由来で 13 slug しか拾えていなかったのを真値に直し、
   閾値を `impr>=2` → `clicks>=1 or impr>=10` に締めて **13→167 slug**。
   うち **46本が index 復帰**（次の CI フル実行で反映）。
   残る noindex 約1,030本の物理削除は未着手。※AdSense 判定は外から検証不可＝仮説
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
