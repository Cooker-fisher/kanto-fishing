"""
koueimaru_crawler.py — 幸栄丸（koueimaru-f.jp）釣果サイト専用クローラー

koueimaru-f.jp/jsonget.php API から choka_comment を取得し、
3段階でポイントを補完して catches_raw.json を更新する。

[ポイント補完の優先順位]
  ① コメントキーワード（北沖/真沖/南沖/魚礁/湾内/大根）
  ② 魚種デフォルト（データから確認した支配的ポイント ≥65%）
  ③ 気象推定（ワラサ/イナダ/ヒラマサ等の分散コンボに wave_height+SST+wind で分岐）

実行:
    python direct-crawl/koueimaru_crawler.py [--dry-run]
"""

import json
import os
import re
import sqlite3
import sys
import time
from urllib.request import Request, urlopen
from urllib.parse import urlencode

sys.stdout.reconfigure(encoding="utf-8")

ROOT_DIR       = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CATCHES_RAW    = os.path.join(ROOT_DIR, "crawl", "catches_raw.json")
TSURI_MAP_PATH = os.path.join(ROOT_DIR, "normalize", "tsuri_mono_map_draft.json")
SITE_URL       = "https://koueimaru-f.jp"
SITE_NO        = "272"
SHIP_NAME      = "幸栄丸"
SLEEP_SEC      = 0.8

# ポイント候補キーワード → 保存名マップ
# 「北沖」等は他船宿でも使うため「鹿島{名}」に変換して衝突を防ぐ
POINT_KEYWORDS = {
    "北沖": "鹿島北沖",
    "真沖": "鹿島真沖",
    "南沖": "鹿島南沖",
    "魚礁": "鹿島魚礁",
    "大根": "大根",      # N<30 で最適化対象外のため変換なし
    "湾内": "鹿島湾内",
}

# コメントにポイント記載なし時のフォールバック（魚種別デフォルトポイント）
# 根拠: catches_raw.json の point_rawあり158件から集計
#   N≥3 かつ最頻ポイント≥65% のみ採用
FISH_DEFAULT_POINT = {
    # 支配的ポイント ≥65%（N≥10 or 明確な傾向）
    "ヒラメ":       "鹿島北沖",   # 70% N=44
    "マハタ":       "鹿島北沖",   # 68% N=25
    "ヤリイカ":     "鹿島真沖",   # 86% N=15（水深60-70m帯＝真沖）
    "マダコ":       "鹿島真沖",   # 80% N=6
    "マダイ":       "鹿島南沖",   # 67% N=6
    "フグ":         "鹿島南沖",   # 57% N=7
    # N小さいが傾向明確
    "アブラボウズ": "鹿島北沖",   # 100% N=3
    "カサゴ":       "鹿島北沖",   # 67% N=3
    "カツオ":       "鹿島真沖",   # 100% N=3
    "メバル":       "鹿島北沖",   # 100% N=3
}

# 気象推定を試みる魚種（ワラサ/イナダ/ヒラマサは分散 → wave+SST+wind で分岐）
FISH_WEATHER_ESTIMATE = {"ワラサ", "イナダ", "ヒラマサ", "スジイカ", "ムギイカ"}

WEATHER_DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "ocean", "weather_cache.sqlite")

# ── 魚種正規化 ────────────────────────────────────────────────────────────────

def _load_tsuri_map():
    with open(TSURI_MAP_PATH, encoding="utf-8") as f:
        raw = json.load(f)
    return raw.get("TSURI_MONO_MAP", raw)

def normalize_fish(raw_name: str, tsuri_map: dict) -> str:
    s = raw_name.strip()
    if s in tsuri_map:
        return s
    for canon, patterns in tsuri_map.items():
        if s in patterns:
            return canon
    for canon, patterns in tsuri_map.items():
        if any(p in s for p in patterns):
            return canon
    return s

# ── 日付パース ────────────────────────────────────────────────────────────────

_DATE_RE = re.compile(r'(\d{4})年(\d{1,2})月(\d{1,2})日')

def parse_date(choka_date: str) -> str:
    m = _DATE_RE.search(choka_date)
    if not m:
        return ""
    y, mo, d = m.group(1), m.group(2).zfill(2), m.group(3).zfill(2)
    return f"{y}/{mo}/{d}"

# ── 気象ベース ポイント推定 ──────────────────────────────────────────────────────

_weather_conn = None
_weather_coord = None  # (lat, lon)

