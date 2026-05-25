/**
 * 釣果価値チェッカー（複数魚種対応・サイズ別匹数入力・魚アイコンピッカー v6）
 */
'use strict';

const $ = (id) => document.getElementById(id);

let SPECIES_MAP = null;
let PRICE_MASTER = null;
let entries = [];
let entryCounter = 0;
let pickerTargetEntry = null; // モーダルが対象とするエントリ

// ============================================
// ユーティリティ
// ============================================

function fmtYen(n) {
  if (!isFinite(n) || n <= 0) return '0';
  return (Math.round(n / 100) * 100).toLocaleString('ja-JP');
}

function fmtWeight(kg) {
  if (kg >= 10) return kg.toFixed(1) + ' kg';
  if (kg >= 1)  return kg.toFixed(2) + ' kg';
  return Math.round(kg * 1000) + ' g';
}

function fmtKgShort(kg) {
  if (!isFinite(kg) || kg <= 0) return '0';
  if (kg < 10) return (Math.round(kg * 100) / 100).toString().replace(/(\.\d)0$/, '$1');
  return kg.toFixed(1);
}

function kgToCm(curve, kg) {
  if (!curve || curve.length === 0) return null;
  if (kg <= curve[0].kg) return curve[0].cm;
  if (kg >= curve[curve.length - 1].kg) return curve[curve.length - 1].cm;
  for (let i = 0; i < curve.length - 1; i++) {
    if (kg >= curve[i].kg && kg <= curve[i + 1].kg) {
      const ratio = (kg - curve[i].kg) / (curve[i + 1].kg - curve[i].kg);
      return curve[i].cm + (curve[i + 1].cm - curve[i].cm) * ratio;
    }
  }
  return curve[curve.length - 1].cm;
}

function showError(msg) {
  const el = $('err-msg');
  el.textContent = msg;
  el.hidden = false;
  $('result').hidden = true;
  $('caution').hidden = true;
}

function clearError() {
  $('err-msg').hidden = true;
}

