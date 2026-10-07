/* ============================================================================
   sg-3d.js — the 3D storytelling layer, written directly against <canvas>.

   Two pieces, both driven by scroll position:
     1. Globe3D   — Earth wireframe with Saudi Arabia lit up, rotating as the page
                    scrolls, with a dust belt and inbound dust-event arcs.
     2. PanelRig  — a perspective solar array that gets buried in dust as you
                    scroll down, then gets cleaned, with a live loss readout.

   Deliberately dependency-free: no three.js, no CDN. If the network is down the
   page still has 3D. Real data drives the numbers (soiling loss from the API is
   passed in by the page).
   ========================================================================= */

/* --------------------------------------------------------------- globe */
export class Globe3D {
  constructor(canvas, opts = {}) {
    this.c = canvas;
    this.ctx = canvas.getContext("2d");
    this.lat = opts.lat ?? 24.0;
    this.lon = opts.lon ?? 45.0;
    this.spin = opts.spin ?? 0.06;         // rad/s idle spin
    this.borders = null;
    this.dust = Array.from({ length: 90 }, () => ({
      a: Math.random() * Math.PI * 2,          // orbit angle
      r: 1.16 + Math.random() * 0.5,           // orbit radius (planet radii)
      y: (Math.random() - 0.5) * 2.2,
      s: 0.05 + Math.random() * 0.25,          // angular speed
      size: 0.5 + Math.random() * 1.7,
    }));
    this.plumes = Array.from({ length: 4 }, (_, i) => ({ start: -0.2 - i * 0.5, len: 0.5 + Math.random() * 0.3 }));
    this.scroll = 0;
    this._resize();
    addEventListener("resize", () => this._resize());
    fetch("assets/data/borders.json").then((r) => r.json()).then((b) => { this.borders = b; }).catch(() => {});
    this._t0 = performance.now();
    this._loop();
  }
  _resize() {
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    this.w = this.c.clientWidth || 600;
    this.h = this.c.clientHeight || 460;
    this.c.width = Math.round(this.w * dpr); this.c.height = Math.round(this.h * dpr);
    this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    this.R = Math.min(this.w, this.h) * 0.36;
    this.cx = this.w / 2; this.cy = this.h / 2;
  }
  setScroll(p) { this.scroll = p; }

  _rot(latDeg, lonDeg, yaw, pitch) {
    const la = (latDeg * Math.PI) / 180, lo = (lonDeg * Math.PI) / 180 + yaw;
    let x = Math.cos(la) * Math.sin(lo);
    let y = Math.sin(la);
    let z = Math.cos(la) * Math.cos(lo);
    const cp = Math.cos(pitch), sp = Math.sin(pitch);
    const y2 = y * cp - z * sp, z2 = y * sp + z * cp;
    return { x, y: y2, z: z2 };
  }

