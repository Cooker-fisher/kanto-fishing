#!/usr/bin/env python3
"""
関東船釣り情報クローラー v2
対象: gyo.ne.jp（関東沖釣り情報）
実行: python3 crawler.py
出力: catches.json / index.html
"""

import re, json, time
from datetime import datetime
from urllib.request import urlopen, Request
from urllib.error import URLError
from html.parser import HTMLParser

SHIPS = [
    {"area": "外川",        "name": "孝進丸",       "cid": "ikoshin"},
    {"area": "外川",        "name": "三浦丸",        "cid": "miura"},
    {"area": "片貝",        "name": "勇幸丸",        "cid": "yukou"},
    {"area": "大原",        "name": "義之丸",        "cid": "yoshino"},
    {"area": "松部港",      "name": "和八丸",        "cid": "wahachi"},
    {"area": "伊戸",        "name": "海老丸",        "cid": "ebimaru"},
    {"area": "勝山",        "name": "新盛丸",        "cid": "sinsei"},
    {"area": "富津",        "name": "川崎丸",        "cid": "kawasaki"},
    {"area": "江戸川放水路","name": "たかはし遊船",  "cid": "takahashi_y"},
    {"area": "浦安",        "name": "吉久",          "cid": "yoshikyu"},
    {"area": "新山下",      "name": "山下橋黒川本家","cid": "kurokawa"},
    {"area": "金沢八景",    "name": "一之瀬丸",      "cid": "ichinose"},
    {"area": "金沢八景",    "name": "忠彦丸",        "cid": "tadahiko"},
    {"area": "金沢八景",    "name": "米元釣船店",    "cid": "yonemoto"},
    {"area": "久比里",      "name": "みのすけ丸",    "cid": "minosukemaru"},
    {"area": "久比里",      "name": "山下丸",        "cid": "yamashita"},
    {"area": "久比里",      "name": "山天丸",        "cid": "yamaten"},
    {"area": "久里浜",      "name": "大正丸",        "cid": "taishou"},
    {"area": "松輪",        "name": "浜鈴丸",        "cid": "hamasuzu"},
    {"area": "松輪",        "name": "瀬戸丸",        "cid": "sedo"},
    {"area": "三浦・毘沙門","name": "新店丸",        "cid": "shinmise"},
    {"area": "長井港",      "name": "はら丸",        "cid": "haramaru"},
    {"area": "長井港",      "name": "丸八丸",        "cid": "maruhachi"},
    {"area": "葉山鐙摺港",  "name": "愛正丸",        "cid": "aisho"},
    {"area": "葉山鐙摺",    "name": "まさみ丸",      "cid": "masami"},
    {"area": "腰越",        "name": "飯岡丸",        "cid": "iioka"},
    {"area": "茅ヶ崎",      "name": "ちがさき丸",    "cid": "chigasaki"},
    {"area": "平塚",        "name": "庄三郎丸",      "cid": "shou3"},
    {"area": "小田原早川",  "name": "平安丸",        "cid": "heian"},
    {"area": "東伊豆・網代","name": "鈴喜丸",        "cid": "suzukimaru"},
    {"area": "宇佐美",      "name": "秀正丸",        "cid": "hidemasa"},
    {"area": "宇佐美港",    "name": "藤吉丸",        "cid": "toukichimaru"},
    {"area": "東伊豆",      "name": "伊東港政一丸",  "cid": "masaichimaru"},
    {"area": "戸田港",      "name": "ふじ丸",        "cid": "fujimaru"},
    {"area": "戸田",        "name": "福将丸",        "cid": "fukusyo"},
    {"area": "古宇",        "name": "吉田丸",        "cid": "yosida"},
]

BASE_URL = "https://www.gyo.ne.jp/rep_tsuri_view|CID-{cid}.htm"
USER_AGENT = "Mozilla/5.0 (compatible; FishingInfoBot/1.0)"

