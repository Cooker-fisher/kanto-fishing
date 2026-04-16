#!/usr/bin/env python3
"""
関東船釣り情報クローラー v5.17
変更点(v5.17):
- SST傾向軸追加: 7日間予報のSST前半→後半変化から「上昇/安定/低下」を判定、分析テキストに反映
- _build_analysis_text: sst_trendパラメータ追加
- build_forecast_json: エリア別area_sst_trendsを事前計算、detailed_predictionsにsst_trendを追加
変更点(v5.16):
- 潮差・月齢を天文計算で算出し釣果予測に連携（_calc_moon_age, _calc_tide_range）
- wave_periodの予報値をpredict_catchesに直接連携（波高からの間接推定をフォールバックに格下げ）
- forecast.jsonに潮差・月齢・潮汐タイプを追加
変更点(v5.15):
- コンボ別詳細分析（セクション12）: calc_combo_scores()で魚種×エリアグループの複合スコアを計算
- index.htmlに「注目の魚種×エリア」セクション追加（上位6コンボをカード表示）
- fish_area/ページにサマリーカード・シーズンバー・トレンドコメント追加
- 海況カード: load_weather_data()で最新weather_data/*.csvを読み込み、build_weather_section()でindex.htmlに海況4エリア表示
- GA4カスタムイベント: 魚種カードクリック・狙い目クリック・エリアフィルター・魚種検索にgtag()イベント送信
- 爆釣アラート: is_surge()追加（先週比1.5倍以上+出船5隻以上→🔥バッジ）
- 旬の突入検出: calc_season_entry()追加（今年vs昨年の初釣果週を魚種ページに表示）
- 週末予測確率: calc_weekend_prob()追加（過去2年同週実績→%表示）
  - 狙い目セクションにプログレスバー表示
  - 魚種カードにも小型プログレスバー追加
変更点(v5.12):
- 魚種別ページデザイン改善: ページ上部にサマリーカード（今週出船数・平均釣果・最高釣果）追加
- 魚種別ページ: ランキングTOP3にメダル絵文字（🥇🥈🥉）
- 魚種別ページ: テーブル縞模様・ホバー強調・バーにグラデーション追加
変更点(v5.11):
- staleデータフィルタ: 直近30日以内に釣果がない魚種をcalc_targetsのTOP5から除外
- build_html: stale魚種カードを薄表示（opacity 0.55）＋最終釣果日の警告注記
変更点(v5.10):
- build_fish_area_pages: history引数追加・昨年同週比較テーブル（yoy-table）追加
変更点(v5.9):
- update_history: weight_avgを週次・月次集計に追加
- build_fish_pages: 昨年比テーブルの「平均サイズ/重さ」でsize_avg=0時はweight_avgを表示
- build_sitemap(): sitemap.xml自動生成（index/fish/area/fish_area 全URL）
変更点(v5.8):
- 推薦コメント整合性: build_reason_tagsに先週比タグ追加（📈先週比UP/📉先週比DOWN）
- build_comment: WoW矛盾注記（top/highでwow≦-30%→「直近は急減傾向・注意」）
- 魚種×港ページ新設: build_fish_area_pages()（≥5件の組み合わせのみ fish_area/ に生成）
- build_fish_pages: 「エリア別の釣果」セクション追加（fish_area/へのリンク）
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
import re, json, time, os, csv, math
from datetime import datetime, timedelta
from urllib.request import urlopen, Request
from urllib.error import URLError
from urllib.parse import quote
from html.parser import HTMLParser

# ── data/ バージョン管理 ───────────────────────────────────────────────────
# config.json の active_version に連動して data/{ver}/ を DATA_DIR として使う。
# バージョンアップ時（CSV列追加等）は config.json の active_version を上げるだけ。
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
try:
    with open(os.path.join(_BASE_DIR, "config.json"), encoding="utf-8") as _f:
        _ACTIVE_VER = json.load(_f)["active_version"]
except Exception:
    _ACTIVE_VER = "V2"
_DATA_DIR = os.path.join(_BASE_DIR, "data", _ACTIVE_VER)

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
WEB_DIR  = "docs"  # Web出力フォルダ（GitHub Pages /docs から配信）

# Google AdSense
ADSENSE_TAG = '<script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=ca-pub-7406401300491553" crossorigin="anonymous"></script>'
# Google Analytics
GA_TAG = '<script async src="https://www.googletagmanager.com/gtag/js?id=G-LS469BTBBX"></script><script>window.dataLayer=window.dataLayer||[];function gtag(){dataLayer.push(arguments);}gtag("js",new Date());gtag("config","G-LS469BTBBX");</script>'

DATA_NOTE_HTML = """<div class="data-note">
  <details>
    <summary>データについて</summary>
    <ul>
      <li>釣果データは関東各地の船宿情報から毎日自動収集しています</li>
      <li>船宿ごとの表記ゆれや未記載項目があり、数値は参考値です</li>
      <li>魚種・数量・サイズは独自ルールで正規化しています</li>
      <li>「最終更新」は本サイトのデータ取得日時（日本時間16:30頃）を示します</li>
    </ul>
  </details>
</div>"""

# ============================================================
# 週末海況予報（Open-Meteo Marine API で土日の予報を取得）
# ============================================================
# エリアグループごとの代表座標（Open-Meteo Marine APIで予報取得）
AREA_FORECAST_COORDS = {
    "茨城":           {"lat": 36.3, "lon": 140.7},
    "千葉・外房":     {"lat": 35.3, "lon": 140.6},
    "千葉・内房":     {"lat": 35.1, "lon": 139.8},
    "千葉・東京湾奥": {"lat": 35.6, "lon": 139.9},
    "東京":           {"lat": 35.5, "lon": 139.8},
    "神奈川・東京湾": {"lat": 35.3, "lon": 139.7},
    "神奈川・相模湾": {"lat": 35.1, "lon": 139.4},
    "静岡":           {"lat": 35.0, "lon": 139.1},
}

# weather_data/ の4エリアサマリー（潮汐・月齢）
_TIDE_AREA_MAP = {
    "tokyo_bay":  "東京湾",
    "sagami_bay": "相模湾",
    "outer_boso": "外房",
    "ibaraki":    "茨城沖",
}

_TIDE_GROUP_MAP = {
    "千葉・東京湾奥": "tokyo_bay", "東京": "tokyo_bay", "神奈川・東京湾": "tokyo_bay",
    "神奈川・相模湾": "sagami_bay", "静岡": "sagami_bay",
    "千葉・外房": "outer_boso", "千葉・内房": "outer_boso",
    "茨城": "ibaraki",
}

def _wind_dir_text(deg):
    if deg is None or deg == "": return ""
    try: deg = float(deg)
    except: return ""
    dirs = ["北","北北東","北東","東北東","東","東南東","南東","南南東",
            "南","南南西","南西","西南西","西","西北西","北西","北北西"]
    return dirs[int((deg + 11.25) / 22.5) % 16]

def _wave_icon(h):
    if h is None: return ""
    if h < 0.5: return "🟢"
    if h < 1.0: return "🟡"
    if h < 1.5: return "🟠"
    return "🔴"

def _wave_label(h):
    if h is None: return ""
    if h < 0.5: return "穏やか"
    if h < 1.0: return "やや波"
    if h < 1.5: return "波あり"
    return "高波注意"

def _wind_label(ws):
    if ws is None: return ""
    if ws < 3: return "微風"
    if ws < 6: return "弱風"
    if ws < 10: return "やや強い"
    return "強風注意"

def _float_or_none(v):
    if v is None or v == "": return None
    try: return float(v)
    except: return None

def _next_weekend():
    """次の土日の日付を返す。土日当日なら今週末を返す。"""
    now = datetime.now()
    wd = now.weekday()  # 0=月 ... 5=土 6=日
    if wd == 5:       # 土曜日
        sat = now
    elif wd == 6:     # 日曜日
        sat = now - timedelta(days=1)
    else:
        sat = now + timedelta(days=(5 - wd))
    sun = sat + timedelta(days=1)
    return sat, sun

# ── 月齢・潮差の天文計算（標準ライブラリのみ） ──────────────────────

def _calc_moon_age(date_str):
    """日付文字列(YYYY-MM-DD) → 月齢(0〜29.5)を天文計算で返す。
    Conway法: 2000年1月6日の新月を基準に、朔望月(29.53059日)で割った余り。
    """
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        return None
    # 基準新月: 2000-01-06 18:14 UTC
    ref = datetime(2000, 1, 6, 18, 14)
    diff = (dt - ref).total_seconds() / 86400.0
    age = diff % 29.53059
    return round(age, 1)

def _moon_title(age):
    """月齢 → 潮汐タイプ名"""
    if age is None:
        return ""
    # 新月(0), 上弦(7.4), 満月(14.8), 下弦(22.1) 付近が大潮
    for center in [0, 14.8, 29.53]:
        if abs(age - center) <= 1.5:
            return "大潮"
    for center in [7.4, 22.1]:
        if abs(age - center) <= 1.0:
            return "小潮"
    for center in [7.4, 22.1]:
        if abs(age - center) <= 2.5:
            return "中潮"
    # 大潮の前後
    for center in [0, 14.8, 29.53]:
        if abs(age - center) <= 3.5:
            return "中潮"
    # 長潮・若潮（小潮の前後）
    for center in [9.5, 24.0]:
        if abs(age - center) <= 1.0:
            return "長潮"
    for center in [10.5, 25.0]:
        if abs(age - center) <= 1.0:
            return "若潮"
    return "中潮"

def _weather_code_text(code):
    """WMO Weather interpretation code → 日本語テキスト"""
    if code is None: return ""
    code = int(code)
    if code == 0: return "快晴"
    if code <= 2: return "晴れ"
    if code == 3: return "曇り"
    if code in (45, 48): return "霧"
    if code <= 55: return "霧雨"
    if code <= 65: return "雨"
    if code <= 67: return "雨氷"
    if code <= 75: return "雪"
    if code <= 77: return "霧雪"
    if code <= 82: return "にわか雨"
    if code <= 86: return "にわか雪"
    if code == 95: return "雷雨"
    if code <= 99: return "雷雨(雹)"
    return ""

def _pressure_label(hpa):
    """気圧 → 定性ラベル"""
    if hpa is None: return ""
    if hpa >= 1020: return "高気圧"
    if hpa >= 1013: return "安定"
    if hpa >= 1005: return "やや低め"
    return "低気圧接近"

def _calc_tide_range(date_str):
    """日付文字列(YYYY-MM-DD) → 潮差(cm)の概算を天文計算で返す。
    大潮(新月・満月)で最大、小潮(上弦・下弦)で最小。
    横須賀の実測データから: 大潮≒120cm, 小潮≒50cm を基準に正弦近似。
    """
    age = _calc_moon_age(date_str)
    if age is None:
        return None
    # 月齢 → 朔望サイクルの位相(0〜2π)
    phase = (age / 29.53059) * 2 * math.pi
    # 新月(0)・満月(π)で大潮(最大)、上弦(π/2)・下弦(3π/2)で小潮(最小)
    # cos(2*phase): 0,πで+1、π/2,3π/2で-1
    amplitude = math.cos(2 * phase)
    # 潮差: 中央85cm ± 35cm
    tide_range = 85 + 35 * amplitude
    return round(tide_range, 1)

def _fetch_marine_forecast(lat, lon, date_from, date_to):
    """Open-Meteo Marine APIから予報を取得。釣りの時間帯(6-15時)の平均を返す。"""
    url = (
        f"https://marine-api.open-meteo.com/v1/marine"
        f"?latitude={lat}&longitude={lon}"
        f"&hourly=wave_height,wave_period,swell_wave_height,sea_surface_temperature"
        f"&start_date={date_from}&end_date={date_to}"
        f"&timezone=Asia/Tokyo"
    )
    try:
        req = Request(url, headers={"User-Agent": USER_AGENT})
        with urlopen(req, timeout=15) as r:
            data = json.loads(r.read())
    except Exception as e:
        print(f"  Marine forecast error [{lat},{lon}]: {e}")
        return None
    hourly = data.get("hourly", {})
    times = hourly.get("time", [])
    if not times:
        return None
    # 釣りの時間帯(6-15時)だけ抽出して日別に集約
    day_data = {}
    for i, t in enumerate(times):
        dt_part, hr_part = t.split("T")
        hour = int(hr_part.split(":")[0])
        if hour < 6 or hour > 15:
            continue
        day_data.setdefault(dt_part, []).append({
            "wave_height": hourly.get("wave_height", [None]*(i+1))[i],
            "wave_period": hourly.get("wave_period", [None]*(i+1))[i],
            "swell":       hourly.get("swell_wave_height", [None]*(i+1))[i],
            "sst":         hourly.get("sea_surface_temperature", [None]*(i+1))[i],
        })
    result = {}
    for day, rows in day_data.items():
        def _avg(key):
            vals = [r[key] for r in rows if r.get(key) is not None]
            return round(sum(vals)/len(vals), 1) if vals else None
        result[day] = {"wave_height": _avg("wave_height"), "wave_period": _avg("wave_period"),
                       "swell": _avg("swell"), "sst": _avg("sst")}
    return result

def _fetch_wind_forecast(lat, lon, date_from, date_to):
    """Open-Meteo Forecast APIから風速・天気・気圧予報を取得。"""
    url = (
        f"https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat}&longitude={lon}"
        f"&hourly=wind_speed_10m,wind_direction_10m,weather_code,surface_pressure"
        f"&start_date={date_from}&end_date={date_to}"
        f"&timezone=Asia/Tokyo&wind_speed_unit=ms"
    )
    try:
        req = Request(url, headers={"User-Agent": USER_AGENT})
        with urlopen(req, timeout=15) as r:
            data = json.loads(r.read())
    except Exception as e:
        print(f"  Wind forecast error [{lat},{lon}]: {e}")
        return None
    hourly = data.get("hourly", {})
    times = hourly.get("time", [])
    day_data = {}
    for i, t in enumerate(times):
        dt_part, hr_part = t.split("T")
        hour = int(hr_part.split(":")[0])
        if hour < 6 or hour > 15:
            continue
        ws = hourly.get("wind_speed_10m", [None]*(i+1))[i]
        wd = hourly.get("wind_direction_10m", [None]*(i+1))[i]
        wc = hourly.get("weather_code", [None]*(i+1))[i]
        sp = hourly.get("surface_pressure", [None]*(i+1))[i]
        day_data.setdefault(dt_part, []).append({"ws": ws, "wd": wd, "wc": wc, "sp": sp})
    result = {}
    for day, rows in day_data.items():
        ws_vals = [r["ws"] for r in rows if r["ws"] is not None]
        wd_vals = [r["wd"] for r in rows if r["wd"] is not None]
        wc_vals = [r["wc"] for r in rows if r["wc"] is not None]
        sp_vals = [r["sp"] for r in rows if r["sp"] is not None]
        # 天気コードは最頻値を採用
        wc_mode = max(set(wc_vals), key=wc_vals.count) if wc_vals else None
        result[day] = {
            "wind_speed": round(sum(ws_vals)/len(ws_vals), 1) if ws_vals else None,
            "wind_dir":   round(sum(wd_vals)/len(wd_vals))     if wd_vals else None,
            "weather_code": wc_mode,
            "pressure":   round(sum(sp_vals)/len(sp_vals), 1) if sp_vals else None,
        }
    return result

def load_weather_data():
    """7日間の日次海況予報を全エリアから取得 + 潮汐データを読み込む"""
    result = {"forecast": {}, "tide": {}}
    today = datetime.now()
    date_from = today.strftime("%Y-%m-%d")
    date_to   = (today + timedelta(days=6)).strftime("%Y-%m-%d")

    # 後方互換: 週末日付も保持（build_weather_section等で使用）
    sat, sun = _next_weekend()
    result["sat_date"] = sat.strftime("%Y-%m-%d")
    result["sun_date"] = sun.strftime("%Y-%m-%d")

    print(f"海況予報取得: {date_from} ～ {date_to}（7日間）")
    for group, coord in AREA_FORECAST_COORDS.items():
        print(f"  [{group}] ...", end=" ", flush=True)
        marine = _fetch_marine_forecast(coord["lat"], coord["lon"], date_from, date_to)
        wind   = _fetch_wind_forecast(coord["lat"], coord["lon"], date_from, date_to)
        time.sleep(0.3)
        if marine:
            for day in sorted(marine.keys()):
                m = marine.get(day, {})
                w = (wind or {}).get(day, {})
                key = (group, day)
                result["forecast"][key] = {
                    "wave_height":  m.get("wave_height"),
                    "wave_period":  m.get("wave_period"),
                    "swell":        m.get("swell"),
                    "sst":          m.get("sst"),
                    "wind_speed":   w.get("wind_speed"),
                    "wind_dir":     w.get("wind_dir"),
                    "weather_code": w.get("weather_code"),
                    "weather_text": _weather_code_text(w.get("weather_code")),
                    "pressure":     w.get("pressure"),
                    "tide_range":   _calc_tide_range(day),
                    "moon_age":     _calc_moon_age(day),
                    "moon_title":   _moon_title(_calc_moon_age(day)),
                }
            print("OK")
        else:
            print("SKIP")

    # weather_data/{area}.csv から潮汐情報
    base = os.path.dirname(__file__)
    for area_code in _TIDE_AREA_MAP:
        path = os.path.join(base, "weather_data", f"{area_code}.csv")
        if not os.path.exists(path):
            continue
        last_row = None
        try:
            with open(path, encoding="utf-8", newline="") as f:
                for row in csv.DictReader(f):
                    last_row = row
        except Exception:
            continue
        if last_row:
            result["tide"][area_code] = last_row

    return result

def _fishing_ok_score(wave, wind):
    """出船可否スコア: 100=最適 0=欠航リスク"""
    score = 100
    if wave is not None:
        if wave >= 2.5: score -= 60
        elif wave >= 1.5: score -= 30
        elif wave >= 1.0: score -= 10
    if wind is not None:
        if wind >= 12: score -= 50
        elif wind >= 8: score -= 25
        elif wind >= 6: score -= 10
    return max(0, score)

def _ok_label(score):
    if score >= 80: return "◎ 出船日和", "#4dcc88"
    if score >= 60: return "○ 概ね良好", "#f4a261"
    if score >= 40: return "△ やや不安", "#e85d04"
    return "✕ 欠航リスク", "#cc4d4d"

def build_weather_section(weather_data):
    """週末海況予報カードをエリアグループ別・土日別に生成"""
    forecasts = weather_data.get("forecast", {})
    if not forecasts:
        return ""
    sat_date = weather_data.get("sat_date", "")
    sun_date = weather_data.get("sun_date", "")
    sat_m = int(sat_date[5:7]) if sat_date else 0
    sat_d = int(sat_date[8:10]) if sat_date else 0
    sun_m = int(sun_date[5:7]) if sun_date else 0
    sun_d = int(sun_date[8:10]) if sun_date else 0

    cards = ""
    for group in AREA_FORECAST_COORDS:
        sat_fc = forecasts.get((group, sat_date), {})
        sun_fc = forecasts.get((group, sun_date), {})
        if not sat_fc and not sun_fc:
            continue

        rows_html = ""
        for label, fc, date_str in [("土", sat_fc, sat_date), ("日", sun_fc, sun_date)]:
            if not fc:
                continue
            wave = _float_or_none(fc.get("wave_height"))
            wind = _float_or_none(fc.get("wind_speed"))
            sst  = _float_or_none(fc.get("sst"))
            wd   = fc.get("wind_dir")

            icon   = _wave_icon(wave)
            wlabel = _wave_label(wave)
            wdir   = _wind_dir_text(wd)
            score  = _fishing_ok_score(wave, wind)
            ok_txt, ok_color = _ok_label(score)
            ok_cls = "good" if score >= 80 else ("warn" if score >= 50 else "bad")

            wave_txt = f"{icon} {wave}m {wlabel}" if wave is not None else "-"
            wind_txt = f"{wdir}{wind}m/s" if wind is not None else "-"
            sst_txt  = f"{sst}℃" if sst is not None else "-"

            rows_html += f"""<div class="wl-row">
  <div class="wl-day">{label}</div>
  <div class="wl-wave">{wave_txt}</div>
  <div class="wl-wind">💨 {wind_txt}</div>
  <div class="wl-temp">🌡️ {sst_txt}</div>
  <div class="wl-judge {ok_cls}">{ok_txt}</div>
</div>"""

        # 潮汐
        tide_txt = ""
        tide_key = _TIDE_GROUP_MAP.get(group)
        if tide_key:
            trow = weather_data.get("tide", {}).get(tide_key)
            if trow:
                tt = trow.get("tide_type", "")
                ma = trow.get("moon_age", "")
                if tt:
                    tide_txt = f'🌙 {tt}'
                    if ma: tide_txt += f'(月齢{ma})'

        cards += f"""<div class="weather-card">
  <div class="wc-head">
    <span class="wc-area">{group}</span>
    {f'<span class="wc-tide">{tide_txt}</span>' if tide_txt else ''}
  </div>
  {rows_html}
</div>"""

    if not cards:
        return ""
    return f"""<h2 class="st">🌊 今週末の海況予報 <span class="st-sub">{sat_m}/{sat_d}(土)・{sun_m}/{sun_d}(日) 6〜15時</span></h2>
