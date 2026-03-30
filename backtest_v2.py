#!/usr/bin/env python3
"""
backtest_v2.py - 日次バックテスト（気象×釣果）v4

[予測モデル v4]  5エリア×魚種単位
  予測 = ベースライン × シーズン補正 × 気象補正（エリア別）

  ベースライン : 昨年同日 ±window日 の【同エリア同魚種】平均
                エリア内サンプル不足 → 全エリアにフォールバック
                それも不足 → DOY±window の全年度同エリア平均（季節平均）
                それも不足 → DOY±window の全エリア全年度平均
                それも不足 → 長期静的平均（最終フォールバック）

  気象補正     : 分析で有意（|r|≥0.20）と判明した fish×area の組み合わせのみ適用
                それ以外は波高・風速補正なし（ノイズ除去）

[エリア定義]
  東京湾奥  浦安・羽田・平和島・長浦・東葛西・内房（富津・金谷等）
  東京湾口  久比里・金沢八景・鴨居大室・洲崎・横浜
  相模湾    松輪・長井・葉山・平塚・小田原
  外房      大原・飯岡・外川・片貝・天津・御宿
  茨城      波崎・鹿島・日立久慈

[バリデーション]
  MAPE・レンジ的中率・方向性的中率を 魚種×エリア単位で出力
"""
import csv, json, os, sys
from datetime import datetime, timedelta
from collections import defaultdict

sys.stdout.reconfigure(encoding="utf-8")

BASE_DIR        = os.path.dirname(os.path.abspath(__file__))
HISTORY_FILE    = os.path.join(BASE_DIR, "history.json")
AREA_MAP        = os.path.join(BASE_DIR, "area_weather_map.json")
WEATHER_DIR     = os.path.join(BASE_DIR, "weather_data")
DATA_DIR        = os.path.join(BASE_DIR, "data")
MASTER_DATASET  = os.path.join(BASE_DIR, "analysis", "master_dataset.csv")

# ── 5エリア定義（port名 → エリアグループ） ─────────────────────────
PORT_TO_AREA5 = {
    # 東京湾奥
    "浦安":                    "東京湾奥",
    "羽田":                    "東京湾奥",
    "平和島":                  "東京湾奥",
    "長浦":                    "東京湾奥",
    "東葛西":                  "東京湾奥",
    "江戸川放水路･原木中山":   "東京湾奥",
    "富浦港":                  "東京湾奥",
    "金谷港":                  "東京湾奥",
    "富津港":                  "東京湾奥",
    "大津港":                  "東京湾奥",
    "保田港":                  "東京湾奥",
    # 東京湾口
    "久比里港":                "東京湾口",
    "金沢八景":                "東京湾口",
    "鴨居大室港":              "東京湾口",
    "洲崎港":                  "東京湾口",
    "磯子港":                  "東京湾口",
    "横浜本牧港":              "東京湾口",
    "小柴港":                  "東京湾口",
    # 相模湾
    "平塚港":                  "相模湾",
    "松輪間口港":              "相模湾",
    "葉山あぶずり港":          "相模湾",
    "小坪港":                  "相模湾",
    "松輪江奈港":              "相模湾",
    "長井港":                  "相模湾",
    "長井漆山港":              "相模湾",
    "大磯港":                  "相模湾",
    "小田原早川港":            "相模湾",
    "勝浦川津港":              "相模湾",
    # 外房
    "大原港":                  "外房",
    "飯岡港":                  "外房",
    "外川港":                  "外房",
    "外川":                    "外房",
    "片貝港":                  "外房",
    "天津港":                  "外房",
    "御宿岩和田港":            "外房",
    # 茨城
    "波崎港":                  "茨城",
    "鹿島港":                  "茨城",
    "日立久慈港":              "茨城",
    "鹿島市新浜":              "茨城",
}

