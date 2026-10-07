/* ============================================================================
   sg-core.js — shared runtime: API client, formatters, canvas charts,
   dust particle engine, scroll machinery, toasts.
   No build step, no framework: plain ES2020 modules.
   ========================================================================= */

/* ------------------------------------------------------------------ api */
const API = "api";   // the pages live at /solarguard/ so relative works

async function jget(path, params) {
  const url = new URL(API + path, location.href);
  if (params) for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== "") url.searchParams.set(k, v);
  }
  const r = await fetch(url, { headers: { accept: "application/json" } });
  if (!r.ok) throw new Error(`${path} -> HTTP ${r.status}`);
  return r.json();
}

async function jpost(path, body) {
  const r = await fetch(new URL(API + path, location.href), {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`${path} -> HTTP ${r.status}`);
  return r.json();
}

/* ------------------------------------------------------------------ format */
const nf = (v, d = 0) => (v === null || v === undefined || Number.isNaN(v))
  ? "—" : Number(v).toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
const money = (v, d = 0) => nf(v, d) + " SAR";
const pct = (v, d = 1) => (v === null || v === undefined) ? "—" : nf(v, d) + "%";
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
const dateShort = (s) => new Date(s + "T00:00:00+03:00")
  .toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short" });

function riskColor(r) {
  return { low: "#3ddc97", moderate: "#ffd166", high: "#ff9f43", severe: "#ff5f6d" }[r] || "#7f8dab";
}
function lossColor(p) {          // green -> amber -> red as soiling grows
  const t = clamp(p / 30, 0, 1);
  const stops = [[61, 220, 151], [255, 209, 102], [255, 95, 109]];
  const seg = t < 0.5 ? 0 : 1;
  const f = t < 0.5 ? t / 0.5 : (t - 0.5) / 0.5;
  const c = stops[seg].map((c0, i) => Math.round(c0 + (stops[seg + 1][i] - c0) * f));
  return `rgb(${c.join(",")})`;
}

/* ------------------------------------------------------------------ charts */
/* Tiny canvas chart helpers — hand-written so the page ships with zero
   charting dependency and stays pixel-crisp on any DPI. */

function hidpi(canvas) {
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  const w = canvas.clientWidth || 600, h = canvas.clientHeight || 200;
  canvas.width = Math.round(w * dpr);
  canvas.height = Math.round(h * dpr);
  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, w, h);
  return { ctx, w, h };
}

