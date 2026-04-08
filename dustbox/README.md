# dustbox/ — 退避ファイル置き場

## 役割

削除ではなく「救済可能な状態で退避」するフォルダ。
参照ゼロ・不要と判断されたファイルを保管する。

> **本番コードからは一切参照されていない。**
> 復元が必要になった場合は git mv で元の場所に戻す。

---

## 収容ファイル一覧

| ファイル | 退避理由 | 退避日 |
|---------|---------|--------|
| backfill_depth.py | 水深バックフィル一時スクリプト。crawl.yml から削除済み | 2026/04/08 |
| backfill_precipitation.py | 降水バックフィル一時スクリプト | 2026/04/08 |
| build_point_coords.py | ポイント座標ビルド一時スクリプト | 2026/04/08 |
| check_depth_ab.py | 深度チェック一時スクリプト | 2026/04/08 |
| crawl_cancellations.py | 欠航クロール一時スクリプト | 2026/04/08 |
| crawl_history_raw.py | 履歴クロール一時スクリプト | 2026/04/08 |
| history_crawl.py | 履歴クロール一時スクリプト | 2026/04/08 |
| master_dataset.csv | V1 分析用結合データ（5.8MB）。analysis/V1/results/ に結果あり | 2026/04/08 |
| migrate_csv.py | CSV マイグレーション一時スクリプト | 2026/04/08 |
| moon.py | 旧月齢計算スクリプト（build_tide_moon.py に置換） | 2026/04/08 |
| point_normalize_map.json | build_point_coords.py の副産物。crawler.py 参照ゼロ | 2026/04/08 |
| recrawl_ships.py | 船宿再クロール一時スクリプト | 2026/04/08 |
| typhoon.py | 旧台風処理スクリプト（build_typhoon.py に置換） | 2026/04/08 |
| crawl.yml | ルートに残っていた旧ワークフロー定義（.github/workflows/crawl.yml が正） | 2026/04/08 |
| fish_raw_list.txt | 魚種名一覧デバッグ用一時ファイル。参照ゼロ | 2026/04/08 |
| turimono_list_raw.txt | 魚種×件数集計デバッグ用一時ファイル。参照ゼロ | 2026/04/08 |

---

## 復元方法

```bash
git mv dustbox/ファイル名 元の場所/
git commit -m "restore: ファイル名 を復元"
```
