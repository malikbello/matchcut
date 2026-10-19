"""Bake crowd impostors: a CC0 fan rendered in eight poses as sprite cards (run in Blender).

    blender -b --factory-startup -P crowd_atlas.py -- <character.gltf> <UAL1.glb> <UAL2.glb> <hair.gltf> <out dir>

Sports games draw big crowds as impostors: pre-rendered cards, thousands of them instanced
on the GPU. This renders the Quaternius base character (CC0) in Quaternius animation poses
(CC0): two seated, two standing, four celebrating. Two atlases come out:
  crowd_color.png  the fan lit from above, shirt rendered white so it can be tinted
  crowd_mask.png   red = shirt, green = skin, blue = trousers (the Studio tints each per fan)
Everything here is CC0, so the atlases are committed with the Studio.
"""

import sys
from pathlib import Path

import bpy
import numpy as np
from mathutils import Vector

argv = sys.argv[sys.argv.index("--") + 1 :]
char_path, ual1, ual2, hair_path, out = (Path(a) for a in argv[:5])
out.mkdir(parents=True, exist_ok=True)

POSES = [  # (action, seconds into it)
    ("Sitting_Idle_Loop", 0.4),
    ("Sitting_Talking_Loop", 1.2),
    ("Idle_Loop", 0.6),
    ("Idle_FoldArms_Loop", 0.8),
    ("Yes", 0.9),
    ("Jump_Loop", 0.4),
    ("Dance_Loop", 0.25),
    ("Dance_Loop", 0.75),
]
CARD_W, CARD_H = 160, 320

bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
scene.render.fps = 30


def imp(path: Path) -> list[bpy.types.Object]:
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=str(path))
    return [o for o in bpy.data.objects if o not in before]


char = imp(char_path)
arm = next(o for o in char if o.type == "ARMATURE")
body = next(o for o in char if o.type == "MESH" and "SuperHero" in o.name)
hair = imp(hair_path)
hair_arm = next((o for o in hair if o.type == "ARMATURE"), None)
for o in hair:
    if o.type == "MESH":
        for m in o.modifiers:
            if m.type == "ARMATURE":
                m.object = arm
        o.parent = arm
if hair_arm:
    bpy.data.objects.remove(hair_arm, do_unlink=True)
actions = {}
for lib in (ual1, ual2):
    for o in imp(lib):
        if o.type == "ARMATURE" and o.animation_data:
            for t in o.animation_data.nla_tracks:
                for s in t.strips:
                    if s.action:
                        s.action.use_fake_user = True
                        actions[s.action.name] = s.action
        bpy.data.objects.remove(o, do_unlink=True)
for a in bpy.data.actions:
    a.use_fake_user = True
    actions.setdefault(a.name, a)
print("actions available:", sorted(n for n in actions if any(p[0] in n for p in POSES)))


def find_action(name: str) -> bpy.types.Action:
    return next(a for n, a in actions.items() if n == name or n.startswith(name))


# body material: the skin texture, with the shirt region (bind-pose height and width, the same
# bands the Studio's kit shader uses) rendered white for tinting
mat = body.active_material
nt = mat.node_tree
bsdf = next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED")
skin_link = bsdf.inputs["Base Color"].links[0] if bsdf.inputs["Base Color"].links else None
skin_out = skin_link.from_socket if skin_link else None
tc = nt.nodes.new("ShaderNodeTexCoord")
sep = nt.nodes.new("ShaderNodeSeparateXYZ")
nt.links.new(tc.outputs["Generated"], sep.inputs[0])
# generated coords run 0..1 over the bind-pose box: z is height, x spans the T-pose arms
math_nodes = []


def node_math(op, a, b=None):
    n = nt.nodes.new("ShaderNodeMath")
    n.operation = op
    if isinstance(a, (int, float)):
        n.inputs[0].default_value = a
    else:
        nt.links.new(a, n.inputs[0])
    if b is not None:
        if isinstance(b, (int, float)):
            n.inputs[1].default_value = b
        else:
            nt.links.new(b, n.inputs[1])
    return n.outputs[0]


