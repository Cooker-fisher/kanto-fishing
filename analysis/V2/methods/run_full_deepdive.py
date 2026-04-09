#!/usr/bin/env python3
"""
全魚種コンボ深掘り分析を順次実行するランチャー
Usage: python analysis/V2/methods/run_full_deepdive.py [--fish アジ カワハギ ...]
       引数なしで全55種実行
"""
import subprocess, sys, time, os

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
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

def main():
    fish_list = sys.argv[1:] if len(sys.argv) > 1 else ALL_FISH
    print(f"対象: {len(fish_list)}種 先頭3: {fish_list[:3]}")
    
    ok = 0; ng = []
    t0 = time.time()
    for i, fish in enumerate(fish_list, 1):
        print(f"[{i}/{len(fish_list)}] {fish} ...", end=" ", flush=True)
        t1 = time.time()
        r = subprocess.run(
            [sys.executable, SCRIPT, "--fish", fish],
            capture_output=True, text=True, encoding="utf-8", errors="replace"
        )
        elapsed = time.time() - t1
        if r.returncode == 0:
            ok += 1
            print(f"OK ({elapsed:.0f}s)")
        else:
            ng.append(fish)
            print(f"NG ({elapsed:.0f}s)")
            last = [l for l in r.stderr.splitlines() if l.strip()]
            if last:
                print(f"  ERROR: {last[-1]}")
    
    total = time.time() - t0
    print(f"\n完了: {ok}/{len(fish_list)} OK, NG={ng}, 所要時間{total:.0f}s")

if __name__ == "__main__":
    main()
