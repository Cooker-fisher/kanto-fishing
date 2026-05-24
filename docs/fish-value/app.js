let SPECIES_MAP = null;
let PRICE_MASTER = null;

const el = {};

window.addEventListener('DOMContentLoaded', () => {
  bindElements();
  bindEvents();
  loadData();
});

function bindElements() {
  el.fish = document.getElementById('fish');
  el.count = document.getElementById('count');
  el.size = document.getElementById('size');
  el.weight = document.getElementById('weight');
  el.sizeRow = document.getElementById('size-row');
  el.weightRow = document.getElementById('weight-row');
  el.calcBtn = document.getElementById('calc-btn');
  el.err = document.getElementById('err-msg');
  el.result = document.getElementById('result');
  el.badge = document.getElementById('size-badge');
  el.totalWeight = document.getElementById('total-weight');
  el.retailRange = document.getElementById('retail-range');
  el.retailPer = document.getElementById('retail-per');
  el.wholesaleRange = document.getElementById('wholesale-range');
  el.wholesalePer = document.getElementById('wholesale-per');
  el.basis = document.getElementById('basis');
  el.basisList = document.getElementById('basis-list');
}

function bindEvents() {
  el.fish.addEventListener('change', () => {
    clearError();
    updateInputMode();
  });
  el.calcBtn.addEventListener('click', calculate);
  [el.count, el.size, el.weight].forEach(input => {
    input.addEventListener('input', clearError);
    input.addEventListener('keydown', event => {
      if (event.key === 'Enter') calculate();
    });
  });
}

async function loadData() {
  try {
    const [speciesRes, priceRes] = await Promise.all([
      fetch('./fish-species-map.json'),
      fetch('./fish-price-master.json')
    ]);
    if (!speciesRes.ok || !priceRes.ok) throw new Error('data fetch failed');

    SPECIES_MAP = await speciesRes.json();
    PRICE_MASTER = await priceRes.json();

    populateFishSelect();
    applyUrlParams();
    updateInputMode();
    el.calcBtn.disabled = false;
    el.calcBtn.textContent = '計算する';

    if (hasCompleteParams()) calculate();
  } catch (error) {
    el.calcBtn.disabled = true;
    el.calcBtn.textContent = 'データ読込エラー';
    showError('価格データを読み込めませんでした。時間をおいて再度お試しください。');
  }
}

function populateFishSelect() {
  const frag = document.createDocumentFragment();
  SPECIES_MAP.species.forEach(species => {
    const option = document.createElement('option');
    option.value = species.site_fish_id;
    option.textContent = species.site_display_name;
    frag.appendChild(option);
  });
  el.fish.appendChild(frag);
}

function applyUrlParams() {
  const params = new URLSearchParams(location.search);
  setIfValidOption(params.get('fish'));
  setIfNumber(el.count, params.get('count'));
  setIfNumber(el.size, params.get('size'));
  setIfNumber(el.weight, params.get('weight'));
}

function setIfValidOption(value) {
  if (!value) return;
  const exists = Array.from(el.fish.options).some(option => option.value === value);
  if (exists) el.fish.value = value;
}

function setIfNumber(input, value) {
  if (value === null || value === '') return;
  const n = Number(value);
  if (Number.isFinite(n) && n > 0) input.value = value;
}

function hasCompleteParams() {
  const species = getSelectedSpecies();
  if (!species || !validInt(el.count.value, 1, 999)) return false;
  const mode = getInputMode(species);
  if (mode === 'cm') return validNumber(el.size.value, 1, 200);
  return validNumber(el.weight.value, 0.05, 100);
}

function updateInputMode() {
  const species = getSelectedSpecies();
  const mode = species ? getInputMode(species) : 'cm';
  el.sizeRow.hidden = mode !== 'cm';
  el.weightRow.hidden = mode !== 'kg';
}

function calculate() {
  clearError();

  const input = readInput();
  if (!input.ok) {
    showError(input.message, input.field);
    return;
  }

  const species = input.species;
  const priceEntry = PRICE_MASTER.prices[species.price_fish_id];
  if (!priceEntry) {
    showError('この魚種の価格データが見つかりません。', el.fish);
    return;
  }

  const mode = getInputMode(species);
  let perFishKg;
  if (mode === 'cm') {
    if (!Array.isArray(priceEntry.size_weight_curve)) {
      showError('この魚種のサイズ換算データが見つかりません。', el.size);
      return;
    }
    perFishKg = cmToKg(priceEntry.size_weight_curve, input.sizeCm);
  } else {
    perFishKg = input.weightKg;
  }

  const band = findBand(priceEntry.size_bands, perFishKg);
  const totalKg = perFishKg * input.count;
  const wholesaleLow = totalKg * band.wholesale_low;
  const wholesaleHigh = totalKg * band.wholesale_high;
  const retailLow = totalKg * band.retail_low;
  const retailHigh = totalKg * band.retail_high;

  renderResult({
    species,
    priceEntry,
    mode,
    count: input.count,
    sizeCm: input.sizeCm,
    perFishKg,
    totalKg,
    band,
    wholesaleLow,
    wholesaleHigh,
    retailLow,
    retailHigh
  });
}