<p class="note-text">波高・風速から出船可否を判定。データ: Open-Meteo Marine Forecast</p>
<div class="wx-grid">{cards}</div>"""

# ============================================================
# 釣果予測エンジン（海況予報 × 過去実績）
# ============================================================
def _load_historical_catches():
    """data/V2/*.csv から全釣果を読み込み（V2正規化済み、約82,000行）
    修正 2026/04/16: data/*.csv (V1スタブ・数行のみ) ではなく
    data/V2/*.csv (active_version=V2、正規化済み全件) を参照するよう変更。
    V2はカラム名が tsuri_mono（旧: fish）。_build_catch_weather_index 側で吸収済み。
    """
    base = os.path.dirname(__file__) or "."
    try:
        with open(os.path.join(base, "config.json"), encoding="utf-8") as f:
            cfg = json.load(f)
        ver = cfg.get("active_version", "V2")
    except Exception:
        ver = "V2"
    data_dir = os.path.join(base, "data", ver)
    if not os.path.isdir(data_dir):
        print(f"WARNING: data/{ver}/ が見つかりません。data/ にフォールバック")
        data_dir = os.path.join(base, "data")
    rows = []
    for fname in sorted(os.listdir(data_dir)):
        if not fname.endswith(".csv"): continue
        try:
            with open(os.path.join(data_dir, fname), encoding="utf-8", newline="") as f:
                for row in csv.DictReader(f):
                    rows.append(row)
        except Exception:
            continue
    return rows

def _load_historical_weather():
    """weather/*.csv から日付×地点の6-15時平均海況を返す（波周期含む）"""
    base = os.path.dirname(__file__)
    wx_dir = os.path.join(base, "weather")
    if not os.path.isdir(wx_dir):
        return {}
    raw = {}
    for fname in sorted(os.listdir(wx_dir)):
        if not fname.endswith(".csv") or fname.startswith("."): continue
        try:
            with open(os.path.join(wx_dir, fname), encoding="utf-8", newline="") as f:
                for row in csv.DictReader(f):
                    pt, dt, hr = row.get("point",""), row.get("date",""), int(row.get("hour","0"))
                    if hr < 6 or hr > 15: continue
                    key = (dt, pt)
                    if key not in raw:
                        raw[key] = {"w":[], "ws":[], "s":[], "wp":[]}
                    try: raw[key]["w"].append(float(row["wave_height"]))
                    except: pass
                    try: raw[key]["ws"].append(float(row["wind_speed"]))
                    except: pass
                    try: raw[key]["s"].append(float(row["sst"]))
                    except: pass
                    try: raw[key]["wp"].append(float(row["wave_period"]))
                    except: pass
        except Exception:
            continue
    result = {}
    for k, v in raw.items():
        def _a(lst): return round(sum(lst)/len(lst), 2) if lst else None
        result[k] = {"wave": _a(v["w"]), "wind": _a(v["ws"]),
                      "sst": _a(v["s"]), "wave_period": _a(v["wp"])}
    return result

def _load_tide_data():
    """tide/*.csv → {date: 潮差(max-min cm, 6-15時)}"""
    base = os.path.join(os.path.dirname(__file__), "tide")
    if not os.path.isdir(base):
        return {}
    raw = {}  # date -> [cm values]
    for fname in sorted(os.listdir(base)):
        if not fname.endswith(".csv"): continue
        try:
            with open(os.path.join(base, fname), encoding="utf-8", newline="") as f:
                for row in csv.DictReader(f):
                    hr = int(row.get("hour", "0"))
                    if hr < 6 or hr > 15: continue
                    dt = row.get("date", "")
                    try: cm = float(row["tide_cm"])
                    except: continue
                    raw.setdefault(dt, []).append(cm)
        except Exception:
            continue
    return {dt: round(max(vals) - min(vals), 1) for dt, vals in raw.items() if len(vals) >= 2}

def _load_moon_data():
    """moon.csv → {date: {"age": float, "title": str}}"""
    path = os.path.join(os.path.dirname(__file__), "moon.csv")
    if not os.path.exists(path):
        return {}
    result = {}
    try:
        with open(path, encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                dt = row.get("date", "")
                result[dt] = {
                    "age": float(row["moon_age"]) if row.get("moon_age") else None,
                    "title": row.get("moon_title", ""),
                }
    except Exception:
        pass
    return result

def _area_to_group(area):
    """船宿エリア名 → AREA_GROUPSのグループ名"""
    for group, areas in AREA_GROUPS.items():
        if area in areas:
            return group
    return None

def _load_ship_fish_point():
    """ship_fish_point.json を読み込み"""
    path = os.path.join(os.path.dirname(__file__), "ship_fish_point.json")
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def _resolve_point(point_place, ship, fish, sfp):
    """point_placeを解決。空の場合はship_fish_point.jsonでフォールバック"""
    pp = (point_place or "").strip()
    if pp:
        return pp
    ship_data = sfp.get(ship)
    if not ship_data:
        return ""
    fish_map = ship_data.get(fish) or ship_data.get("_default")
    if fish_map and isinstance(fish_map, dict):
        return fish_map.get("point1", "") or ""
    return ""

def _load_area_weather_map():
    """area_weather_map.json を読み込み"""
    path = os.path.join(os.path.dirname(__file__), "area_weather_map.json")
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return {k: v for k, v in data.items() if not k.startswith("_")}
    except Exception:
        return {}

# join_catch_weather.py と同じ不明ポイント判定
_UNRESOLVABLE_RE = re.compile(r'^(航程|近場|浅場|深場|東京湾一帯|湾内|南沖|東沖|西沖|北沖|赤灯沖|観音沖).*')

def _is_unresolvable(pp):
    return not pp or bool(_UNRESOLVABLE_RE.match(pp))

# kanso_raw からポイント名を抽出するための regex（遅延初期化）
_KANSO_POINT_RE = None

def _build_kanso_point_re():
    """point_coords.json の座標あきポイント名を OR 結合した regex を返す（長い名前優先）"""
    global _KANSO_POINT_RE
    if _KANSO_POINT_RE is not None:
        return _KANSO_POINT_RE
    pc_path = os.path.join(os.path.dirname(__file__), "normalize", "point_coords.json")
    try:
        with open(pc_path, encoding="utf-8") as f:
            pc = json.load(f)
        # lat が None でなく 3文字以上 のポイント名のみ使用（短すぎると誤マッチ）
        names = [k for k, v in pc.items()
                 if len(k) >= 3 and v.get("lat") is not None]
        names.sort(key=lambda x: -len(x))  # 長い名前を優先（部分マッチ防止）
        _KANSO_POINT_RE = re.compile("|".join(re.escape(n) for n in names))
    except Exception:
        _KANSO_POINT_RE = re.compile(r'(?!)')  # never matches
    return _KANSO_POINT_RE

def _extract_point_from_kanso(comment):
    """kanso_raw から既知ポイント名を検索して返す。見つからなければ空文字。"""
    if not comment:
        return ""
    return (m := _build_kanso_point_re().search(comment)) and m.group(0) or ""

# エリアグループ → weather/ 96地点の代表ポイント（エリアごとに異なる海況を反映）
_GROUP_TO_WX_POINT = {
    "茨城":           "鹿島沖",
    "千葉・外房":     "大原沖",
    "千葉・内房":     "金谷沖",
    "千葉・東京湾奥": "浦安沖",
    "東京":           "羽田沖",
    "神奈川・東京湾": "八景沖",
    "神奈川・相模湾": "城ヶ島沖",
    "静岡":           "真鶴沖",
}
# area_weather_map.json のコード用（Step3フォールバック）
_AREA_CODE_TO_WX_POINT = {
    "tokyo_bay":  "八景沖",
    "sagami_bay": "城ヶ島沖",
    "outer_boso": "大原沖",
    "ibaraki":    "鹿島沖",
}

def _build_catch_weather_index(catches, weather_by_point, tide_data=None, moon_data=None):
    """釣果×海況のJOIN済みインデックスを構築（join_catch_weather.pyの3段階ロジック）
    全ステップで weather/ の96地点3時間粒度データを使用。
    1. point_place が point_coords.json に存在 → そのポイントのweatherデータ
    2. ship_fish_point.json でフォールバック → そのポイントのweatherデータ
    3. area_weather_map.json → エリア代表ポイントのweatherデータ
    """
    if tide_data is None: tide_data = {}
    if moon_data is None: moon_data = {}
    base = os.path.dirname(__file__)
    sfp = _load_ship_fish_point()
    area_map = _load_area_weather_map()

    # point_coords.json
    pc_path = os.path.join(base, "point_coords.json")
    point_coords = {}
    if os.path.exists(pc_path):
        try:
            with open(pc_path, encoding="utf-8") as f:
                pc_raw = json.load(f)
            point_coords = {k: v for k, v in pc_raw.items() if v.get("lat") is not None}
        except Exception:
            pass

    index = []
    for row in catches:
        dt = (row.get("date") or "").replace("/", "-")
        # V2カラム(tsuri_mono)とV1カラム(fish)の両方をサポート
        fish = row.get("tsuri_mono") or row.get("fish", "")
        area = (row.get("area") or "").strip()
        ship = (row.get("ship") or "").strip()
        if not dt or not fish: continue
        # V2ノイズ除外: tsuri_monoが数字のみ（パース失敗行 約2,700件）や「欠航」をスキップ
        if fish.isdigit() or fish == "欠航": continue
        try: cnt = float(row.get("cnt_max", ""))
        except: continue
        month = int(dt[5:7]) if len(dt) >= 7 else None
        group = _area_to_group(area)

        # V2カラム(point_place1)とV1カラム(point_place)の両方をサポート
        pp = (row.get("point_place1") or row.get("point_place") or "").strip()
        wx = None

        # Step 1: point_place が直接解決
        if pp and not _is_unresolvable(pp) and pp in point_coords:
            wx = weather_by_point.get((dt, pp))

        # Step 2: ship_fish_point フォールバック
        if not wx:
            ship_entry = sfp.get(ship, {})
            fish_entry = ship_entry.get(fish) or ship_entry.get("_default")
            if fish_entry and isinstance(fish_entry, dict):
                fb_point = fish_entry.get("point1", "")
                if fb_point and fb_point in point_coords:
                    wx = weather_by_point.get((dt, fb_point))

        # Step 3: エリア代表ポイント（weather/ 96地点から）
        if not wx:
            area_code = area_map.get(area, "tokyo_bay")
            rep_point = _AREA_CODE_TO_WX_POINT.get(area_code, "中ノ瀬")
            wx = weather_by_point.get((dt, rep_point))

        if not wx: continue
        moon = moon_data.get(dt, {})
        index.append({"fish": fish, "cnt": cnt, "wave": wx.get("wave"),
                       "wind": wx.get("wind"), "sst": wx.get("sst"),
                       "wave_period": wx.get("wave_period"),
                       "tide_range": tide_data.get(dt),
                       "moon_age": moon.get("age"),
                       "moon_title": moon.get("title", ""),
                       "month": month, "area": area, "group": group})
    return index

# 魚種別の予測プロファイル（ネット調査 + データ分析に基づく）
# weight: 各要素の重み（0=無視、1=標準、2=重要）
# damping_override: 低匹数でも補正を効かせる場合はNone
FISH_PREDICT_PROFILE = {
    # ── 予測表示対象（バックテスト誤差50%以内） ──
    # 標準型: 波高が主
    "アジ":     {"wave": 1.5, "wind": 0.5, "sst": 0.5, "wave_period": 1.0, "tide": 0.5, "moon": 0.3, "show": True},
    "シロギス": {"wave": 1.5, "wind": 1.0, "sst": 0.8, "wave_period": 0.5, "tide": 0.5, "moon": 0.3, "show": True},
    # SST感応型
    "カワハギ": {"wave": 0.3, "wind": 1.0, "sst": 2.0, "wave_period": 0.3, "tide": 0.5, "moon": 0.3, "show": True},
    # 月齢感応型
    "マルイカ": {"wave": 0.3, "wind": 0.3, "sst": 0.3, "wave_period": 0.3, "tide": 0.5, "moon": 2.0, "show": True},
    # 季節型
    "マダイ":   {"wave": 0.5, "wind": 0.3, "sst": 0.5, "wave_period": 0.5, "tide": 0.5, "moon": 0.3, "show": True},
    "ヒラメ":   {"wave": 0.5, "wind": 0.5, "sst": 0.3, "wave_period": 0.3, "tide": 0.5, "moon": 0.3, "show": True},
    "アマダイ": {"wave": 0.5, "wind": 0.5, "sst": 0.5, "wave_period": 0.3, "tide": 0.3, "moon": 0.3, "show": True},
    "クロムツ": {"wave": 0.5, "wind": 0.3, "sst": 0.5, "wave_period": 0.3, "tide": 0.3, "moon": 0.3, "show": True},
    "イサキ":   {"wave": 0.8, "wind": 0.5, "sst": 0.5, "wave_period": 0.5, "tide": 0.5, "moon": 0.3, "show": True},
    # ── 予測非表示（精度不足: 回遊型・ベイト依存・低匹数） ──
    "カサゴ":   {"wave": 2.0, "wind": 0.3, "sst": 0.3, "wave_period": 2.0, "tide": 0.2, "moon": 0.3, "show": False},
    "メバル":   {"wave": 2.0, "wind": 1.5, "sst": 1.0, "wave_period": 1.5, "tide": 0.5, "moon": 0.3, "show": False},
    "タチウオ": {"wave": 0.3, "wind": 0.3, "sst": 1.5, "wave_period": 0.5, "tide": 1.5, "moon": 0.5, "show": False},
    "フグ":     {"wave": 0.3, "wind": 0.5, "sst": 1.5, "wave_period": 0.5, "tide": 2.0, "moon": 0.5, "show": False},
    "ワラサ":   {"wave": 0.2, "wind": 0.2, "sst": 0.5, "wave_period": 0.2, "tide": 0.3, "moon": 0.2, "show": False},
    "サワラ":   {"wave": 0.2, "wind": 0.2, "sst": 0.3, "wave_period": 0.2, "tide": 0.2, "moon": 0.2, "show": False},
    "ヤリイカ": {"wave": 0.3, "wind": 0.3, "sst": 0.5, "wave_period": 0.3, "tide": 0.5, "moon": 0.5, "show": False},
    "スルメイカ":{"wave": 0.3, "wind": 0.3, "sst": 0.8, "wave_period": 0.3, "tide": 0.3, "moon": 1.0, "show": False},
    "マハタ":   {"wave": 0.3, "wind": 0.3, "sst": 0.3, "wave_period": 0.3, "tide": 0.3, "moon": 0.3, "show": False},
    "キンメダイ":{"wave": 0.3, "wind": 0.3, "sst": 0.3, "wave_period": 0.3, "tide": 0.3, "moon": 0.3, "show": False},
    "メダイ":   {"wave": 0.3, "wind": 0.3, "sst": 0.3, "wave_period": 0.3, "tide": 0.3, "moon": 0.3, "show": False},
}
_DEFAULT_PROFILE = {"wave": 0.5, "wind": 0.5, "sst": 0.5, "wave_period": 0.5, "tide": 0.5, "moon": 0.3}

def _calc_deviation_effect(month_rows, key, norm_val, threshold, base_avg):
    """偏差補正の共通ロジック: low群とhigh群の釣果差から効果量を推定"""
    if norm_val is None or base_avg <= 0:
        return 0.0
    low  = [r["cnt"] for r in month_rows if r.get(key) is not None and r[key] < norm_val - threshold]
    high = [r["cnt"] for r in month_rows if r.get(key) is not None and r[key] > norm_val + threshold]
    if not low or not high:
        return 0.0
    return (sum(high)/len(high) - sum(low)/len(low)) / base_avg

def predict_catches(index, area_forecasts, target_month, forecast_tide=None, forecast_moon=None):
    """偏差ベース予測: エリア×魚種の平常値を基準に、予報日の海況偏差で補正。

    補正要素: 波高・風速・海水温・波周期・潮差・月齢（全6要素）
    低匹数魚種対策: base_avg < 10 の場合は補正幅を縮小
    """
    predictions = {}

    for group, fc in area_forecasts.items():
        fc_wave = fc.get("wave_height")
        fc_sst  = fc.get("sst")
        fc_wind = fc.get("wind_speed")

        group_rows = [r for r in index if r["group"] == group]
        if not group_rows: continue

        fish_groups = {}
        for r in group_rows:
            fish_groups.setdefault(r["fish"], []).append(r)

        for fish, rows in fish_groups.items():
            if fish == "不明": continue
            month_rows = [r for r in rows if r["month"] is not None and
                          (abs(r["month"] - target_month) <= 1 or
                           abs(r["month"] - target_month) >= 11)]
            if len(month_rows) < 5: continue

            # ── 基準値 ──
            cnts = [r["cnt"] for r in month_rows]
            base_avg = sum(cnts) / len(cnts)
            base_max = max(cnts)
            # 中央値（低匹数魚種の外れ値対策）
            sorted_cnts = sorted(cnts)
            base_median = sorted_cnts[len(sorted_cnts) // 2]

            def _norm(key):
                vals = [r[key] for r in month_rows if r.get(key) is not None]
                return sum(vals) / len(vals) if vals else None

            norm_wave = _norm("wave")
            norm_wind = _norm("wind")
            norm_sst  = _norm("sst")
            norm_wp   = _norm("wave_period")
            norm_tide = _norm("tide_range")
            norm_moon = _norm("moon_age")

            # ── 魚種別プロファイルで偏差補正 ──
            prof = FISH_PREDICT_PROFILE.get(fish, _DEFAULT_PROFILE)
            adjustment = 0.0

            # 低匹数魚種は補正幅を縮小
            damping = 1.0
            if base_avg < 5:
                damping = 0.3
            elif base_avg < 10:
                damping = 0.5

            # 波高偏差 (weight: prof["wave"])
            if fc_wave is not None and norm_wave is not None and prof["wave"] > 0:
                effect = _calc_deviation_effect(month_rows, "wave", norm_wave, 0.15, base_avg)
                effect = max(-0.5, min(0.5, effect))
                wave_dev = fc_wave - norm_wave
                adjustment += effect * (wave_dev / max(0.3, norm_wave)) * prof["wave"] * damping

            # 風速偏差 (weight: prof["wind"])
            if fc_wind is not None and norm_wind is not None and prof["wind"] > 0:
                effect = _calc_deviation_effect(month_rows, "wind", norm_wind, 1.0, base_avg)
                effect = max(-0.3, min(0.3, effect))
                wind_dev = fc_wind - norm_wind
                adjustment += effect * (wind_dev / max(1.0, norm_wind)) * 0.5 * prof["wind"] * damping

            # SST偏差 (weight: prof["sst"])
            if fc_sst is not None and norm_sst is not None and prof["sst"] > 0:
                effect = _calc_deviation_effect(month_rows, "sst", norm_sst, 1.0, base_avg)
                effect = max(-0.3, min(0.3, effect))
                sst_dev = fc_sst - norm_sst
                adjustment += effect * (sst_dev / max(1.0, abs(norm_sst))) * 0.5 * prof["sst"] * damping

            # 波周期偏差 (weight: prof["wave_period"])
            fc_wp = fc.get("wave_period")
            if norm_wp is not None and prof["wave_period"] > 0:
                effect = _calc_deviation_effect(month_rows, "wave_period", norm_wp, 0.5, base_avg)
                effect = max(-0.3, min(0.3, effect))
                if fc_wp is not None:
                    # 予報値が直接ある場合はそれを使う
                    wp_dev = fc_wp - norm_wp
                    adjustment += effect * (wp_dev / max(1.0, norm_wp)) * 0.3 * prof["wave_period"] * damping
                elif fc_wave is not None and norm_wave is not None:
                    # フォールバック: 波高から間接推定
                    wp_dev_est = (fc_wave - norm_wave) * 1.5
                    adjustment += effect * (wp_dev_est / max(1.0, norm_wp)) * 0.3 * prof["wave_period"] * damping

            # 潮差偏差 (weight: prof["tide"])
            if forecast_tide is not None and norm_tide is not None and prof["tide"] > 0:
                effect = _calc_deviation_effect(month_rows, "tide_range", norm_tide, 15, base_avg)
                effect = max(-0.3, min(0.3, effect))
                tide_dev = forecast_tide - norm_tide
                adjustment += effect * (tide_dev / max(20, norm_tide)) * 0.5 * prof["tide"] * damping

            # 月齢偏差 (weight: prof["moon"])
            if forecast_moon is not None and norm_moon is not None and prof["moon"] > 0:
                effect = _calc_deviation_effect(month_rows, "moon_age", norm_moon, 3, base_avg)
                effect = max(-0.2, min(0.2, effect))
                moon_dev = forecast_moon - norm_moon
                adjustment += effect * (moon_dev / max(3, norm_moon)) * 0.3 * prof["moon"] * damping

            # 補正を適用（0.6〜1.4。低匹数はさらに狭い範囲）
            max_adj = 0.2 if base_avg < 5 else 0.3 if base_avg < 10 else 0.4
            adjustment = max(-max_adj, min(max_adj, adjustment))
            pred_avg = round(base_avg * (1.0 + adjustment), 1)
            # 低匹数魚種は中央値ベースも加味（外れ値の影響を抑制）
            if base_avg < 10:
                pred_median = round(base_median * (1.0 + adjustment), 1)
                pred_avg = round((pred_avg + pred_median) / 2, 1)

            key = (fish, group)
            season_score = get_season_score(fish, target_month) if target_month else 0
            season_types = SEASON_TYPE.get(fish, [""]*12)
            season_type = season_types[target_month - 1] if target_month and len(season_types) >= target_month else ""
            predictions[key] = {
                "fish": fish,
                "group": group,
                "avg": pred_avg,
                "base_avg": round(base_avg, 1),
                "adjustment": round(adjustment, 3),
                "max": int(base_max),
                "samples": len(month_rows),
                "season_score": season_score,
                "season_type": season_type,
            }

    # 魚種でまとめつつ、エリア別の内訳も保持
    fish_summary = {}
    for (fish, group), pred in predictions.items():
        if fish not in fish_summary:
            fish_summary[fish] = {"areas": [], "total_samples": 0, "weighted_avg": 0}
        fish_summary[fish]["areas"].append(pred)
        fish_summary[fish]["total_samples"] += pred["samples"]
        fish_summary[fish]["weighted_avg"] += pred["avg"] * pred["samples"]

    result = []
    for fish, s in fish_summary.items():
        if s["total_samples"] == 0: continue
        # 予測非表示の魚種はスキップ
        prof = FISH_PREDICT_PROFILE.get(fish, _DEFAULT_PROFILE)
        if not prof.get("show", True):
            continue
        w_avg = round(s["weighted_avg"] / s["total_samples"], 1)
        best_area = max(s["areas"], key=lambda a: a["avg"])
        result.append({
            "fish": fish,
            "avg": w_avg,
            "max": max(a["max"] for a in s["areas"]),
            "samples": s["total_samples"],
            "best_area": best_area["group"],
            "best_avg": best_area["avg"],
            "areas": sorted(s["areas"], key=lambda a: -a["avg"]),
        })

    result.sort(key=lambda x: -(x["samples"] * x["avg"]))
    return result

# ============================================================
# 有料予測ページ用の関数群
# ============================================================

def _enrich_forecast_combos(predictions, catches):
    """predict_catches()結果の各areaにサイズ・船宿TOP3を付与。サイズなしは除外フラグ。"""
    from collections import Counter
    for pred in predictions:
        for area in pred.get("areas", []):
            fish, group = area["fish"], area["group"]
            matching = [c for c in catches
                        if fish in c.get("fish", [])
                        and _area_to_group(c.get("area", "")) == group]
            # サイズ集計（直近catchesのsize_cm）
            sizes = [c["size_cm"] for c in matching
                     if c.get("size_cm") and c["size_cm"].get("min") and c["size_cm"]["min"] > 0]
            if sizes:
                area["size_min"] = min(s["min"] for s in sizes)
                area["size_max"] = max(s["max"] for s in sizes)
            else:
                area["size_min"] = None
                area["size_max"] = None
            # 重量集計
            weights = [c["weight_kg"] for c in matching
                       if c.get("weight_kg") and c["weight_kg"].get("min")]
            if weights:
                area["weight_min"] = min(w["min"] for w in weights)
                area["weight_max"] = max(w["max"] for w in weights)
            else:
                area["weight_min"] = None
                area["weight_max"] = None
            # 船宿TOP3
            ship_counts = Counter(c["ship"] for c in matching)
            area["top_ships"] = [s for s, _ in ship_counts.most_common(3)]


def _condition_label(fish, fc):
    """海況予報値 → 定性表現dict（閾値は非公開）。内部でmaster_datasetの帯域判定を行うが出力は定性のみ。"""
    labels = {}
    wave = fc.get("wave_height") if fc else None
    wind = fc.get("wind_speed") if fc else None
    sst  = fc.get("sst") if fc else None
    pressure = fc.get("pressure") if fc else None

    # 波高
    if wave is not None:
        if wave < 0.5:   labels["wave"] = "好条件"
        elif wave < 1.0: labels["wave"] = "好条件"
        elif wave < 1.5: labels["wave"] = "やや注意"
        else:            labels["wave"] = "注意"
    # 風速
    if wind is not None:
        if wind < 5:     labels["wind"] = "好条件"
        elif wind < 8:   labels["wind"] = "好条件"
        elif wind < 12:  labels["wind"] = "やや注意"
        else:            labels["wind"] = "注意"
    # 水温（定性表現のみ。閾値は非公開）
    if sst is not None:
        labels["sst"] = "適温帯"  # 詳細はmaster_dataset分析で内部判定
    # 気圧
    if pressure is not None:
        labels["pressure"] = _pressure_label(pressure)
    return labels


def _tide_impact_label(fish):
    """魚種ごとの潮汐影響度テキスト（master_datasetの分析結果に基づく）。"""
    # master_datasetの潮汐タイプ別平均差に基づく（±5%以内は「影響限定的」）
    high_impact = {"マダイ", "タチウオ", "フグ", "マルイカ"}
    if fish in high_impact:
        return "影響あり"
    return "影響限定的"


def _calc_confidence(samples, adjustment, season_score):
    """確信度A/B/C/D"""
    if samples >= 500 and abs(adjustment) < 0.15 and season_score >= 4:
        return "A"
    if samples >= 200 and season_score >= 3:
        return "B"
    if samples >= 50:
        return "C"
    return "D"


_WIND_ADVERSE_MAP = {
    "茨城":               {"南東", "東南東", "東", "東北東", "南南東"},
    "千葉・外房":         {"南東", "東南東", "東", "東北東", "南南東"},
    "千葉・内房":         {"北東", "東北東", "東", "北北東"},
    "千葉・東京湾奥":     {"北東", "東北東", "東", "北北東"},
    "東京":               {"北東", "東北東", "東", "北北東"},
    "神奈川・東京湾":     {"北東", "東北東", "東", "北北東"},
    "神奈川・相模湾":     {"南", "南南東", "南東", "南南西"},
}
_WIND_FAVORABLE_MAP = {
    "茨城":               {"北西", "西北西", "西", "西南西"},
    "千葉・外房":         {"北西", "西北西", "西", "西南西"},
    "千葉・内房":         {"南", "南南西", "南西"},
    "千葉・東京湾奥":     {"南", "南南西", "南西"},
    "東京":               {"南", "南南西", "南西"},
    "神奈川・東京湾":     {"南", "南南西", "南西"},
    "神奈川・相模湾":     {"北西", "北北西", "北", "北北東"},
}


def _build_analysis_text(fish, group, fc, trend_weeks, yoy_data, n_samples, season_score, moon_title, sst_trend="stable", month=None):
    """分析段落テキスト生成（閾値は非公開、定性表現のみ）"""
    parts = []
    labels = _condition_label(fish, fc)

    # 海況コメント
    good_count = sum(1 for v in labels.values() if v in ("好条件", "適温帯", "安定", "高気圧"))
    if good_count >= 3:
        parts.append("海況が安定しており、過去の類似条件で釣果が伸びる傾向が確認されている")
    elif good_count >= 2:
        parts.append("海況は概ね良好。安定した釣果が期待できる条件")
    else:
        parts.append("海況にやや不安要素あり。条件次第で釣果が変動する可能性")

    # シーズンスコア定性表現
    season_label_map = {5: "旬盛り", 4: "旬", 3: "平年並み", 2: "端境期", 1: "オフシーズン"}
    season_label = season_label_map.get(season_score, "")
    if season_label:
        if season_score >= 4:
            parts.append(f"シーズン的には「{season_label}」で活性が高い時期")
        elif season_score == 3:
            parts.append(f"シーズンは{season_label}で安定して出船がある時期")
        else:
            parts.append(f"シーズン的には「{season_label}」にあたり出船数は少なめ")

    # 来月展望（SEASON_DATAで来月スコアと比較）
    if month is not None:
        next_month = (month % 12) + 1
        next_score = get_season_score(fish, next_month)
        if next_score > season_score:
            parts.append(f"来月（{next_month}月）に向けてシーズンが上向く見込み")
        elif next_score < season_score and season_score >= 4:
            parts.append(f"今がピーク。{next_month}月以降は徐々に落ち着く傾向")

    # SST傾向（7日間予報の前半→後半の変化から推定）
    if sst_trend == "rising":
        parts.append("今週を通じて海水温は上昇傾向。魚の活性が高まる方向")
    elif sst_trend == "declining":
        parts.append("海水温はやや低下傾向。水温変化への適応が遅い魚種は注意")

    # 風向き影響（エリア別の有利/不利方向マップ）
    wind_dir = fc.get("wind_dir") if fc else None
    if wind_dir is not None:
        dir_text = _wind_dir_text(wind_dir)
        if dir_text:
            if dir_text in _WIND_ADVERSE_MAP.get(group, set()):
                parts.append(f"{dir_text}風は{group}エリアでは時化やすく出船に影響する可能性")
            elif dir_text in _WIND_FAVORABLE_MAP.get(group, set()):
                parts.append(f"{dir_text}風はこのエリアで穏やかな海況をもたらす傾向")

    # 平均匹数トレンド（3週連続変化）
    if trend_weeks and len(trend_weeks) >= 3:
        avgs = [w.get("avg", 0) for w in trend_weeks[-3:]]
        if all(avgs[i] < avgs[i+1] for i in range(len(avgs)-1)):
            vals = "←".join(f"{a:.0f}匹" for a in reversed(avgs))
            parts.append(f"{len(avgs)}週連続上昇中（{vals}）")
        elif all(avgs[i] > avgs[i+1] for i in range(len(avgs)-1)):
            parts.append(f"{len(avgs)}週連続で減少傾向")

    # 船数トレンド（前週比）
    if trend_weeks and len(trend_weeks) >= 2:
        ships_prev = trend_weeks[-2].get("ships", 0)
        ships_curr = trend_weeks[-1].get("ships", 0)
        if ships_prev > 0 and ships_curr > 0:
            ships_pct = round((ships_curr - ships_prev) / ships_prev * 100)
            if ships_pct >= 30:
                parts.append(f"出船数が前週から大幅増（+{ships_pct}%）。人気が集まっている")
            elif ships_pct <= -30:
                parts.append(f"出船数が前週から減少（{ships_pct}%）")

    # 昨年比
    if yoy_data:
        this_avg = yoy_data.get("this_avg")
        last_avg = yoy_data.get("last_avg")
        if this_avg and last_avg and last_avg > 0:
            pct = round((this_avg - last_avg) / last_avg * 100)
            if pct > 10:
                parts.append(f"昨年同週を上回るペースで推移（+{pct}%）")
            elif pct < -10:
                parts.append(f"昨年同週を下回るペース（{pct}%）")

    # サンプル数
    parts.append(f"分析データ: {n_samples:,}件")

    return "。".join(parts)


def _build_uncertainty_text(fish, group, confidence, samples):
    """確信度C/D向けの予測ブレ要因テキスト"""
    if confidence in ("A", "B"):
        return ""
    parts = []
    if samples < 100:
        parts.append("分析データが少なく、予測の精度が出にくい")
    # 魚種固有のブレ要因
    uncertainty_map = {
        "マダイ": "個体差が大きく匹数予測の精度が出にくい魚種",
        "ワラサ": "回遊魚のため群れの接岸状況に大きく左右される",
        "カツオ": "回遊次第で釣果が極端に変動する",
        "サワラ": "回遊パターンが不安定で予測が難しい魚種",
        "タチウオ": "群れの移動が速く、日による変動が大きい",
        "ヤリイカ": "群れの接岸状況で大きく変動する",
        "スルメイカ": "群れの接岸状況で大きく変動する",
    }
    if fish in uncertainty_map:
        parts.append(uncertainty_map[fish])
    if not parts:
        parts.append("海況変動の影響を受けやすく、予報が外れると釣果が大きく変動する可能性")
    return "。".join(parts)


def _select_todays_pick(predictions, prev_pick_fish=None):
    """TODAY'S PICK選出。偏り防止: 前日と同じ魚種なら2位を採用。"""
    if not predictions:
        return None
    # compositeスコア順（samples * avg）で最高のものを選出
    for pred in predictions:
        if pred.get("areas"):
            best = pred["areas"][0]  # avg最高のエリア
            if prev_pick_fish and best["fish"] == prev_pick_fish and len(predictions) > 1:
                continue  # 前日と同じなら次へ
            return best
    return predictions[0]["areas"][0] if predictions and predictions[0].get("areas") else None


def _get_trend_weeks(history, fish, n=4):
    """直近n週の推移データを取得"""
    weekly = history.get("weekly", {})
    year, week_num = current_iso_week()
    weeks = []
    for i in range(n, 0, -1):
        w = week_num - i
        y = year
        if w <= 0:
            w += 52
            y -= 1
        key = f"{y}/W{w:02d}"
        d = weekly.get(key, {}).get(fish)
        if d:
            weeks.append({"week": key, "avg": d.get("avg", 0), "ships": d.get("ships", 0)})
    return weeks


def build_forecast_json(weather_data, catches=None, history=None):
    """forecast.json を生成: 7日分の海況予報 × 釣果予測 + 2〜4週後の週次予測"""
    forecasts = weather_data.get("forecast", {})
    if not forecasts:
        return None

    print("過去データ読み込み中...")
    hist_catches = _load_historical_catches()
    hist_weather = _load_historical_weather()
    tide_data = _load_tide_data()
    moon_data = _load_moon_data()
    index = _build_catch_weather_index(hist_catches, hist_weather, tide_data, moon_data)
    print(f"  釣果×海況インデックス: {len(index)} 件（潮汐{len(tide_data)}日・月齢{len(moon_data)}日）")

    if history is None:
        history = {}

    result = {"generated_at": datetime.now().strftime("%Y/%m/%d %H:%M"), "days": {}, "weeks": {}}

    # ── エリア別SST傾向（7日間予報の前半→後半で変化方向を計算）──
    _area_sst_pairs = {}
    for (grp, d), fc in forecasts.items():
        if fc.get("sst") is not None:
            _area_sst_pairs.setdefault(grp, []).append((d, fc["sst"]))
    area_sst_trends = {}
    for grp, pairs in _area_sst_pairs.items():
        pairs.sort()
        if len(pairs) >= 4:
            mid = len(pairs) // 2
            avg_early = sum(v for _, v in pairs[:mid]) / mid
            avg_late  = sum(v for _, v in pairs[mid:]) / (len(pairs) - mid)
            diff = avg_late - avg_early
            area_sst_trends[grp] = "rising" if diff > 0.4 else "declining" if diff < -0.4 else "stable"
        else:
            area_sst_trends[grp] = "stable"

    # ── 日次予測（7日分）──
    all_dates = sorted(set(d for (_, d) in forecasts.keys()))
    prev_pick_fish = None
    for date_str in all_dates:
        waves, winds, ssts, pressures, weather_codes = [], [], [], [], []
        area_forecasts = {}
        for (group, d), fc in forecasts.items():
            if d != date_str: continue
            area_forecasts[group] = fc
            if fc.get("wave_height") is not None: waves.append(fc["wave_height"])
            if fc.get("wind_speed") is not None: winds.append(fc["wind_speed"])
            if fc.get("sst") is not None: ssts.append(fc["sst"])
            if fc.get("pressure") is not None: pressures.append(fc["pressure"])
            if fc.get("weather_code") is not None: weather_codes.append(fc["weather_code"])

        avg_wave = round(sum(waves)/len(waves), 1) if waves else None
        avg_wind = round(sum(winds)/len(winds), 1) if winds else None
        avg_sst  = round(sum(ssts)/len(ssts), 1)   if ssts  else None
        avg_pressure = round(sum(pressures)/len(pressures), 1) if pressures else None
        wc_mode = max(set(weather_codes), key=weather_codes.count) if weather_codes else None
        month = int(date_str[5:7]) if len(date_str) >= 7 else None

        score = _fishing_ok_score(avg_wave, avg_wind)
        ok_txt, _ = _ok_label(score)
        fc_tide = _calc_tide_range(date_str)
        fc_moon = _calc_moon_age(date_str)

        predictions = predict_catches(index, area_forecasts, month,
                                      forecast_tide=fc_tide,
                                      forecast_moon=fc_moon) if month else []

        # enrichment: サイズ・船宿を付与
        if catches:
            _enrich_forecast_combos(predictions, catches)

        # 全エリアの詳細予測を展開（確信度・分析テキスト付き）
        year, week_num = current_iso_week()
        detailed_predictions = []
        for pred in predictions:
            for area in pred.get("areas", []):
                fish = area["fish"]
                # サイズなしは除外
                if area.get("size_min") is None and catches:
                    continue
                confidence = _calc_confidence(area["samples"], area["adjustment"],
                                              area.get("season_score", 0))
                fc_for_area = area_forecasts.get(area["group"], {})
                trend_weeks = _get_trend_weeks(history, fish)
                this_w, last_w = get_yoy_data(history, fish, year, week_num)
                yoy_data = None
                if this_w and last_w:
                    yoy_data = {"this_avg": this_w.get("avg"), "last_avg": last_w.get("avg")}
                sst_trend = area_sst_trends.get(area["group"], "stable")
                analysis = _build_analysis_text(fish, area["group"], fc_for_area,
                                                 trend_weeks, yoy_data, area["samples"],
                                                 area.get("season_score", 0),
                                                 _moon_title(fc_moon),
                                                 sst_trend=sst_trend,
                                                 month=month)
                uncertainty = _build_uncertainty_text(fish, area["group"], confidence, area["samples"])
                detailed_predictions.append({
                    "fish": fish,
                    "group": area["group"],
                    "avg": area["avg"],
                    "base_avg": area["base_avg"],
                    "adjustment": area["adjustment"],
                    "max": area["max"],
                    "samples": area["samples"],
                    "season_score": area.get("season_score", 0),
                    "season_type": area.get("season_type", ""),
                    "size_min": area.get("size_min"),
                    "size_max": area.get("size_max"),
                    "weight_min": area.get("weight_min"),
                    "weight_max": area.get("weight_max"),
                    "top_ships": area.get("top_ships", []),
                    "confidence": confidence,
                    "analysis": analysis,
                    "uncertainty": uncertainty,
                    "condition_labels": _condition_label(fish, fc_for_area),
                    "tide_impact": _tide_impact_label(fish),
                    "sst_trend": sst_trend,
                })

        # TODAY'S PICK
        pick = _select_todays_pick(predictions, prev_pick_fish)
        if pick:
            prev_pick_fish = pick["fish"]

        # エリア別海況
        area_detail = {}
        for g, fc in area_forecasts.items():
            s = _fishing_ok_score(fc.get("wave_height"), fc.get("wind_speed"))
            area_detail[g] = {
                "wave": fc.get("wave_height"), "wind": fc.get("wind_speed"),
                "sst": fc.get("sst"), "wind_dir": fc.get("wind_dir"),
                "weather_text": fc.get("weather_text", ""),
                "pressure": fc.get("pressure"),
                "score": s, "ok": _ok_label(s)[0],
            }

        result["days"][date_str] = {
            "wave": avg_wave, "wind": avg_wind, "sst": avg_sst,
            "pressure": avg_pressure,
            "weather_code": wc_mode,
            "weather_text": _weather_code_text(wc_mode),
            "tide_range": fc_tide, "moon_age": fc_moon,
            "moon_title": _moon_title(fc_moon),
            "score": score, "ok": ok_txt,
            "areas": area_detail,
            "predictions": detailed_predictions,
            "todays_pick": pick["fish"] + "×" + pick["group"] if pick else None,
        }

    # ── 週次予測（2〜4週後）──
    today = datetime.now()
    for week_offset in range(2, 5):
        week_start = today + timedelta(days=(7 * week_offset - today.weekday()))
        week_end = week_start + timedelta(days=6)
        mid_date = week_start + timedelta(days=3)
        week_id = f"{mid_date.isocalendar()[0]}-W{mid_date.isocalendar()[1]:02d}"
        month = mid_date.month

        fc_tide = _calc_tide_range(mid_date.strftime("%Y-%m-%d"))
        fc_moon = _calc_moon_age(mid_date.strftime("%Y-%m-%d"))

        # 海況なし（空のarea_forecasts）→ 潮差・月齢のみで補正
        empty_forecasts = {g: {} for g in AREA_FORECAST_COORDS}
        predictions = predict_catches(index, empty_forecasts, month,
                                      forecast_tide=fc_tide, forecast_moon=fc_moon)

        if catches:
            _enrich_forecast_combos(predictions, catches)

        weekly_predictions = []
        for pred in predictions:
            for area in pred.get("areas", []):
                if area.get("size_min") is None and catches:
                    continue
                confidence = _calc_confidence(area["samples"], area["adjustment"],
                                              area.get("season_score", 0))
                weekly_predictions.append({
                    "fish": area["fish"],
                    "group": area["group"],
                    "avg": area["avg"],
                    "max": area["max"],
                    "samples": area["samples"],
                    "season_score": area.get("season_score", 0),
                    "season_type": area.get("season_type", ""),
                    "size_min": area.get("size_min"),
                    "size_max": area.get("size_max"),
                    "top_ships": area.get("top_ships", []),
                    "confidence": confidence,
                    "tide_impact": _tide_impact_label(area["fish"]),
                })

        # 週の潮回りスケジュール
        tide_schedule = []
        for i in range(7):
            d = week_start + timedelta(days=i)
            ds = d.strftime("%Y-%m-%d")
            tide_schedule.append({
                "date": ds,
                "weekday": ["月","火","水","木","金","土","日"][d.weekday()],
                "moon_title": _moon_title(_calc_moon_age(ds)),
            })

        result["weeks"][week_id] = {
            "label": f"{week_offset}週後",
            "start": week_start.strftime("%Y-%m-%d"),
            "end": week_end.strftime("%Y-%m-%d"),
            "month": month,
            "tide_schedule": tide_schedule,
            "moon_age": fc_moon,
            "moon_title": _moon_title(fc_moon),
            "predictions": weekly_predictions,
        }

    return result

# ============================================================
# 有料予測ページ HTML生成
# ============================================================

_FORECAST_EXTRA_CSS = """.date-nav{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:16px}
.date-nav a{display:inline-block;padding:6px 12px;background:var(--card);border:1px solid var(--border);border-radius:6px;color:var(--sub);font-size:12px;text-decoration:none}
.date-nav a:hover,.date-nav a.active{color:var(--cta);border-color:var(--cta)}
.date-nav a.weekend{font-weight:bold}
.wx-dash{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-bottom:16px}
.wx-panel{background:var(--card);border:1px solid var(--border);border-radius:var(--r);padding:10px;text-align:center}
.wx-panel-icon{font-size:18px}
.wx-panel-value{display:block;font-size:16px;font-weight:bold;color:var(--accent);margin:4px 0 2px}
.wx-panel-label{font-size:10px;color:var(--muted)}
.wx-panel-note{font-size:11px;color:var(--sub)}
.area-chips{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:16px}
.area-chip{padding:6px 12px;border-radius:16px;font-size:12px;text-decoration:none;font-weight:bold}
.area-chip.ok-good{background:#e8f7ee;color:var(--pos);border:1px solid #b8ddc8}
.area-chip.ok-fair{background:#fff8e6;color:var(--warn);border:1px solid #e8d898}
.area-chip.ok-warn{background:#fff0e6;color:var(--cta);border:1px solid #f0c8a0}
.area-chip.ok-bad{background:#fce8e8;color:var(--neg);border:1px solid #e8b8b8}
.pick-card{background:var(--card);border:1px solid var(--border);border-top:3px solid var(--warn);border-radius:var(--r);padding:20px;margin-bottom:20px}
.pick-label{font-size:10px;color:var(--warn);letter-spacing:2px;font-weight:bold;margin-bottom:8px}
.pick-fish{font-size:20px;font-weight:bold;color:var(--accent)}
.pick-range{font-size:14px;color:var(--sub);margin:6px 0}
.pick-analysis{font-size:13px;color:var(--sub);line-height:1.7;margin:10px 0;background:#f8f9fb;border-left:3px solid var(--warn);padding:10px 14px;border-radius:0 var(--r) var(--r) 0}
.pick-meta{font-size:11px;color:var(--muted)}
.pred-table{width:100%;border-collapse:collapse;margin-bottom:16px}
.pred-table th{background:var(--accent);color:#fff;padding:8px;font-size:11px;text-align:left}
.pred-table td{padding:10px 8px;border-bottom:1px solid var(--border);font-size:13px}
.pred-table tr:hover td{background:#f0f4f8}
.conf-badge{display:inline-block;padding:2px 8px;border-radius:4px;font-size:11px;font-weight:bold}
.conf-A{background:var(--cta);color:#fff}
.conf-B{background:var(--accent);color:#fff}
.conf-C{background:#d0d8e8;color:var(--sub)}
.conf-D{background:var(--bg);color:var(--muted);border:1px solid var(--border)}
.trend-up{color:var(--pos)}.trend-down{color:var(--neg)}.trend-flat{color:var(--muted)}
.detail-card{background:var(--card);border:1px solid var(--border);border-radius:var(--r);padding:16px;margin-bottom:12px}
.detail-card.high-conf{border-top:3px solid var(--cta)}
.detail-card.low-conf{border-top:3px solid var(--muted)}
.dc-header{display:flex;justify-content:space-between;align-items:center;margin-bottom:8px}
.dc-fish{font-size:16px;font-weight:bold;color:var(--accent)}
.dc-range{font-size:14px;color:var(--sub);margin-bottom:6px}
.dc-factors{display:flex;gap:8px;flex-wrap:wrap;margin:8px 0}
.dc-factor{font-size:12px;padding:4px 8px;border-radius:4px}
.dc-factor.good{background:#e8f7ee;color:var(--pos)}
.dc-factor.warn{background:#fff8e6;color:var(--warn)}
.dc-factor.bad{background:#fce8e8;color:var(--neg)}
.dc-factor.neutral{background:#f0f3f7;color:var(--sub)}
.dc-analysis{font-size:13px;color:var(--sub);line-height:1.7;margin:10px 0;padding:10px;background:#f8f9fb;border-radius:6px}
.dc-uncertainty{font-size:12px;color:var(--warn);margin:8px 0;padding:8px;background:#fff8e6;border-left:3px solid var(--warn);border-radius:0 6px 6px 0}
.dc-ships{font-size:12px;color:var(--muted)}
.paywall{text-align:center;padding:30px;background:linear-gradient(transparent,var(--bg) 40%);margin-top:10px}
.paywall-btn{display:inline-block;background:var(--cta);color:#fff;padding:12px 32px;border-radius:24px;font-size:14px;font-weight:bold;text-decoration:none}
.paywall-btn:hover{background:var(--cta2)}
.paywall-sub{font-size:12px;color:var(--muted);margin-top:8px}
.blur-text{filter:blur(6px);user-select:none}
.section-note{font-size:12px;color:var(--muted);margin-bottom:12px}
@media(max-width:640px){.wx-dash{grid-template-columns:repeat(2,1fr)}.pred-table{font-size:12px}}
"""


def _forecast_page_head(title):
    return f"""<!DOCTYPE html>
<html lang="ja"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title} | 船釣り予想</title>
{GA_TAG}
{ADSENSE_TAG}
<style>{V2_COMMON_CSS}
{_FORECAST_EXTRA_CSS}</style>
</head><body>
{_v2_header_nav('forecast')}
<div class="c">
<p class="bread"><a href="/index.html">トップ</a> &rsaquo; <a href="/forecast/index.html">釣果予測</a> &rsaquo; {title}</p>"""


def _forecast_page_foot():
    return f"""</div>
{_v2_footer()}
{_v2_bottom_nav('prem')}
</body></html>"""


def _forecast_date_nav(all_dates, all_weeks, current):
    """日付ナビバー"""
    html = '<div class="date-nav">'
    for d in all_dates:
        m, dd = int(d[5:7]), int(d[8:10])
        wd_idx = datetime.strptime(d, "%Y-%m-%d").weekday()
        wd = ["月","火","水","木","金","土","日"][wd_idx]
        cls = " active" if d == current else ""
        cls += " weekend" if wd_idx >= 5 else ""
        html += f'<a href="{d}.html" class="{cls.strip()}">{m}/{dd}({wd})</a>'
    for wk_id, wk in all_weeks.items():
        cls = " active" if wk_id == current else ""
        html += f'<a href="{wk_id}.html" class="{cls.strip()}">{wk["label"]}</a>'
    html += '</div>'
    return html


def _forecast_combo_card(pred, fc=None, show_area=True):
    """予測詳細カードHTML"""
    fish = pred["fish"]
    group = pred.get("group", "")
    conf = pred.get("confidence", "D")
    cls = "high-conf" if conf in ("A", "B") else "low-conf"
    title = f"{fish} × {group}" if show_area else fish

    avg = pred.get("avg", 0)
    pred_min = max(1, round(avg * 0.6))
    pred_max = pred.get("max", round(avg * 1.4))

    size_str = ""
    if pred.get("size_min") and pred.get("size_max"):
        size_str = f' / {pred["size_min"]}〜{pred["size_max"]}cm'
    weight_str = ""
    if pred.get("weight_min") and pred.get("weight_max"):
        weight_str = f' / {pred["weight_min"]}〜{pred["weight_max"]}kg'

    season_type = pred.get("season_type", "")
    type_str = f"{'数' if season_type == '数' else '型' if season_type == '型' else '数＆型'}狙い" if season_type else ""

    # 海況ファクター
    labels = pred.get("condition_labels", {})
    factors_html = ""
    for key, icon in [("wave", "🌊 波高"), ("wind", "💨 風"), ("sst", "🌡️ 水温"), ("pressure", "📊 気圧")]:
        label = labels.get(key, "")
        if label:
            cls_f = "good" if label in ("好条件", "適温帯", "安定", "高気圧") else "warn" if "注意" in label else "neutral"
            factors_html += f'<span class="dc-factor {cls_f}">{icon} → {label}</span>'
    tide = pred.get("tide_impact", "")
    if tide:
        cls_t = "neutral" if "限定" in tide else "good"
        factors_html += f'<span class="dc-factor {cls_t}">🌙 潮 → {tide}</span>'
    sst_trend = pred.get("sst_trend", "stable")
    if sst_trend == "rising":
        factors_html += '<span class="dc-factor good">🌡️ 水温推移 → 上昇傾向</span>'
    elif sst_trend == "declining":
        factors_html += '<span class="dc-factor warn">🌡️ 水温推移 → 低下傾向</span>'

    analysis = pred.get("analysis", "")
    uncertainty = pred.get("uncertainty", "")
    ships = pred.get("top_ships", [])

    html = f"""<div class="detail-card {cls}">
<div class="dc-header"><span class="dc-fish">{title}</span><span class="conf-badge conf-{conf}">{conf}</span></div>
<div class="dc-range">予測 {pred_min}〜{pred_max}匹{size_str}{weight_str}　{type_str}</div>
<div class="dc-factors">{factors_html}</div>"""
    if analysis:
        html += f'<div class="dc-analysis">{analysis}</div>'
    if uncertainty:
        html += f'<div class="dc-uncertainty">⚠️ 予測のブレ要因: {uncertainty}</div>'
    if ships:
        html += f'<div class="dc-ships">📍 {" / ".join(ships)}</div>'
    html += '</div>'
    return html


def _build_daily_page(date_str, day_data, forecast_data, weather_data):
    """日次予測ページHTML"""
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    m, d = dt.month, dt.day
    wd = ["月","火","水","木","金","土","日"][dt.weekday()]
    title = f"{m}月{d}日({wd}) 釣果予測"

    html = _forecast_page_head(title)

    # 日付ナビ
    all_dates = sorted(forecast_data.get("days", {}).keys())
    all_weeks = forecast_data.get("weeks", {})
    html += _forecast_date_nav(all_dates, all_weeks, date_str)

    # 海況ダッシュボード
    wave = day_data.get("wave")
    wind = day_data.get("wind")
    sst = day_data.get("sst")
    pressure = day_data.get("pressure")
    weather = day_data.get("weather_text", "")
    moon_age = day_data.get("moon_age")
    moon_title = day_data.get("moon_title", "")
    ok = day_data.get("ok", "")

    html += f"""<h2>{m}月{d}日({wd}) 海況</h2>
<div class="wx-dash">
<div class="wx-panel"><span class="wx-panel-icon">🌊</span><span class="wx-panel-value">{wave}m</span><span class="wx-panel-label">波高</span><span class="wx-panel-note">{_wave_label(wave)}</span></div>
<div class="wx-panel"><span class="wx-panel-icon">💨</span><span class="wx-panel-value">{wind}m/s</span><span class="wx-panel-label">風速</span><span class="wx-panel-note">{_wind_label(wind)}</span></div>
<div class="wx-panel"><span class="wx-panel-icon">☀️</span><span class="wx-panel-value">{weather or '-'}</span><span class="wx-panel-label">天気</span></div>
<div class="wx-panel"><span class="wx-panel-icon">📊</span><span class="wx-panel-value">{pressure or '-'}hPa</span><span class="wx-panel-label">気圧</span><span class="wx-panel-note">{_pressure_label(pressure)}</span></div>
<div class="wx-panel"><span class="wx-panel-icon">🌡️</span><span class="wx-panel-value">{sst or '-'}℃</span><span class="wx-panel-label">海水温</span></div>
<div class="wx-panel"><span class="wx-panel-icon">🌙</span><span class="wx-panel-value">{moon_title}</span><span class="wx-panel-label">月齢{moon_age or ''}</span></div>
</div>
<p style="font-size:14px;color:#fff;margin-bottom:8px">出船判定: {ok}</p>"""

    # エリア別チップ（リンク付き）
    areas = day_data.get("areas", {})
    html += '<div class="area-chips">'
    for g, a in areas.items():
        s = a.get("score", 0)
        cls = "ok-good" if s >= 70 else "ok-fair" if s >= 45 else "ok-warn" if s >= 20 else "ok-bad"
        ok_mark = a.get("ok", "")
        html += f'<a href="area/{area_slug(g)}.html" class="area-chip {cls}">{g} {ok_mark}</a>'
    html += '</div>'

    preds = day_data.get("predictions", [])
    if not preds:
        html += '<p style="color:#7a9bb5">予測データなし</p>'
        html += _forecast_page_foot()
        return html

    # TODAY'S PICK
    pick_name = day_data.get("todays_pick")
    if pick_name and preds:
        pick = next((p for p in preds if f'{p["fish"]}×{p["group"]}' == pick_name), preds[0])
        avg = pick.get("avg", 0)
        pred_min = max(1, round(avg * 0.6))
        pred_max = pick.get("max", round(avg * 1.4))
        size_str = f' / {pick["size_min"]}〜{pick["size_max"]}cm' if pick.get("size_min") else ""
        analysis = pick.get("analysis", "")
        ships = pick.get("top_ships", [])
        html += f"""<div class="pick-card">
<div class="pick-label">TODAY'S PICK</div>
<div class="pick-fish">{pick['fish']} × {pick['group']}</div>
<div class="pick-range">予測 {pred_min}〜{pred_max}匹{size_str}　{pick.get('season_type','')}{'狙い' if pick.get('season_type') else ''}</div>
<div class="pick-analysis">{analysis}</div>
<div class="pick-meta">📍 {' / '.join(ships)}　分析データ: {pick.get('samples',0):,}件</div>
</div>"""

    # 予測一覧テーブル（エリア別セクション）
    html += '<h2>予測一覧</h2>'
    # エリアでグループ化
    area_groups = {}
    for p in preds:
        area_groups.setdefault(p["group"], []).append(p)

    for group, group_preds in area_groups.items():
        area_info = areas.get(group, {})
        area_ok = area_info.get("ok", "")
        html += f'<h3 id="area-{quote(group, safe="")}">{group} {area_ok}</h3>'
        html += '<table class="pred-table"><thead><tr>'
        html += '<th>魚種</th><th>予測匹数</th><th>型</th><th>狙い</th><th>傾向</th><th>確信度</th>'
        html += '</tr></thead><tbody>'
        for p in sorted(group_preds, key=lambda x: -x.get("avg", 0)):
            avg = p.get("avg", 0)
            pred_min = max(1, round(avg * 0.6))
            pred_max = p.get("max", round(avg * 1.4))
            size = f'{p["size_min"]}〜{p["size_max"]}cm' if p.get("size_min") else "-"
            st = p.get("season_type", "")
            type_str = "数" if st == "数" else "型" if st == "型" else "数＆型" if st else "-"
            adj = p.get("adjustment", 0)
            trend = '<span class="trend-up">↑</span>' if adj > 0.05 else '<span class="trend-down">↓</span>' if adj < -0.05 else '<span class="trend-flat">→</span>'
            conf = p.get("confidence", "D")
            html += f'<tr><td>{p["fish"]}</td><td>{pred_min}〜{pred_max}匹</td><td>{size}</td><td>{type_str}</td><td>{trend}</td><td><span class="conf-badge conf-{conf}">{conf}</span></td></tr>'
        html += '</tbody></table>'

        # 詳細カード
        for p in sorted(group_preds, key=lambda x: -x.get("avg", 0)):
            html += _forecast_combo_card(p, show_area=False)

    html += _forecast_page_foot()
    return html


def _build_weekly_page(week_id, week_data, forecast_data):
    """週次予測ページHTML"""
    label = week_data.get("label", "")
    start = week_data.get("start", "")
    end = week_data.get("end", "")
    s_m, s_d = int(start[5:7]), int(start[8:10]) if start else (0, 0)
    e_m, e_d = int(end[5:7]), int(end[8:10]) if end else (0, 0)
    title = f"{label} ({s_m}/{s_d}〜{e_m}/{e_d}) 釣果トレンド予測"

    html = _forecast_page_head(title)
    all_dates = sorted(forecast_data.get("days", {}).keys())
    all_weeks = forecast_data.get("weeks", {})
    html += _forecast_date_nav(all_dates, all_weeks, week_id)

    # 潮回りスケジュール
    html += f'<h2>{title}</h2>'
    moon_title = week_data.get("moon_title", "")
    html += f'<p style="color:#7a9bb5;margin-bottom:12px">🌙 {moon_title}　⚠️ 海況予報なし（季節傾向＋潮汐で予測）</p>'

    schedule = week_data.get("tide_schedule", [])
    if schedule:
        html += '<div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:16px">'
        for s in schedule:
            dd = int(s["date"][8:10])
            html += f'<span style="background:#0d2137;border:1px solid #1a4060;border-radius:6px;padding:6px 10px;font-size:12px">{dd}({s["weekday"]}) {s["moon_title"]}</span>'
        html += '</div>'

    preds = week_data.get("predictions", [])
    if preds:
        html += '<table class="pred-table"><thead><tr><th>魚種</th><th>エリア</th><th>予測匹数</th><th>型</th><th>狙い</th><th>確信度</th></tr></thead><tbody>'
        for p in sorted(preds, key=lambda x: -x.get("avg", 0)):
            avg = p.get("avg", 0)
            pred_min = max(1, round(avg * 0.6))
            pred_max = p.get("max", round(avg * 1.4))
            size = f'{p["size_min"]}〜{p["size_max"]}cm' if p.get("size_min") else "-"
            st = p.get("season_type", "")
            type_str = "数" if st == "数" else "型" if st == "型" else "-"
            conf = p.get("confidence", "D")
            html += f'<tr><td>{p["fish"]}</td><td>{p["group"]}</td><td>{pred_min}〜{pred_max}匹</td><td>{size}</td><td>{type_str}</td><td><span class="conf-badge conf-{conf}">{conf}</span></td></tr>'
        html += '</tbody></table>'

    html += _forecast_page_foot()
    return html


def _build_area_forecast_page(area_group, forecast_data):
    """エリア別予測ページHTML"""
    title = f"{area_group} 釣果予測"
    html = _forecast_page_head(title)
    all_dates = sorted(forecast_data.get("days", {}).keys())
    all_weeks = forecast_data.get("weeks", {})
    html += _forecast_date_nav(all_dates, all_weeks, "")

    # 7日間サマリー（日付→日次ページリンク）
    html += f'<h2>{area_group} 予測</h2>'
    html += '<div class="date-nav">'
    for d in all_dates:
        day = forecast_data["days"].get(d, {})
        area_info = day.get("areas", {}).get(area_group, {})
        ok = area_info.get("ok", "")
        m, dd = int(d[5:7]), int(d[8:10])
        wd_idx = datetime.strptime(d, "%Y-%m-%d").weekday()
        wd = ["月","火","水","木","金","土","日"][wd_idx]
        cls = " weekend" if wd_idx >= 5 else ""
        html += f'<a href="{d}.html#area-{quote(area_group, safe="")}" class="{cls.strip()}">{m}/{dd}({wd}) {ok}</a>'
    html += '</div>'

    # このエリアの予測一覧（最新日のデータ）
    if all_dates:
        latest = all_dates[-1]
        # 次の土曜があればそちらを優先
        for d in all_dates:
            if datetime.strptime(d, "%Y-%m-%d").weekday() == 5:
                latest = d
                break
        day = forecast_data["days"].get(latest, {})
        preds = [p for p in day.get("predictions", []) if p.get("group") == area_group]

        if preds:
            html += f'<h3>このエリアの予測一覧（{latest}）</h3>'
            html += '<table class="pred-table"><thead><tr><th>魚種</th><th>予測匹数</th><th>型</th><th>狙い</th><th>傾向</th><th>確信度</th></tr></thead><tbody>'
            for p in sorted(preds, key=lambda x: -x.get("avg", 0)):
                avg = p.get("avg", 0)
                pred_min = max(1, round(avg * 0.6))
                pred_max = p.get("max", round(avg * 1.4))
                size = f'{p["size_min"]}〜{p["size_max"]}cm' if p.get("size_min") else "-"
                st = p.get("season_type", "")
                type_str = "数" if st == "数" else "型" if st == "型" else "数＆型" if st else "-"
                adj = p.get("adjustment", 0)
                trend = '<span class="trend-up">↑</span>' if adj > 0.05 else '<span class="trend-down">↓</span>' if adj < -0.05 else '<span class="trend-flat">→</span>'
                conf = p.get("confidence", "D")
                html += f'<tr><td>{p["fish"]}</td><td>{pred_min}〜{pred_max}匹</td><td>{size}</td><td>{type_str}</td><td>{trend}</td><td><span class="conf-badge conf-{conf}">{conf}</span></td></tr>'
            html += '</tbody></table>'

            # 詳細カード
            for p in sorted(preds, key=lambda x: -x.get("avg", 0)):
                html += _forecast_combo_card(p, show_area=False)

    html += _forecast_page_foot()
    return html


def _build_forecast_hub(forecast_data, catches=None):
    """有料トップページHTML（予測結果レポート＋チラ見せ＋料金）"""
    html = _forecast_page_head("釣果予測 プレミアム")

    # ── 予測結果レポート（1件完全＋4件ぼかし）──
    html += '<h2>📊 予測結果レポート</h2>'
    # TODO: evaluate_predictions()で実績と突合。現時点ではプレースホルダ
    html += '<p class="section-note">34,800件超の実績データに基づく独自分析。予測精度は継続的に検証しています。</p>'

    # ── 今日の予測チラ見せ ──
    days = forecast_data.get("days", {})
    all_dates = sorted(days.keys())
    all_weeks = forecast_data.get("weeks", {})

    html += '<h2>📅 日付から探す</h2>'
    html += _forecast_date_nav(all_dates, all_weeks, "")

    if all_dates:
        # 次の土曜を優先表示
        show_date = all_dates[0]
        for d in all_dates:
            if datetime.strptime(d, "%Y-%m-%d").weekday() == 5:
                show_date = d
                break

        day = days[show_date]
        preds = day.get("predictions", [])
        dt = datetime.strptime(show_date, "%Y-%m-%d")
        m, d_num = dt.month, dt.day
        wd = ["月","火","水","木","金","土","日"][dt.weekday()]

        html += f'<h3>{m}月{d_num}日({wd}) の予測 — {len(preds)}件分析済み</h3>'

        if preds:
            # 1件目は完全表示
            first = preds[0]
            avg = first.get("avg", 0)
            pred_min = max(1, round(avg * 0.6))
            pred_max = first.get("max", round(avg * 1.4))
            size = f'{first["size_min"]}〜{first["size_max"]}cm' if first.get("size_min") else "-"
            st = first.get("season_type", "")
            type_str = "数" if st == "数" else "型" if st == "型" else "数＆型" if st else "-"
            conf = first.get("confidence", "D")
            html += '<table class="pred-table"><thead><tr><th>魚種 × エリア</th><th>予測匹数</th><th>型</th><th>狙い</th><th>確信度</th></tr></thead><tbody>'
            html += f'<tr><td>{first["fish"]} × {first["group"]}</td><td>{pred_min}〜{pred_max}匹</td><td>{size}</td><td>{type_str}</td><td><span class="conf-badge conf-{conf}">{conf}</span></td></tr>'

            # 2〜5件はコンボ名ぼかし（匹数・型・確信度は見せる）
            for p in preds[1:5]:
                avg = p.get("avg", 0)
                pred_min = max(1, round(avg * 0.6))
                pred_max = p.get("max", round(avg * 1.4))
                size = f'{p["size_min"]}〜{p["size_max"]}cm' if p.get("size_min") else "-"
                st = p.get("season_type", "")
                type_str = "数" if st == "数" else "型" if st == "型" else "数＆型" if st else "-"
                conf = p.get("confidence", "D")
                html += f'<tr><td class="blur-text">■■■ × ■■■</td><td>{pred_min}〜{pred_max}匹</td><td>{size}</td><td>{type_str}</td><td><span class="conf-badge conf-{conf}">{conf}</span></td></tr>'
            html += '</tbody></table>'

            html += f"""<div class="paywall">
<a href="#" class="paywall-btn">全{len(preds)}件の予測を見る（月額500円）</a>
<p class="paywall-sub">スポット購入: 100円/日　|　1回の船代1万円。500円で判断材料を</p>
</div>"""

    # ── エリアから探す ──
    html += '<h2>📍 エリアから探す</h2>'
    html += '<div class="area-chips">'
    for group in AREA_FORECAST_COORDS:
        html += f'<a href="area/{area_slug(group)}.html" class="area-chip ok-good">{group}</a>'
    html += '</div>'

    html += _forecast_page_foot()
    return html


def build_forecast_pages(forecast_data, weather_data, catches=None, history=None):
    """有料予測ページ群を生成（forecast/ディレクトリ）"""
    if not forecast_data:
        return

    os.makedirs(os.path.join(WEB_DIR, "forecast"), exist_ok=True)
    os.makedirs(os.path.join(WEB_DIR, "forecast", "area"), exist_ok=True)
    page_count = 0

    # 日次ページ
    for date_str, day_data in forecast_data.get("days", {}).items():
        html = _build_daily_page(date_str, day_data, forecast_data, weather_data)
        with open(os.path.join(WEB_DIR, f"forecast/{date_str}.html"), "w", encoding="utf-8") as f:
            f.write(html)
        page_count += 1

    # 週次ページ
    for week_id, week_data in forecast_data.get("weeks", {}).items():
        html = _build_weekly_page(week_id, week_data, forecast_data)
        with open(os.path.join(WEB_DIR, f"forecast/{week_id}.html"), "w", encoding="utf-8") as f:
            f.write(html)
        page_count += 1

    # エリア別ページ
    for group in AREA_FORECAST_COORDS:
        html = _build_area_forecast_page(group, forecast_data)
        encoded = quote(group, safe="")
        with open(os.path.join(WEB_DIR, f"forecast/area/{encoded}.html"), "w", encoding="utf-8") as f:
            f.write(html)
        page_count += 1

    # ハブページ
    html = _build_forecast_hub(forecast_data, catches)
    with open(os.path.join(WEB_DIR, "forecast/index.html"), "w", encoding="utf-8") as f:
        f.write(html)
    page_count += 1

    print(f"forecast/: {page_count}ページ生成")


def build_forecast_section(forecast_data, weather_data):
    """海況予報 + 釣果予測のHTMLセクション（JS日付切替対応）"""
    if not forecast_data or not forecast_data.get("days"):
        return ""
    sat_date = weather_data.get("sat_date", "")
    sun_date = weather_data.get("sun_date", "")

    days = forecast_data["days"]
    all_dates = sorted(days.keys())

    # 日付ボタン
    date_btns = ""
    for i, d in enumerate(all_dates):
        m, dd = int(d[5:7]), int(d[8:10])
        wd_idx = datetime.strptime(d, "%Y-%m-%d").weekday()
        wd_names = ["月","火","水","木","金","土","日"]
        wd = wd_names[wd_idx]
        is_weekend = "weekend" if wd_idx >= 5 else ""
        active = " active" if d == sat_date or (sat_date not in [x for x in all_dates] and i == 0) else ""
        date_btns += f'<button class="fc-date-btn{active} {is_weekend}" data-date="{d}" onclick="switchForecastDate(this,\'{d}\')">{m}/{dd}({wd})</button>'

    # 日別データをJSONとしてscriptタグに埋め込み
    forecast_json = json.dumps(forecast_data["days"], ensure_ascii=False)

    # 初期表示用の日付
    init_date = sat_date if sat_date in days else all_dates[0]

    return f"""<h2>🔮 釣果予測</h2>
    <p style="font-size:12px;color:#7a9bb5;margin-bottom:10px">海況予報と過去2年の実績データから、指定日の釣果を予測</p>
    <div class="fc-date-bar">{date_btns}</div>
    <div id="forecast-content"></div>
    <script>
    var _fcData = {forecast_json};
    function switchForecastDate(btn, date) {{
      document.querySelectorAll('.fc-date-btn').forEach(b=>b.classList.remove('active'));
      btn.classList.add('active');
      renderForecast(date);
      if(typeof gtag==='function') gtag('event','forecast_date',{{date:date}});
    }}
    function renderForecast(date) {{
      var d = _fcData[date];
      if (!d) {{ document.getElementById('forecast-content').innerHTML='<p style="color:#7a9bb5">データなし</p>'; return; }}
      var h = '';
      // 海況サマリー
      var okColor = d.score>=80?'#4dcc88':d.score>=60?'#f4a261':d.score>=40?'#e85d04':'#cc4d4d';
      h += '<div class="fc-wx-summary">';
      h += '<span class="fc-ok" style="color:'+okColor+'">'+d.ok+'</span>';
      h += '<span class="fc-wx-val">🌊 '+(d.wave!=null?d.wave+'m':'-')+'</span>';
      h += '<span class="fc-wx-val">💨 '+(d.wind!=null?d.wind+'m/s':'-')+'</span>';
      h += '<span class="fc-wx-val">🌡️ '+(d.sst!=null?d.sst+'℃':'-')+'</span>';
      h += '</div>';
      // エリア別
      var areas = d.areas||{{}};
      var ak = Object.keys(areas);
      if (ak.length) {{
        h += '<div class="wx-grid">';
        ak.forEach(function(g){{
          var a = areas[g];
          var ac = a.score>=80?'#4dcc88':a.score>=60?'#f4a261':a.score>=40?'#e85d04':'#cc4d4d';
          h += '<div class="wx-card">';
          h += '<div class="wx-area">'+g+'</div>';
          h += '<div class="wx-ok" style="color:'+ac+'">'+a.ok+'</div>';
          h += '<div class="wx-detail">';
          h += '<div>🌊 '+(a.wave!=null?a.wave+'m':'-')+'</div>';
          h += '<div>💨 '+(a.wind!=null?a.wind+'m/s':'-')+'</div>';
          h += '<div>🌡️ '+(a.sst!=null?a.sst+'℃':'-')+'</div>';
          h += '</div></div>';
        }});
        h += '</div>';
      }}
      // 釣果予測
      var preds = d.predictions||[];
      if (preds.length) {{
        h += '<h3 style="font-size:14px;color:#4db8ff;margin:16px 0 8px;border-left:3px solid #4db8ff;padding-left:8px">🐟 この海況での予測釣果</h3>';
        h += '<div class="pred-grid">';
        preds.forEach(function(p,i){{
          var medal = i<3?['🥇','🥈','🥉'][i]:'';
          h += '<div class="pred-card">';
          h += '<div class="pred-fish">'+medal+' '+p.fish+'</div>';
          h += '<div class="pred-avg">平均 <strong>'+p.avg+'</strong> 匹</div>';
          h += '<div class="pred-max">最高 '+p.max+' 匹</div>';
          if(p.best_area) h += '<div class="pred-area">📍 '+p.best_area+' (平均'+p.best_avg+'匹)</div>';
          h += '<div class="pred-samples">過去'+p.samples+'件の実績</div>';
          h += '</div>';
        }});
        h += '</div>';
      }}
      document.getElementById('forecast-content').innerHTML = h;
    }}
    renderForecast('{init_date}');
    </script>"""

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
    "シロアマダイ": ["シロアマダイ"],
    "アマダイ": ["アカアマダイ", "アマダイ"],
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
    "シロアマダイ": {"size_cm": (20, 65),  "count": (0, 10),  "weight_kg": (0.1, 3.0)},
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
    '竹岡沖水深20～30m'          → ('竹岡沖', '20～30m')
    '水深15m'                    → (None, '15m')
    '竹岡沖'                     → ('竹岡沖', None)
    '秋谷沖～城ヶ島沖タナ57～100m' → ('秋谷沖～城ヶ島沖', '57～100m')
    '二海堡沖深30m'               → ('二海堡沖', '30m')
    '剣崎沖 70～100m'            → ('剣崎沖', '70～100m')
    """
    if not s:
        return None, None
    s = s.strip()
    # 「航程」「潮」はポイント情報であり水深ではない → そのままplaceとして返す
    if re.search(r'航程|潮', s):
        return s or None, None
    # 先頭が「水深」→ place なし
    m = re.match(r'^水深\s*(.+)', s)
    if m:
        return None, m.group(1).strip()
    # 途中に「水深」→ place + depth
    m = re.search(r'^(.+?)水深\s*(.+)', s)
    if m:
        return m.group(1).strip() or None, m.group(2).strip() or None
    # 途中に「タナ」→ place + depth
    m = re.search(r'^(.+?)タナ\s*(.+)', s)
    if m:
        return m.group(1).strip() or None, m.group(2).strip() or None
    # 途中に「深」(「水深」以外の単独「深」) → place + depth
    m = re.search(r'^(.+?)深\s*(\d[\d～〜~\-mM\s]*)', s)
    if m:
        return m.group(1).strip() or None, m.group(2).strip() or None
    # 末尾に「数字～数字m」or「数字m」→ place + depth（例: '剣崎沖 70～100m'）
    m = re.search(r'^(.+?)\s+(\d+[～〜~\-]\d+\s*[mM]?)$', s)
    if m:
        return m.group(1).strip() or None, m.group(2).strip() or None
    m = re.search(r'^(.+?)\s+(\d+\s*[mM])$', s)
    if m:
        return m.group(1).strip() or None, m.group(2).strip() or None
    # 全部 place
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

        # テーブルが空 → 休船テキストを検出
        if not catches:
            box_text = re.sub(r'<[^>]+>', ' ', box_html)
            box_text = ' '.join(box_text.split())
            # 日付部分を除去して本文だけ残す
            box_text = re.sub(r'\d{4}年\d{1,2}月\d{1,2}日[^\s]*', '', box_text).strip()
            if box_text and re.search(
                r'出船中止|欠航|定休|休業|出船なし|中止しました|休船|悪天|強風|荒天|予報悪|台風|波高|時化|シケ',
                box_text
            ):
                results.append({
                    "ship":            ship,
                    "area":            area,
                    "date":            date,
                    "month":           month,
                    "is_cancellation": True,
                    "reason_text":     box_text[:300],
                    "fish":            [],
                    "catch_raw":       "",
                    "count_range":     None,
                    "count_avg":       None,
                    "size_cm":         None,
                    "weight_kg":       None,
                    "point_place":     None,
                    "point_depth":     None,
                })

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
                "fish_raw":    fish_name,
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

        # 数量パターン: 魚名から100文字以内に N〜M 枚/匹/尾/本
        # 「マダイ 0.6キロ～1.5キロ 5～7枚」のように間に重さが入る形式にも対応
        p_range  = rf'{re.escape(fish_name)}.{{0,100}}?(\d+)\s*[〜~～]\s*(\d+)\s*[枚匹尾本杯]'
        p_single = rf'{re.escape(fish_name)}.{{0,100}}?(\d+)\s*[枚匹尾本杯]'

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


def parse_catches_gyo(html, ship, area, year, cutoff_days=60):
    """
    gyo.ne.jp 専用パーサー。
    日付が特定できない記録は全てスキップ（今日の日付のデフォルト使用禁止）。
    cutoff_days 日以内の日付のみ有効とする（デフォルト60日）。
    """
    results = []
    now     = datetime.now()
    cutoff  = now - timedelta(days=cutoff_days)

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

# ============================================================
# V2 ローダー: fish_tackle / area_description / decadal / area_decadal
# ============================================================
ANALYSIS_DB = os.path.join("analysis", "V2", "results", "analysis.sqlite")

def load_fish_tackle():
    """normalize/fish_tackle.json を {fish: {...}} で返す"""
    path = os.path.join("normalize", "fish_tackle.json")
    if not os.path.exists(path): return {}
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except: return {}

def load_area_description():
    """normalize/area_description.json を {area: {...}} で返す"""
    path = os.path.join("normalize", "area_description.json")
    if not os.path.exists(path): return {}
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except: return {}

def load_decadal_calendar():
    """analysis.sqlite の decadal_calendar を {fish: {decade_no: {cnt_index, size_index}}} で返す"""
    if not os.path.exists(ANALYSIS_DB): return {}
    import sqlite3
    result = {}
    try:
        con = sqlite3.connect(ANALYSIS_DB, timeout=10)
        con.row_factory = sqlite3.Row
        cur = con.cursor()
        cur.execute("SELECT fish, decade_no, avg_cnt_index, avg_size_index FROM decadal_calendar")
        for row in cur.fetchall():
            result.setdefault(row["fish"], {})[row["decade_no"]] = {
                "cnt_index":  row["avg_cnt_index"]  or 0,
                "size_index": row["avg_size_index"] or 0,
            }
        con.close()
    except Exception as e:
        print(f"load_decadal_calendar: {e}")
    return result

def load_area_decadal():
    """analysis.sqlite の area_decadal を {area: {fish: {decade_no: cnt_index}}} で返す"""
    if not os.path.exists(ANALYSIS_DB): return {}
    import sqlite3
    result = {}
    try:
        con = sqlite3.connect(ANALYSIS_DB, timeout=10)
        con.row_factory = sqlite3.Row
        cur = con.cursor()
        cur.execute("SELECT area, fish, decade_no, cnt_index FROM area_decadal")
        for row in cur.fetchall():
            result.setdefault(row["area"], {}).setdefault(row["fish"], {})[row["decade_no"]] = row["cnt_index"] or 0
        con.close()
    except Exception as e:
        print(f"load_area_decadal: {e}")
    return result

def load_fish_romaji():
    """normalize/fish_romaji_map.json → {日本語: slug}"""
    p = os.path.join("normalize", "fish_romaji_map.json")
    if not os.path.exists(p): return {}
    with open(p, encoding="utf-8") as f:
        return json.load(f)

def load_area_romaji():
    """normalize/area_romaji_map.json → {日本語: slug}"""
    p = os.path.join("normalize", "area_romaji_map.json")
    if not os.path.exists(p): return {}
    with open(p, encoding="utf-8") as f:
        return json.load(f)

# モジュールレベルで1回だけロード
_FISH_ROMAJI = load_fish_romaji()
_AREA_ROMAJI = load_area_romaji()

def fish_slug(fish: str) -> str:
    """魚種名 → URL用ローマ字スラグ（マップ未登録時はそのまま返す）"""
    return _FISH_ROMAJI.get(fish, fish)

def area_slug(area: str) -> str:
    """エリア名 → URL用ローマ字スラグ（マップ未登録時はそのまま返す）"""
    return _AREA_ROMAJI.get(area, area)

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
                if fish not in store[key]: store[key][fish] = {"ships": 0, "sum": 0, "cnt": 0, "max": 0, "szs": [], "wkgs": []}
                d = store[key][fish]
                d["ships"] += 1
                if not is_boat:  # 船中数は平均に含めない
                    d["sum"] += avg; d["cnt"] += 1
                if mx > d["max"]: d["max"] = mx
                if sz > 0: d["szs"].append(sz)
                wkg = c.get("weight_kg") or {}
                wkg_avg = (wkg.get("min", 0) + wkg.get("max", 0)) / 2 if wkg else 0
                if wkg_avg > 0: d["wkgs"].append(wkg_avg)
    for store, hist_key in [(temp_w, "weekly"), (temp_m, "monthly")]:
        for key, fish_data in store.items():
            history[hist_key][key] = {}
            for fish, d in fish_data.items():
                history[hist_key][key][fish] = {
                    "ships": d["ships"],
                    "avg":   round(d["sum"] / d["cnt"], 1) if d["cnt"] > 0 else 0,
                    "max":   d["max"],
                    "size_avg":   round(sum(d["szs"]) / len(d["szs"]), 1) if d["szs"] else 0,
                    "weight_avg": round(sum(d["wkgs"]) / len(d["wkgs"]), 2) if d["wkgs"] else 0,
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

def calc_weekend_prob(history, fish, year, week_num):
    """過去2年の同週±1週の実績から今週末の釣れる確率を算出（0〜100 or None）"""
    weekly = history.get("weekly", {})
    hits = 0
    total = 0
    for y in range(year - 2, year):
        for w in range(max(1, week_num - 1), min(53, week_num + 2)):
            key = f"{y}/W{w:02d}"
            d = weekly.get(key, {}).get(fish)
            if d is not None:
                total += 1
                if (d.get("ships") or 0) >= 3:
                    hits += 1
    if total == 0:
        return None
    return round(hits / total * 100)

def is_surge(history, fish, year, week_num):
    """先週比1.5倍以上かつ出船5隻以上なら爆釣アラート"""
    this_w, _ = get_yoy_data(history, fish, year, week_num)
    prev_w = get_prev_week_data(history, fish, year, week_num)
    if not (this_w and prev_w):
        return False
    this_s = this_w.get("ships") or 0
    prev_s = prev_w.get("ships") or 0
    return prev_s > 0 and this_s / prev_s >= 1.5 and this_s >= 5

def calc_season_entry(history, fish, year):
    """今年と昨年の初釣果週（ships>=3の最初の週番号）を返す"""
    weekly = history.get("weekly", {})
    def _first_week(y):
        for w in range(1, 53):
            d = weekly.get(f"{y}/W{w:02d}", {}).get(fish)
            if d and (d.get("ships") or 0) >= 3:
                return w
        return None
    return _first_week(year), _first_week(year - 1)

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
# V2 デザイン共通 CSS
# ============================================================
V2_COMMON_CSS = """:root{
  --bg:#f5f7fa;--card:#fff;--border:#d0d8e0;
  --text:#1a2332;--sub:#5a6a7a;--muted:#8a96a4;
  --accent:#0d2b4a;--cta:#e85d04;--cta2:#d04e00;
  --pos:#1a9d56;--neg:#d43333;--warn:#d4a017;--prem:#7c3aed;
  --hdr:#0d2b4a;--nav:#f0f3f7;--line:#06c755;
  --r:10px;--mx:900px;
}
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
body{font-family:system-ui,-apple-system,"Hiragino Sans",sans-serif;background:var(--bg);color:var(--text);line-height:1.6;padding-bottom:60px}
a{color:var(--cta);text-decoration:none}a:hover{text-decoration:underline}
.c{max-width:var(--mx);margin:0 auto;padding:0 14px}
header{background:var(--hdr);color:#fff;padding:12px 20px;border-bottom:3px solid var(--cta)}
header .inner{max-width:var(--mx);margin:0 auto;display:flex;justify-content:space-between;align-items:center}
header h1{font-size:19px;font-weight:700}header h1 span{color:var(--cta)}
header .domain{font-size:11px;opacity:.5}
nav.gnav{background:var(--nav);padding:7px 20px;display:flex;gap:6px;flex-wrap:wrap;justify-content:center;border-bottom:1px solid var(--border)}
nav.gnav a{color:var(--sub);font-size:12px;font-weight:600;padding:5px 12px;border-radius:16px}
nav.gnav a:hover,nav.gnav a.on{background:var(--accent);color:#fff;text-decoration:none}
nav.gnav a.prem{color:var(--prem)}
nav.gnav a.prem::before{content:"";display:inline-block;width:8px;height:8px;background:var(--prem);border-radius:50%;margin-right:4px;vertical-align:middle}
.st{font-size:15px;font-weight:700;color:var(--accent);padding:18px 0 8px;border-bottom:2px solid var(--accent);margin-bottom:12px;display:flex;align-items:center;gap:8px}
.st.teaser-title{color:var(--prem);border-color:var(--prem)}
.st .tag{font-size:9px;padding:2px 7px;border-radius:8px;color:#fff;font-weight:700}
.st .tag.free{background:var(--pos)}.st .tag.coming{background:var(--prem)}
.ad-slot{background:#f0f0f0;border:1px dashed #ccc;border-radius:var(--r);padding:22px;text-align:center;margin:16px 0;font-size:11px;color:#999}
.bread{font-size:11px;color:var(--muted);padding:10px 0}.bread a{color:var(--sub)}
.tbl-wrap{overflow-x:auto;-webkit-overflow-scrolling:touch}
table{width:100%;border-collapse:collapse;font-size:13px}
th{background:var(--accent);color:#fff;padding:8px;text-align:left;font-size:12px}
td{padding:8px;border-bottom:1px solid var(--border)}
tbody tr:hover td{background:#f0f4f8}
tr.highlight td{background:#e6f7ee}
tr.dim td{opacity:.45}
.stat-cards{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin:16px 0}
.stat-card{background:var(--card);border:1px solid var(--border);border-radius:var(--r);padding:12px;text-align:center}
.stat-card .sv{font-size:22px;font-weight:800;color:var(--cta);line-height:1.2}
.stat-card .sl{font-size:11px;color:var(--muted);margin-top:4px}
.bar-wrap{background:#e0e8f0;border-radius:2px;height:8px;width:80px}
.bar-fill{background:linear-gradient(90deg,var(--accent),#2c6ea8);height:8px;border-radius:2px}
.yoy-table .up{color:var(--pos)}.yoy-table .down{color:var(--neg)}
.data-note{max-width:var(--mx);margin:20px auto 0;padding:0 14px}
.data-note details{background:var(--card);border:1px solid var(--border);border-radius:var(--r);padding:10px 14px}
.data-note summary{color:var(--muted);font-size:12px;cursor:pointer;user-select:none}
.data-note ul{margin-top:8px;padding-left:16px;color:var(--sub);font-size:11px;line-height:1.9}
footer{background:var(--hdr);color:rgba(255,255,255,.6);padding:20px 14px;text-align:center;font-size:11px;margin-top:24px}
footer a{color:rgba(255,255,255,.8)}
footer .fl{margin-top:8px;display:flex;gap:10px;justify-content:center;flex-wrap:wrap}
footer .cp{margin-top:10px;display:block;opacity:.5}
.bn{position:fixed;bottom:0;left:0;right:0;background:var(--card);border-top:1px solid var(--border);display:flex;z-index:100;box-shadow:0 -2px 8px rgba(0,0,0,.06)}
.bn a{flex:1;text-align:center;padding:8px 0 6px;font-size:10px;color:var(--muted);display:flex;flex-direction:column;align-items:center;gap:2px;text-decoration:none;font-weight:600}
.bn a svg{width:22px;height:22px;stroke:var(--muted);stroke-width:1.8;fill:none;stroke-linecap:round;stroke-linejoin:round}
.bn a.on{color:var(--cta)}.bn a.on svg{stroke:var(--cta)}
.bn a:hover{color:var(--cta)}.bn a:hover svg{stroke:var(--cta)}
.bn a.prem.on{color:var(--prem)}.bn a.prem.on svg{stroke:var(--prem)}
.teaser{background:linear-gradient(135deg,#f8f4ff,#f0eafa);border:1.5px dashed var(--prem);border-radius:var(--r);padding:16px;margin-bottom:16px;position:relative;overflow:hidden}
.teaser-head{display:flex;align-items:center;gap:8px;margin-bottom:10px}
.teaser-badge{display:inline-block;font-size:10px;padding:3px 9px;background:var(--cta);color:#fff;border-radius:10px;font-weight:700;letter-spacing:.5px}
.teaser-badge.soon{background:var(--cta)}
.teaser-title-in{font-size:14px;font-weight:800;color:var(--prem)}
.teaser-desc{font-size:12px;color:var(--sub);margin-bottom:12px;line-height:1.7}
.teaser-desc strong{color:var(--accent)}
.teaser-dummy{background:var(--card);border:1px solid #e0d6f5;border-radius:8px;padding:12px;margin-bottom:8px;position:relative;filter:blur(1.5px);opacity:.75;pointer-events:none;user-select:none}
.teaser-dummy .td-fish{font-size:13px;font-weight:800;color:var(--accent)}
.teaser-dummy .td-star{color:var(--warn);font-size:11px;margin-left:4px}
.teaser-dummy .td-range{font-size:15px;font-weight:700;color:var(--cta);margin-top:3px}
.teaser-dummy .td-reason{font-size:10px;color:var(--sub);margin-top:4px}
.teaser-overlay{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;pointer-events:none}
.coming-soon-panel{background:rgba(124,58,237,.92);color:#fff;padding:14px 18px;border-radius:12px;font-size:12px;box-shadow:0 4px 16px rgba(124,58,237,.4);min-width:180px;text-align:left}
.cs-title{font-weight:800;font-size:13px;margin-bottom:8px;text-align:center;letter-spacing:.5px}
.cs-features{list-style:none;padding:0;margin:0 0 8px 0}
.cs-features li{padding:2px 0;font-size:11px;line-height:1.5}
.cs-price{text-align:center;font-size:10px;opacity:.85;border-top:1px solid rgba(255,255,255,.3);padding-top:6px;margin-top:2px}
.cs-price em{font-style:normal;font-weight:700}
.teaser-cta-wrap{background:var(--card);border:1px solid #e0d6f5;border-radius:8px;padding:12px;margin-top:10px;text-align:center}
.teaser-cta-msg{font-size:12px;color:var(--sub);margin-bottom:8px;line-height:1.5}
.teaser-cta-msg strong{color:var(--accent)}
.teaser-cta-btns{display:flex;gap:8px;justify-content:center;flex-wrap:wrap}
.cta-line{display:inline-flex;align-items:center;gap:6px;padding:10px 18px;background:var(--line);color:#fff;border-radius:22px;font-size:13px;font-weight:700;text-decoration:none}
.cta-line:hover{opacity:.9;text-decoration:none}
.cta-line .line-ic{width:16px;height:16px;background:#fff;color:var(--line);border-radius:4px;font-size:10px;font-weight:800;display:inline-flex;align-items:center;justify-content:center}
.teaser-price{font-size:10px;color:var(--muted);margin-top:8px}
.teaser-price em{color:var(--cta);font-style:normal;font-weight:700}
.teaser-rotator{background:linear-gradient(135deg,#f8f4ff,#f0eafa);border:1.5px dashed var(--prem);border-radius:var(--r);padding:16px;margin-bottom:16px}
.tr-track{overflow:hidden}
.tr-slide{display:none}
.tr-slide.is-active{display:block}
.tr-dots{display:flex;justify-content:center;gap:8px;margin-top:12px}
.tr-dot{width:8px;height:8px;border-radius:50%;background:#d4c4f5;border:none;cursor:pointer;padding:0;transition:background .2s}
.tr-dot.is-active{background:var(--prem)}
.season-map{background:var(--card);border:1px solid var(--border);border-radius:var(--r);padding:14px;margin-bottom:16px}
.season-map h3{font-size:13px;font-weight:700;color:var(--accent);margin-bottom:10px}
.sm-wrap{overflow-x:auto}
.sm-table{border-collapse:separate;border-spacing:3px;min-width:220px}
.sm-table th{font-size:10px;color:var(--muted);font-weight:600;text-align:center;padding:2px 4px}
.sm-th-mo{font-size:11px;font-weight:700;color:var(--sub);text-align:left;padding-right:8px;white-space:nowrap}
.sm-cell{width:40px;height:24px;border-radius:3px;font-size:9px;font-weight:700;text-align:center;vertical-align:middle}
.sm-cell[data-v="0"]{background:#eef2f5;color:var(--muted)}
.sm-cell[data-v="1"]{background:#c8e6c9;color:#2e7d32}
.sm-cell[data-v="2"]{background:#66bb6a;color:#fff}
.sm-cell[data-v="3"]{background:#388e3c;color:#fff}
.sm-cell[data-v="4"]{background:#1b5e20;color:#fff}
.sm-legend{display:flex;align-items:center;gap:6px;margin-top:8px;font-size:10px;color:var(--muted)}
.sm-lc{width:14px;height:14px;border-radius:2px;display:inline-block}
.area-season{background:var(--card);border:1px solid var(--border);border-radius:var(--r);padding:14px;margin-bottom:16px}
.as-wrap{overflow-x:auto}
.as-table{border-collapse:separate;border-spacing:3px;min-width:220px}
.as-table th{font-size:10px;color:var(--muted);font-weight:600;text-align:center;padding:2px 4px}
.as-th-fish{font-size:11px;font-weight:700;color:var(--sub);text-align:left;padding-right:8px;white-space:nowrap}
.as-cell{width:36px;height:22px;border-radius:3px;font-size:9px;font-weight:700;text-align:center;vertical-align:middle}
.as-cell[data-v="0"]{background:#eef2f5;color:var(--muted)}
.as-cell[data-v="1"]{background:#c8e6c9;color:#2e7d32}
.as-cell[data-v="2"]{background:#66bb6a;color:#fff}
.as-cell[data-v="3"]{background:#388e3c;color:#fff}
.as-cell[data-v="4"]{background:#1b5e20;color:#fff}
.as-legend{display:flex;align-items:center;gap:6px;margin-top:8px;font-size:10px;color:var(--muted)}
.as-lc{width:14px;height:14px;border-radius:2px;display:inline-block}
.fish-guide{background:var(--card);border:1px solid var(--border);border-radius:var(--r);padding:14px;margin-bottom:16px}
.fish-guide>h3{font-size:13px;font-weight:700;color:var(--accent);margin-bottom:12px}
.fg-row{display:flex;gap:10px;line-height:1.75;padding:7px 0;border-bottom:1px solid var(--bg)}
.fg-row:last-child{border-bottom:none}
.fg-lbl{flex:0 0 68px;font-size:10px;font-weight:700;color:var(--muted);letter-spacing:.4px;padding-top:3px}
.fg-val{flex:1;font-size:13px;color:var(--text)}
.fg-val .sub{font-size:11px;color:var(--sub)}
.tackle-grid{display:grid;grid-template-columns:1fr 1fr;gap:5px}
.tk{background:var(--bg);border-radius:6px;padding:6px 8px}
.tk-lbl{font-size:9px;font-weight:700;color:var(--muted);letter-spacing:.5px}
.tk-val{font-size:11px;color:var(--text);margin-top:1px;line-height:1.45}
.area-guide{background:var(--card);border:1px solid var(--border);border-radius:var(--r);padding:14px;margin-bottom:16px}
.area-guide>h3{font-size:13px;font-weight:700;color:var(--accent);margin-bottom:12px}
.ag-row{display:flex;gap:10px;line-height:1.75;padding:7px 0;border-bottom:1px solid var(--bg)}
.ag-row:last-child{border-bottom:none}
.ag-lbl{flex:0 0 68px;font-size:10px;font-weight:700;color:var(--muted);letter-spacing:.4px;padding-top:3px}
.ag-val{flex:1;font-size:13px;color:var(--text)}
.access-grid{display:grid;grid-template-columns:1fr 1fr;gap:5px}
.ac{background:var(--bg);border-radius:6px;padding:6px 8px}
.ac-lbl{font-size:9px;font-weight:700;color:var(--muted);letter-spacing:.5px}
.ac-val{font-size:11px;color:var(--text);margin-top:1px;line-height:1.45}
.faq-list{background:var(--card);border:1px solid var(--border);border-radius:var(--r);padding:14px;margin-bottom:16px}
.faq-list>h3{font-size:13px;font-weight:700;color:var(--accent);margin-bottom:10px}
.faq-list details{border-bottom:1px solid var(--bg)}
.faq-list details:last-child{border-bottom:none}
.faq-list summary{font-size:13px;font-weight:600;color:var(--accent);padding:11px 0;cursor:pointer;list-style:none;display:flex;justify-content:space-between;gap:8px}
.faq-list summary::-webkit-details-marker{display:none}
.faq-list summary::after{content:"+";font-size:16px;color:var(--muted);flex-shrink:0;line-height:1}
.faq-list details[open]>summary::after{content:"−"}
.faq-ans{font-size:12px;color:var(--sub);line-height:1.75;padding-bottom:12px}
.overview{background:var(--card);border:1px solid var(--border);border-radius:var(--r);padding:14px;margin-bottom:16px}
.overview-title{font-size:11px;font-weight:700;color:var(--sub);margin-bottom:6px}
.overview-body{font-size:13px;color:var(--text);line-height:1.8}
@media(min-width:769px){.bn{display:none}body{padding-bottom:0}}
@media(max-width:640px){header{padding:10px 14px}.stat-cards{grid-template-columns:1fr 1fr}table{font-size:11px}th,td{padding:5px 4px}.bar-wrap{width:50px}}"""

# ============================================================
# V2 ビルダー関数
# ============================================================

def _v2_header_nav(active_page=""):
    """V2共通ヘッダー + グローバルナビ"""
    pages = [
        ("今日の釣果", "index.html", ""),
        ("魚種",       "fish/",      ""),
        ("エリア",     "area/",      ""),
        ("カレンダー", "calendar/index.html", ""),
        ("有料プラン", "premium/index.html",  "prem"),
    ]
    links = ""
    for label, href, cls in pages:
        on = " on" if active_page in href or active_page == label else ""
        links += f'<a href="/{href}" class="{cls}{on}".strip()>{label}</a>'
    return f"""<header>
  <div class="inner">
    <h1>船釣り<span>予想</span></h1>
    <span class="domain">funatsuri-yoso.com</span>
  </div>
</header>
<nav class="gnav">
  <a href="/index.html"{' class="on"' if active_page == 'index' else ''}>今日の釣果</a>
  <a href="/fish/"{' class="on"' if active_page == 'fish' else ''}>魚種</a>
  <a href="/area/"{' class="on"' if active_page == 'area' else ''}>エリア</a>
  <a href="/calendar.html"{' class="on"' if active_page == 'calendar' else ''}>カレンダー</a>
  <a href="/forecast/index.html" class="prem{' on' if active_page == 'forecast' else ''}">有料プラン</a>
</nav>"""

def _v2_footer(crawled_at=""):
    return f"""<footer>
  <div>© 2026 船釣り予想 (funatsuri-yoso.com)</div>
  <div class="fl">
    <a href="/pages/about.html">サイトについて</a>
    <a href="/pages/privacy.html">プライバシーポリシー</a>
    <a href="/pages/terms.html">利用規約</a>
    <a href="/pages/contact.html">お問い合わせ</a>
  </div>
  <span class="cp">データ提供: 釣りビジョン / 各船宿{' | 最終更新: ' + crawled_at if crawled_at else ''}</span>
</footer>"""

def _v2_bottom_nav(active_page=""):
    icons = {
        "index": '<svg viewBox="0 0 24 24"><path d="M2 12c3-5 8-7 13-5 2 1 4 3 5 5-1 2-3 4-5 5-5 2-10 0-13-5z"/><circle cx="16" cy="11" r=".8" fill="currentColor" stroke="none"/><path d="M20 12l2-2M20 12l2 2"/></svg>',
        "fish":  '<svg viewBox="0 0 24 24"><line x1="4" y1="7" x2="20" y2="7"/><line x1="4" y1="12" x2="20" y2="12"/><line x1="4" y1="17" x2="20" y2="17"/><circle cx="4" cy="7" r="1" fill="currentColor" stroke="none"/><circle cx="4" cy="12" r="1" fill="currentColor" stroke="none"/><circle cx="4" cy="17" r="1" fill="currentColor" stroke="none"/></svg>',
        "area":  '<svg viewBox="0 0 24 24"><path d="M12 2c-4 0-7 3-7 7 0 5 7 13 7 13s7-8 7-13c0-4-3-7-7-7z"/><circle cx="12" cy="9" r="2.5"/></svg>',
        "cal":   '<svg viewBox="0 0 24 24"><rect x="4" y="5" width="16" height="16" rx="2"/><line x1="4" y1="10" x2="20" y2="10"/><line x1="9" y1="3" x2="9" y2="7"/><line x1="15" y1="3" x2="15" y2="7"/></svg>',
        "prem":  '<svg viewBox="0 0 24 24"><path d="M3 8l4 4 5-7 5 7 4-4v11H3z"/><line x1="3" y1="19" x2="21" y2="19"/></svg>',
    }
    items = [
        ("index", "/index.html", "釣果", ""),
        ("fish",  "/fish/",      "魚種", ""),
        ("area",  "/area/",      "エリア", ""),
        ("cal",   "/calendar.html",        "カレンダー", ""),
        ("prem",  "/forecast/index.html", "有料", "prem"),
    ]
    nav = '<nav class="bn">'
    for key, href, label, cls in items:
        on = " on" if active_page == key else ""
        cls_attr = f'{cls}{on}'.strip()
        nav += f'<a href="{href}"{" class=" + chr(34) + cls_attr + chr(34) if cls_attr else ""}>{icons[key]}{label}</a>'
    nav += '</nav>'
    return nav

def build_teaser_rotator_html():
    """有料機能プレビュー ローテーターパネル（index.html用）"""
    return """<h2 class="st teaser-title">有料機能プレビュー <span class="tag coming">まもなく公開</span></h2>
<div class="teaser-rotator">
  <div class="tr-track">
    <div class="tr-slide is-active">
      <div class="teaser-head">
        <span class="teaser-badge soon">開発中</span>
        <span class="teaser-title-in">今週の狙い目 — 週末TOP5魚種</span>
      </div>
      <div class="teaser-desc">約10万件の釣果データ×気象×潮汐をAI分析。<strong>今週末の狙い目魚種・エリア</strong>をランキング表示。</div>
      <div style="position:relative">
        <div class="teaser-dummy"><div class="td-fish">アジ <span class="td-star">★★★★★</span></div><div class="td-range">25〜45匹 / 18〜25cm</div><div class="td-reason">大潮×水温上昇×波穏やか。金沢八景推奨</div></div>
        <div class="teaser-dummy"><div class="td-fish">マダイ <span class="td-star">★★★★☆</span></div><div class="td-range">0〜5匹 / 30〜55cm</div><div class="td-reason">中潮×SST適温。剣崎・久里浜が狙い目</div></div>
        <div class="teaser-overlay"><div class="coming-soon-panel"><div class="cs-title">🔒 準備中</div><ul class="cs-features"><li>✓ 今週 日毎の釣果予測</li><li>✓ 2・3・4週先の釣果予測</li><li>✓ 気象×潮汐で自動算出</li></ul><div class="cs-price">月額<em>500円</em> / 1回<em>100円</em></div></div></div>
      </div>
    </div>
    <div class="tr-slide">
      <div class="teaser-head">
        <span class="teaser-badge soon">開発中</span>
        <span class="teaser-title-in">予測の答え合わせ — 予測 vs 実績</span>
      </div>
      <div class="teaser-desc"><strong>前日の予測</strong>が実際の釣果と一致したかを毎日公開。「なぜ当たった・外れたか」を正直レポート。</div>
      <div style="position:relative">
        <div class="teaser-dummy"><div class="td-fish">アジ <span style="color:var(--pos);font-size:10px;margin-left:6px">的中</span></div><div class="td-range">予想 25〜42匹 → 実績 20〜48匹</div><div class="td-reason">水温○ / 風速○ / 波高○ 予報通りで好条件持続</div></div>
        <div class="teaser-dummy"><div class="td-fish">マダイ <span style="color:var(--neg);font-size:10px;margin-left:6px">ハズレ</span></div><div class="td-range">予想 2〜8匹 → 実績 0〜3匹</div><div class="td-reason">水温× 予報より1.5℃低下で活性低下</div></div>
        <div class="teaser-overlay"><div class="coming-soon-panel"><div class="cs-title">🔒 準備中</div><ul class="cs-features"><li>✓ 先週の予測 vs 実績比較</li><li>✓ 予測精度スコア</li><li>✓ 外れた理由の解説</li></ul><div class="cs-price">月額<em>500円</em> / 1回<em>100円</em></div></div></div>
      </div>
    </div>
    <div class="tr-slide">
      <div class="teaser-head">
        <span class="teaser-badge soon">開発中</span>
        <span class="teaser-title-in">分析・予測 — 注目コンボ・急落コンボ</span>
      </div>
      <div class="teaser-desc"><strong>魚種×エリアの組合せ</strong>を独自スコアリング。「来週のどの日に何が釣れるか」を日別で予測。</div>
      <div style="position:relative">
        <div class="teaser-dummy"><div class="td-fish">注目: アジ × 金沢八景</div><div class="td-range">スコア 92 / 平年比 +38%</div><div class="td-reason">大潮×SST18.5℃×波0.8m でベスト条件</div></div>
        <div class="teaser-dummy"><div class="td-fish">急落: タチウオ × 走水</div><div class="td-range">先週比 -45%</div><div class="td-reason">水温急低下でベイトが抜けた模様</div></div>
        <div class="teaser-overlay"><div class="coming-soon-panel"><div class="cs-title">🔒 準備中</div><ul class="cs-features"><li>✓ 日別釣果予測（7日先）</li><li>✓ 気象相関グラフ</li><li>✓ 急上昇・急落コンボ通知</li></ul><div class="cs-price">月額<em>500円</em> / 1回<em>100円</em></div></div></div>
      </div>
    </div>
  </div>
  <div class="tr-dots">
    <button class="tr-dot is-active" aria-label="スライド1"></button>
    <button class="tr-dot" aria-label="スライド2"></button>
    <button class="tr-dot" aria-label="スライド3"></button>
  </div>
  <div class="teaser-cta-wrap">
    <div class="teaser-cta-msg">公開時に<strong>LINEでお知らせ</strong>します。友だち追加してお待ちください。</div>
    <div class="teaser-cta-btns"><a class="cta-line" href="#line-pending"><span class="line-ic">L</span>LINEで通知を受け取る</a></div>
    <div class="teaser-price">※ 全機能まとめて <em>月額500円</em> / スポット <em>1回100円</em></div>
  </div>
</div>"""

def build_index_overview_text(catches, history, crawled_at=""):
    """今日の関東船釣り概況テキスト（200〜300字）を生成"""
    now = datetime.now()
    today_str = now.strftime("%Y/%m/%d")
    year, week_num = current_iso_week()
    # 今日分のみで集計
    today_catches = [c for c in catches if c.get("date") == today_str]
    base = today_catches if today_catches else catches  # 今日データなければ全件フォールバック
    label = "本日" if today_catches else "直近"
    total = len(base)
    areas_set = set(c["area"] for c in base)
    ships_set = set(c["ship"] for c in base)
    # 主力魚種 TOP3（今日 or 全件）
    fish_counts: dict = {}
    for c in base:
        for f in c["fish"]:
            if f != "不明": fish_counts[f] = fish_counts.get(f, 0) + 1
    top_fish = sorted(fish_counts.items(), key=lambda x: -x[1])[:3]
    top_names = "・".join(f for f, _ in top_fish)
    # 昨年比（TOP魚種・週次データなので全件から）
    yoy_text = ""
    if top_fish:
        f1 = top_fish[0][0]
        this_w, last_w = get_yoy_data(history, f1, year, week_num)
        if this_w and last_w and last_w.get("ships"):
            pct = round((this_w.get("ships", 0) - last_w["ships"]) / last_w["ships"] * 100)
            if pct > 0:   yoy_text = f"先週比+{pct}%と上昇傾向が続いています。"
            elif pct < 0: yoy_text = f"先週比{pct}%とやや低調です。"
            else:          yoy_text = "先週並みの釣果が続いています。"
    # 組み合わせ文
    body = (
        f"{label}の関東全域で{total}件の釣果報告が寄せられました（{len(areas_set)}エリア・{len(ships_set)}船宿）。"
        f"主力魚種は{top_names}。"
    )
    if top_fish and yoy_text:
        f1 = top_fish[0][0]
        top_areas = list(dict.fromkeys(c["area"] for c in base if f1 in c["fish"]))[:2]
        area_str = "・".join(top_areas) if top_areas else "各エリア"
        body += f"{f1}は{area_str}を中心に{yoy_text}"
    body += "最新の釣果情報・船宿ランキングは各魚種・エリアページをご確認ください。"
    title_str = crawled_at + " 更新" if crawled_at else now.strftime("%Y/%m/%d") + " 更新"
    return (
        f'<h2 class="st">今日の関東船釣り概況 <span class="tag free">無料</span></h2>'
        f'<div class="overview">'
        f'<div class="overview-title">{title_str} — {len(areas_set)}エリア・{len(ships_set)}船宿から集計</div>'
        f'<div class="overview-body">{body}</div>'
        f'</div>'
    )

def _decadal_to_monthly_index(fish_decades: dict) -> list:
    """36旬のcnt_indexを12か月平均に変換して返す（0〜4スケール）"""
    monthly = []
    for m in range(1, 13):
        d1 = (m - 1) * 3 + 1
        d2 = d1 + 1
        d3 = d1 + 2
        vals = [fish_decades.get(d, {}).get("cnt_index", 100) for d in (d1, d2, d3)]
        avg = sum(vals) / len(vals)
        # 100を中央値として0〜4スケール
        if avg >= 160:   lv = 4
        elif avg >= 130: lv = 3
        elif avg >= 90:  lv = 2
        elif avg >= 50:  lv = 1
        else:            lv = 0
        monthly.append(lv)
    return monthly

def _decadal_to_monthly_size_index(fish_decades: dict) -> list:
    """36旬のsize_indexを12か月平均に変換して返す（0〜4スケール）"""
    monthly = []
    for m in range(1, 13):
        d1 = (m - 1) * 3 + 1
        d2 = d1 + 1
        d3 = d1 + 2
        vals = [fish_decades.get(d, {}).get("size_index", 100) for d in (d1, d2, d3)]
        avg = sum(vals) / len(vals)
        if avg >= 110:   lv = 4
        elif avg >= 103: lv = 3
        elif avg >= 97:  lv = 2
        elif avg >= 90:  lv = 1
        else:            lv = 0
        monthly.append(lv)
    return monthly

def build_fish_season_map_html(fish, decadal_calendar):
    """魚種の旬カレンダー（12か月×数釣/型釣 ヒートマップ）"""
    fish_decades = decadal_calendar.get(fish, {})
    cnt_levels   = _decadal_to_monthly_index(fish_decades)
    size_levels  = _decadal_to_monthly_size_index(fish_decades)
    month_labels = ["1月","2月","3月","4月","5月","6月","7月","8月","9月","10月","11月","12月"]
    ths = "".join(f"<th>{m}</th>" for m in month_labels)
    cnt_cells  = "".join(f'<td class="sm-cell" data-v="{lv}"></td>' for lv in cnt_levels)
    size_cells = "".join(f'<td class="sm-cell" data-v="{lv}"></td>' for lv in size_levels)
    note = "" if fish_decades else f'<p style="font-size:11px;color:var(--muted)">※ {fish}のデータが不足しています</p>'
    return f"""<div class="season-map">
  <div class="sm-wrap">
    <table class="sm-table">
      <thead><tr><th style="width:28px"></th>{ths}</tr></thead>
      <tbody>
        <tr><th class="sm-th-mo">数釣</th>{cnt_cells}</tr>
        <tr><th class="sm-th-mo">型釣</th>{size_cells}</tr>
      </tbody>
    </table>
  </div>
  <div class="sm-legend">
    <span>釣れ具合：</span>
    <span class="sm-lc" style="background:#eef2f5"></span>なし
    <span class="sm-lc" style="background:#c8e6c9"></span>渋
    <span class="sm-lc" style="background:#66bb6a"></span>普通
    <span class="sm-lc" style="background:#388e3c"></span>良
    <span class="sm-lc" style="background:#1b5e20"></span>◎
  </div>
  <p style="font-size:11px;color:var(--muted);margin-top:6px">※ 過去3年の関東船釣り釣果データより集計（2023〜2025年）</p>
  <div style="margin-top:8px;padding:8px 10px;background:#f8f4ff;border:1px dashed var(--prem);border-radius:6px;font-size:11px;color:var(--prem);font-weight:600">
    🔒 上旬/中旬/下旬の旬別詳細データは有料プランで公開予定
  </div>
  {note}
</div>"""

def build_area_season_map_html(area, area_decadal, top_fish_list):
    """エリアの魚種別旬カレンダー（魚種×12か月 ヒートマップ）"""
    area_data = area_decadal.get(area, {})
    month_labels = ["1","2","3","4","5","6","7","8","9","10","11","12"]
    ths = "".join(f"<th>{m}</th>" for m in month_labels)
    rows = ""
    for fish in top_fish_list[:6]:
        fish_decades = area_data.get(fish, {})
        # area_decadal は cnt_index のみ
        cnt_levels = []
        for m in range(1, 13):
            d1 = (m - 1) * 3 + 1
            d2 = d1 + 1
            d3 = d1 + 2
            vals = [fish_decades.get(d, 100) for d in (d1, d2, d3)]
            avg = sum(vals) / 3
            if avg >= 160:   lv = 4
            elif avg >= 130: lv = 3
            elif avg >= 90:  lv = 2
            elif avg >= 50:  lv = 1
            else:            lv = 0
            cnt_levels.append(lv)
        cells = "".join(f'<td class="as-cell" data-v="{lv}"></td>' for lv in cnt_levels)
        rows += f'<tr><th class="as-th-fish">{fish}</th>{cells}</tr>\n'
    if not rows:
        return ""
    return f"""<div class="area-season">
  <div class="as-wrap">
    <table class="as-table">
      <thead><tr><th class="as-th-fish"></th>{ths}</tr></thead>
      <tbody>{rows}</tbody>
    </table>
  </div>
  <div class="as-legend">
    <span>釣れ具合：</span>
    <span class="as-lc" style="background:#eef2f5"></span>なし
    <span class="as-lc" style="background:#c8e6c9"></span>渋
    <span class="as-lc" style="background:#66bb6a"></span>普通
    <span class="as-lc" style="background:#388e3c"></span>良
    <span class="as-lc" style="background:#1b5e20"></span>◎
  </div>
  <p style="font-size:11px;color:var(--muted);margin-top:6px">※ 過去3年の釣果データより集計（2023〜2025年）</p>
</div>"""

def build_fish_guide_html(fish, tackle_data):
    """魚種ガイドセクション（釣り方・タックル・サイズ・外道・出船率）"""
    td = tackle_data.get(fish) if tackle_data else None
    if not td:
        return ""
    method = td.get("method_detail") or td.get("method_name") or ""
    size_info = td.get("size_typical", {})
    if isinstance(size_info, dict):
        size_text = size_info.get("text", "")
    else:
        size_text = str(size_info)
    bycatch = td.get("bycatch") or []
    bycatch_text = "・".join(bycatch) if bycatch else ""
    notes = td.get("notes") or ""
    # タックル表示
    tackle = td.get("tackle") or {}
    tackle_html = ""
    if isinstance(tackle, dict):
        # タックルが複数釣法に分かれている場合は最初の一つだけ表示
        first_key = next(iter(tackle), None)
        if first_key:
            t = tackle[first_key]
            if isinstance(t, dict):
                rod   = t.get("rod", "")
                reel  = t.get("reel", "")
                line  = t.get("line", "")
                rig   = t.get("rig", "")
                bait  = t.get("bait", "")
                tackle_html = f"""<div class="tackle-grid">
          <div class="tk"><div class="tk-lbl">竿</div><div class="tk-val">{rod}</div></div>
          <div class="tk"><div class="tk-lbl">リール</div><div class="tk-val">{reel}</div></div>
          <div class="tk"><div class="tk-lbl">ライン</div><div class="tk-val">{line}</div></div>
          <div class="tk"><div class="tk-lbl">仕掛け</div><div class="tk-val">{rig}</div></div>
          <div class="tk" style="grid-column:span 2"><div class="tk-lbl">エサ</div><div class="tk-val">{bait}</div></div>
        </div>"""
    rows = ""
    if method:
        rows += f'<div class="fg-row"><span class="fg-lbl">釣り方</span><span class="fg-val">{method}</span></div>'
    if tackle_html:
        rows += f'<div class="fg-row"><span class="fg-lbl">タックル</span><span class="fg-val">{tackle_html}</span></div>'
    if size_text:
        rows += f'<div class="fg-row"><span class="fg-lbl">サイズ目安</span><span class="fg-val"><strong>{size_text}</strong></span></div>'
    if bycatch_text:
        rows += f'<div class="fg-row"><span class="fg-lbl">外道</span><span class="fg-val">{bycatch_text}</span></div>'
    if notes:
        rows += f'<div class="fg-row"><span class="fg-lbl">メモ</span><span class="fg-val">{notes}</span></div>'
    if not rows:
        return ""
    return f"""<div class="fish-guide">
  <h3>{fish}の船釣り（関東）基本情報</h3>
  {rows}
</div>"""

def build_fish_7day_chart_html(fish, catches):
    """直近7日間の釣果推移バーチャート（匹数上限）"""
    from datetime import datetime, timedelta
    today = datetime.now().date()
    days = [(today - timedelta(days=i)) for i in range(6, -1, -1)]  # 6日前〜今日
    # 日付→最大釣果
    daily_max = {}
    for c in catches:
        try:
            d = datetime.strptime(c["date"], "%Y/%m/%d").date()
        except Exception:
            continue
        if d not in daily_max:
            daily_max[d] = 0
        cr = c.get("count_range")
        cnt = (cr["max"] if cr and not cr.get("is_boat") else 0) or 0
        if cnt and cnt > daily_max[d]:
            daily_max[d] = cnt
    values = [daily_max.get(d, 0) for d in days]
    week_max = max(values) if any(v > 0 for v in values) else 1
    # データが全部0なら非表示
    if week_max == 0:
        return ""
    # 棒の高さ・クラス
    bars = []
    for i, (d, v) in enumerate(zip(days, values)):
        h = max(8, int(v / week_max * 100)) if v > 0 else 4
        cls = "cb today" if d == today else ("cb weekend" if d.weekday() >= 5 else "cb")
        bars.append(f'<div class="{cls}" style="height:{h}%"></div>')
    # ラベル
    labels = []
    for d in days:
        if d == today:
            labels.append("<span>今日</span>")
        else:
            labels.append(f"<span>{d.month}/{d.day}</span>")
    # トレンド（後半3日 vs 前半4日の平均比較）
    first4 = [v for v in values[:4] if v > 0]
    last3  = [v for v in values[4:] if v > 0]
    trend = ""
    if first4 and last3:
        avg_first = sum(first4) / len(first4)
        avg_last  = sum(last3) / len(last3)
        if avg_last > avg_first * 1.1:
            trend = '<div class="chart-trend">↑ 上昇トレンド</div>'
        elif avg_last < avg_first * 0.9:
            trend = '<div class="chart-trend down">↓ 下降トレンド</div>'
        else:
            trend = '<div class="chart-trend flat">→ 横ばい</div>'
    return f"""<h2 class="st">直近7日間の釣果推移 <span class="tag free">無料</span></h2>
<div class="chart7">
  <h3>匹数上限（上ヒゲ）の7日推移</h3>
  <div class="chart-bars">{''.join(bars)}</div>
  <div class="chart-labels">{''.join(labels)}</div>
  {trend}
</div>"""

def build_fish_faq_html(fish, site_url=""):
    """魚種別FAQ（デフォルト質問セット）＋ FAQPage JSON-LD を返す (html, jsonld) のタプル"""
    faqs = [
        (f"{fish}の船釣りはどの季節が一番釣れますか？",
         f"関東の{fish}船釣りの旬はエリアや年度によって異なります。このページの旬カレンダーで月別の釣れ具合をご確認ください。"),
        (f"初心者でも{fish}釣りは楽しめますか？",
         f"はい。{fish}は比較的タックルがシンプルで、船宿スタッフのサポートも受けられます。竿・リールのレンタルができる船宿も多くあります。"),
        (f"関東で{fish}の船釣りができる主なエリアはどこですか？",
         f"神奈川・東京湾エリアをはじめ、千葉・外房、茨城など幅広いエリアで船が出ています。エリア別釣果ページで各エリアの状況をご確認ください。"),
        (f"{fish}の船で一日どれくらい釣れますか？",
         f"釣果は日・潮回り・季節によって大きく変動します。このページの最新釣果テーブルで実績をご確認ください。"),
        (f"{fish}釣りに必要なタックルは何ですか？",
         f"竿・リール・仕掛けのセットが必要です。詳細はこのページの「魚種ガイド」セクションをご覧ください。"),
    ]
    html = '<div class="faq-list">\n'
    for q, a in faqs:
        html += f'  <details><summary>{q}</summary><p class="faq-ans">{a}</p></details>\n'
    html += '</div>'
    jsonld_items = ",\n".join(
        f'{{"@type":"Question","name":{json.dumps(q, ensure_ascii=False)},"acceptedAnswer":{{"@type":"Answer","text":{json.dumps(a, ensure_ascii=False)}}}}}'
        for q, a in faqs
    )
    jsonld = f'<script type="application/ld+json">{{"@context":"https://schema.org","@type":"FAQPage","mainEntity":[{jsonld_items}]}}</script>'
    return html, jsonld

def build_area_guide_html(area, desc_data):
    """エリアガイドセクション（アクセス・特徴・主要ポイント・船宿系統・出船率）"""
    ad = desc_data.get(area) if desc_data else None
    if not ad:
        return ""
    rows = ""
    if ad.get("feature"):
        rows += f'<div class="ag-row"><span class="ag-lbl">エリア特徴</span><span class="ag-val">{ad["feature"]}</span></div>'
    train = ad.get("access_train", "")
    car   = ad.get("access_car", "")
    if train or car:
        ac_cells = ""
        if train: ac_cells += f'<div class="ac"><div class="ac-lbl">電車</div><div class="ac-val">{train}</div></div>'
        if car:   ac_cells += f'<div class="ac"><div class="ac-lbl">車</div><div class="ac-val">{car}</div></div>'
        rows += f'<div class="ag-row"><span class="ag-lbl">アクセス</span><span class="ag-val"><div class="access-grid">{ac_cells}</div></span></div>'
    if ad.get("key_points"):
        rows += f'<div class="ag-row"><span class="ag-lbl">主要ポイント</span><span class="ag-val">{ad["key_points"]}</span></div>'
    if ad.get("key_ships"):
        rows += f'<div class="ag-row"><span class="ag-lbl">主力船宿</span><span class="ag-val">{ad["key_ships"]}</span></div>'
    if ad.get("departure_rate"):
        rows += f'<div class="ag-row"><span class="ag-lbl">出船率</span><span class="ag-val">{ad["departure_rate"]}</span></div>'
    if not rows:
        return ""
    pref = ad.get("prefecture", "")
    title_sub = f"（{pref}）" if pref else ""
    return f"""<div class="area-guide">
  <h3>{area}{title_sub}</h3>
  {rows}
</div>"""

def build_area_faq_html(area, desc_data, area_coords=None):
    """エリア別FAQ＋ FAQPage+Place JSON-LD を返す (html, jsonld) のタプル"""
    ad = (desc_data.get(area) or {}) if desc_data else {}
    top_fish_str = ad.get("top_fish_text", "複数の魚種")
    faqs = [
        (f"{area}で釣れる魚は何ですか？",
         f"{top_fish_str}が主力です。季節によって釣れる魚が変わります。旬カレンダーで月別の状況をご確認ください。"),
        (f"{area}エリアへのアクセス方法は？",
         ad.get("access_summary") or f"{area}への詳細なアクセスは各船宿のウェブサイトをご確認ください。"),
        (f"{area}は初心者向けですか？",
         f"はい。タックルレンタルや仕掛け販売が充実した船宿があります。船宿スタッフのサポートも受けられるため初心者の方も安心して楽しめます。"),
        (f"{area}でおすすめの時期はいつですか？",
         f"魚種によって旬が異なります。このページの旬カレンダーで各魚種の月別釣れ具合をご確認ください。"),
        (f"{area}の主要な釣りポイントはどこですか？",
         ad.get("key_points") or f"{area}の主要ポイントは各船宿のページでご確認ください。"),
    ]
    html = '<div class="faq-list">\n'
    for q, a in faqs:
        html += f'  <details><summary>{q}</summary><p class="faq-ans">{a}</p></details>\n'
    html += '</div>'
    # JSON-LD: FAQPage + Place
    faq_items = ",\n".join(
        f'{{"@type":"Question","name":{json.dumps(q, ensure_ascii=False)},"acceptedAnswer":{{"@type":"Answer","text":{json.dumps(a, ensure_ascii=False)}}}}}'
        for q, a in faqs
    )
    place_json = ""
    if area_coords and area in area_coords:
        lat = area_coords[area].get("lat")
        lon = area_coords[area].get("lon")
        if lat and lon:
            place_json = f',{{"@context":"https://schema.org","@type":"Place","name":{json.dumps(area, ensure_ascii=False)},"geo":{{"@type":"GeoCoordinates","latitude":{lat},"longitude":{lon}}}}}'
    jsonld = f'<script type="application/ld+json">[{{"@context":"https://schema.org","@type":"FAQPage","mainEntity":[{faq_items}]}}{place_json}]</script>'
    return html, jsonld

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
    suffix = f"（釣果{count}件"
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
.fc.stale{opacity:0.55;border-color:#1a3050}
.fc-stale{font-size:10px;color:#e85d04;margin-top:6px}
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
.prob-wrap{display:flex;align-items:center;gap:6px;margin:8px 0;font-size:12px}
.prob-bar-bg{flex:1;max-width:120px;height:6px;background:#0a1628;border-radius:3px}
.prob-bar-fill{height:6px;border-radius:3px}
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
.surge-badge{font-size:11px;color:#e85d04;font-weight:bold;padding:2px 6px;background:#2a1000;border-radius:4px;border:1px solid #e85d04}
.fc-prob{display:flex;align-items:center;gap:5px;font-size:11px;margin-top:5px}
.prob-label{color:#7a9bb5;white-space:nowrap}
.prob-bar-bg{width:60px;height:5px;background:#081020;border-radius:3px}
.prob-bar-fill{height:5px;border-radius:3px}
.prob-pct{font-weight:bold}
.prob-wrap{display:flex;align-items:center;gap:6px;margin:8px 0;font-size:12px}
.fc-date-bar{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:12px}
.fc-date-btn{background:#081020;border:1px solid #1a4060;color:#7a9bb5;padding:6px 12px;border-radius:16px;cursor:pointer;font-size:12px;transition:all .2s}
.fc-date-btn:hover{border-color:#4db8ff;color:#4db8ff}
.fc-date-btn.active{background:#1a6ea8;color:#fff;border-color:#1a6ea8}
.fc-date-btn.weekend{border-color:#e85d04}
.fc-date-btn.weekend.active{background:#e85d04}
.fc-wx-summary{display:flex;gap:12px;align-items:center;flex-wrap:wrap;padding:10px 14px;background:#0d2137;border-radius:8px;margin-bottom:12px}
.fc-ok{font-size:15px;font-weight:bold}
.fc-wx-val{font-size:13px;color:#c8d8e8}
.pred-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:10px}
.pred-card{background:#0d2137;border:1px solid #1a4060;border-radius:8px;padding:12px}
.pred-fish{font-size:15px;font-weight:bold;color:#fff;margin-bottom:4px}
.pred-avg{font-size:13px;color:#4db8ff;margin-bottom:2px}
.pred-max{font-size:11px;color:#7a9bb5}
.pred-area{font-size:11px;color:#f4a261;margin-top:2px}
.pred-samples{font-size:10px;color:#4a6a8a;margin-top:4px}
.combo-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin:12px 0}
.combo-card{display:block;background:#0d2137;border:1px solid #1a4060;border-radius:8px;padding:12px;text-decoration:none;color:#e0e8f0;transition:border-color .2s,transform .1s}
.combo-card:hover{border-color:#4db8ff;transform:translateY(-2px)}
.combo-header{display:flex;align-items:center;gap:4px;flex-wrap:wrap}
.combo-fish{font-size:15px;font-weight:bold;color:#fff}
.combo-x{color:#4a6a8a;font-size:12px}
.combo-area{font-size:13px;color:#f4a261}
.combo-trend{font-size:14px;font-weight:bold;margin-left:auto}
.combo-trend.trend-up{color:#4dcc88}
.combo-trend.trend-down{color:#cc4d4d}
.combo-trend.trend-flat{color:#7a9bb5}
.combo-stars{font-size:13px;margin:4px 0 2px}
.combo-stats{font-size:12px;color:#4db8ff;margin:2px 0}
.combo-meta{font-size:11px;color:#7a9bb5;margin-top:2px}
.combo-rank{font-size:10px;font-weight:bold;border-radius:3px;padding:1px 5px;margin-right:4px}
.combo-rank.rank-1{background:#e85d04;color:#fff}
.combo-rank.rank-2{background:#7a9bb5;color:#fff}
.combo-rank.rank-3{background:#8b6914;color:#fff}
.tbl-wrap{overflow-x:auto;-webkit-overflow-scrolling:touch}
@media(max-width:640px){header{padding:12px 14px}header h1{font-size:18px}header .site-desc{font-size:10px}nav{padding:6px 12px;gap:8px 12px}.wrap{padding:14px 10px}.target-top{flex-direction:column;gap:10px}.target-grid{grid-template-columns:1fr 1fr}.grid{grid-template-columns:1fr 1fr}.area-grid{grid-template-columns:1fr 1fr}.combo-grid{grid-template-columns:1fr 1fr}.area-menu{min-width:min(300px,calc(100vw - 24px));max-height:55vh;overflow-y:auto}table{font-size:11px}th,td{padding:5px 4px}.bar-wrap{width:50px}}
"""

# ============================================================
# #7: 今週イチ押し + #1: リンク付きカード
# ============================================================
def calc_targets(data, history):
    now = datetime.now()
    cur_month = now.month
    year, week_num = current_iso_week()
    cutoff = (now - timedelta(days=30)).strftime("%Y/%m/%d")
    fish_counts = {}
    fish_latest: dict = {}
    ship_counts_per_fish = {}
    for c in data:
        date_str = c.get("date") or ""
        for f in c["fish"]:
            if f != "不明":
                fish_counts[f] = fish_counts.get(f, 0) + 1
                ship_counts_per_fish.setdefault(f, set()).add(c["ship"])
                if date_str > fish_latest.get(f, ""):
                    fish_latest[f] = date_str
    max_cnt = max(fish_counts.values()) if fish_counts else 1
    targets = []
    for fish, cnt in fish_counts.items():
        # 直近30日以内に釣果がない魚種はトップ除外
        if fish_latest.get(fish, "") < cutoff:
            continue
        score     = get_season_score(fish, cur_month)
        this_w, last_w = get_yoy_data(history, fish, year, week_num)
        prev_w    = get_prev_week_data(history, fish, year, week_num)
        ships     = len(ship_counts_per_fish.get(fish, set()))
        composite = calc_composite_score(fish, cnt, max_cnt, this_w, last_w, prev_w, cur_month)
        badge     = yoy_badge(this_w, last_w)
        comment   = build_comment(fish, cnt, score, this_w, last_w, prev_w, max_cnt, composite)
        stars     = composite_to_stars(composite)
        tags      = build_reason_tags(fish, cnt, max_cnt, this_w, last_w, prev_w, cur_month)
        prob      = calc_weekend_prob(history, fish, year, week_num)
        surge     = is_surge(history, fish, year, week_num)
        targets.append({"fish": fish, "count": cnt, "score": score, "composite": composite,
                        "comment": comment, "badge": badge, "ships": ships,
                        "stars": stars, "tags": tags, "prob": prob, "surge": surge})
    targets.sort(key=lambda x: -x["composite"])
    return targets[:5]

# ============================================================
# #12: コンボ別詳細分析（魚種×エリアグループ）
# ============================================================
def calc_combo_scores(data, history):
    """魚種×エリアグループごとの複合スコアを計算しランキング化"""
    now = datetime.now()
    cur_month = now.month
    year, week_num = current_iso_week()
    cutoff = (now - timedelta(days=30)).strftime("%Y/%m/%d")

    # エリアグループごとに集計
    combo: dict = {}  # (fish, group) -> list of catches
    for c in data:
        group = _area_to_group(c["area"])
        if not group:
            continue
        for f in c["fish"]:
            if f != "不明":
                combo.setdefault((f, group), []).append(c)

    results = []
    # 全魚種最大件数（スコアリング用）
    max_cnt = max((len(cs) for cs in combo.values()), default=1)

    for (fish, group), catches in combo.items():
        if len(catches) < 3:
            continue
        latest = max((c.get("date") or "" for c in catches), default="")
        if latest < cutoff:
            continue

        # 個人釣果のみ（船中数除外）で統計
        personal = [c for c in catches if c.get("count_range") and not c["count_range"].get("is_boat")]
        if personal:
            avgs = [(c["count_range"]["min"] + c["count_range"]["max"]) // 2 for c in personal]
            combo_avg = round(sum(avgs) / len(avgs), 1)
            combo_max = max(c["count_range"]["max"] for c in personal)
        else:
            combo_avg = 0
            combo_max = 0

        ships = len(set(c["ship"] for c in catches))

        # 昨年比・前週比（魚種全体のhistoryを使用）
        this_w, last_w = get_yoy_data(history, fish, year, week_num)
        prev_w = get_prev_week_data(history, fish, year, week_num)

        # コンボ専用スコア計算
        cnt = len(catches)
        count_s = cnt / max_cnt if max_cnt > 0 else 0.5

        def safe_ratio(a, b, cap=2.0):
            if a and b and b > 0:
                return min(a / b, cap) / cap
            return 0.5

        avg_s = safe_ratio(
            this_w.get("avg") if this_w else None,
            last_w.get("avg") if last_w else None,
        )
        yoy_s = safe_ratio(
            this_w.get("ships") if this_w else None,
            last_w.get("ships") if last_w else None,
        )
        wow_s = safe_ratio(
            this_w.get("ships") if this_w else None,
            prev_w.get("ships") if prev_w else None,
            cap=1.5,
        )
        season = get_season_score(fish, cur_month)
        season_s = (season / 5.0) if season > 0 else 0.5
        # コンボ密度ボーナス: 船宿数に対して件数が多い → 安定して釣れている
        density_s = min(cnt / max(ships, 1) / 3.0, 1.0)

        weights = [
            (count_s,   0.20),
            (avg_s,     0.15),
            (yoy_s,     0.15),
            (wow_s,     0.10),
            (season_s,  0.15),
            (density_s, 0.25),
        ]
        composite = round(sum(s * w for s, w in weights) * 100, 1)

        # 前週比トレンド
        trend = ""
        if this_w and prev_w:
            t_s = this_w.get("ships") or 0
            p_s = prev_w.get("ships") or 0
            if t_s and p_s:
                ratio = t_s / p_s
                if ratio > 1.2:
                    trend = "up"
                elif ratio < 0.8:
                    trend = "down"
                else:
                    trend = "flat"

        # エリア内の代表的な港
        area_ports = list(dict.fromkeys(c["area"] for c in catches))[:3]

        results.append({
            "fish": fish, "group": group, "catches": cnt,
            "avg": combo_avg, "max": combo_max, "ships": ships,
            "composite": composite, "trend": trend,
            "ports": area_ports, "season": season,
        })

    results.sort(key=lambda x: -x["composite"])
    return results[:10]


def build_combo_section(combos):
    """index.htmlに表示するコンボ分析セクションHTML"""
    if not combos:
        return ""
    cards = ""
    for i, cb in enumerate(combos[:6]):
        trend_icon = {"up": "↑", "down": "↓", "flat": "→"}.get(cb["trend"], "")
        trend_cls = {"up": "trend-up", "down": "trend-down", "flat": "trend-flat"}.get(cb["trend"], "")
        trend_html = f'<span class="combo-trend {trend_cls}">{trend_icon}</span>' if trend_icon else ""

        stars = composite_to_stars(cb["composite"])
        ports_str = "・".join(cb["ports"])
        avg_str = f'平均{cb["avg"]:.0f}匹' if cb["avg"] else ""
        max_str = f'最高{cb["max"]}匹' if cb["max"] else ""
        stat_str = " / ".join(s for s in [avg_str, max_str] if s)

        # 代表的なfish_areaページへのリンク（最初の港）
        link_area = cb["ports"][0] if cb["ports"] else ""
        link_href = f'fish_area/{quote(cb["fish"], safe="")}_{quote(link_area, safe="")}.html' if link_area else "#"

        rank_label = ""
        if i == 0:
            rank_label = '<span class="combo-rank rank-1">1st</span>'
        elif i == 1:
            rank_label = '<span class="combo-rank rank-2">2nd</span>'
        elif i == 2:
            rank_label = '<span class="combo-rank rank-3">3rd</span>'

        cards += f"""
    <a class="combo-card" href="{link_href}">
      <div class="combo-header">
        {rank_label}
        <span class="combo-fish">{cb['fish']}</span>
        <span class="combo-x">×</span>
        <span class="combo-area">{cb['group']}</span>
        {trend_html}
      </div>
      <div class="combo-stars">{stars}</div>
      <div class="combo-stats">{stat_str}</div>
      <div class="combo-meta">{cb['catches']}件 / {cb['ships']}隻 / {ports_str}</div>
    </a>"""

    return f"""
  <h2>🔍 注目の魚種×エリア</h2>
  <p style="font-size:12px;color:#7a9bb5;margin-bottom:10px">魚種とエリアの組み合わせをスコアリング。「どこで何を狙うか」の参考に</p>
  <div class="combo-grid">{cards}
  </div>"""


def _render_tags(tags):
    html = ""
    for kind, label in tags:
        cls = "rtag-up" if kind in ("up","up2","season","hot","wow-up") else "rtag-down"
        html += f'<span class="rtag {cls}">{label}</span>'
    return html

def _prob_bar(prob, surge):
    """週末予測確率のプログレスバーHTML"""
    if prob is None:
        return ""
    if prob >= 80:
        color, label = "#e85d04", "激アツ"
    elif prob >= 60:
        color, label = "#f4a261", "良好"
    elif prob >= 40:
        color, label = "#4db8ff", "まずまず"
    else:
        color, label = "#7a9bb5", "渋め"
    surge_html = '<span style="color:#e85d04;font-size:11px;font-weight:bold;margin-left:6px">🔥 急上昇中</span>' if surge else ""
    return (
        f'<div class="prob-wrap">'
        f'<span class="prob-label">週末の期待度</span>'
        f'<div class="prob-bar-bg"><div class="prob-bar-fill" style="width:{prob}%;background:{color}"></div></div>'
        f'<span class="prob-pct" style="color:{color};font-weight:bold">{label}</span>'
        f'{surge_html}</div>'
    )

def build_target_section(targets):
    if not targets:
        return "<p style='color:#7a9bb5'>データ収集中です。しばらくお待ちください。</p>"
    top = targets[0]
    tags_html = _render_tags(top.get("tags", []))
    prob_html  = _prob_bar(top.get("prob"), top.get("surge"))
    top_html = f"""
    <a class="target-top" href="fish/{fish_slug(top['fish'])}.html">
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
        {prob_html}
        <div class="tt-comment">{top['comment']}</div>
        <div class="tt-meta">出船: 約{top['ships']}隻 ／ 直近釣果: {top['count']}件</div>
      </div>
    </a>"""
    rest_html = ""
    for t in targets[1:]:
        t_tags   = _render_tags(t.get("tags", []))
        t_prob   = _prob_bar(t.get("prob"), t.get("surge"))
        rest_html += f"""
    <a class="target-card" href="fish/{fish_slug(t['fish'])}.html">
      <div class="tc-name-row">
        <span class="tc-fish-name">{t['fish']}</span>
        <span class="tc-stars">{t['stars']}</span>
      </div>
      <div class="tc-tags">{t_tags}</div>
      {t_prob}
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
        links = [f'<a href="area/{area_slug(a)}.html" class="filter-btn">{a}</a>'
                 for a in group_areas if a in active_areas]
        covered.update(group_areas)
        if links:
            filter_btns += (f'<div class="filter-group">'
                            f'<span class="filter-group-label">{group_label}</span>'
                            f'{"".join(links)}</div>')
    others = [f'<a href="area/{area_slug(a)}.html" class="filter-btn">{a}</a>'
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
    <div class="tbl-wrap"><table id="catch-table">
      <tr><th>日付</th><th>エリア</th><th>船宿</th><th>魚種</th><th>数量</th><th>大きさ(cm)</th><th>重量(kg)</th></tr>
      {rows}
    </table></div>"""

# ============================================================
# index.html 生成
# ============================================================
def build_html(catches, crawled_at, history, weather_data=None):
    now = datetime.now()
    current_month = now.month
    fish_summary = {}
    year, week_num = current_iso_week()
    stale_cutoff = (now - timedelta(days=30)).strftime("%Y/%m/%d")
    for c in catches:
        for f in c["fish"]:
            if f != "不明":
                fish_summary.setdefault(f, []).append(c)
    areas = sorted(set(c["area"] for c in catches))
    cards = ""
    for fish, cs in sorted(fish_summary.items(), key=lambda x: -len(x[1])):
        areas_list  = list(dict.fromkeys(c["area"] for c in cs[:3]))
        fish_id     = re.sub(r'[^\w]', '_', fish)
        latest_date = max((c.get("date") or "" for c in cs), default="")
        is_stale    = latest_date < stale_cutoff
        ship_counts = {}
        for c in cs: ship_counts[c["ship"]] = ship_counts.get(c["ship"], 0) + 1
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
        surge_badge = '<span class="surge-badge">🔥 急上昇中</span>' if is_surge(history, fish, year, week_num) else ""
        prob        = calc_weekend_prob(history, fish, year, week_num)
        prob_html   = ""
        if prob is not None:
            if prob >= 80:
                color, label = "#e85d04", "激アツ"
            elif prob >= 60:
                color, label = "#f4a261", "良好"
            elif prob >= 40:
                color, label = "#4db8ff", "まずまず"
            else:
                color, label = "#7a9bb5", "渋め"
            prob_html = (
                f'<div class="fc-prob">'
                f'<span class="prob-label">週末</span>'
                f'<div class="prob-bar-bg"><div class="prob-bar-fill" style="width:{prob}%;background:{color}"></div></div>'
                f'<span class="prob-pct" style="color:{color};font-weight:bold">{label}</span></div>'
            )
        # V2 カード用データ計算
        cnt_range_str = ""
        if this_w:
            mx = this_w.get("max") or 0
            av = this_w.get("avg") or 0
            if av and mx: cnt_range_str = f"{av:.0f}〜{mx}匹"
            elif mx:       cnt_range_str = f"〜{mx}匹"
            elif av:       cnt_range_str = f"平均{av:.0f}匹"
        if not cnt_range_str: cnt_range_str = f"{len(cs)}件"
        sz_val = (this_w.get("size_avg") or 0) if this_w else 0
        sz_str = f"{sz_val:.0f}cm" if sz_val else ""
        areas_str2 = "・".join(areas_list[:2])
        detail_str = " | ".join(filter(None, [sz_str, areas_str2]))
        top_ship_name = sorted(ship_counts.items(), key=lambda x: -x[1])[0][0] if ship_counts else ""
        yoy_pct_str = ""
        if this_w and last_w and last_w.get("ships"):
            _p = round((this_w.get("ships", 0) - last_w["ships"]) / last_w["ships"] * 100)
            if abs(_p) >= 5: yoy_pct_str = f"{'+'if _p>=0 else ''}{_p}%"
        fb_text = " ".join(filter(None, [f"◎{top_ship_name}" if top_ship_name else "", yoy_pct_str]))
        v2_trend_cls, v2_trend_txt = "", ""
        if this_w and prev_w:
            _ts = this_w.get("ships") or 0
            _ps = prev_w.get("ships") or 0
            if _ts and _ps:
                if _ts/_ps > 1.2:   v2_trend_cls, v2_trend_txt = "up",   "↑ 先週より上昇"
                elif _ts/_ps < 0.8: v2_trend_cls, v2_trend_txt = "dn",   "↓ 先週より減少"
                else:                v2_trend_cls, v2_trend_txt = "flat", "→ 先週並み"
        stale_cls = " stale" if is_stale else ""
        trend_tag = f'<div class="trend {v2_trend_cls}">{v2_trend_txt}</div>' if v2_trend_txt else ""
        fb_tag    = f'<div class="fb">{fb_text}</div>' if fb_text else ""
        # ミニバー（7日間）
        _today = now.date()
        _daily_max = {}
        for c in cs:
            try: _d = datetime.strptime(c["date"], "%Y/%m/%d").date()
            except: continue
            _cr = c.get("count_range")
            _v = (_cr["max"] if _cr and not _cr.get("is_boat") else 0) or 0
            if _v > _daily_max.get(_d, 0): _daily_max[_d] = _v
        _vals = [_daily_max.get(_today - timedelta(days=i), 0) for i in range(6, -1, -1)]
        _wmax = max(_vals) if any(v > 0 for v in _vals) else 1
        mini_bars = ""
        if _wmax > 0:
            _bar_parts = []
            _label_parts = []
            for _i, _v in enumerate(_vals):
                _h = max(8, int(_v / _wmax * 100)) if _v > 0 else 4
                _cls = " today" if _i == 6 else ""
                _bar_parts.append(f'<div class="b{_cls}" style="height:{_h}%"></div>')
                _d = _today - timedelta(days=6 - _i)
                if _i == 6:
                    _label_parts.append('<span class="bl today">今日</span>')
                elif _i == 0:
                    _label_parts.append(f'<span class="bl">{_d.month}/{_d.day}</span>')
                else:
                    _label_parts.append('<span class="bl"></span>')
            mini_bars = (
                f'<div class="bars">{"".join(_bar_parts)}</div>'
                f'<div class="bar-labels">{"".join(_label_parts)}</div>'
            )
        cards += (
            f'<a class="fc{stale_cls}" href="fish/{fish_slug(fish)}.html">'
            f'<div class="fn">{fish}</div>'
            f'<div class="fr">{cnt_range_str} <small>釣果{len(cs)}件・{ship_num}船宿</small></div>'
            f'<div class="fs">{detail_str}</div>'
            f'{fb_tag}{mini_bars}{trend_tag}'
            f'</a>'
        )
    targets      = calc_targets(catches, history)
    target_html  = build_target_section(targets)
    forecast     = build_forecast(targets)
    weather_html = ""  # V1遺産: build_weather_section 廃止
    forecast_json_data = weather_data.get("_forecast_data") if weather_data else None
    forecast_html = build_forecast_section(forecast_json_data, weather_data) if forecast_json_data else ""
    catch_table  = build_catch_table(catches)
    combos       = calc_combo_scores(catches, history)
    combo_html   = build_combo_section(combos)
    active_areas = set(c["area"] for c in catches)
    area_nav_parts = []
    covered = set()
    for group_label, group_areas in AREA_GROUPS.items():
        links = [f'<a href="area/{area_slug(a)}.html">{a}</a>' for a in group_areas if a in active_areas]
        covered.update(group_areas)
        if links:
            area_nav_parts.append(
                f'<div class="area-group"><div class="area-group-label">{group_label}</div>'
                f'<div class="area-group-links">{"".join(links)}</div></div>'
            )
    # AREA_GROUPS未分類のエリアは「その他」にまとめる
    others = [f'<a href="area/{area_slug(a)}.html">{a}</a>' for a in sorted(active_areas - covered)]
    if others:
        area_nav_parts.append(
            f'<div class="area-group"><div class="area-group-label">その他</div>'
            f'<div class="area-group-links">{"".join(others)}</div></div>'
        )
    area_nav = "".join(area_nav_parts)
    # V2 ZONE B2: エリア別今日の釣果カード
    today_str = now.strftime("%Y/%m/%d")
    today_catches = [c for c in catches if c.get("date") == today_str]
    area_today_html = ""
    area_fish_map = {}  # area -> {fish: count}
    for c in today_catches:
        for f in c["fish"]:
            if f not in ("不明", "欠航"):
                area_fish_map.setdefault(c["area"], {}).setdefault(f, 0)
                area_fish_map[c["area"]][f] += 1
    # エリアを件数降順でソート
    area_cnt_map = {}
    for c in today_catches:
        area_cnt_map[c["area"]] = area_cnt_map.get(c["area"], 0) + 1
    for area in sorted(active_areas, key=lambda x: -area_cnt_map.get(x, 0))[:8]:
        cnt = area_cnt_map.get(area, 0)
        top_fish = sorted(area_fish_map.get(area, {}).items(), key=lambda x: -x[1])[:4]
        fish_tags = "".join(f'<a href="fish/{fish_slug(f)}.html" class="at-ftag">{f}</a>' for f, _ in top_fish)
        # NOTE: <a> の中に <a> をネストすると HTML 違反 → div で囲い、上部のみ area リンク
        area_today_html += (
            f'<div class="at-card">'
            f'<a href="area/{area_slug(area)}.html" class="at-area-link">'
            f'<div class="at-name">{area}</div>'
            f'<div class="at-count">{cnt}件</div>'
            f'</a>'
            f'<div class="at-fish">{fish_tags}</div>'
            f'</div>'
        )
    # V2 ZONE C: 出船リスク予報（7日間）
    risk_grid_html = ""
    forecast_json_data_for_risk = weather_data.get("_forecast_data") if weather_data else None
    if forecast_json_data_for_risk:
        days_data = forecast_json_data_for_risk.get("days", {})
        dow_jp = ["月","火","水","木","金","土","日"]
        risk_days = ""
        for date_str in sorted(days_data.keys())[:7]:
            try:
                dt = datetime.strptime(date_str, "%Y-%m-%d")
                dow = dow_jp[dt.weekday()]
                label_date = f"{dt.month}/{dt.day}"
            except: continue
            day_info = days_data[date_str]
            # エリア別波高・風速の平均
            areas_info = day_info.get("areas", {})
            if areas_info:
                waves = [v.get("wave_height", 0) or 0 for v in areas_info.values()]
                winds = [v.get("wind_speed", 0) or 0 for v in areas_info.values()]
                avg_wave = sum(waves) / len(waves) if waves else 0
                avg_wind = sum(winds) / len(winds) if winds else 0
            else:
                avg_wave = day_info.get("wave_height") or 0
                avg_wind = day_info.get("wind_speed") or 0
            if avg_wave >= 2.0 or avg_wind >= 10:
                cls, icon, lbl = "bad", "×", "欠航警戒"
            elif avg_wave >= 1.2 or avg_wind >= 7:
                cls, icon, lbl = "warn", "△", "注意"
            else:
                cls, icon, lbl = "good", "○", "好条件"
            risk_days += (
                f'<div class="risk-day {cls}">'
                f'<div class="rd-dow">{dow}</div>'
                f'<div class="rd-date">{label_date}</div>'
                f'<div class="rd-icon">{icon}</div>'
                f'<div class="rd-label">{lbl}</div>'
                f'</div>'
            )
        if risk_days:
            risk_grid_html = f'<div class="risk-grid">{risk_days}</div>'
    # V2 魚種ナビチップ（ZONE E）
    fish_nav_html = "".join(
        f'<a href="fish/{fish_slug(f)}.html">{f}</a>'
        for f in sorted(fish_summary.keys(), key=lambda x: -len(fish_summary[x]))[:12]
    )
    area_nav_html = "".join(
        f'<a href="area/{area_slug(a)}.html">{a}</a>'
        for a in sorted(active_areas)[:12]
    )
    # V2 概況テキスト
    overview_html = build_index_overview_text(catches, history, crawled_at)
    # V2 ティザー
    teaser_html = build_teaser_rotator_html()
    # V2 その他魚種（fish_others）
    sorted_fish = sorted(fish_summary.keys(), key=lambda x: -len(fish_summary[x]))
    main_fish = sorted_fish[:10]
    other_fish = sorted_fish[10:]
    main_cards = "".join(
        cards_part for f, cards_part in zip(
            [f for f in sorted(fish_summary.keys(), key=lambda x: -len(fish_summary[x]))],
            cards.split('</a><a ') if '</a><a ' in cards else [cards]
        )
    ) if cards else ""
    # カードをそのまま使う（分割せずに）
    fish_others_html = ""
    if other_fish:
        other_links = "".join(f'<a href="fish/{fish_slug(f)}.html">{f}</a>' for f in other_fish)
        fish_others_html = (
            f'<div class="fish-others">'
            f'<div class="fo-title">今日ほかに釣れている魚</div>'
            f'<div class="fo-list">{other_links}</div>'
            f'</div>'
        )
    # HERO 数値（今日分のみ）
    today_str = now.strftime("%Y/%m/%d")
    today_catches = [c for c in catches if c.get("date") == today_str]
    hero_base = today_catches if today_catches else catches
    hero_count = len(hero_base)
    hero_ships = len(set(c["ship"] for c in hero_base))
    hero_areas = len(set(c["area"] for c in hero_base))
    index_extra_css = """.hero{background:linear-gradient(135deg,#0d2b4a,#163d5c);color:#fff;text-align:center;padding:24px 14px 20px}
.hero-sub{font-size:12px;color:rgba(255,255,255,.6)}
.hero .n{font-size:48px;font-weight:800;color:var(--cta);line-height:1.1}
.hero .n u{font-size:16px;color:rgba(255,255,255,.7);font-weight:400;text-decoration:none;margin-left:3px}
.hero .info{font-size:12px;color:rgba(255,255,255,.6);margin-top:6px;display:flex;align-items:center;justify-content:center;gap:5px}
.hero .dot{width:6px;height:6px;background:var(--pos);border-radius:50%;animation:blink 2s ease-in-out infinite}
@keyframes blink{0%,100%{opacity:1}50%{opacity:.3}}
.hero .updated{font-size:11px;color:rgba(255,255,255,.5);margin-top:4px}
.fish-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:8px;margin-bottom:4px}
.fc{background:var(--card);border:1px solid var(--border);border-radius:var(--r);padding:10px;display:block;transition:border-color .15s}
.fc:hover{border-color:var(--cta);text-decoration:none}
.fc .fn{font-size:14px;font-weight:800;color:var(--accent)}
.fc .fr{font-size:18px;font-weight:800;color:var(--cta);margin-top:2px}
.fc .fr small{font-size:11px;color:var(--muted);font-weight:400}
.fc .fs{font-size:10px;color:var(--muted)}
.fc .fb{font-size:10px;color:var(--pos);font-weight:600;margin-top:3px}
.fc .bars{display:flex;align-items:flex-end;gap:1px;height:20px;margin-top:4px}
.fc .bars .b{flex:1;background:var(--cta);border-radius:1px 1px 0 0;opacity:.6;min-width:4px}
.fc .bars .b.today{opacity:1;background:var(--pos)}
.fc .bar-labels{display:flex;gap:1px;margin-top:1px}
.fc .bar-labels .bl{flex:1;font-size:8px;color:var(--muted);text-align:center;min-width:4px}
.fc .bar-labels .bl.today{color:var(--pos);font-weight:700}
.fc .trend{font-size:9px;font-weight:700;margin-top:2px}
.fc .trend.up{color:var(--pos)}.fc .trend.dn{color:var(--neg)}.fc .trend.flat{color:var(--muted)}
.fc.stale{opacity:.6}
.fish-others{margin:12px 0 20px;padding:10px 12px;background:var(--card);border:1px solid var(--border);border-radius:var(--r)}
.fo-title{font-size:11px;color:var(--muted);font-weight:600;margin-bottom:6px}
.fo-list{display:flex;flex-wrap:wrap;gap:4px}
.fo-list a{font-size:12px;padding:3px 8px;background:var(--bg);border-radius:12px;color:var(--sub);font-weight:600}
.fo-list a:hover{background:var(--accent);color:#fff;text-decoration:none}
.area-today{display:grid;grid-template-columns:repeat(2,1fr);gap:8px;margin-bottom:16px}
.at-card{background:var(--card);border:1px solid var(--border);border-radius:var(--r);padding:10px 12px;transition:border-color .15s}
.at-card:hover{border-color:var(--cta)}
.at-area-link{display:block;text-decoration:none;color:inherit}
.at-area-link:hover{text-decoration:none}
.at-name{font-size:12px;font-weight:700;color:var(--accent)}
.at-count{font-size:22px;font-weight:800;color:var(--cta);line-height:1.1;margin-top:2px}
.at-count::before{content:"釣果報告";display:block;font-size:9px;font-weight:400;color:var(--sub);margin-bottom:1px}
.at-fish{display:flex;flex-wrap:wrap;gap:3px;margin-top:5px}
.at-ftag{font-size:9px;padding:2px 6px;background:var(--bg);border:1px solid var(--border);border-radius:8px;color:var(--sub);text-decoration:none}
.at-ftag:hover{background:var(--accent);color:#fff;border-color:var(--accent);text-decoration:none}
.risk-grid{display:grid;grid-template-columns:repeat(7,1fr);gap:4px;margin-bottom:14px}
.risk-day{background:var(--card);border:1px solid var(--border);border-radius:8px;padding:8px 4px;text-align:center}
.risk-day.good{border-color:var(--pos);background:#f0fdf4}
.risk-day.warn{border-color:var(--warn);background:#fffbeb}
.risk-day.bad{border-color:var(--neg);background:#fef2f2}
.rd-dow{font-size:10px;color:var(--muted);font-weight:600}
.rd-date{font-size:11px;color:var(--sub);font-weight:600}
.rd-icon{font-size:16px;margin:4px 0;font-weight:800}
.risk-day.good .rd-icon{color:var(--pos)}
.risk-day.warn .rd-icon{color:var(--warn)}
.risk-day.bad .rd-icon{color:var(--neg)}
.rd-label{font-size:9px;font-weight:700}
.nav-section{background:var(--card);border:1px solid var(--border);border-radius:var(--r);padding:14px;margin-bottom:16px}
.nav-section h3{font-size:13px;font-weight:700;color:var(--accent);margin-bottom:8px}
.nav-chips{display:flex;flex-wrap:wrap;gap:5px}
.nav-chips a{font-size:12px;padding:5px 10px;background:var(--bg);border-radius:12px;color:var(--sub);font-weight:600}
.nav-chips a:hover{background:var(--accent);color:#fff;text-decoration:none}
@media(min-width:769px){.fish-grid{grid-template-columns:repeat(3,1fr)}}
.st-sub{font-size:12px;font-weight:400;color:var(--sub);margin-left:6px}
.note-text{font-size:12px;color:var(--sub);margin-bottom:10px}
.wx-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:10px;margin-bottom:16px}
.weather-card{background:var(--card);border:1px solid var(--border);border-radius:var(--r);padding:12px}
.wc-head{display:flex;align-items:center;gap:8px;margin-bottom:8px}
.wc-area{font-size:14px;font-weight:700;color:var(--accent)}
.wc-tide{font-size:11px;color:var(--sub)}
.wl-row{display:flex;align-items:center;gap:6px;padding:6px 0;border-top:1px solid var(--border);font-size:11px;flex-wrap:wrap}
.wl-day{font-weight:700;color:var(--text);min-width:16px}
.wl-wave{flex:1 1 90px;color:var(--sub)}
.wl-wind{flex:1 1 80px;color:var(--sub)}
.wl-temp{flex:0 0 50px;color:var(--sub)}
.wl-judge{font-size:12px;font-weight:700;flex:0 0 80px;text-align:right}
.wl-judge.good{color:var(--pos)}.wl-judge.warn{color:#f4a261}.wl-judge.bad{color:var(--neg)}"""
    jsonld_website = f'{{"@context":"https://schema.org","@type":"WebSite","name":"船釣り予想","url":"{SITE_URL}/","potentialAction":{{"@type":"SearchAction","target":{{"@type":"EntryPoint","urlTemplate":"{SITE_URL}/fish/{{search_term_string}}.html"}},"query-input":"required name=search_term_string"}}}}'
    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
  <meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
  <title>関東船釣り釣果情報 | 今日何が釣れてる？ | 船釣り予想</title>
  <meta name="description" content="関東エリア（神奈川・東京・千葉・茨城）の船宿釣果を毎日更新。今日釣れている魚・エリア別速報・船宿ランキング。">
  <link rel="canonical" href="{SITE_URL}/">
  <meta property="og:title" content="関東船釣り釣果情報 | 今日何が釣れてる？">
  <meta property="og:description" content="関東エリアの船宿釣果を毎日自動集計。今日釣れている魚・エリア別速報。">
  <meta property="og:url" content="{SITE_URL}/">
  <meta property="og:type" content="website">
  <meta property="og:site_name" content="船釣り予想">
  <script type="application/ld+json">{jsonld_website}</script>
  {GA_TAG}
  {ADSENSE_TAG}
  <style>{V2_COMMON_CSS}
{index_extra_css}</style>
</head>
<body>
{_v2_header_nav('index')}
<!-- HERO -->
<div class="hero">
  <div class="hero-sub">関東船釣り釣果情報</div>
  <div class="n">{hero_count}<u>件</u></div>
  <div class="info">
    <span class="dot"></span>
    <span>本日の釣果報告 — {hero_ships}船宿・{hero_areas}エリア</span>
  </div>
  <div class="updated">最終更新: {crawled_at}</div>
</div>
<div class="c">
<!-- ZONE B: 釣れている魚 -->
<h2 class="st">今日 釣れている魚 <span class="tag free">無料</span></h2>
<div class="fish-grid">{cards}</div>
{fish_others_html}
<!-- ZONE B2: エリア別今日の釣果 -->
<h2 class="st">エリア別 今日の釣果 <span class="tag free">無料</span></h2>
<div class="area-today">{area_today_html}</div>
{f'<h2 class="st">出船リスク予報 <span class="tag free">無料</span></h2>{risk_grid_html}' if risk_grid_html else ''}
<!-- TEASER ROTATOR -->
{teaser_html}
<!-- 広告① -->
<ins class="adsbygoogle" style="display:block" data-ad-client="ca-pub-7406401300491553" data-ad-slot="auto" data-ad-format="auto" data-full-width-responsive="true"></ins>
<script>(adsbygoogle=window.adsbygoogle||[]).push({{}});</script>
<!-- 概況テキスト -->
{overview_html}
<!-- ZONE E: ナビ -->
<div class="nav-section">
  <h3>人気の魚種から探す</h3>
  <div class="nav-chips">{fish_nav_html}<a href="calendar.html">すべて見る →</a></div>
</div>
<div class="nav-section">
  <h3>エリアから探す</h3>
  <div class="nav-chips">{area_nav_html}<a href="area/">すべて見る →</a></div>
</div>
<!-- 広告② -->
<ins class="adsbygoogle" style="display:block" data-ad-client="ca-pub-7406401300491553" data-ad-slot="auto" data-ad-format="auto" data-full-width-responsive="true"></ins>
<script>(adsbygoogle=window.adsbygoogle||[]).push({{}});</script>
</div><!-- /.c -->
{DATA_NOTE_HTML}
{_v2_footer(crawled_at)}
{_v2_bottom_nav('index')}
<script>
(function(){{
  var slides=document.querySelectorAll('.tr-slide');
  var dots=document.querySelectorAll('.tr-dot');
  if(!slides.length)return;
  var cur=0;
  function go(i){{slides[cur].classList.remove('is-active');dots[cur].classList.remove('is-active');cur=i;slides[cur].classList.add('is-active');dots[cur].classList.add('is-active');}}
  dots.forEach(function(d,i){{d.addEventListener('click',function(){{go(i);clearInterval(timer);}});}});
  var timer;
  if(!window.matchMedia('(prefers-reduced-motion:reduce)').matches)
    timer=setInterval(function(){{go((cur+1)%slides.length);}},5000);
}})();
</script>
</body>
</html>"""

# ============================================================
# #6: 魚種別ページ
# ============================================================
def build_fish_pages(data, history, crawled_at=""):
    os.makedirs(os.path.join(WEB_DIR, "fish"), exist_ok=True)
    now = datetime.now()
    current_month = now.month
    year, week_num = current_iso_week()
    decadal_calendar = load_decadal_calendar()
    tackle_data = load_fish_tackle()
    fish_summary = {}
    _SKIP_FISH = {"不明", "欠航"}
    for c in data:
        for f in c["fish"]:
            if f not in _SKIP_FISH: fish_summary.setdefault(f, []).append(c)
    for fish, catches in fish_summary.items():
        if len(catches) < 1: continue
        season_bar_html = build_season_bar(fish, current_month)
        score   = get_season_score(fish, current_month)
        this_w, last_w = get_yoy_data(history, fish, year, week_num)
        comment = build_comment(fish, len(catches), score, this_w, last_w)
        # 旬の突入検出
        entry_this, entry_last = calc_season_entry(history, fish, year)
        season_entry_html = ""
        if entry_this and entry_last:
            diff = entry_this - entry_last
            if diff < 0:
                trend_txt = f"昨年より{abs(diff)}週早い 🌱"
                trend_cls = "entry-early"
            elif diff > 0:
                trend_txt = f"昨年より{diff}週遅い"
                trend_cls = "entry-late"
            else:
                trend_txt = "昨年と同時期"
                trend_cls = "entry-same"
            season_entry_html = (
                f'<div class="season-entry {trend_cls}">'
                f'今年の初釣果: 第{entry_this}週 ／ 昨年: 第{entry_last}週'
                f'<span class="entry-trend">（{trend_txt}）</span></div>'
            )
        # V2: 今日・今週の集計
        today_str_f = now.strftime("%Y/%m/%d")
        today_catches_f = [c for c in catches if c.get("date") == today_str_f]
        max_cnt = 0
        for c in catches:
            cr = c.get("count_range")
            if cr and not cr.get("is_boat"): max_cnt = max(max_cnt, cr["max"])
        # fish-hero 数値
        t_maxs = [c["cnt_max"] for c in today_catches_f if c.get("cnt_max") is not None]
        t_mins = [c["cnt_min"] for c in today_catches_f if c.get("cnt_min") is not None]
        t_sz_lo = [c["size_min"] for c in today_catches_f if c.get("size_min") is not None]
        t_sz_hi = [c["size_max"] for c in today_catches_f if c.get("size_max") is not None]
        if t_mins and t_maxs:
            cnt_range_str = f"{int(min(t_mins))}〜{int(max(t_maxs))}匹"
        elif t_maxs:
            cnt_range_str = f"〜{int(max(t_maxs))}匹"
        else:
            cnt_range_str = f"釣果{len(catches)}件"
        sz_str = f"{int(min(t_sz_lo))}〜{int(max(t_sz_hi))}cm" if t_sz_lo and t_sz_hi else ""
        # area-cmp（今日のエリア別）
        area_today_f: dict = {}
        for c in today_catches_f:
            d = area_today_f.setdefault(c["area"], {"hi": [], "lo": []})
            if c.get("cnt_max") is not None: d["hi"].append(c["cnt_max"])
            if c.get("cnt_min") is not None: d["lo"].append(c["cnt_min"])
        area_cmp_rows = ""
        for aname, ad in sorted(area_today_f.items(), key=lambda x: -(max(x[1]["hi"] or [0])))[:5]:
            a_lo = int(min(ad["lo"])) if ad["lo"] else None
            a_hi = int(max(ad["hi"])) if ad["hi"] else None
            a_range = f"{a_lo}〜{a_hi}匹" if a_lo and a_hi and a_lo != a_hi else (f"{a_hi}匹" if a_hi else "—")
            area_cmp_rows += (
                f'<a class="ar" href="../area/{area_slug(aname)}.html">'
                f'<span class="ar-name">{aname}</span>'
                f'<span class="ar-range">{a_range}</span>'
                f'</a>'
            )
        area_cmp_html = f'<div class="area-cmp"><h3>エリア別の今日の釣果</h3>{area_cmp_rows}</div>' if area_cmp_rows else ""
        # ship-rank（今週・今日優先）
        ship_data_f: dict = {}
        for c in catches:
            d = ship_data_f.setdefault(c["ship"], {"cnt": 0, "cnt_his": [], "cnt_los": [], "pts": [], "today": False})
            d["cnt"] += 1
            cr = c.get("count_range")
            if cr and not cr.get("is_boat"):
                d["cnt_his"].append(cr["max"])
                d["cnt_los"].append(cr.get("min", cr["max"]))
            if c.get("point_place1"): d["pts"].append(c["point_place1"])
            if c.get("date") == today_str_f: d["today"] = True
        _sr_marks = ["◎", "◎", "○", "○", "○", "△", "△", "△"]
        sr_items = ""
        from collections import Counter as _CtrF
        for i, (sn, sd) in enumerate(sorted(ship_data_f.items(), key=lambda x: (0 if x[1]["today"] else 1, -x[1]["cnt"]))[:8]):
            mark = _sr_marks[i] if i < len(_sr_marks) else "△"
            s_lo = int(min(sd["cnt_los"])) if sd["cnt_los"] else None
            s_hi = int(max(sd["cnt_his"])) if sd["cnt_his"] else None
            s_range = f"{s_lo}〜{s_hi}匹" if s_lo and s_hi and s_lo != s_hi else (f"{s_hi}匹" if s_hi else f"{sd['cnt']}件")
            top_pt = _CtrF(sd["pts"]).most_common(1)[0][0] if sd["pts"] else ""
            sr_items += (
                f'<div class="sr"><span class="sr-m">{mark}</span>'
                f'<span class="sr-name">{sn}</span>'
                f'<span class="sr-range">{s_range}</span>'
                f'<span class="sr-pt">{top_pt}</span></div>'
            )
        ship_rank_html = f'<div class="ship-rank"><h3>船宿ランキング（今週）</h3>{sr_items}</div>' if sr_items else ""
        # 有料ティザー
        fish_teaser_html = (
            f'<h2 class="st teaser-title">{fish}が釣れる条件 <span class="tag coming">まもなく公開</span></h2>'
            f'<div class="teaser">'
            f'<div class="teaser-head"><span class="teaser-badge">開発中</span>'
            f'<span class="teaser-title-in">気象相関分析 × 日別予測</span></div>'
            f'<div class="teaser-desc"><strong>約10万件</strong>の釣果データより分析した「<strong>{fish}が釣れる条件</strong>」と<strong>明日〜1週間後の予測</strong>を公開予定です。</div>'
            f'<div style="position:relative">'
            f'<div class="teaser-dummy"><div class="td-fish">釣れる条件の傾向</div>'
            f'<div class="td-range">水温○ / 大潮○ / 波穏○</div>'
            f'<div class="td-reason">気象スコアより推定</div></div>'
            f'<div class="teaser-overlay"><div class="coming-soon-panel">'
            f'<div class="cs-title">🔒 準備中</div>'
            f'<ul class="cs-features"><li>✓ 気象条件スコア</li>'
            f'<li>✓ 来週の釣れる日予測</li>'
            f'<li>✓ 船宿別おすすめ日</li></ul>'
            f'<div class="cs-price">月額<em>500円</em> / 1回<em>100円</em></div>'
            f'</div></div></div></div>'
        )
        fish_url = f"{SITE_URL}/fish/{fish_slug(fish)}.html"
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
            '<a href="../fish/' + fish_slug(rf) + '.html" class="chip-link">' + rf + '</a>'
            for rf, _ in sorted(_rel_counts.items(), key=lambda x: -x[1])[:6]
        )
        related_section_html = (
            '<h2 class="st">同じエリアで釣れる魚</h2>'
            '<div class="chip-wrap">' + _rel_links + '</div>'
        ) if _rel_links else ""
        # エリア別釣果リンク（fish_area/）
        _fa_counts: dict = {}
        for _c in catches:
            _fa_counts[_c["area"]] = _fa_counts.get(_c["area"], 0) + 1
        _fa_links = "".join(
            '<a href="../fish_area/' + fish_slug(fish) + '-' + area_slug(a) + '.html" class="chip-link">'
            + a + f'（{c}件）</a>'
            for a, c in sorted(_fa_counts.items(), key=lambda x: -x[1])
            if c >= 5
        )
        fish_area_section_html = (
            '<h2 class="st">エリア別の釣果</h2>'
            '<div class="chip-wrap">' + _fa_links + '</div>'
        ) if _fa_links else ""
        # V2 season map / guide / FAQ / chart
        season_map_html = build_fish_season_map_html(fish, decadal_calendar)
        guide_html = build_fish_guide_html(fish, tackle_data)
        faq_html, faq_jsonld = build_fish_faq_html(fish, SITE_URL)
        chart7_html = build_fish_7day_chart_html(fish, catches)
        fish_extra_css = """\
.fish-hero{background:linear-gradient(135deg,#0d2b4a,#163d5c);color:#fff;padding:22px 14px 18px;text-align:center}
.fish-hero h2{font-size:26px;font-weight:800;margin:0}
.fish-hero .fh-r{font-size:30px;font-weight:800;color:var(--cta);margin-top:4px;line-height:1.1}
.fish-hero .fh-s{font-size:18px;font-weight:700;color:#fff;margin-top:2px}
.fish-hero .fh-m{font-size:11px;color:rgba(255,255,255,.5);margin-top:8px}
.area-cmp{background:var(--card);border:1px solid var(--border);border-radius:var(--r);padding:14px;margin-bottom:16px}
.area-cmp h3{font-size:13px;font-weight:700;color:var(--accent);margin-bottom:10px}
.ar{display:flex;align-items:center;padding:9px 0;border-bottom:1px solid var(--bg);gap:8px;text-decoration:none;color:inherit}
.ar:last-child{border-bottom:none}
.ar .ar-name{flex:0 0 85px;font-size:13px;font-weight:700;color:var(--cta)}
.ar .ar-range{flex:0 0 85px;font-size:14px;font-weight:700;color:var(--accent)}
.ship-rank{background:var(--card);border:1px solid var(--border);border-radius:var(--r);padding:14px;margin-bottom:16px}
.ship-rank h3{font-size:13px;font-weight:700;color:var(--accent);margin-bottom:10px}
.sr{display:flex;align-items:center;padding:8px 0;border-bottom:1px solid var(--bg);gap:6px}
.sr:last-child{border-bottom:none}
.sr .sr-m{font-size:14px;font-weight:800;color:var(--cta);flex:0 0 22px;text-align:center}
.sr .sr-name{flex:0 0 80px;font-size:13px;font-weight:700;color:var(--accent)}
.sr .sr-range{flex:0 0 80px;font-size:13px;font-weight:700;color:var(--cta)}
.sr .sr-pt{flex:1;font-size:10px;color:var(--muted);text-align:right}
.comment{background:var(--card);border-left:3px solid var(--cta);padding:12px;border-radius:4px;font-size:13px;margin-bottom:16px;color:var(--text)}
.season-entry{font-size:12px;color:var(--sub);margin:8px 0;padding:6px 10px;border-radius:4px;background:var(--card);border:1px solid var(--border)}
.season-entry.entry-early{border-left:3px solid var(--pos)}.season-entry.entry-late{border-left:3px solid var(--warn)}.season-entry.entry-same{border-left:3px solid var(--accent)}
.entry-trend{font-weight:bold;margin-left:6px}
.chip-wrap{display:flex;flex-wrap:wrap;gap:6px;margin:10px 0}
.chip-link{background:var(--card);border:1px solid var(--border);border-radius:16px;padding:5px 12px;font-size:12px;color:var(--accent);text-decoration:none;font-weight:600}
.chip-link:hover{background:var(--accent);color:#fff;text-decoration:none}
.chart7{background:var(--card);border:1px solid var(--border);border-radius:var(--r);padding:14px;margin-bottom:16px}
.chart7 h3{font-size:13px;font-weight:700;color:var(--accent);margin-bottom:8px}
.chart-bars{display:flex;align-items:flex-end;gap:3px;height:60px}
.chart-bars .cb{flex:1;background:var(--cta);border-radius:2px 2px 0 0;opacity:.7;min-width:10px}
.chart-bars .cb.today{opacity:1;background:var(--pos)}.chart-bars .cb.weekend{opacity:.8;background:#f4a043}
.chart-labels{display:flex;justify-content:space-between;font-size:9px;color:var(--muted);margin-top:3px}
.chart-trend{text-align:center;margin-top:6px;font-size:12px;font-weight:700;color:var(--pos)}
.chart-trend.down{color:var(--warn)}.chart-trend.flat{color:var(--sub)}"""
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
  {faq_jsonld}
  {GA_TAG}
  {ADSENSE_TAG}
  <style>{V2_COMMON_CSS}
{fish_extra_css}</style>
</head>
<body>
{_v2_header_nav('fish')}
<div class="fish-hero">
  <h2>{fish}</h2>
  {f'<div class="fh-r">{cnt_range_str}</div>' if cnt_range_str else ''}
  {f'<div class="fh-s">{sz_str}</div>' if sz_str else ''}
  <div class="fh-m">今日 {len(today_catches_f)}件・{len(set(c['ship'] for c in today_catches_f))}船宿</div>
</div>
<div class="c">
  <p class="bread"><a href="../index.html">トップ</a> &rsaquo; {fish}</p>
  {season_entry_html}
  <div class="comment">💬 {comment}</div>
  {chart7_html}
  <h2 class="st">今日の釣果 <span class="tag free">無料</span></h2>
  {area_cmp_html if area_cmp_html else '<p style="color:var(--muted);font-size:13px;padding:8px 0">本日の釣果はまだ集計中です</p>'}
  {ship_rank_html}
  <!-- 広告① -->
  <ins class="adsbygoogle" style="display:block;min-height:0" data-ad-client="ca-pub-7406401300491553" data-ad-slot="auto" data-ad-format="auto" data-full-width-responsive="true"></ins>
  <script>(adsbygoogle=window.adsbygoogle||[]).push({{}});</script>
  {related_section_html}
  {fish_area_section_html}
  <h2 class="st">旬カレンダー <span class="tag free">無料</span></h2>
  {season_map_html}
  {('<h2 class="st">魚種ガイド <span class="tag free">無料</span></h2>' + guide_html) if guide_html else ''}
  {fish_teaser_html}
  <!-- 広告② -->
  <ins class="adsbygoogle" style="display:block;min-height:0" data-ad-client="ca-pub-7406401300491553" data-ad-slot="auto" data-ad-format="auto" data-full-width-responsive="true"></ins>
  <script>(adsbygoogle=window.adsbygoogle||[]).push({{}});</script>
  <h2 class="st">よくある質問</h2>
  {faq_html}
</div>
{DATA_NOTE_HTML}
{_v2_footer(crawled_at)}
{_v2_bottom_nav('fish')}
</body></html>"""
        with open(os.path.join(WEB_DIR, f"fish/{fish_slug(fish)}.html"), "w", encoding="utf-8") as f:
            f.write(html)

    # fish/index.html: 魚種一覧
    fish_index_cards = ""
    for fish, cs in sorted(fish_summary.items(), key=lambda x: -len(x[1])):
        cnt = len(cs)
        fish_index_cards += (
            f'<a class="fi-card" href="{fish_slug(fish)}.html">'
            f'<div class="fi-name">{fish}</div>'
            f'<div class="fi-cnt">今週釣果{cnt}件</div>'
            f'</a>'
        )
    fish_index_css = """.fi-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(130px,1fr));gap:8px;margin:16px 0}
.fi-card{background:var(--card);border:1px solid var(--border);border-radius:var(--r);padding:12px;display:block;text-decoration:none;color:inherit;transition:border-color .15s}
.fi-card:hover{border-color:var(--cta);text-decoration:none}
.fi-name{font-size:14px;font-weight:700;color:var(--accent)}
.fi-cnt{font-size:11px;color:var(--muted);margin-top:4px}"""
    fish_index_html = f"""<!DOCTYPE html>
<html lang="ja"><head>
  <meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
  <title>魚種別釣果一覧 | 船釣り予想</title>
  <meta name="description" content="関東の船釣り魚種別釣果一覧。アジ・マダイ・ヒラメ・タチウオなど今週釣れている魚種をまとめて確認できます。">
  <link rel="canonical" href="{SITE_URL}/fish/">
  {GA_TAG}{ADSENSE_TAG}
  <style>{V2_COMMON_CSS}{fish_index_css}</style>
</head>
<body>
{_v2_header_nav('fish')}
<div style="background:var(--accent);color:#fff;padding:18px 14px 20px;margin-bottom:0">
  <div class="c"><div style="font-size:26px;font-weight:800">魚種別 釣果一覧</div>
  <div style="font-size:12px;opacity:.7;margin-top:4px">今週釣れている魚種 {len(fish_summary)}種</div></div>
</div>
<div class="c">
  <p class="bread"><a href="../index.html">トップ</a> &rsaquo; 魚種一覧</p>
  <h2 class="st">今週釣れている魚種</h2>
  <div class="fi-grid">{fish_index_cards}</div>
</div>
{DATA_NOTE_HTML}
{_v2_footer(crawled_at)}
{_v2_bottom_nav('fish')}
</body></html>"""
    with open(os.path.join(WEB_DIR, "fish/index.html"), "w", encoding="utf-8") as f:
        f.write(fish_index_html)

# ============================================================
# #10: エリア別ページ
# ============================================================
def build_area_pages(data, history, crawled_at="", weather_data=None):
    os.makedirs(os.path.join(WEB_DIR, "area"), exist_ok=True)
    now = datetime.now()
    today_str = now.strftime("%Y/%m/%d")
    today_iso = now.strftime("%Y-%m-%d")
    area_desc_data = load_area_description()
    area_decadal = load_area_decadal()
    area_summary = {}
    for c in data:
        area_summary.setdefault(c["area"], []).append(c)

    area_extra_css = """\
.area-hero{background:linear-gradient(135deg,#0d2b4a,#163d5c);color:#fff;padding:22px 14px 18px;text-align:center}
.area-hero h2{font-size:26px;font-weight:800;margin:0}
.area-hero .ah-sub{font-size:12px;color:rgba(255,255,255,.6);margin-top:2px}
.area-hero .ah-m{font-size:20px;font-weight:800;color:var(--cta);margin-top:8px}
.area-hero .ah-m small{font-size:12px;color:rgba(255,255,255,.6);font-weight:400}
.area-hero .ah-sea{font-size:11px;color:rgba(255,255,255,.5);margin-top:6px}
.fia-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:8px;margin-bottom:16px}
.fia{background:var(--card);border:1px solid var(--border);border-radius:var(--r);padding:10px;display:block;text-decoration:none;color:inherit}
.fia:hover{border-color:var(--cta);text-decoration:none}
.fia .fn{font-size:14px;font-weight:800;color:var(--accent)}
.fia .fr{font-size:17px;font-weight:800;color:var(--cta);margin-top:2px;line-height:1.2}
.fia .fs{font-size:10px;color:var(--muted);margin-top:2px}
.fia .fb{font-size:10px;color:var(--pos);font-weight:600;margin-top:3px}
.sea-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-bottom:16px}
.sea-item{background:var(--card);border:1px solid var(--border);border-radius:var(--r);padding:12px 8px;text-align:center}
.sea-item .sv{font-size:18px;font-weight:800;color:var(--accent)}
.sea-item .sl2{font-size:10px;color:var(--muted);margin-top:2px}
.sl-card{background:var(--card);border:1px solid var(--border);border-radius:var(--r);padding:14px;margin-bottom:16px}
.sl-item{padding:10px 0;border-bottom:1px solid var(--bg)}
.sl-item:last-child{border-bottom:none}
.sl-top{display:flex;justify-content:space-between;align-items:baseline;gap:8px;flex-wrap:wrap}
.sl-name{font-size:14px;font-weight:800;color:var(--accent)}
.sl-fish{display:flex;gap:4px;flex-wrap:wrap}
.sl-fish span{font-size:10px;padding:2px 6px;border-radius:8px;font-weight:700}
.sl-fish .g{background:#e6f7ee;color:var(--pos)}
.sl-fish .o{background:#fef6ee;color:var(--cta)}
.sl-detail{font-size:11px;color:var(--muted);margin-top:3px}
.point-box{background:var(--card);border:1px solid var(--border);border-radius:var(--r);padding:14px;margin-bottom:16px}
.point-box h3{font-size:13px;font-weight:700;color:var(--accent);margin-bottom:10px}
.point-list{display:flex;flex-wrap:wrap;gap:6px}
.point-list a{font-size:12px;padding:5px 12px;background:var(--bg);border:1px solid var(--border);border-radius:14px;color:var(--sub);font-weight:600;text-decoration:none}
.point-list a:hover{background:var(--accent);color:#fff;border-color:var(--accent);text-decoration:none}
.point-hidden{display:inline-block;font-size:11px;padding:5px 12px;background:#f8f4ff;border:1px dashed var(--prem);border-radius:14px;color:var(--prem);font-weight:700}
.related{background:var(--card);border:1px solid var(--border);border-radius:var(--r);padding:14px;margin-bottom:16px}
.related h3{font-size:13px;font-weight:700;color:var(--accent);margin-bottom:8px}
.related .rl{display:flex;flex-wrap:wrap;gap:6px}
.related .rl a{font-size:12px;padding:4px 10px;background:var(--bg);border-radius:12px;color:var(--sub);font-weight:600;text-decoration:none}
.related .rl a:hover{background:var(--accent);color:#fff;text-decoration:none}"""

    for area, catches in area_summary.items():
        if len(catches) < 2:
            continue

        group = next((g for g, areas in AREA_GROUPS.items() if area in areas), "関東")

        # 今日の釣果
        today_catches = [c for c in catches if c.get("date") == today_str]
        use_today = len(today_catches) >= 1
        fish_source = today_catches if use_today else catches
        fish_label = "今日" if use_today else "今週"

        # 魚種別集計（fia-grid用）
        fish_data = {}
        for c in fish_source:
            for f in c["fish"]:
                if f in ("不明", "欠航"):
                    continue
                d = fish_data.setdefault(f, {"cnt_mins": [], "cnt_maxs": [], "sz_mins": [], "sz_maxs": [], "ships": set(), "records": 0, "ship_recs": {}})
                d["records"] += 1
                d["ships"].add(c["ship"])
                d["ship_recs"][c["ship"]] = d["ship_recs"].get(c["ship"], 0) + 1
                if c.get("cnt_min") is not None: d["cnt_mins"].append(c["cnt_min"])
                if c.get("cnt_max") is not None: d["cnt_maxs"].append(c["cnt_max"])
                if c.get("size_min") is not None: d["sz_mins"].append(c["size_min"])
                if c.get("size_max") is not None: d["sz_maxs"].append(c["size_max"])

        top_fish_items = sorted(fish_data.items(), key=lambda x: -x[1]["records"])[:6]

        fia_cards = ""
        for fish, fd in top_fish_items:
            cnt_lo = int(min(fd["cnt_mins"])) if fd["cnt_mins"] else None
            cnt_hi = int(max(fd["cnt_maxs"])) if fd["cnt_maxs"] else None
            if cnt_lo is not None and cnt_hi is not None and cnt_lo != cnt_hi:
                cnt_str = f"{cnt_lo}〜{cnt_hi}匹"
            elif cnt_hi is not None:
                cnt_str = f"{cnt_hi}匹"
            elif cnt_lo is not None:
                cnt_str = f"{cnt_lo}匹"
            else:
                cnt_str = ""
            sz_lo = int(min(fd["sz_mins"])) if fd["sz_mins"] else None
            sz_hi = int(max(fd["sz_maxs"])) if fd["sz_maxs"] else None
            sz_str = f"{sz_lo}〜{sz_hi}cm" if sz_lo and sz_hi else (f"〜{sz_hi}cm" if sz_hi else "")
            detail_parts = []
            if sz_str: detail_parts.append(sz_str)
            detail_parts.append(f"{fd['records']}件・{len(fd['ships'])}船宿")
            best_ship = max(fd["ship_recs"].items(), key=lambda x: x[1])[0] if fd["ship_recs"] else ""
            fia_cards += (
                f'<a class="fia" href="../fish/{fish_slug(fish)}.html">'
                f'<div class="fn">{fish}</div>'
                + (f'<div class="fr">{cnt_str}</div>' if cnt_str else "")
                + f'<div class="fs">{" | ".join(detail_parts)}</div>'
                + (f'<div class="fb">◎{best_ship}</div>' if best_ship else "")
                + '</a>'
            )

        # 海況データ
        sea_fc = {}
        if weather_data:
            sea_fc = weather_data.get("forecast", {}).get((group, today_iso), {})
        sst = sea_fc.get("sst")
        wave = sea_fc.get("wave_height")
        wind_spd = sea_fc.get("wind_speed")
        wind_dir = sea_fc.get("wind_dir")
        pressure = sea_fc.get("pressure")
        tide_range = sea_fc.get("tide_range", "")
        moon_age = sea_fc.get("moon_age")
        sst_str = f"{sst:.1f}℃" if sst else "—"
        wave_str = f"{wave:.1f}m" if wave else "—"
        wind_txt = (_wind_dir_text(wind_dir) if wind_dir else "") + (f"{wind_spd:.1f}m/s" if wind_spd else "")
        wind_str = wind_txt if wind_txt else "—"
        tide_str = tide_range if tide_range else "—"
        moon_str = f"{moon_age:.1f}" if moon_age is not None else "—"
        pressure_str = f"{int(pressure)}hPa" if pressure else "—"
        # ヒーローの海況テキスト
        sea_parts = []
        if sst: sea_parts.append(f"水温{sst_str}")
        if wave: sea_parts.append(f"波{wave_str}")
        if wind_txt: sea_parts.append(wind_str)
        if tide_range: sea_parts.append(str(tide_range))
        ah_sea_html = f'<div class="ah-sea">{" / ".join(sea_parts)}</div>' if sea_parts else ""
        sea_section_html = ""
        if sea_fc:
            sea_section_html = (
                f'<h2 class="st">海況データ <span class="tag free">無料</span></h2>'
                f'<div class="sea-grid">'
                f'<div class="sea-item"><div class="sv">{sst_str}</div><div class="sl2">水温</div></div>'
                f'<div class="sea-item"><div class="sv">{wave_str}</div><div class="sl2">波高</div></div>'
                f'<div class="sea-item"><div class="sv">{wind_str}</div><div class="sl2">風</div></div>'
                f'<div class="sea-item"><div class="sv">{tide_str}</div><div class="sl2">潮汐</div></div>'
                f'<div class="sea-item"><div class="sv">{moon_str}</div><div class="sl2">月齢</div></div>'
                f'<div class="sea-item"><div class="sv">{pressure_str}</div><div class="sl2">気圧</div></div>'
                f'</div>'
            )

        # 船宿リスト（sl-card）
        ship_week_fish = {}
        ship_today_set = set(c["ship"] for c in today_catches)
        for c in catches:
            for f in c["fish"]:
                if f not in ("不明", "欠航"):
                    ship_week_fish.setdefault(c["ship"], {}).setdefault(f, 0)
                    ship_week_fish[c["ship"]][f] += 1
        sorted_ships = sorted(ship_week_fish.keys(), key=lambda s: (0 if s in ship_today_set else 1, -sum(ship_week_fish[s].values())))[:8]
        ship_items_html = ""
        for sn in sorted_ships:
            fish_dict = ship_week_fish[sn]
            top_f = sorted(fish_dict.items(), key=lambda x: -x[1])[:3]
            badges = "".join(f'<span class="{"g" if i == 0 else "o"}">{f}</span>' for i, (f, _) in enumerate(top_f))
            pts = [c["point_place1"] for c in catches if c["ship"] == sn and c.get("point_place1")]
            from collections import Counter as _Counter
            top_pt = _Counter(pts).most_common(1)[0][0] if pts else ""
            ship_items_html += (
                f'<div class="sl-item">'
                f'<div class="sl-top"><span class="sl-name">{sn}</span>'
                f'<div class="sl-fish">{badges}</div></div>'
                + (f'<div class="sl-detail">{top_pt}</div>' if top_pt else "")
                + '</div>'
            )

        # ポイントTOP3
        all_pts = []
        for c in catches:
            for k in ("point_place1", "point_place2", "point_place3"):
                p = c.get(k)
                if p and p.strip():
                    all_pts.append(p.strip())
        from collections import Counter as _Counter2
        top_pts = [p for p, _ in _Counter2(all_pts).most_common(3) if p]
        total_pts = len(set(all_pts))
        point_box_html = ""
        if top_pts:
            pt_links = "".join(f'<a href="#">{p}</a>' for p in top_pts)
            more = total_pts - len(top_pts)
            hidden = f'<span class="point-hidden">＋{more}ポイント（有料プランで公開）</span>' if more > 0 else ""
            point_box_html = (
                f'<div class="point-box"><h3>主要ポイント（TOP3）</h3>'
                f'<div class="point-list">{pt_links}{hidden}</div></div>'
            )

        # 近隣エリア（related card）
        _group_areas = AREA_GROUPS.get(group, [])
        _nearby_links = "".join(
            f'<a href="../area/{area_slug(a)}.html">{a}</a>'
            for a in _group_areas if a != area and a in area_summary
        )
        nearby_section_html = (
            f'<div class="related"><h3>近隣エリア</h3>'
            f'<div class="rl">{_nearby_links}</div></div>'
        ) if _nearby_links else ""

        # 既存セクション（旬カレンダー・ガイド・FAQ）
        top_fish_list = [f for f, _ in top_fish_items]
        area_season_html = build_area_season_map_html(area, area_decadal, top_fish_list)
        area_guide_html = build_area_guide_html(area, area_desc_data)
        area_faq_html, area_faq_jsonld = build_area_faq_html(area, area_desc_data)

        # SEO
        area_url = f"{SITE_URL}/area/{area_slug(area)}.html"
        _top_fish_str = "・".join(f for f, _ in top_fish_items[:3])
        _area_desc_fish = f"{_top_fish_str}など" if _top_fish_str else ""
        today_cnt = len(today_catches)
        area_desc = f"{area}（{group}）の船釣り釣果。今日{today_cnt}件。{_area_desc_fish}釣れている魚種と船宿情報を毎日更新。"

        # 有料ティザー
        area_teaser_html = (
            f'<h2 class="st teaser-title">このエリアの予測・分析 <span class="tag coming">まもなく公開</span></h2>'
            f'<div class="teaser">'
            f'<div class="teaser-head"><span class="teaser-badge">開発中</span>'
            f'<span class="teaser-title-in">エリア別 日別予測・全ポイント情報</span></div>'
            f'<div class="teaser-desc"><strong>{area}</strong>の明日〜1週間後の魚種別予測、'
            f'<strong>全ポイント一覧</strong>、海況相関の詳細分析を提供します。</div>'
            f'<div style="position:relative">'
            f'<div class="teaser-dummy"><div class="td-fish">{area} 予測</div>'
            f'<div class="td-range">{top_fish_list[0] if top_fish_list else "—"} ★★★★☆</div>'
            f'<div class="td-reason">潮汐・SST・前週実績より推定</div></div>'
            f'<div class="teaser-overlay"><div class="coming-soon-panel">'
            f'<div class="cs-title">🔒 準備中</div>'
            f'<ul class="cs-features"><li>✓ エリア別日別予測（7日先）</li>'
            f'<li>✓ 全ポイント情報</li><li>✓ 欠航リスク予報</li></ul>'
            f'<div class="cs-price">月額<em>500円</em> / 1回<em>100円</em></div>'
            f'</div></div></div></div>'
        )

        html = f"""<!DOCTYPE html>
<html lang="ja"><head>
  <meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
  <title>{area}の釣果情報・おすすめ船宿【今日{today_cnt}件】| 船釣り予想</title>
  <meta name="description" content="{area_desc}">
  <link rel="canonical" href="{area_url}">
  <meta property="og:title" content="{area}の釣果情報・おすすめ船宿【今日{today_cnt}件】">
  <meta property="og:description" content="{area_desc}">
  <meta property="og:url" content="{area_url}">
  <meta property="og:type" content="website">
  <meta property="og:site_name" content="船釣り予想">
  <script type="application/ld+json">{{"@context":"https://schema.org","@type":"BreadcrumbList","itemListElement":[{{"@type":"ListItem","position":1,"name":"トップ","item":"{SITE_URL}/"}},{{"@type":"ListItem","position":2,"name":"{group}","item":"{SITE_URL}/"}},{{"@type":"ListItem","position":3,"name":"{area}の釣果","item":"{area_url}"}}]}}</script>
  {area_faq_jsonld}
  {GA_TAG}
  {ADSENSE_TAG}
  <style>{V2_COMMON_CSS}
{area_extra_css}</style>
</head>
<body>
{_v2_header_nav('area')}
<div class="area-hero">
  <div class="c">
    <h2>{area}</h2>
    <div class="ah-sub">{group}</div>
    <div class="ah-m">{today_cnt}件 <small>({len(set(c['ship'] for c in today_catches))}船宿・今日)</small></div>
    {ah_sea_html}
  </div>
</div>
<div class="c">
  <p class="bread"><a href="../index.html">トップ</a> &rsaquo; <a href="../area/">エリア一覧</a> &rsaquo; {area}</p>
  <h2 class="st">このエリアで{fish_label}釣れている魚 <span class="tag free">無料</span></h2>
  <div class="fia-grid">{fia_cards if fia_cards else '<p style="color:var(--muted);font-size:13px">本日の釣果はまだ集計中です</p>'}</div>
  {sea_section_html}
  <!-- 広告① -->
  <ins class="adsbygoogle" style="display:block;min-height:0" data-ad-client="ca-pub-7406401300491553" data-ad-slot="auto" data-ad-format="auto" data-full-width-responsive="true"></ins>
  <script>(adsbygoogle=window.adsbygoogle||[]).push({{}});</script>
  <h2 class="st">船宿一覧 <span class="tag free">無料</span></h2>
  <div class="sl-card">{ship_items_html}</div>
  {point_box_html}
  {area_teaser_html}
  {nearby_section_html}
  <h2 class="st">魚種別 旬カレンダー <span class="tag free">無料</span></h2>
  {area_season_html}
  {('<h2 class="st">エリアガイド</h2>' + area_guide_html) if area_guide_html else ''}
  <!-- 広告② -->
  <ins class="adsbygoogle" style="display:block;min-height:0" data-ad-client="ca-pub-7406401300491553" data-ad-slot="auto" data-ad-format="auto" data-full-width-responsive="true"></ins>
  <script>(adsbygoogle=window.adsbygoogle||[]).push({{}});</script>
  <h2 class="st">よくある質問</h2>
  {area_faq_html}
</div>
{DATA_NOTE_HTML}
{_v2_footer(crawled_at)}
{_v2_bottom_nav('area')}
</body></html>"""
        with open(os.path.join(WEB_DIR, f"area/{area_slug(area)}.html"), "w", encoding="utf-8") as f:
            f.write(html)

    # area/index.html: エリア一覧（グループ別）
    _group_order = ["茨城", "千葉・外房", "千葉・内房", "千葉・東京湾奥", "東京", "神奈川・東京湾", "神奈川・相模湾", "静岡"]
    area_index_sections = ""
    for grp in _group_order:
        grp_areas = [(area, catches) for area, catches in area_summary.items()
                     if area in AREA_GROUPS.get(grp, []) and len(catches) >= 2]
        if not grp_areas: continue
        cards = ""
        for area, catches in sorted(grp_areas, key=lambda x: -len(x[1])):
            top_f = sorted({f for c in catches for f in c["fish"] if f != "不明"},
                           key=lambda f: -sum(1 for c in catches if f in c["fish"]))[:3]
            cards += (
                f'<a class="ai-card" href="{area_slug(area)}.html">'
                f'<div class="ai-name">{area}</div>'
                f'<div class="ai-fish">{"・".join(top_f)}</div>'
                f'<div class="ai-cnt">今週釣果{len(catches)}件</div>'
                f'</a>'
            )
        area_index_sections += f'<h2 class="st">{grp}</h2><div class="ai-grid">{cards}</div>'
    # 未分類エリア
    _matched = {a for areas in AREA_GROUPS.values() for a in areas}
    _other = [(area, catches) for area, catches in area_summary.items()
              if area not in _matched and len(catches) >= 2]
    if _other:
        cards = ""
        for area, catches in sorted(_other, key=lambda x: -len(x[1])):
            top_f = sorted({f for c in catches for f in c["fish"] if f != "不明"},
                           key=lambda f: -sum(1 for c in catches if f in c["fish"]))[:3]
            cards += (
                f'<a class="ai-card" href="{area_slug(area)}.html">'
                f'<div class="ai-name">{area}</div>'
                f'<div class="ai-fish">{"・".join(top_f)}</div>'
                f'<div class="ai-cnt">今週釣果{len(catches)}件</div>'
                f'</a>'
            )
        area_index_sections += f'<h2 class="st">その他</h2><div class="ai-grid">{cards}</div>'

    area_index_css = """.ai-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:8px;margin:12px 0 20px}
.ai-card{background:var(--card);border:1px solid var(--border);border-radius:var(--r);padding:12px;display:block;text-decoration:none;color:inherit;transition:border-color .15s}
.ai-card:hover{border-color:var(--cta);text-decoration:none}
.ai-name{font-size:14px;font-weight:700;color:var(--accent)}
.ai-fish{font-size:11px;color:var(--sub);margin-top:4px}
.ai-cnt{font-size:11px;color:var(--cta);font-weight:600;margin-top:4px}"""
    area_index_html = f"""<!DOCTYPE html>
<html lang="ja"><head>
  <meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
  <title>エリア別釣果一覧 | 船釣り予想</title>
  <meta name="description" content="関東の船釣りエリア別釣果一覧。茨城・千葉・東京・神奈川エリアの今週の釣果件数と釣れている魚種を確認できます。">
  <link rel="canonical" href="{SITE_URL}/area/">
  {GA_TAG}{ADSENSE_TAG}
  <style>{V2_COMMON_CSS}{area_index_css}</style>
</head>
<body>
{_v2_header_nav('area')}
<div style="background:var(--accent);color:#fff;padding:18px 14px 20px;margin-bottom:0">
  <div class="c"><div style="font-size:26px;font-weight:800">エリア別 釣果一覧</div>
  <div style="font-size:12px;opacity:.7;margin-top:4px">今週釣果あり {len([a for a,cs in area_summary.items() if len(cs)>=2])}エリア</div></div>
</div>
<div class="c">
  <p class="bread"><a href="../index.html">トップ</a> &rsaquo; エリア一覧</p>
  {area_index_sections}
</div>
{DATA_NOTE_HTML}
{_v2_footer(crawled_at)}
{_v2_bottom_nav('area')}
</body></html>"""
    with open(os.path.join(WEB_DIR, "area/index.html"), "w", encoding="utf-8") as f:
        f.write(area_index_html)

# ============================================================
# #11: 魚種×港ページ（fish_area/）
# ============================================================
def build_fish_area_pages(data, crawled_at="", history=None):
    os.makedirs(os.path.join(WEB_DIR, "fish_area"), exist_ok=True)
    fa_summary: dict = {}
    for c in data:
        for f in c["fish"]:
            if f != "不明":
                fa_summary.setdefault((f, c["area"]), []).append(c)

    fa_extra_css = """\
.combo-comment{background:var(--card);border-left:3px solid var(--cta);padding:12px;border-radius:4px;font-size:13px;margin-bottom:16px;color:var(--text)}
.stat-card.trend-up{border-color:var(--pos)}.stat-card.trend-down{border-color:var(--neg)}
.sl-card{background:var(--card);border:1px solid var(--border);border-radius:var(--r);padding:12px;margin-bottom:8px}
.sl-head{display:flex;justify-content:space-between;align-items:center;margin-bottom:4px}
.sl-name{font-size:14px;font-weight:700;color:var(--accent)}
.sl-date{font-size:11px;color:var(--muted)}
.sl-sub{font-size:12px;color:var(--sub)}
.ship-rank{background:var(--card);border:1px solid var(--border);border-radius:var(--r);padding:14px;margin-bottom:16px}
.ship-rank h3{font-size:13px;font-weight:700;color:var(--accent);margin-bottom:10px}
.sr{display:flex;align-items:center;padding:8px 0;border-bottom:1px solid var(--bg);gap:6px}
.sr:last-child{border-bottom:none}
.sr .sr-m{font-size:14px;font-weight:800;color:var(--cta);flex:0 0 22px;text-align:center}
.sr .sr-name{flex:0 0 80px;font-size:13px;font-weight:700;color:var(--accent)}
.sr .sr-range{flex:0 0 80px;font-size:13px;font-weight:700;color:var(--cta)}
.sr .sr-pt{flex:1;font-size:10px;color:var(--muted);text-align:right}"""

    now_fa_global = datetime.now()
    current_month_fa = now_fa_global.month
    year_fa_g, week_num_fa_g = current_iso_week()

    count = 0
    for (fish, area), catches in fa_summary.items():
        if len(catches) < 5:
            continue
        max_cnt = 0
        personal_catches = []
        for c in catches:
            cr = c.get("count_range")
            if cr and not cr.get("is_boat"):
                max_cnt = max(max_cnt, cr["max"])
                personal_catches.append(c)
        # コンボ統計
        combo_avg = 0
        if personal_catches:
            avgs = [(c["count_range"]["min"] + c["count_range"]["max"]) // 2 for c in personal_catches]
            combo_avg = round(sum(avgs) / len(avgs), 1)
        ship_num = len(set(c["ship"] for c in catches))
        # トレンド判定
        this_w_fa, last_w_fa = get_yoy_data(history, fish, year_fa_g, week_num_fa_g) if history else (None, None)
        prev_w_fa = get_prev_week_data(history, fish, year_fa_g, week_num_fa_g) if history else None
        trend_fa = ""
        if this_w_fa and prev_w_fa:
            t_s = this_w_fa.get("ships") or 0
            p_s = prev_w_fa.get("ships") or 0
            if t_s and p_s:
                r = t_s / p_s
                if r > 1.2: trend_fa = "up"
                elif r < 0.8: trend_fa = "down"
                else: trend_fa = "flat"
        trend_cls = {"up": " trend-up", "down": " trend-down"}.get(trend_fa, "")
        trend_label = {"up": "↑ 上昇中", "down": "↓ 減少", "flat": "→ 横ばい"}.get(trend_fa, "-")
        stat_cards_fa = f"""<div class="stat-cards">
  <div class="stat-card"><div class="sv">{ship_num}船宿</div><div class="sl">出船船宿数</div></div>
  <div class="stat-card"><div class="sv">{'%.0f' % combo_avg if combo_avg else '-'}匹</div><div class="sl">平均釣果</div></div>
  <div class="stat-card{trend_cls}"><div class="sv">{max_cnt if max_cnt else '-'}匹</div><div class="sl">最高釣果</div></div>
</div>"""
        # シーズンバー
        season_bar_fa = build_season_bar(fish, current_month_fa)
        # コンボコメント
        season_score_fa = get_season_score(fish, current_month_fa)
        group_fa = _area_to_group(area) or area
        if season_score_fa >= 4:
            combo_cmt = f"💬 {group_fa}の{fish}は今月がシーズン本番。{trend_label}の傾向です。"
        elif season_score_fa >= 3:
            combo_cmt = f"💬 {group_fa}の{fish}はシーズン中盤。安定した釣果が期待できます。"
        elif season_score_fa >= 2:
            combo_cmt = f"💬 {group_fa}の{fish}はシーズンの立ち上がり／終盤。{trend_label}の傾向。"
        else:
            combo_cmt = f"💬 {group_fa}の{fish}はオフシーズンですが釣果報告あり。"
        combo_comment_html = f'<div class="combo-comment">{combo_cmt}</div>'
        # V2: ship-rank（sr スタイル）
        today_str_fa = now_fa_global.strftime("%Y/%m/%d")
        ship_data_fa: dict = {}
        for c in catches:
            d = ship_data_fa.setdefault(c["ship"], {"cnt": 0, "max": 0, "today": False})
            d["cnt"] += 1
            cr = c.get("count_range")
            if cr and not cr.get("is_boat"):
                d["max"] = max(d["max"], cr["max"])
            if c.get("date") == today_str_fa:
                d["today"] = True
        _sr_marks_fa = ["◎", "◎", "○", "○", "○", "△", "△", "△"]
        sr_items_fa = ""
        for i, (sn, sd) in enumerate(sorted(ship_data_fa.items(), key=lambda x: (0 if x[1]["today"] else 1, -x[1]["cnt"]))[:8]):
            mark = _sr_marks_fa[i] if i < len(_sr_marks_fa) else "△"
            mx = sd["max"]
            s_range = f"最高{mx}匹" if mx else f"{sd['cnt']}件"
            sr_items_fa += (
                f'<div class="sr"><span class="sr-m">{mark}</span>'
                f'<span class="sr-name">{sn}</span>'
                f'<span class="sr-range">{s_range}</span>'
                f'<span class="sr-pt">{sd["cnt"]}件</span></div>'
            )
        ship_rank_fa_html = f'<div class="ship-rank"><h3>船宿ランキング（今週）</h3>{sr_items_fa}</div>' if sr_items_fa else ""
        # V2: 最近の釣果（sl-card スタイル）
        recent_cards_fa = ""
        for c in sorted(catches, key=lambda x: x.get("date") or "", reverse=True)[:10]:
            cnt_str = fmt_count(c)
            sz_cm = fmt_size_cm(c)
            sub = " / ".join(filter(None, [cnt_str, sz_cm]))
            recent_cards_fa += (
                f'<div class="sl-card">'
                f'<div class="sl-head"><span class="sl-name">{c["ship"]}</span>'
                f'<span class="sl-date">{(c.get("date") or "")[-5:]}</span></div>'
                f'<div class="sl-sub">{sub if sub else "釣果あり"}</div>'
                f'</div>'
            )
        page_url = f"{SITE_URL}/fish_area/{fish_slug(fish)}-{area_slug(area)}.html"
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
  <script type="application/ld+json">{{"@context":"https://schema.org","@type":"BreadcrumbList","itemListElement":[{{"@type":"ListItem","position":1,"name":"トップ","item":"{SITE_URL}/"}},{{"@type":"ListItem","position":2,"name":"{fish}の釣果","item":"{SITE_URL}/fish/{fish_slug(fish)}.html"}},{{"@type":"ListItem","position":3,"name":"{area}の{fish}釣果","item":"{page_url}"}}]}}</script>
  {GA_TAG}
  {ADSENSE_TAG}
  <style>{V2_COMMON_CSS}
{fa_extra_css}</style>
</head>
<body>
{_v2_header_nav('')}
<div class="c">
  <p class="bread"><a href="../index.html">トップ</a> &rsaquo; <a href="../fish/{fish_slug(fish)}.html">{fish}</a> &rsaquo; {area}</p>
  <h2 class="st">{area}の{fish}釣果情報</h2>
  {stat_cards_fa}
  <h2 class="st">年間シーズン <span class="tag free">無料</span></h2>{season_bar_fa}
  {combo_comment_html}
  <h2 class="st">船宿ランキング <span class="tag free">無料</span></h2>
  {ship_rank_fa_html}
  <h2 class="st">最近の釣果 <span class="tag free">無料</span></h2>
  {recent_cards_fa}
</div>
{DATA_NOTE_HTML}
{_v2_footer(crawled_at)}
{_v2_bottom_nav('')}
</body></html>"""
        with open(os.path.join(WEB_DIR, f"fish_area/{fish_slug(fish)}-{area_slug(area)}.html"), "w", encoding="utf-8") as fp:
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
        rows += f"<tr><td class='fish-name'><a href='fish/{fish_slug(fish)}.html'>{fish}</a></td>{cells}</tr>"
    cal_extra_css = """.cal-wrap{overflow-x:auto;-webkit-overflow-scrolling:touch;margin-bottom:16px}
.cal-wrap table{font-size:12px;min-width:600px}
.cal-wrap th{text-align:center;min-width:34px;font-size:11px;padding:6px 4px}
.cal-wrap th.cur-month{background:var(--cta);color:#fff}
.cal-wrap td{text-align:center;padding:5px 3px;border-bottom:1px solid var(--border)}
.cal-wrap td.fish-name{text-align:left;font-weight:700;min-width:80px;padding-left:4px;white-space:nowrap}
.cal-wrap td.fish-name a{color:var(--text)}
.cal-wrap td.fish-name a:hover{color:var(--cta)}
.cal-wrap td.peak-count{background:#fde8d4;color:#b84500;font-weight:700}
.cal-wrap td.peak-size{background:#ece5fd;color:#6d28d9;font-weight:700}
.cal-wrap td.mid{background:#dfe8f4;color:#2c6ea8}
.cal-wrap td.low{color:var(--muted)}
.cal-wrap td.cur-month{outline:2px solid var(--cta);outline-offset:-2px}
.legend{display:flex;gap:12px;flex-wrap:wrap;margin:12px 0 16px;font-size:11px;color:var(--sub)}
.leg{display:flex;align-items:center;gap:5px}
.leg-dot{width:12px;height:12px;border-radius:2px}"""
    return f"""<!DOCTYPE html>
<html lang="ja"><head>
  <meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
  <title>関東船釣り 旬カレンダー | 月別釣りものガイド | 船釣り予想</title>
  <meta name="description" content="関東エリアの船釣り旬カレンダー。アジ・マダイ・タチウオ・ヒラメなど50魚種以上の月別シーズン表。数釣り・型釣りのピーク月が一目でわかる。">
  <link rel="canonical" href="{SITE_URL}/calendar.html">
  {GA_TAG}
  {ADSENSE_TAG}
  <style>{V2_COMMON_CSS}
{cal_extra_css}</style>
</head>
<body>
{_v2_header_nav('calendar')}
<div class="c">
  <p class="bread"><a href="index.html">トップ</a> &rsaquo; 旬カレンダー</p>
  <h2 class="st">月別 釣りものカレンダー <span class="tag free">無料</span></h2>
  <div class="legend">
    <div class="leg"><div class="leg-dot" style="background:#fde8d4;border:1px solid #b84500"></div>数釣りピーク◎</div>
    <div class="leg"><div class="leg-dot" style="background:#ece5fd;border:1px solid #6d28d9"></div>型釣りピーク◎</div>
    <div class="leg"><div class="leg-dot" style="background:#dfe8f4;border:1px solid #2c6ea8"></div>シーズン中○</div>
    <div class="leg"><div class="leg-dot" style="background:var(--border)"></div>端境期</div>
  </div>
  <div class="cal-wrap tbl-wrap"><table><tr><th>魚種</th>{header_cells}</tr>{rows}</table></div>
</div>
{DATA_NOTE_HTML}
{_v2_footer(crawled_at)}
{_v2_bottom_nav('cal')}
</body></html>"""

# ============================================================
# Layer 2: catches_raw.json → data/YYYY-MM.csv 変換
# ============================================================

# tsuri_mono_map_draft.json から58種MAPを動的ロード
_tmap_path = os.path.join(os.path.dirname(__file__), "normalize", "tsuri_mono_map_draft.json")
with open(_tmap_path, encoding="utf-8") as _f:
    _tmap_data = json.load(_f)
TSURI_MONO_MAP = {
    k: v for k, v in _tmap_data["TSURI_MONO_MAP"].items()
    if isinstance(v, list) and not k.startswith("_")
}

# 船宿別イカ特例: fish_raw="イカ" の場合に船宿で判別
SHIP_IKA_RULES = {
    "吉久":       "スミイカ",
    "ちがさき丸": "ヤリイカ",
    "山下丸":     "スミイカ",
}

# 船宿別五目特例: fish_raw が五目系汎用表記の場合に船宿で判別
SHIP_GOMOKU_RULES = {
    "啓秀丸":       "タイ五目",
    "大洗丸":       "タイ五目",
    "大盛丸":       "タイ五目",
    "庄治郎丸":     "タイ五目",
    "なごみ丸":     "イサキ",
    "ちがさき丸":   "タイ五目",
    "あまさけや丸": "タイ五目",
    "弘漁丸":       "ヒラメ",
    "こなや丸":     "サワラ",
    "林遊船":       "サワラ",
}


def normalize_tsuri_mono(raw, ship=""):
    """釣りもの生テキスト → 正規化名（58種MAP）。マッチしなければ空文字を返す"""
    if not raw:
        return ""
    # D2: 数字のみの場合はノイズ（HTMLパース失敗による列ズレ）
    if raw.isdigit():
        return ""
    # 船宿別イカ特例
    if raw == "イカ" and ship in SHIP_IKA_RULES:
        return SHIP_IKA_RULES[ship]
    # 船宿別五目特例（汎用五目系表記）
    _gomoku_keys = ("五目", "LT五目", "タイ五目", "イナダ五目", "イサキ五目", "根魚五目", "青物")
    if any(k in raw for k in _gomoku_keys) and ship in SHIP_GOMOKU_RULES:
        return SHIP_GOMOKU_RULES[ship]
    # 通常マッチ（58種MAP）: 優先順位を厳密に
    # 1. キー完全一致（例: raw="アマダイ" → TSURI_MONO_MAP["アマダイ"]）
    if raw in TSURI_MONO_MAP:
        return raw
    # 2. パターン完全一致（例: raw="LTアマダイ" → patterns["アマダイ"]に"LTアマダイ"あり）
    for tsuri_mono, patterns in TSURI_MONO_MAP.items():
        if raw in patterns:
            return tsuri_mono
    # 3. パターンがrawに含まれる（例: raw="大マダイ" → "マダイ" in "大マダイ"）
    #    ※ raw in p（逆方向）は使わない → アマダイ→マダイ等の誤分類を防ぐ
    for tsuri_mono, patterns in TSURI_MONO_MAP.items():
        if any(p in raw for p in patterns):
            return tsuri_mono
    return ""


def _extract_tsuri_mono(r, same_trip_records, ship):
    """釣りもの名を導出（優先順: ①感想先頭ワード→MAP正規化 ②同一trip最初のfish_raw→MAP正規化）"""
    comment = r.get("kanso_raw") or ""
    # ① kanso_raw 先頭ワード（出番番号を除く）→ normalize
    m = re.match(r'(?:[■□]?\d+\s+)?([^\s。、・]{2,12})[\s。、・]', comment.strip())
    if m:
        c = m.group(1)
        if not re.match(r'^(他に|本日|今日|釣果|合計|出船)', c):
            norm = normalize_tsuri_mono(c, ship)
            if norm:
                return norm
    # ② 同一trip内のfish_rawを順に試す → normalize
    for rec in same_trip_records:
        fw = rec.get("fish_raw", "")
        if fw:
            norm = normalize_tsuri_mono(fw, ship)
            if norm:
                return norm
    return ""


def _classify_main_sub(fish_raw, tsuri_mono):
    """メイン/サブを判定。fish_rawがtsuri_monoのMAPリストに含まれるかで判定"""
    if not tsuri_mono or not fish_raw:
        return "メイン"
    if "五目" in tsuri_mono:
        return "メイン"
    target_list = TSURI_MONO_MAP.get(tsuri_mono, [])
    for pattern in target_list:
        if pattern in fish_raw or fish_raw in pattern:
            return "メイン"
    return "サブ"


def _extract_water_temp_range(text):
    """水温テキストから {min, max} を返す。例: "15〜17℃"→{min:15,max:17}, "18℃"→{min:18,max:18}"""
    text = text.translate(Z2H)
    m = re.search(r'(\d+(?:\.\d+)?)(?:[~〜](\d+(?:\.\d+)?))?\s*[℃度]', text)
    if not m:
        return {}
    lo = float(m.group(1))
    hi = float(m.group(2)) if m.group(2) else lo
    return {"min": lo, "max": hi}


def _extract_water_color(text):
    """水色を正規化して返す"""
    for word in ["青潮", "赤潮", "やや澄み", "やや濁り", "澄み", "濁り"]:
        if word in text:
            return word
    return ""


def _extract_wind_info(comment):
    """風向と風速を分離して返す。例: "南風10m"→{direction:"南",speed:"10"}"""
    comment = comment.translate(Z2H)
    m = re.search(r'(北東|北西|南東|南西|北|南|東|西)?風\s*(?:が)?(?:(強|弱)|(\d+(?:\.\d+)?)m)?', comment)
    if not m or not any([m.group(1), m.group(2), m.group(3)]):
        return {}
    direction = m.group(1) or ""
    speed = m.group(3) if m.group(3) else (m.group(2) or "")
    return {"direction": direction, "speed": speed}


def _extract_tide_info(comment):
    """潮況キーワードを抽出（カンマ区切り）。二枚潮・潮流れずは予測の重要特徴量"""
    patterns = ["二枚潮", "潮流れず", "潮が速", "潮速い", "潮流れよく", "潮がよく",
                "潮が緩", "潮止まり", "潮動かず", "上げ潮", "下げ潮", "大潮", "小潮"]
    found = [p for p in patterns if p in comment]
    return ",".join(found) if found else ""


def _extract_wave_info(comment):
    """波・うねり情報を抽出"""
    comment = comment.translate(Z2H)
    parts = []
    m = re.search(r'波\s*(\d+(?:\.\d+)?)\s*m', comment)
    if m:
        parts.append(f"波{m.group(1)}m")
    for word in ["ウネリあり", "うねりあり", "ウネリ", "うねり", "大波", "高波", "波が高", "穏やか"]:
        if word in comment and word not in ",".join(parts):
            parts.append(word)
            break
    return ",".join(parts) if parts else ""


def _extract_weather(comment):
    """天気キーワードを抽出（カンマ区切り）"""
    keywords = ["台風後", "嵐後", "嵐", "雷", "豪雨後", "雨後", "小雨", "雨", "霧", "快晴", "晴れ", "曇り"]
    found = [k for k in keywords if k in comment]
    return ",".join(found) if found else ""


def _extract_by_catch(comment):
    """「他に〜」から外道魚種リストをカンマ区切りで返す（最大3件）"""
    m = re.search(r'他に([^。]+?)(?:が釣れ|も釣れ|など|。|$)', comment)
    if not m:
        return ""
    fish_names = re.split(r'[・、\s]+', m.group(1).strip())
    valid = [f for f in fish_names if f][:3]
    return ",".join(valid)


def _classify_cancel_type(reason: str) -> str:
    """欠航理由テキスト → 分類。定休日 / 荒天 / 台風 / 不漁 / 不明"""
    if not reason:
        return "不明"
    if any(k in reason for k in ["定休", "定期休", "休業日", "お休み"]):
        return "定休日"
    if any(k in reason for k in ["台風"]):
        return "台風"
    if any(k in reason for k in ["強風", "風強", "荒天", "悪天", "しけ", "シケ",
                                   "波高", "高波", "うねり", "大波", "雷", "霧",
                                   "雨", "雪", "天候", "気象", "海況", "海が悪"]):
        return "荒天"
    if any(k in reason for k in ["中止", "欠航", "キャンセル", "休み", "お休"]):
        return "中止"
    return "不明"


def _extract_time_slot(fish_raw: str) -> str:
    """fish_raw から時間帯を抽出。例: '午前ライトアジ'→'午前', '夜イカ'→'夜'"""
    if not fish_raw:
        return ""
    # 午前・午後 併記（例: 忠彦丸「午前・午後ライトアジ乗合船」）→ 時間帯不定
    if "午前" in fish_raw and "午後" in fish_raw:
        return ""
    # 優先順位順にチェック（長いパターンを先に）
    for pattern, slot in [
        ("ショートショート", "ショート"),
        ("午前半日",   "午前"),
        ("午後半日",   "午後"),
        ("ナイト",     "夜"),
        ("デイゲーム", "昼"),
        ("午前",       "午前"),
        ("午後",       "午後"),
        ("朝マヅメ",   "朝"),
        ("夕マヅメ",   "夕"),
        ("夜",         "夜"),
        ("朝",         "朝"),
        ("夕",         "夕"),
        ("ショート",   "ショート"),
        ("半日",       "午前"),
    ]:
        if pattern in fish_raw:
            return slot
    return ""


def _extract_tackle(tokki):
    """特記欄から仕掛けを抽出"""
    for word in ["ルアー", "テンヤ", "コマセ", "ビシ", "胴付き", "泳がせ", "エサ"]:
        if word in tokki:
            return word
    return ""


def _split_point_places_depth(point_raw, comment=""):
    """ポイント文字列から場所リスト（最大3）と水深 {min, max} を分離して返す。"""
    point_raw = point_raw.translate(Z2H)
    depth = {}
    depth_patterns = [
        r'(?:水深|タナ|棚)\s*(\d+(?:\.\d+)?)(?:[~〜](\d+(?:\.\d+)?))?\s*m?',
        r'(\d+(?:\.\d+)?)[~〜](\d+(?:\.\d+)?)\s*m',
        r'(?:水深|タナ|棚)\s*(\d+(?:\.\d+)?)\s*m',
        r'(\d+(?:\.\d+)?)\s*m(?:\s|$|・|→)',
    ]
    for pat in depth_patterns:
        dm = re.search(pat, point_raw, re.I)
        if dm:
            lo = float(dm.group(1))
            hi = float(dm.group(2)) if dm.lastindex >= 2 and dm.group(2) else lo
            depth = {"min": lo, "max": hi}
            point_raw = (point_raw[:dm.start()] + point_raw[dm.end():]).strip("・→/ ")
            break
    places = [p.strip() for p in re.split(r'[・→/]', point_raw) if p.strip()]
    if len(places) == 1 and '~' in places[0]:
        sub = [p.strip() for p in places[0].split('~') if p.strip()]
        if all(not re.match(r'^\d+\.?\d*$', p) for p in sub):
            places = sub
    if not places and comment:
        m = re.search(r'(\S{2,10}[沖瀬根崎岬])[\s・。]', comment)
        if m:
            places = [m.group(1)]
    return places[:3], depth


RAW_CSV_HEADER = [
    "ship", "area", "date",
    "trip_no", "is_cancellation", "tsuri_mono_raw", "tsuri_mono", "main_sub",
    "fish_raw", "time_slot",
    "cnt_min", "cnt_max", "cnt_avg", "is_boat",
    "size_min", "size_max", "kg_min", "kg_max",
    "tackle",
    "point_place1", "point_place2", "point_place3",
    "depth_min", "depth_max",
    "water_temp_min", "water_temp_max",
    "water_color",
    "wind_direction", "wind_speed",
    "tide_info",
    "wave_info",
    "weather",
    "by_catch",
    "cancel_reason", "cancel_type",
    "kanso_raw", "suion_raw", "suishoku_raw",
]


def export_csv_from_raw(raw_path=None, output_dir=None, ships_filter=None):
    """catches_raw.json を読み込み、data/V{n}/YYYY-MM.csv を全件上書き再生成。
    output_dir: 省略時は _DATA_DIR（config.json の active_version に連動）。
    ships_filter: リスト指定でその船宿のみ処理（テスト用）。
    TSURI_MONO_MAP更新後に単体呼び出し可。"""
    if output_dir is None:
        output_dir = _DATA_DIR
    if raw_path is None:
        raw_path = os.path.join(os.path.dirname(__file__), "crawl", "catches_raw.json")
    if not os.path.exists(raw_path):
        print(f"export_csv_from_raw: {raw_path} が見つかりません")
        return 0
    with open(raw_path, encoding="utf-8") as f:
        records = json.load(f)

    # catches_raw_direct.json をマージ（忠彦丸・一之瀬丸・米元等の直接クロール分）
    _direct_path = os.path.join(os.path.dirname(os.path.abspath(raw_path)),
                                "direct-crawl", "catches_raw_direct.json")
    if os.path.exists(_direct_path):
        with open(_direct_path, encoding="utf-8") as _df:
            _direct = json.load(_df)
        for _r in _direct:
            _c = (_r.get("count_raw") or "").translate(Z2H)
            if not _r.get("size_raw"):
                _sm = re.search(r'(\d+)[~〜～](\d+)\s*(?:cm|㎝|ｃｍ)', _c, re.I)
                if _sm:
                    _r["size_raw"] = f"{_sm.group(1)}～{_sm.group(2)} cm"
                else:
                    _sm = re.search(r'(\d+)\s*(?:cm|㎝|ｃｍ)', _c, re.I)
                    if _sm:
                        _r["size_raw"] = f"{_sm.group(1)} cm"
            if not _r.get("weight_raw"):
                _wm = re.search(r'(\d+\.?\d*)[~〜～](\d+\.?\d*)\s*(?:kg|ｋｇ)', _c, re.I)
                if _wm:
                    _r["weight_raw"] = f"{_wm.group(1)}～{_wm.group(2)} kg"
                else:
                    _wm = re.search(r'(\d+\.?\d*)\s*(?:kg|ｋｇ)', _c, re.I)
                    if _wm:
                        _r["weight_raw"] = f"{_wm.group(1)} kg"
        records = _direct + records
        print(f"export_csv_from_raw: direct merge {len(_direct)}件")

    os.makedirs(output_dir, exist_ok=True)
    from collections import defaultdict as _dd
    by_month = _dd(list)
    for r in records:
        if ships_filter and r.get("ship") not in ships_filter:
            continue
        try:
            ym = datetime.strptime(r["date"], "%Y/%m/%d").strftime("%Y-%m")
            by_month[ym].append(r)
        except Exception:
            continue

    total = 0
    for ym, recs in sorted(by_month.items()):
        trip_idx = _dd(list)
        for r in recs:
            trip_idx[(r["ship"], r["date"], r.get("trip_no"))].append(r)

        rows = []
        for r in recs:
            if r.get("is_cancellation"):
                rows.append({
                    "ship":           r["ship"],
                    "area":           r["area"],
                    "date":           r["date"],
                    "trip_no":        "",
                    "is_cancellation": 1,
                    "tsuri_mono_raw": "",
                    "tsuri_mono":     "欠航",
                    "main_sub":       "",
                    "fish_raw":       "",
                    "time_slot":      "",
                    "cnt_min": "", "cnt_max": "", "cnt_avg": "", "is_boat": "",
                    "size_min": "", "size_max": "", "kg_min": "", "kg_max": "",
                    "tackle": "",
                    "point_place1": "", "point_place2": "", "point_place3": "",
                    "depth_min": "", "depth_max": "",
                    "water_temp_min": "", "water_temp_max": "",
                    "water_color": "", "wind_direction": "", "wind_speed": "",
                    "tide_info": "", "wave_info": "", "weather": "", "by_catch": "",
                    "cancel_reason":  r.get("reason_text", ""),
                    "cancel_type":    _classify_cancel_type(r.get("reason_text", "")),
                    "kanso_raw":      r.get("reason_text", ""),
                    "suion_raw":      "",
                    "suishoku_raw":   "",
                })
                continue

            comment   = r.get("kanso_raw") or ""
            trip_key  = (r["ship"], r["date"], r.get("trip_no"))
            same_trip = trip_idx[trip_key]

            tsuri_raw  = _extract_tsuri_mono(r, same_trip, r["ship"])
            tsuri_norm = normalize_tsuri_mono(tsuri_raw, r["ship"])
            main_sub   = _classify_main_sub(r.get("fish_raw", ""), tsuri_norm)

            _parts = comment.split("。")
            kanso_short = "。".join(_parts[:2]) + ("。" if len(_parts) > 1 else "")

            wt          = _extract_water_temp_range(r.get("suion_raw") or comment)
            water_color = _extract_water_color(r.get("suishoku_raw") or comment)
            wind        = _extract_wind_info(comment)
            tide_info   = _extract_tide_info(comment)
            wave_info   = _extract_wave_info(comment)
            weather     = _extract_weather(comment)
            by_catch    = _extract_by_catch(comment)
            tackle      = _extract_tackle(r.get("tokki_raw") or "")
            places, depth = _split_point_places_depth(r.get("point_raw") or "", comment)

            if not places or not places[0]:
                pp_from_kanso = _extract_point_from_kanso(comment)
                if pp_from_kanso:
                    places = [pp_from_kanso] + list(places[1:])

            cr = extract_count(r.get("count_raw") or "")
            sc = extract_size_cm(r.get("size_raw") or "")
            wk = extract_weight_kg(r.get("weight_raw") or "") or \
                 extract_weight_kg(r.get("tokki_raw") or "")
            cnt_avg = None
            if cr and cr.get("min") is not None and cr.get("max") is not None:
                cnt_avg = (cr["min"] + cr["max"]) // 2

            is_boat_rec = bool(cr and cr.get("is_boat"))
            if is_boat_rec:
                has_individual = any(
                    not (extract_count(x.get("count_raw") or "") or {}).get("is_boat")
                    for x in same_trip if x.get("count_raw")
                )
                if has_individual:
                    continue

            rows.append({
                "ship":           r["ship"],
                "area":           r["area"],
                "date":           r["date"],
                "trip_no":        r.get("trip_no", ""),
                "is_cancellation": 0,
                "tsuri_mono_raw": tsuri_raw or "",
                "tsuri_mono":     tsuri_norm,
                "main_sub":       main_sub,
                "fish_raw":       r.get("fish_raw", ""),
                "time_slot":      _extract_time_slot(r.get("fish_raw", "")),
                "cnt_min":        cr["min"] if cr else "",
                "cnt_max":        cr["max"] if cr else "",
                "cnt_avg":        cnt_avg if cnt_avg is not None else "",
                "is_boat":        1 if is_boat_rec else 0,
                "size_min":       sc["min"] if sc else "",
                "size_max":       sc["max"] if sc else "",
                "kg_min":         wk["min"] if wk else "",
                "kg_max":         wk["max"] if wk else "",
                "tackle":         tackle,
                "point_place1":   places[0] if len(places) > 0 else "",
                "point_place2":   places[1] if len(places) > 1 else "",
                "point_place3":   places[2] if len(places) > 2 else "",
                "depth_min":      depth.get("min", ""),
                "depth_max":      depth.get("max", ""),
                "water_temp_min": wt.get("min", ""),
                "water_temp_max": wt.get("max", ""),
                "water_color":    water_color,
                "wind_direction": wind.get("direction", ""),
                "wind_speed":     wind.get("speed", ""),
                "tide_info":      tide_info,
                "wave_info":      wave_info,
                "weather":        weather,
                "by_catch":       by_catch,
                "cancel_reason":  "",
                "cancel_type":    "",
                "kanso_raw":      kanso_short,
                "suion_raw":      r.get("suion_raw") or "",
                "suishoku_raw":   r.get("suishoku_raw") or "",
            })

        filepath = os.path.join(output_dir, f"{ym}.csv")
        with open(filepath, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=RAW_CSV_HEADER)
            writer.writeheader()
            writer.writerows(rows)
        total += len(rows)
        print(f"  {ym}.csv: {len(rows)}行")

    print(f"export_csv_from_raw: 合計{total}行 → {output_dir}/")
    return total


# ============================================================
# メイン
# ============================================================
CSV_HEADER = ["ship","area","date","fish","fish_raw","cnt_min","cnt_max","cnt_avg",
              "size_min","size_max","kg_min","kg_max","is_boat","point_place","point_place2",
              "point_depth_min","point_depth_max"]

def _split_place_pair(place_str):
    """「葉山沖〜城ヶ島沖」→ ('葉山沖', '城ヶ島沖')。〜がなければ (place, '')"""
    if not place_str:
        return "", ""
    m = re.search(r'^(.+?)[〜～~](.+)$', place_str)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    return place_str, ""


def _split_depth(depth_str):
    """水深文字列を min/max に分割。
    '20～30m' → (20, 30)
    '20m'     → (20, 20)
    '20～30'  → (20, 30)
    ''        → ('', '')
    """
    if not depth_str:
        return "", ""
    s = parse_num(depth_str.replace("m", "").replace("M", "").strip())
    m = re.search(r"(\d+)[～〜~\-](\d+)", s)
    if m:
        return int(m.group(1)), int(m.group(2))
    m = re.search(r"(\d+)", s)
    if m:
        v = int(m.group(1))
        return v, v
    return "", ""

def save_daily_csv(catches):
    """釣果を data/V2/YYYY-MM.csv に V2形式（38列）で追記（重複スキップ）。
    pageID=1 は複数日分を返すが、既存行との (ship, area, date, fish_raw) キーで
    重複チェックするため二重追記は発生しない。
    注: in-memory catch dict にはテキスト抽出列（kanso_raw等）がないため空欄になる。
    完全なV2 CSVは export_csv_from_raw() で catches_raw.json から全再生成する。
    """
    os.makedirs(_DATA_DIR, exist_ok=True)

    from collections import defaultdict
    by_month = defaultdict(list)
    for c in catches:
        if c.get("is_cancellation"):
            continue
        date_str = c.get("date", "")
        if not date_str:
            continue
        try:
            ym = datetime.strptime(date_str, "%Y/%m/%d").strftime("%Y-%m")
        except ValueError:
            continue
        by_month[ym].append(c)

    total_added = 0
    for ym, month_catches in by_month.items():
        filepath = os.path.join(_DATA_DIR, f"{ym}.csv")

        existing_keys = set()
        if os.path.exists(filepath):
            with open(filepath, encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    key = (row.get("ship",""), row.get("area",""),
                           row.get("date",""), row.get("fish_raw",""))
                    existing_keys.add(key)

        new_rows = []
        for c in month_catches:
            fish_raw = c.get("fish_raw", "")
            key = (c["ship"], c["area"], c["date"], fish_raw)
            if key in existing_keys:
                continue
            existing_keys.add(key)

            # V2 正規化
            tsuri_norm = normalize_tsuri_mono(fish_raw, c["ship"])
            main_sub   = _classify_main_sub(fish_raw, tsuri_norm)
            time_slot  = _extract_time_slot(fish_raw)
            pp1, pp2   = _split_place_pair(c.get("point_place") or "")
            d_min, d_max = _split_depth(c.get("point_depth") or "")

            cr = c.get("count_range") or {}
            sc = c.get("size_cm")    or {}
            wk = c.get("weight_kg") or {}
            cnt_avg = c["count_avg"] if c.get("count_avg") is not None else ""

            new_rows.append({
                "ship":           c["ship"],
                "area":           c["area"],
                "date":           c["date"],
                "trip_no":        "",
                "is_cancellation": 0,
                "tsuri_mono_raw": fish_raw,
                "tsuri_mono":     tsuri_norm,
                "main_sub":       main_sub,
                "fish_raw":       fish_raw,
                "time_slot":      time_slot,
                "cnt_min":        cr.get("min", ""),
                "cnt_max":        cr.get("max", ""),
                "cnt_avg":        cnt_avg,
                "is_boat":        1 if cr.get("is_boat") else 0,
                "size_min":       sc.get("min", ""),
                "size_max":       sc.get("max", ""),
                "kg_min":         wk.get("min", ""),
                "kg_max":         wk.get("max", ""),
                "tackle":         "",
                "point_place1":   pp1,
                "point_place2":   pp2,
                "point_place3":   "",
                "depth_min":      d_min,
                "depth_max":      d_max,
                "water_temp_min": "",
                "water_temp_max": "",
                "water_color":    "",
                "wind_direction": "",
                "wind_speed":     "",
                "tide_info":      "",
                "wave_info":      "",
                "weather":        "",
                "by_catch":       "",
                "cancel_reason":  "",
                "cancel_type":    "",
                "kanso_raw":      "",
                "suion_raw":      "",
                "suishoku_raw":   "",
            })

        if not new_rows:
            continue

        write_header = not os.path.exists(filepath)
        with open(filepath, "a", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=RAW_CSV_HEADER)
            if write_header:
                writer.writeheader()
            writer.writerows(new_rows)
        total_added += len(new_rows)

    return total_added


CANCELLATIONS_HEADER = ["date", "ship", "area", "reason_text"]

def save_cancellations_csv(catches):
    """休船・出船中止を data/V2/cancellations.csv に追記（重複スキップ）。"""
    cancels = [c for c in catches if c.get("is_cancellation")]
    if not cancels:
        return 0

    os.makedirs(_DATA_DIR, exist_ok=True)
    filepath = os.path.join(_DATA_DIR, "cancellations.csv")

    existing_keys = set()
    if os.path.exists(filepath):
        with open(filepath, encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                existing_keys.add((row["date"], row["ship"]))

    new_rows = []
    for c in cancels:
        key = (c["date"], c["ship"])
        if key in existing_keys:
            continue
        new_rows.append({
            "date":        c["date"],
            "ship":        c["ship"],
            "area":        c["area"],
            "reason_text": c.get("reason_text", ""),
        })

    if not new_rows:
        return 0

    write_header = not os.path.exists(filepath)
    with open(filepath, "a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CANCELLATIONS_HEADER)
        if write_header:
            writer.writeheader()
        writer.writerows(new_rows)
    return len(new_rows)


def repair_csv_depth(catches):
    """既存CSVの水深欠損を修復する。
    1. 14列の壊れた行 → point_depth(raw)を分割して16列に復元
    2. 16列でdepth空 → point_placeをparse_pointで再分割（タナ・深・末尾m対応）
    3. それでも空 → catches.jsonから補完
    """
    # catches.json → (ship, date, fish) -> (point_place, point_depth)
    depth_map = {}
    for c in catches:
        pd = c.get("point_depth") or ""
        pp = c.get("point_place") or ""
        if pd:
            for fish in c.get("fish", []):
                depth_map[(c["ship"], c.get("date", ""), fish)] = (pp, pd)

    data_dir = os.path.join(os.path.dirname(__file__), "data")
    if not os.path.isdir(data_dir):
        return 0
    total_fixed = 0
    for fname in sorted(os.listdir(data_dir)):
        if not fname.endswith(".csv"):
            continue
        filepath = os.path.join(data_dir, fname)
        with open(filepath, encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            header = next(reader)
            rows = list(reader)

        # Normalize header to 16 columns
        target_header = CSV_HEADER
        if header != target_header:
            header = target_header

        fixed_rows = []
        fixed_count = 0
        for row in rows:
            # 14列 → 16列: point_place=12, point_depth(raw)=13 → split into 4 cols
            if len(row) == 14:
                pp = row[12]
                pd_raw = row[13]
                d_min, d_max = _split_depth(pd_raw)
                row = row[:12] + [pp, "", str(d_min), str(d_max)]
                fixed_count += 1
            # 16列でdepth空 → point_placeをparse_pointで再分割
            elif len(row) == 16:
                if not row[14] and not row[15] and row[12]:
                    new_place, new_depth = parse_point(row[12])
                    if new_depth:
                        d_min, d_max = _split_depth(new_depth)
                        row[12] = new_place or ""
                        row[14] = str(d_min)
                        row[15] = str(d_max)
                        fixed_count += 1
                    else:
                        # parse_pointで取れなければcatches.jsonから補完
                        key = (row[0], row[2], row[3])  # ship, date, fish
                        info = depth_map.get(key)
                        if info:
                            pp_cj, pd_cj = info
                            d_min, d_max = _split_depth(pd_cj)
                            if d_min:
                                row[14] = str(d_min)
                                row[15] = str(d_max)
                                fixed_count += 1
            # Pad short rows
            while len(row) < 16:
                row.append("")
            fixed_rows.append(row)

        if fixed_count > 0:
            with open(filepath, "w", encoding="utf-8", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(target_header)
                writer.writerows(fixed_rows)
            total_fixed += fixed_count

    return total_fixed


# ============================================================
# sitemap.xml 自動生成
# ============================================================
def build_sitemap(data):
    from urllib.parse import quote as _quote
    now = datetime.now().strftime("%Y-%m-%d")
    urls = [
        (f"{SITE_URL}/", "1.0", "daily"),
        (f"{SITE_URL}/calendar.html", "0.6", "weekly"),
    ]
    # fish/*.html
    fish_set = set()
    _SKIP = {"不明", "欠航"}
    for c in data:
        for f in c["fish"]:
            if f not in _SKIP:
                fish_set.add(f)
    for fish in sorted(fish_set):
        urls.append((f"{SITE_URL}/fish/{fish_slug(fish)}.html", "0.8", "daily"))
    # area/*.html
    area_set = set(c["area"] for c in data)
    for area in sorted(area_set):
        urls.append((f"{SITE_URL}/area/{area_slug(area)}.html", "0.7", "daily"))
    # fish_area/*.html（≥5件の組み合わせ）
    fa_counts: dict = {}
    for c in data:
        for f in c["fish"]:
            if f not in _SKIP:
                fa_counts[(f, c["area"])] = fa_counts.get((f, c["area"]), 0) + 1
    for (fish, area), cnt in sorted(fa_counts.items()):
        if cnt >= 5:
            urls.append((f"{SITE_URL}/fish_area/{fish_slug(fish)}-{area_slug(area)}.html", "0.7", "weekly"))
    entries = "\n".join(
        f"  <url><loc>{loc}</loc><lastmod>{now}</lastmod><changefreq>{freq}</changefreq><priority>{pri}</priority></url>"
        for loc, pri, freq in urls
    )
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
{entries}
</urlset>"""
    with open(os.path.join(WEB_DIR, "sitemap.xml"), "w", encoding="utf-8") as f:
        f.write(xml)
    print(f"sitemap.xml: {len(urls)} URLs 生成 → docs/")


# ============================================================
# V2 共通インフラ: style.css / main.js / page構造
# ============================================================

def build_style_css():
    """V2 style.css を docs/ に生成する（V1 CSS とは完全に独立）"""
    css = """:root {
  /* ── ベース ── */
  --bg-primary:    #f5f7fa;
  --bg-card:       #ffffff;
  --bg-input:      #eef1f5;
  --border:        #d0d8e0;

  /* ── テキスト ── */
  --text-primary:  #1a2332;
  --text-secondary:#5a6a7a;
  --text-muted:    #8a96a4;

  /* ── アクセント（濃紺+オレンジ） ── */
  --accent:        #0d2b4a;
  --accent-hover:  #1a3d5c;
  --cta:           #e85d04;
  --cta-hover:     #d04e00;

  /* ── セマンティック ── */
  --positive:      #1a9d56;
  --negative:      #d43333;
  --warning:       #d4a017;
  --premium:       #7c3aed;

  /* ── ヘッダ・ナビ ── */
  --header-bg:     #0d2b4a;
  --header-text:   #ffffff;
  --nav-bg:        #f0f3f7;

  /* ── サイズ（2026/04/11 確定: --mx: 900px） ── */
  --radius-sm:     6px;
  --radius-md:     10px;
  --radius-lg:     14px;
  --mx:            900px;
}