function escapeHtml(s) {
  return (s || '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
}

// ============================================
// 魚アイコン
// ============================================

// site_fish_id → asset folder（ハイフン除去だけでは解決しない特殊ケース）
const ICON_FOLDER_MAP = {
  'abura-bouzu': 'aburabozu',
  'mongoika':    'mongouika',
};

function iconFolderOf(sid) {
  if (!sid) return null;
  return ICON_FOLDER_MAP[sid] || sid.replace(/-/g, '');
}

function iconUrlOf(species) {
  const folder = iconFolderOf(species.site_fish_id);
  if (!folder) return null;
  return `../assets/fish/${folder}/${folder}_icon.png`;
}

// ============================================
// 50音グループ
// ============================================

const KANA_GROUPS = [
  { label: 'ア行', chars: 'アイウエオ' },
  { label: 'カ行', chars: 'カキクケコガギグゲゴ' },
  { label: 'サ行', chars: 'サシスセソザジズゼゾ' },
  { label: 'タ行', chars: 'タチツテトダヂヅデド' },
  { label: 'ナ行', chars: 'ナニヌネノ' },
  { label: 'ハ行', chars: 'ハヒフヘホバビブベボパピプペポ' },
  { label: 'マ行', chars: 'マミムメモ' },
  { label: 'ヤ行', chars: 'ヤユヨ' },
  { label: 'ラ行', chars: 'ラリルレロ' },
  { label: 'ワ行', chars: 'ワヲン' },
];
const KANJI_FIRST_MAP = { '沖': 'オキ' };

function readingOf(displayName) {
  if (!displayName) return '';
  const first = displayName.charAt(0);
  if (KANJI_FIRST_MAP[first]) return KANJI_FIRST_MAP[first] + displayName.slice(1);
  return displayName;
}

function kanaGroupOf(displayName) {
  const reading = readingOf(displayName);
  if (!reading) return null;
  const first = reading.charAt(0);
  for (const g of KANA_GROUPS) {
    if (g.chars.indexOf(first) >= 0) return g.label;
  }
  return 'その他';
}

function kanaSortKey(displayName) {
  if (!displayName) return 'zzzz';
  const grp = kanaGroupOf(displayName);
  const grpIdx = KANA_GROUPS.findIndex(g => g.label === grp);
  return (grpIdx < 0 ? 99 : grpIdx).toString().padStart(2, '0') + readingOf(displayName);
}

function findSpecies(fishId) {
  if (!fishId) return null;
  let s = SPECIES_MAP.species.find(x => x.site_fish_id === fishId);
  if (s) return s;
  if (typeof fishId === 'string' && fishId.startsWith('bycatch-')) {
    const pfid = fishId.replace('bycatch-', '');
    return SPECIES_MAP.species.find(x => x.price_fish_id === pfid && x.category === 'bycatch');
  }
  return null;
}

// ============================================
// 魚ピッカーモーダル
// ============================================

function buildFishPickerModal() {
  const content = document.querySelector('#fish-picker-modal .picker-content');
  content.innerHTML = '';

  const targets = SPECIES_MAP.species
    .filter(s => s.category === 'target')
    .slice()
    .sort((a, b) => kanaSortKey(a.site_display_name).localeCompare(kanaSortKey(b.site_display_name)));
  const bycatches = SPECIES_MAP.species
    .filter(s => s.category === 'bycatch')
    .slice()
    .sort((a, b) => kanaSortKey(a.site_display_name).localeCompare(kanaSortKey(b.site_display_name)));

  let currentGroup = null;
  for (const s of targets) {
    const grp = kanaGroupOf(s.site_display_name);
    if (grp !== currentGroup) {
      const label = document.createElement('div');
      label.className = 'picker-group-label';
      label.textContent = grp;
      content.appendChild(label);
      currentGroup = grp;
    }
    content.appendChild(buildFishChipEl(s));
  }

  if (bycatches.length > 0) {
    const label = document.createElement('div');
    label.className = 'picker-group-label';
    label.textContent = '外道';
    content.appendChild(label);
    for (const s of bycatches) {
      content.appendChild(buildFishChipEl(s));
    }
  }
}

function buildFishChipEl(species) {
  const fishId = species.site_fish_id || ('bycatch-' + species.price_fish_id);
  const chip = document.createElement('button');
  chip.type = 'button';
  chip.className = 'fish-chip';
  chip.dataset.fishId = fishId;

  const url = iconUrlOf(species);
  if (url) {
    const img = document.createElement('img');
    img.className = 'fish-chip-icon';
    img.src = url;
    img.alt = '';
    img.width = 36;
    img.height = 36;
    img.loading = 'lazy';
    img.onerror = function() { this.replaceWith(makeFallbackIcon()); };
    chip.appendChild(img);
  } else {
    chip.appendChild(makeFallbackIcon());
  }

  const nameEl = document.createElement('span');
  nameEl.className = 'fish-chip-name';
  nameEl.textContent = species.site_display_name;
  chip.appendChild(nameEl);

  chip.addEventListener('click', () => onPickerSelect(fishId));
  return chip;
}

function makeFallbackIcon() {
  const span = document.createElement('span');
  span.className = 'fish-chip-icon fish-chip-icon-placeholder';
  span.textContent = '🐟';
  return span;
}

function openFishPicker(entry) {
  pickerTargetEntry = entry;
  const modal = $('fish-picker-modal');

  modal.querySelectorAll('.fish-chip').forEach(chip => {
    chip.classList.toggle('selected', chip.dataset.fishId === entry.fishId);
  });

  modal.hidden = false;
  document.body.classList.add('picker-open');

  const selectedChip = modal.querySelector('.fish-chip.selected');
  if (selectedChip) {
    setTimeout(() => selectedChip.scrollIntoView({ block: 'center', behavior: 'instant' }), 50);
  }
}

function closeFishPicker() {
  $('fish-picker-modal').hidden = true;
  document.body.classList.remove('picker-open');
  pickerTargetEntry = null;
}

function onPickerSelect(fishId) {
  if (!pickerTargetEntry) return;
  const entry = pickerTargetEntry;

  $('fish-picker-modal').querySelectorAll('.fish-chip').forEach(chip => {
    chip.classList.toggle('selected', chip.dataset.fishId === fishId);
  });

  closeFishPicker();
  onEntryFishChange(entry, fishId);
}

// ============================================
// 初期化
// ============================================

async function init() {
  try {
    const [smRes, pmRes] = await Promise.all([
      fetch('fish-species-map.json'),
      fetch('fish-price-master.json'),
    ]);
    if (!smRes.ok || !pmRes.ok) throw new Error('JSON ロード失敗');
    SPECIES_MAP = await smRes.json();
    PRICE_MASTER = await pmRes.json();
  } catch (e) {
    showError('データの読み込みに失敗しました。再読み込みしてください。');
    console.error(e);
    return;
  }

  buildFishPickerModal();
  bindGlobalEvents();
  addEntry();
  applyUrlParams();
}

// ============================================
// グローバルイベント
// ============================================

function bindGlobalEvents() {
  $('calc-btn').addEventListener('click', () => onCalculate({ scroll: true }));
  $('reset-btn').addEventListener('click', onReset);
  $('add-entry-btn').addEventListener('click', () => {
    addEntry();
    const last = $('entries').lastElementChild;
    if (last) {
      last.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
  });

  $('picker-close-btn').addEventListener('click', closeFishPicker);

  $('fish-picker-modal').addEventListener('click', (e) => {
    if (e.target === $('fish-picker-modal')) closeFishPicker();
  });

  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && !$('fish-picker-modal').hidden) closeFishPicker();
  });
}

