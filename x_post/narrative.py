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
    """倍率の平易表現。'例年の1.8倍' / '例年並み' / '例年の4割程度'"""
    if ratio is None:
        return ""
    if _is_flat(ratio):
        return "例年並み"
    if ratio >= 1.0:
        return f"例年の{ratio:.1f}倍"
    wari = int(round(ratio * 10))
    return f"例年の{wari}割程度" if wari >= 1 else "例年を大きく下回る数"


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
        cards.append(("本日の最大魚", kg_fish, val, meta))
        used.add(kg_fish)

    # 2. 数の好調
    cnt_fish, cnt_max = ctx.get("top_cnt_fish", ""), ctx.get("top_cnt_max", 0)
    if cnt_fish and cnt_max > 0:
        val = _cnt_range_str(ctx.get("top_cnt_min", 0), cnt_max)
        ins = ins_all.get(cnt_fish) or {}
        meta = f"{ctx.get('top_cnt_port','')}｜{ctx.get('top_cnt_ship','')}"
        if _has_norm(ins):
            meta += f"<br>{season}としては<span class=\"up\">{times_short(ins['ratio'])}</span>"
        cards.append(("最も数が出た魚", cnt_fish, val, meta))
        used.add(cnt_fish)

    # 3. 例年より好調
    cand = [(f, i) for f, i in ins_all.items()
            if f not in used and i.get("ratio")
            and (i.get("norm_n") or 0) >= _MIN_NORM_N and (i.get("n_trips") or 0) >= 2
            and i["ratio"] >= 1.2]
    if cand:
        f, i = max(cand, key=lambda x: x[1]["ratio"])
        top = (i.get("top_trips") or [{}])[0]
        cards.append(("例年を上回った魚", f, times_short(i["ratio"]),
                      f"{season}の平年は{_fmt_num(i['norm_cnt'])}匹前後 → 本日は{_fmt_num(i['today_cnt'])}匹前後"
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
            cards.append(("過去2か月で最多", f, f"{_fmt_num(top.get('cnt'))}匹",
                          f"過去2か月で釣果の出た{i['n_days60']}日のどれよりも多い"
                          f"<br>{top.get('area','')}｜{top.get('ship','')}"))
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
        s = (f"本日の最多は<b>{cnt_fish} {ctx.get('top_cnt_max')}匹</b>。"
             f"{ctx.get('top_cnt_port','')}の<b>{ctx.get('top_cnt_ship','')}</b>での記録です。")
        if _has_norm(ins) and not _is_flat(ins["ratio"]):
            s += (f"本日の{cnt_fish}は{ins['n_trips']}便で{_fmt_num(ins['today_cnt'])}匹前後。"
                  f"{season}の平年は{_fmt_num(ins['norm_cnt'])}匹前後なので、"
                  f"<b>{times_label(ins['ratio'])}</b>のペースでした。")
        elif _has_norm(ins):
            s += f"{season}としては{times_label(ins['ratio'])}のペースです。"
        if ins.get("rank60") == 1 and (ins.get("n_days60") or 0) >= 10:
            s += f"この過去2か月で釣果の出た{ins['n_days60']}日の中でも最多です。"
        paras.append(s)

    # 大物
    kg_fish = ctx.get("top_kg_fish", "")
    if kg_fish and ctx.get("top_kg_max", 0) > 0:
        ins = ins_all.get(kg_fish) or {}
        s = (f"重量では<b>{kg_fish} {ctx.get('top_kg_max'):.1f}kg</b>。"
             f"{ctx.get('top_kg_port','')}の<b>{ctx.get('top_kg_ship','')}</b>で記録されました。")
        if (ins.get("kg_ratio") and (ins.get("norm_n") or 0) >= _MIN_NORM_N
                and not _is_flat(ins["kg_ratio"])):
            s += (f"{season}の平年の型は{_fmt_num(ins['norm_kg'])}kg前後なので、"
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
                  f"平年の{_fmt_num(i['norm_cnt'])}匹前後には届きませんでした。")
        paras.append(s)

    # 明日の予想（内部用語を出さない）
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
              f"（本日時点で{len(fc)}件）。<a href=\"/forecast/\">明日の予想を見る</a>")
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
            parts.append(f"<b>{fish}</b> — <b>{t['ship']}</b>{area}の{_fmt_num(t['cnt'])}匹、の1便のみ。")
        else:
            head = f"<b>{fish}</b>（{n}便）— 最多は<b>{t['ship']}</b>{area}の{_fmt_num(t['cnt'])}匹"
            if len(tops) > 1:
                head += f"、次点は{tops[1]['ship']}の{_fmt_num(tops[1]['cnt'])}匹"
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
                         f"{season}の平年は{_fmt_num(ins['norm_cnt'])}匹前後なので"
                         f"<b>{times_label(ins['ratio'])}</b>です。")

    if ins.get("rank60") == 1 and (ins.get("n_days60") or 0) >= 10 and tops:
        parts.append("過去2か月では最多の記録です。")
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

    # 出船可否の判定（crawler._sail_judge / _sea_grid_html と同じ閾値ベルト）
    wv, wd = inner.get("wave"), inner.get("wind_spd")
    if wv is not None and wd is not None:
        try:
            wv, wd = float(wv), float(wd)
            sev = max(0 if wd < 6 else 1 if wd < 8 else 2 if wd < 10 else 3,
                      0 if wv < 0.5 else 1 if wv < 1.0 else 2 if wv < 1.5 else 3)
            sents.append(["内海は出船に支障のない穏やかな海況でした。",
                          "内海はそよ風程度で、釣りに支障のない範囲でした。",
                          "内海は強風・高波で出船には注意が必要な水準でした。",
                          "内海は荒天で欠航が出やすい水準でした。"][sev])
        except (TypeError, ValueError):
            pass

    n_ships = ctx.get("n_ships", 0)
    n_cancel = ctx.get("n_cancellations", 0)
    if n_ships:
        sents.append(f"本日は<b>{n_ships}軒</b>の船宿から釣果の報告があり、欠航の記録は{n_cancel}件でした。")

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

