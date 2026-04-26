"""FastAPI HTTP wrapper for Lucy — registers behind the Foundry AI Gateway.

This module exposes Lucy's runtime over HTTP so the Foundry AI Gateway (Azure
API Management) can proxy clients/evals to it. It is Chainlit-free; the
Chainlit member experience continues to run unchanged in apex.py.

Routes:
    POST /agent/respond   — invoke LucyRuntime, return LucyResponse JSON
    GET  /agent/health    — liveness (process is up)
    GET  /agent/ready     — readiness (runtime initialized)

Auth:
    X-Agent-Token header, constant-time compared against LUCY_GATEWAY_API_TOKEN
    env var. APIM is a transparent proxy per Microsoft Foundry docs — Lucy's
    own auth schema is preserved end-to-end.

OpenTelemetry agent ID:
    LUCY_OTEL_AGENT_ID env var (default "lucy-aca"). This is the value Foundry
    uses to correlate traces to the registered custom agent. Per-request
    GenAI-conformant spans (gen_ai.agents.id, gen_ai.system, etc.) are added
    in a follow-up step that wires lucy_core.runtime to emit them.

Production runtime wiring (next iteration):
    Out of scope for this scaffold. The default runtime factory raises
    NotImplementedError; tests inject a mock LucyRuntime via the
    runtime_factory= argument to create_app(). Wiring foundry_init +
    Lucy's tool list through the FastAPI process is the next milestone.
"""

from __future__ import annotations

import hmac
import logging
import os
from typing import Any, Optional

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, ConfigDict

from .runtime import LucyRuntime
from .session import LucyArtifact, LucyRequest, LucyResponse, LucySession

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pydantic wire types
# ---------------------------------------------------------------------------


class _SessionPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    session_id: str
    conversation_id: Optional[str] = None
    previous_response_id: Optional[str] = None
    last_eval_final_response_id: Optional[str] = None
    authenticated: bool = False
    apex_id: Optional[str] = None
    user_name: Optional[str] = None
    metadata: dict[str, Any] = {}


class _RequestBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    input_text: str
    session: _SessionPayload
    metadata: dict[str, Any] = {}


class _ArtifactPayload(BaseModel):
    type: str
    label: str
    url: Optional[str] = None
    blob_url: Optional[str] = None
    expires_at: Optional[str] = None
    metadata: dict[str, Any] = {}


class _ResponseBody(BaseModel):
    text: str
    session: _SessionPayload
    tool_calls: list[dict[str, Any]] = []
    artifacts: list[_ArtifactPayload] = []
    handoff: Optional[dict[str, Any]] = None
    trace_id: Optional[str] = None
    errors: list[dict[str, Any]] = []


# ---------------------------------------------------------------------------
# Marshalling helpers (pure; covered by unit tests)
# ---------------------------------------------------------------------------


def session_payload_to_lucy(p: _SessionPayload) -> LucySession:
    return LucySession(
        session_id=p.session_id,
        conversation_id=p.conversation_id,
        previous_response_id=p.previous_response_id,
        last_eval_final_response_id=p.last_eval_final_response_id,
        authenticated=p.authenticated,
        apex_id=p.apex_id,
        user_name=p.user_name,
        metadata=dict(p.metadata),
    )


def lucy_session_to_payload(s: LucySession) -> _SessionPayload:
    return _SessionPayload(
        session_id=s.session_id,
        conversation_id=s.conversation_id,
        previous_response_id=s.previous_response_id,
        last_eval_final_response_id=s.last_eval_final_response_id,
        authenticated=s.authenticated,
        apex_id=s.apex_id,
        user_name=s.user_name,
        metadata=dict(s.metadata),
    )


def lucy_artifact_to_payload(a: LucyArtifact) -> _ArtifactPayload:
    return _ArtifactPayload(
        type=a.type,
        label=a.label,
        url=a.url,
        blob_url=a.blob_url,
        expires_at=a.expires_at,
        metadata=dict(a.metadata),
    )


