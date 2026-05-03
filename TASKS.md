# TASKS.md

Current state: **prestable, barely**. Lucy Hosted is running and trace/agent metrics are landing, but the main ops dashboard is not yet reliable enough to call the Foundry migration complete.

## Read This First

- [ ] Start with `/state/refactor-ledger.md`, especially the `Hosted Agent RBAC/search/dashboard cleanup 2026-04-29` section.
- [ ] Treat `agent-lucy-hosted-ncus:12` as the current Hosted canary.
- [ ] Treat `agent-lucy-eus2` as the current member-facing Chainlit runtime.
- [ ] Do not delete or disable the EUS2 gateway/APIM bridge until Hosted proves full production parity.
- [ ] Use raw App Insights KQL and the Foundry Agent metrics surface as the current evidence path. The main ops dashboard is still not populated/reliable.

## Current Live Topology

- [x] Member UI/runtime is still in East US 2:
  - ACA: `agent-lucy-eus2`
  - RG: `agent-lucy-eus2`
  - App Insights: `agent-lucy-appins-eus2`
- [x] Hosted Agent canary is in North Central US:
  - Foundry account/project: `agent-lucy-foundry-ncus` / `agent-lucy-prj-ncus`
  - Hosted Agent: `agent-lucy-hosted-ncus:12`
  - ACR image: `agentlucyacrncus.azurecr.io/agent-lucy-hosted:hosted-pr2-20260503072101-convfix`
  - Model deployment: `gpt-5.2`
- [x] Hosted v12 smoke passed:
  - Response id: `caresp_4f0031a1cb5fec3d00XpJLlinob82htkJ88uOhm6l5enb9339R`
  - SDK status: `completed`
  - Error: `None`
- [x] Hosted v12 response retrieval passed for the same `caresp_...` id; the
  prior Hosted target-eval blank-output failure was caused by forwarding Hosted
  `conv_...` / `caresp_...` wrapper ids into the inner prompt agent.
- [x] Hosted v12 target evaluation passed:
  - Eval run: `evalrun_df11a3f7b4f3458b8e2d492d45be85b8`
  - Output text: `Lucy hosted target evaluation v12 is online.`
  - Result counts: `passed=1`, `failed=0`, `errored=0`
- [x] Hosted v12 telemetry should carry canonical agent attributes:
  - `gen_ai.agent.name=agent-lucy-hosted-ncus`
  - `gen_ai.agent.id=agent-lucy-hosted-ncus:12`
  - `gen_ai.agent.version=12`
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

- [ ] Confirm the main Foundry/App Insights ops dashboard starts populating after v12 traffic. Current status: not populated/reliable.
- [ ] Confirm the Agent-specific metrics surface continues to populate after multiple Hosted v12 runs.
- [ ] Re-test Hosted-targeted continuous evaluation after v12 traffic. A one-off Hosted target eval passed on 2026-05-03, but the old continuous response-eval rule has not yet produced a fresh post-v12 run.
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
- [ ] Build a COO-safe dashboard fallback using KQL/custom workbook if the preview ops dashboard remains flaky.
- [ ] Keep `AZURE_TRACING_GEN_AI_CONTENT_RECORDING_ENABLED=false` unless there is an explicit privacy-approved reason to enable content recording.
- [ ] Clean up duplicate/noisy logs only after functionality is stable. Current known noise: duplicate tool name warning for `send_handoff_notification_email_sync`.

## Next Agent Plan

- [ ] First, verify live v12 telemetry with KQL before editing code.
- [ ] Second, generate 3-5 Hosted v12 smoke calls and wait a few minutes for portal lag.
- [ ] Third, check these surfaces in order:
  - Foundry Agent metrics for `agent-lucy-hosted-ncus`
  - App Insights raw traces/dependencies/requests
  - main App Insights/Foundry ops dashboard
  - continuous eval runs
- [ ] Fourth, if main ops dashboard is still blank but raw telemetry and Agent metrics are present, treat it as a portal/workbook issue and create a custom KQL workbook for the COO demo.
- [ ] Fifth, only after observability is acceptable, test full notice-auth-PDF-HITL parity through Hosted.
- [ ] Sixth, write the result back to `/state/refactor-ledger.md` with exact resource names, response ids, KQL evidence, and remaining blockers.
