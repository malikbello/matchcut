// Matchcut Studio: one match clock drives the data pitch, the score bug and the verified graphics.
"use strict";

const $ = (id) => document.getElementById(id);
const KIND = {
  goal: ["Goal", "i-goal"], big_chance: ["Big chance", "i-chance"], great_save: ["Big save", "i-save"],
  momentum_swing: ["Momentum", "i-momentum"], press_surge: ["Pressing", "i-press"],
  tactical_shift: ["Pressing harder", "i-press"], speed_peak: ["Top speed", "i-speed"],
  card: ["Card", "i-card"], substitution: ["Substitution", "i-sub"],
};
// one hero number per card: the fact that best tells the moment, and its short label
const HERO = {
  goal: [["expected goals of the shot (0", "xG"]],
  big_chance: [["expected goals of the shot (0", "xG"]],
  great_save: [["expected goals of the shot that was saved", "xG denied"]],
  speed_peak: [["top speed in km/h", "km/h"]],
  tactical_shift: [["opponent passes per defensive action, last", "PPDA now"]],
  momentum_swing: [["momentum", "momentum"]],
};
const RTL = new Set(["ar"]);
// in right-to-left text a score like 1-0 would display as 0-1: keep scores and decimals as left-to-right runs
const LRI = String.fromCharCode(0x2066), PDI = String.fromCharCode(0x2069);
const isolateNumbers = (text, lang) => (RTL.has(lang) ? text.replace(/[0-9]+(?:[.,][0-9]+)?(?:-[0-9]+)?(?: ?xG)?/g, (m) => LRI + m + PDI) : text);
const CUE_SECONDS = 7; // on screen for 7 s of wall time at any replay speed
const PITCH = { L: 105, W: 68 };
// how loud the 3D crowd gets while a moment's card is on screen (0 calm to 1 eruption)
const EXCITEMENT = { goal: 1, big_chance: 0.75, great_save: 0.7, card: 0.45, speed_peak: 0.4 };
const now = () => performance.now();

const state = {
  match: null, feed: null, cues: [], moments: [], t: 0, end: 5400000, playing: true, speed: 15,
  shown: null, shownAt: 0, lastFrame: performance.now(), trail: [], dpr: 1,
  sound: true, audio: new Audio(), view: "3d", show: null,
};
state.audio.addEventListener("playing", () => $("sound").classList.add("speaking"));
state.audio.addEventListener("ended", () => $("sound").classList.remove("speaking"));

function speak(cue) {
  state.audio.pause();
  $("sound").classList.remove("speaking");
  if (!state.sound || !cue.audio) return;
  state.audio.src = `/media/${cue.audio}`;
  state.audio.play().catch(() => {}); // a browser may still block sound until the next click
}

function el(tag, attrs = {}, text) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
  if (text !== undefined) n.textContent = text; // textContent only: never parse data as HTML
  return n;
}
function icon(id) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("class", "icon");
  const use = document.createElementNS("http://www.w3.org/2000/svg", "use");
  use.setAttribute("href", `#${id}`);
  svg.append(use);
  return svg;
}
const clock = (ms) => `${Math.floor(ms / 60000)}:${String(Math.floor(ms / 1000) % 60).padStart(2, "0")}`;

async function api(path, options) {
  const r = await fetch(path, { credentials: "same-origin", ...options });
  if (r.status === 401) { showGate(); throw new Error("unauthorised"); }
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}
function showGate() { $("gate").hidden = false; $("studio").hidden = true; $("live-chip").hidden = true; }
async function enter(code) {
  const r = await fetch("/api/session", {
    method: "POST", credentials: "same-origin",
    headers: { "Content-Type": "application/json" }, body: JSON.stringify({ code }),
  });
  if (!r.ok) throw new Error(r.status === 429 ? "Too many attempts. Wait a minute." : "That code was not recognised.");
}

