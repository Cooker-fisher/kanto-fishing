#!/usr/bin/env python3
"""
関東船釣り情報クローラー v5.2
変更点(v5.2):
- Google AdSense コードを全ページの<head>に追加
変更点(v5.1):
- parse_catches_from_tables を廃止
- parse_catches_from_html に置き換え
  → choka_box 単位で li.date から正しい出船日を取得
  → 全釣果に「今日の日付」が入る問題を修正
"""
import re, json, time, os
from datetime import datetime
from urllib.request import urlopen, Request
from urllib.error import URLError
from html.parser import HTMLParser

SHIPS = [
    {"area": "外川",         "name": "孝進丸",       "sid": 749},
    {"area": "片貝",         "name": "勇幸丸",       "sid": 58},
    {"area": "大原",         "name": "義之丸",       "sid": 61},
    {"area": "勝浦松部港",   "name": "和八丸",       "sid": 1480},
    {"area": "勝山",         "name": "新盛丸",       "sid": 121},
    {"area": "富津",         "name": "川崎丸",       "sid": 141},
    {"area": "江戸川放水路", "name": "たかはし遊船", "sid": 145},
    {"area": "浦安",         "name": "吉久",         "sid": 147},
    {"area": "金沢八景",     "name": "一之瀬丸",     "sid": 186},
    {"area": "金沢漁港",     "name": "忠彦丸",       "sid": 185},
    {"area": "金沢八景",     "name": "米元釣船店",   "sid": 188},
    {"area": "金沢八景",     "name": "野毛屋",       "sid": 192},
    {"area": "久比里",       "name": "山下丸",       "sid": 209},
    {"area": "久比里",       "name": "山天丸",       "sid": 211},
    {"area": "久比里",       "name": "みのすけ丸",   "sid": 210},
    {"area": "久里浜",       "name": "大正丸",       "sid": 689},
    {"area": "松輪",         "name": "瀬戸丸",       "sid": 659},
    {"area": "長井",         "name": "はら丸",       "sid": 218},
    {"area": "長井",         "name": "丸八丸",       "sid": 12224},
    {"area": "葉山鐙摺",     "name": "愛正丸",       "sid": 232},
    {"area": "腰越",         "name": "飯岡丸",       "sid": 235},
    {"area": "茅ヶ崎",       "name": "ちがさき丸",   "sid": 795},
    {"area": "平塚",         "name": "庄三郎丸",     "sid": 244},
    {"area": "小田原早川",   "name": "平安丸",       "sid": 1700},
    {"area": "宇佐美",       "name": "秀正丸",       "sid": 270},
    {"area": "戸田",         "name": "福将丸",       "sid": 1875},
]

# エリアの地域グループ定義
AREA_GROUPS = {
    "千葉・外房":     ["外川", "片貝", "大原", "勝浦松部港"],
    "千葉・内房":     ["勝山", "富津"],
    "千葉・東京湾奥": ["江戸川放水路", "浦安"],
    "神奈川・東京湾": ["金沢八景", "金沢漁港", "久比里", "久里浜"],
    "神奈川・相模湾": ["松輪", "長井", "葉山鐙摺", "腰越", "茅ヶ崎", "平塚", "小田原早川"],
    "静岡":           ["宇佐美", "戸田"],
}

BASE_URL = "https://www.fishing-v.jp/choka/choka_detail.php?s={sid}"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

# Google AdSense
ADSENSE_TAG = '<script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=ca-pub-7406401300491553" crossorigin="anonymous"></script>'

FISH_MAP = {
    "アジ":     ["アジ", "LTアジ", "ライトアジ"],
    "タチウオ": ["タチウオ"],
    "フグ":     ["フグ", "トラフグ", "ショウサイフグ"],
    "カワハギ": ["カワハギ"],
    "マダイ":   ["マダイ", "真鯛"],
    "シロギス": ["シロギス", "キス"],
    "イサキ":   ["イサキ"],
    "ヤリイカ": ["ヤリイカ"],
    "スルメイカ": ["スルメイカ"],
    "マダコ":   ["タコ", "マダコ"],
    "カサゴ":   ["カサゴ", "オニカサゴ"],
    "メバル":   ["メバル"],
    "ワラサ":   ["ワラサ", "イナダ", "ブリ"],
    "アマダイ": ["アマダイ"],
    "メダイ":   ["メダイ"],
    "サワラ":   ["サワラ"],
    "ヒラメ":   ["ヒラメ"],
    "マゴチ":   ["マゴチ"],
    "キンメダイ": ["キンメダイ", "キンメ"],
    "クロムツ": ["クロムツ", "ムツ"],
    "マルイカ": ["マルイカ"],
    "カンパチ": ["カンパチ"],
    "マハタ":   ["マハタ"],
}

Z2H = str.maketrans("０１２３４５６７８９．", "0123456789.")

# ============================================================
# HTMLパーサー（テーブル抽出）
# ============================================================
class TableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tables = []
        self._in_table = False; self._in_row = False; self._in_cell = False
        self._current_table = []; self._current_row = []; self._current_cell = []
        self._skip = False; self._depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script","style"): self._skip = True
        if tag == "table":
            self._depth += 1
            if self._depth == 1: self._in_table = True; self._current_table = []
        elif tag == "tr" and self._in_table and self._depth == 1:
            self._in_row = True; self._current_row = []
        elif tag in ("td","th") and self._in_row:
            self._in_cell = True; self._current_cell = []
        elif tag == "br" and self._in_cell:
            self._current_cell.append(" ")

    def handle_endtag(self, tag):
        if tag in ("script","style"): self._skip = False
        if tag == "table":
            if self._depth == 1 and self._current_table:
                self.tables.append(self._current_table)
            self._in_table = False; self._depth -= 1
        elif tag == "tr" and self._in_row:
            if self._current_row: self._current_table.append(self._current_row)
            self._in_row = False
        elif tag in ("td","th") and self._in_cell:
            self._current_row.append("".join(self._current_cell).strip())
            self._in_cell = False

    def handle_data(self, data):
        if not self._skip and self._in_cell:
            self._current_cell.append(data)

# ============================================================
# パース補助
# ============================================================
def guess_fish(t):
    return [f for f, kws in FISH_MAP.items() if any(k in t for k in kws)] or ["不明"]

def parse_num(s):
    return s.translate(Z2H)

def extract_count(t):
    t = parse_num(t)
    m = re.search(r"(\d+)[～〜~](\d+)\s*[匹本尾枚杯]", t)
    if m: return {"min": int(m[1]), "max": int(m[2])}
    m = re.search(r"(\d+)\s*[匹本尾枚杯]", t)
    if m: v = int(m[1]); return {"min": v, "max": v}
    return None

def extract_size(t):
    t = parse_num(t)
    m = re.search(r"(\d+\.?\d*)[～〜~](\d+\.?\d*)\s*kg", t, re.I)
    if m: return {"min": float(m[1]), "max": float(m[2]), "unit": "kg"}
    m = re.search(r"(\d+\.?\d*)\s*kg", t, re.I)
    if m: v = float(m[1]); return {"min": v, "max": v, "unit": "kg"}
    m = re.search(r"(\d+)[～〜~](\d+)\s*cm", t, re.I)
    if m: return {"min": int(m[1]), "max": int(m[2]), "unit": "cm"}
    m = re.search(r"(\d+)\s*cm", t, re.I)
    if m: v = int(m[1]); return {"min": v, "max": v, "unit": "cm"}
    return None

def parse_jp_date(date_str, year):
    """
    '2026年1月7日(水)' → '2026/01/07'
    '1月7日(水)' → '{year}/01/07'
    """
    m = re.search(r'(\d{4})年(\d{1,2})月(\d{1,2})日', date_str)
    if m:
        return f"{int(m[1])}/{int(m[2]):02d}/{int(m[3]):02d}"
    m = re.search(r'(\d{1,2})月(\d{1,2})日', date_str)
    if m:
        return f"{year}/{int(m[1]):02d}/{int(m[2]):02d}"
    return None

