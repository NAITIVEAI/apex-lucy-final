# Deployment Policy Baseline (Storage Configuration Gate)

## Policy Intent
Prevent runtime startup without persistent storage configuration, except for explicitly approved temporary fallback scenarios.

## Required Variables
- `AZURE_STORAGE_CONNECTION_STRING` (required by default)

## Policy Controls
- `REQUIRE_AZURE_STORAGE_CONNECTION_STRING=true` (default)
- `ALLOW_STORAGE_FALLBACK=false` (default)

## Enforcement Points
- Agent startup verification: `agent/app/startup_verification.py`
- Agent service launcher: `agent/app/start_services.sh`
- Portal service launcher: `portal/app/start_agent_portal.sh`

## Behavior
- If storage is required and the connection string is absent, startup exits with non-zero status.
- Temporary exception path: set `ALLOW_STORAGE_FALLBACK=true` with explicit approval and documented rationale.

## Operational Requirement
- In production, keep fallback disabled and ensure storage configuration is injected via managed secrets.

