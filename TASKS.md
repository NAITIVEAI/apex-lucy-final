# TASKS.md

Current state: **prestable, improving**. Lucy Hosted v22 is active and the
member-facing EUS2 runtime is healthy. Prior v21 raw App Insights telemetry has
hosted `create_agent` plus Operate-workbook-compatible `chat` model/token usage;
fresh v22 raw telemetry was not visible in the short post-deploy query window.
The built-in preview Foundry ops dashboard is still not reliable enough to call
the Foundry migration complete; use App Insights KQL and the
`Lucy Hosted COO Monitor` workbook as the verified portal evidence path unless
the native Operate cards start showing usable run/cost/success/token evidence.

## Read This First

- [ ] Start with `/state/refactor-ledger.md`, especially the `Hosted Agent RBAC/search/dashboard cleanup 2026-04-29` section.
- [ ] Treat `agent-lucy-hosted-ncus:22` as the current Hosted canary.
- [ ] Treat `agent-lucy-eus2` as the current member-facing Chainlit runtime.
- [ ] The EUS2 AI Gateway/APIM bridge has been retired and deleted; do not rebuild it unless Hosted is explicitly abandoned again.
- [ ] Use raw App Insights KQL, Foundry Agent metrics where populated, and the
  `Lucy Hosted COO Monitor` workbook as the current evidence path. The main
  native ops dashboard is still not populated/reliable.

## Current Live Topology

- [x] Member UI/runtime is still in East US 2:
  - ACA: `agent-lucy-eus2`
  - RG: `agent-lucy-eus2`
  - App Insights: `agent-lucy-appins-eus2`
  - Current revision: `agent-lucy-eus2--0000071`
  - Current image: `agentlucyacreus2.azurecr.io/agent-lucy-eus2:main-ed5d2a2-20260507063412`
- [x] Hosted Agent canary is in North Central US:
  - Foundry account/project: `agent-lucy-foundry-ncus` / `agent-lucy-prj-ncus`
  - Hosted Agent: `agent-lucy-hosted-ncus:22`
  - Current ACR image: `agentlucyacrncus.azurecr.io/agent-lucy-hosted:hosted-main-ed5d2a2-20260507063412`
  - Model deployment: `gpt-5.2-chat`
  - Inner prompt agent used by the hosted runtime: `agent-lucy-prod:8`
- [x] Generic notice sync job is live in West US:
  - Container App Job: `lucy-generic-notice-sync`
  - Resource group: `rg-apex-integration-prod`
  - Current image: `acrapexintegrationprod.azurecr.io/generic-notice-sync:generic-notice-sync-ed5d2a2-20260507063412`
  - Schedule: `15 3 * * *`
- [x] Hosted v22 smoke passed on 2026-05-07:
  - Response id: `caresp_ed298900f7ae4fc700dBXFaKoaB7vdEGtRya8Y99vMeLKE8Wdu`
  - SDK status: `completed`
  - Error: `None`
- [x] Hosted v21 smoke passed on 2026-05-06:
  - Latest response ids:
    `caresp_65a1ddd2d4dcc73700KUIfwqFoHdZZJLFBxGfSc8HTMpmdNo1s`,
    `caresp_b41756284523295400kHMouXPVPnbF9ek9IBxWU37rbrScSIkE`,
    `caresp_c0208595c364d6f400q3jDeh60dxrZ3GxpX6B9kyzEP8AjuyAp`,
    `caresp_ff39db10110eda0000IEoPzSeV3jwlQdOTX1qc6lE0d76uQGGw`
  - SDK status: `completed`
  - REST response retrieval returned assistant messages:
    `Lucy May 6 portal telemetry smoke N is alive.`
- [x] Hosted v13 target evaluation passed on 2026-05-03:
  - Eval run: `evalrun_b03b7e0521e642c6986d3e84e10b65a3`
  - Result counts: `passed=1`, `failed=0`, `errored=0`
- [x] Hosted v21 telemetry carries canonical agent attributes, provider, model, token usage, workbook-compatible `chat` spans, and GenAI client metrics:
  - `gen_ai.agent.name=agent-lucy-hosted-ncus`
  - `gen_ai.agent.id=agent-lucy-hosted-ncus:21`
  - `gen_ai.agent.version=21`
  - `gen_ai.provider.name=azure.ai.foundry`
  - `gen_ai.response.model=gpt-5.2-chat`
  - `gen_ai.usage.total_tokens` populated on the hosted `create_agent` and `chat` spans
  - `gen_ai.client.token.usage` and `gen_ai.client.operation.duration` exported to App Insights custom metrics
  - `chat gpt-5.2-chat-2025-12-11`
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
  - APIM `apexclassaction-ai-gw` and gateway ACA `agent-lucy-gateway-eus2` were deleted on 2026-05-04 after Hosted became the selected route.
