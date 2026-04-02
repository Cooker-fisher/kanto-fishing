現行バージョン: crawler.py v5.20（Layer1/Layer2 データ2層設計実装）
最終更新: 2026/04/03

---

## ★ 次チャットでやること（優先度順）

### 1. 釣り物Map（TSURI_MONO_MAP）設計
- ships.jsonの各船宿から `turimono_list` を取得（detail.php?s=SID の `<ul class="turimono_list"><li>` 要素）
- 75船宿（除外3件を除く）の釣り物リストを収集
- TSURI_MONO_MAP を設計
- スルメイカ/ヤリイカ は船宿ごとのturimono_listで判別

### 2. export_csv_from_raw() 実行 → Layer2 CSV生成
- fish_raw はそのまま保持（正規化しない）
- tsuri_mono（釣り物）を正確に判定するのが最重要

### 3. FISH_MAP設計（分析クエリ用）
- 1と2が完成すると8割できる
- CSVが出来てから作る（書き込み時には使わない）

---

## 確定した設計方針（変更不可）

### FISH_MAP新方針（2026/04/03確定）
- **分析クエリ専用**（CSV書き込み時には使わない）
- `fish_raw IN FISH_MAP["アジ"] AND main_sub="メイン"` で分析フィルタ
- **統合しない**: キメジ/キハダマグロ、トラフグ/フグ、イナダ/ワラサ/ブリ は別エントリ
- **不明ゼロ**: fish_rawをそのままCSVに書く
- **キメジは独立種**（相模湾・駿河湾の若魚、キハダマグロと別）

### ships.json フィールド（2026/04/03更新）
- `exclude: true` → 利一丸・岩崎レンタルボート・海上つり堀まるや（3件）
- `boat_only: true` → 青木丸（1件）
- 有効船宿: 75件

### データ収集状況（2026/04/03時点）
- catches_raw.json: 84,047件（有効75,432件）
- fish_raw ユニーク種: 501種（除外・欠航除く）
- 期間: 2023/01/01〜2026/04/03

### 価格・マネタイズ
- **月額500円 / スポット100円**
- 無料=事実、有料=分析+予測

---

## 後回し・未実装
- [ ] turimono_list 収集 → ships.json に追記
- [ ] TSURI_MONO_MAP 設計・実装
- [ ] export_csv_from_raw() 検証
- [ ] FISH_MAP（分析クエリ用、CSV完成後）
- [ ] 欠航データ再クロール（crawl_cancellations.py）
- [ ] 決済連携（Stripe等）
- [ ] AdSense審査結果待ち（2026/03/21申請済み）
- [ ] X自動投稿（アカウントロック解除待ち）
- [ ] crawl.ymlのNode.js 20→24アップグレード
