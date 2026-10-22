// Matchcut show camera: a real-time 3D broadcast of the synthetic match, driven by the
// same 10 Hz tracking feed, event stream and match clock as the 2D data pitch (its fallback tier).
//
//   const show = await createShow({ canvas, feed, assets: "assets/3d" });
//   show.render(tMs, { spotlight: "Quinouani", excitement: 0.4 });
import * as THREE from "three";
import { EffectComposer } from "three/addons/postprocessing/EffectComposer.js";
import { OutputPass } from "three/addons/postprocessing/OutputPass.js";
import { RenderPass } from "three/addons/postprocessing/RenderPass.js";
import { UnrealBloomPass } from "three/addons/postprocessing/UnrealBloomPass.js";
import { GTAOPass } from "three/addons/postprocessing/GTAOPass.js";
import { ShaderPass } from "three/addons/postprocessing/ShaderPass.js";
import { RoomEnvironment } from "three/addons/environments/RoomEnvironment.js";
import { Director } from "./camera.js";
import { buildPitch, L, toWorld, W } from "./pitch.js";
import { loadLibrary } from "./library.js";
import { celebrationPose, planPackage, segmentAt } from "./package.js";
import { Player } from "./players.js";
import { FrameGovernor, ORDER, TIERS, webglAvailable } from "./quality.js";
import { animateCrowd, buildSky, buildStadium } from "./stadium.js";

export { webglAvailable };
const EMPTY = -9999; // the feed's empty-slot marker (see services/sim feed.py)
export { Crowd } from "./crowd.js";

function frameAt(feed, t) {
  const ts = feed.t;
  let lo = 0;
  let hi = ts.length - 1;
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1;
    if (ts[mid] <= t) lo = mid;
    else hi = mid - 1;
  }
  const b = Math.min(lo + 1, ts.length - 1);
  const u = b === lo ? 0 : THREE.MathUtils.clamp((t - ts[lo]) / (ts[b] - ts[lo]), 0, 1);
  return [lo, b, u, b === lo ? 1 : (ts[b] - ts[lo]) / 1000];
}

// Centripetal-free Catmull-Rom through four tracking samples: smooth positions and a
// continuous velocity from 10 Hz data (linear interpolation makes speed step every frame).
function spline(p0, p1, p2, p3, u) {
  const u2 = u * u;
  const u3 = u2 * u;
  return 0.5 * (2 * p1 + (-p0 + p2) * u + (2 * p0 - 5 * p1 + 4 * p2 - p3) * u2 + (-p0 + 3 * p1 - 3 * p2 + p3) * u3);
}
function splineVel(p0, p1, p2, p3, u, span) {
  const u2 = u * u;
  return (0.5 * ((-p0 + p2) + 2 * (2 * p0 - 5 * p1 + 4 * p2 - p3) * u + 3 * (-p0 + 3 * p1 - 3 * p2 + p3) * u2)) / span;
}

// Keeper kits must contrast with both outfield kits, as the Laws of the Game require.
const KEEPER_COLOURS = ["#39ff6a", "#ff7a1a", "#19d3ff", "#ff2d95", "#f4ff3a"];
function colourDistance(a, b) {
  const ca = new THREE.Color(a);
  const cb = new THREE.Color(b);
  return Math.hypot(ca.r - cb.r, ca.g - cb.g, ca.b - cb.b);
}
function keeperKits(feed) {
  const outfield = [feed.teams.home.kit.primary, feed.teams.away.kit.primary];
  const ranked = [...KEEPER_COLOURS].sort(
    (a, b) => Math.min(...outfield.map((o) => colourDistance(b, o))) - Math.min(...outfield.map((o) => colourDistance(a, o))),
  );
  return { home: { primary: ranked[0], secondary: "#111111", shorts: "#111111", socks: ranked[0] },
           away: { primary: ranked[1], secondary: "#111111", shorts: "#111111", socks: ranked[1] } };
}

const GOAL_HALF = 3.66; // half the goal's width (7.32 m)
const GOAL_CLEAR = 0.45; // how close a body may come to the goal line inside the goal mouth
const PASS_DECAY = 0.45; // 1/s: a rolling pass loses about a third of its pace over a second
const MAX_CONTROLLED_SPEED = 20; // m/s: how fast a ball knocked between players can be drawn moving
const PASSES = new Set(["pass", "free_kick", "corner", "goal_kick", "kick_off"]);

