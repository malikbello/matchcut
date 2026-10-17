## What and why

<!-- One or two sentences: the change and the reason for it. -->

## How it was checked

- [ ] `uv run ruff format --check . && uv run ruff check . && uv run pyright`
- [ ] `uv run pytest --cov` (coverage ≥ 80%)
- [ ] Contracts changed? Schemas regenerated (`uv run python -m matchcut_contracts.export`)
- [ ] UI changed? Screenshots attached; tokens only, no raw colours
- [ ] Simulation changed? Realism report regenerated

## Risk and rollback

<!-- What could break, and how to undo it. -->