// ============================================
// エントリ管理
// ============================================

function addEntry(preset) {
  entryCounter += 1;
  const id = entryCounter;
  const entry = { id, fishId: preset?.fishId || '', bandCounts: preset?.bandCounts ? { ...preset.bandCounts } : {} };
  entries.push(entry);

  const el = document.createElement('div');
  el.className = 'entry';
  el.dataset.eid = String(id);
  el.innerHTML =
    '<div class="entry-head">' +
      '<span class="entry-num"></span>' +
      '<button type="button" class="entry-fish-btn" aria-label="魚種を選択">' +
        '<span class="efb-icon"></span>' +
        '<span class="efb-name">▼ 魚種を選択</span>' +
        '<svg class="efb-caret" viewBox="0 0 12 12" width="12" height="12" aria-hidden="true">' +
          '<path d="M2 4l4 4 4-4" stroke="currentColor" stroke-width="1.8" fill="none" stroke-linecap="round" stroke-linejoin="round"/>' +
        '</svg>' +
      '</button>' +
      '<button type="button" class="entry-remove" aria-label="削除">' +
        '<svg viewBox="0 0 20 20" width="18" height="18" aria-hidden="true"><path d="M5 5l10 10M15 5L5 15" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"/></svg>' +
      '</button>' +
    '</div>' +
    '<div class="band-list-row" hidden>' +
      '<div class="band-list-head">' +
        '<label>サイズ別 匹数</label>' +
        '<div class="band-total">' +
          '<span class="band-total-val">0</span>' +
          '<span class="band-total-unit">尾</span>' +
        '</div>' +
      '</div>' +
      '<div class="band-list"></div>' +
    '</div>';
  $('entries').appendChild(el);

  el.querySelector('.entry-fish-btn').addEventListener('click', () => openFishPicker(entry));
  el.querySelector('.entry-remove').addEventListener('click', () => removeEntry(entry));

  if (preset?.fishId) {
    onEntryFishChange(entry, preset.fishId);
    if (preset.bandCounts) {
      setTimeout(() => {
        Object.entries(preset.bandCounts).forEach(([idx, cnt]) => {
          const row = el.querySelector('.band-row[data-idx="' + idx + '"]');
          if (row) {
            const inp = row.querySelector('.bs-input');
            inp.value = cnt;
            inp.dispatchEvent(new Event('input'));
          }
        });
      }, 0);
    }
  }

  updateEntryNumbers();
  updateRemoveButtons();
  return entry;
}

function removeEntry(entry) {
  if (entries.length <= 1) return;
  entries = entries.filter(e => e !== entry);
  const el = $('entries').querySelector('.entry[data-eid="' + entry.id + '"]');
  if (el) el.remove();
  updateEntryNumbers();
  updateRemoveButtons();
  scheduleLiveCalc();
}

function updateEntryNumbers() {
  const els = $('entries').querySelectorAll('.entry');
  els.forEach((el, i) => {
    el.querySelector('.entry-num').textContent = String(i + 1);
  });
}

function updateRemoveButtons() {
  const removable = entries.length > 1;
  $('entries').querySelectorAll('.entry-remove').forEach(btn => {
    btn.disabled = !removable;
  });
}

