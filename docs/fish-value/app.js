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

function cmToKg(curve, cm) {
  if (!curve || curve.length === 0) return 0;
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

  const all = SPECIES_MAP.species
    .slice()
    .sort((a, b) => kanaSortKey(a.site_display_name).localeCompare(kanaSortKey(b.site_display_name)));

  let currentGroup = null;
  for (const s of all) {
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
  const entry = { id, fishId: preset?.fishId || '', bandCounts: preset?.bandCounts ? { ...preset.bandCounts } : {}, detailMode: false, items: [] };
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
        '<div class="input-mode-seg">' +
          '<button type="button" class="ims-btn ims-simple active">簡単入力</button>' +
          '<button type="button" class="ims-btn ims-detail">詳細入力</button>' +
        '</div>' +
        '<div class="band-total">' +
          '<span class="band-total-val">0</span>' +
          '<span class="band-total-unit">尾</span>' +
        '</div>' +
      '</div>' +
      '<div class="band-list"></div>' +
      '<div class="detail-list" hidden></div>' +
      '<button type="button" class="lock-btn" hidden></button>' +
    '</div>' +
    '<div class="entry-locked-summary" hidden></div>' +
    '<div class="entry-del-confirm" hidden></div>';
  $('entries').appendChild(el);

  el.querySelector('.entry-fish-btn').addEventListener('click', () => {
    if (entry.locked) { showFishChangeConfirm(entry); return; }
    openFishPicker(entry);
  });
  el.querySelector('.entry-remove').addEventListener('click', () => removeEntry(entry));
  el.querySelector('.ims-simple').addEventListener('click', () => { if (!entry.detailMode) return; toggleDetailMode(entry); });
  el.querySelector('.ims-detail').addEventListener('click', () => { if (entry.detailMode || !entry._priceEntry) return; toggleDetailMode(entry); });
  el.querySelector('.lock-btn').addEventListener('click', () => lockEntry(entry));

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
  if (entry.locked) {
    showDeleteConfirm(entry);
    return;
  }
  entries = entries.filter(e => e !== entry);
  const el = $('entries').querySelector('.entry[data-eid="' + entry.id + '"]');
  if (el) el.remove();
  updateEntryNumbers();
  updateRemoveButtons();
  scheduleLiveCalc();
}

function lockEntry(entry) {
  entry.locked = true;
  const el = $('entries').querySelector('.entry[data-eid="' + entry.id + '"]');
  if (!el) return;
  el.classList.add('is-locked');
  el.querySelector('.band-list-row').hidden = true;
  buildLockedSummary(el, entry);
  el.querySelector('.entry-locked-summary').hidden = false;
}

function unlockEntry(entry) {
  entry.locked = false;
  const el = $('entries').querySelector('.entry[data-eid="' + entry.id + '"]');
  if (!el) return;
  el.classList.remove('is-locked');
  el.querySelector('.band-list-row').hidden = false;
  el.querySelector('.entry-locked-summary').hidden = true;
  el.querySelector('.entry-del-confirm').hidden = true;
}

function buildLockedSummary(el, entry) {
  const summaryEl = el.querySelector('.entry-locked-summary');
  summaryEl.innerHTML = '';
  const species = entry._species;
  const total = entry.detailMode
    ? entry.items.filter(it => it.val > 0).length
    : Object.values(entry.bandCounts).reduce((a, b) => a + b, 0);

  const iconEl = document.createElement('div');
  iconEl.className = 'els-icon';
  const url = iconUrlOf(species);
  if (url) {
    const img = document.createElement('img');
    img.src = url;
    img.alt = '';
    img.onerror = function() { this.replaceWith(makeFallbackIcon()); };
    iconEl.appendChild(img);
  } else {
    iconEl.appendChild(makeFallbackIcon());
  }

  const bodyEl = document.createElement('div');
  bodyEl.className = 'els-body';
  const nameEl = document.createElement('div');
  nameEl.className = 'els-name';
  nameEl.textContent = species.site_display_name;
  const countEl = document.createElement('div');
  countEl.className = 'els-count';
  countEl.textContent = '合計 ' + total + '尾';
  bodyEl.appendChild(nameEl);
  bodyEl.appendChild(countEl);

  const editBtn = document.createElement('button');
  editBtn.type = 'button';
  editBtn.className = 'els-edit-btn';
  editBtn.textContent = '編集';
  editBtn.addEventListener('click', () => unlockEntry(entry));

  summaryEl.appendChild(iconEl);
  summaryEl.appendChild(bodyEl);
  summaryEl.appendChild(editBtn);
}

function showDeleteConfirm(entry) {
  const el = $('entries').querySelector('.entry[data-eid="' + entry.id + '"]');
  if (!el) return;
  const confirmEl = el.querySelector('.entry-del-confirm');
  // toggle: if already visible, hide it
  if (!confirmEl.hidden) {
    confirmEl.hidden = true;
    return;
  }
  confirmEl.innerHTML = '';

  const msg = document.createElement('span');
  msg.className = 'edc-msg';
  msg.textContent = '削除しますか？';

  const btnsEl = document.createElement('div');
  btnsEl.className = 'edc-btns';

  const cancelBtn = document.createElement('button');
  cancelBtn.type = 'button';
  cancelBtn.className = 'edc-cancel';
  cancelBtn.textContent = 'キャンセル';
  cancelBtn.addEventListener('click', () => { confirmEl.hidden = true; });

  const deleteBtn = document.createElement('button');
  deleteBtn.type = 'button';
  deleteBtn.className = 'edc-delete';
  deleteBtn.textContent = '削除する';
  deleteBtn.addEventListener('click', () => {
    entry.locked = false;
    entries = entries.filter(e => e !== entry);
    el.remove();
    updateEntryNumbers();
    updateRemoveButtons();
    scheduleLiveCalc();
  });

  btnsEl.appendChild(cancelBtn);
  btnsEl.appendChild(deleteBtn);
  confirmEl.appendChild(msg);
  confirmEl.appendChild(btnsEl);
  confirmEl.hidden = false;
}

function showFishChangeConfirm(entry) {
  const el = $('entries').querySelector('.entry[data-eid="' + entry.id + '"]');
  if (!el) return;
  const confirmEl = el.querySelector('.entry-del-confirm');
  if (!confirmEl.hidden) {
    confirmEl.hidden = true;
    return;
  }
  confirmEl.innerHTML = '';

  const msg = document.createElement('span');
  msg.className = 'edc-msg';
  msg.textContent = '魚種を変更すると入力内容がリセットされます。';

  const btnsEl = document.createElement('div');
  btnsEl.className = 'edc-btns';

  const cancelBtn = document.createElement('button');
  cancelBtn.type = 'button';
  cancelBtn.className = 'edc-cancel';
  cancelBtn.textContent = 'キャンセル';
  cancelBtn.addEventListener('click', () => { confirmEl.hidden = true; });

  const changeBtn = document.createElement('button');
  changeBtn.type = 'button';
  changeBtn.className = 'edc-delete';
  changeBtn.textContent = '変更する';
  changeBtn.addEventListener('click', () => {
    confirmEl.hidden = true;
    openFishPicker(entry);
  });

  btnsEl.appendChild(cancelBtn);
  btnsEl.appendChild(changeBtn);
  confirmEl.appendChild(msg);
  confirmEl.appendChild(btnsEl);
  confirmEl.hidden = false;
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
  if (entry.locked) unlockEntry(entry);
  clearError();
  entry.fishId = fishId;
  entry.bandCounts = {};
  entry.detailMode = false;
  entry.detailUnit = null;
  entry.items = [];

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
  // 詳細モードリセット
  el.querySelector('.band-list').hidden = false;
  el.querySelector('.detail-list').hidden = true;
  el.querySelector('.detail-list').innerHTML = '';
  el.querySelector('.ims-simple').classList.add('active');
  el.querySelector('.ims-detail').classList.remove('active');
  listRow.hidden = false;
  el.classList.add('has-fish');
  // 入力完了ボタンを表示・更新
  const lockBtn = el.querySelector('.lock-btn');
  lockBtn.textContent = species.site_display_name + ' 入力完了';
  lockBtn.hidden = false;
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
  const kgStr = hiKg == null ? lo + 'kg+' : lo + '〜' + fmtKgShort(hiKg) + 'kg';
  // kgモードでもsize_weight_curveがあればcm目安を括弧追記
  if (curve) {
    const loCm = prevKg > 0 ? Math.round(kgToCm(curve, prevKg)) : Math.round(curve[0].cm);
    const hiCm = hiKg != null ? Math.round(kgToCm(curve, hiKg)) : null;
    const cmHint = hiCm != null ? loCm + '〜' + hiCm + 'cm' : loCm + 'cm+';
    return kgStr + '  ' + cmHint;
  }
  return kgStr;
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

// ============================================
// 詳細入力モード
// ============================================

function toggleDetailMode(entry) {
  if (!entry._priceEntry) return;
  entry.detailMode = !entry.detailMode;
  entry.items = [];
  entry.bandCounts = {};
  const el = $('entries').querySelector('.entry[data-eid="' + entry.id + '"]');
  if (!el) return;
  const simpleBtn = el.querySelector('.ims-simple');
  const detailBtn = el.querySelector('.ims-detail');
  const bandList = el.querySelector('.band-list');
  const detailList = el.querySelector('.detail-list');
  if (entry.detailMode) {
    const speciesCm = entry._species && entry._species.input_modes && entry._species.input_modes[0] === 'cm';
    entry.detailUnit = speciesCm ? 'cm' : 'kg';
    detailBtn.classList.add('active');
    simpleBtn.classList.remove('active');
    bandList.hidden = true;
    detailList.hidden = false;
    addDetailItem(entry); // 最初の1匹を自動追加
  } else {
    simpleBtn.classList.add('active');
    detailBtn.classList.remove('active');
    bandList.hidden = false;
    detailList.hidden = true;
    detailList.innerHTML = '';
  }
  updateEntryTotal(entry);
  scheduleLiveCalc();
}

function buildDetailList(el, entry) {
  const detailList = el.querySelector('.detail-list');
  detailList.innerHTML = '';
  const priceEntry = entry._priceEntry;
  const curve = priceEntry && priceEntry.size_weight_curve;
  const unit = entry.detailUnit || 'kg';
  const isCm = unit === 'cm';

  // 単位トグル（size_weight_curveがある魚のみ）
  if (curve) {
    const unitSeg = document.createElement('div');
    unitSeg.className = 'unit-seg';
    ['kg', 'cm'].forEach(u => {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'us-btn us-' + u + (unit === u ? ' active' : '');
      btn.dataset.unit = u;
      btn.textContent = u;
      btn.addEventListener('click', () => {
        if (u === entry.detailUnit) return;
        entry.items.forEach(item => {
          if (item.val > 0) {
            if (u === 'cm') {
              item.val = Math.round(kgToCm(curve, item.val));
            } else {
              item.val = Math.round(cmToKg(curve, item.val) * 100) / 100;
            }
          }
        });
        entry.detailUnit = u;
        buildDetailList(el, entry);
      });
      unitSeg.appendChild(btn);
    });
    detailList.appendChild(unitSeg);
  }

  // 1匹ずつ行
  entry.items.forEach((item, idx) => {
    detailList.appendChild(buildDetailItemRow(entry, item, idx, unit, curve));
  });

  // 追加ボタン
  const addBtn = document.createElement('button');
  addBtn.type = 'button';
  addBtn.className = 'detail-add-btn';
  addBtn.textContent = '＋ 1匹追加';
  addBtn.addEventListener('click', () => addDetailItem(entry));
  detailList.appendChild(addBtn);
}

function formatStepperVal(v, unit) {
  if (unit === 'cm') return (v > 0 ? String(Math.round(v)) : '0') + ' cm';
  return (v > 0 ? (Math.round(v * 10) / 10).toFixed(1) : '0.0') + ' kg';
}

function toHalfWidth(str) {
  return (str || '')
    .replace(/[０-９]/g, ch => String.fromCharCode(ch.charCodeAt(0) - 0xFEE0))
    .replace(/[．。]/g, '.');
}

function buildDetailItemRow(entry, item, idx, unit, curve) {
  const isCm = unit === 'cm';
  const step = isCm ? 1 : 0.1;

  const row = document.createElement('div');
  row.className = 'detail-item';

  const numEl = document.createElement('span');
  numEl.className = 'di-num';
  numEl.textContent = (idx + 1) + '匹目';

  const stepper = document.createElement('div');
  stepper.className = 'di-stepper' + (item.val > 0 ? ' has-value' : '');

  const minusBtn = document.createElement('button');
  minusBtn.type = 'button';
  minusBtn.className = 'ds-btn ds-minus';
  minusBtn.setAttribute('aria-label', '−');
  minusBtn.innerHTML = '<svg viewBox="0 0 20 20" width="16" height="16"><path d="M4 10h12" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"/></svg>';

  const valEl = document.createElement('span');
  valEl.className = 'ds-val';
  valEl.textContent = formatStepperVal(item.val, unit);

  const plusBtn = document.createElement('button');
  plusBtn.type = 'button';
  plusBtn.className = 'ds-btn ds-plus';
  plusBtn.setAttribute('aria-label', '＋');
  plusBtn.innerHTML = '<svg viewBox="0 0 20 20" width="16" height="16"><path d="M10 4v12M4 10h12" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"/></svg>';

  stepper.appendChild(minusBtn);
  stepper.appendChild(valEl);
  stepper.appendChild(plusBtn);

  function setDetailVal(v) {
    if (!Number.isFinite(v)) v = 0;
    v = Math.max(0, isCm ? Math.round(v) : Math.round(v * 100) / 100);
    item.val = v;
    valEl.textContent = formatStepperVal(v, unit);
    stepper.classList.toggle('has-value', v > 0);
    updateEntryTotal(entry);
    scheduleLiveCalc();
  }

  attachHoldRepeat(minusBtn, () => setDetailVal(item.val - step));
  attachHoldRepeat(plusBtn, () => setDetailVal(item.val + step));

  // 数値タップで直接入力
  valEl.addEventListener('click', () => {
    if (valEl.querySelector('.ds-edit-input')) return; // 既に編集中
    const cur = item.val > 0 ? (isCm ? String(Math.round(item.val)) : (Math.round(item.val * 10) / 10).toFixed(1)) : '';
    valEl.textContent = '';
    const inp = document.createElement('input');
    inp.type = 'text';
    inp.className = 'ds-edit-input';
    inp.value = cur;
    inp.setAttribute('inputmode', 'decimal');
    valEl.appendChild(inp);
    inp.select();
    inp.focus();
    function commit() {
      const num = parseFloat(toHalfWidth(inp.value.trim()));
      valEl.textContent = '';
      if (Number.isFinite(num) && num >= 0) setDetailVal(num);
      else valEl.textContent = formatStepperVal(item.val, unit);
    }
    inp.addEventListener('blur', commit);
    inp.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') { e.preventDefault(); inp.blur(); }
      if (e.key === 'Escape') { valEl.textContent = formatStepperVal(item.val, unit); }
    });
  });

  const removeBtn = document.createElement('button');
  removeBtn.type = 'button';
  removeBtn.className = 'di-remove';
  removeBtn.setAttribute('aria-label', '削除');
  removeBtn.innerHTML = '<svg viewBox="0 0 20 20" width="14" height="14" aria-hidden="true"><path d="M5 5l10 10M15 5L5 15" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"/></svg>';
  removeBtn.addEventListener('click', () => removeDetailItem(entry, idx));

  row.appendChild(numEl);
  row.appendChild(stepper);
  row.appendChild(removeBtn);
  return row;
}

