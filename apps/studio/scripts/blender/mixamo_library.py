"""Build the football animation library from Mixamo clips (run inside Blender, headless).

    blender -b --factory-startup -P mixamo_library.py -- <character.fbx> <clips dir> <out.glb> <meta.json>

For every clip it measures what the game engine needs instead of guessing:
  root_speed   metres per second the hips travel (locomotion clips play at the player's real speed)
  root_dir     direction of travel relative to facing, in degrees (0 forward, 180 backpedal, +-90 strafe)
  contact      seconds into the clip when the striking foot or the head is moving fastest
               (the moment of ball contact, aligned to the event time at runtime)
  contact_bone which bone strikes (RightFoot, LeftFoot, Head, hands for the keeper)
Then it exports one GLB holding the rigged character and every clip as a named animation.
Mixamo files are licensed for use inside a product, not for redistribution, so the
inputs and the output stay out of git (assets-private/).
"""

import json
import math
import re
import sys
from pathlib import Path

import bpy
from mathutils import Vector

argv = sys.argv[sys.argv.index("--") + 1 :]
character, clips_dir, out_glb, out_meta = Path(argv[0]), Path(argv[1]), Path(argv[2]), Path(argv[3])

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.context.scene.render.fps = 30


def import_fbx(path: Path) -> list[bpy.types.Object]:
    before = set(bpy.data.objects)
    bpy.ops.import_scene.fbx(filepath=str(path), automatic_bone_orientation=False, ignore_leaf_bones=True)
    return [o for o in bpy.data.objects if o not in before]


def slug(name: str) -> str:
    s = re.sub(r"\((\d+)\)", r"\1", name.lower())
    return re.sub(r"[^a-z0-9]+", "_", s).strip("_")


rig_objs = import_fbx(character)
rig = next(o for o in rig_objs if o.type == "ARMATURE")
rig.name = "Player"
if rig.animation_data and rig.animation_data.action:
    rig.animation_data.action.name = "_bind"

actions: dict[str, bpy.types.Action] = {}
for f in sorted(clips_dir.glob("*.fbx")):
    objs = import_fbx(f)
    arm = next((o for o in objs if o.type == "ARMATURE"), None)
    act = arm.animation_data.action if arm and arm.animation_data else None
    if act is None:
        print(f"skip (no animation): {f.name}")
    else:
        name = slug(f.stem)
        act.name = name
        act.use_fake_user = True
        actions[name] = act
    for o in objs:
        bpy.data.objects.remove(o, do_unlink=True)

scene = bpy.context.scene
STRIKERS = {
    "head": ["mixamorig:Head"],
    "keeper": ["mixamorig:RightHand", "mixamorig:LeftHand"],
    "foot": ["mixamorig:RightFoot", "mixamorig:LeftFoot"],
}


def assign(action: bpy.types.Action) -> None:
    rig.animation_data_create()
    rig.animation_data.action = action
    if hasattr(rig.animation_data, "action_slot") and action.slots:
        rig.animation_data.action_slot = action.slots[0]


def world(bone: str) -> Vector:
    pb = rig.pose.bones[bone]
    return rig.matrix_world @ pb.head


meta: dict[str, dict] = {}
for name, act in actions.items():
    assign(act)
    f0, f1 = (int(round(v)) for v in act.frame_range)
    fps = scene.render.fps
    kind = "head" if "head" in name else "keeper" if name.startswith("goalkeeper") else "foot"
    track: dict[str, list[Vector]] = {b: [] for b in [*STRIKERS[kind], "mixamorig:Hips"]}
    facing = []
    for fr in range(f0, f1 + 1):
        scene.frame_set(fr)
        for b, pts in track.items():
            pts.append(world(b).copy())
        # facing: the hips' forward axis projected on the ground
        m = rig.matrix_world @ rig.pose.bones["mixamorig:Hips"].matrix
        fwd = m.to_3x3() @ Vector((0, 0, 1))
        facing.append(Vector((fwd.x, fwd.y)).normalized())
    hips = track["mixamorig:Hips"]
    dur = (f1 - f0) / fps
    disp = Vector((hips[-1].x - hips[0].x, hips[-1].y - hips[0].y))
    speed = disp.length / dur if dur > 0 else 0.0
    heading = math.degrees(math.atan2(facing[0].x, facing[0].y))
    travel = math.degrees(math.atan2(disp.x, disp.y)) if disp.length > 0.05 else 0.0
    rel = (travel - heading + 540) % 360 - 180
    best = (0.0, None, 0)
    for b in STRIKERS[kind]:
        pts = track[b]
        for i in range(1, len(pts)):
            v = (pts[i] - pts[i - 1]).length * fps
            if v > best[0]:
                best = (v, b, i)
    meta[name] = {
        "duration": round(dur, 3),
        "root_speed": round(speed, 3),
        "root_dir": round(rel, 1),
        "contact": round(best[2] / fps, 3),
        "contact_bone": (best[1] or "").replace("mixamorig:", ""),
        "contact_speed": round(best[0], 2),
    }
    print(
        f"{name:34s} {dur:5.2f}s speed {speed:4.2f} dir {rel:6.1f} contact {best[2] / fps:4.2f}s {meta[name]['contact_bone']}"
    )

# push every clip to its own NLA track so the exporter writes each as a named animation
rig.animation_data.action = None
for name, act in actions.items():
    trk = rig.animation_data.nla_tracks.new()
    trk.name = name
    strip = trk.strips.new(name, int(act.frame_range[0]), act)
    strip.name = name
    trk.mute = True

bpy.ops.object.select_all(action="DESELECT")
rig.select_set(True)
for o in bpy.data.objects:
    if o.type == "MESH" and o.parent == rig:
        o.select_set(True)
bpy.context.view_layer.objects.active = rig
out_glb.parent.mkdir(parents=True, exist_ok=True)
bpy.ops.export_scene.gltf(
    filepath=str(out_glb),
    export_format="GLB",
    use_selection=True,
    export_animations=True,
    export_animation_mode="NLA_TRACKS",
    export_force_sampling=True,
    export_frame_step=1,
    export_yup=True,
    export_apply=False,
)
out_meta.write_text(json.dumps(meta, indent=1), encoding="utf-8")
print(f"exported {len(actions)} clips to {out_glb}")
