# -*- coding: utf-8 -*-
"""
SolarGuard Space - headless Cycles CPU renderer.

    blender --background --python render_anim.py -- -t 2 -- <args>

Args (after the first `--`):
  --mode      turntable | dustwave | clean | stills | all     (default: all)
  --quality   fast | final                                     (default: final)
  --frames    N          override sequence length
  --start N --end N      partial render (frame range override)
  --outdir    DIR        root for rendered frames (default <proj>/renders)
  --still     hero | dash | close   (only with --mode stills)
  --tag       NAME       appended to the log/manifest name

Everything is deterministic; the same seed always yields the same frames.
"""

import bpy
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(HERE)
sys.path.append(HERE)

import build_scene as BS  # noqa: E402

SEQS = {"turntable": 96, "dustwave": 96, "clean": 60}

QUALITY = {
    # samples, resx, resy, adaptive-threshold, transparent bounces
    "fast":  dict(samples=14, resx=768, resy=432, adaptive=0.10, trans=18),
    "final": dict(samples=12, resx=1024, resy=576, adaptive=0.08, trans=14),
    "still": dict(samples=40, resx=1600, resy=900, adaptive=0.04, trans=20),
}


def parse():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    a = dict(mode="all", quality="final", frames=None, start=None, end=None,
             outdir=os.path.join(PROJ, "renders"), still=None, tag=None)
    i = 0
    while i < len(argv):
        k = argv[i]
        if k == "--mode":
            a["mode"] = argv[i + 1]; i += 2
        elif k == "--quality":
            a["quality"] = argv[i + 1]; i += 2
        elif k == "--frames":
            a["frames"] = int(argv[i + 1]); i += 2
        elif k == "--start":
            a["start"] = int(argv[i + 1]); i += 2
        elif k == "--end":
            a["end"] = int(argv[i + 1]); i += 2
        elif k == "--outdir":
            a["outdir"] = argv[i + 1]; i += 2
        elif k == "--still":
            a["still"] = argv[i + 1]; i += 2
        elif k == "--tag":
            a["tag"] = argv[i + 1]; i += 2
        else:
            i += 1
    return a


def render_sequence(H, seq, a, q):
    n = a["frames"] or SEQS[seq]
    scn = bpy.context.scene
    BS.animate(H, seq, n)
    BS.setup_render(samples=q["samples"], resx=q["resx"], resy=q["resy"],
                    adaptive=q["adaptive"], trans_bounces=q["trans"])
    out = os.path.join(a["outdir"], seq, "frames")
    os.makedirs(out, exist_ok=True)
    scn.render.filepath = out + "/"
    f0 = a["start"] or 1
    f1 = a["end"] or n
    scn.frame_start = f0
    scn.frame_end = f1
    print("[render] %s frames %d-%d @ %dx%d spp=%d -> %s"
          % (seq, f0, f1, q["resx"], q["resy"], q["samples"], out))
    t0 = time.time()
    try:
        bpy.ops.render.render(animation=True)
    except Exception as e:
        print("[render] ERROR", e)
    dt = time.time() - t0
    nf = max(1, f1 - f0 + 1)
    print("[render] %s DONE  %.1fs  (%.2fs/frame)" % (seq, dt, dt / nf))
    return dict(sequence=seq, frames=nf, seconds=round(dt, 1),
                sec_per_frame=round(dt / nf, 2), resx=q["resx"], resy=q["resy"],
                samples=q["samples"], outdir=out)


def render_still(H, which, a, q):
    scn = bpy.context.scene
    BS.setup_still(H, which)
    BS.setup_render(samples=q["samples"], resx=q["resx"], resy=q["resy"],
                    adaptive=q["adaptive"], trans_bounces=q["trans"])
    out = os.path.join(a["outdir"], "stills")
    os.makedirs(out, exist_ok=True)
    scn.render.filepath = os.path.join(out, "still_%s.png" % which)
    print("[render] still %s @ %dx%d spp=%d" % (which, q["resx"], q["resy"],
                                                q["samples"]))
    t0 = time.time()
    bpy.ops.render.render(write_still=True)
    dt = time.time() - t0
    print("[render] still %s DONE %.1fs" % (which, dt))
    return dict(still=which, seconds=round(dt, 1),
                path=os.path.join(out, "still_%s.png" % which))


def main():
    a = parse()
    q = dict(QUALITY[a["quality"]])
    H = BS.build_all()
    manifest = []

    if a["mode"] == "stills":
        qs = dict(QUALITY["still"])
        which = [a["still"]] if a["still"] else ["hero", "dash", "closeup"]
        for w in which:
            manifest.append(render_still(H, w, a, qs))
    elif a["mode"] == "all":
        for s in ("turntable", "dustwave", "clean"):
            manifest.append(render_sequence(H, s, a, q))
    else:
        manifest.append(render_sequence(H, a["mode"], a, q))

    tag = a["tag"] or a["mode"]
    mf = os.path.join(PROJ, "logs", "render_%s.json" % tag)
    os.makedirs(os.path.dirname(mf), exist_ok=True)
    with open(mf, "w") as f:
        json.dump(manifest, f, indent=2)
    print("[render] manifest ->", mf)
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
