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
    // ★ 実釣のリアルな放出量に合わせて係数強化
    //   上窓 0.35 + ストローク 100cm (factor=2) で 1ストローク ≈ 33% 放出
    //     → 3発撃てば 1ビシほぼ空 (実釣で 1回投入で 1ビシ使い切る感覚)
    //   上窓 0.10 + ストローク 50cm で ≈ 4% (穴ほぼ閉=ためてポロポロ)
    return 0.005 + cageUpper(params) * 0.16 * strokeFactor;
  }
  // 連続漏れ (毎秒) 容量比 — 下窓開けると漂う
  //   下窓 0.15 で 0.012/s → 約 80秒で1ビシ空 (実釣で 1-2分での持続放出感覚)
  //   下窓 0.50 で 0.04/s → 25秒で1ビシ
  function leakRate(params) {
    return cageLower(params) * 0.08;
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

    // モトス区間 (上のハリス): cushion 下〜サル管。モトス無効なら長さ 0
    const motosEnabled = params.motosEnabled !== false;
    const motosLength = motosEnabled ? (params.motosLength != null ? params.motosLength : 0) : 0;
    const motosNo = params.motosNo != null ? params.motosNo : 5;

    // ガン玉位置 t (0..1) は HARRIS 内 (サル管〜針) の比率: 0=サル管直下, 1=hook近傍
    let tGan;
    if (params.ganDamaPct != null) {
      tGan = Math.max(0.02, Math.min(0.98, params.ganDamaPct / 100));
    } else if (ganDamaPos === "chimoto") tGan = 0.05;
    else if (ganDamaPos === "near-hook") tGan = 0.92;
    else tGan = 0.50;

    // 抗力係数: ナイロン直径 ∝ √号数。係数 10.0 は実釣傾きに合わせ調整済
    const dragCoefByNo = (no) => (0.04 + no * 0.045) * 10.0;
    const harrisDragCoef = dragCoefByNo(harrisNo);
    const motosDragCoef = dragCoefByNo(motosNo);
    const ganW = ganDamaSize * 0.9;
    const harrisFrontLen = harrisLength * tGan;
    const harrisBackLen = harrisLength * (1 - tGan);

    // 後半セクション (ガン玉→hook): 流体抗力 vs hook 重量のみ
    const dragBack = harrisDragCoef * harrisBackLen * cCage * cCage;
    const weightBack = Math.max(0.10, hookWeight);
    let thetaBack = Math.atan2(dragBack, weightBack);
    thetaBack = Math.min(thetaBack, 1.40);

    // 前半セクション (サル管→ガン玉): 後半から伝達される抗力も含めて支える
    const dragHarrisFront = harrisDragCoef * harrisFrontLen * cCage * cCage;
    const harrisHorizForce = dragHarrisFront + dragBack;
    const weightFront = Math.max(0.15, hookWeight + ganW);
    let thetaFront = Math.atan2(harrisHorizForce, weightFront);
    thetaFront = Math.min(thetaFront, 1.30);

    // モトス区間 (cushion下〜サル管): ハリス全体+ガン玉+hook の合計重量を支え、抗力は自身+ハリス両半
    const dragMotos = motosDragCoef * motosLength * cCage * cCage;
    const motosHorizForce = dragMotos + harrisHorizForce;
    const weightMotos = Math.max(0.15, hookWeight + ganW);
    let thetaMotos = motosLength > 0.01 ? Math.atan2(motosHorizForce, weightMotos) : 0;
    thetaMotos = Math.min(thetaMotos, 1.30);

    // 互換: 旧コードが totalHorizForce / dragFront を見るので alias
    const dragFront = dragHarrisFront;
    const totalHorizForce = harrisHorizForce + dragMotos;

    // クッションゴム物理:
    //   素材: 天然/合成ゴム (NR)、密度 ~1.05 g/cm³
    //   海水密度: 1.025 g/cm³ → ほぼ中性浮力 (-0.025 g/cm³ で微沈)
    //   径: 標準 2.5mm (1m あたり質量 5.16g、浮力 5.03g → 水中正味重量 0.13g)
    //   抗力: 直径比 (2.5 / 0.286mm) = 8.74倍/m vs ハリス #3
    //   ハリス #3 単位係数 (0.04 + 3*0.045) * 10 = 1.75 → クッション 2.5mm = 1.75 * 8.74 / 9 = 1.70/m
    //     (ハリス号数項を外しシンプル化: cushion固有定数 1.70/m × 径mm)
    const cushionDiaMM = params.cushionDiaMM != null ? params.cushionDiaMM : 2.5;
    const cushionDragCoefPerM = cushionDiaMM * 0.68;  // 2.5mm → 1.70/m, harrisと整合
    const dragCushion = cushionDragCoefPerM * cushionLength * cCage * cCage;
    // クッションは天秤(E)に吊られ、下にハリス・ガン玉・hook を支える。
    // 上方張力 ≈ (ganW + hookW)、水平力 ≈ dragCushion + dragHarrisFront + dragHarrisBack (下から伝達)
    const cushionHorizForce = dragCushion + totalHorizForce;
    const weightCushion = Math.max(0.20, hookWeight + ganW);
    // 弾性ゴムのため瞬間張力に対しては伸び・歪みで吸収するが、定常状態では張力方向に揃う
    // → 物理通りの計算 (旧 0.15 抑制は廃止)
    let thetaCushion = Math.atan2(cushionHorizForce, weightCushion);
    thetaCushion = Math.min(thetaCushion, 1.30);  // 75度上限

    // 沈降時の落ち遅れ (全セクション共通)
    const dragLenTotal = harrisLength + cushionLength * 0.3;
    const dropDrag = harrisDragCoef * dragLenTotal * dv * dv * 7.2;
    const lagRatio = Math.min(1, dropDrag / Math.max(0.1, weightFront + dropDrag));

    const segsCushion = 3;
    const segsMotos = motosLength > 0.01 ? 4 : 0;
    const segsHarrisFront = 7;
    const segsHarrisBack = 7;
    const pts = [];

    // ★ 落とし込み中の水平drift抑制:
    //   cage が速く落ちると harris にかかる drag は vertical 方向が支配的になる
    //   (drop drag >> current drag) → 水平 drift は無視できる。
    //   x オフセットを (1 - lagRatio) で混合し、lagRatio=1 (フル沈降) では
    //   x = cage.x (真上トレイル)、lagRatio=0 (静定) では通常の current drift。
    const xMix = 1 - lagRatio;

    // --- クッションゴム区間 ---
    for (let i = 0; i <= segsCushion; i++) {
      const t = i / segsCushion;
      const vertical = cushionLength * t;
      const yLagged = -vertical * 0.85;
      const yMix = vertical * (1 - lagRatio) + yLagged * lagRatio;
      pts.push({
        x: cage.x + Math.sin(thetaCushion) * cushionLength * t * xMix,
        y: cage.y + yMix,
        section: "cushion",
      });
    }
    const cushionEnd = pts[pts.length - 1];

    // --- モトス区間 (cushion下〜サル管) ---
    let motosEndX = cushionEnd.x;
    let motosEndY = cushionEnd.y;
    if (segsMotos > 0) {
      for (let i = 1; i <= segsMotos; i++) {
        const t = i / segsMotos;
        const segLen = motosLength * t;
        const localBend = 0.7 + 0.3 * t;
        const localTheta = thetaMotos * localBend;
        const vertical = Math.cos(localTheta) * segLen;
        const horiz = Math.sin(localTheta) * segLen * xMix;
        const yLagged = -vertical * 0.85;
        const yMix = vertical * (1 - lagRatio) + yLagged * lagRatio;
        pts.push({
          x: cushionEnd.x + horiz,
          y: cushionEnd.y + yMix,
          section: "motos",
        });
        if (i === segsMotos) {
          motosEndX = cushionEnd.x + horiz;
          motosEndY = cushionEnd.y + yMix;
        }
      }
    }

    // --- ハリス前半 (サル管→ガン玉位置)。thetaFront を適用 ---
    let frontEndX = motosEndX;
    let frontEndY = motosEndY;
    for (let i = 1; i <= segsHarrisFront; i++) {
      const t = i / segsHarrisFront;
      const segLen = harrisFrontLen * t;
      const localBend = 0.7 + 0.3 * t;
      const localTheta = thetaFront * localBend;
      const vertical = Math.cos(localTheta) * segLen;
      const horiz = Math.sin(localTheta) * segLen * xMix;
      const yLagged = -vertical * 0.85;
      const yMix = vertical * (1 - lagRatio) + yLagged * lagRatio;
      pts.push({
        x: motosEndX + horiz,
        y: motosEndY + yMix,
        section: "harrisFront",
      });
      if (i === segsHarrisFront) {
        frontEndX = motosEndX + horiz;
        frontEndY = motosEndY + yMix;
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
      const horiz = Math.sin(localTheta) * segLen * xMix;
      const yLagged = -vertical * 0.85;
      const yMix = vertical * (1 - lagRatio) + yLagged * lagRatio;
      pts.push({
        x: frontEndX + horiz,
        y: frontEndY + yMix,
        section: "harrisBack",
      });
    }
    const hook = pts[pts.length - 1];

    // 各区間の終端インデックス (描画用)
    const cushionEndIdx = segsCushion;  // 0..segsCushion (cushion 部)
    const motosEndIdx = cushionEndIdx + segsMotos;  // モトス区間最終点 = サル管位置
    const harrisFrontEndIdx = motosEndIdx + segsHarrisFront;  // 前半最終 = ガン玉位置
    const ganDamaIdx = harrisFrontEndIdx;
    const ganDama = pts[Math.max(0, Math.min(pts.length - 1, ganDamaIdx))];
    const saruKanPt = segsMotos > 0 ? pts[motosEndIdx] : null;

    const theta = (thetaFront + thetaBack) * 0.5;

    return {
      cage, harris: pts, hook, ganDama, saruKanPt,
      theta, thetaFront, thetaBack, thetaCushion, thetaMotos,
      lagRatio,
      cushionEndIdx, motosEndIdx, harrisFrontEndIdx, ganDamaIdx,
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
    // ★ 実釣準拠: 落とし込み目安 = ビシ位置 (指示棚 + dropOffsetM)
    //   実釣標準 dropOffsetM=+5 → ビシは指示棚 5m 下 (タナ下5m)
    //   makiOffset = -dropOffsetM (負値で cage が指示棚より下に位置)
    const _motosLen = (params.motosEnabled === false ? 0 : (params.motosLength || 0));
    const _rigLen = (params.cushionLength || 1) + _motosLen + (params.harrisLength || 6.5);
    const _drop = params.dropOffsetM != null ? params.dropOffsetM : 5;
    const _initMaki = -_drop;
    const rs = {
      shakuriOffsetY: 0, shakuriVelY: 0, shakuriOffsetX: ROD_X_M,
      makiOffset: _initMaki, makiTarget: _initMaki,
      pendingMaki: [],
      pendingShakuri: [],
    };
    let chumLevel = 1.0;
    let shakuriTimer = 0;
    let leakAccum = 0;
    let elapsed = 0;
    // warmup: 短くしてユーザー体感 (cycle 投入後すぐ評価開始) に近づける
    //   旧 40% (240s sim で 96s) は steady-state 寄りで楽観的すぎ、ユーザーが
    //   見る 30-60s 区間と乖離していた。固定 15s = 落とし込み + 初期しゃくり 1-2発分。
    const warmup = Math.min(15, durationSec * 0.1);
    // 5基準スコア用カウンタ
    const scoreCounters = {
      totalFrames: 0,
      goodFrames: 0,    // 同調 (rate>=2) かつタナ OK のフレーム
      okFrames: 0,      // 緩い基準
      sumRatio: 0,
      peakRatio: 0,     // ピーク同調率 (live cycleScore の peakSync と整合)
    };
    const MAX_P = 1200;
    const hookW = getHookWeight(params.hookType, params.hookSize);
    const strokeCm = params.shakuriStrokeCm != null ? params.shakuriStrokeCm : 50;
    const strokeIntensity = strokeCm / 50;
    const countPerTrigger = Math.max(1, Math.round(params.shakuriCountPerTrigger || 1));
    // 巻き上げ上限: ビシが水面手前まで来ない範囲 (rigLen + 1m バッファ)
    const _maxMaki = _initMaki + _rigLen + 1;

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
    };

    // === UI 側と整合する state machine ===
    //   shakuri (N発撃ち中) → biting (食わせ待ち shakuriInterval秒) → dropping (drop back) → shakuri
    let autoState = "idle";
    let biteTimer = 0;

    while (elapsed < durationSec) {
      // === 状態遷移 ===
      if (autoState === "idle") {
        doStroke();
        for (let i = 1; i < countPerTrigger; i++) rs.pendingShakuri.push({});
        autoState = "shakuri";
        biteTimer = 0;
      } else if (autoState === "shakuri") {
        // 全 N 発 + maki 完了 + 動的収束 を待つ
        const allStrokesDone = rs.pendingShakuri.length === 0;
        const allMakiDone = rs.pendingMaki.length === 0;
        const rigSettled = Math.abs(rs.shakuriVelY) < 0.12 && Math.abs(rs.shakuriOffsetY) < 0.05;
        const makiSettled = Math.abs(rs.makiTarget - rs.makiOffset) < 0.08;
        if (allStrokesDone && allMakiDone && rigSettled && makiSettled) {
          autoState = "biting";
          biteTimer = 0;
        }
      } else if (autoState === "biting") {
        biteTimer += dt;
        if (biteTimer >= params.shakuriInterval) {
          // サイクル分 (N×makiAmount) を巻き戻して落とし込み位置へ
          // ビシを落としこみ位置 (_initMaki) に直接戻す (累積 drift 防止)
          rs.makiTarget = _initMaki;
          autoState = "dropping";
        }
      } else if (autoState === "dropping") {
        const makiSettled = Math.abs(rs.makiTarget - rs.makiOffset) < 0.08;
        if (makiSettled) {
          // 次サイクル開始
          autoState = "idle";
        }
      }
      // コマセ枯渇 → リセット (ビシ回収相当)
      if (chumLevel <= 0.05) {
        rs.makiTarget = _initMaki;
        rs.makiOffset = _initMaki;
        chumLevel = 1.0;
        rs.pendingShakuri = [];
        rs.pendingMaki = [];
        autoState = "idle";
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
      if (elapsed > warmup) {
        // === 評価基準 (コマセマダイの実釣に整合) ===
        //   指示棚 = ビシを止める作戦水深、付け餌は指示棚に置く必要は無い。
        //   マダイは底寄り→コマセに誘われて上がる。付け餌はビシより下の
        //   コマセ帯 (潮で流れたコマセ雲) に自然に置かれていれば良い。
        // 1. 付け餌とコマセの同調率 (粒子/hook 近傍 1.8m)
        const near = particles.length > 0 ? nearHook(particles, rig.hook, 1.8) : 0;
        const ratio = particles.length > 0 ? (near / particles.length * 100) : 0;
        // 2. 付け餌がビシより下にあるか (実釣の鉄則: ビシ下のコマセ帯)
        const hookBelowCage = rig.hook.y > rig.cage.y + 0.5;
        // 3. 付け餌が中〜深場ゾーンか (タナ以深〜底1m上まで)
        //    マダイが底からコマセで上がってきて食う範囲
        const hookDeepEnough = rig.hook.y >= params.tanaDepth - 1
                            && rig.hook.y <= params.depth - 1;
        // 4. ビシが指示棚に近いか (船長指示の絶対遵守)
        const cageDiff = Math.abs(rig.cage.y - params.tanaDepth);
        const cageOnTana = cageDiff <= 1.5;
        // 「ビシ指示棚 & 付け餌ビシ下のコマセ帯 & 同調」が良いフレーム
        const goodFrame = (ratio >= 2.0 && hookBelowCage && hookDeepEnough && cageOnTana) ? 1 : 0;
        const okFrame = (ratio >= 0.5 && hookBelowCage && cageDiff <= 2.5) ? 1 : 0;
        scoreCounters.totalFrames += 1;
        scoreCounters.goodFrames += goodFrame;
        scoreCounters.okFrames += okFrame;
        scoreCounters.sumRatio += ratio;
        if (ratio > scoreCounters.peakRatio) scoreCounters.peakRatio = ratio;
      }
      elapsed += dt;
    }

    // === 最終スコア計算 (5基準) ===
    //   #1 sustained alignment: goodFrames/totalFrames の割合 (高いほど良)
    //   #2 hook at tana (held): 平均タナズレを penalty 化
    //   #3 cycle duration: shakuriInterval が標準範囲 (60-180s) にあれば加点
    //   #4 chum usage: 1サイクル消費が 8-15% に近いほど良
    //   #5 action validity: しゃくり/巻き/落とし が機能していること
    if (scoreCounters.totalFrames === 0) return 0;
    const sustainRate = scoreCounters.goodFrames / scoreCounters.totalFrames;
    const okRate      = scoreCounters.okFrames   / scoreCounters.totalFrames;
    const meanRatio    = scoreCounters.sumRatio    / scoreCounters.totalFrames;
    const peakSync    = scoreCounters.peakRatio || 0;

    // ★ リアルタイム合否表示と完全に同じスコア式 (app.jsx cycleScore と整合)
    //   旧式はアクション妥当性ボーナス・コマセ消費ボーナスを多数含み、
    //   実物理で sync しない config でも 100+ 点を取れてしまい、
    //   live mode のスコア 0 と乖離していた。
    //   コマセマダイの実釣評価は「ビシ指示棚 + 付け餌コマセ帯 + 同調」が全て。
    const baseScore = sustainRate * 60 + okRate * 15;
    const syncBonus = Math.min(15, meanRatio * 1.5);
    const peakBonus = Math.min(10, peakSync * 0.8);
    const total = Math.max(0, Math.min(100, baseScore + syncBonus + peakBonus));

    if (typeof window !== 'undefined' && window.__lastScoreDump !== false) {
      window.__lastScoreDump = {
        total, baseScore, syncBonus, peakBonus,
        sustainRate, okRate, meanRatio, peakSync,
        totalFrames: scoreCounters.totalFrames,
        goodFrames: scoreCounters.goodFrames,
      };
    }
    return total;
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
      makiAmount:             [1.0, 1.5, 2.0, 2.5],  // 実釣標準 1.5-2m/ストローク (3m超は不自然)
      shakuriInterval:        [60, 90, 120, 180, 240, 300],  // 活性高 120 / 標準 180 / 食い渋り 240-300
      harrisLength:           env.depth > 60 ? [5, 7, 9] : [3, 5, 7, 9],
      harrisNo:               [2, 3, 4],
      motosLength:            [0, 1.0, 1.5, 2.0],  // 0 = モトス無効相当 (実質サル管なし)
      motosNo:                [4, 5, 6, 7],
      dropOffsetM:            [3, 5, 7],  // 落とし込み目安 タナ下3-7m
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

    // ★ 多点出発戦略: harris長 × ガン玉構成 × interval を変えた seed から座標降下を回し、最良を採用
    //   局所最適固定を解消 (短harris + chimoto + 長interval が最強パターンを取り逃さないように)
    //   先頭は ENV ベース seed (現行ユーザー設定) - これを必ず探索範囲に入れて
    //   「推奨 < 現行」の矛盾を防ぐ
    const userSeed = {
      harrisLength: envParams.harrisLength, cushionLength: envParams.cushionLength,
      shakuriCountPerTrigger: envParams.shakuriCountPerTrigger,
      makiAmount: envParams.makiAmount, shakuriStrokeCm: envParams.shakuriStrokeCm,
      cageUpperOpening: envParams.cageUpperOpening,
      cageLowerOpening: envParams.cageLowerOpening != null ? envParams.cageLowerOpening : 0,
      shakuriInterval: envParams.shakuriInterval,
      harrisNo: envParams.harrisNo,
      ganDamaPct: envParams.ganDamaPct != null ? envParams.ganDamaPct : 50,
      ganDamaSize: envParams.ganDamaSize,
      hookType: envParams.hookType, hookSize: envParams.hookSize,
      komaseSize: envParams.komaseSize, smokeLevel: envParams.smokeLevel,
      motosLength: envParams.motosLength != null ? envParams.motosLength : 1.5,
      motosNo: envParams.motosNo != null ? envParams.motosNo : 5,
      dropOffsetM: envParams.dropOffsetM != null ? envParams.dropOffsetM : 5,
    };
    const SEEDS = [
      userSeed,
      // A: 短ハリス + ガン玉mid 0.3g + 長interval (標準シナリオ)
      { harrisLength: 5,  cushionLength: 1.0, shakuriCountPerTrigger: 2, makiAmount: 2.0,
        shakuriStrokeCm: 80, cageUpperOpening: 0.25, cageLowerOpening: 0,
        shakuriInterval: 240, harrisNo: 3, ganDamaPct: 50, ganDamaSize: 0.3,
        hookType: "madai", hookSize: 10, komaseSize: "L", smokeLevel: "weak",
        motosLength: 1.5, motosNo: 5, dropOffsetM: 5 },
      // B: 中ハリス + ガン玉mid 0.5g + 標準サイクル
      { harrisLength: 7,  cushionLength: 1.0, shakuriCountPerTrigger: 2, makiAmount: 2.5,
        shakuriStrokeCm: 80, cageUpperOpening: 0.30, cageLowerOpening: 0,
        shakuriInterval: 180, harrisNo: 3, ganDamaPct: 50, ganDamaSize: 0.5,
        hookType: "madai", hookSize: 10, komaseSize: "L", smokeLevel: "weak",
        motosLength: 1.5, motosNo: 5, dropOffsetM: 5 },
      // C: 長ハリス (深場/速潮)
      { harrisLength: env.depth > 60 ? 11 : 9, cushionLength: 1.5,
        shakuriCountPerTrigger: 3, makiAmount: 1.5,
        shakuriStrokeCm: 90, cageUpperOpening: 0.30, cageLowerOpening: 0,
        shakuriInterval: 180, harrisNo: 4, ganDamaPct: 50, ganDamaSize: 0.5,
        hookType: "madai", hookSize: 10, komaseSize: "L", smokeLevel: "weak",
        motosLength: 1.5, motosNo: 5, dropOffsetM: 5 },
      // D: 短ハリス + チモト + ガン玉なし + 長interval (流し釣り系)
      { harrisLength: 5,  cushionLength: 1.0, shakuriCountPerTrigger: 2, makiAmount: 2.0,
        shakuriStrokeCm: 90, cageUpperOpening: 0.35, cageLowerOpening: 0.10,
        shakuriInterval: 240, harrisNo: 4, ganDamaPct: 5, ganDamaSize: 0,
        hookType: "madai", hookSize: 10, komaseSize: "L", smokeLevel: "weak",
        motosLength: 1.5, motosNo: 5, dropOffsetM: 5 },
      // E: 中ハリス + ハリス下 + ガン玉中 (重ガン玉戦法)
      { harrisLength: 7,  cushionLength: 1.0, shakuriCountPerTrigger: 2, makiAmount: 2.5,
        shakuriStrokeCm: 90, cageUpperOpening: 0.30, cageLowerOpening: 0,
        shakuriInterval: 180, harrisNo: 3, ganDamaPct: 95, ganDamaSize: 0.5,
        hookType: "madai", hookSize: 10, komaseSize: "L", smokeLevel: "weak",
        motosLength: 1.5, motosNo: 5, dropOffsetM: 5 },
      // F: 長ハリス + チモト軽 + 速サイクル (活性高)
      { harrisLength: env.depth > 60 ? 11 : 9, cushionLength: 1.0,
        shakuriCountPerTrigger: 3, makiAmount: 1.5,
        shakuriStrokeCm: 100, cageUpperOpening: 0.30, cageLowerOpening: 0,
        shakuriInterval: 120, harrisNo: 4, ganDamaPct: 5, ganDamaSize: 0.3,
        hookType: "madai", hookSize: 10, komaseSize: "L", smokeLevel: "weak",
        motosLength: 1.5, motosNo: 5, dropOffsetM: 5 },
    ];
    // 各 seed を「ロック反映 + axes 内最近接スナップ」で正規化するヘルパ
    function normalizeStart(seed) {
      const s = { ...seed };
      for (const k of Object.keys(s)) {
        if (locked[k] != null) s[k] = locked[k];
      }
      for (const k of Object.keys(s)) {
        if (axes[k] && !axes[k].includes(s[k])) {
          if (typeof s[k] === "number") {
            let nearest = axes[k][0], d = Infinity;
            for (const v of axes[k]) {
              const dd = Math.abs(v - s[k]);
              if (dd < d) { d = dd; nearest = v; }
            }
            s[k] = nearest;
          } else {
            s[k] = axes[k][0];
          }
        }
      }
      return s;
    }

    // 評価ヘルパ: params 全体を merged して評価
    const evalCache = {};
    function evalCand(cand) {
      const merged = { ...env, ...cand };
      const k = JSON.stringify(cand);
      if (evalCache[k] != null) return evalCache[k];
      const s = evalParams(merged, 240, 2);  // 240秒×2run で 標準サイクル 1-2回 評価可能
      evalCache[k] = s;
      return s;
    }

    // Coordinate descent サブルーチン
    const axisOrder = [
      "shakuriCountPerTrigger", "cageUpperOpening", "shakuriStrokeCm",
      "shakuriInterval", "makiAmount",
      "harrisLength", "harrisNo", "motosLength", "motosNo", "dropOffsetM",
      "ganDamaPct", "ganDamaSize",
      "cageLowerOpening", "cushionLength",
      "komaseSize", "smokeLevel", "hookType", "hookSize",
    ];
    function descendFromStart(startSeed) {
      let best = normalizeStart(startSeed);
      let bestScore = evalCand(best);
      const PASSES = 2;
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

    // 各 seed から座標降下を実行し、最良を採用
    let globalBest = null;
    let globalScore = -Infinity;
    for (const seed of SEEDS) {
      const r = descendFromStart(seed);
      if (r.score > globalScore) {
        globalScore = r.score;
        globalBest = r.best;
      }
    }
    return { best: globalBest, score: globalScore };
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
