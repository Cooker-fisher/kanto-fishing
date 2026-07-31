# GSC 手動インデックス登録の進捗（T49・2026-07-31 開始）

対象は GSC「検出 - インデックス未登録」122件（2026-07-24 スナップショット）。
全件が `前回のクロール: 該当なし`（一度もクロールされていない）で、
うち **118件は実在・indexable・sitemap 掲載済み**。残り4件は ship の noindex で対象外。

**投入ルール**: GSC の「インデックス登録をリクエスト」は 1日 約10〜12本が上限。
**ハブ優先**（`x_post/` が入れば配下の日次ページ、`forecast/` `monthly/` `column/` も同様に下流が拾われる）。
旧・日本語 slug の 404（84本）は恒久 404 が正しいので投入しない。

---

## 2026-07-31 投入済み（15本・すべて「優先クロール キューに追加しました」を確認）

ハブ:
- [x] `x_post/`
- [x] `forecast/`
- [x] `calendar.html`
- [x] `column/`
- [x] `monthly/`
- [x] `pages/privacy.html`
- [x] `pages/faq.html`

魚種:
- [x] `fish/kawahagi.html`
- [x] `fish/kasago.html`
- [x] `fish/saba.html`
- [x] `fish/kinmedai.html`
- [x] `fish/amadai.html`
- [x] `fish/magochi.html`

個別:
- [x] `monthly/2026-06/tachiuo.html`
- [x] `x_post/2026-07-23.html`

### 投入不要と判明
- `x_post/2026-07-22.html` — 検査したら **既にインデックス登録済み**。
  122件リストは 2026-07-24 時点のスナップショットなので、一部は既に自然解消している。
  **投入前に URL 検査で現況を確認すること**（登録済みなら枠を消費しない）。

---

## 未投入（次回以降・優先度順）

### 1. 残りの fish/（14本）
`itoyori` / `kaiwari` / `kanko` / `mahata` / `mebaru` / `medai` / `mejina` /
`sawara` / `soi` / `surumeika` / `takabe` / `umazurahagi` / `umeiro` / `fugu`

### 2. area/（16本）
`edogawa` / `hiratsuka` / `katsuura-kawazu` / `koshiba` / `kotsubo` / `kurihama` /
`matsuwa-ena` / `matsuwa-maguchi` / `nagai` / `oiso` / `omaezaki` / `onjuku-iwawada` /
`otsu` / `tomiura` / `urayasu` / `yokohama-shinyamashita`

### 3. fish_area/（21本）
`aji-kashima` / `anago-urayasu` / `hata-kashima` / `hirame-hitachi-kuji` / `hirame-katakai` /
`kasago-katakai` / `kurodai-matsuwa-ena` / `madai-matsuwa-ena` / `madai-sajima` /
`madako-hachimanbashi` / `madako-nakaminato` / `madako-rokugo-suimon` / `madako-yokohama-honmoku` /
`mahata-ohara` / `maruika-koajiro` / `mugiika-numazu-naiko` / `mugiika-numazu-shizuura` /
`saba-omaezaki` / `saba-sajima` / `shousaifugu-ohara` / `soi-kashima` / `warasa-hitachi-kuji`

### 4. ship/（32本）
`arakawaya` / `daihachi-koumatsu-maru` / `dairoku-ryuei-maru` / `eisho-maru` / `gunji-maru` /
`hamashin-maru` / `hara-maru` / `haruhisa-maru` / `hide-maru` / `hiiragi-maru` / `kiheiji-maru` /
`koei-maru` / `konaya-maru` / `kuni-maru-oiso` / `kuroichi-maru` / `miyoshi-maru-2` /
`muramasa-maru` / `ryusho-maru-iioka` / `saemu-maru` / `sakuei-maru` / `sensho-maru` /
`seto-maru` / `shinei-maru-emi` / `shinei-maru` / `tomihachi-maru` / `tsuru-maru` /
`watanabe-tsuribuneten` / `yamasen-maru` / `yasuda-maru-aihama` / `yosei-maru` /
`yoshikyu` / `yoshinoya`

※ `bentenya` / `kazuhiko-maru` / `ryuichi-maru-kawana` / `shihei-maru` の4本は
**noindex（意図通り）なので投入しない**。

### 5. x_post/ 日次（19本・最も優先度低い）
ハブ `x_post/` を投入済みなので下流は自然に拾われる見込み。
1週間後に GSC を再確認し、拾われていなければ個別投入する。
`2026-05-07/10/13/15/16/18/19` `2026-06-07/20` `2026-07-07/09/10/12/13/15/17/19/21`
（`2026-07-22` は登録済み・`2026-07-23` は投入済み）

---

## 効果測定

- 投入から **1〜2週間後** に GSC「ページ」→「検出 - インデックス未登録」の件数を確認。
  122 → 減っていれば効いている。
- あわせて「見つかりませんでした（404）」287件の推移も見る。
  T49（孤児の noindex 墓標化）が効いていれば **新規 404 が増えなくなる**はず。
- 「クロール済み - インデックス未登録」（現在 23件）が急増した場合は、
  クロールは通ったが品質で弾かれた＝別の問題なので E-E-A-T 側の施策に戻る。
