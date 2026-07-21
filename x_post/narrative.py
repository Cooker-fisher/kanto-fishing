# narrative.py — 日次まとめの散文を「数値根拠つき」で生成する（2026-07-22 新設）
#
# 背景・裁定（ユーザー確定 2026-07-22）:
#   旧実装は templates.py の H/F 文型から1本選ぶ方式で、
#   「今期は好海況が観測されています」「再現性が高いと推察されます」
#   「ローテーション釣行に組み込みやすい魚種です」など**根拠のない断定風フィラー**が
#   本文の大半を占めていた。裁定 = フィラーは全廃し、
#   **数値（平年比・実数・船宿名・日数）を伴う文だけ**を出す。
#
# ここで出す文の原則:
#   1. 1文につき最低1つの検証可能な数値を含む（含められないなら文ごと出さない）
#   2. 因果は断定しない（「〜が要因」「〜と推察されます」は書かない）
#   3. 平年比は母数（同旬 N便）を必ず併記する
#   4. 予測は T47b の関門（検証済みモデル × tier A）を通ったものだけ引用する
#   5. avg は出さない（補遺3）。中央値は「中央値」と明記する
import os

from .insights import load_verified_forecast

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 平年比を文章化する最低条件（薄い母数で「平年比」と言わない）
_MIN_NORM_N = 8
# 「久々」と書く閾値（日）
_GAP_DAYS = 21


def _fmt_num(v):
    if v is None:
        return ""
    f = float(v)
    return str(int(f)) if abs(f - int(f)) < 0.05 else f"{f:.1f}"


def _cnt_range_str(cmin, cmax):
    if not cmax:
        return ""
    return f"{cmax}匹" if (cmin == cmax or not cmin) else f"{cmin}〜{cmax}匹"


def _size_str(row):
    kg_max, kg_min = row.get("kg_max") or 0, row.get("kg_min") or 0
    cm_max, cm_min = row.get("cm_max") or 0, row.get("cm_min") or 0
    if kg_max > 0:
        return f"{kg_min:.1f}〜{kg_max:.1f}kg" if 0 < kg_min < kg_max else f"最大{kg_max:.1f}kg"
    if cm_max > 0:
        return f"{cm_min}〜{cm_max}cm" if 0 < cm_min < cm_max else f"最大{cm_max}cm"
    return ""


# 平年比が ±10% 以内は「平年並み」と書く（+0%/-1% の羅列はノイズ）
_FLAT = 0.10


def _is_flat(ratio):
    return ratio is not None and abs(ratio - 1.0) <= _FLAT


def _has_norm(ins):
    return bool(ins) and bool(ins.get("ratio")) and (ins.get("norm_n") or 0) >= _MIN_NORM_N


def _norm_clause(ins):
    """平年比の説明句。母数が薄ければ空文字。±10% 以内は『平年並み』。"""
    if not _has_norm(ins):
        return ""
    base = f"過去3年の同じ旬（{ins['norm_n']}便）の中央値{_fmt_num(ins['norm_cnt'])}匹"
    if _is_flat(ins["ratio"]):
        return f"{base}に対し<b>ほぼ平年並み</b>"
    return f"{base}に対し<b>平年比 {ins['ratio_str']}</b>"


