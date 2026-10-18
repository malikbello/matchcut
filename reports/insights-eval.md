# Insights agents: evaluation

2 simulated matches, the 10 most important moments of each, languages: en + es,fr. Model: Foundry `gpt-5-mini`, Microsoft Agent Framework.

| Measure | Result |
|---|---|
| Moments sent to the agents | 16 |
| Verified on the first draft | 81% |
| Verified after one retry with Verifier feedback | 88% |
| Kept the plain card (failed checks, error or timeout) | 12% |
| Unverified numbers or names that reached the screen | 0 (by construction: only verified lines air) |
| History claims grounded / rejected | 36 / 6 |
| Translations verified / rejected | 28 / 0 |
| Latency to verified line, median / p95 | 18.4 s / 22.5 s |
| Tokens per moment (in / out) | 3480 / 2136 |
| Estimated model cost per moment | $0.00514 |
| Azure AI Evaluation groundedness (1 to 5), mean / pass rate | 4.57 / 93% of 14 |
| Azure AI Evaluation relevance (1 to 5), mean / pass rate | 3.93 / 100% of 14 |

## What the Verifier caught (first drafts)

- numbers not backed by a cited fact: 4
- each number must be listed in order with the cited fact that states it (wrong: 4
- names not backed by a cited fact: 2

## Sample verified lines

- `28:00` Kestrel Bay FC have cranked up pressing: PPDA down 1.9 to 1.0, now pushing to break a 0-0 deadlock at 29'. (cites F-005, F-008, F-007, F-002, F-001)
- `56:31` Obouhal (9) fires a 0.16 xG finish, Glenhaven City lead 0-1 despite Kestrel Bay FC’s 70% possession. (cites F-006, F-007, F-008, F-004, F-002, F-003, F-012)
- `58:15` Maralund at 59 kept Kestrel Bay FC level at 0-1, denying a 0.27 xG chance for Glenhaven City. (cites F-006, F-001, F-005, F-002, F-008, F-004)
- `61:53` 62: Glenhaven's Obouhal has a big 0.36 xG chance, threatening Kestrel Bay while score remains 0-1. (cites F-001, F-005, F-006, F-008, F-002)
- `15:09` Valuafon (29) converts a 0.89 xG chance, Wexmoor Athletic leading 0-1. (cites F-006, F-007, F-008, F-005, F-002)
- `33:27` Valuafon (29) nets a shock 0.02 xG strike, making it 0-2 in the 34th minute. (cites F-006, F-007, F-008, F-002, F-001)
- `46:08` Valuafon’s goal made it 0-3 at 47 minutes, Wexmoor Athletic out of reach for Westcroft United. (cites F-006, F-002, F-001, F-005, F-003)
- `65:42` Minute 66: Westcroft United have surged in momentum by 0.98 despite trailing 0-3, holding 70% possession. (cites F-001, F-003, F-006, F-002, F-010)
