/* ============================================================================
   sg-dashboard.js — the operator dashboard.

   One state object; one refresh() that re-renders everything from the API.
   The map layer is pluggable: it prefers the real Leaflet map (OPEN data tiles +
   NASA GIBS overlay) and falls back to the built-in canvas map if the CDN is
   unreachable, so the page can never end up with a dead map.
   ========================================================================= */
import { jget, jpost, nf, money, pct, clamp, dateShort, riskColor, drawProjection,
         drawEnergy, drawSeries, toast } from "./sg-core.js";

const $ = (s) => document.querySelector(s);

const state = {
  siteId: "dammam",
  custom: null,
  capacity_kwp: 100000,
  cleaning_interval_days: 10,
  cost_per_mwp_sar: null,
  horizon_days: 14,
  sites: [], presets: {}, layers: [], dates: {},
  lastReport: null,
  history: [],
};

let map = null;            // whichever map implementation won
let mapImpl = "none";

const fmtCapacity = (kwp) => kwp >= 1000
  ? `${nf(kwp / 1000, kwp % 1000 ? 1 : 0)} MWp` : `${nf(kwp)} kWp`;

/* --------------------------------------------------------------- map */
async function initMap() {
  const opts = {
    onPlace: (lat, lon) => placeSite(lat, lon),
    onHover: (ll) => { $("#map-coords").textContent = `${ll.lat.toFixed(3)}°N  ${ll.lon.toFixed(3)}°E`; },
    onSelect: (site) => { if (site && site.id) selectSite(site.id); },
  };
  // 1. real map (Leaflet + OSM/CARTO tiles + GIBS overlay)
  try {
    const mod = await import("./sg-realmaps.js");
    // controls:false — the module renders its own in-map control cluster, and
    // rendering ours as well gave the user two identical selectors and two
    // basemap switches stacked on the same panel
    map = mod.createRealMap($("#realmap"), { ...opts, controls: true });
    mapImpl = "leaflet";
    $("#map-mode").textContent = "real basemap · NASA GIBS overlay";
    return;
  } catch (e) {
    console.warn("[solarguard] real map unavailable, using canvas map:", e.message);
  }
  // 2. canvas fallback (no CDN, no external tiles)
  $("#realmap").style.display = "none";
  $("#sg-map").style.display = "block";
  const { SaudiMap } = await import("./sg-map.js");
  document.body.classList.add("map-canvas");     // shows our own control row
  map = new SaudiMap($("#sg-map"), opts);
  mapImpl = "canvas";
  $("#map-mode").textContent = "offline canvas map · NASA GIBS overlay";
}

function placeSite(lat, lon) {
  if (lat < 15 || lat > 33.5 || lon < 33 || lon > 56.5) {
    toast("That point is outside Saudi Arabia — pick a spot inside the Kingdom.");
    return;
  }
  const near = state.sites.find((s) => Math.abs(s.lat - lat) < 0.06 && Math.abs(s.lon - lon) < 0.06);
  if (near) { selectSite(near.id); return; }
  state.custom = { lat: +lat.toFixed(4), lon: +lon.toFixed(4),
                   name: `Custom site ${lat.toFixed(2)}°N ${lon.toFixed(2)}°E` };
  state.siteId = null;
  map.setMarker(lat, lon, state.custom.name);
  $("#site-select").value = "__custom";
  toast(`Placed a site at ${lat.toFixed(3)}°N, ${lon.toFixed(3)}°E`);
  refresh();
}

function selectSite(id) {
  const s = state.sites.find((x) => x.id === id);
  if (!s) return;
  state.siteId = id;
  state.custom = null;
  if (s.capacity_mwp) state.capacity_kwp = s.capacity_mwp * 1000;
  $("#cap-range").value = state.capacity_kwp;
  $("#cap-val").textContent = fmtCapacity(state.capacity_kwp);
  $("#site-select").value = id;
  map.setMarker(s.lat, s.lon, s.name);
  map.focus(s.lat, s.lon, 7);
  refresh();
}

function applyLayer() {
  const id = $("#layer-select").value;
  if (!id) return;
  const date = $("#layer-date").value || state.dates[id];
  const meta = state.layers.find((l) => l.id === id);
  map.setLayer({ id, label: meta?.label, date });
}

