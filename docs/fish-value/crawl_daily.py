#!/usr/bin/env python3
"""東京都中央卸売市場 日報（豊洲水産）ローリング窓クロール → daily-prices.json

月報（crawl_wholesale.py）を安定ベースに、直近の日報で「当月の実勢レベル」を測る補助データ。
generate_price_master.py がこれを読み、魚種別の daily_correction 係数（= 日報中値 median / 月報avg）
を算出する。中値(中値=nakane)が十分に取れる魚のみ補正対象で、取れない魚は月報＋季節補正へフォールバック。

なぜ中値だけか:
  月報の high/low は「月内の最高値/最安値」＝外れ値。日報の median-high/low と比べると比が
  構造的に割れる（実測: r_low 2〜4.5倍・r_high 0.2〜1.4倍）。粒度が合う中央値どうし
  （日報中値 vs 月報の数量加重 avg）だけが妥当。相対取引で高安しか出ない魚（まだい・ひらめ等）は
  中値欠測のため補正しない（無理に (高+安)/2 を使うと数量加重 avg と乖離してバイアス）。

Usage:
  python crawl_daily.py                 # 直近 DEFAULT_DAYS 営業日分
  python crawl_daily.py --days 20       # 窓サイズ
  python crawl_daily.py --asof 20260705 # 基準日（テスト用・既定は今日）
出力: docs/fish-value/daily-prices.json
"""
from __future__ import annotations
import argparse
import json
import statistics
import sys
import time
import urllib.request
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

JST = timezone(timedelta(hours=9))  # 日報は東京市場（JST）基準。Actions は UTC なので明示する

HERE = Path(__file__).resolve().parent
OUTPUT = HERE / 'daily-prices.json'

NIPPO_HOST = 'https://www.shijou-nippo.metro.tokyo.lg.jp'
UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36')
WAIT_SEC = 0.6

DEFAULT_DAYS = 20        # 目標営業日数（≈4週・週次refreshでも重なり大→安定）
MAX_LOOKBACK = 34        # 暦日の探索上限（水日祝の休場を吸収）
MIN_DAYS_TO_SAVE = 3     # これ未満しか取れなければ保存しない（Actions一時失敗で既存を壊さない）

# 日報 品名 → 釣果価値チェッカー pfid（tmp_fetch_daily.py の検証済みマップを本番採用）
# ⚠ map_hinmei は先着部分一致。より長い/特異なキーを先に置く（部分文字列の誤マッチ防止）。
#   例: 'あまだい' は 'まだい' を含むので madai より前に置かないと甘鯛が真鯛に化ける。
HINMEI_TO_PFID = {
    'あまだい': 'amadai',                              # ← 'まだい' より前（部分一致の誤爆防止）
    'まあじ': 'maaji', 'あじ': 'maaji', 'まいわし': 'maiwashi', 'まさば': 'saba', 'さば': 'saba',
    'まだい': 'madai', 'たい': 'madai', 'すずき': 'seabass', 'ひらめ': 'hirame',
    'かわはぎ': 'kawahagi', 'かさご': 'kasago', 'めばる': 'mebaru', 'たちうお': 'tachiuo',
    'するめいか': 'surumeika', 'やりいか': 'yariika', 'まだこ': 'madako', 'たこ': 'madako',
    'あなご': 'anago', 'きす': 'shirogisu', 'かれい': 'karei', 'ほうぼう': 'houbou',
    'いさき': 'isaki', 'かんぱち': 'kanpachi', 'ぶり': 'buri', 'いなだ': 'inada', 'わらさ': 'warasa',
    'かつお': 'katsuo', 'まはた': 'mahata', 'はた': 'hata', 'きんめだい': 'kinmedai',
    'むつ': 'kuromutsu', 'まこち': 'magochi', 'こち': 'magochi',
    'めじ': 'kihada', 'きわだ': 'kihada', 'きめじ': 'kimeji', 'まいか': 'sumiika',
    'もんごういか': 'mongoika', 'あおりいか': 'aoriika', 'しらぎす': 'shirogisu',
    'いしもち': 'ishimochi', 'くろだい': 'kurodai', 'かます': 'kamasu', 'いしだい': 'ishidai',
    'はなだい': 'hanadai', 'ちだい': 'hanadai', 'おにかさご': 'onikasago',
    'しょうさいふぐ': 'shousaifugu', 'とらふぐ': 'torafugu', 'しいら': 'shiira',
    'ひらまさ': 'hiramasa', 'しまあじ': 'shimaaji',
}


def fetch_day(yyyymmdd: str) -> str | None:
    yyyymm = yyyymmdd[:6]
    url = f'{NIPPO_HOST}/SN/{yyyymm}/{yyyymmdd}/Sui/Sui_K1.csv'
    try:
        req = urllib.request.Request(url, headers={'User-Agent': UA})
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.read().decode('shift-jis', errors='replace')
    except Exception:
        return None


