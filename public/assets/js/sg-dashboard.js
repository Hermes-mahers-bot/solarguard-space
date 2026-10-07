/* ============================================================================
   sg-dashboard.js — the customer dashboard.

   The whole page runs off TWO numbers the owner types: the cost of one
   cleaning pass (SAR, whole plant) and the plant's max capacity (kW). Every
   other figure — the recommended interval, the loss, the money, the water and
   the verdict — is derived from the API.

   The map is the second thing on the page and doubles as the place-picker:
   tapping it prices a plant at that lat/lon. The map layer is pluggable: it
   prefers the real Leaflet map and falls back to the built-in canvas map if
   the CDN is unreachable, so the page can never end up with a dead map.

   The AI block (#ai-out) is deliberately NOT populated here — it is a styled
   placeholder that the model team wires separately.
   ========================================================================= */
import { jget, jpost, nf, money, pct, clamp, drawProjection, drawEnergy, toast } from "./sg-core.js";

const $ = (s) => document.querySelector(s);

const state = {
  siteId: "dammam",
  custom: null,
  capacity_kwp: 100000,          // input 2 (kW)
  cost_sar: 180000,              // input 1 (SAR, whole plant)
  cleaning_interval_days: 10,    // internal baseline only: the "typical habit"
  horizon_days: 14,
  rate_sar_per_mwp: 1800,        // falls back to a sane dry-clean rate
  sites: [], layers: [], dates: {},
  layer: null, dustOn: true,
  lastReport: null,
  history: [],
};

let map = null;            // whichever map implementation won
let mapImpl = "none";

const MWP = (kwp) => kwp / 1000;
const fmtMWp = (kwp) => `${nf(MWP(kwp), MWP(kwp) % 1 ? 1 : 0)} MWp`;
/* SAR per MWp is what the API wants; the owner thinks in whole-plant SAR. */
const costPerMwp = () => state.cost_sar / Math.max(MWP(state.capacity_kwp), 0.001);

/* --------------------------------------------------------------- map */
function defaultLayer() {
  const l = state.layers.find((x) => /dust/i.test(x.id))
    || state.layers.find((x) => /aerosol/i.test(x.id))
    || state.layers[0];
  if (!l) return null;
  state.layer = { id: l.id, label: l.label, date: state.dates[l.id] || "" };
  return state.layer;
}

async function initMap() {
  const opts = {
    controls: false,                        // the page is the place-picker, not a GIS tool
    onPlace: (lat, lon) => placeSite(lat, lon),
    onHover: (ll) => {
      const el = $("#map-coords");
      if (el) el.textContent = `${Number(ll.lat).toFixed(3)}°N  ${Number(ll.lon).toFixed(3)}°E`;
    },
    onSelect: (site) => { if (site && site.id) selectSite(site.id); },
  };
  if (state.layers.length) {
    opts.layers = state.layers;
    opts.dates = state.dates;
    opts.autoLayer = false;
    opts.layer = defaultLayer();
  }
  // 1. real map (Leaflet + basemap tiles + NASA GIBS dust overlay)
  try {
    const mod = await import("./sg-realmaps.js");
    map = mod.createRealMap($("#realmap"), opts);
    mapImpl = "leaflet";
    /* The map module always builds its own GIS cluster (basemap switch, layer
       dropdown, date picker, dust button) — but only once Leaflet has finished
       loading from the CDN, so we cannot just look for it now. This is a
       customer place-picker, not a GIS tool, so we strip that cluster the
       moment it appears; the two plain buttons under the map do the same job.
       Nothing the module needs lives in that node. */
    const stripControls = () => {
      const c = $("#realmap") && $("#realmap").querySelector(".sg-ctrls");
      if (c) c.remove();
      return !!c;
    };
    stripControls();
    if (map.ready && typeof map.ready.then === "function") map.ready.then(stripControls).catch(() => {});
    const host = $("#realmap");
    if (host && window.MutationObserver) {
      const obs = new MutationObserver(stripControls);
      obs.observe(host, { childList: true });
      setTimeout(() => obs.disconnect(), 20000);
    }
    setMapMode("live satellite view");
    return;
  } catch (e) {
    console.warn("[solarguard] real map unavailable, using canvas map:", e.message);
  }
  // 2. canvas fallback (no CDN, no external tiles)
  $("#realmap").style.display = "none";
  $("#sg-map").style.display = "block";
  const { SaudiMap } = await import("./sg-map.js");
  map = new SaudiMap($("#sg-map"), opts);
  mapImpl = "canvas";
  setMapMode("offline map");
}