/* ================================================================
   リセット・ベース
   ================================================================ */
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
html { font-size: 16px; scroll-behavior: smooth; }
body {
  font-family: system-ui, -apple-system, sans-serif;
  background: var(--bg-primary);
  color: var(--text-primary);
  line-height: 1.6;
  min-height: 100vh;
  padding-bottom: 64px;
}
a { color: var(--accent); text-decoration: none; }
a:hover { color: var(--accent-hover); text-decoration: underline; }
img { max-width: 100%; display: block; }

/* ================================================================
   レイアウト
   ================================================================ */
.container {
  max-width: var(--mx);
  margin: 0 auto;
  padding: 0 16px;
}

/* ================================================================
   ヘッダ
   ================================================================ */
.site-header {
  background: var(--header-bg);
  color: var(--header-text);
  position: sticky;
  top: 0;
  z-index: 100;
  box-shadow: 0 2px 8px rgba(0,0,0,0.2);
}
.site-header .container {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 52px;
}
.site-logo {
  font-size: 16px;
  font-weight: 700;
  color: var(--header-text);
  text-decoration: none;
  letter-spacing: 0.02em;
}
.site-logo:hover { color: var(--header-text); text-decoration: none; opacity: 0.9; }
.header-nav { display: none; gap: 24px; }
.header-nav a {
  color: rgba(255,255,255,0.85);
  font-size: 14px;
  font-weight: 500;
  text-decoration: none;
}
.header-nav a:hover { color: #fff; }
.header-nav a.active { color: var(--cta); }
@media (min-width: 769px) { .header-nav { display: flex; } }

/* ================================================================
   ボトムナビ（モバイル固定・5アイコン 2026/04/11 確定）
   ================================================================ */
.bottom-nav {
  position: fixed;
  bottom: 0;
  left: 0;
  right: 0;
  height: 56px;
  background: var(--bg-card);
  border-top: 1px solid var(--border);
  display: flex;
  z-index: 200;
  box-shadow: 0 -2px 8px rgba(0,0,0,0.08);
}
.bottom-nav a {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 3px;
  color: var(--text-muted);
  text-decoration: none;
  font-size: 10px;
  font-weight: 500;
  transition: color 0.15s;
  min-height: 44px;
}
.bottom-nav a:hover,
.bottom-nav a.active { color: var(--accent); text-decoration: none; }
.bottom-nav svg {
  width: 22px;
  height: 22px;
  stroke: currentColor;
  fill: none;
  stroke-width: 1.8;
  stroke-linecap: round;
  stroke-linejoin: round;
}
.bottom-nav a.premium-nav { color: var(--premium); }
.bottom-nav a.premium-nav.active { color: var(--premium); }
@media (min-width: 769px) {
  .bottom-nav { display: none; }
  body { padding-bottom: 0; }
}

/* ================================================================
   ヒーローゾーン（HERO）
   ================================================================ */
.hero {
  background: var(--accent);
  color: #fff;
  padding: 24px 0 20px;
}
.hero-title {
  font-size: 22px;
  font-weight: 700;
  margin-bottom: 4px;
}
.hero-count {
  font-size: 40px;
  font-weight: 800;
  color: var(--cta);
  line-height: 1.1;
}
.hero-count span { font-size: 18px; font-weight: 400; opacity: 0.8; margin-left: 4px; }
.hero-sub { font-size: 13px; opacity: 0.75; margin-top: 6px; }
@media (min-width: 769px) {
  .hero-title { font-size: 28px; }
  .hero-count { font-size: 48px; }
}

/* ================================================================
   セクション共通
   ================================================================ */
.section { padding: 24px 0; }
.section-title {
  font-size: 17px;
  font-weight: 700;
  color: var(--accent);
  margin-bottom: 16px;
  padding-bottom: 8px;
  border-bottom: 2px solid var(--cta);
  display: flex;
  align-items: center;
  gap: 8px;
}
.section-badge {
  font-size: 10px;
  font-weight: 700;
  padding: 2px 7px;
  border-radius: 10px;
  background: var(--positive);
  color: #fff;
}
.section-badge.premium { background: var(--premium); }

/* ================================================================
   魚種カードグリッド（ZONE B）
   ================================================================ */
.fish-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 12px;
  margin-bottom: 20px;
}
@media (min-width: 769px) { .fish-grid { grid-template-columns: repeat(3, 1fr); gap: 16px; } }

