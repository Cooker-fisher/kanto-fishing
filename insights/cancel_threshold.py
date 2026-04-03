#!/usr/bin/env python3
"""
cancel_threshold.py — 船宿×魚種ごとの欠航閾値を実データから計算

[入力]
  data/*.csv          欠航フラグ付き釣果データ（欠航893件含む）
  weather_cache.sqlite 日別海況（153座標）
  insights/analysis.sqlite combo_meta（船宿の代表座標）

[処理]
  各船宿について:
    欠航日の波高・風速 vs 出船日の波高・風速を比較
    → 欠航率50%になる波高・風速の閾値を推定

[出力]
  insights/analysis.sqlite: cancel_thresholds テーブル
  insights/cancel_threshold.txt: 人間が読める閾値一覧
"""
import csv, math, os, sqlite3
from collections import defaultdict
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(BASE_DIR)
DATA_DIR = os.path.join(ROOT_DIR, "data")
DB_ANA   = os.path.join(BASE_DIR, "analysis.sqlite")
DB_WX    = os.path.join(ROOT_DIR, "weather_cache.sqlite")
OUT_TXT  = os.path.join(BASE_DIR, "cancel_threshold.txt")

def load_ship_coords():
    """combo_meta から船宿の代表座標を取得"""
    conn = sqlite3.connect(DB_ANA)
    rows = conn.execute(
        "SELECT ship, AVG(lat), AVG(lon) FROM combo_meta WHERE lat IS NOT NULL GROUP BY ship"
    ).fetchall()
    conn.close()
    return {ship: (round(lat, 3), round(lon, 3)) for ship, lat, lon in rows}

def load_wx_coords():
    """weather_cache の全座標リスト"""
    conn = sqlite3.connect(DB_WX)
    coords = conn.execute("SELECT DISTINCT lat, lon FROM weather").fetchall()
    conn.close()
    return [(lat, lon) for lat, lon in coords]

def nearest_coord(lat, lon, coords):
    return min(coords, key=lambda c: (c[0]-lat)**2 + (c[1]-lon)**2)

def get_daily_wx(conn_wx, lat, lon, date_str):
    """指定日の06:00前後の海況（波高・風速）を取得"""
    rows = conn_wx.execute("""
        SELECT wave_height, wind_speed, sst, temp
        FROM weather
        WHERE lat=? AND lon=? AND dt LIKE ?
        ORDER BY ABS(CAST(substr(dt,12,2) AS INT) - 6)
        LIMIT 1
    """, (lat, lon, f"{date_str}%")).fetchone()
    return rows  # (wave_height, wind_speed, sst, temp) or None

def load_records():
    """全釣果レコードを (ship, date, is_cancellation) でロード"""
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
                # 欠航フラグ
                is_cancel = row.get("is_cancellation") == "1"
                records.append({
                    "ship":      ship,
                    "date":      date,
                    "is_cancel": is_cancel,
                    "tsuri_mono": row.get("tsuri_mono", "").strip(),
                })
    return records

def percentile_threshold(cancel_vals, ok_vals, target_cancel_rate=0.5):
    """
    cancel_vals: 欠航日の波高リスト
    ok_vals:     出船日の波高リスト
    target_cancel_rate: このレートになる閾値を探す

    戻り値: (threshold, cancel_rate_at_threshold, n_cancel, n_ok)
    """
    all_vals = sorted(set(cancel_vals + ok_vals))
    best_thr = None
    best_diff = float("inf")
    for thr in all_vals:
        c_above = sum(1 for v in cancel_vals if v >= thr)
        o_above = sum(1 for v in ok_vals if v >= thr)
        total_above = c_above + o_above
        if total_above == 0:
            continue
        rate = c_above / total_above
        diff = abs(rate - target_cancel_rate)
        if diff < best_diff:
            best_diff = diff
            best_thr = thr
    if best_thr is None:
        return None, None, len(cancel_vals), len(ok_vals)
    c_above = sum(1 for v in cancel_vals if v >= best_thr)
    o_above = sum(1 for v in ok_vals if v >= best_thr)
    total = c_above + o_above
    rate = c_above / total if total > 0 else 0
    return best_thr, rate, len(cancel_vals), len(ok_vals)

