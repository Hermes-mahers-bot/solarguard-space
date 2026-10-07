import json
import time
from urllib.request import Request, urlopen

CAMO = "http://localhost:9377"
USER = "hermes2"
BASE = "https://space-marines.aimaher.com"
BANNED = ["12/12", "12 of 12", "key-gated", "checked 20", ">live<", "· live",
          "home-chat", "foot-status", "Live status", "Team space-Marines · Riyadh"]


def call(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = Request(CAMO + path, data=data, method=method,
                  headers={"Content-Type": "application/json"})
    with urlopen(req, timeout=90) as r:
        return json.loads(r.read() or b"{}")


def text(url):
    with urlopen(url, timeout=60) as r:
        return r.read().decode("utf-8", "replace")


print("=== 1. server-side: banned strings gone from the HTML ===")
for page in ("/", "/dashboard.html", "/technology.html"):
    html = text(BASE + page)
    hits = [b for b in BANNED if b.lower() in html.lower()]
    print(f"  {page:20} {'CLEAN' if not hits else 'FOUND ' + str(hits)}")

print("\n=== 2. browser: homepage agent section + footer ===")
tab = call("POST", "/tabs", {"userId": USER, "sessionKey": "clean", "url": BASE + "/"})["tabId"]
try:
    call("POST", f"/tabs/{tab}/viewport", {"userId": USER, "width": 1440, "height": 1000})
    time.sleep(15)
    print(" ", call("POST", f"/tabs/{tab}/evaluate", {"userId": USER, "expression": """JSON.stringify({
      err: window.__err || null,
      chatPresent: !!document.getElementById('home-chat'),
      agentButton: (document.querySelector('#agent a.btn')||{}).textContent,
      footer: (document.querySelector('footer.site .small.dim')||{}).textContent,
      footerBlocks: [...document.querySelectorAll('footer.site .kicker')].map(e=>e.textContent),
      liveTextOnPage: (document.body.innerText.match(/\\blive\\b/gi)||[]).length,
      twelveRatio: (document.body.innerText.match(/12\\/12|12 of 12/g)||[]).length,
      stats: [...document.querySelectorAll('.stat .v')].map(e=>e.textContent),
      overflowX: document.documentElement.scrollWidth > innerWidth + 1
    })"""})["result"])
    blob = urlopen(f"{CAMO}/tabs/{tab}/screenshot?userId={USER}", timeout=90).read()
    open("/home/hermes2/screenshots/home-agent.png", "wb").write(blob)
    print(f"  home-agent.png {len(blob):,}B")
finally:
    call("DELETE", f"/tabs/{tab}?userId={USER}")

print("\n=== 3. browser: dashboard still alive ===")
tab = call("POST", "/tabs", {"userId": USER, "sessionKey": "clean2", "url": BASE + "/dashboard.html"})["tabId"]
try:
    call("POST", f"/tabs/{tab}/viewport", {"userId": USER, "width": 1440, "height": 1000})
    time.sleep(17)
    print(" ", call("POST", f"/tabs/{tab}/evaluate", {"userId": USER, "expression": """JSON.stringify({
      err: window.__err || null,
      navStatusPresent: !!document.getElementById('nav-status'),
      aiChip: (document.getElementById('ai-status')||{}).textContent,
      kwh: (document.getElementById('ai-output-kwh')||{}).textContent,
      verdict: (document.getElementById('verdict-word')||{}).textContent,
      liveText: (document.body.innerText.match(/\\blive\\b/gi)||[]).length
    })"""})["result"])
finally:
    call("DELETE", f"/tabs/{tab}?userId={USER}")
