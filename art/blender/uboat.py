"""The player's U-boat, Type VII style. Low poly, flat shaded, no outline shells.

Blender basics used here (caveman notes):
  * 1 unit = 1 map tile. Blender +Z is up, bow points +X. glTF/Bevy turns Z-up into Y-up.
  * loft   = a skin stretched over a row of cross-section rings (hull, tanks, deck).
  * prism  = a 2D outline pulled straight up (tower, platform, planes).
  * node   = one animatable thing. Parts are glued into named groups; each group becomes one glTF
             node. Its ORIGIN (pivot) sits on the axis it turns about, so rotating the node in
             Bevy looks right. A child node follows its parent (barrel follows gun).
  * flat shading + a few named materials = the low-poly look, and Bevy can recolour by name.

Nodes (Bevy axes in brackets; Blender Y is Bevy Z):
  Hull                  static body
  Gun                   deck gun mount, yaw about Y (traverse)
    GunBarrel           cradle + trunnion, pitch about Z (elevate)
      GunRecoil         the barrel tube, slides back along -X when firing
  Periscope             tube, raise along +Y, spin about Y
  Flag                  pole, sways about Y
    FlagCloth1..3       chained cloth strips, each yaws a bit -> a waving flag
  Propeller             spins about X
  Rudder                yaws about Y (steering)
  BowPlanes/SternPlanes dive planes, pitch about Z
Old names Gun / Periscope / Flag and their pivots are kept so the game rig keeps working.
Waterline z = 0, length ~1.8 (x -0.94..0.86), beam 0.42. `uboat_gold.glb` swaps hull paint for gold.
"""

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bmesh  # noqa: E402
from mathutils import Matrix, Vector  # noqa: E402
from ship_common import DARK, GOLD, RED, WHITE, Model, shade  # noqa: E402

HULL = (0.25, 0.33, 0.44)
TOWER = (0.78, 0.82, 0.86)
DECK = (0.72, 0.56, 0.38)


def rounded(x, w, h, cz, n=12, p=2.6):
    """One hull ring: a squarish oval (superellipse) `w` wide and `h` tall, as `(x, [(y, z)...])`.
    The half-step angle gives a flat top and bottom, so the deck sits on a flat."""
    pts = []
    for i in range(n):
        a = math.tau * (i + 0.5) / n
        c, s = math.cos(a), math.sin(a)
        pts.append((w * math.copysign(abs(c) ** (2 / p), c), cz + h * math.copysign(abs(s) ** (2 / p), s)))
    return x, pts


def teardrop(cx, front, back, half, n=12):
    """Tower outline (counter-clockwise): pointed-ish at the front, round at the back."""
    pts = []
    for i in range(n):
        t = math.tau * i / n
        c = math.cos(t)
        x = cx + (front if c > 0 else back) * c
        y = half * math.sin(t) * (1 - 0.3 * max(0.0, c))
        pts.append((x, y))
    return pts


def grow(pts, k, dx=0.0):
    return [(x * k + dx, y * k) for x, y in pts]


def deck_half_width(x, table):
    """Deck half-width at `x`, interpolated from the casing table."""
    for (x0, w0, *_), (x1, w1, *_) in zip(table, table[1:]):
        if x0 <= x <= x1:
            return w0 + (w1 - w0) * (x - x0) / (x1 - x0)
    return table[-1][1]


def blade(m, group, pivot, angle, material="Band"):
    """One propeller blade: a flat, twisted slab at radius 0.032 around the X axis."""
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    for v in bm.verts:
        v.co.x *= 0.012
        v.co.y *= 0.03
        v.co.z *= 0.052
    bmesh.ops.rotate(bm, verts=bm.verts, cent=(0, 0, 0), matrix=Matrix.Rotation(0.55, 3, "Z"))
    bmesh.ops.translate(bm, vec=(0, 0, 0.034), verts=bm.verts)
    bmesh.ops.rotate(bm, verts=bm.verts, cent=(0, 0, 0), matrix=Matrix.Rotation(angle, 3, "X"))
    bmesh.ops.translate(bm, vec=Vector(pivot), verts=bm.verts)
    return m._object(bm, material, group, False)