// ------------------------------------------------------------ data
async function loadMatch(match) {
  state.match = match;
  state.feed = match.feed ? await api(match.feed) : null;
  if (state.feed) {
    const { home, away } = state.feed.teams;
    document.documentElement.style.setProperty("--home", home.kit.primary);
    document.documentElement.style.setProperty("--away", away.kit.primary);
    $("home-code").textContent = home.code; $("away-code").textContent = away.code;
    $("home-kit").style.background = home.kit.primary; $("away-kit").style.background = away.kit.primary;
    state.end = state.feed.t[state.feed.t.length - 1];
  }
  await loadCues();
  seek(0);
  if (state.view === "3d") startShow();
}

// ------------------------------------------------------------ 3D show camera
// Loaded on demand as its own bundle; any failure (no WebGL, a slow device that keeps
// stepping down, a load error) falls back to the 2D data pitch with the same clock.
async function startShow() {
  state.show?.dispose(); state.show = null;
  if (!state.feed) return setView("2d");
  $("show-loading").hidden = false;
  try {
    const mod = await import("./dist/show3d.js");
    if (!mod.webglAvailable()) throw new Error("WebGL2 unavailable");
    state.show = await mod.createShow({
      canvas: $("show"), feed: state.feed, assets: "assets/3d",
      onQuality: (tier) => console.info(`show camera quality: ${tier}`),
    });
    state.show.setMode($("cam").value);
    if (location.hostname === "127.0.0.1") window.__show = state.show; // local tuning only
  } catch (err) {
    console.warn("3D show camera unavailable, using the 2D pitch", err);
    setView("2d");
  } finally {
    $("show-loading").hidden = true;
  }
}
function setView(view) {
  state.view = view;
  const is3d = view === "3d";
  $("view-3d").setAttribute("aria-pressed", String(is3d));
  $("view-2d").setAttribute("aria-pressed", String(!is3d));
  $("show").hidden = !is3d; $("pitch").hidden = is3d; $("cam-wrap").hidden = !is3d;
  if (is3d && !state.show && state.feed) startShow();
  if (!is3d) resize();
}
async function loadCues() {
  state.cues = await api(`/api/matches/${encodeURIComponent(state.match.match_id)}/cues?lang=${$("lang").value}`);
  state.moments = state.cues; // one cue per moment, best available for this language
  if (!state.feed && state.cues.length) state.end = state.cues[state.cues.length - 1].t_ms + 120000;
  drawMarkers();
}

const fact = (cue, start) => (cue.facts || []).find((f) => f.label.startsWith(start));
function teamOf(cue) {
  const club = fact(cue, "club involved");
  if (!club || !state.feed) return "";
  return club.value === state.feed.teams.home.name ? "home" : "away";
}

// ------------------------------------------------------------ clock
function seek(t) {
  state.t = Math.max(0, Math.min(t, state.end));
  state.trail = [];
  state.shown = null;
  $("cue").hidden = true;
  rebuildTimeline();
  updateBug();
}
function tick(now) {
  requestAnimationFrame(tick); // schedule first: one bad frame must never stop the clock
  try { step(now); } catch (err) { console.error(err); }
}
function step(now) {
  const dt = Math.min(now - state.lastFrame, 1000); // keep real time even when frames are slow
  state.lastFrame = now;
  if (state.playing && state.t < state.end) {
    const before = state.t;
    state.t = Math.min(state.end, state.t + dt * state.speed);
    for (const c of state.moments) {
      if (c.t_ms > before && c.t_ms <= state.t) { showCue(c); addToTimeline(c); }
    }
    updateBug();
  }
  if (state.shown && now - state.shownAt > CUE_SECONDS * 1000) hideCue();
  $("progress").style.width = `${(100 * state.t) / state.end}%`;
  $("scrubber").setAttribute("aria-valuenow", String(Math.round(state.t / 1000)));
  $("live-chip").hidden = !state.playing;
  draw();
}

