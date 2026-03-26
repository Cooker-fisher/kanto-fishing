# 釣果予測分析パイプライン - データ収集フェーズ完了

## 完成したデータ一覧

| ファイル | 内容 | 行数 | サイズ |
|---------|------|------|--------|
| `data/YYYY-MM.csv` | 釣果データ（25ヶ月） | 34,280行 | - |
| `weather/YYYY-MM.csv` | 気象データ（96ポイント・3時間粒度） | 458,200行 | 22MB |
| `tide/YYYY-MM.csv` | 潮汐データ（4港・毎時） | - | 78KB/月 |
| `moon.csv` | 月齢・潮回り（全期間） | 726行 | - |
| `typhoon.csv` | 台風接近フラグ（全期間） | 726行 | - |
| `point_coords.json` | ポイント名→緯度経度（204エントリ・96ユニーク座標） | - | - |
| `ship_fish_point.json` | 船宿×魚種→ポイント フォールバック（69件） | - | - |

**期間**: 2024年4月〜2026年3月（約2年）

---

## データ詳細

### 釣果データ (`data/YYYY-MM.csv`)
```
ship, area, date, fish, cnt_min, cnt_max, cnt_avg,
size_min, size_max, kg_min, kg_max, is_boat,
point_place, point_place2, point_depth_min, point_depth_max
```
- ポイント解決率: **100%**（point_coords.json直接 + ship_fish_pointフォールバック）

### 気象データ (`weather/YYYY-MM.csv`)
```
point, date, hour, wave_height, wave_period, wind_speed, wind_dir, sst, weather_code
```
- ソース: Open-Meteo（Marine API + Archive API）
- 粒度: 3時間ごと JST（00/03/06/09/12/15/18/21時）
- ポイント数: 96座標（point_coords.jsonのユニーク座標）

### 潮汐データ (`tide/YYYY-MM.csv`)
```
port, date, hour, tide_cm
```
- ソース: tide736.net API
- 港: 横須賀(pc=14,hc=7) / 羽田(pc=13,hc=3) / 銚子(pc=12,hc=2) / 鹿島(pc=8,hc=4)
- 粒度: 毎時

### 月齢・潮回り (`moon.csv`)
```
date, moon_age, moon_title
```
- 計算式: 既知の新月(2000-01-06)からの朔望月サイクル
- moon_title: 大潮 / 中潮 / 小潮 / 長潮 / 若潮

### 台風接近 (`typhoon.csv`)
```
date, typhoon_flag, min_dist_km, typhoon_name
```
- ソース: 気象庁 RSMC ベストトラック (bst_all.zip)
- typhoon_flag: 関東中心(35.5N,139.7E)から500km以内で1
- 接近実績: 19日（AMPIL, PULASAN, KROSA, PEIPAH 等）

---

## 取得スクリプト

| スクリプト | 役割 | 実行時間目安 |
|-----------|------|------------|
| `weather_fetch.py` | Open-Meteoから気象データ取得 | 約5分 |
| `tide_fetch.py` | tide736.netから潮汐データ取得 | 約10分 |
| `moon.py` | 月齢計算（API不要） | 数秒 |
| `typhoon.py` | JMAベストトラック取得・解析 | 数秒 |

すべて**標準ライブラリのみ**で動作。

---

## 次のステップ

### `join_catch_weather.py`（未実装）
釣果データ × 気象データを結合して分析用CSVを生成する。

結合キー:
1. `data/YYYY-MM.csv` の `point_place` → `point_coords.json` → (lat, lon)
2. (lat, lon) + date → `weather/YYYY-MM.csv` の該当行（06:00 JST）
3. date → `moon.csv` / `typhoon.csv`
4. area → 最近傍港 → `tide/YYYY-MM.csv`

出力: `analysis/catch_weather.csv`
```
ship, area, date, fish, cnt_avg, point, lat, lon,
wave_height, wind_speed, sst, weather_code,
tide_cm, moon_age, moon_title, typhoon_flag
```

### その後
- 予測モデル構築（線形回帰 or 決定木）
- backtest.py v3 での精度検証