- [x] Hosted startup no longer shows:
  - `AuthorizationFailed`
  - missing `Microsoft.CognitiveServices/accounts/projects/applications/write`
  - `search_connection_id_set=false`
  - `Failed to setup dashboard routes: 'app'`

## What Still Needs Work

- [ ] Confirm the main Foundry/App Insights ops dashboard starts populating after v21 traffic. Current status: not populated/reliable.
- [ ] Confirm the Agent-specific metrics surface continues to populate visually after multiple Hosted v21 runs.
- [ ] User decision needed for production evidence gate:
  - Option A: explicitly approve quitting/relaunching Chrome Profile 1 to enable
    `Allow JavaScript from Apple Events`, then retry logged-in Foundry
    Operate/Monitor page inspection.
  - Option B: accept native `Traces > Conversations` plus App Insights /
    `Lucy Hosted COO Monitor` workbook as the production portal proof path and
    treat native Operate/Monitor cards as a Microsoft preview metric-rollup
    blocker.
- [ ] Re-test Hosted-targeted continuous evaluation after v21 traffic. A one-off Hosted target eval passed on 2026-05-03, but the old continuous response-eval rule has not yet produced a fresh post-v21 run.
- [x] Native Foundry visual proof captured on 2026-05-06. Current status after
  v21:
  App Insights has valid hosted `create_agent` and
  Operate-workbook-compatible `chat` usage rows, and the workbook-shaped KQL
  returns non-zero rows/tokens. The project metrics namespace still
  returned zero `AgentResponses` / `AgentInputTokens` / `AgentOutputTokens` /
  `AgentRuns` / `AgentToolCalls` series for the fresh May 6 v21 smoke window,
  while the Foundry account model metrics returned non-zero `ModelRequests`,
  `InputTokens`, `OutputTokens`, and `TotalTokens` for the same smoke window.
  A temporary Hosted Agent Application route for `agent-lucy-hosted-ncus:21`
  was created, reached Running, and was then removed after the live
  application-scoped Responses endpoint rejected Hosted agent invocation with
  `Application-scoped routes only support prompt agents`.
  The existing prompt-agent Application route
  `agent-lucy-prod/protocols/openai/responses` completed a control smoke on
  `agent-lucy-prod:8` and moved Foundry account model metrics, but project
  Agent metrics still stayed zero for the same current window. A resumed
  2026-05-06 check confirmed the logged-in Chrome browser has the Foundry
  Operate and COO workbook tabs open, the project has a default App Insights
  connection, the signed-in user and project managed identity have the
  documented App Insights / Log Analytics access, and fresh Hosted plus
  prompt-application calls still leave project Agent metrics at zero. Treat the
  project Agent metric rollup itself as blocked/unreliable for this project.
  CuaDriver then attached to the logged-in Foundry Chrome window, selected
  `agent-lucy-prj-ncus`, and confirmed the Operate overview shows `Running
  agents` as `1/2 agents` while cost, success-rate, token-usage, run-volume,
  and trend surfaces still show no data. The same visual pass opened the Assets
  table and Hosted Agent Monitor page: `agent-lucy-hosted-ncus` appears as
  status `Unknown`, version `21`, blank cost/token/runs, and its Monitor tab
  shows `Estimated cost $0` plus `Total token usage 0` for the 1-month range.
  Monitor settings show App Insights connected to `agent-lucy-appins-eus2`;
  the disabled toggles are evaluation-related. The native `Traces >
  Conversations` tab is populated and shows completed Hosted v21 response rows
  with response ids, durations, token-in/out counts, and agent version 21; the
  latest visible row after the final direct Hosted proof smoke is
  `caresp_52181c90d41c7cb5000Rm8Mly6EKzH9K81JVEeJ7h2gV21MIi2`, status
  `Completed`, created `5/6/26, 7:24:40 AM`, duration `7.871`, tokens in
  `18728`, tokens out `140`, agent version `21`. The prior fresh row is
  `caresp_ff39db10110eda0000IEoPzSeV3jwlQdOTX1qc6lE0d76uQGGw`, status
  `Completed`, duration `8.736`, tokens in `18720`, tokens out `384`. Do not
  claim the native Build/Operate cards are fixed without non-zero project Agent
  metrics or a newer visual check showing populated cards.
  Resume recheck at 2026-05-06 14:33 UTC confirmed Chrome is still logged in on
  the Hosted Agent Monitor URL, but current CuaDriver capture is blocked by a
  ScreenCaptureKit audio/video stream failure even though CuaDriver reports
  Accessibility and Screen Recording as granted and can see the Chrome window.
  JavaScript-from-Apple-Events and Chrome DevTools attachment are also not
  available. The Azure evidence still reproduces the split for response
  `caresp_52181c90d41c7cb5000Rm8Mly6EKzH9K81JVEeJ7h2gV21MIi2`: App Insights
  request/dependency rows are present, Foundry account metrics moved
  (`ModelRequests=1`, `InputTokens=4682`, `OutputTokens=35`,
  `TotalTokens=4717`), and Foundry project Agent metrics remain zero.
  Computer Use then successfully read the authenticated local Chrome Foundry
  session. It confirmed the project Operate overview still shows no data for
  estimated cost, agent success rate, token usage, agent run volume, and
  success trend cards, and the Hosted Agent Monitor tab still shows
  `Estimated cost $0` plus `Total token usage 0` for `agent-lucy-hosted-ncus`.