# ── エリア別・魚種別 気象補正係数（分析で|r|≥0.20の組のみ） ─────────
# 形式: (fish, area5) → {"wave": shrink, "sst": direction}
#   wave: 波高補正のSHRINK係数（0=補正なし, 0.5=強め）
#   sst:  水温補正の向き（+1=高温で増加, -1=低温で増加, 0=補正なし）
#   sst_shrink: 水温補正の強さ
AREA_WEATHER_RULES = {
    # 波高補正あり
    ("フグ",       "東京湾口"): {"wave": 0.6,  "sst": +1, "sst_shrink": 0.3},
    ("カサゴ",     "茨城"):     {"wave": 0.6,  "sst":  0, "sst_shrink": 0.0},
    ("アジ",       "東京湾口"): {"wave": 0.3,  "sst":  0, "sst_shrink": 0.0},
    ("フグ",       "茨城"):     {"wave": 0.4,  "sst": +1, "sst_shrink": 0.3},
    ("マルイカ",   "外房"):     {"wave": 0.3,  "sst":  0, "sst_shrink": 0.0},
    # 水温補正あり
    ("タチウオ",   "東京湾奥"): {"wave": 0.0,  "sst": +1, "sst_shrink": 0.5},
    ("ヒラメ",     "茨城"):     {"wave": 0.0,  "sst": +1, "sst_shrink": 0.4},
    ("マダコ",     "茨城"):     {"wave": 0.0,  "sst": +1, "sst_shrink": 0.6},
    ("シロギス",   "東京湾奥"): {"wave": 0.0,  "sst": +1, "sst_shrink": 0.4},
    ("フグ",       "東京湾奥"): {"wave": 0.0,  "sst": +1, "sst_shrink": 0.5},
    ("アオリイカ", "相模湾"):   {"wave": 0.0,  "sst": +1, "sst_shrink": 0.5},
    ("ワラサ",     "相模湾"):   {"wave": 0.0,  "sst": +1, "sst_shrink": 0.4},
    ("カワハギ",   "東京湾奥"): {"wave": 0.0,  "sst": +1, "sst_shrink": 0.3},
    ("マダコ",     "東京湾奥"): {"wave": 0.0,  "sst": +1, "sst_shrink": 0.3},
    ("マダコ",     "東京湾口"): {"wave": 0.0,  "sst": +1, "sst_shrink": 0.3},
    ("ヒラメ",     "外房"):     {"wave": 0.0,  "sst": +1, "sst_shrink": 0.3},
    ("イサキ",     "外房"):     {"wave": 0.0,  "sst": -1, "sst_shrink": 0.3},
}

# ── シーズンデータ（crawler.py と同じ） ────────────────────────────
SEASON_DATA = {
    "アジ":     [3,3,3,4,4,5,5,4,4,4,4,3],
    "タチウオ": [1,1,1,1,2,3,5,5,5,4,3,2],
    "フグ":     [3,3,4,4,3,2,2,2,3,4,4,3],
    "カワハギ": [2,2,2,2,2,2,3,4,5,5,4,3],
    "マダイ":   [2,2,3,5,5,4,3,3,3,4,4,3],
    "シロギス": [1,1,2,3,5,5,5,4,3,2,1,1],
    "イサキ":   [1,1,2,3,4,5,5,4,3,2,1,1],
    "ヤリイカ": [4,4,3,2,2,2,2,2,2,3,4,5],
    "スルメイカ":[1,1,1,2,3,4,5,5,4,3,2,1],
    "マダコ":   [1,1,1,2,3,5,5,5,4,3,2,1],
    "カサゴ":   [4,4,4,3,3,2,2,2,3,3,4,4],
    "メバル":   [4,4,4,3,3,2,2,2,2,3,4,4],
    "ワラサ":   [2,2,2,2,3,3,4,4,5,5,4,3],
    "ヒラメ":   [4,4,3,3,3,3,3,3,4,5,5,4],
    "アマダイ": [3,3,3,3,3,3,3,3,4,4,4,4],
    "マゴチ":   [1,1,1,2,4,5,5,5,4,2,1,1],
    "キンメダイ":[4,4,4,3,3,3,3,3,3,4,4,4],
    "マルイカ": [2,3,4,5,5,3,1,1,1,1,1,2],
    "クロムツ": [4,4,3,3,3,3,3,3,3,3,4,4],
    "サワラ":   [1,1,2,4,5,3,2,2,4,5,4,2],
    "メダイ":   [4,5,5,4,3,2,1,1,1,2,3,4],
    "マハタ":   [3,3,3,3,4,4,4,4,4,3,3,3],
    "カンパチ": [1,1,1,2,3,4,5,5,4,3,2,1],
}

