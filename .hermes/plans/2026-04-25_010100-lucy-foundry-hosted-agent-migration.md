# Lucy Migration Plan: Azure Foundry Hosted Agent

## Goal

Migrate Lucy from the current Azure Container Apps + Chainlit + Foundry prompt-agent orchestration model to a Foundry Hosted Agent-compatible architecture, so Foundry playground/evals/tracing can invoke the real Lucy runtime and tools rather than only a prompt-agent registration.

The migration should preserve the current production Chainlit experience while adding a Foundry-native hosted-agent runtime in parallel.

## Executive Summary

Lucy can migrate to Microsoft Foundry Hosted Agents, but not by directly lifting the current `agent/app/apex.py` Chainlit app into Hosted Agent Service. The right migration is to extract a UI-independent Lucy runtime core, then build two adapters around it:

1. Existing Chainlit adapter for the user-facing chat app.
2. New Foundry Hosted Agent adapter for Foundry playground/evals/tracing.

Target architecture:

```text
                    +-----------------------------+
                    |      LucyRuntime Core       |
                    | session, tools, responses   |
                    | Dynamics/Search/Blob/Table  |
                    +-------------+---------------+
                                  |
             +--------------------+--------------------+
             |                                         |
+------------v-------------+              +------------v-------------+
| Chainlit Adapter / ACA   |              | Foundry Hosted Agent     |
| Current user-facing UI   |              | Foundry playground/evals |
+--------------------------+              +--------------------------+
```

## Current Context

### Current runtime

- Main app: `agent/app/apex.py`
- Current UI: Chainlit on port `8000`
- Health server: `agent/app/health_server.py` on port `8080`
- Startup: `agent/app/start_services.sh`
- Container: `agent/app/Dockerfile`

### Current Foundry integration

- `agent/app/foundry_v2.py`
- `agent/app/foundry_v2_runtime.py`
- `agent/app/foundry_publish.py`
- `agent/app/agent_registry.py`

Current flow:

```text
Chainlit message
  -> apex.py
  -> Foundry prompt agent via Responses API agent_reference
  -> Foundry returns function calls
  -> apex.py executes local Python tools
  -> apex.py submits function_call_output
  -> Chainlit renders response
```

### Current tool surface

Primary tools are assembled from:

- `agent/app/user_functions.py`
- `_build_lucy_function_list()` in `agent/app/apex.py`
- core helper tools in `agent/app/apex.py`
- handoff tools from `setup_handoff_functions()`

Important tool dependencies:

- Dynamics 365 / Dataverse
- Azure AI Search
- Azure Blob Storage
- Azure Tables
- Agent Portal
- Teams
- SMTP/email fallback

### Human-in-the-loop / portal

- Portal app: `portal/app/agent_portal.py`
- Portal startup: `portal/app/start_agent_portal.sh`
- Portal container: `portal/app/Dockerfile`
- Tables:
  - `conversations`
  - `callbacks`
  - `agentregistry`
- Blob containers include:
  - `lucycmnotices`
  - `lucygenericnotices`
  - `lucyrag`

## Migration Principles

1. Do not break the existing Chainlit production path.
2. Do not rewrite business tools unless necessary.
3. Extract runtime core before introducing Hosted Agent protocol code.
4. Keep Hosted Agent as a parallel canary first.
5. Preserve Azure Tables / Blob / Dynamics behavior.
6. Make evalability and observability first-class migration requirements.
7. Treat portal/handoff security as a prerequisite for production Hosted Agent exposure.

## Phase 0 — Production Safety Prerequisites

These should be completed before allowing a Hosted Agent deployment to execute full production tools.

### 0.1 Secure Portal API

Likely files:

- `portal/app/agent_portal.py`
- `agent/app/user_functions.py`
- `portal/app/.env.example`
- `agent/app/.env.example`

Tasks:

1. Require `AGENT_PORTAL_API_TOKEN` in production.
2. Add auth dependency to sensitive portal routes:
   - `POST /api/handoff`
   - `POST /api/conversations/{conversation_id}/timeout`
   - `POST /api/teams/availability`
   - `POST /api/teams/availability/check`
   - `GET /api/teams/availability/check/{request_id}`
   - `POST /api/teams/webhook`, or add webhook-specific validation
   - `GET /api/metrics/current`
   - `WebSocket /ws/conversation/{conversation_id}`
   - `WebSocket /ws/metrics`
