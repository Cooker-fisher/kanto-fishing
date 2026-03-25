#!/usr/bin/env python3
"""
関東船釣り情報クローラー v5.7
変更点(v5.7):
- point列を point_place / point_depth に分割（「水深」を区切りに前後を分割）
- count_avg フィールドを追加（count_range の min/max 平均）
- CSV_HEADER を更新（point→point_place/point_depth/cnt_avg）
変更点(v5.6):
- SEO改善: fish・areaページのtitle/H1に検索キーワードと件数を明記
- SEO改善: canonical / OGP / BreadcrumbList schema を全ページに追加
- SEO改善: 内部リンク強化（fish→関連魚種 / area→近隣港）
- SITE_URL定数を追加
変更点(v5.3):
- データ品質改善: 船中フラグ検出・kg/cm分離・異常値バリデーション・重複排除
変更点(v5.2):
- Google AdSense コードを全ページの<head>に追加
変更点(v5.1):
- parse_catches_from_tables を廃止
- parse_catches_from_html に置き換え
  → choka_box 単位で li.date から正しい出船日を取得
  → 全釣果に「今日の日付」が入る問題を修正
"""
import re, json, time, os, csv
from datetime import datetime, timedelta
from urllib.request import urlopen, Request
from urllib.error import URLError
from urllib.parse import quote
from html.parser import HTMLParser

SHIPS = [
    # ── 茨城 ──────────────────────────────────
    {"area": "日立久慈港",         "name": "日正丸",              "sid": 11},
    {"area": "日立久慈港",         "name": "大貫丸",              "sid": 12},
    {"area": "日立久慈港",         "name": "宮田丸",              "sid": 13},
    {"area": "日立久慈港",         "name": "弘漁丸",              "sid": 18},
    {"area": "日立久慈港",         "name": "豊丸",                "sid": 1441},
    {"area": "日立久慈港",         "name": "明進丸",              "sid": 11837},
    {"area": "波崎港",             "name": "信栄丸",              "sid": 35},
    {"area": "波崎港",             "name": "仁徳丸",              "sid": 36},
    {"area": "鹿島港",             "name": "幸栄丸",              "sid": 496},
    {"area": "鹿島港",             "name": "第三幸栄丸",          "sid": 27},
    {"area": "鹿島港",             "name": "豊丸",                "sid": 1095},
    {"area": "鹿島市新浜",         "name": "ARCADIA SALTWATER SERVICE", "sid": 12274},
    # ── 千葉・外房 ────────────────────────────
    {"area": "外川港",             "name": "光佑丸",              "sid": 45},
    {"area": "外川港",             "name": "大盛丸",              "sid": 46},
    {"area": "外川",               "name": "孝進丸",              "sid": 749},   # 不定期
    {"area": "飯岡港",             "name": "幸丸",                "sid": 48},
    {"area": "飯岡港",             "name": "梅花丸",              "sid": 52},
    {"area": "飯岡港",             "name": "太幸丸",              "sid": 53},
    {"area": "飯岡港",             "name": "三次郎丸",            "sid": 54},
    {"area": "片貝港",             "name": "孝徳丸",              "sid": 1946},
    {"area": "片貝",               "name": "勇幸丸",              "sid": 58},    # 不定期
    {"area": "大原港",             "name": "第三松栄丸",          "sid": 63},
    {"area": "大原港",             "name": "敷嶋丸",              "sid": 66},
    {"area": "大原港",             "name": "つる丸",              "sid": 71},
    {"area": "大原港",             "name": "明広丸",              "sid": 76},
    {"area": "大原港",             "name": "春栄丸",              "sid": 754},
    {"area": "大原港",             "name": "新幸丸",              "sid": 1394},
    {"area": "大原港",             "name": "勇盛丸",              "sid": 5011},
    {"area": "大原",               "name": "義之丸",              "sid": 61},    # 不定期
    {"area": "天津港",             "name": "第八鶴丸",            "sid": 1412},
    {"area": "勝浦川津港",         "name": "不動丸",              "sid": 796},
    {"area": "勝浦松部港",         "name": "和八丸",              "sid": 1480},  # 不定期
    # ── 千葉・内房 ────────────────────────────
    {"area": "勝山港",             "name": "新盛丸",              "sid": 121},   # 不定期
    {"area": "保田港",             "name": "村井丸",              "sid": 123},
    {"area": "金谷港",             "name": "勘次郎丸",            "sid": 773},
    {"area": "金谷港",             "name": "光進丸",              "sid": 127},
    {"area": "富浦港",             "name": "共栄丸",              "sid": 797},
    {"area": "洲崎港",             "name": "佐衛美丸",            "sid": 1464},
    {"area": "富津港",             "name": "浜新丸",              "sid": 140},
    {"area": "富津",               "name": "川崎丸",              "sid": 141},   # 不定期
    {"area": "長浦",               "name": "こなや丸",            "sid": 142},
    # ── 千葉・東京湾奥 ───────────────────────
    {"area": "浦安",               "name": "吉久",                "sid": 147},
    {"area": "浦安",               "name": "吉野屋",              "sid": 146},
    {"area": "東葛西",             "name": "須原屋",              "sid": 171},
    {"area": "江戸川放水路",       "name": "たかはし遊船",        "sid": 145},   # 不定期
    {"area": "江戸川放水路･原木中山", "name": "林遊船",           "sid": 12260},
    # ── 東京 ──────────────────────────────────
    {"area": "羽田",               "name": "かめだや",            "sid": 165},
    {"area": "平和島",             "name": "船宿 まる八",         "sid": 735},
    {"area": "横浜港･新山下",      "name": "渡辺釣船店",          "sid": 172},
    # ── 神奈川・東京湾 ───────────────────────
    {"area": "小柴港",             "name": "三喜丸釣船店",        "sid": 174},
    {"area": "金沢漁港",           "name": "蒲谷丸",              "sid": 176},
    {"area": "金沢漁港",           "name": "忠彦丸",              "sid": 185},   # 不定期
    {"area": "金沢八景",           "name": "一之瀬丸",            "sid": 186},   # 不定期
    {"area": "金沢八景",           "name": "米元釣船店",          "sid": 188},
    {"area": "金沢八景",           "name": "荒川屋",              "sid": 189},
    {"area": "金沢八景",           "name": "弁天屋",              "sid": 190},
    {"area": "金沢八景",           "name": "野毛屋",              "sid": 192},   # 不定期
    {"area": "金沢八景",           "name": "小柴丸",              "sid": 1750},
    {"area": "新安浦港",           "name": "こうゆう丸",          "sid": 193},
    {"area": "横浜本牧港",         "name": "長崎屋",              "sid": 256},
    {"area": "磯子港",             "name": "鴨下丸kawana",        "sid": 12245},
    {"area": "久比里港",           "name": "山下丸",              "sid": 209},
    {"area": "久比里港",           "name": "巳之助丸",            "sid": 210},
    {"area": "久比里港",           "name": "山天丸",              "sid": 211},
    {"area": "久里浜",             "name": "大正丸",              "sid": 689},   # 不定期
    {"area": "鴨居大室港",         "name": "釣船 五郎丸",         "sid": 1817},
    {"area": "鴨居大室港",         "name": "福よし丸",            "sid": 11282},
    {"area": "小坪港",             "name": "太郎丸",              "sid": 253},
    {"area": "小網代港",           "name": "大和丸",              "sid": 1778},
    {"area": "小網代港",           "name": "翔太丸",              "sid": 1772},
    # ── 神奈川・相模湾 ───────────────────────
    {"area": "松輪江奈港",         "name": "あまさけや丸",        "sid": 1681},
    {"area": "松輪",               "name": "瀬戸丸",              "sid": 659},   # 不定期
    {"area": "長井港",             "name": "はら丸",              "sid": 218},
    {"area": "長井新宿港",         "name": "栃木丸",              "sid": 219},
    {"area": "長井港",             "name": "儀兵衛丸",            "sid": 221},
    {"area": "長井漆山港",         "name": "春盛丸",              "sid": 204},
    {"area": "長井",               "name": "丸八丸",              "sid": 12224}, # 不定期
    {"area": "葉山あぶずり港",     "name": "たいぞう丸",          "sid": 229},
    {"area": "葉山鐙摺",           "name": "愛正丸",              "sid": 232},   # 不定期
    {"area": "腰越",               "name": "飯岡丸",              "sid": 235},   # 不定期
    {"area": "茅ヶ崎港",           "name": "ちがさき丸",          "sid": 795},
    {"area": "平塚港",             "name": "庄治郎丸",            "sid": 245},
    {"area": "平塚",               "name": "庄三郎丸",            "sid": 244},   # 不定期
    {"area": "大磯港",             "name": "恒丸",                "sid": 246},
    {"area": "大磯港",             "name": "とうふや丸",          "sid": 1005},
    {"area": "寒川港",             "name": "小峯丸",              "sid": 12198},
    {"area": "小田原早川港",       "name": "平安丸",              "sid": 1700},
    # ── 静岡 ──────────────────────────────────
    {"area": "宇佐美",             "name": "秀正丸",              "sid": 270},
    {"area": "戸田",               "name": "福将丸",              "sid": 1875},
]

# エリアの地域グループ定義（area/*.html の見出しに使用）
AREA_GROUPS = {
    "茨城":               ["日立久慈港", "波崎港", "鹿島港", "鹿島市新浜"],
    "千葉・外房":         ["外川", "外川港", "飯岡港", "片貝", "片貝港",
                           "大原", "大原港", "天津港", "御宿岩和田港",
                           "勝浦川津港", "勝浦松部港"],
    "千葉・内房":         ["勝山", "勝山港", "保田港", "金谷港", "富浦港",
                           "洲崎港", "富津", "富津港", "長浦"],
    "千葉・東京湾奥":     ["浦安", "東葛西", "江戸川放水路", "江戸川放水路･原木中山"],
    "東京":               ["羽田", "平和島", "横浜港･新山下"],
    "神奈川・東京湾":     ["小柴港", "金沢漁港", "金沢八景", "新安浦港",
                           "横浜本牧港", "磯子港", "久比里", "久比里港",
                           "久里浜", "鴨居大室港", "小坪港", "小網代港"],
    "神奈川・相模湾":     ["松輪", "松輪江奈港", "長井", "長井港",
                           "長井新宿港", "長井漆山港", "葉山鐙摺",
                           "葉山あぶずり港", "腰越", "茅ヶ崎", "茅ヶ崎港",
                           "平塚", "平塚港", "大磯港", "寒川港",
                           "小田原早川", "小田原早川港"],
    "静岡":               ["宇佐美", "戸田"],
}

# ships.json が存在すれば上書き（discover_ships.py が月1回更新）
_ships_json = os.path.join(os.path.dirname(__file__), "ships.json")
if os.path.exists(_ships_json):
    with open(_ships_json, encoding="utf-8") as _f:
        SHIPS = json.load(_f)

BASE_URL     = "https://www.fishing-v.jp/choka/choka_detail.php?s={sid}"
GYO_BASE_URL = "https://www.gyo.ne.jp/rep_tsuri_view%7CCID-{cid}.htm"
USER_AGENT   = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

SITE_URL = "https://funatsuri-yoso.com"

# Google AdSense
ADSENSE_TAG = '<script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=ca-pub-7406401300491553" crossorigin="anonymous"></script>'

DATA_NOTE_HTML = """<div class="data-note">
  <details>
    <summary>データについて</summary>
    <ul>
      <li>釣果データは釣りビジョン（fishing-v.jp）から毎日自動収集しています</li>
      <li>船宿ごとの表記ゆれや未記載項目があり、数値は参考値です</li>
      <li>魚種・数量・サイズは独自ルールで正規化しています</li>
      <li>「最終更新」は本サイトのデータ取得日時（日本時間16:30頃）を示します</li>
    </ul>
  </details>
</div>"""

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

