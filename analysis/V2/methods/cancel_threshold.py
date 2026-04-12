#!/usr/bin/env python3
"""
cancel_threshold.py — 船宿ごとの「確実欠航閾値」を実データから計算

[設計方針]
  閾値の定義: 「この波高/風速以上になると欠航率 >= 80% になる最低ライン」
  = 船宿が持つ「ここまでなら行く」という限界値
  ≠ 欠航率50%点（精度が低かった旧実装）

  季節別閾値: 閾値がシーズンによって変わるかも検証
  → 欠航件数が十分な船宿（欠航 >= 30件）で季節別分析

[出力]
  analysis.sqlite: cancel_thresholds（更新）, cancel_thresholds_seasonal（新規）
  cancel_threshold.txt: 人間が読める一覧
"""
import csv, json, os, sqlite3
from collections import defaultdict
from datetime import datetime

import sys as _sys; _sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _paths import ROOT_DIR, RESULTS_DIR, DATA_DIR, NORMALIZE_DIR, OCEAN_DIR
DB_ANA        = os.path.join(RESULTS_DIR, "analysis.sqlite")
DB_WX         = os.path.join(OCEAN_DIR, "weather_cache.sqlite")
OUT_TXT       = os.path.join(RESULTS_DIR, "cancel_threshold.txt")
OVERRIDE_FILE = os.path.join(NORMALIZE_DIR, "ship_wx_coord_override.json")

MIN_CANCEL_RATE  = 0.80   # 閾値上での最低欠航率（確実欠航の定義）
MIN_CANCEL_ABOVE = 3      # 閾値上の欠航件数の最低数
MIN_CANCEL_TOTAL = 3      # 船宿全体の最低欠航件数
MIN_CANCEL_SEASONAL = 10  # 季節別分析に必要な最低欠航件数

SEASONS = {
    "春(3-5月)":  [3, 4, 5],
    "夏(6-8月)":  [6, 7, 8],
    "秋(9-11月)": [9, 10, 11],
    "冬(12-2月)": [12, 1, 2],
}

def load_exclude_ships():
    path = os.path.join(ROOT_DIR, "crawl", "ships.json")
    try:
        with open(path, encoding="utf-8") as f:
            ships = json.load(f)
        return {s["name"] for s in ships if s.get("exclude") or s.get("boat_only")}
    except Exception:
        return set()

EXCLUDE_SHIPS = load_exclude_ships()

