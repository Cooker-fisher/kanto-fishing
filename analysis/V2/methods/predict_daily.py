#!/usr/bin/env python3
"""
predict_daily.py — D層 日次予測ドライバー（GitHub Actions / クラウド実行）

predict_count.py（蒸留 DB 自動フォールバック対応）を使って、明日〜7日先の日別 +
2/3/4週後の週次アンカー日の全コンボ予測を生成し、E層が読む JSON と的中検証用の
予測ログを書き出す。

設計（90_決定ログ.md 2026-06-10「D層無料公開の確定仕様」）:
- 予測単位 = 魚種×船宿（モデルのネイティブ粒度）。エリア合成はしない。
- 表示は min〜max の2値のみ（cnt_lo/cnt_hi）。avg は出さない（補遺3）。
  cnt_predicted はミッドレンジ由来の内部アンカー値であり JSON にも出さない
  （E層が誤って表示する事故を構造的に防ぐ）。
- H=1..7 は日別（全因子）/ H=14,21,28 は週次傾向（FAST 因子は predict_count 側の
  FAST_MAX_H=7 フィルタで自動除外・実質 SLOW+潮汐のみ）。
- 蒸留 DB（predict_params.sqlite）が無い間は mode="unavailable" を書いて正常終了
  （exit 0）。crawl.yml に組み込んでも Phase 2 エクスポート前に CI を壊さない。

predict_log.jsonl の運用（リポジトリ肥大対策・2026-06-10）:
- predict_count 内部の詳細ログ（_apply_wx_correction ごと・補正内訳つき）は
  日次全コンボ×11日付では1日1万行超になるため本ドライバー実行中は抑制する。
- 的中検証に必要な H=1（前日予測）と H=7（1週間前予測）のみ、コンパクト形式で追記:
    {"d":"2026/06/17","h":7,"f":"アジ","s":"こなや丸","lo":5.0,"hi":45.0,"st":3,"kst":null,"rel":1}
- 60日より古い行は毎回プルーニング（旧形式 "ts" 行も対象）。長期の的中集計は
  E層表示時に data/V2 CSV と突合して計算する（生ログの永久保持はしない）。

使い方:
  python analysis/V2/methods/predict_daily.py            # 全ホライズン
  python analysis/V2/methods/predict_daily.py --max-h 7  # H=1..7 のみ（テスト用）
"""

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timedelta

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _paths import RESULTS_DIR

import predict_count  # DB_PATH は import 時に analysis.sqlite → predict_params.sqlite へ自動解決

OUT_JSON = os.path.join(RESULTS_DIR, "forecast_daily.json")
LOG_PATH = os.path.join(RESULTS_DIR, "predict_log.jsonl")
# T47a: 公開ティア（crawl/build_open_tier.py がローカル蒸留・コミット対象）
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(RESULTS_DIR)))
OPEN_TIER_JSON = os.path.join(_REPO_ROOT, "normalize", "open_tier.json")

# 日別 H=1..7 + 週次アンカー H=14/21/28（コンセプト「1週間日別 + 2/3/4週後予想」）
DAILY_HORIZONS = list(range(1, 8))
WEEKLY_HORIZONS = [14, 21, 28]

# 的中検証ログに残すホライズン（H=1: 前日予測 / H=7: 1週間前予測）
LOGGED_HORIZONS = {1, 7}
# predict_log.jsonl のローリング保持日数
LOG_RETENTION_DAYS = 60


def _load_range_quality(conn) -> dict:
    """combo_range_backtest から cnt の的中品質（E層ゲーティング用）を引く。
    戻り値: {(fish, ship): {"promise_break": float, "winkler": float, "n": int}}
    テーブルが無い場合は空 dict（ゲーティングなし）。
    """
    try:
        rows = conn.execute(
            "SELECT fish, ship, promise_break_rate, winkler, n "
            "FROM combo_range_backtest WHERE metric='cnt' AND horizon=0"
        ).fetchall()
    except Exception:
        return {}
    return {(f, s): {"promise_break": pb, "winkler": w, "n": n}
            for f, s, pb, w, n in rows}


