# build_daily_page.py — docs/x_post/YYYY-MM-DD.html 生成
# mockup-x-post-daily.html を再現する形で HTML を組立

import os
import re
import json


_FISH_ROMAJI: dict = {}
_FISH_ROMAJI_LOADED = False


def _load_fish_romaji() -> dict:
    """normalize/fish_romaji_map.json を読み込んでキャッシュ。
    全 60 魚種対応（ハイフン付き形式・例: 'bishi-aji'）。
    asset フォルダ用にハイフン除去が必要なケースは呼出側で .replace('-', '') する。"""
    global _FISH_ROMAJI, _FISH_ROMAJI_LOADED
    if not _FISH_ROMAJI_LOADED:
        _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        _path = os.path.join(_root, "normalize", "fish_romaji_map.json")
        try:
            with open(_path, encoding="utf-8") as f:
                _FISH_ROMAJI = json.load(f)
        except Exception:
            _FISH_ROMAJI = {}
        _FISH_ROMAJI_LOADED = True
    return _FISH_ROMAJI


# ── CSS（mockup-x-post-daily.html から抽出・CSS 変数のみ使用） ──
_PAGE_CSS = """
:root {
  --bg: #ffffff;
  --bg-alt: #fafbfd;
  --text: #1a2332;
  --accent: #0d2b4a;
  --accent-2: #15406b;
  --cta: #e85d04;
  --cta-soft: #fff3e0;
  --sub: #5a6a7a;
  --border: #e3e9ef;
  --port: #0a7ea4;
  --warn: #c44402;
  --good: #06d6a0;
}
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
body {
  font-family: system-ui, -apple-system, "Hiragino Sans", "Meiryo", sans-serif;
  background: var(--bg);
  color: var(--text);
  line-height: 1.7;
  font-size: 15px;
}
.gnav {
  background: var(--accent);
  padding: 12px 20px;
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.gnav .logo { color: #fff; font-size: 14px; font-weight: 800; text-decoration: none; }
.gnav nav a { color: #fff; font-size: 12px; margin-left: 14px; text-decoration: none; opacity: .85; }
.wrap { max-width: 880px; margin: 0 auto; padding: 24px 20px 60px; }
.crumbs { font-size: 12px; color: var(--sub); margin-bottom: 14px; }
.crumbs a { color: var(--port); text-decoration: none; }
.hero {
  background: linear-gradient(135deg, var(--accent) 0%, var(--accent-2) 100%);
  color: #fff;
  border-radius: 12px;
  padding: 22px 26px;
  margin-bottom: 24px;
  position: relative;
  overflow: hidden;
}
.hero::after {
  content: "";
  position: absolute;
  bottom: 0; left: 0; right: 0; height: 4px;
  background: linear-gradient(90deg, #ff6b35 0%, #ffd166 50%, #06d6a0 100%);
}
.hero h1 { font-size: 22px; font-weight: 900; margin-bottom: 6px; }
.hero .sub { font-size: 13px; color: #b8e0eb; font-weight: 600; }
.hero .stats { display: flex; gap: 14px; margin-top: 14px; flex-wrap: wrap; }
.hero .stat { background: rgba(255,255,255,0.10); padding: 6px 12px; border-radius: 8px; font-size: 12px; }
.hero .stat b { color: #ffd166; font-size: 16px; font-weight: 800; margin-right: 3px; }
.sec { margin-bottom: 32px; }
.sec h2 {
  font-size: 18px;
  font-weight: 800;
  color: var(--accent);
  margin-bottom: 12px;
  padding-bottom: 6px;
  border-bottom: 2px solid var(--cta);
  display: flex;
  align-items: center;
  gap: 6px;
}
.sec h2 .num {
  background: var(--cta);
  color: #fff;
  font-size: 12px;
  width: 22px;
  height: 22px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  font-weight: 800;
}
.sec p { margin-bottom: 8px; font-size: 14px; }
.sec .lead { font-size: 15px; color: var(--text); font-weight: 500; line-height: 1.85; }
.hl-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-top: 12px; }
.hl-card {
  background: var(--bg-alt);
  border: 1px solid var(--border);
  border-left: 4px solid var(--cta);
  border-radius: 8px;
  padding: 12px 14px;
}
.hl-card .label { font-size: 11px; color: var(--sub); text-transform: uppercase; letter-spacing: .5px; margin-bottom: 4px; }
.hl-card .target { font-size: 16px; font-weight: 800; color: var(--accent); margin-bottom: 4px; }
.hl-card .val { font-size: 14px; color: var(--cta); font-weight: 700; margin-bottom: 4px; }
.hl-card .meta { font-size: 12px; color: var(--sub); }
.hl-card .meta .up { color: var(--good); font-weight: 700; }
.umi-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; margin-top: 8px; }
.umi-card { background: var(--bg-alt); border: 1px solid var(--border); border-radius: 8px; padding: 14px 16px; }
.umi-card .h { font-size: 14px; font-weight: 800; color: var(--port); margin-bottom: 8px; }
.umi-card dl { display: grid; grid-template-columns: 80px 1fr; gap: 4px 10px; font-size: 13px; }
.umi-card dt { color: var(--sub); }
.umi-card dd { color: var(--text); font-weight: 600; }
.umi-card .ratio { margin-top: 8px; padding-top: 8px; border-top: 1px dashed var(--border); font-size: 13px; }
.umi-card .ratio b { color: var(--good); font-weight: 800; }
.umi-card .ratio.warn b { color: var(--warn); }
/* sea-pair: 内海・外海を横並び 2 カラム配置（スペース節約） */
.sea-pair { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin: 10px 0 12px; }
.sea-section-title { font-size: 13px; font-weight: 800; color: var(--port); margin: 0 0 6px; padding-bottom: 4px; border-bottom: 1px solid var(--border); }
/* sea-grid: 各カラム内で 3 カード × 2 行 */
.sea-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 6px; }
.sea-item { background: var(--bg-alt); border: 1px solid var(--border); border-radius: 6px; padding: 8px 4px; text-align: center; }
.sea-item .sv { font-size: 14px; font-weight: 800; color: var(--accent); line-height: 1.2; }
.sea-item .sl2 { font-size: 9px; color: var(--sub); margin-top: 2px; }
.sea-summary { font-size: 13px; line-height: 1.7; color: var(--sub); margin: 0 0 10px; }
.ship-rate-bar { margin-top: 10px; font-size: 13px; color: var(--sub); }
.ship-rate-bar b { color: var(--good); font-weight: 800; }
.ship-rate-bar.warn b { color: var(--warn); }
@media (max-width: 640px) {
  .sea-pair { grid-template-columns: 1fr; gap: 10px; }
}
.fish-list { border: 1px solid var(--border); border-radius: 8px; overflow: hidden; }
.fish-row {
  display: grid;
  grid-template-columns: 50px 110px 110px 110px 1fr;
  gap: 10px;
  align-items: center;
  padding: 10px 14px;
  border-bottom: 1px solid var(--border);
  font-size: 13px;
}
.fish-row:last-child { border-bottom: none; }
.fish-row:nth-child(odd) { background: var(--bg-alt); }
.fish-row .icon { width: 32px; height: 32px; object-fit: contain; }
.fish-row .name { font-weight: 800; color: var(--accent); font-size: 14px; }
.fish-row .name .badge {
  display: inline-block;
  background: var(--port);
  color: #fff;
  font-size: 10px;
  font-weight: 700;
  padding: 1px 5px;
  border-radius: 999px;
  margin-left: 4px;
  vertical-align: middle;
}
.fish-row .catch { color: var(--cta); font-weight: 700; }
.fish-row .size { color: var(--accent); font-weight: 600; }
.fish-row .size.kg { background: #ffd166; color: #6a4400; padding: 1px 6px; border-radius: 4px; display: inline-block; }
.fish-row .port { color: var(--port); font-size: 12px; }
.day-nav { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin: 24px 0 16px; }
.day-nav a, .day-nav span { display: block; padding: 10px 14px; border: 1px solid var(--border); border-radius: 8px; background: var(--bg-alt); text-decoration: none; font-size: 13px; }
.day-nav a { color: var(--port); font-weight: 700; }
.day-nav a:hover { background: var(--cta-soft); border-color: var(--cta); color: var(--cta); }
.day-nav .prev { text-align: left; }
.day-nav .next { text-align: right; }
.day-nav .disabled { color: #aab4bf; cursor: default; }
.day-nav small { display: block; font-size: 10px; color: var(--sub); margin-bottom: 2px; font-weight: normal; }
.commentary { margin-top: 12px; font-size: 14px; line-height: 1.85; color: var(--text); }
.commentary b { color: var(--accent); }
.commentary .highlight { color: var(--cta); font-weight: 700; }
.commentary .num { color: var(--good); font-weight: 700; }
.commentary-h { font-size: 14px; font-weight: 800; color: var(--accent); margin: 12px 0 6px; }
.note-card {
  background: var(--cta-soft);
  border-left: 4px solid var(--cta);
  border-radius: 0 8px 8px 0;
  padding: 12px 16px;
}
.note-card .h { font-size: 13px; font-weight: 800; color: var(--warn); margin-bottom: 4px; }
.note-card p { font-size: 13px; color: var(--text); margin: 0; }
.x-image-wrap { margin: 24px 0; }
.x-image-label { font-size: 11px; color: var(--sub); margin-bottom: 6px; text-transform: uppercase; letter-spacing: .5px; }
.x-card { width: 100%; background: #f0f9ff; border-radius: 12px; overflow: hidden; border: 1px solid #b8dde9; }
.x-card .x-header {
  background: linear-gradient(90deg, #0a4d6e 0%, #0a7ea4 50%, #14a3c9 100%);
  padding: 12px 22px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  color: #fff;
  position: relative;
}
.x-card .x-header::after {
  content: ""; position: absolute; bottom:0; left:0; right:0; height:3px;
  background: linear-gradient(90deg, #ff6b35 0%, #ffd166 50%, #06d6a0 100%);
}
.x-card .x-header .a { font-size: 11px; font-weight: 800; }
.x-card .x-header .b { font-size: 16px; font-weight: 900; }
.x-card .x-header .c { font-size: 11px; color: #b8e0eb; font-weight: 700; }
.x-card .x-body { padding: 10px 18px; }
.x-card table { width: 100%; border-collapse: collapse; }
.x-card th { font-size: 10px; font-weight: 700; color: #0a4d6e; padding: 6px 8px; text-align: left; border-bottom: 2px solid #0a7ea4; background: rgba(10,77,110,0.08); }
.x-card td { font-size: 11.5px; padding: 5px 8px; border-bottom: 1px solid #d6ebf2; vertical-align: middle; }
.x-card tr:nth-child(odd) td { background: #fafdfe; }
.x-card .xfc { display: flex; align-items: center; gap: 6px; }
.x-card .xfc .n { font-weight: 800; color: #0a4d6e; font-size: 12px; }
.x-card .xfc .b { background: #14a3c9; color: #fff; font-size: 9px; font-weight: 700; padding: 0 5px; border-radius: 999px; }
.x-card .xc { color: #ff6b35; font-weight: 800; font-size: 12px; }
.x-card .xs { color: #0a4d6e; font-weight: 600; font-size: 11px; }
.x-card .xs.kg { background: #ffd166; color: #6a4400; padding: 1px 5px; border-radius: 4px; }
.x-card .xp { color: #0a7ea4; font-size: 11px; font-weight: 600; }
.x-card .x-footer { padding: 8px 22px; display: flex; justify-content: space-between; background: linear-gradient(90deg, #0a4d6e 0%, #0a7ea4 100%); color: #fff; }
.x-card .x-footer .l { color: #ffd166; font-size: 11px; font-weight: 800; }
.x-card .x-footer .r { color: rgba(255,255,255,0.85); font-size: 10px; }
.related { margin-top: 28px; padding: 14px 16px; background: var(--bg-alt); border-radius: 8px; font-size: 13px; }
.related h3 { font-size: 13px; color: var(--accent); margin-bottom: 6px; }
.related a { color: var(--port); margin-right: 14px; text-decoration: none; }
.char-count { font-size: 11px; color: var(--sub); margin-top: 12px; text-align: right; border-top: 1px dashed var(--border); padding-top: 8px; }
.char-count b { color: var(--good); font-weight: 800; }
footer { background: var(--accent); color: rgba(255,255,255,0.8); font-size: 11px; text-align: center; padding: 16px; margin-top: 40px; }
@media (max-width: 600px) {
  .hl-grid, .umi-grid { grid-template-columns: 1fr; }
  .fish-row { grid-template-columns: 40px 90px 90px 1fr; }
  .fish-row .port { display: none; }
}
"""


