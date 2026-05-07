# T14: reviewer フィードバック

**作成日**: 2026/05/07
**対象**: `crawler.py` `_heat_score` 修正差分
**判定**: ✅ 承認

## 読了確認

- `design/V2/T14_designer_proposal.md`: 読了
- `crawler.py` git diff: 読了
- `crawl/validate_output.py` 実行結果: 読了（errors=0）
- `docs/index.html` ZONE B 先頭12カード: 読了

## ✅ OK

- diff は `_heat_score` 関数のみ。他の関数への変更なし。
- `score = cnt * ratio * season_mul` への変数分離と `if len(cs) < 5: return score * 0.01` ブロックの2点のみ追加。設計仕様 Section 5「変更後の関数全文」と一字一句一致。
- 関数シグネチャ `_heat_score(fish, cs)` は変更なし。L6001 のソート呼び出し `sorted(fish_summary.items(), key=lambda x: -_heat_score(x[0], x[1]))` も変更なし。
- validate_output.py: errors=0 / warnings=0。12条件全 PASS。

## ⚠ NEEDS REVISION

なし

## 🚨 CRITICAL

なし

## TOP12 確認

ZONE B の fc カード出現順（`<a class="fc"` の順序）と件数は以下のとおり。

| # | 魚種 | 釣果件数 |
|---|------|---------|
| 1 | タチウオ | 24件 |
| 2 | マダイ | 149件 |
| 3 | スルメイカ | 15件 |
| 4 | アジ | 174件 |
| 5 | シロギス | 47件 |
| 6 | マルイカ | 43件 |
| 7 | メダイ | 5件（N=5で境界値・N>=5 のため通常スコア） |
| 8 | イサキ | 17件 |
| 9 | ヤリイカ | 12件 |
| 10 | ワラサ | 25件 |
| 11 | マハタ | 18件 |
| 12 | フグ | 23件 |

全12件が N>=5。カンパチ（N=2件）はリスト末尾（15位相当）に押し下げられており、「魚種別 今日ほかに釣れている魚」サブリストに降格している。指摘のあった逆転バグは解消済み。

**境界値注意事項（指摘のみ、修正不要）**: 7位のメダイが釣果件数=5件で N=5 の閾値ちょうどに該当する。`len(cs) < 5` の条件より N=5 は通常スコア扱いで仕様どおり。仕様に問題があるとは言えないが、今後 N=5 の魚が ratio ブーストを受けて上位に浮上する可能性は残る。現時点では設計仕様が意図した挙動の範囲内。

## validate_output 結果

- errors: 0
- warnings: 0
- 全 12 不変条件 PASS

## 全体判断

diff は設計仕様 Section 5 の全文と完全一致。修正対象は `_heat_score` 関数のみで副作用なし。TOP12 全カードが N>=5 となりカンパチ（N=2）の逆転バグも解消。不変条件への影響もない。**承認**。
