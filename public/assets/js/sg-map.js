/* ============================================================================
   sg-map.js — SolarGuard's map engine.

   Hand-written on purpose: no Leaflet, no Mapbox, no tiles from a tile server we
   don't control the terms of. It renders
     * real country outlines from public-domain GeoJSON (assets/data/borders.json)
     * real NASA GIBS satellite raster tiles, proxied through our own /api so we
       can fall back across dates when a day has no orbit coverage
     * the Saudi site catalogue, a click-to-place marker, and a dust particle field
   in one canvas, in Web Mercator, which is the same projection the tiles use.
   ========================================================================= */

const TILE = 256;
const R = 6378137;

function lon2x(lon, z) { return ((lon + 180) / 360) * TILE * Math.pow(2, z); }
function lat2y(lat, z) {
  const s = Math.sin((lat * Math.PI) / 180);
  return (0.5 - Math.log((1 + s) / (1 - s)) / (4 * Math.PI)) * TILE * Math.pow(2, z);
}
function x2lon(x, z) { return (x / (TILE * Math.pow(2, z))) * 360 - 180; }
function y2lat(y, z) {
  const n = Math.PI - (2 * Math.PI * y) / (TILE * Math.pow(2, z));
  return (180 / Math.PI) * Math.atan(0.5 * (Math.exp(n) - Math.exp(-n)));
}

export class SaudiMap {
  constructor(canvas, opts = {}) {
    this.c = canvas;
    this.ctx = canvas.getContext("2d");
    this.onPlace = opts.onPlace || (() => {});
    this.onHover = opts.onHover || (() => {});
    this.borders = null;
    this.sites = [];
    this.marker = null;
    this.layer = null;          // { id, label, date }
    this.tiles = new Map();     // key -> {img, state}
    this.pending = 0;
    this.z = opts.zoom ?? 5;
    this.center = opts.center || { lat: 24.2, lon: 45.2 };
    this.dust = Array.from({ length: 150 }, () => ({
      x: Math.random(), y: Math.random(), r: 0.4 + Math.random() * 1.9,
      vx: 0.00035 + Math.random() * 0.0011, a: 0.06 + Math.random() * 0.3,
    }));
    this.showLayer = true;
    this._bind();
    this._resize();
    this._loadBorders();
    this._loop();
  }

  async _loadBorders() {
    try {
      const r = await fetch("assets/data/borders.json");
      this.borders = await r.json();
    } catch (e) { console.warn("borders failed", e); }
  }

  _bind() {
    const c = this.c;
    this._onResize = () => this._resize();
    addEventListener("resize", this._onResize);
    let dragging = false, last = null, moved = 0;
    c.addEventListener("pointerdown", (e) => { dragging = true; moved = 0; last = { x: e.clientX, y: e.clientY }; c.setPointerCapture(e.pointerId); });
    c.addEventListener("pointermove", (e) => {
      if (dragging && last) {
        const dx = e.clientX - last.x, dy = e.clientY - last.y;
        moved += Math.abs(dx) + Math.abs(dy);
        this.center = this._screenToLatLonWorld(this._worldCenter.x - dx, this._worldCenter.y - dy);
        last = { x: e.clientX, y: e.clientY };
      }
      const ll = this.screenToLatLon(e.clientX, e.clientY);
      this.onHover(ll);
      c.style.cursor = dragging ? "grabbing" : "crosshair";
    });
    c.addEventListener("pointerup", (e) => {
      dragging = false;
      if (moved < 5) {
        const ll = this.screenToLatLon(e.clientX, e.clientY);
        this.onPlace(ll.lat, ll.lon);
      }
    });
    c.addEventListener("wheel", (e) => {
      e.preventDefault();
      this.z = Math.max(3, Math.min(7, this.z + (e.deltaY > 0 ? -1 : 1)));
      this._resize();
    }, { passive: false });
    c.addEventListener("dblclick", () => { this.z = 5; this._resize(); });
  }

  _resize() {
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    this.w = this.c.clientWidth || 800;
    this.h = this.c.clientHeight || 420;
    this.c.width = Math.round(this.w * dpr);
    this.c.height = Math.round(this.h * dpr);
    this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    this._recenter();
  }

  _recenter() {
    const wx = lon2x(this.center.lon, this.z), wy = lat2y(this.center.lat, this.z);
    this._worldCenter = { x: wx, y: wy };
    this._origin = { x: wx - this.w / 2, y: wy - this.h / 2 };
  }

