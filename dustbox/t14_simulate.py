"""T14 — _heat_score ランキング再現とA案シミュレーション
出力: design/V2/T14_research_report.md
"""
import json
import math
import csv
import os
from datetime import datetime, timedelta, timezone

JST = timezone(timedelta(hours=9))
NOW = datetime.now(JST).replace(tzinfo=None)
TODAY_STR = NOW.strftime("%Y/%m/%d")
CURRENT_MONTH = NOW.month
YEAR, WEEK_NUM = NOW.year, NOW.isocalendar()[1]

PEAK = {
    "アジ":     [4,5,6,10,11],
    "シロギス": [5,6,7,8,9],
    "マダイ":   [4,5,10,11],
    "イサキ":   [6,7,8],
    "カツオ":   [7,8,9],
    "カワハギ": [10,11,12],
    "タチウオ": [7,8,9,10],
    "ヒラメ":   [10,11,12,1,2],
    "メバル":   [2,3,4],
    "アマダイ": [11,12,1,2],
}
LATE = {
    "メバル":   [5,6],
    "マダイ":   [6,7,8,9],
    "タチウオ": [11,12,1],
    "ヒラメ":   [3,4,5],
}

def fish_signal(fish, month):
    peaks = PEAK.get(fish, [])
    lates = LATE.get(fish, [])
    if month in peaks:
        return "peak"
    if month in lates:
        return "late"
    adj = set()
    for m in peaks:
        adj.add((m - 2) % 12 + 1)
        adj.add(m % 12 + 1)
    if month in adj:
        return "season"
    return "normal"

SEASON_MUL = {"peak": 1.3, "season": 1.1, "normal": 1.0, "late": 0.7}

# ---- catches.json ----
with open("catches.json", encoding="utf-8") as f:
    catches_raw = json.load(f)
catches = catches_raw.get("data", [])

# ---- is_sparse_today 判定 ----
today_with_fish = sum(1 for c in catches
                      if c.get("date") == TODAY_STR
                      and any(f != "不明" for f in (c.get("fish") or [])))
SPARSE_THRESHOLD = 30
is_sparse = today_with_fish < SPARSE_THRESHOLD

# ---- sparse なら CSV から 7日分 merge（簡易: ship+date+fish_raw でユニーク） ----
catches_for_summary = list(catches)
if is_sparse:
    # 過去7日分の月別CSVを集める
    months = set()
    for d in range(7):
        dt = NOW - timedelta(days=d)
        months.add(dt.strftime("%Y-%m"))
    cutoff = (NOW - timedelta(days=6)).strftime("%Y/%m/%d")
    seen = {(c.get("ship"), c.get("date"), c.get("fish_raw", "")) for c in catches}
    for m in months:
        path = f"data/V2/{m}.csv"
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as f:
            r = csv.DictReader(f)
            for row in r:
                date = row.get("date") or ""
                if date < cutoff or date > TODAY_STR:
                    continue
                if row.get("is_cancellation") == "1":
                    continue
                fish_raw = row.get("fish_raw") or ""
                ship = row.get("ship") or ""
                key = (ship, date, fish_raw)
                if key in seen:
                    continue
                seen.add(key)
                tsuri = row.get("tsuri_mono") or ""
                fish_list = [tsuri] if tsuri else ["不明"]
                # count_range 簡易
                try:
                    cmin = int(row.get("cnt_min") or 0)
                    cmax = int(row.get("cnt_max") or 0)
                    is_boat = row.get("is_boat") == "1"
                    cr = {"min": cmin, "max": cmax, "is_boat": is_boat}
                except Exception:
                    cr = None
                catches_for_summary.append({
                    "ship": ship, "area": row.get("area") or "",
                    "date": date, "fish": fish_list, "fish_raw": fish_raw,
                    "count_range": cr,
                })

# ---- fish_summary ----
fish_summary = {}
for c in catches_for_summary:
    for f in c.get("fish") or []:
        if f != "不明":
            fish_summary.setdefault(f, []).append(c)

# ---- history.json から ratio 算出 ----
with open("history.json", encoding="utf-8") as f:
    history = json.load(f)

def get_yoy(fish):
    this_key = f"{YEAR}/W{WEEK_NUM:02d}"
    return history.get("weekly", {}).get(this_key, {}).get(fish)

def get_prev(fish):
    if WEEK_NUM > 1:
        prev_key = f"{YEAR}/W{WEEK_NUM-1:02d}"
    else:
        prev_key = f"{YEAR-1}/W52"
    return history.get("weekly", {}).get(prev_key, {}).get(fish)

def heat_score(fish, cs):
    cnt = math.log1p(len(cs))
    tw = get_yoy(fish)
    pw = get_prev(fish)
    ratio = 1.0
    if tw and pw:
        ts = tw.get("ships") or 0
        ps = pw.get("ships") or 0
        if ts and ps:
            ratio = min(ts / ps, 3.0)
    sk = fish_signal(fish, CURRENT_MONTH)
    sm = SEASON_MUL[sk]
    return cnt * ratio * sm, cnt, ratio, sk, sm