function setMapMode(txt) {
  const el = $("#map-mode");
  if (el) el.textContent = txt;
}

function placeSite(lat, lon) {
  if (lat < 15 || lat > 33.5 || lon < 33 || lon > 56.5) {
    toast("That point is outside Saudi Arabia — pick a spot inside the Kingdom.");
    return;
  }
  const near = state.sites.find((s) => Math.abs(s.lat - lat) < 0.06 && Math.abs(s.lon - lon) < 0.06);
  if (near) { selectSite(near.id); return; }
  state.custom = { lat: +lat.toFixed(4), lon: +lon.toFixed(4),
                   name: `${lat.toFixed(2)}°N ${lon.toFixed(2)}°E` };
  state.siteId = null;
  if (map) map.setMarker(state.custom.lat, state.custom.lon, state.custom.name);
  toast(`Pricing a plant at ${lat.toFixed(3)}°N, ${lon.toFixed(3)}°E`);
  refresh();
}

/** Tapping one of the catalogued Saudi plants adopts its nameplate size. */
function selectSite(id) {
  const s = state.sites.find((x) => x.id === id);
  if (!s) return;
  state.siteId = id;
  state.custom = null;
  if (s.capacity_mwp) {
    state.capacity_kwp = s.capacity_mwp * 1000;
    $("#in-cap").value = state.capacity_kwp;
    $("#cap-interest").textContent = fmtMWp(state.capacity_kwp);
    // keep the owner's cost line coherent with the plant we just adopted
    state.cost_sar = Math.round((state.rate_sar_per_mwp * s.capacity_mwp) / 1000) * 1000;
    $("#in-cost").value = state.cost_sar;
  }
  if (map) { map.setMarker(s.lat, s.lon, s.name); map.focus(s.lat, s.lon, 7); }
  refresh();
}

function setDust(on) {
  state.dustOn = on;
  if (map) map.setLayerVisible(on);
  const b = $("#layer-toggle");
  if (b) b.textContent = on ? "Hide dust from space" : "Show dust from space";
}

/* --------------------------------------------------------------- inputs */
function readCapacity() {
  const raw = Number($("#in-cap").value);
  if (!Number.isFinite(raw) || raw <= 0) {
    $("#param-error").textContent = "Enter a solar capacity greater than 0 kW.";
    return false;
  }
  state.capacity_kwp = raw;
  $("#cap-interest").textContent = fmtMWp(raw);
  $("#param-error").textContent = "";
  return true;
}

function readCost() {
  const raw = Number($("#in-cost").value);
  if (!Number.isFinite(raw) || raw < 0) {
    $("#param-error").textContent = "Enter a cleaning cost of 0 SAR or more.";
    return false;
  }
  state.cost_sar = raw;
  $("#param-error").textContent = "";
  return true;
}

let refreshTimer = null;
function scheduleRefresh() {
  clearTimeout(refreshTimer);
  refreshTimer = setTimeout(() => refresh(), 400);
}

function wireInputs() {
  // live MWp read-out while typing, fetch once the field is committed
  $("#in-cap").addEventListener("input", () => {
    const v = Number($("#in-cap").value);
    $("#cap-interest").textContent = Number.isFinite(v) && v > 0 ? fmtMWp(v) : "—";
  });
  $("#in-cap").addEventListener("change", () => { if (readCapacity()) scheduleRefresh(); });
  $("#in-cost").addEventListener("change", () => { if (readCost()) scheduleRefresh(); });
}

function wireMapTools() {
  const t = $("#layer-toggle");
  if (t) t.onclick = () => setDust(!state.dustOn);
  const r = $("#reset-view");
  if (r) r.onclick = () => { if (map) map.focus(24.2, 45.4, mapImpl === "leaflet" ? 6 : 5); };
}

