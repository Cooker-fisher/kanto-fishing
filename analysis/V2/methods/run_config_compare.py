"""
Config A/B/C/D 並列比較実験スクリプト
各Configが別DBに書き込み、全Config完了後に精度を比較する
"""
import subprocess, sys, sqlite3, time, shutil, concurrent.futures
from pathlib import Path

ROOT    = Path(__file__).resolve().parents[3]
SCRIPT  = ROOT / "analysis/V2/methods/run_full_deepdive.py"
DB_BASE = ROOT / "analysis/V2/results/analysis.sqlite"
TMP_DIR = ROOT / "analysis/V2/results/config_compare_tmp"

TEST_FISH = ["マダイ", "カワハギ", "フグ", "アカムツ", "キンメダイ", "イナダ", "サワラ", "アジ", "ヒラメ"]

CONFIGS = {
    "A（現状）":        [],
    "B（CMEMS+）":      ["--max-cmems", "4", "--max-cmems-ocean", "5"],
    "C（B+F14）":       ["--max-factors", "14", "--max-cmems", "4", "--max-cmems-ocean", "5"],
    "D（中間値）":      ["--max-factors", "14", "--max-cmems", "3", "--max-cmems-ocean", "5"],
}

def run_config(label: str, extra: list[str]) -> dict | None:
    db_path = TMP_DIR / f"config_{label[0]}.sqlite"
    # ベースDBをコピー（water_color_daily 等を引き継ぐ）
    shutil.copy2(DB_BASE, db_path)
    cmd = [sys.executable, str(SCRIPT)] + TEST_FISH + ["--workers", "3", "--db", str(db_path)] + extra
    print(f"[{label}] 開始: extra={extra}")
    t0 = time.time()
    ret = subprocess.run(cmd, cwd=str(ROOT), capture_output=False)
    elapsed = time.time() - t0
    if ret.returncode != 0:
        print(f"[{label}] ERROR (終了コード {ret.returncode})")
        return None
    m = get_metrics(str(db_path), TEST_FISH)
    m["elapsed"] = elapsed
    print(f"[{label}] 完了 ({elapsed:.0f}s): wMAPE={m['wMAPE_H0']}% BL2={m['BL2_H0']}% r={m['r_H0']}")
    return m

def get_metrics(db_path: str, fish_list: list[str]) -> dict:
    con = sqlite3.connect(db_path)
    ph  = ",".join("?" * len(fish_list))

    def median(h):
        return con.execute(f"""
            SELECT ROUND(AVG(wmape),1) FROM (
              SELECT wmape, ROW_NUMBER() OVER (ORDER BY wmape) rn, COUNT(*) OVER () cnt
              FROM combo_backtest
              WHERE horizon={h} AND metric='cnt_avg' AND fish IN ({ph})
            ) WHERE rn IN (cnt/2, cnt/2+1)
        """, fish_list).fetchone()[0]

    def bl2(h):
        return con.execute(f"""
            SELECT ROUND(100.0*SUM(CASE WHEN wmape<bl2_wmape THEN 1 ELSE 0 END)/COUNT(*),1)
            FROM combo_backtest
            WHERE horizon={h} AND metric='cnt_avg' AND bl2_wmape IS NOT NULL AND fish IN ({ph})
        """, fish_list).fetchone()[0]

    def oos_r(h):
        return con.execute(f"""
            SELECT ROUND(AVG(r),3) FROM combo_backtest
            WHERE horizon={h} AND metric='cnt_avg' AND fish IN ({ph})
        """, fish_list).fetchone()[0]

    result = {
        "wMAPE_H0": median(0), "BL2_H0": bl2(0), "r_H0": oos_r(0),
        "wMAPE_H7": median(7), "BL2_H7": bl2(7),
    }
    con.close()
    return result

def main():
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    print(f"対象: {len(TEST_FISH)}種 {TEST_FISH}")
    print(f"Config数: {len(CONFIGS)}  各Config workers=3（合計最大12並列）\n")

    results = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(CONFIGS)) as ex:
        futs = {ex.submit(run_config, label, extra): label for label, extra in CONFIGS.items()}
        for fut in concurrent.futures.as_completed(futs):
            label = futs[fut]
            results[label] = fut.result()

    # 比較表（CONFIGS の定義順で表示）
    print("\n" + "="*72)
    print("=== 設定別精度比較 ===")
    print(f"{'Config':<18} {'wMAPE H0':>9} {'diff':>7} {'BL2% H0':>8} {'diff':>7} {'r H0':>7} {'wMAPE H7':>9} {'BL2% H7':>8}")
    print("-"*72)
    baseline = results.get("A（現状）")
    for label in CONFIGS:
        m = results.get(label)
        if m is None:
            print(f"{label:<18}  ERROR")
            continue
        if baseline and label != "A（現状）":
            dw = f"{m['wMAPE_H0']-baseline['wMAPE_H0']:+.1f}pt"
            db = f"{m['BL2_H0']-baseline['BL2_H0']:+.1f}pt"
        else:
            dw = db = "-"
        print(f"{label:<18} {m['wMAPE_H0']:>7}% {dw:>8} {m['BL2_H0']:>6}% {db:>8} {m['r_H0']:>7} {m['wMAPE_H7']:>7}% {m['BL2_H7']:>7}%")
    print("="*72)

if __name__ == "__main__":
    main()
