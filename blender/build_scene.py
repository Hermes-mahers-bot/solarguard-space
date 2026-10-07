# -*- coding: utf-8 -*-
"""
SolarGuard Space - cinematic procedural scene builder.

Blender 4.5.3 LTS, headless, Cycles CPU only (no GPU on this box).

Everything here is 100% procedural (mathutils.noise meshes + procedural shader
nodes + Sky Texture). No external textures / HDRI, so it works fully offline.

Usage (scene + asset export):
    blender --background --python build_scene.py -- --export-glb
    blender --background --python build_scene.py -- --save-blend /tmp/sg.blend

The renderer (render_anim.py) does `import build_scene` and calls:
    H = build_scene.build_all()             -> dict of handles
    build_scene.animate(H, "turntable", 96) -> keyframes for that sequence
    build_scene.setup_render(H, mode=...)   -> cycles settings
    build_scene.setup_still(H, "hero")      -> camera for a still
"""

import bpy
import math
import os
import random
import sys

from mathutils import Vector, Euler, noise

DEG = math.pi / 180.0

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(HERE)

# --------------------------------------------------------------------------
# tunables
# --------------------------------------------------------------------------
CFG = dict(
    rows=6,
    per_row=14,
    module_w=2.0,
    module_h=1.0,
    module_t=0.045,
    row_pitch=5.6,
    tilt_deg=24.0,
    tube_z=1.35,
    ground_size=560.0,
    ground_sub=176,
    dust_cards=260,
    rocks=46,
    seed=20261007,
)

ARRAY_CENTER = Vector((0.0, 0.0, 0.0))
ARRAY_W = CFG["per_row"] * (CFG["module_w"] + 0.06)
ARRAY_D = (CFG["rows"] - 1) * CFG["row_pitch"]

# sun: azimuth from +Y axis, elevation above horizon
SUN_AZ = 152.0
SUN_EL = 13.5


def smoothstep(a, b, x):
    if b == a:
        return 0.0 if x < a else 1.0
    t = min(1.0, max(0.0, (x - a) / (b - a)))
    return t * t * (3.0 - 2.0 * t)


def clamp(v, lo=0.0, hi=1.0):
    return max(lo, min(hi, v))


# --------------------------------------------------------------------------
# scene utilities
# --------------------------------------------------------------------------
def purge():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    for coll in (bpy.data.objects, bpy.data.meshes, bpy.data.materials,
                 bpy.data.lights, bpy.data.cameras, bpy.data.textures,
                 bpy.data.particles, bpy.data.worlds):
        for item in list(coll):
            try:
                coll.remove(item)
            except Exception:
                pass


def col():
    return bpy.context.scene.collection


def link(obj):
    col().objects.link(obj)
    return obj


def sock(node, name, value):
    """Set a node input by name, silently ignoring renamed/missing sockets."""
    try:
        if name in node.inputs:
            node.inputs[name].default_value = value
            return True
    except Exception:
        pass
    return False


def aim(obj, target):
    """Point obj's -Z axis at target (correct for cameras and sun lamps)."""
    d = Vector(target) - obj.location
    if d.length < 1e-6:
        return obj
    obj.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()
    return obj


def new_obj(name, mesh):
    o = bpy.data.objects.new(name, mesh)
    link(o)
    return o


def sg_set(o, x, y, z):
    """Store a local-space origin on an object (custom props must be scalars)."""
    o["sg_x"] = float(x)
    o["sg_y"] = float(y)
    o["sg_z"] = float(z)


def sg_get(o):
    return (o["sg_x"], o["sg_y"], o["sg_z"])


# --------------------------------------------------------------------------
# materials
# --------------------------------------------------------------------------
MCACHE = {}


def _mat(name):
    m = bpy.data.materials.get(name)
    if m:
        return m
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    for n in list(nt.nodes):
        if n.type != "OUTPUT_MATERIAL":
            nt.nodes.remove(n)
    out = [n for n in nt.nodes if n.type == "OUTPUT_MATERIAL"][0]
    out.location = (900, 0)
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.location = (520, 0)
    nt.links.new(bsdf.outputs[0], out.inputs[0])
    MCACHE[name] = (nt, out, bsdf)
    return m


def _bsdf(m):
    """Principled BSDF of a material created by _mat()."""
    e = MCACHE.get(m.name)
    if e:
        return e[2]
    return [n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED"][0]


def _out(m):
    e = MCACHE.get(m.name)
    if e:
        return e[1]
    return [n for n in m.node_tree.nodes if n.type == "OUTPUT_MATERIAL"][0]


def _nt(m):
    return m.node_tree


def mat_sand():
    m = _mat("SG_Sand")
    nt, b = m.node_tree, _bsdf(m)
    tex = nt.nodes.new("ShaderNodeTexCoord")
    tex.location = (-900, 0)
    mp = nt.nodes.new("ShaderNodeMapping")
    mp.location = (-700, 0)
    sock(mp, "Scale", (1.0, 1.0, 1.0))
    nt.links.new(tex.outputs["Object"], mp.inputs["Vector"])

    n1 = nt.nodes.new("ShaderNodeTexNoise")
    n1.location = (-480, 120)
    sock(n1, "Scale", 0.9)
    sock(n1, "Detail", 8.0)
    sock(n1, "Roughness", 0.62)
    nt.links.new(mp.outputs["Vector"], n1.inputs["Vector"])

    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.location = (-260, 120)
    ramp.color_ramp.elements[0].position = 0.30
    ramp.color_ramp.elements[0].color = (0.170, 0.105, 0.052, 1.0)
    ramp.color_ramp.elements[1].position = 0.72
    ramp.color_ramp.elements[1].color = (0.585, 0.430, 0.252, 1.0)
    e = ramp.color_ramp.elements.new(0.52)
    e.color = (0.360, 0.245, 0.130, 1.0)
    nt.links.new(n1.outputs["Fac"], ramp.inputs["Fac"])
    nt.links.new(ramp.outputs["Color"], b.inputs["Base Color"])

    n2 = nt.nodes.new("ShaderNodeTexNoise")
    n2.location = (-480, -220)
    sock(n2, "Scale", 22.0)
    sock(n2, "Detail", 6.0)
    sock(n2, "Roughness", 0.7)
    nt.links.new(mp.outputs["Vector"], n2.inputs["Vector"])

    n3 = nt.nodes.new("ShaderNodeTexNoise")
    n3.location = (-480, -480)
    sock(n3, "Scale", 2.2)
    sock(n3, "Detail", 4.0)
    nt.links.new(mp.outputs["Vector"], n3.inputs["Vector"])

    mixb = nt.nodes.new("ShaderNodeMixRGB")
    mixb.location = (-260, -300)
    mixb.blend_type = "MIX"
    mixb.inputs["Fac"].default_value = 0.45
    nt.links.new(n2.outputs["Fac"], mixb.inputs[1])
    nt.links.new(n3.outputs["Fac"], mixb.inputs[2])

    bump = nt.nodes.new("ShaderNodeBump")
    bump.location = (220, -320)
    sock(bump, "Strength", 0.32)
    sock(bump, "Distance", 0.06)
    nt.links.new(mixb.outputs["Color"], bump.inputs["Height"])
    nt.links.new(bump.outputs["Normal"], b.inputs["Normal"])

    sock(b, "Metallic", 0.0)
    sock(b, "Roughness", 0.86)
    sock(b, "Specular IOR Level", 0.25)
    return m


def mat_rock():
    m = _mat("SG_Rock")
    nt, b = m.node_tree, _bsdf(m)
    tex = nt.nodes.new("ShaderNodeTexCoord")
    mp = nt.nodes.new("ShaderNodeMapping")
    nt.links.new(tex.outputs["Object"], mp.inputs["Vector"])
    n = nt.nodes.new("ShaderNodeTexNoise")
    sock(n, "Scale", 14.0)
    sock(n, "Detail", 8.0)
    nt.links.new(mp.outputs["Vector"], n.inputs["Vector"])
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].color = (0.140, 0.104, 0.070, 1.0)
    ramp.color_ramp.elements[1].color = (0.420, 0.318, 0.216, 1.0)
    nt.links.new(n.outputs["Fac"], ramp.inputs["Fac"])
    nt.links.new(ramp.outputs["Color"], b.inputs["Base Color"])
    bump = nt.nodes.new("ShaderNodeBump")
    sock(bump, "Strength", 0.55)
    sock(bump, "Distance", 0.05)
    nt.links.new(n.outputs["Fac"], bump.inputs["Height"])
    nt.links.new(bump.outputs["Normal"], b.inputs["Normal"])
    sock(b, "Roughness", 0.92)
    return m


