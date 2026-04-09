#!/usr/bin/env python3
"""
prediction_log.py — フェーズ2: 予測ログ蓄積・答え合わせ

毎日 daily_predict() で今日+7日の全★3以上コンボを予測して記録し、
target_date が過ぎたら match_actuals() で実績と照合して精度を計算する。

使い方:
  python prediction_log.py --predict            # 今日+7日 予測INSERT
  python prediction_log.py --match              # 昨日以前の実績照合
  python prediction_log.py --both               # predict + match を両方
  python prediction_log.py --predict --dry-run  # 件数確認のみ（DB書き込みなし）
  python prediction_log.py --stats              # 蓄積状況サマリー表示

テーブル: analysis.sqlite / prediction_log

列の役割:
  baseline_cnt         旬別ベースライン（combo_decadal avg_cnt）
  pred_pct             (pred_cnt_avg / baseline_cnt - 1) * 100  ← design/V2 ZONE B' 無料表示用
  actual_pct           (actual_cnt_avg / baseline_cnt - 1) * 100 ← match後に計算
  fcast_wave/wind/sst  予報値 → 将来の気象誤差分析に使用
  is_good_hit          3分類一致フラグ (0/1) ← 的中バッジ用
"""

import argparse, csv, json, os, sqlite3, sys, urllib.request
from datetime import datetime, timedelta, date

sys.stdout.reconfigure(encoding="utf-8")

import sys as _sys
# predict/ は methods/ の兄弟フォルダ。_paths.py は methods/ にある。
_sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "methods"))
from _paths import ROOT_DIR, RESULTS_DIR, DATA_DIR, OCEAN_DIR

DB_PATH      = os.path.join(RESULTS_DIR, "analysis.sqlite")
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
MARINE_URL   = "https://marine-api.open-meteo.com/v1/marine"


# ── ユーティリティ ──────────────────────────────────────────────────────────────

def _today() -> str:
    return date.today().strftime("%Y/%m/%d")

def _date_add(date_str: str, days: int) -> str:
    d = datetime.strptime(date_str.replace("-", "/"), "%Y/%m/%d")
    return (d + timedelta(days=days)).strftime("%Y/%m/%d")

def _decade_of(date_str: str) -> int:
    """YYYY/MM/DD → 旬番号 1-36"""
    date_str = date_str.replace("-", "/")
    try:
        d   = datetime.strptime(date_str, "%Y/%m/%d")
        dec = 1 if d.day <= 10 else (2 if d.day <= 20 else 3)
        return (d.month - 1) * 3 + dec
    except Exception:
        return 0

def _get_season(date_str: str) -> str:
    """YYYY/MM/DD → 春/夏/秋/冬"""
    m = int(date_str.replace("-", "/").split("/")[1])
    return {12: "冬", 1: "冬", 2: "冬",
            3: "春", 4: "春", 5: "春",
            6: "夏", 7: "夏", 8: "夏",
            9: "秋", 10: "秋", 11: "秋"}[m]

def _calc_stars(wmape: float, n: int) -> int:
    """wmape + サンプル数 → ★1〜5"""
    if   wmape < 25 and n >= 50: return 5
    elif wmape < 35 and n >= 30: return 4
    elif wmape < 50 and n >= 20: return 3
    elif wmape < 65 and n >= 10: return 2
    else:                        return 1

def _classify3(value: float, p33: float, p67: float) -> int:
    """値を 0(釣れない) / 1(普通) / 2(釣れる) に分類"""
    if value is None: return 1
    if value <= p33:  return 0
    if value >= p67:  return 2
    return 1

def _pct_vs_baseline(cnt: float, baseline: float) -> float | None:
    """(cnt / baseline - 1) * 100。baseline が0/Noneなら None。"""
    if not baseline or baseline <= 0: return None
    return round((cnt / baseline - 1) * 100, 1)


# ── テーブル初期化 ──────────────────────────────────────────────────────────────

