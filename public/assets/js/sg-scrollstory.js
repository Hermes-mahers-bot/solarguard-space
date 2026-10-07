/* ============================================================================
   sg-scrollstory.js — SolarGuard cinematic scroll storyboard.

   A single canvas-2D scene with its own 3D -> 2D projection maths (no three.js,
   no CDN, no external assets). The page owns the scroll and pushes a 0..1
   progress in; the scene turns that into a day:

         0.00 ─ 0.10   DAWN        sun low left, glass clean, tracker steep
         0.10 ─ 0.45   DAY         sun climbs, trackers flatten, dirt builds
         0.30 ─ 0.68   STORM       dust front rolls in left -> right
         0.58 ─ 0.72   PEAK        ochre sky, sun bloom dies, array buried
         0.72 ─ 1.00   CLEANING    wash bar sweeps L->R, glass clears, sky opens

   Real API numbers can be pushed in with setData(); if they never arrive the
   HUD interpolates from progress instead.

   Usage
       import { createScrollStory } from "./assets/js/sg-scrollstory.js";
       const story = createScrollStory(canvas, { siteName: "DAMMAM / EASTERN PROV" });
       addEventListener("scroll", () => story.setProgress(scrollY / maxScroll), { passive: true });
       story.setData({ soilingLossPct: 12.4, outputPct: 87.6, dustUgm3: 138, siteName: "…" });
       story.start();      // one rAF loop, forever
       story.resize();     // only on real viewport changes
       story.destroy();    // page unload

   Public API: setProgress(p, instant) · setData(obj) · start() · stop() · resize()
               destroy() · getProgress() · isRunning() · isReduced()
   ============================================================================ */

/* ------------------------------------------------------------- tiny maths */
const clamp = (v, a, b) => (v < a ? a : v > b ? b : v);
const lerp = (a, b, t) => a + (b - a) * t;
const smoothstep = (e0, e1, x) => {
  const t = clamp((x - e0) / (e1 - e0 || 1e-6), 0, 1);
  return t * t * (3 - 2 * t);
};
const easeInOut = (t) => (t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2);
/* deterministic hash -> 0..1, so per-module speckle is stable frame to frame */
const hash = (n) => {
  const s = Math.sin(n * 127.1 + 311.7) * 43758.5453123;
  return s - Math.floor(s);
};
const mixCol = (a, b, t) => [
  Math.round(lerp(a[0], b[0], t)),
  Math.round(lerp(a[1], b[1], t)),
  Math.round(lerp(a[2], b[2], t)),
];
const rgba = (c, a) => `rgba(${c[0]},${c[1]},${c[2]},${a})`;

/* Keyframe gradient stops for the sky, indexed by progress. */
const SKY_KEYS = [
  // p,    zenith,        mid,           horizon
  { p: 0.00, z: [9, 14, 34], m: [58, 40, 58], h: [216, 138, 70] }, // dawn
  { p: 0.30, z: [7, 20, 52], m: [30, 66, 110], h: [206, 164, 104] }, // day
  { p: 0.55, z: [58, 38, 22], m: [140, 96, 44], h: [214, 160, 86] }, // dust arriving
  { p: 0.72, z: [96, 63, 30], m: [162, 112, 52], h: [198, 148, 80] }, // storm
  { p: 1.00, z: [12, 15, 38], m: [74, 45, 62], h: [228, 140, 74] }, // clear dusk
];