FISH_MAP = {
    "アジ":      ["アジ", "ライトアジ", "LTアジ"],
    "タチウオ":  ["タチウオ"],
    "フグ":      ["フグ", "トラフグ", "ショウサイ"],
    "カワハギ":  ["カワハギ"],
    "マダイ":    ["マダイ", "真鯛"],
    "シロギス":  ["シロギス", "キス"],
    "イサキ":    ["イサキ"],
    "ヤリイカ":  ["ヤリイカ"],
    "スルメイカ":["スルメイカ"],
    "マダコ":    ["タコ", "マダコ"],
    "カサゴ":    ["カサゴ"],
    "メバル":    ["メバル"],
    "ワラサ":    ["ワラサ", "イナダ"],
    "アマダイ":  ["アマダイ"],
    "メダイ":    ["メダイ"],
    "サワラ":    ["サワラ"],
    "ヒラメ":    ["ヒラメ"],
    "マゴチ":    ["マゴチ"],
}

Z2H = str.maketrans("０１２３４５６７８９", "0123456789")

class TxtParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []; self._skip = False
    def handle_starttag(self, tag, attrs):
        if tag in ("script","style"): self._skip = True
        if tag in ("td","th","div","tr","p","br","li"): self.parts.append("\n")
    def handle_endtag(self, tag):
        if tag in ("script","style"): self._skip = False
    def handle_data(self, data):
        if not self._skip: self.parts.append(data)
    def text(self): return "".join(self.parts)

def guess_fish(t):
    return [f for f, kws in FISH_MAP.items() if any(k in t for k in kws)] or ["不明"]

def extract_count(t):
    t = t.translate(Z2H)
    m = re.search(r"(\d+)[～〜](\d+)\s*[匹本尾枚]", t)
    if m: return {"min":int(m[1]),"max":int(m[2])}
    m = re.search(r"(\d+)\s*[匹本尾枚]", t)
    if m: v=int(m[1]); return {"min":v,"max":v}
    return None

def extract_size(t):
    t = t.translate(Z2H)
    m = re.search(r"(\d+)[～〜](\d+)\s*[cｃ㎝Ccm]{1,2}", t)
    if m: return {"min":int(m[1]),"max":int(m[2])}
    m = re.search(r"(\d+)\s*[cｃ㎝Ccm]{1,2}", t)
    if m: v=int(m[1]); return {"min":v,"max":v}
    return None

def is_empty(t):
    return re.match(r"^[~～〜\-\s]*c[m]?[~～〜\s]*[匹本尾枚]$", t.translate(Z2H), re.I) is not None \
        or t.strip() in ("", "～㎝　～匹", "～cm　～匹")

def parse(text, ship, area, year):
    lines = text.split("\n")
    results = []
    month, day = datetime.now().month, None
    for i, raw in enumerate(lines):
        line = raw.strip()
        if re.match(r"^[０-９\d]+$", line) and line:
            try:
                n = int(line.translate(Z2H))
                nxt = lines[i+1].strip() if i+1 < len(lines) else ""
                if nxt == "月": month = n
                elif nxt == "日": day = n
            except: pass
        if "\t" in raw:
            label, *rest = raw.split("\t", 1)
            val = rest[0].strip() if rest else ""
            if label.strip() == "果" and val and not is_empty(val):
                results.append({
                    "ship": ship, "area": area,
                    "date": f"{year}/{month:02d}/{day:02d}" if month and day else None,
                    "month": month, "day": day,
                    "catch_raw": val,
                    "fish": guess_fish(val),
                    "count_range": extract_count(val),
                    "size_range":  extract_size(val),
                })
    return results

def fetch(url):
    try:
        with urlopen(Request(url, headers={"User-Agent": USER_AGENT}), timeout=20) as r:
            raw = r.read()
            for enc in ("shift_jis","euc-jp","utf-8"):
                try: return raw.decode(enc)
                except: pass
            return raw.decode("utf-8", errors="replace")
    except URLError as e:
        print(f"ERROR: {e}"); return None

