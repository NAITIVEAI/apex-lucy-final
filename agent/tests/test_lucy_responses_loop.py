import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "agent" / "app"))

from lucy_core.responses_loop import (
    _apply_request_reasoning,
    build_authenticated_state_items,
    execute_v2_tool_call,
    extract_v2_function_calls,
    run_response_v2,
)
from lucy_core.session import LucySession


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
    """Returns queued responses from .responses.create() and records the kwargs."""

    def __init__(self, queued_responses):
        self._queue = list(queued_responses)
        self.create_calls = []

        outer = self

        class _Responses:
            def create(self, **kwargs):
                outer.create_calls.append(kwargs)
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


class BuildAuthenticatedStateItemsTests(unittest.TestCase):
    def test_unauthenticated_returns_empty(self):
        s = LucySession(session_id="x", authenticated=False)
        self.assertEqual(build_authenticated_state_items(s), [])

    def test_authenticated_no_apex_id_returns_empty(self):
        s = LucySession(session_id="x", authenticated=True, apex_id=None)
        self.assertEqual(build_authenticated_state_items(s), [])

    def test_authenticated_with_apex_id_and_name(self):
        s = LucySession(
            session_id="x",
            authenticated=True,
            apex_id="A123",
            user_name="Jane",
        )
        items = build_authenticated_state_items(s)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["type"], "message")
        self.assertEqual(items[0]["role"], "system")
        self.assertIn("A123", items[0]["content"])
        self.assertIn("Jane", items[0]["content"])

    def test_authenticated_no_user_name_renders_empty_not_none(self):
        s = LucySession(
            session_id="x",
            authenticated=True,
            apex_id="A123",
            user_name=None,
        )
        items = build_authenticated_state_items(s)
        self.assertEqual(len(items), 1)
        # The literal string "None" must NOT leak into the prompt
        self.assertNotIn("None", items[0]["content"])

    def test_pending_notice_intent_is_injected_before_auth(self):
        s = LucySession(
            session_id="x",
            authenticated=False,
            metadata={
                "pending_notice_request": True,
                "pending_notice_request_text": "Could you explain my class action notice to me?",
            },
        )
        items = build_authenticated_state_items(s)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["role"], "system")
        self.assertIn("already asked Lucy", items[0]["content"])
        self.assertIn("explain my class action notice", items[0]["content"])

    def test_pending_notice_and_authenticated_state_are_both_injected(self):
        s = LucySession(
            session_id="x",
            authenticated=True,
            apex_id="A123",
            user_name="Jane",
            metadata={"pending_notice_request": True},
        )
        items = build_authenticated_state_items(s)
        self.assertEqual(len(items), 2)
        self.assertIn("notice", items[0]["content"])
        self.assertIn("A123", items[1]["content"])


class ExtractV2FunctionCallsTests(unittest.TestCase):
    class _AttrItem:
        def __init__(self, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)

    class _AttrResponse:
        def __init__(self, output):
            self.output = output

    def test_dict_shape_function_call(self):
        resp = self._AttrResponse(
            output=[
                {
                    "type": "function_call",
                    "name": "foo",
                    "arguments": '{"a": 1}',
                    "call_id": "c1",
                }
            ]
        )
        calls = extract_v2_function_calls(resp)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["name"], "foo")
        self.assertEqual(calls[0]["call_id"], "c1")
        self.assertEqual(calls[0]["arguments"], '{"a": 1}')

    def test_attr_shape_function_call(self):
        resp = self._AttrResponse(
            output=[
                self._AttrItem(
                    type="function_call",
                    name="bar",
                    arguments='{"x":2}',
                    call_id="c2",
                )
            ]
        )
        calls = extract_v2_function_calls(resp)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["name"], "bar")
        self.assertEqual(calls[0]["call_id"], "c2")

    def test_skips_non_function_call_types(self):
        resp = self._AttrResponse(
            output=[
                {"type": "message", "content": "hi"},
                {"type": "function_call", "name": "f", "arguments": "{}", "call_id": "c"},
            ]
        )
        calls = extract_v2_function_calls(resp)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["name"], "f")

    def test_skips_function_call_without_call_id(self):
        resp = self._AttrResponse(
            output=[
                {"type": "function_call", "name": "f", "arguments": "{}", "call_id": None},
            ]
        )
        self.assertEqual(extract_v2_function_calls(resp), [])

    def test_skips_function_call_without_name(self):
        resp = self._AttrResponse(
            output=[
                {"type": "function_call", "name": None, "arguments": "{}", "call_id": "c"},
            ]
        )
        self.assertEqual(extract_v2_function_calls(resp), [])

    def test_no_output_returns_empty(self):
        resp = self._AttrResponse(output=None)
        self.assertEqual(extract_v2_function_calls(resp), [])

    def test_missing_arguments_defaults_to_empty_object(self):
        resp = self._AttrResponse(
            output=[
                {"type": "function_call", "name": "f", "arguments": None, "call_id": "c"},
            ]
        )
        calls = extract_v2_function_calls(resp)
        self.assertEqual(calls[0]["arguments"], "{}")


