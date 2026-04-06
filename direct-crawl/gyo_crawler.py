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
    # parser="table"  : 忠彦丸スタイル（<th>=日付縦書き / <td>=釣果の1行2セルテーブル）
    # parser="freetext": 一之瀬丸スタイル（≪船名≫→X日の釣果→釣果テキスト の自由記述）
    {"cid": "tadahiko",  "ship": "忠彦丸",    "area": "金沢八景", "parser": "table"},
    {"cid": "ichinose",  "ship": "一之瀬丸",  "area": "金沢八景", "parser": "freetext"},
    {"cid": "yonemoto",  "ship": "米元釣船店", "area": "横浜",     "parser": "freetext"},
]

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
# fetch
# ============================================================

def fetch_gyo(url):
    """gyo.ne.jp 専用 fetch: cp932 優先でデコード（stdlib のみ）。"""
    try:
        req = Request(url, headers={"User-Agent": USER_AGENT})
        with urlopen(req, timeout=20) as r:
            raw = r.read()
        for enc in ("cp932", "shift_jis", "euc-jp", "utf-8"):
            try:
                return raw.decode(enc)
            except (UnicodeDecodeError, LookupError):
                pass
        return raw.decode("utf-8", errors="replace")
    except (URLError, TimeoutError, OSError) as e:
        print(f"  ERROR fetch: {e}")
        return None

# ============================================================
# 出力
# ============================================================

def append_raw_direct_json(new_records):
    """catches_raw_direct.json に差分追記する。dedup キー = (ship, date, fish_raw)。"""
    existing = []
    if os.path.exists(OUTPUT_PATH):
        with open(OUTPUT_PATH, encoding="utf-8") as f:
            try:
                existing = json.load(f)
            except json.JSONDecodeError:
                existing = []

    keys = {
        (r["ship"], r["date"], r.get("fish_raw", ""))
        for r in existing
    }

    added = []
    for rec in new_records:
        key = (rec["ship"], rec["date"], rec.get("fish_raw", ""))
        if key not in keys:
            existing.append(rec)
            keys.add(key)
            added.append(rec)

    # trip_no を (ship, date) 内で再採番（保存のたびに全件振り直し）
    _counter = {}
    for r in existing:
        k = (r["ship"], r["date"])
        _counter[k] = _counter.get(k, 0) + 1
        r["trip_no"] = _counter[k]

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(existing, f, ensure_ascii=False, indent=2)

    return added

# ============================================================
# メイン
# ============================================================

def main():
    from datetime import timedelta

    today     = datetime.now()
    today_str = today.strftime("%Y/%m/%d")
    dt_param  = today.strftime("%Y/%m/%d")  # URL の dt= パラメータ（今日）

    print(f"=== gyo_crawler.py 開始: {today_str} ===")
    print(f"対象: {len(GYO_SHIPS)} 船宿  出力: {OUTPUT_PATH}\n")

    all_new = []

    for s in GYO_SHIPS:
        parser_type = s.get("parser", "table")
        print(f"  [{s['area']}] {s['ship']} ({parser_type})")

        if parser_type == "freetext":
            # history URL で過去7日分をループ取得
            # 日付は URL から確定するためコンテンツ内の日付パース不要
            ship_records = []
            for days_ago in range(7):
                hdt    = today - timedelta(days=days_ago)
                hdt_str = hdt.strftime("%Y/%m/%d")
                url    = GYO_HISTORY_URL.format(cid=s["cid"], hdt=hdt_str, dt=dt_param)
                html   = fetch_gyo(url)
                if not html:
                    print(f"    {hdt_str}: fetch error")
                    continue
                recs = parse_gyo_freetext(html, s["ship"], s["area"], date_str=hdt_str)
                print(f"    {hdt_str}: {len(recs)} 件")
                ship_records.extend(recs)
                time.sleep(1.0)
            all_new.extend(ship_records)

        else:
            # 忠彦丸スタイル: 最新ページ1本を取得
            url  = GYO_BASE_URL.format(cid=s["cid"])
            html = fetch_gyo(url)
            if not html:
                print("    SKIP (fetch error)")
                continue
            records = parse_gyo_sections(html, s["ship"], s["area"])
            print(f"    最新: {len(records)} 件")
            if records:
                print(f"    先頭3: {[r['fish_raw'] + ' / ' + r['date'] for r in records[:3]]}")
            all_new.extend(records)
            time.sleep(1.0)

    added = append_raw_direct_json(all_new)
    total = _existing_count()
    print(f"\n追記: {len(added)} 件新規  JSON合計: {total} 件")
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