function updateBug() {
  $("clock").textContent = clock(state.t);
  let h = 0, a = 0;
  if (state.feed) {
    for (const g of state.feed.goals) if (g.t <= state.t) { if (g.side === "home") h++; else a++; }
    const poss = state.feed.possession[Math.min(Math.floor(state.t / 60000), state.feed.possession.length - 1)];
    $("poss-home").style.width = `${poss}%`;
  }
  if ($("home-score").textContent !== String(h) || $("away-score").textContent !== String(a)) {
    $("home-score").textContent = String(h); $("away-score").textContent = String(a);
    const box = document.querySelector(".scorebug .score");
    box.classList.remove("bump"); void box.offsetWidth; box.classList.add("bump");
  }
}

// ------------------------------------------------------------ graphics
function hero(cue) {
  for (const [start, label] of HERO[cue.kind] || []) {
    const f = fact(cue, start);
    if (f) return [String(f.value), label];
  }
  const minute = fact(cue, "match minute");
  return minute ? [`${minute.value}'`, "minute"] : null;
}
function showCue(cue) {
  state.shown = cue; state.shownAt = performance.now();
  const box = $("cue");
  box.hidden = true; box.classList.remove("leaving"); void box.offsetWidth;
  const verified = cue.status === "verified";
  box.classList.toggle("verified", verified);
  const [label, iconId] = KIND[cue.kind] || ["Moment", "i-chance"];
  $("cue-kind").textContent = `${cue.clock}  ${label}`;
  $("cue-icon").setAttribute("href", `#${iconId}`);
  $("cue-text").textContent = isolateNumbers(cue.text, cue.language);
  $("cue-text").lang = cue.language;
  box.dir = RTL.has(cue.language) ? "rtl" : "ltr";
  speak(cue);
  const h = hero(cue);
  $("cue-hero").classList.toggle("empty", !h);
  if (h) { $("hero-value").textContent = h[0]; $("hero-label").textContent = h[1]; }
  $("cue-stamp").hidden = !verified; $("cue-pending").hidden = verified;
  $("cue-evidence").setAttribute("aria-expanded", "false"); $("evidence").hidden = true;
  box.hidden = false;
}
function hideCue() {
  const box = $("cue");
  box.classList.add("leaving");
  state.shown = null;
  setTimeout(() => { if (!state.shown) box.hidden = true; }, 130);
}
function showEvidence() {
  const cue = state.shown || state.lastShown;
  if (!cue) return;
  const open = $("evidence").hidden;
  $("evidence").hidden = !open;
  $("cue-evidence").setAttribute("aria-expanded", String(open));
  const cited = new Set(cue.cited_fact_ids);
  $("evidence-list").replaceChildren(...(cue.facts || []).filter((f) => !cited.size || cited.has(f.fact_id)).map((f) => {
    const li = el("li");
    const v = el("span"); v.append(`${f.label}: `, el("span", { class: "v" }, String(f.value)));
    li.append(el("code", {}, f.fact_id), v, el("code", {}, (f.evidence_ids || []).slice(0, 2).join(" · ")));
    return li;
  }));
}
function addToTimeline(cue) {
  const li = el("li", { class: `${cue.status === "verified" ? "verified " : ""}${cue.kind}` });
  li.append(el("span", { class: "t" }, cue.clock), icon((KIND[cue.kind] || [, "i-chance"])[1]), el("span", { class: "x", lang: cue.language }, isolateNumbers(cue.text, cue.language)));
  li.addEventListener("click", () => { seek(cue.t_ms - 4000); });
  $("timeline").prepend(li);
  $("rail-count").textContent = `${$("timeline").children.length} so far`;
}
function rebuildTimeline() {
  $("timeline").replaceChildren();
  for (const c of state.moments) if (c.t_ms <= state.t) addToTimeline(c);
  $("rail-count").textContent = `${$("timeline").children.length} so far`;
}
function drawMarkers() {
  $("markers").replaceChildren(...state.moments.map((c) => {
    const m = el("span", { class: `marker ${c.kind}`, title: `${c.clock} ${(KIND[c.kind] || ["Moment"])[0]}` });
    m.style.left = `${(100 * c.t_ms) / state.end}%`;
    const side = teamOf(c);
    if (side) m.style.background = `var(--${side})`;
    return m;
  }));
}

