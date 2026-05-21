/* ============================================================
   panels.jsx — 左(パラメータ) / 右(評価) パネルと共通UI
   v: bishi slider 30-100 step10
   ============================================================ */
const { useState, useEffect, useRef, useMemo } = React;

// ガン玉の標準号数表 (g) — 0.05g step スライダー値を直近の標準サイズ名に変換
const GAN_DAMA_SIZES = [
  { w: 0.07, name: "8号" },
  { w: 0.09, name: "7号" },
  { w: 0.12, name: "6号" },
  { w: 0.16, name: "5号" },
  { w: 0.20, name: "4号" },
  { w: 0.25, name: "3号" },
  { w: 0.31, name: "2号" },
  { w: 0.40, name: "1号" },
  { w: 0.55, name: "B" },
  { w: 0.75, name: "2B" },
  { w: 0.95, name: "3B" },
  { w: 1.20, name: "4B" },
  { w: 1.85, name: "5B" },
];
function ganDamaSizeName(g) {
  if (g == null || g <= 0.01) return "";
  let best = GAN_DAMA_SIZES[0], dmin = Infinity;
  for (const s of GAN_DAMA_SIZES) {
    const d = Math.abs(s.w - g);
    if (d < dmin) { dmin = d; best = s; }
  }
  return "(" + best.name + ")";
}

function CollapsibleSection({ title, defaultOpen, children }) {
  const key = "komase.section." + title;
  const [open, setOpen] = useState(() => {
    try {
      const saved = localStorage.getItem(key);
      if (saved === "1") return true;
      if (saved === "0") return false;
    } catch (e) {}
    return defaultOpen !== false;
  });
  const toggle = () => {
    setOpen(prev => {
      const next = !prev;
      try { localStorage.setItem(key, next ? "1" : "0"); } catch (e) {}
      return next;
    });
  };
  return (
    <div className={"panel__section " + (open ? "" : "panel__section--closed")}>
      <h3 className="panel__h panel__h--clickable" onClick={toggle}>
        <span className="panel__chevron">{open ? "▼" : "▶"}</span>
        <span>{title}</span>
      </h3>
      {open && <div className="panel__body">{children}</div>}
    </div>
  );
}

function LockToggle({ on, onClick, title }) {
  return (
    <button
      type="button"
      className={"lock " + (on ? "is-locked" : "")}
      onClick={onClick}
      title={title || "最適化時にこの値を固定"}
      aria-label="lock"
    >{on ? "🔒" : "🔓"}</button>
  );
}

function Slider({ label, value, min, max, step, unit, onChange, format, lockKey, locks, toggleLock }) {
  const display = format ? format(value) : value;
  const lockable = lockKey != null && locks != null && toggleLock != null;
  return (
    <div className="field">
      <div className="field__row">
        <span className="field__label">
          {lockable && <LockToggle on={!!locks[lockKey]} onClick={() => toggleLock(lockKey)} />}
          {label}
        </span>
        <span className="field__value">
          {display}<span className="unit">{unit}</span>
        </span>
      </div>
      <input
        type="range"
        min={min} max={max} step={step}
        value={value}
        onChange={(e) => onChange(parseFloat(e.target.value))}
      />
    </div>
  );
}

function Segmented({ label, options, value, onChange, lockKey, locks, toggleLock }) {
  const lockable = lockKey != null && locks != null && toggleLock != null;
  return (
    <div className="field">
      {label && (
        <div className="field__row">
          <span className="field__label">
            {lockable && <LockToggle on={!!locks[lockKey]} onClick={() => toggleLock(lockKey)} />}
            {label}
          </span>
        </div>
      )}
      <div className="seg">
        {options.map(o => (
          <button
            key={o.v}
            className={"seg__btn " + (value === o.v ? "is-on" : "")}
            onClick={() => onChange(o.v)}
          >{o.label}</button>
        ))}
      </div>
    </div>
  );
}

