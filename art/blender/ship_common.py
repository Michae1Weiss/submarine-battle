"""Shared helpers for the Flussbunker 3D Blender models (ships, U-boat, bunker).

Run a model script headless:
    /Applications/Blender.app/Contents/MacOS/Blender --background --python art/blender/ship_speedboat.py

Conventions:
- 1 Blender unit = 1 world unit = 1 map tile. Blender +Z up becomes glTF/Bevy +Y up.
- Ships face Blender +X (the bow), which stays +X in Bevy. Blender +Y (port) becomes Bevy -Z.
- Ship origins sit on the waterline at the hull's centre; the bunker's origin is at ground level.
- Flat shaded, no textures, base colour only, sRGB colours converted to linear on the way in.
- Every chunky part gets an inverted-hull outline shell ("Ink" material, flipped normals), so
  the cartoon outline works in Bevy with plain back-face culling.
- `export(name)` writes `assets/models/<name>.glb`, and `<name>_gold.glb` with every "Paint*"
  material swapped for gold, then renders a 3/4 preview to `target/previews/`.
"""

import math
import os

import bmesh
import bpy
from mathutils import Matrix, Vector

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
MODELS = os.path.join(ROOT, "assets", "models")
PREVIEWS = os.path.join(ROOT, "target", "previews")

INK = (0.07, 0.06, 0.10)
WHITE = (0.97, 0.97, 0.94)
DARK = (0.16, 0.16, 0.21)
GLASS = (0.45, 0.88, 1.0)
GOLD = (1.0, 0.78, 0.2)
GOLD_DARK = (0.86, 0.56, 0.12)
RED = (0.92, 0.22, 0.18)
YELLOW = (1.0, 0.80, 0.16)
OUTLINE = 0.03


def srgb_to_linear(c):
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def shade(rgb, f):
    return tuple(min(1.0, v * f) for v in rgb)


def mix(a, b, t):
    return tuple(x + (y - x) * t for x, y in zip(a, b))


def reset():
    bpy.ops.wm.read_factory_settings(use_empty=True)