# ── 気象係数ルール ─────────────────────────────────────────────────

def wave_factor(wh):
    """波高(m) → 釣果係数 & 説明"""
    if wh is None:   return 1.0, "波高不明"
    if wh < 0.5:     return 1.05, f"波高{wh:.1f}m（べた凪・好条件）"
    if wh < 1.0:     return 1.0,  f"波高{wh:.1f}m（平水）"
    if wh < 1.5:     return 0.95, f"波高{wh:.1f}m（やや波あり）"
    if wh < 2.0:     return 0.80, f"波高{wh:.1f}m（波高め・釣果減）"
    if wh < 2.5:     return 0.65, f"波高{wh:.1f}m（荒れ気味・要注意）"
    return              0.45, f"波高{wh:.1f}m（出船困難クラス）"

def wind_factor(ws):
    """風速(m/s) → 釣果係数 & 説明"""
    if ws is None:   return 1.0, "風速不明"
    if ws < 5:       return 1.0,  f"風速{ws:.1f}m/s（微風）"
    if ws < 8:       return 1.0,  f"風速{ws:.1f}m/s（穏やか）"
    if ws < 12:      return 0.92, f"風速{ws:.1f}m/s（やや強風）"
    if ws < 15:      return 0.75, f"風速{ws:.1f}m/s（強風・釣りにくい）"
    return              0.55, f"風速{ws:.1f}m/s（出船困難クラス）"

def tide_factor(tide_type):
    """潮汐タイプ → 釣果係数 & 説明"""
    table = {
        "大潮": (1.12, "大潮（魚の活性UP・期待大）"),
        "中潮": (1.05, "中潮（標準的な活性）"),
        "小潮": (0.92, "小潮（活性やや低め）"),
        "長潮": (0.88, "長潮（潮動かず・苦戦しやすい）"),
        "若潮": (0.92, "若潮（回復途上・やや低め）"),
    }
    if tide_type in table:
        return table[tide_type]
    return 1.0, f"潮汐不明({tide_type})"

def temp_factor(sst, month):
    """海水温 → 釣果係数 & 説明（季節平均との乖離で補正）"""
    # 東京湾・相模湾の月別平均水温（概算）
    MONTHLY_AVG = [15,14,15,17,19,22,25,27,26,23,20,17]
    if sst is None or month is None:
        return 1.0, "水温不明"
    avg = MONTHLY_AVG[month - 1]
    diff = sst - avg
    if diff > 3:     factor, note = 1.05, f"水温{sst:.1f}°C（平年+{diff:.1f}°・やや高め）"
    elif diff > 1:   factor, note = 1.02, f"水温{sst:.1f}°C（平年+{diff:.1f}°・適温域）"
    elif diff > -1:  factor, note = 1.0,  f"水温{sst:.1f}°C（平年並み）"
    elif diff > -3:  factor, note = 0.97, f"水温{sst:.1f}°C（平年{diff:.1f}°・やや低め）"
    else:            factor, note = 0.92, f"水温{sst:.1f}°C（平年{diff:.1f}°・低水温）"
    return factor, note

