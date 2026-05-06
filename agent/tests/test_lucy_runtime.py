import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "agent" / "app"))

from lucy_core import LucyRequest, LucyResponse, LucyRuntime, LucySession


class _MockResponse:
    def __init__(
        self,
        response_id="r-1",
        output=None,
        output_text="",
        conversation=None,
        conversation_id=None,
    ):
        self.id = response_id
        self.output = output if output is not None else []
        self.output_text = output_text
        self.conversation = conversation
        self.conversation_id = conversation_id


class _MockOpenAIClient:
    def __init__(self, queued):
        self._queue = list(queued)
        self.calls = []

        outer = self

        class _Responses:
            def create(self, **kwargs):
                outer.calls.append(kwargs)
                if not outer._queue:
                    raise AssertionError("No more queued responses for mock client")
                return outer._queue.pop(0)

        self.responses = _Responses()


def _function_call_item(name, arguments, call_id):
    return {
        "type": "function_call",
        "name": name,
        "arguments": arguments,
        "call_id": call_id,
    }


def _clean_env():
    return patch.dict(
        os.environ,
        {
            "AZURE_RESPONSES_MAX_OUTPUT_TOKENS": "",
            "AZURE_RESPONSES_REASONING_EFFORT": "",
            "AZURE_RESPONSES_STORE": "",
            "AZURE_RESPONSES_MAX_TOOL_LOOPS": "6",
        },
        clear=False,
    )


class LucyRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_respond_basic_no_tools(self):
        client = _MockOpenAIClient([
            _MockResponse(response_id="r-1", output_text="hi back"),
        ])
        runtime = LucyRuntime(
            openai_client=client,
            agent_name="lucy",
            agent_version="4",
            function_registry={},
        )
        session = LucySession(session_id="s-1")
        request = LucyRequest(input_text="hello", session=session)
        with _clean_env():
            response = await runtime.respond(request)
        self.assertIsInstance(response, LucyResponse)
        self.assertEqual(response.text, "hi back")
        self.assertIs(response.session, session)
        self.assertEqual(response.tool_calls, [])
        self.assertEqual(response.artifacts, [])
        self.assertIsNone(response.handoff)
        self.assertEqual(response.errors, [])

    async def test_respond_with_tool_call(self):
        executed = {}

        def my_tool(x):
            executed["x"] = x
            return {"ok": True}

        client = _MockOpenAIClient([
            _MockResponse(
                response_id="r-1",
                output=[
                    {
                        "type": "function_call",
                        "name": "my_tool",
                        "arguments": '{"x": 1}',
                        "call_id": "c1",
                    }
                ],
            ),
            _MockResponse(response_id="r-2", output_text="done"),
        ])
        runtime = LucyRuntime(
            openai_client=client,
            agent_name="lucy",
            agent_version="4",
            function_registry={"my_tool": my_tool},
        )
        request = LucyRequest(
            input_text="please run tool",
            session=LucySession(session_id="s-1"),
        )
        with _clean_env():
            response = await runtime.respond(request)
        self.assertEqual(response.text, "done")
        self.assertEqual(len(response.tool_calls), 1)
        self.assertEqual(response.tool_calls[0]["name"], "my_tool")
        self.assertEqual(response.tool_calls[0]["call_id"], "c1")
        self.assertEqual(executed, {"x": 1})

    async def test_respond_extracts_pdf_artifact(self):
        def find_notice_for_user_sync(apex_id):
            return (
                "**PDF_DISPLAY_INFO:**\n"
                "- PDF_URL: https://example.com/lucycmnotices/notice.pdf?sig=abc\n"
                "- PDF_NAME: Notice Packet\n"
                "- DISPLAY_MODE: side"
            )

        client = _MockOpenAIClient([
            _MockResponse(
                response_id="r-1",
                output=[
                    _function_call_item(
                        "find_notice_for_user_sync",
                        '{"apex_id": "A123"}',
                        "call-pdf",
                    )
                ],
            ),
            _MockResponse(response_id="r-2", output_text="Here is the notice."),
        ])
        runtime = LucyRuntime(
            openai_client=client,
            agent_name="lucy",
            agent_version="4",
            function_registry={"find_notice_for_user_sync": find_notice_for_user_sync},
        )
        request = LucyRequest(
            input_text="show me my notice",
            session=LucySession(session_id="s-1"),
        )
        with _clean_env():
            response = await runtime.respond(request)
        self.assertEqual(response.text, "Here is the notice.")
        self.assertEqual(len(response.artifacts), 1)
        self.assertEqual(response.artifacts[0].type, "pdf")
        self.assertEqual(response.artifacts[0].label, "Notice Packet")
        self.assertIn("sig=abc", response.artifacts[0].url)
        self.assertIsNone(response.handoff)

    async def test_respond_marks_notice_miss_terminal_in_session_metadata(self):
        def find_notice_for_user_sync(apex_id):
            return (
                "I couldn't find a notice document for APEX ID A123. "
                "This sometimes happens when there's a delay."
            )

        client = _MockOpenAIClient([
            _MockResponse(
                response_id="r-1",
                output=[
                    _function_call_item(
                        "find_notice_for_user_sync",
                        '{"apex_id": "A123"}',
                        "call-miss",
                    )
                ],
            ),
            _MockResponse(response_id="r-2", output_text="I could not find the notice."),
        ])
        runtime = LucyRuntime(
            openai_client=client,
            agent_name="lucy",
            agent_version="4",
            function_registry={"find_notice_for_user_sync": find_notice_for_user_sync},
        )
        session = LucySession(
            session_id="s-1",
            authenticated=True,
            apex_id="A123",
            metadata={
                "pending_notice_request": True,
                "pending_notice_request_text": "explain my notice",
            },
        )
        request = LucyRequest(input_text="A123", session=session)
        with _clean_env():
            response = await runtime.respond(request)

        self.assertEqual(response.text, "I could not find the notice.")
        self.assertFalse(session.metadata["pending_notice_request"])
        self.assertEqual(session.metadata["pending_notice_request_text"], "")
        self.assertEqual(session.metadata["notice_lookup_status"], "not_found")
        self.assertEqual(session.metadata["notice_lookup_apex_id"], "A123")

    async def test_respond_extracts_handoff_payload_and_artifact(self):
        def send_handoff_notification_email_sync(apex_id, reason=None):
            return (
                '{"success": true, "message": "Human handoff created", '
                '"agent_name": "Agent A", "handoff_id": "conv-9", '
                '"conversation_id": "conv-9", '
                '"portal_url": "https://portal.example/agent/conversation/conv-9", '
                '"user_portal_url": "https://portal.example/chat/conv-9", '
                '"apex_id": "A123", "establish_bridge": false, "wait_for_agent_join": false}'
            )

        client = _MockOpenAIClient([
            _MockResponse(
                response_id="r-1",
                output=[
                    _function_call_item(
                        "send_handoff_notification_email_sync",
                        '{"apex_id": "A123", "reason": "Need help"}',
                        "call-handoff",
                    )
                ],
            ),
            _MockResponse(response_id="r-2", output_text="Human handoff created."),
        ])
        runtime = LucyRuntime(
            openai_client=client,
            agent_name="lucy",
            agent_version="4",
            function_registry={
                "send_handoff_notification_email_sync": send_handoff_notification_email_sync
            },
        )
        request = LucyRequest(
            input_text="I need a human",
            session=LucySession(session_id="s-1"),
            metadata={"handoff_reason": "Need help"},
        )
        with _clean_env():
            response = await runtime.respond(request)
        self.assertIsNotNone(response.handoff)
        self.assertEqual(response.handoff["created"], True)
        self.assertEqual(response.handoff["conversation_id"], "conv-9")
        self.assertEqual(response.handoff["status"], "pending")
        self.assertEqual(response.handoff["reason"], "Need help")
        self.assertEqual(response.artifacts[-1].type, "handoff")
        self.assertEqual(response.artifacts[-1].url, "https://portal.example/agent/conversation/conv-9")

    async def test_respond_mutates_session_in_place(self):
        client = _MockOpenAIClient([
            _MockResponse(
                response_id="r-1",
                output_text="ok",
                conversation_id="conv-x",
            ),
        ])
        runtime = LucyRuntime(
            openai_client=client,
            agent_name="lucy",
            agent_version="4",
            function_registry={},
        )
        session = LucySession(session_id="s-1")
        request = LucyRequest(input_text="hi", session=session)
        with _clean_env():
            response = await runtime.respond(request)
        # Mutations land on the original session object
        self.assertEqual(session.previous_response_id, "r-1")
        self.assertEqual(session.last_eval_final_response_id, "r-1")
        self.assertEqual(session.conversation_id, "conv-x")
        # Response carries the same session reference
        self.assertIs(response.session, session)


if __name__ == "__main__":
    unittest.main()
