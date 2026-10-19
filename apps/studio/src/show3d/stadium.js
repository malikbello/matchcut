// The stadium: a closed bowl of tiered stands and curved corners under cantilever roofs whose
// front edges carry the floodlights, LED perimeter boards and a packed impostor crowd.
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

const CONCRETE = new THREE.MeshStandardMaterial({ color: 0x343b47, roughness: 0.92 });
const STEEL = new THREE.MeshStandardMaterial({ color: 0x2a2f38, roughness: 0.55, metalness: 0.6 });
const ROOF = new THREE.MeshStandardMaterial({ color: 0x1d222b, roughness: 0.7, metalness: 0.35, side: THREE.DoubleSide });
const FLOODLIGHT = new THREE.MeshStandardMaterial({ color: 0xffffff, emissive: 0xfff3dd, emissiveIntensity: 9 });
const BOXES = new THREE.MeshStandardMaterial({ color: 0x0d1118, emissive: 0xffc98a, emissiveIntensity: 0.55, roughness: 0.2, metalness: 0.4 });

// one stand along a side: stepped terrace, seats in club colour, hospitality boxes at the back,
// and a cantilever roof whose front edge carries the floodlights (as modern grounds light the pitch)
function stand(length, { seatColour = 0x1b2a44, roofY = null } = {}) {
  const g = new THREE.Group();
  const seats = new THREE.MeshStandardMaterial({ color: seatColour, roughness: 0.7 });
  const bank = new THREE.InstancedMesh(new THREE.BoxGeometry(length, STEP_H, STEP_D), CONCRETE, ROWS);
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
  const top = roofY ?? height + 7;
  // back wall up to the roof, with a glazed band of hospitality boxes
  const wall = new THREE.Mesh(new THREE.BoxGeometry(length, top, 0.6), CONCRETE);
  wall.position.set(0, top / 2, depth + 0.3);
  g.add(wall);
  const boxes = new THREE.Mesh(new THREE.BoxGeometry(length * 0.96, 2.4, 0.2), BOXES);
  boxes.position.set(0, height + 1.6, depth + 0.02);
  g.add(boxes);
  // roof: a sloping sheet reaching out over the front rows
  const reach = depth + 2;
  const roof = new THREE.Mesh(new THREE.PlaneGeometry(length + 2, reach), ROOF);
  roof.rotation.x = -Math.PI / 2 + 0.06;
  roof.position.set(0, top, depth - reach / 2 + 0.3);
  roof.castShadow = true;
  g.add(roof);
  // front fascia beam and its floodlight strip (the bloom pass makes it glow)
  const fascia = new THREE.Mesh(new THREE.BoxGeometry(length + 2, 1.4, 0.7), STEEL);
  fascia.position.set(0, top - 0.6, depth - reach + 0.3);
  g.add(fascia);
  const lights = new THREE.Mesh(new THREE.BoxGeometry(length * 0.92, 0.22, 0.22), FLOODLIGHT);
  lights.position.set(0, top - 1.35, depth - reach + 0.15);
  g.add(lights);
  // roof trusses: steel ribs from the back wall to the fascia
  const ribs = Math.max(4, Math.round(length / 9));
  const rib = new THREE.BoxGeometry(0.35, 0.9, reach);
  const ribMesh = new THREE.InstancedMesh(rib, STEEL, ribs);
  for (let i = 0; i < ribs; i++) {
    m.makeTranslation(-length / 2 + (i + 0.5) * (length / ribs), top - 0.55, depth - reach / 2 + 0.3);
    ribMesh.setMatrixAt(i, m);
  }
  g.add(ribMesh);
  return { group: g, depth, height, top };
}

