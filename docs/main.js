/* main.js — V2 共通スクリプト */
(function () {
  'use strict';

  /* ── テーブルフィルタ ── */
  var filterInput = document.getElementById('catch-filter');
  var filterRows  = document.querySelectorAll('.catch-table tbody tr');
  if (filterInput && filterRows.length) {
    filterInput.addEventListener('input', function () {
      var q = this.value.trim().toLowerCase();
      filterRows.forEach(function (tr) {
        tr.style.display = (!q || tr.textContent.toLowerCase().indexOf(q) !== -1) ? '' : 'none';
      });
    });
  }

  /* ── エリアフィルタ ── */
  var areaSelect = document.getElementById('area-filter');
  if (areaSelect && filterRows.length) {
    areaSelect.addEventListener('change', function () {
      var area = this.value;
      filterRows.forEach(function (tr) {
        var td = tr.querySelector('.col-area');
        tr.style.display = (!area || (td && td.textContent.trim() === area)) ? '' : 'none';
      });
    });
  }

  /* ── テーブルソート ── */
  document.querySelectorAll('.sortable').forEach(function (th) {
    th.style.cursor = 'pointer';
    th.addEventListener('click', function () {
      var table = th.closest('table');
      if (!table) return;
      var idx = Array.from(th.parentNode.children).indexOf(th);
      var asc = th.dataset.sortDir !== 'asc';
      th.dataset.sortDir = asc ? 'asc' : 'desc';
      var rows = Array.from(table.tBodies[0].rows);
      rows.sort(function (a, b) {
        var av = a.cells[idx].textContent.trim();
        var bv = b.cells[idx].textContent.trim();
        var an = parseFloat(av.replace(/[^\d.-]/g, ''));
        var bn = parseFloat(bv.replace(/[^\d.-]/g, ''));
        if (!isNaN(an) && !isNaN(bn)) return asc ? an - bn : bn - an;
        return asc ? av.localeCompare(bv, 'ja') : bv.localeCompare(av, 'ja');
      });
      rows.forEach(function (r) { table.tBodies[0].appendChild(r); });
    });
  });

  /* ── タブ切替 ── */
  document.querySelectorAll('.tab-group').forEach(function (tg) {
    var tabs   = tg.querySelectorAll('.tab-btn');
    var panels = tg.querySelectorAll('.tab-panel');
    tabs.forEach(function (btn, i) {
      btn.addEventListener('click', function () {
        tabs.forEach(function (t) { t.classList.remove('active'); });
        panels.forEach(function (p) { p.classList.remove('active'); });
        btn.classList.add('active');
        if (panels[i]) panels[i].classList.add('active');
      });
    });
  });

  /* ── スムーススクロール ── */
  document.querySelectorAll('a[href^="#"]').forEach(function (a) {
    a.addEventListener('click', function (e) {
      var id = a.getAttribute('href').slice(1);
      var target = document.getElementById(id);
      if (target) {
        e.preventDefault();
        target.scrollIntoView({ behavior: 'smooth', block: 'start' });
      }
    });
  });

  /* ── ボトムナビ active ── */
  var path = location.pathname.replace(/\/+$/, '') || '/';
  document.querySelectorAll('.bottom-nav a').forEach(function (a) {
    var href = (a.getAttribute('href') || '').replace(/\/+$/, '') || '/';
    if (path === href) a.classList.add('active');
  });

  /* ================================================================
     Analysis Overlay スピナー（D+F 2026/04/07 確定）
     ================================================================ */
  function showAnalysis(onComplete, cacheKey) {
    var overlay = document.getElementById('analysis-overlay');
    if (!overlay) { if (onComplete) onComplete(); return; }
    var steps  = overlay.querySelectorAll('.step');
    var bar    = document.getElementById('analysis-progress-fill');
    var cached = cacheKey && sessionStorage.getItem('spinner_' + cacheKey);

    overlay.classList.add('active');
    overlay.setAttribute('aria-hidden', 'false');

    if (cached) {
      if (bar) bar.style.width = '100%';
      setTimeout(function () { _finishOverlay(overlay, onComplete); }, 500);
      return;
    }

    function activateStep(i, pct, delay) {
      setTimeout(function () {
        if (i > 0) {
          steps[i - 1].classList.remove('active');
          steps[i - 1].classList.add('done');
        }
        steps[i].classList.add('active');
        if (bar) bar.style.width = pct + '%';
      }, delay);
    }

    activateStep(0, 35, 0);
    activateStep(1, 70, 1200);
    activateStep(2, 95, 2400);

    setTimeout(function () {
      steps[2].classList.remove('active');
      steps[2].classList.add('done');
      if (bar) bar.style.width = '100%';
    }, 3200);

    setTimeout(function () {
      _finishOverlay(overlay, onComplete);
      if (cacheKey) sessionStorage.setItem('spinner_' + cacheKey, '1');
    }, 3600);
  }

  function _finishOverlay(overlay, onComplete) {
    overlay.classList.remove('active');
    overlay.setAttribute('aria-hidden', 'true');
    overlay.querySelectorAll('.step').forEach(function (s) { s.classList.remove('active', 'done'); });
    var bar = document.getElementById('analysis-progress-fill');
    if (bar) bar.style.width = '0%';
    if (onComplete) onComplete();
  }

  function countUp(el, to, duration) {
    var start = null;
    function step(ts) {
      if (!start) start = ts;
      var progress = Math.min((ts - start) / duration, 1);
      var eased = 1 - Math.pow(1 - progress, 3);
      el.textContent = Math.round(to * eased);
      if (progress < 1) requestAnimationFrame(step);
    }
    requestAnimationFrame(step);
  }

  window.showAnalysis       = showAnalysis;
  window.countUp            = countUp;

})();