- [ ] Run a real Hosted canary for the notice path:
  - starter intent: explain notice
  - auth
  - notice retrieval
  - PDF artifact/metadata
  - 4+ minute idle/reconnect continuity
  - handoff path
- [ ] Implement the tiered notice retrieval strategy captured in
  `/state/notice-retrieval-strategy.md`:
  - authenticate first
  - attempt individualized notice lookup from the existing PDF corpus
  - fall back to the generic notice under `Print/Notice packet`
  - copy only generic case notice PDFs from SharePoint into the existing
    indexed blob path; do not restore the old all-member Mail Merged PDF sync
  - explain generic fallback in simple grounded language
  - enrich with allowed Dynamics member fields such as estimated amount, total
    class counts, class count metric, PAGA counts/metric when relevant, and
    status context
  - log `individual_notice` vs `generic_notice_fallback`
- [ ] Decide region consolidation. The current split is EUS2 member runtime + NCUS Hosted/Foundry because EUS2 Hosted was unavailable. If Hosted is the production path, it may make sense to consolidate runtime-adjacent resources into the Hosted-supported region, but verify latency, model availability, App Insights linkage, storage/search dependencies, and compliance before moving anything.
- [ ] Decide Chainlit cutover strategy:
  - keep Chainlit in EUS2 and call Hosted NCUS, or
  - move Chainlit/runtime into the same supported region as Hosted, or
  - keep Hosted as eval/observability canary until Microsoft supports EUS2 Hosted.
- [x] Build a COO-safe dashboard fallback using KQL/custom workbook if the preview ops dashboard remains flaky:
  - Azure Monitor workbook: `Lucy Hosted COO Monitor`
  - Workbook resource: `/subscriptions/22f9f915-587f-4a9a-acff-69b061ef48e1/resourceGroups/agent-lucy-eus2/providers/Microsoft.Insights/workbooks/d93d5898-c385-40ff-978e-eea3dbf03332`
  - Verified on 2026-05-06 with Hosted v21 KQL results. Latest recheck:
    App Insights `requests` 24-hour window returned `6` rows, `6`
    successes, `0` failures for `agent-lucy-hosted-ncus:21`; dependency rows
    returned `create_agent`, hosted `chat`, `invoke_agent agent-lucy-prod:8`,
    and `chat gpt-5.2-chat-2025-12-11` with Hosted token totals.
- [ ] Keep `AZURE_TRACING_GEN_AI_CONTENT_RECORDING_ENABLED=false` unless there is an explicit privacy-approved reason to enable content recording.
- [ ] Clean up duplicate/noisy logs only after functionality is stable. Current known noise: duplicate tool name warning for `send_handoff_notification_email_sync`.
- [ ] Move or rotate secret-bearing Hosted Agent environment settings after the COO demo path is safe. Current Hosted version definitions copied runtime env into immutable version metadata.

## Next Agent Plan

- [x] First, verify live v21 telemetry with KQL before editing code.
- [x] Second, generate 3 Hosted v21 smoke calls and wait for ingestion.
- [x] Third, check these surfaces in order:
  - Foundry Agent metrics for `agent-lucy-hosted-ncus`
  - App Insights raw traces/dependencies/requests
  - main App Insights/Foundry ops dashboard
  - continuous eval runs
- [x] Fourth, if main ops dashboard is still blank but raw telemetry and Agent metrics are present, treat it as a portal/workbook issue and use the `Lucy Hosted COO Monitor` custom KQL workbook for the COO demo.
- [ ] Fifth, only after observability is acceptable, test full notice-auth-PDF-HITL parity through Hosted.
- [x] Sixth, write the result back to `/state/refactor-ledger.md` with exact resource names, response ids, KQL evidence, and remaining blockers.
