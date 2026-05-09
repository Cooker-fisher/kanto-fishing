# test_run.py — x_post 全工程のテスト用ドライバ
# 使い方: python -m x_post.test_run --date 2026-05-08 [--dry-run]
#   --dry-run: HTML/PNG/feed.xml を保存しない（出力テキストのみ表示）

import argparse
import json
import os
import re
import sys

# ルートディレクトリをパスに追加（-m x_post.test_run で実行する想定）
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT_DIR = os.path.dirname(_THIS_DIR)
sys.path.insert(0, _ROOT_DIR)

from x_post.context_builder import build_context
from x_post.template_picker import pick_highlight, pick_ocean, pick_fish_templates
from x_post.text_generator import render_template, render_section, build_commentary_html, build_commentary_blocks, measure_text_length
from x_post.build_daily_page import build as build_daily_page
from x_post.build_rss import build as build_rss
from x_post.generate_image import create as create_image


def _load_catches(root_dir, date_str):
    """catches.json を読み込み、指定日 or 全データを返す"""
    path = os.path.join(root_dir, "catches.json")
    with open(path, encoding="utf-8") as f:
        snap = json.load(f)
    data = snap.get("data", snap) if isinstance(snap, dict) else snap
    # 指定日付でフィルタ
    date_slash = date_str.replace("-", "/")  # 2026/05/08
    day_data = [c for c in data if c.get("date", "").startswith(date_slash[:7])]
    # 完全一致があればそちらを優先
    exact = [c for c in data if c.get("date") == date_slash]
    return exact if exact else day_data


