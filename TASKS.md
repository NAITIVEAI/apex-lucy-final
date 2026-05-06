# TASKS.md

Current state: **prestable, improving**. Lucy Hosted v20 is running on the chat-model lane, raw trace/agent metrics and App Insights telemetry are landing, and the member-facing EUS2 runtime is healthy; the preview ops dashboard / Foundry migration is still not fully reliable.

## Read This First

- [ ] Start with `/state/refactor-ledger.md`, especially the `Hosted Agent RBAC/search/dashboard cleanup 2026-04-29` section.
- [ ] Treat `agent-lucy-hosted-ncus:20` as the current Hosted canary.
- [ ] Treat `agent-lucy-eus2` as the current member-facing Chainlit runtime.
- [ ] The EUS2 AI Gateway/APIM bridge has been retired and deleted; do not rebuild it unless Hosted is explicitly abandoned again.
- [ ] Use raw App Insights KQL and the Foundry Agent metrics surface as the current evidence path. The main ops dashboard is still not populated/reliable.

## Current Live Topology

- [x] Member UI/runtime is still in East US 2:
  - ACA: `agent-lucy-eus2`
  - RG: `agent-lucy-eus2`
  - App Insights: `agent-lucy-appins-eus2`
  - Current revision: `agent-lucy-eus2--0000069`
- [x] Hosted Agent canary is in North Central US:
  - Foundry account/project: `agent-lucy-foundry-ncus` / `agent-lucy-prj-ncus`
  - Hosted Agent: `agent-lucy-hosted-ncus:20`
  - Inner prompt agent used by the hosted runtime: `agent-lucy-prod:6`
  - ACR image: `agentlucyacrncus.azurecr.io/agent-lucy-hosted:hosted-pr2-20260504102638-operatechatspan`
  - Model deployment: `gpt-5.2-chat`
- [x] Hosted v20 smoke passed:
  - Latest response ids:
    `caresp_2fb55937c05798c300kxfQqrvat8JXYmHvNWqKUzsyX7mod9So`,
    `caresp_e811045ec9aa75f800glxnGnPg3DrjkDqQvVgPtZldzjPSU3m7`,
    `caresp_047e6e12f038fcb000TgWEPiFxHIXJPMgC107spcN8f8JtfF4K`
  - SDK status: `completed`
  - Output: `Lucy hosted operate chat span online.`
- [x] Hosted v13 target evaluation passed on 2026-05-03:
  - Eval run: `evalrun_b03b7e0521e642c6986d3e84e10b65a3`
  - Result counts: `passed=1`, `failed=0`, `errored=0`
- [x] Hosted v20 telemetry carries canonical agent attributes, provider, model, token usage, workbook-compatible `chat` spans, and GenAI client metrics:
  - `gen_ai.agent.name=agent-lucy-hosted-ncus`
  - `gen_ai.agent.id=agent-lucy-hosted-ncus:20`
  - `gen_ai.agent.version=20`
  - `gen_ai.provider.name=azure.ai.foundry`
  - `gen_ai.response.model=gpt-5.2-chat`
  - `gen_ai.usage.total_tokens` populated on the hosted `create_agent` and `chat` spans
  - `gen_ai.client.token.usage` and `gen_ai.client.operation.duration` exported to App Insights custom metrics
- [x] KQL-backed COO workbook exists:
  - Display name: `Lucy Hosted COO Monitor`
  - Resource: `/subscriptions/22f9f915-587f-4a9a-acff-69b061ef48e1/resourcegroups/agent-lucy-eus2/providers/microsoft.insights/workbooks/d93d5898-c385-40ff-978e-eea3dbf03332`
- [x] Hosted runtime identity has the missing Foundry write permission:
  - Principal: `bf64d26c-34a5-4bc8-a1b2-b22e9ff24b67`
  - Role: `Azure AI Project Manager`
  - Scope: NCUS Foundry project
- [x] Portal agent map for NCUS:
  - `agent-lucy-hosted-ncus` is the hosted runtime/container wrapper.
  - `agent-lucy-prod` is the prompt agent the hosted runtime calls for Lucy reasoning/tools.
  - Both are expected. Do not delete either one during demo prep.
