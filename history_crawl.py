#!/usr/bin/env python3
"""
過去データ一括取得スクリプト（stealth mode）
- シングルワーカー（順次実行）
- ページ間 1.5〜3.0 秒ランダムスリープ
- 船宿間 5〜12 秒ランダムスリープ
- UA複数ローテーション
- 2年前より古いページは打ち切り
"""
import re, json, time, os, sys, random, gzip
from datetime import datetime, timedelta
from urllib.request import urlopen, Request
from urllib.error import URLError
from html.parser import HTMLParser

Z2H = str.maketrans("０１２３４５６７８９", "0123456789")
BASE = "https://www.fishing-v.jp/choka/choka_detail.php?s={sid}&pageID={page}"
GYO_BASE = "https://www.gyo.ne.jp/rep_tsuri_view%7CCID-{cid}.htm"

UA_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36 Edg/121.0.0.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_3) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3 Safari/605.1.15",
]

FISH_MAP = {
    "アジ":     ["アジ","ライトアジ","LTアジ","午前ライト","午後ライト","ウィリー"],
    "タチウオ": ["タチウオ","ショートタチウオ"],
    "フグ":     ["フグ","トラフグ","ショウサイ"],
    "カワハギ": ["カワハギ"],
    "マダイ":   ["マダイ","真鯛"],
    "シロギス": ["シロギス","キス"],
    "イサキ":   ["イサキ"],
    "ヤリイカ": ["ヤリイカ"],
    "スルメイカ":["スルメイカ"],
    "マダコ":   ["タコ","マダコ"],
    "カサゴ":   ["カサゴ"],
    "ワラサ":   ["ワラサ","イナダ","ブリ"],
    "アマダイ": ["アマダイ"],
    "ヒラメ":   ["ヒラメ"],
    "マゴチ":   ["マゴチ"],
    "五目":     ["五目"],
    "イシモチ": ["イシモチ"],
    "サワラ":   ["サワラ"],
    "マルイカ": ["マルイカ"],
    "マハタ":   ["マハタ"],
    "メバル":   ["メバル"],
    "クロムツ": ["クロムツ","ムツ"],
    "キンメダイ":["キンメダイ","キンメ"],
    "カンパチ": ["カンパチ"],
    "メダイ":   ["メダイ"],
}

CUTOFF = (datetime.now() - timedelta(days=365 * 2)).strftime("%Y/%m/%d")


def guess_fish(t):
    return [f for f, kws in FISH_MAP.items() if any(k in t for k in kws)] or [t[:10]]


def to_range(t, unit):
    t = t.translate(Z2H)
    is_boat = bool(re.search(r"船中|合計|全体", t))
    m = re.search(r"(\d+)\s*[~〜～]\s*(\d+)\s*" + unit, t)
    if m: return {"min": int(m[1]), "max": int(m[2]), "is_boat": is_boat}
    m = re.search(r"(\d+)\s*" + unit, t)
    if m: v = int(m[1]); return {"min": v, "max": v, "is_boat": is_boat}
    return None


class Parser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.records = []; self._date = None
        self._in_li = False; self._in_td = False; self._skip = False
        self._row = []; self._cell = ""

    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        if tag in ("script", "style"): self._skip = True; return
        if tag == "li" and d.get("class") == "date": self._in_li = True; self._cell = ""; return
        if tag == "tr": self._row = []
        if tag in ("td", "th"): self._in_td = True; self._cell = ""

    def handle_endtag(self, tag):
        if tag in ("script", "style"): self._skip = False; return
        if tag == "li" and self._in_li:
            self._in_li = False
            m = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日", self._cell.translate(Z2H))
            if m: self._date = f"{m[1]}/{int(m[2]):02d}/{int(m[3]):02d}"
        if tag in ("td", "th") and self._in_td:
            self._in_td = False; self._row.append(self._cell.strip()); self._cell = ""
        if tag == "tr" and self._date and len(self._row) >= 3:
            r = self._row; f = r[0].translate(Z2H)
            if f.isdigit() and len(r) >= 3: fish, cnt, sz = r[1], r[2], r[3] if len(r) > 3 else ""
            else: fish, cnt, sz = r[0], r[1], r[2] if len(r) > 2 else ""
            skip = {"魚種", "匹数", "大きさ", "重さ", "特記", "ポイント", "備考", ""}
            if fish not in skip and to_range(cnt, "匹"):
                self.records.append({"date": self._date, "fish": fish, "cnt": cnt, "sz": sz})

    def handle_data(self, data):
        if self._skip: return
        if self._in_li or self._in_td: self._cell += data


def fetch(url):
    ua = random.choice(UA_POOL)
    headers = {
        "User-Agent": ua,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ja,en-US;q=0.7,en;q=0.3",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
    }
    try:
        r = urlopen(Request(url, headers=headers), timeout=15)
        raw = r.read()
        # decompress if gzip
        if raw[:2] == b'\x1f\x8b':
            raw = gzip.decompress(raw)
        for enc in ("utf-8", "cp932", "shift_jis"):
            try: return raw.decode(enc)
            except: pass
        return raw.decode("utf-8", errors="replace")
    except Exception:
        return None


def sleep_page():
    """ページ間: 1.5〜3.0秒ランダム"""
    time.sleep(random.uniform(1.5, 3.0))


def sleep_ship():
    """船宿間: 5〜12秒ランダム"""
    time.sleep(random.uniform(5.0, 12.0))


