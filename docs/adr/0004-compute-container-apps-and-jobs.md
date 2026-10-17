# ADR-0004: Azure Container Apps for services, Container Apps Jobs for rendering

- Status: accepted · Date: 2026-10-18

## Context
Workloads are mixed:
- long-running stream consumers (simulator, renderer, vision, insights, recap, API, MCP server);
- bursty, CPU-heavy batch work at half time and full time: rendering 24 films, then QA.

Cost must sit at about $0 when idle, and the platform must show cloud-native, event-driven operation.

## Options considered
- **AKS:** full control, but a cluster to run and pay for, which is too much operational weight for this workload.
- **Azure Functions:** excellent for small event handlers; a poor fit for minute-long video renders and stateful agent workflows.
- **Container Apps + Jobs** (chosen): serverless containers with scale-to-zero, KEDA scale rules (Event Hubs, queues), revisions, managed identity, and a free monthly grant.

## Decision
- Every service runs as a Container App in one Consumption environment.
- Rendering and QA run as **event-driven Container Apps Jobs** scaled by a KEDA Storage Queue rule from 0 to N, with a hard parallelism cap.
- Images come from GitHub Container Registry.

## Consequences
- Throughput (films per minute) and cost per film can be measured and shown.
- Cold starts add a few seconds on the first request. Studio-facing services keep one warm replica only during a live match.