def _load_history(root_dir):
    path = os.path.join(root_dir, "history.json")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def main():
    parser = argparse.ArgumentParser(description="x_post 全工程テストドライバ")
    parser.add_argument("--date", required=True, help="対象日 (YYYY-MM-DD)")
    parser.add_argument("--dry-run", action="store_true", help="ファイル保存せず出力のみ確認")
    args = parser.parse_args()

    date_str = args.date  # "2026-05-08"
    dry_run = args.dry_run

    analysis_db = os.path.join(_ROOT_DIR, "analysis", "V2", "results", "analysis.sqlite")
    docs_x_post_dir = os.path.join(_ROOT_DIR, "docs", "x_post")
    feed_xml_path = os.path.join(_ROOT_DIR, "docs", "feed.xml")

    print(f"=== x_post test_run: {date_str} {'[DRY-RUN]' if dry_run else ''} ===\n")

    # 1. データ読み込み
    print("[1/6] データ読み込み...")
    catches = _load_catches(_ROOT_DIR, date_str)
    history = _load_history(_ROOT_DIR)
    print(f"  catches: {len(catches)} 件 / history: {len(history.get('weekly', {}))} 週分")

    # 2. ctx 組立
    print("[2/6] ctx 組立...")
    ctx = build_context(catches, history, analysis_db, date_str)
    print(f"  n_ships={ctx['n_ships']} n_fish_species={ctx['n_fish_species']} n_records={ctx['n_records']}")
    print(f"  top_cnt: {ctx['top_cnt_fish']} {ctx['top_cnt_min']}~{ctx['top_cnt_max']}匹 ({ctx['top_cnt_ship']})")
    print(f"  top_kg : {ctx['top_kg_fish']} {ctx['top_kg_max']:.2f}kg ({ctx['top_kg_ship']})")
    print(f"  tide   : {ctx['tide_type']} / {ctx['moon_phase']}")

    # 3. 文型選択
    print("[3/6] 文型選択...")
    h_tpl = pick_highlight(ctx)
    s_tpl = pick_ocean(ctx)
    f_tpls = pick_fish_templates(ctx)
    print(f"  H={h_tpl['id']}  S={s_tpl['id']}  F=[{', '.join(t['id'] for t in f_tpls)}]")

    # 4. 散文生成
    print("[4/6] 散文生成...")
    hl_text = render_template(h_tpl, ctx)
    ocean_text = render_template(s_tpl, ctx)
    fish_text = render_section(f_tpls, ctx)
    commentary_html = build_commentary_html(hl_text, ocean_text, fish_text, ctx)
    # 各セクション内に散文を配置するための dict 形式（冒頭集中問題の修正）
    commentary_blocks = build_commentary_blocks(hl_text, ocean_text, fish_text, ctx)

    # 文字数計測
    char_count = measure_text_length(commentary_html)
    print(f"  散文文字数（タグ除外）: {char_count} 字")
    if char_count < 800:
        print(f"  [WARNING] 散文が 800 字未満です（{char_count} 字）")
    else:
        print(f"  [OK] 800 字以上")

    # 補遺3 assert
    print("[4b] 補遺3 assert...")
    plain_text = re.sub(r"<[^>]+>", "", commentary_html)
    forbidden_words = ["平均", "ave", "avg", "釣りビジョン", "fishing-v.jp"]
    for word in forbidden_words:
        assert word.lower() not in plain_text.lower(), \
            f"禁止ワード検出: '{word}' が散文に含まれています"
    print("  [OK] 禁止ワードなし（平均/avg/ave/釣りビジョン/fishing-v.jp）")

    # 散文サンプル表示
    print("\n  --- 散文サンプル（先頭300字）---")
    print(plain_text[:300])
    print("  --- end ---\n")

    if dry_run:
        print("[DRY-RUN] ファイル保存をスキップ")
        print(f"\n=== 完了（dry-run）: 散文 {char_count} 字 / H={h_tpl['id']} S={s_tpl['id']} ===")
        return

    # 5. PNG 生成
    print("[5/6] PNG 生成...")
    png_path = os.path.join(docs_x_post_dir, f"{date_str}.png")
    png_ok = create_image(ctx, output_path=png_path)
    if not png_ok:
        print("  [SKIP] Pillow 未インストールのため PNG 生成スキップ")
        print("         pip install Pillow>=10.0.0 で有効化")

    # 6. HTML 生成
    print("[6a/6] HTML 生成...")
    html_path = os.path.join(docs_x_post_dir, f"{date_str}.html")
    png_url = f"https://funatsuri-yoso.com/x_post/{date_str}.png"
    daily_url = f"https://funatsuri-yoso.com/x_post/{date_str}.html"
    build_daily_page(ctx, commentary_blocks, output_path=html_path, png_url=png_url)

    # 最終 HTML 文字数確認
    with open(html_path, encoding="utf-8") as f:
        full_html = f.read()
    plain_full = re.sub(r"<[^>]+>", "", full_html)
    full_char = len(plain_full.replace("\n", "").replace(" ", ""))
    print(f"  HTML 本文字数（タグ・空白除外）: {full_char} 字")

    # 6b. feed.xml 生成
    print("[6b/6] feed.xml 生成...")
    build_rss(ctx, png_url=png_url, daily_url=daily_url,
              output_path=feed_xml_path, existing_feed_path=feed_xml_path)

    # feed.xml サンプル表示
    with open(feed_xml_path, encoding="utf-8") as f:
        feed_content = f.read()
    # <item> ブロック最初の20行を表示
    item_match = re.search(r"<item>.*?</item>", feed_content, flags=re.DOTALL)
    if item_match:
        item_lines = item_match.group(0).split("\n")[:12]
        print("\n  --- feed.xml <item> 抜粋 ---")
        print("\n".join(item_lines))
        print("  --- end ---")

    print(f"\n=== 完了: 散文 {char_count} 字 / H={h_tpl['id']} S={s_tpl['id']} ===")
    print(f"  docs/x_post/{date_str}.html")
    if png_ok:
        print(f"  docs/x_post/{date_str}.png")
    print(f"  docs/feed.xml")


if __name__ == "__main__":
    main()
