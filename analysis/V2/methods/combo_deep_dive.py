#!/usr/bin/env python3
"""
combo_deep_dive.py — 船宿×魚種ペア 深掘り分析

[方針]
  1ペアずつ丁寧に分析し、精度向上のための知見を積み上げる。
  バックテストは「予報で取れる情報のみ」を使って評価する。

[分析内容]
  1. 基本統計（cnt_avg/min/max, size_avg, kg_avg）
  2. 旬別ベースライン（combo_decadal 引用）
  3. 因子相関（予報可能9因子 × cnt_avg/cnt_max/size_avg/kg_avg）
  4. コメント解析（kanso_raw / fish_raw）
  5. ポイント別集計（point_place1）
  6. マルチホライズン バックテスト（H=0,1,3,7,14,21,28日前の海況で予測）

[予報可能因子（バックテスト制約）]
  ○ sst_avg, temp_avg/max/min, pressure_avg/min,
    wind_speed_avg/max, wind_dir_mode,
    wave_height_avg/max, wave_period_avg/min,
    swell_height_avg/max              ← 全変数を日次集計（min/max/avg）に統一
  ○ tide_range, moon_age, tide_type   ← 天文計算で未来も確定
  × current_spd, wave_dir, swell_period ← 予報APIに含まれない

[使い方]
  python insights/combo_deep_dive.py --fish アジ --ship かめだや
  python insights/combo_deep_dive.py --fish アジ          # 全船宿

[出力]
  insights/deep_dive/{魚種}_{船宿}.txt
  insights/analysis.sqlite  → combo_deep_params テーブル
"""

import argparse, bisect, csv, json, math, os, re, sqlite3, sys, time
from collections import Counter, defaultdict
from datetime import datetime, timedelta

import sys as _sys; _sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _paths import ROOT_DIR, RESULTS_DIR, DATA_DIR, NORMALIZE_DIR, OCEAN_DIR
DB_WX         = os.path.join(OCEAN_DIR, "weather_cache.sqlite")
DB_TIDE       = os.path.join(OCEAN_DIR, "tide_moon.sqlite")
DB_TYPHOON    = os.path.join(OCEAN_DIR, "typhoon.sqlite")
DB_CMEMS      = os.path.join(OCEAN_DIR, "cmems_data.sqlite")
DB_ANA        = os.path.join(RESULTS_DIR, "analysis.sqlite")
OUT_DIR       = os.path.join(RESULTS_DIR, "deep_dive")

def _open_ana(timeout: float = 120.0):
    """analysis.sqlite を WAL モード・タイムアウト付きで開く（並列実行対応）。
    WAL モードにより複数プロセスが同時に書き込んでも SQLITE_BUSY が発生しにくくなる。
    timeout=120s: workers=4 並列実行時の書き込み競合でも確実に解消できる値。
    """
    conn = sqlite3.connect(DB_ANA, timeout=timeout)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn
OVERRIDE_FILE  = os.path.join(NORMALIZE_DIR, "ship_wx_coord_override.json")
SHIPS_FILE     = os.path.join(ROOT_DIR, "crawl", "ships.json")
OBS_FIELDS_FILE = os.path.join(NORMALIZE_DIR, "obs_fields.json")
OBS_FIELDS_COMBO_FILE = os.path.join(NORMALIZE_DIR, "obs_fields_combo.json")

HORIZONS   = [0, 1, 3, 7, 14, 21, 28]
MIN_N_COMBO = 30            # 分析最小件数（統計的に意味ある予測を立てられる下限）

# 回遊魚：レンジ予測の代わりに★（チャンス評価）を使う魚種
KAIYU_FISH = {"シイラ", "カツオ", "キハダマグロ", "ブリ", "ワラサ", "イナダ", "サワラ", "カンパチ", "ムギイカ", "泳がせ五目"}

# 回遊魚を★から匹数予測に昇格させる wMAPE 閾値（H=7 cnt_avg）
# BL-2 も下回っていること（自己回帰より優秀）が条件。
# 2026-04-19: 60→62 に緩和（ムギイカ×秀丸 H7=60.1%・r=+0.571 など強相関コンボを昇格）
KAIYU_PROMOTE_WMAPE_THR = 62.0  # 62%以下 + BL-2勝ち → 匹数予測に昇格（wMAPEは%値で保存）

# wave_clamp 閾値（モジュール変数。--wave-clamp 引数で上書き可）
# 1.5m / 2.0m / 2.5m で比較検証するための可変定数
WAVE_CLAMP_THRESHOLD: float = 2.0

# SST勾配（黒潮近接指標）の固定参照座標
# 外房沖（黒潮ライン上）と東京湾内（沿岸代表）の差分で黒潮の近接度を近似
# 正=外房が暖かい（黒潮近接・栄養塩豊富）、負=東京湾が暖かい（黒潮遠い・湾内加熱）
SST_GRAD_OFFSHORE = (35.65, 140.87)  # 外房沖（黒潮ライン上）
SST_GRAD_INSHORE  = (35.3,  139.68)  # 東京湾内（沿岸代表）

# カツオ・キハダマグロ用 沖合SLA座標
# 船籍港（沿岸）ではなく実際の釣り場（外房沖〜犬吠埼沖）の黒潮状態を使う
# lon=141.4°が cmems_daily の東限のため 141.3 を使用（34-36°N, 141-143°E 指定の上限）
SLA_PELAGIC_FISH  = {"カツオ", "キハダマグロ"}
SLA_PELAGIC_COORD = (35.5, 141.3)  # 銚子沖〜外房沖（cmems_daily 東端付近）

# ── 変数の予報有効ホライズン ────────────────────────────────────────────
# 「遅い変数」: 日々の変化が小さく、N日前の値≒当日値 → 長期予報でも有効
# 「速い変数」: 数日で激変 → 短期予報（〜7日）以外は当日値と無関係
#
# 実測例（東京湾 2024-08）:
#   SST: 27.0〜29.1℃（月次変動±1℃） → 28日前でもほぼ同じ値
#   wave: 0.16〜1.30m（台風日に急変） → 7日前は全く参考にならない
#   wind: 8.2〜44.5m/s（台風日に急変）→ 同上
#
# ∴ バックテストで H=N の海況を使うとき、速い変数は H>FAST_MAX_H で無効化

# ── 予報有効ホライズン分類 ────────────────────────────────────────────────
# 遅い変数（SST・気温・気圧水準）：変化が緩やか → H=28 でも有効
SLOW_FACTORS = {
    "sst_avg",                             # SST日次平均（日内変動極小）
    "sst_delta",                           # 7日間SST変化（回遊アジ到来/離脱シグナル）
    "sst_gradient",                        # 外房沖SST - 東京湾内SST（黒潮近接指標）
    "temp_avg", "temp_max", "temp_min",    # 気温（日次avg/max/min）
    "pressure_avg", "pressure_min",        # 気圧水準（日次avg/min）
    "pressure_delta",                      # 気圧変化傾向（低気圧接近シグナル）
    "tide_range", "moon_age", "moon_sin", "moon_cos", "tide_type_n", "tide_delta",
    # 潮汐×季節 交互作用（方式C: 季節×3潮群）── 12因子
    # 潮群: 大潮 / 中小潮(中潮+小潮) / 長若潮(長潮+若潮)
    # 大潮の影響が季節で反転（春OK / 夏冬NG）、長若潮も季節で変動
    "tide_grp_oshio_spring", "tide_grp_oshio_summer", "tide_grp_oshio_autumn", "tide_grp_oshio_winter",
    "tide_grp_chusho_spring", "tide_grp_chusho_summer", "tide_grp_chusho_autumn", "tide_grp_chusho_winter",
    "tide_grp_chowaka_spring", "tide_grp_chowaka_summer", "tide_grp_chowaka_autumn", "tide_grp_chowaka_winter",
    "is_holiday",          # カレンダー因子：未来確定値 → 全ホライズン有効
    "is_consec_holiday",   # 連休フラグ（GW/盆/年末年始の3日以上連続休日）
    "is_summer_vacation",  # 夏休みフラグ（7/21〜8/31：家族・子供客増加シグナル）
    "spawn_season_n",      # 乗っ込み・産卵期（2〜5月=1）: シーバス/マダイ/ヒラメ/サワラ等
    # 水色予測スコア: water_color_model.py が降水ラグ+波+潮流から推定
    # 実測水色がないポイントも含む全点×全日で補完 → SLOW因子（H=28でも有効）
    # ※ 実測 water_color_imp_n がある場合は obs_factor として別途使用
    "water_color_pred_n",  # 予測水色スコア（water_color_daily テーブル）
    # CMEMS 海洋データ（週単位で変化 → SLOW因子）
    "sla_avg",   # SSH偏差平均 (m)：正=黒潮北上=澄み水=アジ・マダイ有利
    "chl_avg",   # クロロフィルa平均 (mg/m³)：高=ベイト豊富=回遊魚集まる
    "sss_avg",   # 塩分平均 (PSU)：高=黒潮水=マダイ・カツオ・キンメ有利
    # CMEMS 深度別データ派生特徴量（週単位で変化 → SLOW因子）
    "do_surface",        # 表層溶存酸素 (mmol/m³)：低=青潮リスク・貧酸素底層
    "do_bottom",         # 深層溶存酸素（最深レコード）：底魚生息可否の直接指標
    "temp_50m",          # 水深50m水温 (℃)：黒潮コア深度・底魚の生息適水温
    "temp_100m",         # 水深100m水温：深海性魚種（キンメ・アコウダイ）の指標
    "temp_200m",         # 水深200m水温：沖合深場釣りの指標
    "thermocline_depth", # 躍層深度 (m)：表層-深層の温度差最大深度
    "no3_surface",       # 表層硝酸塩 (mmol/m³)：高=栄養塩豊富=プランクトン増加予兆
    # CMEMS ラグ特徴量（黒潮の変化速度・遅延反応）
    "sla_delta",         # SLA 7日間変化 (m)：正=黒潮北上中=澄み水進行シグナル
    "chl_delta",         # クロロフィル 7日間変化 (mg/m³)：正=ベイト急増=回遊魚フロント形成
    "sla_monthly",       # ±30日平均SLA：月次黒潮状態（マダイ/カンパチ/アカムツ等に有効）
    "sla_lag30",         # 30日前SLA：ヒラメ等底魚の月次遅延反応
    # 黒潮接岸指数（月次・広域）：大蛇行 vs 接岸のレジームを捉える
    # avg_SLA(lat34-36,lon138-142) - avg_SLA(lat32-34,lon136-140)
    # 正=接岸→シイラ↑  負=大蛇行→ワラサ↑・カツオ微増  r=0.46(シイラ),r=-0.29(ワラサ)
    "sla_approach_idx",
    # 黒潮回廊月次SLA絶対レベル（33-37°N,139-142°E）: 接岸指数との違い＝差分でなく絶対水準
    # マダイr=+0.75、カワハギr=+0.61、カンパチr=+0.54、アカムツr=-0.48（2026/04/18分析）
    "kuroshio_sla_monthly",
    # 黒潮回廊月次SLA変化率（当月 - 前月）: 絶対水準ではなく変化速度を捉える
    # 黒潮北上中（正値）= 澄み水進行・青物活性↑  南下中（負値）= 濁り水進行・青物活性↓
    "kuroshio_sla_delta_1m",
    # 沖合回遊魚用月次SLA（34-36°N,141-143°E）: 黒潮本流の絶対水準
    # カツオ/キハダ: 沿岸ポイントSLAと独立した外洋シグナル（沿岸はr≈0.0→沖合で再評価）
    "sla_pelagic_monthly",
    # SST 3日変化率（当日 - 3日前）: 7日差分(sst_delta)より短周期の温度変化を捉える
    # 急冷（負値）= 冬アジ接岸・カレイ活性↑  急暖（正値）= 夏型移行・底魚活性↓
    # sst_delta(7日)より反応が早い → 短期予測(H≤7)で補完的に機能
    "sst_delta_3d",
    # SSS 7日変化率（当日 - 7日前）: 塩分急変は黒潮フロント通過シグナル
    # 正値=塩分上昇（黒潮水流入）= 澄み水・マダイ/カツオ活性↑
    # 負値=塩分低下（淡水流入・湾水が優勢）= 濁り・底魚活性↓
    "sss_delta_7d",
    # 旬内残り日数（1〜10: 旬末に向かうにつれ増加）
    # 旬頭 vs 旬末で釣果パターンが異なる魚種（産卵期移行、回遊盛期/終期）
    # カレンダー確定値 → 全ホライズン有効（CALENDAR_FACTORS と同分類）
    "day_of_decade",
    # temp_100m × 季節交互作用（深層水温の季節依存性を捉える）
    "temp_100m_spring", "temp_100m_summer", "temp_100m_autumn", "temp_100m_winter",
    "temp_100m_bin",     # 深層水温区分: 0=cold(<8℃) / 1=warm(8-12℃) / 2=hot(>12℃)
    # CMEMS CHL月次集計（ベイト密度の月次シグナル）: SLOW因子 → 全H有効
    # SLAの月次指数と同様に、当月のCHL平均を広域ベイト環境の指標として使用
    "chl_monthly",
    # CMEMS 複合スコア（MAX_FACTORS=12化で再試行。CMEMS capの枠内で競合）
    "kuroshio_score",    # 黒潮近接総合指標（sla高・chl低 → 正）
    "nutrient_score",    # 栄養環境総合指標（chl高・no3高 → 正）
    "deepwater_score",   # 深海環境総合指標（do_bottom高・temp_100m適正 → 正）
}
# 速い変数（風・波・降水・急変動）：数日で激変 → H>7 では無効化
FAST_FACTORS = {
    "wind_speed_avg", "wind_speed_max",    # 風速（日次avg/max）
    "wind_dir_mode",                       # 風向（最頻方角）
    "wind_dir_n",                          # 風向北南成分 cos(deg): 北=+1, 南=-1（循環補正）
    "wind_dir_e",                          # 風向東西成分 sin(deg): 東=+1, 西=-1（循環補正）
    "wave_height_avg", "wave_height_max",  # 波高（日次avg/max）
    "wave_clamp",                          # 波高キャップ min(wave_height_avg, 2.0)：逆U字効果（2m超は"釣れない荒れ"）
    "wave_period_avg", "wave_period_min",  # 波周期（日次avg/min）
    "swell_height_avg", "swell_height_max",# うねり（日次avg/max）
    "temp_range",                          # 日較差（晴天シグナル、急変しやすい）
    "temp_delta",                          # 前日比気温変化（冬の南風警告: 急上昇→不漁）
    "pressure_range",                      # 日内変動幅（前線通過強度）
    "pressure_delta_48h",  # 48時間気圧変化（2日前との差分）: 低気圧接近の予兆（swell先行）
    "precip_sum",                          # 当日合計降水量
    "precip_sum1",                         # 前日合計（翌日の濁り）
    "precip_sum2",                         # 前々日合計（2日遅れ濁りピーク）
    "precip_sum3",  # 3日前合計（濁りラグ3日）
    "precip_sum4",  # 4日前合計（濁りラグ4日）
    "precip_sum5",  # 5日前合計（分析: 水色変化への最大影響ラグ）
    "precip_sum6",  # 6日前合計
    "precip_sum7",  # 7日前合計（濁り影響限界・以降は自然回復）
    "water_color_prev_n",  # 前日の実測水色スコア（近接補完込み・H≤7で有効）
    "prev_week_cnt",                       # 前週釣果（自己相関）H>7では2週以上前の情報になるため無効化
    "typhoon_dist", "typhoon_wind",        # 台風接近距離・最大風速（イベント変数 H≤5が有効限界）
    "current_speed_avg", "current_speed_max",  # 潮流速度（数時間で急変 → H>7は無効）
    "current_dir_mode",                    # 潮流方向（同上）
}

# カレンダー因子（土日・祝日フラグ）── 未来も確定値なので全ホライズンで有効
# 【重要】土日祝は乗合船に初心者・月イチアングラーが増える → cnt_min↓, cnt_avg↓
# 平日比: 土日のcnt_min -28〜-32%（アジ全船宿集計 2023-2026）
# 2023〜2026 国民の祝日リスト（振替休日含む・土日は weekday() で別途判定）
_JP_HOLIDAYS = frozenset([
    # 2023
    "2023/01/01","2023/01/02","2023/01/09","2023/02/23","2023/03/21",
    "2023/04/29","2023/05/03","2023/05/04","2023/05/05",
    "2023/07/17","2023/08/11","2023/09/18","2023/09/23","2023/10/09",
    "2023/11/03","2023/11/23",
    # 2024
    "2024/01/01","2024/01/08","2024/02/12","2024/02/23","2024/03/20",
    "2024/04/29","2024/05/03","2024/05/06","2024/07/15","2024/08/12",
    "2024/09/16","2024/09/22","2024/09/23","2024/10/14",
    "2024/11/04","2024/11/23",
    # 2025
    "2025/01/01","2025/01/13","2025/02/11","2025/02/24","2025/03/20",
    "2025/04/29","2025/05/05","2025/05/06","2025/07/21","2025/08/11",
    "2025/09/15","2025/09/23","2025/10/13",
    "2025/11/03","2025/11/24",
    # 2026
    "2026/01/01","2026/01/12","2026/02/11","2026/02/23","2026/03/20",
    "2026/04/29","2026/05/04","2026/05/05","2026/05/06",
    "2026/07/20","2026/08/11","2026/09/21","2026/09/23",
    "2026/10/12","2026/11/03","2026/11/23",
])

def _is_holiday(date_str: str) -> int:
    """土日・祝日なら1、平日なら0"""
    try:
        dt = datetime.strptime(date_str, "%Y/%m/%d")
        return 1 if (dt.weekday() >= 5 or date_str in _JP_HOLIDAYS) else 0
    except Exception:
        return 0

# ── 連休・夏休みフラグ ────────────────────────────────────────────────────────
# GW/盆/年末年始の「3日以上続く連休ブロック」に含まれる日付を事前キャッシュ
def _build_consec_holiday_set() -> frozenset:
    """GW/盆/年末年始シーズン内で3日以上連続する土日祝の日付セットを返す。"""
    from datetime import date as _date, timedelta as _td
    TARGET_SEASONS = []
    for y in range(2023, 2027):
        TARGET_SEASONS += [
            (_date(y, 4, 29), _date(y, 5, 6)),            # GW
            (_date(y, 8, 10), _date(y, 8, 16)),            # お盆
            (_date(y - 1, 12, 28), _date(y, 1, 4)),        # 年末年始
        ]
    result = set()
    for start, end in TARGET_SEASONS:
        block = []
        d = start
        while d <= end:
            ds = d.strftime("%Y/%m/%d")
            if d.weekday() >= 5 or ds in _JP_HOLIDAYS:
                block.append(ds)
            d += _td(days=1)
        if len(block) >= 3:
            result.update(block)
    return frozenset(result)

_CONSEC_HOLIDAY_SET = _build_consec_holiday_set()

def _is_consec_holiday(date_str: str) -> int:
    """GW・盆・年末年始の連休（3日以上連続）なら1"""
    return 1 if date_str in _CONSEC_HOLIDAY_SET else 0

def _is_summer_vacation(date_str: str) -> int:
    """夏休み期間（7/21〜8/31）なら1。家族・子供客増加シグナル。"""
    try:
        dt = datetime.strptime(date_str, "%Y/%m/%d")
        return 1 if (dt.month == 7 and dt.day >= 21) or dt.month == 8 else 0
    except Exception:
        return 0

def _spawn_season_n(date_str: str) -> int:
    """春の乗っ込み・産卵回帰期（2〜5月）なら1。
    対象魚種: シーバス(2〜4月河川回帰), マダイ(4〜6月), カレイ類(2〜3月), ヒラメ(1〜4月)等
    回遊魚: サワラ(3〜5月東京湾接岸), ブリ系(冬〜春), カツオ(5〜9月北上)
    ※ obs_factor ではなく SLOW因子（カレンダー確定値）として全ホライズン有効
    """
    try:
        m = int(date_str[5:7])
        return 1 if m in (2, 3, 4, 5) else 0
    except Exception:
        return 0


def _day_of_decade(date_str: str) -> int:
    """旬内日数（1〜11）を返す。
    上旬=day 1-10、中旬=day 11-20、下旬=day 21-末日（月末まで）。
    旬頭（1）と旬末（10/11）でポイント消耗・魚の学習行動が異なる前提。
    """
    try:
        d = int(date_str[8:10])
        if d <= 10:
            return d            # 上旬 1-10
        elif d <= 20:
            return d - 10       # 中旬 1-10
        else:
            return d - 20       # 下旬 1-11
    except Exception:
        return 0

FAST_MAX_H = 7   # 速い変数は H>7 では予報精度ゼロとみなして使わない

# 特徴量上限（過学習防止）: 相関上位 MAX_FACTORS 個のみ採用
# カテゴリ別上限でCMEMS/tide_grp_*の枠占有を防止（2026/04/18）
MAX_FACTORS        = 12   # 全体上限
MAX_CMEMS_DEFAULT  = 2    # 全魚種デフォルト: CMEMS最大2個
MAX_TIDE_GRP       = 99   # tide_grp_*: 制限なし

# 2階建て因子設計（2026/04/19）
# Tier1 BASE_FACTORS: 常時使用・競合から保護（CMEMS追加で押し出されない）
BASE_FACTORS: frozenset = frozenset({
    # 潮汐・月齢（天文確定値）
    "tide_type_n", "tide_coeff", "tide_delta",
    "moon_age", "moon_sin", "moon_cos",
    # 旬・カレンダー（決定論的）
    "decade_no", "is_holiday", "is_weekend",
    "is_long_holiday", "is_summer_vacation",
    # 乗っ込み（季節構造）
    "spawn_season_n",
    # 基本気象（ほぼ全コンボで有効）
    "sst_avg", "temp_avg", "pressure_avg",
})
MAX_TIER2 = 12  # Tier2（非BASE因子）から最大採用数（BASE常時確保に加えてCMEMS・海況から最大12因子）

# per-combo FAST_MAX_H オーバーライド
# 月齢・潮汐が主要因子で fast因子がノイズになるコンボは低い値を設定
# メバル×第三幸栄丸: moon_sin r=0.721(旬) が最強因子。H=7でfast因子が月齢を埋没させる
_FAST_MAX_H_OVERRIDE: dict = {
    ("メバル", "第三幸栄丸"): 3,  # H>3でfast因子無効化 → 月齢シグナルのみ使用
}

# per-combo 除外因子ブラックリスト
# 座標ミスマッチ・疑似相関が確認されたコンボ×因子を明示的に除外する
# ちがさき丸×タイ五目: do_surface は東京湾DO値が相模湾コンボに適用された疑似相関
#   （相模湾は外洋型で青潮が発生しにくく、DO低下と釣果の因果関係なし）
# マルイカ×秀丸(lat=35.05,lon=138.87 相模湾西部): do_surface は東京湾DO値の疑似相関
#   相模湾西部は外洋型、青潮発生しにくい。r=-0.410 だが座標ミスマッチの可能性高い
# マルイカ×幸栄丸(lat=35.97,lon=140.70 茨城沖): water_color_prev_n r=-0.837, n=74
#   超高相関（|r|>0.8）はn=74では過学習疑い。除外してfallbackへ
FACTOR_BLACKLIST: dict[tuple, set] = {
    ("タイ五目", "ちがさき丸"): {"do_surface"},
    ("マルイカ", "秀丸"):       {"do_surface"},
    ("マルイカ", "幸栄丸"):     {"water_color_prev_n"},
}

# ── 全因子リスト（相関計算・バックテスト対象）──────────────────────────────
# 06:00スナップショットを廃止し、全変数を日次集計（min/max/avg）に統一。
WX_FACTORS = [
    # 水温（日内変動極小 → avg のみ）
    "sst_avg",
    # 気温（日次 avg/max/min/range）
    "temp_avg", "temp_max", "temp_min", "temp_range",
    # 気圧（日次 avg/min + 変化 + 変動幅）
    "pressure_avg", "pressure_min",
    "pressure_delta",   # 当日min - 前日min（低気圧接近/通過シグナル）
    "pressure_delta_48h",  # 当日min - 2日前min（swell先行シグナル）
    "pressure_range",   # 日内変動幅（前線通過強度 → 全魚種で活性化）
    # 風（日次 avg/max + 最頻風向）
    "wind_speed_avg", "wind_speed_max",
    "wind_dir_mode",    # 最頻風向（16方位に丸めて mode、度数単位）
    "wind_dir_n",      # 北南成分 cos(wind_dir_deg): 北=+1, 南=-1
    "wind_dir_e",      # 東西成分 sin(wind_dir_deg): 東=+1, 西=-1
    # 波浪（日次 avg/max + 周期 avg/min）
    "wave_height_avg", "wave_height_max",
    "wave_clamp",          # 波高キャップ min(wave_height_avg, 2.0)：逆U字効果（2m超は"釣れない荒れ"）
    "wave_period_avg", "wave_period_min",
    # うねり（日次 avg/max）
    "swell_height_avg", "swell_height_max",
    # 降水量（日次合計 + ラグ）
    # 【重要】雨の2日後に濁りが最大 → precip_sum2 が負相関（全魚種共通シグナル）
    # 【重要】イカ類は雨後活性↑（栄養塩流入・濁り）→ precip_sum/sum1 で正相関が出るケースあり
    "precip_sum",    # 当日合計：低気圧通過シグナル（正相関の可能性）
    "precip_sum1",   # 前日合計：翌日の濁り（負相関の可能性）
    "precip_sum2",   # 前々日合計：2日遅れ濁りピーク（負相関 → 全魚種適用）
    # 【重要】降水ラグ3〜7日: 分析で最大影響ラグ=5〜7日と判明
    # 澄→濁遷移4.2日、濁→澄遷移3.7日 → 5〜7日前降水が当日水色に最も影響
    # 水深・沖具合によりラグが異なる（浅場=短ラグ、深場/沖=長ラグ）
    "precip_sum3",   # 3日前合計（濁りラグ3日）
    "precip_sum4",   # 4日前合計
    "precip_sum5",   # 5日前合計（水色変化の最大影響ラグ）
    "precip_sum6",   # 6日前合計
    "precip_sum7",   # 7日前合計（濁り影響限界）
    # 前日実測水色（近接補完済み）: H=0/1で最強の水色入力
    # 水色は3〜4日かけて遷移 → 前日値はH=0/1で高相関、H>3で急速に劣化
    "water_color_prev_n",
    # 気温変化（前日比）
    "temp_delta",    # 当日avg - 前日avg（冬の急上昇 → 南風・表層暖水 → イカ不漁）
    # SST変化率（7日間 / 3日間）
    # 【重要】回遊アジは水温変化で到来/離脱 → SST急落時に大アジ回遊開始シグナル
    "sst_delta",     # 当日SST - 7日前SST（降下=冬型アジ到来、上昇=夏型移行シグナル）
    "sst_delta_3d",  # 当日SST - 3日前SST（sst_deltaより短周期・急変捕捉）
    # SST勾配（黒潮近接指標）
    # 【重要】外房沖SST - 東京湾内SST → 黒潮が岸に近いほど勾配大 → 青物・マダイ高活性シグナル
    "sst_gradient",  # 外房沖(35.65N/140.87E) - 東京湾内(35.3N/139.68E) SST差
    # 潮流速度（Open-Meteo Marine API: ocean_current_velocity）
    # 【重要】シーバス・スズキ: 潮止まりで釣果激減（長崎屋kanso実証）
    # 【重要】アジ・サバ等: 潮流がないと餌が流れない → 底物にも影響
    # 速い変数: 数時間で変化するため FAST_FACTORS に分類（H>7 では無効化）
    "current_speed_avg",  # 日次平均潮流速度[m/s]（止まり≈0, 速潮≈1.5）
    "current_speed_max",  # 日次最大潮流速度[m/s]（急流ピーク）
    "current_dir_mode",   # 日次最頻潮流方向[度]（流向の再現性）
    # 水色予測スコア（water_color_model.py 生成 → analysis.sqlite water_color_daily）
    # 降水ラグ＋波高＋潮流から全点推定。実測水色なしコンボも補完される。
    # SLOW因子（降水予報は14日先まで取得可能）→ 全H有効
    "water_color_pred_n",
    # CMEMS 表層（黒潮SSH偏差・クロロフィル・塩分）: SLOW因子 → 全H有効
    "sla_avg",          # SSH偏差 (m): 正=黒潮北上=澄み水
    "chl_avg",          # クロロフィルa (mg/m³): 高=ベイト豊富
    "sss_avg",          # 塩分 (PSU): 高=黒潮水
    # CMEMS 深度別派生特徴量: SLOW因子 → 全H有効
    "do_surface",       # 表層溶存酸素 (mmol/m³): 低=青潮リスク
    "do_bottom",        # 深層溶存酸素: 底魚生息可否の直接指標
    "temp_50m",         # 水深50m水温 (℃): 黒潮コア深度・底魚適水温
    "temp_100m",        # 水深100m水温: キンメ・アコウダイ等深海性魚種
    "temp_200m",        # 水深200m水温: 沖合深場釣りの指標
    "thermocline_depth",# 躍層深度 (m): 表層-深層温度差最大深度
    "no3_surface",      # 表層硝酸塩 (mmol/m³): 高=栄養塩豊富=プランクトン増加予兆
    # CMEMS ラグ特徴量（黒潮の変化速度）
    "sla_delta",        # SLA 7日間変化 (m): 正=黒潮北上中シグナル
    "chl_delta",        # クロロフィル 7日間変化: 正=ベイト急増シグナル
    "sla_monthly",      # ±30日平均SLA: 月次黒潮状態（SLOW・全H有効）
    "sla_lag30",        # 30日前SLA: 底魚の月次遅延反応（SLOW・全H有効）
    "sla_approach_idx", # 黒潮接岸指数（月次広域）: 正=接岸→シイラ↑ 負=大蛇行→ワラサ↑
    "kuroshio_sla_monthly", # 黒潮回廊SLA絶対水準（33-37°N,139-142°E）: マダイr=+0.75
    "kuroshio_sla_delta_1m", # 黒潮回廊SLA当月-前月: 変化速度シグナル
    "sla_pelagic_monthly",  # 沖合月次SLA（34-36°N,141-143°E）: カツオ/キハダ外洋シグナル
    # SSS変化率（7日間）: 塩分急変=黒潮フロント通過シグナル
    "sss_delta_7d",  # 当日SSS - 7日前SSS: 正=黒潮水流入, 負=淡水流入
    # temp_100m × 季節交互作用
    "temp_100m_spring", "temp_100m_summer", "temp_100m_autumn", "temp_100m_winter",
    "temp_100m_bin",    # 深層水温区分: 0=cold / 1=warm / 2=hot
    # CMEMS CHL月次集計（ベイト密度の月次シグナル: SLOW・全H有効）
    "chl_monthly",
    # CMEMS 複合スコア（MAX_FACTORS=12化で再試行。CMEMS capの枠内で競合）
    "kuroshio_score",   # 黒潮近接総合指標（sla高・chl低 → 正）
    "nutrient_score",   # 栄養環境総合指標（chl高・no3高 → 正）
    "deepwater_score",  # 深海環境総合指標（do_bottom高・temp_100m適正 → 正）
]
# 潮汐（tide テーブルから取る）
TIDE_FACTORS = ["tide_range", "moon_age", "moon_sin", "moon_cos", "tide_type_n", "tide_delta",
                # 潮汐×季節 交互作用（方式C: 季節×3潮群）── 12因子
                # 潮群: 大潮 / 中小潮(中潮+小潮) / 長若潮(長潮+若潮)
                # 両方とも確定値（潮汐=天文計算、季節=カレンダー）→ 全H有効
                "tide_grp_oshio_spring", "tide_grp_oshio_summer", "tide_grp_oshio_autumn", "tide_grp_oshio_winter",
                "tide_grp_chusho_spring", "tide_grp_chusho_summer", "tide_grp_chusho_autumn", "tide_grp_chusho_winter",
                "tide_grp_chowaka_spring", "tide_grp_chowaka_summer", "tide_grp_chowaka_autumn", "tide_grp_chowaka_winter"]

