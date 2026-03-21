#!/usr/bin/env python3
"""
関東船釣り情報クローラー v4 (fishing-v.jp版)
対象: fishing-v.jp（釣りビジョン）
実行: python3 crawler.py
出力: catches.json / index.html / fish/*.html / calendar.html
"""
import re, json, time, os
from datetime import datetime
from urllib.request import urlopen, Request
from urllib.error import URLError
from html.parser import HTMLParser

# ============================================================
# 船宿リスト（fishing-v.jp の s= パラメータ）
# ============================================================
SHIPS = [
    # 千葉・外房
    {"area": "外川",        "name": "孝進丸",       "sid": 749},
    {"area": "片貝",        "name": "勇幸丸",       "sid": 58},
    {"area": "大原",        "name": "義之丸",       "sid": 61},
    {"area": "勝浦松部港",  "name": "和八丸",       "sid": 1480},
    # 千葉・内房
    {"area": "勝山",        "name": "新盛丸",       "sid": 121},
    {"area": "富津",        "name": "川崎丸",       "sid": 141},
    # 千葉・東京湾奥
    {"area": "江戸川放水路","name": "たかはし遊船", "sid": 145},
    {"area": "浦安",        "name": "吉久",         "sid": 147},
    # 神奈川・金沢八景
    {"area": "金沢八景",    "name": "一之瀬丸",     "sid": 186},
    {"area": "金沢漁港",    "name": "忠彦丸",       "sid": 185},
    {"area": "金沢八景",    "name": "米元釣船店",   "sid": 188},
    {"area": "金沢八景",    "name": "野毛屋",       "sid": 192},
    # 神奈川・久比里
    {"area": "久比里",      "name": "山下丸",       "sid": 209},
    {"area": "久比里",      "name": "山天丸",       "sid": 211},
    {"area": "久比里",      "name": "みのすけ丸",   "sid": 210},
    # 神奈川・久里浜
    {"area": "久里浜",      "name": "大正丸",       "sid": 689},
    # 神奈川・松輪
    {"area": "松輪",        "name": "瀬戸丸",       "sid": 659},
    # 神奈川・長井
    {"area": "長井",        "name": "はら丸",       "sid": 218},
    {"area": "長井",        "name": "丸八丸",       "sid": 12224},
    # 神奈川・葉山
    {"area": "葉山鐙摺",    "name": "愛正丸",       "sid": 232},
    # 神奈川・腰越
    {"area": "腰越",        "name": "飯岡丸",       "sid": 235},
    # 神奈川・茅ヶ崎
    {"area": "茅ヶ崎",      "name": "ちがさき丸",   "sid": 795},
    # 神奈川・平塚
    {"area": "平塚",        "name": "庄三郎丸",     "sid": 244},
    # 神奈川・小田原
    {"area": "小田原早川",  "name": "平安丸",       "sid": 1700},
    # 静岡・宇佐美
    {"area": "宇佐美",      "name": "秀正丸",       "sid": 270},
    # 静岡・戸田
    {"area": "戸田",        "name": "福将丸",       "sid": 1875},
]

BASE_URL = "https://www.fishing-v.jp/choka/choka_detail.php?s={sid}"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

FISH_MAP = {
    "アジ":       ["アジ", "LTアジ", "ライトアジ"],
    "タチウオ":   ["タチウオ"],
    "フグ":       ["フグ", "トラフグ", "ショウサイフグ"],
    "カワハギ":   ["カワハギ"],
    "マダイ":     ["マダイ", "真鯛"],
    "シロギス":   ["シロギス", "キス"],
    "イサキ":     ["イサキ"],
    "ヤリイカ":   ["ヤリイカ"],
    "スルメイカ": ["スルメイカ"],
    "マダコ":     ["タコ", "マダコ"],
    "カサゴ":     ["カサゴ", "オニカサゴ"],
    "メバル":     ["メバル"],
    "ワラサ":     ["ワラサ", "イナダ", "ブリ"],
    "アマダイ":   ["アマダイ"],
    "メダイ":     ["メダイ"],
    "サワラ":     ["サワラ"],
    "ヒラメ":     ["ヒラメ"],
    "マゴチ":     ["マゴチ"],
    "キンメダイ": ["キンメダイ", "キンメ"],
    "クロムツ":   ["クロムツ", "ムツ"],
    "マルイカ":   ["マルイカ"],
    "カンパチ":   ["カンパチ"],
    "マハタ":     ["マハタ"],
}