function onEntryFishChange(entry, fishId) {
  clearError();
  entry.fishId = fishId;
  entry.bandCounts = {};

  const el = $('entries').querySelector('.entry[data-eid="' + entry.id + '"]');
  if (!el) return;
  const listRow = el.querySelector('.band-list-row');
  const btn = el.querySelector('.entry-fish-btn');
  const iconEl = btn.querySelector('.efb-icon');
  const nameEl = btn.querySelector('.efb-name');

  // ボタン表示リセット
  iconEl.innerHTML = '';

  if (!fishId) {
    nameEl.textContent = '▼ 魚種を選択';
    el.classList.remove('has-fish');
    listRow.hidden = true;
    scheduleLiveCalc();
    return;
  }

  const species = findSpecies(fishId);
  if (!species) return;

  // アイコン表示
  const url = iconUrlOf(species);
  if (url) {
    const img = document.createElement('img');
    img.src = url;
    img.alt = '';
    img.width = 28;
    img.height = 28;
    img.onerror = function() { this.replaceWith(makeFallbackIcon()); };
    iconEl.appendChild(img);
  } else {
    iconEl.appendChild(makeFallbackIcon());
  }
  nameEl.textContent = species.site_display_name;

  const priceEntry = PRICE_MASTER.prices[species.price_fish_id];
  if (!priceEntry) {
    showError(species.site_display_name + ' の価格データが未登録です');
    return;
  }
  entry._species = species;
  entry._priceEntry = priceEntry;

  buildBandList(el, entry, species, priceEntry);
  listRow.hidden = false;
  el.classList.add('has-fish');
  updateEntryTotal(entry);
  scheduleLiveCalc();
}

// ============================================
// バンドリスト
// ============================================

function buildBandList(el, entry, species, priceEntry) {
  const list = el.querySelector('.band-list');
  list.innerHTML = '';
  const bands = priceEntry.size_bands;
  const isCm = species.input_modes && species.input_modes[0] === 'cm' && priceEntry.size_weight_curve;
  const curve = priceEntry.size_weight_curve;

  bands.forEach((band, idx) => {
    const row = document.createElement('div');
    row.className = 'band-row';
    row.dataset.idx = String(idx);

    const info = document.createElement('div');
    info.className = 'band-info';
    const label = document.createElement('span');
    label.className = 'band-label';
    label.dataset.class = band.size_class || 'standard';
    label.textContent = band.label;
    info.appendChild(label);

    const range = document.createElement('span');
    range.className = 'band-range';
    range.textContent = bandRangeStr(bands, idx, isCm, curve);
    info.appendChild(range);

    const stepper = buildBandStepper(entry, idx);
    row.appendChild(info);
    row.appendChild(stepper);
    list.appendChild(row);
  });
}

function bandRangeStr(bands, idx, isCm, curve) {
  const band = bands[idx];
  const prevKg = idx === 0 ? 0 : (bands[idx - 1].kg_max || 0);
  const hiKg = band.kg_max;
  if (isCm && curve) {
    const lo = prevKg > 0 ? Math.round(kgToCm(curve, prevKg)) : Math.round(curve[0].cm);
    if (hiKg == null) return lo + 'cm+';
    return lo + '〜' + Math.round(kgToCm(curve, hiKg)) + 'cm';
  }
  const lo = prevKg > 0 ? fmtKgShort(prevKg) : '0';
  if (hiKg == null) return lo + 'kg+';
  return lo + '〜' + fmtKgShort(hiKg) + 'kg';
}

function buildBandStepper(entry, idx) {
  const wrap = document.createElement('div');
  wrap.className = 'band-stepper';
  wrap.innerHTML =
    '<button type="button" class="bs-btn" data-act="dec" aria-label="−1">' +
      '<svg viewBox="0 0 20 20" width="18" height="18"><path d="M4 10h12" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"/></svg>' +
    '</button>' +
    '<input type="number" class="bs-input" inputmode="numeric" min="0" max="999" value="0" aria-label="匹数">' +
    '<button type="button" class="bs-btn" data-act="inc" aria-label="+1">' +
      '<svg viewBox="0 0 20 20" width="18" height="18"><path d="M10 4v12M4 10h12" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"/></svg>' +
    '</button>';
  const input = wrap.querySelector('.bs-input');

  function setVal(v) {
    if (!Number.isFinite(v)) v = 0;
    v = Math.max(0, Math.min(999, Math.round(v)));
    input.value = v;
    input.setAttribute('value', String(v));
    wrap.closest('.band-row').classList.toggle('has-value', v > 0);
    if (v > 0) entry.bandCounts[idx] = v;
    else delete entry.bandCounts[idx];
    updateEntryTotal(entry);
    scheduleLiveCalc();
  }

  attachHoldRepeat(wrap.querySelector('[data-act="dec"]'), () => setVal((+input.value || 0) - 1));
  attachHoldRepeat(wrap.querySelector('[data-act="inc"]'), () => setVal((+input.value || 0) + 1));

  input.addEventListener('input', () => {
    let v = parseInt(input.value, 10);
    if (!Number.isFinite(v) || v < 0) v = 0;
    if (v > 999) v = 999;
    setVal(v);
  });
  input.addEventListener('focus', () => input.select());
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') { e.preventDefault(); input.blur(); onCalculate({ scroll: true }); }
  });
  return wrap;
}

