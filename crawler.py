#!/usr/bin/env python3
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
    {"area":"茅ヶ崎","name":"ちがさき丸","sid":101},
    {"area":"深川","name":"吉野屋","sid":300},
    {"area":"浦安","name":"吉久","sid":310},
    {"area":"外川","name":"孝進丸","sid":400},
    {"area":"大原","name":"義之丸","sid":410},
]

BASE = "https://www.fishing-v.jp/choka/choka_detail.php?s={sid}&pageID=1"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36"
Z2H = str.maketrans("０１２３４５６７８９", "0123456789")

FISH_MAP = {
    "アジ":["アジ","ライトアジ","LTアジ","午前ライト","午後ライト","ウィリー"],
    "タチウオ":["タチウオ","ショートタチウオ"],
    "フグ":["フグ","トラフグ","ショウサイ"],
    "カワハギ":["カワハギ"],"マダイ":["マダイ","真鯛"],
    "シロギス":["シロギス","キス"],"イサキ":["イサキ"],
    "ヤリイカ":["ヤリイカ"],"スルメイカ":["スルメイカ"],
    "マダコ":["タコ","マダコ"],"カサゴ":["カサゴ"],"メバル":["メバル"],
    "ワラサ":["ワラサ","イナダ","ブリ"],"アマダイ":["アマダイ"],
    "ヒラメ":["ヒラメ"],"マゴチ":["マゴチ"],"五目":["五目"],
}

def guess_fish(t):
    return [f for f,kws in FISH_MAP.items() if any(k in t for k in kws)] or [t[:10]]

def to_range(t, unit):
    t = t.translate(Z2H)
    m = re.search(r"(\d+)\s*[~〜～]\s*(\d+)\s*" + unit, t)
    if m: return {"min":int(m[1]),"max":int(m[2])}
    m = re.search(r"(\d+)\s*" + unit, t)
    if m: v=int(m[1]); return {"min":v,"max":v}
    return None

class Parser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.records=[]; self._date=None
        self._in_li=False; self._in_td=False; self._skip=False
        self._row=[]; self._cell=""

    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        if tag in ("script","style"): self._skip=True; return
        if tag=="li" and d.get("class")=="date": self._in_li=True; self._cell=""; return
        if tag=="tr": self._row=[]
        if tag in ("td","th"): self._in_td=True; self._cell=""

    def handle_endtag(self, tag):
        if tag in ("script","style"): self._skip=False; return
        if tag=="li" and self._in_li:
            self._in_li=False
            m = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日", self._cell.translate(Z2H))
            if m: self._date=f"{m[1]}/{int(m[2]):02d}/{int(m[3]):02d}"
        if tag in ("td","th") and self._in_td:
            self._in_td=False; self._row.append(self._cell.strip()); self._cell=""
        if tag=="tr" and self._date and len(self._row)>=3:
            r=self._row; f=r[0].translate(Z2H)
            if f.isdigit() and len(r)>=3: fish,cnt,sz=r[1],r[2],r[3] if len(r)>3 else ""
            else: fish,cnt,sz=r[0],r[1],r[2] if len(r)>2 else ""
            skip={"魚種","匹数","大きさ","重さ","特記","ポイント","備考",""}
            if fish not in skip and to_range(cnt,"匹"):
                self.records.append({"date":self._date,"fish":fish,"cnt":cnt,"sz":sz})

    def handle_data(self, data):
        if self._skip: return
        if self._in_li or self._in_td: self._cell += data

def fetch(url):
    try:
        r = urlopen(Request(url, headers={"User-Agent":UA}), timeout=20)
        raw = r.read()
        for enc in ("utf-8","cp932","shift_jis"):
            try: return raw.decode(enc)
            except: pass
        return raw.decode("utf-8",errors="replace")
    except URLError as e:
        print(f"  ERROR:{e}"); return None

def crawl(ship):
    html = fetch(BASE.format(sid=ship["sid"]))
    if not html: return None
    p = Parser(); p.feed(html)
    return [{"ship":ship["name"],"area":ship["area"],"date":r["date"],
             "fish":guess_fish(r["fish"]),
             "count_range":to_range(r["cnt"],"匹"),
             "size_range":to_range(r["sz"],"cm"),
             "catch_raw":f"{r['fish']} {r['cnt']} {r['sz']}".strip()}
            for r in p.records]