/** Soiling-loss curve + money-lost bars for the horizon. */
function drawProjection(canvas, days, opts = {}) {
  const { ctx, w, h } = hidpi(canvas);
  const pad = { l: 44, r: 44, t: 18, b: 30 };
  const plotW = w - pad.l - pad.r, plotH = h - pad.t - pad.b;
  const maxLoss = Math.max(20, ...days.map((d) => d.soiling_loss_pct || 0)) * 1.15;
  const maxLost = Math.max(1, ...days.map((d) => d.lost_sar || 0));
  const X = (i) => pad.l + (plotW * i) / Math.max(days.length - 1, 1);
  const Y = (v) => pad.t + plotH - (plotH * clamp(v, 0, maxLoss)) / maxLoss;

  // grid + axis labels
  ctx.font = "11px ui-monospace, monospace";
  for (let g = 0; g <= 4; g++) {
    const v = (maxLoss / 4) * g, y = Y(v);
    ctx.strokeStyle = "rgba(148,180,255,0.10)"; ctx.beginPath();
    ctx.moveTo(pad.l, y); ctx.lineTo(w - pad.r, y); ctx.stroke();
    ctx.fillStyle = "rgba(127,141,171,0.9)"; ctx.textAlign = "right";
    ctx.fillText(v.toFixed(0) + "%", pad.l - 8, y + 4);
  }

  // lost-money bars (behind the curve)
  const bw = plotW / Math.max(days.length, 1) * 0.52;
  days.forEach((d, i) => {
    const bh = (plotH * 0.42) * ((d.lost_sar || 0) / maxLost);
    const x = X(i) - bw / 2, y = pad.t + plotH - bh;
    const g = ctx.createLinearGradient(0, y, 0, pad.t + plotH);
    g.addColorStop(0, "rgba(243,167,43,0.55)"); g.addColorStop(1, "rgba(243,167,43,0.05)");
    ctx.fillStyle = g; ctx.fillRect(x, y, bw, bh);
  });

  // cleaning markers
  days.forEach((d, i) => {
    if (!d.cleaned) return;
    ctx.strokeStyle = "rgba(61,220,151,0.75)"; ctx.setLineDash([4, 4]);
    ctx.beginPath(); ctx.moveTo(X(i), pad.t); ctx.lineTo(X(i), pad.t + plotH); ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillStyle = "#3ddc97"; ctx.beginPath(); ctx.arc(X(i), pad.t + 6, 3.5, 0, 7); ctx.fill();
  });

  // loss curve with glow
  ctx.beginPath();
  days.forEach((d, i) => { const x = X(i), y = Y(d.soiling_loss_pct || 0); i ? ctx.lineTo(x, y) : ctx.moveTo(x, y); });
  ctx.strokeStyle = "#37e0ff"; ctx.lineWidth = 2.4; ctx.shadowColor = "rgba(55,224,255,0.7)"; ctx.shadowBlur = 14; ctx.stroke(); ctx.shadowBlur = 0;
  const fill = ctx.createLinearGradient(0, pad.t, 0, pad.t + plotH);
  fill.addColorStop(0, "rgba(55,224,255,0.22)"); fill.addColorStop(1, "rgba(55,224,255,0.02)");
  ctx.lineTo(X(days.length - 1), pad.t + plotH); ctx.lineTo(X(0), pad.t + plotH); ctx.closePath();
  ctx.fillStyle = fill; ctx.fill();

  // dots + x labels
  days.forEach((d, i) => {
    if (i % Math.ceil(days.length / 7) && i !== days.length - 1) return;
    ctx.fillStyle = "#eaf1ff"; ctx.beginPath(); ctx.arc(X(i), Y(d.soiling_loss_pct || 0), 3, 0, 7); ctx.fill();
    ctx.fillStyle = "rgba(127,141,171,0.95)"; ctx.textAlign = "center";
    ctx.fillText((d.date || "").slice(8), X(i), h - 10);
  });

  ctx.textAlign = "left"; ctx.fillStyle = "#37e0ff"; ctx.fillText("soiling loss %", pad.l, pad.t - 4);
  ctx.textAlign = "right"; ctx.fillStyle = "#f3a72b"; ctx.fillText("value lost (SAR)", w - pad.r, pad.t - 4);
}

/** Stacked daily-energy chart: delivered vs lost to dust. */
function drawEnergy(canvas, days) {
  const { ctx, w, h } = hidpi(canvas);
  const pad = { l: 10, r: 10, t: 14, b: 26 };
  const plotW = w - pad.l - pad.r, plotH = h - pad.t - pad.b;
  const max = Math.max(...days.map((d) => d.energy_if_clean_kwh || 1)) * 1.1;
  const bw = plotW / days.length * 0.68;
  days.forEach((d, i) => {
    const x = pad.l + (plotW * i) / days.length + (plotW / days.length - bw) / 2;
    const kept = plotH * ((d.energy_kwh || 0) / max);
    const lost = plotH * (((d.energy_if_clean_kwh || 0) - (d.energy_kwh || 0)) / max);
    ctx.fillStyle = "rgba(55,224,255,0.55)";
    ctx.fillRect(x, pad.t + plotH - kept, bw, kept);
    ctx.fillStyle = "rgba(255,95,109,0.72)";
    ctx.fillRect(x, pad.t + plotH - kept - lost, bw, lost);
  });
  ctx.fillStyle = "rgba(127,141,171,0.9)"; ctx.font = "10px ui-monospace, monospace"; ctx.textAlign = "center";
  days.forEach((d, i) => {
    if (i % Math.ceil(days.length / 7)) return;
    ctx.fillText((d.date || "").slice(8), pad.l + (plotW * i) / days.length + plotW / days.length / 2, h - 8);
  });
}

