# water_color_analysis v2 結果レポート

## データ概要
- 分析期間: 2023-04-04 〜 2026-05-12
- trip_records 総数: 82,331 件
- water_color 有効報告 trip 数: 25,206 件
- daily_turbidity ペア数: 11,901

## Sanity Check (turbid_rate 分布)
  turbid_rate P50 = 0.0  P75 = 0.0
  (0 = 濁り報告なし, 1 = 全便が濁り報告)
  ゾーン別 baseline (P25):
    ibaraki: 0.000
    inner_boso: 0.000
    izu: 0.000
    outer_boso: 0.000
    sagami_bay: 0.000
    tokyo_bay: 0.000

## 雨イベント数 (rain 系)
  no (<5mm):    59,091
  lo (5-20mm):  5,622
  mid (20-50mm):447
  hi (50mm+):   11

## 濁りイベント数 (turbid_actual 系)
  turbid_actual: 1,048 イベント
  ゾーン別:
    ibaraki: 71
    inner_boso: 84
    izu: 98
    outer_boso: 233
    sagami_bay: 244
    tokyo_bay: 318

## 改善4: 連続雨除外件数
  除外総数: 223 件 / 除外率: 32.7%
  ⚠ 除外率 20% 超 → 梅雨・台風シーズンの seasonal bias に注意
  月別内訳 (上位 10):
    2023-06: 60 件
    2024-06: 46 件
    2023-09: 32 件
    2024-07: 14 件
    2024-09: 13 件
    2025-07: 9 件
    2024-08: 8 件
    2023-08: 8 件
    2026-04: 8 件
    2024-05: 8 件

## 雨後の濁りダイナミクス (recovery_by_bucket.csv より)
(改善5: n<10 の offset は N/A 扱い)
(recovery_offset_both が主指標: p50 AND p75 両側が baseline+0.2 を下回った最初の日)
(recovery_offset_p50 は参考値: p50 のみ基準)
両側基準は p50 だけでなく上位25%（p75）も収束したことを要求するため、
「半数以上がまだ濁り継続」な状態を回復扱いにしない、より実態に近い回復日数を示す。

  [rain] zone=ibaraki bucket=lo: n_events=449, peak=D+1, peak_rate=0.0, recovery_both(主)=1, recovery_p50(参考)=1
  [rain] zone=inner_boso bucket=lo: n_events=508, peak=D+1, peak_rate=0.0, recovery_both(主)=1, recovery_p50(参考)=1
  [rain] zone=izu bucket=lo: n_events=1127, peak=D+1, peak_rate=0.0, recovery_both(主)=3, recovery_p50(参考)=1
  [rain] zone=outer_boso bucket=lo: n_events=993, peak=D+1, peak_rate=0.0, recovery_both(主)=10, recovery_p50(参考)=1
  [rain] zone=sagami_bay bucket=lo: n_events=1273, peak=D+1, peak_rate=0.0, recovery_both(主)=1, recovery_p50(参考)=1
  [rain] zone=tokyo_bay bucket=lo: n_events=1272, peak=D+1, peak_rate=0.0, recovery_both(主)=1, recovery_p50(参考)=1
  [rain] zone=ibaraki bucket=mid: n_events=24, peak=D+N/A, peak_rate=N/A, recovery_both(主)=>10, recovery_p50(参考)=>10
  [rain] zone=inner_boso bucket=mid: n_events=33, peak=D+2, peak_rate=0.0, recovery_both(主)=8, recovery_p50(参考)=2
  [rain] zone=izu bucket=mid: n_events=130, peak=D+3, peak_rate=1.0, recovery_both(主)=4, recovery_p50(参考)=4
  [rain] zone=outer_boso bucket=mid: n_events=62, peak=D+N/A, peak_rate=N/A, recovery_both(主)=>10, recovery_p50(参考)=>10
  [rain] zone=sagami_bay bucket=mid: n_events=116, peak=D+1, peak_rate=0.0, recovery_both(主)=3, recovery_p50(参考)=1
  [rain] zone=tokyo_bay bucket=mid: n_events=82, peak=D+1, peak_rate=0.0, recovery_both(主)=>10, recovery_p50(参考)=1
  [rain] zone=ibaraki bucket=hi: n_events=6, peak=D+N/A, peak_rate=N/A, recovery_both(主)=>10, recovery_p50(参考)=>10
  [rain] zone=izu bucket=hi: n_events=2, peak=D+N/A, peak_rate=N/A, recovery_both(主)=>10, recovery_p50(参考)=>10
  [rain] zone=tokyo_bay bucket=hi: n_events=3, peak=D+N/A, peak_rate=N/A, recovery_both(主)=>10, recovery_p50(参考)=>10
  [turbid_actual] zone=ibaraki bucket=turbid: n_events=71, peak=D+1, peak_rate=0.0, recovery_both(主)=2, recovery_p50(参考)=1
  [turbid_actual] zone=inner_boso bucket=turbid: n_events=84, peak=D+1, peak_rate=1.0, recovery_both(主)=>10, recovery_p50(参考)=3
  [turbid_actual] zone=izu bucket=turbid: n_events=98, peak=D+1, peak_rate=1.0, recovery_both(主)=3, recovery_p50(参考)=2
  [turbid_actual] zone=outer_boso bucket=turbid: n_events=233, peak=D+2, peak_rate=0.4583, recovery_both(主)=>10, recovery_p50(参考)=3
  [turbid_actual] zone=sagami_bay bucket=turbid: n_events=244, peak=D+1, peak_rate=1.0, recovery_both(主)=>10, recovery_p50(参考)=2
  [turbid_actual] zone=tokyo_bay bucket=turbid: n_events=318, peak=D+1, peak_rate=0.25, recovery_both(主)=>10, recovery_p50(参考)=2

