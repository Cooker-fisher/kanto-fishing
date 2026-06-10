# text_generator.py — 文型 → f-string 展開して散文 HTML 生成
# 補遺3 最終ガード: 出力テキストに「平均」「avg」「ave」が含まれないことを assert

import json
import os
import re

# ship_romaji_map.json をモジュールレベルでキャッシュ
_SHIP_ROMAJI: dict = {}
_SHIP_ROMAJI_LOADED = False


def _load_ship_romaji() -> dict:
    """normalize/ship_romaji_map.json を読み込んでキャッシュ（M5）"""
    global _SHIP_ROMAJI, _SHIP_ROMAJI_LOADED
    if not _SHIP_ROMAJI_LOADED:
        _this_dir = os.path.dirname(os.path.abspath(__file__))
        _root_dir = os.path.dirname(_this_dir)
        _path = os.path.join(_root_dir, "normalize", "ship_romaji_map.json")
        try:
            with open(_path, encoding="utf-8") as f:
                _SHIP_ROMAJI = json.load(f)
        except Exception:
            _SHIP_ROMAJI = {}
        _SHIP_ROMAJI_LOADED = True
    return _SHIP_ROMAJI


def _linkify_ship_names(text: str) -> str:
    """
    散文 HTML 内の船宿名を <a href="/ship/{romaji}.html"> に変換する（M5）。
    - ship_romaji_map.json に登録済みの船宿名のみリンク化
    - 未登録船宿はプレーンテキストのまま（404 防止）
    - HTML タグ内は変換しない（属性値への混入防止）
    - 長い名前を先に処理（部分一致による誤変換防止）
    """
    romaji_map = _load_ship_romaji()
    if not romaji_map:
        return text

    # 長さ降順でソート（部分一致誤変換防止）
    sorted_ships = sorted(romaji_map.items(), key=lambda x: len(x[0]), reverse=True)

    # HTML タグと非タグ部分に分割して処理（タグ内は変換しない）
    parts = re.split(r"(<[^>]+>)", text)
    result = []
    for part in parts:
        if part.startswith("<"):
            result.append(part)  # タグ部分はそのまま
        else:
            for ship_name, romaji in sorted_ships:
                if ship_name in part:
                    part = part.replace(
                        ship_name,
                        f'<a href="/ship/{romaji}.html">{ship_name}</a>'
                    )
            result.append(part)
    return "".join(result)


def _safe_format(template_text, ctx):
    """
    テンプレートの {var} を ctx で置換する。
    :書式指定子: ({var:.2f} 等) に対応するため format_map を使う。
    ctx に存在しないキーは空文字列にフォールバック。
    """
    # {key:.Xf} 等の書式指定子を含む変数を抽出して展開
    # ctx の None 値を安全なデフォルトに変換
    safe_ctx = {}
    for k, v in ctx.items():
        if v is None:
            safe_ctx[k] = ""
        elif isinstance(v, list):
            safe_ctx[k] = "・".join(str(i) for i in v[:3])
        else:
            safe_ctx[k] = v

    class _DefaultDict(dict):
        def __missing__(self, key):
            # 書式指定子を含む場合は 0 / 0.0 でフォールバック
            return ""

    try:
        return template_text.format_map(_DefaultDict(safe_ctx))
    except (ValueError, KeyError):
        # 書式指定子エラーの場合は単純置換
        result = template_text
        for k, v in safe_ctx.items():
            result = result.replace("{" + k + "}", str(v))
        return result


def render_template(template, ctx):
    """文型 dict + ctx → 展開済み散文テキスト（HTML インライン可）"""
    return _safe_format(template["text"], ctx)


def render_section(templates_list, ctx):
    """
    複数テンプレートのリスト（pick_fish_templates の戻り値等）を
    改行で連結して1つのテキストブロックにする。
    """
    parts = [render_template(t, ctx) for t in templates_list]
    return "\n".join(parts)