def _get_weather_for_date(date_str: str) -> dict:
    """date_str='YYYY/MM/DD' → wave_height, sst, wind_dir (朝05-12時JST平均)。失敗時は {}。"""
    global _weather_conn, _weather_coord
    if not os.path.exists(WEATHER_DB):
        return {}
    try:
        if _weather_conn is None:
            _weather_conn = sqlite3.connect(WEATHER_DB)
            coords = _weather_conn.execute(
                "SELECT DISTINCT lat, lon FROM weather"
            ).fetchall()
            TARGET_LAT, TARGET_LON = 35.97, 140.77  # 鹿島沖
            _weather_coord = min(coords, key=lambda c: abs(c[0]-TARGET_LAT) + abs(c[1]-TARGET_LON))
        lat, lon = _weather_coord
        # 05-12 JST = UTC 20:00-03:00 (前日20時〜当日03時)
        y, mo, d = date_str.split("/")
        dt_prefix = f"{y}-{mo}-{d}"
        rows = _weather_conn.execute(
            """SELECT wave_height, sst, wind_dir FROM weather
               WHERE lat=? AND lon=?
               AND (dt LIKE ? OR (dt >= ? AND dt < ?))
               AND CAST(strftime('%H', dt) AS INT) <= 3""",
            (lat, lon, f"{y}-{mo}-{int(d)-1:02d} 2%", f"{dt_prefix} 00:00", f"{dt_prefix} 04:00")
        ).fetchall()
        # 当日早朝も追加
        rows += _weather_conn.execute(
            """SELECT wave_height, sst, wind_dir FROM weather
               WHERE lat=? AND lon=? AND dt LIKE ?
               AND CAST(strftime('%H', dt) AS INT) BETWEEN 20 AND 23""",
            (lat, lon, f"{y}-{mo}-{int(d)-1:02d}%")
        ).fetchall()
        if not rows:
            return {}
        wave_vals = [r[0] for r in rows if r[0] is not None]
        sst_vals  = [r[1] for r in rows if r[1] is not None]
        dir_vals  = [r[2] for r in rows if r[2] is not None]
        result = {}
        if wave_vals: result["wave_height"] = sum(wave_vals) / len(wave_vals)
        if sst_vals:  result["sst"]         = sum(sst_vals)  / len(sst_vals)
        if dir_vals:  result["wind_dir"]     = sum(dir_vals)  / len(dir_vals)
        return result
    except Exception:
        return {}

def _wind_sector(deg: float) -> str:
    """度数 → 8方位文字列。"""
    sectors = ["N","NE","E","SE","S","SW","W","NW"]
    return sectors[int((deg + 22.5) / 45) % 8]

def estimate_point_by_weather(tsuri_mono: str, date_str: str) -> str:
    """
    気象条件から幸栄丸のポイントを推定。FISH_WEATHER_ESTIMATE 対象魚種のみ呼ばれる。
    ルール（分析結果: N=145 wave中央値 北沖1.23m / 南沖0.75m / 大根0.66m）:
      波が高く東寄り風 → 北沖避難
      波が高く西/南西系風 → 真沖
      凪 + 夏季(SST≥20℃) + 南寄り風 → 大根（青物回遊帯）
      それ以外 → 北沖（最頻）
    """
    wx = _get_weather_for_date(date_str)
    if not wx:
        return "鹿島北沖"  # フォールバック

    wave  = wx.get("wave_height", 1.0)
    sst   = wx.get("sst")
    wind  = _wind_sector(wx.get("wind_dir", 315))

    # 荒天（1.5m超）→ 風向で北沖 or 真沖
    if wave >= 1.5:
        if wind in ("NE", "E", "N"):
            return "鹿島北沖"
        return "鹿島真沖"

    # 夏季凪（SST≥20℃, wave<0.8m）+ 南寄り → 大根（青物/回遊狙い）
    if sst is not None and sst >= 20.0 and wave < 0.8 and wind in ("SW", "S", "SE"):
        return "大根"

    # 中程度波（0.8-1.5m）+ 北西/西 → 北沖
    if 0.8 <= wave < 1.5 and wind in ("NW", "W"):
        return "鹿島北沖"

    # 凪 + 北東/東 → 南沖（追い風で南側も狙える）
    if wave < 0.8 and wind in ("NE", "E"):
        return "鹿島南沖"

    return "鹿島北沖"  # デフォルト（最頻33%）

# ── HTML 除去 ─────────────────────────────────────────────────────────────────

def strip_html(text: str) -> str:
    import html as htmlmod
    text = htmlmod.unescape(text)
    text = re.sub(r'<[^>]+>', ' ', text)
    return re.sub(r'\s+', ' ', text).strip()

# ── ポイント抽出 ──────────────────────────────────────────────────────────────

def extract_point(comment: str) -> str:
    """コメントから最初に出現するポイントキーワードを正規化名で返す。"""
    for kw, canonical in POINT_KEYWORDS.items():
        if kw in comment:
            return canonical
    return ""

# ── API 取得 ─────────────────────────────────────────────────────────────────

