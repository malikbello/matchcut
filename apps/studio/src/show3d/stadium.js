// The stadium: a four-sided bowl of tiered stands with roofs, LED perimeter boards,
// floodlight pylons and an instanced crowd that rises and roars with the match.
// Everything is procedural (no third-party models), so it ships with the code.
import * as THREE from "three";
import { L, W } from "./pitch.js";

const GAP = 8; // pitch line to first row
const ROWS = 26;
const STEP_D = 0.85; // row depth
const STEP_H = 0.42; // row rise

function boardTexture(kits) {
  const cv = document.createElement("canvas");
  cv.width = 2048;
  cv.height = 64;
  const c = cv.getContext("2d");
  const words = ["MATCHCUT", "EVERY FAN'S CUT", "VERIFIED", "HARBOUR LEAGUE"];
  for (let i = 0; i < 8; i++) {
    const x = i * 256;
    c.fillStyle = i % 2 ? "#0b1220" : kits[i % kits.length];
    c.fillRect(x, 0, 256, 64);
    c.fillStyle = i % 2 ? "#ff4a2e" : "#ffffff";
    c.font = "800 34px 'Big Shoulders Display', Inter, sans-serif";
    c.textAlign = "center";
    c.textBaseline = "middle";
    c.fillText(words[i % words.length], x + 128, 34);
  }
  const t = new THREE.CanvasTexture(cv);
  t.colorSpace = THREE.SRGBColorSpace;
  t.wrapS = THREE.RepeatWrapping;
  return t;
}

// one stand along a side: stepped concrete, seats, back wall and a cantilever roof
function stand(length, { roof: withRoof = true } = {}) {
  const g = new THREE.Group();
  const concrete = new THREE.MeshStandardMaterial({ color: 0x3a4250, roughness: 0.9 });
  const seats = new THREE.MeshStandardMaterial({ color: 0x1b2a44, roughness: 0.7 });
  const steps = new THREE.BoxGeometry(length, STEP_H, STEP_D);
  const bank = new THREE.InstancedMesh(steps, concrete, ROWS);
  const m = new THREE.Matrix4();
  for (let r = 0; r < ROWS; r++) {
    m.makeTranslation(0, 1.2 + r * STEP_H, r * STEP_D);
    bank.setMatrixAt(r, m);
  }
  bank.receiveShadow = true;
  g.add(bank);
  const seatRows = new THREE.InstancedMesh(new THREE.BoxGeometry(length, 0.22, 0.3), seats, ROWS);
  for (let r = 0; r < ROWS; r++) {
    m.makeTranslation(0, 1.2 + r * STEP_H + 0.3, r * STEP_D - 0.15);
    seatRows.setMatrixAt(r, m);
  }
  g.add(seatRows);
  const depth = ROWS * STEP_D;
  const height = 1.2 + ROWS * STEP_H;
  const wall = new THREE.Mesh(new THREE.BoxGeometry(length, height + 6, 0.6), concrete);
  wall.position.set(0, (height + 6) / 2, depth + 0.3);
  g.add(wall);
  if (withRoof) {
    const roof = new THREE.Mesh(
      new THREE.BoxGeometry(length + 4, 0.5, depth * 0.85),
      new THREE.MeshStandardMaterial({ color: 0x4a525e, roughness: 0.7, metalness: 0.4 }),
    );
    roof.position.set(0, height + 6, depth * 0.58);
    roof.rotation.x = -0.08;
    roof.castShadow = true;
    g.add(roof);
  }
  return { group: g, depth, height };
}

function crowd(count, kits) {
  // a fan is a small capsule; colour mixes both clubs' kits with neutrals
  const geo = new THREE.CapsuleGeometry(0.22, 0.55, 2, 6);
  const mat = new THREE.MeshStandardMaterial({ roughness: 0.85 });
  const mesh = new THREE.InstancedMesh(geo, mat, count);
  const base = [];
  const palette = [...kits.map((k) => new THREE.Color(k)), new THREE.Color(0x2a2f38), new THREE.Color(0xe8e4dc)];
  const sides = [
    { len: L + 2 * GAP, rot: 0, at: (u, d) => [u, -(W / 2 + GAP) - d] },
    { len: L + 2 * GAP, rot: Math.PI, at: (u, d) => [-u, W / 2 + GAP + d] },
    { len: W + 2 * GAP, rot: Math.PI / 2, at: (u, d) => [-(L / 2 + GAP) - d, -u] },
    { len: W + 2 * GAP, rot: -Math.PI / 2, at: (u, d) => [L / 2 + GAP + d, u] },
  ];
  const m = new THREE.Matrix4();
  const q = new THREE.Quaternion();
  const s = new THREE.Vector3(1, 1, 1);
  for (let i = 0; i < count; i++) {
    const side = sides[i % 4];
    const row = Math.floor(Math.random() * ROWS);
    const u = (Math.random() - 0.5) * side.len;
    const [x, z] = side.at(u, row * STEP_D + 0.2);
    const y = 1.2 + row * STEP_H + 0.75;
    q.setFromAxisAngle(new THREE.Vector3(0, 1, 0), side.rot);
    m.compose(new THREE.Vector3(x, y, z), q, s);
    mesh.setMatrixAt(i, m);
    // home fans gather behind one goal, away fans behind the other, neutrals everywhere
    const pick = Math.random() < 0.55 ? palette[i % 4 === 2 ? 0 : i % 4 === 3 ? 1 : i % 2] : palette[2 + (i % 2)];
    mesh.setColorAt(i, pick.clone().offsetHSL(0, 0, (Math.random() - 0.5) * 0.12));
    base.push({ x, y, z, phase: Math.random() * Math.PI * 2, q: q.clone() });
  }
  mesh.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
  return { mesh, base };
}