def build_commentary_html(hl_text, ocean_text, fish_texts, ctx):
    """
    3セクションの散文 HTML を組み立てる。
    hl_text: str (H セクション展開済み)
    ocean_text: str (S セクション展開済み)
    fish_texts: str (F セクション複数テンプレート連結済み)
    返り値: str (HTML)
    """
    date_label = ctx.get("date_label", "")
    n_records = ctx.get("n_records", 0)
    n_ships = ctx.get("n_ships", 0)
    n_fish_species = ctx.get("n_fish_species", 0)
    season_label = ctx.get("season_label", "")

    html_parts = []
    html_parts.append(f"""<div class="commentary">
<p class="lead">{date_label}の関東船釣り釣果まとめ。{n_ships}船宿・{n_fish_species}魚種・{n_records}件の釣果報告が届きました。{season_label}の釣況をデータでお届けします。</p>""")

    # セクション①
    html_parts.append(f"""
<h3 class="commentary-h">今日のハイライト</h3>
<p>{hl_text}</p>""")

    # セクション②
    html_parts.append(f"""
<h3 class="commentary-h">海況レポート</h3>
<p>{ocean_text}</p>""")

    # セクション③
    html_parts.append(f"""
<h3 class="commentary-h">魚種別釣果報告</h3>
<p>{fish_texts}</p>""")

    html_parts.append("</div>")

    full_text = "\n".join(html_parts)

    # M5: commentary 内の船宿名をリンク化
    full_text = _linkify_ship_names(full_text)

    # 補遺3 最終ガード
    # HTML タグを除去して純テキストで確認
    plain = re.sub(r"<[^>]+>", "", full_text)
    _forbidden = ["釣りビジョン", "fishing-v.jp", "fishing-v"]
    for word in _forbidden:
        assert word not in plain, f"データソース言及禁止: '{word}' が含まれています"

    return full_text


def measure_text_length(html_text):
    """HTML タグを除去した純テキスト文字数を返す（800字以上チェック用）"""
    plain = re.sub(r"<[^>]+>", "", html_text)
    return len(plain)


def build_commentary_blocks(hl_text, ocean_text, fish_texts, ctx):
    """
    各セクション用の散文 HTML ブロックを dict で返す（冒頭集中問題の修正）。
    返り値: {"intro": "<p class='lead'>...</p>",
             "hl": "<p>...</p>",
             "ocean": "<p>...</p>",
             "fish": "<p>...</p>"}
    各セクション内の最後に挿入する想定。
    """
    date_label = ctx.get("date_label", "")
    n_records = ctx.get("n_records", 0)
    n_ships = ctx.get("n_ships", 0)
    n_fish_species = ctx.get("n_fish_species", 0)
    season_label = ctx.get("season_label", "")

    intro = (f'<p class="lead">{date_label}は<b>{n_ships}船宿</b>が出船し、'
             f'<b>{n_fish_species}魚種</b>で<b>{n_records}件</b>の釣果報告が寄せられました。'
             f'{season_label}の釣況をデータでお届けします。</p>')
    hl = f'<div class="commentary"><p>{hl_text}</p></div>'
    ocean = f'<div class="commentary"><p>{ocean_text}</p></div>'
    fish = f'<div class="commentary"><p>{fish_texts}</p></div>'

    blocks = {"intro": intro, "hl": hl, "ocean": ocean, "fish": fish}

    # 船宿リンク化（intro は不要・hl/ocean/fish のみ）
    for k in ("hl", "ocean", "fish"):
        blocks[k] = _linkify_ship_names(blocks[k])

    # 禁止語ガード
    plain = " ".join(re.sub(r"<[^>]+>", "", v) for v in blocks.values())
    _forbidden = ["釣りビジョン", "fishing-v.jp", "fishing-v"]
    for word in _forbidden:
        assert word not in plain, f"データソース言及禁止: '{word}' が含まれています"

    return blocks


# ── X 投稿文ドラフト（発見型・2026-06-10） ─────────────────────────────────────
# 背景: 定型「◯/◯ 釣果まとめ」投稿はインプレッションが取れても反応されない
# （海況詳細 533imp/♥1・まとめ 115imp/♥1 vs シミュレーター告知 454imp/♥6/RT2）。
# 「報告」ではなく「発見（驚きのある1つの数字を冒頭に）」で投稿するためのドラフトを
# 毎日自動生成し、日次ページにコピー用として掲載する。
#
# 制約:
# - 補遺3: avg/平均を出さない（レンジ min〜max または「最大◯匹」の事実表現のみ）
# - データソース（釣りビジョン等）への言及なし
# - X の重み付き字数制限: 全角140字相当。本文は全角110字以内を目安に収める

def _x_len(text: str) -> int:
    """X の重み付き字数（全角=2, 半角=1 の近似）を返す。上限は 280。"""
    return sum(2 if ord(c) > 0x7F else 1 for c in text)


