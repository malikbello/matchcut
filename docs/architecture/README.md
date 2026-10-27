# Architecture

Two views, from broad to detailed, following the Azure Well-Architected guidance on [architecture design diagrams](https://learn.microsoft.com/azure/well-architected/architect-role/design-diagrams).

| View | File | Answers |
|---|---|---|
| Functional | [concept.svg](concept.svg) | What does Matchcut do for fans, studios and broadcasters? |
| Component and deployment | [azure-architecture.svg](azure-architecture.svg) | Which Azure services, inside which boundaries, connected how? |

## Main flow (numbers match the component diagram)
Before kick-off, on the build machine (a batch run of the match pipeline):
1. `sim` plays the match: events and 10 Hz tracking.
2. The insights agents (Microsoft Agent Framework) write each moment's line on Foundry gpt-5-mini, with Entra tokens.
3. The Historian asks League Memory over MCP (read-only, parameterised SQL on five seasons).
4. Code verifies every number; verified lines, play-by-play calls and the audio description (code-built descriptions of the play, for blind and partially sighted fans, ADR-0016) are voiced by Azure AI Speech.
5. The match package: tracking feed, verified cues, calls and voices.
6. Images (Studio bundle, match package, services) are built and pushed to Azure Container Registry.

On Azure, in one resource group:

7. The Studio app and the render job pull their images with the managed identity.
8. Fans open the Studio (access code); `api` streams the verified cues on the match clock (SSE).
9. A moment, or a fan's "Clip that": `api` puts its slices on the `cuts` queue.
10. KEDA starts one `render-job` replica per message; each draws its frames with the Studio itself (headless Chromium on CPU).
11. The QA agent checks each language's film: Azure AI Speech hears it, gpt-5-mini reads its captions, code judges (ADR-0014).
12. Pieces, films and QA reports land in Blob; the fan's reel shows each moment with its verdict.
13. At the whistle the Recap Factory queues one message per fan's film; the job makes them side by side and prices each (ADR-0015).
14. `api` serves films, share pages, poster frames and the QR hand-over from Blob.

**Deployment:** `deploy/deploy.sh` runs Bicep (`infra/main.bicep`): the Container Apps environment, the Studio app, the queue-triggered job, Storage with shared keys off, the registry, the managed identity and its least-privilege roles. Images are built with Docker and pushed with an Entra sign-in; the GitHub release identity uses OIDC federation, so no secret is stored anywhere. The same checks as CI (format, lint, types, tests with an 80 % coverage gate) run before every commit.

## Principles
- Code computes every number and makes every judgement; AI writes, translates and perceives.
- Every claim carries evidence: event IDs and League Memory records.
- A plain card airs instantly; the verified AI card replaces it.
- Event-driven and replayable: the job scales from zero on its queue; the Studio keeps one warm replica while it is judged.
- Managed identity everywhere; local (key) auth disabled.
- Every stage is scored against the simulator's hidden truth.

## Regenerating the component diagram
```bash
# one-time: download the official icon set (not committed)
curl -sSLo icons.zip https://arch-center.azureedge.net/icons/Azure_Public_Service_Icons_V24.zip
unzip -q icons.zip -d azure-icons
python tools/gen_azure_architecture.py azure-icons/Azure_Public_Service_Icons/Icons azure-architecture.svg
```
