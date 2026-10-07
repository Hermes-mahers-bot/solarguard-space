/* ============================================================================
   sg-home.js — homepage controller.

   Two scroll animations (a perspective ground view, then an orbital plot),
   text that reveals as you scroll, live numbers in the impact tiles, and the
   live agent demo. Everything is read from the API; nothing is hard-coded.
   ========================================================================= */
import { jget, jpost, nf, clamp, toast, scrollProgress, elementProgress } from "./sg-core.js";

const $ = (s) => document.querySelector(s);
const $$ = (s) => Array.from(document.querySelectorAll(s));

/* ------------------------------------------------------------------ text reveals */
function initReveals() {
  const io = new IntersectionObserver((entries) => {
    entries.forEach((e, i) => {
      if (!e.isIntersecting) return;
      const el = e.target;
      const delay = Number(el.dataset.delay || i * 90);
      setTimeout(() => el.classList.add("in"), Math.min(delay, 600));
      io.unobserve(el);
    });
  }, { rootMargin: "0px 0px -12% 0px", threshold: 0.12 });
  $$(".reveal").forEach((el, i) => { el.style.transitionDelay = `${Math.min(i % 4 * 80, 240)}ms`; io.observe(el); });
}

/* ------------------------------------------------------------------ animation 1: ground view */
async function initGroundStory() {
  const canvas = $("#story"), stage = $("#stage");
  if (!canvas) return null;
  try {
    const { createScrollStory } = await import("./sg-scrollstory.js");
    const story = createScrollStory(canvas, {
      blobScale: 0.7, blobAlpha: 0.8,
      hudTop: innerWidth < 720 ? 74 : 84,      // keep the readout clear of the nav
    });
    story.start();
    const onScroll = () => story.setProgress(scrollProgress(stage));
    addEventListener("scroll", onScroll, { passive: true });
    addEventListener("resize", () => story.resize());
    onScroll();
    return story;
  } catch (e) {
    console.warn("[solarguard] ground story unavailable:", e.message);
    return null;
  }
}

/* ------------------------------------------------------------------ animation 2: orbital plot */
async function initPlumeStory(sites) {
  const canvas = $("#plume"), section = $("#orbit");
  if (!canvas) return;
  const cap = $("#orbit-caption"), sub = $("#orbit-sub");
  const subs = [
    "Scroll to follow one front across the Kingdom.",
    "It crosses 1,000 km of desert in a day.",
    "Every site it touches gets a number.",
    "Then the dust clears — and the cycle starts again.",
  ];
  try {
    const { createPlumeStory } = await import("./sg-plume-story.js");
    const story = createPlumeStory(canvas, {
      sites,
      // phones lay the plot out in normal flow, so the readout goes at the bottom
      // of the canvas where nothing can scroll over it
      hudTop: innerWidth < 720 ? -64 : 84,
      onPhase: (i, text) => {
        // the caption swaps as the scroll reaches each phase — text appears with
        // the animation rather than all at once
        if (cap.textContent === text) return;
        cap.classList.remove("in");
        setTimeout(() => {
          cap.textContent = text;
          sub.textContent = subs[i] || "";
          cap.classList.add("in");
        }, 180);
      },
    });
    cap.classList.add("in");
    story.start();
    // desktop pins the plot and the section scroll drives it; a phone lays the
    // plot out in normal flow, so the canvas's own travel through the viewport is
    // the clock — otherwise the animation finishes off-screen
    const sticky = () => getComputedStyle(section.querySelector(".orbit-sticky")).position === "sticky";
    const onScroll = () => story.setProgress(sticky() ? scrollProgress(section) : elementProgress(canvas));
    addEventListener("scroll", onScroll, { passive: true });
    addEventListener("resize", onScroll);
    onScroll();
    return story;
  } catch (e) {
    console.warn("[solarguard] plume story unavailable:", e.message);
  }
}

/* ------------------------------------------------------------------ live numbers */
const big = (v, unit) => {
  if (v === null || v === undefined) return "—";
  const a = Math.abs(v);
  const s = a >= 1e9 ? [v / 1e9, "B"] : a >= 1e6 ? [v / 1e6, "M"] : a >= 1e3 ? [v / 1e3, "k"] : [v, ""];
  return `${nf(s[0], s[0] < 10 ? 1 : 0)}${s[1]}${unit ? " " + unit : ""}`;
};

