# insights.py — 日次まとめの「比較軸」を data/V2/*.csv から算出する（2026-07-22 新設）
#
# 背景:
#   x_post 日次ページのハイライト／魚種別報告が「推測フィラー文」に依存して薄かった
#   （例:「今期は好海況が観測されています」「ローテーション釣行に組み込みやすい魚種です」）。
#   ユーザー裁定 = 推測文は全廃し、必ず数値根拠を伴う文だけを出す。
#   そのための根拠データをここで作る。
#
# 設計方針:
#   - 参照するのは **コミット済みの data/V2/*.csv のみ**（analysis.sqlite は .gitignore で CI に無い）。
#   - 「当日値」は catches（ctx 側）から渡してもらい、ここでは **過去（当日より前）だけ** を集計する。
#     → CSV への当日行の反映タイミング（crawler の書込順）に依存しない。
#   - 個人釣果のみ（is_boat=1 の船中合計は数の水準が別物なので除外）。
#   - 平年 = 過去の「同じ旬（10日区切り）」の cnt_max 中央値。補遺3 に従い avg は使わない。
#
# 出力（build_insights の戻り値）:
#   {
#     "fish": {魚種: {
#        "norm_cnt": float|None,     # 平年値（同旬 cnt_max 中央値・過去のみ）
#        "norm_n": int,              # 平年値の母数（便数）
#        "today_cnt": float|None,    # 当日の cnt_max 中央値
#        "ratio": float|None,        # today/norm
#        "ratio_str": str,           # "+38%" / "-12%"
#        "norm_cm": float|None, "today_cm": float|None, "cm_ratio": float|None,
#        "norm_kg": float|None, "today_kg": float|None, "kg_ratio": float|None,
#        "days_since_last": int|None,# 前回この魚種が記録された日からの日数
#        "rank60": int|None,         # 直近60日の日別最大値の中での当日順位（1=最多）
#        "n_days60": int,            # 直近60日で記録があった日数
#        "top_trips": [{"ship","area","cnt"}],  # 当日の上位3便
#        "n_trips": int,
#     }},
#     "asof": "YYYY-MM-DD",
#   }
import csv
import datetime as _dt
import os

_THIS = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_THIS)

# 平年値を出すのに最低限必要な過去便数。これ未満は「平年比」を出さない（薄い母数で断定しない）
_MIN_NORM_N = 8
# 平年値の探索期間（年）
_LOOKBACK_YEARS = 3

_cache = {}


