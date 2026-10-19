"""Render a QA contact sheet of retargeted poses (run in Blender): one image per clip at chosen times.

blender -b --factory-startup -P pose_sheet.py -- <footballer.glb> <out dir> clip:seconds [clip:seconds ...]
"""

import sys
from pathlib import Path

import bpy
from mathutils import Vector

argv = sys.argv[sys.argv.index("--") + 1 :]
glb, out = Path(argv[0]), Path(argv[1])
shots = [a.split(":") for a in argv[2:]]
out.mkdir(parents=True, exist_ok=True)

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=str(glb))
arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
for o in bpy.data.objects:
    if o.type == "MESH" and o.name.startswith("HAIR_") and "Buzzed" not in o.name and "Beard" not in o.name:
        o.hide_render = True
scene = bpy.context.scene
scene.render.engine = "BLENDER_WORKBENCH"
scene.display.shading.light = "STUDIO"
scene.display.shading.color_type = "MATERIAL"
scene.render.resolution_x, scene.render.resolution_y = 640, 720
cam_data = bpy.data.cameras.new("cam")
cam = bpy.data.objects.new("cam", cam_data)
scene.collection.objects.link(cam)
scene.camera = cam
for clip, sec in shots:
    act = bpy.data.actions.get(clip)
    if act is None:
        print("missing", clip)
        continue
    arm.animation_data_create()
    arm.animation_data.action = act
    if hasattr(arm.animation_data, "action_slot") and act.slots:
        arm.animation_data.action_slot = act.slots[0]
    scene.frame_set(int(round(float(sec) * 30)))
    hips = arm.matrix_world @ arm.pose.bones["pelvis"].head
    target = Vector((hips.x, hips.y, max(0.5, hips.z)))
    for side, offset in (("front", Vector((2.2, -3.2, 0.9))), ("side", Vector((3.8, 0.4, 0.9)))):
        cam.location = target + offset
        cam.rotation_euler = (target - cam.location).to_track_quat("-Z", "Y").to_euler()
        scene.render.filepath = str(out / f"{clip}-{side}.png")
        bpy.ops.render.render(write_still=True)
    print("rendered", clip)
