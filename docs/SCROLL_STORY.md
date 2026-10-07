# SCROLL_STORY — the SolarGuard scroll storyboard

`public/assets/js/sg-scrollstory.js` renders the homepage's cinematic scene. The
page owns the scroll; the module owns the picture. Everything is canvas&nbsp;2D
with hand-rolled projection maths — no three.js, no CDN, no external images, no
network access of any kind. Pull the module out of the repo and it still draws.

```js
import { createScrollStory } from "./assets/js/sg-scrollstory.js";

const story = createScrollStory(canvas, { siteName: "DAMMAM / EASTERN PROV" });

addEventListener("scroll", () => {
  const max = document.documentElement.scrollHeight - innerHeight;
  story.setProgress(scrollY / Math.max(max, 1));   // 0 → 1
}, { passive: true });

story.start();      // one rAF loop
story.resize();     // call ONLY from a real resize event
story.destroy();    // page teardown
```

Live numbers come from the API and are pushed in; the HUD never fetches:

```js
story.setData({ soilingLossPct: 12.4, outputPct: 87.6, dustUgm3: 138,
                siteName: "Dammam / Eastern Prov" });
story.setData(null);   // back to progress-interpolated numbers
```

### API

| method | notes |
|---|---|
| `setProgress(p, instant?)` | `p` clamped to 0…1. Omit `instant` to get the ~0.15 s damping that hides scroll jitter; pass `true` when you need the frame *now* (tests, screenshots, a scrubber). |
| `setData(obj \| null)` | Partial objects are fine. `soilingLossPct` is the only field that switches the HUD into live mode; `outputPct` defaults to `100 − soiling`. `siteName` renames the footer. |
| `start()` / `stop()` | `stop()` cancels the rAF loop and renders one last frame at the current progress, so the canvas is never stale. |
| `resize()` | Reads `clientWidth/clientHeight/devicePixelRatio` and rebuilds geometry. The render loop never reads the DOM. |
| `destroy()` | Cancels the loop, drops listeners, clears arrays. |
| `numbers()` | The HUD values currently on screen — handy for assertions. |
| `isRunning()` / `isReduced()` / `getProgress()` | introspection for the page and tests. |

`opts`: `{ siteName, staticProgress, reducedMotion, dprCap, smooth, blobScale, blobAlpha }`.
`blobScale` / `blobAlpha` (default `0.7` / `0.72`) dial the storm's churning
puffs — turn them down if the mass starts reading as out-of-focus bokeh.

---

## 1. Projection

World axes: **+x** right, **+y** up, **+z** away from the camera. The camera is
parked in front of the array and slightly to its left, then yawed a few degrees
and pitched down 6.6°:

```
CAM = { x: -2.5, y: 5.2, z: -13.5, yaw: -0.07, pitch: 0.115 }   // radians
focal = canvasHeight * 1.15      // ≈ 53° horizontal FOV at 16:9, tighter when tall
```

`project(x, y, z)` is a textbook pinhole — translate to camera space, rotate by
yaw about Y, rotate by pitch about X, then divide by depth:

```
z1 = -dx·sin(yaw) + dz·cos(yaw)          x1 = dx·cos(yaw) + dz·sin(yaw)
y2 =  dy·cos(pitch) + z1·sin(pitch)      z2 = -dy·sin(pitch) + z1·cos(pitch)
screen = ( CX + focal·x1/z2 ,  CY - focal·y2/z2 )     // null if z2 < 0.35
```

Two derived quantities fall out of the same maths and are used every frame:

* **Horizon.** For a ground point at infinite distance `y2/z2 → tan(pitch)`, so
  the horizon is a constant `horizonY = CY − focal·tan(pitch)` — no mesh, no
  clipping, and the ground is simply a gradient rect below that line.
* **Sun.** `projectDir()` runs a *direction* through the same rotations. The sun's
  world direction is built from an azimuth/elevation pair, so its screen position
  can never disagree with the 3D camera.

**Array geometry.** Rows run along +z; each row is `cols` modules laid end to end.
Modules rotate about the **z** axis, which is exactly how a single-axis N-S
horizontal tracker behaves: the glass faces east, flattens at noon, faces west.