  _screenToLatLonWorld(sx, sy) {
    const p = { x: sx, y: sy };
    return { lat: y2lat(p.y, this.z), lon: x2lon(p.x, this.z) };
  }

  screenToLatLon(cx, cy) {
    const r = this.c.getBoundingClientRect();
    const sx = cx - r.left + this._origin.x, sy = cy - r.top + this._origin.y;
    return { lat: y2lat(sy, this.z), lon: x2lon(sx, this.z) };
  }

  _projectXY(lat, lon) {
    return { x: lon2x(lon, this.z) - this._origin.x, y: lat2y(lat, this.z) - this._origin.y };
  }

  setSites(sites) { this.sites = sites || []; }
  setMarker(lat, lon, label) { this.marker = lat == null ? null : { lat, lon, label }; }
  setLayer(layer, date) {
    this.layer = layer ? { id: layer.id || layer, label: layer.label || layer.id, date } : null;
    this.tiles.clear();
  }
  setLayerVisible(v) { this.showLayer = !!v; }
  focus(lat, lon, z) { this.center = { lat, lon }; if (z) this.z = z; this._resize(); }

  /* ---------------------------------------------------------- tiles */
  _tileKey(z, x, y) { return `${this.layer?.id}/${this.layer?.date}/${z}/${x}/${y}`; }

  _ensureTiles() {
    if (!this.layer || !this.showLayer) return;
    const z = this.z;
    const x0 = Math.floor(this._origin.x / TILE), x1 = Math.floor((this._origin.x + this.w) / TILE);
    const y0 = Math.floor(this._origin.y / TILE), y1 = Math.floor((this._origin.y + this.h) / TILE);
    const n = Math.pow(2, z);
    let started = 0;
    for (let x = x0; x <= x1; x++) {
      for (let y = y0; y <= y1; y++) {
        if (x < 0 || y < 0 || x >= n || y >= n) continue;
        const key = this._tileKey(z, x, y);
        if (this.tiles.has(key)) continue;
        if (started > 6) return;               // throttle: 6 new tiles per frame
        started++;
        this.tiles.set(key, { state: "loading" });
        const url = `api/satellite/tile/${encodeURIComponent(this.layer.id)}/${this.layer.date}/${z}/${x}/${y}.png`;
        const img = new Image();
        img.onload = () => { this.tiles.set(key, { state: "ok", img }); };
        img.onerror = () => { this.tiles.set(key, { state: "none" }); };
        img.src = url;
      }
    }
  }

  /* ---------------------------------------------------------- draw */
  _drawTiles() {
    if (!this.layer || !this.showLayer) return;
    const ctx = this.ctx;
    ctx.save();
    ctx.globalAlpha = 0.92;
    ctx.globalCompositeOperation = "screen";
    ctx.filter = "saturate(1.35) contrast(1.06)";
    const z = this.z, ox = this._origin.x, oy = this._origin.y;
    for (const [key, t] of this.tiles) {
      if (t.state !== "ok") continue;
      const [, , kz, kx, ky] = key.split("/");
      if (+kz !== z) continue;
      const px = +kx * TILE - ox, py = +ky * TILE - oy;
      ctx.drawImage(t.img, px, py, TILE, TILE);
    }
    ctx.restore();
  }

  _drawBorders() {
    if (!this.borders) return;
    const ctx = this.ctx;
    const saudi = this.borders.SAU || [];
    // neighbours: faint, so Saudi Arabia reads as the subject
    for (const [cc, rings] of Object.entries(this.borders)) {
      if (cc === "SAU") continue;
      ctx.beginPath();
      for (const ring of rings) {
        ring.forEach(([lon, lat], i) => {
          const p = this._projectXY(lat, lon);
          i ? ctx.lineTo(p.x, p.y) : ctx.moveTo(p.x, p.y);
        });
        ctx.closePath();
      }
      ctx.fillStyle = "rgba(28,38,62,0.42)";
      ctx.fill();
      ctx.strokeStyle = "rgba(148,180,255,0.20)";
      ctx.lineWidth = 1;
      ctx.stroke();
    }
    // Saudi Arabia: the subject of the story
    ctx.beginPath();
    for (const ring of saudi) {
      ring.forEach(([lon, lat], i) => {
        const p = this._projectXY(lat, lon);
        i ? ctx.lineTo(p.x, p.y) : ctx.moveTo(p.x, p.y);
      });
      ctx.closePath();
    }
    const g = ctx.createLinearGradient(0, 0, this.w, this.h);
    g.addColorStop(0, "rgba(243,167,43,0.10)");
    g.addColorStop(1, "rgba(55,224,255,0.10)");
    ctx.fillStyle = g; ctx.fill();
    ctx.strokeStyle = "rgba(255,205,107,0.85)"; ctx.lineWidth = 1.5;
    ctx.shadowColor = "rgba(243,167,43,0.6)"; ctx.shadowBlur = 12; ctx.stroke(); ctx.shadowBlur = 0;
  }