// =====================================================================
// 左パネル
// =====================================================================
window.LeftPanel = function LeftPanel({ params, set, locks, toggleLock }) {
  const sp = set;
  const hookW = SimPhysics.getHookWeight(params.hookType, params.hookSize);
  const [hLo, hHi] = SimPhysics.HOOK_SIZE_RANGE[params.hookType] || [7, 12];

  // ビギナーモード (localStorage で永続)
  const [beginner, setBeginner] = useState(() => {
    try { return localStorage.getItem("komase.beginner") === "1"; } catch(e) {}
    return false;
  });
  const setBegMode = (val) => {
    setBeginner(val);
    try { localStorage.setItem("komase.beginner", val ? "1" : "0"); } catch(e) {}
  };

  return (
    <aside className="panel app__left">

      {/* ───── モード切替バー ───── */}
      <div style={{padding:"10px 12px", borderBottom:"1px solid var(--line)"}}>
        <div className="seg">
          <button className={"seg__btn " + (beginner ? "is-on" : "")}
            onClick={() => setBegMode(true)}>🔰 かんたん</button>
          <button className={"seg__btn " + (!beginner ? "is-on" : "")}
            onClick={() => setBegMode(false)}>⚓ 上級者</button>
        </div>
      </div>

      {/* ───── かんたんモード（7項目） ───── */}
      {beginner && (
        <div className="panel__section">
          <h3 className="panel__h">かんたん設定（7項目）</h3>
          <div className="panel__body">
            <div style={{fontSize:11, color:"var(--sub)", marginBottom:14, lineHeight:1.65,
                         padding:"8px 10px", background:"rgba(232,93,4,0.07)",
                         borderRadius:4, border:"1px solid rgba(232,93,4,0.2)"}}>
              この7項目で基本的な釣り方をシミュレーションできます。<br/>
              右パネルの<b style={{color:"var(--cta)"}}>「おすすめを計算」</b>で残りの設定も自動調整されます。
            </div>

            <Slider label="指示ダナ（海面から）" value={params.tanaDepth} min={5} max={params.depth - 3} step={1} unit="m"
              onChange={v => sp({ tanaDepth: v })} />
            <div style={{fontSize:10.5, color:"var(--paper-dim)", marginTop:-6, marginBottom:14, lineHeight:1.55}}>
              コマセを振る深さ。船長の指示通りに合わせる。<b style={{color:"var(--cta)"}}>コマセ釣りで最重要。</b>
            </div>

            <Slider label="潮流速度" value={params.tideSpeed} min={0} max={1.2} step={0.05} unit="m/s"
              onChange={v => sp({ tideSpeed: v })}
              format={v => v.toFixed(2)} />
            <div style={{fontSize:10.5, color:"var(--paper-dim)", marginTop:-6, marginBottom:14, lineHeight:1.55}}>
              潮の速さ。普通の潮は0.3〜0.5。速いとコマセと仕掛けが離れやすい。
            </div>

            <Slider label="ハリス長" value={params.harrisLength} min={2} max={12} step={0.5} unit="m"
              onChange={v => sp({ harrisLength: v })}
              format={v => v.toFixed(1)} />
            <div style={{fontSize:10.5, color:"var(--paper-dim)", marginTop:-6, marginBottom:14, lineHeight:1.55}}>
              針とビシを繋ぐ細い糸。長いほど食いがいい。標準は6〜8m。
            </div>

            <Slider label="上窓の開き（しゃくり放出）" value={params.cageUpperOpening} min={0} max={1.0} step={0.05} unit=""
              onChange={v => sp({ cageUpperOpening: v })}
              format={v => v === 0 ? "全閉" : Math.round(v * 100) + "%"} />
            <div style={{fontSize:10.5, color:"var(--paper-dim)", marginTop:-6, marginBottom:14, lineHeight:1.55}}>
              しゃくり時にコマセが出る量。多いとコマセが早く尽きる。標準は25〜30%。
            </div>

            <Slider label="下窓の開き（連続漏れ）" value={params.cageLowerOpening} min={0} max={1.0} step={0.05} unit=""
              onChange={v => sp({ cageLowerOpening: v })}
              format={v => v === 0 ? "全閉" : Math.round(v * 100) + "%"} />
            <div style={{fontSize:10.5, color:"var(--paper-dim)", marginTop:-6, marginBottom:14, lineHeight:1.55}}>
              待ち時間にじわじわ出るコマセ量。全閉が基本。開けると煙幕を維持しやすい。
            </div>

            <Slider label="ガン玉サイズ" value={params.ganDamaSize} min={0} max={1.5} step={0.05} unit=""
              onChange={v => sp({ ganDamaSize: v })}
              format={v => v === 0 ? "なし" : v.toFixed(2) + "g " + ganDamaSizeName(v)} />
            <div style={{fontSize:10.5, color:"var(--paper-dim)", marginTop:-6, marginBottom:14, lineHeight:1.55}}>
              ハリスに付けるオモリ。重いほどハリスが立ち、コマセ帯との同調がしやすい。
            </div>

            <Slider label="しゃくり振り幅" value={params.shakuriStrokeCm} min={30} max={150} step={5} unit="cm"
              onChange={v => sp({ shakuriStrokeCm: v })}
              format={v => v.toFixed(0)} />
            <div style={{fontSize:10.5, color:"var(--paper-dim)", marginTop:-6, marginBottom:4, lineHeight:1.55}}>
              1回のしゃくりで竿を動かす幅。大きいほどコマセが多く出る。標準は70〜80cm。
            </div>
          </div>
        </div>
      )}

      {/* ───── くわしい設定（既存セクション） ───── */}
      {!beginner && <>
      <CollapsibleSection title="海況" defaultOpen={true}>
        <Slider label="水深" value={params.depth} min={20} max={100} step={1} unit="m"
          onChange={v => sp({ depth: v, tanaDepth: Math.min(params.tanaDepth, v - 5) })} />
        <Slider label="指示ダナ (海面から)" value={params.tanaDepth} min={5} max={params.depth - 3} step={1} unit="m"
          onChange={v => sp({ tanaDepth: v })} />
        <Slider label="潮流速度" value={params.tideSpeed} min={0} max={1.2} step={0.05} unit="m/s"
          onChange={v => sp({ tideSpeed: v })}
          format={v => v.toFixed(2)} />
        <Slider label="底潮の効き" value={params.tideDepthFactor} min={-1.0} max={1.0} step={0.05} unit="×"
          onChange={v => sp({ tideDepthFactor: v })}
          format={v => v < 0 ? `${v.toFixed(2)} (二枚潮)` : v.toFixed(2)} />
        <Slider label="うねり高さ" value={params.swellHeight} min={0} max={2.5} step={0.1} unit="m"
          onChange={v => sp({ swellHeight: v })}
          format={v => v === 0 ? "なし(凪)" : v.toFixed(1)} />
        <Slider label="うねり周期" value={params.swellPeriod} min={3} max={12} step={0.5} unit="s"
          onChange={v => sp({ swellPeriod: v })}
          format={v => v.toFixed(1)} />
      </CollapsibleSection>

      <CollapsibleSection title="本線・ビシ" defaultOpen={true}>
        <Segmented label="PEライン"
          value={params.peNo}
          onChange={v => sp({ peNo: v })}
          lockKey="peNo" locks={locks} toggleLock={toggleLock}
          options={[
            { v: 1,   label: "1号" },
            { v: 1.5, label: "1.5号" },
            { v: 2,   label: "2号" },
            { v: 3,   label: "3号" },
            { v: 4,   label: "4号" },
          ]} />
        <Slider label="ビシ" value={params.bishiNo} min={30} max={100} step={10} unit="号"
          onChange={v => sp({ bishiNo: v })}
          lockKey="bishiNo" locks={locks} toggleLock={toggleLock}
          format={v => v.toFixed(0)} />
        <Slider label="上窓の開き (しゃくり放出)" value={params.cageUpperOpening} min={0} max={1.0} step={0.05} unit=""
          onChange={v => sp({ cageUpperOpening: v })}
          lockKey="cageUpperOpening" locks={locks} toggleLock={toggleLock}
          format={v => v === 0 ? "全閉" : Math.round(v * 100) + "%"} />
        <Slider label="下窓の開き (連続漏れ)" value={params.cageLowerOpening} min={0} max={1.0} step={0.05} unit=""
          onChange={v => sp({ cageLowerOpening: v })}
          lockKey="cageLowerOpening" locks={locks} toggleLock={toggleLock}
          format={v => v === 0 ? "全閉" : Math.round(v * 100) + "%"} />
        <Segmented label="コマセ粒サイズ"
          value={params.komaseSize}
          onChange={v => sp({ komaseSize: v })}
          lockKey="komaseSize" locks={locks} toggleLock={toggleLock}
          options={[
            { v: "M", label: "M" },
            { v: "L", label: "L" },
            { v: "2L", label: "2L" },
            { v: "3L", label: "3L" },
          ]} />
        <Segmented label="煙幕度"
          value={params.smokeLevel}
          onChange={v => sp({ smokeLevel: v })}
          lockKey="smokeLevel" locks={locks} toggleLock={toggleLock}
          options={[
            { v: "weak", label: "弱 (オキアミ)" },
            { v: "medium", label: "中 (混合)" },
            { v: "strong", label: "強 (アミ/ミンチ)" },
          ]} />
        <div className="note" style={{fontSize: 10, marginTop: 4, opacity: 0.7}}>
          <b>サニー商事マニュアル準拠:</b><br/>
          上窓 = 半開〜全開 (しゃくり時の主放出口)<br/>
          下窓 = オキアミ体幅 ≒ 全閉に近い (連続漏れは控えめ)<br/>
          王道: 上 0.5 / 下 0.15。「上から振り出す」のが基本。<br/>
          外房カモシは下窓全閉＋上窓細＋煙幕強 (ミンチを持たせる)。
        </div>
      </CollapsibleSection>

      <CollapsibleSection title="クッションゴム・モトス・ハリス" defaultOpen={true}>
        <Slider label="クッションゴム長" value={params.cushionLength} min={0.5} max={3.0} step={0.1} unit="m"
          onChange={v => sp({ cushionLength: v })}
          lockKey="cushionLength" locks={locks} toggleLock={toggleLock}
          format={v => v.toFixed(1)} />

        {/* モトス (上ハリス・太め): 有無 + 号数 + 長さ */}
        <div className="tog-row" title="サル管上の太い上ハリス">
          <span>モトス有り</span>
          <div className={"tog " + (params.motosEnabled !== false ? "is-on" : "")}
               onClick={() => sp({ motosEnabled: !(params.motosEnabled !== false) })} />
        </div>
        {params.motosEnabled !== false && (<>
          <Segmented label="モトス号数"
            value={params.motosNo != null ? params.motosNo : 5}
            onChange={v => sp({ motosNo: v })}
            lockKey="motosNo" locks={locks} toggleLock={toggleLock}
            options={[
              { v: 4, label: "4号" },
              { v: 5, label: "5号" },
              { v: 6, label: "6号" },
              { v: 7, label: "7号" },
            ]} />
          <Slider label="モトス長" value={params.motosLength != null ? params.motosLength : 1.5}
            min={0.5} max={3.0} step={0.1} unit="m"
            onChange={v => sp({ motosLength: v })}
            lockKey="motosLength" locks={locks} toggleLock={toggleLock}
            format={v => v.toFixed(1)} />
        </>)}

        {/* サル管: 有無 + 号数 */}
        <div className="tog-row" title="モトスとハリスを繋ぐ連結金具">
          <span>サル管有り</span>
          <div className={"tog " + (params.saruKanEnabled !== false ? "is-on" : "")}
               onClick={() => sp({ saruKanEnabled: !(params.saruKanEnabled !== false) })} />
        </div>
        {params.saruKanEnabled !== false && (
          <Segmented label="サル管号数"
            value={params.saruKanSize != null ? params.saruKanSize : 14}
            onChange={v => sp({ saruKanSize: v })}
            lockKey="saruKanSize" locks={locks} toggleLock={toggleLock}
            options={[
              { v: 10, label: "10号" },
              { v: 14, label: "14号" },
              { v: 18, label: "18号" },
              { v: 22, label: "22号" },
            ]} />
        )}

        {/* ハリス (下・細め): サル管→針。ガン玉はハリスに付く */}
        <Slider label="ハリス長" value={params.harrisLength} min={2} max={12} step={0.5} unit="m"
          onChange={v => sp({ harrisLength: v })}
          lockKey="harrisLength" locks={locks} toggleLock={toggleLock}
          format={v => v.toFixed(1)} />
        <Segmented label="ハリス号数"
          value={params.harrisNo}
          onChange={v => sp({ harrisNo: v })}
          lockKey="harrisNo" locks={locks} toggleLock={toggleLock}
          options={[
            { v: 2, label: "2号" },
            { v: 3, label: "3号" },
            { v: 4, label: "4号" },
            { v: 5, label: "5号" },
          ]} />
      </CollapsibleSection>

      <CollapsibleSection title="針" defaultOpen={true}>
        <Segmented label="針タイプ"
          value={params.hookType}
          onChange={v => {
            const [lo, hi] = SimPhysics.HOOK_SIZE_RANGE[v];
            const size = params.hookSize >= lo && params.hookSize <= hi ? params.hookSize : Math.round((lo+hi)/2);
            sp({ hookType: v, hookSize: size });
          }}
          lockKey="hookType" locks={locks} toggleLock={toggleLock}
          options={[
            { v: "madai", label: "マダイ" },
            { v: "iseama", label: "伊勢尼" },
            { v: "chinu", label: "チヌ" },
            { v: "gure", label: "グレ" },
            { v: "mutsu", label: "ムツ" },
          ]} />
        <Slider label="針サイズ" value={params.hookSize} min={hLo} max={hHi} step={1} unit="号"
          onChange={v => sp({ hookSize: v })}
          lockKey="hookSize" locks={locks} toggleLock={toggleLock} />
        <div className="field">
          <div className="field__row">
            <span className="field__label">針重量 (自動算出)</span>
            <span className="field__value" style={{color:"var(--vermilion)"}}>{hookW.toFixed(2)}<span className="unit">g</span></span>
          </div>
        </div>
        <Slider label="ガン玉位置 (ビシ側0%→針側100%)"
          value={params.ganDamaPct != null ? params.ganDamaPct : 50}
          min={0} max={100} step={5} unit="%"
          onChange={v => sp({ ganDamaPct: v,
            ganDamaPos: v <= 15 ? "chimoto" : v >= 85 ? "near-hook" : "mid" })}
          lockKey="ganDamaPct" locks={locks} toggleLock={toggleLock}
          format={v => (v <= 15 ? "チモト " : v >= 85 ? "ハリス下 " : "中 ") + v} />
        <Slider label="ガン玉サイズ" value={params.ganDamaSize} min={0} max={1.5} step={0.05} unit=""
          onChange={v => sp({ ganDamaSize: v })}
          lockKey="ganDamaSize" locks={locks} toggleLock={toggleLock}
          format={v => v === 0 ? "なし" : v.toFixed(2) + "g " + ganDamaSizeName(v)} />
      </CollapsibleSection>

      <CollapsibleSection title="動作・タナ取り" defaultOpen={true}>
        <Slider label="ビシ落としこみ位置 (指示棚 ±)"
          value={params.dropOffsetM != null ? params.dropOffsetM : 5}
          min={-10} max={10} step={0.5} unit="m"
          onChange={v => sp({ dropOffsetM: v })}
          lockKey="dropOffsetM" locks={locks} toggleLock={toggleLock}
          format={v => v > 0 ? `タナ下${v.toFixed(1)}` : v < 0 ? `タナ上${(-v).toFixed(1)}` : "指示棚"} />
        <Slider label="しゃくり振り幅" value={params.shakuriStrokeCm} min={30} max={150} step={5} unit="cm"
          onChange={v => sp({ shakuriStrokeCm: v })}
          lockKey="shakuriStrokeCm" locks={locks} toggleLock={toggleLock}
          format={v => v.toFixed(0)} />
        <Slider label="1動作のしゃくり数" value={params.shakuriCountPerTrigger} min={1} max={5} step={1} unit="回"
          onChange={v => sp({ shakuriCountPerTrigger: v })}
          lockKey="shakuriCountPerTrigger" locks={locks} toggleLock={toggleLock}
          format={v => v.toFixed(0)} />
        <Slider label="巻き量(1回当たり)" value={params.makiAmount} min={0} max={3.0} step={0.1} unit="m"
          onChange={v => sp({ makiAmount: v })}
          lockKey="makiAmount" locks={locks} toggleLock={toggleLock}
          format={v => v === 0 ? "なし" : v.toFixed(1)} />
        <Slider label="落とし込み量(1回当たり)" value={params.dropAmount} min={0} max={2.0} step={0.1} unit="m"
          onChange={v => sp({ dropAmount: v })}
          lockKey="dropAmount" locks={locks} toggleLock={toggleLock}
          format={v => v === 0 ? "なし" : v.toFixed(1)} />
        <Slider label="しゃくり間隔(待ち)" value={params.shakuriInterval} min={10} max={300} step={5} unit=""
          onChange={v => sp({ shakuriInterval: v })}
          lockKey="shakuriInterval" locks={locks} toggleLock={toggleLock}
          format={v => v >= 60 ? Math.floor(v/60) + "分" + (v%60 ? (v%60)+"秒" : "") : v.toFixed(0) + "秒"} />
        <div className="field">
          <div className="field__row">
            <span className="field__label">落とし込み速度 (自動)</span>
            <span className="field__value" style={{color:"var(--vermilion)"}}>
              {SimPhysics.computeDropSpeed(params.bishiNo).toFixed(2)}<span className="unit">m/s</span>
            </span>
          </div>
          <div className="note" style={{marginTop:2, fontSize:10, opacity:0.65}}>
            ビシ {params.bishiNo}号 ({(params.bishiNo * 3.75).toFixed(0)}g) のフリー落下終端速度
          </div>
        </div>
        <div className="tog-row" title="しゃくり N発 → 巻き → 食わせ待ち → タナへ戻す のサイクルを自動で回す">
          <span>自動最適動作</span>
          <div className={"tog " + (params.autoShakuri ? "is-on" : "")}
               onClick={() => sp({ autoShakuri: !params.autoShakuri })} />
        </div>
      </CollapsibleSection>
      </>}
    </aside>
  );
};

