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
- Measured on Azure on 25 Oct (run f-ff39d73ed74f, 20 replicas): the first of 21 films was ready 54 s after the run started (most of it the replicas starting), all 21 in 158 s; US$0.022 a film at list price (compute US$0.004, QA US$0.018). Locally the same 80.7 s film took 65 s.
- The first run on Azure flagged all 7 of the away club's films, and rightly: a goal call that does not fit a 6.5 s conceded clip was left out of the clip but voiced in the fan's film, over the next moment's pictures and with no line on screen. Voices and lines now stay inside the clip they start in, so a fan's film says exactly what its clips show; the next run passed 20 of 21 (the last flag: the recogniser heard no words in two short Naija calls).
- Portuguese is the AI service's weak spot: Azure Speech fast transcription answered 429 "Resource Exhausted" for European or Brazilian Portuguese, one or the other, for hours at a time in our region, even with nothing else running. The QA agent now moves to the other Portuguese recogniser on each retry, and a film that no recogniser can hear is shown as not checked yet rather than flagged; the pass rate counts only films the agent judged.
- Release 00bde40, run f-c4f713c8f14c (25 Oct, 21:30 UTC): 21 films, the first 59 s after the run started, all in 165 s; US$0.022 a film; 20 of 21 passed. The one flag is the away fans' Naija film, where the recogniser heard no words in two short calls.
- More replicas is not faster here: with 24 allowed, all 21 films started together, Azure Speech throttled the QA agent's checks (it waits them out, so nothing failed) and the run took 236 s at twice the compute per film. The job stays at 20.
- The match in the demo has two goals and no big chances or great saves (its best miss was 0.13 xG), so its run is 21 films: both clubs and the scorer, in seven languages. The other 35 players get no film rather than an empty one.
- Replicas are sized for frame rendering (4 vCPU, 8 GiB) and are oversized for joining; a second, smaller job would cut compute cost per film by about three quarters if runs became frequent.
