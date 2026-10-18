// Players: one rigged CC0 mannequin, cloned 22 times, dressed in each club's kit and
// driven by the tracking feed. Locomotion blends idle, walk, jog and sprint by the
// player's real ground speed, and each clip's playback rate is matched to that speed
// so feet do not slide (the locomotion blend space games use). Heading follows the
// direction of travel, and turns to the ball when standing.
import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { clone as cloneSkinned } from "three/addons/utils/SkeletonUtils.js";
import { MeshoptDecoder } from "three/addons/libs/meshopt_decoder.module.js";

// clip, the ground speed (m/s) at which it plays at its authored rate
const GAIT = [
  ["Idle_Loop", 0],
  ["Walk_Loop", 1.5],
  ["Jog_Fwd_Loop", 3.8],
  ["Sprint_Loop", 7.0],
];
const HEIGHT = 1.8; // metres; the mannequin is scaled to a footballer

export async function loadRig(base) {
  const loader = new GLTFLoader().setMeshoptDecoder(MeshoptDecoder);
  const [players, moves] = await Promise.all([
    loader.loadAsync(`${base}/players.glb`),
    loader.loadAsync(`${base}/moves.glb`).catch(() => null),
  ]);
  const clips = new Map();
  for (const c of [...players.animations, ...(moves?.animations ?? [])]) clips.set(c.name, c);
  return { scene: players.scene, clips };
}

// Paint the kit by height on the bind pose: shirt, shorts, socks, boots, skin. The
// regions are computed in the shader from the un-skinned position, so they follow
// the body as it animates. No textures are needed.
function kitMaterial(source, kit, bounds) {
  const mat = source.clone();
  mat.map = null;
  mat.color = new THREE.Color(0xffffff);
  mat.roughness = 0.75;
  mat.metalness = 0;
  const uniforms = {
    uShirt: { value: new THREE.Color(kit.primary) },
    uTrim: { value: new THREE.Color(kit.secondary) },
    uShorts: { value: new THREE.Color(kit.shorts ?? kit.secondary) },
    uSocks: { value: new THREE.Color(kit.socks ?? kit.primary) },
    uSkin: { value: new THREE.Color(kit.skin) },
    uBoots: { value: new THREE.Color(0x111111) },
    uMinY: { value: bounds.min.y },
    uSpanY: { value: bounds.max.y - bounds.min.y },
    uHalfW: { value: (bounds.max.x - bounds.min.x) / 2 },
  };
  mat.onBeforeCompile = (shader) => {
    Object.assign(shader.uniforms, uniforms);
    shader.vertexShader = shader.vertexShader
      .replace("#include <common>", "#include <common>\nvarying vec3 vBind;")
      .replace("#include <begin_vertex>", "#include <begin_vertex>\nvBind = position;");
    shader.fragmentShader = shader.fragmentShader
      .replace(
        "#include <common>",
        `#include <common>
         varying vec3 vBind;
         uniform vec3 uShirt, uTrim, uShorts, uSocks, uSkin, uBoots;
         uniform float uMinY, uSpanY, uHalfW;`,
      )
      .replace(
        "#include <color_fragment>",
        `#include <color_fragment>
         float h = (vBind.y - uMinY) / uSpanY;          // 0 at the soles, 1 at the crown
         float side = abs(vBind.x) / uHalfW;           // 0 at the spine, 1 at the fingertips
         vec3 kit = uSkin;
         if (h < 0.05) kit = uBoots;
         else if (h < 0.28) kit = uSocks;
         else if (h < 0.30) kit = uTrim;                 // sock tops; knees and thighs stay skin
         if (h >= 0.44 && h < 0.56) kit = uShorts;
         if (h >= 0.56 && h < 0.83 && side < 0.42) kit = uShirt;
         if (h >= 0.80 && h < 0.83 && side < 0.2) kit = uTrim;   // collar
         if (h >= 0.70 && h < 0.83 && side >= 0.2 && side < 0.42) kit = uShirt; // short sleeves
         diffuseColor.rgb *= kit;`,
      );
  };
  mat.customProgramCacheKey = () => "matchcut-kit";
  return mat;
}

const SKINS = [0x8d5524, 0xc68642, 0xe0ac69, 0xf1c27d, 0x6b4423, 0x4a2c17];

export class Player {
  constructor(rig, kit, seed) {
    this.root = cloneSkinned(rig.scene);
    let bounds = null;
    this.root.traverse((o) => {
      if (o.isSkinnedMesh) {
        o.geometry.computeBoundingBox();
        bounds = o.geometry.boundingBox;
      }
    });
    const skin = SKINS[seed % SKINS.length];
    this.root.traverse((o) => {
      if (o.isSkinnedMesh) {
        o.material = kitMaterial(o.material, { ...kit, skin }, bounds);
        o.castShadow = true;
        o.frustumCulled = false; // skinned bounds lag the pose; 22 players are cheap to draw
      }
    });
    const box = new THREE.Box3().setFromObject(this.root);
    const s = HEIGHT / Math.max(0.01, box.max.y - box.min.y);
    this.root.scale.setScalar(s);
    this.mixer = new THREE.AnimationMixer(this.root);
    this.gaits = GAIT.map(([name, speed]) => {
      const clip = rig.clips.get(name);
      const action = this.mixer.clipAction(clip);
      action.play();
      action.setEffectiveWeight(name === "Idle_Loop" ? 1 : 0);
      return { action, speed };
    });
    for (const g of this.gaits) g.action.time = (seed * 0.137) % g.action.getClip().duration;
    this.heading = 0;
    this.speed = 0;
  }

  // place at (x, z) with ground velocity (vx, vz) in m/s; dt in seconds of match time
  update(x, z, vx, vz, ballX, ballZ, dt) {
    this.root.position.set(x, 0, z);
    const speed = Math.hypot(vx, vz);
    this.speed += (speed - this.speed) * Math.min(1, dt * 6);
    const target = this.speed > 0.6 ? Math.atan2(vx, vz) : Math.atan2(ballX - x, ballZ - z);
    let d = target - this.heading;
    d = Math.atan2(Math.sin(d), Math.cos(d));
    this.heading += d * Math.min(1, dt * 8);
    this.root.rotation.y = this.heading;
    // weights: piecewise-linear between neighbouring gaits
    const v = this.speed;
    for (let i = 0; i < this.gaits.length; i++) {
      const g = this.gaits[i];
      const lo = this.gaits[i - 1]?.speed ?? -1;
      const hi = this.gaits[i + 1]?.speed ?? Infinity;
      let w = 0;
      if (v <= g.speed) w = lo < 0 ? 1 : Math.max(0, (v - lo) / (g.speed - lo));
      else w = hi === Infinity ? 1 : Math.max(0, (hi - v) / (hi - g.speed));
      g.action.setEffectiveWeight(w);
      g.action.timeScale = g.speed > 0 ? THREE.MathUtils.clamp(v / g.speed, 0.6, 1.5) : 1;
    }
    this.mixer.update(dt);
  }
}