def lucy_response_to_payload(r: LucyResponse) -> _ResponseBody:
    return _ResponseBody(
        text=r.text,
        session=lucy_session_to_payload(r.session),
        tool_calls=list(r.tool_calls),
        artifacts=[lucy_artifact_to_payload(a) for a in r.artifacts],
        handoff=r.handoff,
        trace_id=r.trace_id,
        errors=list(r.errors),
    )


# ---------------------------------------------------------------------------
# Auth helper
# ---------------------------------------------------------------------------


def _check_token(x_agent_token: Optional[str] = Header(default=None)) -> None:
    expected = os.getenv("LUCY_GATEWAY_API_TOKEN", "")
    if not expected:
        raise HTTPException(status_code=503, detail="Server auth token not configured")
    if not x_agent_token:
        raise HTTPException(status_code=401, detail="Missing X-Agent-Token header")
    if not hmac.compare_digest(x_agent_token, expected):
        raise HTTPException(status_code=401, detail="Invalid token")


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


async def _default_runtime_factory() -> LucyRuntime:
    """Production runtime factory.

    Imports apex.py and reuses its Foundry init + tool registry. apex.py
    requires chainlit to be importable, which it is in the Lucy ACA container
    (Chainlit and this FastAPI process run side-by-side).

    Both processes initialize independently against the same Foundry agent
    (`lucy-prod`) — they each call _initialize_persistent_agent_v2(), find
    the existing version, and load the SAME function_registry from the same
    apex.py code. Lucy's tools stay locked: there is no second tool registry
    to drift from production.
    """
    import apex

    await apex._initialize_persistent_agent_v2()
    if not (apex.openai_client and apex.agent_name and apex.agent_version):
        raise RuntimeError(
            "apex._initialize_persistent_agent_v2() returned but globals are "
            "not set. Cannot construct LucyRuntime."
        )
    logger.info(
        "🟢 Lucy HTTP wrapper bound to apex globals: agent=%s version=%s tools=%d",
        apex.agent_name,
        apex.agent_version,
        len(apex.v2_function_registry or {}),
    )
    return LucyRuntime(
        openai_client=apex.openai_client,
        agent_name=apex.agent_name,
        agent_version=apex.agent_version,
        function_registry=apex.v2_function_registry,
    )


def create_app(*, runtime_factory=_default_runtime_factory) -> FastAPI:
    """Construct the FastAPI app.

    `runtime_factory`: an async or sync callable returning a LucyRuntime.
    Called once on startup. Tests inject a mock factory; production wiring
    will provide a foundry_init-backed factory in the next iteration.
    """
    app = FastAPI(title="Lucy HTTP wrapper", version="0.1.0")
    app.state.runtime = None
    app.state.otel_agent_id = os.getenv("LUCY_OTEL_AGENT_ID", "lucy-aca")

    @app.on_event("startup")
    async def _startup() -> None:
        result = runtime_factory()
        if hasattr(result, "__await__"):
            result = await result
        app.state.runtime = result
        logger.info(
            "✅ Lucy HTTP wrapper ready (otel_agent_id=%s)",
            app.state.otel_agent_id,
        )

    @app.get("/agent/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/agent/ready")
    async def ready() -> dict[str, Any]:
        return {
            "ready": app.state.runtime is not None,
            "otel_agent_id": app.state.otel_agent_id,
        }

    @app.post(
        "/agent/respond",
        response_model=_ResponseBody,
        dependencies=[Depends(_check_token)],
    )
    async def respond(body: _RequestBody) -> _ResponseBody:
        runtime: Optional[LucyRuntime] = app.state.runtime
        if runtime is None:
            raise HTTPException(status_code=503, detail="Runtime not initialized")
        request = LucyRequest(
            input_text=body.input_text,
            session=session_payload_to_lucy(body.session),
            metadata=dict(body.metadata),
        )
        response = await runtime.respond(request)
        return lucy_response_to_payload(response)

    return app