| viewport | rows × cols | modules | half-width |
|---|---|---|---|
| ≥ 640 px | 6 × 5 | 30 | 9.3 world units |
| < 640 px | 5 × 6 | 30 | 5.2 world units |

The grid is drawn by **bilinear interpolation of the four projected corners**
(`bl(a,b,c2,e,s,t)`), so cell lines, speckle, the sheen band and the washer head
all land on the module's real perspective, not on a screen-space rectangle.

Painter's algorithm: modules are sorted back-to-front by mean depth each frame.

---

## 2. Phase timings

Progress `p` is the only input. `updateDay(p)` derives everything else.

| p | beat | what changes |
|---|---|---|
| 0.00 | **dawn** | sun low-left (az −25°, el 1.6°), sky deep blue → warm horizon, tracker at max tilt 36°, glass clean |
| 0.00–0.26 | accumulation | soiling creeps, motes thin, sheen strong |
| ≈ 0.475 | **noon** | sun highest (el 13°) and centred, `trackerT = 1` → panels fall to ~2° (flat) |
| 0.26–0.64 | **storm builds** | `stormAmt` ramps, sky → ochre, sun bloom dies, mote density climbs |
| 0.40–0.70 | **front** | wavy ochre wall crosses the frame; it swallows the array around **p ≈ 0.6** |
| 0.64–0.72 | **buried** | peak soiling (~32 %), HUD reads `DUST STORM` |
| 0.72–0.95 | **cleaning** | wash bar sweeps in *projected* left→right order, each module it passes returns to clean, cyan glint + spray |
| 0.95–1.00 | **clear** | sky opens, panels blue again, sun low-right, soiling back near zero |

Derived scalars (all in `updateDay`):

```
arc      = sin(π · p/0.95) ^ 0.9      // 0 dawn/dusk … 1 noon  → tracker + sun height
acc      = smoothstep(0.26, 0.64, p)  // dust accumulation
cleanT   = smoothstep(0.72, 0.95, p) ^ 0.7   // sweep position, eased out
stormAmt = acc · (1 − 0.94·cleanT)    // what the glass + veil + motes actually see
frontP   = smoothstep(0.40, 0.70, p)  // leading edge of the wall
```

### The cleaning pass — why it is ordered in screen space

Every frame `drawArray()` projects all modules, records each one's **screen-space
centre x**, and takes `sweepX = min(screenX) + cleanT · (max(screenX) − min(screenX))`.
A module is "washed" by `smoothstep(sweepX−26, sweepX+26, m.cx2)`. Because the
camera is yawed, the projected left→right order is *not* the world x order — the
far corner is drawn first. That is the correct, visible order, and it is why the
sweep is computed from projections rather than from `m.c` (the column index).
Washed modules keep a faint cool cast so the cleaned half of the array separates
from the ochre half at a glance.

---

## 3. Retuning

Everything worth touching lives in three blocks at the top of the factory.

**`PHASE`** — the beats, in progress units. Widen a gap to slow a beat down:
`stormStart: 0.26` → larger delays the dust; `frontStart/frontEnd` move the wall
(it engulfs the array when `frontP ≈ 0.7–1`, so `frontEnd ≈ 0.70` puts the burial
at `p ≈ 0.60`); `cleanStart/cleanEnd` move the wash.

**`CAM`** — the shot. Raising `CAM.y` looks down more and flattens the array;
lowering `pitch` lifts the horizon and gives more sky; `yaw` controls the 3/4
angle. `focal = H × 1.15` is set in `resize()` — raise the multiplier for a
telephoto, flatter, more "product page" look (and reduce `halfX` to keep the
array in frame), lower it for a wider, more dramatic one.

**`SKY_KEYS`** — five colour keys (`zenith, mid, horizon`) at p = 0, 0.30, 0.55,
0.72, 1.00, linearly interpolated. To push the storm warmer, edit the 0.55/0.72
entries; to keep more blue at the end, edit the 1.00 entry.

Also worth knowing:
* `MAX_TILT` (0.62 rad) / `MIN_TILT` (−0.10 rad) bound the tracker. The lower
  bound is deliberately not the mirror of the upper one: clamping the glass so it
  never presents its back to the camera keeps the array readable during the
  cleaning pass, which is the one moment the viewer must read every panel.
