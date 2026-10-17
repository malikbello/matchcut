# ADR-0005: Keyless identity and the security baseline

- Status: accepted · Date: 2026-10-18

## Decision
- **Identity:** each service authenticates to Azure with a managed identity through `DefaultAzureCredential`. Each identity holds only the RBAC roles it needs. For example, `insights` gets *Cognitive Services OpenAI User* and *Azure Event Hubs Data Receiver/Sender*; `league-memory` gets *db_datareader* on SQL.
- **No keys:** local (key) auth is disabled on Foundry, Speech, Event Hubs and Storage. SQL uses Microsoft Entra-only authentication.
- **CI/CD:** GitHub Actions signs in to Azure with OIDC workload identity federation. No stored cloud secrets.
- **Application:**
  - live AI generation sits behind a hashed access code and rate limits;
  - strict CORS, CSP and security headers; request size limits;
  - agents read structured data only, and the MCP tools are read-only and parameterised;
  - prompt-injection cases sit in the eval suite.
- **Supply chain:** pinned, locked dependencies (`uv.lock`); Dependabot; pip-audit in CI; CodeQL once public; secret scanning with push protection; non-root container images; Trivy image scans.
- **Cost guards:** budget alerts; replica and job-parallelism caps; per-request and daily token caps.

## Consequences
There are no secrets to leak or rotate. Every access path is visible in RBAC, and the security posture can be checked in review.