Z2H = str.maketrans("０１２３４５６７８９．", "0123456789.")


class TableParser(HTMLParser):
    """fishing-v.jpの釣果テーブルをパースする"""
    def __init__(self):
        super().__init__()
        self.tables = []
        self._in_table = False
        self._in_row = False
        self._in_cell = False
        self._current_table = []
        self._current_row = []
        self._current_cell = []
        self._skip = False
        self._depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip = True
        if tag == "table":
            self._depth += 1
            if self._depth == 1:
                self._in_table = True
                self._current_table = []
        elif tag == "tr" and self._in_table and self._depth == 1:
            self._in_row = True
            self._current_row = []
        elif tag in ("td", "th") and self._in_row:
            self._in_cell = True
            self._current_cell = []
        elif tag == "br" and self._in_cell:
            self._current_cell.append(" ")

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self._skip = False
        if tag == "table":
            if self._depth == 1 and self._current_table:
                self.tables.append(self._current_table)
                self._in_table = False
            self._depth -= 1
        elif tag == "tr" and self._in_row:
            if self._current_row:
                self._current_table.append(self._current_row)
            self._in_row = False
        elif tag in ("td", "th") and self._in_cell:
            self._current_row.append("".join(self._current_cell).strip())
            self._in_cell = False

    def handle_data(self, data):
        if not self._skip and self._in_cell:
            self._current_cell.append(data)


def guess_fish(t):
    return [f for f, kws in FISH_MAP.items() if any(k in t for k in kws)] or ["不明"]


def parse_num(s):
    return s.translate(Z2H)


def extract_count(t):
    t = parse_num(t)
    m = re.search(r"(\d+)[～〜~](\d+)\s*[匹本尾枚杯]", t)
    if m:
        return {"min": int(m[1]), "max": int(m[2])}
    m = re.search(r"(\d+)\s*[匹本尾枚杯]", t)
    if m:
        v = int(m[1])
        return {"min": v, "max": v}
    return None


def extract_size(t):
    t = parse_num(t)
    m = re.search(r"(\d+\.?\d*)[～〜~](\d+\.?\d*)\s*kg", t, re.I)
    if m:
        return {"min": float(m[1]), "max": float(m[2]), "unit": "kg"}
    m = re.search(r"(\d+\.?\d*)\s*kg", t, re.I)
    if m:
        v = float(m[1])
        return {"min": v, "max": v, "unit": "kg"}
    m = re.search(r"(\d+)[～〜~](\d+)\s*cm", t, re.I)
    if m:
        return {"min": int(m[1]), "max": int(m[2]), "unit": "cm"}
    m = re.search(r"(\d+)\s*cm", t, re.I)
    if m:
        v = int(m[1])
        return {"min": v, "max": v, "unit": "cm"}
    return None


def parse_catches_from_tables(tables, ship, area, year):
    """
    fishing-v.jp のテーブル構造から釣果データを取得。
    ヘッダー例: [No, 魚種, 匹数, 大きさ, 重さ, 特記, ポイント]
    """
    results = []
    now = datetime.now()
    current_month = now.month
    current_day = now.day

    for table in tables:
        if not table:
            continue
        header = table[0]
        header_str = " ".join(header)
        if "魚種" not in header_str and "匹数" not in header_str:
            continue

        fish_idx = next((i for i, h in enumerate(header) if "魚種" in h), 1)
        count_idx = next((i for i, h in enumerate(header) if "匹数" in h), 2)
        size_idx = next((i for i, h in enumerate(header) if "大きさ" in h), 3)
        weight_idx = next((i for i, h in enumerate(header) if "重さ" in h), 4)

        for row in table[1:]:
            if len(row) <= fish_idx:
                continue
            fish_name = row[fish_idx].strip()
            if not fish_name or fish_name in ("魚種", "-", "－", ""):
                continue

            count_str = row[count_idx].strip() if count_idx < len(row) else ""
            size_str = row[size_idx].strip() if size_idx < len(row) else ""
            weight_str = row[weight_idx].strip() if weight_idx < len(row) else ""

            fishes = guess_fish(fish_name)
            count = extract_count(count_str)
            size = extract_size(weight_str) or extract_size(size_str)

            results.append({
                "ship": ship,
                "area": area,
                "date": f"{year}/{current_month:02d}/{current_day:02d}",
                "month": current_month,
                "day": current_day,
                "catch_raw": f"{fish_name} {count_str} {size_str} {weight_str}".strip(),
                "fish": fishes,
                "count_range": count,
                "size_range": size,
            })

    return results


