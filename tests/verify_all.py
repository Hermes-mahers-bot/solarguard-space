"""Full-system check: every endpoint, every page, both viewports.

    python3 tests/verify_all.py            # everything
    python3 tests/verify_all.py api        # API only (no browser)
    python3 tests/verify_all.py browser    # pages only

Prints a PASS/FAIL line per check and exits non-zero if anything failed.
"""
from __future__ import annotations

import json
import sys
import time
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

BASE = "https://space-marines.aimaher.com"
CAMO = "http://localhost:9377"
USER = "hermes2"
OK, BAD = [], []


def check(name, cond, detail=""):
    (OK if cond else BAD).append(name)
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"   {detail}" if detail else ""))


def get(path, method="GET", body=None, timeout=60):
    url = path if path.startswith("http") else BASE + path
    data = json.dumps(body).encode() if body is not None else None
    req = Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
    try:
        with urlopen(req, timeout=timeout) as r:
            raw = r.read()
            return r.status, raw
    except HTTPError as e:
        return e.code, e.read()
    except URLError as e:
        return 0, str(e).encode()
    except Exception as e:                                    # noqa: BLE001
        return 0, f"{type(e).__name__}: {e}".encode()


def jget(path, **kw):
    st, raw = get(path, **kw)
    try:
        return st, json.loads(raw)
    except Exception:
        return st, {"_raw": raw[:200].decode("utf-8", "replace")}


# ───────────────────────────────────────────────────────── API
def api_checks():
    print("\n=== API endpoints ===")
    simple = [
        ("/api/health", lambda d: d.get("status") == "ok"),
        ("/api/version", lambda d: "version" in d),
        ("/api/sg/status", lambda d: d.get("tool_count") == 10),
        ("/api/ai/status", lambda d: d.get("ai_enabled") is not None),
        ("/api/sites", lambda d: len(d.get("sites", [])) == 12),
        ("/api/sources", lambda d: d.get("open_live", 0) >= 10),
        ("/api/satellite/layers", lambda d: len(d.get("layers", [])) > 0),
        ("/api/rag/stats", lambda d: d.get("chunks", 0) > 300),
        ("/api/model", lambda d: "active" in d),
        ("/api/ai/models", lambda d: d.get("available") is True),
        ("/api/buckets", lambda d: "himawari9" in d),
    ]
    for path, pred in simple:
        st, d = jget(path)
        try:
            good = st == 200 and pred(d)
        except Exception as e:                                 # noqa: BLE001
            good, d = False, f"{type(e).__name__}: {e}"
        check(f"GET {path}", bool(good), "" if good else f"status={st} {str(d)[:90]}")

    st, d = jget("/api/report?site=dammam&capacity_kwp=100000&horizon_days=7")
    good = st == 200 and d.get("verdict", {}).get("decision") in ("clean_now", "wait") \
        and len(d.get("report", {}).get("fixed_schedule", {}).get("rows", [])) >= 5
    check("GET /api/report (site)", good, f"verdict={d.get('verdict', {}).get('decision')}")

    st, d = jget("/api/report?lat=24.71&lon=46.67&capacity_kwp=50000&horizon_days=5")
    check("GET /api/report (coordinates)", st == 200 and d.get("site", {}).get("id") == "custom",
          f"status={st}")

    st, d = jget("/api/report")
    check("GET /api/report without params -> 400", st == 400, f"status={st}")

    st, d = jget("/api/ai?site=dammam&capacity_kwp=100000")
    ok = st == 200 and d.get("ok") and 0 <= d["storm"]["t1"]["p"] <= 1 \
        and 0 < d["output"]["kwh_per_kwp"] <= 12 and 0 <= d["soiling"]["loss_pct"] <= 65 \
        and isinstance(d["output"]["error_kwh_per_kwp"], (int, float))
    check("GET /api/ai (predictions + error bars)", ok, f"status={st} out={d.get('output', {}).get('kwh_per_kwp')}")

    st, d = jget("/api/ai?lat=24.71&lon=46.67&capacity_kwp=100000")
    check("GET /api/ai (arbitrary coordinates)", st == 200 and d.get("ok") is True,
          f"threshold={d.get('model', {}).get('storm_threshold_ugm3')}")

    st, d = jget("/api/forecast?site=dammam&days=5")
    check("GET /api/forecast", st == 200 and len(d.get("days", [])) >= 3, f"status={st}")

    for path in ("/api/dust?lat=26.43&lon=50.10", "/api/aeronet"):
        st, d = jget(path)
        check(f"GET {path}", st == 200, f"status={st}")

    st, d = jget("/api/rag/search?q=soiling%20loss%20cleaning")
    check("GET /api/rag/search", st == 200 and len(d.get("hits", [])) > 0,
          f"{len(d.get('hits', []))} hits")

    st, d = jget("/api/knowledge")
    check("GET /api/knowledge", st == 200, f"status={st}")

    st, _ = get("/api/satellite/tile/modis_aod/2026-10-01/3/5/3.png")
    check("GET /api/satellite/tile (GIBS proxy)", st in (200, 204), f"status={st}")

    st, _ = get("/api/satellite/image?lat=26.43&lon=50.10&layer=modis_aod&size=256")
    check("GET /api/satellite/image (stitcher)", st in (200, 204), f"status={st}")

    st, d = jget("/api/simulate", method="POST",
                 body={"site": "jeddah", "capacity_kwp": 100000, "cleaning_interval_days": 14})
    check("POST /api/simulate", st == 200 and "annual" in d, f"status={st}")

    # the agent, end to end
    st, d = jget("/api/assistant", method="POST",
                 body={"question": "Should we clean Dammam this week? Answer in one sentence.",
                       "history": [], "site": "dammam", "capacity_kwp": 100000})
    ok = st == 200 and d.get("ok") and len(d.get("answer", "")) > 40
    check("POST /api/assistant (agent answers)", ok,
          f"tools={d.get('tools')} chars={len(d.get('answer', ''))}")
    return d


