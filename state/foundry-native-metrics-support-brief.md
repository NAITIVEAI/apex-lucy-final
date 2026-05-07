# Foundry Native Metrics Support Brief

Last updated: 2026-05-06

## Issue

Lucy Hosted Agent traffic executes successfully and emits telemetry to the
Application Insights resource connected to the Foundry project, but Azure
Monitor project Agent metrics remain zero. This prevents the native Foundry
Operate / Build Agent monitor cards from being accepted as production evidence.

## Resources

- Subscription: `22f9f915-587f-4a9a-acff-69b061ef48e1`
- Foundry account:
  `/subscriptions/22f9f915-587f-4a9a-acff-69b061ef48e1/resourceGroups/agent-lucy-ncus/providers/Microsoft.CognitiveServices/accounts/agent-lucy-foundry-ncus`
- Foundry project:
  `/subscriptions/22f9f915-587f-4a9a-acff-69b061ef48e1/resourceGroups/agent-lucy-ncus/providers/Microsoft.CognitiveServices/accounts/agent-lucy-foundry-ncus/projects/agent-lucy-prj-ncus`
- Application Insights:
  `/subscriptions/22f9f915-587f-4a9a-acff-69b061ef48e1/resourceGroups/agent-lucy-eus2/providers/Microsoft.Insights/components/agent-lucy-appins-eus2`
- Hosted Agent: `agent-lucy-hosted-ncus:21`
- Prompt-agent control: `agent-lucy-prod:8`

## Reproduction Window

2026-05-06 13:35-13:50 UTC.

Calls made:

- Direct Hosted Responses endpoint:
  `caresp_ff39db10110eda0000IEoPzSeV3jwlQdOTX1qc6lE0d76uQGGw`
- Prompt-agent Application route:
  `resp_02daf5317b79b4350169fb452942c081909de28df403ce1840`

Both calls returned `status=completed` and `error=null`.

## Positive Evidence

Application Insights ingested current rows for:

- `invoke_agent agent-lucy-hosted-ncus:21`
- Hosted `create_agent`
- Hosted `chat`
- `invoke_agent agent-lucy-prod:8`
- `chat gpt-5.2-chat-2025-12-11`

The Hosted rows include:

- `microsoft.foundry.project.id` set to the NCUS Foundry project resource ID
- `gen_ai.agent.name=agent-lucy-hosted-ncus`
- `gen_ai.agent.id=agent-lucy-hosted-ncus:21`
- `gen_ai.agent.version=21`
- `gen_ai.provider.name=azure.ai.foundry`
- `gen_ai.system=azure.ai.foundry`
- token usage attributes on Hosted `create_agent` / `chat`

Foundry account metrics for the same 2026-05-06 13:35-13:50 UTC window moved:

- `ModelRequests=1`
- `InputTokens=4680`
- `OutputTokens=96`
- `TotalTokens=4776`

## Telemetry Shape Check

Live App Insights KQL after the portal inspection confirmed the deployed v21
telemetry is not missing the primary Foundry identity dimensions:

- Hosted request row:
  - name `invoke_agent agent-lucy-hosted-ncus:21`
  - `gen_ai.operation.name=invoke_agent`
  - `gen_ai.system=azure.ai.agentserver`
  - `gen_ai.provider.name=AzureAI Hosted Agents`
  - `gen_ai.agent.name=agent-lucy-hosted-ncus`
  - `gen_ai.agent.id=agent-lucy-hosted-ncus:21`
  - `gen_ai.agent.version=21`
  - `microsoft.foundry.project.id` set to the NCUS project resource ID
