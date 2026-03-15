#!/usr/bin/env python3
import re, json, time
from datetime import datetime
from urllib.request import urlopen, Request
from urllib.error import URLError
from html.parser import HTMLParser

SHIPS = [
    # 金沢漁港・金沢八景
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
    {"area":"金沢八景","name":"一之瀬丸","sid":186},
    {"area":"金沢八景","name":"新修丸","sid":187},
    {"area":"金沢八景","name":"米元釣船店","sid":188},
    {"area":"金沢八景","name":"荒川屋","sid":189},
    {"area":"金沢八景","name":"弁天屋","sid":190},
    {"area":"金沢八景","name":"太田屋","sid":191},
    {"area":"金沢八景","name":"野毛屋釣船店","sid":192},
    {"area":"金沢八景","name":"黒川丸","sid":260},
    {"area":"金沢八景","name":"小柴丸","sid":1750},
    {"area":"金沢八景","name":"新健丸","sid":11301},
    {"area":"金沢漁港","name":"久保弘丸","sid":759},
    {"area":"金沢漁港","name":"横内丸","sid":11403},
    # 横浜港・本牧
    {"area":"横浜本牧","name":"長崎屋","sid":256},
    {"area":"横浜港","name":"渡辺釣船店","sid":172},
    {"area":"横浜港","name":"黒川本家","sid":173},
    {"area":"横浜港","name":"アイランドクルーズ","sid":10055},
    {"area":"横浜港","name":"打木屋釣船店","sid":11294},
    # 走水
    {"area":"走水","name":"吉明丸","sid":197},
    {"area":"走水","name":"健洋丸","sid":198},
    {"area":"走水","name":"高司丸","sid":199},
    {"area":"走水","name":"海福丸","sid":200},
    # 久里浜
    {"area":"久里浜","name":"ムツ六釣船店","sid":212},
    {"area":"久里浜","name":"久里浜黒川本家","sid":213},
    # 久比里
    {"area":"久比里","name":"山下丸","sid":209},
    {"area":"久比里","name":"巳之助丸","sid":210},
    {"area":"久比里","name":"山天丸","sid":211},
    # 松輪
    {"area":"松輪","name":"喜平治丸","sid":215},
    {"area":"松輪","name":"一義丸","sid":216},
    {"area":"松輪","name":"成銀丸","sid":217},
    # 長井
    {"area":"長井","name":"はら丸","sid":218},
    {"area":"長井","name":"栃木丸","sid":219},
    {"area":"長井","name":"徳丸","sid":220},
    {"area":"長井","name":"儀兵衛丸","sid":221},
    {"area":"長井","name":"丸伊丸","sid":223},
    {"area":"長井","name":"春盛丸","sid":204},
    {"area":"長井","name":"光三丸","sid":205},
    {"area":"長井","name":"長助丸","sid":207},
    {"area":"長井","name":"青木丸","sid":208},
    # 葉山
    {"area":"葉山","name":"たいぞう丸","sid":229},
    {"area":"葉山","name":"与兵衛丸","sid":231},
    {"area":"葉山","name":"愛正丸","sid":232},
    {"area":"葉山","name":"まさみ丸","sid":233},
    # 茅ヶ崎
    {"area":"茅ヶ崎","name":"まごうの丸","sid":240},
    {"area":"茅ヶ崎","name":"沖右ヱ門丸","sid":241},
    # 平塚
    {"area":"平塚","name":"庄三郎丸","sid":244},
    # 東京・深川
    {"area":"深川","name":"吉野屋","sid":161},
    {"area":"深川","name":"冨士見","sid":11201},
    {"area":"深川","name":"船宿さわ浦","sid":12074},
    # 東京・羽田
    {"area":"羽田","name":"かみや","sid":164},
    {"area":"羽田","name":"かめだや","sid":165},
    {"area":"羽田","name":"えさ政釣船店","sid":166},
    # 千葉・浦安
    {"area":"浦安","name":"吉久","sid":147},
    {"area":"浦安","name":"岩田屋本店","sid":1691},
    # 茨城・鹿島
    {"area":"鹿島","name":"幸栄丸","sid":496},
    # 千葉・外川港
    {"area":"外川","name":"三浦丸","sid":41},
    {"area":"外川","name":"家田丸","sid":43},
    {"area":"外川","name":"長治丸","sid":44},
    {"area":"外川","name":"光佑丸","sid":45},
    {"area":"外川","name":"大盛丸","sid":46},
    # 千葉・飯岡港
    {"area":"飯岡","name":"幸丸","sid":48},
    {"area":"飯岡","name":"優光丸","sid":50},
    {"area":"飯岡","name":"長五郎丸","sid":51},
    {"area":"飯岡","name":"梅花丸","sid":52},
    {"area":"飯岡","name":"三次郎丸","sid":54},
    {"area":"飯岡","name":"潮丸","sid":55},
    # 千葉・片貝港
    {"area":"片貝","name":"二三丸","sid":57},
    {"area":"片貝","name":"勇幸丸","sid":58},
    {"area":"片貝","name":"第二新亀丸","sid":59},
    # 千葉・大原港
    {"area":"大原","name":"力漁丸","sid":61},
    {"area":"大原","name":"利永丸","sid":62},
    {"area":"大原","name":"第三松栄丸","sid":63},
    {"area":"大原","name":"利東丸","sid":65},
    {"area":"大原","name":"敷嶋丸","sid":66},
    {"area":"大原","name":"鈴栄丸","sid":67},
    {"area":"大原","name":"松鶴丸","sid":68},
    {"area":"大原","name":"拓永丸","sid":69},
    {"area":"大原","name":"若栄丸","sid":70},
    {"area":"大原","name":"つる丸","sid":71},
    {"area":"大原","name":"初栄丸","sid":72},
    # 千葉・御宿
    {"area":"御宿","name":"太平丸","sid":73},
    {"area":"御宿","name":"長栄丸","sid":74},
    {"area":"御宿","name":"義丸","sid":75},
    {"area":"御宿","name":"明広丸","sid":76},
    {"area":"御宿","name":"明栄丸","sid":10058},
    # 千葉・勝浦
    {"area":"勝浦","name":"新勝丸","sid":78},
    {"area":"勝浦","name":"良幸丸","sid":79},
    {"area":"勝浦","name":"基吉丸","sid":82},
    {"area":"勝浦","name":"宏昌丸","sid":83},
    {"area":"勝浦","name":"釣丸","sid":86},
    {"area":"勝浦","name":"盛幸丸","sid":88},
    # 千葉・勝山港
    {"area":"勝山","name":"萬栄丸","sid":740},
    {"area":"勝山","name":"庄幸丸","sid":118},
    {"area":"勝山","name":"宝生丸","sid":120},
    {"area":"勝山","name":"新盛丸","sid":121},
    {"area":"勝山","name":"利八丸","sid":1270},
    # 千葉・保田港
    {"area":"保田","name":"弥生丸","sid":122},
    {"area":"保田","name":"村井丸","sid":123},
    {"area":"保田","name":"国丸","sid":125},
    # 千葉・金谷港
    {"area":"金谷","name":"共栄丸","sid":126},
    {"area":"金谷","name":"光進丸","sid":127},
    {"area":"金谷","name":"吉三郎丸","sid":130},
    # 千葉・富津港
    {"area":"富津","name":"鹿島丸","sid":138},
    {"area":"富津","name":"寿々春丸","sid":139},
    {"area":"富津","name":"浜新丸","sid":140},
    {"area":"富津","name":"川崎丸","sid":141},
    # 千葉・浦安
    {"area":"浦安","name":"吉野屋","sid":146},
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
    "イシモチ":["イシモチ"],"サワラ":["サワラ"],
    "アカムツ":["アカムツ","ノドグロ"],"キンメ":["キンメ"],
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
    import json as _json
    from datetime import datetime, timedelta
    fs = {}
    for c in data:
        for f in c["fish"]:
            fs.setdefault(f, []).append(c)

    cards = ""
    for f, cs in sorted(fs.items(), key=lambda x: -len(x[1])):
        areas = list(dict.fromkeys(c["area"] for c in cs[:3]))
        recent = sum(1 for c in cs if c.get("date") and c["date"] >= (datetime.now()-timedelta(days=7)).strftime("%Y/%m/%d"))
        badge = f'<span class="nb">{recent}件/週</span>' if recent > 0 else ""
        cards += f'<div class="fc" onclick="showRank(\'{f}\')" title="{f}のランキング"><div class="fn">{f}</div><div class="fk">{len(cs)}件 {badge}</div><div class="fa">{"/".join(areas)}</div></div>'

    def rng(r, u): return f'{r["min"]}~{r["max"]}{u}' if r and r["min"] != r["max"] else (f'{r["min"]}{u}' if r else "")

    rows = "".join(
        f"<tr><td>{c['date']}</td><td>{c['area']}</td><td>{c['ship']}</td>"
        f"<td>{'・'.join(c['fish'])}</td><td>{rng(c.get('count_range'),'')}</td>"
        f"<td>{rng(c.get('size_range'),'cm')}</td></tr>"
        for c in sorted(data, key=lambda x: x["date"], reverse=True)[:200]
    )

    rank_data = {}
    for f, cs in fs.items():
        ships = {}
        for c in cs:
            key = c["ship"]
            mx = (c.get("count_range") or {}).get("max", 0)
            if key not in ships or ships[key]["max"] < mx:
                ships[key] = {"ship": c["ship"], "area": c["area"], "max": mx, "date": c.get("date", "")}
        rank_data[f] = sorted(ships.values(), key=lambda x: -x["max"])[:10]

    rank_json = _json.dumps(rank_data, ensure_ascii=False)

    css = ("*{box-sizing:border-box;margin:0;padding:0}"
           "body{font-family:sans-serif;background:#0a1628;color:#e0e8f0}"
           "header{background:#0d2137;padding:16px 24px;border-bottom:2px solid #1a6ea8}"
           "h1{font-size:22px;color:#4db8ff}header p{font-size:12px;color:#7a9bb5;margin-top:4px}"
           ".w{max-width:1200px;margin:0 auto;padding:20px 16px}"
           "h2{font-size:15px;color:#4db8ff;border-left:4px solid #4db8ff;padding-left:10px;margin:24px 0 12px}"
           ".g{display:grid;grid-template-columns:repeat(auto-fill,minmax(110px,1fr));gap:8px}"
           ".fc{background:#0d2137;border:1px solid #1a4060;border-radius:8px;padding:10px;text-align:center;cursor:pointer;transition:border-color .2s,transform .15s}"
           ".fc:hover{border-color:#4db8ff;transform:translateY(-2px)}"
           ".fn{font-size:15px;font-weight:bold}.fk{font-size:12px;color:#4db8ff;margin-top:3px}"
           ".fa{font-size:11px;color:#7a9bb5;margin-top:2px}"
           ".nb{background:#1a4060;border-radius:4px;padding:1px 5px;font-size:10px;color:#7dd3fc}"
           ".tw{overflow-x:auto}table{width:100%;border-collapse:collapse;font-size:12px}"
           "th{background:#0d2137;color:#4db8ff;padding:8px 6px;text-align:left;border-bottom:1px solid #1a4060}"
           "td{padding:7px 6px;border-bottom:1px solid #0d2137}tr:hover td{background:#0d2137}"
           ".note{font-size:11px;color:#7a9bb5;text-align:right;margin-top:8px}"
           ".overlay{display:none;position:fixed;inset:0;background:rgba(0,0,0,.75);z-index:100;align-items:center;justify-content:center}"
           ".overlay.open{display:flex}"
           ".modal{background:#0d2137;border:1px solid #1a6ea8;border-radius:12px;padding:24px;width:92%;max-width:520px;max-height:85vh;overflow-y:auto;position:relative}"
           ".modal h3{font-size:18px;color:#4db8ff;margin-bottom:4px}"
           ".modal-sub{font-size:12px;color:#7a9bb5;margin-bottom:16px}"
           ".close-btn{position:absolute;top:12px;right:16px;background:none;border:none;color:#7a9bb5;font-size:22px;cursor:pointer;line-height:1}"
           ".close-btn:hover{color:#fff}"
           ".rrow{display:flex;align-items:center;gap:12px;padding:11px 0;border-bottom:1px solid #0a1628}"
           ".rrow:last-child{border-bottom:none}"
           ".rnum{font-size:20px;font-weight:bold;color:#334155;width:32px;text-align:center;flex-shrink:0}"
           ".rnum.g1{color:#f59e0b}.rnum.g2{color:#94a3b8}.rnum.g3{color:#b45309}"
           ".rinfo{flex:1;min-width:0}.rship{font-size:15px;font-weight:bold;color:#fff}"
           ".rarea{font-size:11px;color:#7a9bb5;margin-top:2px}"
           ".rbar-wrap{width:110px;flex-shrink:0;text-align:right}"
           ".rcnt{font-size:16px;font-weight:bold;color:#4db8ff}"
           ".runit{font-size:11px;color:#7a9bb5}"
           ".rbar-bg{background:#0a1628;border-radius:4px;height:5px;margin-top:5px}"
           ".rbar{height:5px;background:linear-gradient(90deg,#1a6ea8,#4db8ff);border-radius:4px}")

    js = f"""const RANK={rank_json};
const MEDALS=['g1','g2','g3'];
function showRank(fish){{
  const rows=RANK[fish]||[];
  const max=rows[0]?rows[0].max:1;
  let html='';
  rows.forEach(function(r,i){{
    const pct=max>0?Math.round(r.max/max*100):0;
    const mc=MEDALS[i]||'';
    html+='<div class="rrow"><div class="rnum '+mc+'">'+(i+1)+'</div>'
      +'<div class="rinfo"><div class="rship">'+r.ship+'</div>'
      +'<div class="rarea">'+r.area+' · '+r.date+'</div></div>'
      +'<div class="rbar-wrap"><div class="rcnt">'+r.max+'<span class="runit"> 匹</span></div>'
      +'<div class="rbar-bg"><div class="rbar" style="width:'+pct+'%"></div></div>'
      +'</div></div>';
  }});
  document.getElementById('rank-title').textContent=fish+' 釣果ランキング TOP'+rows.length;
  document.getElementById('rank-sub').textContent='船宿別の最高釣果（直近データ）';
  document.getElementById('rank-body').innerHTML=html||'<p style="color:#7a9bb5;padding:16px 0">データがありません</p>';
  document.getElementById('overlay').classList.add('open');
}}
function closeModal(){{document.getElementById('overlay').classList.remove('open');}}
document.addEventListener('keydown',function(e){{if(e.key==='Escape')closeModal();}});"""

    return (f'<!DOCTYPE html><html lang="ja"><head><meta charset="UTF-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>関東船釣り釣果情報 | 今日何が釣れてる？</title>'
            f'<style>{css}</style></head><body>'
            f'<header><h1>🎣 関東船釣り釣果情報</h1>'
            f'<p>今日何が釣れてる？関東エリアの船宿釣果 毎日16:30自動更新 · 魚種をタップでランキング</p></header>'
            f'<div class="w">'
            f'<h2>🐟 釣れている魚 <span style="font-size:11px;font-weight:normal;color:#7a9bb5">↓ タップでランキング表示</span></h2>'
            f'<div class="g">{cards}</div>'
            f'<h2>📋 最新釣果</h2>'
            f'<div class="tw"><table>'
            f'<tr><th>日付</th><th>エリア</th><th>船宿</th><th>魚種</th><th>数量</th><th>サイズ</th></tr>'
            f'{rows}</table></div>'
            f'<p class="note">最終更新: {ts} · {len(data)}件 · {n}船宿</p>'
            f'</div>'
            f'<div class="overlay" id="overlay" onclick="if(event.target===this)closeModal()">'
            f'<div class="modal"><button class="close-btn" onclick="closeModal()">×</button>'
            f'<h3 id="rank-title"></h3><div class="modal-sub" id="rank-sub"></div>'
            f'<div id="rank-body"></div></div></div>'
            f'<script>{js}</script></body></html>')


def main():
    all,errs=[],[]
    ts=datetime.now().strftime("%Y/%m/%d %H:%M")
    print(f"=== 開始:{ts} / {len(SHIPS)}船宿 ===")
    for s in SHIPS:
        print(f"  [{s['area']}]{s['name']}(s={s['sid']})...",end=" ",flush=True)
        r=crawl(s)
        if r is None: errs.append(s["name"]); print("ERROR")
        else: print(f"{len(r)}件"); all.extend(r)
        time.sleep(0.8)
    json.dump({"crawled_at":ts,"total":len(all),"errors":errs,"data":all},
              open("catches.json","w",encoding="utf-8"),ensure_ascii=False,indent=2)
    open("index.html","w",encoding="utf-8").write(build_html(all,ts,len(SHIPS)))
    print(f"=== 完了:{len(all)}件 エラー:{errs or 'なし'} ===")

if __name__=="__main__":
    main()