// a curved corner stand that closes the bowl between two straight stands
function corner(sx, sz, top) {
  const g = new THREE.Group();
  const thetaStart = sx > 0 ? (sz > 0 ? 0 : Math.PI / 2) : sz > 0 ? (3 * Math.PI) / 2 : Math.PI;
  for (let r = 0; r < ROWS; r++) {
    const radius = (r + 1) * STEP_D;
    const step = new THREE.Mesh(
      new THREE.CylinderGeometry(radius, radius, STEP_H, 18, 1, false, thetaStart, Math.PI / 2),
      CONCRETE,
    );
    step.position.y = 1.2 + r * STEP_H;
    step.receiveShadow = true;
    g.add(step);
  }
  const depth = ROWS * STEP_D;
  const outer = new THREE.Mesh(new THREE.CylinderGeometry(depth + 0.3, depth + 0.3, top, 18, 1, true, thetaStart, Math.PI / 2), CONCRETE);
  outer.material = CONCRETE;
  outer.position.y = top / 2;
  g.add(outer);
  const roof = new THREE.Mesh(new THREE.RingGeometry(1, depth + 2, 18, 1, -thetaStart, Math.PI / 2) /* ring angles run the other way */, ROOF);
  roof.rotation.x = Math.PI / 2;
  roof.position.y = top;
  g.add(roof);
  g.position.set(sx * (L / 2 + GAP), 0, sz * (W / 2 + GAP));
  return g;
}

// The crowd: impostor cards, as sports games draw big crowds. Each fan is a pre-rendered card
// (scripts/blender/crowd_atlas.py: a CC0 fan in eight poses, with a shirt, skin and trousers
// mask), instanced thousands of times. The shader picks each fan's pose from the excitement and
// his own rhythm and dresses him (shirt, trousers, skin tone), so nothing moves on the CPU.
const FRAMES = 8;
const CROWD_VERT = `
  attribute vec4 aFan;        // x: phase, y: temperament (0 sits tight, 1 on his feet), z: skin, w: seed
  attribute vec3 aShirt;
  attribute vec3 aTrousers;
  uniform float uTime;
  uniform float uExcite;
  varying vec2 vUv;
  varying vec3 vShirt;
  varying vec3 vTrousers;
  varying vec3 vSkin;
  varying float vFrame;
  varying float vFog;
  vec3 skinTone(float k) {
    vec3 a = vec3(0.24, 0.15, 0.10);
    vec3 b = vec3(0.98, 0.80, 0.66);
    return mix(a, b, k);
  }
  void main() {
    float e = uExcite;
    float beat = fract(uTime * (0.6 + 1.8 * e) + aFan.x);
    float f;
    if (e < 0.35) {
      // calm: most sit, the restless stand; a few chat
      f = aFan.y > 0.82 ? (aFan.w > 0.5 ? 2.0 : 3.0) : (fract(uTime * 0.07 + aFan.x) > 0.85 ? 1.0 : 0.0);
    } else if (e < 0.7) {
      // an attack builds: the crowd rises
      f = aFan.y > 0.35 ? (aFan.w > 0.7 ? 4.0 : 2.0) : 0.0;
    } else {
      // eruption: everyone up, jumping and dancing on their own beat
      f = 4.0 + floor(beat * 4.0);
    }
    vFrame = f;
    vUv = uv;
    vShirt = aShirt;
    vTrousers = aTrousers;
    vSkin = skinTone(aFan.z);
    vec3 pos = position;
    pos.y += (e > 0.7 ? 0.12 * abs(sin(6.2831 * beat)) : 0.0);
    vec4 mv = modelViewMatrix * instanceMatrix * vec4(pos, 1.0);
    vFog = -mv.z;
    gl_Position = projectionMatrix * mv;
  }
`;
const CROWD_FRAG = `
  uniform sampler2D uColor;
  uniform sampler2D uMask;
  uniform vec3 uFogColor;
  uniform float uFogNear;
  uniform float uFogFar;
  uniform float uLight;
  varying vec2 vUv;
  varying vec3 vShirt;
  varying vec3 vTrousers;
  varying vec3 vSkin;
  varying float vFrame;
  varying float vFog;
  void main() {
    vec2 uv = vec2((vFrame + clamp(vUv.x, 0.02, 0.98)) / ${FRAMES}.0, vUv.y); // never bleed into a neighbouring pose
    vec4 c = texture2D(uColor, uv);
    if (c.a < 0.5) discard;
    vec3 m = texture2D(uMask, uv).rgb;
    vec3 base = c.rgb;
    float lum = dot(base, vec3(0.299, 0.587, 0.114));
    // normalised mask weights keep each fan's colours saturated however small he is on screen
    float sum = m.r + m.g + m.b;
    vec3 w = m / max(sum, 1e-3);
    vec3 tint = w.r * vShirt + w.g * vSkin + w.b * vTrousers;
    vec3 col = tint * (0.55 + 0.6 * lum);
    float hair = 1.0 - clamp(sum, 0.0, 1.0);
    col = mix(col, base * 0.22, hair);
    col *= uLight;
    float fog = smoothstep(uFogNear, uFogFar, vFog);
    gl_FragColor = vec4(mix(col, uFogColor, fog), 1.0);
    #include <colorspace_fragment>
  }
`;

