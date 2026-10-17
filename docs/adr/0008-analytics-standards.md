# ADR-0008: Use established football-analytics methods and data standards

- Status: accepted · Date: 2026-10-18

## Context
Analysts, broadcasters and judges trust numbers they recognise. Home-made formulas invite doubt. The analytics also have to run unchanged on a licensed real feed later.

## Decision
- **One analytics package** (`matchcut_analytics`) that depends **only on the contracts**, never on the simulator. The simulator imports its xG model, so there is one source of truth.
- **Expected goals:** logistic model of distance and goal-mouth angle, with header and pressure penalties, calibrated to public open-play benchmarks.
- **Expected threat (xT):** Karun Singh's (2019) Markov method on a 16 × 12 grid, *trained on our own simulated events*: shot and move probabilities, a transition matrix, and value iteration. Sparse cells are shrunk towards an analytic prior. The same method is implemented in the open-source `socceraction` library (MIT).
- **Pressing:** PPDA, using the conventional defensive-60% zone.
- **Territory and possession:** field tilt and possession share by pass attempts (the common broadcast method).
- **Momentum:** exponentially weighted threat difference; **control vs chaos** from turnover rate and completion.
- **Tactical change detection:** one-sided CUSUM change-point tests on defensive-line height (from tracking) and high-pressure frequency. Scored for precision and recall against the simulator's hidden truth.
- **Synthetic-data validation:** the "validation trinity" of fidelity (the realism report against published benchmarks), utility (downstream detection scored against truth) and privacy (fully fictional).
- **Interoperability (planned):** export events, tracking and metadata in the **Common Data Format (CDF) v1.0** (Anzer et al., 2025; authors from FIFA, DFB and RB Leipzig), so any CDF-aware tool can read Matchcut's feed.

## Consequences
Every number on screen has a recognised definition that we can cite in docs and tooltips. Swapping the synthetic feed for a real one changes the source, not the analytics.
