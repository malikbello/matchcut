# Matchcut status

**Updated:** Sun 18 Oct 2026 · **Phase:** D2 complete (branch `d2/history-analytics`)

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

## Resume here (handoff, 17 Oct late evening)
- Branch `d2/history-analytics` is pushed (work in progress, not merged).
- **Re-run when resuming** (interrupted by shutdown): `uv run matchcut-sim eval-tactics --matches 8` (new pressing-window detector) and `uv run matchcut-sim realism --matches 12` (after reverting the global defensive-line change). Both must pass, then open the D2 PR and merge on green CI.
- Assets: Mixamo Soccer Game Pack (54) + 10 extra clips + Y Bot are in `assets-private/mixamo/` (git-ignored, local only). Blender is installed. Still to fetch: Quaternius UAL (CC0), CMU soccer mocap, Poly Haven textures.
- Next: D3 (agents on Foundry + API + Studio), then D4 (3D show camera + vision lane).

## Done in D2 (18 Oct)
- **Five-season universe** (ADR-0007): Dixon-Coles results, 26 clubs with promotion and relegation, ageing curves, retirements, transfers, academy; permanent player IDs; current season matchdays 1–8 played, live match on matchday 9.
- **Realism: 14 of 14 measures in range** over 12 matches. Conversion 10.0% (Premier League ~10.3%), inside the box 13.4% (~13%), outside 4.9% (~4%), outside-box share 40.5% (~43%). Research record: `docs/research/data-calibration.md`.
- **Analytics package** (ADR-0008): xG; expected threat trained on our matches (Singh 2019); PPDA, field tilt, momentum, control vs chaos, sprints; moment detector with a CUSUM tactical-shift test scored against truth.
- **League Memory:** SQLite (Azure SQL later) + MCP server (official SDK v2) with 6 read-only tools; every answer carries a query ID and evidence.
- **Data camera** (ADR-0009): Skia broadcast renderer with director, per-frame camera truth and screen boxes for the vision lane.
- **Quality:** 46 tests, 90% coverage; ruff and pyright clean; contracts 1.1.0.

## Next (D3)
1. Live agents on Foundry with Agent Framework (Analyst ‖ Historian → Writer → Verifier → Localiser) + eval suite.
2. API (SSE) and the Studio screen v0.

## Decisions log
| Date | Decision |
|---|---|
| 17 Oct | Matchcut approved; solo build; $0 spend; repo private until submission day |
| 17 Oct | Auto-eventing from video in scope; AI narration for the demo film |
| 18 Oct | Show camera animation sources: Mixamo (football actions, raw files kept private, baked into the app, never in the public repo), CMU motion capture, Quaternius CC0; public repo falls back to CMU + Quaternius. Automatic Low/Medium/High quality with 2D fallback; High is the default and the demo standard |
| 18 Oct | Five seasons with squad evolution; show camera (premium stylised 3D) approved; video-game quality on the roadmap |
| 18 Oct | Agent-based tracking-first engine (ADR-0002); Event Hubs backbone (ADR-0003); Container Apps + Jobs (ADR-0004); keyless security (ADR-0005); uv monorepo (ADR-0006) |
