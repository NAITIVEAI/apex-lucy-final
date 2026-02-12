# Handoff Cleanup Summary

Date: 2026-02-12

## Objective
Prepare a client-facing package that contains only core runtime and essential documentation, while isolating non-essential artifacts.

## What Was Moved
A new `/removal` folder was created and populated with non-core assets, including:
- AI assistant tooling artifacts (`.claude`, `.cursor`, `.specstory`, `.mcp.json`, etc.)
- Deployment/infra/CI-CD assets (`.github/workflows`, `infra`, `jobs`, deployment scripts)
- Historical notes and operational logs (`findings.md`, `to-do.md`, `CURRENT_STATE.md`, etc.)
- Reports and helper scripts (`reports`, `scripts`, `env` manifests)
- Legacy and debug code from `agent/app` (fix scripts, extracted archives, test harnesses, portal duplicates)
- Ops/maintenance docs and CI/CD docs

## What Remains as Primary Code
- Runtime assistant service: `agent/app`
- Runtime portal service: `portal/app`
- Core technical/product docs: `docs/` (excluding moved operational/CI-CD docs)

## Security Hardening Applied
- Added optional token-based auth gate for portal requests (`AGENT_PORTAL_API_TOKEN`)
- Disabled portal debug endpoints by default (`ENABLE_DEBUG_ENDPOINTS=false`)
- Removed connection-string prefix from debug responses

## Notes
- `/removal` is intentionally preserved to maintain traceability without exposing non-core artifacts in the main runtime surface.
- This handoff package is prepared for client review, not as an active deployment operations repo.

