// Players: animated footballers driven by the tracking feed and the event stream.
//
// Locomotion is a directional blend space (forward, diagonals, strafes, backpedal) with
// forward gears (jog, run, sprint). All locomotion clips share one normalised phase that
// advances with the player's real speed divided by the blended stride length, so feet
// plant instead of sliding (a sync group, as game engines do it).
//
// Facing follows how footballers move: they watch the ball while repositioning and
// backpedal or side-step to keep it in view, and only turn their back when sprinting.
//
// Actions (pass, shot, header, tackle, save, throw-in...) come from the event stream. An
// action's clip time is set from match time, aligned so its measured contact frame lands
// exactly on the event: deterministic, so scrubbing and video export reproduce exactly.
import * as THREE from "three";
import { clone as cloneSkinned } from "three/addons/utils/SkeletonUtils.js";
import { actionFor, GEARS, IDLE, LOCOMOTION } from "./library.js";

const HEIGHT = 1.82;
const FADE_IN = 0.12;
const FADE_OUT = 0.3;
const TURN_RATE = 7; // rad/s, body yaw
const SPRINT_FACING = 4.3; // above this speed players face where they run

// Celebrations a scorer can make, beyond the library's one victory clip, posed in code by aiming
// the skeleton's limbs as games do for aim poses: "leap" jumps with a half turn and lands arms
// swept down and out, chest out, feet planted wide; "aeroplane" runs to the corner arms out wide.
// A scorer's goals of a match take the styles in turn, from a start his name sets.
export const CELEBRATIONS = ["leap", "victory", "aeroplane"];
export function celebrationStyle(name, goalsBefore = 0) {
  let h = 0;
  for (const ch of name || "") h += ch.charCodeAt(0);
  return CELEBRATIONS[(h + goalsBefore) % CELEBRATIONS.length];
}
const LEAP = { start: 0.15, up: 0.5, height: 0.55, hold: 1.4 }; // s after arriving, s in the air, m, s held
// when a leaping scorer lets the landing go and celebrates on (the victory clip takes over)
export const LEAP_END = LEAP.start + LEAP.up + LEAP.hold;
const _a = new THREE.Vector3();
const _b = new THREE.Vector3();
const _turn = new THREE.Quaternion();
const _world = new THREE.Quaternion();
const _parent = new THREE.Quaternion();
const _dir = new THREE.Vector3();

// turn a bone so that it points (towards its child joint) along a world direction, by weight w
function aim(bone, child, dir, w) {
  if (!bone || !child || w <= 0) return;
  bone.getWorldPosition(_a);
  child.getWorldPosition(_b);
  _turn.setFromUnitVectors(_b.sub(_a).normalize(), dir);
  bone.getWorldQuaternion(_world).premultiply(_turn);
  bone.parent.getWorldQuaternion(_parent).invert();
  bone.quaternion.slerp(_parent.multiply(_world), w);
  bone.updateMatrixWorld(true);
}

