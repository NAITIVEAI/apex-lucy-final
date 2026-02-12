import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "agent" / "app"))

from foundry_v2 import normalize_query_type, build_ai_search_tool, AZURE_PROJECTS_AVAILABLE


class FoundryV2ToolTests(unittest.TestCase):
    def test_normalize_query_type_default(self):
        self.assertEqual(normalize_query_type(None), "vector_semantic_hybrid")
        self.assertEqual(normalize_query_type("SEMANTIC"), "semantic")

    def test_build_ai_search_tool_requires_azure(self):
        if AZURE_PROJECTS_AVAILABLE:
            self.skipTest("Azure AI Projects SDK available locally")
        with self.assertRaises(RuntimeError):
            build_ai_search_tool(
                connection_id="/subscriptions/abc/resourceGroups/rg/providers/Microsoft.CognitiveServices/accounts/foundry/projects/prj/connections/conn",
                index_name="lucy-notices-v2",
                query_type="vector_semantic_hybrid",
            )


if __name__ == "__main__":
    unittest.main()
