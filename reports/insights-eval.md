# Insights agents: evaluation

2 simulated matches, the 10 most important moments of each, languages: en + es,fr. Model: Foundry `gpt-5-mini`, Microsoft Agent Framework.

| Measure | Result |
|---|---|
| Moments sent to the agents | 16 |
| Verified on the first draft | 81% |
| Verified after one retry with Verifier feedback | 88% |
| Kept the plain card (failed checks, error or timeout) | 12% |
| Unverified numbers or names that reached the screen | 0 (by construction: only verified lines air) |
| History claims grounded / rejected | 28 / 16 |
| Translations verified / rejected | 28 / 0 |
| Latency to verified line, median / p95 | 13.6 s / 20.5 s |
| Tokens per moment (in / out) | 3289 / 2039 |
| Estimated model cost per moment | $0.00490 |

## What the Verifier caught (first drafts)

- numbers not backed by a cited fact: 4
- names not backed by a cited fact: 2

## Sample verified lines

- `28:00` Kestrel Bay FC have cranked up the press — opponent passes per defensive action down from 1.9 to 1.0 over the last 8 minutes. — cites F-005, F-008, F-007
- `56:31` Obouhal (19) nets a 0.16 xG strike to make it 0-1 after 57 minutes, Glenhaven on just 30% possession. — cites F-006, F-007, F-008, F-002, F-001, F-016
- `58:15` At 59' Maralund (No. 1) denied a 0.27-xG chance, preserving Kestrel Bay FC's 0-1 lead. — cites F-001, F-006, F-007, F-008, F-003, F-002
- `61:53` 62 Obouhal's 0.36 xG big chance offers Glenhaven City a route to equalise while trailing 0-1 — cites F-001, F-006, F-008, F-005, F-002
- `15:09` Valuafon (No.19) breaks the deadlock, 0-1 in the 16th minute with an 0.89 xG finish. — cites F-006, F-007, F-002, F-001, F-008
- `33:27` Valuafon (shirt 19) makes it 0-2 with a 0.02 xG strike; Westcroft United, with 75% possession, still have 0 shots. — cites F-006, F-007, F-002, F-008, F-003, F-012, F-009
- `46:08` Valuafon (No.19) makes it 0-3 for Wexmoor Athletic, despite Westcroft's 77% possession and 0 shots. — cites F-006, F-007, F-002, F-005, F-012, F-009
- `65:42` Westcroft United have 70% possession, 0 shots on target and a momentum swing to 0.98 despite trailing 0-3. — cites F-003, F-010, F-008, F-006, F-002