- Hosted dependency rows:
  - names `create_agent` and `chat`
  - `gen_ai.operation.name=create_agent` / `chat`
  - `gen_ai.provider.name=azure.ai.foundry`
  - `gen_ai.system=azure.ai.foundry`
  - `gen_ai.request.model=gpt-5.2-chat`
  - `gen_ai.response.model=gpt-5.2-chat`
  - `gen_ai.usage.input_tokens=4680`
  - `gen_ai.usage.output_tokens=96`
  - `gen_ai.usage.total_tokens=4776`
  - `gen_ai.agent.name=agent-lucy-hosted-ncus`
  - `gen_ai.agent.id=agent-lucy-hosted-ncus:21`
  - `gen_ai.agent.version=21`
  - `microsoft.foundry.project.id` set to the NCUS project resource ID

This rules out the earlier suspected local-code mismatch where
`gen_ai.agent.name` might have included the version suffix in deployed traces.

## Failing Evidence

Foundry project metrics for the same 2026-05-06 13:35-13:50 UTC window stayed
at zero for:

- `AgentResponses`
- `AgentInputTokens`
- `AgentOutputTokens`
- `AgentRuns`
- `AgentToolCalls`
- project-level `InputTokens`
- project-level `OutputTokens`
- project-level `TotalTokens`

This was reproduced with both direct Hosted traffic and a prompt-agent
Application control. The issue is therefore not explained solely by the direct
Hosted endpoint.

## Control-Plane Checks

- Project App Insights connection:
  - name `agentlucyappinseus2dq5t8e`
  - category `AppInsights`
  - target `agent-lucy-appins-eus2`
  - `isDefault=true`
  - `error=null`
- Signed-in Azure user has inherited subscription monitor/log permissions,
  including `Owner`, `Monitoring Contributor`, and `Log Analytics Contributor`.
- Foundry project managed identity
  `d4f3d82d-0056-4e6f-93f8-d1be9b049d94` has:
  - `Log Analytics Reader` on `agent-lucy-appins-eus2`
  - `Log Analytics Reader` on the managed App Insights workspace
  - `Log Analytics Data Reader` on the managed App Insights workspace
- Hosted runtime identity
  `bf64d26c-34a5-4bc8-a1b2-b22e9ff24b67` has:
  - `Azure AI User` on the NCUS Foundry project
  - `Azure AI Project Manager` on the NCUS Foundry project

## Local Browser State

CuaDriver confirmed the logged-in Chrome window is inspectable:

```text
Chrome pid: 65519
Window id: 6335
Title: Microsoft Foundry - Google Chrome - Chris
Url: https://ai.azure.com/nextgen/r/Ivn5FVh_Spqs_2mwYe9I4Q,agent-lucy-ncus,,agent-lucy-foundry-ncus,agent-lucy-prj-ncus/operate/overview
```

The project selector exposed options for `All projects`, `agent-lucy-prj-eus2`,
and `agent-lucy-prj-ncus`. After selecting `agent-lucy-prj-ncus`, the Operate
overview Accessibility tree showed:

- `Running agents`: `1/2 agents`
- `Estimated cost`: `No data to show`
- `Agent success rate`: `No data to show`
- `Token usage`: `No data to show`
- `Agent run volume over time`:
  `No data available for the selected time range. Please select a different time range.`
- `Agent run volume` top increases/decreases: `No data to show`
- `Agent success rate` chart:
  `No data available for the selected time range. Please select a different time range.`
- `Agent run success rate trends` top increases/decreases: `No data to show`
- active alert row:
  `HIGH Out of Compliance Policy Alert agent-lucy-foundry-eus2 Policy Review`

Prior terminal-level approaches were blocked (`screencapture`, Chrome
AppleScript JavaScript, Chrome DevTools attach, and direct Quartz capture), but
CuaDriver provided both screenshot dimensions and page Accessibility content for
the logged-in browser window.

## Agent-Specific Portal State

The same logged-in Chrome session was used to open the Operate Assets table and
the Hosted Agent Monitor page.

Assets table for project `agent-lucy-prj-ncus`:

- `agent-lucy-hosted-ncus`: Source `Foundry`, Status `Unknown`, Version `21`,
  Published as `--`, Error rate `--`, Estimated cost `--`, Token usage `--`,
  Runs `--`, Monitoring features `1/3 enabled`