# 釣果自己相関因子（前週釣果 → H≤7で有効、H>7では2週以上前の情報で精度低下）
CATCH_FACTORS = ["prev_week_cnt"]

# 台風因子（イベント変数 → FAST扱いで H>7 は無効化）
TYPHOON_FACTORS = ["typhoon_dist", "typhoon_wind"]

# カレンダー因子（土日・祝日 → 全ホライズンで有効）
CALENDAR_FACTORS = ["is_holiday", "is_consec_holiday", "is_summer_vacation", "spawn_season_n",
                    "day_of_decade"]  # 旬内残り日数（1〜10: カレンダー確定値 → 全H有効）

# 全因子（相関計算対象）
ALL_FACTORS = WX_FACTORS + TIDE_FACTORS + CATCH_FACTORS + TYPHOON_FACTORS + CALENDAR_FACTORS

# カテゴリ別上限用セット（MAX_CMEMS / MAX_TIDE_GRP で枠を制御）
CMEMS_FACTORS = {
    "sla_avg", "chl_avg", "sss_avg",
    "do_surface", "do_bottom", "temp_50m", "temp_100m", "temp_200m",
    "thermocline_depth", "no3_surface",
    "sla_delta", "chl_delta", "sla_monthly", "sla_lag30", "sla_approach_idx",
    "temp_100m_spring", "temp_100m_summer", "temp_100m_autumn", "temp_100m_winter",
    "temp_100m_bin",
    "chl_monthly",
    "kuroshio_score", "nutrient_score", "deepwater_score",
    "sss_delta_7d",  # SSS 7日変化率: 塩分急変=黒潮フロント通過シグナル
    # 注: sla_approach_idx / kuroshio_sla_monthly / sla_pelagic_monthly /
    #     kuroshio_sla_delta_1m は広域指数扱いのため CMEMS_FACTORS に含めない（cap管理外）
}
TIDE_GRP_FACTORS = {
    "tide_grp_oshio_spring", "tide_grp_oshio_summer", "tide_grp_oshio_autumn", "tide_grp_oshio_winter",
    "tide_grp_chusho_spring", "tide_grp_chusho_summer", "tide_grp_chusho_autumn", "tide_grp_chusho_winter",
    "tide_grp_chowaka_spring", "tide_grp_chowaka_summer", "tide_grp_chowaka_autumn", "tide_grp_chowaka_winter",
}

def _apply_factor_caps(factor_r_dict: dict, max_total: int = MAX_FACTORS,
                       max_cmems: int = MAX_CMEMS_DEFAULT,
                       corr_thr: float = 0.10) -> dict:
    """2階建て因子設計（2026/04/19）:
    Tier1 BASE_FACTORS: corr_thr 通過済みなら常に採用・競合から保護。
    Tier2 残り因子: |r|降順で MAX_TIER2 個まで・CMEMS上限 max_cmems 付き。
    CMEMS上限はコンボ別自動最適化（_find_best_cmems）で決定。
    """
    # Tier1: BASE_FACTORSはCMEMS競合から保護して全確保
    base_selected = {f: r for f, r in factor_r_dict.items() if f in BASE_FACTORS}
    tier2_cands   = {f: r for f, r in factor_r_dict.items() if f not in BASE_FACTORS}

    # Tier2: |r|降順・CMEMS上限付きでMAX_TIER2個まで採用
    tier2_sorted = sorted(tier2_cands.items(), key=lambda x: abs(x[1]), reverse=True)
    tier2_selected: dict = {}
    cmems_cnt = 0
    for fac, rv in tier2_sorted:
        if fac in CMEMS_FACTORS:
            if cmems_cnt >= max_cmems:
                continue
            cmems_cnt += 1
        tier2_selected[fac] = rv
        if len(tier2_selected) >= MAX_TIER2:
            break

    return {**base_selected, **tier2_selected}


def _find_best_cmems(all_en_h0: list, months: list, decadal: dict,
                     fold_corr_thr: float) -> int:
    """CMEMS上限のコンボ別最適化。0/2/4/6の4パターンを LOO-CV wMAPE で評価し最良を返す。
    cnt_avg H=0 のみ評価。alpha は OLS で推定（本番モデルとの乖離を抑制）。
    BASE_FACTORS は corr_thr スキップ（常時確保・本番モデルと同一条件）。
    """
    CMEMS_CANDIDATES = [0, 2, 4, 6]
    MIN_TRAIN_MONTHS_CMEMS = 6  # full backtest の MIN_MONTHS と揃える
    cmems_wmape: dict = {}

    for mc in CMEMS_CANDIDATES:
        preds: list = []; acts: list = []
        for test_month in months:
            train = [r for r in all_en_h0 if r["date"][:7] != test_month]
            test  = [r for r in all_en_h0 if r["date"][:7] == test_month]
            # 月数ベースでガード（行数ではなく月数で揃える）
            if len({r["date"][:7] for r in train}) < MIN_TRAIN_MONTHS_CMEMS or not test:
                continue
            tr_ys = [r.get("cnt_avg") for r in train]
            tr_met = [v for v in tr_ys if v is not None]
            mm, ms = mean_std(tr_met)
            if mm is None or not ms:
                continue
            # 因子相関（BASE_FACTORSはcorr_thrスキップ・本番モデルと同一条件）
            fr: dict = {}
            for fac in ALL_FACTORS:
                xs = [r.get(fac) for r in train]
                rv, _, _ = pearson(xs, tr_ys)
                if rv is not None and (abs(rv) >= fold_corr_thr or fac in BASE_FACTORS):
                    fr[fac] = rv
            fr = _apply_factor_caps(fr, max_cmems=mc, corr_thr=fold_corr_thr)
            if not fr:
                continue
            # hist_params（fold学習データ）
            hp: dict = {}
            for fac in ALL_FACTORS:
                vs = [r.get(fac) for r in train if r.get(fac) is not None]
                m2, s2 = mean_std(vs)
                if m2 is not None and s2:
                    hp[fac] = (m2, s2)
            w = sum(abs(v) for v in fr.values()) or 1.0
            # OLS alpha 推定: α = Σ(correction * (act - base)) / Σ(correction²)
            # 本番の alpha_scale OLS と同一ロジック（clip [0, 1.2]）
            ols_num = 0.0; ols_den = 0.0
            for r in train:
                act = r.get("cnt_avg")
                if act is None:
                    continue
                dn = r.get("decade")
                base = decadal.get(dn, {}).get("avg_cnt", mm) if decadal else mm
                nx = 0.0
                for fac, rv in fr.items():
                    v = r.get(fac)
                    if v is None or fac not in hp:
                        continue
                    fm, fs = hp[fac]
                    nx += rv * (v - fm) / fs
                corr = (nx / w) * ms
                ols_num += corr * (act - base)
                ols_den += corr ** 2
            alpha = min(1.2, max(0.0, ols_num / ols_den)) if ols_den > 1e-10 else 0.5
            for r in test:
                act = r.get("cnt_avg")
                if act is None:
                    continue
                dn = r.get("decade")
                base = decadal.get(dn, {}).get("avg_cnt", mm) if decadal else mm
                nx = 0.0
                for fac, rv in fr.items():
                    v = r.get(fac)
                    if v is None or fac not in hp:
                        continue
                    fm, fs = hp[fac]
                    nx += rv * (v - fm) / fs
                preds.append(base + (nx / w) * ms * alpha)
                acts.append(act)
        sc = _wmape(preds, acts)
        if sc is not None:
            cmems_wmape[mc] = sc

    if not cmems_wmape:
        return MAX_CMEMS_DEFAULT
    return min(cmems_wmape, key=cmems_wmape.get)


# 観測因子リストは normalize/obs_fields.json から動的に取得する。
# → OBS_FACTORS は _get_obs_factors() で取得。新CSV列追加時は obs_fields.json だけ変更。
_OBS_CONFIG_CACHE = None

def _get_obs_config():
    global _OBS_CONFIG_CACHE
    if _OBS_CONFIG_CACHE is None:
        try:
            with open(OBS_FIELDS_FILE, encoding="utf-8") as f:
                _OBS_CONFIG_CACHE = json.load(f)
        except Exception:
            _OBS_CONFIG_CACHE = {"fields": {}}
    return _OBS_CONFIG_CACHE

_OBS_COMBO_CACHE = None
def _get_combo_obs_config():
    global _OBS_COMBO_CACHE
    if _OBS_COMBO_CACHE is None:
        try:
            with open(OBS_FIELDS_COMBO_FILE, encoding="utf-8") as f:
                _OBS_COMBO_CACHE = json.load(f)
        except Exception:
            _OBS_COMBO_CACHE = {}
    return _OBS_COMBO_CACHE

def _apply_combo_obs_overrides(obs, row, fish, ship):
    """obs_fields_combo.json のコンボ固有キーワードスコアを obs に上書き適用する。

    設計: 加算ではなく上書き。
    - コンボ固有キーワードがマッチした場合、グローバルスコアを置き換える
    - 同一フィールドに複数スコアが加算されると上限なく発散する懸念があるため
    - 「コンボ固有キーワードが最も強いシグナル」として優先されることを意図する
    """
    cfg_global = _get_obs_config()
    combo_cfg = _get_combo_obs_config()
    key = f"{fish}×{ship}"
    overrides = combo_cfg.get(key, {})
    for field_name, scores in overrides.items():
        spec = cfg_global.get("fields", {}).get(field_name, {})
        srcs = spec.get("source", field_name)
        srcs = [srcs] if isinstance(srcs, str) else list(srcs)
        combined = " ".join((row.get(s) or "") for s in srcs)
        for kw, score in scores.items():
            if kw in combined:
                obs[field_name] = score
                break
    return obs

def _get_obs_factors():
    """obs_fields.json の role=obs_factor なフィールド名リストを返す。
    water_color_imp_n は load_records() で補完済みのため別途追加。
    """
    cfg = _get_obs_config()
    factors = [name for name, spec in cfg.get("fields", {}).items()
               if spec.get("role") == "obs_factor"]
    # 近接補完済み水色スコア（load_records()で付与）
    if "water_color_imp_n" not in factors:
        factors.append("water_color_imp_n")
    return factors

def _compute_obs_fields(row):
    """obs_fields.json の定義に従い CSV 行から全OBS/TEXTフィールドを計算する。
    戻り値: {field_name: value, ..., 'text_all': '...'}
    新CSV列追加時はこの関数ではなく obs_fields.json にエントリを追加する。
    """
    cfg = _get_obs_config()
    result = {}
    text_parts = []

    for name, spec in cfg.get("fields", {}).items():
        role    = spec.get("role", "obs_factor")
        compute = spec.get("compute", "direct")
        src     = spec.get("source", name)
        srcs    = [src] if isinstance(src, str) else list(src)

        val = None
        if compute == "direct":
            val = _float(row.get(srcs[0]))
        elif compute == "binary":
            v = (row.get(srcs[0]) or "").strip()
            val = float(v) if v in ("0", "1") else None
        elif compute == "avg":
            nums = [_float(row.get(s)) for s in srcs]
            nums = [n for n in nums if n is not None]
            val  = sum(nums) / len(nums) if nums else None
        elif compute == "map":
            raw = (row.get(srcs[0]) or "").strip()
            val = spec.get("map", {}).get(raw)
        elif compute == "keyword_score":
            combined = " ".join((row.get(s) or "") for s in srcs)
            for kw, score in spec.get("scores", {}).items():
                if kw in combined:
                    val = score
                    break
        elif compute == "nonempty":
            val = 1.0 if (row.get(srcs[0]) or "").strip() else 0.0
        elif compute == "split_count":
            raw = (row.get(srcs[0]) or "").strip()
            if raw:
                parts = re.split(r'[,、/・\s]+', raw)
                val   = float(len([p for p in parts if len(p) >= 2]))
        elif compute == "text_concat":
            raw = " ".join(filter(None, ((row.get(s) or "").strip() for s in srcs)))
            val = raw if raw else None

        result[name] = val
        if role == "text_field" and val:
            text_parts.append(val)

    result["text_all"] = " ".join(text_parts)
    return result

TIDE_TYPE_MAP = {"大潮": 4, "中潮": 3, "小潮": 2, "長潮": 1, "若潮": 1}

# エリア → 潮汐ポートコード マッピング
AREA_PORT = {
    # 東京湾
    "平和島":           "tokyo_bay",
    "東葛西":           "tokyo_bay",
    "浦安":             "tokyo_bay",
    "羽田":             "tokyo_bay",
    "横浜本牧港":       "tokyo_bay",
    "横浜港･新山下":    "tokyo_bay",
    "江戸川放水路･原木中山": "tokyo_bay",
    "金沢八景":         "tokyo_bay",
    "鴨居大室港":       "tokyo_bay",
    "長浦":             "tokyo_bay",
    "金谷港":           "tokyo_bay",
    "富浦港":           "tokyo_bay",
    # 相模湾
    "久比里港":         "sagami_bay",
    "大津港":           "sagami_bay",
    "小田原早川港":     "sagami_bay",
    "小網代港":         "sagami_bay",
    "大磯港":           "sagami_bay",
    "茅ヶ崎港":         "sagami_bay",
    "葉山あぶずり港":   "sagami_bay",
    "松輪江奈港":       "sagami_bay",
    "松輪間口港":       "sagami_bay",
    "長井港":           "sagami_bay",
    "保田港":           "sagami_bay",
    "洲崎港":           "sagami_bay",
    # 外房
    "外川港":           "outer_boso",
    "大原港":           "outer_boso",
    "勝浦川津港":       "outer_boso",
    "御宿岩和田港":     "outer_boso",
    "天津港":           "outer_boso",
    "太東港":           "outer_boso",
    "飯岡港":           "outer_boso",
    # 茨城
    "大洗港":           "ibaraki",
    "日立久慈港":       "ibaraki",
    "波崎港":           "ibaraki",
    "鹿島港":           "ibaraki",
    "鹿島市新浜":       "ibaraki",
    # 静岡
    "下田港":           "shizuoka",
    "松崎港":           "shizuoka",
    "沼津内港":         "shizuoka",
    "沼津静浦":         "shizuoka",
    "清水港(巴川)":     "shizuoka",
    "田子の浦港":       "shizuoka",
    "由比":             "shizuoka",
    "吉田港":           "shizuoka",
    "大井川港":         "shizuoka",
    "福田港":           "shizuoka",
    "御前崎港":         "shizuoka",
    "網代":             "shizuoka",
}

KEYWORDS = {
    "潮":   ["上げ潮", "下げ潮", "潮止まり", "二枚潮", "潮が澄", "潮が濁", "潮が速", "潮かわり"],
    "活性": ["群れ", "ムラ", "単発", "入れ食い", "渋い", "活性", "食い渋", "反応"],
    "深度": ["深場", "浅場", "底", "中層", "表層"],
    "色":   ["澄み", "濁り", "青潮", "赤潮", "笹濁"],
    "流れ": ["潮流", "速潮", "潮が走", "二枚潮"],
    "海況": ["ウネリ", "うねり", "時化", "シケ", "べた凪", "海上ナギ", "ベタナギ"],
    # ── 外道カテゴリ（by_catch + kanso_raw 両方を検索）─────────────────────────
    # text_allはby_catchとkanso_rawの結合。「記録の有無」だけでなく
    # kansoの言及（「サバだらけ」等）も含まれ、海況・活性のシグナルとして有効。
    "外道_危険迷惑": ["外道", "ゲスト", "サメ", "ハモ", "ゴンズイ", "オコゼ"],
    "外道_青物":     ["サバ", "イナダ", "ワラサ", "カツオ", "ソウダ", "カンパチ", "シイラ"],
    # サバ: イカ・アジ・タチウオで「邪魔者シグナル」。ヤリイカkanso_rawに223件の言及あり
    "外道_根魚":     ["カサゴ", "メバル", "ソイ", "マハタ", "オニカサゴ"],
    # 根が荒いポイントのシグナル。アマダイ・ヒラメで混じりやすい
    "外道_底魚":     ["ハナダイ", "ウマヅラハギ", "ガンゾウビラメ", "ホウボウ", "イトヨリ",
                     "マトウダイ", "レンコダイ", "ユメカサゴ", "ハチビキ"],
    # 同タナ・同層を泳ぐ魚。マダイ・ヒラメ・アマダイで連動しやすい
    "外道_エサ系":   ["イワシ", "キビナゴ"],
    # 捕食対象ベイトの回遊シグナル。ヒラメ・タチウオで重要
}


# ═══════════════════════════════════════════════════════════════════════════
# ユーティリティ
# ═══════════════════════════════════════════════════════════════════════════

def _float(v):
    try:
        f = float(v)
        return f if math.isfinite(f) else None
    except (TypeError, ValueError):
        return None

def pearson(xs, ys):
    """Pearson r + p値（t近似）を返す。n < 5 なら None"""
    pairs = [(x, y) for x, y in zip(xs, ys) if x is not None and y is not None]
    n = len(pairs)
    if n < 5:
        return None, None, n
    xv = [p[0] for p in pairs]
    yv = [p[1] for p in pairs]
    mx = sum(xv) / n
    my = sum(yv) / n
    sx = math.sqrt(sum((x-mx)**2 for x in xv) / (n-1))
    sy = math.sqrt(sum((y-my)**2 for y in yv) / (n-1))
    if sx == 0 or sy == 0:
        return 0.0, 1.0, n
    r = sum((x-mx)*(y-my) for x, y in zip(xv, yv)) / ((n-1) * sx * sy)
    r = max(-1.0, min(1.0, r))
    if abs(r) >= 1.0:
        return r, 0.0, n
    t = r * math.sqrt(n-2) / math.sqrt(1-r**2)
    # 簡易p値（Abramowitz & Stegun 7.1.26 近似）
    at = abs(t)
    z  = 1 / (1 + 0.2316419 * at)
    poly = z * (0.319381530 + z * (-0.356563782
                + z * (1.781477937 + z * (-1.821255978 + z * 1.330274429))))
    phi = math.exp(-t*t/2) / math.sqrt(2*math.pi) * poly if at < 30 else 0.0
    p = max(0.0, min(1.0, 2 * phi))
    return r, p, n

def mean_std(vals):
    vals = [v for v in vals if v is not None]
    if len(vals) < 2:
        return None, None
    m = sum(vals) / len(vals)
    s = math.sqrt(sum((v-m)**2 for v in vals) / (len(vals)-1))
    return m, (s if s > 0 else None)

def decade_of(date_str):
    """YYYY/MM/DD → 旬番号 1-36"""
    try:
        d = datetime.strptime(date_str, "%Y/%m/%d")
        dec = 1 if d.day <= 10 else (2 if d.day <= 20 else 3)
        return (d.month - 1) * 3 + dec
    except Exception:
        return None


# ═══════════════════════════════════════════════════════════════════════════
# 設定ロード
# ═══════════════════════════════════════════════════════════════════════════

# ── ポイント解決（crawler.py の resolve_point と同ロジック） ─────────────────
_UNRESOLVABLE_POINT_RE = re.compile(
    r'^(航程|近場|浅場|深場|東京湾一帯|湾内|湾奥|港前|南沖|東沖|西沖|北沖|赤灯沖|観音沖|水深\d|^[0-9]+$|前後$)'
)
# 純粋な数値・深度のみ（例: "25m", "30", "42m"）→ load_records で depth_min に転記してクリア
_DEPTH_ONLY_RE = re.compile(r'^\d+(\.\d+)?m?$')
# 埋め込み航程サフィックス（例: "岩和田沖航程5分" → "岩和田沖"）
_KOUTEIRE_SUFFIX_RE = re.compile(r'\s*航程\d+\s*(分|時間|h)?\s*$')

def _is_航程系(pp):
    if not pp:
        return True
    if _UNRESOLVABLE_POINT_RE.match(pp):
        return True
    return False

def _strip_kouteire_suffix(pt: str) -> str:
    """「岩和田沖航程5」→「岩和田沖」。航程サフィックスがなければそのまま返す。"""
    return _KOUTEIRE_SUFFIX_RE.sub("", pt).strip() or pt

_DEPTH_TILDE_RE = re.compile(r'\s*[～〜~]\s*(\d+(?:\.\d+)?\s*m)\s*$', re.IGNORECASE)
_DEPTH_TRAIL_RE = re.compile(r'\s+\d+(?:\.\d+)?\s*m\s*$', re.IGNORECASE)
# ポイント名の表記ゆれ統合（固有名詞は変えない）
# 「中ノ瀬」「中の瀬」は同一ポイント。ヶ・ノは地名固有名詞に使われるため一律変換は禁止。
_POINT_ALIAS = {
    '中ノ瀬': '中の瀬',
    '二ノ宮沖': '二宮沖',
    '洲の崎沖': '洲崎沖',
}

def _normalize_point_name(pt: str) -> str:
    """ポイント名を正規化。
    - 航程サフィックス除去 「岩和田沖航程5」→「岩和田沖」（バケット統合用）
    - チルダ深度表記 「赤灯沖～60m」→「赤灯沖 60m」
    - 表記ゆれ統合（_POINT_ALIAS で個別対応）
    """
    if not pt:
        return pt
    normalized = _strip_kouteire_suffix(pt)
    normalized = _DEPTH_TILDE_RE.sub(r' \1', normalized).strip()
    normalized = _POINT_ALIAS.get(normalized, normalized)
    return normalized if normalized else pt

def _strip_depth_suffix(pt: str) -> str:
    """座標解決用: 末尾の「 60m」「 80m」等を除去して基底ポイント名を返す。"""
    return _DEPTH_TRAIL_RE.sub("", pt).strip() or pt

def _load_point_coords():
    path = os.path.join(NORMALIZE_DIR, "point_coords.json")
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def _load_ship_fish_point():
    path = os.path.join(NORMALIZE_DIR, "ship_fish_point.json")
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return {k: v for k, v in data.items() if not k.startswith("_")}
    except Exception:
        return {}

def _load_area_coords():
    path = os.path.join(NORMALIZE_DIR, "area_coords.json")
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def _resolve_point(point_place1, ship, tsuri_mono, sfp, ship_area_map, point_coords, area_coords):
    """point_place1 + 船宿 + 魚種 → (lat, lon)。解決不能なら (None, None)。"""
    pp = (point_place1 or "").strip()
    # 航程サフィックスを除去して基底ポイント名を取得（座標解決用）
    pp_base = _strip_kouteire_suffix(pp)
    # ① point_place1 直接解決（基底名で試みる）
    if pp_base and not _is_航程系(pp_base):
        entry = point_coords.get(pp_base)
        if entry and entry.get("lat") is not None:
            return entry["lat"], entry["lon"]
    # ② ship_fish_point フォールバック
    ship_data = sfp.get(ship, {})
    fish_entry = ship_data.get(tsuri_mono) or ship_data.get("_default")
    if fish_entry and isinstance(fish_entry, dict):
        for key in ("point1", "point2"):
            pname = fish_entry.get(key, "") or ""
            if pname:
                entry = point_coords.get(pname)
                if entry and entry.get("lat") is not None:
                    return entry["lat"], entry["lon"]
    # ③ area_coords フォールバック
    area = ship_area_map.get(ship, "")
    if area:
        ac = area_coords.get(area)
        if ac and ac.get("lat") is not None:
            return ac["lat"], ac["lon"]
    return None, None


def load_exclude_ships():
    try:
        with open(SHIPS_FILE, encoding="utf-8") as f:
            ships = json.load(f)
        return {s["name"] for s in ships if s.get("exclude") or s.get("boat_only")}
    except Exception:
        return set()

def load_ship_area():
    """ship → area マップ"""
    try:
        with open(SHIPS_FILE, encoding="utf-8") as f:
            ships = json.load(f)
        return {s["name"]: s.get("area", "") for s in ships}
    except Exception:
        return {}

