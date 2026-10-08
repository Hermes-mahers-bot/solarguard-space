"""Screenshot every slide of the HTML preview, in one browser tab."""
import json
import os
import time
from urllib.request import Request, urlopen

CAMO, USER = "http://localhost:9377", "hermes2"
URL = os.environ.get("PREVIEW", "http://localhost:8123/preview.html")
OUT = "/home/hermes2/solarguard-space/deck/shots"
os.makedirs(OUT, exist_ok=True)


def camo(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = Request(CAMO + path, data=data, method=method, headers={"Content-Type": "application/json"})
    with urlopen(req, timeout=120) as r:
        return json.loads(r.read() or b"{}")


tab = camo("POST", "/tabs", {"userId": USER, "sessionKey": "deckqa", "url": URL})["tabId"]
try:
    camo("POST", f"/tabs/{tab}/viewport", {"userId": USER, "width": 1280, "height": 720})
    time.sleep(8)
    n = int(camo("POST", f"/tabs/{tab}/evaluate",
                 {"userId": USER, "expression": "document.querySelectorAll('.slide').length"})["result"])
    print(f"slides found: {n}")
    for i in range(n):
        camo("POST", f"/tabs/{tab}/evaluate", {"userId": USER, "expression":
             f"document.getElementById('s{i}').scrollIntoView(); window.scrollBy(0,0);"})
        time.sleep(0.6)
        blob = urlopen(f"{CAMO}/tabs/{tab}/screenshot?userId={USER}", timeout=120).read()
        fn = f"{OUT}/s{i:02d}.png"
        open(fn, "wb").write(blob)
        print(f"  {fn}  {len(blob):,}B")
finally:
    camo("DELETE", f"/tabs/{tab}?userId={USER}")
