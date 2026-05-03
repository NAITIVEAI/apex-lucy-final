import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "agent" / "app"))

from lucy_core.artifacts import extract_artifacts_from_text, extract_artifacts_from_tool_outputs


class LucyArtifactExtractionTests(unittest.TestCase):
    def test_extracts_pdf_artifact_from_structured_text(self):
        artifacts = extract_artifacts_from_text(
            "**PDF_DISPLAY_INFO:**\n"
            "- PDF_URL: https://example.com/lucycmnotices/notice.pdf?sig=abc\n"
            "- PDF_NAME: Notice Packet\n"
            "- DISPLAY_MODE: side"
        )
        self.assertEqual(len(artifacts), 1)
        self.assertEqual(artifacts[0].type, "pdf")
        self.assertEqual(artifacts[0].label, "Notice Packet")
        self.assertIn("sig=abc", artifacts[0].url)
        self.assertEqual(artifacts[0].metadata["display"], "side")

    def test_extracts_link_artifact_from_tool_output(self):
        artifacts = extract_artifacts_from_tool_outputs(
            [
                {
                    "name": "some_tool",
                    "output": "See the docs at https://example.com/docs/guide",
                    "call_id": "c1",
                    "arguments": "{}",
                }
            ]
        )
        self.assertEqual(len(artifacts), 1)
        self.assertEqual(artifacts[0].type, "link")
        self.assertEqual(artifacts[0].url, "https://example.com/docs/guide")


if __name__ == "__main__":
    unittest.main()