# ── ハイライトカード ────────────────────────────────────────────────────
def build_hl_cards(ctx):
    """ハイライトカード（最大4枚）を HTML で返す。全カードが数値実績ベース。"""
    ins_all = (ctx.get("insights") or {}).get("fish") or {}
    cards = []
    used_fish = set()

    # 1. 大物記録
    kg_fish, kg_max = ctx.get("top_kg_fish", ""), ctx.get("top_kg_max", 0.0)
    if kg_fish and kg_max > 0:
        kg_min = ctx.get("top_kg_min", 0.0)
        val = f"{kg_min:.1f}〜{kg_max:.2f}kg" if 0 < kg_min < kg_max else f"最大{kg_max:.2f}kg"
        ins = ins_all.get(kg_fish) or {}
        meta = f"{ctx.get('top_kg_port','')}｜{ctx.get('top_kg_ship','')}"
        if (ins.get("kg_ratio") and (ins.get("norm_n") or 0) >= _MIN_NORM_N
                and not _is_flat(ins["kg_ratio"])):
            meta += f"<br>型 平年比 <span class=\"up\">{_pct(ins['kg_ratio'])}</span>"
        cards.append(("大物記録", kg_fish, val, meta))
        used_fish.add(kg_fish)

    # 2. 数の好調
    cnt_fish, cnt_max = ctx.get("top_cnt_fish", ""), ctx.get("top_cnt_max", 0)
    if cnt_fish and cnt_max > 0:
        val = _cnt_range_str(ctx.get("top_cnt_min", 0), cnt_max)
        ins = ins_all.get(cnt_fish) or {}
        meta = f"{ctx.get('top_cnt_port','')}｜{ctx.get('top_cnt_ship','')}"
        if _has_norm(ins):
            _lbl = "ほぼ平年並み" if _is_flat(ins["ratio"]) else f"平年比 {ins['ratio_str']}"
            meta += f"<br><span class=\"up\">{_lbl}</span>（同旬{ins['norm_n']}便）"
        else:
            meta += f"<br>先週比 <span class=\"up\">{ctx.get('wow_pct_top_cnt_str','')}</span>"
        cards.append(("数の好調", cnt_fish, val, meta))
        used_fish.add(cnt_fish)

    # 3. 平年比トップ（母数十分・2便以上）
    cand = [(f, i) for f, i in ins_all.items()
            if f not in used_fish and i.get("ratio")
            and (i.get("norm_n") or 0) >= _MIN_NORM_N and (i.get("n_trips") or 0) >= 2
            and i["ratio"] >= 1.2]
    if cand:
        f, i = max(cand, key=lambda x: x[1]["ratio"])
        top = (i.get("top_trips") or [{}])[0]
        cards.append(("平年比トップ", f, f"平年比 {i['ratio_str']}",
                      f"当日中央値{_fmt_num(i['today_cnt'])}匹 / 同旬中央値{_fmt_num(i['norm_cnt'])}匹"
                      f"<br>{top.get('area','')}｜{top.get('ship','')}"))
        used_fish.add(f)

    # 4. 特記（間隔が空いた記録 / 直近60日で最多）
    if len(cards) < 4:
        gap = [(f, i) for f, i in ins_all.items()
               if f not in used_fish and (i.get("days_since_last") or 0) >= _GAP_DAYS]
        best = [(f, i) for f, i in ins_all.items()
                if f not in used_fish and i.get("rank60") == 1 and (i.get("n_days60") or 0) >= 10]
        if best:
            f, i = max(best, key=lambda x: (x[1].get("n_days60") or 0))
            top = (i.get("top_trips") or [{}])[0]
            cards.append(("直近60日で最多", f,
                          f"{_fmt_num(top.get('cnt'))}匹",
                          f"記録日{i['n_days60']}日の中で最多<br>{top.get('area','')}｜{top.get('ship','')}"))
        elif gap:
            f, i = max(gap, key=lambda x: x[1]["days_since_last"])
            top = (i.get("top_trips") or [{}])[0]
            val = f"{_fmt_num(top.get('cnt'))}匹" if top.get("cnt") else "記録あり"
            cards.append((f"{i['days_since_last']}日ぶりの記録", f, val,
                          f"{top.get('area','')}｜{top.get('ship','')}"))

    if not cards:
        return ""
    html = []
    for label, target, val, meta in cards[:4]:
        html.append(f"""      <div class="hl-card">
        <div class="label">{label}</div>
        <div class="target">{target}</div>
        <div class="val">{val}</div>
        <div class="meta">{meta}</div>
      </div>""")
    return '    <div class="hl-grid">\n' + "\n".join(html) + "\n    </div>"


def _pct(ratio):
    pct = int(round((ratio - 1) * 100))
    return f"+{pct}%" if pct >= 0 else f"{pct}%"