def _fish_table_rows_html(fish_rows, depth="../"):
    """魚種別テーブル行 HTML（docs/x_post/ から見た相対パスでアイコン参照）"""
    rows = []
    icon_base = f"{depth}assets/fish/"
    _romaji = _load_fish_romaji()
    for row in fish_rows:
        fish_name = row.get("fish", "")
        cnt_min = row.get("cnt_min", 0)
        cnt_max = row.get("cnt_max", 0)
        kg_max = row.get("kg_max", 0.0)
        kg_min = row.get("kg_min", 0.0)
        cm_max = row.get("cm_max", 0)
        cm_min = row.get("cm_min", 0)
        top_port = row.get("top_port", "")
        n_trips = row.get("n_trips", 0)
        # asset フォルダ名はハイフンなし（例: bishi-aji → bishiaji）
        romaji = _romaji.get(fish_name, fish_name.lower()).replace("-", "")
        icon_path = f"{icon_base}{romaji}/{romaji}_emoji.webp"
        # M3: 型表示を min-max 形式に（補遺3 遵守）
        if kg_max and kg_max > 0:
            if kg_min and kg_min > 0 and kg_min < kg_max:
                size_html = f'<span class="size kg">{kg_min:.1f}〜{kg_max:.1f}kg</span>'
            else:
                size_html = f'<span class="size kg">最大{kg_max:.1f}kg</span>'
        elif cm_max and cm_max > 0:
            if cm_min and cm_min > 0 and cm_min < cm_max:
                size_html = f'<span class="size">{cm_min}〜{cm_max}cm</span>'
            else:
                size_html = f'<span class="size">最大{cm_max}cm</span>'
        else:
            size_html = '<span class="size">—</span>'

        rows.append(f"""      <div class="fish-row">
        <img class="icon" src="{icon_path}" alt="{fish_name}" onerror="this.style.display='none'">
        <div class="name">{fish_name}<span class="badge">{n_trips}便</span></div>
        <div class="catch">{cnt_min}〜{cnt_max}匹</div>
        {size_html}
        <div class="port">{top_port}</div>
      </div>""")
    return "\n".join(rows)


