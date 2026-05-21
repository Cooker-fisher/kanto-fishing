# code-reviewer レビュー: T33 Plan v1 (2026-05-21)

判定: **NEEDS_FIX**

CRITICAL: 1件 / MAJOR: 3件 / MINOR: 3件

---

## CRITICAL

### C-1. [CMEMS最適化スキップ] MIN_MONTHS=4 変更後も `_find_best_cmems` 内の MIN_TRAIN_MONTHS_CMEMS=6 がハードコードされたまま

**箇所:** `combo_deep_dive.py:559`

```python
MIN_TRAIN_MONTHS_CMEMS = 6  # full backtest の MIN_MONTHS と揃える
```

Plan §3 Phase 3 は `combo_deep_dive.py:2882` の `MIN_MONTHS = 6 → 4` のみを変更するが、
`_find_best_cmems` 内の `MIN_TRAIN_MONTHS_CMEMS = 6` はモジュールレベルの `MIN_MONTHS` を参照しておらず独立したローカル定数である。

影響:
- MIN_MONTHS=4 で通過したコンボ（月数 4〜5）は `deep_dive()` のバックテストは実行される
- しかし `_find_best_cmems` の LOO-CV ループ内で `len(train_months) < 6` のフォールドが全スキップされ、月数 4〜5 のコンボでは `cmems_wmape` が空になる
- 空の場合 L633 で `return MAX_CMEMS_DEFAULT` にフォールバックするため、これらのコンボは CMEMS 上限が常に 2 固定となり最適化が機能しない
- Plan の「chowari 系 0-factor コンボ 4〜7 件で因子登録」の期待効果が、CMEMS 最適化の不発で減衰する可能性がある

**修正方針:**
L559 を `MIN_TRAIN_MONTHS_CMEMS = MIN_MONTHS` に変更し、モジュールレベルの変数に追随させる。
または `_find_best_cmems(... min_train_months: int = 6)` としてパラメータ化し、呼び出し元 L2921 から `min_train_months=MIN_MONTHS` を渡す。

---

## MAJOR

### M-1. [predict_count.py] DO 因子の予測時取得経路が存在しない

**箇所:** `predict_count.py` 内 `_build_all_wx` 関数（L557〜L621）

`_build_all_wx` は `weather_cache.sqlite`（気象・波高）と `tide_moon.sqlite`（潮汐）のみを参照し、
`cmems_data.sqlite` を一切読まない。`do_surface` / `do_bottom` を取得するコードが存在しない。

訓練側（`combo_deep_dive.py` の `enrich()`）では `conn_cmems` 経由で DO 値を付与している。
予測側では DO=None のまま `_apply_correction_from_params` に渡されるため、
`if all_wx.get(fac) is not None` のガードで DO 項がスキップされる。

結果:
- 訓練時に DO を採用したコンボの `combo_wx_params` に DO の mean/std/r が登録される
- 予測実行時（GitHub Actions 含む）は DO が取れないため気象補正が学習時より弱くなる
- バックテスト評価（ローカル・DO あり）と本番予測（GitHub Actions・DO なし）で系統的なギャップが生じる

Plan §5 リスク2「predict_count.py 側で DO=NULL 時のフォールバックが既存実装で動作するか確認必要」と
記載されているが、実態は「フォールバックがあるのではなく、DO 項が暗黙的にスキップされるだけ」であり、
設計意図と挙動の乖離を明示的に認識・記録する必要がある。

**修正方針（選択肢）:**
A) predict_count.py に CMEMS（月次 SLA/CHL/DO）を GitHub Actions でも参照できる仕組みを追加する（コスト大）
B) DO 因子は「ローカルバックテスト専用指標」と明示し、`combo_wx_params._meta` に `has_do_factor=1` フラグを追加して predict_count.py 側で警告ログを出す（コスト小）
C) DO の `r` が高くても予測時には使えないことを Plan に明記し、wMAPE 改善がバックテスト限定であることをユーザーへ伝達する

最低限 C が必要。実装前にユーザーの了解を取ること。

### M-2. [ハードコード散在] MIN_MONTHS=4 変更が `deep_dive_by_trip` / `deep_dive_by_water_color` のローカル定数 6 に伝播しない

**箇所:**
- `combo_deep_dive.py:5399` `deep_dive_by_trip`: `if len(trip_months) < 6:`
- `combo_deep_dive.py:5400`: `print(f"    [trip_opt] skip ... < 6")`
- `combo_deep_dive.py:5712` `deep_dive_by_water_color`: `if len(cat_months) < 6:`
- `combo_deep_dive.py:5713`: `print(f"    [wc_opt] skip ... < 6")`
- `combo_deep_dive.py:5900` (keyword 最適化): `if len(key_months) < 6:`
- `combo_deep_dive.py:2922`: `if len(months) >= 6:` (CMEMS 最適化 print 分岐)

これらはいずれも `MIN_MONTHS` 変数を参照せず直接 `6` をハードコードしている。
MIN_MONTHS=4 に変更しても trip・water_color・keyword セグメント最適化は月数 4〜5 のコンボをスキップし続ける。

メイン `deep_dive()` が通過するコンボに対してサブ最適化が漏れる不整合が発生する。
chowari 系で月数が 4〜5 のコンボは trip/wc 最適化の恩恵を受けられない。

**修正方針:** 全箇所の `6` を `MIN_MONTHS` への参照に置換する。
または trip/wc/keyword 最適化は意図的に月数要件を緩めないなら、その旨をコメントに明記する。