// =====================================================================
// 右パネル
// =====================================================================
window.RightPanel = function RightPanel(props) {
  const { metrics, params, presets, selectedPresets, onPreset,
          onOptimize, optimizing, recommendation, onApplyRec, locks, lastCycleResult } = props;
  const sel = selectedPresets || {};
  const grade = metrics.grade;
  const gradeClass = grade === "◎" || grade === "○" ? "grade--ok" : grade === "×" ? "grade--bad" : "";
  const cycResGradeClass = lastCycleResult
    ? (lastCycleResult.grade === "◎" || lastCycleResult.grade === "○" ? "grade--ok"
       : lastCycleResult.grade === "×" ? "grade--bad" : "")
    : "";

  const lockedKeys = locks ? Object.keys(locks).filter(k => locks[k]) : [];

  return (
    <aside className="panel panel--right app__right">
      <CollapsibleSection title="プリセット" defaultOpen={true}>
        {(() => {
          const groupOrder = [
            { key: "cycle", label: "サイクル" },
            { key: "cond", label: "海況" },
            { key: "area", label: "エリア" },
          ];
          const grouped = {};
          presets.forEach(p => {
            const g = p.group || "_other";
            if (!grouped[g]) grouped[g] = [];
            grouped[g].push(p);
          });
          return groupOrder.map(g => {
            const list = grouped[g.key];
            if (!list || list.length === 0) return null;
            return (
              <div key={g.label} className="preset-group">
                <span className="preset-group__label">{g.label}</span>
                <div className="chips chips--compact">
                  {list.map(p => (
                    <button key={p.key}
                            className={"chip chip--compact " + (sel[g.key] === p.key ? "is-on" : "")}
                            onClick={() => onPreset(p.key)}>{p.label}</button>
                  ))}
                </div>
              </div>
            );
          });
        })()}
      </CollapsibleSection>

      <CollapsibleSection title="自動最適化" defaultOpen={true}>
        <button
          className={"btn " + (optimizing ? "is-active" : "is-primary")}
          style={{width:"100%", padding:"12px"}}
          disabled={optimizing}
          onClick={onOptimize}
        >{optimizing ? "計算中..." : "おすすめを計算"}</button>
        <div className="note" style={{marginTop:8}}>
          現在の海況固定で、ハリス・ガン玉・しゃくり・巻きの<b>最適な組合せ</b>を探索します。
          スライダー左の <span style={{fontFamily:"var(--mono)"}}>🔒</span> で値を固定すれば、その項目は変えずに探索します。
        </div>
        {lockedKeys.length > 0 && (
          <div className="note" style={{marginTop:6, color:"var(--brass)"}}>
            <b>固定中:</b> {lockedKeys.map(k => LOCK_LABEL[k] || k).join(" / ")}
          </div>
        )}
        {recommendation && (
          <RecommendationCard rec={recommendation} onApply={onApplyRec} params={params} />
        )}
      </CollapsibleSection>

      <CollapsibleSection title="合否" defaultOpen={true}>
        {(() => {
          const cycScore = metrics.cycleScore || 0;
          const cycGrade = metrics.cycleGrade || "×";
          const cycGradeClass = cycGrade === "◎" || cycGrade === "○" ? "grade--ok" : cycGrade === "×" ? "grade--bad" : "";
          return (
            <div style={{
              marginBottom: 12,
              padding: "10px 12px",
              background: "rgba(232, 93, 4, 0.08)",
              borderLeft: "3px solid var(--cta)",
              borderRadius: "4px",
            }}>
              <div style={{display:"flex", alignItems:"center", justifyContent:"space-between", marginBottom: 6}}>
                <span style={{fontSize: 11, color: "var(--sub)", letterSpacing: ".08em", fontWeight: 600}}>
                  サイクル {metrics.cycleNo + 1} 進行中 ({(metrics.cycleDurationSec || 0).toFixed(0)}秒)
                </span>
                <span className={"grade " + cycGradeClass} style={{fontSize: 22, marginLeft: 8}}>
                  {cycGrade}
                </span>
              </div>
              <div style={{display:"flex", alignItems:"baseline", gap: 8, marginBottom: 6}}>
                <span style={{fontSize: 28, fontWeight: 700, color: "var(--cta)", fontFamily: "var(--mono)"}}>
                  {cycScore.toFixed(1)}
                </span>
                <span style={{fontSize: 14, color: "var(--sub)"}}>/ 100</span>
              </div>
              <div style={{fontSize: 11, color: "var(--paper-dim)", lineHeight: 1.5, marginBottom: 6}}>
                {metrics.cycleNote}
              </div>
              <div style={{fontSize: 10, color: "var(--sub)", fontFamily: "var(--mono)", letterSpacing: ".03em"}}>
                良 {(metrics.cycleSustainRate || 0).toFixed(1)}% / 可 {(metrics.cycleOkRate || 0).toFixed(1)}% / 平均同調 {(metrics.cycleMeanSync || 0).toFixed(2)}% / ピーク {(metrics.cyclePeakSync || 0).toFixed(2)}%
              </div>
            </div>
          );
        })()}
        <div style={{fontSize: 10, color: "var(--sub)", letterSpacing: ".05em", marginBottom: 6}}>
          配置のリアルタイム判定
        </div>
        <div style={{display:"flex", alignItems:"center"}}>
          <span className={"grade " + gradeClass}>{grade}</span>
          <span style={{fontSize:"12px", color:"var(--paper-dim)", lineHeight:1.5}}>
            {metrics.gradeNote}
          </span>
        </div>
        {metrics.waitHint && metrics.waitHint.active && (
          <div className="wait-hint" style={{
            marginTop: 10,
            padding: "8px 10px",
            background: "rgba(251, 191, 36, 0.14)",
            borderLeft: "3px solid " + metrics.waitHint.color,
            borderRadius: "4px",
            fontSize: "12px",
            color: metrics.waitHint.color,
            fontFamily: "var(--sans)",
            fontWeight: 600,
            letterSpacing: ".05em",
          }}>
            {metrics.waitHint.label}
            <div style={{fontSize: "10px", color: "var(--sub)", marginTop: 4, fontFamily: "var(--sans)", letterSpacing: 0, fontWeight: 400}}>
              タイがいるところにコマセが届いている状態。<br/>
              この状態を維持して食わせのタイミングを待つのがコマセ釣りの肝。
            </div>
          </div>
        )}
        {metrics.belowWarning && (
          <div style={{
            marginTop: 10,
            padding: "8px 10px",
            background: "rgba(232, 93, 4, 0.10)",
            borderLeft: "3px solid " + metrics.belowWarning.color,
            borderRadius: "4px",
            fontSize: "12px",
            color: metrics.belowWarning.color,
            fontFamily: "var(--sans)",
            fontWeight: 600,
            letterSpacing: ".03em",
          }}>
            {metrics.belowWarning.text}
            <div style={{fontSize: "10px", color: "var(--sub)", marginTop: 4, fontFamily: "var(--sans)", letterSpacing: 0, fontWeight: 400}}>
              ビシ自体が指示棚より下に沈むと、コマセ放出点が指示棚より深くなり、魚のタナを外す。<br/>
              「巻く」ボタンで指示棚まで持ち上げて、コマセは指示棚で振る。
            </div>
          </div>
        )}
      </CollapsibleSection>

      <CollapsibleSection title="付けエサ到達率" defaultOpen={true}>
        <div className="metric">
          <div className="metric__num">
            {metrics.hitRate.toFixed(1)}<span className="small">%</span>
          </div>
          <div className="metric__bar"><i style={{width: Math.min(100, metrics.hitRate * 15) + "%"}}/></div>
          <div className="note">
            付けエサ周辺 <b>1.8m</b> 圏内に滞留するコマセ粒子の割合(平均)。<br/>
            理想は <b>4%以上</b>、実釣で <b>1〜3%</b> が標準的。
          </div>
        </div>
      </CollapsibleSection>

      <CollapsibleSection title="タナ別密度" defaultOpen={false}>
        <Histogram data={metrics.histogram} hookBin={metrics.hookBin} />
        <div className="histogram__axis">
          <span>海面</span><span>付けエサ</span><span>海底</span>
        </div>
        <div className="note">緑バー = 付けエサのタナ。コマセ雲がここに重なるのが理想。</div>
      </CollapsibleSection>

      <CollapsibleSection title="運用ログ" defaultOpen={false}>
        <div className="note" style={{lineHeight:1.8}}>
          <div>累計しゃくり <b>{metrics.shakuriCount}回</b></div>
          <div>放出コマセ <b>{metrics.totalSpawned}粒</b></div>
          <div>ハリス傾斜 <b>{(metrics.harrisAngleDeg).toFixed(0)}°</b></div>
          <div>付けエサ深度 <b>{metrics.hookDepth.toFixed(1)}m</b></div>
          <div>指示ダナとのズレ <b style={{color: Math.abs(metrics.tanaDiff) > 1.5 ? "var(--vermilion)" : "var(--moss)"}}>
            {metrics.tanaDiff > 0 ? "+" : ""}{metrics.tanaDiff.toFixed(1)}m
          </b></div>
          {metrics.peVertical != null && (
            <div style={{marginTop: 4, paddingTop: 4, borderTop: "1px dashed var(--line)"}}>
              <span style={{color: "var(--brass)"}}>PE鉛直距離 (竿先→ビシ)</span>{" "}
              <b style={{fontSize: 14, color: "var(--vermilion)"}}>{metrics.peVertical.toFixed(2)}m</b>
              <span style={{fontSize: 10, color: "var(--paper-dim)", marginLeft: 4}}>
                / ライン長 {metrics.peTotal.toFixed(1)}m
              </span>
              <div style={{fontSize: 10, color: "var(--paper-dim)", marginTop: 2, opacity: 0.85}}>
                竿先→ビシ。潮で横変位 {metrics.peHorizontal.toFixed(1)}m 分余分に道糸が出る。
              </div>
            </div>
          )}
          {metrics.rigVertical != null && (
            <div style={{marginTop: 4, paddingTop: 4, borderTop: "1px dashed var(--line)"}}>
              <span style={{color: "var(--brass)"}}>仕掛け鉛直距離 (ビシ→付けエサ)</span>{" "}
              <b style={{fontSize: 14, color: "var(--vermilion)"}}>{metrics.rigVertical.toFixed(2)}m</b>
              <span style={{fontSize: 10, color: "var(--paper-dim)", marginLeft: 4}}>
                / ハリス長 {metrics.rigTotal.toFixed(1)}m ({(metrics.rigVerticalRatio * 100).toFixed(0)}%)
              </span>
              <div style={{fontSize: 10, color: "var(--paper-dim)", marginTop: 2, opacity: 0.85}}>
                ビシ→付けエサの実 y 差。潮流でハリスが流れ短縮。<br/>
                タナ取りはこの鉛直距離で計算する。
              </div>
            </div>
          )}
          <div style={{marginTop: 6}}>コマセ雲(中心深度) <b>{metrics.komaseDepth != null ? metrics.komaseDepth.toFixed(1) + "m" : "—"}</b></div>
          <div>タナ下流出率 <b style={{color: metrics.belowRatio >= 25 ? "var(--vermilion)" : "var(--paper)"}}>
            {(metrics.belowRatio || 0).toFixed(0)}%
          </b></div>
        </div>
      </CollapsibleSection>
    </aside>
  );
};