.fish-card {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  padding: 14px 12px;
  transition: box-shadow 0.2s, border-color 0.2s;
  text-decoration: none;
  display: block;
  color: inherit;
}
.fish-card:hover {
  box-shadow: 0 4px 16px rgba(13,43,74,0.12);
  border-color: var(--accent);
  text-decoration: none;
}
.fish-card-name {
  font-size: 15px;
  font-weight: 700;
  color: var(--text-primary);
  margin-bottom: 2px;
}
.fish-card-count { font-size: 12px; color: var(--text-secondary); margin-bottom: 6px; }
.fish-card-range { font-size: 16px; font-weight: 700; color: var(--accent); margin-bottom: 4px; }
.fish-card-yoy {
  font-size: 11px;
  font-weight: 600;
  padding: 2px 6px;
  border-radius: 8px;
  display: inline-block;
  margin-bottom: 8px;
}
.fish-card-yoy.up   { background: #e8f5ee; color: var(--positive); }
.fish-card-yoy.down { background: #fde8e8; color: var(--negative); }
.fish-card-yoy.flat { background: var(--bg-input); color: var(--text-secondary); }
.fish-card-area { font-size: 11px; color: var(--text-muted); margin-top: 4px; }

.season-bar { display: flex; gap: 2px; margin-bottom: 6px; }
.season-bar span { flex: 1; height: 4px; border-radius: 2px; background: var(--bg-input); }
.season-bar span.on   { background: var(--cta); }
.season-bar span.peak { background: var(--accent); }

/* ================================================================
   釣果テーブル（ZONE B）
   ================================================================ */
.catch-table-wrap {
  overflow-x: auto;
  border-radius: var(--radius-md);
  border: 1px solid var(--border);
  margin-bottom: 16px;
  background: var(--bg-card);
}
.catch-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
  min-width: 480px;
}
.catch-table th {
  background: var(--bg-input);
  color: var(--text-secondary);
  font-weight: 600;
  padding: 8px 10px;
  text-align: left;
  border-bottom: 1px solid var(--border);
  white-space: nowrap;
}
.catch-table td {
  padding: 8px 10px;
  border-bottom: 1px solid var(--border);
  vertical-align: middle;
}
.catch-table tr:last-child td { border-bottom: none; }
.catch-table tr:hover td { background: var(--bg-input); }
.yoy-badge {
  font-size: 11px;
  font-weight: 600;
  padding: 1px 5px;
  border-radius: 7px;
  white-space: nowrap;
}
.yoy-badge.up   { background: #e8f5ee; color: var(--positive); }
.yoy-badge.down { background: #fde8e8; color: var(--negative); }
.yoy-badge.flat { background: var(--bg-input); color: var(--text-secondary); }

/* ================================================================
   海況予報（ZONE C）
   ================================================================ */
.weather-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 12px;
}
@media (min-width: 769px) { .weather-grid { grid-template-columns: repeat(4, 1fr); } }

.weather-card {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  padding: 14px 12px;
  text-align: center;
}
.weather-date { font-size: 11px; color: var(--text-muted); margin-bottom: 4px; }
.weather-risk {
  font-size: 12px;
  font-weight: 700;
  padding: 2px 8px;
  border-radius: 10px;
  margin-bottom: 8px;
  display: inline-block;
}
.weather-risk.safe    { background: #e8f5ee; color: var(--positive); }
.weather-risk.caution { background: #fff8e1; color: var(--warning); }
.weather-risk.danger  { background: #fde8e8; color: var(--negative); }
.weather-stat { font-size: 12px; color: var(--text-secondary); margin-top: 3px; }
.weather-stat strong  { color: var(--text-primary); font-weight: 600; }

/* ================================================================
   ペイウォール（有料チラ見せ 2026/04/04 確定）
   ================================================================ */
.premium-section { position: relative; }
.premium-content-blurred {
  filter: blur(6px);
  pointer-events: none;
  user-select: none;
}
.premium-overlay {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  background: rgba(11,24,41,0.5);
  border-radius: var(--radius-md);
  gap: 10px;
}
.premium-lock { font-size: 26px; line-height: 1; }
.premium-cta-btn {
  background: var(--cta);
  color: #fff;
  padding: 8px 22px;
  border-radius: 20px;
  text-decoration: none;
  font-size: 14px;
  font-weight: 700;
  transition: background 0.15s;
}
.premium-cta-btn:hover { background: var(--cta-hover); color: #fff; text-decoration: none; }
.premium-free-badge {
  position: absolute;
  top: 8px;
  right: 8px;
  font-size: 10px;
  font-weight: 700;
  padding: 2px 7px;
  border-radius: 8px;
  background: var(--positive);
  color: #fff;
}
.premium-banner {
  background: linear-gradient(135deg, #1a0a30, #0a1a3a);
  border: 1px solid var(--premium);
  border-radius: var(--radius-lg);
  padding: 24px;
  text-align: center;
  margin: 20px 0;
  color: #fff;
}
.premium-banner p { margin-bottom: 12px; opacity: 0.85; font-size: 14px; }
.cta-btn-main {
  display: inline-block;
  background: var(--cta);
  color: #fff;
  padding: 12px 32px;
  border-radius: 24px;
  font-size: 16px;
  font-weight: 700;
  text-decoration: none;
  transition: background 0.15s;
}
.cta-btn-main:hover { background: var(--cta-hover); color: #fff; text-decoration: none; }

/* ================================================================
   フッタ
   ================================================================ */
.site-footer {
  background: var(--accent);
  color: rgba(255,255,255,0.75);
  padding: 32px 0 24px;
  margin-top: 40px;
  font-size: 13px;
}
.footer-links { display: flex; flex-wrap: wrap; gap: 16px; margin-bottom: 12px; }
.footer-links a { color: rgba(255,255,255,0.75); text-decoration: none; }
.footer-links a:hover { color: #fff; }
.footer-copy { font-size: 12px; opacity: 0.5; }

/* ================================================================
   Analysis Overlay スピナー（D+F 2026/04/07 確定）
   ================================================================ */
.analysis-overlay {
  position: fixed; inset: 0;
  background: rgba(0,0,0,0.65);
  display: flex; align-items: center; justify-content: center;
  z-index: 1000;
  opacity: 0; pointer-events: none;
  transition: opacity 0.3s ease;
}
.analysis-overlay.active { opacity: 1; pointer-events: auto; }
.analysis-modal {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: 28px 24px 20px;
  width: min(340px, 90vw);
  text-align: center;
  box-shadow: 0 8px 32px rgba(0,0,0,0.18);
}
.analysis-title { font-size: 14px; font-weight: 700; color: var(--text-primary); margin-bottom: 20px; }
.analysis-steps { text-align: left; display: flex; flex-direction: column; gap: 12px; margin-bottom: 20px; }
.step { display: flex; align-items: center; gap: 12px; opacity: 0.3; transition: opacity 0.4s; }
.step.active { opacity: 1; }
.step.done   { opacity: 0.55; }
.step-dot {
  width: 18px; height: 18px;
  border-radius: 50%;
  border: 2px solid var(--border);
  flex-shrink: 0; position: relative;
  transition: background 0.3s, border-color 0.3s, box-shadow 0.3s;
}
.step.active .step-dot { background: var(--cta); border-color: var(--cta); animation: pulse-dot 0.9s ease-in-out infinite; }
.step.done .step-dot   { background: var(--positive); border-color: var(--positive); animation: none; }
.step.done .step-dot::after {
  content: ''; position: absolute;
  top: 2px; left: 5px; width: 5px; height: 9px;
  border: 2px solid #fff; border-top: none; border-left: none;
  transform: rotate(45deg);
}
@keyframes pulse-dot {
  0%,100% { box-shadow: 0 0 0 4px rgba(232,93,4,0.18); }
  50%      { box-shadow: 0 0 0 7px rgba(232,93,4,0.08); }
}
.step-body { display: flex; flex-direction: column; gap: 2px; }
.step-text { font-size: 13px; font-weight: 600; color: var(--text-primary); }
.step-meta { font-size: 11px; color: var(--text-muted); }
.analysis-progress-wrap { height: 4px; background: var(--bg-input); border-radius: 2px; overflow: hidden; margin-bottom: 12px; }
.analysis-progress-fill {
  height: 100%; width: 0%;
  background: linear-gradient(90deg, var(--accent), var(--cta));
  border-radius: 2px; transition: width 0.7s ease;
}
.analysis-note { font-size: 11px; color: var(--text-muted); }
.count-up-target { display: inline-block; font-variant-numeric: tabular-nums; }
.forecast-result { opacity: 0; transform: translateY(6px); transition: opacity 0.4s, transform 0.4s; }
.forecast-result.visible { opacity: 1; transform: translateY(0); }

/* ================================================================
   ユーティリティ
   ================================================================ */
.text-center { text-align: center; }
.mt-8  { margin-top: 8px; }
.mt-16 { margin-top: 16px; }
.mt-24 { margin-top: 24px; }
.mb-8  { margin-bottom: 8px; }
.mb-16 { margin-bottom: 16px; }
.mb-24 { margin-bottom: 24px; }
"""
    with open(os.path.join(WEB_DIR, "style.css"), "w", encoding="utf-8") as f:
        f.write(css)
    print("style.css: V2 共通スタイルシート生成 → docs/")


def build_main_js():
    """V2 main.js を docs/ に生成する"""
    js = """/* main.js — V2 共通スクリプト */
(function () {
  'use strict';

  /* ── テーブルフィルタ ── */
  var filterInput = document.getElementById('catch-filter');
  var filterRows  = document.querySelectorAll('.catch-table tbody tr');
  if (filterInput && filterRows.length) {
    filterInput.addEventListener('input', function () {
      var q = this.value.trim().toLowerCase();
      filterRows.forEach(function (tr) {
        tr.style.display = (!q || tr.textContent.toLowerCase().indexOf(q) !== -1) ? '' : 'none';
      });
    });
  }

  /* ── エリアフィルタ ── */
  var areaSelect = document.getElementById('area-filter');
  if (areaSelect && filterRows.length) {
    areaSelect.addEventListener('change', function () {
      var area = this.value;
      filterRows.forEach(function (tr) {
        var td = tr.querySelector('.col-area');
        tr.style.display = (!area || (td && td.textContent.trim() === area)) ? '' : 'none';
      });
    });
  }

  /* ── テーブルソート ── */
  document.querySelectorAll('.sortable').forEach(function (th) {
    th.style.cursor = 'pointer';
    th.addEventListener('click', function () {
      var table = th.closest('table');
      if (!table) return;
      var idx = Array.from(th.parentNode.children).indexOf(th);
      var asc = th.dataset.sortDir !== 'asc';
      th.dataset.sortDir = asc ? 'asc' : 'desc';
      var rows = Array.from(table.tBodies[0].rows);
      rows.sort(function (a, b) {
        var av = a.cells[idx].textContent.trim();
        var bv = b.cells[idx].textContent.trim();
        var an = parseFloat(av.replace(/[^\\d.-]/g, ''));
        var bn = parseFloat(bv.replace(/[^\\d.-]/g, ''));
        if (!isNaN(an) && !isNaN(bn)) return asc ? an - bn : bn - an;
        return asc ? av.localeCompare(bv, 'ja') : bv.localeCompare(av, 'ja');
      });
      rows.forEach(function (r) { table.tBodies[0].appendChild(r); });
    });
  });

  /* ── タブ切替 ── */
  document.querySelectorAll('.tab-group').forEach(function (tg) {
    var tabs   = tg.querySelectorAll('.tab-btn');
    var panels = tg.querySelectorAll('.tab-panel');
    tabs.forEach(function (btn, i) {
      btn.addEventListener('click', function () {
        tabs.forEach(function (t) { t.classList.remove('active'); });
        panels.forEach(function (p) { p.classList.remove('active'); });
        btn.classList.add('active');
        if (panels[i]) panels[i].classList.add('active');
      });
    });
  });

  /* ── スムーススクロール ── */
  document.querySelectorAll('a[href^="#"]').forEach(function (a) {
    a.addEventListener('click', function (e) {
      var id = a.getAttribute('href').slice(1);
      var target = document.getElementById(id);
      if (target) {
        e.preventDefault();
        target.scrollIntoView({ behavior: 'smooth', block: 'start' });
      }
    });
  });

  /* ── ボトムナビ active ── */
  var path = location.pathname.replace(/\\/+$/, '') || '/';
  document.querySelectorAll('.bottom-nav a').forEach(function (a) {
    var href = (a.getAttribute('href') || '').replace(/\\/+$/, '') || '/';
    if (path === href) a.classList.add('active');
  });

  /* ================================================================
     Analysis Overlay スピナー（D+F 2026/04/07 確定）
     ================================================================ */
  function showAnalysis(onComplete, cacheKey) {
    var overlay = document.getElementById('analysis-overlay');
    if (!overlay) { if (onComplete) onComplete(); return; }
    var steps  = overlay.querySelectorAll('.step');
    var bar    = document.getElementById('analysis-progress-fill');
    var cached = cacheKey && sessionStorage.getItem('spinner_' + cacheKey);

    overlay.classList.add('active');
    overlay.setAttribute('aria-hidden', 'false');

    if (cached) {
      if (bar) bar.style.width = '100%';
      setTimeout(function () { _finishOverlay(overlay, onComplete); }, 500);
      return;
    }

    function activateStep(i, pct, delay) {
      setTimeout(function () {
        if (i > 0) {
          steps[i - 1].classList.remove('active');
          steps[i - 1].classList.add('done');
        }
        steps[i].classList.add('active');
        if (bar) bar.style.width = pct + '%';
      }, delay);
    }

    activateStep(0, 35, 0);
    activateStep(1, 70, 1200);
    activateStep(2, 95, 2400);

    setTimeout(function () {
      steps[2].classList.remove('active');
      steps[2].classList.add('done');
      if (bar) bar.style.width = '100%';
    }, 3200);

    setTimeout(function () {
      _finishOverlay(overlay, onComplete);
      if (cacheKey) sessionStorage.setItem('spinner_' + cacheKey, '1');
    }, 3600);
  }

  function _finishOverlay(overlay, onComplete) {
    overlay.classList.remove('active');
    overlay.setAttribute('aria-hidden', 'true');
    overlay.querySelectorAll('.step').forEach(function (s) { s.classList.remove('active', 'done'); });
    var bar = document.getElementById('analysis-progress-fill');
    if (bar) bar.style.width = '0%';
    if (onComplete) onComplete();
  }

  function countUp(el, to, duration) {
    var start = null;
    function step(ts) {
      if (!start) start = ts;
      var progress = Math.min((ts - start) / duration, 1);
      var eased = 1 - Math.pow(1 - progress, 3);
      el.textContent = Math.round(to * eased);
      if (progress < 1) requestAnimationFrame(step);
    }
    requestAnimationFrame(step);
  }

  window.showAnalysis       = showAnalysis;
  window.countUp            = countUp;

})();
"""
    with open(os.path.join(WEB_DIR, "main.js"), "w", encoding="utf-8") as f:
        f.write(js)
    print("main.js: V2 共通スクリプト生成 → docs/")
    # pages/*.html を docs/pages/ にコピー（フッターリンク用）
    import shutil
    pages_src = "pages"
    pages_dst = os.path.join(WEB_DIR, "pages")
    if os.path.isdir(pages_src):
        os.makedirs(pages_dst, exist_ok=True)
        for fn in os.listdir(pages_src):
            if fn.endswith(".html"):
                shutil.copy2(os.path.join(pages_src, fn), os.path.join(pages_dst, fn))
        print(f"pages/: {len([f for f in os.listdir(pages_src) if f.endswith('.html')])} ファイル → docs/pages/")


def _page_head(title, desc="", canonical=""):
    """V2 共通 <head>〜<body> 開きタグを返す"""
    if not desc:
        desc = "関東船釣りの最新釣果情報。今日何が釣れたか、エリア別・魚種別に一目でわかる。"
    canon_tag = (
        f'<link rel="canonical" href="{SITE_URL}/{canonical}">'
        if canonical else ""
    )
    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<meta name="description" content="{desc}">
<link rel="stylesheet" href="/style.css">
{canon_tag}
</head>
<body>"""


def _page_nav(current_page=""):
    """V2 ヘッダ + ボトムナビ（5アイコン SVG インライン）を返す"""
    def act(page):
        return ' class="active"' if current_page == page else ""

    prem_cls = ('class="premium-nav active"'
                if current_page == "premium"
                else 'class="premium-nav"')

    # SVG アイコン（線画・fill:none・CSS で stroke を管理）
    svg_catch = '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M12 8v4l2.5 2.5"/></svg>'
    svg_fish  = '<svg viewBox="0 0 24 24"><path d="M3 12c0 0 4-7 9-7s9 7 9 7-4 7-9 7-9-7-9-7z"/><circle cx="8.5" cy="11" r="1.2"/></svg>'
    svg_area  = '<svg viewBox="0 0 24 24"><path d="M12 2C8.13 2 5 5.13 5 9c0 5.25 7 13 7 13s7-7.75 7-13c0-3.87-3.13-7-7-7z"/><circle cx="12" cy="9" r="2.5"/></svg>'
    svg_cal   = '<svg viewBox="0 0 24 24"><rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4M8 2v4M3 10h18"/></svg>'
    svg_prem  = '<svg viewBox="0 0 24 24"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg>'

    idx  = act('index')
    fish = act('fish')
    area = act('area')
    cal  = act('calendar')
    prem = act('premium')

    return (
        '<header class="site-header">'
        '<div class="container">'
        '<a href="/" class="site-logo">船釣り予想</a>'
        '<nav class="header-nav" aria-label="メインナビゲーション">'
        f'<a href="/"{idx}>今日の釣果</a>'
        f'<a href="/fish/"{fish}>魚種</a>'
        f'<a href="/area/"{area}>エリア</a>'
        f'<a href="/calendar.html"{cal}>カレンダー</a>'
        f'<a href="/forecast/index.html"{prem}>有料</a>'
        '</nav>'
        '</div>'
        '</header>'
        '<nav class="bottom-nav" aria-label="ボトムナビゲーション">'
        f'<a href="/"{idx}>{svg_catch}<span>釣果</span></a>'
        f'<a href="/fish/"{fish}>{svg_fish}<span>魚種</span></a>'
        f'<a href="/area/"{area}>{svg_area}<span>エリア</span></a>'
        f'<a href="/calendar.html"{cal}>{svg_cal}<span>カレンダー</span></a>'
        f'<a href="/forecast/index.html" {prem_cls}>{svg_prem}<span>有料</span></a>'
        '</nav>'
    )


def _page_foot():
    """V2 共通フッタ + </body></html> を返す"""
    return (
        '<footer class="site-footer">'
        '<div class="container">'
        '<div class="footer-links">'
        '<a href="/pages/about.html">サイトについて</a>'
        '<a href="/pages/privacy.html">プライバシーポリシー</a>'
        '<a href="/pages/terms.html">利用規約</a>'
        '<a href="/pages/contact.html">お問い合わせ</a>'
        '</div>'
        '<p class="footer-copy">&copy; 2026 funatsuri-yoso.com</p>'
        '</div>'
        '</footer>'
        '<script src="/main.js"></script>'
        '</body>'
        '</html>'
    )


def main():
    import sys as _sys
    # --export-csv: catches_raw.json から data/V2/ を全再生成して終了
    if "--export-csv" in _sys.argv:
        export_csv_from_raw()
        return

    all_catches = []
    errors = []
    now = datetime.now()
    crawled_at = now.strftime("%Y/%m/%d %H:%M")
    year = now.year
    fv_count  = sum(1 for s in SHIPS if s.get("source", "fishing-v") == "fishing-v")
    gyo_count = sum(1 for s in SHIPS if s.get("source") == "gyo")
    print(f"=== 関東船釣りクローラー v5.15 開始: {crawled_at} ===")
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

    # 日次CSV蓄積（V2形式 → data/V2/）
    csv_added = save_daily_csv(all_catches)
    if csv_added:
        print(f"CSV保存: {csv_added} 件追記 → {_DATA_DIR}/")

    # 休船・出船中止の記録
    cancel_added = save_cancellations_csv(all_catches)
    if cancel_added:
        print(f"休船記録: {cancel_added} 件追記 → {_DATA_DIR}/cancellations.csv")

    # repair_csv_depth: V1形式専用のため無効化（V2ではdepth_min/depth_maxで管理）

    # 問題2対応 (2026/04/16): catches.json は当日分のみに絞る
    # save_daily_csv はメモリ上の all_catches を使うため影響なし
    _today_str_snap = datetime.now().strftime("%Y/%m/%d")
    today_all = [c for c in all_catches if c.get("date") == _today_str_snap]
    today_valid = [c for c in valid_catches if c.get("date") == _today_str_snap]
    today_anomaly = sum(1 for c in today_all if c.get("anomaly"))
    # 当日分が0件（クロール直後・翌0時前後等）は全件フォールバック
    snap_data = today_all if today_all else all_catches
    snap_valid = today_valid if today_all else valid_catches
    snap_anomaly = today_anomaly if today_all else anomaly_count
    with open("catches.json", "w", encoding="utf-8") as f:
        json.dump({"crawled_at": crawled_at, "total": len(snap_data), "valid": len(snap_valid),
                   "anomaly": snap_anomaly, "errors": errors, "data": snap_data,
                   "_all_count": len(all_catches), "_today_only": bool(today_all)}, f, ensure_ascii=False, indent=2)
    weather_data = load_weather_data()
    fc_count = len(weather_data.get("forecast", {}))
    if fc_count:
        print(f"海況予報: {fc_count} エリア×日")
    # 釣果予測
    forecast_data = build_forecast_json(weather_data, catches=valid_catches, history=history) if fc_count else None
    if forecast_data:
        weather_data["_forecast_data"] = forecast_data
        with open("forecast.json", "w", encoding="utf-8") as f:
            json.dump(forecast_data, f, ensure_ascii=False, indent=2)
        print(f"forecast.json: {len(forecast_data.get('days', {}))} 日分 + {len(forecast_data.get('weeks', {}))} 週分生成")
        build_forecast_pages(forecast_data, weather_data, catches=valid_catches, history=history)
    os.makedirs(WEB_DIR, exist_ok=True)
    with open(os.path.join(WEB_DIR, "CNAME"), "w", encoding="utf-8") as f:
        f.write("funatsuri-yoso.com")
    build_style_css()
    build_main_js()
    with open(os.path.join(WEB_DIR, "index.html"), "w", encoding="utf-8") as f:
        f.write(build_html(valid_catches, crawled_at, history, weather_data))
    build_fish_pages(valid_catches, history, crawled_at)
    build_area_pages(valid_catches, history, crawled_at, weather_data)
    build_fish_area_pages(valid_catches, crawled_at, history)
    with open(os.path.join(WEB_DIR, "calendar.html"), "w", encoding="utf-8") as f:
        f.write(build_calendar_page(crawled_at))
    build_sitemap(valid_catches)
    print(f"\n=== 完了 ===")
    _today_label = f"当日: {len(today_all)} 件" if today_all else f"当日0件→全件フォールバック: {len(all_catches)} 件"
    print(f"釣果: {len(all_catches)} 件（有効: {len(valid_catches)} / 異常値: {anomaly_count} / 重複除外: {dup_removed}）")
    print(f"出力: {_today_label}（catches.json）")
    print(f"エラー: {errors or 'なし'}")
    print(f"出力: docs/ (index.html / fish/*.html / area/*.html / fish_area/*.html / sitemap.xml / CNAME)")

if __name__ == "__main__":
    main()