def build_x_post_drafts(ctx) -> list:
    """発見型の X 投稿文ドラフトを優先度順に最大3本返す。

    投稿タイミング前提: 16:30 JST 生成 → 翌朝 8:00 JST 投稿（ユーザー運用 2026-06-10）。
    そのため相対表現は「昨日」基準。基本フックは date_label（日付明示）なので影響なし。

    戻り値: [{"label": str, "text": str}, ...]
    フックの優先順位（強い発見から）:
      1. 例年比フック: season_ratio_top_cnt >= 1.5（この旬の過去実績比・analysis.sqlite 必要）
      2. 大物フック:   top_kg_max >= 3.0
      3. 急増フック:   wow_pct_top_cnt >= 1.5 かつ top_cnt_max >= 30（先週比）
      4. 数釣りフック: top_cnt_max >= 30
      5. 型フック:     top_cm_max >= 40
      6. フォールバック: 当日の基本サマリー
    """
    date_iso = ctx.get("date_iso", "")
    date_label = ctx.get("date_label", "")
    link = f"https://funatsuri-yoso.com/x_post/{date_iso}.html" if date_iso else "https://funatsuri-yoso.com/"

    f_cnt = ctx.get("top_cnt_fish", "")
    ship_cnt = ctx.get("top_cnt_ship", "")
    port_cnt = ctx.get("top_cnt_port", "")
    cnt_max = ctx.get("top_cnt_max", 0) or 0
    cnt_range = ctx.get("top_cnt_range", "")
    sr = ctx.get("season_ratio_top_cnt") or 0
    wow = ctx.get("wow_pct_top_cnt") or 0
    wow_str = ctx.get("wow_pct_top_cnt_str", "")

    f_kg = ctx.get("top_kg_fish", "")
    ship_kg = ctx.get("top_kg_ship", "")
    port_kg = ctx.get("top_kg_port", "")
    kg_max = ctx.get("top_kg_max", 0) or 0

    f_cm = ctx.get("top_cm_fish", "")
    port_cm = ctx.get("top_cm_port", "")
    cm_max = ctx.get("top_cm_max", 0) or 0

    n_ships = ctx.get("n_ships", 0)
    n_fish = ctx.get("n_fish_species", 0)

    hooks = []  # (label, 本文1〜2行, ハッシュタグ魚種)
    if sr >= 1.5 and f_cnt and cnt_max >= 10:
        hooks.append((
            "例年比",
            f"{port_cnt}・{ship_cnt}の{f_cnt}、昨日{cnt_range}。\nこの時期の過去実績の{sr}倍ペースです。",
            f_cnt,
        ))
    if kg_max >= 3.0 and f_kg:
        hooks.append((
            "大物",
            f"{f_kg} {kg_max:.1f}kg、{port_kg}・{ship_kg}で上がりました。\n昨日の関東で一番の大物です。",
            f_kg,
        ))
    if wow >= 1.5 and cnt_max >= 30 and f_cnt and wow_str:
        hooks.append((
            "急増",
            f"{f_cnt}が動き出しました。{port_cnt}・{ship_cnt}で{cnt_range}、先週比{wow_str}。",
            f_cnt,
        ))
    if cnt_max >= 30 and f_cnt:
        hooks.append((
            "数釣り",
            f"昨日の関東で一番釣れたのは{port_cnt}・{ship_cnt}の{f_cnt}、{cnt_range}。",
            f_cnt,
        ))
    if cm_max >= 40 and f_cm:
        hooks.append((
            "型",
            f"{f_cm} 最大{cm_max}cm（{port_cm}）。型狙いに良い流れです。",
            f_cm,
        ))
    # フォールバック（必ず1本は出す）
    hooks.append((
        "基本",
        f"{date_label}の関東船釣り: {n_ships}船宿・{n_fish}魚種の釣果が出ました。",
        f_cnt or "",
    ))

    drafts = []
    for label, body, fish_tag in hooks[:3]:
        tags = "#船釣り" + (f" #{fish_tag}" if fish_tag else "")
        no_link = f"{body}\n\n{tags}"
        with_link = f"{body}\n\n詳細→ {link}\n{tags}"
        drafts.append({
            "label": f"{label}フック",
            "text_no_link": no_link,   # リーチ重視（X はリンク付きを抑制するため既定）
            # 字数超過時はリンクなし版にフォールバック
            "text_with_link": with_link if _x_len(with_link) <= 270 else no_link,
        })
    return drafts
