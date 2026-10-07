/* ============================================================================
   sg-realmaps.js — SolarGuard's REAL map.

   Replaces the hand-drawn canvas map (sg-map.js) with an actual slippy map:
     * Leaflet 1.9.4 (loaded from unpkg, CSS + JS) as the renderer
     * real vector-rendered basemap tiles — Carto "dark_all" (default, matches the
       near-black design) and OSM standard, both switchable in the UI
     * our NASA GIBS satellite raster on top, fetched through OUR OWN proxy
       (api/satellite/tile/{layer}/{date}/{z}/{x}/{y}.png) so no key is needed and
       the backend silently walks back to a date that has orbit coverage
     * the Saudi site catalogue, a click-to-place marker and a hover read-out

   Public API — a drop-in replacement for the canvas map:

       const map = createRealMap(el, {
         onPlace(lat, lon),          // click on empty map
         onHover(lat, lon) | onHover({lat, lon}),   // both call shapes accepted
         onSelect(site),             // click on a catalogue marker
         onLayerChange({id,label,date}),
         apiBase, layer, center, zoom, basemap, controls, autoLayer,
       });
       map.setSites(sites)           // [{id,name,lat,lon,region,climate,capacity_mwp}]
       map.setMarker(lat, lon, label)  // null clears
       map.setLayer({id, label, date}) // null clears the satellite overlay
       map.setLayerVisible(bool)
       map.focus(lat, lon, zoom)
       map.showLayer                 // bool property, kept for dashboard compat
       map.setBasemap('dark'|'osm')
       map.destroy()

   createRealMap() returns IMMEDIATELY. Leaflet loads asynchronously; every call
   made before it is ready is queued and replayed. If the CDN fails, the module
   transparently falls back to the canvas map and the dashboard still has a map.
   ========================================================================= */

const LEAFLET_VER = "1.9.4";
const LEAFLET_CSS = `https://unpkg.com/leaflet@${LEAFLET_VER}/dist/leaflet.css`;
const LEAFLET_JS = `https://unpkg.com/leaflet@${LEAFLET_VER}/dist/leaflet.js`;

/* 1x1 transparent GIF — Leaflet shows this instead of a broken-image icon when a
   tile is missing (our proxy answers 204 "no data" for days without coverage). */
const BLANK_TILE = "data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7";

const PALETTE = { sand: "#ffcd6b", amber: "#f3a72b", cyan: "#37e0ff" };

/* Basemaps.
   NOTE ON CARTO: the spec'd Carto "dark_all" URL is kept below and is still
   selectable, but CARTO now serve an "API KEY REQUIRED / carto.com/basemaps/apikey"
   watermark PNG (~2.5 kB, identical for every tile) to unkeyed requests, so it is
   NOT the default. The default dark style is Esri's free World Dark Gray Canvas
   (base + reference labels) which needs no key and carries country/city labels. */
const CARTO_URL = "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png";
const CARTO_ATTR = "© OpenStreetMap contributors © CARTO";
const OSM_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png";
const OSM_ATTR = "© OpenStreetMap contributors";
const ESRI_BASE_URL = "https://services.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}";
const ESRI_REF_URL = "https://services.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Reference/MapServer/tile/{z}/{y}/{x}";
const ESRI_ATTR = "Esri, HERE, Garmin, © OpenStreetMap contributors, and the GIS user community";
const GIBS_ATTR = "NASA GIBS/EOSDIS";

const DEFAULT_CENTER = { lat: 24.2, lon: 45.2 };
const DEFAULT_ZOOM = 5;