  _drawDust(t) {
    const ctx = this.ctx;
    for (const p of this.dust) {
      p.x += p.vx * (1 + this.z * 0.12);
      if (p.x > 1.02) { p.x = -0.02; p.y = Math.random(); }
      ctx.globalAlpha = p.a;
      ctx.fillStyle = p.r > 1.5 ? "#ffcd6b" : "#f3a72b";
      ctx.beginPath();
      ctx.arc(p.x * this.w, p.y * this.h + Math.sin(t / 1400 + p.y * 9) * 4, p.r, 0, 6.283);
      ctx.fill();
    }
    ctx.globalAlpha = 1;
  }

  _drawSites(t) {
    const ctx = this.ctx;
    for (const s of this.sites) {
      const p = this._projectXY(s.lat, s.lon);
      if (p.x < -40 || p.y < -40 || p.x > this.w + 40 || p.y > this.h + 40) continue;
      const active = this.marker && Math.abs(this.marker.lat - s.lat) < 1e-6;
      const pulse = 1 + Math.sin(t / 600) * 0.18;
      ctx.beginPath(); ctx.arc(p.x, p.y, (active ? 11 : 7) * pulse, 0, 6.283);
      ctx.fillStyle = active ? "rgba(243,167,43,0.28)" : "rgba(55,224,255,0.16)";
      ctx.fill();
      ctx.beginPath(); ctx.arc(p.x, p.y, active ? 4.4 : 3.1, 0, 6.283);
      ctx.fillStyle = active ? "#ffcd6b" : "#37e0ff";
      ctx.shadowColor = active ? "#f3a72b" : "#37e0ff"; ctx.shadowBlur = 12; ctx.fill(); ctx.shadowBlur = 0;
      if (this.z >= 5 && (active || s.capacity_mwp >= 90)) {
        ctx.font = "600 11px Inter, system-ui, sans-serif";
        ctx.fillStyle = active ? "#ffcd6b" : "rgba(234,241,255,0.82)";
        ctx.textAlign = "left";
        ctx.fillText(s.name.replace(/ \(.*\)$/, ""), p.x + 9, p.y + 4);
      }
    }
    if (this.marker && !this.sites.some((s) => Math.abs(s.lat - this.marker.lat) < 1e-6)) {
      const p = this._projectXY(this.marker.lat, this.marker.lon);
      ctx.beginPath(); ctx.arc(p.x, p.y, 6, 0, 6.283);
      ctx.fillStyle = "#ffcd6b"; ctx.shadowColor = "#f3a72b"; ctx.shadowBlur = 18;
      ctx.fill(); ctx.shadowBlur = 0;
      ctx.strokeStyle = "rgba(255,205,107,0.7)"; ctx.beginPath();
      ctx.arc(p.x, p.y, 13 + Math.sin(t / 500) * 3, 0, 6.283); ctx.stroke();
    }
  }

  _loop() {
    const step = (t) => {
      this._ensureTiles();
      const ctx = this.ctx;
      ctx.clearRect(0, 0, this.w, this.h);
      // deep-sea base
      const bg = ctx.createRadialGradient(this.w * 0.5, this.h * 0.45, 20, this.w * 0.5, this.h * 0.5, Math.max(this.w, this.h) * 0.85);
      bg.addColorStop(0, "#071023"); bg.addColorStop(1, "#04060c");
      ctx.fillStyle = bg; ctx.fillRect(0, 0, this.w, this.h);

      this._drawTiles();
      this._drawBorders();
      this._drawDust(t);
      this._drawSites(t);

      // scale bar + zoom readout
      ctx.font = "11px ui-monospace, monospace";
      ctx.fillStyle = "rgba(127,141,171,0.9)"; ctx.textAlign = "right";
      ctx.fillText(`zoom ${this.z} · ${this.layer ? this.layer.id : "no layer"}${this.layer?.date ? " · " + this.layer.date : ""}`,
                   this.w - 10, 18);
      requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  }
}