/* --------------------------------------------------------------- boot */
async function boot() {
  const [sites, layers] = await Promise.all([
    jget("/sites").catch((e) => ({ error: e.message })),
    jget("/satellite/layers").catch(() => ({ error: "unavailable" })),
  ]);
  if (sites.error) {
    $("#param-error").textContent = "Could not reach the SolarGuard service — please retry.";
    toast("SolarGuard service unavailable: " + sites.error);
    return;
  }

  state.sites = sites.sites || [];
  const preset = (sites.cleaning_presets || {}).dry_saudi;
  if (preset && preset.sar_per_mwp) state.rate_sar_per_mwp = preset.sar_per_mwp;
  if (!layers.error) {
    state.layers = layers.layers || [];
    state.dates = layers.dates || {};
  }

  // Start from the Dammam weather cell but keep the owner's two defaults.
  const start = state.sites.find((s) => s.id === state.siteId) || state.sites[0];
  if (start) state.siteId = start.id;
  $("#cap-interest").textContent = fmtMWp(state.capacity_kwp);

  await initMap();
  if (map) { map.setSites(state.sites); if (start) map.setMarker(start.lat, start.lon, start.name); }

  wireInputs();
  wireMapTools();
  initChat();
  await refresh();
}

/* --------------------------------------------------------------- AI
   backend/sg_ai.py serves this: P(sandstorm) for the next three days, tomorrow's
   energy, tomorrow's soiling — each with the error measured on held-out days.
   It is deliberately separate from the physics verdict above: the AI predicts,
   the calibrated physics engine decides when a crew is worth sending. */
const AI_LEVEL_CLASS = { "quiet": "quiet", "watch": "watch", "storm likely": "storm" };

async function aiPredict() {
  const chip = $("#ai-status");
  try {
    const r = await jget("/ai", {
      site: state.custom ? undefined : state.siteId,
      lat: state.custom?.lat, lon: state.custom?.lon,
      capacity_kwp: Math.round(state.capacity_kwp),
    });
    if (!r.ok) throw new Error(r.error || "unavailable");
    const set = (id, txt) => { const el = $(id); if (el) el.textContent = txt; };

    if (chip) { chip.textContent = "AI · live"; chip.className = "chip ok"; }
    set("#ai-asof", `as of ${r.as_of}`);
    [1, 2, 3].forEach((h) => {
      const el = $(`#ai-storm-t${h}`);
      const s = r.storm?.[`t${h}`];
      if (!el || !s) return;
      el.textContent = `${s.level} · ${(s.p * 100).toFixed(s.p < 0.01 ? 2 : 0)} %`;
      el.className = "v lvl " + (AI_LEVEL_CLASS[s.level] || "quiet");
    });
    set("#ai-output-kwh", nf(r.output.kwh, 0));
    set("#ai-output-kwp", nf(r.output.kwh_per_kwp, 2));
    set("#ai-output-err", `±${nf((r.output.error_kwh_per_kwp || 0) * state.capacity_kwp, 0)}`);
    set("#ai-soiling", nf(r.soiling.loss_pct, 1));
    set("#ai-soiling-err", `±${nf(r.soiling.error_points, 1)}`);

    const sk = r.skill || {};
    set("#ai-skill-note",
      `Measured on days the model never saw: it caught ${nf(sk.storm_recall_pct, 0)} % of sandstorms, `
      + `${nf(sk.storm_precision_pct, 0)} % of its alarms were real (AUC ${nf(sk.storm_auc, 3)}). `
      + `Output ±${nf(r.output.error_kwh_per_kwp, 3)} kWh/kWp · soiling ±${nf(r.soiling.error_points, 1)} points. `
      + `A storm here means PM10 ≥ ${nf(r.model.storm_threshold_ugm3, 0)} µg/m³ — three times this site's own `
      + `median, not a fixed number. Soiling assumes no cleaning: rain is the only thing washing the glass.`);
  } catch (e) {
    if (chip) { chip.textContent = "AI offline"; chip.className = "chip pending"; }
    const n = $("#ai-skill-note");
    if (n) n.textContent = "The AI is not answering right now (" + e.message
      + "). Everything above still comes from the calibrated physics model.";
  }
}

/* --------------------------------------------------------------- refresh */
let inflight = 0;
async function refresh() {
  const token = ++inflight;
  try {
    const rep = await jget("/report", {
      site: state.custom ? undefined : state.siteId,
      lat: state.custom?.lat, lon: state.custom?.lon, name: state.custom?.name,
      capacity_kwp: Math.round(state.capacity_kwp),
      cleaning_interval_days: state.cleaning_interval_days,
      horizon_days: state.horizon_days,
      cost_per_mwp_sar: +costPerMwp().toFixed(2),
    });
    if (token !== inflight) return;
    state.lastReport = rep;
    aiPredict();                    // fire and forget: the AI must never block the page
    $("#nav-status").innerHTML = '<span class="dot"></span> live';
    render(rep);
  } catch (e) {
    if (token !== inflight) return;
    $("#param-error").textContent = "Could not price this location — " + e.message;
    $("#nav-status").innerHTML = '<span class="dot" style="background:#ff5f6d"></span> offline';
  }
}