# 魚種別の正常値範囲（異常値検知用）
FISH_VALID_RANGE = {
    "アジ":       {"size_cm": (10, 55),   "count": (0, 400)},
    "タチウオ":   {"size_cm": (50, 200),  "count": (0, 80)},
    "フグ":       {"size_cm": (10, 60),   "count": (0, 150)},
    "カワハギ":   {"size_cm": (10, 45),   "count": (0, 150)},
    "マダイ":     {"size_cm": (10, 100),  "count": (0, 20),  "weight_kg": (0.1, 15.0)},
    "シロギス":   {"size_cm": (10, 40),   "count": (0, 300)},
    "イサキ":     {"size_cm": (20, 55),   "count": (0, 150)},
    "ヤリイカ":   {"size_cm": (10, 65),   "count": (0, 150)},
    "スルメイカ": {"size_cm": (10, 65),   "count": (0, 150)},
    "マダコ":     {"weight_kg": (0.1, 15.0), "count": (0, 30)},
    "カサゴ":     {"size_cm": (10, 55),   "count": (0, 80)},
    "メバル":     {"size_cm": (10, 45),   "count": (0, 80)},
    "ワラサ":     {"size_cm": (30, 110),  "count": (0, 20),  "weight_kg": (0.5, 15.0)},
    "アマダイ":   {"size_cm": (20, 75),   "count": (0, 20),  "weight_kg": (0.1, 5.0)},
    "メダイ":     {"size_cm": (30, 90),   "count": (0, 20),  "weight_kg": (0.3, 10.0)},
    "サワラ":     {"size_cm": (40, 130),  "count": (0, 20),  "weight_kg": (0.5, 15.0)},
    "ヒラメ":     {"size_cm": (30, 100),  "count": (0, 10),  "weight_kg": (0.3, 15.0)},
    "マゴチ":     {"size_cm": (20, 80),   "count": (0, 20),  "weight_kg": (0.1, 5.0)},
    "キンメダイ": {"size_cm": (20, 65),   "count": (0, 80),  "weight_kg": (0.1, 5.0)},
    "クロムツ":   {"size_cm": (20, 65),   "count": (0, 80)},
    "マルイカ":   {"size_cm": (5,  45),   "count": (0, 300)},
    "カンパチ":   {"size_cm": (20, 110),  "count": (0, 20),  "weight_kg": (0.3, 20.0)},
    "マハタ":     {"size_cm": (20, 90),   "count": (0, 15),  "weight_kg": (0.3, 15.0)},
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
    is_boat = bool(re.search(r"船中|合計|全体", t))
    m = re.search(r"(\d+)[～〜~](\d+)\s*[匹本尾枚杯]", t)
    if m: return {"min": int(m[1]), "max": int(m[2]), "is_boat": is_boat}
    m = re.search(r"(\d+)\s*[匹本尾枚杯]", t)
    if m: v = int(m[1]); return {"min": v, "max": v, "is_boat": is_boat}
    return None

def extract_weight_kg(t):
    t = parse_num(t)
    m = re.search(r"(\d+\.?\d*)[～〜~](\d+\.?\d*)\s*kg", t, re.I)
    if m: return {"min": float(m[1]), "max": float(m[2])}
    m = re.search(r"(\d+\.?\d*)\s*kg", t, re.I)
    if m: v = float(m[1]); return {"min": v, "max": v}
    return None

def extract_size_cm(t):
    t = parse_num(t)
    m = re.search(r"(\d+)[～〜~](\d+)\s*cm", t, re.I)
    if m: return {"min": int(m[1]), "max": int(m[2])}
    m = re.search(r"(\d+)\s*cm", t, re.I)
    if m: v = int(m[1]); return {"min": v, "max": v}
    return None

def parse_point(s):
    """ポイント文字列を場所と水深に分割する。
    '竹岡沖水深20～30m' → ('竹岡沖', '20～30m')
    '水深15m'           → (None, '15m')
    '竹岡沖'            → ('竹岡沖', None)
    """
    if not s:
        return None, None
    s = s.strip()
    # 先頭が「水深」→ place なし
    m = re.match(r'^水深(.+)', s)
    if m:
        return None, m.group(1).strip()
    # 途中に「水深」→ place + depth
    m = re.search(r'^(.+?)水深(.+)', s)
    if m:
        return m.group(1).strip() or None, m.group(2).strip() or None
    # 「水深」なし → 全部 place
    return s or None, None

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
        point_idx  = next((i for i,h in enumerate(header) if "ポイント" in h), None)

        for row in table[1:]:
            if len(row) <= fish_idx: continue
            fish_name = row[fish_idx].strip()
            if not fish_name or fish_name in ("魚種", "-", "－", ""): continue
            count_str  = row[count_idx].strip()  if count_idx  < len(row) else ""
            size_str   = row[size_idx].strip()   if size_idx   < len(row) else ""
            weight_str = row[weight_idx].strip() if weight_idx < len(row) else ""
            point_str  = row[point_idx].strip()  if point_idx is not None and point_idx < len(row) else ""
            cr = extract_count(count_str)
            # fish_name に「船中」が含まれる場合も is_boat フラグを立てる
            if cr and re.search(r"船中|合計|全体", fish_name):
                cr["is_boat"] = True
            _pp, _pd = parse_point(point_str)
            results.append({
                "ship":        ship,
                "area":        area,
                "date":        date,
                "month":       month,
                "catch_raw":   f"{fish_name} {count_str} {size_str} {weight_str}".strip(),
                "fish":        guess_fish(fish_name),
                "count_range": cr,
                "count_avg":   ((cr["min"] + cr["max"]) // 2) if cr else None,
                "size_cm":     extract_size_cm(size_str),
                "weight_kg":   extract_weight_kg(weight_str) or extract_weight_kg(size_str),
                "point_place": _pp,
                "point_depth": _pd,
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
    except (URLError, TimeoutError, OSError) as e:
        print(f"ERROR: {e}"); return None

def fetch_gyo(url):
    """gyo.ne.jp 専用 fetch: Shift-JIS を優先してデコード"""
    try:
        req = Request(url, headers={"User-Agent": USER_AGENT})
        with urlopen(req, timeout=20) as r:
            raw = r.read()
        for enc in ("cp932", "shift_jis", "euc-jp", "utf-8"):
            try: return raw.decode(enc)
            except: pass
        return raw.decode("utf-8", errors="replace")
    except (URLError, TimeoutError, OSError) as e:
        print(f"ERROR: {e}"); return None

# ============================================================
# gyo.ne.jp 専用パーサー
# ============================================================
# gyo.ne.jp のテーブルヘッダ候補（複数表記に対応）
_GYO_FISH_HDRS  = ("魚種", "釣り物", "種類")
_GYO_COUNT_HDRS = ("匹数", "尾数", "数量", "釣果数")
_GYO_SIZE_HDRS  = ("大きさ", "サイズ", "cm", "寸")

def _parse_text_section_gyo(section_html, ship, area, date_str, month):
    """
    gyo.ne.jp のテキスト形式釣果セクションをパース。
    word-break:break-all div の自由記述テキストから魚種・数量を抽出する。
    """
    # HTML タグ除去・正規化
    text = re.sub(r'<[^>]+>', ' ', section_html)
    text = re.sub(r'&[a-zA-Z]+;|&#\d+;', ' ', text)
    text = re.sub(r'[\u3000\xa0\ufffd]+', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    if not text:
        return []

    results = []
    # canonical → [読み方リスト] の逆引き辞書（長い名前を先にマッチ）
    all_fish = {}  # fish_name → canonical
    for canon, names in FISH_MAP.items():
        for n in names:
            all_fish[n] = canon
    sorted_fish = sorted(all_fish.keys(), key=len, reverse=True)

    found_canon = set()
    for fish_name in sorted_fish:
        if fish_name not in text:
            continue
        canon = all_fish[fish_name]
        if canon in found_canon:
            continue

        # 数量パターン: 魚種[、,\s]+ N〜M 枚/匹/尾/本
        p_range = rf'{re.escape(fish_name)}\s*[、,，\s]+\s*(\d+)\s*[〜~～]\s*(\d+)\s*[枚匹尾本]'
        p_single = rf'{re.escape(fish_name)}\s*[、,，\s]+\s*(\d+)\s*[枚匹尾本]'

        cr = None
        for pat in [p_range, p_single]:
            m = re.search(pat, text)
            if m:
                if len(m.groups()) == 2:
                    mn, mx = int(m.group(1)), int(m.group(2))
                else:
                    mn = mx = int(m.group(1))
                cr = {"min": mn, "max": mx}
                break

        if cr is None:
            continue
        found_canon.add(canon)

        # サイズ（大きさ N〜M cm/kg/サイズ）
        size_str = ""
        sm = re.search(
            rf'{re.escape(fish_name)}.{{0,80}}?(\d+(?:[.,、]\d+)?)\s*[〜~～]\s*(\d+(?:[.,、]\d+)?)\s*(cm|㎝|サイズ|kg|㎏|キロ)',
            text, re.S)
        if sm:
            size_str = f"{sm.group(1)}〜{sm.group(2)}{sm.group(3)}"

        # 水深（棚/水深 N m）
        depth_str = None
        dm = re.search(r'(?:棚|水深)\s*(\d+(?:[.,]\d+)?)\s*[mMｍM]', text)
        if dm:
            depth_str = f"{dm.group(1)}m"

        # 釣り場（～沖・～漁場等）
        place_str = None
        pm = re.search(r'(?:^|[。。 　,])([^\s、。，。]{2,8}(?:沖|漁場|ポイント|前))', text)
        if pm:
            place_str = pm.group(1).strip()

        results.append({
            "ship":        ship,
            "area":        area,
            "date":        date_str,
            "month":       month,
            "catch_raw":   text[:200],
            "fish":        [canon],
            "count_range": cr,
            "count_avg":   (cr["min"] + cr["max"]) // 2,
            "size_cm":     extract_size_cm(size_str) if size_str else None,
            "weight_kg":   extract_weight_kg(size_str) if size_str else None,
            "point_place": place_str,
            "point_depth": depth_str,
        })
    return results


def _parse_tables_gyo(tables, ship, area, date, month):
    """gyo.ne.jp のテーブルリストから釣果を抽出する。"""
    results = []
    for table in tables:
        if not table or len(table) < 2:
            continue
        header = table[0]
        hstr   = " ".join(header)
        has_fish  = any(k in hstr for k in _GYO_FISH_HDRS)
        has_count = any(k in hstr for k in _GYO_COUNT_HDRS)
        if not (has_fish or has_count):
            continue
        fish_idx  = next((i for i, h in enumerate(header) if any(k in h for k in _GYO_FISH_HDRS)),  0)
        count_idx = next((i for i, h in enumerate(header) if any(k in h for k in _GYO_COUNT_HDRS)), 1)
        size_idx  = next((i for i, h in enumerate(header) if any(k in h for k in _GYO_SIZE_HDRS)),  2)
        for row in table[1:]:
            if len(row) <= fish_idx:
                continue
            fish_name = row[fish_idx].strip()
            if not fish_name or fish_name in ("魚種", "釣り物", "-", "－", ""):
                continue
            count_str = row[count_idx].strip() if count_idx < len(row) else ""
            size_str  = row[size_idx].strip()  if size_idx  < len(row) else ""
            cr_g = extract_count(count_str)
            if cr_g is None:
                continue  # 数量不明の行はスキップ（出船予定表等を除外）
            results.append({
                "ship":        ship,
                "area":        area,
                "date":        date,
                "month":       month,
                "catch_raw":   f"{fish_name} {count_str} {size_str}".strip(),
                "fish":        guess_fish(fish_name),
                "count_range": cr_g,
                "count_avg":   ((cr_g["min"] + cr_g["max"]) // 2) if cr_g else None,
                "size_cm":     extract_size_cm(size_str),
                "weight_kg":   extract_weight_kg(size_str),
                "point_place": None,
                "point_depth": None,
            })
    return results


def parse_catches_gyo(html, ship, area, year):
    """
    gyo.ne.jp 専用パーサー。
    日付が特定できない記録は全てスキップ（今日の日付のデフォルト使用禁止）。
    直近60日以内の日付のみ有効とする。
    """
    results = []
    now     = datetime.now()
    cutoff  = now - timedelta(days=60)

    def _valid_date(y, mo, d):
        """(year, month, day) → (ok, date_str, month_int) or None"""
        try:
            dt = datetime(y, mo, d)
        except ValueError:
            return None
        if dt < cutoff or dt > now:
            return None
        return f"{y}/{mo:02d}/{d:02d}", mo

    date_positions = []  # (html_position, date_str, month_int)

    # YYYY年M月D日 のみ（YYYY/M/D はナビURLと混同するため除外）
    for m in re.finditer(r'(\d{4})年(\d{1,2})月(\d{1,2})日', html):
        res = _valid_date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if res:
            date_positions.append((m.start(), res[0], res[1]))

    # M月D日（年なし）→ 当年・前年の順で試す
    for m in re.finditer(r'(\d{1,2})月(\d{1,2})日', html):
        mo, d = int(m.group(1)), int(m.group(2))
        for y in (year, year - 1):
            res = _valid_date(y, mo, d)
            if res:
                date_positions.append((m.start(), res[0], res[1]))
                break

    if not date_positions:
        return []  # 日付が1件も取れない場合は空を返す

    # 位置順にソートし、同じ日付文字列の重複を除去（最初の出現位置を使用）
    date_positions.sort(key=lambda x: x[0])
    seen_dates   = set()
    unique_dates = []
    for pos, date_str, mo in date_positions:
        if date_str not in seen_dates:
            seen_dates.add(date_str)
            unique_dates.append((pos, date_str, mo))

    # 日付セクションごとにパース（テーブル優先→テキスト形式フォールバック）
    for i, (date_pos, date_str, month) in enumerate(unique_dates):
        end_pos = unique_dates[i + 1][0] if i + 1 < len(unique_dates) else len(html)
        section = html[date_pos:end_pos]
        # 1) テーブル形式を試みる
        parser  = TableParser()
        parser.feed(section)
        catches = _parse_tables_gyo(parser.tables, ship, area, date_str, month)
        # 2) テーブルが取れなければテキスト形式を試みる
        if not catches:
            catches = _parse_text_section_gyo(section, ship, area, date_str, month)
        results.extend(catches)

    return results

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

def validate_catch(c):
    """異常値チェック。正常はTrue、異常はFalse。"""
    fish_list = c.get("fish", [])
    if not fish_list or fish_list[0] == "不明":
        return True
    fish = fish_list[0]
    rules = FISH_VALID_RANGE.get(fish)
    if not rules:
        return True
    cr = c.get("count_range")
    sr = c.get("size_cm")
    wkg = c.get("weight_kg")
    if cr and not cr.get("is_boat"):  # 船中数は個人上限チェックしない
        lo, hi = rules.get("count", (1, 9999))
        if cr["max"] > hi or cr["min"] < lo:
            return False
    if sr and "size_cm" in rules:
        lo, hi = rules["size_cm"]
        if sr["max"] < lo or sr["min"] > hi:
            return False
    if wkg and "weight_kg" in rules:
        lo, hi = rules["weight_kg"]
        if wkg["max"] < lo or wkg["min"] > hi:
            return False
    return True

def dedup_catches(catches):
    """同一船宿・日付・魚種・最高数が同じレコードを重複排除する。"""
    seen = set()
    result = []
    for c in catches:
        cr = c.get("count_range") or {}
        key = (c["ship"], c.get("date") or "", ",".join(sorted(c.get("fish", []))), cr.get("max", 0))
        if key not in seen:
            seen.add(key)
            result.append(c)
    return result

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
        if c.get("anomaly"):
            continue
        cr = c.get("count_range") or {}
        sr = c.get("size_cm") or {}
        is_boat = cr.get("is_boat", False)
        avg = (cr.get("min", 0) + cr.get("max", 0)) // 2 if cr else 0
        mx  = cr.get("max", 0)
        sz  = sr.get("max", 0)
        for fish in c.get("fish", []):
            for store, key in [(temp_w, wk), (temp_m, mo)]:
                if key not in store: store[key] = {}
                if fish not in store[key]: store[key][fish] = {"ships": 0, "sum": 0, "cnt": 0, "max": 0, "szs": []}
                d = store[key][fish]
                d["ships"] += 1
                if not is_boat:  # 船中数は平均に含めない
                    d["sum"] += avg; d["cnt"] += 1
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
# #5: 好調度コメント（100パターン）
# comp_tier: top(75+)/high(60-75)/mid(45-60)/low(30-45)/bottom(<30)
# season_tier: peak(5)/good(4)/mid(3)/off(2)/dead(1)/na
# yoy_tier: boom(+100%+)/up(+20%+)/flat(±20%)/down(-20%以下)/na
# ============================================================
_COMMENTS = {
    # ── top tier (composite 75+) ──────────────────────────
    ("top","peak","boom"):  ["記録的な好調！旬×昨年比大幅増の最高条件が揃った","今年は当たり年。旬のピークで数・型ともに期待大"],
    ("top","peak","up"):    ["旬真っ只中で昨年以上の好調。今すぐ出陣を","ピーク期に好調が重なった週。チャンスを逃すな"],
    ("top","peak","flat"):  ["旬のピーク期。例年通りの安定した好釣果","今が一番釣れる季節。コンスタントに数が出る"],
    ("top","peak","down"):  ["旬だが今年はやや渋め。それでも今週の最上位","例年より少なめだが、旬の底力は確か"],
    ("top","peak","na"):    ["旬のピーク期。今週の大本命","今が狙い時。ピーク期に入り釣果好調"],
    ("top","good","boom"):  ["好シーズン入りで昨年を大きく上回る絶好調","今年は一段上の好調。予約を急ぎたい"],
    ("top","good","up"):    ["好シーズンに昨年比アップが重なった高スコア週","上昇トレンドに乗っている。今週の狙い目"],
    ("top","good","flat"):  ["好シーズン中の安定した釣果。外さない一手","例年並みだが十分な水準。コンスタントに釣れる"],
    ("top","good","down"):  ["好シーズンだが今年はやや低調。腕でカバーを","シーズンの実力は確か。昨年より少ないが狙う価値あり"],
    ("top","good","na"):    ["好シーズン到来。今週の注目株","安定した好シーズン。今週も期待できる"],
    ("top","mid","boom"):   ["シーズン中盤で昨年比大幅増。今年の当たり週","予想外の好調。データが示す今週のイチ推し"],
    ("top","mid","up"):     ["中盤戦でも高水準をキープ。安定感が光る","シーズン中でもしっかり釣れている。頼れる存在"],
    ("top","mid","flat"):   ["例年通りのシーズン中盤。ブレのない安定感","今週も安定して釣れている。頼もしい選択肢"],
    ("top","mid","down"):   ["今年はやや渋いシーズン中盤だが他より優秀","不調気味でも全魚種中でトップクラスの釣れ具合"],
    ("top","mid","na"):     ["今週の総合トップ。安定した釣果が続く","データ的に今週最もおすすめの釣り物"],
    ("top","off","boom"):   ["端境期にもかかわらず昨年比大幅増の異例の好調","オフ入りのはずが大爆釣。今だけのチャンス"],
    ("top","off","up"):     ["端境期を感じさせない好調ぶり。今のうちに","シーズンオフ前の嬉しいサプライズ"],
    ("top","off","flat"):   ["端境期だが安定して釣れている特例の週","オフシーズン入りしても健闘。好機を逃すな"],
    ("top","off","down"):   ["端境期の終盤。今のうちに釣っておきたい","そろそろ終わり際。ラストチャンスかも"],
    ("top","off","na"):     ["端境期とは思えない好釣果","オフ直前の駆け込みチャンス"],
    ("top","dead","boom"):  ["オフシーズン中の奇跡的な好況","季節外れの大チャンス。今だけの特別な状況"],
    ("top","dead","up"):    ["オフシーズンにしては驚きの好調","冬眠中のはずが元気に釣れている"],
    ("top","dead","flat"):  ["オフシーズン中でも意外な釣果","通年狙える魚。シーズン外でも安定している"],
    ("top","dead","down"):  ["厳しい季節だが今週は健闘している","オフ中でも一定の釣果を出している"],
    ("top","dead","na"):    ["オフシーズン中の隠れた好機","通年釣れる魚で今週も安定"],
    # ── high tier (60-75) ────────────────────────────────
    ("high","peak","boom"): ["旬のピークで昨年を大きく上回る好調","今年の旬は例年以上。数釣りのチャンス"],
    ("high","peak","up"):   ["旬まっさかり。昨年より好調で今週も期待","ピーク期に入り釣果が増加中"],
    ("high","peak","flat"): ["旬のピーク期。例年通りの安定した釣果","今が一番釣れる季節。コンスタントに顔が見れる"],
    ("high","peak","down"): ["旬だが今年はやや低調。それでも安定した釣果","例年より少なめだが旬の魚は地力がある"],
    ("high","peak","na"):   ["旬まっさかり。安定した釣果が続く","ピーク期に入り出船数も増加中"],
    ("high","good","boom"): ["好シーズン入りで昨年比大幅アップ","釣果が昨年を大きく上回る好況"],
    ("high","good","up"):   ["好調なシーズンが続いている。上昇トレンド","今季は好調で昨年より釣れている"],
    ("high","good","flat"): ["安定した好シーズン。コンスタントに釣れる","このシーズンの定番、今年も安定"],
    ("high","good","down"): ["好シーズンだが今年はやや低め。腕でカバー","昨年には届かないが十分楽しめる水準"],
    ("high","good","na"):   ["好シーズン中の安定した釣果","好調なシーズンが続いている"],
    ("high","mid","boom"):  ["中盤戦で昨年比大幅増。今年は違う","シーズン折り返しで好調が加速"],
    ("high","mid","up"):    ["シーズン中盤でも好調をキープ","安定して昨年を上回る推移"],
    ("high","mid","flat"):  ["平年並みの安定した釣果が続く","コンスタントに釣れている中盤戦"],
    ("high","mid","down"):  ["やや低調気味だが十分狙える水準","昨年より少ないが安定はしている"],
    ("high","mid","na"):    ["シーズン中盤でも安定した釣果","コンスタントに釣れている。頼れる選択肢"],
    ("high","off","boom"):  ["端境期の大逆転。昨年比大幅増","シーズン末期とは思えない好調"],
    ("high","off","up"):    ["端境期だが昨年より好調をキープ","オフ入り前の嬉しいプレゼント"],
    ("high","off","flat"):  ["端境期ながら安定した釣果","オフシーズン入り前の最後の好機"],
    ("high","off","down"):  ["徐々に失速気味。今のうちに","端境期に入り下降傾向だが、まだ釣れる"],
    ("high","off","na"):    ["端境期だが粘れば釣れる。今のうちに","シーズン末期の安定した釣果"],
    ("high","dead","boom"): ["オフシーズンを忘れさせる好釣果","冬場にしては驚異的な釣れっぷり"],
    ("high","dead","up"):   ["オフシーズンにしては健闘中","シーズン外でも昨年以上の釣果"],
    ("high","dead","flat"):  ["オフシーズン中でも例年並みの釣果","通年狙える魚。今週も安定した釣果"],
    ("high","dead","down"):  ["オフ中だがそれなりの釣果","厳しい季節でも粘れば釣れる"],
    ("high","dead","na"):   ["通年釣れる魚。オフ中でも健闘","オフシーズンにしては安定した釣果"],
    # ── mid tier (45-60) ─────────────────────────────────
    ("mid","peak","boom"):  ["旬のピーク期で昨年比は増えているが全体では中位","数は増えているが、もう一息の状況"],
    ("mid","peak","up"):    ["旬だが釣果はまずまず。昨年より好調","ピーク期の割に伸び切っていないが昨年比プラス"],
    ("mid","peak","flat"):  ["旬のはずが例年並みどまり。型狙いにシフトも","ピーク期の安定感はあるが爆発力に欠ける"],
    ("mid","peak","down"):  ["旬なのに今年は苦戦中。腕と場所選びが重要","ピーク期だが低調。型狙いで活路を"],
    ("mid","peak","na"):    ["旬だが今週は中位の釣れ具合","ピーク期ながら爆発力に欠ける。型狙いで"],
    ("mid","good","boom"):  ["好シーズンで昨年比は増えているが他も釣れている","数は増えているが今週は中位"],
    ("mid","good","up"):    ["好シーズン入りで上昇中。安定感はある","好調なシーズンで昨年を上回っているが他も競っている"],
    ("mid","good","flat"):  ["まずまずの釣果が続いている。安定はしている","可もなく不可もなく。コンスタントに釣れる"],
    ("mid","good","down"):  ["好シーズンだが今年は伸び悩み","昨年より少ないが、まだ狙う価値はある"],
    ("mid","good","na"):    ["好シーズン中のまずまずの状況","安定した釣果だが爆発力はない"],
    ("mid","mid","boom"):   ["中盤戦で昨年比大幅増。悪くない状況","シーズン中盤で釣果が昨年を上回っている"],
    ("mid","mid","up"):     ["シーズン中盤でコンスタントに釣れている","平均的な時期だが昨年より釣れている"],
    ("mid","mid","flat"):   ["平年並みの釣果。可もなく不可もなく","数は出ないが型狙いも一手"],
    ("mid","mid","down"):   ["やや渋め。腕の見せどころ","例年より少ないが完全にダメではない"],
    ("mid","mid","na"):     ["コンスタントに釣れているが特別好調でもない","今週の普通の状況。安定してはいる"],
    ("mid","off","boom"):   ["端境期に昨年比大幅増。隠れた好機","オフ入りにしては昨年を大幅に上回る"],
    ("mid","off","up"):     ["端境期だが昨年よりマシな状況","オフシーズン入りでも善戦中"],
    ("mid","off","flat"):   ["端境期ながら粘れば釣れる","シーズン末期の安定した釣果"],
    ("mid","off","down"):   ["端境期に入り厳しくなってきた","オフシーズンへ向けて徐々に失速"],
    ("mid","off","na"):     ["端境期。今のうちに釣っておきたい","オフ入り前のラスト好機"],
    ("mid","dead","boom"):  ["オフシーズン中に昨年比大幅増。珍しい状況","通年釣れる魚で昨年を上回る好調"],
    ("mid","dead","up"):    ["オフ中だが昨年よりは釣れている","シーズン外でも意外と釣果がある"],
    ("mid","dead","flat"):  ["難しい季節だが一定の釣果がある","オフシーズン中でも通年狙える魚"],
    ("mid","dead","down"):  ["厳しい時期。数は出にくい","難しいシーズン。覚悟して挑もう"],
    ("mid","dead","na"):    ["難しい季節だが一定の釣果がある","通年釣れる魚で今週も安定"],
    # ── low tier (30-45) ─────────────────────────────────
    ("low","peak","boom"):  ["旬で昨年比は増えているが全体では低位","ピーク期だが期待ほどではない。昨年比は増加"],
    ("low","peak","up"):    ["旬だが今週は苦戦気味。型狙いで勝負","ピーク期にしては低調。昨年よりは増えている"],
    ("low","peak","flat"):  ["旬のはずが今年は不振気味","ピーク期なのに例年並みどまり"],
    ("low","peak","down"):  ["旬なのに今年は明らかに不調","ピーク期にもかかわらず苦戦が続く"],
    ("low","peak","na"):    ["旬だが今週は苦戦。他の魚種も検討を","ピーク期にしては物足りない釣れ具合"],
    ("low","good","boom"):  ["好シーズンで昨年比は増えているが全体では低位","数は増えているが他の魚種と比べると苦戦"],
    ("low","good","up"):    ["好シーズンだが今週は厳しい。昨年よりは増加","昨年より増えているが全体的には苦戦"],
    ("low","good","flat"):  ["好シーズンだが低調。天候や潮の影響か","釣れなくはないが期待は禁物"],
    ("low","good","down"):  ["好シーズンにもかかわらず大苦戦","昨年を大きく下回る低調なシーズン"],
    ("low","good","na"):    ["好シーズンの割に今週は低調","釣れなくはないが全体的には苦戦"],
    ("low","mid","boom"):   ["昨年比は増えているが今週は渋い","数は増加傾向だが全体では苦戦"],
    ("low","mid","up"):     ["やや渋め。状況の好転を待ちたい","確実に釣りたいなら別の魚種も検討を"],
    ("low","mid","flat"):   ["渋い週。厳しいコンディション","数は出にくい時期。型狙いで"],
    ("low","mid","down"):   ["今週はかなり厳しい状況","苦戦中。他の魚種と組み合わせて楽しもう"],
    ("low","mid","na"):     ["やや渋め。確実性なら他の魚種が無難","今週は苦しい。腕の見せどころ"],
    ("low","off","boom"):   ["端境期で昨年比は増えているが全体的には厳しい","オフ入りにしては釣れているが渋い"],
    ("low","off","up"):     ["端境期。厳しいが昨年よりはマシ","シーズン終盤。苦しいが粘れば"],
    ("low","off","flat"):   ["端境期。次の季節に期待","オフシーズン入りで急失速"],
    ("low","off","down"):   ["端境期で急激に渋くなってきた","シーズン終盤の大苦戦"],
    ("low","off","na"):     ["端境期で厳しい状況","次のシーズンに期待。今は様子見"],
    ("low","dead","boom"):  ["オフシーズン中で昨年比は増えているが依然厳しい","季節外れだが昨年よりは釣れている"],
    ("low","dead","up"):    ["オフ中で苦しいが昨年よりはマシ","厳しい季節だが健闘している"],
    ("low","dead","flat"):  ["完全なオフシーズン","今は時期ではない。来シーズンに期待"],
    ("low","dead","down"):  ["厳しいオフシーズン。苦戦必至","今は別の魚種を狙うのが賢明"],
    ("low","dead","na"):    ["オフシーズン。厳しい時期","来シーズンまで待ちの姿勢"],
    # ── bottom tier (<30) ────────────────────────────────
    ("bottom","peak","boom"):  ["旬で昨年比は増えているが今週は全魚種中で最下位","ピーク期で昨年比増加も、他との差が大きい"],
    ("bottom","peak","up"):    ["旬のはずが今週は大苦戦","ピーク期にもかかわらず全魚種中で最も厳しい"],
    ("bottom","peak","flat"):  ["旬なのに今週は全魚種中で最も苦戦","ピーク期だが今週はリセット待ちか"],
    ("bottom","peak","down"):  ["旬なのに記録的な不振。今年は例外か","ピーク期で昨年比大幅減。苦しい状況"],
    ("bottom","peak","na"):    ["旬にもかかわらず今週は最下位","ピーク期だが全体では大苦戦"],
    ("bottom","good","boom"):  ["好シーズンで昨年比増加も全体では最下位","数は増えているが他との差が大きい"],
    ("bottom","good","up"):    ["好シーズンだが今週は全魚種中で低位","昨年よりは増えているが厳しい状況"],
    ("bottom","good","flat"):  ["好シーズンの割に今週は大苦戦","釣れなくはないが今週は厳しい"],
    ("bottom","good","down"):  ["好シーズンにもかかわらず全魚種中で最下位","今年は明らかな不調シーズン"],
    ("bottom","good","na"):    ["好シーズンだが今週は大苦戦","シーズンの割に今週は全魚種中で低位"],
    ("bottom","mid","boom"):   ["昨年比は増えているが今週は全魚種中で最下位","数は増加傾向だが今週は苦しい"],
    ("bottom","mid","up"):     ["今週は全魚種中で最も苦しい状況","様子見が無難。他の魚種を検討"],
    ("bottom","mid","flat"):   ["今週はかなり厳しい。他の魚種と比較を","渋い中でも完全なゼロではない"],
    ("bottom","mid","down"):   ["今週の全魚種中で最も低調","苦戦必至。確実性を求めるなら他の魚種で"],
    ("bottom","mid","na"):     ["今週は全魚種中で最も苦しい","様子見が無難。他の魚種を検討"],
    ("bottom","off","boom"):   ["端境期で昨年比増加も全体では最下位","オフ入りで昨年比は増えているが全体的に苦戦"],
    ("bottom","off","up"):     ["端境期で厳しい。昨年よりはマシだが","シーズン終盤で全魚種中の最下位"],
    ("bottom","off","flat"):   ["端境期で完全に失速","次のシーズンまで待ちの姿勢"],
    ("bottom","off","down"):   ["端境期で急激に失速。最悪の状況","シーズン終盤の記録的な低調"],
    ("bottom","off","na"):     ["端境期で完全に失速","次シーズンに期待。今は別の魚種で"],
    ("bottom","dead","boom"):  ["オフシーズン中で昨年比は増えているが全魚種最下位","季節外れの状況。それでも昨年よりは釣れている"],
    ("bottom","dead","up"):    ["オフシーズンで苦戦。昨年よりはマシ","厳しい季節。今は別の魚種が無難"],
    ("bottom","dead","flat"):  ["オフシーズン中、無理は禁物","また来シーズン。今は別の魚種で"],
    ("bottom","dead","down"):  ["厳しいオフシーズンで昨年を大きく下回る","今は休漁期の扱い。次の季節に期待"],
    ("bottom","dead","na"):    ["オフシーズン中、無理は禁物","また来シーズン。今は別の魚種で"],
}

def build_comment(fish, count, score, this_w, last_w, prev_w=None, max_cnt=1, composite=50):
    """100パターン対応のコメント生成"""
    comp_tier = (
        "top"    if composite >= 75 else
        "high"   if composite >= 60 else
        "mid"    if composite >= 45 else
        "low"    if composite >= 30 else
        "bottom"
    )
    season_tier = (
        "peak" if score >= 5 else
        "good" if score >= 4 else
        "mid"  if score == 3 else
        "off"  if score == 2 else
        "dead" if score >= 1 else
        "na"
    )
    yoy_pct = None
    yoy_tier = "na"
    if this_w and last_w:
        t_a = this_w.get("avg") or 0
        l_a = last_w.get("avg") or 0
        if t_a and l_a:
            yoy_pct = round((t_a - l_a) / l_a * 100)
            yoy_tier = (
                "boom" if yoy_pct >= 100 else
                "up"   if yoy_pct >= 20  else
                "flat" if yoy_pct >= -20 else
                "down"
            )
    # 完全一致 → yoy=na → mid season → na全部 の順でフォールバック
    key = (comp_tier, season_tier, yoy_tier)
    pool = (
        _COMMENTS.get(key) or
        _COMMENTS.get((comp_tier, season_tier, "na")) or
        _COMMENTS.get((comp_tier, "mid", "na")) or
        ["安定した釣果が続いている", "コンスタントに釣れている"]
    )
    base = pool[hash(fish) % len(pool)]
    # 先週比チェック（コメント本文との矛盾を防ぐ注記）
    wow_pct = None
    if this_w and prev_w:
        t_s = this_w.get("ships") or 0
        p_s = prev_w.get("ships") or 0
        if t_s and p_s:
            wow_pct = round((t_s - p_s) / p_s * 100)
    if wow_pct is not None:
        if comp_tier in ("top", "high") and wow_pct <= -30:
            base += "（直近は急減傾向・注意）"
        elif comp_tier in ("low", "bottom") and wow_pct >= 50:
            base += "（ただし直近は急増中）"
    suffix = f"（今週{count}件"
    if yoy_pct is not None:
        sign = "+" if yoy_pct >= 0 else ""
        suffix += f"・昨年比{sign}{yoy_pct}%"
    if wow_pct is not None and abs(wow_pct) <= 150:
        sign2 = "+" if wow_pct >= 0 else ""
        suffix += f"・先週比{sign2}{wow_pct}%"
    suffix += "）"
    return base + suffix

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
    if this_w and prev_w:
        t_s = this_w.get("ships") or 0
        p_s = prev_w.get("ships") or 0
        if t_s and p_s:
            wow = (t_s - p_s) / p_s
            if wow >= 0.2:
                tags.append(("wow-up", "📈 先週比UP"))
            elif wow <= -0.2:
                tags.append(("wow-down", "📉 先週比DOWN"))
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
nav{background:#081020;padding:8px 24px;display:flex;gap:16px;flex-wrap:wrap;align-items:center}
nav a{color:#7a9bb5;text-decoration:none;font-size:13px}
nav a:hover{color:#4db8ff}
.area-dropdown{position:relative}
.area-btn{background:none;border:1px solid #1a4060;color:#7a9bb5;font-size:12px;padding:3px 10px;border-radius:12px;cursor:pointer;white-space:nowrap}
.area-btn:hover{color:#4db8ff;border-color:#4db8ff}
.area-menu{display:none;position:absolute;top:calc(100% + 6px);left:0;background:#0d2137;border:1px solid #1a6ea8;border-radius:8px;padding:12px 16px;z-index:100;min-width:260px}
.area-menu.open{display:block}
.area-group{margin-bottom:10px}
.area-group:last-child{margin-bottom:0}
.area-group-label{font-size:10px;color:#4db8ff;font-weight:bold;letter-spacing:.5px;margin-bottom:4px;padding-bottom:3px;border-bottom:1px solid #1a3050}
.area-group-links{display:flex;flex-wrap:wrap;gap:4px 10px}
.area-menu a{color:#7a9bb5;text-decoration:none;font-size:12px;white-space:nowrap}
.area-menu a:hover{color:#4db8ff}
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
tr.dim td{opacity:0.45}
.boat-catch{color:#f0a040;font-size:11px}
.data-note{max-width:900px;margin:20px auto 0;padding:0 16px}
.data-note details{background:#0d2137;border:1px solid #1a4060;border-radius:8px;padding:10px 14px}
.data-note summary{color:#7a9bb5;font-size:12px;cursor:pointer;user-select:none}
.data-note ul{margin-top:8px;padding-left:16px;color:#5a8aaa;font-size:11px;line-height:1.9}
.filter-bar{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px}
.filter-btn{background:#081020;border:1px solid #1a4060;color:#7a9bb5;padding:4px 12px;border-radius:16px;cursor:pointer;font-size:12px;transition:all .2s}
.filter-btn.active{background:#1a6ea8;color:#fff;border-color:#1a6ea8}
.filter-group{margin-bottom:14px;display:flex;flex-wrap:wrap;align-items:center;gap:6px}
.filter-group-label{font-size:10px;color:#4db8ff;font-weight:bold;min-width:80px;flex-shrink:0}
.filter-btn.all-btn{margin-bottom:6px}
a.filter-btn{text-decoration:none;display:inline-block}
.note{font-size:11px;color:#7a9bb5;text-align:right;margin-top:8px}
.search-sort-bar{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:10px}
#fish-search{background:#081020;border:1px solid #1a4060;color:#c8d8e8;padding:6px 12px;border-radius:16px;font-size:12px;flex:1;min-width:160px;outline:none}
#fish-search::placeholder{color:#4a6a8a}
.sort-btns{display:flex;gap:6px}
.sort-btn{background:#081020;border:1px solid #1a4060;color:#7a9bb5;padding:4px 10px;border-radius:16px;cursor:pointer;font-size:11px;transition:all .2s}
.sort-btn.active{background:#1a4060;color:#4db8ff;border-color:#4db8ff}
.new-badge{display:inline-block;background:#e85d04;color:#fff;font-size:10px;font-weight:bold;padding:1px 6px;border-radius:8px;margin-left:6px;vertical-align:middle}
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
.fc-stats-row{display:flex;gap:6px;align-items:center;flex-wrap:wrap;margin-top:6px}
.fc-avg{font-size:11px;color:#c8d8e8}
.fc-trend{font-size:11px;margin-top:4px;padding:2px 6px;border-radius:4px;display:inline-block}
.trend-up{background:#0d3320;color:#4dcc88}
.trend-down{background:#330d0d;color:#cc4d4d}
.trend-flat{background:#1a2a3a;color:#7a9bb5}
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
        score     = get_season_score(fish, cur_month)
        this_w, last_w = get_yoy_data(history, fish, year, week_num)
        prev_w    = get_prev_week_data(history, fish, year, week_num)
        ships     = len(ship_counts_per_fish.get(fish, set()))
        composite = calc_composite_score(fish, cnt, max_cnt, this_w, last_w, prev_w, cur_month)
        badge     = yoy_badge(this_w, last_w)
        comment   = build_comment(fish, cnt, score, this_w, last_w, prev_w, max_cnt, composite)
        stars     = composite_to_stars(composite)
        tags      = build_reason_tags(fish, cnt, max_cnt, this_w, last_w, prev_w, cur_month)
        targets.append({"fish": fish, "count": cnt, "score": score, "composite": composite,
                        "comment": comment, "badge": badge, "ships": ships,
                        "stars": stars, "tags": tags})
    targets.sort(key=lambda x: -x["composite"])
    return targets[:5]

def _render_tags(tags):
    html = ""
    for kind, label in tags:
        cls = "rtag-up" if kind in ("up","up2","season","hot","wow-up") else "rtag-down"
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
# 表示ヘルパー
# ============================================================
def fmt_count(c):
    """数量セル用文字列。船中の場合は '船中X' と表示。"""
    cr = c.get("count_range")
    if not cr:
        return ""
    mn, mx = cr["min"], cr["max"]
    val = f"{mn}〜{mx}" if mn != mx else str(mn)
    if cr.get("is_boat"):
        return f"<span class='boat-catch' title='船全体の合計数'>船中{val}</span>"
    return val

def fmt_size_cm(c):
    """大きさ(cm)セル用文字列。"""
    sr = c.get("size_cm")
    if not sr: return ""
    mn, mx = sr["min"], sr["max"]
    return f"{mn}〜{mx}cm" if mn != mx else f"{mn}cm"

def fmt_size_kg(c):
    """重量(kg)セル用文字列。"""
    wkg = c.get("weight_kg")
    if not wkg: return ""
    mn, mx = wkg["min"], wkg["max"]
    return f"{mn}〜{mx}kg" if mn != mx else f"{mn}kg"

def fmt_size(c):
    """後方互換用。cm と kg を結合して返す。"""
    parts = [s for s in [fmt_size_cm(c), fmt_size_kg(c)] if s]
    return " ".join(parts)

# ============================================================
def build_catch_table(catches):
    active_areas = set(c["area"] for c in catches)
    # 「すべて」だけフィルター、エリアボタンはページへ遷移
    filter_btns = '<div class="filter-group"><button class="filter-btn active all-btn" onclick="filterArea(this,\'all\')">すべて</button></div>'
    covered = set()
    for group_label, group_areas in AREA_GROUPS.items():
        links = [f'<a href="area/{a}.html" class="filter-btn">{a}</a>'
                 for a in group_areas if a in active_areas]
        covered.update(group_areas)
        if links:
            filter_btns += (f'<div class="filter-group">'
                            f'<span class="filter-group-label">{group_label}</span>'
                            f'{"".join(links)}</div>')
    others = [f'<a href="area/{a}.html" class="filter-btn">{a}</a>'
              for a in sorted(active_areas - covered)]
    if others:
        filter_btns += (f'<div class="filter-group">'
                        f'<span class="filter-group-label">その他</span>'
                        f'{"".join(others)}</div>')
    rows = ""
    max_count = 0
    _top = sorted(catches, key=lambda x: x["date"] or "", reverse=True)[:20]
    for c in _top:
        cr = c.get("count_range")
        if cr and not cr.get("is_boat"): max_count = max(max_count, cr["max"])
    for c in _top:
        cr = c.get("count_range")
        cnt = fmt_count(c)
        is_top = cr and not cr.get("is_boat") and cr["max"] == max_count and max_count > 0
        is_dim = not cr or "不明" in c["fish"]
        sz_cm = fmt_size_cm(c)
        sz_kg = fmt_size_kg(c)
        hl = ' class="highlight"' if is_top else (' class="dim"' if is_dim else "")
        max_val = cr["max"] if cr and not cr.get("is_boat") else 0
        fish_str = "・".join(c["fish"])
        rows += f'<tr{hl} data-area="{c["area"]}" data-count="{max_val}" data-date="{c["date"] or ""}"><td>{c["date"] or "-"}</td><td>{c["area"]}</td><td>{c["ship"]}</td><td>{fish_str}</td><td>{cnt}</td><td>{sz_cm}</td><td>{sz_kg}</td></tr>'
    return f"""
    <div class="search-sort-bar">
      <input id="fish-search" type="text" placeholder="🔍 魚種で絞り込む..." oninput="searchFish(this.value)">
      <div class="sort-btns">
        <button class="sort-btn active" onclick="sortTable('date',this)">新着順</button>
        <button class="sort-btn" onclick="sortTable('count',this)">釣果数順</button>
      </div>
    </div>
    <div class="filter-bar">{filter_btns}</div>
    <table id="catch-table">
      <tr><th>日付</th><th>エリア</th><th>船宿</th><th>魚種</th><th>数量</th><th>大きさ(cm)</th><th>重量(kg)</th></tr>
      {rows}
    </table>"""

# ============================================================
# index.html 生成
# ============================================================
def build_html(catches, crawled_at, history):
    now = datetime.now()
    current_month = now.month
    fish_summary = {}
    year, week_num = current_iso_week()
    for c in catches:
        for f in c["fish"]:
            if f != "不明":
                fish_summary.setdefault(f, []).append(c)
    areas = sorted(set(c["area"] for c in catches))
    cards = ""
    for fish, cs in sorted(fish_summary.items(), key=lambda x: -len(x[1])):
        areas_list  = list(dict.fromkeys(c["area"] for c in cs[:3]))
        fish_id     = re.sub(r'[^\w]', '_', fish)
        ship_counts = {}
        for c in cs: ship_counts[c["ship"]] = ship_counts.get(c["ship"], 0) + 1
        daily_rows = ""
        for c in sorted(cs, key=lambda x: x["date"] or "", reverse=True)[:5]:
            cnt = fmt_count(c)
            sz_cm = fmt_size_cm(c); sz_kg = fmt_size_kg(c)
            daily_rows += f"<tr><td>{c['date'] or '-'}</td><td>{c['area']}</td><td>{c['ship']}</td><td>{cnt}</td><td>{sz_cm}</td><td>{sz_kg}</td></tr>"
        weekly_rows = ""
        for sn, cnt in sorted(ship_counts.items(), key=lambda x:-x[1])[:10]:
            pct = int(cnt / len(cs) * 100) if cs else 0
            weekly_rows += f'<tr><td>{sn}</td><td>{cnt}件</td><td><div class="bar-wrap"><div class="bar-fill" style="width:{pct}%"></div></div></td></tr>'
        ship_num   = len(ship_counts)
        ships_html = f'<span class="ships-badge">約{ship_num}隻</span>'
        # 昨年比 / 平均匹数 / 前週比トレンド
        this_w, last_w = get_yoy_data(history, fish, year, week_num)
        prev_w = get_prev_week_data(history, fish, year, week_num)
        yoy_html = yoy_badge(this_w, last_w)
        avg_html = ""
        if this_w:
            avg_val = this_w.get("avg") or 0
            max_val = this_w.get("max") or 0
            if avg_val:
                avg_html = f'<span class="fc-avg">平均{avg_val:.0f}匹'
                if max_val: avg_html += f'・最高{max_val}匹'
                avg_html += '</span>'
        trend_html = ""
        if this_w and prev_w:
            t_s = this_w.get("ships") or 0
            p_s = prev_w.get("ships") or 0
            if t_s and p_s and abs(t_s / p_s - 1) <= 1.5:
                if t_s / p_s > 1.2:
                    trend_html = '<div class="fc-trend trend-up">↑ 先週より上昇</div>'
                elif t_s / p_s < 0.8:
                    trend_html = '<div class="fc-trend trend-down">↓ 先週より減少</div>'
                else:
                    trend_html = '<div class="fc-trend trend-flat">→ 先週並み</div>'
        stats_html = f'<div class="fc-stats-row">{yoy_html}{avg_html}</div>{trend_html}'
        cards += f"""
    <div class="fc">
      <div class="fc-summary">
        <div class="fn">{fish}{ships_html}</div>
        <div class="fk">{len(cs)}件</div>
        <div class="fa">{" / ".join(areas_list)}</div>
        {stats_html}
      </div>
      <a class="fc-link" href="fish/{fish}.html">詳細・船宿ランキング →</a>
      <div class="fc-detail" style="display:none" id="detail-{fish_id}">
        <div class="tab-wrap">
          <button class="tab-btn active" onclick="switchTab(event,'daily-{fish_id}','weekly-{fish_id}')">デイリー</button>
          <button class="tab-btn" onclick="switchTab(event,'weekly-{fish_id}','daily-{fish_id}')">ウィークリー</button>
        </div>
        <div id="daily-{fish_id}"><table class="rank-table"><tr><th>日付</th><th>エリア</th><th>船宿</th><th>数量</th><th>大きさ</th><th>重量</th></tr>{daily_rows or '<tr><td colspan=6 style="color:#7a9bb5">データなし</td></tr>'}</table></div>
        <div id="weekly-{fish_id}" style="display:none"><table class="rank-table"><tr><th>船宿</th><th>釣果数</th><th>割合</th></tr>{weekly_rows or '<tr><td colspan=3 style="color:#7a9bb5">データなし</td></tr>'}</table></div>
      </div>
    </div>"""
    targets      = calc_targets(catches, history)
    target_html  = build_target_section(targets)
    forecast     = build_forecast(targets)
    catch_table  = build_catch_table(catches)
    active_areas = set(c["area"] for c in catches)
    area_nav_parts = []
    covered = set()
    for group_label, group_areas in AREA_GROUPS.items():
        links = [f'<a href="area/{a}.html">{a}</a>' for a in group_areas if a in active_areas]
        covered.update(group_areas)
        if links:
            area_nav_parts.append(
                f'<div class="area-group"><div class="area-group-label">{group_label}</div>'
                f'<div class="area-group-links">{"".join(links)}</div></div>'
            )
    # AREA_GROUPS未分類のエリアは「その他」にまとめる
    others = [f'<a href="area/{a}.html">{a}</a>' for a in sorted(active_areas - covered)]
    if others:
        area_nav_parts.append(
            f'<div class="area-group"><div class="area-group-label">その他</div>'
            f'<div class="area-group-links">{"".join(others)}</div></div>'
        )
    area_nav = "".join(area_nav_parts)
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
  <p class="site-desc">神奈川・東京・千葉・茨城の船宿{len(SHIPS)}軒の釣果を毎日自動収集。魚種・エリア・船宿を横断比較して「今週どこへ行くか」の意思決定をサポートします。</p>
</header>
<nav>
  <a href="index.html">🏠 トップ</a>
  <a href="calendar.html">📅 釣りものカレンダー</a>
  <span style="color:#1a4060">|</span>
  <div class="area-dropdown">
    <button class="area-btn" onclick="var m=document.getElementById('areaMenu');m.classList.toggle('open')">エリアから探す ▼</button>
    <div class="area-menu" id="areaMenu">{area_nav}</div>
  </div>
</nav>
<script>document.addEventListener('click',function(e){{if(!e.target.closest('.area-dropdown'))document.getElementById('areaMenu').classList.remove('open')}});</script>
<div class="wrap">
  <h2>🎯 今週の狙い目</h2>
  {forecast}
  {target_html}
  <h2>🐟 釣れている魚</h2>
  <p style="font-size:12px;color:#7a9bb5;margin-bottom:10px">タップで詳細表示 ／ 各カードの「詳細→」で船宿ランキングを確認</p>
  <div class="grid">{cards}</div>
  <h2>📋 最新の釣果</h2>
  {catch_table}
  <p class="note">最終更新: {crawled_at}<span id="new-badge"></span> ／ 総件数: {len(catches)} 件</p>
</div>
{DATA_NOTE_HTML}
<footer>
  <p><a href="contact.html">お問い合わせ</a> | <a href="privacy.html">プライバシーポリシー</a></p>
  <p style="margin-top:8px">© 2026 船釣り予想. All rights reserved.</p>
  <p style="margin-top:6px;font-size:11px;color:#4a6a8a">最終更新: {crawled_at} | v5.6</p>
</footer>
<script>
function filterArea(btn, area) {{
  document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  document.querySelectorAll('#catch-table tr[data-area]').forEach(tr => {{
    tr.style.display = (area === 'all' || tr.dataset.area === area) ? '' : 'none';
  }});
}}
function searchFish(val) {{
  const q = val.trim().toLowerCase();
  document.querySelectorAll('#catch-table tr[data-area]').forEach(tr => {{
    const fish = tr.cells[3] ? tr.cells[3].textContent.toLowerCase() : '';
    tr.style.display = (!q || fish.includes(q)) ? '' : 'none';
  }});
}}
function sortTable(key, btn) {{
  document.querySelectorAll('.sort-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  const tbody = document.getElementById('catch-table');
  const rows = Array.from(tbody.querySelectorAll('tr[data-area]'));
  rows.sort((a, b) => {{
    if (key === 'count') return parseInt(b.dataset.count||0) - parseInt(a.dataset.count||0);
    return (b.dataset.date||'').localeCompare(a.dataset.date||'');
  }});
  rows.forEach(r => tbody.appendChild(r));
}}
(function() {{
  const updated = "{crawled_at}";
  const m = updated.match(/(\d{{4}})\/(\d{{2}})\/(\d{{2}}) (\d{{2}}):(\d{{2}})/);
  if (m) {{
    const t = new Date(m[1],m[2]-1,m[3],m[4],m[5]);
    if (Date.now() - t.getTime() < 86400000) {{
      document.getElementById('new-badge').innerHTML = '<span class="new-badge">NEW</span>';
    }}
  }}
}})();
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
def build_fish_pages(data, history, crawled_at=""):
    os.makedirs("fish", exist_ok=True)
    now = datetime.now()
    current_month = now.month
    year, week_num = current_iso_week()
    fish_summary = {}
    for c in data:
        for f in c["fish"]:
            if f != "不明": fish_summary.setdefault(f, []).append(c)
    for fish, catches in fish_summary.items():
        if len(catches) < 1: continue
        season_bar_html = build_season_bar(fish, current_month)
        score   = get_season_score(fish, current_month)
        this_w, last_w = get_yoy_data(history, fish, year, week_num)
        comment = build_comment(fish, len(catches), score, this_w, last_w)
        rows = ""
        max_cnt = 0
        for c in catches:
            cr = c.get("count_range")
            if cr and not cr.get("is_boat"): max_cnt = max(max_cnt, cr["max"])
        for c in sorted(catches, key=lambda x: x["date"] or "", reverse=True)[:20]:
            cnt = fmt_count(c)
            sz_cm = fmt_size_cm(c); sz_kg = fmt_size_kg(c)
            cr  = c.get("count_range")
            is_top = cr and not cr.get("is_boat") and cr["max"] == max_cnt and max_cnt > 0
            is_dim = not cr
            hl = ' class="highlight"' if is_top else (' class="dim"' if is_dim else "")
            rows += f"<tr{hl}><td>{c['date'] or '-'}</td><td>{c['area']}</td><td>{c['ship']}</td><td>{cnt}</td><td>{sz_cm}</td><td>{sz_kg}</td></tr>"
        ship_counts = {}
        ship_max    = {}
        for c in catches:
            ship_counts[c["ship"]] = ship_counts.get(c["ship"], 0) + 1
            cr = c.get("count_range")
            if cr and not cr.get("is_boat"):
                ship_max[c["ship"]] = max(ship_max.get(c["ship"], 0), cr["max"])
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
        fish_encoded = quote(fish, safe='')
        fish_url = f"{SITE_URL}/fish/{fish_encoded}.html"
        max_cnt_str = f"・最高{max_cnt}匹" if max_cnt > 0 else ""
        fish_desc = f"関東エリアの{fish}釣果情報。今週{len(catches)}件{max_cnt_str}。船宿別ランキング・昨年同週比をリアルタイム更新。"
        # 同エリアで釣れる関連魚種
        _this_areas = set(c["area"] for c in catches)
        _rel_counts: dict = {}
        for _c in data:
            if _c["area"] in _this_areas:
                for _f in _c["fish"]:
                    if _f != fish and _f != "不明":
                        _rel_counts[_f] = _rel_counts.get(_f, 0) + 1
        _rel_links = "".join(
            '<a href="../fish/' + rf + '.html" style="background:#0d2137;border:1px solid #1a4060;border-radius:6px;padding:6px 10px;text-decoration:none;color:#4db8ff;font-size:13px;display:inline-block;margin:3px">' + rf + '</a>'
            for rf, _ in sorted(_rel_counts.items(), key=lambda x: -x[1])[:6]
        )
        related_section_html = (
            '<h2>🐟 同じエリアで釣れる魚</h2>'
            '<div style="display:flex;flex-wrap:wrap;gap:6px;margin:12px 0">' + _rel_links + '</div>'
        ) if _rel_links else ""
        # エリア別釣果リンク（fish_area/）
        _fa_counts: dict = {}
        for _c in catches:
            _fa_counts[_c["area"]] = _fa_counts.get(_c["area"], 0) + 1
        _fa_links = "".join(
            '<a href="../fish_area/' + fish + '_' + a + '.html" '
            'style="background:#0d2137;border:1px solid #1a4060;border-radius:6px;padding:6px 10px;text-decoration:none;color:#4db8ff;font-size:13px;display:inline-block;margin:3px">'
            + a + f'（{c}件）</a>'
            for a, c in sorted(_fa_counts.items(), key=lambda x: -x[1])
            if c >= 5
        )
        fish_area_section_html = (
            '<h2>🗺️ エリア別の釣果</h2>'
            '<div style="display:flex;flex-wrap:wrap;gap:6px;margin:12px 0">' + _fa_links + '</div>'
        ) if _fa_links else ""
        fish_css = "*{box-sizing:border-box;margin:0;padding:0}body{font-family:'Helvetica Neue',Arial,sans-serif;background:#0a1628;color:#e0e8f0}header{background:#0d2137;padding:16px 24px;border-bottom:2px solid #1a6ea8}header h1{font-size:20px;color:#4db8ff}nav{background:#081020;padding:8px 24px;display:flex;gap:12px;flex-wrap:wrap}nav a{color:#7a9bb5;text-decoration:none;font-size:13px}nav a:hover{color:#4db8ff}.wrap{max-width:900px;margin:0 auto;padding:20px 16px}h2{font-size:15px;color:#4db8ff;border-left:4px solid #4db8ff;padding-left:10px;margin:24px 0 12px}.season-bar{display:flex;gap:2px;margin:12px 0;flex-wrap:wrap}.sb-cell{min-width:20px;height:18px;border-radius:3px;font-size:10px;color:#fff;display:flex;align-items:center;justify-content:center;padding:0 2px}.sb-cell.peak-count{background:#e85d04}.sb-cell.peak-size{background:#7209b7}.sb-cell.mid{background:#1a6ea8}.sb-cell.low{background:#1a3050}.sb-cell.now{outline:2px solid #fff;outline-offset:1px}.comment{background:#0d2137;border-left:3px solid #e85d04;padding:12px;border-radius:4px;font-size:14px;margin-bottom:16px}table{width:100%;border-collapse:collapse;font-size:13px}th{background:#0d2137;color:#4db8ff;padding:8px;text-align:left}td{padding:8px;border-bottom:1px solid #0d2137}tr.highlight td{background:#1a2d10;color:#7ddd6f}tr.dim td{opacity:0.45}.bar-wrap{background:#081020;border-radius:2px;height:8px;width:80px}.bar-fill{background:#1a6ea8;height:8px;border-radius:2px}.yoy-table .up{color:#4dcc88}.yoy-table .down{color:#cc4d4d}.boat-catch{color:#f0a040;font-size:11px}.data-note{max-width:900px;margin:20px auto 0;padding:0 16px}.data-note details{background:#0d2137;border:1px solid #1a4060;border-radius:8px;padding:10px 14px}.data-note summary{color:#7a9bb5;font-size:12px;cursor:pointer;user-select:none}.data-note ul{margin-top:8px;padding-left:16px;color:#5a8aaa;font-size:11px;line-height:1.9}footer{background:#081020;border-top:1px solid #1a3050;padding:20px;text-align:center;font-size:12px;color:#7a9bb5;margin-top:40px}footer a{color:#4db8ff;text-decoration:none}"
        html = f"""<!DOCTYPE html>
<html lang="ja"><head>
  <meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
  <title>関東の{fish}釣果・船宿ランキング【今週{len(catches)}件】| 船釣り予想</title>
  <meta name="description" content="{fish_desc}">
  <link rel="canonical" href="{fish_url}">
  <meta property="og:title" content="関東の{fish}釣果・船宿ランキング【今週{len(catches)}件】">
  <meta property="og:description" content="{fish_desc}">
  <meta property="og:url" content="{fish_url}">
  <meta property="og:type" content="website">
  <meta property="og:site_name" content="船釣り予想">
  <script type="application/ld+json">{{"@context":"https://schema.org","@type":"BreadcrumbList","itemListElement":[{{"@type":"ListItem","position":1,"name":"トップ","item":"{SITE_URL}/"}},{{"@type":"ListItem","position":2,"name":"{fish}の釣果情報","item":"{fish_url}"}}]}}</script>
  {ADSENSE_TAG}
  <style>{fish_css}</style>
</head><body>
<header><h1>🎣 関東の{fish}釣果・船宿ランキング</h1></header>
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
  <table><tr><th>日付</th><th>エリア</th><th>船宿</th><th>数量</th><th>大きさ</th><th>重量</th></tr>{rows}</table>
  {related_section_html}
  {fish_area_section_html}
</div>
{DATA_NOTE_HTML}
<footer>
  <p><a href="../contact.html">お問い合わせ</a> | <a href="../privacy.html">プライバシーポリシー</a></p>
  <p style="margin-top:8px">© 2026 船釣り予想. All rights reserved.</p>
  <p style="margin-top:6px;font-size:11px;color:#4a6a8a">最終更新: {crawled_at}</p>
</footer>
</body></html>"""
        with open(f"fish/{fish}.html", "w", encoding="utf-8") as f:
            f.write(html)

# ============================================================
# #10: エリア別ページ
# ============================================================
def build_area_pages(data, history, crawled_at=""):
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
            cnt_str = fmt_count(c)
            sz_cm = fmt_size_cm(c); sz_kg = fmt_size_kg(c)
            cr = c.get("count_range")
            is_dim = not cr or "不明" in c["fish"]
            dim_attr = ' class="dim"' if is_dim else ""
            rows += f"<tr{dim_attr}><td>{c['date'] or '-'}</td><td>{c['ship']}</td><td>{'・'.join(c['fish'])}</td><td>{cnt_str}</td><td>{sz_cm}</td><td>{sz_kg}</td></tr>"
        group   = next((g for g, areas in AREA_GROUPS.items() if area in areas), "関東")
        area_encoded = quote(area, safe='')
        area_url = f"{SITE_URL}/area/{area_encoded}.html"
        _top_fish_str = "・".join(f for f, _ in top_fish[:3])
        _area_desc_fish = f"{_top_fish_str}など" if _top_fish_str else ""
        area_desc = f"{area}（{group}）の船釣り釣果。今週{len(catches)}件。{_area_desc_fish}釣れている魚種と船宿ランキングを毎日更新。"
        # 同グループの近隣港リンク
        _group_areas = AREA_GROUPS.get(group, [])
        _nearby_links = "".join(
            '<a href="../area/' + a + '.html" style="background:#0d2137;border:1px solid #1a4060;border-radius:6px;padding:6px 10px;text-decoration:none;color:#4db8ff;font-size:13px;display:inline-block;margin:3px">' + a + '</a>'
            for a in _group_areas if a != area and a in area_summary
        )
        nearby_section_html = (
            '<h2>🗺️ 同エリアの港</h2>'
            '<div style="display:flex;flex-wrap:wrap;gap:6px;margin:12px 0">' + _nearby_links + '</div>'
        ) if _nearby_links else ""
        area_css = "*{box-sizing:border-box;margin:0;padding:0}body{font-family:'Helvetica Neue',Arial,sans-serif;background:#0a1628;color:#e0e8f0}header{background:#0d2137;padding:16px 24px;border-bottom:2px solid #1a6ea8}header h1{font-size:20px;color:#4db8ff}header p{font-size:12px;color:#7a9bb5;margin-top:4px}nav{background:#081020;padding:8px 24px}nav a{color:#7a9bb5;text-decoration:none;font-size:13px}nav a:hover{color:#4db8ff}.wrap{max-width:900px;margin:0 auto;padding:20px 16px}h2{font-size:15px;color:#4db8ff;border-left:4px solid #4db8ff;padding-left:10px;margin:24px 0 12px}.fish-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(140px,1fr));gap:10px;margin-bottom:8px}.fish-grid a:hover{border-color:#4db8ff!important}table{width:100%;border-collapse:collapse;font-size:13px}th{background:#0d2137;color:#4db8ff;padding:8px;text-align:left}td{padding:8px;border-bottom:1px solid #0d2137}tr.dim td{opacity:0.45}.data-note{max-width:900px;margin:20px auto 0;padding:0 16px}.data-note details{background:#0d2137;border:1px solid #1a4060;border-radius:8px;padding:10px 14px}.data-note summary{color:#7a9bb5;font-size:12px;cursor:pointer;user-select:none}.data-note ul{margin-top:8px;padding-left:16px;color:#5a8aaa;font-size:11px;line-height:1.9}footer{background:#081020;border-top:1px solid #1a3050;padding:20px;text-align:center;font-size:12px;color:#7a9bb5;margin-top:40px}footer a{color:#4db8ff;text-decoration:none}"
        html = f"""<!DOCTYPE html>
<html lang="ja"><head>
  <meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
  <title>{area}の釣果速報・おすすめ船宿【今週{len(catches)}件】| 船釣り予想</title>
  <meta name="description" content="{area_desc}">
  <link rel="canonical" href="{area_url}">
  <meta property="og:title" content="{area}の釣果速報・おすすめ船宿【今週{len(catches)}件】">
  <meta property="og:description" content="{area_desc}">
  <meta property="og:url" content="{area_url}">
  <meta property="og:type" content="website">
  <meta property="og:site_name" content="船釣り予想">
  <script type="application/ld+json">{{"@context":"https://schema.org","@type":"BreadcrumbList","itemListElement":[{{"@type":"ListItem","position":1,"name":"トップ","item":"{SITE_URL}/"}},{{"@type":"ListItem","position":2,"name":"{group}","item":"{SITE_URL}/"}},{{"@type":"ListItem","position":3,"name":"{area}の釣果","item":"{area_url}"}}]}}</script>
  {ADSENSE_TAG}
  <style>{area_css}</style>
</head><body>
<header>
  <h1>🚢 {area}の釣果速報・おすすめ船宿</h1>
  <p>{group} ／ 今週の釣果: {len(catches)}件</p>
</header>
<nav><a href="../index.html">← トップへ戻る</a></nav>
<div class="wrap">
  <h2>🐟 今週釣れている魚</h2>
  <div class="fish-grid">{fish_cards}</div>
  <h2>🏆 船宿ランキング（今週）</h2>
  <table><tr><th>#</th><th>船宿</th><th>釣果数</th><th>割合</th></tr>{ship_rows}</table>
  <h2>📋 最新の釣果</h2>
  <table><tr><th>日付</th><th>船宿</th><th>魚種</th><th>数量</th><th>大きさ</th><th>重量</th></tr>{rows}</table>
  {nearby_section_html}
</div>
{DATA_NOTE_HTML}
<footer>
  <p><a href="../contact.html">お問い合わせ</a> | <a href="../privacy.html">プライバシーポリシー</a></p>
  <p style="margin-top:8px">© 2026 船釣り予想. All rights reserved.</p>
  <p style="margin-top:6px;font-size:11px;color:#4a6a8a">最終更新: {crawled_at}</p>
</footer>
</body></html>"""
        with open(f"area/{area}.html", "w", encoding="utf-8") as f:
            f.write(html)

# ============================================================
# #11: 魚種×港ページ（fish_area/）
# ============================================================
def build_fish_area_pages(data, crawled_at=""):
    os.makedirs("fish_area", exist_ok=True)
    fa_summary: dict = {}
    for c in data:
        for f in c["fish"]:
            if f != "不明":
                fa_summary.setdefault((f, c["area"]), []).append(c)

    fish_area_css = "*{box-sizing:border-box;margin:0;padding:0}body{font-family:'Helvetica Neue',Arial,sans-serif;background:#0a1628;color:#e0e8f0}header{background:#0d2137;padding:16px 24px;border-bottom:2px solid #1a6ea8}header h1{font-size:20px;color:#4db8ff}header p{font-size:12px;color:#7a9bb5;margin-top:4px}nav{background:#081020;padding:8px 24px;display:flex;gap:12px;flex-wrap:wrap}nav a{color:#7a9bb5;text-decoration:none;font-size:13px}nav a:hover{color:#4db8ff}.wrap{max-width:900px;margin:0 auto;padding:20px 16px}h2{font-size:15px;color:#4db8ff;border-left:4px solid #4db8ff;padding-left:10px;margin:24px 0 12px}table{width:100%;border-collapse:collapse;font-size:13px}th{background:#0d2137;color:#4db8ff;padding:8px;text-align:left}td{padding:8px;border-bottom:1px solid #0d2137}tr.highlight td{background:#1a2d10;color:#7ddd6f}tr.dim td{opacity:0.45}.bar-wrap{background:#081020;border-radius:2px;height:8px;width:80px}.bar-fill{background:#1a6ea8;height:8px;border-radius:2px}.boat-catch{color:#f0a040;font-size:11px}.data-note{max-width:900px;margin:20px auto 0;padding:0 16px}.data-note details{background:#0d2137;border:1px solid #1a4060;border-radius:8px;padding:10px 14px}.data-note summary{color:#7a9bb5;font-size:12px;cursor:pointer;user-select:none}.data-note ul{margin-top:8px;padding-left:16px;color:#5a8aaa;font-size:11px;line-height:1.9}footer{background:#081020;border-top:1px solid #1a3050;padding:20px;text-align:center;font-size:12px;color:#7a9bb5;margin-top:40px}footer a{color:#4db8ff;text-decoration:none}"

    count = 0
    for (fish, area), catches in fa_summary.items():
        if len(catches) < 5:
            continue
        max_cnt = 0
        for c in catches:
            cr = c.get("count_range")
            if cr and not cr.get("is_boat"):
                max_cnt = max(max_cnt, cr["max"])
        rows = ""
        for c in sorted(catches, key=lambda x: x["date"] or "", reverse=True)[:20]:
            cnt_str = fmt_count(c)
            sz_cm = fmt_size_cm(c); sz_kg = fmt_size_kg(c)
            cr = c.get("count_range")
            is_top = cr and not cr.get("is_boat") and cr["max"] == max_cnt and max_cnt > 0
            is_dim = not cr
            hl = ' class="highlight"' if is_top else (' class="dim"' if is_dim else "")
            rows += f"<tr{hl}><td>{c['date'] or '-'}</td><td>{c['ship']}</td><td>{cnt_str}</td><td>{sz_cm}</td><td>{sz_kg}</td></tr>"
        ship_counts: dict = {}
        ship_max: dict = {}
        for c in catches:
            ship_counts[c["ship"]] = ship_counts.get(c["ship"], 0) + 1
            cr = c.get("count_range")
            if cr and not cr.get("is_boat"):
                ship_max[c["ship"]] = max(ship_max.get(c["ship"], 0), cr["max"])
        rank_rows = ""
        for i, (sn, cnt) in enumerate(sorted(ship_counts.items(), key=lambda x: -x[1])[:8], 1):
            mx  = ship_max.get(sn, 0)
            pct = int(cnt / len(catches) * 100) if catches else 0
            rank_rows += (
                f'<tr><td style="color:#4db8ff;font-weight:bold;width:24px">{i}</td>'
                f'<td><strong>{sn}</strong></td>'
                f'<td style="color:#4dcc88">{cnt}件</td>'
                f'<td style="color:#e85d04">最高{mx}匹</td>'
                f'<td><div class="bar-wrap"><div class="bar-fill" style="width:{pct}%"></div></div></td></tr>'
            )
        fish_encoded = quote(fish, safe='')
        area_encoded = quote(area, safe='')
        page_url = f"{SITE_URL}/fish_area/{fish_encoded}_{area_encoded}.html"
        max_cnt_str = f"・最高{max_cnt}匹" if max_cnt > 0 else ""
        desc = f"{area}での{fish}釣果情報。今週{len(catches)}件{max_cnt_str}。船宿別ランキングをリアルタイム更新。"
        html = f"""<!DOCTYPE html>
<html lang="ja"><head>
  <meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
  <title>{area}の{fish}釣果・おすすめ船宿【今週{len(catches)}件】| 船釣り予想</title>
  <meta name="description" content="{desc}">
  <link rel="canonical" href="{page_url}">
  <meta property="og:title" content="{area}の{fish}釣果・おすすめ船宿【今週{len(catches)}件】">
  <meta property="og:description" content="{desc}">
  <meta property="og:url" content="{page_url}">
  <meta property="og:type" content="website">
  <meta property="og:site_name" content="船釣り予想">
  <script type="application/ld+json">{{"@context":"https://schema.org","@type":"BreadcrumbList","itemListElement":[{{"@type":"ListItem","position":1,"name":"トップ","item":"{SITE_URL}/"}},{{"@type":"ListItem","position":2,"name":"{fish}の釣果","item":"{SITE_URL}/fish/{fish_encoded}.html"}},{{"@type":"ListItem","position":3,"name":"{area}の{fish}釣果","item":"{page_url}"}}]}}</script>
  {ADSENSE_TAG}
  <style>{fish_area_css}</style>
</head><body>
<header>
  <h1>🎣 {area}の{fish}釣果情報</h1>
  <p>今週の釣果: {len(catches)}件{max_cnt_str}</p>
</header>
<nav>
  <a href="../index.html">← トップへ戻る</a>
  <span style="color:#1a4060">|</span>
  <a href="../fish/{fish}.html">{fish}の全釣果（関東）</a>
  <span style="color:#1a4060">|</span>
  <a href="../area/{area}.html">{area}の全魚種釣果</a>
</nav>
<div class="wrap">
  <h2>🏆 船宿ランキング（今週）</h2>
  <table><tr><th>#</th><th>船宿</th><th>釣果件数</th><th>最高釣果</th><th>割合</th></tr>{rank_rows}</table>
  <h2>📋 最近の釣果 ({len(catches)}件)</h2>
  <table><tr><th>日付</th><th>船宿</th><th>数量</th><th>大きさ</th><th>重量</th></tr>{rows}</table>
</div>
{DATA_NOTE_HTML}
<footer>
  <p><a href="../contact.html">お問い合わせ</a> | <a href="../privacy.html">プライバシーポリシー</a></p>
  <p style="margin-top:8px">© 2026 船釣り予想. All rights reserved.</p>
  <p style="margin-top:6px;font-size:11px;color:#4a6a8a">最終更新: {crawled_at}</p>
</footer>
</body></html>"""
        with open(f"fish_area/{fish}_{area}.html", "w", encoding="utf-8") as fp:
            fp.write(html)
        count += 1
    print(f"魚種×港ページ: {count} 件生成 → fish_area/*.html")

# ============================================================
# calendar.html
# ============================================================
def build_calendar_page(crawled_at=""):
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
  <style>*{{box-sizing:border-box;margin:0;padding:0}}body{{font-family:'Helvetica Neue',Arial,sans-serif;background:#0a1628;color:#e0e8f0}}header{{background:#0d2137;padding:16px 24px;border-bottom:2px solid #1a6ea8}}header h1{{font-size:20px;color:#4db8ff}}nav{{background:#081020;padding:8px 24px}}nav a{{color:#7a9bb5;text-decoration:none;font-size:13px}}.wrap{{max-width:900px;margin:0 auto;padding:20px 16px;overflow-x:auto}}h2{{font-size:15px;color:#4db8ff;border-left:4px solid #4db8ff;padding-left:10px;margin:24px 0 12px}}table{{border-collapse:collapse;font-size:13px;width:100%}}th{{background:#0d2137;color:#4db8ff;padding:8px 6px;text-align:center;min-width:36px}}th.cur-month{{background:#1a6ea8;color:#fff}}td{{padding:6px;text-align:center;border-bottom:1px solid #081020}}td.fish-name{{text-align:left;font-weight:bold;min-width:90px}}td.fish-name a{{color:#e0e8f0;text-decoration:none}}td.fish-name a:hover{{color:#4db8ff}}td.peak-count{{background:#e85d04;color:#fff}}td.peak-size{{background:#7209b7;color:#fff}}td.mid{{background:#1a6ea8;color:#fff}}td.low{{background:#0d2137;color:#444}}td.cur-month{{outline:2px solid #fff;outline-offset:-2px}}.legend{{display:flex;gap:16px;margin:16px 0;font-size:12px}}.leg{{display:flex;align-items:center;gap:6px}}.leg-dot{{width:14px;height:14px;border-radius:2px}}footer{{background:#081020;border-top:1px solid #1a3050;padding:20px;text-align:center;font-size:12px;color:#7a9bb5;margin-top:40px}}footer a{{color:#4db8ff;text-decoration:none}}.data-note{{max-width:900px;margin:20px auto 0;padding:0 16px}}.data-note details{{background:#0d2137;border:1px solid #1a4060;border-radius:8px;padding:10px 14px}}.data-note summary{{color:#7a9bb5;font-size:12px;cursor:pointer;user-select:none}}.data-note ul{{margin-top:8px;padding-left:16px;color:#5a8aaa;font-size:11px;line-height:1.9}}</style>
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
{DATA_NOTE_HTML}
<footer>
  <p><a href="contact.html">お問い合わせ</a> | <a href="privacy.html">プライバシーポリシー</a></p>
  <p style="margin-top:8px">© 2026 船釣り予想. All rights reserved.</p>
  <p style="margin-top:6px;font-size:11px;color:#4a6a8a">最終更新: {crawled_at}</p>
</footer>
</body></html>"""

# ============================================================
# メイン
# ============================================================
CSV_HEADER = ["ship","area","date","fish","cnt_min","cnt_max","cnt_avg",
              "size_min","size_max","kg_min","kg_max","is_boat","point_place","point_depth"]

def save_daily_csv(catches):
    """当日の釣果をdata/YYYY-MM.csvに追記（重複スキップ）"""
    os.makedirs("data", exist_ok=True)
    today = datetime.now().strftime("%Y/%m/%d")
    # 月ごとにファイル分割
    ym = datetime.now().strftime("%Y-%m")
    filepath = os.path.join("data", f"{ym}.csv")

    # 既存レコードのキーセットを読み込んで重複チェック
    existing_keys = set()
    if os.path.exists(filepath):
        with open(filepath, encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                key = (row["ship"], row["area"], row["date"], row["fish"])
                existing_keys.add(key)

    # 本日分のみ追記
    new_rows = []
    for c in catches:
        if c.get("date") != today:
            continue
        for fish in (c["fish"] or ["不明"]):
            key = (c["ship"], c["area"], c["date"], fish)
            if key in existing_keys:
                continue
            cr = c.get("count_range") or {}
            sc = c.get("size_cm")    or {}
            wk = c.get("weight_kg") or {}
            new_rows.append({
                "ship":        c["ship"],
                "area":        c["area"],
                "date":        c["date"],
                "fish":        fish,
                "cnt_min":     cr.get("min", ""),
                "cnt_max":     cr.get("max", ""),
                "cnt_avg":     c["count_avg"] if c.get("count_avg") is not None else "",
                "size_min":    sc.get("min", ""),
                "size_max":    sc.get("max", ""),
                "kg_min":      wk.get("min", ""),
                "kg_max":      wk.get("max", ""),
                "is_boat":     1 if cr.get("is_boat") else 0,
                "point_place": c.get("point_place") or "",
                "point_depth": c.get("point_depth") or "",
            })

    if not new_rows:
        return 0

    write_header = not os.path.exists(filepath)
    with open(filepath, "a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_HEADER)
        if write_header:
            writer.writeheader()
        writer.writerows(new_rows)

    return len(new_rows)


def main():
    all_catches = []
    errors = []
    now = datetime.now()
    crawled_at = now.strftime("%Y/%m/%d %H:%M")
    year = now.year
    fv_count  = sum(1 for s in SHIPS if s.get("source", "fishing-v") == "fishing-v")
    gyo_count = sum(1 for s in SHIPS if s.get("source") == "gyo")
    print(f"=== 関東船釣りクローラー v5.7 開始: {crawled_at} ===")
    print(f"対象: {len(SHIPS)} 船宿（釣りビジョン:{fv_count} / gyo.ne.jp:{gyo_count}）\n")

    for s in SHIPS:
        source = s.get("source", "fishing-v")
        print(f"  [{s['area']}] {s['name']} ({source}) ...", end=" ", flush=True)
        if source == "gyo":
            url  = GYO_BASE_URL.format(cid=s["cid"])
            html = fetch_gyo(url)
            if not html:
                errors.append(s["name"]); print("エラー"); continue
            catches = parse_catches_gyo(html, s["name"], s["area"], year)
        else:
            url  = BASE_URL.format(sid=s["sid"])
            html = fetch(url)
            if not html:
                errors.append(s["name"]); print("エラー"); continue
            catches = parse_catches_from_html(html, s["name"], s["area"], year)
        print(f"{len(catches)} 件")
        all_catches.extend(catches)
        time.sleep(0.8)

    # 重複排除
    before = len(all_catches)
    all_catches = dedup_catches(all_catches)
    dup_removed = before - len(all_catches)
    if dup_removed:
        print(f"重複排除: {dup_removed} 件削除")

    # 異常値フラグ付け（データは保持、集計・表示からは除外）
    for c in all_catches:
        c["anomaly"] = not validate_catch(c)
    anomaly_count = sum(1 for c in all_catches if c.get("anomaly"))
    if anomaly_count:
        print(f"異常値フラグ: {anomaly_count} 件（catches.jsonに保存、表示から除外）")

    # 表示・集計用は正常値のみ
    valid_catches = [c for c in all_catches if not c.get("anomaly")]

    history = load_history()
    history = update_history(valid_catches, history)

    # 日次CSV蓄積
    csv_added = save_daily_csv(all_catches)
    if csv_added:
        print(f"CSV保存: {csv_added} 件追記 → data/{datetime.now().strftime('%Y-%m')}.csv")

    with open("catches.json", "w", encoding="utf-8") as f:
        json.dump({"crawled_at": crawled_at, "total": len(all_catches), "valid": len(valid_catches),
                   "anomaly": anomaly_count, "errors": errors, "data": all_catches}, f, ensure_ascii=False, indent=2)
    with open("index.html", "w", encoding="utf-8") as f:
        f.write(build_html(valid_catches, crawled_at, history))
    build_fish_pages(valid_catches, history, crawled_at)
    build_area_pages(valid_catches, history, crawled_at)
    build_fish_area_pages(valid_catches, crawled_at)
    with open("calendar.html", "w", encoding="utf-8") as f:
        f.write(build_calendar_page(crawled_at))
    print(f"\n=== 完了 ===")
    print(f"釣果: {len(all_catches)} 件（有効: {len(valid_catches)} / 異常値: {anomaly_count} / 重複除外: {dup_removed}）")
    print(f"エラー: {errors or 'なし'}")
    print(f"出力: catches.json / index.html / fish/*.html / area/*.html / calendar.html")

if __name__ == "__main__":
    main()