def fetch(url):
    try:
        req = Request(url, headers={"User-Agent": USER_AGENT})
        with urlopen(req, timeout=20) as r:
            raw = r.read()
        for enc in ("utf-8", "shift_jis", "euc-jp"):
            try:
                return raw.decode(enc)
            except Exception:
                pass
        return raw.decode("utf-8", errors="replace")
    except URLError as e:
        print(f"ERROR: {e}")
        return None


# ============================================================
# シーズンデータ・HTML生成
# ============================================================

SEASON_DATA = {
    "アジ":       [3,3,3,4,4,5,5,4,4,4,4,3],
    "タチウオ":   [1,1,1,1,2,3,5,5,5,4,3,2],
    "フグ":       [3,3,4,4,3,2,2,2,3,4,4,3],
    "カワハギ":   [2,2,2,2,2,2,3,4,5,5,4,3],
    "マダイ":     [2,2,3,5,5,4,3,3,3,4,4,3],
    "シロギス":   [1,1,2,3,5,5,5,4,3,2,1,1],
    "イサキ":     [1,1,2,3,4,5,5,4,3,2,1,1],
    "ヤリイカ":   [4,4,3,2,2,2,2,2,2,3,4,5],
    "スルメイカ": [1,1,1,2,3,4,5,5,4,3,2,1],
    "マダコ":     [1,1,1,2,3,5,5,5,4,3,2,1],
    "カサゴ":     [4,4,4,3,3,2,2,2,3,3,4,4],
    "メバル":     [4,4,4,3,3,2,2,2,2,3,4,4],
    "ワラサ":     [2,2,2,2,3,3,4,4,5,5,4,3],
    "ヒラメ":     [4,4,3,3,3,3,3,3,4,5,5,4],
    "アマダイ":   [3,3,3,3,3,3,3,3,4,4,4,4],
    "マゴチ":     [1,1,1,2,4,5,5,5,4,2,1,1],
    "キンメダイ": [4,4,4,3,3,3,3,3,3,4,4,4],
}

SEASON_TYPE = {
    "アジ":       ["数","数","数","数","型","型","型","数","数","数","数","数"],
    "タチウオ":   ["数","数","数","数","数","数","型","型","数","数","数","数"],
    "マダイ":     ["数","数","型","型","型","数","数","数","数","型","型","数"],
    "シロギス":   ["数","数","数","数","数","型","型","数","数","数","数","数"],
    "ヤリイカ":   ["型","型","数","数","数","数","数","数","数","数","型","型"],
    "ヒラメ":     ["型","型","型","数","数","数","数","数","型","型","型","型"],
}

COMMENTS = {
    5: ["爆釣モード突入！今すぐ行くべき！", "今季最高潮！チャンスを逃すな！"],
    4: ["かなり好調！釣り物としておすすめ！", "良型混じりで数も出ています！"],
    3: ["コンスタントに釣れています", "安定した釣果が続いています"],
    2: ["やや渋め。腕の見せどころ", "数は出ないが型狙いも一手"],
    1: ["端境期。好転待ちの状況", "オフシーズン入り。次の季節に期待"],
}


def get_season_score(fish, month):
    s = SEASON_DATA.get(fish, [])
    return s[month - 1] if s else 0


def build_season_bar(fish, current_month):
    scores = SEASON_DATA.get(fish, [3]*12)
    types  = SEASON_TYPE.get(fish, [""]*12)
    cells = ""
    for i, (sc, tp) in enumerate(zip(scores, types)):
        m = i + 1
        is_now = "now" if m == current_month else ""
        cls = ("peak-count" if tp == "数" else "peak-size") if sc >= 4 else ("mid" if sc == 3 else "low")
        cells += f'<div class="sb-cell {cls} {is_now}" title="{m}月">{m}</div>'
    label = ""
    if fish in SEASON_TYPE:
        label = '<div class="sb-legend"><span class="leg-count">■数狙い</span><span class="leg-size">■型狙い</span></div>'
    return f'<div class="season-bar">{cells}</div>{label}'


