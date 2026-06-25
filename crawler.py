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
- 魚種×港ページ新設: build_fish_area_pages()（≥1件の組み合わせ全て fish_area/ に生成・2026-05-10 閾値 5→1 変更）
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
    "茨城":               ["日立久慈港", "波崎港", "鹿島港", "鹿島市新浜",
                           "久慈", "会瀬漁港", "大洗港", "平潟",
                           "日立", "波崎新港", "那珂湊港", "鹿島",
                           "鹿嶋新港", "鹿嶋旧港"],
    "千葉・外房":         ["外川", "外川港", "飯岡港", "片貝", "片貝港",
                           "大原", "大原港", "天津港", "御宿岩和田港",
                           "勝浦川津港", "勝浦松部港",
                           "勝浦", "江見", "江見漁港", "相浜", "浜行川"],
    "千葉・内房":         ["勝山", "勝山港", "保田港", "金谷港", "富浦港",
                           "洲崎港", "富津", "富津港", "長浦",
                           "伊戸", "洲崎"],
    "千葉・東京湾奥":     ["浦安", "江戸川放水路", "江戸川放水路･原木中山",
                           "江戸川区今井水門", "江戸川区新今井橋", "江戸川区鹿本橋"],
    "東京":               ["羽田", "平和島", "東葛西",
                           "品川区品川堀", "品川区立会川勝島運河", "品川区鮫洲勝島運河",
                           "大田区六郷水門", "大田区呑川", "大田区海老取川",
                           "大田区羽田",
                           "江東区夢の島桟橋", "江東区小名木川", "江東区木場",
                           "江東区東京湾マリーナ", "江東区釣船橋",
                           "港区京浜運河", "足立区千住大橋"],
    "神奈川・東京湾":     ["小柴港", "金沢漁港", "金沢八景", "新安浦港",
                           "横浜本牧港", "横浜港･新山下", "横浜港", "磯子港",
                           "久比里", "久比里港",
                           "久里浜", "久里浜港", "鴨居大室港", "小坪港",
                           "小網代港", "佐島", "佐島港",
                           "川名", "柴漁港", "横浜", "横浜市八幡橋",
                           "横浜市金沢八景乙舳", "横浜市金沢八景平潟"],
    "神奈川・相模湾":     ["松輪", "松輪江奈港", "松輪間口港", "長井", "長井港",
                           "長井新宿港", "長井漆山港", "葉山鐙摺",
                           "葉山あぶずり港", "葉山町葉山鐙摺港", "腰越", "茅ヶ崎", "茅ヶ崎港",
                           "平塚", "平塚港", "平塚漁港", "大磯港", "寒川港",
                           "小田原早川", "小田原早川港",
                           "腰越港", "片瀬漁港", "小田原新港", "早川漁港",
                           "湯河原町福浦港", "真鶴町真鶴港"],
    "静岡":               ["宇佐美", "戸田", "沼津内港", "沼津静浦",
                           "由比", "御前崎港", "福田港", "下田港",
                           "宇佐美港", "伊東", "熱海港", "網代", "網代港",
                           "戸又港", "戸田港", "久料港", "南伊豆町手石港",
                           "松崎港", "松崎町松崎港", "西伊豆町安良里港", "清水港", "須崎港",
                           "焼津港", "焼津小川港", "田子の浦港",
                           "沼津市江の浦港", "静浦漁港", "寸座マリーナ"],
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

# X (Twitter) アカウント設定（手動投稿時の URL 貼付け時にカードを描画するための twitter:site 値）
TWITTER_HANDLE = "@funatsuri_yoso"
# 共通 OGP 画像（1200x630 推奨・docs/ogp-default.png）。未配置時は最新 x_post PNG を fallback コピーで充填
OGP_DEFAULT_IMG = f"{SITE_URL}/ogp-default.png"

# Google AdSense
ADSENSE_TAG = '<script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=ca-pub-7406401300491553" crossorigin="anonymous"></script>'
# ship ページ body のレクタングル広告枠（2026/06/16: noindex の空 ship では出さない＝
# 「インデックスされないページは収益化しない」AdSense 薄判定対策）
_SHIP_AD_RECT = '<div class="ad-slot">広告スペース（レクタングル）</div>'
_SHIP_AD_INS = ('<ins class="adsbygoogle" style="display:block;min-height:0;height:auto" '
                'data-ad-client="ca-pub-7406401300491553" data-ad-slot="auto" data-ad-format="auto" '
                'data-full-width-responsive="true"></ins>'
                '<script>(adsbygoogle = window.adsbygoogle || []).push({});</script>')
# 有料予測テザー表示フラグ（2026/06/16）。
# マネタイズ方針が「D層予測は当面無料公開で集客／有料化は数千〜1万UU到達後」に変更（90_決定ログ
# 2026-06-10）されたため、fish/area/ship の「準備中・月額500円」テザーは現状ミスマッチ＋
# AdSense 薄判定リスク。False で非表示にする。有料サイトオープン時に True に戻せば全テザーが復活。
SHOW_PAID_TEASER = False
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

# [DEPRECATED 2026-06-07] 旧出船判定の閾値。判定は _WIND_BELTS/_WAVE_BELTS ベースの
# _sail_judge に統一済み（_risk_label も _sail_judge 経由に変更）。参照なし・履歴目的で残置。
# (warn_wave, warn_wind, bad_wave, bad_wind)
_RISK_THR = {
    "外海": (2.0, 10.0, 3.5, 15.0),
    "内海": (0.8,  6.0, 1.5,  9.0),
}

# 船釣り基準の風速・波高ベルト（内海/外海別・0=穏, 1=やや, 2=強, 3=暴）
# 内海 = 東京湾・相模湾・湾内の小型船想定（風6m/s で出船判断微妙、9m/s で多くの船宿欠航）
# 外海 = 外房・銭洲・神津島の大型船想定（風8m/s 程度なら問題なし、13m/s 超で欠航圏）
_WIND_BELTS = {
    "内海": (6.0, 8.0, 10.0),   # sev境界: <6=穏, 6-8=やや, 8-10=強, ≥10=暴
    "外海": (8.0, 10.0, 13.0),  # sev境界: <8=穏, 8-10=やや, 10-13=強, ≥13=暴
}
_WAVE_BELTS = {
    "内海": (0.5, 1.0, 1.5),    # sev境界: <0.5=穏, 0.5-1.0=やや, 1.0-1.5=強, ≥1.5=暴
    "外海": (1.0, 2.0, 3.0),    # sev境界: <1.0=穏, 1.0-2.0=やや, 2.0-3.0=強, ≥3.0=暴
}

def _sev_from_belts(value, belts):
    """value をベルト境界 (b0, b1, b2) で 0/1/2/3 に分類"""
    b0, b1, b2 = belts
    if value < b0: return 0
    if value < b1: return 1
    if value < b2: return 2
    return 3

def _sea_label(wave, wind, sea_type):
    """波高(m)・風速(m/s)・内海/外海 → (sev, label_text)
    sev: 0=穏, 1=やや, 2=強, 3=暴
    label_text: 「波X.Xm・風Ym/sの○○」形式の一行コメント
    """
    if sea_type not in _WIND_BELTS:
        sea_type = "内海"
    w_val = wave if wave is not None else 0.0
    wnd_val = wind if wind is not None else 0.0
    wind_sev = _sev_from_belts(wnd_val, _WIND_BELTS[sea_type])
    wave_sev = _sev_from_belts(w_val, _WAVE_BELTS[sea_type])
    sev = max(wind_sev, wave_sev)
    # severity ごとの定型コメント（validate_output.py のキーワード「出船日和/出船注意/欠航警戒」を含める）
    if sev == 0:
        tail = "の好海況で出船日和"
    elif sev == 1:
        tail = "でそよ風あり、釣り可"
    elif sev == 2:
        tail = "の強風で出船注意、船酔い注意"
    else:  # 3
        tail = "の暴風で欠航警戒"
    return sev, f"波{w_val:.1f}m・風{wnd_val:.0f}m/s{tail}"

# ============================================================
# 出船判定の単一ソース（全ページ共通）
# 海域別ベルト（_WIND_BELTS/_WAVE_BELTS）で severity 0-3 を算出し、
# トップのリスクグリッド・予測ページ・週末カードの全表示をこれに統一する。
# 旧 _risk_label（_RISK_THR 別閾値・海域別3段階）と _fishing_ok_score（海域非依存スコア）の
# 二重基準により、同一エリア・同一日でも判定が食い違う不整合（2026-06-07 指摘）を解消する。
# ============================================================
_SAIL_LEVELS = {
    #     cls,    icon, label,       score, color
    0: ("good", "◎", "出船日和", 90, "#4dcc88"),
    1: ("good", "○", "出船可",   68, "#7ac77a"),
    2: ("warn", "△", "注意",     42, "#e8a34d"),
    3: ("bad",  "✕", "欠航警戒", 15, "#cc4d4d"),
}

def _sail_severity(wave, wind, sea_type):
    """波高(m)・風速(m/s)・内海/外海 → severity 0(穏)〜3(暴)。海域別ベルトで判定。"""
    if sea_type not in _WIND_BELTS:
        sea_type = "内海"
    w = wave if wave is not None else 0.0
    n = wind if wind is not None else 0.0
    return max(_sev_from_belts(n, _WIND_BELTS[sea_type]),
               _sev_from_belts(w, _WAVE_BELTS[sea_type]))

def _sail_judge(wave, wind, sea_type):
    """出船判定の正準関数。(severity, cls, icon, label, score, color) を返す。

    全ての出船判定（トップ・予測ページ・週末カード・日次/エリア別）はこれを使う。
    """
    sev = _sail_severity(wave, wind, sea_type)
    cls, icon, label, score, color = _SAIL_LEVELS[sev]
    return sev, cls, icon, label, score, color

def _risk_label(wave, wind, sea_type):
    """[後方互換] 波高・風速・海域 → (cls, icon, lbl)。判定は _sail_judge に統一。"""
    _sev, cls, icon, label, _score, _color = _sail_judge(wave, wind, sea_type)
    return cls, icon, label

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
        f'<div class="risk-row-head"><span class="risk-sea-type">{label}</span>'
        f'<span class="risk-sea-areas">（{subtitle}・最も荒れるエリア基準）</span></div>'
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

# [DEPRECATED 2026-06-07] 海域非依存スコアで出船判定の二重基準の原因だった。
# 出船判定は _sail_judge（海域別ベルト・単一ソース）に統一済み。呼び出し元なし。
def _fishing_ok_score(wave, wind):
    """[非推奨] 出船可否スコア。出船判定は _sail_judge に統一済み。"""
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
    """[非推奨] 出船判定は _sail_judge に統一済み。"""
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
            # 出船判定は海域別の正準関数に統一（週末カードもエリアの海域型で判定）
            _sev, ok_cls, _jic, _jlb, score, ok_color = _sail_judge(wave, wind, _area_sea_type(group))
            ok_txt = f"{_jic} {_jlb}"

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
# エリア正規化（2026/06/20）: 船宿が自由表記する area 名のうち、同一物理港を指す
# 別名を正規港名へ統合する（表示層のみ。ソースCSVは原表記を保持する＝B案）。
# 重複の根拠: 船宿重複 or 同一市の「X市Y港」フル表記 or 旧港/新港の分裂。
# 誤統合回避のため曖昧なもの（横浜/勝浦/日立/金沢漁港/小網代/茨城平潟）は対象外。
_AREA_CANONICAL = {
    "鹿島": "鹿島港", "鹿島市新浜": "鹿島港", "鹿嶋旧港": "鹿島港", "鹿嶋新港": "鹿島港",
    "久慈": "日立久慈港",
    "洲崎": "洲崎港",
    "網代": "網代港",
    "佐島港": "佐島",
    "横浜市金沢八景乙舳": "金沢八景", "横浜市金沢八景平潟": "金沢八景",
    "横浜港": "横浜港･新山下",
    "葉山町葉山鐙摺港": "葉山あぶずり港",
    "平塚漁港": "平塚港",
    "富士市田子の浦漁港": "田子の浦港",
    "江見漁港": "江見",
    "大洗町大洗港": "大洗港",
    "松崎町松崎港": "松崎港",
    "大田区羽田": "羽田",
}

def _canonicalize_area(a):
    """area 名を正規港名へ統合（未登録はそのまま）。"""
    return _AREA_CANONICAL.get(a, a) if a else a

def _load_historical_catches():
    """data/V2/*.csv から全釣果を読み込み（V2正規化済み、約100,000行）
    修正 2026/04/16: data/*.csv (V1スタブ・数行のみ) ではなく
    data/V2/*.csv (active_version=V2、正規化済み全件) を参照するよう変更。
    V2はカラム名が tsuri_mono（旧: fish）。_build_catch_weather_index 側で吸収済み。

    2026/05/16 追記: chowari 等の直クロール由来CSV (hirono_YYYY-MM.csv 等) も
    同ディレクトリに置かれており、sorted(os.listdir) で自動的に取り込まれる。
    既存V2 39列 + 末尾に source 列を持つ40列スキーマ。各レコードの取得元は
    'source' 列で識別可能 ('釣りビジョン' / 'chowari/ひろの丸' 等)。
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
                    # chowari 系 CSV は欠損セルに文字列 "NULL" を書くため、表示に使う
                    # 名称フィールドは読み込み時に正規化する（魚種「NULL」がエリアページの
                    # fia-grid / 旬カレンダーに露出した 2026-06-10 のバグ対策）。
                    # tsuri_mono="NULL" は正規化失敗を意味するので既存の「不明」に揃える。
                    if row.get("tsuri_mono") == "NULL":
                        row["tsuri_mono"] = "不明"
                    for _pcol in ("point_place1", "point_place2", "point_place3"):
                        if row.get(_pcol) == "NULL":
                            row[_pcol] = ""
                    # エリア正規化（表示層・同一物理港の別名を統合）
                    row["area"] = _canonicalize_area(row.get("area", ""))
                    rows.append(row)
        except Exception:
            continue
    return rows

def _hist_is_cancelled(r):
    """hist_rows CSV 行が欠航または不明かどうか判定（compute_* 系関数用）"""
    return str(r.get("is_cancellation", "")).strip() == "1" or r.get("tsuri_mono") in ("欠航", "不明", "NULL", "")


def compute_fish_area_summary(hist_rows):
    """hist_rows から (fish, area) → 件数 の辞書を計算する（共有キャッシュ用）"""
    summary = {}
    for r in hist_rows:
        if _hist_is_cancelled(r):
            continue
        f = r.get("tsuri_mono")
        a = r.get("area")
        if f and a:
            key = (f, a)
            summary[key] = summary.get(key, 0) + 1
    return summary


def compute_fish_top_areas(hist_rows):
    """hist_rows から fish → [(area, cnt), ...] 件数降順 の辞書を計算する"""
    tmp = {}
    for r in hist_rows:
        if _hist_is_cancelled(r):
            continue
        f = r.get("tsuri_mono")
        a = r.get("area")
        if f and a:
            tmp.setdefault(f, {})
            tmp[f][a] = tmp[f].get(a, 0) + 1
    result = {}
    for f, ac in tmp.items():
        result[f] = sorted(ac.items(), key=lambda x: -x[1])
    return result


def compute_area_top_fishes(hist_rows):
    """hist_rows から area → [(fish, cnt), ...] 件数降順 の辞書を計算する"""
    tmp = {}
    for r in hist_rows:
        if _hist_is_cancelled(r):
            continue
        f = r.get("tsuri_mono")
        a = r.get("area")
        if f and a:
            tmp.setdefault(a, {})
            tmp[a][f] = tmp[a].get(f, 0) + 1
    result = {}
    for a, fc in tmp.items():
        result[a] = sorted(fc.items(), key=lambda x: -x[1])
    return result


def compute_fish_related_via_cooccurrence(hist_rows, fish, fish_top_areas_dict, top_n=6):
    """
    {fish} の主要エリアで同時期に釣れている魚種を共起便数降順で返す。
    戻り値: [(fish_name, cnt), ...] （fish/{slug}.html が存在するもののみ）
    fish_top_areas_dict: compute_fish_top_areas() の戻り値
    """
    top_areas = [a for a, _ in (fish_top_areas_dict.get(fish) or [])[:3]]
    if not top_areas:
        return []
    co_fish = {}
    for r in hist_rows:
        if _hist_is_cancelled(r):
            continue
        if r.get("area") in top_areas and r.get("tsuri_mono") != fish:
            f2 = r.get("tsuri_mono")
            if f2:
                co_fish[f2] = co_fish.get(f2, 0) + 1
    result = []
    for f2, n in sorted(co_fish.items(), key=lambda x: -x[1]):
        if f2 in _FISH_ROMAJI:
            result.append((f2, n))
        if len(result) >= top_n:
            break
    return result


def _display_today_str(now):
    """表示用の『今日』日付 (YYYY/MM/DD)。

    朝10時前 (0:00〜9:59) は前日を返す。船宿は釣果ブログを当日夕方〜翌日朝に
    投稿するため、深夜〜早朝にビルドした HTML では当日データが極端に少なく、
    HERO・ZONE B/B2・LIVE ティッカーが空表示になりやすい。
    表示用の『今日』を前日にシフトすることで、十分なデータがある日を基準に
    組まれる。10時以降は当日を返す。

    実日付（catches_raw 追記・dedup・x_post ファイル名など）には使わない。
    あくまで HTML 生成時の HERO 日付・概況・LIVE 等の表示基準のみ。
    """
    if now.hour < 10:
        return (now - timedelta(days=1)).strftime("%Y/%m/%d")
    return now.strftime("%Y/%m/%d")


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
    today_str = _display_today_str(now)
    cutoff = (datetime.strptime(today_str, "%Y/%m/%d") - timedelta(days=days-1)).strftime("%Y/%m/%d")
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
        # 釣りビジョン経由 (YYYY-MM.csv) + chowari 経由 (chowari_YYYY-MM.csv) を両方読み込み
        # 2026/05/17: 新規 chowari 船宿 (150隻) の直近7日データを fish/area HTML の
        # 「今週」「直近1週間」集計に反映するため
        paths = [
            os.path.join(data_dir, f"{ym}.csv"),
            os.path.join(data_dir, f"chowari_{ym}.csv"),
        ]
        for path in paths:
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
                            "area":        _canonicalize_area(row.get("area", "")),
                            "date":        d,
                            "fish":        guess_fish(fish_raw),
                            "fish_raw":    fish_raw,
                            "count_range": count_range,
                            "count_avg":   cavg,
                            "size_cm":     size_cm,
                            "weight_kg":   weight_kg,
                            "point_place1": row.get("point_place1", "") or None,
                            "is_cancellation": False,
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
        if f and f not in ("不明", "欠航", "NULL") and not f.isdigit():
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

# T31 (2026/05/12): 相対ポイント表記（南沖・近場・西沖等）を {port_short}+{方向} に正規化。
# 既存 point_coords.json の「茅ヶ崎西沖・大磯東沖・葉山西沖・富津南沖」等と同パターン。
# area → port_short マップ。area_coords.json で None の area も含むため独立マップ。
_AREA_TO_PORT_SHORT = {
    "葉山あぶずり港": "葉山",
    "小田原早川港": "小田原",
    "平塚港": "平塚",
    "茅ヶ崎港": "茅ヶ崎",
    "大磯港": "大磯",
    "御前崎港": "御前崎",
    "網代": "網代",
    "横浜港･新山下": "横浜",
    "横浜本牧港": "横浜",
    "江戸川放水路･原木中山": "江戸川",
    "下田港": "下田",
    "鴨居大室港": "鴨居",
    "松輪江奈港": "松輪",
    "松輪間口港": "松輪",
    "久里浜港": "久里浜",
    "久比里港": "久比里",
    "長井港": "長井",
    "長井新宿港": "長井",
    "長井漆山港": "長井",
    "小坪港": "小坪",
    "小柴港": "小柴",
    "金沢八景": "金沢八景",
    "佐島": "佐島",
    "鹿島港": "鹿島",
    "波崎港": "波崎",
    "日立久慈港": "日立",
    "大洗港": "大洗",
    "飯岡港": "飯岡",
    "外川港": "外川",
    "片貝港": "片貝",
    "大原港": "大原",
    "勝浦川津港": "勝浦",
    "御宿岩和田港": "御宿",
    "天津港": "天津",
    "太東港": "太東",
    "金谷港": "金谷",
    "保田港": "保田",
    "富浦港": "富浦",
    "富津港": "富津",
    "洲崎港": "洲崎",
    "長浦": "長浦",
    "浦安": "浦安",
    "東葛西": "葛西",
    "羽田": "羽田",
    "平和島": "平和島",
    "沼津内港": "沼津",
    "沼津静浦": "沼津",
    "田子の浦港": "田子の浦",
    "福田港": "福田",
    "松崎港": "松崎",
    "由比": "由比",
    "吉田港": "吉田",
}
# 相対ポイント表記（_UNRESOLVABLE_RE の主要部分・後置語含む）
_RELATIVE_POINT_RE = re.compile(r'^(近場周り|近場|南沖|東沖|西沖|北沖|河口沖|湾内|店前)$')

def _normalize_relative_point(pp, area):
    """相対ポイント表記を {port_short}+{方向} に書き換え（T31 2026/05/12）。

    pp が「南沖・近場・西沖」等のとき、area から port_short を取得して
    point_coords.json の既存「{port_short}+{方向}」エントリ名に変換する。
    変換できない場合は元のまま返す（area_coords フォールバックで対応継続）。
    """
    if not pp:
        return pp
    m = _RELATIVE_POINT_RE.match(pp.strip())
    if not m:
        return pp
    direction = m.group(1)
    if direction == "近場周り":
        direction = "近場"
    port_short = _AREA_TO_PORT_SHORT.get(area or "")
    if not port_short:
        return pp
    return port_short + direction

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

        # 日次の出船判定は「関東で最も荒れるエリア基準」(worst-case) に統一。
        # 各エリアを海域型ごとに判定し最も厳しい severity を採用 → トップのリスクグリッド(MAX)と整合。
        _day_sev = 0
        for _g, _fc in area_forecasts.items():
            _day_sev = max(_day_sev, _sail_severity(_fc.get("wave_height"), _fc.get("wind_speed"), _area_sea_type(_g)))
        _dcls, _dic, _dlb, score, _dcolor = _SAIL_LEVELS[_day_sev]
        ok_txt = f"{_dic} {_dlb}"
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

        # エリア別海況（出船判定はエリアの海域型で正準関数に統一）
        area_detail = {}
        for g, fc in area_forecasts.items():
            _asev, _acls, _aic, _alb, s, _acolor = _sail_judge(
                fc.get("wave_height"), fc.get("wind_speed"), _area_sea_type(g))
            area_detail[g] = {
                "wave": fc.get("wave_height"), "wind": fc.get("wind_speed"),
                "sst": fc.get("sst"), "wind_dir": fc.get("wind_dir"),
                "weather_text": fc.get("weather_text", ""),
                "pressure": fc.get("pressure"),
                "score": s, "ok": f"{_aic} {_alb}",
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
<link rel="icon" href="/favicon.ico" sizes="48x48"><link rel="apple-touch-icon" href="/apple-touch-icon.png">
<meta name="robots" content="noindex, follow">
<title>{title} | 船釣り予想</title>
{GA_TAG}
<link rel="stylesheet" href="{depth_prefix}style.css">
<style>{_FORECAST_EXTRA_CSS}</style>
</head><body>
{_v2_header_nav('forecast')}
<div class="c">
<p class="bread"><a href="/">トップ</a> &rsaquo; <a href="/forecast/">釣果予測</a> &rsaquo; {title}</p>
<h1 class="page-h1">{title}</h1>"""


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
<a href="/forecast/" class="paywall-btn">月額500円で全て見る</a>
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
<p style="font-size:14px;color:#fff;margin-bottom:4px">関東 総合判定（最も注意が必要なエリア基準）: {ok}</p>
<p style="font-size:12px;color:rgba(255,255,255,.7);margin-bottom:8px">※ エリアによって状況は異なります。下記エリア別の出船判定をご確認ください。</p>"""

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
    wb = _WAVE_BELTS[sea_type]
    nb = _WIND_BELTS[sea_type]
    note = f'△注意: 波{wb[1]}〜{wb[2]}m・風{nb[1]}〜{nb[2]}m/s / ✕欠航警戒: 波{wb[2]}m超・風{nb[2]}m/s超'
    return (
        f'<h2 class="st">出船リスク予報 <span class="tag free">無料</span></h2>'
        f'<p class="risk-note">判定（{sea_type}基準）: {note}</p>'
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
    """海況予報ハブ（無料の海況サマリー＋日次/週次ナビ＋釣果予測の案内）。
    海況は無料公開・釣果予測は各日ページで一部を無料プレビュー（フル版は拡充中）。"""
    html = _forecast_page_head("海況予報・釣果予測")
    all_dates = sorted(forecast_data.get("days", {}).keys())
    all_weeks = forecast_data.get("weeks", {})

    # 日次/週次ナビ（海況の実コンテンツページへ）
    html += _forecast_date_nav(all_dates, all_weeks, "")

    # 無料: 今週の海況サマリー（波高・風速・海水温・出船判定）
    html += '<h2>今週の海況（無料公開）</h2>'
    html += '<p class="section-note">関東の波高・風速・海水温・出船判定を無料で公開しています。<strong>出船判定は関東で最も注意が必要なエリアを基準</strong>に表示しています。日付をタップすると主要エリア別の詳細（エリアごとの出船可否）が見られます。</p>'
    if all_dates:
        html += '<table style="width:100%;border-collapse:collapse;font-size:13px;margin-bottom:10px">'
        html += ('<tr style="background:#0d2b4a;color:#fff">'
                 '<th style="padding:7px 6px;text-align:left">日付</th>'
                 '<th style="padding:7px 6px">出船判定</th>'
                 '<th style="padding:7px 6px">🌊波高</th>'
                 '<th style="padding:7px 6px">💨風速</th>'
                 '<th style="padding:7px 6px">🌡️海水温</th></tr>')
        for i, d in enumerate(all_dates):
            day = forecast_data["days"][d]
            m, dd = int(d[5:7]), int(d[8:10])
            wd = ["月", "火", "水", "木", "金", "土", "日"][datetime.strptime(d, "%Y-%m-%d").weekday()]
            wave = day.get("wave"); wind = day.get("wind"); sst = day.get("sst"); ok = day.get("ok", "")
            bg = "#ffffff" if i % 2 == 0 else "#f5f7fa"
            html += (f'<tr style="background:{bg};border-bottom:1px solid #e0e6ec">'
                     f'<td style="padding:7px 6px"><a href="{d}.html" style="font-weight:700">{m}/{dd}({wd})</a></td>'
                     f'<td style="padding:7px 6px;text-align:center">{ok}</td>'
                     f'<td style="padding:7px 6px;text-align:center">{wave if wave is not None else "-"}m</td>'
                     f'<td style="padding:7px 6px;text-align:center">{wind if wind is not None else "-"}m/s</td>'
                     f'<td style="padding:7px 6px;text-align:center">{sst if sst is not None else "-"}℃</td></tr>')
        html += '</table>'
        html += '<p class="section-note">各日付ページでは主要エリア別の海況と出船リスク（7日間）も確認できます。</p>'

    # 釣果予測の案内（各日ページで一部を無料プレビュー・フル版は拡充中）
    html += '''
<div style="background:linear-gradient(135deg,#f8f4ff,#f0eafa);border:2px solid #7c3aed;border-radius:14px;padding:28px 20px;margin:24px 0">
<h2 style="font-size:18px;color:#7c3aed;margin-bottom:10px;border:none;padding:0">魚種別 釣果予測</h2>
<p style="font-size:13px;color:#5a6a7a;line-height:1.9;margin-bottom:14px">
海況・潮通し・過去3年の実績データから算出する<strong>魚種別の釣果予測（匹数レンジ・サイズ・確信度）</strong>です。
各日付ページで<strong>上位予測を無料でプレビュー</strong>でき、全魚種・エリア別のフル版を順次拡充しています。
</p>
<ul style="font-size:13px;color:#5a6a7a;line-height:1.9;margin:0 0 14px 18px">
<li>日次予測: 匹数レンジ・サイズ・確信度・分析コメント</li>
<li>週次予測: 潮回り×季節傾向×直近実績</li>
<li>エリア別の出船リスク予報（7日間）</li>
</ul>
<p style="font-size:12px;color:#7c3aed;font-weight:700">フル版: 月額500円 / スポット100円〜（公開準備中）</p>
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
    """fish_raw 文字列から魚種を抽出してリスト返却。
    tsuri_mono_map_draft.json の 73 魚種に対応（旧 FISH_MAP は 24 魚種しか登録されておらず、
    シーバス・クロダイ・キンメダイ・ハナダイ・イシモチ・カンパチ等が「不明」になるバグを修正）。

    複数魚種が混在する場合は全て返す（既存仕様）。長いパターンを優先してマッチさせ、
    マッチした文字列を削除してから次を探すことで「クロダイ」→「タイ」誤マッチを防ぐ。
    """
    if not t:
        return ["不明"]
    # patterns を長さ降順で展開（長いパターン優先 → 「クロダイ」が「タイ」にマッチする前に消費）
    items = []
    for canon, patterns in TSURI_MONO_MAP.items():
        for p in patterns:
            items.append((canon, p))
    items.sort(key=lambda x: -len(x[1]))

    remaining = t
    found = []
    for canon, p in items:
        if p in remaining:
            if canon not in found:
                found.append(canon)
            remaining = remaining.replace(p, " ")
    return found or ["不明"]

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

def _cnt_personal(cr):
    """count_range を個人釣果として匹数集計に使えるか判定する。

    is_boat=False（catch_raw に「船中/合計/全体」なし）は常に個人。
    is_boat=True でも範囲表記 N〜M（min!=max）が取れていれば「個人レンジ＋船中合計」
    併記型（例「0〜14匹 船中302匹」）なので個人レンジとして含める。
    純船中（例「船中5匹」で min==max=船全体数）のみ匹数集計から除外する。
    実データ根拠（2026/06/01・crawl/catches_raw.json 126,392件）:
      個人レンジ併記 min!=max … 5,133件（含む）/ 純船中 min==max … 11,480件（除外）
    """
    if not cr:
        return False
    if not cr.get("is_boat"):
        return True
    lo, hi = cr.get("min"), cr.get("max")
    return lo is not None and hi is not None and lo != hi

def _cnt_personal_csv(r):
    """CSV行（data/V2/*.csv 由来 dict）を個人釣果として匹数集計に使えるか判定する。

    _cnt_personal（count_range dict 版）の CSV 版。当日 valid_catches を経ず hist_rows を
    直接ループする集計（FAQ 固定文章・area_cmp の長期フォールバック等）で使う。
    CSV には範囲表記が取れたか(ranged)を示す列が無いため、cnt_min != cnt_max を
    「個人レンジ＋船中合計」併記型（例「0〜14匹 船中302匹」）の代理判定に使う。

    is_boat≠1 は常に個人。is_boat=1 でも cnt_min != cnt_max なら個人レンジ併記として含める。
    純船中（is_boat=1 かつ cnt_min == cnt_max = 船全体数）のみ匹数集計から除外する。
    ⚠ 下限欠落型「〜14匹 船中58匹」（extract_count が min==max=14・約129件/0.1%）は
      この代理判定では取りこぼすが、低品質・他便でカバーされるため許容する。
    """
    ib = str(r.get("is_boat", "") or "").strip().lower()
    if ib not in ("1", "true"):
        return True
    cmin = r.get("cnt_min", "")
    cmax = r.get("cnt_max", "")
    if cmin in ("", None) or cmax in ("", None):
        return False
    try:
        return float(cmin) != float(cmax)
    except (ValueError, TypeError):
        return False

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
    # T31 (2026/05/12): ブラウザ風の自然なリクエストヘッダ。
    # Accept-Language: 日本語優先・Referer: 親ドメイン・Accept: HTML優先で fishing-v.jp の
    # 検知回避を強化（過去クロールスクリプトの一括実行時に使用）。
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
        "Accept-Encoding": "identity",
        "Referer": "https://www.fishing-v.jp/",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    }
    try:
        req = Request(url, headers=headers)
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
    # 旧 FISH_MAP (24魚種) では gyo.ne.jp のテキストでシーバス・クロダイ等が
    # 検出漏れしていた。TSURI_MONO_MAP (73魚種) ベースに変更（2026-05-10）
    all_fish = {}  # fish_name → canonical
    for canon, names in TSURI_MONO_MAP.items():
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

def load_fish_content():
    """normalize/fish_content.json（固定文・月1見直し）+ fish_content_stats.json（月1数値
    スナップショット）を読み、プレースホルダ解決済みの {fish: {section: html_text}} を返す。

    設計（2026-06-11）: 数値を毎日再計算すると固定プローズと数値が乖離して文意がズレる
    リスクがあるため、月1スナップショット方式（crawl/build_fish_content_stats.py で更新）。
    未解決プレースホルダが残るセクションは出力せず WARN（不変条件 #45 が最終ゲート）。
    """
    base = os.path.dirname(__file__) or "."
    try:
        with open(os.path.join(base, "normalize", "fish_content.json"), encoding="utf-8") as f:
            content = json.load(f)
    except Exception:
        return {}
    try:
        with open(os.path.join(base, "normalize", "fish_content_stats.json"), encoding="utf-8") as f:
            stats_all = (json.load(f) or {}).get("fish", {})
    except Exception:
        stats_all = {}
    _ph_re = re.compile(r"\{[a-z][a-z0-9_]*\}")

    class _KeepMissing(dict):
        def __missing__(self, key):
            return "{" + key + "}"

    out = {}
    for fish, entry in content.items():
        if fish.startswith("_") or not isinstance(entry, dict):
            continue
        st = _KeepMissing(stats_all.get(fish, {}))
        secs = {}
        for sec in ("howto", "tackle_detail", "season", "areas", "food", "beginner"):
            text = entry.get(sec) or ""
            if not text:
                continue
            rendered = text.format_map(st)
            if _ph_re.search(rendered):
                print(f"WARN: fish_content {fish}.{sec} に未解決プレースホルダ → セクション省略")
                continue
            secs[sec] = rendered
        if secs:
            out[fish] = secs
    return out

def load_area_description():
    """normalize/area_description.json を {area: {...}} で返す"""
    path = os.path.join("normalize", "area_description.json")
    if not os.path.exists(path): return {}
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except: return {}

def load_area_seo_alias():
    """normalize/area_seo_alias.json を {area: [別称, ...]} で返す。
    検索需要のある呼称ゆれ（例: 飯岡港⇔飯岡漁港）を本文/metaに自然注入し取りこぼしを防ぐ。"""
    path = os.path.join("normalize", "area_seo_alias.json")
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

# ships.json の romaji_slug で _SHIP_ROMAJI を拡張（chowari 船宿を含む全船宿を対象に）
for _s in SHIPS:
    _n = _s.get("name")
    _slug = _s.get("romaji_slug")
    if _n and _slug and _n not in _SHIP_ROMAJI:
        _SHIP_ROMAJI[_n] = _slug

# T38-A10: エリア→県マッピング（chip-pref 県emoji 表示用）
# docs/assets/area/{pref}_emoji.webp が存在する県のみ設定
# 茨城は emoji 未作成のため None（chip-pref img 出力スキップ）
AREA_TO_PREFECTURE = {
    # 神奈川（ships.json area 値ベース）
    '金沢八景': 'kanagawa', '横浜本牧港': 'kanagawa', '川崎': 'kanagawa',
    '久里浜港': 'kanagawa', '久里浜': 'kanagawa', '茅ヶ崎港': 'kanagawa',
    '茅ヶ崎': 'kanagawa', '小田原': 'kanagawa', '小田原早川港': 'kanagawa',
    '小田原早川': 'kanagawa',
    '下浦': 'kanagawa', '葉山': 'kanagawa', '葉山あぶずり港': 'kanagawa',
    '葉山鐙摺': 'kanagawa', '腰越': 'kanagawa',
    '平塚港': 'kanagawa', '平塚': 'kanagawa', '寒川港': 'kanagawa',
    '剣崎': 'kanagawa', '佐島': 'kanagawa', '横須賀': 'kanagawa',
    '久比里港': 'kanagawa', '久比里': 'kanagawa',
    '小坪港': 'kanagawa', '小柴港': 'kanagawa',
    '小網代港': 'kanagawa', '大磯港': 'kanagawa',
    '松輪': 'kanagawa', '松輪江奈港': 'kanagawa', '松輪間口港': 'kanagawa',
    '横浜港･新山下': 'kanagawa', '鴨居大室港': 'kanagawa',
    '長井': 'kanagawa', '長井港': 'kanagawa',
    '長井新宿港': 'kanagawa', '長井漆山港': 'kanagawa',
    '金沢漁港': 'kanagawa', '新安浦港': 'kanagawa', '磯子港': 'kanagawa',
    # 東京
    '羽田': 'tokyo', '深川': 'tokyo', '江戸川': 'tokyo',
    '平和島': 'tokyo', '東葛西': 'tokyo',
    # 千葉
    '金谷港': 'chiba', '浦安': 'chiba', '大原': 'chiba', '大原港': 'chiba',
    '勝山': 'chiba', '勝山港': 'chiba', '館山': 'chiba',
    '洲崎': 'chiba', '洲崎港': 'chiba', '勝浦': 'chiba',
    '勝浦川津港': 'chiba',  # 千葉県勝浦市川津
    '勝浦松部港': 'chiba',
    '片貝': 'chiba', '片貝港': 'chiba',
    '飯岡': 'chiba', '飯岡港': 'chiba',
    '鴨川': 'chiba', '和田浦': 'chiba',
    '富津': 'chiba', '富津港': 'chiba', '木更津': 'chiba', '千倉': 'chiba',
    '天津港': 'chiba', '富浦港': 'chiba',
    '御宿岩和田港': 'chiba', '長浦': 'chiba',
    '外川': 'chiba', '外川港': 'chiba',
    '江戸川放水路': 'chiba', '江戸川放水路･原木中山': 'chiba',
    '保田港': 'chiba',
    # 静岡
    '伊東': 'shizuoka', '熱海': 'shizuoka', '網代': 'shizuoka',
    '下田': 'shizuoka', '下田港': 'shizuoka', '稲取': 'shizuoka',
    '沼津': 'shizuoka', '沼津内港': 'shizuoka', '沼津静浦': 'shizuoka',
    '御前崎': 'shizuoka', '御前崎港': 'shizuoka', '南伊豆': 'shizuoka',
    '由比': 'shizuoka', '福田港': 'shizuoka',
    '宇佐美': 'shizuoka', '戸田': 'shizuoka',
    '田子の浦港': 'shizuoka',
    # 茨城
    '鹿島': 'ibaraki', '鹿島港': 'ibaraki', '鹿島市新浜': 'ibaraki',
    '鹿嶋新港': 'ibaraki', '鹿嶋旧港': 'ibaraki',
    '日立': 'ibaraki', '日立久慈港': 'ibaraki',
    '波崎': 'ibaraki', '波崎港': 'ibaraki', '波崎新港': 'ibaraki',
    '大洗': 'ibaraki', '大洗港': 'ibaraki',
    '久慈': 'ibaraki', '会瀬漁港': 'ibaraki',
    '平潟': 'ibaraki', '那珂湊港': 'ibaraki',
    # 千葉（追加）
    '江見': 'chiba', '江見漁港': 'chiba', '相浜': 'chiba', '浜行川': 'chiba',
    '伊戸': 'chiba',
    '江戸川区今井水門': 'tokyo', '江戸川区新今井橋': 'tokyo', '江戸川区鹿本橋': 'tokyo',
    # 東京（追加）
    '品川区品川堀': 'tokyo', '品川区立会川勝島運河': 'tokyo', '品川区鮫洲勝島運河': 'tokyo',
    '大田区六郷水門': 'tokyo', '大田区呑川': 'tokyo', '大田区海老取川': 'tokyo',
    '大田区羽田': 'tokyo',
    '江東区夢の島桟橋': 'tokyo', '江東区小名木川': 'tokyo', '江東区木場': 'tokyo',
    '江東区東京湾マリーナ': 'tokyo', '江東区釣船橋': 'tokyo',
    '港区京浜運河': 'tokyo', '足立区千住大橋': 'tokyo',
    # 神奈川（追加）
    '横浜港': 'kanagawa', '横浜': 'kanagawa', '横浜市八幡橋': 'kanagawa',
    '横浜市金沢八景乙舳': 'kanagawa', '横浜市金沢八景平潟': 'kanagawa',
    '佐島港': 'kanagawa', '柴漁港': 'kanagawa', '川名': 'kanagawa',
    '葉山町葉山鐙摺港': 'kanagawa', '平塚漁港': 'kanagawa',
    '腰越港': 'kanagawa', '片瀬漁港': 'kanagawa',
    '小田原新港': 'kanagawa', '早川漁港': 'kanagawa',
    '湯河原町福浦港': 'kanagawa', '真鶴町真鶴港': 'kanagawa',
    # 静岡（追加）
    '宇佐美港': 'shizuoka', '熱海港': 'shizuoka', '網代港': 'shizuoka',
    '戸又港': 'shizuoka', '戸田港': 'shizuoka', '久料港': 'shizuoka',
    '南伊豆町手石港': 'shizuoka', '松崎港': 'shizuoka', '松崎町松崎港': 'shizuoka',
    '西伊豆町安良里港': 'shizuoka', '清水港': 'shizuoka', '須崎港': 'shizuoka',
    '焼津港': 'shizuoka', '焼津小川港': 'shizuoka',
    '沼津市江の浦港': 'shizuoka', '静浦漁港': 'shizuoka', '寸座マリーナ': 'shizuoka',
    # 不明（住所未確認・None でスキップ）
    '大津港': None,
}

# 県スラグ → 表示用ラベル（img alt 属性等の SEO 用）
PREF_LABEL = {
    'kanagawa': '神奈川県',
    'tokyo':    '東京都',
    'chiba':    '千葉県',
    'shizuoka': '静岡県',
    'ibaraki':  '茨城県',
}


def _chip_pref_img(area, depth=1):
    """エリアに対応する県 emoji img タグを返す。マッピングなし・None なら空文字。
    depth: 相対パスの深さ（fish_area/ なら 1、area/ なら 1）
    alt 属性に県名（神奈川県/東京都/千葉県/静岡県/茨城県）を設定し SEO 強化。
    """
    pref = AREA_TO_PREFECTURE.get(area)
    if not pref:
        return ""
    prefix = "../" * depth
    label = PREF_LABEL.get(pref, "")
    return (
        f'<img src="{prefix}assets/area/{pref}_emoji.webp" alt="{label}" class="chip-pref"'
        f' width="14" height="14" loading="lazy" onerror="this.style.display=\'none\'">'
    )


def _fa_exists(fish, area):
    """docs/fish_area/{fish_slug}-{area_slug}.html が存在するか確認。Phase C で使用。"""
    fname = f"{fish_slug(fish)}-{area_slug(area)}.html"
    return os.path.exists(os.path.join(WEB_DIR, "fish_area", fname))


# H2 (T22): 空ページ（noindex 対象）の romaji_slug を蓄積するセット
# _ship_build_page_html() が書き込み、build_sitemap() が参照して URL 除外に使う
_SHIP_NOINDEX_SLUGS: set = set()

# T39 (2026/05/25): hist_count < 30 の薄い fish_area ページの slug stem ({fish}-{area}) を
# 蓄積するセット。build_fish_area_pages() が書き込み、build_sitemap() が参照して URL 除外。
# AdSense「有用性の低いコンテンツ」対策。
_FA_NOINDEX_SLUGS: set = set()
# 2026/06/16 AdSense「有用性の低いコンテンツ」再対策: 30→80 に引上げ。
# 過去3年で 80便（≒年27便）以上の実データを持つコンボのみ index+収益化し、
# それ未満はテンプレ穴埋めで実質薄ページのため noindex + 広告除去 + sitemap 除外。
# noindex ページには ADSENSE_TAG を出さない（build_fish_area_pages の広告ゲート）。
_FA_NOINDEX_HIST_THRESHOLD = 80

# T40 (2026/05/26): build_point_pages() が生成するポイント系 area ページ（赤灯沖・鹿島南沖等）は
# 自動生成ボイラープレートのみで fia-grid/season-map/海況 セクションを持たない構造的薄ページ。
# AdSense「有用性の低いコンテンツ」対策として全件 noindex 付与 + sitemap から除外。
_AREA_POINT_NOINDEX_SLUGS: set = set()

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

def _first_phone_for_tel(phone: str) -> str:
    """ships.json の phone は '0463-21-1312 / 070-4486-7173' のように複数番号入りの
    ことがある。区切り文字ごと数字だけ残すと番号が連結され無効な tel: になるため
    （2026-06-10 バグ: 23船宿で発生）、先頭の有効な1番号のみを tel: 用に返す。"""
    # 区切りは空白も含む（"0463-21-1312 070-4486-7173" のようなスペースのみ区切り対策・
    # code-reviewer 指摘 2026-06-10）。単一番号内の空白（"03 1234 5678"）は各 chunk が
    # 9 桁未満になりフォールバックで全体から数字抽出されるため正しく1番号に復元される。
    for chunk in re.split(r"[\s/／,、・]+", phone or ""):
        digits = re.sub(r"[^\d+\-]", "", chunk)
        if len(re.sub(r"\D", "", digits)) >= 9:  # 日本の電話番号は9〜11桁
            return digits
    return re.sub(r"[^\d+\-]", "", phone or "")

_FISH_ASSET_DIRS: set | None = None

def _fish_asset_img_slug(fish: str) -> str:
    """画像パス用スラグ。docs/assets/fish/ にフォルダが実在する場合のみ返し、
    無ければ "" を返す（img タグ自体を出さず 404 リクエストを防ぐ）。
    ship ページ系が URL スラグ（kihada-maguro）を画像フォルダ名（kihadamaguro）と
    取り違えて大量の画像 404 を出していた 2026-06-10 のバグ対策。"""
    global _FISH_ASSET_DIRS
    if _FISH_ASSET_DIRS is None:
        _d = os.path.join(WEB_DIR, "assets", "fish")
        _FISH_ASSET_DIRS = set(os.listdir(_d)) if os.path.isdir(_d) else set()
    slug = fish_img_slug(fish)
    return slug if slug in _FISH_ASSET_DIRS else ""

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
    fish_rel = f"fish/{fish_slug(fish)}.html"
    if os.path.exists(os.path.join(WEB_DIR, fish_rel)):
        return f"{prefix}{fish_rel}"
    # 魚種ページも無い場合（アカイカ・コハダ等のページ未生成魚種）は魚種一覧へ
    # フォールバック（リンク切れ防止・2026-06-10）
    return f"{prefix}fish/"

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
header .brand{font-size:19px;font-weight:700}header .brand span{color:var(--cta)}a.site-logo{text-decoration:none;color:inherit}a.site-logo:hover{opacity:.8;text-decoration:none}
header .domain{font-size:11px;opacity:.5}
nav.gnav{background:var(--nav);padding:7px 20px;display:flex;gap:6px;flex-wrap:wrap;justify-content:center;border-bottom:1px solid var(--border)}
nav.gnav a{color:var(--sub);font-size:12px;font-weight:600;padding:5px 12px;border-radius:16px}
nav.gnav a:hover,nav.gnav a.on{background:var(--accent);color:#fff;text-decoration:none}
nav.gnav a.prem{color:var(--prem)}
nav.gnav a.prem::before{content:"";display:inline-block;width:8px;height:8px;background:var(--prem);border-radius:50%;margin-right:4px;vertical-align:middle}
nav.gnav a .nav-new{display:inline-block;background:var(--cta);color:#fff;font-size:9px;font-weight:700;padding:1px 5px;border-radius:8px;margin-left:5px;vertical-align:middle;letter-spacing:.04em}
nav.gnav a:hover .nav-new,nav.gnav a.on .nav-new{background:#fff;color:var(--cta)}
nav.gnav .nav-disabled{color:var(--border);font-size:12px;font-weight:600;padding:5px 12px;cursor:default}
.st{font-size:15px;font-weight:700;color:var(--accent);padding:18px 0 8px;border-bottom:2px solid var(--accent);margin-bottom:12px;display:flex;align-items:center;gap:8px}
.st.teaser-title{color:var(--prem);border-color:var(--prem)}
.st .tag{font-size:9px;padding:2px 7px;border-radius:8px;color:#fff;font-weight:700}
.st .tag.free{background:var(--pos)}.st .tag.coming{background:var(--prem)}
.ad-slot{background:#f0f0f0;border:1px dashed #ccc;border-radius:var(--r);padding:22px;text-align:center;margin:16px 0;font-size:11px;color:#999}
.bread{font-size:11px;color:var(--muted);padding:10px 0;line-height:1.6}.bread a{color:var(--sub)}.bread .bread-sep{white-space:nowrap;display:inline-block;padding:0 4px;color:var(--muted)}
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
.sm-fish-title{display:flex;align-items:center;gap:6px;font-size:14px;font-weight:700;color:var(--accent);margin-bottom:6px}
.sm-fish-emoji{vertical-align:middle;width:20px;height:20px;object-fit:contain}
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

def _stale_banner_html():
    """全ページ共通の鮮度バナー（ビルド日付 + JS）を返す。

    CDN/ブラウザキャッシュで古い版を見た場合でも、JS が「このページの生成日」と
    閲覧者の今日を比較し、2日以上古ければ「更新遅延」を表示する（ページ種別ごとの
    キャッシュ齟齬対策・2026-06-07）。生成時刻 = ビルド時刻なので now() でよい。
    """
    _now = datetime.now(JST)
    _bd_iso = _now.strftime("%Y-%m-%d")
    _bt_ms = int(_now.timestamp() * 1000)  # ビルド時刻（UTC epoch ms・TZ非依存）
    # 判定はビルド時刻からの経過時間で行う（日付だけの比較は UTC/JST 境界で誤警告が出る）。
    # crawl は日次（遅延込みで最長 ~28h 間隔）なので、36h 超 = 1日分まるごと欠落＝真の遅延。
    return f"""<div id="stale-banner" role="alert" hidden style="background:#b3261e;color:#fff;padding:9px 14px;text-align:center;font-size:13px;line-height:1.5;font-weight:600">
  ⚠️ このページは更新が遅延している可能性があります（生成日: {_bd_iso}）。<a href="/" style="color:#fff;text-decoration:underline">トップで最新の釣果を確認</a>
</div>
<script>
(function(){{
  var b="{_bd_iso}";var bt={_bt_ms};
  if((Date.now()-bt)>129600000){{var e=document.getElementById("stale-banner");if(e)e.hidden=false;}}
}})();
</script>
"""

def _v2_header_nav(active_page=""):
    """V2共通ヘッダー + グローバルナビ

    全ページにビルド日付ベースの鮮度バナーを注入する（_stale_banner_html）。
    """
    stale_banner = _stale_banner_html()
    return f"""{stale_banner}<header>
  <div class="inner">
    <a href="/" class="site-logo"><span class="brand">船釣り<span>予想</span></span></a>
    <span class="domain">funatsuri-yoso.com</span>
  </div>
</header>
<nav class="gnav">
  <a href="/"{' class="on"' if active_page == 'index' else ''}>今日の釣果</a>
  <a href="/x_post/"{' class="on"' if active_page == 'xpost' else ''}>釣果速報</a>
  <a href="/fish/"{' class="on"' if active_page == 'fish' else ''}>魚種</a>
  <a href="/area/"{' class="on"' if active_page == 'area' else ''}>エリア</a>
  <a href="/calendar.html"{' class="on"' if active_page == 'calendar' else ''}>カレンダー</a>
  <a href="/monthly/"{' class="on"' if active_page == 'monthly' else ''}>月報</a>
  <a href="/komase-sim/"{' class="on"' if active_page == 'komasim' else ''}>🎣 コマセsim<span class="nav-new">NEW</span></a>

  {('<a href="/forecast/" class="prem' + (' on' if active_page == 'forecast' else '') + '">有料プラン</a>') if SHOW_PAID_TEASER else ''}
</nav>"""

def _v2_footer(crawled_at=""):
    return f"""<footer>
  <div>© 2026 船釣り予想 (funatsuri-yoso.com)</div>
  <div class="fl">
    <a href="/pages/about.html">サイトについて</a>
    <a href="/pages/privacy.html">プライバシーポリシー</a>
    <a href="/pages/terms.html">利用規約</a>
    <a href="/pages/contact.html">お問い合わせ</a>
    <a href="/pages/faq.html">よくある質問</a>
  </div>
</footer>"""

def _v2_bottom_nav(active_page=""):
    icons = {
        "index":  '<svg viewBox="0 0 24 24"><path d="M2 12c3-5 8-7 13-5 2 1 4 3 5 5-1 2-3 4-5 5-5 2-10 0-13-5z"/><circle cx="16" cy="11" r=".8" fill="currentColor" stroke="none"/><path d="M20 12l2-2M20 12l2 2"/></svg>',
        "xpost":  '<svg viewBox="0 0 24 24"><rect x="3" y="5" width="18" height="14" rx="2"/><path d="M3 9h18"/><circle cx="7" cy="14" r="1.2" fill="currentColor" stroke="none"/><line x1="10" y1="14" x2="17" y2="14"/><line x1="10" y1="11" x2="17" y2="11"/></svg>',
        "fish":   '<svg viewBox="0 0 24 24"><line x1="4" y1="7" x2="20" y2="7"/><line x1="4" y1="12" x2="20" y2="12"/><line x1="4" y1="17" x2="20" y2="17"/><circle cx="4" cy="7" r="1" fill="currentColor" stroke="none"/><circle cx="4" cy="12" r="1" fill="currentColor" stroke="none"/><circle cx="4" cy="17" r="1" fill="currentColor" stroke="none"/></svg>',
        "area":   '<svg viewBox="0 0 24 24"><path d="M12 2c-4 0-7 3-7 7 0 5 7 13 7 13s7-8 7-13c0-4-3-7-7-7z"/><circle cx="12" cy="9" r="2.5"/></svg>',
        "cal":    '<svg viewBox="0 0 24 24"><rect x="4" y="5" width="16" height="16" rx="2"/><line x1="4" y1="10" x2="20" y2="10"/><line x1="9" y1="3" x2="9" y2="7"/><line x1="15" y1="3" x2="15" y2="7"/></svg>',
        "prem":   '<svg viewBox="0 0 24 24"><path d="M3 8l4 4 5-7 5 7 4-4v11H3z"/><line x1="3" y1="19" x2="21" y2="19"/></svg>',
    }
    items = [
        ("index", "/",                    "釣果",     ""),
        ("xpost", "/x_post/",  "速報",     ""),
        ("fish",  "/fish/",              "魚種",     ""),
        ("area",  "/area/",              "エリア",   ""),
        ("cal",   "/calendar.html",      "カレンダー", ""),
        ("prem",  "/forecast/", "有料",    "prem"),
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
    today_str = _display_today_str(now)
    cutoff_str = (datetime.strptime(today_str, "%Y/%m/%d") - timedelta(days=6)).strftime("%Y/%m/%d")
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
    # 先週同期間 (8〜14日前。表示用 today を基準にずらす)
    prev_now = now - timedelta(days=7)
    try:
        prev_recs = _load_recent_catches_for_index(prev_now, days=7)
    except Exception:
        prev_recs = []
    prev_today = _display_today_str(prev_now)
    prev_cutoff = (datetime.strptime(prev_today, "%Y/%m/%d") - timedelta(days=6)).strftime("%Y/%m/%d")
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


def build_surge_combos_html(catches_for_summary, history, now):
    """今週の急上昇 魚×エリア TOP3 — 先週比（便数）でランキング（2026/06/16）。
    build_top_combos_html（件数主体）と相補。こちらは「先週より急に報告が増えたコンボ」を
    可視化し、サイトの"予想・分析"価値を一目で伝える。
    信頼性最優先: 先週・今週とも一定便数（distinct ship×date）を満たすコンボのみ対象とし、
    少数ベースの偽の急騰（例 1→6便で+500%）を除外。% に実数を併記して透明性を担保する。
    無料=事実 境界遵守: 便数・先週比のみ（理由解釈・★評価は載せない）。
    """
    # 信頼性フィルタ閾値: 先週ベース・今週ベース・最低上昇率
    PREV_MIN, CUR_MIN, SURGE_MIN_PCT = 3, 5, 50
    today_str = _display_today_str(now)
    cutoff_str = (datetime.strptime(today_str, "%Y/%m/%d") - timedelta(days=6)).strftime("%Y/%m/%d")
    combo = {}
    for c in catches_for_summary:
        d = c.get("date")
        if not d or d < cutoff_str or d > today_str:
            continue
        for f in c.get("fish", []):
            if f == "不明":
                continue
            combo.setdefault((f, c.get("area")), set()).add((c.get("ship"), d))
    if not combo:
        return ""
    # 先週同期間（8〜14日前）
    prev_now = now - timedelta(days=7)
    try:
        prev_recs = _load_recent_catches_for_index(prev_now, days=7)
    except Exception:
        prev_recs = []
    prev_today = _display_today_str(prev_now)
    prev_cutoff = (datetime.strptime(prev_today, "%Y/%m/%d") - timedelta(days=6)).strftime("%Y/%m/%d")
    prev_combo = {}
    for c in prev_recs:
        d = c.get("date")
        if not d or d < prev_cutoff or d > prev_today:
            continue
        for f in c.get("fish", []):
            if f == "不明":
                continue
            prev_combo.setdefault((f, c.get("area")), set()).add((c.get("ship"), d))
    surges = []
    for key, recs in combo.items():
        cnt = len(recs)
        prev_cnt = len(prev_combo.get(key, set()))
        if prev_cnt < PREV_MIN or cnt < CUR_MIN:
            continue
        pct = (cnt - prev_cnt) / prev_cnt * 100
        if pct < SURGE_MIN_PCT:
            continue
        surges.append((key, cnt, prev_cnt, round(pct)))
    if not surges:
        return ""
    surges.sort(key=lambda x: -x[3])
    cards = []
    for (fish, area), cnt, prev_cnt, pct_int in surges[:3]:
        target = _fish_area_link_or_fish(fish, area, depth=0)
        cards.append(
            f'<a class="topc-card" href="{target}">'
            f'<div class="topc-fish"><img src="assets/fish/{fish_img_slug(fish)}/{fish_img_slug(fish)}_emoji.webp" '
            f'alt="" class="topc-emoji" width="20" height="20" loading="lazy" decoding="async" '
            f'onerror="this.style.display=\'none\'">{fish} × {area}</div>'
            f'<div class="topc-stats"><span class="topc-wow up">先週比 +{pct_int}%</span> '
            f'先週{prev_cnt}→今週{cnt}件</div>'
            f'</a>'
        )
    return (
        '<h2 class="st">🔥 今週の急上昇 魚×エリア <span class="tag free">無料</span>'
        '<span class="topc-period">先週比・直近1週間</span></h2>'
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
    <div class="teaser-cta-btns"><a class="cta-btn" href="/forecast/">今週末、どこに乗るべきか見る → 1回100円</a></div>
    <div class="teaser-price">※ 全機能まとめて <em>月額500円</em> / スポット <em>1回100円</em></div>
  </div>
</div>"""

def build_index_overview_text(catches, history, crawled_at="", hero_label=""):
    """今日の関東船釣り概況テキスト（200〜300字）を生成"""
    now = datetime.now(JST).replace(tzinfo=None)
    today_str = _display_today_str(now)
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
        f"{label}の関東全域で{total}便の釣果報告が寄せられました（{len(areas_set)}エリア・{len(ships_set)}船宿）。"
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

def _render_season_map_block(fish, cnt_levels, size_levels, ths, source_note, depth=1, show_legend=True):
    """旬カレンダーの共通レンダリング（魚種名+アイコン見出し + 数釣/型釣 行 + 凡例 + 出典）。
    型データが全て 0（lv==0）の場合は「型釣」行を省略する。
    show_legend=False で凡例・出典を省略（複数魚種を並べる場合に最後にまとめて表示するため）。"""
    cnt_cells  = "".join(f'<td class="sm-cell" data-v="{lv}"></td>' for lv in cnt_levels)
    size_row_html = ""
    if any(lv > 0 for lv in size_levels):
        size_cells = "".join(f'<td class="sm-cell" data-v="{lv}"></td>' for lv in size_levels)
        size_row_html = f'<tr><th class="sm-th-mo">型釣</th>{size_cells}</tr>'
    fish_emoji_src = ("../" * depth if depth > 0 else "") + f"assets/fish/{fish_img_slug(fish)}/{fish_img_slug(fish)}_emoji.webp"
    legend_html = ""
    if show_legend:
        legend_html = f"""  <div class="sm-legend">
    <span>釣れ具合：</span>
    <span class="sm-lc sm-lc-0"></span>なし
    <span class="sm-lc sm-lc-1"></span>渋
    <span class="sm-lc sm-lc-2"></span>普通
    <span class="sm-lc sm-lc-3"></span>良
    <span class="sm-lc sm-lc-4"></span>◎
  </div>
  <p style="font-size:11px;color:var(--muted);margin-top:6px">※ {source_note}</p>"""
    return f"""<div class="season-map">
  <div class="sm-fish-title"><img src="{fish_emoji_src}" alt="{fish}" class="sm-fish-emoji" width="20" height="20" loading="lazy" decoding="async" onerror="this.style.display='none'">{fish}</div>
  <div class="sm-wrap">
    <table class="sm-table">
      <thead><tr><th style="width:28px"></th>{ths}</tr></thead>
      <tbody>
        <tr><th class="sm-th-mo">数釣</th>{cnt_cells}</tr>
        {size_row_html}
      </tbody>
    </table>
  </div>
{legend_html}
</div>"""


def build_combo_season_map_html(fish, area, hist_rows, current_month=None, decadal_calendar=None):
    """fish × area の旬カレンダー（数釣/型釣 × 12ヶ月 ヒートマップ）。
    fish_area ページ用に build_fish_season_map_html と同じフォーマットでコンボ別件数を描画する。
    型データはコンボ別 size_max 集計から計算（データ無ければ型釣行省略）。

    優先順位:
    1. hist_rows × area で fish×area の月別件数（max>=3）
    2. hist_rows × 全エリアで fish 全体の月別件数（コンボ件数不足時の fallback）
    3. decadal_calendar / SEASON_DATA fallback（build_fish_season_map_html に委譲）
    """
    month_labels = ["1月","2月","3月","4月","5月","6月","7月","8月","9月","10月","11月","12月"]
    ths = "".join(f"<th>{m}</th>" for m in month_labels)
    counts = compute_combo_month_records(fish, area, hist_rows) if hist_rows else [0] * 12
    max_v = max(counts) if any(counts) else 0
    if max_v < 3:
        # コンボ件数が少ない場合は fish 全体の月別件数 fallback
        return build_fish_season_map_html(fish, decadal_calendar, current_month, hist_rows=hist_rows)
    # 数釣レベル: cnt 件数の正規化
    cnt_levels = []
    for i in range(12):
        cnt = counts[i]
        ratio = cnt / max_v if max_v else 0
        if ratio >= 0.7:    lv = 4
        elif ratio >= 0.4:  lv = 3
        elif ratio >= 0.15: lv = 2
        elif cnt > 0:       lv = 1
        else:               lv = 0
        cnt_levels.append(lv)
    # 型釣レベル: size_max を持つレコードの月別件数を正規化
    size_counts = compute_combo_month_size_records(fish, area, hist_rows) if hist_rows else [0] * 12
    size_max_v = max(size_counts) if any(size_counts) else 0
    size_levels = []
    for i in range(12):
        if size_max_v < 3:
            size_levels.append(0)
            continue
        sz = size_counts[i]
        ratio = sz / size_max_v if size_max_v else 0
        if ratio >= 0.7:    lv = 4
        elif ratio >= 0.4:  lv = 3
        elif ratio >= 0.15: lv = 2
        elif sz > 0:        lv = 1
        else:               lv = 0
        size_levels.append(lv)
    return _render_season_map_block(fish, cnt_levels, size_levels, ths, f"{area}での{fish}釣果データから集計（過去3年）", depth=1)


def build_fish_season_map_html(fish, decadal_calendar, current_month=None, hist_rows=None):
    """魚種の旬カレンダー（12か月×数釣/型釣 ヒートマップ）。
    優先順位（2026/05/06 改修）:
    1. hist_rows（CSV から fish 全エリア合算の月別件数を計算）← 最優先
    2. decadal_calendar（analysis.sqlite 由来・cnt_index/size_index）
    3. SEASON_DATA + SEASON_TYPE（ハードコード fallback）

    型釣レベルは hist_rows の size_max を持つレコード月別件数から実データ計算。データなし時は型行省略。
    """
    fish_decades = decadal_calendar.get(fish, {}) if decadal_calendar else {}
    month_labels = ["1月","2月","3月","4月","5月","6月","7月","8月","9月","10月","11月","12月"]
    ths = "".join(f"<th>{m}</th>" for m in month_labels)
    source_note = "過去3年の関東船釣り釣果データより集計（2023年〜）"
    # ヘルパー: counts/max から levels (1..4) 配列を構築
    def _counts_to_levels(counts, max_v):
        out = []
        for i in range(12):
            cnt = counts[i]
            ratio = cnt / max_v if max_v else 0
            if ratio >= 0.7:    lv = 4
            elif ratio >= 0.4:  lv = 3
            elif ratio >= 0.15: lv = 2
            elif cnt > 0:       lv = 1
            else:               lv = 0
            out.append(lv)
        return out
    # 2026/05/06: hist_rows を最優先で使用
    hist_counts = None
    if hist_rows:
        hc = compute_fish_month_records(fish, hist_rows)
        if max(hc) >= 5:
            hist_counts = hc
    if hist_counts is not None:
        cnt_levels = _counts_to_levels(hist_counts, max(hist_counts))
        # 型レベル: hist_rows から size_max を持つレコード月別件数を正規化
        size_counts = compute_fish_month_size_records(fish, hist_rows)
        size_max_v = max(size_counts) if any(size_counts) else 0
        size_levels = _counts_to_levels(size_counts, size_max_v) if size_max_v >= 3 else [0] * 12
        return _render_season_map_block(fish, cnt_levels, size_levels, ths, source_note, depth=1)
    if not fish_decades:
        # SEASON_DATA + SEASON_TYPE fallback（hist_rows も decadal_calendar も無い場合）
        scores = SEASON_DATA.get(fish, [3] * 12)
        types  = SEASON_TYPE.get(fish, [""] * 12)
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
        return _render_season_map_block(fish, cnt_levels, size_levels, ths, source_note, depth=1)
    cnt_levels   = _decadal_to_monthly_index(fish_decades)
    size_levels  = _decadal_to_monthly_size_index(fish_decades)
    return _render_season_map_block(fish, cnt_levels, size_levels, ths, source_note, depth=1)

def build_area_season_map_html(area, area_decadal, top_fish_list, hist_rows=None):
    """エリアの魚種別旬カレンダー。
    各魚種ごとに「{魚種アイコン}{魚種名} + 数釣 + 型釣」のブロックを並べる
    （fish/* fish_area/* の旬カレンダーと同じフォーマットで統一）。
    型データが無い魚種は型釣行を省略。

    データソース優先順位:
    1. hist_rows（CSV から fish×area の月別件数を計算）← 最優先
    2. area_decadal（analysis.sqlite 由来・cnt_index 集計値）
    3. SEASON_DATA（ハードコード fallback）
    """
    area_data = area_decadal.get(area) if area_decadal else None
    if area_data is None:
        region = _port_to_analysis_region(area)
        area_data = area_decadal.get(region, {}) if (area_decadal and region) else {}
    month_labels = ["1月","2月","3月","4月","5月","6月","7月","8月","9月","10月","11月","12月"]
    ths = "".join(f"<th>{m}</th>" for m in month_labels)
    blocks_html = ""
    for fish in top_fish_list[:6]:
        # 数釣 cnt_levels: hist_rows 優先 → area_decadal → SEASON_DATA fallback
        cnt_levels = []
        hist_counts = None
        if hist_rows:
            hc = compute_combo_month_records(fish, area, hist_rows)
            if max(hc) >= 3:
                hist_counts = hc
        fish_decades = area_data.get(fish, {})
        if hist_counts is not None:
            max_v = max(hist_counts)
            for i in range(12):
                cnt = hist_counts[i]
                ratio = cnt / max_v if max_v else 0
                if ratio >= 0.7:    lv = 4
                elif ratio >= 0.4:  lv = 3
                elif ratio >= 0.15: lv = 2
                elif cnt > 0:       lv = 1
                else:               lv = 0
                cnt_levels.append(lv)
        elif fish_decades:
            for m in range(1, 13):
                d1 = (m - 1) * 3 + 1
                raw_vals = [fish_decades.get(d) for d in (d1, d1 + 1, d1 + 2)]
                present = [v for v in raw_vals if v is not None]
                if not present:
                    sd = SEASON_DATA.get(fish)
                    lv = max(0, min(4, sd[m - 1] - 1)) if sd else 0
                else:
                    avg = sum(present) / len(present)
                    if avg >= 160:   lv = 4
                    elif avg >= 130: lv = 3
                    elif avg >= 90:  lv = 2
                    elif avg >= 50:  lv = 1
                    else:            lv = 0
                cnt_levels.append(lv)
        else:
            sd = SEASON_DATA.get(fish)
            for m in range(1, 13):
                lv = max(0, min(4, sd[m - 1] - 1)) if sd else 0
                cnt_levels.append(lv)
        # 全部 0 ならスキップ
        if all(lv == 0 for lv in cnt_levels):
            continue
        # 型釣 size_levels: hist_rows から実データ計算（無ければ全0 → 型行省略）
        size_levels = [0] * 12
        if hist_rows:
            size_counts = compute_combo_month_size_records(fish, area, hist_rows)
            size_max_v = max(size_counts) if any(size_counts) else 0
            if size_max_v >= 3:
                for i in range(12):
                    sz = size_counts[i]
                    ratio = sz / size_max_v if size_max_v else 0
                    if ratio >= 0.7:    lv = 4
                    elif ratio >= 0.4:  lv = 3
                    elif ratio >= 0.15: lv = 2
                    elif sz > 0:        lv = 1
                    else:               lv = 0
                    size_levels[i] = lv
        # 凡例は最後にまとめて表示するため show_legend=False
        blocks_html += _render_season_map_block(
            fish, cnt_levels, size_levels, ths,
            f"{area}での{fish}釣果データから集計（過去3年）",
            depth=1, show_legend=False
        )
    if not blocks_html:
        return ""
    # 全体凡例 + 出典を最後に1回表示
    return f"""{blocks_html}
<div class="sm-legend" style="margin-top:0;padding:8px 14px;background:var(--card);border:1px solid var(--border);border-radius:var(--r);margin-bottom:16px">
  <span>釣れ具合：</span>
  <span class="sm-lc sm-lc-0"></span>なし
  <span class="sm-lc sm-lc-1"></span>渋
  <span class="sm-lc sm-lc-2"></span>普通
  <span class="sm-lc sm-lc-3"></span>良
  <span class="sm-lc sm-lc-4"></span>◎
  <span style="margin-left:auto;font-size:10px">※ 過去3年の釣果データより集計（2023年〜）</span>
</div>"""

def build_fish_guide_html(fish, tackle_data, content=None):
    """魚種ガイドセクション（釣り方・タックル・サイズ・外道・出船率）

    2026-06-11 拡張:
    - タックルが複数釣法/エリアに分かれている場合は **全バリアントをラベル付きで表示**
      （旧仕様は最初の一つだけ表示 → ブランコ/直結の2キー魚種で片方が見えなかった）。
      エリアでタックルが別物になる魚種（マルイカ等）はキー名に「釣法（対応エリア）」を書く。
    - content（load_fish_content() の魚種別固定文）があれば、釣り方/タックル補足/食味/
      初心者向けのプローズを差し込む（不変条件 #45 対象・class="fish-content-text"）。
    """
    td = tackle_data.get(fish) if tackle_data else None
    if not td:
        return ""
    content = content or {}
    method = td.get("method_detail") or td.get("method_name") or ""
    size_info = td.get("size_typical", {})
    if isinstance(size_info, dict):
        size_text = size_info.get("text", "")
    else:
        size_text = str(size_info)
    bycatch = td.get("bycatch") or []
    bycatch_text = "・".join(bycatch) if bycatch else ""
    notes = td.get("notes") or ""
    # タックル表示（全バリアント）
    tackle = td.get("tackle") or {}
    tackle_html = ""
    if isinstance(tackle, dict):
        variants = []
        show_label = len(tackle) >= 2
        for vkey, t in tackle.items():
            if not isinstance(t, dict):
                continue
            rod   = t.get("rod", "")
            reel  = t.get("reel", "")
            line  = t.get("line", "")
            rig   = t.get("rig", "")
            bait  = t.get("bait", "")
            label = f'<div class="tk-variant-label">{vkey}</div>' if show_label else ""
            variants.append(f"""<div class="tk-variant">{label}<div class="tackle-grid">
          <div class="tk"><div class="tk-lbl">竿</div><div class="tk-val">{rod}</div></div>
          <div class="tk"><div class="tk-lbl">リール</div><div class="tk-val">{reel}</div></div>
          <div class="tk"><div class="tk-lbl">ライン</div><div class="tk-val">{line}</div></div>
          <div class="tk"><div class="tk-lbl">仕掛け</div><div class="tk-val">{rig}</div></div>
          <div class="tk" style="grid-column:span 2"><div class="tk-lbl">エサ</div><div class="tk-val">{bait}</div></div>
        </div></div>""")
        tackle_html = "".join(variants)
    rows = ""
    if content.get("howto"):
        rows += f'<div class="fg-row"><span class="fg-lbl">釣り方</span><span class="fg-val fish-content-text">{content["howto"]}</span></div>'
    elif method:
        rows += f'<div class="fg-row"><span class="fg-lbl">釣り方</span><span class="fg-val">{method}</span></div>'
    if tackle_html:
        rows += f'<div class="fg-row"><span class="fg-lbl">タックル</span><span class="fg-val">{tackle_html}</span></div>'
    if content.get("tackle_detail"):
        rows += f'<div class="fg-row"><span class="fg-lbl">タックル補足</span><span class="fg-val fish-content-text">{content["tackle_detail"]}</span></div>'
    if size_text:
        rows += f'<div class="fg-row"><span class="fg-lbl">サイズ目安</span><span class="fg-val"><strong>{size_text}</strong></span></div>'
    if bycatch_text:
        rows += f'<div class="fg-row"><span class="fg-lbl">外道</span><span class="fg-val">{bycatch_text}</span></div>'
    if content.get("food"):
        rows += f'<div class="fg-row"><span class="fg-lbl">食味・持ち帰り</span><span class="fg-val fish-content-text">{content["food"]}</span></div>'
    elif notes:
        rows += f'<div class="fg-row"><span class="fg-lbl">メモ</span><span class="fg-val">{notes}</span></div>'
    if content.get("beginner"):
        rows += f'<div class="fg-row"><span class="fg-lbl">初心者向け</span><span class="fg-val fish-content-text">{content["beginner"]}</span></div>'
    if not rows:
        return ""
    _g_emoji = (f'<img src="../assets/fish/{fish_img_slug(fish)}/{fish_img_slug(fish)}_emoji.webp" alt="" '
                f'class="fg-emoji" width="16" height="16" loading="lazy" decoding="async" '
                f'onerror="this.style.display=\'none\'">')
    return f"""<div class="fish-guide" id="fish-guide">
  <h3>{_g_emoji}{fish}の船釣り（関東）基本情報</h3>
  {rows}
</div>"""

def _latest_monthly_report_link(fish):
    """docs/monthly/YYYY-MM/{slug}.html が存在する最新月の (url, label) を返す。無ければ None。

    月報は MONTHLY_FISH_CONFIG の対象魚種のみ生成されるため、実在ファイル確認で判定する
    （存在しない月報への空リンク・「準備中」リンクは出さない 2026-06-11 方針）。
    """
    slug = fish_slug(fish)
    mdir = os.path.join(WEB_DIR, "monthly")
    if not os.path.isdir(mdir):
        return None
    for d in sorted(os.listdir(mdir), reverse=True):
        if len(d) == 7 and d[4] == "-" and os.path.isfile(os.path.join(mdir, d, f"{slug}.html")):
            try:
                y, m = d.split("-")
                return (f"/monthly/{d}/{slug}.html", f"{int(y)}年{int(m)}月 {fish}釣果月報")
            except ValueError:
                continue
    return None


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
        cnt = (cr["max"] if _cnt_personal(cr) else 0) or 0
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


def _format_months_range(months):
    """月リスト [int] を旬カレンダー文章用に整形。
    例: [6,7,8] → "6〜8月", [4,7,10] → "4月・7月・10月", [4,5,9,10,11] → "4〜5月・9〜11月",
        12ヶ月全て → "通年", [] → ""
    年跨ぎ連続（11,12,1 等）も結合する。"""
    if not months:
        return ""
    ms = sorted(set(int(m) for m in months if 1 <= int(m) <= 12))
    if not ms:
        return ""
    if len(ms) == 12:
        return "通年"
    # 年跨ぎ連続を検出（12 と 1 が両方含まれる場合のみ結合候補）
    wrap = (12 in ms and 1 in ms)
    if wrap:
        # 12 を起点に巡回連続を取り、それ以外を通常処理
        head_end = 12
        while (head_end - 1) in ms and head_end > 1:
            head_end -= 1
        head = list(range(head_end, 13))
        tail_start = 1
        while (tail_start + 1) in ms and tail_start < 12:
            tail_start += 1
        tail = list(range(1, tail_start + 1))
        # head と tail が ms をカバーしてなければ wrap は無効
        # wrap span が 7ヶ月超なら「ほぼ通年」相当で読みづらい→通常分割に倒す
        wrap_months = set(head) | set(tail)
        if not wrap_months.issubset(set(ms)) or len(wrap_months) > 7:
            wrap = False
        else:
            remaining = sorted(set(ms) - wrap_months)
            # 通常処理に渡すために残月をランに分割
            runs = []
            if remaining:
                cur = [remaining[0]]
                for m in remaining[1:]:
                    if m == cur[-1] + 1:
                        cur.append(m)
                    else:
                        runs.append(cur)
                        cur = [m]
                runs.append(cur)
            # wrap ラン: 11〜2月 形式
            wrap_label = f"{head[0]}〜{tail[-1]}月"
            parts = [wrap_label]
            for run in runs:
                if len(run) == 1:
                    parts.append(f"{run[0]}月")
                else:
                    parts.append(f"{run[0]}〜{run[-1]}月")
            return "・".join(parts)
    # 通常: 連続月を「X〜Y月」、単月を「X月」、間を「・」で結合
    runs = []
    cur = [ms[0]]
    for m in ms[1:]:
        if m == cur[-1] + 1:
            cur.append(m)
        else:
            runs.append(cur)
            cur = [m]
    runs.append(cur)
    parts = []
    for run in runs:
        if len(run) == 1:
            parts.append(f"{run[0]}月")
        else:
            parts.append(f"{run[0]}〜{run[-1]}月")
    return "・".join(parts)


def _build_fish_season_q1_text(fish, hist_rows, decadal_calendar):
    """FAQ Q1「{魚}の旬はいつですか？」を旬カレンダーと同じデータソース・同じレベル判定で文章化。

    旬カレンダー（build_fish_season_map_html）と同じ優先順位:
    1. hist_rows（CSV から fish 全エリア合算の月別件数）← 最優先（max>=5）
    2. decadal_calendar（analysis.sqlite cnt_index 由来）
    3. SEASON_DATA（ハードコード）

    レベル判定（旬カレンダー本体と完全一致）:
      ratio = cnt / max_v
      ratio>=0.7 → lv4 (◎)・ratio>=0.4 → lv3 (良)・ratio>=0.15 → lv2 (普通)・cnt>0 → lv1 (渋)・0 → lv0
    """
    levels = None  # [12] int 0-4

    # 1. hist_rows 優先
    if hist_rows:
        counts = compute_fish_month_records(fish, hist_rows)
        max_v = max(counts) if counts else 0
        if max_v >= 5:
            levels = []
            for cnt in counts:
                ratio = cnt / max_v
                if ratio >= 0.7:    levels.append(4)
                elif ratio >= 0.4:  levels.append(3)
                elif ratio >= 0.15: levels.append(2)
                elif cnt > 0:       levels.append(1)
                else:               levels.append(0)

    # 2. decadal_calendar フォールバック
    if levels is None:
        fish_decades = decadal_calendar.get(fish, {}) if decadal_calendar else {}
        if fish_decades:
            try:
                levels = _decadal_to_monthly_index(fish_decades)
            except Exception:
                levels = None

    # 3. SEASON_DATA フォールバック（ハードコードを 0-4 レベルに正規化）
    if levels is None:
        scores = SEASON_DATA.get(fish, [])
        if scores:
            levels = [max(0, min(4, s - 1)) for s in scores]

    if not levels or all(lv == 0 for lv in levels):
        return f"{fish}の月別釣果データは現在集計中です。本ページの旬カレンダーで月別推移をご確認ください。"

    peak = [m for m, lv in enumerate(levels, 1) if lv == 4]
    good = [m for m, lv in enumerate(levels, 1) if lv == 3]
    weak = [m for m, lv in enumerate(levels, 1) if lv == 0]

    peak_str = _format_months_range(peak)
    good_str = _format_months_range(good)
    weak_str = _format_months_range(weak)

    # ピーク月の有無で文章を分岐（最大3パート）
    if peak_str:
        head = f"関東{fish}船釣りの釣果は{peak_str}に実績が集中しています。"
        if good_str and weak_str:
            return head + f"{good_str}も狙える時期で、{weak_str}は釣果が少なくなります。"
        if good_str:
            return head + f"{good_str}も狙える時期です。"
        if weak_str:
            return head + f"{weak_str}は釣果が少なくなります。"
        return head
    # ピークなし・shoulder のみ
    if good_str:
        if weak_str:
            return f"関東{fish}船釣りの釣果は{good_str}に実績があります。{weak_str}は釣果が少なくなります。"
        return f"関東{fish}船釣りの釣果は{good_str}に実績があります。"
    # peak/good ともになし・「普通」レベル(lv=2)以下のみ
    normal = [m for m, lv in enumerate(levels, 1) if lv == 2]
    normal_str = _format_months_range(normal)
    if normal_str and weak_str:
        return f"関東{fish}船釣りの釣果は{normal_str}に少しずつ見られます。{weak_str}は釣果ほぼなしです。"
    if normal_str:
        return f"関東{fish}船釣りの釣果は{normal_str}に少しずつ見られます。"
    if weak_str:
        return f"関東{fish}船釣りの釣果は限られた月にのみ記録されています。{weak_str}は釣果ほぼなしです。"
    return f"{fish}の月別釣果データは現在集計中です。本ページの旬カレンダーで月別推移をご確認ください。"


def _build_fish_area_q2_text(fish, hist_rows):
    """FAQ Q2「関東で{魚}の船釣りができる主なエリアはどこですか？」を hist_rows ベースで固定文章化。

    catches（当日スナップショット）参照だとオフシーズン魚種で件数が偏る・データ無し問題が発生するため、
    hist_rows（全期間 CSV）から tsuri_mono=fish のレコードを area 別に集計し TOP3 を固定出力する。
    """
    fallback = f"{fish}の釣果データは集計中です。本ページの最新釣果テーブルでエリア別実績をご確認ください。"
    if not hist_rows:
        return fallback
    area_counts = {}
    for r in hist_rows:
        if r.get("tsuri_mono") != fish:
            continue
        area = (r.get("area", "") or "").strip()
        if area:
            area_counts[area] = area_counts.get(area, 0) + 1
    if not area_counts:
        return fallback
    top = sorted(area_counts.items(), key=lambda x: -x[1])[:3]
    parts = "、".join(f"{a}（{n}便）" for a, n in top)
    return f"関東{fish}船釣りの主なエリアは{parts}です。"


_FISH_BEGINNER_MAP = {
    "アジ":       ("入門魚の定番", "ライトな仕掛けで数釣りを楽しめる入門向きの魚。食いが立てば初心者でもツ抜けが狙えます"),
    "サバ":       ("入門向け", "コマセ釣りで豪快な数釣りが楽しめます。引きも強く、釣りの醍醐味を存分に味わえます"),
    "キス":       ("入門〜中級", "天ぷらネタとして人気の魚。シンプルな仕掛けで楽しめますが、アタリを取る繊細さも醍醐味です"),
    "シロギス":   ("入門〜中級", "天ぷらネタとして人気の魚。シンプルな仕掛けで楽しめますが、アタリを取る繊細さも醍醐味です"),
    "タコ":       ("入門向け", "底を叩くだけのシンプルな釣り。ファミリーフィッシングにも人気で、道具も比較的手軽です"),
    "マダコ":     ("入門向け", "底を叩くだけのシンプルな釣り。ファミリーフィッシングにも人気で、道具も比較的手軽です"),
    "マダイ":     ("中級者向け", "コマセを使ったビシ釣りが主流。繊細なアタリを取る楽しさがあり、釣れたときの達成感は格別です"),
    "ヒラメ":     ("中級者向け", "泳がせ釣りで大物を狙います。アタリからの「一呼吸」をおいてから合わせるのがコツです"),
    "マルイカ":   ("上級者向け", "直結仕掛けの操作が独特でテクニカルな釣り。習得に時間がかかりますが、釣れると病みつきになります"),
    "スルメイカ": ("入門〜中級", "ブランコ仕掛けならビギナーでも数釣りが楽しめます。夜釣りでの豪快な多点掛けが醍醐味です"),
    "ヤリイカ":   ("入門〜中級", "ブランコ仕掛けでの数釣りが楽しめます。冬〜春の風物詩で、繊細なアタリと食味の良さが魅力です"),
    "アオリイカ": ("中級者向け", "エギングや活きエサ泳がせで狙う高級イカ。繊細な誘いとアタリの取り方に技術が求められます"),
    "スミイカ":   ("中級者向け", "スッテ釣りで狙う秋〜冬のターゲット。底を取る感覚と独特の引きが魅力です"),
    "ムギイカ":   ("入門〜中級", "初夏のスルメイカ若魚。ブランコ仕掛けで数釣りが楽しめ、夏の風物詩として人気です"),
    "カツオ":     ("入門〜中級", "コマセ釣りで豪快な引きを楽しめます。口切れしやすいので走られても慌てず一定のテンションを保つのがポイントです"),
    "キハダマグロ": ("上級者向け", "大型青物との長期戦。専用の強靭なタックルが必要で、体力・経験が問われる上級者向けの釣りです"),
    "キメジ":     ("中〜上級", "キハダマグロの若魚。タックルはやや軽めでも、青物特有の引きとスピード感が楽しめます"),
    "シーバス":   ("中級者向け", "ルアーとエサ釣り両方が楽しめます。河川〜沖合まで幅広いフィールドで狙えるのも魅力です"),
    "スズキ":     ("中級者向け", "ルアーとエサ釣り両方が楽しめます。河川〜沖合まで幅広いフィールドで狙えるのも魅力です"),
    "カサゴ":     ("入門向け", "根魚の定番。底を丁寧に探るだけで釣れることも多く、初心者にも優しい魚です"),
    "メバル":     ("初級〜中級", "食い込みを待つ繊細な釣り。活性が高い時間帯を読むのが釣果を伸ばすコツです"),
    "アマダイ":   ("中級者向け", "深場を狙う高級魚。丁寧な底取りとゆっくりした誘い上げが重要で、釣れたときの喜びは大きいです"),
    "シロアマダイ": ("上級者向け", "希少な高級魚。アマダイより警戒心が強く、繊細なアタリを取る技術が求められます"),
    "ワラサ":     ("中級者向け", "ブリの若魚で引きが豪快。体力勝負になる場面もあり、タックルはある程度しっかりしたものが必要です"),
    "ブリ":       ("中〜上級", "強烈な引きに耐えるタックル選びが重要。大型を仕留めたときの達成感は格別ですが、初心者には難易度高めです"),
    "ヒラマサ":   ("上級者向け", "根に潜る習性が強く、青物の中でも特に難易度の高いターゲット。強靭なタックルと経験が必要です"),
    "サワラ":     ("中級者向け", "鋭い歯と独特の食い込み方が特徴。合わせのタイミングが難しいですが、スピード感あふれる引きが魅力です"),
    "タチウオ":   ("中級者向け", "テンヤ・コマセなど釣り方の幅が広い魚。銀色に輝く魚体と独特のアタリが病みつきになります"),
    "カワハギ":   ("上級者向け", "エサ取りの名手相手の高度な駆け引きが醍醐味。腕の差が如実に出る釣りで、熟練者ほどはまります"),
    "イサキ":     ("入門〜中級", "コマセ釣りで安定した釣果が期待でき、食味も抜群。数釣りと型釣りを両立できる人気ターゲットです"),
    "ハナダイ":   ("入門〜中級", "マダイより口が小さく繊細な食い込み。コマセ釣りで狙い、食味の良さも人気の理由です"),
    "クロダイ":   ("中級者向け", "警戒心が強く難易度は高め。潮の変わり目など時合いを読む経験が釣果に直結します"),
    "イナダ":     ("入門向け", "青物入門として最適。コマセで群れを引き寄せ、豪快な引きを楽しめます"),
    "カンパチ":   ("中〜上級", "パワフルな引きと根に潜る習性への対応が重要。大型を狙うほど難易度が上がります"),
    "シイラ":     ("中級者向け", "派手なジャンプと強烈な引きが特徴的なゲームフィッシュ。夏場の人気ターゲットです"),
    "メダイ":     ("中級者向け", "深場の中型ターゲット。底取りと丁寧な誘いが釣果を左右します"),
    "クロムツ":   ("中級者向け", "深場の高級魚。電動リールと丁寧な底取りが必要で、釣れたときの食味は格別です"),
    "オニカサゴ": ("中級者向け", "深場の根魚で毒棘に注意が必要。慎重な底取りと取り込み時のハンドリングが重要です"),
    "アナゴ":     ("入門向け", "夜釣りの定番。底を丁寧に探るだけで釣れることが多く、ファミリーにも人気です"),
    "イシモチ":   ("入門向け", "投げ釣り・船釣り両方で楽しめる魚。アタリも明確で、初心者の数釣り対象として人気です"),
    "マハタ":     ("中〜上級", "根魚の高級ターゲット。根に潜る習性が強く、強引なやり取りが求められます"),
    "クロムツ":   ("中級者向け", "深場の高級魚。電動リールと丁寧な底取りが必要で、釣れたときの食味は格別です"),
    "キンメダイ": ("中〜上級", "深場の高級魚。重いオモリと電動リールが必要で、底取りと誘いに技術が求められます"),
    "フグ":       ("中級者向け", "カットウ釣り・テンヤ釣りで狙う高級魚。繊細なアタリを取るテクニックが必要です"),
    "ショウサイフグ": ("中級者向け", "カットウ釣り・テンヤ釣りで狙う高級魚。繊細なアタリを取るテクニックが必要です"),
    "トラフグ":   ("中〜上級", "高級魚の代表格。専門船宿でのカットウ釣りが主流で、繊細なアタリと駆け引きが楽しめます"),
    "マゴチ":     ("中級者向け", "活きエサで狙う夏のターゲット。アタリから合わせまでの間合いがコツです"),
    "ホウボウ":   ("入門〜中級", "アマダイやマダイの外道としても人気の食味の良い魚。底物五目で楽しめます"),
    "カマス":     ("入門向け", "サビキ・コマセで数釣りが楽しめる青物入門ターゲット。シーズンになると港湾でも狙えます"),
    "イシダイ":   ("上級者向け", "磯釣りの王様として知られる難ターゲット。船からも狙えますが、根に潜る習性への対応が必要です"),
    "ハゼ":       ("入門向け", "ミャク釣り・ウキ釣りで楽しめる入門の定番。秋の風物詩でファミリーにも大人気です"),
    "カレイ":     ("入門〜中級", "投げ釣り・船釣り両方で楽しめる底物。丁寧な底取りと当たりを待つ釣りが特徴です"),
    "タイ五目":   ("入門〜中級", "マダイを中心に複数魚種が狙えるコマセ釣り。初心者から熟練者まで楽しめる定番スタイルです"),
}


# T30 (2026/05/12): fish_area FAQ 固定文章化用マップ群
# 妥当範囲外の cm/kg 値（CSV 誤入力）を異常値として除外するための魚種別上限マップ。
# primary は「主単位」: cm 主流の魚は "cm"・kg 主流の大型魚は "kg"。
# 範囲を保守的に設定（実際の最大記録より厳しめ）して明らかな異常値のみ除外。
# 2026/05/23: 単一のソースから crawler.py / x_post 両方で参照するため
# normalize/fish_size_range.json に外部化（DRY 違反解消）。
def _load_fish_size_range_map():
    """normalize/fish_size_range.json から魚種別 cm/kg 上限テーブルを読み込む。
    返り値: (魚種別 dict, _default dict)
    """
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "normalize", "fish_size_range.json")
    try:
        with open(path, encoding="utf-8") as _f:
            _raw = json.load(_f)
    except Exception:
        return {}, {"cm_max": 200, "kg_max": 100, "primary": "cm"}
    _default = _raw.pop("_default", {"cm_max": 200, "kg_max": 100, "primary": "cm"})
    return _raw, _default

_FISH_SIZE_RANGE_MAP, _FISH_SIZE_DEFAULT = _load_fish_size_range_map()

# 魚種別の釣法主流テキスト。「マダイ=コマセダイ」など正確な釣法名で書く。
# 「ビシ釣り」は本来アジ用語のため、マダイには使わない（T30 ユーザー指摘で修正）。
_FISH_METHOD_MAP = {
    "アジ":         "コマセを使ったライトアジ（LTアジ）・ビシアジが代表的な釣り方",
    "ビシアジ":     "重めのビシを使った深場アジ釣り（大型狙い）",
    "シマアジ":     "コマセを使ったコマセシマアジ釣りが主流",
    "サバ":         "コマセ釣り・ジギング・サビキ釣りが代表的",
    "マダイ":       "コマセを使ったコマセダイ（コマセマダイ）が主流。タイラバや一つテンヤも人気",
    "クロダイ":     "船からはコマセを使ったクロダイ釣り（落とし込みやヘチ釣りも）",
    "ハナダイ":     "コマセダイ・サビキ釣りが主流",
    "イサキ":       "コマセを使ったコマセイサキ釣りが主流",
    "タチウオ":     "テンヤ・コマセ・ジギングが代表的な釣り方",
    "シロギス":     "テンビン仕掛けのキス釣りが主流",
    "カワハギ":     "テンヤ・胴突き仕掛けでの繊細なアタリ取りが特徴",
    "カレイ":       "船からは胴突き仕掛けのカレイ釣りが主流",
    "ヒラメ":       "活きエサ泳がせ釣りが代表的",
    "マゴチ":       "活きエサ泳がせ釣り・テンヤが主流",
    "ホウボウ":     "テンビン仕掛けや五目釣りで狙う",
    "メバル":       "サビキ・胴突き仕掛けのメバル釣り",
    "カサゴ":       "胴突き仕掛けでの根魚釣り",
    "アマダイ":     "テンビン仕掛けでの深場狙い",
    "シロアマダイ": "テンビン仕掛けでの深場狙い（希少な高級魚）",
    "オニカサゴ":   "胴突き仕掛けでの深場根魚釣り（毒棘に注意）",
    "クロムツ":     "胴突き仕掛けでの深場釣り（電動リール推奨）",
    "アカムツ":     "胴突き仕掛けでの深場釣り（電動リール推奨）",
    "キンメダイ":   "胴突き仕掛けでの深場釣り（電動リール使用）",
    "アコウダイ":   "胴突き仕掛けでの深場釣り",
    "ベニアコウ":   "深場専門の胴突き仕掛け釣り",
    "メヌケ":       "胴突き仕掛けでの深場釣り",
    "マハタ":       "胴突き仕掛けでの根魚釣り",
    "ハタ":         "胴突き仕掛けでの根魚釣り",
    "イシダイ":     "ウニ・サザエなどのエサで狙う底物釣り",
    "アラ":         "胴突き仕掛けでの深場大物釣り",
    "イシモチ":     "テンビン仕掛け・サビキ釣りが主流",
    "スズキ":       "ルアー釣り・活きエサのエサ釣りの両方が主流",
    "シーバス":     "ルアー釣りが代表的",
    "ブリ":         "コマセ・ジギング・泳がせ釣りが主流",
    "ワラサ":       "コマセ・ジギング・泳がせ釣りが主流",
    "イナダ":       "コマセ・ジギングが主流",
    "カンパチ":     "ジギング・コマセ・泳がせ釣りが主流",
    "ヒラマサ":     "ジギング・キャスティングが主流",
    "サワラ":       "ジギング・キャスティングが主流",
    "カツオ":       "コマセを使ったコマセ釣りが代表的",
    "キハダマグロ": "コマセ・ジギング・キャスティングが主流",
    "キメジ":       "コマセ・ジギングが主流",
    "シイラ":       "キャスティング・ジギングが代表的",
    "メダイ":       "胴突き仕掛けでの中深場釣り",
    "カマス":       "サビキ・コマセ釣りが主流",
    "アナゴ":       "テンビン仕掛けでの夜釣りが代表的",
    "ハゼ":         "ミャク釣り・ウキ釣りが代表的",
    "マダコ":       "テンヤ・エギを使ったタコ釣りが主流",
    "アオリイカ":   "エギング・活きエサ泳がせ（ヤエン）が代表的",
    "スミイカ":     "スッテ釣りが主流",
    "モンゴウイカ": "スッテ釣りが主流",
    "マルイカ":     "直結仕掛けの専門的な釣り",
    "スルメイカ":   "ブランコ仕掛け・直結仕掛けが主流",
    "ヤリイカ":     "ブランコ仕掛けが主流",
    "ムギイカ":     "ブランコ仕掛けが主流（スルメイカ若魚）",
    "ショウサイフグ": "カットウ釣り・テンヤ釣りが代表的",
    "トラフグ":     "カットウ釣り・テンヤ釣りが代表的",
    "アブラボウズ": "深場専門の胴突き仕掛け釣り",
    "タイ五目":     "コマセを使ったコマセ五目釣り",
    "キントキ":     "胴突き仕掛けでの中深場釣り",
}


def _build_fish_beginner_q4_text(fish, hist_rows):
    """FAQ Q4「初心者でも{魚}釣りは楽しめますか？」を hist_rows ベースで固定文章化。

    _FISH_BEGINNER_MAP（53 魚種・難易度+説明）と hist_rows のユニーク船宿数を組合せて固定文章を生成。
    catches（当日スナップショット）依存だとオフシーズン魚種で船宿数が 0 になっていた問題への対策。
    """
    ship_count = 0
    if hist_rows:
        ships = set()
        for r in hist_rows:
            if r.get("tsuri_mono") != fish:
                continue
            ship = (r.get("ship", "") or "").strip()
            if ship:
                ships.add(ship)
        ship_count = len(ships)
    fish_info = _FISH_BEGINNER_MAP.get(fish)
    if fish_info:
        level, desc = fish_info
        ship_str = f"関東では{ship_count}船宿が出船実績あり。" if ship_count > 0 else ""
        return f"難易度は{level}の釣りです。{desc}。{ship_str}多くの船宿でレンタルタックルや仕掛けの購入が可能です。"
    if ship_count > 0:
        return f"はい。関東では{ship_count}船宿が出船実績があります。多くの船宿でレンタルタックルや仕掛けの購入が可能で、初心者でも安心して楽しめます。"
    return f"はい。船宿スタッフのサポートも受けられます。竿・リールのレンタルができる船宿も多くあります。"


# ============================================================
# 釣果数の現実的上限（品質ゲート）
# 年号誤抽出（例: ヒラメ「2025匹」=西暦の混入）や桁化けを弾く。
# 値は「個人1人の1日の常識的な最大値」を大きく上回る安全マージンで設定し、
# 実在の大釣り（アジ713・スジイカ702等）を誤って除外しないこと。
# ここに無い魚種は _DEFAULT_CNT_CAP を適用。
# ============================================================
_DEFAULT_CNT_CAP = 300
_FISH_CNT_CAP = {
    # サビキ・数物（極めて多く釣れる）
    # アジは LTアジ/ビシアジで「ビリ〜竿頭」の便内スプレッドが count_raw に入りやすく、
    # 竿頭としても非現実な上限（吉野屋「120〜713匹」等＝実質 船中値）が混入する。
    # 竿頭の現実的上限 ~350 を見て 400 で頭打ち（371 等の境界は保持）。豆アジ/サビキは別枠。
    "アジ": 400, "マアジ": 400, "豆アジ": 1500,
    "イワシ": 1500, "マイワシ": 1500, "カタクチイワシ": 2000, "ウルメイワシ": 1500,
    "サバ": 800, "マサバ": 800, "ゴマサバ": 800,
    "シロギス": 500, "キス": 500, "ハゼ": 600, "カマス": 500,
    # イカ類（多点掛け）
    "スジイカ": 1000, "ムギイカ": 600, "マルイカ": 600, "スルメイカ": 600,
    "ヤリイカ": 500, "アカイカ": 500, "ケンサキイカ": 600,
    # その他やや多め
    "タチウオ": 400, "カワハギ": 400, "カサゴ": 400, "メバル": 400,
    "イサキ": 350, "イシモチ": 300,
    # 高級魚・大型魚・根魚・青物（1人1日の数は本来少ない＝低めの上限で boat 誤集計も弾く）
    "ヒラメ": 40, "マゴチ": 40, "マダイ": 80, "クロダイ": 50,
    "マハタ": 40, "ハタ": 50, "アラ": 25, "クエ": 20,
    "アマダイ": 80, "シロアマダイ": 30, "キンメダイ": 100,
    "アカムツ": 60, "クロムツ": 70, "オニカサゴ": 60, "ホウボウ": 60,
    "スズキ": 80, "シーバス": 100, "イシダイ": 25,
    "カンパチ": 80, "ブリ": 50, "ワラサ": 70, "ヒラマサ": 50,
    "サワラ": 60, "シイラ": 60, "カツオ": 120,
    "キハダマグロ": 30, "キメジ": 120, "メジ": 80,
}


def _cnt_cap(fish):
    """魚種の釣果数の現実的上限を返す。"""
    return _FISH_CNT_CAP.get(fish, _DEFAULT_CNT_CAP)


def _is_plausible_cnt(fish, v):
    """釣果数 v が魚種 fish にとって現実的か（上限以内か）を判定。"""
    try:
        return 0 <= float(v) <= _cnt_cap(fish)
    except (ValueError, TypeError):
        return False


def _build_fish_count_q3_text(fish, hist_rows):
    """FAQ Q3「{魚}の一日の釣果はどのくらいですか？」を hist_rows ベースで固定文章化。

    catches（当日スナップショット）参照だとオフシーズン魚種でフォールバック汎用文に落ちる問題への対策。
    hist_rows（全期間 CSV）から tsuri_mono=fish かつ is_boat≠1 のレコードの cnt_max を集計し、
    P25〜P75 を「標準的なレンジ」・最大値を「最高実績」として出力する固定文章。

    cnt_max=0（ボウズ便）は除外（「典型的な釣果」を表現するため）。

    補遺3 遵守: 「平均」「avg」「ave」表現は使わず、「標準的なレンジ」「最高実績」を使う。
    """
    fallback = f"{fish}の釣果データは集計中です。本ページの最新釣果テーブルで実績をご確認ください。"
    if not hist_rows:
        return fallback
    maxes = []
    for r in hist_rows:
        if r.get("tsuri_mono") != fish:
            continue
        if not _cnt_personal_csv(r):
            continue
        cmax = r.get("cnt_max", "")
        if cmax == "" or cmax is None:
            continue
        try:
            v = int(float(cmax))
        except (ValueError, TypeError):
            continue
        if not _is_plausible_cnt(fish, v):
            continue  # 年号誤抽出・桁化け等の非現実値を除外（品質ゲート）
        if v > 0:  # ボウズ便は典型レンジ算出から除外
            maxes.append(v)
    if not maxes:
        return fallback
    n = len(maxes)
    sorted_maxes = sorted(maxes)
    max_max = sorted_maxes[-1]
    if n >= 4:
        p25 = sorted_maxes[int(n * 0.25)]
        p75 = sorted_maxes[int(n * 0.75)]
    else:
        p25 = sorted_maxes[0]
        p75 = sorted_maxes[-1]
    # n>=30 で中央値・上位10%を追記（2026-06-11・固定文プロジェクト）
    # 補遺3 遵守: 「平均」は使わない（中央値・分位は P25/P75 と同じ流儀で可）
    extra = ""
    if n >= 30:
        med = sorted_maxes[n // 2]
        p90 = sorted_maxes[min(int(n * 0.9), n - 1)]
        extra = f"中央値は{med}匹・上位10%の好日は{p90}匹以上です。"
    if p25 == p75:
        return f"関東{fish}船釣りの一日の釣果は{p25}匹前後が標準的です。{extra}最高実績は{max_max}匹です（いずれも個人釣果ベース・船全体の合計数は除く）。"
    return f"関東{fish}船釣りの一日の釣果は{p25}〜{p75}匹が標準的なレンジです。{extra}最高実績は{max_max}匹です（いずれも個人釣果ベース・船全体の合計数は除く）。"


def build_fish_faq_html(fish, catches, decadal_calendar, site_url="", hist_rows=None, content_sections=None):
    """魚種別FAQ（データ駆動型）＋ FAQPage JSON-LD を返す (html, faq_pairs) のタプル

    content_sections（load_fish_content() の魚種別固定文 dict）がある場合、
    HTML 側の回答末尾に該当セクションへのアンカーリンクを付ける（内部回遊用）。
    JSON-LD（faq_pairs）にはリンクを入れない。
    """
    # Q1: 旬はいつ？ → 旬カレンダーと同じデータソース・レベル判定で固定文章化
    q1_ans = _build_fish_season_q1_text(fish, hist_rows, decadal_calendar)

    # Q2: 主なエリア → hist_rows（全期間 CSV）ベースで固定文章化
    q2_ans = _build_fish_area_q2_text(fish, hist_rows)

    # Q3: 一日の釣果 → hist_rows（全期間 CSV）ベースで固定文章化（オフシーズンでも値が出る）
    q3_ans = _build_fish_count_q3_text(fish, hist_rows)

    # Q4: 初心者向け → _FISH_BEGINNER_MAP + hist_rows のユニーク船宿数で固定文章化
    q4_ans = _build_fish_beginner_q4_text(fish, hist_rows)

    faqs = [
        (f"{fish}の旬はいつですか？", q1_ans),
        (f"関東で{fish}の船釣りができる主なエリアはどこですか？", q2_ans),
        (f"{fish}の一日の釣果はどのくらいですか？", q3_ans),
        (f"初心者でも{fish}釣りは楽しめますか？", q4_ans),
    ]
    # 固定文セクションへのアンカーリンク（HTML のみ・JSON-LD には入れない）
    _faq_anchor = {}
    if content_sections:
        if content_sections.get("season"):
            _faq_anchor[0] = ' <a class="faq-more" href="#fish-season-note">→ エリア別のシーズン傾向を見る</a>'
        if content_sections.get("beginner"):
            _faq_anchor[3] = ' <a class="faq-more" href="#fish-guide">→ 初心者向けガイドを見る</a>'
    import html as _html_mod
    block_ttl = f"{_html_mod.escape(fish)}釣果データから分かること"
    html = f'<div class="faq-list faq-data">\n<h3 class="faq-block-ttl">{block_ttl}</h3>\n'
    for _qi, (q, a) in enumerate(faqs):
        html += f'  <details><summary>{q}</summary><p class="faq-ans">{a}{_faq_anchor.get(_qi, "")}</p></details>\n'
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
    train = ad.get("access_train", "") or ad.get("nearest_station", "")
    car   = ad.get("access_car", "") or ad.get("nearest_ic", "")
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


_AREA_SKIP_FISH = {"不明", "欠航", "NULL", ""}


def _is_cancelled_row(r):
    """is_cancellation == '1' のレコードを欠航として除外判定（T31 2026/05/12 追加）。"""
    return str(r.get("is_cancellation", "")).strip() == "1"


def _build_area_top_fish_q1_text(area, hist_rows):
    """area FAQ Q1（T31 2026/05/12）: TOP3魚種 + 件数 + 各魚種のピーク月特徴を hist_rows から固定文章化。"""
    if not hist_rows:
        return f"{area}の釣果データは集計中です。最新の釣果カードをご確認ください。"
    fish_counts = {}
    fish_month_counts = {}
    total = 0
    for r in hist_rows:
        if r.get("area") != area:
            continue
        if _is_cancelled_row(r):
            continue
        f = (r.get("tsuri_mono") or "").strip()
        if not f or f in _AREA_SKIP_FISH or f.isdigit():
            continue
        fish_counts[f] = fish_counts.get(f, 0) + 1
        total += 1
        d = r.get("date", "")
        if len(d) >= 7:
            try:
                m = int(d[5:7])
                if 1 <= m <= 12:
                    fish_month_counts.setdefault(f, [0] * 12)[m - 1] += 1
            except (ValueError, TypeError):
                pass
    if total == 0:
        return f"{area}の釣果データは集計中です。最新の釣果カードをご確認ください。"
    n_kinds = len(fish_counts)
    top3 = sorted(fish_counts.items(), key=lambda x: -x[1])[:3]
    parts = []
    for fname, fcnt in top3:
        mc = fish_month_counts.get(fname, [0] * 12)
        max_v = max(mc) if any(mc) else 0
        if max_v > 0:
            peak_months = [i + 1 for i, v in enumerate(mc) if v >= max_v * 0.7]
            peak_str = _format_months_range(peak_months) if peak_months else ""
            if peak_str and peak_str != "通年":
                parts.append(f"{fname}（{fcnt:,}便・{peak_str}が好機）")
            else:
                parts.append(f"{fname}（{fcnt:,}便）")
        else:
            parts.append(f"{fname}（{fcnt:,}便）")
    head = f"2023年以降の{area}の釣果データは{total:,}便・{n_kinds}魚種が記録されています。"
    body = f"件数の多い順に{'、'.join(parts)}が主力です。"
    tail = "潮回り・水温・季節で構成は変動するため、本ページの旬カレンダーや最新の釣果カードも併せてご確認ください。"
    return head + body + tail


def _build_area_access_q2_text(area, area_description):
    """area FAQ Q2（T31 2026/05/12）: area_description.json の nearest_ic / nearest_station /
    parking から 最寄りIC + 最寄り駅 + 駐車場 を固定文章化。
    未登録のときは「各船宿のウェブサイトでご確認ください」。"""
    nearest_ic = ""
    nearest_station = ""
    parking = ""
    if area_description and isinstance(area_description, dict):
        entry = area_description.get(area) or {}
        if isinstance(entry, dict):
            nearest_ic = (entry.get("nearest_ic") or "").strip()
            nearest_station = (entry.get("nearest_station") or "").strip()
            parking = (entry.get("parking") or "").strip()
    # IC/駅は名詞句前提。末尾の句読点を除去して「、…です。」テンプレの二重句読点を防ぐ
    nearest_ic = nearest_ic.rstrip("。、 ")
    nearest_station = nearest_station.rstrip("。、 ")
    if parking and not parking.endswith("。"):
        parking += "。"
    parts = []
    if nearest_ic:
        parts.append(f"最寄りICは{nearest_ic}")
    if nearest_station:
        parts.append(f"最寄り駅は{nearest_station}")
    if parts:
        return (
            f"{area}への{'、'.join(parts)}です。"
            f"{parking}"
            f"集合場所や料金の詳細は船宿ごとに異なるため、予約時または本ページの船宿一覧から各船宿のウェブサイトをご確認ください。"
        )
    if parking:
        return (
            f"{area}の{parking}"
            f"最寄りIC・最寄り駅は本ページの船宿一覧から各船宿のウェブサイトをご確認ください。"
        )
    return (
        f"{area}への詳細なアクセス情報は準備中です。"
        f"最寄りIC・最寄り駅は本ページの船宿一覧から各船宿のウェブサイトをご確認ください。"
    )


def _build_area_recommendation_q3_text(area, hist_rows):
    """area FAQ Q3（T31）: 季節別TOP魚種で推奨時期を固定文章化（春夏秋冬の4区分）。"""
    if not hist_rows:
        return f"{area}の釣果データは集計中です。本ページの旬カレンダーで月別の状況をご確認ください。"
    month_fish = {}
    fish_total = {}
    for r in hist_rows:
        if r.get("area") != area:
            continue
        if _is_cancelled_row(r):
            continue
        f = (r.get("tsuri_mono") or "").strip()
        if not f or f in _AREA_SKIP_FISH or f.isdigit():
            continue
        d = r.get("date", "")
        if len(d) < 7:
            continue
        try:
            m = int(d[5:7])
            if not (1 <= m <= 12):
                continue
        except (ValueError, TypeError):
            continue
        mf = month_fish.setdefault(m, {})
        mf[f] = mf.get(f, 0) + 1
        fish_total[f] = fish_total.get(f, 0) + 1
    if not fish_total:
        return f"{area}の月別実績は集計中です。本ページの旬カレンダーで詳細をご確認ください。"
    season_groups = [
        ("春（3〜5月）", [3, 4, 5]),
        ("夏（6〜8月）", [6, 7, 8]),
        ("秋（9〜11月）", [9, 10, 11]),
        ("冬（12〜2月）", [12, 1, 2]),
    ]
    season_top = []
    for sname, months in season_groups:
        sf_counts = {}
        for m in months:
            for f, c in month_fish.get(m, {}).items():
                sf_counts[f] = sf_counts.get(f, 0) + c
        if sf_counts:
            top1 = max(sf_counts.items(), key=lambda x: x[1])
            season_top.append((sname, top1[0], top1[1]))
    if not season_top:
        return f"{area}の月別実績は集計中です。本ページの旬カレンダーで詳細をご確認ください。"
    parts = [f"{s}は{f}（{c:,}件）" for s, f, c in season_top]
    head = f"過去3年間の{area}での月別実績を集計すると、"
    body = "、".join(parts) + "が代表的なターゲットです。"
    tail = "魚種ごとに釣れる時期が異なるため、本ページの旬カレンダーで詳細な月別釣れ具合をご確認ください。"
    return head + body + tail


def _build_area_ships_q4_text(area, hist_rows):
    """area FAQ Q4（T31）: 船宿TOP5 + 船宿総数で固定文章化。"""
    if not hist_rows:
        return f"{area}の船宿情報は集計中です。本ページの船宿一覧をご確認ください。"
    ship_counts = {}
    for r in hist_rows:
        if r.get("area") != area:
            continue
        if _is_cancelled_row(r):
            continue
        sn = (r.get("ship") or "").strip()
        if sn:
            ship_counts[sn] = ship_counts.get(sn, 0) + 1
    if not ship_counts:
        return f"{area}の船宿情報は集計中です。本ページの船宿一覧をご確認ください。"
    n_ships = len(ship_counts)
    top5 = sorted(ship_counts.items(), key=lambda x: -x[1])[:5]
    ship_str = "、".join(f"{sn}（{cnt:,}便）" for sn, cnt in top5)
    if n_ships == 1:
        sn, cnt = top5[0]
        return (
            f"過去3年間の{area}での釣果データは{sn}が{cnt:,}便記録されており、"
            f"現状は{sn}に集約されています。出船日・料金・対象魚種の詳細は本ページの船宿一覧からご確認ください。"
        )
    head = f"過去3年間の{area}での釣果データは計{n_ships}船宿で記録されています。"
    if n_ships >= 5:
        body = f"件数の多い順に{ship_str}が出船実績豊富です。"
    else:
        body = f"{ship_str}が記録上の主力船宿です。"
    tail = "各船宿で出船日・料金・対象魚種が異なるため、本ページの船宿一覧から詳細をご確認ください。"
    return head + body + tail


def build_area_faq_html(area, desc_data, hist_rows=None, area_coords=None):
    """エリア別 FAQ（T31 2026/05/12）: 3年分 hist_rows ベース固定文章化。

    旧版（catches/top_fish_items 依存）から、hist_rows 依存に変更。
    Q1=魚種実績、Q2=地理特徴（area_description + 3年件数）、Q3=季節別推奨、Q4=船宿実績。
    戻り値: (html, faq_pairs)
    """
    q1_ans = _build_area_top_fish_q1_text(area, hist_rows)
    q2_ans = _build_area_access_q2_text(area, desc_data)
    q3_ans = _build_area_recommendation_q3_text(area, hist_rows)
    q4_ans = _build_area_ships_q4_text(area, hist_rows)
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


def build_area_fixed_faq_html(area, fixed_faq_data):
    """エリアページ用の固定 FAQ（T31 2026/05/12）。

    T22-M1（fish）と同じパターン: エリア固有の固定FAQ（fixed_faq.json の area スコープ）のみを
    <details> で出力し、共通 7 問は faq.html へのリンクブロックに差し替える（HTML には含めない）。
    戻り値: (html, faq_pairs)  faq_pairs はエリア固有 FAQ の (q, a) のみ（JSON-LD 用）
    """
    import html as _html
    scoped_items = (fixed_faq_data.get("area") or {}).get(area, [])

    faq_pairs = []
    inner = ""

    if scoped_items:
        block_ttl = f"{_html.escape(area)}を釣り場として知る"
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

    if inner:
        html_out = f'<div class="faq-list faq-static" data-scope="area-{_html.escape(area)}">\n{inner}</div>'
    else:
        html_out = ""

    return html_out, faq_pairs

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
    # ALL_FISH 追加分
    "クロダイ":     [2,2,3,4,5,4,3,2,3,3,3,2],  # 春（4〜6月）乗っ込みピーク
    "タイ五目":     [2,2,3,4,4,4,3,3,3,3,3,2],  # 春〜秋
    "アオリイカ":   [1,1,2,3,4,4,3,2,4,5,4,2],  # 春産卵・秋新子
    "キハダマグロ": [1,1,1,1,1,2,4,5,5,3,2,1],  # 夏（8〜9月）
    "イナダ":       [1,1,1,1,2,3,4,5,5,5,4,2],  # 夏〜秋（7〜11月）
    "カツオ":       [1,1,1,1,2,3,5,5,5,4,2,1],  # 夏〜秋（7〜10月）
    "シーバス":     [2,2,2,3,4,4,3,3,5,5,4,3],  # 秋（9〜10月）がピーク
    "ハタ":         [2,2,2,2,3,4,5,5,4,4,3,2],  # 夏〜秋
    "ムギイカ":     [2,3,4,5,5,4,2,1,1,1,2,2],  # 春（4〜6月）
    "アカムツ":     [4,4,4,4,3,3,3,3,3,4,4,4],  # 通年・冬〜春やや好調
    "シマアジ":     [1,1,1,2,3,4,5,5,4,3,2,1],  # 夏（7〜8月）
    "シイラ":       [1,1,1,1,2,3,5,5,4,4,3,1],  # 夏〜秋（7〜10月）
    "トラフグ":     [5,5,4,4,3,2,1,1,2,3,4,4],  # 冬〜春（12〜2月）
    "ビシアジ":     [3,3,3,4,4,5,5,4,4,4,4,3],  # アジと同様・通年
    "ショウサイフグ":[4,4,3,2,2,1,1,1,2,4,5,5],  # 秋〜冬（10〜2月）
    "アカメフグ":   [3,3,3,3,3,2,1,1,2,3,4,4],  # 秋〜冬
    "カマス":       [3,3,2,2,2,2,2,2,3,4,5,4],  # 秋〜冬（10〜11月）
    "スジイカ":     [1,1,1,2,3,5,5,5,4,3,2,1],  # 夏（6〜9月）
    "ヒラマサ":     [2,2,2,3,4,4,5,5,4,3,3,2],  # 夏〜秋（7〜8月）
    "コハダ":       [3,3,2,2,2,2,2,2,3,4,4,4],  # 秋〜冬
    "スミイカ":     [3,3,2,2,2,2,2,2,3,4,5,4],  # 秋（10〜11月）
    "シロアマダイ": [3,3,3,3,3,3,3,3,4,4,4,4],  # アマダイと同様・通年
    "ブリ":         [5,5,4,3,2,2,2,2,3,3,4,5],  # 冬（11〜2月）
    "オニカサゴ":   [4,4,4,4,3,3,3,3,3,3,4,4],  # 冬〜春・通年
    "キメジ":       [1,1,1,1,2,3,5,5,4,3,2,1],  # 夏〜秋
    "カレイ":       [4,4,4,4,3,2,1,1,2,3,3,4],  # 冬〜春
    "メヌケ":       [3,3,3,3,3,3,3,3,3,3,3,3],  # 深場・通年
    "アラ":         [4,4,3,3,3,3,3,3,3,4,4,5],  # 秋〜冬
    "モンゴウイカ": [2,2,4,5,5,4,2,1,1,2,2,2],  # 春（3〜6月）
    "イシダイ":     [1,1,1,2,3,4,5,5,5,4,2,1],  # 夏〜秋
    "モロコ":       [3,3,3,3,3,3,3,3,3,3,3,3],  # 深場・通年
    "ホウボウ":     [4,4,4,4,3,2,2,2,2,3,3,4],  # 冬〜春
    "イシモチ":     [1,1,1,2,3,5,5,5,4,3,2,1],  # 夏（6〜9月）
    "キントキ":     [2,2,2,2,3,4,4,4,4,4,3,2],  # 夏〜秋・深場
    "ハナダイ":     [2,2,3,4,5,5,4,4,4,3,3,2],  # 春〜秋（4〜10月）
    "アナゴ":       [1,1,1,2,3,5,5,5,4,2,1,1],  # 夏（6〜9月）
}
SEASON_TYPE = {
    "アジ":         ["数","数","数","数","型","型","型","数","数","数","数","数"],
    "タチウオ":     ["数","数","数","数","数","数","型","型","数","数","数","数"],
    "マダイ":       ["数","数","型","型","型","数","数","数","数","型","型","数"],
    "シロギス":     ["数","数","数","数","数","型","型","数","数","数","数","数"],
    "ヤリイカ":     ["型","型","数","数","数","数","数","数","数","数","型","型"],
    "ヒラメ":       ["型","型","型","数","数","数","数","数","型","型","型","型"],
    "マルイカ":     ["数","数","数","数","数","数","数","数","数","数","数","数"],
    "サワラ":       ["数","数","数","数","数","数","数","数","数","数","数","数"],
    "カンパチ":     ["数","数","数","数","数","型","型","型","数","数","数","数"],
    "クロダイ":     ["数","数","数","型","型","数","数","数","数","数","数","数"],
    "アオリイカ":   ["型","型","型","型","型","数","数","数","数","型","型","型"],
    "キハダマグロ": ["数","数","数","数","数","数","数","型","型","数","数","数"],
    "イナダ":       ["数","数","数","数","数","数","数","数","型","型","数","数"],
    "カツオ":       ["数","数","数","数","数","数","数","数","数","数","数","数"],
    "シーバス":     ["数","数","数","数","数","数","数","数","数","数","数","数"],
    "ムギイカ":     ["数","数","数","数","数","数","数","数","数","数","数","数"],
    "シイラ":       ["数","数","数","数","数","数","数","数","数","数","数","数"],
    "トラフグ":     ["型","型","型","型","数","数","数","数","数","数","数","型"],
    "ブリ":         ["型","型","型","数","数","数","数","数","数","数","型","型"],
    "ショウサイフグ":["数","数","数","数","数","数","数","数","数","数","数","数"],
    "カマス":       ["数","数","数","数","数","数","数","数","数","数","数","数"],
    "イシモチ":     ["数","数","数","数","数","数","数","数","数","数","数","数"],
    "ハナダイ":     ["数","数","数","数","数","数","数","数","数","数","数","数"],
    "アナゴ":       ["数","数","数","数","数","数","数","数","数","数","数","数"],
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


def compute_fish_month_size_records(fish, hist_rows):
    """fish 全エリアの過去CSV から、size_max が記録されている月別件数を返す（list[12]）"""
    counts = [0] * 12
    for r in hist_rows:
        if r.get("tsuri_mono") != fish:
            continue
        try:
            sz_mx = float(r.get("size_max") or 0)
        except (ValueError, TypeError):
            sz_mx = 0
        if sz_mx <= 0:
            continue
        d = r.get("date", "")
        try:
            mm = int(d.split("/")[1])
            if 1 <= mm <= 12:
                counts[mm - 1] += 1
        except (ValueError, IndexError):
            continue
    return counts


def compute_combo_month_size_records(fish, area, hist_rows):
    """fish × area の過去CSV から、size_max が記録されている月別件数を返す（list[12]）"""
    counts = [0] * 12
    for r in hist_rows:
        if r.get("tsuri_mono") != fish:
            continue
        if r.get("area") != area:
            continue
        try:
            sz_mx = float(r.get("size_max") or 0)
        except (ValueError, TypeError):
            sz_mx = 0
        if sz_mx <= 0:
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
    # T37 (2026/05/13): N=0 専用早期 return。
    # シーズンオフ魚種（アオリイカ等）が直近7日0件のとき、
    # 「普通の状況」「少なめ」「腕次第で差が出る」等の不適切な文言を完全に回避する。
    # season_tier (off/dead/na vs peak/good/mid) で文言を分岐。
    if count == 0:
        if season_tier in ("off", "dead", "na"):
            return (
                f"{fish}は今週0便の釣果報告。\n"
                f"シーズン外のため船宿の出船自体が少なく、釣果データが集まっていない時期。\n"
                f"本格的なシーズンインまで待つのが現実的。"
            )
        else:
            # 期待月（peak/good/mid）なのに0件 = 海況不良・船宿休業等
            return (
                f"{fish}は今週0便の釣果報告。\n"
                f"本来は釣れる時期だが、海況や出船状況の影響で報告が上がっていない。\n"
                f"船宿に直接最新状況を確認してから出船判断するのが安全だ。"
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
        s2 = f"{fish}の釣果報告は今週{N}便と少なめです。本格的なシーズンに向けてデータを注視中です。"
    elif N >= 5 and wow_ratio >= 1.5:
        # パターン3: シーズン序盤・急増（P1 より優先）
        s2 = (
            f"{fish}の釣果報告が増え始めており、今週は{N}便を記録しました。"
            f"水温の上昇とともに本格的なシーズン到来が期待されます。"
        )
    elif N >= 30 and wow_ratio >= 1.2:
        # パターン1: シーズン最盛期・数釣り好調
        max_str = f"{max_v}匹超えの実績も出ており、" if max_v else ""
        s2 = (
            f"今週は{N}便と多くの釣果報告が集まり、活性が高い状態が続いています。"
            f"{area_str}{max_str}{fish}のシーズンが本格化しています。"
        )
    elif N >= 5 and wow_ratio < 0.7:
        # パターン4: シーズン終盤・終了間近
        s2 = (
            f"{fish}は今週{N}便の釣果報告がありましたが、先週比で減少傾向にあります。"
            f"シーズン終盤に入りつつある状況で、出かけるなら早めが得策です。"
        )
    elif N >= 10 and 0.8 <= wow_ratio < 1.2:
        # パターン2: シーズン中・平常運転（レンジ表記あり）
        s2 = (
            f"{fish}は今週{N}便の釣果報告がありました。"
            f"潮回りや時合によって差が出やすい時期です。"
        )
    else:
        # フォールバック（P2 相当・N5〜9 でwow_ratio 0.7〜1.5）
        s2 = f"今週は{N}便の釣果報告がありました。"

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

        # 個人釣果のみ（純船中は除外・個人レンジ併記便は含む）で統計
        personal = [c for c in catches if _cnt_personal(c.get("count_range"))]
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
        if _cnt_personal(cr): max_count = max(max_count, cr["max"])
    for c in _top:
        cr = c.get("count_range")
        cnt = fmt_count(c)
        is_top = _cnt_personal(cr) and cr["max"] == max_count and max_count > 0
        is_dim = not cr or "不明" in c["fish"]
        sz_cm = fmt_size_cm(c)
        sz_kg = fmt_size_kg(c)
        hl = ' class="highlight"' if is_top else (' class="dim"' if is_dim else "")
        max_val = cr["max"] if _cnt_personal(cr) else 0
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
    # 2026/05/22 修正: 朝10時前 (0:00〜9:59) は表示用『今日』を前日にシフト。
    # 船宿は釣果ブログを翌朝に投稿することが多く、深夜〜早朝の HTML 生成では
    # 当日データがほぼ無く HERO/ZONE B/B2 が空表示になっていたため。
    today_str_local = _display_today_str(now)
    SPARSE_THRESHOLD = 30
    # T19 (2026/05/09): hero_label / hero_date を冒頭で確定。
    # ZONE B ミニバー軸 / fish_others / 概況 / セクション見出し で使用するため。
    today_str = today_str_local
    hero_base, hero_label, hero_date = _resolve_display_dataset(catches, today_str)
    # 2026/05/16 修正: sparse 判定を hero_date 基準に変更。
    # 当日0件で前日にフォールバックした場合、前日データが充実していれば sparse 扱いにしない。
    # （旧仕様だと「5/15 釣れている魚」見出しのまま 7日max が出て、5/14 ピークの 132 等が紛れ込む）
    hero_with_fish = sum(1 for c in catches
                         if c.get("date") == hero_date
                         and any(f != "不明" for f in (c.get("fish") or [])))
    is_sparse_today = hero_with_fish < SPARSE_THRESHOLD
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
    # T37 (2026/05/13): pageID=1 が古い釣果を返す船宿対策（T34/T35 拡張）。
    # シーズンオフ魚種（アオリイカ等）が「直近7日0件」なのに index 魚種カードに
    # 「7件・3船宿」と表示される regression を防ぐ。catches 側に2025/11等の古いレコードが
    # 混入していると merged にも残る → fish_summary でカード生成される。今日含む7日窓で限定。
    _cutoff_date_T37 = (now - timedelta(days=6)).strftime("%Y/%m/%d")
    catches_for_summary = [c for c in merged if c.get("date", "") >= _cutoff_date_T37]

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
            if _cnt_personal(c.get("count_range"))
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
        # 2026/05/16 修正: sparse でなければカードの数値は hero_date 当日のみで集計。
        # 7日窓のままだと「5/15 釣れている魚」見出しなのに 5/14 ピークの値が出るバグの解消。
        _cs_scope = [c for c in cs if c.get("date") == hero_date] if not is_sparse_today else cs
        # 2026/05/20 修正: 当日釣果ゼロの魚は "{date} 釣れている魚" セクションから除外。
        # 7日集計値しかない魚が当日セクションに混入すると「釣れている魚」の意味が破綻するため。
        if not _cs_scope and not is_sparse_today:
            continue
        _cs_p = [c for c in _cs_scope if _cnt_personal(c.get("count_range"))]
        _mn = None
        _mx = None
        if _cs_p:
            _mns = [c["count_range"].get("min") for c in _cs_p if c["count_range"].get("min") is not None]
            _mxs = [c["count_range"].get("max") for c in _cs_p if c["count_range"].get("max") is not None]
            if _mns: _mn = int(min(_mns))
            if _mxs: _mx = int(max(_mxs))
        # this_w.max は週max なので sparse 時のみ採用（hero_date 当日値を尊重）
        if is_sparse_today and this_w and (this_w.get("max") or 0):
            _mx = int(this_w.get("max"))
        if _mn is not None and _mx is not None and _mn != _mx:
            cnt_range_str = f"{_mn}〜{_mx}匹"
        elif _mx is not None:
            cnt_range_str = f"{_mx}匹"
        else:
            # fallback: 当日スコープ件数を優先。0件なら「今週N件」と明示して7日集計と分かるようにする。
            cnt_range_str = f"今週{len(cs)}件" if not _cs_scope else f"{len(_cs_scope)}件"
        # 当日スコープが空のとき「釣果0件・0船宿」を出さない（件数との矛盾を防ぐ）
        # T41 (2026/05/31): 「便数」= ユニーク(ship,date,trip_no) で count に統一。
        # 旧: len(_cs_scope) は merged 重複や同便複数 fish_raw でインフレして
        #     x_post「N便」と食い違っていた（マダイ 5/30: x_post 18便 vs index 27件）。
        _unique_trips = {
            (c.get("ship"), c.get("date"), c.get("trip_no"))
            for c in _cs_scope
        }
        _scope_small = (
            f' <small>{len(_unique_trips)}便・{len({c["ship"] for c in _cs_scope})}船宿</small>'
            if _cs_scope else ""
        )
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
            _v = (_cr["max"] if _cnt_personal(_cr) else 0) or 0
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
            f'<div class="fr">{cnt_range_str}{_scope_small}</div>'
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
    # 2026/05/20 修正: today_str (実日付) ではなく hero_date で絞る。
    # hero_date が前日に解決された場合 today_str でフィルタすると空になり 0件になるため。
    if is_sparse_today:
        today_catches = catches_for_summary
    else:
        today_catches = [c for c in catches if c.get("date") == hero_date]
    area_today_html = ""
    area_fish_map = {}  # area -> {fish: count}
    for c in today_catches:
        for f in c["fish"]:
            if f not in ("不明", "欠航", "NULL"):
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
            f'<img src="assets/fish/{fish_img_slug(f)}/{fish_img_slug(f)}_emoji.webp" alt="{f}" class="at-ftag-emoji" width="12" height="12" loading="lazy" decoding="async" onerror="this.style.display=\'none\'">{f}</a>'
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
    # V2 ティザー（SHOW_PAID_TEASER で表示制御・有料オープン時に復活）
    teaser_html = build_teaser_rotator_html() if SHOW_PAID_TEASER else ""
    # R3 (2026/05/06): 今週末の見どころ TOP3
    top_combos_html = build_top_combos_html(catches_for_summary, history, now)
    surge_combos_html = build_surge_combos_html(catches_for_summary, history, now)
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
            if f in ("不明", "欠航", "NULL") or not ship or not n:
                continue
            _ticker_candidates.append((f, ship, int(n)))
    # 魚種×船宿でユニーク化し件数上位5件
    _seen_ticker = set()
    _ticker_items_list = []
    for f, s, n in sorted(_ticker_candidates, key=lambda x: -x[2]):
        key = (f, s)
        if key not in _seen_ticker:
            _seen_ticker.add(key)
            _ticker_items_list.append(f'<span>{hero_label} <img src="assets/fish/{fish_img_slug(f)}/{fish_img_slug(f)}_emoji.webp" alt="{f}" class="lt-emoji" width="16" height="16" loading="lazy" decoding="async" onerror="this.style.display=\'none\'">{f} × {s} {n}匹</span>')
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
            if f in ("不明", "欠航", "NULL"):
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
            f'<div class="live-track">{ticker_items}<span class="lt-dup" aria-hidden="true">{ticker_items}</span></div>'
            f'</div>'
            f'</div>'
        )
    index_extra_css = """.hero{background:linear-gradient(135deg,var(--accent),var(--accent2));color:#fff;text-align:center;padding:24px 14px 0}
.hero-sub{font-size:12px;color:rgba(255,255,255,.6);margin:0;font-weight:400}
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
.lt-dup{display:contents}
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
.fc .bars .b.weekend{opacity:.85;background:var(--weekend)}
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
.ship-chips .ship-cnt{font-size:10px;color:var(--cta);font-weight:700}
.komase-sim-card-section{margin:16px 0;padding:0 12px}
.komase-sim-card{display:block;padding:16px;background:linear-gradient(135deg,#0b1d33 0%,#14406a 100%);color:#f3ead7;border-radius:8px;text-decoration:none;position:relative;overflow:hidden;transition:box-shadow .2s,transform .2s}
.komase-sim-card:hover{box-shadow:0 4px 12px rgba(0,0,0,.3);transform:translateY(-1px)}
.kc-badge{display:inline-block;padding:2px 8px;background:#c84427;color:#fff;font-size:11px;font-weight:700;border-radius:3px;margin-bottom:6px}
.komase-sim-card h3{margin:6px 0;font-size:18px;color:#f3ead7}
.komase-sim-card p{margin:6px 0;font-size:13px;line-height:1.6;color:#e7dcc3}
.kc-cta{display:inline-block;margin-top:8px;padding:6px 14px;background:#c84427;color:#fff;border-radius:3px;font-weight:700;font-size:13px}
@media(max-width:600px){.komase-sim-card h3{font-size:16px}.komase-sim-card p{font-size:12px}}"""
    # GSC 404 修正 (2026/05/28): SearchAction を削除（サイト内検索エンドポイントが
    # 無いため {search_term_string} placeholder を Google が literal URL としてクロール
    # → /fish/{search_term_string}.html が 404 として GSC に記録されていた）。
    # 本サイトに検索フォームが追加されたら適切な urlTemplate で復活させる。
    jsonld_website = f'{{"@context":"https://schema.org","@type":"WebSite","name":"船釣り予想","url":"{SITE_URL}/"}}'
    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
  <meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="icon" href="/favicon.ico" sizes="48x48"><link rel="apple-touch-icon" href="/apple-touch-icon.png">
  <title>関東船釣り釣果情報 | 今日何が釣れてる？ | 船釣り予想</title>
  <meta name="description" content="関東エリア（神奈川・東京・千葉・茨城）の船宿釣果を毎日更新。今日釣れている魚・エリア別速報・船宿ランキング。">
  <link rel="canonical" href="{SITE_URL}/">
  {_build_share_meta(
      title="関東船釣り釣果情報 | 今日何が釣れてる？",
      desc="関東エリアの船宿釣果を毎日自動集計。今日釣れている魚・エリア別速報。",
      url=f"{SITE_URL}/",
      og_image=(_latest_x_post_image_url() or OGP_DEFAULT_IMG),
  )}
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
  <h1 class="hero-sub">関東船釣り釣果情報・予想</h1>
  <div class="n">{hero_count}<u>件</u></div>
  <div class="info">
    <span class="dot"></span>
    <span>{hero_label}の釣果報告 — {hero_ships}船宿・{hero_areas}エリア</span>
  </div>
  <div class="updated">最終更新: {crawled_at} JST</div>
{live_ticker_html}
</div>
<div class="c">
{_build_share_buttons(
    share_text="今日の関東船釣り釣果まとめ | 船釣り予想",
    share_url=f"{SITE_URL}/",
)}
<!-- TOP COMBOS: R3 今週末の見どころ -->
{top_combos_html}
{surge_combos_html}
<!-- ZONE B: 釣れている魚 -->
<h2 class="st">{"直近1週間 釣れている魚" if is_sparse_today else f"{hero_label} 釣れている魚"} <span class="tag free">無料</span></h2>
<div class="fish-grid">{cards}</div>
{fish_others_html}
<!-- ZONE B2: エリア別今日の釣果 -->
<h2 class="st">{"エリア別 直近1週間の釣果" if is_sparse_today else f"エリア別 {hero_label}の釣果"} <span class="tag free">無料</span></h2>
<div class="area-today">{area_today_html}</div>
{f'<h2 class="st">広域 出船リスク速報 <span class="tag free">無料</span></h2><p class="section-note">各海域で<strong>最も荒れるエリアを基準</strong>に表示しています（安全側）。エリア別の出船可否は<a href="/forecast/">予報ページ</a>でご確認ください。</p>{risk_grid_html}' if risk_grid_html else ''}
<!-- TEASER ROTATOR -->
{teaser_html}
<!-- 広告① -->
<ins class="adsbygoogle" style="display:block;min-height:0;height:auto" data-ad-client="ca-pub-7406401300491553" data-ad-slot="auto" data-ad-format="auto" data-full-width-responsive="true"></ins>
<script>(adsbygoogle=window.adsbygoogle||[]).push({{}});</script>
<!-- 概況テキスト -->
{overview_html}
<!-- NEW: コマセシミュレーターカード -->
<section class="komase-sim-card-section">
  <a href="/komase-sim/" class="komase-sim-card" aria-label="マダイコマセシミュレーターを開く">
    <span class="kc-badge">🆕 NEW</span>
    <h3>🎣 マダイコマセシミュレーター</h3>
    <p>ハリス・ガン玉・しゃくり方を変えると、コマセ帯と付けエサの「同調」がどう変わるか。物理シミュで可視化する無料ツール。</p>
    <span class="kc-cta">試してみる →</span>
  </a>
</section>
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

def _is_plausible_size_cm(lo, hi):
    """size_cm ペアが妥当か判定。抽出失敗の典型パターン（「5〜5cm」等の単一極小値）を除外。

    船釣り対象魚で 10cm 未満の単一値は抽出ロジックの誤拾い（水深・船便番号等を size と誤読）
    が圧倒的に多い。10cm 以上のレンジは正常データとみなす。
    """
    if lo is None or hi is None:
        return False
    if lo <= 0 or hi <= 0:
        return False
    # 単一極小値（5〜5cm 等）は抽出失敗の可能性大
    if lo == hi and lo < 10:
        return False
    return True


def _aggregate_area_cmp_from_catches(catches_list):
    """catches dict 形式（catches.json/recent_fp 由来）から area_cmp 用集計を返す。

    戻り値: {area_name: {"hi":[], "lo":[], "sz_hi":[], "sz_lo":[], "kg_hi":[], "kg_lo":[],
                        "ships":[], "trips":int}}
    is_boat=True の便は cnt 集計から除外（船全体集計は個人釣果と粒度が違うため）。
    size_cm / weight_kg 両方を拾い、表示時に cm 優先 → kg フォールバックで型表示する。
    size 外れ値（_is_plausible_size_cm で False）は除外。
    """
    area_dict = {}
    for c in catches_list:
        area = (c.get("area") or "").strip()
        if not area:
            continue
        d = area_dict.setdefault(area, {"hi": [], "lo": [], "sz_hi": [], "sz_lo": [],
                                        "kg_hi": [], "kg_lo": [], "ships": [], "trips": 0})
        cr = c.get("count_range")
        if _cnt_personal(cr):
            if cr.get("max") is not None: d["hi"].append(cr["max"])
            if cr.get("min") is not None: d["lo"].append(cr["min"])
        sz = c.get("size_cm")
        if sz and _is_plausible_size_cm(sz.get("min"), sz.get("max")):
            d["sz_lo"].append(sz["min"])
            d["sz_hi"].append(sz["max"])
        kg = c.get("weight_kg")
        if kg:
            if kg.get("min") is not None and kg["min"] > 0: d["kg_lo"].append(kg["min"])
            if kg.get("max") is not None and kg["max"] > 0: d["kg_hi"].append(kg["max"])
        sname = (c.get("ship") or "").strip()
        if sname and sname not in d["ships"]:
            d["ships"].append(sname)
        d["trips"] += 1
    return area_dict


def _aggregate_area_cmp_from_hist(fish, hist_rows, days=365):
    """過去N日の CSV 履歴（dict 形式）から area_cmp 用集計を返す。

    catches dict 経由と同じ戻り値形式で _render_area_cmp_rows に渡せる。
    cnt_max/cnt_min/size_min/size_max の各列を読む。is_boat=1 は cnt 集計から除外。
    """
    if not hist_rows or not fish:
        return {}
    try:
        cutoff_dt = (datetime.now(JST).replace(tzinfo=None) - timedelta(days=days))
        cutoff = cutoff_dt.strftime("%Y/%m/%d")
    except Exception:
        cutoff = ""
    area_dict = {}
    for r in hist_rows:
        if r.get("tsuri_mono") != fish:
            continue
        d = r.get("date", "")
        if cutoff and d < cutoff:
            continue
        area = (r.get("area") or "").strip()
        if not area:
            continue
        ad = area_dict.setdefault(area, {"hi": [], "lo": [], "sz_hi": [], "sz_lo": [],
                                          "kg_hi": [], "kg_lo": [], "ships": [], "trips": 0})
        if _cnt_personal_csv(r):
            try:
                cmax = r.get("cnt_max", "")
                if cmax not in ("", None):
                    ad["hi"].append(int(float(cmax)))
            except (ValueError, TypeError):
                pass
            try:
                cmin = r.get("cnt_min", "")
                if cmin not in ("", None):
                    ad["lo"].append(int(float(cmin)))
            except (ValueError, TypeError):
                pass
        # size_cm: 妥当性チェック後にペアで追加（外れ値「5〜5cm」等を除外）
        _smin_v = None
        _smax_v = None
        try:
            smin = r.get("size_min", "")
            if smin not in ("", None):
                _smin_v = float(smin)
        except (ValueError, TypeError):
            pass
        try:
            smax = r.get("size_max", "")
            if smax not in ("", None):
                _smax_v = float(smax)
        except (ValueError, TypeError):
            pass
        if _is_plausible_size_cm(_smin_v, _smax_v):
            ad["sz_lo"].append(_smin_v)
            ad["sz_hi"].append(_smax_v)
        try:
            kmin = r.get("kg_min", "")
            if kmin not in ("", None):
                v = float(kmin)
                if v > 0:
                    ad["kg_lo"].append(v)
        except (ValueError, TypeError):
            pass
        try:
            kmax = r.get("kg_max", "")
            if kmax not in ("", None):
                v = float(kmax)
                if v > 0:
                    ad["kg_hi"].append(v)
        except (ValueError, TypeError):
            pass
        ship = (r.get("ship") or "").strip()
        if ship and ship not in ad["ships"]:
            ad["ships"].append(ship)
        ad["trips"] += 1
    return area_dict


def _render_area_cmp_rows(area_dict, max_areas=20, depth=1, fish=None):
    """area_dict（{area: {hi, lo, sz_hi, sz_lo, ships, trips}}）から area_cmp の HTML rows を生成。

    ネストアンカー回避のため、親 <div class="ar"> + 内部に <a class="ar-name"> と <a> (船宿リンク) を並列配置。
    fish を指定した場合、fish_area ページが存在するエリアに「{エリア}の{魚種}釣果」リンク（ar-fa）を追加（T29）。
    """
    if not area_dict:
        return ""
    rows = ""
    for aname, ad in sorted(area_dict.items(), key=lambda x: -(max(x[1]["hi"] or [0])))[:max_areas]:
        # 匹数レンジ
        a_lo = int(min(ad["lo"])) if ad["lo"] else None
        a_hi = int(max(ad["hi"])) if ad["hi"] else None
        if a_lo is not None and a_hi is not None and a_lo != a_hi:
            a_range = f"{a_lo}〜{a_hi}匹"
        elif a_hi is not None:
            a_range = f"{a_hi}匹"
        else:
            a_range = "—"
        # 型レンジ: cm 優先、無ければ kg にフォールバック（マダイ等は kg 表記が主流）
        sz_str = ""
        if ad["sz_hi"]:
            _szlo_src = ad["sz_lo"] if ad["sz_lo"] else ad["sz_hi"]
            sz_lo = int(min(_szlo_src))
            sz_hi = int(max(ad["sz_hi"]))
            if sz_lo and sz_lo != sz_hi:
                sz_str = f"{sz_lo}〜{sz_hi}cm"
            else:
                sz_str = f"{sz_hi}cm"
        elif ad.get("kg_hi"):
            _kglo_src = ad["kg_lo"] if ad["kg_lo"] else ad["kg_hi"]
            kg_lo = min(_kglo_src)
            kg_hi = max(ad["kg_hi"])
            # 小数1桁・末尾の .0 は除去
            def _fmt_kg(v):
                s = f"{v:.1f}"
                return s[:-2] if s.endswith(".0") else s
            if kg_lo != kg_hi:
                sz_str = f"{_fmt_kg(kg_lo)}〜{_fmt_kg(kg_hi)}kg"
            else:
                sz_str = f"{_fmt_kg(kg_hi)}kg"
        sz_html = f'<span class="ar-size">{sz_str}</span>' if sz_str else '<span class="ar-size"></span>'
        # 便数
        trip_str = f"{ad['trips']}便"
        # 船宿リンク（最大5・以降は ほかN船宿）
        ship_links_list = [_ship_link(s, depth=depth) for s in ad["ships"][:5]]
        ships_str = "、".join(ship_links_list)
        if len(ad["ships"]) > 5:
            ships_str += f'<span class="ar-more"> ほか{len(ad["ships"]) - 5}船宿</span>'
        area_href = ("../" * depth if depth > 0 else "") + f"area/{area_slug(aname)}.html"
        # T29: fish_area ページが存在する場合のみ「{エリア}の{魚種}釣果」リンクを追加。
        # ネストアンカー回避: <span class="ar-fa"> として <a class="ar-name"> と並列配置。
        ar_fa_html = ""
        if fish and aname in _AREA_ROMAJI:
            _fa_file = os.path.join(WEB_DIR, f"fish_area/{fish_slug(fish)}-{area_slug(aname)}.html")
            if os.path.exists(_fa_file):
                _fa_href = ("../" * depth if depth > 0 else "") + f"fish_area/{fish_slug(fish)}-{area_slug(aname)}.html"
                ar_fa_html = f'<span class="ar-fa"><a href="{_fa_href}">{aname}の{fish}釣果</a></span>'
        rows += (
            f'<div class="ar">'
            f'<a class="ar-name" href="{area_href}">{aname}</a>'
            f'<span class="ar-range">{a_range}</span>'
            f'{sz_html}'
            f'<span class="ar-trips">{trip_str}</span>'
            f'<span class="ar-ships">{ships_str}</span>'
            f'{ar_fa_html}'
            f'</div>'
        )
    return rows


def build_fish_pages(data, history, crawled_at="", hist_rows=None, fish_area_summary=None, fish_top_areas=None):
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
    fish_content_all = load_fish_content()  # 魚種別固定文（月1見直し・2026-06-11）
    fixed_faq_data = _load_fixed_faq()
    # 過去CSV（引数で渡された共有キャッシュを使用、なければ個別ロード）
    _hist_rows_for_fish = hist_rows if hist_rows is not None else _load_historical_catches()
    # T38-A9: fish_area_summary は将来「chip 便数表示の高速化」等に活用予定（現状未使用）
    _ = fish_area_summary  # mark as intentionally unused
    _fish_top_areas = fish_top_areas or {}
    # T38 fish-related 上段判定用: 直近7日 catches を 1回ロード（魚種ループ内の重複排除）
    # 旧仕様（catches=当該魚種便のみ）では「アマダイ単独便」の場合 _week_cooc_fish が常に空となり
    # 共起魚種が全件下段（折り畳み）に行く問題があった（2026/05/14 ユーザー指摘）。
    # 主要エリアの全 catches を見るように修正。
    _recent7_for_related = _load_recent_catches_for_index(now, days=7)
    fish_summary = {}
    _SKIP_FISH = {"不明", "欠航", "NULL"}

    # 個別 fish ページは「直近7日間の釣果推移」チャート + マイナー魚種（マダコ・
    # マゴチ等の当日0件魚）への配慮で、常時 7日マージを行う。
    # 旧仕様: 当日 catches >= 30件のとき merge skip → 当日0件のマイナー魚種が
    # placeholder 経路に流れる regression があった（2026/05/06 ユーザー指摘）。
    # 常時マージで全魚種に直近1週間データが揃う（再クロールなし・save_daily_csv の蓄積を流用）。
    try:
        _recent7_fp = _load_recent_catches_for_index(now, days=7)
    except Exception:
        _recent7_fp = []

    # 2026/05/13 修正: valid_catches を直近7日窓に絞る。
    # fishing-v.jp の船宿ページは最新ページ(pageID=1)を返す仕様だが、
    # シーズンオフ魚種では数ヶ月前の釣果が最新ページに残ったまま更新されない
    # 場合があり、当日クロール結果に混入する。これにより
    # _resolve_display_dataset が「最新日=半年前」とフォールバックし、
    # HERO サブライン・7日チャート・area-cmp・ship-rank が
    # 一斉に半年前基準で描画される regression が発生した
    # （fish/アオリイカ.html・fish/シロアマダイ.html で確認）。
    # 直近7日窓に絞れば、シーズンオフ魚種は len(catches)<1 経路
    # (placeholder形式) に自動的に流れる。
    _fish_cutoff_date = (now - timedelta(days=6)).strftime("%Y/%m/%d")  # today含めて7日
    data_recent = [c for c in data if c.get("date", "") >= _fish_cutoff_date]

    seen_fp = {(c.get("ship"), c.get("date"), c.get("fish_raw", "")) for c in data_recent}
    merged_data = list(data_recent)
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
        # 魚種別固定文（プレースホルダ解決済み・無い魚種は空 dict）
        fc = fish_content_all.get(fish) or {}
        # catches=0 でもメバル形式（rich path）で統一。
        # 過去1年サマリーを HERO / comment 文言に使うために先取りする。
        _fish_hist_0 = None
        if len(catches) < 1:
            _fish_hist_0 = _summarize_fish_history(fish, _hist_rows_for_fish, now)
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
        # V2: 今日・今週の集計（朝10時前は前日を『今日』として表示）
        today_str_f = _display_today_str(now)
        today_catches_f, fish_today_label, fish_display_date_str = _resolve_display_dataset(catches, today_str_f)
        max_cnt = 0
        for c in catches:
            cr = c.get("count_range")
            if _cnt_personal(cr): max_cnt = max(max_cnt, cr["max"])
        # fish-hero 数値: **トップページ ZONE B カードと完全一致させる**ため、
        # 同じ catches （魚種フィルタ済み）を使って min/max を直接集計する。
        # 補遺3 (2026/05/08): avg/平均 は出さず min〜max のみ表示。
        # this_w に min が無いため、min は catches から計算。max は this_w 優先。
        cnt_range_str = ""
        w_p = [c for c in catches if _cnt_personal(c.get("count_range"))]
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
        elif catches:
            cnt_range_str = f"釣果{len(catches)}便"
        else:
            # catches=0: fh-r に過去1年件数を表示（_fish_hist_0 が設定済みのはず）
            _py_n = (_fish_hist_0 or {}).get("recent_365_records", 0)
            cnt_range_str = f"過去1年 {_py_n:,}件" if _py_n else ""
        # サイズ: catches から min〜max レンジを優先、無ければ this_w.size_avg を fallback
        # 外れ値「5〜5cm」等の抽出失敗パターンは _is_plausible_size_cm で除外
        sz_str = ""
        _sz_pairs = [(c["size_cm"]["min"], c["size_cm"]["max"])
                     for c in catches
                     if c.get("size_cm")
                     and c["size_cm"].get("min") is not None
                     and c["size_cm"].get("max") is not None
                     and _is_plausible_size_cm(c["size_cm"]["min"], c["size_cm"]["max"])]
        if _sz_pairs:
            _sz_lo = int(min(p[0] for p in _sz_pairs))
            _sz_hi = int(max(p[1] for p in _sz_pairs))
            sz_str = f"{_sz_lo}〜{_sz_hi}cm" if _sz_lo != _sz_hi else f"{_sz_hi}cm"
        elif this_w and this_w.get("size_avg"):
            sz_str = f"{this_w['size_avg']:.0f}cm"
        # area-cmp 充足版: 3段階フォールバック
        # Stage 1: today_catches_f（_resolve_display_dataset の最新日 or 7日窓）
        # Stage 2: catches 全体（直近7日マージ済）
        # Stage 3: _hist_rows_for_fish から過去1年集計（CSV）
        area_today_f = _aggregate_area_cmp_from_catches(today_catches_f)
        area_label = f"エリア別の{fish_today_label}の釣果"
        if not area_today_f and catches:
            area_today_f = _aggregate_area_cmp_from_catches(catches)
            if area_today_f:
                area_label = "エリア別の直近1週間の釣果"
        if not area_today_f:
            area_today_f = _aggregate_area_cmp_from_hist(fish, _hist_rows_for_fish, days=365)
            if area_today_f:
                area_label = "過去1年の主なエリアと釣果"
        area_cmp_rows = _render_area_cmp_rows(area_today_f, max_areas=20, depth=1, fish=fish)
        area_cmp_html = f'<div class="area-cmp"><h3>{area_label}</h3>{area_cmp_rows}</div>' if area_cmp_rows else ""
        # ship-rank（今週・今日優先）
        ship_data_f: dict = {}
        for c in catches:
            d = ship_data_f.setdefault(c["ship"], {"cnt": 0, "cnt_his": [], "cnt_los": [], "sz_his": [], "sz_los": [], "kg_his": [], "kg_los": [], "pts": [], "area": "", "today": False})
            d["cnt"] += 1
            if not d["area"] and c.get("area"): d["area"] = c["area"]
            cr = c.get("count_range")
            if _cnt_personal(cr):
                d["cnt_his"].append(cr["max"])
                d["cnt_los"].append(cr.get("min", cr["max"]))
            sz = c.get("size_cm")
            if sz:
                if sz.get("max") is not None:
                    d["sz_his"].append(sz["max"])
                if sz.get("min") is not None:
                    d["sz_los"].append(sz["min"])
            wkg = c.get("weight_kg")
            if wkg:
                if wkg.get("max") is not None:
                    d["kg_his"].append(wkg["max"])
                if wkg.get("min") is not None:
                    d["kg_los"].append(wkg["min"])
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
            sz_lo = int(min(sd["sz_los"])) if sd["sz_los"] else None
            sz_hi = int(max(sd["sz_his"])) if sd["sz_his"] else None
            if sz_lo is not None and sz_hi is not None and sz_lo != sz_hi:
                sz_range = f"{sz_lo}〜{sz_hi}cm"
            elif sz_hi is not None:
                sz_range = f"{sz_hi}cm"
            else:
                kg_lo = sd["kg_los"] and min(sd["kg_los"])
                kg_hi = sd["kg_his"] and max(sd["kg_his"])
                if kg_lo and kg_hi and round(kg_lo, 1) != round(kg_hi, 1):
                    sz_range = f"{kg_lo:.1f}〜{kg_hi:.1f}kg"
                elif kg_hi:
                    sz_range = f"{kg_hi:.1f}kg"
                else:
                    sz_range = ""
            top_pt = sd.get("area", "")
            sr_items += (
                f'<div class="sr">'
                f'<span class="sr-rank">{i+1}</span>'
                f'<span class="sr-name">{_ship_link(sn, depth=1)}</span>'
                f'<span class="sr-range">{s_range}</span>'
                + (f'<span class="sr-size">{sz_range}</span>' if sz_range else "")
                + f'<span class="sr-pt">{top_pt}</span></div>'
            )
        ship_rank_html = f'<div class="ship-rank"><h3>船宿ランキング（今週）</h3>{sr_items}</div>' if sr_items else ""
        # 有料ティザー
        fish_teaser_html = "" if not SHOW_PAID_TEASER else (
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
        # P3 (2026/05/31): title/description を「関東」クエリ適合に強化（GSC SEO改善 3/4）
        # GSC 実クエリ「{魚種} 釣果 関東」「{魚種} 船釣り 関東」が pos7-10位で埋もれていた。
        # 語順を魚種先頭にし「関東」を独立キーワード化（旧「関東の{魚種}釣果」は前置で弱い）。
        # 出船状況で4分岐（P2 fish_area と同型・N=0 で薄ページ露呈を防ぐ）。
        # description に5県横断を明示し競合（個別船宿サイト）との独自価値を言語化。
        # 数値は全て実測/3年累計=事実（無料=事実の方針）。
        _hist_cnt_fish = len([r for r in _hist_rows_for_fish if r.get("tsuri_mono") == fish])
        _kanto_note = "神奈川・東京・千葉・茨城・静岡の5県を横断集計。"
        if len(catches) >= 1 and max_cnt > 0:
            fish_title_body = f"{fish}釣果 関東【今週{len(catches)}便・最高{int(max_cnt)}匹】"
            fish_desc = f"関東の{fish}釣果を横断集計。今週{len(catches)}便・最高{int(max_cnt)}匹。{_kanto_note}船宿別ランキング・旬カレンダーを毎日更新。"
        elif len(catches) >= 1:
            fish_title_body = f"{fish}釣果 関東【今週{len(catches)}便出船】"
            fish_desc = f"関東の{fish}釣果情報。今週{len(catches)}便出船中。{_kanto_note}船宿別ランキング・旬カレンダーを毎日更新。"
        elif _hist_cnt_fish > 0:
            fish_title_body = f"{fish}釣果 関東【過去{_hist_cnt_fish}件の実績】"
            fish_desc = f"関東の{fish}釣果情報。過去{_hist_cnt_fish}件の実績から旬カレンダーを掲載。{_kanto_note}例年の最盛期と船宿別傾向を確認できます。"
        else:
            fish_title_body = f"{fish}釣果 関東の船宿情報"
            fish_desc = f"関東の{fish}船釣り情報。{_kanto_note}旬カレンダーと船宿別ランキングを公開。"
        fish_title_str = f"{fish_title_body} | 船釣り予想"
        # T38-A6: fish-related-species（共起便数ベース・Layer 1 固定・折り畳み付き）
        _cooc_fish = compute_fish_related_via_cooccurrence(_hist_rows_for_fish, fish, _fish_top_areas)
        # 上段判定: {fish} の主要エリア（TOP-3）で直近7日に出ている魚種
        # 旧仕様（catches = 当該魚種便のみ）では「アマダイ単独便」のような状況で
        # 常に空セットになり、共起魚種が全件下段に行ってしまう問題があった。
        _top_areas_for_rel = [a for a, _n in (_fish_top_areas.get(fish) or [])[:3]]
        _week_cooc_fish = set()
        for c in _recent7_for_related:
            if c.get("area") not in _top_areas_for_rel:
                continue
            for _bf in c.get("fish", []):
                if _bf and _bf != fish and _bf != "不明":
                    _week_cooc_fish.add(_bf)
        _rel_active = []
        _rel_fold = []
        for rf, rn in _cooc_fish:
            _chip = (
                '<a href="../fish/' + fish_slug(rf) + '.html" class="chip-link">'
                + f'<img src="../assets/fish/{fish_img_slug(rf)}/{fish_img_slug(rf)}_emoji.webp" alt="{rf}" class="chip-emoji" width="14" height="14" loading="lazy" decoding="async" onerror="this.style.display=\'none\'">'
                + f'{rf}（{rn:,}便）</a>'
            )
            if rf in _week_cooc_fish:
                _rel_active.append(_chip)
            else:
                _rel_fold.append(_chip)
        if _rel_active or _rel_fold:
            _rel_parts = []
            if _rel_active:
                _rel_parts.append(f'<p class="tier-label">★ 今週実績あり（{len(_rel_active)}魚種）</p>')
                _rel_parts.append(f'<div class="chip-wrap">{"".join(_rel_active)}</div>')
            if _rel_fold:
                _rel_parts.append(
                    f'<details class="fold-chips"><summary>過去実績あり（今週ゼロ・{len(_rel_fold)}魚種）を表示</summary>'
                    f'<div class="chip-wrap">{"".join(_rel_fold)}</div></details>'
                )
            related_section_html = (
                '<section class="fish-related-species">'
                f'<h2 class="st">{fish}と合わせて釣れる魚</h2>'
                + "".join(_rel_parts)
                + '</section>'
            )
        else:
            related_section_html = ""
        # T38-A4: fish-all-areas セクション（Layer 1 固定・全履歴エリア・折り畳み付き）
        # _fish_top_areas から全エリアを取得し、直近7日にある=active / なし=fold に分類
        _week_areas_f = set(c["area"] for c in catches)  # 直近7日のエリア
        _all_areas_f = _fish_top_areas.get(fish, [])  # [(area, cnt), ...]
        _fa_active_chips = []
        _fa_fold_chips = []
        for _a, _n in _all_areas_f:
            if _a not in _AREA_ROMAJI:
                continue
            # GSC 404 修正 (2026/05/28): fish_area HTML が実際に生成されているコンボのみ
            # chip link を出力。build_fish_area_pages は 7日窓 (≥1便) かつ existing_fa_files
            # しか生成しないため、hist のみのコンボはここでスキップ。
            # ※ build_fish_area_pages → build_fish_pages 順なので _fa_exists() は正確
            if not _fa_exists(fish, _a):
                continue
            _fa_url = f"../fish_area/{fish_slug(fish)}-{area_slug(_a)}.html"
            _chip = (
                f'<a href="{_fa_url}" class="chip-link">'
                f'{_chip_pref_img(_a)}{_a}（{_n}便）</a>'
            )
            if _a in _week_areas_f:
                _fa_active_chips.append(_chip)
            else:
                _fa_fold_chips.append(_chip)
        _faa_parts = []
        if _fa_active_chips:
            _faa_parts.append(f'<p class="tier-label">★ 今週実績あり（{len(_fa_active_chips)}エリア）</p>')
            _faa_parts.append(f'<div class="chip-wrap">{"".join(_fa_active_chips)}</div>')
        if _fa_fold_chips:
            _faa_parts.append(
                f'<details class="fold-chips"><summary>過去実績あり（今週ゼロ・{len(_fa_fold_chips)}エリア）を表示</summary>'
                f'<div class="chip-wrap">{"".join(_fa_fold_chips)}</div></details>'
            )
        # 固定文: 主要エリア解説（lead 文・不変条件 #45 対象）。
        # ⚠ chip の有無（週次の釣果変動）に依存させない。fc["areas"] は月1見直しの
        #   キュレーション固定文で、#45 が常時カウントする前提。chip 不在の週に
        #   この lead が消えると固定文合計が ~50-120 字目減りし 800 字割れで CI fail する
        #   （2026-06-21 ホウボウ/メバル/ヒラマサ/カレイ で発生）。固定文は常に出力する。
        _fa_lead = (f'<p class="fish-content-lead fish-content-text">{fc["areas"]}</p>'
                    if fc.get("areas") else "")
        if _fa_lead or _faa_parts:
            fish_area_section_html = (
                '<section class="fish-areas-all">'
                f'<h2 class="st">エリア別の{fish}釣果情報</h2>'
                + _fa_lead
                + "".join(_faa_parts)
                + '</section>'
            )
        else:
            fish_area_section_html = ""
        # V2 season map / guide / FAQ / chart
        season_map_html = build_fish_season_map_html(fish, decadal_calendar, current_month, hist_rows=_hist_rows_for_fish)
        # 固定文: エリア別シーズン解説（旬カレンダー直下・不変条件 #45 対象）
        # 月報が実在する魚種のみ末尾に最新月報リンクを付ける
        season_note_html = ""
        if fc.get("season"):
            _ml = _latest_monthly_report_link(fish)
            _ml_html = (f' 月ごとの詳しい振り返りは「<a href="{_ml[0]}">{_ml[1]}</a>」で読める。'
                        if _ml else "")
            _sn_emoji = (f'<img src="../assets/fish/{fish_img_slug(fish)}/{fish_img_slug(fish)}_emoji.webp" alt="" '
                         f'class="fcn-emoji" width="16" height="16" loading="lazy" decoding="async" '
                         f'onerror="this.style.display=\'none\'">')
            season_note_html = (
                f'<div class="fish-content-note" id="fish-season-note">'
                f'<h3>{_sn_emoji}{fish}のシーズン傾向（エリア別）</h3>'
                f'<p class="fish-content-text">{fc["season"]}{_ml_html}</p></div>'
            )
        guide_html = build_fish_guide_html(fish, tackle_data, content=fc)
        auto_faq_html, auto_faq_pairs = build_fish_faq_html(fish, catches, decadal_calendar, SITE_URL, hist_rows=_hist_rows_for_fish, content_sections=fc)
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
.ar{display:flex;align-items:center;padding:9px 0;border-bottom:1px solid var(--bg);gap:8px;flex-wrap:wrap;color:inherit}
.ar:last-child{border-bottom:none}
.ar .ar-name{flex:0 0 90px;font-size:13px;font-weight:700;color:var(--cta);text-decoration:none}
.ar .ar-range{flex:0 0 80px;font-size:14px;font-weight:700;color:var(--accent)}
.ar .ar-size{flex:0 0 80px;font-size:12px;color:var(--muted)}
.ar .ar-trips{flex:0 0 48px;font-size:12px;color:var(--muted)}
.ar .ar-ships{flex:1 1 200px;font-size:12px;color:var(--sub);min-width:0;line-height:1.5}
.ar .ar-ships a{color:var(--cta);text-decoration:none}
.ar .ar-ships a:hover{text-decoration:underline}
.ar .ar-more{color:var(--muted);font-size:11px}
.ar .ar-fa{flex:0 0 auto}
.ar .ar-fa a{font-size:11px;color:var(--cta);text-decoration:none;padding:8px 12px;border:1px solid var(--cta);border-radius:10px;white-space:nowrap;display:inline-block;line-height:1.2}
.ar .ar-fa a:hover{background:var(--cta);color:#fff}
@media(max-width:520px){.ar .ar-name{flex:0 0 100%}.ar .ar-range{flex:0 0 auto}.ar .ar-size{flex:0 0 auto}.ar .ar-trips{flex:0 0 auto}.ar .ar-ships{flex:1 1 100%}.ar .ar-fa{flex:0 0 auto}}
.ship-rank{background:var(--card);border:1px solid var(--border);border-radius:var(--r);padding:14px;margin-bottom:16px}
.ship-rank h3{font-size:13px;font-weight:700;color:var(--accent);margin-bottom:10px}
.sr{display:flex;align-items:center;padding:8px 0;border-bottom:1px solid var(--bg);gap:6px}
.sr:last-child{border-bottom:none}
.sr .sr-rank{font-size:11px;font-weight:700;color:var(--muted);flex:0 0 18px;text-align:center}
.sr .sr-name{flex:0 0 80px;font-size:13px;font-weight:700;color:var(--accent)}
.sr .sr-range{flex:0 0 80px;font-size:13px;font-weight:700;color:var(--cta)}
.sr .sr-size{flex:0 0 70px;font-size:11px;color:var(--sub)}
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
.chip-pref{width:14px;height:14px;object-fit:contain;flex-shrink:0}
.chip-area{display:inline-flex;align-items:center;gap:4px}
.tier-label{font-size:11px;color:var(--muted);margin:8px 0 2px;font-weight:600}
.fold-chips{margin:4px 0 8px}
.fold-chips summary{font-size:12px;color:var(--accent);cursor:pointer;padding:4px 0}
.fold-chips .chip-wrap{margin-top:6px}
.fish-areas-all{margin-bottom:16px}.fish-related-species{margin-bottom:16px}.area-all-fish{margin-bottom:16px}
.page-h1{font-size:14px;font-weight:700;color:var(--sub);padding:8px 0 0;margin:0;line-height:1.4}
.chart7{background:var(--card);border:1px solid var(--border);border-radius:var(--r);padding:14px;margin-bottom:16px}
.chart7 h3{font-size:13px;font-weight:700;color:var(--accent);margin-bottom:8px}
.chart-bars{display:flex;align-items:flex-end;gap:3px;height:60px}
.chart-bars .cb{flex:1;background:var(--cta);border-radius:2px 2px 0 0;opacity:.7;min-width:10px}
.chart-bars .cb.weekend{opacity:.8;background:var(--weekend)}
.chart-bars .cb.today{opacity:1;background:var(--pos);outline:1.5px solid var(--accent);outline-offset:-1.5px}
.chart-labels{display:flex;justify-content:space-between;font-size:9px;color:var(--muted);margin-top:3px}
.chart-labels span.weekend{color:#c66a14}
.chart-labels span.today{color:var(--pos);font-weight:700;border-bottom:2px solid var(--pos);padding-bottom:1px}
.chart-trend{text-align:center;margin-top:6px;font-size:12px;font-weight:700;color:var(--pos)}
.chart-trend.down{color:var(--warn)}.chart-trend.flat{color:var(--sub)}
.faq-common-link{font-size:14px;color:var(--accent);margin:16px 0;padding:12px 16px;background:var(--card);border:2px solid var(--accent);border-radius:var(--r);line-height:1.6}
.related-sim{margin:20px 0;padding:14px;background:#f5f5f5;border-left:4px solid #c84427;border-radius:4px;font-size:14px}
.related-sim a{color:#0b1d33;font-weight:700;text-decoration:none}
.related-sim a:hover{text-decoration:underline}
.faq-common-link a{color:var(--cta);text-decoration:underline}
.fish-content-note{background:var(--card);border:1px solid var(--border);border-radius:var(--r);padding:14px;margin-bottom:16px}
.fish-content-note h3{font-size:13px;font-weight:700;color:var(--accent);margin-bottom:8px;display:flex;align-items:center;gap:6px}
.fcn-emoji{width:16px;height:16px;object-fit:contain}
.fg-emoji{width:16px;height:16px;object-fit:contain;vertical-align:-3px;margin-right:4px}
.fish-content-text{font-size:13px;line-height:1.9;color:var(--text)}
.fish-content-text a{color:var(--cta)}
.fish-content-lead{margin:8px 0 4px}
.tk-variant-label{font-size:12px;font-weight:700;color:var(--accent);margin:10px 0 4px}
.tk-variant:first-child .tk-variant-label{margin-top:0}
.faq-more{font-size:12px;color:var(--cta);white-space:nowrap}"""
        html = f"""<!DOCTYPE html>
<html lang="ja"><head>
  <meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="icon" href="/favicon.ico" sizes="48x48"><link rel="apple-touch-icon" href="/apple-touch-icon.png">
  <title>{fish_title_str}</title>
  <meta name="description" content="{fish_desc}">
  <link rel="canonical" href="{fish_url}">
  {_build_share_meta(
      title=fish_title_body,
      desc=fish_desc,
      url=fish_url,
      og_image=_resolve_fish_ogp_image(fish),
  )}
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
  <div class="fh-m">{'本日の釣果報告は集計待ち' if not catches else f'今週 {len(catches)}便・{len(set(c["ship"] for c in catches))}船宿'}</div>
</div>
<div class="c">
  <h1 class="page-h1">{fish}の船釣り釣果情報（関東）</h1>
  <p class="bread"><a href="../">トップ</a> &rsaquo; {fish}</p>
  <p class="area-note" style="font-size:12px;color:var(--sub);margin:4px 0 8px">神奈川・東京・千葉・茨城・静岡の5県の船宿を横断集計しています。</p>
  {_build_share_buttons(
      share_text=f"{fish}の最新釣果と旬カレンダー | 船釣り予想",
      share_url=fish_url,
  )}
  {season_entry_html}
  <h2 class="st">今週の概況 <span class="tag free">無料</span></h2>
  <div class="comment-wrap">
    <img src="../assets/fish/{fish_img_slug(fish)}/{fish_img_slug(fish)}_illustration.png" alt="{fish}" class="comment-img" width="160" height="160" loading="lazy" onerror="this.style.display='none'">
    <div class="comment"><span class="comment-fish-name">{fish}{"（" + FISH_KANJI[fish] + "）" if fish in FISH_KANJI and FISH_KANJI[fish] != fish else ""}</span>{comment}</div>
  </div>
  {chart7_html}
  {('<h2 class="st">' + fish_today_label + 'の釣果 <span class="tag free">無料</span></h2>' + (area_cmp_html if area_cmp_html else '<p style="color:var(--muted);font-size:13px;padding:8px 0">本日の釣果はまだ集計中です</p>') + ship_rank_html) if (fish_today_label and fish_today_label != '—') else ''}
  <!-- 広告① -->
  <ins class="adsbygoogle" style="display:block;min-height:0;height:auto" data-ad-client="ca-pub-7406401300491553" data-ad-slot="auto" data-ad-format="auto" data-full-width-responsive="true"></ins>
  <script>(adsbygoogle=window.adsbygoogle||[]).push({{}});</script>
  {related_section_html}
  {fish_area_section_html}
  <h2 class="st">旬カレンダー <span class="tag free">無料</span></h2>
  {season_map_html}
  {season_note_html}
  {('<h2 class="st">魚種ガイド <span class="tag free">無料</span></h2>' + guide_html) if guide_html else ''}
  {'<div class="related-sim">🎣 <a href="/komase-sim/">マダイコマセシミュレーターで仕掛けを試す →</a></div>' if fish == 'マダイ' else ''}
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

    # fish/index.html の生成は build_fish_index_html() に分離（Phase C）
    # build_fish_area_pages 完了後に呼ばれるため _fa_exists() が正確に動作する


def build_fish_index_html(now, hist_rows, fish_area_summary, recent7, fish_summary, crawled_at=""):
    """fish/index.html を生成する（Phase C: build_fish_pages から分離）。

    呼出タイミング: build_fish_area_pages 完了後に main() から呼ばれる。
    これにより _fa_exists() が全 fish_area HTML を正確に参照できる。

    Args:
        now         : datetime（JST）
        hist_rows   : _load_historical_catches() の結果（共有キャッシュ）
        fish_area_summary : {(fish, area): cnt} 過去3年集計（compute_fish_area_summary 結果）
        recent7     : _load_recent_catches_for_index(now, days=7) の結果（共有）
        fish_summary: build_fish_pages 内で構築した {fish: catches_list} キーセット（今週魚種集合）
        crawled_at  : 更新日時文字列
    """
    os.makedirs(os.path.join(WEB_DIR, "fish"), exist_ok=True)
    _SKIP_FISH = {"不明", "欠航", "NULL"}

    # ── 今週実績判定（fish_summary を使用・fish 詳細ページと同じ数値にする） ──
    # 旧実装は recent7 を再集計していたため fish/aji.html の len(catches) と
    # 数十件の差が生じることがあった。fish_summary は build_fish_pages が
    # data_for_fish から構築した同一データのため乖離ゼロになる。
    fish_week_cnt: dict[str, int] = {
        f: len(cats)
        for f, cats in fish_summary.items()
        if f not in _SKIP_FISH and not f.isdigit()
    }

    # 今週カード（fi-card: 既存構造を維持） ──
    # fish_summary はキーセットとして受け取り、今週便数で並べ直す
    all_fish_set = set(fish_summary.keys()) | {f for (f, _a) in fish_area_summary.keys()}
    # 魚種ページが存在するもののみ（_FISH_ROMAJI に登録済み）
    all_fish_set = {f for f in all_fish_set if f in _FISH_ROMAJI and f not in _SKIP_FISH}

    fish_index_cards = ""
    # 今週実績ありの魚種を便数降順でカード化
    for fish in sorted(all_fish_set, key=lambda f: (-fish_week_cnt.get(f, 0), f)):
        cnt = fish_week_cnt.get(fish, 0)
        if cnt == 0:
            continue  # fi-card は今週実績ありのみ（既存動作維持）
        fish_index_cards += (
            f'<a class="fi-card" href="{fish_slug(fish)}.html">'
            f'<div class="fi-name"><img src="../assets/fish/{fish_img_slug(fish)}/{fish_img_slug(fish)}_emoji.webp"'
            f' alt="{fish}" class="fi-emoji" width="28" height="28" loading="lazy" decoding="async"'
            f' onerror="this.style.display=\'none\'">{fish}</div>'
            f'<div class="fi-cnt">今週釣果{cnt}便</div>'
            f'</a>'
        )
    _week_active = sum(1 for f in all_fish_set if fish_week_cnt.get(f, 0) > 0)

    # ── 「魚種」セクション（Phase C 新規） ──
    # hist_rows から (fish, area) 別便数を集計
    fa_hist_cnt: dict[tuple, int] = {}  # (fish, area) -> 過去3年便数
    for (f, a), cnt in fish_area_summary.items():
        fa_hist_cnt[(f, a)] = cnt

    # fish ごとの今週エリア集合（recent7 から）
    fish_week_areas: dict[str, set] = {}  # fish -> {area, ...} 今週実績あり
    for c in recent7:
        area = c.get("area", "")
        for f in c.get("fish", []):
            if f in _SKIP_FISH or f.isdigit():
                continue
            fish_week_areas.setdefault(f, set()).add(area)

    # 対象魚種リスト: fish_area ページが1件以上存在するものだけ
    def _has_any_fa(fish):
        return any(
            _fa_exists(fish, area)
            for (_f, area) in fa_hist_cnt
            if _f == fish
        )

    target_fishes = [f for f in all_fish_set if _has_any_fa(f)]

    # 並び順: 今週実績あり → 今週便数降順、その後 → 過去3年便数降順
    def _fish_sort_key(f):
        week_cnt = fish_week_cnt.get(f, 0)
        hist_total = sum(fa_hist_cnt.get((f, a), 0)
                         for (_f, a) in fa_hist_cnt if _f == f)
        # 今週0は末尾（week_cnt=0 → sort key の第1要素を 1 にする）
        return (0 if week_cnt > 0 else 1, -week_cnt, -hist_total, f)

    target_fishes.sort(key=_fish_sort_key)

    idx_blocks_html = ""
    for fish in target_fishes:
        slug_f = fish_slug(fish)
        slug_fi = fish_img_slug(fish)

        # このfruitのエリア一覧（hist_rows 由来・便数降順）
        fish_areas_with_cnt = sorted(
            [(area, fa_hist_cnt[(fish, area)])
             for (f, area) in fa_hist_cnt
             if f == fish and _fa_exists(fish, area)],
            key=lambda x: -x[1]
        )
        if not fish_areas_with_cnt:
            continue  # 空ブロック禁止

        week_areas_set = fish_week_areas.get(fish, set())
        active_areas = [(a, cnt) for a, cnt in fish_areas_with_cnt if a in week_areas_set]
        inactive_areas = [(a, cnt) for a, cnt in fish_areas_with_cnt if a not in week_areas_set]

        week_cnt = fish_week_cnt.get(fish, 0)
        total_areas = len(fish_areas_with_cnt)

        # idx-block-h
        block_h = (
            f'<div class="idx-block-h">'
            f'<img src="../assets/fish/{slug_fi}/{slug_fi}_emoji.webp" alt="{fish}" class="ib-emoji"'
            f' width="20" height="20" loading="lazy" onerror="this.style.display=\'none\'">'
            f'<a href="{slug_f}.html">{fish}</a>'
            f'<span class="ib-cnt">今週{week_cnt}便・全{total_areas}エリア</span>'
            f'</div>'
        )

        # 上段（今週実績あり）
        if active_areas:
            active_chips = "".join(
                f'<a href="../fish_area/{slug_f}-{area_slug(a)}.html" class="chip-link chip-active">'
                f'{_chip_pref_img(a, depth=1)}'
                f'{a}（{cnt}便）'
                f'</a>'
                for a, cnt in active_areas
            )
            active_section = (
                f'<p class="tier-label">★ 今週実績あり（{len(active_areas)}エリア）</p>'
                f'<div class="chip-wrap">{active_chips}</div>'
            )
        else:
            active_section = '<p class="tier-label" style="color:#aaa;">今週実績なし</p>'

        # 下段（過去実績のみ）
        if inactive_areas:
            inactive_chips = "".join(
                f'<a href="../fish_area/{slug_f}-{area_slug(a)}.html" class="chip-link">'
                f'{_chip_pref_img(a, depth=1)}'
                f'{a}（{cnt}便）'
                f'</a>'
                for a, cnt in inactive_areas
            )
            # 今週ゼロのブロックは open（展開済み）
            open_attr = " open" if not active_areas else ""
            inactive_section = (
                f'<details class="fold-chips"{open_attr}>'
                f'<summary>過去実績あり（今週ゼロ・{len(inactive_areas)}エリア）を表示</summary>'
                f'<div class="chip-wrap">{inactive_chips}</div>'
                f'</details>'
            )
        else:
            inactive_section = ""

        idx_blocks_html += (
            f'<div class="idx-block">'
            f'{block_h}'
            f'{active_section}'
            f'{inactive_section}'
            f'</div>'
        )

    idx_all_section = ""
    if idx_blocks_html:
        idx_all_section = f"""<h2 class="st">魚種</h2>
<p class="faa-note">
  各魚種について、関東で釣れる<b>全エリアへの直リンク</b>を網羅。
  便数は過去3年の実績報告数。<b>★今週実績あり</b>を上段に、
  <b>過去実績のみ</b>を下段（折り畳み）に分離。
</p>
<div class="idx-all-grid">{idx_blocks_html}</div>"""

    # ── CSS ──
    fish_index_css = """.fi-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(130px,1fr));gap:8px;margin:16px 0}
.fi-card{background:var(--card);border:1px solid var(--border);border-radius:var(--r);padding:12px;display:block;text-decoration:none;color:inherit;transition:border-color .15s}
.fi-card:hover{border-color:var(--cta);text-decoration:none}
.fi-name{font-size:14px;font-weight:700;color:var(--accent);display:flex;align-items:center;gap:6px}
.fi-emoji{width:28px;height:28px;object-fit:contain;flex-shrink:0}
.fi-cnt{font-size:11px;color:var(--muted);margin-top:4px}
.idx-all-grid{background:var(--card);border:1px solid var(--border);border-radius:var(--r);padding:12px 14px;margin:8px 0 20px}
.idx-block{padding:8px 0;border-bottom:1px solid var(--border)}
.idx-block:last-child{border-bottom:none}
.idx-block-h{font-size:14px;font-weight:700;color:var(--accent);display:flex;align-items:center;gap:6px;padding:6px 0 4px}
.idx-block-h .ib-emoji{width:20px;height:20px;object-fit:contain}
.idx-block-h .ib-cnt{font-size:11px;color:var(--muted);font-weight:400;margin-left:auto}
.idx-block-h a{color:var(--accent);text-decoration:none}
.idx-block-h a:hover{text-decoration:underline}
.chip-link.chip-active{background:#fff8e7;border-color:#f5c542}
.chip-link.chip-active:hover{background:#fff3d0}
.faa-note{font-size:13px;color:var(--sub);margin:0 0 8px}
@media(max-width:480px){.idx-block-h .ib-cnt{display:none}}"""

    # ── HTML 組立 ──
    fish_index_html = f"""<!DOCTYPE html>
<html lang="ja"><head>
  <meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="icon" href="/favicon.ico" sizes="48x48"><link rel="apple-touch-icon" href="/apple-touch-icon.png">
  <title>魚種別釣果一覧 | 船釣り予想</title>
  <meta name="description" content="関東の船釣り魚種別釣果一覧。アジ・マダイ・ヒラメ・タチウオなど今週釣れている魚種をまとめて確認できます。">
  <link rel="canonical" href="{SITE_URL}/fish/">
  {_build_share_meta(
      title="魚種別釣果一覧 | 船釣り予想",
      desc="関東の船釣り魚種別釣果一覧。アジ・マダイ・ヒラメ・タチウオなど今週釣れている魚種をまとめて確認できます。",
      url=f"{SITE_URL}/fish/",
  )}
  {GA_TAG}{ADSENSE_TAG}
  <link rel="stylesheet" href="../style.css">
  <style>{fish_index_css}</style>
</head>
<body>
{_v2_header_nav('fish')}
<div style="background:var(--accent);color:#fff;padding:18px 14px 20px;margin-bottom:0">
  <div class="c"><h1 style="font-size:26px;font-weight:800;margin:0">魚種別 釣果一覧</h1>
  <div style="font-size:12px;opacity:.7;margin-top:4px">今週釣果あり {_week_active}種</div></div>
</div>
<div class="c">
  <p class="bread"><a href="../">トップ</a> &rsaquo; 魚種一覧</p>
  <h2 class="st">今週よく釣れている魚</h2>
  <div class="fi-grid">{fish_index_cards}</div>
  {idx_all_section}
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
def build_area_redirects():
    """エリア正規化（_AREA_CANONICAL）で統合された旧 area ページ（旧slug）を
    canonical slug へ meta refresh redirect する（2026/06/20）。
    SEO の重複・データ分散を解消。旧slugが存在し canonical と異なる場合のみ生成。"""
    out_dir = os.path.join(WEB_DIR, "area")
    os.makedirs(out_dir, exist_ok=True)
    rom = _AREA_ROMAJI
    n = 0
    for old_area, canon_area in _AREA_CANONICAL.items():
        old_slug = rom.get(old_area)
        canon_slug = rom.get(canon_area)
        if not old_slug or not canon_slug or old_slug == canon_slug:
            continue
        new_url = f"{SITE_URL}/area/{canon_slug}.html"
        html = f"""<!DOCTYPE html>
<html lang="ja"><head>
<meta charset="utf-8">
<meta http-equiv="refresh" content="0;url={new_url}">
<link rel="canonical" href="{new_url}">
<meta name="robots" content="noindex,follow">
<title>移動しました | 船釣り予想</title>
</head>
<body>このページは <a href="{new_url}">{canon_area}の釣果情報</a> に統合されました。</body></html>"""
        with open(os.path.join(out_dir, f"{old_slug}.html"), "w", encoding="utf-8") as f:
            f.write(html)
        n += 1
    if n:
        print(f"エリア統合リダイレクト: {n} 件 → area/*.html")
    return n


def build_area_pages(data, history, crawled_at="", weather_data=None, hist_rows=None, fish_area_summary=None, area_top_fishes=None):
    os.makedirs(os.path.join(WEB_DIR, "area"), exist_ok=True)
    now = datetime.now(JST).replace(tzinfo=None)
    # 朝10時前は表示用『今日』を前日にシフト（船宿ブログの翌朝投稿パターン対応）
    today_str = _display_today_str(now)
    # today_iso は海況予報（weather_data.forecast）の検索キーなので実日付のまま
    today_iso = now.strftime("%Y-%m-%d")
    area_desc_data = load_area_description()
    area_seo_alias = load_area_seo_alias()
    area_decadal = load_area_decadal()
    fixed_faq_data_area = _load_fixed_faq()
    # 過去CSV（引数で渡された共有キャッシュを使用、なければ個別ロード）
    _hist_rows_for_placeholder = hist_rows if hist_rows is not None else _load_historical_catches()
    _fish_area_summary_area = fish_area_summary or {}
    _area_top_fishes = area_top_fishes or {}
    # area_coords.json（Place JSON-LD の geo に使用）
    _area_coords_for_placeholder = _ship_load_area_coords()
    # 2026/05/13 T34拡張: valid_catches を直近7日窓に絞る。
    # fishing-v.jp の船宿ページは最新ページ(pageID=1)を返す仕様だが、
    # シーズンオフ魚種・休止中船宿では数ヶ月前の釣果が最新ページに残ったまま
    # 更新されない場合があり、当日クロール結果に混入する。
    # T34 (build_fish_pages) と同じ7日窓フィルタを area にも適用。
    # 注: T34本体は data_recent 別名だが、ここでは下流の処理が全て同じ変数名を
    # 使うため破壊的上書きで簡潔化。呼び出し側で同一リストの再参照なし。
    _cutoff_date_T34 = (now - timedelta(days=6)).strftime("%Y/%m/%d")  # today含めて7日
    data = [c for c in data if c.get("date", "") >= _cutoff_date_T34]
    # 2026/05/19: chowari 経由 / 遅延到着データの補完
    # valid_catches は fishing-v.jp 当日クロール分のみだが、CSV には chowari 経由データや
    # 過去7日内の遅延到着レコードも含まれる。これらを取り込まないと一部エリア・船宿が
    # area_summary に登場せず、thin path（古いフォーマット）に分岐したり、
    # 船宿一覧の魚バッジが空のままになる（例: 大田区呑川・房丸）。
    _recent7_csv = _load_recent_catches_for_index(now, days=7)
    _existing_keys = {(c.get("date"), c.get("ship"), c.get("area"), c.get("fish_raw") or tuple(c.get("fish") or [])) for c in data}
    for r in _recent7_csv:
        key = (r.get("date"), r.get("ship"), r.get("area"), r.get("fish_raw") or tuple(r.get("fish") or []))
        if key in _existing_keys:
            continue
        _existing_keys.add(key)
        data.append(r)
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
.area-hero h1{font-size:26px;font-weight:800;margin:0}
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
.area-desc p:last-child{margin-bottom:0}
.chip-wrap{display:flex;flex-wrap:wrap;gap:6px;margin:10px 0}
.chip-link{background:var(--card);border:1px solid var(--border);border-radius:16px;padding:5px 12px;font-size:12px;color:var(--accent);text-decoration:none;font-weight:600;display:inline-flex;align-items:center;gap:4px}
.chip-link:hover{background:var(--accent);color:#fff;text-decoration:none}
.chip-emoji{vertical-align:middle}"""

    for area, catches in area_summary.items():
        # area_romaji_map.json に slug が無いエリアはスキップ（日本語ファイル名生成防止）
        if area not in _AREA_ROMAJI:
            continue
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
            # T31: thin パスも normal と同じ build_area_faq_html / build_area_fixed_faq_html を呼ぶ
            # （hist_rows ベース固定文章化・共通 7 問は faq.html リンクへ）
            auto_faq_html_thin, auto_faq_pairs_thin = build_area_faq_html(area, area_desc_data, hist_rows=_hist_rows_for_placeholder)
            fixed_faq_html_thin, fixed_faq_pairs_thin = build_area_fixed_faq_html(area, fixed_faq_data_area)
            faq_html = auto_faq_html_thin + fixed_faq_html_thin

            teaser_html = "" if not SHOW_PAID_TEASER else (
                '<h2 class="st teaser-title">このエリアの予測・分析 <span class="tag coming">まもなく公開</span></h2>'
                '<div class="teaser"><div class="teaser-head"><span class="teaser-badge">開発中</span>'
                f'<span class="teaser-title-in">{area} 日別予測・全ポイント情報</span></div>'
                f'<div class="teaser-desc"><strong>{area}</strong>の明日〜1週間後の魚種別予測、全ポイント一覧、'
                '海況相関の詳細分析を提供します。<br>月額500円 / スポット100円（決済は準備中）。</div></div>'
            )

            import json as _json
            _thin_main_entity = []
            for _q, _a in (auto_faq_pairs_thin + fixed_faq_pairs_thin):
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

            # thin パスでも area_description.json の解説文を表示（full パスと同じ build 関数）
            area_desc_html_thin = build_area_description_html(area, area_desc_data)

            html_min = f"""<!DOCTYPE html>
<html lang="ja"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="icon" href="/favicon.ico" sizes="48x48"><link rel="apple-touch-icon" href="/apple-touch-icon.png">
<title>{title_min}</title>
<meta name="description" content="{desc_meta_min}">
<link rel="canonical" href="{SITE_URL}/area/{area_slug(area)}.html">
{_build_share_meta(
    title=title_min,
    desc=desc_meta_min,
    url=f"{SITE_URL}/area/{area_slug(area)}.html",
)}
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
    <h1>{area}の船釣り釣果</h1>
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
  <p class="bread"><a href="../">トップ</a> &rsaquo; <a href="../area/">エリア一覧</a> &rsaquo; {area}</p>
  {_build_share_buttons(
      share_text=f"{area}の船釣り釣果情報 | 船釣り予想",
      share_url=f"{SITE_URL}/area/{area_slug(area)}.html",
  )}
  <div class="notice">
    <strong>本日の{area}からの出船報告はまだ届いていません。</strong>
    出船情報は各船宿のWebサイト・電話で直接ご確認ください。
    本ページでは過去1年の実績データから主要魚種・代表ポイント・出船船宿の傾向をご確認いただけます。
  </div>
  {('<h2 class="st">このエリアについて</h2>' + area_desc_html_thin) if area_desc_html_thin else ''}
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
  <p class="faq-common-link">船釣り全般の Q&amp;A（服装・船酔い・予約・ライフジャケット等）は<a href="/pages/faq.html"><strong>よくある質問ページ</strong></a>にまとめています。</p>
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
                if not f or f in ("不明", "欠航", "NULL"):
                    continue
                d = fish_data.setdefault(f, {"cnt_mins": [], "cnt_maxs": [], "sz_mins": [], "sz_maxs": [], "ships": set(), "records": 0, "ship_recs": {}})
                d["records"] += 1
                d["ships"].add(c["ship"])
                d["ship_recs"][c["ship"]] = d["ship_recs"].get(c["ship"], 0) + 1
                # count_range が dict なら優先（in-memory形式）、無ければ cnt_min/max（CSV形式）
                cr = c.get("count_range")
                if isinstance(cr, dict):
                    if cr.get("min") is not None and _cnt_personal(cr):
                        d["cnt_mins"].append(cr["min"])
                    if cr.get("max") is not None and _cnt_personal(cr):
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
                f'<div class="fn"><img src="../assets/fish/{fish_img_slug(fish)}/{fish_img_slug(fish)}_emoji.webp" alt="{fish}" class="fn-emoji" width="18" height="18" loading="lazy" decoding="async" onerror="this.style.display=\'none\'">{fish}</div>'
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
            if wave is not None or wind_spd is not None:
                _w = wave or 0
                _wd = wind_spd or 0
                _, _label = _sea_label(_w, _wd, sea_type)
                cm_parts.append(_label)
            if cm_parts:
                sea_comment = f'<p style="font-size:13px;line-height:1.7;color:var(--sub);margin:0 0 12px">{"。".join(cm_parts)}。</p>'

        # T38-A5: area-all-fish セクション（Layer 1 固定・全履歴魚種・折り畳み付き）
        # T29 past_fish_section_html を廃止し、全履歴魚種を常時表示
        _week_fish_set = {f for f, _ in top_fish_items}  # 直近7日に実績あり
        _all_area_fishes = _area_top_fishes.get(area, [])  # [(fish, cnt), ...]
        _aaf_active_chips = []
        _aaf_fold_chips = []
        for _f_hist, _n_hist in _all_area_fishes:
            _fa_file = os.path.join(WEB_DIR, f"fish_area/{fish_slug(_f_hist)}-{area_slug(area)}.html")
            if not os.path.exists(_fa_file):
                continue
            _chip = (
                f'<a href="../fish_area/{fish_slug(_f_hist)}-{area_slug(area)}.html" class="chip-link">'
                f'<img src="../assets/fish/{fish_img_slug(_f_hist)}/{fish_img_slug(_f_hist)}_emoji.webp" alt="{_f_hist}" class="chip-emoji" width="16" height="16" loading="lazy" decoding="async" onerror="this.style.display=\'none\'">'
                f'{_f_hist}（{_n_hist}便）</a>'
            )
            if _f_hist in _week_fish_set:
                _aaf_active_chips.append(_chip)
            else:
                _aaf_fold_chips.append(_chip)
        if _aaf_active_chips or _aaf_fold_chips:
            _aaf_parts = []
            if _aaf_active_chips:
                _aaf_parts.append(f'<p class="tier-label">★ 今週実績あり（{len(_aaf_active_chips)}魚種）</p>')
                _aaf_parts.append(f'<div class="chip-wrap">{"".join(_aaf_active_chips)}</div>')
            if _aaf_fold_chips:
                _aaf_parts.append(
                    f'<details class="fold-chips"><summary>過去実績あり（今週ゼロ・{len(_aaf_fold_chips)}魚種）を表示</summary>'
                    f'<div class="chip-wrap">{"".join(_aaf_fold_chips)}</div></details>'
                )
            past_fish_section_html = (
                '<section class="area-all-fish">'
                f'<h2 class="st">{area}エリアで釣れる魚種</h2>'
                + "".join(_aaf_parts)
                + '</section>'
            )
        else:
            past_fish_section_html = ""

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
                if f not in ("不明", "欠航", "NULL"):
                    ship_week_fish.setdefault(c["ship"], {}).setdefault(f, 0)
                    ship_week_fish[c["ship"]][f] += 1
        # T31 (2026/05/12): ships.json で area マッチする active 船宿も補完
        # （過去7日 catches に居なくても hist_rows に存在する船宿を一覧から漏らさない）
        # 2026/05/17: source_priority に "chowari" 等の代替ソースがあれば fishing_v_zero でも対象
        for s in SHIPS:
            if s.get("exclude") or s.get("boat_only"):
                continue
            if s.get("fishing_v_zero"):
                # 代替ソース（chowari 等）がある船宿は対象に含める
                _sp = s.get("source_priority") or []
                if not any(src != "fishing_v" for src in _sp):
                    continue
            if s.get("area") == area and s.get("name") and s["name"] not in ship_week_fish:
                ship_week_fish[s["name"]] = {}  # 過去7日釣果なし扱い
        sorted_ships = sorted(ship_week_fish.keys(), key=lambda s: (0 if s in ship_today_set else 1, -sum(ship_week_fish[s].values())))[:8]
        ship_items_html = ""
        for sn in sorted_ships:
            fish_dict = ship_week_fish[sn]
            top_f = sorted(fish_dict.items(), key=lambda x: -x[1])[:3]
            badges = "".join(
                f'<span class="{"g" if i == 0 else "o"}">'
                f'<img src="../assets/fish/{fish_img_slug(f)}/{fish_img_slug(f)}_emoji.webp" alt="{f}" class="sl-emoji" width="14" height="14" loading="lazy" decoding="async" onerror="this.style.display=\'none\'">{f}</span>'
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
        auto_area_faq_html, auto_area_faq_pairs = build_area_faq_html(area, area_desc_data, hist_rows=_hist_rows_for_placeholder)
        fixed_area_faq_html, fixed_area_faq_pairs = build_area_fixed_faq_html(area, fixed_faq_data_area)
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
        # Bug5修正: ヒーローは直近7日集計を表示。特定日の件数を出すと
        # 「その日だけ更新されていない」と誤解されるため。
        _week_cnt = len(catches)
        _week_ships = len({c["ship"] for c in catches})
        # 最新釣果日ラベル（area_date = _resolve_display_dataset が返す最新日付）
        _latest_label = fish_label  # 既に "M/D(曜)" or "—" 形式
        # P4 (2026/05/31): title/description を CTR 訴求型に強化（GSC SEO改善 4/4）
        # GSC 港名クエリ（天津港 imp45 pos9.6 CTR0%）。旧 title「{area}の釣果情報・
        # おすすめ船宿【直近7日N件】」は N=0 で薄ページ露呈。港の検索意図=何が釣れるか
        # → 主要魚種を title に出し CTR 訴求。_top_fish_str（直近7日 top3・既存変数）使用。
        # title本体と「| 船釣り予想」分離（OGP共用・P2/P3 同型）。数値は実測=事実。
        # 2026/06/20 SEO(CTR): スニペット先頭を「過去3年累計実績」にし、薄い「直近7日2件」表示で
        # クリックを取り逃すのを防ぐ（GSC: 港名クエリ pos8-10 CTR≈0% 対策）。
        # 「便」= ユニーク (ship, date) の出船。エリアは1便で複数魚種=複数行になるため、
        # 行数ではなくユニーク便を数える（2026/06/20 修正: 行数を便と誤表示し約2倍水増ししていた）。
        _area_trip_set = {
            (_r.get("ship"), _r.get("date"), _r.get("trip_no")) for _r in (_hist_rows_for_placeholder or [])
            if _r.get("area") == area and not _is_cancelled_row(_r)
            and (_r.get("tsuri_mono") or "").strip() not in _AREA_SKIP_FISH
            and _r.get("ship") and _r.get("date")
        }
        _area_hist_n = len(_area_trip_set)
        _area_hist_lead = f"過去3年{_area_hist_n:,}便の出船実績。" if _area_hist_n >= 30 else ""
        # 呼称ゆれ（飯岡港⇔飯岡漁港 等）。検索需要があるのに表記不一致で取りこぼす分を補う
        _area_aliases = [a for a in area_seo_alias.get(area, []) if a and a != area]
        _alias_meta = f"「{'」「'.join(_area_aliases)}」とも呼ばれます。" if _area_aliases else ""
        _alias_intro_html = (
            f'<p class="area-alias-lead">{area}（{"・".join(_area_aliases)}）周辺で出船する船宿の最新釣果と出船状況をまとめています。</p>'
            if _area_aliases else ""
        )
        # SERP で「{別称} 釣果」検索時にタイトル内別称が太字一致しCTRが上がる（最重要別称1件のみ）
        _area_title_name = f"{area}（{_area_aliases[0]}）" if _area_aliases else area
        if _top_fish_str:
            area_title_body = f"{_area_title_name}の釣果【{_top_fish_str}／{_week_ships}船宿】"
            area_desc = f"{area}（{group}）の船釣り釣果。{_alias_meta}{_area_hist_lead}直近7日{_week_cnt}件・{_week_ships}船宿が出船し{_area_desc_fish}釣れています。旬の魚種・船宿・最寄りアクセスを毎日更新。"
        else:
            area_title_body = f"{_area_title_name}の船釣り釣果情報"
            area_desc = f"{area}（{group}）の船釣り釣果情報。{_alias_meta}{_area_hist_lead}旬カレンダー・船宿情報・最寄りアクセス・海況データを掲載。"
        area_title_str = f"{area_title_body} | 船釣り予想"

        # 有料ティザー
        area_teaser_html = "" if not SHOW_PAID_TEASER else (
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
<link rel="icon" href="/favicon.ico" sizes="48x48"><link rel="apple-touch-icon" href="/apple-touch-icon.png">
  <title>{area_title_str}</title>
  <meta name="description" content="{area_desc}">
  <link rel="canonical" href="{area_url}">
  {_build_share_meta(
      title=area_title_body,
      desc=area_desc,
      url=area_url,
  )}
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
    <h1>{area}の船釣り釣果</h1>
    <div class="ah-sub">{group}</div>
    <div class="ah-m">直近7日: {_week_cnt}件・{_week_ships}船宿 <small>(最新: {_latest_label})</small></div>
    {ah_sea_html}
  </div>
</div>
<div class="c">
  <p class="bread"><a href="../">トップ</a> &rsaquo; <a href="../area/">エリア一覧</a> &rsaquo; {area}</p>
  {_build_share_buttons(
      share_text=f"{area}の船釣り釣果情報 | 船釣り予想",
      share_url=area_url,
  )}
  {_alias_intro_html}
  <h2 class="st">このエリアで今週釣れている魚 <span class="tag free">無料</span></h2>
  {fia_desc_html}<div class="fia-grid">{fia_cards if fia_cards else '<p style="color:var(--muted);font-size:13px">今週の釣果はまだ集計中です</p>'}</div>
  {past_fish_section_html}
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
  <p class="faq-common-link">船釣り全般の Q&amp;A（服装・船酔い・予約・ライフジャケット等）は<a href="/pages/faq.html"><strong>よくある質問ページ</strong></a>にまとめています。</p>
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

    # area/index.html の生成は build_area_index_html() に分離（Phase C）
    # build_fish_area_pages 完了後に main() から呼ばれる


def build_area_index_html(now, hist_rows, fish_area_summary, area_top_fishes, recent7, crawled_at=""):
    """area/index.html を生成する（Phase C: build_area_pages から分離）。

    呼出タイミング: build_fish_area_pages 完了後に main() から呼ばれる。
    これにより _fa_exists() が全 fish_area HTML を正確に参照できる。

    Args:
        now              : datetime（JST）
        hist_rows        : _load_historical_catches() の結果（共有キャッシュ）
        fish_area_summary: {(fish, area): cnt} 過去3年集計
        area_top_fishes  : compute_area_top_fishes(hist_rows) の結果
        recent7          : _load_recent_catches_for_index(now, days=7) の結果（共有）
        crawled_at       : 更新日時文字列
    """
    os.makedirs(os.path.join(WEB_DIR, "area"), exist_ok=True)
    _SKIP_FISH = {"不明", "欠航", "NULL"}
    _group_order = ["茨城", "千葉・外房", "千葉・内房", "千葉・東京湾奥", "東京", "神奈川・東京湾", "神奈川・相模湾", "静岡"]

    # ── 今週エリア別集計（recent7 から） ──
    area_week_cnt: dict[str, int] = {}   # area -> 今週便数
    area_week_fish: dict[str, dict] = {}  # area -> {fish: cnt}（今週）
    for c in recent7:
        area = c.get("area", "")
        if not area:
            continue
        area_week_cnt[area] = area_week_cnt.get(area, 0) + 1
        for f in c.get("fish", []):
            if f in _SKIP_FISH or f.isdigit():
                continue
            area_week_fish.setdefault(area, {})
            area_week_fish[area][f] = area_week_fish[area].get(f, 0) + 1

    # ── 既存 AREA_GROUPS 別カードゾーン（ai-card を直リンク化） ──
    area_index_sections = ""
    for grp in _group_order:
        grp_areas = [(a, area_week_cnt.get(a, 0))
                     for a in AREA_GROUPS.get(grp, [])
                     if area_week_cnt.get(a, 0) >= 2]
        if not grp_areas:
            continue
        cards = ""
        for area_nm, week_cnt in sorted(grp_areas, key=lambda x: -x[1]):
            slug_a = area_slug(area_nm)
            pref_img = _chip_pref_img(area_nm, depth=1)
            # ai-name の img は width:18px
            pref = AREA_TO_PREFECTURE.get(area_nm)
            if pref:
                pref_img_name = (
                    f'<img src="../assets/area/{pref}_emoji.webp" alt="{PREF_LABEL.get(pref, "")}" class="chip-pref"'
                    f' style="width:18px;height:18px;object-fit:contain;vertical-align:middle;margin-right:4px"'
                    f' onerror="this.style.display=\'none\'">'
                )
            else:
                pref_img_name = ""

            # 今週実績魚種（最大3件・便数降順）→ fish_area 直リンク化
            fish_sorted = sorted(
                area_week_fish.get(area_nm, {}).items(),
                key=lambda x: -x[1]
            )[:3]
            fish_links = []
            for i, (f, _) in enumerate(fish_sorted):
                if _fa_exists(f, area_nm):
                    fish_links.append(
                        f'<a href="../fish_area/{fish_slug(f)}-{slug_a}.html">{f}</a>'
                    )
                else:
                    fish_links.append(f)
            ai_fish_html = '<span class="ai-sep">・</span>'.join(fish_links) if fish_links else "—"

            cards += (
                f'<div class="ai-card">'
                f'<a class="ai-name" href="{slug_a}.html">{pref_img_name}{area_nm}</a>'
                f'<div class="ai-fish">{ai_fish_html}</div>'
                f'<a class="ai-cnt" href="{slug_a}.html">今週釣果{week_cnt}便</a>'
                f'</div>'
            )
        area_index_sections += f'<h2 class="st">{grp}</h2><div class="ai-grid">{cards}</div>'

    # 未分類エリア（その他）
    _matched_areas = {a for areas in AREA_GROUPS.values() for a in areas}
    _other_areas = [(a, area_week_cnt.get(a, 0))
                    for a in area_week_cnt
                    if a not in _matched_areas and area_week_cnt.get(a, 0) >= 2]
    if _other_areas:
        cards = ""
        for area_nm, week_cnt in sorted(_other_areas, key=lambda x: -x[1]):
            slug_a = area_slug(area_nm)
            pref = AREA_TO_PREFECTURE.get(area_nm)
            if pref:
                pref_img_name = (
                    f'<img src="../assets/area/{pref}_emoji.webp" alt="{PREF_LABEL.get(pref, "")}" class="chip-pref"'
                    f' style="width:18px;height:18px;object-fit:contain;vertical-align:middle;margin-right:4px"'
                    f' onerror="this.style.display=\'none\'">'
                )
            else:
                pref_img_name = ""
            fish_sorted = sorted(
                area_week_fish.get(area_nm, {}).items(),
                key=lambda x: -x[1]
            )[:3]
            fish_links = []
            for i, (f, _) in enumerate(fish_sorted):
                if _fa_exists(f, area_nm):
                    fish_links.append(
                        f'<a href="../fish_area/{fish_slug(f)}-{slug_a}.html">{f}</a>'
                    )
                else:
                    fish_links.append(f)
            ai_fish_html = '<span class="ai-sep">・</span>'.join(fish_links) if fish_links else "—"
            cards += (
                f'<div class="ai-card">'
                f'<a class="ai-name" href="{slug_a}.html">{pref_img_name}{area_nm}</a>'
                f'<div class="ai-fish">{ai_fish_html}</div>'
                f'<a class="ai-cnt" href="{slug_a}.html">今週釣果{week_cnt}便</a>'
                f'</div>'
            )
        area_index_sections += f'<h2 class="st">その他</h2><div class="ai-grid">{cards}</div>'

    _week_active_area = sum(1 for cnt in area_week_cnt.values() if cnt >= 2)

    # ── 「エリア」セクション（Phase C 新規） ──
    # (fish, area) 別便数を参照
    fa_hist_cnt: dict[tuple, int] = {}
    for (f, a), cnt in fish_area_summary.items():
        fa_hist_cnt[(f, a)] = cnt

    # エリアごとの今週魚種集合（recent7 から）
    area_week_fish_set: dict[str, set] = {}
    for c in recent7:
        area_nm = c.get("area", "")
        for f in c.get("fish", []):
            if f in _SKIP_FISH or f.isdigit():
                continue
            area_week_fish_set.setdefault(area_nm, set()).add(f)

    # 全エリアリスト: hist_rows と today エリアの和集合から _AREA_ROMAJI 登録済みのもの
    all_areas = set(a for (_, a) in fa_hist_cnt) | set(area_week_cnt.keys())
    all_areas = {a for a in all_areas if a in _AREA_ROMAJI}

    def _has_any_fa_area(area_nm):
        return any(
            _fa_exists(f, area_nm)
            for (f, _a) in fa_hist_cnt
            if _a == area_nm
        )

    target_areas = [a for a in all_areas if _has_any_fa_area(a)]

    # 並び順: _group_order 順 → グループ内今週便数降順 → 未分類
    def _area_group_idx(a):
        for i, grp in enumerate(_group_order):
            if a in AREA_GROUPS.get(grp, []):
                return i
        return len(_group_order)  # 未分類は末尾

    target_areas.sort(key=lambda a: (_area_group_idx(a), -area_week_cnt.get(a, 0), a))

    idx_blocks_html = ""
    for area_nm in target_areas:
        slug_a = area_slug(area_nm)
        pref_img = _chip_pref_img(area_nm, depth=1)
        pref = AREA_TO_PREFECTURE.get(area_nm)
        if pref:
            pref_img_ib = (
                f'<img src="../assets/area/{pref}_emoji.webp" alt="{PREF_LABEL.get(pref, "")}" class="ib-emoji"'
                f' width="20" height="20" loading="lazy" onerror="this.style.display=\'none\'">'
            )
        else:
            pref_img_ib = ""

        # このエリアの魚種一覧（hist_rows 由来・便数降順）
        area_fishes_with_cnt = sorted(
            [(f, fa_hist_cnt[(f, area_nm)])
             for (f, a) in fa_hist_cnt
             if a == area_nm and _fa_exists(f, area_nm)],
            key=lambda x: -x[1]
        )
        if not area_fishes_with_cnt:
            continue  # 空ブロック禁止

        week_fish_set = area_week_fish_set.get(area_nm, set())
        active_fishes = [(f, cnt) for f, cnt in area_fishes_with_cnt if f in week_fish_set]
        inactive_fishes = [(f, cnt) for f, cnt in area_fishes_with_cnt if f not in week_fish_set]

        week_cnt = area_week_cnt.get(area_nm, 0)
        total_fish = len(area_fishes_with_cnt)

        # idx-block-h
        block_h = (
            f'<div class="idx-block-h">'
            f'{pref_img_ib}'
            f'<a href="{slug_a}.html">{area_nm}</a>'
            f'<span class="ib-cnt">今週{week_cnt}便・全{total_fish}魚種</span>'
            f'</div>'
        )

        # 上段（今週実績あり）
        if active_fishes:
            active_chips = "".join(
                f'<a href="../fish_area/{fish_slug(f)}-{slug_a}.html" class="chip-link chip-active">'
                f'<img src="../assets/fish/{fish_img_slug(f)}/{fish_img_slug(f)}_emoji.webp" alt="{f}" class="chip-emoji"'
                f' width="14" height="14" loading="lazy" onerror="this.style.display=\'none\'">'
                f'{f}（{cnt}便）'
                f'</a>'
                for f, cnt in active_fishes
            )
            active_section = (
                f'<p class="tier-label">★ 今週実績あり（{len(active_fishes)}魚種）</p>'
                f'<div class="chip-wrap">{active_chips}</div>'
            )
        else:
            active_section = '<p class="tier-label" style="color:#aaa;">今週実績なし</p>'

        # 下段（過去実績のみ）
        if inactive_fishes:
            inactive_chips = "".join(
                f'<a href="../fish_area/{fish_slug(f)}-{slug_a}.html" class="chip-link">'
                f'<img src="../assets/fish/{fish_img_slug(f)}/{fish_img_slug(f)}_emoji.webp" alt="{f}" class="chip-emoji"'
                f' width="14" height="14" loading="lazy" onerror="this.style.display=\'none\'">'
                f'{f}（{cnt}便）'
                f'</a>'
                for f, cnt in inactive_fishes
            )
            open_attr = " open" if not active_fishes else ""
            inactive_section = (
                f'<details class="fold-chips"{open_attr}>'
                f'<summary>過去実績あり（今週ゼロ・{len(inactive_fishes)}魚種）を表示</summary>'
                f'<div class="chip-wrap">{inactive_chips}</div>'
                f'</details>'
            )
        else:
            inactive_section = ""

        idx_blocks_html += (
            f'<div class="idx-block">'
            f'{block_h}'
            f'{active_section}'
            f'{inactive_section}'
            f'</div>'
        )

    idx_all_section = ""
    if idx_blocks_html:
        idx_all_section = f"""<h2 class="st">エリア</h2>
<p class="faa-note">
  各エリアについて、過去に釣果報告のある<b>全魚種への直リンク</b>を網羅。
  便数は過去3年の実績報告数。<b>★今週実績あり</b>を上段に、
  <b>過去実績のみ</b>を下段（折り畳み）に分離。
</p>
<div class="idx-all-grid">{idx_blocks_html}</div>"""

    # ── CSS ──
    area_index_css = """.ai-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:8px;margin:12px 0 20px}
.ai-card{background:var(--card);border:1px solid var(--border);border-radius:var(--r);padding:12px;display:block;transition:border-color .15s}
.ai-card:hover{border-color:var(--cta)}
.ai-name{display:block;font-size:14px;font-weight:700;color:var(--accent);text-decoration:none}
.ai-name:hover{text-decoration:underline}
.ai-fish{font-size:11px;color:var(--sub);margin-top:4px;line-height:1.9}
.ai-fish a{color:#1a4a72;text-decoration:none;white-space:nowrap;padding:3px 6px;border-radius:3px;display:inline-block}
.ai-fish a:hover{background:#eaf2fa;text-decoration:underline}
.ai-sep{color:#aaa}
.ai-cnt{display:block;font-size:11px;color:var(--cta);font-weight:600;margin-top:4px;text-decoration:none}
.ai-cnt:hover{text-decoration:underline}
.idx-all-grid{background:var(--card);border:1px solid var(--border);border-radius:var(--r);padding:12px 14px;margin:8px 0 20px}
.idx-block{padding:8px 0;border-bottom:1px solid var(--border)}
.idx-block:last-child{border-bottom:none}
.idx-block-h{font-size:14px;font-weight:700;color:var(--accent);display:flex;align-items:center;gap:6px;padding:6px 0 4px}
.idx-block-h .ib-emoji{width:20px;height:20px;object-fit:contain}
.idx-block-h .ib-cnt{font-size:11px;color:var(--muted);font-weight:400;margin-left:auto}
.idx-block-h a{color:var(--accent);text-decoration:none}
.idx-block-h a:hover{text-decoration:underline}
.chip-link.chip-active{background:#fff8e7;border-color:#f5c542}
.chip-link.chip-active:hover{background:#fff3d0}
.faa-note{font-size:13px;color:var(--sub);margin:0 0 8px}
@media(max-width:480px){.idx-block-h .ib-cnt{display:none}}"""

    # ── HTML 組立 ──
    area_index_html = f"""<!DOCTYPE html>
<html lang="ja"><head>
  <meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="icon" href="/favicon.ico" sizes="48x48"><link rel="apple-touch-icon" href="/apple-touch-icon.png">
  <title>エリア別釣果一覧 | 船釣り予想</title>
  <meta name="description" content="関東の船釣りエリア別釣果一覧。茨城・千葉・東京・神奈川エリアの今週の釣果件数と釣れている魚種を確認できます。">
  <link rel="canonical" href="{SITE_URL}/area/">
  {_build_share_meta(
      title="エリア別釣果一覧 | 船釣り予想",
      desc="関東の船釣りエリア別釣果一覧。茨城・千葉・東京・神奈川エリアの今週の釣果件数と釣れている魚種を確認できます。",
      url=f"{SITE_URL}/area/",
  )}
  {GA_TAG}{ADSENSE_TAG}
  <link rel="stylesheet" href="../style.css">
  <style>{area_index_css}</style>
</head>
<body>
{_v2_header_nav('area')}
<div style="background:var(--accent);color:#fff;padding:18px 14px 20px;margin-bottom:0">
  <div class="c"><h1 style="font-size:26px;font-weight:800;margin:0">エリア別 釣果一覧</h1>
  <div style="font-size:12px;opacity:.7;margin-top:4px">今週釣果あり {_week_active_area}エリア</div></div>
</div>
<div class="c">
  <p class="bread"><a href="../">トップ</a> &rsaquo; エリア一覧</p>
  {area_index_sections}
  {idx_all_section}
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
        if _cnt_personal(c.get("count_range"))
        and c["count_range"].get("max") is not None
    ]
    max_boat = max(
        (c["count_range"]["max"] for c in fa_catches
         if c.get("count_range") and c["count_range"].get("is_boat")
         and not _cnt_personal(c.get("count_range"))
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


def _build_fa_intro_html(fish, area, fa_catches, decadal_calendar, area_description=None, hist_stats=None):
    """fish_area 説明文（200字以上・自サイトデータのみ）
    H3 (T22): area_description を渡すとエリア固有の1文を冒頭に差し込む。
    2026/06/16: hist_stats（_fa_hist_stats の過去3年コンボ統計）を渡すと便数・
    最高釣果・船宿を3年ベースで記述し、FAQ・stat card と数値を一致させる。
    旧実装は今週の fa_catches ベースで「1便・最高45匹」と書き、3年ベースの FAQ
    「383便・最高273匹」と同一ページ内で矛盾していた（AdSense 薄判定リスク）。
    hist_stats=None のときは従来どおり fa_catches ベース（後方互換）。
    """
    fish_decades = decadal_calendar.get(fish, {}) if decadal_calendar else {}
    peak_label = ""
    if fish_decades:
        top_dn = max(fish_decades.items(), key=lambda x: x[1].get("cnt_index", 0))
        peak_label = _decade_label(top_dn[0])

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

    if hist_stats and hist_stats.get("n_trips"):
        # 3年ベース（FAQ と同一ソース）
        N = hist_stats["n_trips"]
        years_str = hist_stats.get("years_str", "")
        max_val = hist_stats.get("cnt_max")
        med = hist_stats.get("cnt_med")
        p25 = hist_stats.get("cnt_p25")
        p75 = hist_stats.get("cnt_p75")
        top_ships = hist_stats.get("top_ships") or []
        total_ships = hist_stats.get("n_ships", 0)
        intro_lead = f"{area}での{fish}は過去3年で{N:,}便の出船記録があります{years_str}。"
    else:
        # 後方互換: 当日 fa_catches ベース
        N = len(fa_catches)
        n_personal, avg_med, max_val, p25, p75, max_boat = _fa_catches_stats(fa_catches)
        med = avg_med if n_personal >= 5 else None
        ship_counts: dict = {}
        for c in fa_catches:
            sn = c.get("ship", "")
            if sn:
                ship_counts[sn] = ship_counts.get(sn, 0) + 1
        top_ships = sorted(ship_counts.items(), key=lambda x: -x[1])[:3]
        total_ships = len(ship_counts)
        dates = sorted([c.get("date", "") for c in fa_catches if c.get("date")])
        years_str = ""
        if len(dates) >= 2:
            y0, y1 = dates[0][:4], dates[-1][:4]
            years_str = f"（{y0}年〜{y1}年）" if y0 != y1 else f"（{y0}年）"
        intro_lead = f"{area}での{fish}の釣果データは{N}便記録されています{years_str}。"

    lines = []
    if area_intro:
        lines.append(area_intro)
    lines.append(intro_lead)
    if peak_label:
        lines.append(f"月別の集計では{peak_label}前後に釣果が集中する傾向があります。")
    if max_val and med:
        lines.append(f"1回の釣行あたりの中央値は{med:.0f}匹で、最高釣果は{max_val}匹の記録があります。")
        if p25 is not None and p75 is not None and p25 < p75:
            lines.append(f"標準的な釣果レンジは{p25}〜{p75}匹です。")
        lines.append("釣果は潮回りや水温の影響を受けやすく、旬の時期を選ぶと安定した釣果が期待できます。")
    elif max_val:
        lines.append(f"最高釣果は{max_val}匹の記録があります。")
        lines.append("釣果は潮回りや季節によって変動するため、シーズンバーと直近の釣果カードを参考にしてください。")
    else:
        lines.append("個人釣果の統計は引き続きデータ収集中です。")
        lines.append("釣果は潮回りや季節によって変動するため、旬の時期を選ぶと安定した釣果が期待できます。")
    if top_ships:
        ship_strs = "、".join(f"{sn}（{cnt}便）" for sn, cnt in top_ships)
        lines.append(f"出船実績の多い船宿は{ship_strs}です。")
    if total_ships > 0:
        lines.append(f"このエリアでは計{total_ships}船宿が{fish}の出船実績を持ちます。各船宿の出船スケジュールは直接ご確認ください。")
    text = "".join(lines)
    if len(text) < 200:
        text += "このページのシーズンバーと釣果カードで最新の傾向を確認の上、釣行計画にお役立てください。"
    return f'<p class="fa-intro">{text}</p>'


def _build_fish_area_season_q1_text(fish, area, hist_rows):
    """fish_area FAQ Q1（T30 2026/05/12）: 月別件数・三大ピーク・同魚種他エリア順位の固定文章。

    hist_rows（3年分 CSV）から (tsuri_mono=fish, area=area) を抽出し、月別件数の三大ピーク、
    同魚種における全エリア順位（1位=最大集積地・etc）を併記する。
    """
    if not hist_rows:
        return f"{area}での{fish}の釣果データは集計中です。本ページの旬カレンダーで月別推移をご確認ください。"
    fa_rows = []
    fish_area_counts = {}
    for r in hist_rows:
        if r.get("tsuri_mono") != fish:
            continue
        a = (r.get("area") or "").strip()
        if not a:
            continue
        fish_area_counts[a] = fish_area_counts.get(a, 0) + 1
        if a == area:
            fa_rows.append(r)
    # 便 = ユニーク (ship, date, trip_no)（行数だと重複行/main・sub で水増し）
    N = len({(r.get("ship"), r.get("date"), r.get("trip_no")) for r in fa_rows})
    if N == 0:
        return f"{area}での{fish}の釣果データは現在集計中です。本ページの最新釣果カードをご確認ください。"
    months = [0] * 12
    for r in fa_rows:
        d = r.get("date", "")
        if len(d) >= 7:
            try:
                m = int(d[5:7])
                if 1 <= m <= 12:
                    months[m - 1] += 1
            except (ValueError, TypeError):
                pass
    total_records = sum(fish_area_counts.values())
    total_areas = len(fish_area_counts)
    ranks = sorted(fish_area_counts.items(), key=lambda x: -x[1])
    area_rank = next((i for i, (a, _) in enumerate(ranks, 1) if a == area), None)
    if area_rank == 1 and total_records > 0:
        pct = round(N / total_records * 100)
        rank_str = f"関東の{fish}釣果{total_records:,}件のうち約{pct}%を占める関東最大の集積地（{total_areas}エリア中1位）"
    elif area_rank is not None:
        rank_str = f"関東の{fish}釣果{total_records:,}件のうち{area_rank}番目の集積地（{total_areas}エリア中）"
    else:
        rank_str = f"関東の{fish}釣果集積地の一つ"
    months_indexed = [(i + 1, c) for i, c in enumerate(months) if c > 0]
    if not months_indexed:
        return (
            f"2023年以降の{area}での{fish}釣果データは{N:,}便で、{rank_str}です。"
            f"月別データは取得中で、最新の釣果報告をご確認ください。"
        )
    sorted_months = sorted(months_indexed, key=lambda x: -x[1])
    top3 = sorted_months[: min(3, len(sorted_months))]
    # 表示は月を時系列順に（件数順のまま並べると「5月・10月・4月」のように不自然になる）
    top3_str = "、".join(f"{m}月（{c}件）" for m, c in sorted(top3, key=lambda x: x[0]))
    n_months_with_data = len(months_indexed)
    extra = ""
    if len(sorted_months) >= 4:
        min_m, min_c = sorted_months[-1]
        if min_c < top3[0][1] * 0.6:
            extra = f"最も少ない{min_m}月でも{min_c}件と"
    if n_months_with_data == 12:
        months_text = "通年で実績が記録されています"
    elif n_months_with_data >= 8:
        months_text = "ほぼ通年で実績があります"
    elif n_months_with_data >= 4:
        months_text = f"年間{n_months_with_data}ヶ月で実績があります"
    else:
        months_text = f"年間{n_months_with_data}ヶ月のみに実績が記録されています"
    peak_label = "三大ピーク" if len(top3) >= 3 else ("二大ピーク" if len(top3) == 2 else "ピーク月")
    return (
        f"2023年以降の{area}での{fish}釣果データは{N:,}便で、{rank_str}です。"
        f"月別では{top3_str}が{peak_label}。{extra}{months_text}。"
        f"釣果は潮回り・水温・群れの回遊で日々変動するため、最新の釣果報告も併せてご確認ください。"
    )


def _build_fish_area_count_q2_text(fish, area, hist_rows):
    """fish_area FAQ Q2（T30）: 釣果レンジ + cm/kg 統計（妥当範囲フィルタ付き）の固定文章。

    cnt_max は cnt_max>0 かつ is_boat≠1 でフィルタ。サイズは _FISH_SIZE_RANGE_MAP の
    cm_max・kg_max を超える値を異常値として除外し、主単位（cm or kg）に応じて表示。
    """
    if not hist_rows:
        return f"{area}での{fish}の釣果データは集計中です。直近の釣果カードをご確認ください。"
    sz_range = _FISH_SIZE_RANGE_MAP.get(fish, _FISH_SIZE_DEFAULT)
    cm_limit = sz_range["cm_max"]
    kg_limit = sz_range["kg_max"]
    primary = sz_range.get("primary", "cm")
    cnts, cms, kgs = [], [], []
    for r in hist_rows:
        if r.get("tsuri_mono") != fish or r.get("area") != area:
            continue
        if _cnt_personal_csv(r):
            try:
                v = int(float(r.get("cnt_max", "") or 0))
                if v > 0 and _is_plausible_cnt(fish, v):
                    cnts.append(v)
            except (ValueError, TypeError):
                pass
        try:
            v = int(float(r.get("size_max", "") or 0))
            if 0 < v <= cm_limit:
                cms.append(v)
        except (ValueError, TypeError):
            pass
        try:
            v = float(r.get("kg_max", "") or 0)
            if 0 < v <= kg_limit:
                kgs.append(v)
        except (ValueError, TypeError):
            pass
    if not cnts:
        return f"{area}での{fish}の釣果データは集計中です。直近の釣果カードをご確認ください。"
    cnts.sort()
    cn = len(cnts)
    cnt_p25 = cnts[int(cn * 0.25)] if cn >= 4 else cnts[0]
    cnt_p75 = cnts[int(cn * 0.75)] if cn >= 4 else cnts[-1]
    cnt_max = cnts[-1]
    # n>=10 は「標準的なレンジ」・n>=4 は「実績レンジ」・n<4 は「参考値」（少データで断定を避ける）
    if cn >= 10:
        if cnt_p25 == cnt_p75:
            cnt_text = f"一日{cnt_p25}匹前後が標準的で、最高実績は{cnt_max}匹です"
        else:
            cnt_text = f"一日{cnt_p25}〜{cnt_p75}匹が標準的なレンジで、最高実績は{cnt_max}匹です"
    elif cn >= 4:
        if cnt_p25 == cnt_p75:
            cnt_text = f"釣果実績は{cnt_p25}匹前後、最高実績は{cnt_max}匹です（サンプル{cn}件）"
        else:
            cnt_text = f"釣果レンジは{cnt_p25}〜{cnt_p75}匹、最高実績は{cnt_max}匹です（サンプル{cn}件）"
    else:
        cnt_text = f"最高実績は{cnt_max}匹です（サンプル{cn}件と少なく標準的なレンジの推定は困難）"
    head = f"過去3年間の{area}での{fish}実釣記録{cn:,}件（個人釣果のみ・船全体の合計数は除く）を集計すると、{cnt_text}。"
    cms.sort()
    kgs.sort()
    # kg 表示は整数なら "1.0" → "1" に詰める（自然な読み）
    def _fkg(v):
        s = f"{v:.1f}"
        return s[:-2] if s.endswith(".0") else s
    size_text = ""
    if primary == "kg" and len(kgs) >= 5:
        kg_med = kgs[len(kgs) // 2]
        size_text = (
            f"重量データは{len(kgs):,}件で、{_fkg(kgs[0])}〜{_fkg(kgs[-1])}kgのレンジで記録されており中位は約{_fkg(kg_med)}kg。"
        )
        if len(cms) < 5:
            size_text += "サイズ（cm）データは取得数が少ないため省略します。"
        else:
            cm_med = cms[len(cms) // 2]
            size_text += f"サイズデータ{len(cms):,}件では中央値{cm_med}cm・最大{cms[-1]}cmです。"
    elif primary == "cm" and len(cms) >= 5:
        cm_med = cms[len(cms) // 2]
        size_text = f"サイズは中央値{cm_med}cm・最大{cms[-1]}cmで記録されています。"
        if len(kgs) >= 5:
            kg_med = kgs[len(kgs) // 2]
            size_text += f"重量データ{len(kgs):,}件では中位約{_fkg(kg_med)}kgです。"
    elif len(kgs) >= 5:
        kg_med = kgs[len(kgs) // 2]
        size_text = (
            f"重量データは{len(kgs):,}件で、{_fkg(kgs[0])}〜{_fkg(kgs[-1])}kgのレンジで記録されており中位は約{_fkg(kg_med)}kg。"
        )
    elif len(cms) >= 5:
        cm_med = cms[len(cms) // 2]
        size_text = f"サイズは中央値{cm_med}cm・最大{cms[-1]}cmで記録されています。"
    tail = "釣果は潮回り・水温・群れの密度で大きく変動するため、本ページの最新の釣果カードも併せてご参考ください。"
    return head + size_text + tail


def _build_fish_area_ships_q3_text(fish, area, hist_rows, area_description=None):
    """fish_area FAQ Q3（T30）: 船宿リスト + 釣法 + 難易度 + 地理特性の固定文章。

    船宿は hist_rows 件数の TOP5。釣法は _FISH_METHOD_MAP・難易度は _FISH_BEGINNER_MAP
    から取得。地理特性は area_description.json の冒頭1文（80字以下）を採用。
    """
    if not hist_rows:
        return f"{area}での{fish}の船宿情報は集計中です。直近の釣果カードをご確認ください。"
    ship_counts = {}
    for r in hist_rows:
        if r.get("tsuri_mono") != fish or r.get("area") != area:
            continue
        sn = (r.get("ship") or "").strip()
        if sn:
            ship_counts[sn] = ship_counts.get(sn, 0) + 1
    if not ship_counts:
        return f"{area}での{fish}の船宿情報は集計中です。直近の釣果カードをご確認ください。"
    top5 = sorted(ship_counts.items(), key=lambda x: -x[1])[:5]
    ship_str = "、".join(f"{sn}（{cnt:,}便）" for sn, cnt in top5)
    n_ships = len(ship_counts)
    head = (
        f"過去3年間の{area}での{fish}釣果データがある船宿は計{n_ships}船宿です。"
        f"記録件数の多い順に{ship_str}が出船実績豊富です。"
    )
    method = _FISH_METHOD_MAP.get(fish, "")
    beginner_info = _FISH_BEGINNER_MAP.get(fish)
    method_text = ""
    if method:
        # _FISH_METHOD_MAP がある魚種は desc を使わない（釣法説明が重複・矛盾する恐れがあるため）
        method_text = f"{fish}釣りは{method}"
        if beginner_info:
            level, _desc = beginner_info
            method_text += f"で、難易度は{level}の釣り"
        method_text += "。"
    elif beginner_info:
        # _FISH_METHOD_MAP 未登録魚種のみ _FISH_BEGINNER_MAP の desc を使う
        level, desc = beginner_info
        method_text = f"{fish}釣りは難易度{level}の釣りです。{desc}。"
    geo_text = ""
    if area_description and isinstance(area_description, dict):
        entry = area_description.get(area) or area_description.get(area + "港") or {}
        if isinstance(entry, dict):
            desc_full = entry.get("description", "") or ""
            if desc_full:
                first_sentence = desc_full.split("。")[0]
                if first_sentence and len(first_sentence) <= 80:
                    geo_text = first_sentence + "。"
    tail = "各船宿で仕掛け・タックルの貸出有無や出船スケジュールが異なるため、予約時にお問い合わせください。"
    return head + method_text + geo_text + tail


def build_fish_area_faq_html(fish, area, hist_rows, decadal_calendar=None, area_description=None):
    """fish_area ページ用 FAQ 3問 + FAQPage JSON-LD を返す (html, jsonld) タプル。

    T30 (2026/05/12): catches（当日スナップショット）依存から hist_rows（3年分 CSV）依存に変更。
    - 各回答 200〜350字目安・3年間の実績データに基づく具体的なコメント
    - _FISH_SIZE_RANGE_MAP で cm/kg 妥当範囲外の異常値を除外
    - _FISH_METHOD_MAP で魚種別釣法を正確に記述（マダイ=コマセダイ・「ビシ釣り」誤用排除）
    - area_description.json から地理特性の1文を Q3 末尾に組込み
    - 同魚種他エリア順位を Q1 に組込み（相対比較で意味出し）
    """
    q1_ans = _build_fish_area_season_q1_text(fish, area, hist_rows)
    q2_ans = _build_fish_area_count_q2_text(fish, area, hist_rows)
    q3_ans = _build_fish_area_ships_q3_text(fish, area, hist_rows, area_description)
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


def _fa_hist_stats(fish, area, hist_rows):
    """fish_area の過去3年（CSV hist）コンボ統計。FAQ Q2 と同一フィルタで算出し、
    intro / stat card / title の数値を FAQ 固定文章と一致させて自己矛盾を防ぐ
    （2026/06/16: hero/intro=今週・FAQ=3年 で「1便/最高45匹 vs 383便/最高273匹」と
    同一ページ内で矛盾していた問題の修正。AdSense 薄判定対策）。
    返却 dict: n_trips, n_ships, top_ships[(name,cnt)], cnt_med, cnt_p25, cnt_p75,
              cnt_max, cm_med, cm_max, years_str。データ無しは 0/None/""。
    cnt 系は個人釣果(is_boat≠1)・_is_plausible_cnt フィルタ後（FAQ Q2 と一致）。"""
    sz_range = _FISH_SIZE_RANGE_MAP.get(fish, _FISH_SIZE_DEFAULT)
    cm_limit = sz_range["cm_max"]
    cnts, cms = [], []
    ship_trips: dict = {}
    trip_set: set = set()
    years: set = set()
    for r in hist_rows:
        if r.get("tsuri_mono") != fish or r.get("area") != area:
            continue
        if _is_cancelled_row(r):
            continue
        # 便 = ユニーク (ship, date, trip_no)。同便の重複行や main/sub 重複で水増ししない。
        trip_set.add((r.get("ship"), r.get("date"), r.get("trip_no")))
        sn = r.get("ship")
        if sn:
            ship_trips.setdefault(sn, set()).add((r.get("date"), r.get("trip_no")))
        d = r.get("date", "")
        if len(d) >= 4:
            years.add(d[:4])
        if _cnt_personal_csv(r):
            try:
                v = int(float(r.get("cnt_max", "") or 0))
                if v > 0 and _is_plausible_cnt(fish, v):
                    cnts.append(v)
            except (ValueError, TypeError):
                pass
        try:
            v = int(float(r.get("size_max", "") or 0))
            if 0 < v <= cm_limit:
                cms.append(v)
        except (ValueError, TypeError):
            pass
    cnts.sort()
    cms.sort()
    cn = len(cnts)
    n_trips = len(trip_set)
    top_ships = sorted(((s, len(v)) for s, v in ship_trips.items()), key=lambda x: -x[1])[:3]
    years_sorted = sorted(years)
    years_str = ""
    if years_sorted:
        y0, y1 = years_sorted[0], years_sorted[-1]
        years_str = f"（{y0}年〜{y1}年）" if y0 != y1 else f"（{y0}年）"
    return {
        "n_trips": n_trips,
        "n_ships": len(ship_trips),
        "top_ships": top_ships,
        "cnt_med": cnts[cn // 2] if cn else None,
        "cnt_p25": cnts[int(cn * 0.25)] if cn >= 4 else (cnts[0] if cn else None),
        "cnt_p75": cnts[int(cn * 0.75)] if cn >= 4 else (cnts[-1] if cn else None),
        "cnt_max": cnts[-1] if cn else None,
        "cm_med": cms[len(cms) // 2] if cms else None,
        "cm_max": cms[-1] if cms else None,
        "years_str": years_str,
    }


def build_fish_area_pages(data, crawled_at="", history=None, decadal_calendar=None, hist_rows=None, fish_area_summary=None, fish_top_areas=None):
    fa_out_dir = os.path.join(WEB_DIR, "fish_area")
    os.makedirs(fa_out_dir, exist_ok=True)

    # 孤児削除用: hist_rows を先にロード（パージブロックで使用するため前倒し）
    _hist_rows_for_fa = hist_rows if hist_rows is not None else _load_historical_catches()

    # 孤児削除用: hist_rows ベースの (fish, area) セットを構築
    _hist_fa_set: set = set()
    for _r in _hist_rows_for_fa:
        if _r.get("is_cancellation") == "1":
            continue
        _f = _r.get("tsuri_mono")
        _a = _r.get("area")
        if _f and _a:
            _hist_fa_set.add((_f, _a))

    # 孤児削除用: fish_area_summary が渡されていれば追加
    _fas_fa_set: set = set()
    if fish_area_summary:
        _fas_fa_set = set(fish_area_summary.keys())

    # 孤児削除用: 引数 data（当日 catches）から (fish, area) セットを構築
    # T34 の 7日窓フィルタを孤児判定にも適用する。
    # catches.json が _today_only=False（全件フォールバック）のとき全過去データが混入し
    # 孤児ペアが _today_fa_set に入って削除されなくなる問題を防ぐ。
    # ここで cutoff を先算しておき、T34 本体（後段の data 上書き）と同じ7日窓を適用する。
    _now_fa = datetime.now(JST).replace(tzinfo=None)
    _cutoff_date_T34_fa = (_now_fa - timedelta(days=6)).strftime("%Y/%m/%d")  # today含めて7日
    _today_fa_set: set = set()
    for _c in data:
        if _c.get("date", "") < _cutoff_date_T34_fa:
            continue
        _ca = _c.get("area", "")
        for _cf in _c.get("fish", []):
            if _cf and _cf != "不明":
                _today_fa_set.add((_cf, _ca))

    # 有効 (fish, area) セット = hist + fish_area_summary + 当日 catches いずれかに存在
    _valid_fa_set = _hist_fa_set | _fas_fa_set | _today_fa_set

    # 孤児削除用: fish slug → 日本語 / area slug → 日本語 の逆引き辞書
    # 重複なし（事前確認済み）のためシンプルに dict comprehension
    _fish_slug_rev: dict = {v: k for k, v in _FISH_ROMAJI.items()}
    _area_slug_rev: dict = {v: k for k, v in _AREA_ROMAJI.items()}
    # 長いslugを優先してマッチするためキーを長い順にソート
    _fish_slugs_sorted = sorted(_fish_slug_rev.keys(), key=len, reverse=True)

    def _parse_fa_filename(stem: str):
        """'{fish_slug}-{area_slug}' を (fish_jp, area_jp) に分解。
        逆引き不可・曖昧な場合は (None, None) を返す（パージ対象外＝安全側）。"""
        for fs in _fish_slugs_sorted:
            if stem.startswith(fs + "-"):
                area_slug = stem[len(fs) + 1:]
                fish_jp = _fish_slug_rev.get(fs)
                area_jp = _area_slug_rev.get(area_slug)
                if fish_jp and area_jp:
                    return fish_jp, area_jp
                # area_slug が一致しない場合はさらに短い fish slug を試す
                # （ループが続くので continue）
                continue
        return None, None

    # 古いフォーマット (OGP なし = PR #34 以前) および孤児 HTML を削除。
    # 当日 5件未満の魚×エリアコンボは再生成スキップされるため、古いまま残り続けると
    # validate_output.py の不変条件 [19] OGP メタタグ / [20] share-bar で永続 fail する。
    # 新フォーマットでない HTML は責任を持って削除し、当日条件を満たすコンボのみ
    # 新フォーマットで再生成する設計に揃える。
    _orphan_purge_count = 0
    for _fn in os.listdir(fa_out_dir):
        if not _fn.endswith(".html") or _fn == "index.html":
            continue
        _p = os.path.join(fa_out_dir, _fn)
        try:
            with open(_p, encoding="utf-8") as _f:
                _h = _f.read()
            # T30 (2026/05/12): OGP無し（PR#34以前）または 古い FAQ v1 形式
            # （T28以前・当日 fa_catches 依存で「直近{N}件」「データ蓄積中」表現を含む）を削除
            is_old_ogp = 'property="og:image"' not in _h
            is_old_faq_v1 = ('直近データ（' in _h or 'データ蓄積中（' in _h or
                            'を集計中です。このページの年間シーズンバー' in _h)
            if is_old_ogp or is_old_faq_v1:
                os.remove(_p)
                continue
            # T38 孤児削除: hist_rows・当日 catches・fish_area_summary のいずれにも
            # 存在しない (fish, area) ペアの HTML を削除する。
            # 逆引き不可 / 曖昧なファイル名は安全側に倒してパージ対象外。
            _stem = _fn[:-5]  # ".html" を除いたstem
            _fj, _aj = _parse_fa_filename(_stem)
            if _fj is not None and _aj is not None:
                if (_fj, _aj) not in _valid_fa_set:
                    print(f"[orphan-purge] {_fn}: hist=0 today=0 -> delete")
                    os.remove(_p)
                    _orphan_purge_count += 1
        except Exception:
            pass
    if _orphan_purge_count > 0:
        print(f"[orphan-purge] 孤児 HTML {_orphan_purge_count} 本削除完了")

    if decadal_calendar is None:
        decadal_calendar = load_decadal_calendar()
    # H3 (T22): area_description.json をロード（エリア固有1文をイントロに差し込む）
    _area_desc_fa = load_area_description()
    # 年間シーズンバーを実データで生成するため過去CSV（共有キャッシュまたは個別ロード）
    # ※ _hist_rows_for_fa は孤児削除ブロックで既にロード済み
    _fish_top_areas_fa = fish_top_areas or {}
    # 2026/05/13 T34拡張: valid_catches を直近7日窓に絞る。
    # fishing-v.jp の船宿ページは最新ページ(pageID=1)を返す仕様だが、
    # シーズンオフ魚種・休止中船宿では数ヶ月前の釣果が最新ページに残ったまま
    # 更新されない場合があり、当日クロール結果に混入する。
    # T34 (build_fish_pages) と同じ7日窓フィルタを fish_area にも適用。
    # 注: T34本体は data_recent 別名だが、ここでは下流の処理が全て同じ変数名を
    # 使うため破壊的上書きで簡潔化。呼び出し側で同一リストの再参照なし。
    # _now_fa / _cutoff_date_T34_fa は孤児削除ブロックで既に算出済み（同値）
    data = [c for c in data if c.get("date", "") >= _cutoff_date_T34_fa]
    # build_fish_pages と同様に chowari 等 CSV ソース（valid_catches 未収録）をマージ
    try:
        _recent7_fa = _load_recent_catches_for_index(_now_fa, days=7)
    except Exception:
        _recent7_fa = []
    _seen_fa = {(c.get("ship"), c.get("date"), c.get("fish_raw", "")) for c in data}
    for _c in _recent7_fa:
        _k = (_c.get("ship"), _c.get("date"), _c.get("fish_raw", ""))
        if _k not in _seen_fa:
            data.append(_c)
            _seen_fa.add(_k)
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
.sr .sr-size{flex:0 0 70px;font-size:11px;color:var(--sub)}
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
.sb-legend .leg-size::before{content:"";display:inline-block;width:8px;height:8px;background:#7209b7;border-radius:2px;margin-right:3px;vertical-align:middle}
.chip-wrap{display:flex;flex-wrap:wrap;gap:6px;margin:10px 0}
.chip-link{background:var(--card);border:1px solid var(--border);border-radius:16px;padding:5px 12px;font-size:12px;color:var(--accent);text-decoration:none;font-weight:600;display:inline-flex;align-items:center;gap:4px}
.chip-link:hover{background:var(--accent);color:#fff;text-decoration:none}
.chip-emoji{vertical-align:middle}
.chip-pref{width:14px;height:14px;object-fit:contain;flex-shrink:0}
.chip-area{display:inline-flex;align-items:center;gap:4px}
.tier-label{font-size:11px;color:var(--muted);margin:8px 0 2px;font-weight:600}
.fold-chips{margin:4px 0 8px}
.fold-chips summary{font-size:12px;color:var(--accent);cursor:pointer;padding:4px 0}
.fold-chips .chip-wrap{margin-top:6px}
.fa-related{margin-bottom:16px}
.fa-h2-emoji{vertical-align:middle;margin-right:6px}
.chart7{background:var(--card);border:1px solid var(--border);border-radius:var(--r);padding:14px;margin-bottom:16px}
.chart7 h3{font-size:13px;font-weight:700;color:var(--accent);margin-bottom:8px}
.chart-bars{display:flex;align-items:flex-end;gap:3px;height:60px}
.chart-bars .cb{flex:1;background:var(--cta);border-radius:2px 2px 0 0;opacity:.7;min-width:10px}
.chart-bars .cb.weekend{opacity:.8;background:var(--weekend)}
.chart-bars .cb.today{opacity:1;background:var(--pos);outline:1.5px solid var(--accent);outline-offset:-1.5px}
.chart-labels{display:flex;justify-content:space-between;font-size:9px;color:var(--muted);margin-top:3px}
.chart-labels span.weekend{color:#c66a14}
.chart-labels span.today{color:var(--pos);font-weight:700;border-bottom:2px solid var(--pos);padding-bottom:1px}
.chart-trend{text-align:center;margin-top:6px;font-size:12px;font-weight:700;color:var(--pos)}
.chart-trend.down{color:var(--warn)}.chart-trend.flat{color:var(--sub)}"""

    # 深夜0時境界で _now_fa とズレないよう統一（reviewer 指摘）
    now_fa_global = _now_fa
    current_month_fa = now_fa_global.month
    year_fa_g, week_num_fa_g = current_iso_week()

    # T29: fish_area 同士の相互リンク用に、3年分 hist の (fish, area) 件数を集計。
    # _is_cancelled_row フィルタで欠航除外（MAJOR-1 修正）。
    # 便 = ユニーク (ship, date, trip_no)。行数（魚種×便レコード）を便と数えると
    # 重複行/main・sub で水増しするため set で出船便を数える（2026/06/20 修正）。
    _fa_hist_trips: dict = {}
    for r in _hist_rows_for_fa:
        if _is_cancelled_row(r):
            continue
        _f = r.get("tsuri_mono")
        _a = r.get("area")
        if _f and _a and _f != "不明":
            _fa_hist_trips.setdefault((_f, _a), set()).add((r.get("ship"), r.get("date"), r.get("trip_no")))
    fa_hist_count: dict = {k: len(v) for k, v in _fa_hist_trips.items()}
    will_generate_fa = {(f, a) for (f, a), cs in fa_summary.items() if len(cs) >= 1}
    # ディスク上に既に存在する fish_area HTML も link 対象に含める（T29: 通年リンク網）
    fa_out_dir = os.path.join(WEB_DIR, "fish_area")
    existing_fa_files: set = set()
    if os.path.isdir(fa_out_dir):
        for _fn in os.listdir(fa_out_dir):
            if _fn.endswith(".html") and _fn != "index.html":
                existing_fa_files.add(_fn[:-5])  # slug-slug 形式
    # 同魚種他エリア・同エリア他魚種の件数を事前集計（ループ内で再利用）
    same_fish_areas: dict = {}  # fish -> [(area, hist_count), ...] sorted desc
    same_area_fishes: dict = {}  # area -> [(fish, hist_count), ...] sorted desc
    for (_f, _a), _n in fa_hist_count.items():
        same_fish_areas.setdefault(_f, []).append((_a, _n))
        same_area_fishes.setdefault(_a, []).append((_f, _n))
    for _f in same_fish_areas:
        same_fish_areas[_f].sort(key=lambda x: -x[1])
    for _a in same_area_fishes:
        same_area_fishes[_a].sort(key=lambda x: -x[1])

    # T38-A2 修正 (2026/05/15): 直近7日 (fish, area) ペアは fa_summary のキーから全コンボ横断で構築。
    # 旧実装は per-page catches から構築していたため、軸1（同魚種・他エリア）は area が固定で常に空、
    # 軸2（同エリア・他魚種）も bycatch しか拾えず、tsuri_mono が主対象の他魚種が全てfoldに落ちていた。
    _recent7_fish_area_global = set(fa_summary.keys())

    def _fa_page_available(_f, _a):
        """fish_area ページが今回生成される or 既存ディスクにあるなら True"""
        if (_f, _a) in will_generate_fa:
            return True
        slug = f"{fish_slug(_f)}-{area_slug(_a)}"
        return slug in existing_fa_files

    count = 0
    # 生成閾値: 2026-05-10 ユーザー判断で 5 件 → 1 件に変更（記録ボリューム重視）。
    # 旧: 統計カード/ランキングが薄くならない最低件数として 5 件
    # 新: 1 件でも記録があれば fish_area ページを生成（薄いページが増えても網羅性優先）
    for (fish, area), catches in fa_summary.items():
        if len(catches) < 1:
            continue
        max_cnt = 0
        personal_catches = []
        for c in catches:
            cr = c.get("count_range")
            if cr and not cr.get("is_boat"):
                # P2 (2026/05/31): cr["max"] が None だと TypeError。0 にフォールバック
                _cmx = cr.get("max")
                max_cnt = max(max_cnt, _cmx if isinstance(_cmx, (int, float)) else 0)
                personal_catches.append(c)
        # コンボ統計
        combo_avg = 0
        if personal_catches:
            avgs = [(c["count_range"]["min"] + c["count_range"]["max"]) // 2 for c in personal_catches]
            combo_avg = round(sum(avgs) / len(avgs), 1)
        ship_num = len(set(c["ship"] for c in catches))
        # 過去3年コンボ統計（FAQ Q2 と同一ソース）。hero/intro/title の数値整合に使用。
        _hs = _fa_hist_stats(fish, area, _hist_rows_for_fa)
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
        # hero スタッツは過去3年（hist）ベースに統一。intro・FAQ と数値を一致させ
        # 「今週1便/最高45匹 vs FAQ 383便/最高273匹」の自己矛盾を解消する。
        # hist が空（新規コンボ等）の場合のみ当週値にフォールバック。
        _hs_ships = _hs["n_ships"] or ship_num
        _hs_med = _hs["cnt_med"]
        _hs_max = _hs["cnt_max"] if _hs["cnt_max"] is not None else (int(max_cnt) if max_cnt else None)
        stat_cards_fa = f"""<div class="stat-cards">
  <div class="stat-card"><div class="sv">{_hs_ships}船宿</div><div class="sl">出船船宿数(3年)</div></div>
  <div class="stat-card"><div class="sv">{(str(_hs_med) + '匹') if _hs_med else '-'}</div><div class="sl">釣果目安(中央値)</div></div>
  <div class="stat-card"><div class="sv">{(str(_hs_max) + '匹') if _hs_max else '-'}</div><div class="sl">最高釣果(3年)</div></div>
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
            d = ship_data_fa.setdefault(c["ship"], {"cnt": 0, "his": [], "los": [], "boat_his": [], "boat_los": [], "sz_his": [], "sz_los": [], "today": False})
            d["cnt"] += 1
            cr = c.get("count_range")
            if _cnt_personal(cr):
                if cr.get("max") is not None:
                    d["his"].append(cr["max"])
                if cr.get("min") is not None:
                    d["los"].append(cr["min"])
                elif cr.get("max") is not None:
                    d["los"].append(cr["max"])
            elif cr and cr.get("is_boat"):
                if cr.get("max") is not None:
                    d["boat_his"].append(cr["max"])
                if cr.get("min") is not None:
                    d["boat_los"].append(cr["min"])
                elif cr.get("max") is not None:
                    d["boat_los"].append(cr["max"])
            sz = c.get("size_cm")
            if sz:
                if sz.get("max") is not None:
                    d["sz_his"].append(sz["max"])
                if sz.get("min") is not None:
                    d["sz_los"].append(sz["min"])
            if c.get("date") == today_str_fa:
                d["today"] = True
        sr_items_fa = ""
        def _sr_sort_key(item):
            sd = item[1]
            return -(max(sd["his"]) if sd["his"] else (max(sd["boat_his"]) if sd["boat_his"] else 0))
        for i, (sn, sd) in enumerate(sorted(ship_data_fa.items(), key=_sr_sort_key)[:8]):
            s_lo = int(min(sd["los"])) if sd["los"] else None
            s_hi = int(max(sd["his"])) if sd["his"] else None
            if s_lo is not None and s_hi is not None and s_lo != s_hi:
                s_range = f"{s_lo}〜{s_hi}匹"
            elif s_hi is not None:
                s_range = f"{s_hi}匹"
            elif sd["boat_his"]:
                b_lo = int(min(sd["boat_los"])) if sd["boat_los"] else None
                b_hi = int(max(sd["boat_his"]))
                if b_lo is not None and b_lo != b_hi:
                    s_range = f"船中{b_lo}〜{b_hi}匹"
                else:
                    s_range = f"船中{b_hi}匹"
            else:
                s_range = f"{sd['cnt']}便"
            sz_lo = int(min(sd["sz_los"])) if sd["sz_los"] else None
            sz_hi = int(max(sd["sz_his"])) if sd["sz_his"] else None
            if sz_lo is not None and sz_hi is not None and sz_lo != sz_hi:
                sz_range = f"{sz_lo}〜{sz_hi}cm"
            elif sz_hi is not None:
                sz_range = f"{sz_hi}cm"
            else:
                sz_range = ""
            sr_items_fa += (
                f'<div class="sr">'
                f'<span class="sr-rank">{i+1}</span>'
                f'<span class="sr-name">{_ship_link(sn, depth=1)}</span>'
                f'<span class="sr-range">{s_range}</span>'
                + (f'<span class="sr-size">{sz_range}</span>' if sz_range else "")
                + f'<span class="sr-pt">{sd["cnt"]}便</span></div>'
            )
        ship_rank_fa_html = f'<div class="ship-rank"><h3>船宿ランキング（今週）</h3>{sr_items_fa}</div>' if sr_items_fa else ""
        # V2: 最近の釣果（sl-card スタイル）
        recent_cards_fa = ""
        for c in sorted(catches, key=lambda x: x.get("date") or "", reverse=True)[:10]:
            cnt_str = fmt_count(c)
            if cnt_str:
                cnt_str = cnt_str + "匹"
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
        fa_intro_html = _build_fa_intro_html(fish, area, catches, decadal_calendar, area_description=_area_desc_fa, hist_stats=_hs)
        # T30 (2026/05/12): catches → _hist_rows_for_fa（3年分CSV）に変更で固定文章化。
        fa_faq_html, fa_faq_ld = build_fish_area_faq_html(fish, area, _hist_rows_for_fa, decadal_calendar, _area_desc_fa)
        # T38-A2: fa-related 3軸構造（閾値廃止・全件常駐・折り畳み付き）
        # 直近7日 (fish, area) ペアは fa_summary 全体から構築（per-page catches だと area 固定で軸1が機能しない）
        _recent7_fish_area = _recent7_fish_area_global
        _related_blocks = []

        # 軸1: 同魚種・他エリア
        _other_areas = [(a2, n2) for (a2, n2) in same_fish_areas.get(fish, [])
                        if a2 != area and _fa_page_available(fish, a2)]
        if _other_areas:
            _oa_active = [(a2, n2) for (a2, n2) in _other_areas if (fish, a2) in _recent7_fish_area]
            _oa_fold   = [(a2, n2) for (a2, n2) in _other_areas if (fish, a2) not in _recent7_fish_area]
            _axis1_html = f'<h2 class="st">{fish}を他のエリアで探す</h2>'
            if _oa_active:
                _axis1_html += f'<p class="tier-label">★ 今週実績あり（{sum(n2 for _,n2 in _oa_active)}便）</p>'
                _axis1_html += '<div class="chip-wrap">'
                for a2, n2 in _oa_active[:6]:
                    _axis1_html += (
                        f'<a href="../fish_area/{fish_slug(fish)}-{area_slug(a2)}.html" class="chip-link chip-area">'
                        f'{_chip_pref_img(a2)}{a2}（{n2}便）</a>'
                    )
                _axis1_html += '</div>'
            if _oa_fold:
                _axis1_html += f'<details class="fold-chips"><summary>過去実績あり（今週ゼロ・{sum(n2 for _,n2 in _oa_fold)}便）を表示</summary><div class="chip-wrap">'
                for a2, n2 in _oa_fold[:12]:
                    _axis1_html += (
                        f'<a href="../fish_area/{fish_slug(fish)}-{area_slug(a2)}.html" class="chip-link chip-area">'
                        f'{_chip_pref_img(a2)}{a2}（{n2}便）</a>'
                    )
                _axis1_html += '</div></details>'
            _related_blocks.append(_axis1_html)

        # 軸2: 同エリア・他魚種
        _other_fishes = [(f2, n2) for (f2, n2) in same_area_fishes.get(area, [])
                         if f2 != fish and _fa_page_available(f2, area)]
        if _other_fishes:
            _of_active = [(f2, n2) for (f2, n2) in _other_fishes if (f2, area) in _recent7_fish_area]
            _of_fold   = [(f2, n2) for (f2, n2) in _other_fishes if (f2, area) not in _recent7_fish_area]
            _axis2_html = f'<h2 class="st">{area}で実績のある他の魚種</h2>'
            if _of_active:
                _axis2_html += f'<p class="tier-label">★ 今週実績あり（{sum(n2 for _,n2 in _of_active)}便）</p>'
                _axis2_html += '<div class="chip-wrap">'
                for f2, n2 in _of_active[:6]:
                    _axis2_html += (
                        f'<a href="../fish_area/{fish_slug(f2)}-{area_slug(area)}.html" class="chip-link">'
                        f'<img src="../assets/fish/{fish_img_slug(f2)}/{fish_img_slug(f2)}_emoji.webp" alt="{f2}" class="chip-emoji" width="16" height="16" loading="lazy" decoding="async" onerror="this.style.display=\'none\'">'
                        f'{f2}（{n2}便）</a>'
                    )
                _axis2_html += '</div>'
            if _of_fold:
                _axis2_html += f'<details class="fold-chips"><summary>過去実績あり（今週ゼロ・{sum(n2 for _,n2 in _of_fold)}便）を表示</summary><div class="chip-wrap">'
                for f2, n2 in _of_fold[:12]:
                    _axis2_html += (
                        f'<a href="../fish_area/{fish_slug(f2)}-{area_slug(area)}.html" class="chip-link">'
                        f'<img src="../assets/fish/{fish_img_slug(f2)}/{fish_img_slug(f2)}_emoji.webp" alt="{f2}" class="chip-emoji" width="16" height="16" loading="lazy" decoding="async" onerror="this.style.display=\'none\'">'
                        f'{f2}（{n2}便）</a>'
                    )
                _axis2_html += '</div></details>'
            _related_blocks.append(_axis2_html)

        # 軸3: 関連魚種（同港共起）
        _co_fish_list = compute_fish_related_via_cooccurrence(_hist_rows_for_fa, fish, _fish_top_areas_fa)
        if _co_fish_list:
            _axis3_html = f'<h2 class="st">{fish}と合わせて釣れる魚</h2><div class="chip-wrap">'
            for f2, n2 in _co_fish_list:
                _axis3_html += (
                    f'<a href="../fish/{fish_slug(f2)}.html" class="chip-link">'
                    f'<img src="../assets/fish/{fish_img_slug(f2)}/{fish_img_slug(f2)}_emoji.webp" alt="{f2}" class="chip-emoji" width="16" height="16" loading="lazy" decoding="async" onerror="this.style.display=\'none\'">'
                    f'{f2}（{n2}便）</a>'
                )
            _axis3_html += '</div>'
            _related_blocks.append(_axis3_html)

        fa_related_html = f'<div class="fa-related">{"".join(_related_blocks)}</div>' if _related_blocks else '<div class="fa-related"></div>'
        # 直近7日間の釣果推移チャート（fish/* と同じ関数を流用）
        chart7_html_fa = build_fish_7day_chart_html(fish, catches)
        page_url = f"{SITE_URL}/fish_area/{fish_slug(fish)}-{area_slug(area)}.html"
        # P2 (2026/05/31): title/description を CTR 訴求型に強化（GSC SEO改善 2/4）
        # 「今週N便」は N=0 のとき薄ページを露呈するため、出船状況で4分岐:
        #   ① 出船あり+乗合釣果あり → 船宿数・最高釣果の具体数値（最強の CTR 訴求）
        #   ② 出船あり・釣果数値なし（仕立て便等） → 今週便数
        #   ③ 今週0便+過去実績あり → 過去実績（hist_count・3年累計の釣果件数）に切替
        #   ④ 今週0便+過去実績0 → 数値を出さず汎用文（hist_n=0 露出を防ぐ）
        # 数値は当該ページの実測値/3年累計でいずれも事実（無料=事実の方針）
        # title 本体と「| 船釣り予想」を分離（OGP title と共用・replace 依存を排除）
        _fa_hist_n = fa_hist_count.get((fish, area), 0)
        _fa_ship_num = len({c.get("ship") for c in catches if c.get("ship")})
        if len(catches) >= 1 and max_cnt > 0:
            # title/hero は3年hist値で統一（_hs_ships/_hs_max は stat card と同値・自己矛盾防止）。
            fa_title_body = f"{fish}釣果 {area}【{_hs_ships}船宿・最高{_hs_max}匹】"
            desc = f"{area}の{fish}釣果を船宿別ランキングで掲載。今週{len(catches)}便・過去3年で最高{_hs_max}匹。旬カレンダーと船宿情報を毎日更新。"
        elif len(catches) >= 1:
            fa_title_body = f"{fish}釣果 {area}【今週{len(catches)}便出船】"
            desc = f"{area}の{fish}釣果情報。今週{len(catches)}便出船。過去{_fa_hist_n}便の実績から旬カレンダーと船宿別ランキングを毎日更新。"
        elif _fa_hist_n > 0:
            fa_title_body = f"{fish}釣果 {area}【過去{_fa_hist_n}便の実績】"
            desc = f"{area}の{fish}釣果情報。過去{_fa_hist_n}便の実績から旬カレンダーと船宿別ランキングを公開。例年の最盛期と釣果傾向を確認できます。"
        else:
            fa_title_body = f"{fish}釣果 {area}の船宿情報"
            desc = f"{area}の{fish}釣果情報。旬カレンダーと船宿別ランキングを公開。例年の最盛期と釣果傾向を確認できます。"
        fa_title_str = f"{fa_title_body} | 船釣り予想"
        fa_share_title = fa_title_body
        # T39 (2026/05/25): hist_count < 30 のコンボは FAQ 等の固定文章が薄く
        # AdSense「有用性の低いコンテンツ」判定リスクが高いため noindex を付与し
        # sitemap から除外する。ページ自体は内部リンク経由でユーザーに到達可能。
        # （_fa_hist_n は上で算出済み）
        _fa_slug_stem = f"{fish_slug(fish)}-{area_slug(area)}"
        if _fa_hist_n < _FA_NOINDEX_HIST_THRESHOLD:
            fa_noindex_tag = '<meta name="robots" content="noindex, follow">'
            _FA_NOINDEX_SLUGS.add(_fa_slug_stem)
        else:
            fa_noindex_tag = ""
        html = f"""<!DOCTYPE html>
<html lang="ja"><head>
  <meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="icon" href="/favicon.ico" sizes="48x48"><link rel="apple-touch-icon" href="/apple-touch-icon.png">
  <title>{fa_title_str}</title>
  <meta name="description" content="{desc}">
  {fa_noindex_tag}
  <link rel="canonical" href="{page_url}">
  {_build_share_meta(
      title=fa_share_title,
      desc=desc,
      url=page_url,
      og_image=_resolve_fish_ogp_image(fish),
  )}
  <script type="application/ld+json">{{"@context":"https://schema.org","@type":"BreadcrumbList","itemListElement":[{{"@type":"ListItem","position":1,"name":"トップ","item":"{SITE_URL}/"}},{{"@type":"ListItem","position":2,"name":"魚種一覧","item":"{SITE_URL}/fish/"}},{{"@type":"ListItem","position":3,"name":"{fish}の釣果","item":"{SITE_URL}/fish/{fish_slug(fish)}.html"}},{{"@type":"ListItem","position":4,"name":"{area}の{fish}釣果","item":"{page_url}"}}]}}</script>
  {fa_faq_ld}
  {GA_TAG}
  {'' if fa_noindex_tag else ADSENSE_TAG}
  <link rel="stylesheet" href="../style.css">
  <style>
{fa_extra_css}
.fa-intro{{font-size:13px;line-height:1.7;color:var(--text);margin-bottom:16px}}</style>
</head>
<body>
{_v2_header_nav('')}
<div class="c">
  <p class="bread"><a href="../">トップ</a> &rsaquo; <a href="../fish/{fish_slug(fish)}.html">{fish}</a> &rsaquo; {area}<span class="bread-sep"> ／ </span><a href="../area/{area_slug(area)}.html">{area}エリア</a> &rsaquo; {fish}</p>
  {_build_share_buttons(
      share_text=f"{area}の{fish}釣果情報 | 船釣り予想",
      share_url=page_url,
  )}
  <h1 class="st"><img src="../assets/fish/{fish_img_slug(fish)}/{fish_img_slug(fish)}_emoji.webp" alt="{fish}" class="fa-h2-emoji" width="22" height="22" loading="lazy" decoding="async" onerror="this.style.display='none'">{area}の{fish}釣果情報</h1>
  {fa_intro_html}
  {stat_cards_fa}
  {chart7_html_fa}
  <h2 class="st">{area}の{fish}旬カレンダー <span class="tag free">無料</span></h2>
  {combo_season_map_fa}
  {combo_comment_html}
  <h2 class="st">船宿ランキング <span class="tag free">無料</span></h2>
  {ship_rank_fa_html}
  <h2 class="st">最近の釣果 <span class="tag free">無料</span></h2>
  {recent_cards_fa}
  {fa_related_html}
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
    if _FA_NOINDEX_SLUGS:
        print(f"  └ うち noindex 付与: {len(_FA_NOINDEX_SLUGS)} 件（hist_count < {_FA_NOINDEX_HIST_THRESHOLD}・AdSense 薄判定対策）")

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
        # SEASON_DATA にはページ未生成の魚種（コハダ・アカイカ等）も含まれるため、
        # fish/{slug}.html が実在する場合のみリンク化（リンク切れ防止・2026-06-10）
        _cal_inner = f"<img src='assets/fish/{fish_img_slug(fish)}/{fish_img_slug(fish)}_emoji.webp' alt='{fish}' class='cal-emoji' width='20' height='20' loading='lazy' decoding='async' onerror='this.style.display=\"none\"'>{fish}"
        if os.path.exists(os.path.join(WEB_DIR, "fish", f"{fish_slug(fish)}.html")):
            _cal_cell = f"<a href='fish/{fish_slug(fish)}.html'>{_cal_inner}</a>"
        else:
            _cal_cell = _cal_inner
        rows += f"<tr><td class='fish-name'>{_cal_cell}</td>{cells}</tr>"
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
<link rel="icon" href="/favicon.ico" sizes="48x48"><link rel="apple-touch-icon" href="/apple-touch-icon.png">
  <title>関東船釣り 旬カレンダー | 月別釣りものガイド | 船釣り予想</title>
  <meta name="description" content="関東エリアの船釣り旬カレンダー。アジ・マダイ・タチウオ・ヒラメなど50魚種以上の月別シーズン表。数釣り・型釣りのピーク月が一目でわかる。">
  <link rel="canonical" href="{SITE_URL}/calendar.html">
  {_build_share_meta(
      title="関東船釣り 旬カレンダー | 月別釣りものガイド",
      desc="関東エリアの船釣り旬カレンダー。50魚種以上の月別シーズン表。数釣り・型釣りのピーク月が一目でわかる。",
      url=f"{SITE_URL}/calendar.html",
  )}
  <script type="application/ld+json">{{"@context":"https://schema.org","@type":"BreadcrumbList","itemListElement":[{{"@type":"ListItem","position":1,"name":"トップ","item":"{SITE_URL}/"}},{{"@type":"ListItem","position":2,"name":"旬カレンダー","item":"{SITE_URL}/calendar.html"}}]}}</script>
  <script type="application/ld+json">{{"@context":"https://schema.org","@type":"WebPage","name":"関東船釣り 旬カレンダー","description":"関東エリアの船釣り旬カレンダー。50魚種以上の月別シーズン表。","url":"{SITE_URL}/calendar.html","isPartOf":{{"@type":"WebSite","name":"船釣り予想","url":"{SITE_URL}/"}}}}</script>
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
  <p class="bread"><a href="/">トップ</a> &rsaquo; 旬カレンダー</p>
  <h1 class="st">月別 釣りものカレンダー <span class="tag free">無料</span></h1>
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
      - 無料プランCTA のみ有効（href="../"）
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
.bread{font-size:11px;color:var(--muted);padding:10px 0;line-height:1.6}.bread a{color:var(--sub)}.bread .bread-sep{white-space:nowrap;display:inline-block;padding:0 4px;color:var(--muted)}
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
<link rel="icon" href="/favicon.ico" sizes="48x48"><link rel="apple-touch-icon" href="/apple-touch-icon.png">
<meta name="robots" content="noindex, follow">
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
<div class="bread"><a href="../">トップ</a> &gt; <a href="../forecast/">有料プラン</a> &gt; プラン比較</div>

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
<a class="plan-cta" href="../">無料で使う</a>
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


# ============================================================
# 複合主役船ルール（オプトイン制・2026/05/16 追加）
# ============================================================
# 「マダイ五目のアジは外道扱い」を維持しつつ、明示登録した便種のみ複合メインを許容。
# 列挙にない便種は単一メイン（既存ロジック維持・五目分岐込み）
#
# SHIP_KANSO_MULTI_MAIN: kanso_raw 先頭プレフィックスで判定
#   船宿が kanso 冒頭に船種名を書く場合（仁徳丸・清勝丸・丸天丸・浜べ丸・稲荷丸・治久丸ほか）
SHIP_KANSO_MULTI_MAIN = {
    "仁徳丸": [
        ("オニカサゴ・アラ五目", frozenset({"オニカサゴ", "アラ"})),
        ("アラ・オニカサゴ五目", frozenset({"アラ", "オニカサゴ"})),
    ],
    "清勝丸": [
        ("アジ+ハナダイ五目",   frozenset({"アジ", "ハナダイ"})),
        ("アジハナダイ五目",     frozenset({"アジ", "ハナダイ"})),
        ("アジ・ハナダイ五目",   frozenset({"アジ", "ハナダイ"})),
        ("沖根魚",               frozenset({"アラ", "オニカサゴ"})),
    ],
    "丸天丸": [
        ("メヌケ船",     frozenset({"メヌケ", "アブラボウズ"})),
        ("アラ五目",     frozenset({"アラ", "オニカサゴ"})),
    ],
    "浜べ丸": [
        ("鬼五目",         frozenset({"オニカサゴ", "アラ"})),
        ("ジギング青物",   frozenset({"ワラサ", "イナダ"})),
        # 「ジギング五目」は単独主役（ヒラメ）→ 登録しない
    ],
    "稲荷丸": [
        # 鴨川稲荷丸（江見漁港）のみ該当・既存「稲荷丸（由比/静岡）」とは別船宿
        ("アラ釣り＋アマダイ五目",   frozenset({"アラ", "アマダイ"})),
        ("アラ＋アマダイ五目",       frozenset({"アラ", "アマダイ"})),
        ("アラ五目＋アマダイ五目",   frozenset({"アラ", "アマダイ"})),
        ("マダイ五目＋アマダイ五目", frozenset({"マダイ", "アマダイ"})),
        ("マダイ＋アマダイ五目",     frozenset({"マダイ", "アマダイ"})),
    ],
    "治久丸": [
        ("カイワリ・イサキ",       frozenset({"カイワリ", "イサキ"})),
        ("カイワリからのイサキ",   frozenset({"カイワリ", "イサキ"})),
        ("カイワリ＋イサキ",       frozenset({"カイワリ", "イサキ"})),
    ],
    # 2026/05/17: 千葉外房 B群拡張で追加
    "幸辰丸": [
        # kanso 例: 「朝便、午前イサキ良型混じりで釣れました 後半ハナダイは…」
        #          「イサキハナダイリレー船」「イサキハナダイリレー」
        ("イサキハナダイリレー",   frozenset({"イサキ", "ハナダイ"})),
        ("イサキ・ハナダイリレー", frozenset({"イサキ", "ハナダイ"})),
        # 単発 startswith 用 prefix
        ("朝便", frozenset({"イサキ", "ハナダイ"})),  # 「朝便、午前イサキ…後半ハナダイ」=リレー船
    ],
    "第三孝徳丸": [
        # kanso 例: 「朝便はイサキ花鯛リレー釣りで出船…」「朝便は花鯛五目で出船…」
        ("イサキ花鯛リレー",   frozenset({"イサキ", "ハナダイ"})),
        ("イサキ・花鯛リレー", frozenset({"イサキ", "ハナダイ"})),
        ("花鯛五目",           frozenset({"ハナダイ"})),  # 単独便（複合主役ではないが正しい主役を確定）
    ],
    "新栄丸": [
        # kanso 例: 「黒ムツ・マダイ五目で出船」「マダイ五目で出船」
        ("黒ムツ・マダイ五目", frozenset({"クロムツ", "マダイ"})),
        ("黒ムツ＋マダイ",     frozenset({"クロムツ", "マダイ"})),
        ("クロムツ・マダイ",   frozenset({"クロムツ", "マダイ"})),
    ],
}

# SHIP_TRIP_FISHSET_MULTI_MAIN: 同一trip内の魚種セットで判定
#   kanso に船種ワードが無い船宿用（三次郎丸タイプ）
SHIP_TRIP_FISHSET_MULTI_MAIN = {
    "三次郎丸": [
        # trip内に {アラ, オニカサゴ} 両方あれば → 両方メイン
        (frozenset({"アラ", "オニカサゴ"}), frozenset({"アラ", "オニカサゴ"})),
    ],
}


def _get_multi_main(ship, kanso_raw, trip_fish_set):
    """複数主役の判定（オプトイン制）。
    1) ship + kanso_raw 先頭プレフィックス（startswith）または先頭80字以内に含む → 該当ルール
    2) ship + trip 内魚種セット部分一致 → 該当ルールの主役セット
    3) 該当なし → frozenset() （既存ロジックに落ちる）

    2026/05/17: 「リレー船」「五目」が kanso 先頭ではなく中間に来る船宿
    （幸辰丸・第三孝徳丸・新栄丸 等）対応のため、head[:80] に含むかも判定。"""
    # (1) Kansoマッチ（先頭プレフィックス or 先頭80字以内に含む）
    if ship and ship in SHIP_KANSO_MULTI_MAIN and kanso_raw:
        head = kanso_raw.lstrip()
        head_80 = head[:80]
        for prefix, main_set in SHIP_KANSO_MULTI_MAIN[ship]:
            if head.startswith(prefix) or prefix in head_80:
                return main_set
    # (2) 同一trip魚種セット
    if ship and ship in SHIP_TRIP_FISHSET_MULTI_MAIN and trip_fish_set:
        for required_set, main_set in SHIP_TRIP_FISHSET_MULTI_MAIN[ship]:
            if required_set.issubset(trip_fish_set):
                return main_set
    return frozenset()


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


def _classify_main_sub(fish_raw, tsuri_mono, ship="", kanso_raw="", trip_fish_set=None):
    """メイン/サブを判定。

    2026/05/16 拡張: 複合主役船ルール（SHIP_KANSO_MULTI_MAIN / SHIP_TRIP_FISHSET_MULTI_MAIN）
    が該当する便のみ複数メインを許容。それ以外は既存ロジック維持。

    引数:
        fish_raw: 当該レコードの魚種名（生）
        tsuri_mono: trip 単位の正規化釣り物（_extract_tsuri_mono 由来）
        ship: 船宿名（複合主役ルール参照用・後方互換のためデフォルト ""）
        kanso_raw: 感想生テキスト（先頭から船種名抽出）
        trip_fish_set: 同一trip 内の fish_raw 集合（複合主役ルール用）
    """
    # 複合主役船の限定許容（マダイ五目のアジ等は通常ロジックに落ちる）
    multi_mains = _get_multi_main(ship, kanso_raw, trip_fish_set)
    if multi_mains:
        fish_norm = normalize_tsuri_mono(fish_raw, ship)
        return "メイン" if fish_norm in multi_mains else "サブ"
    # 既存ロジック（変更なし）
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
    T31 (2026/05/12): kanso_raw からの抽出力強化（ササ濁り・コーヒー・クリア等の語彙を追加）。
    """
    # (パターン, 正規化後の値) — 長いものを先に
    _MAP = [
        ("青潮",       "青潮"),
        ("赤潮",       "赤潮"),
        ("コーヒー色", "濁り"),
        ("味噌汁色",   "濁り"),
        ("ササ濁り",   "やや濁り"),
        ("ささ濁り",   "やや濁り"),
        ("笹濁り",     "やや濁り"),
        ("クリア",     "澄み"),
        ("ブルー",     "澄み"),
        ("黒潮の影響", "澄み"),
        ("澄み気味",   "やや澄み"),
        ("やや澄",     "やや澄み"),
        ("澄む",       "澄み"),
        ("澄み",       "澄み"),
        ("澄んで",     "澄み"),
        ("濁り気味",   "やや濁り"),
        ("やや濁",     "やや濁り"),
        ("薄濁",       "薄濁り"),
        ("濁る",       "濁り"),
        ("濁り",       "濁り"),
        ("普通",       "普通"),
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
    """潮況キーワードを抽出（カンマ区切り）。二枚潮・潮流れずは予測の重要特徴量。
    T31 (2026/05/12): 中潮・若潮・長潮・潮替わり・潮効いて・潮悪し・澄み潮等のパターン追加。
    """
    patterns = [
        # 二枚潮系
        "二枚潮",
        # 潮の速さ・流れ
        "潮流れず", "潮流れない", "潮が流れず", "潮が流れない",
        "潮が速", "潮速い", "潮速く", "速潮",
        "潮流れよく", "潮がよく", "潮効いて", "潮が効いて", "潮よく効いて",
        "潮が緩", "潮緩", "潮ゆるく",
        "潮止まり", "潮止まって", "潮動かず", "潮動かない",
        "潮悪し", "潮が悪", "潮悪い",
        # 潮の向き
        "上げ潮", "下げ潮", "上り潮", "下り潮",
        "澄み潮", "濁り潮", "潮替わり", "潮変わり",
        # 潮回り（既存）
        "大潮", "中潮", "小潮", "長潮", "若潮",
    ]
    found = [p for p in patterns if p in comment]
    return ",".join(found) if found else ""


def _extract_wave_info(comment):
    """波・うねり情報を抽出。
    T31 (2026/05/12): ベタ凪・凪ぎ・大シケ・うねり強等のパターン追加。
    """
    comment = comment.translate(Z2H)
    parts = []
    m = re.search(r'波\s*(\d+(?:\.\d+)?)\s*m', comment)
    if m:
        parts.append(f"波{m.group(1)}m")
    # 長い表現を先にマッチ（短いものに飲まれないよう）
    for word in ["ベタ凪", "ベタなぎ", "ベタナギ",
                 "うねり強", "ウネリ強", "うねりあり", "ウネリあり",
                 "大シケ", "大しけ", "シケ気味", "しけ気味",
                 "凪ぎ", "なぎ", "凪",
                 "うねり", "ウネリ",
                 "大波", "高波", "波が高", "波高",
                 "穏やか", "おだやか"]:
        if word in comment and word not in ",".join(parts):
            parts.append(word)
            break
    return ",".join(parts) if parts else ""


def _extract_weather(comment):
    """天気キーワードを抽出（カンマ区切り）。
    T31 (2026/05/12): 猛暑・寒波・曇天・薄曇り等のパターン追加。
    """
    keywords = [
        # イベント天気（重複回避: 包含関係のあるパターンは「長い形」のみ・「台風後」を含む文字列で「台風」が重複しないように単独語は省略）
        "台風後", "嵐後", "豪雨後", "雨後",
        "嵐", "雷",
        # 降水
        "豪雨", "小雨", "霧雨", "雨", "霧",
        # 晴れ・曇り（長い順）
        "薄曇り", "曇天", "曇り",
        "快晴", "晴れ",
        # 気温・気象
        "猛暑", "酷暑", "寒波", "冷え込",
    ]
    # 重複防止: 例「台風後」検出時に「台風」もマッチ → 既出パターンと包含関係チェック
    found = []
    for k in keywords:
        if k in comment and not any(prev in k or k in prev for prev in found):
            found.append(k)
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
    # 2026/05/16: データソース識別（釣りビジョン / chowari/ひろの丸 / 直サイト/gyo 等）
    "source",
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
                    "source":         r.get("source") or "釣りビジョン",
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
            # 2026/05/16: 複合主役船ルール用に ship / kanso / trip_fish_set を渡す
            _trip_fish_set = frozenset(x.get("fish_raw", "") for x in same_trip if x.get("fish_raw"))
            main_sub   = _classify_main_sub(
                r.get("fish_raw", ""), tsuri_norm,
                ship=r.get("ship", ""), kanso_raw=comment,
                trip_fish_set=_trip_fish_set,
            )

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
            # T31 (2026/05/12): 相対ポイント表記（南沖・近場・西沖等）を {port_short}+{方向} に正規化
            if places and places[0]:
                places[0] = _normalize_relative_point(places[0], r.get("area") or "")

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

            # サブ行の tsuri_mono 修正（T40 2026/05/30）:
            # tsuri_norm は便ターゲット（trip-level）だが、サブ釣果行は
            # fish_raw が実際の魚種であるため normalize_tsuri_mono(fish_raw) で上書きする。
            # main_sub=='メイン' 行（五目便含む）は一切変更しない。
            # norm が空（地名ノイズ等で正規化不能）の場合は便ターゲットを維持する。
            _csv_tsuri_norm = tsuri_norm
            if main_sub == "サブ":
                _norm_from_fish = normalize_tsuri_mono(r.get("fish_raw") or "", r["ship"])
                if _norm_from_fish:
                    _csv_tsuri_norm = _norm_from_fish

            rows.append({
                "ship":           r["ship"],
                "area":           r["area"],
                "date":           r["date"],
                "trip_no":        r.get("trip_no", ""),
                "is_cancellation": 0,
                "tsuri_mono_raw": tsuri_raw or "",
                "tsuri_mono":     _csv_tsuri_norm,
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
                "source":         r.get("source") or "釣りビジョン",
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

def append_to_catches_raw(catches):
    """T31 リカバリ (2026/05/12): in-memory catches を catches_raw.json にも追記。

    背景: 過去 save_daily_csv() は data/V2/*.csv にのみ追記し、catches_raw.json は
    手動 history_crawl_* 経由でしか更新されない設計だった。このため
    `--export-csv` で catches_raw.json から CSV を全再生成すると、save_daily_csv
    で追記されていた最新分（数百件単位）が wipe される regression が再発した。

    対策: 毎日のクロール時に catches_raw.json にも同期追記することで、
    catches_raw.json が常に最新化され、--export-csv で上書きされても data 消失を防ぐ。

    dedup キー: (ship, area, date, fish_raw, trip_no) — history_crawl_single.py と同じ
    """
    RAW_PATH = os.path.join(os.path.dirname(__file__), "crawl", "catches_raw.json")
    if not os.path.exists(RAW_PATH):
        print(f"  catches_raw.json が存在しないためスキップ: {RAW_PATH}")
        return 0
    try:
        with open(RAW_PATH, encoding="utf-8") as f:
            all_records = json.load(f)
    except Exception as e:
        print(f"  catches_raw.json 読込失敗・スキップ: {e}")
        return 0
    existing_keys = {
        (r.get("ship", ""), r.get("area", ""), r.get("date", ""),
         r.get("fish_raw", ""), str(r.get("trip_no", "")))
        for r in all_records if r.get("date")
    }
    added = []
    for c in catches:
        if not c.get("date") or not c.get("ship"):
            continue
        if c.get("is_cancellation"):
            continue
        if not c.get("fish_raw"):
            continue
        key = (c["ship"], c.get("area", ""), c["date"],
               c.get("fish_raw", ""), str(c.get("trip_no", "")))
        if key in existing_keys:
            continue
        existing_keys.add(key)
        # V2 形式に変換（history_crawl_single.to_v2_record と同パターン）
        # 2026/05/16: source 列追加。catches_raw.json には A1 釣りビジョン経由分のみ書く想定。
        added.append({
            "ship":            c.get("ship", ""),
            "area":            c.get("area", ""),
            "date":            c.get("date", ""),
            "trip_no":         c.get("trip_no"),
            "is_cancellation": c.get("is_cancellation", False),
            "reason_text":     c.get("reason_text", ""),
            "fish_raw":        c.get("fish_raw", ""),
            "count_raw":       c.get("count_raw", ""),
            "size_raw":        c.get("size_raw", ""),
            "weight_raw":      c.get("weight_raw", ""),
            "tokki_raw":       c.get("tokki_raw", ""),
            "point_raw":       c.get("point_raw", ""),
            "kanso_raw":       c.get("kanso_raw") or c.get("trip_comment", ""),
            "suion_raw":       c.get("suion_raw"),
            "suishoku_raw":    c.get("suishoku_raw"),
            "source":          c.get("source") or "釣りビジョン",
        })
    if added:
        all_records.extend(added)
        all_records.sort(key=lambda r: (r.get("ship", ""), r.get("date", ""), r.get("trip_no") or 0))
        with open(RAW_PATH, "w", encoding="utf-8") as f:
            json.dump(all_records, f, ensure_ascii=False, indent=2)
    return len(added)


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

        # 2026/05/16: 複合主役船ルール用に trip 単位の魚種セットを事前構築
        _trip_idx = defaultdict(set)
        for c in month_catches:
            if c.get("fish_raw"):
                _trip_idx[(c["ship"], c["date"], c.get("trip_no"))].add(c["fish_raw"])

        new_rows = []
        for c in month_catches:
            fish_raw = c.get("fish_raw", "")
            key = (c["ship"], c["area"], c["date"], fish_raw)
            if key in existing_keys:
                continue
            existing_keys.add(key)

            # V2 正規化
            # 日次経路は tsuri_norm が行ごとの実魚種なのでサブ汚染なし。便ターゲット汚染は export_csv_from_raw 経路のみで対処。
            tsuri_norm = normalize_tsuri_mono(fish_raw, c["ship"])
            _trip_fish_set = frozenset(_trip_idx.get((c["ship"], c["date"], c.get("trip_no")), set()))
            main_sub   = _classify_main_sub(
                fish_raw, tsuri_norm,
                ship=c["ship"], kanso_raw=c.get("kanso_raw", "") or "",
                trip_fish_set=_trip_fish_set,
            )
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
nav.gnav a .nav-new{display:inline-block;background:var(--cta);color:#fff;font-size:9px;font-weight:700;padding:1px 5px;border-radius:8px;margin-left:5px;vertical-align:middle;letter-spacing:.04em}
nav.gnav a:hover .nav-new,nav.gnav a.on .nav-new{background:#fff;color:var(--cta)}
.bn a.prem{color:var(--prem)}
.st{font-size:15px;font-weight:700;color:var(--accent);padding:18px 0 8px;border-bottom:2px solid var(--accent);margin-bottom:12px}
.ship-hero{background:linear-gradient(135deg,var(--accent),var(--accent2));color:#fff;padding:20px 14px;text-align:center}
.ship-hero h1{font-size:24px;font-weight:800;line-height:1.3;margin:0}
.ship-hero .sh-name{display:block}
.ship-hero .sh-loc{display:block;font-size:15px;font-weight:400;color:rgba(255,255,255,.75);margin-top:2px}
.ship-hero .sh-main-fish{font-size:12px;color:rgba(255,255,255,.6);margin-top:6px}
.ship-hero .sh-badges{display:flex;justify-content:center;gap:6px;margin-top:10px;flex-wrap:wrap}
.ship-hero .sh-badge{font-size:10px;padding:3px 8px;background:rgba(255,255,255,.15);border-radius:10px;color:#fff}
.ship-hero .sh-overall{font-size:11px;color:rgba(255,255,255,.6);margin-top:8px}
.bread{font-size:11px;color:var(--muted);padding:10px 0;line-height:1.6}.bread a{color:var(--sub)}.bread .bread-sep{white-space:nowrap;display:inline-block;padding:0 4px;color:var(--muted)}
.ad-slot{background:#f0f0f0;border:1px dashed #ccc;border-radius:var(--r);padding:20px;text-align:center;margin:12px 0;font-size:11px;color:#999}
.info-box{background:var(--card);border:1px solid var(--border);border-radius:var(--r);padding:14px;margin-bottom:16px;font-size:12px;color:var(--sub);line-height:1.8}
.info-box strong{color:var(--text)}
.info-box .info-row{display:flex;gap:8px;padding:4px 0;border-bottom:1px solid var(--bg)}
.info-box .info-row:last-child{border-bottom:none}
.info-box .info-label{flex:0 0 100px;color:var(--muted);font-weight:600}
.info-box .info-val{flex:1}
.fish-section{background:var(--card);border:1px solid var(--border);border-radius:var(--r);padding:14px;margin-bottom:12px}
.fish-section h3{font-size:13px;font-weight:700;color:var(--accent);margin-bottom:8px;display:flex;justify-content:space-between;align-items:center}
.fish-section h3 .h-fish{display:inline-flex;align-items:center;gap:6px}
.fish-section h3 .fs-emoji{vertical-align:middle}
.fish-section h3 .h-range{color:var(--cta);font-size:15px}
.chart-bars{display:flex;align-items:flex-end;gap:3px;height:40px}
.chart-bars .cb{flex:1;background:var(--cta);border-radius:2px 2px 0 0;opacity:.7;min-width:10px}
.chart-bars .cb.weekend{opacity:.8;background:var(--weekend)}
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
.ship-hero h1{font-size:24px;font-weight:800;line-height:1.3;margin:0}
.ship-hero .sh-name{display:block}
.ship-hero .sh-loc{display:block;font-size:15px;font-weight:400;color:rgba(255,255,255,.75);margin-top:2px}
.ship-hero .sh-main-fish{font-size:12px;color:rgba(255,255,255,.6);margin-top:6px}
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
.fish-section h3 .h-fish{display:inline-flex;align-items:center;gap:6px}
.fish-section h3 .fs-emoji{vertical-align:middle}
.fish-section h3 .h-range{color:var(--cta);font-size:15px}
.chart-bars{display:flex;align-items:flex-end;gap:3px;height:40px}
.chart-bars .cb{flex:1;background:var(--cta);border-radius:2px 2px 0 0;opacity:.7;min-width:10px}
.chart-bars .cb.weekend{opacity:.8;background:var(--weekend)}
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
.contact-cta a{display:inline-block;padding:10px 24px;background:var(--cta);color:#fff;border-radius:20px;font-weight:700;font-size:13px;margin:4px}
.monthly-archive{background:var(--card);border:1px solid var(--border);border-radius:var(--r);padding:16px;margin-bottom:16px}
.monthly-archive>h3{font-size:14px;font-weight:700;color:var(--accent);margin-bottom:4px;display:flex;align-items:center;gap:6px}
.monthly-archive .ma-sub{font-size:11px;color:var(--muted);margin-bottom:14px}
.ma-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:10px}
.ma-card{background:var(--bg);border-radius:8px;padding:12px;border-top:3px solid var(--accent)}
.ma-card.recent{border-top-color:var(--cta);background:#fff;box-shadow:0 1px 3px rgba(0,0,0,.05)}
.ma-head{display:flex;justify-content:space-between;align-items:baseline;margin-bottom:8px}
.ma-head .ma-month{font-size:14px;font-weight:800;color:var(--accent)}
.ma-head .ma-rate{font-size:10px;color:var(--muted)}
.ma-head .ma-rate strong{color:var(--pos);font-weight:700}
.ma-trips{font-size:11px;color:var(--sub);margin-bottom:8px}
.ma-fish-list{font-size:12px;line-height:1.6;list-style:none;padding:0}
.ma-fish-list .mfl-row{display:flex;justify-content:space-between;gap:6px;padding:4px 0;border-bottom:1px dotted var(--border)}
.ma-fish-list .mfl-row:last-child{border-bottom:none}
.ma-fish-list .mfl-fish{font-weight:700;color:var(--accent);flex:0 0 auto}
.ma-fish-list .mfl-stat{font-size:11px;color:var(--sub);text-align:right}
.ma-fish-list .mfl-stat .mfl-cnt{color:var(--cta);font-weight:700}
.ma-collapse{margin-top:12px;border-top:1px dashed var(--border);padding-top:12px}
.ma-collapse summary{cursor:pointer;font-size:12px;color:var(--accent);font-weight:700;padding:10px 14px;background:var(--bg);border-radius:6px;list-style:none;user-select:none;display:flex;align-items:center;justify-content:center;gap:8px;transition:background .2s,color .2s}
.ma-collapse summary::-webkit-details-marker{display:none}
.ma-collapse summary::before{content:"\\25B6";font-size:9px;transition:transform .2s}
.ma-collapse[open] summary::before{transform:rotate(90deg)}
.ma-collapse summary:hover{background:var(--accent);color:#fff}
.ma-collapse[open] .ma-grid{margin-top:12px}
.ma-archive-links{margin-top:14px;padding-top:12px;border-top:1px solid var(--border);font-size:11px;color:var(--muted)}
.ma-archive-links a{display:inline-block;padding:3px 8px;background:var(--bg);color:var(--accent);border-radius:10px;text-decoration:none;margin:2px;font-size:11px}
.ma-archive-links a:hover{background:var(--accent);color:#fff}
/* J-B/C/D/E 統合実装 (2026/05/23) */
.sh-auto-badges{display:flex;justify-content:center;gap:6px;margin-top:8px;flex-wrap:wrap;padding-top:8px;border-top:1px dashed rgba(255,255,255,.15)}
.sub-label{font-size:10px;color:rgba(255,255,255,.55);margin-top:6px;letter-spacing:.5px}
.sh-ab{font-size:10px;height:22px;line-height:22px;padding:0 10px;border-radius:11px;color:#fff;font-weight:700;letter-spacing:.3px;display:inline-flex;align-items:center;gap:4px;white-space:nowrap}
.sh-ab.spec  {background:linear-gradient(135deg,#e85d04,#d04e00);order:1}
.sh-ab.rate  {background:linear-gradient(135deg,#1a9d56,#127a42);order:2}
.sh-ab.rank  {background:linear-gradient(135deg,#f4d03f,#dab500);color:#5a4500;order:3}
.sh-ab.vol   {background:linear-gradient(135deg,#5a8db8,#3d6e94);order:4}
.sh-ab.season{background:linear-gradient(135deg,#a070d0,#7c52a8);order:5}
.sh-ab .sh-ab-icon{font-size:11px;line-height:1}
.sh-ab .sh-ab-fish-img{width:14px;height:14px;border-radius:50%;background:rgba(255,255,255,.2);object-fit:contain;flex-shrink:0}
.sh-ab.rank .sh-ab-fish-img{background:rgba(90,69,0,.15)}
.sh-ab .sh-ab-sub{font-size:9px;opacity:.85;font-weight:600;padding-left:4px;margin-left:2px;border-left:1px solid rgba(255,255,255,.4)}
.sh-ab.rank .sh-ab-sub{border-left-color:rgba(90,69,0,.3)}
/* B 年間サマリー + B+ 船宿特徴文 */
.yearly-summary{background:var(--card);border:1px solid var(--border);border-top:4px solid var(--accent);box-shadow:0 1px 3px rgba(0,0,0,.04);border-radius:var(--r);padding:14px 16px 12px;margin-bottom:16px;position:relative}
.yearly-summary .ys-label{position:absolute;top:-10px;left:14px;background:var(--accent);color:#fff;font-size:10px;font-weight:700;padding:3px 10px;border-radius:12px;letter-spacing:.5px}
.yearly-summary .ys-period{font-size:11px;color:var(--muted);margin-bottom:12px;margin-top:4px}
.ys-portrait{background:linear-gradient(135deg,#fff8e1,#fff);border-left:3px solid var(--cta);padding:12px 14px;border-radius:6px;margin-bottom:14px;font-size:13px;line-height:1.8;color:var(--text)}
.ys-portrait .ysp-label{display:inline-block;font-size:10px;color:#fff;background:var(--cta);padding:2px 8px;border-radius:10px;font-weight:700;margin-bottom:8px;letter-spacing:.3px}
.ys-portrait p{margin:0 0 6px 0}
.ys-portrait p:last-child{margin-bottom:0}
.ys-portrait strong{color:var(--accent);background:rgba(232,93,4,.08);padding:0 3px;border-radius:3px;font-weight:700}
.ys-kpi-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-bottom:14px;padding-bottom:12px;border-bottom:1px dashed var(--border)}
.ys-kpi{text-align:center;padding:8px 4px;background:var(--bg);border-radius:8px}
.ys-kpi .ysk-n{font-size:22px;font-weight:800;color:var(--accent);line-height:1}
.ys-kpi .ysk-n.cta{color:var(--cta)}
.ys-kpi .ysk-l{font-size:10px;color:var(--muted);margin-top:4px}
.ys-kpi .ysk-sub{font-size:10px;color:var(--sub);margin-top:2px}
.ys-section{margin-bottom:12px}
.ys-section:last-child{margin-bottom:0}
.ys-section h4{font-size:12px;font-weight:700;color:var(--accent);margin-bottom:8px;display:flex;align-items:center;gap:5px}
.ys-top-fish{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}
.ys-tf-card{background:var(--bg);border-radius:8px;padding:10px 8px;text-align:center;border-top:3px solid var(--cta);position:relative}
.ys-tf-card.rank1{border-top-color:#f4d03f;background:linear-gradient(180deg,#fffaeb,#fff8e1)}
.ys-tf-card.rank2{border-top-color:#a0a8b4;background:#f7f7f9}
.ys-tf-card.rank3{border-top-color:#c8a878;background:#fbf6ef}
.ys-tf-medal{position:absolute;top:4px;left:6px;font-size:16px;line-height:1}
.ys-tf-img{width:44px;height:44px;display:block;margin:4px auto 6px}
.ys-tf-head{display:flex;align-items:baseline;justify-content:center;gap:6px;margin-bottom:4px}
.ys-tf-name{font-size:13px;font-weight:800;color:var(--accent)}
.ys-tf-trips{font-size:12px;color:var(--cta);font-weight:700}
.ys-tf-stats{margin-top:6px;padding-top:6px;border-top:1px dashed var(--border);font-size:10px;color:var(--sub);line-height:1.6}
.ys-tf-stats .ystf-row{display:block}
.ys-tf-stats strong{color:var(--accent);font-weight:700}
.ys-tf-stats .ystf-max{color:var(--cta);font-weight:700}
/* C 季節別主力魚種 */
.seasonal-fish{background:var(--card);border:1px solid var(--border);border-top:4px solid var(--accent);box-shadow:0 1px 3px rgba(0,0,0,.04);border-radius:var(--r);padding:14px 16px 12px;margin-bottom:16px;position:relative}
.sf-label{position:absolute;top:-10px;left:14px;background:var(--accent);color:#fff;font-size:10px;font-weight:700;padding:3px 10px;border-radius:12px;letter-spacing:.5px}
.sf-subtitle{font-size:11px;color:var(--muted);margin-bottom:12px;margin-top:4px}
.sf-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:10px}
.sf-card{background:var(--bg);border-radius:8px;padding:10px;border-left:3px solid var(--accent)}
.sf-card.spring{border-left-color:#e8a3c7;background:linear-gradient(180deg,#fef0f6,#fff)}
.sf-card.summer{border-left-color:#4dc3e6;background:linear-gradient(180deg,#e8f6fc,#fff)}
.sf-card.autumn{border-left-color:#e08c3f;background:linear-gradient(180deg,#fef0e3,#fff)}
.sf-card.winter{border-left-color:#5a8db8;background:linear-gradient(180deg,#eaf2f8,#fff)}
.sf-head{display:flex;align-items:center;gap:6px;margin-bottom:8px;padding-bottom:6px;border-bottom:1px dashed var(--border)}
.sf-emoji-season{font-size:18px;line-height:1}
.sf-season-name{font-size:13px;font-weight:800;color:var(--accent)}
.sf-months{font-size:10px;color:var(--muted);margin-left:auto}
.sf-fish-list{list-style:none;padding:0;margin:0}
.sf-fish-row{display:flex;align-items:flex-start;gap:6px;padding:6px 0;border-bottom:1px dotted var(--border)}
.sf-fish-row:last-child{border-bottom:none}
.sf-fish-rank{flex:0 0 16px;font-size:10px;color:var(--muted);font-weight:700;text-align:center;line-height:24px}
.sf-fish-img{width:24px;height:24px;flex:0 0 24px;margin-top:2px}
.sf-fish-body{flex:1;min-width:0}
.sf-fish-head{display:flex;align-items:baseline;gap:6px}
.sf-fish-name{font-size:12px;font-weight:700;color:var(--accent)}
.sf-fish-trips{font-size:11px;color:var(--cta);font-weight:700}
.sf-fish-stats{font-size:10px;color:var(--sub);line-height:1.5;margin-top:2px}
.sf-fish-stats strong{color:var(--accent);font-weight:700}
.sf-fish-stats .sff-max{color:var(--cta);font-weight:700}
/* D 大物実績ランキング */
.trophy-rank{background:linear-gradient(135deg,#fffaeb,#fff);border:1px solid var(--border);border-top:4px solid #f4d03f;box-shadow:0 1px 3px rgba(0,0,0,.04);border-radius:var(--r);padding:14px 16px 12px;margin-bottom:16px;position:relative}
.tr-label{position:absolute;top:-10px;left:14px;background:#f4d03f;color:#5a4500;font-size:10px;font-weight:700;padding:3px 10px;border-radius:12px;letter-spacing:.5px}
.tr-subtitle{font-size:11px;color:var(--muted);margin-bottom:12px;margin-top:4px}
.tr-list{list-style:none;padding:0;margin:0}
.tr-row{display:flex;align-items:center;gap:8px;padding:8px 6px;border-bottom:1px dotted var(--border)}
.tr-row:last-child{border-bottom:none}
.tr-row.r1{background:linear-gradient(90deg,#fffaeb,transparent);border-left:3px solid #f4d03f;padding-left:8px;border-radius:4px 0 0 4px}
.tr-row.r2{background:linear-gradient(90deg,#f7f7f9,transparent);border-left:3px solid #a0a8b4;padding-left:8px;border-radius:4px 0 0 4px}
.tr-row.r3{background:linear-gradient(90deg,#fbf6ef,transparent);border-left:3px solid #c8a878;padding-left:8px;border-radius:4px 0 0 4px}
.tr-medal{flex:0 0 28px;font-size:18px;text-align:center;line-height:1}
.tr-rank{flex:0 0 28px;font-size:11px;text-align:center;color:var(--muted);font-weight:700;line-height:1}
.tr-img{width:36px;height:36px;flex:0 0 36px}
.tr-body{flex:1;min-width:0}
.tr-fish{font-size:14px;font-weight:800;color:var(--accent)}
.tr-rank-badge{font-size:11px;color:var(--accent);font-weight:700;background:#fff2dc;padding:1px 6px;border-radius:8px;margin-left:4px}
.tr-rank-badge.low{font-size:10px;color:var(--sub);background:#eef1f5}
.tr-date{font-size:11px;color:var(--muted);margin-left:6px}
.tr-val{font-size:15px;font-weight:800;color:var(--cta);flex:0 0 auto}
.weekly-report{background:#fff;border-top:4px solid var(--cta);border-left:1px solid var(--border);border-right:1px solid var(--border);border-bottom:1px solid var(--border);box-shadow:0 1px 3px rgba(0,0,0,.04);border-radius:var(--r);padding:16px 18px 14px;margin:14px 0;position:relative}
.weekly-report .wr-label{position:absolute;top:-10px;left:14px;background:var(--cta);color:#fff;font-size:10px;font-weight:700;padding:3px 10px;border-radius:12px;letter-spacing:.5px}
.weekly-report .wr-period{font-size:11px;color:var(--muted);margin-bottom:12px;margin-top:4px}
.wr-kpi-row{display:flex;align-items:baseline;gap:12px;background:rgba(255,255,255,.7);border-radius:8px;padding:10px 12px;margin-bottom:12px;border:1px solid rgba(232,93,4,.15);flex-wrap:wrap}
.wr-kpi-row .wkr-label{font-size:11px;color:var(--muted)}
.wr-kpi-row .wkr-main{font-size:20px;font-weight:800;color:var(--cta)}
.wr-kpi-row .wkr-diff{font-size:11px;padding:2px 8px;border-radius:10px;background:rgba(26,157,86,.12);color:var(--pos);font-weight:700}
.wr-kpi-row .wkr-diff.neg{background:rgba(212,51,51,.12);color:var(--neg)}
.wr-kpi-row .wkr-sub{font-size:11px;color:var(--sub);margin-left:auto}
.wr-section{margin-bottom:12px;padding-bottom:10px;border-bottom:1px dashed var(--border)}
.wr-section:last-child{border-bottom:none;padding-bottom:0}
.wr-section h4{font-size:12px;font-weight:700;color:var(--accent);margin-bottom:6px;display:flex;align-items:center;gap:5px}
.wr-fish-list{list-style:none;padding:0;font-size:12px}
.wr-fish-list li{padding:4px 0;display:flex;flex-wrap:wrap;gap:6px;align-items:baseline}
.wr-fish-list .wfl-fish{font-weight:700;color:var(--accent)}
.wr-fish-list .wfl-fish-img{vertical-align:middle;margin-right:3px;border-radius:50%}
.wr-trophy .wrt-fish-img{vertical-align:middle;margin-right:3px;border-radius:50%;background:rgba(133,100,4,.15)}
.wr-fish-list .wfl-count{color:var(--cta);font-weight:700}
.wr-fish-list .wfl-diff{font-size:10px;padding:1px 6px;border-radius:8px;background:rgba(26,157,86,.12);color:var(--pos);font-weight:700}
.wr-fish-list .wfl-diff.neg{background:rgba(212,51,51,.12);color:var(--neg)}
.wr-fish-list .wfl-detail{font-size:11px;color:var(--sub);flex:1 1 100%;padding-left:8px}
.wr-trophy{display:inline-block;padding:4px 10px;border-radius:14px;background:linear-gradient(135deg,#fff3cd,#fff8e1);border:1px solid #f4d03f;font-size:12px;color:#856404;font-weight:700}
.wr-trophy .wrt-date{font-size:10px;color:#7a6500;font-weight:600;margin-left:4px}
.wr-next-week{font-size:12px;color:var(--text);line-height:1.7}
.wr-next-week .wnw-row{display:flex;gap:6px;align-items:baseline;margin-bottom:4px;flex-wrap:wrap}
.wr-next-week .wnw-tag{flex:0 0 auto;font-size:10px;padding:2px 8px;border-radius:10px;background:rgba(13,43,74,.08);color:var(--accent);font-weight:700}
.wr-next-week .wnw-text{font-size:12px;color:var(--sub);flex:1}
.wr-next-week .wnw-text strong{color:var(--accent);background:rgba(232,93,4,.1);padding:1px 4px;border-radius:3px}
.wr-yoy{display:grid;grid-template-columns:1fr 1fr;gap:8px;font-size:11px}
.wr-yoy .wy-card{padding:8px 10px;background:var(--bg);border-radius:6px}
.wr-yoy .wy-year{font-size:10px;color:var(--muted);margin-bottom:2px}
.wr-yoy .wy-val{font-size:13px;font-weight:700;color:var(--accent)}
.wr-yoy .wy-val .wyv-unit{font-size:11px;color:var(--sub);font-weight:400}
.wr-yoy .wy-card.now{background:#fff;border:1px solid var(--cta)}
.wr-yoy .wy-card.now .wy-val{color:var(--cta)}
.weekly-report .wr-stats{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-top:12px;padding-top:10px;border-top:1px dashed var(--border)}
.weekly-report .wr-stat{text-align:center;padding:6px 4px}
.weekly-report .wr-stat .wrs-n{font-size:18px;font-weight:800;color:var(--cta);line-height:1}
.weekly-report .wr-stat .wrs-l{font-size:10px;color:var(--muted);margin-top:4px}"""


# ============================================================
# F2 (2026/05/22): 魚種別シーズン文マップ
# 主要 16 魚種 × 12 月の短文 (20-30字)。
# 船宿の主要魚種に合わせて「来週の見どころ」セクションで表示する。
# 主要外の魚種は _fish_season_phrase_auto() で SEASON_DATA から自動生成。
# ============================================================
_FISH_SEASON_PHRASE = {
    "マダイ": {
        1: "深場狙いで寒鯛の良型期待",
        2: "産卵前の好機・型揃う",
        3: "ノッコミ開幕・3〜5kg良型出始め",
        4: "ノッコミ前期・数型ともに最盛期",
        5: "ノッコミ後期・産卵明けの荒食い最終週",
        6: "乗っ込み後期・深場狙いで型物",
        7: "高水温期・深場と早朝勝負",
        8: "夏枯れ・早朝時合いを逃すな",
        9: "秋型シーズン入り・活性上向き",
        10: "秋の数釣り好機・型も期待",
        11: "深場中心・型物の良型期待",
        12: "寒鯛の良型シーズン突入",
    },
    "アジ": {
        1: "寒アジ絶好調・身が締まる最高期",
        2: "寒の底・良型揃いで数釣り継続",
        3: "春の旬ピーク開幕・釣果上向き",
        4: "春の数釣り全盛期",
        5: "数釣り絶好調・束釣りも現実的",
        6: "夏アジ・中型混じる好シーズン",
        7: "夏の数釣り好調・早朝便おすすめ",
        8: "中アジ盛期・型狙いに最適",
        9: "秋の荒食い・束釣り炸裂",
        10: "秋の数型ともに絶好調",
        11: "良型混じり・脂のりが向上",
        12: "寒アジ開幕・脂のった良型シーズン",
    },
    "タチウオ": {
        1: "シーズン終盤・大型のドラゴン狙い",
        2: "オフシーズン・解禁待ち",
        3: "オフシーズン・解禁待ち",
        4: "解禁前・準備期",
        5: "東京湾解禁・シーズン開幕",
        6: "本格シーズン・数も型も期待",
        7: "最盛期・指4本超えドラゴン狙い",
        8: "最盛期継続・夏のメインターゲット",
        9: "秋型シーズン・大型のチャンス",
        10: "秋の大型シーズン・指5本も",
        11: "シーズン終盤・型狙い最後の好機",
        12: "終盤・寒タチの大型期待",
    },
    "ヒラメ": {
        1: "外房乗っ込みシーズン真っ只中",
        2: "乗っ込み継続・大型のチャンス",
        3: "シーズン終盤・最後の型狙い",
        4: "オフ移行期・浅場で散発",
        5: "オフシーズン・他魚種狙い推奨",
        6: "オフシーズン継続",
        7: "オフシーズン継続",
        8: "オフシーズン継続",
        9: "シーズン開幕・浅場の活性UP",
        10: "秋の数型シーズン突入",
        11: "本格シーズン・乗っ込み前の荒食い",
        12: "乗っ込み開幕・型物期待",
    },
    "カワハギ": {
        1: "肝パン継続・脂ノリ最高",
        2: "終盤・型物の良型期待",
        3: "シーズン終盤・最後の型狙い",
        4: "オフ移行期・散発的",
        5: "オフシーズン",
        6: "オフシーズン",
        7: "オフシーズン",
        8: "シーズン開幕・浅場で顔",
        9: "本格化・数釣りシーズン入り",
        10: "肝が肥え始める好シーズン",
        11: "肝パンピーク・年間ベストタイミング",
        12: "肝パン継続・刺身/肝和え絶品",
    },
    "シロギス": {
        1: "オフシーズン・深場で散発",
        2: "オフシーズン継続",
        3: "暖かい日は浅場で顔・準備期",
        4: "シーズン開幕・浅場で数釣り",
        5: "本格シーズン突入・束釣り狙い",
        6: "数釣り最盛期・浅場で良釣果",
        7: "夏の浅場釣り好調継続",
        8: "夏の数釣り安定・型も出る",
        9: "シーズン後半・型狙いに切替",
        10: "良型シーズン・型釣り楽しい",
        11: "深場移行期・終盤の型物",
        12: "オフ移行期・深場で散発",
    },
    "タイ五目": {
        1: "深場の根魚混じり・寒鯛も期待",
        2: "深場メインで多彩",
        3: "春の浅場狙い・マダイ混じる",
        4: "春の盛期・五目で多彩",
        5: "ゴールデンシーズン・多種混じる",
        6: "夏入りで多種多彩",
        7: "高水温期・深場の五目",
        8: "夏型の五目・早朝勝負",
        9: "秋の活性UP・多種揃う",
        10: "秋の数型シーズン",
        11: "深場根魚混じり・型物期待",
        12: "寒の深場五目・良型シーズン",
    },
    "アマダイ": {
        1: "深場の脂ノリ最高シーズン",
        2: "良型シーズン継続",
        3: "春の浅場移行期・型狙い",
        4: "産卵前の好機・型物期待",
        5: "シーズン後半・浅場狙い",
        6: "オフ移行期・型は出る",
        7: "オフシーズン・水温高い",
        8: "オフシーズン継続",
        9: "シーズン開幕・深場の活性UP",
        10: "本格シーズン入り・数型期待",
        11: "良型シーズン・脂のり向上",
        12: "脂ノリ最高・寒甘鯛シーズン",
    },
    "マルイカ": {
        1: "オフシーズン",
        2: "オフシーズン",
        3: "シーズン開幕・浅場で釣れ始め",
        4: "シーズン入り・数釣り期待",
        5: "本格シーズン・数型ともに好調",
        6: "数釣りピーク・束釣りも現実",
        7: "シーズン後半・型狙い好機",
        8: "終盤・大型のチャンス",
        9: "シーズン終了間際",
        10: "オフ移行期",
        11: "オフシーズン",
        12: "オフシーズン",
    },
    "ヤリイカ": {
        1: "本格シーズン・大型の良型期待",
        2: "シーズン継続・型物狙い",
        3: "シーズン終盤・最後の好機",
        4: "オフ移行期・終盤戦",
        5: "オフシーズン",
        6: "オフシーズン",
        7: "オフシーズン",
        8: "オフシーズン",
        9: "オフシーズン",
        10: "シーズン開幕・浅場で釣れ始め",
        11: "本格シーズン入り・数型期待",
        12: "シーズン入り・大型狙い",
    },
    "スルメイカ": {
        1: "オフ・深場で散発",
        2: "オフ移行期",
        3: "オフシーズン",
        4: "シーズン入り・沖合で散発",
        5: "シーズン開幕・沖合で釣れ始め",
        6: "数釣りシーズン入り",
        7: "本格シーズン・好調期",
        8: "最盛期・数釣り炸裂",
        9: "秋の好調期継続",
        10: "シーズン終盤・最後の数釣り",
        11: "終盤・型狙い",
        12: "オフ移行期",
    },
    "マダコ": {
        1: "オフ・湾内で散発",
        2: "オフシーズン",
        3: "オフ移行期",
        4: "シーズン入り・湾内で釣れ始め",
        5: "解禁港増加・船タコシーズン入り",
        6: "本格シーズン突入",
        7: "旬ピーク・湾内活性最高",
        8: "夏のピーク継続・数型期待",
        9: "シーズン後半・良型狙い",
        10: "終盤・最後の数釣り",
        11: "終盤・型狙い",
        12: "オフ移行期",
    },
    "イサキ": {
        1: "オフ・深場で散発",
        2: "オフシーズン",
        3: "シーズン開幕の兆し・浅場移行",
        4: "シーズン入り・千葉・静岡で開幕",
        5: "本格シーズン・型釣り楽しい",
        6: "最盛期・数釣り炸裂",
        7: "数釣り好調継続",
        8: "夏の好調期・型物も",
        9: "シーズン後半・型狙い",
        10: "終盤・最後の数釣り",
        11: "オフ移行期",
        12: "オフシーズン",
    },
    "フグ": {
        1: "乗っ込み真っ最中・型揃う",
        2: "産卵前の荒食い・型物期待",
        3: "産卵期終盤・型物多い",
        4: "オフ移行期・産卵明け",
        5: "オフシーズン",
        6: "オフシーズン",
        7: "オフシーズン",
        8: "オフシーズン",
        9: "オフシーズン",
        10: "シーズン入り・活性上向き",
        11: "本格シーズン入り・関東全域好調",
        12: "数釣り・型物ともに好調",
    },
    "カサゴ": {
        1: "産卵前の荒食い・良型期待",
        2: "産卵期入り・型狙い",
        3: "シーズン継続・浅場で数釣り",
        4: "シーズン後半・型物も期待",
        5: "終盤戦・浅場で散発",
        6: "オフ移行期",
        7: "オフシーズン",
        8: "オフシーズン",
        9: "シーズン入り・活性上向き",
        10: "本格シーズン入り・数釣り好調",
        11: "数釣り好調・脂ノリ向上",
        12: "良型シーズン・寒カサゴ",
    },
    "マハタ": {
        1: "深場の高級魚・脂ノリ最高",
        2: "深場狙い継続・大型期待",
        3: "シーズン継続・型物狙い",
        4: "シーズン継続・春の活性UP",
        5: "本格シーズン・大原で良型",
        6: "夏型・深場の活性UP",
        7: "シーズン継続・型狙い",
        8: "シーズン継続",
        9: "秋型・型物のチャンス",
        10: "秋の良型シーズン",
        11: "深場の高級魚シーズン",
        12: "脂ノリ最高・寒マハタ",
    },
}


def _fish_season_phrase(fish, month):
    """魚種・月から短いシーズン文を返す。
    主要 16 魚種は _FISH_SEASON_PHRASE を参照。
    それ以外は SEASON_DATA (1〜5 スコア) から自動生成。
    取れない場合は空文字列を返す。
    """
    if not fish or not month:
        return ""
    # 主要魚種
    phrase_map = _FISH_SEASON_PHRASE.get(fish)
    if phrase_map:
        return phrase_map.get(month, "")
    # 自動生成: SEASON_DATA スコアからラベル化
    try:
        scores = SEASON_DATA.get(fish)
        if not scores or len(scores) < 12:
            return ""
        s = scores[month - 1]
        next_s = scores[month % 12]  # 翌月 (12 月 → 1 月)
        if s >= 5:
            base = "シーズンピーク"
        elif s >= 4:
            base = "好調期"
        elif s >= 3:
            base = "通常期"
        elif s >= 2:
            base = "やや低迷"
        else:
            base = "オフシーズン"
        if next_s > s:
            trend = "上向き"
        elif next_s < s:
            trend = "後半戦"
        else:
            trend = "安定"
        return f"{base}・{trend}"
    except Exception:
        return ""


def _ship_load_area_coords():
    """area_coords.json を読む（{area: {lat, lon}}）"""
    p = os.path.join("normalize", "area_coords.json")
    if not os.path.exists(p): return {}
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


# ============================================================
# F1 (2026/05/22): 月別釣果実績セクション
# 各 ship/*.html に「過去 N ヶ月の月別出船・釣果データ」カードを追加
# 直近3ヶ月のみ常時表示・4ヶ月目以降は <details> 折り畳み
# データソース: data/V2/YYYY-MM.csv 24ヶ月分蓄積済 + chowari_*.csv 同月key 合算
# SEO: 各船宿で「{船宿名} {YYYY年MM月} 釣果」ロングテール獲得・コンテンツ量 4倍
# 配置: 予約CTA 下・FAQ 上 (rev2 確定)
# ============================================================

def _ship_load_weekly_data(ship_name, today_dt):
    """直近14日分の catches を data/V2 から読んで今週/前週に分割集計。
    返り値: {
      'period_start': 'YYYY/MM/DD',
      'period_end': 'YYYY/MM/DD',
      'this_week': {trips, cancels, fish_count{}, fish_cnt{}, fish_size_max{}, fish_kg_max{}, fish_max_record{}},
      'prev_week': 同上
    }
    """
    if not ship_name:
        return None
    today = today_dt.date()
    week_start = today - timedelta(days=6)
    prev_start = today - timedelta(days=13)
    prev_end = week_start - timedelta(days=1)

    months = set()
    cur = prev_start
    while cur <= today:
        months.add(cur.strftime("%Y-%m"))
        cur += timedelta(days=1)

    this_rows = []
    prev_rows = []
    for month in months:
        for fname in (f"{month}.csv", f"chowari_{month}.csv"):
            path = os.path.join(_DATA_DIR, fname)
            if not os.path.exists(path):
                continue
            try:
                with open(path, encoding="utf-8") as fp:
                    for row in csv.DictReader(fp):
                        if row.get("ship") != ship_name:
                            continue
                        try:
                            d = datetime.strptime(row.get("date", ""), "%Y/%m/%d").date()
                        except Exception:
                            continue
                        if week_start <= d <= today:
                            this_rows.append(row)
                        elif prev_start <= d <= prev_end:
                            prev_rows.append(row)
            except Exception:
                continue

    def _summarize(rows):
        trips = 0
        cancels = 0
        fish_count = {}
        fish_cnt_sum = {}
        fish_size_max = {}
        fish_kg_max = {}
        fish_max_record = {}  # {fish: (kind, value, date)}
        for r in rows:
            if r.get("is_cancellation") == "1":
                cancels += 1
                continue
            trips += 1
            fish = (r.get("tsuri_mono") or "").strip()
            if not fish or fish in ("不明", "欠航", "NULL"):
                continue
            fish_count[fish] = fish_count.get(fish, 0) + 1
            try:
                cnt = float(r.get("cnt_avg") or 0)
                if cnt > 0:
                    fish_cnt_sum.setdefault(fish, []).append(cnt)
            except (ValueError, TypeError):
                pass
            try:
                sm = float(r.get("size_max") or 0)
                if sm > fish_size_max.get(fish, 0):
                    fish_size_max[fish] = sm
                    fish_max_record[fish] = ("size", sm, r.get("date", ""))
            except (ValueError, TypeError):
                pass
            try:
                km = float(r.get("kg_max") or 0)
                if km > fish_kg_max.get(fish, 0):
                    fish_kg_max[fish] = km
                    # kg優先 (size_max より重い情報)
                    fish_max_record[fish] = ("kg", km, r.get("date", ""))
            except (ValueError, TypeError):
                pass
        return {
            "trips": trips, "cancels": cancels,
            "fish_count": fish_count, "fish_cnt_sum": fish_cnt_sum,
            "fish_size_max": fish_size_max, "fish_kg_max": fish_kg_max,
            "fish_max_record": fish_max_record,
        }

    return {
        "period_start": week_start.strftime("%Y/%m/%d"),
        "period_end": today.strftime("%Y/%m/%d"),
        "this_week": _summarize(this_rows),
        "prev_week": _summarize(prev_rows),
    }


def _ship_load_yoy_data(ship_name, today_dt):
    """前年同月（全期間）と今年同月（1日〜today まで）の集計を返す。
    {
      'last_year_month': 'YYYY-MM',
      'last_year_fish_count': {fish: n},
      'last_year_total_trips': int,
      'this_year_fish_count': {fish: n} (1日〜today),
      'this_year_total_trips': int,
    }
    前年データが無ければ None。
    """
    if not ship_name:
        return None
    try:
        last_year_month = today_dt.replace(year=today_dt.year - 1).strftime("%Y-%m")
    except Exception:
        return None
    this_year_month = today_dt.strftime("%Y-%m")
    today_d = today_dt.date()

    last_year_fish_count = {}
    last_year_total_trips = 0
    found_last_year = False
    for fname in (f"{last_year_month}.csv", f"chowari_{last_year_month}.csv"):
        path = os.path.join(_DATA_DIR, fname)
        if not os.path.exists(path):
            continue
        found_last_year = True
        try:
            with open(path, encoding="utf-8") as fp:
                for r in csv.DictReader(fp):
                    if r.get("ship") != ship_name:
                        continue
                    if r.get("is_cancellation") == "1":
                        continue
                    last_year_total_trips += 1
                    fish = (r.get("tsuri_mono") or "").strip()
                    if fish and fish not in ("不明", "欠航", "NULL"):
                        last_year_fish_count[fish] = last_year_fish_count.get(fish, 0) + 1
        except Exception:
            continue
    if not found_last_year:
        return None

    # 今年同月 (1日〜today)
    this_year_fish_count = {}
    this_year_total_trips = 0
    for fname in (f"{this_year_month}.csv", f"chowari_{this_year_month}.csv"):
        path = os.path.join(_DATA_DIR, fname)
        if not os.path.exists(path):
            continue
        try:
            with open(path, encoding="utf-8") as fp:
                for r in csv.DictReader(fp):
                    if r.get("ship") != ship_name:
                        continue
                    try:
                        d = datetime.strptime(r.get("date", ""), "%Y/%m/%d").date()
                    except Exception:
                        continue
                    if d > today_d:
                        continue
                    if r.get("is_cancellation") == "1":
                        continue
                    this_year_total_trips += 1
                    fish = (r.get("tsuri_mono") or "").strip()
                    if fish and fish not in ("不明", "欠航", "NULL"):
                        this_year_fish_count[fish] = this_year_fish_count.get(fish, 0) + 1
        except Exception:
            continue

    return {
        "last_year_month": last_year_month,
        "last_year_fish_count": last_year_fish_count,
        "last_year_total_trips": last_year_total_trips,
        "this_year_fish_count": this_year_fish_count,
        "this_year_total_trips": this_year_total_trips,
    }


def _ship_get_next_week_spring_tides(today_dt):
    """来週 (today+1 ~ today+7) の大潮日を tide_moon.sqlite から取得。
    返り値: [(date_str 'M/D', tide_type), ...] 大潮のみ。
    """
    db_path = os.path.join("ocean", "tide_moon.sqlite")
    if not os.path.exists(db_path):
        return []
    try:
        import sqlite3
        start = (today_dt + timedelta(days=1)).strftime("%Y-%m-%d")
        end = (today_dt + timedelta(days=7)).strftime("%Y-%m-%d")
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        # スキーマ確認: 列名は date, tide_type
        cur.execute(
            "SELECT date, tide_type FROM tide_moon "
            "WHERE date BETWEEN ? AND ? AND tide_type='大潮' "
            "ORDER BY date",
            (start, end),
        )
        rows = cur.fetchall()
        conn.close()
        result = []
        for date_str, tide_type in rows:
            try:
                d = datetime.strptime(date_str, "%Y-%m-%d")
                result.append((d.strftime("%-m/%-d") if os.name != "nt" else f"{d.month}/{d.day}", tide_type))
            except Exception:
                result.append((date_str, tide_type))
        return result
    except Exception:
        return []


# ============================================================
# J-BCDE (2026/05/23): 月別キャッシュ機構 + 統合データ取得
# data/V2/ship_monthly_cache.json で全船宿の B/C/D/E データを月別キャッシュ
# 月変わりで全 ship 一括再計算・同月内は使い回し
# ============================================================

_SHIP_MONTHLY_CACHE_PATH = os.path.join(_BASE_DIR, "data", _ACTIVE_VER, "ship_monthly_cache.json")
_SHIP_MONTHLY_CACHE = None  # メモリキャッシュ (1走行内で何度も load しない)


def _ship_load_monthly_cache(today_dt):
    """月別キャッシュをロード・月変わりなら全 ship 再計算用に空 dict 返す。
    返り値: {ship_name: {yearly, portrait, seasonal, trophies, badges}, "__month__": "YYYY-MM"}
    """
    global _SHIP_MONTHLY_CACHE
    cur_month = today_dt.strftime("%Y-%m")
    if _SHIP_MONTHLY_CACHE is not None:
        if _SHIP_MONTHLY_CACHE.get("__month__") == cur_month:
            return _SHIP_MONTHLY_CACHE
    cache = {}
    if os.path.exists(_SHIP_MONTHLY_CACHE_PATH):
        try:
            with open(_SHIP_MONTHLY_CACHE_PATH, encoding="utf-8") as f:
                cache = json.load(f)
        except Exception:
            cache = {}
    if cache.get("__month__") != cur_month:
        # 月変わり → 空 cache (要再計算)
        cache = {"__month__": cur_month}
    _SHIP_MONTHLY_CACHE = cache
    return cache


def _ship_save_monthly_cache():
    """メモリキャッシュをディスクに保存"""
    global _SHIP_MONTHLY_CACHE
    if _SHIP_MONTHLY_CACHE is None:
        return
    try:
        os.makedirs(os.path.dirname(_SHIP_MONTHLY_CACHE_PATH), exist_ok=True)
        with open(_SHIP_MONTHLY_CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(_SHIP_MONTHLY_CACHE, f, ensure_ascii=False)
    except Exception as e:
        print(f"[ship-cache-save] err: {e}")


# 大物実績 cross-ship ranking キャッシュ (全 ship で1回計算・全 ship 共有)
_SHIP_CROSS_RANK = None


def _ship_compute_cross_ship_rankings():
    """全 ship × 全魚種の最大 kg / 最大 cm ランキングを構築。
    返り値: {
      'kg': {fish: [(ship, value), ...] (降順)},
      'cm': {fish: [(ship, value), ...] (降順)},
    }
    全 ship で 1 回計算・以降は使い回し。
    """
    global _SHIP_CROSS_RANK
    if _SHIP_CROSS_RANK is not None:
        return _SHIP_CROSS_RANK
    from collections import defaultdict
    fish_ship_max_kg = defaultdict(dict)  # fish -> {ship: kg}
    fish_ship_max_cm = defaultdict(dict)
    try:
        all_files = [f for f in os.listdir(_DATA_DIR) if f.endswith(".csv") and f != "cancellations.csv"]
    except FileNotFoundError:
        _SHIP_CROSS_RANK = {"kg": {}, "cm": {}}
        return _SHIP_CROSS_RANK
    for fname in all_files:
        path = os.path.join(_DATA_DIR, fname)
        try:
            with open(path, encoding="utf-8") as fp:
                for r in csv.DictReader(fp):
                    fish = (r.get("tsuri_mono") or "").strip()
                    ship = (r.get("ship") or "").strip()
                    if not fish or fish in ("不明", "欠航", "NULL") or not ship:
                        continue
                    try:
                        km = float(r.get("kg_max") or 0)
                        if km > 0 and km > fish_ship_max_kg[fish].get(ship, 0):
                            fish_ship_max_kg[fish][ship] = km
                    except (ValueError, TypeError):
                        pass
                    try:
                        sm = float(r.get("size_max") or 0)
                        if sm > 0 and sm > fish_ship_max_cm[fish].get(ship, 0):
                            fish_ship_max_cm[fish][ship] = sm
                    except (ValueError, TypeError):
                        pass
        except Exception:
            continue
    # ランキング (降順) に変換
    rank_kg = {fish: sorted(d.items(), key=lambda x: -x[1]) for fish, d in fish_ship_max_kg.items()}
    rank_cm = {fish: sorted(d.items(), key=lambda x: -x[1]) for fish, d in fish_ship_max_cm.items()}
    _SHIP_CROSS_RANK = {"kg": rank_kg, "cm": rank_cm}
    return _SHIP_CROSS_RANK


# 魚種別 kg/cm 単位の判定 (B/C/D 共通)
_FISH_KG_SET = {
    "マダイ", "アマダイ", "シロアマダイ", "マハタ", "アカハタ", "ハタ", "アラ",
    "キハダマグロ", "キメジ", "カツオ", "ワラサ", "イナダ", "ブリ", "カンパチ",
    "シマアジ", "ヒラマサ", "シーバス", "ヒラメ", "マダコ", "キンメダイ",
    "クロムツ", "メダイ", "メヌケ", "アカムツ", "アブラボウズ", "ハナダイ",
    "クロダイ", "カイワリ", "サワラ", "シイラ",
}

def _fish_unit(fish):
    """魚種別の kg/cm 単位を返す。kg 系魚種は 'kg'・それ以外は 'cm'。"""
    return "kg" if fish in _FISH_KG_SET else "cm"


def _ship_load_monthly_archive(ship_name, max_months=13):
    """data/V2/*.csv から船宿の月別出船・釣果集計を返す。
    返り値: list[dict] — 新月→古月の順、最大 max_months 件
    各要素: {
      'month': 'YYYY-MM', 'trips': int, 'cancels': int, 'rate': int (%),
      'fish': [{'fish': str, 'count': int, 'avg': float, 'size_max': int|None, 'kg_max': float|None}] 上位5魚種
    }
    注: data/V2/ には通常 CSV (`YYYY-MM.csv`) と chowari 由来 CSV (`chowari_YYYY-MM.csv`) が
    共存する。船宿によってどちらか片方にしかレコードが無いため、同じ月 key で両ファイル
    を集計対象にまとめる (T32 検証で「両ファイルに同船宿存在は 0.02% で許容範囲」確認済)。
    """
    if not ship_name:
        return []
    try:
        all_files = os.listdir(_DATA_DIR)
    except FileNotFoundError:
        return []
    month_groups = {}
    for f in all_files:
        if not f.endswith(".csv") or f == "cancellations.csv":
            continue
        if f.startswith("chowari_"):
            month_key = f[len("chowari_"):].replace(".csv", "")
        else:
            month_key = f.replace(".csv", "")
        if len(month_key) != 7 or month_key[4] != "-":
            continue
        month_groups.setdefault(month_key, []).append(os.path.join(_DATA_DIR, f))
    if not month_groups:
        return []
    sorted_months = sorted(month_groups.keys(), reverse=True)[:max_months]
    result = []
    for month_key in sorted_months:
        trips = 0
        cancels = 0
        fish_count = {}
        fish_cnt_sum = {}
        fish_size_max = {}
        fish_kg_max = {}
        for path in month_groups[month_key]:
            try:
                with open(path, encoding="utf-8") as fp:
                    reader = csv.DictReader(fp)
                    for row in reader:
                        if row.get("ship") != ship_name:
                            continue
                        if row.get("is_cancellation") == "1":
                            cancels += 1
                            continue
                        trips += 1
                        fish = (row.get("tsuri_mono") or "").strip()
                        if not fish or fish in ("不明", "欠航", "NULL"):
                            continue
                        fish_count[fish] = fish_count.get(fish, 0) + 1
                        try:
                            cnt = float(row.get("cnt_avg") or 0)
                            if cnt > 0 and _is_plausible_cnt(fish, cnt):
                                fish_cnt_sum.setdefault(fish, []).append(cnt)
                        except (ValueError, TypeError):
                            pass
                        # 魚種別の妥当範囲（_FISH_SIZE_RANGE_MAP）で異常値除外
                        _range = _FISH_SIZE_RANGE_MAP.get(fish, {})
                        _cm_cap = _range.get("cm_max")
                        _kg_cap = _range.get("kg_max")
                        try:
                            sm = float(row.get("size_max") or 0)
                            if _cm_cap is not None and sm > _cm_cap:
                                sm = 0  # 異常値は集計から除外
                            if sm > fish_size_max.get(fish, 0):
                                fish_size_max[fish] = sm
                        except (ValueError, TypeError):
                            pass
                        try:
                            km = float(row.get("kg_max") or 0)
                            if _kg_cap is not None and km > _kg_cap:
                                km = 0  # 異常値は集計から除外（例: アジ 8.8kg）
                            if km > fish_kg_max.get(fish, 0):
                                fish_kg_max[fish] = km
                        except (ValueError, TypeError):
                            pass
            except Exception:
                continue
        if trips == 0 and cancels == 0:
            continue
        total = trips + cancels
        rate = round(trips / total * 100) if total else 0
        top_fish = sorted(fish_count.items(), key=lambda x: -x[1])[:5]
        fish_list = []
        for fish, cnt in top_fish:
            cnt_list = fish_cnt_sum.get(fish) or []
            avg = round(sum(cnt_list) / len(cnt_list), 1) if cnt_list else 0
            sm_v = fish_size_max.get(fish, 0)
            km_v = fish_kg_max.get(fish, 0)
            fish_list.append({
                "fish": fish, "count": cnt, "avg": avg,
                "size_max": int(sm_v) if sm_v > 0 else None,
                "kg_max": round(km_v, 1) if km_v > 0 else None,
            })
        result.append({
            "month": month_key, "trips": trips, "cancels": cancels,
            "rate": rate, "fish": fish_list,
        })
    return result


def _ship_load_yearly_summary(ship_name, today_dt):
    """B 年間サマリー集計 (過去12ヶ月) + B+ 用データを返す。月別キャッシュ対応。
    返り値: {
      period_start, period_end (YYYY-MM),
      total_trips, total_cancels, rate,
      top_fish: [{fish, count, avg_min, avg_max, max_cnt, max_kg, max_size, unit}] TOP3
    }
    """
    cache = _ship_load_monthly_cache(today_dt)
    if ship_name in cache and "yearly" in (cache[ship_name] or {}):
        return cache[ship_name]["yearly"]
    months = _ship_load_monthly_archive(ship_name, max_months=12)
    if not months:
        result = None
    else:
        from collections import Counter
        total_trips = sum(m["trips"] for m in months)
        total_cancels = sum(m["cancels"] for m in months)
        # 出船率は欠航データ欠落で信用不可・廃止
        # 代替: ユニーク釣行日数 + 釣果魚種数
        unique_dates = set()
        fish_set = set()
        from collections import Counter as _CR
        raw_counter = _CR()
        month_keys = [m["month"] for m in months]
        for month_key in month_keys:
            for fname in (f"{month_key}.csv", f"chowari_{month_key}.csv"):
                p = os.path.join(_DATA_DIR, fname)
                if not os.path.exists(p):
                    continue
                try:
                    with open(p, encoding="utf-8") as fp:
                        for r in csv.DictReader(fp):
                            if r.get("ship") != ship_name:
                                continue
                            if r.get("is_cancellation") == "1":
                                continue
                            d = (r.get("date") or "").strip()
                            if d:
                                unique_dates.add(d)
                            fish = (r.get("tsuri_mono") or "").strip()
                            if fish and fish not in ("不明", "欠航", "NULL"):
                                fish_set.add(fish)
                            # tsuri_mono_raw 集計 (船宿の現場表記・釣りものの具体性)
                            raw = (r.get("tsuri_mono_raw") or "").strip()
                            if raw and raw not in ("不明", "欠航", "NULL"):
                                raw_counter[raw] += 1
                except Exception:
                    continue
        unique_days = len(unique_dates)
        unique_fishes = len(fish_set)
        raw_top = [r for r, _ in raw_counter.most_common(5)]
        # 年間 TOP3 + 詳細 (cnt_min/max 平均・max値)
        fish_count = Counter()
        for m in months:
            for fi in m.get("fish", []):
                fish_count[fi["fish"]] += fi["count"]
        top3 = fish_count.most_common(3)
        # 各 TOP3 の詳細: 全期間 CSV から cnt_min/cnt_max 集計
        top_fish_detail = []
        for fish, n in top3:
            cnt_mins, cnt_maxes, max_kg, max_size = [], [], 0, 0
            month_keys = [m["month"] for m in months]
            for month_key in month_keys:
                for fname in (f"{month_key}.csv", f"chowari_{month_key}.csv"):
                    p = os.path.join(_DATA_DIR, fname)
                    if not os.path.exists(p):
                        continue
                    try:
                        with open(p, encoding="utf-8") as fp:
                            for r in csv.DictReader(fp):
                                if r.get("ship") != ship_name:
                                    continue
                                if r.get("tsuri_mono") != fish:
                                    continue
                                try:
                                    cn = float(r.get("cnt_min") or 0)
                                    if cn > 0: cnt_mins.append(cn)
                                except: pass
                                try:
                                    cx = float(r.get("cnt_max") or 0)
                                    if cx > 0 and _is_plausible_cnt(fish, cx): cnt_maxes.append(cx)
                                except: pass
                                try:
                                    km = float(r.get("kg_max") or 0)
                                    if km > max_kg: max_kg = km
                                except: pass
                                try:
                                    sm = float(r.get("size_max") or 0)
                                    if sm > max_size: max_size = sm
                                except: pass
                    except Exception:
                        continue
            avg_min = round(sum(cnt_mins) / len(cnt_mins), 1) if cnt_mins else 0
            avg_max = round(sum(cnt_maxes) / len(cnt_maxes), 1) if cnt_maxes else 0
            max_cnt = int(max(cnt_maxes)) if cnt_maxes else 0
            unit = _fish_unit(fish)
            top_fish_detail.append({
                "fish": fish, "count": n,
                "avg_min": avg_min, "avg_max": avg_max, "max_cnt": max_cnt,
                "max_kg": round(max_kg, 1) if max_kg > 0 else None,
                "max_size": int(max_size) if max_size > 0 else None,
                "unit": unit,
            })
        result = {
            "period_start": months[-1]["month"], "period_end": months[0]["month"],
            "total_trips": total_trips,
            "unique_days": unique_days,
            "unique_fishes": unique_fishes,
            "raw_top": raw_top,
            "top_fish": top_fish_detail,
        }
    cache.setdefault(ship_name, {})["yearly"] = result
    return result


# 規模カテゴリ (年間出船数)
def _ship_size_category(total_trips):
    if total_trips >= 500: return "大型船宿"
    if total_trips >= 200: return "中規模船宿"
    if total_trips >= 50:  return "小規模船宿"
    return "小規模"


# 季節分類 (春3-5月・夏6-8月・秋9-11月・冬12-2月)
_SEASON_MAP = {
    3: ("春", "spring"), 4: ("春", "spring"), 5: ("春", "spring"),
    6: ("夏", "summer"), 7: ("夏", "summer"), 8: ("夏", "summer"),
    9: ("秋", "autumn"), 10: ("秋", "autumn"), 11: ("秋", "autumn"),
    12: ("冬", "winter"), 1: ("冬", "winter"), 2: ("冬", "winter"),
}

def _ship_generate_portrait_text(ship_name, area, yearly, seasonal, trophies):
    """B+ 船宿特徴文をデータから自動生成 (約500字・5段落・月一更新)。
    入力: yearly (年間サマリー)・seasonal (季節別 TOP2)・trophies (関東TOPクラス大物)
    段落構成:
      1. 船宿概要+主軸魚種+年間規模
      2. 季節別の主力魚種
      3. 大物実績 (具体的な魚種・サイズ)
      4. 月別ピーク傾向 (最多便数の月)
      5. おすすめの釣り人像
    規模カテゴリ (大型/小規模) は失礼に当たるため使わない。出船率も信頼できない (欠航データ欠落) ため使わない。
    """
    if not yearly or not yearly.get("top_fish"):
        return ""
    top = yearly["top_fish"]
    top1 = top[0]["fish"] if top else ""
    top2_3 = [t["fish"] for t in top[1:3]] if len(top) > 1 else []
    total_trips = yearly.get("total_trips", 0)
    unique_fishes = yearly.get("unique_fishes", 0)

    # 釣りジャンル推定 (主要魚種から)
    def _genre(fishes):
        if any(f in ("マハタ", "アカムツ", "クロムツ", "キンメダイ", "メダイ", "アラ") for f in fishes):
            return "深場の高級魚を狙う五目釣り"
        if any(f in ("マルイカ", "スルメイカ", "ヤリイカ", "アオリイカ", "ムギイカ") for f in fishes):
            return "イカ狙い"
        if any(f in ("タチウオ",) for f in fishes):
            return "タチウオ専門"
        if any(f in ("カツオ", "キハダマグロ", "ワラサ", "ブリ", "シイラ") for f in fishes):
            return "青物・回遊魚狙い"
        if "マダイ" in fishes:
            return "マダイ五目"
        if "アジ" in fishes:
            return "アジ五目"
        return f"{top1}メイン"
    genre = _genre([top1] + top2_3)

    # 推奨ターゲット層 (ジャンル別定型)
    def _recommend(g):
        if "深場" in g:
            return "電動リールでの深場釣り経験者や、高級魚を本気で狙いたい中級〜上級者"
        if "イカ" in g:
            return "イカ釣りが好きな方や、繊細な誘いと数釣りの両方を楽しみたい釣り人"
        if "タチウオ" in g:
            return "テンヤやジギングでタチウオを狙いたい釣り人"
        if "青物" in g:
            return "回遊魚との力強い引きを味わいたい釣り人"
        if "マダイ" in g:
            return "マダイ一本狙いから五目まで幅広く楽しみたい釣り人"
        if "アジ" in g:
            return "アジ釣りが好きな方や、家族・初心者連れでも安心して乗れる船を探している方"
        return f"{top1}を中心に多魚種を狙いたい釣り人"

    # 段落2: 季節別主力魚種
    season_order = ["春", "夏", "秋", "冬"]
    season_lines = []
    max_season = None
    max_season_cnt = 0
    if seasonal:
        for s in season_order:
            fishes = seasonal.get(s)
            if not fishes:
                continue
            top2 = [f["fish"] for f in fishes[:2]]
            if top2:
                season_lines.append(f"<strong>{s}は{'・'.join(top2)}</strong>")
        for s, fishes in seasonal.items():
            cnt = sum(f["count"] for f in fishes) if fishes else 0
            if cnt > max_season_cnt:
                max_season_cnt = cnt
                max_season = s
    season_str = ""
    if season_lines:
        season_str = "季節ごとの主力魚種は、" + "、".join(season_lines) + "が中心で、四季を通じて狙える魚種が豊富。"
        if max_season:
            season_str += f"特に{max_season}に出船が集中する。"

    # 段落3: 大物実績 (具体的な魚種・サイズ・ランキング)
    trophy_str = ""
    if trophies:
        n = len(trophies)
        trophy_parts = []
        seen = set()
        top_rank_info = None  # (fish, rank, n_ships) 最上位 1 件をピックアップ
        for t in trophies[:8]:
            fish = t.get("fish")
            val = t.get("value")
            unit = t.get("unit")
            if not fish or fish in seen or not val or not unit:
                continue
            seen.add(fish)
            trophy_parts.append(f"<strong>{fish}最大{val}{unit}</strong>")
            if top_rank_info is None:
                top_rank_info = (fish, t.get("rank"), t.get("n_ships"))
            if len(trophy_parts) >= 3:
                break
        if trophy_parts:
            trophy_str = "大物実績は<strong>関東トップクラス</strong>で、" + "・".join(trophy_parts) + f"など全船宿ランキング上位に{n}件入賞。"
            if top_rank_info and top_rank_info[1] and top_rank_info[2]:
                trophy_str += f"特に{top_rank_info[0]}は競合{top_rank_info[2]}船宿中{top_rank_info[1]}位の実績で、{area}エリアでも屈指の型狙いポイントを押さえている証拠。"
            else:
                trophy_str += "型狙いの中級者以上にも応えられる、ベテラン御用達の船宿。"

    # 段落4: 月別ピーク + 上位月の分布
    monthly_str = ""
    months = _ship_load_monthly_archive(ship_name, max_months=12)
    if months:
        sorted_months = sorted(months, key=lambda m: m.get("trips", 0), reverse=True)
        peak = sorted_months[0] if sorted_months else None
        if peak and peak.get("trips", 0) > 0:
            def _mo_label(mk):
                try:
                    _y, _mo = mk.split("-")
                    return f"{int(_mo)}月"
                except Exception:
                    return mk
            month_label = _mo_label(peak["month"])
            peak_fishes = [fi["fish"] for fi in (peak.get("fish") or [])[:2]]
            # 上位3か月をピックアップ (年間出船分布の感覚)
            top3_months = [m for m in sorted_months[:3] if m.get("trips", 0) > 0]
            top3_str = "・".join(f"{_mo_label(m['month'])}（{m['trips']}便）" for m in top3_months)
            if peak_fishes:
                monthly_str = (
                    f"月別実績では<strong>{month_label}が年間最多の{peak['trips']}便</strong>と最盛期で、"
                    f"{'・'.join(peak_fishes)}を中心に活気ある釣行が続く。"
                )
            else:
                monthly_str = f"月別実績では<strong>{month_label}が年間最多の{peak['trips']}便</strong>で出船が集中する。"
            if len(top3_months) >= 2:
                monthly_str += f"出船数上位は{top3_str}と、季節を問わず安定した運航スケジュールを維持している。"

    # 段落生成
    paras = []
    # 段落1: 船宿概要+主軸魚種+年間規模
    raw_top = yearly.get("raw_top") or []
    if raw_top:
        raw_disp = "・".join(f"<strong>{r}</strong>" for r in raw_top[:5])
        if len(raw_top) == 1:
            paras.append(f"{area}の<strong>{ship_name}</strong>は、{raw_disp}の専門船。年間出船{total_trips}便・{unique_fishes}魚種の釣果記録があり、地元釣り師から長く支持されている船宿。")
        elif len(raw_top) >= 4:
            paras.append(f"{area}の<strong>{ship_name}</strong>は、{raw_disp}など多魚種の<strong>{genre}</strong>を案内している船宿。年間出船{total_trips}便・{unique_fishes}魚種の釣果記録があり、幅広いターゲットに対応する懐の深さが魅力。")
        else:
            paras.append(f"{area}の<strong>{ship_name}</strong>は、{raw_disp}などを軸に<strong>{genre}</strong>を案内する船宿。年間出船{total_trips}便・{unique_fishes}魚種の釣果記録があり、安定した出船実績を誇る。")
    elif top2_3:
        paras.append(f"{area}の<strong>{ship_name}</strong>は、<strong>{top1}</strong>を主軸に、{('・'.join(top2_3))}など<strong>{genre}</strong>を案内している船宿。年間出船{total_trips}便・{unique_fishes}魚種の釣果記録がある。")
    else:
        paras.append(f"{area}の<strong>{ship_name}</strong>は、<strong>{top1}</strong>を主軸に<strong>{genre}</strong>を案内している船宿。年間出船{total_trips}便の実績がある。")

    # 段落2: 季節別
    if season_str:
        paras.append(season_str)

    # 段落3: 大物実績
    if trophy_str:
        paras.append(trophy_str)

    # 段落4: 月別ピーク
    if monthly_str:
        paras.append(monthly_str)

    # 段落5: おすすめ + 利用シーン
    closing = (
        f"{_recommend(genre)}におすすめ。"
        f"{area}エリアの船宿選びに迷ったら、年間出船{total_trips}便・{unique_fishes}魚種という実績が示す通り、"
        "幅広いシーズン・狙い物に対応できる選択肢として候補に入る一隻。"
    )
    paras.append(closing)

    return "".join(f"<p>{p}</p>" for p in paras)


def _ship_yearly_summary_section_html(yearly, ship_name, area, seasonal=None, trophies=None):
    """B 年間サマリー (+ B+ 特徴文) HTML を返す"""
    if not yearly:
        return ""
    import html as _html
    period_start = yearly["period_start"]
    period_end = yearly["period_end"]
    try:
        ps = datetime.strptime(period_start, "%Y-%m")
        pe = datetime.strptime(period_end, "%Y-%m")
        period_str = f"{ps.year}年{ps.month}月 〜 {pe.year}年{pe.month}月（過去12ヶ月）"
    except Exception:
        period_str = f"{period_start} 〜 {period_end}"
    # B+ 特徴文
    portrait_html = ""
    portrait_text = _ship_generate_portrait_text(ship_name, area, yearly, seasonal, trophies)
    if portrait_text:
        portrait_html = (
            '<div class="ys-portrait">'
            '<span class="ysp-label">📝 この船宿の特徴</span>'
            f'{portrait_text}'
            '</div>'
        )
    # KPI 3 (出船率は信用不可で削除・代替: 釣行日数 + 釣果魚種数)
    kpi_html = (
        '<div class="ys-kpi-grid">'
        f'<div class="ys-kpi"><div class="ysk-n cta">{yearly["total_trips"]}<span style="font-size:13px">便</span></div><div class="ysk-l">年間出船数</div></div>'
        f'<div class="ys-kpi"><div class="ysk-n">{yearly.get("unique_days", 0)}<span style="font-size:13px">日</span></div><div class="ysk-l">年間釣行日数</div></div>'
        f'<div class="ys-kpi"><div class="ysk-n">{yearly.get("unique_fishes", 0)}<span style="font-size:13px">種</span></div><div class="ysk-l">年間釣果魚種数</div></div>'
        '</div>'
    )
    # TOP3 魚種カード
    cards = []
    for i, fi in enumerate(yearly["top_fish"]):
        medal = ["🥇", "🥈", "🥉"][i] if i < 3 else ""
        rank_cls = f"rank{i+1}"
        fish_slug = _fish_asset_img_slug(fi["fish"])
        img_src = f"../assets/fish/{fish_slug}/{fish_slug}_emoji.webp" if fish_slug else ""
        max_str = ""
        if fi["max_kg"]:
            max_str = f'{fi["max_kg"]} kg'
        elif fi["max_size"]:
            max_str = f'{fi["max_size"]} cm'
        avg_str = f'{fi["avg_min"]}〜{fi["avg_max"]}匹' if (fi["avg_min"] > 0 or fi["avg_max"] > 0) else "—"
        cnt_str = f'{fi["max_cnt"]}匹' if fi["max_cnt"] > 0 else "—"
        img_html = f'<img class="ys-tf-img" src="{img_src}" alt="{_html.escape(fi["fish"])}" onerror="this.style.display=\'none\'">' if img_src else ''
        cards.append(
            f'<div class="ys-tf-card {rank_cls}">'
            f'<span class="ys-tf-medal">{medal}</span>'
            f'{img_html}'
            f'<div class="ys-tf-head"><span class="ys-tf-name">{_html.escape(fi["fish"])}</span><span class="ys-tf-trips">{fi["count"]}便</span></div>'
            f'<div class="ys-tf-stats">'
            f'<span class="ystf-row">平均釣果 <strong>{avg_str}</strong></span>'
            f'<span class="ystf-row">最大匹数 <strong>{cnt_str}</strong></span>'
            f'<span class="ystf-row">最大型 <span class="ystf-max">{max_str if max_str else "—"}</span></span>'
            f'</div>'
            f'</div>'
        )
    top3_html = (
        '<div class="ys-section">'
        '<h4>🎣 年間 主要魚種 TOP3</h4>'
        f'<div class="ys-top-fish">{"".join(cards)}</div>'
        '</div>'
    )
    return (
        '<div class="yearly-summary">'
        '<span class="ys-label">📅 年間サマリー</span>'
        f'<div class="ys-period">{period_str}</div>'
        f'{portrait_html}'
        f'{kpi_html}'
        f'{top3_html}'
        '</div>'
    )


def _ship_load_seasonal_fish(ship_name, today_dt):
    """C 季節別主力魚種 (春夏秋冬 × TOP2 + 詳細)。月別キャッシュ対応。
    返り値: {"春": [{fish, count, avg_min, avg_max, max_cnt, max_kg, max_size, unit}, ...TOP2], ...}
    """
    cache = _ship_load_monthly_cache(today_dt)
    if ship_name in cache and "seasonal" in (cache[ship_name] or {}):
        return cache[ship_name]["seasonal"]
    months = _ship_load_monthly_archive(ship_name, max_months=12)
    if not months:
        result = None
    else:
        from collections import Counter, defaultdict
        # 季節別 fish_count
        season_fish_count = {s[0]: Counter() for s in _SEASON_MAP.values()}
        season_months = defaultdict(list)
        for m in months:
            try:
                _, mo = m["month"].split("-")
                mo = int(mo)
            except:
                continue
            sname, _ = _SEASON_MAP.get(mo, (None, None))
            if not sname:
                continue
            season_months[sname].append(m["month"])
            for fi in m.get("fish", []):
                season_fish_count[sname][fi["fish"]] += fi["count"]
        # 各季節 TOP2 + 詳細
        result = {}
        for sname in ("春", "夏", "秋", "冬"):
            top2 = season_fish_count[sname].most_common(2)
            fish_details = []
            for fish, n in top2:
                # 季節月の CSV から cnt_min/max + max_kg/size
                cnt_mins, cnt_maxes, max_kg, max_size = [], [], 0, 0
                for month_key in season_months[sname]:
                    for fname in (f"{month_key}.csv", f"chowari_{month_key}.csv"):
                        p = os.path.join(_DATA_DIR, fname)
                        if not os.path.exists(p):
                            continue
                        try:
                            with open(p, encoding="utf-8") as fp:
                                for r in csv.DictReader(fp):
                                    if r.get("ship") != ship_name or r.get("tsuri_mono") != fish:
                                        continue
                                    try:
                                        cn = float(r.get("cnt_min") or 0)
                                        if cn > 0: cnt_mins.append(cn)
                                    except: pass
                                    try:
                                        cx = float(r.get("cnt_max") or 0)
                                        if cx > 0 and _is_plausible_cnt(fish, cx): cnt_maxes.append(cx)
                                    except: pass
                                    try:
                                        km = float(r.get("kg_max") or 0)
                                        if km > max_kg: max_kg = km
                                    except: pass
                                    try:
                                        sm = float(r.get("size_max") or 0)
                                        if sm > max_size: max_size = sm
                                    except: pass
                        except Exception:
                            continue
                avg_min = round(sum(cnt_mins) / len(cnt_mins), 1) if cnt_mins else 0
                avg_max = round(sum(cnt_maxes) / len(cnt_maxes), 1) if cnt_maxes else 0
                max_cnt = int(max(cnt_maxes)) if cnt_maxes else 0
                fish_details.append({
                    "fish": fish, "count": n,
                    "avg_min": avg_min, "avg_max": avg_max, "max_cnt": max_cnt,
                    "max_kg": round(max_kg, 1) if max_kg > 0 else None,
                    "max_size": int(max_size) if max_size > 0 else None,
                    "unit": _fish_unit(fish),
                })
            result[sname] = fish_details
    cache.setdefault(ship_name, {})["seasonal"] = result
    return result


_SEASON_DISPLAY = {
    "春": ("spring", "🌸", "3-5月"),
    "夏": ("summer", "☀️", "6-8月"),
    "秋": ("autumn", "🍁", "9-11月"),
    "冬": ("winter", "❄️", "12-2月"),
}

def _ship_seasonal_fish_section_html(seasonal):
    """C 季節別主力魚種 HTML を返す"""
    if not seasonal:
        return ""
    import html as _html
    cards = []
    for sname in ("春", "夏", "秋", "冬"):
        cls, emoji, months_label = _SEASON_DISPLAY[sname]
        fishes = seasonal.get(sname, []) or []
        if not fishes:
            rows_html = '<li class="sf-fish-row"><span class="sf-fish-rank">-</span><div class="sf-fish-body"><div class="sf-fish-stats" style="color:var(--muted)">この季節のデータなし</div></div></li>'
        else:
            rows = []
            for i, fi in enumerate(fishes, 1):
                fish_slug = _fish_asset_img_slug(fi["fish"])
                img_src = f"../assets/fish/{fish_slug}/{fish_slug}_emoji.webp" if fish_slug else ""
                img_html = f'<img class="sf-fish-img" src="{img_src}" alt="{_html.escape(fi["fish"])}" onerror="this.style.display=\'none\'">' if img_src else '<span class="sf-fish-img"></span>'
                max_str = ""
                if fi["max_kg"]: max_str = f'{fi["max_kg"]} kg'
                elif fi["max_size"]: max_str = f'{fi["max_size"]} cm'
                avg_str = f'{fi["avg_min"]}〜{fi["avg_max"]}匹' if (fi["avg_min"] > 0 or fi["avg_max"] > 0) else "—"
                cnt_str = f'{fi["max_cnt"]}匹' if fi["max_cnt"] > 0 else "—"
                rows.append(
                    f'<li class="sf-fish-row">'
                    f'<span class="sf-fish-rank">{i}</span>'
                    f'{img_html}'
                    f'<div class="sf-fish-body">'
                    f'<div class="sf-fish-head"><span class="sf-fish-name">{_html.escape(fi["fish"])}</span><span class="sf-fish-trips">{fi["count"]}便</span></div>'
                    f'<div class="sf-fish-stats">平均 <strong>{avg_str}</strong> / 最大匹数 <strong>{cnt_str}</strong> / 最大 <span class="sff-max">{max_str if max_str else "—"}</span></div>'
                    f'</div>'
                    f'</li>'
                )
            rows_html = "".join(rows)
        cards.append(
            f'<div class="sf-card {cls}">'
            f'<div class="sf-head"><span class="sf-emoji-season">{emoji}</span><span class="sf-season-name">{sname}</span><span class="sf-months">{months_label}</span></div>'
            f'<ul class="sf-fish-list">{rows_html}</ul>'
            f'</div>'
        )
    return (
        '<div class="seasonal-fish">'
        '<span class="sf-label">🌐 季節別 主力魚種</span>'
        '<div class="sf-subtitle">過去12ヶ月の季節ごと主力魚種 TOP2（毎月1日更新）</div>'
        f'<div class="sf-grid">{"".join(cards)}</div>'
        '</div>'
    )


def _ship_load_top_trophies(ship_name, today_dt, top_n=10, min_competitors=5):
    """D 大物実績 cross-ship ranking。月別キャッシュ対応。
    返り値: [{rank, n_ships, fish, value, unit, date}, ...] (TOP10入りのみ・母集団 min_competitors 以上)
    """
    cache = _ship_load_monthly_cache(today_dt)
    if ship_name in cache and "trophies" in (cache[ship_name] or {}):
        return cache[ship_name]["trophies"]
    rank = _ship_compute_cross_ship_rankings()
    # 各魚種で「この船宿が TOP top_n 入り」をチェック
    result = []
    # kg / cm 両方
    for unit, rank_dict in (("kg", rank["kg"]), ("cm", rank["cm"])):
        for fish, ranked in rank_dict.items():
            n_ships = len(ranked)
            if n_ships < min_competitors:
                continue  # 母集団小さい魚種は除外
            for i, (s, v) in enumerate(ranked[:top_n], start=1):
                if s == ship_name:
                    # date を CSV から探す (この船宿の fish 最大値 record)
                    rec_date = ""
                    for fname in sorted(os.listdir(_DATA_DIR), reverse=True):
                        if not fname.endswith(".csv"): continue
                        try:
                            with open(os.path.join(_DATA_DIR, fname), encoding="utf-8") as fp:
                                for r in csv.DictReader(fp):
                                    if r.get("ship") != ship_name or r.get("tsuri_mono") != fish:
                                        continue
                                    try:
                                        val_field = r.get("kg_max" if unit == "kg" else "size_max") or "0"
                                        val = float(val_field)
                                        if abs(val - v) < 0.01:
                                            rec_date = r.get("date", "")
                                            break
                                    except: pass
                            if rec_date: break
                        except: continue
                    result.append({
                        "rank": i, "n_ships": n_ships, "fish": fish,
                        "value": v, "unit": unit, "date": rec_date,
                    })
                    break
    result.sort(key=lambda x: (x["rank"], -x["value"]))
    result = result[:10]
    cache.setdefault(ship_name, {})["trophies"] = result
    return result


def _ship_trophy_section_html(trophies):
    """D 大物実績ランキング HTML を返す。空の場合は省略 (空文字列)。"""
    if not trophies:
        return ""
    import html as _html
    rows = []
    for t in trophies:
        rank = t["rank"]
        if rank == 1:
            medal_html = '<span class="tr-medal">🥇</span>'
            row_cls = "tr-row r1"
        elif rank == 2:
            medal_html = '<span class="tr-medal">🥈</span>'
            row_cls = "tr-row r2"
        elif rank == 3:
            medal_html = '<span class="tr-medal">🥉</span>'
            row_cls = "tr-row r3"
        else:
            medal_html = f'<span class="tr-rank">{rank}位</span>'
            row_cls = "tr-row"
        fish_slug = _fish_asset_img_slug(t["fish"])
        img_src = f"../assets/fish/{fish_slug}/{fish_slug}_emoji.webp" if fish_slug else ""
        img_html = f'<img class="tr-img" src="{img_src}" alt="{_html.escape(t["fish"])}" onerror="this.style.display=\'none\'">' if img_src else ''
        badge_cls = "tr-rank-badge" if rank <= 3 else "tr-rank-badge low"
        val_str = f'{round(t["value"], 1)} kg' if t["unit"] == "kg" else f'{int(t["value"])} cm'
        date_disp = ""
        if t["date"]:
            try:
                d = datetime.strptime(t["date"], "%Y/%m/%d")
                date_disp = f'<span class="tr-date">{d.year}/{d.month:02d}/{d.day:02d}</span>'
            except Exception:
                date_disp = f'<span class="tr-date">{t["date"]}</span>'
        rows.append(
            f'<li class="{row_cls}">'
            f'{medal_html}'
            f'{img_html}'
            f'<div class="tr-body">'
            f'<span class="tr-fish">{_html.escape(t["fish"])} <span class="{badge_cls}">全船宿中 {rank}/{t["n_ships"]}位</span></span>'
            f'{date_disp}'
            f'</div>'
            f'<span class="tr-val">{val_str}</span>'
            f'</li>'
        )
    return (
        '<div class="trophy-rank">'
        '<span class="tr-label">🏆 関東トップクラス大物実績</span>'
        '<div class="tr-subtitle">魚種別「船宿別最大値」ランキングで上位入賞した自慢の1本（毎月1日更新）</div>'
        f'<ul class="tr-list">{"".join(rows)}</ul>'
        '</div>'
    )


def _ship_load_auto_badges(ship_name, today_dt, yearly, seasonal, trophies):
    """E HEROバッジ自動生成。月別キャッシュ対応。
    返り値: [{'kind': 'spec/rate/rank/vol/season', 'label': str, 'sub': str, 'fish': str|None}, ...]
    """
    cache = _ship_load_monthly_cache(today_dt)
    if ship_name in cache and "badges" in (cache[ship_name] or {}):
        return cache[ship_name]["badges"]
    badges = []
    if not yearly:
        cache.setdefault(ship_name, {})["badges"] = []
        return []
    total_fish_count = sum(fi["count"] for fi in yearly.get("top_fish", []))
    # 1. 専門船 (主要魚種 ≥ 50%)
    if yearly["top_fish"] and total_fish_count > 0:
        top1 = yearly["top_fish"][0]
        pct = round(top1["count"] / total_fish_count * 100)
        if pct >= 50:
            badges.append({"kind": "spec", "label": f"{top1['fish']}専門", "sub": f"{pct}%", "fish": top1["fish"]})
    # 2. 釣行日数 (年間 ≥ 100日 = 出船活発)
    udays = yearly.get("unique_days", 0)
    if udays >= 100:
        badges.append({"kind": "rate", "label": "年間釣行", "sub": f"{udays}日", "fish": None})
    # 3. 順位 (全船宿中 1〜3 位)
    for t in trophies or []:
        if t["rank"] <= 3:
            val_str = f'{round(t["value"], 1)}kg' if t["unit"] == "kg" else f'{int(t["value"])}cm'
            badges.append({
                "kind": "rank", "label": f'{t["fish"]} {val_str}',
                "sub": f'全船宿中 {t["rank"]}/{t["n_ships"]}位', "fish": t["fish"],
            })
            break
    # 4. 便数 (年間 ≥ 500)
    if yearly["total_trips"] >= 500:
        badges.append({"kind": "vol", "label": "年間出船", "sub": f"{yearly['total_trips']}便", "fish": None})
    # 5. 季節得意 (季節 TOP1 魚種で年間 100便以上)
    if seasonal:
        max_s, max_fish, max_n = None, None, 0
        for sname in ("春", "夏", "秋", "冬"):
            fishes = seasonal.get(sname, []) or []
            if fishes and fishes[0]["count"] > max_n:
                max_s = sname
                max_fish = fishes[0]["fish"]
                max_n = fishes[0]["count"]
        if max_s and max_n >= 30:
            badges.append({
                "kind": "season", "label": f"{max_s}{max_fish}",
                "sub": f"{max_n}便", "fish": max_fish,
            })
    badges = badges[:5]
    cache.setdefault(ship_name, {})["badges"] = badges
    return badges


def _ship_auto_badges_html(badges):
    """E HEROバッジ HTML を返す (HERO 内に挿入)"""
    if not badges:
        return ""
    import html as _html
    ICONS = {"rate": "✓", "rank": "🥈", "vol": "📅", "season": "🌟"}
    SEASON_ICONS = {"春": "🌸", "夏": "☀️", "秋": "🍁", "冬": "❄️"}
    items = []
    for b in badges:
        kind = b["kind"]
        fish_img_html = ""
        if b.get("fish"):
            fish_slug = _fish_asset_img_slug(b["fish"])
            if fish_slug:
                fish_img_html = f'<img class="sh-ab-fish-img" width="14" height="14" src="../assets/fish/{fish_slug}/{fish_slug}_emoji.webp" alt="{_html.escape(b["fish"])}" onerror="this.style.display=\'none\'">'
        icon_html = ""
        if kind == "rank":
            t_rank = b["sub"].split("/")[0].replace("全船宿中 ", "").strip()
            icon_html = f'<span class="sh-ab-icon">{"🥇" if t_rank == "1" else ("🥈" if t_rank == "2" else "🥉")}</span>'
        elif kind == "season":
            for sname, ico in SEASON_ICONS.items():
                if b["label"].startswith(sname):
                    icon_html = f'<span class="sh-ab-icon">{ico}</span>'
                    break
        elif kind == "rate":
            icon_html = '<span class="sh-ab-icon">✓</span>'
        elif kind == "vol":
            icon_html = '<span class="sh-ab-icon">📅</span>'
        sub_html = f'<span class="sh-ab-sub">{_html.escape(b["sub"])}</span>' if b.get("sub") else ""
        items.append(
            f'<span class="sh-ab {kind}">'
            f'{icon_html}'
            f'{fish_img_html}'
            f'{_html.escape(b["label"])}'
            f'{sub_html}'
            f'</span>'
        )
    return (
        '<div class="sub-label">🤖 データ分析バッジ</div>'
        f'<div class="sh-auto-badges">{"".join(items)}</div>'
    )


def _ship_weekly_report_section_html(weekly, yoy, tide_days, today_dt):
    """週次レポート HTML を返す。weekly が None or 今週 trips == 0 なら空文字列。
    weekly: _ship_load_weekly_data() の出力
    yoy: _ship_load_yoy_data() の出力 (None でも可)
    tide_days: _ship_get_next_week_spring_tides() の出力 (空でも可)
    """
    if not weekly:
        return ""
    tw = weekly.get("this_week") or {}
    pw = weekly.get("prev_week") or {}
    this_trips = tw.get("trips", 0)
    if this_trips == 0:
        return ""  # 今週データなしならセクション全省略
    import html as _html

    # 期間表示: M/D〜M/D
    try:
        ps = datetime.strptime(weekly["period_start"], "%Y/%m/%d")
        pe = datetime.strptime(weekly["period_end"], "%Y/%m/%d")
        period_str = f"{ps.year}年{ps.month}月{ps.day}日〜{pe.month}月{pe.day}日（7日間）"
    except Exception:
        period_str = f"{weekly['period_start']} 〜 {weekly['period_end']}"

    # KPI 行: 今週の出船便数 + 前週比（出船率は撤去・欠航データ不完全のため）
    prev_trips = pw.get("trips", 0)
    if prev_trips > 0:
        diff = this_trips - prev_trips
        if diff >= 0:
            diff_html = f'<span class="wkr-diff">前週比 +{diff}便</span>'
        else:
            diff_html = f'<span class="wkr-diff neg">前週比 {diff}便</span>'
    else:
        diff_html = '<span class="wkr-diff" style="background:rgba(138,150,164,.12);color:var(--muted)">前週データなし</span>'
    kpi_row = (
        '<div class="wr-kpi-row">'
        '<span class="wkr-label">今週の出船</span>'
        f'<span class="wkr-main">{this_trips}便</span>'
        f'{diff_html}'
        '</div>'
    )

    # 主要釣果 Top2 + 大物速報
    top_fish_items = sorted(tw["fish_count"].items(), key=lambda x: -x[1])[:2]
    fish_list_rows = []
    trophy_html = ""
    best_trophy = None  # (fish, kind, value, date)
    for fish, cnt in top_fish_items:
        prev_cnt = pw.get("fish_count", {}).get(fish, 0)
        cnt_diff = cnt - prev_cnt
        if cnt_diff > 0:
            diff_chip = f'<span class="wfl-diff">前週比 +{cnt_diff}便</span>'
        elif cnt_diff < 0:
            diff_chip = f'<span class="wfl-diff neg">前週比 {cnt_diff}便</span>'
        else:
            diff_chip = ''
        # 詳細
        cnt_list = tw["fish_cnt_sum"].get(fish) or []
        avg = round(sum(cnt_list) / len(cnt_list), 1) if cnt_list else 0
        sm = tw["fish_size_max"].get(fish, 0)
        km = tw["fish_kg_max"].get(fish, 0)
        detail_parts = []
        if avg > 0:
            detail_parts.append(f"平均 {avg}匹")
        if km > 0:
            detail_parts.append(f"最大 {round(km, 1)}kg")
        elif sm > 0:
            detail_parts.append(f"最大 {int(sm)}cm")
        detail = "・".join(detail_parts)
        detail_html = f'<span class="wfl-detail">{detail}</span>' if detail else ''
        # 魚 emoji webp
        _fslug = _fish_asset_img_slug(fish)
        fish_img = f'<img class="wfl-fish-img" width="16" height="16" src="../assets/fish/{_fslug}/{_fslug}_emoji.webp" alt="" onerror="this.style.display=\'none\'">' if _fslug else ''
        fish_list_rows.append(
            f'<li>'
            f'{fish_img}'
            f'<span class="wfl-fish">{_html.escape(fish)}</span>'
            f'<span class="wfl-count">{cnt}便</span>'
            f'{diff_chip}'
            f'{detail_html}'
            f'</li>'
        )
        # 大物候補
        rec = tw["fish_max_record"].get(fish)
        if rec:
            kind, val, date = rec
            # 比較指標: kg は val そのまま、size は val/100 程度
            score = val if kind == "kg" else val / 100
            if best_trophy is None or score > best_trophy[4]:
                best_trophy = (fish, kind, val, date, score)
    if fish_list_rows:
        fish_list_html = (
            '<div class="wr-section">'
            '<h4>🎣 今週の主要釣果</h4>'
            f'<ul class="wr-fish-list">{"".join(fish_list_rows)}</ul>'
        )
        if best_trophy:
            fish, kind, val, date_str, _ = best_trophy
            try:
                d = datetime.strptime(date_str, "%Y/%m/%d")
                date_disp = f"{d.month}/{d.day}"
            except Exception:
                date_disp = date_str
            if kind == "kg":
                val_str = f"{round(val, 1)}kg"
            else:
                val_str = f"{int(val)}cm"
            _tslug = _fish_asset_img_slug(fish)
            trophy_img = f'<img class="wrt-fish-img" width="16" height="16" src="../assets/fish/{_tslug}/{_tslug}_emoji.webp" alt="" onerror="this.style.display=\'none\'">' if _tslug else ''
            fish_list_html += (
                '<div style="margin-top:8px">'
                f'<span class="wr-trophy">🏆 今週の大物: {trophy_img}{_html.escape(fish)} {val_str}'
                f'<span class="wrt-date">({date_disp})</span></span>'
                '</div>'
            )
        fish_list_html += '</div>'
    else:
        fish_list_html = ''

    # 来週の見どころ
    next_rows = []
    # シーズン位置: 主要魚種 Top1 のシーズン文 (来月にかかる場合は来月)
    next_week_start = today_dt + timedelta(days=1)
    season_month = next_week_start.month
    def _fish_inline_img(fish):
        s = _fish_asset_img_slug(fish)
        return f'<img class="wnw-fish-img" width="14" height="14" src="../assets/fish/{s}/{s}_emoji.webp" alt="" onerror="this.style.display=\'none\'" style="vertical-align:middle;margin-right:3px">' if s else ''
    if top_fish_items:
        top_fish = top_fish_items[0][0]
        phrase = _fish_season_phrase(top_fish, season_month)
        if phrase:
            next_rows.append(
                '<div class="wnw-row">'
                '<span class="wnw-tag">シーズン</span>'
                f'<span class="wnw-text">{_fish_inline_img(top_fish)}<strong>{_html.escape(top_fish)}</strong>:{_html.escape(phrase)}</span>'
                '</div>'
            )
        # 2 番目魚種も
        if len(top_fish_items) >= 2:
            f2 = top_fish_items[1][0]
            p2 = _fish_season_phrase(f2, season_month)
            if p2:
                next_rows.append(
                    '<div class="wnw-row">'
                    '<span class="wnw-tag">シーズン</span>'
                    f'<span class="wnw-text">{_fish_inline_img(f2)}<strong>{_html.escape(f2)}</strong>:{_html.escape(p2)}</span>'
                    '</div>'
                )
    # 大潮日
    if tide_days:
        first_date = tide_days[0][0]
        last_date = tide_days[-1][0] if len(tide_days) > 1 else first_date
        if first_date == last_date:
            range_str = first_date
        else:
            range_str = f"{first_date}〜{last_date}"
        next_rows.append(
            '<div class="wnw-row">'
            '<span class="wnw-tag">潮回り</span>'
            f'<span class="wnw-text"><strong>{range_str} 大潮</strong> — 朝マズメ活性 UP 期待</span>'
            '</div>'
        )
    next_html = ''
    if next_rows:
        end_dt = today_dt + timedelta(days=7)
        next_html = (
            '<div class="wr-section">'
            f'<h4>📅 来週の見どころ ({next_week_start.month}/{next_week_start.day}-{end_dt.month}/{end_dt.day})</h4>'
            f'<div class="wr-next-week">{"".join(next_rows)}</div>'
            '</div>'
        )

    # 前年比較
    yoy_html = ''
    if yoy and yoy.get("last_year_fish_count") and top_fish_items:
        top_fish = top_fish_items[0][0]
        ly_cnt = yoy["last_year_fish_count"].get(top_fish, 0)
        ty_cnt = yoy["this_year_fish_count"].get(top_fish, 0)
        if ly_cnt > 0:
            try:
                yym = datetime.strptime(yoy["last_year_month"], "%Y-%m")
                ly_label = f"{yym.year}年{yym.month}月（全期間）"
            except Exception:
                ly_label = yoy["last_year_month"]
            ty_label = f"{today_dt.year}年{today_dt.month}月（{today_dt.month}/{today_dt.day}時点）"
            yoy_html = (
                '<div class="wr-section">'
                '<h4>📊 過去比較（同月）</h4>'
                '<div class="wr-yoy">'
                f'<div class="wy-card"><div class="wy-year">{ly_label}</div>'
                f'<div class="wy-val">{_html.escape(top_fish)} {ly_cnt}<span class="wyv-unit">便</span></div></div>'
                f'<div class="wy-card now"><div class="wy-year">{ty_label}</div>'
                f'<div class="wy-val">{_html.escape(top_fish)} {ty_cnt}<span class="wyv-unit">便（途中）</span></div></div>'
                '</div>'
                '</div>'
            )

    # 統計ハイライト 3 つ
    # ラベルから「(7日中)」を撤去（出船率の連想を避ける・wr-period に7日間表記あり）
    stats_html = ''
    fish_total_count = sum(tw["fish_count"].values())
    stats_items = [
        (f"{this_trips}便", "今週の出船"),
        (str(fish_total_count), "釣果便数"),
    ]
    if top_fish_items:
        top_fish = top_fish_items[0][0]
        cnt_list = tw["fish_cnt_sum"].get(top_fish) or []
        if cnt_list:
            avg = round(sum(cnt_list) / len(cnt_list), 1)
            stats_items.append((f"{avg}匹", f"{top_fish}平均"))
    stats_inner = "".join(
        f'<div class="wr-stat"><div class="wrs-n">{n}</div><div class="wrs-l">{_html.escape(l)}</div></div>'
        for n, l in stats_items
    )
    if stats_inner:
        stats_html = f'<div class="wr-stats">{stats_inner}</div>'

    return (
        '<div class="weekly-report">'
        '<span class="wr-label">今週の傾向</span>'
        f'<div class="wr-period">{period_str}</div>'
        f'{kpi_row}'
        f'{fish_list_html}'
        f'{next_html}'
        f'{yoy_html}'
        f'{stats_html}'
        '</div>'
    )


def _ship_monthly_archive_section_html(months, ship_name, area, area_slug):
    """月別釣果実績セクションの HTML を返す。
    months: _ship_load_monthly_archive の出力（新→古順）
    最初の3ヶ月を常時表示、4ヶ月目以降は <details> 折り畳み
    months が空の場合は空文字列を返す（セクション全体省略）。
    """
    if not months:
        return ""
    import html as _html

    def _month_jp(month_key):
        try:
            y, m = month_key.split("-")
            return f"{int(y)}年{int(m)}月"
        except Exception:
            return month_key

    def _card_html(m, is_recent=False):
        # 出船率バッジ・欠航便表記は撤去（2026-05-24・欠航データ取得不完全のため）
        rows = []
        for fi in m["fish"]:
            stat_parts = [f'<span class="mfl-cnt">{fi["count"]}便</span>']
            if fi["avg"] > 0:
                stat_parts.append(f'平均{fi["avg"]}匹')
            if fi["kg_max"] is not None:
                stat_parts.append(f'最大{fi["kg_max"]}kg')
            elif fi["size_max"] is not None:
                stat_parts.append(f'最大{fi["size_max"]}cm')
            rows.append(
                f'<li class="mfl-row">'
                f'<span class="mfl-fish">{_html.escape(fi["fish"])}</span>'
                f'<span class="mfl-stat">{"・".join(stat_parts)}</span>'
                f'</li>'
            )
        fish_html = "".join(rows) if rows else '<li class="mfl-row"><span class="mfl-fish" style="color:var(--muted)">釣果データなし</span></li>'
        cls = "ma-card recent" if is_recent else "ma-card"
        return (
            f'<div class="{cls}">'
            f'<div class="ma-head">'
            f'<span class="ma-month">{_month_jp(m["month"])}</span>'
            f'</div>'
            f'<div class="ma-trips">出船 {m["trips"]}便</div>'
            f'<ul class="ma-fish-list">{fish_html}</ul>'
            f'</div>'
        )

    recent_3 = months[:3]
    older = months[3:]

    recent_html = "".join(_card_html(m, i == 0) for i, m in enumerate(recent_3))
    collapse_html = ""
    if older:
        older_cards = "".join(_card_html(m) for m in older)
        summary_text = (
            f"過去{len(older)}ヶ月分の実績を表示"
            f"（{_month_jp(older[0]['month'])}〜{_month_jp(older[-1]['month'])}）"
        )
        collapse_html = (
            f'<details class="ma-collapse">'
            f'<summary>{summary_text}</summary>'
            f'<div class="ma-grid">{older_cards}</div>'
            f'</details>'
        )

    archive_links = ""
    if months:
        top_fishes = []
        for fi in months[0]["fish"][:2]:
            top_fishes.append(fi["fish"])
        link_parts = []
        for fish in top_fishes:
            fish_slug = _FISH_ROMAJI.get(fish)
            if fish_slug and area_slug:
                link_parts.append(
                    f'<a href="../fish_area/{fish_slug}-{area_slug}.html">'
                    f'{_html.escape(fish)} × {_html.escape(area)}</a>'
                )
        if area_slug:
            link_parts.append(f'<a href="../area/{area_slug}.html">{_html.escape(area)}全体</a>')
        for fish in top_fishes:
            fish_slug = _FISH_ROMAJI.get(fish)
            if fish_slug:
                link_parts.append(f'<a href="../fish/{fish_slug}.html">関東の{_html.escape(fish)}釣果</a>')
                break
        if link_parts:
            archive_links = (
                f'<div class="ma-archive-links">'
                f'<strong style="color:var(--accent)">関連ページ:</strong>'
                f'{"".join(link_parts)}'
                f'</div>'
            )

    return (
        f'<div class="monthly-archive">'
        f'<h3>📊 月別釣果実績</h3>'
        f'<div class="ma-sub">過去{len(months)}ヶ月の出船・釣果便数データ（毎月1日に前月分を自動追加）</div>'
        f'<div class="ma-grid">{recent_html}</div>'
        f'{collapse_html}'
        f'{archive_links}'
        f'</div>'
    )


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
            if not f or f in ("不明", "欠航", "NULL"):
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
            f'<h3><span class="h-fish"><img src="../assets/fish/{fish_img_slug(fish)}/{fish_img_slug(fish)}_emoji.webp" alt="{fish}" class="fs-emoji" width="18" height="18" loading="lazy" decoding="async" onerror="this.style.display=\'none\'">{fish}</span><span class="h-range">{range_str}</span></h3>'
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
        # ships.json romaji_slug 優先（chowari 船宿を含む全船宿をリンク化）
        slug = ship_slug(sn) or _SHIP_ROMAJI.get(sn)
        if is_self:
            name_html = f'{sn}（このページ）'
        elif slug:
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
    """その船宿の主要対象魚 TOP N。
    優先: data/V2/*.csv 過去13ヶ月の月次集計 (chowari 25ヶ月遡及データ反映)
    fallback: 直近90日 catches (新規船宿で月次データなしの場合)
    """
    from collections import Counter as _C
    # まず過去13ヶ月の月次集計から計算
    try:
        monthly = _ship_load_monthly_archive(ship_name, max_months=13)
    except Exception:
        monthly = []
    if monthly:
        counter = _C()
        for m in monthly:
            for fi in m.get("fish", []):
                counter[fi["fish"]] += fi["count"]
        if counter:
            return [n for n, _ in counter.most_common(limit)]
    # fallback: 直近90日 catches
    from datetime import timedelta
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
            if f and f not in ("不明", "欠航", "NULL"):
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

    # F1 (2026/05/22): 月別釣果実績セクション
    # data/V2/*.csv から最大13ヶ月分を集計してカード表示 (直近3ヶ月 + 折り畳み)
    _ma_area_slug = area_slug(area) if area else ""
    _ma_months = _ship_load_monthly_archive(name, max_months=13)
    monthly_archive_html = _ship_monthly_archive_section_html(_ma_months, name, area, _ma_area_slug)

    # F2 (2026/05/22): 週次レポート (HERO 直下)
    # 直近14日 catches を今週/前週分割集計・前年同月比較・来週大潮日・魚種別シーズン文
    _wr_weekly = _ship_load_weekly_data(name, today_dt)
    _wr_yoy = _ship_load_yoy_data(name, today_dt)
    _wr_tide = _ship_get_next_week_spring_tides(today_dt)
    weekly_report_html = _ship_weekly_report_section_html(_wr_weekly, _wr_yoy, _wr_tide, today_dt)

    # J-BCDE (2026/05/23): 25ヶ月データから 5 セクション自動生成 (月別キャッシュ)
    _jb_yearly = _ship_load_yearly_summary(name, today_dt)
    _jc_seasonal = _ship_load_seasonal_fish(name, today_dt)
    _jd_trophies = _ship_load_top_trophies(name, today_dt)
    _je_badges = _ship_load_auto_badges(name, today_dt, _jb_yearly, _jc_seasonal, _jd_trophies)
    yearly_summary_html = _ship_yearly_summary_section_html(_jb_yearly, name, area, _jc_seasonal, _jd_trophies)
    seasonal_fish_html = _ship_seasonal_fish_section_html(_jc_seasonal)
    trophy_rank_html = _ship_trophy_section_html(_jd_trophies)
    auto_badges_html = _ship_auto_badges_html(_je_badges)

    # H2 (T22): 空ページ判定 — 直近7日データがない場合のみ noindex
    # 旧: _SHIP_INFO 未登録でも noindex（T22 AdSense 対応）
    # 新: chowari 経由 114 船宿は ship_info 未登録でも釣果データがあればインデックス対象とする
    has_recent_data = "直近7日のデータがありません" not in recent_html
    has_ship_info = name in _SHIP_INFO
    is_empty_ship_page = not has_recent_data
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
    # 出船日数のみ表示（出船率・欠航日数は撤去・欠航データ取得不完全のため）
    overall_str = ""
    total_known = sail + cancel
    if sail > 0:
        overall_str = f"直近30日: 出船{sail}日 <span style=\"font-size:9px;opacity:.7\">(クロール記録ベース)</span>"

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
    if sail > 0:
        info_rows.append(f'<div class="info-row"><span class="info-label">直近30日</span><span class="info-val">出船{sail}日 <span style="color:var(--muted);font-size:11px">(当サイトのクロール記録ベース)</span></span></div>')

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
        phone_digits = _first_phone_for_tel(phone)
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
        phone_digits = _first_phone_for_tel(phone)
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
        _stale_banner_html() +
        '<header><div class="inner">'
        '<a href="/" class="site-logo"><span class="brand">船釣り<span>予想</span></span></a>'
        '<span style="font-size:11px;opacity:.5">funatsuri-yoso.com</span>'
        '</div></header>'
        '<nav class="gnav">'
        '<a href="/">今日の釣果</a>'
        '<a href="/fish/">魚種</a>'
        '<a href="/area/">エリア</a>'
        '<a href="/calendar.html">カレンダー</a>'
        '<a href="/komase-sim/">🎣 コマセsim<span class="nav-new">NEW</span></a>'
        + ('<a href="/forecast/" class="prem">有料プラン</a>' if SHOW_PAID_TEASER else '')
        + '</nav>'
    )
    bottom_nav = (
        '<div class="bn">'
        '<a href="/"><span class="i">🎣</span>釣果</a>'
        '<a href="/fish/"><span class="i">🐟</span>魚種</a>'
        '<a href="/area/"><span class="i">📍</span>エリア</a>'
        '<a href="/calendar.html"><span class="i">📅</span>カレンダー</a>'
        '<a href="/forecast/" class="prem"><span class="i">⭐</span>有料</a>'
        '</div>'
    )

    # メタ (F3: F1/F2 データを反映して指名検索 CTR を底上げ)
    # 今月実績 = _ma_months の先頭 (= 今月のはず・データなしなら fallback)
    # P4 (2026/05/31): 今月データなし時のデフォルト title を h1「{name}（{area}）の釣果」と
    # 統一（旧「釣果情報・船舶・予約方法 —」は冗長）。今月データありの場合は下で上書きされる。
    title = f"{name}（{area}）の釣果・船宿情報 | 船釣り予想"
    desc_parts = [f"{name}（{area}）の船釣り情報。"]
    _current_month_data = None
    if _ma_months:
        _curr_month_str = today_dt.strftime("%Y-%m")
        for _md in _ma_months:
            if _md.get("month") == _curr_month_str:
                _current_month_data = _md
                break
    if _current_month_data and _current_month_data.get("fish"):
        # 今月データあり: 鮮度+具体性をtitleに反映
        _cm_jp_month = today_dt.month
        _top_fish_obj = _current_month_data["fish"][0]
        _t_fish = _top_fish_obj["fish"]
        _t_cnt = _top_fish_obj["count"]
        _t_max_kg = _top_fish_obj.get("kg_max")
        _t_max_size = _top_fish_obj.get("size_max")
        _max_str = ""
        if _t_max_kg:
            _max_str = f"・最大{_t_max_kg}kg"
        elif _t_max_size:
            _max_str = f"・最大{_t_max_size}cm"
        title = f"{name}（{area}）最新釣果【{_cm_jp_month}月{_t_fish}{_t_cnt}便{_max_str}】| 船釣り予想"
        # description: 数値+前年比+構造紹介
        _desc_bits = [f"{name}（{area}）の最新釣果データ。"]
        _desc_bits.append(f"{today_dt.year}年{_cm_jp_month}月{_t_fish}{_t_cnt}便")
        _t_avg = _top_fish_obj.get("avg") or 0
        if _t_avg > 0:
            _desc_bits.append(f"・平均{_t_avg}匹")
        if _t_max_kg:
            _desc_bits.append(f"・最大{_t_max_kg}kg")
        elif _t_max_size:
            _desc_bits.append(f"・最大{_t_max_size}cm")
        _cm_trips = _current_month_data.get("trips") or 0
        if _cm_trips > 0:
            _desc_bits.append(f"・今月{_cm_trips}便出船")
        _desc_bits.append("。")
        # 前年比
        if _wr_yoy and _wr_yoy.get("last_year_fish_count"):
            _ly_cnt = _wr_yoy["last_year_fish_count"].get(_t_fish, 0)
            if _ly_cnt > 0:
                _diff = _t_cnt - _ly_cnt
                if _diff > 0:
                    _desc_bits.append(f"前年同月比+{_diff}便。")
                elif _diff < 0:
                    _desc_bits.append(f"前年同月比{_diff}便。")
        _desc_bits.append("13か月分の月別実績と週次傾向レポートを毎週更新。")
        desc = "".join(_desc_bits)[:160]
    else:
        # 今月データなし: 既存形式を維持 (fallback)
        if vessel.get("length_m") and vessel.get("capacity"):
            desc_parts.append(f"全長{vessel['length_m']}m・定員{vessel['capacity']}名。")
        if primary_fish:
            desc_parts.append(f"主要対象魚: {' ・ '.join(primary_fish[:4])}。")
        if sail > 0:
            desc_parts.append(f"直近30日の出船{sail}日。")
        desc = "".join(desc_parts)[:160]

    page_url = f"{SITE_URL}/ship/{slug}.html"

    # 明日の予測（有料・準備中チラ見せ）。SHOW_PAID_TEASER で表示制御（有料オープン時に復活）。
    ship_pred_teaser = "" if not SHOW_PAID_TEASER else (
        '<!-- 明日の予測（有料・準備中チラ見せ） -->\n'
        '<div style="background:linear-gradient(135deg,#f8f4ff,#f0eafa);border:2px solid var(--prem);border-radius:var(--r);padding:16px;margin-bottom:16px">\n'
        f'<h3 style="font-size:14px;color:var(--prem);margin-bottom:8px;text-align:center">{name}の明日の予測（準備中）</h3>\n'
        '<div style="background:var(--card);border:1px solid #e0d6f5;border-radius:8px;padding:12px;margin-bottom:8px;position:relative;overflow:hidden">\n'
        '<div style="filter:blur(5px);user-select:none;pointer-events:none">\n'
        '<div style="font-weight:700;color:var(--accent);font-size:13px">明日の主要魚種 — 信頼度 ★★★★★</div>\n'
        '<div style="font-size:15px;font-weight:800;color:var(--cta);margin-top:4px">XX〜XX匹</div>\n'
        '<div style="font-size:10px;color:var(--sub);margin-top:4px">気象条件・潮通し分析より推定</div>\n'
        '</div>\n'
        '<div style="position:absolute;inset:0;display:flex;align-items:center;justify-content:center;background:rgba(124,58,237,.06);font-size:13px;font-weight:700;color:var(--prem)">月額500円で見る予定</div>\n'
        '</div>\n'
        '</div>'
    )

    html = f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="icon" href="/favicon.ico" sizes="48x48"><link rel="apple-touch-icon" href="/apple-touch-icon.png">
{ship_noindex_tag}
<title>{title}</title>
<meta name="description" content="{desc}">
<link rel="canonical" href="{page_url}">
{_build_share_meta(
    title=title,
    desc=desc,
    url=page_url,
)}
{ld_json}
{'' if ship_noindex_tag else ADSENSE_TAG}
<link rel="stylesheet" href="../style.css">
<style>{_SHIP_EXTRA_CSS}</style>
</head>
<body>
{header_html}

<div class="ship-hero">
<h1><span class="sh-name">{name}</span><span class="sh-loc">（{area}）の釣果</span></h1>
{f'<div class="sh-main-fish">{" ・ ".join(primary_fish[:3])}</div>' if primary_fish else ''}
<div class="sh-badges">{badges_html}</div>
{auto_badges_html}
{f'<div class="sh-overall">{overall_str}</div>' if overall_str else ''}
</div>

<div class="c">
<div class="bread"><a href="../">トップ</a> &gt; <a href="../area/{area_slug_str}.html">{area}</a> &gt; {name}</div>
{_build_share_buttons(
    share_text=f"{name}（{area}）の船宿情報 | 船釣り予想",
    share_url=page_url,
)}

{weekly_report_html}

{yearly_summary_html}

{seasonal_fish_html}

{trophy_rank_html}

<h2 class="st">基本情報</h2>
<div class="info-box">
{"".join(info_rows)}
</div>

{vessel_html}

{reservation_html}

{season_html}

<h2 class="st">最近の釣果実績（直近7日・船宿実績）</h2>
{recent_html}

{'' if ship_noindex_tag else _SHIP_AD_RECT}

{ship_pred_teaser}

{area_rank_html}

<div class="contact-cta">
<h3>{name}で釣行を計画する</h3>
<p>予約は船宿へ直接お電話ください。最新の料金・空席・出船判断はすべて船宿が把握しています。</p>
{phone_cta_block}
</div>

{'' if ship_noindex_tag else _SHIP_AD_INS}

{monthly_archive_html}

{faq_html}

</div>

<footer>
<a href="../pages/privacy.html">プライバシーポリシー</a> · <a href="../pages/terms.html">利用規約</a> · <a href="../pages/about.html">サイトについて</a> · <a href="../pages/contact.html">お問い合わせ</a> · <a href="../pages/faq.html">よくある質問</a><br>
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
    # fishing_v_zero=True（fishing-v.jp で釣果0件確認済み）はスキップ
    # ただし source_priority に "chowari" 等の代替ソースがあれば対象に含める
    # （2026/05/17 chowari 経由船宿 150隻対応・元の T31 fishing_v_zero=True スキップは
    #  「釣りビジョン以外にデータ取得手段なし」前提だったが、chowari クロール導入で
    #  fishing_v_zero でも chowari 経由データがある船宿が登場）
    def _has_alt_source(s):
        sp = s.get("source_priority") or []
        return any(src != "fishing_v" for src in sp)
    target_ships = [
        s for s in SHIPS
        if s.get("romaji_slug")
        and not s.get("exclude")
        and (not s.get("fishing_v_zero") or _has_alt_source(s))
    ]
    today_dt = datetime.now(JST).replace(tzinfo=None)
    # 2026/05/13 T34拡張: valid_catches を直近7日窓に絞る。
    # fishing-v.jp の船宿ページは最新ページ(pageID=1)を返す仕様だが、
    # シーズンオフ魚種・休止中船宿では数ヶ月前の釣果が最新ページに残ったまま
    # 更新されない場合があり、当日クロール結果に混入する。
    # T34 (build_fish_pages) と同じ7日窓フィルタを ship にも適用。
    # 注: T34本体は data_recent 別名だが、ここでは下流の処理が全て同じ変数名を
    # 使うため破壊的上書きで簡潔化。crawler.py 内で本関数の呼び出しは1箇所のみ。
    _cutoff_date_T34_ship = (today_dt - timedelta(days=6)).strftime("%Y/%m/%d")  # today含めて7日
    catches = [c for c in catches if c.get("date", "") >= _cutoff_date_T34_ship]
    # 2026/05/19: chowari 経由 / 遅延到着データの補完（build_area_pages と同じ理由）
    try:
        _recent7_ship = _load_recent_catches_for_index(today_dt, days=7)
    except Exception:
        _recent7_ship = []
    _seen_ship = {(c.get("ship"), c.get("date"), c.get("fish_raw", "")) for c in catches}
    for _c in _recent7_ship:
        _k = (_c.get("ship"), _c.get("date"), _c.get("fish_raw", ""))
        if _k not in _seen_ship:
            _seen_ship.add(_k)
            catches.append(_c)
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


def build_ship_redirects():
    """旧 chowari-NNNNN.html → 新slug への meta refresh redirect HTML を生成。

    背景: 2026/05/24 chowari-NNNNN 形式の暫定 slug 114件を意味ある英語 slug に
    刷新した。Google SC で chowari-00454.html 等が index 済の可能性があり、
    canonical を新 URL に向けつつ meta refresh で誘導する。

    入力: crawl/chowari_slug_redirect_map.json （rename_chowari_slugs.py 出力）
    出力: docs/ship/chowari-NNNNN.html （redirect HTML で上書き）
    """
    redirect_path = os.path.join(_BASE_DIR, "crawl", "chowari_slug_redirect_map.json")
    if not os.path.exists(redirect_path):
        return 0
    try:
        with open(redirect_path, encoding="utf-8") as f:
            redirect_map = json.load(f)
    except Exception as e:
        print(f"  redirect map 読込失敗: {e}")
        return 0

    out_dir = os.path.join(WEB_DIR, "ship")
    os.makedirs(out_dir, exist_ok=True)
    generated = 0
    for old_slug, new_slug in redirect_map.items():
        new_url = f"https://funatsuri-yoso.com/ship/{new_slug}.html"
        html = f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta http-equiv="refresh" content="0;url={new_url}">
<link rel="canonical" href="{new_url}">
<meta name="robots" content="noindex,follow">
<title>移動しました | 船釣り予想</title>
</head>
<body>
<p>このページは <a href="{new_url}">{new_url}</a> に移動しました。自動的に遷移しない場合はリンクをクリックしてください。</p>
<script>location.replace("{new_url}");</script>
</body>
</html>"""
        with open(os.path.join(out_dir, f"{old_slug}.html"), "w", encoding="utf-8") as f:
            f.write(html)
        generated += 1
    print(f"船宿redirect生成: {generated} 件 → docs/ship/chowari-*.html (→ 新slug)")
    return generated


# ============================================================
# Kanso由来ポイント area_pages（2026/05/17 追加）
# build_area_pages は ships.json area のみ対象だが、hist_rows の
# point_place1/2/3（剣崎沖・大原沖・鹿島沖等）も独立 area_pages として
# 簡易生成して SEO/UX を強化する
# ============================================================
def build_point_pages(hist_rows, crawled_at=""):
    """Kanso由来主要ポイントの area_pages を docs/area/ に簡易生成する。
    対象: area_romaji_map.json にスラッグがあり ships.json area に含まれない
          point_place の上位40件（point_place1/2/3 のいずれかで N>=10 件出現）
    出力: docs/area/{slug}.html （既存 area_pages と同ディレクトリ・URL）
    """
    from collections import Counter
    out_dir = os.path.join(WEB_DIR, "area")
    os.makedirs(out_dir, exist_ok=True)

    # 既存 ships.json area（除外対象）
    ship_areas = set(s.get("area") for s in SHIPS if s.get("area"))

    # hist_rows から point_place 集計
    point_counter = Counter()
    for r in hist_rows:
        for k in ("point_place1", "point_place2", "point_place3"):
            p = (r.get(k) or "").strip()
            if not p or p == "NULL" or len(p) > 15:
                continue
            # 既存 area_pages と被るものは除外（重複生成防止）
            if p in ship_areas:
                continue
            # area_romaji_map にスラッグがあるもののみ
            if p not in _AREA_ROMAJI:
                continue
            point_counter[p] += 1

    target_points = [p for p, n in point_counter.most_common(40) if n >= 10]
    print(f"build_point_pages: 対象ポイント {len(target_points)}件 (Kanso由来)")

    today_dt = datetime.now(JST).replace(tzinfo=None)
    cutoff_365 = (today_dt - timedelta(days=365)).strftime("%Y/%m/%d")

    generated = 0
    for point in target_points:
        slug = _AREA_ROMAJI[point]
        # このポイントを使う hist_rows レコード抽出
        point_rows = [
            r for r in hist_rows
            if (r.get("point_place1") == point
                or r.get("point_place2") == point
                or r.get("point_place3") == point)
            and r.get("is_cancellation") != "1"
            and r.get("date", "") >= cutoff_365
        ]
        if not point_rows:
            continue

        # 主要魚種 TOP5
        fish_cnt = Counter()
        ship_cnt = Counter()
        port_cnt = Counter()
        for r in point_rows:
            tm = r.get("tsuri_mono", "") or ""
            if tm and tm != "NULL":
                fish_cnt[tm] += 1
            s = r.get("ship", "")
            if s:
                ship_cnt[s] += 1
            a = r.get("area", "")
            if a:
                port_cnt[a] += 1

        top_fish = fish_cnt.most_common(5)
        top_ships = ship_cnt.most_common(8)
        top_ports = port_cnt.most_common(3)
        n_records = len(point_rows)
        n_ships = len(ship_cnt)
        n_ports = len(port_cnt)

        # HTML 生成（既存 area_pages 簡易版）
        # GSC 404 修正 (2026/05/28): docs/fish/{slug}.html が実在しない魚種は
        # リンクではなく span でテキスト表示（アカイカ等 build_fish_pages 対象外の魚種）
        def _fish_name_or_link(_f):
            _slug = _FISH_ROMAJI.get(_f, _f)
            _fp = os.path.join(WEB_DIR, f"fish/{_slug}.html")
            if os.path.exists(_fp):
                return f'<a href="../fish/{_slug}.html">{_f}</a>'
            return _f
        fish_items = "".join(
            f'<div class="sl-item"><div class="sl-top">'
            f'<span class="sl-name">{_fish_name_or_link(f)}</span>'
            f'<span class="sl-detail">過去1年 {n}件</span></div></div>'
            for f, n in top_fish
        )
        fish_card = f'<div class="sl-card">{fish_items}</div>' if fish_items else ""

        ship_items = "".join(
            f'<div class="sl-item"><div class="sl-top">'
            f'<span class="sl-name">{_ship_link(s, depth=1)}</span>'
            f'<span class="sl-detail">過去1年 {n}件</span></div></div>'
            for s, n in top_ships
        )
        ship_card = f'<div class="sl-card">{ship_items}</div>' if ship_items else ""

        port_items = "".join(
            f'<div class="sl-item"><div class="sl-top">'
            f'<span class="sl-name"><a href="../area/{_AREA_ROMAJI.get(p, p)}.html">{p}</a></span>'
            f'<span class="sl-detail">過去1年 {n}件</span></div></div>'
            for p, n in top_ports if _AREA_ROMAJI.get(p)
        )
        port_card = f'<div class="sl-card">{port_items}</div>' if port_items else ""

        # FAQ
        top_fish_str = "・".join(f for f, _ in top_fish[:3])
        top_ship_str = "・".join(s for s, _ in top_ships[:3])
        faq_html = (
            f'<details><summary>{point}でよく釣れる魚は？</summary>'
            f'<p class="faq-ans">過去1年で{point}で記録された主要魚種は{top_fish_str}です。'
            f'計{len(fish_cnt)}魚種・{n_records}件の釣果記録があります。</p></details>'
            f'<details><summary>{point}に出船する船宿は？</summary>'
            f'<p class="faq-ans">過去1年で{point}を利用した船宿は{n_ships}船宿で、'
            f'主な出船港は{"、".join(p for p, _ in top_ports[:3])}です。'
            f'件数の多い順に{top_ship_str}が実績豊富です。</p></details>'
        )

        # T40: 全ポイントページは構造的薄ページ → noindex 付与 + sitemap 除外
        _AREA_POINT_NOINDEX_SLUGS.add(slug)

        # 簡易テンプレート
        html = f"""<!doctype html><html lang="ja"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="icon" href="/favicon.ico" sizes="48x48"><link rel="apple-touch-icon" href="/apple-touch-icon.png">
<title>{point}の釣果情報・船宿一覧 | 船釣り予想</title>
<meta name="description" content="関東の釣り場「{point}」の過去1年の釣果データ。{n_records}件・{n_ships}船宿・主要魚種{top_fish_str}。">
<meta name="robots" content="noindex, follow">
<meta property="og:title" content="{point}の釣果情報">
<meta property="og:description" content="{point}を利用する{n_ships}船宿・{n_records}件の過去釣果サマリー">
<meta property="og:url" content="{SITE_URL}/area/{slug}.html">
<meta property="og:type" content="website">
<meta property="og:site_name" content="船釣り予想">
<meta property="og:image" content="{SITE_URL}/ogp-default.png">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:site" content="@funatsuri_yoso">
<link rel="canonical" href="{SITE_URL}/area/{slug}.html">
<link rel="stylesheet" href="../style.css">
<script async src="https://www.googletagmanager.com/gtag/js?id=G-LS469BTBBX"></script>
<script>window.dataLayer=window.dataLayer||[];function gtag(){{dataLayer.push(arguments);}}gtag("js",new Date());gtag("config","G-LS469BTBBX");</script>
</head><body>
<header class="hd"><a href="../" class="hd-name">船釣り予想</a><div class="hd-sub">{crawled_at} 更新</div></header>
<main>
<div class="area-hero"><h2>{point}</h2><div class="ah-sub">釣り場ポイント情報</div>
<div class="ah-m">過去1年 <strong>{n_records}件</strong><small> {n_ships}船宿・{n_ports}港経由</small></div></div>
<h2 class="st">主要魚種（過去1年） <span class="tag free">無料</span></h2>{fish_card}
<h2 class="st">出船する船宿（過去1年） <span class="tag free">無料</span></h2>{ship_card}
<h2 class="st">主な出船港 <span class="tag free">無料</span></h2>{port_card}
<h2 class="st">{point} よくある質問</h2><div class="faq">{faq_html}</div>
<div class="share-bar"><a href="https://twitter.com/intent/tweet?url={SITE_URL}/area/{slug}.html&text={point}の釣果情報" target="_blank" rel="noopener">Xでシェア</a></div>
</main>
<footer class="ft"><a href="../">トップへ戻る</a> | <a href="../area/">エリア一覧</a> | <a href="../fish/">魚種一覧</a></footer>
</body></html>"""

        with open(os.path.join(out_dir, f"{slug}.html"), "w", encoding="utf-8") as f:
            f.write(html)
        generated += 1

    print(f"build_point_pages: {generated} 件生成 → docs/area/")
    return generated


# ============================================================
# 月報生成（build_monthly_pages / build_monthly_index）
# ============================================================

# ── 月報対象魚種設定 ──
MONTHLY_FISH_CONFIG = {
    "アジ": {
        "unit": "匹", "type_metric": "cm",
        "romaji": "aji",
        "og_image": "https://funatsuri-yoso.com/assets/fish/aji/aji_photo.png",
        "area_ports": {
            "東京湾": [("金沢八景", "kanazawa-hakkei"), ("横浜新山下", "yokohama-shinyamashita"), ("横浜本牧", "yokohama-honmoku"), ("久比里", "kubiri"), ("鴨居大室", "kamoi-omuro"), ("小柴", "koshiba"), ("浦安", "urayasu"), ("金沢漁港", "kanazawa-gyoko"), ("平和島", "heiwajima")],
            "内房": [("金谷", "kanaya")],
            "相模湾・伊豆": [("小坪", "kotsubo"), ("茅ヶ崎", "chigasaki"), ("平塚", "hiratsuka"), ("腰越", "koshigoe"), ("片瀬", "katase-gyoko"), ("佐島", "sajima")],
            "駿河湾・遠州灘": [("福田", "fukuda"), ("御前崎", "omaezaki")],
            "外房": [("大原", "ohara"), ("片貝", "katakai")],
            "鹿島・茨城": [("日立久慈", "hitachi-kuji"), ("鹿島", "kashima"), ("大洗", "oarai")],
        },
        "narratives": {
            "東京湾": {"trend": "本月の主役エリア。金沢八景の米元釣船店38便・荒川屋28便、横浜（新山下の渡辺釣船店35便・本牧の長崎屋）、久比里・鴨居大室・小柴・浦安まで広く出船した。久比里の巳之助丸が5/16・5/19にMax167〜181匹の束釣りを連発し数を牽引、横浜本牧の長崎屋も5/13にMax155匹を記録。Max平均は全エリア最高水準で数のエリア。", "tackle": "LTアジ（ライトタックル）・ビシアジが主流。アンドンビシ＋ウィリーまたは付けエサ。タナをこまめに取り直す手返し勝負。"},
            "内房": {"trend": "金谷の光進丸24便・勘次郎丸20便がほぼ専業。数より型のエリアで、さえむ丸・光進丸が5月上旬（5/6〜9）に52〜53cmの大アジ（月間最大）を上げた。", "tackle": "ビシアジ・コマセ釣り。金谷沖の深場で良型を狙う。"},
            "相模湾・伊豆": {"trend": "小坪の洋征丸19便・茅ヶ崎のちがさき丸16便・平塚の庄治郎丸が中心。Max平均は東京湾より控えめだが、49cm級の良型が交じった。腰越・片瀬など小港からの近場LTアジも多い。", "tackle": "LTアジ・コマセ＋ウィリー。手前の根周りを丁寧に探る。"},
            "外房": {"trend": "太幸丸・勇幸丸など出船は少なめ。Max平均は控えめだが45cm級の型が交じる。アジ専業より五目・イサキ便の混じりが主体だった。", "tackle": "コマセ釣り中心。"},
            "鹿島・茨城": {"trend": "日立久慈の大貫丸ほか出船は限られる。Max平均は高い数値だが10便とサンプルが少なく参考値。", "tackle": "ビシアジ・LTアジ。北部の浅場で数を狙う。"},
            "駿河湾・遠州灘": {"trend": "福田港の啓秀丸17便が中心。Max平均は低めだが（釣果数の記録欠損の影響もあり）、40cm級の型は出ている。", "tackle": "コマセ・ビシ釣り。遠州灘の数狙い。"},
        },
        "consideration_title": "2026年5月の海況とアジ釣果の関係",
        "consideration_html": (
            "2026年5月のアジ釣果は全{total}便、前年同月{prev_total}便から{yoy:+.1f}%と増加した。関東全域で最も出船数の多い基幹ターゲットで、本月も88船宿が報告を寄せている。日別Max平均は{cmax}匹、月間最大は内房・金谷の53cmだった。"
            "主役は東京湾。金沢八景の米元釣船店・荒川屋、横浜（新山下・本牧）、久比里・鴨居大室・小柴・浦安まで広く出船し、久比里の巳之助丸が5/16・5/19にMax167〜181匹の束釣りを連発、横浜本牧の長崎屋も5/13にMax155匹と数を牽引した。"
            "型では内房・金谷が際立ち、さえむ丸・光進丸が5月上旬に52〜53cmの大アジを上げた。相模湾・伊豆も小坪〜茅ヶ崎で40cm台後半の良型が交じっている。"
            "釣果の日別の山は5/7〜13に集中し、中潮〜大潮の潮回りで群れが濃くなる傾向が見られた。外道はイシモチ・サバ・クロダイ・カサゴが目立ち、初夏らしい多魚種の混じりとなった月である。"
        ),
        "forecast_intro": "過去2年の6月アジ実績は以下の通り。6月も周年安定するアジの好機が続き、5月並み〜やや増の傾向。",
        "forecast_items": [
            "<strong>全体:</strong> 6月も関東全域で最も安定して数が狙えるターゲット。梅雨の合間を突けば束釣りも継続見込み。",
            "<strong>東京湾:</strong> 金沢八景・横浜・久里浜のLTアジが本番。巳之助丸クラスの束釣り日も期待できる。",
            "<strong>内房:</strong> 金谷沖の大アジ（40〜50cm級）の型シーズンが継続見込み。",
            "<strong>相模湾・伊豆:</strong> 小坪〜茅ヶ崎の近場LTアジが安定。数は東京湾に譲るが手軽さで人気。",
            "<strong>鹿島・茨城／駿河湾:</strong> 出船は限られるが、群れに当たれば数が伸びる時期。",
        ],
        "related_fish": ["マダイ", "イサキ"],
        "related_fish_area": [("金沢八景", "kanazawa-hakkei"), ("金谷", "kanaya")],
    },
    "マダイ": {
        "unit": "匹", "type_metric": "kg",
        "romaji": "madai",
        "og_image": "https://funatsuri-yoso.com/assets/fish/madai/madai_photo.png",
        "area_ports": {
            "東京湾": [("松輪江奈", "matsuwa-ena"), ("松輪間口", "matsuwa-maguchi"), ("久里浜", "kurihama"), ("金沢八景", "kanazawa-hakkei"), ("小柴", "koshiba")],
            "内房": [("富浦", "tomiura"), ("保田", "hota"), ("金谷", "kanaya"), ("館山", "tateyama")],
            "相模湾・伊豆": [("佐島", "sajima"), ("茅ヶ崎", "chigasaki"), ("小田原早川", "hayakawa"), ("網代", "ajiro"), ("下田", "shimoda"), ("大磯", "ooiso"), ("平塚", "hiratsuka")],
            "駿河湾・遠州灘": [("御前崎", "omaezaki"), ("由比", "yui"), ("沼津", "numazu"), ("田子の浦", "tagonoura")],
            "外房": [("飯岡", "iioka"), ("大原", "ohara"), ("天津", "amatsu"), ("片貝", "katakai"), ("御宿岩和田", "onjuku-iwawada")],
            "鹿島・茨城": [("鹿島", "kashima"), ("日立久慈", "hitachi-kuji"), ("大洗", "ooarai")],
        },
        "narratives": {
            "東京湾": {"trend": "湾口の松輪・久里浜が出船の中心。Max平均は全エリア最低水準で、中盤以降の南西風で波が立ち食い渋りが目立った。", "tackle": "コマセビシ釣りが主流。神奈川県条例により湾内ではコマセ一本。ハリス3〜4号・3m前後。"},
            "内房": {"trend": "出船船宿は少なくデータ蓄積が薄い月。共栄丸が継続的に出船。", "tackle": "コマセビシ・一つテンヤ併用。"},
            "相模湾・伊豆": {"trend": "全体は控えめだが、恒丸（大磯港）が型物混じりの好釣果。中盤の中潮タイミングで一発当たった様子。", "tackle": "コマセビシ中心・一部一つテンヤ。葉山〜茅ヶ崎は浅場・小田原から伊豆は深場と釣り方が変わる。"},
            "駿河湾・遠州灘": {"trend": "月間最大の90cm級が伊達丸（御前崎）で上がった。深場狙いの遠州灘テンヤで型物が連発。", "tackle": "一つテンヤが主流。遠州灘の深場で重めのテンヤ・タングステン系。"},
            "外房": {"trend": "本月の主役エリア。幸丸（飯岡）が爆釣連発・梅花丸（大原）も安定。乗っ込みのピーク末期で大原沖の浅場が好調。", "tackle": "一つテンヤが主流。3〜10号のテンヤにエビ餌。底取り後の小突き＋誘いで乗っ込み個体を狙う。"},
            "鹿島・茨城": {"trend": "東京湾と並ぶ水準。鹿島港・日立久慈港の北部沖が中心。幸栄丸がハイ便数で月間全体の底上げに貢献。", "tackle": "一つテンヤ・タイラバ混在。鹿島は北沖の深場ポイントが多くタイラバ80〜120g。"},
        },
        "consideration_title": "2026年5月の海況とマダイ釣果の関係",
        "consideration_html": (
            "2026年5月のマダイ釣果は全{total}便と前年比{yoy:+.1f}%で推移した。月中盤の大潮タイミング（5/11〜14前後）では外房・大原〜飯岡で記録的な束釣りが連発した。"
            "とくに5/30の幸丸（飯岡港）の19匹は、乗っ込み終盤のピーク食いを捉えた一日で、産卵接岸群が浅場に差した瞬間と推察される。"
            "一方で東京湾は全エリア最低水準のMax平均と低調だった。これは5月後半に南西風が連日吹き付け、湾口の松輪・剣崎ポイントで波が立ち食い渋りが目立った影響と考えられる。"
            "対照的に駿河湾の伊達丸（御前崎）は月間最大の90cm級を上げており、深場の一つテンヤで型物に的を絞れた数日があった。水温の動きを見ると、2026年5月の駿河湾西部は18〜20℃の理想帯にとどまり、産卵で浅場に差した個体を狙う釣りと、深場の落ち個体を狙う釣りの両方が成立した月だった。"
            "潮回りでは大潮〜中潮の食いが顕著で、長潮・若潮では各エリアでツ抜けすら難しい便も散見された。乗っ込み終盤の食い渋り時期と重なり、後半は型を狙う釣りに切り替えた船が好結果を残している。"
        ),
        "forecast_intro": "過去2年の6月マダイ実績は以下の通り。5月と同水準〜やや増の傾向。",
        "forecast_items": [
            "<strong>全体:</strong> 梅雨入りで欠航日が増えるが、産卵後の落ちダイ狙いで型物実績が上がる時期。",
            "<strong>外房:</strong> 5月の主役からシフトし、深場の落ちダイ狙いに切替期。便数はやや減るが型物の比率が上がる見込み。",
            "<strong>東京湾:</strong> 5月の南西風影響から脱し、湾口の松輪エリアで安定釣果が見込める。",
            "<strong>駿河湾・遠州灘:</strong> 御前崎・遠州灘の深場テンヤが本格期。90cm級の型物実績は6月も継続見込み。",
            "<strong>鹿島・茨城:</strong> 北沖の安定釣果が継続。タイラバ・テンヤ問わず2桁実績の便数が増える時期。",
        ],
        "related_fish": ["マルイカ"],
        "related_fish_area": [("飯岡", "iioka"), ("大原", "ohara")],
    },
    "マルイカ": {
        "unit": "杯", "type_metric": "cm", "size_term": "胴長",
        "romaji": "maruika",
        "og_image": "https://funatsuri-yoso.com/assets/fish/maruika/maruika_photo.png",
        "area_ports": {
            "東京湾": [("松輪間口", "matsuwa-maguchi"), ("久比里", "kubiri"), ("鴨居大室", "kamoi-oomuro")],
            "内房": [],
            "相模湾・伊豆": [("小網代", "koajiro"), ("葉山あぶずり", "hayama-abuzuri"), ("平塚", "hiratsuka"), ("長井", "nagai"), ("佐島", "sajima")],
            "駿河湾・遠州灘": [("沼津", "numazu")],
            "外房": [],
            "鹿島・茨城": [],
        },
        "narratives": {
            "東京湾": {"trend": "松輪間口の喜平治丸が際立った。胴長40cm級の良型を5/9・5/12・5/26と繰り返し上げ、数（最大121杯）と型を両立。直結直ブラの感度釣りがハマった。", "tackle": "直結（直ブラ）仕掛けが主流。スッテ5〜7本・中オモリ。乗りの渋い日は浮きスッテで誘い上げ。"},
            "内房": {"trend": "本月の出船報告なし。マルイカは三浦〜相模湾が主漁場で内房は対象外。", "tackle": "—"},
            "相模湾・伊豆": {"trend": "本月の主役エリア。小網代の翔太丸が5/14に132杯の大爆釣。葉山あぶずり・平塚でも安定。たいぞう丸・大和丸・翔太丸の3船が各19便と高稼働で相模湾を牽引した。", "tackle": "ブランコ仕掛け・直結併用。スッテへの抱きを目感度・手感度で取る繊細な釣り。乗っ込み群は浅場のタナを丁寧に。"},
            "駿河湾・遠州灘": {"trend": "沼津・秀丸の6便のみと出船が限られ、日別の数値（Max60杯超の日もあり）は1船宿・6便の参考値で振れ幅が大きい。マルイカの本格シーズンは別時期。", "tackle": "ブランコ仕掛け中心。"},
            "外房": {"trend": "本月の出船報告なし。マルイカ（ケンサキ系）の主漁場外。", "tackle": "—"},
            "鹿島・茨城": {"trend": "本月の出船報告なし。", "tackle": "—"},
        },
        "consideration_title": "2026年5月の海況とマルイカ釣果の関係",
        "consideration_html": (
            "2026年5月のマルイカ釣果は全{total}便、前年同月{prev_total}便から{yoy:+.1f}%と倍増した。出船数の増加に加え、春の乗っ込み群が早めに接岸した好シーズンを反映している。日別Max平均は{cmax}杯で、束に迫る日も複数あった。"
            "主役は相模湾。小網代の翔太丸が5/14に132杯の大爆釣を記録し、葉山あぶずり・平塚でも安定した数が出た。たいぞう丸・大和丸・翔太丸の3船が各19便と高稼働で、相模湾全体を牽引した。"
            "東京湾では松輪間口の喜平治丸が際立った。胴長40cm級の良型を5/9・5/12・5/26と繰り返し上げ、数（最大121杯）と型を両立させた。直結直ブラの感度釣りがハマった形である。"
            "水温は内海20.9℃・外海20.7℃と、マルイカの適水温帯に乗った。大潮回りで群れが固まった日に束釣りが集中する一方、潮の緩い日は拾い釣りとなり、日較差が大きかった。これはマルイカが群れ依存の強いターゲットであることの裏返しで、「群れに当たれば束、外せば一桁」という本種らしい分布を示した月だった。"
        ),
        "forecast_intro": "過去2年の6月マルイカ実績は以下の通り。6月は最盛期後半で、年により数の振れ幅が大きい。",
        "forecast_items": [
            "<strong>全体:</strong> 6月はマルイカ最盛期の後半。胴長が育って型は上向く。梅雨の欠航を挟みつつ数は5月並み〜やや増の見込み。",
            "<strong>相模湾・伊豆:</strong> 引き続き主戦場。小網代・葉山で群れが続く限り束狙いが可能。凪の日を狙い撃ちたい。",
            "<strong>東京湾:</strong> 松輪間口で40cm級の良型シーズンが継続。型を狙うなら6月前半が本命。",
            "<strong>駿河湾・遠州灘:</strong> 沼津で細々。本格化は別シーズンで、6月は数が読みにくい。",
            "<strong>外房・鹿島・内房:</strong> マルイカの主漁場外。6月も出船は見込み薄。",
        ],
        "related_fish": ["マダイ"],
        "related_fish_area": [("小網代", "koajiro"), ("葉山あぶずり", "hayama-abuzuri")],
    },
    "ムギイカ": {
        "unit": "杯", "type_metric": "cm", "size_term": "胴長",
        "romaji": "mugiika",
        "og_image": "https://funatsuri-yoso.com/assets/fish/mugiika/mugiika_photo.png",
        "area_ports": {
            "東京湾": [],
            "内房": [],
            "相模湾・伊豆": [("小田原早川", "odawara-hayakawa"), ("長井", "nagai"), ("葉山あぶずり", "hayama-abuzuri"), ("平塚", "hiratsuka"), ("久料", "kuryo")],
            "駿河湾・遠州灘": [("沼津内港", "numazu-naiko"), ("沼津静浦", "numazu-shizuura")],
            "外房": [("天津", "amatsu")],
            "鹿島・茨城": [],
        },
        "narratives": {
            "東京湾": {"trend": "本月のムギイカ出船報告なし。ムギイカ（スルメイカ若魚）は相模湾〜駿河湾が主漁場で、東京湾は対象外。", "tackle": "—"},
            "内房": {"trend": "本月の出船報告なし。", "tackle": "—"},
            "相模湾・伊豆": {"trend": "型のエリア。小田原早川の平安丸が12便と最も高稼働で、長井のはら丸が5/3・5/6・5/13と胴長35cm（月間最大）の良型を重ねた。葉山あぶずりの長三朗丸も5/6にMax84杯と数を出している。数の駿河湾に対し、こちらは胴長の伸びた個体が交じった。", "tackle": "ブランコ仕掛けが主流（スルメイカ若魚）。スッテ5〜7本にプラヅノ併用。乗りの渋い日は誘い上げで抱かせる。"},
            "駿河湾・遠州灘": {"trend": "本月の主役エリア（59便）。沼津の秀丸34便・第八幸松丸25便のほぼ2船体制で数を一手に牽引した。第八幸松丸が5/25にMax148杯・5/29にMax125杯、秀丸も5/13にMax134杯と束超えを連発。沼津沖の群れに当たった日は爆釣となった。", "tackle": "ブランコ仕掛け中心。沼津沖は数狙いでスッテ多点。群れが濃い日は手返し勝負。"},
            "外房": {"trend": "天津の第八鶴丸が1便のみ（Max18杯）と参考値。ムギイカの主漁場は相模湾〜駿河湾で、外房は本格的な狙いものにならなかった。", "tackle": "ブランコ仕掛け。"},
            "鹿島・茨城": {"trend": "本月の出船報告なし。", "tackle": "—"},
        },
        "consideration_title": "2026年5月の海況とムギイカ釣果の関係",
        "consideration_html": (
            "2026年5月のムギイカ釣果は全{total}便、前年同月{prev_total}便から{yoy:+.1f}%と便数を大きく減らした。出船が沼津の2船・相模湾の特定船に絞られ、母数が縮んだ月である。日別Max平均は{cmax}杯で、群れに当たった日は束を超えた。"
            "数の主役は駿河湾。沼津の秀丸・第八幸松丸のほぼ2船体制で、第八幸松丸が5/25にMax148杯、秀丸が5/13にMax134杯と束超えを連発した。沼津沖の群れに乗った日に釣果が集中している。"
            "型では相模湾が際立ち、長井のはら丸が5月上旬から胴長35cm（月間最大）の良型を重ねた。小田原早川の平安丸も12便と高稼働で数・型を両立している。"
            "水温は18.7〜21.1℃とムギイカの適水温帯に乗り、大潮回りで群れが固まった日に束釣りが出る一方、潮の緩い日は拾い釣りとなった。群れ依存の強い本種らしく日較差が大きい月だった。"
        ),
        "forecast_intro": "過去2年の6月ムギイカ実績は以下の通り。6月は群れが育って数・型とも伸びやすく、年により振れ幅が大きい。",
        "forecast_items": [
            "<strong>全体:</strong> 6月はムギイカが育つ時期。胴長が伸びて型は上向き、群れに当たれば数も5月並み〜やや増の見込み。",
            "<strong>駿河湾・遠州灘:</strong> 沼津沖が引き続き主戦場。群れが続けば束狙いが可能で、凪の日を狙い撃ちたい。",
            "<strong>相模湾・伊豆:</strong> 小田原早川・長井で胴長の伸びた良型シーズンが継続見込み。",
            "<strong>東京湾・外房・鹿島・内房:</strong> ムギイカの主漁場外。6月も出船は見込み薄。",
        ],
        "related_fish": ["スルメイカ", "マルイカ"],
        "related_fish_area": [("沼津内港", "numazu-naiko"), ("長井", "nagai")],
    },
    "スルメイカ": {
        "unit": "杯", "type_metric": "cm", "size_term": "胴長",
        "romaji": "surumeika",
        "og_image": "https://funatsuri-yoso.com/assets/fish/surumeika/surumeika_photo.png",
        "area_ports": {
            "東京湾": [("松輪間口", "matsuwa-maguchi")],
            "内房": [],
            "相模湾・伊豆": [("長井新宿", "nagai-shinjuku"), ("長井", "nagai"), ("長井漆山", "nagai-urushiyama"), ("小田原早川", "odawara-hayakawa"), ("葉山あぶずり", "hayama-abuzuri")],
            "駿河湾・遠州灘": [],
            "外房": [("勝浦川津", "katsuura-kawazu")],
            "鹿島・茨城": [],
        },
        "narratives": {
            "東京湾": {"trend": "松輪間口の喜平治丸が9便で専業。胴長40cm（月間最大）の良型を5/28に上げ、5/9にはMax55杯と数も出した。直結直ブラの感度釣りで型を引き出している。", "tackle": "直結（直ブラ）・ブランコ仕掛け併用。スッテ5〜7本・中オモリ。良型は誘い上げでフッキング。"},
            "内房": {"trend": "本月のスルメイカ出船報告なし。", "tackle": "—"},
            "相模湾・伊豆": {"trend": "本月の主役エリア（60便）。長井の3船（栃木丸21便・儀兵衛丸18便・春盛丸8便）が高稼働で数を牽引した。小田原早川の平安丸が5/27にMax79杯と月間トップの数を記録、長三朗丸（葉山）も5/13にMax63杯。胴長38cm級の良型も交じった。", "tackle": "ブランコ仕掛け・直結併用。長井沖はスッテ多点で数狙い。夜〜早朝の時合いを丁寧に。"},
            "駿河湾・遠州灘": {"trend": "本月の出船報告なし。", "tackle": "—"},
            "外房": {"trend": "勝浦川津の不動丸が1便のみ（Max22杯・胴長40cm）と参考値。スルメイカの主漁場は相模湾で、外房は単発にとどまった。", "tackle": "ブランコ仕掛け。"},
            "鹿島・茨城": {"trend": "本月の出船報告なし。", "tackle": "—"},
        },
        "consideration_title": "2026年5月の海況とスルメイカ釣果の関係",
        "consideration_html": (
            "2026年5月のスルメイカ釣果は全{total}便、前年同月{prev_total}便から{yoy:+.1f}%とほぼ前年並みで推移した。日別Max平均は{cmax}杯で、群れに乗った日は束に迫った。"
            "主役は相模湾。長井の栃木丸・儀兵衛丸・春盛丸の3船が高稼働で数を牽引し、小田原早川の平安丸が5/27にMax79杯と月間トップの数を記録した。長三朗丸（葉山）も5/13にMax63杯と続いている。"
            "東京湾では松輪間口の喜平治丸が専業で、5/28に胴長40cm（月間最大）の良型を上げ、5/9にはMax55杯と数も両立した。直結直ブラの感度釣りがはまった形である。"
            "水温は18.4〜19.5℃とスルメイカの適水温帯で、中潮〜大潮で群れが濃くなる傾向が見られた。群れ依存が強く、潮の緩い日は拾い釣りとなる日較差の大きい月だった。"
        ),
        "forecast_intro": "過去2年の6月スルメイカ実績は以下の通り。6月は群れの接岸で数が大きく伸びやすく、最盛期に向かう。",
        "forecast_items": [
            "<strong>全体:</strong> 6月はスルメイカの数が伸びる時期。群れの接岸で5月を大きく上回る年もあり、最盛期に向かう見込み。",
            "<strong>相模湾・伊豆:</strong> 長井・小田原早川が引き続き主戦場。群れが続けば束狙いが可能。",
            "<strong>東京湾:</strong> 松輪間口で胴長の伸びた良型シーズンが継続見込み。",
            "<strong>外房・駿河湾・鹿島・内房:</strong> 単発〜主漁場外。6月も数は読みにくい。",
        ],
        "related_fish": ["ムギイカ", "マルイカ"],
        "related_fish_area": [("長井新宿", "nagai-shinjuku"), ("松輪間口", "matsuwa-maguchi")],
    },
    "イサキ": {
        "unit": "匹", "type_metric": "cm",
        "romaji": "isaki",
        "og_image": "https://funatsuri-yoso.com/assets/fish/isaki/isaki_photo.png",
        "area_ports": {
            "東京湾": [("松輪江奈", "matsuwa-ena"), ("久里浜", "kurihama")],
            "内房": [("洲崎", "susaki")],
            "相模湾・伊豆": [("佐島", "sajima"), ("網代", "ajiro-port"), ("伊東", "ito-shi"), ("宇佐美", "usami")],
            "駿河湾・遠州灘": [("御前崎", "omaezaki")],
            "外房": [("大原", "ohara"), ("片貝", "katakai"), ("飯岡", "iioka")],
            "鹿島・茨城": [],
        },
        "narratives": {
            "東京湾": {"trend": "久里浜・松輪江奈が中心。久里浜の平作丸が5/23〜25にMax100匹級を連発し、月間の数を牽引した。型も42cm級の良型が出ている。", "tackle": "コマセビシ＋ウィリー（または付けエサ）。剣崎・松輪沖の根回りをハリス1.5〜2号で手返しよく。"},
            "内房": {"trend": "洲崎の佐衛美丸がほぼ専業で14便。Max50匹と高活性の日もあり、41cmの良型交じりで数・型とも好調だった。", "tackle": "コマセ＋ウィリー仕掛け。3〜4本針の数釣り。"},
            "相模湾・伊豆": {"trend": "佐島・網代・伊東に16船宿が分散。1船あたりはMax20匹前後と外房より控えめだが、40cm級の良型が出るエリア。", "tackle": "コマセ＋ウィリー。相模湾は手前の根周りを丁寧に探る。"},
            "駿河湾・遠州灘": {"trend": "御前崎・田子の浦で月間最大45cmの良型。博栄丸・増福丸が中心で、数より型のエリア。", "tackle": "コマセ釣り中心。深場の良型を狙う。"},
            "外房": {"trend": "本月の主役エリア（70便）。大原・片貝に船が集中し、第三松栄丸・つる丸・勇幸丸が高稼働。乗っ込みの数釣りでMax35〜37匹と安定した。", "tackle": "コマセ＋ウィリー仕掛けが主流。ハリス1.5〜2号・3〜5本針で手返し重視。"},
            "鹿島・茨城": {"trend": "本月のイサキ出船報告なし。イサキは外房以南が主漁場で、鹿島以北は対象外。", "tackle": "—"},
        },
        "consideration_title": "2026年5月の海況とイサキ釣果の関係",
        "consideration_html": (
            "2026年5月のイサキ釣果は全{total}便、前年同月{prev_total}便から{yoy:+.1f}%と増加した。初夏の乗っ込み（産卵期）に入り、関東各地で数釣りシーズンが本格化した月である。日別Max平均は{cmax}匹で、束（100匹）に迫る日も出た。"
            "主役は外房。大原・片貝に船が集中し、第三松栄丸・つる丸・勇幸丸が各14〜23便と高稼働で数を伸ばした。東京湾では久里浜の平作丸が5/23〜25にMax100匹級を連発し、月間の数を牽引している。"
            "型は各地で40cm級が安定し、駿河湾・田子の浦と外房・片貝では45cm前後の良型も上がった。水温が上がって産卵群が浅場の根周りに固まったことで、コマセ＋ウィリーの手返し勝負がはまった月といえる。潮回りでは中潮〜大潮で群れが濃くなる傾向が見られた。"
        ),
        "forecast_intro": "過去2年の6月イサキ実績は以下の通り。6月は乗っ込み後半〜数のピークで、5月並み〜やや増の傾向。",
        "forecast_items": [
            "<strong>全体:</strong> 6月は乗っ込み後半で数釣りのピーク。梅雨の合間を縫えれば束釣りも狙える時期。",
            "<strong>外房:</strong> 引き続き主戦場。大原・片貝で群れが続く限り数が伸びる見込み。",
            "<strong>東京湾:</strong> 久里浜・松輪沖でコマセ＋ウィリーの数釣りが安定。",
            "<strong>相模湾・伊豆:</strong> 佐島〜伊東で40cm級の良型交じり。数は外房に譲るが型に分あり。",
            "<strong>駿河湾・遠州灘:</strong> 御前崎で45cm級の良型シーズンが継続見込み。",
        ],
        "related_fish": ["マダイ"],
        "related_fish_area": [("大原", "ohara"), ("片貝", "katakai")],
    },
    "タチウオ": {
        "unit": "匹", "type_metric": "cm",
        "romaji": "tachiuo",
        "area_ports": {
            "東京湾": [("浦安", "urayasu"), ("鴨居大室", "kamoi-omuro"), ("小柴", "koshiba")],
            "内房": [],
            "相模湾・伊豆": [("佐島", "sajima")],
            "駿河湾・遠州灘": [],
            "外房": [],
            "鹿島・茨城": [],
        },
        "narratives": {
            "東京湾": {"trend": "本月はほぼ東京湾一択（88便）。浦安の吉久19便・横浜新山下の渡辺釣船店18便・福よし丸14便・吉野屋13便が高稼働。渡辺釣船店は5/26にMax58匹と数を伸ばし、浦安の吉久では135cm、江東区木場の吉野屋でも127cmのドラゴン級が上がった。", "tackle": "テンヤ・テンビン（一部ジギング）。誘い上げ〜フォールで食わせる。指5本級は120cm超。"},
            "内房": {"trend": "本月のタチウオ出船報告なし。", "tackle": "—"},
            "相模湾・伊豆": {"trend": "深田家が1便のみ。データが僅少で参考値。", "tackle": "—"},
            "駿河湾・遠州灘": {"trend": "本月のタチウオ出船報告なし。", "tackle": "—"},
            "外房": {"trend": "本月のタチウオ出船報告なし。", "tackle": "—"},
            "鹿島・茨城": {"trend": "本月のタチウオ出船報告なし。", "tackle": "—"},
        },
        "consideration_title": "2026年5月の海況とタチウオ釣果の関係",
        "consideration_html": (
            "2026年5月のタチウオ釣果は全{total}便、前年同月{prev_total}便から{yoy:+.1f}%で推移した。出船はほぼ東京湾に集中し、内房・外房・鹿島では本格的な狙いものにはならなかった。"
            "浦安の吉久（19便）・福よし丸（14便）・吉野屋（13便）が高稼働で東京湾の数を支えた。横浜港の渡辺釣船店は5/26にMax58匹と数を伸ばし、浦安の吉久では135cm、江東区木場の吉野屋でも127cmの大型が上がっている。"
            "日別Max平均は{cmax}匹と数自体は控えめだが、5月の東京湾は指5本（130cm前後）クラスの型狙いに向いた月だった。テンヤ・テンビンの誘い上げで良型を引き出した船が好結果を残している。"
        ),
        "forecast_intro": "過去2年の6月タチウオ実績は以下の通り。東京湾中心の傾向は6月も続く見込み。",
        "forecast_items": [
            "<strong>全体:</strong> 東京湾の周年タチウオが主体。梅雨で出船日は減るが、ドラゴン級の型実績は継続見込み。",
            "<strong>東京湾:</strong> 浦安・横浜・鴨居大室の各船で数・型とも狙える。指5本級の良型は6月も期待。",
            "<strong>相模湾・伊豆:</strong> 単発の出船にとどまる見込みで、数は読みにくい。",
            "<strong>外房・内房・鹿島:</strong> 本格的な狙いものにはなりにくい時期。",
        ],
        "related_fish": ["マダイ"],
        "related_fish_area": [("鴨居大室", "kamoi-omuro"), ("小柴", "koshiba")],
    },
}

# エリア定義（月報用 6エリア）
_MONTHLY_AREA_MAP = {
    "東京湾": ["松輪江奈", "松輪間口", "久里浜", "久比里", "金沢八景", "小柴", "金田", "野比",
              "剣崎", "三崎", "鴨居大室", "鴨居", "大室", "羽田", "八丁堀", "浦安", "本牧", "船橋", "深川",
              "横浜", "金沢漁港", "江戸川", "原木中山", "鹿本橋", "平和島", "東葛西", "柴漁港",
              "品川", "大田区", "六郷", "海老取川", "木場", "江東区", "長浦"],
    "内房": ["富浦", "保田", "金谷", "館山", "勝山", "岩井", "洲崎", "布良", "那古船形"],
    "相模湾・伊豆": ["佐島", "小網代", "茅ヶ崎", "小田原", "網代", "下田", "大磯", "平塚", "小坪",
                  "葉山", "伊東", "宇佐美", "熱海", "真鶴", "東伊豆", "南伊豆", "西伊豆", "長井",
                  "腰越", "片瀬", "早川", "久料"],
    "駿河湾・遠州灘": ["御前崎", "由比", "沼津", "田子の浦", "福田港", "寸座"],
    "外房": ["飯岡", "大原", "天津", "片貝", "御宿", "勝浦", "鴨川", "銚子", "白浜", "千倉", "九十九里"],
    "鹿島・茨城": ["鹿島", "日立", "久慈", "大洗", "那珂湊", "磯崎", "平潟", "大津港"],
}
_MONTHLY_AREA_ORDER = ["東京湾", "内房", "外房", "鹿島・茨城", "相模湾・伊豆", "駿河湾・遠州灘"]

# 月報を生成する対象月（前月自動が本来だが、データが確実に揃う月を固定指定も可）
# "auto" を指定すると実行時の前月を対象にする
_MONTHLY_TARGET = "2026-05"  # "auto" で前月自動


def _monthly_get_area(port: str) -> str:
    if not port:
        return "未分類"
    for area, ports in _MONTHLY_AREA_MAP.items():
        if any(p in port for p in ports):
            return area
    return f"未分類:{port}"


def _monthly_to_float(s):
    if not s or s in ("", "-"):
        return None
    try:
        return float(s)
    except (ValueError, TypeError):
        return None


def _monthly_to_int(s):
    v = _monthly_to_float(s)
    return int(v) if v is not None else None


def _monthly_load_csv(year: int, month: int, fish: str):
    """data/V2/{year}-{month:02d}.csv から指定魚種の行を返す（欠航除く）"""
    import csv as _csv
    rows = []
    for csv_dir_name in (f"{year}-{month:02d}.csv", f"chowari_{year}-{month:02d}.csv"):
        path = os.path.join(_DATA_DIR, csv_dir_name)
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as f:
            for r in _csv.DictReader(f):
                if r.get("tsuri_mono") != fish:
                    continue
                if r.get("is_cancellation") == "1":
                    continue
                rows.append(r)
    return rows


def _monthly_summarize(rows):
    from collections import defaultdict as _dd
    ships = _dd(int)
    dates = set()
    cnt_min_vals, cnt_max_vals, size_max_vals = [], [], []
    for r in rows:
        ships[r["ship"]] += 1
        dates.add(r["date"])
        cmin = _monthly_to_int(r.get("cnt_min"))
        cmax = _monthly_to_int(r.get("cnt_max"))
        smax = _monthly_to_float(r.get("size_max"))
        if cmin is not None:
            cnt_min_vals.append(cmin)
        if cmax is not None:
            cnt_max_vals.append(cmax)
        if smax is not None:
            size_max_vals.append(smax)
    return {
        "total_trips": len(rows),
        "n_ships": len(ships),
        "n_dates": len(dates),
        "cnt_min_avg": round(sum(cnt_min_vals) / len(cnt_min_vals), 1) if cnt_min_vals else None,
        "cnt_max_avg": round(sum(cnt_max_vals) / len(cnt_max_vals), 1) if cnt_max_vals else None,
        "size_max_overall": max(size_max_vals) if size_max_vals else None,
        "ships_top": sorted(ships.items(), key=lambda x: -x[1])[:15],
    }


def _monthly_daily_minmax(rows):
    from collections import defaultdict as _dd
    by_date = _dd(lambda: {"min": [], "max": [], "n_ships": set()})
    for r in rows:
        d = r["date"]
        cmin = _monthly_to_int(r.get("cnt_min"))
        cmax = _monthly_to_int(r.get("cnt_max"))
        if cmin is not None:
            by_date[d]["min"].append(cmin)
        if cmax is not None:
            by_date[d]["max"].append(cmax)
        by_date[d]["n_ships"].add(r["ship"])
    result = []
    for d in sorted(by_date.keys()):
        v = by_date[d]
        result.append({
            "date": d,
            "min_avg": round(sum(v["min"]) / len(v["min"]), 1) if v["min"] else 0,
            "max_avg": round(sum(v["max"]) / len(v["max"]), 1) if v["max"] else 0,
            "n_ships": len(v["n_ships"]),
        })
    return result


def _monthly_best_trips(rows, top_k=3):
    scored = []
    for r in rows:
        cmax = _monthly_to_int(r.get("cnt_max"))
        if cmax is None:
            continue
        scored.append({
            "date": r["date"], "ship": r["ship"], "port": r["area"],
            "cnt_min": _monthly_to_int(r.get("cnt_min")), "cnt_max": cmax,
            "size_max": _monthly_to_float(r.get("size_max")),
        })
    scored.sort(key=lambda x: (-x["cnt_max"], -(x["size_max"] or 0)))
    return scored[:top_k]


def _monthly_best_size_trips(rows, top_k=3):
    scored = []
    for r in rows:
        sz = _monthly_to_float(r.get("size_max"))
        if sz is None or sz <= 0:
            continue
        scored.append({
            "date": r["date"], "ship": r["ship"], "port": r["area"],
            "size_min": _monthly_to_float(r.get("size_min")), "size_max": sz,
            "cnt_max": _monthly_to_int(r.get("cnt_max")),
        })
    scored.sort(key=lambda x: (-x["size_max"], -(x["cnt_max"] or 0)))
    return scored[:top_k]


def _monthly_best_kg_trips(rows, top_k=3):
    scored = []
    for r in rows:
        kg = _monthly_to_float(r.get("kg_max"))
        if kg is None or kg <= 0:
            continue
        scored.append({
            "date": r["date"], "ship": r["ship"], "port": r["area"],
            "kg_min": _monthly_to_float(r.get("kg_min")), "kg_max": kg,
            "size_max": _monthly_to_float(r.get("size_max")),
            "cnt_max": _monthly_to_int(r.get("cnt_max")),
        })
    scored.sort(key=lambda x: (-x["kg_max"], -(x["size_max"] or 0)))
    return scored[:top_k]


def _monthly_by_area(rows):
    from collections import defaultdict as _dd
    area_rows = _dd(list)
    for r in rows:
        area_rows[_monthly_get_area(r["area"])].append(r)
    result = {}
    for area, lst in area_rows.items():
        ships = _dd(int)
        cnt_min_vals, cnt_max_vals, size_max_vals = [], [], []
        dates = set()
        for r in lst:
            ships[r["ship"]] += 1
            dates.add(r["date"])
            cmin = _monthly_to_int(r.get("cnt_min"))
            cmax = _monthly_to_int(r.get("cnt_max"))
            smax = _monthly_to_float(r.get("size_max"))
            if cmin is not None:
                cnt_min_vals.append(cmin)
            if cmax is not None:
                cnt_max_vals.append(cmax)
            if smax is not None:
                size_max_vals.append(smax)
        result[area] = {
            "n_trips": len(lst), "n_ships": len(ships), "n_dates": len(dates),
            "cnt_min_avg": round(sum(cnt_min_vals) / len(cnt_min_vals), 1) if cnt_min_vals else None,
            "cnt_max_avg": round(sum(cnt_max_vals) / len(cnt_max_vals), 1) if cnt_max_vals else None,
            "size_max_overall": max(size_max_vals) if size_max_vals else None,
            "top_ships": sorted(ships.items(), key=lambda x: -x[1])[:5],
        }
    return result


def _monthly_by_catch_top(rows, top_k=8):
    from collections import defaultdict as _dd
    import re as _re
    counter = _dd(int)
    _skip = ("なし", "無し", "ナシ", "不明", "-", "—", "ー", "他", "外道", "その他")
    _suf = ("も交じる", "が交じる", "も混じり", "が混じり", "交じる", "混じり", "まじり", "など", "も")
    for r in rows:
        bc = (r.get("by_catch") or "").strip()
        if not bc:
            continue
        # 区切り: 、 , / ・ ＋ + と各種空白（「アジ・マダイ」「カサゴ／メイゴ」を分割）
        for token in _re.split(r"[、,/・＋\+\s　]+", bc):
            t = token.strip()
            # 末尾の表記揺れ（「サバも」「メジナも交じる」等）を正規化
            for _s in _suf:
                if t.endswith(_s) and len(t) > len(_s):
                    t = t[:-len(_s)]
                    break
            # DB欠損値・無意味トークンを除外（"NULL 57回" 等の生データ露出防止）
            if t.upper() in ("NULL", "NONE", "NAN") or t in _skip:
                continue
            if 2 <= len(t) <= 8:
                counter[t] += 1
    return sorted(counter.items(), key=lambda x: -x[1])[:top_k]


def _monthly_kg_coverage(rows):
    total = len(rows)
    with_kg = sum(1 for r in rows if _monthly_to_float(r.get("kg_max")))
    return {"total": total, "with_kg": with_kg, "pct": round(with_kg / total * 100, 1) if total else 0}


def _monthly_size_coverage(rows):
    total = len(rows)
    with_sz = sum(1 for r in rows if _monthly_to_float(r.get("size_max")))
    return {"total": total, "with_sz": with_sz, "pct": round(with_sz / total * 100, 1) if total else 0}


def _monthly_daily_svg(daily_cur, daily_prev, unit, width=820, height=240):
    """日別 Min/Max 平均の SVG グラフ生成"""
    pad_l, pad_r, pad_t, pad_b = 40, 20, 16, 36
    w = width - pad_l - pad_r
    h = height - pad_t - pad_b

    def to_map(daily):
        m = {}
        for r in daily:
            try:
                day = int(r["date"].split("/")[-1])
                m[day] = (r["min_avg"], r["max_avg"], r["n_ships"])
            except Exception:
                pass
        return m

    m26 = to_map(daily_cur)
    m25 = to_map(daily_prev)
    all_max = max([v[1] for v in m26.values()] + [v[1] for v in m25.values()] + [10])
    y_max = max(10, int(all_max) + 2)

    def x(d):
        return pad_l + (d - 1) * (w / 30)

    def y(v):
        return pad_t + h - (v / y_max) * h

    p = [f'<svg viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg" class="daily-chart" role="img" aria-label="日別Min/Max平均{unit}数グラフ">']
    p.append(f'<rect x="0" y="0" width="{width}" height="{height}" fill="var(--card, #fff)"/>')
    for v in [0, y_max // 4, y_max // 2, y_max * 3 // 4, y_max]:
        gy = y(v)
        p.append(f'<line x1="{pad_l}" y1="{gy}" x2="{width - pad_r}" y2="{gy}" stroke="var(--border, #e3e7ed)" stroke-width="0.5"/>')
        p.append(f'<text x="{pad_l - 6}" y="{gy + 3}" text-anchor="end" font-size="9" fill="var(--sub, #8a96a4)">{v}</text>')
    for d in [1, 5, 10, 15, 20, 25, 31]:
        p.append(f'<text x="{x(d)}" y="{height - pad_b + 14}" text-anchor="middle" font-size="9" fill="var(--text, #5a6a7a)">{d}日</text>')
    max_ships = max([v[2] for v in m26.values()] + [1])
    for d in range(1, 32):
        if d in m26:
            bh = (m26[d][2] / max_ships) * h * 0.4
            p.append(f'<rect x="{x(d) - 3}" y="{pad_t + h - bh}" width="6" height="{bh}" fill="var(--accent, #0d2b4a)" opacity="0.08"/>')
    if m25:
        s25 = sorted(m25.items())
        p.append(f'<polyline points="{" ".join(f"{x(d)},{y(v[1])}" for d, v in s25)}" fill="none" stroke="var(--sub, #8a96a4)" stroke-width="1.4" stroke-dasharray="4,3" opacity="0.7"/>')
        p.append(f'<polyline points="{" ".join(f"{x(d)},{y(v[0])}" for d, v in s25)}" fill="none" stroke="var(--muted, #bfc7d1)" stroke-width="1.2" stroke-dasharray="3,3" opacity="0.6"/>')
    if m26:
        s26 = sorted(m26.items())
        band = [f"{x(d)},{y(m26[d][1])}" for d, _ in s26] + [f"{x(d)},{y(m26[d][0])}" for d, _ in reversed(s26)]
        p.append(f'<polygon points="{" ".join(band)}" fill="var(--cta, #e85d04)" opacity="0.10"/>')
        p.append(f'<polyline points="{" ".join(f"{x(d)},{y(v[1])}" for d, v in s26)}" fill="none" stroke="var(--cta, #e85d04)" stroke-width="2.2"/>')
        p.append(f'<polyline points="{" ".join(f"{x(d)},{y(v[0])}" for d, v in s26)}" fill="none" stroke="var(--accent, #0d2b4a)" stroke-width="1.6"/>')
        for d, v in s26:
            p.append(f'<circle cx="{x(d)}" cy="{y(v[1])}" r="2.5" fill="var(--cta, #e85d04)"/>')
    lg = pad_t + 2
    p.append('<g font-size="10" fill="var(--text, #1a2332)">')
    p.append(f'<line x1="{width - pad_r - 180}" y1="{lg + 5}" x2="{width - pad_r - 160}" y2="{lg + 5}" stroke="var(--cta, #e85d04)" stroke-width="2.2"/><text x="{width - pad_r - 155}" y="{lg + 8}">本月 Max平均</text>')
    p.append(f'<line x1="{width - pad_r - 180}" y1="{lg + 20}" x2="{width - pad_r - 160}" y2="{lg + 20}" stroke="var(--accent, #0d2b4a)" stroke-width="1.6"/><text x="{width - pad_r - 155}" y="{lg + 23}">本月 Min平均</text>')
    p.append(f'<line x1="{width - pad_r - 180}" y1="{lg + 35}" x2="{width - pad_r - 160}" y2="{lg + 35}" stroke="var(--sub, #8a96a4)" stroke-width="1.4" stroke-dasharray="4,3"/><text x="{width - pad_r - 155}" y="{lg + 38}">前年 Max平均</text>')
    p.append('</g></svg>')
    return "\n".join(p)


def _monthly_detect_existing(monthly_dir: str) -> set:
    """docs/monthly/ 配下の月ディレクトリ（YYYY-MM 形式）の set を返す"""
    existing = set()
    if not os.path.isdir(monthly_dir):
        return existing
    import re as _re
    for name in os.listdir(monthly_dir):
        if _re.match(r"^\d{4}-\d{2}$", name) and os.path.isdir(os.path.join(monthly_dir, name)):
            existing.add(name)
    return existing


def _monthly_build_html(fish, cfg, month_str, cur_data, prev_data, next_month_hist, crawled_at=""):
    """
    月報 HTML を生成して返す。
    month_str: "2026-05" 形式
    cur_data / prev_data / next_month_hist: _monthly_summarize / _monthly_daily_minmax 等の出力
    """
    year_num, month_num = int(month_str[:4]), int(month_str[5:])
    next_m = month_num + 1 if month_num < 12 else 1
    next_y = year_num if month_num < 12 else year_num + 1
    next_month_str = f"{next_y}-{next_m:02d}"

    romaji = cfg["romaji"]
    unit = cfg["unit"]
    s = cur_data["summary"]
    ps = prev_data["summary"]
    yoy_pct = (s["total_trips"] / ps["total_trips"] * 100 - 100) if ps.get("total_trips") else 0
    n_area_active = sum(1 for a in _MONTHLY_AREA_ORDER if cur_data["by_area"].get(a))

    canonical = f"{SITE_URL}/monthly/{month_str}/{romaji}.html"
    title = f"{year_num}年{month_num}月 {fish}釣果月報｜関東船釣り｜船釣り予想"
    desc_yoy = f"前年比{yoy_pct:+.1f}%" if ps.get("total_trips") else "初月集計"
    desc = f"{year_num}年{month_num}月の関東{fish}釣果{s['total_trips']}便を集計（{desc_yoy}）。エリア別傾向・海況考察・{month_num + 1}月予測まで、{s['n_ships']}船宿のデータを網羅。"

    # 月号ナビ：docs/monthly/ 既存月リストから動的生成
    monthly_dir = os.path.join(WEB_DIR, "monthly")
    existing_months = _monthly_detect_existing(monthly_dir)

    prev_m = month_num - 1 if month_num > 1 else 12
    prev_y = year_num if month_num > 1 else year_num - 1
    prev_month_str = f"{prev_y}-{prev_m:02d}"
    prev_label = f"{prev_y}年{prev_m}月号"
    next_label = f"{next_y}年{next_m}月号"
    if prev_month_str in existing_months:
        nav_prev = f'<a href="../{prev_month_str}/{romaji}.html">‹ {prev_label}</a>'
    else:
        nav_prev = f'<span class="ml-nav-disabled">‹ {prev_label}（未公開）</span>'
    if next_month_str in existing_months:
        nav_next = f'<a href="../{next_month_str}/{romaji}.html">{next_label} ›</a>'
    else:
        nav_next = f'<span class="ml-nav-disabled">{next_label}（近日公開）</span>'
    nav_html = f'<nav class="ml-nav-month" aria-label="月報ナビゲーション">{nav_prev}<span class="ml-nav-current">{year_num}年{month_num}月号</span>{nav_next}</nav>'

    # ベスト3（数）HTML
    best_html = []
    for i, t in enumerate(cur_data.get("best_trips", []), 1):
        size_s = f" / 最大{t['size_max']:.0f}cm" if t.get("size_max") else ""
        ship_lnk = _ship_link(t["ship"], depth=2)
        # min==max（または min欠落）は単一値に統一（決定ログ2026/05/23・「N〜N匹」禁止）
        _cmin, _cmax = t.get("cnt_min"), t.get("cnt_max")
        cnt_disp = f"{_cmin}〜{_cmax}{unit}" if (_cmin is not None and _cmin != _cmax) else f"{_cmax}{unit}"
        best_html.append(
            f'<li class="bt-item"><span class="bt-rank">#{i}</span>'
            f'<span class="bt-date">{t["date"]}</span>'
            f'<span class="bt-ship">{ship_lnk}</span>'
            f'<span class="bt-port">（{t["port"]}）</span>'
            f'<span class="bt-cnt">{cnt_disp}</span>'
            f'<span class="bt-size">{size_s}</span></li>'
        )

    # ベスト3（型）HTML
    best_type_html = []
    if cfg["type_metric"] == "kg":
        type_tag = "型（重量）"
        for i, t in enumerate(cur_data.get("best_kg_trips", []), 1):
            # kg min==max は単一値（「8.2〜8.2kg」禁止）
            kg_min_s = f"{t['kg_min']:.1f}〜" if (t.get("kg_min") and t["kg_min"] != t["kg_max"]) else ""
            size_s = f" / {t['size_max']:.0f}cm" if t.get("size_max") else ""
            cnt_s = f" / {t['cnt_max']}{unit}" if t.get("cnt_max") else ""
            ship_lnk = _ship_link(t["ship"], depth=2)
            best_type_html.append(
                f'<li class="bt-item"><span class="bt-rank bt-rank-kg">#{i}</span>'
                f'<span class="bt-date">{t["date"]}</span>'
                f'<span class="bt-ship">{ship_lnk}</span>'
                f'<span class="bt-port">（{t["port"]}）</span>'
                f'<span class="bt-cnt bt-kg">{kg_min_s}{t["kg_max"]:.1f}kg</span>'
                f'<span class="bt-size">{size_s}{cnt_s}</span></li>'
            )
        cov = cur_data.get("kg_coverage", {})
        type_note = f"※ 重量記録は{cov.get('with_kg', 0)}/{cov.get('total', 0)}便（{cov.get('pct', 0)}%）で記録あり。"
    else:
        _st = cfg.get("size_term", "全長")  # イカ系のみ "胴長"・魚は "全長"
        type_tag = f"型（{_st}）"
        for i, t in enumerate(cur_data.get("best_size_trips", []), 1):
            # サイズ min==max は単一値（「40〜40cm」禁止）
            sz_min_s = f"{t['size_min']:.0f}〜" if (t.get("size_min") and t["size_min"] != t["size_max"]) else ""
            cnt_s = f" / {t['cnt_max']}{unit}" if t.get("cnt_max") else ""
            ship_lnk = _ship_link(t["ship"], depth=2)
            best_type_html.append(
                f'<li class="bt-item"><span class="bt-rank bt-rank-kg">#{i}</span>'
                f'<span class="bt-date">{t["date"]}</span>'
                f'<span class="bt-ship">{ship_lnk}</span>'
                f'<span class="bt-port">（{t["port"]}）</span>'
                f'<span class="bt-cnt bt-kg">{sz_min_s}{t["size_max"]:.0f}cm</span>'
                f'<span class="bt-size">{cnt_s}</span></li>'
            )
        cov = cur_data.get("size_coverage", {})
        type_note = f"※ {_st}記録は{cov.get('with_sz', 0)}/{cov.get('total', 0)}便（{cov.get('pct', 0)}%）で記録あり。"

    # 船宿チップ（depth=2 でリンク化）
    ships_chips = "".join(
        f'{_ship_link(n, depth=2)} <span class="ml-chip-n">{c}便</span>'
        if _SHIP_ROMAJI.get(n) else f'<span class="ml-chip">{n} <span class="ml-chip-n">{c}便</span></span>'
        for n, c in s["ships_top"]
    )
    ships_html = f'<div class="ml-ships-list">{ships_chips}</div>'

    # エリアセクション
    area_sections = []
    for area in _MONTHLY_AREA_ORDER:
        v = cur_data["by_area"].get(area)
        nar = cfg.get("narratives", {}).get(area, {})
        if not v:
            area_sections.append(
                f'<section class="ml-area" id="area-{area}">'
                f'<h3>{area}</h3>'
                f'<p class="ml-empty">本月の{area}での{fish}出船報告はありません。</p>'
                f'</section>'
            )
            continue
        size_label = f"最大{v['size_max_overall']:.0f}cm" if v.get("size_max_overall") else "型データ未取得"
        # 船宿チップ（depth=2）
        ships_chips_a = "".join(
            f'<a href="../../ship/{_SHIP_ROMAJI[sh]}.html" class="ml-chip">{sh} <span class="ml-chip-n">{c}便</span></a>'
            if _SHIP_ROMAJI.get(sh) else f'<span class="ml-chip">{sh} <span class="ml-chip-n">{c}便</span></span>'
            for sh, c in v["top_ships"]
        )
        # 港チップ（area_slug が _AREA_ROMAJI に存在すればリンク化）
        ports_chips = ""
        for label, slug in cfg.get("area_ports", {}).get(area, []):
            area_key = next((k for k in _AREA_ROMAJI if _AREA_ROMAJI[k] == slug), None)
            if area_key and _AREA_ROMAJI.get(area_key):
                ports_chips += f'<a href="../../area/{slug}.html" class="ml-chip ml-chip-port">⚓ {label}</a>'
            else:
                ports_chips += f'<span class="ml-chip ml-chip-port">⚓ {label}</span>'

        # fish_area リンク or fish ページにフォールバック
        fish_romaji_val = _FISH_ROMAJI.get(fish, fish)
        area_slug_val = _AREA_ROMAJI.get(area, area)
        fa_path = os.path.join(WEB_DIR, "fish_area", f"{fish_romaji_val}-{area_slug_val}.html")
        if os.path.exists(fa_path):
            detail_href = f"../../fish_area/{fish_romaji_val}-{area_slug_val}.html"
        else:
            detail_href = f"../../fish/{fish_romaji_val}.html"

        cnt_min_lbl = f"{v['cnt_min_avg']}{unit}" if v.get("cnt_min_avg") is not None else "—"
        cnt_max_lbl = f"{v['cnt_max_avg']}{unit}" if v.get("cnt_max_avg") is not None else "—"

        area_sections.append(f'''<section class="ml-area" id="area-{area}">
  <h3>{area} <span class="ml-area-num">{v['n_trips']}便 / {v['n_ships']}船宿</span></h3>
  <div class="ml-area-stats">
    <div class="ml-stat"><span class="ml-stat-label">日別Min平均</span><span class="ml-stat-val">{cnt_min_lbl}</span></div>
    <div class="ml-stat"><span class="ml-stat-label">日別Max平均</span><span class="ml-stat-val">{cnt_max_lbl}</span></div>
    <div class="ml-stat"><span class="ml-stat-label">型</span><span class="ml-stat-val">{size_label}</span></div>
    <div class="ml-stat"><span class="ml-stat-label">釣行日数</span><span class="ml-stat-val">{v['n_dates']}日</span></div>
  </div>
  <p class="ml-trend">{nar.get('trend', '—')}</p>
  <p class="ml-tackle"><strong>仕掛け:</strong> {nar.get('tackle', '—')}</p>
  <div class="ml-row"><span class="ml-row-label">主要船宿:</span><div class="ml-chips">{ships_chips_a}</div></div>
  <div class="ml-row"><span class="ml-row-label">主要港:</span><div class="ml-chips">{ports_chips}</div></div>
  <p class="ml-detail-link"><a href="{detail_href}">› このエリアの{fish}詳細データ</a></p>
</section>''')

    # 外道
    bycatch_html = "".join(
        f'<li><span class="bc-name">{n}</span><span class="bc-count">{c}回</span></li>'
        for n, c in cur_data.get("by_catch", [])
    ) or '<li><span class="bc-name">特筆すべき外道なし</span></li>'

    # 次月予測テーブル
    nh_rows = []
    for k in sorted(next_month_hist.keys(), reverse=True):
        v_nh = next_month_hist[k]
        if v_nh and v_nh.get("total_trips"):
            _lo, _hi = v_nh.get('cnt_min_avg'), v_nh.get('cnt_max_avg')
            rng_s = (f"{_lo}〜{_hi}{unit}" if (_lo is not None and _hi is not None and _lo != _hi)
                     else (f"{_hi}{unit}" if _hi is not None else "—"))
            nh_rows.append(f'<tr><th>{k}</th><td>{v_nh["total_trips"]}便</td><td>{v_nh["n_ships"]}船宿</td><td>{rng_s}</td></tr>')
    _lo_c, _hi_c = s.get('cnt_min_avg'), s.get('cnt_max_avg')
    rng_cur = (f"{_lo_c}〜{_hi_c}{unit}" if (_lo_c is not None and _hi_c is not None and _lo_c != _hi_c)
               else (f"{_hi_c}{unit}" if _hi_c is not None else "—"))
    nh_rows.append(f'<tr><td><strong>{year_num}年{month_num}月（本月）</strong></td><td>{s["total_trips"]}便</td><td>{s["n_ships"]}船宿</td><td>{rng_cur}</td></tr>')

    chart_svg = _monthly_daily_svg(cur_data.get("daily", []), prev_data.get("daily", []), unit)

    # 考察テキスト（format 変数を try で安全注入）
    try:
        consideration = cfg["consideration_html"].format(
            total=s["total_trips"],
            yoy=yoy_pct,
            prev_total=ps.get("total_trips", 0),
            cmax=s.get("cnt_max_avg") or "—",
            cmin=s.get("cnt_min_avg") or "—",
        )
    except (KeyError, ValueError):
        consideration = cfg.get("consideration_html", "（考察テキスト未設定）")

    forecast_items_html = "".join(f"<li>{it}</li>" for it in cfg.get("forecast_items", []))

    # 関連リンク
    fish_romaji_val = _FISH_ROMAJI.get(fish, fish)
    related_links = []
    # 自魚種詳細
    related_links.append(f'<a href="../../fish/{fish_romaji_val}.html">{fish}詳細ページ（最新7日チャート・船宿ランキング）</a>')
    # 他魚種月報（同ディレクトリ）
    for other_fish in cfg.get("related_fish", []):
        other_romaji = MONTHLY_FISH_CONFIG.get(other_fish, {}).get("romaji", _FISH_ROMAJI.get(other_fish, other_fish))
        related_links.append(f'<a href="./{other_romaji}.html">{year_num}年{month_num}月 {other_fish}月報</a>')
    # 月報一覧
    related_links.append(f'<a href="../">月報一覧（全月号）</a>')
    # fish_area 関連（実在する 魚種×港 ページのみリンク。無い場合は出さない＝
    # 「×エリア 詳細」と書いて fish ページに飛ばす欺きリンクを排除）
    for port_label, fa_slug in cfg.get("related_fish_area", []):
        fa_path_r = os.path.join(WEB_DIR, "fish_area", f"{fish_romaji_val}-{fa_slug}.html")
        if os.path.exists(fa_path_r):
            related_links.append(f'<a href="../../fish_area/{fish_romaji_val}-{fa_slug}.html">{fish} × {port_label} 詳細</a>')
    related_html = "".join(related_links)

    # JSON-LD
    import json as _json
    breadcrumb = {
        "@context": "https://schema.org", "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "トップ", "item": f"{SITE_URL}/"},
            {"@type": "ListItem", "position": 2, "name": "月報", "item": f"{SITE_URL}/monthly/"},
            {"@type": "ListItem", "position": 3, "name": f"{fish}月報（{year_num}年{month_num}月）", "item": canonical},
        ]
    }
    date_published = f"{year_num}-{month_num + 1:02d}-01" if month_num < 12 else f"{year_num + 1}-01-01"
    article = {
        "@context": "https://schema.org", "@type": "Article",
        "headline": f"{year_num}年{month_num}月 関東{fish}釣果月報",
        "description": desc,
        "image": cfg.get("og_image", OGP_DEFAULT_IMG),
        "datePublished": date_published,
        "dateModified": crawled_at or datetime.now(JST).replace(tzinfo=None).strftime("%Y-%m-%d"),
        "author": {"@type": "Organization", "name": "船釣り予想"},
        "publisher": {"@type": "Organization", "name": "船釣り予想",
                      "logo": {"@type": "ImageObject", "url": f"{SITE_URL}/assets/logo.png"}},
        "mainEntityOfPage": canonical,
    }

    og_image = cfg.get("og_image", OGP_DEFAULT_IMG)
    yoy_cls = "neg" if yoy_pct < 0 else "pos"
    yoy_label = f"前年比 {yoy_pct:+.1f}% （前年 {ps.get('total_trips', '—')}便）" if ps.get("total_trips") else "初月集計"
    size_overall = s.get("size_max_overall")
    size_overall_s = f"{size_overall:.0f}" if size_overall else "—"
    share_text = f"{year_num}年{month_num}月 関東{fish}釣果月報｜船釣り予想"
    share_bar_html = _build_share_buttons(share_text, canonical)

    html = f'''<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="icon" href="/favicon.ico" sizes="48x48"><link rel="apple-touch-icon" href="/apple-touch-icon.png">
<title>{title}</title>
<meta name="description" content="{desc}">
<link rel="canonical" href="{canonical}">
<meta property="og:title" content="{title}">
<meta property="og:description" content="{desc}">
<meta property="og:url" content="{canonical}">
<meta property="og:type" content="article">
<meta property="og:site_name" content="船釣り予想">
<meta property="og:image" content="{og_image}">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:site" content="@funatsuri_yoso">
<meta name="twitter:title" content="{title}">
<meta name="twitter:description" content="{desc}">
<meta name="twitter:image" content="{og_image}">
<script type="application/ld+json">{_json.dumps(breadcrumb, ensure_ascii=False)}</script>
<script type="application/ld+json">{_json.dumps(article, ensure_ascii=False)}</script>
<link rel="stylesheet" href="../../style.css">
<style>
.ml-hero{{background:linear-gradient(135deg,var(--accent),var(--hero-grad-end,#1a4a7a));color:#fff;padding:28px 18px 24px;text-align:center}}
.ml-hero h1{{font-size:24px;font-weight:800;margin:0 0 6px;line-height:1.3}}
.ml-hero h1 .ml-hero-fish{{color:var(--cta);font-size:30px;display:block;margin-bottom:2px}}
.ml-hero-sub{{font-size:13px;color:rgba(255,255,255,0.85);margin-top:6px}}
.ml-hero-stats{{display:flex;flex-wrap:wrap;justify-content:center;gap:18px;margin-top:14px}}
.ml-hero-stat{{display:flex;flex-direction:column;align-items:center;min-width:80px}}
.ml-hero-stat .v{{font-size:22px;font-weight:800;color:#fff;line-height:1.1}}
.ml-hero-stat .l{{font-size:11px;color:rgba(255,255,255,0.75);margin-top:2px}}
.ml-hero-yoy{{display:inline-block;margin-top:10px;padding:4px 12px;border-radius:14px;font-size:12px;font-weight:700;background:rgba(255,255,255,0.15)}}
.ml-hero-yoy.neg{{background:rgba(212,51,51,0.30)}}
.ml-hero-yoy.pos{{background:rgba(26,157,86,0.30)}}
.ml-toc{{background:var(--card);border:1px solid var(--border);border-radius:var(--r,8px);padding:14px 18px;margin:16px 0}}
.ml-toc h2{{font-size:13px;font-weight:700;color:var(--accent);margin:0 0 8px}}
.ml-toc ol{{margin:0;padding-left:20px;font-size:13px}}
.ml-toc li{{padding:4px 0}}
.ml-toc li a{{color:var(--cta);text-decoration:none}}
.ml-sec{{background:var(--card);border:1px solid var(--border);border-radius:var(--r,8px);padding:18px;margin-bottom:18px}}
.ml-sec h2{{font-size:17px;font-weight:800;color:var(--accent);margin:0 0 14px;padding-bottom:8px;border-bottom:2px solid var(--cta)}}
.ml-sec h2 .ml-sec-num{{display:inline-block;background:var(--cta);color:#fff;width:26px;height:26px;line-height:26px;text-align:center;border-radius:50%;font-size:14px;margin-right:8px;vertical-align:middle}}
.ml-sec p{{font-size:14px;line-height:1.75;color:var(--text);margin:0 0 12px}}
.ml-summary-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:10px;margin-bottom:16px}}
.ml-summary-grid .ml-stat{{background:var(--bg);border-radius:8px;padding:10px 12px;text-align:center}}
.ml-summary-grid .ml-stat-label{{font-size:10px;color:var(--sub);display:block}}
.ml-summary-grid .ml-stat-val{{font-size:18px;font-weight:800;color:var(--accent);display:block;margin-top:2px}}
.ml-best-twin{{display:flex;flex-direction:column;gap:14px;margin:18px 0 10px}}
.ml-best-col{{background:var(--bg);border-radius:8px;padding:14px 16px;border-left:4px solid var(--cta)}}
.ml-best-col.ml-best-col-kg{{border-left-color:var(--prem,#7c3aed)}}
.ml-best-title{{font-size:14px;font-weight:800;color:var(--accent);margin:0 0 10px;display:flex;align-items:center;gap:8px}}
.ml-best-tag{{display:inline-block;background:var(--cta);color:#fff;font-size:11px;padding:3px 10px;border-radius:10px;font-weight:700}}
.ml-best-tag-kg{{background:var(--prem,#7c3aed)}}
.ml-best-note{{font-size:11px;color:var(--muted,#8a96a4);margin-top:8px}}
.ml-best{{list-style:none;margin:0;padding:0}}
.bt-item{{display:flex;align-items:center;flex-wrap:wrap;gap:6px;padding:10px 0;border-bottom:1px solid var(--border);font-size:13px}}
.bt-item:last-child{{border-bottom:none}}
.bt-rank{{display:inline-block;width:30px;height:30px;line-height:30px;text-align:center;background:var(--cta);color:#fff;border-radius:50%;font-weight:800;font-size:12px}}
.bt-rank-kg{{background:var(--prem,#7c3aed)}}
.bt-date{{font-weight:700;color:var(--sub);min-width:88px;font-size:12px}}
.bt-ship{{font-weight:700;font-size:13px}}
.bt-ship a{{color:var(--accent);text-decoration:none}}
.bt-port{{color:var(--muted,#8a96a4);font-size:12px}}
.bt-cnt{{margin-left:auto;font-weight:800;color:var(--cta);font-size:16px}}
.bt-kg{{color:var(--prem,#7c3aed)}}
.bt-size{{color:var(--sub);font-size:12px}}
.ml-ships-list{{display:flex;flex-wrap:wrap;gap:6px;margin-top:10px}}
.ml-chip{{display:inline-flex;align-items:center;gap:4px;background:var(--card);border:1px solid var(--border);border-radius:14px;padding:5px 10px;font-size:12px;color:var(--accent);text-decoration:none;font-weight:600}}
.ml-chip a{{color:var(--accent);text-decoration:none}}
.ml-chip:hover{{background:var(--accent);color:#fff}}
.ml-chip-port{{background:#f0f7ff;border-color:#b6d4ed}}
.ml-chip-n{{font-size:11px;color:var(--muted,#8a96a4);font-weight:500}}
.ml-chart-wrap{{margin:16px 0;background:var(--bg);border-radius:8px;padding:14px}}
.ml-chart-wrap h3{{font-size:13px;font-weight:700;color:var(--accent);margin:0 0 8px}}
.ml-chart-wrap .daily-chart{{width:100%;height:auto;display:block}}
.ml-chart-note{{font-size:11px;color:var(--muted,#8a96a4);margin-top:8px}}
.ml-area{{background:var(--bg);border-left:4px solid var(--cta);border-radius:6px;padding:14px;margin-bottom:14px}}
.ml-area h3{{font-size:15px;font-weight:800;color:var(--accent);margin:0 0 10px;display:flex;align-items:baseline;gap:10px;flex-wrap:wrap}}
.ml-area-num{{font-size:12px;color:var(--muted,#8a96a4);font-weight:500}}
.ml-area-stats{{display:grid;grid-template-columns:repeat(auto-fit,minmax(100px,1fr));gap:8px;margin-bottom:10px}}
.ml-area-stats .ml-stat{{background:var(--card);border:1px solid var(--border);border-radius:6px;padding:6px 10px;text-align:center}}
.ml-area-stats .ml-stat-label{{font-size:10px;color:var(--sub);display:block}}
.ml-area-stats .ml-stat-val{{font-size:14px;font-weight:700;color:var(--accent);display:block;margin-top:2px}}
.ml-trend{{font-size:13px;line-height:1.7;color:var(--text);margin:8px 0}}
.ml-tackle{{font-size:12px;color:var(--sub);margin:6px 0;background:var(--card);padding:6px 10px;border-radius:4px}}
.ml-row{{display:flex;align-items:flex-start;gap:8px;margin:6px 0;flex-wrap:wrap}}
.ml-row-label{{font-size:11px;color:var(--muted,#8a96a4);font-weight:700;min-width:60px;line-height:1.8}}
.ml-chips{{display:flex;flex-wrap:wrap;gap:5px;flex:1}}
.ml-detail-link{{font-size:12px;margin-top:8px}}
.ml-detail-link a{{color:var(--cta);text-decoration:none}}
.ml-empty{{font-size:13px;color:var(--muted,#8a96a4);font-style:italic}}
.ml-consider{{background:linear-gradient(180deg,#fff8f0,#fff);border:1px solid #f4d8b8;border-radius:8px;padding:16px}}
.ml-consider h3{{font-size:13px;font-weight:700;color:#b85020;margin:0 0 8px}}
.ml-consider-body{{font-size:14px;line-height:1.85;color:var(--text)}}
.ml-consider-note{{font-size:11px;color:var(--muted,#8a96a4);margin-top:10px;padding:6px 10px;background:var(--bg);border-radius:4px}}
.ml-forecast-table{{width:100%;border-collapse:collapse;font-size:13px;margin:10px 0}}
.ml-forecast-table th,.ml-forecast-table td{{padding:8px 10px;border:1px solid var(--border);text-align:center}}
.ml-forecast-table th{{background:var(--accent);color:#fff;font-weight:700}}
.ml-bycatch{{background:var(--bg);border-radius:6px;padding:10px}}
.ml-bycatch h4{{font-size:11px;color:var(--muted,#8a96a4);font-weight:700;margin:0 0 6px}}
.ml-bycatch ul{{list-style:none;margin:0;padding:0;display:flex;flex-wrap:wrap;gap:6px}}
.ml-bycatch li{{display:inline-flex;align-items:center;gap:4px;background:var(--card);border:1px solid var(--border);border-radius:12px;padding:3px 8px;font-size:12px}}
.bc-name{{font-weight:700;color:var(--accent)}}
.bc-count{{color:var(--muted,#8a96a4);font-size:11px}}
.ml-related{{background:var(--bg);border-radius:8px;padding:14px;margin-top:18px}}
.ml-related h3{{font-size:13px;font-weight:700;color:var(--accent);margin:0 0 10px}}
.ml-related-list{{display:flex;flex-wrap:wrap;gap:8px}}
.ml-related-list a{{display:inline-block;padding:8px 14px;background:var(--card);border:1px solid var(--border);border-radius:18px;font-size:12px;color:var(--accent);text-decoration:none;font-weight:600}}
.ml-related-list a:hover{{background:var(--accent);color:#fff}}
.ml-nav-month{{display:flex;justify-content:space-between;align-items:stretch;gap:8px;margin:14px 0;padding:10px;background:var(--card);border:1px solid var(--border);border-radius:8px}}
.ml-nav-month>*{{flex:1 1 0;min-width:0;display:flex;align-items:center;justify-content:center;text-align:center;line-height:1.35}}
.ml-nav-month a{{color:var(--cta);text-decoration:none;font-size:13px;font-weight:600}}
.ml-nav-month .ml-nav-current{{color:var(--accent);font-weight:800;font-size:13px}}
.ml-nav-month .ml-nav-disabled{{color:var(--muted,#8a96a4);font-size:13px;font-weight:500;opacity:.7;cursor:default}}
@media(max-width:520px){{.ml-hero h1{{font-size:20px}}.ml-hero h1 .ml-hero-fish{{font-size:24px}}.bt-cnt{{margin-left:0;width:100%;text-align:right}}.ml-nav-month{{gap:6px;padding:8px}}.ml-nav-month a,.ml-nav-month .ml-nav-current,.ml-nav-month .ml-nav-disabled{{font-size:11px}}}}
</style>
</head>
<body>
{_v2_header_nav("monthly")}
<section class="ml-hero">
  <h1><span class="ml-hero-fish">{fish}</span>{year_num}年{month_num}月 釣果月報</h1>
  <p class="ml-hero-sub">関東{n_area_active}海域・{s['n_ships']}船宿のデータで読み解く{month_num}月の{fish}釣況</p>
  <div class="ml-hero-stats">
    <div class="ml-hero-stat"><span class="v">{s['total_trips']}</span><span class="l">便</span></div>
    <div class="ml-hero-stat"><span class="v">{s['n_ships']}</span><span class="l">船宿</span></div>
    <div class="ml-hero-stat"><span class="v">{s['n_dates']}</span><span class="l">日</span></div>
    <div class="ml-hero-stat"><span class="v">{size_overall_s}<small style="font-size:14px">cm</small></span><span class="l">月間最大</span></div>
  </div>
  <span class="ml-hero-yoy {yoy_cls}">{yoy_label}</span>
</section>
<div class="c">
  <p class="bread"><a href="/">トップ</a> &rsaquo; <a href="/monthly/">月報</a> &rsaquo; {fish}月報（{year_num}年{month_num}月）</p>
  {nav_html}
  <p style="font-size:14px;line-height:1.75;color:var(--text);margin:14px 0">{year_num}年{month_num}月の関東{fish}釣果を全エリア・全船宿で集計しました。日別釣果グラフ、エリア別傾向、海況考察、{month_num + 1}月の傾向予測まで。<a href="../../fish/{fish_romaji_val}.html" style="color:var(--cta)">{fish}詳細ページ</a> もあわせてどうぞ。</p>
  <nav class="ml-toc" aria-label="目次"><h2>もくじ</h2><ol>
    <li><a href="#sec-1">{fish}の釣果実績（{month_num}月全体サマリー・対象船宿・ベスト3・日別グラフ）</a></li>
    <li><a href="#sec-2">エリア別釣果傾向（主要船宿・仕掛け）</a></li>
    <li><a href="#sec-3">海況との関係考察</a></li>
    <li><a href="#sec-4">{month_num + 1}月の傾向予測</a></li>
  </ol></nav>
  <section class="ml-sec" id="sec-1">
    <h2><span class="ml-sec-num">1</span>{fish}の釣果実績</h2>
    <div class="ml-summary-grid">
      <div class="ml-stat"><span class="ml-stat-label">釣行件数</span><span class="ml-stat-val">{s['total_trips']}便</span></div>
      <div class="ml-stat"><span class="ml-stat-label">対象船宿</span><span class="ml-stat-val">{s['n_ships']}</span></div>
      <div class="ml-stat"><span class="ml-stat-label">釣行日数</span><span class="ml-stat-val">{s['n_dates']}日</span></div>
      <div class="ml-stat"><span class="ml-stat-label">日別Min平均</span><span class="ml-stat-val">{s.get('cnt_min_avg') or '—'}{unit}</span></div>
      <div class="ml-stat"><span class="ml-stat-label">日別Max平均</span><span class="ml-stat-val">{s.get('cnt_max_avg') or '—'}{unit}</span></div>
      <div class="ml-stat"><span class="ml-stat-label">月間最大型</span><span class="ml-stat-val">{size_overall_s}cm</span></div>
    </div>
    <details class="ml-ships-wrap" open><summary style="font-size:13px;font-weight:700;color:var(--accent);cursor:pointer;padding:6px 0">対象船宿一覧（{s['n_ships']}船宿{'・便数上位15を表示' if s['n_ships'] > 15 else ''}）</summary>{ships_html}</details>
    <div class="ml-best-twin">
      <div class="ml-best-col"><h3 class="ml-best-title">月間ベスト3 <span class="ml-best-tag">釣果（数）</span></h3><ol class="ml-best">{"".join(best_html) or "<li>データなし</li>"}</ol></div>
      <div class="ml-best-col ml-best-col-kg"><h3 class="ml-best-title">月間ベスト3 <span class="ml-best-tag ml-best-tag-kg">{type_tag}</span></h3><ol class="ml-best">{"".join(best_type_html) or "<li>データなし</li>"}</ol><p class="ml-best-note">{type_note}</p></div>
    </div>
    <div class="ml-chart-wrap"><h3>日別 Min/Max 平均{unit}数（{year_num}年{month_num}月・前年重ね描き）</h3>{chart_svg}<p class="ml-chart-note">※ オレンジ実線=本月Max平均、紺実線=本月Min平均、灰破線=前年Max平均。背景の縦バーは出船船数（信頼度）。データは出船あり船宿のみ平均。</p></div>
  </section>
  <section class="ml-sec" id="sec-2">
    <h2><span class="ml-sec-num">2</span>エリア別釣果傾向</h2>
    <p style="font-size:13px;color:var(--sub)">関東の{fish}釣り場を地理特性で6エリアに分類。各エリアの主要船宿・主要港・釣果傾向・仕掛けをまとめます（本月出船のあったエリアを中心に）。</p>
    {"".join(area_sections)}
    <div class="ml-bycatch"><h4>本月の主な外道（{month_num}月全体）</h4><ul>{bycatch_html}</ul></div>
  </section>
  <section class="ml-sec" id="sec-3">
    <h2><span class="ml-sec-num">3</span>海況との関係考察</h2>
    <div class="ml-consider"><h3>{cfg['consideration_title']}</h3><div class="ml-consider-body">{consideration}</div><p class="ml-consider-note">※ 本セクションは月次の水温・潮位・潮回りの傾向と当月の釣果実績にもとづく定性的な分析です。</p></div>
  </section>
  <section class="ml-sec" id="sec-4">
    <h2><span class="ml-sec-num">4</span>{month_num + 1}月の傾向予測</h2>
    <p>{cfg.get('forecast_intro', '')}</p>
    <table class="ml-forecast-table"><thead><tr><th>月</th><th>釣行件数</th><th>船宿数</th><th>Min〜Max平均</th></tr></thead><tbody>{"".join(nh_rows)}</tbody></table>
    <p class="ml-chart-note" style="margin:4px 0 12px">※ 2026年は収録船宿数が前年から大きく増えており、便数の単純比較はできません。Min〜Max平均（1便あたりの傾向）を比較の目安としてください。</p>
    <h3 style="font-size:14px;font-weight:700;color:var(--accent);margin:14px 0 8px">{month_num + 1}月の傾向見立て</h3>
    <ul style="font-size:13px;line-height:1.85;color:var(--text);padding-left:20px">{forecast_items_html}</ul>
    <p class="ml-consider-note" style="background:var(--bg);font-size:11px;color:var(--muted,#8a96a4);margin-top:10px;padding:6px 10px;border-radius:4px">※ 上記は過去年実績と季節傾向からの見立て。具体的な日別予測は <a href="/forecast/" style="color:var(--cta)">有料の日別予測ページ</a> で提供予定。</p>
  </section>
  <div class="ml-related"><h3>関連ページ・他の月報</h3><div class="ml-related-list">{related_html}</div></div>
  {nav_html}
  {share_bar_html}
</div>
<footer style="margin-top:30px;padding:20px;background:var(--accent);color:#fff;text-align:center;font-size:12px">
  <p>© 2026 船釣り予想 funatsuri-yoso.com</p>
  <p style="margin-top:6px;font-size:11px;opacity:0.7">月報は毎月1日に前月分を公開予定。</p>
  <p style="margin-top:6px;font-size:11px"><a href="/pages/privacy.html" style="color:rgba(255,255,255,0.7)">プライバシーポリシー</a></p>
</footer>
</body>
</html>'''
    return html


def build_monthly_pages(crawled_at=""):
    """
    MONTHLY_FISH_CONFIG の各魚種について前月（または _MONTHLY_TARGET 固定月）の月報 HTML を生成する。
    出力: docs/monthly/{month_str}/{romaji}.html
    """
    now = datetime.now(JST).replace(tzinfo=None)
    if _MONTHLY_TARGET == "auto":
        if now.month == 1:
            target_year, target_month = now.year - 1, 12
        else:
            target_year, target_month = now.year, now.month - 1
    else:
        try:
            target_year = int(_MONTHLY_TARGET[:4])
            target_month = int(_MONTHLY_TARGET[5:7])
        except (ValueError, IndexError):
            print(f"[build_monthly_pages] _MONTHLY_TARGET パース失敗: {_MONTHLY_TARGET}")
            return

    month_str = f"{target_year}-{target_month:02d}"
    # 前年同月
    prev_year = target_year - 1

    monthly_dir = os.path.join(WEB_DIR, "monthly")
    month_dir = os.path.join(monthly_dir, month_str)
    os.makedirs(month_dir, exist_ok=True)

    for fish, cfg in MONTHLY_FISH_CONFIG.items():
        romaji = cfg["romaji"]
        print(f"[monthly] {month_str} {fish} 集計中...")

        # 今月データ
        cur_rows = _monthly_load_csv(target_year, target_month, fish)
        if not cur_rows:
            print(f"  [WARN] {month_str} {fish}: CSVデータなし → スキップ")
            continue

        # 前年同月データ
        prev_rows = _monthly_load_csv(prev_year, target_month, fish)

        # 翌月2年分（来月予測用）
        next_m = target_month + 1 if target_month < 12 else 1
        next_y = target_year if target_month < 12 else target_year + 1
        next_month_hist = {}
        for ny in (next_y - 1, next_y - 2):
            k = f"{ny}-{next_m:02d}"
            rows_nh = _monthly_load_csv(ny, next_m, fish)
            next_month_hist[k] = _monthly_summarize(rows_nh) if rows_nh else None

        cur_data = {
            "summary": _monthly_summarize(cur_rows),
            "daily": _monthly_daily_minmax(cur_rows),
            "best_trips": _monthly_best_trips(cur_rows),
            "best_kg_trips": _monthly_best_kg_trips(cur_rows),
            "best_size_trips": _monthly_best_size_trips(cur_rows),
            "by_area": _monthly_by_area(cur_rows),
            "by_catch": _monthly_by_catch_top(cur_rows),
            "kg_coverage": _monthly_kg_coverage(cur_rows),
            "size_coverage": _monthly_size_coverage(cur_rows),
        }
        prev_data = {
            "summary": _monthly_summarize(prev_rows) if prev_rows else {"total_trips": 0},
            "daily": _monthly_daily_minmax(prev_rows) if prev_rows else [],
        }

        html = _monthly_build_html(fish, cfg, month_str, cur_data, prev_data, next_month_hist, crawled_at)

        out_path = os.path.join(month_dir, f"{romaji}.html")
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"  生成: {out_path} ({len(html):,} chars)")

    print(f"[build_monthly_pages] 完了 → docs/monthly/{month_str}/")


def build_monthly_index(crawled_at=""):
    """
    docs/monthly/index.html（月報ハブ）を生成する。
    docs/monthly/**/*.html をスキャンし、月×魚種カードを一覧表示。
    """
    import re as _re
    monthly_dir = os.path.join(WEB_DIR, "monthly")
    os.makedirs(monthly_dir, exist_ok=True)

    # 生成済み月報を収集
    report_cards = {}  # {month_str: {romaji: {fish, href, title}}}
    if os.path.isdir(monthly_dir):
        for month_name in sorted(os.listdir(monthly_dir), reverse=True):
            if not _re.match(r"^\d{4}-\d{2}$", month_name):
                continue
            month_path = os.path.join(monthly_dir, month_name)
            if not os.path.isdir(month_path):
                continue
            for fname in sorted(os.listdir(month_path)):
                if not fname.endswith(".html"):
                    continue
                romaji = fname[:-5]
                # MONTHLY_FISH_CONFIG から fish 名を逆引き
                fish = next((f for f, c in MONTHLY_FISH_CONFIG.items() if c.get("romaji") == romaji), None)
                if not fish:
                    continue
                report_cards.setdefault(month_name, {})[romaji] = {
                    "fish": fish,
                    "href": f"{month_name}/{fname}",
                }

    # ハブ HTML 生成
    now = datetime.now(JST).replace(tzinfo=None)
    canonical = f"{SITE_URL}/monthly/"
    title = "月報一覧｜関東船釣り釣果月報｜船釣り予想"
    desc = "関東の船釣り釣果を魚種別・月別に集計した月報の一覧です。マダイ・マルイカなど主要魚種の釣果傾向・エリア別データを毎月公開。"

    cards_html = ""
    for month_str in sorted(report_cards.keys(), reverse=True):
        year_n = int(month_str[:4])
        month_n = int(month_str[5:])
        month_label = f"{year_n}年{month_n}月"
        fish_links = "".join(
            f'<a href="{info["href"]}" class="mh-card-fish">{info["fish"]}月報</a>'
            for romaji_key, info in sorted(report_cards[month_str].items())
        )
        cards_html += f'''<div class="mh-month-block">
  <h2 class="mh-month-label">{month_label}</h2>
  <div class="mh-fish-row">{fish_links}</div>
</div>'''

    if not cards_html:
        cards_html = '<p style="color:var(--muted,#8a96a4);font-size:14px">まだ月報が公開されていません。毎月1日に前月分を公開予定です。</p>'

    import json as _json
    breadcrumb = {
        "@context": "https://schema.org", "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "トップ", "item": f"{SITE_URL}/"},
            {"@type": "ListItem", "position": 2, "name": "月報一覧", "item": canonical},
        ]
    }

    html = f'''<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="icon" href="/favicon.ico" sizes="48x48"><link rel="apple-touch-icon" href="/apple-touch-icon.png">
<title>{title}</title>
<meta name="description" content="{desc}">
<link rel="canonical" href="{canonical}">
<meta property="og:title" content="{title}">
<meta property="og:description" content="{desc}">
<meta property="og:url" content="{canonical}">
<meta property="og:type" content="website">
<meta property="og:site_name" content="船釣り予想">
<meta property="og:image" content="{OGP_DEFAULT_IMG}">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:site" content="@funatsuri_yoso">
<meta name="twitter:title" content="{title}">
<meta name="twitter:description" content="{desc}">
<meta name="twitter:image" content="{OGP_DEFAULT_IMG}">
<script type="application/ld+json">{_json.dumps(breadcrumb, ensure_ascii=False)}</script>
<link rel="stylesheet" href="../style.css">
<style>
.mh-hero{{background:var(--accent);color:#fff;padding:24px 18px 20px;text-align:center}}
.mh-hero h1{{font-size:22px;font-weight:800;margin:0 0 6px}}
.mh-hero-sub{{font-size:13px;color:rgba(255,255,255,0.8);margin:4px 0 0}}
.mh-month-block{{background:var(--card);border:1px solid var(--border);border-radius:var(--r,8px);padding:16px;margin-bottom:14px}}
.mh-month-label{{font-size:16px;font-weight:800;color:var(--accent);margin:0 0 12px;padding-bottom:6px;border-bottom:2px solid var(--cta)}}
.mh-fish-row{{display:flex;flex-wrap:wrap;gap:10px}}
.mh-card-fish{{display:inline-block;padding:10px 18px;background:var(--bg);border:1px solid var(--border);border-radius:8px;font-size:14px;font-weight:700;color:var(--accent);text-decoration:none}}
.mh-card-fish:hover{{background:var(--accent);color:#fff}}
</style>
</head>
<body>
{_v2_header_nav("monthly")}
<section class="mh-hero">
  <h1>関東船釣り 月報一覧</h1>
  <p class="mh-hero-sub">主要魚種の釣果を月別に集計・公開しています</p>
</section>
<div class="c">
  <p class="bread"><a href="/">トップ</a> &rsaquo; 月報一覧</p>
  <p style="font-size:14px;line-height:1.75;color:var(--text);margin:14px 0">関東船釣りの釣果データを魚種別・月別に集計した月報ページです。エリア別傾向・ベスト釣果・海況考察・翌月予測をまとめています。</p>
  {cards_html}
</div>
<footer style="margin-top:30px;padding:20px;background:var(--accent);color:#fff;text-align:center;font-size:12px">
  <p>© 2026 船釣り予想 funatsuri-yoso.com</p>
  <p style="margin-top:6px;font-size:11px"><a href="/pages/privacy.html" style="color:rgba(255,255,255,0.7)">プライバシーポリシー</a></p>
</footer>
</body>
</html>'''
    out_path = os.path.join(monthly_dir, "index.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[build_monthly_index] 完了 → {out_path}")


# ============================================================
# デッドリンク掃引（fish_area 孤児パージ後の参照元残留対策）
# ============================================================
def _sweep_dead_internal_links():
    """docs/ 配下の全 HTML から、実在しない fish/*.html・fish_area/*.html への
    <a> リンクを <span>（href 無し）に変換する。

    背景（2026-06-10）: build_fish_area_pages の孤児パージが fish_area HTML を
    削除しても、それをリンクしていた他ページは「直近7日に釣果がある時だけ再生成」
    のため残留し、デッドリンク化する（例: 6/8 に kintoki-hitachi.html がパージ
    されたが 6/7 生成の mahata-hitachi.html のチップが残った）。
    旧コード時代の日本語スラグリンク（fish_area/aji-佐島港.html 等）も同様に
    stale ページに残留していたため、生成完了後の最終パスとして毎回掃引する。

    変換は <a ...> → <span ...>（class 等の属性は保持・href のみ除去）で、
    チップ/カードの見た目を維持しつつ無効リンクだけを除去する。
    docs/ 全 HTML にネストアンカーは無い前提（不変条件 #11 で担保）。
    """
    from urllib.parse import unquote as _unquote
    _dir_files: dict = {}
    for _sub in ("fish", "fish_area", "ship"):
        _d = os.path.join(WEB_DIR, _sub)
        _dir_files[_sub] = (
            {f for f in os.listdir(_d) if f.endswith(".html")} if os.path.isdir(_d) else set()
        )

    # href はダブル/シングルクォート両対応（calendar.html はシングルクォート属性）
    # 前提: <a> の属性値に ">" を含まない（生成 HTML は属性に ">" を書かない）。
    # 万一含む場合はマッチせず素通りするが、不変条件 #44 が残存デッドリンクを検出する。
    _href_re = re.compile(
        r'<a\b([^>]*?)\shref=(["\'])(?:(?:\.\./)+|/)?(fish|fish_area|ship)/([^"\'/#?]+\.html)\2([^>]*)>(.*?)</a>',
        re.DOTALL,
    )

    swept_pages = 0
    swept_links = 0
    for root, _dirs, files in os.walk(WEB_DIR):
        for fn in files:
            if not fn.endswith(".html"):
                continue
            p = os.path.join(root, fn)
            try:
                with open(p, encoding="utf-8") as f:
                    html = f.read()
            except Exception:
                continue
            changed = 0

            def _fix(m):
                nonlocal changed
                attrs_pre, _q, kind, fname, attrs_post, inner = m.groups()
                exists = _unquote(fname) in _dir_files[kind]
                if exists:
                    return m.group(0)
                changed += 1
                return f"<span{attrs_pre}{attrs_post}>{inner}</span>"

            new_html = _href_re.sub(_fix, html)
            if changed:
                with open(p, "w", encoding="utf-8") as f:
                    f.write(new_html)
                swept_pages += 1
                swept_links += changed
    if swept_links:
        print(f"[dead-link-sweep] {swept_pages} ページから {swept_links} 件のデッドリンクを unlink")
    else:
        print("[dead-link-sweep] デッドリンクなし")


# ============================================================
# 404 ページ生成
# ============================================================
def build_404_page():
    """GitHub Pages 用カスタム 404（docs/404.html）。
    fish_area の孤児パージや過去リンクからの流入をトップ/一覧へ誘導する。"""
    html = f"""<!DOCTYPE html>
<html lang="ja"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="icon" href="/favicon.ico" sizes="48x48"><link rel="apple-touch-icon" href="/apple-touch-icon.png">
<meta name="robots" content="noindex">
<title>ページが見つかりません | 船釣り予想</title>
{GA_TAG}
<link rel="stylesheet" href="/style.css">
</head><body>
{_v2_header_nav('')}
<div class="c" style="text-align:center;padding:48px 16px">
<h1 style="font-size:48px;margin-bottom:8px">404</h1>
<h2 style="margin-bottom:16px">ページが見つかりません</h2>
<p style="color:var(--sub);margin-bottom:24px">お探しのページは移動または削除された可能性があります。<br>
釣果データの更新に伴い、一部の魚種×エリアページは統廃合されることがあります。</p>
<div style="display:flex;gap:10px;justify-content:center;flex-wrap:wrap">
<a href="/" style="display:inline-block;padding:12px 24px;background:var(--accent);color:#fff;border-radius:24px;font-weight:700;text-decoration:none">トップページへ</a>
<a href="/fish/" style="display:inline-block;padding:12px 24px;background:var(--card);border:1px solid var(--border);color:var(--accent);border-radius:24px;font-weight:700;text-decoration:none">魚種一覧</a>
<a href="/area/" style="display:inline-block;padding:12px 24px;background:var(--card);border:1px solid var(--border);color:var(--accent);border-radius:24px;font-weight:700;text-decoration:none">エリア一覧</a>
</div>
</div>
{_v2_footer()}
</body></html>"""
    with open(os.path.join(WEB_DIR, "404.html"), "w", encoding="utf-8") as f:
        f.write(html)
    print("404.html: 生成 → docs/")


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
    # fish/*.html・area/*.html（実ファイルベース・2026/05/14 修正）
    # 旧: data (valid_catches) + tackle/ship_info/area_description ベース → 過去実績のみのページが漏れる
    # 新: docs/fish/*.html / docs/area/*.html を直接スキャン → 生成済み全ファイルをカバー
    # index.html はトップ URL `/` で別掲載のため除外
    _SKIP = {"不明", "欠航"}  # 後方の参照用に残す
    fish_dir = os.path.join(WEB_DIR, "fish")
    if os.path.isdir(fish_dir):
        for fname in sorted(os.listdir(fish_dir)):
            if fname.endswith(".html") and fname != "index.html":
                urls.append((f"{SITE_URL}/fish/{fname}", "0.8", "daily"))
    # fish/index.html (魚種一覧ハブ)
    if os.path.isfile(os.path.join(fish_dir, "index.html")):
        urls.append((f"{SITE_URL}/fish/", "0.8", "daily"))
    area_dir = os.path.join(WEB_DIR, "area")
    if os.path.isdir(area_dir):
        for fname in sorted(os.listdir(area_dir)):
            if not fname.endswith(".html") or fname == "index.html":
                continue
            _area_stem = fname[:-5]
            # T40 (2026/05/26): build_point_pages 生成の薄ポイントページは sitemap から除外
            if _area_stem in _AREA_POINT_NOINDEX_SLUGS:
                continue
            # ディスク上 HTML を読んで noindex meta タグがあれば sitemap から除外
            # （一時スクリプト適用済み既存ファイルも含む）
            try:
                with open(os.path.join(area_dir, fname), encoding="utf-8") as _fp:
                    _ahead = _fp.read(2048)
                if 'name="robots"' in _ahead and "noindex" in _ahead:
                    continue
            except Exception:
                pass
            urls.append((f"{SITE_URL}/area/{fname}", "0.7", "daily"))
    # area/index.html (エリア一覧ハブ)
    if os.path.isfile(os.path.join(area_dir, "index.html")):
        urls.append((f"{SITE_URL}/area/", "0.7", "daily"))
    # fish_area/*.html（実ファイルベース・2026/05/14 修正）
    # 旧: data (valid_catches=直近7日 sparse) ベース → 過去実績のみのコンボが漏れる
    # 新: docs/fish_area/*.html を直接スキャン → build_fish_area_pages が生成した全件カバー
    # T39 (2026/05/25): _FA_NOINDEX_SLUGS に含まれる薄ページは sitemap から除外
    # T39-fix (2026/05/25): _FA_NOINDEX_SLUGS は当回 build_fish_area_pages が再生成した
    # ページのみを含む（再生成対象は7日窓に該当する fish_area のみ）。
    # 7日窓外のディスク上既存 HTML（手動 tmp_apply_fa_noindex.py 等で noindex 付与済み）は
    # in-memory セットに含まれないため、HTML を直接読んで noindex タグの有無で判定する。
    fa_dir = os.path.join(WEB_DIR, "fish_area")
    if os.path.isdir(fa_dir):
        for fname in sorted(os.listdir(fa_dir)):
            if not fname.endswith(".html"):
                continue
            _stem = fname[:-5]
            if _stem in _FA_NOINDEX_SLUGS:
                continue
            # ディスク上 HTML を読んで noindex meta タグがあれば sitemap から除外
            try:
                with open(os.path.join(fa_dir, fname), encoding="utf-8") as _fp:
                    _head = _fp.read(4096)  # head 部分だけで十分
                if 'name="robots"' in _head and "noindex" in _head:
                    continue
            except Exception:
                pass
            urls.append((f"{SITE_URL}/fish_area/{fname}", "0.8", "daily"))
    # ship/*.html（romaji_slug + ship_info あり・chowari_id なくても手動データなら掲載）
    # H2 (T22): _SHIP_NOINDEX_SLUGS に含まれる空ページは sitemap から除外
    # 2026/05/17: fishing_v_zero でも代替ソース（chowari等）あれば対象
    # 2026/05/22 B-task: build_ship_pages と対象集合を揃えるため exclude フィルタを追加
    # （旧: exclude チェック欠落で磯渡船・営業停止船等 54件分の 404 URL が sitemap に残存）
    for s in SHIPS:
        if s.get("exclude"):
            continue
        if s.get("fishing_v_zero"):
            _sp = s.get("source_priority") or []
            if not any(src != "fishing_v" for src in _sp):
                continue
        slug_s = s.get("romaji_slug")
        if slug_s and slug_s not in _SHIP_NOINDEX_SLUGS:
            urls.append((f"{SITE_URL}/ship/{slug_s}.html", "0.6", "weekly"))
    # x_post/*.html（日次釣果まとめ＝独自編集コンテンツ・2026/06/05 追加）
    # 当サイト唯一の純オリジナルコンテンツ。indexable（noindex なし）だが従来
    # sitemap 未収録でクローラーから見えにくかった。AdSense「有用性の低いコンテンツ」
    # 対策として最も価値の高い原本性コンテンツを審査クローラーに露出する。
    # 将来の安全弁として noindex タグがあれば除外。
    xpost_dir = os.path.join(WEB_DIR, "x_post")
    if os.path.isdir(xpost_dir):
        if os.path.isfile(os.path.join(xpost_dir, "index.html")):
            urls.append((f"{SITE_URL}/x_post/", "0.8", "daily"))
        for fname in sorted(os.listdir(xpost_dir)):
            if not fname.endswith(".html") or fname == "index.html":
                continue
            try:
                with open(os.path.join(xpost_dir, fname), encoding="utf-8") as _fp:
                    _xhead = _fp.read(2048)
                if 'name="robots"' in _xhead and "noindex" in _xhead:
                    continue
            except Exception:
                pass
            # 日付付きアーカイブは公開後に変化しないため changefreq=monthly
            urls.append((f"{SITE_URL}/x_post/{fname}", "0.7", "monthly"))
    # pages/*.html（静的ページ・2026/06/05 追加）
    # フッターリンク済みだが sitemap 未収録だった。AdSense はプライバシーポリシーを
    # 確実に発見したいため明示収録する。
    for _pg in ("about", "faq", "contact", "privacy", "terms"):
        if os.path.isfile(os.path.join(WEB_DIR, "pages", f"{_pg}.html")):
            urls.append((f"{SITE_URL}/pages/{_pg}.html", "0.5", "monthly"))
    # premium/plan.html は noindex（薄い販売ページ・2026/06/05）のため sitemap 非収録
    # monthly/**/*.html（月報ページ・YYYY-MM/{romaji}.html）
    # noindex タグがあれば除外。index.html（ハブ）は優先度 0.7/weekly で収録。
    _monthly_dir = os.path.join(WEB_DIR, "monthly")
    import re as _re_sitemap
    if os.path.isdir(_monthly_dir):
        # ハブ index.html
        if os.path.isfile(os.path.join(_monthly_dir, "index.html")):
            urls.append((f"{SITE_URL}/monthly/", "0.7", "weekly"))
        # 月別サブディレクトリをスキャン
        for _ym in sorted(os.listdir(_monthly_dir), reverse=True):
            if not _re_sitemap.match(r"^\d{4}-\d{2}$", _ym):
                continue
            _ym_dir = os.path.join(_monthly_dir, _ym)
            if not os.path.isdir(_ym_dir):
                continue
            for _mfname in sorted(os.listdir(_ym_dir)):
                if not _mfname.endswith(".html"):
                    continue
                try:
                    with open(os.path.join(_ym_dir, _mfname), encoding="utf-8") as _mfp:
                        _mhead = _mfp.read(2048)
                    if 'name="robots"' in _mhead and "noindex" in _mhead:
                        continue
                except Exception:
                    pass
                urls.append((f"{SITE_URL}/monthly/{_ym}/{_mfname}", "0.8", "monthly"))
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
    """V2 style.css を docs/ に生成する（design/V2/style.css を読んで同期）"""
    design_css_path = os.path.join(_BASE_DIR, "design", "V2", "style.css")
    if not os.path.exists(design_css_path):
        print(f"[WARN] design/V2/style.css が見つかりません: {design_css_path}")
        return
    with open(design_css_path, "r", encoding="utf-8") as f:
        css = f.read()
    if False:  # 旧インラインCSS（参照用に保持・実際には読まれない）
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


def _build_share_meta(title, desc, url, og_image=None, og_type="website"):
    """OGP + twitter:card 共通メタタグブロックを返す。

    - title / desc: HTML エスケープ済みの想定（呼び出し側で f-string 中の文字を渡す既存規約に準拠）
    - url: 絶対 URL（SITE_URL から始まる完全 URL）
    - og_image: 省略時は OGP_DEFAULT_IMG。絶対 URL 必須
    - og_type: "website" / "article" 等
    """
    img = og_image or OGP_DEFAULT_IMG
    return (
        f'<meta property="og:title" content="{title}">'
        f'<meta property="og:description" content="{desc}">'
        f'<meta property="og:url" content="{url}">'
        f'<meta property="og:type" content="{og_type}">'
        f'<meta property="og:site_name" content="船釣り予想">'
        f'<meta property="og:image" content="{img}">'
        f'<meta property="og:image:width" content="1200">'
        f'<meta property="og:image:height" content="630">'
        f'<meta name="twitter:card" content="summary_large_image">'
        f'<meta name="twitter:site" content="{TWITTER_HANDLE}">'
        f'<meta name="twitter:title" content="{title}">'
        f'<meta name="twitter:description" content="{desc}">'
        f'<meta name="twitter:image" content="{img}">'
    )


def _build_share_buttons(share_text, share_url, hashtags="船釣り,釣果"):
    """X シェアボタン + フォローボタンの HTML を返す。

    - share_text / share_url / hashtags は urllib.parse.quote でエンコード
    - <a> を含む block の外側で使うこと（ネストアンカー禁止規約）
    """
    from urllib.parse import quote
    intent_url = (
        "https://twitter.com/intent/tweet?"
        f"text={quote(share_text)}&url={quote(share_url)}&hashtags={quote(hashtags)}"
    )
    handle = TWITTER_HANDLE.lstrip("@")
    follow_url = f"https://twitter.com/intent/follow?screen_name={handle}"
    return (
        '<div class="share-bar" role="group" aria-label="シェア">'
        f'<a class="share-x" href="{intent_url}" target="_blank" rel="noopener nofollow" '
        f'aria-label="X（旧Twitter）でシェア">𝕏 でシェア</a>'
        f'<a class="share-follow" href="{follow_url}" target="_blank" rel="noopener nofollow" '
        f'aria-label="@{handle} をフォロー">フォロー</a>'
        '</div>'
    )


def _latest_x_post_image_url():
    """docs/x_post/ 配下の最新 YYYY-MM-DD.png の絶対 URL を返す。なければ None。"""
    d = os.path.join(WEB_DIR, "x_post")
    if not os.path.isdir(d):
        return None
    pat = re.compile(r"^(\d{4}-\d{2}-\d{2})\.png$")
    dates = []
    for fn in os.listdir(d):
        m = pat.match(fn)
        if m:
            dates.append(m.group(1))
    if not dates:
        return None
    dates.sort(reverse=True)
    return f"{SITE_URL}/x_post/{dates[0]}.png"


def _resolve_fish_ogp_image(fish):
    """魚種別 og:image を docs/assets/fish/{slug}/{slug}_photo.png → _illustration.png → 共通ロゴ
    の段階フォールバックで返す。webp は X 互換性のため使わず png 優先。"""
    try:
        slug = fish_img_slug(fish)
    except Exception:
        return OGP_DEFAULT_IMG
    base = os.path.join(WEB_DIR, "assets", "fish", slug)
    for suffix in ("_photo.png", "_illustration.png"):
        path = os.path.join(base, f"{slug}{suffix}")
        if os.path.isfile(path):
            return f"{SITE_URL}/assets/fish/{slug}/{slug}{suffix}"
    return OGP_DEFAULT_IMG


def _ensure_ogp_default_image():
    """docs/ogp-default.png が未配置なら最新 x_post PNG をコピーして fallback 画像を作る。

    crawler.py 起動時 / build 系の冒頭で呼ぶ。共通ロゴ画像が未作成のうちでも
    リッチカードが描画されるようにする暫定対応。
    """
    import shutil as _shutil
    dst = os.path.join(WEB_DIR, "ogp-default.png")
    if os.path.isfile(dst):
        return
    src_url = _latest_x_post_image_url()
    if not src_url:
        return
    src_name = src_url.rsplit("/", 1)[-1]
    src_path = os.path.join(WEB_DIR, "x_post", src_name)
    if not os.path.isfile(src_path):
        return
    try:
        os.makedirs(WEB_DIR, exist_ok=True)
        _shutil.copy2(src_path, dst)
        print(f"[ogp] {src_name} を {dst} に複製（共通 OGP fallback）")
    except Exception as e:
        print(f"[ogp] fallback 複製失敗: {e}")


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
<link rel="icon" href="/favicon.ico" sizes="48x48"><link rel="apple-touch-icon" href="/apple-touch-icon.png">
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
        f'<a href="/forecast/"{prem}>有料</a>'
        '</nav>'
        '</div>'
        '</header>'
        '<nav class="bottom-nav" aria-label="ボトムナビゲーション">'
        f'<a href="/"{idx}>{svg_catch}<span>釣果</span></a>'
        f'<a href="/fish/"{fish}>{svg_fish}<span>魚種</span></a>'
        f'<a href="/area/"{area}>{svg_area}<span>エリア</span></a>'
        f'<a href="/calendar.html"{cal}>{svg_cal}<span>カレンダー</span></a>'
        f'<a href="/forecast/" {prem_cls}>{svg_prem}<span>有料</span></a>'
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

    # --ships-only: data/V2/*.csv から全釣果を読み込み、船宿ページのみ再生成（クロールなし）
    if "--ships-only" in _sys.argv:
        crawled_at = datetime.now(JST).replace(tzinfo=None).strftime("%Y/%m/%d %H:%M")
        print("=== 船宿ページ再生成（--ships-only: data/V2/*.csv から読み込み）===")
        # CSV 行を build_ship_pages が期待する catches 形式に変換
        # catches 形式: fish=[str], count_range={max, min, avg}, is_cancellation=bool等
        def _csv_to_catch(r):
            fish_str = (r.get("tsuri_mono") or "").strip()
            fish_list = [fish_str] if fish_str and fish_str not in ("欠航", "不明", "", "NULL") else []
            try: cnt_max = float(r.get("cnt_max") or 0) or None
            except: cnt_max = None
            try: cnt_min = float(r.get("cnt_min") or 0) or None
            except: cnt_min = None
            try: cnt_avg = float(r.get("cnt_avg") or 0) or None
            except: cnt_avg = None
            try: sz_min = float(r.get("size_min") or 0) or None
            except: sz_min = None
            try: sz_max = float(r.get("size_max") or 0) or None
            except: sz_max = None
            return {
                "ship": r.get("ship", ""),
                "area": r.get("area", ""),
                "date": r.get("date", ""),
                "fish": fish_list,
                "count_range": {"max": cnt_max, "min": cnt_min, "avg": cnt_avg},
                "size_range_cm": {"min": sz_min, "max": sz_max},
                "point_place1": r.get("point_place1"),
                "is_cancellation": r.get("is_cancellation") == "1",
            }
        raw_rows = list(_load_historical_catches())
        valid_catches = [_csv_to_catch(r) for r in raw_rows]
        print(f"釣果レコード変換: {len(valid_catches)}件")
        build_ship_pages(valid_catches, crawled_at)
        build_ship_redirects()
        build_sitemap(valid_catches)
        print("=== 船宿ページ再生成完了 ===")
        return

    # --area-only: CSV から area ページを再生成（クロールなし・thin path フォールバック検証用）
    if "--area-only" in _sys.argv:
        crawled_at = datetime.now(JST).replace(tzinfo=None).strftime("%Y/%m/%d %H:%M")
        print("=== エリアページ再生成（--area-only: data/V2/*.csv から読み込み）===")
        def _csv_to_catch_a(r):
            fish_str = (r.get("tsuri_mono") or "").strip()
            fish_list = [fish_str] if fish_str and fish_str not in ("欠航", "不明", "", "NULL") else []
            try: cnt_max = float(r.get("cnt_max") or 0) or None
            except: cnt_max = None
            try: cnt_min = float(r.get("cnt_min") or 0) or None
            except: cnt_min = None
            try: cnt_avg = float(r.get("cnt_avg") or 0) or None
            except: cnt_avg = None
            return {
                "ship": r.get("ship", ""),
                "area": r.get("area", ""),
                "date": r.get("date", ""),
                "fish": fish_list,
                "fish_raw": r.get("fish_raw", "") or (fish_list[0] if fish_list else ""),
                "count_range": {"max": cnt_max, "min": cnt_min, "avg": cnt_avg, "is_boat": r.get("is_boat") == "1"},
                "count_avg": cnt_avg,
                "point_place1": r.get("point_place1") or None,
                "is_cancellation": r.get("is_cancellation") == "1",
            }
        raw_rows = list(_load_historical_catches())
        valid_catches = [_csv_to_catch_a(r) for r in raw_rows]
        with open("history.json", encoding="utf-8") as _f:
            history = json.load(_f)
        weather_data = load_weather_data()
        os.makedirs(WEB_DIR, exist_ok=True)
        # area-all-fish セクション用に hist 派生集計を算出
        _fish_area_summary_aonly = compute_fish_area_summary(raw_rows)
        _area_top_fishes_aonly = compute_area_top_fishes(raw_rows)
        build_area_pages(valid_catches, history, crawled_at, weather_data,
                         hist_rows=raw_rows,
                         fish_area_summary=_fish_area_summary_aonly,
                         area_top_fishes=_area_top_fishes_aonly)
        print("=== エリアページ再生成完了 ===")
        return

    # --fish-index-only: CSV から index.html + fish pages を再生成（クロールなし）
    # T39 で追加: コマセシミュレーターカード (T-4) と マダイページ sim リンク (T-5) の反映用
    if "--fish-index-only" in _sys.argv:
        crawled_at = datetime.now(JST).replace(tzinfo=None).strftime("%Y/%m/%d %H:%M")
        print("=== index.html + fish pages 再生成（--fish-index-only: data/V2/*.csv から読み込み）===")
        def _csv_to_catch_fi(r):
            fish_str = (r.get("tsuri_mono") or "").strip()
            fish_list = [fish_str] if fish_str and fish_str not in ("欠航", "不明", "", "NULL") else []
            try: cnt_max = float(r.get("cnt_max") or 0) or None
            except: cnt_max = None
            try: cnt_min = float(r.get("cnt_min") or 0) or None
            except: cnt_min = None
            try: cnt_avg = float(r.get("cnt_avg") or 0) or None
            except: cnt_avg = None
            try: sz_min = float(r.get("size_min") or 0) or None
            except: sz_min = None
            try: sz_max = float(r.get("size_max") or 0) or None
            except: sz_max = None
            return {
                "ship": r.get("ship", ""),
                "area": r.get("area", ""),
                "date": r.get("date", ""),
                "fish": fish_list,
                "fish_raw": r.get("fish_raw", "") or (fish_list[0] if fish_list else ""),
                "count_range": {"max": cnt_max or 0.0, "min": cnt_min or 0.0, "avg": cnt_avg or 0.0, "is_boat": r.get("is_boat") == "1"},
                "count_avg": cnt_avg,
                "size_range_cm": {"min": sz_min, "max": sz_max},
                "point_place1": r.get("point_place1") or None,
                "is_cancellation": r.get("is_cancellation") == "1",
            }
        raw_rows = list(_load_historical_catches())
        valid_catches = [_csv_to_catch_fi(r) for r in raw_rows]
        print(f"釣果レコード変換: {len(valid_catches)}件")
        with open("history.json", encoding="utf-8") as _f:
            history = json.load(_f)
        weather_data = load_weather_data()
        forecast_data = None
        if os.path.exists("forecast.json"):
            try:
                with open("forecast.json", encoding="utf-8") as _f:
                    forecast_data = json.load(_f)
            except Exception as _e:
                print(f"forecast.json load failed: {_e}")
        if forecast_data:
            weather_data["_forecast_data"] = forecast_data
        os.makedirs(WEB_DIR, exist_ok=True)
        build_style_css()
        build_main_js()
        _ensure_ogp_default_image()
        now_fi = datetime.now(JST).replace(tzinfo=None)
        with open(os.path.join(WEB_DIR, "index.html"), "w", encoding="utf-8") as _f:
            _f.write(build_html(valid_catches, crawled_at, history, weather_data))
        print("index.html 生成完了")
        _fi_hist_rows = raw_rows
        _fi_fish_area_summary = compute_fish_area_summary(_fi_hist_rows)
        _fi_fish_top_areas = compute_fish_top_areas(_fi_hist_rows)
        build_fish_pages(valid_catches, history, crawled_at,
                         hist_rows=_fi_hist_rows,
                         fish_area_summary=_fi_fish_area_summary,
                         fish_top_areas=_fi_fish_top_areas)
        print("fish pages 生成完了")
        _fi_recent7 = _load_recent_catches_for_index(now_fi, days=7)
        _fi_cutoff = (now_fi - timedelta(days=6)).strftime("%Y/%m/%d")
        _fi_data_recent = [c for c in valid_catches if c.get("date", "") >= _fi_cutoff]
        _fi_seen = {(c.get("ship"), c.get("date"), c.get("fish_raw", "")) for c in _fi_data_recent}
        _fi_merged2 = list(_fi_data_recent)
        for _c in _fi_recent7:
            _k = (_c.get("ship"), _c.get("date"), _c.get("fish_raw", ""))
            if _k not in _fi_seen:
                _fi_merged2.append(_c)
                _fi_seen.add(_k)
        _fi_summary_keys: dict = {}
        _SKIP_FISH_FI = {"不明", "欠航"}
        for _c in _fi_merged2:
            for _f in _c.get("fish", []):
                if _f not in _SKIP_FISH_FI and not _f.isdigit():
                    _fi_summary_keys.setdefault(_f, []).append(_c)
        _fi_tackle_data = load_fish_tackle()
        for _f in _fi_tackle_data.keys():
            if _f in _FISH_ROMAJI and _f not in _fi_summary_keys:
                _fi_summary_keys[_f] = []
        build_fish_index_html(
            now=now_fi,
            hist_rows=_fi_hist_rows,
            fish_area_summary=_fi_fish_area_summary,
            recent7=_fi_recent7,
            fish_summary=_fi_summary_keys,
            crawled_at=crawled_at,
        )
        print("fish/index.html 生成完了")
        build_sitemap(crawled_at)
        print("=== index.html + fish pages 再生成完了 ===")
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
        # OGP fallback: docs/ogp-default.png が未配置なら最新 x_post PNG を複製
        _ensure_ogp_default_image()
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

    # 2026/05/17: 釣りビジョン sid=None の船宿はクロール対象外（chowari 等の代替ソース経由）
    # 修正前: 150隻分の HTTP 404 リクエスト（2-3分のロス + ログ汚染）
    skipped_no_sid = 0
    for s in active_ships:
        source = s.get("source", "fishing-v")
        # 釣りビジョン経由 だが sid=None → 代替ソース利用（chowari 等）なのでスキップ
        if source != "gyo" and not s.get("sid"):
            skipped_no_sid += 1
            continue
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
    if skipped_no_sid:
        print(f"\n釣りビジョン sid=None スキップ: {skipped_no_sid}隻（chowari 等別ソース利用）")

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
    # エリア正規化（表示層）: 当日クロール分も正規港名に統合（ソース all_catches/CSV は原表記保持）
    for _c in valid_catches:
        _c["area"] = _canonicalize_area(_c.get("area", ""))

    history = load_history()
    history = update_history(valid_catches, history)

    # 日次CSV蓄積（V2形式 → data/V2/）
    csv_added = save_daily_csv(all_catches)
    if csv_added:
        print(f"CSV保存: {csv_added} 件追記 → {_DATA_DIR}/")

    # T31 (2026/05/12) リカバリ: catches_raw.json にも同期追記
    # save_daily_csv との二重書きで、--export-csv の wipe regression を防止
    raw_added = append_to_catches_raw(all_catches)
    if raw_added:
        print(f"catches_raw.json: {raw_added} 件追記")

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
    # OGP fallback: docs/ogp-default.png が未配置なら最新 x_post PNG を複製
    _ensure_ogp_default_image()
    with open(os.path.join(WEB_DIR, "index.html"), "w", encoding="utf-8") as f:
        f.write(build_html(valid_catches, crawled_at, history, weather_data))
    # T38-A9: hist_rows を1回ロードして各 build_* 関数で共有（重複ロード排除）
    _shared_hist_rows = _load_historical_catches()
    _shared_fish_area_summary = compute_fish_area_summary(_shared_hist_rows)
    _shared_fish_top_areas = compute_fish_top_areas(_shared_hist_rows)
    _shared_area_top_fishes = compute_area_top_fishes(_shared_hist_rows)
    # fish_area を先に生成 → build_fish_pages の area-cmp / build_area_pages の
    # _fish_area_link_or_fish が当日生成された fish_area ページを正しく検出できる
    build_fish_area_pages(valid_catches, crawled_at, history,
                          hist_rows=_shared_hist_rows,
                          fish_area_summary=_shared_fish_area_summary,
                          fish_top_areas=_shared_fish_top_areas)
    build_fish_pages(valid_catches, history, crawled_at,
                     hist_rows=_shared_hist_rows,
                     fish_area_summary=_shared_fish_area_summary,
                     fish_top_areas=_shared_fish_top_areas)
    # T38-C: fish/index・area/index は fish_area HTML 生成後に呼ぶ
    # （_fa_exists() が全 fish_area HTML を正確に参照するため）
    _shared_recent7 = _load_recent_catches_for_index(now, days=7)
    # fish_summary（今週の魚種キーセット）を build_fish_index_html 用に再構築。
    # build_fish_pages 内と同等の軽量集計（valid_catches から直近7日を除く → 共通処理）
    _fi_cutoff = (now - timedelta(days=6)).strftime("%Y/%m/%d")
    _fi_data_recent = [c for c in valid_catches if c.get("date", "") >= _fi_cutoff]
    _fi_seen = {(c.get("ship"), c.get("date"), c.get("fish_raw", "")) for c in _fi_data_recent}
    _fi_merged = list(_fi_data_recent)
    for _c in _shared_recent7:
        _k = (_c.get("ship"), _c.get("date"), _c.get("fish_raw", ""))
        if _k not in _fi_seen:
            _fi_merged.append(_c)
            _fi_seen.add(_k)
    _shared_fish_summary_keys: dict = {}
    _SKIP_FISH_MAIN = {"不明", "欠航", "NULL"}
    for _c in _fi_merged:
        for _f in _c.get("fish", []):
            if _f not in _SKIP_FISH_MAIN and not _f.isdigit():
                _shared_fish_summary_keys.setdefault(_f, []).append(_c)
    # fish_tackle.json で説明がある魚種もキーセットに追加（build_fish_pages と整合）
    _shared_tackle_data = load_fish_tackle()
    for _f in _shared_tackle_data.keys():
        if _f in _FISH_ROMAJI and _f not in _shared_fish_summary_keys:
            _shared_fish_summary_keys[_f] = []
    build_fish_index_html(
        now=now,
        hist_rows=_shared_hist_rows,
        fish_area_summary=_shared_fish_area_summary,
        recent7=_shared_recent7,
        fish_summary=_shared_fish_summary_keys,
        crawled_at=crawled_at,
    )
    build_area_pages(valid_catches, history, crawled_at, weather_data,
                     hist_rows=_shared_hist_rows,
                     fish_area_summary=_shared_fish_area_summary,
                     area_top_fishes=_shared_area_top_fishes)
    # 2026/05/17: Kanso由来ポイント（剣崎沖・大原沖等）の area_pages 簡易生成
    # build_area_pages の対象外（ships.json area のみ）を補完
    build_point_pages(_shared_hist_rows, crawled_at=crawled_at)
    build_area_index_html(
        now=now,
        hist_rows=_shared_hist_rows,
        fish_area_summary=_shared_fish_area_summary,
        area_top_fishes=_shared_area_top_fishes,
        recent7=_shared_recent7,
        crawled_at=crawled_at,
    )
    # エリア正規化で統合された旧 area ページを canonical へリダイレクト
    build_area_redirects()
    build_ship_pages(valid_catches, crawled_at)
    build_ship_redirects()
    with open(os.path.join(WEB_DIR, "calendar.html"), "w", encoding="utf-8") as f:
        f.write(build_calendar_page(crawled_at))
    # 月報生成（フルクロール経路のみ・--html-only はこのコードパスに到達しない）
    try:
        build_monthly_pages(crawled_at)
        build_monthly_index(crawled_at)
    except Exception as _e_monthly:
        print(f"[WARN] build_monthly_pages/index 失敗（スキップ）: {_e_monthly}")
    build_sitemap(valid_catches)
    build_premium_plan_page()
    build_404_page()
    # 全ページ生成完了後の最終パス: 孤児パージ等で消えた fish/fish_area への
    # デッドリンクを stale ページから unlink（2026-06-10）
    try:
        _sweep_dead_internal_links()
    except Exception as _e_sweep:
        print(f"[WARN] dead-link-sweep 失敗（スキップ）: {_e_sweep}")

    # ── X 投稿用コンテンツ生成（--html-only のときはスキップ）──
    # --html-only パスはこのブロックに到達しないが、念のため argv チェックも付ける
    if "--html-only" not in _sys.argv:
        try:
            from x_post.context_builder import build_context as _build_ctx
            from x_post.template_picker import (
                pick_highlight as _pick_hl,
                pick_ocean as _pick_oc,
                pick_fish_templates as _pick_ft,
            )
            from x_post.text_generator import (
                render_template as _render_tpl,
                render_section as _render_sec,
                build_commentary_html as _build_comm,
                build_commentary_blocks as _build_blocks,
            )
            from x_post.generate_image import create as _create_img
            from x_post.build_daily_page import build as _build_daily
            from x_post.build_rss import build as _build_rss

            _today_str = now.strftime("%Y-%m-%d")
            _x_post_dir = os.path.join(WEB_DIR, "x_post")
            os.makedirs(_x_post_dir, exist_ok=True)

            print("\n[x_post] ctx 組立...")
            _ctx = _build_ctx(
                valid_catches, history, ANALYSIS_DB,
                _today_str,
                weather_dir=os.path.join("weather"),
            )

            print("[x_post] 文型選択...")
            _h_tpl = _pick_hl(_ctx)
            _s_tpl = _pick_oc(_ctx)
            _f_tpls = _pick_ft(_ctx)

            print("[x_post] 散文生成...")
            _hl_text = _render_tpl(_h_tpl, _ctx)
            _oc_text = _render_tpl(_s_tpl, _ctx)
            _fi_text = _render_sec(_f_tpls, _ctx)
            _comm_html = _build_comm(_hl_text, _oc_text, _fi_text, _ctx)
            # 各セクション内挿入用 dict（冒頭集中問題の修正）
            _comm_blocks = _build_blocks(_hl_text, _oc_text, _fi_text, _ctx)

            _png_url = f"https://funatsuri-yoso.com/x_post/{_today_str}.png"
            _daily_url = f"https://funatsuri-yoso.com/x_post/{_today_str}.html"
            _feed_path = os.path.join(WEB_DIR, "feed.xml")

            print("[x_post] PNG 生成...")
            _create_img(_ctx, output_path=os.path.join(_x_post_dir, f"{_today_str}.png"))

            print("[x_post] daily HTML 生成...")
            _build_daily(
                _ctx, _comm_blocks,
                output_path=os.path.join(_x_post_dir, f"{_today_str}.html"),
                png_url=_png_url,
            )

            print("[x_post] feed.xml 生成...")
            _build_rss(
                _ctx,
                png_url=_png_url,
                daily_url=_daily_url,
                output_path=_feed_path,
                existing_feed_path=_feed_path if os.path.exists(_feed_path) else None,
            )

            print(f"[x_post] 完了 → docs/x_post/{_today_str}.html / docs/feed.xml")
        except Exception as _e:
            print(f"[x_post] ERROR: {_e}")
            import traceback as _tb
            _tb.print_exc()

        # index.html は日次生成失敗時もアーカイブから再構築して常に最新を保つ
        try:
            print("[x_post] index.html 再構築...")
            from x_post.build_index_page import build_index as _build_x_index
            _x_post_dir2 = os.path.join(WEB_DIR, "x_post")
            _build_x_index(
                output_path=os.path.join(_x_post_dir2, "index.html"),
                docs_x_post_dir=_x_post_dir2,
            )
            print("[x_post] index.html 完了")
        except Exception as _e2:
            print(f"[x_post] index rebuild ERROR: {_e2}")

        # 自己修復: CI 失敗で欠落した直近の x_post 日を catches CSV から補完。
        # 日次 crawl が validate 失敗で止まり復旧が翌 JST 日にずれ込むと、run 日基準の
        # x_post が「失敗した当日」分を永久に欠落させる問題への恒久対策（valid_catches は
        # 当日スナップショットで過去日を持たないため None を渡し CSV から再ロードさせる）。
        try:
            from x_post.backfill import backfill_recent as _backfill_recent
            _bf = _backfill_recent(now=now, lookback=10, valid_catches=None,
                                   history=history, verbose=True)
            if _bf:
                print(f"[x_post] 欠落バックフィル {len(_bf)}件: {_bf}")
        except Exception as _e3:
            print(f"[x_post] backfill ERROR: {_e3}")

    print(f"\n=== 完了 ===")
    _today_label = f"当日: {len(today_all)} 件" if today_all else f"当日0件→全件フォールバック: {len(all_catches)} 件"
    print(f"釣果: {len(all_catches)} 件（有効: {len(valid_catches)} / 異常値: {anomaly_count} / 重複除外: {dup_removed}）")
    print(f"出力: {_today_label}（catches.json）")
    print(f"エラー: {errors or 'なし'}")
    print(f"出力: docs/ (index.html / fish/*.html / area/*.html / fish_area/*.html / sitemap.xml / premium/plan.html / CNAME)")

if __name__ == "__main__":
    main()
