# ADR-0002: Synthetic league with an agent-based, tracking-first match engine

- Status: accepted · Date: 2026-10-18

## Context
The product must run on synthetic, football-realistic data, with no real clubs, players or footage. The system needs four things from that data:
- an **event feed** (passes, shots, pressures);
- **10 Hz tracking**, used by the TV renderer and the vision lane;
- **history**, for milestones;
- a **hidden truth** to score every downstream stage against.

## Options considered
1. **Event generator only** (a Markov chain of events). Fast, but there's no tracking, so the vision lane and replays would be impossible, and events and positions could contradict each other.
2. **Generate events, then fabricate tracking around them.** Tracking would be cosmetic and physically inconsistent.
3. **Agent-based simulation, tracking first** (chosen). Players move under tactical targets, and events are *emitted from* the simulated play.

## Decision
Option 3, with these rules:
- **Fixed 0.1 s tick.** Movement is capped by pace-derived top speed (≈ 25–35 km/h) and 4.2 m/s² acceleration.
- **Team shape:**
  - each team positions itself around the ball from its formation and style (press intensity, line height, width, tempo, directness, risk);
  - a compact low block when defending near its own goal;
  - attackers held onside by the second-last defender.
- **Ball-carrier decisions** use explicit football models: a possession-value surface, an expected-goals model, and pass difficulty from distance, lane blocking and receiver pressure.
- **History** for past seasons uses a fast Poisson team-strength model over the *same* squads, so careers stay consistent.
- **Everything is seeded and deterministic:** the same seed gives the same match, byte for byte.
- **Hidden truth** records tactical changes and true shot probabilities.

## Consequences
- Events and tracking agree by construction; tests check pass origins against tracking positions.
- A **realism report** compares simulated matches with top-flight norms (goals, shots, conversion, xG, passes, completion, fouls, cards, distance, top speed). Any engine change must keep it in range.
- A full 90-minute match takes about 30 s on a laptop CPU. Tests use shortened halves through the same code path.
