# template_picker.py — 条件評価・文型選択ロジック
# H1→H20 順に評価。最初にヒットした文型を採用。フォールバックは必ず最終位置。
# F セクションは複数同時採用可（F1 冒頭固定 + F2-F11 並列 + F12-F19 末尾1つ + F20 フォールバック）

from .templates import H_TEMPLATES, S_TEMPLATES, F_TEMPLATES


def _eval_cond(cond, ctx):
    """単一条件を評価する。(key, op, value) のタプル。"""
    key, op, val = cond
    ctx_val = ctx.get(key)
    if ctx_val is None:
        # None は比較できないので False とみなす（条件不成立）
        return False
    try:
        if op == ">=":
            return float(ctx_val) >= float(val)
        elif op == "<=":
            return float(ctx_val) <= float(val)
        elif op == ">":
            return float(ctx_val) > float(val)
        elif op == "<":
            return float(ctx_val) < float(val)
        elif op == "==":
            return ctx_val == val
        elif op == "!=":
            return ctx_val != val
        elif op == "in":
            return ctx_val in val
        elif op == "not_in":
            return ctx_val not in val
    except (TypeError, ValueError):
        return False
    return False


def _all_conds(template, ctx):
    """テンプレートの全条件が満たされているか確認。条件ゼロ（フォールバック）は常に True。"""
    return all(_eval_cond(c, ctx) for c in template["conds"])


def pick_highlight(ctx):
    """H セクションから最初にヒットした文型を返す。必ずいずれかが返る（H20 フォールバック）。"""
    for tpl in H_TEMPLATES:
        if _all_conds(tpl, ctx):
            return tpl
    # フォールバック（H_TEMPLATES[-1] は conds=[] なので必ずヒットするが念のため）
    return H_TEMPLATES[-1]


def pick_ocean(ctx):
    """S セクションから最初にヒットした文型を返す。"""
    for tpl in S_TEMPLATES:
        if _all_conds(tpl, ctx):
            return tpl
    return S_TEMPLATES[-1]


def pick_fish_templates(ctx):
    """
    F セクションの選択ロジック（複数同時採用可）。
    - F1 (全体感): conds が満たされれば先頭に固定（フォールバック F20 除外のリスト）
    - F2〜F11 (魚種別): ヒット全件を並列出力
    - F12〜F19 (全体補足): 最初にヒットした1つのみ
    - F20 (フォールバック): F2-F19 が0件のときのみ採用
    返り値: list of template dict
    """
    result = []

    # F1: 全体感（単一）
    f1 = F_TEMPLATES[0]
    if _all_conds(f1, ctx):
        result.append(f1)

    # F2〜F11: 魚種別（並列）
    fish_specific = F_TEMPLATES[1:11]  # F2-F11
    fish_hits = [t for t in fish_specific if _all_conds(t, ctx)]
    result.extend(fish_hits)

    # F12〜F19: 全体補足（最初の1つ）
    supplement = F_TEMPLATES[11:19]  # F12-F19
    for tpl in supplement:
        if _all_conds(tpl, ctx):
            result.append(tpl)
            break

    # F20: 魚種別・全体補足がゼロの場合のフォールバック
    if not fish_hits:
        result.append(F_TEMPLATES[-1])  # F20

    return result
