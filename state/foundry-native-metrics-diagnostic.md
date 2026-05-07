# Foundry Native Metrics Diagnostic

Last verified: 2026-05-06

## Current conclusion

Lucy Hosted traffic is healthy in App Insights and account-level model metrics,
but the Foundry project Agent metric namespace is not binding the Hosted runs.

This means the current production-safe portal evidence path is:

- Azure Portal workbook: `Lucy Hosted COO Monitor`
- Application Insights: `agent-lucy-appins-eus2`

The native Foundry Build/Operate Agent cards should not be treated as fixed
until the project Agent metrics below return non-zero values or the UI is
visibly confirmed populated.

## Agent Application route check

On 2026-05-06, a temporary published Agent Application named
`agent-lucy-hosted-ncus` was created to test whether the native project Agent
metric rollup requires traffic through the application/deployment surface rather
than the direct Hosted endpoint.

Observed ARM state during the test:

- Application `agent-lucy-hosted-ncus` provisioned successfully.
- Deployment `agent-lucy-hosted-ncus` provisioned successfully as
  `deploymentType=Hosted`.
- Deployment routed to `agent-lucy-hosted-ncus:21`.
- Deployment reached `state=Running`.

The application-scoped Responses endpoint rejected invocation:

```text
Application-scoped routes only support prompt agents. Agent kind 'hosted' is not supported.
```

The temporary application and deployment were stopped/deleted after the test.
Verification returned `ApplicationNotFound` and `DeploymentNotFound` for both
`2025-10-01-preview` and `2026-03-15-preview` ARM API versions.

Do not recreate this route as an observability fix unless Microsoft changes the
application-scoped route support contract for Hosted agents.

## Prompt application control check

On 2026-05-06, the existing prompt-agent Application route was also invoked as a
control:

```text
https://agent-lucy-foundry-ncus.services.ai.azure.com/api/projects/agent-lucy-prj-ncus/applications/agent-lucy-prod/protocols/openai/responses?api-version=2025-11-15-preview
```

Observed response:

- Response id:
  `resp_06a8c313860b3cee0169fb427a97808194a2b7305137ed0c07`
- `status=completed`
- `error=null`
- Agent reference: `agent-lucy-prod:8`
- Output text: `Prompt application route is alive.`

After this control call, the Foundry account-level model metrics for
2026-05-06 13:20-13:40 UTC returned non-zero values:

- `ModelRequests=2`
- `InputTokens=9366`
- `OutputTokens=129`
- `TotalTokens=9495`

The Foundry project metric namespace for the same window still returned zero
for:

- `AgentResponses`
- `AgentInputTokens`
- `AgentOutputTokens`
- `AgentRuns`
- `AgentToolCalls`
- project-level `InputTokens`
- project-level `OutputTokens`
- project-level `TotalTokens`

This shows the project Agent metric gap is not explained only by using the
direct Hosted endpoint; a supported prompt-agent Application invocation also
failed to move project Agent metrics while model usage appeared at account
scope.

## Resumed control check

On 2026-05-06 after gateway retirement was rechecked, two fresh calls were made
in the 13:41-13:42 UTC window:

- Direct Hosted route response:
  `caresp_ff39db10110eda0000IEoPzSeV3jwlQdOTX1qc6lE0d76uQGGw`
- Prompt-agent Application control response:
  `resp_02daf5317b79b4350169fb452942c081909de28df403ce1840`

Both returned `status=completed` and `error=null`. App Insights ingested:

- request rows for `invoke_agent agent-lucy-hosted-ncus:21`
- Hosted `create_agent` and `chat` dependency rows with
  `gen_ai.agent.id=agent-lucy-hosted-ncus:21`
- prompt-agent `invoke_agent agent-lucy-prod:8` and model `chat
  gpt-5.2-chat-2025-12-11` rows

The Foundry account model metrics for 2026-05-06 13:35-13:50 UTC moved:

- `ModelRequests=1`
- `InputTokens=4680`
- `OutputTokens=96`
- `TotalTokens=4776`

The Foundry project metrics for the same window still returned zero totals for:

