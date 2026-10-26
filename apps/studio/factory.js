// Recap Factory: every fan's film made at the whistle, one Azure Container Apps Job replica per
// film. Everything on this page is read back from the run (blob storage): nothing is simulated.
"use strict";

const $ = (id) => document.getElementById(id);
const ASPECT = "9x16";
const LANGS = {
  en: "English", "en-NG": "Nigerian English", pcm: "Naijá", fr: "Français", es: "Español", pt: "Português", ar: "العربية",
};
const SHORT = { en: "EN", "en-NG": "EN-NG", pcm: "PCM", fr: "FR", es: "ES", pt: "PT", ar: "AR" };
const state = { match: null, run: null, fetchedAt: 0, timer: 0, ticker: 0 };

function el(tag, attrs = {}, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) if (v !== undefined && v !== null) e.setAttribute(k, v);
  e.append(...kids);
  return e;
}
function svg(tag, attrs = {}) {
  const e = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
  return e;
}
function icon(id) {
  const s = svg("svg", { class: "icon", "aria-hidden": "true" });
  s.append(svg("use", { href: `#${id}` }));
  return s;
}
const secs = (s) => (s == null ? "–" : s < 90 ? `${Math.round(s)} s` : `${Math.floor(s / 60)} min ${String(Math.round(s % 60)).padStart(2, "0")} s`);
// lines heard word for word, and lines checked for voice only (Naija; a name and a word or two)
const qaLines = (q) => {
  const heard = q.heard && !q.heard.endsWith("/0") ? `heard ${q.heard}` : "";
  const parts = [heard, q.voiced ? `voiced ${q.voiced}` : ""].filter(Boolean).join(", ") || "no";
  return `${parts.charAt(0).toUpperCase()}${parts.slice(1)} lines`;
};
const dollars = (d) => (d == null ? "–" : d < 0.1 ? `$${d.toFixed(3)}` : `$${d.toFixed(2)}`);

async function api(path, options) {
  const r = await fetch(path, { credentials: "same-origin", ...options });
  if (r.status === 401) { showGate(); throw new Error("unauthorised"); }
  return r;
}
function showGate() { $("gate").hidden = false; $("factory").hidden = true; }
async function enter(code) {
  const r = await fetch("/api/session", {
    method: "POST", credentials: "same-origin",
    headers: { "Content-Type": "application/json" }, body: JSON.stringify({ code }),
  });
  if (!r.ok) throw new Error(r.status === 429 ? "Too many attempts. Wait a minute." : "That code was not recognised.");
}

// ------------------------------------------------------------ data
async function load() {
  const r = await api(`/api/matches/${encodeURIComponent(state.match)}/factory?aspect=${ASPECT}`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  state.run = await r.json();
  state.fetchedAt = performance.now();
  render();
  clearTimeout(state.timer);
  const running = state.run.run && !state.run.finished;
  state.timer = setTimeout(() => load().catch(() => {}), running ? 2000 : 15000);
}

async function startRun() {
  $("f-start").disabled = true;
  $("f-run-note").textContent = "Putting every film on the queue…";
  try {
    const r = await api(`/api/matches/${encodeURIComponent(state.match)}/factory`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ aspect: ASPECT }),
    });
    if (!r.ok) {
      const body = await r.json().catch(() => ({}));
      $("f-run-note").textContent = r.status === 429 && body.detail === "no more runs today"
        ? "That is today's last run: the films below are its films."
        : r.status === 409 ? "A run is making its films now." : r.status === 429 ? "The next run opens soon." : "Could not start a run.";
    }
  } finally {
    await load().catch(() => {});
  }
}

// ------------------------------------------------------------ view
function elapsedNow() {
  const run = state.run;
  if (!run?.run) return 0;
  return run.finished ? run.elapsed : run.elapsed + (performance.now() - state.fetchedAt) / 1000;
}

