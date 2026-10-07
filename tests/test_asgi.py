"""In-process ASGI test for the SolarGuard sub-app.

Exercises the real routes (including live upstream calls and the DeepSeek copilot)
without starting a server or touching the live site.

    cd /home/hermes2/solarguard-space && python3 tests/test_asgi.py
"""
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

import httpx                    # noqa: E402
import sg_app                   # noqa: E402

BASE = "http://sg.local"


async def main():
    transport = httpx.ASGITransport(app=sg_app.sg_app)
    async with httpx.AsyncClient(transport=transport, base_url=BASE, timeout=120) as c:
        checks = []

        async def probe(method, url, **kw):
            r = await c.request(method, url, **kw)
            body = r.text[:200].replace("\n", " ")
            print(f"{method:5} {url[:74]:<76} {r.status_code}  {len(r.content):>8,}B  {body[:80]}")
            checks.append((url, r.status_code))
            return r

        await probe("GET", "/api/health")
        await probe("GET", "/api/version")
        await probe("GET", "/api/ai/status")
        await probe("GET", "/api/sites")
        r = await probe("GET", "/api/satellite/layers")
        layers = r.json()
        await probe("GET", f"/api/satellite/tile/MODIS_Terra_Aerosol/{layers['dates']['MODIS_Terra_Aerosol']}/4/10/6.png")
        await probe("GET", "/api/sources")
        await probe("GET", "/api/rag/stats")
        await probe("GET", "/api/model")
        await probe("GET", "/api/aeronet?lat=24.71&lon=46.67")
        await probe("GET", "/api/dust?site=dammam&days=5")
        r = await probe("GET", "/api/report?site=dammam&capacity_kwp=100000&cleaning_interval_days=10&horizon_days=10")
        rep = r.json()
        fsrow = rep["report"]["fixed_schedule"]["rows"]
        print("\n  report →", json.dumps({
            "site": rep["site"]["name"], "climate": rep["report"]["params"]["climate"],
            "day1_loss_pct": fsrow[0]["soiling_loss_pct"],
            "verdict": rep["verdict"]["decision"],
            "money_at_risk_7d": rep["verdict"]["next_7d_money_at_risk_sar"],
            "crew_cost": rep["verdict"]["cleaning_cost_sar"],
            "adaptive_net": rep["annual"]["habits"]["adaptive"]["net_cost_sar"],
            "your_net": rep["annual"]["habits"]["industry_today"]["net_cost_sar"],
            "saving_sar": rep["annual"]["opportunity"]["sar_saved_year"],
        }, indent=2))
        await probe("POST", "/api/simulate", json={"site": "jeddah", "capacity_kwp": 50000,
                                                   "cleaning_interval_days": 30, "horizon_days": 7})
        await probe("GET", "/api/report?lat=27.99&lon=35.25&capacity_kwp=5000&horizon_days=7")
        await probe("GET", "/api/report")
        r = await probe("POST", "/api/assistant", json={
            "question": "Compare Jeddah and Dammam and tell me where to clean first.",
            "capacity_kwp": 100000, "site": "dammam"})
        out = r.json()
        print("\n  copilot →", json.loads(json.dumps({
            "ok": out.get("ok"), "tools": [t["tool"] for t in out.get("tool_trace", [])],
            "actions": out.get("actions"), "ms": out.get("elapsed_ms"),
            "answer_chars": len(out.get("answer") or ""),
        }, default=str)))
        print("  answer preview:", (out.get("answer") or "")[:420].replace("\n", " "))

        # static pages
        for page in ["/", "/dashboard.html", "/technology.html", "/api/ai", "/api/ai/models",
                     "/assets/css/solarguard.css",
                     "/assets/js/sg-core.js", "/assets/js/sg-scrollstory.js",
                     "/assets/js/sg-plume-story.js", "/assets/js/sg-realmaps.js",
                     "/assets/data/borders.json", "/api/sg/status"]:
            await probe("GET", page)

    print("\n--- results ---")
    bad = [(u, s) for u, s in checks if s >= 500]
    for u, s in checks:
        if s >= 400:
            print(f"  {s}  {u}")
    print("5xx count:", len(bad))
    print("OK" if not bad else "SOME ROUTES FAILED")


if __name__ == "__main__":
    asyncio.run(main())