/* --------------------------------------------------------------- render */
function render(rep) {
  const { verdict: v, days } = rep;
  const fs = rep.report.fixed_schedule;
  const d0 = fs.rows[0] || days[0];
  const site = rep.site || {};

  /* who / where */
  const where = state.custom
    ? `your pin at ${state.custom.lat.toFixed(3)}°N, ${state.custom.lon.toFixed(3)}°E`
    : `${site.region || ""} · ${Number(site.lat).toFixed(3)}°N, ${Number(site.lon).toFixed(3)}°E`;
  $("#site-title").textContent = state.custom ? "Your chosen point" : (site.name || "This site");
  $("#site-sub").textContent = `${where} · ${pct(v.current_soiling_loss_pct)} of today's energy already lost to dust`;
  $("#cap-interest").textContent = fmtMWp(state.capacity_kwp);
  $("#verdict-stamp").textContent = `${rep.generated_utc.slice(11, 16)} UTC`;

  /* the answer */
  const box = $("#verdict-box");
  box.className = "verdict " + (v.decision === "clean_now" ? "now" : "wait");
  $("#verdict-word").textContent = v.decision === "clean_now" ? "CLEAN NOW" : "WAIT";
  $("#verdict-sub").textContent = v.decision === "clean_now"
    ? `a wash pays for itself in about ${nf(v.payback_days, 1)} days at this dust load`
    : "hold the crew — cleaning now would cost more than the dust takes";

  const p = rep.report.policy.adaptive;
  const perYear = p.cleaning_events_per_year || 0;
  const recoDays = perYear > 0 ? Math.round(365 / perYear) : null;
  $("#reco-line").textContent = recoDays
    ? `about every ${recoDays} days`
    : "wait for the next heavy dust";

  $("#urgency-val").textContent = `${nf(v.urgency, 0)}/100 · dust risk today: ${v.risk_today}`;
  $("#urgency-bar").style.width = `${clamp(v.urgency, 0, 100)}%`;
  $("#verdict-reason").innerHTML = `<p class="small">${v.reason}</p>`;

  /* the three headline numbers */
  $("#k-loss").textContent = pct(d0.soiling_loss_pct);
  $("#k-lost").textContent = `${nf(d0.lost_kwh)} kWh`;
  $("#k-lost-sar").textContent = `about ${money(d0.lost_sar)} today`;
  $("#k-risk").textContent = money(v.next_7d_money_at_risk_sar);
  $("#k-cost").textContent = `one cleaning pass: ${money(v.cleaning_cost_sar)}`;

  /* two charts, no more */
  drawProjection($("#chart-projection"), fs.rows);
  drawEnergy($("#chart-energy"), fs.rows);
  $("#proj-note").textContent = `${days.length} days ahead`;
  $("#energy-note").textContent =
    `${nf(fs.energy_kwh / 1000)} MWh delivered · ${nf(fs.lost_kwh / 1000)} MWh lost`;

  /* the year, priced — the one money table */
  const a = rep.annual;
  const rows = [
    ["Cleaning weekly", a.habits.weekly],
    [`Typical habit (every ${state.cleaning_interval_days} days)`, a.habits.industry_today],
    ["Our recommendation", a.habits.adaptive],
    ["Never cleaning", a.habits.never],
  ];
  const best = Math.min(...rows.map(([, r]) => r.net_cost_sar));
  const sarShort = (val) =>
    Math.abs(val) >= 1e6 ? `${nf(val / 1e6, 1)}M` : `${nf(val / 1e3, 0)}k`;
  $("#habits-table tbody").innerHTML = rows.map(([label, r]) => `
    <tr><td>${label}${r.net_cost_sar === best ? ' <span class="pill live">cheapest</span>' : ""}</td>
    <td class="num">${r.cleaning_events_per_year} <span class="u">/yr</span></td>
    <td class="num">${pct(r.mean_soiling_loss_pct)}</td>
    <td class="num"><b>${sarShort(r.net_cost_sar)}</b> <span class="u">SAR</span></td></tr>`).join("");

  const opp = a.opportunity || {};
  const fewer = Math.abs(nf(opp.events_saved));
  $("#habits-note").innerHTML =
    `Cost per year counts the cleaning spend plus the energy dust costs you. Loss is the average`
    + ` soiling loss across the year. Against a typical 10-day habit, our plan `
    + `<b style="color:var(--green)">saves ${money(opp.sar_saved_year)} a year</b>`
    + ` and needs ${fewer} ${opp.events_saved >= 0 ? "fewer" : "more"} washes.`;

  /* water — the desert matters here */
  const litres = (val) => val >= 1e6 ? `${nf(val / 1e6, 1)} M L` : `${nf(val)} L`;
  $("#w-pass").textContent = litres(2500 * MWP(state.capacity_kwp));
  $("#w-habit").textContent =
    `${litres(a.habits.industry_today.water_litres)}  (${a.habits.industry_today.cleaning_events_per_year} washes)`;
  $("#w-tuned").textContent =
    `${litres(a.habits.adaptive.water_litres)}  (${a.habits.adaptive.cleaning_events_per_year} washes)`;
  $("#w-saved").textContent =
    `${litres(Math.max(0, a.habits.industry_today.water_litres - a.habits.adaptive.water_litres))}/yr`;
}

