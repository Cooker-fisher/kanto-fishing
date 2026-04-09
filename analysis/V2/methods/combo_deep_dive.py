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

import argparse, bisect, csv, json, math, os, re, sqlite3, sys
from collections import defaultdict
from datetime import datetime, timedelta

import sys as _sys; _sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _paths import ROOT_DIR, RESULTS_DIR, DATA_DIR, NORMALIZE_DIR, OCEAN_DIR
DB_WX         = os.path.join(OCEAN_DIR, "weather_cache.sqlite")
DB_TIDE       = os.path.join(OCEAN_DIR, "tide_moon.sqlite")
DB_TYPHOON    = os.path.join(OCEAN_DIR, "typhoon.sqlite")
DB_ANA        = os.path.join(RESULTS_DIR, "analysis.sqlite")
OUT_DIR       = os.path.join(RESULTS_DIR, "deep_dive")
OVERRIDE_FILE  = os.path.join(NORMALIZE_DIR, "ship_wx_coord_override.json")
SHIPS_FILE     = os.path.join(ROOT_DIR, "crawl", "ships.json")
OBS_FIELDS_FILE = os.path.join(NORMALIZE_DIR, "obs_fields.json")

TRAIN_END  = "2024/12/31"   # この日以前 = 学習データ
HORIZONS   = [0, 1, 3, 7, 14, 21, 28]
MIN_N_COMBO = 30            # 分析最小件数（統計的に意味ある予測を立てられる下限）

# wave_clamp 閾値（モジュール変数。--wave-clamp 引数で上書き可）
# 1.5m / 2.0m / 2.5m で比較検証するための可変定数
WAVE_CLAMP_THRESHOLD: float = 2.0

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
    "temp_avg", "temp_max", "temp_min",    # 気温（日次avg/max/min）
    "pressure_avg", "pressure_min",        # 気圧水準（日次avg/min）
    "pressure_delta",                      # 気圧変化傾向（低気圧接近シグナル）
    "tide_range", "moon_age", "moon_sin", "moon_cos", "tide_type_n", "tide_delta",
    "is_holiday",          # カレンダー因子：未来確定値 → 全ホライズン有効
    "is_consec_holiday",   # 連休フラグ（GW/盆/年末年始の3日以上連続休日）
    "is_summer_vacation",  # 夏休みフラグ（7/21〜8/31：家族・子供客増加シグナル）
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
    "precip_sum",                          # 当日合計降水量
    "precip_sum1",                         # 前日合計（翌日の濁り）
    "precip_sum2",                         # 前々日合計（2日遅れ濁りピーク）
    "prev_week_cnt",                       # 前週釣果（自己相関）H>7では2週以上前の情報になるため無効化
    "typhoon_dist", "typhoon_wind",        # 台風接近距離・最大風速（イベント変数 H≤5が有効限界）
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

FAST_MAX_H = 7   # 速い変数は H>7 では予報精度ゼロとみなして使わない

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
    # 気温変化（前日比）
    "temp_delta",    # 当日avg - 前日avg（冬の急上昇 → 南風・表層暖水 → イカ不漁）
    # SST変化率（7日間）
    # 【重要】回遊アジは水温変化で到来/離脱 → SST急落時に大アジ回遊開始シグナル
    "sst_delta",     # 当日SST - 7日前SST（降下=冬型アジ到来、上昇=夏型移行シグナル）
]
# 潮汐（tide テーブルから取る）
TIDE_FACTORS = ["tide_range", "moon_age", "moon_sin", "moon_cos", "tide_type_n", "tide_delta"]

# 釣果自己相関因子（前週釣果 → H≤7で有効、H>7では2週以上前の情報で精度低下）
CATCH_FACTORS = ["prev_week_cnt"]

# 台風因子（イベント変数 → FAST扱いで H>7 は無効化）
TYPHOON_FACTORS = ["typhoon_dist", "typhoon_wind"]

# カレンダー因子（土日・祝日 → 全ホライズンで有効）
CALENDAR_FACTORS = ["is_holiday", "is_consec_holiday", "is_summer_vacation"]

# 全因子（相関計算対象）
ALL_FACTORS = WX_FACTORS + TIDE_FACTORS + CATCH_FACTORS + TYPHOON_FACTORS + CALENDAR_FACTORS

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

