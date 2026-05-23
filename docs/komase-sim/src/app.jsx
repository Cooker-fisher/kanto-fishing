import { settingPanel } from './panels.jsx?v=33';

const app = document.getElementById('app');

app.innerHTML = `
  <main class="layout">
    <section class="main">
      <header class="card result-card">
        <p class="eyebrow">診断結果</p>
        <h1>食わせ位置判定: 〇</h1>
        <p>付けエサがコマセに入る確率 <strong>72%</strong></p>
      </header>


      <section class="card link-card">
        <h2>レビュー用リンク</h2>
        <p><a href="./mockups/ui-redesign-v33.html">UIモック（v33）を開く</a></p>
      </section>

      <section class="card viz">
        <h2>棚のイメージ</h2>
        <div class="water">
          <div class="current">潮流 →</div>
          <div class="komase">コマセ帯</div>
          <div class="bait">付けエサ</div>
          <div class="bishi">ビシ</div>
        </div>
      </section>

      <section class="metrics">
        <article class="card"><h3>到達秒数</h3><p>14.2s</p></article>
        <article class="card"><h3>流距離</h3><p>1.8m</p></article>
        <article class="card"><h3>棚ズレ</h3><p>0.3m</p></article>
      </section>

      <section class="card optimize">
        <h2>釣れる設定を探す</h2>
        <p>今の条件でヒット率が上がる組み合わせを候補表示します。</p>
        <button>候補を更新</button>
      </section>
    </section>

    <aside class="side">
      ${settingPanel()}
    </aside>
  </main>

  <nav class="mobile-actions">
    <button>投入</button><button>しゃくる</button><button>巻く</button>
    <button>落とす</button><button>回収</button>
  </nav>
`;