def init_table(conn: sqlite3.Connection):
    conn.execute("""
    CREATE TABLE IF NOT EXISTS prediction_log (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        fish            TEXT,
        ship            TEXT,
        target_date     TEXT,
        pred_date       TEXT,
        horizon         INTEGER,
        -- 予測値（絶対値）
        pred_cnt_avg    REAL,
        pred_cnt_min    REAL,
        pred_cnt_max    REAL,
        pred_stars      INTEGER,
        -- ベースライン比（ZONE B' 表示 + 分析用）
        baseline_cnt    REAL,
        pred_pct        REAL,
        -- 気象予報値（将来の予報誤差分析用）
        fcast_wave      REAL,
        fcast_wind      REAL,
        fcast_sst       REAL,
        fcast_temp      REAL,
        -- 実績（match_actuals で埋まる）
        actual_cnt_avg  REAL,
        actual_cnt_min  REAL,
        actual_cnt_max  REAL,
        actual_pct      REAL,
        actual_wave     REAL,
        actual_wind     REAL,
        -- サイズ予測（有料表示用・データあり魚種のみ）
        pred_size_lo    REAL,
        pred_size_hi    REAL,
        -- サイズ実績（match後）
        actual_size_min REAL,
        actual_size_max REAL,
        -- 精度評価
        wmape           REAL,
        mae             REAL,
        is_good_hit     INTEGER,
        -- タイムスタンプ
        created_at      TEXT,
        matched_at      TEXT,
        UNIQUE(fish, ship, target_date, pred_date)
    )
    """)
    # 既存テーブルへの列追加（テーブルが先に作られていた場合のマイグレーション）
    for col, typ in [("pred_size_lo", "REAL"), ("pred_size_hi", "REAL"),
                     ("actual_size_min", "REAL"), ("actual_size_max", "REAL")]:
        try:
            conn.execute(f"ALTER TABLE prediction_log ADD COLUMN {col} {typ}")
        except sqlite3.OperationalError:
            pass  # 既に存在する
    conn.commit()


# ── 気象予報取得 ────────────────────────────────────────────────────────────────

def _fetch_forecast(lat: float, lon: float, date_str: str) -> dict:
    """
    Open-Meteo Forecast API から target_date の朝 6〜9 時平均を取得。
    失敗時は空 dict。
    """
    d     = datetime.strptime(date_str.replace("-", "/"), "%Y/%m/%d")
    start = d.strftime("%Y-%m-%d")
    wx    = {}
    try:
        params = "&".join([
            f"latitude={lat}", f"longitude={lon}",
            f"start_date={start}", f"end_date={start}",
            "hourly=wind_speed_10m,temperature_2m",
            "timezone=Asia%2FTokyo",
        ])
        with urllib.request.urlopen(f"{FORECAST_URL}?{params}", timeout=8) as resp:
            data = json.loads(resp.read())
        hourly = data.get("hourly", {})
        times  = hourly.get("time", [])
        morning = [t[-5:] in ("06:00", "07:00", "08:00", "09:00") for t in times]
        temps = [hourly["temperature_2m"][i] for i, m in enumerate(morning)
                 if m and hourly["temperature_2m"][i] is not None]
        winds = [hourly["wind_speed_10m"][i] for i, m in enumerate(morning)
                 if m and hourly["wind_speed_10m"][i] is not None]
        if temps: wx["temp"] = round(sum(temps) / len(temps), 1)
        if winds: wx["wind"] = round(sum(winds) / len(winds), 1)
    except Exception:
        pass
    try:
        params = "&".join([
            f"latitude={lat}", f"longitude={lon}",
            f"start_date={start}", f"end_date={start}",
            "hourly=wave_height,sea_surface_temperature",
            "timezone=Asia%2FTokyo",
        ])
        with urllib.request.urlopen(f"{MARINE_URL}?{params}", timeout=8) as resp:
            data = json.loads(resp.read())
        hourly = data.get("hourly", {})
        times  = hourly.get("time", [])
        morning = [t[-5:] in ("06:00", "07:00", "08:00", "09:00") for t in times]
        waves = [hourly["wave_height"][i] for i, m in enumerate(morning)
                 if m and hourly["wave_height"][i] is not None]
        ssts  = [hourly["sea_surface_temperature"][i] for i, m in enumerate(morning)
                 if m and hourly["sea_surface_temperature"][i] is not None]
        if waves: wx["wave"] = round(sum(waves) / len(waves), 2)
        if ssts:  wx["sst"]  = round(sum(ssts)  / len(ssts),  1)
    except Exception:
        pass
    return wx


# ── 対象コンボ取得 ──────────────────────────────────────────────────────────────