// Kit painted over the textured athlete. Regions are measured on the bind pose (the
// un-skinned position), so they follow the body as it animates: boots, socks, shorts,
// shirt with short sleeves and collar; skin keeps the character's texture, tinted to the
// player's tone. On the back of the shirt a decal carries the name and number, projected
// from the bind pose too, as broadcast close-ups demand.
function kitMaterial(source, colours, frame, decal) {
  const mat = source.clone();
  const u = {
    uShirt: { value: new THREE.Color(colours.shirt) },
    uTrim: { value: new THREE.Color(colours.trim) },
    uShorts: { value: new THREE.Color(colours.shorts) },
    uSocks: { value: new THREE.Color(colours.socks) },
    uSkin: { value: new THREE.Color(colours.skin) },
    uBoots: { value: new THREE.Color(colours.boots) },
    uMinY: { value: frame.minY },
    uSpanY: { value: frame.spanY },
    uHalfW: { value: frame.halfW },
    uCenterX: { value: frame.centerX },
    uFront: { value: frame.front },
    uDecal: { value: decal },
  };
  mat.userData.kit = u;
  mat.onBeforeCompile = (shader) => {
    Object.assign(shader.uniforms, u);
    shader.vertexShader = shader.vertexShader
      .replace("#include <common>", "#include <common>\nvarying vec3 vBind;\nvarying vec3 vBindN;")
      .replace("#include <begin_vertex>", "#include <begin_vertex>\nvBind = position;\nvBindN = normal;");
    shader.fragmentShader = shader.fragmentShader
      .replace(
        "#include <common>",
        `#include <common>
         varying vec3 vBind;
         varying vec3 vBindN;
         uniform vec3 uShirt, uTrim, uShorts, uSocks, uSkin, uBoots;
         uniform float uMinY, uSpanY, uHalfW, uCenterX, uFront;
         uniform sampler2D uDecal;
         float kitMask;`,
      )
      .replace(
        "#include <map_fragment>",
        `#include <map_fragment>
         float h = (vBind.y - uMinY) / uSpanY;
         float side = abs(vBind.x - uCenterX) / uHalfW;
         float back = -uFront * vBindN.z;
         vec3 kit = vec3(-1.0);
         if (h < 0.055) kit = uBoots;
         else if (h < 0.27) kit = uSocks;
         else if (h < 0.29) kit = uTrim;
         if (h >= 0.44 && h < 0.565) kit = uShorts;
         if (h >= 0.555 && h < 0.815 && side < 0.30) kit = uShirt;
         if (h >= 0.70 && h < 0.815 && side >= 0.30 && side < 0.48) kit = uShirt;          // sleeves
         if (h >= 0.70 && h < 0.712 && side >= 0.46 && side < 0.48) kit = uTrim;           // cuffs
         if (h >= 0.80 && h < 0.815 && side < 0.12) kit = uTrim;                            // collar
         kitMask = kit.x < 0.0 ? 0.0 : 1.0;
         if (kitMask > 0.5) {
           // name and number on the back of the shirt
           if (back > 0.2 && h > 0.60 && h < 0.79 && side < 0.22) {
             vec2 uv = vec2(0.5 - uFront * (vBind.x - uCenterX) / (0.44 * uHalfW), 1.0 - (h - 0.60) / 0.19); // read from behind; canvas rows run top-down
             vec4 d = texture2D(uDecal, uv);
             kit = mix(kit, d.rgb, d.a);
           }
           // fabric: a soft weave so the shirt never reads as flat paint
           float weave = 0.96 + 0.04 * sin(vBind.y * 900.0) * sin(vBind.x * 900.0);
           diffuseColor.rgb = kit * weave;
         } else {
           // skin: the character's texture tinted to the player's tone
           float lum = dot(diffuseColor.rgb, vec3(0.299, 0.587, 0.114));
           diffuseColor.rgb = mix(diffuseColor.rgb, uSkin * (0.55 + 0.9 * lum), 0.82);
         }`,
      )
      .replace(
        "#include <roughnessmap_fragment>",
        `#include <roughnessmap_fragment>
         roughnessFactor = mix(roughnessFactor, 0.78, kitMask);`,
      );
  };
  mat.customProgramCacheKey = () => "matchcut-footballer-kit";
  return mat;
}

// Rocketbox footballers (realistic athletes, MIT): the kit is painted by a baked mask that
// names each texel's garment (shirt, shorts, socks, boots, trim) and marks the back's name
// panel; a fitted UV-to-panel map prints the name and number sharp at any distance. Folds come
// from the normal map; skin keeps the photographic texture, tinted to the player's tone.
const SKIN_TINT = `
  vec3 skinTone(vec3 tex, vec3 tone) {
    float lum = dot(tex, vec3(0.299, 0.587, 0.114));
    return mix(tex, tone * (0.42 + 1.15 * lum), 0.5);
  }`;
