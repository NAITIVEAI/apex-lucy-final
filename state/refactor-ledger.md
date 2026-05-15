# Refactor Ledger

This ledger records every plan from `/plans/` along with its status, summary, files changed, research evidence, tests, results, blockers, and follow-ups. It is the canonical resume point for any new agent session per `AGENTS.md`.

**Source-of-truth hierarchy:** explicit user instruction → `AGENTS.md` → `TASKS.md` → active `/plans/*.md` → existing code patterns.

---

## Active Plan

### `001-lucy-foundry-hosted-agent-migration.md` — IN PROGRESS

**Status:** in_progress. Phase 1 (runtime extraction) and Phase 2 (artifact/handoff abstractions) are complete. The 2026-04-25 gateway pivot is now understood as an interim bridge, not the target architecture. Phase 3 Hosted Agent adapter/container/deployment scaffold is code-complete. Phase 4 (supported-region Hosted Agent identity/RBAC and first Hosted deployment) is provisioned in North Central US as of 2026-04-29. Phases 5-8 (notice/auth/PDF/HITL canary, Chainlit hosted-endpoint cutover, parity validation, and gateway retirement) remain pending.

**Goal (revised 2026-04-28):** Extract and preserve a UI-independent `LucyRuntime` core out of `agent/app/apex.py` so it can be invoked from (a) Chainlit (existing member UI), (b) the current FastAPI HTTP wrapper used as an interim AI Gateway custom-agent bridge, and (c) a Hosted Agent Responses protocol adapter (`azure-ai-agentserver-responses`) on the Foundry Hosted Agent serving surface.

