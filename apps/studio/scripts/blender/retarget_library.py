"""Retarget the Mixamo football clips onto the Quaternius base character, with hairstyles (run in Blender).

    blender -b --factory-startup -P retarget_library.py -- <character.fbx> <mixamo source rig.fbx>
        <clips dir> <hair dir> <out.glb> <meta.json>

Retargeting: for each mapped bone the source's world rotation relative to its rest pose
is applied to the target bone's rest pose (delta = R_src(t) * R_src_rest^-1; R_tgt(t) =
delta * R_tgt_rest). This is independent of bone roll and rest-pose differences. The
hips' travel is scaled by the ratio of hip heights. Unmapped target bones keep their rest
pose relative to their parent. Every clip is baked as an NLA track, and the clip metadata
(speed, direction, contact time) is measured on the target so it matches what plays.

Inputs are licensed (Mixamo: use in product only) and CC0 (Quaternius); the output
contains Mixamo-derived motion, so it stays private (git-ignored).
"""

import json
import math
import re
import sys
from pathlib import Path

import bpy
from mathutils import Matrix, Vector

argv = sys.argv[sys.argv.index("--") + 1 :]
character, _source_rig, clips_dir, hair_dir = (Path(a) for a in argv[:4])
out_glb, out_meta = Path(argv[4]), Path(argv[5])

MAP = {
    "Hips": "pelvis",
    "Spine": "spine_01",
    "Spine1": "spine_02",
    "Spine2": "spine_03",
    "Neck": "neck_01",
    "Head": "Head",
    "LeftShoulder": "clavicle_l",
    "LeftArm": "upperarm_l",
    "LeftForeArm": "lowerarm_l",
    "LeftHand": "hand_l",
    "RightShoulder": "clavicle_r",
    "RightArm": "upperarm_r",
    "RightForeArm": "lowerarm_r",
    "RightHand": "hand_r",
    "LeftUpLeg": "thigh_l",
    "LeftLeg": "calf_l",
    "LeftFoot": "foot_l",
    "LeftToeBase": "ball_l",
    "RightUpLeg": "thigh_r",
    "RightLeg": "calf_r",
    "RightFoot": "foot_r",
    "RightToeBase": "ball_r",
}
for side, s in (("Left", "l"), ("Right", "r")):
    for finger, f in (
        ("Thumb", "thumb"),
        ("Index", "index"),
        ("Middle", "middle"),
        ("Ring", "ring"),
        ("Pinky", "pinky"),
    ):
        for i in (1, 2, 3):
            MAP[f"{side}Hand{finger}{i}"] = f"{f}_0{i}_{s}"

bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
scene.render.fps = 30


def import_fbx(path: Path, leaf: bool = True) -> list[bpy.types.Object]:
    before = set(bpy.data.objects)
    bpy.ops.import_scene.fbx(filepath=str(path), automatic_bone_orientation=False, ignore_leaf_bones=leaf)
    return [o for o in bpy.data.objects if o not in before]


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", re.sub(r"\((\d+)\)", r"\1", name.lower())).strip("_")


# ---------------------------------------------------------------- target character and hair
tgt_objs = import_fbx(character, leaf=False)
tgt = next(o for o in tgt_objs if o.type == "ARMATURE")
tgt.name = "Footballer"
tgt.animation_data_create()
if tgt.animation_data.action:
    tgt.animation_data.action = None
bones_t = tgt.data.bones
assert "Head" in bones_t, "target rig has no Head bone"

for f in sorted(hair_dir.glob("*.fbx")):
    objs = import_fbx(f, leaf=False)
    hair_arm = next((o for o in objs if o.type == "ARMATURE"), None)
    for o in objs:
        if o.type != "MESH":
            continue
        o.name = f"HAIR_{f.stem}"
        # rebind to the footballer's skeleton (same bone names), keep the world placement
        for mod in o.modifiers:
            if mod.type == "ARMATURE":
                mod.object = tgt
        o.parent = tgt
    if hair_arm:
        bpy.data.objects.remove(hair_arm, do_unlink=True)

# ---------------------------------------------------------------- textures
# The FBX files point at texture paths that do not exist: relink them from the pack's Textures
# folders and size them for the web. The body takes the light skin map; the Studio tints it.
TEX_DIRS = [character.parent.parent / "Textures", hair_dir.parent.parent / "Textures"]
SIZES = {"Superhero": 1024, "Hair": 512, "Eye": 256}
for img in list(bpy.data.images):
    base = Path(img.filepath.replace("\\", "/")).name or img.name
    if "Superhero_Male" in base and "Normal" not in base and "Roughness" not in base:
        base = "T_Superhero_Male_Ligh.png"
    found = next((d / base for d in TEX_DIRS if (d / base).is_file()), None)
    if found is None:
        print(f"texture not found: {base}")
        continue
    img.filepath = str(found)
    img.reload()
    size = next((v for k, v in SIZES.items() if k in base), 512)
    if img.size[0] > size:
        img.scale(size, size)
    img.pack()


# ---------------------------------------------------------------- source (Mixamo) rest data
def sname(n: str) -> str:
    return f"mixamorig:{n}"


