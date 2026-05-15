"""湾別海況 X投稿ドラフト生成スクリプト

Usage:
    python tools/build_bay_kaikyou.py 2026/05/16    # 指定日の翌日海況を生成
    python tools/build_bay_kaikyou.py               # 引数なしで明日分

Output:
    dustbox/bay_kaikyou_YYYY-MM-DD.md   # コピペ用 markdown
"""
import csv, glob, json, sys, sqlite3, urllib.request, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')
from collections import Counter, defaultdict
from datetime import datetime, timedelta, date
from pathlib import Path

# ============================================================
# 湾定義
# ============================================================

# 投稿順 = 都心から遠い順
BAY_ORDER = [
    "茨城", "千葉外房", "相模湾", "千葉内房",
    "神奈川東京湾", "千葉東京湾内", "東京",
]

# forecast.json での area キー (mojibake せず) を確認するため辞書化
BAY_FORECAST_KEY = {
    "茨城": "茨城",
    "千葉外房": "千葉・外房",
    "千葉内房": "千葉・内房",
    "千葉東京湾内": "千葉・東京湾内",
    "東京": "東京",
    "神奈川東京湾": "神奈川・東京湾",
    "相模湾": "神奈川・相模湾",
}

# 湾表示名（投稿タイトル）
BAY_DISPLAY = {
    "茨城": "茨城エリア",
    "千葉外房": "千葉・外房",
    "千葉内房": "千葉・内房",
    "千葉東京湾内": "千葉・東京湾内",
    "東京": "東京",
    "神奈川東京湾": "神奈川・東京湾",
    "相模湾": "神奈川・相模湾",
}

# 潮位取得用座標（湾代表点）
BAY_COORDS = {
    "茨城": (36.0, 140.6),
    "千葉外房": (35.2, 140.4),
    "千葉内房": (35.1, 139.9),
    "千葉東京湾内": (35.6, 139.95),
    "東京": (35.6, 139.85),
    "神奈川東京湾": (35.33, 139.65),
    "相模湾": (35.18, 139.5),
}

# ハッシュタグ（湾ごと）
BAY_HASHTAGS = {
    "茨城": "#船釣り #茨城 #鹿島 #日立久慈 #大洗 #波崎",
    "千葉外房": "#船釣り #外房 #大原 #飯岡 #勝浦 #片貝",
    "千葉内房": "#船釣り #内房 #富津 #金谷 #保田",
    "千葉東京湾内": "#船釣り #東京湾 #浦安 #船橋",
    "東京": "#船釣り #東京湾 #羽田 #平和島 #東葛西",
    "神奈川東京湾": "#船釣り #東京湾 #金沢八景 #小柴 #久里浜 #長井港 #松輪 #佐島",
    "相模湾": "#船釣り #相模湾 #葉山 #茅ヶ崎 #平塚 #小田原 #佐島",
}

# 隣接同海域参照ルール（自データ <10件のとき参照）
BAY_FALLBACK = {
    "千葉外房": "茨城",         # 外洋接続
    "東京": "千葉東京湾内",      # 東京湾奥共通
    # 静岡は流用不可（伊豆半島で隔絶）→ 投稿対象外
}

