# 釣果データ分析 継続ガイド
> 作成: 2026-03-27
> 目的: 次のチャットでもすぐに分析を再開できるようにする

---

## データの場所

```
C:/Users/newsh/Desktop/kanto-fishing/analysis/
├── master_dataset.csv     # メインデータ（約34,000件）
├── analysis_results.md    # 分析結果まとめ
├── discovery_process.md   # 発見のプロセス（記事ネタ）
└── analysis_guide.md      # このファイル
```

---

## master_dataset.csv のカラム一覧

| カラム名 | 内容 | 備考 |
|---------|------|------|
| date | 釣行日 | YYYY/MM/DD |
| ship | 船宿名 | |
| area | 港名 | 金沢八景・松輪間口港など |
| fish | 魚種名 | |
| cnt_min / cnt_max / cnt_avg | 釣果数（最小/最大/平均） | |
| size_min / size_max | サイズ（cm） | |
| kg_min / kg_max | 重量（kg） | |
| is_boat | 船中合計フラグ | 1=船中合計（集計除外） |
| point_place | 釣り場ポイント | |
| wave_height | 波高（m） | |
| wave_period | 波周期（秒） | |
| swell_height | うねり（m） | |
| wind_speed | 風速（m/s） | |
| wind_dir | 風向 | |
| temp | 気温（℃） | |
| sea_surface_temp | 海面水温（℃） | |
| tide_type | 潮汐種別 | 大潮/中潮/小潮/長潮/若潮 |
| tide_range | 潮位差（cm） | 連続値・36〜216cm |
| moon_age | 月齢 | |
| flood1 / flood1_cm | 満潮時刻 / 満潮潮位（cm） | |
| ebb1 / ebb1_cm | 干潮時刻 / 干潮潮位（cm） | |

---

## データの注意点（重要）

### is_boat フラグ
- `is_boat == '1'` は船中合計。釣果分析には必ず除外する
- `r.get('is_boat') == '1': continue` を条件に入れること

### 魚種別 異常値閾値（船中合計混入対策）
```python
BOAT_THRESHOLD = {
    'アジ': 200, 'サバ': 200, 'イワシ': 300,
    'タチウオ': 100, 'マダイ': 50, 'ヒラメ': 20,
    'イサキ': 150, 'スルメイカ': 150, 'ヤリイカ': 100,
    'マルイカ': 200, 'アオリイカ': 50,
}
```

### 潮汐種別の注意
- 小潮データが統計的に有意に少ない（z=-3.55、p=0.04%）
- データ収集タイミングのバイアスが原因と推定
- 潮汐種別による釣果比較は信頼性が低い

### 波高の注意
- 波高と釣果の全体相関はエリア特性の擬似相関
- 分析する場合は必ずエリアを固定すること

---

## 分析の基本パターン（コードテンプレート）

### 基本ロード
```python
import csv, math
from collections import defaultdict

path = "C:/Users/newsh/Desktop/kanto-fishing/analysis/master_dataset.csv"

rows = []
with open(path, encoding='utf-8') as f:
    for r in csv.DictReader(f):
        if r.get('is_boat') == '1': continue  # 船中合計除外
        try:
            cnt  = float(r['cnt_max'])  if r.get('cnt_max')  else None
            sst  = float(r['sea_surface_temp']) if r.get('sea_surface_temp') else None
            date = r.get('date','')
            month= int(date[5:7]) if date and len(date)>=7 else None
        except: continue
        rows.append({'cnt':cnt, 'sst':sst, 'month':month,
                     'fish':r.get('fish',''), 'area':r.get('area','')})
```

### ピアソン相関係数
```python
def pearson(xs, ys):
    pairs = [(x,y) for x,y in zip(xs,ys) if x is not None and y is not None]
    n = len(pairs)
    if n < 15: return None, n
    x2,y2 = [p[0] for p in pairs],[p[1] for p in pairs]
    mx,my = sum(x2)/n, sum(y2)/n
    num = sum((x-mx)*(y-my) for x,y in pairs)
    dx = math.sqrt(sum((x-mx)**2 for x in x2))
    dy = math.sqrt(sum((y-my)**2 for y in y2))
    return (round(num/(dx*dy),3) if dx and dy else 0), n
```

### 変動係数（CV）
```python
def cv(lst):
    if len(lst) < 2: return 0
    mean = sum(lst)/len(lst)
    std  = math.sqrt(sum((x-mean)**2 for x in lst)/len(lst))
    return round(std/mean*100, 1) if mean else 0
```

---

## 確認済みの分析結果（再分析不要）

### 要因別説明力ランキング
1. **エリア** ← 最強（同魚種でも最大10倍差）
2. **月・季節** ← 2番目（CV最大61%）
3. **水温SST** ← 魚種固定で有効（閾値あり）
4. **気温** ← 水温と高相関（r=0.879）。独立した情報は少ない
5. **潮位差** ← アジのみ弱い正相関（r=+0.17）
6. **波高** ← 擬似相関（エリア固定でゼロ）
7. **潮汐種別** ← データバイアスあり・信頼不可

### 水温閾値（確認済み）
- アオリイカ: 20℃↑で急増
- マルイカ: 15℃↑で急増
- ヒラメ: 16℃↑で増加
- スルメイカ: 28℃↑で激減
- ヤリイカ: 冷水（〜13℃）ほど多
- タチウオ: 二山構造（18〜20℃が最低、26〜28℃が最高）

---

## 未分析・次にやりたいこと

### データ分析
- [ ] 年次トレンド（年ごとに釣果は変化しているか）
- [ ] エリア×月×水温の3次元分析
- [ ] 釣果の前日比・週次変化（釣況の急変を捉える）
- [ ] 船宿ごとのクセ（同エリアでも船宿差はあるか）
- [ ] 気象データの「変化量」と釣果（急冷・急暖で釣果が変わるか）

### データ整備
- [ ] 気象データの毎日自動収集（水温・気温・波高）→ crawler.pyに組み込む
- [ ] 潮汐データを日付から正確に再計算（APIから取得してバイアス解消）
- [ ] 釣り場ポイント（point_place）の整備・活用

### サイト実装
- [ ] 「水温◯℃になったから○○が釣れ始める」コメントの自動生成
- [ ] 水温閾値トリガーによる魚種別アラート

---

## 気象データ 毎日収集について（TODO）

### 取得すべきデータ
- 海面水温（SST）: Open-Meteo Marine API
- 波高・波周期: Open-Meteo Marine API
- 気温・風速: Open-Meteo Forecast API
- 潮汐: 海保潮汐API または気象庁

### 取得エリアの代表座標（主要港）
```python
AREA_COORDS = {
    '金沢八景':   (35.33, 139.62),
    '松輪間口港': (35.15, 139.62),
    '平塚港':     (35.32, 139.35),
    '日立久慈港': (36.55, 140.65),
    '飯岡港':     (35.72, 140.77),
    '浦安':       (35.66, 139.90),
}
```

### 方針
- crawler.py実行時に合わせて毎日取得・蓄積
- analysis/weather_daily.csv に追記形式で保存
- 将来的にmaster_dataset.csvに結合して分析精度を上げる