def _x_card_table_rows_html(fish_rows):
    """X 投稿画像プレビュー用テーブル行 HTML（縮小版）"""
    rows = []
    _romaji = _load_fish_romaji()
    icon_base = "../../assets/fish/"
    for row in fish_rows[:10]:
        fish_name = row.get("fish", "")
        cnt_min = row.get("cnt_min", 0)
        cnt_max = row.get("cnt_max", 0)
        kg_max = row.get("kg_max", 0.0)
        cm_max = row.get("cm_max", 0)
        top_port = row.get("top_port", "")
        n_trips = row.get("n_trips", 0)
        # asset フォルダ名はハイフンなし
        romaji = _romaji.get(fish_name, fish_name.lower()).replace("-", "")
        icon_path = f"{icon_base}{romaji}/{romaji}_icon_sm.png"
        # 型
        if kg_max and kg_max > 0:
            size_html = f'<span class="xs kg">{kg_max:.1f}kg</span>'
        elif cm_max and cm_max > 0:
            size_html = f'<span class="xs">{cm_max}cm</span>'
        else:
            size_html = "—"
        rows.append(
            f'<tr><td><div class="xfc">'
            f'<img src="{icon_path}" alt="{fish_name}" onerror="this.style.display=\'none\'">'
            f'<span class="n">{fish_name}</span>'
            f'<span class="b">{n_trips}便</span></div></td>'
            f'<td><span class="xc">{cnt_min}〜{cnt_max}匹</span></td>'
            f'<td>{size_html}</td>'
            f'<td class="xp">{top_port}</td></tr>'
        )
    return "\n".join(rows)


