# Critical / Major Issues Log

Date: 2026-02-12

## Summary
No confirmed code-level production-breaking defects were found during this cleanup pass.

## Security-Significant Findings
1. Portal auth enforcement depends on environment configuration.
- Severity: High (configuration risk)
- Detail: If `AGENT_PORTAL_API_TOKEN` is not set, portal endpoints remain accessible without token auth.
- Mitigation implemented: Token auth support added in code (`portal/app/agent_portal.py`).
- Remaining action: Set and rotate `AGENT_PORTAL_API_TOKEN` in runtime secrets.

2. Broad browser origin and upload settings in Chainlit config.
- Severity: Medium
- Detail: `allow_origins = ["*"]` and `accept = ["*/*"]` increase exposure.
- Current status: Not changed in this pass to avoid accidental functional regressions.
- Remaining action: Restrict origins and file MIME allow-list in production configuration.

3. In-memory fallback when Azure Storage is missing.
- Severity: Medium (availability/audit-trail risk)
- Detail: Callback/history fallback to memory can reduce persistence and traceability.
- Mitigation implemented: Startup storage configuration gates were added to runtime startup paths.
- Policy behavior:
  - `REQUIRE_AZURE_STORAGE_CONNECTION_STRING=true` (default)
  - Startup fails when `AZURE_STORAGE_CONNECTION_STRING` is missing unless `ALLOW_STORAGE_FALLBACK=true`
- Remaining action: Ensure deployment environments keep fallback disabled by default and monitor exceptions.
