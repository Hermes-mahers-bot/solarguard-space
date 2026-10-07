"""Download small public-domain country outlines so the map and the 3D globe can
be drawn without any runtime dependency or API key.

Source: github.com/johan/world.geo.json (GeoJSON, public domain).
Output: public/assets/data/borders.json
"""
import json
import os
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "public", "assets", "data", "borders.json")
os.makedirs(os.path.dirname(OUT), exist_ok=True)

BASE = "https://raw.githubusercontent.com/johan/world.geo.json/master/countries/{}.geo.json"
COUNTRIES = ["SAU", "YEM", "OMN", "ARE", "QAT", "BHR", "KWT", "IRQ", "JOR", "EGY",
             "SDN", "ERI", "ETH", "DJI", "SYR", "IRN", "TUR", "ISR", "PSE", "LBN"]

out = {}
for cc in COUNTRIES:
    try:
        req = urllib.request.Request(BASE.format(cc), headers={"User-Agent": "SolarGuard/1.0"})
        with urllib.request.urlopen(req, timeout=45) as r:
            gj = json.loads(r.read().decode())
        rings = []
        for feat in gj.get("features", []):
            geom = feat.get("geometry") or {}
            if geom.get("type") == "Polygon":
                rings.extend(geom["coordinates"])
            elif geom.get("type") == "MultiPolygon":
                for poly in geom["coordinates"]:
                    rings.extend(poly)
        # keep only reasonably large rings (drop tiny islands) and round coords
        keep = []
        for ring in rings:
            if len(ring) < 6:
                continue
            keep.append([[round(float(x), 4), round(float(y), 4)] for x, y in ring])
        if keep:
            out[cc] = keep
            print(f"{cc}: {len(keep)} ring(s), {sum(len(r) for r in keep)} points")
    except Exception as e:
        print(f"{cc}: FAILED {type(e).__name__}: {e}")

json.dump(out, open(OUT, "w"))
print(f"\nwrote {OUT} ({os.path.getsize(OUT):,} bytes) with {len(out)} countries")
