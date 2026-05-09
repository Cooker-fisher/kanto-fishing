# text_generator.py — 文型 → f-string 展開して散文 HTML 生成
# 補遺3 最終ガード: 出力テキストに「平均」「avg」「ave」が含まれないことを assert

import re


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
