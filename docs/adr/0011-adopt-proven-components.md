# ADR-0011: Adopt proven components before building our own

- Status: accepted · Date: 2026-10-18

## Context
Several early pieces of Matchcut were written by hand although mature, maintained components exist: agent orchestration, tracing, sessions, rate limiting, server-sent events and the match data format. Hand-rolled infrastructure costs time, hides bugs and looks immature to anyone reviewing the code. We audited every component against what mature, well-maintained projects use.

## Decision
We adopt proven components and hand-build only where a tested gap exists, recording the reason.

| Area | Adopted | Instead of | Why |
|---|---|---|---|
| Agent orchestration | Microsoft Agent Framework **workflows** (typed executors, fan-out and fan-in, conditional edges) | `asyncio.gather` and a loop | Framework-native parallelism, routing, checkpoints and tracing |
| Tracing | OpenTelemetry via the Azure Monitor distro plus Agent Framework instrumentation, exported to Application Insights | none | Every executor, model call (with tokens) and MCP tool call is a span; message content is never recorded |
| Agent evaluation | **Azure AI Evaluation** groundedness and relevance (model-graded, keyless) next to our deterministic scorecard | our scorecard only | An independent, industry-standard second opinion |
| Verifier testing | A red team that plants realistic false claims (catch rate and false-rejection rate) | happy-path tests only | Measures what matters; it found a real weakness on its first run (below) |
| Sessions | Starlette `SessionMiddleware` (signed cookies) | hand-signed HMAC tokens | Standard, reviewed code |
| Rate limiting | `limits` (moving window; Redis when scaled out) | a hand-written deque | The library behind Flask-Limiter |
| Server-sent events | `sse-starlette` | a hand-written stream | Keep-alive pings and disconnect handling |
| Match data | **Common Data Format** (CDF v0.3.2) export, checked in CI by the official validator in strict mode | our own JSON only | Any CDF-aware tool can read our matches |
| Recap films (D5) | Remotion (programmatic, personalised video; React and Three.js) | hand-built ffmpeg compositing | Built for personalised video at scale; free for individuals |
| Broadcast graphics (D7) | Templates compatible with SPX, CasparCG and OBS | Studio-only HTML | A real production gallery can load our graphics |
| Vision lane (D4) | Roboflow `supervision`, ByteTrack and RF-DETR | a custom detector | Permissive licences; we avoid AGPL-licensed YOLO |

Kept on purpose:
- **The match engine.** No library produces calibrated fictional football with hidden truth.
- **The deterministic Verifier.** A model judging a model's numbers can be talked round; code that checks every number against the fact it cites cannot, so we never air an unverified line.
- **Our expected-threat implementation.** socceraction is the reference but is no longer developed. A cross-check against it is planned.

## What the red team found
The Verifier first checked each number against all cited facts as a set. "3 shots after 5 minutes" nudged to "5 shots after 5 minutes" passed, because 5 was a real fact (the minute). The fix is **attributed generation**: the Writer lists every number it writes, in order, with the fact that states it, and the Verifier checks each pairing. A score such as "2-1" may be attributed as one value. Result over 4 matches: 709 of 709 planted false lines caught, 0 of 128 true lines rejected (`reports/verifier-redteam.md`).

## Consequences
- Less custom code to maintain; reviewers recognise the components.
- The Studio and API depend on small, well-known libraries.
- Each new component starts with a reuse check, recorded here or in its own ADR.
