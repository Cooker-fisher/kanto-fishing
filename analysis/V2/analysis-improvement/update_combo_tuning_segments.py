"""
update_combo_tuning_segments.py
combo_tuning/ JSONに便別・ポイント×水深帯・水色セグメントモデル結果を追加する。

読取元:
  analysis/V2/results/analysis.sqlite
    - combo_backtest          : 全体モデル wmape_h0
    - combo_trip_backtest     : 便別セグメント
    - combo_point_depth_backtest : ポイント×水深帯セグメント
    - combo_water_color_backtest : 水色セグメント

書込先:
  analysis/V2/analysis-improvement/combo_tuning/{魚種}×{船宿}.json

追加フィールド:
  trip_models, best_trip
  point_depth_models, best_point_depth
  water_color_models, best_water_color

既存フィールドは変更しない（point_models, best_point, improvement_pt 等）。
last_reviewed を "2026-04-22" に更新。
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
TODAY = "2026-04-22"


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


def main():
    print(f"DB: {DB_PATH}")
    print(f"JSON DIR: {JSON_DIR}")

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

    db.close()

    # --- JSONファイル一覧 ---
    json_files = sorted(f for f in os.listdir(JSON_DIR) if f.endswith(".json"))
    print(f"\nJSON files: {len(json_files)}件 先頭3: {json_files[:3]}")

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

    print(f"\n=== 完了 ===")
    print(f"更新: {updated}件 / スキップ: {skipped}件 / エラー: {len(errors)}件")
    if errors:
        for fname, msg in errors:
            print(f"  ERROR {fname}: {msg}")

    # --- 代表例出力 ---
    for target_fname in ["アジ×長崎屋.json", "タチウオ×吉野屋.json"]:
        fpath = os.path.join(JSON_DIR, target_fname)
        if not os.path.exists(fpath):
            print(f"\n{target_fname}: ファイルなし")
            continue
        with open(fpath, encoding="utf-8") as f:
            d = json.load(f)
        print(f"\n=== {target_fname} 更新内容 ===")
        print(f"  base wmape_h0: {base_map.get((d['fish'], d['ship']), {}).get('wmape_h0')}")
        print(f"  trip_models ({len(d.get('trip_models', []))}件): {d.get('trip_models', [])[:3]}")
        print(f"  best_trip: {d.get('best_trip')}")
        print(f"  point_depth_models ({len(d.get('point_depth_models', []))}件): {d.get('point_depth_models', [])[:2]}")
        print(f"  best_point_depth: {d.get('best_point_depth')}")
        print(f"  water_color_models ({len(d.get('water_color_models', []))}件): {d.get('water_color_models', [])[:3]}")
        print(f"  best_water_color: {d.get('best_water_color')}")
        print(f"  last_reviewed: {d.get('last_reviewed')}")


if __name__ == "__main__":
    main()