def _get_obs_factors():
    """obs_fields.json の role=obs_factor なフィールド名リストを返す"""
    cfg = _get_obs_config()
    return [name for name, spec in cfg.get("fields", {}).items()
            if spec.get("role") == "obs_factor"]

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

def _is_航程系(pp):
    return not pp or bool(_UNRESOLVABLE_POINT_RE.match(pp))

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
    # ① point_place1 直接解決
    if pp and not _is_航程系(pp):
        entry = point_coords.get(pp)
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
    conn = sqlite3.connect(DB_ANA)
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

def load_decadal(fish, ship):
    conn = sqlite3.connect(DB_ANA)
    rows = conn.execute(
        "SELECT decade_no, avg_cnt, avg_size, n FROM combo_decadal WHERE fish=? AND ship=?",
        (fish, ship)
    ).fetchall()
    conn.close()
    return {r[0]: {"avg_cnt": r[1], "avg_size": r[2], "n": r[3]} for r in rows}


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
                lat, lon = _resolve_point(
                    point_place1, ship, tsuri, sfp, ship_area, point_coords, area_coords
                )

                # OBS/TEキストフィールドを obs_fields.json から一括計算
                obs = _compute_obs_fields(row)

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
                    "point":   point_place1,
                    "lat":     lat,
                    "lon":     lon,
                    # 参照用（obs_fields.json 外）
                    "trip_no": int(row.get("trip_no") or 1),
                    "is_train": date_str <= TRAIN_END,
                    # カレンダー因子（土日・祝日・連休・夏休み）
                    "is_holiday":         _is_holiday(date_str),
                    "is_consec_holiday":  _is_consec_holiday(date_str),
                    "is_summer_vacation": _is_summer_vacation(date_str),
                    **obs,   # OBS因子 + テキストフィールド + text_all
                })
    records.sort(key=lambda r: r["date"])
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
               precipitation
        FROM weather
        WHERE lat=? AND lon=? AND dt LIKE ?
        ORDER BY dt
    """, (lat, lon, f"{date_iso}%")).fetchall()
    if not rows:
        return None

    wind_speeds   = [r[0] for r in rows if r[0] is not None]
    wind_dirs     = [r[1] for r in rows if r[1] is not None]
    temps         = [r[2] for r in rows if r[2] is not None]
    pressures     = [r[3] for r in rows if r[3] is not None]
    wave_heights  = [r[4] for r in rows if r[4] is not None]
    wave_periods  = [r[5] for r in rows if r[5] is not None]
    swell_heights = [r[6] for r in rows if r[6] is not None]
    ssts          = [r[7] for r in rows if r[7] is not None]
    precips       = [r[8] for r in rows if r[8] is not None]

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


def enrich(records, ship_coords, wx_coords, conn_wx, ship_area, horizon=0, all_records=None, conn_tide=None, conn_typhoon=None):
    """全レコードに海況・潮汐・前週釣果を付与（horizon 日前の weather を使用）。

    all_records: 前週釣果(prev_week_cnt)の参照用に全期間レコードを渡す。
    Noneのとき records 内のみで探索。
    horizon=H のとき、prediction_date = D - H 以前の最新釣果を prev_week_cnt とする。
    H=0〜7: 先週以内の釣果 → 有効  |  H>7: 2週以上前 → FAST_FACTORS により無効化
    """
    wx_cache      = {}
    tide_cache    = {}
    typhoon_cache = {}
    result = []

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

        # pressure_delta: 当日最低気圧 - 前日最低気圧（気圧変化の方向・速度）
        p_today = wx.get("pressure_min")
        p_prev  = wx.get("pressure_min1")
        wx["pressure_delta"] = (p_today - p_prev) if (p_today and p_prev) else None

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

        rec = dict(r)
        rec.update(wx)
        rec.update(tide)
        rec.update(typhoon_cache[wx_date])
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
    buckets = defaultdict(list)
    for r in records:
        pt = r["point"]
        if pt:
            buckets[pt].append(r["cnt_avg"])
    if not buckets:
        return ["  (ポイントデータなし)"]
    lines = [f"  {'ポイント':<22}  {'n':>4}  {'平均':>7}  {'最大':>7}  {'最小':>7}"]
    lines.append("  " + "-"*55)
    for pt, cnts in sorted(buckets.items(), key=lambda x: -sum(x[1])/len(x[1])):
        if len(cnts) < 2:
            continue
        avg = sum(cnts)/len(cnts)
        lines.append(
            f"  {pt:<22}  {len(cnts):>4}  {avg:>7.1f}  {max(cnts):>7.0f}  {min(cnts):>7.0f}"
        )
    return lines[:16]

def _season_of(month):
    """月 → 季節（春/夏/秋/冬）"""
    if month in (3, 4, 5):  return "春"
    if month in (6, 7, 8):  return "夏"
    if month in (9, 10, 11): return "秋"
    return "冬"

def _percentile(vals, p):
    """vals（ソート済み想定なし）の p パーセンタイルを返す。線形補間なし。"""
    sv = sorted(v for v in vals if v is not None)
    if not sv:
        return None
    idx = int(len(sv) * p / 100)
    return sv[min(idx, len(sv)-1)]

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

def section_backtest_rolling(records, ship_coords, wx_coords, conn_wx, ship_area, decadal, conn_tide=None, conn_typhoon=None):
    """ローリング月次クロスバリデーション

    各月をテスト期として、それ以前の全データを学習に使う拡張ウィンドウCV。
    固定分割（≤2024/12 = train）より本番運用に近い評価方法。
    本番では「全期間でパラメータ推定 → 来週を予測」するため、
    rolling CV がその流れを最も正確にシミュレートする。
    """
    MIN_TRAIN_N = 15
    MIN_TRAIN_MONTHS = 4

    months = sorted(set(r["date"][:7] for r in records))
    if len(months) < MIN_TRAIN_MONTHS + 1:
        return ["  データ不足（ローリングCV最低月数に達しない）"], [], {}, {}, None, None

    # 全ホライズン分を一括 enrich（SQL クエリを事前に全発行してキャッシュ活用）
    all_en_by_H = {}
    for H in HORIZONS:
        all_en_by_H[H] = enrich(
            records, ship_coords, wx_coords, conn_wx, ship_area,
            horizon=H, all_records=records, conn_tide=conn_tide, conn_typhoon=conn_typhoon
        )

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

    for test_month in months:
        train_en_h0 = [r for r in all_en_by_H[0] if r["date"][:7] < test_month]
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

        # train_sorted_m の日付リスト（bisect用）
        train_dates_m = [r["date"] for r in train_sorted_m]

        for met in METRICS_LIST:
            tr_ys = [r.get(met) for r in train_en_h0]
            factor_r_m = {}
            for fac in ALL_FACTORS:
                xs = [r.get(fac) for r in train_en_h0]
                rv, _, _ = pearson(xs, tr_ys)
                if rv is not None and abs(rv) >= 0.10:
                    factor_r_m[fac] = rv
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
            alpha_scale = max(0.1, min(2.0, _ols_num / _ols_den)) if _ols_den > 1e-9 else 0.5
            alpha_scales_by_met[met].append(alpha_scale)  # フォールドごとに収集
            # β: BL-2 ブレンド比（0〜0.5 にクリップ）
            _bt_num = 0.0; _bt_den = 0.0
            for _b, _c, _bl2t, _a in _alpha_tr:
                _mp = _b + _c * alpha_scale
                _d  = _bl2t - _mp
                _bt_num += _d * (_a - _mp)
                _bt_den += _d * _d
            beta_bl2 = max(0.0, min(0.5, _bt_num / _bt_den)) if _bt_den > 1e-9 else 0.0

            for H in HORIZONS:
                te_en_h = [r for r in all_en_by_H[H] if r["date"][:7] == test_month]
                usable  = {fac: rv for fac, rv in factor_r_m.items()
                           if fac in SLOW_FACTORS or H <= FAST_MAX_H}
                w_h = sum(abs(rv) for rv in usable.values()) or 1.0

                for r in te_en_h:
                    act = r.get(met)
                    if act is None:
                        continue

                    dn = r.get("decade")
                    if met == "cnt_avg" and decadal and dn in decadal:
                        base = decadal[dn].get("avg_cnt", met_mean_m)
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
                    # 案C: BL-2 ブレンド適用
                    pred = pred + beta_bl2 * (_bl2_p - pred)

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
            if len(acs) < MIN_N_COMBO:  # テストセットが少なすぎるコンボは除外
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
                         if fac in SLOW_FACTORS or H <= FAST_MAX_H)
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

    # ── 全学習データ（TRAIN_END以前）での最終パラメータ確定 ─────────────────────────
    # バックテスト後に全学習データで因子統計・α・β を再計算し save_wx_params() で保存。
    # predict_count.py の天候補正で使用する。
    wx_params_data = {}  # metric -> {factors, alpha_scale, met_mean, met_std}
    final_train = [r for r in all_en_by_H[0] if r["date"] <= TRAIN_END]

    # コンボ代表座標: 学習データの最頻 (lat, lon) ペアを使う
    # avg ではなく mode を使うことで、実際の主要釣り場座標に近づける
    _modal_lat = None; _modal_lon = None
    _coord_pairs = [(round(r.get("lat", 0) or 0, 3), round(r.get("lon", 0) or 0, 3))
                    for r in final_train if r.get("lat") and r.get("lon")]
    if _coord_pairs:
        _modal_pair = max(set(_coord_pairs), key=_coord_pairs.count)
        _modal_lat, _modal_lon = _modal_pair

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
                xs = [r.get(fac) for r in final_train]
                rv, _, _ = pearson(xs, final_ys)
                if rv is not None and abs(rv) >= 0.10:
                    final_factor_r[fac] = rv
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

    return lines, bt_data, season_thr, wx_params_data, _modal_lat, _modal_lon


def save_params(fish, ship, corr_results):
    conn = sqlite3.connect(DB_ANA)
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


def save_wx_params(fish, ship, wx_params_data, modal_lat=None, modal_lon=None, use_fallback=False):
    """天候補正パラメータを combo_wx_params テーブルに保存。
    predict_count.py が天候補正時に参照する。
    factor='_meta' 行: alpha_scale / met_mean / met_std / lat / lon（コンボ代表座標）
    factor=<因子名> 行: 因子の mean / std / r
    lat/lon は学習データの最頻ポイント座標（avg ではなく mode）
    """
    if not wx_params_data:
        return
    conn = sqlite3.connect(DB_ANA)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS combo_wx_params (
            fish         TEXT,
            ship         TEXT,
            metric       TEXT,
            factor       TEXT,
            mean         REAL,
            std          REAL,
            r            REAL,
            alpha_scale  REAL,
            met_mean     REAL,
            met_std      REAL,
            lat          REAL,
            lon          REAL,
            updated_at   TEXT,
            use_fallback INTEGER DEFAULT 0,
            PRIMARY KEY (fish, ship, metric, factor)
        )
    """)
    # 既存テーブルへの列追加（マイグレーション）
    existing = {r[1] for r in conn.execute("PRAGMA table_info(combo_wx_params)").fetchall()}
    for col, typ in [("lat", "REAL"), ("lon", "REAL"), ("use_fallback", "INTEGER")]:
        if col not in existing:
            conn.execute(f"ALTER TABLE combo_wx_params ADD COLUMN {col} {typ}")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rows = []
    for met, params in wx_params_data.items():
        rows.append((fish, ship, met, "_meta",
                     None, None, None,
                     params["alpha_scale"], params["met_mean"], params["met_std"],
                     modal_lat, modal_lon, now, int(use_fallback)))
        for fac, (mean, std, r) in params["factors"].items():
            rows.append((fish, ship, met, fac, mean, std, r, None, None, None, None, None, now, 0))
    # 列名を明示して列順ずれを防ぐ（ALTER TABLE でカラム追加した場合の位置ズレ対策）
    conn.executemany(
        """INSERT OR REPLACE INTO combo_wx_params
           (fish, ship, metric, factor, mean, std, r,
            alpha_scale, met_mean, met_std, lat, lon, updated_at, use_fallback)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        rows
    )
    conn.commit()
    conn.close()


def save_keywords(fish, ship, kw_data):
    """コメントキーワード解析結果を combo_keywords テーブルに保存"""
    if not kw_data:
        return
    conn = sqlite3.connect(DB_ANA)
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
    conn = sqlite3.connect(DB_ANA)
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


def save_thresholds(fish, ship, season_thr_final):
    """季節別分類閾値を combo_thresholds テーブルに保存"""
    if not season_thr_final:
        return
    conn = sqlite3.connect(DB_ANA)
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


# ═══════════════════════════════════════════════════════════════════════════
# メイン
# ═══════════════════════════════════════════════════════════════════════════

def deep_dive(fish, ship, verbose=True):
    os.makedirs(OUT_DIR, exist_ok=True)

    ship_coords = load_ship_coords()
    wx_coords   = load_wx_coords_list()
    ship_area   = load_ship_area()

    records = load_records(fish, ship_filter=ship)
    if len(records) < MIN_N_COMBO:
        print(f"  {fish} × {ship}: データ不足 ({len(records)}件)")
        return

    conn_wx      = sqlite3.connect(DB_WX)      if (os.path.exists(DB_WX)      and os.path.getsize(DB_WX)      > 0) else None
    conn_tide    = sqlite3.connect(DB_TIDE)    if (os.path.exists(DB_TIDE)    and os.path.getsize(DB_TIDE)    > 0) else None
    conn_typhoon = sqlite3.connect(DB_TYPHOON) if (os.path.exists(DB_TYPHOON) and os.path.getsize(DB_TYPHOON) > 0) else None
    en0     = enrich(records, ship_coords, wx_coords, conn_wx, ship_area, horizon=0, all_records=records, conn_tide=conn_tide, conn_typhoon=conn_typhoon)
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

    out.append("\n【マルチホライズン バックテスト（ローリング月次CV）】")
    bt_lines, bt_data, season_thr_final, wx_params_data, modal_lat, modal_lon = section_backtest_rolling(records, ship_coords, wx_coords, conn_wx, ship_area, decadal, conn_tide=conn_tide, conn_typhoon=conn_typhoon)
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

    if verbose:
        print(text)
    print(f"\n  → 保存: {out_path}", flush=True)

    save_params(fish, ship, corr_results)
    save_keywords(fish, ship, kw_data)
    save_backtest(fish, ship, bt_data)
    save_thresholds(fish, ship, season_thr_final)

    # auto_fallback: H=0 cnt_avg でモデルが BL-0（全体平均）より 10pt 以上悪い場合、
    # predict_count.py で気象補正をスキップして旬別ベースラインをそのまま使う。
    # 例: ヒラメ×つる丸（model=91.4% vs BL0=69.2%）→ use_fallback=True
    use_fallback = False
    # bt_data row: (met, H, rv, mae, mape, smape, wmape, rmse, dacc,
    #               good_r, bad_r, gprec, grec, gf1, bprec, brec, bf1, acc3, n, 0.0,
    #               bl0w, bl0m, bl0r, bl1w, bl1m, bl1r, bl2w, bl2m, bl2r)
    # bl0_wmape は index 20
    for row in bt_data:
        met = row[0]; H = row[1]; wmape = row[6]; bl0w = row[20]  # row[20] = bl0_wmape
        if met == "cnt_avg" and H == 0:
            if wmape is not None and bl0w is not None and wmape > bl0w + 10:
                use_fallback = True
            break

    save_wx_params(fish, ship, wx_params_data, modal_lat=modal_lat, modal_lon=modal_lon,
                   use_fallback=use_fallback)


def main():
    parser = argparse.ArgumentParser(description="船宿×魚種 深掘り分析")
    parser.add_argument("--fish",       required=True,  help="魚種名（例: アジ）")
    parser.add_argument("--ship",       default=None,   help="船宿名（省略時は全船宿）")
    parser.add_argument("--wave-clamp", type=float, default=None,
                        help="wave_clamp 閾値（例: 1.5, 2.0, 2.5。省略時はデフォルト2.0m）")
    args = parser.parse_args()

    if args.wave_clamp is not None:
        import combo_deep_dive as _self
        _self.WAVE_CLAMP_THRESHOLD = args.wave_clamp
        global WAVE_CLAMP_THRESHOLD
        WAVE_CLAMP_THRESHOLD = args.wave_clamp
        print(f"[wave_clamp] 閾値を {args.wave_clamp}m に設定")

    if args.ship:
        deep_dive(args.fish, args.ship)
    else:
        recs_all = load_records(args.fish)
        counts = defaultdict(int)
        for r in recs_all:
            counts[r["ship"]] += 1
        ships = sorted(s for s, n in counts.items() if n >= MIN_N_COMBO)
        print(f"{args.fish}: {len(ships)}船宿（各{MIN_N_COMBO}件以上）\n")
        for ship in ships:
            deep_dive(args.fish, ship, verbose=False)


if __name__ == "__main__":
    main()