function render() {
  const run = state.run;
  const films = run.films || [];
  const home = films.find((f) => f.focus.side === "home"), away = films.find((f) => f.focus.side === "away");
  if (home && away) $("f-fixture").textContent = `${home.label} v ${away.label} · full time`;
  const pieces = run.pieces || {};
  const langs = [...new Set(films.map((f) => f.lang))];
  const players = [...new Set(films.filter((f) => f.focus.player).map((f) => f.focus.player))];
  const fans = players.length ? `each club's fans and ${players.length > 3 ? `${players.length} players'` : `${players.join(", ")}'s`}` : "each club's fans";
  $("f-lede").textContent = `At the whistle, ${films.length} films: for ${fans}, in ${langs.length} languages, ` +
    `one render job replica each, side by side on Azure Container Apps. Each film is joined from the ` +
    `${pieces.moments ?? ""} moment clips rendered once during the match, mixed in the fan's language, ` +
    `then listened to and read by the QA agent before any fan sees it.` +
    (films.some((f) => f.ad) ? " Every film is made a second time with audio description, for blind and partially sighted fans, and checked too." : "");

  const c = { waiting: films.length, making: 0, checked: 0, flagged: 0, unchecked: 0, failed: 0, ...run.counts };
  const made = c.checked + c.flagged + c.unchecked;
  // each fan's replica also makes the described film: two films a fan, priced together
  const perFan = films.some((f) => f.ad) ? 2 : 1;
  const described = films.filter((f) => f.ad).length;
  $("s-made").textContent = `${made + described}/${(run.total ?? films.length) * perFan}`;
  $("s-made-label").textContent = perFan === 2 ? "Films made, half of them audio described" : "Films made";
  const peak = run.peak_replicas || 0;
  $("s-replicas").textContent = run.run && !run.finished ? String(c.making) : String(peak);
  $("s-replicas-label").textContent = run.run && !run.finished ? "Replicas at work" : "Replicas at peak";
  $("s-first").textContent = secs(run.first_film_s);
  $("s-all").textContent = run.finished ? secs(run.all_films_s) : run.run ? `${secs(elapsedNow())}…` : "–";
  const cost = run.cost_per_film;
  $("s-cost").textContent = cost ? dollars(cost.total / perFan) : "–";
  $("s-cost-label").textContent = cost
    ? `Per film: compute ${dollars(cost.compute / perFan)}, QA ${dollars(cost.qa / perFan)}`
    : "Per film, list price";
  const judged = c.checked + c.flagged;
  $("s-qa").textContent = judged ? `${c.checked}/${judged}` : "–";
  $("s-qa-label").textContent = c.unchecked ? `Passed QA · ${c.unchecked} not checked yet` : "Passed QA";

  renderButton();
  renderChart();
  renderGrid(films, langs);
  const took = pieces.players ?? 0;
  const without = Math.max(took - players.length, 0);
  $("f-foot").textContent = without
    ? `${without} of the ${took} players who took part have no moment of their own in this match, so no film is made for them. ` +
      `Prices are Azure list prices (eastus2): Container Apps by the second, Speech by the audio hour, gpt-5-mini by the token.`
    : "Prices are Azure list prices (eastus2): Container Apps by the second, Speech by the audio hour, gpt-5-mini by the token.";
}

function renderButton() {
  const run = state.run;
  const running = run.run && !run.finished;
  const wait = run.run ? Math.max(0, run.next_run_in - (performance.now() - state.fetchedAt) / 1000) : 0;
  $("f-start").disabled = running || wait > 0;
  $("f-start").textContent = run.run ? "Run it again" : "Make every fan's film";
  if (running) $("f-run-note").textContent = `Making ${run.total} films: ${secs(elapsedNow())} in.`;
  else if (wait > 0) $("f-run-note").textContent = `Runs use Azure credit: the next one opens in ${secs(wait)}.`;
  else if (run.run) $("f-run-note").textContent = `Last run: ${new Date(run.started * 1000).toLocaleString([], { dateStyle: "medium", timeStyle: "short" })}.`;
  else $("f-run-note").textContent = "One replica per film, all at once.";
}

function renderChart() {
  const chart = $("f-chart");
  const run = state.run;
  const line = run.timeline || [];
  const end = Math.max(elapsedNow(), line.length ? line[line.length - 1][0] : 0, 10);
  const top = Math.max(run.total || 1, 1);
  const W = 800, H = 180, pad = 8;
  const x = (t) => (t / end) * W, y = (v) => H - pad - (v / top) * (H - pad * 2);
  chart.replaceChildren();
  for (let i = 1; i <= 3; i++) chart.append(svg("line", { x1: 0, x2: W, y1: y((top * i) / 4), y2: y((top * i) / 4), class: "grid" }));
  if (!line.length) { $("f-axis-end").textContent = ""; return; }
  const steps = (k) => {
    let d = `M0 ${y(0)}`, last = 0;
    for (const p of line) { d += ` L${x(p[0])} ${y(last)} L${x(p[0])} ${y(p[k])}`; last = p[k]; }
    return { d: `${d} L${x(end)} ${y(last)}`, last };
  };
  const reps = steps(2), made = steps(1);
  chart.append(svg("path", { d: `${reps.d} L${x(end)} ${y(0)} Z`, class: "area replicas" }));
  chart.append(svg("path", { d: made.d, class: "stroke made" }));
  $("f-axis-end").textContent = secs(end);
}

function renderGrid(films, langs) {
  const grid = $("f-grid");
  const rows = new Map();
  for (const f of films) {
    const k = JSON.stringify(f.focus);
    if (!rows.has(k)) rows.set(k, { focus: f.focus, label: f.label, team: f.team, kit: f.kit, cells: {} });
    rows.get(k).cells[f.lang] = f;
  }
  const head = el("tr", {}, el("th", { scope: "col" }, el("span", { class: "sr-only" }, "Fans of")));
  for (const l of langs) head.append(el("th", { scope: "col", title: LANGS[l] || l }, SHORT[l] || l));
  const body = [...rows.values()].map((r) => {
    const sw = el("span", { class: "kit" }); sw.style.background = r.kit || "var(--mist)";
    const who = el("th", { scope: "row" }, sw, el("span", { class: "who" }, r.label),
      el("span", { class: "muted small" }, r.focus.side ? " fans" : ` · ${r.team}`));
    const tr = el("tr", {}, who);
    for (const l of langs) tr.append(el("td", {}, cell(r.cells[l], r.label)));
    return tr;
  });
  grid.replaceChildren(el("thead", {}, head), el("tbody", {}, ...body));
}

