#!/usr/bin/env python3
"""
釣果×気象 相関分析スクリプト  analysis/analyze.py

[入力]
  analysis/master_dataset.csv

[出力]
  analysis/report.html  — 魚種別・気象条件別の釣果傾向レポート
"""

import csv, os, sys, math
from collections import defaultdict

sys.stdout.reconfigure(encoding="utf-8")

BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
INPUT_FILE = os.path.join(BASE_DIR, "master_dataset.csv")
OUTPUT_HTML = os.path.join(BASE_DIR, "report.html")

# 分析対象魚種（件数が多い順）
TARGET_FISH = [
    "アジ", "マダイ", "イサキ", "ヒラメ", "タチウオ",
    "シロギス", "アマダイ", "フグ", "スルメイカ", "カサゴ",
    "マルイカ", "クロダイ", "サバ", "メバル", "カレイ",
]

# ── ユーティリティ ─────────────────────────────────────────────────

def safe_float(v):
    try: return float(v) if v not in ("", None) else None
    except: return None

def safe_int(v):
    try: return int(v) if v not in ("", None) else None
    except: return None

def avg(lst):
    lst = [x for x in lst if x is not None]
    return round(sum(lst) / len(lst), 1) if lst else None

def median(lst):
    lst = sorted(x for x in lst if x is not None)
    n = len(lst)
    if not n: return None
    return round(lst[n // 2], 1)

# ── データ読み込み ─────────────────────────────────────────────────

def load():
    rows = []
    with open(INPUT_FILE, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            cnt = safe_float(r.get("cnt_max") or r.get("cnt_avg"))
            if cnt is None or cnt == 0:
                continue
            if safe_int(r.get("is_boat")) == 1:  # 船全体釣果は除外
                continue
            rows.append({
                "fish":       r["fish"],
                "cnt":        cnt,
                "wave":       safe_float(r.get("wave_height")),
                "wind":       safe_float(r.get("wind_speed")),
                "tide_type":  r.get("tide_type", ""),
                "moon_age":   safe_float(r.get("moon_age")),
                "sst":        safe_float(r.get("sea_surface_temp")),
                "tide_range": safe_float(r.get("tide_range")),
                "date":       r.get("date", ""),
            })
    return rows

# ── 区間集計 ──────────────────────────────────────────────────────

def bucket_wave(wave):
    if wave is None: return None
    if wave < 0.5:   return "凪（〜0.5m）"
    if wave < 1.0:   return "波穏（0.5〜1m）"
    if wave < 1.5:   return "波普通（1〜1.5m）"
    if wave < 2.5:   return "やや荒（1.5〜2.5m）"
    return "荒れ（2.5m〜）"

WAVE_ORDER = ["凪（〜0.5m）", "波穏（0.5〜1m）", "波普通（1〜1.5m）", "やや荒（1.5〜2.5m）", "荒れ（2.5m〜）"]

def bucket_wind(wind):
    if wind is None: return None
    if wind < 3:  return "微風（〜3m/s）"
    if wind < 6:  return "弱風（3〜6m/s）"
    if wind < 10: return "中風（6〜10m/s）"
    return "強風（10m/s〜）"

WIND_ORDER = ["微風（〜3m/s）", "弱風（3〜6m/s）", "中風（6〜10m/s）", "強風（10m/s〜）"]

TIDE_ORDER = ["大潮", "中潮", "小潮", "長潮", "若潮"]

def group_by(rows, key_fn):
    """key_fn(row) → key でグループ化。key=None はスキップ。"""
    groups = defaultdict(list)
    for r in rows:
        k = key_fn(r)
        if k is not None:
            groups[k].append(r["cnt"])
    return groups

def summarize_group(groups, order):
    result = []
    for label in order:
        cnts = groups.get(label, [])
        if len(cnts) < 3:
            continue
        result.append({
            "label": label,
            "n":     len(cnts),
            "avg":   avg(cnts),
            "med":   median(cnts),
            "max":   max(cnts),
        })
    return result

# ── 相関係数 ──────────────────────────────────────────────────────

def pearson(rows, x_key, y_key="cnt"):
    pairs = [(r[x_key], r[y_key]) for r in rows if r[x_key] is not None and r[y_key] is not None]
    n = len(pairs)
    if n < 10:
        return None
    xs = [p[0] for p in pairs]
    ys = [p[1] for p in pairs]
    mx, my = sum(xs)/n, sum(ys)/n
    num = sum((x-mx)*(y-my) for x,y in pairs)
    dx  = math.sqrt(sum((x-mx)**2 for x in xs))
    dy  = math.sqrt(sum((y-my)**2 for y in ys))
    if dx == 0 or dy == 0:
        return None
    return round(num / (dx * dy), 3)

# ── HTML生成 ─────────────────────────────────────────────────────

CSS = """
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Helvetica Neue',Arial,sans-serif;background:#0a1628;color:#e0e8f0;padding:20px}
h1{font-size:22px;color:#4db8ff;margin-bottom:6px}
.subtitle{color:#7a9bb5;font-size:13px;margin-bottom:30px}
h2{font-size:16px;color:#4db8ff;border-left:4px solid #4db8ff;padding-left:10px;margin:32px 0 12px}
h3{font-size:13px;color:#7a9bb5;margin:16px 0 6px}
.fish-section{background:#0d2137;border:1px solid #1a4060;border-radius:8px;padding:16px 20px;margin-bottom:24px}
.fish-title{font-size:18px;color:#e0e8f0;font-weight:bold;margin-bottom:4px}
.fish-meta{font-size:12px;color:#7a9bb5;margin-bottom:14px}
.corr-badges{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:14px}
.badge{padding:5px 10px;border-radius:12px;font-size:12px;border:1px solid}
.badge-neg{background:#1a0a10;border-color:#cc4d4d;color:#ff8080}
.badge-neu{background:#0d1a2d;border-color:#4a6a8a;color:#7a9bb5}
.badge-pos{background:#0a1a10;border-color:#4dcc88;color:#4dcc88}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:16px}
table{width:100%;border-collapse:collapse;font-size:13px}
th{background:#081020;color:#4db8ff;padding:7px 10px;text-align:left;font-weight:normal}
td{padding:7px 10px;border-bottom:1px solid #0d1a2d}
.bar-cell{width:120px}
.bar-wrap{background:#081020;border-radius:2px;height:8px}
.bar-fill{background:#1a6ea8;height:8px;border-radius:2px}
.best{color:#4dcc88;font-weight:bold}
footer{margin-top:40px;font-size:11px;color:#4a6a8a;text-align:center}
"""

def corr_badge(label, r):
    if r is None:
        return f'<span class="badge badge-neu">{label}: -</span>'
    if r <= -0.15:
        cls = "badge-neg"
        sign = f"r={r}"
    elif r >= 0.15:
        cls = "badge-pos"
        sign = f"r=+{r}"
    else:
        cls = "badge-neu"
        sign = f"r={r}"
    return f'<span class="badge {cls}">{label}: {sign}</span>'

def table_html(rows_data, best_avg):
    if not rows_data:
        return "<p style='color:#4a6a8a;font-size:12px'>データ不足</p>"
    max_avg = max(r["avg"] for r in rows_data if r["avg"])
    html = "<table><tr><th>条件</th><th>件数</th><th>平均</th><th>中央値</th><th>最高</th><th class='bar-cell'></th></tr>"
    for r in rows_data:
        pct = int(r["avg"] / max_avg * 100) if max_avg and r["avg"] else 0
        best_cls = ' class="best"' if r["label"] == best_avg else ""
        html += (
            f"<tr{best_cls}>"
            f"<td>{r['label']}</td>"
            f"<td style='color:#7a9bb5'>{r['n']}</td>"
            f"<td>{r['avg'] or '-'}</td>"
            f"<td style='color:#7a9bb5'>{r['med'] or '-'}</td>"
            f"<td style='color:#e85d04'>{int(r['max'])}</td>"
            f"<td class='bar-cell'><div class='bar-wrap'><div class='bar-fill' style='width:{pct}%'></div></div></td>"
            f"</tr>"
        )
    return html + "</table>"

def best_label(rows_data):
    if not rows_data: return None
    return max(rows_data, key=lambda r: r["avg"] or 0)["label"]

def build_html(fish_results, generated_at):
    sections = ""
    for fish, res in fish_results:
        n_total = res["n_total"]
        if n_total < 20:
            continue

        # 相関バッジ
        badges = (
            corr_badge("波高", res["corr_wave"]) +
            corr_badge("風速", res["corr_wind"]) +
            corr_badge("月齢", res["corr_moon"]) +
            corr_badge("潮位差", res["corr_tide_range"])
        )

        best_wave = best_label(res["wave"])
        best_wind = best_label(res["wind"])
        best_tide = best_label(res["tide"])

        sections += f"""
<div class="fish-section">
  <div class="fish-title">🐟 {fish}</div>
  <div class="fish-meta">分析件数: {n_total}件  /  平均釣果: {res['cnt_avg']}匹  /  最高: {res['cnt_max']}匹</div>
  <div class="corr-badges">{badges}</div>
  <div class="grid">
    <div>
      <h3>🌊 波高別（最良: {best_wave or '-'}）</h3>
      {table_html(res['wave'], best_wave)}
    </div>
    <div>
      <h3>💨 風速別（最良: {best_wind or '-'}）</h3>
      {table_html(res['wind'], best_wind)}
    </div>
    <div>
      <h3>🌙 潮汐区分別（最良: {best_tide or '-'}）</h3>
      {table_html(res['tide'], best_tide)}
    </div>
  </div>
</div>"""

    return f"""<!DOCTYPE html>
<html lang="ja"><head>
  <meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
  <title>釣果×気象 相関分析レポート | 船釣り予想</title>
  <style>{CSS}</style>
</head><body>
<h1>📊 釣果×気象 相関分析レポート</h1>
<div class="subtitle">生成: {generated_at}  /  data/YYYY-MM.csv + weather_data/*_history.csv</div>
{sections}
<footer>分析対象: cnt_max (is_boat=0 のみ) / 相関係数はPearson r / 件数&lt;3の区間は非表示</footer>
</body></html>"""

# ── メイン ────────────────────────────────────────────────────────

def main():
    from datetime import datetime
    print("=== analyze.py ===")
    all_rows = load()
    print(f"有効行: {len(all_rows)}件")

    fish_results = []

    for fish in TARGET_FISH:
        rows = [r for r in all_rows if r["fish"] == fish]
        if len(rows) < 20:
            continue

        wave_groups = group_by(rows, lambda r: bucket_wave(r["wave"]))
        wind_groups = group_by(rows, lambda r: bucket_wind(r["wind"]))
        tide_groups = group_by(rows, lambda r: r["tide_type"] if r["tide_type"] in TIDE_ORDER else None)

        cnts = [r["cnt"] for r in rows]
        res = {
            "n_total":        len(rows),
            "cnt_avg":        avg(cnts),
            "cnt_max":        int(max(cnts)),
            "corr_wave":      pearson(rows, "wave"),
            "corr_wind":      pearson(rows, "wind"),
            "corr_moon":      pearson(rows, "moon_age"),
            "corr_tide_range":pearson(rows, "tide_range"),
            "wave":           summarize_group(wave_groups, WAVE_ORDER),
            "wind":           summarize_group(wind_groups, WIND_ORDER),
            "tide":           summarize_group(tide_groups, TIDE_ORDER),
        }
        fish_results.append((fish, res))
        print(f"  {fish}: {len(rows)}件  波高r={res['corr_wave']}  風速r={res['corr_wind']}")

    generated_at = datetime.now().strftime("%Y/%m/%d %H:%M")
    html = build_html(fish_results, generated_at)
    with open(OUTPUT_HTML, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"\n出力: {OUTPUT_HTML}")


if __name__ == "__main__":
    main()
