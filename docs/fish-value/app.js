/**
 * 釣果価値チェッカー
 * fish-species-map.json + fish-price-master.json を元に
 * 卸売・小売換算レンジを表示する。
 */
'use strict';

const $ = (id) => document.getElementById(id);

let SPECIES_MAP = null;
let PRICE_MASTER = null;
let currentInputMode = null;

function fmtYen(n) {
  if (!isFinite(n) || n <= 0) return '0';
  const rounded = Math.round(n / 100) * 100;
  return rounded.toLocaleString('ja-JP');
}

function fmtWeight(kg) {
  if (kg >= 10) return kg.toFixed(1) + ' kg';
  if (kg >= 1) return kg.toFixed(2) + ' kg';
  return Math.round(kg * 1000) + ' g';
}

function cmToKg(curve, cm) {
  if (!curve || curve.length === 0) return null;
  if (cm <= curve[0].cm) return curve[0].kg;
  if (cm >= curve[curve.length - 1].cm) return curve[curve.length - 1].kg;
  for (let i = 0; i < curve.length - 1; i++) {
    if (cm >= curve[i].cm && cm <= curve[i + 1].cm) {
      const ratio = (cm - curve[i].cm) / (curve[i + 1].cm - curve[i].cm);
      return curve[i].kg + (curve[i + 1].kg - curve[i].kg) * ratio;
    }
  }
  return curve[curve.length - 1].kg;
}

function findBand(bands, kg) {
  for (const band of bands) {
    if (band.kg_max === null || band.kg_max === undefined) return band;
    if (kg <= band.kg_max) return band;
  }
  return bands[bands.length - 1];
}

function setInvalid(field) {
  ['fish', 'count', 'size', 'weight'].forEach(id => $(id).removeAttribute('aria-invalid'));
  if (field) {
    field.setAttribute('aria-invalid', 'true');
    field.focus();
  }
}

function showError(msg, field) {
  const err = $('err-msg');
  err.textContent = msg;
  err.hidden = false;
  $('result').hidden = true;
  setInvalid(field);
}

function clearError() {
  $('err-msg').hidden = true;
  $('err-msg').textContent = '';
  setInvalid(null);
}

async function init() {
  try {
    const [smRes, pmRes] = await Promise.all([
      fetch('fish-species-map.json'),
      fetch('fish-price-master.json')
    ]);
    if (!smRes.ok || !pmRes.ok) throw new Error('JSONロード失敗');
    SPECIES_MAP = await smRes.json();
    PRICE_MASTER = await pmRes.json();
  } catch (e) {
    showError('データの読み込みに失敗しました。再読み込みしてください。');
    console.error(e);
    $('calc-btn').textContent = 'データ読込エラー';
    $('calc-btn').disabled = true;
    return;
  }

  populateFishSelect();
  bindEvents();
  applyUrlParams();
  if (!currentInputMode) onFishChange();
  $('calc-btn').textContent = '計算する';
  $('calc-btn').disabled = false;
}

function populateFishSelect() {
  const select = $('fish');
  const frag = document.createDocumentFragment();

  for (const species of SPECIES_MAP.species) {
    const opt = document.createElement('option');
    opt.value = species.site_fish_id || ('bycatch-' + species.price_fish_id);
    opt.textContent = species.site_display_name;
    if (!species.site_fish_id) opt.dataset.pfid = species.price_fish_id;
    frag.appendChild(opt);
  }

  select.appendChild(frag);
}

function bindEvents() {
  $('fish').addEventListener('change', onFishChange);
  $('calc-btn').addEventListener('click', onCalculate);

  ['count', 'size', 'weight'].forEach(id => {
    $(id).addEventListener('input', clearError);
    $(id).addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        e.preventDefault();
        onCalculate();
      }
    });
  });
}

function onFishChange() {
  clearError();
  const fishId = $('fish').value;
  if (!fishId) {
    $('size-row').hidden = false;
    $('weight-row').hidden = true;
    currentInputMode = 'cm';
    return;
  }

  const species = findSpecies(fishId);
  if (!species) return;
  const modes = species.input_modes || ['cm'];
  currentInputMode = modes.includes('kg') ? 'kg' : 'cm';

  if (currentInputMode === 'cm') {
    $('size-row').hidden = false;
    $('weight-row').hidden = true;
    $('weight').value = '';
  } else {
    $('size-row').hidden = true;
    $('weight-row').hidden = false;
    $('size').value = '';
  }
}

function findSpecies(fishId) {
  let species = SPECIES_MAP.species.find(s => s.site_fish_id === fishId);
  if (species) return species;

  if (fishId.startsWith('bycatch-')) {
    const pfid = fishId.replace('bycatch-', '');
    return SPECIES_MAP.species.find(s => s.price_fish_id === pfid && s.category === 'bycatch');
  }
  return null;
}

