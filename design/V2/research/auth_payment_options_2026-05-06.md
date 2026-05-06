# 認証・決済方式 選択肢比較（2026-05-06）

**作成者**: data-reviewer  
**WebSearch**: 利用不可（ツール未ロード）。以下はすべて **AI知識ベース（〜2025-08）** による。  
公開情報として広く知られているパターンのみ記載。釣りビジョンVOD等の内部実装は「公開情報のみ」。

---

## 前提の整理

| 項目 | 現状 |
|------|------|
| ホスティング | GitHub Pages（静的サイト）|
| 配信ドメイン | funatsuri-yoso.com |
| サーバーサイド | **無し** |
| 有料価格 | 月額500円 / スポット100円 |
| ペイウォール方式 | チラ見せ（1件無料+CSSブラー）|

---

## 表1: 認証・決済方式の選択肢比較（4案）

| 案 | 認証方式 | 決済 | サーバー要否 | 月額固定費 | 実装コスト(週) | GitHub Pages継続 | 既存ドメイン継続 |
|----|---------|------|------------|----------|--------------|----------------|----------------|
| **A** Stripe + Cloudflare Workers | Magic Link or Google（Firebase Auth） | Stripe Checkout | Cloudflare Workers（エッジ） | 0〜5$/月 | 2〜3週 | ✅（DNS: CF経由） | ✅ |
| **B** Stripe + Firebase Auth + Functions | Google / メアド / パスワード | Stripe Checkout | Firebase Functions | 0〜5$/月（従量） | 2〜3週 | ✅（SPA埋込） | ✅ |
| **C** memberstack / Memberful（外部SaaS） | メアド+パスワード or Google SSO | Stripe（内包） | **不要**（SaaS側） | 2,000〜5,000円/月 | 0.5〜1週 | ✅（JS1行埋込） | ✅ |
| **D** Stripe + Vercel Edge Functions | Magic Link（Stripe Customer Portal） | Stripe Billing | Vercel（エッジ） | 0〜20$/月 | 3〜4週 | △（DNS移行必要） | ✅ |

### 案A: Stripe + Cloudflare Workers + Firebase Auth

GitHub Pages はそのまま。Cloudflareを「薄いAPIプロキシ」として使い、Firebase Authでトークン発行。月額課金はStripe Checkout→Webhookで購読状態をFirestore（無料枠）に書く。ブラー解除はFirebase IDトークンをlocalStorageに持たせてJSで判定。

- メリット: 無料枠が広い（CF Workers 10万回/日・Firebase Spark無料）。ドメイン移行不要。
- デメリット: 3サービス連携でデバッグが複雑。Firestore→Workers→GitHub Pagesの呼び出しフローが必要。
- スポット100円: Stripe Checkout（one-time payment）で実装可。購入後に一時トークン発行。

### 案B: Stripe + Firebase Auth + Hosting Functions（フルFirebase）

GitHub Pagesを廃止してFirebase Hostingに移行。Functions（Node.js）でStripe Webhookを受け、Firestoreに購読状態を保存。認証はFirebase Auth（Google/メアド）。

- メリット: Firebase完結で管理シンプル。Firebase Hosting + 独自ドメインは無料。
- デメリット: GitHub Pagesを捨てる必要（GitActionsの再設定が必要）。Functions有料枠超え時に課金。
- スポット100円: 実装可（one-time purchase → Firestoreに有効期限付きアクセス権を保存）。

### 案C: memberstack or Memberful（外部SaaS）

JSを1行埋め込むだけで会員機能が完成する外部SaaS。CSSブラー解除・ゲーティングをSaaS側が管理。GitHub Pagesの構成を変えない。Stripe連携は内蔵。

- メリット: 実装ほぼゼロ。認証UI・メール送信・解約フローがすべて込み。個人開発向けに最速。
- デメリット: 月額固定費が高い（memberstackは最安$29/月≒4,500円。Memberfulは$25〜）。収益500円×数十人規模では赤字リスク。
- スポット100円: Memberfulの「one-time purchase」で実装可。memberstackはワンタイム購入サポートが弱い。

### 案D: Stripe + Vercel Edge Functions（Vercelへ移行）

GitHub PagesからVercelに移行。VercelはEdge FunctionsでStripe Webhookを受けられ、JWTをCookieで発行。GitHub Actions→Vercel CIに切り替え。

- メリット: VercelはJamstack標準。Edge FunctionsはCFWより高機能。Stripe連携サンプルが豊富。
- デメリット: GitHub Pages→Vercel DNS移行が必要（手間数時間）。GitHub Actionsの crawl.yml 再設定が必要。無料枠を超えると$20/月。
- スポット100円: Stripe Checkout（one-time）で実装可。

---

## 表2: 「ブラー解除」クライアント側実装手法

| 手法 | セキュリティ | UX | 実装難度 |
|------|------------|-----|---------|
| **JWTをlocalStorageに保持しJSでblur解除** | 低（JSを無効化すれば見える。本格課金には不向き） | 高（ページ遷移なし） | 低 |
| **購読確認APIを叩いてDOMを差し替え** | 中（APIが正規のトークンを検証する必要あり） | 中（APIレイテンシ分遅延） | 中 |
| **有料コンテンツを別ドメインAPIから取得し埋め込み** | 高（コンテンツをHTMLに含まない） | 中（fetch後に表示） | 高 |
| **iframe（別origin・要認証）で有料コンテンツ配信** | 高（CORSで保護） | 低（iframeはSEO・モバイル不利） | 高 |

**チラ見せ方式（1件無料+CSSブラー）の場合、セキュリティは「低」で十分**。  
理由: 2〜5件目の内容はCSSを外せば見えるが、技術的に破れる人は月額500円を払う見込み客ではなく、かつブラーを外してもデータ解釈コストが高い。釣果予測のビジネス価値はコンテンツ内容より「自分で見る手間を省くこと」にあるため、過剰な保護は実装コストに見合わない。

---

## 表3: 決定が必要な項目チェックリスト

| 項目 | 選択肢 | 優先度 |
|------|--------|--------|
| 決済プロバイダ | Stripe（事実上の一択。国内審査不要・100円対応） | **最優先** |
| 認証方式 | Magic Link（メアドのみ）/ Google OAuth / メアド+PW | **最優先** |
| 有料コンテンツの配信場所 | GitHub Pages継続（案A/C）/ Firebase Hosting（案B）/ Vercel（案D） | **最優先** |
| スポット100円の単位 | 1日分全魚種 / 1魚種分7日 / 1魚種×1日 | 優先 |
| 無料トライアル | なし（即課金） / 7日間無料 / 1件永久無料（現行チラ見せ） | 優先 |
| 課金後のページ配信方法 | JWT+JSブラー解除 / API取得+DOM差し替え | 優先 |
| 解約フロー | Stripe Customer Portal（自動）/ メール申請 | 普通 |
| メール配信（課金確認・決済失敗通知） | Stripe内蔵メール / SendGrid（無料100通/日） | 普通 |

---

## 所見（推奨案と理由）

**推奨: 案A（Stripe + Cloudflare Workers + Firebase Auth）**。  
GitHub Pagesと既存crawl.ymlを維持したままエッジ関数を「薄い認証レイヤー」として追加できる。月額固定費はほぼゼロで加入者数が少い初期段階のリスクが最小。Magic Linkにすれば認証UIの実装量も削減できる。SaaSのmemberstackは月固定費が収益を超えるリスクが高い。
