"""Foundry Hosted Agent Responses adapter for Lucy.

The hosted process is intentionally thin: it translates the Foundry Responses
protocol request/context into `LucyRequest`, calls `LucyRuntime.respond()`, and
streams the resulting Lucy text plus portable metadata back through the
protocol library.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import os
import sys
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, AsyncIterator, Callable, Iterable


_PACKAGE_PARENT = Path(__file__).resolve().parents[1]
_REPO_APP_ROOT = _PACKAGE_PARENT / "app"
APP_ROOT = _REPO_APP_ROOT if _REPO_APP_ROOT.exists() else _PACKAGE_PARENT
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from lucy_core.runtime import LucyRuntime  # noqa: E402
from lucy_core.runtime_factory import default_runtime_factory  # noqa: E402
from lucy_core.session import LucyArtifact, LucyRequest, LucyResponse, LucySession  # noqa: E402

logger = logging.getLogger(__name__)

try:  # pragma: no cover - exercised in the hosted container
    from azure.ai.agentserver.responses import ResponseEventStream, ResponsesAgentServerHost
except Exception as exc:  # pragma: no cover - local tests should not need preview SDK
    ResponseEventStream = None  # type: ignore[assignment]
    ResponsesAgentServerHost = None  # type: ignore[assignment]
    _SDK_IMPORT_ERROR: Exception | None = exc
else:  # pragma: no cover
    _SDK_IMPORT_ERROR = None


RuntimeFactory = Callable[[], LucyRuntime | Any]

_runtime: LucyRuntime | None = None
_runtime_lock = asyncio.Lock()
_TRUE_VALUES = {"1", "true", "yes", "y", "on"}


def apply_hosted_env_aliases() -> None:
    """Restore Lucy's legacy env names from Hosted-safe aliases.

    Foundry Hosted Agents reserve `AGENT_*`, `FOUNDRY_*`,
    `APPLICATIONINSIGHTS_CONNECTION_STRING`, and `PORT` for platform use. Lucy's
    existing runtime still reads a few `AGENT_PORTAL_*` / `FOUNDRY_*` names from
    apex.py and user_functions.py, so the hosted deployment passes them as
    `LUCY_*` aliases and remaps them inside the container before apex imports.
    """
    aliases = {
        "LUCY_AGENT_PORTAL_ENABLED": "AGENT_PORTAL_ENABLED",
        "LUCY_AGENT_PORTAL_URL": "AGENT_PORTAL_URL",
        "LUCY_AGENT_PORTAL_API_TOKEN": "AGENT_PORTAL_API_TOKEN",
        "LUCY_AGENT_PORTAL_PORT": "AGENT_PORTAL_PORT",
        "LUCY_FOUNDRY_AGENT_NAME": "FOUNDRY_AGENT_NAME",
        "LUCY_FOUNDRY_APPLICATION_NAME": "FOUNDRY_APPLICATION_NAME",
        "LUCY_FOUNDRY_PROJECT_ENDPOINT": "FOUNDRY_PROJECT_ENDPOINT",
    }
    for source, target in aliases.items():
        value = os.getenv(source)
        if value and not os.getenv(target):
            os.environ[target] = value


def _as_mapping(value: Any) -> dict[str, Any]:
    """Best-effort conversion of SDK models or dicts into plain mappings."""
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    if is_dataclass(value):
        return asdict(value)
    if hasattr(value, "as_dict"):
        try:
            maybe = value.as_dict()
            if isinstance(maybe, dict):
                return dict(maybe)
        except Exception:
            pass
    if hasattr(value, "model_dump"):
        try:
            maybe = value.model_dump()
            if isinstance(maybe, dict):
                return dict(maybe)
        except Exception:
            pass
    return {}


def _strict_bool(value: Any) -> bool:
    """Parse untrusted Hosted metadata without Python truthiness surprises."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value == 1
    if isinstance(value, str):
        return value.strip().lower() in _TRUE_VALUES
    return False


def _metadata_from_request(request: Any) -> dict[str, Any]:
    metadata = getattr(request, "metadata", None)
    if metadata is None:
        metadata = _as_mapping(request).get("metadata")
    return _as_mapping(metadata)


def _conversation_id_from(request: Any, context: Any, metadata: dict[str, Any]) -> str | None:
    conversation_id = getattr(context, "conversation_id", None)
    if conversation_id:
        return str(conversation_id)
    conversation = getattr(request, "conversation", None)
    if isinstance(conversation, str) and conversation:
        return conversation
    conversation_mapping = _as_mapping(conversation)
    if conversation_mapping.get("id"):
        return str(conversation_mapping["id"])
    if metadata.get("conversation_id"):
        return str(metadata["conversation_id"])
    return None


