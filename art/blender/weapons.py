"""Torpedo, shell and explosion for the playground. Each is one node, origin in the middle,
pointing along +X. The explosion is a single static burst: Bevy grows it and shrinks it away.
Run: /Applications/Blender.app/Contents/MacOS/Blender --background --python art/blender/weapons.py"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ship_common import DARK, GOLD, YELLOW, Model  # noqa: E402


def torpedo():
    """Long and slim like a real G7: round nose, yellow band, tail fins; node TorpedoProp spins."""
    m = Model("torpedo", outline=0)
    m.mat("Body", (0.34, 0.36, 0.35))
    m.mat("Band", YELLOW, emit=0.2)
    m.mat("Dark", DARK)
    g = "Torpedo"

    def ring(x0, x1, r0, r1, mat="Body"):
        m.cyl(((x0 + x1) / 2, 0, 0), r0, x1 - x0, mat, group=g, outline=False, axis="X", radius_top=r1)

    ring(-0.17, 0.12, 0.022, 0.022)  # body
    ring(0.12, 0.17, 0.022, 0.019)  # nose, in three steps
    ring(0.17, 0.215, 0.019, 0.012)
    ring(0.215, 0.245, 0.012, 0.003)
    ring(0.05, 0.075, 0.0232, 0.0232, "Band")
    ring(-0.23, -0.17, 0.012, 0.022, "Dark")  # tapered tail
    m.box((-0.19, 0, 0), (0.05, 0.09, 0.004), "Dark", group=g, outline=False)
    m.box((-0.19, 0, 0), (0.05, 0.004, 0.09), "Dark", group=g, outline=False)
    ring(-0.245, -0.23, 0.008, 0.008, "Dark")  # hub
    m.pivot("TorpedoProp", (-0.26, 0, 0))  # the two props turn together about X
    m.parent("TorpedoProp", "Torpedo")
    for x, turn in ((-0.255, 0.0), (-0.268, 0.785)):
        m.box((x, 0, 0), (0.006, 0.07, 0.012), "Dark", group="TorpedoProp", outline=False, rot=(turn, 0, 0))
        m.box((x, 0, 0), (0.006, 0.012, 0.07), "Dark", group="TorpedoProp", outline=False, rot=(turn, 0, 0))
    return m


def shell():
    m = Model("shell", outline=0)
    m.mat("Band", GOLD, rough=0.4, emit=0.3)
    m.mat("Dark", DARK)
    m.cyl((0, 0, 0), 0.028, 0.16, "Band", group="Shell", outline=False, axis="X")
    m.cyl((0.1, 0, 0), 0.028, 0.045, "Dark", group="Shell", outline=False, axis="X", radius_top=0.006)
    return m


def explosion():
    m = Model("explosion", outline=0)
    m.mat("Core", (1.0, 0.93, 0.55), emit=1.5)
    m.mat("Flame", (1.0, 0.5, 0.1), emit=1.2)
    m.mat("Smoke", (0.22, 0.2, 0.2))
    g = "Explosion"
    m.ball((0, 0, 0), (0.8, 0.8, 0.8), "Core", group=g, outline=False, subdivisions=2)
    # Odd corners pushed out make the flame ball jagged.
    flame = m.ball((0, 0, 0), (1.0, 1.0, 1.0), "Flame", group=g, outline=False, subdivisions=2)
    for i, v in enumerate(flame.data.vertices):
        if i % 2:
            v.co *= 1.7
    for at in [(0.7, 0.2, 0.3), (-0.6, 0.4, -0.4), (0.1, 0.8, -0.5), (-0.3, -0.3, 0.7), (0.5, -0.4, -0.6),
               (0.0, 0.9, 0.4)]:
        m.ball(at, (0.3, 0.3, 0.3), "Smoke", group=g, outline=False)
    return m


if __name__ == "__main__":
    for build in (torpedo, shell, explosion):
        build().export(gold=False, camera=(0.5, -0.9, 0.5))
