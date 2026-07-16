#!/usr/bin/env python3
"""
t44b_parity_check.py — 学習(enrich) ↔ 本番(_build_all_wx) の因子パリティ検証

T44b で predict_count に追加供給した因子（カレンダー・季節交互作用・潮汐×季節・
台風・CMEMS月次・SST勾配・前週釣果）が、combo_deep_dive.enrich() と同じ値を
返すことを実データで検証する。式の複製がある因子（祝日リスト等）のドリフト検知も兼ねる。

実行（ローカル・weather_cache / cmems / analysis.sqlite があるメインrepoで）:
  python analysis/V2/analysis-improvement/t44b_parity_check.py [魚種 船宿 ...]
  引数省略時はデフォルト3コンボ。exit 0=PASS / 1=FAIL。

判定基準:
- 完全一致必須: カレンダー5因子・季節交互作用8・tide_grp 12・typhoon 2・SLA月次3・prev_week_cnt
- sst_gradient は日次集計実装が学習/本番で別関数のため差分を報告のみ（fail にしない）
"""
import os
import sys
import io
import sqlite3

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
_METHODS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "methods")
sys.path.insert(0, os.path.normpath(_METHODS))

import combo_deep_dive as cdd
import predict_count as pc

DEFAULT_COMBOS = [("アジ", "こなや丸"), ("マダイ", "幸丸"), ("タチウオ", "吉久")]

EXACT_KEYS = (
    ["is_holiday", "is_consec_holiday", "is_summer_vacation", "spawn_season_n", "day_of_decade"]
    + [f"wave_clamp_{s}" for s, _ in pc._SEASON_SUFFIX]
    + [f"sst_{s}" for s, _ in pc._SEASON_SUFFIX]
    + [f"tide_grp_{g}_{s}" for g in ("oshio", "chusho", "chowaka") for s, _ in pc._SEASON_SUFFIX]
    + ["typhoon_dist", "typhoon_wind",
       "kuroshio_sla_monthly", "sla_pelagic_monthly", "sla_approach_idx",
       "kuroshio_sla_delta_1m"]
)
REPORT_KEYS = ["sst_gradient"]
SAMPLE_PER_COMBO = 15


