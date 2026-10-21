// Matchcut Studio: one match clock drives the data pitch, the score bug and the verified graphics.
"use strict";

const $ = (id) => document.getElementById(id);
// Render mode (films): the clock is virtual, so every frame of an exported cut is reproducible
const RENDER = new URLSearchParams(location.search).has("render");
let virtualMs = 0;
if (RENDER) performance.now = () => virtualMs;
const KIND = {
  goal: ["Goal", "i-goal"], big_chance: ["Big chance", "i-chance"], great_save: ["Big save", "i-save"],
  momentum_swing: ["Momentum", "i-momentum"], press_surge: ["Pressing", "i-press"],
  tactical_shift: ["Pressing harder", "i-press"], speed_peak: ["Top speed", "i-speed"],
  card: ["Card", "i-card"], substitution: ["Substitution", "i-sub"],
};
// one hero number per card: the fact that best tells the moment, and its short label
// chance quality is shown as fans say it ("9 times in 10"), never as a raw xG decimal
const HERO = {
  goal: [["times in 10 a chance", "in 10 scored"], ["a chance like this is scored once", "tries per goal"]],
  big_chance: [["times in 10 a chance", "in 10 scored"], ["a chance like this is scored once", "tries per goal"]],
  great_save: [["times in 10 a chance", "in 10 scored"], ["a chance like this is scored once", "tries per goal"]],
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
  p2Start: Infinity, sound: true, audio: new Audio(), callAudio: new Audio(), calls: [], view: "3d", show: null, pkg: null,
};
state.audio.addEventListener("playing", () => { $("sound").classList.add("speaking"); state.crowd?.duck(true); });
state.audio.addEventListener("ended", () => { $("sound").classList.remove("speaking"); state.crowd?.duck(false); });
state.callAudio.addEventListener("playing", () => state.crowd?.duck(true));
state.callAudio.addEventListener("ended", () => state.crowd?.duck(false));

// the crowd mix lives in the show bundle; it plays in 2D and 3D, once the viewer has interacted
async function startCrowd() {
  if (state.crowd || state.crowdStarting) return;
  state.crowdStarting = true;
  try {
    const mod = await import("./dist/show3d.js");
    state.crowd = new mod.Crowd("assets/audio/crowd");
    state.crowd.setEnabled(state.sound);
    await state.crowd.start();
  } catch (err) { console.warn("crowd audio unavailable", err); }
}
// 2D excitement: how close the ball is to either goal
function dangerAt(t) {
  if (!state.feed) return 0;
  const [a] = frameAt(t);
  const bx = state.feed.b[a][0] / 10;
  return Math.max(0, Math.min(1, 1 - (PITCH.L / 2 - Math.abs(bx - PITCH.L / 2)) / 30)) * 0.6;
}