function readInput() {
  const species = getSelectedSpecies();
  if (!species) return { ok: false, message: '魚種を選択してください。', field: el.fish };

  const count = parseInt(el.count.value, 10);
  if (!validInt(el.count.value, 1, 999)) {
    return { ok: false, message: '匹数は1〜999の整数で入力してください。', field: el.count };
  }

  const mode = getInputMode(species);
  if (mode === 'cm') {
    const sizeCm = parseFloat(el.size.value);
    if (!validNumber(el.size.value, 1, 200)) {
      return { ok: false, message: '平均サイズは1〜200cmで入力してください。', field: el.size };
    }
    return { ok: true, species, count, sizeCm };
  }

  const weightKg = parseFloat(el.weight.value);
  if (!validNumber(el.weight.value, 0.05, 100)) {
    return { ok: false, message: '平均重量は0.05〜100kgで入力してください。', field: el.weight };
  }
  return { ok: true, species, count, weightKg };
}

function getSelectedSpecies() {
  if (!SPECIES_MAP) return null;
  return SPECIES_MAP.species.find(s => s.site_fish_id === el.fish.value) || null;
}

function getInputMode(species) {
  return Array.isArray(species.input_modes) && species.input_modes.includes('kg') ? 'kg' : 'cm';
}

function validInt(value, min, max) {
  if (!/^\d+$/.test(String(value).trim())) return false;
  const n = Number(value);
  return Number.isInteger(n) && n >= min && n <= max;
}

function validNumber(value, min, max) {
  if (String(value).trim() === '') return false;
  const n = Number(value);
  return Number.isFinite(n) && n >= min && n <= max;
}

function cmToKg(curve, cm) {
  if (cm <= curve[0].cm) return curve[0].kg;
  if (cm >= curve[curve.length - 1].cm) return curve[curve.length - 1].kg;
  for (let i = 0; i < curve.length - 1; i++) {
    const left = curve[i];
    const right = curve[i + 1];
    if (cm >= left.cm && cm <= right.cm) {
      const ratio = (cm - left.cm) / (right.cm - left.cm);
      return left.kg + (right.kg - left.kg) * ratio;
    }
  }
  return curve[curve.length - 1].kg;
}

function findBand(bands, kg) {
  for (const band of bands) {
    if (band.kg_max === null || kg <= band.kg_max) return band;
  }
  return bands[bands.length - 1];
}

function fmtYen(n) {
  const rounded = Math.round(n / 100) * 100;
  return rounded.toLocaleString('ja-JP');
}

function fmtKg(n) {
  const rounded = Math.round(n * 100) / 100;
  return Number.isInteger(rounded) ? String(rounded) : rounded.toFixed(2).replace(/0$/, '');
}

function priceRange(low, high) {
  return `約 ${fmtYen(low)} 〜 ${fmtYen(high)} 円`;
}

function renderResult(data) {
  el.badge.textContent = data.band.label;
  el.badge.dataset.class = data.band.size_class || 'standard';
  el.totalWeight.textContent = `推定総重量 ${fmtKg(data.totalKg)} kg`;

  el.retailRange.textContent = priceRange(data.retailLow, data.retailHigh);
  el.retailPer.textContent = `1匹あたり ${priceRange(data.retailLow / data.count, data.retailHigh / data.count)}`;
  el.wholesaleRange.textContent = priceRange(data.wholesaleLow, data.wholesaleHigh);
  el.wholesalePer.textContent = `1匹あたり ${priceRange(data.wholesaleLow / data.count, data.wholesaleHigh / data.count)}`;

  renderBasis(data);
  el.result.hidden = false;
  el.basis.hidden = false;
}

function renderBasis(data) {
  const inputText = data.mode === 'cm'
    ? `入力: 平均サイズ ${data.sizeCm}cm → 推定重量 ${fmtKg(data.perFishKg)} kg/尾`
    : `入力: 平均重量 ${fmtKg(data.perFishKg)} kg/尾`;
  const kgMax = data.band.kg_max === null ? '上限なし' : `${data.band.kg_max} kg`;
  const multiplier = `${data.priceEntry.category_tag || '分類未設定'}カテゴリ × ${data.band.size_class || 'standard'}サイズ`;
  const source = data.priceEntry.wholesale_source || '価格マスタ';

  const items = [
    inputText,
    `サイズ帯: ${data.band.label} (kg_max: ${kgMax})`,
    `卸売単価: ${data.band.wholesale_low.toLocaleString('ja-JP')} 〜 ${data.band.wholesale_high.toLocaleString('ja-JP')} 円/kg（出典: ${source}）`,
    `倍率: ${multiplier} → 丸ごと小売換算 ${data.band.retail_low.toLocaleString('ja-JP')} 〜 ${data.band.retail_high.toLocaleString('ja-JP')} 円/kg`
  ];

  el.basisList.textContent = '';
  items.forEach(text => {
    const li = document.createElement('li');
    li.textContent = text;
    el.basisList.appendChild(li);
  });
}

function showError(message, field) {
  el.err.textContent = message;
  el.err.hidden = false;
  [el.fish, el.count, el.size, el.weight].forEach(input => {
    input.removeAttribute('aria-invalid');
  });
  if (field) {
    field.setAttribute('aria-invalid', 'true');
    field.focus();
  }
}

function clearError() {
  el.err.hidden = true;
  el.err.textContent = '';
  [el.fish, el.count, el.size, el.weight].forEach(input => {
    input.removeAttribute('aria-invalid');
  });
}
