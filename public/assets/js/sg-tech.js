/* ============================================================================
   sg-tech.js — the technology page: the engineering detail, kept off the
   homepage. Same live data, tables instead of marketing.
   ========================================================================= */
import { jget, nf, money, pct } from "./sg-core.js";

const $ = (s) => document.querySelector(s);

async function sources() {
  try {
    const src = await jget("/sources");
    $("#sources-table tbody").innerHTML = src.sources.map((s) => `
      <tr>
        <td>${s.name}${s.effective_date ? `<div class="dim small">effective ${s.effective_date}</div>` : ""}</td>
        <td><span class="pill ${s.status === "live" ? "live" : "gated"}">${s.access === "open" ? "open" : s.access}</span></td>
        <td class="dim">${s.provides}</td>
        <td class="dim">${s.used_for}</td>
        <td class="num"><span class="pill ${s.status === "live" ? "live" : s.status === "gated" ? "gated" : "warn"}">${s.status}</span></td>
      </tr>`).join("");
  } catch (e) {
    console.warn("source probe failed:", e.message);
  }
}

async function models() {
  try {
    const s = await jget("/ai/models");
    const st1 = s.metrics?.storm_t1, st3 = s.metrics?.storm_t3;
    const y = s.metrics?.yield_t1, so = s.metrics?.soiling_t1;
    const loso = s.loso_mean;
    const pctOr = (v) => (v === null || v === undefined ? "—" : `${nf(v, 1)} %`);
    const rows = [
      ["Sandstorm, next day (" + (s.storm_definition ? "PM10 ≥ 3× site median" : "") + ")",
       st1 ? `caught ${pctOr(st1.recall_pct)} of storms, ${pctOr(st1.precision_pct)} of alerts were real`
           : null,
       st1 ? `AUC ${nf(st1.auc, 3)} · Brier ${nf(st1.brier, 3)}` : null],
      ["Sandstorm, 3 days ahead", st3 ? `caught ${pctOr(st3.recall_pct)}, ${pctOr(st3.precision_pct)} precision` : null,
       st3 ? `AUC ${nf(st3.auc, 3)} · Brier ${nf(st3.brier, 3)}` : null],
      ["Panel output, tomorrow (kWh/kWp)", y ? `±${nf(y.mae, 3)} kWh/kWp (${nf(y.mae_pct_of_mean, 1)} % of the mean)` : null,
       y ? `R² ${nf(y.r2, 3)}` : null],
      ["Soiling loss, tomorrow (% points)", so ? `±${nf(so.mae, 2)} points` : null,
       so ? `R² ${nf(so.r2, 3)}` : null],
      ["Output, a site the models never saw", loso ? `±${nf(loso.yield_mae, 3)} kWh/kWp` : null,
       loso ? `R² ${nf(loso.yield_r2, 3)}` : null],
    ].filter((r) => r[1]);
    $("#model-table tbody").innerHTML = rows.map(([t, e, k]) => `
      <tr><td>${t}</td><td class="num">${e}</td><td class="num dim">${k || ""}</td></tr>`).join("");
    const b = s.baselines || {};
    $("#model-line").textContent = s.available
      ? `Trained ${String(s.trained_utc || "").slice(0, 10)} on ${nf(s.samples)} site-days across ${s.sites} sites `
        + `(${s.date_range?.[0]} to ${s.date_range?.[1]}); ${s.n_features || 37} features from the live 92-day window `
        + `+ forecast. Gradient-boosted trees + a small neural net, blended by measured skill.`
      : "models are still training";
  } catch (e) {
    $("#model-table tbody").innerHTML =
      `<tr><td colspan="3" class="dim">AI report card unavailable: ${e.message}</td></tr>`;
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
