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
from datetime import datetime, timedelta, timezone
from urllib.request import urlopen, Request
from urllib.error import URLError
from urllib.parse import quote
from html.parser import HTMLParser

JST = timezone(timedelta(hours=9))

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
                           "久里浜", "久里浜港", "鴨居大室港", "小坪港",
                           "小網代港", "佐島"],
    "神奈川・相模湾":     ["松輪", "松輪江奈港", "松輪間口港", "長井", "長井港",
                           "長井新宿港", "長井漆山港", "葉山鐙摺",
                           "葉山あぶずり港", "腰越", "茅ヶ崎", "茅ヶ崎港",
                           "平塚", "平塚港", "大磯港", "寒川港",
                           "小田原早川", "小田原早川港"],
    "静岡":               ["宇佐美", "戸田", "沼津内港", "沼津静浦",
                           "由比", "御前崎港", "福田港", "下田港"],
}

# crawl/ships.json が正（discover_ships.py が月1回更新）
# フォールバック: 旧位置 ships.json（ルート直下）
_ships_json = os.path.join(os.path.dirname(__file__), "crawl", "ships.json")
if not os.path.exists(_ships_json):
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

# ============================================================
# 出船リスク予報：内海/外海分類と閾値
# ============================================================
_UCHIUMI_AREAS = {"千葉・内房", "千葉・東京湾奥", "東京", "神奈川・東京湾"}
_SOTOUMI_AREAS = {"茨城", "千葉・外房", "神奈川・相模湾", "静岡"}

# (warn_wave, warn_wind, bad_wave, bad_wind)
# 外海 = 大型船・高波想定内 → 高い閾値（条件が甘い＝ひどい荒天でのみ警戒）
# 内海 = 小型船・低波でも欠航 → 低い閾値（条件が厳しい＝少しの荒れで警戒）
# 集計方法: MAX（海域内の最も荒れたエリアで判定）
_RISK_THR = {
    "外海": (2.0, 10.0, 3.5, 15.0),
    "内海": (0.8,  6.0, 1.5,  9.0),
}

def _risk_label(wave, wind, sea_type):
    """波高(m)・風速(m/s)・内海/外海 → (cls, icon, lbl)"""
    warn_w, warn_wnd, bad_w, bad_wnd = _RISK_THR[sea_type]
    if wave >= bad_w or wind >= bad_wnd:
        return "bad", "×", "欠航警戒"
    if wave >= warn_w or wind >= warn_wnd:
        return "warn", "△", "注意"
    return "good", "○", "好条件"

def _risk_grid_row(label, area_names, days_data):
    """1行分のリスクグリッドHTML（ラベル付き）"""
    dow_jp = ["月","火","水","木","金","土","日"]
    sea_type = "内海" if label == "内海" else "外海"
    cells = ""
    for date_str in sorted(days_data.keys())[:7]:
        try:
            dt = datetime.strptime(date_str, "%Y-%m-%d")
            dow = dow_jp[dt.weekday()]
            label_date = f"{dt.month}/{dt.day}"
        except:
            continue
        day_info = days_data[date_str]
        areas_info = day_info.get("areas", {})
        waves = [areas_info[a]["wave"] for a in area_names if a in areas_info and areas_info[a].get("wave") is not None]
        winds = [areas_info[a]["wind"] for a in area_names if a in areas_info and areas_info[a].get("wind") is not None]
        avg_wave = max(waves) if waves else day_info.get("wave") or 0
        avg_wind = max(winds) if winds else day_info.get("wind") or 0
        cls, icon, lbl = _risk_label(avg_wave, avg_wind, sea_type)
        cells += (
            f'<div class="risk-day {cls}">'
            f'<div class="rd-dow">{dow}</div>'
            f'<div class="rd-date">{label_date}</div>'
            f'<div class="rd-icon">{icon}</div>'
            f'<div class="rd-label">{lbl}</div>'
            f'</div>'
        )
    subtitle = "茨城・外房・相模湾・静岡" if sea_type == "外海" else "東京湾各エリア"
    return (
        f'<div class="risk-row">'
        f'<div class="risk-row-head"><span class="risk-sea-type">{label}</span><span class="risk-sea-areas">（{subtitle}）</span></div>'
        f'<div class="risk-days">{cells}</div>'
        f'</div>'
    )

# 予測広域エリア → URL/アンカー用ヘボン式スラッグ（決定ログ 2026/04/10「ローマ字統一」）
_FORECAST_AREA_SLUG = {
    "茨城":           "ibaraki",
    "千葉・外房":     "chiba-sotobo",
    "千葉・内房":     "chiba-uchibo",
    "千葉・東京湾奥": "chiba-tokyo-bay-inner",
    "東京":           "tokyo",
    "神奈川・東京湾": "kanagawa-tokyo-bay",
    "神奈川・相模湾": "kanagawa-sagami-bay",
    "静岡":           "shizuoka",
}

def forecast_area_slug(group: str) -> str:
    """予測広域エリア名 → URLスラッグ（V2ローマ字統一）"""
    return _FORECAST_AREA_SLUG.get(group, group)

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
    now = datetime.now(JST).replace(tzinfo=None)
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

def _moon_phase_name(age):
    """月齢 → 月相名（満月・新月・半月 等）。海況表示用。"""
    if age is None:
        return ""
    if age < 1.5:                 return "新月"
    if age < 6.5:                 return "三日月"
    if age < 8.5:                 return "上弦の月"
    if age < 13.5:                return "十三夜"
    if age < 16.0:                return "満月"
    if age < 21.5:                return "十六夜"
    if age < 23.5:                return "下弦の月"
    if age < 28.0:                return "有明月"
    return "新月"

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
    today = datetime.now(JST).replace(tzinfo=None)
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

def _load_recent_catches_for_index(now, days=7):
    """過去 days 日（today 含む）の catches を data/V2/*.csv から読み込み、
    fish/index.html・area/index.html の「今週」集計用に dict-list を返す。
    再クロールは一切しない（save_daily_csv() による日次蓄積を流用）。

    返却 record（valid_catches と互換）: {ship, area, date, fish, fish_raw}
      - fish: guess_fish(fish_raw) でサイト全体と同一の FISH_MAP 正規化
      - date: "YYYY/MM/DD"

    遅延到着耐性: data/V2 CSV は (ship, area, date, fish_raw) で dedup 追記される。
    Day N の record が Day N に取れず Day N+1 のクロールで初めて拾われた場合も、
    Day N+1 に正しく CSV へ追加される（既存キーに該当しないため）。
    7日窓で読めば遅延到着 records も自然に含まれる。
    """
    cutoff = (now - timedelta(days=days-1)).strftime("%Y/%m/%d")
    today_str = now.strftime("%Y/%m/%d")
    months_needed = set()
    for d in range(days):
        dt = now - timedelta(days=d)
        months_needed.add(dt.strftime("%Y-%m"))

    base = os.path.dirname(__file__) or "."
    try:
        with open(os.path.join(base, "config.json"), encoding="utf-8") as f:
            ver = json.load(f).get("active_version", "V2")
    except Exception:
        ver = "V2"
    data_dir = os.path.join(base, "data", ver)
    if not os.path.isdir(data_dir):
        return []

    rows_out = []
    for ym in sorted(months_needed):
        path = os.path.join(data_dir, f"{ym}.csv")
        if not os.path.isfile(path):
            continue
        try:
            with open(path, encoding="utf-8", newline="") as f:
                for row in csv.DictReader(f):
                    d = row.get("date", "")
                    if not d or d < cutoff or d > today_str:
                        continue
                    if row.get("is_cancellation") == "1":
                        continue
                    fish_raw = row.get("fish_raw", "") or row.get("tsuri_mono_raw", "")
                    if not fish_raw:
                        continue
                    # count_range / size_cm 構築（ミニバー・サイズ表示で使用）
                    def _to_int(s):
                        try: return int(float(s))
                        except (ValueError, TypeError): return None
                    def _to_float(s):
                        try: return float(s)
                        except (ValueError, TypeError): return None
                    cmin = _to_int(row.get("cnt_min", ""))
                    cmax = _to_int(row.get("cnt_max", ""))
                    cavg = _to_int(row.get("cnt_avg", ""))
                    is_boat = row.get("is_boat", "") == "1"
                    count_range = None
                    if cmin is not None and cmax is not None:
                        count_range = {"min": cmin, "max": cmax, "is_boat": is_boat}
                    smin = _to_float(row.get("size_min", ""))
                    smax = _to_float(row.get("size_max", ""))
                    size_cm = None
                    if smin is not None and smax is not None:
                        size_cm = {"min": smin, "max": smax}
                    kgmin = _to_float(row.get("kg_min", ""))
                    kgmax = _to_float(row.get("kg_max", ""))
                    weight_kg = None
                    if kgmin is not None and kgmax is not None:
                        weight_kg = {"min": kgmin, "max": kgmax}
                    rows_out.append({
                        "ship":        row.get("ship", ""),
                        "area":        row.get("area", ""),
                        "date":        d,
                        "fish":        guess_fish(fish_raw),
                        "fish_raw":    fish_raw,
                        "count_range": count_range,
                        "count_avg":   cavg,
                        "size_cm":     size_cm,
                        "weight_kg":   weight_kg,
                    })
        except Exception:
            continue
    return rows_out

def _summarize_area_history(area: str, hist_rows: list, today_dt) -> dict:
    """data/V2/CSV から area の過去データを集計（catches=0 のときの準備中ページ用）。
    返却: total/recent_30_days/recent_30_ships/top_fish/top_points/top_ships/top_sizes/month_days
    """
    from collections import Counter as _Counter
    from datetime import timedelta as _td
    cutoff_30 = today_dt - _td(days=30)
    cutoff_365 = today_dt - _td(days=365)
    rows_area = []
    for r in hist_rows:
        if r.get("area") != area:
            continue
        if r.get("is_cancellation") == "1":
            continue
        rows_area.append(r)
    recent_30, recent_365 = [], []
    for r in rows_area:
        try:
            d = datetime.strptime(r["date"], "%Y/%m/%d")
        except Exception:
            continue
        if d >= cutoff_30:
            recent_30.append(r)
        if d >= cutoff_365:
            recent_365.append(r)
    days_30 = len({r["date"] for r in recent_30})
    ships_30 = len({r["ship"] for r in recent_30 if r.get("ship")})
    fish_c, point_c, ship_c = _Counter(), _Counter(), _Counter()
    sizes = []
    month_days_set: dict = {}
    for r in recent_365:
        f = r.get("tsuri_mono", "")
        if f and f not in ("不明", "欠航") and not f.isdigit():
            fish_c[f] += 1
        p = (r.get("point_place1") or "").strip()
        if p:
            point_c[p] += 1
        s = r.get("ship", "")
        if s:
            ship_c[s] += 1
        try:
            sz = float(r.get("size_max") or 0)
            if sz > 0 and f:
                sizes.append((sz, f, r.get("date", "")))
        except Exception:
            pass
        d = r.get("date", "")
        if len(d) >= 10:
            month_days_set.setdefault(d[5:7], set()).add(d)
    sizes.sort(reverse=True)
    return {
        "total": len(rows_area),
        "recent_365_records": len(recent_365),
        "recent_30_days": days_30,
        "recent_30_ships": ships_30,
        "top_fish": fish_c.most_common(10),
        "top_points": point_c.most_common(5),
        "top_ships": ship_c.most_common(10),
        "top_sizes": sizes[:5],
        "month_days": {m: len(ds) for m, ds in month_days_set.items()},
    }


def _summarize_fish_history(fish: str, hist_rows: list, today_dt) -> dict:
    """data/V2/CSV から fish の過去データを集計（catches=0 のときの準備中ページ用）。
    返却: total/recent_365_records/top_areas/top_ships/top_sizes/month_records/avg_size/max_size
    """
    from collections import Counter as _Counter
    from datetime import timedelta as _td
    cutoff_365 = today_dt - _td(days=365)
    rows_f = []
    for r in hist_rows:
        if r.get("tsuri_mono") != fish:
            continue
        if r.get("is_cancellation") == "1":
            continue
        rows_f.append(r)
    recent_365 = []
    for r in rows_f:
        try:
            d = datetime.strptime(r["date"], "%Y/%m/%d")
        except Exception:
            continue
        if d >= cutoff_365:
            recent_365.append(r)
    area_c, ship_c = _Counter(), _Counter()
    sizes = []
    month_records: dict = {}
    for r in recent_365:
        a = r.get("area", "")
        if a:
            area_c[a] += 1
        s = r.get("ship", "")
        if s:
            ship_c[s] += 1
        try:
            sz = float(r.get("size_max") or 0)
            if sz > 0:
                sizes.append((sz, a, r.get("date", "")))
        except Exception:
            pass
        d = r.get("date", "")
        if len(d) >= 10:
            month_records[d[5:7]] = month_records.get(d[5:7], 0) + 1
    sizes.sort(reverse=True)
    avg_size = round(sum(s for s, _, _ in sizes) / len(sizes), 1) if sizes else None
    max_size = sizes[0][0] if sizes else None
    return {
        "total": len(rows_f),
        "recent_365_records": len(recent_365),
        "top_areas": area_c.most_common(5),
        "top_ships": ship_c.most_common(5),
        "top_sizes": sizes[:5],
        "month_records": month_records,
        "avg_size": avg_size,
        "max_size": max_size,
    }


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
        try: cnt_min_val = float(row.get("cnt_min", ""))
        except: cnt_min_val = None
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
        index.append({"fish": fish, "cnt": cnt, "cnt_min": cnt_min_val, "wave": wx.get("wave"),
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
            # cnt_min の実測値から P20 相当を base_min に（NULL 除外）
            cnt_mins_raw = [r["cnt_min"] for r in month_rows if r.get("cnt_min") is not None]
            if cnt_mins_raw:
                cnt_mins_sorted = sorted(cnt_mins_raw)
                base_min = cnt_mins_sorted[int(len(cnt_mins_sorted) * 0.2)]
            else:
                base_min = None

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
            # cnt_min の実測値 P20 に同じ adjustment を適用（NULL の場合は None）
            pred_min = int(max(0, round(base_min * (1.0 + adjustment)))) if base_min is not None else None

            key = (fish, group)
            season_score = get_season_score(fish, target_month) if target_month else 0
            season_types = SEASON_TYPE.get(fish, [""]*12)
            season_type = season_types[target_month - 1] if target_month and len(season_types) >= target_month else ""
            predictions[key] = {
                "fish": fish,
                "group": group,
                "avg": pred_avg,
                "min": pred_min,
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

    result = {"generated_at": datetime.now(JST).replace(tzinfo=None).strftime("%Y/%m/%d %H:%M"), "days": {}, "weeks": {}}

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
                    "min": area.get("min"),
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
    today = datetime.now(JST).replace(tzinfo=None)
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
                    "min": area.get("min"),
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


def _forecast_page_head(title, depth_prefix="../"):
    return f"""<!DOCTYPE html>
<html lang="ja"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex, follow">
<title>{title} | 船釣り予想</title>
{GA_TAG}
{ADSENSE_TAG}
<link rel="stylesheet" href="{depth_prefix}style.css">
<style>{_FORECAST_EXTRA_CSS}</style>
</head><body>
{_v2_header_nav('forecast')}
<div class="c">
<p class="bread"><a href="/index.html">トップ</a> &rsaquo; <a href="/forecast/index.html">釣果予測</a> &rsaquo; {title}</p>"""


def _forecast_page_foot():
    return f"""</div>
{_v2_footer()}
{_v2_bottom_nav('prem')}
</body></html>"""


def _forecast_date_nav(all_dates, all_weeks, current, prefix=""):
    """日付ナビバー。prefix は forecast/ への相対パス（forecast/area/ から呼ぶ場合は '../'）"""
    html = '<div class="date-nav">'
    for d in all_dates:
        m, dd = int(d[5:7]), int(d[8:10])
        wd_idx = datetime.strptime(d, "%Y-%m-%d").weekday()
        wd = ["月","火","水","木","金","土","日"][wd_idx]
        cls = " active" if d == current else ""
        cls += " weekend" if wd_idx >= 5 else ""
        html += f'<a href="{prefix}{d}.html" class="{cls.strip()}">{m}/{dd}({wd})</a>'
    for wk_id, wk in all_weeks.items():
        cls = " active" if wk_id == current else ""
        html += f'<a href="{prefix}{wk_id}.html" class="{cls.strip()}">{wk["label"]}</a>'
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
    pred_min = pred.get("min") if pred.get("min") is not None else max(1, round(avg * 0.6))
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


def _build_teaser_predictions(preds, free_count=1, max_count=5):
    """予測ティザーHTML: free_count件は完全表示、残りはblur+ペイウォール"""
    if not preds:
        return ''
    shown = preds[:max_count]
    total = len(preds)
    html = '<div class="st teaser-title"><span>釣果予測</span><span class="tag coming">有料プラン</span></div>'
    html += '<p class="section-note">海況・潮汐・過去実績から算出。上位1件は無料表示、残りは有料プランで閲覧できます。</p>'
    for i, pred in enumerate(shown):
        card = _forecast_combo_card(pred)
        if i < free_count:
            html += card
        else:
            html += f'<div style="filter:blur(5px);user-select:none;pointer-events:none;opacity:0.75">{card}</div>'
    hidden_count = total - free_count
    if hidden_count > 0:
        html += f'''<div class="paywall">
<p style="font-size:13px;color:#5a6a7a;margin-bottom:16px">残り<strong>{hidden_count}件</strong>の予測と詳細分析は有料プランで閲覧できます。</p>
<a href="/forecast/index.html" class="paywall-btn">月額500円で全て見る</a>
<p class="paywall-sub">スポット閲覧 100円〜 ・ 決済システム準備中</p>
</div>'''
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

    # エリア別チップ（リンク付き）— forecast/area/<slug>.html へ
    areas = day_data.get("areas", {})
    html += '<div class="area-chips">'
    for g, a in areas.items():
        s = a.get("score", 0)
        cls = "ok-good" if s >= 70 else "ok-fair" if s >= 45 else "ok-warn" if s >= 20 else "ok-bad"
        ok_mark = a.get("ok", "")
        html += f'<a href="area/{forecast_area_slug(g)}.html" class="area-chip {cls}">{g} {ok_mark}</a>'
    html += '</div>'

    preds = day_data.get("predictions", [])
    if not preds:
        html += '<p style="color:#7a9bb5">予測データなし</p>'
        html += _forecast_page_foot()
        return html

    html += _build_teaser_predictions(preds)
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

    week_preds = week_data.get("predictions", [])
    html += _build_teaser_predictions(week_preds)
    html += _forecast_page_foot()
    return html


def _area_sea_type(area_group):
    """エリアグループ名 → '内海' or '外海'"""
    return "内海" if area_group in _UCHIUMI_AREAS else "外海"

def _area_risk_grid(area_group, forecast_data):
    """エリア別出船リスクグリッドHTML（7日間）"""
    days_data = forecast_data.get("days", {})
    if not days_data:
        return ""
    sea_type = _area_sea_type(area_group)
    dow_jp = ["月","火","水","木","金","土","日"]
    cells = ""
    for date_str in sorted(days_data.keys())[:7]:
        try:
            dt = datetime.strptime(date_str, "%Y-%m-%d")
            dow = dow_jp[dt.weekday()]
            label_date = f"{dt.month}/{dt.day}"
        except:
            continue
        day_info = days_data[date_str]
        area_info = day_info.get("areas", {}).get(area_group, {})
        wave = area_info.get("wave") or day_info.get("wave") or 0
        wind = area_info.get("wind") or day_info.get("wind") or 0
        cls, icon, lbl = _risk_label(wave, wind, sea_type)
        cells += (
            f'<div class="risk-day {cls}">'
            f'<div class="rd-dow">{dow}</div>'
            f'<div class="rd-date">{label_date}</div>'
            f'<div class="rd-icon">{icon}</div>'
            f'<div class="rd-label">{lbl}</div>'
            f'</div>'
        )
    thr = _RISK_THR[sea_type]
    note = f'注意: 波{thr[0]}m・風{thr[1]}m/s / 欠航警戒: 波{thr[2]}m・風{thr[3]}m/s'
    return (
        f'<h2 class="st">出船リスク予報 <span class="tag free">無料</span></h2>'
        f'<p class="risk-note">閾値（{sea_type}基準）: {note}</p>'
        f'<div class="risk-grid">{cells}</div>'
    )

def _build_area_forecast_page(area_group, forecast_data):
    """エリア別予測ページHTML（forecast/area/<slug>.html）"""
    title = f"{area_group} 釣果予測"
    html = _forecast_page_head(title, depth_prefix="../../")
    all_dates = sorted(forecast_data.get("days", {}).keys())
    all_weeks = forecast_data.get("weeks", {})
    # forecast/area/ から forecast/<日付>.html へのリンクは ../ プレフィックスが必要
    html += _forecast_date_nav(all_dates, all_weeks, "", prefix="../")

    # 出船リスクグリッド（エリア固有閾値）
    html += _area_risk_grid(area_group, forecast_data)

    # 7日間サマリー（日付→日次ページリンク）
    html += f'<h2>{area_group} 予測</h2>'
    html += '<div class="date-nav">'
    area_anchor = forecast_area_slug(area_group)
    for d in all_dates:
        day = forecast_data["days"].get(d, {})
        area_info = day.get("areas", {}).get(area_group, {})
        ok = area_info.get("ok", "")
        m, dd = int(d[5:7]), int(d[8:10])
        wd_idx = datetime.strptime(d, "%Y-%m-%d").weekday()
        wd = ["月","火","水","木","金","土","日"][wd_idx]
        cls = " weekend" if wd_idx >= 5 else ""
        html += f'<a href="../{d}.html#area-{area_anchor}" class="{cls.strip()}">{m}/{dd}({wd}) {ok}</a>'
    html += '</div>'

    # 釣果予測は有料機能（準備中）
    html += '''
<div style="background:linear-gradient(135deg,#f8f4ff,#f0eafa);border:2px solid #7c3aed;border-radius:10px;padding:32px 16px;margin:24px 0;text-align:center">
<h2 style="font-size:18px;color:#7c3aed;margin-bottom:12px;border:none;padding:0">エリア別釣果予測（準備中）</h2>
<p style="font-size:13px;color:#5a6a7a;line-height:1.8;margin-bottom:18px">
このエリアの<strong>魚種別予測（匹数レンジ・サイズ・確信度）</strong>を準備中です。<br>
公開時は有料プランのみで提供予定です。
</p>
<div style="display:inline-block;padding:12px 32px;background:#7c3aed;color:#fff;border-radius:24px;font-weight:700;font-size:14px">準備中・公開時は月額500円</div>
</div>
'''
    html += _forecast_page_foot()
    return html


def _build_forecast_hub(forecast_data, catches=None):
    """有料トップページHTML（予測結果レポート＋チラ見せ＋料金）"""
    html = _forecast_page_head("釣果予測 プレミアム")

    html += '''
<div style="background:linear-gradient(135deg,#f8f4ff,#f0eafa);border:2px solid #7c3aed;border-radius:14px;padding:36px 24px;margin:24px 0;text-align:center">
<h2 style="font-size:20px;color:#7c3aed;margin-bottom:12px;border:none;padding:0">釣果予測 プレミアム</h2>
<p style="font-size:13px;color:#5a6a7a;line-height:1.9;margin-bottom:20px">
気象条件・潮通し・過去3年の実績データから算出する<strong>魚種別・エリア別の釣果予測</strong>です。<br>
日次予測（7日先）・週次予測（4週先）・エリア別ハブを提供します。
</p>
<ul style="display:inline-block;text-align:left;font-size:13px;color:#5a6a7a;line-height:1.9;margin-bottom:20px">
<li>日次予測: 匹数レンジ・サイズ・確信度・分析コメント</li>
<li>週次予測: 潮回り×季節傾向×直近実績</li>
<li>エリア別出船リスク予報（7日間）</li>
<li>船宿別 釣果ランキング＋予測</li>
</ul>
<p style="font-size:13px;color:#7c3aed;font-weight:700;margin-bottom:16px">月額500円 / スポット閲覧 100円〜</p>
<p style="font-size:11px;color:#8a96a4">決済システム整備中。下の日付から予測の一部を無料でプレビューできます。</p>
</div>
'''
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

    # エリア別ページ（V2ローマ字スラッグ。古いURLエンコード版があれば削除）
    forecast_area_dir = os.path.join(WEB_DIR, "forecast", "area")
    for _fn in os.listdir(forecast_area_dir):
        if "%" in _fn or any(ord(c) > 127 for c in _fn):
            os.remove(os.path.join(forecast_area_dir, _fn))
    for group in AREA_FORECAST_COORDS:
        html = _build_area_forecast_page(group, forecast_data)
        slug = forecast_area_slug(group)
        with open(os.path.join(WEB_DIR, f"forecast/area/{slug}.html"), "w", encoding="utf-8") as f:
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
          var rangeStr = (p.min!=null && p.min!==p.max) ? (p.min+'〜'+p.max) : p.max;
          h += '<div class="pred-range"><strong>'+rangeStr+'</strong> 匹</div>';
          if(p.best_area) h += '<div class="pred-area">📍 '+p.best_area+'</div>';
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
    # 「数匹」「数尾」等: 匹数欄に "数" + 単位 → 0〜2匹として扱う
    if re.search(r'数[匹尾本頭]', t):
        return {"min": 0, "max": 2, "is_boat": is_boat}
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
        now = datetime.now(JST).replace(tzinfo=None)
        fallback_date = f"{year}/{now.month:02d}/{now.day:02d}"
        return _parse_tables(parser.tables, ship, area, fallback_date, now.month)

    for box_html in boxes:
        # li.date から日付を取得
        date_m = re.search(r'<li[^>]+class="[^"]*date[^"]*"[^>]*>([^<]+)</li>', box_html)
        if date_m:
            date_str = date_m.group(1).strip()
            date = parse_jp_date(date_str, year)
            month = int(re.search(r'(\d{1,2})月', date_str).group(1)) if re.search(r'(\d{1,2})月', date_str) else datetime.now(JST).replace(tzinfo=None).month
        else:
            now = datetime.now(JST).replace(tzinfo=None)
            date = f"{year}/{now.month:02d}/{now.day:02d}"
            month = now.month

        # box内のテーブルをパース
        box_parser = TableParser()
        box_parser.feed(box_html)
        catches = _parse_tables(box_parser.tables, ship, area, date, month)

        # 【水温】【水色】をテーブル下テキストから抽出してレコードに付与
        box_text_plain = re.sub(r'<[^>]+>', ' ', box_html)
        suion_m = re.search(r'【水温】\s*([^\s【】]{1,20})', box_text_plain)
        suishoku_m = re.search(r'【水色】\s*([^\s【】]{1,20})', box_text_plain)
        box_suion = suion_m.group(1).strip() if suion_m else ""
        box_suishoku = suishoku_m.group(1).strip() if suishoku_m else ""
        if box_suion or box_suishoku:
            for c in catches:
                if not c.get("suion_raw"):
                    c["suion_raw"] = box_suion
                if not c.get("suishoku_raw"):
                    c["suishoku_raw"] = box_suishoku

        # div.color の生テキストを color_raw として保存
        color_div_m = re.search(r'<div[^>]+class="color"[^>]*>([\s\S]*?)</div>', box_html)
        if color_div_m:
            _ct = re.sub(r'<[^>]+>', '', color_div_m.group(1))
            _ct = re.sub(r'\s+', ' ', _ct).strip()
            box_color_raw = _ct if _ct else None
        else:
            box_color_raw = None
        for c in catches:
            if "color_raw" not in c:
                c["color_raw"] = box_color_raw

        # 感想テキストを trip_no で紐付け → kanso_raw に設定
        trip_comments = _extract_trip_comments(box_html)
        for c in catches:
            t = c.get("trip_no")
            if t is not None and t in trip_comments:
                c["trip_comment"] = trip_comments[t]["comment"]
            if not c.get("kanso_raw"):
                c["kanso_raw"] = c.get("trip_comment") or ""

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


def _extract_trip_comments(box_html):
    """choka_boxのHTMLからテーブル外の感想テキストを抽出。
    Returns: {1: {"comment": "LT五目。他に...", "trip_type": "LT五目"}, ...}
    """
    cm = re.search(r'<div[^>]+class="[^"]*choka_comment[^"]*"[^>]*>([\s\S]*?)</div>', box_html, re.I)
    if cm:
        source = cm.group(1)
    else:
        source = re.sub(r'<table[\s\S]*?</table>', '', box_html, flags=re.I)
    plain = re.sub(r'<[^>]+>', ' ', source)
    plain = ' '.join(plain.split())

    comments = {}
    for m in re.finditer(r'[■□]?(\d+)\s+([^■□\d][^■□]*?)(?=[■□]?\d+\s+[^■□\d]|$)', plain):
        trip_no = int(m.group(1))
        text = m.group(2).strip()
        if not text or len(text) <= 2:
            continue
        trip_type = None
        if not text.startswith("他に"):
            type_m = re.match(r'^([^\s。、・]{2,10})[\s。、]', text)
            if type_m:
                trip_type = type_m.group(1)
        comments[trip_no] = {"comment": text, "trip_type": trip_type}
    return comments


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
        tokki_idx  = next((i for i,h in enumerate(header) if "特記" in h), None)
        point_idx  = next((i for i,h in enumerate(header) if "ポイント" in h), None)
        trip_no_idx = 0 if fish_idx >= 1 else None

        current_trip_no = None
        for row in table[1:]:
            if len(row) <= fish_idx: continue
            if trip_no_idx is not None and trip_no_idx < len(row):
                tn_m = re.search(r'(\d+)', row[trip_no_idx])
                if tn_m:
                    current_trip_no = int(tn_m.group(1))
            fish_name = row[fish_idx].strip()
            if not fish_name or fish_name in ("魚種", "-", "－", ""): continue
            count_str  = row[count_idx].strip()  if count_idx  < len(row) else ""
            size_str   = row[size_idx].strip()   if size_idx   < len(row) else ""
            weight_str = row[weight_idx].strip() if weight_idx < len(row) else ""
            tokki_str  = row[tokki_idx].strip()  if tokki_idx is not None and tokki_idx < len(row) else ""
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
                "trip_no":     current_trip_no,
                "trip_comment": None,
                # V2 生文字列フィールド
                "count_raw":   count_str,
                "size_raw":    size_str,
                "weight_raw":  weight_str,
                "tokki_raw":   tokki_str,
                "point_raw":   point_str,
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
    now     = datetime.now(JST).replace(tzinfo=None)
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

_GROUP_TO_ANALYSIS_REGION = {
    "茨城":           "外房・茨城",
    "千葉・外房":     "外房・茨城",
    "千葉・内房":     "東京湾中部",
    "千葉・東京湾奥": "東京湾中部",
    "東京":           "東京湾中部",
    "神奈川・東京湾": "金沢八景・久里浜",
    "神奈川・相模湾": "相模湾東・三浦",
    "静岡":           "相模湾西",
}

def _port_to_analysis_region(area):
    """港名 → area_analysis の座標ベース地域名に変換"""
    coords_path = os.path.join("normalize", "area_coords.json")
    if os.path.exists(coords_path):
        try:
            with open(coords_path, encoding="utf-8") as f:
                area_coords = json.load(f)
            # 名称ゆれ対応: "久比里" → "久比里港" も試す
            coord = area_coords.get(area) or area_coords.get(area + "港")
            if coord:
                lat, lon = coord["lat"], coord["lon"]
                if lon >= 140.0:                                  return "外房・茨城"
                if 35.35 < lat <= 35.5 and lon < 140.0:          return "東京湾中部"
                if 35.2 < lat <= 35.35 and 139.5 <= lon < 140.0: return "金沢八景・久里浜"
                if lat <= 35.35 and lon < 139.5:                  return "相模湾西"
                if lat <= 35.35 and 139.5 <= lon < 140.0:        return "相模湾東・三浦"
        except Exception:
            pass
    # 座標で解決できなければ AREA_GROUPS グループ名経由でフォールバック
    group = _area_to_group(area)
    return _GROUP_TO_ANALYSIS_REGION.get(group)

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

def load_ship_romaji():
    """normalize/ship_romaji_map.json → {船宿名: slug}"""
    p = os.path.join("normalize", "ship_romaji_map.json")
    if not os.path.exists(p): return {}
    with open(p, encoding="utf-8") as f:
        return json.load(f)

def load_ship_info():
    """normalize/ship_info.json → {船宿名: {basic, vessel, reservation, season_strategy, access, features}}"""
    p = os.path.join("normalize", "ship_info.json")
    if not os.path.exists(p): return {}
    with open(p, encoding="utf-8") as f:
        return json.load(f)

# モジュールレベルで1回だけロード
_FISH_ROMAJI = load_fish_romaji()
_AREA_ROMAJI = load_area_romaji()
_SHIP_ROMAJI = load_ship_romaji()
_SHIP_INFO = load_ship_info()

# H2 (T22): 空ページ（noindex 対象）の romaji_slug を蓄積するセット
# _ship_build_page_html() が書き込み、build_sitemap() が参照して URL 除外に使う
_SHIP_NOINDEX_SLUGS: set = set()

def fish_slug(fish: str) -> str:
    """魚種名 → URL用ローマ字スラグ（マップ未登録時はそのまま返す）"""
    return _FISH_ROMAJI.get(fish, fish)

# URLスラグとフォルダ名が異なる魚種の上書きマップ
_FISH_IMG_OVERRIDES = {
    "ビシアジ":    "bishiaji",
    "シロアマダイ": "shiroamadai",
    "キハダマグロ": "kihadamaguro",
    "タイ五目":    "taigomoku",
    "モンゴウイカ": "mongouika",
    "沖カサゴ":    "okikasago",
    "沖メバル":    "okimebaru",
    "アブラボウズ": "aburabozu",
    "シマアジ":    "shimaaji",
}

def fish_img_slug(fish: str) -> str:
    """画像アセットフォルダ用スラグ（URLスラグとは別管理・フォルダ名と一致）"""
    return _FISH_IMG_OVERRIDES.get(fish, fish_slug(fish))

def area_slug(area: str) -> str:
    """エリア名 → URL用ローマ字スラグ（マップ未登録時はそのまま返す）"""
    return _AREA_ROMAJI.get(area, area)

FISH_KANJI: dict[str, str] = {
    "マダイ":       "真鯛",
    "アジ":         "鰺",
    "ビシアジ":     "錘鰺",
    "シロギス":     "白鱚",
    "ヒラメ":       "鮃",
    "カワハギ":     "皮剥",
    "タチウオ":     "太刀魚",
    "ワラサ":       "ワラサ",
    "ブリ":         "鰤",
    "イナダ":       "イナダ",
    "カツオ":       "鰹",
    "キハダマグロ": "黄肌鮪",
    "キメジ":       "木目地",
    "サワラ":       "鰆",
    "カンパチ":     "間八",
    "シイラ":       "鱪",
    "ムギイカ":     "麦烏賊",
    "スルメイカ":   "鯣烏賊",
    "ヤリイカ":     "槍烏賊",
    "スミイカ":     "墨烏賊",
    "マルイカ":     "丸烏賊",
    "アオリイカ":   "障泥烏賊",
    "モンゴウイカ": "紋甲烏賊",
    "スジイカ":     "条烏賊",
    "マダコ":       "真蛸",
    "カサゴ":       "笠子",
    "沖カサゴ":     "沖笠子",
    "オキカサゴ":   "沖笠子",
    "オニカサゴ":   "鬼笠子",
    "メバル":       "眼張",
    "沖メバル":     "沖眼張",
    "オキメバル":   "沖眼張",
    "キンメダイ":   "金目鯛",
    "アカムツ":     "赤鯥",
    "クロムツ":     "黒鯥",
    "メダイ":       "目鯛",
    "アマダイ":     "甘鯛",
    "シロアマダイ": "白甘鯛",
    "フグ":         "河豚",
    "トラフグ":     "虎河豚",
    "ショウサイフグ": "小西河豚",
    "アカメフグ":   "赤目河豚",
    "ヒラマサ":     "平政",
    "カレイ":       "鰈",
    "ホウボウ":     "魴鮄",
    "イサキ":       "伊佐木",
    "クロダイ":     "黒鯛",
    "シマアジ":     "縞鰺",
    "マハタ":       "真羽太",
    "ハタ":         "羽太",
    "メヌケ":       "目抜",
    "カマス":       "魳",
    "イシダイ":     "石鯛",
    "コハダ":       "小鰭",
    "アユ":         "鮎",
    "マゴチ":       "真鯒",
    "シーバス":     "鱸",
    "アラ":         "荒",
    "タイ五目":     "鯛五目",
}

def ship_slug(name: str) -> str:
    """船宿名 → URL用ローマ字スラグ（マップ未登録時はNone）"""
    return _SHIP_ROMAJI.get(name)

def _ship_link(name: str, depth: int = 1) -> str:
    """
    船宿名をリンク化。
    depth: HTMLからship/への相対パス階層（1=fish/area配下から、0=ルートから）
    リンク条件: ships.json に romaji_slug があるすべての船宿をリンク化。
    """
    slug = None
    # ships.json から slug を取得
    for ship in SHIPS:
        if ship.get("name") == name and ship.get("romaji_slug"):
            slug = ship.get("romaji_slug")
            break
    # フォールバック: _SHIP_ROMAJI から取得
    if not slug:
        slug = _SHIP_ROMAJI.get(name)
    if not slug:
        return name
    prefix = "../" * depth if depth > 0 else ""
    return f'<a href="{prefix}ship/{slug}.html">{name}</a>'

def _fish_area_link_or_fish(fish: str, area: str, depth: int = 1) -> str:
    """
    魚種×エリア用のリンク先を返す。
    fish_area/{slug}-{area}.html が存在すれば fish_area へ、無ければ fish/{slug}.html にフォールバック。
    depth: HTMLから docs/ への相対パス階層（1=fish/area/fish_area/ship 配下から、0=ルートから）

    ※ build_fish_area_pages を build_area_pages より先に実行することで、
       本日生成された fish_area ページが正しく検出される。
    """
    prefix = "../" * depth if depth > 0 else ""
    fa_rel = f"fish_area/{fish_slug(fish)}-{area_slug(area)}.html"
    if os.path.exists(os.path.join(WEB_DIR, fa_rel)):
        return f"{prefix}{fa_rel}"
    return f"{prefix}fish/{fish_slug(fish)}.html"

def current_iso_week():
    now = datetime.now(JST).replace(tzinfo=None)
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
# V2 旬シグナル / エリアカラーヘルパー
# ============================================================
def _fish_signal(fish: str, month: int):
    """旬シグナル (signal_key, signal_label) を返す（簡易版）"""
    peak = {
        "アジ":     [4,5,6,10,11],
        "シロギス": [5,6,7,8,9],
        "マダイ":   [4,5,10,11],
        "イサキ":   [6,7,8],
        "カツオ":   [7,8,9],
        "カワハギ": [10,11,12],
        "タチウオ": [7,8,9,10],
        "ヒラメ":   [10,11,12,1,2],
        "メバル":   [2,3,4],
        "アマダイ": [11,12,1,2],
    }
    late = {
        "メバル":   [5,6],
        "マダイ":   [6,7,8,9],
        "タチウオ": [11,12,1],
        "ヒラメ":   [3,4,5],
    }
    peaks = peak.get(fish, [])
    lates = late.get(fish, [])
    if month in peaks:
        return "peak", "旬ピーク"
    if month in lates:
        return "late", "終盤"
    adj = set()
    for m in peaks:
        adj.add((m - 2) % 12 + 1)
        adj.add(m % 12 + 1)
    if month in adj:
        return "season", "シーズン中"
    return "normal", "通常"

_EA_KEY = {
    "神奈川": "kanagawa", "横須賀": "kanagawa", "金沢": "kanagawa",
    "走水": "kanagawa", "久里浜": "kanagawa", "三浦": "kanagawa",
    "剣崎": "kanagawa", "城ヶ島": "kanagawa", "小網代": "kanagawa",
    "平塚": "kanagawa", "茅ヶ崎": "kanagawa", "江ノ島": "kanagawa",
    "東京": "tokyo", "湾奥": "tokyo", "浦安": "tokyo",
    "千葉": "chiba", "館山": "chiba", "富浦": "chiba",
    "大原": "chiba", "勝浦": "chiba", "銚子": "chiba",
    "九十九里": "chiba", "外房": "chiba", "内房": "chiba",
    "茨城": "ibaraki", "大洗": "ibaraki", "鹿島": "ibaraki",
    "静岡": "shizuoka", "沼津": "shizuoka", "焼津": "shizuoka",
    "御前崎": "shizuoka",
}

def _area_ea_key(area_name: str) -> str:
    """エリア名から CSS data-ea 値を返す"""
    for k, v in _EA_KEY.items():
        if k in area_name:
            return v
    return "gaiwan"

# ============================================================
# V2 デザイン共通 CSS
# ============================================================
V2_COMMON_CSS = """@import url('https://fonts.googleapis.com/css2?family=Outfit:wght@800&display=swap');
:root{
  --bg:#f5f7fa;--card:#fff;--border:#d0d8e0;
  --text:#1a2332;--sub:#5a6a7a;--muted:#8a96a4;
  --accent:#0d2b4a;--accent2:#163d5c;--cta:#e85d04;--cta2:#d04e00;
  --pos:#1a9d56;--neg:#d43333;--warn:#d4a017;--prem:#7c3aed;
  --hdr:#0d2b4a;--nav:#f0f3f7;--line:#06c755;
  --teal:#00bfa5;
  --ea-kanagawa:#1a6fb5;
  --ea-tokyo:#0d2b4a;
  --ea-chiba:#16a34a;
  --ea-ibaraki:#dc2626;
  --ea-shizuoka:#d97706;
  --ea-gaiwan:#7c3aed;
  --sig-peak:#ffc107;
  --sig-season:#00bfa5;
  --sig-normal:#8a96a4;
  --sig-late:#ff6b6b;
  --r:10px;--mx:900px;
}
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
body{font-family:system-ui,-apple-system,"Hiragino Sans",sans-serif;background:var(--bg);color:var(--text);line-height:1.6;padding-bottom:60px}
a{color:var(--cta);text-decoration:none}a:hover{text-decoration:underline}
.c{max-width:var(--mx);margin:0 auto;padding:0 14px}
header{background:var(--hdr);color:#fff;padding:12px 20px;border-bottom:3px solid var(--cta)}
header .inner{max-width:var(--mx);margin:0 auto;display:flex;justify-content:space-between;align-items:center}
header h1{font-size:19px;font-weight:700}header h1 span{color:var(--cta)}a.site-logo{text-decoration:none;color:inherit}a.site-logo:hover{opacity:.8;text-decoration:none}
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
.cta-btn{display:inline-block;padding:10px 20px;background:var(--cta);color:#fff;border-radius:22px;font-size:13px;font-weight:700;text-decoration:none}
.cta-btn:hover{background:var(--cta2);text-decoration:none}
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
.sm-lc-0{background:#eef2f5}
.sm-lc-1{background:#c8e6c9}
.sm-lc-2{background:#66bb6a}
.sm-lc-3{background:#388e3c}
.sm-lc-4{background:#1b5e20}
.season-bar{display:flex;gap:2px;margin-top:8px;justify-content:center;flex-wrap:wrap}
.sb-cell{min-width:22px;height:20px;border-radius:4px;font-size:10px;color:#fff;display:flex;align-items:center;justify-content:center;padding:0 3px}
.sb-cell.peak-count{background:var(--cta)}.sb-cell.peak-size{background:#7209b7}
.sb-cell.mid{background:var(--accent)}.sb-cell.low{background:#d0d8e0;color:#8a96a4}
.sb-cell.now{outline:2px solid var(--text);outline-offset:1px}
.sb-legend{font-size:9px;color:var(--muted);text-align:center;margin-top:3px}
.leg-count{color:var(--cta)}.leg-size{color:#7209b7;margin-left:6px}
.area-season{background:var(--card);border:1px solid var(--border);border-radius:var(--r);padding:14px;margin-bottom:16px}
.as-wrap{overflow-x:auto}
.as-table{border-collapse:separate;border-spacing:3px;min-width:220px}
.as-table th{font-size:10px;color:var(--muted);font-weight:600;text-align:center;padding:2px 4px}
.as-th-fish{font-size:11px;font-weight:700;color:var(--sub);text-align:left;padding-right:8px;white-space:nowrap}
.as-th-fish .as-emoji{width:16px;height:16px;object-fit:contain;vertical-align:-3px;margin-right:4px}
.as-cell{width:36px;height:22px;border-radius:3px;font-size:9px;font-weight:700;text-align:center;vertical-align:middle}
.as-cell[data-v="-1"]{background:#f0f0f0;opacity:.4}
.as-cell[data-v="0"]{background:#eef2f5;color:var(--muted)}
.as-cell[data-v="1"]{background:#c8e6c9;color:#2e7d32}
.as-cell[data-v="2"]{background:#66bb6a;color:#fff}
.as-cell[data-v="3"]{background:#388e3c;color:#fff}
.as-cell[data-v="4"]{background:#1b5e20;color:#fff}
.as-legend{display:flex;align-items:center;gap:6px;margin-top:8px;font-size:10px;color:var(--muted)}
.as-lc{width:14px;height:14px;border-radius:2px;display:inline-block}
.as-lc-0{background:#eef2f5}
.as-lc-1{background:#c8e6c9}
.as-lc-2{background:#66bb6a}
.as-lc-3{background:#388e3c}
.as-lc-4{background:#1b5e20}
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
.faq-block-ttl{font-size:11px;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:.06em;padding:10px 0 6px;border-bottom:1px solid var(--border);margin-bottom:2px}
.faq-block-ttl:first-child{padding-top:2px}
.faq-block-ttl--common{margin-top:10px}
.faq-src{display:block;font-size:10px;color:var(--muted);margin-top:6px;line-height:1.5}
.faq-src-link{color:var(--muted);text-decoration:underline;text-decoration-style:dotted}
.faq-src-link:hover{color:var(--sub)}
.overview{background:var(--card);border:1px solid var(--border);border-radius:var(--r);padding:14px;margin-bottom:16px}
.overview-title{font-size:11px;font-weight:700;color:var(--sub);margin-bottom:6px}
.overview-body{font-size:13px;color:var(--text);line-height:1.8}
ins.adsbygoogle{display:block;min-height:0 !important;height:auto !important}
ins.adsbygoogle[data-ad-status="unfilled"]{display:none !important}
@media(min-width:769px){.bn{display:none}body{padding-bottom:0}}
@media(max-width:640px){header{padding:10px 14px}.stat-cards{grid-template-columns:1fr 1fr}table{font-size:11px}th,td{padding:5px 4px}.bar-wrap{width:50px}}"""

# ============================================================
# V2 ビルダー関数
# ============================================================

def _format_date_label(date_str: str) -> str:
    """YYYY/MM/DD → 'M/D(曜)' 形式（例: 4/25(金)）"""
    try:
        dt = datetime.strptime(date_str, "%Y/%m/%d")
        wday = "月火水木金土日"[dt.weekday()]
        return f"{dt.month}/{dt.day}({wday})"
    except (ValueError, TypeError):
        return date_str

def _resolve_display_dataset(catches, today_str):
    """
    当日データありなら (today_catches, 'M/D(曜)', today_str)
    なければ catches 内の最新日にフォールバック → (latest_catches, 'M/D(曜)', latest_date)
    両者とも0件なら (catches, '—', today_str)
    T19(2026/05/09): 常にデータ日付ラベルを返す（「今日」は誤認の原因になるため廃止）
    """
    today_catches = [c for c in catches if c.get("date") == today_str]
    if today_catches:
        return today_catches, _format_date_label(today_str), today_str
    dates = [c["date"] for c in catches if c.get("date")]
    if not dates:
        return catches, "—", today_str
    latest_date = max(dates)
    latest_catches = [c for c in catches if c.get("date") == latest_date]
    return latest_catches, _format_date_label(latest_date), latest_date

def _v2_header_nav(active_page=""):
    """V2共通ヘッダー + グローバルナビ"""
    return f"""<header>
  <div class="inner">
    <a href="/index.html" class="site-logo"><h1>船釣り<span>予想</span></h1></a>
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

def _load_prediction_log_one():
    """R5 (2026/05/06): prediction_log から「答え合わせ」用に1件取得。
    1) analysis.sqlite が存在すればそこから直接（local dev 経路）
    2) なければ analysis/V2/results/prediction_log_recent.json から（CI 経路）
    3) 両方ない場合は None（teaser placeholder にフォールバック）

    返却: dict {target_date, fish, ship, pred_pct, actual_pct, is_good_hit,
                fcast_wave, fcast_wind, fcast_sst, ...} or None
    """
    base = os.path.dirname(__file__) or "."
    sqlite_path = os.path.join(base, "analysis", "V2", "results", "analysis.sqlite")
    json_path = os.path.join(base, "analysis", "V2", "results", "prediction_log_recent.json")
    # 1) sqlite 経路
    if os.path.exists(sqlite_path):
        try:
            import sqlite3
            conn = sqlite3.connect(sqlite_path)
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute("""
                SELECT target_date, fish, ship, pred_pct, actual_pct, is_good_hit,
                       fcast_wave, fcast_wind, fcast_sst, fcast_temp,
                       pred_cnt_min, pred_cnt_max, actual_cnt_min, actual_cnt_max, horizon
                FROM prediction_log
                WHERE is_good_hit IS NOT NULL AND pred_pct IS NOT NULL AND actual_pct IS NOT NULL
                  AND ABS(pred_pct) > 1.0 AND ABS(actual_pct) > 1.0
                ORDER BY
                    CASE WHEN is_good_hit=1 THEN 0 ELSE 1 END,
                    ABS(pred_pct - actual_pct) ASC,
                    target_date DESC
                LIMIT 1
            """)
            r = cur.fetchone()
            conn.close()
            if r:
                return dict(r)
        except Exception as e:
            print(f"prediction_log sqlite read failed: {e}")
    # 2) JSON フォールバック
    if os.path.exists(json_path):
        try:
            with open(json_path, encoding="utf-8") as f:
                payload = json.load(f)
            recs = payload.get("records", [])
            if recs:
                return recs[0]
        except Exception as e:
            print(f"prediction_log_recent.json read failed: {e}")
    return None


def build_top_combos_html(catches_for_summary, history, now):
    """今週よく釣れているコンボ TOP3 — 直近1週間 (魚種×エリア) の事実集計。
    R3 (2026/05/06): HERO直下に結論型パネルを追加し、件数・船宿数・先週比を表示。
    無料=事実 境界遵守: 件数・先週比のみで理由解釈・★評価は載せない。

    R3-fix (2026/05/06): 「見どころ」名は減少コンボが入ると違和感があるため
    「今週よく釣れているコンボ」に変更。平日釣行者も含めて訴求。
    選定ロジック: 件数 TOP10 → 先週比+優先（先週比+ で3件揃ったらそこで終了、
    足りなければ件数順で補充）→ TOP3
    """
    today_str = now.strftime("%Y/%m/%d")
    cutoff_str = (now - timedelta(days=6)).strftime("%Y/%m/%d")
    # 直近1週間 (fish, area) → set of (ship, date)
    combo = {}
    for c in catches_for_summary:
        d = c.get("date")
        if not d or d < cutoff_str or d > today_str:
            continue
        for f in c.get("fish", []):
            if f == "不明":
                continue
            key = (f, c.get("area"))
            combo.setdefault(key, set()).add((c.get("ship"), d))
    if not combo:
        return ""
    # 先週同期間 (8〜14日前)
    prev_now = now - timedelta(days=7)
    try:
        prev_recs = _load_recent_catches_for_index(prev_now, days=7)
    except Exception:
        prev_recs = []
    prev_cutoff = (prev_now - timedelta(days=6)).strftime("%Y/%m/%d")
    prev_today = prev_now.strftime("%Y/%m/%d")
    prev_combo = {}
    for c in prev_recs:
        d = c.get("date")
        if not d or d < prev_cutoff or d > prev_today:
            continue
        for f in c.get("fish", []):
            if f == "不明":
                continue
            key = (f, c.get("area"))
            prev_combo.setdefault(key, set()).add((c.get("ship"), d))
    # 選定: 件数 TOP10 から先週比+ を優先で3件、足りなければ件数順で補充
    top10 = sorted(combo.items(), key=lambda x: -len(x[1]))[:10]
    positive = []  # 先週比 ≥ 0% or 先週データ無し
    negative = []  # 先週比 < 0%
    for key, records in top10:
        cnt = len(records)
        prev_cnt = len(prev_combo.get(key, set()))
        pct = None if prev_cnt == 0 else (cnt - prev_cnt) / prev_cnt * 100
        if pct is None or pct >= 0:
            positive.append((key, records, pct))
        else:
            negative.append((key, records, pct))
    selected = (positive + negative)[:3]
    if not selected:
        return ""
    cards = []
    for (fish, area), records, pct in selected:
        cnt = len(records)
        ships = len(set(r[0] for r in records))
        wow_html = ""
        if pct is not None:
            pct_int = round(pct)
            cls = "up" if pct_int > 0 else "dn" if pct_int < 0 else "flat"
            sign = "+" if pct_int >= 0 else ""
            wow_html = f' <span class="topc-wow {cls}">先週比 {sign}{pct_int}%</span>'
        # リンク先: fish_area ページがあればそこ、無ければ fish ページ
        target = _fish_area_link_or_fish(fish, area, depth=0)
        cards.append(
            f'<a class="topc-card" href="{target}">'
            f'<div class="topc-fish"><img src="assets/fish/{fish_img_slug(fish)}/{fish_img_slug(fish)}_emoji.webp" '
            f'alt="" class="topc-emoji" width="20" height="20" loading="lazy" decoding="async" '
            f'onerror="this.style.display=\'none\'">{fish} × {area}</div>'
            f'<div class="topc-stats">{cnt}件・{ships}船宿{wow_html}</div>'
            f'</a>'
        )
    return (
        '<h2 class="st">今週よく釣れている 魚×エリア <span class="tag free">無料</span><span class="topc-period">直近1週間集計</span></h2>'
        '<div class="topc-grid">' + "".join(cards) + '</div>'
    )


def build_teaser_rotator_html():
    """有料機能プレビュー ローテーターパネル（index.html用）

    R5 (2026/05/06): スライド1を prediction_log の実データで本物化。
    答え合わせ済みコンボ（is_good_hit=1）を1件取得して的中バッジ付きで表示。
    データ取得失敗時は従来の準備中表示にフォールバック（regression防止）。
    """
    # R5: prediction_log から答え合わせ1件
    pl = _load_prediction_log_one()
    if pl:
        # 実データ表示
        target_date = pl.get("target_date", "").replace("/", "-")
        fish = pl.get("fish", "")
        ship = pl.get("ship", "")
        pred_pct = pl.get("pred_pct", 0)
        actual_pct = pl.get("actual_pct", 0)
        is_hit = pl.get("is_good_hit", 0) == 1
        f_wave = pl.get("fcast_wave")
        f_wind = pl.get("fcast_wind")
        f_sst = pl.get("fcast_sst")
        # バッジ
        badge_html = (
            '<span style="color:var(--pos);font-size:10px;margin-left:6px;font-weight:700">的中</span>'
            if is_hit else
            '<span style="color:var(--neg);font-size:10px;margin-left:6px;font-weight:700">ハズレ</span>'
        )
        # pred/actual 表示
        def _pct_str(v):
            sign = "+" if (v is not None and v >= 0) else ""
            return f"{sign}{v:.1f}%" if v is not None else "—"
        # 気象要因メッセージ
        wx_parts = []
        if f_wave is not None: wx_parts.append(f"波{f_wave:.1f}m")
        if f_wind is not None: wx_parts.append(f"風{f_wind:.1f}m/s")
        if f_sst is not None: wx_parts.append(f"SST{f_sst:.1f}℃")
        wx_str = " / ".join(wx_parts) if wx_parts else "予報詳細あり"
        slide1_real = f'''<div class="tr-slide is-active">
      <div class="teaser-head">
        <span class="teaser-badge soon" style="background:var(--pos)">実例</span>
        <span class="teaser-title-in">予測の答え合わせ — 実例公開中</span>
      </div>
      <div class="teaser-desc">過去約10万件の船宿釣果に、風・波・潮・水温を重ねて判定しています。<strong>外れた予測も毎日公開</strong>します。</div>
      <div style="position:relative">
        <div class="teaser-dummy" style="filter:none;opacity:1"><div class="td-fish">{fish} × {ship}{badge_html}</div><div class="td-range">予想 {_pct_str(pred_pct)} → 実績 {_pct_str(actual_pct)}</div><div class="td-reason">{target_date} 予報: {wx_str}</div></div>
        <div class="teaser-dummy"><div class="td-fish">マダイ <span class="td-star">★★★★☆</span></div><div class="td-range">0〜5匹 / 30〜55cm</div><div class="td-reason">中潮×SST適温。剣崎・久里浜が狙い目</div></div>
        <div class="teaser-overlay" style="align-items:flex-end;padding-bottom:8px"><div class="coming-soon-panel" style="background:rgba(13,43,74,.92)"><div class="cs-title">詳細予測は有料</div><ul class="cs-features"><li>匹数レンジ・サイズ範囲</li><li>2・3・4週先の予測</li><li>気象×潮汐で自動算出</li></ul><div class="cs-price">月額<em>500円</em> / 1回<em>100円</em></div></div></div>
      </div>
    </div>'''
    else:
        # フォールバック: 従来の準備中表示
        slide1_real = '''<div class="tr-slide is-active">
      <div class="teaser-head">
        <span class="teaser-badge soon">開発中</span>
        <span class="teaser-title-in">今週の狙い目 — 週末TOP5魚種</span>
      </div>
      <div class="teaser-desc">過去約10万件の船宿釣果に、風・波・潮・水温を重ねて<strong>今週末の狙い目魚種・エリア</strong>を判定しています。<strong>外れた予測も毎日公開</strong>します。</div>
      <div style="position:relative">
        <div class="teaser-dummy"><div class="td-fish">アジ <span class="td-star">★★★★★</span></div><div class="td-range">25〜45匹 / 18〜25cm</div><div class="td-reason">大潮×水温上昇×波穏やか。金沢八景推奨</div></div>
        <div class="teaser-dummy"><div class="td-fish">マダイ <span class="td-star">★★★★☆</span></div><div class="td-range">0〜5匹 / 30〜55cm</div><div class="td-reason">中潮×SST適温。剣崎・久里浜が狙い目</div></div>
        <div class="teaser-overlay"><div class="coming-soon-panel"><div class="cs-title">準備中</div><ul class="cs-features"><li>今週 日毎の釣果予測</li><li>2・3・4週先の釣果予測</li><li>気象×潮汐で自動算出</li></ul><div class="cs-price">月額<em>500円</em> / 1回<em>100円</em></div></div></div>
      </div>
    </div>'''
    return f"""<h2 class="st teaser-title">有料機能プレビュー <span class="tag coming">まもなく公開</span></h2>
<div class="teaser-rotator">
  <div class="tr-track">
    {slide1_real}
    <div class="tr-slide">
      <div class="teaser-head">
        <span class="teaser-badge soon">開発中</span>
        <span class="teaser-title-in">予測の答え合わせ — 予測 vs 実績</span>
      </div>
      <div class="teaser-desc"><strong>前日の予測</strong>が実際の釣果と一致したかを毎日公開。「なぜ当たった・外れたか」を正直レポート。</div>
      <div style="position:relative">
        <div class="teaser-dummy"><div class="td-fish">アジ <span style="color:var(--pos);font-size:10px;margin-left:6px">的中</span></div><div class="td-range">予想 25〜42匹 → 実績 20〜48匹</div><div class="td-reason">水温○ / 風速○ / 波高○ 予報通りで好条件持続</div></div>
        <div class="teaser-dummy"><div class="td-fish">マダイ <span style="color:var(--neg);font-size:10px;margin-left:6px">ハズレ</span></div><div class="td-range">予想 2〜8匹 → 実績 0〜3匹</div><div class="td-reason">水温× 予報より1.5℃低下で活性低下</div></div>
        <div class="teaser-overlay"><div class="coming-soon-panel"><div class="cs-title">準備中</div><ul class="cs-features"><li>先週の予測 vs 実績比較</li><li>予測精度スコア</li><li>外れた理由の解説</li></ul><div class="cs-price">月額<em>500円</em> / 1回<em>100円</em></div></div></div>
      </div>
    </div>
    <div class="tr-slide">
      <div class="teaser-head">
        <span class="teaser-badge soon">開発中</span>
        <span class="teaser-title-in">分析・予測 — 注目の魚×エリア・急落速報</span>
      </div>
      <div class="teaser-desc"><strong>魚種×エリアの組合せ</strong>を独自スコアリング。「来週のどの日に何が釣れるか」を日別で予測。</div>
      <div style="position:relative">
        <div class="teaser-dummy"><div class="td-fish">注目: アジ × 金沢八景</div><div class="td-range">スコア 92 / 平年比 +38%</div><div class="td-reason">大潮×SST18.5℃×波0.8m でベスト条件</div></div>
        <div class="teaser-dummy"><div class="td-fish">急落: タチウオ × 走水</div><div class="td-range">先週比 -45%</div><div class="td-reason">水温急低下でベイトが抜けた模様</div></div>
        <div class="teaser-overlay"><div class="coming-soon-panel"><div class="cs-title">準備中</div><ul class="cs-features"><li>日別釣果予測（7日先）</li><li>気象相関グラフ</li><li>急上昇・急落 魚×エリア通知</li></ul><div class="cs-price">月額<em>500円</em> / 1回<em>100円</em></div></div></div>
      </div>
    </div>
  </div>
  <div class="tr-dots">
    <button class="tr-dot is-active" aria-label="スライド1"></button>
    <button class="tr-dot" aria-label="スライド2"></button>
    <button class="tr-dot" aria-label="スライド3"></button>
  </div>
  <div class="teaser-cta-wrap">
    <div class="teaser-cta-msg">現在開発中。<strong>有料プランページ</strong>で最新の釣果予測をご確認ください。</div>
    <div class="teaser-cta-btns"><a class="cta-btn" href="/forecast/index.html">今週末、どこに乗るべきか見る → 1回100円</a></div>
    <div class="teaser-price">※ 全機能まとめて <em>月額500円</em> / スポット <em>1回100円</em></div>
  </div>
</div>"""

def build_index_overview_text(catches, history, crawled_at="", hero_label=""):
    """今日の関東船釣り概況テキスト（200〜300字）を生成"""
    now = datetime.now(JST).replace(tzinfo=None)
    today_str = now.strftime("%Y/%m/%d")
    year, week_num = current_iso_week()
    # 今日分のみで集計
    today_catches = [c for c in catches if c.get("date") == today_str]
    base = today_catches if today_catches else catches  # 今日データなければ全件フォールバック
    # R8 (2026/05/06): フォールバック時は集計期間を明示（直近1週間（4/30〜5/6）等）
    if today_catches:
        label = "本日"
    else:
        # 集計期間を records から実際のmin/max日付で算出
        dates_in_base = sorted(set(c.get("date") for c in base if c.get("date")))
        if dates_in_base:
            try:
                d_min = datetime.strptime(dates_in_base[0], "%Y/%m/%d")
                d_max = datetime.strptime(dates_in_base[-1], "%Y/%m/%d")
                label = f"直近1週間（{d_min.month}/{d_min.day}〜{d_max.month}/{d_max.day}）"
            except Exception:
                label = "直近"
        else:
            label = "直近"
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
    # T19: hero_label 未渡し時は today_str から算出（呼び出し順の制約があるため）
    h2_label = hero_label if hero_label else _format_date_label(today_str)
    return (
        f'<h2 class="st">{h2_label}の関東船釣り概況 <span class="tag free">無料</span></h2>'
        f'<div class="overview">'
        f'<div class="overview-title">{title_str} — {len(areas_set)}エリア・{len(ships_set)}船宿から集計</div>'
        f'<div class="overview-body">{body}</div>'
        f'</div>'
    )

def _to_relative_levels(avgs: list) -> list:
    """月別平均値リストを魚種内の相対ランクで0〜4に変換する"""
    mx = max(avgs) if avgs else 0
    mn = min(avgs) if avgs else 0
    rng = mx - mn
    if mx == 0:
        return [0] * len(avgs)
    if rng < 10:
        # 変動幅が小さい（型釣りスコア等）→ 絶対値で低・中・高を判定
        return [2 if v >= mx * 0.9 else 1 if v >= mx * 0.5 else 0 for v in avgs]
    levels = []
    for v in avgs:
        norm = (v - mn) / rng
        if norm >= 0.80:   lv = 4
        elif norm >= 0.60: lv = 3
        elif norm >= 0.35: lv = 2
        elif norm >= 0.15: lv = 1
        else:              lv = 0
        levels.append(lv)
    return levels

def _decadal_to_monthly_index(fish_decades: dict) -> list:
    """36旬のcnt_indexを12か月平均に変換して返す（魚種内相対スケール0〜4）"""
    avgs = []
    for m in range(1, 13):
        d1 = (m - 1) * 3 + 1
        vals = [fish_decades.get(d, {}).get("cnt_index", 0) for d in (d1, d1+1, d1+2)]
        avgs.append(sum(vals) / 3)
    return _to_relative_levels(avgs)

def _decadal_to_monthly_size_index(fish_decades: dict) -> list:
    """36旬のsize_indexを12か月平均に変換して返す（魚種内相対スケール0〜4）"""
    avgs = []
    for m in range(1, 13):
        d1 = (m - 1) * 3 + 1
        vals = [fish_decades.get(d, {}).get("size_index", 0) for d in (d1, d1+1, d1+2)]
        avgs.append(sum(vals) / 3)
    return _to_relative_levels(avgs)

def build_combo_season_map_html(fish, area, hist_rows, current_month=None, decadal_calendar=None):
    """fish × area の旬カレンダー（数釣/型釣 × 12ヶ月 ヒートマップ）。
    fish_area ページ用に build_fish_season_map_html と同じフォーマットでコンボ別件数を描画する。

    優先順位:
    1. hist_rows × area で fish×area の月別件数（max>=3）
    2. hist_rows × 全エリアで fish 全体の月別件数（コンボ件数不足時の fallback）
    3. decadal_calendar / SEASON_DATA fallback（build_fish_season_map_html に委譲）
    """
    types = SEASON_TYPE.get(fish, [""] * 12)
    month_labels = ["1月","2月","3月","4月","5月","6月","7月","8月","9月","10月","11月","12月"]
    ths = "".join(f"<th>{m}</th>" for m in month_labels)
    counts = compute_combo_month_records(fish, area, hist_rows) if hist_rows else [0] * 12
    max_v = max(counts) if any(counts) else 0
    if max_v < 3:
        # コンボ件数が少ない場合は fish 全体の月別件数 fallback
        return build_fish_season_map_html(fish, decadal_calendar, current_month, hist_rows=hist_rows)
    cnt_levels = []
    size_levels = []
    for i in range(12):
        cnt = counts[i]
        ratio = cnt / max_v if max_v else 0
        if ratio >= 0.7:    lv = 4
        elif ratio >= 0.4:  lv = 3
        elif ratio >= 0.15: lv = 2
        elif cnt > 0:       lv = 1
        else:               lv = 0
        tp = types[i] if i < len(types) else ""
        if tp == "数" and lv >= 3:
            cnt_levels.append(lv)
            size_levels.append(max(0, lv - 1))
        elif tp == "型" and lv >= 3:
            cnt_levels.append(max(0, lv - 1))
            size_levels.append(lv)
        else:
            cnt_levels.append(lv)
            size_levels.append(lv)
    cnt_cells  = "".join(f'<td class="sm-cell" data-v="{lv}"></td>' for lv in cnt_levels)
    size_cells = "".join(f'<td class="sm-cell" data-v="{lv}"></td>' for lv in size_levels)
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
    <span class="sm-lc sm-lc-0"></span>なし
    <span class="sm-lc sm-lc-1"></span>渋
    <span class="sm-lc sm-lc-2"></span>普通
    <span class="sm-lc sm-lc-3"></span>良
    <span class="sm-lc sm-lc-4"></span>◎
  </div>
  <p style="font-size:11px;color:var(--muted);margin-top:6px">※ {area}での{fish}釣果データから集計（過去3年）</p>
</div>"""


def build_fish_season_map_html(fish, decadal_calendar, current_month=None, hist_rows=None):
    """魚種の旬カレンダー（12か月×数釣/型釣 ヒートマップ）。
    優先順位（2026/05/06 改修）:
    1. hist_rows（CSV から fish 全エリア合算の月別件数を計算）← 最優先
    2. decadal_calendar（analysis.sqlite 由来・cnt_index/size_index）
    3. SEASON_DATA + SEASON_TYPE（ハードコード fallback）
    """
    fish_decades = decadal_calendar.get(fish, {}) if decadal_calendar else {}
    month_labels = ["1月","2月","3月","4月","5月","6月","7月","8月","9月","10月","11月","12月"]
    ths = "".join(f"<th>{m}</th>" for m in month_labels)
    types = SEASON_TYPE.get(fish, [""] * 12)
    # 2026/05/06: hist_rows を最優先で使用
    hist_counts = None
    if hist_rows:
        hc = compute_fish_month_records(fish, hist_rows)
        if max(hc) >= 5:
            hist_counts = hc
    if hist_counts is not None:
        cnt_levels = []
        size_levels = []
        max_v = max(hist_counts)
        for i in range(12):
            cnt = hist_counts[i]
            ratio = cnt / max_v if max_v else 0
            if ratio >= 0.7:    lv = 4
            elif ratio >= 0.4:  lv = 3
            elif ratio >= 0.15: lv = 2
            elif cnt > 0:       lv = 1
            else:               lv = 0
            tp = types[i] if i < len(types) else ""
            if tp == "数" and lv >= 3:
                cnt_levels.append(lv)
                size_levels.append(max(0, lv - 1))
            elif tp == "型" and lv >= 3:
                cnt_levels.append(max(0, lv - 1))
                size_levels.append(lv)
            else:
                cnt_levels.append(lv)
                size_levels.append(lv)
        cnt_cells  = "".join(f'<td class="sm-cell" data-v="{lv}"></td>' for lv in cnt_levels)
        size_cells = "".join(f'<td class="sm-cell" data-v="{lv}"></td>' for lv in size_levels)
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
    <span class="sm-lc sm-lc-0"></span>なし
    <span class="sm-lc sm-lc-1"></span>渋
    <span class="sm-lc sm-lc-2"></span>普通
    <span class="sm-lc sm-lc-3"></span>良
    <span class="sm-lc sm-lc-4"></span>◎
  </div>
  <p style="font-size:11px;color:var(--muted);margin-top:6px">※ 過去3年の関東船釣り釣果データより集計（2023〜2025年）</p>
</div>"""
    if not fish_decades:
        # SEASON_DATA + SEASON_TYPE fallback（hist_rows も decadal_calendar も無い場合）
        scores = SEASON_DATA.get(fish, [3] * 12)
        types  = SEASON_TYPE.get(fish, [""] * 12)
        month_labels = ["1月","2月","3月","4月","5月","6月","7月","8月","9月","10月","11月","12月"]
        ths = "".join(f"<th>{m}</th>" for m in month_labels)
        cnt_levels  = []
        size_levels = []
        for s, t in zip(scores, types):
            base = max(0, min(4, s - 1))
            if t == "数" and s >= 4:
                cnt_levels.append(base)
                size_levels.append(max(0, base - 1))
            elif t == "型" and s >= 4:
                cnt_levels.append(max(0, base - 1))
                size_levels.append(base)
            else:
                cnt_levels.append(base)
                size_levels.append(base)
        cnt_cells  = "".join(f'<td class="sm-cell" data-v="{lv}"></td>' for lv in cnt_levels)
        size_cells = "".join(f'<td class="sm-cell" data-v="{lv}"></td>' for lv in size_levels)
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
    <span class="sm-lc sm-lc-0"></span>なし
    <span class="sm-lc sm-lc-1"></span>渋
    <span class="sm-lc sm-lc-2"></span>普通
    <span class="sm-lc sm-lc-3"></span>良
    <span class="sm-lc sm-lc-4"></span>◎
  </div>
  <p style="font-size:11px;color:var(--muted);margin-top:6px">※ 過去3年の関東船釣り釣果データより集計（2023〜2025年）</p>
</div>"""
    cnt_levels   = _decadal_to_monthly_index(fish_decades)
    size_levels  = _decadal_to_monthly_size_index(fish_decades)
    month_labels = ["1月","2月","3月","4月","5月","6月","7月","8月","9月","10月","11月","12月"]
    ths = "".join(f"<th>{m}</th>" for m in month_labels)
    cnt_cells  = "".join(f'<td class="sm-cell" data-v="{lv}"></td>' for lv in cnt_levels)
    size_cells = "".join(f'<td class="sm-cell" data-v="{lv}"></td>' for lv in size_levels)
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
    <span class="sm-lc sm-lc-0"></span>なし
    <span class="sm-lc sm-lc-1"></span>渋
    <span class="sm-lc sm-lc-2"></span>普通
    <span class="sm-lc sm-lc-3"></span>良
    <span class="sm-lc sm-lc-4"></span>◎
  </div>
  <p style="font-size:11px;color:var(--muted);margin-top:6px">※ 過去3年の関東船釣り釣果データより集計（2023〜2025年）</p>
</div>"""

def build_area_season_map_html(area, area_decadal, top_fish_list, hist_rows=None):
    """エリアの魚種別旬カレンダー（魚種×12か月 ヒートマップ）

    データソース優先順位:
    1. area_decadal（analysis.sqlite 由来・cnt_index 集計値）
    2. hist_rows（CSV から fish×area の月別件数を計算）— 2026/05/06 追加
    3. SEASON_DATA（ハードコード fallback）

    （2）が hist_rows を渡せば動作。analysis.sqlite が無くても CSV からエリア×魚種
    の月別実態を反映できる。
    """
    # 港名で直接引けなければ座標→分析地域名に変換してlookup
    area_data = area_decadal.get(area) if area_decadal else None
    if area_data is None:
        region = _port_to_analysis_region(area)
        area_data = area_decadal.get(region, {}) if (area_decadal and region) else {}
    month_labels = ["1","2","3","4","5","6","7","8","9","10","11","12"]
    ths = "".join(f"<th>{m}</th>" for m in month_labels)
    rows = ""
    for fish in top_fish_list[:6]:
        fish_decades = area_data.get(fish, {})
        # area_decadal は cnt_index のみ
        cnt_levels = []
        # 2026/05/06: hist_rows を**最優先**で使用。area_decadal の cnt_index 集計値より
        # 実 CSV 件数の方が正確（cnt_index しきい値 50/90/130/160 が実態と乖離するケースあり）。
        hist_counts = None
        fallback_scores = None
        if hist_rows:
            hc = compute_combo_month_records(fish, area, hist_rows)
            if max(hc) >= 3:
                hist_counts = hc
        if hist_counts is None and not fish_decades:
            fallback_scores = SEASON_DATA.get(fish)
        for m in range(1, 13):
            if hist_counts is not None:
                # 実データ正規化: max=4, ratio>=0.7=4 / 0.4=3 / 0.15=2 / >0=1 / 0=0
                max_v = max(hist_counts)
                cnt = hist_counts[m - 1]
                ratio = cnt / max_v if max_v else 0
                if ratio >= 0.7:    lv = 4
                elif ratio >= 0.4:  lv = 3
                elif ratio >= 0.15: lv = 2
                elif cnt > 0:       lv = 1
                else:               lv = 0
            elif fallback_scores is not None:
                # SEASON_DATA score 1〜5 → level 0〜4
                lv = max(0, min(4, fallback_scores[m - 1] - 1))
            else:
                d1 = (m - 1) * 3 + 1
                d2 = d1 + 1
                d3 = d1 + 2
                raw_vals = [fish_decades.get(d) for d in (d1, d2, d3)]
                present = [v for v in raw_vals if v is not None]
                if not present:
                    # 部分データ欠落 → hist_rows があれば実データ計算
                    if hist_rows:
                        hc2 = compute_combo_month_records(fish, area, hist_rows)
                        if max(hc2) >= 3:
                            max_v = max(hc2)
                            cnt = hc2[m - 1]
                            ratio = cnt / max_v if max_v else 0
                            if ratio >= 0.7:    lv = 4
                            elif ratio >= 0.4:  lv = 3
                            elif ratio >= 0.15: lv = 2
                            elif cnt > 0:       lv = 1
                            else:               lv = 0
                        else:
                            sd = SEASON_DATA.get(fish)
                            lv = max(0, min(4, sd[m - 1] - 1)) if sd else -1
                    else:
                        sd = SEASON_DATA.get(fish)
                        lv = max(0, min(4, sd[m - 1] - 1)) if sd else -1
                else:
                    avg = sum(present) / len(present)
                    if avg >= 160:   lv = 4
                    elif avg >= 130: lv = 3
                    elif avg >= 90:  lv = 2
                    elif avg >= 50:  lv = 1
                    else:            lv = 0
            cnt_levels.append(lv)
        cells = "".join(f'<td class="as-cell" data-v="{lv}"></td>' for lv in cnt_levels)
        rows += f'<tr><th class="as-th-fish"><img src="../assets/fish/{fish_img_slug(fish)}/{fish_img_slug(fish)}_emoji.webp" alt="" class="as-emoji" width="16" height="16" loading="lazy" decoding="async" onerror="this.style.display=\'none\'">{fish}</th>{cells}</tr>\n'
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
    <span class="as-lc as-lc-0"></span>なし
    <span class="as-lc as-lc-1"></span>渋
    <span class="as-lc as-lc-2"></span>普通
    <span class="as-lc as-lc-3"></span>良
    <span class="as-lc as-lc-4"></span>◎
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

def build_fish_7day_chart_html(fish, catches, display_date=None, display_label=None):
    """直近7日間の釣果推移バーチャート（匹数上限）

    T19 (2026/05/09): base_date を「今日固定」から「データ最新日 (display_date)」に変更。
    display_date 未指定時のみ今日基準にフォールバック。
    HERO subline と最右列ラベルが常に同じデータ日付を指すようにする。
    """
    from datetime import datetime, timedelta
    today = datetime.now(JST).replace(tzinfo=None).date()
    base_date = display_date if display_date else today
    days = [(base_date - timedelta(days=i)) for i in range(6, -1, -1)]  # 6日前〜base_date
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
        cls = "cb today" if d == base_date else ("cb weekend" if d.weekday() >= 5 else "cb")
        bars.append(f'<div class="{cls}" style="height:{h}%"></div>')
    # ラベル: 最右列は M/D 形式（T19: 「今日」廃止・データ日付明示）
    # T20: today/weekend クラスをラベルにも付与（色覚補助）
    labels = []
    for d in days:
        _lcls_parts = []
        if d == base_date: _lcls_parts.append("today")
        if d.weekday() >= 5: _lcls_parts.append("weekend")
        _lcls = f' class="{" ".join(_lcls_parts)}"' if _lcls_parts else ""
        labels.append(f"<span{_lcls}>{d.month}/{d.day}</span>")
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

def _load_fixed_faq():
    """normalize/fixed_faq.json を読み込む。失敗時は空 dict を返す。"""
    import os as _os
    path = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "normalize", "fixed_faq.json")
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _faq_source_html(sources):
    """sources リストから出典 <small> HTML を生成する。空リストなら空文字。"""
    if not sources:
        return ""
    import html as _html
    import urllib.parse as _up
    links = []
    for url in sources:
        try:
            host = _up.urlparse(url).netloc
            # www. prefix を除去してドメイン部分を表示
            display = host.replace("www.", "") if host.startswith("www.") else host
        except Exception:
            display = url
        links.append(
            f'<a href="{_html.escape(url)}" target="_blank" rel="nofollow noopener noreferrer" class="faq-src-link">{_html.escape(display)}</a>'
        )
    joined = "、".join(links)
    return f'<small class="faq-src">出典: {joined}</small>'


def build_fixed_faq_html(scope_type, scope_key, fixed_faq_data):
    """
    固定FAQブロック (faq-static) を生成する。
    scope_type: "fish" or "area"
    scope_key : 魚種名 or エリア名
    fixed_faq_data: _load_fixed_faq() の戻り値
    戻り値: (html, faq_pairs)  faq_pairs = [(q, a), ...]
    """
    import html as _html
    common_items = fixed_faq_data.get("common", [])
    scoped_items = (fixed_faq_data.get(scope_type) or {}).get(scope_key, [])

    faq_pairs = []
    inner = ""

    # ── 固有FAQ ────────────────────────────────────────────
    if scoped_items:
        if scope_type == "fish":
            block_ttl = f"{_html.escape(scope_key)}船釣りの基礎知識"
        else:
            block_ttl = f"{_html.escape(scope_key)}を釣り場として知る"
        inner += f'<h3 class="faq-block-ttl">{block_ttl}</h3>\n'
        for item in scoped_items:
            q = item.get("q", "")
            a = item.get("a", "")
            sources = item.get("sources", [])
            src_html = _faq_source_html(sources)
            inner += (
                f'  <details><summary>{_html.escape(q)}</summary>'
                f'<p class="faq-ans">{_html.escape(a)}{src_html}</p></details>\n'
            )
            faq_pairs.append((q, a))

    # ── 共通FAQ ───────────────────────────────────────────
    if common_items:
        common_cls = "faq-block-ttl faq-block-ttl--common" if scoped_items else "faq-block-ttl"
        inner += f'<h3 class="{common_cls}">船釣り共通の基礎知識</h3>\n'
        for item in common_items:
            q = item.get("q", "")
            a = item.get("a", "")
            sources = item.get("sources", [])
            src_html = _faq_source_html(sources)
            inner += (
                f'  <details><summary>{_html.escape(q)}</summary>'
                f'<p class="faq-ans">{_html.escape(a)}{src_html}</p></details>\n'
            )
            faq_pairs.append((q, a))

    if not inner:
        return "", []

    scope_attr = _html.escape(f"{scope_type}-{scope_key}")
    html = f'<div class="faq-list faq-static" data-scope="{scope_attr}">\n{inner}</div>'
    return html, faq_pairs


def build_fish_fixed_faq_html(fish, fixed_faq_data):
    """
    M1 (T22): 魚種ページ用の固定FAQ。
    固有 FAQ（魚種別）のみを <details> で出力し、
    共通 9 問は faq.html へのリンクブロックに差し替える。
    戻り値: (html, faq_pairs)  faq_pairs は固有 FAQ の (q, a) のみ（JSON-LD 用）
    """
    import html as _html
    scoped_items = (fixed_faq_data.get("fish") or {}).get(fish, [])

    faq_pairs = []
    inner = ""

    if scoped_items:
        block_ttl = f"{_html.escape(fish)}船釣りの基礎知識"
        inner += f'<h3 class="faq-block-ttl">{block_ttl}</h3>\n'
        for item in scoped_items:
            q = item.get("q", "")
            a = item.get("a", "")
            sources = item.get("sources", [])
            src_html = _faq_source_html(sources)
            inner += (
                f'  <details><summary>{_html.escape(q)}</summary>'
                f'<p class="faq-ans">{_html.escape(a)}{src_html}</p></details>\n'
            )
            faq_pairs.append((q, a))

    # 共通 FAQ はリンクに差し替え（M1: 51 魚種 × 7 問の重複解消）
    # common_link は魚種ガイド直後（広告②の前）に配置するため、ここでは html に含めない。
    # build_fish_pages() 側でテンプレートに直接差し込む。

    if inner:
        html = f'<div class="faq-list faq-static" data-scope="fish-{_html.escape(fish)}">\n{inner}</div>'
    else:
        html = ""

    return html, faq_pairs


def build_fish_faq_html(fish, catches, decadal_calendar, site_url=""):
    """魚種別FAQ（データ駆動型）＋ FAQPage JSON-LD を返す (html, faq_pairs) のタプル"""
    # Q1: 旬はいつ？
    fish_decades = decadal_calendar.get(fish, {})
    if fish_decades:
        monthly_scores = {}
        for decade_no, data in fish_decades.items():
            month = ((decade_no - 1) // 3) + 1
            score = data.get("cnt_index", 0)
            if month not in monthly_scores:
                monthly_scores[month] = []
            monthly_scores[month].append(score)
        monthly_avg = {m: sum(s) / len(s) for m, s in monthly_scores.items()}
        top_3_months = sorted(monthly_avg.items(), key=lambda x: -x[1])[:3]
        if top_3_months:
            month_names = ["1月", "2月", "3月", "4月", "5月", "6月", "7月", "8月", "9月", "10月", "11月", "12月"]
            month_strs = [month_names[m - 1] for m, _ in sorted(top_3_months, key=lambda x: x[0])]
            q1_ans = f"直近のデータでは{month_strs[0]}・{month_strs[1] if len(month_strs) > 1 else ''}・{month_strs[2] if len(month_strs) > 2 else ''}が実績が多い傾向です。旬カレンダーで詳しい月別推移をご確認ください。"
        else:
            q1_ans = f"関東の{fish}船釣りの旬はエリアや年度によって異なります。このページの旬カレンダーで月別の釣れ具合をご確認ください。"
    else:
        q1_ans = f"関東の{fish}船釣りの旬はエリアや年度によって異なります。このページの旬カレンダーで月別の釣れ具合をご確認ください。"

    # Q2: 主なエリア
    if catches:
        area_counts = {}
        for c in catches:
            area = c.get("area", "")
            if area:
                area_counts[area] = area_counts.get(area, 0) + 1
        top_3_areas = sorted(area_counts.items(), key=lambda x: -x[1])[:3]
        if top_3_areas:
            area_strs = "、".join(f"{a}（{n}件）" for a, n in top_3_areas)
            q2_ans = f"直近の釣果データでは{area_strs}が主なエリアです。"
        else:
            q2_ans = f"神奈川・東京湾エリアをはじめ、千葉・外房、茨城など幅広いエリアで船が出ています。エリア別釣果ページで各エリアの状況をご確認ください。"
    else:
        q2_ans = f"神奈川・東京湾エリアをはじめ、千葉・外房、茨城など幅広いエリアで船が出ています。エリア別釣果ページで各エリアの状況をご確認ください。"

    # Q3: 一日の釣果
    if catches:
        _q3_crs = [c.get("count_range") for c in catches if c.get("count_range") and not c["count_range"].get("is_boat")]
        cnt_maxes = [cr["max"] for cr in _q3_crs if cr.get("max") is not None]
        cnt_mins  = [cr["min"] for cr in _q3_crs if cr.get("min") is not None]
        if cnt_mins and cnt_maxes:
            p25_val = sorted(cnt_mins)[int(len(cnt_mins) * 0.25)] if len(cnt_mins) >= 4 else min(cnt_mins)
            p75_val = sorted(cnt_maxes)[int(len(cnt_maxes) * 0.75)] if len(cnt_maxes) >= 4 else max(cnt_maxes)
            max_val = max(cnt_maxes)
            q3_ans = f"直近{len(catches)}件のデータでは{int(p25_val)}〜{int(p75_val)}匹が標準的なレンジです。最高実績は{int(max_val)}匹です。"
        elif cnt_maxes:
            max_val = max(cnt_maxes)
            q3_ans = f"直近データでは最高{int(max_val)}匹の実績があります。釣果は潮回り・季節によって変動します。"
        else:
            q3_ans = f"釣果は日・潮回り・季節によって大きく変動します。このページの最新釣果テーブルで実績をご確認ください。"
    else:
        q3_ans = f"釣果は日・潮回り・季節によって大きく変動します。このページの最新釣果テーブルで実績をご確認ください。"

    # Q4: 初心者向け（魚種別）
    _FISH_BEGINNER = {
        "アジ":       ("入門魚の定番", "ライトな仕掛けで数釣りを楽しめる入門向きの魚。食いが立てば初心者でもツ抜けが狙えます"),
        "サバ":       ("入門向け", "コマセ釣りで豪快な数釣りが楽しめます。引きも強く、釣りの醍醐味を存分に味わえます"),
        "キス":       ("入門〜中級", "天ぷらネタとして人気の魚。シンプルな仕掛けで楽しめますが、アタリを取る繊細さも醍醐味です"),
        "タコ":       ("入門向け", "底を叩くだけのシンプルな釣り。ファミリーフィッシングにも人気で、道具も比較的手軽です"),
        "マダイ":     ("中級者向け", "コマセを使ったビシ釣りが主流。繊細なアタリを取る楽しさがあり、釣れたときの達成感は格別です"),
        "ヒラメ":     ("中級者向け", "泳がせ釣りで大物を狙います。アタリからの「一呼吸」をおいてから合わせるのがコツです"),
        "マルイカ":   ("上級者向け", "直結仕掛けの操作が独特でテクニカルな釣り。習得に時間がかかりますが、釣れると病みつきになります"),
        "スルメイカ": ("入門〜中級", "ブランコ仕掛けならビギナーでも数釣りが楽しめます。夜釣りでの豪快な多点掛けが醍醐味です"),
        "カツオ":     ("入門〜中級", "コマセ釣りで豪快な引きを楽しめます。口切れしやすいので走られても慌てず一定のテンションを保つのがポイントです"),
        "キハダマグロ": ("上級者向け", "大型青物との長期戦。専用の強靭なタックルが必要で、体力・経験が問われる上級者向けの釣りです"),
        "シーバス":   ("中級者向け", "ルアーとエサ釣り両方が楽しめます。河川〜沖合まで幅広いフィールドで狙えるのも魅力です"),
        "カサゴ":     ("入門向け", "根魚の定番。底を丁寧に探るだけで釣れることも多く、初心者にも優しい魚です"),
        "メバル":     ("初級〜中級", "食い込みを待つ繊細な釣り。活性が高い時間帯を読むのが釣果を伸ばすコツです"),
        "アマダイ":   ("中級者向け", "深場を狙う高級魚。丁寧な底取りとゆっくりした誘い上げが重要で、釣れたときの喜びは大きいです"),
        "ワラサ":     ("中級者向け", "ブリの若魚で引きが豪快。体力勝負になる場面もあり、タックルはある程度しっかりしたものが必要です"),
        "ブリ":       ("中〜上級", "強烈な引きに耐えるタックル選びが重要。大型を仕留めたときの達成感は格別ですが、初心者には難易度高めです"),
        "サワラ":     ("中級者向け", "鋭い歯と独特の食い込み方が特徴。合わせのタイミングが難しいですが、スピード感あふれる引きが魅力です"),
        "タチウオ":   ("中級者向け", "テンヤ・コマセなど釣り方の幅が広い魚。銀色に輝く魚体と独特のアタリが病みつきになります"),
        "カワハギ":   ("上級者向け", "エサ取りの名手相手の高度な駆け引きが醍醐味。腕の差が如実に出る釣りで、熟練者ほどはまります"),
        "イサキ":     ("入門〜中級", "コマセ釣りで安定した釣果が期待でき、食味も抜群。数釣りと型釣りを両立できる人気ターゲットです"),
        "ハナダイ":   ("入門〜中級", "マダイより口が小さく繊細な食い込み。コマセ釣りで狙い、食味の良さも人気の理由です"),
        "クロダイ":   ("中級者向け", "警戒心が強く難易度は高め。潮の変わり目など時合いを読む経験が釣果に直結します"),
        "イナダ":     ("入門向け", "青物入門として最適。コマセで群れを引き寄せ、豪快な引きを楽しめます"),
        "カンパチ":   ("中〜上級", "パワフルな引きと根に潜る習性への対応が重要。大型を狙うほど難易度が上がります"),
        "シイラ":     ("中級者向け", "派手なジャンプと強烈な引きが特徴的なゲームフィッシュ。夏場の人気ターゲットです"),
    }
    ship_count = len(set(c.get("ship", "") for c in catches if c.get("ship"))) if catches else 0
    fish_info = _FISH_BEGINNER.get(fish)
    if fish_info:
        level, desc = fish_info
        ship_str = f"関東では{ship_count}船宿が出船実績あり。" if ship_count > 0 else ""
        q4_ans = f"難易度は{level}の釣りです。{desc}。{ship_str}多くの船宿でレンタルタックルや仕掛けの購入が可能です。"
    elif ship_count > 0:
        q4_ans = f"はい。現在{ship_count}船宿が出船実績があります。多くの船宿でレンタルタックルや仕掛けの購入が可能で、初心者でも安心して楽しめます。"
    else:
        q4_ans = f"はい。船宿スタッフのサポートも受けられます。竿・リールのレンタルができる船宿も多くあります。"

    faqs = [
        (f"{fish}の旬はいつですか？", q1_ans),
        (f"関東で{fish}の船釣りができる主なエリアはどこですか？", q2_ans),
        (f"{fish}の一日の釣果はどのくらいですか？", q3_ans),
        (f"初心者でも{fish}釣りは楽しめますか？", q4_ans),
    ]
    import html as _html_mod
    block_ttl = f"{_html_mod.escape(fish)}釣果データから分かること"
    html = f'<div class="faq-list faq-data">\n<h3 class="faq-block-ttl">{block_ttl}</h3>\n'
    for q, a in faqs:
        html += f'  <details><summary>{q}</summary><p class="faq-ans">{a}</p></details>\n'
    html += '</div>'
    return html, faqs

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

def build_area_description_html(area, desc_data):
    """area_description.json の description フィールドを段落に変換して返す。なければ空文字。"""
    ad = (desc_data.get(area) or {}) if desc_data else {}
    text = ad.get("description", "")
    if not text:
        return ""
    paras = [p.strip() for p in text.split("\n") if p.strip()]
    return '<div class="area-desc">' + "".join(f"<p>{p}</p>" for p in paras) + "</div>"


def build_area_faq_html(area, desc_data, area_coords=None, top_fish_items=None, area_catches=None):
    """エリア別FAQ（データ駆動型）＋ FAQPage+Place JSON-LD を返す (html, jsonld) のタプル"""
    ad = (desc_data.get(area) or {}) if desc_data else {}

    # Q1: 釣れる魚は何？
    if top_fish_items:
        top_3_str = "、".join(f"{f}（{r['records']}件）" for f, r in top_fish_items[:3])
        q1_ans = f"直近の釣果データでは{top_3_str}が中心です。"
    else:
        top_fish_str = ad.get("top_fish_text", "複数の魚種")
        q1_ans = f"{top_fish_str}が主力です。季節によって釣れる魚が変わります。旬カレンダーで月別の状況をご確認ください。"

    # Q2: アクセス方法
    if ad.get("access_summary"):
        q2_ans = ad.get("access_summary")
    elif ad.get("access_train") or ad.get("access_car"):
        q2_ans = (ad.get("access_train") or "") + ("、" if ad.get("access_train") and ad.get("access_car") else "") + (ad.get("access_car") or "")
    else:
        q2_ans = f"{area}への詳細なアクセスは各船宿のウェブサイトをご確認ください。"

    # Q3: おすすめの釣り物と時期
    if top_fish_items and top_fish_items[0]:
        top_f = top_fish_items[0][0]
        q3_ans = f"直近データでは{top_f}の実績が最多です。このページの旬カレンダーで各魚種の月別釣れ具合をご確認ください。"
    else:
        q3_ans = f"魚種によって旬が異なります。このページの旬カレンダーで各魚種の月別釣れ具合をご確認ください。"

    # Q4: よく出船する船宿
    if area_catches:
        ship_counts = {}
        for c in area_catches:
            ship = c.get("ship", "")
            if ship:
                ship_counts[ship] = ship_counts.get(ship, 0) + 1
        top_3_ships = sorted(ship_counts.items(), key=lambda x: -x[1])[:3]
        if top_3_ships:
            ship_strs = "、".join(f"{s}（{n}件）" for s, n in top_3_ships)
            q4_ans = f"直近の釣果では{ship_strs}などの実績が確認されています。"
        else:
            q4_ans = f"{area}の船宿一覧はこのページでご確認ください。"
    else:
        q4_ans = f"{area}の船宿一覧はこのページでご確認ください。"

    faqs = [
        (f"{area}で釣れる魚は何ですか？", q1_ans),
        (f"{area}エリアへのアクセス方法は？", q2_ans),
        (f"{area}でおすすめの釣り物と時期は？", q3_ans),
        (f"{area}でよく出船する船宿は？", q4_ans),
    ]
    import html as _html_mod2
    block_ttl2 = f"{_html_mod2.escape(area)}釣果データから分かること"
    html = f'<div class="faq-list faq-data">\n<h3 class="faq-block-ttl">{block_ttl2}</h3>\n'
    for q, a in faqs:
        html += f'  <details><summary>{q}</summary><p class="faq-ans">{a}</p></details>\n'
    html += '</div>'
    return html, faqs

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


def compute_fish_month_records(fish, hist_rows):
    """fish の過去CSV から月別件数を返す（list[12]・全エリア合算）"""
    counts = [0] * 12
    for r in hist_rows:
        if r.get("tsuri_mono") != fish:
            continue
        d = r.get("date", "")
        try:
            mm = int(d.split("/")[1])
            if 1 <= mm <= 12:
                counts[mm - 1] += 1
        except (ValueError, IndexError):
            continue
    return counts


def build_season_bar_from_fish_data(fish, hist_rows, current_month):
    """fish の過去CSV から年間シーズンバーを実データで生成（fish ページ用・全エリア合算）。
    max<5 のときは SEASON_DATA fallback。
    """
    counts = compute_fish_month_records(fish, hist_rows)
    max_v = max(counts) if any(counts) else 0
    if max_v < 5:
        return build_season_bar(fish, current_month)
    types = SEASON_TYPE.get(fish, [""] * 12)
    month_labels = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11", "12"]
    cells = ""
    for i in range(12):
        m = i + 1
        cnt = counts[i]
        ratio = cnt / max_v if max_v else 0
        if ratio >= 0.7:
            sc = 4
        elif ratio >= 0.4:
            sc = 3
        elif ratio >= 0.15:
            sc = 2
        elif cnt > 0:
            sc = 1
        else:
            sc = 0
        is_now = "now" if m == current_month else ""
        tp = types[i] if i < len(types) else ""
        if sc >= 4:
            cls = "peak-count" if tp == "数" else "peak-size"
        elif sc == 3:
            cls = "mid"
        else:
            cls = "low"
        cells += f'<div class="sb-cell {cls} {is_now}" title="{m}月: {cnt}件">{month_labels[i]}</div>'
    label = ""
    if fish in SEASON_TYPE:
        label = '<div class="sb-legend"><span class="leg-count">■数狙い</span><span class="leg-size">■型狙い</span></div>'
    return f'<div class="season-bar">{cells}</div>{label}'


def compute_combo_month_records(fish, area, hist_rows):
    """fish × area の過去CSV から月別件数を返す（list[12]）"""
    counts = [0] * 12
    for r in hist_rows:
        if r.get("tsuri_mono") != fish:
            continue
        if r.get("area") != area:
            continue
        d = r.get("date", "")
        try:
            mm = int(d.split("/")[1])
            if 1 <= mm <= 12:
                counts[mm - 1] += 1
        except (ValueError, IndexError):
            continue
    return counts


def build_season_bar_from_data(fish, area, hist_rows, current_month):
    """fish × area の過去CSV から年間シーズンバーを実データで生成。
    ハードコード SEASON_DATA より優先（fish_area ページ専用）。
    データが無い（max=0）または極端に少ない（max<3）ときは SEASON_DATA fallback。
    """
    counts = compute_combo_month_records(fish, area, hist_rows)
    max_v = max(counts) if any(counts) else 0
    if max_v < 3:
        return build_season_bar(fish, current_month)
    types = SEASON_TYPE.get(fish, [""] * 12)
    month_labels = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11", "12"]
    cells = ""
    for i in range(12):
        m = i + 1
        cnt = counts[i]
        ratio = cnt / max_v if max_v else 0
        if ratio >= 0.7:
            sc = 4
        elif ratio >= 0.4:
            sc = 3
        elif ratio >= 0.15:
            sc = 2
        elif cnt > 0:
            sc = 1
        else:
            sc = 0
        is_now = "now" if m == current_month else ""
        tp = types[i] if i < len(types) else ""
        if sc >= 4:
            cls = "peak-count" if tp == "数" else "peak-size"
        elif sc == 3:
            cls = "mid"
        else:
            cls = "low"
        cells += f'<div class="sb-cell {cls} {is_now}" title="{m}月: {cnt}件">{month_labels[i]}</div>'
    label = ""
    if fish in SEASON_TYPE:
        label = '<div class="sb-legend"><span class="leg-count">■数狙い</span><span class="leg-size">■型狙い</span></div>'
    return f'<div class="season-bar">{cells}</div>{label}'


def get_combo_season_score(fish, area, hist_rows, month):
    """fish × area × month の実データ正規化スコア (0-4)。
    SEASON_DATA fallback ロジックは build_season_bar_from_data と同じ。
    """
    counts = compute_combo_month_records(fish, area, hist_rows)
    max_v = max(counts) if any(counts) else 0
    if max_v < 3:
        return get_season_score(fish, month)
    cnt = counts[month - 1]
    ratio = cnt / max_v if max_v else 0
    if ratio >= 0.7:
        return 4
    if ratio >= 0.4:
        return 3
    if ratio >= 0.15:
        return 2
    if cnt > 0:
        return 1
    return 0

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

def build_comment(fish, count, score, this_w, last_w, prev_w=None, max_cnt=1, composite=50,
                  p75=None, area_top=""):
    """100パターン対応のコメント生成（2文構成）
    M2 (T22): 2文目を6パターン分岐化・平均値表記を廃止してレンジ表記に統一（補遺3）。
    引数:
      p75      : 今週釣果の P75 値（None 時はパターン6の末文付加をスキップ）
      area_top : 最多釣果エリア名（空文字時はエリア言及を省略）
    """
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
    sentence1 = pool[hash(fish) % len(pool)]
    # 句点で終わっていなければ補完
    if sentence1 and sentence1[-1] not in ("。", "！", "…", "）"):
        sentence1 += "。"

    # 先週比（wow_ratio・wow_pct）
    wow_pct = None
    wow_ratio = 1.0
    if this_w and prev_w:
        t_s = this_w.get("ships") or 0
        p_s = prev_w.get("ships") or 0
        if t_s and p_s:
            wow_pct = round((t_s - p_s) / p_s * 100)
            wow_ratio = t_s / p_s

    # max_val: max_cnt（呼び出し元から渡される全魚種最大）より this_w.max を優先
    max_v = (this_w or {}).get("max") or max_cnt or 0

    # 矛盾注記（sentence1 末尾に付与）
    if wow_pct is not None:
        if comp_tier in ("top", "high") and wow_pct <= -30:
            sentence1 = sentence1.rstrip("。") + "（直近は急減傾向・注意）。"
        elif comp_tier in ("low", "bottom") and wow_pct >= 50:
            sentence1 = sentence1.rstrip("。") + "（ただし直近は急増中）。"

    # ── 2文目: 6パターン分岐（M2 T22）─────────────────────────
    # 補遺3: avg/平均 は出さない。レンジ（lo〜hi）のみ使用。
    N = count
    area_str = f"{area_top}を中心に" if area_top else ""

    # パターン優先順位: P3 > P1 > P4 > P2 > P5（P6 は末文付加）
    if N < 5:
        # パターン5: 閑散期・データ少
        s2 = f"{fish}の釣果報告は今週{N}件と少なめです。本格的なシーズンに向けてデータを注視中です。"
    elif N >= 5 and wow_ratio >= 1.5:
        # パターン3: シーズン序盤・急増（P1 より優先）
        s2 = (
            f"{fish}の釣果報告が増え始めており、今週は{N}件を記録しました。"
            f"水温の上昇とともに本格的なシーズン到来が期待されます。"
        )
    elif N >= 30 and wow_ratio >= 1.2:
        # パターン1: シーズン最盛期・数釣り好調
        max_str = f"{max_v}匹超えの実績も出ており、" if max_v else ""
        s2 = (
            f"今週は{N}件と多くの釣果報告が集まり、活性が高い状態が続いています。"
            f"{area_str}{max_str}{fish}のシーズンが本格化しています。"
        )
    elif N >= 5 and wow_ratio < 0.7:
        # パターン4: シーズン終盤・終了間近
        s2 = (
            f"{fish}は今週{N}件の釣果報告がありましたが、先週比で減少傾向にあります。"
            f"シーズン終盤に入りつつある状況で、出かけるなら早めが得策です。"
        )
    elif N >= 10 and 0.8 <= wow_ratio < 1.2:
        # パターン2: シーズン中・平常運転（レンジ表記あり）
        s2 = (
            f"{fish}は今週{N}件の釣果報告がありました。"
            f"潮回りや時合によって差が出やすい時期です。"
        )
    else:
        # フォールバック（P2 相当・N5〜9 でwow_ratio 0.7〜1.5）
        s2 = f"今週は{N}件の釣果報告がありました。"

    # パターン6: 大型実績・型狙い（末文として付加・P1/P2 と排他でない）
    if p75 is not None and max_v and max_v >= p75 * 2 and N >= 10:
        max_str6 = f"{max_v}匹超えの好実績が含まれています。"
        s2 = s2.rstrip("。") + f"。今週は{max_str6}型狙いのチャンスです。"

    # 昨年比
    if yoy_pct is not None:
        sign = "+" if yoy_pct >= 0 else ""
        if yoy_pct >= 20:
            s2 += f"昨年同期比{sign}{yoy_pct}%と好調をキープしており、例年以上の期待が持てる。"
        elif yoy_pct <= -20:
            s2 += f"昨年同期比{yoy_pct}%とやや低調で、全体的に厳しい状況が続いている。"
        else:
            s2 += f"昨年同期比{sign}{yoy_pct}%と概ね例年並みで安定した水準を維持している。"

    # 先週比
    if wow_pct is not None and abs(wow_pct) >= 10:
        sign2 = "+" if wow_pct >= 0 else ""
        if wow_pct >= 30:
            s2 += f"先週比{sign2}{wow_pct}%と出船数が急増しており、魚影の濃さが伺える。"
        elif wow_pct >= 10:
            s2 += f"先週比{sign2}{wow_pct}%と出船数は増加傾向にある。"
        elif wow_pct <= -30:
            s2 += f"先週比{wow_pct}%と出船数が急減しており、注意が必要だ。"
        else:
            s2 += f"先週比{wow_pct}%と出船数はやや減少傾向にある。"

    # ── 3文目: comp_tier × season_tier による釣行アドバイス ──
    _advice = {
        ("top",    "peak"):   ["今が最高のタイミング。迷わず予約を入れたい。",    "ピーク×高スコアの組み合わせは年に数度。逃す手はない。"],
        ("top",    "good"):   ["好シーズン中の高水準。数・型ともに期待できる。",   "安定した好シーズン。数狙いも型狙いも成立する絶好機。"],
        ("top",    "mid"):    ["総合トップだが旬はこれから。今から狙い始めると吉。", "今週の全魚種中トップ。コンスタントな釣果が見込める。"],
        ("top",    "off"):    ["終盤戦ながら今週は高スコア。ラストチャンスかもしれない。", "端境期にもかかわらずトップスコア。貴重な機会を活かしたい。"],
        ("top",    "dead"):   ["オフシーズン中でも驚異的な好釣果。狙ってみる価値あり。", "季節外れの大チャンス。今だけの特別な状況を見逃すな。"],
        ("high",   "peak"):   ["旬のピーク期で安定した釣果。積極的に狙いたい。",    "数釣りも型釣りも成立するシーズン。今週も期待できる。"],
        ("high",   "good"):   ["好シーズン中の安定株。外しにくい一手。",           "コンスタントに釣れる時期。確実に釣果を重ねたい。"],
        ("high",   "mid"):    ["全体的に安定して釣れている。選択肢に入れやすい。",  "高スコアで安定感あり。初心者から上級者まで楽しめる。"],
        ("high",   "off"):    ["端境期だがまだ粘れる。今週中に狙っておきたい。",   "残り少ない好機。今のうちに釣っておくのが賢明。"],
        ("high",   "dead"):   ["オフ中でも意外な好釣果。狙う価値あり。",          "厳しい季節でも健闘。腕試しにはいい機会かもしれない。"],
        ("mid",    "peak"):   ["型狙いに絞ると満足度が高まりそう。丁寧な釣りが鍵。", "数より型を意識した釣りにシフトするとよい結果が得られやすい。"],
        ("mid",    "good"):   ["まずまずの状態が続く。エリアと時合を押さえれば釣果は十分期待できる。", "まずまずの水準。丁寧な釣りで十分楽しめる。"],
        ("mid",    "mid"):    ["可もなく不可もなく。腕の見せどころでもある。",      "平均的な状況。腕次第で差が出る時期だ。"],
        ("mid",    "off"):    ["端境期。今のうちに釣っておくのが賢明。",           "そろそろ終わりに近い。今週が最後のチャンスかもしれない。"],
        ("mid",    "dead"):   ["難しい季節だが可能性はゼロではない。",             "厳しい状況。数より型狙いに絞るのが現実的。"],
        ("low",    "peak"):   ["旬の割に厳しい展開。場所と時間帯を慎重に選びたい。", "苦戦気味だが、丁寧な釣りで型を絞り出せる可能性はある。"],
        ("low",    "good"):   ["好シーズンにしては厳しい。他の魚種との併用も一手。", "期待より低い水準が続く。事前に船宿に問い合わせてから出船したい。"],
        ("low",    "mid"):    ["やや厳しい状況が続く。腕と釣法の工夫が必要だ。",   "確実に釣りたいなら他の魚種の選択も視野に入れたい。"],
        ("bottom", "peak"):   ["旬にもかかわらず全魚種中で苦戦中。今週は他を優先しても。", "厳しい状況が続いている。腕に自信があるなら挑戦してみてもいい。"],
        ("bottom", "mid"):    ["今週は別の魚種を優先する方が賢明かもしれない。",   "全体的に厳しい週。状況の好転を待って出船判断したい。"],
    }
    advice_key = (comp_tier, season_tier)
    advice_pool = (
        _advice.get(advice_key) or
        _advice.get((comp_tier, "mid")) or
        ["今週の状況を参考に出船計画を立てたい。", "船宿に最新状況を確認してから出船判断を。"]
    )
    sentence3 = advice_pool[hash(fish + "adv") % len(advice_pool)]

    return sentence1 + "\n" + s2 + "\n" + sentence3

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
.pred-range{font-size:14px;color:#4db8ff;margin-bottom:2px}
.pred-range strong{font-size:16px}
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
    now = datetime.now(JST).replace(tzinfo=None)
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
    now = datetime.now(JST).replace(tzinfo=None)
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

        # 代表的なfish_areaページへのリンク（最初の港）— V2ローマ字ハイフン形式
        # fish_area が無ければ fish ページへフォールバック（404防止）
        link_area = cb["ports"][0] if cb["ports"] else ""
        link_href = _fish_area_link_or_fish(cb["fish"], link_area, depth=0) if link_area else "#"

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
    now = datetime.now(JST).replace(tzinfo=None)
    current_month = now.month
    year, week_num = current_iso_week()
    stale_cutoff = (now - timedelta(days=30)).strftime("%Y/%m/%d")

    # ZONE B（魚種カード）/ ZONE B2（エリア今日）は 7日窓ベースで集計する。
    # ZONE B のミニバーグラフ・船宿数・「N匹」表示が7日分のデータを使うため、
    # fish_summary を常時 7日マージで構築する（build_fish_pages と同じ方針・2026/05/08）。
    # 旧仕様 is_sparse_today で「当日 30件以上なら7日マージしない」は、
    # 当日 N=1〜数件の魚種がフォールバック経路を取らず ratio ブーストで上位に来る
    # regression（カンパチ問題）の原因だった。
    # HERO カウント・LIVE ティッカーは別途 catches（当日 sparse 含む）を使うため
    # is_sparse_today フラグはセクションラベル切替のみで使用する。
    today_str_local = now.strftime("%Y/%m/%d")
    today_with_fish = sum(1 for c in catches
                          if c.get("date") == today_str_local
                          and any(f != "不明" for f in (c.get("fish") or [])))
    SPARSE_THRESHOLD = 30
    is_sparse_today = today_with_fish < SPARSE_THRESHOLD
    # T19 (2026/05/09): hero_label / hero_date を冒頭で確定。
    # ZONE B ミニバー軸 / fish_others / 概況 / セクション見出し で使用するため。
    today_str = today_str_local
    hero_base, hero_label, hero_date = _resolve_display_dataset(catches, today_str)
    try:
        _recent7 = _load_recent_catches_for_index(now, days=7)
    except Exception:
        _recent7 = []
    # マージ（dedup: ship+date+fish_raw）。catches 側に詳細フィールドがあるため優先。
    seen = {(c.get("ship"), c.get("date"), c.get("fish_raw", "")) for c in catches}
    merged = list(catches)
    for c in _recent7:
        k = (c.get("ship"), c.get("date"), c.get("fish_raw", ""))
        if k not in seen:
            merged.append(c)
            seen.add(k)
    catches_for_summary = merged

    fish_summary = {}
    for c in catches_for_summary:
        for f in c["fish"]:
            if f != "不明":
                fish_summary.setdefault(f, []).append(c)
    areas = sorted(set(c["area"] for c in catches_for_summary))
    cards = ""
    # ミニバーグラフ最右列ラベル: M/D 形式でデータ日付を明示（T19: 「今日」廃止）
    # .today CSS クラスは土日色分け等の視覚効果のため維持する

    def _trend_key(fish):
        tw = get_yoy_data(history, fish, year, week_num)[0]
        pw = get_prev_week_data(history, fish, year, week_num)
        if tw and pw:
            ts = tw.get("ships") or 0
            ps = pw.get("ships") or 0
            if ts and ps:
                if ts / ps > 1.2: return 0
                if ts / ps < 0.8: return 2
        return 1

    def _heat_score(fish, cs):
        # 件数を対数変換（絶対数の支配力を圧縮）
        cnt = math.log1p(len(cs))
        # 前週比（上限3倍）
        tw = get_yoy_data(history, fish, year, week_num)[0]
        pw = get_prev_week_data(history, fish, year, week_num)
        ratio = 1.0
        if tw and pw:
            ts = tw.get("ships") or 0
            ps = pw.get("ships") or 0
            if ts and ps:
                ratio = min(ts / ps, 3.0)
        # 旬係数
        sk, _ = _fish_signal(fish, current_month)
        season_mul = {"peak": 1.3, "season": 1.1, "normal": 1.0, "late": 0.7}[sk]
        score = cnt * ratio * season_mul
        # 集計可件数（count_range あり & is_boat=False）が 5 未満の魚種は末尾に集める。
        # 旧仕様 len(cs)<5 では「N=5 だが is_boat=True で実質集計可0」のカンパチ等が
        # 前週比 ratio=3.0 ブーストで上位に来てグラフ空カードになる regression 発生。
        display_cnt = sum(
            1 for c in cs
            if c.get("count_range") and not c["count_range"].get("is_boat")
        )
        if display_cnt < 5:
            return score * 0.01
        return score

    for fish, cs in sorted(fish_summary.items(), key=lambda x: -_heat_score(x[0], x[1])):
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
        # V2 カード用データ計算（補遺3: min〜max のみ・avg は出さない）
        cnt_range_str = ""
        # this_w に min が無い（旧スキーマ）ため、min は cs から直接集計
        _cs_p = [c for c in cs if c.get("count_range") and not c["count_range"].get("is_boat")]
        _mn = None
        _mx = None
        if _cs_p:
            _mns = [c["count_range"].get("min") for c in _cs_p if c["count_range"].get("min") is not None]
            _mxs = [c["count_range"].get("max") for c in _cs_p if c["count_range"].get("max") is not None]
            if _mns: _mn = int(min(_mns))
            if _mxs: _mx = int(max(_mxs))
        # this_w.max があれば優先（history.json で集計済み・cs と同期している前提）
        if this_w and (this_w.get("max") or 0):
            _mx = int(this_w.get("max"))
        if _mn is not None and _mx is not None and _mn != _mx:
            cnt_range_str = f"{_mn}〜{_mx}匹"
        elif _mx is not None:
            cnt_range_str = f"{_mx}匹"
        else:
            cnt_range_str = f"{len(cs)}件"
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
        # T19 (2026/05/09): 軸を hero_date 基準に変更（HERO subline と最右列ラベル整合）
        try:
            _today = datetime.strptime(hero_date, "%Y/%m/%d").date() if hero_date else now.date()
        except Exception:
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
                _d = _today - timedelta(days=6 - _i)
                # T20 (2026/05/09): weekend クラス追加（土日色分け・WCAG 1.4.1 対応）
                _bar_cls_parts = []
                if _i == 6: _bar_cls_parts.append("today")
                if _d.weekday() >= 5: _bar_cls_parts.append("weekend")
                _cls = " " + " ".join(_bar_cls_parts) if _bar_cls_parts else ""
                _bar_parts.append(f'<div class="b{_cls}" style="height:{_h}%"></div>')
                # R2 (2026/05/06): 中間日も M/D ラベル。T19: 最右列も M/D 形式統一
                # T20: ラベルにも weekend クラス付与（色覚補助）
                _label_parts.append(f'<span class="bl{_cls}">{_d.month}/{_d.day}</span>')
            mini_bars = (
                f'<div class="bars">{"".join(_bar_parts)}</div>'
                f'<div class="bar-labels">{"".join(_label_parts)}</div>'
            )
        signal_key, signal_label = _fish_signal(fish, current_month)
        cards += (
            f'<a class="fc{stale_cls}" href="fish/{fish_slug(fish)}.html" data-signal="{signal_key}">'
            f'<span class="fc-signal">{signal_label}</span>'
            f'<div class="fn"><img src="assets/fish/{fish_img_slug(fish)}/{fish_img_slug(fish)}_emoji.webp" alt="{fish}" class="fc-emoji" width="32" height="32" loading="lazy" decoding="async" onerror="this.style.display=\'none\'">{fish}</div>'
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
    # V2 ZONE B2: エリア別今日の釣果カード（当日 sparse 時は7日窓を使用）
    today_str = now.strftime("%Y/%m/%d")
    if is_sparse_today:
        today_catches = catches_for_summary
    else:
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
        fish_tags = "".join(
            f'<a href="fish/{fish_slug(f)}.html" class="at-ftag">'
            f'<img src="assets/fish/{fish_img_slug(f)}/{fish_img_slug(f)}_emoji.webp" alt="" class="at-ftag-emoji" width="12" height="12" loading="lazy" decoding="async" onerror="this.style.display=\'none\'">{f}</a>'
            for f, _ in top_fish
        )
        # NOTE: <a> の中に <a> をネストすると HTML 違反 → div で囲い、上部のみ area リンク
        ea_key = _area_ea_key(area)
        area_today_html += (
            f'<div class="at-card" data-ea="{ea_key}">'
            f'<a href="area/{area_slug(area)}.html" class="at-area-link">'
            f'<div class="at-name-wrap"><span class="at-dot"></span><div class="at-name">{area}</div></div>'
            f'<div class="at-count">{cnt}件</div>'
            f'</a>'
            f'<div class="at-fish">{fish_tags}</div>'
            f'</div>'
        )
    # V2 ZONE C: 出船リスク予報（内海/外海 × 7日間）
    risk_grid_html = ""
    forecast_json_data_for_risk = weather_data.get("_forecast_data") if weather_data else None
    if forecast_json_data_for_risk:
        days_data = forecast_json_data_for_risk.get("days", {})
        if days_data:
            soto_row = _risk_grid_row("外海", _SOTOUMI_AREAS, days_data)
            uchi_row = _risk_grid_row("内海", _UCHIUMI_AREAS, days_data)
            risk_grid_html = f'<div class="risk-grid-wrap">{soto_row}{uchi_row}</div>'
    # V2 魚種ナビチップ（ZONE E）
    fish_nav_html = "".join(
        f'<a href="fish/{fish_slug(f)}.html"><img src="assets/fish/{fish_img_slug(f)}/{fish_img_slug(f)}_emoji.webp" alt="{f}" class="chip-emoji" width="16" height="16" loading="lazy" decoding="async" onerror="this.style.display=\'none\'">{f}</a>'
        for f in sorted(fish_summary.keys(), key=lambda x: -len(fish_summary[x]))[:12]
    )
    area_nav_html = "".join(
        f'<a href="area/{area_slug(a)}.html">{a}</a>'
        for a in sorted(active_areas)[:12]
    )
    # T19: hero_label / hero_date は冒頭（line 5963 付近）で既に確定済み
    # V2 概況テキスト（T19: hero_label 渡しでデータ日付を反映）
    overview_html = build_index_overview_text(catches, history, crawled_at, hero_label=hero_label)
    # V2 ティザー
    teaser_html = build_teaser_rotator_html()
    # R3 (2026/05/06): 今週末の見どころ TOP3
    top_combos_html = build_top_combos_html(catches_for_summary, history, now)
    # R9 (2026/05/06): 人気の船宿（直近1週間 件数 TOP5）。
    # build_ship_pages が ships.json で romaji_slug を持つ全船宿のページを生成するため、
    # _SHIP_ROMAJI 登録船宿のみリンク化すれば 404 にならない。
    _ship_count = {}
    for _c in catches_for_summary:
        _s = _c.get("ship", "")
        if _s and _s in _SHIP_ROMAJI:
            _ship_count[_s] = _ship_count.get(_s, 0) + 1
    _top_ships = sorted(_ship_count.items(), key=lambda x: -x[1])[:5]
    top_ships_html = ""
    if _top_ships:
        _ship_links = "".join(
            f'<a href="ship/{_SHIP_ROMAJI[_sn]}.html">{_sn} <span class="ship-cnt">{_sc}件</span></a>'
            for _sn, _sc in _top_ships
        )
        top_ships_html = (
            '<div class="nav-section">'
            '<h3>人気の船宿から探す</h3>'
            f'<div class="nav-chips ship-chips">{_ship_links}</div>'
            '</div>'
        )
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
        other_links = "".join(
            f'<a href="fish/{fish_slug(f)}.html">'
            f'<img src="assets/fish/{fish_img_slug(f)}/{fish_img_slug(f)}_emoji.webp" alt="{f}" class="fo-emoji" width="18" height="18" loading="lazy" decoding="async" onerror="this.style.display=\'none\'">'
            f'{f}</a>'
            for f in other_fish
        )
        fish_others_html = (
            f'<div class="fish-others">'
            f'<div class="fo-title">{hero_label}ほかに釣れている魚</div>'
            f'<div class="fo-list">{other_links}</div>'
            f'</div>'
        )
    # HERO 数値（hero_label / hero_base は上で確定済み・T19）
    hero_count = len(hero_base)
    hero_ships = len(set(c["ship"] for c in hero_base))
    hero_areas = len(set(c["area"] for c in hero_base))
    # LIVE ティッカーアイテム生成（当日データから上位5件）
    _ticker_candidates = []
    for c in hero_base:
        ship = c.get("ship", "")
        cr = c.get("count_range") or {}
        n = c.get("count_avg") or (cr.get("min", 0) + cr.get("max", 0)) // 2
        for f in c.get("fish", []):
            if f in ("不明", "欠航") or not ship or not n:
                continue
            _ticker_candidates.append((f, ship, int(n)))
    # 魚種×船宿でユニーク化し件数上位5件
    _seen_ticker = set()
    _ticker_items_list = []
    for f, s, n in sorted(_ticker_candidates, key=lambda x: -x[2]):
        key = (f, s)
        if key not in _seen_ticker:
            _seen_ticker.add(key)
            _ticker_items_list.append(f'<span>{hero_label} <img src="assets/fish/{fish_img_slug(f)}/{fish_img_slug(f)}_emoji.webp" alt="" class="lt-emoji" width="16" height="16" loading="lazy" decoding="async" onerror="this.style.display=\'none\'">{f} × {s} {n}匹</span>')
        if len(_ticker_items_list) >= 5:
            break
    # R10 (2026/05/06): 大物（kg級）トロフィーティッカーを末尾に追加
    _trophy_candidates = []
    _seen_trophy = set()
    for c in hero_base:
        ship = c.get("ship", "")
        kg = c.get("weight_kg") or {}
        kgmax = kg.get("max")
        if not ship or kgmax is None or kgmax < 1.0:
            continue
        for f in c.get("fish", []):
            if f in ("不明", "欠航"):
                continue
            key = (f, ship)
            if key in _seen_trophy:
                continue
            _seen_trophy.add(key)
            _trophy_candidates.append((f, ship, float(kgmax)))
    for f, s, kgmax in sorted(_trophy_candidates, key=lambda x: -x[2])[:3]:
        kg_str = f"{kgmax:.1f}kg" if kgmax < 10 else f"{int(kgmax)}kg"
        _ticker_items_list.append(
            f'<span>{hero_label} <span class="lt-trophy">大物</span> '
            f'<img src="assets/fish/{fish_img_slug(f)}/{fish_img_slug(f)}_emoji.webp" '
            f'alt="" class="lt-emoji" width="16" height="16" loading="lazy" decoding="async" '
            f'onerror="this.style.display=\'none\'">{f} {kg_str} × {s}</span>'
        )
    ticker_items = "".join(_ticker_items_list)
    # ティッカーアイテムが空でも構造は維持（空ティッカーは非表示）
    live_ticker_html = ""
    if ticker_items:
        live_ticker_html = (
            f'<div class="hero-live">'
            f'<span class="live-badge"><span class="live-pulse"></span>LIVE</span>'
            f'<div class="live-track-wrap">'
            f'<div class="live-track">{ticker_items}{ticker_items}</div>'
            f'</div>'
            f'</div>'
        )
    index_extra_css = """.hero{background:linear-gradient(135deg,var(--accent),var(--accent2));color:#fff;text-align:center;padding:24px 14px 0}
.hero-sub{font-size:12px;color:rgba(255,255,255,.6)}
.hero .n{font-size:48px;font-weight:800;color:var(--cta);line-height:1.1;font-family:'Outfit',system-ui}
.hero .n u{font-size:16px;color:rgba(255,255,255,.7);font-weight:400;text-decoration:none;margin-left:3px;font-family:system-ui}
.hero .info{font-size:12px;color:rgba(255,255,255,.6);margin-top:6px;display:flex;align-items:center;justify-content:center;gap:5px}
.hero .dot{width:6px;height:6px;background:var(--pos);border-radius:50%;animation:blink 2s ease-in-out infinite}
@keyframes blink{0%,100%{opacity:1}50%{opacity:.3}}
.hero .updated{font-size:11px;color:rgba(255,255,255,.5);margin-top:4px}
.hero-live{display:flex;align-items:center;gap:10px;margin-top:14px;padding:10px 14px;background:rgba(0,0,0,.25);overflow:hidden}
.live-badge{display:inline-flex;align-items:center;gap:5px;background:var(--teal);color:#fff;font-size:10px;font-weight:800;padding:3px 8px;border-radius:10px;white-space:nowrap;letter-spacing:.5px;flex-shrink:0}
.live-pulse{width:6px;height:6px;background:#fff;border-radius:50%;animation:live-blink 1s ease-in-out infinite}
@keyframes live-blink{0%,100%{opacity:1}50%{opacity:.2}}
.live-track-wrap{flex:1;overflow:hidden}
.live-track{display:flex;white-space:nowrap;font-size:12px;color:rgba(255,255,255,.85)}
.live-track span{display:inline-block;padding:0 32px}
.live-track .lt-emoji{vertical-align:-3px;margin:0 4px;object-fit:contain}
.live-track .lt-trophy{display:inline-block;background:var(--cta);color:#fff;font-size:9px;font-weight:800;padding:2px 6px;border-radius:6px;margin-right:4px;letter-spacing:.5px}
.live-track .lt-trophy::after{content:none}
.live-track span::after{content:"·";margin-left:16px;opacity:.4}
@media(prefers-reduced-motion:no-preference){.live-track{animation:live-scroll 40s linear infinite}}
@keyframes live-scroll{0%{transform:translateX(0)}100%{transform:translateX(-50%)}}
.fish-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:8px;margin-bottom:4px}
.fc{background:var(--card);border:1px solid var(--border);border-radius:var(--r);padding:10px;display:block;transition:border-color .2s,box-shadow .2s;position:relative;overflow:hidden;padding-bottom:14px}
.fc:hover{border-color:var(--fc-sig-color,var(--cta));box-shadow:0 0 0 2px rgba(232,93,4,.15);text-decoration:none}
.fc::after{content:"";position:absolute;bottom:0;left:0;right:0;height:4px;background:var(--fc-sig-color,var(--border));border-radius:0 0 var(--r) var(--r)}
.fc-signal{position:absolute;top:8px;right:8px;font-size:10px;font-weight:700;padding:2px 8px;border-radius:4px;background:rgba(138,150,164,.15);color:var(--fc-sig-color,var(--muted))}
.fc[data-signal="peak"]{--fc-sig-color:var(--sig-peak)}
.fc[data-signal="season"]{--fc-sig-color:var(--sig-season)}
.fc[data-signal="normal"]{--fc-sig-color:var(--sig-normal)}
.fc[data-signal="late"]{--fc-sig-color:var(--sig-late)}
.fc .fn{font-size:14px;font-weight:800;color:var(--accent)}
.fc .fr{font-size:18px;font-weight:800;color:var(--cta);margin-top:2px;font-family:'Outfit',system-ui}
.fc .fr .unit{font-size:13px;color:var(--teal);font-weight:700;font-family:system-ui}
.fc .fr small{font-size:11px;color:var(--muted);font-weight:400;font-family:system-ui}
.fc .fs{font-size:10px;color:var(--muted)}
.fc .fb{font-size:10px;color:var(--pos);font-weight:600;margin-top:3px}
.fc .bars{display:flex;align-items:flex-end;gap:1px;height:20px;margin-top:4px}
.fc .bars .b{flex:1;background:var(--cta);border-radius:1px 1px 0 0;opacity:.6;min-width:4px}
.fc .bars .b.weekend{opacity:.85;background:#f4a043}
.fc .bars .b.today{opacity:1;background:var(--pos);outline:1px solid var(--accent);outline-offset:-1px}
.fc .bar-labels{display:flex;gap:1px;margin-top:1px}
.fc .bar-labels .bl{flex:1;font-size:8px;color:var(--muted);text-align:center;min-width:4px}
.fc .bar-labels .bl.weekend{color:#c66a14}
.fc .bar-labels .bl.today{color:var(--pos);font-weight:700;border-bottom:2px solid var(--pos);padding-bottom:1px}
.fc .trend{font-size:9px;font-weight:700;margin-top:2px}
.fc .trend.up{color:var(--pos)}.fc .trend.dn{color:var(--neg)}.fc .trend.flat{color:var(--muted)}
.fc.stale{opacity:.6}
.fc-emoji{width:32px;height:32px;object-fit:contain;vertical-align:middle;margin-right:5px;flex-shrink:0}
.fo-emoji{width:18px;height:18px;object-fit:contain;vertical-align:middle;margin-right:3px}
.fish-others{margin:12px 0 20px;padding:10px 12px;background:var(--card);border:1px solid var(--border);border-radius:var(--r)}
.fo-title{font-size:11px;color:var(--muted);font-weight:600;margin-bottom:6px}
.fo-list{display:flex;flex-wrap:wrap;gap:4px}
.fo-list a{font-size:12px;padding:3px 8px;background:var(--bg);border-radius:12px;color:var(--sub);font-weight:600}
.fo-list a:hover{background:var(--accent);color:#fff;text-decoration:none}
.area-today{display:grid;grid-template-columns:repeat(2,1fr);gap:8px;margin-bottom:16px}
.at-card{background:var(--card);border:1px solid var(--border);border-radius:var(--r);padding:10px 12px;transition:border-color .15s;border-left:4px solid var(--at-ea-color,var(--border))}
.at-card:hover{border-color:var(--at-ea-color,var(--cta))}
.at-card[data-ea="kanagawa"]{--at-ea-color:var(--ea-kanagawa)}
.at-card[data-ea="tokyo"]{--at-ea-color:var(--ea-tokyo)}
.at-card[data-ea="chiba"]{--at-ea-color:var(--ea-chiba)}
.at-card[data-ea="ibaraki"]{--at-ea-color:var(--ea-ibaraki)}
.at-card[data-ea="shizuoka"]{--at-ea-color:var(--ea-shizuoka)}
.at-card[data-ea="gaiwan"]{--at-ea-color:var(--ea-gaiwan)}
.at-name-wrap{display:flex;align-items:center;gap:6px}
.at-dot{width:8px;height:8px;border-radius:50%;background:var(--at-ea-color,var(--muted));flex-shrink:0}
.at-area-link{display:block;text-decoration:none;color:inherit}
.at-area-link:hover{text-decoration:none}
.at-name{font-size:12px;font-weight:700;color:var(--accent)}
.at-count{font-size:22px;font-weight:800;color:var(--cta);line-height:1.1;margin-top:2px;font-family:'Outfit',system-ui}
.at-count::before{content:"釣果報告";display:block;font-size:9px;font-weight:400;color:var(--sub);margin-bottom:1px}
.at-fish{display:flex;flex-wrap:wrap;gap:3px;margin-top:5px}
.at-ftag{font-size:9px;padding:2px 6px;background:var(--bg);border:1px solid var(--border);border-radius:8px;color:var(--sub);text-decoration:none;display:inline-flex;align-items:center;gap:3px}
.at-ftag:hover{background:var(--accent);color:#fff;border-color:var(--accent);text-decoration:none}
.at-ftag-emoji{width:12px;height:12px;object-fit:contain;flex-shrink:0}
.risk-grid-wrap{display:flex;flex-direction:column;gap:10px;margin-bottom:14px}
.risk-row{display:flex;flex-direction:column;gap:4px}
.risk-row-head{font-size:11px;font-weight:700;color:var(--sub)}
.risk-sea-type{color:var(--text)}
.risk-sea-areas{font-weight:400;color:var(--muted)}
.risk-days{display:grid;grid-template-columns:repeat(7,1fr);gap:4px}
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
.risk-note{font-size:10px;color:var(--muted);margin:-6px 0 4px}
.nav-section{background:var(--card);border:1px solid var(--border);border-radius:var(--r);padding:14px;margin-bottom:16px}
.nav-section h3{font-size:13px;font-weight:700;color:var(--accent);margin-bottom:8px}
.nav-chips{display:flex;flex-wrap:wrap;gap:5px}
.nav-chips a{font-size:12px;padding:5px 10px;background:var(--bg);border-radius:12px;color:var(--sub);font-weight:600}
.nav-chips a:hover{background:var(--accent);color:#fff;text-decoration:none}
.chip-emoji{width:16px;height:16px;object-fit:contain;vertical-align:middle;margin-right:3px}
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
.wl-judge.good{color:var(--pos)}.wl-judge.warn{color:#f4a261}.wl-judge.bad{color:var(--neg)}
.topc-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-bottom:18px}
.topc-card{background:var(--card);border:1px solid var(--border);border-left:4px solid var(--cta);border-radius:var(--r);padding:10px 12px;display:block;text-decoration:none;transition:border-color .15s,box-shadow .15s}
.topc-card:hover{border-color:var(--cta);box-shadow:0 0 0 2px rgba(232,93,4,.15);text-decoration:none}
.topc-fish{font-size:13px;font-weight:800;color:var(--accent);margin-bottom:4px;display:flex;align-items:center;gap:4px}
.topc-emoji{width:20px;height:20px;object-fit:contain;flex-shrink:0}
.topc-stats{font-size:11px;color:var(--sub)}
.topc-wow{font-weight:700;font-size:11px}
.topc-wow.up{color:var(--pos)}.topc-wow.dn{color:var(--neg)}.topc-wow.flat{color:var(--muted)}
.topc-period{font-size:10px;font-weight:600;color:var(--muted);margin-left:6px}
@media(max-width:640px){.topc-grid{grid-template-columns:1fr}}
.ship-chips a{display:inline-flex;align-items:center;gap:4px}
.ship-chips .ship-cnt{font-size:10px;color:var(--cta);font-weight:700}"""
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
  <link rel="stylesheet" href="style.css">
  <style>{index_extra_css}</style>
</head>
<body>
{_v2_header_nav('index')}
<!-- HERO -->
<div class="hero">
  <div class="hero-sub">関東船釣り釣果情報</div>
  <div class="n">{hero_count}<u>件</u></div>
  <div class="info">
    <span class="dot"></span>
    <span>{hero_label}の釣果報告 — {hero_ships}船宿・{hero_areas}エリア</span>
  </div>
  <div class="updated">最終更新: {crawled_at} JST</div>
{live_ticker_html}
</div>
<div class="c">
<!-- TOP COMBOS: R3 今週末の見どころ -->
{top_combos_html}
<!-- ZONE B: 釣れている魚 -->
<h2 class="st">{"直近1週間 釣れている魚" if is_sparse_today else f"{hero_label} 釣れている魚"} <span class="tag free">無料</span></h2>
<div class="fish-grid">{cards}</div>
{fish_others_html}
<!-- ZONE B2: エリア別今日の釣果 -->
<h2 class="st">{"エリア別 直近1週間の釣果" if is_sparse_today else f"エリア別 {hero_label}の釣果"} <span class="tag free">無料</span></h2>
<div class="area-today">{area_today_html}</div>
{f'<h2 class="st">出船リスク予報 <span class="tag free">無料</span></h2>{risk_grid_html}' if risk_grid_html else ''}
<!-- TEASER ROTATOR -->
{teaser_html}
<!-- 広告① -->
<ins class="adsbygoogle" style="display:block;min-height:0;height:auto" data-ad-client="ca-pub-7406401300491553" data-ad-slot="auto" data-ad-format="auto" data-full-width-responsive="true"></ins>
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
{top_ships_html}
<!-- 広告② -->
<ins class="adsbygoogle" style="display:block;min-height:0;height:auto" data-ad-client="ca-pub-7406401300491553" data-ad-slot="auto" data-ad-format="auto" data-full-width-responsive="true"></ins>
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
    # 旧バージョンで生成された数字ファイル名（正規化失敗）を削除
    fish_dir = os.path.join(WEB_DIR, "fish")
    for _fn in os.listdir(fish_dir):
        if _fn.endswith(".html") and os.path.splitext(_fn)[0].isdigit():
            os.remove(os.path.join(fish_dir, _fn))
    now = datetime.now(JST).replace(tzinfo=None)
    current_month = now.month
    year, week_num = current_iso_week()
    decadal_calendar = load_decadal_calendar()
    tackle_data = load_fish_tackle()
    fixed_faq_data = _load_fixed_faq()
    # 過去CSVを一度だけロード（catches=0 魚種の準備中ページ用）
    _hist_rows_for_fish = _load_historical_catches()
    fish_summary = {}
    _SKIP_FISH = {"不明", "欠航"}

    # 個別 fish ページは「直近7日間の釣果推移」チャート + マイナー魚種（マダコ・
    # マゴチ等の当日0件魚）への配慮で、常時 7日マージを行う。
    # 旧仕様: 当日 catches >= 30件のとき merge skip → 当日0件のマイナー魚種が
    # placeholder 経路に流れる regression があった（2026/05/06 ユーザー指摘）。
    # 常時マージで全魚種に直近1週間データが揃う（再クロールなし・save_daily_csv の蓄積を流用）。
    try:
        _recent7_fp = _load_recent_catches_for_index(now, days=7)
    except Exception:
        _recent7_fp = []
    seen_fp = {(c.get("ship"), c.get("date"), c.get("fish_raw", "")) for c in data}
    merged_data = list(data)
    for c in _recent7_fp:
        k = (c.get("ship"), c.get("date"), c.get("fish_raw", ""))
        if k not in seen_fp:
            merged_data.append(c)
            seen_fp.add(k)
    data_for_fish = merged_data

    for c in data_for_fish:
        for f in c["fish"]:
            if f not in _SKIP_FISH and not f.isdigit(): fish_summary.setdefault(f, []).append(c)
    # fish_tackle.json で説明がある魚種も最低限ページを生成（404 防止）。
    # スラッグ未登録（_FISH_ROMAJI にない）はURL作れないので除外。
    for f in tackle_data.keys():
        if f in _FISH_ROMAJI and f not in fish_summary:
            fish_summary[f] = []
    for fish, catches in fish_summary.items():
        if len(catches) < 1:
            # 当日 catches=0 → 過去データを使った充実版「準備中」ページ
            # （月別釣果トレンド / TOPエリア / TOP船宿 / 大物実績 / 旬カレンダー / 釣り方 / タックル / FAQ / 有料ティザー）
            fish_hist = _summarize_fish_history(fish, _hist_rows_for_fish, now)

            # tackle 情報（fish_tackle.json）
            tackle_obj = tackle_data.get(fish, {}) if isinstance(tackle_data, dict) else {}
            method = ""
            tackle_lines = ""
            size_typical_text = ""
            notes = ""
            if isinstance(tackle_obj, dict):
                method = tackle_obj.get("method_detail") or tackle_obj.get("method_name") or ""
                tackle_dict = tackle_obj.get("tackle", {})
                if isinstance(tackle_dict, dict) and tackle_dict:
                    first_method = next(iter(tackle_dict.keys()))
                    first_tackle = tackle_dict[first_method] if isinstance(tackle_dict[first_method], dict) else {}
                    tackle_lines = f'<li><b>釣法</b>: {first_method}</li>'
                    for label, key in (("竿", "rod"), ("リール", "reel"), ("ライン", "line"),
                                        ("仕掛け", "rig"), ("エサ", "bait")):
                        v = first_tackle.get(key) if isinstance(first_tackle, dict) else None
                        if v:
                            tackle_lines += f'<li><b>{label}</b>: {v}</li>'
                size_typ_obj = tackle_obj.get("size_typical", {})
                if isinstance(size_typ_obj, dict):
                    size_typical_text = size_typ_obj.get("text", "") or ""
                elif isinstance(size_typ_obj, str):
                    size_typical_text = size_typ_obj
                notes = tackle_obj.get("notes", "") or ""

            # 月別釣果バーグラフ（過去1年）
            mb_max = max(fish_hist["month_records"].values()) if fish_hist["month_records"] else 1
            mb_html_f = ""
            for mi in range(1, 13):
                mm = f"{mi:02d}"
                cnt = fish_hist["month_records"].get(mm, 0)
                pct = int((cnt / mb_max) * 100) if mb_max else 0
                mb_html_f += (
                    f'<div class="mb-col"><div class="mb-bar" style="height:{pct}%" title="{cnt}件"></div>'
                    f'<div class="mb-label">{mi}月</div><div class="mb-num">{cnt}</div></div>'
                )

            # TOP エリア（過去1年）— area/<slug>.html へリンク
            area_cards = ""
            for aname, acnt in fish_hist["top_areas"]:
                aslug = _AREA_ROMAJI.get(aname)
                if aslug:
                    area_cards += (
                        f'<a class="fia" href="../area/{aslug}.html">'
                        f'<div class="fn">{aname}</div>'
                        f'<div class="fr">{acnt}件</div>'
                        f'<div class="fs">過去1年</div></a>'
                    )
                else:
                    area_cards += (
                        f'<div class="fia"><div class="fn">{aname}</div>'
                        f'<div class="fr">{acnt}件</div><div class="fs">過去1年</div></div>'
                    )
            area_grid_html = f'<div class="fia-grid">{area_cards}</div>' if area_cards else ""

            # TOP 船宿
            ship_items_f = ""
            for sname, scnt in fish_hist["top_ships"]:
                ship_items_f += (
                    f'<div class="sl-item"><div class="sl-top">'
                    f'<span class="sl-name">{_ship_link(sname, depth=1)}</span>'
                    f'<span class="sl-detail">過去1年 {scnt}件</span></div></div>'
                )
            ship_card_f = f'<div class="sl-card">{ship_items_f}</div>' if ship_items_f else ""

            # 大物実績
            big_rows_f = ""
            for sz, aname, dt in fish_hist["top_sizes"]:
                big_rows_f += (
                    f'<tr><td>{aname}</td>'
                    f'<td style="text-align:right;font-weight:700;color:var(--cta)">'
                    f'{int(sz) if sz == int(sz) else sz}cm</td>'
                    f'<td style="color:var(--muted);font-size:11px">{dt}</td></tr>'
                )
            big_html_f = (
                '<div class="tbl-wrap"><table>'
                '<thead><tr><th>港・エリア</th><th style="text-align:right">最大サイズ</th><th>記録日</th></tr></thead>'
                f'<tbody>{big_rows_f}</tbody></table></div>'
            ) if big_rows_f else ""

            # 旬カレンダー（数釣/型釣 × 12ヶ月 ヒートマップ・実データ駆動）
            # 2026/05/06: フォーマット統一のため小バー→旬カレンダーに変更（fish rich path と同じ）
            season_map_min = build_fish_season_map_html(fish, decadal_calendar, current_month, hist_rows=_hist_rows_for_fish)

            # FAQ
            past_year_records = fish_hist["recent_365_records"]
            # 薄コンテンツガード: 過去1年5件未満は分析セクションを非表示にして AdSense Thin Content 判定を回避
            is_thin = past_year_records < 5

            top_areas_names = [a for a, _ in fish_hist["top_areas"][:3]]
            top_areas_str = "・".join(top_areas_names) if top_areas_names else ""

            # avg_size 文字列構築（None の場合は別文を使う）
            if fish_hist["avg_size"] and fish_hist["max_size"]:
                _max = fish_hist["max_size"]
                _max_str = f"{int(_max) if _max == int(_max) else _max}cm"
                avg_size_phrase = f"過去1年の実測サイズは平均 {fish_hist['avg_size']}cm（最大 {_max_str}）。"
            else:
                avg_size_phrase = ""

            faq_q1 = f"{fish}は関東のどこで釣れますか？"
            if is_thin:
                # 薄コン時はサンプルが少なすぎて港名を断言できない（本文と矛盾を避ける）
                faq_a1 = "現在この魚種の過去1年の実績データは件数が少なく、釣れる港の集計は今後のデータ蓄積を待ちます。"
            elif top_areas_names:
                faq_a1 = f"過去1年の実績では{top_areas_str}が中心です。各エリアの詳細ページで実績をご確認いただけます。"
            else:
                faq_a1 = "現在この魚種は過去1年の実績データが少なく、釣れる港の傾向は集計中です。"
            faq_q2 = f"{fish}は今日釣れていますか？"
            faq_a2 = ("本日の釣果報告はまだ届いていません。出船情報は各船宿のWebサイト・電話で直接ご確認ください。"
                      "出船報告があり次第このページに反映されます。")
            faq_q3 = f"{fish}の釣れる時期は？"
            if is_thin:
                faq_a3 = "現在この魚種の過去1年の実績データが少なく、月別の傾向は集計中です。"
            else:
                faq_a3 = "本ページの月別釣果トレンドで過去1年の月別件数をご確認いただけます。"
            faq_q4 = f"{fish}のサイズ目安は？"
            if avg_size_phrase and size_typical_text:
                faq_a4 = avg_size_phrase + size_typical_text
            elif avg_size_phrase:
                faq_a4 = avg_size_phrase
            elif size_typical_text:
                faq_a4 = size_typical_text
            else:
                faq_a4 = "サイズの実測データを集計中です。"
            faq_q5 = f"{fish}の釣り方・タックル目安は？"
            faq_a5 = method if method else "本ページのタックル目安欄をご確認ください。"
            faq_html_f = (
                '<div class="faq-list">'
                f'<details><summary>{faq_q1}</summary><p class="faq-ans">{faq_a1}</p></details>'
                f'<details><summary>{faq_q2}</summary><p class="faq-ans">{faq_a2}</p></details>'
                f'<details><summary>{faq_q3}</summary><p class="faq-ans">{faq_a3}</p></details>'
                f'<details><summary>{faq_q4}</summary><p class="faq-ans">{faq_a4}</p></details>'
                f'<details><summary>{faq_q5}</summary><p class="faq-ans">{faq_a5}</p></details>'
                '</div>'
            )

            teaser_html_f = (
                '<h2 class="st teaser-title">この魚種の予測・分析 <span class="tag coming">まもなく公開</span></h2>'
                '<div class="teaser"><div class="teaser-head"><span class="teaser-badge">開発中</span>'
                f'<span class="teaser-title-in">{fish} 日別予測・船宿別分析</span></div>'
                f'<div class="teaser-desc"><strong>{fish}</strong>の明日〜1週間後のエリア別・船宿別予測、'
                '海況相関の詳細分析を提供します。<br>月額500円 / スポット100円（決済は準備中）。</div></div>'
            )

            import json as _json_f
            faq_jsonld_f = _json_f.dumps({
                "@context":"https://schema.org","@type":"FAQPage",
                "mainEntity":[
                    {"@type":"Question","name":faq_q1,"acceptedAnswer":{"@type":"Answer","text":faq_a1}},
                    {"@type":"Question","name":faq_q2,"acceptedAnswer":{"@type":"Answer","text":faq_a2}},
                    {"@type":"Question","name":faq_q3,"acceptedAnswer":{"@type":"Answer","text":faq_a3}},
                    {"@type":"Question","name":faq_q4,"acceptedAnswer":{"@type":"Answer","text":faq_a4}},
                    {"@type":"Question","name":faq_q5,"acceptedAnswer":{"@type":"Answer","text":faq_a5}},
                ],
            }, ensure_ascii=False)
            crumb_jsonld_f = _json_f.dumps({
                "@context":"https://schema.org","@type":"BreadcrumbList",
                "itemListElement":[
                    {"@type":"ListItem","position":1,"name":"トップ","item":SITE_URL + "/"},
                    {"@type":"ListItem","position":2,"name":"魚種一覧","item":f"{SITE_URL}/fish/"},
                    {"@type":"ListItem","position":3,"name":fish,"item":f"{SITE_URL}/fish/{fish_slug(fish)}.html"},
                ],
            }, ensure_ascii=False)

            title_f_min = f"{fish}の船釣り情報・実績・釣り方 | 船釣り予想"
            if is_thin:
                desc_f_min = (f"{fish}の船釣り情報。釣り方・タックル目安・サイズ目安をまとめました。"
                              f"過去1年の実績データは{past_year_records}件と少なく、月別トレンドや釣れる港の集計は今後のデータ蓄積を待ちます。")
            else:
                desc_f_min = (f"{fish}の船釣り情報。本日の釣果報告は集計待ちです。"
                              f"過去1年{past_year_records}件の実績データ、釣れる港、月別釣果トレンド、釣り方・タックル目安をまとめました。")

            # 統一感のため、placeholder 経路にも rich と同等の「シーズン概況」を出す
            # （イラスト + 自動生成コメント）。直近1週間 catches 0件でも見栄えを揃える。
            _peak_month = ""
            if fish_hist["month_records"]:
                _max_cnt = max(fish_hist["month_records"].values())
                _peak_months = [m for m, c in fish_hist["month_records"].items() if c == _max_cnt]
                _peak_month = "・".join(f"{int(m)}月" for m in _peak_months[:2])
            _shun_text_parts = [f"過去1年で{past_year_records:,}件の釣果報告。"]
            if _peak_month and not is_thin:
                _shun_text_parts.append(f"{_peak_month}にピークを迎えています。")
            if top_areas_str:
                _shun_text_parts.append(f"主な釣り場は{top_areas_str}。")
            if avg_size_phrase:
                _shun_text_parts.append(avg_size_phrase)
            _shun_text_parts.append("直近1週間は出船報告がまだ届いていません。集まり次第このページに反映します。")
            _shun_comment_text = "".join(_shun_text_parts)
            _kanji_suffix = f"（{FISH_KANJI[fish]}）" if fish in FISH_KANJI and FISH_KANJI[fish] != fish else ""
            shun_section_html = (
                f'<h2 class="st">シーズン概況 <span class="tag free">無料</span></h2>'
                f'<div class="comment-wrap">'
                f'<img src="../assets/fish/{fish_img_slug(fish)}/{fish_img_slug(fish)}_illustration.png" '
                f'alt="{fish}" class="comment-img" width="160" height="160" loading="lazy" '
                f'onerror="this.style.display=\'none\'">'
                f'<div class="comment"><span class="comment-fish-name">{fish}{_kanji_suffix}</span>{_shun_comment_text}</div>'
                f'</div>'
            )

            # 薄コンテンツ時は分析セクション群を非表示（AdSense Thin Content 対策）
            if is_thin:
                analysis_sections = (
                    '<div style="background:var(--card);border:1px dashed var(--border);'
                    'border-radius:var(--r);padding:18px;margin-bottom:16px;text-align:center;'
                    f'color:var(--muted);font-size:13px">過去1年の釣果記録は{past_year_records}件と少ないため、'
                    '月別トレンド・釣れる港・船宿実績・大物実績は表示しておりません。'
                    'データ蓄積後に公開します。</div>'
                )
            else:
                _month_label = "過去1年の月別釣果件数（単位: 件）"
                analysis_sections = (
                    f'<h2 class="st">月別釣果トレンド <span class="tag free">無料</span></h2>'
                    f'<div class="month-chart"><div class="mb-grid">{mb_html_f}</div>'
                    f'<p style="font-size:11px;color:var(--muted);margin-top:8px;text-align:center">{_month_label}</p></div>'
                )
                if area_grid_html:
                    analysis_sections += f'<h2 class="st">釣れる港・エリア（過去1年） <span class="tag free">無料</span></h2>{area_grid_html}'
                if ship_card_f:
                    analysis_sections += f'<h2 class="st">出船する船宿（過去1年） <span class="tag free">無料</span></h2>{ship_card_f}'

            big_section_html = (f'<h2 class="st">大物実績 TOP5 <span class="tag free">無料</span></h2>{big_html_f}'
                                if (big_html_f and not is_thin) else '')
            season_section_html = (f'<h2 class="st">旬カレンダー <span class="tag free">無料</span></h2>{season_map_min}'
                                   if (season_map_min and not is_thin) else '')

            html_f_min = f"""<!DOCTYPE html>
<html lang="ja"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title_f_min}</title>
<meta name="description" content="{desc_f_min}">
<link rel="canonical" href="{SITE_URL}/fish/{fish_slug(fish)}.html">
<meta property="og:title" content="{title_f_min}">
<meta property="og:description" content="{desc_f_min}">
<meta property="og:url" content="{SITE_URL}/fish/{fish_slug(fish)}.html">
<meta property="og:type" content="website">
<meta property="og:site_name" content="船釣り予想">
<script type="application/ld+json">{crumb_jsonld_f}</script>
<script type="application/ld+json">{faq_jsonld_f}</script>
{GA_TAG}{ADSENSE_TAG}
<link rel="stylesheet" href="../style.css">
<style>
.notice{{background:#fff8e6;border-left:3px solid var(--warn);padding:10px 14px;margin:14px 0;border-radius:0 6px 6px 0;font-size:13px;color:var(--sub);line-height:1.7}}
.month-chart{{background:var(--card);border:1px solid var(--border);border-radius:var(--r);padding:14px;margin-bottom:16px}}
.mb-grid{{display:flex;gap:4px;align-items:flex-end;height:100px;padding:0 4px}}
.mb-col{{flex:1;display:flex;flex-direction:column;align-items:center;justify-content:flex-end}}
.mb-bar{{width:80%;background:linear-gradient(180deg,var(--cta),#f47b3a);border-radius:3px 3px 0 0;min-height:3px}}
.mb-label{{font-size:10px;color:var(--muted);margin-top:6px}}
.mb-num{{font-size:11px;color:var(--accent);font-weight:700}}
.fish-hero{{background:linear-gradient(135deg,var(--accent),var(--accent2,#163d5c));color:#fff;padding:22px 14px 18px;text-align:center}}
.fish-hero h2{{font-size:26px;font-weight:800;margin:0;display:flex;align-items:center;justify-content:center;gap:8px}}
.fh-emoji{{width:40px;height:40px;object-fit:contain}}
.fish-hero .fh-r{{font-size:30px;font-weight:800;color:var(--cta);margin-top:4px;line-height:1.1}}
.fish-hero .fh-s{{font-size:18px;font-weight:700;color:#fff;margin-top:2px}}
.fish-hero .fh-m{{font-size:11px;color:rgba(255,255,255,.5);margin-top:8px}}
.comment-wrap{{display:flex;gap:16px;align-items:flex-start;background:var(--card);border:1px solid var(--border);border-radius:var(--r);padding:14px;margin-bottom:16px}}
.comment-img{{width:160px;height:160px;object-fit:contain;flex-shrink:0;border-radius:8px;background:#f5f7fa}}
.comment{{font-size:13px;color:var(--text);white-space:pre-line;min-width:0}}
.comment-fish-name{{display:block;font-size:15px;font-weight:800;color:var(--accent);margin-bottom:6px}}
.fia-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(140px,1fr));gap:8px;margin-bottom:16px}}
.fia{{background:var(--card);border:1px solid var(--border);border-radius:var(--r);padding:10px;display:block;text-decoration:none;color:inherit}}
.fia:hover{{border-color:var(--cta);text-decoration:none}}
.fia .fn{{font-size:14px;font-weight:800;color:var(--accent)}}
.fia .fr{{font-size:17px;font-weight:800;color:var(--cta);margin-top:2px;line-height:1.2}}
.fia .fs{{font-size:10px;color:var(--muted);margin-top:2px}}
.sl-card{{background:var(--card);border:1px solid var(--border);border-radius:var(--r);padding:14px;margin-bottom:16px}}
.sl-item{{padding:10px 0;border-bottom:1px solid var(--bg)}}
.sl-item:last-child{{border-bottom:none}}
.sl-top{{display:flex;justify-content:space-between;align-items:baseline;gap:8px;flex-wrap:wrap}}
.sl-name{{font-size:14px;font-weight:800;color:var(--accent)}}
.sl-detail{{font-size:11px;color:var(--muted)}}
.tbl-wrap table{{width:100%;border-collapse:collapse;font-size:13px;background:var(--card);border:1px solid var(--border);border-radius:var(--r);overflow:hidden;margin-bottom:16px}}
.tbl-wrap th{{background:var(--accent);color:#fff;padding:8px;text-align:left;font-size:12px}}
.tbl-wrap td{{padding:8px;border-bottom:1px solid var(--border)}}
.season-bar{{display:flex;gap:2px;margin-top:8px;justify-content:center;flex-wrap:wrap;margin-bottom:16px}}
.sb-cell{{min-width:20px;height:18px;border-radius:3px;font-size:10px;color:#fff;display:flex;align-items:center;justify-content:center;padding:0 2px}}
.sb-cell.peak-count{{background:#e85d04}}
.sb-cell.peak-size{{background:#7209b7}}
.sb-cell.mid{{background:#1a6ea8}}
.sb-cell.low{{background:#1a3050}}
.sb-cell.now{{outline:2px solid #fff;outline-offset:1px}}
</style>
</head>
<body>
{_v2_header_nav('fish')}
<!-- 統一HERO: マダイ等の rich 形式と同構造 -->
<div class="fish-hero">
  <h2><img src="../assets/fish/{fish_img_slug(fish)}/{fish_img_slug(fish)}_emoji.webp" alt="{fish}" class="fh-emoji" width="40" height="40" loading="lazy" decoding="async" onerror="this.style.display='none'">{fish}</h2>
  <div class="fh-r">過去1年 {past_year_records:,}件</div>
  <div class="fh-m">本日の釣果報告は集計待ち</div>
</div>
<div class="c">
  <p class="bread"><a href="../index.html">トップ</a> &rsaquo; <a href="index.html">魚種一覧</a> &rsaquo; {fish}</p>
  <div class="notice">
    <strong>本日の{fish}の釣果報告はまだ届いていません。</strong>
    出船情報は各船宿のWebサイト・電話で直接ご確認ください。
    {('現在この魚種は過去1年の実績データが少なく、釣り方・タックル目安のみ表示しています。' if is_thin else '本ページでは過去1年の実績データから、釣れる港・月別トレンド・釣り方をご確認いただけます。')}
  </div>
  {shun_section_html}
  {analysis_sections}
  <!-- 広告① -->
  <ins class="adsbygoogle" style="display:block;min-height:0;height:auto" data-ad-client="ca-pub-7406401300491553" data-ad-slot="auto" data-ad-format="auto" data-full-width-responsive="true"></ins>
  <script>(adsbygoogle=window.adsbygoogle||[]).push({{}});</script>
  {big_section_html}
  {season_section_html}
  {('<h2 class="st">釣り方</h2><p style="font-size:13px;color:var(--sub);line-height:1.8;margin-bottom:14px">' + method + '</p>') if method else ''}
  {('<h2 class="st">タックル目安</h2><ul style="font-size:13px;color:var(--sub);line-height:1.9;padding-left:18px;margin-bottom:14px">' + tackle_lines + '</ul>') if tackle_lines else ''}
  {('<h2 class="st">サイズ目安</h2><p style="font-size:13px;color:var(--sub);line-height:1.7;margin-bottom:14px">' + size_typical_text + '</p>') if size_typical_text else ''}
  {('<p style="font-size:12px;color:var(--muted);line-height:1.7;margin:12px 0 18px">' + notes + '</p>') if notes else ''}
  <!-- 広告② -->
  <ins class="adsbygoogle" style="display:block;min-height:0;height:auto" data-ad-client="ca-pub-7406401300491553" data-ad-slot="auto" data-ad-format="auto" data-full-width-responsive="true"></ins>
  <script>(adsbygoogle=window.adsbygoogle||[]).push({{}});</script>
  <h2 class="st">よくある質問</h2>
  {faq_html_f}
  {teaser_html_f}
</div>
{DATA_NOTE_HTML}
{_v2_footer(crawled_at)}
{_v2_bottom_nav('fish')}
</body></html>"""
            with open(os.path.join(WEB_DIR, f"fish/{fish_slug(fish)}.html"), "w", encoding="utf-8") as f:
                f.write(html_f_min)
            continue
        # rich path は build_fish_season_map_html (heatmap) のみを使う
        # （以前は build_season_bar_from_fish_data も呼んでいたが HTML には埋め込まれていなかった dead code）
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
        today_catches_f, fish_today_label, fish_display_date_str = _resolve_display_dataset(catches, today_str_f)
        max_cnt = 0
        for c in catches:
            cr = c.get("count_range")
            if cr and not cr.get("is_boat"): max_cnt = max(max_cnt, cr["max"])
        # fish-hero 数値: **トップページ ZONE B カードと完全一致させる**ため、
        # 同じ catches （魚種フィルタ済み）を使って min/max を直接集計する。
        # 補遺3 (2026/05/08): avg/平均 は出さず min〜max のみ表示。
        # this_w に min が無いため、min は catches から計算。max は this_w 優先。
        cnt_range_str = ""
        w_p = [c for c in catches if c.get("count_range") and not c["count_range"].get("is_boat")]
        w_mins = [c["count_range"].get("min") for c in w_p if c["count_range"].get("min") is not None]
        w_maxs = [c["count_range"].get("max") for c in w_p if c["count_range"].get("max") is not None]
        _mn = int(min(w_mins)) if w_mins else None
        _mx = int(max(w_maxs)) if w_maxs else None
        if this_w and (this_w.get("max") or 0):
            _mx = int(this_w.get("max"))
        if _mn is not None and _mx is not None and _mn != _mx:
            cnt_range_str = f"{_mn}〜{_mx}匹"
        elif _mx is not None:
            cnt_range_str = f"{_mx}匹"
        else:
            cnt_range_str = f"釣果{len(catches)}件"
        # サイズ: this_w.size_avg があれば「平均{X}cm」、無ければ catches から min〜max
        sz_str = ""
        if this_w and this_w.get("size_avg"):
            sz_str = f"{this_w['size_avg']:.0f}cm"
        else:
            w_sz_lo = [c["size_cm"]["min"] for c in catches if c.get("size_cm") and c["size_cm"].get("min") is not None]
            w_sz_hi = [c["size_cm"]["max"] for c in catches if c.get("size_cm") and c["size_cm"].get("max") is not None]
            if w_sz_lo and w_sz_hi:
                sz_str = f"{int(min(w_sz_lo))}〜{int(max(w_sz_hi))}cm"
        # area-cmp（今日のエリア別）
        area_today_f: dict = {}
        for c in today_catches_f:
            d = area_today_f.setdefault(c["area"], {"hi": [], "lo": []})
            cr = c.get("count_range")
            if cr and not cr.get("is_boat"):
                if cr.get("max") is not None: d["hi"].append(cr["max"])
                if cr.get("min") is not None: d["lo"].append(cr["min"])
        area_cmp_rows = ""
        for aname, ad in sorted(area_today_f.items(), key=lambda x: -(max(x[1]["hi"] or [0])))[:5]:
            a_lo = int(min(ad["lo"])) if ad["lo"] else None
            a_hi = int(max(ad["hi"])) if ad["hi"] else None
            if a_lo is not None and a_hi is not None and a_lo != a_hi:
                a_range = f"{a_lo}〜{a_hi}匹"
            elif a_hi is not None:
                a_range = f"{a_hi}匹"
            else:
                a_range = "—"
            area_cmp_rows += (
                f'<a class="ar" href="../area/{area_slug(aname)}.html">'
                f'<span class="ar-name">{aname}</span>'
                f'<span class="ar-range">{a_range}</span>'
                f'</a>'
            )
        area_cmp_html = f'<div class="area-cmp"><h3>エリア別の{fish_today_label}の釣果</h3>{area_cmp_rows}</div>' if area_cmp_rows else ""
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
        sr_items = ""
        from collections import Counter as _CtrF
        for i, (sn, sd) in enumerate(sorted(ship_data_f.items(), key=lambda x: -max(x[1]["cnt_his"] or [0]))[:8]):
            s_lo = int(min(sd["cnt_los"])) if sd["cnt_los"] else None
            s_hi = int(max(sd["cnt_his"])) if sd["cnt_his"] else None
            if s_lo is not None and s_hi is not None and s_lo != s_hi:
                s_range = f"{s_lo}〜{s_hi}匹"
            elif s_hi is not None:
                s_range = f"{s_hi}匹"
            else:
                s_range = f"{sd['cnt']}件"
            top_pt = _CtrF(sd["pts"]).most_common(1)[0][0] if sd["pts"] else ""
            sr_items += (
                f'<div class="sr">'
                f'<span class="sr-rank">{i+1}</span>'
                f'<span class="sr-name">{_ship_link(sn, depth=1)}</span>'
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
            f'<div class="cs-title">準備中</div>'
            f'<ul class="cs-features"><li>気象条件スコア</li>'
            f'<li>来週の釣れる日予測</li>'
            f'<li>船宿別おすすめ日</li></ul>'
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
            '<a href="../fish/' + fish_slug(rf) + '.html" class="chip-link">'
            + f'<img src="../assets/fish/{fish_img_slug(rf)}/{fish_img_slug(rf)}_emoji.webp" alt="" class="chip-emoji" width="14" height="14" loading="lazy" decoding="async" onerror="this.style.display=\'none\'">'
            + rf + '</a>'
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
        season_map_html = build_fish_season_map_html(fish, decadal_calendar, current_month, hist_rows=_hist_rows_for_fish)
        guide_html = build_fish_guide_html(fish, tackle_data)
        auto_faq_html, auto_faq_pairs = build_fish_faq_html(fish, catches, decadal_calendar, SITE_URL)
        # M1 (T22): 共通 FAQ 9 問を faq.html に切り出し。固有 FAQ + リンクのみ出力
        fixed_faq_html, fixed_faq_pairs = build_fish_fixed_faq_html(fish, fixed_faq_data)
        faq_html = auto_faq_html + fixed_faq_html
        # JSON-LD は auto + 固有のみ（共通 FAQ の重複 JSON-LD を除去）
        all_faq_pairs = auto_faq_pairs + fixed_faq_pairs
        _faq_jsonld_items = ",\n".join(
            f'{{"@type":"Question","name":{json.dumps(q, ensure_ascii=False)},"acceptedAnswer":{{"@type":"Answer","text":{json.dumps(a, ensure_ascii=False)}}}}}'
            for q, a in all_faq_pairs
        )
        faq_jsonld = f'<script type="application/ld+json">{{"@context":"https://schema.org","@type":"FAQPage","mainEntity":[{_faq_jsonld_items}]}}</script>'
        _chart7_base = datetime.strptime(fish_display_date_str, "%Y/%m/%d").date()
        chart7_html = build_fish_7day_chart_html(fish, catches, display_date=_chart7_base, display_label=fish_today_label)
        fish_extra_css = """\
.fish-hero{background:linear-gradient(135deg,var(--accent),var(--accent2));color:#fff;padding:22px 14px 18px;text-align:center}
.fish-hero h2{font-size:26px;font-weight:800;margin:0;display:flex;align-items:center;justify-content:center;gap:8px}
.fh-emoji{width:40px;height:40px;object-fit:contain}
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
.sr .sr-rank{font-size:11px;font-weight:700;color:var(--muted);flex:0 0 18px;text-align:center}
.sr .sr-name{flex:0 0 80px;font-size:13px;font-weight:700;color:var(--accent)}
.sr .sr-range{flex:0 0 80px;font-size:13px;font-weight:700;color:var(--cta)}
.sr .sr-pt{flex:1;font-size:10px;color:var(--muted);text-align:right}
.comment{font-size:13px;color:var(--text);white-space:pre-line;min-width:0}
.comment-fish-name{display:block;font-size:15px;font-weight:800;color:var(--accent);margin-bottom:6px}
.comment-wrap{display:flex;gap:16px;align-items:flex-start;background:var(--card);border:1px solid var(--border);border-radius:var(--r);padding:14px;margin-bottom:16px}
.comment-img{width:160px;height:160px;object-fit:contain;flex-shrink:0;border-radius:8px;background:#f5f7fa}
.season-entry{font-size:12px;color:var(--sub);margin:8px 0;padding:6px 10px;border-radius:4px;background:var(--card);border:1px solid var(--border)}
.season-entry.entry-early{border-left:3px solid var(--pos)}.season-entry.entry-late{border-left:3px solid var(--warn)}.season-entry.entry-same{border-left:3px solid var(--accent)}
.entry-trend{font-weight:bold;margin-left:6px}
.chip-wrap{display:flex;flex-wrap:wrap;gap:6px;margin:10px 0}
.chip-link{background:var(--card);border:1px solid var(--border);border-radius:16px;padding:5px 12px;font-size:12px;color:var(--accent);text-decoration:none;font-weight:600;display:inline-flex;align-items:center;gap:4px}
.chip-link:hover{background:var(--accent);color:#fff;text-decoration:none}
.chip-link .chip-emoji{width:14px;height:14px;object-fit:contain;flex-shrink:0}
.chart7{background:var(--card);border:1px solid var(--border);border-radius:var(--r);padding:14px;margin-bottom:16px}
.chart7 h3{font-size:13px;font-weight:700;color:var(--accent);margin-bottom:8px}
.chart-bars{display:flex;align-items:flex-end;gap:3px;height:60px}
.chart-bars .cb{flex:1;background:var(--cta);border-radius:2px 2px 0 0;opacity:.7;min-width:10px}
.chart-bars .cb.weekend{opacity:.8;background:#f4a043}
.chart-bars .cb.today{opacity:1;background:var(--pos);outline:1.5px solid var(--accent);outline-offset:-1.5px}
.chart-labels{display:flex;justify-content:space-between;font-size:9px;color:var(--muted);margin-top:3px}
.chart-labels span.weekend{color:#c66a14}
.chart-labels span.today{color:var(--pos);font-weight:700;border-bottom:2px solid var(--pos);padding-bottom:1px}
.chart-trend{text-align:center;margin-top:6px;font-size:12px;font-weight:700;color:var(--pos)}
.chart-trend.down{color:var(--warn)}.chart-trend.flat{color:var(--sub)}
.faq-common-link{font-size:14px;color:var(--accent);margin:16px 0;padding:12px 16px;background:var(--card);border:2px solid var(--accent);border-radius:var(--r);line-height:1.6}
.faq-common-link a{color:var(--cta);text-decoration:underline}"""
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
  <script type="application/ld+json">{{"@context":"https://schema.org","@type":"BreadcrumbList","itemListElement":[{{"@type":"ListItem","position":1,"name":"トップ","item":"{SITE_URL}/"}},{{"@type":"ListItem","position":2,"name":"魚種一覧","item":"{SITE_URL}/fish/"}},{{"@type":"ListItem","position":3,"name":"{fish}の釣果情報","item":"{fish_url}"}}]}}</script>
  {faq_jsonld}
  {GA_TAG}
  {ADSENSE_TAG}
  <link rel="stylesheet" href="../style.css">
  <style>{fish_extra_css}</style>
</head>
<body>
{_v2_header_nav('fish')}
<div class="fish-hero">
  <h2><img src="../assets/fish/{fish_img_slug(fish)}/{fish_img_slug(fish)}_emoji.webp" alt="{fish}" class="fh-emoji" width="40" height="40" loading="lazy" decoding="async" onerror="this.style.display='none'">{fish}</h2>
  {f'<div class="fh-r">{cnt_range_str}</div>' if cnt_range_str else ''}
  {f'<div class="fh-s">{sz_str}</div>' if sz_str else ''}
  <div class="fh-m">今週 {len(catches)}件・{len(set(c['ship'] for c in catches))}船宿</div>
</div>
<div class="c">
  <p class="bread"><a href="../index.html">トップ</a> &rsaquo; {fish}</p>
  {season_entry_html}
  <h2 class="st">今週の概況 <span class="tag free">無料</span></h2>
  <div class="comment-wrap">
    <img src="../assets/fish/{fish_img_slug(fish)}/{fish_img_slug(fish)}_illustration.png" alt="{fish}" class="comment-img" width="160" height="160" loading="lazy" onerror="this.style.display='none'">
    <div class="comment"><span class="comment-fish-name">{fish}{"（" + FISH_KANJI[fish] + "）" if fish in FISH_KANJI and FISH_KANJI[fish] != fish else ""}</span>{comment}</div>
  </div>
  {chart7_html}
  <h2 class="st">{fish_today_label}の釣果 <span class="tag free">無料</span></h2>
  {area_cmp_html if area_cmp_html else '<p style="color:var(--muted);font-size:13px;padding:8px 0">本日の釣果はまだ集計中です</p>'}
  {ship_rank_html}
  <!-- 広告① -->
  <ins class="adsbygoogle" style="display:block;min-height:0;height:auto" data-ad-client="ca-pub-7406401300491553" data-ad-slot="auto" data-ad-format="auto" data-full-width-responsive="true"></ins>
  <script>(adsbygoogle=window.adsbygoogle||[]).push({{}});</script>
  {related_section_html}
  {fish_area_section_html}
  <h2 class="st">旬カレンダー <span class="tag free">無料</span></h2>
  {season_map_html}
  {('<h2 class="st">魚種ガイド <span class="tag free">無料</span></h2>' + guide_html) if guide_html else ''}
  <p class="faq-common-link">船釣り全般の Q&amp;A（服装・船酔い・予約・ライフジャケット等）は<a href="/pages/faq.html"><strong>よくある質問ページ</strong></a>にまとめています。</p>
  <!-- 広告② -->
  <ins class="adsbygoogle" style="display:block;min-height:0;height:auto" data-ad-client="ca-pub-7406401300491553" data-ad-slot="auto" data-ad-format="auto" data-full-width-responsive="true"></ins>
  <script>(adsbygoogle=window.adsbygoogle||[]).push({{}});</script>
  <h2 class="st">よくある質問</h2>
  {faq_html}
  {fish_teaser_html}
</div>
{DATA_NOTE_HTML}
{_v2_footer(crawled_at)}
{_v2_bottom_nav('fish')}
</body></html>"""
        with open(os.path.join(WEB_DIR, f"fish/{fish_slug(fish)}.html"), "w", encoding="utf-8") as f:
            f.write(html)

    # fish/index.html: 魚種一覧（今週 = 過去7日間ローリング、CSV由来）
    # 再クロール禁止: data/V2/*.csv の蓄積データを読み込む
    _recent7 = _load_recent_catches_for_index(now, days=7)
    fish_week_summary = {f: [] for f in fish_summary.keys()}
    for c in _recent7:
        for f in c["fish"]:
            if f in _SKIP_FISH or f.isdigit():
                continue
            fish_week_summary.setdefault(f, []).append(c)
    fish_index_cards = ""
    for fish, cs in sorted(fish_week_summary.items(), key=lambda x: (-len(x[1]), x[0])):
        cnt = len(cs)
        fish_index_cards += (
            f'<a class="fi-card" href="{fish_slug(fish)}.html">'
            f'<div class="fi-name"><img src="../assets/fish/{fish_img_slug(fish)}/{fish_img_slug(fish)}_emoji.webp" alt="{fish}" class="fi-emoji" width="28" height="28" loading="lazy" decoding="async" onerror="this.style.display=\'none\'">{fish}</div>'
            f'<div class="fi-cnt">今週釣果{cnt}件</div>'
            f'</a>'
        )
    _week_active = sum(1 for cs in fish_week_summary.values() if cs)
    fish_index_css = """.fi-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(130px,1fr));gap:8px;margin:16px 0}
.fi-card{background:var(--card);border:1px solid var(--border);border-radius:var(--r);padding:12px;display:block;text-decoration:none;color:inherit;transition:border-color .15s}
.fi-card:hover{border-color:var(--cta);text-decoration:none}
.fi-name{font-size:14px;font-weight:700;color:var(--accent);display:flex;align-items:center;gap:6px}
.fi-emoji{width:28px;height:28px;object-fit:contain;flex-shrink:0}
.fi-cnt{font-size:11px;color:var(--muted);margin-top:4px}"""
    fish_index_html = f"""<!DOCTYPE html>
<html lang="ja"><head>
  <meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
  <title>魚種別釣果一覧 | 船釣り予想</title>
  <meta name="description" content="関東の船釣り魚種別釣果一覧。アジ・マダイ・ヒラメ・タチウオなど今週釣れている魚種をまとめて確認できます。">
  <link rel="canonical" href="{SITE_URL}/fish/">
  {GA_TAG}{ADSENSE_TAG}
  <link rel="stylesheet" href="../style.css">
  <style>{fish_index_css}</style>
</head>
<body>
{_v2_header_nav('fish')}
<div style="background:var(--accent);color:#fff;padding:18px 14px 20px;margin-bottom:0">
  <div class="c"><div style="font-size:26px;font-weight:800">魚種別 釣果一覧</div>
  <div style="font-size:12px;opacity:.7;margin-top:4px">今週釣果あり {_week_active}種</div></div>
</div>
<div class="c">
  <p class="bread"><a href="../index.html">トップ</a> &rsaquo; 魚種一覧</p>
  <h2 class="st">今週釣れている魚種（過去7日間）</h2>
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
    now = datetime.now(JST).replace(tzinfo=None)
    today_str = now.strftime("%Y/%m/%d")
    today_iso = now.strftime("%Y-%m-%d")
    area_desc_data = load_area_description()
    area_decadal = load_area_decadal()
    fixed_faq_data_area = _load_fixed_faq()
    # 過去CSVを一度だけロード（catches=0 エリアの準備中ページに使う）
    _hist_rows_for_placeholder = _load_historical_catches()
    # area_coords.json（Place JSON-LD の geo に使用）
    _area_coords_for_placeholder = _ship_load_area_coords()
    area_summary = {}
    for c in data:
        area_summary.setdefault(c["area"], []).append(c)
    # ship_info / 有効船宿 / area_description で言及されるエリアも、
    # 当日 catches=0 でも最低限ページを作る（404 防止）。
    # スラッグ未登録（_AREA_ROMAJI にない）エリアは生成不能なので除外。
    for ship_name, info in _SHIP_INFO.items():
        a = info.get("area")
        if a and a in _AREA_ROMAJI and a not in area_summary:
            area_summary[a] = []
    for s in SHIPS:
        if s.get("exclude") or s.get("boat_only"):
            continue
        a = s.get("area")
        if a and a in _AREA_ROMAJI and a not in area_summary:
            area_summary[a] = []
    for a in area_desc_data.keys():
        if a in _AREA_ROMAJI and a not in area_summary:
            area_summary[a] = []
    # 過去CSVに言及されているエリア（=旧V1時代から実績データがある）も対象に。
    # 近隣エリアリンク（同じ AREA_GROUPS 内）の404を防ぐため。
    for r in _hist_rows_for_placeholder:
        a = r.get("area")
        if a and a in _AREA_ROMAJI and a not in area_summary:
            area_summary[a] = []

    area_extra_css = """\
.area-hero{background:linear-gradient(135deg,var(--accent),var(--accent2));color:#fff;padding:22px 14px 18px;text-align:center}
.area-hero h2{font-size:26px;font-weight:800;margin:0}
.area-hero .ah-sub{font-size:12px;color:rgba(255,255,255,.6);margin-top:2px}
.area-hero .ah-m{font-size:20px;font-weight:800;color:var(--cta);margin-top:8px}
.area-hero .ah-m small{font-size:12px;color:rgba(255,255,255,.6);font-weight:400}
.area-hero .ah-sea{font-size:11px;color:rgba(255,255,255,.5);margin-top:6px}
.fia-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(140px,1fr));gap:8px;margin-bottom:16px}
.fia{background:var(--card);border:1px solid var(--border);border-radius:var(--r);padding:10px;display:block;text-decoration:none;color:inherit}
.fia:hover{border-color:var(--cta);text-decoration:none}
.fia .fn{font-size:14px;font-weight:800;color:var(--accent);display:flex;align-items:center;gap:5px}
.fia .fn-emoji{width:18px;height:18px;object-fit:contain;flex-shrink:0}
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
.sl-fish span{font-size:10px;padding:2px 6px;border-radius:8px;font-weight:700;display:inline-flex;align-items:center;gap:3px}
.sl-fish .g{background:#e6f7ee;color:var(--pos)}
.sl-fish .o{background:#fef6ee;color:var(--cta)}
.sl-fish .sl-emoji{width:14px;height:14px;object-fit:contain;flex-shrink:0}
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
.related .rl a:hover{background:var(--accent);color:#fff;text-decoration:none}
.area-desc{background:var(--card);border:1px solid var(--border);border-radius:var(--r);padding:16px;margin-bottom:16px}
.area-desc p{font-size:14px;line-height:1.8;color:var(--sub);margin:0 0 10px}
.area-desc p:last-child{margin-bottom:0}"""

    for area, catches in area_summary.items():
        group = next((g for g, areas in AREA_GROUPS.items() if area in areas), "関東")

        if len(catches) < 2:
            # 当日 catches < 2 → 過去データを使った充実版「準備中」ページ
            # （旬カレンダー / TOP魚種 / TOPポイント / 船宿一覧 / 大物実績 / FAQ / 有料ティザー）
            hist = _summarize_area_history(area, _hist_rows_for_placeholder, now)

            past_total = hist["recent_365_records"]
            past_30_days = hist["recent_30_days"]
            past_30_ships = hist["recent_30_ships"]

            mb_max = max(hist["month_days"].values()) if hist["month_days"] else 1
            mb_html = ""
            for mi in range(1, 13):
                mm = f"{mi:02d}"
                cnt = hist["month_days"].get(mm, 0)
                pct = int((cnt / mb_max) * 100) if mb_max else 0
                mb_html += (
                    f'<div class="mb-col"><div class="mb-bar" style="height:{pct}%" title="{cnt}日"></div>'
                    f'<div class="mb-label">{mi}月</div><div class="mb-num">{cnt}</div></div>'
                )

            fish_cards_min = ""
            for fname, fcnt in hist["top_fish"][:8]:
                fslug = _FISH_ROMAJI.get(fname)
                _fname_with_icon = (
                    f'<img src="../assets/fish/{fish_img_slug(fname)}/{fish_img_slug(fname)}_emoji.webp" '
                    f'alt="" class="fn-emoji" width="18" height="18" loading="lazy" decoding="async" '
                    f'onerror="this.style.display=\'none\'">{fname}'
                )
                if fslug:
                    fish_cards_min += (
                        f'<a class="fia" href="{_fish_area_link_or_fish(fname, area, depth=1)}">'
                        f'<div class="fn">{_fname_with_icon}</div>'
                        f'<div class="fr">{fcnt}件</div>'
                        f'<div class="fs">過去1年</div></a>'
                    )
                else:
                    fish_cards_min += (
                        f'<div class="fia"><div class="fn">{_fname_with_icon}</div>'
                        f'<div class="fr">{fcnt}件</div><div class="fs">過去1年</div></div>'
                    )
            fish_grid_html = f'<div class="fia-grid">{fish_cards_min}</div>' if fish_cards_min else ""

            ship_items_min = ""
            for sname, scnt in hist["top_ships"][:10]:
                ship_items_min += (
                    f'<div class="sl-item"><div class="sl-top">'
                    f'<span class="sl-name">{_ship_link(sname, depth=1)}</span>'
                    f'<span class="sl-detail">過去1年 {scnt}件</span></div></div>'
                )
            ship_card_html = f'<div class="sl-card">{ship_items_min}</div>' if ship_items_min else ""

            big_rows_html = ""
            for sz, fname, dt in hist["top_sizes"]:
                _fn_icon = (
                    f'<img src="../assets/fish/{fish_img_slug(fname)}/{fish_img_slug(fname)}_emoji.webp" '
                    f'alt="" class="big-emoji" width="16" height="16" loading="lazy" decoding="async" '
                    f'onerror="this.style.display=\'none\'">{fname}'
                )
                big_rows_html += (
                    f'<tr><td>{_fn_icon}</td>'
                    f'<td style="text-align:right;font-weight:700;color:var(--cta)">'
                    f'{int(sz) if sz == int(sz) else sz}cm</td>'
                    f'<td style="color:var(--muted);font-size:11px">{dt}</td></tr>'
                )
            big_html = (
                '<div class="tbl-wrap"><table>'
                '<thead><tr><th>魚種</th><th style="text-align:right">最大サイズ</th><th>記録日</th></tr></thead>'
                f'<tbody>{big_rows_html}</tbody></table></div>'
            ) if big_rows_html else ""

            # 旬カレンダーは件数 5 件以上の魚種のみ採用（過少データの色塗りで誤誘導を防止）
            top_fish_for_season = [f for f, c in hist["top_fish"][:6] if c >= 5]
            season_map = build_area_season_map_html(area, area_decadal, top_fish_for_season, hist_rows=_hist_rows_for_placeholder) if top_fish_for_season else ""

            related_links = []
            for other in AREA_GROUPS.get(group, []):
                if other == area:
                    continue
                oslug = _AREA_ROMAJI.get(other)
                if oslug and other in area_summary:  # 同一バッチで生成予定のエリアのみ
                    related_links.append(f'<a href="../area/{oslug}.html">{other}</a>')
            related_html = (
                '<div class="related"><h3>近隣エリア</h3>'
                f'<div class="rl">{"".join(related_links)}</div></div>'
            ) if related_links else ""

            _desc_obj = area_desc_data.get(area, {}) if isinstance(area_desc_data, dict) else {}
            _ovw = _desc_obj.get("overview", "") if isinstance(_desc_obj, dict) else ""
            _access = _desc_obj.get("access", "") if isinstance(_desc_obj, dict) else ""
            _features = _desc_obj.get("features", "") if isinstance(_desc_obj, dict) else ""
            guide_parts = []
            if _ovw:
                guide_parts.append(f'<div class="overview"><div class="overview-title">エリア概要</div><div class="overview-body">{_ovw}</div></div>')
            if _access:
                guide_parts.append(f'<div class="overview"><div class="overview-title">アクセス</div><div class="overview-body">{_access}</div></div>')
            if _features:
                guide_parts.append(f'<div class="overview"><div class="overview-title">特徴</div><div class="overview-body">{_features}</div></div>')
            guide_html = "\n".join(guide_parts)

            top_fish_names = [f for f, _ in hist["top_fish"][:3]]
            top_fish_str = "・".join(top_fish_names) if top_fish_names else "（過去1年の集計データなし）"
            top_ship_names = [s for s, _ in hist["top_ships"][:3]]
            top_ship_str = "・".join(top_ship_names) if top_ship_names else "（出船実績データを準備中）"
            faq_q1 = f"{area}で釣れる魚は何ですか？"
            faq_a1 = (f"過去1年の実績では{top_fish_str}が中心です。本ページの月別トレンドや旬カレンダーで詳細をご確認いただけます。"
                      if top_fish_names else "現在このエリアの過去データを収集中です。")
            faq_q2 = f"{area}でよく出船する船宿は？"
            faq_a2 = (f"過去1年の実績では{top_ship_str}などが出船しています。"
                      if top_ship_names else "現在このエリアの出船データを収集中です。")
            faq_q3 = f"{area}で今日は出船していますか？"
            faq_a3 = ("本日の釣果報告はまだ届いていません。出船情報は各船宿のWebサイト・電話で直接ご確認ください。"
                      "出船報告があり次第このページに反映されます。")
            faq_q4 = f"{area}でおすすめの時期は？"
            faq_a4 = "本ページの旬カレンダーで魚種別の月別釣れ具合をご確認いただけます。過去3年の実績から集計しています。"
            faq_q5 = f"{area}へのアクセス方法は？"
            faq_a5 = _access if _access else f"{area}への詳細なアクセスは各船宿のウェブサイトをご確認ください。"
            auto_faq_html_thin = (
                '<div class="faq-list faq-data">'
                f'<h3 class="faq-block-ttl">{area}釣果データから分かること</h3>'
                f'<details><summary>{faq_q1}</summary><p class="faq-ans">{faq_a1}</p></details>'
                f'<details><summary>{faq_q2}</summary><p class="faq-ans">{faq_a2}</p></details>'
                f'<details><summary>{faq_q3}</summary><p class="faq-ans">{faq_a3}</p></details>'
                f'<details><summary>{faq_q4}</summary><p class="faq-ans">{faq_a4}</p></details>'
                f'<details><summary>{faq_q5}</summary><p class="faq-ans">{faq_a5}</p></details>'
                '</div>'
            )
            fixed_faq_html_thin, fixed_faq_pairs_thin = build_fixed_faq_html("area", area, fixed_faq_data_area)
            faq_html = auto_faq_html_thin + fixed_faq_html_thin

            teaser_html = (
                '<h2 class="st teaser-title">このエリアの予測・分析 <span class="tag coming">まもなく公開</span></h2>'
                '<div class="teaser"><div class="teaser-head"><span class="teaser-badge">開発中</span>'
                f'<span class="teaser-title-in">{area} 日別予測・全ポイント情報</span></div>'
                f'<div class="teaser-desc"><strong>{area}</strong>の明日〜1週間後の魚種別予測、全ポイント一覧、'
                '海況相関の詳細分析を提供します。<br>月額500円 / スポット100円（決済は準備中）。</div></div>'
            )

            import json as _json
            _thin_main_entity = [
                {"@type":"Question","name":faq_q1,"acceptedAnswer":{"@type":"Answer","text":faq_a1}},
                {"@type":"Question","name":faq_q2,"acceptedAnswer":{"@type":"Answer","text":faq_a2}},
                {"@type":"Question","name":faq_q3,"acceptedAnswer":{"@type":"Answer","text":faq_a3}},
                {"@type":"Question","name":faq_q4,"acceptedAnswer":{"@type":"Answer","text":faq_a4}},
                {"@type":"Question","name":faq_q5,"acceptedAnswer":{"@type":"Answer","text":faq_a5}},
            ]
            for _q, _a in fixed_faq_pairs_thin:
                _thin_main_entity.append(
                    {"@type":"Question","name":_q,"acceptedAnswer":{"@type":"Answer","text":_a}}
                )
            faq_jsonld = _json.dumps({
                "@context": "https://schema.org", "@type": "FAQPage",
                "mainEntity": _thin_main_entity,
            }, ensure_ascii=False)
            crumb_jsonld = _json.dumps({
                "@context":"https://schema.org","@type":"BreadcrumbList",
                "itemListElement":[
                    {"@type":"ListItem","position":1,"name":"トップ","item":SITE_URL + "/"},
                    {"@type":"ListItem","position":2,"name":"エリア一覧","item":f"{SITE_URL}/area/"},
                    {"@type":"ListItem","position":3,"name":f"{area}の釣果","item":f"{SITE_URL}/area/{area_slug(area)}.html"},
                ],
            }, ensure_ascii=False)
            _coords = _area_coords_for_placeholder.get(area, {}) if isinstance(_area_coords_for_placeholder, dict) else {}
            _place_obj = {
                "@context":"https://schema.org","@type":"Place",
                "name":area,
                "url":f"{SITE_URL}/area/{area_slug(area)}.html",
            }
            if isinstance(_coords, dict) and _coords.get("lat") is not None and _coords.get("lon") is not None:
                _place_obj["geo"] = {
                    "@type":"GeoCoordinates",
                    "latitude": _coords["lat"],
                    "longitude": _coords["lon"],
                }
            place_jsonld = _json.dumps(_place_obj, ensure_ascii=False)

            past_summary_short = "・".join(top_fish_names[:3]) if top_fish_names else "（過去データ集計中）"
            title_min = f"{area}（{group}）の船釣り情報・過去実績 | 船釣り予想"
            desc_meta_min = (f"{area}（{group}）の船釣り情報。本日の釣果報告は集計待ちです。"
                             f"過去1年{past_total}件の実績データから、{past_summary_short}など主要魚種の旬・代表ポイント・船宿実績をご確認いただけます。")

            html_min = f"""<!DOCTYPE html>
<html lang="ja"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title_min}</title>
<meta name="description" content="{desc_meta_min}">
<link rel="canonical" href="{SITE_URL}/area/{area_slug(area)}.html">
<meta property="og:title" content="{title_min}">
<meta property="og:description" content="{desc_meta_min}">
<meta property="og:url" content="{SITE_URL}/area/{area_slug(area)}.html">
<meta property="og:type" content="website">
<meta property="og:site_name" content="船釣り予想">
<script type="application/ld+json">{crumb_jsonld}</script>
<script type="application/ld+json">{faq_jsonld}</script>
<script type="application/ld+json">{place_jsonld}</script>
{GA_TAG}{ADSENSE_TAG}
<link rel="stylesheet" href="../style.css">
<style>{area_extra_css}
.notice{{background:#fff8e6;border-left:3px solid var(--warn);padding:10px 14px;margin:14px 0;border-radius:0 6px 6px 0;font-size:13px;color:var(--sub);line-height:1.7}}
.month-chart{{background:var(--card);border:1px solid var(--border);border-radius:var(--r);padding:14px;margin-bottom:16px}}
.mb-grid{{display:flex;gap:4px;align-items:flex-end;height:100px;padding:0 4px}}
.mb-col{{flex:1;display:flex;flex-direction:column;align-items:center;justify-content:flex-end}}
.mb-bar{{width:80%;background:linear-gradient(180deg,var(--cta),#f47b3a);border-radius:3px 3px 0 0;min-height:3px}}
.mb-label{{font-size:10px;color:var(--muted);margin-top:6px}}
.mb-num{{font-size:11px;color:var(--accent);font-weight:700}}
.ah-stats{{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-top:12px;max-width:420px;margin-left:auto;margin-right:auto}}
.ah-stats .ah-st{{background:rgba(255,255,255,.08);border-radius:6px;padding:8px 4px}}
.ah-stats .ah-st .v{{font-size:18px;font-weight:800;color:var(--cta)}}
.ah-stats .ah-st .l{{font-size:10px;color:rgba(255,255,255,.7);margin-top:2px}}
@media(max-width:600px){{.ah-stats{{grid-template-columns:1fr 1fr}}}}
.month-chart-caption{{font-size:11px;color:var(--muted);margin-top:8px;text-align:center}}
</style>
</head>
<body>
{_v2_header_nav('area')}
<div class="area-hero">
  <div class="c">
    <h2>{area}</h2>
    <div class="ah-sub">{group}</div>
    <div class="ah-m">本日の釣果報告は集計待ち</div>
    <div class="ah-stats">
      <div class="ah-st"><div class="v">{past_total:,}</div><div class="l">過去1年の釣果記録</div></div>
      <div class="ah-st"><div class="v">{past_30_days}</div><div class="l">直近30日 出船日</div></div>
      <div class="ah-st"><div class="v">{past_30_ships}</div><div class="l">直近30日 出船船宿</div></div>
    </div>
  </div>
</div>
<div class="c">
  <p class="bread"><a href="../index.html">トップ</a> &rsaquo; <a href="../area/">エリア一覧</a> &rsaquo; {area}</p>
  <div class="notice">
    <strong>本日の{area}からの出船報告はまだ届いていません。</strong>
    出船情報は各船宿のWebサイト・電話で直接ご確認ください。
    本ページでは過去1年の実績データから主要魚種・代表ポイント・出船船宿の傾向をご確認いただけます。
  </div>
  <h2 class="st">月別出船トレンド <span class="tag free">無料</span></h2>
  <div class="month-chart">
    <div class="mb-grid">{mb_html}</div>
    <p style="font-size:11px;color:var(--muted);margin-top:8px;text-align:center">過去1年の月別出船日数（単位: 日）</p>
  </div>
  <h2 class="st">このエリアで釣れる魚（過去1年） <span class="tag free">無料</span></h2>
  {fish_grid_html if fish_grid_html else '<p style="color:var(--muted);font-size:13px">過去データを集計中です。</p>'}
  <h2 class="st">出船する船宿（過去1年） <span class="tag free">無料</span></h2>
  {ship_card_html if ship_card_html else '<p style="color:var(--muted);font-size:13px">船宿データを集計中です。</p>'}
  <!-- 広告① -->
  <ins class="adsbygoogle" style="display:block;min-height:0;height:auto" data-ad-client="ca-pub-7406401300491553" data-ad-slot="auto" data-ad-format="auto" data-full-width-responsive="true"></ins>
  <script>(adsbygoogle=window.adsbygoogle||[]).push({{}});</script>
  {related_html}
  {('<h2 class="st">魚種別 旬カレンダー <span class="tag free">無料</span></h2>' + season_map) if season_map else ''}
  {('<h2 class="st">大物実績 TOP5 <span class="tag free">無料</span></h2>' + big_html) if big_html else ''}
  {('<h2 class="st">エリアガイド <span class="tag free">無料</span></h2>' + guide_html) if guide_html else ''}
  <!-- 広告② -->
  <ins class="adsbygoogle" style="display:block;min-height:0;height:auto" data-ad-client="ca-pub-7406401300491553" data-ad-slot="auto" data-ad-format="auto" data-full-width-responsive="true"></ins>
  <script>(adsbygoogle=window.adsbygoogle||[]).push({{}});</script>
  <h2 class="st">よくある質問</h2>
  {faq_html}
  {teaser_html}
</div>
{DATA_NOTE_HTML}
{_v2_footer(crawled_at)}
{_v2_bottom_nav('area')}
</body></html>"""
            with open(os.path.join(WEB_DIR, f"area/{area_slug(area)}.html"), "w", encoding="utf-8") as f:
                f.write(html_min)
            continue

        # 今日の釣果
        today_catches, fish_label, area_date = _resolve_display_dataset(catches, today_str)
        use_today = (area_date == today_str)
        fish_source = catches

        # 魚種別集計（fia-grid用）
        # 修正: valid_catches 形式（count_range/size_cm dict）と CSV 形式
        # （cnt_min/cnt_max/size_min/size_max スカラー）の両方に対応。
        # 過去は CSV 列名のみ参照していたため 匹数range・サイズ が常に空だった。
        fish_data = {}
        for c in fish_source:
            for f in c["fish"]:
                if not f or f in ("不明", "欠航"):
                    continue
                d = fish_data.setdefault(f, {"cnt_mins": [], "cnt_maxs": [], "sz_mins": [], "sz_maxs": [], "ships": set(), "records": 0, "ship_recs": {}})
                d["records"] += 1
                d["ships"].add(c["ship"])
                d["ship_recs"][c["ship"]] = d["ship_recs"].get(c["ship"], 0) + 1
                # count_range が dict なら優先（in-memory形式）、無ければ cnt_min/max（CSV形式）
                cr = c.get("count_range")
                if isinstance(cr, dict):
                    if cr.get("min") is not None and not cr.get("is_boat"):
                        d["cnt_mins"].append(cr["min"])
                    if cr.get("max") is not None and not cr.get("is_boat"):
                        d["cnt_maxs"].append(cr["max"])
                else:
                    if c.get("cnt_min") is not None: d["cnt_mins"].append(c["cnt_min"])
                    if c.get("cnt_max") is not None: d["cnt_maxs"].append(c["cnt_max"])
                sz = c.get("size_cm")
                if isinstance(sz, dict):
                    if sz.get("min") is not None: d["sz_mins"].append(sz["min"])
                    if sz.get("max") is not None: d["sz_maxs"].append(sz["max"])
                else:
                    if c.get("size_min") is not None: d["sz_mins"].append(c["size_min"])
                    if c.get("size_max") is not None: d["sz_maxs"].append(c["size_max"])

        top_fish_items = sorted(fish_data.items(), key=lambda x: -x[1]["records"])[:6]

        # 今週の魚種説明文（2〜3文）
        _week_n = len(catches)
        _week_fish_names = [f for f, _ in top_fish_items]
        _week_ships = len(set(c["ship"] for c in catches))
        if _week_fish_names:
            _desc1 = f"{area}では今週{_week_n}件・{_week_ships}船宿から釣果報告があります。"
            _fish_join = "・".join(_week_fish_names[:4])
            _desc2 = f"{_fish_join}など{len(_week_fish_names)}種の釣果が確認されています。"
            _best_fish, _best_fd = top_fish_items[0]
            if _best_fd["cnt_maxs"]:
                _best_max = int(max(_best_fd["cnt_maxs"]))
                _desc3 = f"なかでも{_best_fish}が{_best_max}匹の最高釣果で好調です。"
            else:
                _desc3 = f"なかでも{_best_fish}が最も多くの船宿で釣れています。"
            fia_desc_html = f'<p style="font-size:13px;line-height:1.7;color:var(--sub);margin:0 0 12px">{_desc1}{_desc2}{_desc3}</p>'
        else:
            fia_desc_html = ""

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
            # ⚠️ fia は <a> なので内部に船宿リンク <a> を入れるとブラウザが
            # 自動的にネストアンカーを分離 → 「◎船宿名」が独立カードとして
            # 表示される事故になる（過去発生済み）。船宿名はプレーンテキストで。
            fia_cards += (
                f'<a class="fia" href="{_fish_area_link_or_fish(fish, area, depth=1)}">'
                f'<div class="fn"><img src="../assets/fish/{fish_img_slug(fish)}/{fish_img_slug(fish)}_emoji.webp" alt="" class="fn-emoji" width="18" height="18" loading="lazy" decoding="async" onerror="this.style.display=\'none\'">{fish}</div>'
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
        moon_age = sea_fc.get("moon_age")
        sst_str = f"{sst:.1f}℃" if sst else "—"
        wave_str = f"{wave:.1f}m" if wave else "—"
        wind_txt = (_wind_dir_text(wind_dir) if wind_dir else "") + (f"{wind_spd:.1f}m/s" if wind_spd else "")
        wind_str = wind_txt if wind_txt else "—"
        # 潮汐: 数字（潮差cm）ではなく 大潮/中潮/小潮 等の名称で表示
        tide_label = _moon_title(moon_age) if moon_age is not None else ""
        tide_str = tide_label if tide_label else "—"
        # 月齢: 数字ではなく 満月/新月/半月 等の名称で表示
        moon_label = _moon_phase_name(moon_age) if moon_age is not None else ""
        moon_str = moon_label if moon_label else "—"
        pressure_str = f"{int(pressure)}hPa" if pressure else "—"
        # ヒーローの海況テキスト
        sea_parts = []
        if sst: sea_parts.append(f"水温{sst_str}")
        if wave: sea_parts.append(f"波{wave_str}")
        if wind_txt: sea_parts.append(wind_str)
        if tide_label: sea_parts.append(tide_label)
        ah_sea_html = f'<div class="ah-sea">{" / ".join(sea_parts)}</div>' if sea_parts else ""

        # 海況1行コメント: 平年比SST・波高/風による欠航リスク
        sea_comment = ""
        if sea_fc:
            cm_parts = []
            # SST 平年比（簡易: 月別の平均SST 想定値との差）
            # 関東沿岸の月別 SST 平年値（5月=17℃ 基準で簡易テーブル）
            _sst_norm = {1:14, 2:13, 3:14, 4:16, 5:18, 6:21, 7:24, 8:26, 9:25, 10:22, 11:19, 12:16}
            if sst is not None:
                norm = _sst_norm.get(now.month, 18)
                diff = sst - norm
                if diff >= 1.5:
                    cm_parts.append(f"水温は平年比+{diff:.1f}℃と高め")
                elif diff <= -1.5:
                    cm_parts.append(f"水温は平年比{diff:.1f}℃と低め")
                else:
                    cm_parts.append(f"水温は平年並み（{sst:.1f}℃）")
            # 波・風 欠航リスク（内部的に外海/内海の閾値で切替するが、文言には出さない）
            sea_type = "内海" if group in _UCHIUMI_AREAS else "外海"
            warn_w, warn_wnd, bad_w, bad_wnd = _RISK_THR[sea_type]
            if wave is not None or wind_spd is not None:
                _w = wave or 0
                _wd = wind_spd or 0
                if _w >= bad_w or _wd >= bad_wnd:
                    cm_parts.append(f"波{_w:.1f}m・風{_wd:.0f}m/sの荒天で欠航警戒")
                elif _w >= warn_w or _wd >= warn_wnd:
                    cm_parts.append(f"波{_w:.1f}m・風{_wd:.0f}m/sでやや荒れ気味、出船注意")
                else:
                    cm_parts.append(f"波{_w:.1f}m・風{_wd:.0f}m/sと穏やかで出船日和")
            if cm_parts:
                sea_comment = f'<p style="font-size:13px;line-height:1.7;color:var(--sub);margin:0 0 12px">{"。".join(cm_parts)}。</p>'

        sea_section_html = ""
        if sea_fc:
            sea_section_html = (
                f'<h2 class="st">海況データ <span class="tag free">無料</span></h2>'
                f'{sea_comment}'
                f'<div class="sea-grid">'
                f'<div class="sea-item"><div class="sv">{sst_str}</div><div class="sl2">水温</div></div>'
                f'<div class="sea-item"><div class="sv">{wave_str}</div><div class="sl2">波高</div></div>'
                f'<div class="sea-item"><div class="sv">{wind_str}</div><div class="sl2">風</div></div>'
                f'<div class="sea-item"><div class="sv">{tide_str}</div><div class="sl2">潮汐</div></div>'
                f'<div class="sea-item"><div class="sv">{moon_str}</div><div class="sl2">月相</div></div>'
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
            badges = "".join(
                f'<span class="{"g" if i == 0 else "o"}">'
                f'<img src="../assets/fish/{fish_img_slug(f)}/{fish_img_slug(f)}_emoji.webp" alt="" class="sl-emoji" width="14" height="14" loading="lazy" decoding="async" onerror="this.style.display=\'none\'">{f}</span>'
                for i, (f, _) in enumerate(top_f)
            )
            pts = [c["point_place1"] for c in catches if c["ship"] == sn and c.get("point_place1")]
            from collections import Counter as _Counter
            top_pt = _Counter(pts).most_common(1)[0][0] if pts else ""
            ship_items_html += (
                f'<div class="sl-item">'
                f'<div class="sl-top"><span class="sl-name">{_ship_link(sn, depth=1)}</span>'
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
        area_season_html = build_area_season_map_html(area, area_decadal, top_fish_list, hist_rows=_hist_rows_for_placeholder)
        area_guide_html = build_area_guide_html(area, area_desc_data)
        auto_area_faq_html, auto_area_faq_pairs = build_area_faq_html(area, area_desc_data, top_fish_items=top_fish_items, area_catches=catches)
        fixed_area_faq_html, fixed_area_faq_pairs = build_fixed_faq_html("area", area, fixed_faq_data_area)
        area_faq_html = auto_area_faq_html + fixed_area_faq_html
        _area_all_faq_pairs = auto_area_faq_pairs + fixed_area_faq_pairs
        area_description_html = build_area_description_html(area, area_desc_data)
        # JSON-LD: FAQPage + Place（統合版）
        _area_faq_items = ",\n".join(
            f'{{"@type":"Question","name":{json.dumps(q, ensure_ascii=False)},"acceptedAnswer":{{"@type":"Answer","text":{json.dumps(a, ensure_ascii=False)}}}}}'
            for q, a in _area_all_faq_pairs
        )
        _area_coords_ld = _ship_load_area_coords()
        _place_script = ""
        if _area_coords_ld and area in _area_coords_ld:
            _lat = _area_coords_ld[area].get("lat")
            _lon = _area_coords_ld[area].get("lon")
            if _lat and _lon:
                _place_script = f'<script type="application/ld+json">{{"@context":"https://schema.org","@type":"Place","name":{json.dumps(area, ensure_ascii=False)},"geo":{{"@type":"GeoCoordinates","latitude":{_lat},"longitude":{_lon}}}}}</script>'
        area_faq_jsonld = f'<script type="application/ld+json">{{"@context":"https://schema.org","@type":"FAQPage","mainEntity":[{_area_faq_items}]}}</script>{_place_script}'

        # SEO
        area_url = f"{SITE_URL}/area/{area_slug(area)}.html"
        _top_fish_str = "・".join(f for f, _ in top_fish_items[:3])
        _area_desc_fish = f"{_top_fish_str}など" if _top_fish_str else ""
        today_cnt = len(today_catches)
        area_desc = f"{area}（{group}）の船釣り釣果。{fish_label}{today_cnt}件。{_area_desc_fish}釣れている魚種と船宿情報を毎日更新。"

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
            f'<div class="cs-title">準備中</div>'
            f'<ul class="cs-features"><li>エリア別日別予測（7日先）</li>'
            f'<li>全ポイント情報</li><li>欠航リスク予報</li></ul>'
            f'<div class="cs-price">月額<em>500円</em> / 1回<em>100円</em></div>'
            f'</div></div></div></div>'
        )

        html = f"""<!DOCTYPE html>
<html lang="ja"><head>
  <meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
  <title>{area}の釣果情報・おすすめ船宿【{fish_label}{today_cnt}件】| 船釣り予想</title>
  <meta name="description" content="{area_desc}">
  <link rel="canonical" href="{area_url}">
  <meta property="og:title" content="{area}の釣果情報・おすすめ船宿【{fish_label}{today_cnt}件】">
  <meta property="og:description" content="{area_desc}">
  <meta property="og:url" content="{area_url}">
  <meta property="og:type" content="website">
  <meta property="og:site_name" content="船釣り予想">
  <script type="application/ld+json">{{"@context":"https://schema.org","@type":"BreadcrumbList","itemListElement":[{{"@type":"ListItem","position":1,"name":"トップ","item":"{SITE_URL}/"}},{{"@type":"ListItem","position":2,"name":"エリア一覧","item":"{SITE_URL}/area/"}},{{"@type":"ListItem","position":3,"name":"{area}の釣果","item":"{area_url}"}}]}}</script>
  {area_faq_jsonld}
  {GA_TAG}
  {ADSENSE_TAG}
  <link rel="stylesheet" href="../style.css">
  <style>{area_extra_css}</style>
</head>
<body>
{_v2_header_nav('area')}
<div class="area-hero">
  <div class="c">
    <h2>{area}</h2>
    <div class="ah-sub">{group}</div>
    <div class="ah-m">{today_cnt}件 <small>({len(set(c['ship'] for c in today_catches))}船宿・{fish_label})</small></div>
    {ah_sea_html}
  </div>
</div>
<div class="c">
  <p class="bread"><a href="../index.html">トップ</a> &rsaquo; <a href="../area/">エリア一覧</a> &rsaquo; {area}</p>
  <h2 class="st">このエリアで今週釣れている魚 <span class="tag free">無料</span></h2>
  {fia_desc_html}<div class="fia-grid">{fia_cards if fia_cards else '<p style="color:var(--muted);font-size:13px">今週の釣果はまだ集計中です</p>'}</div>
  {sea_section_html}
  <h2 class="st">船宿一覧 <span class="tag free">無料</span></h2>
  <div class="sl-card">{ship_items_html}</div>
  <!-- 広告① -->
  <ins class="adsbygoogle" style="display:block;min-height:0;height:auto" data-ad-client="ca-pub-7406401300491553" data-ad-slot="auto" data-ad-format="auto" data-full-width-responsive="true"></ins>
  <script>(adsbygoogle=window.adsbygoogle||[]).push({{}});</script>
  {point_box_html}
  {nearby_section_html}
  <h2 class="st">魚種別 旬カレンダー <span class="tag free">無料</span></h2>
  {area_season_html}
  {('<h2 class="st">エリアガイド</h2>' + area_guide_html) if area_guide_html else ''}
  <!-- 広告② -->
  <ins class="adsbygoogle" style="display:block;min-height:0;height:auto" data-ad-client="ca-pub-7406401300491553" data-ad-slot="auto" data-ad-format="auto" data-full-width-responsive="true"></ins>
  <script>(adsbygoogle=window.adsbygoogle||[]).push({{}});</script>
  {('<h2 class="st">このエリアについて</h2>' + area_description_html) if area_description_html else ''}
  <h2 class="st">よくある質問</h2>
  {area_faq_html}
  {area_teaser_html}
</div>
{DATA_NOTE_HTML}
{_v2_footer(crawled_at)}
{_v2_bottom_nav('area')}
</body></html>"""
        with open(os.path.join(WEB_DIR, f"area/{area_slug(area)}.html"), "w", encoding="utf-8") as f:
            f.write(html)

    # area/index.html: エリア一覧（今週 = 過去7日間ローリング、CSV由来）
    # 再クロール禁止: data/V2/*.csv の蓄積データを読み込む
    _recent7_area = _load_recent_catches_for_index(now, days=7)
    area_week_summary = {a: [] for a in area_summary.keys()}
    for c in _recent7_area:
        area_week_summary.setdefault(c["area"], []).append(c)
    _group_order = ["茨城", "千葉・外房", "千葉・内房", "千葉・東京湾奥", "東京", "神奈川・東京湾", "神奈川・相模湾", "静岡"]
    area_index_sections = ""
    for grp in _group_order:
        grp_areas = [(area, area_week_summary[area]) for area in area_week_summary
                     if area in AREA_GROUPS.get(grp, []) and len(area_week_summary[area]) >= 2]
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
    _other = [(area, area_week_summary[area]) for area in area_week_summary
              if area not in _matched and len(area_week_summary[area]) >= 2]
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
  <link rel="stylesheet" href="../style.css">
  <style>{area_index_css}</style>
</head>
<body>
{_v2_header_nav('area')}
<div style="background:var(--accent);color:#fff;padding:18px 14px 20px;margin-bottom:0">
  <div class="c"><div style="font-size:26px;font-weight:800">エリア別 釣果一覧</div>
  <div style="font-size:12px;opacity:.7;margin-top:4px">今週釣果あり {len([a for a,cs in area_week_summary.items() if len(cs)>=2])}エリア</div></div>
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
def _decade_label(dn):
    """decade_no（1-36）→ 'X月上/中/下旬' ラベル"""
    month = ((int(dn) - 1) // 3) + 1
    jun = ["上旬", "中旬", "下旬"][(int(dn) - 1) % 3]
    return f"{month}月{jun}"


def _fa_catches_stats(fa_catches):
    """fish_area 用の釣果統計 (n_personal, avg_med, max_val, p25, p75, max_boat)"""
    personal = [
        c for c in fa_catches
        if c.get("count_range") and not c["count_range"].get("is_boat")
        and c["count_range"].get("max") is not None
    ]
    max_boat = max(
        (c["count_range"]["max"] for c in fa_catches
         if c.get("count_range") and c["count_range"].get("is_boat")
         and c["count_range"].get("max") is not None),
        default=0
    )
    if not personal:
        return 0, 0.0, 0, 0, 0, max_boat
    mins = sorted([(c["count_range"].get("min") or 0) for c in personal])
    maxes = sorted([c["count_range"]["max"] for c in personal])
    avgs = sorted([((c["count_range"].get("min") or 0) + c["count_range"]["max"]) / 2 for c in personal])
    n = len(personal)
    med = avgs[n // 2]
    p25 = mins[int(n * 0.25)] if n >= 4 else mins[0]
    p75 = maxes[int(n * 0.75)] if n >= 4 else maxes[-1]
    return n, round(med, 1), int(maxes[-1]), int(p25), int(p75), max_boat


def _build_fa_intro_html(fish, area, fa_catches, decadal_calendar, area_description=None):
    """fish_area 説明文（200字以上・自サイトデータのみ）
    H3 (T22): area_description を渡すとエリア固有の1文を冒頭に差し込む。
    """
    N = len(fa_catches)
    n_personal, avg_med, max_val, p25, p75, max_boat = _fa_catches_stats(fa_catches)

    fish_decades = decadal_calendar.get(fish, {}) if decadal_calendar else {}
    peak_label = ""
    if fish_decades:
        top_dn = max(fish_decades.items(), key=lambda x: x[1].get("cnt_index", 0))
        peak_label = _decade_label(top_dn[0])

    ship_counts: dict = {}
    for c in fa_catches:
        sn = c.get("ship", "")
        if sn:
            ship_counts[sn] = ship_counts.get(sn, 0) + 1
    top_ships = sorted(ship_counts.items(), key=lambda x: -x[1])[:3]

    dates = sorted([c.get("date", "") for c in fa_catches if c.get("date")])
    years_str = ""
    if len(dates) >= 2:
        y0, y1 = dates[0][:4], dates[-1][:4]
        years_str = f"（{y0}年〜{y1}年）" if y0 != y1 else f"（{y0}年）"

    # H3 (T22): area_description.json からエリア固有の1文を抽出して冒頭に差し込む
    area_intro = ""
    if area_description and isinstance(area_description, dict):
        desc_entry = area_description.get(area) or area_description.get(area + "港") or {}
        desc_full = desc_entry.get("description", "") if isinstance(desc_entry, dict) else ""
        if desc_full:
            first_para = desc_full.split("\n\n")[0]
            first_sentence = first_para.split("。")[0] + "。" if first_para else ""
            if len(first_sentence) >= 10:
                area_intro = first_sentence

    total_ships = len(ship_counts)
    lines = []
    if area_intro:
        lines.append(area_intro)
    lines.append(f"{area}での{fish}の釣果データは{N}件記録されています{years_str}。")
    if peak_label:
        lines.append(f"月別の集計では{peak_label}前後に釣果が集中する傾向があります。")
    if n_personal >= 5:
        lines.append(f"1回の釣行あたりの中央値は{avg_med:.0f}匹で、最高釣果は{max_val}匹の記録があります。")
        if p25 < p75:
            lines.append(f"標準的な釣果レンジは{p25}〜{p75}匹です。")
        lines.append(f"釣果は潮回りや水温の影響を受けやすく、旬の時期を選ぶと安定した釣果が期待できます。")
    elif max_val > 0:
        lines.append(f"最高釣果は{max_val}匹の記録があります（データ蓄積中：{N}件）。")
        lines.append(f"釣果は潮回りや季節によって変動するため、シーズンバーと直近の釣果カードを参考にしてください。")
    elif max_boat > 0:
        lines.append(f"乗合船全体の最大釣果は{max_boat}匹の記録があります。")
        lines.append(f"個人釣果の統計は引き続きデータ収集中です。釣果は潮回りや季節によって変動します。")
    else:
        lines.append(f"引き続きデータを収集中です。")
        lines.append(f"釣果は潮回りや季節によって変動するため、旬の時期を選ぶと安定した釣果が期待できます。")
    if top_ships:
        ship_strs = "、".join(f"{sn}（{cnt}件）" for sn, cnt in top_ships)
        lines.append(f"出船実績の多い船宿は{ship_strs}です。")
    if total_ships > 0:
        lines.append(f"このエリアでは計{total_ships}船宿が{fish}の出船実績を持ちます。各船宿の出船スケジュールは直接ご確認ください。")
    text = "".join(lines)
    if len(text) < 200:
        text += "このページのシーズンバーと釣果カードで最新の傾向を確認の上、釣行計画にお役立てください。"
    return f'<p class="fa-intro">{text}</p>'


def build_fish_area_faq_html(fish, area, fa_catches, decadal_calendar):
    """fish_area ページ用 FAQ 3問 + FAQPage JSON-LD を返す (html, jsonld) タプル"""
    N = len(fa_catches)
    n_personal, avg_med, max_val, p25, p75, max_boat = _fa_catches_stats(fa_catches)

    # Q1: 最も釣れる時期
    fish_decades = decadal_calendar.get(fish, {}) if decadal_calendar else {}
    if fish_decades and N >= 5:
        sorted_dns = sorted(fish_decades.items(), key=lambda x: -x[1].get("cnt_index", 0))
        top3 = sorted_dns[:3]
        top_labels = "、".join(_decade_label(dn) for dn, _ in top3)
        top_score = round(top3[0][1].get("cnt_index", 0), 1)
        q1_ans = (
            f"{area}での{fish}は{_decade_label(top3[0][0])}に釣果指数が最も高くなります"
            f"（釣果指数{top_score}）。"
            f"上位3旬は{top_labels}で、この時期に釣果が集中しています。"
            f"シーズン外でも釣果報告はあり、直近{N}件のデータに基づく集計です。"
        )
    elif N >= 5:
        q1_ans = (
            f"直近{N}件の釣果データをもとに季節傾向を集計中です。"
            f"このページの年間シーズンバーで月別の傾向をご確認ください。"
        )
    else:
        q1_ans = f"データ蓄積中（{N}件）のため、季節ピークの特定には十分なサンプルが必要です。今後のデータ追加をお待ちください。"

    # Q2: 釣果レンジ
    if n_personal >= 10:
        q2_ans = (
            f"直近{N}件のデータでは{p25}〜{p75}匹が標準的なレンジです（中央値{avg_med:.0f}匹）。"
            f"{area}での{fish}の最高記録は{max_val}匹です。"
            f"釣果は潮回り・水温・季節によって変動します。直近の釣果カードおよびページ上部のシーズンバーもご参考ください。"
        )
    elif n_personal >= 3:
        q2_ans = (
            f"直近データ（{n_personal}件の実釣記録）では最高{max_val}匹の記録があります。"
            f"釣果は潮回り・水温・季節によって大きく変動します。"
            f"引き続きサンプルを蓄積中のため、今後より精度の高い釣果レンジをお伝えできる予定です。"
            f"直近の実績はこのページの釣果カードをご参照ください。"
        )
    elif max_boat > 0:
        q2_ans = (
            f"{area}での{fish}は直近{N}件の釣果記録があります。"
            f"乗合船全体での最大釣果は{max_boat}匹の記録があります（船全体の合計数）。"
            f"個人別釣果の統計的レンジは引き続きデータ収集中のため、直近の釣果カードをご確認ください。"
        )
    else:
        q2_ans = (
            f"{area}での{fish}は現在データ蓄積中（{N}件）です。"
            f"釣果レンジの統計的な算出には一定のサンプル数が必要なため、引き続き釣果データを収集しています。"
            f"データが蓄積され次第、より詳細な情報を提供します。直近の実績はこのページの釣果カードをご確認ください。"
        )

    # Q3: 船宿
    ship_counts: dict = {}
    for c in fa_catches:
        sn = c.get("ship", "")
        if sn:
            ship_counts[sn] = ship_counts.get(sn, 0) + 1
    top3_ships = sorted(ship_counts.items(), key=lambda x: -x[1])[:3]
    total_ships = len(ship_counts)
    if top3_ships:
        ship_strs = "、".join(f"{sn}（{cnt}件）" for sn, cnt in top3_ships)
        q3_ans = (
            f"{area}での{fish}釣果データがある船宿は計{total_ships}船宿です。"
            f"記録件数が多い順に{ship_strs}が上位です。"
            f"出船スケジュールや仕掛けのレンタル・販売の有無は各船宿に直接お問い合わせください。"
            f"予約方法は電話またはWebから確認できます。"
        )
    else:
        q3_ans = (
            f"{area}での{fish}の船宿情報はデータ蓄積中です。"
            f"引き続き釣果データを収集しており、出船実績のある船宿が確認でき次第、このページに反映します。"
        )

    faqs = [
        (f"{area}で{fish}が最も釣れる時期はいつですか？", q1_ans),
        (f"{area}での{fish}の釣果はどのくらいですか？", q2_ans),
        (f"{area}で{fish}を狙える船宿はどこですか？", q3_ans),
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


def build_fish_area_pages(data, crawled_at="", history=None, decadal_calendar=None):
    os.makedirs(os.path.join(WEB_DIR, "fish_area"), exist_ok=True)
    if decadal_calendar is None:
        decadal_calendar = load_decadal_calendar()
    # H3 (T22): area_description.json をロード（エリア固有1文をイントロに差し込む）
    _area_desc_fa = load_area_description()
    # 年間シーズンバーを実データで生成するため過去CSVを一度だけロード
    _hist_rows_for_fa = _load_historical_catches()
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
.sr .sr-rank{font-size:11px;font-weight:700;color:var(--muted);flex:0 0 18px;text-align:center}
.sr .sr-name{flex:0 0 80px;font-size:13px;font-weight:700;color:var(--accent)}
.sr .sr-range{flex:0 0 80px;font-size:13px;font-weight:700;color:var(--cta)}
.sr .sr-pt{flex:1;font-size:10px;color:var(--muted);text-align:right}
.season-bar{display:flex;gap:2px;margin-top:8px;justify-content:center;flex-wrap:wrap;margin-bottom:6px}
.sb-cell{min-width:20px;height:18px;border-radius:3px;font-size:10px;color:#fff;display:flex;align-items:center;justify-content:center;padding:0 2px}
.sb-cell.peak-count{background:#e85d04}
.sb-cell.peak-size{background:#7209b7}
.sb-cell.mid{background:#1a6ea8}
.sb-cell.low{background:#1a3050}
.sb-cell.now{outline:2px solid #fff;outline-offset:1px}
.sb-legend{font-size:9px;color:var(--muted);text-align:center;margin-top:3px;margin-bottom:14px}
.sb-legend .leg-count::before{content:"";display:inline-block;width:8px;height:8px;background:#e85d04;border-radius:2px;margin-right:3px;vertical-align:middle}
.sb-legend .leg-size::before{content:"";display:inline-block;width:8px;height:8px;background:#7209b7;border-radius:2px;margin-right:3px;vertical-align:middle}"""

    now_fa_global = datetime.now(JST).replace(tzinfo=None)
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
  <div class="stat-card"><div class="sv">{'%.0f' % combo_avg if combo_avg else '-'}匹</div><div class="sl">釣果目安</div></div>
  <div class="stat-card{trend_cls}"><div class="sv">{max_cnt if max_cnt else '-'}匹</div><div class="sl">最高釣果</div></div>
</div>"""
        # 旬カレンダー（数釣/型釣 × 12ヶ月 ヒートマップ・実データ駆動）
        # 2026/05/06: フォーマット統一のため年間シーズンバー→旬カレンダーに変更。
        combo_season_map_fa = build_combo_season_map_html(
            fish, area, _hist_rows_for_fa, current_month_fa, decadal_calendar=decadal_calendar
        )
        # コンボコメント（実データ駆動）
        season_score_fa = get_combo_season_score(fish, area, _hist_rows_for_fa, current_month_fa)
        group_fa = _area_to_group(area) or area
        if season_score_fa >= 4:
            combo_cmt = f"{group_fa}の{fish}は今月がシーズン本番。{trend_label}の傾向です。"
        elif season_score_fa >= 3:
            combo_cmt = f"{group_fa}の{fish}はシーズン中盤。安定した釣果が期待できます。"
        elif season_score_fa >= 2:
            combo_cmt = f"{group_fa}の{fish}はシーズンの立ち上がり／終盤。{trend_label}の傾向。"
        else:
            combo_cmt = f"{group_fa}の{fish}はオフシーズンですが釣果報告あり。"
        combo_comment_html = f'<div class="combo-comment">{combo_cmt}</div>'
        # V2: ship-rank（sr スタイル）
        today_str_fa = now_fa_global.strftime("%Y/%m/%d")
        ship_data_fa: dict = {}
        for c in catches:
            d = ship_data_fa.setdefault(c["ship"], {"cnt": 0, "his": [], "los": [], "today": False})
            d["cnt"] += 1
            cr = c.get("count_range")
            if cr and not cr.get("is_boat"):
                if cr.get("max") is not None:
                    d["his"].append(cr["max"])
                if cr.get("min") is not None:
                    d["los"].append(cr["min"])
                elif cr.get("max") is not None:
                    d["los"].append(cr["max"])
            if c.get("date") == today_str_fa:
                d["today"] = True
        sr_items_fa = ""
        for i, (sn, sd) in enumerate(sorted(ship_data_fa.items(), key=lambda x: -(max(x[1]["his"]) if x[1]["his"] else 0))[:8]):
            s_lo = int(min(sd["los"])) if sd["los"] else None
            s_hi = int(max(sd["his"])) if sd["his"] else None
            if s_lo is not None and s_hi is not None and s_lo != s_hi:
                s_range = f"{s_lo}〜{s_hi}匹"
            elif s_hi is not None:
                s_range = f"{s_hi}匹"
            else:
                s_range = f"{sd['cnt']}件"
            sr_items_fa += (
                f'<div class="sr">'
                f'<span class="sr-rank">{i+1}</span>'
                f'<span class="sr-name">{_ship_link(sn, depth=1)}</span>'
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
                f'<div class="sl-head"><span class="sl-name">{_ship_link(c["ship"], depth=1)}</span>'
                f'<span class="sl-date">{(c.get("date") or "")[-5:]}</span></div>'
                f'<div class="sl-sub">{sub if sub else "釣果あり"}</div>'
                f'</div>'
            )
        # 説明文 + FAQ（AdSense コンテンツ充実）
        # H3 (T22): area_description を渡してエリア固有1文を冒頭に差し込む
        fa_intro_html = _build_fa_intro_html(fish, area, catches, decadal_calendar, area_description=_area_desc_fa)
        fa_faq_html, fa_faq_ld = build_fish_area_faq_html(fish, area, catches, decadal_calendar)
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
  <script type="application/ld+json">{{"@context":"https://schema.org","@type":"BreadcrumbList","itemListElement":[{{"@type":"ListItem","position":1,"name":"トップ","item":"{SITE_URL}/"}},{{"@type":"ListItem","position":2,"name":"魚種一覧","item":"{SITE_URL}/fish/"}},{{"@type":"ListItem","position":3,"name":"{fish}の釣果","item":"{SITE_URL}/fish/{fish_slug(fish)}.html"}},{{"@type":"ListItem","position":4,"name":"{area}の{fish}釣果","item":"{page_url}"}}]}}</script>
  {fa_faq_ld}
  {GA_TAG}
  {ADSENSE_TAG}
  <link rel="stylesheet" href="../style.css">
  <style>
{fa_extra_css}
.fa-intro{{font-size:13px;line-height:1.7;color:var(--text);margin-bottom:16px}}</style>
</head>
<body>
{_v2_header_nav('')}
<div class="c">
  <p class="bread"><a href="../index.html">トップ</a> &rsaquo; <a href="../fish/{fish_slug(fish)}.html">{fish}</a> &rsaquo; {area}</p>
  <h2 class="st">{area}の{fish}釣果情報</h2>
  {fa_intro_html}
  {stat_cards_fa}
  <h2 class="st">旬カレンダー <span class="tag free">無料</span></h2>
  {combo_season_map_fa}
  {combo_comment_html}
  <h2 class="st">船宿ランキング <span class="tag free">無料</span></h2>
  {ship_rank_fa_html}
  <h2 class="st">最近の釣果 <span class="tag free">無料</span></h2>
  {recent_cards_fa}
  <h2 class="st">よくある質問</h2>
  {fa_faq_html}
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
_CALENDAR_MONTHLY_COMMENTS = {
    1: ("1月：寒アジ・フグ・ヤリイカの好期",
        "厳冬期に入り外洋は波が高い日が多くなるが、東京湾奥の寒アジが絶好調。金沢八景・羽田沖では20〜25cmの良型が揃い、1束（100匹）超えも珍しくない。身が締まって脂がのり、食味は一年で最高の時期だ。フグは関東全域で乗っ込みシーズン真っ只中で型が揃い、大原港の越冬ヒラメは3kg超えも期待できる。ヤリイカは相模湾・千葉勝浦で釣果が安定し、型狙いに最適。カサゴ・メバルは冬の根魚として各港でコンスタントに出る。水温が低く全体的に活性は低いが、口を使った個体は型が大きい傾向があるため、仕掛けをシンプルに丁寧に誘うのがコツ。"),
    2: ("2月：寒の底・型狙いに最適なシーズン",
        "冬の底値を迎えるが、東京湾奥の寒アジは引き続き絶好調。身の締まった良型が揃い数釣りを楽しめる。フグは産卵前の荒食いで型が大きくなる時期で、鹿島・大原エリアでは良型のショウサイフグ・アカメフグが揃う。大原・鴨川のヒラメは乗っ込みシーズン継続で、遠征釣りの筆頭ターゲットとして人気が高い。カサゴ・メバルは産卵前の荒食いで数釣りが楽しめ、ヤリイカは相模湾深場で安定した釣果を維持する。2月後半からは水温の底打ちを迎え、3月のマダイ乗っ込み開幕に向けて釣果が徐々に上向いてくる兆しが現れる。"),
    3: ("3月：マダイ乗っ込み開幕・春の扉が開く",
        "春が近づき水温が徐々に上昇する端境期。マダイの乗っ込みシーズンが開幕し、久里浜・剣崎沖でテンヤ・コマセ釣りが盛んになる。3〜5kgの良型が出始め、ゴールデンウィークに向けて期待が高まる時期だ。フグは産卵期に向けて終盤を迎えるが、型の大きい個体が多くまだ十分狙える。ヒラメはそろそろ終盤戦。イサキが徐々に浅場に上がってくる兆しがあり、千葉外房・静岡エリアで早期の釣果報告が入ることも。アジは春の旬ピークに向けて釣果が上向き始める。シロギスも4月開幕に向けて準備中で、暖かい日には浅場で顔を見せ始める。"),
    4: ("4月：春本番・マダイとシロギスが主役",
        "春本番。マダイの乗っ込みが最盛期を迎え、産卵前の荒食いで型・数ともに期待大。剣崎沖・久里浜・走水ではテンヤ・コマセともに好釣果が続き、3kg超えの良型が数釣りできることもある。シロギスが浅場に上がり始めシーズン開幕、天気の良い凪ぎの日には数釣りが楽しめる。イサキも千葉・静岡エリアで釣果が出始め、アジは春の旬ピークで東京湾奥を中心に数釣りが楽しめる。4月後半からはワラサ・イナダの回遊情報も入り始め、青物狙いの出船も増える。タチウオは5月解禁に向けて期待が高まる。水温上昇とともに魚の活性が一気に高くなるシーズン。"),
    5: ("5月：船釣りのゴールデンシーズン",
        "船釣りの最盛期。マダイは乗っ込みピーク〜後期で数・型ともに期待大。シロギスは本格シーズン突入で束釣りも現実的。イサキも千葉外房・静岡沖で開幕し、大型の型釣りが楽しい。アジは数釣り全盛期で、東京湾奥の各港では100匹超えの釣果も珍しくない。ヤリイカは相模湾・千葉でシーズン終盤、スルメイカが沖合で釣れ始める。マゴチが浅場に上がり始めシーズン開幕。ワラサ・イナダも回遊が活発化し、タチウオは東京湾で解禁され注目度が高まる。5月はほぼどの魚種も何らかの旬を迎えており、船釣り初心者から上級者まで楽しめる最良のシーズン。"),
    6: ("6月：夏告げる青物と東京湾タチウオ開幕",
        "夏を迎え多彩な魚種が釣れる好シーズン。タチウオが東京湾で本格シーズン開幕し、夜釣り・日中釣りともに人気が高い。マダイは乗っ込み後期で数は落ち着くが、産卵後の荒食いで型狙いが楽しい。イサキが各地で最盛期を迎え、静岡・千葉で数釣り炸裂。シロギスは浅場で好調継続。マダコが東京湾内で解禁になる港が増え、船タコ釣りが人気を集める。スルメイカが沖合で釣れ盛り。カツオ・ワラサなど青物の回遊情報も入り始め、沖合への出船が増える。夏日の多い6月は早朝出船の時合いを逃さないことが釣果を左右する。"),
    7: ("7月：タチウオドラゴン・カツオ接岸・夏の最盛期",
        "真夏のハイシーズン。タチウオが東京湾で最盛期を迎え、指4本超えのドラゴンサイズ狙いに船が集まる。夜釣り・日中釣りともに人気で、予約が早期に埋まることも多い。イサキは各地でまだ好調で数釣りが楽しめる。シロギスは夏の浅場釣りとして安定した釣果を見せる。マダコが東京湾内で旬ピーク。スルメイカは沖合で引き続き好調。カツオが房総・静岡沖に接岸し始め、トップシーズン前の期待が高まる。マダイは夏の水温上昇期に入り活性がやや落ちるが、深場狙いで型物が出る。猛暑の時期は早朝の時合いを重視し、水分補給と熱中症対策を万全に。"),
    8: ("8月：カツオ最盛期・タチウオドラゴン揃う",
        "盛夏の釣りは早起きが鍵。タチウオは最盛期継続で大型のドラゴンサイズが多い。カツオが房総・相模湾沖で最盛期を迎えカツオ船が大にぎわい、10〜15kgのメジ（キハダマグロ若魚）が混じることもある。シロギスは引き続き数釣りシーズン。スルメイカは沖合で安定。マダコも数が揃う時期。シマアジ・カンパチなど夏の高級魚も狙い目。イナダ（ブリの若魚）が各地で回遊しお手軽青物釣りとして人気。アジも夏場にコンスタントに釣れる。水温が高く魚の活性は高いが、炎天下の釣りは体力消耗が激しいため、日よけ・こまめな水分補給が必須。"),
    9: ("9月：秋の荒食い突入・アジ・タチウオ絶好調",
        "水温がピークを迎え青物の活性が最高潮。カツオは房総・静岡沖で引き続き好調。タチウオは秋口でドラゴンサイズが多く、数も型も年間ベストの時期。アジは秋の荒食いで数釣りが絶好調で、束釣りも珍しくない。マダイも秋の乗っ込みに向けて活性が上がり始め型狙いに期待。シロギスはシーズン後半で数は落ち着くが良型が出る。イナダ・ワラサが各地で回遊し青物ファンを楽しませる。カンパチ・シマアジも9月いっぱいが狙い目。カワハギが浅場に上がり始め、各港でシーズン開幕の声が上がり始める。秋の行楽シーズンとも重なり、船釣り人気が高まる時期。"),
    10: ("10月：カワハギ・タチウオ大物シーズン",
        "秋の行楽シーズン、船釣りも多彩。カワハギが浅場で旬ピークを迎え、肝パン（肝臓が肥大した）の良型が揃う。刺身・肝和えとして食味も抜群。タチウオは秋の大型シーズンで指4〜5本超えの大物狙いが楽しい。アジは秋の荒食いで絶好調が続き、束釣りも期待できる。マダイは秋の乗っ込みで型が大きくなり3〜5kgも狙える。ワラサ・イナダが引き続き回遊。ヤリイカが相模湾・千葉でシーズン開幕し、型狙いで人気が高い。フグも秋のシーズン入りで活性が高くなってくる。マハタ・クロムツなど深場根魚の実績も上がり、船が多種多様な魚を狙える最も充実した時期の一つ。"),
    11: ("11月：カワハギ最旬・ヤリイカ本格化",
        "秋深まり型狙いに最適な季節。カワハギは肝が最も肥える11月が一番の旬で、久里浜・剣崎・小柴エリアで良型の数釣りが楽しめる。ヤリイカが本格シーズン突入し、相模湾・千葉では大型の良型が揃う。アジは秋〜冬にかけて引き続き安定。タチウオはシーズン終盤だが良型は出る。マダイは深場中心で型狙い。フグが関東全域で本格シーズン入りし、ショウサイフグ・アカメフグが活発に動く。クロムツ・アカムツなど冬の高級深場魚が好調になり始める。ヒラメも浅場に上がり始めシーズン開幕。カサゴ・メバルも活性が上がりシーズン入り。水温低下とともに各魚種が荒食いに入り、型物が揃いやすい。"),
    12: ("12月：年末の大物狙い・ヤリイカ・ヒラメ",
        "冬本番、大物狙いの季節。ヤリイカは産卵前の荒食いで大型が多く、束釣りも期待できる数釣りシーズン。相模湾・千葉で型も数も揃う。ヒラメが冬の荒食いシーズンで型が大きく3kg超えも珍しくなく、大原・鴨川への遠征釣りとして人気が高い。アジは年末も好調で、脂のりの良い良型が揃い忘年会の食材として人気。フグは荒食いで厚みのある良型が揃い、食味も最高峰。クロムツ・アカムツの深場釣りが最盛期を迎え、高級魚狙いの釣り人で賑わう。カサゴ・メバルは寒さに強く安定した釣果。水温低下で食い渋りも多いが、口を使ったときの型が大きい。年末最後の釣行先としてヒラメ・ヤリイカが特に人気。"),
}

def build_calendar_page(crawled_at=""):
    now = datetime.now(JST).replace(tzinfo=None)
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
        rows += f"<tr><td class='fish-name'><a href='fish/{fish_slug(fish)}.html'><img src='assets/fish/{fish_img_slug(fish)}/{fish_img_slug(fish)}_emoji.webp' alt='{fish}' class='cal-emoji' width='20' height='20' loading='lazy' decoding='async' onerror='this.style.display=\"none\"'>{fish}</a></td>{cells}</tr>"
    cal_extra_css = """.cal-wrap{overflow-x:auto;-webkit-overflow-scrolling:touch;margin-bottom:16px}
.cal-wrap table{font-size:12px;min-width:600px}
.cal-wrap th{text-align:center;min-width:34px;font-size:11px;padding:6px 4px}
.cal-wrap th.cur-month{background:var(--cta);color:#fff}
.cal-wrap td{text-align:center;padding:5px 3px;border-bottom:1px solid var(--border)}
.cal-wrap td.fish-name{text-align:left;font-weight:700;min-width:80px;padding-left:4px;white-space:nowrap}
.cal-wrap td.fish-name a{color:var(--text);display:flex;align-items:center;gap:4px}
.cal-wrap td.fish-name a:hover{color:var(--cta)}
.cal-emoji{width:20px;height:20px;object-fit:contain;flex-shrink:0}
.cal-wrap td.peak-count{background:#fde8d4;color:#b84500;font-weight:700}
.cal-wrap td.peak-size{background:#ece5fd;color:#6d28d9;font-weight:700}
.cal-wrap td.mid{background:#dfe8f4;color:#2c6ea8}
.cal-wrap td.low{color:var(--muted)}
.cal-wrap td.cur-month{outline:2px solid var(--cta);outline-offset:-2px}
.legend{display:flex;gap:12px;flex-wrap:wrap;margin:12px 0 16px;font-size:11px;color:var(--sub)}
.leg{display:flex;align-items:center;gap:5px}
.leg-dot{width:12px;height:12px;border-radius:2px}"""
    # 月別コメントHTML生成（今月ハイライト → 他月順）
    _mc_cur_title, _mc_cur_body = _CALENDAR_MONTHLY_COMMENTS[current_month]
    _mc_cur_html = f"""<div class="mc-card mc-cur">
  <div class="mc-head">{_mc_cur_title}</div>
  <p class="mc-body">{_mc_cur_body}</p>
</div>"""
    _mc_others = ""
    for m in list(range(current_month + 1, 13)) + list(range(1, current_month)):
        _t, _b = _CALENDAR_MONTHLY_COMMENTS[m]
        _mc_others += f'<div class="mc-card"><div class="mc-head">{_t}</div><p class="mc-body">{_b}</p></div>'
    cal_extra_css2 = """\
.mc-cur{border-left:4px solid var(--cta);background:var(--card)}
.mc-card{border:1px solid var(--border);border-radius:var(--r);padding:14px 16px;margin-bottom:12px;background:var(--bg)}
.mc-head{font-size:14px;font-weight:700;color:var(--accent);margin-bottom:8px}
.mc-body{font-size:13px;line-height:1.8;color:var(--text);margin:0}"""
    return f"""<!DOCTYPE html>
<html lang="ja"><head>
  <meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
  <title>関東船釣り 旬カレンダー | 月別釣りものガイド | 船釣り予想</title>
  <meta name="description" content="関東エリアの船釣り旬カレンダー。アジ・マダイ・タチウオ・ヒラメなど50魚種以上の月別シーズン表。数釣り・型釣りのピーク月が一目でわかる。">
  <link rel="canonical" href="{SITE_URL}/calendar.html">
  {GA_TAG}
  {ADSENSE_TAG}
  <link rel="stylesheet" href="style.css">
  <style>
{cal_extra_css}
{cal_extra_css2}</style>
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
  <h2 class="st" style="margin-top:24px">月別 釣りもの解説 <span class="tag free">無料</span></h2>
  {_mc_cur_html}
  {_mc_others}
</div>
{DATA_NOTE_HTML}
{_v2_footer(crawled_at)}
{_v2_bottom_nav('cal')}
</body></html>"""

def build_premium_plan_page():
    """T13: docs/premium/plan.html を生成する（静的・データ依存なし）

    mockup-plan.html を踏襲しつつ、決定③（90_決定ログ.md 2026/05/06）により
    以下8項目を除外:
      - 7日間無料トライアル（クレカ登録必須）バッジ・記述
      - スポット「月3回まで」表記
      - 友達紹介プログラムセクション全体
      - ウォーターマーク・閲覧上限200ページ/日（規約抜粋内）
      - 「人気No.1」バッジ（CSS は残すが HTML class は削除）
      - 機能比較表の「30日詳細履歴」「釣行プラン提案機能」「マイページ・通知」行
      - 月額・スポットCTA → disabled ボタン「準備中」
      - 無料プランCTA のみ有効（href="../index.html"）
    """
    plan_css = """:root{--bg:#f5f7fa;--card:#fff;--border:#d0d8e0;--text:#1a2332;--sub:#5a6a7a;--muted:#8a96a4;--accent:#0d2b4a;--cta:#e85d04;--pos:#1a9d56;--neg:#d43333;--prem:#7c3aed;--prem2:#6d28d9;--hdr:#0d2b4a;--nav:#f0f3f7;--r:10px;--mx:900px}
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
body{font-family:system-ui,-apple-system,"Hiragino Sans",sans-serif;background:var(--bg);color:var(--text);line-height:1.6;padding-bottom:60px}
a{color:var(--prem);text-decoration:none}a:hover{text-decoration:underline}
.c{max-width:var(--mx);margin:0 auto;padding:0 14px}
.st{font-size:15px;font-weight:700;color:var(--prem);padding:18px 0 8px;border-bottom:2px solid var(--prem);margin-bottom:12px}
.plan-hero{background:linear-gradient(135deg,#7c3aed,#4c1d95);color:#fff;padding:24px 14px;text-align:center}
.plan-hero h2{font-size:22px;font-weight:800}
.plan-hero .ph-sub{font-size:12px;color:rgba(255,255,255,.7);margin-top:4px}
.bread{font-size:11px;color:var(--muted);padding:10px 0}.bread a{color:var(--sub)}
.plans{display:grid;grid-template-columns:1fr;gap:12px;margin-bottom:16px}
@media(min-width:600px){.plans{grid-template-columns:repeat(3,1fr)}}
.plan{background:var(--card);border:2px solid var(--border);border-radius:var(--r);padding:20px;text-align:center;position:relative}
.plan.popular{border-color:var(--prem);background:linear-gradient(180deg,#faf7ff,#fff)}
.plan.popular::before{content:"人気No.1";position:absolute;top:-10px;left:50%;transform:translateX(-50%);background:var(--prem);color:#fff;font-size:10px;padding:3px 14px;border-radius:10px;font-weight:700}
.plan h3{font-size:15px;color:var(--accent);font-weight:700}
.plan-sub{font-size:10px;color:var(--muted);margin-top:2px}
.plan .price{font-size:36px;font-weight:800;color:var(--cta);line-height:1;margin:10px 0 4px}
.plan .price small{font-size:13px;font-weight:400;color:var(--sub)}
.plan ul{text-align:left;font-size:11px;color:var(--sub);list-style:none;margin:10px 0}
.plan ul li{padding:3px 0;padding-left:16px;position:relative}
.plan ul li::before{content:"✓";position:absolute;left:0;color:var(--pos);font-weight:700}
.plan ul li.no::before{content:"✗";color:var(--neg)}
.plan ul li.no{color:var(--muted)}
.plan .plan-cta{display:block;padding:12px;background:var(--prem);color:#fff;border-radius:22px;font-weight:700;font-size:13px;margin-top:12px;text-decoration:none}
.plan.popular .plan-cta{background:var(--cta)}
.plan .plan-cta:hover{opacity:.85;text-decoration:none}
.plan-cta-disabled{background:var(--muted);color:#fff;cursor:not-allowed;opacity:.6;border:none;width:100%;padding:12px;border-radius:22px;font-weight:700;font-size:13px;margin-top:12px}
.compare{background:var(--card);border:1px solid var(--border);border-radius:var(--r);padding:14px;margin-bottom:16px;overflow-x:auto}
.compare h3{font-size:13px;font-weight:700;color:var(--accent);margin-bottom:10px}
.compare table{width:100%;border-collapse:collapse;font-size:11px}
.compare th,.compare td{padding:8px 6px;border-bottom:1px solid var(--bg);text-align:center}
.compare th:first-child,.compare td:first-child{text-align:left;color:var(--sub);font-weight:600}
.compare th{font-size:10px;color:var(--accent);font-weight:700;background:var(--bg)}
.compare td.yes{color:var(--pos);font-weight:700}
.compare td.no{color:var(--muted)}
.value{background:linear-gradient(135deg,#fef6ee,#fed7aa);border:1px solid #fb923c;border-radius:var(--r);padding:16px;margin-bottom:16px}
.value h3{font-size:13px;color:var(--cta);margin-bottom:8px;text-align:center}
.value-row{display:flex;justify-content:space-between;align-items:center;padding:6px 0;font-size:12px;border-bottom:1px dashed #fb923c}
.value-row:last-child{border-bottom:none}
.value-row .vl{color:var(--text);font-weight:600}
.value-row .vv{color:var(--cta);font-weight:800}
.payment{background:var(--card);border:1px solid var(--border);border-radius:var(--r);padding:14px;margin-bottom:16px}
.payment h3{font-size:13px;font-weight:700;color:var(--accent);margin-bottom:8px}
.payment .pay-list{display:flex;gap:8px;flex-wrap:wrap}
.payment .pay-item{font-size:11px;padding:6px 12px;background:var(--bg);border-radius:6px;color:var(--sub);font-weight:600}
:root{--warn-bg:#fef9c3;--warn-border:#eab308;--warn-text:#a16207}
.payment-warn{background:var(--warn-bg);border-color:var(--warn-border)}
.payment-warn h3{color:var(--warn-text)}"""

    html = f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>料金プラン — 船釣り予想</title>
<meta name="description" content="船釣り予想の料金プラン。月額500円・スポット100円。機能比較表あり。">
<link rel="stylesheet" href="../style.css">
<style>
{plan_css}
</style>
</head>
<body>

{_v2_header_nav('prem')}

<div class="plan-hero">
<h2>プラン比較</h2>
<div class="ph-sub">あなたに合ったプランを選べます</div>
</div>

<div class="c">
<div class="bread"><a href="../index.html">トップ</a> &gt; <a href="../index.html">有料プラン</a> &gt; プラン比較</div>

<!-- 価値訴求 -->
<div class="value">
<h3>月額500円の価値</h3>
<div class="value-row"><span class="vl">仕掛け1セット（道糸・ハリス・オモリ）</span><span class="vv">約500〜1,000円</span></div>
<div class="value-row"><span class="vl">船宿1回の乗船料</span><span class="vv">約8,000〜15,000円</span></div>
<div class="value-row"><span class="vl">釣り雑誌1冊</span><span class="vv">約800円</span></div>
<div class="value-row"><span class="vl"><strong>船釣り予想 1ヶ月</strong></span><span class="vv"><strong>¥500</strong></span></div>
</div>

<!-- 3プラン -->
<h2 class="st">プラン一覧</h2>
<div class="plans">

<div class="plan">
<h3>無料プラン</h3>
<div class="plan-sub">事実情報のみ</div>
<div class="price">¥0</div>
<ul>
<li>今日の釣果（全魚種）</li>
<li>直近7日の推移グラフ</li>
<li>船宿◎○△ ランキング</li>
<li>エリア・魚種詳細</li>
<li>答え合わせ（1件/日）</li>
<li class="no">明日以降の予測</li>
<li class="no">因果分析コメント</li>
<li class="no">最適仕掛け推奨</li>
</ul>
<a class="plan-cta" href="../index.html">無料で使う</a>
</div>

<div class="plan">
<h3>月額プラン</h3>
<div class="plan-sub">フル機能</div>
<div class="price">¥500<small>/月</small></div>
<ul>
<li>無料プランの全機能</li>
<li>明日〜4週間後の予測</li>
<li>信頼度★5段階評価</li>
<li>因果分析コメント</li>
<li>最適ポイント・仕掛け推奨</li>
<li>欠航リスク予報</li>
</ul>
<button class="plan-cta plan-cta-disabled" disabled>準備中</button>
</div>

<div class="plan">
<h3>スポット</h3>
<div class="plan-sub">1日単位で購入</div>
<div class="price">¥100<small>/日</small></div>
<ul>
<li>指定日の予測のみ</li>
<li>選んだ魚種の予測</li>
<li>釣行前日だけ買える</li>
<li class="no">長期予測</li>
<li class="no">仕掛け推奨</li>
<li class="no">お気に入り通知</li>
</ul>
<button class="plan-cta plan-cta-disabled" disabled>準備中</button>
</div>

</div>

<!-- 機能比較表 -->
<div class="compare">
<h3>機能比較</h3>
<table>
<thead><tr><th>機能</th><th>無料</th><th>月額¥500</th><th>スポット¥100</th></tr></thead>
<tbody>
<tr><td>今日の釣果</td><td class="yes">○</td><td class="yes">○</td><td class="yes">○</td></tr>
<tr><td>直近7日グラフ</td><td class="yes">○</td><td class="yes">○</td><td class="yes">○</td></tr>
<tr><td>船宿◎○△</td><td class="yes">○</td><td class="yes">○</td><td class="yes">○</td></tr>
<tr><td>答え合わせ（1件/日）</td><td class="yes">○</td><td class="yes">○</td><td class="yes">○</td></tr>
<tr><td>明日の予測</td><td class="no">—</td><td class="yes">○</td><td class="yes">○</td></tr>
<tr><td>1週間予測</td><td class="no">—</td><td class="yes">○</td><td class="no">—</td></tr>
<tr><td>4週間予測</td><td class="no">—</td><td class="yes">○</td><td class="no">—</td></tr>
<tr><td>因果分析コメント</td><td class="no">—</td><td class="yes">○</td><td class="yes">○</td></tr>
<tr><td>最適ポイント推奨</td><td class="no">—</td><td class="yes">○</td><td class="yes">○</td></tr>
<tr><td>仕掛け推奨</td><td class="no">—</td><td class="yes">○</td><td class="no">—</td></tr>
<tr><td>信頼度★評価</td><td class="no">—</td><td class="yes">○</td><td class="yes">○</td></tr>
<tr><td>欠航リスク予報</td><td class="no">—</td><td class="yes">○</td><td class="no">—</td></tr>
</tbody>
</table>
</div>

<!-- 支払い方法 -->
<div class="payment">
<h3>お支払い方法</h3>
<div class="pay-list">
<div class="pay-item">クレジットカード</div>
<div class="pay-item">デビットカード</div>
<div class="pay-item">Apple Pay</div>
<div class="pay-item">Google Pay</div>
</div>
<div style="font-size:10px;color:var(--muted);margin-top:8px">※ 決済はStripe社が安全に処理します。カード情報は当サイトに保存されません。</div>
</div>

<!-- ご利用規約（抜粋） -->
<div class="payment" style="background:#fef9c3;border-color:#eab308">
<h3 style="color:#a16207">ご利用規約（抜粋）</h3>
<div style="font-size:11px;color:var(--sub);line-height:1.7">
<strong>・スクレイピング・自動取得の禁止</strong>: 本サイトの予測データ・釣果データの機械的な取得・転載を禁止します。違反した場合は即時アカウント停止・法的措置を取る場合があります。<br>
<strong>・API非公開</strong>: 公式APIの提供はありません。プログラムによる大量アクセスを検知した場合、IPブロック等の対応を行います。<br>
<strong>・予測の免責</strong>: 予測はあくまで参考情報です。釣果を保証するものではありません。的中率と答え合わせは全公開しています。
</div>
<div style="text-align:center;margin-top:8px"><a href="../pages/terms.html" style="font-size:11px;color:var(--prem);font-weight:700">利用規約 全文を見る →</a></div>
</div>

</div>

{_v2_footer()}
{_v2_bottom_nav('prem')}
</body></html>"""

    out_dir = os.path.join(WEB_DIR, "premium")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "plan.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"premium/plan.html → {out_path}")


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

# ship_trip_slot_map.json から trip_no フォールバックマップをロード（モジュール起動時1回）
_stsm_path = os.path.join(os.path.dirname(__file__), "normalize", "ship_trip_slot_map.json")
try:
    with open(_stsm_path, encoding="utf-8") as _f:
        _raw_stsm = json.load(_f)
    # "_comment" キーを除外し、trip_no キーを str で統一
    SHIP_TRIP_SLOT_MAP: dict[str, dict[str, str]] = {
        ship: {str(k): v for k, v in trips.items()}
        for ship, trips in _raw_stsm.items()
        if not ship.startswith("_")
    }
except FileNotFoundError:
    SHIP_TRIP_SLOT_MAP = {}

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
    "太幸丸":       "コマセ五目",
}

# 船宿別デフォルトポイント（point_raw・kanso_rawで地名が取れない場合のフォールバック）
# 地元の単一ポイント運航が明らかな船宿のみ登録
SHIP_DEFAULT_POINT = {
    "ちがさき丸": "茅ヶ崎沖",
    "平安丸":     "小田原沖",
}

# 船宿別便種ルール: kanso_raw 先頭がパターンに前方一致 → tsuri_mono を強制上書き
# SHIP_GOMOKU_RULES より優先的に適用される（複数便種を持つ船宿専用）
SHIP_TRIP_RULES = {
    "平安丸": [
        ("根魚",     "キンメダイ"),   # 根魚船・根魚リレー船 → キンメダイ
        ("LT五目",  "イサキ"),
    ],
    "村井丸": [
        ("LTタイ五目", "クロダイ"),
        ("タイ五目船",  "クロダイ"),
        ("タイ仕立船",  "クロダイ"),
        ("タイ船",      "クロダイ"),
        ("マダイ船",    "クロダイ"),
        ("LTタイ船",    "クロダイ"),
        ("LT五目",      "LT五目"),
        ("ライト五目",  "LT五目"),
        ("落とし込み",  "落とし込み"),
        ("落し込み",    "落とし込み"),
        ("アマダイ",    "アマダイ"),
        ("カワハギ",    "カワハギ"),
    ],
    "鶴丸": [
        ("朝シロアマダイ", "シロアマダイ"),
        ("朝アカアマダイ", "アカアマダイ"),
        ("朝紅白アマダイ", "アカアマダイ"),  # 紅白＝アカ・シロ → 冒頭アカ
        ("朝アマダイ",     "アマダイ"),
    ],
    "たいぞう丸": [
        ("シロアマダイ五目", "シロアマダイ"),
        ("アマダイ五目",     "アマダイ"),
        ("アマダイ船",       "アマダイ"),
        ("アマダイ",         "アマダイ"),
    ],
    "大盛丸": [
        ("ホウボウ", "ホウボウ"),  # ホウボウ五目船
        ("イシナギ", "ヒラメ"),
        ("アマダイ", "アマダイ"),  # アマダイ船
        ("五目",     "五目"),      # 五目船（汎用）
    ],
    "大貫丸": [
        ("アマダイ", "アマダイ"),  # アマダイ船100件のマダイ誤分類修正
        ("ムラソイ船", "キンメダイ"),  # ムラソイ船=根魚五目
    ],
    "恵漁丸": [
        ("シロアマダイ", "シロアマダイ"),
        ("アマダイ",     "アマダイ"),
    ],
    "海桜丸": [
        ("五目アマダイ", "アマダイ"),
        ("五目&アマダイ", "アマダイ"),
        ("アマダイ",     "アマダイ"),
    ],
    "第八幸松丸": [
        ("午前便アマダイ五目", "アマダイ"),
        ("午前便アマダイ",     "アマダイ"),
    ],
    "仁徳丸": [
        ("スロージギング", "スロージギング"),
        ("浅場根魚五目",   "キンメダイ"),
        ("アラ五目",       "アラ"),
        ("アマダイ五目",   "アマダイ"),
        ("アマダイ",       "アマダイ"),
    ],
    "共栄丸": [
        ("午後アマダイ五目", "アマダイ"),
        ("午前アマダイ五目", "アマダイ"),
        ("アマダイ五目",     "アマダイ"),
    ],
    "秀丸": [
        ("早夜ムラサキイカ", "アカイカ"),
        ("深夜ムラサキイカ", "アカイカ"),
        ("ムラサキイカ",     "アカイカ"),
    ],
    "庄治郎丸": [
        ("ライトルアー", "ライトルアー"),
    ],
    "不動丸": [
        ("SLJ", "SLJ"),
    ],
    "伊達丸": [
        ("アマラバ", "アマラバ"),
    ],
    "吉野屋": [
        ("アナゴ船", "アナゴ"),
    ],
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
    # 船宿別便種ルール（SHIP_GOMOKU_RULES より優先）
    if ship in SHIP_TRIP_RULES:
        for pattern, result in SHIP_TRIP_RULES[ship]:
            if raw.startswith(pattern):
                return result
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
    #    ※ アマダイ系を先にチェック（"マダイ" in "アマダイ" = True の誤ヒット防止）
    _amadai_priority = ("アカアマダイ", "シロアマダイ", "アマダイ")
    for _tm in _amadai_priority:
        if _tm in TSURI_MONO_MAP:
            if any(p in raw for p in TSURI_MONO_MAP[_tm]):
                return _tm
    for tsuri_mono, patterns in TSURI_MONO_MAP.items():
        if tsuri_mono in _amadai_priority:
            continue
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
    """水色を正規化カテゴリに変換して返す。
    優先順位: 長いパターン → 短いパターン の順で先頭一致。
    """
    # (パターン, 正規化後の値) — 長いものを先に
    _MAP = [
        ("青潮",    "青潮"),
        ("赤潮",    "赤潮"),
        ("澄み気味", "やや澄み"),
        ("やや澄",  "やや澄み"),
        ("澄む",    "澄み"),
        ("澄み",    "澄み"),
        ("澄んで",  "澄み"),
        ("濁り気味", "やや濁り"),
        ("やや濁",  "やや濁り"),
        ("薄濁",    "薄濁り"),
        ("濁る",    "濁り"),
        ("濁り",    "濁り"),
        ("普通",    "普通"),
    ]
    for pat, norm in _MAP:
        if pat in text:
            return norm
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


def _extract_time_slot(fish_raw: str, kanso_raw: str = "", trip_no: int = 1, ship: str = "") -> str:
    """fish_raw/kanso_raw/trip_no から時間帯を抽出。例: '午前ライトアジ'→'午前', '夜イカ'→'夜'
    ship 引数を指定すると、fish_raw/kanso_raw で確定できない場合に
    normalize/ship_trip_slot_map.json の trip_no→slot フォールバックを適用する。
    """
    combined = (fish_raw or "") + " " + (kanso_raw or "")
    if not combined.strip():
        # combined が空でも ship フォールバックは試みる
        mapped = SHIP_TRIP_SLOT_MAP.get(ship, {}).get(str(trip_no), "")
        return mapped
    # 午前・午後 併記（例: 忠彦丸「午前・午後ライトアジ乗合船」）→ 時間帯不定
    if "午前" in combined and "午後" in combined:
        return ""
    # 優先順位順にチェック（長いパターンを先に）
    for pattern, slot in [
        ("ショートショート", "ショート"),
        ("午前半日",   "午前"),
        ("午後半日",   "午後"),
        ("ナイト",     "夜"),
        ("デイゲーム", "昼"),
        ("早朝",       "朝"),
        ("深夜",       "夜"),
        ("夜釣",       "夜"),
        ("夜間",       "夜"),
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
        if pattern in combined:
            return slot
    # イカ系でtrip_no>=2かつtime_slot未判定の場合は夜便と推定
    _ika_words = ("ムギイカ", "マルイカ", "ヤリイカ", "スルメイカ", "コウイカ", "スミイカ")
    if trip_no >= 2 and any(w in combined for w in _ika_words):
        return "夜"
    # ship_trip_slot_map フォールバック: キーワードで確定できなかった場合のみ適用
    if ship:
        mapped = SHIP_TRIP_SLOT_MAP.get(ship, {}).get(str(trip_no), "")
        if mapped:
            return mapped
    return ""


def _extract_tackle(tokki):
    """特記欄から仕掛けを抽出"""
    for word in ["ルアー", "テンヤ", "コマセ", "ビシ", "胴付き", "泳がせ", "エサ"]:
        if word in tokki:
            return word
    return ""


def _split_point_places_depth(point_raw, comment=""):
    """ポイント文字列から場所リスト（最大3）と水深 {min, max} を分離して返す。"""
    point_raw = point_raw.translate(Z2H).replace('\uff5e', '~').replace('\u301c', '~')
    depth = {}
    depth_patterns = [
        # 「水深/タナ/棚 数字[~数字] m [前後/付近]」を一括除去
        r'(?:水深|タナ|棚)\s*(\d+(?:\.\d+)?)(?:[~](\d+(?:\.\d+)?))?\s*m?\s*(?:前後|付近)?',
        r'(\d+(?:\.\d+)?)[~](\d+(?:\.\d+)?)\s*m',
        r'(?:水深|タナ|棚)\s*(\d+(?:\.\d+)?)\s*m?\s*(?:前後|付近)?',
        r'(\d+(?:\.\d+)?)\s*m(?:\s|$|・|→)',
    ]
    for pat in depth_patterns:
        dm = re.search(pat, point_raw, re.I)
        if dm:
            lo = float(dm.group(1))
            hi = float(dm.group(2)) if dm.lastindex >= 2 and dm.group(2) else lo
            depth = {"min": lo, "max": hi}
            point_raw = (point_raw[:dm.start()] + point_raw[dm.end():]).strip("・→/~ ")
            break
    places = [p.strip() for p in re.split(r'[・→/]', point_raw) if p.strip()]
    if len(places) == 1 and '~' in places[0]:
        sub = [p.strip() for p in places[0].split('~') if p.strip()]
        if all(not re.match(r'^\d+\.?\d*$', p) for p in sub):
            places = sub
    # 各place名から残余の水深表現・前後・付近・他・末尾数字mを除去し、数字のみ項目を除外
    cleaned = []
    for p in places:
        p = re.sub(r'(?:水深|タナ|棚)\s*[\d.]+(?:[~][\d.]+)?\s*m?\s*(?:前後|付近)?', '', p, flags=re.I).strip()
        p = re.sub(r'\s*(?:前後|付近|他)\s*$', '', p).strip('・→/~ ')
        p = re.sub(r'\s*\d+(?:[~]\d+)?\s*m$', '', p, flags=re.I).strip()
        if re.match(r'^[\d.~m]+$', p, re.I):
            continue
        if p:
            cleaned.append(p)
    places = cleaned
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
    "n_points_visited",
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

    # 鮮度ガード: catches_raw.json が stale だと CSV を全再生成すると
    # save_daily_csv() が日次で追記した records が wipe される（過去に発生）。
    # raw の最新日付が today-7日 より古ければ refuse して abort。
    # 環境変数 FORCE_EXPORT=1 で override 可能（手動メンテナンス時）。
    if os.environ.get("FORCE_EXPORT") != "1":
        try:
            _raw_dates = sorted(
                r["date"] for r in records
                if isinstance(r, dict) and r.get("date")
            )
            if _raw_dates:
                _raw_latest = _raw_dates[-1]
                _today = datetime.now(JST).replace(tzinfo=None)
                _cutoff = (_today - timedelta(days=7)).strftime("%Y/%m/%d")
                if _raw_latest < _cutoff:
                    print(
                        f"\n❌ export_csv_from_raw: ABORT\n"
                        f"   catches_raw.json の最新日付 {_raw_latest} が cutoff {_cutoff} より古い。\n"
                        f"   このまま CSV 再生成すると save_daily_csv() の追記分が wipe される。\n"
                        f"   override したい場合: FORCE_EXPORT=1 python crawler.py --export-csv\n"
                    )
                    return -1
        except Exception as _e:
            print(f"WARN: 鮮度チェック skip ({_e})")

    # ships.json の exclude/boat_only フラグを読み込んで除外リストを構築
    _ships_json = os.path.join(os.path.dirname(__file__), "crawl", "ships.json")
    _exclude_ships = set()
    if os.path.exists(_ships_json):
        with open(_ships_json, encoding="utf-8") as _sf:
            for _s in json.load(_sf):
                if _s.get("exclude") or _s.get("boat_only"):
                    _exclude_ships.add(_s["name"])
    if _exclude_ships:
        before = len(records)
        records = [r for r in records if r.get("ship") not in _exclude_ships]
        print(f"export_csv_from_raw: exclude {before - len(records)}件 ({', '.join(sorted(_exclude_ships))})")

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
                    "n_points_visited": "",
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
            # 大盛丸専用: kanso先頭から正確な釣り物に再分類
            # fishing-v.jp が「タイ五目」に誤分類しているため kanso で上書き
            if r.get("ship") == "大盛丸" and tsuri_norm == "タイ五目":
                _khead = comment.split("。")[0] if comment else ""
                if re.search(r'ハナダイ', _khead):
                    tsuri_raw, tsuri_norm = "ハナダイ", "ハナダイ"
                elif re.search(r'泳がせ五目', _khead):
                    tsuri_raw, tsuri_norm = "泳がせ五目", "泳がせ五目"
                else:
                    tsuri_raw, tsuri_norm = "", ""
            # 幸栄丸専用: フグ便でfish_rawがカワハギの場合はカワハギに再分類
            if r.get("ship") == "幸栄丸" and tsuri_norm == "フグ" and r.get("fish_raw", "").strip() == "カワハギ":
                tsuri_raw, tsuri_norm = "カワハギ", "カワハギ"
            main_sub   = _classify_main_sub(r.get("fish_raw", ""), tsuri_norm)

            _parts = comment.split("。")
            kanso_short = "。".join(_parts[:2]) + ("。" if len(_parts) > 1 else "")

            wt          = _extract_water_temp_range(r.get("suion_raw") or r.get("color_raw") or comment)
            water_color = _extract_water_color(r.get("suishoku_raw") or r.get("color_raw") or comment)
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
            # 船宿別デフォルトポイント（地元単一運航船）
            if (not places or not places[0]) and r.get("ship") in SHIP_DEFAULT_POINT:
                places = [SHIP_DEFAULT_POINT[r["ship"]]] + list(places[1:] if places else [])

            cr = extract_count(r.get("count_raw") or "")
            sc = extract_size_cm(r.get("size_raw") or "")
            wk = extract_weight_kg(r.get("weight_raw") or "") or \
                 extract_weight_kg(r.get("tokki_raw") or "")
            # count_raw が空の場合、tokki_raw / weight_raw / size_raw に
            # 「数匹」「数尾」等があれば 0〜2 匹として拾う
            if not cr:
                _sub = " ".join([
                    r.get("tokki_raw") or "",
                    r.get("weight_raw") or "",
                    r.get("size_raw") or "",
                ])
                if re.search(r'数[匹尾本頭]', _sub):
                    cr = {"min": 0, "max": 2}
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
                "time_slot":      _extract_time_slot(r.get("fish_raw", ""), r.get("kanso_raw", ""), int(r.get("trip_no") or 1), r.get("ship", "")),
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
                "n_points_visited": max(1, sum(1 for _p in places if _p and _p.strip())),
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
            time_slot  = _extract_time_slot(fish_raw, c.get("kanso_raw", ""), int(c.get("trip_no") or 1), c.get("ship", ""))
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
                "n_points_visited": max(1, sum(1 for _p in [pp1, pp2] if _p and _p.strip())),
                "depth_min":      d_min,
                "depth_max":      d_max,
                "water_temp_min": _extract_water_temp_range(c.get("suion_raw") or c.get("color_raw") or "").get("min", ""),
                "water_temp_max": _extract_water_temp_range(c.get("suion_raw") or c.get("color_raw") or "").get("max", ""),
                "water_color":    _extract_water_color(c.get("suishoku_raw") or c.get("color_raw") or ""),
                "wind_direction": "",
                "wind_speed":     "",
                "tide_info":      "",
                "wave_info":      "",
                "weather":        "",
                "by_catch":       "",
                "cancel_reason":  "",
                "cancel_type":    "",
                "kanso_raw":      "",
                "suion_raw":      c.get("suion_raw") or "",
                "suishoku_raw":   c.get("suishoku_raw") or "",
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
# 船宿個別ページ生成 (T8: docs/ship/*.html)
# ============================================================

# mockup-ship.html から流用したCSS（V2配色・濃紺ヘッダ + オレンジCTA）
_SHIP_PAGE_CSS = """
:root{--bg:#f5f7fa;--card:#fff;--border:#d0d8e0;--text:#1a2332;--sub:#5a6a7a;--muted:#8a96a4;--accent:#0d2b4a;--accent2:#163d5c;--cta:#e85d04;--cta2:#d04e00;--pos:#1a9d56;--neg:#d43333;--warn:#d4a017;--prem:#7c3aed;--hdr:#0d2b4a;--nav:#f0f3f7;--r:10px;--mx:900px}
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
body{font-family:system-ui,-apple-system,"Hiragino Sans",sans-serif;background:var(--bg);color:var(--text);line-height:1.6;padding-bottom:60px}
a{color:var(--cta);text-decoration:none}a:hover{text-decoration:underline}
.c{max-width:var(--mx);margin:0 auto;padding:0 14px}
header{background:var(--hdr);color:#fff;padding:12px 20px;border-bottom:3px solid var(--cta)}
header .inner{max-width:var(--mx);margin:0 auto;display:flex;justify-content:space-between;align-items:center}
header h1{font-size:19px;font-weight:700}header h1 a{color:#fff}header h1 span{color:var(--cta)}
nav.gnav{background:var(--nav);padding:7px 20px;display:flex;gap:6px;flex-wrap:wrap;justify-content:center;border-bottom:1px solid var(--border)}
nav.gnav a{color:var(--sub);font-size:12px;font-weight:600;padding:5px 12px;border-radius:16px}
nav.gnav a:hover,nav.gnav a.on{background:var(--accent);color:#fff;text-decoration:none}
nav.gnav a.prem{color:var(--prem)}
nav.gnav a.prem::before{content:"";display:inline-block;width:8px;height:8px;background:var(--prem);border-radius:50%;margin-right:4px;vertical-align:middle}
.bn a.prem{color:var(--prem)}
.st{font-size:15px;font-weight:700;color:var(--accent);padding:18px 0 8px;border-bottom:2px solid var(--accent);margin-bottom:12px}
.ship-hero{background:linear-gradient(135deg,var(--accent),var(--accent2));color:#fff;padding:20px 14px;text-align:center}
.ship-hero h2{font-size:24px;font-weight:800}
.ship-hero .sh-area{font-size:13px;color:rgba(255,255,255,.7);margin-top:2px}
.ship-hero .sh-badges{display:flex;justify-content:center;gap:6px;margin-top:10px;flex-wrap:wrap}
.ship-hero .sh-badge{font-size:10px;padding:3px 8px;background:rgba(255,255,255,.15);border-radius:10px;color:#fff}
.ship-hero .sh-overall{font-size:11px;color:rgba(255,255,255,.6);margin-top:8px}
.bread{font-size:11px;color:var(--muted);padding:10px 0}.bread a{color:var(--sub)}
.ad-slot{background:#f0f0f0;border:1px dashed #ccc;border-radius:var(--r);padding:20px;text-align:center;margin:12px 0;font-size:11px;color:#999}
.info-box{background:var(--card);border:1px solid var(--border);border-radius:var(--r);padding:14px;margin-bottom:16px;font-size:12px;color:var(--sub);line-height:1.8}
.info-box strong{color:var(--text)}
.info-box .info-row{display:flex;gap:8px;padding:4px 0;border-bottom:1px solid var(--bg)}
.info-box .info-row:last-child{border-bottom:none}
.info-box .info-label{flex:0 0 100px;color:var(--muted);font-weight:600}
.info-box .info-val{flex:1}
.fish-section{background:var(--card);border:1px solid var(--border);border-radius:var(--r);padding:14px;margin-bottom:12px}
.fish-section h3{font-size:13px;font-weight:700;color:var(--accent);margin-bottom:8px;display:flex;justify-content:space-between;align-items:center}
.fish-section h3 .h-range{color:var(--cta);font-size:15px}
.chart-bars{display:flex;align-items:flex-end;gap:3px;height:40px}
.chart-bars .cb{flex:1;background:var(--cta);border-radius:2px 2px 0 0;opacity:.7;min-width:10px}
.chart-bars .cb.weekend{opacity:.8;background:#f4a043}
.chart-bars .cb.today{opacity:1;background:var(--pos);outline:1.5px solid var(--accent);outline-offset:-1.5px}
.chart-labels{display:flex;justify-content:space-between;font-size:9px;color:var(--muted);margin-top:3px}
.chart-labels span.weekend{color:#c66a14}
.chart-labels span.today{color:var(--pos);font-weight:700;border-bottom:2px solid var(--pos);padding-bottom:1px}
.fish-meta{font-size:11px;color:var(--sub);margin-top:8px;padding-top:8px;border-top:1px solid var(--bg)}
.fish-meta strong{color:var(--accent)}
.rank-box{background:var(--card);border:1px solid var(--border);border-radius:var(--r);padding:14px;margin-bottom:16px}
.rank-box h3{font-size:13px;font-weight:700;color:var(--accent);margin-bottom:10px}
.rk{display:flex;align-items:center;padding:6px 0;border-bottom:1px solid var(--bg);gap:8px;font-size:12px}
.rk:last-child{border-bottom:none}
.rk.self{background:#fef6ee;border-radius:6px;padding:8px;border-bottom:none;margin-bottom:4px}
.rk .rk-rank{font-weight:800;color:var(--cta);flex:0 0 30px;text-align:center}
.rk .rk-name{flex:1;font-weight:700;color:var(--accent)}
.rk .rk-pct{font-weight:700;font-size:11px;padding:2px 6px;border-radius:6px;background:#e6f7ee;color:var(--pos)}
.spec-card{background:var(--card);border:1px solid var(--border);border-radius:var(--r);padding:14px;margin-bottom:12px}
.spec-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:8px;font-size:12px;color:var(--sub)}
.spec-grid .sg-item{padding:6px 0}
.spec-grid .sg-item strong{display:block;color:var(--muted);font-size:10px;font-weight:600;margin-bottom:2px}
.facility-tags{display:flex;flex-wrap:wrap;gap:6px;margin-top:6px}
.facility-tags .ft{font-size:10px;padding:3px 8px;background:var(--nav);color:var(--sub);border-radius:10px;border:1px solid var(--border)}
.season-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:10px}
.season-grid .sg{padding:10px;background:var(--bg);border-radius:8px;border-left:3px solid var(--cta)}
.season-grid .sg .sg-label{font-size:11px;color:var(--muted);font-weight:700;margin-bottom:4px}
.season-grid .sg .sg-fish{font-size:13px;color:var(--accent);font-weight:600}
.cta-grid{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:10px}
.cta-grid a{padding:10px;background:var(--cta);color:#fff;border-radius:20px;font-weight:700;font-size:13px;text-align:center;text-decoration:none}
.cta-grid a.alt{background:#fff;color:var(--accent);border:1px solid var(--accent)}
.cta-grid a:hover{background:var(--cta2)}
.cta-grid a.alt:hover{background:var(--accent);color:#fff}
.faq-list{margin-top:8px}
.faq-list details{background:var(--card);border:1px solid var(--border);border-radius:var(--r);margin-bottom:6px;padding:0}
.faq-list summary{padding:10px 14px;cursor:pointer;font-size:13px;font-weight:600;color:var(--accent);list-style:none}
.faq-list summary::-webkit-details-marker{display:none}
.faq-list summary::before{content:"Q. ";color:var(--cta);font-weight:800;margin-right:4px}
.faq-list details[open] summary{border-bottom:1px solid var(--bg)}
.faq-list .faq-a{padding:10px 14px;font-size:12px;color:var(--sub);line-height:1.7}
.faq-list .faq-a::before{content:"A. ";color:var(--pos);font-weight:800;margin-right:4px}
.contact-cta{background:var(--accent);color:#fff;border-radius:var(--r);padding:16px;text-align:center;margin-bottom:16px}
.contact-cta h3{font-size:14px;margin-bottom:8px}
.contact-cta p{font-size:12px;color:rgba(255,255,255,.7);margin-bottom:10px}
.contact-cta a{display:inline-block;padding:10px 24px;background:var(--cta);color:#fff;border-radius:20px;font-weight:700;font-size:13px;margin:4px}
footer{background:var(--hdr);color:rgba(255,255,255,.5);padding:16px;text-align:center;font-size:11px;margin-top:24px}
footer a{color:rgba(255,255,255,.7)}
.bn{position:fixed;bottom:0;left:0;right:0;background:var(--card);border-top:1px solid var(--border);display:flex;z-index:100;box-shadow:0 -2px 8px rgba(0,0,0,.05)}
.bn a{flex:1;text-align:center;padding:7px 0;font-size:9px;color:var(--muted);display:flex;flex-direction:column;align-items:center;gap:1px}
.bn a .i{font-size:18px}.bn a.on{color:var(--cta)}.bn a:hover{text-decoration:none;color:var(--cta)}
@media(min-width:769px){.bn{display:none}body{padding-bottom:0}}
""".strip()

# ship ページ固有CSS（style.css 外部化後に残すインライン部分 - 外部CSSに未収録のセレクタのみ）
_SHIP_EXTRA_CSS = """\
.ship-hero{background:linear-gradient(135deg,var(--accent),var(--accent2));color:#fff;padding:20px 14px;text-align:center}
.ship-hero h2{font-size:24px;font-weight:800}
.ship-hero .sh-area{font-size:13px;color:rgba(255,255,255,.7);margin-top:2px}
.ship-hero .sh-badges{display:flex;justify-content:center;gap:6px;margin-top:10px;flex-wrap:wrap}
.ship-hero .sh-badge{font-size:10px;padding:3px 8px;background:rgba(255,255,255,.15);border-radius:10px;color:#fff}
.ship-hero .sh-overall{font-size:11px;color:rgba(255,255,255,.6);margin-top:8px}
.info-box{background:var(--card);border:1px solid var(--border);border-radius:var(--r);padding:14px;margin-bottom:16px;font-size:12px;color:var(--sub);line-height:1.8}
.info-box strong{color:var(--text)}
.info-box .info-row{display:flex;gap:8px;padding:4px 0;border-bottom:1px solid var(--bg)}
.info-box .info-row:last-child{border-bottom:none}
.info-box .info-label{flex:0 0 100px;color:var(--muted);font-weight:600}
.info-box .info-val{flex:1}
.fish-section{background:var(--card);border:1px solid var(--border);border-radius:var(--r);padding:14px;margin-bottom:12px}
.fish-section h3{font-size:13px;font-weight:700;color:var(--accent);margin-bottom:8px;display:flex;justify-content:space-between;align-items:center}
.fish-section h3 .h-range{color:var(--cta);font-size:15px}
.chart-bars{display:flex;align-items:flex-end;gap:3px;height:40px}
.chart-bars .cb{flex:1;background:var(--cta);border-radius:2px 2px 0 0;opacity:.7;min-width:10px}
.chart-bars .cb.weekend{opacity:.8;background:#f4a043}
.chart-bars .cb.today{opacity:1;background:var(--pos);outline:1.5px solid var(--accent);outline-offset:-1.5px}
.chart-labels{display:flex;justify-content:space-between;font-size:9px;color:var(--muted);margin-top:3px}
.chart-labels span.weekend{color:#c66a14}
.chart-labels span.today{color:var(--pos);font-weight:700;border-bottom:2px solid var(--pos);padding-bottom:1px}
.fish-meta{font-size:11px;color:var(--sub);margin-top:8px;padding-top:8px;border-top:1px solid var(--bg)}
.fish-meta strong{color:var(--accent)}
.rank-box{background:var(--card);border:1px solid var(--border);border-radius:var(--r);padding:14px;margin-bottom:16px}
.rank-box h3{font-size:13px;font-weight:700;color:var(--accent);margin-bottom:10px}
.rk{display:flex;align-items:center;padding:6px 0;border-bottom:1px solid var(--bg);gap:8px;font-size:12px}
.rk:last-child{border-bottom:none}
.rk.self{background:#fef6ee;border-radius:6px;padding:8px;border-bottom:none;margin-bottom:4px}
.rk .rk-rank{font-weight:800;color:var(--cta);flex:0 0 30px;text-align:center}
.rk .rk-name{flex:1;font-weight:700;color:var(--accent)}
.rk .rk-pct{font-weight:700;font-size:11px;padding:2px 6px;border-radius:6px;background:#e6f7ee;color:var(--pos)}
.spec-card{background:var(--card);border:1px solid var(--border);border-radius:var(--r);padding:14px;margin-bottom:12px}
.spec-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:8px;font-size:12px;color:var(--sub)}
.spec-grid .sg-item{padding:6px 0}
.spec-grid .sg-item strong{display:block;color:var(--muted);font-size:10px;font-weight:600;margin-bottom:2px}
.facility-tags{display:flex;flex-wrap:wrap;gap:6px;margin-top:6px}
.facility-tags .ft{font-size:10px;padding:3px 8px;background:var(--nav);color:var(--sub);border-radius:10px;border:1px solid var(--border)}
.season-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:10px}
.season-grid .sg{padding:10px;background:var(--bg);border-radius:8px;border-left:3px solid var(--cta)}
.season-grid .sg .sg-label{font-size:11px;color:var(--muted);font-weight:700;margin-bottom:4px}
.season-grid .sg .sg-fish{font-size:13px;color:var(--accent);font-weight:600}
.cta-grid{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:10px}
.cta-grid a{padding:10px;background:var(--cta);color:#fff;border-radius:20px;font-weight:700;font-size:13px;text-align:center;text-decoration:none}
.cta-grid a.alt{background:#fff;color:var(--accent);border:1px solid var(--accent)}
.cta-grid a:hover{background:var(--cta2)}
.cta-grid a.alt:hover{background:var(--accent);color:#fff}
.contact-cta{background:var(--accent);color:#fff;border-radius:var(--r);padding:16px;text-align:center;margin-bottom:16px}
.contact-cta h3{font-size:14px;margin-bottom:8px}
.contact-cta p{font-size:12px;color:rgba(255,255,255,.7);margin-bottom:10px}
.contact-cta a{display:inline-block;padding:10px 24px;background:var(--cta);color:#fff;border-radius:20px;font-weight:700;font-size:13px;margin:4px}"""


def _ship_load_area_coords():
    """area_coords.json を読む（{area: {lat, lon}}）"""
    p = os.path.join("normalize", "area_coords.json")
    if not os.path.exists(p): return {}
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


# 料金表記サニタイザ（船宿料金は変動するため一切記載しない・自社サブスク料金「月額500円」は別フローで保持）
_PRICE_PATTERNS = [
    re.compile(r"\d{1,3}(?:,\d{3})+\s*円"),        # 1,000円・10,500円
    re.compile(r"\d+\s*円"),                        # 500円・3000円
    re.compile(r"[¥￥]\s*\d+(?:[,，]?\d+)*"),        # ¥1000・￥5,000
    re.compile(r"\d+(?:～~〜-)\d+\s*円"),            # 300〜500円
    re.compile(r"\d+\s*[%％]\s*off", re.IGNORECASE),  # 50%off
    re.compile(r"\d+\s*[%％]?割引"),                 # 30%割引・2割引
    re.compile(r"\d+\s*ポイント還元"),               # 100ポイント還元
]
def _sanitize_no_price(text):
    """料金関連の文字列を「（要確認）」に置換。textがNoneや空ならそのまま"""
    if not text or not isinstance(text, str):
        return text
    out = text
    for p in _PRICE_PATTERNS:
        out = p.sub("（要確認）", out)
    # 連続する「（要確認）」を1つに圧縮
    out = re.sub(r"(（要確認）)(?:[\s、・,/]*\1)+", "（要確認）", out)
    # 「（要確認）/台」「（要確認）/日」のような接尾辞も削除
    out = re.sub(r"（要確認）[/／]\s*[台日人]", "（要確認）", out)
    return out


def _sanitize_ship_info(info):
    """ship_info 辞書全体を再帰的に料金サニタイズ"""
    if isinstance(info, dict):
        return {k: _sanitize_ship_info(v) for k, v in info.items()}
    if isinstance(info, list):
        return [_sanitize_ship_info(v) for v in info]
    if isinstance(info, str):
        return _sanitize_no_price(info)
    return info


def _ship_calc_sailrate(catches, ship_name, today_dt):
    """直近30日の出船日数 / 欠航日数 / 出船率"""
    from datetime import timedelta
    cutoff = today_dt - timedelta(days=30)
    days_sail = set()
    days_cancel = set()
    for c in catches:
        if c.get("ship") != ship_name:
            continue
        d_str = c.get("date") or ""
        try:
            d = datetime.strptime(d_str, "%Y/%m/%d")
        except ValueError:
            continue
        if d < cutoff or d > today_dt:
            continue
        if c.get("is_cancellation") or "欠航" in (c.get("fish") or [""])[0]:
            days_cancel.add(d_str)
        else:
            days_sail.add(d_str)
    sail = len(days_sail)
    cancel = len(days_cancel)
    total = sail + cancel
    rate = round(100.0 * sail / total) if total > 0 else None
    return sail, cancel, rate


def _ship_recent_fish_html(catches, ship_name, today_dt, display_label=None):
    """直近7日 × 上位3魚種の7日推移バーチャート HTML
    T19: display_label デフォルトを None に変更（内部で M/D 形式を自動算出）"""
    from datetime import timedelta
    from collections import defaultdict
    cutoff = today_dt - timedelta(days=7)
    # 魚種別カウント（直近7日）
    fish_count = defaultdict(int)
    fish_daily = defaultdict(lambda: defaultdict(list))  # fish → date_str → [cnts]
    fish_size = defaultdict(list)
    fish_point = defaultdict(list)
    for c in catches:
        if c.get("ship") != ship_name:
            continue
        d_str = c.get("date") or ""
        try:
            d = datetime.strptime(d_str, "%Y/%m/%d")
        except ValueError:
            continue
        if d < cutoff or d > today_dt:
            continue
        for f in c.get("fish") or []:
            if not f or f in ("不明", "欠航"):
                continue
            cr = c.get("count_range") or {}
            cnt_max = cr.get("max")
            if cnt_max:
                fish_count[f] += 1
                fish_daily[f][d_str].append(cnt_max)
                sr = c.get("size_range_cm") or {}
                if sr.get("min"): fish_size[f].append(sr["min"])
                if sr.get("max"): fish_size[f].append(sr["max"])
                pp = c.get("point_place1")
                if pp: fish_point[f].append(pp)
    if not fish_count:
        return '<p style="font-size:12px;color:var(--muted);text-align:center;padding:20px">直近7日のデータがありません</p>'
    top_fish = sorted(fish_count.items(), key=lambda x: -x[1])[:3]
    out = []
    today_iso = today_dt.strftime("%Y/%m/%d")
    # 過去7日のラベル
    # T19: バーグラフ最右列も他の列と同じ M/D 形式で統一（連続日付列で曜日省略・A案）
    # display_label 引数は後方互換のため残置・但し最右列ラベルには使わない
    day_labels = []
    day_keys = []
    for i in range(6, -1, -1):
        d = today_dt - timedelta(days=i)
        day_keys.append(d.strftime("%Y/%m/%d"))
        day_labels.append(d.strftime("%-m/%-d") if os.name != "nt" else d.strftime("%#m/%#d"))
    # T20 (2026/05/09): 各日の today/weekend クラスを一度だけ計算（bars/labels で共通利用）
    day_cls_list = []
    for k in day_keys:
        _cp = []
        if k == today_iso: _cp.append("today")
        try:
            _kd = datetime.strptime(k, "%Y/%m/%d").date()
            if _kd.weekday() >= 5: _cp.append("weekend")
        except Exception:
            pass
        day_cls_list.append(" ".join(_cp))
    for fish, _ in top_fish:
        all_cnts = []
        for cnts in fish_daily[fish].values():
            all_cnts.extend(cnts)
        if not all_cnts:
            continue
        max_v = max(all_cnts) or 1
        # 日別 max 値
        bars_html = ""
        for idx, k in enumerate(day_keys):
            day_cnts = fish_daily[fish].get(k, [])
            day_max = max(day_cnts) if day_cnts else 0
            h = int(100 * day_max / max_v) if max_v else 0
            _cls = " " + day_cls_list[idx] if day_cls_list[idx] else ""
            bars_html += f'<div class="cb{_cls}" style="height:{max(h,5)}%"></div>'
        labels_html = ""
        for idx, lab in enumerate(day_labels):
            _lcls = f' class="{day_cls_list[idx]}"' if day_cls_list[idx] else ""
            labels_html += f'<span{_lcls}>{lab}</span>'
        sz_str = ""
        if fish_size[fish]:
            sz_lo = int(min(fish_size[fish]))
            sz_hi = int(max(fish_size[fish]))
            sz_str = f"{sz_lo}〜{sz_hi}cm" if sz_lo != sz_hi else f"{sz_lo}cm"
        from collections import Counter as _C
        top_pt = _C(fish_point[fish]).most_common(1)[0][0] if fish_point[fish] else ""
        cnt_lo = int(min(all_cnts))
        cnt_hi = int(max(all_cnts))
        range_str = f"{cnt_lo}〜{cnt_hi}匹" if cnt_lo != cnt_hi else f"{cnt_hi}匹"
        meta_parts = []
        if sz_str: meta_parts.append(f"<strong>サイズ:</strong> {sz_str}")
        if top_pt: meta_parts.append(f"<strong>主要ポイント:</strong> {top_pt}")
        meta_html = " | ".join(meta_parts) if meta_parts else ""
        out.append(
            f'<div class="fish-section">'
            f'<h3>{fish} <span class="h-range">{range_str}</span></h3>'
            f'<div class="chart-bars">{bars_html}</div>'
            f'<div class="chart-labels">{labels_html}</div>'
            + (f'<div class="fish-meta">{meta_html}</div>' if meta_html else "")
            + '</div>'
        )
    return "\n".join(out)


def _ship_area_ranking_html(catches, area, self_name, today_dt):
    """同エリアの船宿ランキング（直近30日件数 TOP5）"""
    from datetime import timedelta
    from collections import Counter as _C
    cutoff = today_dt - timedelta(days=30)
    counter = _C()
    for c in catches:
        if c.get("area") != area:
            continue
        d_str = c.get("date") or ""
        try:
            d = datetime.strptime(d_str, "%Y/%m/%d")
        except ValueError:
            continue
        if d < cutoff or d > today_dt:
            continue
        if c.get("is_cancellation"):
            continue
        sn = c.get("ship")
        if sn:
            counter[sn] += 1
    if not counter:
        return ""
    top5 = counter.most_common(5)
    out = []
    for i, (sn, cnt) in enumerate(top5, 1):
        # 自船宿は強調
        is_self = (sn == self_name)
        cls = "rk self" if is_self else "rk"
        slug = _SHIP_ROMAJI.get(sn)
        # T8 決定通り: ship_romaji_map と ship_info の両方にあるときだけリンク化（404防止）
        if is_self:
            name_html = f'{sn}（このページ）'
        elif slug and sn in _SHIP_INFO:
            name_html = f'<a href="{slug}.html">{sn}</a>'
        else:
            name_html = sn
        out.append(
            f'<div class="{cls}">'
            f'<span class="rk-rank">{i}位</span>'
            f'<span class="rk-name">{name_html}</span>'
            f'<span class="rk-pct">{cnt}件</span>'
            f'</div>'
        )
    return (
        '<div class="rank-box">'
        f'<h3>{area}エリアの船宿ランキング（直近30日・釣果件数）</h3>'
        + "".join(out)
        + '</div>'
    )


def _ship_primary_fish_list(catches, ship_name, limit=5):
    """その船宿の主要対象魚（直近90日・釣果件数 TOP N）"""
    from datetime import timedelta
    from collections import Counter as _C
    cutoff = datetime.now(JST).replace(tzinfo=None) - timedelta(days=90)
    counter = _C()
    for c in catches:
        if c.get("ship") != ship_name:
            continue
        d_str = c.get("date") or ""
        try:
            d = datetime.strptime(d_str, "%Y/%m/%d")
        except ValueError:
            continue
        if d < cutoff:
            continue
        for f in c.get("fish") or []:
            if f not in ("不明", "欠航"):
                counter[f] += 1
    return [n for n, _ in counter.most_common(limit)]


def _ship_main_points(catches, ship_name, limit=3):
    """その船宿の主要ポイント TOP3"""
    from datetime import timedelta
    from collections import Counter as _C
    cutoff = datetime.now(JST).replace(tzinfo=None) - timedelta(days=180)
    counter = _C()
    for c in catches:
        if c.get("ship") != ship_name:
            continue
        d_str = c.get("date") or ""
        try:
            d = datetime.strptime(d_str, "%Y/%m/%d")
        except ValueError:
            continue
        if d < cutoff:
            continue
        for k in ("point_place1", "point_place2", "point_place3"):
            p = c.get(k)
            if p:
                counter[p] += 1
    return [p for p, _ in counter.most_common(limit)]


def _ship_build_page_html(ship, info, catches, area_coords, today_dt, crawled_at):
    """1船宿分のHTMLを生成して返す"""
    name = ship["name"]
    slug = ship["romaji_slug"]
    area = ship["area"]
    chowari_id = ship.get("chowari_id")
    castingnet_id = ship.get("castingnet_id") or chowari_id
    sid = ship.get("sid")
    chowari_url = f"https://www.chowari.jp/ship/{chowari_id}/" if chowari_id else None
    castingnet_url = f"https://reserve.castingnet.jp/ship{castingnet_id}.html" if castingnet_id else None

    # 料金記載は変動するため一切出さない（サニタイザで（要確認）に置換）
    info = _sanitize_ship_info(info)
    basic = info.get("basic") or {}
    vessel = info.get("vessel") or {}
    reservation = info.get("reservation") or {}
    season = info.get("season_strategy") or {}
    access = info.get("access") or {}
    features = info.get("features") or []

    sail, cancel, rate = _ship_calc_sailrate(catches, name, today_dt)
    primary_fish = _ship_primary_fish_list(catches, name)
    main_points = _ship_main_points(catches, name)
    # 当日データ有無で最右列ラベル/軸日付を決定（fish/area ページと同じ方式）
    # T19 (2026/05/09): バーグラフ軸を ship 個別の最新データ日に揃える
    _ship_catches = [c for c in catches if c.get("ship") == name]
    _today_str_s = today_dt.strftime("%Y/%m/%d")
    _, ship_today_label, _ship_data_date = _resolve_display_dataset(_ship_catches, _today_str_s)
    try:
        # T19: today_dt は datetime 型のため _ship_axis_dt も datetime 型で揃える
        _ship_axis_dt = datetime.strptime(_ship_data_date, "%Y/%m/%d") if _ship_data_date else today_dt
    except Exception:
        _ship_axis_dt = today_dt
    recent_html = _ship_recent_fish_html(catches, name, _ship_axis_dt, display_label=ship_today_label)
    area_rank_html = _ship_area_ranking_html(catches, area, name, today_dt)

    # H2 (T22): 空ページ判定 — 以下 OR 条件のいずれかで noindex 付与
    # 条件1: 直近7日データなし（_ship_recent_fish_html が該当テキストを返す）
    # 条件2: _SHIP_INFO 未登録（住所・電話・基本情報が全欠如）
    has_recent_data = "直近7日のデータがありません" not in recent_html
    has_ship_info = name in _SHIP_INFO
    is_empty_ship_page = (not has_recent_data) or (not has_ship_info)
    ship_noindex_tag = (
        '<meta name="robots" content="noindex, follow">'
        if is_empty_ship_page
        else ""
    )
    # sitemap 除外用にスラグをモジュールセットに蓄積
    if is_empty_ship_page and slug:
        _SHIP_NOINDEX_SLUGS.add(slug)

    # area の slug（パンくず・リンク用）
    area_slug_str = area_slug(area)

    # HEROバッジ（料金・★評価など出所不明・E-E-A-T観点で除外）
    badges_html = ""
    for f in features[:5]:
        # 料金表記・星評価（出所不明）・他サイト評価点は除外
        if any(k in f for k in ("円", "￥", "¥", "%off", "％off", "★", "★", "/5", "つ星", "(件)", "件）")):
            continue
        if re.search(r"\d+\.?\d*\s*[★⭐]", f):
            continue
        badges_html += f'<span class="sh-badge">{f}</span>'
        if badges_html.count("sh-badge") >= 3:
            break
    # 出船率は最低5日のサンプルがある場合のみ表示（データ不足の誤解防止）
    overall_str = ""
    total_known = sail + cancel
    if rate is not None and total_known >= 5:
        overall_str = f"直近30日の出船率: {rate}% （出船{sail}日 / 欠航{cancel}日）"
    elif total_known > 0:
        overall_str = f"直近30日: 出船{sail}日 / 欠航{cancel}日 <span style=\"font-size:9px;opacity:.7\">(クロール記録ベース)</span>"

    # ships.json から contact 情報を取得（official_url, phone, address, business_hours, closed_days）
    ships_contact = {}
    for s in SHIPS:
        if s.get("name") == name:
            ships_contact = {
                "official_url": s.get("official_url"),
                "phone": s.get("phone"),
                "address": s.get("address"),
                "business_hours": s.get("business_hours"),
                "closed_days": s.get("closed_days"),
            }
            break

    # basic に ships_contact をマージ（ships_contact が優先・最新データを表示）
    basic_merged = {**basic, **ships_contact}

    # 基本情報BOX
    info_rows = []
    info_rows.append(f'<div class="info-row"><span class="info-label">エリア</span><span class="info-val"><a href="../area/{area_slug_str}.html">{area}</a></span></div>')
    addr = basic_merged.get("address")
    if addr and addr != "未確認":
        info_rows.append(f'<div class="info-row"><span class="info-label">所在地</span><span class="info-val">{addr}</span></div>')
    phone = basic_merged.get("phone")
    if phone and phone != "未確認":
        info_rows.append(f'<div class="info-row"><span class="info-label">電話</span><span class="info-val">{phone}</span></div>')
    off = basic_merged.get("official_url")
    if off and off.startswith("http"):
        info_rows.append(f'<div class="info-row"><span class="info-label">公式サイト</span><span class="info-val"><a href="{off}" rel="nofollow noopener" target="_blank">外部サイトを開く →</a></span></div>')
    if primary_fish:
        info_rows.append(f'<div class="info-row"><span class="info-label">主要対象魚</span><span class="info-val">{" ・ ".join(primary_fish)}</span></div>')
    if main_points:
        info_rows.append(f'<div class="info-row"><span class="info-label">主要ポイント</span><span class="info-val">{" / ".join(main_points)}（直近実績より）</span></div>')
    nearest = access.get("nearest_station")
    parking = access.get("parking")
    acc_parts = []
    if nearest: acc_parts.append(nearest)
    if parking: acc_parts.append(f"駐車場: {parking}")
    if acc_parts:
        info_rows.append(f'<div class="info-row"><span class="info-label">アクセス</span><span class="info-val">{" / ".join(acc_parts)}</span></div>')

    # 営業時間と定休日
    business_hours = basic_merged.get("business_hours")
    if business_hours and business_hours not in ("記載なし", "未記載"):
        info_rows.append(f'<div class="info-row"><span class="info-label">営業時間</span><span class="info-val">{business_hours}</span></div>')
    closed_days = basic_merged.get("closed_days")
    if closed_days and closed_days not in ("記載なし", "未記載"):
        info_rows.append(f'<div class="info-row"><span class="info-label">定休日</span><span class="info-val">{closed_days}</span></div>')
    if total_known >= 5 and rate is not None:
        info_rows.append(f'<div class="info-row"><span class="info-label">直近30日</span><span class="info-val">出船{sail}日 / 欠航{cancel}日（出船率{rate}%）</span></div>')
    elif total_known > 0:
        info_rows.append(f'<div class="info-row"><span class="info-label">直近30日</span><span class="info-val">出船{sail}日 / 欠航{cancel}日 <span style="color:var(--muted);font-size:11px">(当サイトのクロール記録ベース・実出船日数とは異なります)</span></span></div>')

    # 船舶・設備BOX（vessel が空なら省略）
    vessel_html = ""
    if vessel and any(vessel.get(k) for k in ("length_m", "tonnage_t", "capacity", "facilities")):
        sg_items = []
        if vessel.get("length_m"): sg_items.append(f'<div class="sg-item"><strong>全長</strong>{vessel["length_m"]} m</div>')
        if vessel.get("tonnage_t"): sg_items.append(f'<div class="sg-item"><strong>総トン数</strong>{vessel["tonnage_t"]} t</div>')
        if vessel.get("capacity"): sg_items.append(f'<div class="sg-item"><strong>定員</strong>{vessel["capacity"]} 名</div>')
        spec_grid = '<div class="spec-grid">' + "".join(sg_items) + '</div>' if sg_items else ""
        ft_html = ""
        for f in vessel.get("facilities") or []:
            ft_html += f'<span class="ft">{f}</span>'
        ft_block = f'<div class="facility-tags" style="margin-top:12px">{ft_html}</div>' if ft_html else ""
        vessel_html = f'<h2 class="st">船舶・設備</h2><div class="spec-card">{spec_grid}{ft_block}</div>'

    # 予約方法BOX（料金一切なし・予約は船宿への直接電話が原則）
    rsv_items = []
    dt_str = reservation.get("departure_time")
    if dt_str:
        rsv_items.append(f'<div class="sg-item"><strong>出船時間</strong>{dt_str}</div>')
    # 予約手段は常に「電話で直接お問い合わせください」（船宿の方針）
    if phone:
        # tel: リンクは数字以外を除去
        phone_digits = re.sub(r"[^\d+\-]", "", phone)
        rsv_items.append(f'<div class="sg-item"><strong>予約方法</strong>船宿へ直接お電話 → <a href="tel:{phone_digits}">{phone}</a></div>')
    else:
        rsv_items.append('<div class="sg-item"><strong>予約方法</strong>船宿へ直接お電話ください</div>')
    rentals = reservation.get("rental_items") or []
    if rentals:
        rentals_str = " ・ ".join(rentals)
        rsv_items.append(f'<div class="sg-item"><strong>レンタル品</strong>あり（{rentals_str}）</div>')
    discounts = reservation.get("discount_types") or []
    if discounts:
        disc_str = " ・ ".join(discounts)
        rsv_items.append(f'<div class="sg-item"><strong>割引制度</strong>あり（{disc_str}）</div>')
    rsv_grid = '<div class="spec-grid">' + "".join(rsv_items) + '</div>' if rsv_items else ""
    reservation_html = (
        '<h2 class="st">予約方法</h2>'
        '<div class="spec-card">'
        + rsv_grid
        + '<p style="font-size:11px;color:var(--muted);margin-top:10px">※ 予約は船宿へ直接お電話ください。料金・空席状況・出船判断などは電話で確認するのが確実です。</p>'
        + '</div>'
    )

    # 季節別の狙い物（4つ揃っていなければ部分表示）
    season_html = ""
    season_labels = [("spring", "春 (3〜5月)"), ("summer", "夏 (6〜8月)"), ("autumn", "秋 (9〜11月)"), ("winter", "冬 (12〜2月)")]
    sg_items = []
    for k, label in season_labels:
        v = season.get(k)
        if v:
            sg_items.append(f'<div class="sg"><div class="sg-label">{label}</div><div class="sg-fish">{v}</div></div>')
    if sg_items:
        season_html = '<h2 class="st">季節別の狙い物</h2><div class="spec-card"><div class="season-grid">' + "".join(sg_items) + '</div></div>'

    # FAQ は不要（船宿のテンプレ質問は表示しない）
    faq_html = ""

    # JSON-LD（LocalBusiness + BreadcrumbList + FAQPage）
    ld_local = {
        "@context": "https://schema.org",
        "@type": "LocalBusiness",
        "name": name,
        "url": f"{SITE_URL}/ship/{slug}.html",
        "areaServed": area,
    }
    if addr:
        ld_local["address"] = {"@type": "PostalAddress", "streetAddress": addr}
    if phone:
        ld_local["telephone"] = phone
    coord = area_coords.get(area) or area_coords.get(area + "港") or {}
    if coord.get("lat") and coord.get("lon"):
        ld_local["geo"] = {"@type": "GeoCoordinates", "latitude": coord["lat"], "longitude": coord["lon"]}
    ld_breadcrumb = {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "トップ", "item": f"{SITE_URL}/"},
            {"@type": "ListItem", "position": 2, "name": area, "item": f"{SITE_URL}/area/{area_slug_str}.html"},
            {"@type": "ListItem", "position": 3, "name": name, "item": f"{SITE_URL}/ship/{slug}.html"},
        ],
    }
    ld_json = (
        '<script type="application/ld+json">' + json.dumps(ld_local, ensure_ascii=False) + '</script>'
        '<script type="application/ld+json">' + json.dumps(ld_breadcrumb, ensure_ascii=False) + '</script>'
    )

    # 電話CTA HTML（電話番号があれば tel: リンク・なければ案内）
    if phone:
        phone_digits = re.sub(r"[^\d+\-]", "", phone)
        phone_cta_html = f'<a href="tel:{phone_digits}" style="background:var(--pos)">📞 電話: {phone}</a>'
        phone_cta_block = (
            f'<a href="tel:{phone_digits}" '
            'style="display:inline-block;padding:14px 28px;background:var(--pos);color:#fff;'
            'border-radius:24px;font-weight:700;font-size:16px;margin-top:8px;text-decoration:none">'
            f'📞 {phone}</a>'
        )
    else:
        phone_cta_html = ''
        phone_cta_block = (
            '<p style="font-size:12px;color:rgba(255,255,255,.85);margin-top:10px">'
            '電話番号は船宿の公式サイトまたは予約サイトでご確認ください。</p>'
        )

    # ヘッダ・ナビ・ボトムナビ（fish/area ページと同じ構成・5項目）
    header_html = (
        '<header><div class="inner">'
        '<h1><a href="/index.html">船釣り<span>予想</span></a></h1>'
        '<span style="font-size:11px;opacity:.5">funatsuri-yoso.com</span>'
        '</div></header>'
        '<nav class="gnav">'
        '<a href="/index.html">今日の釣果</a>'
        '<a href="/fish/">魚種</a>'
        '<a href="/area/">エリア</a>'
        '<a href="/calendar.html">カレンダー</a>'
        '<a href="/forecast/index.html" class="prem">有料プラン</a>'
        '</nav>'
    )
    bottom_nav = (
        '<div class="bn">'
        '<a href="/index.html"><span class="i">🎣</span>釣果</a>'
        '<a href="/fish/"><span class="i">🐟</span>魚種</a>'
        '<a href="/area/"><span class="i">📍</span>エリア</a>'
        '<a href="/calendar.html"><span class="i">📅</span>カレンダー</a>'
        '<a href="/forecast/index.html" class="prem"><span class="i">⭐</span>有料</a>'
        '</div>'
    )

    # メタ
    title = f"{name}（{area}）の釣果情報・船舶・予約方法 — 船釣り予想"
    desc_parts = [f"{name}（{area}）の船釣り情報。"]
    if vessel.get("length_m") and vessel.get("capacity"):
        desc_parts.append(f"全長{vessel['length_m']}m・定員{vessel['capacity']}名。")
    if primary_fish:
        desc_parts.append(f"主要対象魚: {' ・ '.join(primary_fish[:4])}。")
    if rate is not None and total_known >= 5:
        desc_parts.append(f"直近30日の出船率{rate}%。")
    desc = "".join(desc_parts)[:160]

    page_url = f"{SITE_URL}/ship/{slug}.html"

    html = f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
{ship_noindex_tag}
<title>{title}</title>
<meta name="description" content="{desc}">
<link rel="canonical" href="{page_url}">
<meta property="og:title" content="{title}">
<meta property="og:description" content="{desc}">
<meta property="og:url" content="{page_url}">
<meta property="og:type" content="website">
{ld_json}
<link rel="stylesheet" href="../style.css">
<style>{_SHIP_EXTRA_CSS}</style>
</head>
<body>
{header_html}

<div class="ship-hero">
<h2>{name}</h2>
<div class="sh-area">{area}</div>
<div class="sh-badges">{badges_html}</div>
{f'<div class="sh-overall">{overall_str}</div>' if overall_str else ''}
</div>

<div class="c">
<div class="bread"><a href="../">トップ</a> &gt; <a href="../area/{area_slug_str}.html">{area}</a> &gt; {name}</div>

<h2 class="st">基本情報</h2>
<div class="info-box">
{"".join(info_rows)}
</div>

{vessel_html}

{reservation_html}

{season_html}

<h2 class="st">最近の釣果実績（直近7日・船宿実績）</h2>
{recent_html}

<div class="ad-slot">広告スペース（レクタングル）</div>

<!-- 明日の予測（有料・準備中チラ見せ） -->
<div style="background:linear-gradient(135deg,#f8f4ff,#f0eafa);border:2px solid var(--prem);border-radius:var(--r);padding:16px;margin-bottom:16px">
<h3 style="font-size:14px;color:var(--prem);margin-bottom:8px;text-align:center">{name}の明日の予測（準備中）</h3>
<div style="background:var(--card);border:1px solid #e0d6f5;border-radius:8px;padding:12px;margin-bottom:8px;position:relative;overflow:hidden">
<div style="filter:blur(5px);user-select:none;pointer-events:none">
<div style="font-weight:700;color:var(--accent);font-size:13px">明日の主要魚種 — 信頼度 ★★★★★</div>
<div style="font-size:15px;font-weight:800;color:var(--cta);margin-top:4px">XX〜XX匹</div>
<div style="font-size:10px;color:var(--sub);margin-top:4px">気象条件・潮通し分析より推定</div>
</div>
<div style="position:absolute;inset:0;display:flex;align-items:center;justify-content:center;background:rgba(124,58,237,.06);font-size:13px;font-weight:700;color:var(--prem)">月額500円で見る予定</div>
</div>
</div>

{area_rank_html}

<div class="contact-cta">
<h3>{name}で釣行を計画する</h3>
<p>予約は船宿へ直接お電話ください。最新の料金・空席・出船判断はすべて船宿が把握しています。</p>
{phone_cta_block}
</div>

<div class="ad-slot">広告スペース（レクタングル）</div>

{faq_html}

</div>

<footer>
<a href="../pages/privacy.html">プライバシーポリシー</a> · <a href="../pages/terms.html">利用規約</a> · <a href="../pages/about.html">サイトについて</a><br>
<div style="margin-top:6px"><a href="../">トップ</a> · <a href="../area/{area_slug_str}.html">{area}</a></div>
<span style="margin-top:6px;display:inline-block">© 2026 船釣り予想 — 最終更新: {crawled_at}</span>
</footer>

{bottom_nav}

</body>
</html>"""
    return html


def build_ship_pages(catches, crawled_at=""):
    """船宿個別ページを docs/ship/ に生成する（romaji_slug がある全船宿）"""
    out_dir = os.path.join(WEB_DIR, "ship")
    os.makedirs(out_dir, exist_ok=True)
    # ships.json に romaji_slug があるすべての船宿を対象
    target_ships = [
        s for s in SHIPS
        if s.get("romaji_slug") and not s.get("exclude")
    ]
    today_dt = datetime.now(JST).replace(tzinfo=None)
    area_coords = _ship_load_area_coords()
    generated = 0
    for ship in target_ships:
        name = ship["name"]
        # ship_info.json があればそれを使用、なければ空で作成
        info = _SHIP_INFO.get(name) or {}
        try:
            html = _ship_build_page_html(ship, info, catches, area_coords, today_dt, crawled_at)
            slug = ship["romaji_slug"]
            with open(os.path.join(out_dir, f"{slug}.html"), "w", encoding="utf-8") as f:
                f.write(html)
            generated += 1
        except Exception as e:
            print(f"  船宿ページ生成失敗 {name}: {e}")
    print(f"船宿ページ生成: {generated} 件 → docs/ship/")
    return generated


# ============================================================
# sitemap.xml 自動生成
# ============================================================
def build_sitemap(data):
    from urllib.parse import quote as _quote
    now = datetime.now(JST).replace(tzinfo=None).strftime("%Y-%m-%d")
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
    # fish_tackle.json で説明があり最低限ページが生成される魚種も sitemap に含める（build_fish_pages と整合）
    try:
        for f in load_fish_tackle().keys():
            if f in _FISH_ROMAJI:
                fish_set.add(f)
    except Exception:
        pass
    fish_set = {f for f in fish_set if f in _FISH_ROMAJI}
    for fish in sorted(fish_set):
        urls.append((f"{SITE_URL}/fish/{fish_slug(fish)}.html", "0.8", "daily"))
    # area/*.html
    area_set = set(c["area"] for c in data if c.get("area"))
    # ship_info / 有効船宿 / area_description で言及される area も含める（build_area_pages と整合）
    for _ship_name, _info in _SHIP_INFO.items():
        _a = _info.get("area")
        if _a:
            area_set.add(_a)
    for _s in SHIPS:
        if _s.get("exclude") or _s.get("boat_only"):
            continue
        _a = _s.get("area")
        if _a:
            area_set.add(_a)
    try:
        for _a in load_area_description().keys():
            area_set.add(_a)
    except Exception:
        pass
    area_set = {a for a in area_set if a in _AREA_ROMAJI}
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
    # ship/*.html（romaji_slug + ship_info あり・chowari_id なくても手動データなら掲載）
    # H2 (T22): _SHIP_NOINDEX_SLUGS に含まれる空ページは sitemap から除外
    for s in SHIPS:
        slug_s = s.get("romaji_slug")
        if slug_s and s["name"] in _SHIP_INFO and slug_s not in _SHIP_NOINDEX_SLUGS:
            urls.append((f"{SITE_URL}/ship/{slug_s}.html", "0.6", "weekly"))
    # premium/plan.html（静的・月次更新）
    urls.append((f"{SITE_URL}/premium/plan.html", "0.7", "monthly"))
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

    # --html-only: catches.json + history.json を使ってHTML生成だけを実行（クロールなし）
    if "--html-only" in _sys.argv:
        crawled_at = datetime.now(JST).replace(tzinfo=None).strftime("%Y/%m/%d %H:%M")
        with open("catches.json", encoding="utf-8") as _f:
            _snap = json.load(_f)
        valid_catches = _snap.get("data", _snap) if isinstance(_snap, dict) else _snap
        with open("history.json", encoding="utf-8") as _f:
            history = json.load(_f)
        weather_data = load_weather_data()
        forecast_data = None
        if os.path.exists("forecast.json"):
            with open("forecast.json", encoding="utf-8") as _f:
                forecast_data = json.load(_f)
        if forecast_data:
            weather_data["_forecast_data"] = forecast_data
        os.makedirs(WEB_DIR, exist_ok=True)
        build_style_css()
        build_main_js()
        # catches.json はスナップショット（当日のみ・魚データ空）なので
        # データ依存ページ（index/fish/area/ship/forecast/sitemap）は生成しない。
        # GitHub Actions のフルクロール版を保護するためスキップする。
        with open(os.path.join(WEB_DIR, "calendar.html"), "w", encoding="utf-8") as _f:
            _f.write(build_calendar_page(crawled_at))
        build_premium_plan_page()
        print(f"=== HTML生成完了（--html-only: CSS/JS/calendar/premium/plan のみ）===")
        return

    all_catches = []
    errors = []
    now = datetime.now(JST).replace(tzinfo=None)
    crawled_at = now.strftime("%Y/%m/%d %H:%M")
    year = now.year
    # exclude / boat_only フラグを持つ船宿はクロール対象外
    active_ships = [s for s in SHIPS if not s.get("exclude") and not s.get("boat_only")]
    fv_count  = sum(1 for s in active_ships if s.get("source", "fishing-v") == "fishing-v")
    gyo_count = sum(1 for s in active_ships if s.get("source") == "gyo")
    print(f"=== 関東船釣りクローラー v5.15 開始: {crawled_at} ===")
    print(f"対象: {len(active_ships)} 船宿（釣りビジョン:{fv_count} / gyo.ne.jp:{gyo_count}）\n")

    for s in active_ships:
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
    _today_str_snap = datetime.now(JST).replace(tzinfo=None).strftime("%Y/%m/%d")
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
    # R1 (2026/05/06): build_forecast_json が None を返した場合の defensive fallback。
    # forecast.json が disk にあれば読み込んで ZONE C 出船リスク予報を出す。
    # API 失敗時に ZONE C が消える regression の防止策。
    elif os.path.exists("forecast.json"):
        try:
            with open("forecast.json", encoding="utf-8") as f:
                weather_data["_forecast_data"] = json.load(f)
            print(f"forecast.json fallback: {len(weather_data['_forecast_data'].get('days', {}))} 日分 (disk)")
        except Exception as e:
            print(f"forecast.json fallback failed: {e}")
    os.makedirs(WEB_DIR, exist_ok=True)
    with open(os.path.join(WEB_DIR, "CNAME"), "w", encoding="utf-8") as f:
        f.write("funatsuri-yoso.com")
    build_style_css()
    build_main_js()
    with open(os.path.join(WEB_DIR, "index.html"), "w", encoding="utf-8") as f:
        f.write(build_html(valid_catches, crawled_at, history, weather_data))
    build_fish_pages(valid_catches, history, crawled_at)
    # fish_area を先に生成 → build_area_pages 内の _fish_area_link_or_fish が
    # 当日生成された fish_area ページを正しく検出できる
    build_fish_area_pages(valid_catches, crawled_at, history)
    build_area_pages(valid_catches, history, crawled_at, weather_data)
    build_ship_pages(valid_catches, crawled_at)
    with open(os.path.join(WEB_DIR, "calendar.html"), "w", encoding="utf-8") as f:
        f.write(build_calendar_page(crawled_at))
    build_sitemap(valid_catches)
    build_premium_plan_page()
    print(f"\n=== 完了 ===")
    _today_label = f"当日: {len(today_all)} 件" if today_all else f"当日0件→全件フォールバック: {len(all_catches)} 件"
    print(f"釣果: {len(all_catches)} 件（有効: {len(valid_catches)} / 異常値: {anomaly_count} / 重複除外: {dup_removed}）")
    print(f"出力: {_today_label}（catches.json）")
    print(f"エラー: {errors or 'なし'}")
    print(f"出力: docs/ (index.html / fish/*.html / area/*.html / fish_area/*.html / sitemap.xml / premium/plan.html / CNAME)")

if __name__ == "__main__":
    main()