def mat_steel(name="SG_Steel", rough=0.42, base=(0.055, 0.058, 0.062, 1.0),
              metallic=0.85):
    m = _mat(name)
    b = _bsdf(m)
    sock(b, "Base Color", base)
    sock(b, "Metallic", metallic)
    sock(b, "Roughness", rough)
    return m


def mat_aluminium():
    m = _mat("SG_Alu")
    nt, b = m.node_tree, _bsdf(m)
    sock(b, "Base Color", (0.560, 0.570, 0.580, 1.0))
    sock(b, "Metallic", 0.92)
    sock(b, "Roughness", 0.24)
    tex = nt.nodes.new("ShaderNodeTexCoord")
    mp = nt.nodes.new("ShaderNodeMapping")
    sock(mp, "Scale", (1.0, 1.0, 0.06))
    nt.links.new(tex.outputs["Object"], mp.inputs["Vector"])
    n = nt.nodes.new("ShaderNodeTexNoise")
    sock(n, "Scale", 40.0)
    sock(n, "Detail", 3.0)
    nt.links.new(mp.outputs["Vector"], n.inputs["Vector"])
    bump = nt.nodes.new("ShaderNodeBump")
    sock(bump, "Strength", 0.12)
    sock(bump, "Distance", 0.01)
    nt.links.new(n.outputs["Fac"], bump.inputs["Height"])
    nt.links.new(bump.outputs["Normal"], b.inputs["Normal"])
    return m


def mat_pv():
    """
    PV module glass. Procedural 12x6 cell grid (object coords) + sunken busbars,
    anti-reflective glass surface, and a dust layer driven by two node values
    that render_anim.py keyframes:

        DUST_AMT   -> how caked the glass is (0..1)
        SWEEP_FROM / SWEEP_TO -> world-X wipe front for the 'clean' sequence
                                 (set far outside the array for dusty shots)

    Returned via node name lookup:  bpy.data.materials['SG_PV'].node_tree.nodes
    """
    m = _mat("SG_PV")
    nt, out, b = m.node_tree, _out(m), _bsdf(m)

    tex = nt.nodes.new("ShaderNodeTexCoord")
    tex.location = (-1400, 0)
    mp = nt.nodes.new("ShaderNodeMapping")
    mp.location = (-1200, 0)
    # anisotropy so brick rows (4/tile) and cols (2/tile) end up square cells:
    # X: 3 tiles/m * 2 = 6 cells/m ; Y: 1.5 tiles/m * 4 = 6 cells/m  -> 16.7cm
    sock(mp, "Scale", (3.0, 1.5, 1.0))
    nt.links.new(tex.outputs["Object"], mp.inputs["Vector"])

    brick = nt.nodes.new("ShaderNodeTexBrick")
    brick.location = (-980, 60)
    sock(brick, "Scale", 1.0)
    sock(brick, "Mortar Size", 0.022)
    sock(brick, "Mortar Smooth", 0.6)
    sock(brick, "Bias", 0.0)
    sock(brick, "Brick Width", 0.5)
    sock(brick, "Row Height", 0.25)
    sock(brick, "Color1", (0.0085, 0.0135, 0.0300, 1.0))
    sock(brick, "Color2", (0.0125, 0.0195, 0.0420, 1.0))
    sock(brick, "Mortar", (0.300, 0.310, 0.330, 1.0))
    try:
        brick.offset = 0.0
        brick.offset_frequency = 1
        brick.squash = 1.0
        brick.squash_frequency = 2
    except Exception:
        pass
    nt.links.new(mp.outputs["Vector"], brick.inputs["Vector"])

    # ---------------- dust layer ----------------
    dust_amt = nt.nodes.new("ShaderNodeValue")
    dust_amt.location = (-1400, -520)
    dust_amt.name = "DUST_AMT"
    dust_amt.label = "DUST_AMT"
    dust_amt.outputs[0].default_value = 0.12

    streak = nt.nodes.new("ShaderNodeTexNoise")
    streak.location = (-980, -520)
    sock(streak, "Scale", 2.4)
    sock(streak, "Detail", 8.0)
    sock(streak, "Roughness", 0.65)
    sock(streak, "Distortion", 0.4)
    nt.links.new(mp.outputs["Vector"], streak.inputs["Vector"])

    sramp = nt.nodes.new("ShaderNodeValToRGB")
    sramp.location = (-760, -520)
    sramp.color_ramp.elements[0].position = 0.28
    sramp.color_ramp.elements[1].position = 0.78
    nt.links.new(streak.outputs["Fac"], sramp.inputs["Fac"])

    # world-space sweep front for the cleaning wipe
    geo = nt.nodes.new("ShaderNodeNewGeometry")
    geo.location = (-1400, -780)
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    sep.location = (-1200, -780)
    nt.links.new(geo.outputs["Position"], sep.inputs["Vector"])
    mr = nt.nodes.new("ShaderNodeMapRange")
    mr.location = (-980, -780)
    mr.name = "SWEEP"
    mr.label = "SWEEP"
    mr.clamp = True
    sock(mr, "From Min", 200.0)
    sock(mr, "From Max", 204.0)
    sock(mr, "To Min", 0.0)
    sock(mr, "To Max", 1.0)
    nt.links.new(sep.outputs["X"], mr.inputs["Value"])

    sub = nt.nodes.new("ShaderNodeMath")
    sub.location = (-760, -780)
    sub.operation = "SUBTRACT"
    sub.inputs[0].default_value = 1.0
    nt.links.new(mr.outputs["Result"], sub.inputs[1])

    dustmask = nt.nodes.new("ShaderNodeMath")
    dustmask.location = (-540, -700)
    dustmask.name = "DUST_MASK"
    dustmask.operation = "MULTIPLY"
    dustmask.use_clamp = True
    nt.links.new(dust_amt.outputs[0], dustmask.inputs[0])
    nt.links.new(sub.outputs[0], dustmask.inputs[1])

    smix = nt.nodes.new("ShaderNodeMath")
    smix.location = (-540, -560)
    smix.operation = "MULTIPLY"
    nt.links.new(sramp.outputs["Color"], smix.inputs[0])
    nt.links.new(dustmask.outputs[0], smix.inputs[1])

    glassmix = nt.nodes.new("ShaderNodeMixRGB")
    glassmix.location = (-260, 0)
    glassmix.blend_type = "MIX"
    nt.links.new(brick.outputs["Color"], glassmix.inputs[1])
    glassmix.inputs[2].default_value = (0.640, 0.505, 0.325, 1.0)
    nt.links.new(smix.outputs[0], glassmix.inputs["Fac"])
    nt.links.new(glassmix.outputs["Color"], b.inputs["Base Color"])

    # roughness: glass -> dusty
    rmix = nt.nodes.new("ShaderNodeMapRange")
    rmix.location = (-260, -260)
    sock(rmix, "To Min", 0.075)
    sock(rmix, "To Max", 0.880)
    nt.links.new(smix.outputs[0], rmix.inputs["Value"])
    nt.links.new(rmix.outputs["Result"], b.inputs["Roughness"])

    # coat only on clean glass
    cmix = nt.nodes.new("ShaderNodeMapRange")
    cmix.location = (-260, -420)
    sock(cmix, "To Min", 0.55)
    sock(cmix, "To Max", 0.0)
    nt.links.new(smix.outputs[0], cmix.inputs["Value"])
    sock(b, "Coat Weight", 0.5)
    try:
        nt.links.new(cmix.outputs["Result"], b.inputs["Coat Weight"])
    except Exception:
        pass

    # micro bump for dust grain
    gn = nt.nodes.new("ShaderNodeTexNoise")
    gn.location = (-540, -960)
    sock(gn, "Scale", 60.0)
    sock(gn, "Detail", 6.0)
    nt.links.new(mp.outputs["Vector"], gn.inputs["Vector"])
    gmix = nt.nodes.new("ShaderNodeMath")
    gmix.location = (-260, -960)
    gmix.operation = "MULTIPLY"
    nt.links.new(gn.outputs["Fac"], gmix.inputs[0])
    nt.links.new(smix.outputs[0], gmix.inputs[1])
    bump = nt.nodes.new("ShaderNodeBump")
    bump.location = (60, -700)
    sock(bump, "Strength", 0.35)
    sock(bump, "Distance", 0.004)
    nt.links.new(gmix.outputs[0], bump.inputs["Height"])
    nt.links.new(bump.outputs["Normal"], b.inputs["Normal"])

    sock(b, "Metallic", 0.0)
    sock(b, "IOR", 1.47)
    sock(b, "Specular IOR Level", 0.62)
    try:
        m.use_backface_culling = False
    except Exception:
        pass
    return m


