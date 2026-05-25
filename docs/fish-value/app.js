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

// ===== ユーティリティ =====

function fmtYen(n) {
  if (!isFinite(n) || n <= 0) return '0';
  const rounded = Math.round(n / 100) * 100;
  return rounded.toLocaleString('ja-JP');
}

function fmtWeight(kg) {
  if (kg >= 10) return kg.toFixed(1) + ' kg';
  if (kg >= 1)  return kg.toFixed(2) + ' kg';
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

// ===== 初期化 =====

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

  populateFishSelect();
  bindEvents();
  applyUrlParams();
}

// カタカナの頭文字 → 50音グループ
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

// 漢字始まりの site_display_name の読み（カタカナ複数文字に変換するためのマップ）
const KANJI_FIRST_MAP = {
  '沖': 'オキ',  // 沖カサゴ・沖メバル
};

function readingOf(displayName) {
  if (!displayName) return '';
  const first = displayName.charAt(0);
  if (KANJI_FIRST_MAP[first]) {
    return KANJI_FIRST_MAP[first] + displayName.slice(1);
  }
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
  // 並び順は KANA_GROUPS の順 → 同行内は読みのカタカナ標準順
  if (!displayName) return 'zzzz';
  const grp = kanaGroupOf(displayName);
  const grpIdx = KANA_GROUPS.findIndex(g => g.label === grp);
  return (grpIdx < 0 ? 99 : grpIdx).toString().padStart(2, '0') + readingOf(displayName);
}

function populateFishSelect() {
  const select = $('fish');
  // target → 50音順ソート、bycatch は最後にまとめる
  const targets = SPECIES_MAP.species
    .filter(s => s.category === 'target')
    .slice()
    .sort((a, b) => kanaSortKey(a.site_display_name).localeCompare(kanaSortKey(b.site_display_name)));
  const bycatches = SPECIES_MAP.species
    .filter(s => s.category === 'bycatch')
    .slice()
    .sort((a, b) => kanaSortKey(a.site_display_name).localeCompare(kanaSortKey(b.site_display_name)));

  // target を 50音グループ別に展開
  let currentGroup = null;
  for (const s of targets) {
    const grp = kanaGroupOf(s.site_display_name);
    if (grp !== currentGroup) {
      const sep = document.createElement('option');
      sep.disabled = true;
      sep.textContent = '── ' + grp + ' ──';
      select.appendChild(sep);
      currentGroup = grp;
    }
    const opt = document.createElement('option');
    opt.value = s.site_fish_id;
    opt.textContent = s.site_display_name;
    select.appendChild(opt);
  }

  // bycatch
  if (bycatches.length > 0) {
    const sep = document.createElement('option');
    sep.disabled = true;
    sep.textContent = '── 外道 ──';
    select.appendChild(sep);
    for (const s of bycatches) {
      const opt = document.createElement('option');
      opt.value = s.site_fish_id || ('bycatch-' + s.price_fish_id);
      opt.dataset.pfid = s.price_fish_id;
      opt.textContent = s.site_display_name;
      select.appendChild(opt);
    }
  }
}

function bindEvents() {
  $('fish').addEventListener('change', onFishChange);
  $('calc-btn').addEventListener('click', onCalculate);

  // mode 切替ラジオ
  document.querySelectorAll('input[name="input-mode"]').forEach(r => {
    r.addEventListener('change', onModeChange);
  });

  // Enter キーで計算
  ['count', 'size', 'weight'].forEach(id => {
    $(id).addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        e.preventDefault();
        onCalculate();
      }
    });
  });
}

const MODE_LABEL_BASE = { cm: 'サイズ (cm)', kg: '重量 (kg)' };

function updateModeLabels(recMode) {
  for (const m of ['cm', 'kg']) {
    const span = document.querySelector(`label[for="mode-${m}"] span, #mode-${m} ~ span`)
              || document.getElementById(`mode-${m}`).closest('label').querySelector('span');
    if (!span) continue;
    span.textContent = MODE_LABEL_BASE[m] + (recMode === m ? '(推奨)' : '');
  }
}