### M-3. [既存バグ・T33 で新規に壊すわけではないが修正機会] `_apply_factor_caps` の `max_total` 引数が本体で未使用

**箇所:** `combo_deep_dive.py:524〜549`

現在のシグネチャ: `def _apply_factor_caps(factor_r_dict: dict, max_total: int = MAX_FACTORS, max_cmems: int = MAX_CMEMS_DEFAULT, corr_thr: float = 0.10)`

しかし関数本体 L546 では `if len(tier2_selected) >= MAX_TIER2:` とモジュール定数 `MAX_TIER2` を直接参照しており、引数 `max_total` は一切使われない。

CLI の `--max-factors` 引数 (L6310〜6332) は `global MAX_FACTORS` を更新するが、`_apply_factor_caps` 内では `max_total` 経由でなく `MAX_TIER2` を読んでいるため CLI 変更が反映されない。

Plan の `_apply_factor_caps` 改修案でも同じ構造が踏襲されているため、T33 実装時に修正機会として指摘する。

**修正方針:** L546 の `MAX_TIER2` を `max_total` に置き換える（`max_total` を `MAX_TIER2` のデフォルトのまま渡す呼び出し元は変更不要）。

---

## MINOR

### m-1. [件数確認 print なし] 1コンボ動作確認フェーズに DO 採用件数の確認 print が設計されていない

Plan §3 Phase 2 末尾「1コンボ動作確認: アジ×大松丸 (do_surface |r|=0.935)」の確認手順として、
CLAUDE.md 必須ルール「ループ実行前に件数 print」の精神で、採用された DO 因子数を出力する手順が未記載。

**修正方針:** 動作確認時に以下を出力することを手順に追記する。
```
do_adopted = [f for f in final_factor_r if f in DO_FACTORS]
print(f'DO 採用: {len(do_adopted)}件 {do_adopted}')
```

### m-2. [コメント古くなる] `_find_best_cmems` の docstring が DO 独立後に不整合

**箇所:** `combo_deep_dive.py:554〜556`

現在の docstring:「CMEMS上限のコンボ別最適化。0/2/4/6の4パターンを LOO-CV wMAPE で評価し最良を返す。」

DO が CMEMS_FACTORS から独立した後も説明文が変わらない。
**修正方針:** 「CMEMS上限 (DO 除く) のコンボ別最適化」に更新する。

### m-3. [L2922 print 分岐の条件ズレ] MIN_MONTHS=4 後に CMEMS 最適化 print が出ない

**箇所:** `combo_deep_dive.py:2922`

```python
if len(months) >= 6:
    print(f"    [CMEMS最適化] best_cmems={best_cmems} (候補: 0/2/4/6)", flush=True)
```

MIN_MONTHS=4 に変更すると月数 4〜5 のコンボはバックテストを通過するが、
この print が出力されないためデバッグ時に CMEMS 最適化結果が確認できない。

**修正方針:** `if len(months) >= 6:` を `if len(months) >= MIN_MONTHS:` に変更する。

---

## 観点別検証サマリー

| # | レビュー観点 | 結果 | 分類 |
|---|---|---|---|
| 1 | `_apply_factor_caps` の 3 呼び出し箇所と `max_do` 追加必要性 | L582・L3241・L4093 の 3 箇所。デフォルト引数 `max_do=MAX_DO` により L3241・L4093 は自動適用される。L582 は `_find_best_cmems` 内で `min_train_months` 問題と組み合わさり CRITICAL | C-1 |
| 2 | `_find_best_cmems` と DO 採用増の干渉 | DO は CMEMS_FACTORS 外になるため `mc` の評価ループで DO がカウントされず、DO 最適化は `_find_best_cmems` の対象外（設計通り）。ただし `MIN_TRAIN_MONTHS_CMEMS=6` ハードコードで月数 4〜5 コンボの CMEMS 最適化がスキップされる | C-1 |
| 3 | CMEMS_FACTORS から DO 除外の副作用 | ALL_FACTORS・BASE_FACTORS への影響なし。deepwater_score は CMEMS_FACTORS 内に残存。FACTOR_BLACKLIST の既存 2 件は別箇所でチェックされるため影響なし | 副作用なし |
| 4 | MIN_MONTHS=6→4 の他箇所非整合 | `_find_best_cmems:L559`・`deep_dive_by_trip:L5399`・`deep_dive_by_water_color:L5712`・`keyword最適化:L5900` に固定値 6 が残る | C-1・M-2 |
| 5 | DO_FACTORS 他参照箇所への副作用 | なし（FACTOR_BLACKLIST の do_surface は別経路でチェック） | 副作用なし |
| 6 | predict_count.py の DO=NULL フォールバック | フォールバック機構はあるが「スキップされるだけ」。バックテスト精度と本番予測精度の系統的ギャップが発生する | M-1 |

---

## 判定: NEEDS_FIX

- CRITICAL C-1: `MIN_TRAIN_MONTHS_CMEMS=6` ハードコードを `MIN_MONTHS` 参照に変更しないと、Plan の主目的である「chowari 系 0-factor コンボ救済」の CMEMS 最適化が月数 4〜5 コンボで機能しない
- MAJOR M-1: DO 因子のバックテスト改善が本番予測（GitHub Actions）に反映されないことをユーザーが承認した上で実装する必要がある
- MAJOR M-2: `deep_dive_by_trip` / `water_color` のハードコード 6 を MIN_MONTHS 参照に置換しないと MIN_MONTHS 変更の効果が一部サブ最適化に伝播しない

MINOR 3 件は実装時に対応可能。CRITICAL・MAJOR の修正後に再レビュー不要（判定変更なし）。
