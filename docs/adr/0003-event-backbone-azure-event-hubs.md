# ADR-0003: Azure Event Hubs as the event backbone

- Status: accepted · Date: 2026-10-18

## Context
Several services consume the same ordered match streams (events, tracking, detections, cues) independently and must be able to replay a match.

## Options considered
| Option | Fit |
|---|---|
| **Event Hubs (Standard)** | Partitioned, ordered per key, retention + replay, a consumer group per service, AMQP, Entra auth. Built for telemetry-style streams. |
| Service Bus | Queue and topic semantics, per-message settlement; great for commands, heavier for high-rate streams; no replay from an offset. |
| Event Grid | Push-based discrete events; no ordered replayable stream. |
| Storage Queues | Cheap work queues; no fan-out, no ordering guarantee. |

## Decision
Event Hubs Standard, one namespace with four hubs: `match-events`, `tracking`, `detections`, `cues`. Partition key is `match_id`, so each match is ordered. Each service gets its own consumer group. **Storage Queues** carry render and QA *work items* (ADR-0004), because those are commands, not streams.

## Consequences
- About $11 for the sprint, covered by the free credit; no free tier exists.
- Local development uses the Event Hubs emulator behind the same client interface.