class ExecuteV2ToolCallTests(unittest.TestCase):
    def test_unknown_tool_returns_error(self):
        result = execute_v2_tool_call("missing", "{}", {})
        parsed = json.loads(result)
        self.assertIn("error", parsed)
        self.assertIn("missing", parsed["error"])

    def test_invokes_callable_with_filtered_args(self):
        def echo(a, b=None):
            return {"a": a, "b": b}

        registry = {"echo": echo}
        result = execute_v2_tool_call(
            "echo", '{"a": 1, "b": 2, "c": "ignored"}', registry
        )
        # Only a and b are in echo's signature; c must be filtered out before invocation
        self.assertEqual(json.loads(result), {"a": 1, "b": 2})

    def test_invalid_json_arguments_treated_as_empty(self):
        def no_args():
            return {"ok": True}

        registry = {"no_args": no_args}
        result = execute_v2_tool_call("no_args", "not json!", registry)
        self.assertEqual(json.loads(result), {"ok": True})

    def test_non_dict_payload_treated_as_empty(self):
        def no_args():
            return {"ok": True}

        registry = {"no_args": no_args}
        # JSON parses to a list, not a dict — should be coerced to {}
        result = execute_v2_tool_call("no_args", "[1, 2, 3]", registry)
        self.assertEqual(json.loads(result), {"ok": True})

    def test_string_result_passed_through(self):
        registry = {"f": lambda: "raw string"}
        self.assertEqual(execute_v2_tool_call("f", "{}", registry), "raw string")

    def test_tool_exception_returns_error_payload(self):
        def boom():
            raise ValueError("nope")

        registry = {"boom": boom}
        result = execute_v2_tool_call("boom", "{}", registry)
        parsed = json.loads(result)
        self.assertIn("error", parsed)
        self.assertIn("nope", parsed["error"])

    def test_async_tool_executed_via_asyncio_run(self):
        async def async_tool():
            return {"async": True}

        registry = {"async_tool": async_tool}
        result = execute_v2_tool_call("async_tool", "{}", registry)
        self.assertEqual(json.loads(result), {"async": True})

    def test_unserializable_result_falls_back_to_str_representation(self):
        class Opaque:
            def __repr__(self):
                return "<opaque>"

        registry = {"f": lambda: Opaque()}
        result = execute_v2_tool_call("f", "{}", registry)
        parsed = json.loads(result)
        self.assertIn("result", parsed)
        self.assertEqual(parsed["result"], "<opaque>")


