"""Print an FBX character's armature: bone names, hierarchy, rest-pose world heads (run in Blender)."""

import sys
from pathlib import Path

import bpy

path = Path(sys.argv[sys.argv.index("--") + 1])
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.fbx(filepath=str(path), automatic_bone_orientation=False, ignore_leaf_bones=True)
for o in bpy.data.objects:
    print(
        f"OBJ {o.type:9s} {o.name} scale={tuple(round(s, 3) for s in o.scale)} rot={tuple(round(r, 3) for r in o.rotation_euler)}"
    )
    if o.type == "MESH":
        print(
            f"    verts={len(o.data.vertices)} mats={[m.name for m in o.data.materials]} uv={len(o.data.uv_layers)}"
        )
arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
for b in arm.data.bones:
    head = arm.matrix_world @ b.head_local
    print(
        f"BONE {b.name:28s} parent={b.parent.name if b.parent else '-':24s} head=({head.x:.3f},{head.y:.3f},{head.z:.3f})"
    )
