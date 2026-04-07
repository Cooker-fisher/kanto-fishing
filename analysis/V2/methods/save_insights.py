#!/usr/bin/env python3
"""
save_insights.py — 分析結果を analysis.sqlite に蓄積する

[テーブル]
  combo_correlations  : コンボ × 海況因子 の相関係数（自動更新）
  combo_compounds     : コンボ × 複合条件 の効果量（自動更新）
  delta_correlations  : 魚種 × 前週差分因子 の相関（自動更新）
  cooccurrence        : 魚種間共起行列（自動更新）
  combo_notes         : コンボへの手動メモ（蓄積・削除なし）

[使い方]
  python save_insights.py              # analysis_combos.py の結果をDBに保存
  python save_insights.py --query アジ # アジの全知見を表示
  python save_insights.py --note "アジ" "庄治郎丸" "夕マズメに特に釣れる傾向"
"""

import csv, json, os, re, sqlite3, sys
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH  = os.path.join(BASE_DIR, "analysis.sqlite")
REPORT   = os.path.join(BASE_DIR, "analysis_report.txt")
SUMMARY  = os.path.join(BASE_DIR, "analysis_summary.csv")
COOCCUR  = os.path.join(BASE_DIR, "fish_cooccurrence.csv")
ENRICHED = os.path.join(BASE_DIR, "enriched_catches.csv")

