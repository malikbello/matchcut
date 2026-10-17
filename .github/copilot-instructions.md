# Matchcut conventions for GitHub Copilot

- Python 3.12 monorepo managed by uv (`packages/*`, `services/*`). Run `uv run ruff format . && uv run ruff check . && uv run pyright && uv run pytest` before proposing changes.
- Data crosses service boundaries only as models from `matchcut_contracts`. Never invent ad-hoc dict shapes; if a contract must change, update the model and regenerate schemas.
- Positions are metres on a 105 × 68 pitch; time is `t_ms` since kick-off. Never mix in pixel or minute units.
- **Code computes every number; AI only explains.** Agents may cite numbers produced by the stats engine, never compute them.
- The simulation must stay deterministic: use the engine's seeded RNG, never `random` module globals or wall-clock time.
- All clubs, players and matches are fictional. Do not add real club, player, league or sponsor names, crests or logos.
- Security: no secrets in code; Azure access uses managed identity / `DefaultAzureCredential`; never enable key-based auth.
- Design: UI uses tokens from `packages/design-tokens/tokens.json`; never hard-code colours.