/* Fallback catalogue so the layer <select> is never empty, even if /api is down. */
const FALLBACK_LAYERS = [
  { id: "MODIS_Terra_Aerosol", label: "MODIS Aerosol Optical Depth (Terra)", tms: "GoogleMapsCompatible_Level6", kind: "daily", unit: "AOD" },
  { id: "MODIS_Aqua_Aerosol_Optical_Depth_3km", label: "MODIS AOD 3km (Aqua)", tms: "GoogleMapsCompatible_Level6", kind: "daily", unit: "AOD" },
  { id: "MODIS_Combined_MAIAC_L2G_AerosolOpticalDepth", label: "MAIAC AOD 1km (combined)", tms: "GoogleMapsCompatible_Level8", kind: "daily", unit: "AOD" },
  { id: "MODIS_Terra_AOD_Deep_Blue_Land", label: "MODIS Deep Blue AOD over land", tms: "GoogleMapsCompatible_Level6", kind: "daily", unit: "AOD" },
  { id: "AIRS_L2_Dust_Score_Day", label: "AIRS Dust Score (day)", tms: "GoogleMapsCompatible_Level6", kind: "daily", unit: "index" },
  { id: "MERRA2_Dust_Surface_Mass_Concentration_Monthly", label: "MERRA-2 Dust Surface Mass (monthly)", tms: "GoogleMapsCompatible_Level6", kind: "monthly", unit: "µg/m³" },
  { id: "MERRA2_Total_Aerosol_Optical_Thickness_550nm_Extinction_Monthly", label: "MERRA-2 AOT 550nm (monthly)", tms: "GoogleMapsCompatible_Level6", kind: "monthly", unit: "AOT" },
  { id: "MERRA2_Total_Dust_Deposition_Dry_Wet_Monthly", label: "MERRA-2 Dust Deposition dry+wet (monthly)", tms: "GoogleMapsCompatible_Level6", kind: "monthly", unit: "kg/m²s" },
];