def fetch_choka(site: str, select: int, page: int) -> list:
    data = urlencode({"site": site, "page": page, "select": select}).encode()
    req = Request(f"{SITE_URL}/jsonget.php", data=data,
                  headers={"User-Agent": "Mozilla/5.0 (compatible; kanto-fishing-bot/1.0)",
                           "Content-Type": "application/x-www-form-urlencoded",
                           "Referer": f"{SITE_URL}/catch.html"})
    raw = urlopen(req).read()
    try:
        d = json.loads(raw.decode("cp932"))
    except Exception:
        d = json.loads(raw.decode("utf-8", errors="replace"))
    if not isinstance(d, dict):
        return []
    choka = d.get("choka", [])
    if not isinstance(choka, list):
        return []
    return [r for r in choka if isinstance(r, dict) and "choka_no" in r]

def fetch_all_choka(site: str) -> list:
    all_rows = []
    seen_ids = set()
    for select in range(0, 20):
        page = 0
        while True:
            rows = fetch_choka(site, select, page)
            if not rows:
                break
            new = [r for r in rows if r["choka_no"] not in seen_ids]
            if not new:
                break
            for r in new:
                seen_ids.add(r["choka_no"])
            all_rows.extend(new)
            page += 1
            time.sleep(SLEEP_SEC)
        if select > 0:
            if not fetch_choka(site, select, 0):
                break
        time.sleep(SLEEP_SEC)
    return all_rows

# ── lookup 構築 ───────────────────────────────────────────────────────────────

def build_point_lookup(choka_rows: list, tsuri_map: dict) -> dict:
    """(date, tsuri_mono) → point_name の辞書を構築。"""
    lookup = {}
    for row in choka_rows:
        date_str = parse_date(row.get("choka_date", ""))
        if not date_str:
            continue
        comment = strip_html(row.get("choka_comment", ""))
        point = extract_point(comment)
        if not point:
            continue
        for fish_item in row.get("choka_fish", []):
            fish_raw = strip_html(fish_item.get("name", ""))
            tsuri_mono = normalize_fish(fish_raw, tsuri_map)
            key = (date_str, tsuri_mono)
            if key not in lookup:
                lookup[key] = point
    return lookup

# ── メイン ───────────────────────────────────────────────────────────────────

def run(dry_run: bool = False):
    print(f"=== {SHIP_NAME} ポイント補完クローラー ===")

    tsuri_map = _load_tsuri_map()

    print(f"釣果データ取得中 (SiteNo={SITE_NO})...", flush=True)
    choka_rows = fetch_all_choka(SITE_NO)
    print(f"取得: {len(choka_rows)}件", flush=True)

    lookup = build_point_lookup(choka_rows, tsuri_map)
    print(f"ポイントルックアップ: {len(lookup)}エントリ")

    # ポイント分布を表示
    from collections import Counter
    pt_count = Counter(lookup.values())
    print(f"ポイント分布: {dict(pt_count.most_common(10))}")

    with open(CATCHES_RAW, encoding="utf-8") as f:
        catches = json.load(f)

    updated = 0
    cnt_comment = 0
    cnt_default = 0
    cnt_weather = 0
    for rec in catches:
        if rec.get("ship") != SHIP_NAME:
            continue
        if rec.get("point_raw"):
            continue
        date_str  = (rec.get("date") or "").replace("-", "/")
        fish_raw  = rec.get("fish_raw") or rec.get("tsuri_mono_raw") or ""
        tsuri_mono = normalize_fish(fish_raw.split()[0] if fish_raw else "", tsuri_map)
        if not tsuri_mono:
            continue

        # ① コメントキーワード（日付×魚種の完全一致）
        point = lookup.get((date_str, tsuri_mono))
        if point:
            cnt_comment += 1
        else:
            # ② 魚種デフォルト（支配的ポイント ≥65%）
            point = FISH_DEFAULT_POINT.get(tsuri_mono)
            if point:
                cnt_default += 1
            elif tsuri_mono in FISH_WEATHER_ESTIMATE and date_str:
                # ③ 気象推定（ワラサ/イナダ/ヒラマサ等の分散コンボ）
                point = estimate_point_by_weather(tsuri_mono, date_str)
                if point:
                    cnt_weather += 1

        if point:
            if not dry_run:
                rec["point_raw"] = point
            updated += 1

    print(f"補完対象: {updated}件  "
          f"(①コメント={cnt_comment} / ②魚種デフォルト={cnt_default} / ③気象推定={cnt_weather})",
          flush=True)

    if not dry_run and updated > 0:
        with open(CATCHES_RAW, "w", encoding="utf-8") as f:
            json.dump(catches, f, ensure_ascii=False)
        print(f"{CATCHES_RAW} を更新しました。")
    elif dry_run:
        print("[DRY RUN] 実際の更新はしていません。")

if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv
    run(dry_run=dry_run)