h = sep.outputs["Z"]
side = node_math("ABSOLUTE", node_math("SUBTRACT", sep.outputs["X"], 0.5))
torso = node_math(
    "MULTIPLY",
    node_math("MULTIPLY", node_math("GREATER_THAN", h, 0.555), node_math("LESS_THAN", h, 0.815)),
    node_math("LESS_THAN", side, 0.15),
)
sleeve = node_math(
    "MULTIPLY",
    node_math("MULTIPLY", node_math("GREATER_THAN", h, 0.70), node_math("LESS_THAN", h, 0.815)),
    node_math("LESS_THAN", side, 0.24),
)
shirt = node_math("MAXIMUM", torso, sleeve)
legs = node_math("MULTIPLY", node_math("GREATER_THAN", h, 0.06), node_math("LESS_THAN", h, 0.555))
shirt = node_math("MAXIMUM", shirt, legs)  # fans wear trousers: also rendered white, tinted per fan
mix = nt.nodes.new("ShaderNodeMix")
mix.data_type = "RGBA"
nt.links.new(shirt, mix.inputs["Factor"])
if skin_out:
    nt.links.new(skin_out, mix.inputs[6])
mix.inputs[7].default_value = (0.92, 0.92, 0.92, 1)
nt.links.new(mix.outputs[2], bsdf.inputs["Base Color"])
colour_link_target = bsdf

# mask material: emission red = shirt, green = everything else on the body (skin)
mask = bpy.data.materials.new("Mask")
mask.use_nodes = True
mn = mask.node_tree
mn.nodes.clear()
mtc = mn.nodes.new("ShaderNodeTexCoord")
msep = mn.nodes.new("ShaderNodeSeparateXYZ")
mn.links.new(mtc.outputs["Generated"], msep.inputs[0])


def mmath(op, a, b=None):
    n = mn.nodes.new("ShaderNodeMath")
    n.operation = op
    for i, v in enumerate((a, b)):
        if v is None:
            continue
        if isinstance(v, (int, float)):
            n.inputs[i].default_value = v
        else:
            mn.links.new(v, n.inputs[i])
    return n.outputs[0]


mh = msep.outputs["Z"]
mside = mmath("ABSOLUTE", mmath("SUBTRACT", msep.outputs["X"], 0.5))
mt = mmath(
    "MULTIPLY",
    mmath("MULTIPLY", mmath("GREATER_THAN", mh, 0.555), mmath("LESS_THAN", mh, 0.815)),
    mmath("LESS_THAN", mside, 0.15),
)
ms = mmath(
    "MULTIPLY",
    mmath("MULTIPLY", mmath("GREATER_THAN", mh, 0.70), mmath("LESS_THAN", mh, 0.815)),
    mmath("LESS_THAN", mside, 0.24),
)
mshirt = mmath("MAXIMUM", mt, ms)
mlegs = mmath("MULTIPLY", mmath("GREATER_THAN", mh, 0.06), mmath("LESS_THAN", mh, 0.555))
comb = mn.nodes.new("ShaderNodeCombineXYZ")
mn.links.new(mshirt, comb.inputs[0])
mn.links.new(mmath("SUBTRACT", mmath("SUBTRACT", 1.0, mshirt), mlegs), comb.inputs[1])
mn.links.new(mlegs, comb.inputs[2])
emit = mn.nodes.new("ShaderNodeEmission")
mn.links.new(comb.outputs[0], emit.inputs["Color"])
outn = mn.nodes.new("ShaderNodeOutputMaterial")
mn.links.new(emit.outputs[0], outn.inputs["Surface"])
black = bpy.data.materials.new("Black")
black.use_nodes = True
black.node_tree.nodes.clear()
be = black.node_tree.nodes.new("ShaderNodeEmission")
be.inputs["Color"].default_value = (0, 0, 0, 1)
bo = black.node_tree.nodes.new("ShaderNodeOutputMaterial")
black.node_tree.links.new(be.outputs[0], bo.inputs["Surface"])

