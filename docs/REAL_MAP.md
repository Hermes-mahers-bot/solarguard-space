# The real map (dashboard)

## What it is

`public/assets/js/sg-realmaps.js` renders the dashboard map with **real basemap
tiles** — country names, roads, city labels, coastline — instead of the
hand-drawn canvas map, and lays our satellite data on top of it.

```js
import { createRealMap } from "./sg-realmaps.js";

const map = createRealMap(document.getElementById("realmap"), {
  onPlace(lat, lon) {},        // click on empty map
  onHover({lat, lon}) {},      // pointer move
  onSelect(site) {},           // catalogue marker clicked
  onLayerChange({id, date}) {},// user changed the satellite layer
  basemap: "dark",             // "dark" | "osm" | "carto"
  controls: true,              // render the in-map control cluster
});

map.setSites(sites);           // [{id,name,lat,lon,region,climate,capacity_mwp}]
map.setMarker(lat, lon, label);// null clears
map.setLayer({id, label, date});
map.setLayerVisible(true);
map.setBasemap("osm");
map.focus(lat, lon, 7);
map.destroy();
```

The interface is deliberately identical to the hand-written canvas map in
`sg-map.js`, so the dashboard can swap between them at runtime — and it does:
if the Leaflet CDN is unreachable, `sg-dashboard.js` falls back to
`import('./sg-map.js')` and mounts the canvas map with the same call signature.
A dead map is not an acceptable failure mode for an operator tool.

## Tile sources and licences

| Layer | URL | Licence / terms |
|---|---|---|
| Carto dark (default) | `https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png` | © OpenStreetMap contributors, © CARTO — free for non-commercial use |
| OpenStreetMap standard | `https://tile.openstreetmap.org/{z}/{x}/{y}.png` | © OpenStreetMap contributors, ODbL — light use only, attributed on the map |
| NASA satellite overlay | our own `/api/satellite/tile/{layer}/{date}/{z}/{x}/{y}.png` | NASA GIBS / EOSDIS, open, no API key |

The NASA overlay is proxied through our API on purpose: GIBS layers are daily and
have gaps (orbit coverage, cloud), and a month of missing tiles looks broken. The
proxy walks back up to 21 days for daily layers and snaps monthly layers (MERRA-2)
to the first of the month, so a date selector always returns *something*, and it
caches the result on disk for a week.

## Why a CDN at all

Leaflet is loaded from unpkg (`leaflet@1.9.4`). It is the one external script the
product depends on, and it is guarded: `sg-realmaps.js` checks for `window.L`
after load and throws a specific error that `sg-dashboard.js` catches, so the
fallback path is automatic. Everything else in the product — both scroll
animations, every chart, the agent UI — is dependency-free.

## Controls

The module renders its own floating cluster (basemap segment, satellite-layer
select, date input, dust on/off). On phones that cluster is hidden by CSS
(`@media (max-width: 719px) { .sg-ctrls { display: none } }`) and the page's own
control row takes over, because a floating cluster on a 390 px screen clips
against the map edge. The page's row is hidden again on desktop unless the canvas
fallback is active (`body.map-canvas`), so the controls are never duplicated.

## Verified

Screenshots in `/home/hermes2/screenshots/`: `d-desk.png` (1440×900, real
basemap + MODIS aerosol overlay + 12 markers) and `d-phone.png` (390×844). Both
were captured through the shared headless browser against the live site; the
failed-resource list is empty at both widths.
