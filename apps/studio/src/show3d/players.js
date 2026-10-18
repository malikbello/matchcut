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

function kitMaterial(source, colours, bounds, role) {
  const mat = new THREE.MeshStandardMaterial({ roughness: role === "joints" ? 0.45 : 0.72, metalness: role === "joints" ? 0.25 : 0 });
  const u = {
    uShirt: { value: new THREE.Color(colours.shirt) },
    uTrim: { value: new THREE.Color(colours.trim) },
    uShorts: { value: new THREE.Color(colours.shorts) },
    uSocks: { value: new THREE.Color(colours.socks) },
    uSkin: { value: new THREE.Color(colours.skin) },
    uBoots: { value: new THREE.Color(0x101010) },
    uMinY: { value: bounds.min.y },
    uSpanY: { value: bounds.max.y - bounds.min.y },
    uHalfW: { value: Math.max(1e-4, (bounds.max.x - bounds.min.x) / 2) },
    uJoints: { value: role === "joints" ? 1 : 0 },
  };
  mat.onBeforeCompile = (shader) => {
    Object.assign(shader.uniforms, u);
    shader.vertexShader = shader.vertexShader
      .replace("#include <common>", "#include <common>\nvarying vec3 vBind;")
      .replace("#include <begin_vertex>", "#include <begin_vertex>\nvBind = position;");
    shader.fragmentShader = shader.fragmentShader
      .replace(
        "#include <common>",
        `#include <common>
         varying vec3 vBind;
         uniform vec3 uShirt, uTrim, uShorts, uSocks, uSkin, uBoots;
         uniform float uMinY, uSpanY, uHalfW, uJoints;`,
      )
      .replace(
        "#include <color_fragment>",
        `#include <color_fragment>
         float h = (vBind.y - uMinY) / uSpanY;
         float side = abs(vBind.x) / uHalfW;
         vec3 kit = uSkin;
         if (h < 0.06) kit = uBoots;
         else if (h < 0.27) kit = uSocks;
         else if (h < 0.29) kit = uTrim;
         if (h >= 0.45 && h < 0.57) kit = uShorts;
         if (h >= 0.57 && h < 0.84 && side < 0.40) kit = uShirt;
         if (h >= 0.70 && h < 0.84 && side >= 0.18 && side < 0.40) kit = uShirt;
         if (h >= 0.81 && h < 0.84 && side < 0.16) kit = uTrim;
         if (uJoints > 0.5) kit = mix(kit, uTrim, 0.55) * 0.8;
         diffuseColor.rgb = kit;`,
      );
  };
  mat.customProgramCacheKey = () => `matchcut-kit-${role}`;
  return mat;
}

const SKINS = [0x8d5524, 0xc68642, 0xe0ac69, 0xf1c27d, 0x6b4423, 0x4a2c17, 0x3b2214];
const wrap = (a) => Math.atan2(Math.sin(a), Math.cos(a));

export class Player {
  constructor(lib, kit, { seed, keeper }) {
    this.lib = lib;
    this.keeper = keeper;
    this.root = new THREE.Group();
    const body = cloneSkinned(lib.scene);
    this.root.add(body);
    let bounds = null;
    body.traverse((o) => {
      if (o.isSkinnedMesh && !bounds) {
        o.geometry.computeBoundingBox();
        bounds = o.geometry.boundingBox.clone();
      }
    });
    const colours = {
      shirt: kit.primary,
      trim: kit.secondary,
      shorts: kit.shorts ?? kit.secondary,
      socks: kit.socks ?? kit.primary,
      skin: SKINS[seed % SKINS.length],
    };
    body.traverse((o) => {
      if (!o.isSkinnedMesh) return;
      const role = /joint/i.test(o.material?.name ?? o.name) ? "joints" : "body";
      o.material = kitMaterial(o.material, colours, bounds, role);
      o.castShadow = true;
      o.frustumCulled = false;
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
      if (/(Foot|Toe)/i.test(o.name)) footY = Math.min(footY, p.y);
    });
    const span = headY !== null && Number.isFinite(footY) ? (headY - footY) / 0.9 : null; // head bone sits ~10% below the crown
    if (span) body.scale.multiplyScalar(HEIGHT / span);
    body.updateMatrixWorld(true);
    let minY = Infinity;
    body.traverse((o) => {
      if (o.isBone && /(Foot|Toe)/i.test(o.name)) minY = Math.min(minY, o.getWorldPosition(p).y);
    });
    if (Number.isFinite(minY)) body.position.y -= minY - 0.04; // soles on the turf
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
    this.actions = new Map(); // clip name -> AnimationAction (created on first use)
    this.phase = (seed * 0.137) % 1;
    this.heading = 0;
    this.speed = 0;
    this.current = null; // { action, start, contact, duration, face }
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
  update({ x, z, vx, vz, ballX, ballZ, tMs, dt, event, snap }) {
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
    if (event) {
      const meta = this.lib.meta;
      const choice = actionFor(event, { keeper: this.keeper, speed: s, meta });
      const a = choice?.clip ? this._action(choice.clip) : null;
      if (a) {
        const m = meta[choice.clip] ?? { contact: 0.3, duration: a.getClip().duration };
        const local = (tMs - event[0]) / 1000 + m.contact; // seconds into the clip
        const dur = a.getClip().duration;
        if (local >= 0 && local <= dur) {
          act = a;
          a.time = local;
          actionWeight = Math.min(1, local / FADE_IN, (dur - local) / FADE_OUT);
          if (choice.faceTarget && event[7] >= 0) {
            const tx = event[7] / 10 - 52.5;
            const tz = event[8] / 10 - 34;
            target = Math.atan2(tx - x, tz - z);
          }
        }
      }
    }
    for (const a of this.actions.values()) if (a !== act) a.setEffectiveWeight(0);
    if (act) act.setEffectiveWeight(actionWeight);

    const turn = wrap(target - this.heading);
    this.heading = snap ? target : this.heading + Math.sign(turn) * Math.min(Math.abs(turn), TURN_RATE * dt);
    this.root.rotation.y = this.heading;

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
    if (!snap) this.phase = (this.phase + (dt * Math.max(s, 0.6)) / Math.max(0.5, stride)) % 1;

    const locoWeight = (1 - actionWeight) * moving;
    for (const l of [...this.loco, ...this.gears]) {
      l.action.time = this.phase * l.action.getClip().duration;
      l.action.setEffectiveWeight(locoWeight * (weights.get(l.action) ?? 0));
    }
    if (this.idle) {
      this.idle.time = (tMs / 1000) % this.idle.getClip().duration;
      this.idle.setEffectiveWeight((1 - actionWeight) * (1 - moving));
    }
    this.mixer.update(0);
  }
}