def calc_targets(data):
    cur_month = datetime.now().month
    fish_counts = {}
    for c in data:
        for f in c["fish"]:
            if f != "不明":
                fish_counts[f] = fish_counts.get(f, 0) + 1
    targets = []
    for fish, cnt in sorted(fish_counts.items(), key=lambda x: -x[1])[:10]:
        score = get_season_score(fish, cur_month)
        comment = COMMENTS.get(score, COMMENTS[3])[hash(fish) % 2]
        targets.append({"fish": fish, "count": cnt, "score": score, "comment": comment})
    return targets[:5]


def build_target_section(targets):
    if not targets:
        return "<p style='color:#7a9bb5'>データ収集中です。しばらくお待ちください。</p>"
    cards = "".join(f"""
    <div class="target-card">
      <div class="tc-fish">{t["fish"]}</div>
      <div class="tc-bar">{"█"*t["score"]}{"░"*(5-t["score"])}</div>
      <div class="tc-comment">{t["comment"]}</div>
      <div class="tc-count">直近釣果: {t["count"]}件</div>
    </div>""" for t in targets)
    return f'<div class="target-grid">{cards}</div>'


CSS = """
    *{box-sizing:border-box;margin:0;padding:0}
    body{font-family:'Helvetica Neue',Arial,sans-serif;background:#0a1628;color:#e0e8f0}
    header{background:#0d2137;padding:16px 24px;border-bottom:2px solid #1a6ea8}
    header h1{font-size:22px;color:#4db8ff}
    header p{font-size:12px;color:#7a9bb5;margin-top:4px}
    nav{background:#081020;padding:8px 24px;display:flex;gap:16px;flex-wrap:wrap}
    nav a{color:#7a9bb5;text-decoration:none;font-size:13px}
    nav a:hover{color:#4db8ff}
    .wrap{max-width:1100px;margin:0 auto;padding:20px 16px}
    h2{font-size:15px;color:#4db8ff;border-left:4px solid #4db8ff;padding-left:10px;margin:24px 0 12px}
    .grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(140px,1fr));gap:10px}
    .fc{background:#0d2137;border:1px solid #1a4060;border-radius:8px;padding:12px;cursor:pointer;transition:border-color .2s}
    .fc:hover{border-color:#4db8ff}
    .fc-summary{text-align:center}
    .fn{font-size:16px;font-weight:bold;color:#fff}
    .fk{font-size:12px;color:#4db8ff;margin-top:4px}
    .fa{font-size:11px;color:#7a9bb5;margin-top:2px}
    .fc-detail{margin-top:12px;border-top:1px solid #1a4060;padding-top:10px}
    .season-bar{display:flex;gap:2px;margin-top:8px;justify-content:center}
    .sb-cell{width:18px;height:14px;border-radius:2px;font-size:8px;color:#fff;display:flex;align-items:center;justify-content:center}
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
    table{width:100%;border-collapse:collapse;font-size:13px}
    th{background:#0d2137;color:#4db8ff;padding:8px;text-align:left;border-bottom:1px solid #1a4060}
    td{padding:8px;border-bottom:1px solid #0d2137}
    tr:hover td{background:#0d2137}
    .note{font-size:11px;color:#7a9bb5;text-align:right;margin-top:8px}
    .target-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:12px}
    .target-card{background:#0d2137;border:1px solid #1a4060;border-radius:8px;padding:14px}
    .tc-fish{font-size:18px;font-weight:bold;color:#fff;margin-bottom:4px}
    .tc-bar{font-size:16px;color:#e85d04;letter-spacing:2px;margin-bottom:6px}
    .tc-comment{font-size:12px;color:#c8d8e8;line-height:1.5;margin-bottom:6px}
    .tc-count{font-size:11px;color:#7a9bb5}
    footer{background:#081020;border-top:1px solid #1a3050;padding:20px 24px;text-align:center;font-size:12px;color:#7a9bb5;margin-top:40px}
    footer a{color:#4db8ff;text-decoration:none}
    footer a:hover{text-decoration:underline}
"""