// ------------------------------------------------------------ data pitch (2D tier)
const canvas = $("pitch");
const ctx = canvas.getContext("2d");
function resize() {
  const r = canvas.getBoundingClientRect();
  state.dpr = Math.min(window.devicePixelRatio || 1, 2);
  canvas.width = Math.round(r.width * state.dpr); canvas.height = Math.round(r.height * state.dpr);
  state.bg = null;
}
function frameAt(t) {
  const ts = state.feed.t;
  let lo = 0, hi = ts.length - 1;
  while (lo < hi) { const mid = (lo + hi + 1) >> 1; if (ts[mid] <= t) lo = mid; else hi = mid - 1; }
  const hi2 = Math.min(lo + 1, ts.length - 1);
  const u = hi2 === lo ? 0 : Math.max(0, Math.min(1, (t - ts[lo]) / (ts[hi2] - ts[lo])));
  return [lo, hi2, u];
}
function rosterAt(t) {
  const slots = {};
  for (const side of ["home", "away"]) for (const [s, p] of Object.entries(state.feed.teams[side].players)) slots[s] = p.id;
  for (const ch of state.feed.changes) if (ch.t <= t) slots[String(ch.slot)] = ch.id;
  return slots;
}
function renderPitch(W, H, d, X, Y, s) {
  const off = document.createElement("canvas");
  off.width = W; off.height = H;
  const c = off.getContext("2d");
  // turf: mowing stripes and a soft floodlit falloff
  c.fillStyle = "#0B2E23"; c.fillRect(0, 0, W, H);
  for (let i = 0; i < 14; i++) {
    c.fillStyle = i % 2 ? "#0E3428" : "#0C2F24";
    c.fillRect(X((i * PITCH.L) / 14), 0, (PITCH.L / 14) * s + 1, H);
  }
  const g = c.createRadialGradient(W / 2, H * 0.45, H * 0.2, W / 2, H / 2, W * 0.75);
  g.addColorStop(0, "rgba(255,255,255,0.05)"); g.addColorStop(1, "rgba(0,0,0,0.45)");
  c.fillStyle = g; c.fillRect(0, 0, W, H);
  // markings
  c.strokeStyle = "rgba(244,246,249,0.55)"; c.lineWidth = 1.6 * d;
  c.strokeRect(X(0), Y(0), PITCH.L * s, PITCH.W * s);
  c.beginPath(); c.moveTo(X(52.5), Y(0)); c.lineTo(X(52.5), Y(68)); c.stroke();
  c.beginPath(); c.arc(X(52.5), Y(34), 9.15 * s, 0, Math.PI * 2); c.stroke();
  for (const [x0, dir] of [[0, 1], [105, -1]]) {
    c.strokeRect(X(dir > 0 ? 0 : 105 - 16.5), Y(34 - 20.16), 16.5 * s, 40.32 * s);
    c.strokeRect(X(dir > 0 ? 0 : 105 - 5.5), Y(34 - 9.16), 5.5 * s, 18.32 * s);
    c.beginPath(); c.arc(X(x0 + dir * 11), Y(34), 9.15 * s, dir > 0 ? -0.93 : Math.PI - 0.93, dir > 0 ? 0.93 : Math.PI + 0.93); c.stroke();
    c.fillStyle = "rgba(244,246,249,0.7)";
    c.beginPath(); c.arc(X(x0 + dir * 11), Y(34), 0.25 * s, 0, Math.PI * 2); c.fill();
    c.strokeRect(X(dir > 0 ? -1.6 : 105), Y(34 - 3.66), 1.6 * s, 7.32 * s);
  }
  return off;
}
function draw() {
  if (state.view === "3d" && state.show && state.feed) {
    const lit = state.shown && fact(state.shown, "player involved");
    const excitement = state.shown && now() - state.shownAt < 6000 ? EXCITEMENT[state.shown.kind] : null;
    state.show.render(state.t, { spotlight: lit ? lit.value : null, excitement });
    return;
  }
  if (state.view === "3d" || !canvas.width || !canvas.height) return; // 3D still loading, or not on screen
  const W = canvas.width, H = canvas.height, d = state.dpr;
  const pad = 0.06 * W;
  const sx = (W - 2 * pad) / PITCH.L, sy = (H - 2 * pad * 0.55) / PITCH.W, s = Math.min(sx, sy);
  const ox = (W - PITCH.L * s) / 2, oy = (H - PITCH.W * s) / 2 + 0.03 * H;
  const X = (x) => ox + x * s, Y = (y) => oy + y * s;
  // the static pitch is pre-rendered once per size; each frame only draws what moves
  if (!state.bg || state.bg.width !== W || state.bg.height !== H) state.bg = renderPitch(W, H, d, X, Y, s);
  ctx.drawImage(state.bg, 0, 0);
  if (!state.feed) return;
  const [a, b, u] = frameAt(state.t);
  const pa = state.feed.p[a], pb = state.feed.p[b];
  const roster = rosterAt(state.t);
  const spotlight = state.shown && fact(state.shown, "player involved");
  const players = [];
  for (let slot = 0; slot < state.feed.slots.length; slot++) {
    if (pa[2 * slot] < 0 || pb[2 * slot] < 0) continue;
    const x = (pa[2 * slot] + (pb[2 * slot] - pa[2 * slot]) * u) / 10;
    const y = (pa[2 * slot + 1] + (pb[2 * slot + 1] - pa[2 * slot + 1]) * u) / 10;
    const side = state.feed.slots[slot] === state.feed.teams.home.id ? "home" : "away";
    const pid = roster[String(slot)];
    players.push({ x, y, side, p: state.feed.players[pid] || { num: "", name: "" } });
  }
  const r = 1.25 * s;
  for (const pl of players) { // contact shadows first
    ctx.fillStyle = "rgba(0,0,0,0.35)";
    ctx.beginPath(); ctx.ellipse(X(pl.x) + 0.3 * s, Y(pl.y) + 0.45 * s, r, r * 0.6, 0, 0, Math.PI * 2); ctx.fill();
  }
  ctx.textAlign = "center"; ctx.textBaseline = "middle";
  ctx.font = `700 ${Math.round(r * 1.05)}px Inter, sans-serif`;
  for (const pl of players) {
    const kit = state.feed.teams[pl.side].kit;
    const lit = spotlight && pl.p.name === spotlight.value;
    if (lit) {
      ctx.strokeStyle = "#FF4A2E"; ctx.lineWidth = 2.5 * d;
      ctx.beginPath(); ctx.arc(X(pl.x), Y(pl.y), r * 2.1, 0, Math.PI * 2); ctx.stroke();
      ctx.fillStyle = "rgba(255,74,46,0.18)"; ctx.fill();
    }
    ctx.fillStyle = kit.primary; ctx.strokeStyle = kit.secondary; ctx.lineWidth = 1.6 * d;
    ctx.beginPath(); ctx.arc(X(pl.x), Y(pl.y), r, 0, Math.PI * 2); ctx.fill(); ctx.stroke();
    ctx.fillStyle = kit.number; ctx.fillText(String(pl.p.num), X(pl.x), Y(pl.y) + 0.5 * d);
    if (lit) {
      ctx.font = `800 ${Math.round(r * 1.5)}px 'Big Shoulders Display', sans-serif`;
      ctx.fillStyle = "#F4F6F9"; ctx.fillText(pl.p.name.toUpperCase(), X(pl.x), Y(pl.y) - r * 3.2);
      ctx.font = `700 ${Math.round(r * 1.05)}px Inter, sans-serif`;
    }
  }
  // ball with a short trail; height lifts it off its shadow
  const ba = state.feed.b[a], bb = state.feed.b[b];
  const bx = (ba[0] + (bb[0] - ba[0]) * u) / 10, by = (ba[1] + (bb[1] - ba[1]) * u) / 10, bz = (ba[2] + (bb[2] - ba[2]) * u) / 10;
  state.trail.push([bx, by]); if (state.trail.length > 14) state.trail.shift();
  ctx.lineCap = "round";
  for (let i = 1; i < state.trail.length; i++) {
    ctx.strokeStyle = `rgba(244,246,249,${(0.35 * i) / state.trail.length})`; ctx.lineWidth = 2 * d * (i / state.trail.length);
    ctx.beginPath(); ctx.moveTo(X(state.trail[i - 1][0]), Y(state.trail[i - 1][1])); ctx.lineTo(X(state.trail[i][0]), Y(state.trail[i][1])); ctx.stroke();
  }
  ctx.fillStyle = "rgba(0,0,0,0.4)";
  ctx.beginPath(); ctx.ellipse(X(bx), Y(by) + 0.2 * s, 0.55 * s, 0.32 * s, 0, 0, Math.PI * 2); ctx.fill();
  ctx.fillStyle = "#FFFFFF";
  ctx.beginPath(); ctx.arc(X(bx), Y(by) - bz * 0.5 * s, 0.55 * s * (1 + bz / 12), 0, Math.PI * 2); ctx.fill();
}

