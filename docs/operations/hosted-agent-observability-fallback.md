# Hosted Agent Observability Fallback

The built-in Foundry `Agents (preview)` workbook is still flaky in the portal
even when raw telemetry is landing. Use this fallback when the top-level
dashboard does not render, or when you need a COO-safe evidence path that can be
copied into an Azure Workbook or queried directly in Log Analytics.

## Current resource

- Application Insights resource: `agent-lucy-appins-eus2`
- Workspace-backed Log Analytics workspace:
  `agent-lucy-law-eus2`
- Hosted Agent name: `agent-lucy-hosted-ncus`
- Canonical hosted agent id/version seen in raw telemetry:
  `agent-lucy-hosted-ncus:21`
- Azure Monitor workbook fallback: `Lucy Hosted COO Monitor`
  - Workbook resource:
    `/subscriptions/22f9f915-587f-4a9a-acff-69b061ef48e1/resourceGroups/agent-lucy-eus2/providers/Microsoft.Insights/workbooks/d93d5898-c385-40ff-978e-eea3dbf03332`
  - Source Application Insights:
    `/subscriptions/22f9f915-587f-4a9a-acff-69b061ef48e1/resourceGroups/agent-lucy-eus2/providers/Microsoft.Insights/components/agent-lucy-appins-eus2`

## Workbook fallback

The shared Azure Monitor workbook `Lucy Hosted COO Monitor` is the current
portal-visible fallback while the built-in Foundry Operate dashboard remains
blank or unreliable. It contains:

- Hosted invocation success by version.
- Dependency and token evidence.
- Hosted run volume over time.
- Preview metric ingestion inventory.

Last verified on 2026-05-06 against Hosted v21:

- `agent-lucy-hosted-ncus:21` returned `6` App Insights request rows from
  three fresh REST smokes, with `6` successes and `0` failures. Latest response:
  `caresp_c0208595c364d6f400q3jDeh60dxrZ3GxpX6B9kyzEP8AjuyAp`.
- Dependency rows included `create_agent`, `chat`, `execute_tool`,
  `invoke_agent agent-lucy-prod:8`, and `chat gpt-5.2-chat-2025-12-11`.
- Hosted v21 `create_agent` and `chat` rows showed `28,698` total tokens
  (`28,128` input, `570` output) in the 24-hour query window.
- Preview metric inventory showed fresh `_APPRESOURCEPREVIEW_` rows for both
  `agent-lucy-hosted-ncus` and `responsesapi`.

## Query 1: Hosted request trail

Use this to confirm the hosted request stream is alive and carrying canonical
agent dimensions:

```kusto
AppRequests
| where TimeGenerated > ago(24h)
| where tostring(Properties["gen_ai.agent.name"]) == "agent-lucy-hosted-ncus"
| project
    TimeGenerated,
    Name,
    ResultCode,
    Success,
    agent_name = tostring(Properties["gen_ai.agent.name"]),
    agent_id = tostring(Properties["gen_ai.agent.id"]),
    agent_version = tostring(Properties["gen_ai.agent.version"]),
    OperationId
| order by TimeGenerated desc
| take 25
```

Expected shape:

- `Name` is the hosted request name, for example `invoke_agent agent-lucy-hosted-ncus:21`
- `agent_name` is `agent-lucy-hosted-ncus`
- `agent_id` is `agent-lucy-hosted-ncus:21`
- `agent_version` is `21`

## Query 2: Dependency breakdown

Use this to show the outer hosted request plus the inner Foundry/tool calls:

```kusto
AppDependencies
| where TimeGenerated > ago(24h)
| where
    tostring(Properties["gen_ai.agent.name"]) == "agent-lucy-hosted-ncus"
    or Name in ("create_agent", "execute_tool")
    or Name has "agent-lucy-prod"
    or Name has "gpt-5.2-chat"
| summarize count() by
    Name,
    agent_name = tostring(Properties["gen_ai.agent.name"]),
    agent_id = tostring(Properties["gen_ai.agent.id"]),
    agent_version = tostring(Properties["gen_ai.agent.version"])
| order by count_ desc
```

Expected values include:

- `create_agent`
- `execute_tool`
- `agent-lucy-prod:8`
- `chat gpt-5.2-chat-2025-12-11`

## Query 3: Preview workbook metric inventory

Use this when the workbook is blank but the resource is still receiving metric
rows:

```kusto
AppMetrics
| where TimeGenerated > ago(24h)
| summarize samples = sum(ItemCount), total_value = sum(Sum) by Name
| order by samples desc
```

For the current hosted canary, the live telemetry stream shows preview metric
rows such as `_APPRESOURCEPREVIEW_` and `Item_Success_Count`.

## Query 4: Recent raw telemetry snapshot

Use this when you want a compact COO report:

```kusto
union withsource=TableName isfuzzy=true AppRequests, AppDependencies, AppMetrics
| where TimeGenerated > ago(24h)
| where
    tostring(Properties["gen_ai.agent.name"]) == "agent-lucy-hosted-ncus"
    or tostring(Properties["service.name"]) == "agent-lucy-hosted-ncus"
    or Name has "agent-lucy-hosted-ncus"
    or Name has "agent-lucy-prod"
    or Name has "gpt-5.2-chat"
    or Name in ("create_agent", "execute_tool")
| project TimeGenerated, TableName, Name, ResultCode, Success, ItemCount, Sum, Properties, OperationId
| order by TimeGenerated desc
| take 100
```

## Workbook guidance

- Build the workbook against the Application Insights resource, not the portal
  surface.
- The workbook editor in Azure Monitor requires workbook write permission on the
  resource (`Microsoft.Insights/workbooks/write`).
- If the built-in preview workbook continues to fail, use `Lucy Hosted COO
  Monitor` as the COO-safe portal surface and keep the raw queries as the
  evidence path.
