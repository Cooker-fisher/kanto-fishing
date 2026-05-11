"""
update_combo_tuning_segments.py
combo_tuning/ JSONに便別・ポイント×水深帯・水色セグメントモデル結果を追加する。

読取元:
  analysis/V2/results/analysis.sqlite
    - combo_backtest          : 全体モデル wmape_h0
    - combo_trip_backtest     : 便別セグメント
    - combo_point_depth_backtest : ポイント×水深帯セグメント
    - combo_water_color_backtest : 水色セグメント
    - combo_wx_params         : 採用因子（adopted_factors 生成元）
    - combo_deep_params       : 因子別サンプル数（n_valid）
    - combo_point_stats       : ポイント別件数（points / modal_coord / multi_point_risk）
    - combo_meta              : modal_coord（lat/lon）

書込先:
  analysis/V2/analysis-improvement/combo_tuning/{魚種}×{船宿}.json

追加フィールド:
  trip_models, best_trip
  point_depth_models, best_point_depth
  water_color_models, best_water_color

--target オプション指定時: 対象コンボのみ以下のフィールドを補完:
  adopted_factors, points, modal_coord, multi_point_risk, overrides, insights, rejected_factors

既存フィールドは変更しない（point_models, best_point, improvement_pt 等）。
last_reviewed を TODAY に更新。

使用例:
  # 全コンボのセグメント更新（既存動作）
  python update_combo_tuning_segments.py

  # 特定コンボに adopted_factors / points も含めて補完
  python update_combo_tuning_segments.py --target イシモチ×小柴丸 キントキ×敷嶋丸
"""

import json
import os
import sqlite3
import sys
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

# --- パス設定 ---
BASE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.join(BASE, "..", "..", "..")  # kanto-fishing/
DB_PATH = os.path.join(REPO, "analysis", "V2", "results", "analysis.sqlite")
JSON_DIR = os.path.join(BASE, "combo_tuning")
from datetime import date as _date
TODAY = _date.today().isoformat()


def load_combo_backtest(cur):
    """全体モデルの wmape_h0, bl2_wmape を (fish, ship) -> dict で返す"""
    rows = cur.execute(
        "SELECT fish, ship, wmape, bl2_wmape FROM combo_backtest "
        "WHERE metric='cnt_avg' AND horizon=0"
    ).fetchall()
    result = {}
    for fish, ship, wmape, bl2 in rows:
        result[(fish, ship)] = {"wmape_h0": wmape, "bl2_wmape": bl2}
    return result


def load_trip_backtest(cur):
    """便別バックテスト: (fish, ship) -> list of dicts"""
    rows = cur.execute(
        "SELECT fish, ship, trip_no, wmape, bl2_wmape, n FROM combo_trip_backtest "
        "WHERE metric='cnt_avg' AND horizon=0 ORDER BY fish, ship, trip_no"
    ).fetchall()
    result = {}
    for fish, ship, trip_no, wmape, bl2, n in rows:
        key = (fish, ship)
        result.setdefault(key, []).append(
            {"trip_no": trip_no, "n": n, "wmape_h0": round(wmape, 1),
             "bl2_wmape": round(bl2, 1)}
        )
    return result


def load_point_depth_backtest(cur):
    """ポイント×水深帯バックテスト: (fish, ship) -> list of dicts"""
    rows = cur.execute(
        "SELECT fish, ship, point_depth_key, wmape, bl2_wmape, n "
        "FROM combo_point_depth_backtest "
        "WHERE metric='cnt_avg' AND horizon=0 ORDER BY fish, ship, wmape"
    ).fetchall()
    result = {}
    for fish, ship, key, wmape, bl2, n in rows:
        k = (fish, ship)
        result.setdefault(k, []).append(
            {"key": key, "n": n, "wmape_h0": round(wmape, 1),
             "bl2_wmape": round(bl2, 1)}
        )
    return result


