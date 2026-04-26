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
import uuid
from typing import Any, Optional

from .session import LucySession

# Agent-side helpers (Chainlit-free) — agent/app/ is on sys.path at runtime
from response_utils import extract_response_text
from foundry_v2_runtime import build_response_payload
from foundry_v2 import build_agent_reference
from response_config import should_include_max_output_tokens

# OpenTelemetry — emits GenAI semantic-convention spans that Foundry's Monitor
# tab filters on (gen_ai.agents.id). When the OTel SDK isn't initialized, the
# tracer returns a no-op span — safe in tests and dev environments.
from opentelemetry import trace as _otel_trace

_tracer = _otel_trace.get_tracer("lucy_core.responses_loop")

logger = logging.getLogger(__name__)


def build_authenticated_state_items(session: LucySession) -> list[dict[str, Any]]:
    """Inject authenticated state into Responses input to avoid re-auth loops.

    Returns a (possibly empty) list of system messages to be prepended to the
    user's input when the session has a verified Apex ID.
    """
    items: list[dict[str, Any]] = []
    if not session.authenticated:
        return items
    if not session.apex_id:
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

    Emits an OpenTelemetry span named "create_agent" with GenAI semantic-
    convention attributes (`operation`, `gen_ai.agents.id`, `gen_ai.system`,
    `gen_ai.request.model`). Foundry's Monitor tab filters by `gen_ai.agents.id`.
    """
    otel_agent_id = os.getenv("LUCY_OTEL_AGENT_ID", "lucy-aca")
    with _tracer.start_as_current_span(
        "create_agent",
        attributes={
            "operation": "create_agent",
            "gen_ai.operation.name": "create_agent",
            "gen_ai.agents.id": otel_agent_id,
            "gen_ai.agents.name": otel_agent_id,
            "gen_ai.system": "azure.ai.foundry",
            "gen_ai.request.model": agent_name,
            "lucy.session.id": session.session_id,
            "lucy.conversation.id": session.conversation_id or "",
        },
    ):
        return await _run_response_v2_impl(
            user_text=user_text,
            session=session,
            openai_client=openai_client,
            agent_name=agent_name,
            agent_version=agent_version,
            function_registry=function_registry,
        )


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

    extra_body = payload.get("extra_body")
    uses_agent_reference = isinstance(extra_body, dict) and "agent" in extra_body

    reasoning_effort = os.getenv("AZURE_RESPONSES_REASONING_EFFORT")
    if reasoning_effort and not uses_agent_reference:
        payload["reasoning"] = {"effort": reasoning_effort}

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
            ):
                output = execute_v2_tool_call(name, arguments, function_registry)
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

    return {"text": assistant_text, "tool_outputs": tool_outputs}
