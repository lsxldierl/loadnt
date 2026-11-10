// Load'nt? motion: scroll reveals, decoding status text, live ticker, self-typing terminal, typed placeholders.
// Everything is readable without this file; it only adds motion.
(function () {
  const root = document.documentElement;
  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
  root.classList.add("js");
  const esc = s => String(s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

  // --- reveal on scroll (children of [data-stagger] get increasing delays)
  function reveal() {
    document.querySelectorAll("[data-stagger]").forEach(g =>
      [...g.querySelectorAll(":scope > [data-reveal]")].forEach((el, i) => el.style.setProperty("--i", i)));
    const els = document.querySelectorAll("[data-reveal]:not(.in)");
    if (reduce || !("IntersectionObserver" in window)) { els.forEach(e => e.classList.add("in")); return; }
    const io = new IntersectionObserver(es => es.forEach(e => {
      if (e.isIntersecting) { e.target.classList.add("in"); io.unobserve(e.target); }
    }), { rootMargin: "0px 0px -8% 0px" });
    els.forEach(e => io.observe(e));
    setTimeout(() => document.querySelectorAll("[data-reveal]:not(.in)").forEach(e => {
      if (e.getBoundingClientRect().top < innerHeight) e.classList.add("in");
    }), 1200);
  }

  // --- text that decodes into place (status changes)
  const GLYPHS = "▖▘▝▗▚▞▙▟▛▜░▒▓#%&*+=<>/";
  function decode(el, text, ms = 650) {
    if (!el) return;
    if (reduce || el.dataset.text === text) { el.textContent = text; el.dataset.text = text; return; }
    el.dataset.text = text;
    const from = el.textContent, len = Math.max(from.length, text.length), t0 = performance.now(), token = {};
    el._dec = token;
    (function frame(now) {
      if (el._dec !== token) return;
      const p = Math.min(1, (now - t0) / ms);
      let out = "";
      for (let i = 0; i < len; i++) {
        const settle = (i / len) * 0.7 + 0.3;
        if (p >= settle) out += esc(text[i] || "");
        else if (text[i] === " " || p < settle - 0.45) out += esc(from[i] || "");
        else out += `<span class="scr">${GLYPHS[(Math.random() * GLYPHS.length) | 0]}</span>`;
      }
      el.innerHTML = out;
      if (p < 1) requestAnimationFrame(frame); else el.textContent = text;
    })(t0);
  }

  // --- ticker of real check results behind the hero
  const MARK = { funcionando: ["✓", "ok"], parcial: ["!", "warn"], caida: ["✕", "bad"], comprobando: ["·", ""] };
  const hm = new Intl.DateTimeFormat("es-EC", { hour: "2-digit", minute: "2-digit", hour12: false });
  function ticker(el, events) {
    if (!el) return;
    const items = (events.length ? events : [[Date.now() / 1000, "", "comprobando", "esperando la primera revisión"]])
      .map(e => { const [m, c] = MARK[e[2]] || MARK.comprobando;
        return `<span>${hm.format(new Date(e[0] * 1000))} <b class="${c}">${m}</b> ${e[1] ? esc(e[1]) + " · " : ""}${esc(String(e[3]).toLowerCase())}</span>`; });
    const sig = items.join("");
    if (el.dataset.sig === sig) return;
    el.dataset.sig = sig;
    const rows = el.querySelectorAll(".row").length || (innerWidth < 700 ? 4 : 6);
    let html = "";
    for (let r = 0; r < rows; r++) {
      const shift = items.slice(r * 3 % items.length).concat(items.slice(0, r * 3 % items.length));
      let line = shift.join("");
      while (line.length < 2400) line += line;          // long enough to loop seamlessly
      html += `<div class="row" style="--dur:${80 + r * 17}s">${line}${line}</div>`;
    }
    el.innerHTML = html;
  }

  // --- terminal transcript that types itself when it scrolls into view
  function terminal(el) {
    if (!el) return;
    const lines = [...el.querySelectorAll("[data-line]")];
    if (reduce || !("IntersectionObserver" in window)) return;
    lines.forEach(l => { l.dataset.full = l.innerHTML; l.style.visibility = "hidden"; });
    const run = async () => {
      for (const l of lines) {
        l.style.visibility = "visible";
        if (l.hasAttribute("data-type")) {
          const txt = l.textContent; l.textContent = "";
          for (let i = 0; i <= txt.length; i++) { l.textContent = txt.slice(0, i); await new Promise(r => setTimeout(r, 28)); }
          l.innerHTML = l.dataset.full;
        }
        await new Promise(r => setTimeout(r, +l.dataset.line || 420));
      }
    };
    const io = new IntersectionObserver(es => { if (es[0].isIntersecting) { io.disconnect(); run(); } }, { threshold: 0.35 });
    io.observe(el);
  }

  // --- typed placeholder cycling through example links
  function typePlaceholder(input, examples) {
    if (!input || reduce) return;
    let i = 0, j = 0, del = false;
    (function step() {
      if (document.activeElement === input || input.value) { input.placeholder = examples[0]; return setTimeout(step, 800); }
      const ex = examples[i];
      input.placeholder = ex.slice(0, j);
      if (!del && j < ex.length) { j++; setTimeout(step, 45); }
      else if (!del) { del = true; setTimeout(step, 1600); }
      else if (j > 0) { j--; setTimeout(step, 18); }
      else { del = false; i = (i + 1) % examples.length; setTimeout(step, 300); }
    })();
  }

  window.FX = { reveal, decode, ticker, terminal, typePlaceholder };
  addEventListener("DOMContentLoaded", () => reveal());
})();