async function initNumbers() {
  try {
    const rep = await jget("/report", { site: "dammam", capacity_kwp: 100000, horizon_days: 10 });
    const h = rep.annual.habits, opp = rep.annual.opportunity || {};
    const passesAvoided = Math.max(0, h.industry_today.cleaning_events_per_year
                                      - h.adaptive.cleaning_events_per_year);
    $("#stat-sar").textContent = big(opp.sar_saved_year, "SAR");
    $("#stat-mwh").textContent = nf(passesAvoided);
    $("#stat-water").textContent = big(opp.water_saved_litres, "L");
  } catch (e) {
    console.warn("report unavailable", e);
  }
  try {
    const src = await jget("/sources");
    $("#stat-feeds").textContent = `${src.open_live}/${src.open_total}`;
    $("#foot-status").textContent =
      `${src.open_live} of ${src.open_total} open feeds answering · ${src.gated} key-gated datasets wired and waiting on credentials · checked ${src.checked_utc}`;
  } catch (e) {
    $("#foot-status").textContent = "status unavailable";
  }
}

/* ------------------------------------------------------------------ agent demo */
async function initAgent() {
  const chat = $("#home-chat"), input = $("#home-ask");
  if (!chat) return;
  const questions = [
    "Should we clean Dammam this week?",
    "Compare Jeddah and Dammam",
    "How much water do we save?",
  ];
  const sug = document.createElement("div");
  sug.className = "suggestions";
  questions.forEach((q) => {
    const b = document.createElement("button");
    b.textContent = q;
    b.onclick = () => ask(q);
    sug.appendChild(b);
  });
  chat.after(sug);

  const render = (el, out) => {
    const body = (out.answer || "")
      .replace(/&/g, "&amp;").replace(/</g, "&lt;")
      .replace(/\*\*(.+?)\*\*/g, "<b>$1</b>")
      .replace(/^#{1,4}\s*(.+)$/gm, "<b>$1</b>")
      .split(/\n{2,}/).map((p) => `<p>${p.replace(/\n/g, "<br>")}</p>`).join("");
    const cites = (out.citations || []).slice(0, 4).map((c) =>
      `<a href="${c.url || "#"}" target="_blank" rel="noopener">[${c.n}] ${c.source}${c.page ? " p." + c.page : ""}</a>`).join("");
    el.innerHTML = body + (cites ? `<div class="cites">${cites}</div>` : "");
  };

  const ask = async (q) => {
    q = (q || input.value || "").trim();
    if (!q) return;
    input.value = "";
    chat.innerHTML = "";
    const u = document.createElement("div"); u.className = "msg user"; u.textContent = q; chat.appendChild(u);
    const b = document.createElement("div"); b.className = "msg bot";
    b.innerHTML = `<span class="typing"><span></span><span></span><span></span></span>
      <span class="small dim">reading the live feeds…</span>`;
    chat.appendChild(b);
    try {
      const out = await jpost("/assistant", { question: q, history: [], site: "dammam", capacity_kwp: 100000 });
      if (!out.ok) { b.textContent = out.message || "The assistant is unavailable right now."; return; }
      render(b, out);
    } catch (e) { b.textContent = "Assistant error: " + e.message; }
  };

  $("#home-ask-go").onclick = () => ask();
  input.onkeydown = (e) => { if (e.key === "Enter") ask(); };
  await ask(questions[0]);
}

/* ------------------------------------------------------------------ boot */
(async () => {
  initReveals();
  const ground = await initGroundStory();
  let sites = [];
  try {
    const s = await jget("/sites");
    sites = s.sites || [];
  } catch (_) { /* the plot works with the default site list */ }
  await initPlumeStory(sites);
  initNumbers();
  initAgent();

  // feed the ground scene the real first-day numbers once we have them
  if (ground) {
    try {
      const rep = await jget("/report", { site: "dammam", capacity_kwp: 100000, horizon_days: 7 });
      const row = rep.report.fixed_schedule.rows[0];
      ground.setData?.({
        soilingLossPct: row.soiling_loss_pct,
        outputPct: 100 - row.soiling_loss_pct,
        dustUgm3: rep.days[0].dust_ugm3,
        siteName: `${rep.site.name} · ${nf(rep.capacity_kwp / 1000)} MWp`,
      });
    } catch (_) { /* HUD falls back to scroll interpolation */ }
  }
})();