# ── DB 初期化 ──────────────────────────────────────────────────────────────
def init_db(conn):
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS combo_correlations (
        fish       TEXT,
        ship       TEXT,
        factor     TEXT,
        r          REAL,
        p          REAL,
        n          INTEGER,
        label      TEXT,
        updated_at TEXT,
        PRIMARY KEY (fish, ship, factor)
    );
    CREATE TABLE IF NOT EXISTS combo_compounds (
        fish       TEXT,
        ship       TEXT,
        condition  TEXT,
        mean_in    REAL,
        mean_out   REAL,
        pct_diff   REAL,
        n_in       INTEGER,
        updated_at TEXT,
        PRIMARY KEY (fish, ship, condition)
    );
    CREATE TABLE IF NOT EXISTS delta_correlations (
        fish       TEXT,
        factor     TEXT,
        r          REAL,
        p          REAL,
        n          INTEGER,
        updated_at TEXT,
        PRIMARY KEY (fish, factor)
    );
    CREATE TABLE IF NOT EXISTS cooccurrence (
        fish1      TEXT,
        fish2      TEXT,
        r          REAL,
        updated_at TEXT,
        PRIMARY KEY (fish1, fish2)
    );
    CREATE TABLE IF NOT EXISTS combo_notes (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        fish       TEXT,
        ship       TEXT,
        note       TEXT,
        created_at TEXT
    );
    CREATE TABLE IF NOT EXISTS combo_meta (
        fish       TEXT,
        ship       TEXT,
        n_records  INTEGER,
        avg_cnt    REAL,
        lat        REAL,
        lon        REAL,
        updated_at TEXT,
        PRIMARY KEY (fish, ship)
    );
    CREATE INDEX IF NOT EXISTS idx_corr_fish   ON combo_correlations (fish);
    CREATE INDEX IF NOT EXISTS idx_corr_factor ON combo_correlations (factor);
    CREATE INDEX IF NOT EXISTS idx_delta_fish  ON delta_correlations (fish);
    CREATE INDEX IF NOT EXISTS idx_notes_fish  ON combo_notes (fish);
    """)
    conn.commit()


# ── レポートパーサ ─────────────────────────────────────────────────────────
def parse_report(path):
    """analysis_report.txt を読んでコンボ別データを抽出する。"""
    combos = {}       # (fish, ship) → {corr: [], compound: [], n, avg_cnt, lat, lon}
    delta  = {}       # fish → {factor: (r, p, n)}
    cooccur_lines = []
    state  = None
    cur_combo = None

    with open(path, encoding="utf-8") as f:
        lines = f.readlines()

    i = 0
    while i < len(lines):
        line = lines[i].rstrip()

        # コンボヘッダ
        m = re.match(r"=== (.+?) × (.+?) ===", line)
        if m:
            fish, ship = m.group(1).strip(), m.group(2).strip()
            cur_combo = (fish, ship)
            combos.setdefault(cur_combo, {"corr": [], "compound": [], "n": 0, "avg_cnt": 0, "lat": None, "lon": None})
            # 次行: 件数
            if i + 1 < len(lines):
                m2 = re.search(r"件数: (\d+)行 / 平均cnt_avg: ([\d.]+)", lines[i+1])
                if m2:
                    combos[cur_combo]["n"]       = int(m2.group(1))
                    combos[cur_combo]["avg_cnt"] = float(m2.group(2))
            # 次次行: 座標
            if i + 2 < len(lines):
                m3 = re.search(r"lat=([\d.]+), lon=([\d.]+)", lines[i+2])
                if m3:
                    combos[cur_combo]["lat"] = float(m3.group(1))
                    combos[cur_combo]["lon"] = float(m3.group(2))
            state = "combo"
            i += 1
            continue

        # 相関行
        if cur_combo and state == "combo":
            m = re.match(r"\s+(.+?)\s+r=([+-][\d.]+)\s+p=([\d.]+)\s+(\S+)\s+n=(\d+)", line)
            if m:
                label  = m.group(1).strip()
                r_val  = float(m.group(2))
                p_val  = float(m.group(3))
                n_val  = int(m.group(5))
                combos[cur_combo]["corr"].append({
                    "label": label, "r": r_val, "p": p_val, "n": n_val
                })

        # 複合効果行
        if cur_combo and state == "combo":
            m = re.match(r"\s+(.+?)\s*:\s*([\d.]+)匹 vs 通常([\d.]+)匹 → ([+-]\d+)%\s+\(n=(\d+)\)", line)
            if m:
                combos[cur_combo]["compound"].append({
                    "condition": m.group(1).strip(),
                    "mean_in":   float(m.group(2)),
                    "mean_out":  float(m.group(3)),
                    "pct_diff":  float(m.group(4)),
                    "n_in":      int(m.group(5)),
                })

        # デルタ相関行
        if "海況変化トレンド" in line:
            state = "delta"
            i += 1
            continue
        if state == "delta" and line.startswith("  ") and ":" in line:
            parts = line.split(":", 1)
            fish_name = parts[0].strip()
            for kv in re.findall(r"(d_\w+)=([+-][\d.]+)\(([*-]+)\)", parts[1]):
                factor, r_str, star = kv
                r_val = float(r_str)
                p_est = 0.001 if "***" in star else (0.01 if "**" in star else (0.05 if "*" in star else 0.2))
                delta.setdefault(fish_name, {})[factor] = (r_val, p_est)
            i += 1
            continue

        i += 1

    return combos, delta


def parse_cooccurrence(path):
    """fish_cooccurrence.csv を読んで (fish1, fish2, r) のリストを返す。"""
    if not os.path.exists(path):
        return []
    results = []
    with open(path, encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        header = next(reader)
        fish_list = header[1:]
        for row in reader:
            f1 = row[0]
            for j, r_str in enumerate(row[1:]):
                if r_str:
                    try:
                        results.append((f1, fish_list[j], float(r_str)))
                    except ValueError:
                        pass
    return results


# ── factor名ラベル逆引き ───────────────────────────────────────────────────
LABEL_TO_KEY = {
    "風速(m/s)": "wind_speed",
    "風向(度)": "wind_dir",
    "気温(℃)": "temp",
    "気圧(hPa)": "pressure",
    "天気コード": "weather_code",
    "波高(m)": "wave_height",
    "波周期(s)": "wave_period",
    "波向(度)": "wave_dir",
    "うねり高(m)": "swell_height",
    "うねり周期(s)": "swell_period",
    "水温(℃)": "sst",
    "海流速(km/h)": "current_spd",
    "海流向(度)": "current_dir",
    "潮型(大4〜若1)": "tide_type_n",
    "潮差(cm)": "tide_range",
    "月齢(日)": "moon_age",
    "満潮1時刻(h)": "flood1_t",
    "満潮1水位(cm)": "flood1_cm",
    "干潮1時刻(h)": "ebb1_t",
    "干潮1水位(cm)": "ebb1_cm",
}


# ── DB 書き込み ────────────────────────────────────────────────────────────
def save_to_db(conn, combos, delta, cooccur):
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    # combo_correlations
    corr_rows = []
    for (fish, ship), d in combos.items():
        for c in d["corr"]:
            factor = LABEL_TO_KEY.get(c["label"], c["label"])
            corr_rows.append((fish, ship, factor, c["r"], c["p"], c["n"], c["label"], now))
    conn.executemany(
        "INSERT OR REPLACE INTO combo_correlations VALUES (?,?,?,?,?,?,?,?)",
        corr_rows
    )

    # combo_compounds
    comp_rows = []
    for (fish, ship), d in combos.items():
        for c in d["compound"]:
            comp_rows.append((fish, ship, c["condition"], c["mean_in"], c["mean_out"],
                              c["pct_diff"], c["n_in"], now))
    conn.executemany(
        "INSERT OR REPLACE INTO combo_compounds VALUES (?,?,?,?,?,?,?,?)",
        comp_rows
    )

    # combo_meta
    meta_rows = []
    for (fish, ship), d in combos.items():
        meta_rows.append((fish, ship, d["n"], d["avg_cnt"], d["lat"], d["lon"], now))
    conn.executemany(
        "INSERT OR REPLACE INTO combo_meta VALUES (?,?,?,?,?,?,?)",
        meta_rows
    )

    # delta_correlations
    delta_rows = []
    for fish, factors in delta.items():
        for factor, (r_val, p_val) in factors.items():
            delta_rows.append((fish, factor, r_val, p_val, None, now))
    conn.executemany(
        "INSERT OR REPLACE INTO delta_correlations VALUES (?,?,?,?,?,?)",
        delta_rows
    )

    # cooccurrence
    cooc_rows = [(f1, f2, r, now) for f1, f2, r in cooccur]
    conn.executemany(
        "INSERT OR REPLACE INTO cooccurrence VALUES (?,?,?,?)",
        cooc_rows
    )

    conn.commit()
    print(f"保存: combo_correlations {len(corr_rows)}件 / compound {len(comp_rows)}件 / delta {len(delta_rows)}件 / cooccur {len(cooc_rows)}件")


# ── クエリ表示 ────────────────────────────────────────────────────────────
def query_fish(conn, fish):
    print(f"\n{'='*60}")
    print(f"=== {fish} の全知見 ===")
    print(f"{'='*60}")

    # コンボ一覧
    combos = conn.execute(
        "SELECT ship, n_records, avg_cnt, lat, lon FROM combo_meta WHERE fish=? ORDER BY n_records DESC",
        (fish,)
    ).fetchall()
    if not combos:
        print("コンボなし")
        return

    print(f"\n[コンボ一覧: {len(combos)}船宿]")
    for ship, n, avg, lat, lon in combos:
        loc = f"lat={lat:.2f},lon={lon:.2f}" if lat else "座標なし"
        print(f"  {ship}: {n}件 平均{avg:.1f}匹 ({loc})")

    # 有意な相関トップ（全コンボまとめ）
    print(f"\n[有意な海況相関(|r|>=0.1, p<0.05)]")
    rows = conn.execute("""
        SELECT ship, factor, label, r, p, n
        FROM combo_correlations
        WHERE fish=? AND p < 0.05 AND ABS(r) >= 0.1
        ORDER BY ABS(r) DESC
        LIMIT 30
    """, (fish,)).fetchall()
    if rows:
        for ship, factor, label, r, p, n in rows:
            star = "***" if p < 0.001 else ("** " if p < 0.01 else "*  ")
            print(f"  {ship:<12} {label:<16} r={r:+.3f} p={p:.3f} {star} n={n}")
    else:
        print("  なし")

    # デルタ相関
    print(f"\n[前週比変化トレンド（Δ）]")
    drows = conn.execute(
        "SELECT factor, r, p FROM delta_correlations WHERE fish=? ORDER BY ABS(r) DESC",
        (fish,)
    ).fetchall()
    for factor, r, p in drows:
        star = "***" if p < 0.001 else ("** " if p < 0.01 else "*  ")
        print(f"  {factor:<20} r={r:+.3f} {star}")

    # 複合効果（効果量大きいもの）
    print(f"\n[複合効果(|pct_diff|>=15%, n>=10)]")
    crows = conn.execute("""
        SELECT ship, condition, mean_in, mean_out, pct_diff, n_in
        FROM combo_compounds
        WHERE fish=? AND ABS(pct_diff) >= 15 AND n_in >= 10
        ORDER BY ABS(pct_diff) DESC
        LIMIT 20
    """, (fish,)).fetchall()
    if crows:
        for ship, cond, mean_in, mean_out, pct, n in crows:
            print(f"  {ship:<12} {cond:<30} {mean_in:.1f} vs {mean_out:.1f} → {pct:+.0f}% (n={n})")
    else:
        print("  なし")

    # 共起（相関強いもの）
    print(f"\n[魚種間共起(|r|>=0.2)]")
    orows = conn.execute("""
        SELECT fish2, r FROM cooccurrence WHERE fish1=? AND ABS(r) >= 0.2 ORDER BY r DESC
    """, (fish,)).fetchall()
    for f2, r in orows:
        mark = "↑同調" if r > 0 else "↓逆行"
        print(f"  {f2}: r={r:+.3f} {mark}")

    # メモ
    notes = conn.execute(
        "SELECT ship, note, created_at FROM combo_notes WHERE fish=? ORDER BY created_at",
        (fish,)
    ).fetchall()
    if notes:
        print(f"\n[メモ]")
        for ship, note, ts in notes:
            label = f"× {ship}" if ship else "(全体)"
            print(f"  [{ts}] {label}: {note}")


def add_note(conn, fish, ship, note):
    conn.execute(
        "INSERT INTO combo_notes (fish, ship, note, created_at) VALUES (?,?,?,?)",
        (fish, ship or "", note, datetime.now().strftime("%Y-%m-%d %H:%M"))
    )
    conn.commit()
    print(f"メモ追加: {fish} × {ship} → {note}")


# ── メイン ────────────────────────────────────────────────────────────────
def main():
    args = sys.argv[1:]

    conn = sqlite3.connect(DB_PATH)
    init_db(conn)

    # --note モード
    if args and args[0] == "--note":
        if len(args) < 4:
            print("使い方: python save_insights.py --note <魚種> <船宿> <メモ>")
            return
        add_note(conn, args[1], args[2], args[3])
        conn.close()
        return

    # --query モード
    if args and args[0] == "--query":
        if len(args) < 2:
            # 全魚種一覧
            fish_list = conn.execute(
                "SELECT DISTINCT fish FROM combo_meta ORDER BY fish"
            ).fetchall()
            print("登録済み魚種:", [f[0] for f in fish_list])
        else:
            query_fish(conn, args[1])
        conn.close()
        return

    # デフォルト: 保存モード
    print(f"=== save_insights.py 開始 ===")
    print(f"レポート解析中...")
    combos, delta = parse_report(REPORT)
    print(f"  コンボ: {len(combos)}件")
    print(f"  デルタ魚種: {len(delta)}種")

    cooccur = parse_cooccurrence(COOCCUR)
    print(f"  共起ペア: {len(cooccur)}件")

    save_to_db(conn, combos, delta, cooccur)

    db_size = os.path.getsize(DB_PATH) / 1024
    print(f"analysis.sqlite: {db_size:.0f} KB")
    print(f"\n=== 完了 ===")
    print(f"次のコマンドで検索:")
    print(f"  python save_insights.py --query アジ")
    print(f"  python save_insights.py --note アジ 庄治郎丸 '夕方に釣果UP傾向'")

    conn.close()


if __name__ == "__main__":
    main()