function onCalculate() {
  clearError();

  const fishId = $('fish').value;
  if (!fishId) {
    showError('魚種を選択してください。', $('fish'));
    return;
  }

  const species = findSpecies(fishId);
  if (!species) {
    showError('魚種データが見つかりません。', $('fish'));
    return;
  }

  const countText = $('count').value.trim();
  const count = Number(countText);
  if (!/^\d+$/.test(countText) || !Number.isInteger(count) || count < 1 || count > 999) {
    showError('匹数は1〜999の整数で入力してください。', $('count'));
    return;
  }

  const priceEntry = PRICE_MASTER.prices[species.price_fish_id];
  if (!priceEntry) {
    showError(species.site_display_name + ' の価格データが未登録です。', $('fish'));
    return;
  }

  let perFishKg;
  let inputDetail;

  if (currentInputMode === 'cm') {
    const cm = Number($('size').value);
    if (!Number.isFinite(cm) || cm < 1 || cm > 200) {
      showError('平均サイズは1〜200cmの数値で入力してください。', $('size'));
      return;
    }
    perFishKg = cmToKg(priceEntry.size_weight_curve, cm);
    if (!perFishKg) {
      showError(species.site_display_name + ' はサイズ→重量換算データが未登録です。', $('size'));
      return;
    }
    inputDetail = '平均サイズ ' + cm + ' cm → 推定重量 ' + fmtWeight(perFishKg) + ' / 尾';
  } else {
    const kg = Number($('weight').value);
    if (!Number.isFinite(kg) || kg < 0.05 || kg > 100) {
      showError('平均重量は0.05〜100kgの数値で入力してください。', $('weight'));
      return;
    }
    perFishKg = kg;
    inputDetail = '平均重量 ' + fmtWeight(perFishKg) + ' / 尾';
  }

  const band = findBand(priceEntry.size_bands, perFishKg);
  const totalKg = perFishKg * count;
  const wholesaleLow = totalKg * band.wholesale_low;
  const wholesaleHigh = totalKg * band.wholesale_high;
  const retailLow = totalKg * band.retail_low;
  const retailHigh = totalKg * band.retail_high;

  renderResult({
    species,
    priceEntry,
    band,
    count,
    perFishKg,
    totalKg,
    wholesaleLow,
    wholesaleHigh,
    retailLow,
    retailHigh,
    inputDetail
  });
}

function renderResult(r) {
  const badge = $('size-badge');
  badge.textContent = r.band.label;
  badge.dataset.class = r.band.size_class || 'standard';

  $('total-weight').textContent = '推定総重量 ' + fmtWeight(r.totalKg);
  $('retail-range').textContent = '約 ' + fmtYen(r.retailLow) + ' 〜 ' + fmtYen(r.retailHigh) + ' 円';
  $('retail-per').textContent = '1匹あたり 約 ' + fmtYen(r.retailLow / r.count) + ' 〜 ' + fmtYen(r.retailHigh / r.count) + ' 円';
  $('wholesale-range').textContent = '約 ' + fmtYen(r.wholesaleLow) + ' 〜 ' + fmtYen(r.wholesaleHigh) + ' 円';
  $('wholesale-per').textContent = '1匹あたり 約 ' + fmtYen(r.wholesaleLow / r.count) + ' 〜 ' + fmtYen(r.wholesaleHigh / r.count) + ' 円';

  renderBasis(r);
  $('result').hidden = false;
}

function renderBasis(r) {
  const basis = $('basis-list');
  basis.textContent = '';
  const items = [
    r.inputDetail,
    'サイズ帯: ' + r.band.label + '（' + bandRangeLabel(r.priceEntry.size_bands, r.band) + '・' + r.band.size_class + '）',
    '卸売単価: ' + r.band.wholesale_low.toLocaleString('ja-JP') + ' 〜 ' + r.band.wholesale_high.toLocaleString('ja-JP') + ' 円/kg',
    '小売単価: ' + r.band.retail_low.toLocaleString('ja-JP') + ' 〜 ' + r.band.retail_high.toLocaleString('ja-JP') + ' 円/kg',
    '倍率カテゴリ: ' + (r.priceEntry.category_tag || '未設定'),
    '出典: ' + (r.priceEntry.wholesale_source || '価格マスタ')
  ];

  for (const item of items) {
    const li = document.createElement('li');
    li.textContent = item;
    basis.appendChild(li);
  }
}

function bandRangeLabel(bands, target) {
  const idx = bands.indexOf(target);
  const lo = idx === 0 ? 0 : (bands[idx - 1].kg_max ?? 0);
  const hi = target.kg_max;
  const loStr = lo > 0 ? fmtWeight(lo) : '0';
  const hiStr = hi == null ? '上限なし' : fmtWeight(hi);
  return loStr + ' 〜 ' + hiStr;
}

function applyUrlParams() {
  const params = new URLSearchParams(location.search);
  const fish = params.get('fish');
  const count = params.get('count');
  const size = params.get('size');
  const weight = params.get('weight');

  if (fish && Array.from($('fish').options).some(opt => opt.value === fish)) {
    $('fish').value = fish;
    onFishChange();
  }
  if (count && Number(count) > 0) $('count').value = count;
  if (size && !$('size-row').hidden && Number(size) > 0) $('size').value = size;
  if (weight && !$('weight-row').hidden && Number(weight) > 0) $('weight').value = weight;

  if ($('fish').value && $('count').value && (($('size').value && !$('size-row').hidden) || ($('weight').value && !$('weight-row').hidden))) {
    onCalculate();
  }
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', init);
} else {
  init();
}