## 魚種別濁り嗜好 (月内比較ベース)
採用条件: n_months >= 3, n_turbid_days >= 5, n_clear_days >= 5

### 濁りで釣果が増える魚 (ratio_p50 >= 1.1)
  + アオリイカ: ratio=1.667 (n_months=3, n_turbid_trips=84)
  + マダイ: ratio=1.300 (n_months=13, n_turbid_trips=278)
  + マルイカ: ratio=1.242 (n_months=10, n_turbid_trips=130)

### 濁りで釣果が減る魚 (ratio_p50 <= 0.9)
  - マダコ: ratio=0.669 (n_months=3, n_turbid_trips=159)
  - アマダイ: ratio=0.873 (n_months=10, n_turbid_trips=254)

### 平気な魚 (0.9 <= ratio_p50 < 1.1)
  = アジ: ratio=1.061 (n_months=22)
  = カワハギ: ratio=0.954 (n_months=10)
  = ヒラメ: ratio=1.069 (n_months=10)
  = シロギス: ratio=1.035 (n_months=7)

## 注意事項

### M-4: 平年 leakage（月内比較は leakage を大幅軽減）
月内比較では同月内の turbid 日と clear 日を比較するため、
旬別平年ベースラインの leakage 問題は大幅に軽減されている。
ただし同月内の季節変化（前半/後半）や天候系統の偏りは残存する。

### 小サンプル警告
- hi (50mm+) バケット: n=11 イベントで统計的推論は不可能
- n_months < 3 の魚種は fish_turbidity_summary から除外済み
- recovery_offset_both (主指標) / recovery_offset_p50 (参考値): n<10 の cell は N/A

## X 投稿用引用文案

【案1: ゲリラ豪雨後の濁り（turbid_actual 基準）】
関東船釣り、実際に濁りが発生したあと（tokyo_bay / n=318イベント）は翌日以降も継続。全便の濁り収束まで約>10日（p50単独では2日）。3年分・船宿水色報告25,206件から。#船釣り #ゲリラ豪雨 #関東

【案2: 濁りが得意な魚】
濁り潮でも釣れる魚は？3年間の船宿水色報告で分析。濁り時の月内比較: アオリイカ +66%, マダイ +30%, マルイカ +24%。大雨の翌日こそチャンスかも。#船釣り #濁り潮 #関東

【案3: 濁りが苦手な魚】
ゲリラ豪雨後は要注意の魚も。濁り時の月内比較で釣果が落ちやすい: マダコ -33%, アマダイ -12%。水色が戻るまで待つのが正解かも。#船釣り #関東釣果 #濁り潮

## 信頼度自己評価
**Mid**
mid イベント 447 件は一定の数だが、hi=11 件が少ない。月内比較ベースの魚種嗜好は参考水準。

### データの限界
- water_color は船宿が自主的に報告する定性情報。報告率 30.6%（25,206 / 82,331 trip）
- 報告バイアス: 濁りが目立つときに記載される可能性（過剰評価方向）
- turbid_actual イベントは小さな連続イベントが除外されるため、長期濁り期間は過小評価
- hi (50mm+) バケットは 11 件のみで統計的推論は不可能。X 投稿では使わないこと

---
生成日時: 2026-05-13 18:14