# CSV area名 → 湾マッピング
AREA_TO_BAY = {
    '鹿島港': '茨城', '波崎港': '茨城', '大洗港': '茨城', '日立久慈港': '茨城',
    '飯岡港': '千葉外房', '大原港': '千葉外房', '片貝港': '千葉外房',
    '勝浦川津港': '千葉外房', '御宿岩和田港': '千葉外房', '天津港': '千葉外房',
    '洲崎港': '千葉外房',
    '富津港': '千葉内房', '金谷港': '千葉内房', '富浦港': '千葉内房', '保田港': '千葉内房',
    '浦安港': '千葉東京湾内', '浦安': '千葉東京湾内', '船橋港': '千葉東京湾内',
    '羽田港': '東京', '羽田': '東京', '平和島港': '東京', '平和島': '東京',
    '東西葛西港': '東京', '東葛西': '東京',
    '江戸川放水路・原木中山': '東京', '江戸川放水路･原木中山': '東京',
    '横浜本牧港': '神奈川東京湾', '横浜新山下港': '神奈川東京湾',
    '横浜港･新山下': '神奈川東京湾', '横浜港・新山下': '神奈川東京湾',
    '金沢八景': '神奈川東京湾', '金沢八景港': '神奈川東京湾',
    '小柴港': '神奈川東京湾',
    '久里浜港': '神奈川東京湾', '長井港': '神奈川東京湾',
    '長井新宿港': '神奈川東京湾', '長井漆山港': '神奈川東京湾',
    '松輪江奈港': '神奈川東京湾', '松輪間口港': '神奈川東京湾',
    '佐島港': '神奈川東京湾', '佐島': '神奈川東京湾',
    '剣崎港': '神奈川東京湾',
    '久比里港': '神奈川東京湾',
    '鴨居・大室港': '神奈川東京湾', '鴨居大室港': '神奈川東京湾',
    '小坪港': '神奈川東京湾',
    '小網代港': '神奈川東京湾',
    '長浦': '神奈川東京湾',
    '葉山あぶずり港': '相模湾', '茅ヶ崎港': '相模湾', '平塚港': '相模湾',
    '大磯港': '相模湾', '小田原早川港': '相模湾',
}

# kanso/water_color キーワード → ラベル
WC_KEYWORDS = [
    ('青々', '澄み'), ('青い', '澄み'), ('クリア', '澄み'),
    ('透明度', '澄み'), ('真っ青', '澄み'), ('潮色良', '澄み'),
    ('ササ濁', 'ササ濁り'), ('薄濁', 'ササ濁り'), ('うす濁', 'ササ濁り'),
    ('やや濁', 'ササ濁り'),
    ('濁り強', '濁り強'), ('かなり濁', '濁り強'), ('濁ってる', '濁り'),
    ('濁って', '濁り'), ('泥濁', '濁り強'), ('茶濁', '濁り'),
]

# 風向 deg → 16方位
def wind_compass(deg):
    if deg is None:
        return ""
    dirs = ['北','北北東','北東','東北東','東','東南東','南東','南南東',
            '南','南南西','南西','西南西','西','西北西','北西','北北西']
    return dirs[int((deg + 11.25) / 22.5) % 16]

# ============================================================
# 濁り度集計
# ============================================================

def aggregate_turbidity(target_date, min_records=10):
    """前日2日のCSVから湾別濁り度を集計。

    target_date: YYYY/MM/DD 形式（target_date とその前日の2日分を合算）
    返り値: {bay: {"label": "🟡薄濁り中心", "n": 14, "from": "自データ"}}
    """
    # 2日窓: target_date と 1日前
    prev_date = (datetime.strptime(target_date, '%Y/%m/%d').date() - timedelta(days=1)).strftime('%Y/%m/%d')
    target_dates = {target_date, prev_date}

    files = sorted(glob.glob('data/V2/2026-*.csv'))[-2:]
    bay_wc = defaultdict(Counter)
    bay_total = Counter()

    for f in files:
        with open(f, encoding='utf-8') as fp:
            for r in csv.DictReader(fp):
                if r.get('date', '') not in target_dates:
                    continue
                bay = AREA_TO_BAY.get(r.get('area', ''))
                if not bay:
                    continue
                bay_total[bay] += 1
                wc = (r.get('water_color') or '').strip()
                if wc:
                    bay_wc[bay][wc] += 1
                kanso = (r.get('kanso_raw') or '') + ' ' + (r.get('suishoku_raw') or '')
                for kw, label in WC_KEYWORDS:
                    if kw in kanso:
                        bay_wc[bay][label] += 0.5
                        break

    def classify(counter, total):
        """釣り人ドメイン: 澄み水は記載されにくく、濁った時だけ kanso に書かれる。
        したがって「未言及=通常水色(澄み〜薄濁り)」とみなし、母数=報告総数で判定する。
        """
        if total == 0:
            return None
        sumi = counter.get('澄み', 0)
        usu = counter.get('薄濁り', 0)
        sasa = counter.get('ササ濁り', 0)
        nigori = counter.get('濁り', 0)
        kyou = counter.get('濁り強', 0)
        nigori_sys = usu + sasa + nigori + kyou
        # 報告総数を母数とする
        if kyou / total >= 0.20:
            return '🔴濁り強'
        if (kyou + nigori) / total >= 0.25:
            # 濁り強+濁りで 25% 超 → 濁り傾向
            return '🟠濁り傾向'
        if nigori_sys / total >= 0.30:
            # 薄濁り含む濁り系で 30% 超
            if usu >= sasa + nigori + kyou:
                return '🟠薄濁り基調'
            return '🟠濁り傾向'
        if nigori_sys / total >= 0.15:
            return '🟡薄濁り中心'
        return '🟢澄み傾向'

    result = {}
    for bay in BAY_ORDER:
        n = bay_total[bay]
        label = None
        if n >= min_records:
            label = classify(bay_wc[bay], n)
        if label:
            result[bay] = {"label": label, "n": n, "from": "自データ"}
            continue
        # フォールバック: 隣接同海域湾
        fb = BAY_FALLBACK.get(bay)
        if fb and result.get(fb, {}).get("from") == "自データ":
            fb_label = result[fb]["label"]
            result[bay] = {"label": fb_label, "n": n, "from": f"{fb}参照"}
        else:
            result[bay] = {"label": None, "n": n, "from": "データ不足"}
    return result