// ------------------------------------------------------------ controls
function setPlaying(on) {
  state.playing = on;
  $("play-icon").setAttribute("href", on ? "#i-pause" : "#i-play");
  $("play").setAttribute("aria-label", on ? "Pause" : "Play");
}
function scrubTo(evt) {
  const r = $("scrubber").getBoundingClientRect();
  seek(((evt.clientX - r.left) / r.width) * state.end);
}
async function start() {
  $("gate").hidden = true; $("studio").hidden = false;
  resize();
  const list = await api("/api/matches");
  $("match").replaceChildren(...list.map((m) => el("option", { value: m.match_id }, m.match_id.toUpperCase())));
  state.list = list;
  if (list.length) await loadMatch(list[0]);
}

document.addEventListener("DOMContentLoaded", () => {
  $("gate-form").addEventListener("submit", async (e) => {
    e.preventDefault(); $("gate-error").hidden = true;
    try { await enter($("code").value); $("code").value = ""; await start(); }
    catch (err) { $("gate-error").textContent = err.message; $("gate-error").hidden = false; }
  });
  $("cue-evidence").addEventListener("click", () => { state.lastShown = state.shown || state.lastShown; showEvidence(); });
  $("play").addEventListener("click", () => setPlaying(!state.playing));
  $("sound").addEventListener("click", () => {
    state.sound = !state.sound;
    $("sound").setAttribute("aria-pressed", String(state.sound));
    $("sound").setAttribute("aria-label", state.sound ? "Commentary sound on" : "Commentary sound off");
    $("sound-icon").setAttribute("href", state.sound ? "#i-sound" : "#i-mute");
    if (!state.sound) { state.audio.pause(); $("sound").classList.remove("speaking"); }
  });
  $("speed").addEventListener("change", () => { state.speed = Number($("speed").value); });
  $("view-3d").addEventListener("click", () => setView("3d"));
  $("view-2d").addEventListener("click", () => setView("2d"));
  $("cam").addEventListener("change", () => state.show?.setMode($("cam").value));
  $("lang").addEventListener("change", async () => { await loadCues(); seek(state.t); });
  $("match").addEventListener("change", () => loadMatch(state.list.find((m) => m.match_id === $("match").value)));
  const scrub = $("scrubber");
  scrub.addEventListener("pointerdown", (e) => { scrub.setPointerCapture(e.pointerId); scrubTo(e); });
  scrub.addEventListener("pointermove", (e) => { if (e.buttons) scrubTo(e); });
  document.addEventListener("keydown", (e) => {
    if ($("studio").hidden || e.target.tagName === "INPUT" || e.target.tagName === "SELECT") return;
    if (e.code === "Space") { e.preventDefault(); setPlaying(!state.playing); }
    if (e.code === "ArrowRight") seek(state.t + 30000);
    if (e.code === "ArrowLeft") seek(state.t - 30000);
  });
  window.addEventListener("resize", resize);
  state.speed = Number($("speed").value);
  setView(state.view);
  requestAnimationFrame(tick);
  start().catch(() => showGate()); // an existing session skips the gate
});