/* --------------------------------------------------------------- boot */
async function boot() {
  const [sites, layers, model, rag, status, sources] = await Promise.all([
    jget("/sites").catch((e) => ({ error: e.message })),
    jget("/satellite/layers").catch(() => ({ error: "unavailable" })),
    jget("/model").catch(() => ({ ml: null })),
    jget("/rag/stats").catch(() => ({ chunks: 0, retriever: "—" })),
    jget("/sg/status").catch(() => ({})),
    jget("/sources").catch((e) => ({ error: e.message })),
  ]);
  if (sites.error) { toast("Sites API failed: " + sites.error); return; }

  state.sites = sites.sites;
  state.presets = sites.cleaning_presets || {};
  await initMap();
  map.setSites(state.sites);

  const sel = $("#site-select");
  sel.innerHTML = state.sites.map((s) => `<option value="${s.id}">${s.name} — ${s.region}</option>`).join("")
    + `<option value="__custom">Custom point (tap the map)</option>`;
  sel.value = state.siteId;
  sel.onchange = () => {
    if (sel.value === "__custom") { toast("Tap anywhere inside Saudi Arabia to place your own site."); return; }
    selectSite(sel.value);
  };

  const cp = $("#cost-preset");
  cp.innerHTML = `<option value="">Default — dry cleaning, ${nf(sites.cleaning_presets.dry_saudi.sar_per_mwp)} SAR/MWp</option>`
    + Object.entries(state.presets).map(([k, v]) =>
      `<option value="${v.sar_per_mwp}">${v.label} — ${nf(v.sar_per_mwp)} SAR/MWp</option>`).join("");
  cp.onchange = () => { state.cost_per_mwp_sar = cp.value ? +cp.value : null; refresh(); };

  $("#cap-range").oninput = (e) => {
    state.capacity_kwp = +e.target.value;
    $("#cap-val").textContent = fmtCapacity(state.capacity_kwp);
  };
  $("#cap-range").onchange = refresh;
  $("#ci-range").oninput = (e) => {
    state.cleaning_interval_days = +e.target.value;
    $("#ci-val").textContent = `${state.cleaning_interval_days} d`;
  };
  $("#ci-range").onchange = refresh;

  if (!layers.error) {
    state.layers = layers.layers;
    state.dates = layers.dates;
    const ls = $("#layer-select");
    ls.innerHTML = state.layers.map((l) => `<option value="${l.id}">${l.label}</option>`).join("");
    $("#layer-date").value = state.dates[ls.value] || "";
    ls.onchange = applyLayer;
    $("#layer-date").onchange = applyLayer;
    $("#layer-toggle").onclick = () => {
      const hidden = $("#layer-toggle").dataset.hidden === "1";
      map.setLayerVisible(hidden);
      $("#layer-toggle").dataset.hidden = hidden ? "0" : "1";
      $("#layer-toggle").textContent = hidden ? "Hide dust" : "Show dust";
    };
    applyLayer();
  }
  $("#reset-view").onclick = () => map.focus(24.2, 45.4, mapImpl === "leaflet" ? 6 : 5);
  $("#basemap").onchange = () => {
    if (map && map.setBasemap) map.setBasemap($("#basemap").value);
    else toast("Basemap switching needs the real map (Leaflet).");
  };

  renderModelCard(model, rag);
  renderFeedHealth(sources);
  $("#nav-status").innerHTML = sources.error
    ? `<span class="dot" style="background:#ff5f6d"></span> probe failed`
    : `<span class="dot"></span> ${sources.open_live}/${sources.open_total} feeds`;
  $("#copilot-meta").textContent = `${status.model || "deepseek"} · ${status.tool_count || 0} tools`;
  $("#cm-retriever").textContent = status.rag?.retriever || rag.retriever || "—";
  $("#cm-chunks").textContent = nf(status.rag?.chunks || rag.chunks || 0);
  $("#cm-model").textContent = status.model || "—";

  initChat();
  await refresh();
}

/* --------------------------------------------------------------- refresh */
let inflight = 0;
async function refresh() {
  const token = ++inflight;
  try {
    const rep = await jget("/report", {
      site: state.custom ? undefined : state.siteId,
      lat: state.custom?.lat, lon: state.custom?.lon, name: state.custom?.name,
      capacity_kwp: state.capacity_kwp,
      cleaning_interval_days: state.cleaning_interval_days,
      horizon_days: state.horizon_days,
      cost_per_mwp_sar: state.cost_per_mwp_sar ?? undefined,
    });
    if (token !== inflight) return;
    state.lastReport = rep;
    render(rep);
  } catch (e) {
    $("#param-error").textContent = "Could not compute this site: " + e.message;
  }
}