/** Multi-series sparkline strip (wind, PM10, AOD …). */
function drawSeries(canvas, series) {
  const { ctx, w, h } = hidpi(canvas);
  const pad = { l: 8, r: 8, t: 16, b: 18 };
  const plotW = w - pad.l - pad.r, plotH = h - pad.t - pad.b;
  series.forEach((s, si) => {
    const vals = s.data.filter((v) => v !== null && v !== undefined);
    if (!vals.length) return;
    const max = Math.max(...vals) * 1.15 || 1, min = Math.min(0, ...vals);
    const off = (plotH / series.length) * si;
    const rowH = plotH / series.length;
    const X = (i) => pad.l + (plotW * i) / Math.max(s.data.length - 1, 1);
    const Y = (v) => off + rowH - 4 - ((rowH - 10) * (v - min)) / (max - min);
    ctx.beginPath();
    s.data.forEach((v, i) => { if (v === null) return; i ? ctx.lineTo(X(i), Y(v)) : ctx.moveTo(X(i), Y(v)); });
    ctx.strokeStyle = s.color; ctx.lineWidth = 1.8; ctx.stroke();
    ctx.fillStyle = s.color; ctx.font = "10px ui-monospace, monospace"; ctx.textAlign = "left";
    ctx.fillText(`${s.label} · max ${max.toFixed(s.decimals ?? 0)}`, pad.l, off + 11);
  });
}

/* ------------------------------------------------------------------ dust particles */
/* A lightweight canvas sandstorm: used as the hero backdrop when the rendered
   frames are unavailable, and as an overlay in the map. */
class DustField {
  constructor(canvas, opts = {}) {
    this.c = canvas; this.ctx = canvas.getContext("2d");
    this.count = opts.count || 220;
    this.speed = opts.speed ?? 1;
    this.colors = opts.colors || ["#f3a72b", "#ffcd6b", "#c98a2a", "#8a6a3a"];
    this.p = [];
    this.resize(); this.spawn();
    this.running = false;
    window.addEventListener("resize", () => { this.resize(); this.spawn(); });
  }
  resize() {
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    this.w = this.c.clientWidth || window.innerWidth;
    this.h = this.c.clientHeight || window.innerHeight;
    this.c.width = this.w * dpr; this.c.height = this.h * dpr;
    this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }
  spawn() {
    this.p = Array.from({ length: this.count }, () => ({
      x: Math.random() * this.w, y: Math.random() * this.h,
      r: 0.6 + Math.random() * 2.6, vx: (0.25 + Math.random() * 1.5) * this.speed,
      vy: (Math.random() - 0.4) * 0.32 * this.speed, a: 0.12 + Math.random() * 0.5,
      c: this.colors[(Math.random() * this.colors.length) | 0], ph: Math.random() * 6.28,
    }));
  }
  step(t) {
    const { ctx, w, h } = this;
    ctx.clearRect(0, 0, w, h);
    for (const p of this.p) {
      p.x += p.vx; p.y += p.vy + Math.sin(t / 900 + p.ph) * 0.18;
      if (p.x > w + 8) { p.x = -8; p.y = Math.random() * h; }
      if (p.y < -8) p.y = h + 8; if (p.y > h + 8) p.y = -8;
      ctx.globalAlpha = p.a; ctx.fillStyle = p.c;
      ctx.beginPath(); ctx.arc(p.x, p.y, p.r, 0, 6.283); ctx.fill();
    }
    ctx.globalAlpha = 1;
  }
  start(getScroll = () => window.scrollY) {
    if (this.running) return; this.running = true;
    const loop = (t) => {
      this.step(t);
      // accelerate with scroll: the storm gets worse as you read down the page
      this.speed = 0.6 + clamp(getScroll() / 2400, 0, 1.6);
      for (const p of this.p) p.vx = (0.25 + (p.r * 0.4 + 0.4) * this.speed);
      requestAnimationFrame(loop);
    };
    requestAnimationFrame(loop);
  }
}

/* ------------------------------------------------------------------ misc */
function toast(msg, ms = 3200) {
  let el = document.getElementById("sg-toast");
  if (!el) { el = document.createElement("div"); el.id = "sg-toast"; document.body.appendChild(el); }
  el.textContent = msg; el.classList.add("show");
  clearTimeout(el._t); el._t = setTimeout(() => el.classList.remove("show"), ms);
}