function onFishChange() {
  clearError();
  const fishId = $('fish').value;
  if (!fishId) {
    $('size-row').hidden = true;
    $('weight-row').hidden = true;
    $('mode-switch').hidden = true;
    currentInputMode = null;
    return;
  }
  const species = findSpecies(fishId);
  if (!species) return;
  const modes = species.input_modes || ['cm'];
  // 両方サポート時のみラジオ表示。主入力(modes[0])をデフォルトに
  if (modes.length >= 2) {
    $('mode-switch').hidden = false;
    const defaultMode = species.recommended_mode || modes[0];
    document.querySelector(`input[name="input-mode"][value="${defaultMode}"]`).checked = true;
    updateModeLabels(species.recommended_mode);
    applyInputMode(defaultMode);
  } else {
    $('mode-switch').hidden = true;
    applyInputMode(modes[0]);
  }
}

function onModeChange() {
  clearError();
  const mode = document.querySelector('input[name="input-mode"]:checked').value;
  applyInputMode(mode);
}

function applyInputMode(mode) {
  currentInputMode = mode;
  if (mode === 'cm') {
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
  // site_fish_id 一致
  let s = SPECIES_MAP.species.find(x => x.site_fish_id === fishId);
  if (s) return s;
  // bycatch（site_fish_id=null）の場合は bycatch-{pfid} 形式
  if (fishId.startsWith('bycatch-')) {
    const pfid = fishId.replace('bycatch-', '');
    return SPECIES_MAP.species.find(x => x.price_fish_id === pfid && x.category === 'bycatch');
  }
  return null;
}

// ===== 計算 =====

function onCalculate() {
  clearError();

  const fishId = $('fish').value;
  if (!fishId) {
    showError('魚種を選択してください');
    return;
  }

  const species = findSpecies(fishId);
  if (!species) {
    showError('魚種データが見つかりません');
    return;
  }

  const count = parseInt($('count').value, 10);
  if (!Number.isFinite(count) || count < 1 || count > 999) {
    showError('匹数は 1〜999 の数値で入力してください');
    return;
  }

  const pfid = species.price_fish_id;
  const priceEntry = PRICE_MASTER.prices[pfid];
  if (!priceEntry) {
    showError(species.site_display_name + ' の価格データが未登録です');
    return;
  }

  let perFishKg;
  let inputDetail;
  if (currentInputMode === 'cm') {
    const cm = parseFloat($('size').value);
    if (!Number.isFinite(cm) || cm <= 0 || cm > 200) {
      showError('平均サイズ（cm）を 1〜200 の数値で入力してください');
      return;
    }
    perFishKg = cmToKg(priceEntry.size_weight_curve, cm);
    if (!perFishKg) {
      showError(species.site_display_name + ' はサイズ→重量換算データが未登録です');
      return;
    }
    inputDetail = '平均サイズ ' + cm + ' cm → 推定重量 ' + fmtWeight(perFishKg) + ' / 尾';
  } else {
    const kg = parseFloat($('weight').value);
    if (!Number.isFinite(kg) || kg <= 0 || kg > 100) {
      showError('平均重量（kg）を 0.01〜100 の数値で入力してください');
      return;
    }
    perFishKg = kg;
    inputDetail = '平均重量 ' + fmtWeight(perFishKg) + ' / 尾';
  }

  const totalKg = perFishKg * count;
  const band = findBand(priceEntry.size_bands, perFishKg);

  const wholesaleLow  = totalKg * band.wholesale_low;
  const wholesaleHigh = totalKg * band.wholesale_high;
  const retailLow     = totalKg * band.retail_low;
  const retailHigh    = totalKg * band.retail_high;

  renderResult({
    species, priceEntry, band, count, perFishKg, totalKg,
    wholesaleLow, wholesaleHigh, retailLow, retailHigh, inputDetail,
  });
}

function renderResult(r) {
  // size-badge
  const badge = $('size-badge');
  badge.textContent = r.band.label;
  badge.dataset.class = r.band.size_class;

  // 総重量
  $('total-weight').textContent = '推定総重量 ' + fmtWeight(r.totalKg);

  // 小売
  $('retail-range').textContent = '約 ' + fmtYen(r.retailLow) + ' 〜 ' + fmtYen(r.retailHigh) + ' 円';
  $('retail-per').textContent = '1匹あたり 約 ' + fmtYen(r.retailLow / r.count) + ' 〜 ' + fmtYen(r.retailHigh / r.count) + ' 円';

  // 卸売
  $('wholesale-range').textContent = '約 ' + fmtYen(r.wholesaleLow) + ' 〜 ' + fmtYen(r.wholesaleHigh) + ' 円';
  $('wholesale-per').textContent = '1匹あたり 約 ' + fmtYen(r.wholesaleLow / r.count) + ' 〜 ' + fmtYen(r.wholesaleHigh / r.count) + ' 円';

  // 計算根拠
  const basis = $('basis-list');
  basis.innerHTML = '';
  const items = [
    r.inputDetail,
    'サイズ帯: ' + r.band.label + '（' + bandRangeLabel(r.priceEntry.size_bands, r.band) + '・' + r.band.size_class + '）',
    '卸売単価: ' + r.band.wholesale_low.toLocaleString() + ' 〜 ' + r.band.wholesale_high.toLocaleString() + ' 円/kg',
    '小売単価: ' + r.band.retail_low.toLocaleString() + ' 〜 ' + r.band.retail_high.toLocaleString() + ' 円/kg',
    '倍率カテゴリ: ' + r.priceEntry.category_tag,
    '出典: ' + r.priceEntry.wholesale_source,
  ];
  for (const it of items) {
    const li = document.createElement('li');
    li.textContent = it;
    basis.appendChild(li);
  }

  $('result').hidden = false;
  $('caution').hidden = false;
}

function bandRangeLabel(bands, target) {
  const idx = bands.indexOf(target);
  const lo = idx === 0 ? 0 : (bands[idx - 1].kg_max ?? 0);
  const hi = target.kg_max;
  const loStr = lo > 0 ? fmtWeight(lo) : '0';
  const hiStr = hi == null ? '上限なし' : fmtWeight(hi);
  return loStr + ' 〜 ' + hiStr;
}

// ===== URL パラメータ =====

function applyUrlParams() {
  const p = new URLSearchParams(location.search);
  const fish = p.get('fish');
  const count = p.get('count');
  const size = p.get('size');
  const weight = p.get('weight');

  if (fish) {
    $('fish').value = fish;
    onFishChange();
  }
  if (count) $('count').value = count;

  // size or weight が URL に含まれていれば、対応するモードに切替
  if (size && weight) {
    // 両方指定時は size を優先（cm入力）
    const cmRadio = document.querySelector('input[name="input-mode"][value="cm"]');
    if (cmRadio && !$('mode-switch').hidden) {
      cmRadio.checked = true;
      applyInputMode('cm');
    }
    $('size').value = size;
  } else if (size) {
    const cmRadio = document.querySelector('input[name="input-mode"][value="cm"]');
    if (cmRadio && !$('mode-switch').hidden) {
      cmRadio.checked = true;
      applyInputMode('cm');
    }
    $('size').value = size;
  } else if (weight) {
    const kgRadio = document.querySelector('input[name="input-mode"][value="kg"]');
    if (kgRadio && !$('mode-switch').hidden) {
      kgRadio.checked = true;
      applyInputMode('kg');
    }
    $('weight').value = weight;
  }

  // 必要パラメータが揃ってたら自動計算
  if (fish && count && (size || weight)) {
    onCalculate();
  }
}

// ===== 起動 =====

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', init);
} else {
  init();
}