# ── 環境条件と傾向の照合（考察）────────────────────────────────────────
# ユーザー指摘（2026-07-22）「ただ数字を書いているだけ。環境要因や考察はしないのか」への対応。
# 使えるのは (1) 当日の実測海況（weather CSV / Forecast API）
#            (2) 過去3年の同じ時期の海況の目安（insights.wx_baseline）
#            (3) 船宿×魚種で採用済みの海況因子（normalize/ship_analysis.json＝C層からの蒸留・
#                ドメインレビュー済み・危険因子は surface=false で除外済み）
# 3つを突き合わせて「本日の条件は、その船宿・魚種が数を伸ばしてきた向きか」を述べる。
# **相関であって因果ではない**ことを必ず明記する（#50 と同じ原則）。

# 当日の実測値と対応づけられる因子だけを扱う（黒潮 SLA や CHL は当日値を持っていないため除外）
_FACTOR_MEASURABLE = {
    "sst": "sst", "sst_avg": "sst", "temp_avg": "sst",
    "wave_height_avg": "wave_height", "wave_height_max": "wave_height",
    "wind_speed_avg": "wind_speed", "wind_speed_max": "wind_speed",
}
_TIDE_FACTOR = {
    "tide_grp_oshio": "大潮", "tide_grp_chusho": "中潮", "tide_grp_chowaka": ("長潮", "若潮"),
}
_METRIC_JP = {"sst": "水温", "wave_height": "波の高さ", "wind_speed": "風速"}
_METRIC_UNIT = {"sst": "℃", "wave_height": "m", "wind_speed": "m/s"}


def _side_of(area, ctx):
    """港名から内海/外海を判定（context_builder の集合を再利用）。"""
    try:
        from .context_builder import _INNER_PORTS
    except Exception:
        return "inner"
    return "inner" if area in _INNER_PORTS else "outer"


