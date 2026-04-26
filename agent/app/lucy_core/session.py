"""Portable session and message data models for the Lucy runtime core.

These models let the runtime be invoked from any adapter (Chainlit,
FastAPI HTTP wrapper, Foundry Hosted Agent) without coupling to that
adapter's session/message types.

Field semantics mirror the values previously kept on Chainlit's
`cl.user_session` so existing logic in apex.py can be migrated by
mechanical substitution: `cl.user_session.get("foo")` -> `session.foo`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class LucySession:
    session_id: str
    conversation_id: str | None = None
    previous_response_id: str | None = None
    last_eval_final_response_id: str | None = None
    authenticated: bool = False
    apex_id: str | None = None
    user_name: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class LucyArtifact:
    type: str
    label: str
    url: str | None = None
    blob_url: str | None = None
    expires_at: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class LucyRequest:
    input_text: str
    session: LucySession
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class LucyResponse:
    text: str
    session: LucySession
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    artifacts: list[LucyArtifact] = field(default_factory=list)
    handoff: dict[str, Any] | None = None
    trace_id: str | None = None
    errors: list[dict[str, Any]] = field(default_factory=list)