def mat_dust(density=0.5, sand=(0.430, 0.305, 0.185, 1.0)):
    """Alpha-cloud material for dust cards / walls (procedural, no textures)."""
    name = "SG_Dust_%d" % int(density * 100)
    m = bpy.data.materials.get(name)
    if m:
        return m
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    for n in list(nt.nodes):
        if n.type != "OUTPUT_MATERIAL":
            nt.nodes.remove(n)
    out = [n for n in nt.nodes if n.type == "OUTPUT_MATERIAL"][0]
    out.location = (700, 0)

    tc = nt.nodes.new("ShaderNodeTexCoord")
    tc.location = (-1000, 0)
    # NOTE: Object/Generated/UV coords are normalised to the card, so the noise
    # must be high-frequency *relative to the card* or every card renders as one
    # flat rectangle. We also multiply by a radial falloff so each card is a
    # soft round puff rather than a hard-edged quad.
    radial = nt.nodes.new("ShaderNodeVectorMath")
    radial.location = (-820, 320)
    radial.operation = "LENGTH"
    nt.links.new(tc.outputs["Object"], radial.inputs[0])
    rmap = nt.nodes.new("ShaderNodeMapRange")
    rmap.location = (-620, 320)
    rmap.clamp = True
    sock(rmap, "From Min", 0.22)
    sock(rmap, "From Max", 0.50)
    sock(rmap, "To Min", 1.0)
    sock(rmap, "To Max", 0.0)
    nt.links.new(radial.outputs["Value"], rmap.inputs["Value"])

    nz = nt.nodes.new("ShaderNodeTexNoise")
    nz.location = (-820, 60)
    sock(nz, "Scale", 3.4)
    sock(nz, "Detail", 8.0)
    sock(nz, "Roughness", 0.62)
    sock(nz, "Distortion", 1.2)
    nt.links.new(tc.outputs["Object"], nz.inputs["Vector"])

    nz2 = nt.nodes.new("ShaderNodeTexNoise")
    nz2.location = (-820, -240)
    sock(nz2, "Scale", 9.0)
    sock(nz2, "Detail", 5.0)
    nt.links.new(tc.outputs["Object"], nz2.inputs["Vector"])

    mul = nt.nodes.new("ShaderNodeMath")
    mul.location = (-620, -60)
    mul.operation = "MULTIPLY_ADD"
    mul.inputs[1].default_value = 0.45
    nt.links.new(nz2.outputs["Fac"], mul.inputs[0])
    nt.links.new(nz.outputs["Fac"], mul.inputs[2])

    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.location = (-400, -60)
    ramp.color_ramp.interpolation = "EASE"
    ramp.color_ramp.elements[0].position = max(0.02, 0.55 - 0.30 * density)
    ramp.color_ramp.elements[0].color = (0, 0, 0, 1)
    ramp.color_ramp.elements[1].position = min(0.98, 0.66 + 0.24 * density)
    ramp.color_ramp.elements[1].color = (1, 1, 1, 1)
    nt.links.new(mul.outputs[0], ramp.inputs["Fac"])

    mask = nt.nodes.new("ShaderNodeMath")
    mask.location = (-180, 60)
    mask.operation = "MULTIPLY"
    mask.use_clamp = True
    nt.links.new(ramp.outputs["Color"], mask.inputs[0])
    nt.links.new(rmap.outputs["Result"], mask.inputs[1])

    trans = nt.nodes.new("ShaderNodeBsdfTransparent")
    trans.location = (200, -320)
    p = nt.nodes.new("ShaderNodeBsdfPrincipled")
    p.location = (200, 60)
    sock(p, "Base Color", sand)
    sock(p, "Roughness", 1.0)
    sock(p, "Metallic", 0.0)
    sock(p, "Specular IOR Level", 0.1)
    sock(p, "Emission Color", sand)
    sock(p, "Emission Strength", 0.06)

    mix = nt.nodes.new("ShaderNodeMixShader")
    mix.location = (460, 0)
    nt.links.new(mask.outputs[0], mix.inputs[0])
    nt.links.new(trans.outputs[0], mix.inputs[1])
    nt.links.new(p.outputs[0], mix.inputs[2])
    nt.links.new(mix.outputs[0], out.inputs[0])
    try:
        m.blend_method = "BLEND"
    except Exception:
        pass
    return m


# --------------------------------------------------------------------------
# geometry helpers
# --------------------------------------------------------------------------
def grid_mesh(name, size, sub, height_fn, uv_scale=1.0):
    verts = []
    for j in range(sub + 1):
        for i in range(sub + 1):
            x = (i / sub - 0.5) * size
            y = (j / sub - 0.5) * size
            verts.append((x, y, height_fn(x, y)))
    faces = []
    for j in range(sub):
        for i in range(sub):
            a = j * (sub + 1) + i
            b = a + 1
            c = a + sub + 1
            d = c + 1
            faces.append((a, b, d, c))
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, [], faces)
    me.update()
    for poly in me.polygons:
        poly.use_smooth = True
    return me


def dune_height(x, y):
    r = math.hypot(x, y)
    p = Vector((x * 0.0042, y * 0.0042, 0.0))
    amp, f, tot, norm = 1.0, 1.0, 0.0, 0.0
    for _ in range(4):
        tot += amp * noise.noise(p * f)
        norm += amp
        amp *= 0.5
        f *= 2.11
    base = tot / norm
    h = base * 11.0
    # ridged dune crests
    p2 = Vector((x * 0.0075, y * 0.0075, 0.0))
    ridge = noise.noise(p2)
    h += 5.0 * (1.0 - abs(ridge * 2.0 - 1.0)) * 0.5
    # fine wind ripples
    h += 0.16 * noise.fractal(Vector((x * 0.45, y * 0.45, 3.0)), 0.9, 2.0, 3)
    # flatten the pad under / around the array
    s = smoothstep(30.0, 86.0, r)
    h *= s
    # terrain rises toward the horizon for a real desert horizon line
    h += 0.012 * max(0.0, r - 60.0)
    return h