  _loop() {
    const step = () => {
      const t = (performance.now() - this._t0) / 1000;
      const yaw = t * this.spin + this.scroll * 2.6;
      const pitch = -0.42 + this.scroll * 0.5;
      const ctx = this.ctx;
      ctx.clearRect(0, 0, this.w, this.h);

      // starfield
      ctx.save();
      for (let i = 0; i < 90; i++) {
        const s = Math.sin(i * 12.9898) * 43758.5453;
        const x = (s - Math.floor(s)) * this.w;
        const s2 = Math.sin(i * 78.233) * 12345.6789;
        const y = (s2 - Math.floor(s2)) * this.h;
        ctx.globalAlpha = 0.16 + ((i % 7) / 7) * 0.5;
        ctx.fillStyle = i % 11 === 0 ? "#8ff2ff" : "#eaf1ff";
        ctx.fillRect(x, y, 1.4, 1.4);
      }
      ctx.restore();

      // atmosphere
      const atmo = ctx.createRadialGradient(this.cx, this.cy, this.R * 0.9, this.cx, this.cy, this.R * 1.4);
      atmo.addColorStop(0, "rgba(55,224,255,0.16)");
      atmo.addColorStop(0.5, "rgba(55,224,255,0.05)");
      atmo.addColorStop(1, "rgba(55,224,255,0)");
      ctx.fillStyle = atmo; ctx.beginPath(); ctx.arc(this.cx, this.cy, this.R * 1.4, 0, 7); ctx.fill();

      // planet body
      const body = ctx.createRadialGradient(this.cx - this.R * 0.35, this.cy - this.R * 0.4, this.R * 0.1, this.cx, this.cy, this.R);
      body.addColorStop(0, "#16233d"); body.addColorStop(0.65, "#0b1425"); body.addColorStop(1, "#050a14");
      ctx.fillStyle = body; ctx.beginPath(); ctx.arc(this.cx, this.cy, this.R, 0, 7); ctx.fill();

      // graticule
      ctx.strokeStyle = "rgba(148,180,255,0.10)"; ctx.lineWidth = 1;
      for (let la = -60; la <= 60; la += 30) {
        ctx.beginPath(); let started = false;
        for (let lo = -180; lo <= 180; lo += 4) {
          const p = this._rot(la, lo, yaw, pitch);
          if (p.z <= 0) { started = false; continue; }
          const x = this.cx + p.x * this.R, y = this.cy - p.y * this.R;
          started ? ctx.lineTo(x, y) : ctx.moveTo(x, y); started = true;
        }
        ctx.stroke();
      }
      for (let lo = -180; lo < 180; lo += 30) {
        ctx.beginPath(); let started = false;
        for (let la = -85; la <= 85; la += 4) {
          const p = this._rot(la, lo, yaw, pitch);
          if (p.z <= 0) { started = false; continue; }
          const x = this.cx + p.x * this.R, y = this.cy - p.y * this.R;
          started ? ctx.lineTo(x, y) : ctx.moveTo(x, y); started = true;
        }
        ctx.stroke();
      }

      // countries — Saudi Arabia highlighted as the subject
      if (this.borders) {
        for (const [cc, rings] of Object.entries(this.borders)) {
          const isSA = cc === "SAU";
          ctx.beginPath();
          for (const ring of rings) {
            let started = false;
            for (const [lo, la] of ring) {
              const p = this._rot(la, lo, yaw, pitch);
              if (p.z <= 0) { started = false; continue; }
              const x = this.cx + p.x * this.R, y = this.cy - p.y * this.R;
              started ? ctx.lineTo(x, y) : ctx.moveTo(x, y); started = true;
            }
            ctx.closePath();
          }
          if (isSA) {
            ctx.fillStyle = "rgba(243,167,43,0.30)";
            ctx.fill();
            ctx.strokeStyle = "#ffcd6b"; ctx.lineWidth = 1.9;
            ctx.shadowColor = "rgba(243,167,43,0.9)"; ctx.shadowBlur = 16;
            ctx.stroke(); ctx.shadowBlur = 0;
          } else {
            ctx.fillStyle = "rgba(55,224,255,0.05)";
            ctx.fill();
            ctx.strokeStyle = "rgba(148,180,255,0.22)"; ctx.lineWidth = 1;
            ctx.stroke();
          }
        }
      }

      // the marker: where the dashboard is aimed
      const m = this._rot(this.lat, this.lon, yaw, pitch);
      if (m.z > 0) {
        const x = this.cx + m.x * this.R, y = this.cy - m.y * this.R;
        ctx.beginPath(); ctx.arc(x, y, 4.6, 0, 7); ctx.fillStyle = "#ff5f6d";
        ctx.shadowColor = "#ff5f6d"; ctx.shadowBlur = 18; ctx.fill(); ctx.shadowBlur = 0;
        for (let k = 1; k <= 3; k++) {
          const rr = 6 + ((t * 26 + k * 14) % 34);
          ctx.globalAlpha = Math.max(0, 0.5 - rr / 70);
          ctx.beginPath(); ctx.arc(x, y, rr, 0, 7);
          ctx.strokeStyle = "#ff5f6d"; ctx.lineWidth = 1.4; ctx.stroke();
          ctx.globalAlpha = 1;
        }
      }

      // dust belt + inbound plumes
      for (const d of this.dust) {
        d.a += d.s * 0.01;
        const x3 = Math.cos(d.a) * d.r, z3 = Math.sin(d.a) * d.r, y3 = d.y;
        if (z3 <= 0) continue;
        const x = this.cx + x3 * this.R, y = this.cy - y3 * this.R;
        ctx.globalAlpha = 0.10 + 0.28 * (z3 / 1.6);
        ctx.fillStyle = d.size > 1.4 ? "#ffcd6b" : "#f3a72b";
        ctx.beginPath(); ctx.arc(x, y, d.size, 0, 6.283); ctx.fill();
      }
      ctx.globalAlpha = 1;
      for (const p of this.plumes) {
        p.start += 0.0028;
        if (p.start > 1.3) p.start = -0.6;
        ctx.beginPath();
        for (let s = 0; s <= 1; s += 0.05) {
          const a = p.start + s * p.len;
          const rr = 1.2 + s * 0.55;
          const x3 = Math.cos(a) * rr, z3 = Math.sin(a) * rr, y3 = -0.2 + s * 0.35;
          if (z3 <= 0) continue;
          const x = this.cx + x3 * this.R, y = this.cy - y3 * this.R;
          s === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
        }
        ctx.strokeStyle = "rgba(255,176,32,0.55)"; ctx.lineWidth = 2.2;
        ctx.shadowColor = "rgba(255,176,32,0.8)"; ctx.shadowBlur = 10; ctx.stroke(); ctx.shadowBlur = 0;
      }
      requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  }
}

/* --------------------------------------------------------------- panel rig */
export class PanelRig {
  constructor(canvas, opts = {}) {
    this.c = canvas;
    this.ctx = canvas.getContext("2d");
    this.rows = opts.rows ?? 4;
    this.cols = opts.cols ?? 9;
    this.dust = 0;              // 0..1 how dirty the glass is
    this.scroll = 0;
    this._resize();
    addEventListener("resize", () => this._resize());
    this._t0 = performance.now();
    this.motes = Array.from({ length: 130 }, () => ({
      x: Math.random(), y: Math.random(), s: 0.2 + Math.random() * 1.5, r: 0.5 + Math.random() * 1.6,
    }));
    this._loop();
  }
  _resize() {
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    this.w = this.c.clientWidth || 640; this.h = this.c.clientHeight || 420;
    this.c.width = Math.round(this.w * dpr); this.c.height = Math.round(this.h * dpr);
    this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }
  /** p in 0..1: first 60 % of the scroll buries the array, then it is cleaned. */
  setScroll(p) {
    this.scroll = p;
    const dirty = Math.min(1, p / 0.62);
    const clean = p <= 0.62 ? 0 : (p - 0.62) / 0.38;
    this.dust = dirty * (1 - clean);            // wipe after the storm
    this.wipe = clean;                          // 0..1 position of the cleaning bar
  }
  _project(u, v, y, tilt) {
    // u,v in 0..1 across the array plane; y is the local height above the plane
    const cx = this.w / 2, cy = this.h * 0.68;
    const sx = 1, sy = Math.cos(tilt), sz = Math.sin(tilt);
    const spread = Math.min(this.w * 1.05, this.h * 1.9);
    const X = (u - 0.5) * spread;
    const Yv = (v - 0.5) * spread * 0.42;
    const Z = y;
    const rx = X;
    const ry = Yv * sy - Z * sz;
    const rz = Yv * sz + Z * sy + spread * 1.55;
    const f = spread * 1.35;
    const k = f / (f + rz);
    return { x: cx + rx * k, y: cy + ry * k - spread * 0.16, k };
  }
  _loop() {
    const step = () => {
      const t = (performance.now() - this._t0) / 1000;
      const ctx = this.ctx;
      ctx.clearRect(0, 0, this.w, this.h);
      const tilt = 0.62 + Math.sin(this.scroll * Math.PI) * 0.10;   // camera eases down
      const spin = this.scroll * 0.5;                                // slight yaw

      // sky / ground gradient
      const sky = ctx.createLinearGradient(0, 0, 0, this.h);
      sky.addColorStop(0, "rgba(12,20,40,0.9)");
      sky.addColorStop(0.55, this.dust > 0.35 ? "rgba(120,86,40,0.45)" : "rgba(20,28,48,0.5)");
      sky.addColorStop(1, "rgba(30,22,12,0.85)");
      ctx.fillStyle = sky; ctx.fillRect(0, 0, this.w, this.h);

      // the sun
      const sunIntensity = 1 - this.dust * 0.75;
      const sxp = this.w * 0.78, syp = this.h * 0.16;
      const glow = ctx.createRadialGradient(sxp, syp, 2, sxp, syp, 150);
      glow.addColorStop(0, `rgba(255,240,200,${0.85 * sunIntensity + 0.1})`);
      glow.addColorStop(0.35, `rgba(255,190,90,${0.28 * sunIntensity})`);
      glow.addColorStop(1, "rgba(255,190,90,0)");
      ctx.fillStyle = glow; ctx.beginPath(); ctx.arc(sxp, syp, 150, 0, 7); ctx.fill();

      // ground plane (desert)
      ctx.beginPath();
      const g0 = this._project(0, 0, 0, tilt), g1 = this._project(1, 0, 0, tilt);
      const g2 = this._project(1, 1, 0, tilt), g3 = this._project(0, 1, 0, tilt);
      ctx.moveTo(g0.x, g0.y + 40); ctx.lineTo(g1.x, g1.y + 40);
      ctx.lineTo(g2.x, g2.y + 140); ctx.lineTo(g3.x, g3.y + 140); ctx.closePath();
      const gg = ctx.createLinearGradient(0, this.h * 0.5, 0, this.h);
      gg.addColorStop(0, "rgba(120,92,52,0.55)"); gg.addColorStop(1, "rgba(48,36,20,0.9)");
      ctx.fillStyle = gg; ctx.fill();

      const cellW = 1 / this.cols, cellH = 1 / this.rows;
      const modules = [];
      for (let r = 0; r < this.rows; r++) {
        for (let c = 0; c < this.cols; c++) {
          const u = c * cellW + cellW * 0.04;
          const v = r * cellH + cellH * 0.12;
          const quad = [
            this._project(u + spin * 0.0, v, 0.0, tilt),
            this._project(u + cellW * 0.92, v, 0.0, tilt),
            this._project(u + cellW * 0.92, v + cellH * 0.66, 0.0, tilt),
            this._project(u, v + cellH * 0.66, 0.0, tilt),
          ];
          modules.push({ r, c, quad, depth: quad[0].k });
        }
      }
      modules.sort((a, b) => a.depth - b.depth);       // painter's algorithm

      for (const m of modules) {
        const [a, b, c2, d] = m.quad;
        // wipe: cells to the left of the cleaning bar are clean again
        const cleanHere = this.wipe > 0 && (m.c / this.cols) < this.wipe;
        const dust = cleanHere ? this.dust * 0.08 : this.dust;
        const glass = 12 + 42 * (1 - dust);
        ctx.beginPath();
        ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.lineTo(c2.x, c2.y); ctx.lineTo(d.x, d.y); ctx.closePath();
        const grad = ctx.createLinearGradient(a.x, a.y, c2.x, c2.y);
        grad.addColorStop(0, `rgba(${28 + dust * 120}, ${48 + dust * 80}, ${92 - dust * 40}, ${0.92 - dust * 0.18})`);
        grad.addColorStop(0.5, `rgba(${16 + dust * 96}, ${34 + dust * 60}, ${70 - dust * 30}, 0.9)`);
        grad.addColorStop(1, `rgba(${22 + dust * 120}, ${40 + dust * 70}, ${84 - dust * 40}, ${0.9 - dust * 0.2})`);
        ctx.fillStyle = grad; ctx.fill();
        ctx.strokeStyle = `rgba(${190 - glass}, ${210 - glass}, 240, ${0.45 - dust * 0.25})`;
        ctx.lineWidth = 1; ctx.stroke();

        // dust speckle on the glass, deterministic per cell
        if (dust > 0.04) {
          const seed = m.r * 31 + m.c * 17;
          for (let s = 0; s < 12; s++) {
            const sx = Math.sin(seed + s * 3.7) * 0.5 + 0.5;
            const sy = Math.sin(seed * 1.3 + s * 5.1) * 0.5 + 0.5;
            const u = a.x + (b.x - a.x) * sx + (d.x - a.x) * sy;
            const v = a.y + (b.y - a.y) * sx + (d.y - a.y) * sy;
            ctx.globalAlpha = dust * 0.5 * (0.3 + (s % 5) / 5);
            ctx.fillStyle = s % 3 ? "#e0b878" : "#c9974f";
            ctx.beginPath(); ctx.arc(u, v, 0.7 + (s % 3) * 0.35, 0, 6.283); ctx.fill();
          }
          ctx.globalAlpha = 1;
        }
        // highlight sheen where the sun reflects
        ctx.globalAlpha = 0.10 * (1 - dust);
        ctx.beginPath();
        ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y);
        ctx.lineTo(d.x + (c2.x - b.x) * 0.25, d.y + (c2.y - b.y) * 0.25);
        ctx.closePath();
        ctx.fillStyle = "#fff6dd"; ctx.fill(); ctx.globalAlpha = 1;
      }

      // cleaning bar sweeping across after the storm
      if (this.wipe > 0 && this.wipe < 1) {
        const bar = this._project(clamp(this.wipe, 0, 1), 0, 0.02, tilt);
        const bar2 = this._project(clamp(this.wipe, 0, 1), 1, 0.02, tilt);
        ctx.beginPath(); ctx.moveTo(bar.x, bar.y); ctx.lineTo(bar2.x, bar2.y);
        ctx.strokeStyle = "rgba(140,240,255,0.85)"; ctx.lineWidth = 3;
        ctx.shadowColor = "#37e0ff"; ctx.shadowBlur = 18; ctx.stroke(); ctx.shadowBlur = 0;
      }

      // airborne sand motes, stronger when dirty
      for (const p of this.motes) {
        p.x += p.s * (0.6 + this.dust * 2.4) / this.w;
        if (p.x > 1.05) { p.x = -0.03; p.y = Math.random(); }
        ctx.globalAlpha = (0.06 + this.dust * 0.4) * 0.8;
        ctx.fillStyle = p.r > 1.2 ? "#ffcd6b" : "#e0b878";
        ctx.beginPath();
        ctx.arc(p.x * this.w, p.y * this.h + Math.sin(t + p.y * 8) * 4, p.r, 0, 6.283);
        ctx.fill();
      }
      ctx.globalAlpha = 1;

      // HUD
      const loss = (this.dust * 34) / 1;
      ctx.font = "600 12px ui-monospace, monospace";
      ctx.fillStyle = "rgba(234,241,255,0.9)";
      ctx.fillText(`SOILING ${loss.toFixed(1)}%`, 16, 24);
      ctx.fillStyle = this.dust > 0.45 ? "#ff5f6d" : "#3ddc97";
      ctx.fillText(`OUTPUT ${(100 - loss).toFixed(1)}% of clean`, 16, 42);
      ctx.fillStyle = "rgba(127,141,171,0.9)";
      ctx.fillText(this.wipe > 0 ? "CLEANING" : this.dust > 0.6 ? "DUST STORM" : "ACCUMULATING", 16, 60);

      requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  }
}