Wt = tgt.matrix_world.copy()
Wt_inv = Wt.inverted()
tgt_rest = {b.name: b.matrix_local.copy() for b in bones_t}  # armature space
tgt_rest_world_rot = {n: (Wt @ m).to_3x3() for n, m in tgt_rest.items()}
tgt_hip_rest = Wt @ bones_t["pelvis"].head_local
order = []  # target bones, parents first


def walk(b):
    order.append(b)
    for c in b.children:
        walk(c)


for b in bones_t:
    if b.parent is None:
        walk(b)
for pb in tgt.pose.bones:
    pb.rotation_mode = "QUATERNION"


ref_objs = import_fbx(_source_rig)
ref = next(o for o in ref_objs if o.type == "ARMATURE")
# the two rigs face opposite ways (Mixamo left arm rests along +X, the target's along -X):
# turn the source frame 180 degrees about the vertical so rotations transfer unmirrored
ALIGN = Matrix.Rotation(math.pi, 4, "Z")
Wr = ALIGN @ ref.matrix_world
REF_REST_ROT = {
    k: (Wr @ ref.data.bones[sname(k)].matrix_local).to_3x3() for k in MAP if sname(k) in ref.data.bones
}
REF_HIP_REST = Wr @ ref.data.bones[sname("Hips")].head_local
for o in ref_objs:
    bpy.data.objects.remove(o, do_unlink=True)


def bake(src: bpy.types.Object, action_src: bpy.types.Action, name: str) -> bpy.types.Action:
    """Retarget one clip from its OWN source skeleton (each Mixamo download carries its own rest pose)."""
    # the pose comes from the clip's own skeleton (its world matrices are right whatever its rest);
    # the rest reference is the skinned Y-Bot's true T-pose (animation-only files have no bind pose)
    Ws = ALIGN @ src.matrix_world
    src_rest_rot = REF_REST_ROT
    src_hip_rest = REF_HIP_REST
    scale = tgt_hip_rest.z / max(src_hip_rest.z, 1e-6)
    inv_map = {v: k for k, v in MAP.items() if sname(k) in src.data.bones and k in REF_REST_ROT}
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
                delta = (Ws @ sp.matrix).to_3x3() @ src_rest_rot[k].inverted()
                rot_arm = (Wt_inv.to_3x3() @ (delta @ tgt_rest_world_rot[bone.name])).normalized()
                loc = default.to_translation()
                if bone.name == "pelvis":
                    loc = Wt_inv @ (tgt_hip_rest + ((Ws @ sp.head) - src_hip_rest) * scale)
                desired = Matrix.Translation(loc) @ rot_arm.to_4x4()
            else:
                desired = default
            pose_arm[bone.name] = desired
            pb.matrix_basis = rel_rest.inverted() @ parent_pose.inverted() @ desired
            pb.keyframe_insert("rotation_quaternion", frame=fr - f0)
            if bone.name == "pelvis":
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
        bpy.data.objects.remove(o, do_unlink=True)

# ---------------------------------------------------------------- measure on the target
STRIKERS = {"head": ["Head"], "keeper": ["hand_r", "hand_l"], "foot": ["foot_r", "foot_l"]}
meta: dict[str, dict] = {}
for name, act in baked.items():
    tgt.animation_data.action = act
    f0, f1 = (int(round(v)) for v in act.frame_range)
    kind = "head" if "head" in name else "keeper" if name.startswith("goalkeeper") else "foot"
    hips, strikers = [], {b: [] for b in STRIKERS[kind]}
    facing = None
    for fr in range(f0, f1 + 1):
        scene.frame_set(fr)
        hips.append(Wt @ tgt.pose.bones["pelvis"].head)
        for b, pts in strikers.items():
            pts.append(Wt @ tgt.pose.bones[b].head)
        if facing is None:
            fwd = (Wt @ tgt.pose.bones["pelvis"].matrix).to_3x3() @ Vector((0, 1, 0))
            facing = Vector((fwd.x, fwd.y)).normalized()
    dur = (f1 - f0) / 30
    disp = Vector((hips[-1].x - hips[0].x, hips[-1].y - hips[0].y))
    speed = disp.length / dur if dur > 0 else 0.0
    heading = math.degrees(math.atan2(facing.x, facing.y))
    travel = math.degrees(math.atan2(disp.x, disp.y)) if disp.length > 0.05 else 0.0
    best = (0.0, "", 0)
    for b, pts in strikers.items():
        for i in range(1, len(pts)):
            v = (pts[i] - pts[i - 1]).length * 30
            if v > best[0]:
                best = (v, b, i)
    meta[name] = {
        "duration": round(dur, 3),
        "root_speed": round(speed, 3),
        "root_dir": round((travel - heading + 540) % 360 - 180, 1),
        "contact": round(best[2] / 30, 3),
        "contact_bone": best[1],
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
out_glb.parent.mkdir(parents=True, exist_ok=True)
bpy.ops.export_scene.gltf(
    filepath=str(out_glb),
    export_format="GLB",
    use_selection=True,
    export_animations=True,
    export_animation_mode="NLA_TRACKS",
    export_force_sampling=True,
    export_yup=True,
)
out_meta.write_text(json.dumps(meta, indent=1), encoding="utf-8")
print(
    f"exported {len(baked)} clips, {len([o for o in bpy.data.objects if o.name.startswith('HAIR_')])} hairstyles"
)
