/* lintc-swiper — from-scratch inline image carousel. Zero dependencies.
 * Auto-mounts to every .lintc-swiper on DOMContentLoaded. Reproduces the
 * default carousel behavior: slide snapping, pointer drag with momentum,
 * prev/next buttons, dot pagination, keyboard arrows. No external engine,
 * no global namespace; the instance lives on root._lintcSwiper = { api }.
 */
(function () {
  "use strict";

  var SVG_PREV = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="15 18 9 12 15 6"/></svg>';
  var SVG_NEXT = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="9 18 15 12 9 6"/></svg>';

  function el(tag, cls) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    return e;
  }

  function makeBtn(dir, label, svg) {
    var b = el("button", "lintc-swiper__btn lintc-swiper__btn--" + dir);
    b.type = "button";
    b.setAttribute("aria-label", label);
    b.innerHTML = svg;
    return b;
  }

  function mount(root) {
    if (root.dataset.lintcSwiperMounted === "true") return;
    var slides = Array.prototype.slice.call(root.children);
    if (slides.length === 0) return;
    root.dataset.lintcSwiperMounted = "true";

    // ---- build DOM scaffold ----
    var viewport = el("div", "lintc-swiper__viewport");
    var track = el("div", "lintc-swiper__track");
    slides.forEach(function (s) {
      s.classList.add("lintc-swiper__slide");
      track.appendChild(s);
    });
    viewport.appendChild(track);

    var controls = el("div", "lintc-swiper__controls");
    var nav = el("div", "lintc-swiper__nav");
    var prev = makeBtn("prev", "Previous slide", SVG_PREV);
    var next = makeBtn("next", "Next slide", SVG_NEXT);
    nav.appendChild(prev);
    nav.appendChild(next);
    var dots = el("div", "lintc-swiper__dots");
    controls.appendChild(nav);
    controls.appendChild(dots);

    root.appendChild(viewport);
    root.appendChild(controls);

    var count = slides.length;
    var index = 0;

    // ---- dots ----
    var dotBtns = [];
    for (var i = 0; i < count; i++) {
      (function (i) {
        var d = el("button", "lintc-swiper__dot");
        d.type = "button";
        d.setAttribute("aria-label", "Go to slide " + (i + 1));
        d.addEventListener("click", function () { goTo(i); });
        dots.appendChild(d);
        dotBtns.push(d);
      })(i);
    }

    function slideWidth() { return viewport.getBoundingClientRect().width; }
    function offsetFor(i) { return -i * slideWidth(); }
    function clamp(i) { return Math.max(0, Math.min(count - 1, i)); }

    function setTransform(x, animate) {
      track.style.transition = animate
        ? "transform 340ms cubic-bezier(0.22, 0.61, 0.36, 1)"
        : "none";
      track.style.transform = "translate3d(" + x + "px, 0, 0)";
    }

    function render(animate) {
      setTransform(offsetFor(index), animate);
      prev.disabled = index === 0;
      next.disabled = index === count - 1;
      for (var i = 0; i < count; i++) {
        dotBtns[i].classList.toggle("is-active", i === index);
        if (i === index) dotBtns[i].setAttribute("aria-current", "true");
        else dotBtns[i].removeAttribute("aria-current");
      }
    }

    function goTo(i, animate) {
      index = clamp(i);
      render(animate !== false);
    }

    prev.addEventListener("click", function () { goTo(index - 1); });
    next.addEventListener("click", function () { goTo(index + 1); });

    // ---- keyboard ----
    root.setAttribute("tabindex", "0");
    root.addEventListener("keydown", function (e) {
      if (e.key === "ArrowLeft") { goTo(index - 1); e.preventDefault(); }
      else if (e.key === "ArrowRight") { goTo(index + 1); e.preventDefault(); }
    });

    // ---- pointer drag with momentum ----
    var dragging = false, decided = false, horizontal = false;
    var startX = 0, startY = 0, baseX = 0, lastX = 0, lastT = 0, velocity = 0;

    function onDown(e) {
      if (e.button != null && e.button !== 0) return;
      dragging = true; decided = false; horizontal = false;
      startX = e.clientX; startY = e.clientY;
      baseX = offsetFor(index); // NB: a viewport resize mid-drag leaves baseX stale; goTo on release re-snaps.
      lastX = e.clientX; lastT = e.timeStamp; velocity = 0;
      setTransform(baseX, false);
      if (track.setPointerCapture) {
        try { track.setPointerCapture(e.pointerId); } catch (err) {}
      }
    }

    function onMove(e) {
      if (!dragging) return;
      var dx = e.clientX - startX, dy = e.clientY - startY;
      if (!decided) {
        if (Math.abs(dx) < 6 && Math.abs(dy) < 6) return;
        horizontal = Math.abs(dx) > Math.abs(dy);
        decided = true;
        if (!horizontal) { dragging = false; return; } // yield to vertical scroll
      }
      e.preventDefault();
      var x = baseX + dx;
      var min = offsetFor(count - 1), max = 0;
      if (x > max) x = max + (x - max) * 0.35;          // rubber-band at start
      else if (x < min) x = min + (x - min) * 0.35;     // rubber-band at end
      setTransform(x, false);
      var now = e.timeStamp;
      if (now > lastT) {
        velocity = (e.clientX - lastX) / (now - lastT); // px per ms
        lastX = e.clientX; lastT = now;
      }
    }

    function onUp(e) {
      if (!dragging) return;
      dragging = false;
      if (!horizontal) return;
      var dx = e.clientX - startX;
      var threshold = slideWidth() * 0.2;
      // Only trust velocity if the gesture was still moving at release; a fast
      // drag that paused before lift-off must not trigger a spurious flick.
      var recentFlick = (e.timeStamp - lastT) <= 80;
      var target = index;
      if (dx <= -threshold || (recentFlick && velocity < -0.5)) target = index + 1;
      else if (dx >= threshold || (recentFlick && velocity > 0.5)) target = index - 1;
      goTo(target, true);
    }

    track.addEventListener("pointerdown", onDown);
    track.addEventListener("pointermove", onMove);
    track.addEventListener("pointerup", onUp);
    track.addEventListener("pointercancel", onUp);
    track.addEventListener("dragstart", function (e) { e.preventDefault(); });

    var resizeRaf = null;
    window.addEventListener("resize", function () {
      if (resizeRaf) return;
      resizeRaf = requestAnimationFrame(function () {
        resizeRaf = null;
        render(false);
      });
    });

    root.classList.add("lintc-swiper--mounted");
    render(false);

    root._lintcSwiper = {
      api: {
        scrollPrev: function () { goTo(index - 1); },
        scrollNext: function () { goTo(index + 1); },
        scrollTo: function (i) { goTo(i); },
        selectedIndex: function () { return index; }
      }
    };
  }

  function init() {
    var roots = document.querySelectorAll(".lintc-swiper");
    Array.prototype.forEach.call(roots, mount);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
