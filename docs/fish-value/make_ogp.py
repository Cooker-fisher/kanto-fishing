#!/usr/bin/env python3
"""釣果価値チェッカー 専用 OGP 画像を生成（docs/fish-value/ogp.png・1200x630）。

X等でURLを貼ったときのカード画像。サイト共通 ogp-default.png（日次釣果まとめ）だと
内容が合わないため専用画像にする。再生成: python docs/fish-value/make_ogp.py
"""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
OUT = HERE / 'ogp.png'
W, H = 1200, 630
NAVY = (13, 43, 74)
NAVY2 = (26, 64, 112)
ORANGE = (232, 93, 4)
BG = (245, 247, 250)
GRAY = (90, 106, 122)
MUTED = (138, 150, 164)

FB = 'C:/Windows/Fonts/BIZ-UDGothicB.ttc'   # bold
FR = 'C:/Windows/Fonts/BIZ-UDGothicR.ttc'   # regular
def f(path, size):
    return ImageFont.truetype(path, size, index=0)

img = Image.new('RGB', (W, H), BG)
d = ImageDraw.Draw(img)

# ヘッダ帯（ネイビー）＋オレンジのアクセント線
d.rectangle([0, 0, W, 116], fill=NAVY)
d.rectangle([0, 116, W, 124], fill=ORANGE)
d.text((60, 38), '船釣り予想', font=f(FB, 40), fill=(255, 255, 255))
d.text((60 + int(d.textlength('船釣り予想', font=f(FB, 40))) + 24, 46),
       '｜ 釣果価値チェッカー', font=f(FR, 32), fill=(200, 214, 230))

# 見出し（2行）— 「買ったら」だけオレンジ
y = 188
d.text((60, y), '釣った魚、スーパーで', font=f(FB, 72), fill=NAVY)
y2 = y + 92
x = 60
seg = [('買ったら', ORANGE), ('いくら？', NAVY)]
for t, col in seg:
    d.text((x, y2), t, font=f(FB, 72), fill=col)
    x += int(d.textlength(t, font=f(FB, 72)))

# オレンジの実例チップ
cx, cy, cw, ch = 60, 388, 760, 108
d.rounded_rectangle([cx, cy, cx + cw, cy + ch], radius=20, fill=ORANGE)
d.text((cx + 34, cy + 22), '例）アジ38匹なら', font=f(FR, 30), fill=(255, 224, 205))
d.text((cx + 34, cy + 54), '¥12,500 相当', font=f(FB, 46), fill=(255, 255, 255))

# 補足＋URL
d.text((60, 524), '豊洲市場の実勢価格 × 季節補正で概算・無料',
       font=f(FR, 30), fill=GRAY)
d.text((60, 566), 'funatsuri-yoso.com/fish-value',
       font=f(FR, 28), fill=MUTED)

img.save(OUT, 'PNG')
print(f'書出: {OUT} ({W}x{H})')