def build_ground():
    me = grid_mesh("SG_Ground", CFG["ground_size"], CFG["ground_sub"], dune_height)
    o = new_obj("SG_Ground", me)
    o.data.materials.append(mat_sand())
    # ensure object coords are sane
    bpy.context.view_layer.objects.active = o
    return o


def build_rocks():
    objs = []
    rng = random.Random(CFG["seed"] + 7)
    mat = mat_rock()
    mesh = bpy.data.meshes.new("SG_RockMesh")
    import bmesh
    bm = bmesh.new()
    bmesh.ops.create_icosphere(bm, subdivisions=1, radius=1.0)
    for v in bm.verts:
        v.co.x *= 0.9 + 0.5 * noise.noise(v.co * 3.0)
        v.co.y *= 0.75 + 0.5 * noise.noise(v.co * 3.0 + Vector((5, 0, 0)))
        v.co.z *= 0.5 + 0.35 * noise.noise(v.co * 3.0 + Vector((0, 5, 0)))
    bm.to_mesh(mesh)
    bm.free()
    mesh.materials.append(mat)
    for i in range(CFG["rocks"]):
        a = rng.uniform(0, math.tau)
        r = rng.uniform(46, 190)
        x, y = math.cos(a) * r, math.sin(a) * r
        o = new_obj("SG_Rock_%02d" % i, mesh)
        s = rng.uniform(0.5, 3.4)
        o.scale = (s * rng.uniform(0.7, 1.5), s * rng.uniform(0.7, 1.4), s)
        o.location = (x, y, dune_height(x, y) - 0.25 * s)
        o.rotation_euler = (rng.uniform(-0.2, 0.2), rng.uniform(-0.2, 0.2),
                            rng.uniform(0, math.tau))
        objs.append(o)
    return objs


# --------------------------------------------------------------------------
# PV module + array
# --------------------------------------------------------------------------
def build_module_mesh():
    """2m x 1m module, local frame: X = width, Z = height, face normal = +Y."""
    import bmesh
    w, h, t = CFG["module_w"], CFG["module_h"], CFG["module_t"]
    me = bpy.data.meshes.new("SG_ModuleMesh")
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    for v in bm.verts:
        v.co.x *= w
        v.co.y *= t
        v.co.z *= h
    bm.faces.ensure_lookup_table()
    # bevel the frame
    bmesh.ops.bevel(bm, geom=list(bm.verts) + list(bm.edges) + list(bm.faces),
                    offset=0.018, segments=2, profile=0.6, affect="EDGES",
                    clamp_overlap=True)
    bm.to_mesh(me)
    bm.free()
    me.update()
    mat_pv()
    mat_aluminium()
    me.materials.append(mat_aluminium())  # slot 0 frame
    me.materials.append(bpy.data.materials["SG_PV"])  # slot 1 glass
    # front face (+Y normal) = glass, plus a thin back sheet
    for poly in me.polygons:
        n = poly.normal
        if n.y > 0.55:
            poly.material_index = 1
        elif n.y < -0.55:
            poly.material_index = 1
    return me


def build_array():
    """Rows of tracker-mounted modules + torque tubes + posts."""
    me = build_module_mesh()
    steel = mat_steel("SG_Steel_Dark", rough=0.38,
                      base=(0.045, 0.048, 0.052, 1.0), metallic=0.88)
    modules = []
    rng = random.Random(CFG["seed"])
    n_rows, per = CFG["rows"], CFG["per_row"]
    y0 = -(n_rows - 1) * CFG["row_pitch"] * 0.5
    x0 = -(per - 1) * (CFG["module_w"] + 0.06) * 0.5

    for r in range(n_rows):
        ry = y0 + r * CFG["row_pitch"]
        tilt = (CFG["tilt_deg"] + rng.uniform(-0.6, 0.6)) * DEG
        for c in range(per):
            o = new_obj("SG_PV_%d_%02d" % (r, c), me)
            o.location = (x0 + c * (CFG["module_w"] + 0.06),
                          ry + 0.02 * math.sin(c * 1.3),
                          CFG["tube_z"] + 0.22)
            o.rotation_euler = (tilt + (0.006 * ((c * 7 + r * 13) % 3 - 1)),
                                0.0, 0.0)
            modules.append(o)

        # torque tube
        tube_me = bpy.data.meshes.new("tube_%d" % r)
        import bmesh
        bm = bmesh.new()
        bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False, segments=16,
                              radius1=0.075, radius2=0.075,
                              depth=ARRAY_W * 1.04)
        bm.to_mesh(tube_me)
        bm.free()
        tube = new_obj("SG_Tube_%d" % r, tube_me)
        tube.data.materials.append(steel)
        tube.rotation_euler = (0.0, 90 * DEG, 0.0)
        tube.location = (0.0, ry, CFG["tube_z"])

        # support posts
        posts = max(2, int(ARRAY_W / 8.0) + 1)
        for k in range(posts):
            px = -ARRAY_W * 0.5 + k * (ARRAY_W / (posts - 1))
            pm = bpy.data.meshes.new("post_%d_%d" % (r, k))
            bm = bmesh.new()
            bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False, segments=12,
                                  radius1=0.085, radius2=0.07,
                                  depth=CFG["tube_z"] + 0.3)
            bm.to_mesh(pm)
            bm.free()
            p = new_obj("SG_Post_%d_%d" % (r, k), pm)
            p.data.materials.append(steel)
            p.location = (px, ry, (CFG["tube_z"] + 0.3) * 0.5 - 0.3)
            p.rotation_euler = (0.06 * math.sin(k), -0.05 * math.cos(k * 1.7), 0)
    return modules


# --------------------------------------------------------------------------
# dust wall
# --------------------------------------------------------------------------
def build_dust_wall():
    """Rolling sandstorm: animated instanced cards + layered volume planes."""
    cards = []
    card_me = bpy.data.meshes.new("SG_CardMesh")
    card_me.from_pydata([(-0.5, 0, -0.5), (0.5, 0, -0.5),
                         (0.5, 0, 0.5), (-0.5, 0, 0.5)], [], [(0, 1, 2, 3)])
    card_me.update()
    card_me.materials.append(mat_dust(0.62))
    for p in card_me.polygons:
        p.use_smooth = False

    rng = random.Random(CFG["seed"] + 99)
    n = CFG["dust_cards"]
    for i in range(n):
        o = new_obj("SG_DustCard_%03d" % i, card_me)
        # local offset inside the wall volume (X wide, Z tall, Y thickness)
        u = rng.uniform(-1.0, 1.0)
        dx = math.copysign(abs(u) ** 1.5, u) * 92.0
        dz = (rng.random() ** 1.2) * 30.0
        dy = rng.uniform(-1.0, 1.0) * 16.0
        s = rng.uniform(2.6, 9.5)
        sg_set(o, dx, dy, dz)
        o.scale = (s, s, s * rng.uniform(0.7, 1.0))
        o.rotation_euler = (rng.uniform(-0.35, 0.35), rng.uniform(-0.35, 0.35),
                            rng.uniform(0, math.tau))
        o["sg_spin"] = float(rng.uniform(-0.010, 0.010))
        o.location = (dx, 400.0 + dy, dz)
        cards.append(o)

    # layered "volumetric-ish" planes
    layers = []
    plane_me = bpy.data.meshes.new("SG_WallMesh")
    plane_me.from_pydata([(-0.5, 0, 0), (0.5, 0, 0), (0.5, 0, 1), (-0.5, 0, 1)],
                         [], [(0, 1, 2, 3)])
    plane_me.update()
    plane_me.materials.append(mat_dust(0.35))
    for i, (yy, hh, ww, dd) in enumerate([
            (0.0, 30.0, 132.0, 0.34),
            (26.0, 26.0, 120.0, 0.44),
            (52.0, 22.0, 108.0, 0.34),
            (78.0, 18.0, 94.0, 0.26)]):
        o = new_obj("SG_Wall_%d" % i, plane_me)
        o.scale = (ww, 1.0, hh)
        o.location = (0.0, 400.0 + yy, hh * 0.5 - 1.0)
        sg_set(o, 0.0, yy, hh * 0.5 - 1.0)
        o["sg_density"] = float(dd)
        layers.append(o)
    return cards, layers


