# TASKS.md

Current state: **prestable, barely**. Lucy Hosted v20 is running and raw App Insights telemetry now has hosted `create_agent` plus Operate-workbook-compatible `chat` model/token usage. The older native Foundry Build Monitor cards still show zero usage because the preview project-metrics namespace remains empty. Use App Insights KQL / the COO workbook as the verified evidence path until visual portal proof is captured.

## Read This First

- [ ] Start with `/state/refactor-ledger.md`, especially the `Hosted Agent RBAC/search/dashboard cleanup 2026-04-29` section.
- [ ] Treat `agent-lucy-hosted-ncus:20` as the current Hosted canary.
- [ ] Treat `agent-lucy-eus2` as the current member-facing Chainlit runtime.
- [ ] Do not delete or disable the EUS2 gateway/APIM bridge until Hosted proves full production parity.
- [ ] Use raw App Insights KQL and the `Lucy Hosted COO Monitor` workbook as the current evidence path. The native Foundry Monitor tab is still not populated/reliable.

## Current Live Topology

- [x] Member UI/runtime is still in East US 2:
  - ACA: `agent-lucy-eus2`
  - RG: `agent-lucy-eus2`
  - App Insights: `agent-lucy-appins-eus2`
- [x] Hosted Agent canary is in North Central US:
  - Foundry account/project: `agent-lucy-foundry-ncus` / `agent-lucy-prj-ncus`
  - Hosted Agent: `agent-lucy-hosted-ncus:20`
  - ACR image: `agentlucyacrncus.azurecr.io/agent-lucy-hosted:hosted-pr2-20260504102638-operatechatspan`
  - Model deployment: `gpt-5.2-chat`
  - Inner prompt agent: `agent-lucy-prod:6`
- [x] Hosted v18 smoke passed:
  - Response ids: `caresp_6e3cef1977800ae8001mKvC6cTbwaufx0M38O9OaTg685nkgNU`, `caresp_2abfdd0d9cda8e7e00HgyEXzdoZhd211nSW7bHFzxkeMG3uEDf`, `caresp_9d6af8231fea912200m0bdCxUuf9yyXpimyhR961t0Rpe4Ber7`
  - SDK status: `completed`
  - Error: `None`
- [x] Fresh Hosted v20 Operate telemetry SDK smoke passed on 2026-05-04:
  - Response id: `caresp_2fb55937c05798c300kxfQqrvat8JXYmHvNWqKUzsyX7mod9So`
  - SDK status: `completed`
  - Error: `None`
  - Output: `Lucy hosted operate chat span online.`
- [x] Hosted v13 response retrieval passed for the same `caresp_...` id; the
  prior Hosted target-eval blank-output failure was caused by forwarding Hosted
  `conv_...` / `caresp_...` wrapper ids into the inner prompt agent.
- [x] Hosted v13 target evaluation passed:
  - Eval run: `evalrun_b03b7e0521e642c6986d3e84e10b65a3`
  - Output text: `The Lucy-hosted Target Evaluation v13 chat is now online.`
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
- [x] Hosted startup no longer shows:
  - `AuthorizationFailed`
  - missing `Microsoft.CognitiveServices/accounts/projects/applications/write`
  - `search_connection_id_set=false`
  - `Failed to setup dashboard routes: 'app'`

## What Still Needs Work

- [ ] Native Foundry visual proof still needs closure. Current status after v20: App Insights has valid hosted `create_agent` and Operate-workbook-compatible `chat` usage rows, and the workbook-shaped KQL returns non-zero rows/tokens. The older project metrics namespace still returns zero `AgentResponses` / `AgentInputTokens` / `AgentOutputTokens` / `AgentRuns` / `AgentToolCalls` series immediately after fresh SDK traffic, so do not claim the Build Monitor cards are fixed without a fresh screenshot.
- [x] Build a COO-safe dashboard fallback using KQL/custom workbook while the preview ops dashboard remains flaky.
- [ ] Re-test Hosted-targeted continuous evaluation after v15 traffic. A one-off Hosted target eval passed on 2026-05-03 for v13, but the old continuous response-eval rule has not yet produced a fresh post-v15 run.
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
- [ ] Keep `AZURE_TRACING_GEN_AI_CONTENT_RECORDING_ENABLED=false` unless there is an explicit privacy-approved reason to enable content recording.
- [ ] Clean up duplicate/noisy logs only after functionality is stable. Current known noise: duplicate tool name warning for `send_handoff_notification_email_sync`.

## Next Agent Plan

- [x] First, verify live v13 telemetry with KQL before editing code.
- [x] Second, generate 3-5 Hosted v18 smoke calls and wait a few minutes for portal lag.
- [ ] Third, check these surfaces in order:
  - Foundry Agent metrics for `agent-lucy-hosted-ncus`
  - App Insights raw traces/dependencies/requests
  - main App Insights/Foundry ops dashboard
  - continuous eval runs
- [x] Fourth, if main ops dashboard is still blank but raw telemetry and Agent metrics are present, treat it as a portal/workbook issue and create a custom KQL workbook for the COO demo.
- [ ] Fifth, after the workbook fallback is reviewed as acceptable, test full notice-auth-PDF-HITL parity through Hosted.
- [x] Sixth, write the result back to `/state/refactor-ledger.md` with exact resource names, response ids, KQL evidence, and remaining blockers.
