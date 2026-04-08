# design/ — ホームページデザイン バージョン管理

## バージョン一覧

| バージョン | 状態 | 内容 |
|-----------|------|------|
| V1 | アーカイブ（現行デプロイ中） | 初期デザイン。style.css / main.js の参照用コピー |
| V2 | 設計中 | リデザイン。無料/有料ページ分離・SEO強化 |

---

## フォルダ構成

```
design/
├── README.md      ← このファイル
├── V1/            ← 現行デザイン（参照用アーカイブ）
│   ├── style.css  ← V1 CSS（ルートの style.css のコピー）
│   └── main.js   ← V1 JS（ルートの main.js のコピー）
└── V2/            ← リデザイン作業フォルダ
    ├── README.md  ← ロールシステム・ワークフロー説明
    ├── 00〜06_*.md  ← ロール定義
    ├── 10〜20_*.md  ← 設計ドキュメント・具体案
    ├── 90_決定ログ.md
    ├── mockup-*.html  ← モックアップ
    └── research/  ← 競合調査・リサーチ成果物
```

---

## デプロイ運用ルール

- **ルートの `style.css` / `main.js`** = 実際にデプロイされるファイル（GitHub Pages）
- `design/V1/` = V1 デザインの参照用アーカイブ（デプロイには使わない）
- `design/V2/` = 設計・モックアップ作業場

**V2 を本番に上げるとき:**
```
1. design/V2/ の全ファイルを完成させる
   （style.css / main.js / about.html / contact.html / privacy.html / terms.html）
2. config.json の "design_version": "V1" → "V2" に変更
3. crawler.py を実行（またはGitHub Actions の次回実行を待つ）
   → design/V2/ の全ファイルが自動的にルートへコピーされる
```

---

## V2 ロールシステム

`design/V2/README.md` を参照。セッション引き継ぎキーワード: `#redesign`