- [x] Retired EUS2 gateway/APIM bridge:
  - EUS2 still has legacy prompt/custom-gateway assets such as `agent-lucy-prod`, `ApexAgentLucy`, and `lucy-chat-v2`.
  - APIM `apexclassaction-ai-gw` and gateway ACA `agent-lucy-gateway-eus2` were deleted on 2026-05-04 after Hosted v20 became the selected route.
- [x] Hosted startup no longer shows:
  - `AuthorizationFailed`
  - missing `Microsoft.CognitiveServices/accounts/projects/applications/write`
  - `search_connection_id_set=false`
  - `Failed to setup dashboard routes: 'app'`

## What Still Needs Work

- [ ] Confirm the main Foundry/App Insights ops dashboard starts populating after v20 traffic. Current status: not populated/reliable.
- [ ] Confirm the Agent-specific metrics surface continues to populate after multiple Hosted v20 runs.
- [ ] Re-test Hosted-targeted continuous evaluation after v20 traffic. A one-off Hosted target eval passed on 2026-05-03, but the old continuous response-eval rule has not yet produced a fresh post-v20 run.
- [ ] Run a real Hosted canary for the notice path:
  - starter intent: explain notice
  - auth
  - notice retrieval
  - PDF artifact/metadata
  - 4+ minute idle/reconnect continuity
  - handoff path
- [ ] Decide region consolidation. The current split is EUS2 member runtime + NCUS Hosted/Foundry because EUS2 Hosted was unavailable. If Hosted is the production path, it may make sense to consolidate runtime-adjacent resources into the Hosted-supported region, but verify latency, model availability, App Insights linkage, storage/search dependencies, and compliance before moving anything.
- [ ] Decide Chainlit cutover strategy:
  - keep Chainlit in EUS2 and call Hosted NCUS, or
  - move Chainlit/runtime into the same supported region as Hosted, or
  - keep Hosted as eval/observability canary until Microsoft supports EUS2 Hosted.
- [x] Build a COO-safe dashboard fallback using KQL/custom workbook if the preview ops dashboard remains flaky:
  - Azure Monitor workbook: `Lucy Hosted COO Monitor`
  - Workbook resource: `/subscriptions/22f9f915-587f-4a9a-acff-69b061ef48e1/resourceGroups/agent-lucy-eus2/providers/Microsoft.Insights/workbooks/d93d5898-c385-40ff-978e-eea3dbf03332`
  - Verified on 2026-05-04 with Hosted v20 KQL results. Latest recheck:
    App Insights `requests` 7-day window returned `18` runs, `18`
    successes, `0` failures; Log Analytics `AppRequests` 24-hour window
    returned `10` runs, `10` successes, `0` failures.
- [ ] Keep `AZURE_TRACING_GEN_AI_CONTENT_RECORDING_ENABLED=false` unless there is an explicit privacy-approved reason to enable content recording.
- [ ] Clean up duplicate/noisy logs only after functionality is stable. Current known noise: duplicate tool name warning for `send_handoff_notification_email_sync`.
- [ ] Move or rotate secret-bearing Hosted Agent environment settings after the COO demo path is safe. Current Hosted version definitions copied runtime env into immutable version metadata.

## Next Agent Plan

- [x] First, verify live v20 telemetry with KQL before editing code.
- [x] Second, generate 3-5 Hosted v20 smoke calls and wait a few minutes for portal lag.
- [ ] Third, check these surfaces in order:
  - Foundry Agent metrics for `agent-lucy-hosted-ncus`
  - App Insights raw traces/dependencies/requests
  - main App Insights/Foundry ops dashboard
  - continuous eval runs
- [x] Fourth, if main ops dashboard is still blank but raw telemetry and Agent metrics are present, treat it as a portal/workbook issue and use the `Lucy Hosted COO Monitor` custom KQL workbook for the COO demo.
- [ ] Fifth, only after observability is acceptable, test full notice-auth-PDF-HITL parity through Hosted.
- [ ] Sixth, write the result back to `/state/refactor-ledger.md` with exact resource names, response ids, KQL evidence, and remaining blockers.
