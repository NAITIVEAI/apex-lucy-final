import os
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "agent" / "app"))

from lucy_core import (
    LucyArtifact,
    LucyError,
    LucyRequest,
    LucyResponse,
    LucySession,
    ResponsesAPIError,
    SessionStateError,
    ToolExecutionError,
)


class LucySessionTests(unittest.TestCase):
    def test_session_defaults(self):
        session = LucySession(session_id="s-1")
        self.assertEqual(session.session_id, "s-1")
        self.assertIsNone(session.conversation_id)
        self.assertIsNone(session.previous_response_id)
        self.assertIsNone(session.last_eval_final_response_id)
        self.assertFalse(session.authenticated)
        self.assertIsNone(session.apex_id)
        self.assertIsNone(session.user_name)
        self.assertEqual(session.metadata, {})

    def test_session_metadata_independence(self):
        a = LucySession(session_id="a")
        b = LucySession(session_id="b")
        a.metadata["x"] = 1
        self.assertEqual(b.metadata, {})


class LucyRequestResponseTests(unittest.TestCase):
    def test_request_basic_shape(self):
        session = LucySession(session_id="s-2")
        request = LucyRequest(input_text="hello", session=session)
        self.assertEqual(request.input_text, "hello")
        self.assertIs(request.session, session)
        self.assertEqual(request.metadata, {})

    def test_response_basic_shape(self):
        session = LucySession(session_id="s-3")
        response = LucyResponse(text="hi back", session=session)
        self.assertEqual(response.text, "hi back")
        self.assertIs(response.session, session)
        self.assertEqual(response.tool_calls, [])
        self.assertEqual(response.artifacts, [])
        self.assertIsNone(response.handoff)
        self.assertIsNone(response.trace_id)
        self.assertEqual(response.errors, [])

    def test_response_lists_independence(self):
        session = LucySession(session_id="s-4")
        a = LucyResponse(text="a", session=session)
        b = LucyResponse(text="b", session=session)
        a.tool_calls.append({"name": "x"})
        a.artifacts.append(LucyArtifact(type="link", label="L"))
        a.errors.append({"code": "E"})
        self.assertEqual(b.tool_calls, [])
        self.assertEqual(b.artifacts, [])
        self.assertEqual(b.errors, [])


class LucyArtifactTests(unittest.TestCase):
    def test_minimal(self):
        artifact = LucyArtifact(type="link", label="See more")
        self.assertEqual(artifact.type, "link")
        self.assertEqual(artifact.label, "See more")
        self.assertIsNone(artifact.url)
        self.assertIsNone(artifact.blob_url)
        self.assertIsNone(artifact.expires_at)
        self.assertEqual(artifact.metadata, {})

    def test_full(self):
        artifact = LucyArtifact(
            type="pdf",
            label="Notice packet",
            url="https://example.com/sas",
            blob_url="https://storage.example.com/lucycmnotices/x.pdf",
            expires_at="2026-04-26T00:00:00Z",
            metadata={"container": "lucycmnotices"},
        )
        self.assertEqual(artifact.metadata["container"], "lucycmnotices")


class LucyErrorHierarchyTests(unittest.TestCase):
    def test_error_subclasses(self):
        self.assertTrue(issubclass(ToolExecutionError, LucyError))
        self.assertTrue(issubclass(ResponsesAPIError, LucyError))
        self.assertTrue(issubclass(SessionStateError, LucyError))


class LucyCorePackageImportTests(unittest.TestCase):
    def test_package_import_does_not_eagerly_import_runtime(self):
        script = """
import lucy_core
import sys

assert "lucy_core.runtime" not in sys.modules
assert "lucy_core.responses_loop" not in sys.modules
assert lucy_core.LucyRuntime.__name__ == "LucyRuntime"
assert "lucy_core.runtime" in sys.modules
"""
        result = subprocess.run(
            [sys.executable, "-c", script],
            check=False,
            cwd=Path(__file__).resolve().parents[2],
            env={
                **os.environ,
                "PYTHONPATH": str(Path(__file__).resolve().parents[2] / "agent" / "app"),
            },
            text=True,
            capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