function attachHoldRepeat(btn, fn) {
  let timer = null;
  let interval = 180;
  let acc = 0;
  const stop = () => {
    if (timer) { clearTimeout(timer); timer = null; }
    btn.classList.remove('pressing');
    acc = 0;
  };
  const tick = () => {
    fn();
    acc++;
    if (acc > 6 && interval > 55) interval -= 18;
    timer = setTimeout(tick, interval);
  };
  btn.addEventListener('pointerdown', (e) => {
    if (e.button !== undefined && e.button !== 0) return;
    e.preventDefault();
    try { btn.setPointerCapture(e.pointerId); } catch (_) {}
    btn.classList.add('pressing');
    interval = 180;
    acc = 0;
    fn();
    timer = setTimeout(tick, 420);
  });
  ['pointerup', 'pointerleave', 'pointercancel', 'blur'].forEach(ev => btn.addEventListener(ev, stop));
}

function updateEntryTotal(entry) {
  const total = Object.values(entry.bandCounts).reduce((a, b) => a + b, 0);
  const el = $('entries').querySelector('.entry[data-eid="' + entry.id + '"]');
  if (!el) return;
  const valEl = el.querySelector('.band-total-val');
  if (valEl) valEl.textContent = String(total);
  el.querySelector('.band-list-row').classList.toggle('has-value', total > 0);
}

// ============================================
// ライブ再計算
// ============================================

let liveCalcTimer = null;
function scheduleLiveCalc() {
  if (liveCalcTimer) clearTimeout(liveCalcTimer);
  liveCalcTimer = setTimeout(() => onCalculate({ silent: true }), 120);
}

// ============================================
// 計算
// ============================================

function bandRepKg(bands, idx) {
  const band = bands[idx];
  const prevKg = idx === 0 ? 0 : (bands[idx - 1].kg_max || 0);
  if (band.kg_max == null) return prevKg > 0 ? prevKg * 1.5 : 1.0;
  return (prevKg + band.kg_max) / 2;
}

function onCalculate(opts) {
  const silent = opts && opts.silent;
  if (!silent) clearError();

  const validEntries = entries.filter(e => e.fishId && e._priceEntry && Object.values(e.bandCounts).some(v => v > 0));
  if (validEntries.length === 0) {
    if (!silent) showError('魚種と匹数を入力してください');
    else hideResult();
    return;
  }

  let totalCount = 0;
  let totalKg = 0;
  let wholesaleLowSum = 0;
  let wholesaleHighSum = 0;
  let wholesaleMidSum = 0;
  let retailLowSum = 0;
  let retailHighSum = 0;
  let retailMidSum = 0;
  const perEntry = [];

  for (const e of validEntries) {
    const species = e._species;
    const priceEntry = e._priceEntry;
    const bands = priceEntry.size_bands;

    let eCount = 0;
    let eKg = 0;
    let eRetailMid = 0;
    let eWholesaleMid = 0;
    const eBreakdown = [];

    for (const [idxStr, count] of Object.entries(e.bandCounts)) {
      if (count <= 0) continue;
      const idx = parseInt(idxStr, 10);
      const band = bands[idx];
      const repKg = bandRepKg(bands, idx);
      const bandKg = repKg * count;
      eCount += count;
      eKg += bandKg;

      wholesaleLowSum  += bandKg * band.wholesale_low;
      wholesaleHighSum += bandKg * band.wholesale_high;
      const wMid = bandKg * (band.wholesale_low + band.wholesale_high) / 2;
      wholesaleMidSum  += wMid;
      eWholesaleMid    += wMid;
      retailLowSum     += bandKg * band.retail_low;
      retailHighSum    += bandKg * band.retail_high;
      const rMid = bandKg * (band.retail_low + band.retail_high) / 2;
      retailMidSum     += rMid;
      eRetailMid       += rMid;

      eBreakdown.push({ label: band.label, count, perKg: repKg, bandKg });
    }

    totalCount += eCount;
    totalKg += eKg;

    perEntry.push({
      name: species.site_display_name,
      count: eCount,
      kg: eKg,
      retailMid: eRetailMid,
      wholesaleMid: eWholesaleMid,
      breakdown: eBreakdown,
    });
  }

  renderResult({
    totalCount, totalKg,
    speciesCount: validEntries.length,
    wholesaleLow: wholesaleLowSum, wholesaleHigh: wholesaleHighSum, wholesaleMid: wholesaleMidSum,
    retailLow: retailLowSum, retailHigh: retailHighSum, retailMid: retailMidSum,
    perEntry,
  }, opts);
}

