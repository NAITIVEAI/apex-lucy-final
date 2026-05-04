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
- `.agents/skills/lucy-spec-implementation/SKILL.md` is referenced by AGENTS.md but does not exist. Track as plan 003 candidate.
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
- Gateway/APIM route remains the rollback and diagnostics bridge until Hosted
  Agent parity is proven.

**COA reason writeback slice 2026-04-29 — IMPLEMENTED WITH LIVE SCHEMA CONFIRMATION:**
- Triggering instruction: user requested the Lucy COA-reason writeback in the
  address-update path. The expected `/plans/004-coa-audit-writeback.md` file is
  not present in this repo, so the explicit user instruction drove this bounded
  slice.
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

## Completed Plans

_none yet_

---

## Blocked / Abandoned Plans

_none_

---

## Restored / Current Target Scope

- **Plan 001 Phases 3-8** (Hosted Agent container, hosted-agent identity/RBAC, hosted-agent canary/cutover) — restored 2026-04-28 as the golden path. The AI Gateway custom-agent route remains an interim bridge and diagnostic fallback, not the desired end-state.

---

## Conventions

- Update this ledger after every completed or blocked plan with: plan name, status, summary, files changed, research evidence, tests run, results, blockers, follow-ups.
- Plans are numbered. The active plan is the lowest-numbered `in_progress` entry; if none is in progress, it is the lowest-numbered absent-from-this-ledger `/plans/*.md`.
- Plan filenames in `/plans/` use `NNN-slug.md` format. Date-prefixed filenames from other agent runtimes (e.g. `.hermes/plans/`) should be migrated and renumbered before being treated as canonical.