def load_wx_overrides():
    """ship_wx_coord_override.json から湾内船宿の座標オーバーライドを読み込む"""
    try:
        with open(OVERRIDE_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return {ship: (info["lat"], info["lon"])
                for ship, info in data.get("overrides", {}).items()}
    except Exception:
        return {}

def load_ship_coords():
    conn = sqlite3.connect(DB_ANA)
    rows = conn.execute(
        "SELECT ship, AVG(lat), AVG(lon) FROM combo_meta WHERE lat IS NOT NULL GROUP BY ship"
    ).fetchall()
    conn.close()
    coords = {ship: (round(lat, 3), round(lon, 3)) for ship, lat, lon in rows}
    # 湾内船宿の座標オーバーライドを適用
    overrides = load_wx_overrides()
    for ship, (lat, lon) in overrides.items():
        coords[ship] = (lat, lon)
    return coords

def load_wx_coords():
    conn = sqlite3.connect(DB_WX)
    coords = conn.execute("SELECT DISTINCT lat, lon FROM weather").fetchall()
    conn.close()
    return [(lat, lon) for lat, lon in coords]

def nearest_coord(lat, lon, coords):
    return min(coords, key=lambda c: (c[0]-lat)**2 + (c[1]-lon)**2)

def get_daily_wx(conn_wx, lat, lon, date_str):
    rows = conn_wx.execute("""
        SELECT wave_height, wind_speed
        FROM weather
        WHERE lat=? AND lon=? AND dt LIKE ?
        ORDER BY ABS(CAST(substr(dt,12,2) AS INT) - 6)
        LIMIT 1
    """, (lat, lon, f"{date_str}%")).fetchone()
    return rows

# 天候欠航とみなす cancel_type（これ以外の欠航は閾値計算から除外）
WEATHER_CANCEL_TYPES = {"荒天", "台風"}

def load_records():
    """釣果CSVから船宿×日次レコードを読み込む。

    欠航の扱い:
      - cancel_type が 荒天/台風 → is_weather_cancel=True（閾値計算の欠航側に含める）
      - cancel_type が 定休日/中止 → is_weather_cancel=False（閾値計算から除外）
      - cancel_type が 不明 → is_weather_cancel=None（海況が閾値超えなら欠航側、以下なら除外）
    """
    records = []
    for fn in sorted(os.listdir(DATA_DIR)):
        if not fn.endswith(".csv") or fn == "cancellations.csv":
            continue
        with open(os.path.join(DATA_DIR, fn), encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                ship = row.get("ship", "").strip()
                date = row.get("date", "").strip()
                if not ship or not date:
                    continue
                if ship in EXCLUDE_SHIPS:
                    continue
                is_cancel = row.get("is_cancellation") == "1"
                cancel_type = (row.get("cancel_type") or "").strip()
                try:
                    month = int(date.split("/")[1])
                except Exception:
                    month = 0
                # 天候欠航フラグ
                if not is_cancel:
                    is_weather_cancel = False
                elif cancel_type in WEATHER_CANCEL_TYPES:
                    is_weather_cancel = True
                elif cancel_type in ("定休日", "中止"):
                    is_weather_cancel = False   # 除外対象
                else:
                    is_weather_cancel = None    # 不明: 海況で判定
                records.append({
                    "ship": ship, "date": date,
                    "tsuri_mono": row.get("tsuri_mono", "").strip(),
                    "is_cancel": is_cancel,
                    "is_weather_cancel": is_weather_cancel,
                    "month": month,
                })
    return records

def certainty_threshold(cancel_vals, ok_vals,
                        min_rate=MIN_CANCEL_RATE,
                        min_above=MIN_CANCEL_ABOVE):
    """
    「確実欠航閾値」: P(欠航 | 波高 >= T) >= min_rate となる最低の T を返す。

    最低値を返す理由: できるだけカバレッジを広く保ちながら
                    精度(min_rate)を担保するため。

    戻り値: (threshold, actual_cancel_rate, n_cancel_above, n_ok_above)
    """
    if not cancel_vals:
        return None, None, 0, 0

    # 昇順にスキャン → 最初に条件を満たす T を返す
    all_vals = sorted(set(cancel_vals + ok_vals))
    for thr in all_vals:
        c_above = sum(1 for v in cancel_vals if v >= thr)
        o_above = sum(1 for v in ok_vals if v >= thr)
        total   = c_above + o_above
        if c_above < min_above or total == 0:
            continue
        rate = c_above / total
        if rate >= min_rate:
            return thr, rate, c_above, o_above

    return None, None, len(cancel_vals), len(ok_vals)

def coverage(cancel_vals, threshold):
    """閾値以上の欠航件数 / 全欠航件数（Recall相当）"""
    if not cancel_vals or threshold is None:
        return None
    return sum(1 for v in cancel_vals if v >= threshold) / len(cancel_vals)

def get_season(month):
    for name, months in SEASONS.items():
        if month in months:
            return name
    return "不明"

def main():
    print("=== cancel_threshold.py 開始 ===")
    print(f"  閾値定義: 欠航率 >= {MIN_CANCEL_RATE*100:.0f}% になる最低波高・風速")
    print(f"  [2パス] 荒天+台風で初期閾値 → 定休日/中止/不明を海況で再分類")

    ship_coords = load_ship_coords()
    wx_coords   = load_wx_coords()
    records     = load_records()
    print(f"レコード: {len(records):,}件 / 座標あり船宿: {len(ship_coords)}件")

    # 船宿×日付でユニーク化（天候欠航優先: True > None > False > 出船）
    def _priority(r):
        wc = r.get("is_weather_cancel")
        if wc is True:  return 3
        if wc is None and r["is_cancel"]: return 2
        if r["is_cancel"]: return 1
        return 0
    ship_dates = {}
    for r in records:
        key = (r["ship"], r["date"])
        if key not in ship_dates or _priority(r) > _priority(ship_dates[key]):
            ship_dates[key] = r

    # ── 気象データ一括取得 ────────────────────────────────────────────────
    conn_wx = sqlite3.connect(DB_WX)
    wx_cache = {}
    # (ship, date) → (wave, wind, month, is_cancel, is_weather_cancel)
    ship_day_wx = {}

    for key, r in ship_dates.items():
        ship, date_str = r["ship"], r["date"]
        if ship not in ship_coords:
            continue
        slat, slon = ship_coords[ship]
        wlat, wlon = nearest_coord(slat, slon, wx_coords)
        date_iso = date_str.replace("/", "-")
        cache_key = (wlat, wlon, date_iso)
        if cache_key not in wx_cache:
            wx_cache[cache_key] = get_daily_wx(conn_wx, wlat, wlon, date_iso)
        wx = wx_cache[cache_key]
        if not wx or wx[0] is None:
            continue
        ship_day_wx[key] = (wx[0], wx[1], r["month"], r["is_cancel"], r["is_weather_cancel"])

    conn_wx.close()
    print(f"海況マッチ: {len(ship_day_wx)}/{len(ship_dates)}件")

    # ── パス1: 荒天+台風のみで初期閾値を計算 ────────────────────────────
    print("  [Pass 1] 荒天+台風のみで初期閾値を計算中...")
    init_ship_data = defaultdict(lambda: {"wave": [], "wind": []})
    for (ship, _), (wave, wind, month, is_cancel, is_wc) in ship_day_wx.items():
        if is_cancel:
            if is_wc is not True:   # 荒天/台風以外はスキップ
                continue
            flag = True
        else:
            flag = False
        if wave is not None:
            init_ship_data[ship]["wave"].append((wave, month, flag))
        if wind is not None:
            init_ship_data[ship]["wind"].append((wind, month, flag))

    # 全cancel_type込みのフォールバック用データも同時構築
    fallback_ship_data = defaultdict(lambda: {"wave": [], "wind": []})
    for (ship, _), (wave, wind, month, is_cancel, is_wc) in ship_day_wx.items():
        flag = is_cancel   # cancel_type問わず全欠航を欠航扱い
        if wave is not None:
            fallback_ship_data[ship]["wave"].append((wave, month, flag))
        if wind is not None:
            fallback_ship_data[ship]["wind"].append((wind, month, flag))

    init_thresholds = {}   # ship -> (wave_thr, wind_thr)
    fallback_used = 0
    for ship in set(list(init_ship_data.keys()) + list(fallback_ship_data.keys())):
        d = init_ship_data.get(ship, {"wave": [], "wind": []})
        cw = [w for w, m, c in d["wave"] if c]
        ow = [w for w, m, c in d["wave"] if not c]
        cv = [w for w, m, c in d["wind"] if c]
        ov = [w for w, m, c in d["wind"] if not c]
        wt, _, _, _ = certainty_threshold(cw, ow)
        vt, _, _, _ = certainty_threshold(cv, ov)
        # 荒天/台風だけでは閾値が出なかった場合 → 全cancel_typeでフォールバック
        if wt is None and vt is None:
            fd = fallback_ship_data.get(ship, {"wave": [], "wind": []})
            fcw = [w for w, m, c in fd["wave"] if c]
            fow = [w for w, m, c in fd["wave"] if not c]
            fcv = [w for w, m, c in fd["wind"] if c]
            fov = [w for w, m, c in fd["wind"] if not c]
            wt, _, _, _ = certainty_threshold(fcw, fow)
            vt, _, _, _ = certainty_threshold(fcv, fov)
            if wt is not None or vt is not None:
                fallback_used += 1
        init_thresholds[ship] = (wt, vt)
    print(f"  初期閾値: {sum(1 for wt,vt in init_thresholds.values() if wt or vt)}船宿（うち全cancel_typeフォールバック: {fallback_used}件）")

    # ── パス2: 定休日/中止/不明を初期閾値で再分類してship_dataを再構築 ──
    print("  [Pass 2] 定休日/中止/不明を海況で再分類中...")
    ship_data = defaultdict(lambda: {"wave": [], "wind": []})
    reclassified = 0

    for (ship, _), (wave, wind, month, is_cancel, is_wc) in ship_day_wx.items():
        wave_thr, wind_thr = init_thresholds.get(ship, (None, None))

        if is_cancel:
            if is_wc is True:
                # 明示的天候欠航 → そのまま
                effective = True
            elif is_wc is False:
                # 定休日/中止: 海況が初期閾値を超えていれば天候欠航として格上げ
                wx_bad = (wave_thr is not None and wave is not None and wave >= wave_thr) or \
                         (wind_thr is not None and wind is not None and wind >= wind_thr)
                if wx_bad:
                    effective = True
                    reclassified += 1
                else:
                    continue   # 天候と無関係 → 両側に含めない
            else:
                # 不明: 同様に海況で判定
                wx_bad = (wave_thr is not None and wave is not None and wave >= wave_thr) or \
                         (wind_thr is not None and wind is not None and wind >= wind_thr)
                effective = wx_bad
        else:
            effective = False   # 出船日

        if wave is not None:
            ship_data[ship]["wave"].append((wave, month, effective))
        if wind is not None:
            ship_data[ship]["wind"].append((wind, month, effective))

    print(f"  再分類された天候欠航: {reclassified}件（定休日/中止/不明 → 荒天格上げ）")

    # ── コンボ（船宿×釣り物）レベルのデータ構築 ─────────────────────────────
    print("  [Combo] 船宿×釣り物レベルの閾値を計算中...")

    # (ship, tsuri_mono, date) でユニーク化（同じ優先度ロジック）
    combo_dates = {}
    for r in records:
        tsuri = r.get("tsuri_mono", "")
        if not tsuri:
            continue
        key = (r["ship"], tsuri, r["date"])
        if key not in combo_dates or _priority(r) > _priority(combo_dates[key]):
            combo_dates[key] = r

    # 気象データ紐付け（wx_cache を再利用、不足分は再クエリ）
    conn_wx_c = sqlite3.connect(DB_WX)
    combo_data = defaultdict(lambda: {"wave": [], "wind": []})
    for (ship, tsuri, date_str), r in combo_dates.items():
        if ship not in ship_coords:
            continue
        slat, slon = ship_coords[ship]
        wlat, wlon = nearest_coord(slat, slon, wx_coords)
        date_iso = date_str.replace("/", "-")
        cache_key = (wlat, wlon, date_iso)
        if cache_key not in wx_cache:
            wx_cache[cache_key] = get_daily_wx(conn_wx_c, wlat, wlon, date_iso)
        wx = wx_cache[cache_key]
        if not wx or wx[0] is None:
            continue
        wave, wind = wx[0], wx[1]
        wave_thr, wind_thr = init_thresholds.get(ship, (None, None))
        is_cancel = r["is_cancel"]
        is_wc     = r["is_weather_cancel"]

        # Pass 2 と同じ再分類ロジック（船宿レベル初期閾値を使用）
        if is_cancel:
            if is_wc is True:
                effective = True
            elif is_wc is False:
                wx_bad = (wave_thr is not None and wave is not None and wave >= wave_thr) or \
                         (wind_thr is not None and wind is not None and wind >= wind_thr)
                if wx_bad:
                    effective = True
                else:
                    continue   # 天候と無関係 → 除外
            else:
                wx_bad = (wave_thr is not None and wave is not None and wave >= wave_thr) or \
                         (wind_thr is not None and wind is not None and wind >= wind_thr)
                effective = wx_bad
        else:
            effective = False

        combo_key = (ship, tsuri)
        if wave is not None:
            combo_data[combo_key]["wave"].append((wave, r["month"], effective))
        if wind is not None:
            combo_data[combo_key]["wind"].append((wind, r["month"], effective))
    conn_wx_c.close()
    print(f"  コンボ海況マッチ: {sum(len(d['wave']) for d in combo_data.values())}件 / コンボ数: {len(combo_data)}件")

    # コンボ閾値を計算
    combo_results = []
    for (ship, tsuri), d in combo_data.items():
        cancel_wave = [w for w, m, c in d["wave"] if c]
        ok_wave     = [w for w, m, c in d["wave"] if not c]
        cancel_wind = [w for w, m, c in d["wind"] if c]
        ok_wind     = [w for w, m, c in d["wind"] if not c]
        nc = len(cancel_wave)
        if nc < MIN_CANCEL_TOTAL:
            continue
        wave_thr2, wave_rate2, _, _ = certainty_threshold(cancel_wave, ok_wave)
        wind_thr2, wind_rate2, _, _ = certainty_threshold(cancel_wind, ok_wind)
        wave_cov2 = coverage(cancel_wave, wave_thr2)
        combo_results.append({
            "ship": ship, "tsuri_mono": tsuri,
            "n_cancel": nc, "n_ok": len(ok_wave),
            "wave_threshold":   round(wave_thr2, 2) if wave_thr2 else None,
            "wave_cancel_rate": round(wave_rate2, 2) if wave_rate2 else None,
            "wave_coverage":    round(wave_cov2, 2) if wave_cov2 else None,
            "wind_threshold":   round(wind_thr2, 2) if wind_thr2 else None,
            "wind_cancel_rate": round(wind_rate2, 2) if wind_rate2 else None,
        })
    combo_results.sort(key=lambda x: (-x["n_cancel"], x["ship"]))
    print(f"  コンボ閾値: {len(combo_results)}件（うち波高閾値あり: {sum(1 for r in combo_results if r['wave_threshold'])}件）")

    # ── 全期間閾値 ──────────────────────────────────────────────────────────
    results = []
    for ship, d in ship_data.items():
        cancel_wave = [w for w, m, c in d["wave"] if c]
        ok_wave     = [w for w, m, c in d["wave"] if not c]
        cancel_wind = [w for w, m, c in d["wind"] if c]
        ok_wind     = [w for w, m, c in d["wind"] if not c]

        nc = len(cancel_wave)
        if nc < MIN_CANCEL_TOTAL:
            continue

        wave_thr, wave_rate, wave_nc_above, wave_no_above = certainty_threshold(cancel_wave, ok_wave)
        wind_thr, wind_rate, wind_nc_above, wind_no_above = certainty_threshold(cancel_wind, ok_wind)

        wave_cov = coverage(cancel_wave, wave_thr)
        wind_cov = coverage(cancel_wind, wind_thr)

        avg_cancel_wave = sum(cancel_wave)/len(cancel_wave) if cancel_wave else None
        avg_ok_wave     = sum(ok_wave)/len(ok_wave) if ok_wave else None

        results.append({
            "ship":             ship,
            "n_cancel":         nc,
            "n_ok":             len(ok_wave),
            "cancel_wave_avg":  round(avg_cancel_wave, 2) if avg_cancel_wave else None,
            "ok_wave_avg":      round(avg_ok_wave, 2) if avg_ok_wave else None,
            "wave_threshold":   round(wave_thr, 2) if wave_thr else None,
            "wave_cancel_rate": round(wave_rate, 2) if wave_rate else None,
            "wave_coverage":    round(wave_cov, 2) if wave_cov else None,
            "wind_threshold":   round(wind_thr, 2) if wind_thr else None,
            "wind_cancel_rate": round(wind_rate, 2) if wind_rate else None,
            "wind_coverage":    round(wind_cov, 2) if wind_cov else None,
        })

    results.sort(key=lambda x: -x["n_cancel"])

    # ── 季節別閾値（欠航件数が多い船宿のみ） ─────────────────────────────
    seasonal_results = []
    for ship, d in ship_data.items():
        total_cancel = sum(1 for _, _, c in d["wave"] if c)
        if total_cancel < MIN_CANCEL_SEASONAL:
            continue
        for season_name, months in SEASONS.items():
            cancel_wave = [w for w, m, c in d["wave"] if c and m in months]
            ok_wave     = [w for w, m, c in d["wave"] if not c and m in months]
            cancel_wind = [w for w, m, c in d["wind"] if c and m in months]
            ok_wind     = [w for w, m, c in d["wind"] if not c and m in months]
            nc = len(cancel_wave)
            if nc < 3:
                continue
            wave_thr, wave_rate, _, _ = certainty_threshold(cancel_wave, ok_wave, min_above=2)
            wind_thr, wind_rate, _, _ = certainty_threshold(cancel_wind, ok_wind, min_above=2)
            wave_cov = coverage(cancel_wave, wave_thr)
            seasonal_results.append({
                "ship":           ship,
                "season":         season_name,
                "n_cancel":       nc,
                "n_ok":           len(ok_wave),
                "wave_threshold": round(wave_thr, 2) if wave_thr else None,
                "wave_cancel_rate": round(wave_rate, 2) if wave_rate else None,
                "wave_coverage":  round(wave_cov, 2) if wave_cov else None,
                "wind_threshold": round(wind_thr, 2) if wind_thr else None,
                "wind_cancel_rate": round(wind_rate, 2) if wind_rate else None,
            })

    # ── DB保存 ─────────────────────────────────────────────────────────────
    conn_ana = sqlite3.connect(DB_ANA)

    conn_ana.execute("DROP TABLE IF EXISTS cancel_thresholds")
    conn_ana.execute("""
        CREATE TABLE cancel_thresholds (
            ship              TEXT PRIMARY KEY,
            n_cancel          INTEGER,
            n_ok              INTEGER,
            cancel_wave_avg   REAL,
            ok_wave_avg       REAL,
            wave_threshold    REAL,
            wave_cancel_rate  REAL,
            wave_coverage     REAL,
            wind_threshold    REAL,
            wind_cancel_rate  REAL,
            wind_coverage     REAL
        )
    """)
    for r in results:
        conn_ana.execute("INSERT INTO cancel_thresholds VALUES (?,?,?,?,?,?,?,?,?,?,?)", (
            r["ship"], r["n_cancel"], r["n_ok"],
            r["cancel_wave_avg"], r["ok_wave_avg"],
            r["wave_threshold"], r["wave_cancel_rate"], r["wave_coverage"],
            r["wind_threshold"], r["wind_cancel_rate"], r["wind_coverage"],
        ))

    conn_ana.execute("DROP TABLE IF EXISTS cancel_thresholds_combo")
    conn_ana.execute("""
        CREATE TABLE cancel_thresholds_combo (
            ship              TEXT,
            tsuri_mono        TEXT,
            n_cancel          INTEGER,
            n_ok              INTEGER,
            wave_threshold    REAL,
            wave_cancel_rate  REAL,
            wave_coverage     REAL,
            wind_threshold    REAL,
            wind_cancel_rate  REAL,
            PRIMARY KEY (ship, tsuri_mono)
        )
    """)
    for r in combo_results:
        conn_ana.execute("INSERT INTO cancel_thresholds_combo VALUES (?,?,?,?,?,?,?,?,?)", (
            r["ship"], r["tsuri_mono"], r["n_cancel"], r["n_ok"],
            r["wave_threshold"], r["wave_cancel_rate"], r["wave_coverage"],
            r["wind_threshold"], r["wind_cancel_rate"],
        ))

    conn_ana.execute("DROP TABLE IF EXISTS cancel_thresholds_seasonal")
    conn_ana.execute("""
        CREATE TABLE cancel_thresholds_seasonal (
            ship              TEXT,
            season            TEXT,
            n_cancel          INTEGER,
            n_ok              INTEGER,
            wave_threshold    REAL,
            wave_cancel_rate  REAL,
            wave_coverage     REAL,
            wind_threshold    REAL,
            wind_cancel_rate  REAL,
            PRIMARY KEY (ship, season)
        )
    """)
    for r in seasonal_results:
        conn_ana.execute("INSERT INTO cancel_thresholds_seasonal VALUES (?,?,?,?,?,?,?,?,?)", (
            r["ship"], r["season"], r["n_cancel"], r["n_ok"],
            r["wave_threshold"], r["wave_cancel_rate"], r["wave_coverage"],
            r["wind_threshold"], r["wind_cancel_rate"],
        ))

    conn_ana.commit()
    conn_ana.close()

    # ── テキスト出力 ────────────────────────────────────────────────────────
    lines = [
        f"# 船宿別 確実欠航閾値（欠航率 >= {MIN_CANCEL_RATE*100:.0f}% になる最低波高・風速）",
        f"# 生成: {datetime.now().strftime('%Y/%m/%d %H:%M')}",
        f"# 対象船宿: {len(results)}件",
        "",
        "  [列の説明]",
        "  波高閾値: この値以上の日は欠航率 >= 80%（確実欠航ライン）",
        "  カバー率: 実際の欠航のうち閾値以上で検出できた割合",
        "  ※ カバー率が低い = 荒天以外の理由（機械故障・行事等）で欠航している船宿",
        "",
        f"  {'船宿':<14} {'欠航':>5} {'出船':>6} {'欠航波高平均':>10} {'出船波高平均':>10} "
        f"{'波高閾値':>8} {'欠航率':>6} {'カバー率':>8}  {'風速閾値':>8} {'欠航率':>6}",
        "-" * 100,
    ]
    for r in results:
        wt  = f"{r['wave_threshold']}m" if r['wave_threshold'] else "-"
        wr  = f"{r['wave_cancel_rate']*100:.0f}%" if r['wave_cancel_rate'] else "-"
        wc  = f"{r['wave_coverage']*100:.0f}%" if r['wave_coverage'] else "-"
        wnd = f"{r['wind_threshold']}m/s" if r['wind_threshold'] else "-"
        wdr = f"{r['wind_cancel_rate']*100:.0f}%" if r['wind_cancel_rate'] else "-"
        lines.append(
            f"  {r['ship']:<14} {r['n_cancel']:>5} {r['n_ok']:>6} "
            f"  {r['cancel_wave_avg'] or '-':>8}m   {r['ok_wave_avg'] or '-':>8}m "
            f"  {wt:>7} {wr:>6} {wc:>8}   {wnd:>8} {wdr:>6}"
        )

    # 季節別閾値（欠航件数が多い船宿）
    ships_with_seasonal = sorted(set(r["ship"] for r in seasonal_results))
    if ships_with_seasonal:
        lines += ["", "=" * 80, "【季節別閾値】", "=" * 80]
        for ship in ships_with_seasonal:
            ship_seasonal = [r for r in seasonal_results if r["ship"] == ship]
            total_cancel = sum(r["n_cancel"] for r in ship_seasonal)
            lines += ["", f"  ▼ {ship}（年間欠航 {total_cancel}件）"]
            lines.append(
                f"    {'季節':<12} {'欠航':>5} {'出船':>6} {'波高閾値':>8} {'欠航率':>6} {'カバー率':>8}  {'風速閾値':>8} {'欠航率':>6}"
            )
            lines.append("    " + "-" * 65)
            for r in sorted(ship_seasonal, key=lambda x: list(SEASONS.keys()).index(x["season"])):
                wt  = f"{r['wave_threshold']}m" if r['wave_threshold'] else "データ不足"
                wr  = f"{r['wave_cancel_rate']*100:.0f}%" if r['wave_cancel_rate'] else "-"
                wc  = f"{r['wave_coverage']*100:.0f}%" if r['wave_coverage'] else "-"
                wnd = f"{r['wind_threshold']}m/s" if r['wind_threshold'] else "-"
                wdr = f"{r['wind_cancel_rate']*100:.0f}%" if r['wind_cancel_rate'] else "-"
                lines.append(
                    f"    {r['season']:<12} {r['n_cancel']:>5} {r['n_ok']:>6} "
                    f"  {wt:>7} {wr:>6} {wc:>8}   {wnd:>7} {wdr:>6}"
                )

    # 全体サマリー
    valid_thr = [r["wave_threshold"] for r in results if r["wave_threshold"]]
    valid_cov = [r["wave_coverage"] for r in results if r["wave_coverage"]]
    if valid_thr:
        lines += [
            "", "=" * 80, "【全船宿集計】",
            f"  波高閾値の中央値: {sorted(valid_thr)[len(valid_thr)//2]:.2f}m",
            f"  波高閾値の最小:   {min(valid_thr):.2f}m（最も繊細）",
            f"  波高閾値の最大:   {max(valid_thr):.2f}m（最も頑丈）",
            f"  平均カバー率:     {sum(valid_cov)/len(valid_cov)*100:.0f}%（欠航のうち閾値上で検出できた割合）",
            f"  ※ カバー率 < 50% の船宿は海況以外の欠航理由が多い可能性あり",
        ]

    # コンボ（船宿×釣り物）閾値のサマリー
    if combo_results:
        lines += ["", "=" * 80, "【船宿×釣り物 コンボ別閾値】",
                  "  ※ 欠航率 >= 80% になる波高・風速閾値（釣り物ごとに異なる出漁エリア・季節を反映）",
                  ""]
        lines.append(
            f"  {'船宿':<14} {'釣り物':<12} {'欠航':>5} {'出船':>6} {'波高閾値':>8} {'欠航率':>6} {'カバー率':>8}  {'風速閾値':>8} {'欠航率':>6}"
        )
        lines.append("-" * 100)
        for r in combo_results:
            wt  = f"{r['wave_threshold']}m"   if r['wave_threshold']   else "-"
            wr  = f"{r['wave_cancel_rate']*100:.0f}%" if r['wave_cancel_rate'] else "-"
            wc  = f"{r['wave_coverage']*100:.0f}%"   if r['wave_coverage']    else "-"
            wnd = f"{r['wind_threshold']}m/s" if r['wind_threshold']   else "-"
            wdr = f"{r['wind_cancel_rate']*100:.0f}%" if r['wind_cancel_rate'] else "-"
            lines.append(
                f"  {r['ship']:<14} {r['tsuri_mono']:<12} {r['n_cancel']:>5} {r['n_ok']:>6} "
                f"  {wt:>7} {wr:>6} {wc:>8}   {wnd:>8} {wdr:>6}"
            )
        lines += [
            "",
            f"  コンボ閾値あり: {sum(1 for r in combo_results if r['wave_threshold'])}件 / 全{len(combo_results)}コンボ",
            "  ※ コンボ閾値がない場合は船宿レベル閾値にフォールバック",
        ]

    with open(OUT_TXT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"保存: {len(results)}船宿 → cancel_thresholds")
    print(f"保存: {len(combo_results)}件 → cancel_thresholds_combo")
    print(f"保存: {len(seasonal_results)}件 → cancel_thresholds_seasonal")
    print(f"保存: {OUT_TXT}")

if __name__ == "__main__":
    main()
