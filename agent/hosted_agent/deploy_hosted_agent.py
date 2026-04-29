"""Create a Foundry Hosted Agent version for Lucy.

Configuration is read from environment variables so the script can run from a
developer shell, CI, or an Azure deployment job without baking resource names
into the repo.
"""

from __future__ import annotations

import os
import sys
import time
from typing import Any


DEFAULT_ENV_KEYS = (
    "AZURE_AI_FOUNDRY_PROJECT_ENDPOINT",
    "AZURE_AI_PROJECT_ENDPOINT",
    "AZURE_CLIENT_ID",
    "AZURE_SEARCH_ENDPOINT",
    "AZURE_SEARCH_INDEX",
    "AZURE_STORAGE_ACCOUNT",
    "AZURE_STORAGE_CONNECTION_STRING",
    "DYNAMICS_BASE_URL",
    "LUCY_AGENT_NAME",
    "LUCY_APPLICATION_NAME",
    "LUCY_GATEWAY_API_TOKEN",
    "LUCY_OTEL_AGENT_ID",
    "MODEL_DEPLOYMENT_NAME",
    "OPENAI_API_VERSION",
    "PORTAL_BASE_URL",
    "LUCY_AGENT_PORTAL_URL",
    "LUCY_AGENT_PORTAL_API_TOKEN",
)

HOSTED_ENV_ALIASES = {
    "AGENT_PORTAL_ENABLED": "LUCY_AGENT_PORTAL_ENABLED",
    "AGENT_PORTAL_URL": "LUCY_AGENT_PORTAL_URL",
    "AGENT_PORTAL_API_TOKEN": "LUCY_AGENT_PORTAL_API_TOKEN",
    "AGENT_PORTAL_PORT": "LUCY_AGENT_PORTAL_PORT",
    "FOUNDRY_AGENT_NAME": "LUCY_FOUNDRY_AGENT_NAME",
    "FOUNDRY_APPLICATION_NAME": "LUCY_FOUNDRY_APPLICATION_NAME",
    "FOUNDRY_PROJECT_ENDPOINT": "LUCY_FOUNDRY_PROJECT_ENDPOINT",
}

RESERVED_ENV_NAMES = {"APPLICATIONINSIGHTS_CONNECTION_STRING", "PORT"}


def _hosted_env_name(key: str) -> str | None:
    if key in HOSTED_ENV_ALIASES:
        return HOSTED_ENV_ALIASES[key]
    if key in RESERVED_ENV_NAMES or key.startswith("AGENT_") or key.startswith("FOUNDRY_"):
        return None
    return key


def _env_mapping(extra_keys: list[str], *, agent_name: str | None = None) -> dict[str, str]:
    keys = list(dict.fromkeys([*DEFAULT_ENV_KEYS, *extra_keys]))
    env: dict[str, str] = {}
    for key in keys:
        value = os.getenv(key)
        hosted_key = _hosted_env_name(key)
        if value and hosted_key:
            env[hosted_key] = value
    if agent_name:
        env["LUCY_OTEL_AGENT_ID"] = os.getenv("LUCY_HOSTED_OTEL_AGENT_ID", agent_name)
    env.setdefault("AZURE_TRACING_GEN_AI_CONTENT_RECORDING_ENABLED", "false")
    env.setdefault("LUCY_CHAINLIT_ENABLED", "false")
    env.setdefault("LUCY_DASHBOARD_ROUTES_ENABLED", "false")
    env.setdefault("OTEL_SERVICE_NAME", "lucy-hosted-agent")
    env.setdefault(
        "OTEL_RESOURCE_ATTRIBUTES",
        "service.name=lucy-hosted-agent,service.version=1.0.0",
    )
    return env


def _require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise SystemExit(f"Missing required environment variable: {name}")
    return value


def _status_value(version_info: Any) -> str:
    if isinstance(version_info, dict):
        return str(version_info.get("status") or "")
    status = getattr(version_info, "status", "")
    return str(getattr(status, "value", status) or "")


def main() -> int:
    try:
        from azure.ai.projects import AIProjectClient
        from azure.ai.projects.models import AgentProtocol, HostedAgentDefinition, ProtocolVersionRecord
        from azure.identity import DefaultAzureCredential
    except ImportError as exc:
        raise SystemExit(
            "Missing Azure Hosted Agent SDK dependencies. Install "
            "azure-ai-projects>=2.1.0 and azure-identity first."
        ) from exc

    endpoint = os.getenv("AZURE_AI_FOUNDRY_PROJECT_ENDPOINT") or _require_env(
        "AZURE_AI_PROJECT_ENDPOINT"
    )
    agent_name = os.getenv("LUCY_HOSTED_AGENT_NAME", "agent-lucy-hosted")
    image = _require_env("LUCY_HOSTED_IMAGE")
    cpu = os.getenv("LUCY_HOSTED_CPU", "1")
    memory = os.getenv("LUCY_HOSTED_MEMORY", "2Gi")
    protocol_version = os.getenv("LUCY_HOSTED_PROTOCOL_VERSION", "1.0.0")
    poll = os.getenv("LUCY_HOSTED_POLL", "true").lower() not in {"0", "false", "no"}
    extra_env_keys = [
        key.strip()
        for key in os.getenv("LUCY_HOSTED_EXTRA_ENV_KEYS", "").split(",")
        if key.strip()
    ]

    project = AIProjectClient(
        endpoint=endpoint,
        credential=DefaultAzureCredential(),
        allow_preview=True,
    )
    agent = project.agents.create_version(
        agent_name=agent_name,
        definition=HostedAgentDefinition(
            container_protocol_versions=[
                ProtocolVersionRecord(
                    protocol=AgentProtocol.RESPONSES,
                    version=protocol_version,
                )
            ],
            cpu=cpu,
            memory=memory,
            image=image,
            environment_variables=_env_mapping(extra_env_keys, agent_name=agent_name),
        ),
    )

    version = getattr(agent, "version", None) or (
        agent.get("version") if isinstance(agent, dict) else None
    )
    print(f"Hosted agent version created: name={agent_name} version={version} image={image}")

    if poll and version:
        while True:
            info = project.agents.get_version(agent_name=agent_name, agent_version=version)
            status = _status_value(info)
            print(f"Hosted agent status: {status}")
            if status in {"active", "failed", "deleted"}:
                return 0 if status == "active" else 1
            time.sleep(5)

    return 0


if __name__ == "__main__":
    sys.exit(main())