def build_html(catches, crawled_at):
    now = datetime.now()
    current_month = now.month
    fish_summary = {}
    for c in catches:
        for f in c["fish"]:
            if f != "不明":
                fish_summary.setdefault(f, []).append(c)

    cards = ""
    for fish, cs in sorted(fish_summary.items(), key=lambda x: -len(x[1])):
        areas = list(dict.fromkeys(c["area"] for c in cs[:3]))
        season_bar = build_season_bar(fish, current_month)
        fish_id = re.sub(r'[^\w]', '_', fish)

        daily_rows = ""
        for c in sorted(cs, key=lambda x: x["date"] or "", reverse=True)[:5]:
            cnt = f"{c['count_range']['min']}〜{c['count_range']['max']}" if c["count_range"] and c["count_range"]["min"] != c["count_range"]["max"] else (str(c["count_range"]["min"]) if c["count_range"] else "")
            sz = ""
            if c["size_range"]:
                mn, mx, unit = c["size_range"]["min"], c["size_range"]["max"], c["size_range"].get("unit", "cm")
                sz = f"{mn}〜{mx}{unit}" if mn != mx else f"{mn}{unit}"
            daily_rows += f"<tr><td>{c['date'] or '-'}</td><td>{c['area']}</td><td>{c['ship']}</td><td>{cnt}</td><td>{sz}</td></tr>"

        ship_counts = {}
        for c in cs:
            ship_counts[c["ship"]] = ship_counts.get(c["ship"], 0) + 1
        weekly_rows = ""
        for sn, cnt in sorted(ship_counts.items(), key=lambda x: -x[1])[:10]:
            pct = int(cnt / len(cs) * 100) if cs else 0
            weekly_rows += f'<tr><td>{sn}</td><td>{cnt}件</td><td><div class="bar-wrap"><div class="bar-fill" style="width:{pct}%"></div></div></td></tr>'

        cards += f"""
        <div class="fc" onclick="toggleDetail(this)">
          <div class="fc-summary">
            <div class="fn">{fish}</div><div class="fk">{len(cs)}件</div>
            <div class="fa">{" / ".join(areas)}</div>{season_bar}
          </div>
          <div class="fc-detail" style="display:none">
            <div class="tab-wrap">
              <button class="tab-btn active" onclick="switchTab(event,'daily-{fish_id}','weekly-{fish_id}')">デイリー</button>
              <button class="tab-btn" onclick="switchTab(event,'weekly-{fish_id}','daily-{fish_id}')">ウィークリー</button>
            </div>
            <div id="daily-{fish_id}"><table class="rank-table"><tr><th>日付</th><th>エリア</th><th>船宿</th><th>数量</th><th>サイズ</th></tr>{daily_rows or '<tr><td colspan=5 style="color:#7a9bb5">データなし</td></tr>'}</table></div>
            <div id="weekly-{fish_id}" style="display:none"><table class="rank-table"><tr><th>船宿</th><th>釣果数</th><th>割合</th></tr>{weekly_rows or '<tr><td colspan=3 style="color:#7a9bb5">データなし</td></tr>'}</table></div>
          </div>
        </div>"""

    rows = ""
    for c in sorted(catches, key=lambda x: x["date"] or "", reverse=True)[:5]:
        cnt = f"{c['count_range']['min']}〜{c['count_range']['max']}" if c["count_range"] and c["count_range"]["min"] != c["count_range"]["max"] else (str(c["count_range"]["min"]) if c["count_range"] else "")
        sz = ""
        if c["size_range"]:
            mn, mx, unit = c["size_range"]["min"], c["size_range"]["max"], c["size_range"].get("unit", "cm")
            sz = f"{mn}〜{mx}{unit}" if mn != mx else f"{mn}{unit}"
        rows += f"<tr><td>{c['date'] or '-'}</td><td>{c['area']}</td><td>{c['ship']}</td><td>{'・'.join(c['fish'])}</td><td>{cnt}</td><td>{sz}</td></tr>"

    targets = calc_targets(catches)
    target_html = build_target_section(targets)

    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
  <meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
  <title>関東船釣り釣果情報 | 今日何が釣れてる？</title>
  <meta name="description" content="関東エリア（神奈川・千葉）の船宿釣果をリアルタイム集計。今週の狙い目魚種、釣れている船宿ランキングを毎日更新。">
  <style>{CSS}</style>