def animate_dust_wall(cards, layers, mode, nframes):
    """
    mode: 'off'      -> parked far behind camera (turntable)
          'approach' -> rolls in from +Y and engulfs the array (dustwave)
          'clean'    -> wall far away, only light drifting haze (clean)
    """
    rng = random.Random(CFG["seed"] + 555)

    for o in cards + layers:
        o.animation_data_clear()
        o.rotation_euler = o.rotation_euler  # keep

    def key(obj, frame, loc):
        obj.location = loc
        obj.keyframe_insert("location", frame=frame)

    if mode == "off":
        for i, o in enumerate(cards):
            dx, dy, dz = sg_get(o)
            key(o, 1, (dx, 430.0 + dy, dz))
            key(o, nframes, (dx + 6.0, 470.0 + dy, dz))
        for i, o in enumerate(layers):
            _, yy, zz = sg_get(o)
            key(o, 1, (0.0, 420.0 + yy, zz))
            key(o, nframes, (0.0, 450.0 + yy, zz))

    elif mode == "approach":
        # front of the wall reaches the array around frame 72/96 and swallows it
        for i, o in enumerate(cards):
            dx, dy, dz = sg_get(o)
            s = 1.0 + 0.18 * rng.random()
            start = 190.0 + dy
            end = -18.0 + dy * 0.85 - 5.0 * rng.random()
            wob = rng.uniform(1.5, 5.0)
            spin = o["sg_spin"]
            prev_rx = o.rotation_euler.x
            for k in range(5):
                t = k / 4.0
                f = 1 + t * (nframes - 1)
                y = start + (end - start) * (t ** 0.92) * s
                x = dx * (1.0 + 0.25 * t) + wob * math.sin(t * 6.0 + i)
                z = dz + 1.2 * math.sin(t * 3.4 + i * 0.7)
                key(o, f, (x, y, z))
            o.rotation_euler = (prev_rx, 0.0, o.rotation_euler.z)
            try:
                o.animation_data.action.fcurves.find(
                    "rotation_euler", index=2).keyframe_points.insert(1, o.rotation_euler.z)
                o.animation_data.action.fcurves.find(
                    "rotation_euler", index=2).keyframe_points.insert(
                        nframes, o.rotation_euler.z + spin * nframes)
            except Exception:
                pass
        for i, o in enumerate(layers):
            _, yy, zz = sg_get(o)
            start = 200.0 + yy
            end = 30.0 + yy * 0.9
            for k in range(5):
                t = k / 4.0
                f = 1 + t * (nframes - 1)
                key(o, f, (0.0, start + (end - start) * (t ** 0.92), zz))

    else:  # clean
        for i, o in enumerate(cards):
            dx, dy, dz = sg_get(o)
            key(o, 1, (dx * 1.1, 300.0 + dy, dz))
            key(o, nframes, (dx * 1.1, 360.0 + dy, dz))
        for i, o in enumerate(layers):
            _, yy, zz = sg_get(o)
            key(o, 1, (0.0, 300.0 + yy, zz))
            key(o, nframes, (0.0, 345.0 + yy, zz))

    for o in cards + layers:
        ad = o.animation_data
        if not ad or not ad.action:
            continue
        for fc in ad.action.fcurves:
            for kp in fc.keyframe_points:
                kp.interpolation = "LINEAR"
            for kp in fc.keyframe_points:
                kp.easing = "EASE_IN_OUT"


# --------------------------------------------------------------------------
# world / lights / camera
# --------------------------------------------------------------------------
def build_world():
    w = bpy.data.worlds.get("SG_World") or bpy.data.worlds.new("SG_World")
    bpy.context.scene.world = w
    w.use_nodes = True
    nt = w.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    out = nt.nodes.new("ShaderNodeOutputWorld")
    out.location = (500, 0)
    bg = nt.nodes.new("ShaderNodeBackground")
    bg.location = (260, 0)
    sock(bg, "Strength", 0.55)

    sky = nt.nodes.new("ShaderNodeTexSky")
    sky.location = (-100, 0)
    ok = False
    for t in ("NISHITA", "MULTIPLE_SCATTERING"):
        try:
            sky.sky_type = t
            ok = True
            break
        except Exception:
            continue
    sock(sky, "Sun Elevation", SUN_EL * DEG)
    sock(sky, "Sun Rotation", SUN_AZ * DEG)
    sock(sky, "Sun Intensity", 1.0)
    sock(sky, "Altitude", 120.0)
    sock(sky, "Air", 1.1)
    sock(sky, "Dust", 2.2)
    sock(sky, "Ozone", 1.4)
    try:
        sky.sun_disc = True
        sky.sun_size = 0.6 * DEG
    except Exception:
        pass
    if not ok:
        grad = nt.nodes.new("ShaderNodeTexGradient")
        grad.gradient_type = "EASING"
        nt.links.new(grad.outputs[0], bg.inputs["Color"])
    else:
        nt.links.new(sky.outputs[0], bg.inputs["Color"])
    nt.links.new(bg.outputs[0], out.inputs[0])
    return sky


def build_lights():
    lights = []
    az, el = SUN_AZ * DEG, SUN_EL * DEG
    d = Vector((math.sin(az) * math.cos(el),
                -math.cos(az) * math.cos(el),
                math.sin(el)))
    sun = bpy.data.lights.new("SG_Sun", type="SUN")
    sun.energy = 6.0
    sun.color = (1.0, 0.905, 0.775)
    sun.angle = 0.75 * DEG
    try:
        sun.cycles.cast_shadow = True
    except Exception:
        pass
    o = new_obj("SG_Sun", sun)
    o.location = d * 300.0
    aim(o, ARRAY_CENTER)
    lights.append(o)

    # soft sky fill from the opposite side so shadows read, not crush
    fill = bpy.data.lights.new("SG_Fill", type="SUN")
    fill.energy = 0.9
    fill.color = (0.62, 0.72, 1.0)
    fill.angle = 25.0 * DEG
    fo = new_obj("SG_Fill", fill)
    az2 = az + math.pi * 0.95
    d2 = Vector((math.sin(az2) * math.cos(0.9), -math.cos(az2) * math.cos(0.9),
                 0.55))
    fo.location = d2 * 300.0
    aim(fo, ARRAY_CENTER)
    lights.append(fo)
    return lights


def build_camera():
    cam = bpy.data.cameras.new("SG_Cam")
    cam.lens = 35.0
    cam.sensor_width = 36.0
    cam.dof.use_dof = True
    cam.dof.aperture_fstop = 7.0
    o = new_obj("SG_Cam", cam)

    rig = bpy.data.objects.new("SG_CamRig", None)
    link(rig)
    rig.location = (0, 0, 3.6)
    o.parent = rig
    o.location = (0.0, -66.0, 5.0)

    tgt = bpy.data.objects.new("SG_LookAt", None)
    link(tgt)
    tgt.location = (0.0, 0.0, 3.0)
    c = o.constraints.new("TRACK_TO")
    c.target = tgt
    c.track_axis = "TRACK_NEGATIVE_Z"
    c.up_axis = "UP_Y"
    cam.dof.focus_object = tgt
    bpy.context.scene.camera = o
    return o, rig, tgt