const NEUTRAL_SHIRTS = [0xf2f2f2, 0x1b1f2a, 0x6b7280, 0x22344f, 0x8a1c1c, 0x2f5d3a];
const TROUSERS = [0x23324d, 0x1c2433, 0x111111, 0x3a3a3a, 0x5b4a36, 0x2c3e66];

function crowd(count, kits, base) {
  const card = new THREE.PlaneGeometry(1.2, 2.4);
  card.translate(0, 1.05, 0); // card frame: feet sit 0.15 m above its bottom edge
  const geo = new THREE.InstancedBufferGeometry().copy(card);
  const fan = new Float32Array(count * 4);
  const shirt = new Float32Array(count * 3);
  const trousers = new Float32Array(count * 3);
  const loader = new THREE.TextureLoader();
  const colorTex = loader.load(`${base}/crowd_color.png`);
  colorTex.colorSpace = THREE.SRGBColorSpace;
  const maskTex = loader.load(`${base}/crowd_mask.png`);
  for (const t of [colorTex, maskTex]) {
    t.minFilter = THREE.LinearMipmapLinearFilter;
    t.generateMipmaps = true;
  }
  const mat = new THREE.ShaderMaterial({
    vertexShader: CROWD_VERT,
    fragmentShader: CROWD_FRAG,
    uniforms: {
      uColor: { value: colorTex },
      uMask: { value: maskTex },
      uTime: { value: 0 },
      uExcite: { value: 0 },
      uLight: { value: 1.0 },
      uFogColor: { value: new THREE.Color(0x0b1424) }, // matches the scene fog
      uFogNear: { value: 180 },
      uFogFar: { value: 520 },
    },
  });
  const mesh = new THREE.InstancedMesh(geo, mat, count);
  const homeC = new THREE.Color(kits[0]);
  const awayC = new THREE.Color(kits[1]);
  const sides = [
    { len: L + 2 * GAP, rot: 0, at: (u, d) => [u, -(W / 2 + GAP) - d] },
    { len: L + 2 * GAP, rot: Math.PI, at: (u, d) => [-u, W / 2 + GAP + d] },
    { len: W + 2 * GAP, rot: Math.PI / 2, at: (u, d) => [-(L / 2 + GAP) - d, -u] },
    { len: W + 2 * GAP, rot: -Math.PI / 2, at: (u, d) => [L / 2 + GAP + d, u] },
  ];
  const m = new THREE.Matrix4();
  const q = new THREE.Quaternion();
  const sc = new THREE.Vector3();
  const rnd = mulberry(20261019);
  const tmp = new THREE.Color();
  // every seat of every row, shuffled, so a lower quality tier (which draws fewer) thins evenly
  const seats = [];
  sides.forEach((side, sideIdx) => {
    const perRow = Math.floor(side.len / 0.56);
    for (let row = 0; row < ROWS; row++) {
      for (let k = 0; k < perRow; k++) seats.push([sideIdx, row, (k + 0.5) / perRow - 0.5]);
    }
  });
  // the curved corners: rows are quarter circles around each corner of the bowl
  const corners = [[-1, -1], [1, -1], [1, 1], [-1, 1]];
  corners.forEach((c, ci) => {
    for (let row = 1; row < ROWS; row++) {
      const per = Math.floor((Math.PI / 2) * row * STEP_D / 0.56);
      for (let k = 0; k < per; k++) seats.push([4 + ci, row, (k + 0.5) / per]);
    }
  });
  for (let i = seats.length - 1; i > 0; i--) {
    const j = Math.floor(rnd() * (i + 1));
    [seats[i], seats[j]] = [seats[j], seats[i]];
  }
  for (let i = 0; i < count; i++) {
    const [sideIdx, row, frac] = seats[i % seats.length];
    let x;
    let z;
    if (sideIdx < 4) {
      const side = sides[sideIdx];
      const u = (frac + (rnd() - 0.5) * 0.004) * side.len;
      [x, z] = side.at(u, row * STEP_D + 0.25);
      q.setFromAxisAngle(new THREE.Vector3(0, 1, 0), side.rot);
    } else {
      const [cx, cz] = corners[sideIdx - 4];
      const theta = (frac * Math.PI) / 2;
      const r = row * STEP_D + 0.4;
      x = cx * (L / 2 + GAP + r * Math.sin(theta));
      z = cz * (W / 2 + GAP + r * Math.cos(theta));
      q.setFromAxisAngle(new THREE.Vector3(0, 1, 0), Math.atan2(-x, -z)); // face the centre spot
    }
    const y = 1.2 + row * STEP_H + STEP_H / 2;
    const size = 0.9 + rnd() * 0.12;
    sc.set(size, size, size);
    m.compose(new THREE.Vector3(x, y, z), q, sc);
    mesh.setMatrixAt(i, m);
    // home fans fill the stand behind one goal, the away end sits behind the other,
    // the long stands are mixed with plenty of neutral colours
    const r = rnd();
    let c;
    const end = sideIdx === 2 || (sideIdx >= 4 && corners[sideIdx - 4][0] < 0) ? 2 : sideIdx === 3 || sideIdx >= 4 ? 3 : sideIdx;
    if (end === 2) c = r < 0.82 ? homeC : NEUTRAL_SHIRTS[Math.floor(rnd() * NEUTRAL_SHIRTS.length)];
    else if (end === 3) c = r < 0.72 ? awayC : NEUTRAL_SHIRTS[Math.floor(rnd() * NEUTRAL_SHIRTS.length)];
    else c = r < 0.38 ? homeC : r < 0.56 ? awayC : NEUTRAL_SHIRTS[Math.floor(rnd() * NEUTRAL_SHIRTS.length)];
    tmp.set(c).offsetHSL(0, 0, (rnd() - 0.5) * 0.1);
    shirt.set([tmp.r, tmp.g, tmp.b], i * 3);
    tmp.set(TROUSERS[Math.floor(rnd() * TROUSERS.length)]);
    trousers.set([tmp.r, tmp.g, tmp.b], i * 3);
    fan.set([rnd(), rnd(), rnd() ** 0.8, rnd()], i * 4);
  }
  geo.setAttribute("aFan", new THREE.InstancedBufferAttribute(fan, 4));
  geo.setAttribute("aShirt", new THREE.InstancedBufferAttribute(shirt, 3));
  geo.setAttribute("aTrousers", new THREE.InstancedBufferAttribute(trousers, 3));
  mesh.frustumCulled = false;
  return { mesh, material: mat };
}

