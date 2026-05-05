"""Responses-API loop for the Lucy runtime core.

Extracted from agent/app/apex.py to enable invocation from any adapter
(Chainlit, FastAPI HTTP wrapper, evals). All runtime dependencies are passed
as parameters — no module-level globals, no Chainlit imports.

Public surface:
- build_authenticated_state_items(session)
- extract_v2_function_calls(response)
- execute_v2_tool_call(name, arguments, function_registry)
- run_response_v2(user_text, session, openai_client, agent_name, agent_version, function_registry)

The agent-side helpers (response_utils.extract_response_text, foundry_v2_runtime.build_response_payload,
foundry_v2.build_agent_reference, response_config.should_include_max_output_tokens) are imported
by name. They live in agent/app/ and are added to sys.path by the agent service entry script.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import os
import time
import uuid
from typing import Any, Optional

from .session import LucySession

# Agent-side helpers (Chainlit-free) — agent/app/ is on sys.path at runtime
from response_utils import extract_response_text
from foundry_v2_runtime import build_response_payload
from foundry_v2 import build_agent_reference
from response_config import should_include_max_output_tokens

# OpenTelemetry — emits GenAI semantic-convention spans that Foundry's Monitor
# tab filters on (gen_ai.agent.id). When the OTel SDK isn't initialized, the
# tracer returns a no-op span — safe in tests and dev environments.
from opentelemetry import trace as _otel_trace
from opentelemetry.trace import SpanKind, Status, StatusCode

_tracer = _otel_trace.get_tracer("lucy_core.responses_loop")
_metric_meter: Any | None = None
_metric_provider: Any | None = None
_metric_instruments: dict[str, Any] = {}

logger = logging.getLogger(__name__)

_AGENT_OPERATION_NAME = "create_agent"
_INFERENCE_OPERATION_NAME = "chat"


def _get_model_deployment_name() -> str:
    return (
        os.getenv("MODEL_DEPLOYMENT_NAME")
        or os.getenv("AZURE_AGENT_MODEL")
        or os.getenv("AZURE_GPT_MODEL")
        or ""
    ).strip()


def _uses_agent_reference(payload: dict[str, Any]) -> bool:
    if "agent_reference" in payload or "agent" in payload:
        return True
    extra_body = payload.get("extra_body")
    return isinstance(extra_body, dict) and (
        "agent_reference" in extra_body or "agent" in extra_body
    )


def _apply_request_reasoning(payload: dict[str, Any]) -> None:
    reasoning_effort = os.getenv("AZURE_RESPONSES_REASONING_EFFORT", "").strip().lower()
    model = _get_model_deployment_name().lower()

    if _uses_agent_reference(payload):
        payload.pop("reasoning", None)
        return

    if model.startswith("gpt-5.2") and reasoning_effort and reasoning_effort != "medium":
        logger.warning(
            "Ignoring unsupported request reasoning effort %s for %s; using SDK default",
            reasoning_effort,
            model,
        )
        payload.pop("reasoning", None)
        return

    if reasoning_effort:
        payload["reasoning"] = {"effort": reasoning_effort}


def _truncate_span_value(value: Any, *, limit: int = 2048) -> str:
    """Keep span attributes bounded; Application Insights rejects huge values."""
    text = value if isinstance(value, str) else str(value)
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def _content_recording_enabled() -> bool:
    return (
        os.getenv("AZURE_TRACING_GEN_AI_CONTENT_RECORDING_ENABLED", "false").lower()
        in {"1", "true", "yes", "on"}
    )


def _response_value(source: Any, key: str) -> Any:
    if isinstance(source, dict):
        return source.get(key)
    return getattr(source, key, None)


def _first_response_value(source: Any, *keys: str) -> Any:
    for key in keys:
        value = _response_value(source, key)
        if value is not None:
            return value
    return None


def _coerce_token_count(value: Any) -> Optional[int]:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        if text.isdigit():
            return int(text)
    return None


def collect_response_telemetry(response: Any) -> dict[str, Any]:
    """Collect non-content GenAI telemetry from a Responses API response."""
    telemetry: dict[str, Any] = {}

    response_id = _response_value(response, "id")
    if response_id:
        telemetry["gen_ai.response.id"] = str(response_id)

    model = _first_response_value(response, "model", "deployment", "deployment_name")
    if model:
        telemetry["gen_ai.response.model"] = str(model)

    usage = _response_value(response, "usage")
    input_tokens = _coerce_token_count(
        _first_response_value(usage, "input_tokens", "prompt_tokens")
    )
    output_tokens = _coerce_token_count(
        _first_response_value(usage, "output_tokens", "completion_tokens")
    )
    total_tokens = _coerce_token_count(
        _first_response_value(usage, "total_tokens", "total")
    )
    if total_tokens is None and input_tokens is not None and output_tokens is not None:
        total_tokens = input_tokens + output_tokens

    if input_tokens is not None:
        telemetry["gen_ai.usage.input_tokens"] = input_tokens
    if output_tokens is not None:
        telemetry["gen_ai.usage.output_tokens"] = output_tokens
    if total_tokens is not None:
        telemetry["gen_ai.usage.total_tokens"] = total_tokens

    return telemetry


def _set_response_telemetry(span: Any, telemetry: dict[str, Any]) -> None:
    for key, value in telemetry.items():
        if value is not None:
            span.set_attribute(key, value)


def _otel_resource_attributes() -> dict[str, str]:
    attributes: dict[str, str] = {}
    for item in os.getenv("OTEL_RESOURCE_ATTRIBUTES", "").split(","):
        if "=" not in item:
            continue
        key, value = item.split("=", 1)
        key = key.strip()
        if key:
            attributes[key] = value.strip()
    return attributes


def _foundry_project_id() -> str:
    for key in (
        "MICROSOFT_FOUNDRY_PROJECT_ID",
        "AZURE_AI_FOUNDRY_PROJECT_ID",
        "AZURE_AI_PROJECT_ID",
    ):
        value = os.getenv(key, "").strip()
        if value:
            return value

    connection_id = os.getenv("AI_SEARCH_PROJECT_CONNECTION_ID", "").strip()
    marker = "/connections/"
    if marker in connection_id:
        return connection_id.split(marker, 1)[0]
    return ""


def _genai_metric_meter() -> Any | None:
    """Return a dedicated Azure Monitor meter for GenAI dashboard metrics."""
    global _metric_meter, _metric_provider
    if _metric_meter is not None:
        return _metric_meter

    connection_string = os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING", "").strip()
    if not connection_string:
        return None

    try:
        from azure.monitor.opentelemetry.exporter import AzureMonitorMetricExporter
        from opentelemetry.sdk.metrics import MeterProvider
        from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
        from opentelemetry.sdk.resources import Resource, SERVICE_NAME, SERVICE_VERSION
    except Exception:
        logger.debug("Azure Monitor metric exporter unavailable", exc_info=True)
        return None

    resource_values = {
        SERVICE_NAME: os.getenv("OTEL_SERVICE_NAME", "lucy-hosted-agent"),
        SERVICE_VERSION: os.getenv("LUCY_VERSION", "1.0.0"),
    }
    resource_values.update(_otel_resource_attributes())
    project_id = _foundry_project_id()
    if project_id:
        resource_values["microsoft.foundry.project.id"] = project_id
    resource = Resource.create(resource_values)
    try:
        interval_ms = int(os.getenv("LUCY_GENAI_METRIC_EXPORT_INTERVAL_MS", "5000"))
    except ValueError:
        interval_ms = 5000
    reader = PeriodicExportingMetricReader(
        AzureMonitorMetricExporter(connection_string=connection_string),
        export_interval_millis=interval_ms,
    )
    _metric_provider = MeterProvider(resource=resource, metric_readers=[reader])
    _metric_meter = _metric_provider.get_meter("lucy_core.responses_loop")
    return _metric_meter


def _histogram(name: str, *, unit: str, description: str) -> Any | None:
    instrument = _metric_instruments.get(name)
    if instrument is None:
        meter = _genai_metric_meter()
        if meter is None:
            return None
        instrument = meter.create_histogram(name, unit=unit, description=description)
        _metric_instruments[name] = instrument
    return instrument


def _metric_attributes(
    *,
    operation: str,
    provider: str,
    request_model: str,
    telemetry: dict[str, Any] | None,
    otel_agent_id: str,
    otel_agent_version: str,
) -> dict[str, Any]:
    attributes: dict[str, Any] = {
        "gen_ai.operation.name": operation,
        "gen_ai.provider.name": provider,
        "gen_ai.agent.id": otel_agent_id,
        "gen_ai.agent.name": otel_agent_id.split(":", 1)[0],
    }
    if otel_agent_version:
        attributes["gen_ai.agent.version"] = otel_agent_version
    if request_model:
        attributes["gen_ai.request.model"] = request_model
    project_id = _foundry_project_id()
    if project_id:
        attributes["microsoft.foundry.project.id"] = project_id
    response_model = (telemetry or {}).get("gen_ai.response.model")
    if response_model:
        attributes["gen_ai.response.model"] = response_model
    return attributes


def _genai_span_attributes(
    *,
    operation: str,
    request_model: str,
    session: LucySession,
    otel_agent_id: str,
    otel_agent_version: str,
) -> dict[str, Any]:
    attributes: dict[str, Any] = {
        "operation": operation,
        "gen_ai.operation.name": operation,
        "gen_ai.agent.id": otel_agent_id,
        "gen_ai.agent.name": otel_agent_id,
        "gen_ai.provider.name": "azure.ai.foundry",
        "gen_ai.system": "azure.ai.foundry",
        "gen_ai.request.model": request_model,
        "lucy.session.id": session.session_id,
        "lucy.conversation.id": session.conversation_id or "",
    }
    if otel_agent_version:
        attributes["gen_ai.agent.version"] = otel_agent_version
    project_id = _foundry_project_id()
    if project_id:
        attributes["microsoft.foundry.project.id"] = project_id
    return attributes


def _annotate_response_span(
    span: Any,
    *,
    result: dict[str, Any],
    session: LucySession,
    user_text: str,
) -> None:
    span.set_attribute("response_length", len(result.get("text", "")))
    span.set_attribute("tools_used", json.dumps([
        item.get("name", "") for item in result.get("tool_outputs", [])
    ]))
    telemetry = result.get("_telemetry", {})
    _set_response_telemetry(span, telemetry)
    if session.last_eval_final_response_id:
        span.set_attribute(
            "lucy.eval.final_response_id",
            session.last_eval_final_response_id,
        )
    if _content_recording_enabled():
        span.set_attribute("eval.user_input", _truncate_span_value(user_text))
        span.set_attribute(
            "eval.agent_response",
            _truncate_span_value(result.get("text", "")),
        )
        span.set_attribute(
            "eval.tools_used",
            _truncate_span_value(result.get("tool_outputs", [])),
        )


def _annotate_error_span(span: Any, exc: Exception) -> None:
    span.set_attribute("error.type", type(exc).__name__)
    span.set_attribute("error.message", _truncate_span_value(str(exc)))
    span.set_status(Status(StatusCode.ERROR, str(exc)))
    span.record_exception(exc)


def record_response_metrics(
    *,
    telemetry: dict[str, Any] | None,
    duration_seconds: float,
    request_model: str,
    otel_agent_id: str,
    otel_agent_version: str,
    error_type: str | None = None,
) -> None:
    """Emit GenAI metrics used by Azure Monitor/Foundry agent dashboards."""
    try:
        attributes = _metric_attributes(
            operation="create_agent",
            provider="azure.ai.foundry",
            request_model=request_model,
            telemetry=telemetry,
            otel_agent_id=otel_agent_id,
            otel_agent_version=otel_agent_version,
        )
        if error_type:
            attributes["error.type"] = error_type

        duration_histogram = _histogram(
            "gen_ai.client.operation.duration",
            unit="s",
            description="GenAI operation duration.",
        )
        if duration_histogram is not None:
            duration_histogram.record(max(duration_seconds, 0.0), attributes)

        token_histogram = _histogram(
            "gen_ai.client.token.usage",
            unit="{token}",
            description="Number of input and output tokens used.",
        )
        if token_histogram is None:
            return
        input_tokens = (telemetry or {}).get("gen_ai.usage.input_tokens")
        if input_tokens is not None:
            token_histogram.record(
                input_tokens,
                {**attributes, "gen_ai.token.type": "input"},
            )
        output_tokens = (telemetry or {}).get("gen_ai.usage.output_tokens")
        if output_tokens is not None:
            token_histogram.record(
                output_tokens,
                {**attributes, "gen_ai.token.type": "output"},
            )
    except Exception:
        logger.debug("Failed to record GenAI response metrics", exc_info=True)


def _get_otel_agent_version(otel_agent_id: str) -> str:
    explicit_version = os.getenv("LUCY_OTEL_AGENT_VERSION", "").strip()
    if explicit_version:
        return explicit_version
    if ":" in otel_agent_id:
        return otel_agent_id.rsplit(":", 1)[-1].strip()
    return ""


def build_authenticated_state_items(session: LucySession) -> list[dict[str, Any]]:
    """Inject session state into Responses input to avoid context drops.

    Returns a (possibly empty) list of system messages to be prepended to the
    user's input. This includes pending intent captured before authentication
    and, when available, verified Apex ID state.
    """
    items: list[dict[str, Any]] = []

    pending_notice = session.metadata.get("pending_notice_request")
    if str(pending_notice).strip().lower() in {"1", "true", "yes", "on"}:
        pending_text = str(session.metadata.get("pending_notice_request_text") or "").strip()
        content = (
            "The user already asked Lucy to retrieve and explain their class action notice. "
            "If this turn authenticates the user successfully, continue that original notice "
            "request immediately. Do not reset to a generic greeting or ask how you can help. "
            "Use the authenticated Apex ID to retrieve the notice."
        )
        if pending_text:
            content += f" Original user request: {pending_text}"
        items.append(
            {
                "type": "message",
                "role": "system",
                "content": content,
            }
        )

    if not session.authenticated or not session.apex_id:
        return items

    user_name = session.user_name or ""
    content = (
        "User is already authenticated. "
        f"Apex ID: {session.apex_id}. "
        f"Name: {user_name}."
        " Do NOT ask for authentication again. Use the Apex ID for any member lookup."
    )
    items.append(
        {
            "type": "message",
            "role": "system",
            "content": content,
        }
    )
    return items


def extract_v2_function_calls(response: Any) -> list[dict[str, Any]]:
    """Extract function-call directives from a Responses API response object.

    Tolerates both dict-shape and attribute-shape items in the response output.
    """
    calls: list[dict[str, Any]] = []
    output_items = getattr(response, "output", None) or []
    for item in output_items:
        item_type = getattr(item, "type", None)
        if isinstance(item, dict):
            item_type = item.get("type")
        if item_type != "function_call":
            continue
        if isinstance(item, dict):
            name = item.get("name")
            arguments = item.get("arguments")
            call_id = item.get("call_id")
        else:
            name = getattr(item, "name", None)
            arguments = getattr(item, "arguments", None)
            call_id = getattr(item, "call_id", None)
        if not call_id or not name:
            continue
        calls.append(
            {
                "name": name,
                "arguments": arguments or "{}",
                "call_id": call_id,
            }
        )
    return calls


def execute_v2_tool_call(
    name: str,
    arguments: str,
    function_registry: dict[str, Any],
) -> str:
    """Execute a registered function tool by name with JSON-encoded arguments.

    Returns a JSON string with either the tool's output or an error payload.
    Coroutine results are awaited via asyncio.run() to preserve sync behavior.
    """
    func = function_registry.get(name)
    if func is None:
        logger.warning("⚠️ V2 tool call requested unknown function: %s", name)
        return json.dumps({"error": f"Unknown tool: {name}"})

    try:
        payload = json.loads(arguments) if arguments else {}
    except Exception:
        payload = {}

    if not isinstance(payload, dict):
        payload = {}

    try:
        sig = inspect.signature(func)
        allowed = {k: v for k, v in payload.items() if k in sig.parameters}
    except Exception:
        allowed = payload

    try:
        result = func(**allowed)
        if asyncio.iscoroutine(result):
            # Ensure coroutines are executed in sync context
            result = asyncio.run(result)
    except Exception as exc:
        logger.error("❌ Tool execution failed for %s: %s", name, exc, exc_info=True)
        return json.dumps({"error": str(exc)})

    if isinstance(result, str):
        return result
    try:
        return json.dumps(result)
    except Exception:
        return json.dumps({"result": str(result)})


async def execute_v2_tool_call_async(
    name: str,
    arguments: str,
    function_registry: dict[str, Any],
) -> str:
    """Async-safe variant of execute_v2_tool_call for the live Responses loop."""
    func = function_registry.get(name)
    if func is None:
        logger.warning("⚠️ V2 tool call requested unknown function: %s", name)
        return json.dumps({"error": f"Unknown tool: {name}"})

    try:
        payload = json.loads(arguments) if arguments else {}
    except Exception:
        payload = {}

    if not isinstance(payload, dict):
        payload = {}

    try:
        sig = inspect.signature(func)
        allowed = {k: v for k, v in payload.items() if k in sig.parameters}
    except Exception:
        allowed = payload

    try:
        result = func(**allowed)
        if inspect.isawaitable(result):
            result = await result
    except Exception as exc:
        logger.error("❌ Tool execution failed for %s: %s", name, exc, exc_info=True)
        return json.dumps({"error": str(exc)})

    if isinstance(result, str):
        return result
    try:
        return json.dumps(result)
    except Exception:
        return json.dumps({"result": str(result)})


async def run_response_v2(
    user_text: str,
    session: LucySession,
    openai_client: Any,
    agent_name: str,
    agent_version: str,
    function_registry: dict[str, Any],
) -> dict[str, Any]:
    """Execute a Foundry v2 Responses API call with tool-loop dispatch.

    Mutates `session` in place: updates conversation_id, previous_response_id,
    and last_eval_final_response_id as the loop progresses. Adapters are
    responsible for persisting those changes back to their session store.

    Returns a dict shape compatible with the original apex.py implementation:
        {"text": str, "tool_outputs": list[dict]}

    Caller must verify openai_client/agent_name/agent_version are initialized
    before calling — this function does not initialize the Foundry client.

    Emits an OpenTelemetry span named "create_agent" for Foundry custom-agent
    correlation and a nested "chat" span for the Operate/Application Analytics
    inference-call workbook. Both carry GenAI semantic-convention attributes
    (`operation`, `gen_ai.agent.id`, `gen_ai.agent.name`, `gen_ai.system`,
    `gen_ai.request.model`).
    """
    otel_agent_id = os.getenv("LUCY_OTEL_AGENT_ID", "lucy-aca")
    request_model = _get_model_deployment_name() or agent_name
    start_time = time.monotonic()
    otel_agent_version = _get_otel_agent_version(otel_agent_id)
    span_attributes = _genai_span_attributes(
        operation=_AGENT_OPERATION_NAME,
        request_model=request_model,
        session=session,
        otel_agent_id=otel_agent_id,
        otel_agent_version=otel_agent_version,
    )
    inference_span_attributes = _genai_span_attributes(
        operation=_INFERENCE_OPERATION_NAME,
        request_model=request_model,
        session=session,
        otel_agent_id=otel_agent_id,
        otel_agent_version=otel_agent_version,
    )

    with _tracer.start_as_current_span(
        _AGENT_OPERATION_NAME,
        kind=SpanKind.CLIENT,
        attributes=span_attributes,
    ) as span:
        if _content_recording_enabled():
            span.set_attribute("eval.user_input", _truncate_span_value(user_text))
        try:
            with _tracer.start_as_current_span(
                _INFERENCE_OPERATION_NAME,
                kind=SpanKind.CLIENT,
                attributes=inference_span_attributes,
            ) as inference_span:
                try:
                    result = await _run_response_v2_impl(
                        user_text=user_text,
                        session=session,
                        openai_client=openai_client,
                        agent_name=agent_name,
                        agent_version=agent_version,
                        function_registry=function_registry,
                    )
                except Exception as exc:
                    _annotate_error_span(inference_span, exc)
                    raise
                _annotate_response_span(
                    inference_span,
                    result=result,
                    session=session,
                    user_text=user_text,
                )
                inference_span.set_status(Status(StatusCode.OK))
            _annotate_response_span(span, result=result, session=session, user_text=user_text)
            telemetry = result.get("_telemetry", {})
            span.set_status(Status(StatusCode.OK))
            record_response_metrics(
                telemetry=telemetry,
                duration_seconds=time.monotonic() - start_time,
                request_model=request_model,
                otel_agent_id=otel_agent_id,
                otel_agent_version=otel_agent_version,
            )
            return result
        except Exception as exc:
            _annotate_error_span(span, exc)
            record_response_metrics(
                telemetry=None,
                duration_seconds=time.monotonic() - start_time,
                request_model=request_model,
                otel_agent_id=otel_agent_id,
                otel_agent_version=otel_agent_version,
                error_type=type(exc).__name__,
            )
            raise


async def _run_response_v2_impl(
    user_text: str,
    session: LucySession,
    openai_client: Any,
    agent_name: str,
    agent_version: str,
    function_registry: dict[str, Any],
) -> dict[str, Any]:
    """Inner implementation — OTel-wrapped by run_response_v2."""
    eval_turn_id = str(uuid.uuid4())
    eval_step_index = 0

    def _normalize_metadata_values(metadata: dict[str, Any]) -> dict[str, str]:
        """Coerce metadata values to strings and truncate to 512 chars per API spec."""
        normalized: dict[str, str] = {}
        for key, value in metadata.items():
            if value is None:
                continue
            if not isinstance(value, str):
                value = str(value)
            if len(value) > 512:
                value = value[:512]
            normalized[key] = value
        return normalized

    def _apply_eval_metadata(
        payload: dict[str, Any],
        *,
        step: str,
        step_index: int,
        previous_id: Optional[str] = None,
    ) -> None:
        metadata = dict(payload.get("metadata") or {})
        metadata["lucy_eval_turn_id"] = eval_turn_id
        metadata["lucy_eval_step"] = step
        metadata["lucy_eval_step_index"] = str(step_index)
        if previous_id:
            metadata["lucy_eval_previous_response_id"] = previous_id
        payload["metadata"] = _normalize_metadata_values(metadata)

    conversation_id = session.conversation_id
    previous_response_id = session.previous_response_id
    state_items = build_authenticated_state_items(session)

    if conversation_id:
        payload = build_response_payload(
            conversation_id=conversation_id,
            user_input=user_text,
            agent_name=agent_name,
            agent_version=agent_version,
        )
        if state_items:
            payload["input"] = state_items + [
                {
                    "type": "message",
                    "role": "user",
                    "content": user_text,
                }
            ]
    else:
        payload = {
            "input": user_text,
            "extra_body": build_agent_reference(agent_name, agent_version),
        }
        if previous_response_id:
            payload["previous_response_id"] = previous_response_id
        if state_items:
            payload["input"] = state_items + [
                {
                    "type": "message",
                    "role": "user",
                    "content": user_text,
                }
            ]

    _apply_eval_metadata(
        payload,
        step="initial",
        step_index=eval_step_index,
        previous_id=previous_response_id,
    )

    max_output_tokens = should_include_max_output_tokens(
        os.getenv("AZURE_RESPONSES_MAX_OUTPUT_TOKENS")
    )
    if max_output_tokens is not None:
        payload["max_output_tokens"] = max_output_tokens

    _apply_request_reasoning(payload)

    store = os.getenv("AZURE_RESPONSES_STORE")
    if store:
        payload["store"] = store.strip().lower() in {"1", "true", "yes", "on"}

    logger.info(
        "🧵 V2 context: conversation_id=%s previous_response_id=%s state_items=%s",
        conversation_id,
        previous_response_id,
        len(state_items),
    )
    response = openai_client.responses.create(**payload)
    tool_outputs: list[dict[str, Any]] = []

    response_id = getattr(response, "id", None)
    if response_id:
        session.previous_response_id = response_id

    if not conversation_id:
        conv = getattr(response, "conversation", None)
        if isinstance(conv, dict):
            conversation_id = conv.get("id")
        else:
            conversation_id = getattr(conv, "id", None)
        if not conversation_id:
            conversation_id = getattr(response, "conversation_id", None)
        if conversation_id:
            session.conversation_id = conversation_id

    max_tool_loops = int(os.getenv("AZURE_RESPONSES_MAX_TOOL_LOOPS", "6"))
    loop_count = 0
    while True:
        tool_calls = extract_v2_function_calls(response)
        if not tool_calls:
            break
        loop_count += 1
        if loop_count > max_tool_loops:
            logger.warning("⚠️ Tool loop exceeded max iterations (%s). Stopping.", max_tool_loops)
            break

        output_items: list[dict[str, Any]] = []
        for call in tool_calls:
            name = call["name"]
            arguments = call.get("arguments") or "{}"
            call_id = call["call_id"]
            with _tracer.start_as_current_span(
                "execute_tool",
                attributes={
                    "gen_ai.operation.name": "execute_tool",
                    "gen_ai.tool.name": name,
                    "gen_ai.tool.call.id": call_id,
                },
            ) as span:
                if _content_recording_enabled():
                    span.set_attribute(
                        "gen_ai.tool.call.arguments",
                        _truncate_span_value(arguments),
                    )
                output = await execute_v2_tool_call_async(
                    name,
                    arguments,
                    function_registry,
                )
                span.set_attribute("tool_result_size", len(str(output)))
                if _content_recording_enabled():
                    span.set_attribute(
                        "gen_ai.tool.call.result",
                        _truncate_span_value(output),
                    )
            tool_outputs.append(
                {
                    "name": name,
                    "arguments": arguments,
                    "output": output,
                    "call_id": call_id,
                }
            )
            output_items.append(
                {
                    "type": "function_call_output",
                    "call_id": call_id,
                    "output": output,
                }
            )

        follow_payload = {
            "input": output_items,
            "previous_response_id": response.id,
            "extra_body": build_agent_reference(agent_name, agent_version),
        }
        if conversation_id:
            follow_payload["conversation"] = conversation_id

        eval_step_index += 1
        _apply_eval_metadata(
            follow_payload,
            step="tool_output",
            step_index=eval_step_index,
            previous_id=response.id,
        )

        response = openai_client.responses.create(**follow_payload)
        response_id = getattr(response, "id", None)
        if response_id:
            session.previous_response_id = response_id

    assistant_text = extract_response_text(response).strip()
    if not assistant_text:
        output_items = getattr(response, "output", None)
        summary = []
        for item in output_items or []:
            item_type = getattr(item, "type", None)
            if isinstance(item, dict):
                item_type = item.get("type")
                contents = item.get("content", [])
            else:
                contents = getattr(item, "content", None)
            content_types = []
            for content in contents or []:
                if isinstance(content, dict):
                    content_types.append(content.get("type"))
                else:
                    content_types.append(getattr(content, "type", None))
            summary.append({"type": item_type, "content_types": content_types})
        logger.warning(
            "Responses returned empty text. output_summary=%s output_text_type=%s",
            summary,
            type(getattr(response, "output_text", None)).__name__,
        )

    final_response_id = getattr(response, "id", None)
    if final_response_id:
        session.last_eval_final_response_id = final_response_id
    logger.info(
        "📊 Eval response: turn_id=%s final_response_id=%s step_index=%s",
        eval_turn_id,
        final_response_id,
        eval_step_index,
    )

    return {
        "text": assistant_text,
        "tool_outputs": tool_outputs,
        "_telemetry": collect_response_telemetry(response),
    }
