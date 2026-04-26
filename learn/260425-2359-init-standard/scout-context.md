# Scout Context — 260425-2359-init-standard

Mode: init | Scope: everything | Depth: standard
Project: Apex-Lucy-Final (Lucy class-action settlement support agent)

## Project Type
Multi-service Python monorepo:
- `agent/app/` — Chainlit 2.9.5 + FastAPI conversational AI agent (Lucy) on port 8000, health on 8080
- `portal/app/` — FastAPI handoff/admin portal on port 8001
Both deployed via Docker (python:3.12-slim).

## Stack
Python 3.12 · Chainlit 2.9.5 · FastAPI 0.116.1 · Uvicorn 0.35.0 · Jinja2 templates · vanilla JS · Azure AI Foundry (gpt-5.2) · Azure AI Search (lucy-notices-v2) · Azure Storage Tables/Blob · Microsoft Teams Graph · Dynamics 365 OAuth · OpenTelemetry/Azure Monitor.

## Agent Service Highlights (agent/app/)
- Entry: `apex.py` (~9.5K LOC, Chainlit app)
- 36 .py modules (~17.7K LOC)
- 9 unittest files in agent/tests/
- Foundry v2 runtime: `foundry_v2.py`, `foundry_v2_runtime.py`, `foundry_publish.py`
- Stores: `agent_registry.py`, `conversation_store.py`, `callback_system.py` (Azure Tables → in-memory fallback)
- Integrations: `teams_integration.py`, `agentic_authentication.py`, `agentic_authentication_enhanced_v2.py`
- Tracing: `tracing_config.py` + Azure Monitor OpenTelemetry
- Health endpoints (8080): GET /health, /health/ready, /health/live

## Portal Service Highlights (portal/app/)
- Entry: `agent_portal.py` (1,824 LOC) — 27 routes including WebSocket `/ws/conversation/{id}` and `/ws/metrics`
- 8 templates (agent_portal, dashboard, conversation, user_chat, callbacks, redirect — modern variants for portal/dashboard)
- Auth: shared API token (X-Agent-Token / Bearer) with constant-time compare
- Real-time: bidirectional WebSocket sync between agent service and portal users
- Callback queue with priority + AI summarization

## Spec Workflow (root files)
- `AGENTS.md` enforces strict spec-driven loop: read state/refactor-ledger.md → pick lowest-numbered `/plans/*.md` → load `.agents/skills/lucy-spec-implementation/SKILL.md`
- Source-of-truth hierarchy: user instruction → AGENTS.md → active plan → skill → existing code patterns
- Currently `plans/` and `state/refactor-ledger.md` are empty/uninitialized
- KNOWNS.md governs `knowns` CLI conventions (do not duplicate doc content into memory; search before reading)
- OPENCODE.md is a thin redirect to KNOWNS.md
- `.agents/skills/lucy-spec-implementation/` directory exists but SKILL.md not yet authored

## Existing Docs (PRESERVE — do not overwrite)
22,471 lines across 18 files:

**docs/architecture/** (7 files, ~11.3K LOC)
- architecture-overview.md (2,432) — comprehensive system architecture
- authentication-architecture.md (992) — member auth + D365 + learning cache
- foundry-v2-implementation.md (3,420) — Assistants→Foundry v2 migration
- foundry-v2-registration-reset-2026-04-17.md (51) — runtime ops rules
- human-escalation-architecture.md (1,416) — Teams escalation flow
- rag-search-architecture.md (2,944) — RAG, hybrid search, OCR, scale
- "Authoritative URL map.md" (9) — sparse stub

**docs/integrations/** (3 files, ~3.95K LOC)
- azure-search-integration.md (1,080)
- dynamics365-integration.md (1,732)
- teams-integration.md (1,138)

**docs/handoff/** (5 files, 264 LOC)
- CRITICAL_ISSUES.md (28)
- DEPLOYMENT_POLICY_BASELINE.md (24)
- GIT_HANDOFF_STRATEGY.md (41)
- HANDOFF_CLEANUP_SUMMARY.md (30)
- SOC2_RENEWAL_SUPPORT.md (141)

**docs/executive/** (2 files, ~2.67K LOC)
- executive-summary.md (796)
- system-capabilities-guide.md (1,878)

**docs/portal-guide/** (1 file)
- portal-user-guide.md (3,193)

## Env Vars (signals for configuration-guide if Deep)
agent/.env.example — AZURE_AI_FOUNDRY_PROJECT_ENDPOINT, MODEL_DEPLOYMENT_NAME (gpt-5.2), FOUNDRY_AGENT_NAME (lucy), USE_FOUNDRY_V2, AZURE_RESPONSES_ENABLED, AZURE_RESPONSES_REASONING_EFFORT, AI_SEARCH_INDEX_NAME (lucy-notices-v2), SEARCH_QUERY_TYPE (vector_semantic_hybrid), D365_RESOURCE_URL, TEAMS_WEBHOOK_URL, AGENT_PORTAL_ENABLED, AZURE_STORAGE_CONNECTION_STRING.
portal/.env.example — AGENT_PORTAL_PORT (8001), AGENT_PORTAL_API_TOKEN, ENABLE_DEBUG_ENDPOINTS, TEAMS_APP_ID/PASSWORD/TENANT_ID, TEAMS_AGENT_EMAILS, D365_TENANT_ID/CLIENT_ID/CLIENT_SECRET, AZURE_SEARCH_*, ACCOUNT_KEY/NAME/CONTAINER_NAME, SEARCH_TOP_K, LOG_LEVEL.

## Tests
agent/tests/ uses unittest. Run: `uv run pytest -q`. No portal tests detected.

## Build/Deploy
- agent/app/Dockerfile (python:3.12-slim, ports 8000+8080, `start_services.sh`)
- portal/app/Dockerfile (python:3.12-slim, port 8001, `start_agent_portal.sh`)
- No `.github/workflows/` detected at repo root

## Last Commits
Code: 2026-04-25 22:20:24 -0700
Docs: 2026-04-17 03:22:07 -0700
Staleness gap: ~8 days