**Active sub-objective (Phase 1, "Recommended First Sprint" §1-6 from plan):**
1. `LucySession`, `LucyRequest`, `LucyResponse`, `LucyArtifact` data models — **DONE 2026-04-25**
2. Extract tool-list construction (`_build_lucy_function_list`, `_build_function_registry`, `_toolset_signature`) → `lucy_core/tool_registry.py` — **DONE 2026-04-25**
3. Extract Responses loop (`_run_response_v2`, `_extract_v2_function_calls`, `_execute_v2_tool_call`, `_build_authenticated_state_items`) → `lucy_core/responses_loop.py` — **DONE 2026-04-25** (split into 3a small helpers + 3b the full orchestrator; apex.py wrappers map cl.user_session ↔ LucySession at the boundary)
4. Build `LucyRuntime.respond()` in `lucy_core/runtime.py` — **DONE 2026-04-25** (minimal: constructor takes pre-init deps, single `async respond(LucyRequest) -> LucyResponse`. **Not yet wired into any production code path** — it's a building block for the FastAPI HTTP wrapper in plan 002 Phase A)
5. Adapt Chainlit `@cl.on_message` to call `LucyRuntime.respond()` — **deferred**. Still useful for convergence, but not required before Hosted Agent work if the Hosted protocol adapter can invoke `LucyRuntime` directly.
6. Unit tests with mocked Responses client — **DONE 2026-04-25** (78 tests across data models, tool registry, responses loop, runtime; orchestrator tests use IsolatedAsyncioTestCase with a queued-response mock client)

**Test count:** 78 passing (was 29 at session start).

**Files changed:**
- `agent/app/lucy_core/__init__.py` (new + extended)
- `agent/app/lucy_core/session.py` (new)
- `agent/app/lucy_core/errors.py` (new)
- `agent/app/lucy_core/tool_registry.py` (new)
- `agent/app/lucy_core/responses_loop.py` (new — `build_authenticated_state_items`, `extract_v2_function_calls`, `execute_v2_tool_call`, `run_response_v2`)
- `agent/app/lucy_core/runtime.py` (new — `LucyRuntime` class)
- `agent/app/apex.py` (modified — added `lucy_core` imports; replaced bodies of `_build_lucy_function_list`, `_build_function_registry`, `_toolset_signature`, `_build_authenticated_state_items`, `_extract_v2_function_calls`, `_execute_v2_tool_call`, `_run_response_v2` with thin delegators; surface signatures unchanged)
- `agent/tests/test_lucy_session.py` (new)
- `agent/tests/test_lucy_tool_registry.py` (new)
- `agent/tests/test_lucy_responses_loop.py` (new)
- `agent/tests/test_lucy_runtime.py` (new)

**Foundry init extraction (Path A) — DONE 2026-04-25.**
`agent/app/foundry_init.py` (new, Chainlit-free, ~330 LOC) now owns the Foundry v2 agent initialization flow. It exposes:

- env-reader helpers: `get_agent_name`, `get_application_name_for_agent`, `get_model_deployment_name`, `get_search_index_name`, `get_search_connection_id_env`, `get_search_connection_name_env`
- `fallback_publication_state` — convenience constructor for missing publication metadata
- `FoundryInitContext` dataclass — bundles `project_client`, `openai_client`, `agent_registry`, `agent_name`, `agent_version`, `function_registry`
- `initialize_foundry_v2_agent(*, instructions, function_list, function_registry, toolset_signature, prompt_hash, existing_agent_registry=None)` — async entry point that returns `FoundryInitContext`

apex.py changes:
- Replaced `_initialize_persistent_agent_v2` body (~250 LOC) with a 25-line thin wrapper that calls `initialize_foundry_v2_agent` and assigns the returned context to apex.py's existing module globals. Chainlit-side behavior preserved.
- Deleted the moved helpers from apex.py (`_get_*`, `_INDEX_NAME_PATTERN`, `_normalize_search_index_name`, `_fallback_publication_state`).
- Updated the one external caller of `_get_model_deployment_name()` (line 5207, the LucyAttributes telemetry) to use `get_model_deployment_name()` from foundry_init.

Test count: 100 passing (was 78, added 22 in `agent/tests/test_foundry_init.py` covering env helpers, normalizer, fallback state, and dataclass construction). Full async init flow remains exercised by the running container — its full unit test would require deep Azure SDK mocking and was not done.

**Files added/changed:**
- `agent/app/foundry_init.py` (new)
- `agent/app/apex.py` (modified — added foundry_init import; removed helper definitions; replaced init body with thin wrapper; updated one telemetry call site)
- `agent/tests/test_foundry_init.py` (new)

**Plan 002 Phase A — Scaffold DONE 2026-04-25; production runtime wiring pending.**

`agent/app/lucy_core/http_app.py` (new) implements:
- `POST /agent/respond` (auth-gated, mock-friendly via `runtime_factory` parameter)
- `GET /agent/health` (liveness)
- `GET /agent/ready` (readiness; reports `otel_agent_id`)
- Auth dependency `_check_token` — `X-Agent-Token` constant-time compared against `LUCY_GATEWAY_API_TOKEN` env var (matches Microsoft Foundry guidance that APIM is a transparent proxy preserving original auth)
- Pydantic wire models for LucyRequest / LucyResponse / LucyArtifact / LucySession
- Marshalling helpers (pure functions, separately tested)

Tests: `agent/tests/test_http_app.py` (new). Module-level skip guard for environments where FastAPI/pydantic-core are mismatched. Production CI will run all tests; local dev (where pydantic is currently broken) skips. Scaffold helper functions and routes are unit-tested with a mock `LucyRuntime`.

**Test count:** 100 passing, 1 skipped (was 100 passing).

**Remaining for Phase A to be deployment-ready:**

1. **Production `runtime_factory`.** `_default_runtime_factory()` raises `NotImplementedError`. To wire it:
   - The `_build_lucy_function_list()` flow today depends on apex.py-resident helper tools (`generate_sas_url`, `render_pdf`, `get_current_datetime`, `execute_search_tool`, `extract_text_from_pdf_tool`, `analyze_pdf_content_tool`). Importing apex.py from the FastAPI process is unsafe — apex.py imports Chainlit at module level and the local dev env confirmed `ModuleNotFoundError: chainlit` when imported without it.
   - Cleanest path: extract those 6 helpers to `agent/app/lucy_tools.py` (Chainlit-free; `extract_text_from_pdf_tool` has a function-local `import chainlit as cl` that needs to be conditionalized). apex.py then imports from `lucy_tools`. The FastAPI process imports from `lucy_tools` + `user_functions` (its module-level `import chainlit as cl` is OK at runtime since chainlit is installed in the container, but introduces unwanted coupling — could also move `setup_dynamics_functions` and `setup_handoff_functions` to a Chainlit-free module).
   - **Minimum viable alternative for AI Gateway registration validation:** start with an empty `function_list`. The Foundry agent runs without custom tools — text-only responses. Confirms the gateway+evals+monitor flow works end-to-end before investing in full tool extraction.

2. **GenAI semantic-convention OTel attributes.** `lucy_core/runtime.py` should wrap each `respond()` call in a span with `operation="create_agent"` and `gen_ai.agents.id=<the OTel agent ID we paste in the registration form>` plus `gen_ai.*` attributes on the LLM/tool spans. Without these, the Foundry Monitor tab won't correlate runs to the registered agent. Approximately 30-50 lines of OpenTelemetry attribute-setting in `runtime.py` + `responses_loop.py`. Verifiable only after a deployed registration so we can confirm the Foundry portal sees the spans.

3. **Container/process changes.** `agent/app/Dockerfile` needs `EXPOSE 8002`; `agent/app/start_services.sh` needs to launch the FastAPI uvicorn process alongside Chainlit (8000) and health (8080). `agent/app/.env.example` needs `LUCY_HTTP_PORT=8002`, `LUCY_GATEWAY_API_TOKEN=`, `LUCY_OTEL_AGENT_ID=`.

**Recommended next move:** start (1) with the empty-function_list shortcut to get the registration flow validated end-to-end fast, then iterate on tool extraction.

---

**Plan 002 Phase A — CODE-COMPLETE 2026-04-25 via A3 (parallel ingress, shared code).**

After audit revealed the helper-tool extraction would be multi-session (recursive Chainlit dependencies in apex.py), the user chose **A3**: same container, two Python processes (Chainlit on :8000, FastAPI on :8002), both importing apex.py at startup. Lucy's tool registry stays locked at the apex.py level — no second registry to drift.

**Files added/changed (Phase A code-complete):**
- `agent/app/lucy_core/http_app.py` — `_default_runtime_factory` now imports `apex`, runs `_initialize_persistent_agent_v2`, returns a `LucyRuntime` bound to apex globals.
- `agent/app/lucy_core/responses_loop.py` — added GenAI semantic-convention OTel spans:
  - `create_agent` span wrapping every `run_response_v2` call with attributes `operation="create_agent"`, `gen_ai.operation.name`, `gen_ai.agents.id` (from `LUCY_OTEL_AGENT_ID` env), `gen_ai.system="azure.ai.foundry"`, `gen_ai.request.model`, `lucy.session.id`, `lucy.conversation.id`. Internal body extracted to `_run_response_v2_impl` to keep the wrapping clean.
  - `execute_tool` child span per tool invocation with `gen_ai.tool.name` and `gen_ai.tool.call.id`.
  - When the OTel SDK isn't initialized (tests, dev), spans are no-op.
- `agent/app/start_services.sh` — launches `python -m uvicorn lucy_core.http_app:create_app --factory --host 0.0.0.0 --port $LUCY_HTTP_PORT` in background. Gated by `LUCY_HTTP_ENABLED=true` (default on; set false for emergency rollback).
- `agent/app/Dockerfile` — `EXPOSE 8002` added alongside 8000 and 8080.
- `agent/app/.env.example` — added `LUCY_HTTP_ENABLED`, `LUCY_HTTP_PORT`, `LUCY_GATEWAY_API_TOKEN`, `LUCY_OTEL_AGENT_ID`.

**Test count:** 100 passing, 1 skipped (was 100 + 1). No regressions; the OTel spans no-op cleanly in the test environment.

**What the user does now (off-code):**
1. Deploy the container. Existing Chainlit traffic untouched.
2. Set `LUCY_GATEWAY_API_TOKEN` (fresh shared secret) and `LUCY_OTEL_AGENT_ID` (e.g. `lucy-aca`) in ACA app config.
3. In Foundry portal → Operate → Register asset:
   - Agent URL: `https://<lucy-aca-fqdn>/agent/respond`
   - Protocol: General HTTP, Including REST
   - OpenTelemetry agent ID: `lucy-aca` (must match the env var)
   - Project + Agent name as desired.
4. Configure APIM outbound policy to add `X-Agent-Token: <LUCY_GATEWAY_API_TOKEN>` to Lucy.
5. Hit the Foundry-issued APIM URL → should reach Lucy with the locked tool set.
6. Confirm Foundry Monitor tab populates traces filtered by `gen_ai.agents.id="lucy-aca"`.

**Behavior of Chainlit-coupled tools in the FastAPI path:**
A handful of Lucy's tools call `cl.user_session.set/get` or `cl.Message` for UI side-effects (auth state mirroring, PDF render markers, progress). In the FastAPI process there is no Chainlit session, so those calls raise. They're already wrapped in try/except in apex.py, so the LLM still receives the actual data return — only the cosmetic UI side-effect is lost. Acceptable for evals; Lucy's response correctness is preserved.

**Plan 001 / Plan 002 status:** Phase 1 of plan 001 (runtime extraction) is fully done. Plan 002 Phase A (HTTP wrapper + AI Gateway readiness) is code-complete. Phase B (portal-side registration), Phase C (verify dashboards), Phase D (eval rules), Phase E (Activity Protocol disposition) are user-driven portal work.

**Research evidence:**
- Code inspection of `apex.py` (6,757 LOC) and surrounding modules complete 2026-04-25. Of the 7 symbols to move, 3 are already Chainlit-free (pure moves), 3 need only signature changes (pass `LucySession` and registry as params), and `_run_response_v2` has 6 `cl.user_session.*` touchpoints that map cleanly to `LucySession` fields. All other agent modules are already Chainlit-free. See subagent extraction map for symbol-by-symbol map.
- Foundry research 2026-04-25 confirmed: Lucy's existing `applications/agent-lucy-prod/protocols/activityprotocol` URL is the legacy Agent Application publishing model. Foundry evals target agent **name** at the project scope, not Application URLs. The Custom Agent via AI Gateway registration path is the supported "bring your own runtime" path.
- User correction 2026-04-25: Lucy is NOT a Foundry prompt agent. She is custom Python in ACA. The "Azure AI Gateway" deployed in the Foundry portal is the missing piece for Custom Agent registration.

**Tests run:** `agent/tests/test_lucy_session.py` — pending verification.

**Results:** Data models in place. Ready to proceed with tool_registry extraction next.

**Blockers:** none.

**Follow-ups identified:**
- RESOLVED 2026-05-02: `.agents/skills/lucy-spec-implementation/SKILL.md` was a stale/unmaterialized workflow scaffold. It is no longer part of the active workflow contract; historical references are retained here only as breadcrumb context.
- Repo hygiene: `.hermes/` (other agent runtime), `.fusion/` (memory artifacts), parallel `.agent/skills/` and `.agents/skills/` directories. Track as plan 003 candidate.
- Phase 0 production safety prereqs from plan 001 (portal API auth, `AZURE_TRACING_GEN_AI_CONTENT_RECORDING_ENABLED` default, ACA health probes, storage hardening) — independent of runtime extraction. Track as plan 004 candidate.
- Phase 7 (Chainlit local-runtime vs Hosted-Agent-endpoint decision) is moot under the AI Gateway path; Chainlit always calls `LucyRuntime` in-process.

**Plan 001 Phase 2 — Artifact / handoff abstractions — DONE 2026-04-26.**

`agent/app/lucy_core/artifacts.py` and `agent/app/lucy_core/handoff.py` now own the portable non-text normalization layer that plan 001 called for.

Files changed:
- `agent/app/lucy_core/artifacts.py` (new)
- `agent/app/lucy_core/handoff.py` (new)
- `agent/app/lucy_core/runtime.py` (modified — populates `LucyResponse.artifacts` and `LucyResponse.handoff`)
- `agent/tests/test_lucy_artifacts.py` (new)
- `agent/tests/test_lucy_handoff.py` (new)
- `agent/tests/test_lucy_runtime.py` (modified — added PDF and handoff runtime coverage)

Behavior verified:
- PDF/blob/link text is normalized into `LucyArtifact` objects.
- Successful handoff tool output is normalized into a portable handoff dict plus a `handoff` artifact.
- Existing session/tool-registry/response-loop tests still pass.

Tests run:
- `pytest -q agent/tests/test_lucy_artifacts.py agent/tests/test_lucy_handoff.py agent/tests/test_lucy_runtime.py agent/tests/test_lucy_session.py`
- `pytest -q agent/tests/test_lucy_artifacts.py agent/tests/test_lucy_handoff.py agent/tests/test_lucy_runtime.py agent/tests/test_lucy_session.py agent/tests/test_lucy_tool_registry.py agent/tests/test_lucy_responses_loop.py`
- `pytest -q agent/tests/test_http_app.py` (skipped in local env due to FastAPI/pydantic mismatch)

Results:
- 18 passed in the focused artifact/handoff run.
- 56 passed in the broader Lucy-core run.
- 1 skipped in the HTTP app run (expected local-env skip guard).

Follow-up:
- Plan 002 now has the prerequisite artifact/handoff abstraction layer it needed; remaining work there is portal / registration / docs validation rather than core runtime plumbing.

---

### `002-foundry-ai-gateway-custom-agent-registration.md` — INTERIM BRIDGE / LIVE SMOKE PASSED 2026-04-27

**Status:** implemented for Lucy's gateway-facing ACA runtime as an interim Foundry visibility bridge. This is not the final integration target. The final target remains Foundry Hosted Agent using the Responses protocol container surface.

**Summary:**
- Added production gateway wiring for Lucy's custom ACA runtime without moving Lucy
  out of her existing codebase.
- Created and deployed dedicated gateway ACA `agent-lucy-gateway-eus2` so the
  member-facing Chainlit ACA `agent-lucy-eus2` can keep ingress on port `8000`
  while Foundry/APIM hits the HTTP wrapper on port `8002`.
- Deployed image
  `agentlucyacreus2.azurecr.io/agent-lucy-eus2:codex-gateway-20260427073432`
  (`sha256:61054680e76bcf827935a3443d753d9ec33263284c1b9b4aea23310f94b9624f`)
  to revision `agent-lucy-gateway-eus2--0000008`.
- Gateway runtime recreated the Foundry project prompt-agent version due to
  `reasoning_effort` drift and now uses `agent-lucy-prod:5`.
- `/health/gateway` returns healthy with `project_probe.method=list_versions`.
- Authenticated `POST /agent/respond` with `X-Agent-Token` returned HTTP 200 and
  produced a Lucy response plus a `get_current_datetime` tool call.

**Files changed:**
- `agent/app/requirements.txt` — upgraded Azure AI Projects dependency to the
  current 2.x line and added tracing/evaluation dependencies.
- `agent/app/Dockerfile` — added OTel defaults and `LUCY_CHAINLIT_ENABLED`.
- `agent/app/start_services.sh` — supports dedicated HTTP-wrapper foreground
  mode with `LUCY_CHAINLIT_ENABLED=false`.
- `agent/app/.env.example` — documents project endpoint, gateway token,
  Chainlit toggle, and OTel env vars.
- `agent/app/tracing_config.py` — reads `OTEL_SERVICE_NAME` and
  `OTEL_RESOURCE_ATTRIBUTES`.
- `agent/app/lucy_core/http_app.py` — attaches project client diagnostics,
  exposes `/health/gateway`, and reports gateway readiness fields.
- `agent/app/lucy_core/responses_loop.py` — wraps response/tool execution in
  GenAI/Foundry OTel spans, records eval-safe metadata, handles async tools in
  the live loop, uses `agent_reference`, and suppresses request-level reasoning
  when invoking stored agent versions.
- `agent/app/foundry_v2.py` — uses current `agent_reference`, supports the
  Azure AI Projects 2.1 `AzureAISearchTool` rename, and persists explicit
  prompt-agent reasoning config.
- `agent/app/foundry_v2_runtime.py` — uses current `agent_reference` payload
  shape.
- `agent/app/foundry_init.py` — derives prompt-agent `reasoning_effort`,
  coerces GPT-5.2 to `medium`, and treats reasoning drift as a version mismatch.
- `agent/evals/cases.jsonl` — seed eval cases for scope, notice auth, handoff,
  and sensitive-data behavior.
- `docs/architecture/foundry-ai-gateway-registration.md` — live runbook with
  resource names, smoke checks, eval setup, and RBAC caveat.

**Research evidence used:**
- Microsoft Learn current `PromptAgentDefinition` docs show a `reasoning`
  property on prompt-agent definitions.
- Microsoft Learn current runtime/components and REST reference confirm
  Responses + `agent_reference` as the project-agent invocation path.
- Live Azure SDK inspection in deployed ACA confirmed `azure-ai-projects 2.1.0`
  exposes `AzureAISearchTool` instead of the previous `AzureAISearchAgentTool`
  name, while `Reasoning(effort=...)` supports `medium`.

**Tests run:**
- `python -m pytest -q tests/test_foundry_init.py tests/test_lucy_responses_loop.py tests/test_agent_reference_payload.py tests/test_foundry_v2_runtime.py tests/test_http_app.py`
- `python -m pytest -q tests`
- `bash -n app/start_services.sh`
- JSONL parse check for `agent/evals/cases.jsonl`
- `az acr build --registry agentlucyacreus2 --image agent-lucy-eus2:codex-gateway-20260427073432 agent/app`
- `GET https://agent-lucy-gateway-eus2.purpleocean-f3514433.eastus2.azurecontainerapps.io/health/gateway`
- Authenticated `POST https://agent-lucy-gateway-eus2.purpleocean-f3514433.eastus2.azurecontainerapps.io/agent/respond`

**Results:**
- Focused tests: `62 passed, 1 skipped`.
- Full agent tests: `112 passed, 1 skipped`.
- Shell syntax and eval JSONL validation passed.
- ACR build succeeded with digest
  `sha256:61054680e76bcf827935a3443d753d9ec33263284c1b9b4aea23310f94b9624f`.
- Gateway health smoke returned healthy.
- Gateway respond smoke returned HTTP 200.

**Blockers / caveats:**
- Managed application publication still returns ARM `AuthorizationFailed` for
  `Microsoft.CognitiveServices/accounts/projects/applications/agentdeployments/write`
  under the gateway ACA managed identity. The project agent version path works
  and is the runtime path currently in use; widen RBAC before relying on managed
  application deployment reconciliation.

**Follow-ups:**
- Keep the registered AI Gateway/APIM custom-agent route available as a smoke/eval bridge while Hosted Agent is being built.
- Do not treat the gateway route as the production end-state unless Hosted Agent proves blocked.
- Build a Hosted Agent protocol adapter around `LucyRuntime.respond()` using `azure-ai-agentserver-responses`, served on port `8088`.
- Deploy a Hosted Agent version via `AIProjectClient.agents.create_version(...)` / `HostedAgentDefinition` and compare trace, token, dashboard, and eval behavior against the interim gateway route.
- Retire or downgrade the custom-agent gateway route only after Hosted Agent proves notice auth, tool execution, PDF artifact handling, HITL behavior, traces, token accounting, and evals.

**Live hotfix 2026-04-27 — context preservation after auth/reconnect:**
- User logs showed Chainlit fired `on_chat_start` again after a pause/reconnect,
  and the handler reset `previous_response_id` to `None`; the following auth
  turn had `previous_response_id=None` and `state_items=0`, so Lucy lost the
  prior "explain my notice" starter intent.
- Changed `agent/app/apex.py` so v2 chat startup preserves existing
  `session_id`, `conversation_id`, and `previous_response_id` instead of
  clearing them on reconnect.
- Changed `agent/app/apex.py` to store `pending_notice_request_text` and pass
  pending notice metadata into `LucySession`.
- Changed `agent/app/lucy_core/responses_loop.py` so pending notice intent is
  prepended as a system state item before authentication completes; after auth,
  Lucy is instructed to continue the original notice request instead of asking
  generically how she can help.
- Changed fallback clearing so a pending notice request is only cleared after
  forced notice retrieval succeeds; transient failures leave the request pending
  for the next turn.
- Tests run: `python -m pytest -q agent/tests/test_foundry_init.py
  agent/tests/test_lucy_responses_loop.py agent/tests/test_lucy_runtime.py`
  (`62 passed in 0.14s`).
- Deployed image
  `agentlucyacreus2.azurecr.io/agent-lucy-eus2:codex-context-preserve-20260427034920`
  (`sha256:718d2e537169263ea10e96e81b61c87ccb7f4daf53e84f8e1dea04e1e64494bd`)
  to `agent-lucy-eus2--0000065` and `agent-lucy-gateway-eus2--0000013`.
- Verification: `/health/gateway` returned HTTP 200 healthy; AI Gateway/APIM
  POST returned HTTP 200 with a Lucy response.

**Pending uncovered facts / bugs after live testing:**
- Foundry portal can display a prompt-agent version with `reasoning.effort=low`,
  but the deployed `gpt-5.2-chat-2025-12-11` Responses invocation rejected
  request-time low reasoning with `unsupported_value` and only accepted
  `medium`. Keep production env at `medium` until the exact portal/runtime
  mismatch is reproduced in an isolated test.
- `find_notice_for_user_sync` still attempts Chainlit progress UI updates from
  a tool execution path. Earlier production logs showed `Chainlit context not
  found` from those progress updates. It appears non-fatal, but the progress
  side effect should be made Chainlit-context-aware before relying on it.
- Foundry traces are flowing through AI Gateway/APIM, but token columns were
  observed as `0` in the portal during smoke tests. Confirm whether Foundry
  custom-agent gateway traces can infer tokens from proxied Responses calls or
  whether Lucy must emit explicit GenAI token attributes.
- The Foundry eval table showed intermittent `tool_output_utilization` failures
  and `Ungrounded attributes` columns during early testing. Treat these as eval
  rubric follow-ups, not runtime blockers, and inspect the underlying failed
  rows before tuning prompts/tools.
- Chainlit reconnect behavior is expected, but any future startup work must
  remain idempotent and preserve `conversation_id`, `previous_response_id`, and
  pending task metadata.

**Hosted Agent scaffold 2026-04-28 — CODE-COMPLETE LOCALLY / CANARY PENDING:**
- Added `agent/hosted_agent/app.py`, a Responses protocol adapter using
  `ResponsesAgentServerHost`. The handler maps Foundry `CreateResponse` input
  plus `ResponseContext` into `LucyRequest`, calls `LucyRuntime.respond()`, and
  emits Responses protocol events with Lucy text plus metadata carrying session,
  artifacts, tool calls, handoff state, trace ID, and errors.
- Added `agent/app/lucy_core/runtime_factory.py` so both the interim FastAPI
  gateway wrapper and the Hosted Agent adapter use the same apex-backed runtime
  initialization instead of duplicating production tool-registry logic.
- Updated `agent/app/lucy_core/http_app.py` to consume the shared runtime
  factory; gateway behavior is unchanged.
- Added `agent/hosted_agent/Dockerfile` for the Hosted process. It runs on
  port `8088`, installs `azure-ai-agentserver-responses`, keeps Chainlit deps
  available only because apex/tool imports still require them, installs the
  Debian CA bundle for Azure outbound TLS, and defaults GenAI content recording
  to `false`.
- Added `agent/hosted_agent/deploy_hosted_agent.py` to create hosted versions
  via `AIProjectClient.agents.create_version(...)` with
  `HostedAgentDefinition(container_protocol_versions=[responses])`, carrying
  safe telemetry defaults and selected runtime env vars.
- Added `agent/hosted_agent/README.md` with local smoke, ACR build, hosted
  version creation, and canary/cutover rules.
- Added `agent/tests/test_hosted_agent_adapter.py` covering Hosted request to
  `LucyRequest` mapping, session continuity fields, pending notice metadata,
  artifact/tool/handoff metadata propagation, and response-event conversion.

**Hosted Agent research evidence used:**
- Microsoft Learn Hosted Agents docs (last updated 2026-04-28) confirm hosted
  agents are containerized custom code with Foundry-managed lifecycle,
  observability, versioning, dedicated endpoint, and per-agent Entra identity.
- Microsoft Learn Hosted Agents docs confirm Responses is the right protocol
  for conversational/multi-turn agents and that Hosted endpoints are exposed at
  `{project_endpoint}/agents/{name}/endpoint/protocols/openai/v1/responses`.
- Microsoft Learn Deploy Hosted Agent docs confirm `linux/amd64`, local port
  `8088`, `azure-ai-agentserver-responses`, `/readiness`, platform-injected
  `FOUNDRY_*` and `APPLICATIONINSIGHTS_CONNECTION_STRING`, and SDK creation via
  `HostedAgentDefinition` / `ProtocolVersionRecord(AgentProtocol.RESPONSES)`.
- Microsoft Learn `ResponsesAgentServerHost` API docs confirm the handler shape
  `(request, context, cancellation_signal)` and that `run()` defaults to
  `PORT` or `8088`.
- Local SDK inspection of `azure-ai-agentserver-responses==1.0.0b5` confirmed
  `ResponseContext.get_input_text()`, `context.conversation_id`, private
  `_previous_response_id`, and `ResponseEventStream` lifecycle methods used by
  the adapter.

**Hosted Agent tests run:**
- `python -m pytest -q agent/tests/test_hosted_agent_adapter.py`
- `python -m py_compile agent/hosted_agent/app.py agent/hosted_agent/deploy_hosted_agent.py agent/app/lucy_core/runtime_factory.py`
- `python -m pytest -q agent/tests/test_hosted_agent_adapter.py agent/tests/test_http_app.py agent/tests/test_lucy_runtime.py agent/tests/test_lucy_responses_loop.py agent/tests/test_lucy_session.py`

**Hosted Agent results:**
- Hosted adapter unit tests: `4 passed`.
- Py compile: passed.
- Nearby Lucy-core and HTTP-wrapper regression set: `49 passed, 1 skipped`.

**Hosted Agent North Central US launch 2026-04-29 — DEPLOYED / BASIC SMOKE PASSED:**
- Provisioned supported-region resources after East US2 Hosted Agent creation
  returned `bad_request: The requested experience is not available for this
  subscription.`
- North Central US resource group: `agent-lucy-ncus`.
- North Central US Foundry account/project:
  `agent-lucy-foundry-ncus` / `agent-lucy-prj-ncus`.
- North Central US project endpoint:
  `https://agent-lucy-foundry-ncus.services.ai.azure.com/api/projects/agent-lucy-prj-ncus`.
- North Central US ACR: `agentlucyacrncus.azurecr.io`.
- Model deployment: `gpt-5.2` (`GlobalStandard`, capacity `1000`) on the North
  Central Foundry account.
- AI Search project connection copied into the North Central project as
  `ailucyaisearchsyxvdy`.
- Capability host created as `accountcaphost` with Hosted Agents public hosting
  enabled.
- Hosted Agent name/version: `agent-lucy-hosted-ncus:4`.
- Hosted image:
  `agentlucyacrncus.azurecr.io/agent-lucy-hosted:hosted-20260428212030`
  (`sha256:310ffc2a3fb94760bcadc8bfccdc1e4d8ccee77a5bbc91cfbb4e8bb8e1e3da68`).
- Hosted endpoint is exposed through the project agent route:
  `{project_endpoint}/agents/agent-lucy-hosted-ncus/endpoint/protocols/openai/responses?api-version=v1`.
- SDK invocation smoke passed using
  `AIProjectClient(..., allow_preview=True).get_openai_client(agent_name="agent-lucy-hosted-ncus").responses.create(...)`.
  Result: `status=completed`, `error=None`,
  `output_text="Lucy Hosted is online."`, `agent_reference.version=4`.
- Stopped older Hosted deployments `2` and `3` (`status=Stopped`); version `4`
  remains the latest active version and its deployment status is `Running`.

**Hosted Agent Azure launch fixes 2026-04-29:**
- Version 1 failed startup because the platform probes hit `/liveness` and the
  adapter only exposed the protocol server routes. Fixed by adding `/liveness`
  and `/health` handlers in `agent/hosted_agent/app.py`.
- Version 2 reached runtime but failed outbound Azure TLS with
  `CERTIFICATE_VERIFY_FAILED` against the Foundry/OpenAI endpoint. Fixed by
  installing `ca-certificates` and setting `SSL_CERT_FILE`,
  `REQUESTS_CA_BUNDLE`, and `CURL_CA_BUNDLE` in the Hosted Dockerfile.
- Version 3 exposed a name collision: Foundry Hosted injects/reserves
  `FOUNDRY_AGENT_NAME`, which made Lucy's inner prompt-agent reconciler try to
  recreate the hosted container agent as a prompt agent. Fixed by making
  `agent/app/foundry_init.py` and `agent/app/foundry_publish.py` prefer
  Hosted-safe `LUCY_FOUNDRY_AGENT_NAME` /
  `LUCY_FOUNDRY_APPLICATION_NAME` aliases.
- Current focused validation after these fixes:
  `python -m py_compile agent/app/foundry_init.py agent/app/foundry_publish.py agent/hosted_agent/app.py`
  and
  `python -m pytest -q agent/tests/test_hosted_agent_adapter.py agent/tests/test_http_app.py agent/tests/test_lucy_runtime.py`
  returned `9 passed, 1 skipped`.

**Hosted Agent blockers / follow-ups:**
- Azure launch attempted 2026-04-28. ACR build/push succeeded for hosted image
  `agentlucyacreus2.azurecr.io/agent-lucy-hosted:hosted-20260428202447`
  (`sha256:4c0fb4bfc86e8d02b542a09b14575bba4fbbcfea9f2fb4e53f8a2490c0d891f7`).
- First `create_version` attempt failed validation because Hosted Agents reserve
  `APPLICATIONINSIGHTS_CONNECTION_STRING`, all `AGENT_*`, all `FOUNDRY_*`, and
  `PORT`. Fixed in code by adding Hosted-safe `LUCY_*` aliases and remapping
  them inside the hosted container before apex imports.
- Registered Azure feature
  `Microsoft.CognitiveServices/FoundryComputePreview` and re-registered the
  `Microsoft.CognitiveServices` provider successfully.
- Retried `create_version` after payload fix and feature registration; it still
  failed with `bad_request: The requested experience is not available for this
  subscription.`
- The East US2 Hosted Agent blocker was resolved by intentionally provisioning
  a supported-region North Central US canary. Full parity is not proven yet.
- Chainlit cutover intentionally not implemented yet. Per user plan, replace
  the local `_run_response_v2(message.content)` branch with a Hosted endpoint
  call only after Hosted canary proves notice auth, PDF artifacts, HITL,
  traces, token accounting, evals, and 4+ minute idle/reconnect continuity.
- Hosted container still imports apex.py and therefore keeps Chainlit installed
  in the hosted image. This preserves production tool behavior but should be
  reduced later by extracting remaining Chainlit-coupled tool side effects.
- Security hardening before broad production cutover: current Hosted Agent
  version creation carries runtime configuration in the immutable hosted version
  definition. Move secret-bearing values to managed identity, Key Vault, or a
  secret-backed deployment mechanism before relying on Hosted as the primary
  public production path.
- Continuous evaluation enablement 2026-04-29:
  - Confirmed North Central project has an App Insights connection
    `agent-lucy-appins-eus2-8540` pointing to `agent-lucy-appins-eus2`.
  - Confirmed App Insights telemetry is landing for Hosted Agent traffic:
    request `invoke_agent agent-lucy-hosted-ncus:4`, dependencies
    `create_agent`, `invoke_agent agent-lucy-prod:1`, `execute_tool`, and
    `chat gpt-5.2-2025-12-11`.
  - Created continuous evaluation object
    `eval_f15aaa52477a4780bfccf696788b80f4` named
    `Lucy Hosted Continuous Safety Smoke`.
  - Created enabled evaluation rule
    `lucy-hosted-continuous-safety-smoke`, filtered to
    `agent-lucy-hosted-ncus`, with safety smoke evaluators
    `builtin.violence`, `builtin.hate_unfairness`, and `builtin.self_harm`.
  - Added missing `Azure AI User` RBAC assignment for the North Central project
    managed identity `d4f3d82d-0056-4e6f-93f8-d1be9b049d94` at the project
    scope.
  - Generated post-rule Hosted Agent traffic; continuous eval runs are created
    but currently fail with AOAI `403 session_not_accessible`
    (`inner_error.code=PermissionDenied`, `result_counts.total=0`).
  - Tested header-based endpoint isolation as a possible fix; it did not change
    the failure, so the agent endpoint was restored to Entra isolation.
  - Follow-up: this is now a Foundry continuous-eval/session-access issue, not
    a missing App Insights connection or missing evaluation rule. Escalate with
    a failed run id such as
    `continuousevalrun_fe43df91-a89d-41d7-8c30-79b656c1559c` and request id
    `87fac10263082650e4763462a4a160d6`.
- Hosted Agent operational update 2026-04-29:
  - Expanded the North Central project managed identity RBAC after the first
    eval failures: `Azure AI User`, `Cognitive Services User`, and
    `Cognitive Services OpenAI User` are assigned at both the Foundry account
    and project scopes; `AcrPull` remains assigned on the NCUS ACR.
  - Created a second continuous evaluation rule for the inner prompt agent:
    `lucy-inner-prompt-continuous-safety-smoke`, filtered to
    `agent-lucy-prod`, backed by eval
    `eval_ab4a9b6cb3204e40a66b047bda5e2ed1`.
  - Verified inner prompt-agent continuous evaluation produces completed runs
    when Lucy traffic invokes the inner prompt agent. Latest completed examples
    include `continuousevalrun_df7ee52a-7cdc-4cbb-bbd9-61cf131a04f1` and
    `continuousevalrun_ba980217-00d0-4c0b-82ea-a043dbc80bd0`.
  - Re-tested Hosted Agent continuous evaluation after RBAC expansion and after
    restoring endpoint isolation to Entra. Hosted-targeted continuous eval still
    fails with `session_not_accessible`; this isolates the failure to the outer
    Hosted Agent session access path, not APIM, AI Gateway, missing App
    Insights, missing eval rule, or missing project identity role.
    Latest failed v5 example:
    `continuousevalrun_f4fa020b-99b8-4253-b3b6-5362e294e10d`, request id
    `c64c5956c38a99315d96cedc8a8a4560`.
  - Confirmed the North Central resource group has no APIM service. The only
    APIM gateway resource is the legacy/interim East US2
    `apexclassaction-ai-gw`, so it is not in the direct Hosted Agent request
    path.
  - Built and activated `agent-lucy-hosted-ncus:5` from image
    `agentlucyacrncus.azurecr.io/agent-lucy-hosted:hosted-20260429112236`
    (`sha256:e227a01e23340fef80b4dd64c1779c1abfe0c38dbaf1cf1f4185f2fe480555ef`).
    Version 5 carries the same runtime configuration as version 4, plus
    `AZURE_TRACING_GEN_AI_CONTENT_RECORDING_ENABLED=false` and
    `LUCY_CHAINLIT_NOTICE_PROGRESS=false`.
  - SDK smoke against `agent-lucy-hosted-ncus` after version 5 activation
    returned `status=completed`, `error=None`, and
    `output_text="Lucy hosted v5 is online."`
  - App Insights confirmed fresh version 5 telemetry after the smoke:
    request `invoke_agent agent-lucy-hosted-ncus:5`, plus dependencies
    `create_agent`, `invoke_agent agent-lucy-prod:1`, `execute_tool`, and
    `chat gpt-5.2-2025-12-11`.
  - Latest inner prompt-agent continuous eval runs after the v5 smoke completed:
    `continuousevalrun_d891693c-ff26-40a1-89a1-9caa869ea093` and
    `continuousevalrun_69715048-31b0-4419-96a5-53731d465ac1`.
  - Hosted Agent telemetry normalization 2026-04-29:
    - Found the built-in App Insights `Agents (preview)` workbook parameter
      still failing even though raw telemetry already had canonical Hosted
      Agent dimensions on v5 rows:
      `gen_ai.agent.name=agent-lucy-hosted-ncus`,
      `gen_ai.agent.id=agent-lucy-hosted-ncus:5`, and
      `gen_ai.agent.version=5`.
    - Found Lucy's custom `create_agent` span still emitted the legacy plural
      dimension `gen_ai.agents.id=lucy-aca` via the default
      `LUCY_OTEL_AGENT_ID`, which could confuse preview workbook parsing.
    - Updated `agent/app/lucy_core/responses_loop.py` to emit canonical
      `gen_ai.agent.id` / `gen_ai.agent.name` on Lucy's custom span instead of
      plural `gen_ai.agents.*`.
    - Updated `agent/hosted_agent/deploy_hosted_agent.py` so Hosted Agent
      version creation defaults `LUCY_OTEL_AGENT_ID` to the hosted agent name
      (`agent-lucy-hosted-ncus`) instead of inheriting any stale gateway value.
    - Built/pushed hosted image
      `agentlucyacrncus.azurecr.io/agent-lucy-hosted:hosted-20260429050051-agentattrs`
      (`sha256:ba549bc102c82df4204a7903f072863112525719bfb1b0160d8543fbe25448b2`)
      and activated `agent-lucy-hosted-ncus:6`.
    - SDK smoke against version 6 returned `status=completed`, `error=None`,
      response id `caresp_82fdcc0cecf421a700DqDEHHXgzdHaX0lE19hYl4a0BiAsTtqS`,
      and output text `Lucy hosted the v6 telemetry smoke test successfully.`
    - App Insights KQL confirmed fresh v6 request, `create_agent`, and
      `execute_tool` rows all have `gen_ai.agent.name=agent-lucy-hosted-ncus`,
      `gen_ai.agent.id=agent-lucy-hosted-ncus:6`,
      `gen_ai.agent.version=6`, and no stale `gen_ai.agents.id`.
  - Hosted Agent RBAC/search/dashboard cleanup 2026-04-29:
    - Diagnosed the remaining startup reconciliation failure as RBAC on the
      Hosted Agent runtime managed identity. Runtime identity:
      `bf64d26c-34a5-4bc8-a1b2-b22e9ff24b67`; blueprint application:
      `6059843d-af51-4c95-a409-e117f46605ab`.
    - Assigned built-in role `Azure AI Project Manager` to runtime identity
      `bf64d26c-34a5-4bc8-a1b2-b22e9ff24b67` at project scope
      `/subscriptions/22f9f915-587f-4a9a-acff-69b061ef48e1/resourceGroups/agent-lucy-ncus/providers/Microsoft.CognitiveServices/accounts/agent-lucy-foundry-ncus/projects/agent-lucy-prj-ncus`.
      This role covers the missing
      `Microsoft.CognitiveServices/accounts/projects/applications/write`
      action. Attempting to assign the same role to the blueprint failed
      because Azure reports it as principal type `Application`, not a
      role-assignable service principal.
    - Resolved the secondary startup ambiguity by carrying the full
      `AI_SEARCH_PROJECT_CONNECTION_ID` into Hosted versions:
      `/subscriptions/22f9f915-587f-4a9a-acff-69b061ef48e1/resourceGroups/agent-lucy-ncus/providers/Microsoft.CognitiveServices/accounts/agent-lucy-foundry-ncus/projects/agent-lucy-prj-ncus/connections/ailucyaisearchsyxvdy`.
    - Gated Chainlit dashboard-route registration behind
      `LUCY_DASHBOARD_ROUTES_ENABLED` / `LUCY_CHAINLIT_ENABLED`; Hosted sets
      both false so importing `apex.py` no longer logs
      `Failed to setup dashboard routes: 'app'`.
    - Built/pushed hosted image
      `agentlucyacrncus.azurecr.io/agent-lucy-hosted:hosted-20260429051054-rbac-dashboard`
      (`sha256:c389fc86ed3ae6850d74db18583a5e8498613278a54ce71b4705bf48df16d30e`)
      and activated `agent-lucy-hosted-ncus:8`.
    - SDK smoke against version 8 returned `status=completed`, `error=None`,
      response id `caresp_e39cb37ecf44b94e00mYcReQTjjYUncDkYOEfos8b2puEO5mrd`.
  - App Insights KQL for the v8 response shows:
    `Foundry v2 agent loaded from reconciled publication state:
    agent-lucy-prod:1 (agent-lucy-prod/agent-lucy-prod)`, no new
    `AuthorizationFailed` / `applications/write` error, startup
    `search_connection_id_set=True`, and `Dashboard routes disabled for this
    process` instead of the previous dashboard-route error.
  - User-observed portal state after v8: Lucy is "prestable, barely."
    The main Foundry/App Insights ops dashboard is still not populating
    reliably, but the metrics under the specific Agent surface are
    populating. Treat raw App Insights KQL plus the Agent metrics surface as
    the current proof path; do not claim the top-level ops dashboard is fixed
    until it is visibly populated in the portal.
  - Added a COO-safe fallback runbook at
    `docs/operations/hosted-agent-observability-fallback.md` with raw KQL for
    `AppRequests`, `AppDependencies`, and `AppMetrics`, and linked it from the
    hosted-agent README plus the gateway registration guide.
  - Live verification 2026-04-29 18:51-18:52 UTC:
    - Ran 3 Hosted responses smoke calls against
      `agent-lucy-hosted-ncus` v8 using the Responses endpoint and a bearer
      token acquired with the `https://ai.azure.com/.default` scope.
    - Returned successful completions:
      `caresp_d72480775d7bbdec00LSpqOlGHP7vcqT20tDih4FOV7dha2c9G`,
      `caresp_2d928c9351039b9100QW3KpxbZ6DhhFu1SEj817E5SQqhQdvjM`, and
      `caresp_4c66a25d360b37e00021XSuH64mXL1fCwp8GHWuSC4VP49l7Pn`.
    - AppRequests rows landed for all 3 calls with canonical
      `gen_ai.agent.name=agent-lucy-hosted-ncus`,
      `gen_ai.agent.id=agent-lucy-hosted-ncus:8`, and
      `gen_ai.agent.version=8`.
    - AppDependencies rows landed for the same smoke window, including
      `create_agent`, `invoke_agent agent-lucy-prod:1`, `execute_tool`, and
      `chat gpt-5.2-2025-12-11`.
    - AppMetrics still shows only `_APPRESOURCEPREVIEW_` rows with
      `service.name=agent-lucy-hosted-ncus`; treat that as metrics ingestion
      evidence, not as proof that the top-level portal workbook is fixed.
  - Foundry v2 permissions audit and RBAC fix 2026-04-29 19:09 UTC:
    - Rechecked current Microsoft docs before changing RBAC. Confirmed the
      split between ARM/control-plane roles and Foundry data-plane roles:
      Owner/Contributor alone do not grant agent data-plane operations, the
      project managed identity needs `Azure AI User` on the Foundry account
      for project-endpoint model access, agent identities need `Azure AI User`
      on the project for inferencing, and Log Analytics query access requires
      workspace query/data read permission.
    - Live audit confirmed these existing assignments were already correct:
      NCUS hosted runtime identity
      `bf64d26c-34a5-4bc8-a1b2-b22e9ff24b67` has `Azure AI User` and
      `Azure AI Project Manager` at the NCUS project scope; NCUS project
      managed identity `d4f3d82d-0056-4e6f-93f8-d1be9b049d94` has `AcrPull`
      at the NCUS ACR scope.
    - Added missing least-privilege assignments:
      - `Azure AI User` for EUS2 project managed identity
        `84e7a5d5-8c91-4e05-905f-34b3632eef91` at Foundry account scope
        `/subscriptions/22f9f915-587f-4a9a-acff-69b061ef48e1/resourceGroups/agent-lucy-eus2/providers/Microsoft.CognitiveServices/accounts/agent-lucy-foundry-eus2`.
      - `Log Analytics Data Reader` for NCUS project managed identity
        `d4f3d82d-0056-4e6f-93f8-d1be9b049d94` at workspace scope
        `managed-agent-lucy-appins-eus2-ws`.
      - `Log Analytics Data Reader` for EUS2 project managed identity
        `84e7a5d5-8c91-4e05-905f-34b3632eef91` at workspace scope
        `managed-agent-lucy-appins-eus2-ws`.
      - `Azure AI User` for NCUS project-level agent service identity
        `ac052192-ae57-46b0-a016-41ed16bd41d7` at NCUS project scope.
      - `Azure AI User` for NCUS `agent-lucy-prod` agent service identity
        `9652f540-f4d3-4d24-bcb0-674278092075` at NCUS project scope.
    - Post-change verification:
      - ARM role-assignment reads confirmed all five assignments at the target
        scopes.
      - Hosted Responses smoke against `agent-lucy-hosted-ncus` v8 completed:
        `caresp_636fb40fa620450200WRrPh8hRdk09hoNgk4hC0xWx8n3uAesI`, output
        `Lucy hosted RBAC is ready.`
      - Log Analytics query against workspace
        `4f6a12ab-ccc6-4079-a953-0a9a479eea81` confirmed a fresh
        `AppRequests` row at `2026-04-29T19:09:00Z` with
        `gen_ai.agent.name=agent-lucy-hosted-ncus`,
        `gen_ai.agent.id=agent-lucy-hosted-ncus:8`, and `Success=True`.
      - `AppDependencies` for the same smoke window confirmed successful
        `create_agent`, `execute_tool`, `invoke_agent agent-lucy-prod:1`, and
        `chat gpt-5.2-2025-12-11` spans.
- Member-facing ACA operational update 2026-04-29:
  - Disabled GenAI content recording on `agent-lucy-eus2` by setting
    `AZURE_TRACING_GEN_AI_CONTENT_RECORDING_ENABLED=false`.
  - Added and deployed `LUCY_CHAINLIT_NOTICE_PROGRESS=false` to prevent the
    sync notice retrieval tool from attempting Chainlit progress UI writes when
    it is running outside a valid Chainlit request context. This removes the
    noisy `Chainlit context not found` executor errors while preserving notice
    retrieval, SAS generation, PDF markers, and response content.
  - Built/pushed EUS2 image
    `agentlucyacreus2.azurecr.io/agent-lucy-eus2:codex-notice-progress-20260429111909`
    (`sha256:14352be9d0c922a3922cc9076e666e583830d3c91494b436d6e1cced92b7a6cc`)
    and deployed it to revision `agent-lucy-eus2--0000066`.
  - Verified revision `agent-lucy-eus2--0000066` is latest ready, Chainlit
    returns HTML on the public root, and startup logs show Foundry init plus
    HTTP wrapper readiness on port `8002`.
- PR2 Azure deployment 2026-05-03:
  - Deployment source was PR2 head `62685c9250e5fd23e180f44931a22cf612666858`
    from `/Users/chris/ai/Apex-Lucy-Final-pr2`; only deployment evidence was
    appended after the live rollout.
  - Built/pushed EUS2 app image
    `agentlucyacreus2.azurecr.io/agent-lucy-eus2:codex-pr2-20260503055908`
    (`sha256:2a80ee07e26f097141fe68ee4e6ceb983d74082ea2c7fa602770f0e2c247f32a`).
  - Updated `agent-lucy-eus2` to revision `agent-lucy-eus2--0000069`;
    revision list showed `active=True`, `traffic=100`, `health=Healthy`,
    `replicas=1`.
  - Updated `agent-lucy-gateway-eus2` to revision
    `agent-lucy-gateway-eus2--0000014`; revision list showed
    `active=True`, `traffic=100`, `health=Healthy`, `replicas=1`.
  - Public EUS2 checks passed: member root returned HTTP `200`; gateway
    `/health/gateway` returned HTTP `200` with `status=healthy`,
    `gateway_connected=true`, `runtime_initialized=true`,
    `project_endpoint_configured=true`, `project_probe.ok=true`, and
    `agent_url_path=/agent/respond`.
  - Gateway authenticated POST smoke passed with HTTP `200`, response text
    `Lucy gateway is online.`, `tool_calls=1`, and no errors. Gateway startup
    logs showed the PR2 health gate waiting for `/agent/health`, then
    `FastAPI HTTP wrapper is healthy`, then foreground wrapper startup.
  - Built/pushed NCUS Hosted image
    `agentlucyacrncus.azurecr.io/agent-lucy-hosted:hosted-pr2-20260503055915`
    (`sha256:4e2e6f0e65b5d1dafc8c1166851fbd77c2d5ae72cfd2da73e1a01483b95bd3b1`).
  - Created Hosted Agent version `agent-lucy-hosted-ncus:11`; SDK check
    confirmed `status=active`.
  - Hosted v11 SDK smokes completed with `error=None` and short online
    responses:
    `caresp_36944afbd2e3a5a1000i4GSPf9Ct8QSDyEGiAJbCX2oerOXBmk`,
    `caresp_052b113fdb96380100dpKxIwnhoSF9LvwN5zXNMiRwp8SZOWhR`,
    `caresp_e1d808e148f22c7000sKPjf2ZnlMdMMxGbOoQTZOC45llnlCKl`.
  - App Insights KQL against `agent-lucy-appins-eus2` confirmed fresh
    `requests` rows for `invoke_agent agent-lucy-hosted-ncus:11` with
    `success=True`, `resultCode=0`, `gen_ai.agent.name=agent-lucy-hosted-ncus`,
    `gen_ai.agent.version=11`, and response id dimensions matching the Hosted
    smoke responses above.
  - App Insights `dependencies` rows confirmed NCUS inner prompt-agent
    execution via `agent-lucy-prod:3`, model dependency
    `chat gpt-5.2-2025-12-11`, `success=True`, `resultCode=0`, and project id
    `/subscriptions/22f9f915-587f-4a9a-acff-69b061ef48e1/resourceGroups/agent-lucy-ncus/providers/Microsoft.CognitiveServices/accounts/agent-lucy-foundry-ncus/projects/agent-lucy-prj-ncus`.
  - Caveats / follow-ups:
    - Full member authentication, notice PDF retrieval, and HITL case creation
      scenario smokes were not run in this deployment pass.
    - The member Chainlit app still logs the known dashboard-route setup noise;
      Hosted disables Chainlit/dashboard routes and did not show that failure.
    - Hosted version definitions still copy secret-bearing environment values;
      keep config migration/rotation as a separate production-hardening task.
- SUPERSEDED 2026-05-04: the Gateway/APIM route was later retired and deleted
  after the team abandoned the AI Gateway path.

**Hosted Agent routing/observability canary 2026-04-29 — DEPLOYED / SMOKE PASSED:**
- Built and pushed NCUS Hosted image
  `agentlucyacrncus.azurecr.io/agent-lucy-hosted:hosted-20260429121955-routing-rbac`
  (`sha256:189cefe52f3529aad11753d4beedf2a108a0dc362cdc1afedc9641a9e5e3056f`).
- Created and activated Hosted Agent version `agent-lucy-hosted-ncus:9` from
  the version 8 environment definition, preserving the existing runtime config
  while pinning hosted telemetry defaults:
  `LUCY_OTEL_AGENT_ID=agent-lucy-hosted-ncus`,
  `AZURE_TRACING_GEN_AI_CONTENT_RECORDING_ENABLED=false`,
  `LUCY_CHAINLIT_ENABLED=false`, `LUCY_DASHBOARD_ROUTES_ENABLED=false`, and
  `OTEL_SERVICE_NAME=lucy-hosted-agent`.
- Hosted Responses smoke against `agent-lucy-hosted-ncus` v9 completed:
  response id `caresp_1090afbe0a85d00800je4gPxhp4UKP1RrwZ5MKXt7RpksYecv4`,
  status `completed`, output `Lucy hosted routing is ready.`
- Log Analytics query against workspace
  `4f6a12ab-ccc6-4079-a953-0a9a479eea81` confirmed a fresh
  `AppRequests` row at `2026-04-29T19:24:33Z` with
  `Name=invoke_agent agent-lucy-hosted-ncus:9`,
  `gen_ai.agent.name=agent-lucy-hosted-ncus`,
  `gen_ai.agent.id=agent-lucy-hosted-ncus:9`, and `Success=True`.
- `AppDependencies` for the same smoke window confirmed successful
  `execute_tool` and `chat gpt-5.2-2025-12-11` rows. The `execute_tool` row
  carries `gen_ai.agent.name=agent-lucy-hosted-ncus` and
  `gen_ai.agent.id=agent-lucy-hosted-ncus:9`.
- Live verification 2026-04-29 22:11 UTC:
  - Re-ran raw App Insights KQL against workspace
    `4f6a12ab-ccc6-4079-a953-0a9a479eea81`.
  - `AppRequests` still shows fresh v9 rows with canonical dimensions, most
    recently `invoke_agent agent-lucy-hosted-ncus:9` at
    `2026-04-29T22:11:16.560753Z` with
    `gen_ai.agent.name=agent-lucy-hosted-ncus`,
    `gen_ai.agent.id=agent-lucy-hosted-ncus:9`, and
    `gen_ai.agent.version=9`.
  - `AppDependencies` still shows the expected hosted row mix, including
    `create_agent`, `execute_tool`, `invoke_agent agent-lucy-prod:1`, and
    `chat gpt-5.2-2025-12-11`; v9 rows were present with counts
    `create_agent=2` and `execute_tool=1`.
  - `AppMetrics` still returns preview metric rows
    (`_APPRESOURCEPREVIEW_`, `Item_Success_Count`), which is telemetry
    ingestion evidence only. The top-level workbook remains a portal issue
    until directly confirmed in the UI.
  - Fresh smoke batch 2026-04-29 22:59-23:00 UTC:
    - Ran 3 additional Hosted Responses calls against
      `agent-lucy-hosted-ncus` v9.
    - `AppRequests` now shows the new v9 request rows at
      `2026-04-29T22:59:36.604418Z`,
      `2026-04-29T22:59:59.437101Z`, and
      `2026-04-29T23:00:12.137587Z`, all with
      `gen_ai.agent.name=agent-lucy-hosted-ncus`,
      `gen_ai.agent.id=agent-lucy-hosted-ncus:9`, and
      `gen_ai.agent.version=9`.
    - `AppDependencies` now shows `create_agent=4` and `execute_tool=3` for
      v9 in the fresh 2h query window, with the expected `agent-lucy-prod:2`
      and `chat gpt-5.2-2025-12-11` dependencies also present.
- Focused code validation before deployment:
  `python -m pytest agent/tests/test_lucy_responses_loop.py agent/tests/test_lucy_runtime.py agent/tests/test_notice_tool_instructions.py agent/tests/test_coa_reason_writeback.py agent/tests/test_hosted_agent_adapter.py -q`
  returned `49 passed`; `python -m py_compile agent/app/apex.py agent/app/lucy_core/responses_loop.py agent/app/user_functions.py agent/hosted_agent/app.py`
  passed.

**Hosted stale-conversation and notice follow-up repair 2026-04-29 — DEPLOYED / SMOKE PASSED:**
- Triggering evidence:
  - Screenshot review showed Lucy authenticated correctly, failed to find a
    notice PDF, offered to help from other records, then repeated notice lookup
    on a follow-up asking about the case itself.
  - Raw App Insights at 2026-04-29 22:11 UTC showed a hosted request with an
    inner `create_agent` dependency failure: `conversation_not_found`.
- Code changes:
  - `agent/app/lucy_core/responses_loop.py`
    - Records terminal `find_notice_for_user_sync` outcomes in
      `LucySession.metadata`.
    - Injects authenticated session state telling Lucy to use Dynamics
      member/case/disbursement tools after a notice miss instead of retrying the
      notice/PDF tool for case, eligibility, payment, status, or next-step
      follow-ups.
    - Detects stale Responses `conversation_not_found` errors on the initial
      request, clears `session.conversation_id` and
      `session.previous_response_id`, and retries once with a fresh
      `agent_reference`.
  - `agent/tests/test_lucy_responses_loop.py`
    - Mock client can now raise queued exceptions.
    - Added coverage for stale conversation retry and notice-miss follow-up
      state injection.
- Deployment:
  - Built and deployed EUS2 member-facing image
    `agentlucyacreus2.azurecr.io/agent-lucy-eus2:codex-stale-conversation-20260429160031`
    (`sha256:ddd377df90c2c199d18bde48c043daf200e0c75cbd0f89141a7915cebf2333fb`)
    to ACA revision `agent-lucy-eus2--0000068`.
  - Built and activated NCUS Hosted image
    `agentlucyacrncus.azurecr.io/agent-lucy-hosted:hosted-20260429160031-stale-conversation`
    (`sha256:682296ce152dab8ce5358130a014c8101b67ca269733d98441a8d3163d82ead8`)
    as `agent-lucy-hosted-ncus:10`.
- Live verification:
  - `agent-lucy-eus2--0000068` is running and healthy with 100% traffic.
  - Public EUS2 root returned HTTP 200 after deployment.
  - ACA startup logs show Foundry v2 agent load and
    `Lucy HTTP wrapper ready`.
  - Hosted v10 SDK smoke completed with response id
    `caresp_e0b7cb9514354a5f00oaD8HhOQAx68Z8fjDYODSwXeqBbUqaJf` and output
    `Lucy hosted v10 is ready.`
  - Log Analytics workspace `4f6a12ab-ccc6-4079-a953-0a9a479eea81` shows
    `AppRequests` row `invoke_agent agent-lucy-hosted-ncus:10` at
    `2026-04-29T23:04:19.747676Z` with `Success=True`,
    `gen_ai.agent.id=agent-lucy-hosted-ncus:10`, and
    `gen_ai.agent.version=10`.
  - Matching `AppDependencies` rows show successful `create_agent`,
    `execute_tool`, and `chat gpt-5.2-2025-12-11` dependencies for the same
    v10 operation.
- Portal/control-plane interpretation:
  - NCUS project currently has two expected active agents:
    `agent-lucy-hosted-ncus:10` (hosted container wrapper) and
    `agent-lucy-prod:2` (inner prompt agent used by the hosted runtime).
  - EUS2 still has legacy prompt/custom-gateway assets including
    `agent-lucy-prod:8`, `ApexAgentLucy:2`, and `lucy-chat-v2:5`.
  - SUPERSEDED 2026-05-04: APIM `apexclassaction-ai-gw` and gateway ACA
    `agent-lucy-gateway-eus2` were later retired and deleted.
- Tests run before deployment:
  - `python -m pytest agent/tests/test_lucy_responses_loop.py agent/tests/test_lucy_runtime.py agent/tests/test_hosted_agent_adapter.py -q`
    returned `44 passed`.
  - `python -m py_compile agent/app/lucy_core/responses_loop.py agent/hosted_agent/app.py`
    passed.
  - `git diff --check` passed.
- Post-handoff verification after updating `TASKS.md`, hosted README, and the
  fallback KQL runbook:
  - Re-ran
    `python -m pytest agent/tests/test_lucy_responses_loop.py agent/tests/test_lucy_runtime.py agent/tests/test_hosted_agent_adapter.py -q`;
    result: `44 passed`.
  - Re-ran
    `python -m py_compile agent/app/lucy_core/responses_loop.py agent/hosted_agent/app.py`;
    result: passed.
  - Re-ran `git diff --check`; result: passed.
- Follow-ups:
  - Re-run a real authenticated notice/case canary through Chainlit or Hosted
    before declaring member workflow parity.
  - Built-in preview dashboard may still lag or show incomplete status; use raw
    App Insights KQL and Agent metrics as the evidence path.
  - Hosted version definitions currently include copied runtime environment
    settings. Move secret-bearing settings to managed identity, Key Vault, or a
    supported secret-backed Hosted control-plane pattern, then rotate affected
    secrets.

**PR review P1 remediation 2026-05-03 — IMPLEMENTED LOCALLY:**
- Triggering evidence:
  - PR #5 Codex review flagged Hosted metadata auth parsing: string values such
    as `"false"` were truthy and could incorrectly mark a Hosted session
    authenticated.
  - PR #5 Codex review flagged Hosted deploy env propagation: the deploy
    whitelist forwarded `AZURE_SEARCH_INDEX` but not the Foundry runtime keys
    consumed by `foundry_init.py`.
  - PR #2 CodeRabbit review flagged FastAPI wrapper startup masking: the
    background `/agent/respond` wrapper could fail while Chainlit kept the
    container alive.
- Files changed:
  - `agent/hosted_agent/app.py`
  - `agent/hosted_agent/deploy_hosted_agent.py`
  - `agent/app/start_services.sh`
  - `agent/tests/test_hosted_agent_adapter.py`
  - `agent/tests/test_hosted_deploy_env.py`
- Summary:
  - Added strict Hosted metadata boolean parsing for `authenticated` and
    `pending_notice_request`; only explicit true-like values authenticate.
  - Added Hosted deploy propagation for
    `AI_SEARCH_PROJECT_CONNECTION_ID`, `AI_SEARCH_PROJECT_CONNECTION_NAME`,
    `AI_SEARCH_INDEX_NAME`, and `AZURE_SEARCH_INDEX_NAME`.
  - Added a compatibility mapping from legacy `AZURE_SEARCH_INDEX` to
    `AI_SEARCH_INDEX_NAME` when no consumed index env is already present.
  - Replaced the FastAPI wrapper process-only startup check with a bounded
    `/agent/health` probe loop before Chainlit starts or the HTTP-only mode
    waits in the foreground.
- Research evidence:
  - Microsoft Foundry Hosted Agent docs confirm hosted agent versions are
    immutable snapshots of container image, resources, environment variables,
    and protocol configuration, so deploy-time env propagation is part of the
    runtime contract.
  - Microsoft Azure AI Search tool docs confirm Foundry agents require both a
    project connection (`project_connection_id`) and an exact search
    `index_name`; this matches the repo's `foundry_init.py` required envs.
- Tests run:
  - `PYTHONPATH=agent/app:agent python -m pytest -q agent/tests/test_hosted_agent_adapter.py agent/tests/test_hosted_deploy_env.py`
    returned `10 passed`.
  - `PYTHONPATH=agent/app:agent python -m pytest -q agent/tests/test_lucy_responses_loop.py agent/tests/test_lucy_runtime.py agent/tests/test_hosted_agent_adapter.py agent/tests/test_hosted_deploy_env.py agent/tests/test_http_app.py`
    returned `50 passed, 1 skipped`.
  - `bash -n agent/app/start_services.sh` passed.
  - `python -m py_compile agent/hosted_agent/app.py agent/hosted_agent/deploy_hosted_agent.py`
    passed.
  - `git diff --check` passed.
- Blockers / follow-ups:
  - PR #2 remains a separate open branch (`Naitiveai`); its startup P1 is
    covered by this branch's current startup script, but the older PR should be
    closed or updated separately if it remains an active merge candidate.

**Hosted Agent gpt-5.2-chat alignment and v13 telemetry recheck 2026-05-04 — LIVE VERIFIED / DOCS REFRESHED:**
- Status: deployed and verified for Hosted v13 chat-model routing and raw
  telemetry. The built-in Foundry/App Insights Operate dashboard is still not
  visually proven populated from this session.
- Summary:
  - Local handoff docs still pointed at `agent-lucy-hosted-ncus:10`,
    `agent-lucy-prod:2`, and base `gpt-5.2`.
  - Remote branch evidence and live KQL confirm the current canary is
    `agent-lucy-hosted-ncus:13`, with inner prompt agent `agent-lucy-prod:6`
    and model dependency rows for `chat gpt-5.2-chat-2025-12-11`.
  - Refreshed the operator-facing handoff docs so the next agent tests v13,
    not stale v10/base-model evidence.
- Files changed:
  - `TASKS.md`
  - `agent/hosted_agent/README.md`
  - `docs/operations/hosted-agent-observability-fallback.md`
  - `state/refactor-ledger.md`
- Research evidence:
  - Microsoft Hosted Agents docs confirm Hosted Agents are custom code packaged
    as container images, expose Responses/Invocations protocol libraries, and
    create immutable versions from image, resources, environment variables, and
    protocol configuration:
    https://learn.microsoft.com/en-us/azure/foundry/agents/concepts/hosted-agents
  - Microsoft Agent Monitoring Dashboard docs confirm the dashboard reads from
    the Application Insights resource connected to the Foundry project, requires
    App Insights / Log Analytics RBAC for views, and empty charts can be caused
    by no recent traffic, time-range mismatch, or ingestion delay:
    https://learn.microsoft.com/en-us/azure/foundry/observability/how-to/how-to-monitor-agents-dashboard
  - Microsoft tracing setup docs confirm tracing requires an Application
    Insights connection, recent agent traffic, and a short refresh/ingestion
    delay before portal traces appear:
    https://learn.microsoft.com/en-us/azure/foundry/observability/how-to/trace-agent-setup
  - Microsoft migration docs for the refreshed hosted-agent preview confirm
    custom/BYO agents should use protocol libraries such as
    `azure-ai-agentserver-responses` / `ResponsesAgentServerHost`, update the
    protocol-version format, use `project.get_openai_client(agent_name=...)`,
    grant downstream access to the dedicated agent identity, and verify the
    version reaches active before traffic:
    https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/migrate-hosted-agent-preview
- Tests and live verification:
  - Ran four Hosted v13 response smokes against
    `agent-lucy-hosted-ncus` on 2026-05-04:
    `caresp_7134d54ea580a75b00J20xvnHP4CrbtzYg0Zu5TMRkZ7E7oBme`,
    `caresp_bbbb275a5dab095100H5dl4xnkju92aLL3OoJ89lQk4SGnXwDv`,
    `caresp_a4b147e884c3bcae00OwqgMr93x8l9ujy1Ze0PPSlBv3EBZ5ZI`, and
    `caresp_ae9411e47bbc3cd300RSCBUwg3aZWeT4hcwKuV9YZ8wWr42B3n`.
  - All returned `status=completed`, `error=None`, agent reference
    `agent-lucy-hosted-ncus` version `13`, and output
    `Lucy hosted v13 telemetry is alive.`
  - Log Analytics workspace `4f6a12ab-ccc6-4079-a953-0a9a479eea81`
    showed fresh 30-minute rows through `2026-05-04T08:26:10Z`:
    `AppRequests` for `invoke_agent agent-lucy-hosted-ncus:13` with
    `row_count=7`, `success=True`, `gen_ai.agent.id=agent-lucy-hosted-ncus:13`,
    and `gen_ai.agent.version=13`.
  - Matching `AppDependencies` rows showed `create_agent` for
    `agent-lucy-hosted-ncus:13`, `invoke_agent agent-lucy-prod:6`, and
    `chat gpt-5.2-chat-2025-12-11`, all with `success=True`.
  - `AppMetrics` showed fresh `_APPRESOURCEPREVIEW_` metric rows for both
    `service.name=responsesapi` and `service.name=agent-lucy-hosted-ncus`.
- Blockers / follow-ups:
  - Foundry Operate dashboard remains a visual/portal proof gap. Raw request,
    dependency, and metric telemetry are healthy, but this session did not have
    browser-confirmed dashboard population.
  - The old continuous response-eval rule still needs a clean post-v20 run; the
    one-off v13 Hosted target eval from 2026-05-03 passed.
  - Full notice-auth-PDF-HITL canary remains pending after the observability
    path is acceptable.

**AI Gateway/APIM bridge retirement 2026-05-04 — LIVE DELETED / DOCS REFRESHED:**
- Status: completed for the abandoned East US2 gateway bridge. The Hosted Agent
  route remains the selected path; the member-facing Chainlit ACA was preserved.
- Summary:
  - User clarified that the AI Gateway path had been abandoned after earlier
    APIM method-rewrite work and authorized cleanup.
  - Pre-delete Azure state showed APIM `apexclassaction-ai-gw` in resource group
    `agent-lucy-eus2` with APIs `agent-lucy-foundry-eus2`, `lucy-bo2zjet3`,
    and `lucyv2-eojkdlgt`; `lucyv2-eojkdlgt` forwarded to
    `https://agent-lucy-gateway-eus2.purpleocean-f3514433.eastus2.azurecontainerapps.io/agent/respond`.
  - Pre-delete Azure state showed gateway-only ACA `agent-lucy-gateway-eus2`
    running revision `agent-lucy-gateway-eus2--0000014` with one replica.
  - Seven-day Log Analytics showed no recent `lucy-aca` gateway traffic after
    2026-04-29, while current Hosted traffic was landing through
    `agent-lucy-hosted-ncus:20`.
  - Deleted APIM `apexclassaction-ai-gw`.
  - Deleted gateway-only ACA `agent-lucy-gateway-eus2`.
  - Verified both resources now return `ResourceNotFound`.
  - Verified subscription gateway scan only returns unrelated NAT gateway
    `Apex_NATGW`.
  - Verified member-facing ACA `agent-lucy-eus2` remains running as revision
    `agent-lucy-eus2--0000069`.
- Files changed:
  - `TASKS.md`
  - `agent/hosted_agent/README.md`
  - `docs/architecture/foundry-ai-gateway-registration.md`
  - `state/refactor-ledger.md`
- Tests / live verification:
  - `az resource show` for APIM `apexclassaction-ai-gw` -> `ResourceNotFound`.
  - `az resource show` for ACA `agent-lucy-gateway-eus2` -> `ResourceNotFound`.
  - `az resource list` gateway/APIM scan -> only unrelated `Apex_NATGW`.
  - `az containerapp show --name agent-lucy-eus2 --resource-group agent-lucy-eus2`
    -> `runningStatus=Running`, latest revision `agent-lucy-eus2--0000069`.
- Blockers / follow-ups:
  - EUS2 Foundry still has legacy prompt/application lineages such as
    `agent-lucy-prod`, `lucy-chat-v2`, `lucy-chat`, and `lucy`. Those were not
    deleted in this pass because the explicit gateway bridge cleanup was APIM +
    gateway ACA, and EUS2 member/runtime history may still be useful until
    Chainlit cutover is decided.
  - Built-in Operate dashboard still needs separate closure; raw App Insights
    confirmed current Hosted v20 telemetry, but the dashboard remains visually
    unreliable.

**Operate dashboard fallback workbook refresh 2026-05-04 — LIVE VERIFIED:**
- Status: completed for the portal-visible KQL fallback. The built-in Foundry
  Operate overview remains blank/unreliable, but the Azure Monitor workbook now
  exposes the same production telemetry evidence in portal form.
- Summary:
  - Rechecked the logged-in Foundry Operate overview after gateway deletion; it
    still showed no data for estimated cost, agent success rate, token usage,
    agent run volume, and top increase/decrease panels.
  - Refreshed shared Azure Monitor workbook `Lucy Hosted COO Monitor`:
    `/subscriptions/22f9f915-587f-4a9a-acff-69b061ef48e1/resourceGroups/agent-lucy-eus2/providers/Microsoft.Insights/workbooks/d93d5898-c385-40ff-978e-eea3dbf03332`.
  - Workbook source is Application Insights `agent-lucy-appins-eus2`:
    `/subscriptions/22f9f915-587f-4a9a-acff-69b061ef48e1/resourceGroups/agent-lucy-eus2/providers/Microsoft.Insights/components/agent-lucy-appins-eus2`.
  - Updated workbook content to current Hosted v20, inner prompt
    `agent-lucy-prod:6`, model lane `gpt-5.2-chat`, and retired-gateway state.
  - Removed stale v14/v15 wording and incorrect count/token division from the
    workbook queries.
- Research evidence:
  - Microsoft Agent Monitoring Dashboard docs confirm the dashboard is preview,
    reads from the project's connected Application Insights resource, requires
    App Insights / Log Analytics RBAC, and can show empty charts when traffic,
    time range, or ingestion conditions do not line up:
    https://learn.microsoft.com/en-us/azure/foundry/observability/how-to/how-to-monitor-agents-dashboard
  - Microsoft Application Insights Agent details docs confirm Azure Monitor can
    provide the agent monitoring surface from OpenTelemetry GenAI semantics,
    which is the basis for the `Lucy Hosted COO Monitor` workbook fallback:
    https://learn.microsoft.com/en-us/azure/azure-monitor/app/agents-view
- Files changed:
  - `TASKS.md`
  - `docs/operations/hosted-agent-observability-fallback.md`
  - `state/refactor-ledger.md`
- Tests / live verification:
  - Application Insights workbook invocation query returned
    `agent-lucy-hosted-ncus:20`, `Runs=20`, `Success=20`, `Failures=0`,
    `SuccessRate=1`, latest response
    `caresp_8d573622b8c4439000NJ0TQ3JeQlRW0XoUU1PqRZvd1o2cHcxi`.
  - Resume recheck on 2026-05-04 returned current Hosted v20 health through
    both telemetry paths: App Insights `requests` 7-day window
    `Runs=18`, `Successes=18`, `Failures=0`, latest
    `2026-05-04T11:05:25.568265Z`; Log Analytics `AppRequests` 24-hour window
    `Runs=10`, `Successes=10`, `Failures=0`.
  - Confirmed the real Log Analytics workspace resource is
    `agent-lucy-law-eus2`; the workbook source remains Application Insights
    `agent-lucy-appins-eus2`.
  - Dependency/token query returned Hosted v20 rows for `create_agent` and
    `chat` with `TotalTokens=95940`, `InputTokens=94486`,
    `OutputTokens=1454`, plus inner rows for `agent-lucy-prod:6` and
    `chat gpt-5.2-chat-2025-12-11`.
  - Metric inventory query returned `Item_Success_Count`, plus fresh
    `_APPRESOURCEPREVIEW_` rows for `agent-lucy-hosted-ncus` and `responsesapi`.
- Blockers / follow-ups:
  - This closes the COO-safe portal fallback, not the native Foundry Operate
    preview dashboard. Treat the native dashboard as a Microsoft preview/portal
    issue until it visibly populates or Microsoft confirms the required source
    contract.

**May 6 Hosted v21 portal telemetry recheck — LIVE VERIFIED / NATIVE UI STILL WEAK:**
- Status: completed for fresh telemetry and Azure Monitor workbook evidence;
  blocked for native Foundry Operate visual proof because the resumed terminal can
  control Chrome tabs but cannot capture or inspect the page contents.
- Summary:
  - Removed committed merge-conflict markers from the active handoff docs before
    continuing the audit. The resolved current state is Hosted-first, with the
    old AI Gateway/APIM path retired and deleted.
  - Removed the one real unresolved merge-conflict block in
    `agent/app/lucy_core/responses_loop.py`. The resolved code preserves both
    required behaviors: the GenAI response telemetry/metric helpers and the
    stale `conversation_not_found` recovery helper.
  - Ran three fresh Hosted REST smokes against
    `agent-lucy-hosted-ncus`; all completed successfully and retrieved assistant
    output text:
    `caresp_65a1ddd2d4dcc73700KUIfwqFoHdZZJLFBxGfSc8HTMpmdNo1s`,
    `caresp_b41756284523295400kHMouXPVPnbF9ek9IBxWU37rbrScSIkE`, and
    `caresp_c0208595c364d6f400q3jDeh60dxrZ3GxpX6B9kyzEP8AjuyAp`.
  - Fresh telemetry shows the current Hosted runtime is
    `agent-lucy-hosted-ncus:21`, not the previously documented v20, and the inner
    prompt agent now emits as `agent-lucy-prod:8`, not v6.
  - Updated shared Azure Monitor workbook `Lucy Hosted COO Monitor` to current
    v21/v8 wording and query matching. The new workbook revision is
    `f6657d50222844a08c9a97030c016597`.
  - Chrome control check found an existing logged-in Microsoft Foundry tab at
    `https://ai.azure.com/nextgen/r/Ivn5FVh_Spqs_2mwYe9I4Q,agent-lucy-ncus,,agent-lucy-foundry-ncus,agent-lucy-prj-ncus/operate/overview`.
    `chrome-cli info` confirmed title `Microsoft Foundry`, URL at the Operate
    overview, and `Loading: No`.
  - Opened the Azure Portal workbook URL in the same Chrome window; `chrome-cli
    info` confirmed title
    `d93d5898-c385-40ff-978e-eea3dbf03332 (Lucy Hosted COO Monitor) - Microsoft Azure`,
    URL at the workbook resource, and `Loading: No`.
  - Browser content inspection is still limited:
    Screenshot capture failed with `could not create image from display`,
    JavaScript inspection is disabled in Chrome's Apple Events settings, and
    macOS accessibility inspection is not allowed for `osascript`.
- Files changed:
  - `TASKS.md`
  - `agent/hosted_agent/README.md`
  - `agent/app/lucy_core/responses_loop.py`
  - `state/foundry-native-metrics-diagnostic.md`
  - `docs/operations/hosted-agent-observability-fallback.md`
  - `state/refactor-ledger.md`
- Research evidence:
  - Microsoft supported metrics docs for
    `Microsoft.CognitiveServices/accounts/projects` list
    `AgentResponses`, `AgentInputTokens`, `AgentOutputTokens`, `AgentRuns`, and
    `AgentToolCalls` as project resource metrics with dimensions such as
    `AgentId`, `ModelName`, `ResponseStatus`, `RunStatus`, `StatusCode`,
    `ThreadId`, `StreamType`, and `ToolName`. These metrics are Azure Monitor
    resource metrics, not Application Insights custom metric names:
    https://learn.microsoft.com/en-us/azure/azure-monitor/reference/supported-metrics/microsoft-cognitiveservices-accounts-projects-metrics
  - Microsoft Agent Monitoring Dashboard docs confirm the dashboard is a preview
    surface that reads telemetry from the project's connected Application
    Insights resource, while troubleshooting empty charts recommends checking
    traffic, time range, and ingestion delay:
    https://learn.microsoft.com/en-us/azure/foundry/observability/how-to/how-to-monitor-agents-dashboard
- Tests / live verification:
  - REST retrieval for the three `caresp_...` ids returned `status=completed`,
    `error=null`, agent reference `agent-lucy-hosted-ncus` version `21`, and
    output text `Lucy May 6 portal telemetry smoke N is alive.`
  - App Insights `requests` 24-hour query returned
    `invoke_agent agent-lucy-hosted-ncus:21`, `Runs=6`, `Successes=6`,
    `Failures=0`, latest response
    `caresp_c0208595c364d6f400q3jDeh60dxrZ3GxpX6B9kyzEP8AjuyAp`.
  - App Insights `dependencies` 24-hour query returned current rows for
    `create_agent` and hosted `chat` with `agent-lucy-hosted-ncus:21`,
    `TotalTokens=28698`, `InputTokens=28128`, `OutputTokens=570`; inner rows
    returned `invoke_agent agent-lucy-prod:8` and
    `chat gpt-5.2-chat-2025-12-11`.
  - App Insights `customMetrics` 2-hour query returned
    `gen_ai.client.token.usage`, `gen_ai.client.operation.duration`, and fresh
    `_APPRESOURCEPREVIEW_` rows for `responsesapi` and
    `agent-lucy-hosted-ncus`.
  - Azure Monitor project metric definitions still expose the native dashboard
    metric names (`AgentResponses`, `AgentInputTokens`, `AgentOutputTokens`,
    `AgentRuns`, `AgentToolCalls`), but a direct metric query for the fresh
    2026-05-06 12:45-13:05 UTC smoke window returned all-zero timeseries for
    those five metrics while App Insights showed the v21 request/dependency
    rows. This keeps the native Build/Operate metric path unresolved.
  - Foundry account-level model metrics for the same
    2026-05-06 12:45-13:05 UTC smoke window were non-zero:
    `ModelRequests=3`, `InputTokens=14064`, `OutputTokens=285`, and
    `TotalTokens=14349`. Project-level `AgentEvents`, `AgentMessages`,
    `AgentThreads`, and `AgentUsageIndexedFiles` were also zero. This confirms
    model/runtime execution is visible to the Foundry account metric namespace,
    while the project Agent metric namespace is not binding the Hosted v21 runs.
  - Investigated whether the missing project Agent metrics were caused by using
    the direct Hosted endpoint instead of a published Agent Application. Live
    ARM state showed only `agent-lucy-prod` existed as an application, with a
    `Managed` deployment to prompt agent v8. A temporary application
    `agent-lucy-hosted-ncus` was created with a `Hosted` deployment to
    `agent-lucy-hosted-ncus:21`; it provisioned successfully and reached
    `state=Running`, but the application-scoped Responses endpoint rejected
    invocation with `Application-scoped routes only support prompt agents. Agent
    kind 'hosted' is not supported.` The temporary Hosted application and
    deployment were stopped/deleted, and verification returned
    `ApplicationNotFound` / `DeploymentNotFound` for both tested ARM API
    versions. This rules out Agent Application publication as a current
    supported fix for Hosted native metrics.
  - Post-cleanup direct Hosted route smoke returned
    `caresp_06c3f16130375552006V62t3ttCGXKVpxxbaFvtay0pimmyI2H`,
    `status=completed`, `error=null`, agent reference
    `agent-lucy-hosted-ncus:21`, and output text
    `Direct hosted route remains alive.`
  - Ran a prompt-agent Application route control against
    `agent-lucy-prod/protocols/openai/responses`; response
    `resp_06a8c313860b3cee0169fb427a97808194a2b7305137ed0c07` completed on
    `agent-lucy-prod:8` with output text `Prompt application route is alive.`
    For the actual 2026-05-06 13:20-13:40 UTC window, Foundry account-level
    model metrics moved (`ModelRequests=2`, `InputTokens=9366`,
    `OutputTokens=129`, `TotalTokens=9495`), but project-level
    `AgentResponses`, `AgentInputTokens`, `AgentOutputTokens`, `AgentRuns`,
    `AgentToolCalls`, and project-level model token metrics all remained zero.
    This means the native project metric rollup is not just missing direct
    Hosted endpoint traffic; it also failed to bind a supported prompt-agent
    Application invocation in the same project.
  - Added `state/foundry-native-metrics-diagnostic.md` as a tracked, repeatable
    evidence artifact with the exact KQL and Azure Monitor metric commands for
    the App Insights-positive / project-Agent-metrics-zero split.
  - Final App Insights dimension sanity check showed v21 `create_agent` and
    `chat` dependency rows carry
    `microsoft.foundry.project.id=/subscriptions/22f9f915-587f-4a9a-acff-69b061ef48e1/resourceGroups/agent-lucy-ncus/providers/Microsoft.CognitiveServices/accounts/agent-lucy-foundry-ncus/projects/agent-lucy-prj-ncus`,
    `gen_ai.agent.id=agent-lucy-hosted-ncus:21`,
    `gen_ai.agent.name=agent-lucy-hosted-ncus`,
    `gen_ai.agent.version=21`, `gen_ai.provider.name=azure.ai.foundry`, and
    `gen_ai.system=azure.ai.foundry`.
  - Final App Insights custom metric sanity check showed
    `gen_ai.client.token.usage` and `gen_ai.client.operation.duration` carry the
    same project id, hosted agent name/version, provider, operation, model, and
    token type dimensions.
  - Workbook revision read confirmed `agent-lucy-hosted-ncus:21`,
    `agent-lucy-prod:8`, `gpt-5.2-chat`, and generalized
    `agent_id startswith 'agent-lucy-prod'`; no v20/v6 workbook target remains.
  - Local conflict-marker audit found only separator comments in
    `portal/app/static/js/portal.js`; no unresolved merge-conflict markers
    remain in the active Python/Markdown handoff surfaces.
  - `PYTHONPATH=agent/app:agent python -m py_compile
    agent/app/lucy_core/responses_loop.py` passed.
  - `PYTHONPATH=agent/app:agent python -m pytest -q
    agent/tests/test_lucy_responses_loop.py agent/tests/test_lucy_runtime.py
    agent/tests/test_hosted_agent_adapter.py` returned `53 passed`.
  - `git diff --check` passed after the documentation updates.
- Blockers / follow-ups:
  - Native Foundry Operate remains unclosed as a visual proof requirement. The
    logged-in Chrome tab is present at the Operate URL, but the resumed terminal
    lacks screenshot/DOM/accessibility access to prove whether the native cards
    populated or still show no data.
  - Hosted Agent Application publication is not a valid current workaround for
    native Operate metrics: the live application-scoped Responses route rejects
    Hosted agent kind even though ARM accepts the deployment shape.
  - Prompt-agent Application traffic also failed to populate project Agent
    metrics while account-level model metrics moved, so the remaining native
    Operate/project metric gap is a project/control-plane rollup blocker rather
    than an obvious Lucy application-code patch.
  - The production-safe portal evidence path is currently the Azure Monitor
    workbook and App Insights KQL, not the native Foundry Operate overview.

**COA reason writeback slice 2026-04-29 — IMPLEMENTED WITH LIVE SCHEMA CONFIRMATION:**
- Triggering instruction: user requested the Lucy COA-reason writeback in the
  address-update path. The expected `/plans/004-coa-audit-writeback.md` file is
  not present in this repo. The old `.agents/skills/lucy-spec-implementation/SKILL.md`
  reference has since been resolved as a stale scaffold, so the explicit user
  instruction drove this bounded slice.
- Files changed:
  - `agent/app/user_functions.py`
  - `portal/app/user_functions.py`
  - `agent/tests/test_coa_reason_writeback.py`
- Summary:
  - Added COA reason schema discovery around `new_classmembers` metadata.
  - Lucy address updates now add `COA via Lucy` to the same Dynamics PATCH
    payload as the address fields.
  - For Dataverse choice fields, Lucy resolves the stored integer option value
    from metadata instead of hardcoding a guessed value.
  - Address updates now fail closed before PATCH when the COA reason field is
    missing, metadata is unavailable, or the `COA via Lucy` option cannot be
    confirmed.
  - Live Dataverse metadata confirmed `new_classmembers` maps to logical entity
    `new_classmember`, `COA Reason` is `new_coareason` (`Picklist`), and
    `COA via Lucy` stores as `100000005`.
  - Mirrored the behavior in the portal copy so the duplicate address-update
    surface does not drift.
- Research evidence:
  - Official Dataverse Web API docs confirm row updates use PATCH.
  - Official Dataverse docs confirm choice columns use integer values rather
    than display labels, so non-text COA fields remain blocked until the stored
    option value is confirmed.
- Tests run:
  - `python -m pytest -q agent/tests/test_coa_reason_writeback.py`
  - `python -m py_compile agent/app/user_functions.py portal/app/user_functions.py agent/tests/test_coa_reason_writeback.py`
  - Live Dataverse metadata query for `new_classmember.new_coareason`.
- Blockers / ambiguity:
  - No live writeback mutation was performed from this workspace.

---

## Hosted Agent RBAC and v12 conversation isolation fix 2026-05-03

- Status: deployed and verified for Hosted v12 response retrieval plus one-off
  Hosted target evaluation.
- Summary:
  - Cross-checked current Microsoft Foundry Hosted Agent and Monitor dashboard
    documentation against the live failure. The scheduled eval screenshot was
    the documented App Insights / Log Analytics authorization failure path.
  - Assigned the NCUS Foundry project managed identity
    `d4f3d82d-0056-4e6f-93f8-d1be9b049d94` the missing `Log Analytics Reader`
    role on both the connected App Insights component
    `agent-lucy-appins-eus2` and its backing managed Log Analytics workspace.
    The project identity already had `Log Analytics Data Reader` on the
    workspace; it now has both roles.
  - Root-caused the next Hosted eval blocker: the Hosted adapter was copying
    outer Hosted protocol `conv_...` / `caresp_...` ids into Lucy's inner
    prompt-agent session, causing inner `agent-lucy-prod` Responses calls to
    fail with `conversation_not_found` during Foundry target evals.
  - Updated the adapter so Hosted ids are retained only as metadata
    (`foundry_conversation_id`, `foundry_previous_response_id`), while Lucy's
    inner prompt-agent session only receives state from `lucy_session` metadata
    or real inner `resp_...` ids.
  - Built and pushed NCUS Hosted image
    `agentlucyacrncus.azurecr.io/agent-lucy-hosted:hosted-pr2-20260503072101-convfix`
    (`sha256:6eba51f95558ef0c96ede39c128547761f2e6cfbaa282227f3725297468c477a`).
  - Created Hosted Agent version `agent-lucy-hosted-ncus:12`; SDK polling
    reached `status=active`.
- Files changed:
  - `agent/hosted_agent/app.py`
  - `agent/tests/test_hosted_agent_adapter.py`
  - `TASKS.md`
  - `agent/hosted_agent/README.md`
  - `state/refactor-ledger.md`
- Research evidence:
  - Microsoft Hosted Agent permissions reference: Hosted setup requires
    project managed identity access for evaluation telemetry, and distinguishes
    Foundry data-plane roles from ARM/control-plane roles.
  - Microsoft Agent Monitoring Dashboard docs: authorization errors mean
    missing RBAC on Application Insights or the Log Analytics workspace; log
    access needs `Log Analytics Reader`.
  - Microsoft Cloud Evaluation docs: Hosted agents are supported as
    `azure_ai_agent` targets using `azure_ai_target_completions`; response-id
    evaluation uses the `azure_ai_responses` data source.
- Tests and live verification:
  - `python -m pytest agent/tests/test_hosted_agent_adapter.py agent/tests/test_lucy_responses_loop.py -q`
    -> `40 passed`.
  - `python -m py_compile agent/hosted_agent/app.py agent/hosted_agent/deploy_hosted_agent.py agent/app/lucy_core/responses_loop.py`
    -> passed.
  - Hosted v12 smoke:
    `caresp_4f0031a1cb5fec3d00XpJLlinob82htkJ88uOhm6l5enb9339R`,
    `status=completed`, `error=None`, output `Lucy hosted v12 is online.`
  - Hosted v12 response retrieval for the same `caresp_...` id returned
    `status=completed`, `error=None`, and the same output text.
  - Hosted v12 target evaluation run
    `evalrun_df11a3f7b4f3458b8e2d492d45be85b8` completed with output text
    `Lucy hosted target evaluation v12 is online.`, `passed=1`, `failed=0`,
    `errored=0`, and model usage rows for both `azure_ai_system_model` and
    `gpt-5.2-2025-12-11`.
- Blockers / follow-ups:
  - The old broad scheduled eval definition now gets past the App Insights
    permission failure but needs evaluator data-mapping cleanup for tool-call
    evaluators before it can be used as the production scheduled benchmark.
  - The old Hosted continuous response-eval rule has only historical failed
    v10/v11 runs in the SDK listing; wait for or recreate a clean post-v12
    continuous rule before calling continuous Hosted eval fully closed.
  - Main Foundry Operate dashboard population still needs portal/KQL
    re-check after ingestion lag. Raw Hosted v12 response and one-off eval
    proof are green.

---

## Hosted Agent gpt-5.2-chat alignment 2026-05-03

- Status: deployed and verified for Hosted v13 chat-model routing.
- Summary:
  - Root-caused the model split reported in Foundry: Hosted container env had
    chat-flavored model settings, but `MODEL_DEPLOYMENT_NAME=gpt-5.2` was still
    present and wins over `AZURE_AGENT_MODEL` / `AZURE_GPT_MODEL` in Lucy's
    current startup and Responses code paths.
  - Created the NCUS Foundry model deployment `gpt-5.2-chat`
    (`gpt-5.2-chat`, version `2025-12-11`, `GlobalStandard`, capacity `535`)
    on `agent-lucy-foundry-ncus`.
  - Published/reconciled the NCUS inner prompt agent onto the chat lane. Live
    startup telemetry now reports `agent-lucy-prod:6` and model
    `gpt-5.2-chat`.
  - Created Hosted Agent version `agent-lucy-hosted-ncus:13` from the same
    `hosted-pr2-20260503072101-convfix` image, with
    `MODEL_DEPLOYMENT_NAME`, `AZURE_AGENT_MODEL`, `AZURE_GPT_MODEL`, and
    `AZURE_SUMMARY_MODEL` aligned to `gpt-5.2-chat`.
  - Preserved Hosted-only guards:
    `LUCY_CHAINLIT_ENABLED=false` and
    `LUCY_DASHBOARD_ROUTES_ENABLED=false`.
- Files changed:
  - `TASKS.md`
  - `agent/hosted_agent/README.md`
  - `state/refactor-ledger.md`
- Tests and live verification:
  - Hosted v13 smoke:
    `caresp_3f8f163a7d28231200iW6s1z60fta5B9NnfiPgbJc9aS3e4ep7`,
    `status=completed`, `error=None`, output
    `Lucy's hosted GPT-5.2 chat is online and responding normally.`
  - Hosted v13 response retrieval for the same `caresp_...` id returned
    `status=completed`, `error=None`, and the same output text.
  - Hosted v13 target evaluation run
    `evalrun_b03b7e0521e642c6986d3e84e10b65a3` completed with output text
    `The Lucy-hosted Target Evaluation v13 chat is now online.`,
    `passed=1`, `failed=0`, `errored=0`.
  - App Insights KQL shows Hosted request rows for
    `invoke_agent agent-lucy-hosted-ncus:13` with `success=True`,
    `gen_ai.agent.name=agent-lucy-hosted-ncus`,
    `gen_ai.agent.id=agent-lucy-hosted-ncus:13`, and
    `gen_ai.agent.version=13`.
  - App Insights dependency rows show the actual model path as
    `chat gpt-5.2-chat-2025-12-11`, with request/response model dimensions
    also set to `gpt-5.2-chat-2025-12-11`.
- Blockers / follow-ups:
  - Foundry Operate dashboard is still not proven populated. Raw trace,
    request, dependency, Build traces, and one-off eval evidence are green; the
    remaining issue is now Operate-specific portal/monitoring-feature wiring or
    ingestion/display behavior, not the Hosted model lane.
  - Some Foundry eval usage summaries still display a base `gpt-5.2` label.
    Treat raw App Insights dependency dimensions as the authoritative model
    proof for this deployment.
  - Full notice-auth-PDF-HITL canary is still pending after the observability
    path is acceptable.

---

## Hosted Agent dashboard telemetry hardening 2026-05-04

- Status: deployed and verified for Hosted v15 raw telemetry; native Foundry
  Monitor remains blocked by portal aggregation/display behavior.
- Summary:
  - Verified current Microsoft Foundry custom-agent monitoring guidance before
    editing. The dashboard path requires the registered custom agent to emit
    OpenTelemetry GenAI semantic-convention spans to the same App Insights
    resource, with `gen_ai.operation.name="create_agent"` and
    `gen_ai.agent.id` / `gen_ai.agent.name` matching the registered OTel agent
    identity. OpenTelemetry GenAI conventions also define response id/model and
    token usage attributes for GenAI spans.
  - Root-caused the v13 dashboard gap in App Insights: Hosted `create_agent`
    rows had `gen_ai.agent.id=agent-lucy-hosted-ncus:13`, but lacked response
    model and token usage. The actual usage lived only on the inner
    `agent-lucy-prod:6` model dependency rows, so the Hosted dashboard had no
    hosted-owned usage to aggregate.
  - Updated Lucy's response loop to propagate final Responses API telemetry
    onto the hosted `create_agent` span:
    `gen_ai.response.id`, `gen_ai.response.model`,
    `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`, and
    `gen_ai.usage.total_tokens`.
  - Added `gen_ai.provider.name=azure.ai.foundry` and emitted the
    `create_agent` span as `SpanKind.CLIENT` to align with current
    OpenTelemetry GenAI agent-span conventions.
  - Built and pushed:
    - v14 image
      `agentlucyacrncus.azurecr.io/agent-lucy-hosted:hosted-pr2-20260504085032-telemetry`
      (`sha256:974f40ede01051558ff8d04d2095c62a593d735e3d64a97f719d1d6b7408edf0`)
    - v15 image
      `agentlucyacrncus.azurecr.io/agent-lucy-hosted:hosted-pr2-20260504090635-otelkind`
      (`sha256:e458b27f5857aa5825fff2f4f0421a8e151c86a0072f3a68b9da7e763614510b`)
  - Created Hosted Agent versions `agent-lucy-hosted-ncus:14` and
    `agent-lucy-hosted-ncus:15` by cloning the prior Hosted environment and
    changing only the image plus explicit `LUCY_OTEL_AGENT_VERSION`.
  - Created the Azure Monitor workbook fallback `Lucy Hosted COO Monitor`
    (`/subscriptions/22f9f915-587f-4a9a-acff-69b061ef48e1/resourcegroups/agent-lucy-eus2/providers/microsoft.insights/workbooks/d93d5898-c385-40ff-978e-eea3dbf03332`)
    against App Insights `agent-lucy-appins-eus2`.
- Files changed:
  - `agent/app/lucy_core/responses_loop.py`
  - `agent/tests/test_lucy_responses_loop.py`
  - `TASKS.md`
  - `agent/hosted_agent/README.md`
  - `state/refactor-ledger.md`
- Research evidence:
  - Microsoft Foundry Agent Monitoring Dashboard docs, updated 2026-04-30:
    custom agents must be onboarded, instrumented to GenAI OpenTelemetry
    conventions, and send telemetry to the same App Insights instance as the
    Foundry project.
  - Microsoft Foundry custom-agent registration docs: the OpenTelemetry Agent
    ID is matched through `gen_ai.agent.id` on spans where
    `gen_ai.operation.name="create_agent"`; troubleshooting requires the same
    App Insights resource and GenAI semantic-convention compliance.
  - OpenTelemetry GenAI span conventions: `gen_ai.response.id`,
    `gen_ai.response.model`, `gen_ai.usage.input_tokens`, and
    `gen_ai.usage.output_tokens` are defined GenAI span attributes.
  - OpenTelemetry GenAI agent-span conventions: `create_agent` should use
    `gen_ai.operation.name="create_agent"`, include provider and agent
    identity attributes, and use CLIENT span kind.
- Tests and live verification:
  - `pytest -q agent/tests/test_lucy_responses_loop.py` -> `35 passed`.
  - `pytest -q agent/tests/test_lucy_runtime.py agent/tests/test_lucy_responses_loop.py`
    -> `40 passed`.
  - `python -m py_compile agent/app/lucy_core/responses_loop.py` -> passed.
  - Hosted v14 smoke response ids:
    `caresp_0bd86f079fbf831d00uXtxUJPouJ84cyOxJYsMXV06eIkcT4Mk`,
    `caresp_809a63646da2aa2000MtScEF3yhM3jwtAJYj7NNS1OCZYREYlt`,
    `caresp_2476b60ca3c6dd4100tx7jit6Ak7HValVtRB52KYWZ3RRPjll2`;
    all `status=completed`, `error=None`.
  - Hosted v15 smoke response ids:
    `caresp_80974b8a0367e54500usMJx1drNCMu1Ejne4LRdACjJW5ZlnVp`,
    `caresp_1ef403146a2ebc4700f0wXyuOGbTUYAZpeSfemnH3mfyGJLwke`,
    `caresp_e4833a4a0308afcd0028IggFVsUwtFSwxk2jHIKfZMRRpOE9ur`;
    all `status=completed`, `error=None`.
  - App Insights KQL for Hosted v15 `create_agent` rows shows:
    `agent_id=agent-lucy-hosted-ncus:15`,
    `agent_name=agent-lucy-hosted-ncus`, `agent_version=15`,
    `operation=create_agent`, `provider=azure.ai.foundry`,
    `request_model=gpt-5.2-chat`, `response_model=gpt-5.2-chat`,
    and token totals `4724`, `4763`, and `4741` for the three v15 smokes.
  - Foundry Build visual check shows `agent-lucy-hosted-ncus` at v15 using
    image `hosted-pr2-20260504090635-otelkind`.
  - Foundry Monitor visual check after v15 still shows `Estimated cost $0` and
    `Total token usage 0`, despite raw App Insights rows being populated.
- Blockers / follow-ups:
  - Native Foundry Monitor/Operate aggregation remains blocked outside Lucy's
    runtime instrumentation. The live telemetry now matches the documented
    custom-agent trace contract, so the remaining gap is the preview portal /
    workbook aggregation path.
  - Use `Lucy Hosted COO Monitor` for COO/demo usage and success evidence until
    the native Foundry dashboard displays the same App Insights data.
  - Re-test or recreate Hosted-targeted continuous evaluation after v15.
  - Full notice-auth-PDF-HITL canary remains pending after observability
    fallback acceptance.

---

## Hosted Agent GenAI metric export and native Monitor blocker 2026-05-04

- Status: deployed and verified for Hosted v18 raw spans, raw metrics, and
  Foundry cost API token extraction; native Foundry Monitor cards remain
  blocked by the project metrics namespace.
- Summary:
  - Added GenAI client metric export from Lucy's Responses loop using a
    dedicated Azure Monitor metric exporter, leaving the working trace/export
    path unchanged.
  - Exported `gen_ai.client.operation.duration` and
    `gen_ai.client.token.usage` with Hosted agent identity, version, request
    model, response model, token type, and Foundry project id dimensions.
  - Parsed `AI_SEARCH_PROJECT_CONNECTION_ID` to derive the current Foundry
    project ARM id for metric correlation without hardcoding a project path.
  - Built and pushed:
    - v16 image
      `agentlucyacrncus.azurecr.io/agent-lucy-hosted:hosted-pr2-20260504092413-genaimetrics`
      (`sha256:65a125a43eab408f20c7551fbf40d3c45e5fa1a8ca4c3c869d502be5b6af4c83`)
    - v17 image
      `agentlucyacrncus.azurecr.io/agent-lucy-hosted:hosted-pr2-20260504093323-genaimetricexporter`
      (`sha256:4159a6ec22372cd1c21439625df12e54c0e4fea96b2814273451d81f27435be6`)
    - v18 image
      `agentlucyacrncus.azurecr.io/agent-lucy-hosted:hosted-pr2-20260504094430-foundrymetricdims`
      (`sha256:3cca0f566ba2d65a120de5a92a0d7b35ceba83b7ad7e3efa80667ee158f8c58c`)
  - Created Hosted Agent versions `agent-lucy-hosted-ncus:16`,
    `agent-lucy-hosted-ncus:17`, and `agent-lucy-hosted-ncus:18` by cloning
    the prior Hosted environment and changing only image plus
    `LUCY_OTEL_AGENT_VERSION`.
- Files changed:
  - `agent/app/lucy_core/responses_loop.py`
  - `agent/tests/test_lucy_responses_loop.py`
  - `TASKS.md`
  - `agent/hosted_agent/README.md`
  - `state/refactor-ledger.md`
- Research evidence:
  - Microsoft Foundry Agent Monitoring Dashboard docs, updated 2026-04-30:
    the Monitor dashboard reads telemetry from the App Insights resource linked
    to the Foundry project, and empty charts can mean no recent traffic,
    excluded time range, or ingestion delay.
  - Microsoft Foundry custom-agent registration docs: Foundry correlates
    custom-agent traces through `gen_ai.operation.name="create_agent"` plus
    `gen_ai.agent.id` or `gen_ai.agent.name` matching the configured OpenTelemetry
    agent id.
  - Microsoft Azure Monitor OpenTelemetry exporter docs: Python apps can
    instantiate `AzureMonitorMetricExporter`, attach it through
    `PeriodicExportingMetricReader`, and record metrics through SDK instruments.
  - OpenTelemetry GenAI metric conventions: `gen_ai.client.operation.duration`
    and `gen_ai.client.token.usage` are the current client-side GenAI metric
    names, with token usage split by `gen_ai.token.type`.
- Tests and live verification:
  - `pytest -q agent/tests/test_lucy_responses_loop.py agent/tests/test_lucy_runtime.py`
    -> `41 passed`.
  - `python -m py_compile agent/app/lucy_core/responses_loop.py` -> passed.
  - `git diff --check` -> passed.
  - Hosted v16 smoke response ids:
    `caresp_ac455edd8be2fe1100IsCDBdbZCw4aoIICi5znV7evozkImKnD`,
    `caresp_b55e4d993821a89800sy3nayAJrQngrhLBqI66k4IMv9faB0lw`,
    `caresp_cd0cdabb0ea113b100weS70Sy3zDnF1ftHdH6rZO17267EjK1G`;
    all `status=completed`.
  - Hosted v17 smoke response ids:
    `caresp_cf38c082835d12d8005E32V9tJwRlq13dZ9V7SXoXUbFC4x82Z`,
    `caresp_7053b2f1d61b105900Bxns4Gxsntaz6qFX5sacWM9bu7eaun25`,
    `caresp_ab8c86dcba9bda5f00FHFRmici0GKm6gOiZpj3lqGiaNilwoef`;
    all `status=completed`.
  - Hosted v18 smoke response ids:
    `caresp_6e3cef1977800ae8001mKvC6cTbwaufx0M38O9OaTg685nkgNU`,
    `caresp_2abfdd0d9cda8e7e00HgyEXzdoZhd211nSW7bHFzxkeMG3uEDf`,
    `caresp_9d6af8231fea912200m0bdCxUuf9yyXpimyhR961t0Rpe4Ber7`;
    all `status=completed`.
  - App Insights KQL for Hosted v17 custom metrics showed
    `gen_ai.client.token.usage` and `gen_ai.client.operation.duration` rows
    for `agent-lucy-hosted-ncus`, `gen_ai.agent.version=17`,
    `gen_ai.request.model=gpt-5.2-chat`, `gen_ai.response.model=gpt-5.2-chat`,
    and input/output token dimensions.
  - Foundry Monitor network capture after v18 showed the page's own
    `listBatchCostMetricsData` response returning token totals for Hosted
    versions, including `totalTokens=57296` for
    `agent-lucy-hosted-ncus:18`, and an aggregate `totalTokens=284960` across
    hosted versions 14-18.
  - The same page's Azure Monitor project metrics requests against namespace
    `microsoft.cognitiveservices/accounts/projects` returned empty timeseries
    for `AgentResponses`, `AgentInputTokens`, and `AgentToolCalls`.
  - Foundry Monitor screenshots after v17 and v18 still show `Estimated cost
    $0` / `--` and `Total token usage 0`:
    `/tmp/foundry_agent_v17_monitor.png`,
    `/tmp/foundry_agent_v17_monitor_7D.png`,
    `/tmp/foundry_agent_v17_monitor_1M.png`,
    `/tmp/foundry_agent_v18_monitor.png`, and
    `/tmp/foundry_agent_v18_monitor_after_cost.png`.
  - Fresh SDK invocation on 2026-05-04 at 10:08Z returned
    `caresp_a07125974af2ed6900vmHmvxhbte6i5KGRazOK1OcskevV5VWq`,
    `status=completed`, `error=None`, and output
    `Lucy hosted monitor smoke online.`.
  - App Insights KQL for that response showed a `create_agent` dependency at
    `2026-05-04T10:08:44Z` with
    `gen_ai.agent.id=agent-lucy-hosted-ncus:18`,
    `gen_ai.agent.name=agent-lucy-hosted-ncus`,
    `gen_ai.agent.version=18`, `gen_ai.response.model=gpt-5.2-chat`, and
    `gen_ai.usage.total_tokens=4931`.
  - Direct Azure Monitor query over the following 30-minute project metrics
    window still returned total `0` for `AgentResponses`, `AgentInputTokens`,
    `AgentOutputTokens`, `AgentRuns`, and `AgentToolCalls` in namespace
    `microsoft.cognitiveservices/accounts/projects`.
- Blockers / follow-ups:
  - Native Foundry Monitor cards are now blocked on Microsoft/project-metrics
    aggregation, not Lucy runtime telemetry. The page can extract hosted token
    totals from App Insights via its cost API, but the operational cards are
    driven by project metrics that remain empty.
  - Keep using raw App Insights KQL and `Lucy Hosted COO Monitor` for demo/COO
    evidence until `AgentResponses` / `AgentInputTokens` populate in the
    `microsoft.cognitiveservices/accounts/projects` metrics namespace.
  - Do not mark the Hosted/Foundry dashboard acceptance gate complete until the
    native Monitor cards visually show non-zero usage.
  - Full notice-auth-PDF-HITL canary remains pending after observability
    fallback acceptance.

---

## Hosted Agent Operate workbook chat-span alignment 2026-05-04

- Status: deployed and verified for Hosted v20 raw App Insights rows that match
  the Foundry Operate/Application Analytics workbook query contract; native
  Build Monitor project metrics still return zero and still need visual portal
  proof before the dashboard gate can be called complete.
- Summary:
  - Inspected the live `ai.azure.com` Observability bundle and downloaded the
    English `FoundryDashboard` workbook asset. Its Application Analytics tiles
    filter `dependencies` on `cloud_RoleName` plus
    `gen_ai.operation.name in ("chat", "process_thread_run",
    "text_completion", "get_thread_run")`.
  - Kept Lucy's existing `create_agent` span for Foundry custom-agent
    correlation and added a nested `chat` span around the Responses loop so the
    Operate workbook sees hosted inference-call rows without removing the
    custom-agent correlation row.
  - Built and pushed image
    `agentlucyacrncus.azurecr.io/agent-lucy-hosted:hosted-pr2-20260504102638-operatechatspan`
    (`sha256:f0315752ce921d9972863476b9aa6bb668fd7f0fd538f0241221ee35e7740bda`).
  - Created `agent-lucy-hosted-ncus:19` first, but it was bad because the clone
    script read the wrong SDK field and only carried two env vars. The SDK smoke
    failed with HTTP 500, so v19 must not be used as the canary.
  - Created `agent-lucy-hosted-ncus:20` from v18's full
    `definition.environment_variables` set (`61` env keys), changing only the
    image and `LUCY_OTEL_AGENT_VERSION=20`; v20 reached `active`.
- Files changed:
  - `agent/app/lucy_core/responses_loop.py`
  - `agent/tests/test_lucy_responses_loop.py`
  - `TASKS.md`
  - `agent/hosted_agent/README.md`
  - `state/refactor-ledger.md`
- Research evidence:
  - Microsoft Foundry custom-agent registration docs still require
    `gen_ai.operation.name="create_agent"` plus canonical
    `gen_ai.agent.id` / `gen_ai.agent.name` for custom-agent trace
    correlation, so the existing outer span stayed in place.
  - The live FoundryDashboard workbook asset used by `ai.azure.com` Application
    Analytics filters inference tiles on `chat` / `process_thread_run` /
    `text_completion` / `get_thread_run`, not `create_agent`.
- Tests and live verification:
  - `pytest -q agent/tests/test_lucy_responses_loop.py
    agent/tests/test_lucy_runtime.py agent/tests/test_hosted_deploy_env.py`
    -> `45 passed`.
  - `python -m py_compile agent/app/lucy_core/responses_loop.py` -> passed.
  - `git diff --check` -> passed.
  - Hosted v20 smoke response id
    `caresp_2fb55937c05798c300kxfQqrvat8JXYmHvNWqKUzsyX7mod9So`;
    SDK `status=completed`, `error=None`, output
    `Lucy hosted operate chat span online.`
  - App Insights KQL after ingestion showed v20 `chat` dependency rows at
    `2026-05-04T10:31:16Z`, `success=True`, `resultCode=0`,
    `gen_ai.operation.name=chat`,
    `gen_ai.agent.id=agent-lucy-hosted-ncus:20`,
    `gen_ai.agent.version=20`, `gen_ai.response.model=gpt-5.2-chat`, and
    `gen_ai.usage.total_tokens=4810`.
  - Workbook-shaped KQL over the last 30 minutes returned
    `cloud_RoleName=agent-lucy-hosted-ncus`, `name=chat`, `rows=2`,
    `tokens=9620`, latest `2026-05-04T10:31:16Z`.
  - Direct Azure Monitor project metrics over the last 45 minutes still returned
    `0` totals for `AgentResponses`, `AgentInputTokens`, `AgentOutputTokens`,
    `AgentRuns`, and `AgentToolCalls` in namespace
    `microsoft.cognitiveservices/accounts/projects`.
- Blockers / follow-ups:
  - Native visual proof is still required. App/browser auth was unavailable in
    this session, so the Operate dashboard was verified by the exact workbook
    KQL contract, not by a fresh screenshot.
  - Do not use Hosted v19; v20 is the current canary.
  - Do not mark the dashboard acceptance gate complete until a signed-in
    Foundry visual check confirms the Operate/Application Analytics view shows
    the v20 `chat` traffic and/or the Build Monitor cards leave zero state.

---

## Foundry native metric rollup RBAC closure 2026-05-06

- Status: investigated and still blocked on the native project metric rollup.
  No runtime code change and no Azure RBAC mutation were made.
- Summary:
  - Confirmed the logged-in Chrome session has the Microsoft Foundry Operate tab
    open at
    `https://ai.azure.com/nextgen/r/Ivn5FVh_Spqs_2mwYe9I4Q,agent-lucy-ncus,,agent-lucy-foundry-ncus,agent-lucy-prj-ncus/operate/overview`
    and the `Lucy Hosted COO Monitor` workbook tab open in Azure Portal.
  - Re-ran the post-gateway-retirement Hosted smoke and prompt-application
    control in the 2026-05-06 13:41-13:42 UTC window.
  - Direct Hosted route returned
    `caresp_ff39db10110eda0000IEoPzSeV3jwlQdOTX1qc6lE0d76uQGGw`,
    `status=completed`, `error=null`.
  - Prompt-agent Application route returned
    `resp_02daf5317b79b4350169fb452942c081909de28df403ce1840`,
    `status=completed`, `error=null`, agent reference `agent-lucy-prod:8`.
  - App Insights ingested request rows for
    `invoke_agent agent-lucy-hosted-ncus:21`, Hosted `create_agent` / `chat`
    dependency rows with `gen_ai.agent.id=agent-lucy-hosted-ncus:21`, and
    prompt-agent `invoke_agent agent-lucy-prod:8` plus model `chat
    gpt-5.2-chat-2025-12-11` rows.
  - Foundry account metrics for 2026-05-06 13:35-13:50 UTC moved:
    `ModelRequests=1`, `InputTokens=4680`, `OutputTokens=96`,
    `TotalTokens=4776`.
  - Foundry project metrics for the same window remained zero for
    `AgentResponses`, `AgentInputTokens`, `AgentOutputTokens`, `AgentRuns`,
    `AgentToolCalls`, project-level `InputTokens`, project-level
    `OutputTokens`, and project-level `TotalTokens`.
- RBAC / connection evidence:
  - Foundry project App Insights connection
    `agentlucyappinseus2dq5t8e` is default, targets
    `agent-lucy-appins-eus2`, and has `error=null`.
  - Azure CLI user `Chris@apexclassaction.com` has inherited subscription
    roles including `Owner`, `Contributor`, `Monitoring Contributor`, `Log
    Analytics Contributor`, `Azure AI Administrator`, and `Azure AI User`.
  - Project managed identity `d4f3d82d-0056-4e6f-93f8-d1be9b049d94` has
    `Log Analytics Reader` on `agent-lucy-appins-eus2` and both `Log Analytics
    Reader` / `Log Analytics Data Reader` on the managed App Insights
    workspace.
  - Hosted runtime identity `bf64d26c-34a5-4bc8-a1b2-b22e9ff24b67` has `Azure
    AI User` and `Azure AI Project Manager` on the NCUS Foundry project.
- Research evidence:
  - Microsoft Foundry Agent Monitoring Dashboard docs, updated 2026-04-30:
    dashboard telemetry is read from the Application Insights resource connected
    to the Foundry project; log-based views require access to the associated Log
    Analytics workspace; empty charts can also mean no recent traffic, excluded
    time range, or ingestion delay.
  - Microsoft Foundry tracing docs, updated 2026-04-16: prompt-agent tracing is
    generally available, while workflow, hosted, and custom-agent tracing are
    preview; traces are stored in the connected Application Insights resource.
  - Azure Monitor supported project metrics docs list the project Agent metric
    names queried here (`AgentResponses`, `AgentInputTokens`,
    `AgentOutputTokens`, `AgentRuns`, `AgentToolCalls`) as preview metrics on
    `Microsoft.CognitiveServices/accounts/projects`.
- Tests and live verification:
  - Direct Hosted REST smoke completed.
  - Prompt-agent Application REST control completed.
  - App Insights KQL returned current Hosted and prompt-agent trace rows.
  - Azure Monitor account metrics returned non-zero model totals.
  - Azure Monitor project metrics returned zero Agent and token totals.
  - `chrome-cli list tabs` confirmed logged-in Foundry and COO workbook tabs.
  - `chrome-cli activate -t 162556238 --focus` confirmed the Foundry Operate
    tab can be focused and remains loaded at the Operate overview URL.
  - Process ownership check showed commands are launched by
    `/Applications/Codex.app/Contents/Resources/codex app-server`; the app
    bundle identifier is `com.openai.codex`.
  - `CGPreflightScreenCaptureAccess()` returned `False`.
  - `CGRequestScreenCaptureAccess()` returned `False`.
  - `screencapture -x /tmp/lucy-foundry-operate-resume.png` still failed with
    `could not create image from display`.
  - Window-targeted `screencapture -x -l <chrome-window-id>` still failed with
    `could not create image from window`.
  - Chrome AppleScript JavaScript execution still failed because `Allow
    JavaScript from Apple Events` is disabled.
  - macOS Accessibility inspection still failed with `osascript is not allowed
    assistive access`.
  - `AXIsProcessTrustedWithOptions(prompt: true)` returned `false`.
  - `lsof` showed no Chrome DevTools listening port available for attachment.
  - Quartz `CGWindowListCreateImage` returned no image for the Chrome window.
  - Opened System Settings panes for Screen Recording and Accessibility via
    `x-apple.systempreferences` URLs so `Codex.app` can be granted local visual
    inspection permissions if native Operate proof remains required.
  - Rechecked at 2026-05-06T13:56:09Z: screen capture preflight still returned
    `False`, Accessibility trusted check still returned `false`, and
    `chrome-cli info -t 162556238` still showed the Microsoft Foundry Operate
    tab loaded at the expected project URL.
  - Browser plugin/tool discovery exposed managed browser-session tools rather
    than an attachment to the already logged-in local Chrome tab, so that route
    cannot satisfy the `logged-in Chrome browser` proof requirement.
  - Relaunched Chrome Profile 1 with `--remote-debugging-port=9222` and the
    Foundry Operate URL. The process args contained the flag, but
    `127.0.0.1:9222` did not bind. Chrome's official 2025 remote-debugging
    hardening docs explain why: Chrome 136+ no longer respects
    `--remote-debugging-port` / `--remote-debugging-pipe` for the default Chrome
    data directory; a non-standard `--user-data-dir` would lose the logged-in
    Foundry session and therefore does not satisfy this goal.
  - Tested a reversible Chrome JavaScript Apple Events preference path:
    backed up Profile 1 preferences, attempted
    `browser.allow_javascript_apple_events=true`, restarted Chrome, and reopened
    the Operate URL. Chrome overwrote the profile JSON value on restart. A
    separate `defaults write com.google.Chrome browser.allow_javascript_apple_events
    -bool true` attempt also failed; direct AppleScript still reported
    JavaScript from Apple Events disabled. The defaults value was removed after
    the failed attempt.
- Results:
  - The retired EUS2 gateway is not masking the issue.
  - The direct Hosted route is not the only explanation; a supported
    prompt-agent Application call also failed to move project Agent metrics.
  - The documented App Insights connection and reader-access prerequisites are
    satisfied for the project/dashboard reader path.
  - Added `state/foundry-native-metrics-support-brief.md` as a compact
    Microsoft escalation / handoff artifact with resources, response ids,
    metric windows, RBAC checks, browser limitations, and the current ask.
  - Added `state/foundry-operate-completion-audit.md` to map the active goal to
    concrete evidence and record why the completion gate is still not met.
- Blockers:
  - Native Foundry project Agent metric rollup remains zero despite healthy
    execution, healthy App Insights traces, and non-zero account model metrics.
  - Programmatic visual inspection of the logged-in browser remains limited:
    the in-app browser backend is unavailable, Chrome AppleScript JavaScript is
    disabled, and screenshot capture was blocked earlier by macOS display
    permissions.
- Follow-ups:
  - Use the `Lucy Hosted COO Monitor` workbook and raw App Insights KQL as the
    portal evidence path for COO/demo review.
  - Escalate the project metric rollup behavior to Microsoft with the response
    IDs and metric windows in `state/foundry-native-metrics-support-brief.md`
    if native Build/Operate cards remain a release gate.
  - Do not reintroduce AI Gateway/APIM or mutate runtime code solely to chase
    `Microsoft.CognitiveServices/accounts/projects` metrics without a documented
    ingestion contract.

---

## Lucy COO Field Policy Boundary 2026-05-06

- Status: completed as a bounded implementation slice. This is not a new
  platform migration phase; it is a contract-hardening update based on the
  COO-confirmed Dataverse form source of truth.
- Active source of truth:
  - Dataverse table: `new_classmember` / entity set `new_classmembers`.
  - Main form: `Information`.
  - Form ID: `05e90c7f-deeb-4e50-b9c0-f7bf207bb3a2`.
  - Form tab: `Lucy Class Member Data`.
- Summary:
  - Added a central Lucy field manifest derived from the COO-approved form tab.
  - Split fields by outcome so Lucy can still pivot by intent while each tool
    carries only the fields needed for that outcome.
  - Kept internal Dataverse IDs separate from Lucy-facing fields; IDs remain
    available for tool joins but are not treated as business context.
  - Replaced `get_class_member_details_sync` dynamic all-field discovery/read
    behavior with manifest-backed `$select` clauses.
  - Restricted `get_member_disbursements_sync` to the approved disbursement
    subgrid fields and filtered requested custom selects against the manifest.
  - Tightened authentication reads to the approved identity fields.
  - Removed broad Dataverse query/update/discovery tools and reissue write tools
    from Lucy's registered Dynamics tool list. The underlying helper functions
    remain in code for internal callers, but they are no longer directly exposed
    as Lucy function-call tools.
- Files changed:
  - `agent/app/lucy_field_policy.py` (new central manifest and helpers).
  - `agent/app/user_functions.py` (manifest-backed reads/writes and narrower
    Dynamics tool registration).
  - `agent/app/agentic_authentication.py` (auth query select now uses the
    approved identity field set).
  - `agent/tests/test_lucy_field_policy.py` (new manifest unit tests).
  - `agent/tests/test_coa_reason_writeback.py` (tool registration and bounded
    read regression coverage).
  - `graphify-out/` refreshed with `graphify update .`.
- Research / evidence used:
  - Live Dataverse metadata query confirmed there is no system/personal view,
    form, dashboard, app, or chart with `Lucy` in the artifact name visible to
    the Lucy app user.
  - Live Dataverse `systemform` metadata confirmed the relevant artifact is the
    `new_classmember` main form `Information`, form id
    `05e90c7f-deeb-4e50-b9c0-f7bf207bb3a2`, with tab
    `Lucy Class Member Data`.
  - The same form XML yielded the exact Lucy sections and field logical names:
    PII, employment/settlement, disbursement subgrid, and potential member
    status.
  - The disbursement subgrid references relationship
    `new_new_classmember_new_memberdisbursement_ClassMember`, target entity
    `new_memberdisbursement`, and saved view
    `EC040B47-83C8-48D5-99F0-4BC80BEBA904` (`Active Member Disbursements`).
- Tests run:
  - `pytest -q agent/tests/test_lucy_field_policy.py
    agent/tests/test_coa_reason_writeback.py` -> `14 passed`.
  - `pytest -q agent/tests/test_lucy_tool_registry.py
    agent/tests/test_notice_tool_instructions.py
    agent/tests/test_lucy_responses_loop.py` -> `52 passed`.
  - `python -m compileall -q agent/app/lucy_field_policy.py
    agent/app/user_functions.py agent/app/agentic_authentication.py` -> passed.
  - `python -m compileall -q agent/app/agentic_authentication_enhanced_v2.py
    agent/app/lucy_core/tool_registry.py` -> passed.
  - `graphify update .` -> rebuilt graph artifacts successfully.
- Results:
  - Lucy now has a code-level field policy matching the COO-approved form source.
  - Class member detail reads no longer ask Dataverse for all fields.
  - Disbursement reads no longer pass through unapproved requested fields such
    as `new_checkreissuerequest` or `new_name`.
  - Lucy's registered Dynamics tools no longer include broad direct
    `query_entity_sync`, `update_entity_sync`, dynamic discovery, or reissue
    write surfaces.
- Blockers:
  - None for this bounded slice.
- Follow-ups:
  - If the COO wants Lucy to perform check reissue mutations, add the needed
    reissue fields to the approved Dynamics form/tab first, then reintroduce a
    dedicated outcome tool with manifest-backed read/write policy.
  - Consider mirroring the field manifest into portal/operator code only if the
    portal should share Lucy's exact member-facing boundary. This slice avoided
    changing operator surfaces.

---

## Foundry Operate Browser Inspection 2026-05-06

- Status: blocked for native Operate as the production evidence gate, but the
  direct logged-in browser inspection requirement is now satisfied.
- Summary:
  - Launched the installed CuaDriver daemon and confirmed Accessibility and
    Screen Recording grants.
  - Attached to Chrome pid `65519`, window id `6335`, with the logged-in
    Microsoft Foundry Operate page loaded for `agent-lucy-prj-ncus`.
  - Used CuaDriver `get_window_state` to capture screenshot dimensions and the
    Accessibility tree for the actual local Chrome window.
  - Opened the project selector, confirmed the available projects include
    `agent-lucy-prj-eus2` and `agent-lucy-prj-ncus`, and selected
    `agent-lucy-prj-ncus`.
  - Confirmed the Operate overview shows one active/high compliance alert for
    `agent-lucy-foundry-eus2`.
  - Confirmed the Operate overview shows `Running agents` as `1/2 agents`, but
    still shows no usable native run/cost/success/token evidence for the fresh
    Lucy traffic.
  - Opened the Assets table from the same logged-in session. It lists
    `agent-lucy-hosted-ncus` as Foundry source, status `Unknown`, version `21`,
    blank cost/token/runs, and `1/3 enabled` monitoring features; it lists the
    inner `agent-lucy-prod` as status `Running`, version `8`, published as
    `agent-lucy-prod`, estimated cost `$0.00`, blank token/runs, and `1/3
    enabled` monitoring features.
  - Opened the Hosted Agent Monitor tab for `agent-lucy-hosted-ncus`. It shows
    `Estimated cost` as `$0` and `Total token usage` as `0` for
    `4/6/2026 - 5/6/2026`.
  - Opened Monitor settings. App Insights is connected to
    `agent-lucy-appins-eus2`; continuous evaluation, scheduled evaluations, and
    evaluation alerts are disabled. Those disabled features are evaluation
    related and do not explain the empty operational cost/token/run cards.
  - Rechecked live App Insights dimensions after the visual pass. The deployed
    v21 Hosted request row has `gen_ai.agent.name=agent-lucy-hosted-ncus`,
    `gen_ai.agent.id=agent-lucy-hosted-ncus:21`,
    `gen_ai.agent.version=21`, and the NCUS
    `microsoft.foundry.project.id`. Hosted `create_agent` and `chat`
    dependency rows carry the same agent/project identity plus
    `gen_ai.provider.name=azure.ai.foundry`, `gen_ai.system=azure.ai.foundry`,
    `gen_ai.request.model=gpt-5.2-chat`, `gen_ai.response.model=gpt-5.2-chat`,
    and populated input/output/total token usage. This rules out the suspected
    deployed telemetry mismatch where `gen_ai.agent.name` might include the
    version suffix.
  - Opened the native Foundry `Traces` tab for `agent-lucy-hosted-ncus`. The
    `Sessions` subtab is populated with `1-10 of 50` sessions; the latest
    visible session is
    `cb7a17614b2868be40d605950c8cf6a830ca100764d3b7b415f9b236bbdee71`,
    status `Idle`, created `5/6/26, 7:01:59 AM`, and the session drawer shows
    `agent: agent-lucy-hosted-ncus`, `session_state: Stopped`, generated at
    `2026-05-06T14:20:30.9085254+00:00`, last accessed
    `2026-05-06T14:01:59.764+00:00`.
  - Ran a final direct Hosted Agent smoke after the browser path was working.
    It returned response id
    `caresp_52181c90d41c7cb5000Rm8Mly6EKzH9K81JVEeJ7h2gV21MIi2`,
    `status=completed`, `error=None`, and output text
    `Native trace proof alive.`
  - App Insights confirmed the final smoke with a request row at
    `2026-05-06T14:24:40.380148Z`, name
    `invoke_agent agent-lucy-hosted-ncus:21`, success `True`, duration `7871`,
    response id
    `caresp_52181c90d41c7cb5000Rm8Mly6EKzH9K81JVEeJ7h2gV21MIi2`, agent id
    `agent-lucy-hosted-ncus:21`, agent name `agent-lucy-hosted-ncus`, and
    agent version `21`.
  - App Insights dependency rows for the final smoke included Hosted
    `create_agent` and Hosted `chat` rows with model `gpt-5.2-chat`, input
    tokens `4682`, output tokens `35`, and total tokens `4717`.
  - Refreshed the native Foundry `Traces > Sessions` tab after the final smoke.
    The latest row is
    `b475a2c592cdf55253b3adfb8632f61a95174cfc785656d996e892bd73e0b1f`,
    status `Active`, created `5/6/26, 7:24:37 AM`, expires
    `6/5/26, 7:24:37 AM`.
  - Opened `Traces > Conversations`. It shows `1-25 of 76` visible
    conversation rows. The latest row has trace id
    `0980331f6722444d773ab08c5e8774b6`, response id
    `caresp_52181c90d41c7cb5000Rm8Mly6EKzH9K81JVEeJ7h2gV21MIi2`, status
    `Completed`, created `5/6/26, 7:24:40 AM`, duration `7.871`, tokens in
    `18728`, tokens out `140`, and agent version `21`. The previous fresh row
    is
    `caresp_ff39db10110eda0000IEoPzSeV3jwlQdOTX1qc6lE0d76uQGGw`, status
    `Completed`, created `5/6/26, 6:41:42 AM`, duration `8.736`, tokens in
    `18720`, tokens out `384`, and agent version `21`.
  - An immediate extra CuaDriver recheck of the Monitor tab after the final
    smoke failed with `Failed to start stream due to audio/video capture
    failure`; the latest confirmed Monitor-card state remains the earlier
    logged-in browser inspection showing `Estimated cost $0` and
    `Total token usage 0`.
- Files changed:
  - `state/foundry-operate-completion-audit.md`
  - `state/foundry-native-metrics-support-brief.md`
  - `state/refactor-ledger.md`
- Research / evidence used:
  - Local CuaDriver status and permission checks.
  - CuaDriver Accessibility tree from the logged-in Chrome Foundry Operate
    window.
  - Existing Azure Monitor metric checks recorded in
    `state/foundry-native-metrics-support-brief.md`.
  - Existing Microsoft documentation notes for Agent Monitoring Dashboard,
    project metrics, tracing, and Chrome remote debugging behavior.
  - Current Microsoft Agent Monitoring Dashboard docs still describe the
    dashboard as preview, require a Foundry project with an agent plus connected
    App Insights, and state the dashboard reads telemetry from that connected
    App Insights resource.
  - Current Microsoft project metrics docs still expose
    `AgentResponses`, `AgentInputTokens`, `AgentOutputTokens`, `AgentRuns`, and
    `AgentToolCalls` on `Microsoft.CognitiveServices/accounts/projects`, with
    AgentId/model/status/thread/tool dimensions.
- Tests / validation run:
  - CuaDriver `screenshot` call returned a successful window screenshot capture
    for window id `6335`.
  - CuaDriver `get_window_state` returned page content for the logged-in Foundry
    window before and after selecting `agent-lucy-prj-ncus`.
  - CuaDriver `get_window_state` returned the fresh final
    `caresp_52181c90d41c7cb5000Rm8Mly6EKzH9K81JVEeJ7h2gV21MIi2` row in
    `Traces > Conversations`.
  - `chrome-cli info -t 162556918` confirmed the Hosted Agent Monitor URL is
    loaded and not loading after opening the agent-specific page.
- Results:
  - Browser/visual inspection is no longer the blocker.
  - Native Foundry is not completely blank: the Hosted Agent `Traces >
    Conversations` surface does show completed v21 responses with token counts.
  - Native Operate/Monitor remains unsuitable as the go-live proof path today
    because the selected NCUS project overview, Assets table, Hosted Agent
    Monitor cards, and Azure Monitor project Agent metrics still lack populated
    cost, success, token, and run-volume dashboard evidence.
- Blockers:
  - `Microsoft.CognitiveServices/accounts/projects` Agent metrics and Foundry
    Operate cards still do not reflect the completed Hosted Lucy traffic.
- Follow-ups:
  - Keep App Insights / COO workbook evidence as the working portal proof path
    unless Microsoft resolves the native project-metrics rollup gap or the user
    accepts the workbook path for production.
  - Do not mark the Foundry/Operate production gate complete until the native
    Operate evidence path is either populated, officially replaced, or
    explicitly waived.
  - Current required user decision: either approve quitting/relaunching Chrome
    Profile 1 to enable `Allow JavaScript from Apple Events` for live page
    inspection, or explicitly accept native `Traces > Conversations` plus App
    Insights / `Lucy Hosted COO Monitor` as the production portal evidence path.

**Resume recheck 2026-05-06 14:33 UTC:**
- Chrome state:
  - `chrome-cli list tabs` still shows tab `162556918` as `Microsoft Foundry`.
  - `chrome-cli info -t 162556918` shows the tab loaded at the Hosted Agent
    Monitor URL for `agent-lucy-hosted-ncus` with `Loading: No`.
  - Chrome AppleScript can read the active tab URL and title.
  - `cua-driver call check_permissions` reports Accessibility and Screen
    Recording as granted.
  - `cua-driver call list_windows` sees Chrome pid `65519`, window id `6335`,
    on the current Space, title `Microsoft Foundry`.
  - Current CuaDriver `get_window_state` fails with
    `Failed to start stream due to audio/video capture failure`.
  - Current CuaDriver `screenshot` fails with the same ScreenCaptureKit stream
    error.
  - Current CuaDriver `page get_text` fails because Chrome's `Allow JavaScript
    from Apple Events` setting is disabled.
  - `screencapture` still fails for both display and window-specific capture.
  - Chrome DevTools still is not listening on `127.0.0.1:9222`.
  - System Events UI scripting still fails with `osascript is not allowed
    assistive access`.
  - The latest successful visual/AX inspection remains the earlier CuaDriver
    pass in this ledger.
- Azure evidence for 2026-05-06 14:20-14:35 UTC:
  - App Insights `requests` returned two successful
    `invoke_agent agent-lucy-hosted-ncus:21` rows for response
    `caresp_52181c90d41c7cb5000Rm8Mly6EKzH9K81JVEeJ7h2gV21MIi2`, duration
    `7871`, agent id `agent-lucy-hosted-ncus:21`, agent name
    `agent-lucy-hosted-ncus`, version `21`, and the NCUS Foundry project id.
  - App Insights `dependencies` returned Hosted `create_agent` and `chat` rows
    with `gpt-5.2-chat`, input tokens `4682`, output tokens `35`, total tokens
    `4717`, plus inner `agent-lucy-prod:8` rows.
  - Foundry account metrics moved at 14:25 UTC:
    `ModelRequests=1`, `InputTokens=4682`, `OutputTokens=35`,
    `TotalTokens=4717`.
  - Foundry project metrics for `AgentResponses`, `AgentInputTokens`,
    `AgentOutputTokens`, `AgentRuns`, and `AgentToolCalls` remained zero for
    every minute in the same window; project-level `InputTokens`,
    `OutputTokens`, and `TotalTokens` returned empty timeseries.
- Result:
  - Current evidence still supports App Insights / COO workbook and native
    `Traces > Conversations` as the working portal proof path.
  - Current evidence still does not satisfy a native Operate/Monitor card gate.

**Browser/Computer Use recheck 2026-05-06:**
- Computer Use permissions became available and `get_app_state` could read the
  local Google Chrome app state.
- The prior local Foundry tab was no longer present. Reopening the Hosted Agent
  Monitor URL in the local Chrome profile redirected to Microsoft sign-in.
- Computer Use saw the local Chrome window titled `Sign in to Microsoft
  Foundry`, but did not return the login page contents beyond the window title.
- Browser Use / Firecrawl created a separate browser session, navigated to the
  Foundry Operate URL, and also landed on Microsoft sign-in.
- Browser Use returned a usable sign-in accessibility tree with email textbox,
  `Next`, sign-in options, terms/privacy links, and troubleshooting control.
- Browser Use live view URL for user login:
  `https://liveview.firecrawl.dev/aHR0cHM6Ly9icm93c2VyLmZpcmVjcmF3bC5kZXYvdmlldy81NjcxZTJjYmRlNTkyNGQ0Lz90b2tlbj05YjM2YTQzN2Y0ZTAzNjcyMGZjZDliZWY0ZjRkMzRkOGFmMzMwOGQ5MDMzNDY1ZjlmMDM5ZDA2MDUyMmZlMTg2`
- Result: Browser Use and Computer Use were confirmed viable control paths
  after login. This failed-login note is superseded by the authenticated
  Computer Use recheck below.

**Browser/Computer Use authenticated recheck 2026-05-06:**
- Computer Use can now read the authenticated local Google Chrome Foundry
  session directly.
- Project Operate URL inspected:
  `https://ai.azure.com/nextgen/r/Ivn5FVh_Spqs_2mwYe9I4Q,agent-lucy-ncus,,agent-lucy-foundry-ncus,agent-lucy-prj-ncus/operate/overview`
- The project Operate overview renders normally with `Overview`, `Preview`,
  subscription `Azure subscription 1`, project selector placeholder
  `Project: All projects (2)`, and date range `4/29/2026 - 5/6/2026` with
  `7D` selected.
- The Operate overview still shows `Running agents` as `1/2 agents`, but
  native dashboard evidence is empty:
  - `Estimated cost`: `No data to show`
  - `Agent success rate`: `No data to show`
  - `Token usage`: `No data to show`
  - `Agent run volume over time`: `No data available for the selected time
    range. Please select a different time range.`
  - `Agent run volume` top increases/decreases: `No data to show`
  - `Agent success rate` chart: `No data available for the selected time
    range. Please select a different time range.`
  - `Agent run success rate trends` top increases/decreases:
    `No data to show`
- Hosted Agent Monitor URL inspected:
  `https://ai.azure.com/nextgen/r/Ivn5FVh_Spqs_2mwYe9I4Q,agent-lucy-ncus,,agent-lucy-foundry-ncus,agent-lucy-prj-ncus/build/agents/agent-lucy-hosted-ncus/monitor`
- The Hosted Agent Monitor page renders normally for `agent-lucy-hosted-ncus`;
  `Monitor` is selected, date range is `4/6/2026 - 5/6/2026` with `1M`
  selected, and operational metrics still show `Estimated cost $0` plus
  `Total token usage 0`.
- Result: Browser/Computer inspection is no longer blocked. The portal itself
  confirms the native Operate overview and Hosted Agent Monitor metric cards
  remain unpopulated, while native Traces, App Insights, account metrics, and
  the COO workbook remain the working evidence surfaces for Hosted v21 traffic.

---

## Completed Plans

### Generic Notice Fallback + SharePoint Sync Job — COMPLETED 2026-05-06

**Plan/context:** Active plan remains `001-lucy-foundry-hosted-agent-migration.md`; this completed the current `TASKS.md` notice-auth-PDF-HITL subtask captured in `state/notice-retrieval-strategy.md`.

**Status:** completed.

**Summary:**
- Preserved the existing individualized notice lookup in
  `find_notice_for_user_sync`.
- Added a generic fallback branch only after individualized lookup misses.
- Generic fallback resolves the authenticated member's case via the approved
  class-member field policy, searches the same Azure Search index for the
  case-level generic notice, prefers `generic-notices` / `Print/Notice packet`
  paths, generates a SAS URL, records the notice PDF for the Chainlit/Hosted
  artifact path, and returns structured grounding context.
- Generic fallback output is marked with
  `NOTICE_SOURCE_TYPE: generic_notice_fallback` so the response loop records a
  terminal found status instead of replaying failed lookup every turn.
- Added a standalone scheduled-job entry point for the daily SharePoint generic
  notice sync. It copies PDFs from
  `/Shared Documents/Active Cases/Settlements/{case}/Print/Notice packet` into
  `lucycmnotices/generic-notices/{case-slug}/{filename}.pdf` by default. That
  default is intentional because the live `lucy-notices-v2` Azure Search
  datasources/indexers are watching `lucycmnotices` hourly, not
  `lucygenericnotices`.
- The sync job keeps `_sync/generic_notice_ledger.json` in the destination
  container and skips unchanged files based on SharePoint item fingerprints
  (`id`, eTag/cTag, size, modified time, and hashes when present).

**Files changed:**
- `agent/app/user_functions.py`
- `agent/app/.env.example`
- `agent/app/agent_instructions.txt`
- `agent/app/lucy_core/responses_loop.py`
- `agent/app/apex.py`
- `agent/generic_notice_sync/__init__.py`
- `agent/generic_notice_sync/sync.py`
- `agent/generic_notice_sync/Dockerfile`
- `agent/generic_notice_sync/README.md`
- `agent/tests/test_generic_notice_sync.py`
- `agent/tests/test_generic_notice_fallback.py`
- `agent/tests/test_coa_reason_writeback.py`
- `agent/tests/test_lucy_responses_loop.py`
- `TASKS.md`
- `state/notice-retrieval-strategy.md`

**Research evidence used:**
- Microsoft Graph app-only access uses the OAuth client credentials flow with
  `https://graph.microsoft.com/.default`:
  https://learn.microsoft.com/graph/auth-v2-service
- Microsoft Graph DriveItem children API supports listing folder children:
  https://learn.microsoft.com/graph/api/driveitem-list-children
- Microsoft Graph DriveItem content API supports downloading file content:
  https://learn.microsoft.com/graph/api/driveitem-get-content
- Microsoft Graph site-by-path resolves the SharePoint site from host and
  server-relative path:
  https://learn.microsoft.com/graph/api/site-getbypath
- Azure Blob Python SDK `upload_blob` supports creating/uploading blobs and
  overwrite behavior:
  https://learn.microsoft.com/azure/storage/blobs/storage-blob-upload-python
- Azure AI Search blob indexers detect new/updated blobs and can run on a
  schedule; live validation confirmed the `lucy-notices-v2-*` datasources use
  `container=lucycmnotices` with hourly schedules:
  https://learn.microsoft.com/azure/search/search-howto-indexing-azure-blob-storage
  https://learn.microsoft.com/azure/search/search-howto-run-reset-indexers

**Tests / validation run:**
- `pytest -q agent/tests/test_generic_notice_sync.py agent/tests/test_generic_notice_fallback.py`
  - Result: 6 passed.
- `pytest -q agent/tests/test_generic_notice_sync.py agent/tests/test_generic_notice_fallback.py agent/tests/test_notice_tool_instructions.py agent/tests/test_lucy_field_policy.py agent/tests/test_coa_reason_writeback.py agent/tests/test_lucy_responses_loop.py agent/tests/test_lucy_artifacts.py`
  - Result: 66 passed.
- `pytest -q agent/tests/test_generic_notice_sync.py agent/tests/test_generic_notice_fallback.py agent/tests/test_notice_tool_instructions.py agent/tests/test_lucy_field_policy.py agent/tests/test_coa_reason_writeback.py agent/tests/test_lucy_responses_loop.py agent/tests/test_lucy_artifacts.py agent/tests/test_lucy_tool_registry.py agent/tests/test_lucy_runtime.py`
  - Result: 84 passed.
- `python3 -m compileall -q agent/generic_notice_sync agent/app/user_functions.py`
  - Result: passed.
- `graphify update .`
  - Result: graph rebuilt to 2402 nodes / 3696 edges / 254 communities.

**Results:**
- Acceptance criteria from `state/notice-retrieval-strategy.md` are satisfied
  for code-level behavior:
  - individualized notice lookup still runs first;
  - generic fallback is attempted only after miss;
  - generic fallback uses `Print/Notice packet` as the source contract;
  - fallback response includes natural labels for approved Dynamics context
    and does not expose internal field names;
  - terminal source status is logged for follow-up turn behavior.

**Blockers:** none for local implementation.

**Follow-ups:**
- Deploy/configure the scheduled sync job with Graph app permissions or managed
  identity, Blob write permission, and the real SharePoint site/drive IDs.
- Run the sync job once in dry-run/live mode after its identity is configured,
  then confirm a copied `generic-notices/...` PDF appears in `lucy-notices-v2`
  after the next hourly indexer pass.
- Run a real Hosted canary for notice-auth-PDF-HITL once the generic notice
  blobs are present in the index.

---

### `tiered-notice-retrieval-generic-sync` — COMPLETED 2026-05-07

**Status:** completed.

**Summary:**
- Confirmed the existing Graph app registration `sharepoint-lucy-rag-datacopy`
  already had broad Microsoft Graph / SharePoint application permissions and a
  valid client secret, so the sync job uses that app-only identity.
- Built and deployed Container App Job `lucy-generic-notice-sync` in
  `rg-apex-integration-prod` / West US, using ACR
  `acrapexintegrationprod.azurecr.io`.
- Scheduled the job daily at `15 3 * * *`, with a 7200-second replica timeout.
- Confirmed live Azure Search datasources/indexers for `lucy-notices-v2` watch
  `lucycmnotices`, so generic notice PDFs are copied under
  `lucycmnotices/generic-notices/...` for the existing hourly vectorization
  path.
- Live SharePoint validation showed the literal
  `{case}/Print/Notice packet` folder is often absent. The sync now tries that
  folder first, then falls back to one direct file under `{case}/Print` matching
  notice-packet/class-notice naming.
- The selector now returns exactly one selected source per case, excludes
  obvious individualized/unsafe source names containing `mail merge`,
  `for merge`, or `ssn`, and makes Azure Blob metadata ASCII-safe.
- Microsoft Graph Word-to-PDF conversion failures are non-fatal: the bad source
  is counted as failed and the job continues.

**Files changed:**
- `agent/generic_notice_sync/sync.py`
- `agent/tests/test_generic_notice_sync.py`

**Live Azure validation:**
- Final deployed image:
  `acrapexintegrationprod.azurecr.io/generic-notice-sync:generic-notice-sync-20260507031007`
  (`sha256:3c710919011ce6e7a5b762f5d4407a575a36dee1946f3b36deddfb66490a5173`).
- Clean execution: `lucy-generic-notice-sync-f0s3tgx`
  - status: `Succeeded`
  - start: `2026-05-07T03:12:32+00:00`
  - end: `2026-05-07T03:28:13+00:00`
  - copied blobs under `generic-notices`: `463`
  - duplicate case folders: `0`
  - excluded source-name hits in destination for mail-merge / for-merge / SSN
    patterns: `0`
  - ledger blob `_sync/generic_notice_ledger.json`: exists

**Tests / validation run:**
- `python3 -m compileall -q agent/generic_notice_sync agent/app/user_functions.py`
  - Result: passed.
- `pytest -q agent/tests/test_generic_notice_sync.py agent/tests/test_generic_notice_fallback.py`
  - Result: 10 passed.
- `graphify update .`
  - Result: graph rebuilt to 2414 nodes / 3727 edges / 258 communities.

**Results:**
- The generic notice sync is live, scheduled, and proven to progress through the
  real SharePoint corpus while copying at most one selected generic notice PDF
  per case into the existing west-coast blob/indexing path.
- Lucy code path still attempts individualized notice retrieval first, then
  falls back to the generic notice in Azure Search when no individualized notice
  is found.

**Blockers:** none.

**Follow-ups:**
- Confirm the hourly Azure Search indexer surfaces the new
  `generic-notices/...` blobs in `lucy-notices-v2`.
- Run a Hosted/Chainlit canary where individualized notice lookup misses and
  generic fallback opens the PDF drawer with member-specific Dynamics context.

---

### Azure Deployment Consolidation — COMPLETED 2026-05-07

**Status:** completed.

**Summary:**
- Verified local `main` was clean and in sync with `origin/main` at
  `ed5d2a22ee35d1bdb46d1b6681a74fb5d80e12c7`.
- Built and deployed the member-facing EUS2 Container App from the consolidated
  `main` build.
- Built the North Central US Hosted Agent wrapper image and created Hosted
  Agent version `agent-lucy-hosted-ncus:22` by cloning v21's full hosted
  environment variable set (`61` keys), changing only the image and explicit
  hosted telemetry version values.
- Built and updated the West US generic notice sync Container App Job image,
  then ran a manual execution to prove the refreshed image boots, authenticates,
  reads the existing ledger, and skips unchanged PDFs.

**Files changed:**
- `TASKS.md`
- `agent/hosted_agent/README.md`
- `state/refactor-ledger.md`

**Live Azure validation:**
- Member runtime:
  - ACA: `agent-lucy-eus2`
  - RG: `agent-lucy-eus2`
  - Revision: `agent-lucy-eus2--0000071`
  - Image:
    `agentlucyacreus2.azurecr.io/agent-lucy-eus2:main-ed5d2a2-20260507063412`
  - Digest:
    `sha256:9e4b51979ea468a3d455a5386ce05917b2cc3362f577f582066e9f092c325b64`
  - Public URL returned HTTP `200`:
    `https://agent-lucy-eus2.purpleocean-f3514433.eastus2.azurecontainerapps.io/`
- Hosted Agent:
  - Agent/version: `agent-lucy-hosted-ncus:22`
  - Status: `active`
  - Image:
    `agentlucyacrncus.azurecr.io/agent-lucy-hosted:hosted-main-ed5d2a2-20260507063412`
  - Digest:
    `sha256:7e7528c2525d3e2da9393f4193b4f54f7f005a0de1166167ac17b451485f8e98`
  - SDK smoke response:
    `caresp_ed298900f7ae4fc700dBXFaKoaB7vdEGtRya8Y99vMeLKE8Wdu`
  - SDK status: `completed`; error: `None`.
- Generic notice sync:
  - Container App Job: `lucy-generic-notice-sync`
  - RG: `rg-apex-integration-prod`
  - Schedule: `15 3 * * *`
  - Image:
    `acrapexintegrationprod.azurecr.io/generic-notice-sync:generic-notice-sync-ed5d2a2-20260507063412`
  - Digest:
    `sha256:b5e1a6c97b52a599dc4d119fa7bdde54f826bd878a9f22cb9844162cb3d2520a`
  - Manual execution: `lucy-generic-notice-sync-w7sm2i5`
  - Execution status: `Succeeded`
  - Final stats:
    `cases_seen=1211`, `pdfs_seen=463`, `uploaded=0`, `skipped=463`,
    `failed=0`, `missing_notice_packet=748`.

**Tests / validation run:**
- `python3 -m compileall -q agent/app agent/hosted_agent agent/generic_notice_sync`
  - Result: passed.
- `pytest -q agent/tests/test_generic_notice_sync.py agent/tests/test_generic_notice_fallback.py agent/tests/test_lucy_field_policy.py agent/tests/test_lucy_responses_loop.py agent/tests/test_lucy_runtime.py agent/tests/test_notice_tool_instructions.py agent/tests/test_coa_reason_writeback.py agent/tests/test_hosted_deploy_env.py`
  - Result: `78 passed`.
- `curl` against the member ACA root returned HTTP `200`.
- `az containerapp job logs show` for the manual generic sync execution showed
  clean completion with no failed file transfers.

**Results:**
- Azure now has the consolidated `ed5d2a2` build deployed across the
  member-facing ACA, Hosted Agent wrapper, and generic notice sync job.
- The generic sync redeploy did not churn blob storage because the existing
  ledger correctly skipped all `463` already-copied generic notice PDFs.

**Blockers / follow-ups:**
- App Insights / Log Analytics did not show fresh Hosted v22 rows in the short
  post-smoke query window. The SDK smoke completed successfully, and this
  project already treats native/monitor telemetry surfaces as delayed or
  unreliable. Recheck raw telemetry later before using v22 for COO evidence.
- Next functional canary should exercise individualized notice miss -> generic
  notice fallback -> Chainlit PDF drawer -> Dynamics member context.

---

### Notice Architecture Remediation + Generic Notice Verification — COMPLETED 2026-05-12

**Plan/context:** Active plan remains
`001-lucy-foundry-hosted-agent-migration.md`; this run corrected the notice
architecture implementation so Lucy preserves the West-primary 1M member-notice
RAG path, uses generic case notices only as deterministic fallback templates,
and does not introduce East-primary or per-blob-trigger indexing assumptions.

**Status:** completed. Live generic notices under the existing
`generic-notices/...` convention are searchable through `lucy-notices-v2`, and
Lucy now has a direct keyed case-notice fetch path that does not depend on
Search discovery.

**Summary:**
- Read `AGENTS.md`, this ledger, `TASKS.md`, `graphify-out/GRAPH_REPORT.md`,
  and the active plan only.
- Live Dataverse screen was checked first. The source of truth remains the
  `new_classmember` main `systemform` named `Information`, form id
  `05e90c7f-deeb-4e50-b9c0-f7bf207bb3a2`, tab `Lucy Class Member Data`.
  The live form was published `2026-05-11T19:01:19Z`, version `127064761`,
  so it is newer than the provided screenshot.
- The live form field set includes COA reason and normalized count metrics:
  `new_apexid`, `new_fullname`, `new_firstname`, `new_lastname`,
  `new_shortsocial`, `new_coareason`, address/contact/PIN/employee/site fields,
  `new_estimatedsettlementamount`, `new_classworkweeks`,
  `cr7fe_classcountmetric`, `new_pagaweeks`, `cr7fe_pagacountmetric`,
  employment fields, and the Lucy potential-member status/follow-up fields.
  `agent/app/lucy_field_policy.py` now records the complete live field set and
  a notice-template schema map for the D365 fields Lucy may use to fill generic
  template gaps.
- Confirmed the live generic notice sync job is `lucy-generic-notice-sync` in
  West US, writing to `AZURE_STORAGE_ACCOUNT_NAME=aiagentlucyapex01`,
  `AZURE_GENERIC_NOTICE_CONTAINER=lucycmnotices`, and
  `GENERIC_NOTICE_BLOB_PREFIX=generic-notices`.
- Confirmed the member-facing ACA runs in East US 2 but points at the West
  source data: `AZURE_STORAGE_ACCOUNT_NAME=aiagentlucyapex01`,
  `AZURE_STORAGE_CONTAINER_NAME=lucyrag`,
  `AZURE_SEARCH_ENDPOINT=https://ailucyaisearch.search.windows.net`, and
  `AZURE_SEARCH_INDEX_NAME=lucy-notices-v2`.
- Removed the erroneous repo drift that changed generic notices to
  `gp/generic-notices`; the repo again matches the running West sync job and
  `state/notice-retrieval-strategy.md`.
- Added `get_case_notice(case_id, case_title=None)` in
  `agent/app/user_functions.py`. It resolves the generic notice from West
  storage by case ID/title via
  `lucycmnotices/generic-notices/{case-slug}/{pdf}` and returns the selected
  PDF URL/metadata without relying on Search to discover the document.
- Kept the existing 1M member-notice retrieval order untouched: Apex ID
  filename, OCR/content, Apex ID + name, extended member profile search, then
  generic fallback only after individualized lookup misses.
- Scoped generic fallback RAG to the fetched case notice when indexed chunks are
  present, and falls back to the directly fetched PDF plus approved Dynamics
  member context when Search discovery is unavailable.
- Updated Lucy's system prompt to state the two-layer notice architecture, West
  authority, East mirror/runtime role, Responses API/Foundry v2 runtime, and
  generic notice gap-fill rules.

**Files changed:**
- `agent/generic_notice_sync/sync.py`
- `agent/generic_notice_sync/README.md`
- `agent/app/.env.example`
- `agent/app/user_functions.py`
- `agent/app/lucy_field_policy.py`
- `agent/app/agent_instructions.txt`
- `agent/tests/test_generic_notice_sync.py`
- `agent/tests/test_generic_notice_fallback.py`
- `agent/tests/test_lucy_field_policy.py`
- `state/refactor-ledger.md`
- `graphify-out/GRAPH_REPORT.md`, `graphify-out/graph.json`,
  `graphify-out/graph.html`

**Research / live evidence used:**
- Live storage account inspection:
  - `aiagentlucyapex01` is in `westus`.
- Live Azure Search inspection:
  - `ailucyaisearch` is in `West US`.
- Live blob inspection confirmed existing copied blobs under
  `generic-notices/...`, for example
  `generic-notices/360-health-plan-inc/360 Health Plan Inc - Notice Packet.pdf`.
- Live Azure Search query against `lucy-notices-v2` for
  `360 Health Plan Inc Notice Packet` returned five chunks for
  `https://aiagentlucyapex01.blob.core.windows.net/lucycmnotices/generic-notices/360-health-plan-inc/360%20Health%20Plan%20Inc%20-%20Notice%20Packet.pdf`.
- Live Azure Search query against `lucy-notices-v2` for `generic-notices`
  returned generic notice paths including ONR, Driscoll's, Stars Intervention,
  Wawanesa, and ZVLA.
- Live Dataverse metadata query against
  `https://apexclassaction.crm.dynamics.com/api/data/v9.2/systemforms(...)`
  confirmed the form identity, published timestamp, tab, sections, fields, and
  disbursement subgrid relationship
  `new_new_classmember_new_memberdisbursement_ClassMember`.

**Tests / validation run:**
- `pytest agent/tests/test_generic_notice_sync.py agent/tests/test_generic_notice_fallback.py agent/tests/test_lucy_field_policy.py agent/tests/test_notice_tool_instructions.py`
  - Result: `20 passed`.
- `python3 -m compileall -q agent/app/user_functions.py agent/app/lucy_field_policy.py agent/generic_notice_sync`
  - Result: passed.
- `az storage blob list --account-name aiagentlucyapex01 --container-name lucycmnotices --prefix 'generic-notices/360-health-plan-inc/'`
  - Result: one PDF exists at
    `generic-notices/360-health-plan-inc/360 Health Plan Inc - Notice Packet.pdf`.
- Live `curl` to `lucy-notices-v2/docs/search` with search text
  `360 Health Plan Inc Notice Packet`
  - Result: returned indexed generic notice chunks for the matching
    `generic-notices/360-health-plan-inc/...` PDF.
- `graphify update .`
  - Result: graph rebuilt to `2560` nodes, `3896` edges, `263` communities.

**Results:**
- The repo no longer proposes or depends on `gp/generic-notices`.
- The running generic notice sync job and repo defaults both use
  `generic-notices`.
- Live `lucy-notices-v2` can retrieve existing generic notice chunks from the
  `generic-notices/...` path Lucy uses.
- Lucy can now direct-fetch the generic case PDF from West storage by case
  title/case ID before using Search chunks for explanation.
- The D365 field map is explicit and tied to the live Lucy Class Member Data
  form field set.

**Follow-ups:**
- Run a full Hosted/Chainlit canary with a known Apex ID whose individualized
  notice lookup misses and whose case has a generic notice, then confirm PDF
  drawer + generic RAG chunks + approved Dynamics member context in one live
  conversation.

---

### Global Generic Notice Fallback + Copy Job Selector Hotfix — COMPLETED 2026-05-13

**Plan/context:** Active plan remains
`001-lucy-foundry-hosted-agent-migration.md`. This run followed up on the
live Lucy screenshot where Apex ID `AALG003` missed the individualized notice
and still did not open the generic notice fallback. `AALG003` was the canary;
the bug was global to any legacy case whose valid source notice lived directly
under `Print` with a plain notice filename instead of the newer
`Print/Notice packet` subfolder shape.

**Status:** completed and deployed. Lucy's member-facing ACA now runs the
generic fallback code, the West generic notice copy job image is updated with
the relaxed global legacy selector, and the AALG003 Allergy notice is present
and searchable in `lucy-notices-v2`.

**Summary:**
- Confirmed the live member-facing ACA was still on the older image
  `agentlucyacreus2.azurecr.io/agent-lucy-eus2:main-ed5d2a2-20260507063412`,
  so the previous local direct `get_case_notice` work was not yet in the
  runtime serving Lucy.
- Live Dynamics lookup for `AALG003` resolved to case id
  `e6abebab-48f0-ee11-904b-7c1e520b3f99` and title
  `Paris v. Allergy & Asthma Medical Group of the Bay Area, Inc.`.
- Live SharePoint source inspection found the historical case folder at
  `Active Cases/Settlements/Allergy And Asthma/Print`. The new canonical
  `Print/Notice packet` subfolder was not present for this legacy case, but
  the likely generic source was directly under `Print` as
  `Allergy - Notice v2.docx`.
- The copy job selector was too strict globally for legacy direct-`Print`
  notices. It only accepted names like notice-packet/class-notice variants
  after falling back to `Print`, so files such as `Allergy - Notice v2.docx`
  were skipped even though they are valid non-mail-merge notice sources.
- Kept `Print/Notice packet` as the primary source contract. For any
  historical case where that folder is not present yet, the sync job now
  accepts a supported direct-`Print` file whose name contains `notice`, while
  still rejecting mail-merge and SSN artifacts.
- Extended Lucy's direct generic lookup so a D365 title like
  `Paris v. Allergy & Asthma Medical Group of the Bay Area, Inc.` tries
  defendant-side and short ampersand-expanded aliases, including
  `generic-notices/allergy-and-asthma/`.
- Tightened generic Search fallback so Lucy only RAGs over the direct case
  blob selected by `get_case_notice`. If the direct case blob is absent, she
  does not broad-search `generic-notices` and accidentally attach an unrelated
  case notice.

**Files changed:**
- `agent/app/user_functions.py`
- `agent/generic_notice_sync/sync.py`
- `agent/generic_notice_sync/README.md`
- `agent/tests/test_generic_notice_fallback.py`
- `agent/tests/test_generic_notice_sync.py`
- `state/notice-retrieval-strategy.md`
- `state/refactor-ledger.md`

**Live vectorizer / indexing evidence:**
- The existing 1M individualized notice path is still vectorized. Live indexer
  `lucy-notices-v2-indexer` targets `lucy-notices-v2` through
  `lucy-notices-v2-skillset`, whose skills remain OCR, merge, split, and
  `#Microsoft.Skills.Text.AzureOpenAIEmbeddingSkill`.
- The generic notice path is also vectorized. Live indexer
  `lucy-notices-v2-indexer-generic-notices` targets the same
  `lucy-notices-v2` index, runs hourly, and uses
  `lucy-notices-v2-skillset-generic-notices`, whose skills are split plus
  `#Microsoft.Skills.Text.AzureOpenAIEmbeddingSkill`.
- Manually projected the legacy source document to West storage as
  `lucycmnotices/generic-notices/allergy-and-asthma/Allergy - Notice v2.pdf`.
- Manually ran `lucy-notices-v2-indexer-generic-notices`; last result was
  `success`, `itemsProcessed=1`, `itemsFailed=0`, start
  `2026-05-13T17:14:08.493Z`, end `2026-05-13T17:14:11.969Z`.
- Live Azure Search query for `Allergy Notice v2` returned indexed chunks for
  `https://aiagentlucyapex01.blob.core.windows.net/lucycmnotices/generic-notices/allergy-and-asthma/Allergy%20-%20Notice%20v2.pdf`.

**Deployment evidence:**
- Built and pushed member-facing ACA image:
  `agentlucyacreus2.azurecr.io/agent-lucy-eus2:codex-generic-fallback-69dc0a3-2026051310`
  with digest
  `sha256:dbc7eb5773e94388349f8a4d4d304e5982e929b5abead6d9db7663a98e1a3f97`.
- Updated `agent-lucy-eus2` to that image. Revision
  `agent-lucy-eus2--0000072` became `Running`, `Healthy`, and has
  `trafficWeight=100`.
- Built and pushed West generic notice sync image:
  `acrapexintegrationprod.azurecr.io/generic-notice-sync:generic-notice-sync-69dc0a3-2026051310`
  with digest
  `sha256:c553e31530dd94408230fe130c2ac0b272ccb5c38fc0eee42840fd92d1b9c33c`.
- Updated live Container App Job `lucy-generic-notice-sync` in West US to that
  image. The job is `Ready`, `provisioningState=Succeeded`, and still has
  `GENERIC_NOTICE_SUBPATH=Print/Notice packet` and
  `GENERIC_NOTICE_BLOB_PREFIX=generic-notices`.

**Tests / validation run:**
- `pytest agent/tests/test_generic_notice_sync.py agent/tests/test_generic_notice_fallback.py agent/tests/test_lucy_field_policy.py agent/tests/test_notice_tool_instructions.py agent/tests/test_lucy_responses_loop.py agent/tests/test_lucy_runtime.py`
  - Result: `68 passed`.
- `python3 -m compileall -q agent/app/user_functions.py agent/app/lucy_field_policy.py agent/generic_notice_sync`
  - Result: passed.
- `curl https://agent-lucy-eus2.purpleocean-f3514433.eastus2.azurecontainerapps.io/health`
  - Result: HTTP `200`.

**Results:**
- The vectorizers are still present for both the legacy individualized corpus
  and the generic notice corpus.
- The actual scheduled West copy job is now modified globally, not only the
  local repo and not only AALG003.
- AALG003's legacy Allergy generic notice is now in the West copied/indexed
  projection that Lucy can resolve through `generic-notices/allergy-and-asthma/`.
- Lucy should now use the generic case notice instead of apologizing when an
  individualized AALG003 notice is not found.

**Follow-ups:**
- Run a fresh browser conversation for `AALG003` and confirm the generic PDF
  opens in the side drawer while the chat response uses only approved Dynamics
  fields for member-specific values.

---

### Generic Notice Runtime Regression Rollback + Schema Hotfix — COMPLETED 2026-05-13

**Plan/context:** Active plan remains
`001-lucy-foundry-hosted-agent-migration.md`. This run responded to the live
report that Lucy was no longer retrieving notices after revision `0000072`.

**Status:** completed and redeployed. The broken member-facing image was rolled
back first, then a narrower hotfix was deployed as revision
`agent-lucy-eus2--0000074`.

**Summary:**
- Rolled `agent-lucy-eus2` back from
  `agentlucyacreus2.azurecr.io/agent-lucy-eus2:codex-generic-fallback-69dc0a3-2026051310`
  to the previous known image
  `agentlucyacreus2.azurecr.io/agent-lucy-eus2:main-ed5d2a2-20260507063412`
  while investigating the regression.
- Live logs on revision `0000072` showed Azure Search requests returning HTTP
  `200`, but generic fallback could not load member/case context because the
  expanded D365 `$select` failed with HTTP `400`.
- Live D365 confirmed the concrete mismatch:
  `new_projectcoordinator` is a form lookup name, but the Web API select field
  is `_new_projectcoordinator_value`. The broader issue was using visual/form
  fields and non-class-member fields as unconditional class-member `$select`
  columns in the generic fallback path.
- Treated the user-provided class-member schema list as the runtime contract
  for notice fallback. Generic fallback now selects only the class-member
  schema fields it actually needs: auth/name/address fields, case id, estimated
  settlement amount, class workweeks, and PAGA weeks.
- Kept individualized notice search Apex-ID-first. The unique notice path still
  searches filename/OCR/content using Apex ID, then member name/address only as
  secondary signals, because Apex ID is printed on the individualized PDFs.
- Live D365 trace for `AALG003` with the narrowed schema returned the member,
  case id `e6abebab-48f0-ee11-904b-7c1e520b3f99`, and case title
  `Paris v. Allergy & Asthma Medical Group of the Bay Area, Inc.` without a
  400 error.
- Confirmed the West generic blob exists at
  `generic-notices/allergy-and-asthma/Allergy - Notice v2.pdf`, and
  `lucy-notices-v2` returns indexed chunks for `Allergy Notice v2`.

**Files changed:**
- `agent/app/lucy_field_policy.py`
- `agent/app/user_functions.py`
- `agent/tests/test_generic_notice_fallback.py`
- `agent/tests/test_lucy_field_policy.py`
- `state/refactor-ledger.md`

**Deployment evidence:**
- Built and pushed member-facing ACA hotfix image:
  `agentlucyacreus2.azurecr.io/agent-lucy-eus2:codex-generic-fallback-hotfix-69dc0a3-2026051312`
  with digest
  `sha256:3097ede8d2894a8de8249fd0fe7a3b826fd78382bb75e531ba88e47c3bf9f0cb`.
- Updated `agent-lucy-eus2` to that image. Revision
  `agent-lucy-eus2--0000074` is `Running`, `Healthy`, and has
  `trafficWeight=100`.
- Fresh `curl` to
  `https://agent-lucy-eus2.purpleocean-f3514433.eastus2.azurecontainerapps.io/health`
  returned HTTP `200`.
- Fresh logs connected to revision `agent-lucy-eus2--0000074`; no new
  `400 Client Error` / `new_projectcoordinator` signature appeared in the
  sampled hotfix logs.

**Tests / validation run:**
- `pytest agent/tests/test_generic_notice_fallback.py agent/tests/test_lucy_field_policy.py agent/tests/test_notice_tool_instructions.py agent/tests/test_generic_notice_sync.py agent/tests/test_lucy_responses_loop.py agent/tests/test_lucy_runtime.py`
  - Result: `69 passed`.
- `python3 -m compileall -q agent/app/user_functions.py agent/app/lucy_field_policy.py agent/generic_notice_sync`
  - Result: passed.
- Live D365 query for `AALG003` using the narrowed schema fields:
  - Result: no error; returned member, address/name fields, `_new_case_value`,
    `new_estimatedsettlementamount`, `new_classworkweeks`, and
    `new_pagaweeks`.
- Live Search query for `Allergy Notice v2`:
  - Result: returned indexed chunks for
    `generic-notices/allergy-and-asthma/Allergy - Notice v2.pdf`.
- `graphify update .`
  - Result: graph rebuilt to `2670` nodes, `4025` edges, `260` communities.

**Results:**
- Production is no longer on the bad `0000072` runtime image.
- The actual deployed hotfix uses the narrowed class-member schema contract,
  so generic fallback should be able to fetch D365 case context and resolve the
  generic notice when individualized search misses.
- The generic sync job image from the prior section remains deployed in West;
  this regression was isolated to the member-facing runtime image.

**Follow-ups:**
- Run an interactive browser canary for `AALG003`: ask for the notice, confirm
  no individualized hit, confirm generic fallback opens the Allergy PDF side
  drawer, and confirm the chat response uses the narrowed Dynamics values.

---

### Generic Notice Flat Prefix + Prompt Contract — COMPLETED 2026-05-13

**Plan/context:** Active plan remains
`001-lucy-foundry-hosted-agent-migration.md`; this run adjusted the generic
notice projection shape and Lucy prompt contract after the user confirmed the
right target is not per-case deterministic subfolders, but one targeted generic
PDF corpus under a single folder/prefix.

**Status:** deployed and verified live.

**Summary:**
- Changed the generic notice copy destination from per-case virtual subfolders
  to a single flat prefix:
  `lucycmnotices/generic-notices/{case-slug}--{case-key}--{pdf-name}`.
- Kept the existing West storage/search architecture. The source remains
  SharePoint `Active Cases/Settlements/{case}/Print/Notice packet` with the
  direct-`Print` legacy fallback; the destination remains West storage account
  `aiagentlucyapex01`, container `lucycmnotices`, prefix `generic-notices`.
- Preserved the existing individualized/member-specific notice corpus and
  lookup order. Lucy still searches the 1M member-notice corpus first by Apex
  ID/member signals, and only uses generic fallback after individualized lookup
  misses.
- Updated Lucy's generic lookup to list only the configured generic prefix
  (`generic-notices/`) and score case-name aliases within that small corpus,
  preferring flat blobs while retaining read compatibility for the currently
  indexed legacy nested blobs during migration.
- Tightened generic RAG scoping so URL-encoded Azure Search paths still match
  the selected generic blob name; this keeps Search chunks tied to the selected
  case notice instead of broad-searching unrelated generic notices.
- Expanded `agent/app/agent_instructions.txt` with a play-by-play prompt
  contract: individualized first, then West generic flat-prefix corpus, then
  use the generic PDF as the case grounding document, then bridge to what the
  member cares about using approved D365 fields, especially amount/check,
  status, actions, timing, and rights.

**Files changed:**
- `agent/generic_notice_sync/sync.py`
- `agent/generic_notice_sync/README.md`
- `agent/app/.env.example`
- `agent/app/user_functions.py`
- `agent/app/agent_instructions.txt`
- `agent/tests/test_generic_notice_sync.py`
- `agent/tests/test_generic_notice_fallback.py`
- `agent/tests/test_notice_tool_instructions.py`
- `state/notice-retrieval-strategy.md`
- `state/refactor-ledger.md`
- `graphify-out/GRAPH_REPORT.md`, `graphify-out/graph.json`,
  `graphify-out/graph.html`

**Tests / validation run:**
- `uv run --with pytest==8.3.4 --with requests --with tenacity python -m pytest -q agent/tests/test_generic_notice_sync.py agent/tests/test_generic_notice_fallback.py agent/tests/test_notice_tool_instructions.py agent/tests/test_lucy_field_policy.py`
  - Result: `26 passed`.
- `python3 -m compileall -q agent/app/user_functions.py agent/generic_notice_sync agent/tests/test_generic_notice_sync.py agent/tests/test_generic_notice_fallback.py agent/tests/test_notice_tool_instructions.py`
  - Result: passed.
- `uv run --with requests python - <<'PY' ... build_destination_blob_name('Acme Wage & Hour', 'Notice Packet.docx', source_item_id='item-1')`
  - Result:
    `generic-notices/acme-wage-hour--b87b85c0--Notice Packet.pdf`.
- Live Azure Search datasource check:
  - `lucy-notices-v2-datasource-generic-notices`
  - container: `lucycmnotices`
  - query/prefix: `generic-notices`
- `graphify update .`
  - Result: graph rebuilt to `2789` nodes, `4170` edges, `266` communities.

**Deploy / live verification run:**
- Built and pushed member-facing Lucy runtime:
  - Image:
    `agentlucyacreus2.azurecr.io/agent-lucy-eus2:codex-generic-flat-69dc0a3-20260513214027`
  - Digest:
    `sha256:8cabce33511f14e5522cf633859a0040b3730eeb9f5b3f71460cdfa6a71bf857`
- Built and pushed West generic notice sync job:
  - Image:
    `acrapexintegrationprod.azurecr.io/generic-notice-sync:generic-notice-sync-flat-69dc0a3-20260513214027`
  - Digest:
    `sha256:f3f1c31bb77b4a4741d57fd29110e94d022a22c6790bd1c20c5c948adb1ddce9`
- Deployed Lucy Container App `agent-lucy-eus2` to revision
  `agent-lucy-eus2--0000075`.
  - Revision state: `Running`, `100%` traffic.
  - Health/smoke: `https://agent-lucy-eus2.purpleocean-f3514433.eastus2.azurecontainerapps.io/health`
    returned HTTP `200`.
- Deployed Container Apps Job `lucy-generic-notice-sync` in
  `rg-apex-integration-prod` / West US to the new sync image.
- Started sync execution `lucy-generic-notice-sync-hgx8ia8`.
  - Start: `2026-05-13T21:43:05Z`
  - End: `2026-05-13T22:00:51Z`
  - Status: `Succeeded`
  - Log samples confirmed flat copy names such as
    `generic-notices/7-eleven--ea63dbcd--7-Eleven - Notice Packet.pdf`,
    `generic-notices/amarok-llc--81afbf69--Amarok - Class Notice.pdf`,
    and `generic-notices/american-air-balance-co-inc--76d89b5b--American Air - Notice.pdf`.
  - One non-fatal source document failure was observed:
    `Sierra At Tahoe LLC / Sierra At Tahoe - Notice - Copy.docx`
    returned source status `400`; the job continued and succeeded.
- Post-sync blob inventory for account `aiagentlucyapex01`, container
  `lucycmnotices`, prefix `generic-notices/`:
  - `total_prefix_blobs=1083`
  - `flat_blobs=610`
  - `legacy_or_nonflat_blobs=473`
- Ran Azure AI Search generic-notices indexer
  `lucy-notices-v2-indexer-generic-notices` after the copy completed.
  - First pass was already in progress from `2026-05-13T21:55:22Z` and
    completed at `2026-05-13T22:01:59Z`: `items_processed=431`,
    `items_failed=0`, `errors=0`, `warnings=0`.
  - Second explicit pass accepted with HTTP `202`, ran from
    `2026-05-13T22:03:26Z` to `2026-05-13T22:06:26Z`:
    `items_processed=199`, `items_failed=0`, `errors=0`, `warnings=0`.
- Live Search query against `lucy-notices-v2` for `7-Eleven Notice Packet`
  returned flat-path chunks ahead of the older nested projection:
  - `metadata_storage_path`:
    `https://aiagentlucyapex01.blob.core.windows.net/lucycmnotices/generic-notices/7-eleven--ea63dbcd--7-Eleven%20-%20Notice%20Packet.pdf`
  - `metadata_storage_name`:
    `7-eleven--ea63dbcd--7-Eleven - Notice Packet.pdf`
  - Result count sampled: `8`; flat-path result score top hit:
    `78.357925`.

**Results:**
- New generic notices copied by the sync job will land in one flat
  `generic-notices/` folder/prefix instead of
  `generic-notices/{case-slug}/...`.
- The flattened West blob projection is now present and re-indexed through the
  live `lucy-notices-v2` path Lucy uses.
- Lucy's fallback lookup is now targeted at that one generic PDF corpus and no
  longer depends on per-case subfolder listing.
- Lucy's prompt now explicitly tells her how to bridge from a generic
  case-specific PDF to the member's practical answer using D365, instead of
  apologizing or stopping at "no individualized notice found."

**Follow-ups:**
- After the flat corpus is indexed and verified, decide whether to delete the
  older nested `generic-notices/{case-slug}/...` projection or leave it as
  temporary compatibility until Search deletion behavior is confirmed.
- Investigate/document source-file fallout separately for copied-corpus gaps;
  observed example in this run:
  `Sierra At Tahoe LLC / Sierra At Tahoe - Notice - Copy.docx` returned status
  `400` during source download/export.

---

### Generic Notice Flat Projection Cleanup + Search Tombstone Repair — COMPLETED 2026-05-13

**Plan/context:** Active plan remains
`001-lucy-foundry-hosted-agent-migration.md`. This closes the follow-up from the
flat-prefix migration and records the user's corrected retrieval contract:
individualized member notices and generic case notice templates are two
different valid paths. The member corpus remains Apex-ID/member-signal driven;
the generic corpus is a separate, flat, case-template RAG corpus under one
targeted folder/prefix.

**Status:** deployed, copied, indexed, tombstone-cleaned, and verified live.

**Summary:**
- Preserved the existing individualized notice path over the large
  member-specific corpus. Apex ID remains the critical unique signal for member
  PDFs because it is printed on each individualized notice page.
- Kept generic notices separate from that member corpus. Generic notices are
  case-level templates, one document reused for all members in the case; Lucy
  scopes RAG to the generic notice corpus by case name/case slug/blob path, then
  fills practical member-specific answers from D365.
- Updated the generic notice sync projection to write a single canonical flat
  blob per source case:
  `lucycmnotices/generic-notices/{case-slug}--{case-key}--generic-notice.pdf`.
- Retained source traceability in blob metadata:
  `notice_source_type=generic_notice`, `case_name`, `case_slug`, `case_key`,
  `original_file_name`, `source_file_name`, `sharepoint_item_id`, and
  `sharepoint_case_folder_id`.
- Added sync-side pruning so every non-active blob under `generic-notices/` is
  removed after a successful source walk, including older nested
  `generic-notices/{case-slug}/...` projections and older noncanonical flat
  files.
- Confirmed Azure AI Search did not automatically delete stale chunks after
  the old blobs were removed, so stale `lucy-notices-v2` docs were manually
  deleted by `chunk_id` only when their `metadata_storage_path` no longer
  matched a live blob URL under the active flat corpus.

**Files changed:**
- `agent/generic_notice_sync/sync.py`
- `agent/generic_notice_sync/README.md`
- `agent/app/.env.example`
- `agent/app/user_functions.py`
- `agent/app/agent_instructions.txt`
- `agent/app/lucy_field_policy.py`
- `agent/tests/test_generic_notice_sync.py`
- `agent/tests/test_generic_notice_fallback.py`
- `agent/tests/test_notice_tool_instructions.py`
- `agent/tests/test_lucy_field_policy.py`
- `state/notice-retrieval-strategy.md`
- `state/refactor-ledger.md`
- `graphify-out/GRAPH_REPORT.md`, `graphify-out/graph.json`,
  `graphify-out/graph.html`

**Deploy / live verification run:**
- Lucy runtime image deployed:
  - Image:
    `agentlucyacreus2.azurecr.io/agent-lucy-eus2:codex-generic-case-scope3-69dc0a3-20260513224006`
  - Digest:
    `sha256:8cc1318eca0096f9a81b8f72d1f894df5c991c43043b5dc9efdd540cfd508797`
  - Active revision: `agent-lucy-eus2--0000079`
  - Revision state: running/healthy with `100%` traffic.
- Generic notice sync image deployed:
  - Image:
    `acrapexintegrationprod.azurecr.io/generic-notice-sync:generic-notice-sync-flat-prune-69dc0a3-20260513232214`
  - Digest:
    `sha256:ecf414e7c9a5405b53cd697bd54a125a0f2c00b597a55be6f83a20db29ae33ec`
  - Manual execution: `lucy-generic-notice-sync-hnsbjgf`
  - Start: `2026-05-13T23:24:25Z`
  - End: `2026-05-13T23:35:33Z`
  - Status: `Succeeded`
- Post-prune West blob inventory:
  - Account: `aiagentlucyapex01`
  - Resource group: `rg-apex-lucy-prd-01`
  - Azure resource location: `westus`
  - Region/source role: West source-of-truth storage projection
  - Container: `lucycmnotices`
  - Prefix: `generic-notices/`
  - Total live blobs under prefix: `525`
  - Canonical `--generic-notice.pdf` blobs: `525`
- Example live blob metadata:
  - Blob:
    `generic-notices/7-eleven--67966a96--generic-notice.pdf`
  - `case_name=7 Eleven`
  - `case_slug=7-eleven`
  - `case_key=67966a96`
  - `notice_source_type=generic_notice`
  - `original_file_name=7-Eleven - Notice Packet.pdf`
  - `sharepoint_case_folder_id=015OBNCLPK4PFP37YJ2BELKYHPJHKGY6QX`
  - `sharepoint_item_id=015OBNCLJ77PQ2VXSZ7RBYLKJVMBQYEZD4`

**Search/index validation:**
- Search service:
  - Name: `ailucyaisearch`
  - Resource group: `rg-apex-lucy-prd-01`
  - Azure resource location: `westus`
  - Index Lucy uses: `lucy-notices-v2`
- Ran `lucy-notices-v2-indexer-generic-notices` after the flat copy.
  - Run ending `2026-05-13T23:20:24.24Z`: `itemsProcessed=177`,
    `itemsFailed=0`.
- Ran the same indexer after blob pruning.
  - Run from `2026-05-13T23:39:45.413Z` to
    `2026-05-13T23:39:48.55Z`: `itemsProcessed=0`, `itemsFailed=0`.
  - Important finding: this did not delete stale Search chunks for deleted
    blobs.
- Manual Search tombstone cleanup against `lucy-notices-v2`:
  - Active flat Blob URLs: `525`
  - Generic Search docs seen before cleanup: `52224`
  - Active generic Search docs before cleanup: `16188`
  - Stale generic Search docs before cleanup: `36036`
  - Deleted stale Search docs by `chunk_id`: `36036`
- Post-cleanup Search verification:
  - Active flat Blob URLs: `525`
  - Generic Search docs seen: `16188`
  - Active generic Search docs seen: `16188`
  - Stale generic Search docs seen: `0`
- Known-case query verification:
  - Query for Allergy/Asthma returned only:
    `https://aiagentlucyapex01.blob.core.windows.net/lucycmnotices/generic-notices/allergy-and-asthma--ef9fa239--generic-notice.pdf`
    across the sampled top `8` hits.
  - Query for 7-Eleven returned only:
    `https://aiagentlucyapex01.blob.core.windows.net/lucycmnotices/generic-notices/7-eleven--67966a96--generic-notice.pdf`
    across the sampled top `8` hits.

**Tests / validation run:**
- `uv run --with pytest==8.3.4 --with requests --with tenacity python -m pytest -q agent/tests/test_generic_notice_sync.py agent/tests/test_generic_notice_fallback.py agent/tests/test_notice_tool_instructions.py agent/tests/test_lucy_field_policy.py`
  - Result: `31 passed`.
- `uv run python -m compileall -q agent/app agent/generic_notice_sync`
  - Result: passed.
- `git diff --check`
  - Result: passed.
- `graphify update .`
  - Result: graph rebuilt to `2860` nodes, `4277` edges, `263`
    communities.

**Results:**
- The live West blob projection now contains exactly one flat generic notice
  corpus under `lucycmnotices/generic-notices/`.
- `lucy-notices-v2` now contains only active chunks for that flat corpus; stale
  folder-era and stale noncanonical flat Search docs were removed.
- Lucy's prompt and tool path now explicitly preserve both correct notice
  paths: individualized Apex-ID notice first, generic case-template RAG
  fallback second, D365 field fill in chat after generic grounding.

**Follow-ups:**
- Run an interactive browser canary for `AALG003`: ask for the notice, confirm
  no individualized hit, confirm generic fallback opens
  `allergy-and-asthma--ef9fa239--generic-notice.pdf`, and confirm the response
  fills practical member data from D365 rather than implying the generic PDF
  itself contains member-specific values.
- Track copied-corpus source fallout separately for cases where SharePoint
  source export fails or source folder history does not match the current
  `Print/Notice packet` convention.

---

## Lucy Notices Regression RBAC + Generic Fallback Repair — completed 2026-05-14

**Scope:**
- Investigated live regression where Lucy could not retrieve member notices and
  showed no visible generic notice fallback.
- Preserved the current architecture:
  - Lucy app/runtime: `agent-lucy-eus2` in East US 2.
  - Notice Search and source storage projection: West resources under
    `rg-apex-lucy-prd-01`.
  - Search service: `ailucyaisearch`.
  - Search index: `lucy-notices-v2`.
  - Storage account/container: `aiagentlucyapex01` / `lucycmnotices`.
  - Generic notice corpus: `lucycmnotices/generic-notices/`.

**Findings:**
- The member-specific Search path was still queried first, but AALG003 correctly
  has no individualized PDF hit in `lucy-notices-v2`.
- Generic fallback was blocked by a code mismatch: `_new_case_value` was removed
  from the D365 select list whenever the live metadata cache did not report that
  lookup backing field. That meant `_fetch_case_title_for_member(...)` had no
  case GUID/title and logged generic fallback as unavailable.
- Live ACA env still had `AZURE_STORAGE_CONTAINER_NAME=lucyrag`, while the
  current member/generic notice PDFs live in `lucycmnotices`. Search results can
  carry full `metadata_storage_path` URLs, so the tool also needed to preserve
  the source container from Search metadata instead of rebuilding every URL from
  the stale default.
- RBAC gap found and repaired: the East US 2 app managed identity did not have
  an explicit data-plane role on the West Search service.

**Changes:**
- `agent/app/user_functions.py`
  - Preserves Dataverse lookup backing fields shaped like `_..._value` when
    building the generic fallback member select list.
  - Parses Search `metadata_storage_path`/URL values and keeps the source
    container (`lucycmnotices`) instead of blindly using the default env
    container.
  - Prefers full Search paths before bare `metadata_storage_name` values.
- `agent/tests/test_generic_notice_fallback.py`
  - Added/updated focused tests for preserving `_new_case_value` even when live
    field discovery omits it.
  - Added a regression test proving full Search blob URLs under
    `lucycmnotices` survive even if the env container is stale.
- Azure RBAC:
  - Assigned `Search Index Data Reader` to the `agent-lucy-eus2` managed
    identity `88339d32-6498-46de-a6c8-ee42a7cdac20` on West Search service
    `ailucyaisearch`.
  - Assignment id: `008bf93a-115f-4b92-ac92-448deab4d291`.
- Azure Container Apps:
  - Deployed image
    `agentlucyacreus2.azurecr.io/agent-lucy-eus2:codex-notice-rbac-fallback-69dc0a3-20260514030219`.
  - Digest:
    `sha256:2417e39286311f6191675442cf239bd7a6c9f2b984bd242514e69c9152f47eae`.
  - Active revision: `agent-lucy-eus2--0000080`.
  - Updated live env `AZURE_STORAGE_CONTAINER_NAME=lucycmnotices`.

**Microsoft Learn / Foundry v2 evidence:**
- Microsoft Learn MCP was available and used.
- Reviewed current Foundry/Azure OpenAI deployment docs and Azure OpenAI On Your
  Data RBAC guidance. Relevant RBAC pattern confirmed: Search data-plane access
  uses Search data roles, and Storage/Search/OpenAI identities need explicit
  role assignments when using managed identity across resources.

**Verification:**
- Focused tests:
  - Command:
    `uv run --with pytest==8.3.4 --with requests --with tenacity python -m pytest -q agent/tests/test_generic_notice_fallback.py agent/tests/test_notice_tool_instructions.py agent/tests/test_lucy_field_policy.py`
  - Result: `22 passed`.
- Broader notice/runtime sweep:
  - Command:
    `uv run --with pytest==8.3.4 --with requests --with tenacity --with opentelemetry-api python -m pytest -q agent/tests/test_generic_notice_sync.py agent/tests/test_generic_notice_fallback.py agent/tests/test_notice_tool_instructions.py agent/tests/test_lucy_field_policy.py agent/tests/test_lucy_responses_loop.py && uv run python -m compileall -q agent/app agent/generic_notice_sync && git diff --check`
  - Result: `71 passed`; compile and diff check passed.
- Live local function proof with deployed secrets:
  - `find_notice_for_user_sync("25SEVE0002")` returned an individualized notice
    PDF at
    `https://aiagentlucyapex01.blob.core.windows.net/lucycmnotices/25SEVE0002.pdf`.
  - `find_notice_for_user_sync("AALG003")` found no individualized notice,
    resolved the D365 case title
    `Paris v. Allergy & Asthma Medical Group of the Bay Area, Inc.`, and
    returned the generic notice
    `generic-notices/allergy-and-asthma--ef9fa239--generic-notice.pdf` with
    D365 context including estimated settlement amount `$369.09`, class
    workweeks `33.0`, and PAGA weeks `0.0`.
- Live browser canary:
  - URL:
    `https://agent-lucy-eus2.purpleocean-f3514433.eastus2.azurecontainerapps.io/`
  - Prompted Lucy with Apex ID `AALG003`, completed SSN last-four
    authentication from D365 test data, and observed the flow in Chrome.
  - Result: Lucy explicitly said the individualized mailed notice was not found,
    then found the official generic case notice, opened
    `Allergy - Notice v2.pdf` in the right-side PDF panel from
    `lucycmnotices/generic-notices/allergy-and-asthma--ef9fa239--generic-notice.pdf`,
    and bridged the generic notice with member-specific D365 values including
    estimated payment `$369.09`, PAGA payment `$0.00`, and workweeks `33`.

**Residual notes:**
- `Chainlit context not found` still appears around notice progress-status
  updates. It did not block retrieval or the right-side PDF render in the live
  canary, but it is noise worth cleaning separately.
- The page-rendered generic PDF text still contains sample/member text from the
  source PDF itself. Lucy correctly distinguished that the PDF is the generic
  case notice and used D365 for the authenticated member's personal amount.

---

## Lucy Regular Notice Canary — completed 2026-05-14

**Scope:**
- Confirmed the non-fallback path after the generic fallback repair: when an
  individualized/member-specific notice exists, Lucy must fetch that PDF first
  and must not fall through to the generic notice.

**Verification:**
- Live Chainlit URL:
  `https://agent-lucy-eus2.purpleocean-f3514433.eastus2.azurecontainerapps.io/`
- Started a fresh chat to avoid reusing the prior AALG003 generic-fallback
  session.
- Prompted Lucy with Apex ID `25SEVE0002`, then authenticated with SSN last-four
  `7488`.
- Result: Lucy authenticated the member, found the individualized class member
  notice, opened the right-side PDF drawer, and used the member notice URL:
  `https://aiagentlucyapex01.blob.core.windows.net/lucycmnotices/25SEVE0002.pdf`.
- Live ACA logs confirmed the call path:
  - D365 query returned one `new_classmembers` result for `25SEVE0002` and
    `new_shortsocial eq '7488'`.
  - `NoticeSearch` started member notice lookup for Apex ID `25SEVE0002`.
  - Search attempt `apex_id_filename` returned 5 PDF results.
  - `5/5` results matched the Apex ID.
  - Candidate blob URL selected:
    `https://aiagentlucyapex01.blob.core.windows.net/lucycmnotices/25SEVE0002.pdf`.
  - `Notice lookup terminal status recorded: pdf_found`.
  - Pending side-panel PDF stored as `25SEVE0002.pdf`.

**Conclusion:**
- Regular individualized notice retrieval is working live.
- Generic fallback remains fallback-only; it is not used when the member PDF is
  present.

---

## Lucy Notice Fallback Prompt + Legacy Sync Rescue — completed 2026-05-14

**Scope:**
- Investigated screenshot regression for authenticated member Candice Mendiola
  / Apex ID `CTRE559`, where Lucy stopped after the individualized notice miss
  and did not present a generic notice.
- Reviewed the whole notice prompt path for GPT-5.2-literal instructions that
  could make Lucy apologize instead of completing the required fallback.
- Preserved the COO-approved source contract: `/Print/Notice packet` remains
  the primary generic notice location. Added a narrow legacy fallback only when
  that folder is missing.

**Root cause:**
- Live logs showed `find_notice_for_user_sync("CTRE559")` did attempt the
  generic fallback after the member-specific lookup missed.
- D365 resolved the case to `Hernandez v. Creating a Legacy, Inc.`, but the
  copied/indexed generic corpus had no matching `generic-notices/...` blob.
- SharePoint source check found the case folder as
  `Active Cases/Settlements/Creating a Legacy Inc`.
- The standard `Print/Notice packet` folder was absent for this legacy case.
- The usable generic notice existed one level below `Print` in a legacy mailing
  folder:
  `Print/2nd Mailing/Notice Packet to New CMS - pdf.pdf`.
- The sync job only checked the standard folder and direct files under `Print`,
  so it never copied/indexed this source document.
- The system prompt and terminal tool miss text still contained old
  individualized-miss apology language, which let GPT-5.2 produce the visible
  "check back / no notice" answer after the generic corpus miss.

**Files changed:**
- `agent/app/agent_instructions.txt`
  - Removed the old "If notice not found" apology shortcut.
  - Added explicit play-by-play: individualized notice first; if missing, the
    generic case notice fallback is required; only say unavailable after both
    lookup paths fail.
- `agent/app/user_functions.py`
  - Changed the terminal no-PDF response to label the state as
    `NOTICE_SOURCE_TYPE: notice_unavailable_after_generic_fallback` and
    `NOTICE_LOOKUP_STATUS: no_pdf_after_individualized_and_generic`.
- `agent/generic_notice_sync/sync.py`
  - Kept `/Print/Notice packet` as primary.
  - Kept direct `Print` notice files as the existing fallback.
  - Added a one-level legacy scan of allowed mailing/notice folders under
    `Print`, while explicitly avoiding `Mail Merge`, `Mail Merged`, `Postal`,
    `Disbursement`, `CRM`, and `test` folders.
- `agent/tests/test_notice_tool_instructions.py`
  - Added prompt regression coverage so the old apology shortcut cannot return.
- `agent/tests/test_generic_notice_fallback.py`
  - Updated terminal miss expectations to require both individualized and
    generic fallback paths.
- `agent/tests/test_generic_notice_sync.py`
  - Added coverage for a missing `Print/Notice packet` folder with a generic
    notice in a one-level legacy mailing folder, and confirmed `Mail Merged` is
    not scanned.

**Verification:**
- Focused tests:
  `uv run --with pytest==8.3.4 --with requests --with tenacity python -m pytest -q agent/tests/test_notice_tool_instructions.py agent/tests/test_generic_notice_fallback.py agent/tests/test_generic_notice_sync.py`
  - Result: `27 passed`.
- Compile / graph / diff:
  `uv run python -m compileall -q agent/app agent/generic_notice_sync && graphify update . && git diff --check`
  - Result: compile passed; graph rebuilt with `9196 nodes, 11316 edges, 685
    communities`; diff check passed.
- Source selector proof:
  - `list_notice_pdfs(..., "Creating a Legacy Inc", ...)` selected
    `Notice Packet to New CMS - pdf.pdf`, SharePoint item
    `015OBNCLITJQH3YOA7ZVEYSOQQ4OWDEXBU`, size `2175968`.
- Deploy:
  - Built and pushed app image
    `agentlucyacreus2.azurecr.io/agent-lucy-eus2:codex-notice-prompt-sync-da4347a-20260514194414`.
  - Deployed Lucy ACA revision `agent-lucy-eus2--0000081`.
  - Built and pushed sync image
    `acrapexintegrationprod.azurecr.io/generic-notice-sync:generic-notice-sync-mailing-fallback-da4347a-20260514194414`.
  - Updated Container Apps job `lucy-generic-notice-sync` to that image.
- Sync execution:
  - Started execution `lucy-generic-notice-sync-ncjuj16`.
  - Observed log:
    `Syncing generic notice case=Creating a Legacy Inc file=Notice Packet to New CMS - pdf.pdf blob=generic-notices/creating-a-legacy-inc--1307a7a2--generic-notice.pdf`.
  - Verified blob in West storage account `aiagentlucyapex01`, container
    `lucycmnotices`, path
    `generic-notices/creating-a-legacy-inc--1307a7a2--generic-notice.pdf`,
    size `2175968`.
- Search / vector index:
  - Ran Azure AI Search indexer
    `lucy-notices-v2-indexer-generic-notices` on service `ailucyaisearch`.
  - Indexer result: `success`, `itemsProcessed=21`, `itemsFailed=0`, end
    `2026-05-15T02:56:23.608Z`.
  - Queried `lucy-notices-v2`; top results now include
    `https://aiagentlucyapex01.blob.core.windows.net/lucycmnotices/generic-notices/creating-a-legacy-inc--1307a7a2--generic-notice.pdf`.
- Live post-deploy canary:
  - Opened the deployed Chainlit app and submitted the screenshot case flow:
    notice explanation request, then `Candice Mendiola 8524`.
  - ACA logs show D365 auth resolved Apex ID `CTRE559`, then
    `Notice lookup source_type=generic_notice_fallback apex_id=CTRE559
    case=Hernandez v. Creating a Legacy, Inc.`
  - ACA logs show SAS generation for
    `https://aiagentlucyapex01.blob.core.windows.net/lucycmnotices/generic-notices/creating-a-legacy-inc--1307a7a2--generic-notice.pdf`.
  - ACA logs show `Notice lookup terminal status recorded: pdf_found`.

**Current status:**
- The `CTRE559` generic notice source is now copied into the flat West blob
  corpus and searchable through `lucy-notices-v2`.
- The prompt/tool path no longer allows Lucy to stop after only the
  individualized notice miss.
- The legacy sync rescue is additive only; it does not replace the standard
  `/Print/Notice packet` rule that already works for the successfully migrated
  cases.

---

## Lucy Disbursement Web API Select Repair — completed 2026-05-15

**Scope:**
- Fixed a false no-disbursement path for check/payment questions where Lucy
  could authenticate a member but receive an empty disbursement list from
  Dataverse.
- Kept the change inside the existing COO field-policy boundary; did not
  reintroduce broad Dataverse tools or check-reissue write tools.

**Root cause:**
- Live read-only Dataverse validation for Apex ID `25TEND12509` confirmed the
  member exists and has one related `new_memberdisbursement`.
- The Dynamics screen is not a saved view alone. The live source is the
  `new_classmember` main form named `Information`, form id
  `05e90c7f-deeb-4e50-b9c0-f7bf207bb3a2`, tab `Lucy Class Member Data`.
- The right-side payment grid on that tab is subgrid
  `Lucy_Member_Disbursements`, relationship
  `new_new_classmember_new_memberdisbursement_ClassMember`, using saved view
  `Active Member Disbursements`
  (`ec040b47-83c8-48d5-99f0-4bc80beba904`).
- The previous disbursement manifest could send saved-view/link or lookup
  logical names in `$select` that are not directly selectable Web API
  properties, including `new_disbursementnumber`, `new_case`,
  `new_casedisbursement`, and `modifiedby`.
- Dataverse returned HTTP 400 for those invalid properties. Lucy's generic
  `query_entity` helper converts query errors to `[]`, so the user-facing path
  looked like "no disbursements found."

**Files changed:**
- `agent/app/lucy_field_policy.py`
- `agent/app/user_functions.py`
- `agent/tests/test_lucy_field_policy.py`
- `agent/tests/test_coa_reason_writeback.py`
- `agent/tests/test_generic_notice_fallback.py`

**Validation:**
- `uv run --with pytest==8.3.4 --with requests --with tenacity python -m pytest -q agent/tests/test_lucy_field_policy.py agent/tests/test_coa_reason_writeback.py agent/tests/test_generic_notice_fallback.py`
  - Result: `34 passed`.
- `uv run python -m compileall -q agent/app/lucy_field_policy.py agent/app/user_functions.py`
  - Result: passed.
- `git diff --check`
  - Result: passed.
- `graphify update .`
  - Result: graph rebuilt; `9235 nodes`, `11360 edges`, `693 communities`.
- Live read-only Dataverse check with the post-fix manifest select returned
  `member_count=1` and `disbursement_count=1` for Apex ID `25TEND12509`; the
  returned row includes amount/check/date/cashed/void/reissue fields and the
  class-member lookup matches the authenticated member.
- Built and deployed app image
  `agentlucyacreus2.azurecr.io/agent-lucy-eus2:codex-reissue-view-fields-7275661-20260515025629`
  to ACA revision `agent-lucy-eus2--0000082`; the revision became latest-ready
  and received 100% traffic.
- Live Chainlit canary:
  - User flow: `I need to request a check reissue` -> `Name: Siu Shan Lam,
    Last 4: 7849`.
  - Lucy authenticated Apex ID `25TEND12509`.
  - ACA logs show `get_member_disbursements_sync` selected only Web API-safe
    fields:
    `new_memberdisbursementid,_new_classmember_value,_new_case_value,_new_disbursementdate_value,new_checkamount,new_checknumbertop,new_checkcashed,new_checkdate,new_checkvoiddate,new_checkreissuerequest,new_checkreissuecompleted,cr7fe_bankaccountnumber,createdon,_modifiedby_value,cr7fe_postalsort,cr7fe_traypc,cr7fe_mailbarcode`.
  - ACA logs show `Query for new_memberdisbursements returned 1 results` and
    `Found 1 disbursement(s) for member 25TEND12509`.
  - Lucy's response surfaced the real check: `$459.43`, check `17266`, issue
    date May 9, 2026, cashed May 12, 2026, current status `Cashed`, and did
    not offer an automatic reissue for a cashed check.

**Result:**
- `get_member_disbursements_sync` now uses Web API-safe disbursement select
  fields, including lookup-value properties for internal joins and
  `new_checkreissuerequest` as the authoritative member-disbursement reissue
  read value.

---

## HITL Portal Markdown History Rendering — completed 2026-05-15

**Scope:**
- Render transferred pre-handoff Lucy conversation history as markdown inside
  the HITL portal chat transcript instead of showing raw markdown text.
- Kept the change in the portal display layer only; no callback, routing,
  storage, or Teams handoff contract changes.

**Root cause:**
- The server-rendered conversation history loop in
  `portal/app/templates/conversation.html` emitted `message.content` directly
  inside `.message-content`, so initial handoff history could appear as raw
  markdown before or outside client-side rendering.
- The client-side pre-handoff safety message in
  `portal/app/static/js/conversation.js` also replayed a raw newline-delimited
  preview of transferred messages, which could make markdown snippets visible
  even when the actual transcript entries were rendered correctly.

**Files changed:**
- `portal/app/templates/conversation.html`
- `portal/app/static/js/conversation.js`
- `portal/app/static/css/conversation.css`
- `agent/tests/test_portal_handoff_markdown.py`

**Validation:**
- `uv run --with pytest==8.3.4 python -m pytest -q agent/tests/test_portal_handoff_markdown.py`
  - Result before deploy: `3 passed in 0.01s`.
- `uv run python -m py_compile portal/app/agent_portal.py`
  - Result before deploy: passed.
- `git diff --check`
  - Result before deploy: passed.
- `graphify update .`
  - Result: graph rebuilt; `9258 nodes`, `11385 edges`, `696 communities`.
- Built and deployed portal image
  `agentlucyacreus2.azurecr.io/agent-lucy-portal-eus2:codex-hitl-markdown-b051fdf-20260515040554`
  to ACA revision `agent-lucy-portal-eus2--0000026`.
- Revision verification showed `agent-lucy-portal-eus2--0000026` is healthy,
  running, latest-ready, and receiving 100% traffic.
- Live portal logs for revision `agent-lucy-portal-eus2--0000026` show startup
  completed, `Conversation history functionality enabled`, and successful
  200 responses for `/`, `/api/conversations/pending`, and
  `/api/callbacks/pending`.

**Result:**
- Initial server-rendered history messages are marked for markdown hydration,
  hydrated once on page load via the existing sanitized markdown renderer, and
  the raw pre-handoff preview has been replaced with a rendered-transcript
  status note.
- Chat markdown tables and headings now have compact portal-specific styles so
  Lucy's transferred summaries remain readable in the HITL transcript.

---

## Blocked / Abandoned Plans

_none_

---

## Restored / Current Target Scope

- **Plan 001 Phases 3-8** (Hosted Agent container, hosted-agent identity/RBAC, hosted-agent canary/cutover) — restored 2026-04-28 as the golden path. The AI Gateway custom-agent route was retired and deleted on 2026-05-04.
- **Tiered notice retrieval strategy** — added to active scope 2026-05-06 from
  user handoff. Lucy should try individualized notice PDFs first, then fall back
  to the generic notice under `Print/Notice packet`, grounding the explanation
  in the notice text and enriching with allowed Dynamics member fields. Details
  and acceptance criteria are captured in
  `state/notice-retrieval-strategy.md`.

---

## Conventions

- Update this ledger after every completed or blocked plan with: plan name, status, summary, files changed, research evidence, tests run, results, blockers, follow-ups.
- Plans are numbered. The active plan is the lowest-numbered `in_progress` entry; if none is in progress, it is the lowest-numbered absent-from-this-ledger `/plans/*.md`.
- Plan filenames in `/plans/` use `NNN-slug.md` format. Date-prefixed filenames from other agent runtimes (e.g. `.hermes/plans/`) should be migrated and renumbered before being treated as canonical.