def season_factor(fish, month):
    """シーズンスコア(1〜5) → 釣果係数 & 説明（縮小版: ±10%以内）"""
    scores = SEASON_DATA.get(fish, [3]*12)
    score  = scores[month - 1]
    # 縮小版: 1→0.90, 2→0.95, 3→1.00, 4→1.05, 5→1.10（元は0.60〜1.20）
    table  = {5: (1.10, "旬（ピーク期）"), 4: (1.05, "好期"), 3: (1.0, "普通期"),
              2: (0.95, "やや低調期"), 1: (0.90, "オフシーズン")}
    f, note = table.get(score, (1.0, ""))
    return f, f"{fish} {note}"

# ── データ読み込み ─────────────────────────────────────────────────

def load_weather():
    """weather_data/*_history.csv → {area_code: {date_str: row}}"""
    idx = {}
    for fname in os.listdir(WEATHER_DIR):
        if not fname.endswith("_history.csv"):
            continue
        code = fname.replace("_history.csv", "")
        idx[code] = {}
        with open(os.path.join(WEATHER_DIR, fname), encoding="utf-8") as f:
            for row in csv.DictReader(f):
                idx[code][row["date"]] = row
    return idx

def load_area_map():
    raw = json.load(open(AREA_MAP, encoding="utf-8"))
    return {k: v for k, v in raw.items() if not k.startswith("_")}

def load_history():
    return json.load(open(HISTORY_FILE, encoding="utf-8"))