def main():
    args = sys.argv[1:]
    combos = ([(args[i], args[i + 1]) for i in range(0, len(args) - 1, 2)]
              if len(args) >= 2 else DEFAULT_COMBOS)

    # ── 静的パリティ: 定数の同一性 ─────────────────────────────────────────
    fails = []
    if pc._JP_HOLIDAYS != cdd._JP_HOLIDAYS:
        fails.append("祝日リスト _JP_HOLIDAYS が combo_deep_dive と不一致")
    if pc._CONSEC_HOLIDAY_SET != cdd._CONSEC_HOLIDAY_SET:
        fails.append("連休セット _CONSEC_HOLIDAY_SET が不一致")
    for m in range(1, 13):
        if pc._SEASON_OF_MONTH[m] != cdd._season_of(m):
            fails.append(f"季節マップ不一致: 月={m}")
    print(f"静的パリティ: {'PASS' if not fails else 'FAIL: ' + '; '.join(fails)}")

    # ── serve_sla_monthly が analysis.sqlite に無ければ蒸留（1回だけ・追加テーブルのみ）──
    conn_ana = sqlite3.connect(pc.DB_PATH)
    has_tbl = conn_ana.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='serve_sla_monthly'").fetchone()
    if not has_tbl:
        print("serve_sla_monthly 未整備 → build_predict_params.build_serve_sla_monthly で蒸留…")
        import build_predict_params as bpp
        bpp.build_serve_sla_monthly(conn_ana)

    # ── 動的パリティ: enrich と _build_all_wx を同一レコードで比較 ────────────
    ship_coords = cdd.load_ship_coords()
    wx_coords = cdd.load_wx_coords_list()
    ship_area = cdd.load_ship_area()
    conn_wx = sqlite3.connect(cdd.DB_WX) if os.path.exists(cdd.DB_WX) else None
    conn_tide = sqlite3.connect(cdd.DB_TIDE) if os.path.exists(cdd.DB_TIDE) else None
    conn_ty = sqlite3.connect(cdd.DB_TYPHOON) if os.path.exists(cdd.DB_TYPHOON) else None
    conn_cm = sqlite3.connect(cdd.DB_CMEMS) if os.path.exists(cdd.DB_CMEMS) else None

    stats = {k: [0, 0, 0.0] for k in EXACT_KEYS + REPORT_KEYS + ["prev_week_cnt"]}  # [n, miss, maxdiff]
    for fish, ship in combos:
        records = cdd.load_records(fish, ship_filter=ship)
        if len(records) < 5:
            print(f"  skip {fish}×{ship}: レコード不足 ({len(records)})")
            continue
        # deep_dive() と同一の前処理を再現（prev_week_cnt の参照集合はこの前処理【後】）
        _noboat = [r for r in records if r.get("is_boat", 0) == 0]
        _boat_fired = len(_noboat) >= cdd.MIN_N_COMBO and len(_noboat) < len(records)
        if _boat_fired:
            records = _noboat
        _cnts = sorted(r["cnt_avg"] for r in records if r.get("cnt_avg") is not None)
        _cap_fired = 0
        if len(_cnts) >= 4:
            _q1 = _cnts[len(_cnts) // 4]
            _q3 = _cnts[3 * len(_cnts) // 4]
            _cap = _q3 + 3 * (_q3 - _q1)
            for r in records:
                if r.get("cnt_avg", 0) > _cap:
                    r["cnt_avg"] = _cap
                    _cap_fired += 1
        print(f"    前処理: is_boatフィルタ{'発火' if _boat_fired else 'なし'} / "
              f"外れ値キャップ {_cap_fired}件")
        en0 = cdd.enrich(records, ship_coords, wx_coords, conn_wx, ship_area,
                         horizon=0, all_records=records, conn_tide=conn_tide,
                         conn_typhoon=conn_ty, conn_cmems=conn_cm, fish=fish)
        sample = en0[-SAMPLE_PER_COMBO:]
        print(f"  {fish}×{ship}: enrich {len(en0)}行 → 末尾{len(sample)}行を比較")
        thr = 2.0
        for r in sample:
            date_slash = r["date"]
            serve_wx, _, _ = pc._build_all_wx(
                r.get("lat"), r.get("lon"), date_slash, thr,
                conn=conn_ana, fish=fish, ship=ship)
            for k in EXACT_KEYS + REPORT_KEYS:
                a, b = r.get(k), serve_wx.get(k)
                st = stats[k]
                st[0] += 1
                if a is None and b is None:
                    continue
                if (a is None) != (b is None):
                    st[1] += 1
                elif isinstance(a, (int, float)) and isinstance(b, (int, float)):
                    d = abs(a - b)
                    st[2] = max(st[2], d)
                    if d > 1e-9:
                        st[1] += 1
                elif a != b:
                    st[1] += 1
            # prev_week_cnt はパリティ用に before_date=record日付 で比較
            a = r.get("prev_week_cnt")
            b = pc._get_prev_week_cnt(fish, ship, before_date=date_slash)
            st = stats["prev_week_cnt"]
            st[0] += 1
            if (a is None) != (b is None):
                st[1] += 1
            elif a is not None and abs(a - b) > 1e-9:
                st[1] += 1
                st[2] = max(st[2], abs(a - b))

    print(f"\n{'factor':<26} {'比較n':>5} {'不一致':>5} {'max差':>10}")
    hard_fail = list(fails)
    for k in EXACT_KEYS + ["prev_week_cnt"] + REPORT_KEYS:
        n, miss, mx = stats[k]
        flag = ""
        if miss and k not in REPORT_KEYS:
            flag = " ❌"
            hard_fail.append(f"{k}: {miss}/{n} 不一致")
        elif miss:
            flag = " （報告のみ）"
        print(f"{k:<26} {n:>5} {miss:>5} {mx:>10.4g}{flag}")

    print(f"\n結果: {'✅ PASS（学習↔本番の因子値は一致）' if not hard_fail else '❌ FAIL'}")
    for f in hard_fail:
        print(f"  - {f}")
    sys.exit(1 if hard_fail else 0)


if __name__ == "__main__":
    main()
