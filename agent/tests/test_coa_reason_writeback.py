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

    def test_dynamics_tool_registry_exposes_case_followup_tools(self):
        with patch.object(self.user_functions, "DYNAMICS_ENABLED", True):
            names = {fn.__name__ for fn in self.user_functions.setup_dynamics_functions()}

        self.assertIn("get_class_member_details_sync", names)
        self.assertIn("get_member_disbursements_sync", names)
        self.assertIn("update_member_profile_fields_sync", names)
        self.assertIn("find_notice_for_user_sync", names)
        self.assertNotIn("query_entity_sync", names)
        self.assertNotIn("update_entity_sync", names)
        self.assertNotIn("discover_entity_fields_sync", names)
        self.assertNotIn("smart_query_entity_sync", names)
        self.assertNotIn("reissue_check_sync", names)
        self.assertNotIn("update_reissue_check_requested_sync", names)

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

    def test_legacy_address_aliases_are_preserved_under_lucy_policy(self):
        self._seed_metadata(
            {"LogicalName": "new_address", "AttributeType": "String"},
            {"LogicalName": "new_state", "AttributeType": "String"},
            {"LogicalName": "new_zip", "AttributeType": "String"},
            {
                "LogicalName": "new_coareason",
                "AttributeType": "Picklist",
                "OptionSet": {
                    "Options": [
                        {"Value": 100000005, "Label": {"UserLocalizedLabel": {"Label": "COA via Lucy"}}},
                    ]
                },
            },
        )

        captured_updates = {}

        def fake_query(entity, filter_str=None, select=None):
            if select == "new_classmemberid,new_apexid":
                return json.dumps([{"new_classmemberid": "member-guid", "new_apexid": "A123"}])
            return json.dumps([
                {
                    "new_address": "123 Main",
                    "new_state": "CA",
                    "new_zip": "90001",
                    "new_coareason": 100000005,
                }
            ])

        def fake_update(entity, entity_id, data):
            captured_updates.update(data)
            return "True"

        with patch.object(self.user_functions, "query_entity_sync", side_effect=fake_query), patch.object(
            self.user_functions, "update_entity_sync", side_effect=fake_update
        ):
            result = json.loads(
                self.user_functions.update_member_profile_sync(
                    "A123",
                    {
                        "new_address1": "123 Main",
                        "new_stateorprovince": "CA",
                        "new_postalcode": "90001",
                    },
                )
            )

        self.assertTrue(result["success"])
        self.assertEqual(captured_updates["new_address"], "123 Main")
        self.assertEqual(captured_updates["new_state"], "CA")
        self.assertEqual(captured_updates["new_zip"], "90001")
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

    def test_get_class_member_details_uses_lucy_manifest_select(self):
        captured = {}

        def fake_query(entity, filter_str=None, select=None):
            captured["entity"] = entity
            captured["filter"] = filter_str
            captured["select"] = select
            return json.dumps([
                {
                    "new_classmemberid": "member-guid",
                    "new_apexid": "A123",
                    "new_firstname": "Ada",
                    "new_middlename": "Not Approved",
                    "new_estimatedsettlementamount": 100,
                }
            ])

        with patch.object(self.user_functions, "query_entity_sync", side_effect=fake_query):
            result = json.loads(self.user_functions.get_class_member_details_sync("A123", "settlement"))

        self.assertTrue(result["success"])
        self.assertEqual(captured["entity"], "new_classmembers")
        self.assertIn("new_estimatedsettlementamount", captured["select"])
        self.assertIn("cr7fe_classcountmetric", captured["select"])
        self.assertNotIn("new_middlename", captured["select"])
        self.assertNotIn("new_middlename", json.dumps(result))

    def test_member_disbursement_select_is_restricted_to_lucy_manifest(self):
        calls = []

        def fake_query(entity, filter_str=None, select=None):
            calls.append((entity, select))
            if entity == "new_classmembers":
                return json.dumps([{"new_classmemberid": "member-guid", "new_apexid": "A123"}])
            return json.dumps([
                {
                    "new_memberdisbursementid": "disb-guid",
                    "new_checkamount": 25,
                    "new_checkreissuerequest": True,
                }
            ])

        with patch.object(self.user_functions, "query_entity_sync", side_effect=fake_query):
            result = json.loads(
                self.user_functions.get_member_disbursements_sync(
                    "A123",
                    select_fields="new_checkamount,new_checkreissuerequest,new_name",
                )
            )

        self.assertTrue(result["success"])
        self.assertEqual(calls[1][0], "new_memberdisbursements")
        self.assertIn("new_checkamount", calls[1][1])
        self.assertNotIn("new_checkreissuerequest", calls[1][1])
        self.assertNotIn("new_name", calls[1][1])
        self.assertNotIn("new_checkreissuerequest", json.dumps(result))

    def test_generic_notice_member_context_uses_safe_labels(self):
        context = self.user_functions.build_generic_notice_member_context(
            {
                "new_estimatedsettlementamount": 100,
                "new_classworkweeks": 12,
                "cr7fe_classcountmetric": "Workweeks",
                "new_pagaweeks": 4,
                "cr7fe_pagacountmetric": "PAGA weeks",
                "new_potentialclassmemberstatus": "Eligible",
            }
        )

        self.assertIn("Estimated settlement amount: $100.00", context)
        self.assertIn("Class count: 12", context)
        self.assertIn("PAGA count: 4", context)
        self.assertIn("Member status: Eligible", context)
        self.assertNotIn("new_estimatedsettlementamount", context)
        self.assertNotIn("cr7fe_classcountmetric", context)

    def test_generic_notice_candidate_prefers_notice_packet_container_path(self):
        preferred = {
            "metadata_storage_path": (
                "https://acct.blob.core.windows.net/lucygenericnotices/"
                "Smith Settlement/Print/Notice packet/Long Form Notice.pdf"
            ),
            "metadata_storage_name": "Long Form Notice.pdf",
        }
        other = {
            "metadata_storage_path": "https://acct.blob.core.windows.net/lucycmnotices/A123.pdf",
            "metadata_storage_name": "A123.pdf",
        }

        self.assertGreater(
            self.user_functions._generic_notice_candidate_score(preferred, "Smith Settlement"),
            self.user_functions._generic_notice_candidate_score(other, "Smith Settlement"),
        )


if __name__ == "__main__":
    unittest.main()