def crawl_ship(ship):
    all_records = []
    for page in range(1, 100):
        url = BASE.format(sid=ship["sid"], page=page)
        html = fetch(url)
        if not html:
            print(f"    page{page}: fetch失敗 → スキップ")
            break
        p = Parser(); p.feed(html)
        if not p.records:
            break
        # 2年以上前のレコードが含まれていれば打ち切り
        oldest = min((r["date"] for r in p.records if r["date"]), default="9999")
        page_records = []
        for r in p.records:
            if not r["date"] or r["date"] < CUTOFF:
                continue
            cr = to_range(r["cnt"], "匹")
            sr = to_range(r["sz"], "cm")
            wkgr = to_range(r["sz"], "kg")
            for fish in guess_fish(r["fish"]):
                page_records.append({
                    "date":     r["date"],
                    "ship":     ship["name"],
                    "area":     ship["area"],
                    "fish":     fish,
                    "max":      cr["max"] if cr else 0,
                    "avg":      (cr["min"] + cr["max"]) // 2 if cr else 0,
                    "is_boat":  cr["is_boat"] if cr else False,
                    "size_max": sr["max"] if sr else 0,
                    "weight_avg": (wkgr["min"] + wkgr["max"]) / 2 if wkgr else 0,
                })
        all_records.extend(page_records)
        if "次</a>" not in html and ">次<" not in html:
            break
        # 2年前より古いページは以降不要
        if oldest < CUTOFF:
            break
        sleep_page()
    return all_records


def date_to_yearweek(ds):
    dt = datetime.strptime(ds, "%Y/%m/%d")
    iso = dt.isocalendar()
    return f"{iso[0]}/W{iso[1]:02d}"


def build_and_save(all_records):
    weekly = {}; monthly = {}
    for r in all_records:
        if not r.get("date"): continue
        wk = date_to_yearweek(r["date"]); mo = r["date"][:7]; fish = r["fish"]
        for store, key in [(weekly, wk), (monthly, mo)]:
            if key not in store: store[key] = {}
            if fish not in store[key]:
                store[key][fish] = {"ships": 0, "sum": 0, "max": 0, "cnt": 0, "szs": [], "wkgs": []}
            d = store[key][fish]
            d["ships"] += 1
            if not r.get("is_boat"): d["sum"] += r["avg"]; d["cnt"] += 1
            if r["max"] > d["max"]: d["max"] = r["max"]
            if r["size_max"] > 0: d["szs"].append(r["size_max"])
            if r.get("weight_avg", 0) > 0: d["wkgs"].append(r["weight_avg"])
    for store in [weekly, monthly]:
        for period in store:
            for fish in store[period]:
                d = store[period][fish]
                d["avg"]        = round(d["sum"] / d["cnt"], 1) if d["cnt"] > 0 else 0
                d["size_avg"]   = round(sum(d["szs"]) / len(d["szs"]), 1) if d["szs"] else 0
                d["weight_avg"] = round(sum(d["wkgs"]) / len(d["wkgs"]), 2) if d["wkgs"] else 0
                del d["sum"], d["cnt"], d["szs"], d["wkgs"]
    history = {"weekly": weekly, "monthly": monthly}
    if os.path.exists("history.json"):
        try:
            ex = json.load(open("history.json", encoding="utf-8"))
            if "weekly"  in ex: ex["weekly"].update(weekly);   history["weekly"]  = ex["weekly"]
            if "monthly" in ex: ex["monthly"].update(monthly); history["monthly"] = ex["monthly"]
        except: pass
    json.dump(history, open("history.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    return history


def main():
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from crawler import SHIPS
    fv_ships = [s for s in SHIPS if s.get("source", "fishing-v") == "fishing-v"]
    total = len(fv_ships)
    print(f"=== 過去データ取得（stealth mode）===")
    print(f"対象: {total} 船宿 / カットオフ: {CUTOFF}")
    print(f"待機: ページ間1.5〜3秒 / 船宿間5〜12秒")
    print(f"開始: {datetime.now().strftime('%Y/%m/%d %H:%M:%S')}\n")

    all_records = []
    # シャッフルしてアクセス順をランダム化
    ships_shuffled = fv_ships[:]
    random.shuffle(ships_shuffled)

    for i, ship in enumerate(ships_shuffled, 1):
        print(f"[{i:03d}/{total}] {ship['area']} {ship['name']} ...", end=" ", flush=True)
        recs = crawl_ship(ship)
        all_records.extend(recs)
        print(f"{len(recs)} 件")
        # 20船宿ごとに中間保存
        if i % 20 == 0:
            print(f">>> 中間保存... ({len(all_records)} 件)")
            build_and_save(all_records)
        # 船宿間スリープ（最後は不要）
        if i < total:
            sleep_ship()

    h = build_and_save(all_records)
    wks = sorted(h["weekly"].keys())
    mos = sorted(h["monthly"].keys())

    # 個別レコードを catches_all.json に保存（analysis用）
    json.dump(all_records,
              open("catches_all.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    print(f"\n=== 完了 ===")
    print(f"レコード総数: {len(all_records)} 件")
    print(f"週次: {len(wks)} 週 ({wks[0] if wks else '-'} 〜 {wks[-1] if wks else '-'})")
    print(f"月次: {len(mos)} ヶ月")
    print(f"終了: {datetime.now().strftime('%Y/%m/%d %H:%M:%S')}")
    print(f"個別レコード → catches_all.json")


if __name__ == "__main__":
    main()
