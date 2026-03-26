#!/usr/bin/env python3
"""
過去データ一括取得スクリプト（stealth mode）

[データソース]
- 釣りビジョン (fishing-v.jp): pageID ページネーション（pageID=1〜最大100）
- gyo.ne.jp: nav リンク BFS（1ページ=1日付、約7日分/船宿）

共通設定:
- シングルワーカー（順次実行）
- ページ間 1.5〜3.0 秒ランダムスリープ
- 船宿間 5〜12 秒ランダムスリープ
- UA複数ローテーション
- 2年前より古いページは打ち切り
"""
import re, json, time, os, sys, random, gzip, csv
from datetime import datetime, timedelta
from urllib.request import urlopen, Request
from urllib.error import URLError
from html.parser import HTMLParser

CSV_HEADER = ["ship","area","date","fish","cnt_min","cnt_max","cnt_avg",
              "size_min","size_max","kg_min","kg_max","is_boat","point_place","point_depth"]

def save_to_daily_csv(all_records):
    """
    all_records を data/YYYY-MM.csv に月別追記（重複スキップ）。
    crawler.py の save_daily_csv と同じフォーマット。
    """
    os.makedirs("data", exist_ok=True)
    from collections import defaultdict

    by_month = defaultdict(list)
    for r in all_records:
        date_str = r.get("date", "")
        if not date_str:
            continue
        try:
            ym = datetime.strptime(date_str, "%Y/%m/%d").strftime("%Y-%m")
        except ValueError:
            continue
        by_month[ym].append(r)

    total_added = 0
    for ym, recs in by_month.items():
        filepath = os.path.join("data", f"{ym}.csv")

        existing_keys = set()
        if os.path.exists(filepath):
            with open(filepath, encoding="utf-8", newline="") as f:
                for row in csv.DictReader(f):
                    existing_keys.add((row["ship"], row["area"], row["date"], row["fish"]))

        new_rows = []
        for r in recs:
            key = (r["ship"], r["area"], r["date"], r["fish"])
            if key in existing_keys:
                continue
            avg = r.get("avg", 0)
            mx  = r.get("max", 0)
            mn  = max(0, 2 * avg - mx)  # avg=(min+max)//2 の逆算
            sz  = r.get("size_max", 0)
            wt  = r.get("weight_avg", 0)
            new_rows.append({
                "ship":        r["ship"],
                "area":        r["area"],
                "date":        r["date"],
                "fish":        r["fish"],
                "cnt_min":     mn if mn > 0 else "",
                "cnt_max":     mx if mx > 0 else "",
                "cnt_avg":     avg if avg > 0 else "",
                "size_min":    "",
                "size_max":    sz if sz > 0 else "",
                "kg_min":      "",
                "kg_max":      round(wt * 1.2, 2) if wt > 0 else "",
                "is_boat":     1 if r.get("is_boat") else 0,
                "point_place": "",
                "point_depth": "",
            })
            existing_keys.add(key)

        if not new_rows:
            continue
        write_header = not os.path.exists(filepath)
        with open(filepath, "a", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=CSV_HEADER)
            if write_header:
                w.writeheader()
            w.writerows(new_rows)
        total_added += len(new_rows)

    return total_added

Z2H = str.maketrans("０１２３４５６７８９", "0123456789")
# 全角数字＋小数点（gyo テキスト用）
Z2H_WIDE = str.maketrans("０１２３４５６７８９．", "0123456789.")

# ── 釣りビジョン ──────────────────────────────────────────────────────
BASE = "https://www.fishing-v.jp/choka/choka_detail.php?s={sid}&pageID={page}"

# ── gyo.ne.jp ────────────────────────────────────────────────────────
GYO_MAIN   = "https://www.gyo.ne.jp/rep_tsuri_view%7CCID-{cid}.htm"
GYO_HIST   = "https://www.gyo.ne.jp/rep_tsuri_history_view%7CCID-{cid}%7Chdt-{hdt}%7Cdt-{dt}.htm"
GYO_ORIGIN = "https://www.gyo.ne.jp"

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


# ── gyo.ne.jp フェッチ（Shift-JIS 優先） ────────────────────────────