# ============================================================
# 潮位取得
# ============================================================

def fetch_tide(lat, lon, target_date):
    """Open-Meteo Marine API で指定日の時間別潮位を取得。
    返り値: {"peaks": [(time, h), ...], "troughs": [(time, h), ...]}
    """
    url = (f"https://marine-api.open-meteo.com/v1/marine"
           f"?latitude={lat}&longitude={lon}"
           f"&hourly=sea_level_height_msl"
           f"&start_date={target_date}&end_date={target_date}"
           f"&timezone=Asia%2FTokyo")
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            d = json.load(r)
        times = d['hourly']['time']
        h = d['hourly']['sea_level_height_msl']
        peaks = []
        troughs = []
        for i in range(1, len(h) - 1):
            if h[i] is None or h[i-1] is None or h[i+1] is None:
                continue
            if h[i] > h[i-1] and h[i] > h[i+1] and h[i] > 0.2:
                peaks.append((times[i][-5:], h[i]))
            if h[i] < h[i-1] and h[i] < h[i+1] and h[i] < -0.2:
                troughs.append((times[i][-5:], h[i]))
        return {"peaks": peaks, "troughs": troughs}
    except Exception as e:
        return {"err": str(e), "peaks": [], "troughs": []}


def format_tide_section(tide):
    """潮汐セクションの本文生成。下げ潮ピーク時間帯も含む。"""
    if not tide["peaks"] and not tide["troughs"]:
        return None
    peaks = [p[0] for p in tide["peaks"]]
    troughs = [t[0] for t in tide["troughs"]]
    # 朝マズメ後の下げ潮を判定: 早朝満潮 → その後の干潮の間が「下げ潮」
    drop_window = ""
    for ph, _ in tide["peaks"]:
        ph_int = int(ph.split(":")[0])
        if 0 <= ph_int <= 5:
            # 翌干潮を探す
            for th, _ in tide["troughs"]:
                th_int = int(th.split(":")[0])
                if th_int > ph_int:
                    drop_window = f"朝マズメ後 {ph_int+2}-{th_int-1}時の下げ潮が最大動"
                    break
            break
    lines = []
    if peaks:
        lines.append(f"　満潮 {'・'.join(peaks)}")
    if troughs:
        lines.append(f"　干潮 {'・'.join(troughs)}")
    if drop_window:
        lines.append(f"　{drop_window}")
    return "\n".join(lines)


# ============================================================
# 潮汐種別（大潮/中潮/小潮）
# ============================================================

