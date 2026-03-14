#!/usr/bin/env python3
import re
from urllib.request import urlopen, Request

URL = "https://www.gyo.ne.jp/rep_tsuri_view|CID-tadahiko.htm"
USER_AGENT = "Mozilla/5.0 (compatible; FishingInfoBot/1.0)"

req = Request(URL, headers={"User-Agent": USER_AGENT})
with urlopen(req, timeout=20) as r:
    raw = r.read()

print(f"bytes: {len(raw)}")
print(f"first100: {raw[:100]}")

# 全エンコードを試す
html = None
for enc in ("shift_jis", "cp932", "euc-jp", "utf-8", "latin-1"):
    try:
        html = raw.decode(enc)
        print(f"OK: {enc}, len={len(html)}")
        break
    except Exception as e:
        print(f"NG: {enc}: {e}")

if html is None:
    html = raw.decode("utf-8", errors="replace")
    print(f"fallback utf-8 replace: len={len(html)}")

# テーブル確認
tables = re.findall(r'<table[^>]*>(.*?)</table>', html, re.DOTALL|re.IGNORECASE)
print(f"tables: {len(tables)}")

for i, t in enumerate(tables[:70]):
    flat = re.sub(r'<[^>]+>', ' ', t)
    flat = re.sub(r'\s+', '', flat)
    if '釣果' in flat or '釣' in flat:
        print(f"  table[{i}] has 釣: {flat[:60]}")

