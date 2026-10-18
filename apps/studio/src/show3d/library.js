// The animation library: loads the football clips (Mixamo soccer pack baked by the Blender
// pipeline, with measured speeds and contact times) and prepares them for the game layer:
// root motion is stripped so the tracking feed alone moves players, and clips are grouped
// into a locomotion blend space and an action set. Falls back to the CC0 library.
import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { MeshoptDecoder } from "three/addons/libs/meshopt_decoder.module.js";

// Directional locomotion: clip, direction of travel relative to facing (deg, + = right),
// authored ground speed (m/s; measured by the pipeline, or set for in-place clips).
export const LOCOMOTION = [
  { clip: "jog_forward", dir: 0, speed: null },
  { clip: "jog_forward_diagonal", dir: 45, speed: null },
  { clip: "jog_forward_diagonal_2", dir: -45, speed: null },
  { clip: "jog_strafe_right", dir: 90, speed: null },
  { clip: "jog_strafe_left", dir: -90, speed: null },
  { clip: "jog_backward_diagonal", dir: 135, speed: null },
  { clip: "jog_backward_diagonal_2", dir: -135, speed: null },
  { clip: "jog_backward", dir: 180, speed: null },
];
// forward gears above a jog: in-place clips, speeds set by eye against real footage
export const GEARS = [
  { clip: "running", speed: 5.4 },
  { clip: "fast_run", speed: 7.6 },
];
export const IDLE = { outfield: "offensive_idle", keeper: "goalkeeper_idle" };

function stripRootMotion(clip) {
  // keep the hips' height (crouches, dives) but remove travel on the ground plane
  for (const track of clip.tracks) {
    if (!/Hips\.position$/.test(track.name)) continue;
    const v = track.values;
    const x0 = v[0];
    const z0 = v[2];
    for (let i = 0; i < v.length; i += 3) {
      v[i] = x0;
      v[i + 2] = z0;
    }
  }
  return clip;
}

export async function loadLibrary({ privateBase, publicBase }) {
  const loader = new GLTFLoader().setMeshoptDecoder(MeshoptDecoder);
  try {
    const [gltf, meta] = await Promise.all([
      loader.loadAsync(`${privateBase}/football.glb`),
      fetch(`${privateBase}/football.meta.json`).then((r) => (r.ok ? r.json() : Promise.reject(new Error(r.status)))),
    ]);
    const clips = new Map(gltf.animations.map((c) => [c.name, stripRootMotion(c)]));
    for (const l of LOCOMOTION) l.speed = Math.max(1.6, meta[l.clip]?.root_speed ?? 2.4);
    return { kind: "football", scene: gltf.scene, clips, meta };
  } catch (err) {
    console.warn("football library unavailable, using the CC0 library", err);
    const gltf = await loader.loadAsync(`${publicBase}/players.glb`);
    return { kind: "cc0", scene: gltf.scene, clips: new Map(gltf.animations.map((c) => [c.name, c])), meta: {} };
  }
}

// Pick the clip for an on-ball event. Returns { clip, faceTarget } or null.
export function actionFor(ev, { keeper, speed, meta }) {
  const [, type, , body, outcome, , , ex, ey] = ev;
  const has = (n) => n in meta;
  const pick = (...names) => names.find(has) ?? null;
  const longBall = ex >= 0;
  switch (type) {
    case "pass":
    case "kick_off":
    case "free_kick":
    case "corner":
      if (body === "head") return { clip: pick("soccer_header", "header_soccerball"), faceTarget: true };
      if (keeper) return { clip: pick("goalkeeper_pass", "soccer_pass"), faceTarget: true };
      return { clip: speed > 2.2 ? pick("strike_foward_jog", "soccer_pass") : pick("soccer_pass"), faceTarget: longBall };
    case "goal_kick":
      return { clip: keeper ? pick("goalkeeper_drop_kick", "soccer_pass") : pick("soccer_pass"), faceTarget: true };
    case "shot":
      if (body === "head") return { clip: pick("header_soccerball", "soccer_header"), faceTarget: true };
      if (body === "left_foot") return { clip: pick("kick_soccerball", "soccer_penalty_kick"), faceTarget: true };
      return { clip: speed > 2.5 ? pick("strike_foward_jog", "kick_soccerball_2") : pick("soccer_penalty_kick", "kick_soccerball_2"), faceTarget: true };
    case "clearance":
      return { clip: body === "head" ? pick("soccer_header") : pick("kick_soccerball_2", "soccer_pass"), faceTarget: true };
    case "save":
      return { clip: outcome === "success" ? pick("goalkeeper_catch", "goalkeeper_diving_save") : pick("goalkeeper_diving_save"), faceTarget: false, dive: true };
    case "goal":
      return keeper ? { clip: pick("goalkeeper_miss", "goalkeeper_diving_save_2"), faceTarget: false } : null;
    case "tackle":
      return { clip: speed > 2 ? pick("soccer_tackle_2", "soccer_tackle") : pick("soccer_tackle", "soccer_tackle_3"), faceTarget: false };
    case "interception":
    case "ball_recovery":
      return { clip: pick("receive", "receive_soccerball"), faceTarget: false };
    case "block":
      return { clip: keeper ? pick("goalkeeper_body_block") : pick("soccer_tackle_3", "goalkeeper_body_block_2"), faceTarget: false };
    case "throw_in":
      return { clip: pick("throw_in"), faceTarget: true };
    case "foul":
      return { clip: pick("soccer_tackle", "soccer_tackle_3"), faceTarget: false };
    case "celebrate":
      return { clip: pick("victory"), faceTarget: false, celebrate: true };
    case "fouled":
      return { clip: pick("soccer_trip", "fallen_idle"), faceTarget: false };
    default:
      return null;
  }
}