class RunResponseV2Tests(unittest.IsolatedAsyncioTestCase):
    """End-to-end tests for the orchestrator. Mocks the OpenAI client and the
    function registry; uses real build_response_payload / build_agent_reference
    / extract_response_text helpers (they live in agent/app/ and are Chainlit-free)."""

    def _clean_env(self):
        # Strip Responses-API env vars so tests aren't polluted by host config.
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

    async def test_basic_no_tool_calls(self):
        """Single response, no function calls — text passes through, tool_outputs empty."""
        mock_client = _MockOpenAIClient([
            _MockResponse(response_id="r-1", output_text="hello back"),
        ])
        session = LucySession(session_id="s-1")
        with self._clean_env():
            result = await run_response_v2(
                user_text="hi",
                session=session,
                openai_client=mock_client,
                agent_name="lucy",
                agent_version="4",
                function_registry={},
            )
        self.assertEqual(result["text"], "hello back")
        self.assertEqual(result["tool_outputs"], [])
        self.assertEqual(session.previous_response_id, "r-1")
        self.assertEqual(session.last_eval_final_response_id, "r-1")

    async def test_agent_reference_suppresses_explicit_reasoning_effort(self):
        """Gateway agent_reference calls must not inherit model-specific reasoning settings."""
        mock_client = _MockOpenAIClient([
            _MockResponse(response_id="r-1", output_text="hello back"),
        ])
        session = LucySession(session_id="s-1")
        with patch.dict(
            os.environ,
            {
                "AZURE_RESPONSES_MAX_OUTPUT_TOKENS": "",
                "AZURE_RESPONSES_REASONING_EFFORT": "low",
                "AZURE_RESPONSES_STORE": "",
                "AZURE_RESPONSES_MAX_TOOL_LOOPS": "6",
            },
            clear=False,
        ):
            await run_response_v2(
                user_text="hi",
                session=session,
                openai_client=mock_client,
                agent_name="lucy",
                agent_version="4",
                function_registry={},
            )

        self.assertIn("agent_reference", mock_client.create_calls[0]["extra_body"])
        self.assertNotIn("reasoning", mock_client.create_calls[0])

    def test_gpt52_request_reasoning_low_is_suppressed_without_agent_reference(self):
        payload = {"input": "hello"}
        with patch.dict(
            os.environ,
            {
                "MODEL_DEPLOYMENT_NAME": "gpt-5.2-chat",
                "AZURE_AGENT_MODEL": "",
                "AZURE_GPT_MODEL": "",
                "AZURE_RESPONSES_REASONING_EFFORT": "low",
            },
            clear=False,
        ):
            _apply_request_reasoning(payload)

        self.assertNotIn("reasoning", payload)

    def test_non_gpt52_request_reasoning_uses_explicit_env(self):
        payload = {"input": "hello"}
        with patch.dict(
            os.environ,
            {
                "MODEL_DEPLOYMENT_NAME": "gpt-5",
                "AZURE_AGENT_MODEL": "",
                "AZURE_GPT_MODEL": "",
                "AZURE_RESPONSES_REASONING_EFFORT": "low",
            },
            clear=False,
        ):
            _apply_request_reasoning(payload)

        self.assertEqual(payload["reasoning"], {"effort": "low"})

    async def test_one_tool_call_then_final(self):
        """First response triggers a function call; tool runs; second response is final text."""
        executed_args = {}

        def my_tool(x):
            executed_args["x"] = x
            return {"ok": True, "x": x}

        mock_client = _MockOpenAIClient([
            _MockResponse(
                response_id="r-1",
                output=[_function_call_item("my_tool", '{"x": 42}', "call-1")],
            ),
            _MockResponse(response_id="r-2", output_text="done"),
        ])
        session = LucySession(session_id="s-1")
        with self._clean_env():
            result = await run_response_v2(
                user_text="please run tool",
                session=session,
                openai_client=mock_client,
                agent_name="lucy",
                agent_version="4",
                function_registry={"my_tool": my_tool},
            )
        self.assertEqual(executed_args, {"x": 42})
        self.assertEqual(result["text"], "done")
        self.assertEqual(len(result["tool_outputs"]), 1)
        self.assertEqual(result["tool_outputs"][0]["name"], "my_tool")
        self.assertEqual(result["tool_outputs"][0]["call_id"], "call-1")
        self.assertEqual(session.previous_response_id, "r-2")
        # Two API calls: initial + tool follow-up
        self.assertEqual(len(mock_client.create_calls), 2)

    async def test_async_tool_executes_inside_live_response_loop(self):
        """Async registered tools must work in the already-running event loop."""
        async def async_tool(x):
            return {"x": x, "async": True}

        mock_client = _MockOpenAIClient([
            _MockResponse(
                response_id="r-1",
                output=[_function_call_item("async_tool", '{"x": 7}', "call-async")],
            ),
            _MockResponse(response_id="r-2", output_text="done"),
        ])
        session = LucySession(session_id="s-1")
        with self._clean_env():
            result = await run_response_v2(
                user_text="run async",
                session=session,
                openai_client=mock_client,
                agent_name="lucy",
                agent_version="4",
                function_registry={"async_tool": async_tool},
            )
        self.assertEqual(result["text"], "done")
        self.assertEqual(len(result["tool_outputs"]), 1)
        self.assertEqual(result["tool_outputs"][0]["name"], "async_tool")
        self.assertEqual(
            json.loads(result["tool_outputs"][0]["output"]),
            {"x": 7, "async": True},
        )

    async def test_max_tool_loops_bails(self):
        """When responses keep emitting function calls, the loop bails after the configured max."""

        def loop_tool():
            return "again"

        # Every response emits another function call — should bail at max_loops + 1 final break
        responses = [
            _MockResponse(
                response_id=f"r-{i}",
                output=[_function_call_item("loop_tool", "{}", f"call-{i}")],
            )
            for i in range(10)
        ]
        mock_client = _MockOpenAIClient(responses)
        session = LucySession(session_id="s-1")
        with patch.dict(
            os.environ,
            {
                "AZURE_RESPONSES_MAX_TOOL_LOOPS": "2",
                "AZURE_RESPONSES_MAX_OUTPUT_TOKENS": "",
                "AZURE_RESPONSES_REASONING_EFFORT": "",
                "AZURE_RESPONSES_STORE": "",
            },
            clear=False,
        ):
            result = await run_response_v2(
                user_text="loop me",
                session=session,
                openai_client=mock_client,
                agent_name="lucy",
                agent_version="4",
                function_registry={"loop_tool": loop_tool},
            )
        # 1 initial call + 2 follow-ups (max_loops=2) = 3 total
        self.assertEqual(len(mock_client.create_calls), 3)
        # 2 tool outputs recorded (one per loop iteration)
        self.assertEqual(len(result["tool_outputs"]), 2)

    async def test_authenticated_session_injects_state_items(self):
        """When session.authenticated, the initial payload's input contains the system message."""
        mock_client = _MockOpenAIClient([
            _MockResponse(response_id="r-1", output_text="hi"),
        ])
        session = LucySession(
            session_id="s-1",
            authenticated=True,
            apex_id="A123",
            user_name="Jane",
        )
        with self._clean_env():
            await run_response_v2(
                user_text="hello",
                session=session,
                openai_client=mock_client,
                agent_name="lucy",
                agent_version="4",
                function_registry={},
            )
        first_call = mock_client.create_calls[0]
        # When no conversation_id and state_items present, input becomes a list with system + user
        self.assertIsInstance(first_call["input"], list)
        self.assertEqual(first_call["input"][0]["role"], "system")
        self.assertIn("A123", first_call["input"][0]["content"])
        self.assertEqual(first_call["input"][1]["role"], "user")

    async def test_unauthenticated_session_no_state_items(self):
        """When session.authenticated is False, input stays as a plain string (the user_text)."""
        mock_client = _MockOpenAIClient([
            _MockResponse(response_id="r-1", output_text="hi"),
        ])
        session = LucySession(session_id="s-1", authenticated=False)
        with self._clean_env():
            await run_response_v2(
                user_text="hello",
                session=session,
                openai_client=mock_client,
                agent_name="lucy",
                agent_version="4",
                function_registry={},
            )
        first_call = mock_client.create_calls[0]
        self.assertEqual(first_call["input"], "hello")

    async def test_eval_metadata_applied_to_payload(self):
        """First payload includes lucy_eval_* metadata for trace correlation."""
        mock_client = _MockOpenAIClient([
            _MockResponse(response_id="r-1", output_text="hi"),
        ])
        session = LucySession(session_id="s-1")
        with self._clean_env():
            await run_response_v2(
                user_text="hi",
                session=session,
                openai_client=mock_client,
                agent_name="lucy",
                agent_version="4",
                function_registry={},
            )
        first_call = mock_client.create_calls[0]
        self.assertIn("metadata", first_call)
        self.assertIn("lucy_eval_turn_id", first_call["metadata"])
        self.assertEqual(first_call["metadata"]["lucy_eval_step"], "initial")
        self.assertEqual(first_call["metadata"]["lucy_eval_step_index"], "0")

    async def test_session_conversation_id_captured_from_response(self):
        """When the response carries a conversation_id and session has none, capture it onto session."""
        mock_client = _MockOpenAIClient([
            _MockResponse(response_id="r-1", output_text="hi", conversation_id="conv-x"),
        ])
        session = LucySession(session_id="s-1", conversation_id=None)
        with self._clean_env():
            await run_response_v2(
                user_text="hi",
                session=session,
                openai_client=mock_client,
                agent_name="lucy",
                agent_version="4",
                function_registry={},
            )
        self.assertEqual(session.conversation_id, "conv-x")


if __name__ == "__main__":
    unittest.main()