# --------------------------------------------------------------------------
# render / compositor
# --------------------------------------------------------------------------
def setup_compositor():
    scn = bpy.context.scene
    scn.use_nodes = True
    nt = scn.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    rl = nt.nodes.new("CompositorNodeRLayers")
    rl.location = (-600, 0)
    chain = [rl]

    def add(typ, loc, setup=None):
        try:
            n = nt.nodes.new(typ)
            n.location = loc
            if setup:
                setup(n)
            chain.append(n)
        except Exception as e:
            print("[comp] skipped %s: %s" % (typ, e))

    def _glare(n):
        n.glare_type = "FOG_GLOW"
        n.quality = "MEDIUM"
        n.threshold = 1.25
        n.size = 7
        n.mix = -0.62

    def _haze(n):
        # heat-haze / shimmer: a very subtle noise displace over the whole frame
        t = bpy.data.textures.new("SG_Haze", type="CLOUDS")
        t.noise_scale = 0.30
        t.noise_depth = 2
        n.texture = t
        sock(n, "Strength", 0.004)
        sock(n, "X", 0.0)
        sock(n, "Y", 0.0)

    def _lens(n):
        sock(n, "Distort", 0.0)
        sock(n, "Distortion", 0.0)
        sock(n, "Dispersion", 0.006)

    add("CompositorNodeGlare", (-340, 0), _glare)
    add("CompositorNodeDisplace", (-80, 0), _haze)
    add("CompositorNodeLensdist", (180, 0), _lens)

    comp = nt.nodes.new("CompositorNodeComposite")
    comp.location = (440, 0)
    chain.append(comp)
    for a, b in zip(chain[:-1], chain[1:]):
        try:
            nt.links.new(a.outputs[0], b.inputs[0])
        except Exception as e:
            print("[comp] link fail", a.type, "->", b.type, e)


def setup_render(samples=26, resx=1024, resy=576, denoise=True,
                 adaptive=0.06, trans_bounces=24):
    scn = bpy.context.scene
    scn.render.engine = "CYCLES"
    scn.cycles.device = "CPU"
    scn.cycles.samples = samples
    scn.cycles.use_adaptive_sampling = True
    scn.cycles.adaptive_threshold = adaptive
    scn.cycles.use_denoising = denoise
    if denoise:
        for d in ("OPENIMAGEDENOISE", "OPTIX", "NLM"):
            try:
                scn.cycles.denoiser = d
                break
            except Exception:
                continue
        try:
            scn.cycles.denoising_use_gpu = False
        except Exception:
            pass
    scn.cycles.max_bounces = 6
    scn.cycles.diffuse_bounces = 3
    scn.cycles.glossy_bounces = 3
    scn.cycles.transmission_bounces = 3
    scn.cycles.volume_bounces = 1
    scn.cycles.transparent_max_bounces = trans_bounces
    scn.cycles.use_fast_gi = False
    scn.cycles.caustics_reflective = False
    scn.cycles.caustics_refractive = False
    scn.render.use_persistent_data = True
    scn.render.resolution_x = resx
    scn.render.resolution_y = resy
    scn.render.resolution_percentage = 100
    scn.render.image_settings.file_format = "PNG"
    scn.render.image_settings.color_mode = "RGB"
    scn.render.image_settings.compression = 12
    scn.render.film_transparent = False
    try:
        scn.view_settings.view_transform = "AgX"
        scn.view_settings.look = "AgX - Punchy"
    except Exception:
        try:
            scn.view_settings.view_transform = "Filmic"
        except Exception:
            pass
    scn.view_settings.exposure = -0.5
    setup_compositor()
    return scn


# --------------------------------------------------------------------------
# assembly
# --------------------------------------------------------------------------
def build_all(with_dust=True):
    purge()
    scn = bpy.context.scene
    scn.frame_start = 1
    scn.frame_end = 96
    scn.render.fps = 24

    ground = build_ground()
    rocks = build_rocks()
    modules = build_array()
    cards, layers = build_dust_wall() if with_dust else ([], [])
    sky = build_world()
    lights = build_lights()
    cam, rig, tgt = build_camera()

    # pack everything except dust into a collection for tidiness
    H = dict(ground=ground, rocks=rocks, modules=modules, cards=cards,
             layers=layers, sky=sky, lights=lights, cam=cam, rig=rig,
             tgt=tgt, scn=scn)
    return H


# --------------------------------------------------------------------------
# sequence animation
# --------------------------------------------------------------------------
def _anim_clear(obj):
    obj.animation_data_clear()


def _kf_loc(obj, frame, loc):
    obj.location = loc
    obj.keyframe_insert("location", frame=frame)


def _lin(obj):
    ad = obj.animation_data
    if not ad or not ad.action:
        return
    for fc in ad.action.fcurves:
        for kp in fc.keyframe_points:
            kp.interpolation = "LINEAR"


def _pv_nodes():
    nt = bpy.data.materials["SG_PV"].node_tree
    return (nt.nodes["DUST_AMT"].outputs[0],
            nt.nodes["SWEEP"].inputs["From Min"],
            nt.nodes["SWEEP"].inputs["From Max"])


def animate(H, seq, nframes):
    """Keyframe camera rig, dust wall and PV dust nodes for a sequence."""
    cam, rig = H["cam"], H["rig"]
    cards, layers = H["cards"], H["layers"]
    scn = bpy.context.scene
    scn.frame_start = 1
    scn.frame_end = nframes

    _anim_clear(rig)
    _anim_clear(cam)
    dust_o, sw_from, sw_to = _pv_nodes()
    # the storm wall only exists for the dustwave sequence
    for _o in list(cards) + list(layers):
        _o.hide_render = (seq != "dustwave")
    for node_sock in (dust_o, sw_from, sw_to):
        try:
            node_sock.id_data.animation_data_clear() if hasattr(node_sock, "id_data") else None
        except Exception:
            pass

    f0, f1 = 1, nframes

    if seq == "turntable":
        # slow orbit + gentle rise/dolly, hero product shot
        cam.data.lens = 40.0
        cam.data.dof.aperture_fstop = 6.3
        a0, a1 = -58.0 * DEG, 44.0 * DEG
        for k in range(5):
            t = k / 4.0
            f = f0 + t * (f1 - f0)
            rig.rotation_euler = (0.0, 0.0, a0 + (a1 - a0) * t)
            rig.keyframe_insert("rotation_euler", frame=f)
            cam.location = (0.0, -46.0 - 4.0 * t,
                            2.0 + 2.6 * math.sin(t * math.pi))
            cam.keyframe_insert("location", frame=f)
        _dust_static(cards, layers, 470.0)
        dust_o.default_value = 0.14
        dust_o.keyframe_insert("default_value", frame=f0)
        dust_o.default_value = 0.20
        dust_o.keyframe_insert("default_value", frame=f1)
        sw_from.default_value = 300.0
        sw_from.keyframe_insert("default_value", frame=f0)
        sw_to.default_value = 304.0
        sw_to.keyframe_insert("default_value", frame=f0)

    elif seq == "dustwave":
        # fixed low cinematic angle with a slow push-in; wall engulfs the array
        rig.rotation_euler = (0.0, 0.0, -24.0 * DEG)
        cam.data.lens = 38.0
        cam.data.dof.aperture_fstop = 6.3
        rig.keyframe_insert("rotation_euler", frame=f0)
        for k in range(5):
            t = k / 4.0
            f = f0 + t * (f1 - f0)
            cam.location = (2.5 - 3.0 * t, -66.0 + 8.0 * t,
                            2.4 + 1.0 * math.sin(t * math.pi))
            cam.keyframe_insert("location", frame=f)
        animate_dust_wall(cards, layers, "approach", nframes)
        # dust caking ramps up as the wall swallows the array
        keys = [(f0, 0.12), (f0 + 0.42 * nframes, 0.20),
                (f0 + 0.66 * nframes, 0.45),
                (f0 + 0.82 * nframes, 0.78), (f1, 0.95)]
        for f, v in keys:
            dust_o.default_value = v
            dust_o.keyframe_insert("default_value", frame=f)
        sw_from.default_value = 400.0
        sw_from.keyframe_insert("default_value", frame=f0)
        sw_to.default_value = 404.0
        sw_to.keyframe_insert("default_value", frame=f0)

    elif seq == "clean":
        # caked -> clean via a world-X wipe front sweeping across the array
        rig.rotation_euler = (0.0, 0.0, -10.0 * DEG)
        cam.data.lens = 46.0
        cam.data.dof.aperture_fstop = 5.0
        rig.keyframe_insert("rotation_euler", frame=f0)
        for k in range(5):
            t = k / 4.0
            f = f0 + t * (f1 - f0)
            cam.location = (-2.0 + 6.0 * t, -30.0 + 5.0 * t, 3.2 - 0.9 * t)
            cam.keyframe_insert("location", frame=f)
        _dust_static(cards, layers, 330.0)
        dust_o.default_value = 0.95
        dust_o.keyframe_insert("default_value", frame=f0)
        dust_o.default_value = 0.95
        dust_o.keyframe_insert("default_value", frame=int(f1 * 0.75))
        dust_o.default_value = 0.03
        dust_o.keyframe_insert("default_value", frame=f1)
        # wipe front travels from beyond -X to beyond +X with a soft 2.4m edge
        x0, x1 = -ARRAY_W * 0.5 - 4.0, ARRAY_W * 0.5 + 4.0
        n = 5
        for k in range(n + 1):
            t = k / n
            f = f0 + t * (f1 - f0)
            x = x0 + (x1 - x0) * t
            sw_from.default_value = x
            sw_from.keyframe_insert("default_value", frame=f)
            sw_to.default_value = x + 1.8
            sw_to.keyframe_insert("default_value", frame=f)

    for o in [rig, cam] + cards + layers:
        _lin(o)
    # node fcurves -> linear
    nt = bpy.data.materials["SG_PV"].node_tree
    if bpy.data.materials["SG_PV"].node_tree.animation_data:
        for fc in nt.animation_data.action.fcurves:
            for kp in fc.keyframe_points:
                kp.interpolation = "LINEAR"
    return H


