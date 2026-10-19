# ADR-0013: Fan cuts are rendered by the Studio itself, on a queue-triggered job

- Status: accepted · Date: 2026-10-19

## Context
A fan asks for their own film: their club or one player, in their language, as a phone (9:16) or wide (16:9) video. The film must look exactly like the live show (same stadium, players, replays and graphics), carry the voiced calls and the crowd, and be ready to share. Films take minutes to render, so the request cannot block a web request, and GPUs are not in the budget.

## Decision
- **One renderer, two uses.** The film is drawn by the Studio page itself, opened headless by Playwright with `?render=1`. In render mode the page runs on a virtual clock (`window.__render.frame(spec)`), so every frame is exact and the speed of the machine does not matter. No second renderer to keep in step with the live show.
- **The Editor plans, code decides.** `matchcut_recap.edl` turns the feed, the verified cues and the calls into an edit decision list: title card, run-up to each moment, the goal package (celebration, replays), end card, plus the audio events. Moments are chosen by rules (goals first, then big chances and saves for the fan's side or player), so the film never shows something the data does not hold.
- **Sound is mixed by ffmpeg:** crowd beds, chant swells around danger, roars on goals, the voiced calls with sidechain ducking, loudness normalised to -16 LUFS for phones.
- **Asynchronous on Azure:** `POST /api/cuts` puts the request on the `cuts` Storage Queue; a Container Apps Job with a KEDA `azure-queue` trigger starts one replica per request (at most three at once), renders with Mesa llvmpipe on CPU, and writes the film, its plan and its status to the `cuts` blob container. Everything uses the job's managed identity; the storage account has shared keys turned off.
- **Locally,** the same CLI runs as a background process, so development needs no Azure.

## Consequences
- What fans download is what they saw live, frame for frame, in every language with voices.
- CPU rendering is slow (minutes per film); scale is bought with job parallelism, not GPUs, and the cost stops when the queue is empty.
- The API refuses unknown players and languages, limits cuts per client per hour, and checks every cut id against a strict pattern before any lookup.
