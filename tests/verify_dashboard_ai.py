import json
import sys
import time
from urllib.request import Request, urlopen

CAMO = "http://localhost:9377"
USER = "hermes2"
URL = "https://space-marines.aimaher.com/dashboard.html"


def call(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = Request(CAMO + path, data=data, method=method,
                  headers={"Content-Type": "application/json"})
    with urlopen(req, timeout=90) as r:
        return json.loads(r.read() or b"{}")


def run(width, height, shot):
    tab = call("POST", "/tabs", {"userId": USER, "sessionKey": "aiwire", "url": URL})["tabId"]
    try:
        call("POST", f"/tabs/{tab}/viewport", {"userId": USER, "width": width, "height": height})
        time.sleep(16)
        res = call("POST", f"/tabs/{tab}/evaluate", {"userId": USER, "expression": """JSON.stringify({
          err: window.__err || null,
          chip: (document.querySelector('#ai-status')||{}).textContent,
          asof: (document.querySelector('#ai-asof')||{}).textContent,
          t1: (document.querySelector('#ai-storm-t1')||{}).textContent,
          t2: (document.querySelector('#ai-storm-t2')||{}).textContent,
          t3: (document.querySelector('#ai-storm-t3')||{}).textContent,
          t1class: (document.querySelector('#ai-storm-t1')||{}).className,
          kwh: (document.querySelector('#ai-output-kwh')||{}).textContent,
          kwp: (document.querySelector('#ai-output-kwp')||{}).textContent,
          errk: (document.querySelector('#ai-output-err')||{}).textContent,
          soil: (document.querySelector('#ai-soiling')||{}).textContent,
          soilerr: (document.querySelector('#ai-soiling-err')||{}).textContent,
          note: ((document.querySelector('#ai-skill-note')||{}).textContent||'').slice(0,110),
          overflowX: document.documentElement.scrollWidth > innerWidth + 1,
          inputs: [...document.querySelectorAll('input,select')].map(e=>e.id).filter(Boolean),
          order: ['in-cost','realmap','ai-out'].map(id=>{
             const e=document.getElementById(id); return e? Math.round(e.getBoundingClientRect().top+scrollY):-1;
          })
        })"""})
        print(f"--- {width}x{height} ---")
        print(json.dumps(json.loads(res["result"]), indent=1))
        with urlopen(f"{CAMO}/tabs/{tab}/screenshot?userId={USER}", timeout=90) as r:
            blob = r.read()
        open(f"/home/hermes2/screenshots/{shot}.png", "wb").write(blob)
        print(f"  {shot}.png {len(blob):,}B")
    finally:
        call("DELETE", f"/tabs/{tab}?userId={USER}")


run(1440, 1000, "ai-desk")
run(390, 844, "ai-phone")
