# コマセ巻きシミュレーター — Handover Document

> **Handing back to Claude design (claude.ai/design)**
> Origin bundle: `https://api.anthropic.com/v1/design/h/wHqXDi3pJVspubM5XZZk-w`
> Current location: `docs/komase-sim/` (in kanto-fishing repo)
> Current version: `?v=32`

---

## 1. Project Overview

東京湾コマセマダイ釣りの **物理シミュレーター**。
当初 Claude design から実装ハンドオフされたプロトタイプを、関東一帯の実釣ノウハウ（サニー商事マニュアル、TSURINEWS、SHIMANO 各記事、DAIWA、oretsuri 等）に合わせ込み、リアルな釣りサイクルを再現できる教材＋設計検証ツールに発展させたもの。

将来は **アジ・シマアジ・イサキ・ワラサ・外房カモシ** など他魚種のコマセ釣り全般に拡張可能な設計基盤。

---

## 2. File Structure

```
docs/komase-sim/
├── index.html           — 紹介ページ（SEO/AdSense 向け静的 HTML）
├── ogp-komase-sim.png   — OGP 画像（ユーザーが別途配置）
├── play/
│   ├── index.html       — Entry. React 18 + Babel standalone + 4 jsx をロード
│   ├── app.jsx          — メインApp、state、animation loop、UI 配置
│   ├── physics.jsx      — 物理シミュ (particles, rig shape, current, tides, optimizer)
│   ├── panels.jsx       — 左右パネル（Slider / Segmented / CollapsibleSection / Recommendation）
│   ├── renderer.jsx     — Canvas 描画 (background, boat, rig, particles, fish, labels, bow minimap)
│   └── styles.css       — 海図風配色 (deep ink + paper + vermilion + brass + moss)
├── MOCKUP-themes.html
├── HANDOVER.md          — このファイル
└── mockups/
```

ビルド不要。`<script type="text/babel" src="...">` で in-browser 変換。
**キャッシュバスト**: `play/index.html` の `<script src="*.jsx?v=N">` を版上げ。

---

## 3. Architecture

### 物理座標系
- `x` = 水平 [m]（潮下流 +）
- `y` = 深さ [m]（海面 = 0）
- 竿先世界 x = **`ROD_X_M = 6`**（船体中心 x=0 から右舷外側へ突き出し位置）
- ビシ静止位置 ≈ `ROD_X_M + pelineDrift(tide, depth, peNo)`

### Phase 状態機械
```
fishing ──[投入]──> dropping ──[着底]──> fishing
fishing ──[仕掛け回収]──> dropping ──[着底]──> fishing
fishing ──[コマセ枯渇]──> dropping (自動回収)
```
着底目標: **`bishi y = tana - (cushion+harris) + 5`**（実釣の「指示ダナ下 5m」= 付けエサ位置）

### Animation Loop (`app.jsx` 内)
1. dt 計算（hidden tab は 250ms interval にフォールバック）
2. 落とし込み進行 / phase 遷移
3. 自動しゃくり判定（auto-shakuri ON 時）
4. pending shakuri (N連発) 処理
5. pending maki 処理 + 自動回収判定
6. うねり位相更新
7. `rigStep` → 横変位の glide
8. 粒子放出（連続漏れ・下窓ベース）
9. `stepParticles` → 落下・拡散・寿命
10. `rigShape` 計算
11. メトリクス更新（hit rate, hook y, ハリス傾斜, 鉛直距離, コマセ雲深度, タナ下流出率）
12. タナ到達検出 → トースト＆フラッシュ
13. Canvas 描画

---

## 4. Parameters

### 環境系（左パネル「海況」）
| param | 範囲 | 単位 | default |
|---|---|---|---|
| depth | 20-100 | m | 50 |
| tanaDepth | 5-(depth-3) | m | 30 |
| tideSpeed | 0-1.2 | m/s | 0.35 |
| tideDepthFactor | 0.1-1.0 | × | 0.5 |
| swellHeight | 0-2.5 | m | 0.5 |
| swellPeriod | 3-12 | s | 6 |

