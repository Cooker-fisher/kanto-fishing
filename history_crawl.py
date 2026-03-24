#!/usr/bin/env python3
import re,json,time,os,sys
from datetime import datetime
from urllib.request import urlopen,Request
from urllib.error import URLError
from html.parser import HTMLParser
from concurrent.futures import ThreadPoolExecutor, as_completed

UA="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36"
Z2H=str.maketrans("０１２３４５６７８９","0123456789")
BASE="https://www.fishing-v.jp/choka/choka_detail.php?s={sid}&pageID={page}"
GYO_BASE="https://www.gyo.ne.jp/rep_tsuri_view%7CCID-{cid}.htm"
FISH_MAP={"アジ":["アジ","ライトアジ","LTアジ","午前ライト","午後ライト","ウィリー"],"タチウオ":["タチウオ","ショートタチウオ"],"フグ":["フグ","トラフグ","ショウサイ"],"カワハギ":["カワハギ"],"マダイ":["マダイ","真鯛"],"シロギス":["シロギス","キス"],"イサキ":["イサキ"],"ヤリイカ":["ヤリイカ"],"スルメイカ":["スルメイカ"],"マダコ":["タコ","マダコ"],"カサゴ":["カサゴ"],"ワラサ":["ワラサ","イナダ","ブリ"],"アマダイ":["アマダイ"],"ヒラメ":["ヒラメ"],"マゴチ":["マゴチ"],"五目":["五目"],"イシモチ":["イシモチ"],"サワラ":["サワラ"],"マルイカ":["マルイカ"],"マハタ":["マハタ"]}

def guess_fish(t):
    return [f for f,kws in FISH_MAP.items() if any(k in t for k in kws)] or [t[:10]]

def to_range(t,unit):
    t=t.translate(Z2H)
    is_boat=bool(re.search(r"船中|合計|全体",t))
    m=re.search(r"(\d+)\s*[~〜～]\s*(\d+)\s*"+unit,t)
    if m: return {"min":int(m[1]),"max":int(m[2]),"is_boat":is_boat}
    m=re.search(r"(\d+)\s*"+unit,t)
    if m: v=int(m[1]); return {"min":v,"max":v,"is_boat":is_boat}
    return None

class Parser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.records=[]; self._date=None
        self._in_li=False; self._in_td=False; self._skip=False
        self._row=[]; self._cell=""
    def handle_starttag(self,tag,attrs):
        d=dict(attrs)
        if tag in("script","style"): self._skip=True; return
        if tag=="li" and d.get("class")=="date": self._in_li=True; self._cell=""; return
        if tag=="tr": self._row=[]
        if tag in("td","th"): self._in_td=True; self._cell=""
    def handle_endtag(self,tag):
        if tag in("script","style"): self._skip=False; return
        if tag=="li" and self._in_li:
            self._in_li=False
            m=re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日",self._cell.translate(Z2H))
            if m: self._date=f"{m[1]}/{int(m[2]):02d}/{int(m[3]):02d}"
        if tag in("td","th") and self._in_td:
            self._in_td=False; self._row.append(self._cell.strip()); self._cell=""
        if tag=="tr" and self._date and len(self._row)>=3:
            r=self._row; f=r[0].translate(Z2H)
            if f.isdigit() and len(r)>=3: fish,cnt,sz=r[1],r[2],r[3] if len(r)>3 else ""
            else: fish,cnt,sz=r[0],r[1],r[2] if len(r)>2 else ""
            skip={"魚種","匹数","大きさ","重さ","特記","ポイント","備考",""}
            if fish not in skip and to_range(cnt,"匹"):
                self.records.append({"date":self._date,"fish":fish,"cnt":cnt,"sz":sz})
    def handle_data(self,data):
        if self._skip: return
        if self._in_li or self._in_td: self._cell+=data

def fetch(url):
    try:
        r=urlopen(Request(url,headers={"User-Agent":UA}),timeout=10)
        raw=r.read()
        for enc in("utf-8","cp932","shift_jis"):
            try: return raw.decode(enc)
            except: pass
        return raw.decode("utf-8",errors="replace")
    except: return None

def crawl_ship(ship):
    all_records=[]; page=1
    while True:
        html=fetch(BASE.format(sid=ship["sid"],page=page))
        if not html: break
        p=Parser(); p.feed(html)
        if not p.records: break
        for r in p.records:
            cr=to_range(r["cnt"],"匹"); sr=to_range(r["sz"],"cm")
            for fish in guess_fish(r["fish"]):
                all_records.append({"date":r["date"],"ship":ship["name"],"area":ship["area"],
                    "fish":fish,"max":cr["max"] if cr else 0,
                    "avg":(cr["min"]+cr["max"])//2 if cr else 0,
                    "is_boat":cr["is_boat"] if cr else False,
                    "size_max":sr["max"] if sr else 0})
        if "次</a>" not in html and ">次<" not in html: break
        page+=1; time.sleep(0.3)
    return all_records

def date_to_yearweek(ds):
    dt=datetime.strptime(ds,"%Y/%m/%d"); iso=dt.isocalendar()
    return f"{iso[0]}/W{iso[1]:02d}"

