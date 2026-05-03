# Plan 002 — Foundry AI Gateway Custom Agent Registration

## Goal

Make Microsoft Foundry v2 **evals + Monitor dashboard** work against the real Lucy runtime by registering Lucy's existing ACA agent service as a Custom Agent via the Azure AI Gateway already deployed in the Foundry project.

This plan is the chosen alternative to plan 001 phases 3-8 (Hosted Agent container). It uses the same `LucyRuntime` extraction from plan 001 Phase 1 but skips the Hosted Agent container entirely.

## Why this path

- The user already deployed "Azure AI Gateway" inside the Foundry portal. This is the Foundry-native registration path for "bring your own runtime" agents.
- Lucy's runtime stays in customer-managed ACA — no preview/region/concurrency limits from Hosted Agents preview.
- HITL flow (4-min timer, websocket, Teams ping, custom CSR portal, callback fallback) stays exactly as it is.
- The class-member experience on Chainlit is unchanged.

## Non-goals

- Replacing the existing prompt-agent metadata registration (Lucy still publishes tool schemas + prompt to Foundry on boot via `foundry_publish.py`).
- Touching the existing Activity Protocol Application endpoint (`applications/agent-lucy-prod/protocols/activityprotocol`) — keep it for any Teams/M365 routing currently in place.
- Container-level rebuild or ACR setup.

## Prerequisites

| From | What | Status |
|---|---|---|
| plan 001 Phase 1 | LucySession/LucyRequest/LucyResponse/LucyArtifact data models | DONE 2026-04-25 |
| plan 001 Phase 1 | Extract tool registry → `lucy_core/tool_registry.py` | pending |
| plan 001 Phase 1 | Extract Responses loop → `lucy_core/responses_loop.py` | pending |
| plan 001 Phase 1 | `LucyRuntime.respond()` in `lucy_core/runtime.py` | pending |
| plan 001 Phase 1 | Chainlit calls `LucyRuntime.respond()` in-process | pending |
| plan 001 Phase 2 | `LucyArtifact` extraction from tool outputs (PDF, blob, link, handoff) | pending |
| plan 001 Phase 2 | Handoff tool emits artifact (does not run timer/websocket inline) | pending |

When all of the above are green, this plan can begin Phase A.

## Phase A — HTTP wrapper around LucyRuntime

**New file:** `agent/app/lucy_core/http_app.py`

FastAPI app exposing one route plus health:

```
POST /agent/respond
  Request body: { "input_text": str, "session": { ... LucySession fields ... }, "metadata": { ... } }
  Response body: { "text": str, "session": { ... }, "tool_calls": [...], "artifacts": [...], "handoff": null|{...}, "trace_id": str|null, "errors": [...] }

GET  /agent/health      → 200 if process is up
GET  /agent/ready       → 200 if Foundry endpoint configured + AI Search reachable + Tables reachable
```

Auth (decided in Phase B): bearer token (AAD) OR API key header.

