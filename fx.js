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
  // Radar: a sweep arm rotates around us; the site is a blip that echoes when the sweep passes.
  function ping(canvas) {
    const ctx = canvas.getContext("2d");
    let state = "comprobando", host = "", W = 0, H = 0, cw = 8, ch = 14, cols = 0, rows = 0;
    let echoAt = -1e9, lastA = 0;
    const t0 = performance.now(), seed = [];
    function size() {
      const r = canvas.getBoundingClientRect(), d = Math.min(2, devicePixelRatio || 1);
      W = r.width; H = r.height; canvas.width = W * d; canvas.height = H * d; ctx.setTransform(d, 0, 0, d, 0, 0);
      cols = Math.max(10, Math.floor(W / cw)); rows = Math.max(6, Math.floor(H / ch));
      seed.length = 0; for (let i = 0; i < cols * rows; i++) seed.push(Math.random());
    }
    const col = st => st === "funcionando" ? css("--ok") : st === "parcial" ? css("--warn") : st === "caida" ? css("--bad") : css("--muted");
    function frame(now) {
      if (!W) size();
      ctx.clearRect(0, 0, W, H);
      const mono = css("--mono") || "monospace";
      ctx.font = `12px ${mono}`; ctx.textBaseline = "middle"; ctx.textAlign = "center";
      const cx = W / 2, cy = H / 2, R = Math.min(W / 2, H / 2) - 6;
      const PERIOD = 4200, sweep = (((now - t0) % PERIOD) / PERIOD) * Math.PI * 2 - Math.PI / 2;
      const blipA = -0.55, blipR = R * 0.62, bx = cx + Math.cos(blipA) * blipR, by = cy + Math.sin(blipA) * blipR;
      // fire an echo when the arm crosses the blip
      const norm = a => (a % (Math.PI * 2) + Math.PI * 2) % (Math.PI * 2);
      if (norm(sweep - blipA) < norm(lastA - blipA)) echoAt = now;
      lastA = sweep;
      const echo = (now - echoAt) / 1500;                              // 0..1 while the echo lives
      const accent = col(state), dim = css("--line-2"), faint = css("--line"), mut = css("--dim");
      const echoes = state === "funcionando" || state === "parcial";
      for (let r = 0; r < rows; r++) for (let c = 0; c < cols; c++) {
        const x = c * cw + cw / 2, y = r * ch + ch / 2, dx = x - cx, dy = y - cy, dist = Math.hypot(dx, dy);
        if (dist > R) continue;
        const n = seed[r * cols + c];
        let v = 0, use = dim;
        // range rings
        for (const k of [1 / 3, 2 / 3, 1]) if (Math.abs(dist - R * k) < ch * 0.45) v = Math.max(v, 0.16);
        // sweep trail (eased)
        const behind = norm(sweep - Math.atan2(dy, dx));
        if (behind < 1.25) { const t = 1 - behind / 1.25; v = Math.max(v, t * t * (0.35 + 0.35 * (dist / R)) * (0.6 + 0.4 * n)); }
        // echo rings around the blip
        if (echoes && echo >= 0 && echo < 1) {
          const d2 = Math.hypot(x - bx, y - by);
          for (let k = 0; k < 2; k++) {
            const rad = (echo - k * 0.18) * R * 0.75;
            if (rad > 0) { const w = Math.abs(d2 - rad); if (w < ch * 0.6) { const e = (1 - w / (ch * 0.6)) * (1 - echo) * (state === "parcial" ? 0.55 : 0.95); if (e > v) { v = e; use = accent; } } }
          }
        }
        if (v < 0.06) { if (n > 0.965) { ctx.fillStyle = faint; ctx.fillText("·", x, y); } continue; }
        ctx.fillStyle = use === accent ? accent : (v > 0.45 ? mut : dim);
        ctx.globalAlpha = Math.min(1, 0.25 + v);
        ctx.fillText(RAMP[Math.min(RAMP.length - 1, Math.round(v * (RAMP.length - 1)))], x, y);
        ctx.globalAlpha = 1;
      }
      // center (us) and the blip (the site)
      ctx.fillStyle = css("--fg"); ctx.font = `14px ${mono}`; ctx.fillText("▮", cx, cy);
      ctx.font = `11px ${mono}`; ctx.fillStyle = mut; ctx.fillText("nosotros", cx, cy + ch * 1.3);
      let bl = 1;
      if (state === "caida") bl = 0.55 + 0.45 * Math.abs(Math.sin(now / 260));
      else if (echoes) bl = echo >= 0 && echo < 1 ? 1 : 0.55;
      ctx.globalAlpha = bl; ctx.fillStyle = state === "comprobando" ? dim : accent; ctx.font = `15px ${mono}`;
      ctx.fillText(state === "caida" ? "✕" : "◆", bx, by); ctx.globalAlpha = 1;
      const label = host.length > 24 ? host.slice(0, 23) + "…" : host;
      ctx.font = `11px ${mono}`; ctx.fillStyle = mut; ctx.textAlign = bx > W * 0.7 ? "right" : "center";
      ctx.fillText(label, ctx.textAlign === "right" ? Math.min(W - 2, bx + 40) : bx, by - ch * 1.1);
      ctx.textAlign = "left";
      if (!reduce) requestAnimationFrame(frame);
    }
    new ResizeObserver(() => { size(); if (reduce) frame(performance.now()); }).observe(canvas);
    requestAnimationFrame(frame);
    return { set(st, h) { state = st; host = h || host; if (reduce) frame(performance.now()); } };
  }

  // 24-hour map: one row per hour of the day, one cell per minute. Shows which times of day the site works.
  function dayMap(canvas, day, now) {
    const r = canvas.getBoundingClientRect(), d = Math.min(2, devicePixelRatio || 1), W = r.width, H = r.height;
    if (!W || !H) return;
    canvas.width = W * d; canvas.height = H * d;
    const ctx = canvas.getContext("2d"); ctx.setTransform(d, 0, 0, d, 0, 0); ctx.clearRect(0, 0, W, H);
    const mono = css("--mono") || "monospace", lw = 26, top = 14;
    const cwid = (W - lw) / 60, chgt = (H - top) / 24, gap = Math.min(1.5, cwid * 0.2);
    const C = { f: css("--ok"), p: css("--warn"), c: css("--bad") };
    const empty = css("--raise-2"), dimc = css("--dim");
    ctx.font = `10px ${mono}`; ctx.textBaseline = "middle"; ctx.fillStyle = dimc;
    ctx.textAlign = "right"; for (let h = 0; h < 24; h += 3) ctx.fillText(String(h).padStart(2, "0"), lw - 6, top + h * chgt + chgt / 2);
    ctx.textAlign = "center"; [0, 15, 30, 45].forEach(m => ctx.fillText(":" + String(m).padStart(2, "0"), lw + m * cwid + cwid / 2, 5));
    const cur = new Date(now * 1000), nowH = cur.getHours(), nowM = cur.getMinutes();
    for (let i = 0; i < 1440; i++) {
      const t = new Date((now - i * 60) * 1000), h = t.getHours(), m = t.getMinutes();
      const ch = day ? day[i] : ".";
      ctx.fillStyle = C[ch] || empty;
      ctx.globalAlpha = ch === "c" ? 0.75 : 1;
      ctx.fillRect(lw + m * cwid + gap / 2, top + h * chgt + gap / 2, cwid - gap, chgt - gap);
    }
    ctx.globalAlpha = 1;
    ctx.strokeStyle = css("--fg"); ctx.lineWidth = 1;
    ctx.strokeRect(lw + nowM * cwid - 0.5, top + nowH * chgt - 0.5, cwid + 1, chgt + 1);
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

  window.FX = Object.assign(window.FX || {}, { ping, rtChart, dayMap });
})();
