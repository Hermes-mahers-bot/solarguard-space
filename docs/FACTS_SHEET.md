# ⚡ SolarGuard Space — FACTS SHEET

**One-page digest of verified numbers with citations. Safe to paste as LLM context; safe to lift as website copy.**
Built 2026-10-07. Every figure below was read from the cited source (page given). Region focus: Saudi Arabia / Arabian Peninsula.

---

## 1. How bad is dust soiling? (the money numbers)

| Number | Meaning | Source |
|---|---|---|
| **~12 % per week** | Soiling accumulation over the Arabian Peninsula | Stenchikov et al., MENA-SC 2023 — [KAUST](https://repository.kaust.edu.sa/handle/10754/696394) |
| **30–35 %** | Soiling reached on the **Saudi east coast** (worst case) | ibid. |
| **12–24 % per month** | Uncleaned monthly power loss, Arabian desert (Qatar); ~**15 % avg monthly** yield reduction | Alharbi, *Energies* 2026 — [PDF](https://res.mdpi.com/d_attachment/energies/energies-19-04373/article_deploy/energies-19-04373.pdf) p.6 |
| **0.083–0.36 %/day** | Measured daily soiling rate (Morocco) ≈ **2.5–10.8 % over 30 dry days** | ibid. p.10 |
| **2–50 %** | Range of PV performance lost to soiling, globally, by environment | Al Garni, *Energies* 2022 — [PDF](https://res.mdpi.com/d_attachment/energies/energies-15-08033/article_deploy/energies-15-08033.pdf) p.1 |
| **>50 % power drop** | Result of leaving a module **uncleaned for 6 months** in desert conditions | ibid. p.12 |
| **0.051 %/day** | Global multi-site average soiling loss; **26 %** of sites exceed 0.1 %/day | ibid. p.8 |
| **0.45 %/day** | Benchmark soiling rate at a desert test site (IEA-PVPS) | [IEA-PVPS T13-21:2022](https://iea-pvps.org/wp-content/uploads/2023/01/IEA-PVPS-T13-21-2022-REPORT-Soiling-Losses-PV-Plants.pdf) p.69 |

> **Pitch caveat (use carefully):** the "KAUST ~15 % west / ~45 % east" figure from our pitch is **not** stated in the KAUST texts we could read. The readable KAUST/MENA-SC source says **~12 %/week average, 30–35 % east coast**. Safest phrasing: *"KAUST and regional studies put Arabian-Peninsula soiling at ~12 % per week, rising to 30–45 % on the Gulf/east coast where dust is heaviest."*

## 2. Saudi seasonality — when dust hits

- **Spring and summer** are the main dust-storm seasons in Saudi Arabia; Al Ahsa (east) peaks in **summer (90 events)** and **winter (60 events)**. — Al Garni 2022 p.7
- Dust-accumulation loss peaks at **~16 % in April** (dustiest) vs **~2 % in July** (least dusty). — ibid. p.10
- A single **March sandstorm cut module output by 20 %**; **November rainfall pushed output to the year's high**. — ibid. p.11
- **Dust storms cut incoming radiation by 8 %** and raised annual-average soiling rates by **23 %** vs non-storm days. — Alharbi 2026 p.2
- Arar field exposure: **Isc −2.78 %/day**, **Voc −0.863 %/day**. — Al Garni 2022 p.13

## 3. Why arid dust is worse (mechanisms)

- **Two separate losses:** fine dust (radius **<3 µm**) *dims* sunlight in the air; **coarse dust (>3 µm)** is what actually *deposits* on the glass. Average atmospheric dimming **3–4 %/day**, locally **10–12 %**. — [KAUST MENA-SC 2023](https://repository.kaust.edu.sa/handle/10754/696394)
- **Dew & cementation:** even without cementation, **surface condensation causes capillary adhesion**; repeated dew cycles **cement dust into a hard crust** that dry cleaning cannot remove. — Al Garni 2022 p.6, p.15
- **Humidity alone** cut Voc by **~12 %**; above **60 % RH**, efficiency losses hit **15–30 %** from enhanced adhesion + moisture conduction. — [Almarri et al., JMRT 2025](https://www.sciencedirect.com/science/article/pii/S2238785425027103) p.1–2
- **Dust is ionic and electrostatically sticky:** airborne particles charge each other and *more* dust accumulates on the panel. — Al Garni 2022 p.5
- Jubail dust chemistry: natural dust is **25.4 % silica / 30.5 % calcium oxide**; iron-rich **montmorillonite (62.7 % Fe)** causes the worst heat build-up (**40.4 °C**). Natural dust caused the largest power loss: **48 % at 6 g/m²**. — Almarri 2025 p.1
- **Critical cleaning threshold: 4.0 g/m²** dust density (efficiency then falls exponentially). — Almarri 2025 p.1
- **Slope matters:** 90°-tilted modules accumulate negligible dust → a plus for **bifacial** PV. — [KAUST Abdallah et al. 2020](https://repository.kaust.edu.sa/handle/10754/665153)

## 4. So what should operators do?

| Recommendation | Evidence |
|---|---|
| **Clean weekly → ~6 % better** than uncleaned; microfiber wiper (or microfiber + vacuum) is the most effective manual method | Alharbi 2026 p.3 |
| **Optimal cleaning interval 60–90 days** for the Arar desert climate (cost-balanced) | Alharbi 2026 p.1 |
| **Waterless / dry and robotic** methods matter because **water scarcity** is a hard limit in arid high-irradiance regions | Al Garni 2022 p.16 |
| **Robotic cleaning costs ~50 % less than manual** (LCOE), improving project LCOE >1 % | Al Garni 2022 p.21 |
| **Drones** (brush / microfiber brushes best) give inspection + dry cleaning with long-range monitoring | Al Garni 2022 p.17 |
| **Electrodynamic screen** (waterless) cut soiling power loss by **36 %** vs uncleaned | IEA-PVPS T13-21:2022 p.77 |
| **Self-cleaning coatings** (super-hydrophobic/hydrophilic) still need water — they reduce, not remove, cleaning | Al Garni 2022 p.21 |
| **Clean when avoided revenue > cleaning cost** (the monitoring ROI rule) | [Kipp & Zonen DustIQ](https://www.kippzonen.com/products/dustiq-soiling-monitoring-system) |

## 5. DustIQ sensor — the hardware reference point

Product 386915. Uses an **internal light source** (no pyranometer) and reads scattered/reflected light proportional to soiling.

- **Range:** Soiling Ratio **100 → 50 %**; Transmission Loss **0 → 50 %**
- **Accuracy:** ±0.1 of reading ±1 %, *after local dust calibration*
- **Temp:** sensor **−20 → +80 °C**; enclosure **−20 → +60 °C**
- **Power:** 12–30 VDC, 70–200 mA · **Comms:** 2-wire **RS-485 Modbus RTU**
- **Size:** 990 × 160 × 35 mm · optional **back-of-module temp sensor** ( −20 → +100 °C, ±1 °C)
— [Kipp & Zonen DustIQ](https://www.kippzonen.com/products/dustiq-soiling-monitoring-system)

## 6. Saudi solar context (for the pitch / dashboard)

- **Vision 2030:** diversify the grid to roughly **50 % renewables + 50 % natural gas by 2030**. — Al Garni 2022 p.2
- **Sakaka 300 MW** IPP (Al Jouf) — the Kingdom's first utility-scale solar plant; record **LCOE 2.3417 US¢/kWh** (Feb 2018), single-axis E-W tracking. — Al Garni 2022 p.21
- **Sudair 1.5 GW** — one of the biggest PV plants in the world, largest in Saudi Arabia. — Al Garni 2022 p.2
- **NEOM** — renewables-powered Vision 2030 flagship city on the Red Sea coast (NW Saudi Arabia). — [vision2030.gov.sa](https://www.vision2030.gov.sa/en/explore/projects/neom)
- **Tariff:** SEC residential ≈ **SAR 0.18/kWh** up to 6,000 kWh/month, then **SAR 0.30/kWh** (commercial/industrial differ). — [ksacalc.com/sec](https://ksacalc.com/sec/)
- **Resource:** Saudi Arabia has **~3× the solar potential of Europe**; solar is the cornerstone of its renewables strategy. — [The Energy Year](https://theenergyyear.com/articles/positioning-saudi-arabia-at-the-forefront-of-low-carbon-expertise/)
- **Dustiest months = highest AC-driven demand** (spring/summer) → soiling bites exactly when power is worth most. — Al Garni 2022 p.6–7

## 7. Quick source index

| Tag | Source | Link |
|---|---|---|
| KAUST/MENA-SC 2023 | Coarse dust soiling & fine dust dimming, Arabian Peninsula | https://repository.kaust.edu.sa/handle/10754/696394 |
| KAUST/Abdallah 2020 | Soiling loss rate, hot & humid desert (15 months, W. Saudi) | https://repository.kaust.edu.sa/handle/10754/665153 |
| Al Garni 2022 | *Impact of Soiling on PV Module Performance in Saudi Arabia*, Energies 15, 8033 | https://res.mdpi.com/d_attachment/energies/energies-15-08033/article_deploy/energies-15-08033.pdf |
| Alharbi 2026 | *Seasonal Soiling Rates & Cleaning Optimization, Arar*, Energies 19(18), 4373 | https://res.mdpi.com/d_attachment/energies/energies-19-04373/article_deploy/energies-19-04373.pdf |
| Almarri 2025 | *Dust composition impact on PV in arid coastal environments*, JMRT | https://www.sciencedirect.com/science/article/pii/S2238785425027103 |
| IEA-PVPS T13-21:2022 | *Soiling Losses — Impact on the Performance of PV Power Plants* | https://iea-pvps.org/wp-content/uploads/2023/01/IEA-PVPS-T13-21-2022-REPORT-Soiling-Losses-PV-Plants.pdf |
| DustIQ | Kipp & Zonen soiling sensor spec sheet | https://www.kippzonen.com/products/dustiq-soiling-monitoring-system |