/* --------------------------------------------------------------- agent */
function initChat() {
  const chat = $("#chat");
  const add = (cls, html) => {
    const d = document.createElement("div");
    d.className = "msg " + cls;
    d.innerHTML = html;
    chat.appendChild(d);
    return d;
  };
  const suggestions = [
    "Is now a good time to clean this site?",
    "What did the dust look like over Riyadh last month?",
    "Move the map to Sudair",
    "How much water would I save in a year?",
  ];
  const sug = $("#chat-suggestions");
  suggestions.forEach((q) => {
    const b = document.createElement("button");
    b.textContent = q;
    b.onclick = () => send(q);
    sug.appendChild(b);
  });

  add("bot", `<p>I'm the SolarGuard agent. Ask me anything about this plant — dust, water,
    money or timing — or tap a suggestion. I can also move the map for you.</p>`);

  async function send(text) {
    const q = (text || $("#chat-input").value || "").trim();
    if (!q) return;
    $("#chat-input").value = "";
    add("user", `<p>${q.replace(/</g, "&lt;")}</p>`);
    const t = add("bot", `<span class="typing"><span></span><span></span><span></span></span>
      <div class="small dim" style="margin-top:6px">reading the live feeds…</div>`);
    try {
      const out = await jpost("/assistant", {
        question: q, history: state.history.slice(-6),
        site: state.custom ? undefined : state.siteId,
        site_id: state.custom ? undefined : state.siteId,
        lat: state.custom?.lat, lon: state.custom?.lon,
        capacity_kwp: Math.round(state.capacity_kwp),
      });
      if (!out.ok) { t.innerHTML = `<p>${out.message || "the agent is unavailable right now."}</p>`; return; }
      state.history.push({ role: "user", content: q }, { role: "assistant", content: out.answer });
      const body = (out.answer || "")
        .replace(/&/g, "&amp;").replace(/</g, "&lt;")
        .replace(/\*\*(.+?)\*\*/g, "<b>$1</b>")
        .replace(/^#{1,4}\s*(.+)$/gm, "<b>$1</b>")
        .split(/\n{2,}/).map((para) => `<p>${para.replace(/\n/g, "<br>")}</p>`).join("");
      t.innerHTML = body;

      for (const act of out.actions || []) {
        if (act.type === "place_site" && act.site) {
          const known = state.sites.find((x) => x.id === act.site.id);
          if (known) selectSite(known.id);
          else {
            state.siteId = null;
            state.custom = { lat: act.site.lat, lon: act.site.lon, name: act.site.name };
            if (map) { map.setMarker(act.site.lat, act.site.lon, act.site.name); map.focus(act.site.lat, act.site.lon, 7); }
            refresh();
          }
          toast(act.label || "Map moved");
        } else if (act.type === "show_layer" && act.layer) {
          state.layer = { id: act.layer, label: act.layer, date: act.date || "" };
          if (map) map.setLayer(state.layer);
          setDust(true);
          toast(act.label || "Satellite dust layer switched");
        }
      }
    } catch (e) {
      t.innerHTML = `<p>Sorry — the agent could not answer just now.</p>`;
    }
  }
  $("#chat-send").onclick = () => send();
  $("#chat-input").onkeydown = (e) => { if (e.key === "Enter") send(); };
}

let resizeTimer = null;
addEventListener("resize", () => {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(() => { if (state.lastReport) render(state.lastReport); }, 250);
});

boot();