def fetch_tide_meta(target_date_iso):
    """tide_moon.sqlite から潮汐種別・月齢を取得。target_date_iso = YYYY-MM-DD"""
    try:
        c = sqlite3.connect('ocean/tide_moon.sqlite')
        row = c.execute(
            "SELECT moon_age, tide_type, tide_coeff, moon_phase FROM tide_moon WHERE date=?",
            (target_date_iso,)
        ).fetchone()
        c.close()
        if not row:
            return None
        moon_age, tide_type, tide_coeff, moon_phase = row
        return {
            "tide_type": tide_type,
            "moon_age": moon_age,
            "tide_coeff": tide_coeff,
            "moon_phase": moon_phase,
        }
    except Exception:
        return None


# ============================================================
# 投稿テキスト生成
# ============================================================

def build_post(bay, fc_areas, turbidity, tide_meta, tide, target_date):
    """1湾分の投稿テキストを生成。"""
    forecast_key = BAY_FORECAST_KEY[bay]
    ad = fc_areas.get(forecast_key)
    if not ad:
        return None

    # 日付フォーマット (YYYY/MM/DD or YYYY-MM-DD → M/D(曜))
    if '/' in target_date:
        dt = datetime.strptime(target_date, '%Y/%m/%d').date()
    else:
        dt = datetime.strptime(target_date, '%Y-%m-%d').date()
    weekday_jp = ['月','火','水','木','金','土','日'][dt.weekday()]
    date_label = f"{dt.month}/{dt.day}({weekday_jp})"

    display = BAY_DISPLAY[bay]
    wind_dir = wind_compass(ad.get('wind_dir'))

    # 出船判定: スコア100=◎, 90=○, それ以下=△
    score = ad.get('score', 0)
    if score >= 100:
        ok_mark = "◎"
    elif score >= 90:
        ok_mark = "○"
    else:
        ok_mark = "△"

    # 潮位差（cmに変換: tide_coeff は 0-100 だが、潮位差として表示）
    tide_range_str = ""
    if tide_meta and tide_meta["tide_coeff"]:
        # 大潮で約120cm, 小潮で約60cm 程度の目安
        tide_range_str = f"潮位差{int(tide_meta['tide_coeff'] * 1.2)}cm"

    # 潮汐情報（先頭の tide_type と括弧内は分離）
    tide_type = tide_meta['tide_type'] if tide_meta else '潮汐不明'
    moon_str = ""
    if tide_meta:
        parts = [f"月齢{tide_meta['moon_age']:.1f}"]
        if tide_meta.get('moon_phase'):
            parts.append(tide_meta['moon_phase'])
        moon_str = f"({'・'.join(parts)})"

    # 濁り度（None なら投稿対象外）
    turb = turbidity.get(bay, {})
    if not turb.get('label'):
        return None
    turb_label = turb['label']
    if turb['from'] not in ("自データ", "データ不足"):
        turb_label += f"({turb['from']})"

    # 潮汐セクション
    tide_section = format_tide_section(tide) or "　潮汐データ取得不可"

    # 注釈（特殊条件）
    extra_note = ""
    if score < 100 and score >= 90:
        if ad.get('wind', 0) >= 4.0:
            extra_note = "・午後波上がり注意"

    # 本文組立
    body = (
        f"おはようございます！今日も釣れますように🎣\n"
        f"今日の海況を紹介します。釣りのヒントになれば\n"
        f"\n"
        f"🌊{date_label} {display} 海況予想\n"
        f"\n"
        f"🌀{tide_type}{moon_str} {tide_range_str}\n"
        f"🌬{wind_dir} {ad['wind']:.1f}m/s\n"
        f"〰波{ad['wave']:.1f}m\n"
        f"🌡水温{ad['sst']:.1f}℃\n"
        f"☀{ad.get('weather_text', '晴')} 気圧{ad.get('pressure', 0):.1f}hPa\n"
        f"🚢出船日和{ok_mark}(スコア{score}{extra_note})\n"
        f"\n"
        f"💧濁り度: {turb_label}\n"
        f"\n"
        f"🕐潮の動き:\n"
        f"{tide_section}\n"
        f"\n"
        f"{BAY_HASHTAGS[bay]}"
    )
    return body


# ============================================================
# main
# ============================================================