// Completed passes as flights: start (the ball where it was struck), receiver, departure and
// arrival times. Arrival is when the tracked ball stops travelling at pass pace near the receiver.
function buildFlights(feed) {
  const { t: T, b: B, p: P } = feed;
  const out = [];
  for (const e of feed.events ?? []) {
    if (!PASSES.has(e[1]) || e[4] !== "success" || !(e[9] >= 0)) continue;
    const [i0] = frameAt(feed, e[0]);
    if (i0 + 3 >= T.length) continue;
    const speed = (i) => Math.hypot(B[i + 1][0] - B[i][0], B[i + 1][1] - B[i][1]) / 10 / ((T[i + 1] - T[i]) / 1000);
    const v0 = Math.max(speed(i0 + 1), 1);
    let i1 = i0 + 2;
    for (; i1 < Math.min(T.length - 2, i0 + 45); i1++) {
      const rx = P[i1][2 * e[9]];
      const ry = P[i1][2 * e[9] + 1];
      const near = rx !== EMPTY && Math.hypot(B[i1][0] - rx, B[i1][1] - ry) / 10 < 1.2;
      if (near || speed(i1) < 0.5 * v0) break;
    }
    const [fromX, fromZ] = toWorld(B[i0][0] / 10, B[i0][1] / 10);
    const [endX, endZ] = toWorld(B[i1][0] / 10, B[i1][1] / 10);
    const dist = Math.hypot(endX - fromX, endZ - fromZ);
    if (dist < 4 || T[i1] - e[0] < 150) continue; // a short lay-off is drawn from the data as it is
    out.push({
      t0: e[0], t1: T[i1], to: e[9], fromX, fromZ, endX, endZ,
      dirX: (endX - fromX) / dist, dirZ: (endZ - fromZ) / dist,
      loft: dist > 25 ? THREE.MathUtils.clamp(dist * 0.09, 1.5, 7) : 0, // long balls are played in the air
    });
  }
  return out.sort((x, y) => x.t0 - y.t0);
}

// per-slot event index: for any moment, the event whose action window covers it
function indexEvents(feed) {
  const bySlot = feed.slots.map(() => []);
  for (const e of feed.events ?? []) if (e[2] >= 0) bySlot[e[2]].push(e);
  // fouled players fall: give the recipient of a foul its own row
  for (const e of feed.events ?? []) if (e[1] === "foul" && e[9] >= 0) bySlot[e[9]].push([e[0], "fouled", e[9], "", "", e[5], e[6], -1, -1, -1]);
  for (const list of bySlot) list.sort((a, b) => a[0] - b[0]);
  return bySlot;
}
function eventNear(list, t, before = 2600, after = 3400) {
  // the latest event that started before t + before and is not long finished
  let lo = 0;
  let hi = list.length - 1;
  let best = null;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (list[mid][0] <= t + before) {
      best = mid;
      lo = mid + 1;
    } else hi = mid - 1;
  }
  for (let i = best ?? -1; i >= 0 && i >= (best ?? 0) - 3; i--) {
    const e = list[i];
    if (e[0] - before <= t && t <= e[0] + after) return e;
  }
  return null;
}

// The broadcast grade, applied after tone mapping: floodlit football on TV has cool shadows and
// warm highlights, a little extra saturation, a soft vignette and fine grain.
const GradeShader = {
  uniforms: { tDiffuse: { value: null }, uTime: { value: 0 }, uGrain: { value: 0.022 } },
  vertexShader: "varying vec2 vUv; void main(){ vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }",
  fragmentShader: `uniform sampler2D tDiffuse; uniform float uTime; uniform float uGrain; varying vec2 vUv;
    float hash(vec2 p){ return fract(sin(dot(p, vec2(12.9898, 78.233))) * 43758.5453); }
    void main(){
      vec3 c = texture2D(tDiffuse, vUv).rgb;
      float l = dot(c, vec3(0.2126, 0.7152, 0.0722));
      c = mix(vec3(l), c, 1.08);                                             // saturation
      c += mix(vec3(-0.012, 0.0, 0.018), vec3(0.02, 0.008, -0.012), smoothstep(0.15, 0.75, l)); // split tone
      c = (c - 0.5) * 1.04 + 0.5;                                            // contrast
      vec2 d = vUv - 0.5;
      c *= 1.0 - 0.32 * dot(d, d) * 2.0;                                     // vignette
      c += (hash(vUv * 1024.0 + uTime) - 0.5) * uGrain;                      // grain
      gl_FragColor = vec4(clamp(c, 0.0, 1.0), 1.0);
    }`,
};

