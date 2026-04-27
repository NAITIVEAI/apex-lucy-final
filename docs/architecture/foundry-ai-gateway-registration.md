# Foundry AI Gateway Registration Runbook

This runbook wires Lucy's custom Python runtime in Azure Container Apps (ACA)
to Microsoft Foundry via the Azure AI Gateway. The goal is production Monitor
visibility, continuous evaluations, and gateway-level governance without moving
Lucy out of her custom code runtime.

## Current Production Resources

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

## Why Gateway-Only ACA Is Preferred

ACA exposes one public HTTPS ingress target port per container app. The existing
Lucy app serves Chainlit on port `8000`; the gateway HTTP wrapper serves
`POST /agent/respond` on `LUCY_HTTP_PORT` (`8002` by default). To avoid breaking
the member-facing Chainlit route, create or update a dedicated gateway-facing
ACA using the same image, with `LUCY_CHAINLIT_ENABLED=false` and ingress target
port `8002`.

The existing all-in-one startup remains valid for internal smoke tests, but the
Foundry registration URL must point at an externally reachable HTTP wrapper.

## Required Environment

Set these on the gateway-facing ACA:

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

## Register Lucy In Foundry

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
6. Use the Foundry-issued APIM URL for eval/playground traffic.

Known RBAC note: the gateway ACA managed identity can create project agent
versions and call the project Responses endpoint, but managed application
publication currently returns `AuthorizationFailed` for
`Microsoft.CognitiveServices/accounts/projects/applications/agentdeployments/write`.
Until that role is widened, the runtime falls back to the project agent version
directly.

## Smoke Checks

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

## Monitor Acceptance

Foundry Monitor is ready when:

- new APIM/Foundry URL reaches Lucy successfully
- traces land in the same Application Insights resource as the Foundry project
- spans include `operation="create_agent"` and `gen_ai.agents.id="lucy-aca"`
- tool spans appear with `gen_ai.tool.name`
- continuous evaluation produces scores on sampled traffic

## References

- Microsoft Learn, Register and manage custom agents:
  https://learn.microsoft.com/en-us/azure/foundry/control-plane/register-custom-agent
- Microsoft Learn, Agent Monitoring Dashboard:
  https://learn.microsoft.com/en-us/azure/foundry/observability/how-to/how-to-monitor-agents-dashboard
- Microsoft Learn, Evaluate your AI agents:
  https://learn.microsoft.com/en-us/azure/foundry/observability/how-to/evaluate-agent
- Microsoft Learn, Client-side tracing:
  https://learn.microsoft.com/en-us/azure/foundry/observability/how-to/trace-agent-client-side
