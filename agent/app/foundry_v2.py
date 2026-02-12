import inspect
import logging
import os
from typing import Any, Callable, Optional, Union, get_args, get_origin

logger = logging.getLogger("FoundryV2")

try:
    from azure.ai.projects.models import (
        AzureAISearchAgentTool,
        AzureAISearchToolResource,
        AISearchIndexResource,
        AzureAISearchQueryType,
        FunctionTool,
        PromptAgentDefinition,
    )
    AZURE_PROJECTS_AVAILABLE = True
    _IMPORT_ERROR: Optional[Exception] = None
except Exception as exc:  # pragma: no cover - environment dependent
    AZURE_PROJECTS_AVAILABLE = False
    _IMPORT_ERROR = exc
    AzureAISearchAgentTool = None  # type: ignore[assignment]
    AzureAISearchToolResource = None  # type: ignore[assignment]
    AISearchIndexResource = None  # type: ignore[assignment]
    AzureAISearchQueryType = None  # type: ignore[assignment]
    FunctionTool = None  # type: ignore[assignment]
    PromptAgentDefinition = None  # type: ignore[assignment]

_QUERY_MAP = {
    "simple": "SIMPLE",
    "semantic": "SEMANTIC",
    "vector": "VECTOR",
    "vector_simple_hybrid": "VECTOR_SIMPLE_HYBRID",
    "vector_semantic_hybrid": "VECTOR_SEMANTIC_HYBRID",
}


def normalize_query_type(value: Optional[str]) -> str:
    query = (value or os.getenv("SEARCH_QUERY_TYPE") or "vector_semantic_hybrid").strip().lower()
    return _QUERY_MAP.get(query, "VECTOR_SEMANTIC_HYBRID").lower()


def _resolve_query_enum(query_type: Optional[str]):
    if not AZURE_PROJECTS_AVAILABLE:
        raise RuntimeError("Azure AI Projects SDK not available") from _IMPORT_ERROR

    normalized = normalize_query_type(query_type)
    enum_name = _QUERY_MAP.get(normalized, "VECTOR_SEMANTIC_HYBRID")
    return getattr(AzureAISearchQueryType, enum_name)


def build_ai_search_tool(
    connection_id: str,
    index_name: str,
    query_type: Optional[str] = None,
    top_k: Optional[int] = None,
    filter: Optional[str] = None,
):
    if not AZURE_PROJECTS_AVAILABLE:
        raise RuntimeError("Azure AI Projects SDK not available") from _IMPORT_ERROR

    if not connection_id:
        raise ValueError("connection_id is required for Azure AI Search tool")
    if not index_name:
        raise ValueError("index_name is required for Azure AI Search tool")

    query_enum = _resolve_query_enum(query_type)

    index_resource = AISearchIndexResource(
        project_connection_id=connection_id,
        index_name=index_name,
        query_type=query_enum,
    )
    if top_k is not None:
        index_resource.top_k = top_k
    if filter:
        index_resource.filter = filter

    return AzureAISearchAgentTool(
        azure_ai_search=AzureAISearchToolResource(indexes=[index_resource])
    )


def _normalize_annotation(annotation: Any) -> Any:
    if annotation is inspect._empty:
        return None
    origin = get_origin(annotation)
    if origin is Union:
        args = [arg for arg in get_args(annotation) if arg is not type(None)]  # noqa: E721
        if len(args) == 1:
            return args[0]
        return args
    return annotation


def _json_type_for_annotation(annotation: Any) -> str:
    normalized = _normalize_annotation(annotation)
    if normalized in (str,):
        return "string"
    if normalized in (int,):
        return "integer"
    if normalized in (float,):
        return "number"
    if normalized in (bool,):
        return "boolean"
    if normalized in (dict,):
        return "object"
    if normalized in (list, tuple, set):
        return "array"
    return "string"


def _build_function_schema(func: Callable[..., Any]) -> dict:
    signature = inspect.signature(func)
    properties: dict[str, dict] = {}
    required: list[str] = []

    for name, param in signature.parameters.items():
        if param.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
            continue
        annotation = param.annotation
        json_type = _json_type_for_annotation(annotation)
        properties[name] = {
            "type": json_type,
            "description": f"Parameter {name}",
        }
        if param.default is inspect._empty:
            required.append(name)

    schema: dict[str, Any] = {
        "type": "object",
        "properties": properties,
    }
    if required:
        schema["required"] = required
    return schema


def build_function_tools(functions: list[Callable[..., Any]]) -> list:
    if not AZURE_PROJECTS_AVAILABLE:
        raise RuntimeError("Azure AI Projects SDK not available") from _IMPORT_ERROR
    if FunctionTool is None:
        raise RuntimeError("FunctionTool not available in Azure AI Projects SDK")

    tools = []
    for func in functions:
        if not callable(func):
            continue
        name = getattr(func, "__name__", None) or "function"
        description = (inspect.getdoc(func) or "").strip().splitlines()[0] if inspect.getdoc(func) else ""
        if not description:
            description = f"Execute {name}"
        parameters = _build_function_schema(func)
        tools.append(
            FunctionTool(
                name=name,
                description=description,
                parameters=parameters,
                strict=False,
            )
        )
    return tools


def build_prompt_agent_definition(model: str, instructions: str, tools: list):
    if not AZURE_PROJECTS_AVAILABLE:
        raise RuntimeError("Azure AI Projects SDK not available") from _IMPORT_ERROR

    return PromptAgentDefinition(
        model=model,
        instructions=instructions,
        tools=tools,
    )


def build_agent_reference(agent_name: str, agent_version: str):
    return {
        "agent": {
            "type": "agent_reference",
            "name": agent_name,
            "version": agent_version,
        }
    }
