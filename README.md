# Lucy Application Handoff Package

This repository contains the client-facing runtime code for Lucy:

- `agent/app`: customer-facing assistant service (Chainlit + Azure integrations)
- `portal/app`: internal handoff/callback portal service (FastAPI)

## Repository Layout
- `agent/`: assistant service code and tests
- `portal/`: portal service code
- `docs/`: architecture, integration, and handoff documentation
- `removal/`: non-core artifacts moved out of the primary runtime surface

## Security and Compliance Docs
Handoff documentation for security/compliance review is available in:

- `docs/handoff/SOC2_RENEWAL_SUPPORT.md`
- `docs/handoff/CRITICAL_ISSUES.md`
- `docs/handoff/HANDOFF_CLEANUP_SUMMARY.md`

## Runtime Configuration
Environment values are provided via `.env.example` templates:

- `agent/app/.env.example`
- `portal/app/.env.example`

Recommended production posture:
- Inject secrets from managed secret stores (for example, Azure Container Apps secrets / Key Vault references)
- Publish prompt-agent updates through the Foundry Agent Application / Managed deployment layer so the portal and runtime stay on the same version
- Set `FOUNDRY_APPLICATION_NAME` explicitly when the published application name should differ from the logical agent name
- Set `AGENT_PORTAL_API_TOKEN` for portal request authentication
- Keep `ENABLE_DEBUG_ENDPOINTS` unset or `false` in production

## Notes on Removed Artifacts
To support a clean client handoff, non-runtime assets (deployment tooling, CI/CD, operational history, AI coding assistant artifacts, debug/fix scripts, and historical reports) were moved to `removal/` rather than deleted.
