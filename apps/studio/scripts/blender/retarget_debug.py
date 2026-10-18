"""Compare world bone directions: Mixamo clip skeleton vs Y-Bot rest vs target rest (run in Blender)."""

import sys
from pathlib import Path

import bpy

clip, ybot, char = (Path(a) for a in sys.argv[sys.argv.index("--") + 1 :][:3])
bpy.ops.wm.read_factory_settings(use_empty=True)


def imp(p, leaf=True):
    before = set(bpy.data.objects)
    bpy.ops.import_scene.fbx(filepath=str(p), automatic_bone_orientation=False, ignore_leaf_bones=leaf)
    return next(o for o in bpy.data.objects if o not in before and o.type == "ARMATURE")


src = imp(clip)
ref = imp(ybot)
tgt = imp(char, leaf=False)
act = src.animation_data.action
print(
    "action",
    act.name,
    act.frame_range,
    "slots",
    [s.identifier for s in getattr(act, "slots", [])],
    "slot bound",
    getattr(src.animation_data, "action_slot", None),
)


def d(o, bone, pose=True):
    if pose:
        pb = o.pose.bones[bone]
        v = (o.matrix_world @ pb.tail) - (o.matrix_world @ pb.head)
    else:
        b = o.data.bones[bone]
        v = (o.matrix_world @ b.tail_local) - (o.matrix_world @ b.head_local)
    v.normalize()
    return f"({v.x:+.2f},{v.y:+.2f},{v.z:+.2f})"


for fr in (1, 6):
    bpy.context.scene.frame_set(fr)
    print(f"frame {fr}")
    for s, t in (
        ("LeftArm", "upperarm_l"),
        ("LeftForeArm", "lowerarm_l"),
        ("Spine2", "spine_03"),
        ("LeftUpLeg", "thigh_l"),
    ):
        print(
            f"  {s:12s} clip-pose {d(src, 'mixamorig:' + s)}  clip-rest {d(src, 'mixamorig:' + s, False)}  "
            f"ybot-rest {d(ref, 'mixamorig:' + s, False)}  tgt-rest {d(tgt, t, False)}"
        )
print("world matrices: clip", [round(x, 3) for x in src.matrix_world.to_euler()], src.matrix_world.to_scale())
print("ybot", [round(x, 3) for x in ref.matrix_world.to_euler()], ref.matrix_world.to_scale())
print("tgt", [round(x, 3) for x in tgt.matrix_world.to_euler()], tgt.matrix_world.to_scale())
