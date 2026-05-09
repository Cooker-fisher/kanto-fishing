# generate_image.py — B案 PNG 800x500 生成（Pillow + Noto Sans JP TTF）
# Pillow が必要: pip install Pillow>=10.0.0
# フォント: assets/fonts/NotoSansJP-Bold.ttf / NotoSansJP-Regular.ttf

import os
import re


def _find_font(root_dir, variant="Regular"):
    """Noto Sans JP TTF を探す。見つからない場合 None を返す。
    Windows / Linux / Mac すべて対応のフォールバック順。"""
    # Windows のメイリオは Bold/Regular が同 ttc 内別 face index で実装されている
    # truetype(path, size, index=N) で Bold = index 1, Regular = index 0
    candidates = [
        # 1. リポジトリ同梱（最優先・GitHub Actions 用）
        os.path.join(root_dir, "assets", "fonts", f"NotoSansJP-{variant}.ttf"),
        os.path.join(root_dir, "assets", "fonts", f"NotoSansJP-{variant}.otf"),
        # 2. Windows 標準フォント
        "C:/Windows/Fonts/meiryo.ttc",
        "C:/Windows/Fonts/Meiryo.ttc",
        "C:/Windows/Fonts/YuGothM.ttc",
        "C:/Windows/Fonts/yugothic.ttf",
        "C:/Windows/Fonts/msgothic.ttc",
        # 3. Linux 標準フォント
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/fonts-japanese-gothic.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        # 4. macOS 標準フォント
        "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc",
        "/System/Library/Fonts/Hiragino Sans GB.ttc",
    ]
    for p in candidates:
        if os.path.exists(p):
            return p
    return None


