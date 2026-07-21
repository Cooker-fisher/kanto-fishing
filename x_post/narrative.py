# narrative.py — 日次まとめの散文を「数値根拠つき・平易な日本語」で生成する（2026-07-22 新設）
#
# 背景・裁定（ユーザー確定 2026-07-22）:
#   旧実装は templates.py の H/F 文型から1本選ぶ方式で、
#   「今期は好海況が観測されています」「再現性が高いと推察されます」など
#   **根拠のない断定風フィラー**が本文の大半だった。裁定 = フィラー全廃・数値根拠のみ。
#   同日の第2ラウンド指摘 = 「tier A のような内部用語は読者に通じない」
#   「同旬・中央値・母数といった言い回しが読みにくい」「読んだ人がおっ！となるように」。
#
# 文章ルール:
#   1. 内部用語を書かない。
#        tier A → 「過去の実績と照らして精度を確かめられた組み合わせだけ」
#        同旬   → 「7月下旬」など season_label をそのまま使う
#        中央値 → 「◯匹前後」／母数 → 「過去3年の同じ時期◯便との比較」
#        平年比 +81% → 「例年の1.8倍」（倍率のほうが直感的）
#   2. 1文につき最低1つの検証可能な数値を含む（含められないなら文ごと出さない）
#   3. 因果は断定しない（「〜が要因」「〜と推察されます」は書かない）
#   4. 予測は T47b の関門（検証済みモデル × tier A）を通ったものだけ引用する（表記は平易化）
#   5. avg は出さない（補遺3）
import os

from .insights import load_verified_forecast

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 「例年と比べる」ために最低限必要な過去便数（これ未満は比較を書かない）
_MIN_NORM_N = 8
# 「久しぶり」と書く閾値（日）
_GAP_DAYS = 21
# 例年比が ±10% 以内は「例年並み」
_FLAT = 0.10


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


def _is_flat(ratio):
    # 1.1 の浮動小数誤差で境界を割らないよう微小イプシロンを足す
    return ratio is not None and abs(ratio - 1.0) <= _FLAT + 1e-9


def _has_norm(ins):
    return bool(ins) and bool(ins.get("ratio")) and (ins.get("norm_n") or 0) >= _MIN_NORM_N


def times_label(ratio):
    """倍率の平易表現。'例年の1.8倍' / '例年並み' / '例年の4割ほど'"""
    if ratio is None:
        return ""
    if _is_flat(ratio):
        return "例年並み"
    if ratio >= 1.0:
        return f"例年の{ratio:.1f}倍"
    wari = int(round(ratio * 10))
    return f"例年の{wari}割ほど" if wari >= 1 else "例年を大きく下回る数"


def times_short(ratio):
    """テーブル chip 用の短い表現。"""
    if ratio is None:
        return ""
    if _is_flat(ratio):
        return "例年並み"
    return f"例年の{ratio:.1f}倍" if ratio >= 1.0 else f"例年の{max(int(round(ratio * 10)), 1)}割"


