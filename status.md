# Matchcut status

**Updated:** Sat 17 Oct 2026, evening WAT · **Phase:** design complete, build starts D1 (Sun 18 Oct)

## Done
- Registered; placeholder project saved on Innovation Studio (bland on purpose).
- Concept chosen: **Matchcut**. Live verified insight + every fan's own voiced highlights film + league history + auto-eventing from video.
- Azure (personal account): free trial, spending limit on, credit to about 16 Nov; budget `matchcut-guardrail`; `rg-matchcut-dev` (East US 2); Foundry `matchcut-ai-4e68` with **gpt-5-mini deployed**; keyless test call passed.
- Tooling: Copilot CLI (logged in as malikbello), PowerShell 7, isolated Azure CLI login (`.azure-config`).
- Rules checklist (`research/04`), architecture (`design/azure-architecture.svg`, `design/concept.svg`), brand system (`research/06`, `design/brand-board.png`), build plan.
- Skill added: `azure-architecture-diagrams` (Microsoft WAF guidance + official icons).

## Next (D1)
1. Malik approves the brand, the architecture and the build plan.
2. Create the private repo `malikbello/matchcut`: protection, CI skeleton, ADRs, contracts, tokens.
3. League + history generator, match engine v0, realism report v0.

## Open items for Malik
- Optional: run the three AI-search questions in the portal gallery for the ~75 projects we haven't seen.

## Decisions log
| Date | Decision |
|---|---|
| 17 Oct | Matchcut approved; solo; $0 only; repo private until submission day |
| 17 Oct | Auto-eventing in scope; Arcas AI narration; may say "Premier League" in narration (no marks) |
| 17 Oct | Ultimate rule: mature multi-expert team; no AI credits; brand before UI |

## Links
Checkpoint files: `DECISION.md`, `research/01–06`, `design/`, `rules/`. Private (never published): `private/`.