def load_water_color_backtest(cur):
    """水色バックテスト: (fish, ship) -> list of dicts"""
    rows = cur.execute(
        "SELECT fish, ship, water_color_cat, wmape, bl2_wmape, n "
        "FROM combo_water_color_backtest "
        "WHERE metric='cnt_avg' AND horizon=0 ORDER BY fish, ship, wmape"
    ).fetchall()
    result = {}
    for fish, ship, cat, wmape, bl2, n in rows:
        k = (fish, ship)
        result.setdefault(k, []).append(
            {"cat": cat, "n": n, "wmape_h0": round(wmape, 1),
             "bl2_wmape": round(bl2, 1)}
        )
    return result


def add_improvement(models_list, base_wmape, key_field):
    """各モデルに improvement_pt を付与し、best を返す"""
    if base_wmape is None:
        for m in models_list:
            m["improvement_pt"] = None
        return None

    best = None
    best_imp = None
    for m in models_list:
        imp = round(base_wmape - m["wmape_h0"], 1)
        m["improvement_pt"] = imp
        if best_imp is None or imp > best_imp:
            best_imp = imp
            best = m.copy()

    # 改善がないケース（全て負）でも best は返す（最大値のもの）
    # ただし best_imp < 0 の場合は None を返す
    if best_imp is not None and best_imp < 0:
        return None
    return best


def make_best_trip(best):
    if best is None:
        return None
    return {"trip_no": best["trip_no"], "wmape_h0": best["wmape_h0"],
            "improvement_pt": best["improvement_pt"]}


def make_best_point_depth(best):
    if best is None:
        return None
    return {"key": best["key"], "wmape_h0": best["wmape_h0"],
            "improvement_pt": best["improvement_pt"]}


def make_best_water_color(best):
    if best is None:
        return None
    return {"cat": best["cat"], "wmape_h0": best["wmape_h0"],
            "improvement_pt": best["improvement_pt"]}


# ---------------------------------------------------------------------------
# adopted_factors / points / modal_coord 補完（--target 指定時のみ実行）
# ---------------------------------------------------------------------------

def load_adopted_factors(cur, fish, ship):
    """combo_wx_params + combo_deep_params から adopted_factors を組み立てる。
    採用因子 = combo_wx_params で metric='cnt_avg' かつ r IS NOT NULL な行。
    n_valid = combo_deep_params.n（同一 fish/ship/factor/metric）。
    """
    rows = cur.execute(
        "SELECT wp.factor, wp.r, dp.n "
        "FROM combo_wx_params wp "
        "LEFT JOIN combo_deep_params dp "
        "  ON dp.fish=wp.fish AND dp.ship=wp.ship "
        "  AND dp.factor=wp.factor AND dp.metric=wp.metric "
        "WHERE wp.fish=? AND wp.ship=? AND wp.metric=? AND wp.r IS NOT NULL "
        "ORDER BY ABS(wp.r) DESC",
        (fish, ship, "cnt_avg")
    ).fetchall()
    return [
        {"factor": factor, "corr": round(r, 4), "n_valid": n if n is not None else 0}
        for factor, r, n in rows
    ]


def load_points_info(cur, fish, ship):
    """combo_point_stats から points リスト・modal_coord・multi_point_risk を返す。
    pct は各ポイントの n / 全合計 で計算。is_named=True のポイントのみ対象。
    """
    rows = cur.execute(
        "SELECT point, n FROM combo_point_stats "
        "WHERE fish=? AND ship=? AND is_named=1 "
        "ORDER BY n DESC",
        (fish, ship)
    ).fetchall()
    if not rows:
        return [], None, None

    filtered = [(pt, n) for pt, n in rows if n >= 5]
    if not filtered:
        return [], None, None
    total = sum(n for _, n in filtered)
    points = [
        {"name": pt, "n": n, "pct": round(n / total * 100)}
        for pt, n in filtered
    ]

    # modal_coord: combo_meta.lat/lon
    m = cur.execute(
        "SELECT lat, lon FROM combo_meta WHERE fish=? AND ship=?", (fish, ship)
    ).fetchone()
    modal_coord = {"lat": m[0], "lon": m[1]} if m else {"lat": None, "lon": None}

    # multi_point_risk: 最頻ポイントの占有率で判定
    top_pct = points[0]["pct"] if points else 0
    if top_pct >= 70:
        risk = "low"
    elif top_pct >= 40:
        risk = "medium"
    else:
        risk = "high"

    return points, modal_coord, risk