/* ------------------------------------------------------------------ helpers */
const esc = (s) => String(s == null ? "" : s)
  .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
  .replace(/"/g, "&quot;").replace(/'/g, "&#39;");

const capLabel = (mwp) => {
  const v = Number(mwp);
  if (!isFinite(v)) return "—";
  return v >= 1000 ? `${(v / 1000).toFixed(v % 1000 ? 1 : 0)} GWp` : `${v} MWp`;
};

function joinBase(base) {
  if (!base) return "";
  return base.endsWith("/") ? base : base + "/";
}

function injectCss(href, id) {
  if (document.getElementById(id)) return;
  const l = document.createElement("link");
  l.id = id; l.rel = "stylesheet"; l.href = href;
  document.head.appendChild(l);
}

function loadScript(src, id) {
  return new Promise((resolve, reject) => {
    if (document.getElementById(id)) return resolve();
    const s = document.createElement("script");
    s.id = id; s.src = src; s.async = true;
    s.onload = () => resolve();
    s.onerror = () => reject(new Error(`failed to load ${src}`));
    document.head.appendChild(s);
  });
}

/* The module's own chrome (markers, tooltips, the floating control cluster).
   Injected once; every rule is namespaced under sg- / [data-sg-realmap]. */
function injectStyle() {
  if (document.getElementById("sg-realmaps-style")) return;
  const st = document.createElement("style");
  st.id = "sg-realmaps-style";
  st.textContent = `
  [data-sg-realmap]{background:#04060c}
  /* cursor: our canvas CSS sets crosshair on #sg-map; !important lets Leaflet win */
  [data-sg-realmap].leaflet-grab{cursor:grab!important}
  [data-sg-realmap].leaflet-dragging{cursor:grabbing!important}
  [data-sg-realmap] .leaflet-container{background:#04060c;font:inherit}
  [data-sg-realmap] .leaflet-control-attribution{background:rgba(4,7,14,.72)!important;color:#7f8dab!important;
      font:400 10px/1.4 Inter,system-ui,sans-serif!important;padding:1px 6px!important;border-radius:6px 0 0 0}
  [data-sg-realmap] .leaflet-control-attribution a{color:#9fb4d8!important}

  /* ---- markers -------------------------------------------------------- */
  .sg-mk{border-radius:50%;background:${PALETTE.cyan};border:1px solid rgba(4,6,12,.85);
      box-shadow:0 0 0 2px rgba(4,6,12,.55),0 0 12px rgba(55,224,255,.85);box-sizing:border-box;
      transition:background .15s,box-shadow .15s}
  .sg-mk.sel{background:${PALETTE.sand};box-shadow:0 0 0 2px rgba(4,6,12,.55),0 0 18px rgba(243,167,43,.95);z-index:600!important}
  .sg-mk.pulse{background:${PALETTE.sand};box-shadow:0 0 0 2px rgba(4,6,12,.6),0 0 20px rgba(243,167,43,1);animation:sg-pulse 1.7s ease-in-out infinite}
  .sg-mk.pulse::after{content:"";position:absolute;inset:-5px;border-radius:50%;
      border:2px solid rgba(255,205,107,.85);animation:sg-ring 1.7s ease-out infinite}
  @keyframes sg-pulse{0%,100%{box-shadow:0 0 0 2px rgba(4,6,12,.6),0 0 10px rgba(243,167,43,.75)}
      50%{box-shadow:0 0 0 2px rgba(4,6,12,.6),0 0 22px rgba(243,167,43,1)}}
  @keyframes sg-ring{0%{transform:scale(.55);opacity:.95}100%{transform:scale(2);opacity:0}}

  /* ---- tooltips ------------------------------------------------------- */
  .leaflet-tooltip.sg-tip{background:rgba(7,11,20,.96);border:1px solid rgba(148,180,255,.22);
      color:#eaf1ff;font:400 12px/1.4 Inter,system-ui,sans-serif;padding:7px 10px;border-radius:9px;
      box-shadow:0 10px 30px rgba(0,0,0,.55);white-space:nowrap}
  .leaflet-tooltip.sg-tip .n{font-weight:650;color:#fff;letter-spacing:.01em}
  .leaflet-tooltip.sg-tip .m{color:#8ea3c8;font-family:"JetBrains Mono",ui-monospace,monospace;font-size:11px;margin-top:2px}
  .leaflet-tooltip.sg-tip .m b{color:${PALETTE.sand};font-weight:600}
  .leaflet-tooltip-top.sg-tip::before{border-top-color:rgba(7,11,20,.96)}
  .leaflet-tooltip-bottom.sg-tip::before{border-bottom-color:rgba(7,11,20,.96)}
  .leaflet-tooltip-left.sg-tip::before{border-left-color:rgba(7,11,20,.96)}
  .leaflet-tooltip-right.sg-tip::before{border-right-color:rgba(7,11,20,.96)}

  /* ---- floating control cluster --------------------------------------- */
  .sg-ctrls{position:absolute;top:10px;right:10px;z-index:1000;display:flex;flex-wrap:wrap;
      align-items:center;justify-content:flex-end;gap:6px;max-width:calc(100% - 20px);
      padding:6px;border-radius:12px;background:rgba(5,8,15,.74);
      border:1px solid rgba(148,180,255,.14);backdrop-filter:blur(10px);-webkit-backdrop-filter:blur(10px);
      box-shadow:0 12px 34px rgba(0,0,0,.5);font:500 12px/1 Inter,system-ui,sans-serif;color:#c8d4ee}
  .sg-ctrls *{box-sizing:border-box}
  .sg-ctrls .sg-lbl{font-size:10px;text-transform:uppercase;letter-spacing:.08em;color:#6f7f9e;padding:0 2px}
  .sg-seg{display:inline-flex;border:1px solid rgba(148,180,255,.16);border-radius:9px;overflow:hidden}
  .sg-seg button{appearance:none;border:0;background:transparent;color:#9fb0cf;height:32px;padding:0 12px;
      font:inherit;font-weight:600;cursor:pointer;min-width:46px}
  .sg-seg button+button{border-left:1px solid rgba(148,180,255,.16)}
  .sg-seg button.on{background:linear-gradient(180deg,rgba(243,167,43,.24),rgba(243,167,43,.10));color:#ffd98a}
  .sg-ctrls select,.sg-ctrls input[type=date]{height:32px;border-radius:9px;background:rgba(148,180,255,.07);
      border:1px solid rgba(148,180,255,.16);color:#eaf1ff;font:inherit;padding:0 8px;cursor:pointer;outline:none}
  .sg-ctrls select{max-width:200px}
  .sg-ctrls input[type=date]{width:132px;font-family:"JetBrains Mono",ui-monospace,monospace;font-size:11px}
  .sg-ctrls select:focus,.sg-ctrls input:focus{border-color:rgba(55,224,255,.6);box-shadow:0 0 0 2px rgba(55,224,255,.18)}
  .sg-ctrls .sg-btn{appearance:none;height:32px;border-radius:9px;border:1px solid rgba(148,180,255,.16);
      background:rgba(148,180,255,.07);color:#c8d4ee;font:inherit;font-weight:600;padding:0 12px;cursor:pointer;
      white-space:nowrap}
  .sg-ctrls .sg-btn.on{border-color:rgba(243,167,43,.55);background:rgba(243,167,43,.16);color:#ffd98a}
  .sg-ctrls button:hover{filter:brightness(1.18)}
  .sg-ctrls button:active{transform:translateY(1px)}

  /* Leaflet's own zoom buttons: fat enough to tap */
  [data-sg-realmap] .leaflet-control-zoom a{width:36px;height:36px;line-height:36px;font-size:19px;
      background:rgba(5,8,15,.8);color:#dbe6ff;border:1px solid rgba(148,180,255,.16)}
  [data-sg-realmap] .leaflet-control-zoom a:hover{background:rgba(20,30,50,.9);color:#fff}
  [data-sg-realmap] .leaflet-bar{border:0;border-radius:9px;overflow:hidden;box-shadow:0 8px 24px rgba(0,0,0,.5)}

  /* ---- narrow screens: one compact row --------------------------------- */
  @media (max-width:640px){
    .sg-ctrls{left:8px;right:8px;top:8px;max-width:none;flex-wrap:nowrap;overflow-x:auto;
        justify-content:flex-start;gap:4px;padding:5px;scrollbar-width:none;-webkit-overflow-scrolling:touch}
    .sg-ctrls::-webkit-scrollbar{display:none}
    .sg-ctrls>*{flex:0 0 auto}
    .sg-ctrls .sg-lbl{display:none}
    .sg-seg button,.sg-ctrls .sg-btn,.sg-ctrls select,.sg-ctrls input[type=date]{height:44px;min-height:44px}
    .sg-ctrls select{max-width:124px;font-size:11px}
    .sg-ctrls input[type=date]{width:118px}
    .sg-seg button{padding:0 10px;min-width:44px}
  }
  @media (pointer:coarse){
    .sg-seg button,.sg-ctrls .sg-btn,.sg-ctrls select,.sg-ctrls input[type=date]{min-height:44px}
    [data-sg-realmap] .leaflet-control-zoom a{width:44px;height:44px;line-height:44px}
  }
  `;
  document.head.appendChild(st);
}

/* -------------------------------------------------------------------------- */
/* Leaflet-backed implementation                                              */
/* -------------------------------------------------------------------------- */
class LeafletMap {
  constructor(container, opts = {}) {
    this.opts = opts;
    this.L = opts.L;
    this.el = container;
    this.sites = [];
    this.marker = null;                 // { lat, lon, label } — selected / custom point
    this.layer = null;                  // { id, label, date }
    this.showLayer = opts.showLayer !== false;
    this.basemapId = opts.basemap || "dark";
    this.apiBase = joinBase(opts.apiBase || "");
    // our proxy: no key, and the backend silently walks back to a date with coverage
    this.tileBase = this.apiBase + "api/satellite/tile";
    this._destroyed = false;

    const L = this.L;
    const center = opts.center || DEFAULT_CENTER;
    this.map = L.map(container, {
      center: [center.lat, center.lon],
      zoom: opts.zoom ?? DEFAULT_ZOOM,
      minZoom: opts.minZoom ?? 3,
      maxZoom: opts.maxZoom ?? 13,
      zoomControl: false,
      attributionControl: true,
      worldCopyJump: true,
      zoomSnap: 0.5,
      wheelPxPerZoomLevel: 90,
      preferCanvas: false,
      tap: true,
    });
    L.control.zoom({ position: "bottomright" }).addTo(this.map);
    L.control.scale({ position: "bottomleft", imperial: false }).addTo(this.map);

    /* --- basemaps -------------------------------------------------------- */
    this.basemaps = {
      // default: real cartography, dark, with country/city labels, no key
      dark: L.layerGroup([
        L.tileLayer(ESRI_BASE_URL, { maxNativeZoom: 16, maxZoom: 19, attribution: ESRI_ATTR }),
        L.tileLayer(ESRI_REF_URL, { maxNativeZoom: 16, maxZoom: 19, pane: "overlayPane", opacity: 1 }),
      ]),
      osm: L.tileLayer(OSM_URL, { maxZoom: 19, attribution: OSM_ATTR }),
      carto: L.tileLayer(CARTO_URL, {
        subdomains: "abcd", maxZoom: 19, detectRetina: true, attribution: CARTO_ATTR,
      }),
    };
    if (!this.basemaps[this.basemapId]) this.basemapId = "dark";
    this.basemaps[this.basemapId].addTo(this.map);

    this.siteGroup = L.layerGroup().addTo(this.map);
    this.gibs = null;

    /* --- interaction ----------------------------------------------------- */
    this._onClick = (e) => {
      const cb = this.opts.onPlace;
      if (cb) cb(e.latlng.lat, e.latlng.lng);
    };
    this._onMove = (e) => {
      const cb = this.opts.onHover;
      if (!cb) return;
      // accept both onHover(lat, lon) and the canvas map's onHover({lat, lon})
      if (cb.length >= 2) cb(e.latlng.lat, e.latlng.lng);
      else cb({ lat: e.latlng.lat, lon: e.latlng.lng });
    };
    this.map.on("click", this._onClick);
    this.map.on("mousemove", this._onMove);
    this.map.on("tileerror", (e) => {
      // 204 / missing orbit day — expected, keep it quiet but visible in console
      if (window.__SG_REALMAP_DEBUG) console.debug("[sg-realmaps] tile miss", e.tile?.src);
    });

    this._buildControls();

    // Leaflet sometimes measures before CSS settles (flex/clamp heights).
    setTimeout(() => { if (!this._destroyed) this.map.invalidateSize(); }, 220);
    this._onWinResize = () => { if (!this._destroyed) this.map.invalidateSize(); };
    window.addEventListener("resize", this._onWinResize);

    /* --- layers catalogue + catalogue sites ------------------------------ */
    this.layers = opts.layers || null;
    this.dates = opts.dates || null;
    if (opts.layers) this._populateLayerSelect(opts.layers, opts.dates, false);
    this._fetchCatalogue();

    if (opts.layer) this.setLayer(opts.layer);
    else if (opts.autoLayer !== false) this._autoLayer();
  }

  /* ------------------------------------------------------------ catalogue */
  async _fetchCatalogue() {
    // apiBase is set on the standalone/test page (absolute); the dashboard leaves
    // it empty and the relative path resolves against /solarguard/.
    const urls = this.apiBase
      ? [this.apiBase + "api/satellite/layers"]
      : ["api/satellite/layers"];
    for (const u of urls) {
      try {
        const r = await fetch(u, { mode: "cors" });
        if (!r.ok) continue;
        const j = await r.json();
        if (j && Array.isArray(j.layers) && j.layers.length) {
          this.layers = j.layers; this.dates = j.dates || {};
          this._populateLayerSelect(this.layers, this.dates, false);
          if (!this.layer && this.opts.autoLayer !== false) this._autoLayer();
          return;
        }
      } catch (_) { /* try next */ }
    }
    if (!this.layers) {
      this.layers = FALLBACK_LAYERS;
      this._populateLayerSelect(this.layers, {}, true);
    }
  }

  _autoLayer() {
    if (this.layer || !this.layers || !this.layers.length) return;
    const id = this.layers[0].id;
    const date = (this.dates && this.dates[id]) || new Date().toISOString().slice(0, 10);
    this.setLayer({ id, label: this.layers[0].label, date });
  }

  _layerMeta(id) { return (this.layers || []).find((l) => l.id === id); }

  _populateLayerSelect(layers, dates, lockSel) {
    const sel = this.sel;
    if (!sel) return;
    sel.innerHTML = layers.map((l) => `<option value="${esc(l.id)}">${esc(l.label)}</option>`).join("");
    if (lockSel) sel.disabled = true;
    sel.value = (this.layer && this.layer.id) || layers[0].id;
    if (this.date) {
      const picked = this.layer?.date || (dates && dates[sel.value]) || "";
      this.date.value = picked;
    }
  }

  /* ------------------------------------------------------------- controls */
  _buildControls() {
    const o = this.opts;
    const wrap = document.createElement("div");
    wrap.className = "sg-ctrls";
    wrap.setAttribute("role", "group");
    wrap.setAttribute("aria-label", "Map controls");
    wrap.innerHTML = `
      <div class="sg-seg" role="group" aria-label="Basemap style">
        <button type="button" data-bm="dark" class="${this.basemapId === "dark" ? "on" : ""}">Dark</button>
        <button type="button" data-bm="osm" class="${this.basemapId === "osm" ? "on" : ""}">OSM</button>
        <button type="button" data-bm="carto" class="${this.basemapId === "carto" ? "on" : ""}">Carto</button>
      </div>
      <select class="sg-sel" aria-label="Satellite layer"></select>
      <input class="sg-date" type="date" aria-label="Satellite layer date">
      <button type="button" class="sg-btn sg-dust ${this.showLayer ? "on" : ""}"
              aria-pressed="${this.showLayer}">${this.showLayer ? "Dust on" : "Dust off"}</button>`;
    this.el.appendChild(wrap);
    this.controls = wrap;
    this.sel = wrap.querySelector(".sg-sel");
    this.date = wrap.querySelector(".sg-date");
    this.dust = wrap.querySelector(".sg-dust");

    if (this.layers) this._populateLayerSelect(this.layers, this.dates, false);
    else this.sel.innerHTML = `<option>loading layers…</option>`;

    wrap.querySelectorAll("[data-bm]").forEach((b) => {
      b.addEventListener("click", () => this.setBasemap(b.dataset.bm));
    });
    this.sel.addEventListener("change", () => {
      const id = this.sel.value;
      const date = this.date.value || (this.dates && this.dates[id]) || "";
      const meta = this._layerMeta(id);
      this.setLayer({ id, label: meta?.label, date });
    });
    this.date.addEventListener("change", () => {
      if (!this.layer) return;
      this.setLayer({ ...this.layer, date: this.date.value });
    });
    this.dust.addEventListener("click", () => this.setLayerVisible(!this.showLayer));
  }

  _syncControlState() {
    if (!this.controls) return;
    this.controls.querySelectorAll("[data-bm]").forEach((b) =>
      b.classList.toggle("on", b.dataset.bm === this.basemapId));
    if (this.layer && this.sel) this.sel.value = this.layer.id;
    if (this.layer && this.date && this.layer.date) this.date.value = this.layer.date;
    if (this.dust) {
      this.dust.classList.toggle("on", this.showLayer);
      this.dust.textContent = this.showLayer ? "Dust on" : "Dust off";
      this.dust.setAttribute("aria-pressed", String(this.showLayer));
    }
  }

  /* --------------------------------------------------------- public API */
  setBasemap(id) {
    if (!this.basemaps || !this.basemaps[id] || id === this.basemapId) {
      if (this.basemaps && this.basemaps[id]) this._syncControlState();
      return;
    }
    if (this.map.hasLayer(this.basemaps[this.basemapId])) this.map.removeLayer(this.basemaps[this.basemapId]);
    this.basemapId = id;
    this.basemaps[id].addTo(this.map);
    this.basemaps[id].bringToBack();
    this._syncControlState();
  }

  setSites(sites) {
    this.sites = Array.isArray(sites) ? sites : [];
    this._renderMarkers();
  }

  setMarker(lat, lon, label) {
    this.marker = (lat == null || lon == null) ? null : { lat: +lat, lon: +lon, label: label || "" };
    this._renderMarkers();
  }

  setLayer(layer) {
    if (!layer || !layer.id) {
      if (this.gibs) { this.map.removeLayer(this.gibs); this.gibs = null; }
      this.layer = null;
      if (this.sel) this.sel.value = "";
      if (this.opts.onLayerChange) this.opts.onLayerChange(null);
      return;
    }
    const { id, label, date } = layer;
    this.layer = { id, label, date };
    if (this.gibs) { this.map.removeLayer(this.gibs); this.gibs = null; }

    const meta = this._layerMeta(id);
    const lvl = /Level(\d+)/.exec(meta?.tms || "");
    const maxNativeZoom = lvl ? +lvl[1] : 6;
    // the GIBS layer needs a real day; the backend also walks back server-side
    const d = date || (this.dates && this.dates[id]) || new Date().toISOString().slice(0, 10);
    const url = `${this.tileBase}/${encodeURIComponent(id)}/${encodeURIComponent(d)}/{z}/{x}/{y}.png`;

    this.gibs = this.L.tileLayer(url, {
      opacity: 0.75,
      attribution: GIBS_ATTR,
      maxNativeZoom,
      maxZoom: 13,
      tileSize: 256,
      errorTileUrl: BLANK_TILE,
      className: "sg-gibs",
      updateWhenIdle: false,
      keepBuffer: 2,
    });
    this.stats = this.stats || { load: 0, miss: 0 };
    this.gibs.on("tileload", () => { this.stats.load++; });
    this.gibs.on("tileerror", () => { this.stats.miss++; });
    if (this.showLayer) this.gibs.addTo(this.map);

    this._syncControlState();
    if (this.opts.onLayerChange) this.opts.onLayerChange({ ...this.layer });
  }

  setLayerVisible(v) {
    this.showLayer = !!v;
    if (this.gibs) {
      if (this.showLayer && !this.map.hasLayer(this.gibs)) this.gibs.addTo(this.map);
      else if (!this.showLayer && this.map.hasLayer(this.gibs)) this.map.removeLayer(this.gibs);
    }
    this._syncControlState();
  }

  focus(lat, lon, zoom) {
    if (lat == null || lon == null) return;
    const z = zoom ?? this.map.getZoom();
    this.map.setView([+lat, +lon], Math.max(this.map.options.minZoom, Math.min(this.map.options.maxZoom, +z)), { animate: true });
  }

  /* ----------------------------------------------------------- markers */
  _icon(sel, pulse) {
    const size = sel ? 22 : 18;
    const cls = "sg-mk" + (sel ? " sel" : "") + (pulse ? " pulse" : "");
    return this.L.divIcon({
      className: cls, html: "", iconSize: [size, size], iconAnchor: [size / 2, size / 2],
      tooltipAnchor: [0, -size / 2 - 2],
    });
  }

  _tip(site) {
    return `<div><div class="n">${esc((site.name || site.id || "Site").replace(/ \(.*\)$/, ""))}</div>
      <div class="m"><b>${esc(capLabel(site.capacity_mwp))}</b>${site.climate ? " · " + esc(site.climate) : ""}${
      site.region ? " · " + esc(site.region) : ""}</div></div>`;
  }

  _renderMarkers() {
    if (!this.siteGroup) return;
    this.siteGroup.clearLayers();
    const m = this.marker;
    for (const s of this.sites) {
      if (s.lat == null || s.lon == null) continue;
      const sel = !!(m && Math.abs(m.lat - s.lat) < 1e-6 && Math.abs(m.lon - s.lon) < 1e-6);
      const mk = this.L.marker([s.lat, s.lon], {
        icon: this._icon(sel, false), title: s.name || s.id, zIndexOffset: sel ? 500 : 0,
      });
      mk.bindTooltip(this._tip(s), { className: "sg-tip", direction: "top", offset: [0, -2], opacity: 1 });
      mk.on("click", () => {
        this.marker = { lat: s.lat, lon: s.lon, label: s.name };
        this._renderMarkers();
        if (this.opts.onSelect) this.opts.onSelect(s);
      });
      mk.addTo(this.siteGroup);
    }
    // custom click-to-place point (not one of the catalogue sites)
    if (m) {
      const isCatalogue = this.sites.some((s) => Math.abs(s.lat - m.lat) < 1e-6 && Math.abs(s.lon - m.lon) < 1e-6);
      if (!isCatalogue) {
        const mk = this.L.marker([m.lat, m.lon], { icon: this._icon(true, true), title: m.label || "custom site", zIndexOffset: 700 });
        if (m.label) mk.bindTooltip(this._tip({ name: m.label, capacity_mwp: null, climate: "custom location" }),
          { className: "sg-tip", direction: "top", offset: [0, -2], opacity: 1 });
        mk.addTo(this.siteGroup);
      }
    }
  }

  /* ------------------------------------------------------------ teardown */
  destroy() {
    if (this._destroyed) return;
    this._destroyed = true;
    window.removeEventListener("resize", this._onWinResize);
    if (this.controls && this.controls.parentNode) this.controls.parentNode.removeChild(this.controls);
    try { this.map.off(); this.map.remove(); } catch (_) {}
    if (this.el && this.el.dataset) delete this.el.dataset.sgRealmap;
    this.siteGroup = null; this.gibs = null; this.map = null;
  }
}

/* -------------------------------------------------------------------------- */
/* Canvas fallback (same interface, via sg-map.js)                            */
/* -------------------------------------------------------------------------- */
async function buildFallback(el, opts, warn) {
  console.warn("[sg-realmaps] Leaflet could not be loaded from the CDN — falling back to the " +
                "canvas map (sg-map.js). The dashboard keeps a working map.", warn || "");
  const mod = await import("./sg-map.js");
  let canvas = el;
  if (el.tagName !== "CANVAS") {
    canvas = document.createElement("canvas");
    canvas.style.display = "block";
    canvas.style.width = "100%";
    canvas.style.height = "100%";
    el.appendChild(canvas);
  }
  const impl = new mod.SaudiMap(canvas, opts);
  impl.setLayerVisible = impl.setLayerVisible.bind(impl);
  return impl;
}

/* -------------------------------------------------------------------------- */
/* Facade: returns synchronously, queues calls until the real map is ready     */
/* -------------------------------------------------------------------------- */
export function createRealMap(el, opts = {}) {
  if (!el) {
    console.error("[sg-realmaps] createRealMap(): no container element given.");
    return { setSites() {}, setMarker() {}, setLayer() {}, setLayerVisible() {}, focus() {}, setBasemap() {}, destroy() {}, showLayer: false, ready: Promise.resolve(null) };
  }

  const facade = {
    _impl: null,
    _queue: [],
    _showLayer: opts.showLayer !== false,
    _destroyed: false,
    ready: null,
    showLayer: true,
  };

  const METHODS = ["setSites", "setMarker", "setLayer", "setLayerVisible", "focus", "setBasemap"];
  for (const name of METHODS) {
    facade[name] = (...args) => {
      if (facade._destroyed) return;
      if (facade._impl) return facade._impl[name](...args);
      facade._queue.push([name, args]);
    };
  }
  facade.destroy = () => {
    if (facade._destroyed) return;
    facade._destroyed = true;
    facade._queue.length = 0;
    if (facade._impl && facade._impl.destroy) facade._impl.destroy();
    facade._impl = null;
  };
  Object.defineProperty(facade, "showLayer", {
    get: () => (facade._impl ? facade._impl.showLayer : facade._showLayer),
    set: (v) => { facade._showLayer = !!v; if (facade._impl) facade._impl.setLayerVisible?.(facade._showLayer); },
    enumerable: true,
  });

  facade.ready = (async () => {
    injectStyle();
    let impl = null;
    try {
      if (!(window.L && window.L.map)) {
        injectCss(LEAFLET_CSS, "sg-leaflet-css");
        await Promise.race([
          loadScript(LEAFLET_JS, "sg-leaflet-js"),
          new Promise((_, rej) => setTimeout(() => rej(new Error("Leaflet CDN timeout")), 9000)),
        ]);
      }
      if (!(window.L && window.L.map)) throw new Error("Leaflet did not initialise");

      // Leaflet needs a positioned block container; the dashboard hands us a
      // <canvas>, so swap it for a div in place (same id/classes → same CSS).
      let host = el;
      if (el.tagName === "CANVAS") {
        host = document.createElement("div");
        host.id = el.id || "";
        host.className = el.className || "";
        if (el.id) el.removeAttribute("id");
        el.style.display = "none";
        el.parentNode.insertBefore(host, el);
        host._sgReplacedCanvas = el;
      }
      host.dataset.sgRealmap = "1";
      host.classList.add("sg-realmap");

      impl = new LeafletMap(host, { ...opts, showLayer: facade._showLayer, L: window.L });
    } catch (err) {
      try { impl = await buildFallback(el, opts, err); }
      catch (err2) {
        console.error("[sg-realmaps] fallback canvas map also failed:", err2);
        impl = null;
      }
    }

    if (facade._destroyed) { impl?.destroy?.(); return null; }

    if (impl) {
      impl.showLayer = facade._showLayer;
      if (impl.setLayerVisible && facade._showLayer === false) impl.setLayerVisible(false);
      facade._impl = impl;
      for (const [name, args] of facade._queue) { try { impl[name](...args); } catch (e) { console.warn("[sg-realmaps]", name, e); } }
      facade._queue.length = 0;
    }
    return impl;
  })();

  facade.ready.catch(() => {});
  return facade;
}

export default createRealMap;
