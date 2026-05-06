# 有料ページ mockup 棚卸し報告書
作成日: 2026-05-06  
調査者: data-reviewer  
対象: design/V2/mockup-paid-*.html / mockup-premium.html / mockup-plan.html / mockup-mypage.html（7ファイル）

---

## 表1: ページ別「決まっている要素」一覧

| mockup | 主目的 | 含まれるセクション | データソース | チラ見せ範囲 |
|--------|--------|-----------------|------------|------------|
| mockup-paid-dashboard.html | ログイン済み会員のホーム | ①7日間海況予報 ②TOP10自信予測 ③釣行予定ウォッチ ④船宿ウォッチ ⑤LINE通知ルール ⑥お気に入り動向 | combo_backtest / combo_wx_params / cancel_thresholds / prediction_log | 対象外（全表示・会員限定） |
| mockup-paid-forecast.html | 魚種×日付のマトリクス予測一覧 | エリアフィルター / 信頼度フィルター / 魚種×7日間マトリクス表（色分け★付き） | combo_backtest / combo_decadal / cancel_thresholds_combo | 対象外（会員限定） |
| mockup-paid-calendar.html | 魚種別旬カレンダー一覧（ハブページ） | 魚種カード12種（52週ミニプレビュー・現在位置・信頼度）/ フィルタタブ | combo_decadal / combo_weekly | ハブページ自体は判定なし |
| mockup-paid-fish-calendar.html | 1魚種の旬カレンダー詳細（アジ例示） | 魚種切替タブ / 相関コメント / サマリーカード / 8エリア×数/型×52週ヒートマップ | combo_decadal / combo_weekly / combo_season | 対象外（会員限定） |
| mockup-premium.html | 無料→有料の課金導線（LP） | 的中率表示 / 機能紹介カード / 予測サンプル（TOP3チラ見せ） / プラン選択 / FAQ / ユーザーの声 | prediction_log（is_good_hit / pred_pct / actual_pct） | TOP3予測サンプルをフル表示（課金前の価値体験） |
| mockup-plan.html | 料金プラン比較ページ | 価値訴求 / 3プラン比較（無料/月額/スポット）/ 機能比較表 / 支払い方法 / 友達紹介 / 利用規約抜粋 | なし（静的） | なし（メタ情報ページ） |
| mockup-mypage.html | 会員管理ページ | LINE通知ルール / クイックアクション / お気に入り（魚種/エリア/船宿）/ 通知履歴 / 購入履歴 / 友達紹介 / 設定 | ユーザーDB（未実装） | なし（会員限定） |

---

## 表2: ページ別「未決事項」一覧

| mockup | 未決項目 | なぜ未決か | 決めないと本番化できない度 |
|--------|---------|-----------|----------------------|
| mockup-paid-dashboard.html | ①釣行予定ウォッチ機能（日付+魚種+船宿を「登録」して追跡） | ユーザーDB・セッション管理が必要。GitHub Pages静的サイトでは実装不可 | 高 |
| mockup-paid-dashboard.html | ②LINE通知連携（LINE Messaging API or LINE Notify） | 外部API未選定・未契約。LINE Notify 2025年3月終了済みのため LINE Messaging API が必要 | 高 |
| mockup-paid-dashboard.html | ③「直近的中率 72%」の算出ロジック | prediction_log に is_good_hit は存在するが、的中の定義（方向一致?閾値?）が未明文化 | 中 |
| mockup-paid-dashboard.html | ④ヒーローの「田中さん」= ユーザー名表示 | 認証（ユーザーID取得）が必要 | 高 |
| mockup-paid-forecast.html | ①予測データ本体（D層未実装） | predict_count.py は存在するが、全魚種×全エリア×7日分の一括生成パイプライン未実装 | 高 |
| mockup-paid-forecast.html | ②セルタップで詳細ページへの遷移先 | `premium/forecast/daily/{date}.html` の設計はURLに存在するが中身のmockupが未作成 | 中 |
| mockup-paid-forecast.html | ③「欠航」セルの自動判定基準 | cancel_thresholds_combo は存在するが、予報値との突合ロジックが未実装 | 中 |
| mockup-paid-calendar.html | ①「今週ピーク中」「これから上昇」フィルタの算出ロジック | combo_decadal から現在週との比較で算出可能だが未実装 | 中 |
| mockup-paid-calendar.html | ②「12魚種」の確定リスト | mockupには12魚種名が明示されているが、combo_meta にコンボが存在しない魚種をどう扱うか未決 | 中 |
| mockup-paid-fish-calendar.html | ①「数ピーク週」「型ピーク週」の算出ロジック | combo_weekly の cnt_avg / size_avg から導出可能だが、week単位集計とのマッピング未実装 | 中 |
| mockup-paid-fish-calendar.html | ②相関コメント文章の生成ロジック | ハードコーディングかテンプレート生成か未決。combo_season / combo_keywords を参照できるが書式未設計 | 中 |
| mockup-paid-fish-calendar.html | ③セルタップ先（週×エリア詳細予測ページ） | URL設計上 `premium/forecast/area/{area}.html` があるが魚種×週×エリアの3軸ページは未設計 | 低（後でよい） |
| mockup-premium.html | ①「初回7日間無料トライアル」の有無 | 90_決定ログ.md の未決定事項欄に明示（決済プロバイダ未選定と紐づく） | 高 |
| mockup-premium.html | ②「他社A・他社B」との的中率比較表記 | 根拠データなし。景表法上「比較広告」の要件を満たすかの確認が必要（推測） | 高（法的リスク） |
| mockup-premium.html | ③ユーザーの声（口コミ）の取得方法 | ベータユーザーが存在しないため現時点で実クチコミはゼロ | 中 |
| mockup-plan.html | ①スポット100円の対象範囲（1日分か1魚種分か） | 11_有料ページデザイン.md で「未決定」と明記。mockupには「月3回まで」記載あるが根拠不明 | 高 |
| mockup-plan.html | ②支払い方法（Stripe未連携） | 未実装。mockupには「Stripeが処理」と記載あるが契約・実装ゼロ | 高 |
| mockup-plan.html | ③友達紹介プログラム | mockupに詳細UI設計あるが、紹介コード発行・割引適用の仕組みは未実装 | 低（後でよい） |
| mockup-mypage.html | ①全機能がユーザー認証前提 | GitHub Pagesは静的配信のみ。認証・セッション管理はサーバーレス（Vercel Edge/Supabase等）を別途用意する必要 | 高 |
| mockup-mypage.html | ②連続利用日数（ストリーク）の取得方法 | サーバー側でのアクセスログ記録が必要 | 高 |