def _fmt_sea_cards(sea):
    """sea_data dict → 6 カード .sea-item HTML 文字列"""
    sst  = sea.get("sst")
    wave = sea.get("wave")
    wspd = sea.get("wind_spd")
    wdir = sea.get("wind_dir", "")
    tide = sea.get("tide", "—")
    moon = sea.get("moon", "—")
    pres = sea.get("pressure")

    sst_str  = f"{sst:.1f}℃"       if sst  is not None else "—"
    wave_str = f"{wave:.1f}m"       if wave is not None else "—"
    if wdir and wspd is not None:
        wind_str = f"{wdir}{wspd:.1f}m/s"
    elif wspd is not None:
        wind_str = f"{wspd:.1f}m/s"
    else:
        wind_str = "—"
    pres_str = f"{int(pres)}hPa"   if pres is not None else "—"

    return (
        f'<div class="sea-item"><div class="sv">{sst_str}</div><div class="sl2">水温</div></div>'
        f'<div class="sea-item"><div class="sv">{wave_str}</div><div class="sl2">波高</div></div>'
        f'<div class="sea-item"><div class="sv">{wind_str}</div><div class="sl2">風</div></div>'
        f'<div class="sea-item"><div class="sv">{tide}</div><div class="sl2">潮汐</div></div>'
        f'<div class="sea-item"><div class="sv">{moon}</div><div class="sl2">月相</div></div>'
        f'<div class="sea-item"><div class="sv">{pres_str}</div><div class="sl2">気圧</div></div>'
    )