- `agent-lucy-prod`: Source `Foundry`, Status `Running`, Version `8`, Published
  as `agent-lucy-prod`, Error rate `--`, Estimated cost `$0.00`, Token usage
  `--`, Runs `--`, Monitoring features `1/3 enabled`

Hosted agent Monitor URL:

```text
https://ai.azure.com/nextgen/r/Ivn5FVh_Spqs_2mwYe9I4Q,agent-lucy-ncus,,agent-lucy-foundry-ncus,agent-lucy-prj-ncus/build/agents/agent-lucy-hosted-ncus/monitor
```

Hosted agent Monitor page:

- `Estimated cost`: `$0`
- `Total token usage`: `0`
- date range: `4/6/2026 - 5/6/2026`
- Monitor settings show App Insights `Connected`
- Application Insights resource name: `agent-lucy-appins-eus2`
- Continuous evaluation, scheduled evaluations, and evaluation alerts are
  disabled

The settings panel confirms the expected App Insights resource is connected.
The disabled settings are evaluation-related and do not explain why basic
operational token/cost/run evidence remains empty.

## Native Trace / Conversation Portal State

The Hosted Agent detail page does show native Foundry trace/conversation data.
This is separate from the blank Operate/Monitor operational cards.

`Traces > Sessions` for `agent-lucy-hosted-ncus`:

- version selector: `v21 saved 5/4/2026 11:02 PM`
- table count: `1-10 of 50`
- latest session id:
  `b475a2c592cdf55253b3adfb8632f61a95174cfc785656d996e892bd73e0b1f`
- latest session status: `Active`
- latest session created at: `5/6/26, 7:24:37 AM`
- session drawer shows `agent: agent-lucy-hosted-ncus`,
  `session_state: Stopped`, and
  `last_accessed: 2026-05-06T14:01:59.764+00:00`

`Traces > Conversations` for `agent-lucy-hosted-ncus`:

- visible count: `1-25 of 76`
- latest trace id: `0980331f6722444d773ab08c5e8774b6`
- latest response id:
  `caresp_52181c90d41c7cb5000Rm8Mly6EKzH9K81JVEeJ7h2gV21MIi2`
- status: `Completed`
- created at: `5/6/26, 7:24:40 AM`
- duration: `7.871`
- tokens in: `18728`
- tokens out: `140`
- agent version: `21`

Other visible completed v21 response rows include:

- `caresp_ff39db10110eda0000IEoPzSeV3jwlQdOTX1qc6lE0d76uQGGw`
- `caresp_06c3f16130375552006V62t3ttCGXKVpxxbaFvtay0pimmyI2H`
- `caresp_c0208595c364d6f400q3jDeh60dxrZ3GxpX6B9kyzEP8AjuyAp`
- `caresp_b41756284523295400kHMouXPVPnbF9ek9IBxWU37rbrScSIkE`
- `caresp_65a1ddd2d4dcc73700KUIfwqFoHdZZJLFBxGfSc8HTMpmdNo1s`
- `caresp_d2291c5a9da0e80300ak7hehjjSyTvDPHpFrKrgqvS1tTXpu3Q`

So the Hosted Agent lands in a native Foundry portal trace/conversation surface
with token counts. The unresolved defect is the operational metric rollup into
Operate overview, Assets, agent Monitor cards, and Azure Monitor project Agent
metrics.

## Final Fresh Smoke Evidence

The latest direct Hosted Agent proof smoke returned:

- response id:
  `caresp_52181c90d41c7cb5000Rm8Mly6EKzH9K81JVEeJ7h2gV21MIi2`
- status: `completed`
- output text: `Native trace proof alive.`

App Insights request verification for the same response:

- timestamp: `2026-05-06T14:24:40.380148Z`
- name: `invoke_agent agent-lucy-hosted-ncus:21`
- success: `True`
- duration: `7871`
- agent id: `agent-lucy-hosted-ncus:21`
- agent name: `agent-lucy-hosted-ncus`
- agent version: `21`
- project id: NCUS Foundry project resource ID

