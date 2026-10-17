# Security policy

## Reporting
Please report suspected vulnerabilities privately through GitHub's **Report a vulnerability** (Security tab). Don't open public issues for security problems.

## Baseline
- No secrets in the repository. Azure access uses managed identities and OIDC federation; key-based auth is disabled ([ADR-0005](docs/adr/0005-keyless-identity-and-security-baseline.md)).
- Dependencies are locked (`uv.lock`), audited in CI (pip-audit) and updated by Dependabot.
- Only synthetic data is processed. No personal data is collected beyond what is needed to operate the demo.
