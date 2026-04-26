"""Tests for foundry_init: env-reader helpers, dataclass smoke, and the
private index-name normalizer. The async initialize_foundry_v2_agent flow
is exercised by the running container in staging — its full unit test
would require deep Azure SDK mocking and is out of scope here."""

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "agent" / "app"))

from foundry_init import (
    FoundryInitContext,
    _normalize_search_index_name,
    fallback_publication_state,
    get_agent_name,
    get_application_name_for_agent,
    get_model_deployment_name,
    get_search_connection_id_env,
    get_search_connection_name_env,
    get_search_index_name,
)


class EnvReaderTests(unittest.TestCase):
    def test_get_agent_name_default(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("FOUNDRY_AGENT_NAME", None)
            self.assertEqual(get_agent_name(), "lucy")

    def test_get_agent_name_from_env(self):
        with patch.dict(os.environ, {"FOUNDRY_AGENT_NAME": "lucy-staging"}):
            self.assertEqual(get_agent_name(), "lucy-staging")

    def test_get_model_deployment_name_default(self):
        with patch.dict(os.environ, {}, clear=False):
            for k in ("MODEL_DEPLOYMENT_NAME", "AZURE_AGENT_MODEL", "AZURE_GPT_MODEL"):
                os.environ.pop(k, None)
            self.assertEqual(get_model_deployment_name(), "gpt-4.1")

    def test_get_model_deployment_name_priority(self):
        with patch.dict(
            os.environ,
            {
                "MODEL_DEPLOYMENT_NAME": "first",
                "AZURE_AGENT_MODEL": "second",
                "AZURE_GPT_MODEL": "third",
            },
        ):
            self.assertEqual(get_model_deployment_name(), "first")

    def test_get_model_deployment_name_falls_through(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("MODEL_DEPLOYMENT_NAME", None)
            os.environ.pop("AZURE_AGENT_MODEL", None)
            os.environ["AZURE_GPT_MODEL"] = "third"
            self.assertEqual(get_model_deployment_name(), "third")

    def test_get_application_name_for_agent_uses_agent_name(self):
        # foundry_publish.get_application_name(agent_name) — exact format is
        # owned by that module, just confirm we pass through agent_name.
        with patch.dict(os.environ, {"FOUNDRY_AGENT_NAME": "lucy-test"}):
            result = get_application_name_for_agent()
        self.assertIsInstance(result, str)
        self.assertIn("lucy-test", result)

    def test_get_search_connection_id_env(self):
        with patch.dict(os.environ, {"AI_SEARCH_PROJECT_CONNECTION_ID": "cid-1"}):
            self.assertEqual(get_search_connection_id_env(), "cid-1")

    def test_get_search_connection_name_env_primary(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("AI_AZURE_AI_CONNECTION_ID", None)
            os.environ["AI_SEARCH_PROJECT_CONNECTION_NAME"] = "name-a"
            self.assertEqual(get_search_connection_name_env(), "name-a")

    def test_get_search_connection_name_env_legacy_fallback(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("AI_SEARCH_PROJECT_CONNECTION_NAME", None)
            os.environ["AI_AZURE_AI_CONNECTION_ID"] = "legacy-id"
            self.assertEqual(get_search_connection_name_env(), "legacy-id")


class NormalizeIndexNameTests(unittest.TestCase):
    def test_lowercases(self):
        self.assertEqual(_normalize_search_index_name("MyIndex"), "myindex")

    def test_strips_whitespace(self):
        self.assertEqual(_normalize_search_index_name(" my-index "), "my-index")

    def test_empty_returns_empty(self):
        self.assertEqual(_normalize_search_index_name(""), "")
        self.assertEqual(_normalize_search_index_name(None), "")

    def test_invalid_leading_dash(self):
        with self.assertRaises(ValueError):
            _normalize_search_index_name("-bad")

    def test_invalid_trailing_dash(self):
        with self.assertRaises(ValueError):
            _normalize_search_index_name("bad-")

    def test_invalid_too_long(self):
        with self.assertRaises(ValueError):
            _normalize_search_index_name("a" * 200)

    def test_valid_alphanumeric_with_dashes(self):
        self.assertEqual(_normalize_search_index_name("lucy-notices-v2"), "lucy-notices-v2")


class GetSearchIndexNameTests(unittest.TestCase):
    def test_primary_env_var(self):
        with patch.dict(os.environ, {"AI_SEARCH_INDEX_NAME": "lucy-notices-v2"}, clear=False):
            os.environ.pop("AZURE_SEARCH_INDEX_NAME", None)
            self.assertEqual(get_search_index_name(), "lucy-notices-v2")

    def test_falls_back_to_legacy_env(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("AI_SEARCH_INDEX_NAME", None)
            os.environ["AZURE_SEARCH_INDEX_NAME"] = "legacy-index"
            self.assertEqual(get_search_index_name(), "legacy-index")

    def test_neither_set_returns_empty(self):
        with patch.dict(os.environ, {}, clear=False):
            for k in ("AI_SEARCH_INDEX_NAME", "AZURE_SEARCH_INDEX_NAME"):
                os.environ.pop(k, None)
            self.assertEqual(get_search_index_name(), "")


class FallbackPublicationStateTests(unittest.TestCase):
    def test_empty_deployment_fields(self):
        state = fallback_publication_state("app", "lucy", "5")
        self.assertEqual(state.application_name, "app")
        self.assertEqual(state.deployment_name, "")
        self.assertEqual(state.deployment_id, "")
        self.assertEqual(state.agent_name, "lucy")
        self.assertEqual(state.agent_version, "5")

    def test_coerces_version_to_string(self):
        state = fallback_publication_state("app", "lucy", 7)
        self.assertEqual(state.agent_version, "7")


class FoundryInitContextTests(unittest.TestCase):
    def test_dataclass_construction(self):
        ctx = FoundryInitContext(
            project_client="pc",
            openai_client="oc",
            agent_registry="ar",
            agent_name="lucy",
            agent_version="4",
            function_registry={"f": lambda: None},
        )
        self.assertEqual(ctx.agent_name, "lucy")
        self.assertEqual(ctx.agent_version, "4")
        self.assertIn("f", ctx.function_registry)


if __name__ == "__main__":
    unittest.main()