class Model:
    """Collects parts into named groups (one glTF node each) and exports them."""

    def __init__(self, name, outline=OUTLINE, clean=True):
        # clean=False: build in the live scene (Blender MCP) without wiping it with factory settings.
        if clean:
            reset()
        self.name = name
        self.outline = outline
        self.materials = {}
        # group name -> list of (object, outlined)
        self.groups = {}
        self.pivots = {}
        self.parents = {}
        self.mat("Ink", INK, rough=1.0)

    # ------------------------------------------------------------------ materials

    def mat(self, name, rgb, rough=0.8, metal=0.0, emit=0.0):
        """A named flat material; names starting with "Paint" turn gold in the gold variant."""
        if name in self.materials:
            return self.materials[name]
        m = bpy.data.materials.new(name)
        m.use_nodes = True
        bsdf = m.node_tree.nodes.get("Principled BSDF")
        lin = [srgb_to_linear(c) for c in rgb] + [1.0]
        bsdf.inputs["Base Color"].default_value = lin
        bsdf.inputs["Roughness"].default_value = rough
        bsdf.inputs["Metallic"].default_value = metal
        if emit > 0.0:
            bsdf.inputs["Emission Color"].default_value = lin
            bsdf.inputs["Emission Strength"].default_value = emit
        m.diffuse_color = lin
        # Single-sided: glTF doubleSided=false, so Bevy culls back faces and the inverted
        # outline shells only show at the silhouette.
        m.use_backface_culling = True
        m["srgb"] = list(rgb)
        self.materials[name] = m
        return m

    # ------------------------------------------------------------------ parts

    def _object(self, bm, material, group, outline, name="part"):
        mesh = bpy.data.meshes.new(name)
        bm.to_mesh(mesh)
        bm.free()
        obj = bpy.data.objects.new(name, mesh)
        bpy.context.collection.objects.link(obj)
        obj.data.materials.append(self.materials[material])
        for poly in obj.data.polygons:
            poly.use_smooth = False
        self.groups.setdefault(group, []).append((obj, outline))
        return obj

    @staticmethod
    def _place(bm, at, rot):
        if rot is not None:
            rx, ry, rz = rot
            m = Matrix.Rotation(rz, 4, "Z") @ Matrix.Rotation(ry, 4, "Y") @ Matrix.Rotation(rx, 4, "X")
            bmesh.ops.transform(bm, matrix=m, verts=bm.verts)
        bmesh.ops.translate(bm, vec=Vector(at), verts=bm.verts)

    def box(self, at, size, material, group="Body", outline=True, rot=None, taper=None):
        """Axis-aligned box centred on `at`; `taper=(sx, sy)` shrinks the top face."""
        bm = bmesh.new()
        bmesh.ops.create_cube(bm, size=1.0)
        for v in bm.verts:
            if taper is not None and v.co.z > 0:
                v.co.x *= taper[0]
                v.co.y *= taper[1]
            v.co.x *= size[0]
            v.co.y *= size[1]
            v.co.z *= size[2]
        self._place(bm, at, rot)
        return self._object(bm, material, group, outline)

    def cyl(self, at, radius, depth, material, group="Body", outline=True, segments=8,
            axis="Z", rot=None, radius_top=None, scale=(1.0, 1.0)):
        """Cylinder (or frustum with `radius_top`) centred on `at` along `axis`."""
        bm = bmesh.new()
        bmesh.ops.create_cone(
            bm,
            cap_ends=True,
            segments=segments,
            radius1=radius,
            radius2=radius if radius_top is None else radius_top,
            depth=depth,
        )
        for v in bm.verts:
            v.co.x *= scale[0]
            v.co.y *= scale[1]
        if axis == "X":
            bmesh.ops.rotate(bm, verts=bm.verts, cent=(0, 0, 0), matrix=Matrix.Rotation(math.pi / 2, 3, "Y"))
        elif axis == "Y":
            bmesh.ops.rotate(bm, verts=bm.verts, cent=(0, 0, 0), matrix=Matrix.Rotation(math.pi / 2, 3, "X"))
        self._place(bm, at, rot)
        return self._object(bm, material, group, outline)

    def ball(self, at, size, material, group="Body", outline=True, subdivisions=1):
        bm = bmesh.new()
        bmesh.ops.create_icosphere(bm, subdivisions=subdivisions, radius=0.5)
        for v in bm.verts:
            v.co.x *= size[0]
            v.co.y *= size[1]
            v.co.z *= size[2]
        self._place(bm, at, None)
        return self._object(bm, material, group, outline)

    def loft(self, sections, material, group="Body", outline=True, cap_start=True, cap_end=True):
        """Skins closed cross-sections `[(x, [(y, z), ...]), ...]` (same point count each)."""
        bm = bmesh.new()
        rings = [[bm.verts.new((x, y, z)) for (y, z) in pts] for x, pts in sections]
        n = len(rings[0])
        for a, b in zip(rings, rings[1:]):
            for i in range(n):
                j = (i + 1) % n
                bm.faces.new((a[i], a[j], b[j], b[i]))
        if cap_start:
            bm.faces.new(list(reversed(rings[0])))
        if cap_end:
            bm.faces.new(rings[-1])
        bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-5)
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
        return self._object(bm, material, group, outline)

    def hull(self, stations, material, group="Body", outline=True, bottom_scale=0.55):
        """Ship hull from stations `(x, half_beam, deck_z, keel_z)`, stern first.
        Each section is a hard-chined hexagon: deck edge, chine, keel edge."""
        sections = []
        for x, w, top, keel in stations:
            chine_z = keel + (top - keel) * 0.45
            k = w * bottom_scale
            pts = [(-w, top), (-w * 0.93, chine_z), (-k, keel), (k, keel), (w * 0.93, chine_z), (w, top)]
            sections.append((x, pts))
        return self.loft(sections, material, group, outline)

    def prism(self, points, z0, z1, material, group="Body", outline=True):
        """Vertical prism over a closed XY outline (counter-clockwise), from z0 to z1."""
        bm = bmesh.new()
        bottom = [bm.verts.new((x, y, z0)) for x, y in points]
        top = [bm.verts.new((x, y, z1)) for x, y in points]
        n = len(points)
        for i in range(n):
            j = (i + 1) % n
            bm.faces.new((bottom[i], bottom[j], top[j], top[i]))
        bm.faces.new(top)
        bm.faces.new(list(reversed(bottom)))
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
        return self._object(bm, material, group, outline)

    def pivot(self, group, at):
        """Origin of a group's node (e.g. the gun's turning axis)."""
        self.pivots[group] = Vector(at)

    def parent(self, child, parent):
        """Makes group `child` a glTF child node of group `parent` (it follows the parent's motion)."""
        self.parents[child] = parent

    # ------------------------------------------------------------------ build and export

    def _shell(self, obj):
        """An inverted, slightly fattened copy: the cartoon outline."""
        bm = bmesh.new()
        bm.from_mesh(obj.data)
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
        bm.normal_update()
        moves = [(v, v.normal * self.outline * min(v.calc_shell_factor(), 2.0)) for v in bm.verts]
        for v, d in moves:
            v.co += d
        bmesh.ops.reverse_faces(bm, faces=bm.faces)
        mesh = bpy.data.meshes.new(obj.name + "_ink")
        bm.to_mesh(mesh)
        bm.free()
        shell = bpy.data.objects.new(obj.name + "_ink", mesh)
        bpy.context.collection.objects.link(shell)
        shell.matrix_world = obj.matrix_world.copy()
        mesh.materials.append(self.materials["Ink"])
        for poly in mesh.polygons:
            poly.use_smooth = False
        return shell

    def finish(self):
        """Joins every group into one object named after the group, pivots applied."""
        self.nodes = {}
        for group, parts in self.groups.items():
            objs = [o for o, _ in parts]
            objs += [self._shell(o) for o, outlined in parts if outlined and self.outline > 0]
            bpy.ops.object.select_all(action="DESELECT")
            for o in objs:
                o.select_set(True)
            bpy.context.view_layer.objects.active = objs[0]
            if len(objs) > 1:
                bpy.ops.object.join()
            node = bpy.context.view_layer.objects.active
            node.name = group
            node.data.name = group
            pivot = self.pivots.get(group)
            if pivot is not None:
                node.data.transform(Matrix.Translation(-pivot))
                node.location = pivot
            self.nodes[group] = node
        # Nest child nodes: keep each one where it is in the world, but let it follow its parent.
        bpy.context.view_layer.update()
        for child, parent in self.parents.items():
            node, up = self.nodes[child], self.nodes[parent]
            node.parent = up
            node.matrix_parent_inverse = up.matrix_world.inverted()
        return self

    def tris(self):
        count = 0
        for node in self.nodes.values():
            for p in node.data.polygons:
                count += len(p.vertices) - 2
        return count

    def _export(self, path):
        bpy.ops.object.select_all(action="SELECT")
        bpy.ops.export_scene.gltf(
            filepath=path,
            export_format="GLB",
            use_selection=False,
            export_apply=True,
            export_yup=True,
            export_texcoords=False,
            export_normals=True,
            export_materials="EXPORT",
            export_cameras=False,
            export_lights=False,
            export_animations=False,
            export_extras=False,
        )

    def gold(self):
        """Swaps every Paint* material for shining gold (the golden variant)."""
        gold = self.mat("Gold", GOLD, rough=0.35, metal=0.1, emit=0.45)
        gold_dark = self.mat("GoldDark", GOLD_DARK, rough=0.4, metal=0.1, emit=0.3)
        for node in self.nodes.values():
            slots = node.data.materials
            for i, m in enumerate(slots):
                if m is None:
                    continue
                if m.name.startswith("PaintDark"):
                    slots[i] = gold_dark
                elif m.name.startswith("Paint"):
                    slots[i] = gold

    def export(self, preview=True, gold=True, camera=None):
        os.makedirs(MODELS, exist_ok=True)
        os.makedirs(PREVIEWS, exist_ok=True)
        if not hasattr(self, "nodes"):
            self.finish()
        path = os.path.join(MODELS, self.name + ".glb")
        self._export(path)
        print(f"[model] {self.name}: {self.tris()} tris -> {path}")
        if preview:
            render_preview(os.path.join(PREVIEWS, self.name + ".png"), camera)
        if gold:
            self.gold()
            gold_path = os.path.join(MODELS, self.name + "_gold.glb")
            self._export(gold_path)
            print(f"[model] {self.name}_gold -> {gold_path}")
            if preview:
                render_preview(os.path.join(PREVIEWS, self.name + "_gold.png"), camera)


