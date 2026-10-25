# ADR-0015: The Recap Factory makes every fan's film at the whistle, one replica per film

- Status: accepted · Date: 2026-10-25

## Context
"Every fan's cut" means a film for each club and each player a fan can follow, in each voiced language, ready when the match ends: not one film rendered on request while the fan waits. Rendering frames is slow on CPU (ADR-0013), but every fan's film is made of the same few moments.

## Decision
- **Render moments once, assemble films many times.** Each moment clip is rendered once during the match (sliced across replicas) and captioned in every language. A fan's film is its title card, its moments and the end card joined without re-encoding, with the soundtrack mixed in the fan's language: about 25 s on one replica, against an hour of frame rendering.
- **One replica per film, all at once.** A run puts one `fan` message per film on the `cuts` queue; the Container Apps Job's KEDA `azure-queue` rule starts a replica per message (up to 20 at a time), so the films are made side by side. Each replica joins its film, has the QA agent (ADR-0014) check it, and records its timings, its QA verdict and what it cost.
- **Only films with a story.** Each club always gets a film (its fans see the goals against too). A player gets one only with a moment of their own; a title card and an end card are not a film, so the API refuses those cuts and the factory does not make them.
- **Measured cost, list price.** Each film's cost is its replica's lifetime times the job's size (set once in Bicep and passed to the job) at the Container Apps rate, plus the audio seconds and tokens the QA agent used at the Speech and gpt-5-mini rates (Azure Retail Prices API, eastus2).
- **Rationed, because runs spend credit.** One run at a time, a cooldown after each (30 min) and a cap per day (6), claimed atomically in blob storage so two simultaneous presses start one run.
- **Everything on the screen is read back.** `/factory.html` shows the films as a fans by languages grid, replicas at work over time, time to the first and the last film, cost per film and the QA pass rate, all from the run's blobs; any finished film plays there with its QA report.

## Consequences
- Measured locally on 25 Oct: an 80.7 s film took 65 s on one replica (25 s to join and mix, 40 s for the QA agent) and cost US$0.032 at list price (compute US$0.008, QA US$0.024).
- The match in the demo has two goals and no big chances or great saves (its best miss was 0.13 xG), so its run is 21 films: both clubs and the scorer, in seven languages. The other 35 players get no film rather than an empty one.
- Replicas are sized for frame rendering (4 vCPU, 8 GiB) and are oversized for joining; a second, smaller job would cut compute cost per film by about three quarters if runs became frequent.
