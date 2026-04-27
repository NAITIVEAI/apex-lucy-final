import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "agent" / "app"))

from foundry_v2 import build_agent_reference


class AgentReferenceTests(unittest.TestCase):
    def test_build_agent_reference_payload(self):
        payload = build_agent_reference("lucy", "1")
        self.assertEqual(
            payload,
            {"agent_reference": {"type": "agent_reference", "name": "lucy", "version": "1"}},
        )


if __name__ == "__main__":
    unittest.main()
