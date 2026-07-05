#!/usr/bin/env python3
"""fish-value クロール修正後のスモークテスト。

crawl_daily.py / crawl_wholesale.py / generate_price_master.py を触ったら、
これを実行して壊れていないか即確認する。GitHub Actions の週次を待つ必要はない。

  python docs/fish-value/test_fish_value.py              # 日報クロール→マスタ再生成→全検証（~20s・要ネット）
  python docs/fish-value/test_fish_value.py --check      # クロールせず既存JSONだけ検証（オフライン・数秒）
  python docs/fish-value/test_fish_value.py --days 8     # 窓を縮めて速く（daily-prices.json も縮む点に注意）
  python docs/fish-value/test_fish_value.py --wholesale 202605  # 月報も取り込んでから検証

終了コード: 0=全PASS / 1=FAIL あり。CI にも流用可。
"""
from __future__ import annotations
import argparse
import importlib.util
import json
import os
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

HERE = Path(__file__).resolve().parent
JST = timezone(timedelta(hours=9))
AUDIT_DAYS = 8            # 品名監査で舐める営業日数（軽く）
EXPECTED_MIN_PRICES = 60  # fish-price-master の最低魚種数
OVERRIDE_PFIDS = ('madai', 'shirogisu', 'mebaru')  # 日報検証 override が維持されるべき魚

# crawl_daily.py を import（マッピング関数の直接テスト用）
_spec = importlib.util.spec_from_file_location('crawl_daily', HERE / 'crawl_daily.py')
cd = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cd)

_n_ok = _n_fail = _n_warn = 0


def ok(msg: str):
    global _n_ok; _n_ok += 1; print(f'  [OK]   {msg}')


def fail(msg: str):
    global _n_fail; _n_fail += 1; print(f'  [FAIL] {msg}')


def warn(msg: str):
    global _n_warn; _n_warn += 1; print(f'  [WARN] {msg}')


def run_step(argv: list[str]) -> bool:
    print(f'  $ {" ".join(argv)}')
    # 子プロセスの print(日本語) を確実に utf-8 で受ける（Windows既定 cp932 だと decode 例外）
    env = {**os.environ, 'PYTHONIOENCODING': 'utf-8', 'PYTHONUTF8': '1'}
    r = subprocess.run([sys.executable] + argv, capture_output=True, text=True,
                       encoding='utf-8', errors='replace', env=env)
    tail = (r.stdout or '').strip().splitlines()[-1:] or ['']
    print(f'    → exit {r.returncode} / {tail[0]}')
    if r.returncode != 0:
        print((r.stderr or '').strip()[-500:])
    return r.returncode == 0


# ---- 1. マッピングの回帰ユニットテスト（ネット不要・過去バグの再発防止） --------
def test_mapping_units():
    print('\n[1] 品名→pfid マッピング ユニットテスト（過去バグの回帰ガード）')
    cases = [
        ('あまだい', 'amadai', '甘鯛が真鯛に化ける部分文字列バグ'),
        ('まだい', 'madai', '真鯛は真鯛'),
        ('きわだ（冷凍）', None, '冷凍マグロは除外（生鮮キハダ汚染バグ）'),
        ('きわだ（生鮮）', 'kihada', '生鮮キハダは採用'),
        ('冷かれい', None, '冷凍カレイは除外'),
        ('活ひらめ', None, '活魚は除外'),
        ('ぶり', 'buri', 'ブリ'),
        ('するめいか', 'surumeika', 'スルメイカ'),
    ]
    for hinmei, expect, why in cases:
        got = cd.map_hinmei(hinmei)
        if got == expect:
            ok(f'map_hinmei({hinmei!r}) == {expect!r}  … {why}')
        else:
            fail(f'map_hinmei({hinmei!r}) == {got!r}（期待 {expect!r}）… {why}')