# ── ハイライトカード ────────────────────────────────────────────────────
def build_hl_cards(ctx):
    """ハイライトカード（最大4枚）。全カードが実績値ベース。"""
    ins_all = (ctx.get("insights") or {}).get("fish") or {}
    season = ctx.get("season_label", "この時期")
    cards = []
    used = set()

    # 1. 大物記録
    kg_fish, kg_max = ctx.get("top_kg_fish", ""), ctx.get("top_kg_max", 0.0)
    if kg_fish and kg_max > 0:
        kg_min = ctx.get("top_kg_min", 0.0)
        val = f"{kg_min:.1f}〜{kg_max:.2f}kg" if 0 < kg_min < kg_max else f"最大{kg_max:.2f}kg"
        ins = ins_all.get(kg_fish) or {}
        meta = f"{ctx.get('top_kg_port','')}｜{ctx.get('top_kg_ship','')}"
        if (ins.get("kg_ratio") and (ins.get("norm_n") or 0) >= _MIN_NORM_N
                and not _is_flat(ins["kg_ratio"])):
            meta += f"<br>型は<span class=\"up\">{times_short(ins['kg_ratio'])}</span>"
        cards.append(("きょう一番の大物", kg_fish, val, meta))
        used.add(kg_fish)

    # 2. 数の好調
    cnt_fish, cnt_max = ctx.get("top_cnt_fish", ""), ctx.get("top_cnt_max", 0)
    if cnt_fish and cnt_max > 0:
        val = _cnt_range_str(ctx.get("top_cnt_min", 0), cnt_max)
        ins = ins_all.get(cnt_fish) or {}
        meta = f"{ctx.get('top_cnt_port','')}｜{ctx.get('top_cnt_ship','')}"
        if _has_norm(ins):
            meta += f"<br>{season}としては<span class=\"up\">{times_short(ins['ratio'])}</span>"
        cards.append(("数がいちばん出た魚", cnt_fish, val, meta))
        used.add(cnt_fish)

    # 3. 例年より好調
    cand = [(f, i) for f, i in ins_all.items()
            if f not in used and i.get("ratio")
            and (i.get("norm_n") or 0) >= _MIN_NORM_N and (i.get("n_trips") or 0) >= 2
            and i["ratio"] >= 1.2]
    if cand:
        f, i = max(cand, key=lambda x: x[1]["ratio"])
        top = (i.get("top_trips") or [{}])[0]
        cards.append(("例年よりよく釣れた魚", f, times_short(i["ratio"]),
                      f"{season}のふだんは{_fmt_num(i['norm_cnt'])}匹前後 → きょうは{_fmt_num(i['today_cnt'])}匹前後"
                      f"<br>{top.get('area','')}｜{top.get('ship','')}"))
        used.add(f)

    # 4. 特記（2か月で最多 / 久しぶりの記録）
    if len(cards) < 4:
        best = [(f, i) for f, i in ins_all.items()
                if f not in used and i.get("rank60") == 1 and (i.get("n_days60") or 0) >= 10]
        gap = [(f, i) for f, i in ins_all.items()
               if f not in used and (i.get("days_since_last") or 0) >= _GAP_DAYS]
        if best:
            f, i = max(best, key=lambda x: (x[1].get("n_days60") or 0))
            top = (i.get("top_trips") or [{}])[0]
            cards.append(("この2か月で最多", f, f"{_fmt_num(top.get('cnt'))}匹",
                          f"2か月で釣果の出た{i['n_days60']}日のどれよりも多い"
                          f"<br>{top.get('area','')}｜{top.get('ship','')}"))
        elif gap:
            f, i = max(gap, key=lambda x: x[1]["days_since_last"])
            top = (i.get("top_trips") or [{}])[0]
            val = f"{_fmt_num(top.get('cnt'))}匹" if top.get("cnt") else "記録あり"
            cards.append((f"{i['days_since_last']}日ぶりに顔を出した魚", f, val,
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


# ── ハイライト散文 ──────────────────────────────────────────────────────
def build_highlight_prose(ctx, root=None):
    """セクション1の散文。短い段落を積み重ね、驚きのある数字を先頭に置く。"""
    root = root or _ROOT
    ins_all = (ctx.get("insights") or {}).get("fish") or {}
    season = ctx.get("season_label", "この時期")
    rows = ctx.get("fish_rows") or []
    paras = []

    # フック: 数のトップ
    cnt_fish = ctx.get("top_cnt_fish", "")
    if cnt_fish and ctx.get("top_cnt_max", 0) > 0:
        ins = ins_all.get(cnt_fish) or {}
        s = (f"きょういちばんの数字は<b>{cnt_fish} {ctx.get('top_cnt_max')}匹</b>。"
             f"{ctx.get('top_cnt_port','')}の<b>{ctx.get('top_cnt_ship','')}</b>から出た記録です。")
        if _has_norm(ins) and not _is_flat(ins["ratio"]):
            s += (f"この日の{cnt_fish}は{ins['n_trips']}便で{_fmt_num(ins['today_cnt'])}匹前後。"
                  f"{season}のふだんは{_fmt_num(ins['norm_cnt'])}匹前後なので、"
                  f"<b>{times_label(ins['ratio'])}</b>のペースでした。")
        elif _has_norm(ins):
            s += f"{season}としては{times_label(ins['ratio'])}のペースです。"
        if ins.get("rank60") == 1 and (ins.get("n_days60") or 0) >= 10:
            s += f"この2か月で釣果の出た{ins['n_days60']}日の中でも最多です。"
        paras.append(s)

    # 大物
    kg_fish = ctx.get("top_kg_fish", "")
    if kg_fish and ctx.get("top_kg_max", 0) > 0:
        ins = ins_all.get(kg_fish) or {}
        s = (f"重さでは<b>{kg_fish} {ctx.get('top_kg_max'):.1f}kg</b>。"
             f"{ctx.get('top_kg_port','')}の<b>{ctx.get('top_kg_ship','')}</b>で上がりました。")
        if (ins.get("kg_ratio") and (ins.get("norm_n") or 0) >= _MIN_NORM_N
                and not _is_flat(ins["kg_ratio"])):
            s += (f"{season}のふだんの型は{_fmt_num(ins['norm_kg'])}kg前後なので、"
                  f"{times_label(ins['kg_ratio'])}の型です。")
        paras.append(s)

    # 例年との差（上振れ・下振れ）
    cand = [(f, i) for f, i in ins_all.items()
            if i.get("ratio") and (i.get("norm_n") or 0) >= _MIN_NORM_N and (i.get("n_trips") or 0) >= 2]
    ups = sorted([c for c in cand if c[1]["ratio"] >= 1.2], key=lambda x: -x[1]["ratio"])[:2]
    downs = sorted([c for c in cand if c[1]["ratio"] <= 0.8], key=lambda x: x[1]["ratio"])[:1]
    if ups or downs:
        s = ""
        if ups:
            parts = [f"<b>{f}</b>が{times_label(i['ratio'])}" for f, i in ups]
            s += f"{season}の実績と比べて伸びたのは" + "、".join(parts) + "。"
        if downs:
            f, i = downs[0]
            s += (f"逆に<b>{f}</b>は{times_label(i['ratio'])}で、"
                  f"ふだんの{_fmt_num(i['norm_cnt'])}匹前後には届きませんでした。")
        paras.append(s)

    # あすの予想（内部用語を出さない）
    fish_names = {r["fish"] for r in rows}
    fc = load_verified_forecast(ctx.get("date_iso", ""), fish_names, root=root)
    if fc:
        f0 = fc[0]
        pb = f0.get("pb")
        s = (f"<b>{f0['date_label']}の予想</b>は、{f0['ship']}の{f0['fish']}が"
             f"<b>{round(f0['lo'])}〜{round(f0['hi'])}匹</b>。")
        if isinstance(pb, (int, float)):
            s += f"過去の実績では{(1 - pb) * 100:.0f}%の便がこの範囲に収まっていました。"
        s += (f"予想を出すのは、過去の実績と照らして精度を確かめられた船宿・魚種の組み合わせだけです"
              f"（きょう時点で{len(fc)}件）。<a href=\"/forecast/\">あすの予想を見る</a>")
        paras.append(s)

    if not paras:
        return ""
    return '<div class="commentary evidence">' + "".join(f"<p>{p}</p>" for p in paras) + "</div>"


# ── 魚種別報告の散文 ────────────────────────────────────────────────────
def _is_notable(ins):
    """1便でも個別に触れる価値があるか。"""
    if not ins:
        return False
    if ins.get("rank60") == 1 and (ins.get("n_days60") or 0) >= 10:
        return True
    if (ins.get("days_since_last") or 0) >= _GAP_DAYS:
        return True
    if _has_norm(ins) and not _is_flat(ins["ratio"]):
        return True
    return False


def _fish_sentence(fish, row, ins, single, season):
    """魚種1件ぶんの文。テーブルに出ている情報の反復は避け、
    テーブルに無い情報（どの船宿で出たか・例年との差・記録性）を主役にする。"""
    tops = [t for t in (ins.get("top_trips") or []) if t.get("cnt")]
    n = row.get("n_trips", 0)
    parts = []

    if tops:
        t = tops[0]
        area = f"（{t.get('area','')}）" if t.get("area") else ""
        if single:
            parts.append(f"<b>{fish}</b> — <b>{t['ship']}</b>{area}の{_fmt_num(t['cnt'])}匹、この1便のみ。")
        else:
            head = f"<b>{fish}</b>（{n}便）— トップは<b>{t['ship']}</b>{area}の{_fmt_num(t['cnt'])}匹"
            if len(tops) > 1:
                head += f"、次いで{tops[1]['ship']}の{_fmt_num(tops[1]['cnt'])}匹"
            parts.append(head + "。")
    else:
        size = _size_str(row)
        if not size:
            return ""
        parts.append(f"<b>{fish}</b>（{n}便）— 匹数の記録はなく、型は{size}。")

    if tops and _has_norm(ins):
        if single:
            parts.append(f"{season}としては{times_label(ins['ratio'])}です。")
        elif _is_flat(ins["ratio"]):
            parts.append(f"全体では{_fmt_num(ins['today_cnt'])}匹前後で、{season}としては例年並み。")
        else:
            parts.append(f"全体では{_fmt_num(ins['today_cnt'])}匹前後。"
                         f"{season}のふだんは{_fmt_num(ins['norm_cnt'])}匹前後なので"
                         f"<b>{times_label(ins['ratio'])}</b>です。")

    if ins.get("rank60") == 1 and (ins.get("n_days60") or 0) >= 10 and tops:
        parts.append("この2か月では最多の記録。")
    elif (ins.get("days_since_last") or 0) >= _GAP_DAYS:
        parts.append(f"記録が出るのは{ins['days_since_last']}日ぶりです。")

    return "".join(parts)


def build_fish_prose(ctx):
    """セクション3の散文。
    - 2便以上の魚種: 1件ずつ（船宿名・例年との差・記録性）
    - 1便でも記録性のある魚種: 1件ずつ
    - それ以外の単発: 末尾に1文でまとめる
    """
    ins_all = (ctx.get("insights") or {}).get("fish") or {}
    season = ctx.get("season_label", "この時期")
    rows = ctx.get("fish_rows") or []
    lines, singles = [], []

    for row in rows:
        fish = row["fish"]
        ins = ins_all.get(fish) or {}
        n = row.get("n_trips", 0)
        if n >= 2 or _is_notable(ins):
            s = _fish_sentence(fish, row, ins, single=(n <= 1), season=season)
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
        lines.append("<p>このほか1便だけ記録が出たのは" + "、".join(singles) + "。</p>")

    if not lines:
        return ""
    return '<div class="commentary evidence">' + "".join(lines) + "</div>"


# ── 海況レポートの散文 ──────────────────────────────────────────────────
def build_ocean_prose(ctx):
    """セクション2の散文。実測値の記述のみ。
    旧 S 文型にあった「出船率は高い好スコア」「遠征便も予定通り運航しました」のような
    未検証の断定は出さない（運航実績は釣果報告の有無からしか分からない）。"""
    inner = ctx.get("inner_sea_data") or {}
    outer = ctx.get("outer_sea_data") or {}

    def _leg(label, d):
        bits = []
        if d.get("sst"):
            bits.append(f"水温{float(d['sst']):.1f}℃")
        if d.get("wave") is not None:
            bits.append(f"波{float(d['wave']):.1f}m")
        if d.get("wind_spd") is not None:
            bits.append(f"{d.get('wind_dir','')}の風{float(d['wind_spd']):.1f}m/s")
        return f"<b>{label}</b>は" + "・".join(bits) + "。" if bits else ""

    sents = [x for x in (_leg("東京湾・相模湾", inner),
                         _leg("外房〜銚子・伊豆方面", outer)) if x]

    tide = ctx.get("tide_type", "")
    moon = ctx.get("moon_phase", "")
    press = inner.get("pressure") or outer.get("pressure")
    tail = []
    if tide:
        tail.append(f"潮は{tide}" + (f"（月は{moon}）" if moon else ""))
    if press:
        tail.append(f"気圧{int(round(float(press)))}hPa")
    if tail:
        sents.append("、".join(tail) + "。")

    n_ships = ctx.get("n_ships", 0)
    n_cancel = ctx.get("n_cancellations", 0)
    if n_ships:
        sents.append(f"この日は<b>{n_ships}軒</b>の船宿から釣果の報告があり、欠航の記録は{n_cancel}件でした。")

    if not sents:
        return ""
    return '<div class="commentary evidence"><p>' + "".join(sents) + "</p></div>"

# ── セクション1のリード文 ──────────────────────────────────────────────
def build_intro(ctx):
    """『N船宿が出船し…データでお届けします』という中身の無いリードを、
    その日の要点（例年を上回った魚種の数）に置き換える。"""
    ins_all = (ctx.get("insights") or {}).get("fish") or {}
    season = ctx.get("season_label", "この時期")
    n_ships = ctx.get("n_ships", 0)
    n_fish = ctx.get("n_fish_species", 0)
    n_rec = ctx.get("n_records", 0)
    if not (n_ships and n_rec):
        return ""
    s = (f'{ctx.get("date_label","")}は<b>{n_ships}船宿</b>が出船し、'
         f'<b>{n_fish}魚種</b>で<b>{n_rec}件</b>の釣果報告がありました。')
    up = [f for f, i in ins_all.items()
          if _has_norm(i) and (i.get("n_trips") or 0) >= 2 and i["ratio"] >= 1.2]
    if up:
        head = "・".join(sorted(up, key=lambda f: -ins_all[f]["ratio"])[:3])
        s += f'このうち<b>{len(up)}魚種</b>が{season}の例年を上回りました（{head} ほか）。'
    return f'<p class="lead">{s}</p>'
