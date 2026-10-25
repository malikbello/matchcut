// The pitch: real FIFA dimensions (105 x 68 m), mowing stripes, crisp markings drawn
// once into a high-resolution texture, a run-off apron, and two full-size goals.
// World axes: x along the pitch (0 at the halfway line), z across it, y up.
import * as THREE from "three";

export const L = 105;
export const W = 68;
const APRON = 6; // metres of grass beyond the lines
const PX = 24; // texture pixels per metre

function turfTexture(renderer) {
  const w = Math.round((L + 2 * APRON) * PX);
  const h = Math.round((W + 2 * APRON) * PX);
  const cv = document.createElement("canvas");
  cv.width = w;
  cv.height = h;
  const c = cv.getContext("2d");
  const X = (x) => (x + APRON) * PX;
  const Y = (y) => (y + APRON) * PX;
  c.fillStyle = "#1c5a2c";
  c.fillRect(0, 0, w, h);
  const stripes = 18;
  for (let i = 0; i < stripes; i++) {
    c.fillStyle = i % 2 ? "#2a773b" : "#1c5a2c"; // mowing stripes read strongly on broadcast
    c.fillRect(X(-APRON + (i * (L + 2 * APRON)) / stripes), 0, ((L + 2 * APRON) / stripes) * PX + 1, h);
  }
  // fine grain so the grass never reads as flat paint at broadcast distance
  const img = c.getImageData(0, 0, w, h);
  for (let i = 0; i < img.data.length; i += 4) {
    const n = (Math.random() - 0.5) * 10;
    img.data[i] += n;
    img.data[i + 1] += n * 1.4;
    img.data[i + 2] += n;
  }
  c.putImageData(img, 0, 0);
  // wear, as a pitch looks deep into a season: goalmouths, penalty spots and the centre spot
  const wear = (x, y, rx, ry, a) => {
    const g = c.createRadialGradient(X(x), Y(y), 0, X(x), Y(y), rx * PX);
    g.addColorStop(0, `rgba(122, 104, 64, ${a})`);
    g.addColorStop(1, "rgba(122, 104, 64, 0)");
    c.save();
    c.translate(X(x), Y(y));
    c.scale(1, ry / rx);
    c.translate(-X(x), -Y(y));
    c.fillStyle = g;
    c.fillRect(X(x - rx), Y(y - rx), 2 * rx * PX, 2 * rx * PX);
    c.restore();
  };
  for (const gx of [1.5, L - 1.5]) wear(gx, W / 2, 5, 3.5, 0.42);
  for (const px of [11, L - 11]) wear(px, W / 2, 1.6, 1.6, 0.35);
  wear(L / 2, W / 2, 2.2, 2.2, 0.25);
  // painted lines, not light: off-white and slightly translucent, so floodlights and bloom never
  // make them glow (a glowing penalty spot reads on TV as a second ball)
  c.strokeStyle = "rgba(232,236,228,0.82)";
  c.fillStyle = "rgba(232,236,228,0.82)";
  c.lineWidth = 0.12 * PX;
  c.strokeRect(X(0), Y(0), L * PX, W * PX);
  c.beginPath();
  c.moveTo(X(L / 2), Y(0));
  c.lineTo(X(L / 2), Y(W));
  c.stroke();
  c.beginPath();
  c.arc(X(L / 2), Y(W / 2), 9.15 * PX, 0, Math.PI * 2);
  c.stroke();
  const spot = (x, y) => {
    c.beginPath();
    c.arc(X(x), Y(y), 0.11 * PX, 0, Math.PI * 2); // a 22 cm mark: the size of the ball, never bigger
    c.fill();
  };
  spot(L / 2, W / 2);
  for (const [x0, dir] of [[0, 1], [L, -1]]) {
    c.strokeRect(X(dir > 0 ? 0 : L - 16.5), Y(W / 2 - 20.16), 16.5 * PX, 40.32 * PX);
    c.strokeRect(X(dir > 0 ? 0 : L - 5.5), Y(W / 2 - 9.16), 5.5 * PX, 18.32 * PX);
    spot(x0 + dir * 11, W / 2);
    c.beginPath();
    const a = 0.927;
    c.arc(X(x0 + dir * 11), Y(W / 2), 9.15 * PX, dir > 0 ? -a : Math.PI - a, dir > 0 ? a : Math.PI + a);
    c.stroke();
  }
  for (const [x, y, s] of [[0, 0, 0], [L, 0, Math.PI / 2], [L, W, Math.PI], [0, W, -Math.PI / 2]]) {
    c.beginPath();
    c.arc(X(x), Y(y), 1 * PX, s, s + Math.PI / 2);
    c.stroke();
  }
  const tex = new THREE.CanvasTexture(cv);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.anisotropy = renderer.capabilities.getMaxAnisotropy();
  return tex;
}

function goal(side) {
  const g = new THREE.Group();
  const white = new THREE.MeshStandardMaterial({ color: 0xffffff, roughness: 0.35, metalness: 0.1 });
  const r = 0.06;
  const post = new THREE.CylinderGeometry(r, r, 2.44, 16);
  for (const z of [-3.66, 3.66]) {
    const m = new THREE.Mesh(post, white);
    m.position.set(0, 1.22, z);
    m.castShadow = true;
    g.add(m);
  }
  const bar = new THREE.Mesh(new THREE.CylinderGeometry(r, r, 7.32 + 2 * r, 16), white);
  bar.rotation.x = Math.PI / 2;
  bar.position.set(0, 2.44, 0);
  bar.castShadow = true;
  g.add(bar);
  // net: a light lattice on a box that slopes back, as stadium nets hang
  const netMat = new THREE.MeshStandardMaterial({
    color: 0xffffff, transparent: true, opacity: 0.18, side: THREE.DoubleSide, depthWrite: false, wireframe: true,
  });
  const depth = 2.2;
  const back = new THREE.Mesh(new THREE.PlaneGeometry(7.32, 2.0, 30, 10), netMat);
  back.position.set(-depth, 1.0, 0);
  back.rotation.y = Math.PI / 2;
  g.add(back);
  const roof = new THREE.Mesh(new THREE.PlaneGeometry(depth, 7.32, 10, 30), netMat);
  roof.rotation.x = -Math.PI / 2;
  roof.position.set(-depth / 2, 2.44, 0);
  g.add(roof);
  for (const z of [-3.66, 3.66]) {
    const s = new THREE.Mesh(new THREE.PlaneGeometry(depth, 2.44, 10, 10), netMat);
    s.position.set(-depth / 2, 1.22, z);
    g.add(s);
  }
  g.position.x = side * (L / 2);
  g.rotation.y = side > 0 ? Math.PI : 0;
  return g;
}

export function buildPitch(renderer) {
  const group = new THREE.Group();
  const turf = new THREE.Mesh(
    new THREE.PlaneGeometry(L + 2 * APRON, W + 2 * APRON),
    // grass is velvet-like: blades catch the light at grazing angles, so it gets a sheen
    new THREE.MeshPhysicalMaterial({
      map: turfTexture(renderer), roughness: 0.9, metalness: 0,
      sheen: 0.22, sheenRoughness: 0.6, sheenColor: new THREE.Color(0x5f8f4a),
    }),
  );
  turf.rotation.x = -Math.PI / 2;
  turf.receiveShadow = true;
  group.add(turf);
  group.add(goal(-1), goal(1));
  return group;
}

// feed coordinates (metres, origin at a corner) to world coordinates
export const toWorld = (x, y) => [x - L / 2, y - W / 2];
