"""
koueimaru_crawler.py — 幸栄丸（koueimaru-f.jp）釣果サイト専用クローラー

koueimaru-f.jp/jsonget.php API から choka_comment を取得し、
キーワードマッチングでポイントを抽出して catches_raw.json を補完する。

ポイントキーワード（幸栄丸固有）: 北沖、真沖、南沖、大根、魚礁、湾内 など

実行:
    python direct-crawl/koueimaru_crawler.py [--dry-run]
"""

import json
import os
import re
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

# ポイント候補キーワード（出現順優先・先頭一致）
POINT_KEYWORDS = [
    "北沖", "真沖", "南沖", "大根", "魚礁", "湾内",
    "岸寄り", "沖合", "北側", "南側",
]

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

# ── HTML 除去 ─────────────────────────────────────────────────────────────────

def strip_html(text: str) -> str:
    import html as htmlmod
    text = htmlmod.unescape(text)
    text = re.sub(r'<[^>]+>', ' ', text)
    return re.sub(r'\s+', ' ', text).strip()

# ── ポイント抽出 ──────────────────────────────────────────────────────────────

def extract_point(comment: str) -> str:
    """コメントから最初に出現するポイントキーワードを返す。"""
    for kw in POINT_KEYWORDS:
        if kw in comment:
            return kw
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
    for rec in catches:
        if rec.get("ship") != SHIP_NAME:
            continue
        if rec.get("point_raw"):
            continue
        date_str = (rec.get("date") or "").replace("-", "/")
        fish_raw = rec.get("fish_raw") or rec.get("tsuri_mono_raw") or ""
        tsuri_mono = normalize_fish(fish_raw.split()[0] if fish_raw else "", tsuri_map)
        if not tsuri_mono:
            continue
        point = lookup.get((date_str, tsuri_mono))
        if point:
            if not dry_run:
                rec["point_raw"] = point
            updated += 1

    print(f"補完対象: {updated}件", flush=True)

    if not dry_run and updated > 0:
        with open(CATCHES_RAW, "w", encoding="utf-8") as f:
            json.dump(catches, f, ensure_ascii=False)
        print(f"{CATCHES_RAW} を更新しました。")
    elif dry_run:
        print("[DRY RUN] 実際の更新はしていません。")

if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv
    run(dry_run=dry_run)