def parse_rows(text: str) -> list[dict]:
    """日報CSV → 行dict。前行の品名を継承し、価格が全て '−' の行は捨てる。"""
    rows: list[dict] = []
    prev_hinmei = ''
    for line in text.split('\n'):
        s = line.strip()
        if (not s or '販売結果' in line or '令和' in line or '【' in line
                or line.startswith('※') or '具体的' in line or '当該相場' in line
                or 'ただし' in line or '第三者' in line):
            continue
        parts = [p.strip() for p in line.split(',')]
        if len(parts) < 9 or parts[0] == '品名':
            continue
        if parts[0]:
            prev_hinmei = parts[0]
        takane, nakane, yasune = parts[6], parts[7], parts[8]
        if all(v in ('−', '-', '') for v in (takane, nakane, yasune)):
            continue
        rows.append({'hinmei': prev_hinmei, 'takane': takane,
                     'nakane': nakane, 'yasune': yasune})
    return rows


def map_hinmei(h: str) -> str | None:
    # 冷凍/活魚/加工品は除外。'冷' は「冷かれい」等の接頭辞だけでなく「きわだ（冷凍）」等の
    # 括弧内サフィックスでも現れるため、位置を問わず含めば除外（生鮮＝「（生鮮）」は残す）。
    if '冷' in h or h.startswith(('活', '開干', 'みそ', '塩', '干', '煮')):
        return None
    for kw, pfid in HINMEI_TO_PFID.items():
        if kw in h:
            return pfid
    return None


def num(s: str) -> float | None:
    s = (s or '').strip()
    if s in ('−', '-', ''):
        return None
    try:
        return float(s.replace(',', ''))
    except ValueError:
        return None


def crawl(asof: date, days: int) -> dict:
    agg: dict[str, dict] = defaultdict(lambda: {'mid': [], 'n_days': set()})
    fetched: list[str] = []
    d = asof
    tries = 0
    while len(fetched) < days and tries < MAX_LOOKBACK:
        ds = d.strftime('%Y%m%d')
        d -= timedelta(days=1)
        tries += 1
        txt = fetch_day(ds)
        if not txt or len(txt) < 1000:
            continue
        fetched.append(ds)
        for r in parse_rows(txt):
            pfid = map_hinmei(r['hinmei'])
            if not pfid:
                continue
            mid = num(r['nakane'])
            if mid is not None:
                agg[pfid]['mid'].append(mid)
                agg[pfid]['n_days'].add(ds)
        time.sleep(WAIT_SEC)

    by_pfid = {}
    for pfid, a in agg.items():
        if not a['mid']:
            continue
        by_pfid[pfid] = {
            'n_days': len(a['n_days']),
            'n_mid': len(a['mid']),
            'mid_median_yen_per_kg': round(statistics.median(a['mid'])),
        }
    return {
        'version': 'v1',
        'source': '東京都中央卸売市場 日報（豊洲水産・中値）',
        'source_url': f'{NIPPO_HOST}/SN/YYYYMM/YYYYMMDD/Sui/Sui_K1.csv',
        # generated_at（実行時刻）は入れない: 同一データの再実行で差分が出て
        # 週次cronが無駄コミットを積むため。鮮度は asof + days_fetched で表現する。
        'asof': asof.strftime('%Y%m%d'),
        'window_business_days': len(fetched),
        'days_fetched': sorted(fetched),
        'by_pfid': dict(sorted(by_pfid.items())),
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument('--days', type=int, default=DEFAULT_DAYS, help='目標営業日数')
    p.add_argument('--asof', help='基準日 YYYYMMDD（既定: 今日）')
    args = p.parse_args()

    # 既定は JST の今日（UTC実行のActionsでも東京市場の日付でasofを決める）
    asof = datetime.strptime(args.asof, '%Y%m%d').date() if args.asof else datetime.now(JST).date()
    doc = crawl(asof, args.days)

    n_fetched = doc['window_business_days']
    print(f'取得営業日: {n_fetched} / 中値を持つ魚: {len(doc["by_pfid"])} 種')
    if n_fetched < MIN_DAYS_TO_SAVE:
        print(f'取得 {n_fetched} 日 < {MIN_DAYS_TO_SAVE} → 保存せず終了'
              f'（既存 daily-prices.json を保護）', file=sys.stderr)
        return 0

    with open(OUTPUT, 'w', encoding='utf-8') as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)
    print(f'書出: {OUTPUT.name}（窓 {doc["days_fetched"][0]}..{doc["days_fetched"][-1]}）')
    return 0


if __name__ == '__main__':
    sys.exit(main())