3. Update Lucy handoff call in `agent/app/user_functions.py` to send:
   - `Authorization: Bearer {AGENT_PORTAL_API_TOKEN}` or
   - `X-Agent-Token: {AGENT_PORTAL_API_TOKEN}`
4. Add tests proving unauthenticated requests are rejected and authenticated requests pass.

Validation:

- Unit/API tests for portal auth.
- Manual curl smoke test against deployed portal.

### 0.2 Disable GenAI Content Recording in Production

Current deployed agent had `AZURE_TRACING_GEN_AI_CONTENT_RECORDING_ENABLED=true`.

Tasks:

1. Set production default to `false`.
2. Add startup warning or fail gate if enabled in production without explicit override.
3. Document compliance implications.

### 0.3 Fix Health Probes

Current Container Apps show no configured probes and external `/health` hits Chainlit HTML.

Tasks:

1. Add ACA startup/readiness/liveness probes.
2. Either expose health on the main port or configure probes against the actual health server port if supported.
3. Ensure readiness verifies:
   - Foundry endpoint configured
   - Azure Tables reachable
   - Blob reachable
   - AI Search reachable
   - App Insights exporter configured in production

### 0.4 Storage and Blob Hardening

Tasks:

1. Move storage connection string/account key values to Container App secret refs or Key Vault.
2. Prefer managed identity / user delegation SAS over account-key SAS.
3. Validate allowed storage accounts/containers before SAS generation.
4. Review public access on `lucygenericnotices`.
5. Centralize SAS generation logic to avoid drift.

## Phase 1 — Extract Lucy Runtime Core

Goal: make Lucy’s agent logic callable without Chainlit.

### New package layout

Create:

```text
agent/app/lucy_core/
  __init__.py
  config.py
  session.py
  runtime.py
  responses_loop.py
  tool_registry.py
  artifacts.py
  handoff.py
  errors.py
```

### 1.1 Define portable data models

File: `agent/app/lucy_core/session.py`

Suggested models:

```python
@dataclass
class LucySession:
    session_id: str
    conversation_id: str | None = None
    previous_response_id: str | None = None
    authenticated: bool = False
    apex_id: str | None = None
    user_name: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
```

```python
@dataclass
class LucyRequest:
    input_text: str
    session: LucySession
    metadata: dict[str, Any] = field(default_factory=dict)
```

```python
@dataclass
class LucyArtifact:
    type: str
    label: str
    url: str | None = None
    blob_url: str | None = None
    expires_at: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
```

```python
@dataclass
class LucyResponse:
    text: str
    session: LucySession
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    artifacts: list[LucyArtifact] = field(default_factory=list)
    handoff: dict[str, Any] | None = None
    trace_id: str | None = None
    errors: list[dict[str, Any]] = field(default_factory=list)
```

### 1.2 Move tool-list construction

Current source:

- `_build_lucy_function_list()` in `agent/app/apex.py`
- `_build_function_registry()` in `agent/app/apex.py`
- `_toolset_signature()` in `agent/app/apex.py`

Target:

- `agent/app/lucy_core/tool_registry.py`

Responsibilities:

1. Build all Lucy tools.
2. Build function registry.
3. Compute toolset signature.
4. Avoid Chainlit imports.

### 1.3 Move Responses loop

Current source:

- `_run_response_v2()` in `agent/app/apex.py`
- `_extract_v2_function_calls()` in `agent/app/apex.py`
- `_execute_v2_tool_call()` in `agent/app/apex.py`
- `_build_authenticated_state_items()` in `agent/app/apex.py`

Target:

- `agent/app/lucy_core/responses_loop.py`

Key change:

Replace this pattern:

```python
conversation_id = cl.user_session.get("conversation_id")
cl.user_session.set("previous_response_id", response_id)
```

with:

```python
conversation_id = session.conversation_id
session.previous_response_id = response_id
```

### 1.4 Create `LucyRuntime`

File: `agent/app/lucy_core/runtime.py`

Interface:

```python
class LucyRuntime:
    async def initialize(self) -> None:
        ...

    async def respond(self, request: LucyRequest) -> LucyResponse:
        ...
```

Responsibilities:

1. Initialize Foundry project client.
2. Initialize/open OpenAI Responses client.
3. Register/reconcile agent version if continuing to use prompt-agent internally.
4. Execute Responses loop.
5. Return portable `LucyResponse`.

