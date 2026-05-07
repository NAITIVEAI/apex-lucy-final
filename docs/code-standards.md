# Code Standards & Codebase Structure

The conventions below describe how the Lucy codebase is *actually* written today — patterns observed in `agent/app/` and `portal/app/` — and the constraints contributors must respect when adding new code.

These standards are subordinate to `AGENTS.md`; if anything below conflicts with the spec-driven workflow, the workflow wins.

---

## Language & runtime

- **Language**: Python 3.12 (the `python:3.12-slim` Docker base is the production runtime).
- **Concurrency model**: async-first. Chainlit message handlers, FastAPI routes, and outbound HTTP calls are all `async def`. Synchronous helpers exist only where they are pure and CPU-bound.
- **Type hints**: standard `typing` annotations are used pragmatically — runtime correctness via tests is preferred over exhaustive typing of every call site. Where typed constants exist (schema names, option-set values), they are authoritative per `AGENTS.md`.
- **Style**: PEP 8. No project-wide linter is enforced in CI today; treat consistency with surrounding code as the rule.

---

## Module organization

Both services use a flat `app/` directory rather than a deep package tree. Sibling modules import from each other directly. New modules follow observed naming patterns:

| Suffix | Meaning | Examples |
|---|---|---|
| `*_integration.py` | Outbound integration with an external system | `teams_integration.py` |
| `*_store.py` | Persistence wrapper (Azure Tables → in-memory fallback) | `conversation_store.py` |
| `*_system.py` | Stateful subsystem coordinating multiple stores or APIs | `callback_system.py`, `real_metrics_system.py` |
| `*_authentication*.py` | Auth flows | `agentic_authentication.py`, `agentic_authentication_enhanced_v2.py` |
| `foundry_*.py` | Foundry v2 runtime, client, and publishing | `foundry_v2.py`, `foundry_v2_runtime.py`, `foundry_publish.py` |
| `tracing_config.py` | OpenTelemetry / Azure Monitor wiring | (singleton) |

When adding a module, pick the suffix that matches the role and place it next to its peers. Resist creating new top-level packages — the workflow expects the smallest safe change set.

---

## Async patterns

- **Chainlit handlers** (`@cl.on_message`, `@cl.on_chat_start`, etc.) are the user-facing entry points in `apex.py`. They are `async def` and stream tokens back through Chainlit message APIs.
- **FastAPI routes** in `portal/app/agent_portal.py` are async and use `Depends(...)` for token validation.
- **HTTP integrations** use `aiohttp.ClientSession` with explicit timeouts. Outbound calls to D365, Teams Graph, and Foundry happen inside async functions that propagate cancellation.
- **WebSockets** (`/ws/conversation/{id}`, `/ws/metrics`) use FastAPI's `WebSocket` primitive. Write loops must guard against client disconnects and never block the read loop.
- Avoid mixing sync and async paths in a single helper — wrap blocking SDK calls with `asyncio.to_thread` only when the SDK has no async equivalent.

---

## Error handling & resilience

