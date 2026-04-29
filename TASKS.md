# TASKS.md

Current state: **prestable, barely**. Lucy Hosted is running and trace/agent metrics are landing, but the main ops dashboard is not yet reliable enough to call the Foundry migration complete.

## Read This First

- [ ] Start with `/state/refactor-ledger.md`, especially the `Hosted Agent RBAC/search/dashboard cleanup 2026-04-29` section.
- [ ] Treat `agent-lucy-hosted-ncus:8` as the current Hosted canary.
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
  - Hosted Agent: `agent-lucy-hosted-ncus:8`
  - ACR image: `agentlucyacrncus.azurecr.io/agent-lucy-hosted:hosted-20260429051054-rbac-dashboard`
  - Model deployment: `gpt-5.2`
- [x] Hosted v8 smoke passed:
  - Response id: `caresp_e39cb37ecf44b94e00mYcReQTjjYUncDkYOEfos8b2puEO5mrd`
  - SDK status: `completed`
  - Error: `None`
- [x] Hosted v8 telemetry has canonical agent attributes:
  - `gen_ai.agent.name=agent-lucy-hosted-ncus`
  - `gen_ai.agent.id=agent-lucy-hosted-ncus:8`
  - `gen_ai.agent.version=8`
- [x] Hosted runtime identity has the missing Foundry write permission:
  - Principal: `bf64d26c-34a5-4bc8-a1b2-b22e9ff24b67`
  - Role: `Azure AI Project Manager`
  - Scope: NCUS Foundry project
- [x] Hosted v8 startup no longer shows:
  - `AuthorizationFailed`
  - missing `Microsoft.CognitiveServices/accounts/projects/applications/write`
  - `search_connection_id_set=false`
  - `Failed to setup dashboard routes: 'app'`

## What Still Needs Work

- [ ] Confirm the main Foundry/App Insights ops dashboard starts populating after v8 traffic. Current status: not populated/reliable.
- [ ] Confirm the Agent-specific metrics surface continues to populate after multiple Hosted v8 runs.
- [ ] Re-test Hosted-targeted continuous evaluation. Previous blocker was `403 session_not_accessible`; RBAC and publication reconciliation are now improved, but eval success is not yet re-proven.
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

- [ ] First, verify live v8 telemetry with KQL before editing code.
- [ ] Second, generate 3-5 Hosted v8 smoke calls and wait a few minutes for portal lag.
- [ ] Third, check these surfaces in order:
  - Foundry Agent metrics for `agent-lucy-hosted-ncus`
  - App Insights raw traces/dependencies/requests
  - main App Insights/Foundry ops dashboard
  - continuous eval runs
- [ ] Fourth, if main ops dashboard is still blank but raw telemetry and Agent metrics are present, treat it as a portal/workbook issue and create a custom KQL workbook for the COO demo.
- [ ] Fifth, only after observability is acceptable, test full notice-auth-PDF-HITL parity through Hosted.
- [ ] Sixth, write the result back to `/state/refactor-ledger.md` with exact resource names, response ids, KQL evidence, and remaining blockers.
