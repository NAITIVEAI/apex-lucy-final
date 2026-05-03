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


if __name__ == "__main__":
    unittest.main()