# ============================================================
# v5.1: choka_box単位でパース（日付バグ修正）
# ============================================================
def parse_catches_from_html(html, ship, area, year):
    """
    fishing-v.jpの生HTMLをchoka_box単位で処理。
    li.date から出船日を取得し、同boxのテーブル行に紐づける。
    """
    results = []

    # choka_box ブロックを切り出す
    # 各 choka_box の開始位置を探し、次の choka_box 開始位置（またはHTML末尾）までを切り出す
    box_starts = [m.start() for m in re.finditer(r'<div[^>]+class="[^"]*choka_box[^"]*"', html)]

    # choka_box が見つからない場合はフォールバック: 旧方式（今日の日付）
    if not box_starts:
        boxes = []
    else:
        boxes = []
        for i, start in enumerate(box_starts):
            end = box_starts[i+1] if i+1 < len(box_starts) else len(html)
            boxes.append(html[start:end])
    if not boxes:
        # フォールバック: TableParserで全テーブルを取得し今日の日付を使用
        parser = TableParser()
        parser.feed(html)
        now = datetime.now()
        fallback_date = f"{year}/{now.month:02d}/{now.day:02d}"
        return _parse_tables(parser.tables, ship, area, fallback_date, now.month)

    for box_html in boxes:
        # li.date から日付を取得
        date_m = re.search(r'<li[^>]+class="[^"]*date[^"]*"[^>]*>([^<]+)</li>', box_html)
        if date_m:
            date_str = date_m.group(1).strip()
            date = parse_jp_date(date_str, year)
            month = int(re.search(r'(\d{1,2})月', date_str).group(1)) if re.search(r'(\d{1,2})月', date_str) else datetime.now().month
        else:
            now = datetime.now()
            date = f"{year}/{now.month:02d}/{now.day:02d}"
            month = now.month

        # box内のテーブルをパース
        box_parser = TableParser()
        box_parser.feed(box_html)
        catches = _parse_tables(box_parser.tables, ship, area, date, month)
        results.extend(catches)

    return results


def _parse_tables(tables, ship, area, date, month):
    """テーブルリストから釣果を抽出（日付は呼び出し元から受け取る）"""
    results = []
    for table in tables:
        if not table: continue
        header = table[0]
        header_str = " ".join(header)
        if "魚種" not in header_str and "匹数" not in header_str:
            continue
        fish_idx   = next((i for i,h in enumerate(header) if "魚種" in h), 1)
        count_idx  = next((i for i,h in enumerate(header) if "匹数" in h), 2)
        size_idx   = next((i for i,h in enumerate(header) if "大きさ" in h), 3)
        weight_idx = next((i for i,h in enumerate(header) if "重さ" in h), 4)

        for row in table[1:]:
            if len(row) <= fish_idx: continue
            fish_name = row[fish_idx].strip()
            if not fish_name or fish_name in ("魚種", "-", "－", ""): continue
            count_str  = row[count_idx].strip()  if count_idx  < len(row) else ""
            size_str   = row[size_idx].strip()   if size_idx   < len(row) else ""
            weight_str = row[weight_idx].strip() if weight_idx < len(row) else ""
            results.append({
                "ship":        ship,
                "area":        area,
                "date":        date,
                "month":       month,
                "catch_raw":   f"{fish_name} {count_str} {size_str} {weight_str}".strip(),
                "fish":        guess_fish(fish_name),
                "count_range": extract_count(count_str),
                "size_range":  extract_size(weight_str) or extract_size(size_str),
            })
    return results

def fetch(url):
    try:
        req = Request(url, headers={"User-Agent": USER_AGENT})
        with urlopen(req, timeout=20) as r:
            raw = r.read()
        for enc in ("utf-8","shift_jis","euc-jp"):
            try: return raw.decode(enc)
            except: pass
        return raw.decode("utf-8", errors="replace")
    except URLError as e:
        print(f"ERROR: {e}"); return None

# ============================================================
# history.json (#3: ISO週に統一)
# ============================================================
def load_history():
    if os.path.exists("history.json"):
        try:
            with open("history.json", encoding="utf-8") as f:
                return json.load(f)
        except: pass
    return {"weekly": {}, "monthly": {}}

def current_iso_week():
    now = datetime.now()
    return now.year, now.isocalendar()[1]

