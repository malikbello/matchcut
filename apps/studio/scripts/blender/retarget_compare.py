"""Retarget QA: the Mixamo source pose next to the retargeted footballer, same moment, same camera
(run in Blender, headless).

    blender -b --factory-startup -P retarget_compare.py -- <football.glb> <Y-Bot.fbx> <clips dir>
        <out dir> clip:seconds [clip:seconds ...]

For each shot it renders the source clip on its own skeleton (left) and the baked action on the
footballer (right), front and side. An arm turned the wrong way, a twisted wrist or a leaning
spine shows at a glance, before anything reaches a film.
"""

import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector

argv = sys.argv[sys.argv.index("--") + 1 :]
glb, ybot, clips_dir, out = (Path(a).resolve() for a in argv[:4])
shots = [a.split(":") for a in argv[4:]]
out.mkdir(parents=True, exist_ok=True)

bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
scene.render.engine = "BLENDER_WORKBENCH"
scene.display.shading.light = "STUDIO"
scene.display.shading.color_type = "MATERIAL"
scene.render.resolution_x, scene.render.resolution_y = 1000, 640
scene.render.fps = 30
cam_data = bpy.data.cameras.new("cam")
cam_data.lens = 35
cam = bpy.data.objects.new("cam", cam_data)
scene.collection.objects.link(cam)
scene.camera = cam

before = set(bpy.data.objects)
bpy.ops.import_scene.gltf(filepath=str(glb))
tgt_objs = [o for o in bpy.data.objects if o not in before]
tgt = next(o for o in tgt_objs if o.type == "ARMATURE")
for o in tgt_objs:
    if o.type == "MESH" and "m300" in o.name:
        o.hide_render = True  # one body is enough
pelvis_t = next(b for b in tgt.pose.bones if b.name.endswith("Pelvis") or b.name == "pelvis")


def slug(name: str) -> str:
    import re  # noqa: PLC0415

    return re.sub(r"[^a-z0-9]+", "_", re.sub(r"\((\d+)\)", r"\1", name.lower())).strip("_")


sources = {slug(f.stem): f for f in clips_dir.glob("*.fbx")}
# the source poses play on Mixamo's skinned Y-Bot (bare skeletons do not render)
before = set(bpy.data.objects)
bpy.ops.import_scene.fbx(filepath=str(ybot), automatic_bone_orientation=False)
src = next(o for o in bpy.data.objects if o not in before and o.type == "ARMATURE")
src.animation_data_create()

for clip, sec in shots:
    act = bpy.data.actions.get(clip)
    src_path = sources.get(clip)
    if act is None or src_path is None:
        print("missing", clip)
        continue
    before = set(bpy.data.objects)
    bpy.ops.import_scene.fbx(filepath=str(src_path), automatic_bone_orientation=False)
    clip_objs = [o for o in bpy.data.objects if o not in before]
    clip_arm = next(o for o in clip_objs if o.type == "ARMATURE")
    src_act = clip_arm.animation_data.action
    src_act.use_fake_user = True
    for o in clip_objs:
        bpy.data.objects.remove(o, do_unlink=True)
    src.animation_data.action = src_act
    if hasattr(src.animation_data, "action_slot") and src_act.slots:
        src.animation_data.action_slot = src_act.slots[0]
    src.location = (0, 0, 0)
    frame = int(round(float(sec) * 30))
    tgt.animation_data_create()
    tgt.animation_data.action = act
    if hasattr(tgt.animation_data, "action_slot") and act.slots:
        tgt.animation_data.action_slot = act.slots[0]
    scene.frame_set(frame + int(src.animation_data.action.frame_range[0]))
    # place the source 1.4 m to the footballer's right (+X is his left: put it at -X)
    hips_t = tgt.matrix_world @ pelvis_t.head
    hips_s = src.matrix_world @ src.pose.bones["mixamorig:Hips"].head
    src.location += Vector((hips_t.x - 1.4 - hips_s.x, hips_t.y - hips_s.y, 0))
    scene.frame_set(frame + int(src.animation_data.action.frame_range[0]))
    centre = Vector((hips_t.x - 0.7, hips_t.y, 1.0))
    for side, offset in (("front", Vector((0, -5.2, 0.3))), ("side", Vector((5.2, 0.0, 0.3)))):
        cam.location = centre + offset
        cam.rotation_euler = (centre - cam.location).to_track_quat("-Z", "Y").to_euler()
        if side == "side":
            cam.location = centre + Vector((5.2 * math.cos(0.5), -5.2 * math.sin(0.5), 0.3))
            cam.rotation_euler = (centre - cam.location).to_track_quat("-Z", "Y").to_euler()
        scene.render.filepath = str(out / f"{clip}-{sec}-{side}.png")
        bpy.ops.render.render(write_still=True)
    print("rendered", clip, sec)
