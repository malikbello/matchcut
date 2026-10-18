// Matchcut show camera: a real-time 3D broadcast of the synthetic match, driven by the
// same 5 Hz tracking feed and match clock as the 2D data pitch (its fallback tier).
//
//   const show = await createShow({ canvas, feed, assets: "assets/3d" });
//   show.render(tMs, { spotlight: "Quinouani", excitement: 0.4 });
import * as THREE from "three";
import { EffectComposer } from "three/addons/postprocessing/EffectComposer.js";
import { OutputPass } from "three/addons/postprocessing/OutputPass.js";
import { RenderPass } from "three/addons/postprocessing/RenderPass.js";
import { UnrealBloomPass } from "three/addons/postprocessing/UnrealBloomPass.js";
import { RoomEnvironment } from "three/addons/environments/RoomEnvironment.js";
import { Director } from "./camera.js";
import { buildPitch, L, toWorld, W } from "./pitch.js";
import { loadRig, Player } from "./players.js";
import { FrameGovernor, ORDER, TIERS, webglAvailable } from "./quality.js";
import { animateCrowd, buildStadium } from "./stadium.js";

export { webglAvailable };

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

export async function createShow({ canvas, feed, assets = "assets/3d", quality = "high", onQuality = () => {} }) {
  if (!webglAvailable()) throw new Error("WebGL2 unavailable");
  let tierName = quality;
  let tier = TIERS[tierName];
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: tier.antialias, powerPreference: "high-performance" });
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.05;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;

  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x070b14);
  scene.fog = new THREE.Fog(0x070b14, 160, 420);
  const pmrem = new THREE.PMREMGenerator(renderer);
  scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
  scene.environmentIntensity = 0.25; // reflections only; the floodlights do the lighting

  // night match under floodlights: a key light high over the main stand, soft fill from the sky
  scene.add(new THREE.HemisphereLight(0xb8c7ff, 0x1b2a1b, 0.55));
  const key = new THREE.DirectionalLight(0xfff3e0, 2.6);
  key.position.set(-40, 90, -60);
  key.shadow.camera.left = -L / 2 - 8;
  key.shadow.camera.right = L / 2 + 8;
  key.shadow.camera.top = W / 2 + 8;
  key.shadow.camera.bottom = -W / 2 - 8;
  key.shadow.camera.far = 260;
  key.shadow.bias = -0.0004;
  key.shadow.normalBias = 0.02;
  scene.add(key, key.target);
  const rim = new THREE.DirectionalLight(0xdfe8ff, 0.9);
  rim.position.set(60, 70, 70);
  scene.add(rim);

  scene.add(buildPitch(renderer));
  const kits = [feed.teams.home.kit.primary, feed.teams.away.kit.primary];
  const stadium = buildStadium({ crowdCount: TIERS.high.crowd, kits });
  scene.add(stadium.group);

  const rig = await loadRig(assets);
  const players = feed.slots.map((clubId, slot) => {
    const side = clubId === feed.teams.home.id ? "home" : "away";
    const p = new Player(rig, feed.teams[side].kit, slot);
    p.root.visible = false;
    scene.add(p.root);
    return p;
  });
  const ball = ballMesh();
  scene.add(ball);

  const camera = new THREE.PerspectiveCamera(30, 16 / 9, 0.5, 900);
  const director = new Director(camera);
  const composer = new EffectComposer(renderer);
  composer.addPass(new RenderPass(scene, camera));
  const bloom = new UnrealBloomPass(new THREE.Vector2(1024, 576), 0.4, 0.45, 0.95); // floodlights and LED boards only
  composer.addPass(bloom);
  composer.addPass(new OutputPass());

  function applyTier() {
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, tier.pixelRatio));
    renderer.shadowMap.enabled = tier.shadows > 0;
    key.castShadow = tier.shadows > 0;
    if (tier.shadows) key.shadow.mapSize.set(tier.shadows, tier.shadows);
    key.shadow.map?.dispose();
    key.shadow.map = null;
    bloom.enabled = tier.bloom;
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
  let wallClock = 0;
  const ballPrev = new THREE.Vector3();

  function render(t, { spotlight = null, excitement = null, mode = null } = {}) {
    const now = performance.now();
    const wallDt = Math.min(0.1, (now - lastWall) / 1000);
    lastWall = now;
    wallClock += wallDt;
    if (governor.sample(now, wallDt * 1000)) {
      const next = ORDER[ORDER.indexOf(tierName) + 1];
      if (next) {
        tierName = next;
        tier = TIERS[next];
        applyTier();
        onQuality(next);
      }
    }
    // match time advanced this frame (seconds); seeking backwards resets smoothing
    const matchDt = lastT === null || t < lastT ? 0 : Math.min(2, (t - lastT) / 1000);
    lastT = t;
    if (mode) director.setMode(mode);

    const [a, b, u, span] = frameAt(feed, t);
    const pa = feed.p[a];
    const pb = feed.p[b];
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

    for (let slot = 0; slot < players.length; slot++) {
      const pl = players[slot];
      const xa = pa[2 * slot];
      const xb = pb[2 * slot];
      if (xa < 0 || xb < 0) {
        pl.root.visible = false;
        continue;
      }
      pl.root.visible = true;
      const ya = pa[2 * slot + 1];
      const yb = pb[2 * slot + 1];
      const [x, z] = toWorld((xa + (xb - xa) * u) / 10, (ya + (yb - ya) * u) / 10);
      const vx = (xb - xa) / 10 / span;
      const vz = (yb - ya) / 10 / span;
      pl.update(x, z, vx, vz, bx, bz, matchDt);
    }

    // excitement: danger near either goal, unless the Studio passes its own (goal, big chance)
    const danger = THREE.MathUtils.clamp(1 - (L / 2 - Math.abs(bx)) / 30, 0, 1);
    animateCrowd(stadium.crowd, wallClock, excitement ?? danger * 0.6);
    director.update(ball.position, wallDt);
    void spotlight;
    composer.render();
  }

  return {
    render,
    get quality() {
      return tierName;
    },
    setQuality(name) {
      if (!TIERS[name]) return;
      tierName = name;
      tier = TIERS[name];
      applyTier();
    },
    setMode: (m) => director.setMode(m),
    debug: { scene, renderer, bloom, key, rim, camera, director },
    dispose() {
      observer.disconnect();
      renderer.dispose();
    },
  };
}