def _sea_grid_html(ctx):
    """内海・外海 2 セット × 6 カード海況グリッド + サマリ + 出船率バー"""
    inner = ctx.get("inner_sea_data") or {}
    outer = ctx.get("outer_sea_data") or {}
    n_ships        = ctx.get("n_ships", 0)
    n_cancellations = ctx.get("n_cancellations", 0)

    # フォールバック: inner が空なら後方互換スカラーから組み立て
    if not inner:
        inner = {
            "sst":      ctx.get("sst_mean"),
            "wave":     ctx.get("wave_inner"),
            "wind_spd": ctx.get("max_wind"),
            "wind_dir": ctx.get("wind_dir_label", ""),
            "tide":     ctx.get("tide_type", "—"),
            "moon":     ctx.get("moon_phase", "—"),
            "pressure": ctx.get("pressure_hpa"),
        }
    if not outer:
        outer = inner.copy()  # データなければ内海と同値で表示

    # 1 行サマリ（内海基準）
    sst_norm = {1: 15, 2: 14, 3: 15, 4: 16, 5: 17, 6: 19, 7: 22, 8: 24,
                9: 23, 10: 21, 11: 18, 12: 16}
    from datetime import datetime as _dt
    _m = _dt.now().month
    sst_i  = inner.get("sst")
    wave_i = inner.get("wave")
    wspd_i = inner.get("wind_spd")
    summary_parts = []
    if sst_i is not None:
        diff = sst_i - sst_norm.get(_m, 17)
        if diff >= 1.5:
            summary_parts.append(f"水温は平年比+{diff:.1f}℃と高め（{sst_i:.1f}℃）")
        elif diff <= -1.5:
            summary_parts.append(f"水温は平年比{diff:.1f}℃と低め（{sst_i:.1f}℃）")
        else:
            summary_parts.append(f"水温は平年並み（{sst_i:.1f}℃）")
    if wave_i is not None and wspd_i is not None:
        if wave_i >= 2.0 or wspd_i >= 10:
            summary_parts.append(f"波{wave_i:.1f}m・風{wspd_i:.0f}m/sの荒天で欠航警戒")
        elif wave_i >= 1.0 or wspd_i >= 6:
            summary_parts.append(f"波{wave_i:.1f}m・風{wspd_i:.0f}m/sでやや荒れ気味")
        else:
            summary_parts.append(f"波{wave_i:.1f}m・風{wspd_i:.0f}m/sで出船日和")
    summary_html = ""
    if summary_parts:
        summary_html = f'<p class="sea-summary">{"。".join(summary_parts)}。</p>\n'

    # 出船率バー
    _rate_val = (n_ships - n_cancellations) / max(n_ships, 1)
    ship_rate_str = f"{int(_rate_val * 100)}%"
    warn_cls = " warn" if _rate_val < 0.7 else ""
    rate_html = (
        f'<div class="ship-rate-bar{warn_cls}">'
        f'出船率 <b>{ship_rate_str}</b>（{n_ships}船宿中・{n_cancellations}欠航）'
        f'</div>\n'
    )

    inner_cards = _fmt_sea_cards(inner)
    outer_cards = _fmt_sea_cards(outer)

    return (
        f"{summary_html}"
        f'<div class="sea-pair">'
        f'<div class="sea-section">'
        f'<div class="sea-section-title">内海（東京湾・相模湾）</div>'
        f'<div class="sea-grid">{inner_cards}</div>'
        f'</div>'
        f'<div class="sea-section">'
        f'<div class="sea-section-title">外海（外房・銚子方面）</div>'
        f'<div class="sea-grid">{outer_cards}</div>'
        f'</div>'
        f'</div>\n'
        f"{rate_html}"
    )


