#!/usr/bin/env python3
"""
全魚種コンボ深掘り分析を並列実行するランチャー

Usage:
  python analysis/V2/methods/run_full_deepdive.py                   # 全55種 workers=4
  python analysis/V2/methods/run_full_deepdive.py アジ カワハギ      # 指定魚種のみ
  python analysis/V2/methods/run_full_deepdive.py --workers 6        # 並列数指定
  python analysis/V2/methods/run_full_deepdive.py --workers 1        # 逐次実行（デバッグ用）

[並列化の仕組み]
  ThreadPoolExecutor で N 個の subprocess を同時に走らせる。
  analysis.sqlite への書き込みは combo_deep_dive.py 側で WAL モード + timeout=30s に対応済み。
  SQLite WAL により複数プロセスの同時書き込みが安全にシリアライズされる。

[workers 推奨値]
  ローカル(SSD): 4〜6
  GitHub Actions (2CPU): 2〜3
  I/O バウンド（HDD）: 2
"""
import argparse
import concurrent.futures
import os
import subprocess
import sys
import time

ROOT   = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "combo_deep_dive.py")

ALL_FISH = [
    "マダイ","アジ","クロダイ","ヒラメ","タイ五目","タチウオ","マルイカ","カワハギ",
    "アマダイ","マダコ","シロギス","ワラサ","イサキ","フグ","ヤリイカ","アオリイカ",
    "サワラ","スルメイカ","キハダマグロ","マハタ","イナダ","カサゴ","カツオ","シーバス",
    "キンメダイ","ハタ","ムギイカ","アカムツ","シマアジ","カンパチ","シイラ","トラフグ",
    "ビシアジ","ショウサイフグ","アカメフグ","カマス","スジイカ","マゴチ","クロムツ",
    "ヒラマサ","メバル","コハダ","スミイカ","シロアマダイ","ブリ","オニカサゴ","メダイ",
    "キメジ","カレイ","メヌケ","アラ","モンゴウイカ","イシダイ","モロコ","ホウボウ"
]

def _run_one(fish: str) -> tuple[str, int, float, str]:
    """1魚種を subprocess で実行。(fish, returncode, elapsed_sec, stderr) を返す。"""
    t0 = time.time()
    r = subprocess.run(
        [sys.executable, SCRIPT, "--fish", fish],
        capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    return fish, r.returncode, time.time() - t0, r.stderr


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("fish_list", nargs="*", help="魚種名（省略で全55種）")
    parser.add_argument("--workers", type=int, default=4,
                        help="並列ワーカー数（default: 4）")
    args = parser.parse_args()

    fish_list = args.fish_list if args.fish_list else ALL_FISH
    workers   = args.workers

    print(f"対象: {len(fish_list)}種 先頭3: {fish_list[:3]} workers={workers}")

    ok: list[str] = []
    ng: list[str] = []
    t0 = time.time()
    done = 0

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        future_to_fish = {executor.submit(_run_one, fish): fish for fish in fish_list}

        for future in concurrent.futures.as_completed(future_to_fish):
            done += 1
            fish, returncode, elapsed, stderr = future.result()
            tag = f"[{done}/{len(fish_list)}]"

            if returncode == 0:
                ok.append(fish)
                print(f"{tag} {fish} OK ({elapsed:.0f}s)")
            else:
                ng.append(fish)
                last_lines = [l for l in stderr.splitlines() if l.strip()]
                err_msg = last_lines[-1] if last_lines else "（エラー詳細なし）"
                print(f"{tag} {fish} NG ({elapsed:.0f}s)  ERROR: {err_msg}")

    total = time.time() - t0
    mins, secs = divmod(int(total), 60)
    print(f"\n完了: {len(ok)}/{len(fish_list)} OK  NG={ng}  所要時間 {mins}m{secs:02d}s")
    if ng:
        print("NG魚種を再実行するには:")
        print(f"  python {os.path.relpath(SCRIPT)} " + " ".join(ng))
    return 0 if not ng else 1


if __name__ == "__main__":
    sys.exit(main())