def build(clean=True):
    m = Model("uboat", outline=0, clean=clean)  # outline=0: no black "Ink" shells
    m.mat("Paint", HULL)
    m.mat("PaintDark", shade(HULL, 0.7))
    m.mat("Tower", TOWER)
    m.mat("Deck", DECK)
    m.mat("Dark", DARK)
    m.mat("Band", GOLD, rough=0.4, emit=0.2)
    m.mat("Boot", RED)
    m.mat("White", WHITE)
    m.mat("Flag", (0.95, 0.2, 0.18))

    # ---- Pressure hull: long, low, bow rising to a stem. Lower half is darker (waterline split).
    stations = [
        (-0.88, 0.012, 0.012, 0.04),
        (-0.76, 0.05, 0.05, 0.03),
        (-0.56, 0.10, 0.08, 0.01),
        (-0.30, 0.125, 0.105, 0.0),
        (0.10, 0.13, 0.105, 0.0),
        (0.40, 0.11, 0.10, 0.02),
        (0.62, 0.065, 0.09, 0.05),
        (0.76, 0.03, 0.07, 0.09),
        (0.86, 0.008, 0.03, 0.15),
    ]
    hull = m.loft([rounded(*s) for s in stations], "Paint", group="Hull", outline=False)
    hull.data.materials.append(m.materials["PaintDark"])
    for poly in hull.data.polygons:
        if poly.center.z < 0.0 and abs(poly.center.x) < 0.8:
            poly.material_index = 1

    # ---- Saddle tanks: slim bulges along each side at the waterline.
    tank = [(-0.50, 0.02, 0.02), (-0.36, 0.05, 0.05), (0.0, 0.065, 0.065), (0.30, 0.05, 0.05), (0.50, 0.02, 0.02)]
    for side in (1, -1):
        rings = []
        for x, w, h in tank:
            _, pts = rounded(x, w, h, -0.03, n=8, p=2.2)
            rings.append((x, [(side * 0.105 + y, z) for y, z in pts]))
        m.loft(rings, "PaintDark", group="Hull", outline=False)

    # ---- Wooden deck casing, rising at the bow. (x, half width, top z, bottom z)
    casing = [
        (-0.68, 0.04, 0.145, 0.09),
        (-0.50, 0.075, 0.155, 0.09),
        (-0.30, 0.088, 0.16, 0.09),
        (0.20, 0.088, 0.16, 0.09),
        (0.50, 0.062, 0.17, 0.09),
        (0.70, 0.03, 0.19, 0.11),
        (0.84, 0.008, 0.215, 0.15),
    ]
    m.loft([(x, [(-w, lo), (w, lo), (w, hi), (-w, hi)]) for x, w, hi, lo in casing], "Deck", group="Hull",
           outline=False)
    # Side rail (posts + rail strips) that follows the deck edge.
    xs = [-0.58 + i * 0.13 for i in range(11)]
    for side in (1, -1):
        prev = None
        for x in xs:
            y = side * (deck_half_width(x, casing) - 0.008)
            m.cyl((x, y, 0.185), 0.004, 0.04, "Dark", group="Hull", outline=False, segments=4)
            if prev is not None:
                px, py = prev
                m.box(((x + px) / 2, (y + py) / 2, 0.204), (abs(x - px), 0.004, 0.004), "Dark", group="Hull",
                      outline=False, rot=(0, 0, math.atan2(y - py, x - px)))
            prev = (x, y)

    # ---- Conning tower: teardrop body (narrower than the deck, so nothing overhangs), gold band,
    # rim and a dark bridge hatch on top.
    body = teardrop(-0.08, 0.2, 0.2, 0.062)
    m.prism(body, 0.10, 0.34, "Tower", group="Hull", outline=False)
    m.prism(grow(body, 1.04), 0.235, 0.285, "Band", group="Hull", outline=False)
    m.prism(grow(body, 1.07, -0.006), 0.34, 0.395, "Tower", group="Hull", outline=False)
    m.prism(grow(body, 0.78, -0.02), 0.395, 0.402, "Dark", group="Hull", outline=False)
    # Emblem: white roundel with a red dot on each side, sitting on the flat of the wall.
    for side in (1, -1):
        m.cyl((-0.08, side * 0.061, 0.19), 0.028, 0.008, "White", group="Hull", outline=False, segments=10,
              axis="Y")
        m.cyl((-0.08, side * 0.065, 0.19), 0.014, 0.008, "Flag", group="Hull", outline=False, segments=8,
              axis="Y")

    # ---- Stern shaft: hull tip to propeller hub, so the propeller sits clearly behind the hull.
    m.cyl((-0.895, 0, 0.04), 0.006, 0.05, "Dark", group="Hull", outline=False, segments=6, axis="X")

    # ---- Deck gun (88 mm): Gun (yaw) -> GunBarrel (pitch) -> GunRecoil (slide back).
    # Chunky like the real thing: base plate, pedestal, curved shield, big breech slab, hand wheels.
    gun = (0.42, 0.0, 0.175)
    gx, gy, gz = gun
    m.pivot("Gun", gun)
    m.box((gx, gy, gz + 0.004), (0.09, 0.09, 0.008), "Dark", group="Gun", outline=False)
    m.cyl((gx, gy, gz + 0.036), 0.03, 0.056, "Dark", group="Gun", outline=False, segments=8, radius_top=0.022)
    arc = [math.radians(a) for a in (-75, -50, -25, 0, 25, 50, 75)]
    shield = [(gx + 0.05 * math.cos(t), 0.05 * math.sin(t)) for t in arc]
    shield += [(gx + 0.042 * math.cos(t), 0.042 * math.sin(t)) for t in reversed(arc)]
    m.prism(shield, gz + 0.008, gz + 0.072, "Tower", group="Gun", outline=False)
    trunnion = (gx, gy, gz + 0.09)
    m.pivot("GunBarrel", trunnion)
    m.parent("GunBarrel", "Gun")
    m.box((gx + 0.005, gy, gz + 0.09), (0.12, 0.075, 0.055), "Tower", group="GunBarrel", outline=False,
          taper=(0.85, 0.9))
    m.box((gx - 0.03, 0.03, gz + 0.13), (0.03, 0.018, 0.02), "Dark", group="GunBarrel", outline=False)
    for side in (1, -1):
        m.cyl((gx - 0.03, side * 0.05, gz + 0.085), 0.02, 0.005, "Dark", group="GunBarrel", outline=False,
              segments=8, axis="Y")
    breech = (gx + 0.06, gy, gz + 0.09)
    m.pivot("GunRecoil", breech)
    m.parent("GunRecoil", "GunBarrel")
    m.cyl((gx + 0.1, gy, gz + 0.09), 0.024, 0.08, "Dark", group="GunRecoil", outline=False, segments=8,
          axis="X")
    m.cyl((gx + 0.18, gy, gz + 0.09), 0.015, 0.24, "Dark", group="GunRecoil", outline=False, segments=6,
          axis="X")
    m.cyl((gx + 0.295, gy, gz + 0.09), 0.021, 0.03, "Dark", group="GunRecoil", outline=False, segments=6,
          axis="X")

    # ---- Periscope: the only one. Base hidden in the tower, head with a forward lens.
    scope = (-0.04, 0.0, 0.4)
    sx, sy, sz = scope
    m.pivot("Periscope", scope)
    m.cyl((sx, sy, sz + 0.07), 0.013, 0.32, "Dark", group="Periscope", outline=False, segments=6)
    m.box((sx + 0.015, sy, sz + 0.22), (0.06, 0.03, 0.035), "Dark", group="Periscope", outline=False)

    # ---- Flag: pole plus three chained cloth strips (red / white / red), trailing aft.
    flag = (-0.25, 0.0, 0.4)
    fx, fy, fz = flag
    m.pivot("Flag", flag)
    m.cyl((fx, fy, fz + 0.15), 0.006, 0.3, "Dark", group="Flag", outline=False, segments=4)
    seg, top = 0.055, fz + 0.25
    for i in range(3):
        name = f"FlagCloth{i + 1}"
        hinge = (fx - i * seg, fy, top)
        m.pivot(name, hinge)
        m.parent(name, "Flag" if i == 0 else f"FlagCloth{i}")
        cx = hinge[0] - seg / 2
        m.box((cx, fy, top + 0.03), (seg + 0.002, 0.006, 0.03), "Flag", group=name, outline=False)
        m.box((cx, fy, top), (seg + 0.002, 0.007, 0.03), "White", group=name, outline=False)
        m.box((cx, fy, top - 0.03), (seg + 0.002, 0.006, 0.03), "Flag", group=name, outline=False)

    # ---- Propeller (behind the hull tip on the shaft), rudder in front of it, dive planes.
    prop = (-0.925, 0.0, 0.04)
    m.pivot("Propeller", prop)
    m.cyl(prop, 0.014, 0.03, "Dark", group="Propeller", outline=False, segments=6, axis="X")
    for k in range(4):
        blade(m, "Propeller", prop, k * math.pi / 2)
    rudder = (-0.80, 0.0, 0.0)
    m.pivot("Rudder", rudder)
    m.box((rudder[0] - 0.03, 0, 0.0), (0.07, 0.012, 0.19), "Dark", group="Rudder", outline=False, taper=(0.7, 1))
    for name, x, span in (("BowPlanes", 0.58, 0.34), ("SternPlanes", -0.66, 0.36)):
        m.pivot(name, (x, 0, 0.02))
        h = span / 2
        shape = [(0.04, -0.05), (0.025, -h), (-0.02, -h), (-0.04, -0.05), (-0.04, 0.05), (-0.02, h),
                 (0.025, h), (0.04, 0.05)]
        m.prism([(px + x, py) for px, py in reversed(shape)], 0.014, 0.026, "Dark", group=name, outline=False)
    return m


if __name__ == "__main__":
    build().export(camera=(0.35, -1.0, 0.75))
