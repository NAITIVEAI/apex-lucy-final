import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "agent" / "app"))


class TestPromptHash(unittest.TestCase):
    def test_prompt_hash_is_stable(self) -> None:
        from prompt_utils import compute_prompt_hash

        first = compute_prompt_hash()
        time.sleep(1)
        second = compute_prompt_hash()
        self.assertEqual(first, second)

    def test_prompt_hash_changed_detects_mismatch(self) -> None:
        from prompt_utils import prompt_hash_changed

        self.assertTrue(prompt_hash_changed(None, "abc"))
        self.assertTrue(prompt_hash_changed({}, "abc"))
        self.assertTrue(prompt_hash_changed({"prompt_hash": "old"}, "new"))
        self.assertFalse(prompt_hash_changed({"prompt_hash": "same"}, "same"))


if __name__ == "__main__":
    unittest.main()
