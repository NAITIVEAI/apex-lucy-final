import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "agent" / "app"))

from agent_registry import AgentRegistry, normalize_table_name, DEFAULT_TABLE


class AgentRegistryTests(unittest.TestCase):
    def test_registry_memory_fallback(self):
        os.environ.pop("AZURE_STORAGE_CONNECTION_STRING", None)

        registry = AgentRegistry()

        self.assertTrue(registry.using_memory_fallback)
        self.assertIsNone(registry.get_agent_record("lucy", "persistent"))

        registry.upsert_agent_record(
            "lucy",
            "persistent",
            {
                "agent_name": "lucy",
                "agent_version": "1",
            },
        )

        record = registry.get_agent_record("lucy", "persistent")
        self.assertEqual(record["agent_name"], "lucy")
        self.assertEqual(record["agent_version"], "1")

    def test_normalize_table_name_defaults(self):
        self.assertEqual(normalize_table_name(None), DEFAULT_TABLE)
        self.assertEqual(normalize_table_name(""), DEFAULT_TABLE)

    def test_normalize_table_name_sanitizes_invalid(self):
        self.assertEqual(normalize_table_name("agent_registry"), DEFAULT_TABLE)
        self.assertEqual(normalize_table_name("1_bad__name"), "t1badname")

    def test_normalize_table_name_requires_min_length(self):
        self.assertEqual(normalize_table_name("ab"), DEFAULT_TABLE)


if __name__ == "__main__":
    unittest.main()