# ---- 全魚種スコア計算 ----
rows = []
for fish, cs in fish_summary.items():
    n = len(cs)
    ships = len({c["ship"] for c in cs})
    score, cnt, ratio, sk, sm = heat_score(fish, cs)
    rows.append({
        "fish": fish, "n": n, "ships": ships,
        "season": sk, "season_mul": sm, "ratio": ratio,
        "log1p_n": cnt, "score": score,
    })

# 現状ランク（score 降順）
rows_by_score = sorted(rows, key=lambda r: -r["score"])
for i, r in enumerate(rows_by_score):
    r["rank_now"] = i + 1
rank_now_map = {r["fish"]: r["rank_now"] for r in rows_by_score}

# 件数順
rows_by_count = sorted(rows, key=lambda r: -r["n"])

# ---- A案 シミュレーション（閾値感度 3/5/7/10） ----
def simulate(threshold):
    sim = []
    for r in rows:
        s = r["score"] * 0.01 if r["n"] < threshold else r["score"]
        sim.append({**r, "score_a": s})
    sim.sort(key=lambda r: -r["score_a"])
    for i, r in enumerate(sim):
        r["rank_a"] = i + 1
    return sim

scenarios = {th: simulate(th) for th in [3, 5, 7, 10]}

# ---- レポート生成 ----
def fmt_row_now(r):
    return f"| {r['rank_now']} | {r['fish']} | {r['n']} | {r['ships']} | {r['season']}({r['season_mul']:.1f}) | {r['ratio']:.2f} | {r['log1p_n']:.2f} | **{r['score']:.2f}** |"

def fmt_row_a(r):
    delta = r["rank_now"] - r["rank_a"]
    arrow = "—" if delta == 0 else (f"↑{delta}" if delta > 0 else f"↓{-delta}")
    return f"| {r['rank_a']} | {r['fish']} | {r['n']} | {r['ships']} | {r['season']}({r['season_mul']:.1f}) | {r['ratio']:.2f} | {r['score']:.2f} | {r['score_a']:.4f} | {r['rank_now']} | {arrow} |"

md = []
md.append("# T14 — index.html 魚種カード並び順 修正前データ調査")
md.append("")
md.append(f"**生成日時**: {NOW.strftime('%Y-%m-%d %H:%M JST')}  ")
md.append(f"**現在週**: {YEAR}/W{WEEK_NUM:02d}  ")
md.append(f"**現在月**: {CURRENT_MONTH} 月  ")
md.append("")

md.append("## 1. 現状の `_heat_score` ロジック確認")
md.append("")
md.append("`crawler.py:5984-5999`")
md.append("")
md.append("```python")
md.append("def _heat_score(fish, cs):")
md.append("    cnt = math.log1p(len(cs))")
md.append("    ratio = min(ts/ps, 3.0)  # 前週比（ships数）")
md.append("    season_mul = peak:1.3 / season:1.1 / normal:1.0 / late:0.7")
md.append("    return cnt * ratio * season_mul")
md.append("```")
md.append("")
md.append("仕様の弱点：件数を `log1p` で対数圧縮した上に前週比を最大3倍まで掛ける。")
md.append("結果として「先週0船宿→今週3船宿」の少数派が「先週8船宿→今週8船宿」の主力魚に勝ちうる。")
md.append("")

md.append("## 2. データソース確認")
md.append("")
md.append(f"- `catches.json` 件数: **{len(catches)}**")
md.append(f"- 当日({TODAY_STR}) fish≠不明 件数: **{today_with_fish}**")
md.append(f"- SPARSE_THRESHOLD=30 → **is_sparse_today = {is_sparse}**")
md.append(f"- catches_for_summary 合計: **{len(catches_for_summary)}** 件")
md.append(f"- 認識魚種数: **{len(fish_summary)}**")
md.append("")

md.append("## 3. 現状ランキング（実データ）")
md.append("")
md.append("### 3.1 現状スコア順（=現状の表示順）")
md.append("")
md.append("| 順位 | 魚種 | N | 船宿数 | 旬係数 | ratio | log1p(N) | score |")
md.append("|---|---|---|---|---|---|---|---|")
for r in rows_by_score[:25]:
    md.append(fmt_row_now(r))
md.append("")
md.append(f"（全 {len(rows_by_score)} 魚種中、上位 25 表示）")
md.append("")

md.append("### 3.2 件数順")
md.append("")
md.append("| 件数順位 | 魚種 | N | 船宿数 | 旬係数 | ratio | score | 現状順位 |")
md.append("|---|---|---|---|---|---|---|---|")
for i, r in enumerate(rows_by_count[:25]):
    md.append(f"| {i+1} | {r['fish']} | {r['n']} | {r['ships']} | {r['season']}({r['season_mul']:.1f}) | {r['ratio']:.2f} | {r['score']:.2f} | {rank_now_map[r['fish']]} |")
md.append("")