function cell(f, label) {
  if (!f) return "";
  const done = f.status === "checked" || f.status === "flagged" || f.status === "unchecked";
  const b = el("button", { type: "button", class: `f-cell ${f.status}`, disabled: done ? null : "" });
  const name = `${label}, ${LANGS[f.lang] || f.lang}`;
  if (f.status === "checked") b.append(icon("i-verified"));
  else if (f.status === "flagged") b.append(icon("i-flag"));
  else if (f.status === "unchecked") b.append(el("span", { class: "pip" }));
  else b.append(el("span", { class: "pip" }));
  b.append(el("span", { class: "t" }, f.at != null ? `${Math.round(f.at)}s` : ""));
  if (f.ad) b.append(el("span", { class: `ad ${f.ad.qa?.passed ? "ok" : "flag"}`, title: "Also made with audio description" }, "AD"));
  b.setAttribute("aria-label", `${name}: ${f.status}`);
  b.title = done ? `${name}: ${f.status}, made ${Math.round(f.at)} s into the run` : `${name}: ${f.status}`;
  if (done) b.addEventListener("click", () => openFilm(f, label));
  return b;
}

function openFilm(f, label, withAd = false) {
  const run = state.run;
  $("f-video").src = `/media/factory/${encodeURIComponent(state.match)}/${ASPECT}/${run.run}/${f.id}${withAd ? ".ad" : ""}.mp4`;
  $("f-film-ad").hidden = !f.ad;
  $("f-film-ad").setAttribute("aria-pressed", String(withAd));
  $("f-film-ad").querySelector("span").textContent = withAd ? "Play without audio description" : "Play with audio description";
  $("f-film-ad").onclick = () => openFilm(f, label, !withAd);
  // the described film has its own QA verdict
  const adStatus = f.ad?.qa ? (f.ad.qa.passed ? "checked" : (f.ad.qa.issues || []).some((i) => i.kind === "not checked") ? "unchecked" : "flagged") : f.status;
  const verdict = { checked: "Checked", flagged: "Flagged", unchecked: "Not checked yet" }[withAd ? adStatus : f.status] || "";
  $("f-film-kicker").textContent = `${LANGS[f.lang] || f.lang}${withAd ? " · Audio described" : ""} · ${verdict}`;
  $("f-film-title").textContent = f.focus.side ? `${label} fans` : label;
  const q = (withAd ? f.ad?.qa : f.qa) || {};
  const facts = [
    withAd && f.ad ? `Audio described: ${f.ad.lines} descriptions in the gaps between the commentary` : "",
    `${f.duration ?? "?"} s film, made in ${Math.round(f.seconds ?? 0)} s on its own replica`,
    `${qaLines(q)}, read ${q.read ?? "?"} captions, ${q.lufs ?? "?"} LUFS`,
    f.cost ? `Cost of this fan's ${f.ad ? "two films" : "film"}: ${dollars(f.cost.total)} (compute ${dollars(f.cost.compute)}, QA ${dollars(f.cost.qa)})` : "",
  ].filter(Boolean);
  const at = (s) => (s == null ? "" : `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")} `);
  const flagged = (q.issues || []).map((i) => el("li", { class: "issue" },
    el("strong", {}, `${at(i.at)}${i.kind}`), " ", el("span", { dir: "auto" }, i.text)));
  $("f-film-facts").replaceChildren(...facts.map((t) => el("li", {}, t)), ...flagged);
  if (!$("f-film").open) $("f-film").showModal();
  $("f-video").play().catch(() => {});
}

// ------------------------------------------------------------ start
async function start() {
  const r = await api("/api/matches");
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  const matches = (await r.json()).filter((m) => m.feed);
  const wanted = new URLSearchParams(location.search).get("match");
  state.match = (matches.find((m) => m.match_id === wanted) || matches[0])?.match_id;
  if (!state.match) return;
  $("gate").hidden = true; $("factory").hidden = false;
  await load();
  clearInterval(state.ticker);
  state.ticker = setInterval(() => { if (state.run?.run) { renderButton(); if (!state.run.finished) { renderChart(); $("s-all").textContent = `${secs(elapsedNow())}…`; } } }, 1000);
}

document.addEventListener("DOMContentLoaded", () => {
  $("gate-form").addEventListener("submit", async (e) => {
    e.preventDefault(); $("gate-error").hidden = true;
    try { await enter($("code").value); $("code").value = ""; await start(); }
    catch (err) { $("gate-error").textContent = err.message; $("gate-error").hidden = false; }
  });
  $("f-start").addEventListener("click", startRun);
  $("f-film-close").addEventListener("click", () => { $("f-video").pause(); $("f-film").close(); });
  $("f-film").addEventListener("close", () => $("f-video").pause());
  start().catch(() => {});
});
