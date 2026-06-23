#!/usr/bin/env python3
"""
x_post 欠落日バックフィル（共有ロジック）

日次 crawl が CI 失敗で止まり、復旧実行が JST 日付をまたいだ翌日に走ると、
x_post ページは run 日（now）基準のため「失敗した当日」のページが永久に欠落する。
このモジュールは欠落日を検知し catches CSV から該当日の x_post を復元生成する。

- A 用途（独立実行）   : `python x_post/backfill.py [YYYY-MM-DD ...] [--lookback N]`
- B 用途（自己修復）   : crawler.py 日次フローが backfill_recent() を呼ぶ

crawler._load_recent_catches_for_index で valid_catches 互換レコードを得るため、
当日スナップショット(catches.json)に依存せず過去日も再現できる。
"""
import datetime as _dt
import json
import os
import sys

_THIS = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_THIS)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


def _load_history(root):
    p = os.path.join(root, "history.json")
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def existing_dates(x_post_dir):
    """docs/x_post/ に既にある YYYY-MM-DD.html の日付集合。"""
    out = set()
    if not os.path.isdir(x_post_dir):
        return out
    for fn in os.listdir(x_post_dir):
        if len(fn) == 15 and fn.endswith(".html") and fn[:4].isdigit():
            out.add(fn[:-5])
    return out


def _has_data(valid_catches, date_iso):
    slash = date_iso.replace("-", "/")
    return any(c.get("date") == slash for c in valid_catches)


def backfill_dates(dates, valid_catches, history, root=None, make_png=True, verbose=True):
    """指定 ISO 日付リストの x_post HTML を生成。データが無い日はスキップ。
    戻り値: 実際に生成した日付リスト。"""
    root = root or _ROOT
    import crawler
    from x_post.context_builder import build_context
    from x_post.template_picker import pick_highlight, pick_ocean, pick_fish_templates
    from x_post.text_generator import render_template, render_section, build_commentary_blocks
    from x_post.build_daily_page import build as build_daily
    try:
        from x_post.generate_image import create as create_img
    except Exception:
        create_img = None

    x_post_dir = os.path.join(root, crawler.WEB_DIR, "x_post")
    os.makedirs(x_post_dir, exist_ok=True)
    weather_dir = os.path.join(root, "weather")
    made = []
    for date_iso in dates:
        if not _has_data(valid_catches, date_iso):
            if verbose:
                print(f"[backfill] {date_iso}: データなし → skip")
            continue
        try:
            ctx = build_context(valid_catches, history, crawler.ANALYSIS_DB, date_iso, weather_dir=weather_dir)
            hl = render_template(pick_highlight(ctx), ctx)
            oc = render_template(pick_ocean(ctx), ctx)
            fi = render_section(pick_fish_templates(ctx), ctx)
            blocks = build_commentary_blocks(hl, oc, fi, ctx)
            png_url = f"https://funatsuri-yoso.com/x_post/{date_iso}.png"
            if make_png and create_img is not None:
                try:
                    create_img(ctx, output_path=os.path.join(x_post_dir, f"{date_iso}.png"))
                except Exception as e:
                    if verbose:
                        print(f"[backfill] {date_iso}: PNG skip ({e})")
            build_daily(ctx, blocks,
                        output_path=os.path.join(x_post_dir, f"{date_iso}.html"),
                        png_url=png_url)
            made.append(date_iso)
            if verbose:
                print(f"[backfill] {date_iso}: 生成 ✓")
        except Exception as e:
            if verbose:
                print(f"[backfill] {date_iso}: ERROR {e}")
    return made


def _rebuild_index_rss(valid_catches, history, root, latest_iso, verbose=True):
    import crawler
    x_post_dir = os.path.join(root, crawler.WEB_DIR, "x_post")
    try:
        from x_post.build_index_page import build_index
        build_index(output_path=os.path.join(x_post_dir, "index.html"), docs_x_post_dir=x_post_dir)
        if verbose:
            print("[backfill] index.html 再構築 ✓")
    except Exception as e:
        if verbose:
            print(f"[backfill] index ERROR {e}")


def backfill_recent(now=None, lookback=10, valid_catches=None, history=None, root=None, verbose=True):
    """直近 lookback 日（当日除く）で欠落している x_post を自動補完。
    crawler.py の日次フロー末尾から呼ぶ自己修復エントリ。"""
    root = root or _ROOT
    import crawler
    now = now or _dt.datetime.now(crawler.JST).replace(tzinfo=None)
    if valid_catches is None:
        valid_catches = crawler._load_recent_catches_for_index(now, days=lookback + 2)
    if history is None:
        history = _load_history(root)
    x_post_dir = os.path.join(root, crawler.WEB_DIR, "x_post")
    have = existing_dates(x_post_dir)
    targets = []
    for k in range(1, lookback + 1):  # 1 = 前日。当日(0)は通常フローが担当
        d = (now - _dt.timedelta(days=k)).strftime("%Y-%m-%d")
        if d not in have:
            targets.append(d)
    if not targets:
        if verbose:
            print(f"[backfill] 直近{lookback}日に欠落なし")
        return []
    if verbose:
        print(f"[backfill] 欠落候補 {len(targets)}件: {targets}")
    made = backfill_dates(sorted(targets), valid_catches, history, root=root, verbose=verbose)
    if made:
        _rebuild_index_rss(valid_catches, history, root, max(made), verbose=verbose)
    return made


def main(argv):
    import crawler
    args = [a for a in argv if not a.startswith("--")]
    lookback = 10
    for a in argv:
        if a.startswith("--lookback"):
            try:
                lookback = int(a.split("=")[1]) if "=" in a else int(argv[argv.index(a) + 1])
            except Exception:
                pass
    now = _dt.datetime.now(crawler.JST).replace(tzinfo=None)
    history = _load_history(_ROOT)
    valid_catches = crawler._load_recent_catches_for_index(now, days=max(lookback + 2, 16))
    if args:
        made = backfill_dates(sorted(args), valid_catches, history, root=_ROOT)
        if made:
            _rebuild_index_rss(valid_catches, history, _ROOT, max(made))
    else:
        made = backfill_recent(now=now, lookback=lookback, valid_catches=valid_catches,
                               history=history, root=_ROOT)
    print(f"[backfill] 完了: {len(made)}件生成 {made}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