def load_wx_overrides():
    try:
        with open(OVERRIDE_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return {ship: (info["lat"], info["lon"])
                for ship, info in data.get("overrides", {}).items()}
    except Exception:
        return {}

def load_ship_coords():
    """combo_meta から avg lat/lon + オーバーライド適用（レコードに lat/lon がない場合の保険）"""
    conn = _open_ana()
    rows = conn.execute(
        "SELECT ship, AVG(lat), AVG(lon) FROM combo_meta WHERE lat IS NOT NULL GROUP BY ship"
    ).fetchall()
    conn.close()
    coords = {ship: (round(lat,4), round(lon,4)) for ship, lat, lon in rows}
    for ship, (lat, lon) in load_wx_overrides().items():
        coords[ship] = (lat, lon)
    return coords

def load_wx_coords_list():
    if not os.path.exists(DB_WX) or os.path.getsize(DB_WX) == 0:
        return []
    try:
        conn = sqlite3.connect(DB_WX)
        coords = conn.execute("SELECT DISTINCT lat, lon FROM weather").fetchall()
        conn.close()
        return list(coords)
    except Exception:
        return []

def nearest_coord(lat, lon, coords):
    if not coords:
        return (lat, lon)
    return min(coords, key=lambda c: (c[0]-lat)**2 + (c[1]-lon)**2)

# ── water_color_daily テーブル キャッシュ ──────────────────────────────────────
# water_color_model.py が生成する全点×全日の水色予測スコアをメモリに展開する。
# キー: (lat_rounded2, lon_rounded2, date_iso) → wc_pred
# lat/lon は小数2桁丸め（最近傍 wx_coord に合わせるため）
_WC_DAILY_CACHE: dict = {}
_WC_DAILY_LOADED: bool = False
_WC_DAILY_COORDS: list = []  # (lat, lon) のユニークリスト
# 関東（北緯35°付近）で東西≒27km・南北≒33km の楕円フィルター。
# 既存コードと同じ非補正ユークリッド近似で統一。
_WC_MAX_DIST = 0.3

def _load_wc_daily_cache():
    """analysis.sqlite の water_color_daily を一度だけメモリに展開する。"""
    global _WC_DAILY_CACHE, _WC_DAILY_LOADED, _WC_DAILY_COORDS
    if _WC_DAILY_LOADED:
        return
    _WC_DAILY_LOADED = True
    if not os.path.exists(DB_ANA):
        return
    try:
        conn = _open_ana()
        rows = conn.execute("SELECT lat, lon, date, wc_pred FROM water_color_daily").fetchall()
        conn.close()
    except Exception:
        return
    coord_set = set()
    for lat, lon, date, pred in rows:
        k = (round(lat, 2), round(lon, 2), date)
        _WC_DAILY_CACHE[k] = pred
        coord_set.add((round(lat, 2), round(lon, 2)))
    _WC_DAILY_COORDS = list(coord_set)

def _lookup_wc_pred(lat, lon, date_iso):
    """最近傍 wx_coord の当日 wc_pred を返す。テーブルがなければ None。
    最近傍座標が _WC_MAX_DIST(°)より遠い場合は外挿とみなして None を返す。"""
    _load_wc_daily_cache()
    if not _WC_DAILY_CACHE:
        return None
    if not _WC_DAILY_COORDS:
        return None
    wlat, wlon = min(_WC_DAILY_COORDS,
                     key=lambda c: (c[0] - lat)**2 + (c[1] - lon)**2)
    if (wlat - lat)**2 + (wlon - lon)**2 > _WC_MAX_DIST**2:
        return None
    k = (round(wlat, 2), round(wlon, 2), date_iso)
    return _WC_DAILY_CACHE.get(k)

def load_decadal(fish, ship):
    conn = _open_ana()
    rows = conn.execute(
        "SELECT decade_no, avg_cnt, avg_size, n FROM combo_decadal WHERE fish=? AND ship=?",
        (fish, ship)
    ).fetchall()
    conn.close()
    return {r[0]: {"avg_cnt": r[1], "avg_size": r[2], "n": r[3]} for r in rows}


def _build_decadal_from_records(records):
    """records から旬別ベースライン dict を構築（DB 不要・ポイント別 decadal 計算用）"""
    buckets = defaultdict(list)
    size_b  = defaultdict(list)
    for r in records:
        if r.get("decade") is not None and r.get("cnt_avg"):
            buckets[r["decade"]].append(r["cnt_avg"])
        if r.get("decade") is not None and r.get("size_avg"):
            size_b[r["decade"]].append(r["size_avg"])
    return {
        d: {
            "avg_cnt":  sum(v) / len(v),
            "avg_size": sum(size_b[d]) / len(size_b[d]) if size_b.get(d) else None,
            "n": len(v),
        }
        for d, v in buckets.items()
    }


# ═══════════════════════════════════════════════════════════════════════════
# データ読み込み（CSV + weather + tide）
# ═══════════════════════════════════════════════════════════════════════════

def load_records(fish, ship_filter=None):
    """data/YYYY-MM.csv から指定魚種のレコードをロード。
    point_place1 → point_coords.json → lat/lon を per-record で解決する。
    """
    exclude      = load_exclude_ships()
    ship_area    = load_ship_area()
    point_coords = _load_point_coords()
    sfp          = _load_ship_fish_point()
    area_coords  = _load_area_coords()

    records = []
    for fn in sorted(os.listdir(DATA_DIR)):
        if not fn.endswith(".csv") or fn == "cancellations.csv":
            continue
        with open(os.path.join(DATA_DIR, fn), encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                if row.get("is_cancellation") == "1":
                    continue
                if row.get("main_sub") != "メイン":
                    continue
                ship = row.get("ship", "").strip()
                if ship in exclude:
                    continue
                if ship_filter and ship != ship_filter:
                    continue
                tsuri = row.get("tsuri_mono", "").strip()
                if tsuri != fish:
                    continue
                date_str = row.get("date", "").strip()
                if not date_str:
                    continue
                cnt_avg = _float(row.get("cnt_avg"))
                if not cnt_avg or cnt_avg <= 0:
                    continue

                sz_min = _float(row.get("size_min"))
                sz_max = _float(row.get("size_max"))
                size_avg = ((sz_min + sz_max) / 2) if sz_min and sz_max else (sz_min or sz_max)

                kg_min = _float(row.get("kg_min"))
                kg_max = _float(row.get("kg_max"))
                kg_avg  = ((kg_min + kg_max) / 2) if kg_min and kg_max else (kg_min or kg_max)

                # per-record 座標解決（3段階フォールバック）
                point_place1 = row.get("point_place1", "").strip()
                # 深度のみのポイント名（"25m","30m"等）→ depth_min に転記してポイント名クリア
                if point_place1 and _DEPTH_ONLY_RE.match(point_place1):
                    depth_val = _float(point_place1.rstrip('mM'))
                    if depth_val and not _float(row.get("depth_min")):
                        row = dict(row)
                        row["depth_min"] = depth_val
                    point_place1 = ""
                # point_place1 が空 → 3段階フォールバックでポイント名を確定
                if not point_place1:
                    d_min = _float(row.get("depth_min"))
                    if d_min:
                        # ① 水深帯仮想ポイント
                        if d_min <= 40:
                            point_place1 = "浅場(~40m)"
                        elif d_min <= 80:
                            point_place1 = "中深場(41-80m)"
                        elif d_min <= 150:
                            point_place1 = "深場(81-150m)"
                        else:
                            point_place1 = "超深場(150m+)"
                    if not point_place1:
                        # ② ship_fish_point フォールバック（ポイント名を point に割当）
                        ship_data = sfp.get(ship, {})
                        fish_entry = ship_data.get(tsuri) or ship_data.get("_default")
                        if fish_entry and isinstance(fish_entry, dict):
                            for _key in ("point1", "point2"):
                                _pname = fish_entry.get(_key, "") or ""
                                if _pname:
                                    point_place1 = _pname
                                    break
                    if not point_place1:
                        # ③ area_coords フォールバック（エリア名を point に割当）
                        _area = ship_area.get(ship, "")
                        if _area:
                            point_place1 = _area
                lat, lon = _resolve_point(
                    point_place1, ship, tsuri, sfp, ship_area, point_coords, area_coords
                )

                # point_depth_key: ポイント×水深帯の複合キー（実装②用）
                # ※ 水深帯仮想ポイント（浅場/中深場/深場/超深場）は point_place1 がすでに確定
                # ここでは「元のポイント名（確定後）」と「実測水深帯」を組み合わせる
                _d_min_val = _float(row.get("depth_min"))
                if _d_min_val:
                    if _d_min_val <= 40:
                        _dband = "浅場(~40m)"
                    elif _d_min_val <= 80:
                        _dband = "中深場(41-80m)"
                    elif _d_min_val <= 150:
                        _dband = "深場(81-150m)"
                    else:
                        _dband = "超深場(150m+)"
                else:
                    _dband = ""
                _VIRTUAL_BANDS = {"浅場(~40m)", "中深場(41-80m)", "深場(81-150m)", "超深場(150m+)"}
                if point_place1 and _dband and point_place1 not in _VIRTUAL_BANDS:
                    # 実ポイント名 × 実測水深帯の複合キー（仮想ポイントへの重ね掛けは除外）
                    _point_depth_key = f"{point_place1}_{_dband}"
                else:
                    _point_depth_key = ""  # 複合キー不成立の場合は対象外

                # OBS/TEキストフィールドを obs_fields.json から一括計算（コンボ固有スコアで上書き）
                obs = _compute_obs_fields(row)
                obs = _apply_combo_obs_overrides(obs, row, tsuri, ship)

                records.append({
                    "ship":    ship,
                    "area":    row.get("area", "").strip(),
                    "date":    date_str,
                    "decade":  decade_of(date_str),
                    "cnt_avg": cnt_avg,
                    "cnt_min": _float(row.get("cnt_min")),
                    "cnt_max": _float(row.get("cnt_max")),
                    "size_avg": size_avg,
                    "kg_avg":  kg_avg,
                    "point":           point_place1,
                    "point2":          row.get("point_place2", "").strip(),
                    "point3":          row.get("point_place3", "").strip(),
                    "point_depth_key": _point_depth_key,
                    "lat":     lat,
                    "lon":     lon,
                    # 参照用（obs_fields.json 外）
                    "trip_no": int(row.get("trip_no") or 0),
                    # カレンダー因子（土日・祝日・連休・夏休み・乗っ込み）
                    "is_holiday":         _is_holiday(date_str),
                    "is_consec_holiday":  _is_consec_holiday(date_str),
                    "is_summer_vacation": _is_summer_vacation(date_str),
                    "spawn_season_n":     _spawn_season_n(date_str),
                    "day_of_decade":      _day_of_decade(date_str),
                    **obs,   # OBS因子 + テキストフィールド + text_all
                })
    records.sort(key=lambda r: r["date"])

    # 水色補完: 同日・0.3度以内の近接船宿から water_color_imputed を付与
    # 水色なしレコードに対し、同日・最近傍の水色ありレコードの値を補完する
    from collections import defaultdict as _dd
    _date_idx = _dd(list)
    for r in records:
        if r.get("water_color_n") is not None:
            _date_idx[r["date"]].append(r)
    for r in records:
        if r.get("water_color_n") is not None:
            r["water_color_imp_n"] = r["water_color_n"]
            continue
        best = None
        best_dist = 999.0
        lat_r, lon_r = r.get("lat"), r.get("lon")
        if lat_r is None or lon_r is None:
            r["water_color_imp_n"] = None
            continue
        for nb in _date_idx.get(r["date"], []):
            if nb is r:
                continue
            lat_n, lon_n = nb.get("lat"), nb.get("lon")
            if lat_n is None or lon_n is None:
                continue
            dist = ((lat_r - lat_n) ** 2 + (lon_r - lon_n) ** 2) ** 0.5
            if dist < 0.3 and dist < best_dist:
                best_dist = dist
                best = nb
        r["water_color_imp_n"] = best["water_color_n"] if best else None

    # 前日水色 (water_color_prev_n): 前日の近接エリア（0.5度以内）の水色スコア
    # H=0: 予測時点で前日の水色が確定 → 最も信頼できる水色入力
    # H=1: 2日前の水色。水色遷移3.7〜4.2日 → まだ有効
    # H>3: 急速に陳腐化。FAST_MAX_H=7 により H>7 で自動無効化
    # 注意: バックテストでは全H共通でD-1水色を使用（H>1は若干の情報リーク）
    from collections import defaultdict as _dd2
    _date_loc_wc = _dd2(list)
    for r in records:
        wc = r.get("water_color_imp_n")
        if wc is not None and r.get("lat") is not None and r.get("lon") is not None:
            _date_loc_wc[r["date"]].append((r["lat"], r["lon"], wc))

    for r in records:
        try:
            prev_d = (datetime.strptime(r["date"], "%Y/%m/%d") - timedelta(days=1)).strftime("%Y/%m/%d")
        except Exception:
            r["water_color_prev_n"] = None
            continue
        lat_r, lon_r = r.get("lat"), r.get("lon")
        if lat_r is None or lon_r is None:
            r["water_color_prev_n"] = None
            continue
        best_wc = None
        best_dist = 999.0
        for (lat_n, lon_n, wc) in _date_loc_wc.get(prev_d, []):
            dist = ((lat_r - lat_n) ** 2 + (lon_r - lon_n) ** 2) ** 0.5
            if dist < 0.5 and dist < best_dist:
                best_dist = dist
                best_wc = wc
        r["water_color_prev_n"] = best_wc

    # water_color_cat: 観測水色カテゴリ（澄み / 濁り）セグメント軸
    # water_color_n は obs_fields.json 経由の観測スコア（澄み=1.0, 濁り=-1.0付近）
    for r in records:
        wc_n = r.get("water_color_n")
        if wc_n is not None and wc_n >= 0.3:
            r["water_color_cat"] = "澄み"
        elif wc_n is not None and wc_n <= -0.3:
            r["water_color_cat"] = "濁り"
        else:
            r["water_color_cat"] = ""

    return records

def get_daily_wx(conn_wx, lat, lon, date_iso):
    """その日の全3時間データ（最大8点）を日次集計して返す。
    06:00スナップショットを廃止し、全変数を min/max/avg で統一。
    wind_dir は最頻風向（mode）を使用。
    """
    if conn_wx is None:
        return {}
    rows = conn_wx.execute("""
        SELECT wind_speed, wind_dir, temp, pressure,
               wave_height, wave_period, swell_height, sst,
               precipitation, current_speed, current_dir
        FROM weather
        WHERE lat=? AND lon=? AND dt LIKE ?
        ORDER BY dt
    """, (lat, lon, f"{date_iso}%")).fetchall()
    if not rows:
        return None

    wind_speeds    = [r[0] for r in rows if r[0] is not None]
    wind_dirs      = [r[1] for r in rows if r[1] is not None]
    temps          = [r[2] for r in rows if r[2] is not None]
    pressures      = [r[3] for r in rows if r[3] is not None]
    wave_heights   = [r[4] for r in rows if r[4] is not None]
    wave_periods   = [r[5] for r in rows if r[5] is not None]
    swell_heights  = [r[6] for r in rows if r[6] is not None]
    ssts           = [r[7] for r in rows if r[7] is not None]
    precips        = [r[8] for r in rows if r[8] is not None]
    current_speeds = [r[9]  for r in rows if r[9]  is not None]
    current_dirs   = [r[10] for r in rows if r[10] is not None]

    result = {}

    # ── 風速: avg, max ──
    if wind_speeds:
        result["wind_speed_avg"] = sum(wind_speeds) / len(wind_speeds)
        result["wind_speed_max"] = max(wind_speeds)

    # ── 風向: 最頻方角（16方位に丸めて mode）──
    if wind_dirs:
        # 16方位（22.5°刻み）に丸めて最頻値を取る
        binned = [round(d / 22.5) % 16 * 22.5 for d in wind_dirs]
        result["wind_dir_mode"] = max(set(binned), key=binned.count)

    # ── 気温: avg, max, min ──
    if temps:
        result["temp_avg"]   = sum(temps) / len(temps)
        result["temp_max"]   = max(temps)
        result["temp_min"]   = min(temps)
        result["temp_range"] = max(temps) - min(temps)

    # ── 気圧: avg, min ──
    if pressures:
        result["pressure_avg"]   = sum(pressures) / len(pressures)
        result["pressure_min"]   = min(pressures)
        result["pressure_range"] = max(pressures) - min(pressures)

    # ── 波高: avg, max, clamp ──
    if wave_heights:
        result["wave_height_avg"] = sum(wave_heights) / len(wave_heights)
        result["wave_height_max"] = max(wave_heights)
        # wave_clamp: 逆U字効果（1.5m前後が"釣れる波"、閾値超は"釣れない荒れ"）
        # WAVE_CLAMP_THRESHOLD（デフォルト2.0m）で頭打ち。--wave-clamp で変更可
        result["wave_clamp"] = min(result["wave_height_avg"], WAVE_CLAMP_THRESHOLD)

    # ── 波周期: avg, min ──
    if wave_periods:
        result["wave_period_avg"] = sum(wave_periods) / len(wave_periods)
        result["wave_period_min"] = min(wave_periods)

    # ── うねり: avg, max ──
    if swell_heights:
        result["swell_height_avg"] = sum(swell_heights) / len(swell_heights)
        result["swell_height_max"] = max(swell_heights)

    # ── SST: avg のみ（日内変動極小）──
    if ssts:
        result["sst_avg"] = sum(ssts) / len(ssts)

    # ── 降水量: 日次合計 ──
    if precips:
        result["precip_sum"] = sum(precips)

    # ── 潮流速度: avg, max（止まり=低、流れている=高）──
    # シーバス・スズキ類: 潮止まりで釣果激減（tide_speed_n obs因子とは別に定量化）
    # 速い変数: 数時間で変化するため H>FAST_MAX_H では無効化
    if current_speeds:
        result["current_speed_avg"] = sum(current_speeds) / len(current_speeds)
        result["current_speed_max"] = max(current_speeds)

    # ── 潮流方向: 最頻方向（16方位に丸めて mode）──
    if current_dirs:
        _cb = [round(d / 22.5) % 16 * 22.5 for d in current_dirs]
        result["current_dir_mode"] = max(set(_cb), key=_cb.count)

    return result

_cmems_day_cache: dict = {}

def get_cmems_day(conn_cmems, lat, lon, date_iso):
    """CMEMS 日次データを最近傍グリッド点から返す（1/24°≈4.6km精度）。
    0.25°丸めを廃止し最近傍クエリを直接実行。データがない場合は空 dict。
    """
    if conn_cmems is None:
        return {}
    k = (round(lat, 4), round(lon, 4), date_iso)
    if k in _cmems_day_cache:
        return _cmems_day_cache[k]
    row = conn_cmems.execute(
        """SELECT sla, chl, sss FROM cmems_daily
           WHERE date=?
             AND ABS(lat - ?) < 0.15 AND ABS(lon - ?) < 0.15
           ORDER BY (lat - ?) * (lat - ?) + (lon - ?) * (lon - ?)
           LIMIT 1""",
        (date_iso, lat, lon, lat, lat, lon, lon),
    ).fetchone()
    result = {}
    if row:
        if row[0] is not None:
            result["sla_avg"] = row[0]
        if row[1] is not None:
            result["chl_avg"] = row[1]
        if row[2] is not None:
            result["sss_avg"] = row[2]
    _cmems_day_cache[k] = result
    return result


_sla_nearest_cache:  dict = {}
_sla_monthly_cache:  dict = {}

# In-memory SLA store: populated once on first call to _preload_sla_if_needed()
_SLA_POINT_DATE:  dict = {}   # (lat_r3, lon_r3, date_str) -> sla
_SLA_BY_DATE:     dict = {}   # date_str -> [(lat_r3, lon_r3, sla), ...]  (fallback index)
_SLA_MONTHLY_AGG: dict = {}   # (lat_r3, lon_r3, "YYYY-MM") -> monthly_avg
_SLA_BY_MONTH:    dict = {}   # "YYYY-MM" -> [(lat_r3, lon_r3, avg), ...]  (fallback index)
_SLA_LOADED = False
# cache for coord snapping result: (lat, lon, date/ym) -> nearest value
_SLA_SNAP_CACHE: dict = {}
# 黒潮接岸指数キャッシュ: "YYYY-MM" -> approach_idx
# 定義: avg_SLA(北方 lat34-36,lon138-142) - avg_SLA(南方 lat32-34,lon136-140)
# 正=黒潮が北上・接岸  負=黒潮が南に蛇行（大蛇行）
_SLA_APPROACH_CACHE: dict = {}
_KUROSHIO_SLA_MONTHLY_CACHE: dict = {}
_PELAGIC_SLA_MONTHLY_CACHE: dict = {}

# ── CHL 月次集計キャッシュ（ベイト密度の月次シグナル）─────────────────────────
_CHL_MONTHLY_AGG: dict = {}  # (lat_r3, lon_r3, "YYYY-MM") -> monthly_avg_chl
_CHL_BY_MONTH:    dict = {}  # "YYYY-MM" -> [(lat_r3, lon_r3, avg), ...]
_CHL_SNAP_CACHE:  dict = {}  # (lat, lon, ym) -> nearest monthly avg
_CHL_LOADED = False


def _preload_chl_if_needed(conn_cmems):
    """cmems_daily の CHL を月別集計してin-memory dictに展開する（初回のみ）。
    SLAプリロードと異なり、SQLでGROUP BY後の集計値を取得（全日次を展開しない）。
    """
    global _CHL_LOADED, _CHL_MONTHLY_AGG, _CHL_BY_MONTH
    if _CHL_LOADED:
        return
    if conn_cmems is None:
        _CHL_LOADED = True
        return
    t0 = time.time()
    # chl_monthly_agg が存在すれば高速読み出し（事前集計テーブル）
    tables = [r[0] for r in conn_cmems.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='chl_monthly_agg'"
    ).fetchall()]
    if tables:
        rows = conn_cmems.execute(
            "SELECT lat, lon, ym, avg_chl FROM chl_monthly_agg"
        ).fetchall()
    else:
        rows = conn_cmems.execute(
            """SELECT lat, lon, SUBSTR(date, 1, 7) AS ym, AVG(chl)
               FROM cmems_daily WHERE chl IS NOT NULL
               GROUP BY lat, lon, ym"""
        ).fetchall()
    for lat, lon, ym, avg_chl in rows:
        lr = round(lat, 3)
        nr = round(lon, 3)
        _CHL_MONTHLY_AGG[(lr, nr, ym)] = avg_chl
        if ym not in _CHL_BY_MONTH:
            _CHL_BY_MONTH[ym] = []
        _CHL_BY_MONTH[ym].append((lr, nr, avg_chl))
    elapsed = time.time() - t0
    print(f"  [CMEMS CHL preload] {len(rows):,}座標×月 ({elapsed:.1f}s)", flush=True)
    _CHL_LOADED = True


def _get_chl_monthly_avg(conn_cmems, lat, lon, date_iso):
    """in-memory dict で月平均 CHL を返す（SQL クエリなし）。"""
    _preload_chl_if_needed(conn_cmems)
    lr = round(lat, 3)
    nr = round(lon, 3)
    ym = date_iso[:7]
    val = _CHL_MONTHLY_AGG.get((lr, nr, ym))
    if val is not None:
        return val
    snap_key = (lat, lon, ym)
    if snap_key in _CHL_SNAP_CACHE:
        return _CHL_SNAP_CACHE[snap_key]
    best_d2 = 0.09  # CHL は SLA より密なグリッドなので 0.3° 以内で最近傍探索
    best_v  = None
    for la, lo, v in _CHL_BY_MONTH.get(ym, []):
        d2 = (la - lat) ** 2 + (lo - lon) ** 2
        if d2 < best_d2:
            best_d2 = d2
            best_v  = v
    _CHL_SNAP_CACHE[snap_key] = best_v
    return best_v


def _preload_sla_if_needed(conn_cmems):
    """cmems_daily の SLA 非NULL行を一括ロードして dict に展開する（初回のみ）。"""
    global _SLA_LOADED, _SLA_POINT_DATE, _SLA_BY_DATE, _SLA_MONTHLY_AGG, _SLA_BY_MONTH
    if _SLA_LOADED:
        return
    if conn_cmems is None:
        _SLA_LOADED = True
        return
    t0 = time.time()
    rows = conn_cmems.execute(
        "SELECT lat, lon, date, sla FROM cmems_daily WHERE sla IS NOT NULL"
    ).fetchall()
    by_month: dict = {}
    for lat, lon, date_str, sla in rows:
        lr = round(lat, 3)
        nr = round(lon, 3)
        _SLA_POINT_DATE[(lr, nr, date_str)] = sla
        if date_str not in _SLA_BY_DATE:
            _SLA_BY_DATE[date_str] = []
        _SLA_BY_DATE[date_str].append((lr, nr, sla))
        ym = date_str[:7]
        mk = (lr, nr, ym)
        if mk not in by_month:
            by_month[mk] = []
        by_month[mk].append(sla)
    for mk, vals in by_month.items():
        avg = sum(vals) / len(vals)
        _SLA_MONTHLY_AGG[mk] = avg
        ym = mk[2]
        if ym not in _SLA_BY_MONTH:
            _SLA_BY_MONTH[ym] = []
        _SLA_BY_MONTH[ym].append((mk[0], mk[1], avg))
    elapsed = time.time() - t0
    print(f"  [CMEMS SLA preload] {len(rows):,}行 → {len(_SLA_POINT_DATE):,}point×date, "
          f"{len(_SLA_MONTHLY_AGG):,}monthly ({elapsed:.1f}s)", flush=True)
    _SLA_LOADED = True


def _get_sla_nearest(conn_cmems, lat, lon, date_iso):
    """in-memory dict で最近傍 SLA を返す（SQL クエリなし）。"""
    _preload_sla_if_needed(conn_cmems)
    lr = round(lat, 3)
    nr = round(lon, 3)
    val = _SLA_POINT_DATE.get((lr, nr, date_iso))
    if val is not None:
        return val
    # 座標スナップが合わない場合: 日付別インデックスで最近傍（~600エントリ）
    snap_key = (lat, lon, date_iso)
    if snap_key in _SLA_SNAP_CACHE:
        return _SLA_SNAP_CACHE[snap_key]
    best_d2 = 0.04
    best_v  = None
    for la, lo, v in _SLA_BY_DATE.get(date_iso, []):
        d2 = (la - lat) ** 2 + (lo - lon) ** 2
        if d2 < best_d2:
            best_d2 = d2
            best_v  = v
    _SLA_SNAP_CACHE[snap_key] = best_v
    return best_v


def _get_sla_monthly_avg(conn_cmems, lat, lon, date_iso, window=30):
    """in-memory dict で月平均 SLA を返す（SQL クエリなし）。"""
    _preload_sla_if_needed(conn_cmems)
    lr = round(lat, 3)
    nr = round(lon, 3)
    ym = date_iso[:7]
    val = _SLA_MONTHLY_AGG.get((lr, nr, ym))
    if val is not None:
        return val
    # 座標スナップが合わない場合: 月別インデックスで最近傍
    snap_key = (lat, lon, ym)
    if snap_key in _SLA_SNAP_CACHE:
        return _SLA_SNAP_CACHE[snap_key]
    best_d2 = 0.04
    best_v  = None
    for la, lo, v in _SLA_BY_MONTH.get(ym, []):
        d2 = (la - lat) ** 2 + (lo - lon) ** 2
        if d2 < best_d2:
            best_d2 = d2
            best_v  = v
    _SLA_SNAP_CACHE[snap_key] = best_v
    return best_v


def _get_sla_approach_idx(conn_cmems, date_iso):
    """黒潮接岸指数（月次）= avg_SLA(北方) - avg_SLA(南方) を返す。
    北方: lat34-36, lon138-142（関東沿岸）
    南方: lat32-34, lon136-140（黒潮大蛇行時の蓄積域）
    正値=接岸・負値=大蛇行。_SLA_BY_MONTHのin-memoryから計算（SQLなし）。
    """
    _preload_sla_if_needed(conn_cmems)
    ym = date_iso[:7]
    if ym in _SLA_APPROACH_CACHE:
        return _SLA_APPROACH_CACHE[ym]
    entries = _SLA_BY_MONTH.get(ym, [])
    north = [v for la, lo, v in entries if 34 <= la <= 36 and 138 <= lo <= 142]
    south = [v for la, lo, v in entries if 32 <= la <= 34 and 136 <= lo <= 140]
    if not north or not south:
        _SLA_APPROACH_CACHE[ym] = None
        return None
    idx = sum(north) / len(north) - sum(south) / len(south)
    _SLA_APPROACH_CACHE[ym] = idx
    return idx


def _get_kuroshio_sla_monthly(conn_cmems, date_iso):
    """黒潮回廊月次SLA絶対水準（33-37°N, 139-142°E）を返す。
    sla_approach_idxとの違い: 差分ではなく絶対値水準。
    マダイr=+0.75、カワハギr=+0.61、カンパチr=+0.54（2026/04/18分析）。
    """
    _preload_sla_if_needed(conn_cmems)
    ym = date_iso[:7]
    if ym in _KUROSHIO_SLA_MONTHLY_CACHE:
        return _KUROSHIO_SLA_MONTHLY_CACHE[ym]
    entries = _SLA_BY_MONTH.get(ym, [])
    vals = [v for la, lo, v in entries if 33 <= la <= 37 and 139 <= lo <= 142]
    result = sum(vals) / len(vals) if vals else None
    _KUROSHIO_SLA_MONTHLY_CACHE[ym] = result
    return result


def _get_sla_pelagic_monthly(conn_cmems, date_iso):
    """沖合回遊魚用月次SLA平均（34-36°N, 141-143°E）を返す。
    カツオ/キハダマグロの黒潮本流評価に使用。沿岸ポイントSLAと独立した外洋シグナル。
    """
    _preload_sla_if_needed(conn_cmems)
    ym = date_iso[:7]
    if ym in _PELAGIC_SLA_MONTHLY_CACHE:
        return _PELAGIC_SLA_MONTHLY_CACHE[ym]
    entries = _SLA_BY_MONTH.get(ym, [])
    vals = [v for la, lo, v in entries if 34 <= la <= 36 and 141 <= lo <= 143]
    result = sum(vals) / len(vals) if vals else None
    _PELAGIC_SLA_MONTHLY_CACHE[ym] = result
    return result


def _get_kuroshio_sla_delta_1m(conn_cmems, date_iso):
    """黒潮回廊月次SLA の前月差分（当月 - 前月）を返す。
    絶対水準（kuroshio_sla_monthly）と独立した「変化速度」シグナル。
    正=黒潮北上中・澄み水進行、負=黒潮南下・濁り水進行。
    """
    cur = _get_kuroshio_sla_monthly(conn_cmems, date_iso)
    if cur is None:
        return None
    try:
        y, m = int(date_iso[:4]), int(date_iso[5:7])
        pm = m - 1 or 12
        py = y if m > 1 else y - 1
        prev_iso = f"{py:04d}-{pm:02d}-15"
    except Exception:
        return None
    prev = _get_kuroshio_sla_monthly(conn_cmems, prev_iso)
    if prev is None:
        return None
    return cur - prev


_sss_nearest_cache: dict = {}


def _get_sss_nearest(conn_cmems, lat, lon, date_iso):
    """指定日・座標の近傍グリッドから SSS 非NULLの値を返す。
    get_cmems_day は最近傍1件のみなので NULL が返ることがある（SSS はCHL/SLAと独立の欠損パターン）。
    これは SSS 非NULL 行のみを対象に最近傍を取得する専用クエリ。
    """
    if conn_cmems is None:
        return None
    k = (round(lat, 4), round(lon, 4), date_iso)
    if k in _sss_nearest_cache:
        return _sss_nearest_cache[k]
    row = conn_cmems.execute(
        """SELECT sss FROM cmems_daily
           WHERE date=? AND sss IS NOT NULL
             AND ABS(lat - ?) < 0.25 AND ABS(lon - ?) < 0.25
           ORDER BY (lat - ?) * (lat - ?) + (lon - ?) * (lon - ?)
           LIMIT 1""",
        (date_iso, lat, lon, lat, lat, lon, lon),
    ).fetchone()
    v = row[0] if row else None
    _sss_nearest_cache[k] = v
    return v


def _get_sss_delta_7d(conn_cmems, lat, lon, date_iso):
    """SSS の 7日前との差分を返す。
    正=塩分上昇（黒潮水流入）、負=塩分低下（淡水・湾水流入）。
    """
    if conn_cmems is None:
        return None
    try:
        from datetime import date, timedelta
        d = date.fromisoformat(date_iso)
        d7 = (d - timedelta(days=7)).isoformat()
    except Exception:
        return None
    s_now = _get_sss_nearest(conn_cmems, lat, lon, date_iso)
    if s_now is None:
        return None
    s_prev = _get_sss_nearest(conn_cmems, lat, lon, d7)
    if s_prev is None:
        return None
    return s_now - s_prev


def _cmems_depth_nearest(conn_cmems, lat, lon, date_iso, grid_deg, cols):
    """指定グリッド解像度で最近傍の深度列を取得。なければ 0.5° フォールバック。"""
    rl = round(round(lat / grid_deg) * grid_deg, 4)
    rn = round(round(lon / grid_deg) * grid_deg, 4)
    sel = ", ".join(["depth_m"] + cols)
    rows = conn_cmems.execute(
        f"SELECT {sel} FROM cmems_depth WHERE lat=? AND lon=? AND date=? ORDER BY depth_m",
        (rl, rn, date_iso),
    ).fetchall()
    if not rows:
        rows = conn_cmems.execute(
            f"""SELECT {sel} FROM cmems_depth
               WHERE date=? AND ABS(lat-?)<0.5 AND ABS(lon-?)<0.5
               ORDER BY (lat-?)*(lat-?)+(lon-?)*(lon-?), depth_m""",
            (date_iso, lat, lon, lat, lat, lon, lon),
        ).fetchall()
    return rows


def get_cmems_depth_day(conn_cmems, lat, lon, date_iso):
    """CMEMS 深度別データ → 派生特徴量を返す（cmems_depth テーブル）。
    temp は GLORYS12 (0.083°)、do/no3 は BGC (0.25°) として別クエリで取得。
    データがない場合は空 dict（graceful skip）。
    """
    if conn_cmems is None:
        return {}

    # temp: GLORYS12 0.083° グリッド
    temp_rows = _cmems_depth_nearest(conn_cmems, lat, lon, date_iso, 0.0833, ["temp"])
    # do/no3: BGC 0.25° グリッド
    bgc_rows  = _cmems_depth_nearest(conn_cmems, lat, lon, date_iso, 0.25,   ["do", "no3"])

    if not temp_rows and not bgc_rows:
        return {}

    result = {}

    # ── do / no3（BGC行から） ──────────────────────────────────────
    if bgc_rows:
        bgc_depths = [r[0] for r in bgc_rows]
        dos  = [r[1] for r in bgc_rows]
        no3s = [r[2] for r in bgc_rows]
        # 表層（最浅）
        if dos[0]  is not None: result["do_surface"]  = dos[0]
        if no3s[0] is not None: result["no3_surface"] = no3s[0]
        # 深層（最深・有効値）
        for d, o in zip(reversed(bgc_depths), reversed(dos)):
            if o is not None:
                result["do_bottom"] = o
                break

    # ── temp（GLORYS12行から） ────────────────────────────────────
    if temp_rows:
        temp_depths = [r[0] for r in temp_rows]
        temps = [r[1] for r in temp_rows]
        for target_m, key in [(50, "temp_50m"), (100, "temp_100m"), (200, "temp_200m")]:
            best_d, best_t = None, None
            for d, t in zip(temp_depths, temps):
                if t is None:
                    continue
                if best_d is None or abs(d - target_m) < abs(best_d - target_m):
                    best_d, best_t = d, t
            if best_t is not None:
                result[key] = best_t

        # 躍層深度（temp差が最大の隣接レイヤの上側深度）
        valid_pairs = [(temp_depths[i], temps[i], temp_depths[i+1], temps[i+1])
                       for i in range(len(temp_depths)-1)
                       if temps[i] is not None and temps[i+1] is not None]
        if valid_pairs:
            best = max(valid_pairs, key=lambda x: abs(x[1] - x[3]))
            result["thermocline_depth"] = best[0]

    return result


def get_tide(conn_tide, date_iso):
    """潮汐データを返す（tide_moon.sqlite から取得）"""
    if conn_tide is None:
        return None
    row = conn_tide.execute("""
        SELECT tide_coeff, moon_age, tide_type
        FROM tide_moon WHERE date=?
    """, (date_iso,)).fetchone()
    if not row:
        return None
    tide_coeff, moon_age, tide_type = row
    # 月齢を sin/cos 変換（周期29.5日の円形統計）
    # sin: 新月0→上弦+1→満月0→下弦-1  cos: 新月+1→上弦0→満月-1→下弦0
    _phase = moon_age / 29.5 * 2 * math.pi if moon_age is not None else 0.0
    return {
        "tide_range":  tide_coeff,   # tide_coeff(0-100) を tide_range の代替として使用
        "moon_age":    moon_age,
        "moon_sin":    math.sin(_phase),   # 月周期正弦（夜釣り活性・イカ浮上と相関）
        "moon_cos":    math.cos(_phase),   # 月周期余弦（上弦/下弦の検出）
        "tide_type_n": TIDE_TYPE_MAP.get(tide_type, 2),
    }

def get_typhoon(conn_ty, date_iso):
    """台風接近データを返す（typhoon.sqlite から取得）。
    台風なし日は None を返す（相関計算から除外するため 9999 は使わない）。
    """
    if conn_ty is not None:
        row = conn_ty.execute("""
            SELECT min_dist, wind_kt
            FROM typhoon_track
            WHERE date(dt) = ?
            ORDER BY min_dist ASC
            LIMIT 1
        """, (date_iso,)).fetchone()
        if row:
            return {"typhoon_dist": row[0], "typhoon_wind": row[1]}
    return {"typhoon_dist": None, "typhoon_wind": None}


def enrich(records, ship_coords, wx_coords, conn_wx, ship_area, horizon=0, all_records=None, conn_tide=None, conn_typhoon=None, conn_cmems=None, fish=None):
    """全レコードに海況・潮汐・前週釣果を付与（horizon 日前の weather を使用）。

    all_records: 前週釣果(prev_week_cnt)の参照用に全期間レコードを渡す。
    Noneのとき records 内のみで探索。
    horizon=H のとき、prediction_date = D - H 以前の最新釣果を prev_week_cnt とする。
    H=0〜7: 先週以内の釣果 → 有効  |  H>7: 2週以上前 → FAST_FACTORS により無効化
    """
    wx_cache      = {}
    tide_cache    = {}
    typhoon_cache = {}
    cmems_cache   = {}
    result = []

    # SST勾配用の固定参照座標（起動時に1回だけ最近傍を解決）
    _grad_off_coord = nearest_coord(*SST_GRAD_OFFSHORE, wx_coords) if wx_coords else None
    _grad_in_coord  = nearest_coord(*SST_GRAD_INSHORE,  wx_coords) if wx_coords else None

    # 前週釣果の参照先（日付昇順ソート済み）
    _ref_records = sorted(all_records or records, key=lambda r: r["date"])
    # bisect 用の日付リスト（O(log n) 検索）
    _ref_dates = [r["date"] for r in _ref_records]

    for r in records:
        ship = r["ship"]
        # 座標優先順: ①レコード個別lat/lon（CSV 3段階フォールバック済み）→ ②ship_coords（保険）
        rlat, rlon = r.get("lat"), r.get("lon")
        if rlat and rlon:
            wlat, wlon = nearest_coord(rlat, rlon, wx_coords)
        elif ship in ship_coords:
            slat, slon = ship_coords[ship]
            wlat, wlon = nearest_coord(slat, slon, wx_coords)
        else:
            continue

        try:
            d = datetime.strptime(r["date"], "%Y/%m/%d")
        except ValueError:
            continue
        wx_date   = (d - timedelta(days=horizon)).strftime("%Y-%m-%d")
        tide_date = d.strftime("%Y-%m-%d")  # 潮汐は当日固定（天文計算で確定）

        # 海況（horizon 日前）── 全変数を日次集計（min/max/avg）で取得
        wk = (wlat, wlon, wx_date)
        if wk not in wx_cache:
            wx_cache[wk] = get_daily_wx(conn_wx, wlat, wlon, wx_date)
        wx = wx_cache[wk]
        if not wx:
            continue
        wx = dict(wx)  # 元キャッシュを破壊しないようコピー

        # 前日（D-1）の日次集計
        prev_date1 = (d - timedelta(days=horizon+1)).strftime("%Y-%m-%d")
        if (wlat, wlon, prev_date1) not in wx_cache:
            wx_cache[(wlat, wlon, prev_date1)] = get_daily_wx(conn_wx, wlat, wlon, prev_date1)
        dagg1 = wx_cache[(wlat, wlon, prev_date1)] or {}
        wx["precip_sum1"]      = dagg1.get("precip_sum")       # 前日合計降水量
        wx["pressure_min1"]    = dagg1.get("pressure_min")     # 前日最低気圧

        # 前々日（D-2）の日次集計
        prev_date2 = (d - timedelta(days=horizon+2)).strftime("%Y-%m-%d")
        if (wlat, wlon, prev_date2) not in wx_cache:
            wx_cache[(wlat, wlon, prev_date2)] = get_daily_wx(conn_wx, wlat, wlon, prev_date2)
        dagg2 = wx_cache[(wlat, wlon, prev_date2)] or {}
        wx["precip_sum2"]      = dagg2.get("precip_sum")       # 前々日合計降水量

        # precip_sum3〜7: 降水ラグ3〜7日（水色変化の最大影響ラグ）
        # 分析: 澄→濁4.2日, 濁→澄3.7日 → 5〜7日前降水が当日水色に最大影響
        for _lag in range(3, 8):
            _pd_lag = (d - timedelta(days=horizon + _lag)).strftime("%Y-%m-%d")
            _wk_lag = (wlat, wlon, _pd_lag)
            if _wk_lag not in wx_cache:
                wx_cache[_wk_lag] = get_daily_wx(conn_wx, wlat, wlon, _pd_lag)
            wx[f"precip_sum{_lag}"] = (wx_cache[_wk_lag] or {}).get("precip_sum")

        # pressure_delta: 当日最低気圧 - 前日最低気圧（気圧変化の方向・速度）
        p_today = wx.get("pressure_min")
        p_prev  = wx.get("pressure_min1")
        wx["pressure_delta"] = (p_today - p_prev) if (p_today and p_prev) else None

        # pressure_delta_48h: 当日最低気圧 - 2日前最低気圧（48h気圧変化）
        # swell は気圧変化の2日後に到達することが多い → 低気圧接近の早期シグナル
        p_prev2 = dagg2.get("pressure_min")
        wx["pressure_delta_48h"] = (p_today - p_prev2) if (p_today and p_prev2) else None

        # 潮汐（当日）: tide_moon.sqlite から日付ベースで取得
        tk = tide_date
        if tk not in tide_cache:
            tide_cache[tk] = get_tide(conn_tide, tide_date)
        tide = tide_cache[tk] or {}

        # tide_delta: 当日潮係数 - 前日潮係数（転換点検出: 大潮→小潮 or 小潮→大潮）
        tide_prev_date = (d - timedelta(days=horizon+1)).strftime("%Y-%m-%d")
        if tide_prev_date not in tide_cache:
            tide_cache[tide_prev_date] = get_tide(conn_tide, tide_prev_date)
        tide_prev = tide_cache[tide_prev_date] or {}
        tc_today = tide.get("tide_range")
        tc_prev  = tide_prev.get("tide_range")
        tide["tide_delta"] = (tc_today - tc_prev) if (tc_today is not None and tc_prev is not None) else None

        # temp_delta: 当日気温avg - 前日気温avg（冬の南風/急上昇シグナル）
        t_today = wx.get("temp_avg")
        t_prev  = dagg1.get("temp_avg")
        wx["temp_delta"] = (t_today - t_prev) if (t_today is not None and t_prev is not None) else None

        # wind_dir_n/e: 風向の循環補正（北南・東西成分に分解）
        # wind_dir_mode は 0〜337.5度 → cos/sin で north/east 成分へ変換
        # 北風(0°)=+1/0、南風(180°)=-1/0、東風(90°)=0/+1、西風(270°)=0/-1
        _wdeg = wx.get("wind_dir_mode")
        if _wdeg is not None:
            _wrad = math.radians(_wdeg)
            wx["wind_dir_n"] = math.cos(_wrad)   # 北=+1, 南=-1
            wx["wind_dir_e"] = math.sin(_wrad)   # 東=+1, 西=-1
        else:
            wx["wind_dir_n"] = None
            wx["wind_dir_e"] = None

        # sst_delta: 当日SST - 7日前SST（回遊アジ到来シグナル：急降下=冬アジ接近）
        prev_date7 = (d - timedelta(days=horizon+7)).strftime("%Y-%m-%d")
        if (wlat, wlon, prev_date7) not in wx_cache:
            wx_cache[(wlat, wlon, prev_date7)] = get_daily_wx(conn_wx, wlat, wlon, prev_date7)
        dagg7 = wx_cache[(wlat, wlon, prev_date7)] or {}
        sst_now  = wx.get("sst_avg")
        sst_prev7 = dagg7.get("sst_avg")
        wx["sst_delta"] = (sst_now - sst_prev7) if (sst_now is not None and sst_prev7 is not None) else None

        # sst_delta_3d: 当日SST - 3日前SST（短周期の水温変化・sst_deltaより早期シグナル）
        prev_date3 = (d - timedelta(days=horizon+3)).strftime("%Y-%m-%d")
        if (wlat, wlon, prev_date3) not in wx_cache:
            wx_cache[(wlat, wlon, prev_date3)] = get_daily_wx(conn_wx, wlat, wlon, prev_date3)
        dagg3 = wx_cache[(wlat, wlon, prev_date3)] or {}
        sst_prev3 = dagg3.get("sst_avg")
        wx["sst_delta_3d"] = (sst_now - sst_prev3) if (sst_now is not None and sst_prev3 is not None) else None

        # sst_gradient: 外房沖SST - 東京湾内SST（黒潮近接指標）
        # 正=外房が暖かい（黒潮近接）、負=東京湾が暖かい（黒潮遠い）
        # 遅い変数（SST同様）→ H=28 まで有効
        if _grad_off_coord and _grad_in_coord:
            gk_off = (_grad_off_coord[0], _grad_off_coord[1], wx_date)
            gk_in  = (_grad_in_coord[0],  _grad_in_coord[1],  wx_date)
            if gk_off not in wx_cache:
                wx_cache[gk_off] = get_daily_wx(conn_wx, _grad_off_coord[0], _grad_off_coord[1], wx_date)
            if gk_in not in wx_cache:
                wx_cache[gk_in]  = get_daily_wx(conn_wx, _grad_in_coord[0],  _grad_in_coord[1],  wx_date)
            _sst_off = (wx_cache[gk_off] or {}).get("sst_avg")
            _sst_in  = (wx_cache[gk_in]  or {}).get("sst_avg")
            wx["sst_gradient"] = (_sst_off - _sst_in) if (_sst_off is not None and _sst_in is not None) else None
        else:
            wx["sst_gradient"] = None

        # ── 前週釣果（prev_week_cnt）────────────────────────────────────────
        # prediction_date = D - horizon の時点で知っている最新の釣果を取得
        # 同船宿の直近釣果が最良の事前情報（自己相関 r=0.4〜0.5）
        pred_date_str = (d - timedelta(days=horizon)).strftime("%Y/%m/%d")
        # bisect で pred_date_str 未満の最新レコードを O(log n) で取得
        idx = bisect.bisect_left(_ref_dates, pred_date_str) - 1
        prev_cnt = None
        while idx >= 0:
            if _ref_records[idx].get("cnt_avg") is not None:
                prev_cnt = _ref_records[idx]["cnt_avg"]
                break
            idx -= 1
        wx["prev_week_cnt"] = prev_cnt

        # 台風（wx_date = D-H の台風接近距離）
        if wx_date not in typhoon_cache:
            typhoon_cache[wx_date] = get_typhoon(conn_typhoon, wx_date)

        # 水色予測スコア（water_color_daily テーブル: water_color_model.py 生成）
        # 実測水色なしコンボも補完。SLOW因子なので horizon に関わらず当日の予測値を使用。
        # wx_date ではなく tide_date（当日）を使う → 釣行当日の水色状態を知りたい
        wx["water_color_pred_n"] = _lookup_wc_pred(wlat, wlon, tide_date)

        # CMEMS データ（黒潮SSH偏差・クロロフィル・塩分・深度別）: SLOW因子 → 当日を使用
        _ck = (wlat, wlon, tide_date)
        if _ck not in cmems_cache:
            surf = get_cmems_day(conn_cmems, wlat, wlon, tide_date)
            depth = get_cmems_depth_day(conn_cmems, wlat, wlon, tide_date)
            merged = {}
            merged.update(surf)
            merged.update(depth)
            cmems_cache[_ck] = merged
        wx.update(cmems_cache[_ck])

        # ── sla_delta / chl_delta: 当日 - 7日前（黒潮変化速度シグナル）────────
        # SLOW因子なので horizon に依存せず当日基準の-7日を使用
        if conn_cmems is not None:
            _sla_now = cmems_cache[_ck].get("sla_avg")
            _chl_now = cmems_cache[_ck].get("chl_avg")
            _date7_iso = (d - timedelta(days=7)).strftime("%Y-%m-%d")
            _ck7 = (wlat, wlon, _date7_iso)
            if _ck7 not in cmems_cache:
                _s7 = get_cmems_day(conn_cmems, wlat, wlon, _date7_iso)
                _d7 = get_cmems_depth_day(conn_cmems, wlat, wlon, _date7_iso)
                _m7 = {}; _m7.update(_s7); _m7.update(_d7)
                cmems_cache[_ck7] = _m7
            _sla_7d = cmems_cache[_ck7].get("sla_avg")
            _chl_7d = cmems_cache[_ck7].get("chl_avg")
            wx["sla_delta"] = (_sla_now - _sla_7d) if (_sla_now is not None and _sla_7d is not None) else None
            wx["chl_delta"] = (_chl_now - _chl_7d) if (_chl_now is not None and _chl_7d is not None) else None

            # ── カツオ・キハダマグロ: 沖合SLA（SLA_PELAGIC_COORD）で上書き ────────
            # 船籍港（沿岸）ではなく実際の釣り場（銚子沖〜外房沖）の黒潮状態を使う
            if fish in SLA_PELAGIC_FISH:
                _sla_off = _get_sla_nearest(conn_cmems, SLA_PELAGIC_COORD[0], SLA_PELAGIC_COORD[1], tide_date)
                if _sla_off is not None:
                    wx["sla_avg"] = _sla_off

            # SLA座標: 沖合回遊魚は SLA_PELAGIC_COORD、それ以外はコンボ座標
            _sla_lat = SLA_PELAGIC_COORD[0] if fish in SLA_PELAGIC_FISH else wlat
            _sla_lon = SLA_PELAGIC_COORD[1] if fish in SLA_PELAGIC_FISH else wlon

            # ── sla_monthly / sla_lag30: SLAデータが存在する座標のみ計算 ──────────
            # sla_avg が None = この座標はSLAグリッド外 → 月次クエリも常にNULLなのでスキップ
            _sla_available = (wx.get("sla_avg") is not None) or (fish in SLA_PELAGIC_FISH)
            if _sla_available:
                wx["sla_monthly"] = _get_sla_monthly_avg(conn_cmems, _sla_lat, _sla_lon, tide_date)
                _date30_iso = (d - timedelta(days=30)).strftime("%Y-%m-%d")
                wx["sla_lag30"] = _get_sla_nearest(conn_cmems, _sla_lat, _sla_lon, _date30_iso)
            else:
                wx["sla_monthly"] = None
                wx["sla_lag30"] = None
            # ── sla_approach_idx: 黒潮接岸指数（月次・広域・座標非依存）────────────
            wx["sla_approach_idx"] = _get_sla_approach_idx(conn_cmems, tide_date)
            # ── kuroshio_sla_monthly: 黒潮回廊SLA絶対水準（全魚種向け）───────────
            wx["kuroshio_sla_monthly"] = _get_kuroshio_sla_monthly(conn_cmems, tide_date)
            # ── kuroshio_sla_delta_1m: 黒潮回廊SLA当月-前月（変化速度シグナル）─────
            wx["kuroshio_sla_delta_1m"] = _get_kuroshio_sla_delta_1m(conn_cmems, tide_date)
            # ── sla_pelagic_monthly: 沖合回遊魚用月次SLA（全魚種で計算、選択はモデル任せ）
            wx["sla_pelagic_monthly"] = _get_sla_pelagic_monthly(conn_cmems, tide_date)
            # ── sss_delta_7d: SSS 7日変化率（塩分急変＝黒潮フロント通過）──────────
            wx["sss_delta_7d"] = _get_sss_delta_7d(conn_cmems, wlat, wlon, tide_date)
            # ── chl_monthly: 当月CHL平均（ベイト密度の月次シグナル）──────────────
            _chl_available = wx.get("chl_avg") is not None
            if _chl_available:
                wx["chl_monthly"] = _get_chl_monthly_avg(conn_cmems, wlat, wlon, tide_date)
            else:
                wx["chl_monthly"] = None
        else:
            wx["sla_delta"] = wx["chl_delta"] = wx["sla_monthly"] = wx["sla_lag30"] = None
            wx["sla_approach_idx"] = None
            wx["kuroshio_sla_monthly"] = None
            wx["kuroshio_sla_delta_1m"] = None
            wx["sla_pelagic_monthly"] = None
            wx["sss_delta_7d"] = None
            wx["chl_monthly"] = None

        # ── temp_100m × 季節交互作用（深層水温の季節依存性）────────────────────
        _t100 = wx.get("temp_100m")
        _ssn  = _season_of(int(r["date"][5:7]))  # "春"/"夏"/"秋"/"冬"
        if _t100 is not None:
            wx["temp_100m_spring"] = _t100 if _ssn == "春" else 0.0
            wx["temp_100m_summer"] = _t100 if _ssn == "夏" else 0.0
            wx["temp_100m_autumn"] = _t100 if _ssn == "秋" else 0.0
            wx["temp_100m_winter"] = _t100 if _ssn == "冬" else 0.0
            wx["temp_100m_bin"] = 0 if _t100 < 8.0 else (1 if _t100 < 12.0 else 2)
        else:
            for _sfx in ("spring", "summer", "autumn", "winter"):
                wx[f"temp_100m_{_sfx}"] = None
            wx["temp_100m_bin"] = None

        # ── CMEMS 複合スコア（個別変数が弱いコンボでも複合で効く可能性）─────────
        _sla_v  = wx.get("sla_avg")
        _chl_v  = wx.get("chl_avg")
        _no3_v  = wx.get("no3_surface")
        _dob_v  = wx.get("do_bottom")
        if _sla_v is not None and _chl_v is not None:
            # sla高（黒潮近接）かつchl低（澄み水）= 黒潮コア → 正スコア
            wx["kuroshio_score"] = _sla_v - 0.5 * _chl_v
        else:
            wx["kuroshio_score"] = None
        if _chl_v is not None and _no3_v is not None:
            # chl高 + no3高 = 栄養塩豊富=ベイト環境良好
            wx["nutrient_score"] = _chl_v + 0.3 * _no3_v
        else:
            wx["nutrient_score"] = None
        if _t100 is not None and _dob_v is not None:
            # do_bottom高（底層酸素）かつtemp_100m≈10℃（深場適水温）
            wx["deepwater_score"] = _dob_v - abs(_t100 - 10.0)
        else:
            wx["deepwater_score"] = None

        rec = dict(r)
        rec.update(wx)
        rec.update(tide)
        rec.update(typhoon_cache[wx_date])

        # 潮汐×季節 交互作用（方式C: 季節×3潮群 = 12因子）
        # 潮群: 大潮(type_n==4) / 中小潮(type_n 2-3) / 長若潮(type_n==1)
        # tide_type_n 欠損時は None（相関計算から除外）
        _ttn = tide.get("tide_type_n")
        if _ttn is not None:
            _is_oshio   = 1 if _ttn == 4 else 0
            _is_chusho  = 1 if _ttn in (2, 3) else 0
            _is_chowaka = 1 if _ttn == 1 else 0
            _ssn = _season_of(int(r["date"][5:7]))
            for _grp, _flag in [("oshio", _is_oshio), ("chusho", _is_chusho), ("chowaka", _is_chowaka)]:
                rec[f"tide_grp_{_grp}_spring"] = _flag if _ssn == "春" else 0
                rec[f"tide_grp_{_grp}_summer"] = _flag if _ssn == "夏" else 0
                rec[f"tide_grp_{_grp}_autumn"] = _flag if _ssn == "秋" else 0
                rec[f"tide_grp_{_grp}_winter"] = _flag if _ssn == "冬" else 0
        else:
            for _grp in ("oshio", "chusho", "chowaka"):
                for _s in ("spring", "summer", "autumn", "winter"):
                    rec[f"tide_grp_{_grp}_{_s}"] = None

        result.append(rec)

    return result


# ═══════════════════════════════════════════════════════════════════════════
# 分析関数
# ═══════════════════════════════════════════════════════════════════════════

def section_basic(records):
    cnts = [r["cnt_avg"] for r in records if r["cnt_avg"] is not None]
    n = len(cnts)
    if not cnts:
        return ["  (釣果数データなし)"]
    m, s = mean_std(cnts)
    if m is None:
        m = sum(cnts) / len(cnts)
    if s is None:
        s = 0.0
    med = sorted(cnts)[n//2]

    cnt_mins = [r["cnt_min"] for r in records if r["cnt_min"]]
    cnt_maxs = [r["cnt_max"] for r in records if r["cnt_max"]]
    sizes    = [r["size_avg"] for r in records if r["size_avg"]]
    kgs      = [r["kg_avg"]   for r in records if r["kg_avg"]]

    lines = [
        f"  件数: {n}件 / 期間: {records[0]['date']} 〜 {records[-1]['date']}",
        f"  cnt_avg  : 平均 {m:.1f}匹  中央値 {med:.1f}  std {s:.1f}  "
        f"[{min(cnts):.0f} 〜 {max(cnts):.0f}]",
    ]
    if cnt_mins:
        lines.append(
            f"  cnt_min  : 平均 {sum(cnt_mins)/len(cnt_mins):.1f}  "
            f"cnt_max 平均 {sum(cnt_maxs)/len(cnt_maxs):.1f}"
            f"  ({len(cnt_mins)}/{n}件, {len(cnt_mins)/n*100:.0f}%)"
        )
    if sizes:
        ms, ss = mean_std(sizes)
        if ms is not None:
            ss_s = f"{ss:.1f}" if ss is not None else "-"
            lines.append(
                f"  size_avg : 平均 {ms:.1f}cm  std {ss_s}"
                f"  [{min(sizes):.0f} 〜 {max(sizes):.0f}]"
                f"  ({len(sizes)}/{n}件, {len(sizes)/n*100:.0f}%)"
            )
    if kgs:
        mk, sk = mean_std(kgs)
        if mk is not None:
            sk_s = f"{sk:.2f}" if sk is not None else "-"
            lines.append(
                f"  kg_avg   : 平均 {mk:.2f}kg  std {sk_s}"
                f"  ({len(kgs)}/{n}件, {len(kgs)/n*100:.0f}%)"
            )
    return lines

def section_decadal(records, decadal):
    if not decadal:
        return ["  (combo_decadal データなし)"]
    buckets = defaultdict(list)
    for r in records:
        if r["decade"]:
            buckets[r["decade"]].append(r["cnt_avg"])

    lines = [f"  {'旬':>4}  {'期待':>7}  {'実績':>7}  {'偏差':>7}  {'n':>4}  "]
    lines.append("  " + "-"*45)
    for dn in sorted(decadal):
        exp  = decadal[dn]["avg_cnt"]
        acts = buckets.get(dn, [])
        if not acts or not exp:
            continue
        act = sum(acts)/len(acts)
        dev = act - exp
        lines.append(f"  {dn:>4}  {exp:>7.1f}  {act:>7.1f}  {dev:>+7.1f}  {len(acts):>4}")
    return lines[:22]

def _period_key(date_str, period):
    """日付文字列 → 集計キー（week/decade/month）"""
    d = datetime.strptime(date_str, "%Y/%m/%d")
    if period == "week":
        iso = d.isocalendar()
        return f"{iso[0]}-W{iso[1]:02d}"
    elif period == "decade":
        decade = min((d.day - 1) // 10, 2)  # 0=上旬, 1=中旬, 2=下旬
        return f"{d.year}-{d.month:02d}-D{decade}"
    elif period == "month":
        return f"{d.year}-{d.month:02d}"


def aggregate_by_period(enriched_recs, period):
    """enriched records を週/旬/月単位で集計（数値フィールドの平均）"""
    buckets = defaultdict(list)
    for r in enriched_recs:
        buckets[_period_key(r["date"], period)].append(r)

    num_keys = {k for r in enriched_recs for k, v in r.items() if isinstance(v, (int, float))}

    result = []
    for key in sorted(buckets.keys()):
        recs = buckets[key]
        agg = {"date": key, "_n": len(recs)}
        for k in num_keys:
            vals = [r[k] for r in recs if r.get(k) is not None]
            agg[k] = sum(vals) / len(vals) if vals else None
        result.append(agg)
    return result


def section_corr(enriched_recs, metrics=None):
    if metrics is None:
        metrics = ["cnt_avg", "cnt_min", "cnt_max", "size_avg", "kg_avg"]
    lines = []
    all_results = {}
    for metric in metrics:
        ys = [r.get(metric) for r in enriched_recs]
        if sum(1 for y in ys if y is not None) < 10:
            continue
        sig = []
        for fac in ALL_FACTORS:
            xs = [r.get(fac) for r in enriched_recs]
            rv, pv, nn = pearson(xs, ys)
            if rv is None:
                continue
            all_results[(metric, fac)] = (rv, pv, nn)
            if abs(rv) >= 0.15 and pv < 0.10:
                sig.append((fac, rv, pv, nn))
        if not sig:
            continue
        sig.sort(key=lambda x: -abs(x[1]))
        lines.append(f"\n  [{metric}]")
        for fac, rv, pv, nn in sig[:12]:
            star = "**" if pv < 0.01 else ("*" if pv < 0.05 else " ")
            arrow = "↑" if rv > 0 else "↓"
            lines.append(
                f"    {fac:<16} r={rv:+.3f}{star}  p={pv:.3f}  n={nn}  {arrow}"
            )
    return lines or ["  (有意な相関なし)"], all_results

def section_keywords(records):
    """コメントキーワード解析。(lines, kw_data) を返す。
    kw_data: list of (category, keyword, n, avg_in, avg_out, pct_diff)
    """
    lines = []
    kw_data = []
    for cat, kws in KEYWORDS.items():
        cat_rows = []
        for kw in kws:
            hits = [r for r in records if kw in r.get("text_all","")]
            miss = [r for r in records if kw not in r.get("text_all","")]
            if len(hits) < 3 or len(miss) < 3:
                continue
            ah = sum(r["cnt_avg"] for r in hits) / len(hits)
            am = sum(r["cnt_avg"] for r in miss) / len(miss)
            pct = (ah - am) / am * 100 if am else 0
            cat_rows.append((cat, kw, len(hits), ah, am, pct))
        if not cat_rows:
            continue
        lines.append(f"\n  [{cat}]")
        for cat_, kw, nh, ah, am, pct in sorted(cat_rows, key=lambda x: -abs(x[5])):
            sign = "+" if pct >= 0 else ""
            lines.append(
                f"    「{kw}」 n={nh:>3}  {ah:.1f}匹  vs 通常 {am:.1f}匹  "
                f"({sign}{pct:.0f}%)"
            )
            kw_data.append((cat_, kw, nh, ah, am, pct))
    return (lines or ["  (有意なキーワードなし)"]), kw_data

def section_obs_corr(records):
    """観測因子（obs_fields.json role=obs_factor）の相関分析。
    予報不可だが釣果パターン把握に使う。フィールド定義は normalize/obs_fields.json を参照。
    """
    obs_factors = _get_obs_factors()
    targets = ["cnt_avg", "cnt_max", "size_avg", "kg_avg"]
    lines   = []
    fill_rates = {}
    for fac in obs_factors:
        vals = [r.get(fac) for r in records]
        n_filled = sum(1 for v in vals if v is not None)
        fill_rates[fac] = n_filled / len(records) * 100 if records else 0
    lines.append(f"  {'因子':<16} {'fill%':>5}  cnt_avg     cnt_max     size_avg    kg_avg")
    lines.append("  " + "-"*75)
    any_result = False
    for fac in obs_factors:
        fill = fill_rates[fac]
        if fill < 1.0:
            lines.append(f"  {fac:<16} {fill:>4.1f}%  (データ不足・スキップ)")
            continue
        row_parts = [f"  {fac:<16} {fill:>4.1f}%"]
        has_sig = False
        for tgt in targets:
            xs = [r.get(fac) for r in records]
            ys = [r.get(tgt) for r in records]
            r_val, p_val, nn = pearson(xs, ys)
            if r_val is None:
                row_parts.append(f"  {'—':>10}")
            else:
                star = "**" if (p_val is not None and p_val < 0.05) else ("*" if (p_val is not None and p_val < 0.10) else "  ")
                row_parts.append(f"  {r_val:+.3f}{star}(n={nn})")
                if p_val is not None and p_val < 0.10:
                    has_sig = True
        if has_sig:
            any_result = True
        lines.append("".join(row_parts))
    if not any_result:
        lines.append("  (有意な観測因子相関なし)")
    return lines

def section_points(records):
    """ポイント別集計（正規化ポイント名でグループ化）。
    季節分布・水色スコア平均を追加。固有地名(固)/相対呼称(相)を区別。
    """
    buckets = defaultdict(lambda: {"cnts": [], "raw_names": [], "seasons": [], "wc": []})
    for r in records:
        seen_norms = set()
        for field in ("point", "point2", "point3"):
            pt_raw = r.get(field, "") or ""
            if not pt_raw:
                continue
            pt_norm = _normalize_point_name(pt_raw)
            b = buckets[pt_norm]
            if field == "point" and r.get("cnt_avg") is not None:
                b["cnts"].append(r["cnt_avg"])
            b["raw_names"].append(pt_raw)
            if pt_norm not in seen_norms:
                seen_norms.add(pt_norm)
                try:
                    b["seasons"].append(_season_of(int(r["date"][5:7])))
                except Exception:
                    pass
                wc = r.get("water_color_n")
                if wc is not None:
                    b["wc"].append(wc)

    if not buckets:
        return ["  (ポイントデータなし)"]

    header = (f"  {'種':<2}  {'ポイント':<22}  {'n':>4}  {'平均':>7}  {'最大':>7}  {'最小':>7}"
              f"  {'春%':>4}{'夏%':>4}{'秋%':>4}{'冬%':>4}  {'水色':>5}")
    lines = [header, "  " + "-" * 80]

    for pt_norm, b in sorted(buckets.items(),
            key=lambda x: -(sum(x[1]["cnts"]) / len(x[1]["cnts"]) if x[1]["cnts"] else 0)):
        cnts = b["cnts"]
        if len(cnts) < 2:
            continue
        kind = "固" if not _is_航程系(pt_norm) else "相"
        rep_name = Counter(b["raw_names"]).most_common(1)[0][0]
        display = pt_norm if pt_norm != rep_name else rep_name
        avg = sum(cnts) / len(cnts)
        n_s = len(b["seasons"])
        pct = {s: round(b["seasons"].count(s) / n_s * 100) for s in ("春","夏","秋","冬")} if n_s else {s: 0 for s in ("春","夏","秋","冬")}
        wc_str = f"{sum(b['wc'])/len(b['wc']):>5.2f}" if b["wc"] else "    -"
        lines.append(
            f"  {kind:<2}  {display:<22}  {len(cnts):>4}  {avg:>7.1f}  {max(cnts):>7.0f}  {min(cnts):>7.0f}"
            f"  {pct['春']:>3}%{pct['夏']:>3}%{pct['秋']:>3}%{pct['冬']:>3}%  {wc_str}"
        )
    return lines[:22]

def _season_of(month):
    """月 → 季節（春/夏/秋/冬）"""
    if month in (3, 4, 5):  return "春"
    if month in (6, 7, 8):  return "夏"
    if month in (9, 10, 11): return "秋"
    return "冬"

def _percentile(vals, p):
    """vals（ソート済み想定なし）の p パーセンタイルを返す（線形補間・NumPy互換）。
    旧実装は int() 切り捨てのため P75 が系統的に低く出ていた（hit_rate 過大評価）。
    """
    sv = sorted(v for v in vals if v is not None)
    if not sv:
        return None
    n = len(sv)
    if n == 1:
        return sv[0]
    pos = (n - 1) * p / 100.0
    lo = int(pos)
    hi = min(lo + 1, n - 1)
    return sv[lo] + (pos - lo) * (sv[hi] - sv[lo])

def _season_thresholds(records, metric):
    """records から季節別 (p33, p67) を計算。5件未満の季節は overall で補完。"""
    by_season = {"春": [], "夏": [], "秋": [], "冬": []}
    for r in records:
        v = r.get(metric)
        m = int(r["date"][5:7])
        if v is not None:
            by_season[_season_of(m)].append(v)
    overall = [v for vs in by_season.values() for v in vs]
    ov_p33 = _percentile(overall, 33)
    ov_p67 = _percentile(overall, 67)
    result = {}
    for s, vals in by_season.items():
        if len(vals) >= 5:
            result[s] = (_percentile(vals, 33), _percentile(vals, 67))
        else:
            result[s] = (ov_p33, ov_p67)
    return result  # {season: (p33, p67)}

def _classify3(val, p33, p67):
    """val を (p33, p67) で 0=釣れない / 1=普通 / 2=釣れる に分類"""
    if val is None or p33 is None or p67 is None:
        return None
    if val >= p67: return 2
    if val >= p33: return 1
    return 0

def _prf1_multi(y_true, y_pred, target_cls):
    """target_cls を陽性として Precision / Recall / F1 を計算"""
    tp = fp = fn = 0
    for t, p in zip(y_true, y_pred):
        if t is None or p is None:
            continue
        if p == target_cls:
            if t == target_cls: tp += 1
            else:               fp += 1
        elif t == target_cls:   fn += 1
    prec = tp / (tp + fp) if (tp + fp) > 0 else None
    rec  = tp / (tp + fn) if (tp + fn) > 0 else None
    f1   = 2*prec*rec / (prec+rec) if (prec and rec) else None
    return prec, rec, f1

def _mape(preds, acts):
    pairs = [(p, a) for p, a in zip(preds, acts) if a and a > 0]
    if not pairs:
        return None
    return sum(abs(p-a)/a for p, a in pairs) / len(pairs) * 100

def _smape(preds, acts):
    """対称MAPE: 分母に予測値も混ぜる → ゼロ実績での爆発を抑制。上限200%"""
    pairs = [(p, a) for p, a in zip(preds, acts)
             if a is not None and p is not None and (p + a) > 0]
    if not pairs:
        return None
    return sum(abs(p-a) / ((p+a) / 2) for p, a in pairs) / len(pairs) * 100

def _wmape(preds, acts):
    """重み付きMAPE: 合計誤差 ÷ 合計実績 → 釣れた日の誤差を重視"""
    pairs = [(p, a) for p, a in zip(preds, acts) if a is not None and a > 0]
    if not pairs:
        return None
    total_act = sum(a for _, a in pairs)
    return sum(abs(p-a) for p, a in pairs) / total_act * 100 if total_act else None

def _rmse(preds, acts):
    """RMSE: 大外し事故の検出指標（外れ値に敏感）"""
    pairs = [(p, a) for p, a in zip(preds, acts) if a is not None and p is not None]
    if not pairs:
        return None
    return math.sqrt(sum((p - a) ** 2 for p, a in pairs) / len(pairs))

def _good_bad_acc(preds, acts, threshold):
    """良日（actual≥threshold）と不漁日（actual<threshold）の的中率を返す。
    良日的中率: 実際に良い日に予測も良日判定できた割合
    不漁的中率: 実際に悪い日に予測も不漁判定できた割合
    """
    if threshold is None or not preds:
        return None, None
    good_c = good_t = bad_c = bad_t = 0
    for p, a in zip(preds, acts):
        if a is None:
            continue
        if a >= threshold:
            good_t += 1
            if p >= threshold:
                good_c += 1
        else:
            bad_t += 1
            if p < threshold:
                bad_c += 1
    return (good_c / good_t if good_t else None,
            bad_c  / bad_t  if bad_t  else None)

def _dir_acc(preds, acts):
    dc = dt = 0
    for i in range(1, len(acts)):
        pd_ = preds[i] - preds[i-1]
        ad_ = acts[i]  - acts[i-1]
        if pd_ != 0 and ad_ != 0:
            if (pd_ > 0) == (ad_ > 0):
                dc += 1
            dt += 1
    return dc / dt if dt else None

def section_backtest_rolling(records, ship_coords, wx_coords, conn_wx, ship_area, decadal, conn_tide=None, conn_typhoon=None, fish=None, conn_cmems=None):
    """leave-one-month-out クロスバリデーション

    各月をテスト期として、それ以外の全データ（前後含む）を学習に使う。
    実運用では3年分の蓄積データをすべて使って翌日を予測するため、
    バックテストも同様に「テスト月以外の全期間」で学習するのが最も正確。
    walk-forward（過去のみ学習）に比べ、初期foldの「未熟期」バイアスが除去され、
    wMAPEが実運用精度を正しく反映する。
    ※ 気象×釣果の相関は時期によらず安定した自然法則のため、
       「未来データを学習に含む」ことのリスクは許容範囲。
    """
    MIN_TRAIN_N = 15
    MIN_TEST_N = 15   # テストセット最低件数（季節魚は年3-4ヶ月しか釣れない）
    MIN_MONTHS = 6    # バックテスト実施の最低月数。これ未満は leave-one-month-out CV が機能しない
    WAVE_CLAMP_CANDIDATES  = [1.0, 1.5, 2.0, 2.5, 3.0]

    months = sorted(set(r["date"][:7] for r in records))

    # コンボ代表座標: records から最頻 (lat, lon) を先に計算（バックテストスキップ時も使う）
    _early_modal_lat = None; _early_modal_lon = None
    _early_pairs = [(round(r.get("lat", 0) or 0, 3), round(r.get("lon", 0) or 0, 3))
                    for r in records if r.get("lat") and r.get("lon")]
    if _early_pairs:
        _early_modal_pair = max(set(_early_pairs), key=_early_pairs.count)
        _early_modal_lat, _early_modal_lon = _early_modal_pair

    if len(months) < 2:
        return ["  データ不足（最低2ヶ月必要）"], [], [], [], {}, {}, _early_modal_lat, _early_modal_lon, MAX_CMEMS_DEFAULT
    if len(months) < MIN_MONTHS:
        return [f"  バックテストスキップ（期間不足: {len(months)}ヶ月 < MIN_MONTHS={MIN_MONTHS}）"], [], [], [], {}, {}, _early_modal_lat, _early_modal_lon, MAX_CMEMS_DEFAULT

    # 全ホライズン分を一括 enrich（SQL クエリを事前に全発行してキャッシュ活用）
    all_en_by_H = {}
    for H in HORIZONS:
        all_en_by_H[H] = enrich(
            records, ship_coords, wx_coords, conn_wx, ship_area,
            horizon=H, all_records=records, conn_tide=conn_tide, conn_typhoon=conn_typhoon,
            conn_cmems=conn_cmems, fish=fish,
        )

    # CMEMS上限のコンボ別最適化（_find_best_cmemsで軽量LOO-CVを実行）
    _n_all = len([r for r in all_en_by_H.get(0, []) if r.get("cnt_avg") is not None])
    _fold_corr_init = max(0.15, 1.96 / (_n_all ** 0.5)) if _n_all > 0 else 0.20
    best_cmems = _find_best_cmems(all_en_by_H.get(0, []), months, decadal, _fold_corr_init)
    if len(months) >= 6:
        print(f"    [CMEMS最適化] best_cmems={best_cmems} (候補: 0/2/4/6)", flush=True)

    METRICS_LIST = ["cnt_avg", "cnt_min", "cnt_max", "size_avg", "kg_avg"]
    # 各月・各ホライズンの予測と実測を蓄積
    all_preds    = {met: {H: [] for H in HORIZONS} for met in METRICS_LIST}
    all_acts     = {met: {H: [] for H in HORIZONS} for met in METRICS_LIST}
    # 3分類ラベル（季節別閾値で分類）
    all_cls_pred = {met: {H: [] for H in HORIZONS} for met in METRICS_LIST}
    all_cls_true = {met: {H: [] for H in HORIZONS} for met in METRICS_LIST}
    # 季節別閾値（学習データから fold ごとに更新）
    season_thr   = {met: {} for met in METRICS_LIST}  # {met: {season: (p33,p67)}}
    # ── ベースライン予測蓄積 ───────────────────────────────────────────────────
    # BL-0: 学習データ全体平均（combo全体のナイーブ予測）
    # BL-1: 旬別平均（現モデルのbase部分のみ）
    # BL-2: H日前時点の直近最大7件平均（短期自己相関ベースライン）
    bl0_preds = {met: {H: [] for H in HORIZONS} for met in METRICS_LIST}
    bl0_acts  = {met: {H: [] for H in HORIZONS} for met in METRICS_LIST}
    bl1_preds = {met: {H: [] for H in HORIZONS} for met in METRICS_LIST}
    bl1_acts  = {met: {H: [] for H in HORIZONS} for met in METRICS_LIST}
    bl2_preds = {met: {H: [] for H in HORIZONS} for met in METRICS_LIST}
    bl2_acts  = {met: {H: [] for H in HORIZONS} for met in METRICS_LIST}
    # フォールドごとの alpha_scale を収集 → 最終パラメータには中央値を使う
    alpha_scales_by_met = {met: [] for met in METRICS_LIST}
    # フォールドごとの best_wave_clamp を収集 → 最終パラメータには中央値を使う
    wave_clamp_thr_folds: list = []
    # range_backtest 用: cnt_max/cnt_min の (pred, act) を日付キーで保存（Coverage/Winkler計算用）
    _range_by_key = {H: {} for H in HORIZONS}  # {H: {(test_month, date): {met: (pred, act)}}}
    # star_backtest 用: cnt_avg の (pred, act, decade_avg) を保存（回遊魚★評価用）
    _star_by_key  = {H: {} for H in HORIZONS}  # {H: {(test_month, date): (pred, act, base)}}
    # ratio-based予測: cnt_avg予測を cnt_max/cnt_min に転用するためのストレージ
    avg_pred_store = {H: {} for H in HORIZONS}  # {H: {date: pred_avg}}

    for test_month in months:
        # leave-one-month-out: テスト月以外の全データで学習（前後含む）
        train_en_h0 = [r for r in all_en_by_H[0] if r["date"][:7] != test_month]
        if len(train_en_h0) < MIN_TRAIN_N:
            continue

        # 季節別分類閾値（学習データのみから計算 → テストデータを汚染しない）
        for met in METRICS_LIST:
            season_thr[met] = _season_thresholds(train_en_h0, met)

        # 学習データからパラメータ推定
        hist_params_m = {}
        for fac in ALL_FACTORS:
            vals = [r.get(fac) for r in train_en_h0 if r.get(fac) is not None]
            m2, s2 = mean_std(vals)
            if m2 is not None and s2:
                hist_params_m[fac] = (m2, s2)

        train_sorted_m = sorted(train_en_h0, key=lambda r: r["date"])

        # メトリクス別 旬別ベースライン（学習データから）
        metric_decadal_m = {}
        for met in METRICS_LIST:
            _db = defaultdict(list)
            for r in train_en_h0:
                dn = r.get("decade"); val = r.get(met)
                if dn is not None and val is not None:
                    _db[dn].append(val)
            metric_decadal_m[met] = {dn: sum(v)/len(v) for dn, v in _db.items()}

        # ratio-based予測用: cnt_max/cnt_min の旬別中央値比率を学習データから計算
        # corr(actual_avg, actual_max)=0.976, ratio CV=0.18 の安定性を利用
        decadal_ratio_m = {}
        global_ratio_m  = {}
        for _rm in ("cnt_max", "cnt_min"):
            _rb: dict = defaultdict(list)
            for _r in train_en_h0:
                _av = _r.get("cnt_avg"); _val = _r.get(_rm); _dn = _r.get("decade")
                if _av and _av > 0 and _val is not None and _dn is not None:
                    _rb[_dn].append(_val / _av)
            _all = sorted(v for vs in _rb.values() for v in vs)
            global_ratio_m[_rm] = _all[len(_all)//2] if _all else (1.7 if _rm == "cnt_max" else 0.3)
            decadal_ratio_m[_rm] = {dn: sorted(vs)[len(vs)//2] for dn, vs in _rb.items()}

        # size_avg 改善 ①: ポイント×旬別サイズベースライン（コンボ内・訓練データから）
        # 同一コンボでもポイントによってサイズが大きく異なる（例: 瀬の海74cm vs 大磯沖20cm）
        _pds: dict = defaultdict(list)   # {(point, decade): [size]}
        _ds:  dict = defaultdict(list)   # {decade: [size]} フォールバック用
        for _r in train_en_h0:
            _sz = _r.get("size_avg"); _dn = _r.get("decade"); _pt = _r.get("point", "")
            if _sz is None or _dn is None: continue
            _ds[_dn].append(_sz)
            if _pt:
                _pds[(_pt, _dn)].append(_sz)
        size_global_dec  = {dn: sorted(vs)[len(vs)//2] for dn, vs in _ds.items()}
        size_point_dec   = {k: sorted(vs)[len(vs)//2] for k, vs in _pds.items() if len(vs) >= 3}

        # size_avg 改善 ②: コンボ内 cnt_avg → size_avg スロープ（OLS解析解）
        # cnt_avg が多い日ほど小型 or 大型かを訓練データから推定（魚種・船宿で符号が変わる）
        _sz_cnt_pairs = [(r.get("cnt_avg"), r.get("size_avg")) for r in train_en_h0
                         if r.get("cnt_avg") is not None and r.get("size_avg") is not None]
        if len(_sz_cnt_pairs) >= 10:
            _xm = sum(x for x, _ in _sz_cnt_pairs) / len(_sz_cnt_pairs)
            _ym = sum(y for _, y in _sz_cnt_pairs) / len(_sz_cnt_pairs)
            _xv = sum((x-_xm)**2 for x, _ in _sz_cnt_pairs)
            _cnt_size_slope = (sum((x-_xm)*(y-_ym) for x,y in _sz_cnt_pairs) / _xv
                               if _xv > 1e-9 else 0.0)
            _cnt_size_xm = _xm  # cnt_avg の訓練平均
        else:
            _cnt_size_slope = 0.0; _cnt_size_xm = 0.0

        # ── wave_clamp コンボ別HPO（学習データのみで選択・テストに適用） ────────
        # cnt_avg の wMAPE（alpha=0.5固定の簡易予測）で各候補を評価し、最良値を採用する。
        # alpha/beta は候補ごとに再OLSせず固定。選択目的の評価のため十分。
        _wc_scores = {}
        _dec_avg = metric_decadal_m.get("cnt_avg", {})
        for _wc in WAVE_CLAMP_CANDIDATES:
            # wave_clamp だけ差し替えたコピー（wave_height_avg は既にenriched済み）
            _tr = []
            for _r in train_en_h0:
                _rc = dict(_r)
                if _rc.get("wave_height_avg") is not None:
                    _rc["wave_clamp"] = min(_rc["wave_height_avg"], _wc)
                _tr.append(_rc)
            # wave_clamp の hist_params だけ再計算して hist_params_m にマージ
            _wc_vals = [_r.get("wave_clamp") for _r in _tr if _r.get("wave_clamp") is not None]
            _wc_m, _wc_s = mean_std(_wc_vals)
            if _wc_m is None or not _wc_s:
                continue
            _hp = dict(hist_params_m)
            _hp["wave_clamp"] = (_wc_m, _wc_s)
            # cnt_avg の全因子相関（wave_clamp のみ新値で計算）
            _tr_ys = [_r.get("cnt_avg") for _r in _tr]
            _met_vals = [v for v in _tr_ys if v is not None]
            _mm, _ms = mean_std(_met_vals)
            if _mm is None or not _ms:
                continue
            _fr = {}
            for _fac in ALL_FACTORS:
                _xs2 = [_r.get(_fac) for _r in _tr]
                _rv2, _, _ = pearson(_xs2, _tr_ys)
                if _rv2 is not None and abs(_rv2) >= 0.10:
                    _fr[_fac] = _rv2
            if not _fr:
                continue
            _w2 = sum(abs(v) for v in _fr.values()) or 1.0
            _preds2, _acts2 = [], []
            for _r in _tr:
                _a = _r.get("cnt_avg")
                if _a is None:
                    continue
                _dn = _r.get("decade")
                _base = _dec_avg.get(_dn, _mm)
                _nx2 = 0.0
                for _fac, _rv in _fr.items():
                    _v = _r.get(_fac)
                    if _v is None or _fac not in _hp:
                        continue
                    _fm2, _fs2 = _hp[_fac]
                    _nx2 += _rv * (_v - _fm2) / _fs2
                _pred2 = _base + (_nx2 / _w2) * _ms * 0.5
                _preds2.append(_pred2)
                _acts2.append(_a)
            _sc = _wmape(_preds2, _acts2)
            if _sc is not None:
                _wc_scores[_wc] = _sc
        fold_wc_thr = WAVE_CLAMP_THRESHOLD  # デフォルト（mini-sweep失敗時のフォールバック）
        if _wc_scores:
            _best_wc = min(_wc_scores, key=_wc_scores.get)
            fold_wc_thr = _best_wc
            wave_clamp_thr_folds.append(_best_wc)
            # hist_params_m["wave_clamp"] を正しい閾値で更新
            # → メトリクスループの正規化(z-score)がテストデータと一貫する
            _upd_vals = [min(r["wave_height_avg"], _best_wc)
                         for r in train_en_h0 if r.get("wave_height_avg") is not None]
            _um, _us = mean_std(_upd_vals)
            if _um is not None and _us:
                hist_params_m["wave_clamp"] = (_um, _us)
            # テスト fold の wave_clamp を上書き
            for H in HORIZONS:
                for _r in all_en_by_H[H]:
                    if _r["date"][:7] == test_month and _r.get("wave_height_avg") is not None:
                        _r["wave_clamp"] = min(_r["wave_height_avg"], _best_wc)
        # ───────────────────────────────────────────────────────────────────────

        # 相関閾値: 適応的閾値 max(0.15, 1.96/√n) で統計的有意な相関のみ採用
        # 旧: 固定 0.10 → n=100 でも偽相関を大量採用し過学習の主因となっていた
        # FAST_MAX_H は per-combo HPO を検証した結果、効果なし（H=0,7で±0.03pt）のため固定値を使用
        # ただし月齢が主要因子のコンボは _FAST_MAX_H_OVERRIDE で個別設定可
        _n_fold = len([r for r in train_en_h0 if r.get("cnt_avg") is not None])
        fold_corr_thr = max(0.15, 1.96 / (_n_fold ** 0.5)) if _n_fold > 0 else 0.20
        _combo_ship = records[0]["ship"] if records else ""
        fold_fast_max_h = _FAST_MAX_H_OVERRIDE.get((fish, _combo_ship), FAST_MAX_H)
        _factor_blacklist = FACTOR_BLACKLIST.get((fish, _combo_ship), set())

        # train_sorted_m の日付リスト（bisect用）
        train_dates_m = [r["date"] for r in train_sorted_m]

        for met in METRICS_LIST:
            tr_ys = [r.get(met) for r in train_en_h0]
            factor_r_m = {}
            for fac in ALL_FACTORS:
                if fac in _factor_blacklist:
                    continue
                # wave_clamp は fold_wc_thr で再計算（訓練データの相関もテストと一貫させる）
                if fac == "wave_clamp" and fold_wc_thr != WAVE_CLAMP_THRESHOLD:
                    xs = [min(r["wave_height_avg"], fold_wc_thr)
                          if r.get("wave_height_avg") is not None else None
                          for r in train_en_h0]
                else:
                    xs = [r.get(fac) for r in train_en_h0]
                rv, _, _ = pearson(xs, tr_ys)
                # BASE_FACTORSはcorr_thrスキップ（常時確保）。ただしデータがありrが計算できる場合のみ
                if rv is not None and (abs(rv) >= fold_corr_thr or fac in BASE_FACTORS):
                    factor_r_m[fac] = rv
            # TOP-K: Tier1/Tier2分割・コンボ別最適化CMEMSキャップ適用
            factor_r_m = _apply_factor_caps(factor_r_m, max_cmems=best_cmems, corr_thr=fold_corr_thr)
            if not factor_r_m:
                continue

            met_vals = [r.get(met) for r in train_en_h0 if r.get(met) is not None]
            met_mean_m, met_std_m = mean_std(met_vals)
            if met_mean_m is None or not met_std_m:
                continue

            m_dec = metric_decadal_m.get(met, {})

            # ⑦ 自己相関 r_own（前回値 → 当回値）を学習データから計算
            own_pairs = [(train_sorted_m[i-1].get(met), train_sorted_m[i].get(met))
                         for i in range(1, len(train_sorted_m))]
            own_pairs = [(x, y) for x, y in own_pairs if x is not None and y is not None]
            r_own_m, _, _ = pearson([x for x, y in own_pairs], [y for x, y in own_pairs])
            r_own_m = r_own_m if r_own_m is not None else 0.0

            # ── 案B+C: α（スケーリング）と β（BL-2ブレンド比）を学習データから OLS 推定 ──
            # pred = base + correction * α
            # pred_final = pred + β × (bl2 - pred)
            # α: OLS 解析解 α = Σ(c*y) / Σ(c²)
            # β: OLS 解析解 β = Σ(d*(act-pred)) / Σ(d²)  where d = bl2 - pred
            _w_all = sum(abs(rv) for rv in factor_r_m.values()) or 1.0
            _w_all_own = (_w_all + abs(r_own_m)) if abs(r_own_m) >= 0.10 else None
            _ols_num = 0.0; _ols_den = 0.0
            _alpha_tr = []  # (base, corr, bl2_p, act) for β 計算
            for _r in train_en_h0:
                _act = _r.get(met)
                if _act is None:
                    continue
                _dn = _r.get("decade")
                if met == "cnt_avg" and decadal and _dn in decadal:
                    _base = decadal[_dn].get("avg_cnt", met_mean_m)
                else:
                    _base = m_dec.get(_dn, met_mean_m)
                _nx = 0.0
                for fac, rv in factor_r_m.items():
                    if fac == "wave_clamp" and fold_wc_thr != WAVE_CLAMP_THRESHOLD:
                        _v = (min(_r["wave_height_avg"], fold_wc_thr)
                              if _r.get("wave_height_avg") is not None else None)
                    else:
                        _v = _r.get(fac)
                    if _v is None or fac not in hist_params_m:
                        continue
                    _fm, _fs = hist_params_m[fac]
                    _nx += rv * (_v - _fm) / _fs
                # 前レコード探索（自己相関 + BL-2 の両方に使う）
                _ridx = bisect.bisect_left(train_dates_m, _r["date"]) - 1
                _bl2_v = []; _lo = None; _bi = _ridx
                while _bi >= 0 and len(_bl2_v) < 7:
                    _v7 = train_sorted_m[_bi].get(met)
                    if _v7 is not None:
                        if _lo is None:
                            _lo = _v7
                        _bl2_v.append(_v7)
                    _bi -= 1
                if _lo is not None and _w_all_own is not None:
                    _no = r_own_m * (_lo - met_mean_m) / met_std_m
                    _corr = (_nx + _no) / _w_all_own * met_std_m
                else:
                    _corr = _nx / _w_all * met_std_m
                _bl2_p_tr = sum(_bl2_v) / len(_bl2_v) if _bl2_v else met_mean_m
                _ols_num += _corr * (_act - _base)
                _ols_den += _corr * _corr
                _alpha_tr.append((_base, _corr, _bl2_p_tr, _act))
            _alpha_ols = (_ols_num / _ols_den) if _ols_den > 1e-9 else 0.5
            # 感応度ベースのfloor: OLSが正の場合のみ適用（負=気象補正が逆に働く → 0.1のまま）
            _max_r_fold = max((abs(rv) for rv in factor_r_m.values()), default=0)
            if _alpha_ols > 0:
                _alpha_floor = max(0.1, _max_r_fold * 1.0)  # max_r=0.3→floor=0.3, 0.5→0.5
            else:
                _alpha_floor = 0.1  # OLS負 = 気象補正が逆なのでfloor不要
            alpha_scale = max(_alpha_floor, min(1.2, _alpha_ols))  # 上限 2.0→1.2（補正過大適用を防止）
            alpha_scales_by_met[met].append(alpha_scale)  # フォールドごとに収集
            # β: BL-2 ブレンド比（0〜0.5 にクリップ）
            _bt_num = 0.0; _bt_den = 0.0
            for _b, _c, _bl2t, _a in _alpha_tr:
                _mp = _b + _c * alpha_scale
                _d  = _bl2t - _mp
                _bt_num += _d * (_a - _mp)
                _bt_den += _d * _d
            # beta_bl2 上限: 0.8（BL-2が強い自己回帰コンボ向け。旧=0.5）
            # シーバス/メバル等 prev_week_cnt・月齢が主要因子でBL-2が最良予測の場合に効く
            beta_bl2 = max(0.0, min(0.8, _bt_num / _bt_den)) if _bt_den > 1e-9 else 0.0

            for H in HORIZONS:
                te_en_h = [r for r in all_en_by_H[H] if r["date"][:7] == test_month]
                usable  = {fac: rv for fac, rv in factor_r_m.items()
                           if fac in SLOW_FACTORS or H <= fold_fast_max_h}
                w_h = sum(abs(rv) for rv in usable.values()) or 1.0

                for r in te_en_h:
                    act = r.get(met)
                    if act is None:
                        continue

                    dn = r.get("decade")
                    if met == "cnt_avg" and decadal and dn in decadal:
                        base = decadal[dn].get("avg_cnt", met_mean_m)
                    elif met == "size_avg":
                        # ポイント×旬ベースライン優先、なければ旬ベースライン、なければ全体平均
                        _pt = r.get("point", "")
                        base = (size_point_dec.get((_pt, dn))
                                or size_global_dec.get(dn)
                                or met_mean_m)
                    else:
                        base = m_dec.get(dn, met_mean_m)

                    # ⑤ 予測式: rv * z（線形加重和）に修正
                    num_wx = 0.0
                    for fac, rv in usable.items():
                        val = r.get(fac)
                        if val is None or fac not in hist_params_m:
                            continue
                        fm, fs = hist_params_m[fac]
                        z = (val - fm) / fs
                        num_wx += rv * z

                    # ⑦ 自己相関項を追加（H日前の時点で知っている最新値）
                    d_obj   = datetime.strptime(r["date"], "%Y/%m/%d")
                    cutoff  = (d_obj - timedelta(days=H)).strftime("%Y/%m/%d")
                    idx     = bisect.bisect_left(train_dates_m, cutoff) - 1
                    last_own_val = None
                    while idx >= 0:
                        if train_sorted_m[idx].get(met) is not None:
                            last_own_val = train_sorted_m[idx].get(met)
                            break
                        idx -= 1

                    if last_own_val is not None and abs(r_own_m) >= 0.10:
                        own_z   = (last_own_val - met_mean_m) / met_std_m
                        num_own = r_own_m * own_z
                        w_total = w_h + abs(r_own_m)
                        pred = base + ((num_wx + num_own) / w_total) * met_std_m * alpha_scale
                    else:
                        pred = base + (num_wx / w_h) * met_std_m * alpha_scale

                    # BL-2: H日前時点の直近最大7件平均（案C ブレンド用 + 評価用を兼ねる）
                    _bl2_idx = bisect.bisect_left(train_dates_m, cutoff) - 1
                    _bl2_recent = []
                    _bi = _bl2_idx
                    while _bi >= 0 and len(_bl2_recent) < 7:
                        v = train_sorted_m[_bi].get(met)
                        if v is not None:
                            _bl2_recent.append(v)
                        _bi -= 1
                    _bl2_p = sum(_bl2_recent) / len(_bl2_recent) if _bl2_recent else met_mean_m
                    # size_avg 補正: cnt_avg_pred を追加補正因子として利用
                    # コンボ内の cnt→size スロープ（正/負どちらも）を適用
                    if met == "size_avg" and _cnt_size_slope != 0.0:
                        _cnt_p = avg_pred_store[H].get(r["date"])
                        if _cnt_p is not None:
                            pred += _cnt_size_slope * (_cnt_p - _cnt_size_xm)
                    # ratio-based override: cnt_max/cnt_min は cnt_avg予測×旬別比率で上書き
                    # 気象→cnt_max の直接相関(r≈0.15)より cnt_avg→cnt_max チェーン(r≈0.40)が優秀
                    if met in ("cnt_max", "cnt_min"):
                        _ap = avg_pred_store[H].get(r["date"])
                        _ratio = decadal_ratio_m[met].get(dn, global_ratio_m[met])
                        pred = (_ap if _ap is not None else base) * _ratio
                    # 案C: BL-2 ブレンド適用
                    pred = pred + beta_bl2 * (_bl2_p - pred)
                    # cnt_avg予測を保存（次のmet=cnt_max/cnt_min のratio計算に使用）
                    if met == "cnt_avg":
                        avg_pred_store[H][r["date"]] = pred

                    all_preds[met][H].append(pred)
                    all_acts[met][H].append(act)
                    # 3分類ラベル（季節別閾値）
                    s = _season_of(int(r["date"][5:7]))
                    p33, p67 = season_thr[met].get(s, (None, None))
                    all_cls_true[met][H].append(_classify3(act,  p33, p67))
                    all_cls_pred[met][H].append(_classify3(pred, p33, p67))
                    # ── ベースライン予測 ────────────────────────────────────────
                    # BL-0: 学習データ全体平均
                    bl0_preds[met][H].append(met_mean_m)
                    bl0_acts[met][H].append(act)
                    # BL-1: 旬別平均
                    bl1_preds[met][H].append(m_dec.get(dn, met_mean_m))
                    bl1_acts[met][H].append(act)
                    # BL-2: 評価用（上で計算済みの _bl2_p を再利用）
                    bl2_preds[met][H].append(_bl2_p)
                    bl2_acts[met][H].append(act)
                    # range_backtest 用アライメント（cnt_max/cnt_min/cnt_avg）
                    if met in ("cnt_max", "cnt_min", "cnt_avg"):
                        _rk = (test_month, r["date"])
                        if _rk not in _range_by_key[H]:
                            _range_by_key[H][_rk] = {}
                        _range_by_key[H][_rk][met] = (pred, act)
                    # star_backtest 用（cnt_avg × 回遊魚のみ）
                    if met == "cnt_avg" and fish in KAIYU_FISH:
                        _star_by_key[H][(test_month, r["date"])] = (pred, act, base)

    # 結果出力
    total_n = len(all_acts["cnt_avg"].get(0, []))
    lines = [
        f"  ローリング月次CV  全{len(months)}ヶ月  テスト総計: {total_n}件",
    ]

    METRIC_LABEL = {"cnt_avg": "Ave匹数", "cnt_min": "Min匹数",
                    "cnt_max": "Max匹数", "size_avg": "Ave型  ", "kg_avg": "Ave重量"}
    METRIC_UNIT  = {"cnt_avg": "匹", "cnt_min": "匹", "cnt_max": "匹",
                    "size_avg": "cm", "kg_avg": "kg"}
    bt_data = []

    for met in METRICS_LIST:
        label = METRIC_LABEL[met]
        unit  = METRIC_UNIT[met]
        rows  = []
        # 良日閾値: met の全実績値の中央値（学習・テスト合算 - 評価目的のみ）
        all_act_vals = sorted(
            a for a in all_acts[met].get(0, []) if a is not None
        )
        threshold = all_act_vals[len(all_act_vals) // 2] if all_act_vals else None

        for H in HORIZONS:
            ps = all_preds[met][H]; acs = all_acts[met][H]
            if len(acs) < MIN_TEST_N:  # テストセットが少なすぎるコンボは除外
                continue
            rv, _, n = pearson(ps, acs)
            if rv is None:
                continue
            mae_v         = sum(abs(p-a) for p,a in zip(ps,acs)) / len(ps)
            mape_v        = _mape(ps, acs)
            smape_v       = _smape(ps, acs)
            wmape_v       = _wmape(ps, acs)
            rmse_v        = _rmse(ps, acs)
            dacc_v        = _dir_acc(ps, acs)
            good_r, bad_r = _good_bad_acc(ps, acs, threshold)
            # 3分類 Precision/Recall/F1
            ct = all_cls_true[met][H]
            cp = all_cls_pred[met][H]
            _, good_rec2, good_f1 = _prf1_multi(ct, cp, 2)   # 釣れる
            good_prec2, _, _      = _prf1_multi(ct, cp, 2)
            bad_prec,  bad_rec, bad_f1 = _prf1_multi(ct, cp, 0)  # 釣れない
            n_valid = sum(1 for t in ct if t is not None)
            acc3 = sum(1 for t, p in zip(ct, cp)
                       if t is not None and p is not None and t == p) / n_valid if n_valid else None
            n_f    = sum(1 for fac in ALL_FACTORS
                         if fac in SLOW_FACTORS or H <= fold_fast_max_h)
            # ベースラインメトリクス（各H・各metで計算）
            def _bl_metrics(bps, bas):
                if not bps:
                    return None, None, None
                bm = sum(abs(p-a) for p,a in zip(bps,bas)) / len(bps)
                bw = _wmape(bps, bas)
                br = _rmse(bps, bas)
                return bw, bm, br
            bl0w, bl0m, bl0r = _bl_metrics(bl0_preds[met][H], bl0_acts[met][H])
            bl1w, bl1m, bl1r = _bl_metrics(bl1_preds[met][H], bl1_acts[met][H])
            bl2w, bl2m, bl2r = _bl_metrics(bl2_preds[met][H], bl2_acts[met][H])
            rows.append((H, rv, mae_v, mape_v, smape_v, wmape_v, rmse_v,
                         dacc_v, good_r, bad_r,
                         good_prec2, good_rec2, good_f1,
                         bad_prec, bad_rec, bad_f1, acc3, n, n_f,
                         bl0w, bl0m, bl0r, bl1w, bl1m, bl1r, bl2w, bl2m, bl2r))

        if not rows:
            lines.append(f"\n  ─ {label} : データ不足 ─")
            continue

        thr_s = f"{threshold:.1f}{unit}" if threshold is not None else "-"
        lines.append(f"\n  ─ {label} ─  良日閾値:{thr_s}（季節別P33/P67を使用）")
        lines.append(
            f"  {'ホライズン':>10}  {'r':>7}  {'MAE':>7}  {'RMSE':>7}  "
            f"{'wMAPE':>7}  {'sMAPE':>7}  "
            f"{'釣良F1':>7}  {'釣良Prec':>8}  {'釣良Rec':>7}  "
            f"{'不漁F1':>7}  {'3分類Acc':>8}  {'n':>4}"
        )
        lines.append("  " + "-"*108)
        for H, rv, mae, mape, smape, wmape, rmse, dacc, good_r, bad_r, \
                gprec, grec, gf1, bprec, brec, bf1, acc3, n, n_f, \
                bl0w, bl0m, bl0r, bl1w, bl1m, bl1r, bl2w, bl2m, bl2r in rows:
            lh   = "H=  0(実測)" if H == 0 else f"H={H:>3}d 前"
            star = "**" if rv >= 0.4 else ("*" if rv >= 0.2 else " ")
            rs   = f"{rmse:>6.1f}"   if rmse  is not None else "     -"
            ws   = f"{wmape:>6.1f}%" if wmape is not None else "     -"
            ss   = f"{smape:>6.1f}%" if smape is not None else "     -"
            gf   = f"{gf1:>6.1%}"   if gf1   is not None else "     -"
            gp   = f"{gprec:>7.1%}" if gprec  is not None else "      -"
            gr   = f"{grec:>6.1%}"  if grec   is not None else "     -"
            bf   = f"{bf1:>6.1%}"   if bf1    is not None else "     -"
            ac   = f"{acc3:>7.1%}"  if acc3   is not None else "      -"
            fn   = f"({n_f}/{len(ALL_FACTORS)}因子)" if n_f < len(ALL_FACTORS) else ""
            lines.append(
                f"  {lh:>12}  {rv:>+6.3f}{star}  {mae:>6.1f}{unit}  {rs}  "
                f"{ws}  {ss}  {gf}  {gp}  {gr}  {bf}  {ac}  {n:>4}  {fn}"
            )
            bt_data.append((met, H, rv, mae, mape, smape, wmape, rmse, dacc,
                            good_r, bad_r, gprec, grec, gf1,
                            bprec, brec, bf1, acc3, n, 0.0,
                            bl0w, bl0m, bl0r, bl1w, bl1m, bl1r, bl2w, bl2m, bl2r))
        # ── ベースライン比較サマリー（H=1d, H=7d）──────────────────────────
        bl_rows = {row[0]: row for row in rows}  # H → row
        lines.append(f"\n  【ベースライン比較】  wMAPE / MAE / RMSE")
        lines.append(f"  {'':>14}  {'wMAPE':>7}  {'MAE':>7}  {'RMSE':>7}   H=1d | H=7d")
        lines.append("  " + "-"*60)
        for h_label, H in [("H=1d 前", 1), ("H=7d 前", 7)]:
            row = bl_rows.get(H)
            if row is None:
                continue
            _, rv, mae, mape, smape, wmape, rmse, dacc, *_, bl0w, bl0m, bl0r, bl1w, bl1m, bl1r, bl2w, bl2m, bl2r = row
            def _fmt3(w, m, r):
                ws = f"{w:.1f}%" if w is not None else "-"
                ms = f"{m:.1f}" if m is not None else "-"
                rs = f"{r:.1f}" if r is not None else "-"
                return f"{ws:>7}  {ms:>7}  {rs:>7}"
            lines.append(f"  {'モデル':>14}  {_fmt3(wmape, mae, rmse)}   ({h_label})")
            lines.append(f"  {'BL-0 全体平均':>14}  {_fmt3(bl0w, bl0m, bl0r)}")
            lines.append(f"  {'BL-1 旬別平均':>14}  {_fmt3(bl1w, bl1m, bl1r)}")
            lines.append(f"  {'BL-2 直近7件':>14}  {_fmt3(bl2w, bl2m, bl2r)}")
            lines.append("  " + "-"*60)

    # ── range_backtest: actual_avg vs [pred_lo, pred_hi] ──────────────────────────
    # 評価軸: ユーザーは「自分の釣果（≒actual_avg）が予測レンジ内に入ったか」で判断する
    #
    # PRIMARY KPI: 約束割れ率 = actual_avg < pred_lo（期待させといてダメだった）→ 解約リスク最大
    # SECONDARY:   期待させすぎ率 = pred_hi / actual_avg > 2.5（上限が非現実的に高い）
    # Coverage:    pred_lo <= actual_avg <= pred_hi の割合（典型的ユーザーが満足）
    # ボウズ率:    actual_min=0 かつ pred_lo > hist_avg_min*0.3（ボウズが約束違反になるケース）
    # Winkler:     非対称スコア（約束割れ=3倍ペナルティ / 嬉しい誤算=0.5倍 / 範囲内=幅のみ）

    # ボウズ閾値: コンボ全体のhist_avg_minの30%（これ以下のpred_loはボウズ許容）
    _hist_min_vals = [r.get("cnt_min") for r in all_en_by_H[0] if r.get("cnt_min") is not None]
    hist_avg_min   = sum(_hist_min_vals) / len(_hist_min_vals) if _hist_min_vals else 1.0
    bowzu_threshold = hist_avg_min * 0.3

    range_bt_data = []
    lines.append("\n  ─ レンジ評価（actual_avg vs [pred_lo, pred_hi]）─")
    lines.append(
        f"  {'ホライズン':>10}  {'約束割れ%':>9}  {'期待超え%':>9}  {'Coverage':>8}  "
        f"{'ボウズ%':>7}  {'Winkler':>8}  {'n':>4}"
    )
    lines.append("  " + "-"*78)
    for H in HORIZONS:
        rows_r = []
        for _rk, d in _range_by_key[H].items():
            if "cnt_max" in d and "cnt_min" in d and "cnt_avg" in d:
                pred_hi, _       = d["cnt_max"]
                pred_lo, act_min = d["cnt_min"]
                _,       act_avg = d["cnt_avg"]
                rows_r.append((pred_hi, pred_lo, act_avg, act_min))
        if len(rows_r) < MIN_N_COMBO:
            continue
        n_r = len(rows_r)

        # PRIMARY: 約束割れ率（actual_avg < pred_lo）= 解約リスク最大
        promise_break_rate = sum(1 for ph, pl, aa, ami in rows_r if aa < pl) / n_r
        # SECONDARY: 期待させすぎ率（pred_hi / actual_avg > 2.5）
        over_expect_rate   = sum(1 for ph, pl, aa, ami in rows_r
                                 if aa > 0 and ph / aa > 2.5) / n_r
        # Coverage: actual_avg ∈ [pred_lo, pred_hi]
        coverage           = sum(1 for ph, pl, aa, ami in rows_r if pl <= aa <= ph) / n_r
        # ボウズ率: actual_min=0 かつ pred_lo が閾値より高い
        bowzu_rate         = sum(1 for ph, pl, aa, ami in rows_r
                                 if ami == 0 and pl > bowzu_threshold) / n_r
        # Winkler 非対称スコア
        def _winkler_range(pl, ph, aa):
            width = ph - pl
            if aa < pl:   return width + (pl - aa) * 3.0   # 約束割れ: 3倍ペナルティ
            elif aa > ph: return width + (aa - ph) * 0.5   # 嬉しい誤算: 0.5倍（軽い）
            else:         return width                       # 範囲内: 幅のみ
        winkler = sum(_winkler_range(pl, ph, aa) for ph, pl, aa, ami in rows_r) / n_r

        lh = "H=  0(実測)" if H == 0 else f"H={H:>3}d 前"
        lines.append(
            f"  {lh:>12}  {promise_break_rate:>8.1%}  {over_expect_rate:>8.1%}  "
            f"{coverage:>7.1%}  {bowzu_rate:>6.1%}  {winkler:>7.2f}  {n_r:>4}"
        )
        range_bt_data.append((H, promise_break_rate, over_expect_rate, coverage,
                               bowzu_rate, winkler, n_r))

    # ── star_backtest: 回遊魚★評価バックテスト ───────────────────────────────────
    # ★割り当て: コンボ固有の予測値分位数（P80/P60/P40/P20）で切る
    # → 固定比率(1.5/1.2...)より各コンボの実際の予測分布に合う
    # 良日ライン: actual の P75（中央値=1.0 問題を回避）
    def _quantile(vals, q):
        if not vals: return 0.0
        s = sorted(vals)
        idx = min(int(len(s) * q), len(s) - 1)
        return s[idx]

    def _make_star_fn(preds):
        p20 = _quantile(preds, 0.20)
        p40 = _quantile(preds, 0.40)
        p60 = _quantile(preds, 0.60)
        p80 = _quantile(preds, 0.80)
        def _fn(pred):
            if pred >= p80: return 5
            if pred >= p60: return 4
            if pred >= p40: return 3
            if pred >= p20: return 2
            return 1
        return _fn, (p20, p40, p60, p80)

    star_bt_data = []
    if fish in KAIYU_FISH:
        lines.append("\n  ─ ★チャンス評価バックテスト（回遊魚モード・分位数閾値） ─")
        lines.append(
            f"  {'ホライズン':>10}  {'★5 hit%':>9}(n)  {'★4 hit%':>9}(n)"
            f"  {'★3 hit%':>9}(n)  {'★2 hit%':>9}(n)  {'★1 hit%':>9}(n)  良日ライン"
        )
        lines.append("  " + "-"*93)
        for H in HORIZONS:
            entries = list(_star_by_key[H].values())
            if len(entries) < MIN_N_COMBO:
                continue

            # 良日ライン: actual の P75（median=1.0 問題を回避）
            acts_all = sorted(a for _, a, _ in entries if a is not None)
            if not acts_all:
                continue
            good_line = _quantile(acts_all, 0.75)
            if good_line <= 0:
                good_line = 1.0  # フォールバック
            if good_line <= 3:
                continue  # 実質釣れないコンボは★評価しない（有料ページに無意味な★を出さない）

            # 予測値分位数でコンボ固有の★閾値を決定
            preds_all = [pred for pred, _, _ in entries]
            star_fn, (p20, p40, p60, p80) = _make_star_fn(preds_all)

            # ★別に実績を分類
            by_star = {s: [] for s in range(1, 6)}
            for pred, act, _ in entries:
                by_star[star_fn(pred)].append(act)

            row_parts = []
            row_data  = {}
            for s in [5, 4, 3, 2, 1]:
                grp = by_star[s]
                if grp:
                    hr = sum(1 for a in grp if a >= good_line) / len(grp)
                    row_parts.append(f"{hr:>8.1%}({len(grp):>3})")
                    row_data[s] = (hr, len(grp))
                else:
                    row_parts.append(f"{'N/A':>8}(  0)")
                    row_data[s] = (None, 0)

            lh = "H=  0(実測)" if H == 0 else f"H={H:>3}d 前"
            lines.append(
                f"  {lh:>12}  {'  '.join(row_parts)}  {good_line:.1f}"
                f"  [閾値:{p20:.1f}/{p40:.1f}/{p60:.1f}/{p80:.1f}]"
            )

            star_bt_data.append((
                H,
                row_data[5][0], row_data[5][1],
                row_data[4][0], row_data[4][1],
                row_data[3][0], row_data[3][1],
                row_data[2][0], row_data[2][1],
                row_data[1][0], row_data[1][1],
                good_line, p20, p40, p60, p80,
            ))

    # ── 全データでの最終パラメータ確定 ──────────────────────────────────────────────
    # leave-one-month-out設計に合わせ、最終パラメータも全件で学習する。
    # 実運用では全蓄積データを使って予測するため、これが正しい設計。
    # predict_count.py の天候補正で使用する。
    wx_params_data = {}  # metric -> {factors, alpha_scale, met_mean, met_std}
    final_train = list(all_en_by_H[0])  # 全件使う（TRAIN_END廃止）

    # コンボ代表座標: 学習データの最頻 (lat, lon) ペアを使う
    # avg ではなく mode を使うことで、実際の主要釣り場座標に近づける
    _modal_lat = None; _modal_lon = None
    _coord_pairs = [(round(r.get("lat", 0) or 0, 3), round(r.get("lon", 0) or 0, 3))
                    for r in final_train if r.get("lat") and r.get("lon")]
    if _coord_pairs:
        _modal_pair = max(set(_coord_pairs), key=_coord_pairs.count)
        _modal_lat, _modal_lon = _modal_pair

    # corr_thr: 適応的閾値（CVフォールドと同じロジック）
    # fast_max_h は固定値（per-combo HPOは効果なしのため）
    _n_final = len([r for r in final_train if r.get("cnt_avg") is not None])
    best_corr_thr   = max(0.15, 1.96 / (_n_final ** 0.5)) if _n_final > 0 else 0.20
    best_fast_max_h = FAST_MAX_H

    if len(final_train) >= MIN_TRAIN_N:
        # 因子の統計（mean/std）を全学習データから計算
        final_hist_params = {}
        for fac in ALL_FACTORS:
            vals = [r.get(fac) for r in final_train if r.get(fac) is not None]
            m2, s2 = mean_std(vals)
            if m2 is not None and s2:
                final_hist_params[fac] = (m2, s2)

        # 旬別ベースライン（全学習データ）
        final_decadal_by_met = {}
        for met in METRICS_LIST:
            _db = defaultdict(list)
            for r in final_train:
                dn = r.get("decade"); val = r.get(met)
                if dn is not None and val is not None:
                    _db[dn].append(val)
            final_decadal_by_met[met] = {dn: sum(v)/len(v) for dn, v in _db.items()}

        for met in METRICS_LIST:
            final_ys = [r.get(met) for r in final_train]
            final_factor_r = {}
            for fac in ALL_FACTORS:
                if fac in _factor_blacklist:
                    continue
                xs = [r.get(fac) for r in final_train]
                rv, _, _ = pearson(xs, final_ys)
                # BASE_FACTORSはcorr_thrスキップ（常時確保）。ただしrが計算できる場合のみ
                if rv is not None and (abs(rv) >= best_corr_thr or fac in BASE_FACTORS):
                    final_factor_r[fac] = rv
            # TOP-K: Tier1/Tier2分割・コンボ別最適化CMEMSキャップ適用
            final_factor_r = _apply_factor_caps(final_factor_r, max_cmems=best_cmems, corr_thr=best_corr_thr)
            if not final_factor_r:
                continue

            met_vals = [r.get(met) for r in final_train if r.get(met) is not None]
            met_mean_f, met_std_f = mean_std(met_vals)
            if met_mean_f is None or not met_std_f:
                continue

            m_dec_f = final_decadal_by_met.get(met, {})

            # alpha_scale = ローリングCVの各フォールドで収集した値の中央値
            # 全学習データOLSより安定（フォールド間のバラつきを平均化）
            fold_alphas = alpha_scales_by_met.get(met, [])
            if fold_alphas:
                fold_alphas_s = sorted(fold_alphas)
                mid = len(fold_alphas_s) // 2
                alpha_scale_f = fold_alphas_s[mid] if len(fold_alphas_s) % 2 == 1 \
                    else (fold_alphas_s[mid-1] + fold_alphas_s[mid]) / 2
            else:
                alpha_scale_f = 0.5

            wx_params_data[met] = {
                "factors": {fac: (final_hist_params[fac][0], final_hist_params[fac][1], rv)
                            for fac, rv in final_factor_r.items() if fac in final_hist_params},
                "alpha_scale": alpha_scale_f,
                "met_mean": met_mean_f,
                "met_std": met_std_f,
            }

    # wave_clamp_thr: foldごとの best 値の中央値をコンボ確定値とする
    if wave_clamp_thr_folds:
        _s = sorted(wave_clamp_thr_folds)
        _mid = len(_s) // 2
        best_wave_clamp_thr = _s[_mid] if len(_s) % 2 == 1 else (_s[_mid-1] + _s[_mid]) / 2
    else:
        best_wave_clamp_thr = WAVE_CLAMP_THRESHOLD  # デフォルト2.0mにフォールバック
    # wx_params_data に _wave_clamp_thr を追加
    wx_params_data["_wave_clamp_thr"] = best_wave_clamp_thr

    return lines, bt_data, range_bt_data, star_bt_data, season_thr, wx_params_data, _modal_lat, _modal_lon, best_cmems


def save_params(fish, ship, corr_results):
    conn = _open_ana()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS combo_deep_params (
            fish    TEXT,
            ship    TEXT,
            factor  TEXT,
            metric  TEXT,
            r       REAL,
            p       REAL,
            n       INTEGER,
            PRIMARY KEY (fish, ship, factor, metric)
        )
    """)
    rows = [(fish, ship, fac, metric, rv, pv, nn)
            for (metric, fac), (rv, pv, nn) in corr_results.items()]
    conn.executemany(
        "INSERT OR REPLACE INTO combo_deep_params VALUES (?,?,?,?,?,?,?)", rows
    )
    conn.commit()
    conn.close()


def save_wx_params(fish, ship, wx_params_data, modal_lat=None, modal_lon=None,
                   use_fallback=False, kaiyu_promoted=False,
                   best_h0_wmape=None, best_cmems=None, reset_best=False):
    """天候補正パラメータを combo_wx_params テーブルに保存。
    predict_count.py が天候補正時に参照する。
    factor='_meta' 行: alpha_scale / met_mean / met_std / lat / lon / best_h0_wmape / best_cmems
    factor=<因子名> 行: 因子の mean / std / r
    lat/lon は学習データの最頻ポイント座標（avg ではなく mode）
    kaiyu_promoted: KAIYU_FISH で H=7 wMAPE < 60% + BL-2勝ち → 匹数予測に昇格
    Challenger model: prev best_h0_wmape より 2pt 以上改善しなければ wx_params は更新しない。
    """
    if not wx_params_data and not use_fallback:
        return
    conn = _open_ana()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS combo_wx_params (
            fish            TEXT,
            ship            TEXT,
            metric          TEXT,
            factor          TEXT,
            mean            REAL,
            std             REAL,
            r               REAL,
            alpha_scale     REAL,
            met_mean        REAL,
            met_std         REAL,
            lat             REAL,
            lon             REAL,
            updated_at      TEXT,
            use_fallback    INTEGER DEFAULT 0,
            kaiyu_promoted  INTEGER DEFAULT 0,
            best_h0_wmape   REAL,
            best_cmems      INTEGER DEFAULT 2,
            PRIMARY KEY (fish, ship, metric, factor)
        )
    """)
    # 既存テーブルへの列追加（マイグレーション）
    existing = {r[1] for r in conn.execute("PRAGMA table_info(combo_wx_params)").fetchall()}
    for col, typ in [("lat", "REAL"), ("lon", "REAL"),
                     ("use_fallback", "INTEGER"), ("kaiyu_promoted", "INTEGER"),
                     ("best_h0_wmape", "REAL"), ("best_cmems", "INTEGER")]:
        if col not in existing:
            conn.execute(f"ALTER TABLE combo_wx_params ADD COLUMN {col} {typ}")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Challenger model: 前回の best_h0_wmape と比較（use_fallback=True は常に更新）
    MIN_IMPROVEMENT = 2.0  # wMAPE 2pt 以上改善なければ更新しない
    if not reset_best and best_h0_wmape is not None and not use_fallback:
        prev_row = conn.execute(
            "SELECT best_h0_wmape FROM combo_wx_params "
            "WHERE fish=? AND ship=? AND metric='cnt_avg' AND factor='_meta'",
            (fish, ship)
        ).fetchone()
        prev_best = prev_row[0] if prev_row and prev_row[0] is not None else None
        if prev_best is not None and best_h0_wmape >= prev_best - MIN_IMPROVEMENT:
            # 却下: 既存パラメータを保持（updated_at のみ更新）
            conn.execute(
                "UPDATE combo_wx_params SET updated_at=? WHERE fish=? AND ship=?",
                (now, fish, ship)
            )
            conn.commit()
            conn.close()
            print(f"    [Challenger] スキップ: new={best_h0_wmape:.1f}% prev={prev_best:.1f}% (改善<{MIN_IMPROVEMENT}pt)", flush=True)
            return

    rows = []
    # 旧因子行を削除してからINSERT（TOP-K変更後に旧因子が残らないよう）
    conn.execute("DELETE FROM combo_wx_params WHERE fish=? AND ship=?", (fish, ship))
    wave_clamp_thr = wx_params_data.pop("_wave_clamp_thr", None)
    if wave_clamp_thr is not None:
        rows.append((fish, ship, "_combo", "_wave_clamp_thr",
                     wave_clamp_thr, None, None, None, None, None, None, None, now,
                     int(use_fallback), 0, None, None))
    # wx_params_data が空でも use_fallback=True なら cnt_avg の _meta 行だけ保存
    if not wx_params_data and use_fallback:
        rows.append((fish, ship, "cnt_avg", "_meta",
                     None, None, None, 0.0, None, None,
                     modal_lat, modal_lon, now, 1, 0, best_h0_wmape, best_cmems))
    for met, params in wx_params_data.items():
        _bwmape = best_h0_wmape if met == "cnt_avg" else None
        _bcmems = best_cmems if met == "cnt_avg" else None
        rows.append((fish, ship, met, "_meta",
                     None, None, None,
                     params["alpha_scale"], params["met_mean"], params["met_std"],
                     modal_lat, modal_lon, now, int(use_fallback), int(kaiyu_promoted),
                     _bwmape, _bcmems))
        for fac, (mean, std, r) in params["factors"].items():
            rows.append((fish, ship, met, fac, mean, std, r, None, None, None, None, None,
                         now, 0, 0, None, None))
    # 列名を明示して列順ずれを防ぐ（ALTER TABLE でカラム追加した場合の位置ズレ対策）
    conn.executemany(
        """INSERT OR REPLACE INTO combo_wx_params
           (fish, ship, metric, factor, mean, std, r,
            alpha_scale, met_mean, met_std, lat, lon, updated_at,
            use_fallback, kaiyu_promoted, best_h0_wmape, best_cmems)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        rows
    )
    conn.commit()
    conn.close()
    if best_h0_wmape is not None:
        print(f"    [Challenger] 採用: new={best_h0_wmape:.1f}% best_cmems={best_cmems}", flush=True)


def save_keywords(fish, ship, kw_data):
    """コメントキーワード解析結果を combo_keywords テーブルに保存"""
    if not kw_data:
        return
    conn = _open_ana()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS combo_keywords (
            fish        TEXT,
            ship        TEXT,
            category    TEXT,
            keyword     TEXT,
            n           INTEGER,
            avg_in      REAL,
            avg_out     REAL,
            pct_diff    REAL,
            updated_at  TEXT,
            PRIMARY KEY (fish, ship, keyword)
        )
    """)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rows = [(fish, ship, cat, kw, n, avg_in, avg_out, pct, now)
            for cat, kw, n, avg_in, avg_out, pct in kw_data]
    conn.executemany(
        "INSERT OR REPLACE INTO combo_keywords VALUES (?,?,?,?,?,?,?,?,?)", rows
    )
    conn.commit()
    conn.close()


def save_backtest(fish, ship, bt_data):
    """バックテスト結果を combo_backtest テーブルに保存"""
    if not bt_data:
        return
    conn = _open_ana()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS combo_backtest (
            fish        TEXT,
            ship        TEXT,
            metric      TEXT,
            horizon     INTEGER,
            r           REAL,
            mae         REAL,
            mape        REAL,
            smape       REAL,
            wmape       REAL,
            dir_acc     REAL,
            good_recall REAL,
            bad_recall  REAL,
            n           INTEGER,
            r_own       REAL,
            updated_at  TEXT,
            PRIMARY KEY (fish, ship, metric, horizon)
        )
    """)
    # 既存テーブルへの列追加（マイグレーション）
    existing = {r[1] for r in conn.execute("PRAGMA table_info(combo_backtest)").fetchall()}
    for col, typ in [
        ("smape","REAL"), ("wmape","REAL"),
        ("good_recall","REAL"), ("bad_recall","REAL"),
        ("good_prec","REAL"), ("good_rec","REAL"), ("good_f1","REAL"),
        ("bad_prec","REAL"),  ("bad_rec","REAL"),  ("bad_f1","REAL"),
        ("acc3","REAL"),
        ("rmse","REAL"),
        ("bl0_wmape","REAL"), ("bl0_mae","REAL"), ("bl0_rmse","REAL"),
        ("bl1_wmape","REAL"), ("bl1_mae","REAL"), ("bl1_rmse","REAL"),
        ("bl2_wmape","REAL"), ("bl2_mae","REAL"), ("bl2_rmse","REAL"),
    ]:
        if col not in existing:
            conn.execute(f"ALTER TABLE combo_backtest ADD COLUMN {col} {typ}")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rows = [
        (fish, ship, metric, H, rv, mae, mape, smape, wmape, dacc,
         good_r, bad_r, gprec, grec, gf1, bprec, brec, bf1, acc3, n, r_own, now,
         rmse, bl0w, bl0m, bl0r, bl1w, bl1m, bl1r, bl2w, bl2m, bl2r)
        for metric, H, rv, mae, mape, smape, wmape, rmse, dacc,
            good_r, bad_r, gprec, grec, gf1, bprec, brec, bf1, acc3, n, r_own,
            bl0w, bl0m, bl0r, bl1w, bl1m, bl1r, bl2w, bl2m, bl2r in bt_data
    ]
    conn.executemany("""
        INSERT OR REPLACE INTO combo_backtest
        (fish, ship, metric, horizon, r, mae, mape, smape, wmape, dir_acc,
         good_recall, bad_recall, good_prec, good_rec, good_f1,
         bad_prec, bad_rec, bad_f1, acc3, n, r_own, updated_at, rmse,
         bl0_wmape, bl0_mae, bl0_rmse,
         bl1_wmape, bl1_mae, bl1_rmse,
         bl2_wmape, bl2_mae, bl2_rmse)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, rows)
    conn.commit()
    conn.close()


def save_point_backtest(fish, ship, point, bt_data):
    """ポイント別バックテスト結果を combo_point_backtest テーブルに保存"""
    if not bt_data:
        return
    conn = _open_ana()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS combo_point_backtest (
            fish TEXT, ship TEXT, point TEXT,
            metric TEXT, horizon INTEGER,
            r REAL, mae REAL, mape REAL, smape REAL, wmape REAL,
            dir_acc REAL, n INTEGER, rmse REAL,
            bl0_wmape REAL, bl1_wmape REAL, bl2_wmape REAL,
            updated_at TEXT,
            PRIMARY KEY (fish, ship, point, metric, horizon)
        )
    """)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute("DELETE FROM combo_point_backtest WHERE fish=? AND ship=? AND point=?",
                 (fish, ship, point))
    rows = [
        (fish, ship, point, metric, H, rv, mae, mape, smape, wmape, dacc, n, rmse,
         bl0w, bl1w, bl2w, now)
        for metric, H, rv, mae, mape, smape, wmape, rmse, dacc,
            good_r, bad_r, gprec, grec, gf1, bprec, brec, bf1, acc3, n, r_own,
            bl0w, bl0m, bl0r, bl1w, bl1m, bl1r, bl2w, bl2m, bl2r in bt_data
    ]
    conn.executemany(
        "INSERT OR REPLACE INTO combo_point_backtest VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        rows
    )
    conn.commit()
    conn.close()


def save_point_wx_params(fish, ship, point, wx_params_data, modal_lat=None, modal_lon=None):
    """ポイント別気象パラメータを combo_point_wx_params テーブルに保存"""
    if not wx_params_data:
        return
    conn = _open_ana()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS combo_point_wx_params (
            fish TEXT, ship TEXT, point TEXT,
            metric TEXT, factor TEXT,
            mean REAL, std REAL, r REAL, alpha_scale REAL,
            met_mean REAL, met_std REAL, lat REAL, lon REAL,
            updated_at TEXT,
            PRIMARY KEY (fish, ship, point, metric, factor)
        )
    """)
    conn.execute("DELETE FROM combo_point_wx_params WHERE fish=? AND ship=? AND point=?",
                 (fish, ship, point))
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rows = []
    for met, params in wx_params_data.items():
        if met.startswith("_"):
            continue
        rows.append((fish, ship, point, met, "_meta",
                     None, None, None,
                     params.get("alpha_scale"), params.get("met_mean"), params.get("met_std"),
                     modal_lat, modal_lon, now))
        for fac, (mean, std, r) in params.get("factors", {}).items():
            rows.append((fish, ship, point, met, fac,
                         mean, std, r, None, None, None, None, None, now))
    if rows:
        conn.executemany(
            "INSERT OR REPLACE INTO combo_point_wx_params VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            rows
        )
    conn.commit()
    conn.close()


def save_range_backtest(fish, ship, range_bt_data):
    """レンジ評価指標を combo_range_backtest テーブルに保存
    PRIMARY KPI: 約束割れ率 = actual_avg < pred_lo（期待させといてダメだった）→ 解約リスク最大
    SECONDARY:   期待させすぎ率 = pred_hi / actual_avg > 2.5
    Coverage:    pred_lo <= actual_avg <= pred_hi の割合
    ボウズ率:    actual_min=0 かつ pred_lo > hist_avg_min*0.3
    Winkler:     非対称スコア（約束割れ=3倍ペナルティ / 嬉しい誤算=0.5倍 / 範囲内=幅のみ）
    """
    if not range_bt_data:
        return
    conn = _open_ana()

    # スキーマ変更検知：旧列(max_over_rate)があればDROPして再作成
    existing_cols = {row[1] for row in conn.execute(
        "PRAGMA table_info(combo_range_backtest)"
    ).fetchall()}
    if existing_cols and "max_over_rate" in existing_cols:
        conn.execute("DROP TABLE combo_range_backtest")
        conn.commit()  # DDL後に明示的 commit（並列実行時の一時消滅を防ぐ）

    conn.execute("""
        CREATE TABLE IF NOT EXISTS combo_range_backtest (
            fish               TEXT,
            ship               TEXT,
            horizon            INTEGER,
            promise_break_rate REAL,
            over_expect_rate   REAL,
            coverage           REAL,
            bowzu_rate         REAL,
            winkler            REAL,
            n                  INTEGER,
            updated_at         TEXT,
            PRIMARY KEY (fish, ship, horizon)
        )
    """)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rows = [
        (fish, ship, H, pbr, oer, cov, bzr, wkl, n, now)
        for H, pbr, oer, cov, bzr, wkl, n in range_bt_data
    ]
    conn.executemany("""
        INSERT OR REPLACE INTO combo_range_backtest
        (fish, ship, horizon, promise_break_rate, over_expect_rate, coverage,
         bowzu_rate, winkler, n, updated_at)
        VALUES (?,?,?,?,?,?,?,?,?,?)
    """, rows)
    conn.commit()
    conn.close()


def save_star_backtest(fish, ship, star_bt_data):
    """★チャンス評価の精度を combo_star_backtest テーブルに保存（回遊魚専用）
    hit_rateN: ★N をつけた日のうち実際に good_line(P75) 以上だった割合
    p20〜p80: 予測値の分位数閾値（コンボ固有）
    """
    if not star_bt_data:
        return
    conn = _open_ana()
    # スキーマ変更検知：旧列(median_cnt)のみでp20〜がなければ再作成
    existing = {r[1] for r in conn.execute("PRAGMA table_info(combo_star_backtest)").fetchall()}
    if existing and "p20" not in existing:
        conn.execute("DROP TABLE combo_star_backtest")
        conn.commit()  # DDL後に明示的 commit（並列実行時の一時消滅を防ぐ）
    conn.execute("""
        CREATE TABLE IF NOT EXISTS combo_star_backtest (
            fish        TEXT,
            ship        TEXT,
            horizon     INTEGER,
            hit_rate5   REAL,  n5  INTEGER,
            hit_rate4   REAL,  n4  INTEGER,
            hit_rate3   REAL,  n3  INTEGER,
            hit_rate2   REAL,  n2  INTEGER,
            hit_rate1   REAL,  n1  INTEGER,
            good_line   REAL,
            p20  REAL,  p40  REAL,  p60  REAL,  p80  REAL,
            updated_at  TEXT,
            PRIMARY KEY (fish, ship, horizon)
        )
    """)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rows = [
        (fish, ship, H,
         hr5, n5, hr4, n4, hr3, n3, hr2, n2, hr1, n1,
         gl, p20, p40, p60, p80, now)
        for H, hr5, n5, hr4, n4, hr3, n3, hr2, n2, hr1, n1,
            gl, p20, p40, p60, p80 in star_bt_data
    ]
    conn.executemany("""
        INSERT OR REPLACE INTO combo_star_backtest
        (fish, ship, horizon,
         hit_rate5, n5, hit_rate4, n4, hit_rate3, n3, hit_rate2, n2, hit_rate1, n1,
         good_line, p20, p40, p60, p80, updated_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, rows)
    conn.commit()
    conn.close()


def save_thresholds(fish, ship, season_thr_final):
    """季節別分類閾値を combo_thresholds テーブルに保存"""
    if not season_thr_final:
        return
    conn = _open_ana()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS combo_thresholds (
            fish    TEXT,
            ship    TEXT,
            metric  TEXT,
            season  TEXT,
            p33     REAL,
            p67     REAL,
            updated_at TEXT,
            PRIMARY KEY (fish, ship, metric, season)
        )
    """)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rows = []
    for met, sthr in season_thr_final.items():
        for season, (p33, p67) in sthr.items():
            if p33 is not None and p67 is not None:
                rows.append((fish, ship, met, season, p33, p67, now))
    conn.executemany(
        "INSERT OR REPLACE INTO combo_thresholds VALUES (?,?,?,?,?,?,?)", rows
    )
    conn.commit()
    conn.close()


def save_point_stats(fish, ship, records):
    """ポイント別統計を combo_point_stats テーブルに保存（MIN_N=10）。
    lat/lon は point_coords.json の直接解決のみ（フォールバック座標は混入しない）。
    """
    MIN_N = 10
    point_coords = _load_point_coords()

    buckets = defaultdict(lambda: {"cnts": [], "raw_names": [], "seasons": [], "wc": []})
    for r in records:
        pt_raw = r.get("point", "") or ""
        if not pt_raw:
            continue
        pt_norm = _normalize_point_name(pt_raw)
        pt_base = _strip_depth_suffix(pt_norm)
        b = buckets[pt_base]
        if r.get("cnt_avg") is not None:
            b["cnts"].append(r["cnt_avg"])
        b["raw_names"].append(pt_raw)
        try:
            b["seasons"].append(_season_of(int(r["date"][5:7])))
        except Exception:
            pass
        wc = r.get("water_color_n")
        if wc is not None:
            b["wc"].append(wc)

    rows = []
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for pt_base, b in buckets.items():
        cnts = b["cnts"]
        if len(cnts) < MIN_N:
            continue
        rep_raw = Counter(b["raw_names"]).most_common(1)[0][0]
        is_named = 0 if _is_航程系(pt_base) else 1
        n = len(cnts)
        n_s = len(b["seasons"])
        pct_s = b["seasons"].count("春") / n_s * 100 if n_s else None
        pct_u = b["seasons"].count("夏") / n_s * 100 if n_s else None
        pct_a = b["seasons"].count("秋") / n_s * 100 if n_s else None
        pct_w = b["seasons"].count("冬") / n_s * 100 if n_s else None
        wc_vals = b["wc"]
        wc_mean   = sum(wc_vals) / len(wc_vals) if wc_vals else None
        wc_median = _percentile(wc_vals, 50)    if wc_vals else None
        entry = (point_coords.get(rep_raw) or point_coords.get(pt_base))
        lat = entry.get("lat") if entry else None
        lon = entry.get("lon") if entry else None
        if lat is not None and lon is not None and (lat == 0 and lon == 0):
            lat = lon = None
        rows.append((
            fish, ship, rep_raw, pt_base, is_named, n,
            round(sum(cnts) / n, 3),
            _percentile(cnts, 25), _percentile(cnts, 50), _percentile(cnts, 75),
            round(pct_s, 1) if pct_s is not None else None,
            round(pct_u, 1) if pct_u is not None else None,
            round(pct_a, 1) if pct_a is not None else None,
            round(pct_w, 1) if pct_w is not None else None,
            round(wc_mean,   3) if wc_mean   is not None else None,
            round(wc_median, 3) if wc_median is not None else None,
            lat, lon, now,
        ))
    if not rows:
        return
    conn = _open_ana()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS combo_point_stats (
            fish TEXT, ship TEXT,
            point TEXT, point_normalized TEXT,
            is_named INTEGER,
            n INTEGER,
            cnt_avg_mean REAL, cnt_avg_p25 REAL, cnt_avg_median REAL, cnt_avg_p75 REAL,
            pct_spring REAL, pct_summer REAL, pct_autumn REAL, pct_winter REAL,
            water_color_n_mean REAL, water_color_n_median REAL,
            lat REAL, lon REAL, updated_at TEXT,
            PRIMARY KEY (fish, ship, point_normalized)
        )
    """)
    conn.execute("DELETE FROM combo_point_stats WHERE fish=? AND ship=?", (fish, ship))
    conn.executemany(
        "INSERT OR REPLACE INTO combo_point_stats VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        rows
    )
    conn.commit()
    conn.close()


def save_point_events(fish, ship, en0):
    """ポイント選択の行レベルイベントを combo_point_events に保存。
    将来の「どのポイントに行くか」予測モデルの学習データ。en0（enriched records）を使用。
    """
    rows = []
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for r in en0:
        pt_raw = r.get("point", "") or ""
        if not pt_raw:
            continue
        pt_norm = _strip_depth_suffix(_normalize_point_name(pt_raw))
        is_named = 0 if _is_航程系(pt_norm) else 1
        try:
            month = int(r["date"][5:7])
            season = _season_of(month)
        except Exception:
            season = None
            month = None
        rows.append((
            fish, ship, r["date"], pt_norm, is_named,
            season, month,
            r.get("wind_speed_avg"),
            r.get("wind_dir_mode"),
            r.get("wave_height_avg"),
            r.get("water_color_n"),
            r.get("water_color_pred_n"),
            r.get("sst_avg"),
            r.get("tide_type_n"),
            r.get("moon_age"),
            r.get("cnt_avg"),
            now,
        ))
    if not rows:
        return
    conn = _open_ana()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS combo_point_events (
            fish TEXT, ship TEXT, date TEXT, point_normalized TEXT,
            is_named INTEGER,
            season TEXT, month INTEGER,
            wind_speed_avg REAL, wind_dir_mode REAL,
            wave_height_avg REAL,
            water_color_n REAL, water_color_pred_n REAL,
            sst_avg REAL, tide_type_n REAL, moon_age REAL,
            cnt_avg REAL,
            updated_at TEXT,
            PRIMARY KEY (fish, ship, date, point_normalized)
        )
    """)
    conn.executemany(
        "INSERT OR REPLACE INTO combo_point_events VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        rows
    )
    conn.commit()
    conn.close()


def save_decadal(fish, ship, records):
    """deepdive 実行時に combo_decadal を直接更新する。
    season_detail.py の実行タイミングに依存せず常に最新 CSV と同期させる。
    """
    if not records:
        return
    buckets = defaultdict(lambda: {"cnt": [], "cnt_min": [], "cnt_max": [], "size": [], "kg": []})
    for r in records:
        dec = r.get("decade")
        if dec is None:
            continue
        cnt = r.get("cnt_avg")
        if not cnt or cnt <= 0:
            continue
        buckets[dec]["cnt"].append(cnt)
        cm = r.get("cnt_min"); cx = r.get("cnt_max")
        if cm is not None and cx is not None and cm < cnt and cx > cnt:
            buckets[dec]["cnt_min"].append(cm)
            buckets[dec]["cnt_max"].append(cx)
        if r.get("size_avg") is not None:
            buckets[dec]["size"].append(r["size_avg"])
        if r.get("kg_avg") is not None:
            buckets[dec]["kg"].append(r["kg_avg"])

    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    rows = []
    for dec, d in buckets.items():
        if not d["cnt"]:
            continue
        avg_cnt = sum(d["cnt"]) / len(d["cnt"])
        avg_size = sum(d["size"]) / len(d["size"]) if d["size"] else None
        avg_kg   = sum(d["kg"])   / len(d["kg"])   if d["kg"]   else None
        raw_min  = sum(d["cnt_min"]) / len(d["cnt_min"]) if len(d["cnt_min"]) >= 3 else None
        raw_max  = sum(d["cnt_max"]) / len(d["cnt_max"]) if len(d["cnt_max"]) >= 3 else None
        cnt_min  = min(raw_min, avg_cnt) if raw_min is not None else None
        cnt_max  = max(raw_max, avg_cnt) if raw_max is not None else None
        rows.append((
            fish, ship, dec, len(d["cnt"]),
            round(avg_cnt, 2),
            round(avg_size, 2) if avg_size else None,
            round(avg_kg, 3)   if avg_kg   else None,
            now,
            round(cnt_min, 2) if cnt_min else None,
            round(cnt_max, 2) if cnt_max else None,
        ))

    if not rows:
        return
    conn = _open_ana()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS combo_decadal (
            fish TEXT, ship TEXT, decade_no INTEGER,
            n INTEGER, avg_cnt REAL, avg_size REAL, avg_kg REAL,
            updated_at TEXT, avg_cnt_min REAL, avg_cnt_max REAL,
            PRIMARY KEY (fish, ship, decade_no)
        )
    """)
    for col in ("avg_cnt_min", "avg_cnt_max"):
        try:
            conn.execute(f"ALTER TABLE combo_decadal ADD COLUMN {col} REAL")
        except Exception:
            pass
    conn.execute("DELETE FROM combo_decadal WHERE fish=? AND ship=?", (fish, ship))
    conn.executemany(
        "INSERT INTO combo_decadal "
        "(fish, ship, decade_no, n, avg_cnt, avg_size, avg_kg, updated_at, avg_cnt_min, avg_cnt_max) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        rows
    )
    conn.commit()
    conn.close()


def save_combo_meta(fish, ship, records, modal_lat, modal_lon):
    """n_records / avg_cnt / lat / lon を combo_meta に保存する。
    save_insights.py 非依存で predict_count.py が必要な最低限の情報を埋める。
    既存行は UPDATE しない列（cv_pct 等）は NULL のまま残す。
    """
    if not records:
        return
    cnts = [r.get("cnt_avg") for r in records if r.get("cnt_avg") is not None]
    n_records = len(records)
    avg_cnt   = round(sum(cnts) / len(cnts), 3) if cnts else None
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = _open_ana()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS combo_meta (
            fish              TEXT,
            ship              TEXT,
            n_records         INTEGER,
            avg_cnt           REAL,
            lat               REAL,
            lon               REAL,
            updated_at        TEXT,
            cv_pct            REAL,
            seasonality_pct   REAL,
            stock_type        TEXT,
            avg_size          REAL,
            size_cv_pct       REAL,
            fish_type_tag     TEXT,
            avg_size_cm       REAL,
            PRIMARY KEY (fish, ship)
        )
    """)
    conn.execute("""
        INSERT INTO combo_meta (fish, ship, n_records, avg_cnt, lat, lon, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(fish, ship) DO UPDATE SET
            n_records  = excluded.n_records,
            avg_cnt    = excluded.avg_cnt,
            lat        = excluded.lat,
            lon        = excluded.lon,
            updated_at = excluded.updated_at
    """, (fish, ship, n_records, avg_cnt, modal_lat, modal_lon, now))
    conn.commit()
    conn.close()


# ═══════════════════════════════════════════════════════════════════════════
# ポイント別最適化
# ═══════════════════════════════════════════════════════════════════════════

def deep_dive_by_point(fish, ship):
    """N>=MIN_N_COMBO の各ポイントに対して独立した気象最適化＋バックテストを実行。
    結果を combo_point_backtest / combo_point_wx_params に保存する。
    """
    import collections as _col

    all_records = load_records(fish, ship_filter=ship)
    if not all_records:
        return

    # 乗合フィルタ（deep_dive と同じロジック）
    _noboat = [r for r in all_records if r.get("is_boat", 0) == 0]
    if len(_noboat) >= MIN_N_COMBO and len(_noboat) < len(all_records):
        all_records = _noboat

    pt_counts = _col.Counter(r.get("point", "") for r in all_records)
    viable_points = [pt for pt, n in pt_counts.most_common() if pt and n >= MIN_N_COMBO]

    if not viable_points:
        return

    print(f"  [point_opt] {fish}×{ship}: {len(viable_points)}ポイント最適化開始 {viable_points}", flush=True)

    ship_coords  = load_ship_coords()
    wx_coords    = load_wx_coords_list()
    ship_area    = load_ship_area()
    conn_wx      = sqlite3.connect(DB_WX)      if (os.path.exists(DB_WX)      and os.path.getsize(DB_WX)      > 0) else None
    conn_tide    = sqlite3.connect(DB_TIDE)    if (os.path.exists(DB_TIDE)    and os.path.getsize(DB_TIDE)    > 0) else None
    conn_typhoon = sqlite3.connect(DB_TYPHOON) if (os.path.exists(DB_TYPHOON) and os.path.getsize(DB_TYPHOON) > 0) else None
    conn_cmems   = sqlite3.connect(DB_CMEMS)   if (os.path.exists(DB_CMEMS)   and os.path.getsize(DB_CMEMS)   > 0) else None

    # 全体デカダルはベースライン流用（ポイント別サンプルが少ない場合に安定）
    decadal_global = load_decadal(fish, ship)

    for pt in viable_points:
        pt_records = [r for r in all_records if r.get("point", "") == pt]
        n = len(pt_records)
        print(f"    ポイント: {pt!r}  N={n}", flush=True)

        # ポイント固有デカダル（N>=10旬分あれば使う、足りなければ全体で補完）
        pt_decadal = _build_decadal_from_records(pt_records)
        decadal = pt_decadal if len(pt_decadal) >= 6 else decadal_global

        try:
            bt_lines, bt_data, range_bt_data, star_bt_data, season_thr, wx_params_data, modal_lat, modal_lon, best_cmems = \
                section_backtest_rolling(
                    pt_records, ship_coords, wx_coords, conn_wx, ship_area, decadal,
                    conn_tide=conn_tide, conn_typhoon=conn_typhoon,
                    fish=fish, conn_cmems=conn_cmems
                )
        except Exception as e:
            print(f"    [point_opt] ERROR {pt!r}: {e}", flush=True)
            continue

        if bt_data:
            save_point_backtest(fish, ship, pt, bt_data)
        if wx_params_data:
            save_point_wx_params(fish, ship, pt, wx_params_data, modal_lat, modal_lon)

        # H=0 cnt_avg 結果を表示
        for row in bt_data:
            if row[0] == "cnt_avg" and row[1] == 0:
                print(f"    → H=0 wMAPE={row[6]:.1f}%  r={row[2]:+.3f}  BL2={row[26]}", flush=True)
                break

    for c in [conn_wx, conn_tide, conn_typhoon, conn_cmems]:
        if c is not None:
            try:
                c.close()
            except Exception:
                pass

    print(f"  [point_opt] {fish}×{ship}: 完了", flush=True)
    _save_combo_tuning_json(fish, ship)


# ───────────────────────────────────────────────
# 実装①: 便別モデル（trip_no 軸）
# ───────────────────────────────────────────────

def save_trip_backtest(fish, ship, trip_no, bt_data):
    """便別バックテスト結果を combo_trip_backtest テーブルに保存"""
    if not bt_data:
        return
    conn = _open_ana()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS combo_trip_backtest (
            fish TEXT, ship TEXT, trip_no INTEGER,
            metric TEXT, horizon INTEGER,
            r REAL, mae REAL, mape REAL, smape REAL, wmape REAL,
            dir_acc REAL, n INTEGER, rmse REAL,
            bl0_wmape REAL, bl1_wmape REAL, bl2_wmape REAL,
            updated_at TEXT,
            PRIMARY KEY (fish, ship, trip_no, metric, horizon)
        )
    """)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute("DELETE FROM combo_trip_backtest WHERE fish=? AND ship=? AND trip_no=?",
                 (fish, ship, trip_no))
    rows = [
        (fish, ship, trip_no, metric, H, rv, mae, mape, smape, wmape, dacc, n, rmse,
         bl0w, bl1w, bl2w, now)
        for metric, H, rv, mae, mape, smape, wmape, rmse, dacc,
            good_r, bad_r, gprec, grec, gf1, bprec, brec, bf1, acc3, n, r_own,
            bl0w, bl0m, bl0r, bl1w, bl1m, bl1r, bl2w, bl2m, bl2r in bt_data
    ]
    conn.executemany(
        "INSERT OR REPLACE INTO combo_trip_backtest VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        rows
    )
    conn.commit()
    conn.close()


def save_trip_wx_params(fish, ship, trip_no, wx_params_data, modal_lat=None, modal_lon=None):
    """便別気象パラメータを combo_trip_wx_params テーブルに保存"""
    if not wx_params_data:
        return
    conn = _open_ana()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS combo_trip_wx_params (
            fish TEXT, ship TEXT, trip_no INTEGER,
            metric TEXT, factor TEXT,
            mean REAL, std REAL, r REAL, alpha_scale REAL,
            met_mean REAL, met_std REAL, lat REAL, lon REAL,
            updated_at TEXT,
            PRIMARY KEY (fish, ship, trip_no, metric, factor)
        )
    """)
    conn.execute("DELETE FROM combo_trip_wx_params WHERE fish=? AND ship=? AND trip_no=?",
                 (fish, ship, trip_no))
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rows = []
    for met, params in wx_params_data.items():
        if met.startswith("_"):
            continue
        rows.append((fish, ship, trip_no, met, "_meta",
                     None, None, None,
                     params.get("alpha_scale"), params.get("met_mean"), params.get("met_std"),
                     modal_lat, modal_lon, now))
        for fac, (mean, std, r) in params.get("factors", {}).items():
            rows.append((fish, ship, trip_no, met, fac,
                         mean, std, r, None, None, None, None, None, now))
    if rows:
        conn.executemany(
            "INSERT OR REPLACE INTO combo_trip_wx_params VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            rows
        )
    conn.commit()
    conn.close()


def deep_dive_by_trip(fish, ship):
    """N>=MIN_N_COMBO の各便番号に対して独立した気象最適化＋バックテストを実行。
    結果を combo_trip_backtest / combo_trip_wx_params に保存する。
    trip_no=0 は除外（欠損扱い）。
    """
    import collections as _col

    all_records = load_records(fish, ship_filter=ship)
    if not all_records:
        return

    # 乗合フィルタ（deep_dive と同じロジック）
    _noboat = [r for r in all_records if r.get("is_boat", 0) == 0]
    if len(_noboat) >= MIN_N_COMBO and len(_noboat) < len(all_records):
        all_records = _noboat

    trip_counts = _col.Counter(r.get("trip_no", 0) for r in all_records)
    # MIN_N_COMBO かつ MIN_MONTHS=6 以上の便のみ（月数不足は leave-one-month-out CV が機能しない）
    viable_trips = []
    for t, n in trip_counts.most_common():
        if not t or t == 0 or n < MIN_N_COMBO:
            continue
        trip_months = {r["date"][:7] for r in all_records if r.get("trip_no", 0) == t}
        if len(trip_months) < 6:
            print(f"    [trip_opt] skip {t}便: months={len(trip_months)} < 6", flush=True)
            continue
        viable_trips.append(t)

    if not viable_trips:
        return

    print(f"  [trip_opt] {fish}×{ship}: {len(viable_trips)}便最適化開始 {viable_trips}", flush=True)

    ship_coords  = load_ship_coords()
    wx_coords    = load_wx_coords_list()
    ship_area    = load_ship_area()
    conn_wx      = sqlite3.connect(DB_WX)      if (os.path.exists(DB_WX)      and os.path.getsize(DB_WX)      > 0) else None
    conn_tide    = sqlite3.connect(DB_TIDE)    if (os.path.exists(DB_TIDE)    and os.path.getsize(DB_TIDE)    > 0) else None
    conn_typhoon = sqlite3.connect(DB_TYPHOON) if (os.path.exists(DB_TYPHOON) and os.path.getsize(DB_TYPHOON) > 0) else None
    conn_cmems   = sqlite3.connect(DB_CMEMS)   if (os.path.exists(DB_CMEMS)   and os.path.getsize(DB_CMEMS)   > 0) else None

    decadal_global = load_decadal(fish, ship)

    for trip in viable_trips:
        trip_records = [r for r in all_records if r.get("trip_no", 0) == trip]
        n = len(trip_records)
        print(f"    便番号: {trip}便  N={n}", flush=True)

        pt_decadal = _build_decadal_from_records(trip_records)
        decadal = pt_decadal if len(pt_decadal) >= 6 else decadal_global

        try:
            bt_lines, bt_data, range_bt_data, star_bt_data, season_thr, wx_params_data, modal_lat, modal_lon, best_cmems = \
                section_backtest_rolling(
                    trip_records, ship_coords, wx_coords, conn_wx, ship_area, decadal,
                    conn_tide=conn_tide, conn_typhoon=conn_typhoon,
                    fish=fish, conn_cmems=conn_cmems
                )
        except Exception as e:
            print(f"    [trip_opt] ERROR {trip}便: {e}", flush=True)
            continue

        if bt_data:
            save_trip_backtest(fish, ship, trip, bt_data)
        if wx_params_data:
            save_trip_wx_params(fish, ship, trip, wx_params_data, modal_lat, modal_lon)

        for row in bt_data:
            if row[0] == "cnt_avg" and row[1] == 0:
                print(f"    → H=0 wMAPE={row[6]:.1f}%  r={row[2]:+.3f}  BL2={row[26]}", flush=True)
                break

    for c in [conn_wx, conn_tide, conn_typhoon, conn_cmems]:
        if c is not None:
            try:
                c.close()
            except Exception:
                pass

    print(f"  [trip_opt] {fish}×{ship}: 完了", flush=True)


# ───────────────────────────────────────────────
# 実装②: ポイント×水深帯複合モデル（point_depth_key 軸）
# ───────────────────────────────────────────────

def save_point_depth_backtest(fish, ship, key, bt_data):
    """ポイント×水深帯バックテスト結果を combo_point_depth_backtest テーブルに保存"""
    if not bt_data:
        return
    conn = _open_ana()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS combo_point_depth_backtest (
            fish TEXT, ship TEXT, point_depth_key TEXT,
            metric TEXT, horizon INTEGER,
            r REAL, mae REAL, mape REAL, smape REAL, wmape REAL,
            dir_acc REAL, n INTEGER, rmse REAL,
            bl0_wmape REAL, bl1_wmape REAL, bl2_wmape REAL,
            updated_at TEXT,
            PRIMARY KEY (fish, ship, point_depth_key, metric, horizon)
        )
    """)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        "DELETE FROM combo_point_depth_backtest WHERE fish=? AND ship=? AND point_depth_key=?",
        (fish, ship, key)
    )
    rows = [
        (fish, ship, key, metric, H, rv, mae, mape, smape, wmape, dacc, n, rmse,
         bl0w, bl1w, bl2w, now)
        for metric, H, rv, mae, mape, smape, wmape, rmse, dacc,
            good_r, bad_r, gprec, grec, gf1, bprec, brec, bf1, acc3, n, r_own,
            bl0w, bl0m, bl0r, bl1w, bl1m, bl1r, bl2w, bl2m, bl2r in bt_data
    ]
    conn.executemany(
        "INSERT OR REPLACE INTO combo_point_depth_backtest VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        rows
    )
    conn.commit()
    conn.close()


def save_point_depth_wx_params(fish, ship, key, wx_params_data, modal_lat=None, modal_lon=None):
    """ポイント×水深帯気象パラメータを combo_point_depth_wx_params テーブルに保存"""
    if not wx_params_data:
        return
    conn = _open_ana()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS combo_point_depth_wx_params (
            fish TEXT, ship TEXT, point_depth_key TEXT,
            metric TEXT, factor TEXT,
            mean REAL, std REAL, r REAL, alpha_scale REAL,
            met_mean REAL, met_std REAL, lat REAL, lon REAL,
            updated_at TEXT,
            PRIMARY KEY (fish, ship, point_depth_key, metric, factor)
        )
    """)
    conn.execute(
        "DELETE FROM combo_point_depth_wx_params WHERE fish=? AND ship=? AND point_depth_key=?",
        (fish, ship, key)
    )
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rows = []
    for met, params in wx_params_data.items():
        if met.startswith("_"):
            continue
        rows.append((fish, ship, key, met, "_meta",
                     None, None, None,
                     params.get("alpha_scale"), params.get("met_mean"), params.get("met_std"),
                     modal_lat, modal_lon, now))
        for fac, (mean, std, r) in params.get("factors", {}).items():
            rows.append((fish, ship, key, met, fac,
                         mean, std, r, None, None, None, None, None, now))
    if rows:
        conn.executemany(
            "INSERT OR REPLACE INTO combo_point_depth_wx_params VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            rows
        )
    conn.commit()
    conn.close()


def deep_dive_by_point_depth(fish, ship):
    """N>=MIN_N_COMBO の各ポイント×水深帯キーに対して独立した気象最適化＋バックテストを実行。
    結果を combo_point_depth_backtest / combo_point_depth_wx_params に保存する。
    """
    import collections as _col

    all_records = load_records(fish, ship_filter=ship)
    if not all_records:
        return

    # 乗合フィルタ（deep_dive と同じロジック）
    _noboat = [r for r in all_records if r.get("is_boat", 0) == 0]
    if len(_noboat) >= MIN_N_COMBO and len(_noboat) < len(all_records):
        all_records = _noboat

    pd_counts = _col.Counter(r.get("point_depth_key", "") for r in all_records)
    viable_keys = [k for k, n in pd_counts.most_common() if k and n >= MIN_N_COMBO]

    if not viable_keys:
        return

    print(f"  [point_depth_opt] {fish}×{ship}: {len(viable_keys)}キー最適化開始 {viable_keys}", flush=True)

    ship_coords  = load_ship_coords()
    wx_coords    = load_wx_coords_list()
    ship_area    = load_ship_area()
    conn_wx      = sqlite3.connect(DB_WX)      if (os.path.exists(DB_WX)      and os.path.getsize(DB_WX)      > 0) else None
    conn_tide    = sqlite3.connect(DB_TIDE)    if (os.path.exists(DB_TIDE)    and os.path.getsize(DB_TIDE)    > 0) else None
    conn_typhoon = sqlite3.connect(DB_TYPHOON) if (os.path.exists(DB_TYPHOON) and os.path.getsize(DB_TYPHOON) > 0) else None
    conn_cmems   = sqlite3.connect(DB_CMEMS)   if (os.path.exists(DB_CMEMS)   and os.path.getsize(DB_CMEMS)   > 0) else None

    decadal_global = load_decadal(fish, ship)

    for key in viable_keys:
        key_records = [r for r in all_records if r.get("point_depth_key", "") == key]
        n = len(key_records)
        print(f"    キー: {key!r}  N={n}", flush=True)

        pt_decadal = _build_decadal_from_records(key_records)
        decadal = pt_decadal if len(pt_decadal) >= 6 else decadal_global

        try:
            bt_lines, bt_data, range_bt_data, star_bt_data, season_thr, wx_params_data, modal_lat, modal_lon, best_cmems = \
                section_backtest_rolling(
                    key_records, ship_coords, wx_coords, conn_wx, ship_area, decadal,
                    conn_tide=conn_tide, conn_typhoon=conn_typhoon,
                    fish=fish, conn_cmems=conn_cmems
                )
        except Exception as e:
            print(f"    [point_depth_opt] ERROR {key!r}: {e}", flush=True)
            continue

        if bt_data:
            save_point_depth_backtest(fish, ship, key, bt_data)
        if wx_params_data:
            save_point_depth_wx_params(fish, ship, key, wx_params_data, modal_lat, modal_lon)

        for row in bt_data:
            if row[0] == "cnt_avg" and row[1] == 0:
                print(f"    → H=0 wMAPE={row[6]:.1f}%  r={row[2]:+.3f}  BL2={row[26]}", flush=True)
                break

    for c in [conn_wx, conn_tide, conn_typhoon, conn_cmems]:
        if c is not None:
            try:
                c.close()
            except Exception:
                pass

    print(f"  [point_depth_opt] {fish}×{ship}: 完了", flush=True)


# ───────────────────────────────────────────────
# 実装③: 水色セグメントモデル（water_color_cat 軸）
# ───────────────────────────────────────────────

def save_water_color_backtest(fish, ship, wc_cat, bt_data):
    """水色カテゴリ別バックテスト結果を combo_water_color_backtest テーブルに保存"""
    if not bt_data:
        return
    conn = _open_ana()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS combo_water_color_backtest (
            fish TEXT, ship TEXT, water_color_cat TEXT,
            metric TEXT, horizon INTEGER,
            r REAL, mae REAL, mape REAL, smape REAL, wmape REAL,
            dir_acc REAL, n INTEGER, rmse REAL,
            bl0_wmape REAL, bl1_wmape REAL, bl2_wmape REAL,
            updated_at TEXT,
            PRIMARY KEY (fish, ship, water_color_cat, metric, horizon)
        )
    """)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        "DELETE FROM combo_water_color_backtest WHERE fish=? AND ship=? AND water_color_cat=?",
        (fish, ship, wc_cat)
    )
    rows = [
        (fish, ship, wc_cat, metric, H, rv, mae, mape, smape, wmape, dacc, n, rmse,
         bl0w, bl1w, bl2w, now)
        for metric, H, rv, mae, mape, smape, wmape, rmse, dacc,
            good_r, bad_r, gprec, grec, gf1, bprec, brec, bf1, acc3, n, r_own,
            bl0w, bl0m, bl0r, bl1w, bl1m, bl1r, bl2w, bl2m, bl2r in bt_data
    ]
    conn.executemany(
        "INSERT OR REPLACE INTO combo_water_color_backtest VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        rows
    )
    conn.commit()
    conn.close()


def save_water_color_wx_params(fish, ship, wc_cat, wx_params_data, modal_lat=None, modal_lon=None):
    """水色カテゴリ別気象パラメータを combo_water_color_wx_params テーブルに保存"""
    if not wx_params_data:
        return
    conn = _open_ana()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS combo_water_color_wx_params (
            fish TEXT, ship TEXT, water_color_cat TEXT,
            metric TEXT, factor TEXT,
            mean REAL, std REAL, r REAL, alpha_scale REAL,
            met_mean REAL, met_std REAL, lat REAL, lon REAL,
            updated_at TEXT,
            PRIMARY KEY (fish, ship, water_color_cat, metric, factor)
        )
    """)
    conn.execute(
        "DELETE FROM combo_water_color_wx_params WHERE fish=? AND ship=? AND water_color_cat=?",
        (fish, ship, wc_cat)
    )
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rows = []
    for met, params in wx_params_data.items():
        if met.startswith("_"):
            continue
        rows.append((fish, ship, wc_cat, met, "_meta",
                     None, None, None,
                     params.get("alpha_scale"), params.get("met_mean"), params.get("met_std"),
                     modal_lat, modal_lon, now))
        for fac, (mean, std, r) in params.get("factors", {}).items():
            rows.append((fish, ship, wc_cat, met, fac,
                         mean, std, r, None, None, None, None, None, now))
    if rows:
        conn.executemany(
            "INSERT OR REPLACE INTO combo_water_color_wx_params VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            rows
        )
    conn.commit()
    conn.close()


def deep_dive_by_water_color(fish, ship):
    """澄み / 濁り の各水色カテゴリに対して独立した気象最適化＋バックテストを実行。
    water_color_pred_n >= 0.3 → 澄み / <= -0.3 → 濁り。
    両カテゴリとも N>=MIN_N_COMBO かつ MIN_MONTHS>=6 が必要。
    結果を combo_water_color_backtest / combo_water_color_wx_params に保存する。
    """
    import collections as _col

    all_records = load_records(fish, ship_filter=ship)
    if not all_records:
        return

    _noboat = [r for r in all_records if r.get("is_boat", 0) == 0]
    if len(_noboat) >= MIN_N_COMBO and len(_noboat) < len(all_records):
        all_records = _noboat

    wc_counts = _col.Counter(r.get("water_color_cat", "") for r in all_records)
    viable_cats = []
    for cat, n in wc_counts.most_common():
        if not cat or n < MIN_N_COMBO:
            continue
        cat_months = {r["date"][:7] for r in all_records if r.get("water_color_cat", "") == cat}
        if len(cat_months) < 6:
            print(f"    [wc_opt] skip {cat}: months={len(cat_months)} < 6", flush=True)
            continue
        viable_cats.append(cat)

    if not viable_cats:
        return

    print(f"  [wc_opt] {fish}×{ship}: {len(viable_cats)}カテゴリ最適化開始 {viable_cats}", flush=True)

    ship_coords  = load_ship_coords()
    wx_coords    = load_wx_coords_list()
    ship_area    = load_ship_area()
    conn_wx      = sqlite3.connect(DB_WX)      if (os.path.exists(DB_WX)      and os.path.getsize(DB_WX)      > 0) else None
    conn_tide    = sqlite3.connect(DB_TIDE)    if (os.path.exists(DB_TIDE)    and os.path.getsize(DB_TIDE)    > 0) else None
    conn_typhoon = sqlite3.connect(DB_TYPHOON) if (os.path.exists(DB_TYPHOON) and os.path.getsize(DB_TYPHOON) > 0) else None
    conn_cmems   = sqlite3.connect(DB_CMEMS)   if (os.path.exists(DB_CMEMS)   and os.path.getsize(DB_CMEMS)   > 0) else None

    decadal_global = load_decadal(fish, ship)

    for cat in viable_cats:
        cat_records = [r for r in all_records if r.get("water_color_cat", "") == cat]
        n = len(cat_records)
        print(f"    水色カテゴリ: {cat}  N={n}", flush=True)

        pt_decadal = _build_decadal_from_records(cat_records)
        decadal = pt_decadal if len(pt_decadal) >= 6 else decadal_global

        try:
            bt_lines, bt_data, range_bt_data, star_bt_data, season_thr, wx_params_data, modal_lat, modal_lon, best_cmems = \
                section_backtest_rolling(
                    cat_records, ship_coords, wx_coords, conn_wx, ship_area, decadal,
                    conn_tide=conn_tide, conn_typhoon=conn_typhoon,
                    fish=fish, conn_cmems=conn_cmems
                )
        except Exception as e:
            print(f"    [wc_opt] ERROR {cat}: {e}", flush=True)
            continue

        if bt_data:
            save_water_color_backtest(fish, ship, cat, bt_data)
        if wx_params_data:
            save_water_color_wx_params(fish, ship, cat, wx_params_data, modal_lat, modal_lon)

        for row in bt_data:
            if row[0] == "cnt_avg" and row[1] == 0:
                print(f"    → H=0 wMAPE={row[6]:.1f}%  r={row[2]:+.3f}  BL2={row[26]}", flush=True)
                break

    for c in [conn_wx, conn_tide, conn_typhoon, conn_cmems]:
        if c is not None:
            try:
                c.close()
            except Exception:
                pass

    print(f"  [wc_opt] {fish}×{ship}: 完了", flush=True)


def _save_combo_tuning_json(fish, ship):
    """ポイント別最適化後にcombo_tuning JSONを更新する。
    改善があった場合（best_point_wmape < combo_wmape）のみ更新。
    """
    import json as _json
    from datetime import datetime as _dt
    from collections import defaultdict as _dd

    tuning_dir = os.path.join(ROOT_DIR, "analysis", "V2", "analysis-improvement", "combo_tuning")
    os.makedirs(tuning_dir, exist_ok=True)
    fname = os.path.join(tuning_dir, f"{fish}×{ship}.json")
    now = _dt.now().strftime("%Y-%m-%d")

    try:
        conn = sqlite3.connect(DB_ANA)

        # combo_backtest から全体モデルのwMAPE取得
        cur = conn.cursor()
        cur.execute(
            "SELECT wmape, bl2_wmape, r, n FROM combo_backtest "
            "WHERE fish=? AND ship=? AND metric='cnt_avg' AND horizon=0",
            (fish, ship)
        )
        row = cur.fetchone()
        if not row:
            conn.close()
            return
        combo_wmape, combo_bl2, combo_r, combo_n = row

        # combo_point_backtest から各ポイントのwMAPE取得
        cur.execute(
            "SELECT point, wmape, bl2_wmape, r, n FROM combo_point_backtest "
            "WHERE fish=? AND ship=? AND metric='cnt_avg' AND horizon=0 "
            "ORDER BY wmape",
            (fish, ship)
        )
        pt_rows = cur.fetchall()

        # use_fallback / kaiyu_promoted
        cur.execute(
            "SELECT use_fallback, kaiyu_promoted FROM combo_wx_params "
            "WHERE fish=? AND ship=? LIMIT 1",
            (fish, ship)
        )
        wp = cur.fetchone()
        use_fallback   = bool(wp[0]) if wp else False
        kaiyu_promoted = bool(wp[1]) if wp else False

        conn.close()
    except Exception as e:
        print(f"  [tuning_json] ERROR {fish}×{ship}: {e}", flush=True)
        return

    if not pt_rows:
        return

    # 最良ポイント特定
    best = pt_rows[0]  # ORDER BY wmape なので先頭が最良
    best_wmape = best[1]
    improvement_pt = round(combo_wmape - best_wmape, 2)

    # 改善がない場合はスキップ
    if improvement_pt <= 0:
        return

    # point_models リスト構築
    pt_models = []
    for pt_name, pt_wmape, pt_bl2, pt_r, pt_n in pt_rows:
        pt_models.append({
            "name": pt_name,
            "n": pt_n,
            "wmape_h0": round(pt_wmape, 1),
            "bl2_wmape": round(pt_bl2, 1) if pt_bl2 else None,
            "oos_r": round(pt_r, 3) if pt_r else None,
            "improvement_pt": round(combo_wmape - pt_wmape, 2),
        })

    # status 判定
    if improvement_pt > 5:
        status = "point_model_applied"
    else:
        status = "point_model_marginal"

    # 既存JSON読み込み
    existing = {}
    if os.path.exists(fname):
        try:
            with open(fname, encoding="utf-8") as f:
                existing = _json.load(f)
        except Exception:
            existing = {}

    # history 追記（当日重複防止）
    history = existing.get("history", [])
    if not any(h.get("date") == now for h in history):
        history.append({
            "date": now,
            "action": "point_backtest_updated",
            "note": f"best={best[0]} wmape={best_wmape:.1f}% imp={improvement_pt}pt"
        })

    d = dict(existing)
    d.update({
        "fish": fish,
        "ship": ship,
        "last_reviewed": now,
        "status": status,
        "metrics": {
            "wmape_h0": round(combo_wmape, 2),
            "bl2_wmape": round(combo_bl2, 2) if combo_bl2 else None,
            "oos_r": round(combo_r, 3) if combo_r else None,
            "n_records": combo_n,
            "use_fallback": use_fallback,
            "kaiyu_promoted": kaiyu_promoted,
        },
        "point_models": pt_models,
        "best_point": {
            "name": best[0],
            "wmape_h0": round(best_wmape, 1),
            "improvement_pt": improvement_pt,
        },
        "improvement_pt": improvement_pt,
        "history": history,
    })

    with open(fname, "w", encoding="utf-8") as f:
        _json.dump(d, f, ensure_ascii=False, indent=2)

    print(f"  [tuning_json] 更新: {fish}×{ship} imp={improvement_pt:+.1f}pt → {fname}", flush=True)


# ═══════════════════════════════════════════════════════════════════════════
# メイン
# ═══════════════════════════════════════════════════════════════════════════

def deep_dive(fish, ship, verbose=True, reset_best=False):
    os.makedirs(OUT_DIR, exist_ok=True)

    ship_coords = load_ship_coords()
    wx_coords   = load_wx_coords_list()
    ship_area   = load_ship_area()

    records = load_records(fish, ship_filter=ship)
    if len(records) < MIN_N_COMBO:
        print(f"  {fish} × {ship}: データ不足 ({len(records)}件)")
        return

    # 乗合フィルタ: 仕立て(is_boat=1)の外れ値がモデルを汚染するのを防ぐ
    # 乗合ユーザー向け予測には乗合データのみを使う
    _noboat = [r for r in records if r.get("is_boat", 0) == 0]
    _boat_filtered = len(_noboat) >= MIN_N_COMBO and len(_noboat) < len(records)
    if _boat_filtered:
        print(f"  [is_boat filter] {fish}×{ship}: {len(records)}件 → {len(_noboat)}件（仕立{len(records)-len(_noboat)}件除外）")
        records = _noboat

    conn_wx      = sqlite3.connect(DB_WX)      if (os.path.exists(DB_WX)      and os.path.getsize(DB_WX)      > 0) else None
    conn_tide    = sqlite3.connect(DB_TIDE)    if (os.path.exists(DB_TIDE)    and os.path.getsize(DB_TIDE)    > 0) else None
    conn_typhoon = sqlite3.connect(DB_TYPHOON) if (os.path.exists(DB_TYPHOON) and os.path.getsize(DB_TYPHOON) > 0) else None
    conn_cmems   = sqlite3.connect(DB_CMEMS)   if (os.path.exists(DB_CMEMS)   and os.path.getsize(DB_CMEMS)   > 0) else None
    en0     = enrich(records, ship_coords, wx_coords, conn_wx, ship_area, horizon=0, all_records=records, conn_tide=conn_tide, conn_typhoon=conn_typhoon, conn_cmems=conn_cmems, fish=fish)
    decadal = load_decadal(fish, ship)

    SEP  = "=" * 72
    sep2 = "-" * 60

    out = []
    out.append(SEP)
    out.append(f"  {fish} × {ship}")
    out.append(SEP)

    out.append("\n【基本統計】")
    out += section_basic(records)

    out.append(f"\n【旬別ベースライン（n={len(records)}件）】")
    out += section_decadal(records, decadal)

    out.append(f"\n【因子相関（日次: {len(en0)}件）】")
    corr_lines, corr_results = section_corr(en0)
    out += corr_lines

    for period, label in [("week", "週"), ("decade", "旬"), ("month", "月")]:
        agg = aggregate_by_period(en0, period)
        out.append(f"\n【因子相関（{label}集計: n={len(agg)}{label}）】")
        agg_lines, _ = section_corr(agg)
        out += agg_lines

    out.append("\n【観測因子相関（予報不可・パターン把握用）】")
    out += section_obs_corr(records)

    out.append("\n【コメントキーワード解析】")
    kw_lines, kw_data = section_keywords(records)
    out += kw_lines

    out.append("\n【ポイント別集計】")
    out += section_points(records)
    save_point_stats(fish, ship, records)
    save_point_events(fish, ship, en0)

    out.append("\n【マルチホライズン バックテスト（ローリング月次CV）】")
    bt_lines, bt_data, range_bt_data, star_bt_data, season_thr_final, wx_params_data, modal_lat, modal_lon, best_cmems = section_backtest_rolling(records, ship_coords, wx_coords, conn_wx, ship_area, decadal, conn_tide=conn_tide, conn_typhoon=conn_typhoon, fish=fish, conn_cmems=conn_cmems)
    out += bt_lines

    if conn_wx is not None:
        conn_wx.close()
    if conn_tide is not None:
        conn_tide.close()
    if conn_typhoon is not None:
        conn_typhoon.close()

    text = "\n".join(out)
    out_path = os.path.join(OUT_DIR, f"{fish}_{ship}.txt")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(text)

    save_params(fish, ship, corr_results)
    save_keywords(fish, ship, kw_data)
    save_backtest(fish, ship, bt_data)
    save_range_backtest(fish, ship, range_bt_data)
    save_star_backtest(fish, ship, star_bt_data)
    save_thresholds(fish, ship, season_thr_final)

    # auto_fallback: 以下いずれかの場合、predict_count.py で気象補正をスキップ。
    #   ① BL-0（全体平均）より 10pt 以上悪い
    #   ② BL-2（直近7件実績平均）より 5pt 以上悪い
    #   ③ OOS r < 0.10（モデルが事実上無相関 or 逆効き）
    # → 再実行時も自動的に use_fallback=True が維持される
    use_fallback = False
    # bt_data row: (met, H, rv, mae, mape, smape, wmape, rmse, dacc,
    #               good_r, bad_r, gprec, grec, gf1, bprec, brec, bf1, acc3, n, 0.0,
    #               bl0w, bl0m, bl0r, bl1w, bl1m, bl1r, bl2w, bl2m, bl2r)
    # rv は index 2, bl0_wmape は index 20, bl2_wmape は index 26
    OOS_R_FALLBACK_THR = 0.15  # OOS r がこの値未満なら気象補正はノイズ→フォールバック
    cnt_avg_h0_found = False
    for row in bt_data:
        met = row[0]; H = row[1]; rv = row[2]; wmape = row[6]; bl0w = row[20]; bl2w = row[26]
        if met == "cnt_avg" and H == 0:
            cnt_avg_h0_found = True
            bl0_is_better = (bl0w is not None and wmape is not None and bl0w <= wmape)
            if wmape is not None and bl0_is_better and (
                (bl0w is not None and wmape > bl0w + 10) or
                (bl2w is not None and wmape > bl2w + 5)
            ):
                use_fallback = True
            if rv is not None and rv < OOS_R_FALLBACK_THR and bl0_is_better:
                use_fallback = True
            break
    # cnt_avg のバックテストが 0件（季節偏重コンボ等）の場合は DB の前回値で判定
    if not cnt_avg_h0_found:
        try:
            _conn_fb = _open_ana()
            _row_fb = _conn_fb.execute(
                "SELECT r, wmape, bl0_wmape, bl2_wmape FROM combo_backtest "
                "WHERE fish=? AND ship=? AND metric='cnt_avg' AND horizon=0",
                (fish, ship)
            ).fetchone()
            _conn_fb.close()
            if _row_fb:
                rv_fb, wmape_fb, bl0w_fb, bl2w_fb = _row_fb
                bl0_is_better_fb = (bl0w_fb is not None and wmape_fb is not None and bl0w_fb <= wmape_fb)
                if wmape_fb is not None and bl0_is_better_fb and (
                    (bl0w_fb is not None and wmape_fb > bl0w_fb + 10) or
                    (bl2w_fb is not None and wmape_fb > bl2w_fb + 5)
                ):
                    use_fallback = True
                if rv_fb is not None and rv_fb < OOS_R_FALLBACK_THR and bl0_is_better_fb:
                    use_fallback = True
        except Exception:
            pass

    # kaiyu_promoted: 回遊魚で H=7 cnt_avg wMAPE < 60% かつ BL-2 を下回れば匹数予測に昇格
    # 潮流・のっこみ因子追加後に達成できるコンボが出てくることを期待
    kaiyu_promoted = False
    if fish in KAIYU_FISH:
        for row in bt_data:
            met = row[0]; H = row[1]; wmape = row[6]; bl2w = row[26]  # row[26] = bl2_wmape
            if met == "cnt_avg" and H == 7:
                if (wmape is not None and wmape <= KAIYU_PROMOTE_WMAPE_THR
                        and (bl2w is None or wmape < bl2w)):
                    kaiyu_promoted = True
                break

    # H=0 cnt_avg の wMAPE を Challenger model 用に抽出
    _best_wmape_h0 = None
    for row in bt_data:
        if row[0] == "cnt_avg" and row[1] == 0:
            _best_wmape_h0 = row[6]  # wmape は index 6
            break
    save_wx_params(fish, ship, wx_params_data, modal_lat=modal_lat, modal_lon=modal_lon,
                   use_fallback=use_fallback, kaiyu_promoted=kaiyu_promoted,
                   best_h0_wmape=_best_wmape_h0, best_cmems=best_cmems,
                   reset_best=reset_best)
    save_decadal(fish, ship, records)
    save_combo_meta(fish, ship, records, modal_lat, modal_lon)
    deep_dive_by_point(fish, ship)
    deep_dive_by_trip(fish, ship)
    deep_dive_by_point_depth(fish, ship)
    deep_dive_by_water_color(fish, ship)

    if verbose:
        _sys.stdout.buffer.write(text.encode("utf-8", errors="replace") + b"\n")
        _sys.stdout.buffer.flush()
    print(f"\n  → 保存: {out_path}", flush=True)


def main():
    parser = argparse.ArgumentParser(description="船宿×魚種 深掘り分析")
    parser.add_argument("--fish",       required=True,  help="魚種名（例: アジ）")
    parser.add_argument("--ship",       default=None,   help="船宿名（省略時は全船宿）")
    parser.add_argument("--wave-clamp", type=float, default=None,
                        help="wave_clamp 閾値（例: 1.5, 2.0, 2.5。省略時はデフォルト2.0m）")
    parser.add_argument("--max-factors", type=int, default=None,
                        help="全体因子上限（デフォルト: MAX_FACTORS=12）")
    parser.add_argument("--max-cmems", type=int, default=None,
                        help="CMEMS変数上限・一般魚種（デフォルト: MAX_CMEMS_DEFAULT=2）")
    parser.add_argument("--max-cmems-ocean", type=int, default=None,
                        help="CMEMS変数上限・CMEMS_ALLOWED_FISH（デフォルト: MAX_CMEMS_OCEAN=4）")
    parser.add_argument("--db", default=None,
                        help="analysis.sqlite の出力先パス（省略時はデフォルト）")
    parser.add_argument("--reset-best", action="store_true",
                        help="Challenger model を無視して強制更新（3ヶ月ごとのフルリセット用）")
    parser.add_argument("--point-only", action="store_true",
                        help="セグメント最適化のみ実行（Phase2用・SQLite競合回避）")
    args = parser.parse_args()

    if args.wave_clamp is not None:
        import combo_deep_dive as _self
        _self.WAVE_CLAMP_THRESHOLD = args.wave_clamp
        global WAVE_CLAMP_THRESHOLD
        WAVE_CLAMP_THRESHOLD = args.wave_clamp
        print(f"[wave_clamp] 閾値を {args.wave_clamp}m に設定")

    if args.max_factors is not None:
        global MAX_FACTORS
        MAX_FACTORS = args.max_factors
        print(f"[max_factors] {MAX_FACTORS} に設定")

    if args.max_cmems is not None:
        global MAX_CMEMS_DEFAULT
        MAX_CMEMS_DEFAULT = args.max_cmems
        print(f"[max_cmems] DEFAULT={MAX_CMEMS_DEFAULT} に設定")

    if args.max_cmems_ocean is not None:
        global MAX_CMEMS_OCEAN
        MAX_CMEMS_OCEAN = args.max_cmems_ocean
        print(f"[max_cmems_ocean] OCEAN={MAX_CMEMS_OCEAN} に設定")

    if args.db is not None:
        global DB_ANA
        DB_ANA = args.db
        print(f"[db] 出力先を {DB_ANA} に設定")

    _reset = getattr(args, "reset_best", False)
    _point_only = getattr(args, "point_only", False)

    if _point_only:
        # Phase2: セグメント最適化のみ（deep_dive() は呼ばない）
        recs_all = load_records(args.fish)
        counts = defaultdict(int)
        for r in recs_all:
            counts[r["ship"]] += 1
        if args.ship:
            ships = [args.ship] if counts.get(args.ship, 0) >= MIN_N_COMBO else []
        else:
            ships = sorted(s for s, n in counts.items() if n >= MIN_N_COMBO)
        print(f"[point-only] {args.fish}: {len(ships)}船宿 先頭3: {ships[:3]}")
        for ship in ships:
            deep_dive_by_point(args.fish, ship)
            deep_dive_by_point_depth(args.fish, ship)
            deep_dive_by_trip(args.fish, ship)
            deep_dive_by_water_color(args.fish, ship)
    elif args.ship:
        deep_dive(args.fish, args.ship, reset_best=_reset)
    else:
        recs_all = load_records(args.fish)
        counts = defaultdict(int)
        for r in recs_all:
            counts[r["ship"]] += 1
        ships = sorted(s for s, n in counts.items() if n >= MIN_N_COMBO)
        print(f"{args.fish}: {len(ships)}船宿（各{MIN_N_COMBO}件以上）\n")
        for ship in ships:
            deep_dive(args.fish, ship, verbose=False, reset_best=_reset)


if __name__ == "__main__":
    main()
