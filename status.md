# Matchcut status

**Updated:** Wed 21 Oct 2026 · **Phase:** D6 (Azure live) on `d5/fan-cuts`; D4 and D5 merged (#8)

## Done
- **Design:** functional and Azure component diagrams (`docs/architecture`), brand system and board (`docs/brand`), design tokens (`packages/design-tokens/tokens.json`).
- **Decisions:** ADR-0001 to ADR-0006 (`docs/adr`).
- **Azure (dev):** resource group `rg-matchcut-dev` (East US 2); Foundry resource with **gpt-5-mini** deployed (keyless call verified); budget alerts at $5, $10 and $25.
- **Engineering:** uv workspace (Python 3.12, locked); CI (format, lint, types, schema drift, tests with an 80% coverage gate, realism smoke, dependency audit); CodeQL (on when public); Dependabot; PR template; contributing and security policies; Copilot instructions.
- **Contracts v1:** Club, Player, MatchMeta, MatchEvent, TrackingFrame, TruthRecord, with JSON Schema generated in `packages/contracts/schemas`.
- **Simulation:**
  - Harbour League: 20 fictional clubs, 500 players, kit-clash rules.
  - Two past seasons (760 matches) with per-player match lines.
  - Agent-based match engine: 10 Hz tracking, offside line, low block, pressing, tackles, fouls, cards, substitutions, set pieces, hidden tactical change, true shot probabilities.
  - Realism report (`reports/realism.md`).
- **Quality:** 24 tests passing, 88% coverage; ruff and pyright clean.

## Resume here (handoff, 22 Oct): Malik's review, waiting for him
Malik reviewed out/review/quinouani-goal-en-9x16.mp4 (Rocketbox players, ball truth, fast assembly) and did not accept it yet. He said do nothing until he is back. Open points, in his words and order:
1. Players' hands point to the back (arm pose: check the Rocketbox Biped arm retarget, clip by clip).
2. Players run into and through the goal net (keep bodies out of the goal frame and net).
3. Passes are not sleek, not like real football (ball flight, pace and the kicking motion).
4. Check every example film frame by frame before presenting it.
5. Make another proper clip: a player scoring a free kick, or a proper dribble.
6. He still cannot see how real users would use this in real life: the fan's journey (live, reel, clip, post) must be shown working, not described.
State: local commits a239875 (realism) and 3114ff5 (moments rendered once, cuts assembled in about 10 s) are pushed on d5/fan-cuts; Azure still runs 049af0a (the image build for a239875 stalled when the laptop slept and was stopped). Not started: Studio reel and Clip that, phone view and sharing, history lines, QA agent, Recap Factory, Azure release of the new pipeline.

## Handoff (21 Oct)
- **Branch `d5/fan-cuts`** (pushed, no PR yet: GitHub Actions is blocked for this account until the monthly minutes reset, so CI runs locally: format, lint, pyright, tests at 87%, Bicep build). Merge only after the local suite is green.
- **First fan film made and checked** (Kestrel Bay, English, 9:16, 80.7 s): -16.4 LUFS. Fixed after review: the Studio clock now follows the engine's rule (it showed raw timeline minutes, 2 min ahead of the verified captions); vertical layout for phones; cards lead with the fan's club or player, in their language; encode capped (92 MB to 41 MB, SSIM 0.97); no overlays on cards.
- **Render speed, measured in the container on CPU:** High 3.8 s a frame (ambient occlusion 2.1 s of it), film tier 1.8 s, invisible difference at film size. The quality governor no longer steps down during films (it was changing quality mid-cut).
- **Scale-out:** a cut is 10 slices, one queue message each, one job replica each (up to 20 at once within the 100-core quota); the last slice wins an atomic blob claim and assembles. Tests cover slicing and single assembly.
- **Images are built with local Docker** (ACR Tasks are not allowed on this subscription; GitHub Actions is blocked by billing) and pushed to `crmatchcutcrjdu4fubxrf6.azurecr.io` with `az acr login` from the isolated config. The release identity's OIDC subject uses GitHub's ID form (`malikbello@139644523/matchcut@1423646206`).
- **Next:** push images, `bash deploy/deploy.sh` with `MATCHCUT_IMAGE_TAG` to create the Studio app and render job, smoke-test, request a cut on Azure and time it; then the PR.
- Malik: an Entra recommendation suggests turning off user consent to apps in the personal tenant; offered to apply it, waiting for his go-ahead.

## Handoff (19 Oct, midday)
- **D5 Export my cut, built:** recap Editor (EDL from the feed, cues and calls), headless renderer on a virtual clock (Playwright, Studio `?render=1`), ffmpeg mix (crowd beds, chant, roars, voiced calls with sidechain ducking, -16 LUFS), CLI `matchcut-recap make`. First film (Kestrel Bay, English, 9:16, about 81 s) rendering locally in `out/cuts/`.
- **Fan cut flow:** `POST /api/cuts` (club or player, language, format; validated, 6 per hour), `GET /api/cuts/{id}`, `GET /media/cuts/{id}.mp4` (byte ranges); Studio "Your cut" panel (watch, download, share). Local back end renders in a background process; Azure back end uses the `cuts` queue and blob container.
- **D6 Azure:** `infra/main.bicep` (Log Analytics, App Insights, ACR Basic, user-assigned identity with least-privilege roles, Storage with shared keys off, `cuts` queue and blob, `showcase` blob, Container Apps environment, Studio app scaled to zero, recap Container Apps Job with a KEDA queue trigger on managed identity). `deploy/deploy.sh` (infra, showcase bundle, `az acr build`, apps, smoke test). `.github/workflows/deploy.yml` (OIDC, gated by the `MATCHCUT_DEPLOY_ENABLED` variable). Base infra deployed to `rg-matchcut-dev` on 19 Oct. Production access code and session key live outside the repo in `inside-the-game/.secrets/matchcut-prod.env`.
- Next: verify the film, regenerate the feed (EMPTY sentinel), build images in ACR, deploy the apps, render a cut on Azure, set up the GitHub OIDC identity.

## Earlier handoff (19 Oct, morning)
- Branch `d4/show-camera` (draft PR #8). Local preview: `matchcut-api` on port 8765 (access code `studio-preview`); `npm run assets && npm run build` in `apps/studio` first.
- **Malik's verdict, 19 Oct: the visuals are far below the standard required.** Next is a full visual overhaul (art direction, characters, stadium, crowd, lighting, grading, broadcast graphics), not more features.
- Engine change pending its realism check: interceptions slow the ball when the interceptor cannot reach it in time (calibrated version), and after a goal the ball rests in the net for 35 s before kick-off positions (the celebration window). Commit only when the 12-match scorecard is 14/14 again.
- After any engine change: regenerate the showcase match (feed, insights, calls, voices); the cues in `out/` were made before it.
- Yoruba, Hausa and Igbo voices are pending for production (see ADR-0012). Captions stay.
- At the end of the build, redraw the architecture diagrams to match what was actually used (Kaggle for voice research, Blender asset pipeline, esbuild Studio bundle, crowd audio, calls route).

## Done in D4 so far (18 to 19 Oct)
- **3D show camera:** Three.js bundled with esbuild (strict CSP kept, plus `wasm-unsafe-eval` for the mesh decoder), floodlit FIFA-size pitch, four-stand stadium, LED boards, reacting crowd, quality tiers with automatic step-down, 2D fallback.
- **Feed v2:** 10 Hz positions, every on-ball event mapped to its player, keeper slots, restart cuts (tests).
- **Animation:** Blender pipeline bakes the Mixamo soccer pack (64 clips, measured speed, direction and contact time; private, never committed); eight-way locomotion blend space with forward gears and a synced phase; players watch the ball and backpedal or side-step; actions aligned to the event's contact frame; keeper kits; spline-smoothed tracking that snaps at restarts.
- **Broadcast:** cameras on the correct touchline (the view had been mirrored), close camera, hard cuts; goal package (celebration, branded wipe, two replay angles with slow motion, REPLAY bug, back to live).
- **Sound:** crowd mix from CC0 stadium recordings (beds, stadium song swelling with danger, five goal roars, brightening filter, ducking under commentary); play-by-play calls in seven languages, voiced with emotion; English Harry and French Marc on MAI-Voice-2.1.
- **Language:** chance quality said as fans say it ("9 times in 10"), never "xG", checked by the Verifier.
- **Audits (scripts in the scratch area):** feed realism (speeds, turns, backwards running) and event consistency (actor to event distance per event type) found the missing events and the interception and goal-reset flaws.
- **Voice research:** YarnGPT2 (too fast), Sunbird Orpheus-3B and Chatterbox auditions run on Kaggle free GPUs; Malik: not good enough yet.

- D3.2 merged (#7, 46ceb23). Work continues on branch `d4/show-camera`.
- Voices chosen 18 Oct: English Harry and French Marc (MAI-Voice-2.1, with mood). Yoruba, Hausa and Igbo voices deferred to a later release after the YarnGPT2 trial (too fast to follow); they stay captions-only (ADR-0012).
- Open: native review of Yoruba (Malik), Hausa, Igbo, Pidgin and Arabic captions; the Localiser leaves football terms such as "press" in English, so it needs a per-language glossary.
- Next: D4 (3D show camera with quality tiers + vision lane). First steps: Poly Haven CC0 textures; Blender retarget pipeline (Mixamo private, Quaternius CC0, CMU) onto one rig; Three.js scene.
- Assets (git-ignored, local only): Mixamo in `assets-private/mixamo/`; Quaternius UAL 1+2 and CMU soccer mocap in `assets-cc0/`. Blender installed.

## Done in D3.2 (18 Oct): voices and languages (ADR-0012)
- Ten languages: English, Nigerian English, Nigerian Pidgin, Yoruba, Hausa, Igbo, Arabic, Spanish, French, Portuguese.
- Spoken commentary (Azure AI Speech, keyless): British and Nigerian English, Pidgin (Nigerian English voice), Arabic, Spanish, French, Portuguese. Showcase match: 33 voiced lines.
- Two-stage pipeline: the verified English line never waits on translations (parallel batches, own budget).
- Studio: language menu, commentary toggle, right-to-left Arabic with scores isolated (1-0 never reads 0-1), fonts for tone marks.
- Open: Yoruba/Hausa/Igbo voices via YarnGPT2 (licence-clean, env ready in scratch); trial waits for free memory. Native review of Yoruba, Hausa, Igbo, Pidgin and Arabic lines (some Yoruba lines keep English football terms).

## Done in D3.1 (18 Oct): adopt proven components, Studio v1 (ADR-0011)
- Agents run as a Microsoft Agent Framework workflow; OpenTelemetry tracing to Application Insights (off unless configured).
- Attributed numbers: the Writer lists each number with its fact; the Verifier checks every pairing. House style bans em dashes (also a CI guard).
- Verifier red team: 709 of 709 planted false lines caught, 0 of 128 true lines rejected (`reports/verifier-redteam.md`).
- Live scorecard with Azure AI Evaluation: 88% verified, groundedness 4.57 of 5, relevance 3.93 of 5, about $0.005 per moment (`reports/insights-eval.md`).
- API on standard libraries: Starlette sessions, `limits`, `sse-starlette`; positions feed served pre-compressed; CSP now `'self'` only.
- CDF v0.3.2 export, validated in CI by the official validator (strict).
- Studio v1: event-driven score bug with possession line, live 2D data pitch (the show camera's fallback tier), one match clock with scrubber and team-coloured markers, hero-number lower third, Verified stamp, evidence panel, custom icon set, self-hosted fonts.
- Open: confirm the Studio frame rate on a real laptop GPU (the headless test browser renders at about 1.5 fps on any painting page).

## Done in D3 (18 Oct)
- **Contracts 1.2.0:** `Fact` and `Cue` (verification status, checks, latency).
- **Insights agents** (ADR-0010) on Microsoft Agent Framework 1.22 with Foundry `gpt-5-mini`, keyless: code-built fact sheets and instant plain cards; Analyst ‖ Historian (League Memory over MCP, claims grounded against real tool answers) → Writer → deterministic Verifier (one feedback retry) → Localiser (translations re-verified). Scorecard: `reports/insights-eval.md`.
- **API:** access code → signed HttpOnly SameSite=Strict session; rate limits; strict CSP and security headers; cue replay over SSE.
- **Studio v0:** broadcast lower third with cut-in motion, Verified stamp, evidence panel, four languages, replay speed.
- **Quality:** ruff, pyright and schema drift clean; tests 90% coverage; CI runs with no cloud access (scripted brain).

## Done in D2 (18 Oct)
- **Five-season universe** (ADR-0007): Dixon-Coles results, 26 clubs with promotion and relegation, ageing curves, retirements, transfers, academy; permanent player IDs; current season matchdays 1–8 played, live match on matchday 9.
- **Realism: 14 of 14 measures in range** over 12 matches. Conversion 10.0% (Premier League ~10.3%), inside the box 13.4% (~13%), outside 4.9% (~4%), outside-box share 40.5% (~43%). Research record: `docs/research/data-calibration.md`.
- **Analytics package** (ADR-0008): xG; expected threat trained on our matches (Singh 2019); PPDA, field tilt, momentum, control vs chaos, sprints; moment detector; tactical shifts found with PPDA (tuned on 16 separate matches; held-out precision 83%, recall 62%, `reports/tactical-detection.md`).
- **League Memory:** SQLite (Azure SQL later) + MCP server (official SDK) with 6 read-only tools; every answer carries a query ID and evidence.
- **Data camera** (ADR-0009): Skia broadcast renderer with director, per-frame camera truth and screen boxes for the vision lane.
- **Quality:** 46 tests, 90% coverage; ruff and pyright clean; contracts 1.1.0.

## Next (D4)
1. 3D show camera (Three.js; Low/Medium/High tiers, High default; 2D fallback) driven by tracking.
2. Vision lane (auto-eventing from rendered video, scored against camera truth).

## Decisions log
| Date | Decision |
|---|---|
| 19 Oct | Visuals judged far below standard by Malik: full visual overhaul before new features |
| 19 Oct | Yoruba, Hausa and Igbo voices pending for production; language system stays registry-driven (ADR-0012) |
| 19 Oct | Kaggle free GPUs allowed for research and fine-tuning; serving stays on Azure |
| 19 Oct | Architecture diagrams to be redrawn at the end to match what was built |
| 17 Oct | Matchcut approved; solo build; $0 spend; repo private until submission day |
| 17 Oct | Auto-eventing from video in scope; AI narration for the demo film |
| 18 Oct | Show camera animation sources: Mixamo (football actions, raw files kept private, baked into the app, never in the public repo), CMU motion capture, Quaternius CC0; public repo falls back to CMU + Quaternius. Automatic Low/Medium/High quality with 2D fallback; High is the default and the demo standard |
| 18 Oct | Five seasons with squad evolution; show camera (premium stylised 3D) approved; video-game quality on the roadmap |
| 18 Oct | Voice and languages: live voiced commentary (British and Nigerian English, Arabic on Azure Speech); captions also in Yoruba, Hausa, Igbo and Nigerian Pidgin; their voices only if an open model passes licence and native listening checks |
| 18 Oct | League Memory on MCP SDK 1.x, the range Agent Framework supports (ADR-0010) |
| 18 Oct | Tactical-shift cards state what was measured ("pressing harder", PPDA before and after), not a coach's intent |
| 18 Oct | Agent-based tracking-first engine (ADR-0002); Event Hubs backbone (ADR-0003); Container Apps + Jobs (ADR-0004); keyless security (ADR-0005); uv monorepo (ADR-0006) |
