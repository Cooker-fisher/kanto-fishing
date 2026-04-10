#!/usr/bin/env python3
"""
range_predictor.py — ML ベース釣果レンジ予測 (V2.1)

予測対象:
  y_min   = その日の実績最小釣果（底が抜ける日か）
  y_max   = その日の実績最大釣果（爆発余地があるか）
  y_width = y_max - y_min（安定日か荒れ日か）

2方式:
  方式B（本命）: model_min + model_width → pred_max = pred_min + clip(pred_width, 0)
  方式A（比較）: model_min + model_max  → pred_max = max(pred_max, pred_min)

4モデル: linear / rf / lgbm / catboost

V2 資産の再利用:
  - load_records(fish, ship_filter=ship) : 1コンボ分 CSV ロード
  - enrich()        : 天候・潮汐・前週釣果の付与
  - SLOW/FAST_FACTORS: 特徴量リスト定義
  - combo_decadal   : 旬別 avg_cnt_min / avg_cnt_max をベースライン特徴量として利用

walk-forward validation（expanding window、月単位）
結果は analysis/V2.1/results/range_eval.sqlite に保存

単位: 船宿×魚種 コンボ（n >= MIN_TRAIN_N のみ）

使い方:
  python range_predictor.py --fish アジ [--eda] [--horizon 7]
  python range_predictor.py --combo アジ 庄治郎丸 [--eda]
  python range_predictor.py --all [--horizon 7]
"""

import argparse
import csv
import glob
import os
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from math import sqrt

import numpy as np
import pandas as pd

# ── V2 モジュールを import ────────────────────────────────────────────────────
_V2_METHODS = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "V2", "methods")
)
sys.path.insert(0, _V2_METHODS)

from combo_deep_dive import load_records, enrich, SLOW_FACTORS, FAST_FACTORS
from _paths import ROOT_DIR, DATA_DIR, OCEAN_DIR

# ── V2 DB（combo_decadal 参照用・読み取りのみ） ───────────────────────────────
DB_V2      = os.path.normpath(os.path.join(ROOT_DIR, "analysis", "V2", "results", "analysis.sqlite"))
DB_WX      = os.path.join(OCEAN_DIR, "weather_cache.sqlite")
DB_TIDE    = os.path.join(OCEAN_DIR, "tide_moon.sqlite")
DB_TYPHOON = os.path.join(OCEAN_DIR, "typhoon.sqlite")

# ── V2.1 出力 DB ─────────────────────────────────────────────────────────────
_RESULTS_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "results"))
os.makedirs(_RESULTS_DIR, exist_ok=True)
DB_V21 = os.path.join(_RESULTS_DIR, "range_eval.sqlite")

# ── 定数 ─────────────────────────────────────────────────────────────────────
HORIZON       = 7        # デフォルト予測ホライズン（日）
MIN_TRAIN_N   = 50       # 学習最小件数
MIN_TEST_N    = 5        # テスト最小件数
WINKLER_ALPHA = 0.1      # Winkler score のペナルティ係数
METHODS       = ["B_min_width", "A_min_max"]
MODEL_NAMES   = ["linear", "rf", "lgbm", "catboost"]

# H=7 で使用する特徴量（SLOW + FAST 全て）
FEATURE_COLS = list(SLOW_FACTORS) + list(FAST_FACTORS)

# 分位点設定
QUANTILE_MIN   = 0.20
QUANTILE_MAX   = 0.80
QUANTILE_WIDTH = 0.70

MODEL_VARIANTS = {
    "point":    (None,         None,          None),
    "quantile": (QUANTILE_MIN, QUANTILE_MAX,  QUANTILE_WIDTH),
}


# ══════════════════════════════════════════════════════════════════════════════
# ユーティリティ
# ══════════════════════════════════════════════════════════════════════════════

