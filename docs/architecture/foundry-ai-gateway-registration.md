# Foundry AI Gateway Interim Registration Runbook

This runbook documents the retired interim path that wired Lucy's custom Python
runtime in Azure Container Apps (ACA) to Microsoft Foundry via the Azure AI
Gateway. It was useful for early traces, eval smoke tests, and gateway-level
governance, but it is no longer active. The target Foundry architecture is the
Hosted Agent container that exposes the Responses protocol while reusing the
UI-independent `LucyRuntime` core.

## Retirement Status

Retired on 2026-05-04 after the team abandoned the AI Gateway route and selected
Hosted Agent as the path forward.

- Deleted APIM: `apexclassaction-ai-gw`
- Deleted gateway-only ACA: `agent-lucy-gateway-eus2`
- Preserved member-facing Chainlit ACA: `agent-lucy-eus2`
- Preserved current Hosted Agent path: `agent-lucy-hosted-ncus`

Do not use this document as an active runbook unless the gateway route is
deliberately rebuilt.

## Historical Gateway Resources

- Lucy ACA: `agent-lucy-eus2`
- Lucy Gateway ACA: `agent-lucy-gateway-eus2`
- Resource group: `agent-lucy-eus2`
- Public Chainlit URL: `https://agent-lucy-eus2.purpleocean-f3514433.eastus2.azurecontainerapps.io`
- Public Gateway URL: `https://agent-lucy-gateway-eus2.purpleocean-f3514433.eastus2.azurecontainerapps.io`
- Foundry account: `agent-lucy-foundry-eus2`
- Foundry project: `agent-lucy-prj-eus2`
- AI Gateway: `apexclassaction-ai-gw`
- AI Gateway URL: `https://apexclassaction-ai-gw.azure-api.net`
- Application Insights: `agent-lucy-appins-eus2`
- Current gateway image: `agentlucyacreus2.azurecr.io/agent-lucy-eus2:codex-context-preserve-20260427034920`
- Current gateway image digest: `sha256:718d2e537169263ea10e96e81b61c87ccb7f4daf53e84f8e1dea04e1e64494bd`
- Current Foundry project agent version used by gateway/runtime: `agent-lucy-prod:7`

## Why The Gateway ACA Existed

ACA exposes one public HTTPS ingress target port per container app. The existing
Lucy app serves Chainlit on port `8000`; the gateway HTTP wrapper serves
`POST /agent/respond` on `LUCY_HTTP_PORT` (`8002` by default). To avoid breaking
the member-facing Chainlit route, the interim gateway path uses a dedicated
gateway-facing ACA with `LUCY_CHAINLIT_ENABLED=false` and ingress target port
`8002`.

This is a bridge, not the intended final topology. Hosted Agent uses a different
serving surface: a container that speaks the Foundry protocol library on port
`8088`, with Foundry owning the hosted agent endpoint, lifecycle, telemetry
injection, and versioning. Chainlit should remain the member UI unless and until
there is a separate product decision to replace it.

## Required Environment

These were set on the gateway-facing ACA:

```bash
AZURE_AI_PROJECT_ENDPOINT="https://agent-lucy-foundry-eus2.services.ai.azure.com/api/projects/agent-lucy-prj-eus2"
AZURE_AI_FOUNDRY_PROJECT_ENDPOINT="https://agent-lucy-foundry-eus2.services.ai.azure.com/api/projects/agent-lucy-prj-eus2"
LUCY_HTTP_ENABLED="true"
LUCY_HTTP_PORT="8002"
LUCY_CHAINLIT_ENABLED="false"
LUCY_GATEWAY_API_TOKEN="<fresh-shared-secret>"
LUCY_OTEL_AGENT_ID="lucy-aca"
OTEL_SERVICE_NAME="lucy-agent"
OTEL_RESOURCE_ATTRIBUTES="service.name=lucy-agent,service.version=1.0.0"
APPLICATIONINSIGHTS_CONNECTION_STRING="<same App Insights connection connected to Foundry project>"
```

