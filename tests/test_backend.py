"""Local smoke test for the SolarGuard backend — runs against the real APIs.

    cd /home/hermes2/solarguard-space && python3 tests/test_backend.py
"""
import asyncio
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

import sg_agent          # noqa: E402
import sg_datasources as ds   # noqa: E402
import sg_rag            # noqa: E402
import sg_soiling as soil     # noqa: E402
from sg_config import SITES   # noqa: E402

DAMMAM = next(s for s in SITES if s["id"] == "dammam")
JEDDAH = next(s for s in SITES if s["id"] == "jeddah")


def line(t):
    print("\n" + "=" * 72 + f"\n{t}\n" + "=" * 72)


async def main():
    line("1. live forecast pull (Open-Meteo)")
    t0 = time.time()
    fc = await ds.openmeteo_forecast(DAMMAM["lat"], DAMMAM["lon"], days=7)
    days = ds.daily_rollup(fc)
    print(f"{len(fc['hourly'])} hourly rows, {len(days)} daily rows in {time.time()-t0:.1f}s")
    for d in days[:3]:
        print(f"  {d['date']}  irr={d['irradiation_kwh_m2']:>5} kWh/m2  "
              f"Tmax={d['tair_max_c']:>5}C  wind={d['wind_max_ms']:>4} m/s  "
              f"PM10={d['pm10_ugm3']}  dust={d['dust_ugm3']}  AOD={d['aod']}")

    line("2. soiling + cleaning verdict (east coast = heavy dust)")
    rep = await sg_agent.build_report(DAMMAM, 200_000, 7, 14)
    v = rep["verdict"]
    print(f"model used            : {rep['report']['model']}")
    print(f"climate / params      : {rep['site']['climate']} {rep['report']['params']}")
    print(f"day1 soiling loss     : {v['current_soiling_loss_pct']}%")
    print(f"mean loss over horizon: {rep['report']['fixed_schedule']['mean_soiling_loss_pct']}%")
    print(f"verdict               : {v['decision']} ({v['urgency']}% urgency)")
    print(f"reason                : {v['reason']}")
    print(f"7d money at risk      : {v['next_7d_money_at_risk_sar']:,} SAR   "
          f"crew cost {v['cleaning_cost_sar']:,} SAR   payback {v['payback_days']}d")
    avf = v.get("adaptive_vs_fixed")
    if avf:
        print(f"adaptive vs weekly    : energy +{avf['energy_pct']}%  "
              f"cleaning events {avf['cleaning_events_fixed']} -> {avf['cleaning_events_adaptive']}  "
              f"losses {avf['lost_sar_fixed']:,} -> {avf['lost_sar_adaptive']:,} SAR")
    a = rep['annual']
    print(f"literature reference  : {a['literature_annual_loss_pct']}% ({a['literature_source']})")
    for key in ("weekly", "30d", "adaptive", "never"):
        h = a['habits'][key]
        print(f"  {key:<9} interval={str(h['cleaning_interval_days']):<8} "
              f"events/yr={h['cleaning_events_per_year']:>3}  mean loss={h['mean_soiling_loss_pct']:>5}%  "
              f"lost={h['value_lost_sar']:>12,} SAR  net={h['net_cost_sar']:>12,} SAR")
    print(f"opportunity vs weekly : {a['opportunity']}")

    line("3. west vs east coast (the pitch's core claim)")
    for s in (JEDDAH, DAMMAM):
        r = await sg_agent.build_report(s, 100_000, 7, 10)
        print(f"{s['name']:<24} climate={s['climate']:<6} "
              f"day1={r['verdict']['current_soiling_loss_pct']:>5}% "
              f"mean10d={r['report']['fixed_schedule']['mean_soiling_loss_pct']:>5}% "
              f"literature={r['annual']['literature_annual_loss_pct']:>4}%  "
              f"weekly-sim={r['annual']['habits']['weekly']['mean_soiling_loss_pct']}%  "
              f"{r['verdict']['decision']}")

    line("4. satellite layers + tile proxy (NASA GIBS)")
    dates = ds.gibs_available_dates()
    print("freshest dates:", json.dumps(dates, indent=2)[:300])
    for layer in ("MODIS_Terra_Aerosol", "MERRA2_Dust_Surface_Mass_Concentration_Monthly"):
        z, x, y = 5, 20, 12          # tile covering the Arabian peninsula
        data, eff, ct = await ds.gibs_tile(layer, dates[layer], z, x, y)
        print(f"{layer:<58} {len(data) if data else 0:>8,} bytes  effective date {eff}")

    line("5. source health (real HTTP probes)")
    st = await ds.source_status(refresh=True)
    print(f"open sources live: {st['open_live']}/{st['open_total']}   gated: {st['gated']}")
    for s in st["sources"]:
        print(f"  {s['status']:<11} {s['name'][:44]:<46} {s.get('detail','')[:52]}")

    line("6. RAG index")
    print(json.dumps(sg_rag.stats(), indent=2)[:800])
    for h in sg_rag.search("soiling loss percentage weekly cleaning Saudi Arabia", k=3):
        print(f"  [{h['score']}] {h['source']}: {h['text'][:110]}...")

    line("7. DeepSeek copilot end-to-end (tools + RAG)")
    out = await sg_agent.ask("Should I send a cleaning crew to our Dammam plant today? Give me the numbers.",
                             site=DAMMAM, capacity_kwp=200_000)
    print("ok:", out.get("ok"), "| error:", out.get("error"))
    print("tools called:", [t["tool"] for t in out.get("tool_trace", [])])
    print("actions:", out.get("actions"))
    print("\nANSWER:\n" + (out.get("answer") or out.get("message") or "")[:1600])
    print("\ncitations:", [(c["n"], c["source"]) for c in out.get("citations", [])][:6])

    line("DONE")


if __name__ == "__main__":
    asyncio.run(main())
