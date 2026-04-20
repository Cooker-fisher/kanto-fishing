"""吉野屋×タチウオのポイント別最適化テスト（一時スクリプト）
DB への書き込みをすべてスキップし、バックテスト結果のみをメモリで返す。
"""
import os, sys, csv, sqlite3, collections

# パス解決
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _THIS_DIR)

import combo_deep_dive as cdd

FISH = 'タチウオ'
SHIP = '吉野屋'

# ─────────────────────────────────────────────────
# Step 0: ポイント別件数確認
# ─────────────────────────────────────────────────
all_records = cdd.load_records(FISH, ship_filter=SHIP)
print(f'対象: {len(all_records)}件 先頭3: {[r["point"] for r in all_records[:3]]}')

pt_counts = collections.Counter(r['point'] for r in all_records)
print('\nポイント別件数（全件）:')
for pt, n in pt_counts.most_common(15):
    print(f'  {repr(pt)}: {n}件')

# MIN_N_COMBO=30 以上のポイントを対象とする
POINTS_TO_TEST = [pt for pt, n in pt_counts.most_common() if n >= cdd.MIN_N_COMBO]
print(f'\nN>={cdd.MIN_N_COMBO} のポイント: {POINTS_TO_TEST}')

# ─────────────────────────────────────────────────
# Step 1: 全体モデルの現在の精度（DB から読み取り）
# ─────────────────────────────────────────────────
print('\n' + '='*60)
print('【全体モデル精度（combo_backtest から）】')
try:
    conn_db = sqlite3.connect(cdd.DB_ANA)
    rows = conn_db.execute(
        "SELECT horizon, r, wmape, bl2_wmape, n_test FROM combo_backtest "
        "WHERE fish=? AND ship=? AND metric='cnt_avg' AND horizon IN (0,7) ORDER BY horizon",
        (FISH, SHIP)
    ).fetchall()
    conn_db.close()
    if rows:
        for h, r, wmape, bl2w, n in rows:
            print(f'  H={h}: wMAPE={wmape:.1f}%  r={r:+.3f}  bl2_wmape={bl2w}  n={n}')
    else:
        print('  (DB にデータなし)')
except Exception as e:
    print(f'  DB 読み取りエラー: {e}')

# ─────────────────────────────────────────────────
# Step 2: ポイント別フル最適化（DB 書き込みなし）
# ─────────────────────────────────────────────────
print('\n' + '='*60)
print('【ポイント別最適化（leave-one-month-out CV）】')

results = {}

ship_coords  = cdd.load_ship_coords()
wx_coords    = cdd.load_wx_coords_list()
ship_area    = cdd.load_ship_area()
conn_wx      = sqlite3.connect(cdd.DB_WX)   if (os.path.exists(cdd.DB_WX)   and os.path.getsize(cdd.DB_WX)   > 0) else None
conn_tide    = sqlite3.connect(cdd.DB_TIDE) if (os.path.exists(cdd.DB_TIDE) and os.path.getsize(cdd.DB_TIDE) > 0) else None
conn_typhoon = sqlite3.connect(cdd.DB_TYPHOON) if (os.path.exists(cdd.DB_TYPHOON) and os.path.getsize(cdd.DB_TYPHOON) > 0) else None
conn_cmems   = sqlite3.connect(cdd.DB_CMEMS)   if (os.path.exists(cdd.DB_CMEMS)   and os.path.getsize(cdd.DB_CMEMS)   > 0) else None

