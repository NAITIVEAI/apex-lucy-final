# Refactor Ledger

This ledger records every plan from `/plans/` along with its status, summary, files changed, research evidence, tests, results, blockers, and follow-ups. It is the canonical resume point for any new agent session per `AGENTS.md`.

**Source-of-truth hierarchy:** explicit user instruction → `AGENTS.md` → active `/plans/*.md` → `.agents/skills/lucy-spec-implementation/SKILL.md` → existing code patterns.

---

## Active Plan

### `001-lucy-foundry-hosted-agent-migration.md` — IN PROGRESS (Phase 1 only)

**Status:** in_progress; **scope reduced** 2026-04-25 to Phase 1 (runtime extraction) and Phase 2 (artifact/handoff abstractions). Phases 3-8 (Hosted Agent container, identity/RBAC for Hosted Agent, hosted-agent canary/cutover) are **demoted to future/optional** — the team is taking the AI Gateway custom-agent registration path (plan 002) instead, which uses the same `LucyRuntime` extraction without needing a Hosted Agent container.

**Goal (revised):** Extract a UI-independent `LucyRuntime` core out of `agent/app/apex.py` so it can be invoked from (a) Chainlit (existing), (b) a thin FastAPI HTTP wrapper for AI Gateway custom-agent registration (plan 002).

**Active sub-objective (Phase 1, "Recommended First Sprint" §1-6 from plan):**
1. `LucySession`, `LucyRequest`, `LucyResponse`, `LucyArtifact` data models — **DONE 2026-04-25**
2. Extract tool-list construction (`_build_lucy_function_list`, `_build_function_registry`, `_toolset_signature`) → `lucy_core/tool_registry.py` — **DONE 2026-04-25**
3. Extract Responses loop (`_run_response_v2`, `_extract_v2_function_calls`, `_execute_v2_tool_call`, `_build_authenticated_state_items`) → `lucy_core/responses_loop.py` — **DONE 2026-04-25** (split into 3a small helpers + 3b the full orchestrator; apex.py wrappers map cl.user_session ↔ LucySession at the boundary)
4. Build `LucyRuntime.respond()` in `lucy_core/runtime.py` — **DONE 2026-04-25** (minimal: constructor takes pre-init deps, single `async respond(LucyRequest) -> LucyResponse`. **Not yet wired into any production code path** — it's a building block for the FastAPI HTTP wrapper in plan 002 Phase A)
5. Adapt Chainlit `@cl.on_message` to call `LucyRuntime.respond()` — **deferred**. Optional for the AI Gateway registration path; Chainlit can keep using the existing `_run_response_v2` adapter that itself delegates into `lucy_core.responses_loop`. Revisit if/when convergence on a single in-process invocation path becomes valuable.
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

### `002-foundry-ai-gateway-custom-agent-registration.md` — IMPLEMENTED / LIVE SMOKE PASSED 2026-04-27

**Status:** implemented for Lucy's gateway-facing ACA runtime; Foundry portal/APIM
registration remains the operator-side click/config step.

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
- Register the custom agent in the Foundry portal against
  `https://agent-lucy-gateway-eus2.purpleocean-f3514433.eastus2.azurecontainerapps.io/agent/respond`
  with OpenTelemetry agent ID `lucy-aca`.
- Configure the AI Gateway/APIM outbound policy to send
  `X-Agent-Token: <LUCY_GATEWAY_API_TOKEN>`.
- Confirm Foundry Monitor shows spans with `gen_ai.agents.id="lucy-aca"` and
  `gen_ai.tool.name`.
- Build Foundry continuous eval rules from `agent/evals/cases.jsonl`.

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

---

## Completed Plans

_none yet_

---

## Blocked / Abandoned Plans

_none_

---

## Demoted / Future Scope

- **Plan 001 Phases 3-8** (Hosted Agent container, hosted-agent identity/RBAC, hosted-agent canary/cutover) — demoted 2026-04-25 in favor of plan 002. Kept in plan 001 file for architectural reasoning. Re-prompt only if AI Gateway path proves insufficient.

---

## Conventions

- Update this ledger after every completed or blocked plan with: plan name, status, summary, files changed, research evidence, tests run, results, blockers, follow-ups.
- Plans are numbered. The active plan is the lowest-numbered `in_progress` entry; if none is in progress, it is the lowest-numbered absent-from-this-ledger `/plans/*.md`.
- Plan filenames in `/plans/` use `NNN-slug.md` format. Date-prefixed filenames from other agent runtimes (e.g. `.hermes/plans/`) should be migrated and renumbered before being treated as canonical.
