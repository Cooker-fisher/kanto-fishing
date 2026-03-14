#!/usr/bin/env python3
"""診断版: 実際のHTMLを解析してデバッグ"""
import re
from urllib.request import urlopen, Request
from html.parser import HTMLParser

URL = "https://www.gyo.ne.jp/rep_tsuri_view|CID-tadahiko.htm"
USER_AGENT = "Mozilla/5.0 (compatible; FishingInfoBot/1.0)"

req = Request(URL, headers={"User-Agent": USER_AGENT})
with urlopen(req, timeout=20) as r:
    raw = r.read()

# 文字コード確認
print(f"レスポンスサイズ: {len(raw)} bytes")
for enc in ("shift_jis", "euc-jp", "utf-8"):
    try:
        html = raw.decode(enc)
        print(f"デコード成功: {enc}")
        break
    except:
        print(f"デコード失敗: {enc}")

# テーブル数確認
tables = re.findall(r'<table[^>]*>(.*?)</table>', html, re.DOTALL|re.IGNORECASE)
print(f"テーブル数: {len(tables)}")

# 釣果含むテーブルを探す
found = 0
for i, t in enumerate(tables):
    t_flat = re.sub(r'<[^>]+>', '', t)  # タグを除去
    t_flat2 = re.sub(r'\s+', '', t_flat)
    if '釣果' in t_flat2:
        found += 1
        print(f"  釣果テーブル[{i}]: {t_flat2[:80]}")

print(f"釣果テーブル合計: {found}件")

# thタグを直接確認
class ThParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.cells=[]; self._cur=""; self._in=False; self._tag=""
    def handle_starttag(self, tag, attrs):
        if tag.lower() in ("td","th"): self._in=True; self._cur=""; self._tag=tag.lower()
        elif tag.lower()=="br" and self._in: self._cur+="\n"
    def handle_endtag(self, tag):
        if tag.lower() in ("td","th") and self._in:
            self.cells.append((self._tag, self._cur.strip())); self._in=False
    def handle_data(self, data):
        if self._in: self._cur+=data

p = ThParser()
p.feed(html)
catch_cells = [(tag,txt) for tag,txt in p.cells if '釣果' in re.sub(r'\s','',txt)]
print(f"\n釣果セル数: {len(catch_cells)}")
for tag, txt in catch_cells[:5]:
    print(f"  <{tag}>: {repr(txt[:30])}")