def update_history(catches, history):
    """今週・今月のcatchesデータをhistory.jsonに反映する"""
    target_weeks = set()
    for c in catches:
        if c.get("date"):
            try:
                dt = datetime.strptime(c["date"], "%Y/%m/%d")
                iso = dt.isocalendar()
                target_weeks.add(f"{iso[0]}/W{iso[1]:02d}")
            except: pass
    if not target_weeks:
        return history
    temp_w = {}
    temp_m = {}
    for c in catches:
        if not c.get("date"): continue
        try: dt = datetime.strptime(c["date"], "%Y/%m/%d")
        except: continue
        iso = dt.isocalendar()
        wk = f"{iso[0]}/W{iso[1]:02d}"
        mo = c["date"][:7]
        if wk not in target_weeks: continue
        cr = c.get("count_range") or {}
        sr = c.get("size_range") or {}
        avg = (cr.get("min", 0) + cr.get("max", 0)) // 2 if cr else 0
        mx  = cr.get("max", 0)
        sz  = sr.get("max", 0)
        for fish in c.get("fish", []):
            for store, key in [(temp_w, wk), (temp_m, mo)]:
                if key not in store: store[key] = {}
                if fish not in store[key]: store[key][fish] = {"ships": 0, "sum": 0, "cnt": 0, "max": 0, "szs": []}
                d = store[key][fish]
                d["ships"] += 1; d["sum"] += avg; d["cnt"] += 1
                if mx > d["max"]: d["max"] = mx
                if sz > 0: d["szs"].append(sz)
    for store, hist_key in [(temp_w, "weekly"), (temp_m, "monthly")]:
        for key, fish_data in store.items():
            history[hist_key][key] = {}
            for fish, d in fish_data.items():
                history[hist_key][key][fish] = {
                    "ships": d["ships"],
                    "avg":   round(d["sum"] / d["cnt"], 1) if d["cnt"] > 0 else 0,
                    "max":   d["max"],
                    "size_avg": round(sum(d["szs"]) / len(d["szs"]), 1) if d["szs"] else 0,
                }
    with open("history.json", "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)
    return history

def get_yoy_data(history, fish, year, week_num):
    this_key = f"{year}/W{week_num:02d}"
    last_key = f"{year-1}/W{week_num:02d}"
    this_data = history["weekly"].get(this_key, {}).get(fish)
    last_data = history["weekly"].get(last_key, {}).get(fish)
    return this_data, last_data

def get_prev_week_data(history, fish, year, week_num):
    """先週（同年・1週前）のhistoryデータを取得"""
    if week_num > 1:
        prev_key = f"{year}/W{week_num-1:02d}"
    else:
        prev_key = f"{year-1}/W52"
    return history["weekly"].get(prev_key, {}).get(fish)

def calc_composite_score(fish, cnt, max_cnt, this_w, last_w, prev_w, cur_month):
    """
    複合スコアを計算（0〜100点）
    件数25% + 匹数20% + 昨年比20% + 先週比15% + シーズン15% + サイズ5%
    データなしの場合は中立値（0.5）で計算
    """
    def safe_ratio(a, b, cap=2.0):
        if a and b and b > 0:
            return min(a / b, cap) / cap
        return 0.5  # データなし → 中立

    # 1. 件数スコア（今週の全魚種中での相対的な多さ）
    count_s = (cnt / max_cnt) if max_cnt > 0 else 0.5

    # 2. 平均匹数スコア（今週avg ÷ 昨年同週avg）
    avg_s = safe_ratio(
        this_w.get("avg") if this_w else None,
        last_w.get("avg") if last_w else None,
    )

    # 3. 昨年比スコア（今週ships ÷ 昨年同週ships）
    yoy_s = safe_ratio(
        this_w.get("ships") if this_w else None,
        last_w.get("ships") if last_w else None,
    )

    # 4. 先週比スコア（今週ships ÷ 先週ships、cap=1.5で過剰評価を抑制）
    wow_s = safe_ratio(
        this_w.get("ships") if this_w else None,
        prev_w.get("ships") if prev_w else None,
        cap=1.5,
    )

    # 5. シーズン係数（1〜5 → 0.2〜1.0 / データなし → 中立0.5）
    season = get_season_score(fish, cur_month)
    season_s = (season / 5.0) if season > 0 else 0.5

    # 6. サイズスコア（今週size_avg ÷ 昨年同週size_avg）
    size_s = safe_ratio(
        this_w.get("size_avg") if this_w else None,
        last_w.get("size_avg") if last_w else None,
    )

    weights = [
        (count_s, 0.25),
        (avg_s,   0.20),
        (yoy_s,   0.20),
        (wow_s,   0.15),
        (season_s,0.15),
        (size_s,  0.05),
    ]
    return round(sum(s * w for s, w in weights) * 100, 1)

def yoy_badge(this_data, last_data):
    if not this_data or not last_data: return ""
    t_val = this_data.get("avg") or this_data.get("ships", 0)
    l_val = last_data.get("avg") or last_data.get("ships", 0)
    if not l_val or not t_val: return ""
    pct = round((t_val - l_val) / l_val * 100)
    if pct >= 0: return f'<span class="yoy up">↑昨年比+{pct}%</span>'
    else:        return f'<span class="yoy down">↓昨年比{pct}%</span>'

# ============================================================
# シーズンデータ
# ============================================================
SEASON_DATA = {
    "アジ":     [3,3,3,4,4,5,5,4,4,4,4,3],
    "タチウオ": [1,1,1,1,2,3,5,5,5,4,3,2],
    "フグ":     [3,3,4,4,3,2,2,2,3,4,4,3],
    "カワハギ": [2,2,2,2,2,2,3,4,5,5,4,3],
    "マダイ":   [2,2,3,5,5,4,3,3,3,4,4,3],
    "シロギス": [1,1,2,3,5,5,5,4,3,2,1,1],
    "イサキ":   [1,1,2,3,4,5,5,4,3,2,1,1],
    "ヤリイカ": [4,4,3,2,2,2,2,2,2,3,4,5],
    "スルメイカ":[1,1,1,2,3,4,5,5,4,3,2,1],
    "マダコ":   [1,1,1,2,3,5,5,5,4,3,2,1],
    "カサゴ":   [4,4,4,3,3,2,2,2,3,3,4,4],
    "メバル":   [4,4,4,3,3,2,2,2,2,3,4,4],
    "ワラサ":   [2,2,2,2,3,3,4,4,5,5,4,3],
    "ヒラメ":   [4,4,3,3,3,3,3,3,4,5,5,4],
    "アマダイ": [3,3,3,3,3,3,3,3,4,4,4,4],
    "マゴチ":   [1,1,1,2,4,5,5,5,4,2,1,1],
    "キンメダイ":[4,4,4,3,3,3,3,3,3,4,4,4],
    # 追加魚種
    "マルイカ": [2,3,4,5,5,3,1,1,1,1,1,2],  # 春（4〜5月）がピーク
    "クロムツ": [4,4,3,3,3,3,3,3,3,3,4,4],  # 通年・冬がやや好調
    "サワラ":   [1,1,2,4,5,3,2,2,4,5,4,2],  # 春（4〜5月）・秋（10月）
    "メダイ":   [4,5,5,4,3,2,1,1,1,2,3,4],  # 冬〜春（1〜4月）
    "マハタ":   [3,3,3,3,4,4,4,4,4,3,3,3],  # 夏〜秋がやや好調・通年
    "カンパチ": [1,1,1,2,3,4,5,5,4,3,2,1],  # 夏（7〜8月）がピーク
}
SEASON_TYPE = {
    "アジ":     ["数","数","数","数","型","型","型","数","数","数","数","数"],
    "タチウオ": ["数","数","数","数","数","数","型","型","数","数","数","数"],
    "マダイ":   ["数","数","型","型","型","数","数","数","数","型","型","数"],
    "シロギス": ["数","数","数","数","数","型","型","数","数","数","数","数"],
    "ヤリイカ": ["型","型","数","数","数","数","数","数","数","数","型","型"],
    "ヒラメ":   ["型","型","型","数","数","数","数","数","型","型","型","型"],
    "マルイカ": ["数","数","数","数","数","数","数","数","数","数","数","数"],
    "サワラ":   ["数","数","数","数","数","数","数","数","数","数","数","数"],
    "カンパチ": ["数","数","数","数","数","型","型","型","数","数","数","数"],
}

def get_season_score(fish, month):
    s = SEASON_DATA.get(fish, [])
    return s[month - 1] if s else 0

def build_season_bar(fish, current_month):
    scores = SEASON_DATA.get(fish, [3]*12)
    types  = SEASON_TYPE.get(fish, [""]*12)
    month_labels = ["1","2","3","4","5","6","7","8","9","10","11","12"]
    cells = ""
    for i, (sc, tp) in enumerate(zip(scores, types)):
        m = i + 1
        is_now = "now" if m == current_month else ""
        cls = ("peak-count" if tp == "数" else "peak-size") if sc >= 4 else ("mid" if sc == 3 else "low")
        cells += f'<div class="sb-cell {cls} {is_now}" title="{m}月">{month_labels[i]}</div>'
    label = ""
    if fish in SEASON_TYPE:
        label = '<div class="sb-legend"><span class="leg-count">■数狙い</span><span class="leg-size">■型狙い</span></div>'
    return f'<div class="season-bar">{cells}</div>{label}'

# ============================================================
# #5: 好調度コメント（件数・数値入り）
# ============================================================
def build_comment(fish, count, score, this_w, last_w, prev_w=None):
    base_comments = {
        5: ["爆釣モード！今すぐ行くべき", "今季最高潮。チャンスを逃すな"],
        4: ["かなり好調。おすすめの釣り物", "良型混じりで数も出ている"],
        3: ["コンスタントに釣れている", "安定した釣果が続いている"],
        2: ["やや渋め。腕の見せどころ", "数は出ないが型狙いも一手"],
        1: ["端境期。好転待ちの状況", "オフシーズン。次の季節に期待"],
    }
    base = base_comments.get(score, base_comments[3])[hash(fish) % 2]
    suffix = f"（今週{count}件"
    if this_w and last_w:
        t_val = this_w.get("avg") or 0
        l_val = last_w.get("avg") or 0
        if t_val and l_val:
            pct = round((t_val - l_val) / l_val * 100)
            sign = "+" if pct >= 0 else ""
            suffix += f"・昨年比{sign}{pct}%"
    if this_w and prev_w:
        t_s = this_w.get("ships") or 0
        p_s = prev_w.get("ships") or 0
        if t_s and p_s:
            pct2 = round((t_s - p_s) / p_s * 100)
            if abs(pct2) <= 150:  # データ不足による爆発を抑制
                sign2 = "+" if pct2 >= 0 else ""
                suffix += f"・先週比{sign2}{pct2}%"
    suffix += "）"
    return f"{base}{suffix}"

def composite_to_stars(score):
    """複合スコア(0-100) → ★1〜5"""
    n = max(1, min(5, round(score / 20)))
    return "★" * n + "☆" * (5 - n)

def build_reason_tags(fish, cnt, max_cnt, this_w, last_w, prev_w, cur_month):
    """おすすめ理由タグをリストで返す（最大3つ）"""
    tags = []
    season = get_season_score(fish, cur_month)
    if season >= 4:
        tags.append(("season", "🎣 旬"))
    if this_w and last_w:
        t_a = this_w.get("avg") or 0
        l_a = last_w.get("avg") or 0
        if l_a and t_a:
            ratio = t_a / l_a
            if ratio >= 1.2:
                tags.append(("up", "📈 昨年比UP"))
            elif ratio <= 0.7:
                tags.append(("down", "📉 昨年比DOWN"))
    if max_cnt > 0 and cnt / max_cnt >= 0.6:
        tags.append(("hot", "🔥 釣果多数"))
    return tags[:3]

# ============================================================
# #16: 釣り物予報
# ============================================================
def build_forecast(targets):
    if not targets: return ""
    top = targets[0]
    composite = top.get("composite", 50)
    fish = top["fish"]
    if composite >= 65:
        msg = f"今週の本命は<strong>{fish}</strong>。積極的に狙える状況です。"
    elif composite >= 50:
        msg = f"今週は<strong>{fish}</strong>がコンスタント。外さない一手です。"
    else:
        msg = f"今週は全体的に渋め。<strong>{fish}</strong>中心に様子を見ましょう。"
    high_ships = [t for t in targets if t.get("ships", 0) >= 10]
    if high_ships:
        msg += f' <span class="forecast-crowded">【混雑注意】{high_ships[0]["fish"]}は人気が高く船が混み合う可能性あり</span>'
    return f'<div class="forecast-bar">{msg}</div>'

# ============================================================
# CSS
# ============================================================
CSS = """
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Helvetica Neue',Arial,sans-serif;background:#0a1628;color:#e0e8f0}
header{background:#0d2137;padding:16px 24px;border-bottom:2px solid #1a6ea8}
header h1{font-size:22px;color:#4db8ff}
header p{font-size:12px;color:#7a9bb5;margin-top:4px}
header .site-desc{font-size:11px;color:#5a7a95;margin-top:6px;padding-top:6px;border-top:1px solid #1a3050;line-height:1.6}
nav{background:#081020;padding:8px 24px;display:flex;gap:16px;flex-wrap:wrap}
nav a{color:#7a9bb5;text-decoration:none;font-size:13px}
nav a:hover{color:#4db8ff}
.wrap{max-width:1100px;margin:0 auto;padding:20px 16px}
h2{font-size:15px;color:#4db8ff;border-left:4px solid #4db8ff;padding-left:10px;margin:24px 0 12px}
.forecast-bar{background:#0d2137;border-left:4px solid #e85d04;padding:10px 14px;border-radius:4px;font-size:13px;color:#c8d8e8;margin-bottom:16px;line-height:1.7}
.forecast-crowded{color:#f9c74f;font-size:12px}
.target-top{background:#0d2137;border:2px solid #4db8ff;border-radius:12px;padding:20px;margin-bottom:16px;display:flex;align-items:flex-start;gap:20px;cursor:pointer;transition:border-color .2s;text-decoration:none;color:inherit}
.target-top:hover{border-color:#80d8ff}
.target-top .tt-fish{font-size:28px;font-weight:bold;color:#fff;margin-bottom:6px}
.target-top .tt-badge{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:8px;align-items:center}
.target-top .tt-score{font-size:20px;color:#e85d04;letter-spacing:3px}
.target-top .tt-comment{font-size:13px;color:#c8d8e8;line-height:1.6}
.target-top .tt-label{font-size:10px;background:#1a3050;color:#7a9bb5;padding:2px 8px;border-radius:10px}
.target-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:10px}
.target-card{background:#0d2137;border:1px solid #1a4060;border-radius:8px;padding:12px;cursor:pointer;transition:border-color .2s;text-decoration:none;color:inherit;display:block}
.target-card:hover{border-color:#4db8ff}
.tc-fish{font-size:16px;font-weight:bold;color:#fff;margin-bottom:4px;display:flex;align-items:center;gap:6px;flex-wrap:wrap}
.tc-bar{font-size:14px;color:#e85d04;letter-spacing:2px;margin-bottom:4px}
.tc-comment{font-size:11px;color:#c8d8e8;line-height:1.5;margin-bottom:4px}
.tc-count{font-size:10px;color:#7a9bb5}
.yoy{font-size:11px;font-weight:bold;padding:2px 6px;border-radius:4px;white-space:nowrap}
.yoy.up{background:#0d3320;color:#4dcc88}
.yoy.down{background:#330d0d;color:#cc4d4d}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:10px}
.fc{background:#0d2137;border:1px solid #1a4060;border-radius:8px;padding:12px;transition:border-color .2s}
.fc:hover{border-color:#4db8ff}
.fc-summary{text-align:center}
.fn{font-size:15px;font-weight:bold;color:#fff}
.fk{font-size:12px;color:#4db8ff;margin-top:4px}
.fa{font-size:11px;color:#7a9bb5;margin-top:2px}
.fc-link{display:block;font-size:11px;color:#4db8ff;text-align:center;margin-top:8px;text-decoration:none}
.fc-link:hover{text-decoration:underline}
.fc-detail{margin-top:10px;border-top:1px solid #1a4060;padding-top:10px}
.season-bar{display:flex;gap:2px;margin-top:8px;justify-content:center;flex-wrap:wrap}
.sb-cell{min-width:20px;height:18px;border-radius:3px;font-size:10px;color:#fff;display:flex;align-items:center;justify-content:center;padding:0 2px}
.sb-cell.peak-count{background:#e85d04}.sb-cell.peak-size{background:#7209b7}
.sb-cell.mid{background:#1a6ea8}.sb-cell.low{background:#1a3050}
.sb-cell.now{outline:2px solid #fff;outline-offset:1px}
.sb-legend{font-size:9px;color:#7a9bb5;text-align:center;margin-top:3px}
.leg-count{color:#e85d04}.leg-size{color:#7209b7;margin-left:6px}
.tab-wrap{display:flex;gap:4px;margin-bottom:8px}
.tab-btn{background:#081020;border:1px solid #1a4060;color:#7a9bb5;padding:4px 10px;border-radius:4px;cursor:pointer;font-size:12px}
.tab-btn.active{background:#1a6ea8;color:#fff;border-color:#1a6ea8}
.rank-table{width:100%;border-collapse:collapse;font-size:12px}
.rank-table th{background:#081020;color:#4db8ff;padding:5px;text-align:left}
.rank-table td{padding:5px;border-bottom:1px solid #081020}
.bar-wrap{background:#081020;border-radius:2px;height:8px;width:80px}
.bar-fill{background:#1a6ea8;height:8px;border-radius:2px}
.ships-badge{font-size:10px;background:#1a3050;color:#7a9bb5;padding:1px 6px;border-radius:8px;margin-left:4px}
table{width:100%;border-collapse:collapse;font-size:13px}
th{background:#0d2137;color:#4db8ff;padding:8px;text-align:left;border-bottom:1px solid #1a4060}
td{padding:8px;border-bottom:1px solid #0d2137}
tr:hover td{background:#0d2137}
tr.highlight td{background:#1a2d10;color:#7ddd6f}
.filter-bar{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px}
.filter-btn{background:#081020;border:1px solid #1a4060;color:#7a9bb5;padding:4px 12px;border-radius:16px;cursor:pointer;font-size:12px;transition:all .2s}
.filter-btn.active{background:#1a6ea8;color:#fff;border-color:#1a6ea8}
.note{font-size:11px;color:#7a9bb5;text-align:right;margin-top:8px}
.yoy-table{width:100%;border-collapse:collapse;font-size:12px;margin-top:8px}
.yoy-table th{background:#081020;color:#4db8ff;padding:5px;text-align:left}
.yoy-table td{padding:5px;border-bottom:1px solid #081020}
.yoy-table .up{color:#4dcc88}.yoy-table .down{color:#cc4d4d}
.area-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:10px;margin-bottom:16px}
.area-card{background:#0d2137;border:1px solid #1a4060;border-radius:8px;padding:14px;text-decoration:none;color:inherit;display:block;transition:border-color .2s}
.area-card:hover{border-color:#4db8ff}
.area-name{font-size:15px;font-weight:bold;color:#4db8ff;margin-bottom:6px}
.area-fish{font-size:12px;color:#c8d8e8;line-height:1.8}
.area-ships{font-size:11px;color:#7a9bb5;margin-top:4px}
footer{background:#081020;border-top:1px solid #1a3050;padding:20px 24px;text-align:center;font-size:12px;color:#7a9bb5;margin-top:40px}
footer a{color:#4db8ff;text-decoration:none}
footer a:hover{text-decoration:underline}
.tt-header{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:10px}
.tt-name-row{display:flex;align-items:baseline;gap:12px;margin-bottom:8px}
.tt-fish{font-size:28px;font-weight:bold;color:#fff}
.tt-stars{font-size:18px;color:#f9c74f;letter-spacing:2px}
.tt-tags{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:10px}
.tt-comment{font-size:13px;color:#c8d8e8;line-height:1.6}
.tt-meta{font-size:11px;color:#7a9bb5;margin-top:8px}
.rtag{font-size:11px;padding:3px 8px;border-radius:12px;font-weight:bold}
.rtag-up{background:#0d3320;color:#4dcc88;border:1px solid #1a5535}
.rtag-down{background:#330d0d;color:#cc4d4d;border:1px solid #551a1a}
.tc-name-row{display:flex;align-items:baseline;gap:8px;margin-bottom:4px}
.tc-fish-name{font-size:16px;font-weight:bold;color:#fff}
.tc-stars{font-size:13px;color:#f9c74f}
.tc-tags{display:flex;gap:4px;flex-wrap:wrap;margin-bottom:6px}
"""

# ============================================================
# #7: 今週イチ押し + #1: リンク付きカード
# ============================================================
def calc_targets(data, history):
    now = datetime.now()
    cur_month = now.month
    year, week_num = current_iso_week()
    fish_counts = {}
    ship_counts_per_fish = {}
    for c in data:
        for f in c["fish"]:
            if f != "不明":
                fish_counts[f] = fish_counts.get(f, 0) + 1
                ship_counts_per_fish.setdefault(f, set()).add(c["ship"])
    max_cnt = max(fish_counts.values()) if fish_counts else 1
    targets = []
    for fish, cnt in fish_counts.items():
        score    = get_season_score(fish, cur_month)
        this_w, last_w = get_yoy_data(history, fish, year, week_num)
        prev_w   = get_prev_week_data(history, fish, year, week_num)
        badge    = yoy_badge(this_w, last_w)
        comment  = build_comment(fish, cnt, score, this_w, last_w, prev_w)
        ships    = len(ship_counts_per_fish.get(fish, set()))
        composite = calc_composite_score(fish, cnt, max_cnt, this_w, last_w, prev_w, cur_month)
        stars    = composite_to_stars(composite)
        tags     = build_reason_tags(fish, cnt, max_cnt, this_w, last_w, prev_w, cur_month)
        targets.append({"fish": fish, "count": cnt, "score": score, "composite": composite,
                        "comment": comment, "badge": badge, "ships": ships,
                        "stars": stars, "tags": tags})
    targets.sort(key=lambda x: -x["composite"])
    return targets[:5]

def _render_tags(tags):
    html = ""
    for kind, label in tags:
        cls = "rtag-up" if kind in ("up","up2","season","hot") else "rtag-down"
        html += f'<span class="rtag {cls}">{label}</span>'
    return html

def build_target_section(targets):
    if not targets:
        return "<p style='color:#7a9bb5'>データ収集中です。しばらくお待ちください。</p>"
    top = targets[0]
    tags_html = _render_tags(top.get("tags", []))
    top_html = f"""
    <a class="target-top" href="fish/{top['fish']}.html">
      <div style="flex:1">
        <div class="tt-header">
          <span class="tt-label">今週イチ押し</span>
          {top['badge']}
        </div>
        <div class="tt-name-row">
          <span class="tt-fish">{top['fish']}</span>
          <span class="tt-stars">{top['stars']}</span>
        </div>
        <div class="tt-tags">{tags_html}</div>
        <div class="tt-comment">{top['comment']}</div>
        <div class="tt-meta">出船: 約{top['ships']}隻 ／ 直近釣果: {top['count']}件</div>
      </div>
    </a>"""
    rest_html = ""
    for t in targets[1:]:
        t_tags = _render_tags(t.get("tags", []))
        rest_html += f"""
    <a class="target-card" href="fish/{t['fish']}.html">
      <div class="tc-name-row">
        <span class="tc-fish-name">{t['fish']}</span>
        <span class="tc-stars">{t['stars']}</span>
      </div>
      <div class="tc-tags">{t_tags}</div>
      <div class="tc-comment">{t['comment']}</div>
      <div class="tc-count">出船約{t['ships']}隻 ／ {t['count']}件</div>
    </a>"""
    return top_html + f'<div class="target-grid">{rest_html}</div>'

# ============================================================
# #4: 釣果テーブル用HTML（エリアフィルター + 最高釣果ハイライト）
# ============================================================
def build_catch_table(catches):
    areas = sorted(set(c["area"] for c in catches))
    filter_btns = '<button class="filter-btn active" onclick="filterArea(this,\'all\')">すべて</button>'
    for a in areas:
        filter_btns += f'<button class="filter-btn" onclick="filterArea(this,\'{a}\')">{a}</button>'
    rows = ""
    max_count = 0
    for c in catches[:20]:
        if c["count_range"]: max_count = max(max_count, c["count_range"]["max"])
    for c in catches[:20]:
        cnt = ""
        is_top = False
        if c["count_range"]:
            mn, mx = c["count_range"]["min"], c["count_range"]["max"]
            cnt = f"{mn}〜{mx}" if mn != mx else str(mn)
            if mx == max_count and max_count > 0: is_top = True
        sz = ""
        if c["size_range"]:
            mn, mx, unit = c["size_range"]["min"], c["size_range"]["max"], c["size_range"].get("unit","cm")
            sz = f"{mn}〜{mx}{unit}" if mn != mx else f"{mn}{unit}"
        hl = ' class="highlight"' if is_top else ""
        rows += f'<tr{hl} data-area="{c["area"]}"><td>{c["date"] or "-"}</td><td>{c["area"]}</td><td>{c["ship"]}</td><td>{"・".join(c["fish"])}</td><td>{cnt}</td><td>{sz}</td></tr>'
    return f"""
    <div class="filter-bar">{filter_btns}</div>
    <table id="catch-table">
      <tr><th>日付</th><th>エリア</th><th>船宿</th><th>魚種</th><th>数量</th><th>サイズ</th></tr>
      {rows}
    </table>"""

# ============================================================
# index.html 生成
# ============================================================
def build_html(catches, crawled_at, history):
    now = datetime.now()
    current_month = now.month
    fish_summary = {}
    for c in catches:
        for f in c["fish"]:
            if f != "不明":
                fish_summary.setdefault(f, []).append(c)
    areas = sorted(set(c["area"] for c in catches))
    cards = ""
    for fish, cs in sorted(fish_summary.items(), key=lambda x: -len(x[1])):
        areas_list  = list(dict.fromkeys(c["area"] for c in cs[:3]))
        season_bar  = build_season_bar(fish, current_month)
        fish_id     = re.sub(r'[^\w]', '_', fish)
        ship_counts = {}
        for c in cs: ship_counts[c["ship"]] = ship_counts.get(c["ship"], 0) + 1
        daily_rows = ""
        for c in sorted(cs, key=lambda x: x["date"] or "", reverse=True)[:5]:
            cnt = f"{c['count_range']['min']}〜{c['count_range']['max']}" if c["count_range"] and c["count_range"]["min"] != c["count_range"]["max"] else (str(c["count_range"]["min"]) if c["count_range"] else "")
            sz  = ""
            if c["size_range"]:
                mn,mx,unit = c["size_range"]["min"],c["size_range"]["max"],c["size_range"].get("unit","cm")
                sz = f"{mn}〜{mx}{unit}" if mn != mx else f"{mn}{unit}"
            daily_rows += f"<tr><td>{c['date'] or '-'}</td><td>{c['area']}</td><td>{c['ship']}</td><td>{cnt}</td><td>{sz}</td></tr>"
        weekly_rows = ""
        for sn, cnt in sorted(ship_counts.items(), key=lambda x:-x[1])[:10]:
            pct = int(cnt / len(cs) * 100) if cs else 0
            weekly_rows += f'<tr><td>{sn}</td><td>{cnt}件</td><td><div class="bar-wrap"><div class="bar-fill" style="width:{pct}%"></div></div></td></tr>'
        ship_num   = len(ship_counts)
        ships_html = f'<span class="ships-badge">約{ship_num}隻</span>'
        cards += f"""
    <div class="fc">
      <div class="fc-summary">
        <div class="fn">{fish}{ships_html}</div>
        <div class="fk">{len(cs)}件</div>
        <div class="fa">{" / ".join(areas_list)}</div>
        {season_bar}
      </div>
      <a class="fc-link" href="fish/{fish}.html">詳細・船宿ランキング →</a>
      <div class="fc-detail" style="display:none" id="detail-{fish_id}">
        <div class="tab-wrap">
          <button class="tab-btn active" onclick="switchTab(event,'daily-{fish_id}','weekly-{fish_id}')">デイリー</button>
          <button class="tab-btn" onclick="switchTab(event,'weekly-{fish_id}','daily-{fish_id}')">ウィークリー</button>
        </div>
        <div id="daily-{fish_id}"><table class="rank-table"><tr><th>日付</th><th>エリア</th><th>船宿</th><th>数量</th><th>サイズ</th></tr>{daily_rows or '<tr><td colspan=5 style="color:#7a9bb5">データなし</td></tr>'}</table></div>
        <div id="weekly-{fish_id}" style="display:none"><table class="rank-table"><tr><th>船宿</th><th>釣果数</th><th>割合</th></tr>{weekly_rows or '<tr><td colspan=3 style="color:#7a9bb5">データなし</td></tr>'}</table></div>
      </div>
    </div>"""
    targets      = calc_targets(catches, history)
    target_html  = build_target_section(targets)
    forecast     = build_forecast(targets)
    catch_table  = build_catch_table(catches)
    area_nav     = " ".join(f'<a href="area/{a}.html">{a}</a>' for a in sorted(set(c["area"] for c in catches)))
    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
  <meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
  <title>関東船釣り釣果情報 | 今日何が釣れてる？</title>
  <meta name="description" content="関東エリア（神奈川・千葉）の船宿釣果をリアルタイム集計。今週の狙い目魚種、釣れている船宿ランキングを毎日更新。">
  {ADSENSE_TAG}
  <style>{CSS}</style>
</head>
<body>
<header>
  <h1>🎣 関東船釣り釣果情報</h1>
  <p>今日、何が釣れてる？ 関東エリアの船宿釣果をリアルタイム集計</p>
  <p class="site-desc">神奈川・千葉・静岡の船宿26軒の釣果を毎日自動収集。魚種・エリア・船宿を横断比較して「今週どこへ行くか」の意思決定をサポートします。</p>
</header>
<nav>
  <a href="index.html">🏠 トップ</a>
  <a href="calendar.html">📅 釣りものカレンダー</a>
  <span style="color:#1a4060">|</span>
  <span style="color:#7a9bb5;font-size:12px">エリアから探す：</span> {area_nav}
</nav>
<div class="wrap">
  <h2>🎯 今週の狙い目</h2>
  {forecast}
  {target_html}
  <h2>🐟 釣れている魚</h2>
  <p style="font-size:12px;color:#7a9bb5;margin-bottom:10px">タップで詳細表示 ／ 各カードの「詳細→」で船宿ランキングを確認</p>
  <div class="grid">{cards}</div>
  <h2>📋 最新の釣果</h2>
  {catch_table}
  <p class="note">最終更新: {crawled_at} ／ 総件数: {len(catches)} 件</p>
</div>
<footer>
  <p><a href="contact.html">お問い合わせ</a> | <a href="privacy.html">プライバシーポリシー</a></p>
  <p style="margin-top:8px">© 2026 船釣り予想. All rights reserved.</p>
</footer>
<script>
function filterArea(btn, area) {{
  document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  document.querySelectorAll('#catch-table tr[data-area]').forEach(tr => {{
    tr.style.display = (area === 'all' || tr.dataset.area === area) ? '' : 'none';
  }});
}}
function switchTab(e, showId, hideId) {{
  e.stopPropagation();
  document.getElementById(showId).style.display = 'block';
  document.getElementById(hideId).style.display = 'none';
  const w = e.target.closest('.tab-wrap');
  w.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  e.target.classList.add('active');
}}
document.querySelectorAll('.fc').forEach(el => {{
  el.addEventListener('click', function(e) {{
    if (e.target.classList.contains('fc-link') || e.target.closest('.fc-link')) return;
    const d = this.querySelector('.fc-detail');
    if (d) d.style.display = d.style.display === 'none' ? 'block' : 'none';
  }});
}});
</script>
</body>
</html>"""

# ============================================================
# #6: 魚種別ページ
# ============================================================
def build_fish_pages(data, history):
    os.makedirs("fish", exist_ok=True)
    now = datetime.now()
    current_month = now.month
    year, week_num = current_iso_week()
    fish_summary = {}
    for c in data:
        for f in c["fish"]:
            if f != "不明": fish_summary.setdefault(f, []).append(c)
    for fish, catches in fish_summary.items():
        if len(catches) < 3: continue
        season_bar_html = build_season_bar(fish, current_month)
        score   = get_season_score(fish, current_month)
        this_w, last_w = get_yoy_data(history, fish, year, week_num)
        comment = build_comment(fish, len(catches), score, this_w, last_w)
        rows = ""
        max_cnt = 0
        for c in catches:
            if c["count_range"]: max_cnt = max(max_cnt, c["count_range"]["max"])
        for c in sorted(catches, key=lambda x: x["date"] or "", reverse=True)[:20]:
            cnt = f"{c['count_range']['min']}〜{c['count_range']['max']}" if c["count_range"] and c["count_range"]["min"] != c["count_range"]["max"] else (str(c["count_range"]["min"]) if c["count_range"] else "")
            sz  = ""
            if c["size_range"]:
                mn,mx,unit = c["size_range"]["min"],c["size_range"]["max"],c["size_range"].get("unit","cm")
                sz = f"{mn}〜{mx}{unit}" if mn != mx else f"{mn}{unit}"
            is_top = c["count_range"] and c["count_range"]["max"] == max_cnt and max_cnt > 0
            hl = ' class="highlight"' if is_top else ""
            rows += f"<tr{hl}><td>{c['date'] or '-'}</td><td>{c['area']}</td><td>{c['ship']}</td><td>{cnt}</td><td>{sz}</td></tr>"
        ship_counts = {}
        ship_max    = {}
        for c in catches:
            ship_counts[c["ship"]] = ship_counts.get(c["ship"], 0) + 1
            if c["count_range"]:
                ship_max[c["ship"]] = max(ship_max.get(c["ship"], 0), c["count_range"]["max"])
        rank_rows = ""
        for i, (sn, cnt) in enumerate(sorted(ship_counts.items(), key=lambda x:-x[1])[:10], 1):
            mx   = ship_max.get(sn, 0)
            area = next((c["area"] for c in catches if c["ship"] == sn), "")
            pct  = int(cnt / len(catches) * 100) if catches else 0
            rank_rows += f"""<tr>
  <td style="color:#4db8ff;font-weight:bold;width:24px">{i}</td>
  <td><strong>{sn}</strong><br><span style="font-size:11px;color:#7a9bb5">{area}</span></td>
  <td style="color:#4dcc88">{cnt}件</td>
  <td style="color:#e85d04">最高{mx}匹</td>
  <td><div class="bar-wrap"><div class="bar-fill" style="width:{pct}%"></div></div></td>
</tr>"""
        areas_this = list(dict.fromkeys(c["area"] for c in catches))
        area_links = " / ".join(f'<a href="../area/{a}.html" style="color:#4db8ff;font-size:12px">{a}</a>' for a in areas_this[:5])
        yoy_html = ""
        if this_w and last_w:
            def fmt(v, unit=""): return f"{v}{unit}" if v else "-"
            def diff_cell(t_val, l_val):
                if not t_val or not l_val: return "<td>-</td>"
                pct = round((t_val - l_val) / l_val * 100)
                cls  = "up" if pct >= 0 else "down"
                sign = "+" if pct >= 0 else ""
                return f'<td class="{cls}">{sign}{pct}%</td>'
            yoy_html = f"""
  <h2>📊 昨年同週との比較（第{week_num}週）</h2>
  <table class="yoy-table">
    <tr><th></th><th>今週 ({year}/W{week_num:02d})</th><th>昨年同週 ({year-1}/W{week_num:02d})</th><th>昨年比</th></tr>
    <tr><td>平均釣果</td><td>{fmt(this_w.get("avg"),"匹")}</td><td>{fmt(last_w.get("avg"),"匹")}</td>{diff_cell(this_w.get("avg"),last_w.get("avg"))}</tr>
    <tr><td>最高釣果</td><td>{fmt(this_w.get("max"),"匹")}</td><td>{fmt(last_w.get("max"),"匹")}</td>{diff_cell(this_w.get("max"),last_w.get("max"))}</tr>
    <tr><td>平均サイズ</td><td>{fmt(this_w.get("size_avg"),"cm")}</td><td>{fmt(last_w.get("size_avg"),"cm")}</td>{diff_cell(this_w.get("size_avg"),last_w.get("size_avg"))}</tr>
    <tr><td>出船数</td><td>{fmt(this_w.get("ships"),"隻")}</td><td>{fmt(last_w.get("ships"),"隻")}</td>{diff_cell(this_w.get("ships"),last_w.get("ships"))}</tr>
  </table>"""
        fish_css = "*{box-sizing:border-box;margin:0;padding:0}body{font-family:'Helvetica Neue',Arial,sans-serif;background:#0a1628;color:#e0e8f0}header{background:#0d2137;padding:16px 24px;border-bottom:2px solid #1a6ea8}header h1{font-size:20px;color:#4db8ff}nav{background:#081020;padding:8px 24px;display:flex;gap:12px;flex-wrap:wrap}nav a{color:#7a9bb5;text-decoration:none;font-size:13px}nav a:hover{color:#4db8ff}.wrap{max-width:900px;margin:0 auto;padding:20px 16px}h2{font-size:15px;color:#4db8ff;border-left:4px solid #4db8ff;padding-left:10px;margin:24px 0 12px}.season-bar{display:flex;gap:2px;margin:12px 0;flex-wrap:wrap}.sb-cell{min-width:20px;height:18px;border-radius:3px;font-size:10px;color:#fff;display:flex;align-items:center;justify-content:center;padding:0 2px}.sb-cell.peak-count{background:#e85d04}.sb-cell.peak-size{background:#7209b7}.sb-cell.mid{background:#1a6ea8}.sb-cell.low{background:#1a3050}.sb-cell.now{outline:2px solid #fff;outline-offset:1px}.comment{background:#0d2137;border-left:3px solid #e85d04;padding:12px;border-radius:4px;font-size:14px;margin-bottom:16px}table{width:100%;border-collapse:collapse;font-size:13px}th{background:#0d2137;color:#4db8ff;padding:8px;text-align:left}td{padding:8px;border-bottom:1px solid #0d2137}tr.highlight td{background:#1a2d10;color:#7ddd6f}.bar-wrap{background:#081020;border-radius:2px;height:8px;width:80px}.bar-fill{background:#1a6ea8;height:8px;border-radius:2px}.yoy-table .up{color:#4dcc88}.yoy-table .down{color:#cc4d4d}footer{background:#081020;border-top:1px solid #1a3050;padding:20px;text-align:center;font-size:12px;color:#7a9bb5;margin-top:40px}footer a{color:#4db8ff;text-decoration:none}"
        html = f"""<!DOCTYPE html>
<html lang="ja"><head>
  <meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
  <title>{fish}の釣果情報 | 関東船釣り予想</title>
  <meta name="description" content="関東エリアの{fish}釣果情報。今週の釣れ具合・船宿ランキングをリアルタイム集計。">
  {ADSENSE_TAG}
  <style>{fish_css}</style>
</head><body>
<header><h1>🎣 {fish}の釣果情報</h1></header>
<nav>
  <a href="../index.html">← トップへ戻る</a>
  <span style="color:#1a4060">|</span>
  <span style="font-size:12px;color:#7a9bb5">釣れているエリア：</span>{area_links}
</nav>
<div class="wrap">
  <h2>📅 年間シーズン</h2>{season_bar_html}
  <div class="comment">💬 {comment}</div>
  {yoy_html}
  <h2>🏆 船宿ランキング（今週）</h2>
  <table><tr><th>#</th><th>船宿</th><th>釣果件数</th><th>最高釣果</th><th>割合</th></tr>{rank_rows}</table>
  <h2>📋 最近の釣果 ({len(catches)}件)</h2>
  <table><tr><th>日付</th><th>エリア</th><th>船宿</th><th>数量</th><th>サイズ</th></tr>{rows}</table>
</div>
<footer>
  <p><a href="../contact.html">お問い合わせ</a> | <a href="../privacy.html">プライバシーポリシー</a></p>
  <p style="margin-top:8px">© 2026 船釣り予想. All rights reserved.</p>
</footer>
</body></html>"""
        with open(f"fish/{fish}.html", "w", encoding="utf-8") as f:
            f.write(html)

# ============================================================
# #10: エリア別ページ
# ============================================================
def build_area_pages(data, history):
    os.makedirs("area", exist_ok=True)
    now = datetime.now()
    current_month = now.month
    year, week_num = current_iso_week()
    area_summary = {}
    for c in data:
        area_summary.setdefault(c["area"], []).append(c)
    for area, catches in area_summary.items():
        if len(catches) < 2: continue
        fish_counts = {}
        ship_counts = {}
        for c in catches:
            for f in c["fish"]:
                if f != "不明": fish_counts[f] = fish_counts.get(f, 0) + 1
            ship_counts[c["ship"]] = ship_counts.get(c["ship"], 0) + 1
        top_fish   = sorted(fish_counts.items(), key=lambda x:-x[1])[:5]
        fish_cards = ""
        for fish, cnt in top_fish:
            score = get_season_score(fish, current_month)
            score_bar = "█" * score + "░" * (5 - score)
            fish_cards += f"""
    <a href="../fish/{fish}.html" style="background:#0d2137;border:1px solid #1a4060;border-radius:8px;padding:12px;text-decoration:none;color:inherit;display:block;transition:border-color .2s">
      <div style="font-size:16px;font-weight:bold;color:#fff;margin-bottom:4px">{fish}</div>
      <div style="font-size:13px;color:#e85d04;letter-spacing:2px;margin-bottom:4px">{score_bar}</div>
      <div style="font-size:12px;color:#7a9bb5">今週{cnt}件</div>
    </a>"""
        ship_rows = ""
        for i, (sn, cnt) in enumerate(sorted(ship_counts.items(), key=lambda x:-x[1])[:8], 1):
            ship_fish = {}
            for c in catches:
                if c["ship"] == sn:
                    for f in c["fish"]:
                        if f != "不明": ship_fish[f] = ship_fish.get(f, 0) + 1
            top_f    = sorted(ship_fish.items(), key=lambda x:-x[1])[:2]
            fish_str = "・".join(f for f,_ in top_f)
            pct      = int(cnt / len(catches) * 100) if catches else 0
            ship_rows += f'<tr><td style="color:#4db8ff;font-weight:bold">{i}</td><td><strong>{sn}</strong><br><span style="font-size:11px;color:#7a9bb5">{fish_str}</span></td><td style="color:#4dcc88">{cnt}件</td><td><div style="background:#081020;border-radius:2px;height:8px;width:80px"><div style="background:#1a6ea8;height:8px;border-radius:2px;width:{pct}%"></div></div></td></tr>'
        rows = ""
        for c in sorted(catches, key=lambda x: x["date"] or "", reverse=True)[:15]:
            cnt_str = f"{c['count_range']['min']}〜{c['count_range']['max']}" if c["count_range"] and c["count_range"]["min"] != c["count_range"]["max"] else (str(c["count_range"]["min"]) if c["count_range"] else "")
            sz = ""
            if c["size_range"]:
                mn,mx,unit = c["size_range"]["min"],c["size_range"]["max"],c["size_range"].get("unit","cm")
                sz = f"{mn}〜{mx}{unit}" if mn != mx else f"{mn}{unit}"
            rows += f"<tr><td>{c['date'] or '-'}</td><td>{c['ship']}</td><td>{'・'.join(c['fish'])}</td><td>{cnt_str}</td><td>{sz}</td></tr>"
        group   = next((g for g, areas in AREA_GROUPS.items() if area in areas), "関東")
        area_css = "*{box-sizing:border-box;margin:0;padding:0}body{font-family:'Helvetica Neue',Arial,sans-serif;background:#0a1628;color:#e0e8f0}header{background:#0d2137;padding:16px 24px;border-bottom:2px solid #1a6ea8}header h1{font-size:20px;color:#4db8ff}header p{font-size:12px;color:#7a9bb5;margin-top:4px}nav{background:#081020;padding:8px 24px}nav a{color:#7a9bb5;text-decoration:none;font-size:13px}nav a:hover{color:#4db8ff}.wrap{max-width:900px;margin:0 auto;padding:20px 16px}h2{font-size:15px;color:#4db8ff;border-left:4px solid #4db8ff;padding-left:10px;margin:24px 0 12px}.fish-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(140px,1fr));gap:10px;margin-bottom:8px}.fish-grid a:hover{border-color:#4db8ff!important}table{width:100%;border-collapse:collapse;font-size:13px}th{background:#0d2137;color:#4db8ff;padding:8px;text-align:left}td{padding:8px;border-bottom:1px solid #0d2137}footer{background:#081020;border-top:1px solid #1a3050;padding:20px;text-align:center;font-size:12px;color:#7a9bb5;margin-top:40px}footer a{color:#4db8ff;text-decoration:none}"
        html = f"""<!DOCTYPE html>
<html lang="ja"><head>
  <meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
  <title>{area}の釣果情報 | 関東船釣り予想</title>
  <meta name="description" content="{area}エリアの船釣り釣果情報。今週釣れている魚種・船宿ランキングを毎日更新。">
  {ADSENSE_TAG}
  <style>{area_css}</style>
</head><body>
<header>
  <h1>🚢 {area}の釣果情報</h1>
  <p>{group} ／ 今週の釣果: {len(catches)}件</p>
</header>
<nav><a href="../index.html">← トップへ戻る</a></nav>
<div class="wrap">
  <h2>🐟 今週釣れている魚</h2>
  <div class="fish-grid">{fish_cards}</div>
  <h2>🏆 船宿ランキング（今週）</h2>
  <table><tr><th>#</th><th>船宿</th><th>釣果数</th><th>割合</th></tr>{ship_rows}</table>
  <h2>📋 最新の釣果</h2>
  <table><tr><th>日付</th><th>船宿</th><th>魚種</th><th>数量</th><th>サイズ</th></tr>{rows}</table>
</div>
<footer>
  <p><a href="../contact.html">お問い合わせ</a> | <a href="../privacy.html">プライバシーポリシー</a></p>
  <p style="margin-top:8px">© 2026 船釣り予想. All rights reserved.</p>
</footer>
</body></html>"""
        with open(f"area/{area}.html", "w", encoding="utf-8") as f:
            f.write(html)

# ============================================================
# calendar.html
# ============================================================
def build_calendar_page():
    now = datetime.now()
    current_month = now.month
    months = ["1月","2月","3月","4月","5月","6月","7月","8月","9月","10月","11月","12月"]
    header_cells = "".join(f'<th class="{"cur-month" if i+1==current_month else ""}">{m}</th>' for i,m in enumerate(months))
    rows = ""
    for fish, scores in SEASON_DATA.items():
        types = SEASON_TYPE.get(fish, [""]*12)
        cells = ""
        for i, (sc, tp) in enumerate(zip(scores, types)):
            m      = i + 1
            is_now = "cur-month" if m == current_month else ""
            cls    = ("peak-count" if tp == "数" else "peak-size") if sc >= 4 else ("mid" if sc == 3 else "low")
            label  = "◎" if sc >= 4 else ("○" if sc == 3 else "-")
            cells += f'<td class="{cls} {is_now}">{label}</td>'
        rows += f"<tr><td class='fish-name'><a href='fish/{fish}.html'>{fish}</a></td>{cells}</tr>"
    return f"""<!DOCTYPE html>
<html lang="ja"><head>
  <meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
  <title>関東船釣り カレンダー | 月別釣りものガイド</title>
  {ADSENSE_TAG}
  <style>*{{box-sizing:border-box;margin:0;padding:0}}body{{font-family:'Helvetica Neue',Arial,sans-serif;background:#0a1628;color:#e0e8f0}}header{{background:#0d2137;padding:16px 24px;border-bottom:2px solid #1a6ea8}}header h1{{font-size:20px;color:#4db8ff}}nav{{background:#081020;padding:8px 24px}}nav a{{color:#7a9bb5;text-decoration:none;font-size:13px}}.wrap{{max-width:900px;margin:0 auto;padding:20px 16px;overflow-x:auto}}h2{{font-size:15px;color:#4db8ff;border-left:4px solid #4db8ff;padding-left:10px;margin:24px 0 12px}}table{{border-collapse:collapse;font-size:13px;width:100%}}th{{background:#0d2137;color:#4db8ff;padding:8px 6px;text-align:center;min-width:36px}}th.cur-month{{background:#1a6ea8;color:#fff}}td{{padding:6px;text-align:center;border-bottom:1px solid #081020}}td.fish-name{{text-align:left;font-weight:bold;min-width:90px}}td.fish-name a{{color:#e0e8f0;text-decoration:none}}td.fish-name a:hover{{color:#4db8ff}}td.peak-count{{background:#e85d04;color:#fff}}td.peak-size{{background:#7209b7;color:#fff}}td.mid{{background:#1a6ea8;color:#fff}}td.low{{background:#0d2137;color:#444}}td.cur-month{{outline:2px solid #fff;outline-offset:-2px}}.legend{{display:flex;gap:16px;margin:16px 0;font-size:12px}}.leg{{display:flex;align-items:center;gap:6px}}.leg-dot{{width:14px;height:14px;border-radius:2px}}footer{{background:#081020;border-top:1px solid #1a3050;padding:20px;text-align:center;font-size:12px;color:#7a9bb5;margin-top:40px}}footer a{{color:#4db8ff;text-decoration:none}}</style>
</head><body>
<header><h1>📅 釣りものカレンダー</h1></header>
<nav><a href="index.html">← トップへ戻る</a></nav>
<div class="wrap">
  <h2>月別 釣りものガイド</h2>
  <div class="legend">
    <div class="leg"><div class="leg-dot" style="background:#e85d04"></div>数狙いピーク◎</div>
    <div class="leg"><div class="leg-dot" style="background:#7209b7"></div>型狙いピーク◎</div>
    <div class="leg"><div class="leg-dot" style="background:#1a6ea8"></div>シーズン中○</div>
    <div class="leg"><div class="leg-dot" style="background:#0d2137;border:1px solid #333"></div>端境期</div>
  </div>
  <table><tr><th>魚種</th>{header_cells}</tr>{rows}</table>
</div>
<footer>
  <p><a href="contact.html">お問い合わせ</a> | <a href="privacy.html">プライバシーポリシー</a></p>
  <p style="margin-top:8px">© 2026 船釣り予想. All rights reserved.</p>
</footer>
</body></html>"""

# ============================================================
# メイン
# ============================================================
def main():
    all_catches = []
    errors = []
    now = datetime.now()
    crawled_at = now.strftime("%Y/%m/%d %H:%M")
    year = now.year
    print(f"=== 関東船釣りクローラー v5.1 開始: {crawled_at} ===")
    print(f"対象: {len(SHIPS)} 船宿\n")
    for s in SHIPS:
        url = BASE_URL.format(sid=s["sid"])
        print(f"  [{s['area']}] {s['name']} ...", end=" ", flush=True)
        html = fetch(url)
        if not html:
            errors.append(s["name"]); print("エラー"); continue
        # v5.1: parse_catches_from_html で正しい日付を取得
        catches = parse_catches_from_html(html, s["name"], s["area"], year)
        print(f"{len(catches)} 件")
        all_catches.extend(catches)
        time.sleep(0.8)
    history = load_history()
    history = update_history(all_catches, history)
    with open("catches.json", "w", encoding="utf-8") as f:
        json.dump({"crawled_at": crawled_at, "total": len(all_catches), "errors": errors, "data": all_catches}, f, ensure_ascii=False, indent=2)
    with open("index.html", "w", encoding="utf-8") as f:
        f.write(build_html(all_catches, crawled_at, history))
    build_fish_pages(all_catches, history)
    build_area_pages(all_catches, history)
    with open("calendar.html", "w", encoding="utf-8") as f:
        f.write(build_calendar_page())
    print(f"\n=== 完了 ===")
    print(f"釣果: {len(all_catches)} 件 ／ エラー: {errors or 'なし'}")
    print(f"出力: catches.json / index.html / fish/*.html / area/*.html / calendar.html")

if __name__ == "__main__":
    main()
