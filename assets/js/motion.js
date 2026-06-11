/* ════════════════════════════════════════════════════════════
   PHIREWORX MOTION SYSTEM v1
   Self-contained. Auto-targets existing elements. No HTML edits.
   Respects prefers-reduced-motion. Safe fallbacks everywhere.
   ════════════════════════════════════════════════════════════ */
(function () {
  'use strict';
  if (window.__pwMotion) return; // guard against double-include
  window.__pwMotion = true;

  var REDUCED = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var docEl = document.documentElement;
  docEl.classList.add(REDUCED ? 'pw-reduced' : 'pw-motion');
  if (REDUCED) return; // honor user preference — site behaves exactly as before

  /* ───────────────────────────── helpers ───────────────────────────── */
  function onReady(fn) {
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', fn, { once: true });
    } else { fn(); }
  }
  function raf(fn) { return window.requestAnimationFrame(fn); }

  /* ════════════════════════════════════════════════════════════
     1. SCROLL PROGRESS BAR — thin amber line at very top
     ════════════════════════════════════════════════════════════ */
  function initProgressBar() {
    var bar = document.createElement('div');
    bar.id = 'pw-progress';
    document.body.appendChild(bar);
    var ticking = false;
    function update() {
      var h = docEl.scrollHeight - window.innerHeight;
      var p = h > 0 ? (window.scrollY / h) : 0;
      bar.style.transform = 'scaleX(' + Math.min(1, Math.max(0, p)) + ')';
      ticking = false;
    }
    window.addEventListener('scroll', function () {
      if (!ticking) { ticking = true; raf(update); }
    }, { passive: true });
    update();
  }

  /* ════════════════════════════════════════════════════════════
     2. NAV SCROLL STATE — shadow + tighter feel once scrolled
     ════════════════════════════════════════════════════════════ */
  function initNavState() {
    var nav = document.querySelector('.nav');
    if (!nav) return;
    var ticking = false;
    function update() {
      nav.classList.toggle('pw-scrolled', window.scrollY > 12);
      ticking = false;
    }
    window.addEventListener('scroll', function () {
      if (!ticking) { ticking = true; raf(update); }
    }, { passive: true });
    update();
  }

  /* ════════════════════════════════════════════════════════════
     3. HERO ENTRANCE — staggered load-in on homepage hero
     ════════════════════════════════════════════════════════════ */
  function initHeroEntrance() {
    var hero = document.querySelector('.hero');
    if (!hero) return;
    var seq = [
      '.hero-eyebrow',
      '.hero-h1 > span:nth-of-type(1)',
      '.hero-h1 > span:nth-of-type(2)',
      '.hero-h1 > span:nth-of-type(3)',
      '.hero-sub',
      '.hero-btns',
      '.hero-stats'
    ];
    var delay = 0;
    seq.forEach(function (sel) {
      var el = hero.querySelector(sel);
      if (!el) return;
      el.classList.add('pw-hero-item');
      el.style.transitionDelay = delay + 'ms';
      delay += 110;
    });
    // hero visual slides in from the right slightly later
    var visual = hero.querySelector('.hero-visual');
    if (visual) {
      visual.classList.add('pw-hero-visual');
      visual.style.transitionDelay = '250ms';
    }
    // trigger on next frame so transitions run
    raf(function () { raf(function () {
      hero.classList.add('pw-hero-in');
    }); });
  }

  /* ════════════════════════════════════════════════════════════
     4. SCROLL REVEALS — fade-up for sections, cards, grids
        Auto-tags existing elements. Staggers siblings in grids.
     ════════════════════════════════════════════════════════════ */
  var SINGLE_TARGETS = [
    '.section-eyebrow', '.section-title', '.section-desc', '.section-sub',
    '.page-hero-eyebrow', '.page-hero-title', '.page-hero-sub',
    '.cta-title', '.pricing-header-title', '.faq-category-title',
    '.hs-notice', '.hs-form-section', '.compare-table-wrap',
    '.pricing-block', '.policy-section', '.tm-term-title'
  ];
  var GROUP_TARGETS = [
    '.service-card', '.testimonial-card', '.booking-card', '.feature-card',
    '.gallery-item', '.shoot-gallery-item', '.media-gallery-cell', '.photo-strip-cell',
    '.process-step', '.how-step', '.timeline-step',
    '.ideal-program-card', '.ideal-item', '.included-item', '.deliverable-item',
    '.checklist-item', '.shoot-feature', '.td-feature', '.banner-type-card',
    '.banner-row-item', '.pricing-tier', '.acc-item', '.svc-fact',
    '.pricing-includes-item', '.media-hero-stat'
  ];

  var observer = null;
  function getObserver() {
    if (observer) return observer;
    observer = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) {
          entry.target.classList.add('pw-in');
          observer.unobserve(entry.target);
        }
      });
    }, { rootMargin: '0px 0px -8% 0px', threshold: 0.08 });
    return observer;
  }

  function tagReveals(root) {
    root = root || document;
    var obs = getObserver();

    SINGLE_TARGETS.forEach(function (sel) {
      var els = root.querySelectorAll(sel);
      for (var i = 0; i < els.length; i++) {
        var el = els[i];
        if (el.classList.contains('pw-reveal') || el.closest('.hero')) continue;
        el.classList.add('pw-reveal');
        obs.observe(el);
      }
    });

    GROUP_TARGETS.forEach(function (sel) {
      var els = root.querySelectorAll(sel);
      // group by parent for stagger
      var byParent = new Map();
      for (var i = 0; i < els.length; i++) {
        var el = els[i];
        if (el.classList.contains('pw-reveal') || el.closest('.hero')) continue;
        var p = el.parentElement;
        if (!byParent.has(p)) byParent.set(p, []);
        byParent.get(p).push(el);
      }
      byParent.forEach(function (group) {
        group.forEach(function (el, idx) {
          el.classList.add('pw-reveal');
          el.style.transitionDelay = Math.min(idx * 80, 480) + 'ms';
          obs.observe(el);
        });
      });
    });
  }

  /* ════════════════════════════════════════════════════════════
     5. STAT COUNTERS — count up when stats scroll into view
        Handles "14+", "50K+", "4.9★", "98%", "100%", "7-10"
     ════════════════════════════════════════════════════════════ */
  function initCounters() {
    var nums = document.querySelectorAll('.hero-stat-num, .media-hero-stat-num');
    if (!nums.length) return;
    var cObs = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (!entry.isIntersecting) return;
        cObs.unobserve(entry.target);
        animateCounter(entry.target);
      });
    }, { threshold: 0.4 });
    nums.forEach(function (el) { cObs.observe(el); });
  }

  function animateCounter(el) {
    // first text node holds the number; suffix spans stay untouched
    var node = null;
    for (var i = 0; i < el.childNodes.length; i++) {
      if (el.childNodes[i].nodeType === 3 && el.childNodes[i].textContent.trim()) {
        node = el.childNodes[i]; break;
      }
    }
    if (!node) return;
    var raw = node.textContent.trim();
    // ranges like "7-10" — animate the second part, keep "7-" prefix
    var range = raw.match(/^(\d+\s*[-–]\s*)(\d+(?:\.\d+)?)$/);
    var prefix = '';
    var targetStr = raw;
    if (range) { prefix = range[1]; targetStr = range[2]; }
    var target = parseFloat(targetStr);
    if (isNaN(target)) return;
    var decimals = (targetStr.split('.')[1] || '').length;
    var dur = 1400;
    var start = null;
    function ease(t) { return 1 - Math.pow(1 - t, 4); } // easeOutQuart
    function frame(ts) {
      if (!start) start = ts;
      var p = Math.min(1, (ts - start) / dur);
      var val = (target * ease(p)).toFixed(decimals);
      node.textContent = prefix + val;
      if (p < 1) raf(frame);
      else node.textContent = prefix + targetStr;
    }
    node.textContent = prefix + (0).toFixed(decimals);
    raf(frame);
  }

  /* ════════════════════════════════════════════════════════════
     6. SUBTLE PARALLAX — hero visuals drift gently on scroll
     ════════════════════════════════════════════════════════════ */
  function initParallax() {
    var targets = [];
    var grid = document.querySelector('.hero-visual-grid');
    if (grid) {
      var cells = grid.children;
      for (var i = 0; i < cells.length; i++) {
        targets.push({ el: cells[i], speed: (i % 2 === 0 ? -1 : 1) * (0.03 + (i % 3) * 0.015) });
      }
    }
    var glow = document.querySelector('.hero-glow');
    if (glow) targets.push({ el: glow, speed: 0.08 });
    if (!targets.length) return;

    var ticking = false;
    function update() {
      var y = window.scrollY;
      if (y < window.innerHeight * 1.4) {
        for (var i = 0; i < targets.length; i++) {
          targets[i].el.style.transform = 'translate3d(0,' + (y * targets[i].speed).toFixed(1) + 'px,0)';
        }
      }
      ticking = false;
    }
    window.addEventListener('scroll', function () {
      if (!ticking) { ticking = true; raf(update); }
    }, { passive: true });
  }

  /* ════════════════════════════════════════════════════════════
     7. BADGE DOT PULSE — make the "NOW BOOKING" dot breathe
     ════════════════════════════════════════════════════════════ */
  function initBadgePulse() {
    // common patterns: a span/div dot inside hero-badge or eyebrow-ish badges
    var badges = document.querySelectorAll('.hero-badge, .now-booking, [class*="badge"]');
    badges.forEach(function (b) {
      var dot = b.querySelector('[class*="dot"], span:first-child');
      if (dot && dot.textContent.trim().length <= 1) dot.classList.add('pw-pulse');
    });
  }

  /* ════════════════════════════════════════════════════════════
     8. ASYNC CONTENT — re-tag after CMS loaders inject content
     ════════════════════════════════════════════════════════════ */
  function watchAsyncContent() {
    [600, 1500, 3000].forEach(function (t) {
      setTimeout(function () { try { tagReveals(); } catch (e) {} }, t);
    });
  }

  /* ════════════════════════════════════════════════════════════
     SAFETY NET — if anything goes wrong, force everything visible
     ════════════════════════════════════════════════════════════ */
  function safetyNet() {
    setTimeout(function () {
      var hidden = document.querySelectorAll('.pw-reveal:not(.pw-in)');
      for (var i = 0; i < hidden.length; i++) {
        var r = hidden[i].getBoundingClientRect();
        if (r.top < window.innerHeight && r.bottom > 0) hidden[i].classList.add('pw-in');
      }
    }, 4000);
  }

  /* ───────────────────────────── boot ───────────────────────────── */
  onReady(function () {
    try { initProgressBar(); } catch (e) {}
    try { initNavState(); } catch (e) {}
    try { initHeroEntrance(); } catch (e) {}
    try { tagReveals(); } catch (e) {}
    try { initCounters(); } catch (e) {}
    try { initParallax(); } catch (e) {}
    try { initBadgePulse(); } catch (e) {}
    try { watchAsyncContent(); } catch (e) {}
    try { safetyNet(); } catch (e) {}
  });
})();