/* --------------------------------------------------------------- render */
function render(rep) {
  const { site, verdict: v, days } = rep;
  const fs = rep.report.fixed_schedule;
  const d0 = fs.rows[0] || days[0];

  $("#site-title").textContent = site.name;
  $("#site-sub").textContent =
    `${site.region} · ${site.lat.toFixed(3)}°N, ${site.lon.toFixed(3)}°E · climate "${rep.report.params.climate}"`
    + ` · ${fmtCapacity(rep.capacity_kwp)} · elevation ${nf(rep.elevation_m)} m`;
  $("#cap-interest").textContent = fmtCapacity(rep.capacity_kwp);
  $("#proj-note").textContent = `${days.length} days · ${rep.report.model}`;
  $("#verdict-stamp").textContent = `${rep.generated_utc.slice(11, 16)} UTC`;

  const box = $("#verdict-box");
  box.className = "verdict " + (v.decision === "clean_now" ? "now" : "wait");
  $("#verdict-word").textContent = v.decision === "clean_now" ? "CLEAN NOW" : "WAIT";
  $("#verdict-sub").textContent = v.decision === "clean_now"
    ? `crew pays for itself in ${nf(v.payback_days, 1)} days at this dust load`
    : "hold the crew, recheck tomorrow";
  $("#urgency-val").textContent = `${nf(v.urgency, 0)}/100 · risk today ${v.risk_today}`;
  $("#urgency-bar").style.width = `${clamp(v.urgency, 0, 100)}%`;
  $("#verdict-reason").innerHTML = `
    <p class="small">${v.reason}</p>
    <div class="kv"><span class="k">money at risk, 7 days</span><span class="v">${money(v.next_7d_money_at_risk_sar)}</span></div>
    <div class="kv"><span class="k">one cleaning pass</span><span class="v">${money(v.cleaning_cost_sar)}</span></div>
    <div class="kv"><span class="k">tuned trigger</span><span class="v">${pct(rep.report.policy.adaptive.threshold_pct)} loss</span></div>`;

  $("#k-loss").textContent = pct(d0.soiling_loss_pct);
  $("#k-mass").textContent = `${nf(d0.dust_mass_g_m2, 2)} g/m² on glass`;
  $("#k-lost").textContent = `${nf(d0.lost_kwh)} kWh`;
  $("#k-lost-sar").textContent = `${money(d0.lost_sar)} today`;
  $("#k-risk").textContent = money(v.next_7d_money_at_risk_sar);
  $("#k-cost").textContent = `crew ${money(v.cleaning_cost_sar)}`;
  $("#k-exposure").textContent = `${nf(d0.exposure_days, 1)} days`;
  $("#k-trigger").textContent = `trigger ${pct(rep.report.policy.adaptive.threshold_pct)}`;

  /* The observed strip. These are the measured inputs the prediction was built
     from, and each tile names the feed it came from — so nothing on this page is
     an anonymous number. */
  const obs = (id, txt) => { const el = $(id); if (el) el.textContent = txt; };
  obs("#obs-pm10", nf(d0.pm10_ugm3, 0));
  obs("#obs-dust", nf(d0.dust_ugm3, 0));
  obs("#obs-aod", nf(d0.aod, 2));
  obs("#obs-gust", nf(d0.gust_max_ms, 1));
  obs("#obs-rain", nf(d0.precip_mm, 1));
  obs("#obs-when", `${dateShort(d0.date)} · measured`);

  drawProjection($("#chart-projection"), fs.rows);
  drawEnergy($("#chart-energy"), fs.rows);
  $("#energy-note").textContent =
    `${nf(fs.energy_kwh / 1000)} MWh delivered · ${nf(fs.lost_kwh / 1000)} MWh lost (${pct(fs.mean_soiling_loss_pct)} mean)`;
  drawSeries($("#chart-series"), [
    { label: "PM10 µg/m³", data: days.map((d) => d.pm10_ugm3), color: "#f3a72b", decimals: 0 },
    { label: "dust µg/m³", data: days.map((d) => d.dust_ugm3), color: "#ff9f43", decimals: 0 },
    { label: "AOD", data: days.map((d) => d.aod), color: "#9a7bff", decimals: 2 },
    { label: "gust m/s", data: days.map((d) => d.gust_max_ms), color: "#37e0ff", decimals: 1 },
    { label: "rain mm", data: days.map((d) => d.precip_mm), color: "#3ddc97", decimals: 1 },
  ]);

  $("#plan-table tbody").innerHTML = fs.rows.map((r) => `
    <tr>
      <td>${dateShort(r.date)}</td>
      <td><span class="pill" style="border-color:${riskColor(r.dust_risk)}66;color:${riskColor(r.dust_risk)}">${r.dust_risk}</span></td>
      <td class="num">${nf(r.pm10_ugm3, 0)}</td>
      <td class="num">${nf(r.gust_max_ms, 1)}</td>
      <td class="num">${nf(r.irradiation_kwh_m2, 1)}</td>
      <td class="num">${pct(r.soiling_loss_pct)}</td>
      <td class="num">${nf(r.lost_kwh)}</td>
      <td class="num">${nf(r.lost_sar)}</td>
      <td>${r.cleaned ? '<span class="pill live">yes</span>' : ""}</td>
    </tr>`).join("");

  const a = rep.annual;
  const habits = [
    ["Weekly calendar", a.habits.weekly],
    [`Your ${state.cleaning_interval_days}-day calendar`, a.habits.industry_today],
    ["SolarGuard tuned", a.habits.adaptive],
    ["Never clean", a.habits.never],
  ];
  const best = Math.min(...habits.map(([, r]) => r.net_cost_sar));
  // the policy table lives in a narrow column; full digit groups push the money
  // column off-screen, so short form here (the exact figure is in the note below)
  const sarShort = (v) => (Math.abs(v) >= 1e6 ? `${nf(v / 1e6, 1)}M` : `${nf(v / 1e3, 0)}k`);
  $("#habits-table tbody").innerHTML = habits.map(([label, r]) => `
    <tr><td>${label}${r.net_cost_sar === best ? ' <span class="pill live">best</span>' : ""}</td>
    <td class="num">${r.cleaning_events_per_year}</td>
    <td class="num">${pct(r.mean_soiling_loss_pct)}</td>
    <td class="num"><b>${sarShort(r.net_cost_sar)}</b> <span class="u">SAR</span></td></tr>`).join("");
  const opp = a.opportunity || {};
  $("#habits-note").innerHTML =
    `Tuned by scoring ${rep.report.policy.candidates_evaluated} policies over a simulated year.`
    + ` Versus your habit: <b style="color:var(--green)">${money(opp.sar_saved_year)}/yr</b> cheaper, `
    + `${Math.abs(nf(opp.events_saved))} ${opp.events_saved >= 0 ? "fewer" : "more"} passes, `
    + `${nf(opp.energy_kept_pct, 1)} % of the lost energy kept.`;

  const litresShort = (v) => (v >= 1e6 ? `${nf(v / 1e6, 1)} M` : `${nf(v / 1e3, 0)} k`);
  const wPer = 2500 * rep.capacity_kwp / 1000;
  $("#w-pass").textContent = `${litresShort(wPer)} L`;
  $("#w-habit").textContent = `${litresShort(a.habits.industry_today.water_litres)} L  (${a.habits.industry_today.cleaning_events_per_year} passes)`;
  $("#w-tuned").textContent = `${litresShort(a.habits.adaptive.water_litres)} L  (${a.habits.adaptive.cleaning_events_per_year} passes)`;
  $("#w-saved").textContent = `${litresShort(Math.max(0, a.habits.industry_today.water_litres - a.habits.adaptive.water_litres))} L/yr`;
}