# ── ハイライト散文 ──────────────────────────────────────────────────────
def build_highlight_prose(ctx, root=None):
    """セクション1の散文。全文が数値根拠つき。文が1つも作れなければ空文字。"""
    root = root or _ROOT
    ins_all = (ctx.get("insights") or {}).get("fish") or {}
    rows = ctx.get("fish_rows") or []
    sents = []

    # 数のトップ
    cnt_fish = ctx.get("top_cnt_fish", "")
    if cnt_fish and ctx.get("top_cnt_max", 0) > 0:
        ins = ins_all.get(cnt_fish) or {}
        s = (f"数のトップは<b>{cnt_fish} {ctx.get('top_cnt_max')}匹</b>"
             f"（{ctx.get('top_cnt_port','')}・<b>{ctx.get('top_cnt_ship','')}</b>）。")
        nc = _norm_clause(ins)
        if nc:
            s += f"当日の{cnt_fish}は{ins['n_trips']}便で中央値{_fmt_num(ins['today_cnt'])}匹、{nc}です。"
        sents.append(s)

    # 大物
    kg_fish = ctx.get("top_kg_fish", "")
    if kg_fish and ctx.get("top_kg_max", 0) > 0:
        ins = ins_all.get(kg_fish) or {}
        s = (f"重量トップは<b>{kg_fish} {ctx.get('top_kg_max'):.2f}kg</b>"
             f"（{ctx.get('top_kg_port','')}・<b>{ctx.get('top_kg_ship','')}</b>）。")
        if (ins.get("kg_ratio") and (ins.get("norm_n") or 0) >= _MIN_NORM_N
                and not _is_flat(ins["kg_ratio"])):
            s += (f"同旬の重量中央値{_fmt_num(ins['norm_kg'])}kg に対し"
                  f"当日中央値は{_fmt_num(ins['today_kg'])}kg（{_pct(ins['kg_ratio'])}）。")
        sents.append(s)

    # 平年比で目立つ魚種（上位2件・母数十分）
    cand = [(f, i) for f, i in ins_all.items()
            if i.get("ratio") and (i.get("norm_n") or 0) >= _MIN_NORM_N and (i.get("n_trips") or 0) >= 2]
    ups = sorted([c for c in cand if c[1]["ratio"] >= 1.2], key=lambda x: -x[1]["ratio"])[:2]
    downs = sorted([c for c in cand if c[1]["ratio"] <= 0.8], key=lambda x: x[1]["ratio"])[:1]
    if ups:
        parts = [f"<b>{f}</b>（{i['ratio_str']}・同旬{i['norm_n']}便）" for f, i in ups]
        sents.append("平年（過去3年の同じ旬の中央値）を上回ったのは" + "、".join(parts) + "。")
    if downs:
        f, i = downs[0]
        sents.append(f"逆に<b>{f}</b>は同旬中央値{_fmt_num(i['norm_cnt'])}匹に対し"
                     f"当日中央値{_fmt_num(i['today_cnt'])}匹（{i['ratio_str']}）でした。")

    # 検証済み予測（tier A のみ）
    fish_names = {r["fish"] for r in rows}
    fc = load_verified_forecast(ctx.get("date_iso", ""), fish_names, root=root)
    if fc:
        f0 = fc[0]
        pb = f0.get("pb")
        acc = f"（レンジ実測の下振れ率{pb*100:.1f}%）" if isinstance(pb, (int, float)) else ""
        sents.append(f"検証済みモデル（tier A のみ公開）の{f0['date_label']}予測では、"
                     f"<b>{f0['fish']}×{f0['ship']}</b>が{_fmt_num(f0['lo'])}〜{_fmt_num(f0['hi'])}匹{acc}。"
                     f"<a href=\"/forecast/\">海況予報</a>で全{len(fc)}件を公開しています。")

    if not sents:
        return ""
    return '<div class="commentary evidence"><p>' + "".join(sents) + "</p></div>"


# ── 魚種別報告の散文 ────────────────────────────────────────────────────
def _is_notable(ins):
    """1便でも個別に触れる価値がある（記録性がある）か。"""
    if not ins:
        return False
    if ins.get("rank60") == 1 and (ins.get("n_days60") or 0) >= 10:
        return True
    if (ins.get("days_since_last") or 0) >= _GAP_DAYS:
        return True
    if _has_norm(ins) and not _is_flat(ins["ratio"]):
        return True
    return False


