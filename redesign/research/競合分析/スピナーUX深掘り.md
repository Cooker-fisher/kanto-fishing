# 「分析中...」スピナーUX 深掘りレポート

**作成日**: 2026/04/04
**目的**: 予測サイトで使われる「処理中演出」の効果・設計・実装方針

---

## 1. なぜスピナーが効くのか — 心理学的根拠

### 「労力の可視化」効果 (Labor Illusion)

ハーバード・ビジネス・スクールの研究（Ryan Buell, 2011）で実証済み:

> **裏側で作業が行われていると「見せる」だけで、結果への信頼と満足度が上がる。**
> 即座に結果を出すより、「計算しています...」と待たせた方が結果を高く評価する。

実験: 旅行検索サイトで、同じ結果を(A)即座に表示 vs (B)「航空会社を検索中...」アニメーション付きで15秒待たせてから表示。結果、(B)の方がユーザー満足度が有意に高かった。

**これが競艇AI予想サイトがスピナーを使う理由。** 予測は事前計算済みでも、「AIが分析中...」と3-5秒見せることで知覚価値が上がる。

### 釣り予測への応用

ユーザーが「来週末の予測を見る」をタップした時:
- ❌ 即座に結果表示 → 「ただのテーブルじゃん」
- ✅ 3秒の分析演出 → 「84,757件のデータと気象情報から計算してるんだ」

---

## 2. 成功事例の分析

### A. 競艇AI予想サイト（BOAT ADVISOR等）
- 「AIが最終分析中...」スピナー + プログレスバー
- ステップ表示: ①選手データ読込 → ②水面状況分析 → ③AI予測生成
- 所要時間: 3-5秒（実際は事前計算済み）
- **効果**: 「AIが本当に計算している」感覚を与え、予測の知覚価値UP

### B. netkeiba（AI予想機能）
- 「過去のレースデータを分析しています...」
- 馬のシルエットアイコンが回転するカスタムアニメーション
- 分析完了後に「信頼度 ○○%」がフェードイン
- **効果**: 標準的なスピナーではなく、ドメイン固有のアニメーションで世界観を維持

### C. Apple Weather
- 位置情報取得→気象データ取得→描画の3段階
- 各段階でスケルトンスクリーン（灰色の枠が脈動）
- データが揃うと各カードが順にフェードイン
- **効果**: 「1つずつ丁寧に準備している」感覚

### D. Windy.com
- 地図レイヤー切替時に1-2秒のレンダリングアニメーション
- 気象データの色グラデーションがスムーズに変化
- **効果**: 「膨大な気象データを処理している」感覚

### E. ChatGPT / Claude
- ストリーミング出力（文字が1つずつ表示）
- 「考え中」のドット点滅
- **効果**: 「AIが本当に考えている」感覚。即座に全文表示するより高評価

---

## 3. 最適な演出時間

| 時間 | 印象 | 用途 |
|------|------|------|
| 0.5秒以下 | 嘘くさい | 使わない方がいい |
| 1-2秒 | 軽い処理感 | 単純な切替、フィルタ |
| **3-5秒** | **「ちゃんと計算してる」** | **予測表示（推奨）** |
| 5-8秒 | 重い処理感 | 初回ロード、大量データ |
| 8秒超 | イライラ | 避けるべき |

**funatsuri-yoso.com推奨: 3-4秒**

---

## 4. ステップ型プログレス表示（推奨デザイン）

単純なスピナーよりも、**何を処理しているか段階的に見せる**方が効果的。

### 釣果予測用ステップ設計案

```
[Step 1] 📊 84,757件の釣果データを読み込み中...
         ████████░░░░░░░░ 35%

[Step 2] 🌊 海況データと照合中（波高・水温・潮汐）...
         ██████████████░░ 70%

[Step 3] 🤖 AI予測モデルで来週の釣果を計算中...
         ████████████████ 100%

[完了]   ✅ 分析完了！ → 結果がフェードイン
```

### なぜステップ型が効くか

1. **データ量の可視化**: 「84,757件」という具体的な数字が処理の重みを伝える
2. **専門性の訴求**: 海況データ・AI予測モデルという用語が「ただの統計じゃない」感を出す
3. **プログレスバー**: 進捗が見えるとイライラしない（研究で実証済み）
4. **完了の達成感**: ✅マークとフェードインで「結果が出た」という満足感

---

## 5. funatsuri-yoso.com への具体的実装案

### 5-1. どこで使うか

| 場面 | スピナー | 時間 |
|------|---------|------|
| **有料予測ページ初回表示** | 3ステップ型プログレス | 3-4秒 |
| **日付切替（予測の日を変える）** | 軽いスピナー | 1秒 |
| **「予測を見る」CTA押下** | フルステップ型 | 3-4秒 |
| 魚種カード展開 | なし（即座） | 0秒 |
| テーブルフィルタ | なし（即座） | 0秒 |

### 5-2. HTML/CSS/JS実装