Keep `LUCY_OTEL_AGENT_ID` exactly equal to the OpenTelemetry Agent ID entered
in the Foundry Register Asset form.

## Historical Registration Steps

1. In Foundry, confirm the resource has an AI Gateway configured:
   Operate -> Admin -> AI Gateway.
2. Confirm the Foundry project has Application Insights connected:
   Operate -> Admin -> project -> Connected resources -> AppInsights.
3. Register Lucy:
   Operate -> Overview -> Register asset.
4. Use these values:
   - Agent URL: `https://<gateway-aca-fqdn>/agent/respond`
   - Protocol: General HTTP
   - OpenTelemetry Agent ID: `lucy-aca`
   - Project: `agent-lucy-prj-eus2`
   - Agent name: `Lucy (ACA Gateway)`
5. Configure the AI Gateway/APIM outbound policy to add:
   `X-Agent-Token: <LUCY_GATEWAY_API_TOKEN>`.
6. Use the Foundry-issued APIM URL for interim eval/playground traffic while the Hosted Agent path is built.

Known RBAC note: the gateway ACA managed identity can create project agent
versions and call the project Responses endpoint, but managed application
publication currently returns `AuthorizationFailed` for
`Microsoft.CognitiveServices/accounts/projects/applications/agentdeployments/write`.
Until that role is widened, the runtime falls back to the project agent version
directly.

## Historical Smoke Checks

```bash
az account show

az resource show \
  --resource-group agent-lucy-eus2 \
  --name agent-lucy-foundry-eus2 \
  --resource-type Microsoft.CognitiveServices/accounts

az resource list \
  --resource-group agent-lucy-eus2 \
  --resource-type Microsoft.CognitiveServices/accounts/projects

az resource show \
  --resource-group agent-lucy-eus2 \
  --name apexclassaction-ai-gw \
  --resource-type Microsoft.ApiManagement/service \
  --query "{name:name,gatewayUrl:properties.gatewayUrl,provisioningState:properties.provisioningState}"

curl -sS "https://<gateway-aca-fqdn>/health/gateway"

curl -sS -X POST "https://<gateway-aca-fqdn>/agent/respond" \
  -H "Content-Type: application/json" \
  -H "X-Agent-Token: <LUCY_GATEWAY_API_TOKEN>" \
  -d '{"input_text":"What can Lucy help me with?","session":{"session_id":"smoke-001"},"metadata":{"smoke":true}}'
```

Current smoke evidence from `agent-lucy-gateway-eus2` revision
`agent-lucy-gateway-eus2--0000013`:

- `GET /health/gateway` returned `status=healthy`,
  `gateway_connected=true`, `project_probe.method=list_versions`.
- AI Gateway/APIM `POST /lucyv2-eojkdlgt` returned `200`; Lucy called
  `get_current_datetime` and returned an online confirmation.
- The member-facing Chainlit app is on `agent-lucy-eus2--0000065`; its
  reconnect/startup path preserves `previous_response_id` and pending notice
  metadata so auth follow-up turns do not lose the original notice request.

Expected `/health/gateway` shape:

```json
{
  "status": "healthy",
  "gateway_connected": true,
  "runtime_initialized": true,
  "gateway_token_configured": true,
  "otel_agent_id": "lucy-aca",
  "agent_url_path": "/agent/respond"
}
```

## Eval Seeds

Seed cases live at `agent/evals/cases.jsonl`. They cover:

- generic scope
- notice lookup before authentication
- notice lookup after authentication
- human handoff
- sensitive-data refusal

Use those cases for the initial Foundry eval rule setup, then replace placeholder
authenticated IDs with safe staging records before running tool-writing cases.

## Historical Monitor Acceptance

The gateway bridge was considered healthy when:

