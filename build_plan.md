# Matchcut build plan

**Goal:** win the Inside the Game Grand Prize (1st) plus Best Azure Cloud Native Integration.
**Submit:** Mon 26 Oct 2026. **Hard deadline:** Wed 28 Oct, 07:59 WAT.
**Standard:** a mature team with an expert in every discipline. Malik is the sole author. No AI credits anywhere.

## 1. The team we act as (one owner per discipline)
| Discipline | Owns | Key artefacts |
|---|---|---|
| Product | personas, journeys, scope, the demo story | `docs/product/personas.md`, `journeys.md` |
| Football and analytics | metric definitions, realism targets, commentary tone per market | `docs/football/metrics.md`, `style-guides/` |
| Brand and design | identity, tokens, components, motion, screens, shareables | `design/brand-board`, `web/src/design/tokens.ts`, component gallery |
| AI | agents, prompts, verifier, evaluations, safety | `services/insights`, `services/recap`, `evals/` |
| Simulation and data | league, history, match engine, tracking, truth, realism report | `services/sim`, `data/`, `reports/realism.md` |
| Vision | renderer as camera, detector, tracker, event inference, scoring | `services/renderer`, `services/vision` |
| Video | clip rendering, TTS, captions, compositing, QA | `services/recap/jobs` |
| Frontend | Studio, Fan, Analyst, Recap Factory, Package player | `web/` |
| Platform and infrastructure | Bicep/azd, Container Apps and Jobs, Event Hubs, SQL, Storage, identity | `infra/` |
| Security | threat model, keyless auth, scanning, headers, prompt-injection tests | `docs/security/threat-model.md` |
| Operations and cost | telemetry, dashboards, budgets, runbooks | `docs/runbooks/`, workbook |
| Story | 2-minute video, pitch, README, judge guide | `docs/submission/` |

## 2. Quality gates (nothing merges without them)
- CI: lint, format, type-check (ruff + pyright; eslint + tsc), unit and contract tests, coverage ≥ 80% on core logic.
- Security: CodeQL, secret scanning + push protection, Dependabot, pip-audit and npm audit, Trivy image scan, licence check (no AGPL), SBOM.
- AI: eval suite on fixed matches: number accuracy = 100% (code-checked), groundedness ≥ 4/5, no prompt-injection passes; latency budgets met.
- Design: tokens only (no raw hex in components); contrast AA; reduced motion; right to left; 360 px to 4K.
- Every PR: description, linked task, screenshots for UI. Authored by Malik only.

