// The goal package: what a broadcast director cuts to after a goal.
//
//   celebration  the scorer sprints to the nearest corner and celebrates; teammates pile in,
//                opponents trudge back; a tight camera stays on the scorer
//   replay 1     the whole move from the main camera at 0.75x
//   replay 2     behind the goal, slow motion through the strike
// Segments are separated by a branded wipe. Everything is a pure function of package time
// (seconds since the goal), so live viewing and video export produce the same pictures.
import { L, W } from "./pitch.js";

const CELEBRATION = 7.0;
const WIPE = 0.6;

export function planPackage(goal, shotT) {
  const T = goal.t;
  const strike = shotT ?? T - 300;
  const segments = [];
  let at = 0;
  const add = (seg) => {
    segments.push({ ...seg, start: at, end: at + seg.length });
    at += seg.length;
  };
  add({ kind: "celebration", length: CELEBRATION, mode: "tight" });
  add({ kind: "wipe", length: WIPE });
  // replay 1: from 6 s before the strike to just after the ball crosses the line
  const r1From = strike - 6000;
  const r1To = T + 700;
  add({ kind: "replay", length: (r1To - r1From) / 1000 / 0.75, mode: "broadcast", from: r1From, rate: 0.75, label: "REPLAY" });
  add({ kind: "wipe", length: WIPE });
  // replay 2: reverse angle, slow motion through the strike
  const r2From = strike - 2200;
  const r2To = T + 900;
  add({ kind: "replay", length: (r2To - r2From) / 1000 / 0.35, mode: "goal", from: r2From, rate: 0.35, label: "REPLAY" });
  add({ kind: "wipe", length: WIPE });
  return { goal, strike, segments, duration: at };
}

export function segmentAt(plan, pt) {
  return plan.segments.find((s) => pt >= s.start && pt < s.end) ?? null;
}

// Where each player is during the celebration (pure function of tc, seconds since the goal).
// start: {slot: [x, z]} positions when the ball went in; returns {slot: {x, z, vx, vz, celebrate}}
export function celebrationPose(start, { scorer, scorerTeam, teamOf, keepers, tc }) {
  const [sx, sz] = start[scorer];
  // nearest corner flag on the scorer's end, a few metres in from it
  const cx = Math.sign(sx || 1) * (L / 2 - 3);
  const cz = Math.sign(sz || 1) * (W / 2 - 3);
  const dist = Math.hypot(cx - sx, cz - sz);
  const runFor = Math.max(1.5, dist / 7.2);
  const out = {};
  const toward = (x0, z0, x1, z1, speed, t, delay = 0) => {
    const d = Math.hypot(x1 - x0, z1 - z0);
    const tt = Math.max(0, t - delay);
    const k = Math.min(1, (tt * speed) / Math.max(d, 1e-3));
    const moving = k < 1 && tt > 0;
    const ux = (x1 - x0) / Math.max(d, 1e-3);
    const uz = (z1 - z0) / Math.max(d, 1e-3);
    return { x: x0 + (x1 - x0) * k, z: z0 + (z1 - z0) * k, vx: moving ? ux * speed : 0, vz: moving ? uz * speed : 0 };
  };
  const scorerAt = toward(sx, sz, cx, cz, dist / runFor, tc);
  out[scorer] = { ...scorerAt, celebrate: tc > runFor - 0.2 ? tc - (runFor - 0.2) : null };
  let k = 0;
  for (const [slot, [x, z]] of Object.entries(start)) {
    const s = Number(slot);
    if (s === scorer) continue;
    if (teamOf[s] === scorerTeam && !keepers.has(s)) {
      // teammates join the scorer, arriving in a ring around him
      const ang = (k++ * 2.4) % (Math.PI * 2);
      const tx = cx - Math.sign(cx) * 1.6 + Math.cos(ang) * 1.4;
      const tz = cz - Math.sign(cz) * 1.6 + Math.sin(ang) * 1.4;
      const p = toward(x, z, tx, tz, 6.5, tc, 0.6 + (k % 4) * 0.25);
      const arrived = p.vx === 0 && p.vz === 0 && tc > 1;
      out[s] = { ...p, celebrate: arrived ? tc : null };
    } else {
      // opponents and keepers: a slow walk back towards the centre circle
      out[s] = toward(x, z, x * 0.6, z * 0.6, 1.1, tc, 0.8);
    }
  }
  return out;
}