// a small seeded generator, so the same stadium is built every time (and in exported films)
function mulberry(seed) {
  let a = seed;
  return () => {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export function buildStadium({ crowdCount, kits, assets = "assets/3d" }) {
  const group = new THREE.Group();
  const home = new THREE.Color(kits[0]).multiplyScalar(0.55).getHex();
  const away = new THREE.Color(kits[1]).multiplyScalar(0.55).getHex();
  const placements = [
    { len: L + 2 * GAP, pos: [0, -(W / 2 + GAP)], rot: Math.PI, seat: 0x1b2a44 },
    // main stand: its roof sits above the camera gantry
    { len: L + 2 * GAP, pos: [0, W / 2 + GAP], rot: 0, seat: 0x1b2a44, roofY: 27 },
    { len: W + 2 * GAP, pos: [-(L / 2 + GAP), 0], rot: -Math.PI / 2, seat: home },
    { len: W + 2 * GAP, pos: [L / 2 + GAP, 0], rot: Math.PI / 2, seat: away },
  ];
  let top = 0;
  for (const p of placements) {
    const st = stand(p.len, { seatColour: p.seat, roofY: p.roofY ?? null });
    st.group.position.set(p.pos[0], 0, p.pos[1]);
    st.group.rotation.y = p.rot;
    group.add(st.group);
    if (!p.roofY) top = st.top;
  }
  for (const [sx, sz] of [[-1, -1], [1, -1], [1, 1], [-1, 1]]) group.add(corner(sx, sz, top));
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
  const fans = crowd(crowdCount, kits, assets);
  group.add(fans.mesh);
  return { group, crowd: fans };
}

// excitement 0..1: the crowd sits, rises, then erupts (all in the shader)
export function animateCrowd(crowd, timeS, excitement) {
  const u = crowd.material.uniforms;
  u.uTime.value = timeS;
  u.uExcite.value += (excitement - u.uExcite.value) * 0.06;
}

// The night sky: a gradient dome from deep navy overhead to a warm floodlight glow on the
// horizon (the light a lit stadium throws into the haze), with a faint field of stars.
export function buildSky() {
  const g = new THREE.Group();
  const dome = new THREE.Mesh(
    new THREE.SphereGeometry(600, 32, 16),
    new THREE.ShaderMaterial({
      side: THREE.BackSide,
      depthWrite: false,
      fog: false,
      uniforms: {
        uTop: { value: new THREE.Color(0x03050b) },
        uMid: { value: new THREE.Color(0x0b1424) },
        uGlow: { value: new THREE.Color(0x3a2c22) },
      },
      vertexShader: "varying vec3 vDir; void main(){ vDir = normalize(position); gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }",
      fragmentShader: `uniform vec3 uTop, uMid, uGlow; varying vec3 vDir;
        void main(){
          float h = clamp(vDir.y, 0.0, 1.0);
          vec3 c = mix(uMid, uTop, smoothstep(0.05, 0.6, h));
          c += uGlow * exp(-h * 9.0) * 0.9;
          gl_FragColor = vec4(c, 1.0);
          #include <colorspace_fragment>
        }`,
    }),
  );
  g.add(dome);
  const n = 900;
  const pos = new Float32Array(n * 3);
  let a = 7;
  const rnd = () => ((a = (a * 16807) % 2147483647) / 2147483647);
  for (let i = 0; i < n; i++) {
    const th = rnd() * Math.PI * 2;
    const y = 0.25 + rnd() * 0.75;
    const r = Math.sqrt(1 - y * y);
    pos.set([Math.cos(th) * r * 560, y * 560, Math.sin(th) * r * 560], i * 3);
  }
  const stars = new THREE.Points(
    new THREE.BufferGeometry().setAttribute("position", new THREE.BufferAttribute(pos, 3)),
    new THREE.PointsMaterial({ color: 0x9fb2d6, size: 1.2, sizeAttenuation: false, fog: false, transparent: true, opacity: 0.55 }),
  );
  g.add(stars);
  return g;
}