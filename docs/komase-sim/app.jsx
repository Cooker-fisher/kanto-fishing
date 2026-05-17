/* ============================================================
   app.jsx — メインアプリ
   ============================================================ */

const DEFAULT_PARAMS = {
  depth: 50,
  tanaDepth: 30,
  tideSpeed: 0.35,
  tideDepthFactor: 0.5,

  peNo: 3,
  bishiNo: 80,
  // ビシ窓を上下分離（サニー商事 / TSURIMARU 王道準拠）
  // 上窓: しゃくり時の主放出口だが「ポロポロ程度」が標準＝30%以下
  // 下窓: 「オキアミ体幅」≒ 全閉に近い (連続漏れは控えめ)
  cageUpperOpening: 0.25,
  cageLowerOpening: 0,
  // コマセ粒サイズ: M/L/2L/3L (将来 アミエビ/イワシミンチ拡張用)
  komaseSize: "L",
  // 煙幕度: weak (オキアミ大粒) / medium (オキアミ+ アミ混合) / strong (アミ・ミンチ)
  smokeLevel: "weak",

  cushionLength: 1.0,
  // モトス (上の太ハリス・サル管の上): 通常 4-7号 フロロカーボン
  motosEnabled: true,
  motosLength: 1.5,
  motosNo: 5,
  // サル管 (モトス-ハリス連結金具): 10-22号 程度。流体抵抗ほぼ無視
  saruKanEnabled: true,
  saruKanSize: 14,
  // ハリス (下の細ハリス・サル管の下〜針): 通常 2-5号 フロロカーボン
  harrisLength: 6.5,
  harrisNo: 3,
  hookType: "madai",
  hookSize: 10,

  // ビシ落としこみ位置: 指示棚 +dropOffsetM が hook 初期目標 (default = タナ下 5m)
  dropOffsetM: 5,

  ganDamaPos: "mid",
  ganDamaPct: 50,  // ガン玉位置: ビシ側(0)→針側(100) % で連続指定
  ganDamaSize: 0.2,

  // 関東コマセマダイ標準: 70-80cm 刻みで3回しゃくり、合計約5m 巻き上げ、3分待ち
  shakuriStrokeCm: 80,
  shakuriCountPerTrigger: 3,
  makiAmount: 1.7,
  dropAmount: 0.5,
  shakuriInterval: 30.0,
  autoShakuri: false,
  // 落とし込み速度はビシ号数から物理計算（dropSpeed は physicsParams で導出）
  // うねり (海況セクション)
  swellHeight: 0.5,
  swellPeriod: 6.0,
};

const LOCKABLE_PARAMS = [
  "peNo", "bishiNo",
  "cageUpperOpening", "cageLowerOpening",
  "komaseSize", "smokeLevel",
  "cushionLength",
  "motosEnabled", "motosLength", "motosNo",
  "saruKanEnabled", "saruKanSize",
  "harrisLength", "harrisNo",
  "hookType", "hookSize",
  "ganDamaPos", "ganDamaPct", "ganDamaSize",
  "shakuriStrokeCm", "shakuriCountPerTrigger",
  "makiAmount", "dropAmount", "shakuriInterval", "dropOffsetM",
];

const PRESETS = [
  // ── サイクル系 ──
  { key: "default",  label: "標準 3分サイクル", group: "cycle", patch: {} },
  { key: "kuripote", label: "食い渋り (4-5分)", group: "cycle",
    patch: { harrisLength: 12, harrisNo: 2, hookType: "madai", hookSize: 8, ganDamaSize: 0,
             shakuriStrokeCm: 60, shakuriCountPerTrigger: 2,
             cageUpperOpening: 0.20, cageLowerOpening: 0,
             komaseSize: "L", smokeLevel: "weak",
             makiAmount: 2.5, shakuriInterval: 60 } },
  { key: "highact",  label: "活性高 (2-3分)", group: "cycle",
    patch: { shakuriStrokeCm: 75, shakuriCountPerTrigger: 3,
             cageUpperOpening: 0.30, cageLowerOpening: 0,
             makiAmount: 1.7, shakuriInterval: 20 } },

  // ── 海況系 ──
  { key: "trendrun", label: "二枚潮", group: "cond",
    patch: { tideSpeed: 0.55, tideDepthFactor: 0.25, harrisNo: 3,
             ganDamaPos: "near-hook", ganDamaSize: 0.5, makiAmount: 1.7 } },
  { key: "fastide",  label: "速潮", group: "cond",
    patch: { tideSpeed: 0.8, tideDepthFactor: 0.6, bishiNo: 100, harrisLength: 6,
             ganDamaSize: 0.6, shakuriStrokeCm: 70, shakuriCountPerTrigger: 3,
             makiAmount: 1.7 } },

  // ── エリア系 ──
  // 東京湾・剣崎・久里浜: ビシ80, PE3, ハリス4号10m, ポロポロ放出
  { key: "tokyo_bay", label: "東京湾・剣崎", group: "area",
    patch: { depth: 60, tanaDepth: 35,
             bishiNo: 80, peNo: 3,
             cushionLength: 1.0, harrisLength: 10, harrisNo: 4,
             hookType: "madai", hookSize: 10, ganDamaSize: 0.2, ganDamaPos: "mid",
             cageUpperOpening: 0.25, cageLowerOpening: 0,
             komaseSize: "L", smokeLevel: "weak",
             shakuriStrokeCm: 80, shakuriCountPerTrigger: 2,
             makiAmount: 2.5, shakuriInterval: 60 } },
  { key: "sagami_std", label: "相模湾標準", group: "area",
    patch: { depth: 65, tanaDepth: 45,
             bishiNo: 60, peNo: 2,
             cushionLength: 1.0, harrisLength: 8, harrisNo: 3,
             hookType: "madai", hookSize: 10, ganDamaSize: 0.2, ganDamaPos: "mid",
             cageUpperOpening: 0.25, cageLowerOpening: 0,
             komaseSize: "L", smokeLevel: "weak",
             shakuriStrokeCm: 75, shakuriCountPerTrigger: 2,
             makiAmount: 2.0, shakuriInterval: 45 } },
  { key: "sagami_lt", label: "相模湾LT", group: "area",
    patch: { depth: 50, tanaDepth: 30,
             bishiNo: 40, peNo: 1.5,
             cushionLength: 1.0, harrisLength: 6, harrisNo: 2,
             hookType: "madai", hookSize: 9, ganDamaSize: 0.1, ganDamaPos: "mid",
             cageUpperOpening: 0.20, cageLowerOpening: 0,
             komaseSize: "L", smokeLevel: "weak",
             shakuriStrokeCm: 70, shakuriCountPerTrigger: 2,
             makiAmount: 1.7, shakuriInterval: 30 } },
  { key: "sagami_deep", label: "相模湾深場(冬)", group: "area",
    patch: { depth: 90, tanaDepth: 70,
             bishiNo: 100, peNo: 3,
             cushionLength: 1.5, harrisLength: 10, harrisNo: 4,
             hookType: "madai", hookSize: 11, ganDamaSize: 0.5, ganDamaPos: "mid",
             cageUpperOpening: 0.25, cageLowerOpening: 0,
             komaseSize: "L", smokeLevel: "weak",
             shakuriStrokeCm: 80, shakuriCountPerTrigger: 2,
             makiAmount: 2.0, shakuriInterval: 90 } },
  { key: "kamoshi",  label: "外房カモシ", group: "area",
    patch: { depth: 55, tanaDepth: 25,
             bishiNo: 100, peNo: 4,
             cushionLength: 1.5, harrisLength: 10, harrisNo: 4,
             hookType: "madai", hookSize: 11, ganDamaSize: 0.3, ganDamaPos: "mid",
             cageUpperOpening: 0.15, cageLowerOpening: 0,
             komaseSize: "M", smokeLevel: "strong",
             shakuriStrokeCm: 100, shakuriCountPerTrigger: 2,
             makiAmount: 2.5, shakuriInterval: 60 } },
];

