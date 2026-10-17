# Contributing

## Setup
```bash
uv sync                      # Python 3.12 workspace, locked dependencies
uv run pytest                # tests
```

## Workflow
- Branch from `main` as `<area>/<short-description>`, open a pull request, and fill in the template.
- CI must pass before merging: format, lint, types, schema drift, tests (≥ 80% coverage), realism smoke and dependency audit.
- Commits are small and descriptive, in the imperative mood ("Add pressure events to the engine").

## Standards
- **Contracts first.** Services exchange only `matchcut_contracts` models. Change a model, regenerate schemas (`uv run python -m matchcut_contracts.export`), and update consumers in the same pull request.
- **Determinism.** Simulation code uses the engine's seeded RNG only.
- **Code computes, AI explains.** No model-generated number reaches the screen without a code-computed source.
- **Fiction only.** No real clubs, players, competitions, sponsors, crests or footage.
- **Design tokens.** UI colours, type, spacing and motion come from `packages/design-tokens/tokens.json`.
- **Decisions.** Significant choices get an ADR in `docs/adr/`.
