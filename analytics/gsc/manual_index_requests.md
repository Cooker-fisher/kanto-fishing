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

**2026-08-01 GSC 実績で並べ替え。** 根拠:
- 7月のクリック86のうち **66 (77%) が area/ ページ**（iioka 41・kanaya 16 等）。
  クエリは全て「{港名} 釣果/釣り」型 → **area/ を最優先に繰り上げ**（旧リストは fish/ が先頭だった）
- fish_area/ は shima-aji-ohara が 116表示・6クリックで実績あり → 3番手維持
- ship/ は指名検索の表示実績あり（山大丸51・庄治郎丸33表示）だがクリック0 → 最後
- カテゴリ内は **直近3か月（2026-05〜07）の釣果行数**順（= コンテンツの厚さ = 港の活性）

### 1. area/（16本・最優先）

釣果行数順。1日の投入枠は area から使い切る:

- [x] `matsuwa-ena`（松輪江奈港・1,030行/10隻）✅ 2026-08-02 投入・優先クロールキュー確認
- [x] `hiratsuka`（平塚港・790行）※庄治郎丸(GSC 33表示)の母港 ✅ 2026-08-02 投入
- [x] `omaezaki`（御前崎港・487行）✅ 2026-08-02 投入
- [ ] `urayasu`（浦安・486行）⚠ 2026-08-02 に「割り当て量を超えています」で弾かれた
  （3本目投入後に上限到達。検査済み=検出-未登録は確認済み）。**明日の1本目にする**
  ※教訓: この日は matsuwa-ena で誤操作の重複送信が発生。重複もクォータを消費する
  疑いがあるため、1URL=1回送信を厳守する
- [ ] `kurihama`（久里浜港・253行）
- [ ] `edogawa`（江戸川放水路・217行）
- [ ] `nagai`（長井港・193行）
- [ ] `kotsubo`（小坪港・182行）
- [ ] `yokohama-shinyamashita`（横浜新山下・174行）
- [ ] `matsuwa-maguchi`（松輪間口港・124行）
- [ ] `koshiba`（小柴港・100行）
- [ ] `oiso`（大磯港・92行）
- [ ] `otsu`（大津港・91行）
- [ ] `onjuku-iwawada`（御宿岩和田港・36行）
- [ ] `katsuura-kawazu`（勝浦川津港・31行）
- [ ] `tomiura`（富浦港・11行）

### 2. fish/（14本）

- [ ] `surumeika`（スルメイカ・553行）
- [ ] `mejina`（メジナ・359行）
- [ ] `mebaru`（メバル・336行）
- [ ] `fugu`（フグ・323行）
- [ ] `umazurahagi`（ウマヅラハギ・312行）
- [ ] `medai`（メダイ・268行）
- [ ] `mahata`（マハタ・266行）
- [ ] `itoyori`（イトヨリ・158行）
- [ ] `soi`（ソイ・115行）
- [ ] `kaiwari`（カイワリ・114行）
- [ ] `kanko`（カンコ・94行）
- [ ] `sawara`（サワラ・85行）
- [ ] `umeiro`（ウメイロ・58行）
- [ ] `takabe`（タカベ・49行）

### 3. fish_area/（21本）

上位のみ日付。下位6本（釣果 ≤9行）は薄ページの可能性 → **投入前に中身を見て、
薄ければ投入しない**（クロール済み-未登録行きのリスク・枠の無駄）:

- [ ] `madai-matsuwa-ena`（264行）
- [ ] `maruika-koajiro`（123行）
- [ ] `madako-rokugo-suimon`（79行）
- [ ] `madako-hachimanbashi`（71行）
- [ ] `mahata-ohara`（62行）
- [ ] `anago-urayasu`（50行）
- [ ] `saba-sajima`（49行）
- [ ] `madako-yokohama-honmoku`（47行）
- [ ] `madai-sajima`（43行）
- [ ] `mugiika-numazu-naiko`（41行）
- [ ] `hirame-katakai`（38行）
- [ ] `saba-omaezaki`（37行）
- ~~`mugiika-numazu-shizuura`~~ **投入しない**: 静浦エリア統合（2026-08-01）で
  `mugiika-shizuura` に置き換わり、旧URLは noindex 墓標化される
- [ ] `kurodai-matsuwa-ena`（25行）
- [ ] `madako-nakaminato`（24行）
- [ ] `kasago-katakai`（24行）
- 要中身確認: `shousaifugu-ohara`（9行）/ `hirame-hitachi-kuji`（6行）/
  `warasa-hitachi-kuji`（1行）/ `soi-kashima`（0行）/ `hata-kashima`（0行）/
  `aji-kashima`（0行）

### 4. ship/（32本・最後）

釣果行数順の上位から。下位（≤65行）は自然クロール待ちでも可:

`yasuda-maru-aihama`(612) / `shinei-maru-emi`(407) / `yoshinoya`(312) /
`muramasa-maru`(297) / `ryusho-maru-iioka`(260) / `haruhisa-maru`(191) /
`koei-maru`(178) / `watanabe-tsuribuneten`(174) / `yoshikyu`(174) /
`saemu-maru`(162) / `arakawaya`(150) / `seto-maru`(139) / `kiheiji-maru`(117) /
`yosei-maru`(116) / `tomihachi-maru`(111) / `tsuru-maru`(109) / `eisho-maru`(108) /
`hiiragi-maru`(102) / `hide-maru`(81) / `yamasen-maru`(77) / `shinei-maru`(71) /
`dairoku-ryuei-maru`(68) / `daihachi-koumatsu-maru`(67) / `kuroichi-maru`(67) /
`konaya-maru`(65) / `kuni-maru-oiso`(61) / `hara-maru`(60) / `sakuei-maru`(43) /
`miyoshi-maru-2`(41) / `sensho-maru`(38) / `hamashin-maru`(24) / `gunji-maru`(22)

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