## 3. Day-by-day (definition of done in brackets)
| Day | Date | Deliverables |
|---|---|---|
| D0 | Sat 17 | ✅ Azure account, budget, model test · ✅ rules checklist · ✅ architecture (Azure + concept) · ✅ brand board · this plan |
| D1 | Sun 18 | Private repo `matchcut`, branch protection, CI skeleton, ADRs 001–005, contracts (JSON Schema), design tokens · league + history generator · match engine v0 (events + tracking) [tests green; realism report v0] |
| D2 | Mon 19 | Match engine v1 (tactics, hidden truth) · state engine metrics (xG, xT, PPDA, momentum, control vs chaos) · moment detector · renderer v0 (broadcast camera → MP4/HLS) · League Memory SQL + MCP server [one full match renders] |
| D3 | Tue 20 | Live agents on Foundry with Agent Framework (Analyst ‖ Historian → Writer → Verifier → Localiser) · eval suite v1 · api (SSE) · Studio screen v0 with HLS + synced overlays [**vertical slice live locally**] |
| D3.2 | Sun 18 to Mon 19 | **Voices and languages (approved 18 Oct):** live voiced commentary of verified lines with Azure Speech (standard British English and Nigerian English `en-NG`, Arabic); captions in English, Nigerian English, Spanish, French, Portuguese, Arabic, Yoruba, Hausa, Igbo and Nigerian Pidgin; language tags (BCP 47, e.g. `pcm`), digit normalisation in the Verifier, Latin-script names everywhere, right-to-left Studio, fonts for tone marks and Arabic; licence and native listening checks for a Yoruba/Hausa/Igbo/Pidgin voice model (voice only if both pass) |
| D4 | Wed 21 | **Show camera (approved 18 Oct):** real-time 3D (Three.js/WebGL): stadium, crowd, floodlights, shadows, animated CC0 rigged players driven by tracking, replay cameras, post-processing; brand graphics layer · Vision lane v0 on the data camera (auto-labelled detector, tracking, pass/speed inference, scored vs truth) [show camera plays a live match in the browser] |
| D4.5 | Mon 19 to Tue 20 | **Visual overhaul (Malik, 19 Oct: current design far below standard):** art direction against broadcast and game references; real characters with faces, hair, kit textures, names and numbers; detailed stadium; animated crowd; PBR grass; night lighting, grading and post-processing; broadcast graphics package; a visual review gate before moving on [side-by-side against references passes Malik's review] |
| D5 | Thu 22 | Recap lane: Editor, Director, Scriptwriter + timing loop, Voice (Azure Speech), film timeline; films play in the show camera (16:9 and 9:16) with MP4 export; QA job · Package player [**one fan film end to end**] · re-read rules |
| D6 | Fri 23 | Azure: Bicep/azd for everything, managed identity + RBAC, local auth off, Event Hubs, Container Apps + Jobs, SQL, Storage, SWA, App Insights · CI/CD with OIDC · smoke tests [**live URL**] |
| D7 | Sat 24 | Recap Factory + Analyst screens · 9:16 shareables · native-speaker review of the Nigerian languages and Arabic · motion polish · security hardening · dashboards · docs [UX review against the brand board] |
| D8 | Sun 25 | Curated demo match (storylines) · record and edit the video (Arcas narration, no music) · pitch text · README · judge guide [video < 2:00 confirmed by ffprobe] |
| D9 | Mon 26 | Redraw the architecture diagrams to match what was built · Clean-clone test · final QA on the live URL · make the repo public · Malik submits by hand · re-read rules [**submitted**] |
| Buffer | Tue 27 | Buffer only |

## 4. Cut list (in order, only if behind)
1. A2A partner agent (stretch, not planned)
2. Corrections re-render
3. Vision frame check in QA (keep speech-to-text)
4. Languages 5 → 3
5. History 2 seasons → 1
6. Packages 24 → 8
7. Vision scope → speeds + passes on one clip (never dropped)

**Never cut:** the live lane, one fan film end to end, the verifier, the live URL, security basics.

## 5. Roadmap beyond the hackathon
- **Video-game-quality renders:** an Unreal Engine 5 render node with motion matching and football motion-capture, driven by the same tracking feed (needs GPUs and licensed mocap; weeks of specialist work).
- **CDF export** for interoperability with any CDF-aware tool.
- **Real-footage lane (research watch):** Dense4D (Güler, Imperial College London, arXiv 2610.22325, Oct 2026) recovers dense 3D surface tracks of body, clothing and hair from ordinary video in one feed-forward pass. Once its code and licence are out, it could lift a fan's broadcast clip into full-body 3D motion for our replay cameras and commentary, and sharpen the vision lane. Not in the hackathon build: code unreleased, and the rules require synthetic data.
- **Yoruba, Hausa and Igbo voices in production:** a fine-tune on licence-clean studio data (Google WAXAL, BibleTTS) with spoken numbers in each language and a native listening gate; the language registry already takes new languages without code changes (ADR-0012).

## 6. Risks
| Risk | Mitigation |
|---|---|
| Solo scope over 9 days | Vertical slice by D3; strict cut list; submit on D9 not D10 |
| Vision accuracy on our render style | Train on our own auto-labelled frames; classical fallback detector behind the same interface |
| Model throttling (Tier 0) | 100K TPM deployed (500K available); caching; template-first cards |
| Render cost and time | 1080p only for final films; 720p previews; jobs capped |
| Free credit or limits | Budget alerts; scale to zero; pre-rendered films for judges |
| Trademark | Fictional league; no Premier League marks or crests on screen |