/* --------------------------------------------------------------- side panels */
function renderModelCard(model, rag) {
  const el = $("#model-card");
  const ml = model.ml;
  if (!ml) {
    el.innerHTML = `<p>Active: <b style="color:var(--ink-2)">physics-empirical</b>, anchored on published Saudi
      soiling rates per climate class, plus the tuned cleaning policy.</p>`;
    return;
  }
  const get = (s, m, t) => ml?.[s]?.[m]?.[t] || null;
  const fmt = (x) => x ? `MAE ${nf(x.mae, 2)} · R² ${nf(x.r2, 3)}` : "—";
  const cfg = ml.model_config || {};
  el.innerHTML = `
    <div class="kv"><span class="k">active</span><span class="v">${model.active}</span></div>
    <div class="kv"><span class="k">GBRT · time split</span><span class="v">${fmt(get("time_split", "gbrt", "soiling_loss_pct"))}</span></div>
    <div class="kv"><span class="k">MLP · time split</span><span class="v">${fmt(get("time_split", "mlp", "soiling_loss_pct"))}</span></div>
    <div class="kv"><span class="k">GBRT · unseen site</span><span class="v">${fmt(get("leave_one_site_out", "gbrt", "soiling_loss_pct"))}</span></div>
    ${cfg.gbrt ? `<div class="kv"><span class="k">GBRT config</span><span class="v">${cfg.gbrt.n_trees} trees · d${cfg.gbrt.max_depth} · lr ${cfg.gbrt.learning_rate}</span></div>` : ""}
    <p class="small dim" style="margin-top:10px">Hand-written numpy, CPU only. Labels come from a
      literature-calibrated physics model, not inverter data: decision support, not a meter reading.</p>`;
}