function rocketboxKit(source, colours, kit, decal) {
  const mat = source.clone();
  const [a, b, c, d, e, f] = kit.decal;
  const u = {
    uShirt: { value: new THREE.Color(colours.shirt) },
    uTrim: { value: new THREE.Color(colours.trim) },
    uShorts: { value: new THREE.Color(colours.shorts) },
    uSocks: { value: new THREE.Color(colours.socks) },
    uSkin: { value: new THREE.Color(colours.skin) },
    uBoots: { value: new THREE.Color(colours.boots) },
    uMask: { value: kit.mask },
    uDecal: { value: decal },
    uDecalU: { value: new THREE.Vector3(a, b, c) },
    uDecalV: { value: new THREE.Vector3(d, e, f) },
  };
  mat.userData.kit = u;
  mat.roughness = 0.78;
  mat.onBeforeCompile = (shader) => {
    Object.assign(shader.uniforms, u);
    shader.fragmentShader = shader.fragmentShader
      .replace(
        "#include <common>",
        `#include <common>
         uniform vec3 uShirt, uTrim, uShorts, uSocks, uSkin, uBoots, uDecalU, uDecalV;
         uniform sampler2D uMask, uDecal;
         ${SKIN_TINT}`,
      )
      .replace(
        "#include <map_fragment>",
        `#include <map_fragment>
         vec4 km = texture2D(uMask, vMapUv);
         int region = int(km.r * 255.0 / 40.0 + 0.5);
         vec3 tex = diffuseColor.rgb;
         if (region == 1 || region == 2 || region == 3 || region == 5) {
           vec3 kit = region == 1 ? uShirt : region == 2 ? uShorts : region == 3 ? uSocks : uTrim;
           if (km.a > 0.5) {
             vec3 q = vec3(vMapUv, 1.0);
             vec2 p = vec2(dot(uDecalU, q), dot(uDecalV, q));
             if (p.x >= 0.0 && p.x <= 1.0 && p.y >= 0.0 && p.y <= 1.0) {
               vec4 dc = texture2D(uDecal, vec2(p.x, 1.0 - p.y)); // canvas rows run top-down
               kit = mix(kit, dc.rgb, dc.a);
             }
           }
           diffuseColor.rgb = kit;
         } else if (region == 4) {
           float lum = dot(tex, vec3(0.299, 0.587, 0.114));
           diffuseColor.rgb = mix(tex, uBoots * (0.3 + 0.9 * lum), 0.6);
         } else {
           diffuseColor.rgb = skinTone(tex, uSkin);
         }`,
      );
  };
  mat.customProgramCacheKey = () => "matchcut-rocketbox-kit";
  return mat;
}
function rocketboxSkin(source, tone) {
  const mat = source.clone();
  const u = { uSkin: { value: new THREE.Color(tone) } };
  mat.roughness = 0.55;
  mat.onBeforeCompile = (shader) => {
    Object.assign(shader.uniforms, u);
    shader.fragmentShader = shader.fragmentShader
      .replace("#include <common>", `#include <common>\nuniform vec3 uSkin;\n${SKIN_TINT}`)
      .replace("#include <map_fragment>", "#include <map_fragment>\ndiffuseColor.rgb = skinTone(diffuseColor.rgb, uSkin);");
  };
  mat.customProgramCacheKey = () => "matchcut-rocketbox-skin";
  return mat;
}
const toneLuma = (hex) => {
  const c = new THREE.Color(hex);
  return 0.299 * c.r + 0.587 * c.g + 0.114 * c.b;
};

function nameplate(name, num, colour) {
  const cv = document.createElement("canvas");
  cv.width = 256;
  cv.height = 256;
  const c = cv.getContext("2d");
  c.fillStyle = colour;
  c.textAlign = "center";
  c.textBaseline = "alphabetic";
  // as real shirts carry it: the name across the shoulders, the number below
  c.font = "800 34px 'Big Shoulders Display', 'Arial Narrow', sans-serif";
  c.fillText(String(name).toUpperCase(), 128, 44);
  c.font = "900 170px 'Big Shoulders Display', 'Arial Narrow', sans-serif";
  c.fillText(String(num), 128, 214);
  const t = new THREE.CanvasTexture(cv);
  t.colorSpace = THREE.SRGBColorSpace;
  t.flipY = false;
  return t;
}

// bind-pose frame of a body mesh: height range, width, and which way the face points
function bodyFrame(geometry) {
  geometry.computeBoundingBox();
  const bb = geometry.boundingBox;
  const pos = geometry.attributes.position;
  const minY = bb.min.y;
  const spanY = bb.max.y - bb.min.y;
  let zSum = 0;
  let n = 0;
  for (let i = 0; i < pos.count; i += 3) {
    if ((pos.getY(i) - minY) / spanY > 0.9) {
      zSum += pos.getZ(i) - (bb.min.z + bb.max.z) / 2;
      n++;
    }
  }
  // the face (nose, brow) sits forward of the skull's centre
  return {
    minY, spanY, halfW: (bb.max.x - bb.min.x) / 2, centerX: (bb.min.x + bb.max.x) / 2,
    front: n && zSum / n < 0 ? -1 : 1,
  };
}