# ---- 2. パイプライン実行 ----------------------------------------------------
def run_pipeline(days: int, wholesale_month: str | None) -> bool:
    print('\n[2] パイプライン実行')
    okall = True
    if wholesale_month:
        okall &= run_step([str(HERE / 'crawl_wholesale.py'), '--month', wholesale_month])
    okall &= run_step([str(HERE / 'crawl_daily.py'), '--days', str(days)])
    okall &= run_step([str(HERE / 'generate_price_master.py')])
    if okall:
        ok('crawl → generate すべて exit 0')
    else:
        fail('パイプラインのいずれかが非0終了（上のログ参照）')
    return okall


# ---- 3. daily-prices.json 検証 ---------------------------------------------
def validate_daily():
    print('\n[3] daily-prices.json 構造・健全性')
    p = HERE / 'daily-prices.json'
    if not p.exists():
        warn('daily-prices.json なし（--check かつ未生成？）'); return
    d = json.loads(p.read_text(encoding='utf-8'))
    if 'generated_at' in d:
        fail('generated_at が復活している（週次cronの無駄コミット源・除去したはず）')
    else:
        ok('generated_at なし（無駄コミット防止が維持）')
    asof = str(d.get('asof', ''))
    if len(asof) == 8 and asof.isdigit():
        ok(f'asof={asof}')
        if asof != datetime.now(JST).strftime('%Y%m%d'):
            warn(f'asof が JST今日({datetime.now(JST):%Y%m%d}) と不一致（--asof指定 or 日跨ぎなら想定内）')
    else:
        fail(f'asof が不正: {asof!r}')
    wbd = d.get('window_business_days', 0)
    if wbd == 0:
        fail('window_business_days=0（取得失敗）')
    elif wbd < 10:
        warn(f'window_business_days={wbd}（10未満・窓が薄い）')
    else:
        ok(f'window_business_days={wbd}')
    bad = [k for k, v in d.get('by_pfid', {}).items()
           if not (v.get('n_days', 0) >= 1 and v.get('n_mid', 0) >= 1 and v.get('mid_median_yen_per_kg', 0) > 0)]
    if bad:
        fail(f'by_pfid に異常エントリ: {bad[:5]}')
    else:
        ok(f'by_pfid {len(d.get("by_pfid", {}))}魚種すべて正常（n>=1・中値>0）')


# ---- 4. 品名監査（ネット・実データで混入チェック） --------------------------
def audit_mapping(days: int):
    print(f'\n[4] 品名監査（直近{days}営業日を実取得して混入チェック）')
    agg = defaultdict(Counter)
    fetched = 0
    d = datetime.now(JST).date()
    tries = 0
    while fetched < days and tries < days + 12:
        ds = d.strftime('%Y%m%d'); d -= timedelta(days=1); tries += 1
        txt = cd.fetch_day(ds)
        if not txt or len(txt) < 1000:
            continue
        fetched += 1
        for r in cd.parse_rows(txt):
            pfid = cd.map_hinmei(r['hinmei'])
            if pfid:
                agg[pfid][r['hinmei']] += 1
    if fetched == 0:
        warn('日報を取得できず監査スキップ（ネット不通 or サイト構造変化）'); return

    # 混入ガード: マップ済み品名に 冷/活/加工 が漏れていないか
    leaked = []
    for pfid, cnt in agg.items():
        for h in cnt:
            if '冷' in h or h.startswith(('活', '開干', 'みそ', '塩', '干', '煮')):
                leaked.append(f'{pfid}←{h}')
    if leaked:
        fail(f'冷凍/活魚/加工が混入: {leaked[:5]}')
    else:
        ok(f'冷凍/活魚/加工の混入なし（{fetched}日・{len(agg)}魚種）')

    # 同一品名が複数 pfid に割れていないか（概念混同）
    hinmei_to_pfids = defaultdict(set)
    for pfid, cnt in agg.items():
        for h in cnt:
            hinmei_to_pfids[h].add(pfid)
    conflict = {h: sorted(ps) for h, ps in hinmei_to_pfids.items() if len(ps) > 1}
    if conflict:
        fail(f'同一品名が複数pfidにマップ: {conflict}')
    else:
        ok('品名→pfid は一対一（概念混同なし）')

    print('    参考: pfid → 品名:件数')
    for pfid in sorted(agg):
        print(f'      {pfid:<12} ' + ', '.join(f'{h}:{c}' for h, c in agg[pfid].most_common()))