def _get_target_combos(conn: sqlite3.Connection, min_stars: int = 3, horizon: int = 7):
    """★min_stars 以上のコンボ一覧を返す"""
    rows = conn.execute("""
        SELECT bt.fish, bt.ship, bt.wmape, cm.n_records, cm.lat, cm.lon
        FROM combo_backtest bt
        JOIN combo_meta cm ON bt.fish=cm.fish AND bt.ship=cm.ship
        WHERE bt.metric='cnt_avg' AND bt.horizon=?
    """, (horizon,)).fetchall()

    result = []
    for fish, ship, wmape, n, lat, lon in rows:
        if wmape is None: wmape = 999.0
        stars = _calc_stars(wmape, n or 0)
        if stars >= min_stars:
            result.append((fish, ship, wmape, n, lat, lon, stars))
    return result


# ── daily_predict ──────────────────────────────────────────────────────────────

def daily_predict(horizon: int = 7, min_stars: int = 3, dry_run: bool = False) -> int:
    """
    今日 + horizon 日後のコンボを予測して prediction_log に INSERT。
    UNIQUE 制約により重複は無視される（同日に複数回実行しても安全）。
    Returns: INSERT した件数
    """
    # predict_combo を predict_count.py からインポート
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "predict_count",
        os.path.join(os.path.dirname(__file__), "..", "methods", "predict_count.py")
    )
    pc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pc)

    conn        = sqlite3.connect(DB_PATH)
    init_table(conn)

    pred_date   = _today()
    target_date = _date_add(pred_date, horizon)
    dekad       = _decade_of(target_date)
    now_str     = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    combos = _get_target_combos(conn, min_stars=min_stars, horizon=horizon)
    print(f"対象: {len(combos)}件 先頭3: {combos[:3]}")

    if dry_run:
        print(f"[dry-run] pred_date={pred_date} target_date={target_date} "
              f"horizon={horizon} min_stars={min_stars}")
        print(f"[dry-run] INSERT予定: {len(combos)}件（既存行はスキップ）")
        conn.close()
        return len(combos)

    # 気象予報キャッシュ（lat/lon単位で1回取得）
    wx_cache: dict[tuple, dict] = {}

    inserted = 0
    skipped  = 0
    for fish, ship, wmape, n, lat, lon, stars in combos:
        pred = pc.predict_combo(conn, fish, ship, target_date)
        if pred is None:
            skipped += 1
            continue

        # ベースライン取得（combo_decadal の旬別平均）
        bl_row = conn.execute(
            "SELECT avg_cnt FROM combo_decadal WHERE fish=? AND ship=? AND decade_no=?",
            (fish, ship, dekad)
        ).fetchone()
        baseline_cnt = bl_row[0] if bl_row else None
        pred_pct     = _pct_vs_baseline(pred["cnt_predicted"], baseline_cnt)

        # 気象予報取得
        fcast_wave = fcast_wind = fcast_sst = fcast_temp = None
        if lat and lon:
            key = (round(lat, 1), round(lon, 1))
            if key not in wx_cache:
                wx_cache[key] = _fetch_forecast(lat, lon, target_date)
            wx = wx_cache[key]
            fcast_wave = wx.get("wave")
            fcast_wind = wx.get("wind")
            fcast_sst  = wx.get("sst")
            fcast_temp = wx.get("temp")

        try:
            conn.execute("""
                INSERT OR IGNORE INTO prediction_log
                    (fish, ship, target_date, pred_date, horizon,
                     pred_cnt_avg, pred_cnt_min, pred_cnt_max, pred_stars,
                     baseline_cnt, pred_pct,
                     pred_size_lo, pred_size_hi,
                     fcast_wave, fcast_wind, fcast_sst, fcast_temp,
                     created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                fish, ship, target_date, pred_date, horizon,
                pred["cnt_predicted"], pred["cnt_lo"], pred["cnt_hi"], stars,
                baseline_cnt, pred_pct,
                pred.get("size_lo"), pred.get("size_hi"),
                fcast_wave, fcast_wind, fcast_sst, fcast_temp,
                now_str
            ))
            if conn.execute("SELECT changes()").fetchone()[0]:
                inserted += 1
        except sqlite3.Error as e:
            print(f"  WARN INSERT failed {fish}×{ship}: {e}", file=sys.stderr)

    conn.commit()
    conn.close()

    print(f"daily_predict: inserted={inserted} skipped={skipped} "
          f"(pred={pred_date} target={target_date})")
    return inserted


# ── match_actuals ──────────────────────────────────────────────────────────────

def _load_csv_for_date(target_date: str) -> list[dict]:
    """target_date (YYYY/MM/DD) の釣果行を data/V2/ CSV から返す。"""
    ym    = target_date.replace("-", "/")[:7]
    yyyy  = ym.split("/")[0]
    mm    = ym.split("/")[1]
    path  = os.path.join(DATA_DIR, f"{yyyy}-{mm}.csv")
    if not os.path.exists(path):
        return []
    rows = []
    with open(path, encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            if row.get("date", "").replace("-", "/") == target_date:
                rows.append(row)
    return rows


def _get_actual(csv_rows: list[dict], fish: str, ship: str) -> dict | None:
    """CSV行から ship + tsuri_mono でメイン釣果を集計して返す。"""
    matched = [
        r for r in csv_rows
        if r.get("ship") == ship
        and r.get("tsuri_mono") == fish
        and r.get("is_cancellation", "0") == "0"
        and r.get("main_sub") in ("メイン", "不明", "")
    ]
    if not matched:
        return None

    def _avg(vals):
        v = [float(x) for x in vals if x not in ("", None)]
        return round(sum(v) / len(v), 1) if v else None

    return {
        "cnt_avg":  _avg([r.get("cnt_avg")  for r in matched]),
        "cnt_min":  _avg([r.get("cnt_min")  for r in matched]),
        "cnt_max":  _avg([r.get("cnt_max")  for r in matched]),
        "size_min": _avg([r.get("size_min") for r in matched]),
        "size_max": _avg([r.get("size_max") for r in matched]),
    }


def match_actuals(dry_run: bool = False) -> int:
    """
    target_date が昨日以前 かつ matched_at IS NULL の行を実績と照合する。
    Returns: UPDATE した件数
    """
    conn = sqlite3.connect(DB_PATH)
    init_table(conn)

    yesterday = _date_add(_today(), -1)

    unmatched = conn.execute("""
        SELECT id, fish, ship, target_date, pred_cnt_avg, baseline_cnt
        FROM prediction_log
        WHERE target_date <= ? AND matched_at IS NULL
        ORDER BY target_date
    """, (yesterday,)).fetchall()

    print(f"対象: {len(unmatched)}件 先頭3: {unmatched[:3]}")

    if dry_run:
        print(f"[dry-run] 照合対象: {len(unmatched)}件 (target_date <= {yesterday})")
        conn.close()
        return len(unmatched)

    # combo_thresholds キャッシュ (fish, ship, season) → (p33, p67)
    thresh = {
        (r[0], r[1], r[3]): (r[4], r[5])
        for r in conn.execute(
            "SELECT fish, ship, metric, season, p33, p67 FROM combo_thresholds "
            "WHERE metric='cnt_avg'"
        ).fetchall()
    }
    # フォールバック: (fish, ship) → 最初の season の閾値
    thresh_fallback: dict[tuple, tuple] = {}
    for (f, s, _), vals in thresh.items():
        if (f, s) not in thresh_fallback:
            thresh_fallback[(f, s)] = vals

    csv_cache: dict[str, list] = {}
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    updated = 0
    no_data = 0

    for row_id, fish, ship, target_date, pred_cnt_avg, baseline_cnt in unmatched:
        if target_date not in csv_cache:
            csv_cache[target_date] = _load_csv_for_date(target_date)

        actual = _get_actual(csv_cache[target_date], fish, ship)
        if actual is None or actual["cnt_avg"] is None:
            no_data += 1
            continue

        act_avg = actual["cnt_avg"]
        act_min = actual["cnt_min"]
        act_max = actual["cnt_max"]

        # ベースライン比（ZONE B' 用）
        actual_pct = _pct_vs_baseline(act_avg, baseline_cnt)

        # 精度計算
        wmape = round(abs(pred_cnt_avg - act_avg) / act_avg * 100, 1) if act_avg > 0 else None
        mae   = round(abs(pred_cnt_avg - act_avg), 2)

        # 3分類一致（的中バッジ）
        season = _get_season(target_date)
        p33, p67 = thresh.get(
            (fish, ship, season),
            thresh_fallback.get((fish, ship), (None, None))
        )
        is_good_hit = None
        if p33 is not None and p67 is not None:
            is_good_hit = 1 if _classify3(pred_cnt_avg, p33, p67) == _classify3(act_avg, p33, p67) else 0

        conn.execute("""
            UPDATE prediction_log
            SET actual_cnt_avg=?, actual_cnt_min=?, actual_cnt_max=?,
                actual_pct=?,
                actual_size_min=?, actual_size_max=?,
                wmape=?, mae=?, is_good_hit=?, matched_at=?
            WHERE id=?
        """, (act_avg, act_min, act_max,
              actual_pct,
              actual.get("size_min"), actual.get("size_max"),
              wmape, mae, is_good_hit, now_str,
              row_id))
        updated += 1

    conn.commit()
    conn.close()

    print(f"match_actuals: updated={updated} no_data={no_data} total={len(unmatched)}")
    return updated


# ── stats ──────────────────────────────────────────────────────────────────────

def show_stats():
    """prediction_log の蓄積状況サマリー"""
    if not os.path.exists(DB_PATH):
        print("analysis.sqlite not found")
        return

    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute("SELECT 1 FROM prediction_log LIMIT 1")
    except sqlite3.OperationalError:
        print("prediction_log テーブルなし（未初期化）")
        conn.close()
        return

    total   = conn.execute("SELECT COUNT(*) FROM prediction_log").fetchone()[0]
    matched = conn.execute(
        "SELECT COUNT(*) FROM prediction_log WHERE matched_at IS NOT NULL"
    ).fetchone()[0]
    pending = conn.execute(
        "SELECT COUNT(*) FROM prediction_log WHERE matched_at IS NULL"
    ).fetchone()[0]

    print("=== prediction_log 蓄積状況 ===")
    print(f"  総レコード: {total}")
    print(f"  照合済み:   {matched}")
    print(f"  照合待ち:   {pending}")

    if matched > 0:
        wm_avg   = conn.execute(
            "SELECT AVG(wmape) FROM prediction_log WHERE wmape IS NOT NULL"
        ).fetchone()[0]
        hit_rate = conn.execute(
            "SELECT AVG(is_good_hit) FROM prediction_log WHERE is_good_hit IS NOT NULL"
        ).fetchone()[0]
        if wm_avg:   print(f"  wMAPE平均:  {wm_avg:.1f}%")
        if hit_rate: print(f"  3分類Hit率: {hit_rate*100:.1f}%")

    # 直近5件の照合結果
    recent = conn.execute("""
        SELECT fish, ship, target_date, pred_pct, actual_pct, is_good_hit
        FROM prediction_log
        WHERE matched_at IS NOT NULL
        ORDER BY matched_at DESC LIMIT 5
    """).fetchall()
    if recent:
        print()
        print("  直近5件 (pred_pct→actual_pct):")
        for r in recent:
            hit  = "○" if r[5] == 1 else ("×" if r[5] == 0 else "-")
            pp   = f"{r[3]:+.0f}%" if r[3] is not None else "---"
            ap   = f"{r[4]:+.0f}%" if r[4] is not None else "---"
            print(f"    {r[0]:<10}{r[1]:<14}{r[2]}  予測{pp}→実績{ap}  {hit}")

    conn.close()


# ── メイン ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="フェーズ2: 予測ログ蓄積・答え合わせ")
    parser.add_argument("--predict",   action="store_true", help="今日+7日を予測してINSERT")
    parser.add_argument("--match",     action="store_true", help="昨日以前の実績照合")
    parser.add_argument("--both",      action="store_true", help="predict + match 両方")
    parser.add_argument("--stats",     action="store_true", help="蓄積状況サマリー")
    parser.add_argument("--dry-run",   action="store_true", help="DB書き込みなし")
    parser.add_argument("--horizon",   type=int, default=7,  help="予測ホライズン（デフォルト7）")
    parser.add_argument("--min-stars", type=int, default=3,  help="最小★（デフォルト3）")
    args = parser.parse_args()

    if args.stats:
        show_stats()
        return

    if args.both or (not args.predict and not args.match and not args.stats):
        daily_predict(horizon=args.horizon, min_stars=args.min_stars, dry_run=args.dry_run)
        match_actuals(dry_run=args.dry_run)
        return

    if args.predict:
        daily_predict(horizon=args.horizon, min_stars=args.min_stars, dry_run=args.dry_run)

    if args.match:
        match_actuals(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