def fetch_gyo(url, retries=2):
    """gyo.ne.jp 専用 fetch。cp932/shift_jis を優先してデコード。"""
    for attempt in range(retries + 1):
        try:
            ua = random.choice(UA_POOL)
            req = Request(url, headers={
                "User-Agent": ua,
                "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
                "Accept-Language": "ja,en-US;q=0.7",
                "Connection": "keep-alive",
            })
            with urlopen(req, timeout=20) as r:
                raw = r.read()
            for enc in ("cp932", "shift_jis", "euc-jp", "utf-8"):
                try:
                    return raw.decode(enc)
                except Exception:
                    pass
            return raw.decode("utf-8", errors="replace")
        except Exception as e:
            if attempt < retries:
                time.sleep(2)
            else:
                print(f"  fetch_gyo error [{url[:80]}]: {e}")
    return None


# ── gyo.ne.jp テキストパーサー ────────────────────────────────────────

# FISH_MAP をフラット化（長い名前を先にマッチ）: 遅延初期化
_GYO_FISH_FLAT = {}   # keyword → canonical

def _init_gyo_fish():
    if _GYO_FISH_FLAT:
        return
    for canon, kws in FISH_MAP.items():
        for kw in kws:
            _GYO_FISH_FLAT[kw] = canon


def _gyo_parse_page(html, date_str, ship_name, area_name):
    """
    gyo.ne.jp の 1 ページ（日付はURL等から既知）を解析し、
    history_crawl 形式のレコードリストを返す。

    テキストは全角数字を含むフリー文章形式。
    テーブルが存在する場合にも対応する。
    """
    _init_gyo_fish()

    # メインコンテンツ（word-break:break-all div 以降）を対象にする
    anchor = html.find("word-break: break-all")
    section = html[anchor:] if anchor >= 0 else html

    # HTML タグ除去・全角→半角変換・空白正規化
    text = re.sub(r"<[^>]+>", " ", section)
    text = re.sub(r"&[a-zA-Z]+;|&#\d+;", " ", text)
    text = re.sub(r"[\u3000\xa0\ufffd]+", " ", text)
    text = text.translate(Z2H_WIDE)
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return []

    sorted_names = sorted(_GYO_FISH_FLAT.keys(), key=len, reverse=True)
    results = []
    seen_canon = set()

    for fish_name in sorted_names:
        if fish_name not in text:
            continue
        canon = _GYO_FISH_FLAT[fish_name]
        if canon in seen_canon:
            continue

        # 魚名から 100 文字以内で「N〜M 匹/枚/尾/本」パターンを探す
        pat_range  = rf"{re.escape(fish_name)}.{{0,100}}?(\d+)\s*[〜~～]\s*(\d+)\s*[枚匹尾本]"
        pat_single = rf"{re.escape(fish_name)}.{{0,60}}?(\d+)\s*[枚匹尾本]"

        cr = None
        for pat in (pat_range, pat_single):
            m = re.search(pat, text, re.DOTALL)
            if m:
                if len(m.groups()) == 2:
                    mn, mx = int(m.group(1)), int(m.group(2))
                    cr = {"min": min(mn, mx), "max": max(mn, mx)}
                else:
                    v = int(m.group(1))
                    cr = {"min": v, "max": v}
                break

        if not cr or cr["max"] == 0:
            continue

        seen_canon.add(canon)
        results.append({
            "date":       date_str,
            "ship":       ship_name,
            "area":       area_name,
            "fish":       canon,
            "max":        cr["max"],
            "avg":        (cr["min"] + cr["max"]) // 2,
            "is_boat":    False,
            "size_max":   0,
            "weight_avg": 0,
        })

    return results


# ── gyo.ne.jp 船宿クローラー ──────────────────────────────────────────

