import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "agent" / "app"))

from foundry_v2_runtime import (
    build_response_payload,
    get_project_openai_client,
    get_startup_mode_snapshot,
    resolve_search_connection_id,
    use_foundry_v2,
)


class DummyConnections:
    def __init__(self, connection_id: str) -> None:
        self._connection_id = connection_id

    def get(self, _name: str):
        class Conn:
            def __init__(self, cid: str) -> None:
                self.id = cid

        return Conn(self._connection_id)


class DummyProjectClient:
    def __init__(self, connection_id: str) -> None:
        self.connections = DummyConnections(connection_id)


class FoundryV2RuntimeTests(unittest.TestCase):
    def setUp(self):
        self._env = dict(os.environ)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._env)

    def test_use_foundry_v2_defaults_true_when_responses_enabled(self):
        os.environ.pop("USE_FOUNDRY_V2", None)
        os.environ["AZURE_RESPONSES_ENABLED"] = "true"
        self.assertTrue(use_foundry_v2())

    def test_use_foundry_v2_respects_explicit_flag(self):
        os.environ["USE_FOUNDRY_V2"] = "false"
        os.environ["AZURE_RESPONSES_ENABLED"] = "true"
        self.assertFalse(use_foundry_v2())

    def test_resolve_search_connection_id_prefers_id(self):
        project = DummyProjectClient("/subscriptions/test/conn")
        result = resolve_search_connection_id("/subscriptions/explicit", None, project)
        self.assertEqual(result, "/subscriptions/explicit")

    def test_resolve_search_connection_id_uses_name(self):
        project = DummyProjectClient("/subscriptions/from-name")
        result = resolve_search_connection_id(None, "my-conn", project)
        self.assertEqual(result, "/subscriptions/from-name")

    def test_build_response_payload_includes_agent_reference(self):
        payload = build_response_payload(
            conversation_id="conv_123",
            user_input="hello",
            agent_name="lucy",
            agent_version="1",
        )
        self.assertEqual(payload["conversation"], "conv_123")
        self.assertEqual(payload["input"], "hello")
        self.assertEqual(
            payload["extra_body"],
            {"agent_reference": {"type": "agent_reference", "name": "lucy", "version": "1"}},
        )

    def test_startup_snapshot_reflects_env(self):
        os.environ["USE_FOUNDRY_V2"] = "true"
        os.environ["AZURE_AI_FOUNDRY_PROJECT_ENDPOINT"] = "https://example"
        os.environ["AI_SEARCH_PROJECT_CONNECTION_ID"] = "conn-id"
        os.environ["AI_SEARCH_PROJECT_CONNECTION_NAME"] = "conn-name"
        os.environ["MODEL_DEPLOYMENT_NAME"] = "gpt-5.2"

        snapshot = get_startup_mode_snapshot()

        self.assertTrue(snapshot["use_foundry_v2"])
        self.assertTrue(snapshot["project_endpoint_set"])
        self.assertTrue(snapshot["search_connection_id_set"])
        self.assertTrue(snapshot["search_connection_name_set"])
        self.assertEqual(snapshot["model_deployment_name"], "gpt-5.2")

    def test_get_project_openai_client_uses_method(self):
        class DummyProject:
            def __init__(self):
                self.called = False

            def get_openai_client(self):
                self.called = True
                return "client"

        project = DummyProject()
        result = get_project_openai_client(project)
        self.assertEqual(result, "client")
        self.assertTrue(project.called)

    def test_get_project_openai_client_raises_when_missing(self):
        class DummyProject:
            pass

        with self.assertRaises(AttributeError):
            get_project_openai_client(DummyProject())


if __name__ == "__main__":
    unittest.main()
