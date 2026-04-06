# 08_GitHub運用 — Actions無料枠分析・運用設計

> **変更ガバナンス**: catches_raw.json / data/*.csv のフィールド変更はオーナー最終承認 + 関連MD責任者了解が必須。

## 現在のジョブ構成（4ジョブ）

```yaml
crawl:           cron '30 7 * * *'    # 毎日16:30 JST（釣果+気象）
                 cron '0 7 1 * *'     # 毎月1日16:00 JST（船宿SID更新）
weather:         cron '0 21 * * *'    # 毎日06:00 JST（朝の気象データ）
weekly_insights: cron '0 8 * * 1'     # 毎週月曜17:00 JST（週次分析）
backfill:        workflow_dispatch    # 手動のみ
```

### crawl ジョブの中身（毎日）

```bash
python3 weather_fetch.py      # 気象予報取得
python3 crawler.py            # 釣果クロール+CSV+HTML生成
python3 weather_crawl.py      # 気象実績データ取得
# + 月1日: discover_ships.py / discover_gyo.py
```

### weather ジョブ（毎日朝）

```bash
python3 weather_crawl.py      # 朝の気象データ取得
```

### weekly_insights ジョブ（月曜）

```bash
python3 weather_forecast.py
python3 insights/season_analysis.py
python3 insights/season_detail.py
python3 insights/area_analysis.py
python3 insights/ship_peaks.py
python3 insights/weekly_analysis.py
python3 insights/weekly_wx_score.py
python3 insights/cancel_threshold.py
python3 insights/risk_predict.py
```

---

## 現在の月間 Actions 使用量（推定）

| ジョブ | 頻度 | 1回あたり | 月間 |
|-------|------|---------|------|
| crawl（釣果+気象） | 毎日 | 15〜20分 | 450〜600分 |
| weather（朝気象） | 毎日 | 3〜5分 | 90〜150分 |
| weekly_insights | 週1回 | 15〜30分 | 60〜120分 |
| discover_ships（月1日） | 月1回 | 5〜10分 | 5〜10分 |
| **合計** | | | **605〜880分/月** |

**無料枠 2,000分の 30〜44% を既に使用中。**

---

## 自社HPクロール追加後の見積もり

| 追加項目 | 1回あたり | 月間 |
|---------|---------|------|
| 75船宿HP取得（0.8秒 x 平均2ページ） | 約2〜3分 | 60〜90分 |
| HTMLパース + マージ | 約30秒 | 15分 |
| ship/*.html 生成（75ページ） | 約1分 | 30分 |
| forecast_area/*.html 生成 | 約10秒 | 5分 |
| **追加合計** | **約4分** | **約110〜140分** |

---

## 合計見積もり

| | 既存 | 追加 | 合計 | 枠比率 |
|---|------|------|------|--------|
| 月間使用量 | 605〜880分 | 110〜140分 | **715〜1,020分** | **36〜51%** |

**余裕あり。** ただし weekly_insights が重い週（全魚種で30分超え）だと50%に近づく。

---

## crawl.yml 変更案

```yaml
# 既存のステップ（変更なし）
- name: Crawl fishing-v.jp
  run: python3 crawler.py

# 追加のステップ（既存の後に追加）
- name: Crawl ship websites directly
  run: python3 direct_crawler.py
  timeout-minutes: 10
  continue-on-error: true

# 既存の後続ステップ（CSV生成・HTML生成・デプロイ等）はそのまま
```

ポイント:
- `continue-on-error: true` — direct_crawler.py が失敗しても既存のデプロイは続行
- `timeout-minutes: 10` — ハングアップ防止
- 既存ステップの順序・内容は一切変更しない

---

## rawjson → CSV の流れ

**原則: catches_raw.json と data/*.csv の既存パイプラインは一切変更しない。**

```
【現在】
釣りビジョン → catches_raw.json → generate_csv_all() → data/*.csv

【追加後】
釣りビジョン ───┐
               ├→ catches_raw.json → generate_csv_all() → data/*.csv
自社HP直接 ────┘      ↑
                      │ 同じフォーマットで追加
                      │（source フィールドで識別）
```

---

## 注意事項

1. **タイムアウト**: 75船宿のHP取得で1つでもハングすると全体が止まる → timeout設定 + 個別エラーハンドリング必須
2. **リトライ**: 個別船宿の取得失敗は skip して続行。全体を止めない
3. **キャッシュ**: 同日2回実行しても同じHPを再取得しない仕組み（Last-Modified / ETag）
4. **デプロイ頻度**: 現状1日1回。自社HP追加しても1日1回のまま
5. **リポジトリサイズ**: catches_raw.json が肥大化する → 定期的に古いデータを data/*.csv に移行してJSON をトリム
6. **ブランチ戦略**: 自社HPパーサーの開発は feature ブランチで。main への直pushは避ける

---

## GitHub視点チェックリスト

- [ ] 月間実行時間が2,000分以内に収まるか
- [ ] 個別船宿の取得失敗が全体を止めないか
- [ ] catches_raw.json のサイズ増加が .git の肥大化を引き起こさないか
- [ ] secrets（API鍵が必要なら）は GitHub Secrets に格納されているか
- [ ] workflow の permissions は最小限か
- [ ] デプロイ後の GitHub Pages のビルド時間（静的HTMLが500ページ超え → ビルド時間増加の確認）