def _hl_cards_html(ctx):
    """ハイライトカード 2列 HTML"""
    # 大物記録
    top_kg_fish = ctx.get("top_kg_fish", "")
    top_kg_max = ctx.get("top_kg_max", 0.0)
    top_kg_min = ctx.get("top_kg_min", 0.0)
    top_kg_ship = ctx.get("top_kg_ship", "")
    top_kg_port = ctx.get("top_kg_port", "")
    season_ratio_top_kg = ctx.get("season_ratio_top_kg", 1.0)

    # 数の好調
    top_cnt_fish = ctx.get("top_cnt_fish", "")
    top_cnt_max = ctx.get("top_cnt_max", 0)
    top_cnt_min = ctx.get("top_cnt_min", 0)
    top_cnt_ship = ctx.get("top_cnt_ship", "")
    top_cnt_port = ctx.get("top_cnt_port", "")
    wow_pct_str = ctx.get("wow_pct_top_cnt_str", "+0%")

    kg_card = ""
    if top_kg_fish and top_kg_max > 0:
        kg_card = f"""      <div class="hl-card">
        <div class="label">大物記録</div>
        <div class="target">{top_kg_fish}</div>
        <div class="val">{top_kg_min:.1f}〜{top_kg_max:.2f}kg</div>
        <div class="meta">{top_kg_port}｜{top_kg_ship}<br>過去5年同旬比 <span class="up">&times;{season_ratio_top_kg:.1f}倍</span></div>
      </div>"""

    cnt_card = ""
    if top_cnt_fish and top_cnt_max > 0:
        cnt_card = f"""      <div class="hl-card">
        <div class="label">数の好調</div>
        <div class="target">{top_cnt_fish}</div>
        <div class="val">{top_cnt_min}〜{top_cnt_max}匹</div>
        <div class="meta">{top_cnt_port}｜{top_cnt_ship}<br>先週比 <span class="up">{wow_pct_str}</span></div>
      </div>"""

    cards = [c for c in [kg_card, cnt_card] if c]
    if not cards:
        return ""
    return f'    <div class="hl-grid">\n' + "\n".join(cards) + "\n    </div>"