### 1.5 Keep Chainlit working

Modify `agent/app/apex.py` only enough to call `LucyRuntime.respond()` from `@cl.on_message`.

Chainlit should adapt:

```text
cl.user_session -> LucySession -> LucyRuntime.respond -> Chainlit render
```

Validation:

- Existing `agent/tests` still pass.
- Add unit tests for `LucySession`, tool registry, response loop with mocked OpenAI client.
- Smoke test Chainlit locally if possible.

## Phase 2 — Artifact and Handoff Abstractions

Goal: make non-text outputs portable across Chainlit, Hosted Agent, and evals.

### 2.1 Artifact normalization

Current PDF/blob rendering is partly Chainlit-specific.

Create:

- `agent/app/lucy_core/artifacts.py`

Responsibilities:

1. Detect PDF/blob results from tool outputs.
2. Return `LucyArtifact` objects.
3. Do not render Chainlit elements in core.

Artifact examples:

```json
{
  "type": "pdf",
  "label": "Notice packet",
  "url": "https://...sas-redacted-for-logs...",
  "metadata": {
    "container": "lucycmnotices",
    "blob_name": "...",
    "apex_id_hash": "..."
  }
}
```

### 2.2 Chainlit artifact adapter

In `agent/app/apex.py`, render artifacts:

- PDF artifact -> `cl.Pdf`
- link artifact -> markdown link
- handoff artifact -> status message/action

### 2.3 Hosted Agent artifact adapter

In new hosted-agent adapter, map artifacts into the response shape supported by Microsoft’s hosted-agent protocol/sample.

If protocol does not support rich artifacts cleanly, include stable JSON metadata in response output and retain artifact records in traces/eval outputs.

### 2.4 Explicit handoff result

Create:

- `agent/app/lucy_core/handoff.py`

Normalize handoff from tool output into:

```json
{
  "created": true,
  "conversation_id": "...",
  "portal_url": "...",
  "status": "pending",
  "reason": "..."
}
```

Validation:

- Notice/PDF scenario returns both text and artifact.
- Handoff scenario returns explicit handoff payload.
- Chainlit still renders current UX.

## Phase 3 — Add Hosted Agent Adapter

Goal: deploy Lucy core as a Foundry Hosted Agent container.

### New files

```text
agent/hosted_agent/
  app.py
  Dockerfile
  requirements.txt
  README.md
  azure.yaml or azd-compatible project files
```

Exact file names may change depending on Microsoft’s sample template.

### 3.1 Start from Microsoft quickstart sample

Use the hosted-agent quickstart as the base:

- `https://learn.microsoft.com/en-us/azure/foundry/agents/quickstarts/quickstart-hosted-agent?pivots=azd`
- `https://learn.microsoft.com/en-us/azure/foundry/agents/concepts/hosted-agents`
- `https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/deploy-hosted-agent`

Key hosted-agent requirements to verify from docs/sample before implementation:

1. Expected server framework/library.
2. Expected port, commonly `8088` in current hosted-agent docs/samples.
3. Required health/readiness routes.
4. Responses vs Invocations protocol handler shape.
5. Required manifest/deployment config.
6. Container image architecture: linux/amd64.
7. ACR public endpoint requirement.
8. Identity/RBAC setup.
9. Local test command.
10. Log streaming command.

### 3.2 Implement protocol adapter

Pseudo-flow:

```python
runtime = LucyRuntime()
await runtime.initialize()

async def handle_hosted_agent_request(request):
    lucy_session = map_request_to_lucy_session(request)
    lucy_request = LucyRequest(
        input_text=extract_user_text(request),
        session=lucy_session,
        metadata=extract_metadata(request),
    )
    lucy_response = await runtime.respond(lucy_request)
    return map_lucy_response_to_hosted_agent_response(lucy_response)
```

### 3.3 Hosted Agent config

Environment variables needed:

- Foundry:
  - `AZURE_AI_FOUNDRY_PROJECT_ENDPOINT`
  - `AZURE_AI_SERVICES_ENDPOINT`
  - `MODEL_DEPLOYMENT_NAME` or `AZURE_GPT_MODEL`
  - `FOUNDRY_AGENT_NAME`
  - `FOUNDRY_APPLICATION_NAME`
