"""HTML 全再生成ドライバ（クロールスキップ）。
catches.json (スナップショット) + history.json から docs/ 配下の全 HTML を再生成する。

クロールせず既存 data を使うため、catches.json の data 自体は当日 sparse のままだが、
各 build 関数が data/V2/*.csv (過去全期間) から hist_rows を補完するので、過去データは
反映される。GitHub Actions の毎日 16:30 JST 実行と同じ HTML 出力結果が得られる。

実行: python dustbox/run_html_only.py
"""
import json, sys, os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

import crawler
from datetime import datetime

print("=== run_html_only.py: 全 HTML 再生成（クロールスキップ）===")

with open("catches.json", encoding="utf-8") as f:
    snap = json.load(f)
valid_catches = snap.get("data", snap) if isinstance(snap, dict) else snap
print(f"  catches.json data: {len(valid_catches)} 件")

with open("history.json", encoding="utf-8") as f:
    history = json.load(f)

crawled_at = datetime.now(crawler.JST).replace(tzinfo=None).strftime("%Y/%m/%d %H:%M")

# weather_data: ZONE C 出船リスク予報を出すため forecast.json (disk) を補完。
# クロールスキップで weather_data を構築しないと build_html は risk_grid_html=""
# となり「出船リスク予報」セクションが消える regression の対策。
weather_data = {}
if os.path.exists("forecast.json"):
    try:
        with open("forecast.json", encoding="utf-8") as f:
            weather_data["_forecast_data"] = json.load(f)
        print(f"  forecast.json: {len(weather_data['_forecast_data'].get('days', {}))} 日分 (出船リスク予報用)")
    except Exception as e:
        print(f"  forecast.json 読込失敗: {e}")

print("build_html (index.html) 実行中...")
import os as _os
with open(_os.path.join(crawler.WEB_DIR, "index.html"), "w", encoding="utf-8") as f:
    f.write(crawler.build_html(valid_catches, crawled_at, history, weather_data))

print("build_fish_pages 実行中...")
crawler.build_fish_pages(valid_catches, history, crawled_at)

print("build_area_pages 実行中...")
crawler.build_area_pages(valid_catches, history, crawled_at, weather_data)

print("build_fish_area_pages 実行中...")
crawler.build_fish_area_pages(valid_catches, crawled_at, history)

print("build_calendar_page 実行中...")
with open(_os.path.join(crawler.WEB_DIR, "calendar.html"), "w", encoding="utf-8") as f:
    f.write(crawler.build_calendar_page(crawled_at))

print("build_ship_pages 実行中...")
crawler.build_ship_pages(valid_catches, crawled_at)

print("build_sitemap 実行中...")
crawler.build_sitemap(valid_catches)

print("=== 全 HTML 再生成 完了 ===")
