#!/usr/bin/env python3
"""釣果価値チェッカー 専用 OGP 画像を生成（docs/fish-value/ogp.png・1200x630）。

X等でURLを貼ったときのカード画像。サイト本体の結果表示（レシート風）に合わせ、
左にサンプルのレシート、右にキャッチコピーを置く。再生成: python docs/fish-value/make_ogp.py
"""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
OUT = HERE / 'ogp.png'
W, H = 1200, 630
NAVY = (13, 43, 74)
ORANGE = (232, 93, 4)
ORANGE2 = (208, 78, 0)
BG = (238, 235, 228)      # 台（カウンター）っぽい暖色グレー
PAPER = (255, 253, 246)   # レシート紙
INK = (42, 42, 36)
RC_DIM = (107, 107, 96)
RC_LINE = (154, 150, 138)
GRAY = (90, 106, 122)
MUTED = (138, 150, 164)

FB = 'C:/Windows/Fonts/BIZ-UDGothicB.ttc'   # bold
FR = 'C:/Windows/Fonts/BIZ-UDGothicR.ttc'   # regular
def f(path, size):
    return ImageFont.truetype(path, size, index=0)

img = Image.new('RGB', (W, H), BG)
d = ImageDraw.Draw(img)


def dashed(x0, x1, y, col=RC_LINE, dash=9, gap=7, wdt=2):
    x = x0
    while x < x1:
        d.line([(x, y), (min(x + dash, x1), y)], fill=col, width=wdt)
        x += dash + gap


def leader(x0, x1, y, col=(198, 192, 176)):
    """明細のドットリーダー"""
    x = x0
    while x < x1:
        d.ellipse([x, y, x + 2, y + 2], fill=col)
        x += 8


# ── ヘッダ帯（ネイビー）＋オレンジのアクセント線 ──
d.rectangle([0, 0, W, 100], fill=NAVY)
d.rectangle([0, 100, W, 107], fill=ORANGE)
d.text((56, 30), '船釣り予想', font=f(FB, 36), fill=(255, 255, 255))
d.text((56 + int(d.textlength('船釣り予想', font=f(FB, 36))) + 22, 37),
       '｜ 釣果価値チェッカー', font=f(FR, 28), fill=(200, 214, 230))

# ============================================
# 左：サンプルのレシート
# ============================================
rx0, ry0, rx1, ry1 = 84, 146, 476, 606
# 影
d.rounded_rectangle([rx0 + 9, ry0 + 12, rx1 + 9, ry1 + 12], radius=6, fill=(205, 200, 190))
# 紙
d.rounded_rectangle([rx0, ry0, rx1, ry1], radius=5, fill=PAPER)

cx = (rx0 + rx1) // 2
pad = 30
il, ir = rx0 + pad, rx1 - pad


def center(text, y, font, fill):
    w = d.textlength(text, font=font)
    d.text((cx - w / 2, y), text, font=font, fill=fill)


# ヘッダ
center('船釣り予想 鮮魚店', ry0 + 22, f(FB, 25), INK)
center('FUNATSURI-YOSO FISH MARKET', ry0 + 56, f(FR, 15), RC_DIM)
center('2026/07/18(土)  伝票 No.618', ry0 + 82, f(FR, 16), RC_DIM)
dashed(il, ir, ry0 + 116)

# 集計（テキストで代替）
center('マゴチ 4尾  ・  アジ 6尾', ry0 + 130, f(FB, 19), INK)
center('2魚種 ・ 合計 4.6kg', ry0 + 158, f(FR, 15), RC_DIM)
dashed(il, ir, ry0 + 188)

# 明細
y = ry0 + 200
items = [('マゴチ', None, None),
         (None, '標準', '¥5,200'),
         ('アジ', None, None),
         (None, '小', '¥1,900'),
         (None, '標準', '¥1,800')]
fb18 = f(FB, 18)
fr17 = f(FR, 17)
for sp, label, price in items:
    if sp:
        d.text((il, y), sp, font=fb18, fill=INK)
        y += 28
    else:
        d.text((il, y), label, font=fr17, fill=(85, 82, 74))
        pw = d.textlength(price, font=fb18)
        d.text((ir - pw, y), price, font=fb18, fill=INK)
        lx0 = il + d.textlength(label, font=fr17) + 8
        leader(lx0, ir - pw - 8, y + 12)
        y += 30
dashed(il, ir, y + 4)
y += 16

# 小計 / お会計
d.text((il, y), '小計', font=fr17, fill=(85, 82, 74))
sw = d.textlength('¥8,900', font=fb18)
d.text((ir - sw, y), '¥8,900', font=fb18, fill=INK)
y += 34
d.text((il, y + 8), 'お会計', font=f(FB, 20), fill=INK)
amt = '¥8,900'
aw = d.textlength(amt, font=f(FB, 40))
sfw = d.textlength(' 相当', font=f(FB, 18))
d.text((ir - aw - sfw, y), amt, font=f(FB, 40), fill=ORANGE2)
d.text((ir - sfw, y + 20), ' 相当', font=f(FB, 18), fill=ORANGE2)

# ============================================
# 右：キャッチコピー
# ============================================
tx = 536
d.text((tx, 196), '釣った魚、', font=f(FB, 60), fill=NAVY)
d.text((tx, 272), 'スーパーで', font=f(FB, 60), fill=NAVY)
x = tx
for t, col in [('買ったら', ORANGE), ('いくら？', NAVY)]:
    d.text((x, 348), t, font=f(FB, 60), fill=col)
    x += int(d.textlength(t, font=f(FB, 60)))

# 実例チップ
d.rounded_rectangle([tx, 452, tx + 470, 452 + 64], radius=14, fill=ORANGE)
d.text((tx + 22, 466), 'この釣果なら  ¥8,900 相当', font=f(FB, 30), fill=(255, 255, 255))

# 補足＋URL
d.text((tx, 540), '豊洲市場の実勢価格 × 季節補正で概算・無料',
       font=f(FR, 26), fill=GRAY)
d.text((tx, 578), 'funatsuri-yoso.com/fish-value',
       font=f(FR, 24), fill=MUTED)

img.save(OUT, 'PNG')
print(f'書出: {OUT} ({W}x{H})')