def main():
    # 引数: 対象日（YYYY/MM/DD or YYYY-MM-DD）
    if len(sys.argv) > 1:
        target = sys.argv[1].replace('/', '-')
    else:
        # 明日
        target = (date.today() + timedelta(days=1)).isoformat()
    target_iso = target  # YYYY-MM-DD
    target_slash = target.replace('-', '/')  # YYYY/MM/DD
    prev_slash = (datetime.strptime(target_iso, '%Y-%m-%d').date() - timedelta(days=1)).strftime('%Y/%m/%d')

    print(f"対象日: {target_iso} (前日水色集計: {prev_slash})")

    # forecast.json 読込
    if not Path('forecast.json').exists():
        print('エラー: forecast.json が見つからない。crawler.py を先に実行してください。', file=sys.stderr)
        sys.exit(1)
    with open('forecast.json', encoding='utf-8') as f:
        fc = json.load(f)
    if target_iso not in fc.get('days', {}):
        print(f'エラー: forecast.json に {target_iso} の予報がない。',
              file=sys.stderr)
        sys.exit(1)
    fc_day = fc['days'][target_iso]
    fc_areas = fc_day.get('areas', {})

    # 潮汐メタ
    tide_meta = fetch_tide_meta(target_iso)

    # 濁り度集計
    print('濁り度集計中...')
    turbidity = aggregate_turbidity(prev_slash, min_records=10)
    for bay in BAY_ORDER:
        t = turbidity.get(bay, {})
        print(f"  {bay}: {t.get('label', 'N/A')} (n={t.get('n', 0)} from={t.get('from', '?')})")

    # 各湾の潮汐
    print('潮汐取得中...')
    tides = {}
    for bay in BAY_ORDER:
        lat, lon = BAY_COORDS[bay]
        tides[bay] = fetch_tide(lat, lon, target_iso)
        print(f"  {bay}: 満潮{len(tides[bay]['peaks'])}・干潮{len(tides[bay]['troughs'])}")

    # 投稿生成（都心から遠い順）
    raw_posts = []
    for bay in BAY_ORDER:
        post = build_post(bay, fc_areas, turbidity, tide_meta, tides[bay], target_slash)
        if post is None:
            continue
        raw_posts.append((bay, post))

    # 投稿数に応じて 4:00〜6:00 を均等配分
    n_posts = len(raw_posts)
    posts = []
    if n_posts == 1:
        times_alloc = ['5:00']
    elif n_posts == 0:
        times_alloc = []
    else:
        # 4:00 を 240分, 6:00 を 360分とし均等割
        step = (360 - 240) / (n_posts - 1)
        times_alloc = []
        for i in range(n_posts):
            m = 240 + step * i
            h, mm = int(m // 60), int(m % 60)
            # 5分刻みに丸める
            mm = round(mm / 5) * 5
            if mm == 60:
                h += 1
                mm = 0
            times_alloc.append(f"{h}:{mm:02d}")

    for (bay, post), t in zip(raw_posts, times_alloc):
        posts.append((t, bay, post))

    # markdown 出力
    out_lines = [
        f"# {target_iso} 湾別海況 X投稿ドラフト",
        "",
        f"対象日: {target_iso}",
        f"前日水色集計: {prev_slash}",
        f"投稿対象: {len(posts)}湾（都心から遠い順）",
        f"※静岡は伊豆半島で相模湾と隔絶のため省略",
        "",
        "## 投稿スケジュール",
        "",
        "| 時刻 | 湾 |",
        "|------|-----|",
    ]
    for t, bay, _ in posts:
        out_lines.append(f"| {t} | {BAY_DISPLAY[bay]} |")

    out_lines.append("")
    out_lines.append("---")
    out_lines.append("")

    for i, (t, bay, post) in enumerate(posts):
        out_lines.append(f"## {i+1}. {t} {BAY_DISPLAY[bay]}")
        out_lines.append("")
        out_lines.append("```")
        out_lines.append(post)
        out_lines.append("```")
        out_lines.append("")

    # 保存
    Path('dustbox').mkdir(exist_ok=True)
    out_path = f"dustbox/bay_kaikyou_{target_iso}.md"
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(out_lines))
    print(f'\n出力: {out_path}')


if __name__ == '__main__':
    main()