def fill_missing_fields(d, cur, fish, ship):
    """JSON に存在しないフィールドを DB から補完する。既存フィールドは上書きしない。"""
    changed = False

    # adopted_factors
    if not d.get("adopted_factors"):
        af = load_adopted_factors(cur, fish, ship)
        d["adopted_factors"] = af
        d.setdefault("rejected_factors", [])
        d.setdefault("overrides", {})
        d.setdefault("insights", [])
        changed = True
        print(f"    adopted_factors: {len(af)}件 補完")

    # points / modal_coord / multi_point_risk
    if not d.get("points"):
        pts, mc, risk = load_points_info(cur, fish, ship)
        d["points"] = pts
        d["modal_coord"] = mc
        d["multi_point_risk"] = risk
        changed = True
        print(f"    points: {len(pts)}件 modal_coord={mc} risk={risk}")

    return changed


def main():
    # --target 引数: 指定した場合はそのファイルのみ adopted_factors/points 補完も実施
    target_fnames = set()
    args = sys.argv[1:]
    if "--target" in args:
        idx = args.index("--target")
        raw_targets = args[idx + 1:]
        for t in raw_targets:
            fname = t if t.endswith(".json") else f"{t}.json"
            target_fnames.add(fname)
    fill_missing = bool(target_fnames)

    print(f"DB: {DB_PATH}")
    print(f"JSON DIR: {JSON_DIR}")
    if fill_missing:
        print(f"--target モード: {sorted(target_fnames)} のみ adopted_factors/points 補完")

    db = sqlite3.connect(DB_PATH)
    cur = db.cursor()

    # --- DBから全データ読込 ---
    print("Loading combo_backtest ...")
    base_map = load_combo_backtest(cur)
    print(f"  全体モデル: {len(base_map)}コンボ")

    print("Loading combo_trip_backtest ...")
    trip_map = load_trip_backtest(cur)
    trip_keys = list(trip_map.keys())
    print(f"  trip combos: {len(trip_keys)}件 先頭3: {trip_keys[:3]}")

    print("Loading combo_point_depth_backtest ...")
    pd_map = load_point_depth_backtest(cur)
    pd_keys = list(pd_map.keys())
    print(f"  point_depth combos: {len(pd_keys)}件 先頭3: {pd_keys[:3]}")

    print("Loading combo_water_color_backtest ...")
    wc_map = load_water_color_backtest(cur)
    wc_keys = list(wc_map.keys())
    print(f"  water_color combos: {len(wc_keys)}件 先頭3: {wc_keys[:3]}")

    # --- JSONファイル一覧 ---
    all_json_files = sorted(f for f in os.listdir(JSON_DIR) if f.endswith(".json"))
    # --target 指定時はそのファイルのみ処理、未指定なら全件
    json_files = [f for f in all_json_files if not fill_missing or f in target_fnames]
    print(f"\nJSON files (処理対象): {len(json_files)}件 / 全体: {len(all_json_files)}件")

    # --target 指定のファイルが存在するか事前チェック
    if fill_missing:
        for fname in target_fnames:
            if fname not in set(all_json_files):
                print(f"  WARNING: {fname} が combo_tuning/ に存在しない")

    updated = 0
    skipped = 0
    errors = []

    for fname in json_files:
        fpath = os.path.join(JSON_DIR, fname)
        try:
            with open(fpath, encoding="utf-8") as f:
                d = json.load(f)
        except Exception as e:
            errors.append((fname, f"load error: {e}"))
            continue

        fish = d.get("fish", "")
        ship = d.get("ship", "")
        combo_key = (fish, ship)

        # 全体モデルの基準 wmape
        base = base_map.get(combo_key)
        base_wmape = base["wmape_h0"] if base else None

        changed = False

        # --- adopted_factors / points 補完（--target 指定ファイルのみ）---
        if fill_missing and fname in target_fnames:
            print(f"\n[fill] {fname}")
            c = fill_missing_fields(d, cur, fish, ship)
            if c:
                changed = True

        # --- 便別モデル ---
        if combo_key in trip_map:
            models = [m.copy() for m in trip_map[combo_key]]
            best_raw = add_improvement(models, base_wmape, "trip_no")
            d["trip_models"] = models
            d["best_trip"] = make_best_trip(best_raw)
            changed = True
        else:
            # データなし → フィールドを null で明示
            if "trip_models" not in d:
                d["trip_models"] = []
                d["best_trip"] = None
                changed = True

        # --- ポイント×水深帯モデル ---
        if combo_key in pd_map:
            models = [m.copy() for m in pd_map[combo_key]]
            best_raw = add_improvement(models, base_wmape, "key")
            d["point_depth_models"] = models
            d["best_point_depth"] = make_best_point_depth(best_raw)
            changed = True
        else:
            if "point_depth_models" not in d:
                d["point_depth_models"] = []
                d["best_point_depth"] = None
                changed = True

        # --- 水色モデル ---
        if combo_key in wc_map:
            models = [m.copy() for m in wc_map[combo_key]]
            best_raw = add_improvement(models, base_wmape, "cat")
            d["water_color_models"] = models
            d["best_water_color"] = make_best_water_color(best_raw)
            changed = True
        else:
            if "water_color_models" not in d:
                d["water_color_models"] = []
                d["best_water_color"] = None
                changed = True

        # last_reviewed 更新
        d["last_reviewed"] = TODAY
        changed = True

        if changed:
            with open(fpath, "w", encoding="utf-8") as f:
                json.dump(d, f, ensure_ascii=False, indent=2)
            updated += 1
        else:
            skipped += 1

    db.close()

    print(f"\n=== 完了 ===")
    print(f"更新: {updated}件 / スキップ: {skipped}件 / エラー: {len(errors)}件")
    if errors:
        for fname, msg in errors:
            print(f"  ERROR {fname}: {msg}")

    # --- 代表例出力 ---
    check_fnames = list(target_fnames) if fill_missing else ["アジ×長崎屋.json", "タチウオ×吉野屋.json"]
    for target_fname in check_fnames[:5]:
        fpath = os.path.join(JSON_DIR, target_fname)
        if not os.path.exists(fpath):
            print(f"\n{target_fname}: ファイルなし")
            continue
        with open(fpath, encoding="utf-8") as f:
            d = json.load(f)
        print(f"\n=== {target_fname} 更新内容 ===")
        fish_k = d.get("fish", "")
        ship_k = d.get("ship", "")
        print(f"  base wmape_h0: {base_map.get((fish_k, ship_k), {}).get('wmape_h0')}")
        print(f"  adopted_factors: {len(d.get('adopted_factors') or [])}件")
        print(f"  points: {len(d.get('points') or [])}件")
        print(f"  modal_coord: {d.get('modal_coord')}")
        print(f"  multi_point_risk: {d.get('multi_point_risk')}")
        print(f"  trip_models: {len(d.get('trip_models') or [])}件")
        print(f"  best_trip: {d.get('best_trip')}")
        print(f"  point_depth_models: {len(d.get('point_depth_models') or [])}件")
        print(f"  best_point_depth: {d.get('best_point_depth')}")
        print(f"  water_color_models: {len(d.get('water_color_models') or [])}件")
        print(f"  best_water_color: {d.get('best_water_color')}")
        print(f"  last_reviewed: {d.get('last_reviewed')}")


if __name__ == "__main__":
    main()