</head>
<body>
  <header>
    <h1>🎣 関東船釣り釣果情報</h1>
    <p>今日、何が釣れてる？ 関東エリアの船宿釣果をリアルタイム集計</p>
  </header>
  <nav><a href="index.html">🏠 トップ</a><a href="calendar.html">📅 釣りものカレンダー</a></nav>
  <div class="wrap">
    <h2>🎯 今週の狙い目</h2>{target_html}
    <h2>🐟 釣れている魚</h2>
    <p style="font-size:12px;color:#7a9bb5;margin-bottom:10px">魚種をタップするとランキングを表示</p>
    <div class="grid">{cards}</div>
    <h2>📋 最新の釣果</h2>
    <table><tr><th>日付</th><th>エリア</th><th>船宿</th><th>魚種</th><th>数量</th><th>サイズ</th></tr>{rows}</table>
    <p class="note">最終更新: {crawled_at} ／ 総件数: {len(catches)} 件</p>
  </div>
  <footer>
    <p><a href="contact.html">お問い合わせ</a> | <a href="privacy.html">プライバシーポリシー</a></p>
    <p style="margin-top:8px">© 2024 船釣り予想. All rights reserved.</p>
  </footer>
  <script>
    function toggleDetail(el){{const d=el.querySelector('.fc-detail');if(d)d.style.display=d.style.display==='none'?'block':'none';}}
    function switchTab(e,showId,hideId){{e.stopPropagation();document.getElementById(showId).style.display='block';document.getElementById(hideId).style.display='none';const w=e.target.closest('.tab-wrap');w.querySelectorAll('.tab-btn').forEach(b=>b.classList.remove('active'));e.target.classList.add('active');}}
  </script>
</body>
</html>"""


def build_fish_pages(data):
    os.makedirs("fish", exist_ok=True)
    now = datetime.now()
    current_month = now.month
    fish_summary = {}
    for c in data:
        for f in c["fish"]:
            if f != "不明":
                fish_summary.setdefault(f, []).append(c)

    for fish, catches in fish_summary.items():
        if len(catches) < 3:
            continue
        season_bar_html = build_season_bar(fish, current_month)
        score = get_season_score(fish, current_month)
        comment = COMMENTS.get(score, COMMENTS[3])[hash(fish) % 2]
        rows = ""
        for c in sorted(catches, key=lambda x: x["date"] or "", reverse=True)[:20]:
            cnt = f"{c['count_range']['min']}〜{c['count_range']['max']}" if c["count_range"] and c["count_range"]["min"] != c["count_range"]["max"] else (str(c["count_range"]["min"]) if c["count_range"] else "")
            sz = ""
            if c["size_range"]:
                mn, mx, unit = c["size_range"]["min"], c["size_range"]["max"], c["size_range"].get("unit", "cm")
                sz = f"{mn}〜{mx}{unit}" if mn != mx else f"{mn}{unit}"
            rows += f"<tr><td>{c['date'] or '-'}</td><td>{c['area']}</td><td>{c['ship']}</td><td>{cnt}</td><td>{sz}</td></tr>"

        html = f"""<!DOCTYPE html>
