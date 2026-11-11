/* Slate process motion.
   Approach, grounded in published motion guidance: Apple HIG restraint (brief,
   purposeful, never decorative), Material 3 emphasized decelerate easing with
   short duration tokens, NN/g's 200-500ms window for state changes, Disney's
   follow-through as small staggers on results, and WAAPI interruptibility so a
   fast second action cancels the first animation cleanly. Every animation is
   tied to a real state change or a real wait; nothing loops for decoration and
   nothing adds delay. prefers-reduced-motion gets stillness. */
(() => {
  "use strict";
  const reduce = window.matchMedia("(prefers-reduced-motion: reduce)");
  const EASE = "cubic-bezier(.22,1,.36,1)"; // shared emphasized decelerate curve
  const live = new Set();
  const $ = id => document.getElementById(id);

  reduce.addEventListener("change", () => {
    if (reduce.matches) { live.forEach(a => a.cancel()); live.clear(); }
  });

  const style = document.createElement("style");
  style.textContent = `
/* Real-wait scan line: shown only while a request is actually in flight. */
.motion-scan{position:absolute;left:2px;right:2px;top:0;height:2px;z-index:6;overflow:hidden;border-radius:2px;pointer-events:none}
.motion-scan::before{content:"";position:absolute;top:0;bottom:0;width:45%;background:linear-gradient(90deg,transparent,rgba(53,100,222,.7),transparent);animation:motion-scan-slide 1.1s cubic-bezier(.45,0,.55,1) infinite}
html[data-theme=dark] .motion-scan::before{background:linear-gradient(90deg,transparent,rgba(140,175,255,.8),transparent)}
@keyframes motion-scan-slide{from{transform:translateX(-110%)}to{transform:translateX(320%)}}
/* Theme change is one cross-fade, not a hard cut. Applied only around a toggle. */
html.motion-theme,html.motion-theme body,html.motion-theme body *{transition-property:background-color,color,border-color,box-shadow,outline-color!important;transition-duration:.32s!important;transition-timing-function:ease!important}
@media(prefers-reduced-motion:reduce){.motion-scan{display:none}}
`;
  document.head.appendChild(style);

  function track(a) {
    a._slateMotion = true;
    live.add(a);
    const done = () => live.delete(a);
    a.finished.then(done, done); // cancel() rejects finished; swallow it
    // The change event is not delivered everywhere; poll while this runs.
    const iv = setInterval(() => {
      if (!live.has(a)) { clearInterval(iv); return; }
      if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) a.cancel();
    }, 4);
    return a;
  }

  /* Bounded rise-in for content that just appeared (HIG: brief and purposeful). */
  function rise(el, opts = {}) {
    if (!el || reduce.matches || typeof el.animate !== "function") return null;
    el.getAnimations().forEach(a => { if (a._slateMotion) a.cancel(); });
    return track(el.animate(
      [{ opacity: 0, transform: "translateY(10px)" }, { opacity: 1, transform: "translateY(0)" }],
      { duration: opts.duration || 420, delay: opts.delay || 0, easing: EASE, fill: "backwards" }));
  }

  /* Follow-through stagger for freshly rendered lists (chips, jobs, reviews). */
  function stagger(container, selector, opts = {}) {
    if (!container || reduce.matches) return;
    const step = opts.step || 34, cap = opts.cap || 9;
    container.querySelectorAll(selector).forEach((el, i) => {
      if (i < cap) rise(el, { delay: i * step, duration: opts.duration || 380 });
    });
  }

  /* One-shot settle when a value changes state (status tag, question counter). */
  function settle(el) {
    if (!el || reduce.matches || typeof el.animate !== "function") return;
    el.getAnimations().forEach(a => { if (a._slateMotion) a.cancel(); });
    track(el.animate(
      [{ transform: "scale(1.07)", opacity: .5 }, { transform: "scale(1)", opacity: 1 }],
      { duration: 330, easing: EASE }));
  }

  /* Low-amplitude flash for high-frequency status text (safe during dictation). */
  function flash(el) {
    if (!el || reduce.matches || typeof el.animate !== "function") return;
    el.getAnimations().forEach(a => { if (a._slateMotion) a.cancel(); });
    track(el.animate([{ opacity: .3 }, { opacity: 1 }], { duration: 240, easing: "ease-out" }));
  }

  /* Indeterminate scan line that lives exactly as long as the real request. */
  function scanStart(target) {
    if (!target || reduce.matches) return () => {};
    const box = document.createElement("div");
    box.className = "motion-scan";
    box.setAttribute("aria-hidden", "true");
    const prev = target.style.position;
    if (getComputedStyle(target).position === "static") target.style.position = "relative";
    target.appendChild(box);
    let stopped = false;
    return () => {
      if (stopped) return;
      stopped = true;
      box.remove();
      target.style.position = prev;
    };
  }

  function withScan(target, fn) {
    const stop = scanStart(typeof target === "string" ? $(target) : target);
    let out;
    try { out = fn(); } catch (e) { stop(); throw e; }
    if (out && typeof out.finally === "function") return out.finally(stop);
    stop();
    return out;
  }

  function wrapClick(el, scanTarget, after) {
    if (!el || typeof el.onclick !== "function") return;
    const orig = el.onclick;
    el.onclick = function (...args) {
      const p = scanTarget ? withScan(scanTarget, () => orig.apply(this, args)) : orig.apply(this, args);
      if (after) Promise.resolve(p).then(after).catch(() => {});
      return p;
    };
  }

  function onText(el, fn) {
    if (!el) return;
    new MutationObserver(fn).observe(el, { childList: true, characterData: true, subtree: true });
  }

  function onShown(el, fn) {
    if (!el) return;
    const visible = () => !el.classList.contains("hidden") && !el.classList.contains("off") && !el.hidden;
    let was = visible();
    new MutationObserver(() => {
      const is = visible();
      if (is && !was) fn();
      was = is;
    }).observe(el, { attributes: true, attributeFilter: ["class", "hidden"] });
  }

  window.slateMotion = { rise, stagger, settle, flash, scanStart, withScan };

  /* Theme cross-fade (all pages). Capture phase adds the transition window
     before the page's own click handler flips data-theme; the observer covers
     changes synced from another tab. */
  const themeButton = $("theme-toggle");
  if (themeButton) {
    const fade = () => {
      if (reduce.matches) return;
      const root = document.documentElement;
      root.classList.add("motion-theme");
      setTimeout(() => root.classList.remove("motion-theme"), 380);
    };
    themeButton.addEventListener("click", fade, true);
    new MutationObserver(fade).observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
  }

  /* Folded sections open with a small rise of their content (all pages). */
  document.addEventListener("toggle", e => {
    const d = e.target;
    if (!(d instanceof HTMLDetailsElement) || !d.open || reduce.matches) return;
    Array.from(d.children).filter(c => c.tagName !== "SUMMARY")
      .forEach((c, i) => rise(c, { delay: i * 30, duration: 320 }));
  }, true);

  /* Status tags settle into a new value (index draft tag, ai draft tag). */
  const statusTag = $("status");
  if (statusTag) onText(statusTag, () => settle(statusTag));

  /* ---- Workspace page (index.html) ---- */
  if ($("targetWorkspace")) {
    if (typeof window.say === "function") {
      const origSay = window.say;
      window.say = function (id) {
        const out = origSay.apply(this, arguments);
        flash($(id));
        return out;
      };
    }
    if (typeof window.showParsed === "function") {
      const origShowParsed = window.showParsed;
      window.showParsed = function () {
        const out = origShowParsed.apply(this, arguments);
        rise($("parsed"), { duration: 360 });
        stagger($("parsed"), ".chip", { step: 28 });
        return out;
      };
    }
    const surface = document.querySelector(".response-surface");
    wrapClick($("parse"), surface);
    const pdf = $("pdffile");
    if (pdf && pdf.onchange) {
      const origPdf = pdf.onchange;
      pdf.onchange = function (...a) { return withScan(surface, () => origPdf.apply(this, a)); };
    }
    if (typeof window.loadJobs === "function") {
      const origLoadJobs = window.loadJobs;
      window.loadJobs = function () {
        const p = origLoadJobs.apply(this, arguments);
        Promise.resolve(p).then(() => {
          if ($("jobs").children.length) stagger($("jobs"), ".job", { step: 45, cap: 8 });
        }).catch(() => {});
        return p;
      };
    }
    ["tailor", "targetDraft"].forEach(name => {
      if (typeof window[name] !== "function") return;
      const orig = window[name];
      const scanTarget = name === "tailor" ? $("s2") : $("targetWorkspace");
      window[name] = function () { return withScan(scanTarget, () => orig.apply(this, arguments)); };
    });
    onShown($("s3"), () => {
      stagger($("s3"), ".artifact-sheets > div", { step: 60, cap: 2 });
      rise($("s3").querySelector(".artifact-actions"), { delay: 90, duration: 360 });
    });
    wrapClick($("road"), $("s4"), () => stagger($("roadlist"), "li", { step: 55, cap: 8 }));
    if (typeof window.signedIn === "function") {
      const origSignedIn = window.signedIn;
      window.signedIn = function () {
        const out = origSignedIn.apply(this, arguments);
        flash($("loginmsg"));
        return out;
      };
    }
    if (typeof window.showRoleAck === "function") {
      const origAck = window.showRoleAck;
      window.showRoleAck = function (which) {
        const out = origAck.apply(this, arguments);
        rise($(which), { duration: 340 });
        return out;
      };
    }
  }

  /* ---- Interview page (interview.html) ---- */
  if ($("session") && $("question") && $("start") && !$("targetWorkspace")) {
    if (typeof window.msg === "function") {
      const origMsg = window.msg;
      window.msg = function (id) {
        const out = origMsg.apply(this, arguments);
        flash($(id));
        return out;
      };
    }
    wrapClick($("start"), $("setup"), () => {
      if (!$("session").classList.contains("hidden")) {
        rise($("session"));
        settle($("progress"));
      }
    });
    wrapClick($("submit"), $("session"));
    wrapClick($("endInterview"), $("session"));
    onText($("question"), () => rise($("question"), { duration: 380 }));
    onText($("liveReview"), () => rise($("liveReview"), { duration: 380 }));
    onText($("progress"), () => settle($("progress")));
    onShown($("results"), () => {
      rise($("summary"), { duration: 380 });
      stagger($("details"), ".review", { step: 70, cap: 8 });
    });
  }

  /* ---- AI draft page (ai.html) ---- */
  if ($("gen") && $("job")) {
    wrapClick($("parse"), $("s1"));
    onText($("parsed"), () => flash($("parsed")));
    wrapClick($("gen"), $("s2"), () => {
      if (!$("s3").classList.contains("off")) {
        rise($("dres"), { duration: 400 });
        rise($("dnote"), { delay: 60, duration: 400 });
        rise($("flags"), { delay: 30, duration: 360 });
      }
    });
    onShown($("s2"), () => rise($("s2"), { duration: 380 }));
    onText($("decision"), () => flash($("decision")));
  }
})();