def build_and_save(all_records):
    weekly={}; monthly={}
    for r in all_records:
        if not r.get("date"): continue
        wk=date_to_yearweek(r["date"]); mo=r["date"][:7]; fish=r["fish"]
        for store,key in[(weekly,wk),(monthly,mo)]:
            if key not in store: store[key]={}
            if fish not in store[key]: store[key][fish]={"ships":0,"sum":0,"max":0,"cnt":0,"szs":[]}
            d=store[key][fish]; d["ships"]+=1
            if not r.get("is_boat"): d["sum"]+=r["avg"]; d["cnt"]+=1  # 船中数は平均に含めない
            if r["max"]>d["max"]: d["max"]=r["max"]
            if r["size_max"]>0: d["szs"].append(r["size_max"])
    for store in[weekly,monthly]:
        for period in store:
            for fish in store[period]:
                d=store[period][fish]
                d["avg"]=round(d["sum"]/d["cnt"],1) if d["cnt"]>0 else 0
                d["size_avg"]=round(sum(d["szs"])/len(d["szs"]),1) if d["szs"] else 0
                del d["sum"],d["cnt"],d["szs"]
    history={"weekly":weekly,"monthly":monthly}
    if os.path.exists("history.json"):
        try:
            ex=json.load(open("history.json",encoding="utf-8"))
            if "weekly" in ex: ex["weekly"].update(weekly); history["weekly"]=ex["weekly"]
            if "monthly" in ex: ex["monthly"].update(monthly); history["monthly"]=ex["monthly"]
        except: pass
    json.dump(history,open("history.json","w",encoding="utf-8"),ensure_ascii=False,indent=2)
    return history

def crawl_gyo_ship(ship):
    """gyo.ne.jp の1船宿分の釣果を全日付で取得してhistory形式に変換する"""
    sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
    from crawler import fetch_gyo, parse_catches_gyo
    now=datetime.now(); cutoff_year=now.year-2
    cid=ship["cid"]

    def _to_records(catches):
        out=[]
        for c in catches:
            if not c.get("date"): continue
            cr=c.get("count_range") or {}; sr=c.get("size_range") or {}
            avg=(cr.get("min",0)+cr.get("max",0))//2 if cr else 0
            mx=cr.get("max",0); sz=sr.get("max",0) if sr else 0
            for fish in c.get("fish",[]):
                out.append({"date":c["date"],"ship":ship["name"],"area":ship["area"],
                            "fish":fish,"max":mx,"avg":avg,"size_max":sz})
        return out

    # 最新ページ取得
    html=fetch_gyo(GYO_BASE.format(cid=cid))
    if not html: return []
    all_records=_to_records(parse_catches_gyo(html,ship["name"],ship["area"],now.year))

    # 過去日付リンクを抽出（/rep_tsuri_history_view|CID-...|hdt-YYYY/MM/DD|dt-....htm）
    hist_links=re.findall(r'href="(/rep_tsuri_history_view\|CID-[^"]+\.htm)"',html)
    for href in hist_links:
        m=re.search(r'hdt-(\d{4})',href)
        if not m or int(m.group(1))<cutoff_year: continue
        hist_year=int(m.group(1))
        url="https://www.gyo.ne.jp"+href.replace("|","%7C")
        hist_html=fetch_gyo(url)
        if hist_html:
            all_records.extend(_to_records(parse_catches_gyo(hist_html,ship["name"],ship["area"],hist_year)))
        time.sleep(0.3)
    return all_records

def main():
    sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
    from crawler import SHIPS
    gyo_json=os.path.join(os.path.dirname(os.path.abspath(__file__)),"gyo_ships.json")
    gyo_ships=[]
    if os.path.exists(gyo_json):
        with open(gyo_json,encoding="utf-8") as f: gyo_ships=json.load(f)
    total=len(SHIPS)+len(gyo_ships)
    print(f"=== 過去データ並列取得開始 / fishing-v.jp:{len(SHIPS)} + gyo:{len(gyo_ships)} = {total}船宿 ===")
    print(f"開始: {datetime.now().strftime('%H:%M:%S')} / 並列数:5")
    all_records=[]; done=0
    with ThreadPoolExecutor(max_workers=5) as ex:
        futures={}
        for ship in SHIPS: futures[ex.submit(crawl_ship,ship)]=ship
        for ship in gyo_ships: futures[ex.submit(crawl_gyo_ship,ship)]=ship
        for f in as_completed(futures):
            ship=futures[f]; done+=1
            try:
                recs=f.result(); all_records.extend(recs)
                print(f"[{done:03d}/{total}] {ship['area']} {ship['name']} {len(recs)}件")
            except Exception as e:
                print(f"[{done:03d}/{total}] {ship['name']} ERROR:{e}")
            if done%20==0:
                print(f">>> 中間保存... ({len(all_records)}件)")
                build_and_save(all_records)
    h=build_and_save(all_records)
    wks=sorted(h["weekly"].keys()); mos=sorted(h["monthly"].keys())
    print(f"=== 完了！週次:{len(wks)}週 ({wks[0]}〜{wks[-1]}) ===")
    print(f"終了: {datetime.now().strftime('%H:%M:%S')}")

if __name__=="__main__":
    main()