### 仕掛け系
| param | 範囲 | default | source |
|---|---|---|---|
| peNo | 1/1.5/2/3/4 | 3 | TSURINEWS |
| bishiNo | 30-100 step 10 | 80 | DAIWA / 一之瀬丸 |
| **cageUpperOpening** | 0-1.0 | **0.25** | サニー商事マニュアル |
| **cageLowerOpening** | 0-1.0 | **0.10** | サニー商事マニュアル |
| **komaseSize** | M/L/2L/3L | L | ヒロキュー商品 |
| **smokeLevel** | weak/medium/strong | weak | TSURINEWS |
| cushionLength | 0.5-3.0 | 1.0 | 一之瀬丸 / 美喜丸 |
| harrisLength | 3-15 | 8 | 各船宿 |
| harrisNo | 2/3/4/5 | 3 | TSURINEWS |
| hookType | madai/iseama/chinu/gure/mutsu | madai | — |
| hookSize | type依存 | 10 | DAIWA |
| ganDamaPos | chimoto/mid/near-hook | mid | — |
| ganDamaSize | 0-1.5 | 0.2 | g |

### しゃくり系
| param | 範囲 | default | 王道 |
|---|---|---|---|
| shakuriStrokeCm | 30-150 | **80** | 70-80cm |
| shakuriCountPerTrigger | 1-5 | **3** | 2-3 回 |
| makiAmount | 0-3.0 | **1.7** | 1.7m × 3 = 5m |
| dropAmount | 0-2.0 | 0.5 | — |
| shakuriInterval | 10-300 | **30** | 実釣 180s (3分) |
| autoShakuri | bool | **false** | 手動 |
| dropSpeed | 自動 | √(bishiNo/20) | フリー落下 |

---

## 5. Presets

3 グループに分類:

### サイクル
- `default` — 標準 3分サイクル
- `kuripote` — 食い渋り (4-5分)
- `highact` — 活性高 (2-3分)

### 海況
- `trendrun` — 二枚潮
- `fastide` — 速潮

### エリア
- `tokyo_bay` — 東京湾・剣崎 (ビシ80・PE3・ハリス4号10m・上窓25/下窓10%)
- `sagami_std` — 相模湾標準 (ビシ60・PE2)
- `sagami_lt` — 相模湾LT (ビシ40・PE1.5)
- `sagami_deep` — 相模湾深場(冬) (タナ70m・ガン玉0.5g)
- `kamoshi` — 外房カモシ (PE4・煙幕強・粒M・下窓ほぼ全閉)

---

## 6. Optimizer Algorithm

**決定論的ランダム検索 + 多重評価平均**:

```
seed = FNV-1a hash(env + locked)
rng = LCG(seed)
for i in 0..64:
    cand = makeCandidate(env, locked, rng)
    score = mean(simulateHeadless(cand) × 3 runs × 120s sim)
    if score > best: best = cand
return best
```

**スコア式** (`simulateHeadless` 内):
```
score = ratio + absBonus - ohdoPenalty
  ratio    = (near hook particles / total) × 100
  absBonus = min(8, near × 0.08)        # 退化解抑制
  ohdoPenalty = excessStrokes × 1.2
              + max(0, upper - 0.65) × 12
              + max(0, lower - 0.25) × 30   # 下窓開けすぎは厳罰
```

**評価圏**: 付けエサ 1.8m 圏内のコマセ粒子（魚の感知範囲を仮定）
**性能**: 64候補 × 3評価 × 120s = 約 600ms 〜 1s

---

## 7. UI Components

### Left Panel — 5 折りたたみセクション
1. 海況（水深・指示ダナ・潮・うねり）
2. 本線・ビシ（PE・ビシ・上下窓・粒サイズ・煙幕度）
3. クッションゴム・ハリス
4. 針（タイプ・サイズ・ガン玉）
5. しゃくり・巻き（振り幅・回数・巻き・落とし・間隔・自動）

各 Slider/Segmented に **🔒 ロックトグル** — 最適化探索時に固定可。
状態は **localStorage** に永続化。

### Right Panel — 6 セクション
1. プリセット（3グループ × chips コンパクト表示）
2. 自動最適化（ボタン + RecommendationCard）
3. 合否（◎○△× グレード + 待ちヒント + タナ下流出警告）
4. 付けエサ到達率
5. タナ別密度（ヒストグラム、デフォルト closed）
6. 運用ログ（累計しゃくり・粒子・PE鉛直距離・仕掛け鉛直距離・コマセ雲深度・タナ下流出率）