# camera: orthographic, front on, framing a standing fan from feet to above raised hands
cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
scene.collection.objects.link(cam)
scene.camera = cam
cam.data.type = "ORTHO"
cam.data.ortho_scale = 2.4
forward = None
sun = bpy.data.objects.new("sun", bpy.data.lights.new("sun", "SUN"))
sun.data.energy = 3.5
scene.collection.objects.link(sun)
fill = bpy.data.objects.new("fill", bpy.data.lights.new("fill", "SUN"))
fill.data.energy = 1.2
scene.collection.objects.link(fill)
scene.render.engine = "BLENDER_EEVEE"
scene.render.film_transparent = True
scene.render.resolution_x, scene.render.resolution_y = CARD_W, CARD_H
scene.render.image_settings.file_format = "PNG"
scene.render.image_settings.color_mode = "RGBA"
scene.view_settings.view_transform = "Standard"

meshes = [o for o in bpy.data.objects if o.type == "MESH"]
cards_color, cards_mask = [], []
for i, (name, sec) in enumerate(POSES):
    act = find_action(name)
    arm.animation_data_create()
    arm.animation_data.action = act
    if hasattr(arm.animation_data, "action_slot") and act.slots:
        arm.animation_data.action_slot = act.slots[0]
    scene.frame_set(int(round(sec * 30)))
    if forward is None:
        heel = arm.matrix_world @ arm.pose.bones["foot_l"].head
        toe = arm.matrix_world @ arm.pose.bones["ball_l"].head
        f = toe - heel
        f.z = 0
        forward = f.normalized()
    pelvis = arm.matrix_world @ arm.pose.bones["pelvis"].head
    target = Vector((pelvis.x, pelvis.y, 1.05))
    cam.location = target + forward * 6
    cam.rotation_euler = (target - cam.location).to_track_quat("-Z", "Y").to_euler()
    sun.rotation_euler = (forward * 1 + Vector((0, 0, 2.5))).to_track_quat("-Z", "Y").to_euler()
    sun.rotation_euler = (
        (Vector((0, 0, 0)) - (forward * 1.5 + Vector((0.6, 0, 2.5)))).to_track_quat("-Z", "Y").to_euler()
    )
    fill.rotation_euler = (
        (Vector((0, 0, 0)) - (forward * 2 + Vector((-1, 0, 0.5)))).to_track_quat("-Z", "Y").to_euler()
    )
    for kind, cards in (("color", cards_color), ("mask", cards_mask)):
        saved = {}
        if kind == "mask":
            for o in meshes:
                saved[o.name] = [s.material for s in o.material_slots]
                for s in o.material_slots:
                    s.material = mask if o == body else black
        path = out / f"_card_{i}_{kind}.png"
        scene.render.filepath = str(path)
        bpy.ops.render.render(write_still=True)
        img = bpy.data.images.load(str(path))
        px = np.array(img.pixels[:], dtype=np.float32).reshape(CARD_H, CARD_W, 4)
        cards.append(px)
        bpy.data.images.remove(img)
        path.unlink()
        if kind == "mask":
            for o in meshes:
                for s, m in zip(o.material_slots, saved[o.name], strict=False):
                    s.material = m
    print("posed", i, name)


def save_atlas(cards, name):
    atlas = np.concatenate(cards, axis=1)  # one row of cards, left to right
    img = bpy.data.images.new(name, atlas.shape[1], atlas.shape[0], alpha=True)
    img.pixels = atlas.ravel()
    img.filepath_raw = str(out / f"{name}.png")
    img.file_format = "PNG"
    img.save()


save_atlas(cards_color, "crowd_color")
save_atlas(cards_mask, "crowd_mask")
print("atlases written", len(cards_color))
