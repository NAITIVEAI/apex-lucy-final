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
    GenAI-conformant spans (gen_ai.agent.*, gen_ai.system, etc.) are emitted
    by lucy_core.responses_loop.
"""

from __future__ import annotations

import hmac
import logging
import os
from typing import Any, Optional

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, ConfigDict

from .runtime import LucyRuntime
from .runtime_factory import default_runtime_factory
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


def _project_client_from_runtime(runtime: Optional[LucyRuntime]) -> Any:
    if runtime is None:
        return None
    return getattr(runtime, "project_client", None)


def _probe_project_client(project_client: Any, agent_name: Optional[str]) -> dict[str, Any]:
    """Best-effort Foundry SDK probe used by /health/gateway.

    SDK method names changed across Foundry previews, so this deliberately
    supports multiple read-only list shapes and reports "unchecked" rather
    than failing when the installed SDK lacks a cheap list method.
    """
    if project_client is None:
        return {"checked": False, "ok": False, "reason": "project_client_missing"}
    agents = getattr(project_client, "agents", None)
    if agents is None:
        return {"checked": False, "ok": False, "reason": "agents_client_missing"}

    try:
        if hasattr(agents, "list_agents"):
            try:
                iterator = agents.list_agents(limit=1)
            except TypeError:
                iterator = agents.list_agents()
            next(iter(iterator), None)
            return {"checked": True, "ok": True, "method": "list_agents"}
        if agent_name and hasattr(agents, "list_versions"):
            iterator = agents.list_versions(agent_name=agent_name)
            next(iter(iterator), None)
            return {"checked": True, "ok": True, "method": "list_versions"}
    except Exception as exc:
        logger.warning("Gateway Foundry probe failed: %s", exc, exc_info=True)
        return {
            "checked": True,
            "ok": False,
            "error": str(exc),
            "error_type": type(exc).__name__,
        }

    return {"checked": False, "ok": True, "reason": "no_supported_probe_method"}


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


def create_app(*, runtime_factory=default_runtime_factory) -> FastAPI:
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
            "gateway_token_configured": bool(os.getenv("LUCY_GATEWAY_API_TOKEN")),
            "agent_url_path": "/agent/respond",
        }

    @app.get("/health/gateway")
    async def gateway_health() -> dict[str, Any]:
        runtime: Optional[LucyRuntime] = app.state.runtime
        token_configured = bool(os.getenv("LUCY_GATEWAY_API_TOKEN"))
        otel_agent_id = app.state.otel_agent_id
        project_probe = _probe_project_client(
            _project_client_from_runtime(runtime),
            getattr(runtime, "agent_name", None) if runtime is not None else None,
        )
        gateway_connected = (
            runtime is not None
            and token_configured
            and bool(otel_agent_id)
            and bool(project_probe.get("ok"))
        )
        return {
            "status": "healthy" if gateway_connected else "unhealthy",
            "gateway_connected": gateway_connected,
            "runtime_initialized": runtime is not None,
            "gateway_token_configured": token_configured,
            "otel_agent_id": otel_agent_id,
            "project_endpoint_configured": bool(
                os.getenv("AZURE_AI_PROJECT_ENDPOINT")
                or os.getenv("AZURE_AI_FOUNDRY_PROJECT_ENDPOINT")
            ),
            "agent_url_path": "/agent/respond",
            "project_probe": project_probe,
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