# ---- 5. fish-price-master.json 検証 ----------------------------------------
def validate_master():
    print('\n[5] fish-price-master.json 構造・健全性')
    p = HERE / 'fish-price-master.json'
    if not p.exists():
        fail('fish-price-master.json なし'); return
    pm = json.loads(p.read_text(encoding='utf-8'))
    prices = pm.get('prices', {})
    if len(prices) >= EXPECTED_MIN_PRICES:
        ok(f'prices {len(prices)}魚種（>= {EXPECTED_MIN_PRICES}）')
    else:
        fail(f'prices {len(prices)}魚種（< {EXPECTED_MIN_PRICES}・生成失敗の疑い）')
    badp = [k for k, v in prices.items()
            if not v.get('size_bands') or not (v.get('wholesale_avg', 0) > 0)]
    if badp:
        fail(f'size_bands 空 or avg<=0: {badp[:5]}')
    else:
        ok('全魚種 size_bands あり・wholesale_avg>0')

    # override 維持
    lost = [pf for pf in OVERRIDE_PFIDS
            if pf in prices and 'verify_daily:2026-05-28' not in prices[pf].get('data_basis', [])]
    if lost:
        fail(f'日報検証 override が消えた: {lost}')
    else:
        ok(f'override 3魚種（{", ".join(OVERRIDE_PFIDS)}）維持')

    # seasonal
    seas = pm.get('seasonal') or {}
    if seas.get('by_pfid'):
        ok(f'seasonal あり（{len(seas["by_pfid"])}魚種）')
    else:
        fail('seasonal ブロックが空')

    # daily_correction
    dc = pm.get('daily_correction')
    if not dc:
        warn('daily_correction なし（daily-prices 未生成 or 全魚fallback）')
        return
    by = dc.get('by_pfid', {})
    lo, hi = dc.get('clamp', [0.5, 2.0])
    probs = []
    for pf, e in by.items():
        if pf not in prices:
            probs.append(f'{pf}:priceに無い')
        if not (lo <= e.get('factor', 0) <= hi):
            probs.append(f'{pf}:factor {e.get("factor")} 範囲外')
        if not (e.get('monthly_avg', 0) > 0):
            probs.append(f'{pf}:monthly_avg<=0')
        if e.get('n_mid', 0) < dc.get('min_mid_obs', 8):
            probs.append(f'{pf}:n_mid不足')
    if probs:
        fail(f'daily_correction 異常: {probs[:5]}')
    else:
        ok(f'daily_correction {len(by)}魚種すべて健全（factor∈[{lo},{hi}]・pfid実在・n_mid≥{dc.get("min_mid_obs")}）')
        print('    ' + ', '.join(f'{k}:{v["factor"]}' for k, v in sorted(by.items())))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--check', action='store_true', help='クロールせず既存JSONだけ検証（オフライン）')
    ap.add_argument('--days', type=int, default=20, help='日報クロールの窓（既定20＝本番同等）')
    ap.add_argument('--wholesale', metavar='YYYYMM', help='この月の月報も取り込んでから検証')
    args = ap.parse_args()

    print('=' * 64)
    print(f'fish-value スモークテスト（{"オフライン検証" if args.check else "フル実行"}）')
    print('=' * 64)

    test_mapping_units()                       # 常時（ネット不要）
    if not args.check:
        run_pipeline(args.days, args.wholesale)
    validate_daily()
    if not args.check:
        audit_mapping(AUDIT_DAYS)
    validate_master()

    print('\n' + '=' * 64)
    print(f'結果: OK={_n_ok} / WARN={_n_warn} / FAIL={_n_fail}')
    print('=' * 64)
    if not args.check and _n_fail == 0:
        print('※ daily-prices.json / fish-price-master.json を更新した。'
              'commit するか `git checkout -- docs/fish-value/` で戻す。')
    return 1 if _n_fail else 0


if __name__ == '__main__':
    sys.exit(main())
