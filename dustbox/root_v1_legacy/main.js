/* main.js — vanilla JS interactions for funatsuri-yoso.com */
document.addEventListener("DOMContentLoaded", function () {
  "use strict";

  /* ------------------------------------------------------------------ */
  /* 1. Mobile hamburger menu                                           */
  /* ------------------------------------------------------------------ */
  var hamburger = document.querySelector(".hamburger");
  var drawerOverlay = document.querySelector(".drawer-overlay");

  function openDrawer() {
    document.body.classList.add("drawer-open");
  }
  function closeDrawer() {
    document.body.classList.remove("drawer-open");
  }

  if (hamburger) {
    hamburger.addEventListener("click", function (e) {
      e.stopPropagation();
      if (document.body.classList.contains("drawer-open")) {
        closeDrawer();
      } else {
        openDrawer();
      }
    });
  }

  if (drawerOverlay) {
    drawerOverlay.addEventListener("click", closeDrawer);
  }

  /* Prevent body scroll while drawer is open */
  var origOverflow = "";
  var observer = new MutationObserver(function () {
    if (document.body.classList.contains("drawer-open")) {
      origOverflow = document.body.style.overflow;
      document.body.style.overflow = "hidden";
    } else {
      document.body.style.overflow = origOverflow;
    }
  });
  observer.observe(document.body, { attributes: true, attributeFilter: ["class"] });

  /* ------------------------------------------------------------------ */
  /* 2. Area dropdown menu                                              */
  /* ------------------------------------------------------------------ */
  var areaMenu = document.getElementById("areaMenu");
  var areaBtn = document.querySelector(".area-dropdown > button, .area-dropdown > a");

  if (areaBtn && areaMenu) {
    areaBtn.addEventListener("click", function (e) {
      e.preventDefault();
      e.stopPropagation();
      areaMenu.classList.toggle("open");
    });

    document.addEventListener("click", function (e) {
      if (areaMenu.classList.contains("open")) {
        var dropdown = document.querySelector(".area-dropdown");
        if (dropdown && !dropdown.contains(e.target)) {
          areaMenu.classList.remove("open");
        }
      }
    });
  }

  /* ------------------------------------------------------------------ */
  /* 3. Fish card expand / collapse                                     */
  /* ------------------------------------------------------------------ */
  var fishCards = document.querySelectorAll(".fc");

  fishCards.forEach(function (card) {
    card.addEventListener("click", function (e) {
      /* Don't toggle when clicking links or buttons inside the card */
      if (e.target.closest("a") || e.target.closest("button")) return;

      var detail = card.querySelector(".fc-detail");
      if (!detail) return;

      var isVisible = detail.style.display === "block";
      detail.style.display = isVisible ? "none" : "block";

      gaEvent("fish_card_click", {
        fish: card.dataset.fish || card.querySelector("h3, .fc-name")?.textContent || ""
      });
    });
  });

  /* ------------------------------------------------------------------ */
  /* 4. Tab switching                                                   */
  /* ------------------------------------------------------------------ */
  window.switchTab = function (event, showId, hideId) {
    var show = document.getElementById(showId);
    var hide = document.getElementById(hideId);
    if (show) show.style.display = "";
    if (hide) hide.style.display = "none";

    /* Toggle .active on tab buttons */
    var btns = event.currentTarget.parentElement
      ? event.currentTarget.parentElement.querySelectorAll("button, a")
      : [];
    btns.forEach(function (b) { b.classList.remove("active"); });
    event.currentTarget.classList.add("active");
  };

  /* ------------------------------------------------------------------ */
  /* 5. Catch table filtering                                           */
  /* ------------------------------------------------------------------ */

  /* 5-a. Area filter */
  window.filterArea = function (btn, area) {
    var table = document.querySelector(".catch-table, table");
    if (!table) return;

    var rows = table.querySelectorAll("tbody tr");
    rows.forEach(function (row) {
      if (!area || area === "all") {
        row.style.display = "";
      } else {
        row.style.display = (row.dataset.area === area) ? "" : "none";
      }
    });

    /* Highlight active button */
    var siblings = btn.parentElement ? btn.parentElement.querySelectorAll("button") : [];
    siblings.forEach(function (b) { b.classList.remove("active"); });
    btn.classList.add("active");

    gaEvent("area_filter", { area: area });
  };

  /* 5-b. Fish name search */
  var searchDebounceTimer = null;

  window.searchFish = function (val) {
    var needle = val.toLowerCase();
    var table = document.querySelector(".catch-table, table");
    if (!table) return;

    var rows = table.querySelectorAll("tbody tr");
    rows.forEach(function (row) {
      var fishCell = row.querySelector("td.fish, td:nth-child(2)");
      if (!fishCell) { row.style.display = ""; return; }
      var text = fishCell.textContent.toLowerCase();
      row.style.display = text.indexOf(needle) !== -1 ? "" : "none";
    });

    /* Debounced GA event */
    clearTimeout(searchDebounceTimer);
    searchDebounceTimer = setTimeout(function () {
      if (val.length > 0) {
        gaEvent("fish_search", { query: val });
      }
    }, 1000);
  };

  /* 5-c. Sort table */
  var sortState = {}; /* key -> "asc" | "desc" */

  window.sortTable = function (key, btn) {
    var table = document.querySelector(".catch-table, table");
    if (!table) return;
    var tbody = table.querySelector("tbody");
    if (!tbody) return;

    var dir = sortState[key] === "asc" ? "desc" : "asc";
    sortState[key] = dir;

    var rows = Array.prototype.slice.call(tbody.querySelectorAll("tr"));
    rows.sort(function (a, b) {
      var aVal = cellValue(a, key);
      var bVal = cellValue(b, key);
      if (aVal < bVal) return dir === "asc" ? -1 : 1;
      if (aVal > bVal) return dir === "asc" ? 1 : -1;
      return 0;
    });
    rows.forEach(function (r) { tbody.appendChild(r); });

    /* Highlight active sort button */
    var headers = table.querySelectorAll("th button, .sort-btn");
    headers.forEach(function (b) { b.classList.remove("active", "asc", "desc"); });
    if (btn) {
      btn.classList.add("active", dir);
    }
  };

  function cellValue(row, key) {
    if (key === "date") {
      var cell = row.querySelector("td.date, td:first-child");
      return cell ? cell.textContent.trim() : "";
    }
    if (key === "count") {
      var cell = row.querySelector("td.count, td:nth-child(3)");
      var num = cell ? parseFloat(cell.textContent) : 0;
      return isNaN(num) ? 0 : num;
    }
    return "";
  }

  /* ------------------------------------------------------------------ */
  /* 6. NEW badge                                                       */
  /* ------------------------------------------------------------------ */
  var crawledAtEl = document.querySelector("[data-crawled-at]");
  if (crawledAtEl) {
    var crawledAt = new Date(crawledAtEl.dataset.crawledAt);
    var now = new Date();
    var diffMs = now - crawledAt;
    var diffH = diffMs / (1000 * 60 * 60);

    if (diffH < 24) {
      var badges = document.querySelectorAll(".new-badge");
      badges.forEach(function (badge) {
        badge.style.display = "inline-block";
      });
    }
  }

  /* ------------------------------------------------------------------ */
  /* 7. GA tracking helper                                              */
  /* ------------------------------------------------------------------ */
  function gaEvent(eventName, params) {
    if (typeof gtag === "function") {
      gtag("event", eventName, params || {});
    }
  }

  /* target_click tracking — for any element with data-ga-target */
  document.addEventListener("click", function (e) {
    var target = e.target.closest("[data-ga-target]");
    if (target) {
      gaEvent("target_click", {
        target: target.dataset.gaTarget
      });
    }
  });

  /* ------------------------------------------------------------------ */
  /* 8. Bottom nav active state (mobile)                                */
  /* ------------------------------------------------------------------ */
  var bottomLinks = document.querySelectorAll(".bottom-nav a");
  var currentPath = window.location.pathname;

  bottomLinks.forEach(function (link) {
    var href = link.getAttribute("href") || "";
    /* Normalize: strip trailing slash for comparison */
    var linkPath = href.replace(/\/$/, "") || "/";
    var pagePath = currentPath.replace(/\/$/, "") || "/";

    if (linkPath === pagePath || (href !== "/" && pagePath.indexOf(linkPath) === 0)) {
      link.classList.add("active");
    }
  });

  /* ------------------------------------------------------------------ */
  /* 9. Smooth scroll for anchor links                                  */
  /* ------------------------------------------------------------------ */
  document.addEventListener("click", function (e) {
    var anchor = e.target.closest('a[href^="#"]');
    if (!anchor) return;

    var hash = anchor.getAttribute("href");
    if (!hash || hash === "#") return;

    var targetEl = document.querySelector(hash);
    if (!targetEl) return;

    e.preventDefault();
    targetEl.scrollIntoView({ behavior: "smooth" });

    /* Update URL hash without jumping */
    if (history.pushState) {
      history.pushState(null, null, hash);
    }
  });
});