def load_master_records():
    """analysis/master_dataset.csv → 全レコードのリスト（海況結合済み）"""
    if not os.path.exists(MASTER_DATASET):
        return []
    rows = []
    with open(MASTER_DATASET, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                avg = float(row["cnt_avg"])
            except (ValueError, KeyError):
                continue
            if avg <= 0:
                continue
            rows.append(row)
    return rows

def load_daily_catches():
    """data/YYYY-MM.csv → {date: {area: {fish: [cnt_avg, ...]}}}"""
    result = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    if not os.path.isdir(DATA_DIR):
        return result
    for fname in os.listdir(DATA_DIR):
        if not fname.endswith(".csv"):
            continue
        with open(os.path.join(DATA_DIR, fname), encoding="utf-8") as f:
            for row in csv.DictReader(f):
                date = row.get("date", "")
                area = row.get("area", "")
                fish = row.get("fish", "")
                try:
                    avg = float(row["cnt_avg"])
                except (ValueError, KeyError):
                    continue
                if avg > 0 and date and area and fish:
                    result[date][area][fish].append(avg)
    return result

def date_to_week(date_str):
    """'2026/03/25' → '2026/W13'"""
    dt = datetime.strptime(date_str, "%Y/%m/%d")
    iso = dt.isocalendar()
    return f"{iso[0]}/W{iso[1]:02d}"

def date_to_weather_key(date_str):
    """'2026/03/25' → '2026-03-25'"""
    return date_str.replace("/", "-")

def prev_year_week(wk):
    y, w = wk.split("/W")
    return f"{int(y)-1}/W{w}"

def _float(s):
    try: return float(s)
    except: return None

# ── 日毎インデックス構築 ──────────────────────────────────────────

def build_daily_index(master_rows):
    """
    master_dataset → 4種類のインデックスを返す
      idx_area5    : {date_str: {(fish, area5): [cnt_avg, ...]}}  ← 5エリア別・日付
      idx_all      : {date_str: {fish:           [cnt_avg, ...]}}  ← 全エリア合算・日付
      doy_area5    : {doy: {(fish, area5): [cnt_avg, ...]}}        ← 5エリア別・DOY（全年度）
      doy_all      : {doy: {fish:           [cnt_avg, ...]}}        ← 全エリア合算・DOY
      longterm_avg : {(fish, area5): mean, (fish, None): mean}    ← 長期静的平均（最終FB）
    """
    idx_area5    = defaultdict(lambda: defaultdict(list))
    idx_all      = defaultdict(lambda: defaultdict(list))
    doy_area5    = defaultdict(lambda: defaultdict(list))
    doy_all      = defaultdict(lambda: defaultdict(list))
    lt_buckets   = defaultdict(list)  # (fish, area5_or_None) → [cnt_avg, ...]

    for row in master_rows:
        date = row["date"]
        fish = row["fish"]
        val  = float(row["cnt_avg"])
        a5   = PORT_TO_AREA5.get(row.get("area", ""))
        try:
            doy = datetime.strptime(date, "%Y/%m/%d").timetuple().tm_yday
        except ValueError:
            doy = None

        idx_all[date][fish].append(val)
        lt_buckets[(fish, None)].append(val)
        if doy:
            doy_all[doy][fish].append(val)
        if a5:
            idx_area5[date][(fish, a5)].append(val)
            lt_buckets[(fish, a5)].append(val)
            if doy:
                doy_area5[doy][(fish, a5)].append(val)

    longterm_avg = {k: sum(v)/len(v) for k, v in lt_buckets.items()}
    return idx_area5, idx_all, doy_area5, doy_all, longterm_avg

# 魚種別ウィンドウ幅（季節変化が急な魚は狭く）
FISH_WINDOW = {
    "マルイカ": 7,
    "タチウオ": 10,
    "マダコ":   10,
    "カツオ":   10,
    "マゴチ":   10,
}
DEFAULT_WINDOW = 14
MIN_SAMPLES = 5   # ベースライン計算に必要な最低サンプル数

def daily_baseline(fish, area5, date_str, idx_area5, idx_all, doy_area5, doy_all):
    """
    ベースラインを返す。優先順位:
      1. 昨年同日 ±window の【同エリア同魚種】
      2. 昨年同日 ±window の【全エリア同魚種】
      3. DOY ±window の【同エリア同魚種】（全年度）
      4. DOY ±window の【全エリア同魚種】（全年度）
      いずれも MIN_SAMPLES 未満なら None
    """
    window = FISH_WINDOW.get(fish, DEFAULT_WINDOW)
    dt = datetime.strptime(date_str, "%Y/%m/%d")
    dt_lastyear = dt.replace(year=dt.year - 1)

    lastyear_dates = []
    for delta in range(-window, window + 1):
        past = dt_lastyear + timedelta(days=delta)
        lastyear_dates.append(past.strftime("%Y/%m/%d"))

    # 1. 昨年同日×エリア
    if area5:
        vals = []
        for d in lastyear_dates:
            vals += idx_area5.get(d, {}).get((fish, area5), [])
        if len(vals) >= MIN_SAMPLES:
            return sum(vals) / len(vals), len(vals), "area5"

    # 2. 昨年同日×全エリア
    vals = []
    for d in lastyear_dates:
        vals += idx_all.get(d, {}).get(fish, [])
    if len(vals) >= MIN_SAMPLES:
        return sum(vals) / len(vals), len(vals), "all"

    # 3. DOY×エリア（全年度）
    doy = dt.timetuple().tm_yday
    doys = [(doy + delta - 1) % 365 + 1 for delta in range(-window, window + 1)]
    if area5:
        vals = []
        for d in doys:
            vals += doy_area5.get(d, {}).get((fish, area5), [])
        if len(vals) >= MIN_SAMPLES:
            return sum(vals) / len(vals), len(vals), "doy_area5"

    # 4. DOY×全エリア（全年度）
    vals = []
    for d in doys:
        vals += doy_all.get(d, {}).get(fish, [])
    if len(vals) >= MIN_SAMPLES:
        return sum(vals) / len(vals), len(vals), "doy_all"

    return None, 0, None

# ── 予測エンジン ───────────────────────────────────────────────────

# 月別平均水温（東京湾・相模湾の概算）
MONTHLY_SST_AVG = [15, 14, 15, 17, 19, 22, 25, 27, 26, 23, 20, 17]

def predict(fish, area, date_str, idx_area5, idx_all, doy_area5, doy_all, longterm_avg, weather_row):
    """
    1日・1魚種・1エリアの予測を返す（v4: DOYフォールバック追加）

    ベースライン優先順位:
      1. 昨年同日±window × 同エリア同魚種
      2. 昨年同日±window × 全エリア同魚種
      3. DOY±window × 同エリア同魚種（全年度）
      4. DOY±window × 全エリア同魚種（全年度）
      5. 長期静的平均（最終フォールバック）

    気象補正:
      AREA_WEATHER_RULES に定義された fish×area5 のみ適用
      定義外は波高・風速補正なし（ノイズ除去）
    シーズン補正: ±10%（全魚種共通）
    """
    month = int(date_str[5:7])
    area5 = PORT_TO_AREA5.get(area)

    # ── ベースライン ──
    base_daily, n_samples, base_src = daily_baseline(
        fish, area5, date_str, idx_area5, idx_all, doy_area5, doy_all
    )
    SRC_LABELS = {
        "area5":     "",
        "all":       "[全エリアFB]",
        "doy_area5": "[DOY季節平均×エリア]",
        "doy_all":   "[DOY季節平均×全エリア]",
    }
    if base_daily and base_daily > 0:
        src_label = SRC_LABELS.get(base_src, "")
        baseline  = base_daily
        w         = FISH_WINDOW.get(fish, DEFAULT_WINDOW)
        prefix    = "昨年同日" if base_src in ("area5", "all") else f"DOY季節"
        baseline_label = (
            f"{prefix}±{w}日 {fish}×{area5 or '?'}{src_label} "
            f"平均: {baseline:.1f}匹 (n={n_samples})"
        )
    else:
        # 最終フォールバック: master_dataset の長期静的平均（エリア別 → 全エリア順）
        baseline = longterm_avg.get((fish, area5)) or longterm_avg.get((fish, None))
        if not baseline or baseline <= 0:
            return None
        area_label     = area5 if area5 and (fish, area5) in longterm_avg else "全エリア"
        baseline_label = f"[長期静的平均FB] {fish}×{area_label} 長期平均: {baseline:.1f}匹"
        base_src       = "longterm_fb"

    # ── 気象係数 ──
    wh  = _float(weather_row.get("wave_height"))    if weather_row else None
    ws  = _float(weather_row.get("wind_speed"))     if weather_row else None
    sst = _float(weather_row.get("sea_surface_temp")) if weather_row else None
    ma  = _float(weather_row.get("moon_age"))       if weather_row else None

    f_season, d_season = season_factor(fish, month)
    factors = [("season", f_season, d_season)]

    # 分析結果に基づくエリア別補正
    rule = AREA_WEATHER_RULES.get((fish, area5), {})
    wave_shrink = rule.get("wave", 0.0)
    sst_dir     = rule.get("sst",  0)
    sst_shrink  = rule.get("sst_shrink", 0.0)

    # 波高補正（ルールが定義されている組み合わせのみ）
    if wave_shrink > 0 and wh is not None:
        raw_wave, d_wave = wave_factor(wh)
        f_wave = 1.0 + (raw_wave - 1.0) * wave_shrink
        factors.append(("wave", f_wave, d_wave))

    # 水温補正（ルールが定義されている組み合わせのみ）
    if sst_shrink > 0 and sst is not None:
        avg_sst = MONTHLY_SST_AVG[month - 1]
        diff = sst - avg_sst
        # diff を ±5℃ でクリップし、方向と強さを適用
        raw_sst_f = 1.0 + (diff / 5.0) * sst_dir * 0.15  # max ±15%
        f_sst = 1.0 + (raw_sst_f - 1.0) * sst_shrink
        d_sst = f"水温{sst:.1f}℃(平年比{diff:+.1f}℃)"
        factors.append(("sst", f_sst, d_sst))

    wx_coef   = 1.0
    for _, coef, _ in factors:
        wx_coef *= coef
    predicted = round(baseline * wx_coef, 1)

    cnt_min = round(predicted * 0.70)
    cnt_max = round(predicted * 1.30)

    reasons = [baseline_label, f"補正係数 ×{wx_coef:.3f} = {predicted:.1f}匹 予測"]
    for name, coef, desc in factors:
        sign = "↑" if coef > 1.0 else ("↓" if coef < 1.0 else "→")
        reasons.append(f"  {sign} {desc} (×{coef:.3f})")
    if ma is not None:
        reasons.append(f"  ℹ 月齢: {ma:.1f}")

    return {
        "baseline":     baseline,
        "baseline_src": base_src,
        "area5":        area5,
        "predicted":    predicted,
        "cnt_min":      cnt_min,
        "cnt_max":      cnt_max,
        "size_min":     None,
        "size_max":     None,
        "wt_min":       None,
        "wt_max":       None,
        "wx_coef":      round(wx_coef, 3),
        "factors":      factors,
        "reasons":      reasons,
    }

# ── MAPE 計算 ─────────────────────────────────────────────────────

def mape(pred, actual):
    if actual == 0: return None
    return abs(pred - actual) / actual * 100

# ── メイン ────────────────────────────────────────────────────────

def main():
    master_rows = load_master_records()
    idx_area5, idx_all, doy_area5, doy_all, longterm_avg = build_daily_index(master_rows)

    n_dates = len(idx_all)
    print(f"master_dataset: {len(master_rows)}件, 日付数: {n_dates}日")
    print()

    # ── バリデーション ────────────────────────────────────────────
    records = []

    for row in master_rows:
        date_str = row.get("date", "")
        area     = row.get("area", "")
        fish     = row.get("fish", "")
        if not date_str or not fish:
            continue

        actual_avg = float(row["cnt_avg"])
        wx_row = {
            "wave_height":      row.get("wave_height", ""),
            "wind_speed":       row.get("wind_speed", ""),
            "sea_surface_temp": row.get("sea_surface_temp", ""),
            "tide_type":        row.get("tide_type", ""),
            "moon_age":         row.get("moon_age", ""),
        }

        result = predict(fish, area, date_str, idx_area5, idx_all, doy_area5, doy_all, longterm_avg, wx_row)
        if result is None:
            continue

        e          = mape(result["predicted"], actual_avg)
        baseline   = result["baseline"]
        area5      = result["area5"] or "不明"
        pred_dir   = "up"   if result["predicted"] > baseline * 1.05 else \
                     "down" if result["predicted"] < baseline * 0.95 else "flat"
        actual_dir = "up"   if actual_avg > baseline * 1.05 else \
                     "down" if actual_avg < baseline * 0.95 else "flat"
        records.append({
            "date":         date_str,
            "area":         area,
            "area5":        area5,
            "fish":         fish,
            "actual":       round(actual_avg, 1),
            "predicted":    result["predicted"],
            "baseline":     round(baseline, 1),
            "baseline_src": result["baseline_src"],
            "cnt_min":      result["cnt_min"],
            "cnt_max":      result["cnt_max"],
            "error":        round(e, 1) if e is not None else None,
            "in_range":     result["cnt_min"] <= actual_avg <= result["cnt_max"] if e is not None else None,
            "dir_correct":  pred_dir == actual_dir,
            "wx_coef":      result["wx_coef"],
            "result":       result,
        })

    if not records:
        print("バリデーション対象データなし")
        return

    def stat(recs):
        errs = [r["error"] for r in recs if r["error"] is not None]
        inrs = [r["in_range"] for r in recs if r["in_range"] is not None]
        dirs = [r["dir_correct"] for r in recs]
        if not errs:
            return None, None, None, 0
        return (round(sum(errs)/len(errs), 1),
                round(sum(inrs)/len(inrs)*100, 1) if inrs else 0,
                round(sum(dirs)/len(dirs)*100, 1) if dirs else 0,
                len(errs))

    # ── 魚種×エリア別集計 ─────────────────────────────────────────
    combo_stats = defaultdict(list)
    fish_stats  = defaultdict(list)
    area_stats  = defaultdict(list)
    for r in records:
        combo_stats[(r["fish"], r["area5"])].append(r)
        fish_stats[r["fish"]].append(r)
        area_stats[r["area5"]].append(r)

    AREAS = ["東京湾奥", "東京湾口", "相模湾", "外房", "茨城", "不明"]

    print(f"{'魚種':<12} {'エリア':<8} {'n':>5} {'MAPE':>7} {'的中%':>7} {'方向%':>7}  精度")
    print("-" * 65)
    all_records = []
    prev_fish = None
    for fish in sorted(fish_stats, key=lambda f: -len(fish_stats[f])):
        for a5 in AREAS:
            recs = combo_stats.get((fish, a5), [])
            if not recs:
                continue
            m, h, d, n = stat(recs)
            if m is None:
                continue
            grade = "A" if m < 40 else "B" if m < 60 else "C" if m < 90 else "D"
            if fish != prev_fish:
                prev_fish = fish
            print(f"  {fish:<10} {a5:<8} {n:>5}  {m:>6.1f}%  {h:>6.1f}%  {d:>6.1f}%  [{grade}]")
            all_records.extend(recs)
        # 魚種小計
        m, h, d, n = stat(fish_stats[fish])
        if m is not None:
            print(f"  {'  └'+fish+'計':<18} {n:>5}  {m:>6.1f}%  {h:>6.1f}%  {d:>6.1f}%")
        print()

    # 全体
    print("-" * 65)
    m, h, d, n = stat(records)
    if m:
        print(f"  {'全体':<18} {n:>5}  {m:>6.1f}%  {h:>6.1f}%  {d:>6.1f}%")

    # ベースラインソース内訳
    src_count = defaultdict(int)
    for r in records:
        src_count[r["baseline_src"]] += 1
    print(f"\nベースラインソース: " +
          ", ".join(f"{k}:{v}件" for k, v in sorted(src_count.items())))

    # ── 予測例（直近10件） ────────────────────────────────────────
    print(f"\n{'='*65}")
    print("予測例（直近データ）")
    print("=" * 65)
    recent = sorted(records, key=lambda r: r["date"], reverse=True)
    shown, count = set(), 0
    for r in recent:
        key = (r["date"], r["fish"], r["area5"])
        if key in shown or count >= 10:
            break
        shown.add(key)
        count += 1
        res = r["result"]
        hit = "✓ 的中" if r["in_range"] else "✗ 外れ"
        print(f"\n📅 {r['date']} | {r['area5']} ({r['area']}) | {r['fish']}")
        print(f"   予測: {r['cnt_min']}〜{r['cnt_max']}匹 (avg {r['predicted']})")
        print(f"   実績: {r['actual']}匹  誤差: {r['error']}%  {hit}")
        print(f"   気象補正: ×{r['wx_coef']}")
        for reason in res["reasons"]:
            print(f"   {reason}")

    # ── JSON出力 ─────────────────────────────────────────────────
    m_all, h_all, d_all, n_all = stat(records)
    out = {
        "generated_at":    datetime.now().strftime("%Y/%m/%d %H:%M"),
        "model_version":   "v4_doy_fallback",
        "validation_days": n_dates,
        "total_records":   len(records),
        "overall_mape":    m_all,
        "overall_hit_rate": h_all,
        "combo_stats": {
            f"{fish}×{a5}": {"n": n, "mape": m, "hit_rate": h, "dir_rate": d}
            for (fish, a5), recs in combo_stats.items()
            for m, h, d, n in [stat(recs)] if m is not None
        },
        "records": [
            {k: v for k, v in r.items() if k != "result"}
            for r in records
        ],
    }
    with open("backtest_v2_result.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"\n詳細 → backtest_v2_result.json")


if __name__ == "__main__":
    main()
