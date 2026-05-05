import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "agent" / "app"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "agent"))

from hosted_agent.app import (  # noqa: E402
    lucy_response_metadata,
    lucy_response_to_events,
    request_to_lucy_request,
)
from lucy_core import LucyArtifact, LucyResponse, LucySession  # noqa: E402


class _FakeRequest:
    def __init__(self, *, metadata=None, previous_response_id=None, conversation=None):
        self.metadata = metadata or {}
        self.previous_response_id = previous_response_id
        self.conversation = conversation


class _RequestWithoutPreviousResponseId:
    metadata = {}
    conversation = None


class _FakeIsolation:
    chat_key = "chat-key-1"


class _FakeContext:
    def __init__(
        self,
        text="hello",
        conversation_id="conv-foundry",
        previous_response_id="caresp-prev",
    ):
        self.response_id = "caresp-current"
        self.conversation_id = conversation_id
        self.previous_response_id = previous_response_id
        self.isolation = _FakeIsolation()
        self._text = text

    async def get_input_text(self):
        return self._text


class _FakeStreamResponse:
    metadata = None


class _FakeStream:
    def __init__(self, *, response_id, request):
        self.response_id = response_id
        self.request = request
        self.response = _FakeStreamResponse()

    def emit_created(self):
        return {"type": "response.created"}

    def emit_in_progress(self):
        return {"type": "response.in_progress"}

    def output_item_message(self, text):
        yield {"type": "response.output_text.delta", "text": text}

    def emit_completed(self):
        return {"type": "response.completed", "metadata": self.response.metadata}


class HostedRequestMappingTests(unittest.IsolatedAsyncioTestCase):
    async def test_maps_foundry_context_and_lucy_session_metadata(self):
        request = _FakeRequest(
            metadata={
                "lucy_session": {
                    "session_id": "lucy-s",
                    "conversation_id": "conv-inner",
                    "previous_response_id": "resp_inner_prev",
                    "authenticated": True,
                    "apex_id": "25ONRR2063",
                    "user_name": "Robert Williams",
                    "pending_notice_request": True,
                    "pending_notice_request_text": "explain my notice",
                    "metadata": {"source": "chainlit"},
                }
            }
        )
        lucy_request = await request_to_lucy_request(request, _FakeContext())

        self.assertEqual(lucy_request.input_text, "hello")
        self.assertEqual(lucy_request.session.session_id, "lucy-s")
        self.assertEqual(lucy_request.session.conversation_id, "conv-inner")
        self.assertEqual(lucy_request.session.previous_response_id, "resp_inner_prev")
        self.assertTrue(lucy_request.session.authenticated)
        self.assertEqual(lucy_request.session.apex_id, "25ONRR2063")
        self.assertEqual(
            lucy_request.session.metadata["foundry_conversation_id"],
            "conv-foundry",
        )
        self.assertEqual(
            lucy_request.session.metadata["foundry_previous_response_id"],
            "caresp-prev",
        )
        self.assertTrue(lucy_request.session.metadata["pending_notice_request"])
        self.assertEqual(
            lucy_request.session.metadata["pending_notice_request_text"],
            "explain my notice",
        )

    async def test_string_false_does_not_authenticate_session(self):
        request = _FakeRequest(
            metadata={
                "authenticated": "false",
                "apex_id": "25ONRR2063",
                "pending_notice_request": "false",
            }
        )

        lucy_request = await request_to_lucy_request(request, _FakeContext())

        self.assertFalse(lucy_request.session.authenticated)
        self.assertFalse(lucy_request.session.metadata["pending_notice_request"])

    async def test_true_like_string_authenticates_session(self):
        request = _FakeRequest(
            metadata={
                "lucy_session": {
                    "authenticated": "true",
                    "apex_id": "25ONRR2063",
                }
            }
        )

        lucy_request = await request_to_lucy_request(request, _FakeContext())

        self.assertTrue(lucy_request.session.authenticated)

    async def test_falls_back_to_context_session_identity(self):
        lucy_request = await request_to_lucy_request(_FakeRequest(), _FakeContext())

        self.assertEqual(lucy_request.session.session_id, "chat-key-1")
        self.assertIsNone(lucy_request.session.conversation_id)
        self.assertIsNone(lucy_request.session.previous_response_id)
        self.assertEqual(lucy_request.session.metadata["foundry_response_id"], "caresp-current")

    async def test_top_level_inner_previous_response_id_is_preserved(self):
        request = _FakeRequest(previous_response_id="resp_inner_prev")

        lucy_request = await request_to_lucy_request(
            request,
            _FakeContext(previous_response_id="caresp-prev"),
        )

        self.assertEqual(lucy_request.session.previous_response_id, "resp_inner_prev")

    async def test_request_without_previous_response_id_attribute_is_safe(self):
        lucy_request = await request_to_lucy_request(
            _RequestWithoutPreviousResponseId(),
            _FakeContext(previous_response_id="caresp-prev"),
        )

        self.assertIsNone(lucy_request.session.previous_response_id)

    async def test_hosted_wrapper_response_id_is_not_forwarded_to_inner_agent(self):
        request = _FakeRequest(previous_response_id="caresp-prev")

        lucy_request = await request_to_lucy_request(request, _FakeContext())

        self.assertIsNone(lucy_request.session.previous_response_id)


class HostedResponseMappingTests(unittest.TestCase):
    def test_metadata_preserves_session_artifacts_tools_and_handoff(self):
        response = LucyResponse(
            text="done",
            session=LucySession(
                session_id="s",
                conversation_id="c",
                previous_response_id="r",
                authenticated=True,
                apex_id="A123",
            ),
            tool_calls=[{"name": "find_notice", "output": "ok"}],
            artifacts=[
                LucyArtifact(
                    type="pdf",
                    label="Notice",
                    url="https://example.com/notice.pdf",
                    metadata={"apex_id": "A123"},
                )
            ],
            handoff={"created": True},
            trace_id="trace",
            errors=[{"code": "none"}],
        )

        metadata = lucy_response_metadata(response)

        self.assertEqual(metadata["lucy_session"]["previous_response_id"], "r")
        self.assertEqual(metadata["lucy_artifacts"][0]["type"], "pdf")
        self.assertEqual(metadata["lucy_tool_calls"][0]["name"], "find_notice")
        self.assertEqual(metadata["lucy_handoff"], {"created": True})
        self.assertEqual(metadata["lucy_trace_id"], "trace")

    def test_response_events_emit_message_and_completion_metadata(self):
        request = _FakeRequest(metadata={"existing": "kept"})
        response = LucyResponse(
            text="hello from Lucy",
            session=LucySession(session_id="s", previous_response_id="resp-lucy"),
        )

        events = list(
            lucy_response_to_events(
                response,
                request,
                _FakeContext(),
                stream_cls=_FakeStream,
            )
        )

        self.assertEqual([event["type"] for event in events], [
            "response.created",
            "response.in_progress",
            "response.output_text.delta",
            "response.completed",
        ])
        self.assertEqual(events[2]["text"], "hello from Lucy")
        self.assertEqual(events[-1]["metadata"]["existing"], "kept")
        self.assertEqual(
            events[-1]["metadata"]["lucy_session"]["previous_response_id"],
            "resp-lucy",
        )


if __name__ == "__main__":
    unittest.main()
