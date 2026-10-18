# Matchcut status

**Updated:** Sun 18 Oct 2026 · **Phase:** D3.1 (mature stack and Studio v1) in review

## Done
- **Design:** functional and Azure component diagrams (`docs/architecture`), brand system and board (`docs/brand`), design tokens (`packages/design-tokens/tokens.json`).
- **Decisions:** ADR-0001 to ADR-0006 (`docs/adr`).
- **Azure (dev):** resource group `rg-matchcut-dev` (East US 2); Foundry resource with **gpt-5-mini** deployed (keyless call verified); budget alerts at $5, $10 and $25.
- **Engineering:** uv workspace (Python 3.12, locked); CI (format, lint, types, schema drift, tests with an 80% coverage gate, realism smoke, dependency audit); CodeQL (on when public); Dependabot; PR template; contributing and security policies; Copilot instructions.
- **Contracts v1:** Club, Player, MatchMeta, MatchEvent, TrackingFrame, TruthRecord, with JSON Schema generated in `packages/contracts/schemas`.
- **Simulation:**
  - Harbour League: 20 fictional clubs, 500 players, kit-clash rules.
  - Two past seasons (760 matches) with per-player match lines.
  - Agent-based match engine: 10 Hz tracking, offside line, low block, pressing, tackles, fouls, cards, substitutions, set pieces, hidden tactical change, true shot probabilities.
  - Realism report (`reports/realism.md`).
- **Quality:** 24 tests passing, 88% coverage; ruff and pyright clean.

## Resume here (handoff, 18 Oct)
- D2 merged (#3). D3 PR open from `d3/insights`; merge on green CI.
- Next: D4 (3D show camera with quality tiers + vision lane). First steps: Poly Haven CC0 textures; Blender retarget pipeline (Mixamo private, Quaternius CC0, CMU) onto one rig; Three.js scene.
- Assets (git-ignored, local only): Mixamo in `assets-private/mixamo/`; Quaternius UAL 1+2 and CMU soccer mocap in `assets-cc0/`. Blender installed.

## Done in D3.1 (18 Oct): adopt proven components, Studio v1 (ADR-0011)
- Agents run as a Microsoft Agent Framework workflow; OpenTelemetry tracing to Application Insights (off unless configured).
- Attributed numbers: the Writer lists each number with its fact; the Verifier checks every pairing. House style bans em dashes (also a CI guard).
- Verifier red team: 709 of 709 planted false lines caught, 0 of 128 true lines rejected (`reports/verifier-redteam.md`).
- Live scorecard with Azure AI Evaluation: 88% verified, groundedness 4.57 of 5, relevance 3.93 of 5, about $0.005 per moment (`reports/insights-eval.md`).
- API on standard libraries: Starlette sessions, `limits`, `sse-starlette`; positions feed served pre-compressed; CSP now `'self'` only.
- CDF v0.3.2 export, validated in CI by the official validator (strict).
- Studio v1: event-driven score bug with possession line, live 2D data pitch (the show camera's fallback tier), one match clock with scrubber and team-coloured markers, hero-number lower third, Verified stamp, evidence panel, custom icon set, self-hosted fonts.
- Open: confirm the Studio frame rate on a real laptop GPU (the headless test browser renders at about 1.5 fps on any painting page).

## Done in D3 (18 Oct)
- **Contracts 1.2.0:** `Fact` and `Cue` (verification status, checks, latency).
- **Insights agents** (ADR-0010) on Microsoft Agent Framework 1.22 with Foundry `gpt-5-mini`, keyless: code-built fact sheets and instant plain cards; Analyst ‖ Historian (League Memory over MCP, claims grounded against real tool answers) → Writer → deterministic Verifier (one feedback retry) → Localiser (translations re-verified). Scorecard: `reports/insights-eval.md`.
- **API:** access code → signed HttpOnly SameSite=Strict session; rate limits; strict CSP and security headers; cue replay over SSE.
- **Studio v0:** broadcast lower third with cut-in motion, Verified stamp, evidence panel, four languages, replay speed.
- **Quality:** ruff, pyright and schema drift clean; tests 90% coverage; CI runs with no cloud access (scripted brain).

## Done in D2 (18 Oct)
- **Five-season universe** (ADR-0007): Dixon-Coles results, 26 clubs with promotion and relegation, ageing curves, retirements, transfers, academy; permanent player IDs; current season matchdays 1–8 played, live match on matchday 9.
- **Realism: 14 of 14 measures in range** over 12 matches. Conversion 10.0% (Premier League ~10.3%), inside the box 13.4% (~13%), outside 4.9% (~4%), outside-box share 40.5% (~43%). Research record: `docs/research/data-calibration.md`.
- **Analytics package** (ADR-0008): xG; expected threat trained on our matches (Singh 2019); PPDA, field tilt, momentum, control vs chaos, sprints; moment detector; tactical shifts found with PPDA (tuned on 16 separate matches; held-out precision 83%, recall 62%, `reports/tactical-detection.md`).
- **League Memory:** SQLite (Azure SQL later) + MCP server (official SDK) with 6 read-only tools; every answer carries a query ID and evidence.
- **Data camera** (ADR-0009): Skia broadcast renderer with director, per-frame camera truth and screen boxes for the vision lane.
- **Quality:** 46 tests, 90% coverage; ruff and pyright clean; contracts 1.1.0.

## Next (D4)
1. 3D show camera (Three.js; Low/Medium/High tiers, High default; 2D fallback) driven by tracking.
2. Vision lane (auto-eventing from rendered video, scored against camera truth).

## Decisions log
| Date | Decision |
|---|---|
| 17 Oct | Matchcut approved; solo build; $0 spend; repo private until submission day |
| 17 Oct | Auto-eventing from video in scope; AI narration for the demo film |
| 18 Oct | Show camera animation sources: Mixamo (football actions, raw files kept private, baked into the app, never in the public repo), CMU motion capture, Quaternius CC0; public repo falls back to CMU + Quaternius. Automatic Low/Medium/High quality with 2D fallback; High is the default and the demo standard |
| 18 Oct | Five seasons with squad evolution; show camera (premium stylised 3D) approved; video-game quality on the roadmap |
| 18 Oct | League Memory on MCP SDK 1.x, the range Agent Framework supports (ADR-0010) |
| 18 Oct | Tactical-shift cards state what was measured ("pressing harder", PPDA before and after), not a coach's intent |
| 18 Oct | Agent-based tracking-first engine (ADR-0002); Event Hubs backbone (ADR-0003); Container Apps + Jobs (ADR-0004); keyless security (ADR-0005); uv monorepo (ADR-0006) |