- `AgentResponses`
- `AgentInputTokens`
- `AgentOutputTokens`
- `AgentRuns`
- `AgentToolCalls`
- project-level `InputTokens`
- project-level `OutputTokens`
- project-level `TotalTokens`

This reproduces the same split after the retired gateway resources were removed:
healthy execution and telemetry in App Insights, model usage at account scope,
and no project Agent metric rollup.

## RBAC and connection check

Microsoft's current Foundry monitoring docs say the Agent Monitoring Dashboard
reads from the Application Insights resource connected to the project and that
log-based views require access to the associated Log Analytics workspace. The
project connection and relevant access were checked on 2026-05-06:

- Project connection:
  - name `agentlucyappinseus2dq5t8e`
  - category `AppInsights`
  - target `agent-lucy-appins-eus2`
  - `isDefault=true`
  - `error=null`
- Signed-in Azure CLI user:
  - `Chris@apexclassaction.com`
  - inherited subscription roles include `Owner`, `Contributor`,
    `Monitoring Contributor`, `Log Analytics Contributor`, `Azure AI
    Administrator`, and `Azure AI User`
- Foundry project managed identity:
  - principal `d4f3d82d-0056-4e6f-93f8-d1be9b049d94`
  - `Log Analytics Reader` on `agent-lucy-appins-eus2`
  - `Log Analytics Reader` and `Log Analytics Data Reader` on the managed
    App Insights workspace
- Hosted runtime identity:
  - principal `bf64d26c-34a5-4bc8-a1b2-b22e9ff24b67`
  - `Azure AI User` and `Azure AI Project Manager` on the NCUS Foundry project

The hosted runtime identity does not have App Insights reader roles, but that
identity is not the documented dashboard reader path and the runtime is already
successfully emitting telemetry. No RBAC change was made.

## Resources

- Foundry project:
  `/subscriptions/22f9f915-587f-4a9a-acff-69b061ef48e1/resourceGroups/agent-lucy-ncus/providers/Microsoft.CognitiveServices/accounts/agent-lucy-foundry-ncus/projects/agent-lucy-prj-ncus`
- Foundry account:
  `/subscriptions/22f9f915-587f-4a9a-acff-69b061ef48e1/resourceGroups/agent-lucy-ncus/providers/Microsoft.CognitiveServices/accounts/agent-lucy-foundry-ncus`
- Application Insights:
  `/subscriptions/22f9f915-587f-4a9a-acff-69b061ef48e1/resourceGroups/agent-lucy-eus2/providers/Microsoft.Insights/components/agent-lucy-appins-eus2`
- Current Hosted Agent telemetry:
  `agent-lucy-hosted-ncus:21`
- Current inner prompt-agent telemetry:
  `agent-lucy-prod:8`

## Fresh smoke evidence

May 6 Hosted smoke response IDs:

- `caresp_65a1ddd2d4dcc73700KUIfwqFoHdZZJLFBxGfSc8HTMpmdNo1s`
- `caresp_b41756284523295400kHMouXPVPnbF9ek9IBxWU37rbrScSIkE`
- `caresp_c0208595c364d6f400q3jDeh60dxrZ3GxpX6B9kyzEP8AjuyAp`
- `caresp_06c3f16130375552006V62t3ttCGXKVpxxbaFvtay0pimmyI2H`

REST retrieval returned `status=completed`, `error=null`, agent reference
`agent-lucy-hosted-ncus` version `21`, and assistant output text
`Lucy May 6 portal telemetry smoke N is alive.` The post-cleanup direct Hosted
route smoke returned `Direct hosted route remains alive.`

## App Insights request check

```bash
az monitor app-insights query \
  --app /subscriptions/22f9f915-587f-4a9a-acff-69b061ef48e1/resourceGroups/agent-lucy-eus2/providers/Microsoft.Insights/components/agent-lucy-appins-eus2 \
  --analytics-query "requests | where timestamp between (datetime(2026-05-06T12:45:00Z)..datetime(2026-05-06T13:05:00Z)) | where name has 'agent-lucy-hosted-ncus' | summarize rows=count(), successes=countif(success == true), failures=countif(success == false), latest=max(timestamp) by name, agent_id=tostring(customDimensions['gen_ai.agent.id']), agent_version=tostring(customDimensions['gen_ai.agent.version'])" \
  -o json
```

