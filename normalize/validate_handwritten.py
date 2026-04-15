"""
手書きマスタ検証スクリプト（stdlib のみ）

対象:
  - normalize/fish_tackle.json
  - normalize/area_description.json

検証内容:
  1. スキーマ必須フィールド欠落 / 型
  2. cross-ref lint
     - bycatch[]・major_points[].target[]・representative_targets[]
       が TSURI_MONO_MAP キーに一致
     - area_description.json のトップキーが area_coords.json に存在
  3. 無料/有料境界 deny-list（ゆるめ・2026/04/15 ユーザー決定）
  4. 必須トップキー集合の過不足

終了コード ≠ 0 で違反。pre-commit・T6 ローダーで共用予定。

使い方:
  python3 normalize/validate_handwritten.py
  python3 normalize/validate_handwritten.py --strict  # 警告もエラー扱い
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

# ────────────────────────────────────────────────────────────────
# 定数
# ────────────────────────────────────────────────────────────────

ROOT = Path(__file__).resolve().parent.parent
NORMALIZE_DIR = ROOT / "normalize"
FISH_TACKLE_PATH = NORMALIZE_DIR / "fish_tackle.json"
AREA_DESC_PATH = NORMALIZE_DIR / "area_description.json"
TSURI_MAP_PATH = NORMALIZE_DIR / "tsuri_mono_map_draft.json"
AREA_COORDS_PATH = NORMALIZE_DIR / "area_coords.json"

# T1 確定対象魚種（44 種、n≥100 の 34＋ユーザー指名 10）
EXPECTED_FISH_KEYS = [
    # n 上位 15（プログラマー担当）
    "マダイ", "アジ", "タチウオ", "ヒラメ", "タイ五目",
    "ヤリイカ", "マルイカ", "カワハギ", "アマダイ", "ワラサ",
    "シロギス", "マダコ", "フグ", "イサキ", "サワラ",
    # n 中位 19（調査分析者担当）
    "スルメイカ", "アオリイカ", "イナダ", "クロダイ", "シーバス",
    "キンメダイ", "アカムツ", "カサゴ", "ムギイカ", "カツオ",
    "キハダマグロ", "マハタ", "トラフグ", "カンパチ", "シイラ",
    "ビシアジ", "ショウサイフグ", "アカメフグ", "マゴチ",
    # n 低位 10（ユーザー指名）
    "シマアジ", "ヒラマサ", "クロムツ", "カレイ", "オニカサゴ",
    "メヌケ", "メバル", "カマス", "シロアマダイ", "メダイ",
]

EXPECTED_AREA_KEYS = [
    # 東京湾西（神奈川）
    "走水港", "久里浜港", "久比里港", "松輪江奈港", "金沢八景",
    "小柴港", "横浜本牧港", "横浜港･新山下",
    # 東京湾東（千葉内房）
    "富浦港", "保田港", "金谷港",
    # 外房
    "大原港", "勝浦川津港", "洲崎港",
    # 湘南・相模湾
    "平塚港", "茅ヶ崎港", "小田原早川港",
    # 茨城北
    "大洗港",
]

# 無料/有料境界 deny-list（ゆるめ）
DENY_PATTERNS: list[tuple[str, str]] = [
    (r"★|☆", "星評価（★/☆）は有料境界"),
    (r"\d+\s*%", "%数値は有料境界（平年比・勝率・確率などに相当）"),
    (r"平年比", "「平年比」は有料境界"),
    (r"期待度", "「期待度」は有料境界"),
    (r"MAPE|wMAPE", "精度指標は有料境界"),
    (r"\bprob\b", "probability は有料境界"),
    (r"予測", "「予測」は有料境界"),
    (r"予想", "「予想」は有料境界"),
    (r"見込み", "「見込み」は有料境界"),
    (r"閾値", "「閾値」は有料境界"),
    (r"スコア", "「スコア」は有料境界"),
]

# 席位置キー
SEAT_KEYS = {"dou", "miyoshi", "tomo"}

# ────────────────────────────────────────────────────────────────
# ユーティリティ
# ────────────────────────────────────────────────────────────────


class Reporter:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def err(self, msg: str) -> None:
        self.errors.append(msg)

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)

    def exit_code(self, strict: bool) -> int:
        if self.errors:
            return 1
        if strict and self.warnings:
            return 2
        return 0


def load_json(path: Path, r: Reporter) -> Any:
    if not path.exists():
        r.err(f"{path.name}: ファイルが存在しません")
        return None
    try:
        with path.open(encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        r.err(f"{path.name}: JSON decode error: {e}")
        return None


def walk_strings(node: Any):
    """再帰的に文字列値を yield する"""
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for v in node.values():
            yield from walk_strings(v)
    elif isinstance(node, list):
        for v in node:
            yield from walk_strings(v)


def check_deny(label: str, data: dict, r: Reporter) -> None:
    for text in walk_strings(data):
        for pat, reason in DENY_PATTERNS:
            if re.search(pat, text):
                r.err(f"{label}: deny-list 違反 [{pat}] → {reason} / 該当文: {text[:60]}")


# ────────────────────────────────────────────────────────────────
# fish_tackle.json 検証
# ────────────────────────────────────────────────────────────────


def validate_fish_tackle(data: dict, tsuri_keys: set[str], r: Reporter) -> None:
    label = "fish_tackle.json"

    if not isinstance(data, dict):
        r.err(f"{label}: トップレベルが object ではない")
        return

    actual_keys = set(data.keys())
    expected = set(EXPECTED_FISH_KEYS)

    missing = expected - actual_keys
    extra = actual_keys - expected
    if missing:
        r.err(f"{label}: 必須キー欠落 ({len(missing)}件): {sorted(missing)}")
    if extra:
        r.warn(f"{label}: 予期しないキー ({len(extra)}件): {sorted(extra)}")

    # 各エントリの必須フィールド
    for fish, entry in data.items():
        if entry is None:
            r.warn(f"{label}: '{fish}' は null（stub のまま）")
            continue
        if not isinstance(entry, dict):
            r.err(f"{label}: '{fish}' が dict ではない")
            continue

        # 必須フィールド
        for req in ("method_name", "method_detail", "tackle", "bycatch", "size_typical"):
            if req not in entry or entry[req] in (None, "", []):
                r.err(f"{label}: '{fish}' に {req} がない / 空")

        # tackle: 釣法ごとのマップ {method_name: {rod, rig, bait, ...}}
        tackle = entry.get("tackle") or {}
        if not isinstance(tackle, dict) or not tackle:
            r.err(f"{label}: '{fish}'.tackle が空または dict ではない")
        else:
            for method_key, tset in tackle.items():
                if not isinstance(tset, dict):
                    r.err(f"{label}: '{fish}'.tackle['{method_key}'] が dict ではない")
                    continue
                for req in ("rod", "rig", "bait"):
                    if not tset.get(req):
                        r.err(f"{label}: '{fish}'.tackle['{method_key}'].{req} が空")

        # size_typical 検査
        st = entry.get("size_typical") or {}
        if not st.get("text"):
            r.err(f"{label}: '{fish}'.size_typical.text が空")
        unit = st.get("unit")
        if unit is not None and unit not in ("cm", "kg", "both"):
            r.err(f"{label}: '{fish}'.size_typical.unit 不正: {unit!r}")
        if "min_cm" in st and "max_cm" in st:
            if st["min_cm"] > st["max_cm"]:
                r.err(f"{label}: '{fish}'.size_typical min_cm > max_cm")
        if "min_kg" in st and "max_kg" in st:
            if st["min_kg"] > st["max_kg"]:
                r.err(f"{label}: '{fish}'.size_typical min_kg > max_kg")

        # bycatch cross-ref
        for by in entry.get("bycatch") or []:
            if by not in tsuri_keys:
                r.err(f"{label}: '{fish}'.bycatch に未知の魚種: {by}")

        # seat_tips キー検査
        seat = entry.get("seat_tips")
        if isinstance(seat, dict):
            unknown = set(seat.keys()) - SEAT_KEYS
            if unknown:
                r.err(f"{label}: '{fish}'.seat_tips 不正キー: {sorted(unknown)}")

        # method_detail 長さ
        md = entry.get("method_detail") or ""
        if len(md) < 30:
            r.warn(f"{label}: '{fish}'.method_detail が短い ({len(md)}字・30字以上推奨)")

    # deny-list
    check_deny(label, data, r)


# ────────────────────────────────────────────────────────────────
# area_description.json 検証
# ────────────────────────────────────────────────────────────────


def validate_area_description(
    data: dict, tsuri_keys: set[str], area_keys: set[str], r: Reporter
) -> None:
    label = "area_description.json"

    if not isinstance(data, dict):
        r.err(f"{label}: トップレベルが object ではない")
        return

    actual = set(data.keys())
    expected = set(EXPECTED_AREA_KEYS)

    missing = expected - actual
    extra = actual - expected
    if missing:
        r.err(f"{label}: 必須キー欠落 ({len(missing)}件): {sorted(missing)}")
    if extra:
        r.warn(f"{label}: 予期しないキー ({len(extra)}件): {sorted(extra)}")

    # area_coords.json 整合
    unknown_area = actual - area_keys
    if unknown_area:
        r.err(
            f"{label}: area_coords.json に存在しないキー: {sorted(unknown_area)}"
        )

    for port, entry in data.items():
        if entry is None:
            r.warn(f"{label}: '{port}' は null（stub のまま）")
            continue
        if not isinstance(entry, dict):
            r.err(f"{label}: '{port}' が dict ではない")
            continue

        for req in (
            "display_name", "prefecture", "access", "feature",
            "major_points", "representative_targets", "faq_hints",
        ):
            if req not in entry or entry[req] in (None, "", []):
                r.err(f"{label}: '{port}' に {req} がない / 空")

        # feature 長さ
        feat = entry.get("feature") or ""
        if len(feat) < 60:
            r.warn(f"{label}: '{port}'.feature が短い ({len(feat)}字・60字以上推奨)")

        # major_points[].target cross-ref
        for i, mp in enumerate(entry.get("major_points") or []):
            for t in mp.get("target") or []:
                if t not in tsuri_keys:
                    r.err(
                        f"{label}: '{port}'.major_points[{i}].target 未知: {t}"
                    )

        # representative_targets cross-ref
        for t in entry.get("representative_targets") or []:
            if t not in tsuri_keys:
                r.err(f"{label}: '{port}'.representative_targets 未知: {t}")

        # faq_hints 必須キー
        fh = entry.get("faq_hints") or {}
        for req in ("best_season", "beginner_ok", "typical_price",
                    "sea_condition", "reservation"):
            if not fh.get(req):
                r.err(f"{label}: '{port}'.faq_hints.{req} が空")

    # deny-list
    check_deny(label, data, r)


# ────────────────────────────────────────────────────────────────
# main
# ────────────────────────────────────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(
        description="fish_tackle.json / area_description.json を検証する"
    )
    parser.add_argument(
        "--strict", action="store_true", help="警告もエラー扱い（exit 2）"
    )
    args = parser.parse_args()

    r = Reporter()

    # マスター読み込み
    tsuri_raw = load_json(TSURI_MAP_PATH, r)
    tsuri_keys: set[str] = set()
    if tsuri_raw and isinstance(tsuri_raw, dict):
        tsuri_keys = set(tsuri_raw.get("TSURI_MONO_MAP", {}).keys())

    area_raw = load_json(AREA_COORDS_PATH, r)
    area_keys: set[str] = set(area_raw.keys()) if isinstance(area_raw, dict) else set()

    # 検証対象
    fish_data = load_json(FISH_TACKLE_PATH, r)
    if isinstance(fish_data, dict):
        validate_fish_tackle(fish_data, tsuri_keys, r)

    area_data = load_json(AREA_DESC_PATH, r)
    if isinstance(area_data, dict):
        validate_area_description(area_data, tsuri_keys, area_keys, r)

    # 出力
    print(f"エラー: {len(r.errors)} / 警告: {len(r.warnings)}")
    for m in r.errors:
        print(f"  [ERROR] {m}")
    for m in r.warnings:
        print(f"  [WARN]  {m}")

    code = r.exit_code(args.strict)
    if code == 0:
        print("OK: 検証通過")
    return code


if __name__ == "__main__":
    sys.exit(main())
