/* ============================================================================
   sg-tech.js — the technology page: the engineering detail, kept off the
   homepage. Same live data, tables instead of marketing.
   ========================================================================= */
import { jget, nf, money, pct } from "./sg-core.js";

const $ = (s) => document.querySelector(s);

async function sources() {
  try {
    const src = await jget("/sources");
    $("#feed-status").textContent =
      `${src.open_live} of ${src.open_total} open feeds answered HTTP 200 · ${src.gated} key-gated datasets wired · checked ${src.checked_utc}`;
    $("#sources-table tbody").innerHTML = src.sources.map((s) => `
      <tr>
        <td>${s.name}${s.effective_date ? `<div class="dim small">effective ${s.effective_date}</div>` : ""}</td>
        <td><span class="pill ${s.status === "live" ? "live" : "gated"}">${s.access === "open" ? "open" : s.access}</span></td>
        <td class="dim">${s.provides}</td>
        <td class="dim">${s.used_for}</td>
        <td class="num"><span class="pill ${s.status === "live" ? "live" : s.status === "gated" ? "gated" : "warn"}">${s.status}</span></td>
      </tr>`).join("");
  } catch (e) {
    $("#feed-status").textContent = "source probe failed: " + e.message;
  }
}

async function models() {
  try {
    const m = await jget("/model");
    const ml = m.ml || {};
    const get = (s, mo, t) => ml?.[s]?.[mo]?.[t] || null;
    const rows = [
      ["Gradient-boosted trees", "soiling loss, next day", get("time_split", "gbrt", "soiling_loss_pct")],
      ["Gradient-boosted trees", "dust deposition", get("time_split", "gbrt", "deposition_g_m2_day")],
      ["Neural net (64-32)", "soiling loss, next day", get("time_split", "mlp", "soiling_loss_pct")],
      ["GBRT · leave-one-site-out", "soiling loss, unseen site", get("leave_one_site_out", "gbrt", "soiling_loss_pct")],
      ["MLP · leave-one-site-out", "soiling loss, unseen site", get("leave_one_site_out", "mlp", "soiling_loss_pct")],
    ].filter(([, , v]) => v);
    $("#model-table tbody").innerHTML = rows.map(([mo, t, v]) => `
      <tr><td>${mo}</td><td class="dim">${t}</td>
      <td class="num">${nf(v.mae, 2)} pct-pts</td><td class="num">${nf(v.r2, 3)}</td></tr>`).join("");
    const cfg = ml.model_config || {};
    $("#model-line").textContent = cfg.gbrt
      ? `Active: ${m.active} · GBRT ${cfg.gbrt.n_trees} trees, depth ${cfg.gbrt.max_depth}, lr ${cfg.gbrt.learning_rate} · MLP ${cfg.mlp.hidden.join("-")}, ${cfg.mlp.optimiser}, ${cfg.mlp.epochs} epochs · hand-written numpy, CPU only`
      : "Active: physics-empirical model";
  } catch (e) {
    $("#model-table tbody").innerHTML = `<tr><td colspan="4" class="dim">model card unavailable: ${e.message}</td></tr>`;
  }
}

async function agent() {
  try {
    const st = await jget("/sg/status");
    $("#agent-tools").textContent = `${st.tool_count} — ${(st.tools || []).join(", ")}`;
    $("#agent-model").textContent = st.model + (st.ai_enabled ? "" : " (not configured)");
    $("#agent-rag").textContent = st.rag.retriever;
    $("#agent-corpus").textContent = `${nf(st.rag.chunks)} chunks`;
  } catch (e) {
    $("#agent-tools").textContent = "unavailable: " + e.message;
  }
}

async function calibrationAndPolicy() {
  // one report per climate class — the model parameters and the annual reference
  // differ by climate, and that is the whole point of the calibration table
  try {
    const sites = await jget("/sites");
    const byClimate = {};
    for (const s of sites.sites) if (!byClimate[s.climate]) byClimate[s.climate] = s;
    const reports = await Promise.all(Object.values(byClimate).map((s) =>
      jget("/report", { site: s.id, capacity_kwp: 1000, horizon_days: 3 }).catch(() => null)));

    $("#calib-table tbody").innerHTML = reports.filter(Boolean).map((r) => {
      const p = r.report.params;
      return `<tr>
        <td>${p.climate}</td>
        <td class="num">${nf(p.rate_pct_per_day, 2)}</td>
        <td class="num">${pct(p.lmax * 100, 0)}</td>
        <td class="num">${pct(p.literature.annual_loss_pct, 0)}<div class="dim small">${r.annual.literature_source}</div></td>
      </tr>`;
    }).join("");

    const rep = await jget("/report", { site: "dammam", capacity_kwp: 100000, horizon_days: 10 });
    const a = rep.annual, h = a.habits;
    const rows = [
      ["Weekly calendar", h.weekly],
      [`Industry habit — every ${h.industry_today.cleaning_interval_days} days`, h.industry_today],
      ["SolarGuard tuned policy", h.adaptive],
      ["Never clean", h.never],
    ];
    const best = Math.min(...rows.map(([, v]) => v.net_cost_sar));
    $("#policy-table tbody").innerHTML = rows.map(([label, v]) => `
      <tr><td>${label}${v.net_cost_sar === best ? ' <span class="pill live">best</span>' : ""}</td>
      <td class="num">${v.cleaning_events_per_year}</td>
      <td class="num">${pct(v.mean_soiling_loss_pct)}</td>
      <td class="num">${nf(v.energy_lost_kwh / 1000)} MWh</td>
      <td class="num">${money(v.cleaning_cost_sar)}</td>
      <td class="num"><b>${money(v.net_cost_sar)}</b></td></tr>`).join("");
    const p = rep.report.policy;
    $("#policy-note").textContent =
      `${rep.site.name}, ${nf(rep.capacity_kwp / 1000)} MWp · tuned trigger ${pct(p.adaptive.threshold_pct)} loss · `
      + `${p.candidates_evaluated} policies scored · one pass costs ${nf(rep.report.cost_per_mwp_sar)} SAR/MWp · `
      + `lost generation valued at ${a.assumptions.tariff_sar_per_kwh} SAR/kWh. ` + p.method + ".";
  } catch (e) {
    $("#policy-table tbody").innerHTML = `<tr><td colspan="6" class="dim">unavailable: ${e.message}</td></tr>`;
  }
}

sources();
models();
agent();
calibrationAndPolicy();