for pt in POINTS_TO_TEST:
    # ポイントフィルタ適用
    pt_records = [r for r in all_records if r.get('point') == pt]
    n_total = len(pt_records)
    print(f'\n--- ポイント: {pt!r}  N={n_total} ---')

    if n_total < cdd.MIN_N_COMBO:
        print(f'  スキップ (N < {cdd.MIN_N_COMBO})')
        results[pt] = None
        continue

    # 乗合フィルタ
    noboat = [r for r in pt_records if r.get('is_boat', 0) == 0]
    if len(noboat) >= cdd.MIN_N_COMBO and len(noboat) < len(pt_records):
        print(f'  [is_boat filter] {n_total} → {len(noboat)}件')
        pt_records = noboat

    months = sorted(set(r['date'][:7] for r in pt_records))
    print(f'  月数: {len(months)}ヶ月  期間: {months[0]} 〜 {months[-1]}')

    decadal = cdd.load_decadal(FISH, SHIP)  # 全体ベースラインを流用

    # section_backtest_rolling を呼び出す（DB 書き込みなし）
    bt_lines, bt_data, range_bt_data, star_bt_data, season_thr, wx_params_data, modal_lat, modal_lon, best_cmems = \
        cdd.section_backtest_rolling(
            pt_records, ship_coords, wx_coords, conn_wx, ship_area, decadal,
            conn_tide=conn_tide, conn_typhoon=conn_typhoon,
            fish=FISH, conn_cmems=conn_cmems
        )

    # H=0, H=7 の cnt_avg 結果を抽出
    # bt_data row: (met, H, rv, mae, mape, smape, wmape, rmse, dacc, ..., bl0w, bl0m, bl0r, bl1w, bl1m, bl1r, bl2w, bl2m, bl2r)
    pt_result = {'n': n_total, 'months': len(months)}
    for row in bt_data:
        met = row[0]; H = row[1]; rv = row[2]; wmape = row[6]; bl2w = row[26]; n_test = row[18]
        if met == 'cnt_avg' and H in (0, 7):
            pt_result[f'H{H}_wmape'] = wmape
            pt_result[f'H{H}_r']     = rv
            pt_result[f'H{H}_bl2w']  = bl2w
            pt_result[f'H{H}_n']     = n_test

    results[pt] = pt_result
    # 採用気象因子も表示
    if wx_params_data:
        factors = [k for k in wx_params_data if not k.startswith('_')]
        print(f'  採用因子: {factors[:8]} ...')
    print(f'  H=0: wMAPE={pt_result.get("H0_wmape")}%  r={pt_result.get("H0_r")}  bl2={pt_result.get("H0_bl2w")}%  n={pt_result.get("H0_n")}')
    print(f'  H=7: wMAPE={pt_result.get("H7_wmape")}%  r={pt_result.get("H7_r")}  bl2={pt_result.get("H7_bl2w")}%  n={pt_result.get("H7_n")}')

# 接続クローズ
for c in [conn_wx, conn_tide, conn_typhoon, conn_cmems]:
    if c is not None:
        try: c.close()
        except: pass

# ─────────────────────────────────────────────────
# Step 3: 結果サマリー
# ─────────────────────────────────────────────────
print('\n' + '='*60)
print('【ポイント別最適化 vs 全体モデル サマリー】')
print(f'{"ポイント":16} {"N":>5} {"月数":>4}  H=0 wMAPE      H=7 wMAPE')
print('-'*65)

# 全体モデルの参考値（project_status.md より wMAPE=44.7% との記述があるが DB から取る）
try:
    conn_db = sqlite3.connect(cdd.DB_ANA)
    _h0 = conn_db.execute(
        "SELECT wmape, r, n_test FROM combo_backtest "
        "WHERE fish=? AND ship=? AND metric='cnt_avg' AND horizon=0", (FISH, SHIP)
    ).fetchone()
    _h7 = conn_db.execute(
        "SELECT wmape, r, n_test FROM combo_backtest "
        "WHERE fish=? AND ship=? AND metric='cnt_avg' AND horizon=7", (FISH, SHIP)
    ).fetchone()
    conn_db.close()
    all_h0 = f'{_h0[0]:.1f}% r={_h0[1]:+.3f} n={_h0[2]}' if _h0 else 'N/A'
    all_h7 = f'{_h7[0]:.1f}% r={_h7[1]:+.3f} n={_h7[2]}' if _h7 else 'N/A'
    print(f'{"[全体モデル]":16} {len(all_records):>5}        {all_h0}  {all_h7}')
    print('-'*65)
except Exception as e:
    print(f'DB エラー: {e}')

for pt in POINTS_TO_TEST:
    r = results.get(pt)
    if r is None:
        print(f'{pt[:16]:16}   スキップ')
        continue
    h0w = f"{r.get('H0_wmape', '-'):.1f}%" if r.get('H0_wmape') is not None else '-'
    h0r = f"{r.get('H0_r', '-'):+.3f}" if r.get('H0_r') is not None else '-'
    h0n = r.get('H0_n', '-')
    h7w = f"{r.get('H7_wmape', '-'):.1f}%" if r.get('H7_wmape') is not None else '-'
    h7r = f"{r.get('H7_r', '-'):+.3f}" if r.get('H7_r') is not None else '-'
    h7n = r.get('H7_n', '-')
    print(f'{pt[:16]:16} {r["n"]:>5} {r["months"]:>4}  {h0w} r={h0r} n={h0n}  {h7w} r={h7r} n={h7n}')
