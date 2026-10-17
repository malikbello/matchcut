# ADR-0006: Python monorepo managed by uv, with shared contracts

- Status: accepted · Date: 2026-10-18

## Context
Seven Python services share data shapes. Drift between them is the most common integration bug.

## Decision
- One repository, a **uv workspace** (`packages/*`, `services/*`), a single lockfile, Python 3.12.
- `packages/contracts` holds immutable Pydantic models; JSON Schema is generated from them and CI fails on drift; TypeScript types for the web app are generated from the same schemas.
- Quality gates: ruff (format + lint), pyright, pytest with an 80% coverage floor.

## Consequences
One command sets up everything (`uv sync`). Contract changes are visible in a single diff across producers and consumers.