def _fish_sentence(fish, row, ins, single):
    """魚種1件ぶんの文。テーブルに出ている情報の反復は避け、
    テーブルに無い情報（船宿名・平年比・記録性）を主役にする。"""
    tops = [t for t in (ins.get("top_trips") or []) if t.get("cnt")]
    n = row.get("n_trips", 0)
    parts = []

    if tops:
        t = tops[0]
        area = f"（{t.get('area','')}）" if t.get("area") else ""
        if single:
            parts.append(f"<b>{fish}</b>は<b>{t['ship']}</b>{area}の{_fmt_num(t['cnt'])}匹の1便のみ。")
        else:
            head = f"<b>{fish}</b>（{n}便）の最多は<b>{t['ship']}</b>{area}の{_fmt_num(t['cnt'])}匹"
            if len(tops) > 1:
                head += f"、次点は{tops[1]['ship']}の{_fmt_num(tops[1]['cnt'])}匹"
            parts.append(head + "。")
    else:
        # 匹数未記録（型のみ記録された便）— 数の話はできないので型だけ述べる
        size = _size_str(row)
        if not size:
            return ""
        parts.append(f"<b>{fish}</b>（{n}便）は匹数の記録が無く、型は{size}。")

    nc = _norm_clause(ins)
    if nc and tops:
        if single:
            # 1便しかない日に「中央値」と書くのは不正確なので実数で述べる
            parts.append(f"この{_fmt_num(tops[0]['cnt'])}匹は{nc}。")
        else:
            parts.append(f"当日の中央値{_fmt_num(ins['today_cnt'])}匹は{nc}。")

    if ins.get("rank60") == 1 and (ins.get("n_days60") or 0) >= 10 and tops:
        parts.append(f"直近60日で記録のあった{ins['n_days60']}日の中では最多です。")
    elif (ins.get("days_since_last") or 0) >= _GAP_DAYS:
        parts.append(f"前回の記録は{ins['days_since_last']}日前でした。")

    return "".join(parts)


def build_fish_prose(ctx):
    """セクション3の散文。
    - 2便以上の魚種: 1件ずつ（船宿名・平年比・記録性）
    - 1便でも記録性のある魚種: 1件ずつ
    - それ以外の単発: 末尾に1文でまとめる（同型の文が延々と並ぶのを防ぐ）
    """
    ins_all = (ctx.get("insights") or {}).get("fish") or {}
    rows = ctx.get("fish_rows") or []
    lines, singles = [], []

    for row in rows:
        fish = row["fish"]
        ins = ins_all.get(fish) or {}
        n = row.get("n_trips", 0)
        if n >= 2 or _is_notable(ins):
            s = _fish_sentence(fish, row, ins, single=(n <= 1))
            if s:
                lines.append(f"<p>{s}</p>")
        else:
            tops = [t for t in (ins.get("top_trips") or []) if t.get("cnt")]
            if tops:
                singles.append(f"<b>{fish}</b>（{tops[0]['ship']}・{_fmt_num(tops[0]['cnt'])}匹）")
            else:
                size = _size_str(row)
                if size:
                    singles.append(f"<b>{fish}</b>（{size}）")

    if singles:
        lines.append("<p>単発（1便のみ）の記録は" + "、".join(singles) + "。</p>")

    if not lines:
        return ""
    return '<div class="commentary evidence">' + "".join(lines) + "</div>"

# ── 海況レポートの散文 ──────────────────────────────────────────────────
def build_ocean_prose(ctx):
    """セクション2の散文。実測値の記述のみ。
    旧 S 文型にあった「出船率は高い好スコア」「カンパチの遠征便も予定通り運航しました」
    のような未検証の断定は出さない（運航実績は釣果報告の有無からしか分からない）。"""
    inner = ctx.get("inner_sea_data") or {}
    outer = ctx.get("outer_sea_data") or {}

    def _leg(label, d):
        bits = []
        if d.get("sst"):
            bits.append(f"水温{float(d['sst']):.1f}℃")
        if d.get("wave") is not None:
            bits.append(f"波{float(d['wave']):.1f}m")
        if d.get("wind_spd") is not None:
            bits.append(f"{d.get('wind_dir','')}風{float(d['wind_spd']):.1f}m/s")
        return f"<b>{label}</b>は" + "・".join(bits) + "。" if bits else ""

    sents = [x for x in (_leg("内海（東京湾・相模湾）", inner),
                         _leg("外海（外房〜銚子・伊豆方面）", outer)) if x]

    tide = ctx.get("tide_type", "")
    moon = ctx.get("moon_phase", "")
    press = inner.get("pressure") or outer.get("pressure")
    tail = []
    if tide:
        tail.append(f"潮回りは{tide}" + (f"（月相{moon}）" if moon else ""))
    if press:
        tail.append(f"気圧{int(round(float(press)))}hPa")
    if tail:
        sents.append("、".join(tail) + "。")

    n_ships = ctx.get("n_ships", 0)
    n_cancel = ctx.get("n_cancellations", 0)
    if n_ships:
        s = f"当日は<b>{n_ships}船宿</b>から釣果報告があり、欠航の記録は{n_cancel}件でした。"
        sents.append(s)

    if not sents:
        return ""
    return '<div class="commentary evidence"><p>' + "".join(sents) + "</p></div>"