const SKINS = [0x5a3825, 0x8d5524, 0xc68642, 0xe0ac69, 0xf1c27d, 0x6b4423, 0x3d2416, 0xa87454];
const HAIR_COLOURS = [0x1a1210, 0x2b1d14, 0x3b2a1f, 0x111111, 0x6a4a2f, 0xb08d57];
const HAIRSTYLES = [["Hair_Buzzed"], ["Hair_SimpleParted"], ["Hair_Buzzed", "Hair_Beard"], ["Hair_Long"], ["Hair_Buns"], ["Hair_SimpleParted", "Hair_Beard"], ["Hair_BuzzedFemale"]];
const wrap = (a) => Math.atan2(Math.sin(a), Math.cos(a));

export class Player {
  constructor(lib, kit, { seed, keeper, name = "", num = "" }) {
    this.lib = lib;
    this.keeper = keeper;
    this.root = new THREE.Group();
    const body = cloneSkinned(lib.scene);
    this.root.add(body);
    const colours = {
      shirt: kit.primary,
      trim: kit.secondary,
      shorts: kit.shorts ?? kit.secondary,
      socks: kit.socks ?? kit.primary,
      skin: SKINS[(seed * 5) % SKINS.length],
      boots: [0x111111, 0xf4f4f4, 0x1e88e5, 0xff5722, 0x111111][seed % 5],
    };
    this.numberColour = kit.number ?? kit.secondary;
    this.decal = nameplate(name, num, this.numberColour);
    const style = HAIRSTYLES[(seed * 3) % HAIRSTYLES.length];
    const hairTint = new THREE.Color(HAIR_COLOURS[(seed * 7) % HAIR_COLOURS.length]);
    // Rocketbox: two real footballers on one skeleton; darker tones take the body whose face and
    // hair were made for them, so tinting stays gentle and natural
    const variant = lib.rig === "rocketbox" ? (toneLuma(colours.skin) < 0.42 ? "m300" : "m301") : null;
    const owner = (o) => {
      for (let n = o; n; n = n.parent) if (/^FOOTBALLER_/.test(n.name)) return n.name.slice(11, 15);
      return null;
    };
    body.traverse((o) => {
      if (!o.isMesh) return;
      o.castShadow = true;
      o.frustumCulled = false; // skinned bounds lag the pose; 22 players are cheap to draw
      if (variant) {
        const code = owner(o);
        if (code && code !== variant) {
          o.visible = false;
          return;
        }
        const mname = o.material?.name ?? "";
        if (/_body$/.test(mname) && lib.kits?.[variant]) {
          o.material = rocketboxKit(o.material, colours, lib.kits[variant], this.decal);
        } else if (/_head$/.test(mname)) {
          o.material = rocketboxSkin(o.material, colours.skin);
        } else if (/opacity/.test(mname)) {
          o.material = o.material.clone(); // hair cards: cut out, never sorted glass
          o.material.alphaTest = 0.45;
          o.material.transparent = false;
          o.material.side = THREE.DoubleSide;
        }
        return;
      }
      if (/^HAIR_/.test(o.name)) {
        const keep = style.some((h) => o.name.includes(h)) || /Eyebrows_Regular/.test(o.name);
        o.visible = keep;
        if (keep) {
          o.material = o.material.clone();
          o.material.color = hairTint.clone().multiplyScalar(2.2);
        }
      } else if (/SuperHero|Body|Surface/i.test(o.name) && o.isSkinnedMesh) {
        o.material = kitMaterial(o.material, colours, bodyFrame(o.geometry), this.decal);
      } else if (/Eyebrows/.test(o.name)) {
        o.material = o.material.clone();
        o.material.color = hairTint.clone().multiplyScalar(2.2);
      }
    });
    // size from the skeleton, not the mesh: compressed meshes store normalised positions
    body.updateMatrixWorld(true);
    let headY = null;
    let footY = Infinity;
    const p = new THREE.Vector3();
    body.traverse((o) => {
      if (!o.isBone) return;
      o.getWorldPosition(p);
      if (/Head$/i.test(o.name)) headY = p.y;
      if (/(foot|ball|toe)/i.test(o.name)) footY = Math.min(footY, p.y);
    });
    const span = headY !== null && Number.isFinite(footY) ? (headY - footY) / 0.9 : null; // the head bone sits ~10% below the crown
    if (span) body.scale.multiplyScalar(HEIGHT / span);
    body.updateMatrixWorld(true);
    let minY = Infinity;
    body.traverse((o) => {
      if (o.isBone && /(foot|ball|toe)/i.test(o.name)) minY = Math.min(minY, o.getWorldPosition(p).y);
    });
    if (Number.isFinite(minY)) body.position.y -= minY - 0.03; // soles on the turf
    // which way the model faces, measured from its own feet (heel to toe), so any character works
    const heel = new THREE.Vector3();
    const toe = new THREE.Vector3();
    let found = 0;
    body.traverse((o) => {
      if (!o.isBone) return;
      if (/^foot_l$|LeftFoot$|_L_Foot$/i.test(o.name)) {
        o.getWorldPosition(heel);
        found++;
      }
      if (/^ball_l$|LeftToeBase$|_L_Toe0$/i.test(o.name)) {
        o.getWorldPosition(toe);
        found++;
      }
    });
    const fwd = toe.sub(heel);
    this.yawOffset = found === 2 && Math.hypot(fwd.x, fwd.z) > 1e-4 ? Math.atan2(fwd.x, fwd.z) : 0;
    // the bones that strike the ball, by the library's generic names
    const STRIKER = {
      foot_r: /^foot_r$|RightFoot$|_R_Foot$/i, foot_l: /^foot_l$|LeftFoot$|_L_Foot$/i,
      head: /^head$|(^|_)Head$/i, hand_r: /^hand_r$|RightHand$|_R_Hand$/i, hand_l: /^hand_l$|LeftHand$|_L_Hand$/i,
    };
    this.strikers = {};
    body.traverse((o) => {
      if (!o.isBone) return;
      for (const [k, re] of Object.entries(STRIKER)) if (!this.strikers[k] && re.test(o.name)) this.strikers[k] = o;
    });
    this.strike = null; // { bone, w }: the ball belongs on this bone around an action's contact frame
    this.hands = [];
    body.traverse((o) => {
      if (o.isBone && /^hand_[lr]$|(Left|Right)Hand$|_[LR]_Hand$/i.test(o.name)) this.hands.push(o);
    });
    this.body = body;
    this.mixer = new THREE.AnimationMixer(body);
    const clip = (n) => lib.clips.get(n);
    const make = (name) => {
      const c = clip(name);
      if (!c) return null;
      const a = this.mixer.clipAction(c);
      a.play();
      a.setEffectiveWeight(0);
      a.timeScale = 0; // times are set explicitly every frame
      return a;
    };
    this.idle = make(keeper ? IDLE.keeper : IDLE.outfield) ?? make("Idle_Loop");
    this.loco = LOCOMOTION.map((l) => ({ ...l, action: make(l.clip) })).filter((l) => l.action);
    this.gears = GEARS.map((g) => ({ ...g, action: make(g.clip) })).filter((g) => g.action);
    this.cc0 = lib.kind !== "football";
    if (this.cc0) {
      // CC0 fallback: forward gaits only
      this.loco = [{ clip: "Jog_Fwd_Loop", dir: 0, speed: 3.8, action: make("Jog_Fwd_Loop") }];
      this.gears = [{ clip: "Sprint_Loop", speed: 7, action: make("Sprint_Loop") }];
    }
    // limbs a celebration poses: [joint, the joint it points to] for each segment
    const bone = (re) => {
      let found = null;
      body.traverse((o) => {
        if (!found && o.isBone && re.test(o.name)) found = o;
      });
      return found;
    };
    const chain = (side, names) => names.map((n) => bone(new RegExp(`${side}[ _]${n}$`, "i")));
    this.limbs = {
      L: { arm: chain("L", ["UpperArm", "Forearm", "Hand"]), leg: chain("L", ["Thigh", "Calf", "Foot"]) },
      R: { arm: chain("R", ["UpperArm", "Forearm", "Hand"]), leg: chain("R", ["Thigh", "Calf", "Foot"]) },
    };
    // the gait of a player running with the ball at his feet (body over the ball, short steps)
    this.dribbleGait = this.cc0 ? null : make("dribble");
    this.dribbleStride = (lib.meta?.dribble?.root_speed ?? 2.4) * (this.dribbleGait?.getClip().duration ?? 1.7);
    this.actions = new Map(); // clip name -> AnimationAction (created on first use)
    this.phase = (seed * 0.137) % 1;
    this.strides = 0;
    this.heading = 0;
    this.speed = 0;
    this.current = null; // { action, start, contact, duration, face }
  }

