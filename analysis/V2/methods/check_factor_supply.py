#!/usr/bin/env python3
"""
check_factor_supply.py — 本番予測の因子供給率チェッカー（T44b 不変条件）

学習で採用された因子（combo_wx_params の cnt_avg・|r|>=0.10）のうち、
本番 predict_count._build_all_wx が実際に値を供給できている重み割合を全コンボで測る。
供給されない因子は補正の分子から脱落し（分母には残る）、予測がベースラインに
引き戻される（90_決定ログ 2026/07/16 T44: 修正前は P50=33.6%・100%供給 0件）。

実行（ローカル・weather_cache のあるメインrepoで）:
  python analysis/V2/methods/check_factor_supply.py [--date YYYY/MM/DD] [--min-p50 0.60]
  exit 0=PASS / 1=P50 が閾値未満（供給の regression を検知）

CI 組込は任意（weather_cache が無い環境では過去日供給を測れないため既定はローカル運用）。
"""
import os
import sys
import io
import sqlite3
import argparse
import statistics
from collections import defaultdict

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import predict_count as pc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default="2026/06/20", help="測定対象日（過去日・weather_cache 必須）")
    ap.add_argument("--min-p50", type=float, default=0.60, help="P50 がこの値未満なら exit 1")
    ap.add_argument("--top-missing", type=int, default=12)
    args = ap.parse_args()

    conn = sqlite3.connect(f"file:{pc.DB_PATH}?mode=ro", uri=True)
    combos = conn.execute("SELECT fish, ship FROM combo_meta").fetchall()
    print(f"対象コンボ: {len(combos)}件 / 測定日: {args.date}")

    rates = []
    miss_w = defaultdict(float)
    miss_n = defaultdict(int)
    worst = []
    conn_rw = sqlite3.connect(pc.DB_PATH)  # serve_sla_monthly 読取用（pc は conn を受ける）
    for fish, ship in combos:
        rows = conn.execute(
            "SELECT factor, mean, std, r, lat, lon FROM combo_wx_params "
            "WHERE fish=? AND ship=? AND metric='cnt_avg'", (fish, ship)).fetchall()
        fp = {}
        wlat = wlon = None
        for fac, mean, std, r, rlat, rlon in rows:
            if fac == "_meta":
                wlat, wlon = rlat, rlon
            elif r is not None and abs(r) >= 0.10 and mean is not None and std is not None:
                fp[fac] = abs(r)
        if not fp or not wlat:
            continue
        all_wx, _, _ = pc._build_all_wx(wlat, wlon, args.date, 2.0,
                                        conn=conn_rw, fish=fish, ship=ship)
        w_all = sum(fp.values())
        w_pre = sum(w for f, w in fp.items() if all_wx.get(f) is not None)
        rates.append(w_pre / w_all)
        worst.append((w_pre / w_all, fish, ship))
        for f, w in fp.items():
            if all_wx.get(f) is None:
                miss_w[f] += w
                miss_n[f] += 1

    rates.sort()

    def P(q):
        return rates[min(len(rates) - 1, int(len(rates) * q))] * 100

    print(f"\n実効重み供給率  n={len(rates)}コンボ")
    print(f"  P10={P(0.10):.1f}%  P25={P(0.25):.1f}%  P50={P(0.50):.1f}%  "
          f"P75={P(0.75):.1f}%  P90={P(0.90):.1f}%  平均={statistics.mean(rates)*100:.1f}%")
    print(f"  100%供給={sum(1 for r in rates if r > 0.999)}件  "
          f"50%未満={sum(1 for r in rates if r < 0.5)}件  0%={sum(1 for r in rates if r < 1e-9)}件")

    if miss_w:
        print(f"\n未供給因子 ワースト{args.top_missing}（欠落Σ|r|）")
        for f, w in sorted(miss_w.items(), key=lambda x: -x[1])[:args.top_missing]:
            print(f"  {f:<28} {miss_n[f]:>4}コンボ  Σ|r|={w:>7.1f}")

    worst.sort()
    print("\n供給率ワースト5コンボ")
    for r, fish, ship in worst[:5]:
        print(f"  {fish:<10} {ship:<12} {r*100:>5.1f}%")

    p50 = rates[len(rates) // 2]
    ok = p50 >= args.min_p50
    print(f"\n判定: P50={p50*100:.1f}% {'>=':>2} {args.min_p50*100:.0f}% → {'✅ PASS' if ok else '❌ FAIL（因子供給の regression）'}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