function renderFeedHealth(sources) {
  const el = $("#feed-health");
  if (sources.error) { el.textContent = "probe failed: " + sources.error; return; }
  el.innerHTML = `<div class="kv"><span class="k">open feeds answering</span><span class="v">${sources.open_live}/${sources.open_total}</span></div>`
    + `<div class="kv"><span class="k">key-gated, mapped</span><span class="v">${sources.gated}</span></div>`
    + `<div style="margin-top:8px;display:flex;flex-wrap:wrap;gap:6px">`
    + sources.sources.map((s) => `<span class="pill ${s.status === "live" ? "live" : "gated"}">${s.name.replace(/ —.*$/, "").slice(0, 30)}</span>`).join("")
    + `</div><p class="small dim" style="margin-top:8px">checked ${sources.checked_utc}</p>`;
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
    "Compare Jeddah and Dammam",
    "Show the MERRA-2 dust layer for last month",
    "Move the map to Sudair",
  ];
  const sug = $("#chat-suggestions");
  suggestions.forEach((q) => {
    const b = document.createElement("button");
    b.textContent = q;
    b.onclick = () => send(q);
    sug.appendChild(b);
  });

  add("bot", `<p>I'm the SolarGuard agent. I read the same live feeds this dashboard does, and I can act on it.
    Ask me anything, or tap a suggestion.</p>`);

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
        lat: state.custom?.lat, lon: state.custom?.lon,
        capacity_kwp: state.capacity_kwp,
      });
      if (!out.ok) { t.innerHTML = `<p>${out.message || "agent unavailable"}</p>`; return; }
      state.history.push({ role: "user", content: q }, { role: "assistant", content: out.answer });
      const body = (out.answer || "")
        .replace(/&/g, "&amp;").replace(/</g, "&lt;")
        .replace(/\*\*(.+?)\*\*/g, "<b>$1</b>")
        .replace(/^#{1,4}\s*(.+)$/gm, "<b>$1</b>")
        .split(/\n{2,}/).map((p) => `<p>${p.replace(/\n/g, "<br>")}</p>`).join("");
      const cites = (out.citations || []).slice(0, 5).map((c) =>
        `<a href="${c.url || "#"}" target="_blank" rel="noopener">[${c.n}] ${c.source}${c.page ? " p." + c.page : ""}</a>`).join("");
      t.innerHTML = body + (cites ? `<div class="cites">${cites}</div>` : "")
        + `<div class="small dim" style="margin-top:8px">tools: ${(out.tool_trace || []).map((x) => x.tool).join(", ") || "none"} · ${out.elapsed_ms} ms</div>`;

      for (const a of out.actions || []) {
        if (a.type === "place_site") {
          const known = state.sites.find((x) => x.id === a.site.id);
          if (known) selectSite(known.id);
          else {
            state.siteId = null;
            state.custom = { lat: a.site.lat, lon: a.site.lon, name: a.site.name };
            map.setMarker(a.site.lat, a.site.lon, a.site.name);
            map.focus(a.site.lat, a.site.lon, 7);
            refresh();
          }
          toast(a.label || "Map moved");
        } else if (a.type === "show_layer") {
          const ls = $("#layer-select");
          if ([...ls.options].some((o) => o.value === a.layer)) {
            ls.value = a.layer;
            $("#layer-date").value = a.date;
            applyLayer();
            toast(a.label || "Satellite layer switched");
          }
        }
      }
    } catch (e) {
      t.innerHTML = `<p>Agent error: ${e.message}</p>`;
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
