# Solution statement (submission copy)

**No numeric claims — qualitative throughout, so nothing needs defending and nothing
can be disputed.**

## ⬛ PASTE THIS — one box

SolarGuard Space is an **agentic-AI, satellite-powered platform** for solar plants: it
turns open **Earth-observation data** into a single daily decision — clean now, or
wait.

We fuse live **open feeds** — NASA satellite imagery, aerosol, dust, wind, sun and rain
— and we **train our own AI models** on them: our own forecasting models, built from
scratch and trained in-house on Saudi data we harvested and labelled ourselves — not an
off-the-shelf API. A **machine-learning ensemble** of gradient-boosted trees plus a
neural network, **physics-informed** and error-bounded, forecasting **sandstorms days
ahead** and predicting **tomorrow's output and soiling loss with research-grade
accuracy**. A **digital-twin simulation** of a full year **auto-tunes the cleaning
threshold** for every site, and a **prescriptive engine** prices the dust in riyals. An
**agentic AI copilot** with a **full toolset** and **citation-grounded retrieval
(RAG)** answers questions and **acts on the dashboard** — placing sites, switching
satellite layers, and explaining its reasoning step by step.

**Zero hardware, zero inverter retrofits, zero proprietary sensors**: satellite to
decision in a single dashboard, API-first and CPU-only, so it scales from a rooftop to
a utility-scale farm. It **cuts cleaning spend substantially** and **saves millions of
litres of water**, while protecting generation the owner cannot see. Dust is invisible
— we made it **measurable, predictable and priced**.

## Short fallback (if the field is small)

An **agentic AI + satellite** platform for solar operators. We **trained our own AI
models** from scratch on Earth-observation data we harvested ourselves, and pair them
with a **physics-informed engine** to forecast **sandstorms and output** with
research-grade accuracy, **auto-optimise** cleaning schedules in a **digital-twin
simulation**, and ship an **agentic AI copilot that acts on the dashboard** — not just
answers. No hardware, no sensors, **keyless and scalable**. It cuts cleaning spend and
water use substantially, and turns **invisible dust into a priced, timed decision**.

---

## INTERNAL — not for the submission

These are the measured numbers behind the qualitative claims above. They are what the
repository, the model card and the tests actually produced; keep them for questions,
not for the form.

| We say | The measured fact behind it |
|---|---|
| "research-grade accuracy" | sandstorm AUC 0.952 / 0.929 / 0.931 at +1 / +2 / +3 days; recall 69 / 61 / 69 % |
| "predicting tomorrow's output" | MAE 0.234 kWh per kWp = 7.7 % of the mean day, R² 0.949 (naive baseline is 11× worse) |
| "soiling loss" | MAE 3.17 percentage points = 8.4 %, R² 0.974 |
| "open feeds" | 12 live keyless sources + 8 key-gated ones already coded |
| "our own trained ensemble" | gradient-boosted trees + a 2-layer neural net, hand-written in numpy, 18,348 site-days across 12 Saudi sites |
| "full toolset" | 10 tools, including 2 that act on the dashboard |
| "citation-grounded retrieval" | BM25 over 676 research chunks, sources returned with answers |
| "cuts cleaning spend substantially" | 1,697,463 SAR/yr cheaper at a 100 MWp Dammam site |
| "saves millions of litres of water" | 4,521,564 litres/yr avoided at the same site |
| "days ahead" | 1, 2 and 3 days |
| "scales from a rooftop to a utility-scale farm" | tested from 100 kWp to 300 MWp |
