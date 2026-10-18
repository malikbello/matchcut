# ADR-0010: Insights agents on Microsoft Agent Framework, with a deterministic Verifier

- Status: accepted · Date: 2026-10-18

## Context
Live insight cards must be fast, correct and safe on air. Language models write well but can invent numbers, names and history. A broadcast line that is wrong even once costs trust. The screen must also never wait on a model.

## Options considered
1. **One prompt per moment, with no checks.** Fast to build, but nothing stops a wrong number from airing.
2. **A model judging another model.** Better, but the judge can also be wrong, and its verdicts cannot be explained in one line.
3. **Code computes, agents explain, code verifies** (chosen).

## Decision
- **Fact sheets.** Code turns each moment into numbered facts (`F-001`…): minute, score, names, the moment's metrics and both sides' stats at that instant. Agents never compute.
- **Plain card first.** A template card built only from facts airs the instant a moment is detected.
- **Agents** run on Microsoft Agent Framework (`agent-framework-core` 1.22) with a Foundry-hosted `gpt-5-mini` deployment, signing in keylessly with Entra ID (`DefaultAzureCredential`). Outputs are typed (Pydantic structured outputs).
  - The **Analyst** (what the moment means) and the **Historian** (League Memory over MCP) run in parallel.
  - The **Writer** drafts one line citing fact IDs.
  - The **Localiser** translates verified lines.
- **History grounding.** Every League Memory answer the Historian receives is captured. A history claim becomes a citable fact (`LM-<query id>.<n>`) only if that query really ran and the value appears in its answer.
- **The deterministic Verifier** passes a line only if:
  - every number matches a cited fact (value or code-written label);
  - every proper name belongs to a cited fact;
  - all citations exist;
  - the line is short;
  - it has no betting language or league marks.

  A failed draft gets one retry with the Verifier's feedback; if it fails again, the plain card stays. Translations must keep exactly the source's numbers and names.
- **Failure isolation.** Any model error or timeout leaves the plain card on air.
- **MCP SDK line.** Agent Framework 1.22 supports `mcp>=1.24,<2`. One uv workspace has one resolution, so League Memory uses the 1.x SDK (`FastMCP`). The MCP wire protocol is unchanged, so any MCP client can still connect.

## Consequences
- An unverified number or name cannot reach the screen. This is enforced in code, not left to prompts.
- Every on-air line can be traced to events, moments or history records.
- Tests drive every path with a scripted brain: no network, no credentials in CI.
- Cost and latency are measured by `matchcut-insights eval` (see `reports/insights-eval.md`).
