# Lucy Foundry Hosted Agent

This adapter runs Lucy as a Microsoft Foundry Hosted Agent using the Responses
protocol. It is the production target for first-class Foundry evals, traces,
monitoring, dashboarding, versioning, and managed runtime lifecycle. The
existing AI Gateway/APIM route remains a rollback and diagnostics bridge until
Hosted Agent parity is proven.

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

East US2 is still the production member-facing region for the current ACA and
gateway bridge, but Hosted Agents were not available there during the first
launch attempt. The current Hosted Agent canary is in North Central US:

- Resource group: `agent-lucy-ncus`
- Foundry account: `agent-lucy-foundry-ncus`
- Foundry project: `agent-lucy-prj-ncus`
- Project endpoint:
  `https://agent-lucy-foundry-ncus.services.ai.azure.com/api/projects/agent-lucy-prj-ncus`
- ACR: `agentlucyacrncus.azurecr.io`
- Model deployment: `gpt-5.2`
- Hosted Agent: `agent-lucy-hosted-ncus:8`
- Hosted image:
  `agentlucyacrncus.azurecr.io/agent-lucy-hosted:hosted-20260429051054-rbac-dashboard`

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
  `invoke_agent agent-lucy-prod:1`, `execute_tool`, and the `gpt-5.2` model
  call.
- Version 8 telemetry confirms canonical agent dimensions on hosted request,
  `create_agent`, and `execute_tool` rows:
  `gen_ai.agent.name=agent-lucy-hosted-ncus`,
  `gen_ai.agent.id=agent-lucy-hosted-ncus:8`, and
  `gen_ai.agent.version=8`. The stale custom `gen_ai.agents.id=lucy-aca`
  dimension is no longer emitted by Lucy's custom response loop.
- Version 8 also carries the explicit AI Search project connection ID and
  disables Chainlit-only dashboard route registration in the Hosted process.
- Continuous evaluation is enabled for the inner prompt agent
  `agent-lucy-prod` and produces completed runs.
- Continuous evaluation rules targeting the outer Hosted Agent
  `agent-lucy-hosted-ncus` currently create runs but fail with
  `session_not_accessible`. Treat this as a Foundry preview session-access
  limitation until Microsoft confirms otherwise.

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
