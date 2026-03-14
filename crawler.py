#!/usr/bin/env python3
"""
関東船釣り情報クローラー - 釣りビジョン版 (最終版)
ソース: https://www.fishing-v.jp/choka/choka_detail.php?s=船宿ID&pageID=1
構造確認済み: 日付(li)→テーブル(番号/魚種/匹数/サイズ...)
"""

import re, json, time
from datetime import datetime
from urllib.request import urlopen, Request
from urllib.error import URLError
from html.parser import HTMLParser

SHIPS = [
    {"area":"金沢八景","name":"鴨下丸","sid":175},
    {"area":"金沢八景","name":"蒲谷丸","sid":176},
    {"area":"金沢八景","name":"黒一丸","sid":177},
    {"area":"金沢八景","name":"修司丸","sid":178},
    {"area":"金沢八景","name":"健一丸","sid":179},
    {"area":"金沢八景","name":"青田丸","sid":180},
    {"area":"金沢八景","name":"蒲利丸","sid":181},
    {"area":"金沢八景","name":"木川丸","sid":182},
    {"area":"金沢八景","name":"仁丸","sid":183},
    {"area":"金沢八景","name":"進丸","sid":184},
    {"area":"金沢八景","name":"忠彦丸","sid":185},
    {"area":"金沢漁港","name":"久保弘丸","sid":759},
    {"area":"金沢漁港","name":"横内丸","sid":11403},
    {"area":"走水","name":"大正丸","sid":201},
    {"area":"久里浜","name":"大原丸","sid":202},
    {"area":"松輪","name":"瀬戸丸","sid":150},
    {"area":"久比里","name":"山下丸","sid":160},
    {"area":"葉山","name":"愛正丸","sid":170},
    {"area":"相模湾","name":"庄三郎丸","sid":100},
    {"area":"茅ヶ崎","name":"ちがさき丸","sid":101},
    {"area":"深川","name":"吉野屋","sid":300},
    {"area":"浦安","name":"吉久","sid":310},
    {"area":"外川","name":"孝進丸","sid":400},
    {"area":"大原","name":"義之丸","sid":410},
]

BASE_URL = "https://www.fishing-v.jp/choka/choka_detail.php?s={sid}&pageID=1"
USER_AGENT = "Mozilla/5.0 (compatible; FishingInfoBot/1.0)"
Z2H = str.maketrans("０１２３４５６７８９","0123456789")

FISH_MAP = {
    "アジ":["アジ","ライトアジ","LTアジ","ウィリー"],
    "タチウオ":["タチウオ"],"フグ":["フグ","トラフグ","ショウサイ"],
    "カワハギ":["カワハギ"],"マダイ":["マダイ","真鯛"],
    "シロギス":["シロギス","キス"],"イサキ":["イサキ"],
    "ヤリイカ":["ヤリイカ"],"スルメイカ":["スルメイカ"],
    "マダコ":["タコ","マダコ"],"カサゴ":["カサゴ"],"メバル":["メバル"],
    "ワラサ":["ワラサ","イナダ"],"アマダイ":["アマダイ"],
    "メダイ":["メダイ"],"サワラ":["サワラ"],"ヒラメ":["ヒラメ"],
    "マゴチ":["マゴチ"],"ホウボウ":["ホウボウ"],
}

def guess_fish(t):
    return [f for f,kws in FISH_MAP.items() if any(k in t for k in kws)] or [t[:8]]

def extract_count(t):
    t = t.translate(Z2H)
    m = re.search(r"(\d+)[〜～](\d+)\s*匹", t)
    if m: return {"min":int(m[1]),"max":int(m[2])}
    m = re.search(r"(\d+)\s*匹", t)
    if m: v=int(m[1]); return {"min":v,"max":v}
    return None

def extract_size(t):
    t = t.translate(Z2H)
    m = re.search(r"(\d+)[〜～](\d+)\s*cm", t, re.I)
    if m: return {"min":int(m[1]),"max":int(m[2])}
    m = re.search(r"(\d+)\s*cm", t, re.I)
    if m: v=int(m[1]); return {"min":v,"max":v}
    return None