---

## 表3: 本番化に必要な作業（mockup → docs/premium/）

| ページ | 必要なcrawler.py関数 | 依存するデータ（既存/未実装） | 依存するC層テーブル |
|--------|---------------------|---------------------------|--------------------|
| mockup-premium.html → docs/premium/index.html | `build_premium_lp()` | prediction_log（既存）/ combo_backtest（既存） | prediction_log, combo_meta |
| mockup-plan.html → docs/premium/plan.html | `build_plan_page()` | なし（静的コンテンツ・Stripe実装後にCTA差替） | なし |
| mockup-paid-forecast.html → docs/premium/forecast/index.html | `build_premium_forecast()` | D層予測出力（**未実装**）/ cancel_thresholds_combo（既存）/ weather/YYYY-MM.csv（既存） | combo_backtest, combo_decadal, cancel_thresholds_combo |
| mockup-paid-calendar.html → docs/premium/calendar/index.html | `build_premium_calendar_hub()` | combo_decadal（既存）/ combo_weekly（既存） | combo_decadal, combo_weekly, combo_season |
| mockup-paid-fish-calendar.html → docs/premium/calendar/{fish}.html | `build_premium_fish_calendar()` | combo_decadal（既存）/ combo_weekly（既存） | combo_decadal, combo_weekly, combo_season |
| mockup-paid-dashboard.html → docs/premium/dashboard.html | `build_premium_dashboard()` | D層予測出力（**未実装**）/ 認証（**未実装**）/ LINE API（**未実装**） | 全テーブル + ユーザーDB |
| mockup-mypage.html → docs/premium/mypage.html | `build_mypage()` | 認証（**未実装**）/ ユーザーDB（**未実装**） | prediction_log + ユーザーDB |

---

## 表4: ページ間の重複・整合性

### 同じ情報が複数mockupに出ている箇所

| 情報 | 出現箇所 | 整合状況 |
|------|---------|---------|
| 「アジ 22〜48匹 ★★★★★」予測値 | dashboard TOP10(1位) / forecast マトリクス(4/6アジ) / premium サンプル(TOP3 1位) | 3箇所で同一値。本番では単一データソース（D層出力）から生成すれば一致する |
| 「的中率 72%」 | dashboard ヒーロー / premium LP（acc-box） | 同じ数値だが算出ロジック未定義 |
| LINE通知ルール | dashboard（ln-rule） / mypage（line-rule） | UIは別コンポーネントだが内容が完全に同一。どちらを「管理画面」とするか未整理 |
| 友達紹介プログラム | plan.html / mypage.html | plan: 制度説明、mypage: コード発行・実績表示。役割分担は自然 |

### ナビゲーション設計の関係性

- **無料→課金フロー（推奨順）**: 無料index → premium/index.html（LP） → premium/plan.html → 決済 → premium/dashboard.html → 各コンテンツ
- **有料内ナビ（dashboard内ナビ）**: ダッシュボード / 予測全覧 / 旬カレンダー / 履歴 / マイページ（5タブ）
- **mockup-plan.html のナビ**: 無料ナビ（釣果/魚種/エリア/有料プラン）を使用 ← 課金前ページとして正しい
- **mockup-premium.html のナビ**: 無料ナビを使用 ← 正しい
- **mockup-paid-*.html / mockup-mypage.html**: 有料内ナビ（ダッシュボード中心）を使用 ← 正しい

### 命名の不整合

| 箇所 | 表記 | 問題 |
|------|------|------|
| mockup-premium.html / mockup-plan.html | `mockup-premium.html` | ファイル名とURL設計 `/premium/index.html` が対応 |
| mockup-paid-*.html | `paid` | URL設計では `/premium/` に統一されているがmockupファイル名は `paid` 。本番化時に `/premium/` で統一すれば問題なし |
| mockup-plan.html | `plan` | URL設計では `plan.html` の記載なし。`/premium/plan.html` が想定されるが 90_決定ログ.md に明示なし |
| dashboard のナビ | `履歴`（mockup-history.html へのリンク） | mockup-history.html はnavのリンクに存在するが棚卸し対象7ファイルに含まれていない。有料版の「予測履歴」ページが1枚未作成 |

---

## 所見（200字以内）

最初に本番化すべきページは **mockup-premium.html（有料LP）+ mockup-plan.html（プラン比較）** の2枚セット。理由：（1）D層・認証・決済がゼロの現状でも静的生成可能、（2）prediction_log（既存・蓄積中）の is_good_hit / pred_pct を使えば「答え合わせチラ見せ」が今すぐ本物データで作れる、（3）無料ユーザーが最初に踏む課金導線がこの2枚であり、ここを整備しないとその先のダッシュボード群は機能しない。旬カレンダー（calendar/fish）はD層不要・combo_decadal のみで生成できるため2番手として有力。

