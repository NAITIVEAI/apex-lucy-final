import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "agent" / "app"))

from lucy_core.handoff import (
    extract_handoff_from_tool_outputs,
    handoff_artifact_from_payload,
    normalize_handoff_payload,
)


class LucyHandoffNormalizationTests(unittest.TestCase):
    def test_normalize_success_payload(self):
        raw = {
            "success": True,
            "conversation_id": "conv-1",
            "portal_url": "https://portal.example/agent/conversation/conv-1",
            "message": "Human handoff created",
            "agent_name": "Agent A",
            "apex_id": "A123",
        }
        normalized = normalize_handoff_payload(raw, reason="Need help")
        self.assertEqual(normalized["created"], True)
        self.assertEqual(normalized["conversation_id"], "conv-1")
        self.assertEqual(normalized["status"], "pending")
        self.assertEqual(normalized["reason"], "Need help")
        self.assertEqual(normalized["portal_url"], raw["portal_url"])

    def test_extracts_payload_from_tool_output(self):
        payload = extract_handoff_from_tool_outputs(
            [
                {
                    "name": "send_handoff_notification_email_sync",
                    "output": (
                        '{"success": true, "conversation_id": "conv-2", '
                        '"portal_url": "https://portal.example/agent/conversation/conv-2", '
                        '"message": "Handoff created"}'
                    ),
                    "call_id": "c1",
                    "arguments": "{}",
                }
            ],
            reason="Need support",
        )
        self.assertIsNotNone(payload)
        self.assertEqual(payload["conversation_id"], "conv-2")
        self.assertEqual(payload["reason"], "Need support")

    def test_handoff_artifact_uses_portal_url(self):
        artifact = handoff_artifact_from_payload(
            {
                "created": True,
                "conversation_id": "conv-3",
                "status": "pending",
                "portal_url": "https://portal.example/agent/conversation/conv-3",
                "message": "Human handoff created",
            }
        )
        self.assertIsNotNone(artifact)
        self.assertEqual(artifact.type, "handoff")
        self.assertEqual(artifact.url, "https://portal.example/agent/conversation/conv-3")
        self.assertEqual(artifact.metadata["conversation_id"], "conv-3")


if __name__ == "__main__":
    unittest.main()
