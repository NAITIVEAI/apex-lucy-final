"""Portable handoff normalization helpers for Lucy."""

from __future__ import annotations

import json
import logging
from typing import Any

from .session import LucyArtifact

logger = logging.getLogger(__name__)

_HANDOFF_TOOL_NAMES = {
    "send_handoff_notification_email_sync",
    "request_human_assistance_sync",
    "check_human_availability_sync",
}


def _coerce_json_payload(value: Any) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    if value is None:
        return payloads

    raw_values: list[str] = []
    if isinstance(value, (list, tuple)):
        raw_values.extend(str(item) for item in value if item is not None)
    else:
        raw_values.append(str(value))

    for raw in raw_values:
        try:
            parsed = json.loads(raw)
        except Exception:
            continue
        if isinstance(parsed, dict):
            payloads.append(parsed)
    return payloads


def normalize_handoff_payload(
    payload: dict[str, Any],
    *,
    reason: str | None = None,
) -> dict[str, Any] | None:
    """Convert Lucy handoff tool output into a portable result shape."""
    if not isinstance(payload, dict):
        return None
    if not payload.get("success"):
        return None

    conversation_id = payload.get("conversation_id") or payload.get("handoff_id")
    if not conversation_id:
        return None

    normalized: dict[str, Any] = {
        "created": True,
        "conversation_id": conversation_id,
        "status": "pending",
    }
    for key in (
        "portal_url",
        "user_portal_url",
        "agent_name",
        "apex_id",
        "message",
        "warning",
        "establish_bridge",
        "wait_for_agent_join",
    ):
        value = payload.get(key)
        if value is not None:
            normalized[key] = value
    if reason:
        normalized["reason"] = reason
    return normalized


def handoff_artifact_from_payload(payload: dict[str, Any]) -> LucyArtifact | None:
    if not payload:
        return None
    portal_url = payload.get("portal_url")
    conversation_id = payload.get("conversation_id")
    label = payload.get("message") or "Human handoff requested"
    metadata = {
        "created": payload.get("created", True),
        "status": payload.get("status", "pending"),
    }
    if conversation_id:
        metadata["conversation_id"] = conversation_id
    if payload.get("agent_name"):
        metadata["agent_name"] = payload["agent_name"]
    if payload.get("apex_id"):
        metadata["apex_id"] = payload["apex_id"]
    return LucyArtifact(
        type="handoff",
        label=label,
        url=portal_url,
        metadata=metadata,
    )


def extract_handoff_from_tool_outputs(
    tool_outputs: list[dict[str, Any]],
    *,
    assistant_text: str | None = None,
    reason: str | None = None,
) -> dict[str, Any] | None:
    """Extract the first successful handoff payload from tool outputs."""
    candidates: list[dict[str, Any]] = []

    for call in tool_outputs or []:
        if call.get("name") not in _HANDOFF_TOOL_NAMES:
            continue
        candidates.extend(_coerce_json_payload(call.get("output")))

    if assistant_text:
        candidates.extend(_coerce_json_payload(assistant_text))

    for candidate in candidates:
        normalized = normalize_handoff_payload(candidate, reason=reason)
        if normalized is not None:
            return normalized
    return None
