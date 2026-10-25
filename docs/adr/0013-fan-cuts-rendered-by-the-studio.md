# ADR-0013: Fan cuts are rendered by the Studio itself, on a queue-triggered job

- Status: accepted · Date: 2026-10-19

## Context
A fan asks for their own film: their club or one player, in their language, as a phone (9:16) or wide (16:9) video. The film must look exactly like the live show (same stadium, players, replays and graphics), carry the voiced calls and the crowd, and be ready to share. Films take minutes to render, so the request cannot block a web request, and GPUs are not in the budget.

## Decision
- **One renderer, two uses.** The film is drawn by the Studio page itself, opened headless by Playwright with `?render=1`. In render mode the page runs on a virtual clock (`window.__render.frame(spec)`), so every frame is exact and the speed of the machine does not matter. No second renderer to keep in step with the live show.
- **The Editor plans, code decides.** `matchcut_recap.edl` turns the feed, the verified cues and the calls into an edit decision list: title card, run-up to each moment, the goal package (celebration, replays), end card, plus the audio events. Moments are chosen by rules (goals first, then big chances and saves for the fan's side or player), so the film never shows something the data does not hold.
- **Sound is mixed by ffmpeg:** crowd beds, chant swells around danger, roars on goals, the voiced calls with sidechain ducking, loudness normalised to -16 LUFS for phones.
- **Asynchronous on Azure:** `POST /api/cuts` puts the request on the `cuts` Storage Queue; a Container Apps Job with a KEDA `azure-queue` trigger starts one replica per queue message, renders with Mesa llvmpipe on CPU, and writes the film, its plan and its status to the `cuts` blob container. Everything uses the job's managed identity; the storage account has shared keys turned off.
- **Sliced across replicas.** A cut is split into 10 slices and the API puts one queue message per slice; KEDA starts one job replica per message (up to 20 at once, two films, within the 100-core quota). The plan is deterministic, so every replica computes the same frames and renders only its slice, after 2 s of uncaptured warm-up frames so motion matches a straight-through render. The replica that uploads the last slice wins an atomic claim (a conditional blob create), joins the slices without re-encoding, mixes the sound once and publishes. Progress (slices rendered) is what the fan sees.
- **The plan owns every overlay.** Each frame spec names the caption on screen and its age, so a slice renders exactly what a straight-through render would (the first sliced film lost its caption at two seams when this was page state).
- **Backup tasks for late slices**, as MapReduce runs them: once at most a fifth of the slices are missing, one finished replica watches each (an atomic `watch` claim) and renders it too if it runs 1.3 times longer than its own slice. Whichever copy lands first is used; a slow original that finishes after the film is published changes nothing. A slow host or a lost replica then costs minutes instead of the queue's one-hour visibility timeout. Measured on Azure (19 to 21 Oct): slices take 243 to 340 s at about 1.4 s a frame; one slow host took 675 s and doubled the wait to 15 min, which is what this removes.
- **A film quality tier, chosen by measurement.** On CPU at 720x1280 a High frame takes 3.8 s, of which ambient occlusion is 2.1 s; side-by-side stills showed no visible difference at film size, so films render High without it (1.8 s a frame) and keep shadows, bloom and the full crowd. Films never step quality down mid-cut.
- **Built for sharing:** H.264 High profile, capped at 4.5 Mbps (an 80 s film is about 40 MB, SSIM 0.97 against an uncapped encode).
- **Locally,** the same CLI runs as one process (one slice), so development needs no Azure.

## Consequences
- What fans download is what they saw live, frame for frame, in every language with voices.
- CPU rendering is slow per frame (about 1 hour of compute per film); slicing turns that into minutes of waiting, scale is bought with job parallelism rather than GPUs, and the cost stops when the queue is empty.
- The API refuses unknown players and languages, limits cuts per client per hour, and checks every cut id against a strict pattern before any lookup.
