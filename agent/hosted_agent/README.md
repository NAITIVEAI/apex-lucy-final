# Lucy Foundry Hosted Agent

This adapter runs Lucy as a Microsoft Foundry Hosted Agent using the Responses
protocol. It is the production target for first-class Foundry evals, traces,
monitoring, dashboarding, versioning, and managed runtime lifecycle. The
previous AI Gateway/APIM bridge was retired after the Hosted route became the
selected path.

## Local Smoke

Build for the platform Hosted Agents require:

```bash
docker build --platform linux/amd64 \
  -f agent/hosted_agent/Dockerfile \
  -t lucy-hosted-agent:local .
```

Run locally on the protocol port:

```bash
docker run --rm -p 8088:8088 \
  --env-file agent/app/.env \
  lucy-hosted-agent:local
```

The protocol library owns `/responses` and `/readiness`.

## Current North Central US Canary

East US2 is still the member-facing region for the current Chainlit ACA, but the
old AI Gateway/APIM bridge has been deleted. Hosted Agents were not available
there during the first launch attempt, so the current Hosted Agent canary is in
North Central US:

- Resource group: `agent-lucy-ncus`
- Foundry account: `agent-lucy-foundry-ncus`
- Foundry project: `agent-lucy-prj-ncus`
- Project endpoint:
  `https://agent-lucy-foundry-ncus.services.ai.azure.com/api/projects/agent-lucy-prj-ncus`
- ACR: `agentlucyacrncus.azurecr.io`
- Model deployment: `gpt-5.2-chat`
- Hosted Agent: `agent-lucy-hosted-ncus:21`
- Inner prompt agent: `agent-lucy-prod:8`
- Last documented hosted image:
  `agentlucyacrncus.azurecr.io/agent-lucy-hosted:hosted-pr2-20260504102638-operatechatspan`

The basic SDK smoke is green:

```python
from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential

project = AIProjectClient(
    endpoint="https://agent-lucy-foundry-ncus.services.ai.azure.com/api/projects/agent-lucy-prj-ncus",
    credential=DefaultAzureCredential(),
    allow_preview=True,
)
client = project.get_openai_client(agent_name="agent-lucy-hosted-ncus")
response = client.responses.create(
    input="Health smoke: reply with one short sentence saying Lucy hosted is online."
)
print(response.status, response.error, response.output_text)
```

Expected smoke result: `completed None` with a short Lucy response.

## Current Observability State

- App Insights telemetry is landing for Hosted Agent traffic, including the
  outer hosted request and dependencies for `create_agent`,
  `invoke_agent agent-lucy-prod:8`, `execute_tool`, and the
  `gpt-5.2-chat-2025-12-11` model call.
- Version 21 response creation is green for Hosted wrapper
  response ids. The adapter keeps Hosted `caresp_...` / `conv_...` identifiers
  as Foundry metadata but does not forward them as inner prompt-agent
  conversation state.
- Fresh Hosted v21 REST smokes on 2026-05-06 returned
  `caresp_65a1ddd2d4dcc73700KUIfwqFoHdZZJLFBxGfSc8HTMpmdNo1s`,
  `caresp_b41756284523295400kHMouXPVPnbF9ek9IBxWU37rbrScSIkE`, and
  `caresp_c0208595c364d6f400q3jDeh60dxrZ3GxpX6B9kyzEP8AjuyAp`, all with
  `status=completed`, `error=None`, and assistant output text.
- Version 13 target evaluation completed successfully with output text, model
  usage, and `passed=1`, `failed=0`, `errored=0`:
  `evalrun_b03b7e0521e642c6986d3e84e10b65a3`.
- Version 21 telemetry confirms canonical agent dimensions on hosted request,
  `create_agent`, `chat`, and model/tool rows:
  `gen_ai.agent.name=agent-lucy-hosted-ncus`,
  `gen_ai.agent.id=agent-lucy-hosted-ncus:21`, and
  `gen_ai.agent.version=21`. Hosted `create_agent` and `chat` rows also carry
  `gen_ai.provider.name=azure.ai.foundry`,
  `gen_ai.response.model=gpt-5.2-chat`, and populated
  `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`, and
  `gen_ai.usage.total_tokens`. Lucy also exports App Insights custom metrics
  `gen_ai.client.token.usage` and `gen_ai.client.operation.duration` with
  Hosted agent, model, and Foundry project dimensions. The stale custom
  `gen_ai.agents.id=lucy-aca` dimension is no longer emitted by Lucy's custom
  response loop.
- Version 21 also carries the explicit AI Search project connection ID and
  disables Chainlit-only dashboard route registration in the Hosted process.
- Version 21 includes a stale-conversation recovery fix: if the inner Responses
  API reports `conversation_not_found`, Lucy clears the stored conversation
  handle and retries once with a fresh agent reference.
- Version 21 aligns `MODEL_DEPLOYMENT_NAME`, `AZURE_AGENT_MODEL`, and
  `AZURE_GPT_MODEL` to `gpt-5.2-chat`; `MODEL_DEPLOYMENT_NAME` wins in Lucy's
  code path, so leaving it at base `gpt-5.2` silently routes the inner prompt
  agent to the wrong model lane.