// the play-by-play voice: live calls cut in over a co-commentary line still playing
function call(c) {
  if (!state.sound || !c.audio) return;
  state.audio.pause();
  state.callAudio.src = `/media/${c.audio}`;
  state.callAudio.play().catch(() => {});
}
function speak(cue) {
  if (!state.callAudio.paused && !state.callAudio.ended) return; // never talk over a live call
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
// The broadcast clock, by the engine's rule: the timeline is continuous (stoppage time
// included), so the second half restarts at 45:00 from its own kick-off, and added time
// reads 45:00+N / 90:00+N. Minutes follow football: 52:34 is the 53rd minute.
const mmss = (s) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
function elapsed(ms) {
  const second = ms >= state.p2Start;
  return { base: second ? 2700 : 0, s: Math.floor((second ? ms - state.p2Start : ms) / 1000) + (second ? 2700 : 0) };
}
function clock(ms) {
  const { base, s } = elapsed(ms);
  const full = base + 2700;
  return s < full ? mmss(s) : `${full / 60}:00+${Math.floor(s / 60) - full / 60 + 1}`;
}
function minute(ms) {
  const { base, s } = elapsed(ms);
  const full = (base + 2700) / 60;
  const m = Math.floor(s / 60) + 1;
  return m <= full ? `${m}'` : `${full}+${m - full}'`;
}

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
    const p2 = state.feed.period.indexOf(2);
    state.p2Start = p2 >= 0 ? state.feed.t[p2] : Infinity;
  }
  buildCutPanel();
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
      canvas: $("show"), feed: state.feed, assets: "assets/3d", adaptive: !RENDER,
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
// a broadcast ID tag over a player's head (3D view), or hidden when slot < 0
function placeTag(slot, who) {
  const pos = slot >= 0 && who ? state.show.screenOf(slot) : null;
  const tag = $("tag");
  if (!pos) { tag.hidden = true; tag.dataset.slot = ""; return; }
  if (tag.dataset.slot !== String(slot)) {
    tag.dataset.slot = String(slot);
    $("tag-num").textContent = String(who.num);
    $("tag-name").textContent = who.name;
    $("tag-bar").style.background = state.feed.slots[slot] === state.feed.teams.home.id ? "var(--home)" : "var(--away)";
  }
  tag.hidden = false;
  tag.style.left = `${(pos.x * 100).toFixed(2)}%`;
  tag.style.top = `${(pos.y * 100).toFixed(2)}%`;
}
function endPackage() {
  if (!state.pkg) return;
  state.t = Math.max(state.t, state.pkg.goal.t + 1500);
  state.pkg = null;
  state.show?.endPackage();
  $("wipe").hidden = true; $("replay-bug").hidden = true; $("skip-replay").hidden = true;
  $("goal-strap").hidden = true; $("tag").hidden = true;
}
function setView(view) {
  state.view = view;
  const is3d = view === "3d";
  $("view-3d").setAttribute("aria-pressed", String(is3d));
  $("view-2d").setAttribute("aria-pressed", String(!is3d));
  $("show").hidden = !is3d; $("pitch").hidden = is3d; $("cam-wrap").hidden = !is3d;
  if (!is3d) $("tag").hidden = true;
  if (is3d && !state.show && state.feed) startShow();
  if (!is3d) resize();
}
async function loadCues() {
  const id = encodeURIComponent(state.match.match_id);
  const lang = $("lang").value;
  state.calls = await api(`/api/matches/${id}/calls?lang=${lang}`).catch(() => []);
  state.cues = await api(`/api/matches/${id}/cues?lang=${lang}`);
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
  endPackage();
  state.t = Math.max(0, Math.min(t, state.end));
  state.trail = [];
  state.shown = null;
  $("cue").hidden = true;
  rebuildTimeline();
  updateBug();
}
function tick(now) {
  if (RENDER) return; // films are driven frame by frame by window.__render
  requestAnimationFrame(tick); // schedule first: one bad frame must never stop the clock
  try { step(now); } catch (err) { console.error(err); }
}
function step(now) {
  const dt = Math.min(now - state.lastFrame, 1000); // keep real time even when frames are slow
  state.lastFrame = now;
  if (state.pkg) {
    // goal package: celebration and replays play in real time while the match clock holds
    if (state.playing) state.pkg.pt += dt / 1000;
  } else if (state.playing && state.t < state.end) {
    const before = state.t;
    state.t = Math.min(state.end, state.t + dt * state.speed);
    const goal = state.view === "3d" && state.show && state.speed <= 15
      ? (state.feed?.goals ?? []).find((g) => g.t > before && g.t <= state.t) : null;
    if (goal) {
      state.t = goal.t + 600;
      state.pkg = { plan: state.show.packageFor(goal), pt: 0, goal };
    }
    if ((state.feed?.goals ?? []).some((g) => g.t > before && g.t <= state.t + 700)) state.crowd?.goal();
    for (const c of state.moments) {
      if (c.t_ms > before && c.t_ms <= state.t) { showCue(c); addToTimeline(c); }
    }
    // play-by-play: at broadcast speeds only (at 40x the calls would trip over each other)
    if (state.speed <= 15) for (const c of state.calls ?? []) if (c.t_ms > before && c.t_ms <= state.t) call(c);
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
    if (state.pkg) {
      const res = state.show.renderPackage(state.pkg.plan, state.pkg.pt);
      state.crowd?.update(res.excitement ?? 0.6);
      $("wipe").hidden = !res.wipe;
      $("replay-bug").hidden = !res.label;
      $("replay-bug").classList.toggle("slow", Boolean(res.slowMotion));
      $("skip-replay").hidden = false;
      // the scorer's tag and the goal strap ride the celebration
      const celebrating = !res.label && !res.wipe && state.pkg.pt < 7;
      const scorer = state.pkg.plan.scorer;
      const who = scorer >= 0 ? state.feed.players[rosterAt(state.pkg.goal.t)[String(scorer)]] : null;
      placeTag(celebrating && who ? scorer : -1, who);
      $("goal-strap").hidden = !(celebrating && who && state.pkg.pt > 0.6);
      if (who) {
        $("goal-who").textContent = who.name;
        $("goal-min").textContent = minute(state.pkg.goal.t);
      }
      if (res.done) endPackage();
      return;
    }
    const excitement = state.shown && now() - state.shownAt < 6000 ? EXCITEMENT[state.shown.kind] : null;
    const out = state.show.render(state.t, { excitement });
    state.crowd?.update(out?.excitement ?? 0);
    // the player a moment card is about gets a broadcast ID tag while the card is up
    const named = state.shown && now() - state.shownAt < CUE_SECONDS * 1000 && fact(state.shown, "player involved");
    const slot = named ? state.show.slotOf(named.value) : -1;
    placeTag(slot, slot >= 0 ? state.feed.players[rosterAt(state.t)[String(slot)]] : null);
    return;
  }
  state.crowd?.update(state.shown && now() - state.shownAt < 6000 ? EXCITEMENT[state.shown.kind] ?? dangerAt(state.t) : dangerAt(state.t));
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
    if (pa[2 * slot] === -9999 || pb[2 * slot] === -9999) continue; // empty slot (negative positions are real)
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
// ------------------------------------------------------------ render mode (films)
// The recap renderer (services/recap) opens the Studio with ?render and drives it one frame at a
// time: a title card, live run-ups with the verified cards, goal packages, an end card. CSS
// animations are stepped by hand so the cut-ins and wipes land on the same frames every time.
const tracked = new WeakSet();
function stepAnimations(ms) {
  for (const a of document.getAnimations()) {
    if (!tracked.has(a)) {
      tracked.add(a);
      a.pause();
      a.currentTime = 0;
    } else {
      a.currentTime = (a.currentTime ?? 0) + ms;
    }
  }
}
window.__render = {
  async init({ match, lang, aspect, quality = null }) {
    document.body.classList.add("render", `aspect-${aspect}`);
    $("gate").hidden = true; $("studio").hidden = false;
    state.sound = false; state.playing = false;
    $("lang").value = lang;
    const list = await api("/api/matches");
    state.list = list;
    await loadMatch(list.find((m) => m.match_id === match));
    setView("3d");
    while (!state.show) await new Promise((r) => setTimeout(r, 100));
    if (quality) state.show.setQuality(quality);
    return { end: state.end, goals: state.feed.goals, moments: state.moments.length, quality: state.show.quality };
  },
  packageDuration(goalT) {
    const goal = state.feed.goals.find((g) => g.t === goalT);
    return goal ? state.show.packageFor(goal).duration : 0;
  },
  // seg: { kind: "card" | "live" | "package", t, pt, goalT, title, sub }; index counts output frames
  frame(seg, index, fps) {
    virtualMs = (index * 1000) / fps;
    const card = $("film-card");
    card.hidden = seg.kind !== "card";
    document.body.classList.toggle("on-card", seg.kind === "card"); // cards stand alone: no score bug or tags
    if (seg.kind === "card") { $("fc-title").textContent = seg.title || ""; $("fc-sub").textContent = seg.sub || ""; }
    if (seg.kind === "package") {
      const goal = state.feed.goals.find((g) => g.t === seg.goalT);
      if (!state.pkg || state.pkg.goal !== goal) state.pkg = { plan: state.show.packageFor(goal), pt: 0, goal };
      state.pkg.pt = seg.pt;
      state.t = goal.t + 600;
    } else {
      if (state.pkg) endPackage();
      const jumped = state.renderPrev === undefined || seg.t < state.renderPrev || seg.t - state.renderPrev > 2000;
      const before = jumped ? seg.t - 1 : state.renderPrev;
      if (jumped) { state.shown = null; $("cue").hidden = true; state.show.endPackage(); }
      if (seg.cue === undefined && seg.kind === "live") for (const c of state.moments) if (c.t_ms > before && c.t_ms <= seg.t) showCue(c);
      state.t = seg.t;
      state.renderPrev = seg.t;
      if (seg.cue === undefined && state.shown && virtualMs - state.shownAt > CUE_SECONDS * 1000) hideCue();
    }
    // the plan names the caption on screen and its age, so every frame stands alone (films render in slices)
    if (seg.cue !== undefined) {
      const want = seg.cue && state.moments.find((c) => c.moment_id === seg.cue);
      if (want && state.shown?.moment_id !== want.moment_id) showCue(want);
      if (!want && state.shown) { state.shown = null; $("cue").hidden = true; }
      if (want) state.shownAt = virtualMs - seg.cueAge * 1000;
    }
    updateBug();
    draw();
    stepAnimations(1000 / fps);
    return true;
  },
};

// ------------------------------------------------------------ your cut
// A fan's own film: club or player, language, format. The request goes to the render
// job (a queue-triggered Container Apps Job on Azure); the panel follows it until the
// film is ready to watch, download and share. One cut is remembered per tab.
const CUT_LANGS = ["en", "en-NG", "pcm", "fr", "es", "pt", "ar"]; // languages with voiced calls today
const cut = { focus: "side", side: "home", aspect: "9x16", id: null, timer: 0, started: 0 };
const remember = (id) => { try { id ? sessionStorage.setItem("matchcut.cut", id) : sessionStorage.removeItem("matchcut.cut"); } catch { /* storage is optional */ } };
const remembered = () => { try { return sessionStorage.getItem("matchcut.cut"); } catch { return null; } };
function pick(group, attr, value) {
  for (const b of group.querySelectorAll("[role=radio]")) b.setAttribute("aria-checked", String(b.dataset[attr] === value));
}
function buildCutPanel() {
  const feed = state.feed;
  $("cut").hidden = !feed || RENDER;
  if (!feed) return;
  $("cut-clubs").replaceChildren(...["home", "away"].map((side) => {
    const team = feed.teams[side];
    const b = el("button", { type: "button", role: "radio", class: "club", "data-side": side, "aria-checked": String(cut.side === side) });
    const kit = el("span", { class: "kit" }); kit.style.background = team.kit.primary;
    b.append(kit, el("span", { class: "code" }, team.code), el("span", { class: "name" }, team.name));
    b.addEventListener("click", () => { cut.side = side; pick($("cut-clubs"), "side", side); });
    return b;
  }));
  const groups = ["home", "away"].map((side) => {
    const team = feed.teams[side];
    const ids = new Set(Object.values(team.players).map((p) => p.id));
    for (const c of feed.changes || []) if (c.id && feed.slots[c.slot] === team.id) ids.add(c.id);
    const names = [...ids].map((id) => feed.players[id]).filter(Boolean).sort((x, y) => x.num - y.num);
    const g = el("optgroup", { label: team.name });
    g.append(...names.map((pl) => el("option", { value: pl.name }, `${pl.num}  ${pl.name}`)));
    return g;
  });
  $("cut-player").replaceChildren(...groups);
  const labels = Object.fromEntries([...$("lang").options].map((o) => [o.value, o.textContent]));
  $("cut-lang").replaceChildren(...CUT_LANGS.map((l) => el("option", { value: l }, labels[l] || l)));
  $("cut-lang").value = CUT_LANGS.includes($("lang").value) ? $("lang").value : "en";
}
function cutStage(stage, detail = {}) {
  $("cut-progress").hidden = stage !== "working";
  $("cut-result").hidden = stage !== "done";
  $("cut-error").hidden = stage !== "failed";
  $("cut-go").disabled = stage === "working";
  $("cut-go").hidden = stage === "done";
  if (stage === "failed") $("cut-error").textContent = detail.message || "That cut could not be made. Try again.";
  if (stage === "done") {
    const src = `/media/cuts/${cut.id}.mp4`;
    $("cut-video").src = src;
    $("cut-download").href = src;
    $("cut-download").setAttribute("download", `matchcut-${cut.id}.mp4`);
    $("cut-share").hidden = !(navigator.canShare && navigator.canShare({ files: [new File([""], "x.mp4", { type: "video/mp4" })] }));
  }
}
async function followCut() {
  clearTimeout(cut.timer);
  if (!cut.id) return;
  let st;
  try { st = await api(`/api/cuts/${cut.id}`); }
  catch (err) {
    if (String(err.message).includes("404")) { remember(null); cut.id = null; cutStage("idle"); return; }
    cut.timer = setTimeout(followCut, 5000); return; // a blip: keep following
  }
  if (st.status === "done") { remember(null); cutStage("done"); return; }
  if (st.status === "failed") { remember(null); cutStage("failed"); return; }
  const mins = Math.floor((Date.now() - cut.started) / 60000);
  const meter = $("cut-progress").querySelector(".cut-meter");
  const share = st.chunks ? (st.rendered || 0) / st.chunks : null;
  meter.classList.toggle("known", st.status === "rendering" && share !== null);
  if (share !== null) meter.firstElementChild.style.width = `${Math.max(4, share * 100)}%`;
  $("cut-state").textContent = { queued: "In the queue", rendering: "Rendering your film", assembling: "Mixing the sound" }[st.status] || "Working";
  $("cut-hint").textContent = st.status === "queued"
    ? "Renderers are starting in the cloud."
    : st.status === "assembling"
      ? "All scenes drawn. Adding the crowd and the commentary."
      : `${st.chunks ? `${st.rendered || 0} of ${st.chunks} scenes drawn in parallel` : "Every frame drawn in the cloud"}${mins ? `, ${mins} min so far` : ""}. Keep watching the match meanwhile.`;
  cut.timer = setTimeout(followCut, 4000);
}
async function makeCut(e) {
  e.preventDefault();
  if (!state.match) return;
  const body = { match: state.match.match_id, lang: $("cut-lang").value, aspect: cut.aspect };
  if (cut.focus === "player") body.player = $("cut-player").value; else body.side = cut.side;
  cutStage("working");
  $("cut-state").textContent = "Sending your request";
  $("cut-hint").textContent = "";
  const r = await fetch("/api/cuts", {
    method: "POST", credentials: "same-origin",
    headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  if (r.status === 401) { showGate(); return; }
  if (!r.ok) {
    const why = { 429: "You have made a lot of cuts this hour. Try again a little later.", 503: "Cuts are not switched on here." };
    cutStage("failed", { message: why[r.status] });
    return;
  }
  cut.id = (await r.json()).id;
  cut.started = Date.now();
  remember(cut.id);
  followCut();
}
async function shareCut() {
  try {
    const blob = await (await fetch(`/media/cuts/${cut.id}.mp4`, { credentials: "same-origin" })).blob();
    const file = new File([blob], `matchcut-${cut.id}.mp4`, { type: "video/mp4" });
    await navigator.share({ files: [file], title: "My Matchcut" });
  } catch { /* the fan closed the share sheet */ }
}
function wireCutPanel() {
  if (cut.wired) return;
  cut.wired = true;
  $("cut").addEventListener("submit", makeCut);
  for (const b of $("cut").querySelectorAll("[data-focus]")) {
    b.addEventListener("click", () => {
      cut.focus = b.dataset.focus;
      pick(b.parentElement, "focus", cut.focus);
      $("cut-clubs").hidden = cut.focus !== "side";
      $("cut-player-wrap").hidden = cut.focus !== "player";
    });
  }
  for (const b of $("cut").querySelectorAll("[data-aspect]")) {
    b.addEventListener("click", () => { cut.aspect = b.dataset.aspect; pick(b.parentElement, "aspect", cut.aspect); });
  }
  $("cut-share").addEventListener("click", shareCut);
  $("cut-again").addEventListener("click", () => { $("cut-video").removeAttribute("src"); cut.id = null; cutStage("idle"); });
  const resume = remembered();
  if (resume && /^c-[0-9a-f]{12}$/.test(resume)) { cut.id = resume; cut.started = Date.now(); cutStage("working"); followCut(); }
}

async function start() {
  $("gate").hidden = true; $("studio").hidden = false;
  resize();
  const list = await api("/api/matches");
  $("match").replaceChildren(...list.map((m) => el("option", { value: m.match_id }, m.match_id.toUpperCase())));
  state.list = list;
  if (list.length) await loadMatch(list[0]);
  wireCutPanel();
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
    state.crowd?.setEnabled(state.sound);
  });
  $("speed").addEventListener("change", () => { state.speed = Number($("speed").value); });
  $("skip-replay").addEventListener("click", endPackage);
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
    if (e.code === "Escape") endPackage();
    if (e.code === "ArrowRight") seek(state.t + 30000);
    if (e.code === "ArrowLeft") seek(state.t - 30000);
  });
  window.addEventListener("resize", resize);
  state.speed = Number($("speed").value);
  setView(state.view);
  for (const ev of ["pointerdown", "keydown"]) document.addEventListener(ev, startCrowd, { once: true });
  requestAnimationFrame(tick);
  if (!RENDER) start().catch(() => showGate()); // an existing session skips the gate
});
