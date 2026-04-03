#!/usr/bin/env python3
"""
weekly_wx_score.py — 今週のコンボ別海況スコア一覧

combo_wx_params × 今週の実海況 で各(魚種×船宿)の有利/不利を計算。
毎週月曜の weekly_insights ジョブで自動実行。

出力: insights/weekly_wx_score.txt
"""
import math, os, sqlite3, sys
from datetime import datetime, timedelta

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(BASE_DIR)
DB_ANA   = os.path.join(BASE_DIR, "analysis.sqlite")
DB_WX    = os.path.join(ROOT_DIR, "weather_cache.sqlite")
OUT_FILE = os.path.join(BASE_DIR, "weekly_wx_score.txt")

FACTORS  = ["sst", "temp", "wave_height", "wind_speed", "pressure", "current_spd"]
FACTOR_JP = {
    "sst": "水温", "temp": "気温", "wave_height": "波高",
    "wind_speed": "風速", "pressure": "気圧", "current_spd": "海流速"
}

def load_current_wx():
    """今週（過去7日）の関東エリア平均海況"""
    week_start = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    conn = sqlite3.connect(DB_WX)
    row = conn.execute("""
        SELECT AVG(sst), AVG(temp), AVG(wave_height),
               AVG(wind_speed), AVG(pressure), AVG(current_spd)
        FROM weather
        WHERE lat BETWEEN 34.5 AND 36.5
          AND lon BETWEEN 138.5 AND 141.0
          AND dt >= ?
    """, (week_start,)).fetchone()
    conn.close()
    if not row or row[0] is None:
        return {}
    return dict(zip(FACTORS, row))

def load_combo_params():
    """{(fish, ship): [(factor, r, hist_mean, hist_std), ...]}"""
    conn = sqlite3.connect(DB_ANA)
    rows = conn.execute(
        "SELECT fish, ship, factor, r, hist_mean, hist_std FROM combo_wx_params"
    ).fetchall()
    conn.close()
    combo_wx = {}
    for fish, ship, fac, r, m, s in rows:
        combo_wx.setdefault((fish, ship), []).append((fac, r, m, s))
    return combo_wx

def calc_score(params, current_wx):
    """コンボの総合wxスコアと因子別寄与を返す"""
    details = []
    for fac, r, hist_mean, hist_std in params:
        val = current_wx.get(fac)
        if val is None or hist_std == 0:
            continue
        z = (val - hist_mean) / hist_std
        contrib = r * z
        details.append((fac, r, val, hist_mean, z, contrib))
    if not details:
        return None, []
    score = sum(d[5] for d in details) / len(details)
    return score, details

def main():
    print("=== weekly_wx_score.py 開始 ===")
    current_wx = load_current_wx()
    if not current_wx:
        print("海況データなし → 終了")
        return

    print("今週の海況:")
    for f in FACTORS:
        v = current_wx.get(f)
        if v:
            print(f"  {FACTOR_JP[f]}: {v:.2f}")

    combo_wx = load_combo_params()
    print(f"\nコンボ数: {len(combo_wx)}")

    results = []
    for (fish, ship), params in combo_wx.items():
        score, details = calc_score(params, current_wx)
        if score is None:
            continue
        results.append((fish, ship, score, details))

    # スコア順でソート
    results.sort(key=lambda x: -x[2])

    lines = [
        f"# 今週のコンボ別海況スコア",
        f"# 生成: {datetime.now().strftime('%Y/%m/%d %H:%M')}",
        f"# 今週海況: " + "  ".join(f"{FACTOR_JP[f]}={current_wx[f]:.1f}" for f in FACTORS if f in current_wx),
        "",
        "【有利 上位20】",
        f"{'魚種×船宿':<24} {'スコア':>7}  因子別寄与",
        "-" * 80,
    ]
    for fish, ship, score, details in results[:20]:
        detail_str = "  ".join(
            f"{FACTOR_JP[d[0]]}:{d[5]:+.2f}(z={d[4]:+.1f})" for d in details
        )
        lines.append(f"  {fish}×{ship:<18} {score:+.3f}  {detail_str}")

    lines += [
        "",
        "【不利 下位20】",
        f"{'魚種×船宿':<24} {'スコア':>7}  因子別寄与",
        "-" * 80,
    ]
    for fish, ship, score, details in results[-20:][::-1]:
        detail_str = "  ".join(
            f"{FACTOR_JP[d[0]]}:{d[5]:+.2f}(z={d[4]:+.1f})" for d in details
        )
        lines.append(f"  {fish}×{ship:<18} {score:+.3f}  {detail_str}")

    lines += [
        "",
        "【全コンボ】",
        f"{'魚種':<12} {'船宿':<16} {'スコア':>7}",
        "-" * 40,
    ]
    for fish, ship, score, _ in results:
        lines.append(f"  {fish:<12} {ship:<16} {score:+.3f}")

    with open(OUT_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"\n保存: {OUT_FILE}（{len(results)}コンボ）")

if __name__ == "__main__":
    main()