function hideResult() {
  $('result').hidden = true;
  $('caution').hidden = true;
}

function renderResult(r, opts) {
  $('result-species').textContent = r.speciesCount;
  $('result-count').textContent   = r.totalCount;
  $('result-weight').textContent  = fmtKgShort(r.totalKg);

  const pills = $('result-pills');
  pills.innerHTML = '';
  for (const e of r.perEntry) {
    const pill = document.createElement('span');
    pill.className = 'result-pill';
    pill.innerHTML =
      '<span class="rp-name">' + escapeHtml(e.name) + '</span>' +
      '<span class="rp-count">' + e.count + '尾</span>';
    pills.appendChild(pill);
  }

  $('retail-main').textContent  = fmtYen(r.retailMid);
  $('retail-range').textContent = 'レンジ ' + fmtYen(r.retailLow) + '〜' + fmtYen(r.retailHigh) + ' 円';
  $('wholesale-main').textContent  = fmtYen(r.wholesaleMid);
  $('wholesale-range').textContent = 'レンジ ' + fmtYen(r.wholesaleLow) + '〜' + fmtYen(r.wholesaleHigh) + ' 円';

  const basis = $('basis-list');
  basis.innerHTML = '';
  for (const e of r.perEntry) {
    const heading = document.createElement('li');
    heading.className = 'basis-head';
    heading.textContent = '【' + e.name + '】合計 ' + e.count + '尾・' + fmtWeight(e.kg) +
      ' / 推定 小売 ' + fmtYen(e.retailMid) + '円 (卸売 ' + fmtYen(e.wholesaleMid) + '円)';
    basis.appendChild(heading);
    for (const b of e.breakdown) {
      const li = document.createElement('li');
      li.textContent = '　' + b.label + ': ' + b.count + '尾 × 推定 ' + fmtWeight(b.perKg) + ' = ' + fmtWeight(b.bandKg);
      basis.appendChild(li);
    }
  }

  $('result').hidden = false;
  $('caution').hidden = false;

  if (opts && opts.scroll) {
    requestAnimationFrame(() => {
      const top = $('result').getBoundingClientRect().top + window.scrollY - 8;
      window.scrollTo({ top, behavior: 'smooth' });
    });
  }
}

// ============================================
// リセット
// ============================================

function onReset() {
  clearError();
  $('entries').innerHTML = '';
  entries = [];
  addEntry();
  hideResult();
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

// ============================================
// URL パラメータ
// ============================================

function applyUrlParams() {
  const p = new URLSearchParams(location.search);
  const entriesStr = p.get('entries');
  if (entriesStr) {
    $('entries').innerHTML = '';
    entries = [];
    entriesStr.split(';').forEach(part => {
      const [fishId, bandsStr] = part.split('|');
      if (!fishId) return;
      const bandCounts = {};
      (bandsStr || '').split(',').forEach(bp => {
        const [i, c] = bp.split(':').map(s => parseInt(s, 10));
        if (Number.isFinite(i) && Number.isFinite(c) && c > 0) bandCounts[i] = c;
      });
      addEntry({ fishId, bandCounts });
    });
    onCalculate({ scroll: true });
    return;
  }
  const fish = p.get('fish');
  const bandsParam = p.get('bands');
  if (fish) {
    const entry = entries[0];
    const el = $('entries').querySelector('.entry');
    onEntryFishChange(entry, fish);
    if (bandsParam) {
      bandsParam.split(',').forEach(part => {
        const [i, c] = part.split(':').map(s => parseInt(s, 10));
        if (Number.isFinite(i) && Number.isFinite(c) && c > 0) {
          const row = el.querySelector('.band-row[data-idx="' + i + '"]');
          if (row) {
            const inp = row.querySelector('.bs-input');
            inp.value = c;
            inp.dispatchEvent(new Event('input'));
          }
        }
      });
      onCalculate({ scroll: true });
    }
  }
}

// ============================================
// 起動
// ============================================

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', init);
} else {
  init();
}