### Controls Bar — 5 グループ × 統一 50px 高
1. 投入 / ↯タナへ即着（落とし込み中）
2. しゃくる（朱） / 巻く（真鍮） / 落とす（苔）
3. 仕掛け回収
4. 一時停止 / リセット
5. 統計（粒子 X/1500、巻き上げ Y.YYm）

### Bow-View Minimap（船上から見た図）
- 右下にドラッグ可能
- **左舷 / 右舷** トグル（クリックで船首向き反転）
- 入水角＋潮流＋判定（凪/標準/警戒/速潮）

### Main Canvas
- 横断面ビュー（船から海底まで）
- 海面波（うねり高さ・周期で振幅変動）
- 船シルエット（うねりで上下動）
- 仕掛け（クッション=朱太線、ハリス=細白線）
- コマセ粒子（朱、煙幕度で透明度＆寿命変動）
- 魚影（マダイ風シルエット 4 匹、漂う）
- ヒートマップ（粒子密度）
- 指示ダナ ±1m 帯（緑）/ 指示ダナ下5m 落とし込み目安
- 鉛直距離表示:
  - **PE鉛直** (竿先↕ビシ) ペーパーホワイト系
  - **仕掛け鉛直** (ビシ↕付けエサ) 朱系
- 落とし込み中バナー / うねり情報

---

## 8. Real-World References (出典)

実釣ノウハウの根拠:

| 項目 | 出典 |
|---|---|
| 東京湾コマセマダイ標準 | [TSURINEWS](https://tsurinews.jp/390414/) |
| しゃくり長さ・回数 | [DAIWA 入門](https://www.daiwa.com/jp/beginner/place/hanadai_isaki_komase) |
| しゃくりノウハウ | [oretsuri](https://oretsuri.com/komase-madai-kowhow) |
| ビシ窓上下の使い分け | [サニー商事マニュアル](https://sany32.com/howto) |
| ビシ80号設定 | [DAIWA 船最前線](https://daiwa-funesaizensen.com/blog-fukuda/2018/12/16/424/) |
| 相模湾深場 | [FuneMaga 平安丸](https://funemaga.com/fishing/25229) |
| 相模湾湘南 | [一俊丸](https://kazutoshimaru.net/1217) |
| 外房カモシ釣り | [信照丸](https://www.bii.ne.jp/~sinsho/tool_kamoshi.html), [DAIWA カモシ](https://daiwa-funesaizensen.com/blog-fukuda/2022/05/25/1527/) |
| カモシ Hira+Madai | [FuneMaga 第二沖合丸](https://funemaga.com/fishing/16668) |
| コマセサイクル | [SHIMANO 大原則](https://fish.shimano.com/ja-JP/content/fishingstyle/article/saho/240628/index.html) |
| アミエビvsオキアミ | [TSURI HACK](https://tsurihack.com/5996) |
| 釣り船一之瀬丸レギュレーション | [いちのせまる](https://www.ichinosemaru.net/page/Detail/regulation/) |
| 美喜丸 仕掛け図 | [松輪 美喜丸](https://matsuwa-mikimaru.com/tackle.php) |

---

## 9. Known Issues / Future Work

### 未対応 / 改善余地
- [ ] **モバイル対応** — `min-width: 1280px` 固定、レスポンシブ未実装
- [ ] **キーボードショートカット** — Space=しゃくる / M=巻く / D=落とす / C=投入 などの提案あり
- [ ] **メインキャンバスのラベル整理** — 左側に密集、右端整列 + リーダーラインで再配置案あり
- [ ] **効果音** — しゃくり・巻き・タナ到達音（オプション）
- [ ] **カモシ釣り本格対応** — サンマミンチの油膜・濁り独立物理、ヒラマサ・ワラサ混じり要素
- [ ] **アジ・シマアジ・イサキ・ワラサ** プリセット&専用パラメータ（コマセ種類別の物性）
- [ ] **Web Worker による並列最適化** — 現状 64×3=192 シミュ直列、~1s
- [ ] **保存可能なカスタムプリセット** — ユーザー設定を localStorage 保存
- [ ] **A/B 比較モード** — 2セットの仕掛けを並列シミュ
- [ ] **釣果ログ CSV 出力**

### 既知の物理近似
- ハリス湾曲は **静的形状** のみ。動的弾性振動は未モデル
- 落とし込み時の lag は近似（実際はビシ速度・水深ごとに変化）
- 潮流は **線形深さプロファイル**。二枚潮はパラメータでフェイク
- 風による船の流し・揺動は未モデル

### 開発上の制約
- React 18 + Babel standalone (no build step) — production では precompile 推奨
- `cushionLength` の物理寄与は **drag 30%** で近似
- カモシのサンマミンチは「煙幕強 + 粒M」で代用、独立した油分・拡散モデルなし

---

## 10. How to Run

### ローカルテスト
```bash
# kanto-fishing リポジトリ直下で
python -m http.server 8000
# 紹介ページ → http://localhost:8000/docs/komase-sim/
# シミュ本体 → http://localhost:8000/docs/komase-sim/play/
```

### 検証ポイント
1. 投入 → ビシが「指示ダナ下5m = 付けエサ位置タナ+5m」まで沈降
2. しゃくる → 上窓からコマセ粒子放出、makiOffset 増加
3. 連続: 付けエサがタナに到達したら「✓ タナ取り完了」トースト＋画面フラッシュ
4. 自動回収条件 = **chum 5% 以下のみ**（巻きすぎでリセットは廃止）
5. おすすめを計算 → 同じ環境で押すたび同じ結果（決定論的）

### キャッシュ更新
`index.html` の `?v=N` を上げる:
```html
<link rel="stylesheet" href="styles.css?v=N" />
<script type="text/babel" src="physics.jsx?v=N"></script>
<script type="text/babel" src="renderer.jsx?v=N"></script>
<script type="text/babel" src="panels.jsx?v=N"></script>
<script type="text/babel" src="app.jsx?v=N"></script>
```

---

## 11. Design Tokens (CSS variables)

```css
--ink:        #0f1a2b    /* 墨 */
--indigo:     #1d3a5f    /* 紺青 */
--sea-deep:   #0b1d33    /* 深海 */
--sea-mid:    #14406a    /* 中層 */
--sea-up:     #2a6b96    /* 表層 */
--seabed:     #4a3a26    /* 海底 */
--paper:      #f3ead7    /* 紙白 */
--paper-dim:  #e7dcc3
--paper-soft: #faf4e4
--vermilion:  #c84427    /* 朱・主アクセント */
--vermilion-soft: #e5a89a
--rust:       #8a3a1c
--moss:       #5d6b3a    /* 苔・補助 */
--lead:       #2b2e34    /* ガン玉・錘 */
--brass:      #9d7a3a
--line:       rgba(243, 234, 215, 0.18)
--line-strong: rgba(243, 234, 215, 0.32)

--serif: "Shippori Mincho", "Noto Serif JP", serif
--sans:  "Noto Sans JP", system-ui, sans-serif
--mono:  "JetBrains Mono", "SF Mono", monospace
```

### 色階層ルール
- **朱 vermilion** = 釣り人の主動作（しゃくる、付けエサ、コマセ粒子）
- **真鍮 brass** = 巻く、固定中、補助アクション
- **苔 moss** = 落とす、ベスト状態のフィードバック
- **紙白 paper** = テキスト、ニュートラル要素、PEライン
- **深藍 ink** = 海中、背景

---

## 12. Iteration History Summary

| Phase | 主な変更 | キー出典 |
|---|---|---|
| 1 (initial) | Claude design ハンドオフ。粒子物理、ヒットレート、ランダム探索 | — |
| 2 | しゃくり cm 化、N連発、落とし込みフェーズ、ロック機能、船首視点 minimap | — |
| 3 | 船デザイン改善＆船首反転、ROD_X_M 導入、ガン玉位置の有効重量モデル | tsurihack, kobacyan, ejinobo |
| 4 | クッションゴム分離、しゃくる/巻く分離、折りたたみ、トースト、鉛直距離表示、左舷/右舷切替 | shimano, daiwa |
| 5 | 王道準拠 (2-3振り、控えめ撒餌)、エリアプリセット、ビシ窓上下分離、粒サイズ、煙幕度 | サニー商事, TSURINEWS, 信照丸 |
| 6 | 最適化決定論化（seeded PRNG + 3回平均評価 + 120s sim） | — |

---

## 13. Acknowledgments

実釣ノウハウは各船宿・釣り具メーカー・釣り情報サイトの公開記事に依拠。すべて出典明記済み（§8 参照）。
本シミュレータは **教育・設計検証目的** であり、実釣リスク（怪我・船酔い・トラブル）は別途現場判断が必要。

---

*Last updated: 2026-05-17 (v=32)*
