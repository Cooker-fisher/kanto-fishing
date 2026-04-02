---
name: プロジェクト現状
description: funatsuri-yoso.com の実装状況と次のアクション
type: project
---

現行バージョン: crawler.py v5.20（Layer1/Layer2 データ2層設計実装）
最終更新: 2026/04/03

---

## データ収集状況（2026/04/03時点）

| ファイル | 件数 | 内容 |
|---------|------|------|
| catches_raw.json | 82,030件 | 釣果レコード（欠航なし）|
| fish_raw_list.txt | 684種 | fish_rawユニーク値一覧 |

- 対象船宿: 78船宿（茨城・千葉・東京・神奈川・静岡）
- 期間: 2023/01/01〜2026/04/03（3年分）
- 欠航レコード: **未取得**（コード修正済み・再クロール待ち）

---

## ★ 次チャットでやること（優先度順）

### 1. 欠航データの追加取得
`append_raw_json()` の修正済み（is_cancellation=Trueも保存するよう変更）。
再クロールで釣果はdedupされ、欠航レコードのみ追記される。

```bash
python crawl_history_raw.py
```

出力ログに「釣果○件＋欠航○件」と表示されるようになった。

### 2. FISH_MAP 更新
fish_raw_list.txt の684種を精査し、未登録・誤マッピングを修正。
主な追加候補: アオリイカ、カツオ、シイラ、カマス、イトヨリダイ、イシダイ、ホウボウ、キンメ（→キンメダイ）等。
複合種（アジ・サバ等）はfish_rawそのままで保持し、Layer2 CSV化時に分割する設計。

### 3. export_csv_from_raw() 実行 → Layer2 CSV生成
FISH_MAP更新後に実行:
```bash
python -c "import crawler; crawler.export_csv_from_raw('catches_raw.json', 'data')"
```

---

## 実装済み機能（v5.20・2026/04/03）

### Layer 1: catches_raw.json
- ✅ `to_raw_record()`: catchレコード → raw形式変換（is_cancellation/reason_text追加済み）
- ✅ `append_raw_json()`: 欠航レコードも保存（dedup: 釣果=ship/date/trip_no/fish_raw、欠航=ship/date/CANCEL）
- ✅ `crawl_history_raw.py`: 全船宿×全ページ遡りクロール（CUTOFF=2023/01/01、MAX_PAGE=300）
- ✅ `discover_ships.py`: 静岡（22）追加 → 78船宿に拡張

### Layer 2: data/YYYY-MM.csv（未実行）
- ✅ `export_csv_from_raw()`: catches_raw.json → CSV変換関数（実装済み・未検証）
- ✅ `TSURI_MONO_MAP`: 釣り物正規化マップ
- ✅ `_extract_tsuri_mono()`: 5優先度で釣り物を決定
- ✅ `_classify_main_sub()`: メイン/サブ判定
- ✅ `_split_point_places_depth()`: ポイント場所・水深分離

### 有料予測ページ群（forecast/）
- ✅ forecast/index.html, YYYY-MM-DD.html, YYYY-WXX.html, area/エリア名.html
- ✅ 無料/有料境界（1件目完全・2〜5件目blur）
- ✅ 価格: 月額500円 / スポット100円

---

## 確定した設計方針（変更不可）
- 価格: **月額500円 / スポット100円**
- 無料=事実（今日の釣果）、有料=分析+予測
- 分析テキスト: 閾値・係数は非公開（定性表現のみ）
- LLMによるテキスト生成は採用しない

---

## 後回し・未実装
- [ ] 欠航データ再クロール（crawl_history_raw.py 再実行）
- [ ] FISH_MAP更新（684種精査）
- [ ] export_csv_from_raw() 検証
- [ ] suion_raw / suishoku_raw の choka_box からの個別抽出
- [ ] turimono_list（ships.json拡張・discover_ships.py更新）
- [ ] 決済連携（Stripe等）
- [ ] AdSense審査結果待ち（2026/03/21申請済み）
- [ ] X自動投稿（アカウントロック解除待ち）
- [ ] crawl.ymlのNode.js 20→24アップグレード