def _date_to_decade(date_str: str) -> int:
    """YYYY/MM/DD → 旬番号 1-36"""
    try:
        d = datetime.strptime(date_str, "%Y/%m/%d")
        month_idx = d.month - 1
        decade    = min((d.day - 1) // 10, 2)
        return month_idx * 3 + decade + 1
    except Exception:
        return 0


def _load_decadal_baseline(fish: str, ship: str) -> dict:
    """
    combo_decadal から {decade_no: (avg_cnt_min, avg_cnt_max)} を返す。
    対象コンボのみ絞り込む。
    """
    if not os.path.exists(DB_V2):
        return {}
    conn = sqlite3.connect(DB_V2)
    rows = conn.execute(
        "SELECT decade_no, avg_cnt_min, avg_cnt_max FROM combo_decadal "
        "WHERE fish=? AND ship=? AND avg_cnt_min IS NOT NULL",
        (fish, ship)
    ).fetchall()
    conn.close()
    return {r[0]: (r[1], r[2]) for r in rows}


# ══════════════════════════════════════════════════════════════════════════════
# データロード（コンボ単位）
# ══════════════════════════════════════════════════════════════════════════════

def load_combo_data(fish: str, ship: str, horizon: int = HORIZON) -> pd.DataFrame:
    """
    指定コンボ（魚種×船宿）のレコードを読み込み、天候・潮汐特徴量を付与して DataFrame を返す。

    Returns:
        DataFrame with columns:
          date, ship, area, decade, cnt_min, cnt_max, width,
          + SLOW_FACTORS + FAST_FACTORS（enrich 出力）
          + bl_min, bl_max（combo_decadal ベースライン）
    """
    records = load_records(fish, ship_filter=ship)
    if not records:
        return pd.DataFrame()

    try:
        conn_wx      = sqlite3.connect(DB_WX)      if os.path.exists(DB_WX)      else None
        conn_tide    = sqlite3.connect(DB_TIDE)     if os.path.exists(DB_TIDE)    else None
        conn_typhoon = sqlite3.connect(DB_TYPHOON)  if os.path.exists(DB_TYPHOON) else None

        # ship_coords: enrich に渡す {ship: (lat, lon)}
        ship_coords = {}
        for r in records:
            if r.get("lat") and r.get("lon") and r["ship"] not in ship_coords:
                ship_coords[r["ship"]] = (r["lat"], r["lon"])

        # wx_coords: 気象格子点
        wx_coords = []
        if conn_wx:
            wx_coords = [
                (r[0], r[1]) for r in conn_wx.execute(
                    "SELECT DISTINCT lat, lon FROM weather LIMIT 1000"
                ).fetchall()
            ]

        ship_area = {r["ship"]: r.get("area", "") for r in records}

        enriched = enrich(
            records,
            ship_coords=ship_coords,
            wx_coords=wx_coords,
            conn_wx=conn_wx,
            ship_area=ship_area,
            horizon=horizon,
            all_records=records,
            conn_tide=conn_tide,
            conn_typhoon=conn_typhoon,
        )
    finally:
        for c in [conn_wx, conn_tide, conn_typhoon]:
            if c:
                c.close()

    df = pd.DataFrame(enriched)

    # cnt_min / cnt_max が両方ある行のみ使用
    df = df.dropna(subset=["cnt_min", "cnt_max"])
    df["cnt_min"] = pd.to_numeric(df["cnt_min"], errors="coerce")
    df["cnt_max"] = pd.to_numeric(df["cnt_max"], errors="coerce")
    df = df.dropna(subset=["cnt_min", "cnt_max"])
    df = df[df["cnt_max"] >= df["cnt_min"]]

    df["width"] = df["cnt_max"] - df["cnt_min"]

    if "decade" not in df.columns:
        df["decade"] = df["date"].apply(lambda d: _date_to_decade(d))

    # コンボ別ベースライン
    baseline = _load_decadal_baseline(fish, ship)
    df["bl_min"] = df["decade"].apply(
        lambda dec: baseline.get(dec, (None, None))[0]
    )
    df["bl_max"] = df["decade"].apply(
        lambda dec: baseline.get(dec, (None, None))[1]
    )
    # 欠損は当コンボの中央値で補完
    df["bl_min"] = df["bl_min"].fillna(df["cnt_min"].median())
    df["bl_max"] = df["bl_max"].fillna(df["cnt_max"].median())

    df["date_dt"] = pd.to_datetime(df["date"], format="%Y/%m/%d", errors="coerce")
    df = df.dropna(subset=["date_dt"])
    df = df.sort_values("date_dt").reset_index(drop=True)

    # ── 直近釣果ラグ特徴量（自己相関 r≈0.4〜0.5）────────────────────────────
    # shift(1): 1つ前のレコード（約1週間前）
    # shift(2): 2つ前
    # rolling(3/7): 直近3・7件の平均
    for col in ["cnt_min", "cnt_max"]:
        s = df[col]
        df[f"lag1_{col}"]   = s.shift(1)
        df[f"lag2_{col}"]   = s.shift(2)
        df[f"roll3_{col}"]  = s.shift(1).rolling(3, min_periods=1).mean()
        df[f"roll7_{col}"]  = s.shift(1).rolling(7, min_periods=1).mean()

    # width のラグも追加
    df["lag1_width"]  = df["width"].shift(1)
    df["roll3_width"] = df["width"].shift(1).rolling(3, min_periods=1).mean()

    return df


# ══════════════════════════════════════════════════════════════════════════════
# 特徴量行列の構築
# ══════════════════════════════════════════════════════════════════════════════

def build_feature_matrix(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """
    enrich 出力 DataFrame → モデル入力用 DataFrame X を返す。

    コンボ単位なので ship / area は定数 → 特徴量から除外。
    全列を数値化。欠損は 0 補完。
    """
    LAG_COLS = [
        "lag1_cnt_min", "lag2_cnt_min", "roll3_cnt_min", "roll7_cnt_min",
        "lag1_cnt_max", "lag2_cnt_max", "roll3_cnt_max", "roll7_cnt_max",
        "lag1_width",   "roll3_width",
    ]
    feature_candidates = FEATURE_COLS + ["bl_min", "bl_max"] + LAG_COLS

    use_cols = [c for c in feature_candidates if c in df.columns]
    X = df[use_cols].copy()

    for c in use_cols:
        X[c] = pd.to_numeric(X[c], errors="coerce")
    X = X.fillna(0.0)

    return X, {"cat_indices": [], "cat_names": [], "use_cols": use_cols}


# ══════════════════════════════════════════════════════════════════════════════
# walk-forward splits
# ══════════════════════════════════════════════════════════════════════════════

def walk_forward_splits(df: pd.DataFrame, min_train_n: int = MIN_TRAIN_N):
    """
    expanding window の (train_mask, test_mask, fold_label) ジェネレータ。
    テスト単位は月（YYYY-MM）。
    """
    df = df.copy()
    df["ym"] = df["date_dt"].dt.to_period("M")
    months = sorted(df["ym"].unique())

    for i, test_month in enumerate(months[1:], start=1):
        train_mask = df["ym"] < test_month
        test_mask  = df["ym"] == test_month
        if train_mask.sum() < min_train_n:
            continue
        if test_mask.sum() < MIN_TEST_N:
            continue
        yield train_mask, test_mask, str(test_month)


# ══════════════════════════════════════════════════════════════════════════════
# モデル学習・予測
# ══════════════════════════════════════════════════════════════════════════════

def _get_model(model_name: str, quantile: float | None = None):
    """モデルインスタンスを返す。"""
    from sklearn.linear_model import QuantileRegressor, Ridge
    from sklearn.ensemble import RandomForestRegressor, GradientBoostingRegressor
    from lightgbm import LGBMRegressor
    from catboost import CatBoostRegressor

    if quantile is not None:
        if model_name == "linear":
            return QuantileRegressor(quantile=quantile, alpha=0.1, solver="highs")
        elif model_name == "rf":
            return GradientBoostingRegressor(
                loss="quantile", alpha=quantile,
                n_estimators=200, learning_rate=0.05, random_state=42
            )
        elif model_name == "lgbm":
            return LGBMRegressor(
                objective="quantile", alpha=quantile,
                n_estimators=300, learning_rate=0.05, num_leaves=31,
                random_state=42, verbose=-1
            )
        elif model_name == "catboost":
            return CatBoostRegressor(
                loss_function=f"Quantile:alpha={quantile}",
                iterations=100, learning_rate=0.1,
                random_seed=42, verbose=0, thread_count=4,
            )

    # 点予測
    if model_name == "linear":
        return Ridge(alpha=1.0)
    elif model_name == "rf":
        return RandomForestRegressor(n_estimators=200, n_jobs=-1, random_state=42)
    elif model_name == "lgbm":
        return LGBMRegressor(
            n_estimators=300, learning_rate=0.05, num_leaves=31,
            random_state=42, verbose=-1
        )
    elif model_name == "catboost":
        return CatBoostRegressor(
            iterations=100, learning_rate=0.1,
            random_seed=42, verbose=0, thread_count=4,
        )
    else:
        raise ValueError(f"Unknown model: {model_name}")


def train_predict(
    X_tr: pd.DataFrame, y_tr: np.ndarray,
    X_te: pd.DataFrame, model_name: str,
    cat_indices: list,
    quantile: float | None = None,
) -> np.ndarray:
    """1モデルを学習して予測値を返す。"""
    use_log = (quantile is None)
    model = _get_model(model_name, quantile=quantile)

    y_fit = np.log1p(y_tr) if use_log else y_tr

    # コンボ単位なので cat_indices は常に空
    model.fit(X_tr, y_fit)

    raw = model.predict(X_te)
    pred = (np.expm1(raw) if use_log else raw).clip(min=0.0)
    return pred


# ══════════════════════════════════════════════════════════════════════════════
# 評価指標
# ══════════════════════════════════════════════════════════════════════════════

def evaluate_interval(
    pred_min: np.ndarray, pred_max: np.ndarray,
    true_min: np.ndarray, true_max: np.ndarray
) -> dict:
    """予測区間 [pred_min, pred_max] と実績 [true_min, true_max] を評価。"""
    n = len(true_min)
    if n == 0:
        return {}

    true_width = true_max - true_min
    pred_width = pred_max - pred_min

    mae_min   = float(np.mean(np.abs(pred_min - true_min)))
    mae_max   = float(np.mean(np.abs(pred_max - true_max)))
    mae_width = float(np.mean(np.abs(pred_width - true_width)))
    bias_min  = float(np.mean(pred_min - true_min))
    bias_max  = float(np.mean(pred_max - true_max))

    cover_min = (pred_min <= true_min)
    cover_max = (pred_max >= true_max)
    coverage  = float(np.mean(cover_min & cover_max))

    avg_pred_width = float(np.mean(pred_width))
    avg_true_width = float(np.mean(true_width))

    alpha = WINKLER_ALPHA
    winkler_vals = pred_width.copy().astype(float)
    winkler_vals += np.where(true_min < pred_min, (2 / alpha) * (pred_min - true_min), 0.0)
    winkler_vals += np.where(true_max > pred_max, (2 / alpha) * (true_max - pred_max), 0.0)
    winkler = float(np.mean(winkler_vals))

    denom_min = np.sum(true_min)
    denom_max = np.sum(true_max)
    wmape_min = float(np.sum(np.abs(pred_min - true_min)) / denom_min) if denom_min > 0 else None
    wmape_max = float(np.sum(np.abs(pred_max - true_max)) / denom_max) if denom_max > 0 else None

    return {
        "MAE_min":      round(mae_min, 3),
        "MAE_max":      round(mae_max, 3),
        "MAE_width":    round(mae_width, 3),
        "Bias_min":     round(bias_min, 3),
        "Bias_max":     round(bias_max, 3),
        "Coverage":     round(coverage, 4),
        "AvgPredWidth": round(avg_pred_width, 2),
        "AvgTrueWidth": round(avg_true_width, 2),
        "Winkler":      round(winkler, 3),
        "WMAPE_min":    round(wmape_min, 4) if wmape_min is not None else None,
        "WMAPE_max":    round(wmape_max, 4) if wmape_max is not None else None,
    }


# ══════════════════════════════════════════════════════════════════════════════
# コンボ単位実行
# ══════════════════════════════════════════════════════════════════════════════

def run_combo(fish: str, ship: str, horizon: int = HORIZON,
              verbose: bool = True, active_models: list | None = None) -> list[dict]:
    """
    指定コンボ（魚種×船宿）について全モデル × 全方式 × 全 fold を実行し、結果リストを返す。
    """
    if verbose:
        print(f"\n  [{fish} × {ship}]", end=" ", flush=True)

    df = load_combo_data(fish, ship, horizon)
    if df.empty:
        if verbose:
            print("データなし SKIP")
        return []

    folds = list(walk_forward_splits(df))
    if not folds:
        if verbose:
            print(f"n={len(df)} fold不足 SKIP")
        return []

    if verbose:
        print(f"n={len(df)}  folds={len(folds)}  "
              f"{df['date_dt'].min().date()}〜{df['date_dt'].max().date()}")

    X_all, meta = build_feature_matrix(df)
    cat_indices = meta["cat_indices"]  # 常に空

    y_min_all   = df["cnt_min"].values.astype(float)
    y_max_all   = df["cnt_max"].values.astype(float)
    y_width_all = df["width"].values.astype(float)

    all_results = []
    models_to_run = active_models if active_models is not None else MODEL_NAMES

    for model_name in models_to_run:
        for variant_name, (q_min, q_max, q_width) in MODEL_VARIANTS.items():
            fold_records: dict[str, dict] = {}

            for train_mask, test_mask, fold_label in folds:
                X_tr = X_all[train_mask]
                X_te = X_all[test_mask]

                pred_min = train_predict(
                    X_tr, y_min_all[train_mask], X_te, model_name, cat_indices, quantile=q_min
                )
                pred_max_direct = train_predict(
                    X_tr, y_max_all[train_mask], X_te, model_name, cat_indices, quantile=q_max
                )
                pred_width = train_predict(
                    X_tr, y_width_all[train_mask], X_te, model_name, cat_indices, quantile=q_width
                )

                fold_records[fold_label] = {
                    "true_min":   y_min_all[test_mask],
                    "true_max":   y_max_all[test_mask],
                    "pred_min":   pred_min,
                    "pred_max_A": np.maximum(pred_max_direct, pred_min),
                    "pred_max_B": pred_min + pred_width.clip(min=0),
                }

            true_min  = np.concatenate([v["true_min"]   for v in fold_records.values()])
            true_max  = np.concatenate([v["true_max"]   for v in fold_records.values()])
            pred_min  = np.concatenate([v["pred_min"]   for v in fold_records.values()])
            pred_maxA = np.concatenate([v["pred_max_A"] for v in fold_records.values()])
            pred_maxB = np.concatenate([v["pred_max_B"] for v in fold_records.values()])

            model_key = f"{model_name}_{variant_name}"
            for method, pred_max in [("A_min_max", pred_maxA), ("B_min_width", pred_maxB)]:
                metrics = evaluate_interval(pred_min, pred_max, true_min, true_max)
                all_results.append({
                    "fish":    fish,
                    "ship":    ship,
                    "method":  method,
                    "model":   model_key,
                    "fold":    "all",
                    "n_test":  len(true_min),
                    "horizon": horizon,
                    **metrics,
                })

    return all_results


# ══════════════════════════════════════════════════════════════════════════════
# DB 保存
# ══════════════════════════════════════════════════════════════════════════════

def init_db():
    """range_eval.sqlite のテーブルを作成（なければ）。"""
    conn = sqlite3.connect(DB_V21)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS range_eval (
            fish          TEXT,
            ship          TEXT,
            method        TEXT,
            model         TEXT,
            fold          TEXT,
            horizon       INTEGER,
            MAE_min       REAL,
            MAE_max       REAL,
            MAE_width     REAL,
            Bias_min      REAL,
            Bias_max      REAL,
            Coverage      REAL,
            AvgPredWidth  REAL,
            AvgTrueWidth  REAL,
            Winkler       REAL,
            WMAPE_min     REAL,
            WMAPE_max     REAL,
            n_test        INTEGER,
            updated_at    TEXT,
            PRIMARY KEY (fish, ship, method, model, fold, horizon)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS range_best_model (
            fish          TEXT,
            ship          TEXT,
            method        TEXT,
            model         TEXT,
            Coverage      REAL,
            Winkler       REAL,
            AvgPredWidth  REAL,
            updated_at    TEXT,
            PRIMARY KEY (fish, ship)
        )
    """)
    conn.commit()
    conn.close()


def save_results(results: list[dict]):
    """評価結果を range_eval に保存し、range_best_model を更新。"""
    if not results:
        return
    conn = sqlite3.connect(DB_V21)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    for r in results:
        conn.execute("""
            INSERT OR REPLACE INTO range_eval
            (fish, ship, method, model, fold, horizon,
             MAE_min, MAE_max, MAE_width, Bias_min, Bias_max,
             Coverage, AvgPredWidth, AvgTrueWidth, Winkler,
             WMAPE_min, WMAPE_max, n_test, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            r["fish"], r["ship"], r["method"], r["model"], r["fold"],
            r.get("horizon", HORIZON),
            r.get("MAE_min"), r.get("MAE_max"), r.get("MAE_width"),
            r.get("Bias_min"), r.get("Bias_max"),
            r.get("Coverage"), r.get("AvgPredWidth"), r.get("AvgTrueWidth"),
            r.get("Winkler"),
            r.get("WMAPE_min"), r.get("WMAPE_max"),
            r.get("n_test"), now,
        ))

    # ベストモデル更新: Winkler 最小（Coverage >= 0.3 の候補から）
    combo_list = list({(r["fish"], r["ship"]) for r in results})
    for fish, ship in combo_list:
        candidates = [r for r in results if r["fish"] == fish and r["ship"] == ship
                      and r.get("Coverage") is not None and r["Coverage"] >= 0.3]
        if not candidates:
            candidates = [r for r in results if r["fish"] == fish and r["ship"] == ship]
        if not candidates:
            continue
        best = min(candidates, key=lambda r: r.get("Winkler") or float("inf"))
        conn.execute("""
            INSERT OR REPLACE INTO range_best_model
            (fish, ship, method, model, Coverage, Winkler, AvgPredWidth, updated_at)
            VALUES (?,?,?,?,?,?,?,?)
        """, (
            fish, ship, best["method"], best["model"],
            best.get("Coverage"), best.get("Winkler"), best.get("AvgPredWidth"), now,
        ))

    conn.commit()
    conn.close()
    print(f"\n  -> range_eval.sqlite に {len(results)} 件保存")


# ══════════════════════════════════════════════════════════════════════════════
# EDA
# ══════════════════════════════════════════════════════════════════════════════

def run_eda(df: pd.DataFrame, fish: str, ship: str):
    """基本統計・分布を標準出力に表示。"""
    print(f"\n{'='*60}")
    print(f"  EDA: {fish} x {ship}")
    print(f"{'='*60}")
    print(f"  レコード数: {len(df)}")
    print(f"  期間: {df['date_dt'].min().date()} 〜 {df['date_dt'].max().date()}")
    print()

    for col, label in [("cnt_min","y_min"), ("cnt_max","y_max"), ("width","y_width")]:
        s = df[col]
        print(f"  [{label}]")
        print(f"    ゼロ率: {(s==0).mean()*100:.1f}%")
        print(f"    中央値: {s.median():.1f}  平均: {s.mean():.1f}  std: {s.std():.1f}")
        print(f"    P10={s.quantile(.10):.1f}  P25={s.quantile(.25):.1f}"
              f"  P75={s.quantile(.75):.1f}  P90={s.quantile(.90):.1f}")
        print()

    df2 = df.copy()
    df2["month"] = df2["date_dt"].dt.month
    monthly = df2.groupby("month")[["cnt_min","cnt_max","width"]].median().round(1)
    print("  [月別中央値]")
    print(f"  {'月':>3}  {'min':>6}  {'max':>6}  {'width':>6}")
    for m, row in monthly.iterrows():
        print(f"  {m:>3}  {row['cnt_min']:>6.1f}  {row['cnt_max']:>6.1f}  {row['width']:>6.1f}")
    print()

    r = df["cnt_min"].corr(df["cnt_max"])
    print(f"  [y_min × y_max 相関]  r = {r:.3f}")


# ══════════════════════════════════════════════════════════════════════════════
# コンボ一覧取得
# ══════════════════════════════════════════════════════════════════════════════

def list_all_combos(fish_filter: str | None = None) -> list[tuple[str, str, int]]:
    """
    data/V2/*.csv から (fish, ship, n) リストを返す。
    fish_filter が指定された場合はその魚種のみ。
    n >= MIN_TRAIN_N のコンボのみ返す。
    """
    count: dict[tuple[str, str], int] = defaultdict(int)
    for f in glob.glob(os.path.join(DATA_DIR, "*.csv")):
        with open(f, encoding="utf-8-sig") as fp:
            reader = csv.DictReader(fp)
            for row in reader:
                tm = row.get("tsuri_mono", "").strip()
                ms = row.get("main_sub", "").strip()
                sh = row.get("ship", "").strip()
                if tm and ms == "メイン" and sh:
                    if fish_filter is None or tm == fish_filter:
                        count[(tm, sh)] += 1

    result = [
        (fish, ship, n)
        for (fish, ship), n in count.items()
        if n >= MIN_TRAIN_N
    ]
    result.sort(key=lambda x: (-x[2], x[0], x[1]))  # n 降順
    return result


# ══════════════════════════════════════════════════════════════════════════════
# main
# ══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="V2.1 range predictor（船宿×魚種コンボ単位）")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--fish",  type=str, help="魚種名（例: アジ）→ 全船宿コンボを実行")
    group.add_argument("--combo", nargs=2, metavar=("FISH", "SHIP"), help="コンボ指定（例: アジ 庄治郎丸）")
    group.add_argument("--all",   action="store_true", help="全コンボ（n>=50）を実行")
    parser.add_argument("--eda",         action="store_true", help="EDA レポートを表示")
    parser.add_argument("--horizon",     type=int, default=HORIZON, help="予測ホライズン（日）")
    parser.add_argument("--no-save",     action="store_true", help="DB 保存をスキップ（確認用）")
    parser.add_argument("--no-catboost", action="store_true", help="CatBoost を除外（高速化）")
    args = parser.parse_args()

    init_db()

    active_models = [m for m in MODEL_NAMES if not (args.no_catboost and m == "catboost")]

    # 対象コンボを決定
    if args.combo:
        fish_arg, ship_arg = args.combo
        combos = [(fish_arg, ship_arg, None)]
    elif args.fish:
        combos = list_all_combos(fish_filter=args.fish)
    else:
        combos = list_all_combos()

    print(f"対象コンボ: {len(combos)} 件  先頭3: {[(c[0], c[1]) for c in combos[:3]]}")
    print(f"モデル: {active_models}  horizon={args.horizon}d")

    all_results = []
    for entry in combos:
        fish, ship = entry[0], entry[1]
        n_label = f"(n={entry[2]})" if entry[2] is not None else ""
        try:
            if args.eda:
                df = load_combo_data(fish, ship, args.horizon)
                if not df.empty:
                    run_eda(df, fish, ship)

            results = run_combo(fish, ship, horizon=args.horizon,
                                active_models=active_models)
            all_results.extend(results)
        except Exception as e:
            print(f"\n  [ERROR] {fish} x {ship}: {e}")
            import traceback
            traceback.print_exc()

    if all_results and not args.no_save:
        save_results(all_results)

    # サマリー表示
    if all_results:
        model_variants = [f"{m}_{v}" for m in active_models for v in MODEL_VARIANTS]
        print(f"\n{'='*60}")
        print(f"  評価サマリー（{len(set((r['fish'],r['ship']) for r in all_results))} コンボ合計）")
        print(f"{'='*60}")
        print(f"  {'method':<16}  {'model+variant':<22}  {'Coverage':>8}  {'Winkler':>8}  {'AvgPredW':>9}  {'AvgTrueW':>9}")
        for method in METHODS:
            for model_key in model_variants:
                subset = [r for r in all_results if r["method"] == method and r["model"] == model_key]
                if not subset:
                    continue
                cov = np.mean([r["Coverage"]     for r in subset if r.get("Coverage")     is not None])
                wkl = np.mean([r["Winkler"]      for r in subset if r.get("Winkler")      is not None])
                apw = np.mean([r["AvgPredWidth"] for r in subset if r.get("AvgPredWidth") is not None])
                atw = np.mean([r["AvgTrueWidth"] for r in subset if r.get("AvgTrueWidth") is not None])
                print(f"  {method:<16}  {model_key:<22}  {cov:>8.2%}  {wkl:>8.1f}  {apw:>9.1f}  {atw:>9.1f}")


if __name__ == "__main__":
    main()