def build(ctx, commentary, output_path, png_url=None):
    """
    docs/x_post/YYYY-MM-DD.html を生成して output_path に保存。
    ctx: context_builder.build_context() の戻り値
    commentary: dict (build_commentary_blocks の戻り値) または str (旧 build_commentary_html の戻り値・互換)
    output_path: 保存先パス
    png_url: この日の PNG の URL（sitemap・OGP 用）
    """
    # 互換: str で渡された場合は intro/hl にまとめて入れて ocean/fish は空
    if isinstance(commentary, dict):
        intro_block = commentary.get("intro", "")
        hl_commentary = commentary.get("hl", "")
        ocean_commentary = commentary.get("ocean", "")
        fish_commentary = commentary.get("fish", "")
    else:
        # 後方互換：旧 commentary_html を hl にまとめて入れる
        intro_block = ""
        hl_commentary = commentary or ""
        ocean_commentary = ""
        fish_commentary = ""
    date_label = ctx.get("date_label", "")
    date_iso = ctx.get("date_iso", "")
    n_ships = ctx.get("n_ships", 0)
    n_fish_species = ctx.get("n_fish_species", 0)
    n_records = ctx.get("n_records", 0)
    tide_type = ctx.get("tide_type", "中潮")
    moon_phase = ctx.get("moon_phase", "")
    top_kg_max = ctx.get("top_kg_max", 0.0)
    top_cnt_max = ctx.get("top_cnt_max", 0)
    fish_rows = ctx.get("fish_rows", [])
    season_label = ctx.get("season_label", "")

    # PNG の相対パス（docs/x_post/ からは同ディレクトリ）
    date_str_for_file = date_iso  # YYYY-MM-DD
    png_filename = f"{date_str_for_file}.png"
    png_rel = f"./{png_filename}"
    if png_url is None:
        png_url = f"https://funatsuri-yoso.com/x_post/{png_filename}"

    # OGP
    top_cnt_fish = ctx.get("top_cnt_fish", "")
    og_desc = (
        f"{date_label} 関東5県の船釣り釣果まとめ。"
        f"{n_ships}船宿・{n_fish_species}魚種・{n_records}件の釣果報告と海況レポート。"
    )
    if top_cnt_fish and top_cnt_max:
        og_desc += f"{top_cnt_fish}{ctx.get('top_cnt_min',0)}〜{top_cnt_max}匹など。"

    # 前日・翌日ナビ
    prev_iso = ctx.get("prev_date_iso", "")
    next_iso = ctx.get("next_date_iso", "")
    prev_label = ctx.get("prev_date_label", "")
    next_label = ctx.get("next_date_label", "")
    prev_html = (f'<a class="prev" href="./{prev_iso}.html"><small>← 前日</small>{prev_label} の釣果まとめ</a>'
                 if ctx.get("prev_exists") else
                 f'<span class="prev disabled"><small>← 前日</small>{prev_label}（記録なし）</span>')
    next_html = (f'<a class="next" href="./{next_iso}.html"><small>翌日 →</small>{next_label} の釣果まとめ</a>'
                 if ctx.get("next_exists") else
                 f'<span class="next disabled"><small>翌日 →</small>{next_label}（記録なし）</span>')
    day_nav = f'<div class="day-nav">{prev_html}{next_html}</div>'

    # ハイライトカード
    hl_cards = _hl_cards_html(ctx)
    # 海況グリッド（6カード・area ページと同スタイル）
    sea_grid = _sea_grid_html(ctx)
    # 魚種テーブル
    fish_rows_html = _fish_table_rows_html(fish_rows, depth="../")
    # X カードテーブル
    x_table_rows = _x_card_table_rows_html(fish_rows)

    # 大物ラベル（C3: kg_min〜kg_max 表記に統一）
    top_kg_min = ctx.get("top_kg_min", 0.0)
    kg_label = ""
    if top_kg_max > 0:
        if top_kg_min and top_kg_min > 0 and top_kg_min < top_kg_max:
            kg_label = f'<span class="stat"><b>{top_kg_min:.1f}〜{top_kg_max:.2f}</b>kg 大物記録</span>'
        else:
            kg_label = f'<span class="stat">最大<b>{top_kg_max:.2f}</b>kg 大物記録</span>'

    html = f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{date_label} 関東船釣り 釣果まとめ | 船釣り予想</title>