class TextOnly(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts=[]; self._skip=False; self._tag=""
    def handle_starttag(self, tag, attrs):
        self._tag=tag.lower()
        if self._tag in ("script","style"): self._skip=True
        elif self._tag in ("tr","br","p","h3","li"): self.parts.append("\n")
        elif self._tag in ("td","th"): self.parts.append("\t")
    def handle_endtag(self, tag):
        if tag.lower() in ("script","style"): self._skip=False
    def handle_data(self, data):
        if not self._skip: self.parts.append(data)
    def text(self): return "".join(self.parts)

def parse(html, ship, area, year):
    tp = TextOnly(); tp.feed(html)
    lines = [l.strip() for l in tp.text().split('\n') if l.strip()]
    results = []
    current_date = None
    for line in lines:
        m = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日", line.translate(Z2H))
        if m:
            current_date = f"{m[1]}/{int(m[2]):02d}/{int(m[3]):02d}"; continue
        if '\t' in line and current_date:
            cells = [c.strip() for c in line.split('\t') if c.strip()]
            if len(cells) < 2: continue
            if cells[0].translate(Z2H).isdigit() and len(cells) > 2:
                fish_name, count_str = cells[1], cells[2]
                size_str = cells[3] if len(cells) > 3 else ""
            else:
                fish_name, count_str = cells[0], cells[1]
                size_str = cells[2] if len(cells) > 2 else ""
            skip_words = {"魚種","合計","備考","特記","ポイント","重さ","大きさ","匹数","　","施設","都道府県","電話番号","FAX","住所","定休日","料金","アクセス","乗船"}
            if fish_name in skip_words: continue
            if not fish_name or not re.search(r'\d', count_str.translate(Z2H)): continue
            results.append({
                "ship":ship,"area":area,"date":current_date,
                "catch_raw":f"{fish_name} {count_str} {size_str}".strip(),
                "fish":guess_fish(fish_name),
                "count_range":extract_count(count_str),
                "size_range":extract_size(size_str),
            })
    return results

def fetch(url):
    try:
        req = Request(url, headers={"User-Agent": USER_AGENT})
        with urlopen(req, timeout=20) as r:
            raw = r.read()
        for enc in ("utf-8","cp932","shift_jis","euc-jp"):
            try: return raw.decode(enc)
            except: pass
        return raw.decode("utf-8", errors="replace")
    except URLError as e:
        print(f"ERROR: {e}"); return None

def build_html(catches, crawled_at):
    fish_summary = {}
    for c in catches:
        for f in c["fish"]:
            fish_summary.setdefault(f,[]).append(c)
    cards = ""
    for fish, cs in sorted(fish_summary.items(), key=lambda x:-len(x[1])):
        areas = list(dict.fromkeys(c["area"] for c in cs[:3]))
        cards += (f'<div class="fc"><div class="fn">{fish}</div>'
                  f'<div class="fk">{len(cs)}件</div>'
                  f'<div class="fa">{" / ".join(areas)}</div></div>')
    rows = ""
    for c in sorted(catches, key=lambda x: x["date"] or "", reverse=True)[:80]:
        cnt = ""
        if c.get("count_range"):
            mn,mx=c["count_range"]["min"],c["count_range"]["max"]
            cnt=f"{mn}〜{mx}" if mn!=mx else str(mn)
        sz = ""
        if c.get("size_range"):
            mn,mx=c["size_range"]["min"],c["size_range"]["max"]
            sz=f"{mn}〜{mx}cm" if mn!=mx else f"{mn}cm"
        rows += (f"<tr><td>{c['date'] or '-'}</td><td>{c['area']}</td>"
                 f"<td>{c['ship']}</td><td>{'・'.join(c['fish'])}</td>"
                 f"<td>{cnt}</td><td>{sz}</td>"
                 f"<td style='color:#7a9bb5;font-size:11px'>{c['catch_raw'][:40]}</td></tr>")
    css = "*{box-sizing:border-box;margin:0;padding:0}body{font-family:'Helvetica Neue',Arial,sans-serif;background:#0a1628;color:#e0e8f0}header{background:#0d2137;padding:16px 24px;border-bottom:2px solid #1a6ea8}header h1{font-size:22px;color:#4db8ff}header p{font-size:12px;color:#7a9bb5;margin-top:4px}.wrap{max-width:1200px;margin:0 auto;padding:20px 16px}h2{font-size:15px;color:#4db8ff;border-left:4px solid #4db8ff;padding-left:10px;margin:24px 0 12px}.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(120px,1fr));gap:10px;margin-bottom:8px}.fc{background:#0d2137;border:1px solid #1a4060;border-radius:8px;padding:12px;text-align:center}.fc:hover{border-color:#4db8ff}.fn{font-size:16px;font-weight:bold;color:#fff}.fk{font-size:12px;color:#4db8ff;margin-top:4px}.fa{font-size:11px;color:#7a9bb5;margin-top:2px}.tw{overflow-x:auto}table{width:100%;border-collapse:collapse;font-size:12px}th{background:#0d2137;color:#4db8ff;padding:8px 6px;text-align:left;border-bottom:1px solid #1a4060;white-space:nowrap}td{padding:7px 6px;border-bottom:1px solid #0d2137;vertical-align:top}tr:hover td{background:#0d2137}.note{font-size:11px;color:#7a9bb5;text-align:right;margin-top:8px}"
    return f"""<!DOCTYPE html>
<html lang=\"ja\"><head><meta charset=\"UTF-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">
<title>関東船釣り釣果情報 | 今日何が釣れてる？</title><style>{css}</style></head>
<body><header><h1>🎣 関東船釣り釣果情報</h1>
<p>今日、何が釣れてる？ 関東エリアの船宿釣果をリアルタイム集計 ／ 毎日16:30自動更新</p></header>
<div class=\"wrap\"><h2>🐟 釣れている魚</h2><div class=\"grid\">{cards}</div>
<h2>📋 最新の釣果</h2><div class=\"tw\"><table>
<tr><th>日付</th><th>エリア</th><th>船宿</th><th>魚種</th><th>数量</th><th>サイズ</th><th>詳細</th></tr>
{rows}</table></div>
<p class=\"note\">最終更新: {crawled_at} ／ {len(catches)}件 ／ {len(SHIPS)}船宿</p>
</div></body></html>"""

def main():
    all_catches=[]; errors=[]; now=datetime.now()
    crawled_at=now.strftime("%Y/%m/%d %H:%M"); year=now.year
    print(f"=== 釣りビジョン クローラー 開始: {crawled_at} ===")
    for s in SHIPS:
        url=BASE_URL.format(sid=s["sid"])
        print(f"  [{s['area']}] {s['name']} (s={s['sid']}) ...", end=" ", flush=True)
        html=fetch(url)
        if not html: errors.append(s["name"]); continue
        catches=parse(html,s["name"],s["area"],year)
        print(f"{len(catches)} 件"); all_catches.extend(catches); time.sleep(1.0)
    with open("catches.json","w",encoding="utf-8") as f:
        json.dump({"crawled_at":crawled_at,"total":len(all_catches),"errors":errors,"data":all_catches},f,ensure_ascii=False,indent=2)
    with open("index.html","w",encoding="utf-8") as f:
        f.write(build_html(all_catches,crawled_at))
    print(f"=== 完了: {len(all_catches)}件 エラー:{errors or 'なし'} ===")

if __name__=="__main__":
    main()