App Insights dependency verification for the same smoke included Hosted
`create_agent` and Hosted `chat` rows with model `gpt-5.2-chat`, input tokens
`4682`, output tokens `35`, and total tokens `4717`.

The logged-in Foundry portal then surfaced the same smoke as the top
`Traces > Conversations` row with response id
`caresp_52181c90d41c7cb5000Rm8Mly6EKzH9K81JVEeJ7h2gV21MIi2`, status
`Completed`, created `5/6/26, 7:24:40 AM`, duration `7.871`, tokens in `18728`,
tokens out `140`, and agent version `21`.

## Current Ask

Investigate why `Microsoft.CognitiveServices/accounts/projects` Agent metrics do
not populate for this Foundry project even though:

1. the project has a default App Insights connection,
2. App Insights receives canonical Foundry/GenAI traces for the project,
3. Foundry account-level model metrics move in the same time window, and
4. a prompt-agent Application route control also fails to move project Agent
   metrics.

## Resume Recheck 2026-05-06 14:33 UTC

The 2026-05-06 14:20-14:35 UTC window around response
`caresp_52181c90d41c7cb5000Rm8Mly6EKzH9K81JVEeJ7h2gV21MIi2` was rechecked after
terminal restart.

Positive evidence:

- App Insights `requests`: two successful
  `invoke_agent agent-lucy-hosted-ncus:21` rows, duration `7871`, agent id
  `agent-lucy-hosted-ncus:21`, agent name `agent-lucy-hosted-ncus`, agent
  version `21`, and the NCUS Foundry project id.
- App Insights `dependencies`: Hosted `create_agent` and Hosted `chat` rows
  with `gpt-5.2-chat`, input tokens `4682`, output tokens `35`, total tokens
  `4717`, plus inner `agent-lucy-prod:8` rows.
- Foundry account metrics: `ModelRequests=1`, `InputTokens=4682`,
  `OutputTokens=35`, `TotalTokens=4717`.

Failing evidence:

- Foundry project metrics for `AgentResponses`, `AgentInputTokens`,
  `AgentOutputTokens`, `AgentRuns`, and `AgentToolCalls` stayed zero minute by
  minute for the same 14:20-14:35 UTC window.
- Project-level `InputTokens`, `OutputTokens`, and `TotalTokens` returned empty
  timeseries.

Browser state:

- Computer Use can now read the authenticated local Google Chrome Foundry
  session directly.
- The project Operate overview for
  `agent-lucy-prj-ncus/operate/overview` renders normally and still shows:
  `Estimated cost` `No data to show`, `Agent success rate` `No data to show`,
  `Token usage` `No data to show`, `Agent run volume over time` `No data
  available for the selected time range`, and empty run/success trend cards.
- The Hosted Agent Monitor page for `agent-lucy-hosted-ncus` renders normally
  with `Monitor` selected and still reports `Estimated cost $0` plus `Total
  token usage 0` for `4/6/2026 - 5/6/2026`.
- Chrome AppleScript can read the active tab URL and title.
- CuaDriver permission check reports Accessibility and Screen Recording as
  granted, and `list_windows` sees Chrome pid `65519`, window id `6335`, on the
  current Space.
- Current CuaDriver `get_window_state` and `screenshot` fail with
  `Failed to start stream due to audio/video capture failure`.
- CuaDriver `page get_text` fails because Chrome's `Allow JavaScript from Apple
  Events` setting is disabled.
- `screencapture` still fails for both whole-display and window-specific
  captures.
- Chrome DevTools still is not listening on `127.0.0.1:9222`.
- System Events UI scripting is still denied to `osascript`, so it cannot be
  used as an Accessibility-tree fallback for page contents.
- The latest successful visual/AX inspection is the Computer Use authenticated
  pass captured in `state/foundry-operate-completion-audit.md`.