  // where the ball belongs when this player controls it: in the gloves after a catch,
  // otherwise just ahead of his feet in the direction he faces
  ballSpot(out) {
    if (this.catching && this.hands.length) {
      const a = this.hands[0].getWorldPosition(new THREE.Vector3());
      const b = this.hands.at(-1).getWorldPosition(new THREE.Vector3());
      return out.copy(a).add(b).multiplyScalar(0.5);
    }
    return out.set(this.root.position.x + Math.sin(this.heading) * 0.42, 0.11, this.root.position.z + Math.cos(this.heading) * 0.42);
  }

  // where the striking bone meets the ball at an action's contact frame
  strikePoint(out) {
    const bone = this.strike?.bone;
    if (!bone) return this.ballSpot(out);
    bone.getWorldPosition(out);
    if (bone === this.strikers.head) return out;
    // the instep, not the ankle: a little ahead of the foot bone, at the ball's height
    out.x += Math.sin(this.heading) * 0.12;
    out.z += Math.cos(this.heading) * 0.12;
    out.y = Math.max(0.11, out.y);
    return out;
  }

  // a dribble as players do it: a touch on the stride pushes the ball out, it rolls ahead and
  // slows, the player catches it on the next stride. The offset follows the locomotion phase
  // (one touch per stride cycle, every other cycle at a sprint) and grows with speed.
  dribbleSpot(out, carried) {
    const s = this.speed;
    const u = s > 6 ? ((this.strides % 2) + this.phase) / 2 : this.phase;
    const reach = THREE.MathUtils.clamp(0.35 + s * 0.24, 0.6, 2.3);
    const ahead = 0.32 + (reach - 0.32) * Math.pow(Math.sin(Math.PI * u), 0.8) * carried;
    const side = 0.07 * Math.cos(Math.PI * u); // the touching foot's side, drifting to the middle
    out.set(
      this.root.position.x + Math.sin(this.heading) * ahead + Math.cos(this.heading) * side,
      0.11,
      this.root.position.z + Math.cos(this.heading) * ahead - Math.sin(this.heading) * side,
    );
    return out;
  }

