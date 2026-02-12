import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "agent" / "app"))

from response_utils import extract_response_text


class DummyResponse:
    def __init__(self, output_text=None, output=None):
        self.output_text = output_text
        self.output = output or []


class ResponseUtilsTests(unittest.TestCase):
    def test_extract_prefers_output_text(self):
        resp = DummyResponse(output_text="hello")
        self.assertEqual(extract_response_text(resp), "hello")

    def test_extract_from_output_items(self):
        resp = DummyResponse(
            output=[
                {
                    "type": "message",
                    "content": [
                        {"type": "output_text", "text": "hi"},
                    ],
                }
            ]
        )
        self.assertEqual(extract_response_text(resp), "hi")


if __name__ == "__main__":
    unittest.main()
