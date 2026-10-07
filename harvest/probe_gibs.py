"""Parse the NASA GIBS WMTS capabilities into a small catalog of dust/aerosol layers
we can actually tile over Saudi Arabia with no API key.

Run:  python3 harvest/probe_gibs.py
Out:  data/gibs_layers.json
"""
import json
import os
import urllib.request
import xml.etree.ElementTree as ET

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, "data", "cache")
os.makedirs(CACHE, exist_ok=True)

CAPS_URL = "https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/1.0.0/WMTSCapabilities.xml"
XML_PATH = os.path.join(CACHE, "gibs_capabilities.xml")

INTEREST = ("aerosol", "aod", "dust", "maiac", "merra2", "pm25", "airs_l2_dust")

def fetch_caps():
    if os.path.exists(XML_PATH) and os.path.getsize(XML_PATH) > 100_000:
        return open(XML_PATH, "rb").read()
    req = urllib.request.Request(CAPS_URL, headers={"User-Agent": "SolarGuard/1.0 (hackathon)"})
    with urllib.request.urlopen(req, timeout=120) as r:
        data = r.read()
    open(XML_PATH, "wb").write(data)
    return data

def main():
    data = fetch_caps()
    print(f"capabilities: {len(data):,} bytes")

    root = ET.fromstring(data)
    W = "{http://www.opengis.net/wmts/1.0}"
    O = "{http://www.opengis.net/ows/1.1}"
    X = "{http://www.w3.org/1999/xlink}"

    layers = {}
    for layer in root.iter(W + "Layer"):
        ident = layer.findtext(O + "Identifier", "").strip()
        if not any(k in ident.lower() for k in INTEREST):
            continue
        title = layer.findtext(O + "Title", "").strip()
        dims = {}
        for dim in layer.iter(W + "Dimension"):
            di = dim.findtext(O + "Identifier", "").strip()
            default = dim.findtext(W + "Default", "").strip()
            values = [v.text.strip() for v in dim.iter(W + "Value") if v.text]
            dims[di] = {"default": default, "n_values": len(values),
                        "first": values[0] if values else None,
                        "last": values[-1] if values else None}
        tms = [l.get(X + "href", "").rsplit("/", 1)[-1].replace(".xml", "")
               for l in layer.iter(W + "TileMatrixSetLink")]
        styles = [s.findtext(O + "Identifier", "").strip() for s in layer.iter(W + "Style")]
        fmt = layer.findtext(W + "Format", "").strip()
        layers[ident] = {"title": title, "formats": fmt, "styles": styles,
                         "tile_matrix_sets": sorted(set(tms)), "dimensions": dims}

    # keep the most useful ones for a Saudi solar-dust dashboard
    keep = [
        "MODIS_Terra_Aerosol",
        "MODIS_Aqua_Aerosol_Optical_Depth_3km",
        "MODIS_Combined_MAIAC_L2G_AerosolOpticalDepth",
        "MODIS_Terra_AOD_Deep_Blue_Land",
        "AIRS_L2_Dust_Score_Day",
        "MERRA2_Dust_Surface_Mass_Concentration_Monthly",
        "MERRA2_Total_Aerosol_Optical_Thickness_550nm_Extinction_Monthly",
        "MERRA2_Total_Dust_Deposition_Dry_Wet_Monthly",
        "MODIS_Terra_CorrectedReflectance_TrueColor",
    ]
    catalog = {k: layers[k] for k in keep if k in layers}
    for k in keep:
        if k not in layers:
            print(f"  !! not found: {k}")

    print(f"\nmatched {len(layers)} dust/aerosol layers; kept {len(catalog)}:\n")
    for k, v in catalog.items():
        d = v["dimensions"].get("Time", {})
        print(f"{k}")
        print(f"   {v['title']}")
        print(f"   tile_matrix_sets: {', '.join(v['tile_matrix_sets'])}")
        print(f"   time: default={d.get('default')} first={d.get('first')} last={d.get('last')} ({d.get('n_values')} values)")

    out = os.path.join(ROOT, "data", "gibs_layers.json")
    json.dump({"source": CAPS_URL, "catalog": catalog}, open(out, "w"), indent=2)
    print(f"\nwrote {out} ({os.path.getsize(out):,} bytes)")

if __name__ == "__main__":
    main()