def _dust_static(cards, layers, base_y):
    for o in cards + layers:
        o.animation_data_clear()
        dx, dy, dz = sg_get(o)
        o.location = (dx, base_y + dy, dz)


def setup_still(H, which):
    """Place the camera rig/cam for one of the 3 hero stills."""
    cam, rig, tgt = H["cam"], H["rig"], H["tgt"]
    _anim_clear(rig)
    _anim_clear(cam)
    cards, layers = H["cards"], H["layers"]
    dust_o, sw_from, sw_to = _pv_nodes()
    for _o in list(cards) + list(layers):
        _o.hide_render = (which == "dash")   # only the moody aerial keeps haze

    if which == "hero":
        rig.rotation_euler = (0, 0, -30 * DEG)
        cam.location = (0.0, -52.0, 3.0)
        cam.data.lens = 36.0
        cam.data.dof.aperture_fstop = 7.0
        tgt.location = (0, 0, 3.2)
        _dust_static(cards, layers, 250.0)
        dust_o.default_value = 0.20
        sw_from.default_value = 300.0
        sw_to.default_value = 304.0

    elif which == "dash":
        # high 3/4 aerial, moody, lots of negative space for UI type
        rig.rotation_euler = (0, 0, -14 * DEG)
        cam.location = (0.0, -74.0, 26.0)
        cam.data.lens = 44.0
        cam.data.dof.aperture_fstop = 11.0
        tgt.location = (0, 8.0, 6.0)
        _dust_static(cards, layers, 235.0)
        dust_o.default_value = 0.45
        sw_from.default_value = 300.0
        sw_to.default_value = 304.0

    elif which == "closeup":
        # macro on a module edge, shallow DOF, dust visible on the glass
        rig.rotation_euler = (0, 0, 14 * DEG)
        cam.location = (0.0, -6.0, 2.6)
        cam.data.lens = 74.0
        cam.data.dof.aperture_fstop = 2.0
        tgt.location = (1.0, -4.6, 1.9)
        _dust_static(cards, layers, 250.0)
        dust_o.default_value = 0.62
        sw_from.default_value = 300.0
        sw_to.default_value = 304.0

    for o in cards + layers:
        o.animation_data_clear()
    # node value keyframes must not exist for stills
    nt = bpy.data.materials["SG_PV"].node_tree
    nt.nodes["DUST_AMT"].outputs[0].keyframe_delete("default_value")
    for name, s in (("SWEEP", "From Min"), ("SWEEP", "From Max")):
        nt.nodes[name].inputs[s].keyframe_delete("default_value")
    return cam


