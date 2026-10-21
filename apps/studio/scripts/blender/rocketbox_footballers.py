"""Realistic footballers for the show camera: Microsoft Rocketbox athletes with the Mixamo football
clips (run in Blender, headless).

    blender -b --factory-startup -P rocketbox_footballers.py -- <rocketbox dir> <mixamo rig.fbx>
        <clips dir> <out dir>

Characters: Microsoft Rocketbox Sports_Male_02 and Sports_Male_03 (MIT licence): two real-looking
footballers in full kit on the same 3ds Max Biped skeleton. Both bodies are bound to one armature,
so every clip plays on either.

Kits: each body gets a kit mask texture, baked here from the bind pose so it follows the body:
  R  region: 0 skin and face, 1 shirt, 2 shorts, 3 socks, 4 boots, 5 trim (collar, cuffs, piping)
     (the dominant bone of each triangle decides the garment; skin and the orange trim are then
     found in the original texture, so a bare knee or a collar is never painted as cloth)
  G  B  where a texel of the shirt's back sits in the name-and-number panel (0..1 each), so the
     Studio prints any name and number there, upright and unmirrored, whatever the UV layout
  A  255 inside that panel
The sponsor, crest and stock numbers disappear because kit regions are repainted in club colours;
the fabric's folds stay, carried by the normal map.

Motion: each Mixamo clip is retargeted the way the Quaternius build does it (world rotation
relative to rest, delta = R_src(t) R_src_rest^-1 applied to the target rest; hips travel scaled by
hip height). Rocketbox faces -Y with its left side at +X, as Mixamo does, so no turn is needed.
Clip metadata (speed, direction, contact time and bone) is measured on the target; bone names are
written in the Studio's generic form (foot_r, foot_l, head, hand_r, hand_l).

The output holds Mixamo-derived motion, so it stays private (git-ignored), like the old library.
"""

import json
import math
import re
import sys
from pathlib import Path

import bpy
import numpy as np
from mathutils import Matrix, Vector

argv = sys.argv[sys.argv.index("--") + 1 :]
rb_dir, source_rig, clips_dir, out_dir = (Path(a).resolve() for a in argv[:4])
out_dir.mkdir(parents=True, exist_ok=True)
VARIANTS = {"Sports_Male_02": "m301", "Sports_Male_03": "m300"}
MASK_SIZE = 1024
FPS = 30

MAP = {
    "Hips": "Bip01 Pelvis",
    "Spine": "Bip01 Spine",
    "Spine1": "Bip01 Spine1",
    "Spine2": "Bip01 Spine2",
    "Neck": "Bip01 Neck",
    "Head": "Bip01 Head",
}
for side, s in (("Left", "L"), ("Right", "R")):
    MAP |= {
        f"{side}Shoulder": f"Bip01 {s} Clavicle",
        f"{side}Arm": f"Bip01 {s} UpperArm",
        f"{side}ForeArm": f"Bip01 {s} Forearm",
        f"{side}Hand": f"Bip01 {s} Hand",
        f"{side}UpLeg": f"Bip01 {s} Thigh",
        f"{side}Leg": f"Bip01 {s} Calf",
        f"{side}Foot": f"Bip01 {s} Foot",
        f"{side}ToeBase": f"Bip01 {s} Toe0",
    }
    for i, finger in enumerate(("Thumb", "Index", "Middle", "Ring", "Pinky")):
        MAP |= {
            f"{side}Hand{finger}1": f"Bip01 {s} Finger{i}",
            f"{side}Hand{finger}2": f"Bip01 {s} Finger{i}1",
            f"{side}Hand{finger}3": f"Bip01 {s} Finger{i}2",
        }