- **Retry**: outbound integration calls use [`tenacity`](https://github.com/jd/tenacity). Configure exponential backoff with a finite stop condition; never retry forever inside a request handler.
- **Graceful degradation**: stores wrap Azure Tables with an in-memory fallback. If the table client cannot be initialized, the service still serves traffic — but log the degradation loudly through `tracing_config`.
- **Specific exceptions**: catch the narrowest exception that makes sense (`azure.core.exceptions.HttpResponseError`, `aiohttp.ClientError`). Bare `except:` is forbidden.
- **Writeback failures**: per `AGENTS.md`, important writeback failures (for example, COA reason audit) must not be silently swallowed. Surface them in logs and metrics.
- **No invented fallback values**: if a field is missing, surface a controlled, user-safe response — do not fabricate data.

---

## Auth & secrets

- **Member-side auth**: see [`docs/architecture/authentication-architecture.md`](architecture/authentication-architecture.md).
- **Portal API token**: shared `AGENT_PORTAL_API_TOKEN` validated with `hmac.compare_digest` (constant-time). Token is presented as `X-Agent-Token` or `Authorization: Bearer ...`.
- **Azure auth**: prefer `azure.identity.DefaultAzureCredential` / `ManagedIdentityCredential`. Local development can fall back to environment variables but production injects from Azure Container Apps secrets / Key Vault references.
- **D365 auth**: OAuth 2.0 client-credentials flow against `D365_TENANT_ID` / `D365_CLIENT_ID` / `D365_CLIENT_SECRET`.
- **Secrets in code**: never. `.env.example` documents the variable names; the real values live in the secret store.

---

## Tracing & observability

- All long-lived components initialize OpenTelemetry through `tracing_config.py`, which configures the Azure Monitor distro (`azure-monitor-opentelemetry`).
- Custom metrics (queue depth, callback durations, Foundry tool-call counts) are emitted by `real_metrics_system.py`.
- Spans should wrap external calls and tool invocations so the trace tree is meaningful in Application Insights.
- Avoid logging PII; the conversation store handles the sensitive content path.

---

## Testing conventions

- **Framework**: stdlib `unittest`. Tests live in `agent/tests/` and run with `uv run pytest -q` (pytest discovers `unittest.TestCase` subclasses automatically).
- **Mocks**: stub the Azure SDK clients (`azure-ai-projects`, `azure-ai-agents`, `azure-data-tables`, `azure-storage-blob`) so the suite runs offline. Use `unittest.mock.patch` against the import path used inside the module under test.
- **Scope**: tests target plan acceptance criteria (per `AGENTS.md`). The minimum bar is happy-path + realistic historical/incomplete-data path.
- **Portal**: no test suite exists yet; add coverage with FastAPI's `TestClient` when modifying behavior.
- Avoid spinning up a parallel test harness — extend the existing one.

---

## Spec-driven workflow constraint

Every code change must be traceable to a plan file:

1. Read `state/refactor-ledger.md`.
2. Read **exactly one** active `plans/*.md` file (lowest-numbered incomplete or already-in-progress).
3. Use the source-of-truth hierarchy: explicit user instruction → `AGENTS.md` → active plan → existing code patterns.
4. Produce a proposal-before-edit brief; only then make the smallest safe change.
5. Update the ledger with files changed, tests run, blockers, and follow-ups.

The expected plan files are `001-notice-path.md` through `005-regression-validation.md`. Read [`AGENTS.md`](../AGENTS.md) for the full contract — do not paraphrase it.

---

## File size guideline

Prefer keeping modules under ~1,000 LOC. Beyond that, split by responsibility — by store, by integration target, by tool family. The known exception is `agent/app/apex.py` (~9.5K LOC). It is large by design as the Chainlit app entry point and message router; do not split it speculatively, but resist adding more responsibility to it. New behavior belongs in a peer module that `apex.py` imports.

`portal/app/agent_portal.py` (1,824 LOC) is on the edge of this guideline. New routes and handlers should be considered for extraction into peer modules when they cross integration boundaries.

---

## Quick checklist before opening a change

- [ ] Active plan identified and read; ledger consulted.
- [ ] Implementation brief written (files, helpers, schema, tests, risks).
- [ ] Required research completed if the change touches Foundry, Agents SDK, Responses API, or any evolving external surface.
- [ ] Smallest safe edit set; no out-of-scope cleanup.
- [ ] Tests run with `uv run pytest -q`; happy path + historical/incomplete-data path covered.
- [ ] Telemetry remains intact (spans, metrics, logs without PII).
- [ ] Ledger updated.

---

## See also

- [`AGENTS.md`](../AGENTS.md) — spec-driven workflow contract
- [`docs/project-overview-pdr.md`](project-overview-pdr.md) — scope and users
- [`docs/codebase-summary.md`](codebase-summary.md) — file inventory and dependencies
- [`docs/system-architecture.md`](system-architecture.md) — diagrams and request flow
- [`docs/architecture/architecture-overview.md`](architecture/architecture-overview.md)
- [`docs/architecture/authentication-architecture.md`](architecture/authentication-architecture.md)
- [`docs/architecture/foundry-v2-implementation.md`](architecture/foundry-v2-implementation.md)
- [`docs/architecture/rag-search-architecture.md`](architecture/rag-search-architecture.md)
- [`docs/integrations/azure-search-integration.md`](integrations/azure-search-integration.md)
- [`docs/integrations/dynamics365-integration.md`](integrations/dynamics365-integration.md)
- [`docs/integrations/teams-integration.md`](integrations/teams-integration.md)