def build_html(catches, crawled_at):
    fish_summary = {}
    for c in catches:
        for f in c["fish"]:
            if f != "不明":
                fish_summary.setdefault(f, []).append(c)

    cards = ""
    for fish, cs in sorted(fish_summary.items(), key=lambda x: -len(x[1])):
        areas = list(dict.fromkeys(c["area"] for c in cs[:3]))
        cards += f'<div class="fc"><div class="fn">{fish}</div><div class="fk">{len(cs)}件</div><div class="fa">{" / ".join(areas)}</div></div>'

    rows = ""
    for c in sorted(catches, key=lambda x: x["date"] or "", reverse=True)[:30]:
        cnt = ""
        if c["count_range"]:
            mn,mx = c["count_range"]["min"], c["count_range"]["max"]
            cnt = f"{mn}〜{mx}" if mn!=mx else str(mn)
        sz = ""
        if c["size_range"]:
            mn,mx = c["size_range"]["min"], c["size_range"]["max"]
            sz = f"{mn}〜{mx}cm" if mn!=mx else f"{mn}cm"
        fish_str = "・".join(c["fish"])
        rows += f"<tr><td>{c['date'] or '-'}</td><td>{c['area']}</td><td>{c['ship']}</td><td>{fish_str}</td><td>{cnt}</td><td>{sz}</td></tr>"

    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>関東船釣り釣果情報 | 今日何が釣れてる？</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:'Helvetica Neue',Arial,sans-serif;background:#0a1628;color:#e0e8f0}}
header{{background:#0d2137;padding:16px 24px;border-bottom:2px solid #1a6ea8}}
header h1{{font-size:22px;color:#4db8ff}}
header p{{font-size:12px;color:#7a9bb5;margin-top:4px}}
.wrap{{max-width:1100px;margin:0 auto;padding:20px 16px}}
h2{{font-size:15px;color:#4db8ff;border-left:4px solid #4db8ff;padding-left:10px;margin:24px 0 12px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(120px,1fr));gap:10px}}
.fc{{background:#0d2137;border:1px solid #1a4060;border-radius:8px;padding:12px;text-align:center}}
.fc:hover{{border-color:#4db8ff}}
.fn{{font-size:16px;font-weight:bold;color:#fff}}
.fk{{font-size:12px;color:#4db8ff;margin-top:4px}}
.fa{{font-size:11px;color:#7a9bb5;margin-top:2px}}
table{{width:100%;border-collapse:collapse;font-size:13px}}
th{{background:#0d2137;color:#4db8ff;padding:8px;text-align:left;border-bottom:1px solid #1a4060}}
td{{padding:8px;border-bottom:1px solid #0d2137}}
tr:hover td{{background:#0d2137}}
.note{{font-size:11px;color:#7a9bb5;text-align:right;margin-top:8px}}
</style>
</head>
<body>
<header>
  <h1>🎣 関東船釣り釣果情報</h1>
  <p>今日、何が釣れてる？ 関東エリアの船宿釣果をリアルタイム集計</p>
</header>
<div class="wrap">
  <h2>🐟 釣れている魚</h2>
  <div class="grid">{cards}</div>
  <h2>📋 最新の釣果</h2>
  <table>
    <tr><th>日付</th><th>エリア</th><th>船宿</th><th>魚種</th><th>数量</th><th>サイズ</th></tr>
    {rows}
  </table>
  <p class="note">最終更新: {crawled_at} ／ 総件数: {len(catches)} 件</p>
</div>
</body>
</html>"""

def main():
    all_catches = []
    errors = []
    now = datetime.now()
    crawled_at = now.strftime("%Y/%m/%d %H:%M")
    year = now.year

    print(f"=== 関東船釣りクローラー 開始: {crawled_at} ===")
    print(f"対象: {len(SHIPS)} 船宿\n")

    for s in SHIPS:
        url = BASE_URL.format(cid=s["cid"])
        print(f"  [{s['area']}] {s['name']} ...", end=" ", flush=True)
        html = fetch(url)
        if not html:
            errors.append(s["name"]); continue
        p = TxtParser(); p.feed(html)
        catches = parse(p.text(), s["name"], s["area"], year)
        print(f"{len(catches)} 件")
        all_catches.extend(catches)
        time.sleep(1.2)

    with open("catches.json","w",encoding="utf-8") as f:
        json.dump({"crawled_at":crawled_at,"total":len(all_catches),"errors":errors,"data":all_catches}, f, ensure_ascii=False, indent=2)

    with open("index.html","w",encoding="utf-8") as f:
        f.write(build_html(all_catches, crawled_at))

    print(f"\n=== 完了 ===")
    print(f"釣果: {len(all_catches)} 件 ／ エラー: {errors or 'なし'}")
    print(f"出力: catches.json / index.html")

if __name__ == "__main__":
    main()