GENERIC = {
    "Bip01 R Foot": "foot_r",
    "Bip01 L Foot": "foot_l",
    "Bip01 Head": "head",
    "Bip01 R Hand": "hand_r",
    "Bip01 L Hand": "hand_l",
}
REGION_OF_BONE = {
    "Spine": 1, "Spine1": 1, "Spine2": 1, "Neck": 1, "Clavicle": 1, "UpperArm": 1,
    "Pelvis": 2, "Thigh": 2,
    "Calf": 3,
    "Foot": 4, "Toe0": 4,
}  # fmt: skip

bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
scene.render.fps = FPS


def import_fbx(path: Path) -> list[bpy.types.Object]:
    before = set(bpy.data.objects)
    bpy.ops.import_scene.fbx(filepath=str(path), automatic_bone_orientation=False, ignore_leaf_bones=False)
    return [o for o in bpy.data.objects if o not in before]


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", re.sub(r"\((\d+)\)", r"\1", name.lower())).strip("_")


# ---------------------------------------------------------------- both footballers on one skeleton
tgt = None
bodies: dict[str, bpy.types.Object] = {}
for name, code in VARIANTS.items():
    objs = import_fbx(rb_dir / name / f"{name}.fbx")
    arm = next(o for o in objs if o.type == "ARMATURE")
    mesh = next(o for o in objs if o.type == "MESH")
    mesh.name = f"FOOTBALLER_{code}"
    bodies[code] = mesh
    if tgt is None:
        tgt = arm
        tgt.name = "Footballer"
    else:
        # same Biped, same rest pose (checked): rebind this body to the first skeleton
        for mod in mesh.modifiers:
            if mod.type == "ARMATURE":
                mod.object = tgt
        world = mesh.matrix_world.copy()
        mesh.parent = tgt
        mesh.matrix_world = world
        bpy.data.objects.remove(arm, do_unlink=True)
for o in list(bpy.data.objects):
    if o.type == "EMPTY":  # the Biped's footstep helpers
        bpy.data.objects.remove(o, do_unlink=True)
assert tgt is not None
tgt.animation_data_create()
tgt.animation_data.action = None
bones_t = tgt.data.bones
Wt = tgt.matrix_world.copy()
Wt_inv = Wt.inverted()


# ---------------------------------------------------------------- kit masks (bind pose)
def image_pixels(img: bpy.types.Image) -> np.ndarray:
    w, h = img.size
    px = np.empty(w * h * 4, dtype=np.float32)
    img.pixels.foreach_get(px)
    return px.reshape(h, w, 4)


def skin_like(rgb: np.ndarray) -> np.ndarray:
    """Skin tones by hue and saturation (light to dark); kit black, white and orange fail it."""
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    mx, mn = rgb.max(-1), rgb.min(-1)
    sat = np.where(mx > 1e-4, (mx - mn) / np.maximum(mx, 1e-4), 0)
    hue_ok = (r >= g) & (g >= b * 0.85) & ((r - g) < 0.45 * np.maximum(r, 1e-4))
    return hue_ok & (sat > 0.12) & (sat < 0.62) & (mx > 0.16) & (mx < 0.98)


def trim_like(rgb: np.ndarray) -> np.ndarray:
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    mx, mn = rgb.max(-1), rgb.min(-1)
    sat = np.where(mx > 1e-4, (mx - mn) / np.maximum(mx, 1e-4), 0)
    return (sat > 0.68) & (r > 0.45) & (r > g * 1.6) & (g >= b)


PANEL = (-0.16, 0.16, 1.12, 1.46)  # the back's name panel: x across the spine, z shoulder blades to waist