def build_html(data, ts, n):
    fs={}
    for c in data:
        for f in c["fish"]: fs.setdefault(f,[]).append(c)
    cards="".join(f'<div class="fc"><div class="fn">{f}</div><div class="fk">{len(cs)}件</div><div class="fa">{"/".join(list(dict.fromkeys(c["area"] for c in cs[:3])))}</div></div>'
                  for f,cs in sorted(fs.items(),key=lambda x:-len(x[1])))
    def rng(r,u): return f'{r["min"]}~{r["max"]}{u}' if r and r["min"]!=r["max"] else (f'{r["min"]}{u}' if r else "")
    rows="".join(f"<tr><td>{c['date']}</td><td>{c['area']}</td><td>{c['ship']}</td><td>{'・'.join(c['fish'])}</td><td>{rng(c.get('count_range'),'')}</td><td>{rng(c.get('size_range'),'cm')}</td></tr>"
                 for c in sorted(data,key=lambda x:x["date"],reverse=True)[:100])
    css="*{box-sizing:border-box;margin:0;padding:0}body{font-family:sans-serif;background:#0a1628;color:#e0e8f0}header{background:#0d2137;padding:16px 24px;border-bottom:2px solid #1a6ea8}h1{font-size:22px;color:#4db8ff}header p{font-size:12px;color:#7a9bb5;margin-top:4px}.w{max-width:1200px;margin:0 auto;padding:20px 16px}h2{font-size:15px;color:#4db8ff;border-left:4px solid #4db8ff;padding-left:10px;margin:24px 0 12px}.g{display:grid;grid-template-columns:repeat(auto-fill,minmax(110px,1fr));gap:8px}.fc{background:#0d2137;border:1px solid #1a4060;border-radius:8px;padding:10px;text-align:center}.fn{font-size:15px;font-weight:bold}.fk{font-size:12px;color:#4db8ff}.fa{font-size:11px;color:#7a9bb5}.tw{overflow-x:auto}table{width:100%;border-collapse:collapse;font-size:12px}th{background:#0d2137;color:#4db8ff;padding:8px 6px;text-align:left;border-bottom:1px solid #1a4060}td{padding:6px;border-bottom:1px solid #0d2137}tr:hover td{background:#0d2137}.note{font-size:11px;color:#7a9bb5;text-align:right;margin-top:8px}"
    return f'<!DOCTYPE html><html lang="ja"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>関東船釣り釣果情報</title><style>{css}</style></head><body><header><h1>🎣 関東船釣り釣果情報</h1><p>今日何が釣れてる？関東エリアの船宿釣果 毎日16:30自動更新</p></header><div class="w"><h2>🐟 釣れている魚</h2><div class="g">{cards}</div><h2>📋 最新釣果</h2><div class="tw"><table><tr><th>日付</th><th>エリア</th><th>船宿</th><th>魚種</th><th>数量</th><th>サイズ</th></tr>{rows}</table></div><p class="note">更新:{ts} / {len(data)}件 / {n}船宿</p></div></body></html>'

def main():
    all,errs=[],[]
    ts=datetime.now().strftime("%Y/%m/%d %H:%M")
    print(f"=== 開始:{ts} ===")
    for s in SHIPS:
        print(f"  [{s['area']}]{s['name']}(s={s['sid']})...",end=" ",flush=True)
        r=crawl(s)
        if r is None: errs.append(s["name"]); print("ERROR")
        else: print(f"{len(r)}件"); all.extend(r)
        time.sleep(1)
    json.dump({"crawled_at":ts,"total":len(all),"errors":errs,"data":all},
              open("catches.json","w",encoding="utf-8"),ensure_ascii=False,indent=2)
    open("index.html","w",encoding="utf-8").write(build_html(all,ts,len(SHIPS)))
    print(f"=== 完了:{len(all)}件 エラー:{errs or 'なし'} ===")

if __name__=="__main__":
    main()