function addDetailItem(entry) {
  const prevVal = entry.items.length > 0 ? entry.items[entry.items.length - 1].val : 0;
  entry.items.push({ val: prevVal });
  const el = $('entries').querySelector('.entry[data-eid="' + entry.id + '"]');
  buildDetailList(el, entry);
  const plusBtns = el.querySelectorAll('.ds-plus');
  if (plusBtns.length) plusBtns[plusBtns.length - 1].focus();
}

function removeDetailItem(entry, idx) {
  entry.items.splice(idx, 1);
  const el = $('entries').querySelector('.entry[data-eid="' + entry.id + '"]');
  buildDetailList(el, entry);
  updateEntryTotal(entry);
  scheduleLiveCalc();
}

function updateEntryTotal(entry) {
  const total = entry.detailMode
    ? entry.items.filter(it => it.val > 0).length
    : Object.values(entry.bandCounts).reduce((a, b) => a + b, 0);
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

  const validEntries = entries.filter(e => {
    if (!e.fishId || !e._priceEntry) return false;
    if (e.detailMode) return e.items.some(it => it.val > 0);
    return Object.values(e.bandCounts).some(v => v > 0);
  });
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

    const isCm = species.input_modes && species.input_modes[0] === 'cm';
    const curve = priceEntry.size_weight_curve;

    if (e.detailMode) {
      const detailCm = e.detailUnit === 'cm';
      for (const item of e.items) {
        if (!item.val || item.val <= 0) continue;
        const kgVal = (detailCm && curve) ? cmToKg(curve, item.val) : item.val;
        const bandIdx = bands.findIndex(b => b.kg_max == null || kgVal <= b.kg_max);
        const band = bands[bandIdx >= 0 ? bandIdx : bands.length - 1];
        eCount += 1;
        eKg += kgVal;
        wholesaleLowSum  += kgVal * band.wholesale_low;
        wholesaleHighSum += kgVal * band.wholesale_high;
        const wMid = kgVal * (band.wholesale_low + band.wholesale_high) / 2;
        wholesaleMidSum  += wMid;
        eWholesaleMid    += wMid;
        retailLowSum     += kgVal * band.retail_low;
        retailHighSum    += kgVal * band.retail_high;
        const rMid = kgVal * (band.retail_low + band.retail_high) / 2;
        retailMidSum     += rMid;
        eRetailMid       += rMid;
        const displayVal = detailCm ? item.val + 'cm' : (Math.round(item.val * 10) / 10).toFixed(1) + 'kg';
        eBreakdown.push({ label: band.label + ' ' + displayVal, count: 1, perKg: kgVal, bandKg: kgVal });
      }
    } else {
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
    }

    totalCount += eCount;
    totalKg += eKg;

    perEntry.push({
      name: species.site_display_name,
      site_fish_id: species.site_fish_id,
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
    const folder = iconFolderOf(e.site_fish_id);
    const iconHtml = folder
      ? `<img class="rp-icon" src="../assets/fish/${folder}/${folder}_icon.png" alt="" aria-hidden="true" onerror="this.style.display='none'">`
      : '';
    pill.innerHTML =
      iconHtml +
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
