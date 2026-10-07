/* ============================================================================
   sg-plume-story.js — the second scroll animation.

   Deliberately a different language from the hero: this one is a mission-control
   plot seen from orbit, not a perspective view from the ground. A satellite pass
   sweeps the Kingdom, a dust plume blooms in the north-east and crosses the
   country, site markers redden as the front passes over them, then a cleaning
   sweep clears them again — all driven by the page's scroll position.

   Pure canvas 2D, no dependencies, no tiles. The country outline comes from the
   same public-domain GeoJSON the map uses (assets/data/borders.json), so the
   shape is real, not sketched.
   ========================================================================= */

const hash = (n) => { const s = Math.sin(n * 127.1) * 43758.5453; return s - Math.floor(s); };

export function createPlumeStory(canvas, opts = {}) {
  const ctx = canvas.getContext("2d");
  const CFG = {
    dprCap: opts.dprCap || 1.5,
    sites: opts.sites || [],
    staticProgress: typeof opts.staticProgress === "number" ? opts.staticProgress : 0.45,
    onPhase: opts.onPhase || null,          // (index, text) => void, for captions
    hudTop: typeof opts.hudTop === "number" ? opts.hudTop : 74,
  };

  const PHASE = {
    passStart: 0.02, passEnd: 0.34,         // satellite crossing
    plumeStart: 0.30, plumeFull: 0.68,      // dust front blooming and crossing
    cleanStart: 0.74, cleanEnd: 0.99,
  };
  const CAPTIONS = [
    "We watch the dust from orbit.",
    "A front forms over the north-east and crosses the Kingdom.",
    "Every site it passes gets a number, not a guess.",
    "Then we clear them and start again.",
  ];

  let W = 0, H = 0, dpr = 1, D = 1;
  let progress = CFG.staticProgress, target = CFG.staticProgress;
  let borders = null, saudRings = [], bbox = null;
  let run = false, raf = 0, elapsed = 0, lastT = 0;
  let sites = [];
  let plume = [];
  let dustMotes = [];
  let lastCaption = -1;
  let data = null;

  /* ------------------------------------------------------------ geometry */
  function fit() {
    // equirectangular fit of the Saudi bounding box with padding, then we keep a
    // fixed aspect so the country never squashes
    const rings = saudRings.flat();
    if (!rings.length) return;
    let minLon = 1e9, maxLon = -1e9, minLat = 1e9, maxLat = -1e9;
    for (const [lon, lat] of rings) {
      minLon = Math.min(minLon, lon); maxLon = Math.max(maxLon, lon);
      minLat = Math.min(minLat, lat); maxLat = Math.max(maxLat, lat);
    }
    bbox = { minLon, maxLon, minLat, maxLat };
    const padX = W * 0.10, padY = H * 0.14;
    const sx = (W - padX * 2) / (maxLon - minLon);
    const sy = (H - padY * 2) / (maxLat - minLat);
    D = Math.min(sx, sy);
    bbox.ox = (W - (maxLon - minLon) * D) / 2;
    bbox.oy = (H - (maxLat - minLat) * D) / 2;
  }

  const px = (lon) => bbox.ox + (lon - bbox.minLon) * D;
  const py = (lat) => H - (bbox.oy + (lat - bbox.minLat) * D);   // north up

  function projectSites(list) {
    sites = (list || CFG.sites || []).map((s, i) => {
      const t = hash(i * 3.1);      // each site gets its own exposure timing
      return { ...s, x: 0, y: 0, t: 0.30 + t * 0.34, soiling: 0 };
    });
  }

  /* ------------------------------------------------------------ state */
  function rebuild() {
    const dprWant = Math.min(window.devicePixelRatio || 1, CFG.dprCap);
    W = canvas.clientWidth || 900; H = canvas.clientHeight || 520;
    dpr = dprWant;
    canvas.width = Math.round(W * dpr); canvas.height = Math.round(H * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    fit();
    if (bbox) sites.forEach((s) => { s.x = px(s.lon); s.y = py(s.lat); });

    // the plume is a cluster of soft puffs, born in the north-east
    plume = [];
    const n = W < 640 ? 11 : 18;
    for (let i = 0; i < n; i++) {
      plume.push({
        off: hash(i * 5.3),                      // stagger along the front
        r: (0.10 + hash(i * 2.7) * 0.16) * Math.min(W, H) * 0.9,
        y0: 0.06 + hash(i * 8.1) * 0.5,
        drift: 0.10 + hash(i * 4.4) * 0.22,
      });
    }
    dustMotes = [];
    const m = W < 640 ? 40 : 90;
    for (let i = 0; i < m; i++) {
      dustMotes.push({ x: hash(i * 1.7), y: hash(i * 9.2), s: 0.4 + hash(i * 3.3) * 1.5, z: 0.2 + hash(i * 6.6) });
    }
  }

  /* ------------------------------------------------------------ draw helpers */
  function outlinePath() {
    const p = new Path2D();
    for (const ring of saudRings) {
      ring.forEach(([lon, lat], i) => {
        const x = px(lon), y = py(lat);
        i ? p.lineTo(x, y) : p.moveTo(x, y);
      });
      p.closePath();
    }
    return p;
  }

  function drawGrid() {
    const step = 5;                      // every 5 degrees of lat/lon
    ctx.save();
    ctx.strokeStyle = "rgba(150,176,220,0.10)";
    ctx.lineWidth = 1;
    ctx.beginPath();
    for (let lon = Math.ceil(bbox.minLon / step) * step; lon < bbox.maxLon; lon += step) {
      ctx.moveTo(px(lon), py(bbox.minLat)); ctx.lineTo(px(lon), py(bbox.maxLat));
    }
    for (let lat = Math.ceil(bbox.minLat / step) * step; lat < bbox.maxLat; lat += step) {
      ctx.moveTo(px(bbox.minLon), py(lat)); ctx.lineTo(px(bbox.maxLon), py(lat));
    }
    ctx.stroke();
    ctx.restore();
  }

  function drawPlume(t) {
    if (!bbox || !saudRings.length) return;
    const p = progress;
    const bloom = clamp01((p - PHASE.plumeStart) / (PHASE.plumeFull - PHASE.plumeStart));
    if (bloom <= 0) return;
    const clean = clamp01((p - PHASE.cleanStart) / (PHASE.cleanEnd - PHASE.cleanStart));
    const cover = bloom * (1 - clean);

    ctx.save();
    ctx.clip(outlinePath());                    // dust lands on land, not on the sea
    ctx.globalCompositeOperation = "lighter";
    // a shamal front arrives from the north-east and travels south-west, so it
    // sweeps right to left across the plot and its dust trails behind it
    const east = px(bbox.maxLon) + W * 0.12;
    const west = px(bbox.minLon) - W * 0.12;
    const frontX = east - (east - west) * bloom;

    // leading (western) edge: a brighter band so the front reads as an event
    // moving across the country rather than a wash of colour
    const edge = ctx.createLinearGradient(frontX - W * 0.06, 0, frontX + W * 0.22, 0);
    edge.addColorStop(0, `rgba(255,236,190,${0.26 * cover})`);
    edge.addColorStop(0.35, `rgba(255,214,140,${0.14 * cover})`);
    edge.addColorStop(1, "rgba(255,196,92,0)");
    ctx.fillStyle = edge;
    ctx.fillRect(frontX - W * 0.06, 0, W * 0.28, H);

    for (const b of plume) {
      // dust sits BEHIND the front (to its east) and keeps drifting west
      const bx = frontX + b.off * W * 0.42 + clean * W * 0.30;
      if (bx < -W * 0.3) continue;
      const by = py(bbox.maxLat) + b.y0 * H * 0.7 + Math.sin(t * 0.5 + b.off * 9) * 8;
      const r = b.r * (0.6 + bloom * 0.7 + clean * 0.2);
      const g = ctx.createRadialGradient(bx, by, 0, bx, by, r);
      g.addColorStop(0, `rgba(255,196,92,${0.20 * cover})`);
      g.addColorStop(0.45, `rgba(226,150,64,${0.13 * cover})`);
      g.addColorStop(1, "rgba(180,116,48,0)");
      ctx.fillStyle = g;
      ctx.beginPath(); ctx.arc(bx, by, r, 0, 6.2832); ctx.fill();
    }

    // contour rings so the plume reads as a measured field, not a smudge
    ctx.globalCompositeOperation = "source-over";
    ctx.strokeStyle = `rgba(255,214,140,${0.20 * cover})`;
    ctx.lineWidth = 1;
    for (let k = 0; k < 3; k++) {
      const rr = (0.16 + k * 0.09) * Math.min(W, H);
      ctx.beginPath();
      ctx.ellipse(frontX + W * 0.14, py(bbox.maxLat) + H * 0.26, rr * 1.5, rr, -0.35, 0, 6.2832);
      ctx.stroke();
    }
    ctx.restore();
  }

  function drawCountry() {
    if (!saudRings.length) return;
    const path = outlinePath();
    const g = ctx.createLinearGradient(0, 0, W, H);
    g.addColorStop(0, "rgba(243,167,43,0.055)");
    g.addColorStop(1, "rgba(55,224,255,0.05)");
    ctx.fillStyle = g; ctx.fill(path);
    ctx.strokeStyle = "rgba(255,205,107,0.75)";
    ctx.lineWidth = 1.4;
    ctx.shadowColor = "rgba(243,167,43,0.45)"; ctx.shadowBlur = 14;
    ctx.stroke(path); ctx.shadowBlur = 0;
  }

  function drawSatellite(t) {
    const p = clamp01((progress - PHASE.passStart) / (PHASE.passEnd - PHASE.passStart));
    const x = -60 + p * (W + 120);
    const y = H * 0.10 + Math.sin(p * Math.PI) * H * 0.05;
    // ground track beam
    const beam = ctx.createLinearGradient(x, y, x, H);
    beam.addColorStop(0, `rgba(55,224,255,${0.12 * (1 - p * 0.55)})`);
    beam.addColorStop(1, "rgba(55,224,255,0)");
    ctx.save();
    ctx.globalCompositeOperation = "lighter";
    ctx.fillStyle = beam;
    ctx.beginPath();
    ctx.moveTo(x - 4, y); ctx.lineTo(x + 4, y);
    ctx.lineTo(x + W * 0.10, H); ctx.lineTo(x - W * 0.10, H);
    ctx.closePath(); ctx.fill();
    ctx.restore();

    // the satellite itself: body + two panels
    ctx.save();
    ctx.translate(x, y);
    ctx.fillStyle = "#e8eefc";
    ctx.fillRect(-5, -5, 10, 10);
    ctx.fillStyle = "rgba(55,224,255,0.85)";
    ctx.fillRect(-34, -4, 24, 8);
    ctx.fillRect(10, -4, 24, 8);
    ctx.strokeStyle = "rgba(232,238,252,0.55)";
    ctx.beginPath(); ctx.moveTo(-10, 0); ctx.lineTo(-5, 0); ctx.moveTo(5, 0); ctx.lineTo(10, 0); ctx.stroke();
    ctx.restore();

    // scan ring on the ground under the satellite
    const gy = H * 0.55;
    ctx.strokeStyle = `rgba(55,224,255,${0.20 * (1 - p)})`;
    ctx.beginPath(); ctx.ellipse(x, gy, 46, 16, 0, 0, 6.2832); ctx.stroke();
    ctx.beginPath(); ctx.ellipse(x, gy, 74, 26, 0, 0, 6.2832); ctx.stroke();
  }

  function drawSites(t) {
    const clean = clamp01((progress - PHASE.cleanStart) / (PHASE.cleanEnd - PHASE.cleanStart));
    let affected = 0;
    for (const s of sites) {
      const d = clamp01((progress - s.t) / 0.18) * (1 - clean);
      s.soiling = d;
      if (d > 0.35) affected++;
      const col = d > 0.6 ? "#ff5f6d" : d > 0.25 ? "#ffb020" : "#37e0ff";
      const pulse = 1 + Math.sin(t * 2 + s.x * 0.05) * 0.15;
      ctx.beginPath();
      ctx.arc(s.x, s.y, (5 + d * 4) * pulse, 0, 6.2832);
      ctx.fillStyle = col;
      ctx.shadowColor = col; ctx.shadowBlur = 12; ctx.fill(); ctx.shadowBlur = 0;
      if (d > 0.25) {
        ctx.beginPath(); ctx.arc(s.x, s.y, 12 + d * 10, 0, 6.2832);
        ctx.strokeStyle = d > 0.6 ? "rgba(255,95,109,0.45)" : "rgba(255,176,32,0.4)";
        ctx.lineWidth = 1.2; ctx.stroke();
      }
    }
    return affected;
  }

  function drawMotes(t) {
    const clean = clamp01((progress - PHASE.cleanStart) / (PHASE.cleanEnd - PHASE.cleanStart));
    const amt = clamp01((progress - PHASE.plumeStart) / 0.3) * (1 - clean);
    if (amt <= 0.02) return;
    for (const m of dustMotes) {
      m.x += (0.0009 + m.z * 0.0022) * (1 + amt);
      if (m.x > 1.06) { m.x = -0.05; m.y = hash(m.z * 91 + elapsed); }
      ctx.globalAlpha = amt * (0.10 + m.z * 0.35);
      ctx.fillStyle = m.z > 0.7 ? "#ffd98d" : "#e3b273";
      ctx.beginPath(); ctx.arc(m.x * W, m.y * H, m.s * (W < 640 ? 0.8 : 1.2), 0, 6.2832); ctx.fill();
    }
    ctx.globalAlpha = 1;
  }

  function drawHud(affected) {
    const site = data?.siteName || "SAUDI ARABIA";
    const p = Math.round(progress * 100);
    ctx.font = "500 11px ui-monospace, SFMono-Regular, Menlo, monospace";
    ctx.fillStyle = "rgba(232,238,252,0.85)";
    ctx.textAlign = "left";
    const hudY = CFG.hudTop < 0 ? H + CFG.hudTop : CFG.hudTop;
    const phase = progress < PHASE.plumeStart ? "ORBIT PASS"
      : progress < PHASE.cleanStart ? "DUST FRONT" : "CLEARING";
    ctx.fillText(`${phase}  ·  ${site}`, 16, hudY);
    ctx.fillStyle = "rgba(255,205,107,0.9)";
    ctx.fillText(`SITES AFFECTED ${affected}/${sites.length}`, 16, hudY + 18);
    if (data && typeof data.soilingLossPct === "number") {
      ctx.fillStyle = "rgba(55,224,255,0.9)";
      ctx.fillText(`SOILING ${data.soilingLossPct.toFixed(1)}%`, 16, hudY + 36);
    }
    ctx.textAlign = "right";
    ctx.fillStyle = "rgba(125,138,166,0.9)";
    ctx.fillText(`${p}%`, W - 16, 26);
  }

  const clamp01 = (v) => Math.max(0, Math.min(1, v));

  /* ------------------------------------------------------------ loop */
  function frame(now) {
    if (!run) return;
    const t = now / 1000;
    const dt = Math.min(0.05, lastT ? t - lastT : 0.016);
    lastT = t;
    elapsed += dt;
    progress += (target - progress) * Math.min(1, dt * 6);

    ctx.clearRect(0, 0, W, H);
    const bg = ctx.createLinearGradient(0, 0, 0, H);
    bg.addColorStop(0, "#070d1a"); bg.addColorStop(0.55, "#0a1120"); bg.addColorStop(1, "#0c1424");
    ctx.fillStyle = bg; ctx.fillRect(0, 0, W, H);

    if (borders) {
      drawGrid();
      drawCountry();
      drawPlume(t);
      const affected = drawSites(t);
      drawMotes(t);
      drawSatellite(t);
      drawHud(affected);
    }

    // caption callbacks for the page
    if (CFG.onPhase) {
      const idx = progress < PHASE.plumeStart ? 0 : progress < PHASE.plumeFull ? 1 : progress < PHASE.cleanStart ? 2 : 3;
      if (idx !== lastCaption) { lastCaption = idx; CFG.onPhase(idx, CAPTIONS[idx]); }
    }

    raf = requestAnimationFrame(frame);
  }

  /* ------------------------------------------------------------ public */
  fetch("assets/data/borders.json")
    .then((r) => r.json())
    .then((b) => {
      borders = b;
      saudRings = [b.SAU || []];
      saudRings = b.SAU || [];
      rebuild();                      // re-fit once the real outline is in
      if (!run) start();
    })
    .catch((e) => console.warn("[solarguard] plume story: no borders", e));

  function start() { if (run) return; run = true; lastT = 0; raf = requestAnimationFrame(frame); }
  function stop() { run = false; cancelAnimationFrame(raf); }

  window.addEventListener("resize", () => rebuild());
  projectSites(CFG.sites);
  rebuild();
  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
    target = progress; drawOnce();
    function drawOnce() {
      ctx.clearRect(0, 0, W, H);
      ctx.fillStyle = "#0a1120"; ctx.fillRect(0, 0, W, H);
      if (saudRings.length) { drawGrid(); drawCountry(); drawPlume(0); drawSites(0); drawSatellite(0); drawHud(0); }
    }
  }

  return {
    setProgress(p) { target = clamp01(p); },
    setData(d) { data = d; if (d?.sites) { projectSites(d.sites); } },
    setSites(list) { projectSites(list); if (bbox) sites.forEach((s) => { s.x = px(s.lon); s.y = py(s.lat); }); },
    start, stop,
    resize: rebuild,
    destroy() { stop(); },
    get progress() { return progress; },
  };
}
