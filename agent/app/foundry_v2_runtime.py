import os
from typing import Optional


def _truthy(value: Optional[str]) -> bool:
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "on"}


def use_foundry_v2() -> bool:
    explicit = os.getenv("USE_FOUNDRY_V2")
    if explicit is not None:
        return _truthy(explicit)
    return _truthy(os.getenv("AZURE_RESPONSES_ENABLED", "true"))


def resolve_search_connection_id(
    connection_id: Optional[str],
    connection_name: Optional[str],
    project_client,
) -> str:
    if connection_id:
        return connection_id
    if not connection_name:
        raise ValueError("AI Search connection id or name is required")
    connection = project_client.connections.get(connection_name)
    return connection.id


def build_response_payload(
    conversation_id: str,
    user_input: str,
    agent_name: str,
    agent_version: str,
) -> dict:
    if not conversation_id:
        raise ValueError("conversation_id is required")
    if not user_input:
        raise ValueError("user_input is required")
    if not agent_name or not agent_version:
        raise ValueError("agent_name and agent_version are required")
    return {
        "conversation": conversation_id,
        "input": user_input,
        "extra_body": {
            "agent_reference": {
                "type": "agent_reference",
                "name": agent_name,
                "version": agent_version,
            }
        },
    }


def get_project_openai_client(project_client):
    getter = getattr(project_client, "get_openai_client", None)
    if callable(getter):
        return getter()
    raise AttributeError(
        "AIProjectClient.get_openai_client is missing. "
        "Upgrade azure-ai-projects to >= 1.0.0."
    )


def get_startup_mode_snapshot() -> dict:
    return {
        "use_foundry_v2": use_foundry_v2(),
        "project_endpoint_set": bool(
            os.getenv("AZURE_AI_FOUNDRY_PROJECT_ENDPOINT")
            or os.getenv("AZURE_AI_PROJECT_ENDPOINT")
        ),
        "search_connection_id_set": bool(os.getenv("AI_SEARCH_PROJECT_CONNECTION_ID")),
        "search_connection_name_set": bool(
            os.getenv("AI_SEARCH_PROJECT_CONNECTION_NAME")
            or os.getenv("AI_AZURE_AI_CONNECTION_ID")
        ),
        "model_deployment_name": os.getenv("MODEL_DEPLOYMENT_NAME")
        or os.getenv("AZURE_AGENT_MODEL")
        or os.getenv("AZURE_GPT_MODEL"),
    }