def _load_open_tier() -> dict | None:
    """normalize/open_tier.json を読む。無ければ None（選別なし＝従来挙動）。
    戻り値: {"fish|ship": {"tier": "A"|"star"|"none", ...}}"""
    try:
        with open(OPEN_TIER_JSON, encoding="utf-8") as f:
            return json.load(f).get("tiers") or None
    except Exception:
        return None


def _line_date(obj: dict) -> str:
    """ログ行から日付（YYYY-MM-DD）を取り出す。新形式 "d"（YYYY/MM/DD）と
    旧形式 "ts"（ISO）の両対応。判定不能は空文字（=プルーニング対象）。"""
    d = obj.get("d") or ""
    if d:
        return d.replace("/", "-")[:10]
    ts = obj.get("ts") or obj.get("logged_at") or ""
    return ts[:10].replace("/", "-")


def _prune_predict_log(cutoff_date: str) -> tuple[int, int]:
    """predict_log.jsonl から cutoff_date（YYYY-MM-DD）より古い行を削除。
    一時ファイル + os.replace でアトミックに差し替える（書き込み途中クラッシュでの
    全ログ消失防止・code-reviewer MAJOR 指摘対応 2026-06-10）。
    戻り値: (保持行数, 削除行数)"""
    if not os.path.exists(LOG_PATH):
        return (0, 0)
    kept, dropped = [], 0
    with open(LOG_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
            except Exception:
                dropped += 1
                continue
            if _line_date(obj) >= cutoff_date:
                kept.append(line)
            else:
                dropped += 1
    if dropped == 0:
        return (len(kept), 0)  # 変更なし → 書き換えない
    tmp_path = LOG_PATH + ".tmp"  # *.tmp は gitignore 済み・os.replace で消える
    with open(tmp_path, "w", encoding="utf-8") as f:
        if kept:
            f.write("\n".join(kept) + "\n")
    os.replace(tmp_path, LOG_PATH)
    return (len(kept), dropped)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-h", type=int, default=28,
                    help="最大ホライズン（テスト時の短縮用・デフォルト28）")
    args = ap.parse_args()

    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if not os.path.exists(predict_count.DB_PATH):
        # Phase 2 エクスポート前（蒸留 DB 未コミット）: 正常終了で CI を通す
        payload = {"generated_at": generated_at, "mode": "unavailable",
                   "note": "predict_params.sqlite 未生成（build_predict_params.py のローカル実行待ち）",
                   "days": []}
        with open(OUT_JSON, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=1)
        print("[predict_daily] パラメータ DB なし → mode=unavailable を出力（正常終了）")
        return

    # predict_count 内部の詳細ログを抑制（日次全コンボでは1日1万行超・リポジトリ肥大の主因）
    predict_count._log_predict = lambda entry: None

    # mode 判定（export_meta があれば distilled、analysis.sqlite 直ならローカルフル）
    mode = "local_full"
    exported_at = None
    try:
        _c = sqlite3.connect(predict_count.DB_PATH)
        meta = dict(_c.execute("SELECT key, value FROM export_meta").fetchall())
        mode = f"distilled_{meta.get('mode', 'unknown')}"
        exported_at = meta.get("exported_at")
        _c.close()
    except Exception:
        pass

    conn_q = sqlite3.connect(predict_count.DB_PATH)
    range_quality = _load_range_quality(conn_q)
    conn_q.close()

    # T47a 公開ティア: tier A のみ匹数レンジを JSON に出す。star は★のみ。
    # 的中検証ログ（predict_log.jsonl・非公開）は選別に関係なく生値を残す。
    open_tier = _load_open_tier()
    if open_tier is None:
        print("[predict_daily] open_tier.json なし → レンジ選別なし（従来挙動）")

    horizons = [h for h in DAILY_HORIZONS + WEEKLY_HORIZONS if h <= args.max_h]
    today = datetime.today()
    days_out = []
    log_lines = []

    for h in horizons:
        target = (today + timedelta(days=h)).strftime("%Y/%m/%d")
        results = predict_count.predict_all(target_date=target, min_stars=1)
        combos_out = []
        for r in results:
            f, s = r["fish"], r["ship"]
            rq = range_quality.get((f, s), {})
            kaiyu = r.get("kaiyu_stars")  # {"stars","hit_rate","good_line"} or None
            # T47a 選別: レンジ（cnt_lo/hi）を出せるのは tier A のみ。
            # KAIYU★一本化: kaiyu_stars があるコンボ（非昇格回遊魚）はレンジを出さない。
            # T47b: 週次ホライズン（H>=14）は weekly_ok（H=14/21/28 でも pb 基準クリア）必須
            #       — tier A の H=0 実績を無検証で週次に外挿しない（domain レビュー指摘）。
            _entry = (open_tier.get(f"{f}|{s}", {}) if open_tier is not None else None)
            _tier = _entry.get("tier", "none") if _entry is not None else None
            _show_range = (kaiyu is None) and (_tier in ("A", None))
            if _show_range and h >= 14 and _entry is not None:
                _show_range = bool(_entry.get("weekly_ok"))
            combos_out.append({
                "fish": f,
                "ship": s,
                "cnt_lo": r.get("cnt_lo") if _show_range else None,
                "cnt_hi": r.get("cnt_hi") if _show_range else None,
                "stars": r.get("stars"),
                "kaiyu_stars": kaiyu,               # 回遊魚チャンス評価（None=通常魚 or good_line≤3）
                "tier": _tier,                      # T47a: "A"=レンジ公開可 / "star" / "none" / None=選別なし
                "predicted_point": r.get("predicted_point"),
                "model_reliable": bool(r.get("model_reliable")),
                "transition_risk": r.get("transition_risk"),
                "wx_source": r.get("wx_source"),
                "range_quality": rq or None,        # E層ゲーティング用（winkler 極端→数レンジ非表示）
            })
            if h in LOGGED_HORIZONS:
                log_lines.append(json.dumps({
                    "d": target,                    # 予測対象日
                    "h": h,
                    "f": f,
                    "s": s,
                    "lo": r.get("cnt_lo"),
                    "hi": r.get("cnt_hi"),
                    "st": r.get("stars"),
                    "kst": kaiyu.get("stars") if kaiyu else None,
                    "rel": 1 if r.get("model_reliable") else 0,
                }, ensure_ascii=False))
        days_out.append({
            "target_date": target,
            "horizon": h,
            "kind": "daily" if h <= 7 else "weekly",
            "n_combos": len(combos_out),
            "combos": combos_out,
        })
        print(f"[predict_daily] H={h:>2} {target}: {len(combos_out)} コンボ")

    payload = {
        "generated_at": generated_at,
        "mode": mode,
        "params_exported_at": exported_at,
        "open_tier": "active" if open_tier is not None else "missing",
        "days": days_out,
    }
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)

    # 的中検証用ログ: プルーニング → 追記
    cutoff = (today - timedelta(days=LOG_RETENTION_DAYS)).strftime("%Y-%m-%d")
    kept, dropped = _prune_predict_log(cutoff)
    if log_lines:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write("\n".join(log_lines) + "\n")

    total = sum(d["n_combos"] for d in days_out)
    print(f"[predict_daily] 完了: {len(days_out)} 日付 × 計{total} 予測 → {OUT_JSON}")
    print(f"[predict_daily] predict_log: 追記{len(log_lines)}行 / 保持{kept}行 / プルーニング{dropped}行（{LOG_RETENTION_DAYS}日超）")


if __name__ == "__main__":
    main()