  // a substitution puts a new player in this slot: new name and number on the shirt
  setIdentity(name, num) {
    if (this.identity === `${name}#${num}`) return;
    this.identity = `${name}#${num}`;
    const fresh = nameplate(name, num, this.numberColour);
    this.body.traverse((o) => {
      if (o.material?.userData?.kit) o.material.userData.kit.uDecal.value = fresh;
    });
    this.decal.dispose();
    this.decal = fresh;
  }

  _action(name) {
    if (!this.actions.has(name)) {
      const c = this.lib.clips.get(name);
      if (!c) return null;
      const a = this.mixer.clipAction(c);
      a.setLoop(THREE.LoopOnce, 1);
      a.clampWhenFinished = true;
      a.timeScale = 0;
      a.play();
      a.setEffectiveWeight(0);
      this.actions.set(name, a);
    }
    return this.actions.get(name);
  }

  // event: the feed row, or null; tMs: match time
  update({ x, z, vx, vz, ballX, ballZ, tMs, dt, event, snap, carrying = false, celebration = null }) {
    this.root.position.set(x, 0, z);
    const v = Math.hypot(vx, vz);
    this.speed = snap ? v : this.speed + (v - this.speed) * Math.min(1, dt * 8);
    const s = this.speed;

    // which way the body faces
    const toBall = Math.atan2(ballX - x, ballZ - z);
    const travel = Math.atan2(vx, vz);
    let target = toBall;
    if (s > SPRINT_FACING && !this.keeper) target = travel;
    else if (s > 1.2 && !this.keeper) {
      // repositioning: mostly watch the ball, lean towards travel when running forwards
      const between = wrap(travel - toBall);
      target = Math.abs(between) < Math.PI / 2 ? toBall + between * 0.5 : toBall;
    }

    // the on-ball action, if one covers this moment
    let actionWeight = 0;
    let act = null;
    let strike = null;
    let now = null; // the action playing and its clip time, for motion QA
    if (event) {
      const meta = this.lib.meta;
      const choice = actionFor(event, { keeper: this.keeper, speed: s, meta });
      const a = choice?.clip ? this._action(choice.clip) : null;
      if (a) {
        const m = meta[choice.clip] ?? { contact: 0.3, duration: a.getClip().duration };
        const local = (tMs - event[0]) / 1000 + (choice.stretch ?? m.contact); // seconds into the clip
        const dur = a.getClip().duration;
        // a beaten keeper moves only once he can react to the strike (event[4]), from mid-windup
        const since = choice.beaten ? (tMs - event[4]) / 1000 : local;
        if (since >= 0 && local >= 0 && local <= dur) {
          act = a;
          a.time = local;
          // motion QA: the clip, its time and contact, and whether it aims at a target (a shot, a pass)
          now = { clip: choice.clip, at: Math.round(local * 100) / 100, contact: choice.stretch ?? m.contact,
            aims: Boolean(choice.faceTarget && event[7] >= 0) };
          actionWeight = Math.min(1, since / FADE_IN, (dur - local) / FADE_OUT);
          // the ball is drawn onto the striking bone in the fifth of a second before contact,
          // and let go just after it, when the tracked ball takes over in flight
          const bone = this.strikers[m.contact_bone];
          const before = THREE.MathUtils.smoothstep(local, m.contact - 0.22, m.contact);
          const after = 1 - THREE.MathUtils.smoothstep(local, m.contact, m.contact + 0.05);
          strike = bone && !this.catching && !choice.beaten && !choice.offBall ? { bone, w: Math.min(before, after) } : null;
          if (choice.faceTarget && event[7] >= 0) {
            const tx = event[7] / 10 - 52.5;
            const tz = event[8] / 10 - 34;
            target = Math.atan2(tx - x, tz - z);
          } else if (choice.faceBall) {
            target = toBall; // a tackle goes in on the ball, even from a sprint
          }
        }
      }
    }
    this.strike = strike && strike.w > 0 ? strike : null;
    this.acting = Boolean(act);
    this.actionNow = now;
    for (const a of this.actions.values()) if (a !== act) a.setEffectiveWeight(0);
    if (act) act.setEffectiveWeight(actionWeight);

    const turn = wrap(target - this.heading);
    this.heading = snap ? target : this.heading + Math.sign(turn) * Math.min(Math.abs(turn), TURN_RATE * dt);
    if (now?.aims) now.off = Math.round(Math.abs(THREE.MathUtils.radToDeg(wrap(target - this.heading))));
    this.root.rotation.y = this.heading - this.yawOffset;
    this.catching = Boolean(act && this.keeper && event && event[1] === "save" && tMs >= event[0]);

    // locomotion blend space
    const moving = THREE.MathUtils.smoothstep(s, 0.25, 0.9);
    const rel = THREE.MathUtils.radToDeg(wrap(travel - this.heading));
    const weights = new Map();
    if (this.loco.length > 1) {
      const sorted = [...this.loco].sort((a, b) => a.dir - b.dir);
      const ring = [...sorted, { ...sorted[0], dir: sorted[0].dir + 360 }];
      const r = rel < sorted[0].dir ? rel + 360 : rel;
      for (let i = 0; i < ring.length - 1; i++) {
        const a = ring[i];
        const b = ring[i + 1];
        if (r >= a.dir && r <= b.dir) {
          const u = (r - a.dir) / (b.dir - a.dir);
          weights.set(a.action, (weights.get(a.action) ?? 0) + (1 - u));
          weights.set(b.action, (weights.get(b.action) ?? 0) + u);
          break;
        }
      }
    } else {
      weights.set(this.loco[0].action, 1);
    }
    // forward gears take over the forward share as speed rises past a jog
    const fwd = this.loco.find((l) => l.dir === 0);
    const fwdShare = weights.get(fwd.action) ?? 0;
    if (fwdShare > 0 && this.gears.length) {
      const pts = [fwd, ...this.gears];
      let placed = false;
      for (let i = 0; i < pts.length - 1 && !placed; i++) {
        if (s <= pts[i + 1].speed) {
          const u = THREE.MathUtils.clamp((s - pts[i].speed) / (pts[i + 1].speed - pts[i].speed), 0, 1);
          weights.set(pts[i].action, fwdShare * (1 - u));
          weights.set(pts[i + 1].action, (weights.get(pts[i + 1].action) ?? 0) + fwdShare * u);
          placed = true;
        }
      }
      if (!placed) {
        weights.set(fwd.action, 0);
        weights.set(pts.at(-1).action, fwdShare);
      }
    }

    // one phase for every locomotion clip, advanced by real speed over the blended stride
    let stride = 0;
    let total = 0;
    for (const l of [...this.loco, ...this.gears]) {
      const w = weights.get(l.action) ?? 0;
      stride += w * l.speed * l.action.getClip().duration;
      total += w;
    }
    stride = total > 0 ? stride / total : 2;
    // the ball at his feet, moving forwards at up to a fast jog: the dribbling gait takes over (a
    // sprint stays a run with long touches); it shares the stride phase, so touches stay in step
    const forwards = 1 - THREE.MathUtils.smoothstep(Math.abs(rel), 40, 70);
    const dribble =
      this.dribbleGait && carrying && !this.keeper
        ? THREE.MathUtils.smoothstep(s, 0.9, 1.6) * (1 - THREE.MathUtils.smoothstep(s, 4.8, 5.8)) * forwards
        : 0;
    stride = stride * (1 - dribble) + this.dribbleStride * dribble;
    if (!snap) {
      const next = (this.phase + (dt * Math.max(s, 0.6)) / Math.max(0.5, stride)) % 1;
      if (next < this.phase) this.strides++; // a completed stride cycle (sprint touches every other one)
      this.phase = next;
    }

    const locoWeight = (1 - actionWeight) * moving;
    for (const l of [...this.loco, ...this.gears]) {
      l.action.time = this.phase * l.action.getClip().duration;
      l.action.setEffectiveWeight(locoWeight * (1 - dribble) * (weights.get(l.action) ?? 0));
    }
    if (this.dribbleGait) {
      this.dribbleGait.time = this.phase * this.dribbleGait.getClip().duration;
      this.dribbleGait.setEffectiveWeight(locoWeight * dribble);
    }
    if (this.idle) {
      this.idle.time = (tMs / 1000) % this.idle.getClip().duration;
      this.idle.setEffectiveWeight((1 - actionWeight) * (1 - moving));
    }
    this.mixer.update(0);
    if (celebration) this.celebrate(celebration);
  }