* `module.speck` and `module.seed` come from a stable hash, so per-module dust
  speckle never flickers between frames.
* The camera "breathing" (`heave`) and the storm churn are the only motion that
  continues while the page is not scrolling — everything else is scroll-driven.

---

## 4. Performance budget

Measured with the bench (see §5) on this box — headless, no GPU, canvas 2D:

| | 390 × 844 (DPR 2) | 1440 × 900 (DPR 1) |
|---|---|---|
| per-frame render | **≈ 2.5 ms** | **≈ 6 ms** |
| budget at 60 fps | 16.7 ms | 16.7 ms |

Rules the module sticks to:

* **DPR is capped at 1.5** (`dprCap`). A 3× phone backbuffer would cost 4× the
  fill for no visible gain on a full-bleed scene.
* **Particle counts scale with canvas area** — `clamp(round(W·H/9000), 30, 190)`
  motes, and **everything halves below 640 px** width. Blob counts, shrub counts
  and the array's row/column split also drop on phones.
* **No layout thrash.** `clientWidth`, `clientHeight` and `devicePixelRatio` are
  read in `resize()` and nowhere else. The loop touches no DOM node, ever.
* **One `requestAnimationFrame` loop** for the whole scene (the bench page runs a
  second one only to display its own FPS counter).
* **Cheap fills.** Flat `rgb()` fills for the module frames; one gradient per
  module for the glass; the ground is a gradient rect plus five dune ridge paths
  rather than a mesh. The one blurred fill (`ctx.filter`) is desktop-only.

---

## 5. Accessibility fallback

`prefers-reduced-motion: reduce` is honoured, and it is honoured *live* — the
module subscribes to the media query's `change` event, so flipping the OS setting
mid-session takes effect immediately.

When reduced motion is on:

* no `requestAnimationFrame` loop is started at all;
* a **single static mid-scene frame** is drawn at `opts.staticProgress`
  (default `0.42` — sun up, trackers flat, array clean, sky warm);
* `setProgress()` still works, but it snaps (no damping) and repaints one frame,
  so a page that scrubs on scroll still updates — it simply never *animates*;
* `resize()` and `setData()` repaint the static frame.

The canvas carries `role="img"` and an `aria-label` describing the story
("Scroll storyboard: the sun arcs over a desert solar array that is buried by a
dust storm and then cleaned."), and every number the scene shows is also
available from `story.numbers()` and, on the real page, from the text of the
surrounding sections — the animation is never the sole carrier of information.

Check it yourself: `story-test.html?reduced=1` forces the reduced path, and the
bench's `reduced motion` row reports what the module detected.

---

## 6. Bench (`public/story-test.html`)

Standalone page, dark shell, same palette tokens. Contains:

* the sticky canvas over a **520 vh scroller**, so scrolling really drives it;
* a live progress readout and a slider that can **pin** progress (used for
  screenshots and for stepping through the beats);
* sliders for soiling / dust / site name plus **FEED SLIDER DATA → HUD**, which
  pushes synthetic values through `setData()`;
* **START / STOP / STATIC FRAME / RESET** buttons;
* **FETCH LIVE API NUMBERS**, which pulls
  `https://space-marines.aimaher.com/solarguard/api/report?site=dammam&capacity_kwp=100000&horizon_days=10`
  and reads `report.fixed_schedule.rows[0].soiling_loss_pct` and
  `days[0].dust_ugm3` (both shown in the panel, then handed to `setData()`);
* a live FPS readout.

Query params: `?clean=1` hides the control panel (clean screenshots),
`?reduced=1` forces the reduced-motion path, `?p=0.62` pins a progress value.
For testing, the page exposes `window.__story`, `window.__setProgress(p, instant)`,
`window.__setData(obj)`, `window.__loadApi()` and `window.__errors`.

```sh
cd solarguard-space
python3 -m http.server 8124 --directory public
# → http://localhost:8124/story-test.html          (full bench)
# → http://localhost:8124/story-test.html?clean=1  (scene only)
```
