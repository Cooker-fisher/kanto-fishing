# build_rss.py — docs/feed.xml 生成（RSS 2.0・media:content・enclosure）
# 標準ライブラリのみ

import os
import json
from datetime import datetime, timezone, timedelta
from xml.sax.saxutils import escape as xml_escape

JST = timezone(timedelta(hours=9))

_RSS_TEMPLATE = """\
<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"
  xmlns:media="http://search.yahoo.com/mrss/"
  xmlns:atom="http://www.w3.org/2005/Atom">
  <channel>
    <title>関東船釣り釣果まとめ | 船釣り予想</title>
    <link>https://funatsuri-yoso.com/</link>
    <description>神奈川・東京・千葉・茨城・静岡の船釣り釣果を毎日集計してお届けします。</description>
    <language>ja</language>
    <lastBuildDate>{last_build_date}</lastBuildDate>
    <atom:link href="https://funatsuri-yoso.com/feed.xml" rel="self" type="application/rss+xml"/>
{items}
  </channel>
</rss>
"""

_ITEM_TEMPLATE = """\
    <item>
      <title>{title}</title>
      <link>{link}</link>
      <description><![CDATA[{description}]]></description>
      <pubDate>{pub_date}</pubDate>
      <guid isPermaLink="true">{link}</guid>
      <media:content url="{png_url}" medium="image" width="800" height="500"/>
      <enclosure url="{png_url}" length="0" type="image/png"/>
    </item>"""


def _rfc822(dt):
    """datetime → RFC 822 形式文字列（RSS pubDate 用）"""
    # Python の strftime は曜日名が locale 依存のため手動生成
    day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    month_names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                   "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    return (
        f"{day_names[dt.weekday()]}, {dt.day:02d} {month_names[dt.month-1]} {dt.year} "
        f"{dt.hour:02d}:{dt.minute:02d}:{dt.second:02d} +0900"
    )


def build(ctx, png_url, daily_url, output_path, existing_feed_path=None):
    """
    docs/feed.xml を生成 / 更新。
    ctx: context_builder.build_context() の戻り値
    png_url: この日の PNG の URL（https://...）
    daily_url: この日の HTML の URL（https://...）
    output_path: feed.xml の保存先
    existing_feed_path: 既存 feed.xml のパス（過去記事を引き継ぐ場合）
    """
    date_label = ctx.get("date_label", "")
    date_iso = ctx.get("date_iso", "")
    n_ships = ctx.get("n_ships", 0)
    n_fish_species = ctx.get("n_fish_species", 0)
    n_records = ctx.get("n_records", 0)
    top_cnt_fish = ctx.get("top_cnt_fish", "")
    top_cnt_max = ctx.get("top_cnt_max", 0)
    top_cnt_min = ctx.get("top_cnt_min", 0)
    top_kg_fish = ctx.get("top_kg_fish", "")
    top_kg_max = ctx.get("top_kg_max", 0.0)
    season_label = ctx.get("season_label", "")

    # タイトル
    title = f"{date_label} 関東船釣り 釣果まとめ（{n_ships}船宿・{n_fish_species}魚種・{n_records}件）"

    # 説明文
    desc_parts = [
        f"{date_label}の関東船釣り釣果まとめ。",
        f"{n_ships}船宿・{n_fish_species}魚種・{n_records}件の釣果報告。",
    ]
    if top_cnt_fish and top_cnt_max:
        desc_parts.append(f"{top_cnt_fish} {top_cnt_min}〜{top_cnt_max}匹。")
    if top_kg_fish and top_kg_max > 0:
        desc_parts.append(f"大物: {top_kg_fish} {top_kg_max:.2f}kg。")
    desc_parts.append(f"{season_label}の釣況データ | funatsuri-yoso.com")
    description = "".join(desc_parts)

    # pubDate
    now_jst = datetime.now(JST)
    pub_date = _rfc822(now_jst)
    last_build_date = _rfc822(now_jst)

    # 新規 item
    new_item = _ITEM_TEMPLATE.format(
        title=xml_escape(title),
        link=xml_escape(daily_url),
        description=xml_escape(description),
        pub_date=pub_date,
        png_url=xml_escape(png_url),
    )

    # 既存 feed から過去 item を読み込み（最大29件 = 合計30件）
    past_items = []
    if existing_feed_path and os.path.exists(existing_feed_path):
        try:
            with open(existing_feed_path, encoding="utf-8") as f:
                content = f.read()
            # <item> ブロックを抽出（単純文字列パース）
            import re
            blocks = re.findall(r"<item>.*?</item>", content, flags=re.DOTALL)
            # 最新のもの優先で 29 件取得
            for blk in blocks[:29]:
                # 当日の item は除外（重複防止）
                if daily_url not in blk:
                    past_items.append(blk.strip())
        except Exception as e:
            print(f"[build_rss] 既存 feed の読み込みに失敗: {e}")

    # items 結合
    all_items_str = new_item + ("\n" if past_items else "")
    if past_items:
        all_items_str += "\n    " + "\n    ".join(past_items)

    xml_content = _RSS_TEMPLATE.format(
        last_build_date=last_build_date,
        items=all_items_str,
    )

    os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else ".", exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(xml_content)
    print(f"[build_rss] feed.xml 保存: {output_path}")
    return xml_content