def render_preview(path, camera=None, size=(900, 600)):
    """3/4 view from the game's camera side (south, above), Eevee, soft sun."""
    scene = bpy.context.scene
    # Frame everything: bounding box over all mesh objects.
    lo = Vector((1e9, 1e9, 1e9))
    hi = Vector((-1e9, -1e9, -1e9))
    for o in scene.objects:
        if o.type != "MESH":
            continue
        for c in o.bound_box:
            w = o.matrix_world @ Vector(c)
            lo = Vector(map(min, lo, w))
            hi = Vector(map(max, hi, w))
    centre = (lo + hi) / 2
    radius = max((hi - lo).length / 2, 0.3)
    cam_data = bpy.data.cameras.new("PreviewCam")
    cam_data.lens = 50
    cam = bpy.data.objects.new("PreviewCam", cam_data)
    scene.collection.objects.link(cam)
    # Game camera looks from Bevy +Z (Blender -Y) and above; add a little yaw for 3/4.
    direction = Vector(camera or (0.5, -0.87, 1.73)).normalized()
    cam.location = centre + direction * radius * 3.3
    look = (centre - cam.location).to_track_quat("-Z", "Y")
    cam.rotation_euler = look.to_euler()
    scene.camera = cam
    sun_data = bpy.data.lights.new("PreviewSun", "SUN")
    sun_data.energy = 3.5
    sun = bpy.data.objects.new("PreviewSun", sun_data)
    sun.rotation_euler = (math.radians(40), math.radians(-20), math.radians(-30))
    scene.collection.objects.link(sun)
    world = bpy.data.worlds.new("PreviewWorld")
    world.use_nodes = True
    bg = world.node_tree.nodes.get("Background")
    bg.inputs["Color"].default_value = (0.55, 0.75, 0.95, 1.0)
    bg.inputs["Strength"].default_value = 0.9
    scene.world = world
    for engine in ("BLENDER_EEVEE", "BLENDER_EEVEE_NEXT", "BLENDER_WORKBENCH"):
        try:
            scene.render.engine = engine
            break
        except TypeError:
            continue
    scene.render.resolution_x, scene.render.resolution_y = size
    scene.render.film_transparent = False
    scene.view_settings.view_transform = "Standard"
    scene.render.filepath = path
    bpy.ops.render.render(write_still=True)
    for o in (cam, sun):
        bpy.data.objects.remove(o)