# ───────────────────────────────────────────────────────── pages
def page_checks():
    print("\n=== pages and assets ===")
    pages = ["/", "/dashboard.html", "/technology.html", "/mission/",
             "/assets/css/solarguard.css", "/assets/js/sg-core.js",
             "/assets/js/sg-scrollstory.js", "/assets/js/sg-plume-story.js",
             "/assets/js/sg-realmaps.js", "/assets/js/sg-dashboard.js",
             "/assets/js/sg-home.js", "/assets/js/sg-tech.js",
             "/assets/data/borders.json", "/assets/og.jpg"]
    for p in pages:
        st, raw = get(p)
        check(f"GET {p}", st == 200 and len(raw) > 200, f"status={st} {len(raw)}B")

    st, raw = get("/solarguard")
    check("bare /solarguard redirects (host mount)", st in (307, 308, 200), f"status={st}")


def browser_checks(shots=False):
    print("\n=== browser: JS errors, layout, failed requests ===")
    targets = [("/", "home"), ("/dashboard.html", "dash"), ("/technology.html", "tech")]
    for path, name in targets:
        for w, h, vp in ((1440, 1000, "desktop"), (390, 844, "phone")):
            tab = camo("POST", "/tabs", {"userId": USER, "sessionKey": "verify",
                                         "url": BASE + path})["tabId"]
            try:
                camo("POST", f"/tabs/{tab}/viewport", {"userId": USER, "width": w, "height": h})
                time.sleep(14 if vp == "desktop" else 9)
                res = camo("POST", f"/tabs/{tab}/evaluate", {"userId": USER, "expression": """JSON.stringify({
                    err: window.__err || null,
                    overflowX: document.documentElement.scrollWidth > innerWidth + 1,
                    failed: [...performance.getEntriesByType('resource')]
                              .filter(r=>r.responseStatus>=400).map(r=>r.name.split('/').slice(-1)[0]),
                    text: (document.body.innerText||'').length,
                    navStatus: !!document.getElementById('nav-status')
                })"""})
                d = json.loads(res["result"])
                label = f"{path} @ {w}px"
                check(f"{label}: no JS error", d["err"] is None, str(d["err"])[:80])
                check(f"{label}: no horizontal overflow", not d["overflowX"])
                check(f"{label}: all resources loaded", not d["failed"], str(d["failed"])[:80])
                check(f"{label}: page has content", d["text"] > 400, f"{d['text']} chars")
                if shots:
                    blob = urlopen(f"{CAMO}/tabs/{tab}/screenshot?userId={USER}", timeout=90).read()
                    fn = f"/home/hermes2/screenshots/verify-{name}-{vp}.png"
                    open(fn, "wb").write(blob)
                    print(f"        saved {fn}")
            finally:
                camo("DELETE", f"/tabs/{tab}?userId={USER}")


def camo(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = Request(CAMO + path, data=data, method=method,
                  headers={"Content-Type": "application/json"})
    with urlopen(req, timeout=90) as r:
        return json.loads(r.read() or b"{}")


if __name__ == "__main__":
    what = sys.argv[1] if len(sys.argv) > 1 else "all"
    agent_reply = None
    if what in ("all", "api"):
        agent_reply = api_checks()
    if what in ("all", "browser"):
        page_checks()
        browser_checks(shots=(what == "browser"))
    print(f"\n{len(OK)} passed, {len(BAD)} failed")
    if agent_reply:
        print("\n--- agent answer, for the record ---")
        print(agent_reply.get("answer", "")[:600])
    if BAD:
        print("FAILED: " + "; ".join(BAD))
        raise SystemExit(1)
    print("OK")