OpenTelemetry: emit spans following the **OpenTelemetry GenAI semantic conventions** that Foundry filters on (per https://learn.microsoft.com/en-us/azure/foundry/control-plane/register-custom-agent):
- An agent-creation span with `operation="create_agent"` and attribute `gen_ai.agents.id="<id>"` (or `gen_ai.agents.name`). The value is the **OpenTelemetry Agent ID** we paste into the registration form. Without this attribute the Foundry Traces panel won't correlate runs to the registered agent.
- LLM and tool spans should use `gen_ai.*` attributes (`gen_ai.system`, `gen_ai.request.model`, `gen_ai.tool.name`, etc.) for full Monitor-tab fidelity.
- Lucy's existing `tracing_config.py` initializes Azure Monitor OpenTelemetry; new code in `lucy_core/runtime.py` (and a thin wrapper around `responses_loop.py`) adds the GenAI-conformant attributes.
- App-internal span `lucy.agent.respond` can still wrap each request for our own debugging, but the GenAI-conformant span is what Foundry needs.

**Modify:** `agent/app/start_services.sh` — start the HTTP app on a new port (proposed `:8002`) alongside Chainlit (`:8000`) and health (`:8080`). Three foreground processes; `start_services.sh` already manages multi-process startup.

**Modify:** `agent/app/Dockerfile` — `EXPOSE 8002` (in addition to existing 8000, 8080).

**New file:** `agent/tests/test_http_app.py` — verify request/response shape, auth rejection on missing token, health/ready checks. Use FastAPI TestClient + a mocked `LucyRuntime`.

### Acceptance

- `POST /agent/respond` returns a valid `LucyResponse` JSON with no Chainlit imports anywhere in the call path.
- Existing `agent/tests/` still pass.
- Local Docker build succeeds; container starts all 3 processes.

## Phase B — Identity, routing, registration

### B.1 Confirm portal prereqs (most resolved per MS Learn 2026-04-25)

The "Azure AI Gateway" deployed in Foundry **is Azure API Management** (free to set up via the portal). Per MS Learn, two project-side prereqs must be true before registering:

1. **AI Gateway enabled on the Foundry resource:** Operate → Admin → AI Gateway tab → confirm the resource is listed. If not, "Add AI Gateway".
2. **Application Insights connected to the project:** Operate → Admin → select project → Connected resources → AppInsights category. Required for the Traces panel and Monitor tab to populate. **Important gotcha:** if App Insights is connected *after* the agent is registered, the registration must be redone — the connection isn't picked up retroactively.

### B.2 Auth between gateway and Lucy

Per MS Learn: APIM is a transparent proxy. *"The original authorization and authentication schema in the original endpoint still applies. When you consume the new endpoint, provide the same authentication mechanism as if you're using the original endpoint."*

So the gateway-to-Lucy auth is whatever Lucy already requires on `/agent/respond`. Use a shared `X-Agent-Token` header validated with constant-time compare against `LUCY_GATEWAY_API_TOKEN` env var. Same pattern the portal already uses (`AGENT_PORTAL_API_TOKEN`). No managed identity work, no APIM-specific identity setup.

### B.3 Register Lucy as Custom Agent

In the Foundry portal: **Operate → Overview → Register asset**. Required fields per the actual dialog (screenshot 2026-04-25):

| Field | Value |
|---|---|
| Agent URL | Lucy's ACA URL + `/agent/respond` |
| Protocol | "General HTTP, Including REST" |
| OpenTelemetry agent ID | A stable string we pick (e.g. `lucy-aca`); MUST match `gen_ai.agents.id` attribute Lucy emits on `create_agent` spans |
| Admin portal URL | Optional; could point at the existing CSR portal admin page or be left blank |
| Project | The project containing the AI Gateway and App Insights connection |
| Agent name | e.g. `Lucy (ACA)` — distinct from the existing `agent-lucy-prod` Application |
| Description | Optional |

After save, Foundry generates a new APIM-fronted URL (`https://apim-<resource>.azure-api.net/<agent-name>/`). **That's the URL clients should use going forward.** Capture it for the runbook.

### Acceptance

- Sending a test message to the Foundry-managed URL successfully reaches Lucy's `/agent/respond` and returns a `LucyResponse`.
- Auth rejection works when token is missing or wrong.
- Registration is visible in the Foundry portal.

## Phase C — Verify dashboards and traces

1. Send 5-10 test messages through the Foundry-managed URL covering: general question (no tools), notice lookup (RAG + blob), member auth (D365), handoff request (artifact only — orchestrator runs separately).
2. Confirm OpenTelemetry traces appear in Application Insights with the spans listed in plan 001 §"Observability Requirements".
3. Confirm the **Foundry Monitor tab** shows:
   - Run history with timestamps
   - Latency percentiles
   - Token usage
   - Tool execution spans visible per run
   - Run success/failure indicator
4. Document everything in `docs/architecture/foundry-ai-gateway-registration.md` (new) — runbook for future re-registration or recovery.

### Acceptance

- Monitor tab shows all 5-10 test runs.
- A non-technical leader can open the Monitor tab and see "Lucy is healthy / latency p50 is X / Y runs in last 24h".

## Phase D — Eval rules

1. Author eval dataset in `agent/evals/cases.jsonl` (new file). Start with 5-10 cases per plan 001 §5.2:
   - General scope question
   - Notice lookup
   - Member auth (mocked or staging Apex ID)
   - Handoff request (assert `LucyResponse.handoff` populated)
   - Failure injection (Search unavailable — assert graceful degradation)
2. Configure continuous evaluation rule(s) in the Foundry portal pointing at the registered custom agent. Use the same evaluators that ship with Foundry v2 (groundedness, relevance, handoff appropriateness).
3. Run a manual eval pass; confirm scores appear on Monitor tab.
4. Validate that real tool execution happens during evals — verify Azure Tables rows are written for handoff cases (in staging only) or that mock paths fire when `eval_mode=true`.

### Acceptance

- Evals run end-to-end against the registered agent.
- Scores visible in the Foundry Monitor tab alongside run history.
- At least one eval case demonstrates that real tool execution (not just LLM response) was scored.

## Phase E — Activity Protocol Application disposition

The legacy `applications/agent-lucy-prod/protocols/activityprotocol` URL was published for Teams/M365 channel routing. Decide:

- **Keep** — if Teams/M365 traffic still routes through it. The custom-agent registration is parallel; both can coexist.
- **Retire** — if Teams routing has been moved or was never used in production.

Evidence to gather before deciding:
- Does the AI Gateway support Activity Protocol forwarding for Teams traffic?
- Is there any current Teams/M365 traffic against the existing endpoint? (Check App Insights for activity to that URL.)

No action required in this plan; document the decision in the same runbook from Phase C.

## Files likely to change

### New
- `agent/app/lucy_core/http_app.py`
- `agent/tests/test_http_app.py`
- `agent/evals/cases.jsonl`
- `docs/architecture/foundry-ai-gateway-registration.md`

### Modified
- `agent/app/start_services.sh`
- `agent/app/Dockerfile`
- `agent/app/.env.example` — add `LUCY_GATEWAY_API_TOKEN` (if B.2.b chosen) and `LUCY_HTTP_PORT=8002`

## Open questions (resolved + remaining)

Resolved per https://learn.microsoft.com/en-us/azure/foundry/control-plane/register-custom-agent (2026-04-25):
- ~~Is the deployed AI Gateway APIM-backed or Foundry-managed?~~ → **APIM-backed**, free to set up via portal.
- ~~What protocol shape does the gateway forward in?~~ → **General HTTP** (or A2A); Lucy controls the request/response shape.
- ~~Does the Monitor tab populate from OTel traces emitted by Lucy?~~ → **Yes**, via App Insights, filtered by `gen_ai.agents.id` attribute.
- ~~Is managed identity required between gateway and Lucy?~~ → **No**, APIM is a transparent proxy; existing auth schema is preserved.

Remaining:
1. Does Foundry's eval SDK target Custom Agent registrations the same way it targets project-scoped agents? (Docs show the Traces panel works; eval-target wiring is documented separately and needs verification.)
2. What does the eval framework expect Lucy to return? (Doc shows LangGraph streaming; for our raw HTTP shape we may need to emit a streaming response or accept a synchronous one — TBD via portal eval setup.)
3. If we update the App Insights connection after registration, do we need to fully unregister and re-register? (Doc implies yes; confirm before any App Insights swap in production.)

## Acceptance criteria (overall)

- [ ] Lucy responds to a POST to the Foundry-managed Custom Agent URL.
- [ ] Foundry Monitor tab shows Lucy with traces, latency, and run history.
- [ ] At least one continuous eval rule produces scores visible in the portal.
- [ ] Existing Chainlit/HITL behavior unchanged.
- [ ] Existing prompt-agent Application URL still works (or has a documented retirement decision).
- [ ] Runbook in `docs/architecture/foundry-ai-gateway-registration.md` is complete and reproducible.
