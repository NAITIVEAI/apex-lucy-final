"""Foundry v2 agent initialization — Chainlit-free.

Builds the Azure project client, OpenAI client, agent registry, registers/
reconciles the published agent version, and returns an initialized
FoundryInitContext that adapters can use to construct a LucyRuntime.

Extracted from agent/app/apex.py:_initialize_persistent_agent_v2 to enable
non-Chainlit invocation paths (e.g. the FastAPI HTTP wrapper that registers
behind the Foundry AI Gateway in plan 002 Phase A).

Pure dependency injection — caller provides instructions, function list,
function registry, toolset signature, and prompt hash. This module never
reaches into apex.py or imports Chainlit.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from typing import Any, Optional

from agent_registry import AgentRegistry
from foundry_publish import (
    PublishedDeploymentState,
    get_application_name,
    get_latest_published_deployment_state,
    get_published_deployment_state,
    parse_project_scope_from_connection_id,
    reconcile_managed_publication,
    select_effective_agent_version,
)
from foundry_v2 import (
    build_ai_search_tool,
    build_function_tools,
    build_prompt_agent_definition,
)
from foundry_v2_runtime import (
    get_project_openai_client,
    resolve_search_connection_id,
)
from prompt_utils import prompt_hash_changed

logger = logging.getLogger(__name__)

_INDEX_NAME_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,126}[a-z0-9])?$")


# --- env-reader helpers --------------------------------------------------------

def get_model_deployment_name() -> str:
    return (
        os.getenv("MODEL_DEPLOYMENT_NAME")
        or os.getenv("AZURE_AGENT_MODEL")
        or os.getenv("AZURE_GPT_MODEL")
        or "gpt-4.1"
    )


def get_agent_reasoning_effort(model_deployment: Optional[str] = None) -> str:
    """Reasoning effort persisted into the Foundry prompt-agent version.

    The project Responses request references a stored agent version, so the
    latency/cost knob has to be captured on the agent definition itself. GPT-5.2
    currently rejects non-medium reasoning at invocation time even when agent
    creation accepts the definition, so keep that deployment on medium.
    """
    model = (model_deployment or get_model_deployment_name() or "").strip().lower()
    explicit = (
        os.getenv("AZURE_AGENT_REASONING_EFFORT")
        or os.getenv("AZURE_RESPONSES_REASONING_EFFORT")
        or ""
    ).strip().lower()

    if model.startswith("gpt-5.2"):
        if explicit and explicit != "medium":
            logger.warning(
                "Ignoring unsupported reasoning effort %s for %s; using medium",
                explicit,
                model,
            )
        return "medium"

    if not explicit and model.startswith("gpt-5"):
        return "medium"
    return explicit


def get_agent_name() -> str:
    return os.getenv("FOUNDRY_AGENT_NAME") or "lucy"


def get_application_name_for_agent() -> str:
    return get_application_name(get_agent_name())


def _normalize_search_index_name(value: str) -> str:
    cleaned = (value or "").strip().lower()
    if not cleaned:
        return ""
    if cleaned != value:
        logger.warning("Normalized search index name from '%s' to '%s'", value, cleaned)
    if not _INDEX_NAME_PATTERN.match(cleaned):
        raise ValueError(
            "AI Search index name must be lowercase letters, digits, or dashes, "
            "not start/end with a dash, and be <= 128 characters."
        )
    return cleaned


def get_search_index_name() -> str:
    raw = os.getenv("AI_SEARCH_INDEX_NAME") or os.getenv("AZURE_SEARCH_INDEX_NAME") or ""
    return _normalize_search_index_name(raw)


def get_search_connection_id_env() -> Optional[str]:
    return os.getenv("AI_SEARCH_PROJECT_CONNECTION_ID")


def get_search_connection_name_env() -> Optional[str]:
    return (
        os.getenv("AI_SEARCH_PROJECT_CONNECTION_NAME")
        or os.getenv("AI_AZURE_AI_CONNECTION_ID")
    )


def fallback_publication_state(
    application_name: str,
    agent_name_value: str,
    agent_version_value: str,
) -> PublishedDeploymentState:
    return PublishedDeploymentState(
        application_name=application_name,
        deployment_name="",
        deployment_id="",
        agent_name=agent_name_value,
        agent_version=str(agent_version_value),
    )


# --- result type ---------------------------------------------------------------

@dataclass
class FoundryInitContext:
    """Initialized Foundry v2 runtime state. Constructed by initialize_foundry_v2_agent."""
    project_client: Any
    openai_client: Any
    agent_registry: AgentRegistry
    agent_name: str
    agent_version: str
    function_registry: dict[str, Any]


# --- main init flow ------------------------------------------------------------

async def initialize_foundry_v2_agent(
    *,
    instructions: str,
    function_list: list[Any],
    function_registry: dict[str, Any],
    toolset_signature: str,
    prompt_hash: str,
    existing_agent_registry: Optional[AgentRegistry] = None,
) -> FoundryInitContext:
    """Initialize Foundry v2 agent and return initialized context.

    Creates an Azure project client + OpenAI client, registers the agent version
    with Foundry, reconciles managed publication, and persists state to the
    agent registry. Returns FoundryInitContext for the caller to wire into a
    LucyRuntime or its module globals.

    `instructions`: system prompt the agent will use.
    `function_list`: tool callables (used to build tool schemas for Foundry).
    `function_registry`: name->callable mapping (carried verbatim into the result).
    `toolset_signature`: hex digest of the toolset; used to detect drift.
    `prompt_hash`: hash of the system prompt; used to detect drift.
    `existing_agent_registry`: reuse an already-instantiated AgentRegistry
        (preserves connection caching across init calls); otherwise a new one
        is constructed.
    """
    project_endpoint = (
        os.getenv("AZURE_AI_FOUNDRY_PROJECT_ENDPOINT")
        or os.getenv("AZURE_AI_PROJECT_ENDPOINT")
    )
    if not project_endpoint:
        raise ValueError("AZURE_AI_FOUNDRY_PROJECT_ENDPOINT is required for Foundry v2")

    from azure.identity import DefaultAzureCredential, ManagedIdentityCredential
    from azure.ai.projects import AIProjectClient

    is_container = any(
        [
            os.getenv("CONTAINER_APP_NAME"),
            os.getenv("CONTAINER_APP_REVISION"),
            os.getenv("WEBSITE_SITE_NAME"),
            os.getenv("WEBSITES_PORT"),
            os.getenv("KUBERNETES_SERVICE_HOST"),
            os.path.exists("/.dockerenv"),
        ]
    )
    if is_container:
        logger.info("Container environment detected. Using managed identity for Foundry v2.")
        managed_identity_client_id = os.getenv("MANAGED_IDENTITY_CLIENT_ID")
        if managed_identity_client_id:
            credential = ManagedIdentityCredential(client_id=managed_identity_client_id)
        else:
            credential = ManagedIdentityCredential()
    else:
        credential = DefaultAzureCredential(exclude_interactive_browser_credential=True)

    project_client = AIProjectClient(endpoint=project_endpoint, credential=credential)
    openai_client = get_project_openai_client(project_client)

    agent_registry = existing_agent_registry or AgentRegistry()
    registry_partition = get_agent_name()
    application_name = get_application_name_for_agent()
    model_deployment = get_model_deployment_name()
    reasoning_effort = get_agent_reasoning_effort(model_deployment)
    search_index_name = get_search_index_name()
    if not search_index_name:
        raise ValueError("AI_SEARCH_INDEX_NAME (or AZURE_SEARCH_INDEX_NAME) is required")

    connection_id = resolve_search_connection_id(
        get_search_connection_id_env(),
        get_search_connection_name_env(),
        project_client,
    )
    project_scope = parse_project_scope_from_connection_id(connection_id)
    query_type = os.getenv("SEARCH_QUERY_TYPE")
    top_k = os.getenv("SEARCH_TOP_K")
    top_k_value = int(top_k) if top_k and top_k.isdigit() else None

    record = agent_registry.get_agent_record(registry_partition, "persistent")
    published_state = None
    latest_published_state = None
    try:
        published_state = get_published_deployment_state(
            project_scope,
            application_name,
            credential,
        )
        latest_published_state = get_latest_published_deployment_state(
            project_scope,
            application_name,
            credential,
            agent_name=registry_partition,
        )
    except Exception as publish_error:
        logger.warning("⚠️ Failed to read Foundry publication state: %s", publish_error)

    if record and record.get("agent_name") and record.get("agent_version"):
        mismatch_reasons: list[str] = []
        if record.get("search_index_name") != search_index_name:
            mismatch_reasons.append("search_index_name")
        if record.get("search_connection_id") != connection_id:
            mismatch_reasons.append("search_connection_id")
        if record.get("model_deployment") != model_deployment:
            mismatch_reasons.append("model_deployment")
        if str(record.get("reasoning_effort") or "") != reasoning_effort:
            mismatch_reasons.append("reasoning_effort")
        if record.get("query_type") != (query_type or ""):
            mismatch_reasons.append("query_type")
        if str(record.get("top_k") or "") != (str(top_k_value) if top_k_value is not None else ""):
            mismatch_reasons.append("top_k")
        if record.get("toolset_signature") != toolset_signature:
            mismatch_reasons.append("toolset_signature")
        if prompt_hash_changed(record, prompt_hash):
            mismatch_reasons.append("prompt_hash")

        if (
            published_state
            and str(record.get("agent_version") or "") != published_state.agent_version
        ):
            logger.warning(
                "⚠️ Foundry registry drift detected: table=%s:%s published=%s:%s deployment=%s",
                record.get("agent_name"),
                record.get("agent_version"),
                published_state.agent_name,
                published_state.agent_version,
                published_state.deployment_name,
            )
        if (
            latest_published_state
            and published_state
            and latest_published_state.agent_version != published_state.agent_version
        ):
            logger.warning(
                "⚠️ Foundry application routing is stale: active=%s latest=%s",
                published_state.agent_version,
                latest_published_state.agent_version,
            )

        effective_version = select_effective_agent_version(
            record,
            published_state,
            mismatch_reasons,
            latest_published_state,
        )
        if effective_version:
            try:
                publication_state = reconcile_managed_publication(
                    project_scope,
                    application_name,
                    registry_partition,
                    effective_version,
                    credential,
                )
            except Exception as publish_error:
                logger.warning(
                    "⚠️ Foundry publication reconciliation failed; using project agent version directly: %s",
                    publish_error,
                )
                publication_state = fallback_publication_state(
                    application_name,
                    registry_partition,
                    effective_version,
                )
            agent_name_value = registry_partition
            agent_version_value = publication_state.agent_version
            agent_registry.upsert_agent_record(
                registry_partition,
                "persistent",
                {
                    "agent_name": agent_name_value,
                    "agent_version": agent_version_value,
                    "application_name": publication_state.application_name,
                    "deployment_name": publication_state.deployment_name,
                    "deployment_id": publication_state.deployment_id,
                    "search_index_name": search_index_name,
                    "search_connection_id": connection_id,
                    "model_deployment": model_deployment,
                    "reasoning_effort": reasoning_effort,
                    "query_type": query_type or "",
                    "top_k": top_k_value if top_k_value is not None else "",
                    "toolset_signature": toolset_signature,
                    "prompt_hash": prompt_hash,
                },
            )
            logger.info(
                "✅ Foundry v2 agent loaded from reconciled publication state: %s:%s (%s/%s)",
                agent_name_value,
                agent_version_value,
                publication_state.application_name,
                publication_state.deployment_name,
            )
            return FoundryInitContext(
                project_client=project_client,
                openai_client=openai_client,
                agent_registry=agent_registry,
                agent_name=agent_name_value,
                agent_version=agent_version_value,
                function_registry=function_registry,
            )

        logger.warning(
            "Foundry v2 agent config mismatch (%s). Recreating agent.",
            ", ".join(mismatch_reasons),
        )

    ai_search_tool_v2 = build_ai_search_tool(
        connection_id=connection_id,
        index_name=search_index_name,
        query_type=query_type,
        top_k=top_k_value,
    )
    function_tools = build_function_tools(function_list)
    logger.info("✅ V2 toolset prepared (functions=%s)", len(function_registry))

    agent_definition = build_prompt_agent_definition(
        model=model_deployment,
        instructions=instructions,
        tools=[ai_search_tool_v2] + function_tools,
        reasoning_effort=reasoning_effort,
    )

    try:
        new_agent = project_client.agents.create_version(
            agent_name=registry_partition,
            definition=agent_definition,
            description="Lucy Foundry v2 prompt agent",
        )
    except Exception as create_error:
        error_text = str(create_error).lower()
        should_retry_medium = (
            bool(reasoning_effort)
            and reasoning_effort != "medium"
            and ("reasoning" in error_text or "effort" in error_text)
        )
        if not should_retry_medium:
            raise

        logger.warning(
            "Foundry rejected reasoning effort %s for %s; retrying agent "
            "version creation with medium.",
            reasoning_effort,
            model_deployment,
        )
        reasoning_effort = "medium"
        agent_definition = build_prompt_agent_definition(
            model=model_deployment,
            instructions=instructions,
            tools=[ai_search_tool_v2] + function_tools,
            reasoning_effort=reasoning_effort,
        )
        new_agent = project_client.agents.create_version(
            agent_name=registry_partition,
            definition=agent_definition,
            description="Lucy Foundry v2 prompt agent",
        )

    agent_name_value = new_agent.name
    try:
        publication_state = reconcile_managed_publication(
            project_scope,
            application_name,
            registry_partition,
            str(new_agent.version),
            credential,
        )
    except Exception as publish_error:
        logger.warning(
            "⚠️ Foundry publication creation failed; continuing with project agent version directly: %s",
            publish_error,
        )
        publication_state = fallback_publication_state(
            application_name,
            registry_partition,
            str(new_agent.version),
        )
    agent_version_value = publication_state.agent_version
    agent_registry.upsert_agent_record(
        registry_partition,
        "persistent",
        {
            "agent_name": agent_name_value,
            "agent_version": agent_version_value,
            "application_name": publication_state.application_name,
            "deployment_name": publication_state.deployment_name,
            "deployment_id": publication_state.deployment_id,
            "search_index_name": search_index_name,
            "search_connection_id": connection_id,
            "model_deployment": model_deployment,
            "reasoning_effort": reasoning_effort,
            "query_type": query_type or "",
            "top_k": top_k_value if top_k_value is not None else "",
            "toolset_signature": toolset_signature,
            "prompt_hash": prompt_hash,
        },
    )
    logger.info(
        "✅ Created Foundry v2 agent %s:%s and reconciled application %s deployment %s",
        agent_name_value,
        agent_version_value,
        publication_state.application_name,
        publication_state.deployment_name,
    )
    return FoundryInitContext(
        project_client=project_client,
        openai_client=openai_client,
        agent_registry=agent_registry,
        agent_name=agent_name_value,
        agent_version=agent_version_value,
        function_registry=function_registry,
    )