<html lang="ja"><head>
  <meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
  <title>{fish}の釣果情報 | 関東船釣り予想</title>
  <meta name="description" content="関東エリアの{fish}釣果情報。今週の釣れ具合・おすすめ船宿をリアルタイム集計。">
  <style>*{{box-sizing:border-box;margin:0;padding:0}}body{{font-family:'Helvetica Neue',Arial,sans-serif;background:#0a1628;color:#e0e8f0}}header{{background:#0d2137;padding:16px 24px;border-bottom:2px solid #1a6ea8}}header h1{{font-size:20px;color:#4db8ff}}nav{{background:#081020;padding:8px 24px}}nav a{{color:#7a9bb5;text-decoration:none;font-size:13px}}.wrap{{max-width:900px;margin:0 auto;padding:20px 16px}}h2{{font-size:15px;color:#4db8ff;border-left:4px solid #4db8ff;padding-left:10px;margin:24px 0 12px}}.season-bar{{display:flex;gap:2px;margin:12px 0}}.sb-cell{{width:22px;height:18px;border-radius:2px;font-size:10px;color:#fff;display:flex;align-items:center;justify-content:center}}.sb-cell.peak-count{{background:#e85d04}}.sb-cell.peak-size{{background:#7209b7}}.sb-cell.mid{{background:#1a6ea8}}.sb-cell.low{{background:#1a3050}}.sb-cell.now{{outline:2px solid #fff;outline-offset:1px}}.comment{{background:#0d2137;border-left:3px solid #e85d04;padding:12px;border-radius:4px;font-size:14px;margin-bottom:16px}}table{{width:100%;border-collapse:collapse;font-size:13px}}th{{background:#0d2137;color:#4db8ff;padding:8px;text-align:left}}td{{padding:8px;border-bottom:1px solid #0d2137}}footer{{background:#081020;border-top:1px solid #1a3050;padding:20px;text-align:center;font-size:12px;color:#7a9bb5;margin-top:40px}}footer a{{color:#4db8ff;text-decoration:none}}</style>
</head><body>
  <header><h1>🎣 {fish}の釣果情報</h1></header>
  <nav><a href="../index.html">← トップへ戻る</a></nav>
  <div class="wrap">
    <h2>📅 年間シーズン</h2>{season_bar_html}
    <div class="comment">💬 {comment}</div>
    <h2>📋 最近の釣果 ({len(catches)}件)</h2>
    <table><tr><th>日付</th><th>エリア</th><th>船宿</th><th>数量</th><th>サイズ</th></tr>{rows}</table>
  </div>
  <footer><p><a href="../contact.html">お問い合わせ</a> | <a href="../privacy.html">プライバシーポリシー</a></p></footer>
</body></html>"""
        with open(f"fish/{fish}.html", "w", encoding="utf-8") as f:
            f.write(html)


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
            m = i + 1
            is_now = "cur-month" if m == current_month else ""
            cls = ("peak-count" if tp == "数" else "peak-size") if sc >= 4 else ("mid" if sc == 3 else "low")
            label = "◎" if sc >= 4 else ("○" if sc == 3 else "-")
            cells += f'<td class="{cls} {is_now}">{label}</td>'
        rows += f"<tr><td class='fish-name'><a href='fish/{fish}.html'>{fish}</a></td>{cells}</tr>"

    return f"""<!DOCTYPE html>
<html lang="ja"><head>
  <meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
  <title>関東船釣り カレンダー | 月別釣りものガイド</title>
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
  <footer><p><a href="contact.html">お問い合わせ</a> | <a href="privacy.html">プライバシーポリシー</a></p><p style="margin-top:8px">© 2024 船釣り予想. All rights reserved.</p></footer>
</body></html>"""


def main():
    all_catches = []
    errors = []
    now = datetime.now()
    crawled_at = now.strftime("%Y/%m/%d %H:%M")
    year = now.year

    print(f"=== 関東船釣りクローラー v4 (fishing-v.jp) 開始: {crawled_at} ===")
    print(f"対象: {len(SHIPS)} 船宿\n")

    for s in SHIPS:
        url = BASE_URL.format(sid=s["sid"])
        print(f"  [{s['area']}] {s['name']} (s={s['sid']}) ...", end=" ", flush=True)
        html = fetch(url)
        if not html:
            errors.append(s["name"])
            print("エラー")
            continue
        parser = TableParser()
        parser.feed(html)
        catches = parse_catches_from_tables(parser.tables, s["name"], s["area"], year)
        print(f"{len(catches)} 件")
        all_catches.extend(catches)
        time.sleep(0.8)

    with open("catches.json", "w", encoding="utf-8") as f:
        json.dump({"crawled_at": crawled_at, "total": len(all_catches), "errors": errors, "data": all_catches}, f, ensure_ascii=False, indent=2)
    with open("index.html", "w", encoding="utf-8") as f:
        f.write(build_html(all_catches, crawled_at))
    build_fish_pages(all_catches)
    with open("calendar.html", "w", encoding="utf-8") as f:
        f.write(build_calendar_page())

    print(f"\n=== 完了 ===")
    print(f"釣果: {len(all_catches)} 件 ／ エラー: {errors or 'なし'}")
    print(f"出力: catches.json / index.html / fish/*.html / calendar.html")


if __name__ == "__main__":
    main()
