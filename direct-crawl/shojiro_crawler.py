"""
shojiro_crawler.py — 庄治郎丸 釣果サイト専用クローラー

shojiromaru.net/catch.html の jsonget.php API から釣り場情報を取得し、
catches_raw.json の庄治郎丸レコードの point_raw を補完する。

マッチング: date × tsuri_mono（正規化魚種名）で突き合わせ。
出力: catches_raw.json を直接更新（point_raw が空のレコードのみ）

実行:
    python direct-crawl/shojiro_crawler.py [--dry-run]
"""

import json
import os
import re
import sys
import time
from datetime import datetime
from html.parser import HTMLParser
from urllib.request import Request, urlopen
from urllib.parse import urlencode

sys.stdout.reconfigure(encoding="utf-8")

ROOT_DIR       = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CATCHES_RAW    = os.path.join(ROOT_DIR, "crawl", "catches_raw.json")
TSURI_MAP_PATH = os.path.join(ROOT_DIR, "normalize", "tsuri_mono_map_draft.json")
SITE_URL       = "https://shojiromaru.net"
SHIP_NAME      = "庄治郎丸"
SLEEP_SEC      = 0.8

# ── 魚種正規化 ────────────────────────────────────────────────────────────────

def _load_tsuri_map():
    with open(TSURI_MAP_PATH, encoding="utf-8") as f:
        raw = json.load(f)
    return raw.get("TSURI_MONO_MAP", raw)

def normalize_fish(raw_name: str, tsuri_map: dict) -> str:
    """API の fish name を tsuri_mono に正規化。"""
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
    """「2026年04月20日（月）」→「2026/04/20」"""
    m = _DATE_RE.search(choka_date)
    if not m:
        return ""
    y, mo, d = m.group(1), m.group(2).zfill(2), m.group(3).zfill(2)
    return f"{y}/{mo}/{d}"

# ── HTML エンティティ除去 ────────────────────────────────────────────────────

def strip_html(text: str) -> str:
    text = re.sub(r'&#\d+;', '', text)
    text = re.sub(r'&[a-z]+;', '', text)
    text = re.sub(r'<[^>]+>', '', text)
    return text.strip()

# ── API 取得 ─────────────────────────────────────────────────────────────────

def fetch_site_no() -> str:
    req = Request(f"{SITE_URL}/SiteNo.txt",
                  headers={"User-Agent": "Mozilla/5.0 (compatible; kanto-fishing-bot/1.0)"})
    return urlopen(req).read().decode("utf-8").strip()

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
    # choka_no を持つ dict のみ返す
    return [r for r in choka if isinstance(r, dict) and "choka_no" in r]

def fetch_all_choka(site: str) -> list:
    """全 select × 全 page を取得して全釣果レコードを返す。"""
    all_rows = []
    seen_ids = set()
    for select in range(0, 20):  # select=0(最新60件), 1〜max月別
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
        # select > 0 で page=0 が空なら終了（select=0 は常に最新60件なので除外判定しない）
        if select > 0:
            if not fetch_choka(site, select, 0):
                break
        time.sleep(SLEEP_SEC)
    return all_rows

# ── メイン ───────────────────────────────────────────────────────────────────

def build_point_lookup(choka_rows: list, tsuri_map: dict) -> dict:
    """(date, tsuri_mono) → point_name の辞書を構築。"""
    lookup = {}
    for row in choka_rows:
        date_str  = parse_date(row.get("choka_date", ""))
        point     = strip_html(row.get("ship_name", ""))
        if not date_str or not point:
            continue
        # choka_fish の各魚種に対してエントリ追加
        for fish_item in row.get("choka_fish", []):
            fish_raw   = strip_html(fish_item.get("name", ""))
            tsuri_mono = normalize_fish(fish_raw, tsuri_map)
            key = (date_str, tsuri_mono)
            if key not in lookup:
                lookup[key] = point
        # fisher_ct からも魚種を補完（choka_fish が空の場合）
        if not row.get("choka_fish"):
            fisher = row.get("fisher_ct", "")
            fish_raw = fisher.split()[0] if fisher else ""
            if fish_raw:
                tsuri_mono = normalize_fish(fish_raw, tsuri_map)
                key = (date_str, tsuri_mono)
                if key not in lookup:
                    lookup[key] = point
    return lookup

def run(dry_run: bool = False):
    print("=== 庄治郎丸 ポイント補完クローラー ===")

    tsuri_map = _load_tsuri_map()

    # 1. API から全釣果取得
    print("SiteNo 取得中...", flush=True)
    site = fetch_site_no()
    print(f"SiteNo={site}  釣果データ取得中...", flush=True)
    choka_rows = fetch_all_choka(site)
    print(f"取得: {len(choka_rows)}件", flush=True)

    # 2. lookup 構築
    lookup = build_point_lookup(choka_rows, tsuri_map)
    print(f"ポイントルックアップ: {len(lookup)}エントリ")

    # 3. catches_raw.json の庄治郎丸レコードを更新
    with open(CATCHES_RAW, encoding="utf-8") as f:
        catches = json.load(f)

    updated = 0
    for rec in catches:
        if rec.get("ship") != SHIP_NAME:
            continue
        if rec.get("point_raw"):  # 既に入っている場合はスキップ
            continue
        date_str = (rec.get("date") or "").replace("-", "/")
        fish_raw = rec.get("fish_raw") or rec.get("tsuri_mono_raw") or ""
        # fish_rawから魚種を正規化
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
        print("catches_raw.json を更新しました。")
        print("次: python crawler.py --export-csv && python analysis/V2/methods/run_full_deepdive.py 庄治郎丸")
    elif dry_run:
        print("[DRY RUN] 実際の更新はしていません。")

if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv
    run(dry_run=dry_run)