Observed result:

- `invoke_agent agent-lucy-hosted-ncus:21`
- `rows=6`
- `successes=6`
- `failures=0`

## App Insights dependency check

```bash
az monitor app-insights query \
  --app /subscriptions/22f9f915-587f-4a9a-acff-69b061ef48e1/resourceGroups/agent-lucy-eus2/providers/Microsoft.Insights/components/agent-lucy-appins-eus2 \
  --analytics-query "dependencies | where timestamp between (datetime(2026-05-06T12:45:00Z)..datetime(2026-05-06T13:05:00Z)) | extend agent_id=tostring(customDimensions['gen_ai.agent.id']), model=tostring(customDimensions['gen_ai.response.model']), total_tokens=toint(customDimensions['gen_ai.usage.total_tokens']), input_tokens=toint(customDimensions['gen_ai.usage.input_tokens']), output_tokens=toint(customDimensions['gen_ai.usage.output_tokens']) | where agent_id startswith 'agent-lucy-hosted-ncus' or agent_id startswith 'agent-lucy-prod' or name has 'gpt-5.2-chat' | summarize rows=count(), successes=countif(success == true), total_tokens=sum(total_tokens), input_tokens=sum(input_tokens), output_tokens=sum(output_tokens), latest=max(timestamp) by name, agent_id, model | order by latest desc" \
  -o json
```

Observed result:

- Hosted `create_agent` and `chat` rows for `agent-lucy-hosted-ncus:21`
- Inner rows for `invoke_agent agent-lucy-prod:8`
- Model rows for `chat gpt-5.2-chat-2025-12-11`
- Hosted token total: `28698`
- Hosted input tokens: `28128`
- Hosted output tokens: `570`

## Native project Agent metric check

```bash
az monitor metrics list \
  --resource /subscriptions/22f9f915-587f-4a9a-acff-69b061ef48e1/resourceGroups/agent-lucy-ncus/providers/Microsoft.CognitiveServices/accounts/agent-lucy-foundry-ncus/projects/agent-lucy-prj-ncus \
  --metric AgentResponses AgentInputTokens AgentOutputTokens AgentRuns AgentToolCalls \
  --interval PT1M \
  --aggregation Total \
  --start-time 2026-05-06T12:45:00Z \
  --end-time 2026-05-06T13:05:00Z \
  -o json
```

Observed result:

- all-zero timeseries for all five project Agent metrics

## Foundry account model metric check

```bash
az monitor metrics list \
  --resource /subscriptions/22f9f915-587f-4a9a-acff-69b061ef48e1/resourceGroups/agent-lucy-ncus/providers/Microsoft.CognitiveServices/accounts/agent-lucy-foundry-ncus \
  --metric ModelRequests InputTokens OutputTokens TotalTokens \
  --interval PT1M \
  --aggregation Total \
  --start-time 2026-05-06T12:45:00Z \
  --end-time 2026-05-06T13:05:00Z \
  -o json
```

Observed non-zero totals:

- `ModelRequests=3`
- `InputTokens=14064`
- `OutputTokens=285`
- `TotalTokens=14349`

## Interpretation

The same traffic window has:

- healthy Hosted Agent execution
- healthy App Insights GenAI traces and custom metrics
- non-zero Foundry account model metrics
- zero Foundry project Agent metrics

The prompt-application control check also has:

- healthy prompt-agent Application execution
- non-zero Foundry account model metrics
- zero Foundry project Agent metrics

That points to the native project Agent metric rollup as the remaining blocked
surface for this project, not just a Hosted adapter/code issue. Do not spend
more app-code time trying to write
`Microsoft.CognitiveServices/accounts/projects` metrics directly unless
Microsoft documents a supported ingestion contract for Hosted Agent project
metrics.