def _previous_response_id_from(request: Any, context: Any, metadata: dict[str, Any]) -> str | None:
    previous_response_id = getattr(context, "previous_response_id", None)
    if not previous_response_id:
        previous_response_id = getattr(context, "_previous_response_id", None)
    if not previous_response_id:
        previous_response_id = getattr(request, "previous_response_id", None)
    if not previous_response_id:
        previous_response_id = _as_mapping(request).get("previous_response_id")
    if not previous_response_id:
        previous_response_id = metadata.get("previous_response_id")
    return str(previous_response_id) if previous_response_id else None


def _inner_response_id(value: Any) -> str | None:
    """Return only inner prompt-agent Responses IDs, never Hosted wrapper IDs."""
    if not value:
        return None
    response_id = str(value)
    if response_id.startswith("resp_"):
        return response_id
    return None


def _session_id_from(context: Any, metadata: dict[str, Any], conversation_id: str | None) -> str:
    lucy_session = _as_mapping(metadata.get("lucy_session"))
    for value in (
        lucy_session.get("session_id"),
        metadata.get("lucy_session_id"),
        getattr(getattr(context, "isolation", None), "chat_key", None),
        conversation_id,
        getattr(context, "response_id", None),
    ):
        if value:
            return str(value)
    return "hosted-session"


async def _input_text_from(request: Any, context: Any) -> str:
    getter = getattr(context, "get_input_text", None)
    if callable(getter):
        maybe = getter()
        return await maybe if inspect.isawaitable(maybe) else str(maybe or "")

    raw_input = getattr(request, "input", None)
    if raw_input is None:
        raw_input = _as_mapping(request).get("input")
    if isinstance(raw_input, str):
        return raw_input
    if isinstance(raw_input, list):
        texts: list[str] = []
        for item in raw_input:
            item_map = _as_mapping(item)
            content = item_map.get("content")
            if isinstance(content, str):
                texts.append(content)
            elif isinstance(content, list):
                for part in content:
                    part_map = _as_mapping(part)
                    text = part_map.get("text")
                    if text:
                        texts.append(str(text))
        return "\n".join(texts)
    return ""


async def request_to_lucy_request(request: Any, context: Any) -> LucyRequest:
    """Map a Foundry CreateResponse request/context into Lucy's runtime input."""
    metadata = _metadata_from_request(request)
    lucy_session_meta = _as_mapping(metadata.get("lucy_session"))
    foundry_conversation_id = _conversation_id_from(request, context, metadata)
    foundry_previous_response_id = _previous_response_id_from(request, context, metadata)
    request_previous_response_id = (
        getattr(request, "previous_response_id", None)
        or _as_mapping(request).get("previous_response_id")
    )
    inner_conversation_id = lucy_session_meta.get("conversation_id")
    inner_previous_response_id = (
        _inner_response_id(lucy_session_meta.get("previous_response_id"))
        or _inner_response_id(request_previous_response_id)
        or _inner_response_id(foundry_previous_response_id)
    )
    session = LucySession(
        session_id=_session_id_from(context, metadata, foundry_conversation_id),
        conversation_id=inner_conversation_id,
        previous_response_id=inner_previous_response_id,
        last_eval_final_response_id=lucy_session_meta.get("last_eval_final_response_id"),
        authenticated=_strict_bool(
            lucy_session_meta.get("authenticated", metadata.get("authenticated"))
        ),
        apex_id=lucy_session_meta.get("apex_id") or metadata.get("apex_id"),
        user_name=lucy_session_meta.get("user_name") or metadata.get("user_name"),
        metadata={
            **_as_mapping(lucy_session_meta.get("metadata")),
            "foundry_response_id": getattr(context, "response_id", None),
            "foundry_conversation_id": foundry_conversation_id,
            "foundry_previous_response_id": foundry_previous_response_id,
        },
    )
    pending_notice_request = (
        lucy_session_meta.get("pending_notice_request")
        if "pending_notice_request" in lucy_session_meta
        else metadata.get("pending_notice_request")
    )
    if pending_notice_request is not None:
        session.metadata["pending_notice_request"] = _strict_bool(pending_notice_request)
    pending_notice_text = lucy_session_meta.get("pending_notice_request_text") or metadata.get(
        "pending_notice_request_text"
    )
    if pending_notice_text:
        session.metadata["pending_notice_request_text"] = str(pending_notice_text)

    return LucyRequest(
        input_text=await _input_text_from(request, context),
        session=session,
        metadata=metadata,
    )


