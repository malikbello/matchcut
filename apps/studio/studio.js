// Matchcut Studio v0: access gate, live cue stream (SSE), verified-line stamp and evidence.
"use strict";

const $ = (id) => document.getElementById(id);
const KIND = {
  goal: "Goal", big_chance: "Big chance", great_save: "Big save", momentum_swing: "Momentum",
  press_surge: "Pressing", tactical_shift: "Pressing", speed_peak: "Top speed", card: "Card", substitution: "Substitution",
};
const STATUS = { verified: "Verified", plain: "Live data", rejected: "Live data" };
let source = null;
let current = null;

function el(tag, attrs = {}, text) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
  if (text !== undefined) n.textContent = text; // textContent only: cue text is never parsed as HTML
  return n;
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

async function loadMatches() {
  const list = await api("/api/matches");
  const sel = $("match");
  sel.replaceChildren(...list.map((m) => el("option", { value: m.match_id }, m.match_id.toUpperCase())));
  return list;
}

function showCue(cue) {
  current = cue;
  const box = $("cue");
  box.hidden = true;
  void box.offsetWidth; // restart the cut-in animation
  box.classList.toggle("verified", cue.status === "verified");
  $("cue-kind").textContent = `${cue.clock} · ${KIND[cue.kind] || "Moment"}`;
  $("cue-text").textContent = cue.text;
  const badge = $("cue-badge");
  badge.textContent = STATUS[cue.status] || "Live data";
  badge.className = cue.status === "verified" ? "badge verified" : "badge";
  $("cue-evidence").setAttribute("aria-expanded", "false");
  $("evidence").hidden = true;
  box.hidden = false;
  $("clock").textContent = cue.clock;
  const score = (cue.facts || []).find((f) => f.label.startsWith("score, "));
  if (score) $("score").textContent = score.value;
}

function showEvidence() {
  if (!current) return;
  const open = $("evidence").hidden;
  $("evidence").hidden = !open;
  $("cue-evidence").setAttribute("aria-expanded", String(open));
  const cited = new Set(current.cited_fact_ids);
  const facts = (current.facts || []).filter((f) => cited.size === 0 || cited.has(f.fact_id));
  $("evidence-list").replaceChildren(
    ...facts.map((f) => {
      const li = el("li");
      li.append(el("code", {}, f.fact_id), el("span", {}, `${f.label}: ${f.value}`),
        el("code", {}, (f.evidence_ids || []).slice(0, 3).join(" · ")));
      return li;
    }),
  );
}

function addToTimeline(cue) {
  const li = el("li", { class: cue.status === "verified" ? "verified" : "" });
  li.append(el("span", { class: "t" }, cue.clock), el("span", { class: "x" }, cue.text));
  li.addEventListener("click", () => showCue(cue));
  const tl = $("timeline");
  tl.prepend(li);
}

function play() {
  if (source) source.close();
  $("timeline").replaceChildren();
  $("cue").hidden = true;
  $("score").textContent = "0-0";
  const match = $("match").value;
  if (!match) return;
  const params = new URLSearchParams({ lang: $("lang").value, speed: $("speed").value });
  source = new EventSource(`/api/matches/${encodeURIComponent(match)}/stream?${params}`);
  $("live-chip").hidden = false;
  source.addEventListener("cue", (e) => {
    const cue = JSON.parse(e.data);
    showCue(cue);
    addToTimeline(cue);
  });
  source.addEventListener("end", () => { source.close(); $("live-chip").hidden = true; });
  source.onerror = () => { $("live-chip").hidden = true; };
}

async function start() {
  $("gate").hidden = true;
  $("studio").hidden = false;
  const list = await loadMatches();
  if (list.length) play();
}

document.addEventListener("DOMContentLoaded", () => {
  $("gate-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    $("gate-error").hidden = true;
    try { await enter($("code").value); $("code").value = ""; await start(); }
    catch (err) { $("gate-error").textContent = err.message; $("gate-error").hidden = false; }
  });
  $("cue-evidence").addEventListener("click", showEvidence);
  for (const id of ["lang", "speed", "match"]) $(id).addEventListener("change", play);
  start().catch(() => showGate()); // an existing session skips the gate
});