def garments(mesh: bpy.types.Object, tris: list) -> dict[int, int]:
    """Garment per triangle: its dominant bone first, then its UV island's majority garment (a
    garment is one island, so the shirt hem over the hips stays shirt though the pelvis moves it)."""
    me = mesh.data
    groups = {g.index: g.name for g in mesh.vertex_groups}
    weights = [{groups[g.group]: g.weight for g in v.groups if g.group in groups} for v in me.vertices]
    first: dict[int, int] = {}
    for t in tris:
        score: dict[int, float] = {}
        for vi in t.vertices:
            for gname, w in weights[vi].items():
                reg = REGION_OF_BONE.get(gname.replace("Bip01 ", "").replace("L ", "").replace("R ", ""), 0)
                score[reg] = score.get(reg, 0.0) + w
        first[t.index] = max(score, key=score.get) if score else 0
    parent = {t.index: t.index for t in tris}

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    uv = me.uv_layers.active.data
    owner: dict[tuple, int] = {}
    for t in tris:
        for li in t.loops:
            key = (me.loops[li].vertex_index, round(uv[li].uv[0], 5), round(uv[li].uv[1], 5))
            if key in owner:
                parent[find(t.index)] = find(owner[key])
            else:
                owner[key] = t.index
    votes: dict[int, dict[int, float]] = {}
    for t in tris:
        if first[t.index]:
            v = votes.setdefault(find(t.index), {})
            v[first[t.index]] = v.get(first[t.index], 0.0) + t.area
    out = {}
    for t in tris:
        island = votes.get(find(t.index))
        out[t.index] = (max(island, key=island.get) if island else first[t.index]) if first[t.index] else 0
    return out


def rasterize(uvs: np.ndarray, p3: np.ndarray, reg: int, region: np.ndarray, deco: np.ndarray) -> None:
    """Paint one triangle's garment into the mask; on the shirt's back, its texels' panel coordinates."""
    S = region.shape[0]
    n = np.cross(p3[1] - p3[0], p3[2] - p3[0])
    back = n[1] / (np.linalg.norm(n) + 1e-9) > 0.35  # faces +Y: the back (the face looks at -Y)
    lo = np.floor(uvs.min(0)).astype(int)
    hi = np.ceil(uvs.max(0)).astype(int)
    xs, ys = np.meshgrid(np.arange(lo[0], hi[0] + 1), np.arange(lo[1], hi[1] + 1))
    pts = np.stack([xs.ravel() + 0.5, ys.ravel() + 0.5], -1)
    a, b, c = uvs
    den = (b[1] - c[1]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[1] - c[1])
    if abs(den) < 1e-9:
        return
    l1 = ((b[1] - c[1]) * (pts[:, 0] - c[0]) + (c[0] - b[0]) * (pts[:, 1] - c[1])) / den
    l2 = ((c[1] - a[1]) * (pts[:, 0] - c[0]) + (a[0] - c[0]) * (pts[:, 1] - c[1])) / den
    l3 = 1 - l1 - l2
    inside = (l1 >= -0.01) & (l2 >= -0.01) & (l3 >= -0.01)
    px = xs.ravel()[inside].clip(0, S - 1)
    py = ys.ravel()[inside].clip(0, S - 1)
    region[py, px] = reg
    if reg != 1 or not back:
        return
    x0, x1, z0, z1 = PANEL
    p = np.stack([l1[inside], l2[inside], l3[inside]], -1) @ p3
    u = (x1 - p[:, 0]) / (x1 - x0)  # read from behind: the player's left is the viewer's right
    v = (p[:, 2] - z0) / (z1 - z0)
    ok = (u >= 0) & (u <= 1) & (v >= 0) & (v <= 1)
    deco[py[ok], px[ok], 0] = (u[ok] * 255).astype(np.uint8)
    deco[py[ok], px[ok], 1] = (v[ok] * 255).astype(np.uint8)
    deco[py[ok], px[ok], 2] = 255


def panel_fit(deco: np.ndarray) -> dict:
    """A smooth map from texture UV (glTF convention, v down) to the panel, fitted on the panel's
    texels: the back is one flat UV island, so an affine fit prints names sharp at any size."""
    S = deco.shape[0]
    pr, pc = np.nonzero(deco[..., 2] > 0)
    A = np.stack([(pc + 0.5) / S, 1.0 - (pr + 0.5) / S, np.ones(len(pr))], -1)
    du = deco[pr, pc, 0] / 255.0
    dv = deco[pr, pc, 1] / 255.0
    fu, *_ = np.linalg.lstsq(A, du, rcond=None)
    fv, *_ = np.linalg.lstsq(A, dv, rcond=None)
    err = float(np.abs(A @ fu - du).mean() + np.abs(A @ fv - dv).mean()) / 2
    return {"decal": [round(float(x), 6) for x in (*fu, *fv)], "fit_error": round(err, 4)}