def _decade_no(dt):
    """旬番号 1..36（10日区切り・月末は第3旬に寄せる）"""
    d = min(dt.day, 30)
    return (dt.month - 1) * 3 + min((d - 1) // 10, 2) + 1


def _median(vals):
    v = sorted(vals)
    n = len(v)
    if not n:
        return None
    m = n // 2
    return float(v[m]) if n % 2 else (v[m - 1] + v[m]) / 2.0


def _fnum(s):
    try:
        f = float(s)
        return f if f > 0 else None
    except (TypeError, ValueError):
        return None


def _load_rows(root, since_iso):
    """data/V2/*.csv から個人釣果行を読む。戻り値: [(date_iso, fish, cnt_max, cm_max, kg_max)]"""
    key = (root, since_iso)
    if key in _cache:
        return _cache[key]
    data_dir = os.path.join(root, "data", "V2")
    out = []
    if not os.path.isdir(data_dir):
        _cache[key] = out
        return out
    for fn in sorted(os.listdir(data_dir)):
        if not fn.endswith(".csv") or fn == "cancellations.csv":
            continue
        path = os.path.join(data_dir, fn)
        try:
            with open(path, encoding="utf-8", newline="") as f:
                for r in csv.DictReader(f):
                    if r.get("is_cancellation") == "1":
                        continue
                    if r.get("is_boat") == "1":
                        continue
                    fish = (r.get("tsuri_mono") or "").strip()
                    if not fish or fish in ("NULL", "不明", ""):
                        continue
                    d = (r.get("date") or "").replace("/", "-")
                    if len(d) != 10 or d < since_iso:
                        continue
                    out.append((d, fish,
                                _fnum(r.get("cnt_max")),
                                _fnum(r.get("size_max")),
                                _fnum(r.get("kg_max"))))
        except Exception:
            continue
    _cache[key] = out
    return out


def build_insights(date_iso, today_fish, root=None):
    """
    date_iso: "YYYY-MM-DD"（対象日）
    today_fish: {魚種: [{"ship","area","cnt_max","cm_max","kg_max"}, ...]}（当日の便リスト）
    """
    root = root or _ROOT
    try:
        dt = _dt.datetime.strptime(date_iso, "%Y-%m-%d")
    except ValueError:
        return {"fish": {}, "asof": date_iso}

    since = (dt - _dt.timedelta(days=365 * _LOOKBACK_YEARS + 10)).strftime("%Y-%m-%d")
    rows = _load_rows(root, since)
    target_dec = _decade_no(dt)
    d60 = (dt - _dt.timedelta(days=60)).strftime("%Y-%m-%d")

    # 過去行を魚種別に分類（当日以降は除外＝未来リークと当日二重計上の防止）
    per_fish = {}
    for d, fish, cnt, cm, kg in rows:
        if d >= date_iso:
            continue
        per_fish.setdefault(fish, []).append((d, cnt, cm, kg))

    out = {}
    for fish, trips in (today_fish or {}).items():
        hist = per_fish.get(fish, [])
        # 同旬（過去）
        dec_cnt, dec_cm, dec_kg = [], [], []
        for d, cnt, cm, kg in hist:
            try:
                hd = _dt.datetime.strptime(d, "%Y-%m-%d")
            except ValueError:
                continue
            if _decade_no(hd) != target_dec:
                continue
            if cnt:
                dec_cnt.append(cnt)
            if cm:
                dec_cm.append(cm)
            if kg:
                dec_kg.append(kg)

        norm_cnt = _median(dec_cnt) if len(dec_cnt) >= _MIN_NORM_N else None
        norm_cm = _median(dec_cm) if len(dec_cm) >= _MIN_NORM_N else None
        norm_kg = _median(dec_kg) if len(dec_kg) >= _MIN_NORM_N else None

        today_cnts = [t["cnt_max"] for t in trips if t.get("cnt_max")]
        today_cms = [t["cm_max"] for t in trips if t.get("cm_max")]
        today_kgs = [t["kg_max"] for t in trips if t.get("kg_max")]
        today_cnt = _median(today_cnts)
        today_cm = _median(today_cms)
        today_kg = _median(today_kgs)

        ratio = round(today_cnt / norm_cnt, 2) if (norm_cnt and today_cnt) else None
        cm_ratio = round(today_cm / norm_cm, 2) if (norm_cm and today_cm) else None
        kg_ratio = round(today_kg / norm_kg, 2) if (norm_kg and today_kg) else None

        # 前回記録日からの間隔
        prev_dates = sorted({d for d, cnt, cm, kg in hist if (cnt or cm or kg)})
        days_since = None
        if prev_dates:
            try:
                days_since = (dt - _dt.datetime.strptime(prev_dates[-1], "%Y-%m-%d")).days
            except ValueError:
                days_since = None

        # 直近60日の日別ピークの中での当日順位
        day_peak = {}
        for d, cnt, cm, kg in hist:
            if d < d60 or not cnt:
                continue
            if cnt > day_peak.get(d, 0):
                day_peak[d] = cnt
        rank60 = None
        today_peak = max(today_cnts) if today_cnts else None
        if today_peak and day_peak:
            rank60 = 1 + sum(1 for v in day_peak.values() if v > today_peak)

        top_trips = sorted(
            [t for t in trips if t.get("cnt_max")],
            key=lambda t: t["cnt_max"], reverse=True)[:3]

        out[fish] = {
            "norm_cnt": norm_cnt, "norm_n": len(dec_cnt),
            "today_cnt": today_cnt, "ratio": ratio,
            "ratio_str": _pct_str(ratio),
            "norm_cm": norm_cm, "today_cm": today_cm, "cm_ratio": cm_ratio,
            "norm_kg": norm_kg, "today_kg": today_kg, "kg_ratio": kg_ratio,
            "days_since_last": days_since,
            "rank60": rank60, "n_days60": len(day_peak),
            "top_trips": [{"ship": t.get("ship", ""), "area": t.get("area", ""),
                           "cnt": t.get("cnt_max")} for t in top_trips],
            "n_trips": len(trips),
        }

    return {"fish": out, "asof": date_iso}


def _pct_str(ratio):
    if not ratio:
        return ""
    pct = int(round((ratio - 1) * 100))
    return f"+{pct}%" if pct >= 0 else f"{pct}%"


# ── 検証済み予測（forecast_daily.json × open_tier.json tier A）──────────────
# T47a/T47b で「サイトに出す予測は検証済みモデル × tier A のみ」と確定済み（不変条件 #53）。
# 日次まとめでも同じ関門を通したものだけを引用する。
def load_verified_forecast(date_iso, fish_names, root=None, horizon_days=(1, 2)):
    """翌日以降の検証済み予測レンジを返す（tier A かつレンジ有りのみ）。

    forecast_daily.json のスキーマ（実測・2026-07-22 確認）:
      {"mode": "distilled_full", "days": [
         {"target_date": "YYYY/MM/DD", "horizon": 1,
          "combos": [{"fish","ship","cnt_lo","cnt_hi","tier","stars","range_quality":{...}}]}]}
    tier は combos 各行に入っているので open_tier.json の再読込は不要（同じ蒸留元）。

    戻り値: [{"date_label","fish","ship","lo","hi","pb"}]
    """
    root = root or _ROOT
    import json
    fpath = os.path.join(root, "analysis", "V2", "results", "forecast_daily.json")
    try:
        with open(fpath, encoding="utf-8") as f:
            fc = json.load(f)
    except Exception:
        return []
    if fc.get("mode") not in ("available", "distilled_full"):
        return []

    try:
        base = _dt.datetime.strptime(date_iso, "%Y-%m-%d")
    except ValueError:
        return []
    want = {}
    wd = ["月", "火", "水", "木", "金", "土", "日"]
    for h in horizon_days:
        d = base + _dt.timedelta(days=h)
        want[d.strftime("%Y/%m/%d")] = f"{d.month}/{d.day}({wd[d.weekday()]})"

    rows = []
    for day in (fc.get("days") or []):
        label = want.get(day.get("target_date"))
        if not label:
            continue
        for e in (day.get("combos") or []):
            if e.get("tier") != "A":
                continue
            lo, hi = e.get("cnt_lo"), e.get("cnt_hi")
            if lo is None or hi is None:
                continue
            if fish_names and e.get("fish") not in fish_names:
                continue
            rows.append({"date_label": label, "fish": e.get("fish"), "ship": e.get("ship"),
                         "lo": lo, "hi": hi,
                         "pb": (e.get("range_quality") or {}).get("promise_break")})
    rows.sort(key=lambda r: (r["date_label"], -(r["hi"] or 0)))
    return rows
