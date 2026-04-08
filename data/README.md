# data/ — B層出力: 正規化済み釣果 CSV

## 役割

crawler.py (B層) が catches_raw.json × normalize/ ルールを適用して生成する
月別正規化済み釣果 CSV の蓄積場所。

---

## バージョン管理

**`config.json` の `active_version` に連動してバージョン管理される。**

```
data/
└── V2/          ← 現行（config.json: "active_version": "V2"）
    ├── 2023-04.csv
    ├── 2023-05.csv
    ├── ...
    └── cancellations.csv
```

| バージョン | 期間 | スキーマ |
|-----------|------|---------|
| V2（現行） | 2023-04〜 | 現行列定義（ship/area/date/tsuri_mono/cnt/size/kg/lat/lon 等） |

---

## CSV スキーマ（V2）

PIPELINE.md の「CSV列一覧（B1）」を参照。主要列：

| 列名 | 内容 |
|------|------|
| ship / area / date | 船宿・港・釣行日 |
| tsuri_mono | 正規化魚種名（58魚種） |
| main_sub | メイン/サブ/不明 |
| cnt_min/max/avg | 釣果数 |
| size_min/max | サイズ(cm) |
| kg_min/max | 重量(kg) |
| lat / lon | ポイント座標（3段階フォールバック） |
| point_place1 | ポイント名 |

---

## バージョンアップ手順（V2 → V3）

CSV 列を追加する場合（船長名・トップ成績等）：

```
1. config.json の active_version を "V3" に変更
2. crawler.py の CSV 出力関数に新列を追加
3. python crawler.py（--regen オプション等）で全期間再生成
   → data/V3/YYYY-MM.csv が自動生成される
4. analysis/V3/methods/ を作成（_paths.py をコピー）
5. V2 の CSV は data/V2/ に残り、V1 比較に使える
```

> **catches_raw.json はバージョン管理しない**（生データは変わらない）。
> バージョンアップ時は catches_raw.json から再生成するだけ。

---

## 利用元

| スクリプト | 参照方法 |
|-----------|---------|
| analysis/V2/methods/*.py | `_paths.py` の `DATA_DIR`（config.json 連動で自動解決） |
| crawler.py (E層: HTML生成) | `_DATA_DIR`（同上） |

---

## 前後工程との関係

```
normalize/ ← crawler.py → data/V2/YYYY-MM.csv
                                ↓
              analysis/V2/methods/（C層: 相関分析）
              crawler.py (E層: HTML生成)
```