def bake_mask(mesh: bpy.types.Object, code: str) -> None:
    me = mesh.data
    me.calc_loop_triangles()
    body_slot = next(i for i, m in enumerate(me.materials) if m.name.endswith("_body"))
    src = next(
        n.image
        for n in me.materials[body_slot].node_tree.nodes
        if n.type == "TEX_IMAGE" and "color" in n.image.filepath
    )
    colour = image_pixels(src)
    sh, sw = colour.shape[:2]
    pos = np.array([tuple(mesh.matrix_world @ v.co) for v in me.vertices], dtype=np.float32)
    uv = me.uv_layers.active.data
    S = MASK_SIZE
    region = np.zeros((S, S), np.uint8)
    deco = np.zeros((S, S, 3), np.uint8)
    tris = [t for t in me.loop_triangles if t.material_index == body_slot]
    garment = garments(mesh, tris)
    for t in tris:
        if garment[t.index]:
            uvs = np.array([tuple(uv[li].uv) for li in t.loops], dtype=np.float32) * (S - 1)
            rasterize(uvs, pos[list(t.vertices)], garment[t.index], region, deco)
    # colour tests on the original texture, resampled to the mask (rows are bottom-up in both)
    ys_, xs_ = np.mgrid[0:S, 0:S]
    rgb = colour[(ys_ * sh // S), (xs_ * sw // S), :3]
    cloth = (region > 0) & (region != 4)
    region[cloth & skin_like(rgb)] = 0
    region[cloth & (region > 0) & trim_like(rgb)] = 5
    out = np.zeros((S, S, 4), np.float32)
    out[..., 0] = region * 40 / 255
    out[..., 1] = deco[..., 0] / 255
    out[..., 2] = deco[..., 1] / 255
    out[..., 3] = np.where(deco[..., 2] > 0, 1.0, 0.0)
    KITS[code] = panel_fit(deco)
    img = bpy.data.images.new(f"kit_{code}", S, S, alpha=True, float_buffer=False)
    img.colorspace_settings.name = "Non-Color"
    img.pixels.foreach_set(out.ravel())
    img.filepath_raw = str(out_dir / f"kit_{code}.png")
    img.file_format = "PNG"
    img.save()
    counts = {k: int((region == k).sum()) for k in range(6)}
    print(f"kit mask {code}: regions {counts}, number panel texels {int((deco[..., 2] > 0).sum())}")


KITS: dict[str, dict] = {}
for code, mesh in bodies.items():
    bake_mask(mesh, code)
(out_dir / "kits.json").write_text(json.dumps(KITS, indent=1), encoding="utf-8")
print(f"kits: {KITS}")


# ---------------------------------------------------------------- web-ready materials
SIZES = {"body_color": 1024, "body_normal": 1024, "head_color": 1024, "head_normal": 512, "opacity": 512}
for mat in bpy.data.materials:
    if not mat.node_tree:
        continue
    nodes = mat.node_tree.nodes
    for n in list(nodes):
        if n.type == "TEX_IMAGE" and n.image:
            stem = Path(n.image.filepath).stem
            if "specular" in stem:
                nodes.remove(n)  # no glTF use; the Studio sets cloth and skin roughness
                continue
            size = next((v for k, v in SIZES.items() if k in stem), 512)
            if n.image.size[0] > size:
                n.image.scale(size, size)
            n.image.pack()
    bsdf = next((n for n in nodes if n.type == "BSDF_PRINCIPLED"), None)
    if bsdf:
        bsdf.inputs["Roughness"].default_value = 0.72 if mat.name.endswith("_body") else 0.55
        if "Specular IOR Level" in bsdf.inputs:
            bsdf.inputs["Specular IOR Level"].default_value = 0.3


# ---------------------------------------------------------------- retarget the Mixamo clips
def sname(n: str) -> str:
    return f"mixamorig:{n}"


tgt_rest = {b.name: b.matrix_local.copy() for b in bones_t}
tgt_rest_world_rot = {n: (Wt @ m).to_3x3() for n, m in tgt_rest.items()}
tgt_hip_rest = Wt @ bones_t["Bip01 Pelvis"].head_local
order: list[bpy.types.Bone] = []


def walk(b: bpy.types.Bone) -> None:
    order.append(b)
    for c in b.children:
        walk(c)


for b in bones_t:
    if b.parent is None:
        walk(b)
for pb in tgt.pose.bones:
    pb.rotation_mode = "QUATERNION"

ref_objs = import_fbx(source_rig)
ref = next(o for o in ref_objs if o.type == "ARMATURE")
Wr = ref.matrix_world.copy()  # Rocketbox and Mixamo face the same way: no turn
REF_REST_ROT = {
    k: (Wr @ ref.data.bones[sname(k)].matrix_local).to_3x3() for k in MAP if sname(k) in ref.data.bones
}
REF_HIP_REST = Wr @ ref.data.bones[sname("Hips")].head_local
for o in ref_objs:
    bpy.data.objects.remove(o, do_unlink=True)


def bake(src: bpy.types.Object, action_src: bpy.types.Action, name: str) -> bpy.types.Action:
    Ws = src.matrix_world.copy()
    scale = tgt_hip_rest.z / max(REF_HIP_REST.z, 1e-6)
    inv_map = {
        v: k for k, v in MAP.items() if sname(k) in src.data.bones and k in REF_REST_ROT and v in bones_t
    }
    src.animation_data.action = action_src
    if hasattr(src.animation_data, "action_slot") and action_src.slots:
        src.animation_data.action_slot = action_src.slots[0]
    f0, f1 = (int(round(v)) for v in action_src.frame_range)
    act = bpy.data.actions.new(name)
    act.use_fake_user = True
    tgt.animation_data.action = act
    for fr in range(f0, f1 + 1):
        scene.frame_set(fr)
        pose_arm: dict[str, Matrix] = {}
        for bone in order:
            pb = tgt.pose.bones[bone.name]
            rest = tgt_rest[bone.name]
            if bone.parent is not None:
                parent_pose = pose_arm[bone.parent.name]
                rel_rest = tgt_rest[bone.parent.name].inverted() @ rest
            else:
                parent_pose = Matrix.Identity(4)
                rel_rest = rest
            default = parent_pose @ rel_rest
            k = inv_map.get(bone.name)
            if k is not None:
                sp = src.pose.bones[sname(k)]
                delta = (Ws @ sp.matrix).to_3x3() @ REF_REST_ROT[k].inverted()
                rot_arm = (Wt_inv.to_3x3() @ (delta @ tgt_rest_world_rot[bone.name])).normalized()
                loc = default.to_translation()
                if bone.name == "Bip01 Pelvis":
                    loc = Wt_inv @ (tgt_hip_rest + ((Ws @ sp.head) - REF_HIP_REST) * scale)
                desired = Matrix.Translation(loc) @ rot_arm.to_4x4()
            else:
                desired = default
            pose_arm[bone.name] = desired
            if k is None:
                continue  # unmapped bones (face, eyes) keep their rest pose: no keys
            pb.matrix_basis = rel_rest.inverted() @ parent_pose.inverted() @ desired
            pb.keyframe_insert("rotation_quaternion", frame=fr - f0)
            if bone.name == "Bip01 Pelvis":
                pb.keyframe_insert("location", frame=fr - f0)
    return act


baked: dict[str, bpy.types.Action] = {}
for f in sorted(clips_dir.glob("*.fbx")):
    objs = import_fbx(f)
    arm = next((o for o in objs if o.type == "ARMATURE"), None)
    act = arm.animation_data.action if arm and arm.animation_data else None
    if act is None or sname("Hips") not in arm.data.bones:
        print(f"skip {f.name}")
    else:
        act.use_fake_user = True
        baked[slug(f.stem)] = bake(arm, act, slug(f.stem))
        print(f"baked {slug(f.stem)}")
    for o in objs:
        if o.name in bpy.data.objects:
            bpy.data.objects.remove(o, do_unlink=True)


# ---------------------------------------------------------------- measure on the target
def facing_of() -> Vector:
    # up x (right hip - left hip): the way the pelvis faces, whatever the bone's own axes
    left = Wt @ tgt.pose.bones["Bip01 L Thigh"].head
    right = Wt @ tgt.pose.bones["Bip01 R Thigh"].head
    f = Vector((0, 0, 1)).cross(right - left)
    return Vector((f.x, f.y)).normalized()


STRIKERS = {
    "head": ["Bip01 Head"],
    "keeper": ["Bip01 R Hand", "Bip01 L Hand"],
    "foot": ["Bip01 R Foot", "Bip01 L Foot"],
}
meta: dict[str, dict] = {}
for name, act in baked.items():
    tgt.animation_data.action = act
    f0, f1 = (int(round(v)) for v in act.frame_range)
    kind = "head" if "head" in name else "keeper" if name.startswith("goalkeeper") else "foot"
    hips: list[Vector] = []
    strikers: dict[str, list[Vector]] = {b: [] for b in STRIKERS[kind]}
    facing = None
    for fr in range(f0, f1 + 1):
        scene.frame_set(fr)
        hips.append(Wt @ tgt.pose.bones["Bip01 Pelvis"].head)
        for b, pts in strikers.items():
            pts.append(Wt @ tgt.pose.bones[b].tail if "Foot" in b else Wt @ tgt.pose.bones[b].head)
        if facing is None:
            facing = facing_of()
    dur = (f1 - f0) / FPS
    disp = Vector((hips[-1].x - hips[0].x, hips[-1].y - hips[0].y))
    speed = disp.length / dur if dur > 0 else 0.0
    heading = math.degrees(math.atan2(facing.x, facing.y))
    travel = math.degrees(math.atan2(disp.x, disp.y)) if disp.length > 0.05 else heading
    best = (0.0, "", 0)
    for b, pts in strikers.items():
        for i in range(1, len(pts)):
            v = (pts[i] - pts[i - 1]).length * FPS
            if v > best[0]:
                best = (v, b, i)
    meta[name] = {
        "duration": round(dur, 3),
        "root_speed": round(speed, 3),
        "root_dir": round((travel - heading + 540) % 360 - 180, 1),
        "contact": round(best[2] / FPS, 3),
        "contact_bone": GENERIC.get(best[1], best[1]),
        "contact_speed": round(best[0], 2),
    }

# ---------------------------------------------------------------- export
tgt.animation_data.action = None
for name, act in baked.items():
    trk = tgt.animation_data.nla_tracks.new()
    trk.name = name
    trk.strips.new(name, 0, act).name = name
    trk.mute = True
bpy.ops.object.select_all(action="DESELECT")
for o in bpy.data.objects:
    if tgt in (o, o.parent):
        o.select_set(True)
bpy.context.view_layer.objects.active = tgt
bpy.ops.export_scene.gltf(
    filepath=str(out_dir / "football.glb"),
    export_format="GLB",
    use_selection=True,
    export_animations=True,
    export_animation_mode="NLA_TRACKS",
    export_force_sampling=True,
    export_yup=True,
    export_image_format="WEBP",
    export_image_quality=88,
)
(out_dir / "football.meta.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
print(f"exported {len(baked)} clips onto {len(bodies)} Rocketbox footballers")