- The NCUS portal should show both `agent-lucy-hosted-ncus` and
  `agent-lucy-prod`. That is expected: the hosted agent is the container wrapper,
  while the prompt agent is the inner Lucy reasoning/tool agent.
- The Operate/Application Analytics workbook-shaped KQL now returns non-zero
  Hosted `chat` rows/tokens from App Insights. The older native Build Monitor
  project metrics path still shows zeros after v21 traffic. The page's own cost
  API has previously returned hosted token totals, but its Azure
  Monitor project metrics calls still return empty
  or zero `AgentResponses`, `AgentInputTokens`, `AgentOutputTokens`,
  `AgentRuns`, and `AgentToolCalls` timeseries even after fresh SDK traffic.
  Foundry account model metrics do show non-zero `ModelRequests`, `InputTokens`,
  `OutputTokens`, and `TotalTokens` for the same smoke window, so the remaining
  gap is the project Agent metric rollup, not model/runtime execution.
  The current COO-safe fallback is the Azure Monitor workbook
  `Lucy Hosted COO Monitor` (`d93d5898-c385-40ff-978e-eea3dbf03332`) on App Insights
  `agent-lucy-appins-eus2`.
- A temporary published Agent Application route for `agent-lucy-hosted-ncus:21`
  was tested on 2026-05-06 because the only durable published application was
  `agent-lucy-prod` (Managed, prompt-agent v8). ARM accepted a Hosted deployment
  and it reached Running, but the live application-scoped Responses endpoint
  rejected it with `Application-scoped routes only support prompt agents. Agent
  kind 'hosted' is not supported.` The temporary Hosted application/deployment
  were stopped and deleted. Do not recreate this as an observability workaround
  unless Microsoft changes Hosted support for Agent Application routes.
- Continuous evaluation is enabled for the inner prompt agent
  `agent-lucy-prod` and produces completed runs.
- Continuous evaluation rules targeting the outer Hosted Agent
  `agent-lucy-hosted-ncus` still need a fresh post-v13 run. Historical v10/v11
  runs failed with `session_not_accessible`; a v13 one-off Hosted target eval
  passed after the adapter stopped forwarding Hosted wrapper ids to the inner
  prompt agent.
- If the built-in preview workbook is blank or flaky, use the fallback KQL
  runbook at [docs/operations/hosted-agent-observability-fallback.md](../../docs/operations/hosted-agent-observability-fallback.md).

## Retired Gateway Bridge

The abandoned East US2 AI Gateway path was removed on 2026-05-04:

- APIM `apexclassaction-ai-gw` was deleted.
- Gateway-only ACA `agent-lucy-gateway-eus2` was deleted.
- The member-facing Chainlit ACA `agent-lucy-eus2` remains running separately.

Do not recreate the gateway bridge unless the Hosted route is explicitly
abandoned again.

## Build And Push

```bash
TAG="$(date +%Y%m%d%H%M%S)"
az acr build \
  --registry agentlucyacrncus \
  --image "agent-lucy-hosted:${TAG}" \
  --platform linux/amd64 \
  -f agent/hosted_agent/Dockerfile \
  .
```

## Create Hosted Version

Hosted Agents are preview-region gated. Use a supported Hosted Agents region;
the first green Lucy Hosted canary is in North Central US.

Required:

- `AZURE_AI_PROJECT_ENDPOINT` or `AZURE_AI_FOUNDRY_PROJECT_ENDPOINT`
- `LUCY_HOSTED_IMAGE`, for example
  `agentlucyacrncus.azurecr.io/agent-lucy-hosted:${TAG}`

Optional:

- `LUCY_HOSTED_AGENT_NAME`, default `agent-lucy-hosted`
- `LUCY_HOSTED_CPU`, default `1`
- `LUCY_HOSTED_MEMORY`, default `2Gi`
- `LUCY_HOSTED_PROTOCOL_VERSION`, default `1.0.0`
- `LUCY_HOSTED_EXTRA_ENV_KEYS`, comma-separated env var names to copy into the
  immutable hosted version definition

```bash
python agent/hosted_agent/deploy_hosted_agent.py
```

After the version reaches `active`, invoke the Foundry endpoint:

```text
{project_endpoint}/agents/{agent_name}/endpoint/protocols/openai/responses?api-version=v1
```

Prefer SDK invocation during canary:

```python
project.get_openai_client(agent_name=agent_name).responses.create(input="...")
```

## Secret Handling Note

Hosted Agent versions are immutable, and the current SDK path stores the
provided environment-variable map in the version definition. Before broad
production cutover, move secret-bearing runtime configuration to managed
identity, Key Vault, or a secret-backed pattern supported by the Hosted Agent
control plane.

## Cutover Rule

Do not point Chainlit user traffic at Hosted Agent until canary proves:

- notice auth and retrieval
- PDF artifact propagation
- HITL handoff behavior
- Foundry traces and dependencies
- token accounting
- eval metadata
- 4+ minute idle/reconnect continuity
