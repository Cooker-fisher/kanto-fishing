"""
catches_raw.json の更新を検知して CSV再生成 + 未登録ポイント抽出を行う。
history_crawl_batch.py と並走させる。

使い方:
  python crawl/batch_csv_watcher.py
"""
import sys, os, json, time, re, subprocess, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

RAW_PATH   = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "crawl", "catches_raw.json")
POINT_JSON = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "normalize", "point_coords.json")
ROOT       = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

TARGET_SHIPS = [
    "信栄丸","勇幸丸","浜新丸","三喜丸釣船店","新修丸","米元釣船店","荒川屋","弁天屋",
    "春盛丸","栃木丸","儀兵衛丸","つね丸","太郎丸","棒面丸","平作丸","とうふや丸",
    "小柴丸","大和丸","孝徳丸","美喜丸","洋征丸",
]

_NOT_POINT = re.compile(
    r'航程|沖合|km|ｋｍ|分|時間|ktで|kt|水深|前後|付近|〜|~|以深|以浅|^\d+$'
)

def get_ships_in_raw():
    """catches_raw.json に存在する TARGET_SHIPS の集合を返す"""
    try:
        records = json.load(open(RAW_PATH, encoding='utf-8'))
    except Exception:
        return set()
    return {r.get('ship') for r in records if r.get('ship') in set(TARGET_SHIPS)}

def extract_new_points(ship_name, known_points):
    try:
        records = json.load(open(RAW_PATH, encoding='utf-8'))
    except Exception:
        return []
    candidates = {}
    for r in records:
        if r.get('ship') != ship_name:
            continue
        pt = r.get('point_raw') or ''
        for p in re.split(r'[,、・/／ ]+', pt):
            p = p.strip()
            if len(p) < 2 or len(p) > 15:
                continue
            if _NOT_POINT.search(p):
                continue
            if p not in known_points:
                candidates[p] = candidates.get(p, 0) + 1
    return sorted([(n, c) for n, c in candidates.items() if c >= 3], key=lambda x: -x[1])

def add_points(ship_name, new_pts):
    pc = json.load(open(POINT_JSON, encoding='utf-8'))
    added = 0
    for name, cnt in new_pts:
        if name not in pc:
            pc[name] = {"lat": None, "lon": None, "note": f"auto:{ship_name} n={cnt}"}
            added += 1
    if added:
        json.dump(pc, open(POINT_JSON, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
    return added

def run_export_csv():
    r = subprocess.run([sys.executable, 'crawler.py', '--export-csv'],
                       capture_output=True, cwd=ROOT)
    out = (r.stdout or b'').decode('utf-8', errors='replace')
    err = (r.stderr or b'').decode('utf-8', errors='replace')
    lines = (out + err).strip().split('\n')
    return next((l for l in reversed(lines) if '合計' in l or 'export' in l.lower()), lines[-1] if lines else '?')

def main():
    print(f"=== batch_csv_watcher 起動 ===", flush=True)
    print(f"RAW: {RAW_PATH}", flush=True)

    last_mtime = os.path.getmtime(RAW_PATH) if os.path.exists(RAW_PATH) else 0
    processed  = set()

    # 起動時点で既にrawに入っている船宿を確認
    already = get_ships_in_raw()
    print(f"起動時点でRAWに存在: {sorted(already)}", flush=True)

    while True:
        time.sleep(5)

        if not os.path.exists(RAW_PATH):
            continue

        mtime = os.path.getmtime(RAW_PATH)
        if mtime <= last_mtime:
            continue

        last_mtime = mtime
        current_ships = get_ships_in_raw()
        new_ships = current_ships - processed - already

        if not new_ships:
            # 既存船宿の更新（ページ追加中）→ スキップ
            continue

        for ship_name in sorted(new_ships):
            processed.add(ship_name)
            print(f"\n[完了検出] {ship_name}", flush=True)

            # 未登録ポイント
            pc = json.load(open(POINT_JSON, encoding='utf-8'))
            new_pts = extract_new_points(ship_name, set(pc.keys()))
            if new_pts:
                n = add_points(ship_name, new_pts)
                print(f"  新規ポイント: {[p for p,_ in new_pts[:5]]} → {n}件追加", flush=True)
            else:
                print(f"  新規ポイント: なし", flush=True)

            # CSV更新
            print(f"  CSV更新中...", end=" ", flush=True)
            print(run_export_csv(), flush=True)

        done = len(processed) + len(already)
        print(f"  進捗: {done}/{len(TARGET_SHIPS)}船宿", flush=True)

        if processed | already >= set(TARGET_SHIPS):
            print("\n=== 全21船宿 CSV取込完了 ===", flush=True)
            # 座標未設定ポイント一覧
            pc = json.load(open(POINT_JSON, encoding='utf-8'))
            null_pts = [(n, v.get('note','')) for n, v in pc.items() if v.get('lat') is None]
            if null_pts:
                print(f"座標未設定ポイント ({len(null_pts)}件):", flush=True)
                for n, note in null_pts:
                    print(f"  {n}  [{note}]", flush=True)
            return

if __name__ == "__main__":
    main()