```html
<!-- 分析オーバーレイ -->
<div id="analysis-overlay" class="analysis-overlay">
  <div class="analysis-modal">
    <div class="analysis-icon">🎣</div>
    <div class="analysis-steps">
      <div class="step" id="step1">
        <span class="step-icon">📊</span>
        <span class="step-text">釣果データを読み込み中...</span>
        <span class="step-count">84,757件</span>
      </div>
      <div class="step" id="step2">
        <span class="step-icon">🌊</span>
        <span class="step-text">海況データと照合中...</span>
        <span class="step-sub">波高・水温・潮汐・気圧</span>
      </div>
      <div class="step" id="step3">
        <span class="step-icon">🤖</span>
        <span class="step-text">予測モデルで計算中...</span>
      </div>
    </div>
    <div class="analysis-progress">
      <div class="progress-bar" id="progress-fill"></div>
    </div>
    <div class="analysis-note">初回のみ数秒かかります</div>
  </div>
</div>
```

```css
.analysis-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0,0,0,.7);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 999;
  opacity: 0;
  transition: opacity .3s;
}
.analysis-overlay.active { opacity: 1; }

.analysis-modal {
  background: var(--bg-card);
  border-radius: var(--radius-lg);
  padding: 32px;
  max-width: 360px;
  width: 90%;
  text-align: center;
}

.analysis-icon {
  font-size: 40px;
  margin-bottom: 16px;
  animation: bounce 1s infinite;
}
@keyframes bounce {
  0%, 100% { transform: translateY(0); }
  50% { transform: translateY(-8px); }
}

.analysis-steps { text-align: left; margin: 16px 0; }

.step {
  padding: 8px 0;
  opacity: .3;
  transition: opacity .5s;
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
}
.step.active { opacity: 1; }
.step.done { opacity: .6; }
.step.done .step-icon::after { content: " ✓"; color: var(--positive); }
.step-count {
  font-size: 11px;
  color: var(--accent);
  font-weight: bold;
}
.step-sub {
  font-size: 10px;
  color: var(--text-muted);
}

.analysis-progress {
  height: 4px;
  background: var(--bg-input);
  border-radius: 2px;
  margin: 16px 0 8px;
  overflow: hidden;
}
.progress-bar {
  height: 100%;
  background: linear-gradient(90deg, var(--accent), var(--cta));
  border-radius: 2px;
  width: 0%;
  transition: width .8s ease;
}

.analysis-note {
  font-size: 10px;
  color: var(--text-muted);
}
```

```javascript
function showAnalysis(onComplete) {
  var overlay = document.getElementById('analysis-overlay');
  var steps = overlay.querySelectorAll('.step');
  var bar = document.getElementById('progress-fill');
  overlay.classList.add('active');

  // Step 1: データ読込 (0-1.2秒)
  steps[0].classList.add('active');
  bar.style.width = '35%';

  setTimeout(function() {
    steps[0].classList.remove('active');
    steps[0].classList.add('done');
    steps[1].classList.add('active');
    bar.style.width = '70%';
  }, 1200);

  // Step 2: 海況照合 (1.2-2.4秒)
  setTimeout(function() {
    steps[1].classList.remove('active');
    steps[1].classList.add('done');
    steps[2].classList.add('active');
    bar.style.width = '95%';
  }, 2400);

  // Step 3: 完了 (3.2秒)
  setTimeout(function() {
    steps[2].classList.remove('active');
    steps[2].classList.add('done');
    bar.style.width = '100%';
  }, 3200);

  // フェードアウト→結果表示 (3.6秒)
  setTimeout(function() {
    overlay.classList.remove('active');
    if (onComplete) onComplete();
  }, 3600);
}
```

### 5-3. 使い方（予測ページ）

```javascript
// 「来週の予測を見る」ボタンクリック時
document.querySelector('.forecast-cta').addEventListener('click', function() {
  showAnalysis(function() {
    // 分析完了後に予測結果を表示
    document.querySelector('.forecast-result').style.display = 'block';
    document.querySelector('.forecast-result').classList.add('fade-in');
  });
});
```

---

## 6. 応用: 他に使える場所

| 場所 | 演出 | 目的 |
|------|------|------|
| **トップページ初回ロード** | 「最新の釣果データを取得中...」(1-2秒) | サイトが生きてる感 |
| **魚種ページの予測セクション** | 「{魚種}の予測を計算中...」(2-3秒) | 有料コンテンツの知覚価値UP |
| **エリア天気予報切替** | 「{エリア}の海況データを読込中」(1秒) | データの裏付けを演出 |
| **的中実績ページ** | 「過去3ヶ月の予測精度を集計中...」(2秒) | 信頼性の演出 |
| **比較ツール（将来）** | 「{船宿A} vs {船宿B} のデータを比較中...」(2秒) | 分析ツール感 |

---

## 7. 注意点

### やりすぎ注意
- 同じセッションで何度もスピナーを出さない（2回目以降はキャッシュして即表示）
- テーブルフィルタ等の軽い操作にスピナーは逆効果
- スマホではデータ通信が遅い場合があるので、実際のロードとスピナーが二重にならないよう注意

### 信頼を損なわないために
- 「84,757件」のような具体的数字は**実データと一致**させる（盛らない）
- 実際にデータ処理している場合はスピナーと実処理を同期
- 2回目以降は「キャッシュ済みの予測を表示中」として短縮（0.5秒）

---

## 8. まとめ

| 項目 | 推奨 |
|------|------|
| メイン使用場所 | 有料予測の初回表示 |
| 演出時間 | 3-4秒 |
| 形式 | 3ステップ型プログレス |
| ステップ内容 | ①データ読込→②海況照合→③AI計算 |
| 2回目以降 | 0.5秒のキャッシュ表示 |
| 実装 | CSS + vanilla JS（外部依存なし） |
