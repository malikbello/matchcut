# ADR-0007: A five-season league universe with Dixon-Coles results and squad evolution

- Status: accepted · Date: 2026-10-18 · Extends ADR-0002

## Context
Commentary lives on context: "first away goal in 14", "100th league goal", "unbeaten in 9". That needs years of history that a football fan would believe. Fixed squads over many seasons would not be believable, so the history must evolve the way a real league does.

## Options considered
1. **Two seasons, fixed squads** (D1). Cheap, but no career-scale milestones.
2. **Run the full match engine for every past match.** 1,900 matches at ~30 s each takes hours, for detail nobody reads.
3. **A fast results model plus an off-season model** (chosen).

## Decision
- **Scorelines:** the Dixon-Coles model (Dixon & Coles, 1997). Poisson goal rates from squad strength and home advantage, plus the low-score dependence correction (ρ = −0.13) that fixes the frequency of 0-0, 1-0, 0-1 and 1-1.
- **26 clubs:** 20 in the top flight, 6 in the second tier, with three up and three down every season.
- **Each summer:**
  - Ageing on position-specific curves, peaking at 26 for wingers and AMs, about 27–28 for most outfield roles, 29 for centre-backs and 30 for goalkeepers. Pace peaks two years earlier. This follows published ageing-curve research.
  - Retirements from age 33 (35 for goalkeepers).
  - Transfers weighted towards stronger clubs buying the best younger players of weaker clubs.
  - Academy graduates aged 17–19 fill the 25-man squad plan.
- **Permanent player IDs** (`p00042`) survive transfers. Career history follows the person, not the shirt.
- **The current season's** first 8 matchdays are generated too, so "this season" facts are real. The live match is matchday 9.

## Consequences
- Five seasons (1,900 matches, ~50 transfers, ~190 retirements) generate in seconds and deterministically.
- Checked like a football analyst would: 2.8–3.0 goals per match, 20–26% draws, 5–9% goalless draws, champions on 76–90 points, a "yo-yo" promoted club, a 104-goal striker.
- Player IDs changed format from `<club>-<shirt>` to `p00000`. The contract moved to 1.1 in the same pull request.
