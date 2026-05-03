import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "agent"))

from hosted_agent.deploy_hosted_agent import _env_mapping  # noqa: E402


class HostedDeployEnvTests(unittest.TestCase):
    def test_hosted_agent_name_overrides_stale_gateway_otel_id(self):
        with patch.dict(
            os.environ,
            {
                "LUCY_OTEL_AGENT_ID": "lucy-aca",
                "OTEL_SERVICE_NAME": "old-service",
            },
            clear=True,
        ):
            env = _env_mapping([], agent_name="agent-lucy-hosted-ncus")

        self.assertEqual(env["LUCY_OTEL_AGENT_ID"], "agent-lucy-hosted-ncus")
        self.assertEqual(env["OTEL_SERVICE_NAME"], "lucy-hosted-agent")

    def test_hosted_otel_override_is_explicit(self):
        with patch.dict(
            os.environ,
            {"LUCY_HOSTED_OTEL_AGENT_ID": "agent-lucy-hosted-canary"},
            clear=True,
        ):
            env = _env_mapping([], agent_name="agent-lucy-hosted-ncus")

        self.assertEqual(env["LUCY_OTEL_AGENT_ID"], "agent-lucy-hosted-canary")

    def test_forwards_foundry_search_runtime_keys(self):
        with patch.dict(
            os.environ,
            {
                "AI_SEARCH_PROJECT_CONNECTION_ID": "conn-id",
                "AI_SEARCH_PROJECT_CONNECTION_NAME": "conn-name",
                "AI_SEARCH_INDEX_NAME": "lucy-notices-v2",
                "AZURE_SEARCH_INDEX_NAME": "legacy-index",
            },
            clear=True,
        ):
            env = _env_mapping([], agent_name="agent-lucy-hosted-ncus")

        self.assertEqual(env["AI_SEARCH_PROJECT_CONNECTION_ID"], "conn-id")
        self.assertEqual(env["AI_SEARCH_PROJECT_CONNECTION_NAME"], "conn-name")
        self.assertEqual(env["AI_SEARCH_INDEX_NAME"], "lucy-notices-v2")
        self.assertEqual(env["AZURE_SEARCH_INDEX_NAME"], "legacy-index")

    def test_maps_legacy_azure_search_index_to_consumed_name(self):
        with patch.dict(os.environ, {"AZURE_SEARCH_INDEX": "legacy-search"}, clear=True):
            env = _env_mapping([], agent_name="agent-lucy-hosted-ncus")

        self.assertEqual(env["AZURE_SEARCH_INDEX"], "legacy-search")
        self.assertEqual(env["AI_SEARCH_INDEX_NAME"], "legacy-search")


if __name__ == "__main__":
    unittest.main()