<meta name="description" content="{og_desc}">
<meta property="og:title" content="{date_label} 関東船釣り 釣果まとめ | 船釣り予想">
<meta property="og:description" content="{og_desc}">
<meta property="og:image" content="{png_url}?v=2">
<meta property="og:type" content="article">
<meta name="twitter:card" content="summary_large_image">
<link rel="canonical" href="https://funatsuri-yoso.com/x_post/{date_str_for_file}.html">
<style>{_PAGE_CSS}</style>
</head>
<body>

<header class="gnav">
  <a class="logo" href="/">船釣り予想</a>
  <nav>
    <a href="/">トップ</a>
    <a href="/calendar.html">カレンダー</a>
    <a href="/x_post/index.html">釣果速報</a>
    <a href="/pages/about.html">サイトについて</a>
  </nav>
</header>

<div class="wrap">

  <div class="crumbs">
    <a href="/">トップ</a> &raquo; <a href="/x_post/index.html">釣果速報</a> &raquo; {date_label} 釣果まとめ
  </div>

  <div class="hero">
    <h1>{date_label} 関東船釣り 釣果まとめ</h1>
    <div class="sub">{date_str_for_file}（{tide_type}・{moon_phase}）｜神奈川・東京・千葉・茨城・静岡</div>
    <div class="stats">
      <span class="stat"><b>{n_ships}</b>船宿出船</span>
      <span class="stat"><b>{n_fish_species}</b>魚種</span>
      <span class="stat"><b>{n_records}</b>件の釣果報告</span>
      {kg_label}
    </div>
  </div>

  <section class="sec">
    <h2><span class="num">1</span>今日のハイライト</h2>
{intro_block}
{hl_cards}
{hl_commentary}
  </section>

  <section class="sec">
    <h2><span class="num">2</span>海況レポート</h2>
{sea_grid}
{ocean_commentary}
  </section>

  <section class="sec">
    <h2><span class="num">3</span>魚種別 釣果報告</h2>
    <p class="lead">
      本日の全{n_fish_species}魚種のうち、件数上位を便数・釣果レンジ・型・主な港とともにまとめました。
    </p>
    <div class="fish-list">
{fish_rows_html}
    </div>
{fish_commentary}
  </section>

{day_nav}

  <div class="related">
    <h3>関連ページ</h3>
    <a href="/x_post/index.html">&larr; 釣果速報トップへ戻る</a>
    <a href="/">トップ（今日の釣果）</a>
    <a href="/calendar.html">釣りものカレンダー</a>
    <a href="/forecast/index.html">海況予報</a>
  </div>

</div>

<footer>
  &copy; 2026 船釣り予想 | funatsuri-yoso.com — データ集計・出典: 本サイト独自集計
</footer>

</body>
</html>"""

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[build_daily_page] HTML 保存: {output_path}")
    return html
