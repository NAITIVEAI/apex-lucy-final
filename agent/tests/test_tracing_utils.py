import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "agent" / "app"))

from tracing_utils import get_status_classes


class TracingUtilsTests(unittest.TestCase):
    def test_get_status_classes_returns_status_and_code(self):
        Status, StatusCode = get_status_classes()
        self.assertTrue(hasattr(StatusCode, "ERROR"))
        self.assertTrue(hasattr(StatusCode, "OK"))
        self.assertTrue(callable(Status))


if __name__ == "__main__":
    unittest.main()
