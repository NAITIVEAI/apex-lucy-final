"""Tests for the FastAPI HTTP wrapper.

Skipped in environments where FastAPI/pydantic isn't importable (e.g. local
dev with broken pydantic-core/pydantic version pair). Production container
has the matching deps from agent/app/requirements.txt and will run all tests.
"""

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "agent" / "app"))

# Gate at module level on full FastAPI + pydantic + http_app importability.
# pydantic can raise SystemError (not just ImportError) when its core/major
# versions are mismatched, so catch both.
try:
    from fastapi import HTTPException  # noqa: E402
    from fastapi.testclient import TestClient  # noqa: E402

    from lucy_core import LucyArtifact, LucyRequest, LucyResponse, LucySession  # noqa: E402
    from lucy_core.http_app import (  # noqa: E402
        _check_token,
        _ArtifactPayload,
        _RequestBody,
        _ResponseBody,
        _SessionPayload,
        create_app,
        lucy_artifact_to_payload,
        lucy_response_to_payload,
        lucy_session_to_payload,
        session_payload_to_lucy,
    )
except (ImportError, SystemError) as _import_exc:  # pragma: no cover
    pytest.skip(
        f"FastAPI/pydantic env unavailable: {_import_exc}",
        allow_module_level=True,
    )


# ---------------------------------------------------------------------------
# Marshalling helpers (pure)
# ---------------------------------------------------------------------------


class MarshallingTests(unittest.TestCase):
    def test_session_round_trip(self):
        original = LucySession(
            session_id="s-1",
            conversation_id="c",
            previous_response_id="r",
            last_eval_final_response_id="rf",
            authenticated=True,
            apex_id="A123",
            user_name="Jane",
            metadata={"k": "v"},
        )
        payload = lucy_session_to_payload(original)
        restored = session_payload_to_lucy(payload)
        self.assertEqual(restored.session_id, original.session_id)
        self.assertEqual(restored.conversation_id, original.conversation_id)
        self.assertEqual(restored.authenticated, original.authenticated)
        self.assertEqual(restored.apex_id, original.apex_id)
        self.assertEqual(restored.metadata, original.metadata)

    def test_session_metadata_is_copied_not_shared(self):
        original = LucySession(session_id="s", metadata={"x": 1})
        payload = lucy_session_to_payload(original)
        original.metadata["x"] = 2
        # The payload's snapshot should not reflect post-conversion mutations.
        self.assertEqual(payload.metadata, {"x": 1})

    def test_artifact_round_trip(self):
        artifact = LucyArtifact(
            type="pdf",
            label="Notice",
            url="https://example.com/sas",
            blob_url="https://storage.example.com/lucycmnotices/x.pdf",
            expires_at="2026-04-26T00:00:00Z",
            metadata={"container": "lucycmnotices"},
        )
        payload = lucy_artifact_to_payload(artifact)
        self.assertEqual(payload.type, "pdf")
        self.assertEqual(payload.label, "Notice")
        self.assertEqual(payload.metadata["container"], "lucycmnotices")

    def test_response_payload_includes_artifacts_and_tool_calls(self):
        session = LucySession(session_id="s")
        artifact = LucyArtifact(type="link", label="See more", url="https://x")
        response = LucyResponse(
            text="hi",
            session=session,
            tool_calls=[{"name": "f", "arguments": "{}", "output": "ok", "call_id": "c"}],
            artifacts=[artifact],
            handoff={"created": True},
            trace_id="t",
            errors=[{"code": "E"}],
        )
        payload = lucy_response_to_payload(response)
        self.assertEqual(payload.text, "hi")
        self.assertEqual(len(payload.tool_calls), 1)
        self.assertEqual(len(payload.artifacts), 1)
        self.assertEqual(payload.artifacts[0].type, "link")
        self.assertEqual(payload.handoff, {"created": True})
        self.assertEqual(payload.trace_id, "t")
        self.assertEqual(payload.errors, [{"code": "E"}])


# ---------------------------------------------------------------------------
# Auth (unit-level — tests the dependency function directly)
# ---------------------------------------------------------------------------


class AuthDependencyTests(unittest.TestCase):
    def test_no_server_token_configured_503(self):
        with patch.dict(os.environ, {"LUCY_GATEWAY_API_TOKEN": ""}, clear=False):
            os.environ.pop("LUCY_GATEWAY_API_TOKEN", None)
            with self.assertRaises(HTTPException) as cm:
                _check_token(x_agent_token="anything")
            self.assertEqual(cm.exception.status_code, 503)

    def test_missing_header_401(self):
        with patch.dict(os.environ, {"LUCY_GATEWAY_API_TOKEN": "secret"}):
            with self.assertRaises(HTTPException) as cm:
                _check_token(x_agent_token=None)
            self.assertEqual(cm.exception.status_code, 401)

    def test_wrong_header_401(self):
        with patch.dict(os.environ, {"LUCY_GATEWAY_API_TOKEN": "secret"}):
            with self.assertRaises(HTTPException) as cm:
                _check_token(x_agent_token="wrong")
            self.assertEqual(cm.exception.status_code, 401)

    def test_correct_header_passes(self):
        with patch.dict(os.environ, {"LUCY_GATEWAY_API_TOKEN": "secret"}):
            # No exception means pass — _check_token returns None
            self.assertIsNone(_check_token(x_agent_token="secret"))