- Search:
  - `AI_SEARCH_PROJECT_CONNECTION_NAME` or `AI_SEARCH_PROJECT_CONNECTION_ID`
  - `AI_SEARCH_INDEX_NAME`
  - `SEARCH_QUERY_TYPE`
  - `SEARCH_TOP_K`
- Storage:
  - `AZURE_STORAGE_ACCOUNT_NAME`
  - managed identity RBAC preferred
  - or secret-backed `AZURE_STORAGE_CONNECTION_STRING`
- Dynamics:
  - ideally Key Vault references or managed identity where possible
  - current app uses client ID/secret/resource URL/tenant ID
- Portal:
  - `AGENT_PORTAL_ENABLED`
  - `AGENT_PORTAL_URL`
  - `AGENT_PORTAL_API_TOKEN`
- Observability:
  - `APPLICATIONINSIGHTS_CONNECTION_STRING`
  - `AZURE_TRACING_GEN_AI_CONTENT_RECORDING_ENABLED=false`
  - `ENVIRONMENT=production`

### 3.4 Local hosted-agent test

Before Azure deployment:

1. Run hosted-agent container locally.
2. Send sample hosted-agent protocol request.
3. Validate text response.
4. Validate simple tool call.
5. Validate trace/log output.

Validation cases:

- General question, no tools.
- Member auth mocked or non-mutating lookup.
- Notice lookup mocked or staging Blob/Search.

## Phase 4 — Identity and Azure RBAC

Goal: Hosted Agent identity can access everything Lucy needs.

### 4.1 Identify Hosted Agent identity

After deployment, Foundry creates or associates an agent identity.

Record:

- principal ID
- client ID if applicable
- tenant
- resource group
- Foundry project/account

### 4.2 Required role assignments

Likely roles:

#### Storage

For Blob:

- `Storage Blob Data Reader`
- possibly `Storage Blob Delegator` for user delegation SAS

For Tables:

- `Storage Table Data Contributor`

#### Azure AI Search

- Search index data reader role appropriate for query execution
- Search service access if using keyless auth

#### Foundry / AI services

- Project/user role sufficient to invoke model and hosted-agent operations
- Check current Foundry Agent Service role requirements from docs

#### Key Vault, if introduced

- `Key Vault Secrets User`

#### Application Insights / Azure Monitor

- telemetry connection string is usually enough for ingestion
- RBAC may be needed for querying dashboards, not emission

### 4.3 Secrets strategy

Preferred:

1. Managed identity for Azure Storage/Search/Foundry where possible.
2. Key Vault references for Dynamics/SMTP/Teams secrets.
3. No plain env values for account keys or connection strings.

Validation:

- Hosted Agent can query Search.
- Hosted Agent can read Blob and create SAS if required.
- Hosted Agent can upsert/read Azure Table rows.
- Hosted Agent can call Dynamics.
- Hosted Agent emits telemetry.

## Phase 5 — Foundry Playground and Portal Eval Validation

Goal: prove Foundry invokes real Lucy code/tools.

### 5.1 Playground smoke tests

In Foundry playground against the Hosted Agent:

1. Ask a generic support question.
2. Ask for notice help.
3. Authenticate a test/staging member.
4. Trigger a handoff in staging.

Expected:

- Hosted Agent logs show request.
- Tool spans/logs show execution.
- Azure Table writes occur where expected.
- Blob access occurs where expected.
- Response includes expected text/artifact metadata.

### 5.2 Portal eval dataset

Create eval data in JSONL:

```jsonl
{"case_id":"generic_scope","query":"What can Lucy help me with?","expected":"mentions class action settlement support"}
{"case_id":"notice_lookup","query":"I need my notice packet","expected_tool":"find_notice_for_user_sync"}
{"case_id":"handoff_request","query":"I need a human agent","expected_handoff":true}
```

Add richer rows once staging data is safe.

### 5.3 Eval success criteria

For each eval case capture:

- final answer quality
- tool calls made
- tool success/failure
- latency
- safety outcome
- PII leakage check
- handoff/table/blob side effects where relevant

### 5.4 Confirm App Insights / Foundry observability

Queries should show:

- hosted-agent request spans
- model call spans
- tool call spans
- dependency spans for Dynamics/Search/Blob/Tables/Portal
- exceptions if any
- eval result metrics/events

## Phase 6 — Expand Hosted Agent Coverage

After the POC succeeds, port scenarios incrementally.

### 6.1 Tool migration order