function revealOnScroll() {
  const io = new IntersectionObserver((entries) => {
    for (const e of entries) if (e.isIntersecting) { e.target.classList.add("in"); io.unobserve(e.target); }
  }, { rootMargin: "0px 0px -8% 0px", threshold: 0.08 });
  document.querySelectorAll(".reveal").forEach((el) => io.observe(el));
}

function progressBar() {
  const el = document.createElement("div"); el.id = "sg-progress"; document.body.appendChild(el);
  addEventListener("scroll", () => {
    const max = document.documentElement.scrollHeight - innerHeight;
    el.style.width = (max > 0 ? (scrollY / max) * 100 : 0) + "%";
  }, { passive: true });
}

/** 0 -> 1 as an element travels through the viewport (used when a section is not
 *  pinned: a phone shows the plot in normal flow, so its own travel is the clock). */
function elementProgress(el) {
  const r = el.getBoundingClientRect();
  const span = innerHeight + r.height;
  return clamp((innerHeight - r.top) / (span || 1), 0, 1);
}

/** Scroll position of an element, 0..1 across its own travel. */
function scrollProgress(el) {
  const r = el.getBoundingClientRect();
  const total = r.height - innerHeight;
  return clamp(-r.top / (total || 1), 0, 1);
}

/** Frame-sequence scrubber (the Apple-style technique, plain JS). */
class FrameScrubber {
  constructor(container, { dir, count, ext = "jpg", digits = 3, padding = 1 }) {
    this.dir = dir; this.count = count; this.ext = ext; this.digits = digits;
    this.canvas = document.createElement("canvas");
    this.ctx = this.canvas.getContext("2d");
    container.appendChild(this.canvas);
    this.images = new Array(count);
    this.current = -1; this.ready = 0;
    this.load().then((ok) => { if (ok) container.classList.add("ready"); });
  }
  src(i) { return `${this.dir}/${String(i + 1).padStart(this.digits, "0")}.${this.ext}`; }
  async load() {
    // probe the first frame; if it is missing, bail out quietly (procedural
    // dust takes over) instead of spamming the network with 404s
    const probe = await fetch(this.src(0), { method: "HEAD" }).catch(() => null);
    if (!probe || !probe.ok) return false;
    const first = await this.loadOne(0);
    return !!first;
  }
  loadOne(i) {
    return new Promise((res) => {
      const img = new Image();
      img.onload = () => { this.images[i] = img; this.ready++; res(img); };
      img.onerror = () => res(null);
      img.src = this.src(i);
    });
  }
  draw(i) {
    const img = this.images[i];
    if (!img) return;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const cw = this.canvas.clientWidth || innerWidth, ch = this.canvas.clientHeight || innerHeight;
    if (this.canvas.width !== Math.round(cw * dpr)) {
      this.canvas.width = Math.round(cw * dpr); this.canvas.height = Math.round(ch * dpr);
      this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    }
    const scale = Math.max(cw / img.width, ch / img.height) * 1.06;   // cover
    const dw = img.width * scale, dh = img.height * scale;
    this.ctx.drawImage(img, (cw - dw) / 2 - (i / this.count - 0.5) * 26, (ch - dh) / 2, dw, dh);
  }
  at(p) {                     // p in 0..1, skipping frames as the budget allows
    const i = Math.round(clamp(p, 0, 1) * (this.count - 1));
    if (i !== this.current) { this.current = i; if (!this.images[i]) this.loadOne(i); this.draw(i); }
  }
  /** Prefetch windowed frames so scrubbing stays smooth. */
  prefetch(p) {
    const c = Math.round(clamp(p, 0, 1) * (this.count - 1));
    for (let i = Math.max(0, c - 6); i <= Math.min(this.count - 1, c + 6); i++) {
      if (!this.images[i]) this.loadOne(i);
    }
  }
}

export { API, jget, jpost, nf, money, pct, clamp, dateShort, riskColor, lossColor,
         drawProjection, drawEnergy, drawSeries, DustField, toast, revealOnScroll,
         progressBar, scrollProgress, elementProgress, FrameScrubber, hidpi };
