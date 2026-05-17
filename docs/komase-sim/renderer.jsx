/* ============================================================
   renderer.jsx — Canvas 描画
   ============================================================ */
window.SimRenderer = (function() {

  function makeMap(canvas, params) {
    const W = canvas.width;
    const H = canvas.height;
    // World viewport: 船(x=0)を画面 35% 付近に置き、潮下流へ充分なスペースを確保
    const xMin = -26;
    const xMax = Math.max(48, 22 + params.tideSpeed * 75);
    const yMin = -7;
    const yMax = params.depth + 4;
    const sx = W / (xMax - xMin);
    const sy = H / (yMax - yMin);
    return {
      x: wx => (wx - xMin) * sx,
      y: wy => (wy - yMin) * sy,
      sx, sy, W, H, xMin, xMax, yMin, yMax,
    };
  }

  // ------- Heatmap (粒子密度) -------
  function makeHeatmap(cellsX, cellsY) {
    return {
      cellsX, cellsY,
      grid: new Float32Array(cellsX * cellsY),
      max: 1,
    };
  }
  function heatmapStep(hm, map, particles, dt) {
    const decay = Math.exp(-0.55 * dt);
    for (let i = 0; i < hm.grid.length; i++) hm.grid[i] *= decay;
    for (const p of particles) {
      const fx = (p.x - map.xMin) / (map.xMax - map.xMin);
      const fy = (p.y - map.yMin) / (map.yMax - map.yMin);
      if (fx < 0 || fx >= 1 || fy < 0 || fy >= 1) continue;
      const gx = Math.floor(fx * hm.cellsX);
      const gy = Math.floor(fy * hm.cellsY);
      hm.grid[gy * hm.cellsX + gx] += 1;
    }
    let m = 1;
    for (let i = 0; i < hm.grid.length; i++) if (hm.grid[i] > m) m = hm.grid[i];
    hm.max = m * 0.4 + hm.max * 0.6;
  }
  function drawHeatmap(ctx, hm, map) {
    const cellW = map.W / hm.cellsX;
    const cellH = map.H / hm.cellsY;
    for (let y = 0; y < hm.cellsY; y++) {
      for (let x = 0; x < hm.cellsX; x++) {
        const v = hm.grid[y * hm.cellsX + x] / hm.max;
        if (v < 0.08) continue;
        const a = Math.min(0.45, v * 0.45);
        ctx.fillStyle = `rgba(249, 115, 22, ${a})`;
        ctx.fillRect(x * cellW, y * cellH, cellW + 1, cellH + 1);
      }
    }
  }

  // ------- 背景: 海・海底 -------
  function drawBackground(ctx, map, params, swellPhase) {
    const ySurface = map.y(0);
    const ySea = map.y(params.depth);
    // 空 (海面上) - 晴天グラデーション
    const skyG = ctx.createLinearGradient(0, 0, 0, ySurface);
    skyG.addColorStop(0, "#dbeafe");  // 上空: 淡シアン
    skyG.addColorStop(0.6, "#93c5fd"); // 中空: スカイブルー
    skyG.addColorStop(1, "#60a5fa");   // 水平線近: 濃いめ
    ctx.fillStyle = skyG;
    ctx.fillRect(0, 0, map.W, ySurface);
    // 海中グラデーション (濃紺・情報視認性優先)
    const g = ctx.createLinearGradient(0, ySurface, 0, ySea);
    g.addColorStop(0, "#1c4870");
    g.addColorStop(0.35, "#0f3157");
    g.addColorStop(0.75, "#0a213b");
    g.addColorStop(1, "#061525");
    ctx.fillStyle = g;
    ctx.fillRect(0, ySurface, map.W, ySea - ySurface);

    // 海面波線 (うねりが大きいほど振幅増)
    const swellAmpPx = Math.min(8, ((params.swellHeight || 0) * map.sy) * 0.45 + 1.2);
    const swellPhaseLocal = (swellPhase || 0);
    const period = Math.max(1, params.swellPeriod || 6);
    ctx.strokeStyle = "rgba(255, 255, 255, 0.55)";
    ctx.lineWidth = 1;
    ctx.beginPath();
    for (let x = 0; x <= map.W; x += 8) {
      const phase = x * 0.06 + swellPhaseLocal * (2 * Math.PI / period);
      const yy = ySurface + Math.sin(phase) * swellAmpPx;
      if (x === 0) ctx.moveTo(x, yy);
      else ctx.lineTo(x, yy);
    }
    ctx.stroke();

    // 深さグリッド
    ctx.strokeStyle = "rgba(255, 255, 255, 0.06)";
    ctx.fillStyle = "rgba(255, 255, 255, 0.45)";
    ctx.font = '10px "JetBrains Mono", monospace';
    for (let d = 5; d < params.depth; d += 5) {
      const py = map.y(d);
      ctx.beginPath();
      ctx.moveTo(0, py);
      ctx.lineTo(map.W, py);
      ctx.lineWidth = (d % 10 === 0) ? 0.6 : 0.25;
      ctx.stroke();
      if (d % 10 === 0) {
        ctx.fillText(`-${d}m`, 6, py - 3);
      }
    }
    // 海底
    ctx.fillStyle = "#3a2e1c";
    ctx.fillRect(0, ySea, map.W, map.H - ySea);
    // 海底テクスチャ (砂粒)
    ctx.fillStyle = "rgba(255, 255, 255, 0.07)";
    for (let i = 0; i < 60; i++) {
      const sx = (i * 73) % map.W;
      const sy = ySea + ((i * 47) % (map.H - ySea));
      ctx.fillRect(sx, sy, 1, 1);
    }
    ctx.strokeStyle = "rgba(255, 255, 255, 0.4)";
    ctx.lineWidth = 0.8;
    ctx.beginPath();
    ctx.moveTo(0, ySea);
    ctx.lineTo(map.W, ySea);
    ctx.stroke();

    // 中央: 中央深度 (大型文字)
  }

  // ------- 潮流矢印 -------
  function drawCurrent(ctx, map, params) {
    const baseX = map.W - 110;
    ctx.font = '9px "JetBrains Mono", monospace';
    ctx.fillStyle = "rgba(255, 255, 255, 0.6)";
    ctx.fillText("潮流 →", baseX, map.y(0) + 14);

    ctx.strokeStyle = "rgba(251, 191, 36, 0.85)";
    ctx.fillStyle = "rgba(251, 191, 36, 0.85)";
    ctx.lineWidth = 1.2;
    const steps = Math.floor(params.depth / 10);
    for (let i = 1; i <= steps; i++) {
      const d = i * 10;
      if (d >= params.depth - 2) break;
      const c = SimPhysics.current(d, params);
      const py = map.y(d);
      const len = Math.min(85, c * 80);
      if (len < 4) continue;
      ctx.beginPath();
      ctx.moveTo(baseX, py);
      ctx.lineTo(baseX + len, py);
      ctx.stroke();
      // 矢頭
      ctx.beginPath();
      ctx.moveTo(baseX + len, py);
      ctx.lineTo(baseX + len - 5, py - 3);
      ctx.lineTo(baseX + len - 5, py + 3);
      ctx.closePath();
      ctx.fill();
      ctx.fillStyle = "rgba(255, 255, 255, 0.5)";
      ctx.fillText(`${c.toFixed(2)}m/s`, baseX + 0, py - 4);
      ctx.fillStyle = "rgba(251, 191, 36, 0.85)";
    }
  }

  // ------- 船 + 竿 -------
  // 横断面側方視点。船首=左(やや上に反った形)、船尾=右(垂直)、釣り人(胴の間〜トモ寄り)。
  // 漁船シルエット (側面トラペゾイド) を再現。
  // boatOffsetY: うねりによる上下動 (Px, 正=上)
  function drawBoat(ctx, map, rodTipY, boatOffsetY) {
    const ofs = boatOffsetY || 0;
    const cx = map.x(0);
    const cy = map.y(0) - ofs;
    // 船体: 側面トラペゾイド (船首左に上反り、船尾右は垂直)
    ctx.fillStyle = "#0d2b4a";
    ctx.strokeStyle = "rgba(255, 255, 255, 0.85)";
    ctx.lineWidth = 1.3;
    ctx.beginPath();
    // 船首先端（左・上反り）
    ctx.moveTo(cx - 60, cy - 8);
    ctx.lineTo(cx - 50, cy - 12);     // 舳先(へさき)頂点
    ctx.lineTo(cx + 50, cy - 12);     // デッキ上面トモまで
    ctx.lineTo(cx + 56, cy - 10);     // 船尾上端 (やや張出)
    ctx.lineTo(cx + 56, cy + 4);      // 船尾垂直
    ctx.lineTo(cx + 48, cy + 10);     // 船尾下端
    ctx.lineTo(cx - 38, cy + 10);     // 船底ライン
    ctx.quadraticCurveTo(cx - 58, cy + 6, cx - 60, cy - 8); // 船首水切り
    ctx.closePath();
    ctx.fill();
    ctx.stroke();
    // デッキ上端のハイライト線
    ctx.strokeStyle = "rgba(255, 255, 255, 0.55)";
    ctx.lineWidth = 0.7;
    ctx.beginPath();
    ctx.moveTo(cx - 50, cy - 12);
    ctx.lineTo(cx + 50, cy - 12);
    ctx.stroke();
    // 喫水線 (船底〜水面)
    ctx.strokeStyle = "rgba(253, 186, 116, 0.4)";
    ctx.lineWidth = 0.5;
    ctx.beginPath();
    ctx.moveTo(cx - 56, cy - 1);
    ctx.lineTo(cx + 54, cy - 1);
    ctx.stroke();
    // キャビン（前方寄り）
    ctx.fillStyle = "#0d2b4a";
    ctx.strokeStyle = "rgba(255, 255, 255, 0.7)";
    ctx.lineWidth = 1.0;
    ctx.beginPath();
    ctx.moveTo(cx - 36, cy - 12);
    ctx.lineTo(cx - 36, cy - 30);
    ctx.lineTo(cx - 30, cy - 34);
    ctx.lineTo(cx - 8, cy - 34);
    ctx.lineTo(cx - 4, cy - 30);
    ctx.lineTo(cx - 4, cy - 12);
    ctx.closePath();
    ctx.fill();
    ctx.stroke();
    // キャビン窓 (3つ)
    ctx.fillStyle = "rgba(253, 186, 116, 0.42)";
    ctx.fillRect(cx - 33, cy - 28, 7, 7);
    ctx.fillRect(cx - 24, cy - 28, 7, 7);
    ctx.fillRect(cx - 15, cy - 28, 7, 7);
    // 操舵室上のアンテナ・マスト
    ctx.strokeStyle = "rgba(255, 255, 255, 0.78)";
    ctx.lineWidth = 1.0;
    ctx.beginPath();
    ctx.moveTo(cx - 22, cy - 34);
    ctx.lineTo(cx - 22, cy - 52);
    ctx.stroke();
    // マスト上のライト
    ctx.fillStyle = "rgba(253, 186, 116, 0.9)";
    ctx.beginPath();
    ctx.arc(cx - 22, cy - 54, 1.8, 0, Math.PI * 2);
    ctx.fill();
    // 横ヤード
    ctx.strokeStyle = "rgba(255, 255, 255, 0.55)";
    ctx.lineWidth = 0.7;
    ctx.beginPath();
    ctx.moveTo(cx - 30, cy - 46);
    ctx.lineTo(cx - 14, cy - 46);
    ctx.stroke();
    // 手摺（船縁ライン・後部デッキ）
    ctx.strokeStyle = "rgba(255, 255, 255, 0.45)";
    ctx.lineWidth = 0.5;
    ctx.beginPath();
    ctx.moveTo(cx - 4, cy - 16);
    ctx.lineTo(cx + 52, cy - 16);
    ctx.stroke();
    // 手摺の支柱
    for (let xs of [cx, cx + 14, cx + 28, cx + 42]) {
      ctx.beginPath();
      ctx.moveTo(xs, cy - 12);
      ctx.lineTo(xs, cy - 16);
      ctx.stroke();
    }
    // ロッドキーパー (胴の間〜トモ・右舷)
    ctx.strokeStyle = "rgba(255, 255, 255, 0.7)";
    ctx.lineWidth = 1.0;
    ctx.beginPath();
    ctx.moveTo(cx + 30, cy - 12);
    ctx.lineTo(cx + 30, cy - 20);
    ctx.stroke();
    // 釣り人シルエット（胴の間・トモ寄り）
    const pX = cx + 22;
    const pY = cy - 18;
    ctx.fillStyle = "#0d2b4a";
    ctx.strokeStyle = "rgba(255, 255, 255, 0.5)";
    ctx.lineWidth = 0.5;
    // 頭
    ctx.beginPath();
    ctx.arc(pX, pY - 6, 3.4, 0, Math.PI*2);
    ctx.fill();
    ctx.stroke();
    // 胴体
    ctx.beginPath();
    ctx.moveTo(pX - 3.5, pY - 3);
    ctx.lineTo(pX + 4.5, pY - 3);
    ctx.lineTo(pX + 5, pY + 6);
    ctx.lineTo(pX - 3, pY + 6);
    ctx.closePath();
    ctx.fill();
    ctx.stroke();
    // 竿（右舷ロッドキーパー → ティップ）
    // 竿先は世界座標 ROD_X_M (=6m) に固定。これでビシも竿先の真下に静止する。
    const rodGripX = cx + 30;
    const rodGripY = cy - 18;
    const rodTipXPx = map.x(window.SimPhysics ? window.SimPhysics.ROD_X_M : 6);
    ctx.strokeStyle = "rgba(255, 255, 255, 0.92)";
    ctx.lineWidth = 1.8;
    ctx.beginPath();
    ctx.moveTo(rodGripX, rodGripY);
    const bendX = (rodGripX + rodTipXPx) / 2;
    ctx.quadraticCurveTo(bendX, cy - 32, rodTipXPx, rodTipY);
    ctx.stroke();
    // ガイドリング
    ctx.fillStyle = "rgba(255, 255, 255, 0.85)";
    for (let i = 1; i <= 5; i++) {
      const t = i / 6;
      const rx = rodGripX + (rodTipXPx - rodGripX) * t;
      const ry = rodGripY + (rodTipY - rodGripY) * (t * 0.5 + t * t * 0.5);
      ctx.beginPath();
      ctx.arc(rx, ry, 1.0, 0, Math.PI * 2);
      ctx.fill();
    }
  }

  // ------- 仕掛け (PEライン・ビシ・ハリス・ガン玉・針) -------
  function drawRig(ctx, map, rig, params, rodTipY, chumLevel, boatOffsetY) {
    if (chumLevel == null) chumLevel = 1.0;
    const ofs = boatOffsetY || 0;
    // PEライン (太さは PE 号数で変動)
    ctx.strokeStyle = "rgba(255, 255, 255, 0.85)";
    ctx.lineWidth = 0.6 + (params.peNo || 2) * 0.14;
    // 竿先は世界座標 ROD_X_M に固定。ビシも静止時はこの真下。
    const rodTipX = map.x(window.SimPhysics ? window.SimPhysics.ROD_X_M : 6);
    const cx = map.x(rig.cage.x);
    const cy = map.y(rig.cage.y) - ofs * 0.35; // ビシは波の 35% 程度同期して揺れる
    // ★ 仕掛け構成 (ユーザー指示の天秤レイアウト):
    //     PE → 天秤の左端(J = カゴ吊下点 + PE接続点)
    //     天秤の腕 J → E (右下) に伸びる
    //     カゴは J から真下に吊り下げ
    //     クッションゴム は E から下方へ → ハリス → 針
    const cageW = 11, cageH = 22;
    // 天秤実寸 = 0.5m。クッションやハリスと同じ世界座標で描画して長さを正しく見せる。
    // 1m あたりピクセル: map.sy (≒12) を使用。水平方向は map.sx を使うが
    // 天秤の長さは Euclidean なので最小スケールで近似 (map.sy 基準)。
    const TENBIN_LEN_M = 0.5;
    const TENBIN_ANGLE_DEG = 25;  // 水平から (鈍角寄り = 水平に近い)
    const tenDxM = TENBIN_LEN_M * Math.cos(TENBIN_ANGLE_DEG * Math.PI / 180);  // 約 0.453m
    const tenDyM = TENBIN_LEN_M * Math.sin(TENBIN_ANGLE_DEG * Math.PI / 180);  // 約 0.211m
    // 世界座標 (m) で J 位置を計算 → pixel に変換
    const junctionX = map.x(rig.cage.x - tenDxM);
    const junctionY = map.y(rig.cage.y - tenDyM);
    // カゴ中心は J から真下に (画面上で 6px の吊り紐)
    const cageCenterX = junctionX;
    const cageTopY = junctionY + 6;

    // PE は基本まっすぐ。終点は J (天秤の左端 = PE接続点)。
    const ctrlX = junctionX + (rodTipX - junctionX) * 0.3 + Math.min(18, (params.tideSpeed || 0) * 14);
    const ctrlY = (rodTipY + junctionY) * 0.55;
    ctx.beginPath();
    ctx.moveTo(rodTipX, rodTipY);
    ctx.quadraticCurveTo(ctrlX, ctrlY, junctionX, junctionY);
    ctx.stroke();

    // 竿先 → ビシ 鉛直距離表示（縦点線＋ラベル）
    // 色階層: PE = ペーパーホワイト系（道糸イメージ・冷たい）
    // ★ 仕掛け側 (cx - 22) と同じ X 列に揃えて、海面→ビシ→付けエサが一直線上に並ぶようにする
    const peVertY1 = map.y(0); // 海面 (うねりに依らず固定)
    const peVertY2 = cy;
    const peGuideX = cx - 22;
    ctx.strokeStyle = "rgba(255, 255, 255, 0.45)";
    ctx.setLineDash([2, 3]);
    ctx.lineWidth = 0.6;
    ctx.beginPath();
    ctx.moveTo(peGuideX, peVertY1);
    ctx.lineTo(peGuideX, peVertY2);
    ctx.stroke();
    ctx.setLineDash([]);
    // 端点マーカー
    ctx.strokeStyle = "rgba(255, 255, 255, 0.7)";
    ctx.lineWidth = 0.9;
    ctx.beginPath();
    ctx.moveTo(peGuideX - 4, peVertY1); ctx.lineTo(peGuideX + 4, peVertY1);
    ctx.moveTo(peGuideX - 4, peVertY2); ctx.lineTo(peGuideX + 4, peVertY2);
    ctx.stroke();
    // ラベル (左側に置く=仕掛けラベルと同じ向きで揃える)
    const peVertM = (rig.cage.y - 0);
    const peHorizM = (rig.cage.x - (window.SimPhysics ? window.SimPhysics.ROD_X_M : 6));
    const peTotalM = Math.sqrt(peVertM * peVertM + peHorizM * peHorizM);
    ctx.fillStyle = "rgba(255, 255, 255, 0.95)";
    ctx.font = '10px "JetBrains Mono", monospace';
    const peMidY = (peVertY1 + peVertY2) / 2;
    ctx.fillText(`↕ ${peVertM.toFixed(1)}m`, peGuideX - 70, peMidY - 2);
    ctx.fillStyle = "rgba(255, 255, 255, 0.55)";
    ctx.font = '9px "JetBrains Mono", monospace';
    ctx.fillText(`(ライン長${peTotalM.toFixed(1)}m)`, peGuideX - 100, peMidY + 10);

    // 天秤 (yajiri arm): 左端 J → 右下 E (= cushion 接続点 cx, cy) に伸びる金属棒
    ctx.strokeStyle = "rgba(220, 230, 240, 0.90)";
    ctx.lineWidth = 1.8;
    ctx.beginPath();
    ctx.moveTo(junctionX, junctionY);
    ctx.lineTo(cx, cy);
    ctx.stroke();
    // カゴ吊下紐 (J → カゴ上端)
    ctx.strokeStyle = "rgba(220, 230, 240, 0.55)";
    ctx.lineWidth = 0.8;
    ctx.beginPath();
    ctx.moveTo(junctionX, junctionY);
    ctx.lineTo(cageCenterX, cageTopY);
    ctx.stroke();
    // J リング (PE 結束点)
    ctx.fillStyle = "rgba(220, 230, 240, 0.95)";
    ctx.beginPath();
    ctx.arc(junctionX, junctionY, 2.0, 0, Math.PI*2);
    ctx.fill();
    // E リング (天秤の cushion 接続点)
    ctx.beginPath();
    ctx.arc(cx, cy, 1.5, 0, Math.PI*2);
    ctx.fill();

    // ビシ本体 (カゴ): 上が広く・下が少し角ばった形 (底面が小さく台形)
    //   形状: 八角形/台形ベース
    //     top L:    (cageCenterX - cageW/2, cageTopY)
    //     top R:    (cageCenterX + cageW/2, cageTopY)
    //     side L:   ...垂直
    //     side R:   ...垂直
    //     底面 angle: 左右内側に折れて底辺 (cageW - 4) で平らに
    const cageBotY = cageTopY + cageH;
    const cageTopL = cageCenterX - cageW/2;
    const cageTopR = cageCenterX + cageW/2;
    const cageBotL = cageCenterX - (cageW/2 - 2);
    const cageBotR = cageCenterX + (cageW/2 - 2);
    const cageAngleY = cageBotY - 4;  // ここから底面の角がつく
    // 錘の蓋 (上端の金属蓋)
    ctx.fillStyle = "#1e293b";
    ctx.fillRect(cageTopL - 1, cageTopY - 3, cageW + 2, 4);
    // カゴ本体パス
    ctx.beginPath();
    ctx.moveTo(cageTopL, cageTopY);
    ctx.lineTo(cageTopR, cageTopY);
    ctx.lineTo(cageTopR, cageAngleY);
    ctx.lineTo(cageBotR, cageBotY);
    ctx.lineTo(cageBotL, cageBotY);
    ctx.lineTo(cageTopL, cageAngleY);
    ctx.closePath();
    ctx.fillStyle = "#475569";
    ctx.fill();
    // コマセ充填レベル (内側を coral で塗る・台形クリップ風)
    if (chumLevel > 0.01) {
      const innerW = cageW - 3;
      const fullH = cageH - 4;
      const fillH = fullH * Math.max(0, Math.min(1, chumLevel));
      const fy = cageBotY - 2 - fillH;
      const gd = ctx.createLinearGradient(0, fy, 0, fy + fillH);
      gd.addColorStop(0, "rgba(253, 186, 116, 0.95)");
      gd.addColorStop(1, "rgba(232, 93, 4, 0.95)");
      ctx.save();
      ctx.beginPath();
      ctx.moveTo(cageTopL+1, cageTopY+1);
      ctx.lineTo(cageTopR-1, cageTopY+1);
      ctx.lineTo(cageTopR-1, cageAngleY);
      ctx.lineTo(cageBotR-0.5, cageBotY-0.5);
      ctx.lineTo(cageBotL+0.5, cageBotY-0.5);
      ctx.lineTo(cageTopL+1, cageAngleY);
      ctx.closePath();
      ctx.clip();
      ctx.fillStyle = gd;
      ctx.fillRect(cageCenterX - innerW/2, fy, innerW, fillH);
      ctx.restore();
    }
    // 枠線
    ctx.strokeStyle = "rgba(255, 255, 255, 0.65)";
    ctx.lineWidth = 0.9;
    ctx.beginPath();
    ctx.moveTo(cageTopL, cageTopY);
    ctx.lineTo(cageTopR, cageTopY);
    ctx.lineTo(cageTopR, cageAngleY);
    ctx.lineTo(cageBotR, cageBotY);
    ctx.lineTo(cageBotL, cageBotY);
    ctx.lineTo(cageTopL, cageAngleY);
    ctx.closePath();
    ctx.stroke();
    // メッシュ (前面横線・3-4本に減らす)
    ctx.strokeStyle = "rgba(13, 43, 74, 0.55)";
    ctx.lineWidth = 0.4;
    for (let i = 1; i < 4; i++) {
      const ly = cageTopY + (cageH/4) * i;
      ctx.beginPath();
      ctx.moveTo(cageTopL+1, ly);
      ctx.lineTo(cageTopR-1, ly);
      ctx.stroke();
    }
    // 開口部 — 上窓と下窓
    const upperOp = params.cageUpperOpening != null ? params.cageUpperOpening : (params.cageOpening || 0);
    const lowerOp = params.cageLowerOpening != null ? params.cageLowerOpening : (params.cageOpening || 0);
    if (upperOp > 0.05 && chumLevel > 0.05) {
      const op = Math.min(cageW - 2, upperOp * cageW);
      ctx.fillStyle = "#f97316";
      ctx.fillRect(cageCenterX - op/2, cageTopY - 1, op, 2);
    }
    if (lowerOp > 0.05 && chumLevel > 0.05) {
      const op = Math.min(cageW - 4, lowerOp * (cageW - 4));
      ctx.fillStyle = "rgba(249, 115, 22, 0.7)";
      ctx.fillRect(cageCenterX - op/2, cageBotY - 1, op, 2);
    }

    // 仕掛け描画: クッションゴム → モトス → サル管 → ハリス を別スタイルで
    const yShift = ofs * 0.35;
    const cushionEndIdx = rig.cushionEndIdx != null ? rig.cushionEndIdx : 0;
    const motosEndIdx = rig.motosEndIdx != null ? rig.motosEndIdx : cushionEndIdx;
    // クッションゴム区間（太めの朱色・ゴムを表現）
    if (cushionEndIdx > 0) {
      ctx.strokeStyle = "rgba(232, 93, 4, 0.75)";
      ctx.lineWidth = 2.2;
      ctx.beginPath();
      ctx.moveTo(cx, cy);
      for (let i = 0; i <= cushionEndIdx; i++) {
        const p = rig.harris[i];
        ctx.lineTo(map.x(p.x), map.y(p.y) - yShift);
      }
      ctx.stroke();
    }
    // モトス区間（太めの薄白・上ハリス）
    if (motosEndIdx > cushionEndIdx) {
      ctx.strokeStyle = "rgba(255, 255, 255, 0.85)";
      ctx.lineWidth = 1.4;
      ctx.beginPath();
      const motosStart = rig.harris[cushionEndIdx];
      ctx.moveTo(map.x(motosStart.x), map.y(motosStart.y) - yShift);
      for (let i = cushionEndIdx + 1; i <= motosEndIdx; i++) {
        const p = rig.harris[i];
        ctx.lineTo(map.x(p.x), map.y(p.y) - yShift);
      }
      ctx.stroke();
      // サル管 (モトス末端の小リング)
      const sk = rig.harris[motosEndIdx];
      const skX = map.x(sk.x), skY = map.y(sk.y) - yShift;
      ctx.fillStyle = "rgba(220, 230, 240, 0.95)";
      ctx.strokeStyle = "rgba(50, 60, 70, 0.6)";
      ctx.lineWidth = 0.5;
      ctx.beginPath();
      ctx.arc(skX, skY, 2.2, 0, Math.PI*2);
      ctx.fill();
      ctx.stroke();
    }
    // ハリス区間（細い透明白）
    ctx.strokeStyle = "rgba(255, 255, 255, 0.55)";
    ctx.lineWidth = 0.7;
    ctx.beginPath();
    const startIdx = Math.max(0, motosEndIdx);
    const startPt = rig.harris[startIdx];
    ctx.moveTo(map.x(startPt.x), map.y(startPt.y) - yShift);
    for (let i = startIdx + 1; i < rig.harris.length; i++) {
      const p = rig.harris[i];
      ctx.lineTo(map.x(p.x), map.y(p.y) - yShift);
    }
    ctx.stroke();

    // ガン玉
    const g = rig.ganDama;
    if (params.ganDamaSize > 0.05) {
      const gx = map.x(g.x), gy = map.y(g.y) - yShift;
      ctx.fillStyle = "#1e293b";
      ctx.strokeStyle = "rgba(255, 255, 255, 0.5)";
      ctx.lineWidth = 0.5;
      const gr = 1.8 + params.ganDamaSize * 2.2;
      ctx.beginPath();
      ctx.arc(gx, gy, gr, 0, Math.PI*2);
      ctx.fill();
      ctx.stroke();
    }

    // 付けエサ + 針 (琥珀系で識別)
    const h = rig.hook;
    const hx = map.x(h.x), hy = map.y(h.y) - yShift;
    // 効くゾーン (付けエサ周辺 1.8m) — 琥珀
    ctx.strokeStyle = "rgba(212, 160, 23, 0.55)";
    ctx.fillStyle = "rgba(212, 160, 23, 0.08)";
    ctx.setLineDash([3, 3]);
    ctx.lineWidth = 0.8;
    ctx.beginPath();
    const ez = Math.min(map.sx, map.sy) * 1.8;
    ctx.ellipse(hx, hy, ez, ez * 0.85, 0, 0, Math.PI*2);
    ctx.fill();
    ctx.stroke();
    ctx.setLineDash([]);

    // 針 (琥珀)
    ctx.strokeStyle = "#fbbf24";
    ctx.lineWidth = 1.1;
    ctx.beginPath();
    ctx.arc(hx - 1, hy + 2, 3.2, Math.PI * 0.0, Math.PI * 1.55);
    ctx.stroke();
    ctx.beginPath();
    ctx.moveTo(hx - 4, hy + 4.5);
    ctx.lineTo(hx - 6, hy + 3.2);
    ctx.stroke();
    // 付けエサ (琥珀オキアミ)
    ctx.fillStyle = "#d4a017";
    ctx.beginPath();
    ctx.ellipse(hx + 3, hy + 3, 5.5, 2.8, 0.5, 0, Math.PI*2);
    ctx.fill();
    ctx.strokeStyle = "#92400e";
    ctx.lineWidth = 0.4;
    ctx.stroke();
  }

  // ------- 粒子 -------
  function drawParticles(ctx, map, particles) {
    for (const p of particles) {
      const alphaMul = p.alpha != null ? p.alpha : 1.0;
      const a = Math.min(1, p.life) * 0.88 * alphaMul;
      ctx.fillStyle = `rgba(253, 186, 116, ${a})`;
      const r = p.size * 0.85;
      ctx.beginPath();
      ctx.arc(map.x(p.x), map.y(p.y), r, 0, Math.PI*2);
      ctx.fill();
    }
  }

  // ------- 指示ダナの魚影（マダイのシルエット） -------
  // 指示ダナ周辺にマダイの群れが漂う。コマセを誘い込む対象。
  function drawFishShadows(ctx, map, params) {
    const t = Date.now() * 0.001;
    const tanaY = params.tanaDepth;
    // 4匹のマダイ。それぞれ独立に揺らぎ動作
    const fish = [
      { baseX: 14, baseY: tanaY - 0.3, phase: 0.0, speed: 0.7, size: 1.0 },
      { baseX: 22, baseY: tanaY + 0.6, phase: 1.8, speed: 0.55, size: 1.1 },
      { baseX: 32, baseY: tanaY - 0.8, phase: 3.1, speed: 0.65, size: 0.95 },
      { baseX: 42, baseY: tanaY + 0.4, phase: 4.5, speed: 0.5, size: 1.05 },
    ];
    fish.forEach((f) => {
      const fx = map.x(f.baseX + Math.sin(t * f.speed + f.phase) * 2.5);
      const fy = map.y(f.baseY + Math.sin(t * f.speed * 1.3 + f.phase) * 0.8);
      // 影 (赤茶のマダイらしい色、半透明)
      ctx.save();
      ctx.fillStyle = "rgba(232, 93, 4, 0.32)";
      ctx.strokeStyle = "rgba(232, 93, 4, 0.55)";
      ctx.lineWidth = 0.5;
      const bodyLen = 11 * f.size;
      const bodyH = 4.2 * f.size;
      // 体（楕円）
      ctx.beginPath();
      ctx.ellipse(fx, fy, bodyLen, bodyH, 0, 0, Math.PI * 2);
      ctx.fill();
      ctx.stroke();
      // 尾びれ
      ctx.beginPath();
      ctx.moveTo(fx - bodyLen + 1, fy);
      ctx.lineTo(fx - bodyLen - 5, fy - 4);
      ctx.lineTo(fx - bodyLen - 4, fy);
      ctx.lineTo(fx - bodyLen - 5, fy + 4);
      ctx.closePath();
      ctx.fill();
      ctx.stroke();
      // 背びれ（小さな三角）
      ctx.beginPath();
      ctx.moveTo(fx - 2, fy - bodyH);
      ctx.lineTo(fx + 2, fy - bodyH);
      ctx.lineTo(fx, fy - bodyH - 2.5);
      ctx.closePath();
      ctx.fill();
      // 目（白ドット）
      ctx.fillStyle = "rgba(255, 255, 255, 0.7)";
      ctx.beginPath();
      ctx.arc(fx + bodyLen * 0.55, fy - 0.5, 0.9, 0, Math.PI * 2);
      ctx.fill();
      ctx.restore();
    });
  }

  // ------- ラベル: タナ、ビシ深さ等 -------
  function drawLabels(ctx, map, params, rig, phase, swellOffsetM) {
    const sm = swellOffsetM || 0;
    const yShiftPx = sm * 0.35 * map.sy;
    ctx.font = '10px "JetBrains Mono", monospace';
    ctx.fillStyle = "rgba(255, 255, 255, 0.85)";
    // ビシ
    const cx = map.x(rig.cage.x), cy = map.y(rig.cage.y) - yShiftPx;
    ctx.fillText(`ビシ ${(rig.cage.y - sm * 0.35).toFixed(1)}m`, cx + 14, cy - 4);
    // 付けエサ
    const hx = map.x(rig.hook.x), hy = map.y(rig.hook.y) - yShiftPx;
    ctx.fillStyle = "rgba(251, 191, 36, 0.95)";
    ctx.fillText(`付けエサ ${(rig.hook.y - sm * 0.35).toFixed(1)}m`, hx + 14, hy + 4);
    // 鉛直距離 (ビシと付けエサの y 差)
    // 色階層: 仕掛け = 朱寄り (ハリス・付けエサイメージ・暖色)
    const vertLen = rig.hook.y - rig.cage.y;
    const rigTotal = (params.cushionLength || 1) + (params.harrisLength || 8);
    const midY = (cy + hy) / 2;
    ctx.strokeStyle = "rgba(232, 93, 4, 0.55)";
    ctx.setLineDash([2, 3]);
    ctx.lineWidth = 0.7;
    ctx.beginPath();
    ctx.moveTo(cx - 22, cy);
    ctx.lineTo(cx - 22, hy);
    ctx.stroke();
    ctx.setLineDash([]);
    // 端点マーカー
    ctx.strokeStyle = "rgba(232, 93, 4, 0.85)";
    ctx.lineWidth = 1.0;
    ctx.beginPath();
    ctx.moveTo(cx - 26, cy); ctx.lineTo(cx - 18, cy);
    ctx.moveTo(cx - 26, hy); ctx.lineTo(cx - 18, hy);
    ctx.stroke();
    // ラベル
    ctx.fillStyle = "rgba(249, 115, 22, 0.95)";
    ctx.font = '10px "JetBrains Mono", monospace';
    const ratio = rigTotal > 0 ? (vertLen / rigTotal * 100).toFixed(0) : 100;
    ctx.fillText(`↕ ${vertLen.toFixed(1)}m`, cx - 70, midY - 2);
    ctx.fillStyle = "rgba(249, 115, 22, 0.7)";
    ctx.font = '9px "JetBrains Mono", monospace';
    ctx.fillText(`(ハリス長${rigTotal.toFixed(0)}m / ${ratio}%)`, cx - 100, midY + 10);

    // 指示ダナ ライン
    const taX = map.y(params.tanaDepth);
    // コマセ目標帯（指示ダナ ±1m を緑半透明バンドで強調）
    const bandTop = map.y(params.tanaDepth - 1);
    const bandBottom = map.y(params.tanaDepth + 1);
    ctx.fillStyle = "rgba(26, 157, 86, 0.07)";
    ctx.fillRect(0, bandTop, map.W, bandBottom - bandTop);
    // 帯の境界線
    ctx.strokeStyle = "rgba(26, 157, 86, 0.22)";
    ctx.lineWidth = 0.5;
    ctx.setLineDash([2, 4]);
    ctx.beginPath();
    ctx.moveTo(0, bandTop); ctx.lineTo(map.W, bandTop);
    ctx.moveTo(0, bandBottom); ctx.lineTo(map.W, bandBottom);
    ctx.stroke();
    ctx.setLineDash([]);

    ctx.strokeStyle = "rgba(251, 191, 36, 0.45)";
    ctx.setLineDash([5, 4]);
    ctx.lineWidth = 1.0;
    ctx.beginPath();
    ctx.moveTo(0, taX);
    ctx.lineTo(map.W, taX);
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillStyle = "rgba(251, 191, 36, 0.85)";
    ctx.fillText(`指示ダナ ${params.tanaDepth}m`, 8, taX - 4);

    // 落とし込み目安 = ビシの初期位置 (指示棚 + dropOffsetM)
    const dropOff = params.dropOffsetM != null ? params.dropOffsetM : 5;
    const dropTargetY = map.y(params.tanaDepth + dropOff);
    ctx.strokeStyle = "rgba(212, 160, 23, 0.30)";
    ctx.setLineDash([3, 6]);
    ctx.lineWidth = 0.7;
    ctx.beginPath();
    ctx.moveTo(0, dropTargetY);
    ctx.lineTo(map.W, dropTargetY);
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillStyle = "rgba(212, 160, 23, 0.65)";
    const offLabel = dropOff === 0 ? "指示棚" : (dropOff > 0 ? `タナ下${dropOff.toFixed(1)}m` : `タナ上${(-dropOff).toFixed(1)}m`);
    ctx.fillText(`▼ ビシ落としこみ目安 ${(params.tanaDepth + dropOff).toFixed(1)}m (${offLabel})`, 8, dropTargetY - 3);

    // コマセ雲の中心深度（外部から渡されたら描画）
    if (params._komaseDepth != null && isFinite(params._komaseDepth)) {
      const ky = map.y(params._komaseDepth);
      ctx.strokeStyle = "rgba(253, 186, 116, 0.55)";
      ctx.setLineDash([8, 4]);
      ctx.lineWidth = 1.0;
      ctx.beginPath();
      ctx.moveTo(0, ky);
      ctx.lineTo(map.W, ky);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = "rgba(253, 186, 116, 0.85)";
      ctx.fillText(`☁ コマセ雲 ${params._komaseDepth.toFixed(1)}m`, map.W - 130, ky - 3);
    }

    // 落とし込み中バナー
    if (phase === "dropping") {
      ctx.fillStyle = "rgba(232, 93, 4, 0.9)";
      ctx.font = '13px "Shippori Mincho", serif';
      ctx.fillText("● 落とし込み中（沈降速度 " + (params.dropSpeed || 1.5).toFixed(1) + "m/s）", map.W / 2 - 130, 26);
      if (rig.lagRatio != null && rig.lagRatio > 0.1) {
        ctx.fillStyle = "rgba(253, 186, 116, 0.9)";
        ctx.font = '10px "JetBrains Mono", monospace';
        ctx.fillText(`ハリス落ち遅れ ${(rig.lagRatio * 100).toFixed(0)}%`, map.W / 2 - 60, 44);
      }
    }
    // うねり情報
    if ((params.swellHeight || 0) > 0.05) {
      ctx.fillStyle = "rgba(253, 186, 116, 0.85)";
      ctx.font = '10px "JetBrains Mono", monospace';
      const arrow = sm > 0 ? "↑" : sm < 0 ? "↓" : "・";
      ctx.fillText(`うねり ${params.swellHeight.toFixed(1)}m / ${(params.swellPeriod || 6).toFixed(1)}s  船 ${arrow}${Math.abs(sm).toFixed(2)}m`, 8, map.H - 10);
    }
  }

  // ------- 船首視点ミニビュー（船を真上から見下ろした図・横向き） -------
  // 釣り座（左舷 or 右舷）で船と潮の向きが反転する：
  //   side="port"      (左舷): 船首=右、船尾=左、潮=右→左
  //   side="starboard" (右舷): 船首=左、船尾=右、潮=左→右
  // 竿と糸は釣り人の前（上方向）へ。
  const BOW_VIEW_W = 178;
  const BOW_VIEW_H = 150;
  const BOW_VIEW_TOGGLE_X = 8;
  const BOW_VIEW_TOGGLE_Y = 32;
  const BOW_VIEW_TOGGLE_W = 56;
  const BOW_VIEW_TOGGLE_H = 16;
  function drawBowView(ctx, bx, by, params, rig, side) {
    const boxW = BOW_VIEW_W;
    const boxH = BOW_VIEW_H;
    const isStarboard = side === "starboard";
    const xs = isStarboard ? -1 : 1;
    ctx.fillStyle = "rgba(13, 43, 74, 0.92)";
    ctx.strokeStyle = "rgba(255, 255, 255, 0.32)";
    ctx.lineWidth = 0.8;
    ctx.fillRect(bx, by, boxW, boxH);
    ctx.strokeRect(bx, by, boxW, boxH);

    ctx.font = '11px "Shippori Mincho", serif';
    ctx.fillStyle = "rgba(255, 255, 255, 0.92)";
    ctx.fillText("船上から見た図", bx + 8, by + 16);
    ctx.font = '9px "JetBrains Mono", monospace';
    ctx.fillStyle = "rgba(255, 255, 255, 0.5)";
    ctx.fillText("（真俯瞰・PE 入水方向）", bx + 8, by + 28);
    // ドラッグハンドル
    ctx.strokeStyle = "rgba(255, 255, 255, 0.55)";
    ctx.lineWidth = 1.0;
    for (let i = 0; i < 3; i++) {
      const hy = by + 10 + i * 4;
      ctx.beginPath();
      ctx.moveTo(bx + boxW - 18, hy);
      ctx.lineTo(bx + boxW - 8, hy);
      ctx.stroke();
    }

    // 左舷/右舷切替ボタン
    const tgX = bx + boxW - BOW_VIEW_TOGGLE_X - BOW_VIEW_TOGGLE_W;
    const tgY = by + BOW_VIEW_TOGGLE_Y;
    ctx.fillStyle = "rgba(232, 93, 4, 0.15)";
    ctx.strokeStyle = "rgba(232, 93, 4, 0.55)";
    ctx.lineWidth = 0.8;
    ctx.fillRect(tgX, tgY, BOW_VIEW_TOGGLE_W, BOW_VIEW_TOGGLE_H);
    ctx.strokeRect(tgX, tgY, BOW_VIEW_TOGGLE_W, BOW_VIEW_TOGGLE_H);
    ctx.font = '9px "Shippori Mincho", serif';
    ctx.fillStyle = "rgba(255, 255, 255, 0.9)";
    ctx.textAlign = "center";
    ctx.fillText(isStarboard ? "▶ 右舷" : "◀ 左舷", tgX + BOW_VIEW_TOGGLE_W / 2, tgY + 11);
    ctx.textAlign = "start";

    const cx = bx + boxW * 0.4;
    const cy = by + 78;

    // 水面リング
    ctx.strokeStyle = "rgba(186, 230, 253, 0.55)";
    ctx.lineWidth = 0.5;
    for (let r = 18; r < 76; r += 18) {
      ctx.beginPath();
      ctx.arc(cx, cy, r, 0, Math.PI * 2);
      ctx.stroke();
    }

    // 船シルエット
    ctx.fillStyle = "#0d2b4a";
    ctx.strokeStyle = "rgba(255, 255, 255, 0.8)";
    ctx.lineWidth = 1.0;
    ctx.beginPath();
    ctx.moveTo(cx + 24*xs, cy);
    ctx.lineTo(cx + 16*xs, cy - 9);
    ctx.lineTo(cx - 14*xs, cy - 9);
    ctx.lineTo(cx - 14*xs, cy + 9);
    ctx.lineTo(cx + 16*xs, cy + 9);
    ctx.closePath();
    ctx.fill();
    ctx.stroke();
    // キャビン
    ctx.fillStyle = "#1e3a5f";
    ctx.fillRect(cx + (isStarboard ? -10 : 0), cy - 5, 10, 10);
    ctx.strokeStyle = "rgba(255, 255, 255, 0.55)";
    ctx.lineWidth = 0.5;
    ctx.strokeRect(cx + (isStarboard ? -10 : 0), cy - 5, 10, 10);
    // 船首マーカー
    ctx.fillStyle = "rgba(253, 186, 116, 0.9)";
    ctx.beginPath();
    ctx.moveTo(cx + 24*xs, cy);
    ctx.lineTo(cx + 19*xs, cy - 3);
    ctx.lineTo(cx + 19*xs, cy + 3);
    ctx.closePath();
    ctx.fill();
    // ラベル
    ctx.font = '8px "JetBrains Mono", monospace';
    ctx.fillStyle = "rgba(253, 186, 116, 0.8)";
    ctx.fillText("船首", cx + (isStarboard ? -30 : 18), cy - 14);
    ctx.fillStyle = "rgba(255, 255, 255, 0.45)";
    ctx.fillText("船尾", cx + (isStarboard ? 18 : -32), cy + 4);

    // 潮流矢印
    const tide = params.tideSpeed || 0;
    const arrowLen = Math.min(50, tide * 60);
    ctx.strokeStyle = "rgba(251, 191, 36, 0.9)";
    ctx.fillStyle = "rgba(251, 191, 36, 0.9)";
    ctx.lineWidth = 1.0;
    if (arrowLen > 4) {
      const ay = by + boxH - 30;
      const ax = isStarboard ? (bx + 16) : (bx + boxW - 16);
      const aEnd = ax + (isStarboard ? arrowLen : -arrowLen);
      ctx.beginPath();
      ctx.moveTo(ax, ay);
      ctx.lineTo(aEnd, ay);
      ctx.stroke();
      ctx.beginPath();
      ctx.moveTo(aEnd, ay);
      ctx.lineTo(aEnd + (isStarboard ? -5 : 5), ay - 3);
      ctx.lineTo(aEnd + (isStarboard ? -5 : 5), ay + 3);
      ctx.closePath();
      ctx.fill();
      ctx.font = '8px "JetBrains Mono", monospace';
      ctx.fillStyle = "rgba(251, 191, 36, 0.75)";
      ctx.fillText("潮", ax + (isStarboard ? -2 : -6), ay - 4);
    }

    // 入水角計算
    const tana = Math.max(0.5, params.tanaDepth);
    const horizDisp = (window.SimPhysics && window.SimPhysics.pelineDrift)
      ? window.SimPhysics.pelineDrift(params, tana)
      : (params.tideSpeed || 0) * 0.6 * 1.6;
    const lineAngleRad = Math.atan2(horizDisp, tana);
    const lineAngleDeg = lineAngleRad * 180 / Math.PI;

    // 竿先
    const rodX = cx + (isStarboard ? 8 : -8);
    const rodY = cy - 9;
    const tipX = rodX + (isStarboard ? 3 : -3);
    const tipY = rodY - 14;
    ctx.strokeStyle = "rgba(255, 255, 255, 0.7)";
    ctx.lineWidth = 1.2;
    ctx.beginPath();
    ctx.moveTo(rodX, rodY);
    ctx.lineTo(tipX, tipY);
    ctx.stroke();

    // 入水点
    const driftPx = Math.min(48, lineAngleDeg * 0.9);
    const entryX = tipX + (isStarboard ? driftPx : -driftPx);
    const entryY = tipY - 6 - Math.min(10, lineAngleDeg * 0.1);
    ctx.strokeStyle = "rgba(255, 255, 255, 0.95)";
    ctx.lineWidth = 1.4;
    ctx.beginPath();
    ctx.moveTo(tipX, tipY);
    ctx.lineTo(entryX, entryY);
    ctx.stroke();
    ctx.fillStyle = "rgba(232, 93, 4, 0.95)";
    ctx.beginPath();
    ctx.arc(entryX, entryY, 3.2, 0, Math.PI * 2);
    ctx.fill();
    ctx.strokeStyle = "rgba(253, 186, 116, 0.6)";
    ctx.lineWidth = 0.5;
    ctx.stroke();

    // 角度・評価
    ctx.font = '9px "JetBrains Mono", monospace';
    ctx.fillStyle = "rgba(253, 186, 116, 0.95)";
    ctx.fillText(`入水角 ${lineAngleDeg.toFixed(0)}°`, bx + 8, by + boxH - 16);
    let judge, judgeColor;
    if (lineAngleDeg < 10) { judge = "ほぼ真下 ・凪"; judgeColor = "rgba(26,157,86,0.95)"; }
    else if (lineAngleDeg < 22) { judge = "緩い流れ ・標準"; judgeColor = "rgba(255,255,255,0.92)"; }
    else if (lineAngleDeg < 38) { judge = "流れ強 ・警戒"; judgeColor = "rgba(251,191,36,0.95)"; }
    else { judge = "速潮 ・オモリ↑"; judgeColor = "rgba(232,93,4,0.95)"; }
    ctx.fillStyle = judgeColor;
    ctx.fillText(judge, bx + 60, by + boxH - 16);
    ctx.font = '9px "JetBrains Mono", monospace';
    ctx.fillStyle = "rgba(255, 255, 255, 0.5)";
    ctx.fillText(`潮 ${tide.toFixed(2)}m/s`, bx + boxW - 60, by + boxH - 6);
  }

  return {
    BOW_VIEW_W, BOW_VIEW_H,
    BOW_VIEW_TOGGLE_X, BOW_VIEW_TOGGLE_Y, BOW_VIEW_TOGGLE_W, BOW_VIEW_TOGGLE_H,
    makeMap, makeHeatmap, heatmapStep, drawHeatmap,
    drawBackground, drawCurrent, drawBoat, drawFishShadows,
    drawRig, drawParticles, drawLabels, drawBowView,
  };
})();
