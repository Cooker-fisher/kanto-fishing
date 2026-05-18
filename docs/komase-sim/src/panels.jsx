export function settingPanel() {
  return `
    <details class="settings" id="settingsPanel">
      <summary>設定パネル</summary>
      <div class="settings-body">
        <section class="card">
          <h3>道糸・ビシ</h3>
          <label>道糸号数 <input type="range" min="2" max="8" value="4" /></label>
          <label>ビシ号数 <input type="range" min="40" max="120" value="80" /></label>
        </section>
        <section class="card">
          <h3>撒き方・待ち方</h3>
          <label>撒き回数 <input type="range" min="1" max="6" value="3" /></label>
          <label>待ち時間 <input type="range" min="5" max="60" value="20" /></label>
        </section>
        <section class="card">
          <h3>詳細ログ</h3>
          <p>投入・しゃくる・巻く・落とす・回収の履歴をここに表示します。</p>
        </section>
      </div>
    </details>
  `;
}
