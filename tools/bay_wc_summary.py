"""直近1週間の kanso/water_color から湾別水色傾向を集計"""
import csv, glob, sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta

AREA_TO_BAY = {
    # 茨城
    '鹿島港': '茨城', '波崎港': '茨城', '大洗港': '茨城', '日立久慈港': '茨城',
    # 千葉外房
    '飯岡港': '千葉外房', '大原港': '千葉外房', '片貝港': '千葉外房',
    '勝浦川津港': '千葉外房', '御宿岩和田港': '千葉外房', '天津港': '千葉外房',
    '洲崎港': '千葉外房',
    # 千葉内房
    '富津港': '千葉内房', '金谷港': '千葉内房', '富浦港': '千葉内房', '保田港': '千葉内房',
    # 東京湾(千葉)
    '浦安港': '東京湾(千葉)', '浦安': '東京湾(千葉)', '船橋港': '東京湾(千葉)',
    # 東京
    '羽田港': '東京', '羽田': '東京', '平和島港': '東京', '平和島': '東京',
    '東西葛西港': '東京', '東葛西': '東京',
    '江戸川放水路・原木中山': '東京', '江戸川放水路･原木中山': '東京',
    # 東京湾(神奈川)
    '横浜本牧港': '東京湾(神奈川)', '横浜新山下港': '東京湾(神奈川)',
    '横浜港･新山下': '東京湾(神奈川)', '横浜港・新山下': '東京湾(神奈川)',
    '金沢八景': '東京湾(神奈川)', '金沢八景港': '東京湾(神奈川)',
    '小柴港': '東京湾(神奈川)',
    '久里浜港': '東京湾(神奈川)', '長井港': '東京湾(神奈川)',
    '長井新宿港': '東京湾(神奈川)', '長井漆山港': '東京湾(神奈川)',
    '松輪江奈港': '東京湾(神奈川)', '松輪間口港': '東京湾(神奈川)',
    '佐島港': '東京湾(神奈川)', '佐島': '東京湾(神奈川)',
    '剣崎港': '東京湾(神奈川)',
    '久比里港': '東京湾(神奈川)',
    '鴨居・大室港': '東京湾(神奈川)', '鴨居大室港': '東京湾(神奈川)',
    '小坪港': '東京湾(神奈川)',
    '小網代港': '東京湾(神奈川)',
    '長浦': '東京湾(神奈川)',
    # 相模湾
    '葉山あぶずり港': '相模湾', '茅ヶ崎港': '相模湾', '平塚港': '相模湾',
    '大磯港': '相模湾', '小田原早川港': '相模湾',
    # 静岡
    '御前崎港': '静岡', '沼津内港': '静岡', '沼津静浦': '静岡',
    '田子の浦港': '静岡', '由比港': '静岡', '由比': '静岡',
    '下田港': '静岡', '福田港': '静岡',
}

WC_KEYWORDS = [
    ('青々', '澄み'), ('青い', '澄み'), ('クリア', '澄み'),
    ('透明度', '澄み'), ('真っ青', '澄み'), ('潮色良', '澄み'),
    ('ササ濁', 'ササ濁り'), ('薄濁', 'ササ濁り'), ('うす濁', 'ササ濁り'),
    ('やや濁', 'ササ濁り'),
    ('濁り強', '濁り強'), ('かなり濁', '濁り強'), ('濁ってる', '濁り'),
    ('濁って', '濁り'), ('泥濁', '濁り強'), ('茶濁', '濁り'),
    ('緑色', '緑潮'), ('赤潮', '赤潮'), ('黒潮', '澄み'),
]

def main():
    files = sorted(glob.glob('data/V2/2026-*.csv'))[-2:]
    # 集計対象日（コマンドライン引数 or 前日）
    if len(sys.argv) > 1:
        target_date = sys.argv[1]  # 'YYYY/MM/DD'
    else:
        target_date = (datetime.now().date() - timedelta(days=1)).strftime('%Y/%m/%d')

    bay_wc = defaultdict(Counter)
    bay_total = Counter()
    unmapped = Counter()

    for f in files:
        with open(f, encoding='utf-8') as fp:
            for r in csv.DictReader(fp):
                if r.get('date', '') != target_date:
                    continue
                area = r.get('area', '')
                bay = AREA_TO_BAY.get(area)
                if not bay:
                    unmapped[area] += 1
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

    out = []
    out.append(f'# {target_date} の湾別水色集計（前日 = 翌日海況予想の最良プロキシ）')
    out.append('')
    bay_order = ['茨城', '千葉外房', '千葉内房', '東京湾(千葉)', '東京',
                 '東京湾(神奈川)', '相模湾', '静岡']
    for bay in bay_order:
        out.append(f'## {bay} (報告 {bay_total[bay]}件)')
        if bay_wc[bay]:
            for k, v in sorted(bay_wc[bay].items(), key=lambda x: -x[1])[:6]:
                out.append(f'- {k}: {v}')
        else:
            out.append('- (報告なし)')
        out.append('')

    if unmapped:
        out.append('## 未マップ area（要 AREA_TO_BAY 追記）')
        for a, n in sorted(unmapped.items(), key=lambda x: -x[1])[:20]:
            out.append(f'- {a}: {n}')

    with open('tools/bay_wc_summary_out.md', 'w', encoding='utf-8') as fp:
        fp.write('\n'.join(out))
    print(f'wrote tools/bay_wc_summary_out.md ({len(out)} lines)')

if __name__ == '__main__':
    main()
