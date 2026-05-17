/* ============================================================
   physics.jsx — コマセ巻きシミュレーター 物理エンジン
   - 座標系: x=水平[m] (潮の流れる方向が正), y=深さ[m] (海面が0)
   - 単純化した連続体モデル:
     ・コマセ粒子: 沈降速度 + 潮流追従 + 微小乱流
     ・潮流: 海面で最大、海底で減衰
     ・ハリス: 静的形状（張力 vs 流体抗力 + ガン玉位置で湾曲）
     ・しゃくり: ビシに上向きインパルス + 粒子放出
     ・巻き(maki): しゃくり後にビシを makiAmount [m] 段階的に持ち上げる
     ・コマセ残量: ビシは有限容量。しゃくり・連続漏れで減少。
                  仕掛け回収(リセット)で満タン補充。
   ============================================================ */
window.SimPhysics = (function() {

  // 竿先の世界座標 x [m]。船体中心 (x=0) から右舷へ突き出た位置。
  // ビシはここの真下に静止し、潮流があれば下流(+x)へドリフトする。
  const ROD_X_M = 6;

  // ====== 針重量テーブル [g] ======
  const HOOK_WEIGHTS = {
    madai:  { 7:0.18, 8:0.25, 9:0.35, 10:0.48, 11:0.65, 12:0.88 },
    iseama: { 7:0.22, 8:0.32, 9:0.45, 10:0.60, 11:0.80, 12:1.05 },
    chinu:  { 3:0.18, 4:0.28, 5:0.42, 6:0.58, 7:0.78, 8:1.02 },
    gure:   { 5:0.10, 6:0.15, 7:0.22, 8:0.30, 9:0.40, 10:0.52 },
    mutsu:  { 14:0.55, 15:0.72, 16:0.95, 17:1.25, 18:1.62, 19:2.05 },
  };
  const HOOK_TYPE_LABEL = {
    madai: "マダイ針", iseama: "伊勢尼", chinu: "チヌ針", gure: "グレ針", mutsu: "ムツ針"
  };
  const HOOK_SIZE_RANGE = {
    madai:  [7,12], iseama: [7,12], chinu: [3,8], gure: [5,10], mutsu: [14,19]
  };
  function getHookWeight(type, size) {
    const t = HOOK_WEIGHTS[type] || HOOK_WEIGHTS.madai;
    if (t[size] != null) return t[size];
    const keys = Object.keys(t).map(Number).sort((a,b)=>a-b);
    const lo = keys[0], hi = keys[keys.length-1];
    if (size < lo) return t[lo] * Math.pow(0.7, lo - size);
    return t[hi] * Math.pow(1.3, size - hi);
  }

  // --- 潮流速度プロファイル (m/s) ---
  // 海面 (y=0) で tideSpeed、海底 (y=depth) で tideSpeed × tideDepthFactor の線形補間
  function current(y, params) {
    const depth = Math.max(0.5, params.depth);
    const t = Math.max(0, Math.min(1, y / depth));
    const factor = (1 - t) * (1 - params.tideDepthFactor) + params.tideDepthFactor;
    return params.tideSpeed * factor;
  }

  // --- PEラインの累積横変位 [m] ---
  // 物理: 各深さで PE が受ける流体抗力 ∝ c² × 直径。これに対しビシ重量が水平方向に張力を提供。
  //   局所傾き角 dθ/dy ≈ drag_per_length / (bishi_weight_force) — 但しビシ重ほど傾きにくい
  //   横変位 = ∫ tan(θ(y)) dy ≈ ∫ (drag * y / bishiW) dy (累積効果)
  // PE 直径: 1号≈0.165mm, 3号≈0.286mm, 4号≈0.330mm → √(peNo) で近似
  // ビシ号数: 40号(150g), 80号(300g), 100号(375g) — sqrt で正規化
  function pelineDrift(params, depth) {
    const peDia = Math.sqrt(params.peNo || 3);
    const bishiW = Math.sqrt(Math.max(20, params.bishiNo || 80) / 80); // 80号基準
    const peCoef = peDia * 0.50 / bishiW;  // 重ビシほど流されにくい
    const N = 14;
    const dy = depth / N;
    let acc = 0;
    for (let i = 1; i <= N; i++) {
      const y = depth * i / N;
      const c = current(y, params);
      acc += peCoef * c * c * dy;
    }
    return acc;
  }

  // --- ビシの自由落下終端速度 [m/s] ---
  // 1号 = 3.75g。鉛比重 11.3, 海水 1.025 → 浮力で重量×0.91
  // 籠抵抗が支配的 (A ≈ const) なので v ∝ √m。実釣値 (40号≈1.4 / 80号≈2.0 / 100号≈2.2 m/s)
  // に合うよう v = √(bishiNo/20) を採用
  function computeDropSpeed(bishiNo) {
    const n = bishiNo || 80;
    return Math.sqrt(n / 20);
  }

  // ====== コマセ消費 ======
  // 上窓: しゃくり時にコマセが「吹き上げ」される度合い (実釣で穴2-3つ残しが標準)
  // 下窓: 連続漏れ。閉じれば「ためて出す」、開ければ「漂わせる」
  function cageUpper(params) {
    return params.cageUpperOpening != null
      ? params.cageUpperOpening
      : (params.cageOpening != null ? params.cageOpening : 0.45);
  }
  function cageLower(params) {
    return params.cageLowerOpening != null
      ? params.cageLowerOpening
      : (params.cageOpening != null ? params.cageOpening : 0.45);
  }
  function shakuriConsumption(params) {
    const strokeFactor = (params.shakuriStrokeCm != null ? params.shakuriStrokeCm : 50) / 50;
    // しゃくり消費は主に上窓に依存（下窓は持続漏れに寄与）
    return 0.012 + cageUpper(params) * 0.04 * strokeFactor;
  }
  // 連続漏れ (毎秒) 容量比 — 下窓開けると漂う
  // cageLower=0.15 で 0.00042/s → 1ビシ 40分相当 (実釣感覚と一致)
  // cageLower=0.50 で 0.0014/s → 12分 (開け切ると速い)
  function leakRate(params) {
    return cageLower(params) * 0.0028;
  }

  // ====== コマセ粒 物性（オキアミサイズ / 煙幕度） ======
  // sizeScale: 沈降速度 (terminal m/s ベース) × 粒の見た目 × 寿命減少率
  const KOMASE_SIZE_PROPS = {
    "M":  { terminalBase: 0.07, sizeBase: 0.6, lifeMul: 0.85 },
    "L":  { terminalBase: 0.13, sizeBase: 0.85, lifeMul: 1.00 },
    "2L": { terminalBase: 0.18, sizeBase: 1.10, lifeMul: 1.10 },
    "3L": { terminalBase: 0.22, sizeBase: 1.35, lifeMul: 1.20 },
  };
  // 煙幕度: 粒子の寿命 / 拡散性 / 沈降抗力 / 視覚透明度
  const SMOKE_LEVEL_PROPS = {
    "weak":   { lifeMul: 1.0, diffuse: 0.025, terminalMul: 1.00, alphaMul: 1.0 },
    "medium": { lifeMul: 1.6, diffuse: 0.055, terminalMul: 0.65, alphaMul: 0.78 },
    "strong": { lifeMul: 2.3, diffuse: 0.095, terminalMul: 0.40, alphaMul: 0.55 },
  };
  function komaseSizeProps(params) {
    return KOMASE_SIZE_PROPS[params.komaseSize] || KOMASE_SIZE_PROPS["L"];
  }
  function smokeLevelProps(params) {
    return SMOKE_LEVEL_PROPS[params.smokeLevel] || SMOKE_LEVEL_PROPS["weak"];
  }

  // --- 粒子放出 ---
  // 戻り値: 実際に放出した粒子数 (残量が少ないと減る)
  // rng: 決定論的乱数。未指定なら Math.random（ライブ表示用）
  function spawnParticles(out, cage, params, shakuriIntensity, maxCap, chumLevel, rng) {
    const rnd = rng || Math.random;
    // 粒数は上窓開きと煙幕度に依存（煙幕強=細粒なので多数放出）
    const sz = komaseSizeProps(params);
    const sm = smokeLevelProps(params);
    const opening = cageUpper(params);
    // 細粒(煙幕強)は単位重量あたり多い粒
    const smokeCountMul = sm === SMOKE_LEVEL_PROPS.weak ? 1.0 : sm === SMOKE_LEVEL_PROPS.medium ? 1.6 : 2.4;
    const baseN = Math.round((8 + opening * 26) * smokeCountMul);
    let n = Math.round(baseN * (0.4 + shakuriIntensity * 1.0));
    n = Math.round(n * Math.max(0, Math.min(1, chumLevel)));
    let spawned = 0;
    for (let i = 0; i < n; i++) {
      if (out.length >= maxCap) break;
      const ang = rnd() * Math.PI * 2;
      const ejectSpeed = (0.2 + rnd() * 0.5) * (0.4 + shakuriIntensity * 1.2);
      // 沈降速度: サイズベース × 煙幕度減速 × ランダム±20%
      const terminal = sz.terminalBase * sm.terminalMul * (0.85 + rnd() * 0.3);
      const size = sz.sizeBase * (0.8 + rnd() * 0.5);
      out.push({
        x: cage.x + (rnd() - 0.5) * 0.3,
        y: cage.y + (rnd() - 0.5) * 0.4,
        vx: Math.cos(ang) * ejectSpeed * 0.6,
        vy: Math.sin(ang) * ejectSpeed * 0.5 - shakuriIntensity * 0.45,
        life: 1.0 * sz.lifeMul * sm.lifeMul,
        size: size,
        terminal: terminal,
        alpha: sm.alphaMul,
      });
      spawned++;
    }
    return spawned;
  }

  function stepParticles(particles, params, dt, rng) {
    const rnd = rng || Math.random;
    const sm = smokeLevelProps(params);
    // 煙幕強ほど横方向の乱流が強い（ふわふわ漂う）
    const diffuseX = sm.diffuse;
    const diffuseY = sm.diffuse * 0.45;
    // 寿命減少率: 標準 0.015/s。煙幕強ほどゆっくり消える
    const lifeRate = 0.015 / Math.max(1, sm.lifeMul * 0.6);
    for (let i = particles.length - 1; i >= 0; i--) {
      const p = particles[i];
      p.vy += (p.terminal - p.vy) * dt * 1.8;
      const c = current(p.y, params);
      p.vx += (c - p.vx) * dt * 1.3;
      p.vx += (rnd() - 0.5) * diffuseX;
      p.vy += (rnd() - 0.5) * diffuseY;
      p.x += p.vx * dt;
      p.y += p.vy * dt;
      p.life -= dt * lifeRate;
      if (p.life <= 0 || p.y > params.depth - 0.2 || p.x > 200 || p.x < -30) {
        particles.splice(i, 1);
      }
    }
  }

  // --- 仕掛けの静的形状 ---
  // dropVel > 0 のとき（ビシ沈降中）はハリスがビシ上方に取り残される（落ち遅れ）
  // 仕掛けは2セクション: クッションゴム（ビシ直下・短くほぼ垂直）→ ハリス（潮で流される）
  //
  // ★ ハリスはガン玉位置で物理的に分断される 2 セクション (前半: ビシ→ガン玉 / 後半: ガン玉→hook)。
  //   前半: ガン玉+hook の合計重量を上方張力として支える → 流れに強く θ_front 小
  //   後半: hook 重量だけが上方張力 → 流れに弱く θ_back 大
  //   ガン玉中央なら θ_front < θ_back となり、ハリスは「く」の字に折れる。
  function rigShape(rigDepthTarget, shakuriOffsetY, shakuriOffsetX, params, hookWeightG, dropVel) {
    const cage = { x: shakuriOffsetX, y: rigDepthTarget + shakuriOffsetY };

    const { harrisLength, harrisNo, ganDamaPos, ganDamaSize } = params;
    const cushionLength = params.cushionLength != null ? params.cushionLength : 1.0;
    const hookWeight = hookWeightG != null ? hookWeightG : (params.hookWeight || 0.5);
    const cCage = current(cage.y, params);
    const dv = dropVel || 0;

    // ガン玉位置 t (0..1): 0=ビシ直下, 1=hook 近傍
    // 優先順位: params.ganDamaPct (0-100) > params.ganDamaPos (legacy strings)
    let tGan;
    if (params.ganDamaPct != null) {
      tGan = Math.max(0.02, Math.min(0.98, params.ganDamaPct / 100));
    } else if (ganDamaPos === "chimoto") tGan = 0.05;
    else if (ganDamaPos === "near-hook") tGan = 0.92;
    else tGan = 0.50;

    // ハリス抗力: 0.5 × ρ × Cd × dia × len × v² (gf 換算済み)
    // ナイロン直径: 2号≈0.235mm, 3号≈0.286mm, 4号≈0.330mm → harrisNo に√相関
    // 係数 10.0 は実釣傾き (8m #3 で 0.25m/s で 60-70度) に合わせて経験的にチューニング
    const harrisDragCoef = (0.04 + harrisNo * 0.045) * 10.0;
    const ganW = ganDamaSize * 0.9;  // ガン玉の質量 (g 相当) — 位置で割引せず物理的に支える
    const harrisFrontLen = harrisLength * tGan;
    const harrisBackLen = harrisLength * (1 - tGan);

    // 後半セクション (ガン玉→hook): 流体抗力 vs hook 重量のみ
    const dragBack = harrisDragCoef * harrisBackLen * cCage * cCage;
    const weightBack = Math.max(0.10, hookWeight);
    let thetaBack = Math.atan2(dragBack, weightBack);
    thetaBack = Math.min(thetaBack, 1.40);  // 80度上限

    // 前半セクション (ビシ→ガン玉): 後半から伝達される抗力も含めて支える
    // 水平力 = 前半自身の抗力 + 後半から張力で伝わる水平成分 (dragBack × sin(thetaBack)/sin(90°)≈ dragBack)
    const dragFront = harrisDragCoef * harrisFrontLen * cCage * cCage;
    const totalHorizForce = dragFront + dragBack;
    const weightFront = Math.max(0.15, hookWeight + ganW);
    let thetaFront = Math.atan2(totalHorizForce, weightFront);
    thetaFront = Math.min(thetaFront, 1.30);  // 75度上限

    // クッションゴム (ビシ直下): クッション自体の抗力 + ハリス全体を支える → ほぼ垂直
    const dragCushion = harrisDragCoef * cushionLength * 0.3 * cCage * cCage;
    const weightCushion = Math.max(0.20, hookWeight + ganW);
    const thetaCushion = Math.atan2(dragCushion, weightCushion) * 0.15;  // 弾性で更に抑制

    // 沈降時の落ち遅れ (全セクション共通)
    const dragLenTotal = harrisLength + cushionLength * 0.3;
    const dropDrag = harrisDragCoef * dragLenTotal * dv * dv * 7.2;
    const lagRatio = Math.min(1, dropDrag / Math.max(0.1, weightFront + dropDrag));

    const segsCushion = 3;
    const segsHarrisFront = 7;
    const segsHarrisBack = 7;
    const pts = [];

    // --- クッションゴム区間 ---
    for (let i = 0; i <= segsCushion; i++) {
      const t = i / segsCushion;
      const vertical = cushionLength * t;
      const yLagged = -vertical * 0.85;
      const yMix = vertical * (1 - lagRatio) + yLagged * lagRatio;
      pts.push({
        x: cage.x + Math.sin(thetaCushion) * cushionLength * t,
        y: cage.y + yMix,
        section: "cushion",
      });
    }
    const cushionEnd = pts[pts.length - 1];

    // --- ハリス前半 (ビシ側→ガン玉位置)。thetaFront を適用 ---
    let frontEndX = cushionEnd.x;
    let frontEndY = cushionEnd.y;
    for (let i = 1; i <= segsHarrisFront; i++) {
      const t = i / segsHarrisFront;
      const segLen = harrisFrontLen * t;
      // 緩いカーブ: cosh 近似で前半内でも下流寄りで angle が増す (張力分布)
      const localBend = 0.7 + 0.3 * t;
      const localTheta = thetaFront * localBend;
      const vertical = Math.cos(localTheta) * segLen;
      const horiz = Math.sin(localTheta) * segLen;
      const yLagged = -vertical * 0.85;
      const yMix = vertical * (1 - lagRatio) + yLagged * lagRatio;
      pts.push({
        x: cushionEnd.x + horiz,
        y: cushionEnd.y + yMix,
        section: "harrisFront",
      });
      if (i === segsHarrisFront) {
        frontEndX = cushionEnd.x + horiz;
        frontEndY = cushionEnd.y + yMix;
      }
    }

    // --- ハリス後半 (ガン玉位置→hook)。thetaBack を適用・前半とは独立に折れる ---
    for (let i = 1; i <= segsHarrisBack; i++) {
      const t = i / segsHarrisBack;
      const segLen = harrisBackLen * t;
      // 後半は重量解放されているので t に対して比較的均等に流れる
      const localBend = 0.6 + 0.4 * t;
      const localTheta = thetaBack * localBend;
      const vertical = Math.cos(localTheta) * segLen;
      const horiz = Math.sin(localTheta) * segLen;
      const yLagged = -vertical * 0.85;
      const yMix = vertical * (1 - lagRatio) + yLagged * lagRatio;
      pts.push({
        x: frontEndX + horiz,
        y: frontEndY + yMix,
        section: "harrisBack",
      });
    }
    const hook = pts[pts.length - 1];

    // ガン玉点: 前半の最終点 (frontEnd)
    const ganDamaIdx = segsCushion + 1 + segsHarrisFront - 1;  // 前半最終インデックス
    const ganDama = pts[Math.max(0, Math.min(pts.length - 1, ganDamaIdx))];

    // theta (legacy 表示用): 平均角度
    const theta = (thetaFront + thetaBack) * 0.5;

    return {
      cage, harris: pts, hook, ganDama,
      theta, thetaFront, thetaBack, thetaCushion,
      lagRatio,
      cushionEndIdx: segsCushion,
      ganDamaIdx,
    };
  }

  function rigStep(state, params, dt) {
    // 縦方向 (バネ-ダンパ)
    const ky = 9.0, dy = 3.5;
    const ay = -ky * state.shakuriOffsetY - dy * state.shakuriVelY;
    state.shakuriVelY += ay * dt;
    state.shakuriOffsetY += state.shakuriVelY * dt;
    // 横方向: 竿先の世界 x = ROD_X_M、ここに PE 累積横変位を足す
    const tanaY = params.tanaDepth - (state.makiOffset || 0);
    const targetX = ROD_X_M + pelineDrift(params, Math.max(0, tanaY));
    state.shakuriOffsetX += (targetX - state.shakuriOffsetX) * dt * 0.8;
    // 巻き(maki) を makiTarget へ滑らかに近づける
    if (state.makiTarget == null) state.makiTarget = 0;
    if (state.makiOffset == null) state.makiOffset = 0;
    state.makiOffset += (state.makiTarget - state.makiOffset) * dt * 1.8;
  }

  function shakuri(state, params) {
    // 振り幅 = v / ω (ω=√(k/m)=√9=3 → v=3A)
    // shakuriStrokeCm 30 → v=-0.9 / 50(基本) → v=-1.5 / 150 → v=-4.5
    const strokeCm = params.shakuriStrokeCm != null ? params.shakuriStrokeCm : 50;
    state.shakuriVelY = -3.0 * (strokeCm / 100);
  }

  function nearHook(particles, hookPos, radius) {
    const r2 = radius * radius;
    let n = 0;
    for (const p of particles) {
      const dx = p.x - hookPos.x;
      const dy = p.y - hookPos.y;
      if (dx*dx + dy*dy < r2) n++;
    }
    return n;
  }

  function depthHistogram(particles, depth, bins, hookY) {
    const h = new Array(bins).fill(0);
    const step = depth / bins;
    let hookBin = -1;
    for (const p of particles) {
      const b = Math.floor(p.y / step);
      if (b >= 0 && b < bins) h[b]++;
    }
    if (hookY >= 0) hookBin = Math.max(0, Math.min(bins-1, Math.floor(hookY / step)));
    return { bins: h, hookBin, step };
  }

  // ============================================================
  // 自動最適化: ランダム検索でハリス/ガン玉/しゃくり/巻きを探索
  // 環境(水深・タナ・潮)は固定。
  // 評価: 30秒の高速シミュレーションで付けエサ周辺の平均粒子比率
  // ============================================================
  function simulateHeadless(params, durationSec, dt, rng) {
    // rng が指定されなければ Math.random (ライブ用)。指定されれば決定論。
    const rnd = rng || Math.random;
    const particles = [];
    const rs = {
      shakuriOffsetY: 0, shakuriVelY: 0, shakuriOffsetX: ROD_X_M,
      makiOffset: 0, makiTarget: 0,
      pendingMaki: [],
      pendingShakuri: [],
    };
    let chumLevel = 1.0;
    let shakuriTimer = 0;
    let leakAccum = 0;
    let scoreSum = 0;
    let scoreSamples = 0;
    let elapsed = 0;
    const warmup = durationSec * 0.4;
    const MAX_P = 1200;
    const hookW = getHookWeight(params.hookType, params.hookSize);
    const strokeCm = params.shakuriStrokeCm != null ? params.shakuriStrokeCm : 50;
    const strokeIntensity = strokeCm / 50;
    const countPerTrigger = Math.max(1, Math.round(params.shakuriCountPerTrigger || 1));

    let lastStrokeAt = -Infinity;
    const doStroke = () => {
      rs.shakuriVelY = -3.0 * (strokeCm / 100);
      const cage = {
        x: rs.shakuriOffsetX,
        y: (params.tanaDepth - rs.makiOffset) + rs.shakuriOffsetY,
      };
      spawnParticles(particles, cage, params, strokeIntensity, MAX_P, chumLevel, rnd);
      chumLevel -= shakuriConsumption(params);
      lastStrokeAt = elapsed;
      rs.pendingMaki.push({ at: elapsed + 0.5, amount: params.makiAmount });
      if (rs.makiTarget + params.makiAmount > 4.5 || chumLevel <= 0.05) {
        rs.makiTarget = 0;
        rs.makiOffset = 0;
        chumLevel = 1.0;
      }
    };

    while (elapsed < durationSec) {
      // 自動しゃくり (N連発)
      shakuriTimer += dt;
      if (shakuriTimer >= params.shakuriInterval) {
        shakuriTimer = 0;
        doStroke();
        for (let i = 1; i < countPerTrigger; i++) {
          rs.pendingShakuri.push({});
        }
      }
      // pending shakuri (連発の2発目以降): 前ストロークが収束(settled)してから発火
      if (rs.pendingShakuri.length > 0) {
        const settled = Math.abs(rs.shakuriOffsetY) < 0.05 && Math.abs(rs.shakuriVelY) < 0.12;
        const gap = elapsed - lastStrokeAt;
        if ((settled && gap >= 0.6) || gap >= 3.0) {
          rs.pendingShakuri.shift();
          doStroke();
        }
      }
      // pending maki 適用
      for (let i = rs.pendingMaki.length - 1; i >= 0; i--) {
        if (elapsed >= rs.pendingMaki[i].at) {
          rs.makiTarget += rs.pendingMaki[i].amount;
          rs.pendingMaki.splice(i, 1);
        }
      }
      // 連続漏れ
      const leak = leakRate(params);
      chumLevel = Math.max(0, chumLevel - leak * dt);
      leakAccum += dt;
      // 下窓開きで漏れ粒数も決まる (cageOpening は legacy なので cageLower に統一)
      const leakRatePart = (0.4 + cageLower(params) * 4) * Math.max(0, chumLevel);
      const need = leakAccum * leakRatePart;
      if (need >= 1) {
        const n = Math.floor(need);
        leakAccum -= n / leakRatePart;
        const cage = {
          x: rs.shakuriOffsetX,
          y: (params.tanaDepth - rs.makiOffset) + rs.shakuriOffsetY,
        };
        for (let i = 0; i < n; i++) {
          if (particles.length >= MAX_P) break;
          particles.push({
            x: cage.x + (rnd()-0.5)*0.2,
            y: cage.y + (rnd()-0.5)*0.2 + 0.1,
            vx: 0, vy: 0,
            life: 0.85,
            size: 0.6,
            terminal: 0.06 + rnd()*0.06,
          });
        }
      }
      // dynamics
      rigStep(rs, params, dt);
      stepParticles(particles, params, dt, rnd);
      const rig = rigShape(params.tanaDepth - rs.makiOffset, rs.shakuriOffsetY, rs.shakuriOffsetX, params, hookW, 0);
      if (elapsed > warmup && particles.length > 0) {
        const near = nearHook(particles, rig.hook, 1.8);
        // 比率 + 絶対値ボーナス: 退化解（粒子ほぼ無し＋たまたま近く）を抑え
        // 「コマセが豊富で針近くに留まる」設定を高評価
        const ratio = near / particles.length * 100;
        const absBonus = Math.min(8, near * 0.08);
        // 王道ペナルティ: しゃくりすぎ (>3) と 窓開けすぎ (上>0.65 / 下>0.25) を抑制
        // 下窓は「オキアミ体幅」が標準なので、開きすぎ閾値はかなり厳しめ
        const excessStrokes = Math.max(0, (params.shakuriCountPerTrigger || 1) - 3);
        const excessOpenU = Math.max(0, cageUpper(params) - 0.65);
        const excessOpenL = Math.max(0, cageLower(params) - 0.25);
        const ohdoPenalty = excessStrokes * 1.2 + excessOpenU * 12 + excessOpenL * 30;
        scoreSum += ratio + absBonus - ohdoPenalty;
        scoreSamples++;
      }
      elapsed += dt;
    }
    return scoreSamples > 0 ? scoreSum / scoreSamples : 0;
  }

  // 候補生成: 環境固定で、仕掛け側パラメータをランダム化
  // rng: 決定論用 PRNG（optimize から渡される）。未指定なら Math.random
  function makeCandidate(envParams, locked, rng) {
    locked = locked || {};
    rng = rng || Math.random;
    const hookTypes = ["madai", "iseama", "chinu", "gure"];
    const ganDamaPosOptions = ["chimoto", "mid", "near-hook"];

    const hookType = locked.hookType != null
      ? locked.hookType
      : hookTypes[Math.floor(rng() * hookTypes.length)];
    const [sLo, sHi] = HOOK_SIZE_RANGE[hookType];
    const hookSize = locked.hookSize != null
      ? locked.hookSize
      : sLo + Math.floor(rng() * (sHi - sLo + 1));

    const harrisRange = envParams.depth > 60 ? [6, 13] : [4, 11];
    const harrisLength = locked.harrisLength != null
      ? locked.harrisLength
      : Math.round((harrisRange[0] + rng() * (harrisRange[1] - harrisRange[0])) * 2) / 2;
    const harrisNo = locked.harrisNo != null
      ? locked.harrisNo
      : [2, 3, 4][Math.floor(rng() * 3)];
    const cushionLength = locked.cushionLength != null
      ? locked.cushionLength
      : Math.round((0.8 + rng() * 1.4) * 10) / 10;
    const ganDamaPos = locked.ganDamaPos != null
      ? locked.ganDamaPos
      : ganDamaPosOptions[Math.floor(rng() * 3)];
    const ganDamaSize = locked.ganDamaSize != null
      ? locked.ganDamaSize
      : Math.round(rng() * 1.2 * 20) / 20;
    // 王道 (サニー商事): 上窓 0.10-0.35 (ポロポロ程度)、下窓 0.05-0.20 (オキアミ体幅)
    const cageUpperOpening = locked.cageUpperOpening != null
      ? locked.cageUpperOpening
      : Math.round((0.10 + rng() * 0.25) * 20) / 20;
    const cageLowerOpening = locked.cageLowerOpening != null
      ? locked.cageLowerOpening
      : Math.round((0.05 + rng() * 0.15) * 20) / 20;
    const komaseSize = locked.komaseSize != null
      ? locked.komaseSize
      : ["M", "L", "L", "2L"][Math.floor(rng() * 4)];
    const smokeLevel = locked.smokeLevel != null
      ? locked.smokeLevel
      : ["weak", "weak", "medium"][Math.floor(rng() * 3)];
    const shakuriStrokeCm = locked.shakuriStrokeCm != null
      ? locked.shakuriStrokeCm
      : [60, 70, 70, 80, 80, 80, 90, 100][Math.floor(rng() * 8)];
    // 王道: 2回が標準、3回まで。4-5回は撒きすぎ
    const shakuriCountPerTrigger = locked.shakuriCountPerTrigger != null
      ? locked.shakuriCountPerTrigger
      : [1, 2, 2, 2, 2, 2, 3, 3][Math.floor(rng() * 8)];
    // 王道: 待ち時間 30-120秒 (実釣 3分=180s 相当を短縮)
    const shakuriInterval = locked.shakuriInterval != null
      ? locked.shakuriInterval
      : 30 + Math.round(rng() * 9) * 10;
    // 王道: 1サイクルで合計5-6m 巻き上げ。2回なら 2.5m, 3回なら 1.7m が中心
    const makiAmount = locked.makiAmount != null
      ? locked.makiAmount
      : Math.round((1.5 + rng() * 1.3) * 10) / 10;

    return {
      hookType, hookSize,
      cushionLength, harrisLength, harrisNo,
      ganDamaPos, ganDamaSize,
      cageUpperOpening, cageLowerOpening,
      komaseSize, smokeLevel,
      shakuriStrokeCm, shakuriCountPerTrigger,
      shakuriInterval, makiAmount,
    };
  }

  // 決定論的線形合同 PRNG（LCG）。同じ seed なら毎回同じ系列。
  function makeRng(seed) {
    let s = (seed >>> 0) || 1;
    return function() {
      s = (Math.imul(s, 1664525) + 1013904223) >>> 0;
      return s / 0x100000000;
    };
  }

  // 評価: 同じ params なら毎回同じ score (rng seed を params ハッシュから派生)
  // EVAL_RUNS=3 だが、各 run の seed を派生して "物理ノイズの平均化" を維持
  function evalParams(params, simDuration, evalRuns) {
    simDuration = simDuration || 120;
    evalRuns = evalRuns || 3;
    // params のシリアライズ → ハッシュ → 各 run の seed
    const key = JSON.stringify(params);
    let hash = 2166136261;
    for (let i = 0; i < key.length; i++) {
      hash = Math.imul(hash ^ key.charCodeAt(i), 16777619);
    }
    let sum = 0;
    for (let r = 0; r < evalRuns; r++) {
      const runSeed = Math.imul(hash ^ (r + 1), 2654435761) >>> 0;
      const runRng = makeRng(runSeed);
      sum += simulateHeadless({...params, autoShakuri: true}, simDuration, 0.1, runRng);
    }
    return sum / evalRuns;
  }

  // 決定論的最適化:
  //   Phase 1: 主要 3軸 (shakuriStrokeCm / shakuriCountPerTrigger / cageUpperOpening) を粗いグリッドで全探索
  //            残り (harrisLength, harrisNo, ganDamaPos, ganDamaSize, hookType/Size, etc) は環境推奨値で固定
  //   Phase 2: Phase 1 の TOP-K を起点に、各軸 ±1 ステップの近傍を試して改善が止まるまで反復
  //   Phase 3: ハリス/ガン玉の細部を Phase 2 ベストを固定して局所探索
  // 全工程で Math.random() は一切使用しない → 同じ環境では毎回同じ best が返る。
  function optimize(envParams, iterations, locked) {
    locked = locked || {};
    const env = {
      depth: envParams.depth,
      tanaDepth: envParams.tanaDepth,
      tideSpeed: envParams.tideSpeed,
      tideDepthFactor: envParams.tideDepthFactor,
      peNo: locked.peNo != null ? locked.peNo : envParams.peNo,
      bishiNo: locked.bishiNo != null ? locked.bishiNo : envParams.bishiNo,
      dropSpeed: envParams.dropSpeed,
      swellHeight: envParams.swellHeight,
      swellPeriod: envParams.swellPeriod,
    };

    // 軸定義 (王道範囲)
    const AXES = {
      shakuriStrokeCm:        [50, 60, 70, 80, 90, 100],
      shakuriCountPerTrigger: [1, 2, 3],
      cageUpperOpening:       [0.10, 0.15, 0.20, 0.25, 0.30, 0.35],
      cageLowerOpening:       [0, 0.05, 0.10, 0.15],
      makiAmount:             [1.5, 2.0, 2.5, 3.0],
      shakuriInterval:        [30, 45, 60, 90, 120],
      harrisLength:           env.depth > 60 ? [7, 9, 11] : [5, 7, 9, 11],
      harrisNo:               [2, 3, 4],
      ganDamaPct:             [5, 25, 50, 75, 95],  // ビシ側→針側%
      ganDamaSize:            [0, 0.3, 0.5, 0.8],
      cushionLength:          [1.0, 1.5],
      hookType:               ["madai", "iseama"],
      hookSize:               [9, 10, 11],
      komaseSize:             ["L", "2L"],
      smokeLevel:             ["weak", "medium"],
    };
    // ロックされた軸は固定値だけのリストに置換
    const axes = {};
    for (const k of Object.keys(AXES)) {
      axes[k] = locked[k] != null ? [locked[k]] : AXES[k];
    }

    // 初期推測 (王道セットアップ)
    const start = {
      shakuriStrokeCm: 80, shakuriCountPerTrigger: 2,
      cageUpperOpening: 0.25, cageLowerOpening: 0,
      makiAmount: 2.5, shakuriInterval: 60,
      harrisLength: env.depth > 60 ? 9 : 8,
      harrisNo: 3, ganDamaPct: 50, ganDamaSize: 0.3,
      cushionLength: 1.0,
      hookType: "madai", hookSize: 10,
      komaseSize: "L", smokeLevel: "weak",
    };
    // ロックを優先
    for (const k of Object.keys(start)) {
      if (locked[k] != null) start[k] = locked[k];
    }
    // 各軸の値がリストに無ければ最も近い値にスナップ
    for (const k of Object.keys(start)) {
      if (axes[k] && !axes[k].includes(start[k])) {
        if (typeof start[k] === "number") {
          let nearest = axes[k][0], d = Infinity;
          for (const v of axes[k]) {
            const dd = Math.abs(v - start[k]);
            if (dd < d) { d = dd; nearest = v; }
          }
          start[k] = nearest;
        } else {
          start[k] = axes[k][0];
        }
      }
    }

    // 評価ヘルパ: params 全体を merged して評価
    const evalCache = {};
    function evalCand(cand) {
      const merged = { ...env, ...cand };
      const k = JSON.stringify(cand);
      if (evalCache[k] != null) return evalCache[k];
      const s = evalParams(merged, 90, 2);  // 90秒×2run で速度優先
      evalCache[k] = s;
      return s;
    }

    // Coordinate descent: 各軸を順番にスイープして best を更新
    // 全軸 1pass = 約 (6+3+6+4+4+5+4+3+3+4+2+2+3+2+2) = 53 evals
    // 2pass で 106 evals 程度 → 1.5-2秒
    let best = { ...start };
    let bestScore = evalCand(best);
    const PASSES = 2;
    const axisOrder = [
      "shakuriCountPerTrigger", "cageUpperOpening", "shakuriStrokeCm",
      "shakuriInterval", "makiAmount",
      "harrisLength", "harrisNo", "ganDamaPct", "ganDamaSize",
      "cageLowerOpening", "cushionLength",
      "komaseSize", "smokeLevel", "hookType", "hookSize",
    ];
    for (let pass = 0; pass < PASSES; pass++) {
      let improved = false;
      for (const axis of axisOrder) {
        const values = axes[axis];
        if (!values || values.length <= 1) continue;
        let localBest = best[axis];
        let localScore = bestScore;
        for (const v of values) {
          if (v === best[axis]) continue;
          const cand = { ...best, [axis]: v };
          const s = evalCand(cand);
          if (s > localScore) {
            localScore = s;
            localBest = v;
          }
        }
        if (localBest !== best[axis]) {
          best = { ...best, [axis]: localBest };
          bestScore = localScore;
          improved = true;
        }
      }
      if (!improved) break;  // 収束
    }

    return { best, score: bestScore };
  }

  // 現行設定のスコア（再現性のため複数回平均・seed 派生で完全決定論）
  function scoreParams(params, runs) {
    return evalParams(params, 120, runs || 3);
  }

  return {
    ROD_X_M,
    current, pelineDrift, computeDropSpeed,
    spawnParticles, stepParticles,
    rigShape, rigStep, shakuri,
    nearHook, depthHistogram,
    HOOK_WEIGHTS, HOOK_TYPE_LABEL, HOOK_SIZE_RANGE, getHookWeight,
    shakuriConsumption, leakRate,
    simulateHeadless, optimize, scoreParams, evalParams,
    makeRng,
  };
})();