def build_conditions_note(ctx, root=None):
    """セクション2の末尾に置く『本日の条件と、これまでの傾向』。
    材料が無ければ空文字（無理に書かない）。"""
    root = root or _ROOT
    from .insights import wx_baseline, ship_fish_factors

    ins_all = (ctx.get("insights") or {}).get("fish") or {}
    season = ctx.get("season_label", "この時期")
    base = wx_baseline(ctx.get("date_iso", ""), root=root)
    if not base:
        return ""
    today = {"inner": ctx.get("inner_sea_data") or {}, "outer": ctx.get("outer_sea_data") or {}}
    # sea_data のキー名 → baseline のキー名
    _K = {"sst": "sst", "wave": "wave_height", "wind_spd": "wind_speed"}

    def _dev(side, metric):
        """(当日値, 平年値, 差) を返す。片方でも欠ければ None。"""
        b = (base.get(side) or {}).get(metric)
        tkey = next((k for k, v in _K.items() if v == metric), None)
        t = (today.get(side) or {}).get(tkey)
        if b is None or t is None:
            return None
        try:
            return float(t), float(b), float(t) - float(b)
        except (TypeError, ValueError):
            return None

    paras = []

    # (1) 本日の海況は、この時期として高いか低いか
    bits = []
    for side, label in (("inner", "東京湾・相模湾"), ("outer", "外房〜銚子・伊豆方面")):
        d = _dev(side, "sst")
        if not d:
            continue
        t, b, diff = d
        if abs(diff) < 0.5:
            bits.append(f"{label}の水温{t:.1f}℃は{season}の平年（{b:.1f}℃前後）とほぼ同じ")
        else:
            updown = "高め" if diff > 0 else "低め"
            bits.append(f"{label}の水温{t:.1f}℃は{season}の平年（{b:.1f}℃前後）より{abs(diff):.1f}℃{updown}")
    dwave = _dev("inner", "wave_height")
    if dwave and abs(dwave[2]) >= 0.3:
        t, b, diff = dwave
        bits.append(f"内海の波{t:.1f}mも平年（{b:.1f}m前後）より{'高め' if diff > 0 else '低め'}")
    if bits:
        paras.append("、".join(bits) + "。")

    # (2) 注目魚種について、これまでの傾向と本日の条件を突き合わせる
    focus = []
    cnt_fish = ctx.get("top_cnt_fish", "")
    if cnt_fish:
        focus.append(cnt_fish)
    for f, i in sorted(ins_all.items(), key=lambda x: -(x[1].get("ratio") or 0)):
        if f not in focus and _has_norm(i) and (i.get("n_trips") or 0) >= 2 and not _is_flat(i["ratio"]):
            focus.append(f)
        if len(focus) >= 3:
            break

    notes = []
    for fish in focus[:3]:
        ins = ins_all.get(fish) or {}
        tops = [t for t in (ins.get("top_trips") or []) if t.get("cnt")]
        if not tops:
            continue
        ship, area = tops[0]["ship"], tops[0].get("area", "")
        info = ship_fish_factors(ship, fish, root=root) or {}
        factors = info.get("factors") or []
        if not factors:
            continue
        side = _side_of(area, ctx)
        for fac in factors:
            base_name = fac.get("base", "")
            direction = fac.get("direction", "")  # 「多い」「少ない」
            label = fac.get("label", "")
            metric = _FACTOR_MEASURABLE.get(base_name)
            if metric:
                d = _dev(side, metric)
                if not d:
                    continue
                t, b, diff = d
                if abs(diff) < (0.5 if metric == "sst" else 0.3):
                    state = f"平年並み（{t:.1f}{_METRIC_UNIT[metric]}）"
                    match = None
                else:
                    state = (f"平年より{abs(diff):.1f}{_METRIC_UNIT[metric]}"
                             f"{'高め' if diff > 0 else '低め'}（{t:.1f}{_METRIC_UNIT[metric]}）")
                    high = diff > 0
                    match = (high and direction == "多い") or ((not high) and direction == "少ない")
                s = (f"<b>{ship}</b>の{fish}は、過去{info.get('n_records', 0)}件の記録では"
                     f"{label}が高い日に釣果が<b>{direction}</b>傾向がありました。"
                     f"本日の{_METRIC_JP[metric]}は{state}")
                if match is True:
                    s += "で、数が伸びてきた向きと一致します。"
                elif match is False:
                    s += "で、数が伸びてきた向きとは逆でした。"
                else:
                    s += "でした。"
                notes.append(s)
                break
            tide_want = _TIDE_FACTOR.get(base_name)
            if tide_want:
                tide_now = ctx.get("tide_type", "")
                want = tide_want if isinstance(tide_want, tuple) else (tide_want,)
                s = (f"<b>{ship}</b>の{fish}は、過去{info.get('n_records', 0)}件の記録では"
                     f"{label}に釣果が<b>{direction}</b>傾向がありました。"
                     f"本日の潮は{tide_now}")
                s += "で、その条件に当たります。" if tide_now in want else "でした。"
                notes.append(s)
                break
        if len(notes) >= 2:
            break

    if notes:
        paras.extend(notes)
        paras.append("いずれも過去データ上の相関で、釣果の原因を特定したものではありません。"
                     "海況以外の要因（船長の判断・ポイント選択・仕掛け）も結果を左右します。")

    if not paras:
        return ""
    return ('<div class="commentary evidence"><h3 class="note-h">本日の条件と、これまでの傾向</h3>'
            + "".join(f"<p>{p}</p>" for p in paras) + "</div>")