def main():
    print("=== cancel_threshold.py 開始 ===")
    ship_coords = load_ship_coords()
    wx_coords   = load_wx_coords()
    records     = load_records()
    print(f"レコード: {len(records):,}件 / 座標あり船宿: {len(ship_coords)}件")

    # 船宿×日付でユニーク化（同日複数レコードは欠航優先）
    ship_dates = {}  # (ship, date) -> is_cancel
    for r in records:
        key = (r["ship"], r["date"])
        if key not in ship_dates or r["is_cancel"]:
            ship_dates[key] = r["is_cancel"]

    # 船宿ごとにデータ収集
    ship_data = defaultdict(lambda: {"cancel_wave": [], "ok_wave": [],
                                      "cancel_wind": [], "ok_wind": []})

    conn_wx = sqlite3.connect(DB_WX)
    wx_cache = {}  # (lat, lon, date_iso) -> (wave, wind, sst, temp)
    matched = 0
    total   = 0

    for (ship, date_str), is_cancel in ship_dates.items():
        if ship not in ship_coords:
            continue
        slat, slon = ship_coords[ship]
        wlat, wlon = nearest_coord(slat, slon, wx_coords)
        date_iso = date_str.replace("/", "-")
        total += 1

        cache_key = (wlat, wlon, date_iso)
        if cache_key not in wx_cache:
            wx_cache[cache_key] = get_daily_wx(conn_wx, wlat, wlon, date_iso)
        wx = wx_cache[cache_key]
        if not wx or wx[0] is None:
            continue
        matched += 1

        wave, wind = wx[0], wx[1]
        if wave is None or wind is None:
            continue
        if is_cancel:
            ship_data[ship]["cancel_wave"].append(wave)
            ship_data[ship]["cancel_wind"].append(wind)
        else:
            ship_data[ship]["ok_wave"].append(wave)
            ship_data[ship]["ok_wind"].append(wind)

    conn_wx.close()
    print(f"海況マッチ: {matched}/{total}件")

    # 閾値計算
    results = []
    for ship, d in ship_data.items():
        nc, no = len(d["cancel_wave"]), len(d["ok_wave"])
        if nc < 3:  # 欠航が少なすぎる船宿は除外
            continue
        wave_thr, wave_rate, _, _ = percentile_threshold(d["cancel_wave"], d["ok_wave"])
        wind_thr, wind_rate, _, _ = percentile_threshold(d["cancel_wind"], d["ok_wind"])

        avg_cancel_wave = sum(d["cancel_wave"])/len(d["cancel_wave"]) if d["cancel_wave"] else None
        avg_ok_wave     = sum(d["ok_wave"])/len(d["ok_wave"]) if d["ok_wave"] else None

        results.append({
            "ship":           ship,
            "n_cancel":       nc,
            "n_ok":           no,
            "cancel_wave_avg": round(avg_cancel_wave, 2) if avg_cancel_wave else None,
            "ok_wave_avg":    round(avg_ok_wave, 2) if avg_ok_wave else None,
            "wave_threshold": round(wave_thr, 2) if wave_thr else None,
            "wave_cancel_rate": round(wave_rate, 2) if wave_rate else None,
            "wind_threshold": round(wind_thr, 2) if wind_thr else None,
            "wind_cancel_rate": round(wind_rate, 2) if wind_rate else None,
        })

    results.sort(key=lambda x: -x["n_cancel"])

    # DB保存
    conn_ana = sqlite3.connect(DB_ANA)
    conn_ana.execute("DROP TABLE IF EXISTS cancel_thresholds")
    conn_ana.execute("""
        CREATE TABLE cancel_thresholds (
            ship             TEXT PRIMARY KEY,
            n_cancel         INTEGER,
            n_ok             INTEGER,
            cancel_wave_avg  REAL,
            ok_wave_avg      REAL,
            wave_threshold   REAL,
            wave_cancel_rate REAL,
            wind_threshold   REAL,
            wind_cancel_rate REAL
        )
    """)
    for r in results:
        conn_ana.execute("INSERT INTO cancel_thresholds VALUES (?,?,?,?,?,?,?,?,?)", (
            r["ship"], r["n_cancel"], r["n_ok"],
            r["cancel_wave_avg"], r["ok_wave_avg"],
            r["wave_threshold"], r["wave_cancel_rate"],
            r["wind_threshold"], r["wind_cancel_rate"],
        ))
    conn_ana.commit()
    conn_ana.close()

    # テキスト出力
    lines = [
        "# 船宿別 欠航閾値（実データより）",
        f"# 生成: {datetime.now().strftime('%Y/%m/%d %H:%M')}",
        f"# 欠航n>=3の船宿: {len(results)}件",
        "",
        f"{'船宿':<16} {'欠航':>5} {'出船':>6} {'欠航波高平均':>10} {'出船波高平均':>10} "
        f"{'波高閾値':>8} {'欠航率':>6}  {'風速閾値':>8} {'欠航率':>6}",
        "-" * 90,
    ]
    for r in results:
        lines.append(
            f"  {r['ship']:<14} {r['n_cancel']:>5} {r['n_ok']:>6} "
            f"  {r['cancel_wave_avg'] or '-':>8}m   {r['ok_wave_avg'] or '-':>8}m "
            f"  {r['wave_threshold'] or '-':>6}m {(r['wave_cancel_rate']*100 if r['wave_cancel_rate'] else 0):>5.0f}%"
            f"  {r['wind_threshold'] or '-':>6}m/s {(r['wind_cancel_rate']*100 if r['wind_cancel_rate'] else 0):>5.0f}%"
        )

    # 全体サマリー
    all_cancel_waves = [r["cancel_wave_avg"] for r in results if r["cancel_wave_avg"]]
    all_ok_waves     = [r["ok_wave_avg"] for r in results if r["ok_wave_avg"]]
    all_wave_thr     = [r["wave_threshold"] for r in results if r["wave_threshold"]]
    if all_wave_thr:
        lines += [
            "",
            "【全船宿集計】",
            f"  欠航日の平均波高: {sum(all_cancel_waves)/len(all_cancel_waves):.2f}m",
            f"  出船日の平均波高: {sum(all_ok_waves)/len(all_ok_waves):.2f}m",
            f"  波高閾値の中央値: {sorted(all_wave_thr)[len(all_wave_thr)//2]:.2f}m",
            f"  波高閾値の最小:   {min(all_wave_thr):.2f}m（最も繊細な船宿）",
            f"  波高閾値の最大:   {max(all_wave_thr):.2f}m（最も強い船宿）",
        ]

    with open(OUT_TXT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"保存: {len(results)}船宿 → cancel_thresholds テーブル")
    print(f"保存: {OUT_TXT}")

if __name__ == "__main__":
    main()
