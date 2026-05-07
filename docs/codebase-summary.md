# Codebase Summary

A high-level inventory of the Apex-Lucy-Final repository: top-level layout, per-service structure, tests, build/deploy, and the dependency graph that ties it all together.

This is a navigation document. For architecture detail follow the cross-references; for module-level depth read the source.

---

## Repo layout

```
Apex-Lucy-Final/
  agent/                  Agent service (Chainlit + Azure AI Foundry)
    app/                    Service code, Dockerfile, .env.example, requirements.txt
    tests/                  unittest test suite
  portal/                 Handoff/admin portal service (FastAPI)
    app/                    Service code, Dockerfile, templates/, static/, requirements.txt
  docs/                   Architecture, integration, executive, handoff, portal-guide docs
  plans/                  Active spec-driven plan files (currently empty/uninitialized)
  state/                  refactor-ledger.md and other workflow state (empty/uninitialized)
  .agents/                Local/custom agent skill workspace
  learn/                  Scout reports and autoresearch artifacts
  removal/                Non-runtime artifacts moved out of the runtime surface
  AGENTS.md               Spec-driven workflow contract (mandatory reading)
  KNOWNS.md               `knowns` CLI conventions
  OPENCODE.md             Thin redirect to KNOWNS.md
  CLAUDE.md               context-mode routing rules for Claude Code
  README.md               Repo entry point
```

The `plans/` and `state/refactor-ledger.md` artifacts are referenced by `AGENTS.md` but currently empty; they become load-bearing the moment a plan is added.

---

## Service breakdown

### Agent service — `agent/app/`

| Item | Value |
|---|---|
| Entry point | `apex.py` (~9.5K LOC, Chainlit application) |
| Module count | 36 Python modules totalling ~17.7K LOC |
| Public ports | 8000 (Chainlit chat), 8080 (health) |
| Health endpoints | `GET /health`, `/health/ready`, `/health/live` |
| Tests | `agent/tests/` — 9 unittest files |

**Key modules and one-line purpose**

| Module | Purpose |
|---|---|
| `apex.py` | Chainlit message-handler entry point; orchestrates Foundry v2 runtime, retrieval, D365, and handoff |
| `foundry_v2.py` | Foundry v2 client wrapper for the `lucy` agent on the `gpt-5.2` deployment |
| `foundry_v2_runtime.py` | Streaming/tool-call orchestration for Foundry v2 |
| `foundry_publish.py` | Publishes prompt-agent updates to the Foundry Application layer |
| `agent_registry.py` | Persists agent registrations (Azure Tables → in-memory fallback) |
| `conversation_store.py` | Conversation persistence, lookup, and pruning |
| `callback_system.py` | Callback queue with priority + summarization |
| `teams_integration.py` | Microsoft Teams Graph integration for handoff adaptive cards |
| `agentic_authentication.py` / `agentic_authentication_enhanced_v2.py` | Member auth + D365 OAuth client-credentials |
| `tracing_config.py` | OpenTelemetry/Azure Monitor wiring |
| `real_metrics_system.py` | Live metrics emitted to Azure Monitor |

The `foundry-v2-implementation.md` and `architecture-overview.md` docs cover behavior in depth.

### Portal service — `portal/app/`

| Item | Value |
|---|---|
| Entry point | `agent_portal.py` (1,824 LOC) |
| Routes | 27 HTTP routes + WebSocket endpoints `/ws/conversation/{id}` and `/ws/metrics` |
| Public port | 8001 |
| Templates | 8 Jinja2 templates: `agent_portal`, `dashboard`, `conversation`, `user_chat`, `callbacks`, `redirect`, plus modern variants of portal/dashboard |
| Auth | Shared API token (`X-Agent-Token` or `Bearer`) compared in constant time |
| Real-time | Bidirectional WebSocket sync between agent service and portal users |
| Callbacks | Priority queue with AI summarization |
| Tests | None currently in repo |

The `portal-guide/portal-user-guide.md` document walks through every screen.

---

## Tests

- **Framework**: Python `unittest` (stdlib).
- **Location**: `agent/tests/` — 9 files covering Foundry, registry, conversation, callbacks, and integration glue.
- **Run command**: `uv run pytest -q` from the repo root.
- **Coverage gap**: `portal/` currently has no tests. New behavior in `agent_portal.py` should add coverage as it lands; existing pure-Python helpers can be exercised with FastAPI's `TestClient`.

Mocking conventions: tests stub the Azure SDK clients (`azure-ai-projects`, `azure-ai-agents`, `azure-data-tables`, `azure-storage-blob`) so the suite runs offline without Azure credentials.

---

## Build & deploy