- new APIM/Foundry URL reaches Lucy successfully
- traces land in the same Application Insights resource as the Foundry project
- spans include `operation="create_agent"` and `gen_ai.agents.id="lucy-aca"`
- tool spans appear with `gen_ai.tool.name`
- continuous evaluation produces scores on sampled traffic

## Hosted Agent Target

The production target is a Hosted Agent version, not the custom-agent gateway
registration. The first supported-region Hosted canary is now live in North
Central US:

- Resource group: `agent-lucy-ncus`
- Foundry account: `agent-lucy-foundry-ncus`
- Foundry project: `agent-lucy-prj-ncus`
- Project endpoint:
  `https://agent-lucy-foundry-ncus.services.ai.azure.com/api/projects/agent-lucy-prj-ncus`
- ACR: `agentlucyacrncus.azurecr.io`
- Model deployment: `gpt-5.2`
- Hosted Agent: `agent-lucy-hosted-ncus:4`
- Hosted image:
  `agentlucyacrncus.azurecr.io/agent-lucy-hosted:hosted-20260428212030`
- Basic SDK smoke: `status=completed`, `error=None`,
  `output_text="Lucy Hosted is online."`

The Hosted Agent endpoint is invoked through the Foundry project agent route:

```text
{project_endpoint}/agents/agent-lucy-hosted-ncus/endpoint/protocols/openai/responses?api-version=v1
```

Prefer SDK invocation during canary:

```python
project.get_openai_client(agent_name="agent-lucy-hosted-ncus").responses.create(input="...")
```

The Hosted Agent work should continue to:

- use `agent/hosted_agent/app.py` as the protocol adapter around
  `LucyRuntime.respond()` using `azure-ai-agentserver-responses` /
  `ResponsesAgentServerHost`
- serve the protocol container on port `8088` with
  `agent/hosted_agent/Dockerfile`
- build and push a `linux/amd64` image to ACR
- create a Hosted Agent version with `agent/hosted_agent/deploy_hosted_agent.py`
  (`HostedAgentDefinition` + `AgentProtocol.RESPONSES`)
- preserve Chainlit as the public member UI and treat the hosted endpoint as the
  Foundry-managed agent runtime endpoint
- verify first-class traces, token accounting, dashboards, and Evals v2 before
  production cutover

If the portal's built-in `Agents (preview)` workbook stays blank or unreliable,
use the fallback KQL runbook at
[docs/operations/hosted-agent-observability-fallback.md](../operations/hosted-agent-observability-fallback.md)
and keep the raw App Insights query path as the evidence source.

The East US2 `create_version` attempt against project `agent-lucy-prj-eus2`
returned `bad_request: The requested experience is not available for this
subscription.` The product deliberately moved to the North Central US Hosted
path, and the East US2 gateway route has been deleted.

Before broad production cutover, move secret-bearing runtime configuration out
of plain Hosted version environment variables and into managed identity, Key
Vault, or a secret-backed pattern supported by the Hosted Agent control plane.

## References

- Microsoft Learn, Hosted agents:
  https://learn.microsoft.com/en-us/azure/foundry/agents/concepts/hosted-agents
- Microsoft Learn, Deploy a hosted agent:
  https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/deploy-hosted-agent
- Microsoft Learn, ResponsesAgentServerHost:
  https://learn.microsoft.com/en-us/python/api/azure-ai-agentserver-responses/azure.ai.agentserver.responses.responsesagentserverhost
- Microsoft Learn, Register and manage custom agents (interim gateway route):
  https://learn.microsoft.com/en-us/azure/foundry/control-plane/register-custom-agent
- Microsoft Learn, Agent Monitoring Dashboard:
  https://learn.microsoft.com/en-us/azure/foundry/observability/how-to/how-to-monitor-agents-dashboard
- Microsoft Learn, Evaluate your AI agents:
  https://learn.microsoft.com/en-us/azure/foundry/observability/how-to/evaluate-agent
- Microsoft Learn, Client-side tracing:
  https://learn.microsoft.com/en-us/azure/foundry/observability/how-to/trace-agent-client-side