def create(ctx, output_path):
    """
    B案 PNG (800x500) を生成して output_path に保存。
    Pillow が無い場合 / フォントが無い場合はスキップして警告を出す。
    返り値: bool (成功 True / スキップ False)
    """
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        print("[generate_image] Pillow がインストールされていません。PNG 生成をスキップします。")
        print("  → pip install Pillow>=10.0.0 でインストール後に再実行してください。")
        return False

    _this_dir = os.path.dirname(os.path.abspath(__file__))
    root_dir = os.path.dirname(_this_dir)

    font_bold_path = _find_font(root_dir, "Bold")
    font_reg_path = _find_font(root_dir, "Regular")

    W, H = 800, 500

    # カラー定義（CSS 変数準拠）
    C_BG = (240, 249, 255)        # #f0f9ff
    C_HEADER = (10, 77, 110)      # #0a4d6e
    C_HEADER_END = (10, 126, 164) # #0a7ea4
    C_TEXT = (26, 35, 50)         # #1a2332
    C_SUB = (90, 106, 122)        # #5a6a7a
    C_ACCENT = (255, 107, 53)     # #ff6b35
    C_GOLD = (255, 209, 102)      # #ffd166
    C_GREEN = (6, 214, 160)       # #06d6a0
    C_WHITE = (255, 255, 255)
    C_BORDER = (214, 235, 242)    # #d6ebf2

    img = Image.new("RGB", (W, H), C_BG)
    draw = ImageDraw.Draw(img)

    # フォント読み込み（なければデフォルト）
    def _font(path, size):
        if path:
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                pass
        return ImageFont.load_default()

    fn_bold_28 = _font(font_bold_path, 28)
    fn_bold_22 = _font(font_bold_path, 22)
    fn_bold_18 = _font(font_bold_path, 18)
    fn_bold_16 = _font(font_bold_path, 16)
    fn_bold_14 = _font(font_bold_path, 14)
    fn_reg_13 = _font(font_reg_path, 13)
    fn_reg_12 = _font(font_reg_path, 12)
    fn_bold_12 = _font(font_bold_path, 12)
    fn_reg_11 = _font(font_reg_path, 11)

    # ── ヘッダ部 ──────────────────────────────────
    HEADER_H = 68
    for x in range(W):
        ratio = x / W
        r = int(C_HEADER[0] * (1 - ratio) + C_HEADER_END[0] * ratio)
        g = int(C_HEADER[1] * (1 - ratio) + C_HEADER_END[1] * ratio)
        b = int(C_HEADER[2] * (1 - ratio) + C_HEADER_END[2] * ratio)
        draw.line([(x, 0), (x, HEADER_H - 4)], fill=(r, g, b))
    # 虹色ライン
    rainbow_w = W // 3
    for x in range(W):
        ratio = x / W
        if x < rainbow_w:
            col = (255, 107, 53)
        elif x < rainbow_w * 2:
            col = (255, 209, 102)
        else:
            col = (6, 214, 160)
        draw.line([(x, HEADER_H - 4), (x, HEADER_H)], fill=col)

    # サイト名
    draw.text((22, 14), "⚓ 船釣り予想", font=fn_bold_16, fill=C_WHITE)
    # タイトル
    date_label = ctx.get("date_label", "")
    title = f"{date_label} 関東船釣り 釣果まとめ"
    draw.text((22, 36), title, font=fn_bold_22, fill=C_WHITE)
    # 副題
    n_ships = ctx.get("n_ships", 0)
    n_areas = ctx.get("n_areas", 0)
    draw.text((W - 150, 18), f"{n_ships}船宿 {n_areas}港", font=fn_reg_12, fill=(184, 224, 235))

    # ── テーブルヘッダ ────────────────────────────
    TABLE_TOP = HEADER_H + 8
    COL_W = [180, 140, 130, 130, W - 180 - 140 - 130 - 130 - 44]
    COL_X = [22]
    for w in COL_W[:-1]:
        COL_X.append(COL_X[-1] + w)
    HEADERS = ["魚種", "釣果", "型", "港", "便"]
    TH_BG = (230, 243, 248)
    TH_TEXT = (10, 77, 110)
    TH_H = 24
    draw.rectangle([0, TABLE_TOP, W, TABLE_TOP + TH_H], fill=TH_BG)
    for i, hd in enumerate(HEADERS):
        draw.text((COL_X[i] + 4, TABLE_TOP + 5), hd, font=fn_bold_12, fill=TH_TEXT)
    # ヘッダ下ライン
    draw.line([(0, TABLE_TOP + TH_H), (W, TABLE_TOP + TH_H)], fill=(10, 126, 164), width=2)

    # ── テーブル行 ────────────────────────────────
    fish_rows = ctx.get("fish_rows", [])
    ROW_H = 36
    ROW_TOP = TABLE_TOP + TH_H + 2
    MAX_ROWS = min(len(fish_rows), 9)  # 最大9行（500px に収める）

    for i, row in enumerate(fish_rows[:MAX_ROWS]):
        y = ROW_TOP + i * ROW_H
        row_bg = (250, 253, 254) if i % 2 == 0 else C_BG
        draw.rectangle([0, y, W, y + ROW_H - 1], fill=row_bg)

        fish_name = row.get("fish", "")
        cnt_min = row.get("cnt_min", 0)
        cnt_max = row.get("cnt_max", 0)
        kg_max = row.get("kg_max", 0.0)
        cm_max = row.get("cm_max", 0)
        top_port = row.get("top_port", "")
        n_trips = row.get("n_trips", 0)

        # 魚種名
        draw.text((COL_X[0] + 4, y + 10), fish_name, font=fn_bold_14, fill=(10, 77, 110))

        # 釣果 MIN〜MAX
        catch_str = f"{cnt_min}〜{cnt_max}匹"
        draw.text((COL_X[1] + 4, y + 10), catch_str, font=fn_bold_14, fill=C_ACCENT)

        # 型 (kg 優先)
        if kg_max and kg_max > 0:
            type_str = f"{kg_max:.1f}kg"
            # 黄色背景
            bbox = draw.textbbox((COL_X[2] + 4, y + 8), type_str, font=fn_bold_12)
            draw.rectangle([bbox[0]-3, bbox[1]-2, bbox[2]+3, bbox[3]+2], fill=C_GOLD)
            draw.text((COL_X[2] + 4, y + 8), type_str, font=fn_bold_12, fill=(106, 68, 0))
        elif cm_max and cm_max > 0:
            type_str = f"{cm_max}cm"
            draw.text((COL_X[2] + 4, y + 10), type_str, font=fn_bold_12, fill=(10, 77, 110))
        else:
            draw.text((COL_X[2] + 4, y + 10), "—", font=fn_reg_11, fill=(170, 180, 191))

        # 港
        port_short = top_port[:8] if top_port else ""
        draw.text((COL_X[3] + 4, y + 10), port_short, font=fn_reg_12, fill=(10, 126, 164))

        # 便数
        draw.text((COL_X[4] + 4, y + 10), f"{n_trips}便", font=fn_reg_12, fill=C_SUB)

        # 行ライン
        draw.line([(0, y + ROW_H - 1), (W, y + ROW_H - 1)], fill=C_BORDER)

    # ── フッタ ────────────────────────────────────
    FOOTER_TOP = H - 36
    for x in range(W):
        ratio = x / W
        r = int(C_HEADER[0] * (1 - ratio) + C_HEADER_END[0] * ratio)
        g = int(C_HEADER[1] * (1 - ratio) + C_HEADER_END[1] * ratio)
        b = int(C_HEADER[2] * (1 - ratio) + C_HEADER_END[2] * ratio)
        draw.line([(x, FOOTER_TOP), (x, H)], fill=(r, g, b))

    draw.text((22, FOOTER_TOP + 10), "funatsuri-yoso.com", font=fn_bold_14, fill=C_GOLD)
    n_fish_species = ctx.get("n_fish_species", 0)
    draw.text((W - 200, FOOTER_TOP + 10),
              f"{n_fish_species}魚種 データ集計", font=fn_reg_12,
              fill=(255, 255, 255, 217))

    # 保存
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    img.save(output_path, format="PNG", optimize=True)
    print(f"[generate_image] PNG 保存: {output_path} ({W}x{H})")
    return True