1. No-tool general chat.
2. `get_current_datetime`.
3. Authentication tools.
4. Class member details.
5. Notice lookup and Blob artifacts.
6. Disbursement/status read-only tools.
7. Profile/address update tools.
8. Reissue tools.
9. Handoff tools.
10. Callback tools.
11. Agent notes / monitoring tools.

### 6.2 Guardrail migration order

1. Authentication-required tool gates.
2. Tool allowlist per session state.
3. PII redaction in logs/traces.
4. Legal advice refusal/escalation.
5. Prompt injection detection.
6. SAS URL non-disclosure policy.
7. Human handoff on uncertainty/failure.

## Phase 7 — Chainlit Integration with Hosted Agent

Goal: decide whether Chainlit should continue calling local core or call Hosted Agent endpoint.

### Option A — Chainlit uses local `LucyRuntime`

Pros:

- fewer network hops
- simpler production continuity
- Hosted Agent used for Foundry/evals/playground only

Cons:

- two runtime instances can drift if not tested together

### Option B — Chainlit calls Hosted Agent endpoint

Pros:

- one production agent execution path
- Foundry eval and user traffic use same runtime
- cleaner observability

Cons:

- Chainlit becomes dependent on Hosted Agent availability
- additional auth/networking/session mapping complexity
- must handle artifact rendering from Hosted Agent response

Recommendation:

Start with Option A for canary. Move to Option B only after Hosted Agent is stable and observable.

## Phase 8 — Production Canary and Cutover

### 8.1 Canary

Run Hosted Agent in parallel for:

- internal Foundry playground users
- portal evals
- scheduled regression evals
- shadow traffic if safe

### 8.2 Compare outputs

For each test case compare:

- Chainlit current output
- Hosted Agent output
- tool calls
- side effects
- latency
- trace completeness

### 8.3 Cutover decision

Cut over only if:

- all P0/P1 evals pass
- portal handoff works
- storage/blob/search/dynamics tools work
- App Insights has complete traces
- rollback is documented
- Hosted Agent preview constraints are acceptable

## Files Likely to Change

### Agent runtime

- `agent/app/apex.py`
- `agent/app/foundry_v2.py`
- `agent/app/foundry_v2_runtime.py`
- `agent/app/foundry_publish.py`
- `agent/app/response_utils.py`
- `agent/app/tracing_config.py`
- `agent/app/tracing_utils.py`
- `agent/app/user_functions.py`
- `agent/app/conversation_store.py`
- `agent/app/callback_system.py`

### New core package

- `agent/app/lucy_core/__init__.py`
- `agent/app/lucy_core/config.py`
- `agent/app/lucy_core/session.py`
- `agent/app/lucy_core/runtime.py`
- `agent/app/lucy_core/responses_loop.py`
- `agent/app/lucy_core/tool_registry.py`
- `agent/app/lucy_core/artifacts.py`
- `agent/app/lucy_core/handoff.py`
- `agent/app/lucy_core/errors.py`

### New hosted-agent adapter

- `agent/hosted_agent/app.py`
- `agent/hosted_agent/Dockerfile`
- `agent/hosted_agent/requirements.txt`
- `agent/hosted_agent/README.md`
- `agent/hosted_agent/azure.yaml` or equivalent azd files

### Portal/security

- `portal/app/agent_portal.py`
- `portal/app/start_agent_portal.sh`
- `portal/app/.env.example`
- `agent/app/.env.example`

### Tests

Existing:

- `agent/tests/test_foundry_v2_runtime.py`
- `agent/tests/test_foundry_v2_tools.py`
- `agent/tests/test_response_utils.py`
- `agent/tests/test_tracing_utils.py`

New:

- `agent/tests/test_lucy_session.py`
- `agent/tests/test_lucy_tool_registry.py`
- `agent/tests/test_lucy_runtime.py`
- `agent/tests/test_lucy_artifacts.py`
- `agent/tests/test_hosted_agent_adapter.py`
- `portal/tests/test_portal_auth.py`
- `portal/tests/test_handoff_api.py`

## Validation Plan

### Unit tests

Run:

```bash
python -m pytest agent/tests -q
```

Add portal tests and run:

```bash
python -m pytest portal/tests -q
```

### Integration tests

1. Mock OpenAI/Foundry response with function call.
2. Verify `LucyRuntime` executes correct local tool.
3. Verify `function_call_output` payload is correct.
4. Verify session state updates.
5. Verify artifacts are extracted.
6. Verify handoff creates expected Azure Table row in test storage or mocked table client.