function ballMesh() {
  const cv = document.createElement("canvas");
  cv.width = 256;
  cv.height = 128;
  const c = cv.getContext("2d");
  c.fillStyle = "#f7f7f2";
  c.fillRect(0, 0, 256, 128);
  c.fillStyle = "#1b2433";
  for (let i = 0; i < 12; i++) {
    c.beginPath();
    c.arc(((i * 53) % 256) + 10, ((i * 37) % 128) + 8, 12, 0, Math.PI * 2);
    c.fill();
  }
  const tex = new THREE.CanvasTexture(cv);
  tex.colorSpace = THREE.SRGBColorSpace;
  const m = new THREE.Mesh(new THREE.SphereGeometry(0.11, 24, 16), new THREE.MeshStandardMaterial({ map: tex, roughness: 0.4 }));
  m.castShadow = true;
  return m;
}

export async function createShow({
  canvas, feed, assets = "assets/3d", privateAssets = "assets/private", quality = "high", onQuality = () => {},
  adaptive = true, // live viewing steps quality down on slow devices; films never change quality mid-cut
}) {
  if (!webglAvailable()) throw new Error("WebGL2 unavailable");
  let tierName = quality;
  let tier = TIERS[tierName];
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: tier.antialias, powerPreference: "high-performance" });
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.05;
  renderer.shadowMap.type = THREE.PCFShadowMap; // soft filtering is built in since r180

  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x05080f);
  scene.add(buildSky());
  scene.fog = new THREE.Fog(0x0b1424, 180, 520);
  const pmrem = new THREE.PMREMGenerator(renderer);
  scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
  scene.environmentIntensity = 0.25; // reflections only; the floodlights do the lighting

  // night match under floodlights: a key light high over the main stand, soft fill from the sky
  scene.add(new THREE.HemisphereLight(0xb8c7ff, 0x1b2a1b, 0.55));
  const key = new THREE.DirectionalLight(0xfff3e0, 2.6);
  key.position.set(-35, 95, 55); // from the camera side: faces lit, shadows fall away from the lens
  key.shadow.camera.left = -L / 2 - 8;
  key.shadow.camera.right = L / 2 + 8;
  key.shadow.camera.top = W / 2 + 8;
  key.shadow.camera.bottom = -W / 2 - 8;
  key.shadow.camera.far = 260;
  key.shadow.bias = -0.0004;
  key.shadow.normalBias = 0.02;
  scene.add(key, key.target);
  const rim = new THREE.DirectionalLight(0xdfe8ff, 0.9);
  rim.position.set(60, 70, -70);
  scene.add(rim);

  scene.add(buildPitch(renderer));
  const kits = [feed.teams.home.kit.primary, feed.teams.away.kit.primary];
  const stadium = buildStadium({ crowdCount: TIERS.high.crowd, kits, assets });
  scene.add(stadium.group);

  const lib = await loadLibrary({ privateBase: privateAssets, publicBase: assets });
  const gk = keeperKits(feed);
  const keepers = new Set(feed.keepers ?? []);
  const events = indexEvents(feed);
  const cuts = feed.cuts ?? [];
  const players = feed.slots.map((clubId, slot) => {
    const side = clubId === feed.teams.home.id ? "home" : "away";
    const keeper = keepers.has(slot);
    const who = feed.teams[side].players[String(slot)] ?? { name: "", num: "" };
    const kit = keeper ? { ...gk[side], number: "#111111" } : feed.teams[side].kit;
    const p = new Player(lib, kit, { seed: slot, keeper, name: who.name, num: who.num });
    p.identity = `${who.name}#${who.num}`;
    p.root.visible = false;
    scene.add(p.root);
    return p;
  });
  const ball = ballMesh();
  scene.add(ball);
  // contact shadow: a soft disc under the ball, tight and dark on the grass, wide and faint in
  // the air, so the eye always finds the ball and reads its height, as on television
  const ballShadow = (() => {
    const cv = document.createElement("canvas");
    cv.width = cv.height = 64;
    const c = cv.getContext("2d");
    const g = c.createRadialGradient(32, 32, 0, 32, 32, 32);
    g.addColorStop(0, "rgba(0,0,0,0.75)");
    g.addColorStop(0.45, "rgba(0,0,0,0.35)");
    g.addColorStop(1, "rgba(0,0,0,0)");
    c.fillStyle = g;
    c.fillRect(0, 0, 64, 64);
    const m = new THREE.Mesh(
      new THREE.PlaneGeometry(1, 1).rotateX(-Math.PI / 2),
      new THREE.MeshBasicMaterial({ map: new THREE.CanvasTexture(cv), transparent: true, depthWrite: false }),
    );
    m.renderOrder = 1;
    scene.add(m);
    return m;
  })();
  function placeBallShadow() {
    const h = Math.max(0, ball.position.y - 0.11);
    const s = 0.34 + h * 0.35;
    ballShadow.position.set(ball.position.x, 0.012, ball.position.z);
    ballShadow.scale.set(s, 1, s);
    ballShadow.material.opacity = THREE.MathUtils.clamp(1 - h / 6, 0.15, 1);
  }

  const camera = new THREE.PerspectiveCamera(30, 16 / 9, 0.5, 900);
  const director = new Director(camera);
  const composer = new EffectComposer(renderer);
  composer.addPass(new RenderPass(scene, camera));
  // contact shadows: players sit on the grass instead of floating (High tier only)
  const gtao = new GTAOPass(scene, camera, 1024, 576);
  gtao.updateGtaoMaterial({ radius: 0.6, distanceExponent: 1.5, thickness: 1.2, scale: 1.0 });
  gtao.blendIntensity = 0.85;
  composer.addPass(gtao);
  const bloom = new UnrealBloomPass(new THREE.Vector2(1024, 576), 0.4, 0.45, 0.95); // floodlights and LED boards only
  composer.addPass(bloom);
  composer.addPass(new OutputPass());
  const grade = new ShaderPass(GradeShader);
  composer.addPass(grade);

  function applyTier() {
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, tier.pixelRatio));
    renderer.shadowMap.enabled = tier.shadows > 0;
    key.castShadow = tier.shadows > 0;
    if (tier.shadows) key.shadow.mapSize.set(tier.shadows, tier.shadows);
    key.shadow.map?.dispose();
    key.shadow.map = null;
    bloom.enabled = tier.bloom;
    gtao.enabled = tier.gtao;
    stadium.crowd.mesh.count = tier.crowd;
    resize();
  }
  function resize() {
    const r = canvas.getBoundingClientRect();
    const w = Math.max(1, Math.round(r.width));
    const h = Math.max(1, Math.round(r.height));
    renderer.setSize(w, h, false);
    composer.setSize(w, h);
    composer.setPixelRatio(renderer.getPixelRatio());
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
  }
  const observer = new ResizeObserver(resize);
  observer.observe(canvas);
  applyTier();

  const governor = new FrameGovernor();
  let lastWall = performance.now();
  let lastT = null;
  let lastCutCheck = 0;
  let wallClock = 0;
  const ballPrev = new THREE.Vector3();
  const teamOf = feed.slots;

  // wall-clock bookkeeping and automatic quality step-down, once per rendered frame
  function frameClock() {
    const now = performance.now();
    const wallDt = Math.min(0.1, (now - lastWall) / 1000);
    lastWall = now;
    wallClock += wallDt;
    if (adaptive && ORDER.includes(tierName) && governor.sample(now, wallDt * 1000)) {
      const next = ORDER[ORDER.indexOf(tierName) + 1];
      if (next) {
        tierName = next;
        tier = TIERS[next];
        applyTier();
        onQuality(next);
      }
    }
    return wallDt;
  }

  // Pass flights, re-drawn from the facts the data holds (who passed, when, to whom, when it
  // arrived) with how a ball really travels: off the foot fast, slowing as it rolls (exponential
  // decay), lofted on an arc when the pass is long, arriving at the receiver's feet at the moment
  // the data says it arrived. The tracking stays the truth for analytics; this is how it is drawn.
  const flights = buildFlights(feed);
  let flight = null; // the pass in the air at the current time, if any
  function flightAt(t) {
    let lo = 0;
    let hi = flights.length - 1;
    let hit = null;
    while (lo <= hi) {
      const mid = (lo + hi) >> 1;
      if (flights[mid].t0 <= t) {
        hit = flights[mid];
        lo = mid + 1;
      } else hi = mid - 1;
    }
    return hit && t <= hit.t1 ? hit : null;
  }
  function placeFlight(f, t) {
    const dur = (f.t1 - f.t0) / 1000;
    const tau = THREE.MathUtils.clamp((t - f.t0) / (f.t1 - f.t0), 0, 1);
    const k = PASS_DECAY * dur;
    const s = (1 - Math.exp(-k * tau)) / (1 - Math.exp(-k));
    const end = trackAt(f.to, f.t1);
    const ex = end ? end.x - f.dirX * 0.35 : f.endX;
    const ez = end ? end.z - f.dirZ * 0.35 : f.endZ;
    return [f.fromX + (ex - f.fromX) * s, 0.11 + f.loft * 4 * tau * (1 - tau), f.fromZ + (ez - f.fromZ) * s];
  }

  function placeBall(t) {
    flight = flightAt(t);
    if (flight) {
      const [fx, fy, fz] = placeFlight(flight, t);
      ball.position.set(fx, fy, fz);
      const moved = ball.position.distanceTo(ballPrev);
      if (moved > 0 && moved < 5) {
        const axis = new THREE.Vector3(fz - ballPrev.z, 0, -(fx - ballPrev.x)).normalize();
        ball.rotateOnWorldAxis(axis, moved / 0.11);
      }
      ballPrev.copy(ball.position);
      return;
    }
    const [a, b, u] = frameAt(feed, t);
    const ba = feed.b[a];
    const bb = feed.b[b];
    const [bx, bz] = toWorld((ba[0] + (bb[0] - ba[0]) * u) / 10, (ba[1] + (bb[1] - ba[1]) * u) / 10);
    const by = Math.max(0.11, (ba[2] + (bb[2] - ba[2]) * u) / 10 + 0.11);
    ball.position.set(bx, by, bz);
    const moved = ball.position.distanceTo(ballPrev);
    if (moved > 0 && moved < 5) {
      const axis = new THREE.Vector3(bz - ballPrev.z, 0, -(bx - ballPrev.x)).normalize();
      ball.rotateOnWorldAxis(axis, moved / 0.11);
    }
    ballPrev.copy(ball.position);
  }

  // tracking position and velocity of one slot at time t (spline-smoothed; null when off the pitch)
  function trackAt(slot, t) {
    const [a, b, u, span] = frameAt(feed, t);
    const pa = feed.p[a];
    const pb = feed.p[b];
    const xa = pa[2 * slot];
    const xb = pb[2 * slot];
    if (xa === EMPTY || xb === EMPTY) return null; // a sent-off player; negative positions are real
    const ya = pa[2 * slot + 1];
    const yb = pb[2 * slot + 1];
    const jump = Math.hypot(xb - xa, yb - ya) / 10 > 3; // a teleport in the data is never animated
    if (jump) {
      const [x, z] = toWorld((u < 0.5 ? xa : xb) / 10, (u < 0.5 ? ya : yb) / 10);
      return { x, z, vx: 0, vz: 0, jump };
    }
    const p0 = feed.p[Math.max(0, a - 1)];
    const p3 = feed.p[Math.min(feed.p.length - 1, b + 1)];
    const x0 = p0[2 * slot] !== EMPTY ? p0[2 * slot] : xa;
    const y0 = p0[2 * slot + 1] !== EMPTY ? p0[2 * slot + 1] : ya;
    const x3 = p3[2 * slot] !== EMPTY ? p3[2 * slot] : xb;
    const y3 = p3[2 * slot + 1] !== EMPTY ? p3[2 * slot + 1] : yb;
    const [x, z] = toWorld(spline(x0, xa, xb, x3, u) / 10, spline(y0, ya, yb, y3, u) / 10);
    const vx = splineVel(x0, xa, xb, x3, u, span) / 10;
    const vz = splineVel(y0, ya, yb, y3, u, span) / 10;
    // bodies stop at the netting: a player tracked over the line inside the goal mouth (a scorer
    // running on after a tap-in) is held at the goal line, never drawn through the net
    if (Math.abs(x) > L / 2 - GOAL_CLEAR && Math.abs(z) < GOAL_HALF + 0.5) {
      return { x: Math.sign(x) * (L / 2 - GOAL_CLEAR), z, vx: 0, vz, jump };
    }
    return { x, z, vx, vz, jump };
  }

  // who wears each slot's shirt at time t (substitutions change it)
  function identityAt(slot, t) {
    const side = feed.slots[slot] === feed.teams.home.id ? "home" : "away";
    let who = feed.teams[side].players[String(slot)] ?? null;
    for (const ch of feed.changes ?? []) if (ch.slot === slot && ch.t <= t && ch.id) who = feed.players[ch.id];
    return who;
  }

  // the live (or replayed) match at time t
  function poseMatch(t, matchDt, snapAll) {
    placeBall(t);
    for (const ch of feed.changes ?? []) {
      const who = identityAt(ch.slot, t);
      if (who) players[ch.slot].setIdentity(who.name, who.num);
    }
    const cutNow = cuts.some((c) => lastCutCheck < c && c <= t);
    lastCutCheck = t;
    for (let slot = 0; slot < players.length; slot++) {
      const pl = players[slot];
      const tr = trackAt(slot, t);
      pl.root.visible = Boolean(tr);
      if (!tr) continue;
      pl.update({
        ...tr, ballX: ball.position.x, ballZ: ball.position.z, tMs: t, dt: matchDt,
        event: eventNear(events[slot], t), snap: snapAll || cutNow || matchDt === 0 || tr.jump,
      });
    }
    attachBall(t);
  }

  const spot = new THREE.Vector3();
  let paint = true; // motion QA steps the match without drawing pixels
  // Ball truth, as sports games solve it: the tracked ball is a point, the animated feet are not.
  //  - around an action's contact frame the ball is drawn onto the striking bone (foot, head),
  //    so the foot meets the ball and the ball leaves along the tracked flight;
  //  - a keeper's catch holds it in the gloves;
  //  - a player running with it dribbles: touches on the stride, the ball rolling out ahead;
  //  - a player standing with it keeps it just ahead of his feet.
  // The controller is the player nearest the tracked ball while it is on the ground, kept until
  // someone else is clearly closer, so a defender pressing from behind never takes it by a hair.
  let controller = null;
  let controlledSince = 0;
  let frameNo = 0;
  let carriedOn = -1; // the frame on which the controller last held the ball (motion QA)
  let heldMs = 0;
  const drawnPrev = new THREE.Vector3();
  let drawnAt = null; // match time of the last frame the ball was drawn under someone's control
  function attachBall(t) {
    let striker = null;
    for (const pl of players) {
      if (!pl.root.visible || !pl.strike) continue;
      if (!striker || pl.strike.w > striker.strike.w) striker = pl;
    }
    if (striker) {
      const near = Math.hypot(striker.root.position.x - ball.position.x, striker.root.position.z - ball.position.z);
      if (near < 2.5) {
        ball.position.lerp(striker.strikePoint(spot), striker.strike.w);
        return;
      }
    }
    if (flight && t > flight.t0 + 80) {
      controller = null; // a pass on its way belongs to nobody, even rolling past a defender
      drawnAt = null;
      return;
    }
    let nearest = null;
    let best = 1.3;
    for (const pl of players) {
      if (!pl.root.visible) continue;
      const d = Math.hypot(pl.root.position.x - ball.position.x, pl.root.position.z - ball.position.z);
      if (pl.catching && d < 1.5) {
        ball.position.copy(pl.ballSpot(spot)); // a save the keeper holds (a parry leaves, so the rule lets go)
        controller = pl;
        return;
      }
      if (d < best && ball.position.y < 0.6) {
        best = d;
        nearest = pl;
      }
    }
    if (!nearest) {
      controller = null;
      return;
    }
    if (controller !== nearest) {
      const held = controller && controller.root.visible
        ? Math.hypot(controller.root.position.x - ball.position.x, controller.root.position.z - ball.position.z)
        : Infinity;
      if (held > best + 0.35) {
        controller = nearest;
        controlledSince = t;
      }
    }
    const owner = controller ?? nearest;
    carriedOn = frameNo;
    heldMs = t - controlledSince;
    const d = Math.hypot(owner.root.position.x - ball.position.x, owner.root.position.z - ball.position.z);
    const w = THREE.MathUtils.clamp((1.3 - d) / 0.6, 0, 1);
    const carried = THREE.MathUtils.clamp((t - controlledSince) / 500, 0, 1); // ease into a dribble
    const target = owner.speed > 1.4 && !owner.acting ? owner.dribbleSpot(spot, carried) : owner.ballSpot(spot);
    ball.position.lerp(target, w);
    // a ball under control moves no faster than a ball does: when possession changes (a tackle,
    // a block) it is knocked across to the new player over a few frames, never teleported
    const dt = drawnAt === null ? 0 : (t - drawnAt) / 1000;
    if (dt > 0 && dt < 0.25) {
      const step = ball.position.distanceTo(drawnPrev);
      const most = MAX_CONTROLLED_SPEED * dt;
      if (step > most) ball.position.lerpVectors(drawnPrev, ball.position, most / step);
    }
    drawnPrev.copy(ball.position);
    drawnAt = t;
  }

  function finish(wallDt, excitement, focus) {
    frameNo++;
    placeBallShadow();
    grade.uniforms.uTime.value = wallClock % 100;
    animateCrowd(stadium.crowd, wallClock, excitement);
    director.update(focus ?? ball.position, wallDt);
    if (paint) composer.render();
  }

  function render(t, { excitement = null, mode = null } = {}) {
    const wallDt = frameClock();
    const matchDt = lastT === null || t < lastT ? 0 : Math.min(2, (t - lastT) / 1000);
    lastT = t;
    if (mode) director.setMode(mode);
    poseMatch(t, matchDt, false);
    // excitement: danger near either goal, unless the Studio passes its own (goal, big chance)
    const danger = THREE.MathUtils.clamp(1 - (L / 2 - Math.abs(ball.position.x)) / 30, 0, 1);
    const level = excitement ?? danger * 0.6;
    finish(wallDt, level);
    return { excitement: level };
  }

  // ---------------------------------------------------------------- goal package
  const goalEvents = (feed.events ?? []).filter((e) => e[1] === "goal");
  const shotEvents = (feed.events ?? []).filter((e) => e[1] === "shot");
  let activeSeg = null;
  let celebrationStart = null;

  function packageFor(goal) {
    const ev = goalEvents.find((e) => Math.abs(e[0] - goal.t) < 1500);
    const shot = [...shotEvents].reverse().find((e) => e[0] <= goal.t && goal.t - e[0] < 4000);
    const plan = planPackage(goal, shot?.[0]);
    plan.scorer = ev ? ev[2] : shot ? shot[2] : -1;
    // which goal: where the ball was during the strike (the engine may already have reset it at the goal time)
    const [a] = frameAt(feed, plan.strike + 200);
    plan.side = feed.b[a][0] / 10 >= L / 2 ? 1 : -1;
    return plan;
  }

  // Render the package at pt seconds. Returns { label, wipe, done } for the Studio's graphics.
  function renderPackage(plan, pt) {
    const wallDt = frameClock();
    const seg = segmentAt(plan, pt);
    if (!seg) return { done: true };
    const entering = seg !== activeSeg;
    activeSeg = seg;
    if (seg.kind === "wipe") {
      composer.render();
      return { wipe: true, label: "", excitement: 0.6 };
    }
    if (seg.kind === "replay") {
      const t = seg.from + (pt - seg.start) * seg.rate * 1000;
      const matchDt = entering ? 0 : Math.min(0.5, wallDt * seg.rate);
      director.setMode(seg.mode);
      director.lockGoal(plan.side);
      if (entering) director.cut();
      lastT = t;
      poseMatch(t, matchDt, entering);
      finish(wallDt, 0.55);
      return { label: seg.label, slowMotion: seg.rate < 0.5, excitement: 0.55 };
    }
    // celebration
    const t0 = plan.goal.t + 600;
    if (entering || !celebrationStart) {
      celebrationStart = {};
      for (let s = 0; s < players.length; s++) {
        const tr = trackAt(s, t0);
        if (tr) celebrationStart[s] = [tr.x, tr.z];
      }
      placeBall(t0);
    }
    const tc = pt - seg.start;
    const scorer = plan.scorer >= 0 && celebrationStart[plan.scorer] ? plan.scorer : Number(Object.keys(celebrationStart)[0]);
    const poses = celebrationPose(celebrationStart, { scorer, scorerTeam: teamOf[scorer], teamOf, keepers, tc });
    const tMs = t0 + tc * 1000;
    for (let s = 0; s < players.length; s++) {
      const pl = players[s];
      const pose = poses[s];
      pl.root.visible = Boolean(pose);
      if (!pose) continue;
      const cel = pose.celebrate;
      // a celebrating player plays the victory clip from the moment he arrives
      const event = cel === null || cel === undefined ? null : [tMs - cel * 1000, "celebrate", s, "", "", -1, -1, -1, -1, -1];
      pl.update({ x: pose.x, z: pose.z, vx: pose.vx, vz: pose.vz, ballX: ball.position.x, ballZ: ball.position.z,
        tMs, dt: entering ? 0 : wallDt, event, snap: entering });
    }
    director.setMode("tight");
    if (entering) director.cut();
    const focus = new THREE.Vector3(poses[scorer].x, 0, poses[scorer].z);
    finish(wallDt, 1, focus);
    return { label: "", excitement: 1 };
  }

  return {
    render,
    packageFor,
    renderPackage,
    endPackage() {
      activeSeg = null;
      celebrationStart = null;
      lastT = null;
      director.lockGoal(null);
      director.cut();
    },
    get quality() {
      return tierName;
    },
    // a tier by name, or a named tier with overrides ({ base: "high", gtao: false }) for films
    setQuality(q) {
      const base = typeof q === "string" ? q : q?.base || "high";
      if (!TIERS[base]) return;
      tierName = typeof q === "string" ? q : "custom";
      tier = typeof q === "string" ? TIERS[q] : { ...TIERS[base], ...q };
      applyTier();
    },
    setMode: (m) => director.setMode(m),
    // where a player's head is on screen (0..1 from the top left), for broadcast ID tags
    setPaint(on) {
      paint = Boolean(on);
    },
    // motion QA: where the drawn ball sits against the striking bone and the controlling player
    probe() {
      const out = { ball: ball.position.toArray(), strike: null, carry: null, flight: flight ? [flight.t0, flight.t1, flight.to] : null };
      const st = players.find((p) => p.root.visible && p.strike && p.strike.w > 0.95);
      if (st) out.strike = { slot: players.indexOf(st), dist: st.strikePoint(new THREE.Vector3()).distanceTo(ball.position) };
      if (controller && carriedOn === frameNo - 1 && controller.root.visible && ball.position.y < 0.6) {
        const dx = ball.position.x - controller.root.position.x;
        const dz = ball.position.z - controller.root.position.z;
        out.carry = {
          slot: players.indexOf(controller), speed: controller.speed, acting: controller.acting, heldMs,
          ahead: dx * Math.sin(controller.heading) + dz * Math.cos(controller.heading), dist: Math.hypot(dx, dz),
        };
      }
      return out;
    },
    screenOf(slot) {
      const pl = players[slot];
      if (!pl || !pl.root.visible) return null;
      const p = pl.root.position.clone();
      p.y += 2.15;
      p.project(camera);
      if (p.z > 1 || Math.abs(p.x) > 1.1 || Math.abs(p.y) > 1.1) return null;
      return { x: (p.x + 1) / 2, y: (1 - p.y) / 2 };
    },
    // the slot a named player occupies at the current time (names are unique within a match)
    slotOf(name) {
      for (let s = 0; s < players.length; s++) {
        const who = identityAt(s, lastT ?? 0);
        if (who && who.name === name) return s;
      }
      return -1;
    },
    debug: { scene, renderer, bloom, key, rim, camera, director },
    dispose() {
      observer.disconnect();
      renderer.dispose();
    },
  };
}