const LOCK_LABEL = {
  peNo: "PE", bishiNo: "ビシ",
  cageUpperOpening: "上窓", cageLowerOpening: "下窓",
  komaseSize: "コマセ粒サイズ", smokeLevel: "煙幕度",
  cushionLength: "クッションゴム長",
  harrisLength: "ハリス長", harrisNo: "ハリス号数",
  hookType: "針タイプ", hookSize: "針サイズ",
  ganDamaPos: "ガン玉位置", ganDamaSize: "ガン玉サイズ",
  shakuriStrokeCm: "しゃくり振り幅", shakuriCountPerTrigger: "しゃくり数",
  makiAmount: "巻き量", dropAmount: "落とし込み量", shakuriInterval: "しゃくり間隔",
  ganDamaPct: "ガン玉位置",
  motosLength: "モトス長", motosNo: "モトス号数", dropOffsetM: "ビシ落とし込み",
};

function RecommendationCard({ rec, onApply, params }) {
  const r = rec.best;
  const locked = rec.locked || {};
  const hookLabel = SimPhysics.HOOK_TYPE_LABEL[r.hookType];
  const ganPct = r.ganDamaPct != null ? r.ganDamaPct
    : (r.ganDamaPos === "chimoto" ? 5 : r.ganDamaPos === "near-hook" ? 92 : 50);
  const ganLabel = ganPct <= 15 ? "チモト" : ganPct >= 85 ? "ハリス下" : "中";
  const cell = (key, value) => (
    <RecRow label={LOCK_LABEL[key] || key} value={value} locked={!!locked[key]} />
  );
  return (
    <div style={{
      marginTop: 12,
      border: "1px solid var(--cta)",
      borderRadius: "6px",
      padding: "10px 12px",
      background: "rgba(232, 93, 4, 0.06)",
    }}>
      <div style={{
        fontFamily: "var(--sans)", fontSize: 11, fontWeight: 700,
        color: "var(--cta)", letterSpacing: ".14em", marginBottom: 6
      }}>推奨設定</div>
      {/* 針タイプは長いので 2列スパン */}
      <div style={{marginBottom: 4}}>
        {cell("hookType", `${hookLabel} ${r.hookSize}号 (${SimPhysics.getHookWeight(r.hookType, r.hookSize).toFixed(2)}g)`)}
      </div>
      {/* 残りの 12 項目を 2列グリッドに */}
      <div style={{
        display: "grid",
        gridTemplateColumns: "1fr 1fr",
        columnGap: "10px",
        rowGap: "2px",
        color:"var(--text)",
      }}>
        {r.cushionLength != null && cell("cushionLength", `${r.cushionLength.toFixed(1)}m`)}
        {r.motosLength != null && cell("motosLength",
          r.motosLength === 0 ? "なし" : `${r.motosLength.toFixed(1)}m ${r.motosNo || 5}号`)}
        {cell("harrisLength", `${r.harrisLength.toFixed(1)}m ${r.harrisNo}号`)}
        {r.dropOffsetM != null && cell("dropOffsetM",
          r.dropOffsetM > 0 ? `タナ下${r.dropOffsetM.toFixed(1)}m` : r.dropOffsetM < 0 ? `タナ上${(-r.dropOffsetM).toFixed(1)}m` : "指示棚")}
        {cell("ganDamaPct", `${ganLabel} ${ganPct}% ${r.ganDamaSize === 0 ? "なし" : r.ganDamaSize.toFixed(2)+"g " + ganDamaSizeName(r.ganDamaSize)}`)}
        {r.cageUpperOpening != null && cell("cageUpperOpening", `${Math.round(r.cageUpperOpening*100)}%`)}
        {r.cageLowerOpening != null && cell("cageLowerOpening", `${Math.round(r.cageLowerOpening*100)}%`)}
        {r.komaseSize != null && cell("komaseSize", `${r.komaseSize}`)}
        {r.smokeLevel != null && cell("smokeLevel", r.smokeLevel === "weak" ? "弱" : r.smokeLevel === "medium" ? "中" : "強")}
        {cell("shakuriStrokeCm", `${r.shakuriStrokeCm}cm`)}
        {cell("shakuriCountPerTrigger", `${r.shakuriCountPerTrigger}回`)}
        {cell("makiAmount", r.makiAmount === 0 ? "なし" : r.makiAmount.toFixed(2)+"m")}
        {cell("shakuriInterval", `${r.shakuriInterval.toFixed(0)}s`)}
      </div>
      <div style={{
        marginTop: 8, paddingTop: 8, borderTop: "1px dashed var(--border)",
        fontSize:11, color:"var(--sub)",
      }}>
        予測到達率 <b style={{color:"var(--cta)", fontSize:14}}>{rec.score.toFixed(1)}%</b>
        {rec.baseline != null && (
          <span style={{marginLeft:6, fontFamily:"var(--mono)"}}>
            (現行 {rec.baseline.toFixed(1)}% / <span style={{color: rec.score >= rec.baseline ? "var(--pos)" : "var(--sub)"}}>
              {rec.score - rec.baseline >= 0 ? "+" : ""}{(rec.score - rec.baseline).toFixed(1)}pt
            </span>)
          </span>
        )}
      </div>
      <button className="btn is-primary" style={{width:"100%", marginTop:8}}
              onClick={onApply}>この設定を適用</button>
    </div>
  );
}

function RecRow({ label, value, locked }) {
  return (
    <div style={{
      display:"flex",
      justifyContent:"space-between",
      alignItems:"baseline",
      fontSize: 10.5,
      lineHeight: 1.4,
      minWidth: 0,
    }}>
      <span style={{
        color: locked ? "var(--gold-deep)" : "var(--sub)",
        overflow:"hidden",
        textOverflow:"ellipsis",
        whiteSpace:"nowrap",
        flex: "0 1 auto",
        marginRight: 4,
      }}>
        {locked && <span style={{marginRight:2}}>🔒</span>}{label}
      </span>
      <span style={{
        fontFamily:"var(--mono)",
        fontSize: 10.5,
        fontWeight: 600,
        color: locked ? "var(--gold-deep)" : "var(--text)",
        flexShrink: 0,
      }}>{value}</span>
    </div>
  );
}

function Histogram({ data, hookBin }) {
  if (!data || !data.length) return <div className="histogram"></div>;
  const max = Math.max(1, ...data);
  return (
    <div className="histogram">
      {data.map((v, i) => (
        <i key={i}
           className={i === hookBin ? "is-hook" : ""}
           style={{height: (v / max * 100) + "%"}} />
      ))}
    </div>
  );
}
