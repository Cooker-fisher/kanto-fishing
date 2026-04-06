# direct-crawl/ — 自社HP直接クロール（脱・釣りビジョン依存）

## 問題

**関東最大市場の金沢八景エリアが catches_raw.json に1船宿（野毛屋釣船店）しかない。**
忠彦丸・一之瀬丸・荒川屋・太田屋・弁天屋は全件ゼロ。

釣りビジョン経由では:
- 関東主要船宿の半数がカバーされていない
- 水温データは全件 null
- 情報量が自社HP の 1/10 の船宿もある（山本釣船店: 情報ロス90%）

## 目標

関東主要船宿の自社HPから直接釣果データを取得し、catches_raw.json に統合する。

## 変更ガバナンス

**catches_raw.json / data/*.csv のフィールド変更は以下の全条件を満たして初めて実行する：**

1. 全要件が固まっていること（06_データ定義.md で確定）
2. ホームページデザイン（redesign/）に影響がないこと
3. 分析パイプライン（PIPELINE.md）に影響がないこと
4. **オーナーの最終承認**を得ること
5. **関連MDの責任者の了解**を得ること（redesign/00_責任者、PIPELINE.md 管理者）

**このルールに例外はない。** フィールド追加・型変更・既存データの書き換えは全てこのプロセスを経る。

## redesign/ との関係

| フォルダ | 役割 |
|---------|------|
| redesign/ | UIデザイン・ページ構造・無料有料設計 |
| **direct-crawl/** | **データソース戦略・自社HPパーサー・カバレッジ改善** |

橋渡し: direct-crawl で取得したデータは redesign のモックアップを実データ化する基盤。

### 相互参照

**direct-crawl/ → redesign/**
- `redesign/06_釣り人訪問者.md` — ペルソナ定義（どのユーザーにどのデータが必要か）
- `redesign/20_デザイン具体案.md` — 無料/有料の線引きルール

**redesign/ → direct-crawl/**
- `direct-crawl/02_カバレッジ分析.md` — モックアップで使う船宿名の正確性チェック
- `direct-crawl/01_船宿HP分類.md` — 取得可能な情報フィールド（有料コンテンツ設計の根拠）

## PIPELINE.md との連携

**姿勢: 「NGではなく、こう拡張すべき」**

PIPELINE.md の制約に従うだけでなく、新データによってパイプラインをどう進化させるかの+α提案を行う。

例:
- 船長報告の水温 vs API水温の差分分析が可能に
- source フィールドで品質別分析が可能に
- タックル情報が有料コンテンツの根拠データに

## catches_raw.json の既存フィールド（参照用）

```json
{
  "ship": "船宿名",
  "area": "港名",
  "date": "YYYY/MM/DD",
  "trip_no": 1,
  "is_cancellation": false,
  "reason_text": "",
  "fish_raw": "魚種名",
  "count_raw": "X～Y 匹",
  "size_raw": "X～Y cm",
  "weight_raw": "",
  "tokki_raw": "",
  "point_raw": "ポイント名",
  "kanso_raw": "感想テキスト",
  "suion_raw": null,
  "suishoku_raw": null
}
```

**suion_raw / suishoku_raw は全件 null**。自社HP直接取得なら値が入る。

## 自社HPで追加取得可能なフィールド（候補）

```json
{
  "suion_raw": "16.0",
  "suishoku_raw": "薄濁",
  "source": "direct",
  "weather_raw": "曇りのち晴れ",
  "tide_type_raw": "大潮",
  "tackle_raw": "ハリス1.5号 チヌ2号",
  "top_catch_raw": "7匹",
  "boat_count": 2,
  "photo_urls": [],
  "fetched_at": "2026-04-05T16:30:00"
}
```

**これらのフィールド追加は変更ガバナンスの承認プロセスを経てから実施する。**

## ドキュメント一覧

| ファイル | 内容 |
|---------|------|
| 00_調査結果.md | 5船宿の分析結果 |
| 01_船宿HP分類.md | 5タイプの分類・パーサー方針 |
| 02_カバレッジ分析.md | エリア別穴・ポテンシャル層 |
| 03_優先順位.md | Phase 1-4 の対応計画 |
| 04_法的リスク.md | スクレイピングの法的整理 |
| 05_実装方針.md | パーサー設計・crawler.py統合 |
| 06_データ定義.md | 既存フィールド互換+新規フィールド |
| 07_パイプライン影響分析.md | PIPELINE.md拡張版（+α思考） |
| 08_GitHub運用.md | Actions無料枠・実行時間管理 |
| 09_対象船宿リスト.md | 全船宿の対応状況＋開発トラッキング |
| research/{船宿名}.md | 個別HP調査メモ |
