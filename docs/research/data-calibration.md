# Research record: how Matchcut's synthetic data was calibrated

**Purpose.** This record lists every published benchmark and method we used to shape the synthetic league and matches, why we chose it, and where it lives in the code. It is updated whenever a calibration changes.

## Validation framework
We validate synthetic data on the **"validation trinity"**:
- **fidelity:** does it look like real football? Measured by `reports/realism.md`.
- **utility:** can downstream systems learn from it? The analytics and AI are scored against the hidden truth.
- **privacy:** no real people. Everything is fictional.

Source: UK Financial Conduct Authority, *Exploring Synthetic Data Validation: privacy, utility and fidelity*.

## Match-level benchmarks (top-flight men's football)
| Measure | Target | Source / basis | Used in |
|---|---|---|---|
| Goals per match | 2.2–3.4 | Long-run Premier League average ≈ 2.8 | `realism.TARGETS`, `history.HOME_BASE/AWAY_BASE` |
| Shot conversion | 8–14% | Premier League since 2003/04 ≈ 10.3%; 2023/24 record 11.88% (Premier League / Opta) | engine finishing |
| Conversion inside / outside the box | 10–17% / 2–6% | 2023/24 sample: 13% inside, 4% outside | engine shot selection |
| Share of shots from outside the box | 35–48% | Same sample: 3,174 of 7,363 shots ≈ 43% | engine `p_shoot` |
| Share of shots blocked | 18–30% | Stats Perform "Shots, Pressure, Clarity": 42% of low-clarity shots blocked | engine blocking |
| Expected goals per match | 2.0–3.6 | Equal to goals on average, by definition of xG | `matchcut_analytics.geometry.expected_goals` |
| Passes / completion | 750–1150 / 76–88% | Typical elite top-flight ranges | engine pass model |
| Fouls / yellow cards | 16–28 / 2–6 | Typical elite top-flight ranges | engine duels |
| Distance per outfield player | 9–12 km per 90 | Published physical-performance studies | engine movement |
| Top sprint speed | 31–37 km/h | Published physical-performance studies | engine `max_speed` |

**A key modelling decision.** xG is calibrated over *all* shots, blocked ones included. The engine therefore decides whether a shot is a goal first, from the true scoring probability, and only then shares the misses between blocks, saves and off-target. This keeps goals equal to xG in every zone of the pitch.

## League and history
| Element | Method | Source |
|---|---|---|
| Scorelines | Dixon-Coles bivariate Poisson with low-score correction (ρ = −0.13) | Dixon & Coles (1997), *Modelling association football scores and inefficiencies in the football betting market* |
| Home advantage | ≈ 45% home wins, 22–26% draws | Long-run top-flight results |
| Ageing curves | Peak ~26 for wingers and AMs, 27–28 for most outfield roles, 29 for CBs, 30 for GKs; pace peaks earlier and declines after 30 | Aging-curve studies (e.g. PMC12551122; ESPN age-curve analysis) |
| Retirements, transfers, academy | From 33 (GK 35); stronger clubs buy younger stars; academy aged 17–19 | Domain convention |

## Analytics methods
| Method | Source |
|---|---|
| Expected goals (distance, angle, header, pressure) | Public open-play xG benchmarks |
| Expected threat (xT), Markov value iteration on a 16 × 12 grid | Karun Singh (2019), *Introducing Expected Threat*; also implemented in `socceraction` (MIT) |
| PPDA, field tilt, possession by passes | Common analytics practice |
| Tactical change detection (CUSUM) | Page (1954) change-point method |

## Data standards
- **Common Data Format (CDF) v1.0** for match sheet, event, tracking, video and metadata (Anzer et al., 2025; arXiv:2505.15820). Planned as the export format.
- **SPADL** (socceraction) as the reference action vocabulary.

## Precedent for data-driven animated broadcasts
- *NFL Toy Story Funday Football* (ESPN, Disney and Beyond Sports, 2023) rendered a live NFL game as animation from tracking data. It won three Sports Emmys and drew 140M+ social views in 24 hours. *The Simpsons Funday Football* followed in 2024.
- This is the precedent for Matchcut's tracking-driven visual style: an established, award-winning way to turn tracking data into shareable video.

## Change log
| Date | Change |
|---|---|
| 2026-10-17 | D1 engine: offside line, low block, longer restarts |
| 2026-10-18 | Goals decided first from true probability; long-shot share; block rate; finishing centred on league average; five-season Dixon-Coles universe |