### Azure staging tests

1. Deploy Hosted Agent to staging Foundry project.
2. Invoke via Foundry playground.
3. Invoke via eval dataset.
4. Verify Application Insights traces.
5. Verify Azure Table rows.
6. Verify Blob access.
7. Verify portal handoff.

### Production canary tests

1. Non-mutating member lookup.
2. Notice lookup.
3. Handoff to portal test queue.
4. Callback test record.
5. Failure injection:
   - Search unavailable
   - Blob missing
   - portal unavailable
   - Dynamics timeout

## Observability Requirements

Every hosted-agent request should emit:

- request span
- model/Responses span
- tool span per tool call
- dependency span for:
  - Dynamics
  - Azure AI Search
  - Blob Storage
  - Azure Tables
  - Portal API
  - Teams/SMTP
- trace attributes:
  - `lucy.session_id`
  - `lucy.conversation_id`
  - `lucy.turn_id`
  - `lucy.agent.name`
  - `lucy.agent.version`
  - `lucy.tool.name`
  - `lucy.handoff.id`
  - hashed/tokenized Apex ID only

Do not record:

- full SSN or SSN fragments
- raw SAS URLs
- full Dynamics OData filters with PII
- full prompt/completion content in production unless explicitly approved

## Key Risks

### Hosted Agents preview risk

Hosted Agents are preview and may have operational constraints.

Mitigation:

- parallel deployment
- no immediate production cutover
- keep ACA path alive

### Chainlit coupling risk

`apex.py` currently mixes UI and runtime logic.

Mitigation:

- extract core first
- keep changes small and covered by tests

### Session-state mismatch

Hosted Agent session model differs from Chainlit session model.

Mitigation:

- introduce `LucySession`
- persist session state in Azure Tables if needed

### Tool side-effect risk

Foundry evals/playground can trigger real tools.

Mitigation:

- eval mode
- staging resources
- tool allowlist
- dry-run support for mutating tools

### Portal exposure risk

Hosted Agent makes handoff tools easier to invoke from Foundry playground/evals.

Mitigation:

- secure portal first
- require service token
- validate handoff inputs

## Open Questions

1. Which Hosted Agent protocol should Lucy implement first: Responses or Invocations?
2. Should Chainlit call Hosted Agent endpoint after canary, or keep local runtime call?
3. Will production Dynamics allow Hosted Agent identity/key strategy without ACA-specific assumptions?
4. Should mutating tools support `eval_mode=true` dry runs?
5. Should session state live in Foundry session metadata, Azure Tables, or both?
6. Should Blob SAS URLs be returned directly to Foundry playground, or represented as secured artifact references?
7. Are Hosted Agent preview SLA constraints acceptable for production, or should Hosted Agent initially be eval/playground-only?

## Recommended First Sprint

Sprint goal: prove hosted-agent feasibility without changing production behavior.

### Deliverables

1. `LucySession`, `LucyRequest`, `LucyResponse` data models.
2. Extract tool registry from `apex.py` into `lucy_core/tool_registry.py`.
3. Extract Responses loop into `lucy_core/responses_loop.py` without Chainlit dependency.
4. Create `LucyRuntime.respond()`.
5. Update Chainlit to call `LucyRuntime` with equivalent behavior.
6. Add unit tests for runtime with mocked Responses client.
7. Add minimal hosted-agent adapter skeleton from Microsoft quickstart sample.
8. Deploy Hosted Agent to staging with one no-tool scenario and one read-only tool scenario.

### Acceptance criteria

- Existing tests still pass.
- Chainlit still works locally/staging.
- Hosted Agent container starts locally.
- Hosted Agent responds to a simple prompt.
- Hosted Agent can execute at least one read-only Lucy tool.
- App Insights receives at least one request/span from Hosted Agent.
- Foundry playground can interact with the Hosted Agent.

## Final Recommendation

Proceed with migration, but as a staged architecture migration:

1. Extract Lucy runtime core.
2. Build Hosted Agent adapter.
3. Deploy Hosted Agent in parallel.
4. Validate real tool execution through Foundry playground/evals.
5. Only then decide whether to route Chainlit production traffic through Hosted Agent.

This path gives Lucy the benefits of Foundry Hosted Agents while preserving the current working production app and minimizing go-live risk.
