# SERP 実査ログ

GSC に出ない2つの事象を追うための、**手動実査の記録場所**。

1. **Google が `<title>` を捨てて `<h1>` を SERP タイトルに使う**現象（不変条件 #68・決定ログ 2026-08-29）
2. **AI回答での自サイト引用** — impression/click に一切出ない露出経路

---

## ⚠ 自動取得はしない

`https://search.yahoo.co.jp/robots.txt` は

```
User-agent: *
Disallow: /search?
```

**検索結果ページの自動取得を明示的に禁止している**（Google も同様）。
スクレイパを書かない。CI にも載せない。**人がブラウザで開いて見た内容だけを記録する。**

そのぶん頻度は上げられないので、**月1回・GSC で impression 上位のクエリ 10〜15本**に絞る。

## なぜ Yahoo!検索を見るのか

Yahoo!検索は Google の検索インデックス供給を受けているため、organic の並びと
タイトル/スニペットの出方が Google と揃う（2026-08-01 の実査でも同じ方法を使った）。

⚠ **AI回答は別物の可能性がある。** Yahoo の「AI回答」が Google の AI Overview と
同一のシステムかは未確認。`ai_answer_cited` は「Yahoo の AI回答で引用されたか」であって、
Google AI Overview での引用を意味しない。ここを混同しないこと。

---

## 手順

1. 対象クエリを決める（`python analytics/serp/report.py --suggest` で GSC 上位を出せる）
2. ブラウザで `https://search.yahoo.co.jp/search?p=<クエリ>` を開く
3. 以下を**見たまま**記録する。分からなかった項目は `null`。推測で埋めない
   - `serp_title` … SERP に出ていたタイトル（末尾の `...` も含めて）
   - `title_source` … ページの `<title>` と一致 → `title` / `<h1>` と一致 → `h1` /
     どちらとも違う → `other` / 1ページ目に不在 → `absent`
   - `serp_date_label` … スニペット先頭の日付表記（`2026/8/18`、`21時間前` 等）。無ければ `null`
   - `snippet_source` … 抜粋元（`faq` / `weekly` / `meta` / `other`）
   - `ai_answer_cited` / `ai_answer_quotes` … AI回答ブロック内の自ドメイン引用
4. `observations.json` の `observations` 配列に追記
5. `python analytics/serp/report.py` で GSC 実績と突き合わせる

## 読み方

`report.py` は `title_source` 別に GSC の CTR を集計する。2026-08-29 の初回実測は

| title_source | ページ | 8月CTR |
|---|---|---|
| title 維持 | 金谷・静浦 | 5.24% / 5.01% |
| h1 差し替え | 飯岡・勝浦・天津 | 2.03% / 1.11% / 0.49% |

順位帯はどれも pos 6.8〜8.2 で揃っており、**n=6 で例外なし**。
ただし **因果は未証明**（低エンゲージメントの結果として Google が title を
信用しなくなった可能性も残る）。観測を重ねて判断する。

## 次の観測

不変条件 #68（H1 に別称+県名）を 2026-08-29 に投入した。Google の再クロールが要るので、
**2026-09-12 以降**に同じ6クエリを再実査し、`title_source` と `serp_title` が
変わったかを見る。変わらない／CTR が動かないなら、次はクロール頻度
（`serp_date_label` の鮮度）側に戻る。