def _artifact_to_dict(artifact: LucyArtifact) -> dict[str, Any]:
    return {
        "type": artifact.type,
        "label": artifact.label,
        "url": artifact.url,
        "blob_url": artifact.blob_url,
        "expires_at": artifact.expires_at,
        "metadata": dict(artifact.metadata),
    }


def lucy_response_metadata(response: LucyResponse) -> dict[str, Any]:
    """Create Foundry response metadata preserving Lucy-specific state."""
    session = response.session
    return {
        "lucy_session": {
            "session_id": session.session_id,
            "conversation_id": session.conversation_id,
            "previous_response_id": session.previous_response_id,
            "last_eval_final_response_id": session.last_eval_final_response_id,
            "authenticated": session.authenticated,
            "apex_id": session.apex_id,
            "user_name": session.user_name,
            "metadata": dict(session.metadata),
        },
        "lucy_artifacts": [_artifact_to_dict(artifact) for artifact in response.artifacts],
        "lucy_tool_calls": list(response.tool_calls),
        "lucy_handoff": response.handoff,
        "lucy_trace_id": response.trace_id,
        "lucy_errors": list(response.errors),
    }


def _merge_response_metadata(stream: Any, request: Any, response: LucyResponse) -> None:
    existing = _metadata_from_request(request)
    merged = {**existing, **lucy_response_metadata(response)}
    try:
        stream.response.metadata = merged
    except Exception:
        logger.debug("Hosted response stream metadata assignment failed", exc_info=True)


def lucy_response_to_events(
    response: LucyResponse,
    request: Any,
    context: Any,
    *,
    stream_cls: Any = None,
) -> Iterable[Any]:
    """Convert a LucyResponse into Responses protocol stream events."""
    stream_cls = stream_cls or ResponseEventStream
    if stream_cls is None:
        raise RuntimeError("azure-ai-agentserver-responses is not installed")
    stream = stream_cls(response_id=getattr(context, "response_id", None), request=request)
    _merge_response_metadata(stream, request, response)

    yield stream.emit_created()
    yield stream.emit_in_progress()
    yield from stream.output_item_message(response.text or "")
    yield stream.emit_completed()


async def get_runtime(runtime_factory: RuntimeFactory = default_runtime_factory) -> LucyRuntime:
    """Initialize LucyRuntime once per hosted process."""
    global _runtime  # pylint: disable=global-statement
    if _runtime is not None:
        return _runtime
    async with _runtime_lock:
        if _runtime is not None:
            return _runtime
        apply_hosted_env_aliases()
        result = runtime_factory()
        if inspect.isawaitable(result):
            result = await result
        _runtime = result
        return _runtime


async def handle_response(request: Any, context: Any, _cancellation_signal: Any) -> AsyncIterator[Any]:
    """Hosted Agent response handler registered with ResponsesAgentServerHost."""
    response_id = getattr(context, "response_id", None)
    stream_cls = ResponseEventStream
    if stream_cls is None:
        raise RuntimeError(f"azure-ai-agentserver-responses import failed: {_SDK_IMPORT_ERROR}")

    try:
        lucy_request = await request_to_lucy_request(request, context)
        runtime = await get_runtime()
        lucy_response = await runtime.respond(lucy_request)
        for event in lucy_response_to_events(
            lucy_response,
            request,
            context,
            stream_cls=stream_cls,
        ):
            yield event
    except Exception as exc:
        logger.exception("Hosted Agent Lucy response failed")
        stream = stream_cls(response_id=response_id, request=request)
        yield stream.emit_created()
        yield stream.emit_failed(message=str(exc))


def create_app() -> Any:
    """Create the protocol host used by Foundry Hosted Agent runtime."""
    if ResponsesAgentServerHost is None:
        raise RuntimeError(f"azure-ai-agentserver-responses import failed: {_SDK_IMPORT_ERROR}")
    app = ResponsesAgentServerHost()

    async def liveness(_request: Any) -> Any:
        from starlette.responses import JSONResponse

        return JSONResponse({"status": "alive"})

    app.add_route("/liveness", liveness, methods=["GET"])
    app.add_route("/health", liveness, methods=["GET"])
    app.response_handler(handle_response)
    return app


app = create_app() if ResponsesAgentServerHost is not None else None


if __name__ == "__main__":  # pragma: no cover
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
    create_app().run()
