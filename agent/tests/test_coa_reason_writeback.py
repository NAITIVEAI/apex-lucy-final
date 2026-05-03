import importlib
import json
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch


APP_DIR = Path(__file__).resolve().parents[1] / "app"


def _install_import_stubs() -> None:
    sys.path.insert(0, str(APP_DIR))

    azure = types.ModuleType("azure")
    azure_storage = types.ModuleType("azure.storage")
    azure_blob = types.ModuleType("azure.storage.blob")
    azure_blob.BlobServiceClient = object
    azure_blob.BlobSasPermissions = object
    azure_blob.generate_blob_sas = lambda *args, **kwargs: "sas"
    azure_blob.BlobClient = object
    sys.modules.setdefault("azure", azure)
    sys.modules.setdefault("azure.storage", azure_storage)
    sys.modules.setdefault("azure.storage.blob", azure_blob)

    chainlit = types.ModuleType("chainlit")
    chainlit.user_session = types.SimpleNamespace(get=lambda *a, **k: None, set=lambda *a, **k: None)
    chainlit.Message = object
    sys.modules.setdefault("chainlit", chainlit)

    dotenv = types.ModuleType("dotenv")
    dotenv.load_dotenv = lambda *args, **kwargs: None
    sys.modules.setdefault("dotenv", dotenv)


def _load_user_functions():
    _install_import_stubs()
    sys.modules.pop("user_functions", None)
    return importlib.import_module("user_functions")


class CoaReasonWritebackTests(unittest.TestCase):
    def setUp(self):
        self.user_functions = _load_user_functions()
        self.user_functions._ENTITY_FIELDS_CACHE.clear()

    def _seed_metadata(self, *attributes):
        self.user_functions._ENTITY_FIELDS_CACHE["new_classmembers"] = {
            "ts": 9999999999,
            "fields": {attr["LogicalName"] for attr in attributes},
            "attributes": list(attributes),
        }

    def test_choice_coa_reason_field_is_added_to_member_address_update(self):
        self._seed_metadata(
            {"LogicalName": "new_address", "AttributeType": "String"},
            {"LogicalName": "new_city", "AttributeType": "String"},
            {
                "LogicalName": "new_coareason",
                "AttributeType": "Picklist",
                "OptionSet": {
                    "Options": [
                        {"Value": 100000001, "Label": {"UserLocalizedLabel": {"Label": "COA via Email"}}},
                        {"Value": 100000005, "Label": {"UserLocalizedLabel": {"Label": "COA via Lucy"}}},
                    ]
                },
            },
        )

        captured_updates = {}

        def fake_query(entity, filter_str=None, select=None):
            if select == "new_classmemberid,new_apexid":
                return json.dumps([{"new_classmemberid": "member-guid", "new_apexid": "A123"}])
            return json.dumps([{"new_address": "123 Main", "new_coareason": 100000005}])

        def fake_update(entity, entity_id, data):
            captured_updates.update(data)
            return "True"

        with patch.object(self.user_functions, "query_entity_sync", side_effect=fake_query), patch.object(
            self.user_functions, "update_entity_sync", side_effect=fake_update
        ):
            result = json.loads(
                self.user_functions.update_member_profile_sync(
                    "A123",
                    {"new_address": "123 Main", "new_city": "Los Angeles"},
                )
            )

        self.assertTrue(result["success"])
        self.assertEqual(captured_updates["new_address"], "123 Main")
        self.assertEqual(captured_updates["new_coareason"], 100000005)

    def test_text_coa_reason_field_uses_lucy_label(self):
        self._seed_metadata(
            {"LogicalName": "new_address", "AttributeType": "String"},
            {"LogicalName": "new_coareason", "AttributeType": "Memo"},
        )

        update, error = self.user_functions._build_coa_reason_update("new_classmembers")

        self.assertIsNone(error)
        self.assertEqual(update, {"new_coareason": "COA via Lucy"})

    def test_missing_coa_reason_schema_blocks_address_update(self):
        self._seed_metadata({"LogicalName": "new_address", "AttributeType": "String"})

        with patch.object(self.user_functions, "update_entity_sync") as update_entity:
            result = json.loads(
                self.user_functions.update_member_profile_sync(
                    "A123",
                    {"new_address": "123 Main"},
                )
            )

        self.assertFalse(result["success"])
        self.assertIn("No confirmed COA reason field", result["error"])
        update_entity.assert_not_called()

    def test_choice_coa_reason_schema_reads_option_metadata_when_not_cached(self):
        self._seed_metadata(
            {"LogicalName": "new_address", "AttributeType": "String"},
            {"LogicalName": "new_coareason", "AttributeType": "Picklist"},
        )
        choice_metadata = {
            "LogicalName": "new_coareason",
            "AttributeType": "Picklist",
            "OptionSet": {
                "Options": [
                    {"Value": 100000010, "Label": {"UserLocalizedLabel": {"Label": "COA via Call"}}},
                    {"Value": 100000011, "Label": {"UserLocalizedLabel": {"Label": "COA via Lucy"}}},
                ]
            },
        }

        with patch.object(self.user_functions, "_get_choice_attribute_metadata", return_value=choice_metadata):
            update, error = self.user_functions._build_coa_reason_update("new_classmembers")

        self.assertIsNone(error)
        self.assertEqual(update, {"new_coareason": 100000011})

    def test_metadata_lookup_uses_classmember_logical_name(self):
        calls = []

        def fake_metadata(entity):
            calls.append(entity)
            return {"value": [{"LogicalName": "new_address", "AttributeType": "String"}]}

        with patch.object(self.user_functions, "get_entity_metadata", side_effect=fake_metadata):
            self.user_functions._ENTITY_FIELDS_CACHE.clear()
            fields = self.user_functions._get_entity_fields_cached("new_classmembers")

        self.assertIn("new_address", fields)
        self.assertEqual(calls, ["new_classmember"])

    def test_choice_coa_reason_schema_blocks_without_lucy_option(self):
        self._seed_metadata(
            {"LogicalName": "new_address", "AttributeType": "String"},
            {"LogicalName": "new_coareason", "AttributeType": "Picklist"},
        )

        with patch.object(self.user_functions, "_get_choice_attribute_metadata", return_value={}):
            update, error = self.user_functions._build_coa_reason_update("new_classmembers")

        self.assertEqual(update, {})
        self.assertIn("COA via Lucy", error)


if __name__ == "__main__":
    unittest.main()
