# Architecture

Two views, from broad to detailed, following the Azure Well-Architected guidance on [architecture design diagrams](https://learn.microsoft.com/azure/well-architected/architect-role/design-diagrams).

| View | File | Answers |
|---|---|---|
| Functional | [concept.svg](concept.svg) | What does Matchcut do for fans, studios and broadcasters? |
| Component and deployment | [azure-architecture.svg](azure-architecture.svg) | Which Azure services, inside which boundaries, connected how? |

## Main flow (numbers match the component diagram)
1. `sim` publishes match events and 10 Hz tracking to Event Hubs.
2. `renderer` consumes tracking and draws the broadcast feed.
3. `renderer` writes HLS segments to Blob Storage.
4. `vision` reads frames from Blob Storage.
5. `vision` publishes detected events (auto-eventing).
6. `insights` consumes events and detections.
7. Agents call Foundry models with Entra tokens.
8. The Historian agent calls League Memory over MCP.
9. League Memory runs parameterised, read-only SQL.
10. `insights` publishes verified, timed cues.
11. `recap` starts at half time and full time.
12. Recap agents call Foundry and Azure AI Speech (voice timing).
13. `recap` enqueues one render task per fan profile.
14. `render-job` scales from 0 to N and writes MP4 files to Blob Storage.
15. `qa-job` runs speech-to-text and a vision check, then publishes.
16. `api` streams cues to screens over SSE.
17. The web app calls `api` (access code, rate limits).
18. Fans open the web app.
19. `api` serves films through short-lived SAS links.

**Deployment:** GitHub Actions signs in with OIDC (no stored secrets) and deploys Bicep/azd templates, with images from ghcr.io.

## Principles
- Code computes every number; AI only explains.
- Every claim carries evidence: event IDs, history record IDs or camera tracks.
- A plain card airs instantly; the verified AI card replaces it.
- Event-driven, replayable, scale to zero.
- Managed identity everywhere; local (key) auth disabled.
- Every stage is scored against the simulator's hidden truth.

## Regenerating the component diagram
```bash
# one-time: download the official icon set (not committed)
curl -sSLo icons.zip https://arch-center.azureedge.net/icons/Azure_Public_Service_Icons_V24.zip
unzip -q icons.zip -d azure-icons
python tools/gen_azure_architecture.py azure-icons/Azure_Public_Service_Icons/Icons azure-architecture.svg
```