# --------------------------------------------------------------------------
# GLB assets for the Three.js layer
# --------------------------------------------------------------------------
def export_glb(outdir):
    """Low-poly, texture-free PBR modules for the browser layer."""
    os.makedirs(outdir, exist_ok=True)

    # ---- solar_panel.glb : module + torque tube + 2 posts + bearing ----
    purge()
    import bmesh

    m_glass = bpy.data.materials.new("PV_Glass")
    m_glass.use_nodes = True
    b = m_glass.node_tree.nodes["Principled BSDF"]
    sock(b, "Base Color", (0.012, 0.022, 0.058, 1.0))
    sock(b, "Metallic", 0.35)
    sock(b, "Roughness", 0.10)
    sock(b, "Coat Weight", 0.6)

    m_cell = bpy.data.materials.new("PV_Cell")
    m_cell.use_nodes = True
    b = m_cell.node_tree.nodes["Principled BSDF"]
    sock(b, "Base Color", (0.020, 0.040, 0.095, 1.0))
    sock(b, "Metallic", 0.25)
    sock(b, "Roughness", 0.16)

    m_alu = bpy.data.materials.new("PV_Aluminium")
    m_alu.use_nodes = True
    b = m_alu.node_tree.nodes["Principled BSDF"]
    sock(b, "Base Color", (0.620, 0.632, 0.645, 1.0))
    sock(b, "Metallic", 0.95)
    sock(b, "Roughness", 0.22)

    m_steel = bpy.data.materials.new("PV_Steel")
    m_steel.use_nodes = True
    b = m_steel.node_tree.nodes["Principled BSDF"]
    sock(b, "Base Color", (0.062, 0.066, 0.072, 1.0))
    sock(b, "Metallic", 0.9)
    sock(b, "Roughness", 0.35)

    parts = []

    def add_mesh(name, build, mat):
        me = bpy.data.meshes.new(name)
        bm = bmesh.new()
        build(bm)
        bm.to_mesh(me)
        bm.free()
        me.materials.append(mat)
        for p in me.polygons:
            p.use_smooth = p.normal.z > 0.9
        o = new_obj(name, me)
        parts.append(o)
        return o

    # glass sheet
    def _glass(bm):
        bmesh.ops.create_cube(bm, size=1.0)
        for v in bm.verts:
            v.co.x *= 1.98
            v.co.y *= 0.028
            v.co.z *= 0.98
    g = add_mesh("glass", _glass, m_glass)

    # cell grid: 12 x 6 cells as thin plates on the glass face (low poly)
    def _cells(bm):
        n_x, n_y = 12, 6
        cw, ch = 1.98 / n_x, 0.98 / n_y
        gap = 0.012
        for i in range(n_x):
            for j in range(n_y):
                cx = -0.99 + cw * (i + 0.5)
                cy = -0.49 + ch * (j + 0.5)
                r = bmesh.ops.create_cube(bm, size=1.0)
                for v in r["verts"]:
                    v.co.x = v.co.x * (cw - gap) + cx
                    v.co.y = v.co.y * 0.004 + 0.0155
                    v.co.z = v.co.z * (ch - gap) + cy
    cells = add_mesh("cells", _cells, m_cell)

    # aluminium frame: 4 bars
    def _frame(bm):
        bars = [((1.98 + 0.09) / 2, 0.0, 0.055, 1.07, 0.05, 0.11),
                (-(1.98 + 0.09) / 2, 0.0, 0.055, 1.07, 0.05, 0.11)]
        for x, y, w, h, d, t in bars:
            r = bmesh.ops.create_cube(bm, size=1.0)
            for v in r["verts"]:
                v.co.x = v.co.x * t + x
                v.co.y = v.co.y * d
                v.co.z = v.co.z * h
        for zz in (0.545, -0.545):
            r = bmesh.ops.create_cube(bm, size=1.0)
            for v in r["verts"]:
                v.co.x = v.co.x * 2.07
                v.co.y = v.co.y * 0.05
                v.co.z = v.co.z * 0.075 + zz
    fr = add_mesh("frame", _frame, m_alu)
    fr.location = (0, 0, 0)

    # torque tube
    def _tube(bm):
        bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False, segments=12,
                              radius1=0.055, radius2=0.055, depth=4.6)
    t = add_mesh("torque_tube", _tube, m_steel)
    t.rotation_euler = (0.0, math.pi / 2, 0.0)

    # posts + bearings
    for px in (-1.9, 1.9):
        def _post(bm, px=px):
            bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False, segments=10,
                                  radius1=0.05, radius2=0.042, depth=1.6)
            for v in bm.verts:
                v.co.z += 0.8
                v.co.x += px
        add_mesh("post_%.1f" % px, _post, m_steel)

    def _bearing(bm):
        bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False, segments=10,
                              radius1=0.075, radius2=0.075, depth=0.08)
        for v in bm.verts:
            v.co.y += 0.0
    for px in (-1.9, 1.9):
        def _b(bm, px=px):
            bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False, segments=10,
                                  radius1=0.082, radius2=0.082, depth=0.09)
            for v in bm.verts:
                v.co.rotate(Euler((math.pi / 2, 0, 0)))
                v.co.x += px
                v.co.z += 1.6
        add_mesh("bearing_%.1f" % px, _b, m_steel)

    # tilt + raise the whole assembly
    root = bpy.data.objects.new("SolarPanel_Root", None)
    link(root)
    for p in parts:
        p.parent = root
        p.matrix_parent_inverse = root.matrix_world.inverted()
    root.rotation_euler = (CFG["tilt_deg"] * DEG, 0, 0)
    root.location = (0, 0, 1.62)

    bpy.ops.object.select_all(action="DESELECT")
    for o in parts + [root]:
        o.select_set(True)
    bpy.context.view_layer.objects.active = root
    bpy.ops.export_scene.gltf(
        filepath=os.path.join(outdir, "solar_panel.glb"),
        export_format="GLB",
        use_selection=True,
        export_apply=True,
        export_materials="EXPORT",
        export_yup=True,
        export_cameras=False,
        export_lights=False,
    )

    # ---- solarguard_globe.glb : low-poly globe + atmosphere + ring ----
    purge()
    m_earth = bpy.data.materials.new("Globe_Surface")
    m_earth.use_nodes = True
    b = m_earth.node_tree.nodes["Principled BSDF"]
    sock(b, "Base Color", (0.035, 0.075, 0.145, 1.0))
    sock(b, "Roughness", 0.55)
    sock(b, "Metallic", 0.1)

    m_atmo = bpy.data.materials.new("Globe_Atmosphere")
    m_atmo.use_nodes = True
    b = m_atmo.node_tree.nodes["Principled BSDF"]
    sock(b, "Base Color", (0.12, 0.55, 0.95, 1.0))
    sock(b, "Emission Color", (0.20, 0.62, 1.0, 1.0))
    sock(b, "Emission Strength", 0.9)
    sock(b, "Alpha", 0.16)
    try:
        m_atmo.blend_method = "BLEND"
    except Exception:
        pass

    m_grid = bpy.data.materials.new("Globe_Grid")
    m_grid.use_nodes = True
    b = m_grid.node_tree.nodes["Principled BSDF"]
    sock(b, "Base Color", (0.05, 0.85, 0.70, 1.0))
    sock(b, "Emission Color", (0.05, 0.95, 0.78, 1.0))
    sock(b, "Emission Strength", 1.6)

    objs = []
    me = bpy.data.meshes.new("Globe")
    bm = bmesh.new()
    bmesh.ops.create_icosphere(bm, subdivisions=3, radius=1.0)
    bm.to_mesh(me)
    bm.free()
    me.materials.append(m_earth)
    o = new_obj("SolarGuard_Globe", me)
    objs.append(o)

    me = bpy.data.meshes.new("Atmo")
    bm = bmesh.new()
    bmesh.ops.create_icosphere(bm, subdivisions=2, radius=1.035)
    bm.to_mesh(me)
    bm.free()
    me.materials.append(m_atmo)
    objs.append(new_obj("SG_Atmosphere", me))

    # marker: a small emissive hexagon at Saudi Arabia (~25N, 45E)
    lat, lon = 24.7 * DEG, 45.2 * DEG
    pos = Vector((math.cos(lat) * math.cos(lon), math.sin(lat),
                  math.cos(lat) * math.sin(lon))) * 1.012
    me = bpy.data.meshes.new("Marker")
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False, segments=6,
                          radius1=0.045, radius2=0.045, depth=0.02)
    for v in bm.verts:
        v.co.rotate(Euler((math.pi / 2, 0, 0)))
    bm.to_mesh(me)
    bm.free()
    me.materials.append(m_grid)
    mk = new_obj("SG_Marker_SaudiArabia", me)
    mk.location = pos
    aim(mk, Vector((0, 0, 0)))
    objs.append(mk)

    # grid rings (2 thin torus-ish rings) for the "intelligence" look
    for r, axis in ((1.28, (1, 0, 0)), (1.34, (0.35, 1, 0.15))):
        bm = bmesh.new()
        seg = 48
        verts = []
        for i in range(seg):
            a = i / seg * math.tau
            verts.append(Vector((math.cos(a) * r, math.sin(a) * r, 0.0)))
        for i in range(seg):
            v1, v2 = verts[i], verts[(i + 1) % seg]
            w = 0.008
            quad = [v1 + Vector((-w, -w, 0)), v2 + Vector((w, -w, 0)),
                    v2 + Vector((w, w, 0)), v1 + Vector((-w, w, 0))]
            vs = [bm.verts.new(p) for p in quad]
            bm.faces.new(vs)
        bm.to_mesh(bpy.data.meshes.new("tmp"))
        bm.free()

    bpy.ops.object.select_all(action="DESELECT")
    for o in objs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = objs[0]
    bpy.ops.export_scene.gltf(
        filepath=os.path.join(outdir, "solarguard_globe.glb"),
        export_format="GLB",
        use_selection=True,
        export_apply=True,
        export_materials="EXPORT",
        export_yup=True,
        export_cameras=False,
        export_lights=False,
    )
    return outdir


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------
def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    out_models = os.path.join(PROJ, "public", "assets", "models")

    if "--export-glb" in argv:
        export_glb(out_models)
        print("[build_scene] GLB export done ->", out_models)
        return

    if "--save-blend" in argv:
        path = argv[argv.index("--save-blend") + 1]
        build_all()
        bpy.ops.wm.save_as_mainfile(filepath=path)
        print("[build_scene] saved", path)
        return

    build_all()
    print("[build_scene] scene built (no action requested)")


if __name__ == "__main__":
    main()