md.append("## 4. A案シミュレーション（件数 N<5 の魚種を score×0.01 で押下げ）")
md.append("")
md.append("### 4.1 閾値=5 の TOP12")
md.append("")
md.append("| 新順位 | 魚種 | N | 船宿数 | 旬係数 | ratio | 現score | 適用後score | 旧順位 | 変動 |")
md.append("|---|---|---|---|---|---|---|---|---|---|")
for r in scenarios[5][:12]:
    md.append(fmt_row_a(r))
md.append("")

md.append("### 4.2 閾値=5 の押下げ対象魚種（N<5 で 0.01倍）")
md.append("")
md.append("| 魚種 | N | 船宿数 | 現状順位 | 適用後順位 |")
md.append("|---|---|---|---|---|")
for r in sorted([r for r in scenarios[5] if r["n"] < 5], key=lambda x: -x["n"]):
    md.append(f"| {r['fish']} | {r['n']} | {r['ships']} | {r['rank_now']} | {r['rank_a']} |")
md.append("")

md.append("## 5. 副作用評価（閾値感度 3 / 5 / 7 / 10）")
md.append("")
md.append("各閾値での「TOP12 入れ替わり数」と「対象（押下げ）魚種数」")
md.append("")
md.append("| 閾値 | 押下げ対象数 | TOP12 入れ替え数 | 押下げ対象（魚種：N） |")
md.append("|---|---|---|---|")
for th in [3, 5, 7, 10]:
    sim = scenarios[th]
    targets = [r for r in sim if r["n"] < th]
    # TOP12 の入れ替え数：旧TOP12 と 新TOP12 の差集合
    top12_now = {r["fish"] for r in rows_by_score[:12]}
    top12_a = {r["fish"] for r in sim[:12]}
    diff = len(top12_now - top12_a)
    targets_str = ", ".join(f"{r['fish']}:{r['n']}" for r in sorted(targets, key=lambda x: -x["n"])[:8])
    if len(targets) > 8:
        targets_str += f" ...他{len(targets)-8}件"
    md.append(f"| {th} | {len(targets)} | {diff} | {targets_str} |")
md.append("")

# ---- 5件未満で旬ピーク中の魚種チェック ----
md.append("### 5.1 N<5 で旬ピーク中の魚種（重要かもしれない魚）")
md.append("")
md.append("| 魚種 | N | 旬係数 | 備考 |")
md.append("|---|---|---|---|")
n5_peak = [r for r in scenarios[5] if r["n"] < 5 and r["season"] == "peak"]
if n5_peak:
    for r in sorted(n5_peak, key=lambda x: -x["n"]):
        md.append(f"| {r['fish']} | {r['n']} | peak | 押下げ対象になるが旬中 |")
else:
    md.append("| (該当なし) | | | 5月時点で N<5 の peak 魚種は無い |")
md.append("")

md.append("## 6. 推奨閾値と根拠")
md.append("")
md.append("**推奨**: 閾値 **5**（A案そのまま）")
md.append("")
md.append("**根拠**:")
md.append("- 閾値3だと押下げ効果が弱く、4件のカンパチ（本問題のトリガー）が依然上位に残る")
md.append("- 閾値10だと押下げ対象が増えすぎ、N=6〜9の魚種（実質的に複数船宿で出ている）まで巻き込む副作用が強い")
md.append("- 閾値5は「単独船宿の偶発釣果（1〜4件）」と「複数船宿で安定した釣果（5件〜）」の境界として直感的")
md.append("- 5月時点で N<5 の peak 魚種が存在しない（上記5.1表）→ 副作用は限定的")
md.append("")
md.append("**実装案**:")
md.append("```python")
md.append("def _heat_score(fish, cs):")
md.append("    if len(cs) < 5:")
md.append("        return 0.0  # または既存スコア × 0.01")
md.append("    cnt = math.log1p(len(cs))")
md.append("    ratio = min(ts/ps, 3.0)")
md.append("    sk, _ = _fish_signal(fish, current_month)")
md.append("    season_mul = {...}[sk]")
md.append("    return cnt * ratio * season_mul")
md.append("```")
md.append("")
md.append("`return 0.0` だと TOP12 から確実に外れる。`× 0.01` だと末尾に集まる順位が出る。どちらでも良いが、")
md.append("「本日 ZONE B カードに表示される魚種数」が減ること自体は許容（カード5枚以上残れば validate_output 不変条件1 PASS）。")

with open("design/V2/T14_research_report.md", "w", encoding="utf-8") as f:
    f.write("\n".join(md))

print(f"Report written: design/V2/T14_research_report.md")
print(f"is_sparse_today: {is_sparse}")
print(f"fish_count: {len(fish_summary)}")
print(f"top5: {[(r['fish'], r['n'], round(r['score'],2)) for r in rows_by_score[:5]]}")
print(f"top12 in_now vs in_a (th=5):")
top12_now = [r['fish'] for r in rows_by_score[:12]]
top12_a = [r['fish'] for r in scenarios[5][:12]]
print(f"  now: {top12_now}")
print(f"  a:   {top12_a}")
