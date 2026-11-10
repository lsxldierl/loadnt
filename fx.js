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
  const hm = new Intl.DateTimeFormat(undefined, { hour: "2-digit", minute: "2-digit", hour12: false });
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

// --- "ping" scene: a signal in monospace glyphs travels from our server to the site.
// up: arrives and returns, the site lights green · partial: arrives weak (orange) · down: fades out, red ✕
(function () {
  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const RAMP = " ·:-=+*#%@";
  function css(v) { return getComputedStyle(document.documentElement).getPropertyValue(v).trim(); }
  function ping(canvas) {
    const ctx = canvas.getContext("2d");
    let state = "comprobando", host = "", W = 0, H = 0, cw = 9, ch = 16, cols = 0, rows = 0, t0 = performance.now();
    const seed = [];
    function size() {
      const r = canvas.getBoundingClientRect(), d = Math.min(2, devicePixelRatio || 1);
      W = r.width; H = r.height; canvas.width = W * d; canvas.height = H * d; ctx.setTransform(d, 0, 0, d, 0, 0);
      cols = Math.max(10, Math.floor(W / cw)); rows = Math.max(5, Math.floor(H / ch));
      seed.length = 0; for (let i = 0; i < cols * rows; i++) seed.push(Math.random());
    }
    function color(st) { return st === "funcionando" ? css("--ok") : st === "parcial" ? css("--warn") : st === "caida" ? css("--bad") : css("--muted"); }
    function frame(now) {
      if (!W) size();
      ctx.clearRect(0, 0, W, H);
      ctx.font = `13px ${css("--mono") || "monospace"}`; ctx.textBaseline = "middle";
      const mid = Math.floor(rows / 2), x0 = 3, x1 = cols - 9, span = x1 - x0;
      const T = 3400, p = ((now - t0) % T) / T;                     // one round trip
      const reach = state === "caida" ? 0.62 : 1;                    // down: dies before the site
      const out = Math.min(1, p * 2), back = p > 0.5 ? (p - 0.5) * 2 : -1;
      const head = x0 + span * Math.min(out, reach);
      const fade = state === "caida" ? Math.max(0, 1 - Math.max(0, out - reach * 0.7) / 0.35) : 1;
      const accent = color(state), dim = css("--line-2"), faint = css("--line");
      const spread = Math.max(1.6, rows * 0.22);                      // how thick the signal is
      const arrived = state !== "caida" && out >= 1 ? (p - 0.5) / 0.5 : -1;   // 0..1 after reaching the site
      const burst = state === "caida" && out >= reach ? Math.min(1, (out - reach) / 0.35 + 0.0001) : -1;
      for (let r = 0; r < rows; r++) for (let c = 0; c < cols; c++) {
        const dy = Math.abs(r - mid);
        const n = seed[r * cols + c];
        let v = 0;
        if (c > x0 && c < x1) {
          const d = head - c;                                         // outgoing pulse with a tapered trail
          if (d >= 0 && d < 12 && p <= 0.5 && burst < 0) v = Math.max(v, (1 - d / 12) * Math.max(0, 1 - dy / (spread * (1 - d / 16)))) ;
          if (back >= 0 && state !== "caida") {                       // reply coming back
            const bh = x1 - span * back, db = c - bh;
            if (db >= 0 && db < 9) v = Math.max(v, (1 - db / 9) * Math.max(0, 1 - dy / (spread * .7)) * (state === "parcial" ? 0.5 : 0.95));
          }
          if (dy === 0) v = Math.max(v, 0.13);                        // the wire
        }
        if (arrived >= 0) {                                           // rings rippling out of the site
          const dx = (c - x1) * cw / ch, dist = Math.sqrt(dx * dx + dy * dy);
          for (let k = 0; k < 3; k++) {
            const rad = (arrived * 1.2 - k * 0.22) * rows * 0.9;
            if (rad > 0) { const w = Math.abs(dist - rad); if (w < 0.7) v = Math.max(v, (1 - w / 0.7) * (1 - arrived) * (state === "parcial" ? 0.55 : 0.9)); }
          }
        }
        if (burst >= 0) {                                             // down: the signal breaks apart
          const bx = x0 + span * reach, dx = (c - bx) * cw / ch, dist = Math.sqrt(dx * dx + dy * dy);
          if (dist < 1 + burst * rows * 0.6 && n > 0.55 + burst * 0.4) v = Math.max(v, (1 - burst) * 0.8 * n);
        }
        if (v < 0.05) { if (n > 0.94) { ctx.fillStyle = faint; ctx.fillText("·", c * cw, r * ch + ch / 2); } continue; }
        ctx.fillStyle = v > 0.32 ? accent : dim;
        ctx.globalAlpha = Math.min(1, 0.3 + v);
        ctx.fillText(RAMP[Math.min(RAMP.length - 1, Math.round(v * (RAMP.length - 1)))], c * cw, r * ch + ch / 2);
        ctx.globalAlpha = 1;
      }
      // end nodes: our server on the left, the site on the right
      const nodeY = mid * ch + ch / 2;
      ctx.fillStyle = css("--fg"); ctx.fillText("▮", x0 * cw - cw, nodeY);
      const lit = state === "funcionando" || state === "parcial" ? (p > 0.45 ? 1 : 0.5) : 1;
      ctx.globalAlpha = lit; ctx.fillStyle = state === "comprobando" ? dim : accent;
      ctx.fillText(state === "caida" ? "✕" : "▮", x1 * cw + cw, nodeY); ctx.globalAlpha = 1;
      ctx.fillStyle = css("--dim"); ctx.font = `11px ${css("--mono") || "monospace"}`;
      ctx.fillText("nosotros", (x0 - 1) * cw, nodeY + ch * 1.4);
      const label = host.length > 22 ? host.slice(0, 21) + "…" : host;
      ctx.textAlign = "center"; ctx.fillText(label, (x1 + 1.5) * cw, nodeY + ch * 1.4); ctx.textAlign = "left";
      if (!reduce) requestAnimationFrame(frame);
    }
    new ResizeObserver(() => { size(); if (reduce) frame(performance.now()); }).observe(canvas);
    requestAnimationFrame(frame);
    return { set(st, h) { state = st; host = h || host; if (reduce) frame(performance.now()); } };
  }

  // --- response-time chart (one dot per check, last hour), drawn in the page's own palette
  function rtChart(canvas, data, now) {
    const r = canvas.getBoundingClientRect(), d = Math.min(2, devicePixelRatio || 1), W = r.width, H = r.height;
    if (!W || !H) return;
    canvas.width = W * d; canvas.height = H * d;
    const ctx = canvas.getContext("2d"); ctx.setTransform(d, 0, 0, d, 0, 0); ctx.clearRect(0, 0, W, H);
    const pad = { l: 34, r: 6, t: 8, b: 18 }, iw = W - pad.l - pad.r, ih = H - pad.t - pad.b;
    const ok = data.filter(x => x[2] != null && x[1] !== "caida");
    const max = Math.max(5, ...ok.map(x => x[2] / 1000));
    const top = max <= 5 ? 5 : max <= 15 ? 15 : max <= 30 ? 30 : 60;
    ctx.font = `10px ${css("--mono") || "monospace"}`; ctx.textBaseline = "middle";
    [0, top / 2, top].forEach(v => {
      const y = pad.t + ih - (v / top) * ih;
      ctx.strokeStyle = css("--line"); ctx.lineWidth = 1; ctx.beginPath(); ctx.moveTo(pad.l, y + .5); ctx.lineTo(W - pad.r, y + .5); ctx.stroke();
      ctx.fillStyle = css("--dim"); ctx.textAlign = "right"; ctx.fillText(v + " s", pad.l - 6, y);
    });
    ctx.textAlign = "left"; ctx.fillText("hace 60 min", pad.l, H - 6); ctx.textAlign = "right"; ctx.fillText("ahora", W - pad.r, H - 6);
    const X = t => pad.l + iw * (1 - Math.min(3600, Math.max(0, now - t)) / 3600);
    ctx.strokeStyle = css("--line-2"); ctx.lineWidth = 1.5; ctx.beginPath();
    ok.forEach((x, i) => { const px = X(x[0]), py = pad.t + ih - Math.min(1, x[2] / 1000 / top) * ih; i ? ctx.lineTo(px, py) : ctx.moveTo(px, py); });
    ctx.stroke();
    data.forEach(x => {
      const px = X(x[0]);
      if (x[1] === "caida" || x[2] == null) { ctx.fillStyle = css("--bad"); ctx.fillRect(px - 1, pad.t + ih - 6, 2, 6); return; }
      const py = pad.t + ih - Math.min(1, x[2] / 1000 / top) * ih;
      ctx.fillStyle = x[1] === "funcionando" ? css("--ok") : css("--warn");
      ctx.beginPath(); ctx.arc(px, py, 2.5, 0, 7); ctx.fill();
    });
  }

  window.FX = Object.assign(window.FX || {}, { ping, rtChart });
})();
