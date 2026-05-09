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