def crawl_ship_gyo(ship):
    """
    gyo.ne.jp の 1 船宿分（メインページ＋nav リンク）を取得する。

    gyo.ne.jp は 1 ページ = 1 日付。
    メインページと nav に列挙された過去ページをすべて取得する。
    2 年前より古い日付はスキップ。
    """
    cid   = ship["cid"]
    today = datetime.now().strftime("%Y/%m/%d")
    all_records = []
    visited = set()

    def _parse_and_store(url, date_str):
        if url in visited:
            return
        visited.add(url)
        html = fetch_gyo(url)
        if not html:
            return
        recs = _gyo_parse_page(html, date_str, ship["name"], ship["area"])
        all_records.extend(recs)
        return html  # nav リンク収集のため返す

    # 1. メインページ（最新日付）
    main_url = GYO_MAIN.format(cid=cid)
    html = _parse_and_store(main_url, today)
    if not html:
        return all_records

    # メインページ中の「発信」日付を抽出して上書き
    m = re.search(r"(\d{4}/\d{2}/\d{2})\s*[&nbsp;　]*発信", html)
    if m:
        all_records_today_date = m.group(1)
        for r in all_records:
            r["date"] = all_records_today_date

    # 2. nav リンクから過去ページを列挙して取得
    nav_pattern = rf"/rep_tsuri_history_view\|CID-{re.escape(cid)}\|hdt-([0-9/]+)\|dt-([0-9/]+)\.htm"
    for hdt, dt in re.findall(nav_pattern, html):
        # 2 年以上前はスキップ
        try:
            if datetime.strptime(hdt, "%Y/%m/%d") < datetime.now() - timedelta(days=365 * 2):
                continue
        except ValueError:
            continue
        hist_url = GYO_HIST.format(cid=cid, hdt=hdt, dt=dt)
        time.sleep(random.uniform(1.5, 3.0))
        _parse_and_store(hist_url, hdt)

    return all_records


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
    fv_ships  = [s for s in SHIPS if s.get("source", "fishing-v") == "fishing-v"]
    gyo_ships = [s for s in SHIPS if s.get("source") == "gyo"]

    print(f"=== 過去データ取得（stealth mode）===")
    print(f"釣りビジョン: {len(fv_ships)} 船宿 / gyo.ne.jp: {len(gyo_ships)} 船宿")
    print(f"カットオフ: {CUTOFF}")
    print(f"待機: ページ間1.5〜3秒 / 船宿間5〜12秒")
    print(f"開始: {datetime.now().strftime('%Y/%m/%d %H:%M:%S')}\n")

    all_records = []

    # ── 釣りビジョン（pageID ページネーション） ──────────────────────
    total_fv = len(fv_ships)
    print(f"--- 釣りビジョン ({total_fv} 船宿) ---")
    ships_shuffled = fv_ships[:]
    random.shuffle(ships_shuffled)

    for i, ship in enumerate(ships_shuffled, 1):
        print(f"[FV {i:03d}/{total_fv}] {ship['area']} {ship['name']} ...", end=" ", flush=True)
        recs = crawl_ship(ship)
        all_records.extend(recs)
        print(f"{len(recs)} 件")
        if i % 20 == 0:
            print(f">>> 中間保存... ({len(all_records)} 件)")
            build_and_save(all_records)
            save_to_daily_csv(all_records)
        if i < total_fv:
            sleep_ship()

    # ── gyo.ne.jp（nav リンク BFS） ──────────────────────────────────
    total_gyo = len(gyo_ships)
    print(f"\n--- gyo.ne.jp ({total_gyo} 船宿) ---")
    gyo_shuffled = gyo_ships[:]
    random.shuffle(gyo_shuffled)

    for i, ship in enumerate(gyo_shuffled, 1):
        print(f"[GYO {i:03d}/{total_gyo}] {ship['area']} {ship['name']} ...", end=" ", flush=True)
        recs = crawl_ship_gyo(ship)
        all_records.extend(recs)
        print(f"{len(recs)} 件")
        if i % 10 == 0:
            print(f">>> 中間保存... ({len(all_records)} 件)")
            build_and_save(all_records)
            save_to_daily_csv(all_records)
        if i < total_gyo:
            sleep_ship()

    h = build_and_save(all_records)
    wks = sorted(h["weekly"].keys())
    mos = sorted(h["monthly"].keys())

    # 日次CSVに保存（data/YYYY-MM.csv）
    csv_added = save_to_daily_csv(all_records)

    print(f"\n=== 完了 ===")
    print(f"レコード総数: {len(all_records)} 件")
    print(f"週次: {len(wks)} 週 ({wks[0] if wks else '-'} 〜 {wks[-1] if wks else '-'})")
    print(f"月次: {len(mos)} ヶ月")
    print(f"日次CSV追記: {csv_added} 件 → data/")
    print(f"終了: {datetime.now().strftime('%Y/%m/%d %H:%M:%S')}")


if __name__ == "__main__":
    main()