/* ---------------------------------------------------------- the factory */
export function createScrollStory(canvas, opts = {}) {
  if (!canvas || typeof canvas.getContext !== "function") {
    throw new Error("createScrollStory(canvas): a <canvas> element is required");
  }
  const ctx = canvas.getContext("2d", { alpha: false });
  if (!ctx) throw new Error("createScrollStory: canvas 2D context unavailable");

  /* design tokens (mirror of --sand/--cyan/--ink/--dim in solarguard.css) */
  const C = {
    bg: "#04060c", sand: "#f3a72b", sand2: "#ffcd6b", sandDeep: "#b9721a",
    cyan: "#37e0ff", cyan2: "#8ff2ff", ink: "#eaf1ff", dim: "#7f8dab",
    green: "#3ddc97", red: "#ff5f6d", amber: "#ffb020",
  };

  /* ---- tunables (see docs/SCROLL_STORY.md for how to retune) ---- */
  const CFG = {
    dprCap: opts.dprCap || 1.5,          // cap the backing store; 1.5 is our budget
    smooth: opts.smooth !== false,       // damp scroll jitter
    siteName: opts.siteName || "DAMMAM / EASTERN PROV",
    staticProgress: typeof opts.staticProgress === "number" ? opts.staticProgress : 0.42,
    // the churning storm mass reads as out-of-focus bokeh if it is too large or
    // too opaque; both are tunable from the page
    blobScale: opts.blobScale || 0.7,
    blobAlpha: opts.blobAlpha || 0.72,
    hudTop: typeof opts.hudTop === "number" ? opts.hudTop : 26,   // clear the fixed nav
    hudLeft: typeof opts.hudLeft === "number" ? opts.hudLeft : 16,
  };
  const PHASE = {
    dayFull: 0.95,       // sun reaches its highest point at p ~ 0.475
    stormStart: 0.26,    // dirt starts to build once the day is up
    stormFull: 0.64,     // fully buried by here
    frontStart: 0.40,
    frontEnd: 0.70,      // the wall crosses the array around p ~ 0.6
    cleanStart: 0.72,
    cleanEnd: 0.95,      // the bar clears the array just before the end
  };
  /* camera: parked in front of the array, tilted down a few degrees */
  const CAM = { x: -2.5, y: 5.2, z: -13.5, yaw: -0.07, pitch: 0.115 };
  const MAX_TILT = 0.62;                 // rad (~36°), single-axis tracker travel
  const MIN_TILT = -0.10;                // rad, never let the glass face away from camera
  const PIVOT_Y = 0.62;                  // module height above ground at the torque tube

  /* ---- live state ---- */
  let W = 0, H = 0, CX = 0, CY = 0, dpr = 1, focal = 0, horizonY = 0;
  let progress = CFG.staticProgress;
  let target = CFG.staticProgress;
  let dustLevel = 0, stormAmt = 0, cleanT = 0, frontP = 0;
  let sunAz = 0, sunEl = 0, sunDirX = 0, sunDirY = 0;
  let trackerT = 1;
  let data = null;                        // set via setData()
  let rows = 6, cols = 5, halfX = 8.6;    // array footprint, rebuilt on resize
  let modules = [];
  let motes = [];                         // airborne dust
  let spray = [];                         // cleaning-pass droplets
  let blobs = [];                         // churning storm-front mass
  let bushes = [];                        // static ground detail (world coords)
  let running = false, raf = 0, lastT = 0, elapsed = 0;
  let destroyed = false;
  let reduced = false;
  let mq = null;
  let heave = 0;                          // gentle breathing offset (time based)

  /* ================================================================ sizing */
  function resize() {
    if (destroyed) return;
    /* read the DOM exactly once per resize — never inside the render loop */
    const cw = canvas.clientWidth || canvas.parentElement?.clientWidth || 640;
    const ch = canvas.clientHeight || canvas.parentElement?.clientHeight || 420;
    W = Math.max(120, Math.round(cw));
    H = Math.max(120, Math.round(ch));
    dpr = Math.min(window.devicePixelRatio || 1, CFG.dprCap);
    canvas.width = Math.round(W * dpr);
    canvas.height = Math.round(H * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    CX = W * 0.5;
    CY = H * 0.5;
    focal = H * 1.15;                     // ~53° horizontal FOV at 16:9, tighter when tall
    const mobile = W < 640;
    /* array geometry adapts to the viewport: 5 rows on a phone, 6 on desktop */
    if (mobile) { rows = 5; cols = 6; halfX = 5.2; }
    else { rows = 6; cols = 5; halfX = 9.3; }
    buildModules();
    buildBushes();
    buildParticles();
    const far = project(0, 0, 100000);
    horizonY = far ? far.y : CY;
  }

  function buildModules() {
    modules = [];
    const z0 = 2.6, z1 = 14.4;
    const stepZ = (z1 - z0) / cols;
    const stepX = (halfX * 2) / rows;
    const hw = stepX * 0.46;              // half width along x
    const hl = stepZ * 0.44;              // half length along z
    for (let r = 0; r < rows; r++) {
      const x = -halfX + stepX * 0.5 + r * stepX;
      for (let c = 0; c < cols; c++) {
        const z = z0 + stepZ * 0.5 + c * stepZ;
        modules.push({
          x, z, hw, hl, r, c,
          /* stable per-module seeds: speckle, sheen jitter, row desync */
          seed: (r * 17 + c * 31) * 0.7853 + r * 2.1,
          speck: 0.35 + hash(r * 13.3 + c * 7.7) * 0.65,
          phase: hash(r * 5.1 + c * 2.3) * Math.PI * 2,
          cor: null, cx2: 0, cy2: 0, depth: 0, tM: 0, dustM: 0, swept: 0,
        });
      }
    }
  }

  function buildBushes() {
    bushes = [];
    const n = W < 640 ? 18 : 40;
    for (let i = 0; i < n; i++) {
      const bx = lerp(-halfX * 2.6, halfX * 2.6, hash(i * 3.1));
      const bz = lerp(-3.0, 26, hash(i * 9.7 + 1));
      bushes.push({ x: bx, z: bz, s: 0.030 + hash(i * 4.4) * 0.045, dark: hash(i * 8.2) });
    }
  }

  function buildParticles() {
    /* particle budget scales with area and halves on phone-width canvases */
    const area = W * H;
    let n = clamp(Math.round(area / 9000), 30, 190);
    if (W < 640) n = Math.round(n * 0.5);
    motes = [];
    for (let i = 0; i < n; i++) {
      motes.push({
        x: hash(i * 1.7) * 1.1 - 0.05,
        y: hash(i * 5.3 + 2) * 1.05,
        z: 0.25 + hash(i * 9.1 + 4) * 0.75,      // depth: speed + size + parallax
        s: 0.4 + hash(i * 2.9 + 6) * 1.9,
        ph: hash(i * 6.1 + 8) * 6.283,
      });
    }
    spray = [];
    for (let i = 0; i < 22; i++) spray.push({ t: 0, life: 0.6 + hash(i) * 0.5, vy: 0, vx: 0, r: 0, on: false });
    blobs = [];
    const nb = W < 640 ? 12 : 22;
    for (let i = 0; i < nb; i++) {
      blobs.push({ ox: hash(i * 3.7) * 0.5, y: hash(i * 7.9) * 0.95, r: 0.018 + hash(i * 2.2) * 0.055, ph: hash(i * 5.5) * 6.283, sp: 0.1 + hash(i * 4.1) * 0.3 });
    }
  }

  /* ============================================================ projection */
  /* world axes: +x right (east/west), +y up, +z away from camera.
     camera parked at CAM, yawed slightly then pitched down. Classic
     pinhole: rotate, translate, divide by depth. */
  function project(x, y, z) {
    const dx = x - CAM.x, dy = y - CAM.y, dz = z - CAM.z;
    const cyw = Math.cos(CAM.yaw), syw = Math.sin(CAM.yaw);
    const x1 = dx * cyw + dz * syw;
    const z1 = -dx * syw + dz * cyw;
    const cp = Math.cos(CAM.pitch), sp = Math.sin(CAM.pitch);
    const y2 = dy * cp + z1 * sp;
    const z2 = -dy * sp + z1 * cp;
    if (z2 < 0.35) return null;
    const k = focal / z2;
    return { x: CX + x1 * k, y: CY - y2 * k, k, z: z2 };
  }
  /* project a direction (unit-ish) from the camera — used for the sun */
  function projectDir(dx, dy, dz) {
    const cyw = Math.cos(CAM.yaw), syw = Math.sin(CAM.yaw);
    const x1 = dx * cyw + dz * syw;
    const z1 = -dx * syw + dz * cyw;
    const cp = Math.cos(CAM.pitch), sp = Math.sin(CAM.pitch);
    const y2 = dy * cp + z1 * sp;
    const z2 = -dy * sp + z1 * cp;
    if (z2 < 1e-4) return null;
    return { x: CX + (focal * x1) / z2, y: CY - (focal * y2) / z2 };
  }

  /* ========================================================== day / phases */
  function updateDay(p) {
    const d = clamp(p / PHASE.dayFull, 0, 1);
    /* apparent sun elevation — compressed so the arc fits the frame */
    const arc = Math.pow(Math.sin(Math.PI * d), 0.9);
    sunEl = (1.6 + 11.4 * arc) * (Math.PI / 180);
    sunAz = lerp(-25, 28, easeInOut(clamp(p, 0, 1))) * (Math.PI / 180);
    sunDirX = Math.sin(sunAz) * Math.cos(sunEl);
    sunDirY = Math.sin(sunEl);
    trackerT = arc;                                     // 0 dawn/dusk … 1 noon
    /* dust budget */
    const acc = smoothstep(PHASE.stormStart, PHASE.stormFull, p);
    /* <1 exponent: the bar starts quickly and eases out as it reaches the far
       corner, which keeps the pass legible in the middle of the scroll */
    cleanT = Math.pow(smoothstep(PHASE.cleanStart, PHASE.cleanEnd, p), 0.7);
    dustLevel = acc;
    stormAmt = acc * (1 - cleanT * 0.94);
    frontP = smoothstep(PHASE.frontStart, PHASE.frontEnd, p);
  }

  function trackerAngle(m) {
    const sgn = Math.tanh(Math.sin(sunAz) * 6);
    /* Magnitude falls to ~0 at noon; the sign follows the sun's azimuth but is
       clamped so the array never presents its back edge to the camera — the
       glass has to stay readable for the whole story. */
    const base = clamp(-sgn * MAX_TILT * (1 - 0.94 * trackerT), MIN_TILT, MAX_TILT);
    /* a hair of per-module desync keeps rows from looking welded together */
    return base + Math.sin(elapsed * 0.6 + m.phase) * 0.012;
  }

  /* =============================================================== pieces */
  function skyColours(p) {
    let a = SKY_KEYS[0], b = SKY_KEYS[SKY_KEYS.length - 1];
    for (let i = 0; i < SKY_KEYS.length - 1; i++) {
      if (p >= SKY_KEYS[i].p && p <= SKY_KEYS[i + 1].p) { a = SKY_KEYS[i]; b = SKY_KEYS[i + 1]; break; }
      if (p > SKY_KEYS[SKY_KEYS.length - 1].p) { a = b = SKY_KEYS[SKY_KEYS.length - 1]; }
    }
    const t = b.p === a.p ? 0 : smoothstep(a.p, b.p, p);
    return {
      z: mixCol(a.z, b.z, t),
      m: mixCol(a.m, b.m, t),
      h: mixCol(a.h, b.h, t),
    };
  }

  function drawSky(p) {
    const c = skyColours(p);
    const g = ctx.createLinearGradient(0, 0, 0, Math.max(horizonY + 4, 8));
    g.addColorStop(0, rgba(c.z, 1));
    g.addColorStop(0.55, rgba(c.m, 1));
    g.addColorStop(1, rgba(c.h, 1));
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, W, Math.max(horizonY + 4, 8));
    /* the ground below the horizon is painted later; fill it with the deep
       sand base so there is never a transparent gap. */
    const gg = ctx.createLinearGradient(0, horizonY, 0, H);
    gg.addColorStop(0, rgba(mixCol(c.h, [206, 162, 102], 0.40), 1));
    gg.addColorStop(0.16, rgba(mixCol(c.h, [160, 118, 70], 0.45), 1));
    gg.addColorStop(0.55, "rgb(104,76,45)");
    gg.addColorStop(1, "rgb(38,28,17)");
    ctx.fillStyle = gg;
    ctx.fillRect(0, horizonY, W, H - horizonY + 1);
  }

  function drawSunGlow() {
    const dir = projectDir(sunDirX, sunDirY, Math.cos(sunAz) * Math.cos(sunEl));
    if (!dir) return null;
    const dim = 1 - Math.min(0.86, dustLevel * 0.86);
    const R = clamp(H * 0.30, 120, 380);
    ctx.save();
    ctx.globalCompositeOperation = "lighter";
    /* wide halo */
    const halo = ctx.createRadialGradient(dir.x, dir.y, 2, dir.x, dir.y, R);
    halo.addColorStop(0, `rgba(255,244,214,${0.55 * dim + 0.06})`);
    halo.addColorStop(0.18, `rgba(255,207,120,${0.26 * dim})`);
    halo.addColorStop(0.5, `rgba(255,170,74,${0.09 * dim})`);
    halo.addColorStop(1, "rgba(255,150,60,0)");
    ctx.fillStyle = halo;
    ctx.beginPath(); ctx.arc(dir.x, dir.y, R, 0, 6.2832); ctx.fill();
    /* tight bloom */
    const bloom = ctx.createRadialGradient(dir.x, dir.y, 0, dir.x, dir.y, R * 0.22);
    bloom.addColorStop(0, `rgba(255,252,240,${0.95 * dim + 0.05})`);
    bloom.addColorStop(0.45, `rgba(255,222,150,${0.5 * dim})`);
    bloom.addColorStop(1, "rgba(255,200,110,0)");
    ctx.fillStyle = bloom;
    ctx.beginPath(); ctx.arc(dir.x, dir.y, R * 0.22, 0, 6.2832); ctx.fill();
    /* anamorphic streak + disc */
    const streak = ctx.createLinearGradient(dir.x - R * 0.9, dir.y, dir.x + R * 0.9, dir.y);
    streak.addColorStop(0, "rgba(255,220,160,0)");
    streak.addColorStop(0.5, `rgba(255,240,205,${0.30 * dim})`);
    streak.addColorStop(1, "rgba(255,220,160,0)");
    ctx.fillStyle = streak;
    ctx.fillRect(dir.x - R * 0.9, dir.y - H * 0.006, R * 1.8, H * 0.012);
    ctx.fillStyle = `rgba(255,252,242,${0.9 * dim + 0.08})`;
    ctx.beginPath(); ctx.arc(dir.x, dir.y, clamp(H * 0.016, 7, 22), 0, 6.2832); ctx.fill();
    /* lens bloom ghosts along the sun->centre axis (they die in the dust) */
    if (dim > 0.25) {
      const gx = CX + (dir.x - CX) * -1.15, gy = CY + (dir.y - CY) * -1.15;
      ctx.globalCompositeOperation = "screen";
      ctx.fillStyle = `rgba(120,190,255,${0.05 * dim})`;
      ctx.beginPath(); ctx.arc(gx, gy, R * 0.16, 0, 6.2832); ctx.fill();
      ctx.fillStyle = `rgba(255,190,120,${0.05 * dim})`;
      ctx.beginPath(); ctx.arc(CX + (dir.x - CX) * 0.45, CY + (dir.y - CY) * 0.45, R * 0.07, 0, 6.2832); ctx.fill();
    }
    ctx.restore();
    return dir;
  }

  function drawDunes() {
    /* Far dunes sit behind the array (z >= 18); near dunes sit in front
       (z <= -2). The depth split keeps the array unoccluded. */
    const far = [
      { z: 74, amp: 9, freq: 0.0052, col: [196, 152, 98], a: 0.55 },
      { z: 38, amp: 15, freq: 0.0038, col: [166, 124, 74], a: 0.6 },
      { z: 19, amp: 20, freq: 0.003, col: [134, 98, 58], a: 0.68 },
    ];
    for (const d of far) {
      const base = project(0, 0, d.z);
      if (!base) continue;
      const y0 = base.y + heave * 2 * (1 - d.z / 200);
      ridgePath(y0, d.amp, d.freq, d.z * 0.7);
      ctx.fillStyle = rgba(d.col, d.a);
      ctx.fill();
    }
    return far;
  }

  function drawNearDunes() {
    const near = [
      { z: -2, amp: 22, freq: 0.0026, col: [86, 62, 38], a: 0.82 },
      { z: -4.2, amp: 30, freq: 0.0019, col: [58, 42, 26], a: 0.92 },
    ];
    for (const d of near) {
      const base = project(0, 0, d.z);
      if (!base) continue;
      ridgePath(base.y + heave * 1.5, d.amp, d.freq, d.z * 1.3);
      ctx.fillStyle = rgba(d.col, d.a);
      ctx.fill();
    }
  }

  function ridgePath(y0, amp, freq, phase) {
    ctx.beginPath();
    ctx.moveTo(-4, y0 - amp * (0.6 * Math.sin(-4 * freq + phase) + 0.4 * Math.sin(-4 * freq * 2.3 + phase * 1.7)));
    for (let x = 0; x <= W + 4; x += 12) {
      const y = y0 + amp * (0.6 * Math.sin(x * freq + phase) + 0.4 * Math.sin(x * freq * 2.3 + phase * 1.7));
      ctx.lineTo(x, y);
    }
    ctx.lineTo(W + 4, H + 8);
    ctx.lineTo(-4, H + 8);
    ctx.closePath();
  }

  function drawGroundDetail() {
    /* a few scrub bushes for scale and parallax — deliberately tiny */
    for (const b of bushes) {
      const p = project(b.x, 0, b.z);
      if (!p) continue;
      const s = clamp(b.s * p.k * 1.15, 0.5, 5.5);
      const cx2 = p.x, cy2 = p.y;
      const fade = clamp(1.15 - b.z / 34, 0.25, 1);   // distant shrubs sink into haze
      ctx.globalAlpha = fade;
      /* contact shadow */
      ctx.fillStyle = "rgba(20,13,5,0.34)";
      ctx.beginPath(); ctx.ellipse(cx2, cy2, s * 1.9, s * 0.62, 0, 0, 6.2832); ctx.fill();
      ctx.fillStyle = `rgba(${58 + b.dark * 26},${48 + b.dark * 20},${27 + b.dark * 12},0.8)`;
      ctx.beginPath(); ctx.ellipse(cx2, cy2 - s * 0.9, s, s * 0.86, 0, 0, 6.2832); ctx.fill();
      ctx.globalAlpha = 1;
    }
  }

  function drawArrayShadow() {
    /* one long soft shadow slab under the whole array, direction + length
       driven by the sun. Reads as the array's own cast shadow. */
    const elr = Math.max(0.02, sunEl);
    const stretch = clamp(1.15 / Math.tan(elr), 1.0, 5.4);
    const offX = -Math.sin(sunAz) * stretch * 1.15;
    const offZ = -0.30 * stretch;
    const x0 = -halfX - 0.5, x1 = halfX + 0.5, z0 = 1.5, z1 = 15.4;
    const quad = [
      [x0, z0], [x1, z0], [x1 + offX, z1 + offZ], [x0 + offX, z1 + offZ],
    ].map(([x, z]) => project(x, 0.015, z));
    if (quad.some((q) => !q)) return;
    /* soften on wide canvases (one blurred fill); plain alpha on phones */
    const canBlur = W >= 640 && "filter" in ctx;
    ctx.beginPath();
    ctx.moveTo(quad[0].x, quad[0].y);
    for (let i = 1; i < 4; i++) ctx.lineTo(quad[i].x, quad[i].y);
    ctx.closePath();
    ctx.fillStyle = "rgba(18,11,4,0.22)";
    if (canBlur) { ctx.save(); ctx.filter = "blur(16px)"; }
    ctx.fill();
    if (canBlur) { ctx.restore(); ctx.filter = "none"; }
  }

  function drawArray() {
    /* --- transform every module once --- */
    let minX = Infinity, maxX = -Infinity;
    for (const m of modules) {
      const rho = trackerAngle(m);
      const cr = Math.cos(rho), sr = Math.sin(rho);
      const corners = [
        [m.x - m.hw, m.z - m.hl],
        [m.x + m.hw, m.z - m.hl],
        [m.x + m.hw, m.z + m.hl],
        [m.x - m.hw, m.z + m.hl],
      ].map(([ux, uz]) => {
        const X = m.x + (ux - m.x) * cr;
        const Y = PIVOT_Y + (ux - m.x) * sr;
        return project(X, Y, uz);
      });
      if (corners.some((c) => !c)) { m.cor = null; continue; }
      m.cor = corners;
      m.cx2 = (corners[0].x + corners[2].x) * 0.5;
      m.cy2 = (corners[0].y + corners[2].y) * 0.5;
      m.depth = (corners[0].z + corners[1].z + corners[2].z + corners[3].z) * 0.25;
      if (m.cx2 < minX) minX = m.cx2;
      if (m.cx2 > maxX) maxX = m.cx2;
    }
    /* --- sweep line in projected space: cleaning is left -> right --- */
    const sweepX = minX + (maxX - minX) * cleanT;
    const washerOn = cleanT > 0.0001 && cleanT < 0.9999;
    for (const m of modules) {
      if (!m.cor) continue;
      /* how far past the bar this module is (0 = dirty, 1 = washed) */
      m.swept = smoothstep(sweepX - 26, sweepX + 26, m.cx2);
      m.dustM = stormAmt * (1 - m.swept * 0.94);
    }
    /* --- painter's algorithm: far modules first --- */
    const order = modules.filter((m) => m.cor).sort((a, b) => b.depth - a.depth);

    const sheenT = clamp(0.5 + Math.sin(sunAz) * 1.5, 0.06, 0.94);
    for (const m of order) {
      const q = m.cor, d = m.dustM;
      const a = q[0], b = q[1], c2 = q[2], e = q[3];

      /* frame: dark surround, slightly proud of the glass */
      ctx.beginPath();
      ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.lineTo(c2.x, c2.y); ctx.lineTo(e.x, e.y);
      ctx.closePath();
      ctx.fillStyle = `rgb(${10 + d * 34},${13 + d * 26},${18 + d * 16})`;
      ctx.fill();
      ctx.strokeStyle = `rgba(${168 + d * 40},${178 + d * 30},${196 - d * 30},${0.5 - d * 0.18})`;
      ctx.lineWidth = 1.1;
      ctx.stroke();

      /* glass, inset from the frame */
      const inset = 0.86;
      const ic = [
        bl(a, b, c2, e, 0.5 - 0.5 * inset, 0.5 - 0.5 * inset),
        bl(a, b, c2, e, 0.5 + 0.5 * inset, 0.5 - 0.5 * inset),
        bl(a, b, c2, e, 0.5 + 0.5 * inset, 0.5 + 0.5 * inset),
        bl(a, b, c2, e, 0.5 - 0.5 * inset, 0.5 + 0.5 * inset),
      ];
      ctx.beginPath();
      ctx.moveTo(ic[0].x, ic[0].y);
      for (let i = 1; i < 4; i++) ctx.lineTo(ic[i].x, ic[i].y);
      ctx.closePath();
      /* deep blue silicon -> ochre as dust settles */
      const g = ctx.createLinearGradient(ic[0].x, ic[0].y, ic[2].x, ic[2].y);
      g.addColorStop(0, `rgb(${Math.round(30 + d * 170)},${Math.round(74 + d * 80)},${Math.round(164 - d * 96)})`);
      g.addColorStop(0.55, `rgb(${Math.round(18 + d * 150)},${Math.round(48 + d * 74)},${Math.round(118 - d * 52)})`);
      g.addColorStop(1, `rgb(${Math.round(26 + d * 160)},${Math.round(62 + d * 82)},${Math.round(146 - d * 76)})`);
      ctx.fillStyle = g;
      ctx.fill();

      /* freshly washed glass flashes cyan as the bar passes over it */
      const fresh = 1 - Math.abs(m.swept * 2 - 1);
      if (fresh > 0.02) {
        ctx.fillStyle = `rgba(150,240,255,${0.26 * fresh})`;
        ctx.beginPath();
        ctx.moveTo(ic[0].x, ic[0].y);
        for (let i = 1; i < 4; i++) ctx.lineTo(ic[i].x, ic[i].y);
        ctx.closePath(); ctx.fill();
      }
      /* washed modules keep a cool cast, so the swept half of the array reads
         instantly different from the ochre half still under the storm */
      if (m.swept > 0.12) {
        ctx.fillStyle = `rgba(150,214,255,${0.13 * m.swept})`;
        ctx.beginPath();
        ctx.moveTo(ic[0].x, ic[0].y);
        for (let i = 1; i < 4; i++) ctx.lineTo(ic[i].x, ic[i].y);
        ctx.closePath(); ctx.fill();
      }

      /* cell grid drawn by bilinear interpolation of the projected corners,
         so the cells follow perspective and the module's tilt */
      ctx.strokeStyle = `rgba(${196 - d * 60},${212 - d * 60},${236 - d * 70},${0.30 - d * 0.19})`;
      ctx.lineWidth = 0.8;
      ctx.beginPath();
      const CN = 4, RN = 2;
      for (let i = 1; i < CN; i++) {
        const s = i / CN;
        const p1 = bl(a, b, c2, e, s, 0.07), p2 = bl(a, b, c2, e, s, 0.93);
        ctx.moveTo(p1.x, p1.y); ctx.lineTo(p2.x, p2.y);
      }
      for (let j = 1; j < RN; j++) {
        const t = j / RN;
        const p1 = bl(a, b, c2, e, 0.07, t), p2 = bl(a, b, c2, e, 0.93, t);
        ctx.moveTo(p1.x, p1.y); ctx.lineTo(p2.x, p2.y);
      }
      ctx.stroke();

      /* per-module deterministic speckle — stable, no flicker */
      if (d > 0.035) {
        ctx.fillStyle = d > 0.5 ? "#d8a45f" : "#c9974f";
        const n = 5 + Math.round(m.speck * 7);
        for (let k = 0; k < n; k++) {
          const sx = hash(m.seed + k * 1.93);
          const sy = hash(m.seed * 1.7 + k * 4.31);
          const p = bl(a, b, c2, e, 0.08 + sx * 0.84, 0.08 + sy * 0.84);
          ctx.globalAlpha = d * m.speck * (0.28 + hash(m.seed + k) * 0.42);
          ctx.beginPath(); ctx.arc(p.x, p.y, 0.6 + hash(m.seed * 2 + k) * 1.5, 0, 6.2832); ctx.fill();
        }
        ctx.globalAlpha = 1;
        /* a dull ochre film over the whole pane as it gets buried */
        ctx.fillStyle = `rgba(206,150,74,${0.30 * d * m.speck})`;
        ctx.beginPath();
        ctx.moveTo(ic[0].x, ic[0].y);
        for (let i = 1; i < 4; i++) ctx.lineTo(ic[i].x, ic[i].y);
        ctx.closePath(); ctx.fill();
      }

      /* specular sheen — a soft band whose position tracks the sun */
      if (d < 0.85) {
        const s0 = clamp(sheenT - 0.16, 0.02, 0.96), s1 = clamp(sheenT + 0.16, 0.02, 0.96);
        const p1 = bl(a, b, c2, e, s0, 0.05), p2 = bl(a, b, c2, e, s1, 0.05);
        const p3 = bl(a, b, c2, e, s1, 0.95), p4 = bl(a, b, c2, e, s0, 0.95);
        ctx.globalAlpha = 0.20 * (1 - d) * (0.5 + trackerT * 0.5);
        ctx.fillStyle = "#fff6dd";
        ctx.beginPath();
        ctx.moveTo(p1.x, p1.y); ctx.lineTo(p2.x, p2.y); ctx.lineTo(p3.x, p3.y); ctx.lineTo(p4.x, p4.y);
        ctx.closePath(); ctx.fill();
        /* hot glint line */
        ctx.globalAlpha = 0.30 * (1 - d);
        ctx.strokeStyle = "#fffdf4";
        ctx.lineWidth = 1.1;
        ctx.beginPath();
        const g1 = bl(a, b, c2, e, sheenT, 0.06), g2 = bl(a, b, c2, e, sheenT, 0.94);
        ctx.moveTo(g1.x, g1.y); ctx.lineTo(g2.x, g2.y);
        ctx.stroke();
        ctx.globalAlpha = 1;
      }
    }
    /* live per-frame info the cleaning pass + HUD need */
    drawArray._minX = minX;
    drawArray._maxX = maxX;
    drawArray._sweepX = sweepX;
    drawArray._washerOn = washerOn;
    return { order };
  }

  /* bilinear interpolation across a projected quad (a,b,c2,e = corners) */
  function bl(a, b, c2, e, s, t) {
    const it = 1 - t;
    return {
      x: (1 - s) * it * a.x + s * it * b.x + s * t * c2.x + (1 - s) * t * e.x,
      y: (1 - s) * it * a.y + s * it * b.y + s * t * c2.y + (1 - s) * t * e.y,
    };
  }

  function drawWasher() {
    if (!drawArray._washerOn) return;
    const x = drawArray._sweepX;
    if (x < -W * 0.3 || x > W * 1.3) return;
    const yTop = horizonY + (H - horizonY) * 0.06;
    const yBot = H * 1.02;
    ctx.save();
    /* washed trail: the strip already swept reads brighter and cooler */
    const trail = ctx.createLinearGradient(x - W * 0.42, 0, x, 0);
    trail.addColorStop(0, "rgba(120,220,255,0.00)");
    trail.addColorStop(1, "rgba(150,235,255,0.10)");
    ctx.fillStyle = trail;
    ctx.fillRect(x - W * 0.42, horizonY, W * 0.42, H - horizonY);
    /* water/brush glint bar */
    const g = ctx.createLinearGradient(x - W * 0.075, 0, x + W * 0.075, 0);
    g.addColorStop(0, "rgba(55,224,255,0)");
    g.addColorStop(0.34, "rgba(143,242,255,0.34)");
    g.addColorStop(0.5, "rgba(245,255,255,0.90)");
    g.addColorStop(0.66, "rgba(143,242,255,0.34)");
    g.addColorStop(1, "rgba(55,224,255,0)");
    ctx.fillStyle = g;
    ctx.fillRect(x - W * 0.075, yTop, W * 0.15, yBot - yTop);
    ctx.strokeStyle = "rgba(200,250,255,0.95)";
    ctx.lineWidth = 3.0;
    ctx.shadowColor = "#37e0ff";
    ctx.shadowBlur = 26;
    ctx.beginPath(); ctx.moveTo(x, yTop); ctx.lineTo(x, yBot); ctx.stroke();
    ctx.shadowBlur = 0;
    /* brush head sweeping the plane */
    const headTop = horizonY + (H - horizonY) * 0.30;
    ctx.fillStyle = "rgba(226,252,255,0.85)";
    roundRect(x - 9, headTop, 18, 10, 3); ctx.fill();
    ctx.fillStyle = "rgba(120,220,255,0.5)";
    roundRect(x - 5, headTop + 9, 10, 8, 3); ctx.fill();
    /* spray kicked up by the brush */
    for (const s of spray) {
      if (!s.on) continue;
      if (elapsed - s.t > s.life) continue;
      const k = (elapsed - s.t) / s.life;
      const px = s.x0 + (s.x1 - s.x0) * k;
      const py = s.y0 + (s.y1 - s.y0) * k + 90 * k * k;
      ctx.globalAlpha = (1 - k) * 0.75;
      ctx.fillStyle = "#cdf3ff";
      ctx.beginPath(); ctx.arc(px, py, 1.4 + s.r * 2, 0, 6.2832); ctx.fill();
    }
    ctx.globalAlpha = 1;
    ctx.restore();
  }

  function emitSpray() {
    for (let i = 0; i < 2; i++) {
      const s = spray.find((p) => !p.on) || spray[i % spray.length];
      if (!s) continue;
      const x = drawArray._sweepX;
      const yTop = horizonY + (H - horizonY) * 0.16;
      s.on = true; s.t = elapsed; s.life = 0.5 + Math.random() * 0.5; s.r = Math.random();
      s.x0 = x + (Math.random() - 0.5) * 16;
      s.y0 = yTop + Math.random() * (H - yTop) * 0.7;
      s.x1 = s.x0 + 22 + Math.random() * 30;
      s.y1 = s.y0 - 16 - Math.random() * 40;
    }
  }

  function drawStorm() {
    if (stormAmt <= 0.004 && frontP <= 0.004) return;
    /* 1. layered parallax bands that thicken as the storm builds */
    const bands = 3;
    for (let i = 0; i < bands; i++) {
      const t = (i + 1) / bands;
      const y = horizonY - H * 0.05 + (H * 1.02 - horizonY) * (0.10 + t * 0.30) * (1 - 0.25 * i);
      const a = stormAmt * (0.07 + t * 0.05) * (1 - cleanT * 0.85);
      if (a <= 0.003) continue;
      const sh = H * (0.05 + i * 0.035);
      const off = Math.sin(elapsed * (0.1 + i * 0.06) + i) * W * 0.03;
      const g = ctx.createLinearGradient(0, y, 0, y + sh);
      g.addColorStop(0, `rgba(228,168,92,0)`);
      g.addColorStop(0.45, `rgba(226,164,86,${a})`);
      g.addColorStop(1, `rgba(196,132,62,0)`);
      ctx.fillStyle = g;
      ctx.fillRect(off - W * 0.05, y, W * 1.12, sh);
    }

    /* 2. airborne motes: blown left -> right, density grows with the storm */
    if (stormAmt > 0.01) {
      const speedBase = 0.06 + stormAmt * 0.30;
      for (const p of motes) {
        p.x += (speedBase * p.z) * (1 / 60);
        if (p.x > 1.08) { p.x = -0.08; p.y = hash(p.ph + elapsed * 0.13) ; }
        const y = p.y * H + Math.sin(elapsed * 1.3 + p.ph) * 5;
        const x = p.x * W;
        const sz = p.s * (0.6 + p.z * 1.1);
        ctx.globalAlpha = stormAmt * (0.10 + p.z * 0.30);
        ctx.fillStyle = p.z > 0.72 ? "#ffd98d" : "#e3b273";
        ctx.beginPath(); ctx.arc(x, y, sz, 0, 6.2832); ctx.fill();
      }
      ctx.globalAlpha = 1;
    }

    /* 3. the rolling front — a churning wall that crosses the frame and
          engulfs the array; by frontP = 1 everything is behind it. */
    if (frontP > 0.001) {
      const fx = -W * 0.30 + W * 1.45 * frontP;
      const coverA = clamp(frontP * 1.15, 0, 1) * (1 - cleanT * 0.92);
      if (coverA > 0.004) {
        const g = ctx.createLinearGradient(0, 0, fx, 0);
        g.addColorStop(0, `rgba(150,98,44,${0.80 * coverA})`);
        g.addColorStop(0.55, `rgba(186,128,62,${0.62 * coverA})`);
        g.addColorStop(0.88, `rgba(206,150,78,${0.34 * coverA})`);
        g.addColorStop(1, `rgba(214,160,88,0)`);
        ctx.fillStyle = g;
        /* wavy leading edge so the wall rolls instead of reading as a band */
        ctx.beginPath();
        const y0 = horizonY - H * 0.16, y1 = H * 1.06;
        ctx.moveTo(-4, y0);
        for (let yy = y0; yy <= y1; yy += Math.max(12, H / 46)) {
          const wave = Math.sin(yy * 0.019 + elapsed * 0.5) * W * 0.020
                     + Math.sin(yy * 0.041 - elapsed * 0.31) * W * 0.011;
          ctx.lineTo(fx + wave, yy);
        }
        ctx.lineTo(fx, y1);
        ctx.lineTo(-4, y1);
        ctx.closePath();
        ctx.fill();
        /* bright leading rim */
        const rim = ctx.createLinearGradient(fx - W * 0.06, 0, fx + W * 0.05, 0);
        rim.addColorStop(0, "rgba(255,220,160,0)");
        rim.addColorStop(0.6, `rgba(255,226,170,${0.42 * coverA})`);
        rim.addColorStop(1, "rgba(255,214,150,0)");
        ctx.fillStyle = rim;
        ctx.fillRect(fx - W * 0.06, horizonY - H * 0.2, W * 0.11, H * 1.25);
        /* churn — soft rolling puffs, not hard discs */
        for (const b of blobs) {
          const bx = fx - b.ox * W * 0.45 - Math.sin(elapsed * b.sp + b.ph) * W * 0.03;
          const by = b.y * H + Math.sin(elapsed * (0.4 + b.sp) + b.ph) * 12;
          const r = b.r * H * CFG.blobScale;
          const g2 = ctx.createRadialGradient(bx, by, 0, bx, by, r);
          const warm = bx > fx - W * 0.05;
          const A = coverA * CFG.blobAlpha;
          g2.addColorStop(0, warm ? `rgba(255,226,166,${0.15 * A})` : `rgba(206,152,78,${0.14 * A})`);
          g2.addColorStop(0.6, warm ? `rgba(244,196,124,${0.07 * A})` : `rgba(178,124,60,${0.06 * A})`);
          g2.addColorStop(1, "rgba(160,110,52,0)");
          ctx.fillStyle = g2;
          ctx.beginPath(); ctx.arc(bx, by, r, 0, 6.2832); ctx.fill();
        }
      }
    }

    /* 4. full-frame ochre veil — this is what actually buries the glass */
    const veil = stormAmt * 0.24 * (1 - cleanT * 0.94);
    if (veil > 0.004) {
      const g = ctx.createLinearGradient(0, horizonY - H * 0.3, 0, H);
      g.addColorStop(0, `rgba(214,158,88,${veil * 0.55})`);
      g.addColorStop(0.55, `rgba(186,130,66,${veil * 0.8})`);
      g.addColorStop(1, `rgba(126,86,44,${veil * 0.75})`);
      ctx.fillStyle = g;
      ctx.fillRect(0, 0, W, H);
    }
    /* horizon haze always present a little, so the ground meets the sky */
    const hz = ctx.createLinearGradient(0, horizonY - H * 0.09, 0, horizonY + H * 0.09);
    hz.addColorStop(0, `rgba(206,150,84,0)`);
    hz.addColorStop(0.5, `rgba(206,150,84,${0.12 + stormAmt * 0.20})`);
    hz.addColorStop(1, `rgba(196,142,78,0)`);
    ctx.fillStyle = hz;
    ctx.fillRect(0, horizonY - H * 0.09, W, H * 0.18);
  }

  /* ================================================================= HUD */
  function hudNumbers() {
    if (data && typeof data.soilingLossPct === "number") {
      const s = data.soilingLossPct;
      const o = typeof data.outputPct === "number" ? data.outputPct : 100 - s;
      return { soiling: s, output: o, dust: data.dustUgm3, live: true };
    }
    const s = 0.7 + 31.3 * clamp(stormAmt, 0, 1);
    const d = 12 + 268 * clamp(stormAmt, 0, 1);
    return { soiling: s, output: 100 - s, dust: d, live: false };
  }

  function stateLabel(p) {
    if (p >= PHASE.cleanStart) return { t: "CLEANING", c: C.cyan };
    if (stormAmt > 0.55) return { t: "DUST STORM", c: C.red };
    return { t: "ACCUMULATING", c: C.green };
  }

  function drawHUD(p) {
    const n = hudNumbers();
    const st = stateLabel(p);
    const pad = Math.round(clamp(W * 0.018, 12, 22));
    const small = W < 560;
    const fs = small ? 11 : 12.5;
    const lh = Math.round(fs * 1.72);
    const cardW = small ? Math.min(W - pad * 2, 268) : 300;
    const cardH = lh * 3 + pad * 1.6 + 12;
    // the page has a fixed nav; hudTop keeps the readout card clear of it
    const x = pad + (CFG.hudLeft - 16), y = pad + (CFG.hudTop - 26);

    ctx.save();
    /* card */
    ctx.fillStyle = "rgba(4,7,14,0.58)";
    roundRect(x, y, cardW, cardH, 12);
    ctx.fill();
    ctx.strokeStyle = "rgba(148,180,255,0.16)";
    ctx.lineWidth = 1;
    roundRect(x + 0.5, y + 0.5, cardW - 1, cardH - 1, 12);
    ctx.stroke();
    /* sand accent rail */
    ctx.fillStyle = C.sand;
    roundRect(x, y + 12, 2.5, cardH - 24, 2);
    ctx.fill();

    const tx = x + pad * 0.78;
    let ty = y + pad * 0.72 + fs;
    ctx.textBaseline = "alphabetic";
    ctx.textAlign = "left";
    ctx.font = `600 ${fs}px ${MONO}`;

    /* SOILING */
    ctx.fillStyle = C.dim;
    ctx.fillText("SOILING", tx, ty);
    ctx.textAlign = "right";
    ctx.fillStyle = n.soiling > 8 ? C.sand2 : C.green;
    ctx.font = `700 ${small ? fs + 1.5 : fs + 2}px ${MONO}`;
    ctx.fillText(`${(n.live ? n.soiling : n.soiling).toFixed(1)}%`, x + cardW - pad * 0.7, ty);

    /* OUTPUT */
    ty += lh;
    ctx.textAlign = "left";
    ctx.font = `600 ${fs}px ${MONO}`;
    ctx.fillStyle = C.dim;
    ctx.fillText("OUTPUT", tx, ty);
    ctx.textAlign = "right";
    ctx.fillStyle = C.ink;
    ctx.font = `700 ${small ? fs + 1.5 : fs + 2}px ${MONO}`;
    ctx.fillText(`${n.output.toFixed(1)}%`, x + cardW - pad * 0.7, ty);
    ctx.textAlign = "left";
    ctx.font = `500 ${fs - 1.5}px ${MONO}`;
    ctx.fillStyle = "rgba(127,141,171,0.85)";
    ctx.fillText("of clean", tx, ty + fs + 1);
    ty += fs + 1;

    /* state pill + dust */
    ty += lh * 0.62;
    const pillW = 12 + ctx.measureText(st.t).width + (small ? 14 : 18);
    ctx.font = `700 ${fs - 1.5}px ${MONO}`;
    const pw = ctx.measureText(st.t).width;
    ctx.fillStyle = "rgba(255,255,255,0.05)";
    roundRect(tx - 4, ty - fs + 1, pw + 26, fs + 12, 999);
    ctx.fill();
    ctx.fillStyle = st.c;
    ctx.beginPath(); ctx.arc(tx + 7, ty - fs + 1 + (fs + 12) / 2, 3, 0, 6.2832); ctx.fill();
    ctx.fillText(st.t, tx + 15, ty + 4);
    if (typeof n.dust === "number") {
      ctx.font = `500 ${fs - 2}px ${MONO}`;
      ctx.fillStyle = "rgba(127,141,171,0.9)";
      ctx.textAlign = "right";
      ctx.fillText(`DUST ${Math.round(n.dust)} µg/m³`, x + cardW - pad * 0.7, ty + 4);
      ctx.textAlign = "left";
    }

    /* thin progress rail at the card's foot */
    const railW = cardW - pad * 1.4;
    const ry = y + cardH - 8;
    ctx.fillStyle = "rgba(148,180,255,0.15)";
    roundRect(x + pad * 0.7, ry, railW, 2, 1);
    ctx.fill();
    ctx.fillStyle = cleanT > 0.005 ? C.cyan : C.sand;
    roundRect(x + pad * 0.7, ry, Math.max(2, railW * clamp(p, 0, 1)), 2, 1);
    ctx.fill();

    /* site name, bottom-left, small and dim */
    ctx.font = `500 ${small ? 9.5 : 10.5}px ${MONO}`;
    ctx.fillStyle = "rgba(127,141,171,0.75)";
    ctx.fillText(CFG.siteName.toUpperCase(), pad, H - pad * 0.7);
    ctx.fillStyle = "rgba(127,141,171,0.5)";
    ctx.fillText(n.live ? "LIVE API" : "SCENARIO", pad, H - pad * 0.7 - (small ? 13 : 15));
    ctx.restore();
  }

  function roundRect(x, y, w, h, r) {
    const rr = Math.min(r, w * 0.5, h * 0.5);
    ctx.beginPath();
    ctx.moveTo(x + rr, y);
    ctx.lineTo(x + w - rr, y);
    ctx.quadraticCurveTo(x + w, y, x + w, y + rr);
    ctx.lineTo(x + w, y + h - rr);
    ctx.quadraticCurveTo(x + w, y + h, x + w - rr, y + h);
    ctx.lineTo(x + rr, y + h);
    ctx.quadraticCurveTo(x, y + h, x, y + h - rr);
    ctx.lineTo(x, y + rr);
    ctx.quadraticCurveTo(x, y, x + rr, y);
    ctx.closePath();
  }

  /* ============================================================== the frame */
  function render(p) {
    if (!W || !H) return;
    updateDay(p);
    heave = Math.sin(elapsed * 0.55) * 1.2 + Math.cos(elapsed * 0.23) * 0.8;

    drawSky(p);
    drawSunGlow();
    drawDunes();
    drawGroundDetail();
    drawArrayShadow();
    drawArray();
    drawWasher();
    drawNearDunes();
    drawStorm();
    drawHUD(p);

    /* film grain-ish vignette so flat ochre areas are not dead */
    const vg = ctx.createRadialGradient(CX, CY * 0.92, Math.min(W, H) * 0.28, CX, CY, Math.max(W, H) * 0.78);
    vg.addColorStop(0, "rgba(0,0,0,0)");
    vg.addColorStop(1, "rgba(0,0,0,0.42)");
    ctx.fillStyle = vg;
    ctx.fillRect(0, 0, W, H);
  }

  /* ================================================================== loop */
  function loop(now) {
    if (!running || destroyed) return;
    const dt = Math.min(0.05, (now - lastT) / 1000 || 0.016);
    lastT = now;
    elapsed += dt;
    const k = CFG.smooth ? 1 - Math.exp(-dt * 14) : 1;
    progress += (target - progress) * k;
    if (Math.abs(target - progress) < 0.0004) progress = target;
    if (drawArray._washerOn) emitSpray();
    render(progress);
    raf = requestAnimationFrame(loop);
  }

  function renderOnce() {
    updateDay(progress);
    elapsed = elapsed || 0;
    render(progress);
  }

  /* ============================================================= public API */
  function setProgress(p, instant) {
    target = clamp(typeof p === "number" ? p : 0, 0, 1);
    if (instant || reduced || !running) {
      progress = target;
      if (!running) renderOnce();
    }
    return target;
  }
  function setData(d) {
    data = d && typeof d === "object" ? d : null;
    if (data && data.siteName) CFG.siteName = String(data.siteName);
    if (!running) renderOnce();
  }
  function start() {
    if (destroyed || running) return;
    if (reduced) { progress = target; renderOnce(); return; }
    running = true;
    lastT = performance.now();
    raf = requestAnimationFrame(loop);
  }
  function stop() {
    running = false;
    if (raf) cancelAnimationFrame(raf);
    raf = 0;
    renderOnce();
  }
  function destroy() {
    stop();
    destroyed = true;
    if (mq && mq.removeEventListener) mq.removeEventListener("change", onMQ);
    modules = []; motes = []; spray = []; blobs = []; bushes = [];
  }
  function onMQ(e) {
    reduced = !!e.matches;
    if (reduced) { stop(); progress = target; renderOnce(); }
    else { progress = target; start(); }
  }

  /* ================================================================ init */
  if (window.matchMedia) {
    mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    reduced = !!mq.matches;
    if (mq.addEventListener) mq.addEventListener("change", onMQ);
  }
  if (opts.reducedMotion === true) reduced = true;
  progress = target = clamp(CFG.staticProgress, 0, 1);
  resize();
  renderOnce();

  return {
    setProgress, setData, start, stop, destroy, resize,
    getProgress: () => progress,
    isRunning: () => running,
    isReduced: () => reduced,
    /** the HUD numbers currently on screen (useful for tests) */
    numbers: () => hudNumbers(),
    phases: PHASE,
  };
}

/* mono stack used by the HUD — mirrors --mono in solarguard.css */
const MONO = '"JetBrains Mono", ui-monospace, SFMono-Regular, Menlo, Consolas, "DejaVu Sans Mono", monospace';
