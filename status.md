# Matchcut status

**Updated:** Sun 18 Oct 2026 · **Phase:** D1, foundations (branch `d1/foundations`)

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

## Next (D2)
1. Match-state engine: xG, possession value, PPDA, field tilt, momentum, control vs chaos.
2. Moment detector.
3. TV camera renderer v0 (tracking → broadcast frames → HLS/MP4).
4. League Memory: Azure SQL schema + MCP server (read-only, parameterised tools).

## Decisions log
| Date | Decision |
|---|---|
| 17 Oct | Matchcut approved; solo build; $0 spend; repo private until submission day |
| 17 Oct | Auto-eventing from video in scope; AI narration for the demo film |
| 18 Oct | Agent-based tracking-first engine (ADR-0002); Event Hubs backbone (ADR-0003); Container Apps + Jobs (ADR-0004); keyless security (ADR-0005); uv monorepo (ADR-0006) |
