"""
gyo_crawler.py — gyo.ne.jp 専用クローラー
catches_raw_direct.json に生データを差分追記する。

設計方針:
- crawler.py への依存なし（stdlib のみ）
- FISH_MAP 不使用。fish_raw は Table A テキストをそのまま格納
- 長文テキストは kanso_raw へ。余分な抽出ロジックは持たない
- 出力: direct-crawl/catches_raw_direct.json（catches_raw.json と同一15フィールド）
"""

import sys
import json
import os
import re
import time
from datetime import datetime
from html.parser import HTMLParser
from urllib.request import Request, urlopen
from urllib.error import URLError

sys.stdout.reconfigure(encoding="utf-8")

# ============================================================
# 設定
# ============================================================

GYO_BASE_URL    = "https://www.gyo.ne.jp/rep_tsuri_view%7CCID-{cid}.htm"
GYO_HISTORY_URL = "https://www.gyo.ne.jp/rep_tsuri_history_view%7CCID-{cid}%7Chdt-{hdt}%7Cdt-{dt}.htm"
USER_AGENT      = "Mozilla/5.0 (compatible; kanto-fishing-bot/1.0)"

GYO_SHIPS = [
    # parser="ichinose": ≪便名≫ → 「N日の釣果」→ 魚種行 の自由記述（1魚種=1レコード）
    {"cid": "ichinose",  "ship": "一之瀬丸",  "area": "金沢八景", "parser": "ichinose"},
]

# 2026-08-02: 対象を一之瀬丸1船宿に縮小した。
# 他3船宿は別経路でカバー済みで、gyo から取ると二重計上になるため除外する:
#   忠彦丸       … chowari（chowari_id=00703 / data/V2/chowari_*.csv に 2024-04 から継続）
#   米元釣船店   … 釣りビジョン sid=188（+ chowari 00836）
#   勇幸丸       … 釣りビジョン sid=58
# 一之瀬丸は ships.json に存在せず、gyo.ne.jp が唯一のデータ経路。
# 除外した3船宿用のパーサー（parse_gyo_sections / parse_gyo_freetext /
# parse_gyo_yukou）は書式リファレンスとしてファイル下部に残してあるが、呼ばれない。

OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "catches_raw_direct.json")

# ============================================================
# HTML ユーティリティ
# ============================================================

class TableParser(HTMLParser):
    """全 <table> をセルテキストの2次元リストとして抽出する。"""

    def __init__(self):
        super().__init__()
        self.tables  = []   # [ [[cell, ...], ...], ... ]
        self._rows   = []
        self._cells  = []
        self._cell   = None
        self._depth  = 0    # table のネスト深さ

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self._depth += 1
            if self._depth == 1:
                self._rows = []
        elif tag in ("tr",) and self._depth == 1:
            self._cells = []
        elif tag in ("td", "th") and self._depth == 1:
            self._cell = []

    def handle_endtag(self, tag):
        if tag == "table":
            if self._depth == 1:
                # Flush pending row (malformed HTML: missing </tr> before </table>)
                if self._cell is not None:
                    self._cells.append("".join(self._cell).strip())
                    self._cell = None
                if self._cells:
                    self._rows.append(self._cells)
                    self._cells = []
                self.tables.append(self._rows)
                self._rows = []
            self._depth -= 1
        elif tag == "tr" and self._depth == 1:
            if self._cells:
                self._rows.append(self._cells)
            self._cells = []
        elif tag in ("td", "th") and self._depth == 1 and self._cell is not None:
            self._cells.append("".join(self._cell).strip())
            self._cell = None

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)

    def handle_entityref(self, name):
        # &nbsp; 等 → スペース
        if self._cell is not None:
            self._cell.append(" ")

    def handle_charref(self, name):
        if self._cell is not None:
            self._cell.append(" ")


def table_text(table):
    """table（2次元リスト）の全セルを結合したテキストを返す。"""
    return " ".join(cell for row in table for cell in row)