  // a scorer's own celebration, posed over the clips: { style, cel } with cel the seconds since
  // he reached the corner (null while still running there)
  celebrate({ style, cel }) {
    const { L, R } = this.limbs;
    if (!L.arm[0] || !R.arm[0]) return;
    let spin = 0;
    let lift = 0;
    let arms = null; // [side, up, back] weights of each arm's direction
    let legs = 0; // how wide the feet are planted
    let weight = 1; // how much the pose overrides the clip underneath
    if (style === "aeroplane" && cel === null && this.speed > 1.5) {
      arms = [0.97, -0.08, 0.2];
    } else if (style === "leap" && cel !== null) {
      const air = THREE.MathUtils.clamp((cel - LEAP.start) / LEAP.up, 0, 1);
      lift = cel > LEAP.start && air < 1 ? LEAP.height * Math.sin(Math.PI * air) : 0;
      spin = Math.PI * THREE.MathUtils.smootherstep(air, 0, 1); // a half turn in the air
      const landed = THREE.MathUtils.smoothstep(cel, LEAP.start + LEAP.up, LEAP.start + LEAP.up + 0.12);
      // in the air the arms rise wide; landed they sweep down and back, chest out
      arms = [0.62, THREE.MathUtils.lerp(0.55, -0.72, landed), THREE.MathUtils.lerp(0, 0.32, landed)];
      // after the hold the pose lets go and the victory clip takes the body back, smoothly
      weight = 1 - THREE.MathUtils.smoothstep(cel, LEAP_END, LEAP_END + 0.35);
      legs = landed * weight;
      if (weight <= 0) return;
    }
    if (!arms) return;
    this.root.position.y += lift - legs * 0.035; // wide feet sit lower, the hips drop to the turf
    this.root.rotation.y += spin;
    this.root.updateMatrixWorld(true);
    const facing = this.heading + spin;
    const fwd = _b.set(Math.sin(facing), 0, Math.cos(facing)).clone();
    const right = new THREE.Vector3(-Math.cos(facing), 0, Math.sin(facing));
    for (const [side, limbs] of [[-1, L], [1, R]]) {
      const [s, up, back] = arms;
      _dir.copy(right).multiplyScalar(side * s).addScaledVector(fwd, -back).setY(up).normalize();
      aim(limbs.arm[0], limbs.arm[1], _dir, weight);
      aim(limbs.arm[1], limbs.arm[2], _dir, weight);
      if (legs > 0) {
        _dir.copy(right).multiplyScalar(side * 0.3).setY(-0.95).normalize();
        aim(limbs.leg[0], limbs.leg[1], _dir, legs);
        _dir.copy(right).multiplyScalar(side * 0.12).setY(-0.99).normalize();
        aim(limbs.leg[1], limbs.leg[2], _dir, legs);
      }
    }
  }
}
