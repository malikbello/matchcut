// Build the Studio's 3D player assets from Quaternius' Universal Animation Library (CC0).
//
//   players.glb  the rigged mannequin with the locomotion clips (idle, walk, jog, sprint)
//   moves.glb    skeleton-only clips for match moments (slide tackle, throw, celebrations)
//
// Clips bind by bone name, so moves.glb plays on the players' skeletons. Unused clips
// are dropped, then everything is pruned, deduplicated, quantised and compressed with
// meshopt (decoded in the browser by three's MeshoptDecoder). Inputs are the GLBs
// from the UAL zips, kept outside git in assets-cc0/quaternius/.
import { NodeIO } from "@gltf-transform/core";
import { ALL_EXTENSIONS } from "@gltf-transform/extensions";
import { dedup, meshopt, prune, quantize, resample } from "@gltf-transform/functions";
import { MeshoptEncoder } from "meshoptimizer";
import { mkdir } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";

const here = path.dirname(fileURLToPath(import.meta.url));
const src = path.resolve(here, "../../../assets-cc0/quaternius");
const out = path.resolve(here, "../assets/3d");

const BUILDS = [
  {
    from: "UAL1_Standard.glb",
    to: "players.glb",
    keepMesh: true,
    clips: ["Idle_Loop", "Walk_Loop", "Jog_Fwd_Loop", "Sprint_Loop", "Jump_Start", "Jump_Loop", "Jump_Land", "Dance_Loop", "Roll"],
  },
  {
    from: "UAL2_Standard.glb",
    to: "moves.glb",
    keepMesh: false,
    clips: ["Slide_Start", "Slide_Loop", "Slide_Exit", "OverhandThrow", "Yes", "Idle_FoldArms_Loop", "Idle_No_Loop"],
  },
];

// The football library: Microsoft Rocketbox footballers (MIT) moved by the Mixamo soccer pack,
// baked by scripts/blender/rocketbox_footballers.py (older builds: the Quaternius body, from
// retarget_library.py). The motion is licensed for use inside the product, not for
// redistribution, so the output goes to a git-ignored folder and deployments fetch it from
// private storage.
import { copyFile, readdir, stat } from "node:fs/promises";
const exists = (p) => stat(p).then(() => true, () => false);
const rocketbox = path.resolve(here, "../../../assets-private/build-rb");
const privateSrc = (await exists(path.join(rocketbox, "football.glb"))) ? rocketbox : path.resolve(here, "../../../assets-private/build");
const privateOut = path.resolve(here, "../assets/private");
const havePrivate = await exists(path.join(privateSrc, "football.glb"));
if (havePrivate) {
  BUILDS.push({ from: "football.glb", to: "football.glb", keepMesh: true, clips: null, src: privateSrc, out: privateOut });
}

await MeshoptEncoder.ready;
const io = new NodeIO().registerExtensions(ALL_EXTENSIONS).registerDependencies({ "meshopt.encoder": MeshoptEncoder });
await mkdir(out, { recursive: true });

for (const b of BUILDS) {
  const doc = await io.read(path.join(b.src ?? src, b.from));
  const root = doc.getRoot();
  if (b.clips) {
    const keep = new Set(b.clips);
    for (const anim of root.listAnimations()) if (!keep.has(anim.getName())) anim.dispose();
    const missing = b.clips.filter((c) => !root.listAnimations().some((a) => a.getName() === c));
    if (missing.length) throw new Error(`${b.from}: clips not found: ${missing.join(", ")}`);
  }
  if (!b.keepMesh) {
    for (const node of root.listNodes()) {
      node.setMesh(null);
      node.setSkin(null);
    }
  }
  await doc.transform(resample(), prune({ keepLeaves: true }), dedup(), quantize(), meshopt({ encoder: MeshoptEncoder, level: "medium" }));
  await mkdir(b.out ?? out, { recursive: true });
  const file = path.join(b.out ?? out, b.to);
  await io.write(file, doc);
  if (b.src === privateSrc) {
    // clip metadata, and for Rocketbox the kit masks and their UV-to-panel fits
    const extras = (await readdir(privateSrc)).filter((f) => f === "football.meta.json" || f === "kits.json" || /^kit_.*\.png$/.test(f));
    for (const f of extras) await copyFile(path.join(privateSrc, f), path.join(privateOut, f));
  }
  const { size } = await import("node:fs").then((fs) => fs.promises.stat(file));
  console.log(`${b.to}: ${root.listAnimations().length} clips, ${(size / 1024).toFixed(0)} KB`);
}
