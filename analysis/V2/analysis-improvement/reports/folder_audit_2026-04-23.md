# フォルダ全体点検レポート 2026-04-23

目的: V2運用状況の棚卸し。CLAUDE.md / PIPELINE.md の記述と実態の乖離、V1残存、未整備箇所を洗い出す。

---

## 🔴 Critical（ドキュメントと実態の重大乖離）

### 1. HTML配信ディレクトリが CLAUDE.md と実態で不一致

**CLAUDE.md の記述**: ルート直下に `index.html / fish/ / area/ / forecast/ / sitemap.xml / style.css / main.js / pages/ / CNAME` が存在する前提で書かれている。

**実態**: これらは全て `docs/` 配下に配置されている。ルート直下には HTML ファイルは一切無し（`forecast.json` のみ）。

- `docs/CNAME` = `funatsuri-yoso.com`（ルートには CNAME なし）
- `docs/index.html` / `docs/fish/` / `docs/area/` / `docs/forecast/` / `docs/calendar.html` / `docs/sitemap.xml`
- `docs/style.css` / `docs/main.js` / `docs/pages/`
- crawler.py は `docs/` に書き出す実装になっている
- 直近コミット（e7b07ab8 update 2026/04/22 など）は `docs/` 配下への更新

**影響**: GitHub Pages のソースは `docs/` ブランチ設定になっているはず。CLAUDE.md を信じてルート直下を探すと「ファイルが無い」と誤判断する。新規参加者・サブエージェント双方にとって危険。

**対応**: CLAUDE.md のファイル構成ツリーを `docs/` 配下構造に更新。PIPELINE.md の E層表も同様に修正。

---

## 🟠 Warning（統計値・仕様の古い記述）

### 2. CLAUDE.md / PIPELINE.md の件数が古い

| 項目 | ドキュメント記述 | 実測 (2026-04-23) | 差 |
|---|---|---|---|
| catches_raw.json 件数 | 86,024件 (PIPELINE v2.4) / 84,757 (CLAUDE.md) | **96,697件** | +10,000件超 |
| data/V2/*.csv 行数 | 64,991行 | **75,553行** | +10,562行 |
| combo_meta | 246 | 252 | +6 |

→ 2026/04/22 の過去クロール補完・CSV再生成が反映されていない。PIPELINE v2.4 の日付(2026/04/22)と矛盾するので、次の分析実行後に更新。

### 3. weather_cache.sqlite 鮮度（infra_audit で既出）

- MAX(dt) = 2026-04-04 21:00 → catches_raw 最新 2026-04-22 に対して **19日遅れ**
- この間 (04/05〜04/22) の釣果に気象結合ができず、最新コンボ精度を劣化させている可能性
- 対応: `python ocean/rebuild_weather_cache.py`（約30分）実行推奨（ユーザー判断）

### 4. 未収録船宿 21件 in ships.json

`ships.json` に存在するが `catches_raw` に0件の船宿が21件:
平作丸・つね丸・とうふや丸・浜新丸・太郎丸・洋征丸・三喜丸釣船店・大和丸・棒面丸・美喜丸・信栄丸・勇幸丸・孝徳丸・小柴丸・弁天屋・新修丸・米元釣船店・荒川屋・栃木丸・儀兵衛丸・春盛丸

→ SID無効化 or 釣りビジョン掲載終了の可能性。`exclude:true` マーク検討。

---

## 🟡 Notice（中程度の整理すべき事項）

### 5. direct-crawl/ スクリプトが crawl.yml 未統合

- `direct-crawl/gyo_crawler.py`（忠彦丸・一之瀬丸・米元）
- `direct-crawl/shojiro_crawler.py`（庄治郎丸・2026/04/22 追加）
- `direct-crawl/koueimaru_crawler.py`（幸栄丸・2026/04/22 追加。気象推定のためローカル専用）

いずれも `.github/workflows/crawl.yml` に組み込まれておらず手動実行。gyo_crawler は PIPELINE.md で「毎日」と記述されているが実態は手動。

→ shojiro は天気依存なしなので CI 組込可能。koueimaru は weather_cache 依存で難しい。まず gyo/shojiro を統合するのが有益。

### 6. `tmp_shojiro.html` がルートに放置

git untracked。shojiro_crawler.py 開発時の残骸と思われる。削除推奨。

### 7. tsuri_mono空 547件 (0.72%)

正規化失敗レコードの魚種分布を確認すれば tsuri_mono_map_draft.json 改善余地あり。優先度低。

### 8. 弘漁丸 (2023/12/03〜) / はら丸 (2023/07/25〜) の欠落期間

`history_crawl` 対象候補。優先度低。

---

## ✅ 良好（V2移行完了・V1残存は許容範囲）

- `analysis/V1/` / `design/V1/` はアーカイブとして保持（CLAUDE.md 想定どおり）
- `data/V2/` 運用中、`dustbox/data_v1_stubs/` に旧 V1 スタブ退避済み
- `config.json` active_version=V2 / design_version=V2
- `crawl.yml` は Python 3.12 で実行
- analysis.sqlite: 36テーブル（ポイント別最適化完了・2026/04/20）

---

## 📋 対応優先度サマリー

| 優先度 | 項目 | アクション |
|---|---|---|
| 🔴 Critical | CLAUDE.md のファイル構成を `docs/` 配下構造に修正 | ドキュメント更新（今セッション対応可） |
| 🔴 Critical | PIPELINE.md E層表の出力先を `docs/` に修正 | ドキュメント更新 |
| 🟠 High | weather_cache 再構築（19日遅れ） | `python ocean/rebuild_weather_cache.py`（ユーザー判断） |
| 🟠 High | CLAUDE.md / PIPELINE.md の件数・combo_meta更新 | ドキュメント更新 |
| 🟡 Mid | direct-crawl スクリプトの crawl.yml 統合 (gyo/shojiro) | 要設計 |
| 🟡 Mid | 未収録21船宿の exclude 判定 | ships.json 編集 |
| 🟢 Low | `tmp_shojiro.html` 削除 | `rm tmp_shojiro.html` |
| 🟢 Low | tsuri_mono空 547件調査 | 分析タスク |
| 🟢 Low | 弘漁丸・はら丸 2023年補完 | history_crawl 実行 |

---

## 補足: 本セッションの分析スクリプト側対応

analyst が factor 宣言のみで中途半端だった以下5特徴量の SQL計算ロジックを combo_deep_dive.py に実装済み（未コミット）:

- `sst_delta_3d`（SST 3日前比）
- `pressure_delta_48h`（気圧 48時間前比・WX_FACTORS 追加漏れを補正）
- `kuroshio_sla_delta_1m`（黒潮SLA 月差分）
- `sss_delta_7d`（塩分 7日前比・NULL回避の nearest クエリ新設）
- `day_of_decade`（旬内日数 1〜11）

アジ×こなや丸で単体テスト済み（deep_params N=4 取得確認）。全種バックテストは次セッション: `python analysis/V2/methods/run_full_deepdive.py --workers 4 --reset-best`（60〜90分）。