def normalize_text(s):
    """全角スペース・制御文字を正規化し、前後の空白を除去する。"""
    s = re.sub(r"[\u3000\xa0\ufffd]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

# ============================================================
# 一之瀬丸パーサー（2026-08-02〜 唯一の対象船宿）
# ============================================================
#
# ページ構造（rep_tsuri_view|CID-ichinose.htm）:
#
#   【釣果速報】８月２日（日）晴れ      ← ページ発行日 = アンカー日
#   ≪イサキ船≫                        ← 便（セクション）
#   １日の釣果                          ← その便の釣行日（日のみ。月はアンカーから確定）
#   イサキ ２０～３４ｃｍ ４～３１匹    ← 魚種行（複数可 = リレー船）
#   他タカベ、ウマヅラ                  ← 外道
#   ＜集合６：３０ 出船７：００ …＞     ← タックル情報
#   久里浜～剣崎沖２０～３０ｍ！！      ← 実況コメント（ポイントを含む）
#   ３日（月）出船確定！！…             ← 予約案内（捨てる）
#
# 重要: ページは「各便の最新釣果」を並べたもので、便ごとに日付が違う。
# 旧実装は history URL を7日ぶん叩いて同じ内容に URL の日付を貼っていたため、
# 373件中237件(63%)が水増しになっていた（2026-08-02 に発見）。
# 現実装は最新ページ1本だけを取得し、日付は必ず本文の「N日の釣果」から確定する。

_Z2H_NUM = str.maketrans("０１２３４５６７８９．", "0123456789.")

# 「８月２日（日）晴れ」→ アンカー日
_RE_PAGE_DATE = re.compile(r"(\d{1,2})月\s*(\d{1,2})日")

# 「１日の釣果」「２日乗合２隻の釣果」「１９日の釣果」
_RE_TRIP_DATE = re.compile(r"^(\d{1,2})日.{0,14}釣果")

# 「イサキ 20～34cm 4～31匹」「マダコ 0.3～1.5kg 0～10杯」「カサゴ主体 15～26cm 30～63匹」
# サイズ・数はレンジでない単一値も許容する。
_RE_FISH_LINE = re.compile(
    r"^([^\d\s]{1,12}?)(?:主体)?\s*"
    r"([\d.]+)(?:\s*[~〜～]\s*([\d.]+))?\s*(cm|㎝|ｃｍ|kg|㎏|ｋｇ)\s*"
    r"([\d.]+)(?:\s*[~〜～]\s*([\d.]+))?\s*([匹尾杯本枚])",
    re.I,
)

# 予約案内・注意書き（kanso_raw から除外する）
_RE_RESERVATION = re.compile(
    r"^\d{1,2}日\s*[（(]|ご予約|予約受付|お休みします|出船確定|^※|募集|お知らせ"
)

# セクション見出しでない ≪…≫ 行（タックル・内部ラベル）
_RE_NOT_HEADER = re.compile(r"集合|出船|納竿|料金|オモリ|道糸|ハリス|釣果|コメント")


def _fish_line_to_record(line):
    """魚種行を (fish, size_raw, weight_raw, count_raw) に分解する。非該当は None。"""
    m = _RE_FISH_LINE.match(line)
    if not m:
        return None
    fish = m.group(1).strip("・、 ")
    if len(fish) < 2:
        return None

    v1, v2, unit  = m.group(2), m.group(3) or m.group(2), m.group(4)
    c1, c2, cunit = m.group(5), m.group(6) or m.group(5), m.group(7)

    is_kg = unit.lower() in ("kg", "㎏", "ｋｇ")
    size_raw   = "" if is_kg else f"{v1}～{v2} cm"
    weight_raw = f"{v1}～{v2} kg" if is_kg else ""
    count_raw  = f"{c1}～{c2} {cunit}"
    return fish, size_raw, weight_raw, count_raw


def parse_ichinose(html, ship, area):
    """一之瀬丸ページから釣果レコードのリストを返す（1魚種 = 1レコード）。

    日付は必ず本文の「N日の釣果」から確定する。N がアンカー日より大きい場合は前月。
    釣行日が確定できないセクションは捨てる（URL 日付での代替はしない）。
    """
    idx = html.find("釣果速報")
    if idx < 0:
        print("    WARN: 【釣果速報】が見つからない → スキップ")
        return []

    lines = html_to_lines(html[idx:])
    if not lines:
        return []

    # ── アンカー日（ページ発行日）─────────────────────────────
    now = datetime.now()
    m   = _RE_PAGE_DATE.search(lines[0].translate(_Z2H_NUM))
    if not m:
        print(f"    WARN: ページ日付をパースできない: {lines[0][:40]}")
        return []
    a_month, a_day = int(m.group(1)), int(m.group(2))
    a_year = now.year
    # 年跨ぎ: 1月に 12月のアンカーが出た場合は前年
    if a_month > now.month + 1:
        a_year -= 1
    try:
        anchor = datetime(a_year, a_month, a_day)
    except ValueError:
        print(f"    WARN: 不正なページ日付 {a_year}/{a_month}/{a_day}")
        return []

    # ── セクション分割 ─────────────────────────────────────────
    sections       = []   # [(便名, [body lines]), ...]
    current_header = None
    current_body   = []

    for line in lines[1:]:
        if re.fullmatch(r"[≪《].+[≫》]", line) and not _RE_NOT_HEADER.search(line):
            if current_header is not None:
                sections.append((current_header, current_body))
            current_header = line.strip("≪≫《》")
            current_body   = []
        elif current_header is not None:
            current_body.append(line)
    if current_header is not None:
        sections.append((current_header, current_body))

    # ── レコード化 ─────────────────────────────────────────────
    records    = []
    trip_count = {}   # date -> その日の便番号カウンタ

    for trip_name, body in sections:
        # 釣行日
        rec_date = None
        for line in body:
            dm = _RE_TRIP_DATE.match(line.translate(_Z2H_NUM))
            if dm:
                day         = int(dm.group(1))
                month, year = anchor.month, anchor.year
                if day > anchor.day:          # 未来日 = 前月の釣果
                    month -= 1
                    if month == 0:
                        month, year = 12, year - 1
                try:
                    rec_date = datetime(year, month, day).strftime("%Y/%m/%d")
                except ValueError:
                    rec_date = None
                break
        if rec_date is None:
            continue

        # 魚種行・外道・タックル・コメントに仕分け
        fishes, by_catch, tackle, comments = [], [], "", []
        in_comment = False
        for line in body:
            norm = line.translate(_Z2H_NUM)
            if _RE_TRIP_DATE.match(norm):
                continue
            if not in_comment and re.match(r"[＜<]", line):
                tackle     = normalize_text(line)
                in_comment = True
                continue
            if in_comment:
                if not _RE_RESERVATION.search(line):
                    comments.append(line)
                continue
            parsed = _fish_line_to_record(norm)
            if parsed:
                fishes.append(parsed)
            elif line.startswith("他"):
                by_catch.append(line)

        if not fishes:
            continue

        trip_count[rec_date] = trip_count.get(rec_date, 0) + 1
        trip_no = trip_count[rec_date]

        # 便名を先頭に置く（crawler.py の time_slot 抽出が午前/午後/夜を拾えるように）
        kanso = normalize_text(f"≪{trip_name}≫ " + " ".join(comments + by_catch))

        for fish, size_raw, weight_raw, count_raw in fishes:
            records.append({
                "ship":            ship,
                "area":            area,
                "date":            rec_date,
                "trip_no":         trip_no,
                "is_cancellation": False,
                "reason_text":     "",
                "fish_raw":        fish,
                "count_raw":       count_raw,
                "size_raw":        size_raw,
                "weight_raw":      weight_raw,
                "tokki_raw":       tackle,
                "point_raw":       "",
                "kanso_raw":       kanso,
                "suion_raw":       None,
                "suishoku_raw":    None,
                "source":          "直サイト/gyo",
            })

    return records


# ============================================================
# テーブル分類
# ============================================================

def classify_table(table):
    """
    table (2次元リスト) の役割を返す。
    'A': 船種ヘッダー（セクション開始）
    'B': タックル・料金情報（スキップ）
    'C': 釣果テーブル  ← "日釣果" or "月日釣果" を含む1行2セルの表
    'D': コメントテーブル
    '?': 不明（スキップ）

    NOTE: "日釣果" は "乗合船" より先にチェックする。
    釣果テキスト "(乗合船と仕立船２隻の高低)" が誤って A に分類されるのを防ぐ。
    """
    if not table:
        return "?"
    txt = table_text(table)
    # C: 釣果テーブル — "日釣果" or "月日釣果" を含む（最優先）
    if "日釣果" in txt:
        return "C"
    # B: タックル情報
    if any(k in txt for k in ("出船時間", "納竿時間")):
        return "B"
    # D: コメントテーブル
    if "コメント" in txt:
        return "D"
    # A: 船種ヘッダー
    if any(k in txt for k in ("乗合船", "仕立船", "限定", "予約制")):
        return "A"
    return "?"

# ============================================================
# 日付パース
# ============================================================

_CUTOFF_DAYS = 60  # この日数より古いデータは取得しない


def parse_date_label(label_text, today_year, today_month):
    """
    日付ラベルから (year, month, day) を返す。
    パース不能・60日超過は None を返す。

    対応フォーマット:
      "４月６日釣果"        → (year, 4, 6)
      "6日釣果"            → (year, today_month, 6)
      "4月tadahiko1日釣果" → typo: 非数字を除去してパース
      "月日釣果"           → プレースホルダー → None
    """
    txt = normalize_text(label_text)
    # 全角数字を半角に変換
    txt = txt.translate(str.maketrans("０１２３４５６７８９", "0123456789"))

    # "月日釣果" = プレースホルダー（数字がない）
    if not re.search(r"\d", txt):
        return None

    # "X月Y日" を探す（typo 対応: 月・日の間に不要文字が入る場合も許容）
    m = re.search(r"(\d{1,2})\s*月.*?(\d{1,2})\s*日", txt)
    if m:
        month = int(m.group(1))
        day   = int(m.group(2))
        year  = today_year
        # 未来日付になる場合は前年を使う
        try:
            dt = datetime(year, month, day)
            if dt > datetime.now():
                year -= 1
        except ValueError:
            return None
        return year, month, day

    # "Y日" のみ（月なし）
    m = re.search(r"(\d{1,2})\s*日", txt)
    if m:
        day   = int(m.group(1))
        month = today_month
        year  = today_year
        try:
            dt = datetime(year, month, day)
            if dt > datetime.now():
                # 月をひとつ戻す
                month -= 1
                if month == 0:
                    month = 12
                    year  -= 1
        except ValueError:
            return None
        return year, month, day

    return None

# ============================================================
# メインパーサー
# ============================================================

def parse_gyo_sections(html, ship, area):
    """
    gyo.ne.jp ページから釣果レコードのリストを返す。
    各レコードは 15 フィールド辞書。
    """
    today      = datetime.now()
    today_year = today.year
    today_month= today.month

    parser = TableParser()
    parser.feed(html)
    tables = parser.tables

    records = []

    # セクション状態
    current_fish_raw = None
    current_count_raw = None
    current_date_str  = None
    current_kanso_raw = None

    def flush_record():
        """現在のセクションデータを records に追加する。"""
        if current_fish_raw and current_date_str and current_count_raw:
            records.append({
                "ship":            ship,
                "area":            area,
                "date":            current_date_str,
                "trip_no":         None,
                "is_cancellation": False,
                "reason_text":     "",
                "fish_raw":        current_fish_raw,
                "count_raw":       current_count_raw,
                "size_raw":        "",
                "weight_raw":      "",
                "tokki_raw":       "",
                "point_raw":       "",
                "kanso_raw":       current_kanso_raw or "",
                "suion_raw":       None,
                "suishoku_raw":    None,
            })

    for table in tables:
        kind = classify_table(table)

        if kind == "A":
            # 前セクションを flush してから新セクション開始
            flush_record()
            current_fish_raw  = None
            current_count_raw = None
            current_date_str  = None
            current_kanso_raw = None

            # fish_raw: 【...】 で囲まれた船種名を優先して取得
            # 例: "【ショートフィッシング天秤タチウオ乗合船】", "【午前・午後ライトアジ乗合船】"
            all_text = " ".join(cell for row in table for cell in row if cell.strip())
            m = re.search(r'【(.+?)】', all_text)
            if m:
                current_fish_raw = m.group(0)  # 【...】 込みで保持
            else:
                current_fish_raw = normalize_text(all_text)

        elif kind == "B":
            # タックル・料金情報 → kanso_raw に連結
            # 各行 [ラベル, 値] を "ラベル: 値" に整形して追記
            rows_text = " / ".join(
                ": ".join(cell for cell in row if cell.strip())
                for row in table
                if any(cell.strip() for cell in row)
            )
            b_text = normalize_text(rows_text)
            if b_text:
                current_kanso_raw = (current_kanso_raw + " " + b_text).strip() if current_kanso_raw else b_text

        elif kind == "C":
            # 構造: 1行2セル → row0 = [date_label, catch_text]
            # <th> = "４月６日釣果"（縦書き <br/> 区切り → Parser が連結）
            # <td> = "0.9～3.4kg　０～２匹(乗合船と仕立船２隻の高低)"
            if not table or not table[0]:
                continue
            row0 = table[0]
            date_text  = row0[0] if len(row0) > 0 else ""
            count_text = row0[1] if len(row0) > 1 else ""

            parsed = parse_date_label(date_text, today_year, today_month)
            if parsed is None:
                # "月日釣果" プレースホルダー → この釣り物の釣果なし、スキップ
                continue

            y, mo, d = parsed
            current_date_str  = f"{y}/{mo:02d}/{d:02d}"
            current_count_raw = normalize_text(count_text)

        elif kind == "D":
            # 構造: 1行2セル → row0 = ["コメント" or "X日コメント", comment_text]
            if table and table[0] and len(table[0]) > 1:
                d_text = normalize_text(table[0][1])
                current_kanso_raw = (current_kanso_raw + " " + d_text).strip() if current_kanso_raw else d_text

    # ループ終了後に最後のセクションを flush
    flush_record()

    return records

# ============================================================
# 自由記述形式パーサー（一之瀬丸スタイル）
# ============================================================

def html_to_lines(html_chunk):
    """
    HTML断片をテキスト行リストに変換する。
    <br> → 改行、その他タグ除去、全角スペース正規化。
    """
    text = re.sub(r'<br\s*/?>', '\n', html_chunk, flags=re.I)
    text = re.sub(r'<[^>]+>', '', text)
    text = re.sub(r'&[a-zA-Z]+;|&#\d+;', ' ', text)
    text = re.sub(r'[\u3000\xa0\ufffd]+', ' ', text)
    lines = [l.strip() for l in text.split('\n')]
    return [l for l in lines if l]


def parse_gyo_freetext(html, ship, area, date_str=None):
    """
    自由記述形式パーサー（一之瀬丸・米元スタイル共通）。

    date_str: history URL の hdt から渡す場合は YYYY/MM/DD 文字列。
              None の場合はページ内容からパース（一之瀬丸通常URL使用時）。

    セクション区切り:
      ≪船名≫ / 《船名》  → 一之瀬丸スタイル
      ★船名               → 米元スタイル（color:blue 大字）

    内部分割（米元スタイル: ≪釣果≫/≪コメント≫ ラベルあり）:
      ≪釣果≫   → count_raw 開始
      ≪コメント≫ → kanso_raw 開始（感想）

    内部分割（一之瀬丸スタイル: ＜集合...＞ で分割）:
      ＜集合...＞ より前 → count_raw
      ＜集合...＞ 以降  → kanso_raw
    """
    today       = datetime.now()
    today_year  = today.year
    today_month = today.month

    # 【釣果速報】以降を抽出（なければページ先頭から試みる）
    idx = html.find('釣果速報')
    if idx < 0:
        idx = 0

    lines = html_to_lines(html[idx:])

    # ── セクション分割 ─────────────────────────────────────────
    # 内部ラベル（セクション区切りにしない）
    _INTERNAL = re.compile(r'^[≪《][釣果コメント]{2,4}[≫》]$')
    # タックル情報（セクション区切りにしない）
    _TACKLE   = re.compile(r'集合|出船|納竿|料金|オモリ|道糸|ハリス')

    sections       = []
    current_header = None
    current_body   = []

    for line in lines:
        if _INTERNAL.fullmatch(line):
            # 内部ラベル → body に追加
            if current_header is not None:
                current_body.append(line)
            continue

        is_header = False
        # ≪...≫ / 《...》 形式（タックル行は除外）
        if re.fullmatch(r'[≪《].+[≫》]', line) and not _TACKLE.search(line):
            is_header = True
        # ★... 形式（米元スタイル）
        elif line.startswith('★'):
            is_header = True

        if is_header:
            if current_header is not None:
                sections.append((current_header, current_body))
            current_header = line
            current_body   = []
        elif current_header is not None:
            current_body.append(line)

    if current_header is not None:
        sections.append((current_header, current_body))

    # ── 各セクションをレコード化 ────────────────────────────────
    records = []

    # 非釣果セクションを除外するキーワード（お知らせ・アクセス等）
    _NON_FISHING = re.compile(
        r'お知らせ|アクセス|ライフジャケット|幹事様|ＢＢＱ|BBQ'
        r'|お湯があります|ワンポイント|定休日|駐車場|メニュー|募集'
    )

    for fish_raw, body_lines in sections:
        if not body_lines:
            continue

        # 非釣果セクション（お知らせ・アクセス等）はスキップ
        if _NON_FISHING.search(fish_raw):
            continue

        # "－－－" のみ → 釣果なし
        first = next((l for l in body_lines if l.strip()), "")
        if re.fullmatch(r'[－\-ー]+', first):
            continue

        # 日付の確定
        rec_date   = date_str     # None の場合は以下でパース
        body_start = 0

        if rec_date is None:
            for j, line in enumerate(body_lines):
                parsed = parse_date_label(line, today_year, today_month)
                if parsed:
                    rec_date   = f"{parsed[0]}/{parsed[1]:02d}/{parsed[2]:02d}"
                    body_start = j + 1
                    break
            if rec_date is None:
                continue

        # ── count_raw / kanso_raw の分割 ────────────────────────
        has_chouka_label = any(_INTERNAL.fullmatch(l) and '釣果' in l
                               for l in body_lines[body_start:])

        count_lines = []
        kanso_lines = []

        if has_chouka_label:
            # 米元スタイル: ≪釣果≫ → count、≪コメント≫ → kanso
            mode = "skip"
            for line in body_lines[body_start:]:
                if _INTERNAL.fullmatch(line) and '釣果' in line:
                    mode = "count"
                elif _INTERNAL.fullmatch(line) and 'コメント' in line:
                    mode = "kanso"
                elif mode == "count":
                    count_lines.append(line)
                elif mode == "kanso":
                    kanso_lines.append(line)
        else:
            # 一之瀬丸スタイル: ＜集合...＞ で count/kanso を分割
            in_kanso = False
            for line in body_lines[body_start:]:
                if not in_kanso and re.match(r'[＜<]', line):
                    in_kanso = True
                if in_kanso:
                    kanso_lines.append(line)
                else:
                    count_lines.append(line)

        count_raw = normalize_text(" ".join(count_lines))
        kanso_raw = normalize_text(" ".join(kanso_lines))

        if not count_raw:
            continue

        records.append({
            "ship":            ship,
            "area":            area,
            "date":            rec_date,
            "trip_no":         None,
            "is_cancellation": False,
            "reason_text":     "",
            "fish_raw":        fish_raw,
            "count_raw":       count_raw,
            "size_raw":        "",
            "weight_raw":      "",
            "tokki_raw":       "",
            "point_raw":       "",
            "kanso_raw":       kanso_raw,
            "suion_raw":       None,
            "suishoku_raw":    None,
        })

    return records


# ============================================================
# 勇幸丸専用パーサー（<div style="color:green;"> 形式）
# ============================================================

# ポイント抽出パターン（「〜沖」「〜瀬」「〜根」「〜ポイント」等）
# - 直前が語頭・空白・助詞区切り相当（は/で/に/を/が/と/も の後ろにあるものはスキップ）
# - 先頭は漢字・片仮名2〜6文字（地名らしさを担保）、末尾は地形語
_POINT_PATTERN = re.compile(
    r'([一-龥ァ-ン]{2,6}(?:沖|瀬|根|礁|洲|海峡|岬|ポイント))'
)


def parse_gyo_yukou(html, ship, area, date_str=None):
    """
    勇幸丸スタイルのパーサー。

    ページ構造:
      <div style="color:green;"> に最新釣果1件が格納されている。
      テキスト例: "４月１４日　本日14日の釣果は イサキ　21~36cm 0~20尾
                   コマセ釣り。前半は太東沖攻め..."

    パース方針:
      1. <div style="color:green;"> 内のテキストを取得
      2. 先頭の「X月Y日」（全角数字対応）で日付を確定
      3. date_str 指定時: HTMLの日付が date_str と一致しなければスキップ（stale data対策）
      4. 日付より後のテキストを「。」で区切り:
           - 最初の文（「〜」）→ fish_raw（釣果行）
           - 残り全体         → kanso_raw（コメント）
      5. 全テキストからポイント名（〜沖 / 〜瀬 等）を抽出 → point_raw

    戻り値: レコードリスト（0件または1件）
    """
    today      = datetime.now()
    today_year = today.year
    today_month = today.month

    # <div style="color:green;"> または <div style='color:green;'> を取得
    divs = re.findall(
        r'<div[^>]*color\s*:\s*green[^>]*>(.*?)</div>',
        html, re.S | re.I
    )
    if not divs:
        return []

    # 最初のdivを使用（通常1件のみ）
    raw_html = divs[0]

    # <span> 等内タグを除去してテキスト化
    text = re.sub(r'<[^>]+>', '', raw_html)
    text = re.sub(r'&[a-zA-Z]+;|&#\d+;', ' ', text)
    # 全角スペース・&nbsp; 正規化
    text = re.sub(r'[\u3000\xa0\ufffd]+', ' ', text)
    text = text.strip()

    if not text:
        return []

    # 全角数字を半角に変換
    text_half = text.translate(str.maketrans('０１２３４５６７８９', '0123456789'))

    # 先頭の「X月Y日」を抽出して日付確定
    m_date = re.match(r'\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日', text_half)
    if m_date is None:
        return []

    month = int(m_date.group(1))
    day   = int(m_date.group(2))
    year  = today_year
    try:
        dt_obj = datetime(year, month, day)
        if dt_obj > datetime.now():
            year -= 1
            datetime(year, month, day)  # バリデーション
    except ValueError:
        return []

    parsed_date = f"{year}/{month:02d}/{day:02d}"

    # date_str 指定時: HTMLの日付と一致しなければ stale data としてスキップ
    if date_str is not None and parsed_date != date_str:
        return []

    date_str = parsed_date

    # 日付部分より後のテキストを取得
    body = text_half[m_date.end():].strip()
    # 先頭の「本日X日の釣果は」のような説明句をスキップ（オプション）
    body = re.sub(r'^本日\d+日の釣果は\s*', '', body).strip()

    # fish_raw: 先頭から最初の「。」の手前まで（釣果行）
    # kanso_raw: 最初の「。」以降（コメント行）
    # 「。」がない場合は全体を fish_raw とする
    period_idx = body.find('。')
    if period_idx >= 0:
        # 「。」を含めて fish_raw に入れる
        fish_raw  = normalize_text(body[:period_idx + 1])
        kanso_raw = normalize_text(body[period_idx + 1:])
    else:
        fish_raw  = normalize_text(body)
        kanso_raw = ""

    if not fish_raw:
        return []

    # point_raw: 全テキストから「〜沖」「〜瀬」等を抽出して「/」区切りで結合
    # point_coords.json にある片貝沖・太東沖などをカバーする
    points_found = _POINT_PATTERN.findall(text)
    # 重複除去・順序保持
    seen = set()
    unique_points = []
    for p in points_found:
        if p not in seen and len(p) >= 2:
            seen.add(p)
            unique_points.append(p)
    point_raw = '/'.join(unique_points)

    return [{
        "ship":            ship,
        "area":            area,
        "date":            date_str,
        "trip_no":         None,
        "is_cancellation": False,
        "reason_text":     "",
        "fish_raw":        fish_raw,
        "count_raw":       "",
        "size_raw":        "",
        "weight_raw":      "",
        "tokki_raw":       "",
        "point_raw":       point_raw,
        "kanso_raw":       kanso_raw,
        "suion_raw":       None,
        "suishoku_raw":    None,
    }]


# ============================================================
# fetch
# ============================================================

FETCH_TIMEOUT = 45   # 秒。CI(GitHub Actions)からは応答が遅い/届かないことがある
# 失敗時のバックオフ（秒）。要素数+1 が試行回数。
# 2026-08-05: 3回×10/20秒（＝約2.5分の窓）では 8/4 の障害を吸収できなかったので
# 窓を約8分に広げた。gyo は「各便の最新釣果」しか出さない＝取りこぼした日は
# 二度と取れないため、job を数分延ばしてでも粘る方が得。
FETCH_BACKOFF = (30, 60, 120, 240)
FETCH_RETRIES = len(FETCH_BACKOFF) + 1


def fetch_gyo(url):
    """gyo.ne.jp 専用 fetch: cp932 優先でデコード（stdlib のみ）。

    2026-08-03: CI から `<urlopen error timed out>` で落ちていたためリトライを追加。
    ローカルからは 0.5秒/115KB で取得できるので、遅延ではなく GitHub Actions の
    IP レンジが弾かれている疑いがある。全リトライ失敗なら None を返し、
    呼び出し側（main）が非0終了する ＝ 黙って success を報告しない。

    2026-08-05: 実績は CI 3回中 成功1（8/3）・timeout 2（8/2 は当時リトライ無しで
    無言の空振り / 8/4 は3連続 timeout で赤）。ローカルからは常に 0.4秒で
    取得できるので恒久ブロックではなく断続的な不達と判断し、リトライ窓を拡大。
    """
    for attempt in range(1, FETCH_RETRIES + 1):
        try:
            req = Request(url, headers={"User-Agent": USER_AGENT})
            with urlopen(req, timeout=FETCH_TIMEOUT) as r:
                raw = r.read()
            for enc in ("cp932", "shift_jis", "euc-jp", "utf-8"):
                try:
                    return raw.decode(enc)
                except (UnicodeDecodeError, LookupError):
                    pass
            return raw.decode("utf-8", errors="replace")
        except (URLError, TimeoutError, OSError) as e:
            print(f"  ERROR fetch (attempt {attempt}/{FETCH_RETRIES}): {e}")
            if attempt < FETCH_RETRIES:
                wait = FETCH_BACKOFF[attempt - 1]
                print(f"    retry in {wait}s")
                time.sleep(wait)
    return None

# ============================================================
# 出力
# ============================================================

_CONTENT_DUP_DAYS = 120   # 同一内容を別日付で再登録しない期間


def _content_key(r):
    """内容シグネチャ（日付を含まない）。同じ釣果が別日で二重登録されるのを防ぐ。"""
    return (r.get("ship", ""), r.get("fish_raw", ""),
            r.get("count_raw", ""), r.get("size_raw", ""), r.get("weight_raw", ""))


def append_raw_direct_json(new_records):
    """catches_raw_direct.json に差分追記する。

    dedup は2段構え:
      1. キー (ship, date, trip_no, fish_raw) の完全一致 → スキップ（再実行の冪等性）
      2. 内容シグネチャが一致し、既存の日付が {_CONTENT_DUP_DAYS} 日以内 → スキップ
         （ページに残り続ける古い便を、毎日ちがう日付で登録してしまうのを防ぐ。
           2026-08-02 に 63% 水増しが見つかった原因への対策）

    trip_no はパーサーが便単位で採番済みのため、ここでは振り直さない
    （旧実装はレコード単位で連番を振り直しており、crawler.py 側の
      (ship, date, trip_no) による便グルーピングを壊していた）。
    """
    existing = []
    if os.path.exists(OUTPUT_PATH):
        with open(OUTPUT_PATH, encoding="utf-8") as f:
            try:
                existing = json.load(f)
            except json.JSONDecodeError:
                existing = []

    keys     = {(r["ship"], r["date"], r.get("trip_no"), r.get("fish_raw", ""))
                for r in existing}
    contents = {}
    for r in existing:
        contents.setdefault(_content_key(r), []).append(r["date"])

    added, skipped_dup = [], 0
    for rec in new_records:
        key = (rec["ship"], rec["date"], rec.get("trip_no"), rec.get("fish_raw", ""))
        if key in keys:
            continue

        ck = _content_key(rec)
        if any(
            abs((datetime.strptime(rec["date"], "%Y/%m/%d")
                 - datetime.strptime(d, "%Y/%m/%d")).days) <= _CONTENT_DUP_DAYS
            for d in contents.get(ck, [])
        ):
            skipped_dup += 1
            continue

        existing.append(rec)
        keys.add(key)
        contents.setdefault(ck, []).append(rec["date"])
        added.append(rec)

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(existing, f, ensure_ascii=False, indent=2)

    if skipped_dup:
        print(f"  内容重複スキップ: {skipped_dup} 件")
    return added

# ============================================================
# メイン
# ============================================================

def main():
    today_str = datetime.now().strftime("%Y/%m/%d")

    print(f"=== gyo_crawler.py 開始: {today_str} ===")
    print(f"対象: {len(GYO_SHIPS)} 船宿  出力: {OUTPUT_PATH}\n")

    all_new  = []
    failures = []

    for s in GYO_SHIPS:
        print(f"  [{s['area']}] {s['ship']} ({s['parser']})")

        # 最新ページ1本のみ取得する。history URL は「指定日以降の最新レポート」を
        # 返す仕様で、遡っても同じ内容が返ってくるため使わない（2026-08-02 に水増しの
        # 原因と判明）。各便の釣行日はページ本文の「N日の釣果」から確定する。
        url  = GYO_BASE_URL.format(cid=s["cid"])
        html = fetch_gyo(url)
        if not html:
            print("    SKIP (fetch error)")
            failures.append(s["ship"])
            continue

        records = parse_ichinose(html, s["ship"], s["area"])
        print(f"    パース: {len(records)} 件")
        if records:
            _dates = sorted({r["date"] for r in records})
            print(f"    日付: {_dates[0]} 〜 {_dates[-1]} ({len(_dates)}日分)")
            for r in records[:3]:
                print(f"      {r['date']} 便{r['trip_no']} {r['fish_raw']} "
                      f"{r['size_raw'] or r['weight_raw']} {r['count_raw']}")
        all_new.extend(records)
        time.sleep(1.0)

    added = append_raw_direct_json(all_new)
    total = _existing_count()
    print(f"\n追記: {len(added)} 件新規  JSON合計: {total} 件")

    # 取得できなかった船宿があれば非0終了する。
    # 旧実装は fetch 失敗を握りつぶして exit 0 していたため、CI が success を
    # 報告し続けた（2026-08-02 の初回 CI 実行が実際には timeout で空振り）。
    if failures:
        print(f"\n❌ 取得失敗: {', '.join(failures)}")
        sys.exit(1)

    print("完了")


def _existing_count():
    if os.path.exists(OUTPUT_PATH):
        try:
            with open(OUTPUT_PATH, encoding="utf-8") as f:
                return len(json.load(f))
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    main()
