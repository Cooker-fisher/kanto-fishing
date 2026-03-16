#!/usr/bin/env python3
import re, json, time, os
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

FISH_MASTER = {
  "アジ":      {"season":[1,2,3,4,5,6,7,8,9,10,11,12],"peak_num":[6,7,8,9],"peak_size":[10,11,12],"axis":"数◎","comment":"東京湾の王様。通年釣れるが夏は数釣り、秋冬は金アジで脂乗り最高"},
  "マダイ":    {"season":[4,5,6,9,10,11],"peak_num":[5,6],"peak_size":[4,5,10,11],"axis":"型◎","comment":"春の乗っ込みと秋の荒食い。4〜6月は大型の数釣りも期待できる"},
  "ヒラメ":    {"season":[9,10,11,12,1,2],"peak_num":[7,8],"peak_size":[11,12,1],"axis":"型◎","comment":"冬が旬で座布団級も。秋口から数が出始め、冬は食味も最高"},
  "タチウオ":  {"season":[7,8,9,10,11],"peak_num":[8,9],"peak_size":[11,12,1],"axis":"数＆型","comment":"夏は浅場で数爆釣、晩秋〜冬は深場でドラゴン級の型狙い"},
  "シロギス":  {"season":[5,6,7,8,9,10],"peak_num":[7,8],"peak_size":[9,10],"axis":"数◎","comment":"夏は数釣り天国。秋の落ちギスは良型揃い。入門魚の定番"},
  "カワハギ":  {"season":[9,10,11,12],"peak_num":[10,11],"peak_size":[11,12],"axis":"肝◎","comment":"秋〜冬が本番。肝がパンパンの12月前後が最高。久比里がメッカ"},
  "イサキ":    {"season":[6,7,8],"peak_num":[6,7],"peak_size":[6],"axis":"数◎","comment":"梅雨イサキが最高。脂乗りと数釣りが同時に楽しめる夏の風物詩"},
  "ヤリイカ":  {"season":[12,1,2,3],"peak_num":[1,2],"peak_size":[1,2],"axis":"数◎","comment":"真冬が最盛期。パラソル級の大型も。3月で終盤を迎える"},
  "マルイカ":  {"season":[5,6,7],"peak_num":[6],"peak_size":[6,7],"axis":"数◎","comment":"初夏の短期集中シーズン。6月が最盛期で数釣りが楽しめる"},
  "スルメイカ":{"season":[7,8,9],"peak_num":[7,8],"peak_size":[8],"axis":"数◎","comment":"夏の夜焚き釣りで爆釣も。秋に南下して終了"},
  "アマダイ":  {"season":[11,12,1,2],"peak_num":[12,1],"peak_size":[12,1],"axis":"型◎","comment":"冬の高級魚。数より型狙い。大型は60cm超えも。干物も絶品"},
  "フグ":      {"season":[3,4,5,6,7],"peak_num":[5,6],"peak_size":[4,5],"axis":"数◎","comment":"春の白子入りが特に人気。5〜6月は白子たっぷりの旬の時期"},
  "カサゴ":    {"season":[2,3,4,5,6,7,8,9,10,11],"peak_num":[4,5,6],"peak_size":[2,3],"axis":"数◎","comment":"通年釣れる根魚の定番。冬は自主規制の船宿も。春が最盛期"},
  "サワラ":    {"season":[10,11,12],"peak_num":[11],"peak_size":[11,12],"axis":"型◎","comment":"秋の一発大物。ルアー系で人気急上昇中。70cm超えザラ"},
  "マハタ":    {"season":[3,4,5,6,7,8,9],"peak_num":[7,8],"peak_size":[9,10],"axis":"型◎","comment":"高級根魚。春から夏が狙い目。型はキロオーバーが基準"},
  "イシモチ":  {"season":[4,5,6,7,8],"peak_num":[4,5,6],"peak_size":[5,6],"axis":"数◎","comment":"東京湾の春の定番。数が出やすく入門にも最適"},
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

def build_target_section(targets):
    """狙い目セクションのHTMLを生成"""
    from datetime import datetime
    now = datetime.now()
    week_label = f"{now.month}月第{(now.day-1)//7+1}週"
    stars = ["★★★★★","★★★★☆","★★★☆☆","★★☆☆☆","★☆☆☆☆"]
    medals = ["🥇","🥈","🥉","4","5"]
    rows = ""
    for i, t in enumerate(targets):
        star = stars[i] if i < len(stars) else "★☆☆☆☆"
        medal = medals[i] if i < len(medals) else str(i+1)
        rows += (f'<div class="tr-row">'
                 f'<span class="tr-medal">{medal}</span>'
                 f'<span class="tr-star">{star}</span>'
                 f'<span class="tr-fish">{t["fish"]}</span>'
                 f'<span class="tr-comment">{t["comment"]}</span>'
                 f'<span class="tr-hot">直近{t["hot"]}件</span>'
                 f'</div>')
    return (f'<div class="target-section">'
            f'<div class="target-header">'
            f'<span class="target-title">🎯 今週末の狙い目</span>'
            f'<span class="target-week">{week_label} · 過去データ×直近釣果から算出</span>'
            f'</div>'
            f'{rows}'
            f'</div>')

def calc_targets(data):
    """今週末の狙い目を計算して返す"""
    from datetime import datetime, timedelta
    import json as _j
    now = datetime.now()
    this_m = now.month - 1  # 0-indexed
    next_m = (this_m + 1) % 12
    prev_m = (this_m - 1) % 12
    week_ago = (now - timedelta(days=7)).strftime("%Y/%m/%d")

    month_fish = {}
    recent7 = {}
    for c in data:
        if not c.get("date"): continue
        m = int(c["date"].split("/")[1]) - 1
        for f in c["fish"]:
            if f not in month_fish: month_fish[f] = [0]*12
            month_fish[f][m] += 1
        if c["date"] >= week_ago:
            for f in c["fish"]: recent7[f] = recent7.get(f,0)+1

    targets = []
    for fish, counts in month_fish.items():
        this_mon = counts[this_m]
        next_mon = counts[next_m]
        prev_mon = counts[prev_m]
        hot = recent7.get(fish, 0)
        trend = round(this_mon/prev_mon, 1) if prev_mon > 0 else (2.0 if this_mon > 0 else 0)
        score = this_mon*2 + next_mon*1.5 + hot*3 + trend*5
        if score <= 0: continue
        # コメント生成
        if trend >= 10:
            comment = f"急上昇中！先月比{trend}倍"
        elif next_mon > this_mon:
            comment = "これから本格シーズン入り"
        elif trend >= 3 and hot > 5:
            comment = "今まさに乗り頃"
        elif hot >= 10:
            comment = "安定して好調"
        elif trend < 1:
            comment = "そろそろ終盤"
        else:
            comment = f"今月{this_mon}件の実績"
        targets.append({"fish":fish,"score":score,"hot":hot,"trend":trend,"comment":comment})

    targets.sort(key=lambda x: -x["score"])
    return targets[:5]

def build_fish_pages(data):
    """魚種別の個別HTMLページを fish/ ディレクトリに生成する"""
    from datetime import datetime, timedelta
    os.makedirs("fish", exist_ok=True)
    now = datetime.now()
    week_ago  = (now - timedelta(days=7)).strftime("%Y/%m/%d")
    month_ago = (now - timedelta(days=30)).strftime("%Y/%m/%d")
    ts = now.strftime("%Y/%m/%d %H:%M")

    # history.json から昨年同週データを読み込む
    history_weekly = {}
    if os.path.exists("history.json"):
        with open("history.json", encoding="utf-8") as hf:
            history_weekly = json.load(hf).get("weekly", {})
    iso = now.isocalendar()
    cur_week_key  = f"{iso[0]}/W{iso[1]:02d}"
    prev_week_key = f"{iso[0]-1}/W{iso[1]:02d}"
    cur_week_data  = history_weekly.get(cur_week_key,  {})
    prev_week_data = history_weekly.get(prev_week_key, {})

    def yoy_diff_html(cur, prev, unit=""):
        """増減率バッジを返す。prevが0またはNoneなら '－' を返す"""
        if not prev:
            return '<span class="yoy-na">－</span>'
        pct = (cur - prev) / prev * 100
        if pct > 0:
            return f'<span class="yoy-up">+{pct:.0f}%&nbsp;▲</span>'
        elif pct < 0:
            return f'<span class="yoy-dn">{pct:.0f}%&nbsp;▼</span>'
        else:
            return '<span class="yoy-eq">±0%</span>'

    # 魚種ごとにレコードを集約
    fs = {}
    for c in data:
        for f in c["fish"]:
            fs.setdefault(f, []).append(c)

    css = ("*{box-sizing:border-box;margin:0;padding:0}"
           "body{font-family:sans-serif;background:#0a1628;color:#e0e8f0}"
           "header{background:#0d2137;padding:16px 24px;border-bottom:2px solid #1a6ea8}"
           "h1{font-size:20px;color:#4db8ff}header p{font-size:12px;color:#7a9bb5;margin-top:4px}"
           ".w{max-width:900px;margin:0 auto;padding:20px 16px}"
           "h2{font-size:15px;color:#4db8ff;border-left:4px solid #4db8ff;padding-left:10px;margin:24px 0 12px}"
           ".stats{display:flex;gap:12px;flex-wrap:wrap;margin-bottom:8px}"
           ".stat{background:#0d2137;border:1px solid #1a4060;border-radius:8px;padding:14px 20px;flex:1;min-width:130px;text-align:center}"
           ".stat-num{font-size:28px;font-weight:bold;color:#4db8ff}"
           ".stat-label{font-size:11px;color:#7a9bb5;margin-top:4px}"
           ".rrow{display:flex;align-items:center;gap:12px;padding:11px 0;border-bottom:1px solid #0a1628}"
           ".rrow:last-child{border-bottom:none}"
           ".rnum{font-size:18px;font-weight:bold;color:#334155;width:28px;text-align:center;flex-shrink:0}"
           ".rnum.g1{color:#f59e0b}.rnum.g2{color:#94a3b8}.rnum.g3{color:#b45309}"
           ".rinfo{flex:1;min-width:0}.rship{font-size:14px;font-weight:bold;color:#fff}"
           ".rarea{font-size:11px;color:#7a9bb5;margin-top:2px}"
           ".rbar-wrap{width:130px;flex-shrink:0;text-align:right}"
           ".rcnt{font-size:15px;font-weight:bold;color:#4db8ff}"
           ".runit{font-size:11px;color:#7a9bb5}"
           ".rbar-bg{background:#0a1628;border-radius:4px;height:6px;margin-top:5px}"
           ".rbar{height:6px;background:linear-gradient(90deg,#1a6ea8,#4db8ff);border-radius:4px}"
           ".area-list{display:flex;flex-wrap:wrap;gap:8px}"
           ".area-tag{background:#0d2137;border:1px solid #1a4060;border-radius:6px;padding:6px 14px;font-size:13px}"
           ".area-tag span{color:#4db8ff;font-weight:bold;margin-left:6px}"
           ".back{display:inline-block;margin-top:28px;color:#4db8ff;font-size:13px;text-decoration:none;border:1px solid #1a4060;border-radius:6px;padding:8px 18px}"
           ".back:hover{border-color:#4db8ff;background:#0d2137}"
           ".note{font-size:11px;color:#7a9bb5;margin-top:20px}"
           ".season-section{background:#0d2137;border:1px solid #1a4060;border-radius:8px;padding:16px;margin:0 0 20px}"
           ".season-header{display:flex;align-items:center;gap:10px;margin-bottom:12px}"
           ".season-title{font-size:13px;color:#7a9bb5;font-weight:bold}"
           ".axis-badge{background:#1a6ea8;color:#e0e8f0;font-size:12px;font-weight:bold;padding:4px 12px;border-radius:20px}"
           ".season-bar{display:flex;gap:2px;margin-bottom:8px}"
           ".sb-cell{flex:1;border-radius:4px;padding:5px 1px;text-align:center;display:flex;flex-direction:column;align-items:center;justify-content:center;min-width:0}"
           ".sb-month{font-size:9px;color:#e0e8f0;opacity:.8}"
           ".sb-label{font-size:9px;color:#fff;font-weight:bold;margin-top:2px;min-height:11px}"
           ".season-legend{display:flex;gap:14px;flex-wrap:wrap;margin-bottom:10px}"
           ".leg{font-size:10px;color:#7a9bb5;display:flex;align-items:center;gap:4px}"
           ".leg-dot{width:10px;height:10px;border-radius:2px;display:inline-block;flex-shrink:0}"
           ".season-comment{font-size:13px;color:#7dd3fc;line-height:1.7;padding-top:10px;border-top:1px solid #1a4060;margin-top:4px}"
           ".yoy-section{background:#0d2137;border:1px solid #1a4060;border-radius:8px;padding:4px 16px;margin-bottom:8px}"
           ".yoy-row{display:flex;align-items:center;gap:8px;padding:10px 0;border-bottom:1px solid #0a1628}"
           ".yoy-row:last-child{border-bottom:none}"
           ".yoy-label{font-size:12px;color:#7a9bb5;width:72px;flex-shrink:0}"
           ".yoy-cur{font-size:20px;font-weight:bold;color:#4db8ff;min-width:56px;text-align:right}"
           ".yoy-unit{font-size:11px;color:#7a9bb5;margin-right:4px}"
           ".yoy-arrow{font-size:11px;color:#334155;margin:0 6px}"
           ".yoy-prev{font-size:12px;color:#7a9bb5;min-width:56px;text-align:right}"
           ".yoy-diff{font-size:13px;font-weight:bold;min-width:72px;text-align:right;flex-shrink:0}"
           ".yoy-up{color:#4ade80}.yoy-dn{color:#f87171}.yoy-eq{color:#fbbf24}.yoy-na{color:#4b5563}"
           ".yoy-week{font-size:11px;color:#7a9bb5;margin-bottom:10px}")

    for fish, catches in fs.items():
        if len(catches) < 5:
            continue

        cnt7  = sum(1 for c in catches if c.get("date") and c["date"] >= week_ago)
        cnt30 = sum(1 for c in catches if c.get("date") and c["date"] >= month_ago)

        # 船宿別ランキング（最高釣果）
        ships = {}
        for c in catches:
            key = c["ship"]
            mx = (c.get("count_range") or {}).get("max", 0)
            if key not in ships or ships[key]["max"] < mx:
                ships[key] = {"ship": c["ship"], "area": c["area"], "max": mx, "date": c.get("date", "")}
        ranking = sorted(ships.values(), key=lambda x: -x["max"])[:10]
        top_max = ranking[0]["max"] if ranking else 1

        rank_html = ""
        medals = ["g1", "g2", "g3"]
        for i, r in enumerate(ranking):
            pct = round(r["max"] / top_max * 100) if top_max > 0 else 0
            mc = medals[i] if i < len(medals) else ""
            rank_html += (f'<div class="rrow">'
                          f'<div class="rnum {mc}">{i+1}</div>'
                          f'<div class="rinfo"><div class="rship">{r["ship"]}</div>'
                          f'<div class="rarea">{r["area"]} · {r["date"]}</div></div>'
                          f'<div class="rbar-wrap">'
                          f'<div class="rcnt">{r["max"]}<span class="runit"> 匹</span></div>'
                          f'<div class="rbar-bg"><div class="rbar" style="width:{pct}%"></div></div>'
                          f'</div></div>')

        # エリア別件数
        area_cnt = {}
        for c in catches:
            area_cnt[c["area"]] = area_cnt.get(c["area"], 0) + 1
        area_html = "".join(
            f'<div class="area-tag">{a}<span>{n}件</span></div>'
            for a, n in sorted(area_cnt.items(), key=lambda x: -x[1])
        )

        # 昨年同週比較セクション
        yoy_html = ""
        cur_fish  = cur_week_data.get(fish)
        # historyに当週データがない場合、直近7日の catches から即時集計
        if not cur_fish:
            week_catches = [c for c in catches if c.get("date") and c["date"] >= week_ago]
            if week_catches:
                maxes = [c["count_range"]["max"] for c in week_catches
                         if c.get("count_range") and c["count_range"].get("max")]
                cur_fish = {
                    "ships": len(week_catches),
                    "max":   max(maxes) if maxes else 0,
                    "avg":   round(sum(maxes) / len(maxes), 1) if maxes else 0,
                }
        prev_fish = prev_week_data.get(fish)
        if cur_fish or prev_fish:
            def _val(d, key):
                return d[key] if d and key in d else None
            c_ships = _val(cur_fish, "ships")
            c_avg   = _val(cur_fish, "avg")
            c_max   = _val(cur_fish, "max")
            p_ships = _val(prev_fish, "ships")
            p_avg   = _val(prev_fish, "avg")
            p_max   = _val(prev_fish, "max")

            def row(label, c_v, p_v, unit):
                if c_v is None:
                    return ""
                cur_str  = f'{c_v:.0f}' if isinstance(c_v, float) else str(c_v)
                prev_str = (f'{p_v:.0f}' if isinstance(p_v, float) else str(p_v)) if p_v is not None else "－"
                diff     = yoy_diff_html(c_v, p_v)
                return (f'<div class="yoy-row">'
                        f'<span class="yoy-label">{label}</span>'
                        f'<span class="yoy-cur">{cur_str}</span><span class="yoy-unit">{unit}</span>'
                        f'<span class="yoy-arrow">vs</span>'
                        f'<span class="yoy-prev">昨年&nbsp;{prev_str}<span class="yoy-unit">{unit}</span></span>'
                        f'<span class="yoy-diff">{diff}</span>'
                        f'</div>')

            rows = (row("出船数",   c_ships, p_ships, "隻") +
                    row("平均匹数", c_avg,   p_avg,   "匹") +
                    row("Max匹数",  c_max,   p_max,   "匹"))
            if rows:
                yoy_html = (f'<h2>📅 昨年同週比較（{cur_week_key} vs {prev_week_key}）</h2>'
                            f'<div class="yoy-section">{rows}</div>')

        # シーズンバー（FISH_MASTERに登録されている魚種のみ）
        season_html = ""
        if fish in FISH_MASTER:
            md = FISH_MASTER[fish]
            s_set  = set(md.get("season", []))
            pn_set = set(md.get("peak_num", []))
            ps_set = set(md.get("peak_size", []))
            axis    = md.get("axis", "")
            comment = md.get("comment", "")
            cells = ""
            for m in range(1, 13):
                if m in ps_set:
                    bg = "#fbbf24"; lbl = "型"
                elif m in pn_set:
                    bg = "#f59e0b"; lbl = "数"
                elif m in s_set:
                    bg = "#1a4060"; lbl = "○"
                else:
                    bg = "#071020"; lbl = ""
                cells += (f'<div class="sb-cell" style="background:{bg}">'
                          f'<div class="sb-month">{m}</div>'
                          f'<div class="sb-label">{lbl}</div>'
                          f'</div>')
            axis_badge = f'<span class="axis-badge">{axis}</span>' if axis else ""
            season_html = (
                f'<div class="season-section">'
                f'<div class="season-header">{axis_badge}'
                f'<span class="season-title">年間シーズンカレンダー</span></div>'
                f'<div class="season-bar">{cells}</div>'
                f'<div class="season-legend">'
                f'<span class="leg"><span class="leg-dot" style="background:#1a4060"></span>出船期間</span>'
                f'<span class="leg"><span class="leg-dot" style="background:#f59e0b"></span>数狙いピーク</span>'
                f'<span class="leg"><span class="leg-dot" style="background:#fbbf24"></span>型狙いピーク</span>'
                f'</div>'
                f'<div class="season-comment">{comment}</div>'
                f'</div>'
            )

        html = (f'<!DOCTYPE html><html lang="ja"><head><meta charset="UTF-8">'
                f'<meta name="viewport" content="width=device-width,initial-scale=1">'
                f'<title>{fish}の釣果情報 | 関東船釣り予想</title>'
                f'<meta name="description" content="関東エリアの{fish}最新釣果。船宿別ランキング、週間件数、エリア情報を毎日更新。">'
                f'<style>{css}</style></head><body>'
                f'<header><h1>🎣 {fish}の釣果情報</h1>'
                f'<p>関東エリアの船宿釣果 毎日自動更新</p></header>'
                f'<div class="w">'
                f'{season_html}'
                f'<h2>📊 直近の釣果件数</h2>'
                f'<div class="stats">'
                f'<div class="stat"><div class="stat-num">{cnt7}</div><div class="stat-label">直近7日</div></div>'
                f'<div class="stat"><div class="stat-num">{cnt30}</div><div class="stat-label">直近30日</div></div>'
                f'<div class="stat"><div class="stat-num">{len(catches)}</div><div class="stat-label">累計件数</div></div>'
                f'</div>'
                f'{yoy_html}'
                f'<h2>🏆 船宿別釣果ランキング（最高釣果 TOP{len(ranking)}）</h2>'
                f'{rank_html}'
                f'<h2>📍 エリア別内訳</h2>'
                f'<div class="area-list">{area_html}</div>'
                f'<a class="back" href="../index.html">← 関東船釣りトップへ戻る</a>'
                f'<p class="note">最終更新: {ts} · 総件数: {len(catches)}件</p>'
                f'</div></body></html>')

        fname = f"fish/{fish}.html"
        with open(fname, "w", encoding="utf-8") as fh:
            fh.write(html)
        print(f"  生成: {fname} ({len(catches)}件)")

    print(f"=== 魚種ページ生成完了 ===")


def build_calendar_page():
    """釣りものカレンダーページ（calendar.html）を生成する"""
    from datetime import datetime
    now = datetime.now()
    cur_m = now.month
    ts = now.strftime("%Y/%m/%d %H:%M")

    CALENDAR_FISH = ["アジ","マダイ","ヒラメ","タチウオ","シロギス","カワハギ",
                     "イサキ","ヤリイカ","マルイカ","スルメイカ","アマダイ","フグ","カサゴ","サワラ"]

    # ヘッダー行
    head_cells = ""
    for m in range(1, 13):
        cur_cls = " cal-cur-h" if m == cur_m else ""
        head_cells += f'<th class="cal-mh{cur_cls}">{m}月</th>'
    head_html = f'<tr><th class="cal-fish-h">魚種 / 軸</th>{head_cells}</tr>'

    # データ行
    rows_html = ""
    for fish in CALENDAR_FISH:
        md = FISH_MASTER.get(fish, {})
        s_set  = set(md.get("season", []))
        pn_set = set(md.get("peak_num", []))
        ps_set = set(md.get("peak_size", []))
        axis   = md.get("axis", "")
        axis_badge = f'<span class="axis-badge">{axis}</span>' if axis else ""
        fish_link  = f'<a href="fish/{fish}.html" class="fish-link">{fish}</a>'
        cells = ""
        for m in range(1, 13):
            cur_cls = " cal-cur" if m == cur_m else ""
            if m in ps_set:
                bg = "#fbbf24"; lbl = "型▲"
            elif m in pn_set:
                bg = "#f59e0b"; lbl = "数◎"
            elif m in s_set:
                bg = "#1a4060"; lbl = "○"
            else:
                bg = ""; lbl = ""
            style = f"background:{bg}" if bg else ""
            cells += f'<td class="cal-cell{cur_cls}" style="{style}">{lbl}</td>'
        rows_html += f'<tr><td class="cal-fish-td">{fish_link} {axis_badge}</td>{cells}</tr>'

    css = ("*{box-sizing:border-box;margin:0;padding:0}"
           "body{font-family:sans-serif;background:#0a1628;color:#e0e8f0}"
           "header{background:#0d2137;padding:16px 24px;border-bottom:2px solid #1a6ea8}"
           "h1{font-size:20px;color:#4db8ff}header p{font-size:12px;color:#7a9bb5;margin-top:4px}"
           ".nav{background:#071020;padding:8px 24px;border-bottom:1px solid #1a4060;display:flex;gap:16px}"
           ".nav a{color:#7a9bb5;font-size:13px;text-decoration:none}.nav a:hover{color:#4db8ff}"
           ".nav a.active{color:#4db8ff;font-weight:bold}"
           ".w{max-width:1100px;margin:0 auto;padding:20px 16px}"
           "h2{font-size:15px;color:#4db8ff;border-left:4px solid #4db8ff;padding-left:10px;margin:24px 0 12px}"
           ".legend{display:flex;gap:16px;flex-wrap:wrap;margin:0 0 16px;padding:12px 16px;background:#0d2137;border-radius:8px;border:1px solid #1a4060}"
           ".leg{font-size:11px;display:flex;align-items:center;gap:6px;color:#7a9bb5}"
           ".leg-dot{width:14px;height:14px;border-radius:3px;display:inline-block;flex-shrink:0}"
           ".cal-wrap{overflow-x:auto}"
           "table{border-collapse:collapse;width:100%;min-width:680px}"
           ".cal-fish-h{text-align:left;padding:8px 12px;background:#0d2137;color:#4db8ff;font-size:12px;white-space:nowrap;position:sticky;left:0;z-index:2}"
           ".cal-mh{min-width:52px;text-align:center;padding:8px 4px;background:#0d2137;color:#7a9bb5;font-size:12px;border-left:1px solid #1a4060}"
           ".cal-cur-h{color:#f59e0b !important;background:#1a3050 !important;font-weight:bold}"
           ".cal-fish-td{padding:8px 12px;border-bottom:1px solid #071020;background:#071830;position:sticky;left:0;z-index:1;white-space:nowrap}"
           ".cal-cell{text-align:center;padding:8px 2px;border-left:1px solid #071020;border-bottom:1px solid #071020;font-size:10px;color:#fff;min-width:52px}"
           ".cal-cur{outline:2px solid rgba(245,158,11,.45);outline-offset:-2px}"
           ".fish-link{color:#e0e8f0;text-decoration:none;font-size:13px;font-weight:bold;margin-right:4px}"
           ".fish-link:hover{color:#4db8ff}"
           ".axis-badge{background:#1a6ea8;color:#e0e8f0;font-size:10px;font-weight:bold;padding:2px 7px;border-radius:10px}"
           ".note{font-size:11px;color:#7a9bb5;text-align:right;margin-top:12px}"
           ".back{display:inline-block;margin-top:20px;color:#4db8ff;font-size:13px;text-decoration:none;border:1px solid #1a4060;border-radius:6px;padding:8px 18px}"
           ".back:hover{border-color:#4db8ff;background:#0d2137}")

    html = (f'<!DOCTYPE html><html lang="ja"><head><meta charset="UTF-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>釣りものカレンダー | 関東船釣り予想</title>'
            f'<meta name="description" content="関東エリアの魚種別シーズンカレンダー。月別の出船・数ピーク・型ピークを一覧表示。">'
            f'<style>{css}</style></head><body>'
            f'<header><h1>🎣 釣りものカレンダー</h1>'
            f'<p>関東エリア 魚種別シーズン早見表 · 毎日自動更新</p></header>'
            f'<nav class="nav"><a href="index.html">🏠 トップ</a>'
            f'<a href="calendar.html" class="active">📅 カレンダー</a></nav>'
            f'<div class="w">'
            f'<h2>📅 魚種別シーズンカレンダー</h2>'
            f'<div class="legend">'
            f'<span class="leg"><span class="leg-dot" style="background:#1a4060"></span>出船あり</span>'
            f'<span class="leg"><span class="leg-dot" style="background:#f59e0b"></span>数狙いピーク（数◎）</span>'
            f'<span class="leg"><span class="leg-dot" style="background:#fbbf24"></span>型狙いピーク（型▲）</span>'
            f'<span class="leg"><span class="leg-dot" style="outline:2px solid rgba(245,158,11,.45);background:transparent"></span>今月（{cur_m}月）</span>'
            f'</div>'
            f'<div class="cal-wrap"><table>{head_html}{rows_html}</table></div>'
            f'<a class="back" href="index.html">← 関東船釣りトップへ戻る</a>'
            f'<p class="note">最終更新: {ts}</p>'
            f'</div></body></html>')

    with open("calendar.html", "w", encoding="utf-8") as fh:
        fh.write(html)
    print("  生成: calendar.html")


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
        link = (f'<a class="fc-link" href="fish/{f}.html" onclick="event.stopPropagation()" title="{f}の詳細ページ">詳細→</a>'
                if len(cs) >= 5 else "")
        cards += (f'<div class="fc" onclick="showRank(\'{f}\')" title="{f}のランキング">'
                  f'<div class="fn">{f}</div>'
                  f'<div class="fk">{len(cs)}件 {badge}</div>'
                  f'<div class="fa">{"/".join(areas)}</div>'
                  f'{link}</div>')

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
           ".target-section{background:#0d2137;border:1px solid #1a6ea8;border-radius:10px;padding:16px 20px;margin-bottom:24px}"
           ".target-header{display:flex;align-items:baseline;gap:12px;margin-bottom:12px;flex-wrap:wrap}"
           ".target-title{font-size:16px;font-weight:bold;color:#4db8ff}"
           ".target-week{font-size:11px;color:#7a9bb5}"
           ".tr-row{display:flex;align-items:center;gap:10px;padding:8px 0;border-bottom:1px solid #0a1628;flex-wrap:wrap}"
           ".tr-row:last-child{border-bottom:none}"
           ".tr-medal{font-size:18px;width:28px;flex-shrink:0}"
           ".tr-star{font-size:12px;color:#f59e0b;width:80px;flex-shrink:0;letter-spacing:-1px}"
           ".tr-fish{font-size:15px;font-weight:bold;color:#fff;width:80px;flex-shrink:0}"
           ".tr-comment{font-size:12px;color:#7dd3fc;flex:1}"
           ".tr-hot{font-size:11px;color:#7a9bb5;flex-shrink:0}"
           ".fc{background:#0d2137;border:1px solid #1a4060;border-radius:8px;padding:10px;text-align:center;cursor:pointer;transition:border-color .2s,transform .15s}"
           ".fc:hover{border-color:#4db8ff;transform:translateY(-2px)}"
           ".fn{font-size:15px;font-weight:bold}.fk{font-size:12px;color:#4db8ff;margin-top:3px}"
           ".fa{font-size:11px;color:#7a9bb5;margin-top:2px}"
           ".fc-link{display:inline-block;font-size:10px;color:#4db8ff;text-decoration:none;margin-top:5px;border:1px solid #1a4060;border-radius:3px;padding:1px 6px}"
           ".fc-link:hover{background:#1a4060}"
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
           ".rbar{height:5px;background:linear-gradient(90deg,#1a6ea8,#4db8ff);border-radius:4px}"
           ".nav{background:#071020;padding:8px 24px;border-bottom:1px solid #1a4060;display:flex;gap:16px}"
           ".nav a{color:#7a9bb5;font-size:13px;text-decoration:none}.nav a:hover{color:#4db8ff}"
           ".nav a.active{color:#4db8ff;font-weight:bold}")

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
            f'<nav class="nav"><a href="index.html" class="active">🏠 トップ</a>'
            f'<a href="calendar.html">📅 カレンダー</a></nav>'
            f'<div class="w">'
            f'{build_target_section(calc_targets(data))}'
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
    build_fish_pages(all)
    build_calendar_page()
    print(f"=== 完了:{len(all)}件 エラー:{errs or 'なし'} ===")

if __name__=="__main__":
    main()