export function buildStadium({ crowdCount, kits }) {
  const group = new THREE.Group();
  const placements = [
    { len: L + 2 * GAP, pos: [0, -(W / 2 + GAP)], rot: Math.PI },
    { len: L + 2 * GAP, pos: [0, W / 2 + GAP], rot: 0, roof: false }, // main stand: the gantry hangs here
    { len: W + 2 * GAP, pos: [-(L / 2 + GAP), 0], rot: -Math.PI / 2 },
    { len: W + 2 * GAP, pos: [L / 2 + GAP, 0], rot: Math.PI / 2 },
  ];
  for (const p of placements) {
    const st = stand(p.len, { roof: p.roof !== false });
    st.group.position.set(p.pos[0], 0, p.pos[1]);
    st.group.rotation.y = p.rot;
    group.add(st.group);
  }
  // LED boards just beyond the touchlines and goal lines
  const tex = boardTexture(kits);
  const boardMat = new THREE.MeshStandardMaterial({ map: tex, emissive: 0xffffff, emissiveMap: tex, emissiveIntensity: 0.9 });
  for (const [len, x, z, ry] of [
    [L + 10, 0, -(W / 2 + 4), 0],
    [L + 10, 0, W / 2 + 4, Math.PI],
    [W, -(L / 2 + 4.5), 0, Math.PI / 2],
    [W, L / 2 + 4.5, 0, -Math.PI / 2],
  ]) {
    const t = tex.clone();
    t.repeat.set(len / 32, 1);
    t.needsUpdate = true;
    const mat = boardMat.clone();
    mat.map = t;
    mat.emissiveMap = t;
    const b = new THREE.Mesh(new THREE.BoxGeometry(len, 0.9, 0.15), mat);
    b.position.set(x, 0.45, z);
    b.rotation.y = ry;
    group.add(b);
  }
  // floodlight pylons at the corners: emissive heads feed the bloom pass
  const head = new THREE.MeshStandardMaterial({ color: 0xffffff, emissive: 0xfff4dc, emissiveIntensity: 6 });
  const steel = new THREE.MeshStandardMaterial({ color: 0x9aa3b2, metalness: 0.6, roughness: 0.4 });
  for (const [sx, sz] of [[-1, -1], [1, -1], [1, 1], [-1, 1]]) {
    const x = sx * (L / 2 + GAP + ROWS * STEP_D + 6);
    const z = sz * (W / 2 + GAP + ROWS * STEP_D + 6);
    const mast = new THREE.Mesh(new THREE.CylinderGeometry(0.5, 0.9, 48, 12), steel);
    mast.position.set(x, 24, z);
    group.add(mast);
    const panel = new THREE.Mesh(new THREE.BoxGeometry(9, 5, 0.6), head);
    panel.position.set(x, 49, z);
    panel.lookAt(0, 0, 0);
    group.add(panel);
  }
  const fans = crowd(crowdCount, kits);
  group.add(fans.mesh);
  return { group, crowd: fans };
}

// excitement 0..1 makes the crowd bounce and stand; called every frame
const _m = new THREE.Matrix4();
const _p = new THREE.Vector3();
const _s = new THREE.Vector3(1, 1, 1);
export function animateCrowd(crowd, timeS, excitement) {
  const { mesh, base } = crowd;
  const amp = 0.04 + 0.35 * excitement;
  const rate = 2 + 6 * excitement;
  for (let i = 0; i < base.length; i++) {
    const b = base[i];
    const lift = Math.max(0, Math.sin(timeS * rate + b.phase)) * amp;
    _p.set(b.x, b.y + lift, b.z);
    _m.compose(_p, b.q, _s);
    mesh.setMatrixAt(i, _m);
  }
  mesh.instanceMatrix.needsUpdate = true;
}