# ---------------------------------------------------------------------------
# Route tests with TestClient + mock runtime
# ---------------------------------------------------------------------------


class _MockRuntime:
    def __init__(self, response_text="hi from mock"):
        self._response_text = response_text
        self.received_requests: list[LucyRequest] = []

    async def respond(self, request: LucyRequest) -> LucyResponse:
        self.received_requests.append(request)
        return LucyResponse(text=self._response_text, session=request.session)


class _MockProjectClient:
    class _Agents:
        def list_agents(self, limit=1):
            return iter([{"name": "lucy"}])

    def __init__(self):
        self.agents = self._Agents()


class RouteTests(unittest.TestCase):
    def _client(self, runtime=None) -> TestClient:
        runtime = runtime or _MockRuntime()
        app = create_app(runtime_factory=lambda: runtime)
        return TestClient(app)

    def test_health(self):
        with self._client() as client:
            resp = client.get("/agent/health")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"status": "ok"})

    def test_ready_after_startup(self):
        with self._client() as client:
            resp = client.get("/agent/ready")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body["ready"])
        self.assertEqual(body["otel_agent_id"], "lucy-aca")
        self.assertFalse(body["gateway_token_configured"])
        self.assertEqual(body["agent_url_path"], "/agent/respond")

    def test_gateway_health_reports_unhealthy_when_token_missing(self):
        runtime = _MockRuntime()
        runtime.project_client = _MockProjectClient()
        with patch.dict(os.environ, {"AZURE_AI_PROJECT_ENDPOINT": "https://example"}):
            os.environ.pop("LUCY_GATEWAY_API_TOKEN", None)
            with self._client(runtime=runtime) as client:
                resp = client.get("/health/gateway")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["status"], "unhealthy")
        self.assertFalse(body["gateway_connected"])
        self.assertTrue(body["runtime_initialized"])
        self.assertFalse(body["gateway_token_configured"])
        self.assertTrue(body["project_probe"]["ok"])

    def test_gateway_health_reports_connected(self):
        runtime = _MockRuntime()
        runtime.project_client = _MockProjectClient()
        with patch.dict(os.environ, {
            "LUCY_GATEWAY_API_TOKEN": "secret",
            "AZURE_AI_PROJECT_ENDPOINT": "https://example",
        }):
            with self._client(runtime=runtime) as client:
                resp = client.get("/health/gateway")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["status"], "healthy")
        self.assertTrue(body["gateway_connected"])
        self.assertEqual(body["project_probe"]["method"], "list_agents")

    def test_respond_requires_token(self):
        with patch.dict(os.environ, {"LUCY_GATEWAY_API_TOKEN": "secret"}):
            with self._client() as client:
                resp = client.post(
                    "/agent/respond",
                    json={
                        "input_text": "hi",
                        "session": {"session_id": "s"},
                    },
                )
        self.assertEqual(resp.status_code, 401)

    def test_respond_rejects_wrong_token(self):
        with patch.dict(os.environ, {"LUCY_GATEWAY_API_TOKEN": "secret"}):
            with self._client() as client:
                resp = client.post(
                    "/agent/respond",
                    json={
                        "input_text": "hi",
                        "session": {"session_id": "s"},
                    },
                    headers={"X-Agent-Token": "wrong"},
                )
        self.assertEqual(resp.status_code, 401)

    def test_respond_with_correct_token_invokes_runtime(self):
        runtime = _MockRuntime(response_text="echo back")
        with patch.dict(os.environ, {"LUCY_GATEWAY_API_TOKEN": "secret"}):
            with self._client(runtime=runtime) as client:
                resp = client.post(
                    "/agent/respond",
                    json={
                        "input_text": "hello",
                        "session": {
                            "session_id": "s-99",
                            "authenticated": True,
                            "apex_id": "A123",
                        },
                    },
                    headers={"X-Agent-Token": "secret"},
                )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["text"], "echo back")
        self.assertEqual(body["session"]["session_id"], "s-99")
        self.assertEqual(body["session"]["apex_id"], "A123")
        self.assertEqual(len(runtime.received_requests), 1)
        self.assertEqual(runtime.received_requests[0].input_text, "hello")

    def test_otel_agent_id_overridable_via_env(self):
        with patch.dict(os.environ, {
            "LUCY_OTEL_AGENT_ID": "lucy-staging",
            "LUCY_GATEWAY_API_TOKEN": "secret",
        }):
            with self._client() as client:
                resp = client.get("/agent/ready")
        self.assertEqual(resp.json()["otel_agent_id"], "lucy-staging")


if __name__ == "__main__":
    unittest.main()