- **Agent**: `agent/app/Dockerfile` — `python:3.12-slim`, exposes ports 8000 and 8080, entrypoint `start_services.sh`.
- **Portal**: `portal/app/Dockerfile` — `python:3.12-slim`, exposes port 8001, entrypoint `start_agent_portal.sh`.
- **CI/CD**: No `.github/workflows/` directory exists at repo root. Build and release are operator-driven; Foundry application updates are published through the Foundry managed deployment layer (see [`docs/architecture/foundry-v2-registration-reset-2026-04-17.md`](architecture/foundry-v2-registration-reset-2026-04-17.md)).
- **Secrets**: Inject from a managed secret store (Azure Container Apps secrets / Key Vault references). `.env.example` files in each service document required variables.

---

## Key dependencies

The agent and portal services share most of their stack but pin versions independently. The agent uses unpinned ranges for some Azure packages so it can track Foundry beta SDK rolls; the portal pins to exact versions for SOC2-friendly reproducibility.

| Dependency | Agent version | Portal version | Purpose | Class |
|---|---|---|---|---|
| `chainlit` | `2.9.5` | `2.9.5` | Conversational UI framework powering Lucy's member-facing chat | runtime |
| `fastapi` | `0.116.1` | `0.116.1` | HTTP framework for portal routes and Chainlit's underlying server | runtime |
| `uvicorn` | `0.35.0` | `0.35.0` | ASGI server hosting both services | runtime |
| `azure-ai-projects` | `2.0.0b3` | `1.0.0b11` | Azure AI Foundry projects SDK; agent tracks the v2 beta line | runtime |
| `azure-ai-agents` | `~=1.2.0b2` | `1.0.0` | Azure AI Agents SDK; agent uses v2 runtime, portal uses stable for read access | runtime |
| `azure-search-documents` | unpinned | `11.5.2` | Azure AI Search client for `lucy-notices-v2` retrieval | runtime |
| `azure-storage-blob` | unpinned | `12.25.1` | Blob storage for OCR artifacts and supporting documents | runtime |
| `azure-data-tables` | unpinned | `12.7.0` | Backing store for registry, conversation, and callback queues (with in-memory fallback) | runtime |
| `azure-identity` | unpinned | `1.23.0` | DefaultAzureCredential / ManagedIdentity for all Azure client auth | runtime |
| `azure-monitor-opentelemetry` | unpinned | `1.6.10` | OpenTelemetry distro that exports traces and metrics to Azure Monitor | runtime |
| `openai` | `2.15.0` | `1.84.0` | OpenAI SDK; agent uses v2 (Responses API), portal uses v1 for compatibility | runtime |
| `tenacity` | unpinned | `9.1.2` | Retry/backoff for external integrations (D365, Teams, Search) | runtime |
| `aiohttp` | unpinned | `3.12.9` | Async HTTP for outbound integrations | runtime |
| `botbuilder-core` / `botbuilder-schema` | unpinned | `4.17.0` | Bot Framework primitives used by the Teams integration | runtime |
| `websockets` | unpinned | `15.0.1` | WebSocket support for portal real-time relay | runtime |
| `jinja2` | unpinned | `3.1.6` | Template rendering for portal pages | runtime |
| `python-multipart` | unpinned | `0.0.18` | Multipart form parsing for portal uploads | runtime |
| `pytz` | unpinned | `2025.2` | Timezone handling for `get_current_datetime_sync` | runtime |
| `PyPDF2` | unpinned | `3.0.1` | PDF parsing for notice ingestion / OCR-adjacent flows | runtime |
| `python-dotenv` | unpinned | `1.1.0` | Local `.env` loading (production injects via secret store) | dev/runtime |
| `literalai` | unpinned (agent only) | — | Chainlit 2.9.5 transitive dependency for trace export | runtime |

There is no separate dev-requirements file; testing relies on the stdlib `unittest` runner plus the Azure SDK mocks already used in tests.

---

## See also

- [`docs/project-overview-pdr.md`](project-overview-pdr.md) — mission, users, scope
- [`docs/system-architecture.md`](system-architecture.md) — condensed architecture with diagrams
- [`docs/code-standards.md`](code-standards.md) — module conventions and patterns
- [`docs/architecture/architecture-overview.md`](architecture/architecture-overview.md) — full system architecture
- [`docs/architecture/foundry-v2-implementation.md`](architecture/foundry-v2-implementation.md) — agent runtime detail
- [`docs/architecture/rag-search-architecture.md`](architecture/rag-search-architecture.md) — retrieval pipeline
- [`docs/architecture/foundry-v2-registration-reset-2026-04-17.md`](architecture/foundry-v2-registration-reset-2026-04-17.md) — runtime ops rules
- [`docs/integrations/azure-search-integration.md`](integrations/azure-search-integration.md)
- [`docs/integrations/dynamics365-integration.md`](integrations/dynamics365-integration.md)
- [`docs/integrations/teams-integration.md`](integrations/teams-integration.md)
- [`docs/portal-guide/portal-user-guide.md`](portal-guide/portal-user-guide.md)
- [`AGENTS.md`](../AGENTS.md) — spec-driven workflow contract