const MAX_PARTICLES = 1500;

function App() {
  const [params, setParams] = useState(DEFAULT_PARAMS);
  // 各グループ独立: cycle/cond/area から 1 つずつ or null。複数同時アクティブ可
  const [selectedPresets, setSelectedPresets] = useState({ cycle: "default", cond: null, area: null });
  const [running, setRunning] = useState(true);
  const [tick, setTick] = useState(0);
  const [optimizing, setOptimizing] = useState(false);
  const [recommendation, setRecommendation] = useState(null);
  const [locks, setLocks] = useState({});

  const canvasRef = useRef(null);
  const particlesRef = useRef([]);
  const rigStateRef = useRef({
    shakuriOffsetY: 0, shakuriVelY: 0, shakuriOffsetX: SimPhysics.ROD_X_M,
    makiOffset: 0, makiTarget: 0,
  });
  const chumRef = useRef(1.0);
  const heatmapRef = useRef(null);
  const lastTimeRef = useRef(0);
  const accumRef = useRef(0);
  const shakuriTimerRef = useRef(0);
  const flashRef = useRef(0);
  const pendingMakiRef = useRef([]);
  const pendingShakuriRef = useRef([]);
  const lastShakuriAtRef = useRef(0);
  // 自動最適動作の状態マシン: "shakuri" | "biting" | "dropping" | "idle"
  //   shakuri: N発撃ち中 → 撃ち終わって maki が落ち着いたら biting
  //   biting: 高位置 (tana - makiAmount) で食わせ待ち (shakuriInterval 秒)
  //   dropping: タナへ戻る (makiTarget=0) → 着いたら shakuri 再開
  const autoStateRef = useRef({ state: "idle", biteTimer: 0 });
  const phaseRef = useRef("fishing");
  const bishiAbsYRef = useRef(0);
  const dropVelRef = useRef(0);
  const swellPhaseRef = useRef(0);
  const swellOffsetYRef = useRef(0);
  const minimapPosRef = useRef(null);
  const minimapDragRef = useRef(null);
  const [bowViewSide, setBowViewSide] = useState("port");
  const bowViewSideRef = useRef("port");
  bowViewSideRef.current = bowViewSide;
  const [phase, setPhase] = useState("fishing");
  const [toast, setToast] = useState(null);
  const toastTimerRef = useRef(null);
  const showToast = (text, color) => {
    if (toastTimerRef.current) clearTimeout(toastTimerRef.current);
    setToast({ text, color: color || "var(--brass)" });
    toastTimerRef.current = setTimeout(() => setToast(null), 2200);
  };
  const tanaArrivalLastRef = useRef(false);

  const toggleLock = (name) => {
    setLocks(prev => ({ ...prev, [name]: !prev[name] }));
  };

  const metricsRef = useRef({
    hitCount: 0,
    sampleCount: 0,
    hitRateEMA: 0,
    shakuriCount: 0,
    totalSpawned: 0,
    hookDepth: 0,
    harrisAngleDeg: 0,
    histogram: new Array(24).fill(0),
    hookBin: 0,
  });

  // 物理に渡す前に hookWeight・dropSpeed を算出して合成
  const physicsParams = useMemo(() => ({
    ...params,
    hookWeight: SimPhysics.getHookWeight(params.hookType, params.hookSize),
    dropSpeed: SimPhysics.computeDropSpeed(params.bishiNo),
  }), [params]);
  const physicsParamsRef = useRef(physicsParams);
  physicsParamsRef.current = physicsParams;

  // パッチ合成: DEFAULT → area → cond → cycle の順で上書き
  // (area = 環境ベース / cond = 海況上書き / cycle = 動作上書き)
  function rebuildFromPresets(sel) {
    let p = { ...DEFAULT_PARAMS };
    for (const g of ["area", "cond", "cycle"]) {
      const key = sel[g];
      if (key) {
        const preset = PRESETS.find(x => x.key === key);
        if (preset) p = { ...p, ...preset.patch };
      }
    }
    return p;
  }

  const set = (patch) => {
    setParams(prev => ({ ...prev, ...patch }));
    // 手動編集: 全プリセット解除 (params が乖離するので)
    setSelectedPresets({ cycle: null, cond: null, area: null });
  };

  // プリセット トグル: 同グループ内で 1 つ選択 (再クリックで解除)
  const togglePreset = (key) => {
    const p = PRESETS.find(x => x.key === key);
    if (!p) return;
    const g = p.group;
    const newSel = { ...selectedPresets, [g]: selectedPresets[g] === key ? null : key };
    setSelectedPresets(newSel);
    setParams(rebuildFromPresets(newSel));
    resetSim();
    const active = ["area","cond","cycle"].map(gg => {
      const k = newSel[gg];
      const pp = k ? PRESETS.find(x => x.key === k) : null;
      return pp ? pp.label : null;
    }).filter(Boolean);
    showToast(active.length ? "プリセット: " + active.join(" + ") : "プリセット解除", "var(--vermilion)");
  };
  // 互換: applyPreset 名で呼ばれる箇所用
  const applyPreset = togglePreset;

  function resetSim() {
    particlesRef.current = [];
    heatmapRef.current = null;
    // ★ 落とし込み目安 = ビシ位置 (指示棚 + dropOffsetM)
    //   実釣標準: dropOffsetM = +5 → ビシは指示棚 5m 下 (タナ下5m)
    //   その後 shakuri × N + maki でビシを徐々に上げ、付け餌をタナへ寄せる
    //   makiOffset = -dropOffsetM (負値で cage が指示棚より下に位置)
    const pp = physicsParamsRef.current || DEFAULT_PARAMS;
    const _drop = pp.dropOffsetM != null ? pp.dropOffsetM : 5;
    const _initMaki = -_drop;
    // ★ リセット直後は潮で流れ切った状態からスタート (shakuriOffsetX を settle 済みの位置で初期化)
    //   理由: 旧実装は ROD_X_M から徐々に潮下へ流れていく途中でしゃくり開始 → 釣り座基準の X 想定とずれる
    const _tanaY = pp.tanaDepth + _drop;
    const _settledX = SimPhysics.ROD_X_M + SimPhysics.pelineDrift(pp, Math.max(0, _tanaY));
    rigStateRef.current = { shakuriOffsetY: 0, shakuriVelY: 0, shakuriOffsetX: _settledX, makiOffset: _initMaki, makiTarget: _initMaki };
    chumRef.current = 1.0;
    pendingMakiRef.current = [];
    pendingShakuriRef.current = [];
    autoStateRef.current = { state: "idle", biteTimer: 0 };
    phaseRef.current = "fishing";
    bishiAbsYRef.current = 0;
    dropVelRef.current = 0;
    setPhase("fishing");
    metricsRef.current.shakuriCount = 0;
    metricsRef.current.totalSpawned = 0;
    metricsRef.current.hitRateEMA = 0;
  }

  function getCageY() {
    const rs = rigStateRef.current;
    const pp = physicsParamsRef.current;
    if (phaseRef.current === "dropping") return bishiAbsYRef.current;
    return pp.tanaDepth - rs.makiOffset + rs.shakuriOffsetY;
  }

  // canvas resize
  useEffect(() => {
    const canvas = canvasRef.current;
    const resize = () => {
      const rect = canvas.parentElement.getBoundingClientRect();
      const dpr = Math.min(2, window.devicePixelRatio || 1);
      canvas.width  = Math.floor(rect.width  * dpr);
      canvas.height = Math.floor(rect.height * dpr);
      canvas.style.width = rect.width + "px";
      canvas.style.height = rect.height + "px";
      const ctx = canvas.getContext("2d");
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      canvas.__cssW = rect.width;
      canvas.__cssH = rect.height;
      // resize 時に minimap が画面外なら右下に再配置
      const mw = SimRenderer.BOW_VIEW_W || 178;
      const mh = SimRenderer.BOW_VIEW_H || 150;
      const mm = minimapPosRef.current;
      if (mm) {
        mm.x = Math.max(0, Math.min(rect.width - mw, mm.x));
        mm.y = Math.max(0, Math.min(rect.height - mh, mm.y));
      }
    };
    resize();
    window.addEventListener("resize", resize);
    return () => window.removeEventListener("resize", resize);
  }, []);

  // ミニビュー (船上から見た図) のドラッグ機能
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const MW = SimRenderer.BOW_VIEW_W || 178;
    const MH = SimRenderer.BOW_VIEW_H || 150;

    const getPos = (e) => {
      const rect = canvas.getBoundingClientRect();
      const t = e.touches ? e.touches[0] : e;
      return { x: t.clientX - rect.left, y: t.clientY - rect.top };
    };
    const inMinimap = (p) => {
      const mm = minimapPosRef.current;
      if (!mm) return false;
      return p.x >= mm.x && p.x <= mm.x + MW && p.y >= mm.y && p.y <= mm.y + MH;
    };

    const inToggle = (p) => {
      const mm = minimapPosRef.current;
      if (!mm) return false;
      const tgX = mm.x + MW - (SimRenderer.BOW_VIEW_TOGGLE_X || 8) - (SimRenderer.BOW_VIEW_TOGGLE_W || 56);
      const tgY = mm.y + (SimRenderer.BOW_VIEW_TOGGLE_Y || 32);
      const tgW = SimRenderer.BOW_VIEW_TOGGLE_W || 56;
      const tgH = SimRenderer.BOW_VIEW_TOGGLE_H || 16;
      return p.x >= tgX && p.x <= tgX + tgW && p.y >= tgY && p.y <= tgY + tgH;
    };

    const onDown = (e) => {
      const p = getPos(e);
      if (inToggle(p)) {
        // 左舷↔右舷 切替
        setBowViewSide(bowViewSideRef.current === "port" ? "starboard" : "port");
        e.preventDefault();
        return;
      }
      if (inMinimap(p)) {
        const mm = minimapPosRef.current;
        minimapDragRef.current = { dx: p.x - mm.x, dy: p.y - mm.y };
        canvas.style.cursor = "grabbing";
        e.preventDefault();
      }
    };
    const onMove = (e) => {
      const p = getPos(e);
      if (minimapDragRef.current) {
        const W = canvas.__cssW || canvas.width;
        const H = canvas.__cssH || canvas.height;
        const nx = Math.max(0, Math.min(W - MW, p.x - minimapDragRef.current.dx));
        const ny = Math.max(0, Math.min(H - MH, p.y - minimapDragRef.current.dy));
        minimapPosRef.current = { x: nx, y: ny };
        e.preventDefault();
      } else {
        canvas.style.cursor = inMinimap(p) ? "grab" : "default";
      }
    };
    const onUp = () => {
      if (minimapDragRef.current) {
        minimapDragRef.current = null;
        canvas.style.cursor = "default";
      }
    };

    canvas.addEventListener("mousedown", onDown);
    canvas.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    canvas.addEventListener("touchstart", onDown, { passive: false });
    canvas.addEventListener("touchmove", onMove, { passive: false });
    window.addEventListener("touchend", onUp);
    return () => {
      canvas.removeEventListener("mousedown", onDown);
      canvas.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
      canvas.removeEventListener("touchstart", onDown);
      canvas.removeEventListener("touchmove", onMove);
      window.removeEventListener("touchend", onUp);
    };
  }, []);

  // ===== 単発しゃくり実行（withMaki=true で 0.5s 後に巻き上げをスケジュール） =====
  const _executeOneStroke = (withMaki) => {
    if (phaseRef.current !== "fishing") return;
    const rs = rigStateRef.current;
    const pp = physicsParamsRef.current;
    SimPhysics.shakuri(rs, pp);
    const cage = { x: rs.shakuriOffsetX, y: getCageY() };
    const before = particlesRef.current.length;
    const strokeIntensity = pp.shakuriStrokeCm / 50;
    SimPhysics.spawnParticles(particlesRef.current, cage, pp, strokeIntensity, MAX_PARTICLES, chumRef.current);
    metricsRef.current.totalSpawned += particlesRef.current.length - before;
    metricsRef.current.shakuriCount += 1;
    chumRef.current = Math.max(0, chumRef.current - SimPhysics.shakuriConsumption(pp));
    flashRef.current = 1.0;
    lastShakuriAtRef.current = performance.now();
    if (withMaki && pp.makiAmount > 0.01) {
      pendingMakiRef.current.push({ at: performance.now() + 500, amount: pp.makiAmount });
    }
  };

  // ===== N連発しゃくりサイクル =====
  // 2発目以降は前のしゃくりがバネ-ダンパで完全に収まってから発火する
  // (固定 500ms 間隔だと前ストロークが peak 折返し中に重なって動作が不自然)
  const _doShakuriCycle = (withMaki) => {
    if (phaseRef.current !== "fishing") return;
    const pp = physicsParamsRef.current;
    const n = Math.max(1, Math.round(pp.shakuriCountPerTrigger || 1));
    _executeOneStroke(withMaki);
    for (let i = 1; i < n; i++) {
      pendingShakuriRef.current.push({ withMaki: withMaki });
    }
  };

  // ===== 自動最適動作用: N発撃ちそれぞれが maki を伴う (per-stroke maki) =====
  // 実釣準拠: 1サイクルで N×makiAmount だけビシが上昇 → 食わせ待ち → drop で元に戻る
  // (rigLen=6, init=1, N=2, makiAmount=2.5 → peakMaki=6 → 付け餌が指示棚に到達)
  const _doOptimalShakuriBurst = () => {
    if (phaseRef.current !== "fishing") return;
    const pp = physicsParamsRef.current;
    const n = Math.max(1, Math.round(pp.shakuriCountPerTrigger || 1));
    _executeOneStroke(true);  // 1発目 + maki
    for (let i = 1; i < n; i++) {
      pendingShakuriRef.current.push({ withMaki: true });  // 後続も maki
    }
  };

  // 手動しゃくる（巻きなし）
  const triggerShakuri = () => _doShakuriCycle(false);
  const triggerRef = useRef(triggerShakuri);
  triggerRef.current = triggerShakuri;

  // 手動巻く（makiAmount だけ巻き上げ）。コマセ枯渇でも自動回収しない（仕掛け回収は手動のみ）。
  const triggerMaki = () => {
    if (phaseRef.current !== "fishing") return;
    const pp = physicsParamsRef.current;
    const physicalMaxMaki = Math.max(2, pp.tanaDepth - 1);
    const nextTarget = rigStateRef.current.makiTarget + (pp.makiAmount || 0);
    rigStateRef.current.makiTarget = Math.min(physicalMaxMaki, nextTarget);
    flashRef.current = 0.5;
  };
  const makiRef = useRef(triggerMaki);
  makiRef.current = triggerMaki;

  // 手動落とし込み（dropAmount だけビシを下げる）
  const triggerDropOnly = () => {
    if (phaseRef.current !== "fishing") return;
    const pp = physicsParamsRef.current;
    // ビシが海底に当たらない最小 makiOffset (bishi y <= depth - 2)
    const minMaki = pp.tanaDepth - pp.depth + 2;
    const nextTarget = rigStateRef.current.makiTarget - (pp.dropAmount || 0);
    rigStateRef.current.makiTarget = Math.max(minMaki, nextTarget);
    flashRef.current = 0.5;
  };
  const dropManualRef = useRef(triggerDropOnly);
  dropManualRef.current = triggerDropOnly;

  // ===== 落とし込みスキップ（ビシが指示棚 + dropOffsetM へ即着） =====
  const skipDrop = () => {
    if (phaseRef.current !== "dropping") return;
    const pp = physicsParamsRef.current;
    const drop = pp.dropOffsetM != null ? pp.dropOffsetM : 5;
    bishiAbsYRef.current = Math.max(1, pp.tanaDepth + drop);
    phaseRef.current = "fishing";
    dropVelRef.current = 0;
    rigStateRef.current.makiOffset = -drop;
    rigStateRef.current.makiTarget = -drop;
    setPhase("fishing");
  };
  const skipRef = useRef(skipDrop);
  skipRef.current = skipDrop;

  // ===== 仕掛け投入 (落とし込みフェーズ) =====
  const castRig = () => {
    phaseRef.current = "dropping";
    setPhase("dropping");
    bishiAbsYRef.current = 0;
    dropVelRef.current = physicsParamsRef.current.dropSpeed || 0.1;
    rigStateRef.current.makiOffset = 0;
    rigStateRef.current.makiTarget = 0;
    rigStateRef.current.shakuriOffsetY = 0;
    rigStateRef.current.shakuriVelY = 0;
    particlesRef.current = [];
    pendingMakiRef.current = [];
    pendingShakuriRef.current = [];
    autoStateRef.current = { state: "idle", biteTimer: 0 };
    chumRef.current = 1.0;
  };
  const castRef = useRef(castRig);
  castRef.current = castRig;

  // ===== 仕掛け回収(コマセ補充 + 巻きリセット + 自動再投入) =====
  // 自動回収 (triggerMaki の上限到達時) と同じ挙動。回収して dropping フェーズへ。
  const retrieveRig = () => {
    rigStateRef.current.makiTarget = 0;
    rigStateRef.current.makiOffset = 0;
    rigStateRef.current.shakuriOffsetY = 0;
    rigStateRef.current.shakuriVelY = 0;
    pendingMakiRef.current = [];
    pendingShakuriRef.current = [];
    autoStateRef.current = { state: "idle", biteTimer: 0 };
    chumRef.current = 1.0;
    particlesRef.current = [];
    phaseRef.current = "dropping";
    setPhase("dropping");
    bishiAbsYRef.current = 0;
    dropVelRef.current = physicsParamsRef.current.dropSpeed || 1.5;
    flashRef.current = 1.4;
  };
  const retrieveRef = useRef(retrieveRig);
  retrieveRef.current = retrieveRig;

  const paramsRef = useRef(params);
  paramsRef.current = params;
  const runningRef = useRef(running);
  runningRef.current = running;

  // ===== Animation loop =====
  useEffect(() => {
    let rafId;
    let intervalId;
    const loop = (t) => {
      if (!lastTimeRef.current) lastTimeRef.current = t;
      let dt = (t - lastTimeRef.current) / 1000;
      lastTimeRef.current = t;
      if (dt > 0.1) dt = 0.1;
      const params = paramsRef.current;
      const pp = physicsParamsRef.current;
      const running = runningRef.current;
      if (!running) dt = 0;

      // === 落とし込みフェーズ ===
      // 関東コマセマダイ実釣: 「指示ダナ下 5m」は **付けエサ(hook)** が下 5m に来る位置
      // → ビシ(cage) は付けエサより (cushion+harris) m 上、つまり tana - (cushion+harris) + 5
      // その後 3回しゃくり×1.7m巻きで付けエサが指示ダナに到達 → 待ち時間 → 回収
      if (running && phaseRef.current === "dropping") {
        // ★ ビシ落としこみ目安: 指示棚 + dropOffsetM
        const drop = pp.dropOffsetM != null ? pp.dropOffsetM : 5;
        const dropTarget = Math.max(1, pp.tanaDepth + drop);
        if (bishiAbsYRef.current < dropTarget) {
          // 沈降中
          const vel = pp.dropSpeed || 1.5;
          dropVelRef.current = vel;
          bishiAbsYRef.current += vel * dt;
          if (bishiAbsYRef.current >= dropTarget) {
            bishiAbsYRef.current = dropTarget;
            // ビシは tana + drop に固定 → makiOffset = -drop
            rigStateRef.current.makiOffset = -drop;
            rigStateRef.current.makiTarget = -drop;
            // dropVel はここでゼロにしない (settling で指数減衰させて潮なじみを再現)
          }
        } else {
          // 着定後の潮なじみ: dropVel が指数減衰してハリス傾き (lagRatio) が
          // 沈降中の真下→静止時の潮下流drift へ滑らかに遷移する。
          // 時定数 0.7s (k=1.4) → 約 1.5〜2 秒でほぼ静定。
          const k = 1.4;
          dropVelRef.current = (dropVelRef.current || 0) * Math.exp(-k * dt);
          if (dropVelRef.current < 0.05) {
            dropVelRef.current = 0;
            phaseRef.current = "fishing";
            setPhase("fishing");
          }
        }
      } else {
        dropVelRef.current = 0;
      }

      // === うねり ===
      if (running) {
        swellPhaseRef.current += dt;
        const period = Math.max(1, pp.swellPeriod || 6);
        const amp = (pp.swellHeight || 0) * 0.5; // peak-to-trough/2
        swellOffsetYRef.current = amp * Math.sin(swellPhaseRef.current * 2 * Math.PI / period);
      }

      // 自動最適動作 (fishing 中のみ): 状態マシンで shakuri→biting→dropping→shakuri を回す
      //   shakuri:  N発撃ち中 (最終発のみ maki) → 終わって maki が完了したら biting
      //   biting:   高位置で食わせ待ち (shakuriInterval 秒)
      //   dropping: makiTarget=0 でタナへ戻す → 着いたら次の shakuri 開始
      if (running && params.autoShakuri && phaseRef.current === "fishing") {
        const auto = autoStateRef.current;
        const rs = rigStateRef.current;

        if (auto.state === "idle") {
          // 初回: shakuri 開始
          _doOptimalShakuriBurst();
          auto.state = "shakuri";
          auto.biteTimer = 0;
        } else if (auto.state === "shakuri") {
          // 全 N 発と maki が完了したら biting へ
          const allStrokesDone = pendingShakuriRef.current.length === 0;
          const allMakiDone = pendingMakiRef.current.length === 0;
          const rigSettled = Math.abs(rs.shakuriVelY) < 0.12 && Math.abs(rs.shakuriOffsetY) < 0.05;
          const makiSettled = Math.abs((rs.makiTarget || 0) - (rs.makiOffset || 0)) < 0.08;
          if (allStrokesDone && allMakiDone && rigSettled && makiSettled) {
            auto.state = "biting";
            auto.biteTimer = 0;
          }
        } else if (auto.state === "biting") {
          auto.biteTimer += dt;
          if (auto.biteTimer >= (pp.shakuriInterval || 60)) {
            // 食わせ時間終了 → ビシを落としこみ目安位置 (tana + dropOffsetM) に戻す
            // 「巻きすぎ累積で cage が tana より上に固定」のドリフトを防ぐため、
            // dropBack ではなく ALWAYS baseMaki にスナップ。
            const drop = pp.dropOffsetM != null ? pp.dropOffsetM : 5;
            rs.makiTarget = -drop;
            auto.state = "dropping";
          }
        } else if (auto.state === "dropping") {
          // ビシが目標位置に戻ったら次サイクル開始
          const makiSettled = Math.abs((rs.makiTarget || 0) - (rs.makiOffset || 0)) < 0.08;
          if (makiSettled) {
            _doOptimalShakuriBurst();
            auto.state = "shakuri";
            auto.biteTimer = 0;
          }
        }
      } else {
        // 自動 OFF または fishing 外 → idle にリセット
        autoStateRef.current.state = "idle";
        autoStateRef.current.biteTimer = 0;
      }

      // Pending shakuri (N連発の2発目以降)
      // 前のしゃくりが完全に収まる(バネ-ダンパが落ち着く)まで待ってから次を発火。
      //   settled = |shakuriOffsetY| < 5cm かつ |shakuriVelY| < 0.12 m/s
      //   さらに前ストロークから最低 600ms 経過 (視覚的な間を確保)
      //   最大 3 秒で強制発火 (安全弁: 何らかの理由で収束しなくても進行)
      const now = performance.now();
      if (pendingShakuriRef.current.length > 0 && phaseRef.current === "fishing") {
        const rs = rigStateRef.current;
        const settled = Math.abs(rs.shakuriOffsetY) < 0.05 && Math.abs(rs.shakuriVelY) < 0.12;
        const elapsed = now - lastShakuriAtRef.current;
        if ((settled && elapsed >= 600) || elapsed >= 3000) {
          const next = pendingShakuriRef.current.shift();
          _executeOneStroke(!!next.withMaki);
        }
      }

      // Pending maki (0.5s 後に巻く)
      // 自動回収: コマセ枯渇時のみ。巻き上げが過剰になっても勝手にリセットしない
      //（ユーザーが「仕掛け回収」を手動で押すまで保持）。
      // makiTarget の上限はビシが水面 1m 以下に出ない範囲だけ守る。
      const _rigLen2 = (pp.cushionLength || 1) + (pp.harrisLength || 8);
      const physicalMaxMaki = Math.max(2, pp.tanaDepth - 1); // bishi y >= 1m (水面より下)
      for (let i = pendingMakiRef.current.length - 1; i >= 0; i--) {
        if (now >= pendingMakiRef.current[i].at) {
          const nextTarget = rigStateRef.current.makiTarget + pendingMakiRef.current[i].amount;
          // 巻きすぎは物理的上限でクランプするだけ（リセットしない）
          // コマセ空でも自動リセットしない: 回収はユーザーが「仕掛け回収」で明示
          rigStateRef.current.makiTarget = Math.min(physicalMaxMaki, nextTarget);
          pendingMakiRef.current.splice(i, 1);
        }
      }
      // 巻き過ぎ / 残量0 で自動回収サジェスト (実回収はユーザー操作)
      // ただし、makiTarget が水面に達する前にあえて止めない

      // コマセの連続漏れ
      if (running) {
        chumRef.current = Math.max(0, chumRef.current - SimPhysics.leakRate(pp) * dt);
      }

      // ビシ動力学
      SimPhysics.rigStep(rigStateRef.current, pp, dt);

      // 連続放出 (残量に比例・fishing 中のみ・下窓主導)
      const lowerOpen = pp.cageLowerOpening != null ? pp.cageLowerOpening : (pp.cageOpening != null ? pp.cageOpening : 0);
      if (running && phaseRef.current === "fishing" && lowerOpen > 0.05 && chumRef.current > 0.01) {
        accumRef.current += dt;
        const rate = (0.4 + lowerOpen * 4) * chumRef.current;
        const need = accumRef.current * rate;
        if (need >= 1) {
          const n = Math.floor(need);
          accumRef.current -= n / rate;
          const rs = rigStateRef.current;
          const cage = { x: rs.shakuriOffsetX, y: getCageY() };
          for (let i = 0; i < n; i++) {
            if (particlesRef.current.length >= MAX_PARTICLES) break;
            particlesRef.current.push({
              x: cage.x + (Math.random()-0.5)*0.2,
              y: cage.y + (Math.random()-0.5)*0.2 + 0.1,
              vx: 0, vy: 0,
              life: 0.85,
              size: 0.5 + Math.random()*0.6,
              terminal: 0.06 + Math.random()*0.06,
            });
            metricsRef.current.totalSpawned += 1;
          }
        }
      }

      // 粒子更新
      SimPhysics.stepParticles(particlesRef.current, pp, dt);

      // 仕掛け形状 (落とし込み中は dropVel を渡してハリスを上方に流す)
      const cageYForRig = phaseRef.current === "dropping"
        ? bishiAbsYRef.current
        : pp.tanaDepth - rigStateRef.current.makiOffset;
      const rig = SimPhysics.rigShape(
        cageYForRig,
        rigStateRef.current.shakuriOffsetY,
        rigStateRef.current.shakuriOffsetX,
        pp,
        pp.hookWeight,
        dropVelRef.current
      );

      // メトリクス (圏内 1.8m = 魚が匂いで感知する範囲)
      const near = SimPhysics.nearHook(particlesRef.current, rig.hook, 1.8);
      const total = particlesRef.current.length;
      const ratio = total > 0 ? near / total * 100 : 0;
      const a = 0.04;
      metricsRef.current.hitRateEMA = metricsRef.current.hitRateEMA * (1 - a) + ratio * a;
      metricsRef.current.hookDepth = rig.hook.y;
      metricsRef.current.harrisAngleDeg = rig.theta * 180 / Math.PI;
      // 仕掛け鉛直距離 (ビシ → 付けエサの実 y 差) / 仕掛け全長 (cushion + harris)
      const rigLenTotal = (pp.cushionLength || 1) + (pp.harrisLength || 8);
      const vertLen = rig.hook.y - rig.cage.y;
      metricsRef.current.rigVertical = vertLen;
      metricsRef.current.rigTotal = rigLenTotal;
      metricsRef.current.rigVerticalRatio = rigLenTotal > 0 ? vertLen / rigLenTotal : 1;
      // PE道糸 (釣り人(竿先 world x=ROD_X_M, y≈0) → ビシ) の鉛直距離 / 斜距離
      const rodX = SimPhysics.ROD_X_M;
      const peVert = rig.cage.y; // 竿先 y ≈ 0
      const peHoriz = rig.cage.x - rodX;
      const peTotal = Math.sqrt(peVert * peVert + peHoriz * peHoriz);
      metricsRef.current.peVertical = peVert;
      metricsRef.current.peHorizontal = peHoriz;
      metricsRef.current.peTotal = peTotal;

      // タナ到達検出（付けエサ y がタナ ±0.5m に入った瞬間のみ）
      if (running && phaseRef.current === "fishing") {
        const onTana = Math.abs(rig.hook.y - pp.tanaDepth) < 0.5;
        if (onTana && !tanaArrivalLastRef.current) {
          tanaArrivalLastRef.current = true;
          flashRef.current = 1.6; // 大きめのフラッシュ
          showToast("✓ タナ取り完了 — 待ち時間", "var(--moss)");
        }
        if (!onTana && Math.abs(rig.hook.y - pp.tanaDepth) > 1.0) {
          tanaArrivalLastRef.current = false;
        }
      }
      const histo = SimPhysics.depthHistogram(particlesRef.current, pp.depth, 24, rig.hook.y);
      metricsRef.current.histogram = histo.bins;
      metricsRef.current.hookBin = histo.hookBin;

      // タナ下流出率 + コマセ雲の中心深度
      let belowTana = 0;
      let sumY = 0, countY = 0;
      for (let i = 0; i < particlesRef.current.length; i++) {
        const p = particlesRef.current[i];
        if (p.y > pp.tanaDepth + 1) belowTana++;
        if (p.life > 0.3) { sumY += p.y; countY += 1; }
      }
      const belowRatio = total > 0 ? (belowTana / total * 100) : 0;
      metricsRef.current.belowTanaRatio = metricsRef.current.belowTanaRatio == null
        ? belowRatio
        : metricsRef.current.belowTanaRatio * (1 - a) + belowRatio * a;
      metricsRef.current.komaseDepth = countY > 0 ? sumY / countY : null;

      // ビシ深度 (fishing 中) — 指示棚より深ければ警告対象
      // shakuriOffsetY の瞬間的なオシレーションは無視したいので、makiOffset ベースで判定
      const cageDepthBase = pp.tanaDepth - (rigStateRef.current.makiOffset || 0);
      const cageOverrun = cageDepthBase - pp.tanaDepth;  // 正の値 = ビシが指示棚より深い
      metricsRef.current.cageOverrun = metricsRef.current.cageOverrun == null
        ? cageOverrun
        : metricsRef.current.cageOverrun * (1 - a) + cageOverrun * a;

      // 描画
      const canvas = canvasRef.current;
      if (canvas && canvas.__cssW) {
        const ctx = canvas.getContext("2d");
        const W = canvas.__cssW;
        const H = canvas.__cssH;
        const map = SimRenderer.makeMap({width: W, height: H}, pp);
        if (!heatmapRef.current) heatmapRef.current = SimRenderer.makeHeatmap(60, 40);
        SimRenderer.heatmapStep(heatmapRef.current, map, particlesRef.current, dt);

        ctx.clearRect(0, 0, W, H);
        const swellPx = swellOffsetYRef.current * map.sy;
        SimRenderer.drawBackground(ctx, map, pp, swellPhaseRef.current);
        SimRenderer.drawHeatmap(ctx, heatmapRef.current, map);
        SimRenderer.drawCurrent(ctx, map, pp);

        const rodTipY = map.y(0) - 36 - swellPx;
        SimRenderer.drawBoat(ctx, map, rodTipY, swellPx);
        SimRenderer.drawFishShadows(ctx, map, pp);
        SimRenderer.drawRig(ctx, map, rig, pp, rodTipY, chumRef.current, swellPx);
        SimRenderer.drawParticles(ctx, map, particlesRef.current);
        const ppLabels = Object.assign({}, pp, { _komaseDepth: metricsRef.current.komaseDepth });
        SimRenderer.drawLabels(ctx, map, ppLabels, rig, phaseRef.current, swellOffsetYRef.current);
        // ミニビュー位置 (未設定なら右下デフォルト)
        if (!minimapPosRef.current) {
          const mw = SimRenderer.BOW_VIEW_W || 178;
          const mh = SimRenderer.BOW_VIEW_H || 150;
          minimapPosRef.current = { x: W - mw - 18, y: H - mh - 18 };
        }
        SimRenderer.drawBowView(ctx, minimapPosRef.current.x, minimapPosRef.current.y, pp, rig, bowViewSideRef.current);

        if (flashRef.current > 0) {
          flashRef.current -= dt * 3.5;
          const fa = Math.max(0, flashRef.current);
          ctx.fillStyle = `rgba(255, 255, 255, ${fa * 0.08})`;
          ctx.fillRect(0, 0, W, H);
        }
      }

      // panels tick
      if ((Math.floor(t / 100)) !== (Math.floor((t - dt*1000) / 100))) {
        setTick(k => (k + 1) % 1000000);
      }

      rafId = requestAnimationFrame(loop);
    };
    rafId = requestAnimationFrame(loop);
    intervalId = setInterval(() => {
      if (document.visibilityState === "visible") return;
      loop(performance.now());
    }, 250);
    return () => { cancelAnimationFrame(rafId); clearInterval(intervalId); };
  }, []);

  // 初期同期描画
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !canvas.__cssW) return;
    const ctx = canvas.getContext("2d");
    const map = SimRenderer.makeMap({width: canvas.__cssW, height: canvas.__cssH}, physicsParams);
    if (!heatmapRef.current) heatmapRef.current = SimRenderer.makeHeatmap(60, 40);
    const rig = SimPhysics.rigShape(physicsParams.tanaDepth, 0, 0, physicsParams, physicsParams.hookWeight, 0);
    ctx.clearRect(0, 0, canvas.__cssW, canvas.__cssH);
    SimRenderer.drawBackground(ctx, map, physicsParams, 0);
    SimRenderer.drawCurrent(ctx, map, physicsParams);
    SimRenderer.drawBoat(ctx, map, map.y(0) - 36, 0);
    SimRenderer.drawFishShadows(ctx, map, physicsParams);
    SimRenderer.drawRig(ctx, map, rig, physicsParams, map.y(0) - 36, chumRef.current, 0);
    SimRenderer.drawLabels(ctx, map, physicsParams, rig, phaseRef.current, 0);
    if (!minimapPosRef.current) {
      const mw = SimRenderer.BOW_VIEW_W || 178;
      const mh = SimRenderer.BOW_VIEW_H || 150;
      minimapPosRef.current = { x: canvas.__cssW - mw - 18, y: canvas.__cssH - mh - 18 };
    }
    SimRenderer.drawBowView(ctx, minimapPosRef.current.x, minimapPosRef.current.y, physicsParams, rig, bowViewSideRef.current);
  }, [physicsParams, bowViewSide]);

  // ===== 自動最適化 =====
  const runOptimize = async () => {
    setOptimizing(true);
    setRecommendation(null);
    await new Promise(r => setTimeout(r, 50));
    const baseline = SimPhysics.scoreParams(physicsParams);
    const lockedValues = {};
    for (const k of LOCKABLE_PARAMS) {
      if (locks[k]) lockedValues[k] = physicsParams[k];
    }
    const result = SimPhysics.optimize(physicsParams, 64, lockedValues);
    setRecommendation({ ...result, baseline, locked: { ...lockedValues } });
    setOptimizing(false);
  };
  const applyRecommendation = () => {
    if (!recommendation) return;
    setParams(prev => ({ ...prev, ...recommendation.best }));
    setSelectedPresets({ cycle: null, cond: null, area: null });  // 手動 override 扱い
    resetSim();
  };

  // ===== Grade =====
  const grade = useMemo(() => {
    const rate = metricsRef.current.hitRateEMA;
    const tanaDiff = metricsRef.current.hookDepth - params.tanaDepth;
    const absDiff = Math.abs(tanaDiff);
    // 合否は「付けエサとコマセの一致」AND「付けエサが指示棚にいる」の両方が必要。
    //   タナ ズレ ≤ 1.5m: タナ取り OK
    //   タナ ズレ 1.5-3m: タナ取り NG (△)
    //   タナ ズレ > 3m: タナ取り 大幅 NG (×)
    let g, note;
    if (absDiff > 3) {
      g = "×";
      note = "付けエサがタナから大きく外れている。ガン玉/ハリス長で調整。";
    } else if (absDiff > 1.5) {
      g = "△";
      note = `付けエサが指示棚から ${absDiff.toFixed(1)}m ズレ。ガン玉/ハリス長を調整して付けエサをタナに合わせる。`;
    } else if (rate < 0.5) {
      g = "×";
      note = "付けエサはタナだがコマセ雲が届いていない。しゃくり振り幅/上窓を増やす。";
    } else if (rate < 2) {
      g = "△";
      note = "タナ OK だがコマセ薄い。しゃくり間隔/巻き量を見直し。";
    } else if (rate < 4) {
      g = "○";
      note = "タナ OK + コマセ雲と同調。微調整で更に上を狙える。";
    } else {
      g = "◎";
      note = "タナ OK + コマセ雲と完全同調。理想的な配置。";
    }

    // 「待ち推奨」判定: 付けエサ位置にコマセ雲が重なっており、かつタナズレが小さい
    // この状態では追加のしゃくりは不要、待って魚を食わせる時間
    let waitHint = null;
    if (absDiff <= 2 && rate >= 2.5 && phaseRef.current === "fishing") {
      waitHint = {
        active: true,
        label: rate >= 4 ? "✓ ベスト重なり中 — 待つ！" : "✓ 重なり良好 — 追いコマセ控えめに",
        color: rate >= 4 ? "var(--moss)" : "var(--brass)",
      };
    }

    // ビシ位置警告: ビシ自体が指示棚より深く沈んでいたら警告 (タナ取り失敗)
    //   指示棚下にビシが居ると、コマセは指示棚より深い位置から放出される → 魚のタナ外しまで散らす
    //   原因: 落とし込み過ぎ・巻き上げ不足・ガン玉重すぎでハリスが沈む
    const belowRatio = metricsRef.current.belowTanaRatio || 0;
    const cageOver = metricsRef.current.cageOverrun || 0;
    let belowWarning = null;
    if (cageOver >= 8.0) {
      belowWarning = { level: "high", text: `⚠ ビシが指示棚より ${cageOver.toFixed(1)}m 下 — タナ取り直しを!`, color: "var(--vermilion)" };
    } else if (cageOver >= 6.0) {
      belowWarning = { level: "mid", text: `⚠ ビシが指示棚より ${cageOver.toFixed(1)}m 下 — 巻き上げて`, color: "var(--brass)" };
    }

    return {
      grade: g, gradeNote: note,
      hitRate: rate,
      hookDepth: metricsRef.current.hookDepth,
      harrisAngleDeg: metricsRef.current.harrisAngleDeg,
      tanaDiff,
      histogram: metricsRef.current.histogram,
      hookBin: metricsRef.current.hookBin,
      shakuriCount: metricsRef.current.shakuriCount,
      totalSpawned: metricsRef.current.totalSpawned,
      waitHint,
      belowRatio,
      belowWarning,
      komaseDepth: metricsRef.current.komaseDepth,
      rigVertical: metricsRef.current.rigVertical,
      rigTotal: metricsRef.current.rigTotal,
      rigVerticalRatio: metricsRef.current.rigVerticalRatio,
      peVertical: metricsRef.current.peVertical,
      peHorizontal: metricsRef.current.peHorizontal,
      peTotal: metricsRef.current.peTotal,
    };
  }, [tick, params.tanaDepth, phase]);

  const chum = chumRef.current;
  const chumColor = chum > 0.3 ? "var(--paper)" : chum > 0.1 ? "var(--brass)" : "var(--vermilion)";

  return (
    <div className="app">
      <header className="head app__head">
        <div>
          <h1 className="head__title"><span className="kanji-accent">朱</span>コマセ巻きシミュレーター</h1>
          <div className="head__sub">TOKYO BAY ・ 紅鯛 コマセ釣り 物理モデル</div>
        </div>
        <div className="head__meta">
          <div>SIM <b>● LIVE</b>　{Math.round(particlesRef.current.length)}粒</div>
          <div>累計しゃくり {metricsRef.current.shakuriCount}回</div>
        </div>
      </header>

      <LeftPanel params={params} set={set} locks={locks} toggleLock={toggleLock} />

      <main className="stage app__main">
        <canvas ref={canvasRef} className="stage__canvas" />
        {toast && (
          <div className="toast" style={{
            position: "absolute",
            top: 14,
            left: "50%",
            transform: "translateX(-50%)",
            padding: "10px 22px",
            background: "rgba(13, 43, 74, 0.94)",
            border: "1px solid " + toast.color,
            borderRadius: "6px",
            color: toast.color,
            fontFamily: "var(--sans)",
            fontWeight: 700,
            fontSize: 14,
            letterSpacing: ".12em",
            pointerEvents: "none",
            boxShadow: "0 4px 20px rgba(13, 43, 74, 0.3)",
            zIndex: 10,
            animation: "toastFade 2.2s ease-in-out forwards",
          }}>{toast.text}</div>
        )}
        <div className="stage__hud">
          <div>指示ダナ {phase === "dropping" && <span style={{color:"var(--vermilion)", fontFamily:"var(--mono)", fontSize:10, marginLeft:6}}>● 落とし込み中</span>}</div>
          <span className="hud-big">{params.tanaDepth}<small style={{fontSize:14, opacity:.6, marginLeft:3}}>m</small></span>
          {phase === "dropping" && (() => {
            const motosLen = (params.motosEnabled === false ? 0 : (params.motosLength || 0));
            const rigLen = (params.cushionLength || 1) + motosLen + (params.harrisLength || 8);
            const drop = params.dropOffsetM != null ? params.dropOffsetM : 5;
            const bishiTarget = Math.max(1, params.tanaDepth + drop);
            const hookY = bishiAbsYRef.current + rigLen;
            return (
              <div style={{marginTop:6, fontFamily:"var(--mono)", fontSize:11, color:"var(--paper)"}}>
                ビシ {bishiAbsYRef.current.toFixed(1)}/{bishiTarget.toFixed(0)}m<br/>
                付けエサ {hookY.toFixed(1)}m → {(params.tanaDepth + 5).toFixed(0)}m (下5m)
              </div>
            );
          })()}
          <div style={{marginTop:14, fontSize:11, letterSpacing:".15em"}}>コマセ残量</div>
          <div style={{
            width: 120, height: 8, marginTop: 5,
            background: "rgba(255,255,255,0.18)",
            border: "1px solid rgba(255,255,255,0.35)",
            borderRadius: "4px",
            overflow: "hidden",
          }}>
            <div style={{
              height:"100%",
              width: Math.max(0, Math.min(100, chum * 100)) + "%",
              background: chumColor,
              transition: "background 0.2s",
            }}></div>
          </div>
          <div style={{
            fontFamily:"var(--mono)", fontSize:11, marginTop:3,
            color: chumColor
          }}>{Math.round(chum * 100)}%</div>
        </div>
        <div className="stage__legend">
          <div style={{fontFamily:"var(--sans)", fontWeight:700, fontSize:12, color:"var(--text)", marginBottom:6, letterSpacing:".12em"}}>凡例</div>
          <div className="legend-row"><span className="legend-dot" style={{background:"#fdba74"}}></span><b>コマセ粒子</b></div>
          <div className="legend-row"><span className="legend-dot" style={{background:"#e85d04"}}></span>付けエサ</div>
          <div className="legend-row"><span className="legend-dot" style={{background:"#1e293b", border:"1px solid #94a3b8"}}></span>ガン玉</div>
          <div className="legend-row"><span className="legend-dot" style={{background:"#475569"}}></span>ビシ</div>
        </div>
      </main>

      <div className="controls app__controls">
        {/* グループ1: 投入 / スキップ */}
        <div className="controls__group">
          <button
            className="btn-action btn-cast"
            onClick={() => castRef.current()}
            disabled={phase === "dropping"}
          >投入<small>落とし込み</small></button>
          {phase === "dropping" && (
            <button
              className="btn-action btn-skip"
              onClick={() => skipRef.current()}
            >↯ タナへ<small>即着</small></button>
          )}
        </div>

        {/* グループ2: 竿操作 (主要) */}
        <div className="controls__group">
          <button
            className="btn-action shakuri-btn"
            onClick={() => triggerRef.current()}
            disabled={phase !== "fishing"}
          >しゃくる</button>
          <button
            className="btn-action maki-btn"
            onClick={() => makiRef.current()}
            disabled={phase !== "fishing"}
          >巻く</button>
          <button
            className="btn-action drop-btn"
            onClick={() => dropManualRef.current()}
            disabled={phase !== "fishing"}
          >落とす</button>
        </div>

        {/* グループ3: 回収 */}
        <div className="controls__group">
          <button
            className="btn-action btn-rig"
            onClick={() => retrieveRef.current()}
          >仕掛け回収<small>コマセ補充</small></button>
        </div>

        {/* グループ4: シミュ制御 */}
        <div className="controls__group">
          <button
            className={"btn-action btn-sim " + (running ? "is-running" : "")}
            onClick={() => setRunning(r => !r)}
          >{running ? "一時停止" : "再開"}</button>
          <button className="btn-action btn-sim" onClick={resetSim}>リセット</button>
        </div>

        {/* グループ5: 状態表示 */}
        <div className="controls__group controls__group--stats">
          <div className="ctl-stat">
            <div className="ctl-stat__label">粒子</div>
            <div className="ctl-stat__value">{particlesRef.current.length}<small>/{MAX_PARTICLES}</small></div>
          </div>
          <div className="ctl-stat">
            <div className="ctl-stat__label">巻き上げ</div>
            <div className="ctl-stat__value">{rigStateRef.current.makiOffset.toFixed(2)}<small>m</small></div>
          </div>
        </div>
      </div>

      <RightPanel
        metrics={grade}
        params={params}
        presets={PRESETS}
        selectedPresets={selectedPresets}
        onPreset={togglePreset}
        onOptimize={runOptimize}
        optimizing={optimizing}
        recommendation={recommendation}
        onApplyRec={applyRecommendation}
        locks={locks}
      />
    </div>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<App />);
