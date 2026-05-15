import importlib
import json
import os
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
    chainlit.CustomElement = lambda *args, **kwargs: object()
    chainlit.Message = lambda *args, **kwargs: types.SimpleNamespace(
        send=lambda: None,
        update=lambda: None,
        elements=[],
    )
    chainlit.user_session = types.SimpleNamespace(get=lambda *a, **k: None, set=lambda *a, **k: None)
    sys.modules.setdefault("chainlit", chainlit)

    dotenv = types.ModuleType("dotenv")
    dotenv.load_dotenv = lambda *args, **kwargs: None
    sys.modules.setdefault("dotenv", dotenv)


def _install_search_stubs(generic_result):
    azure_search = types.ModuleType("azure.search")
    azure_search_documents = types.ModuleType("azure.search.documents")
    azure_core = types.ModuleType("azure.core")
    azure_core_credentials = types.ModuleType("azure.core.credentials")
    azure_core_exceptions = types.ModuleType("azure.core.exceptions")
    azure_identity = types.ModuleType("azure.identity")

    class FakeSearchClient:
        def __init__(self, *args, **kwargs):
            pass

        def search(self, **kwargs):
            text = kwargs.get("search_text", "")
            if "generic-notices" in text or "Acme Wage Case" in text:
                return [generic_result]
            return []

    azure_search_documents.SearchClient = FakeSearchClient
    azure_core_credentials.AzureKeyCredential = lambda key: ("key", key)
    azure_core_exceptions.HttpResponseError = RuntimeError
    azure_identity.DefaultAzureCredential = object

    sys.modules["azure.search"] = azure_search
    sys.modules["azure.search.documents"] = azure_search_documents
    sys.modules["azure.core"] = azure_core
    sys.modules["azure.core.credentials"] = azure_core_credentials
    sys.modules["azure.core.exceptions"] = azure_core_exceptions
    sys.modules["azure.identity"] = azure_identity


def _load_user_functions():
    _install_import_stubs()
    sys.modules.pop("user_functions", None)
    return importlib.import_module("user_functions")


class GenericNoticeFallbackTests(unittest.TestCase):
    def test_member_context_uses_approved_labels(self):
        user_functions = _load_user_functions()
        context = user_functions.build_generic_notice_member_context(
            {
                "new_estimatedsettlementamount": 1234.5,
                "new_classworkweeks": 12,
                "cr7fe_classcountmetric": "weeks",
                "new_middlename": "not approved",
            }
        )

        self.assertIn("Estimated settlement amount: $1,234.50", context)
        self.assertIn("Class count: 12", context)
        self.assertNotIn("Class count metric", context)
        self.assertNotIn("not approved", context)

    def test_member_record_select_is_filtered_to_live_d365_fields(self):
        user_functions = _load_user_functions()
        captured = {}

        def fake_query(entity, filter_str=None, select=None):
            captured["entity"] = entity
            captured["filter"] = filter_str
            captured["select"] = select
            return json.dumps([
                {
                    "new_classmemberid": "member-id",
                    "_new_case_value": "case-id",
                    "new_apexid": "AALG003",
                    "new_estimatedsettlementamount": 12.34,
                }
            ])

        live_fields = {
            "new_classmemberid",
            "new_apexid",
            "new_fullname",
            "new_firstname",
            "new_lastname",
            "new_shortsocial",
            "new_estimatedsettlementamount",
            "new_classworkweeks",
            "new_pagaweeks",
        }

        with patch.object(user_functions, "DYNAMICS_ENABLED", True), patch.object(
            user_functions, "_get_entity_fields_cached", return_value=live_fields
        ), patch.object(user_functions, "query_entity_sync", side_effect=fake_query):
            record = user_functions._fetch_generic_notice_member_record("aalg003")

        self.assertEqual(record["new_classmemberid"], "member-id")
        self.assertNotIn("cr7fe_classcountmetric", captured["select"])
        self.assertNotIn("cr7fe_pagacountmetric", captured["select"])
        self.assertIn("_new_case_value", captured["select"])
        self.assertIn("new_estimatedsettlementamount", captured["select"])

    def test_member_notice_full_blob_url_keeps_source_container(self):
        user_functions = _load_user_functions()
        member_result = {
            "chunk": "A123 is printed on this individualized notice.",
            "metadata_storage_name": "A123.pdf",
            "metadata_storage_path": "https://acct.blob.core.windows.net/lucycmnotices/A123.pdf",
            "metadata_storage_file_extension": ".pdf",
            "file_extension": ".pdf",
        }

        azure_search = types.ModuleType("azure.search")
        azure_search_documents = types.ModuleType("azure.search.documents")
        azure_core = types.ModuleType("azure.core")
        azure_core_credentials = types.ModuleType("azure.core.credentials")
        azure_core_exceptions = types.ModuleType("azure.core.exceptions")
        azure_identity = types.ModuleType("azure.identity")

        class FakeSearchClient:
            def __init__(self, *args, **kwargs):
                pass

            def search(self, **kwargs):
                text = kwargs.get("search_text", "")
                if "A123" in text:
                    return [member_result]
                return []

        azure_search_documents.SearchClient = FakeSearchClient
        azure_core_credentials.AzureKeyCredential = lambda key: ("key", key)
        azure_core_exceptions.HttpResponseError = RuntimeError
        azure_identity.DefaultAzureCredential = object

        sys.modules["azure.search"] = azure_search
        sys.modules["azure.search.documents"] = azure_search_documents
        sys.modules["azure.core"] = azure_core
        sys.modules["azure.core.credentials"] = azure_core_credentials
        sys.modules["azure.core.exceptions"] = azure_core_exceptions
        sys.modules["azure.identity"] = azure_identity

        captured = {}

        def fake_generate_sas_url(blob_url):
            captured["blob_url"] = blob_url
            return "https://sas.example/member.pdf?sig=1"

        env = {
            "AZURE_SEARCH_ENDPOINT": "https://search.example.net",
            "AZURE_SEARCH_API_KEY": "test",
            "AZURE_SEARCH_INDEX_NAME": "lucy-notices-v2",
            "AZURE_STORAGE_ACCOUNT_NAME": "acct",
            "AZURE_STORAGE_CONTAINER_NAME": "lucyrag",
        }

        with patch.dict(os.environ, env, clear=False), patch.object(
            user_functions, "generate_sas_url", side_effect=fake_generate_sas_url
        ):
            output = user_functions.find_notice_for_user_sync("A123")

        self.assertEqual(
            captured["blob_url"],
            "https://acct.blob.core.windows.net/lucycmnotices/A123.pdf",
        )
        self.assertIn("I've found your notice", output)

    def test_notice_lookup_falls_back_to_generic_case_notice(self):
        user_functions = _load_user_functions()
        generic_result = {
            "chunk": "This generic notice explains the Acme settlement.",
            "metadata_storage_name": "Acme Notice Packet.pdf",
            "metadata_storage_path": (
                "https://acct.blob.core.windows.net/lucycmnotices/"
                "generic-notices/acme-wage-case--1234abcd--Acme%20Notice%20Packet.pdf"
            ),
            "metadata_storage_file_extension": ".pdf",
            "file_extension": ".pdf",
        }
        _install_search_stubs(generic_result)

        member_record = {
            "_new_case_value": "case-guid",
            "new_estimatedsettlementamount": 99.25,
            "new_classworkweeks": 3,
            "cr7fe_classcountmetric": "work weeks",
        }

        env = {
            "AZURE_SEARCH_ENDPOINT": "https://search.example.net",
            "AZURE_SEARCH_API_KEY": "test",
            "AZURE_SEARCH_INDEX_NAME": "lucy-notices-v2",
            "AZURE_STORAGE_ACCOUNT_NAME": "acct",
            "AZURE_STORAGE_CONTAINER_NAME": "lucyrag",
            "AZURE_GENERIC_NOTICE_CONTAINER": "lucycmnotices",
        }
        sas_mock = patch.object(
            user_functions, "generate_sas_url", return_value="https://sas.example/notice.pdf?sig=1"
        )
        with patch.dict(os.environ, env, clear=False), patch.object(
            user_functions, "_fetch_generic_notice_member_record", return_value=member_record
        ), patch.object(
            user_functions, "_fetch_case_title_for_member", return_value="Acme Wage Case"
        ), patch.object(
            user_functions,
            "get_case_notice",
            return_value={
                "case_id": "case-guid",
                "case_title": "Acme Wage Case",
                "source_region": "westus",
                "container": "lucycmnotices",
                "blob_name": "generic-notices/acme-wage-case--1234abcd--Acme Notice Packet.pdf",
                "display_name": "Acme Notice Packet.pdf",
                "blob_url": (
                    "https://acct.blob.core.windows.net/lucycmnotices/"
                    "generic-notices/acme-wage-case--1234abcd--Acme Notice Packet.pdf"
                ),
            },
        ), sas_mock as generate_sas:
            output = user_functions.find_notice_for_user_sync("A123")

        self.assertIn("generic notice packet", output)
        self.assertIn("NOTICE_SOURCE_TYPE:** generic_notice_fallback", output)
        self.assertIn("Estimated settlement amount: $99.25", output)
        self.assertIn("PDF_DISPLAY_INFO", output)
        self.assertIn("DISPLAY_MODE: side", output)
        self.assertEqual(
            generate_sas.call_args.args[0],
            "https://acct.blob.core.windows.net/lucycmnotices/generic-notices/acme-wage-case--1234abcd--Acme Notice Packet.pdf",
        )

    def test_get_case_notice_lists_existing_west_blob_path(self):
        user_functions = _load_user_functions()

        class FakeContainer:
            def list_blobs(self, *, name_starts_with, include=None):
                self.prefix = name_starts_with
                return [
                    types.SimpleNamespace(
                        name="generic-notices/acme-wage-case--11111111--Acme Wage Case - Draft.pdf",
                        metadata={"case_slug": "acme-wage-case"},
                    ),
                    types.SimpleNamespace(
                        name="generic-notices/acme-wage-case--11111111--Acme Wage Case - Notice Packet.pdf",
                        metadata={
                            "case_slug": "acme-wage-case",
                            "original_file_name": "Acme Wage Case - Notice Packet.pdf",
                        },
                    ),
                ]

        class FakeBlobService:
            container = FakeContainer()

            @classmethod
            def from_connection_string(cls, connection_string):
                cls.connection_string = connection_string
                return cls()

            def get_container_client(self, container_name):
                self.container_name = container_name
                return self.container

        env = {
            "AZURE_STORAGE_ACCOUNT_NAME": "aiagentlucyapex01",
            "AZURE_STORAGE_CONNECTION_STRING": "UseDevelopmentStorage=true",
            "AZURE_GENERIC_NOTICE_CONTAINER": "lucycmnotices",
            "GENERIC_NOTICE_BLOB_PREFIX": "generic-notices",
        }
        with patch.dict(os.environ, env, clear=False), patch.object(
            user_functions, "BlobServiceClient", FakeBlobService
        ):
            notice = user_functions.get_case_notice("case-guid", "Acme Wage Case")

        self.assertEqual(
            notice["blob_name"],
            "generic-notices/acme-wage-case--11111111--Acme Wage Case - Notice Packet.pdf",
        )
        self.assertEqual(FakeBlobService.container.prefix, "generic-notices/")
        self.assertEqual(notice["display_name"], "Acme Wage Case - Notice Packet.pdf")
        self.assertEqual(notice["source_region"], "westus")
        self.assertEqual(
            notice["blob_url"],
            "https://aiagentlucyapex01.blob.core.windows.net/lucycmnotices/generic-notices/acme-wage-case--11111111--Acme Wage Case - Notice Packet.pdf",
        )
        self.assertEqual(notice["case_slug"], "acme-wage-case")
        self.assertEqual(notice["case_key"], "")
        self.assertEqual(notice["case_lookup_key"], "acme-wage-case")

    def test_get_case_notice_tries_defendant_slug_from_versus_title(self):
        user_functions = _load_user_functions()

        class FakeContainer:
            prefixes = []

            def list_blobs(self, *, name_starts_with, include=None):
                self.prefixes.append(name_starts_with)
                return [
                    types.SimpleNamespace(
                        name="generic-notices/unrelated-case--00000000--Other Notice Packet.pdf"
                    ),
                    types.SimpleNamespace(
                        name="generic-notices/acme-wage-case--22222222--Acme Notice Packet.pdf"
                    ),
                ]

        class FakeBlobService:
            container = FakeContainer()

            @classmethod
            def from_connection_string(cls, connection_string):
                return cls()

            def get_container_client(self, container_name):
                return self.container

        env = {
            "AZURE_STORAGE_ACCOUNT_NAME": "acct",
            "AZURE_STORAGE_CONNECTION_STRING": "UseDevelopmentStorage=true",
            "AZURE_GENERIC_NOTICE_CONTAINER": "lucycmnotices",
            "GENERIC_NOTICE_BLOB_PREFIX": "generic-notices",
        }
        with patch.dict(os.environ, env, clear=False), patch.object(
            user_functions, "BlobServiceClient", FakeBlobService
        ):
            notice = user_functions.get_case_notice("case-guid", "Smith v. Acme Wage Case")

        self.assertEqual(FakeBlobService.container.prefixes, ["generic-notices/"])
        self.assertEqual(
            notice["blob_name"],
            "generic-notices/acme-wage-case--22222222--Acme Notice Packet.pdf",
        )

    def test_get_case_notice_keeps_legacy_nested_blob_compatibility(self):
        user_functions = _load_user_functions()

        class FakeContainer:
            def list_blobs(self, *, name_starts_with, include=None):
                self.prefix = name_starts_with
                return [
                    types.SimpleNamespace(
                        name="generic-notices/acme-wage-case/Acme Notice Packet.pdf"
                    )
                ]

        class FakeBlobService:
            container = FakeContainer()

            @classmethod
            def from_connection_string(cls, connection_string):
                return cls()

            def get_container_client(self, container_name):
                return self.container

        env = {
            "AZURE_STORAGE_ACCOUNT_NAME": "acct",
            "AZURE_STORAGE_CONNECTION_STRING": "UseDevelopmentStorage=true",
            "AZURE_GENERIC_NOTICE_CONTAINER": "lucycmnotices",
            "GENERIC_NOTICE_BLOB_PREFIX": "generic-notices",
        }
        with patch.dict(os.environ, env, clear=False), patch.object(
            user_functions, "BlobServiceClient", FakeBlobService
        ):
            notice = user_functions.get_case_notice("case-guid", "Smith v. Acme Wage Case")

        self.assertEqual(FakeBlobService.container.prefix, "generic-notices/")
        self.assertEqual(
            notice["blob_name"],
            "generic-notices/acme-wage-case/Acme Notice Packet.pdf",
        )

    def test_get_case_notice_tries_short_ampersand_alias(self):
        user_functions = _load_user_functions()

        class FakeContainer:
            prefixes = []

            def list_blobs(self, *, name_starts_with, include=None):
                self.prefixes.append(name_starts_with)
                return [
                    types.SimpleNamespace(
                        name="generic-notices/allergy-and-asthma--33333333--Allergy - Notice v2.pdf"
                    )
                ]

        class FakeBlobService:
            container = FakeContainer()

            @classmethod
            def from_connection_string(cls, connection_string):
                return cls()

            def get_container_client(self, container_name):
                return self.container

        env = {
            "AZURE_STORAGE_ACCOUNT_NAME": "acct",
            "AZURE_STORAGE_CONNECTION_STRING": "UseDevelopmentStorage=true",
            "AZURE_GENERIC_NOTICE_CONTAINER": "lucycmnotices",
            "GENERIC_NOTICE_BLOB_PREFIX": "generic-notices",
        }
        title = "Paris v. Allergy & Asthma Medical Group of the Bay Area, Inc."
        with patch.dict(os.environ, env, clear=False), patch.object(
            user_functions, "BlobServiceClient", FakeBlobService
        ):
            notice = user_functions.get_case_notice("case-guid", title)

        self.assertEqual(FakeBlobService.container.prefixes, ["generic-notices/"])
        self.assertEqual(
            notice["blob_name"],
            "generic-notices/allergy-and-asthma--33333333--Allergy - Notice v2.pdf",
        )

    def test_get_case_notice_prefers_canonical_generic_notice_blob(self):
        user_functions = _load_user_functions()

        class FakeContainer:
            prefixes = []

            def list_blobs(self, *, name_starts_with, include=None):
                self.prefixes.append(name_starts_with)
                return [
                    types.SimpleNamespace(
                        name="generic-notices/allergy-and-asthma/Allergy - Notice v2.pdf"
                    ),
                    types.SimpleNamespace(
                        name="generic-notices/allergy-and-asthma--44444444--generic-notice.pdf",
                        metadata={
                            "case_slug": "allergy-and-asthma",
                            "original_file_name": "Allergy - Notice v2.pdf",
                        },
                    ),
                ]

        class FakeBlobService:
            container = FakeContainer()

            @classmethod
            def from_connection_string(cls, connection_string):
                return cls()

            def get_container_client(self, container_name):
                return self.container

        env = {
            "AZURE_STORAGE_ACCOUNT_NAME": "acct",
            "AZURE_STORAGE_CONNECTION_STRING": "UseDevelopmentStorage=true",
            "AZURE_GENERIC_NOTICE_CONTAINER": "lucycmnotices",
            "GENERIC_NOTICE_BLOB_PREFIX": "generic-notices",
        }
        with patch.dict(os.environ, env, clear=False), patch.object(
            user_functions, "BlobServiceClient", FakeBlobService
        ):
            notice = user_functions.get_case_notice("case-guid", "Paris v. Allergy & Asthma")

        self.assertEqual(FakeBlobService.container.prefixes, ["generic-notices/"])
        self.assertEqual(
            notice["blob_name"],
            "generic-notices/allergy-and-asthma--44444444--generic-notice.pdf",
        )
        self.assertEqual(notice["display_name"], "Allergy - Notice v2.pdf")
        self.assertEqual(notice["case_slug"], "allergy-and-asthma")
        self.assertEqual(notice["case_key"], "44444444")
        self.assertEqual(notice["case_lookup_key"], "allergy-and-asthma--44444444")

    def test_get_case_notice_prefers_clean_template_over_member_named_flat_blob(self):
        user_functions = _load_user_functions()

        class FakeContainer:
            prefixes = []

            def list_blobs(self, *, name_starts_with, include=None):
                self.prefixes.append(name_starts_with)
                return [
                    types.SimpleNamespace(
                        name=(
                            "generic-notices/allergy-and-asthma--26289d92--"
                            "Allergy - Notice - Anissa Coleman.pdf"
                        ),
                        metadata={"case_slug": "allergy-and-asthma"},
                    ),
                    types.SimpleNamespace(
                        name="generic-notices/allergy-and-asthma/Allergy - Notice v2.pdf"
                    ),
                ]

        class FakeBlobService:
            container = FakeContainer()

            @classmethod
            def from_connection_string(cls, connection_string):
                return cls()

            def get_container_client(self, container_name):
                return self.container

        env = {
            "AZURE_STORAGE_ACCOUNT_NAME": "acct",
            "AZURE_STORAGE_CONNECTION_STRING": "UseDevelopmentStorage=true",
            "AZURE_GENERIC_NOTICE_CONTAINER": "lucycmnotices",
            "GENERIC_NOTICE_BLOB_PREFIX": "generic-notices",
        }
        title = "Paris v. Allergy & Asthma Medical Group of the Bay Area, Inc."
        with patch.dict(os.environ, env, clear=False), patch.object(
            user_functions, "BlobServiceClient", FakeBlobService
        ):
            notice = user_functions.get_case_notice("case-guid", title)

        self.assertEqual(FakeBlobService.container.prefixes, ["generic-notices/"])
        self.assertEqual(
            notice["blob_name"],
            "generic-notices/allergy-and-asthma/Allergy - Notice v2.pdf",
        )

    def test_get_case_notice_excludes_canonical_blob_with_member_source_metadata(self):
        user_functions = _load_user_functions()

        class FakeContainer:
            prefixes = []

            def list_blobs(self, *, name_starts_with, include=None):
                self.prefixes.append(name_starts_with)
                return [
                    types.SimpleNamespace(
                        name="generic-notices/acme-wage-case--11111111--generic-notice.pdf",
                        metadata={
                            "case_slug": "acme-wage-case",
                            "source_file_name": "Jonathan A Aguayo - Notice Packet.pdf",
                        },
                    )
                ]

        class FakeBlobService:
            container = FakeContainer()

            @classmethod
            def from_connection_string(cls, connection_string):
                return cls()

            def get_container_client(self, container_name):
                return self.container

        env = {
            "AZURE_STORAGE_ACCOUNT_NAME": "acct",
            "AZURE_STORAGE_CONNECTION_STRING": "UseDevelopmentStorage=true",
            "AZURE_GENERIC_NOTICE_CONTAINER": "lucycmnotices",
            "GENERIC_NOTICE_BLOB_PREFIX": "generic-notices",
        }
        with patch.dict(os.environ, env, clear=False), patch.object(
            user_functions, "BlobServiceClient", FakeBlobService
        ):
            notice = user_functions.get_case_notice("case-guid", "Acme Wage Case")

        self.assertEqual(FakeBlobService.container.prefixes, ["generic-notices/"])
        self.assertIsNone(notice)

    def test_notice_lookup_does_not_use_unrelated_generic_search_result_without_case_blob(self):
        user_functions = _load_user_functions()
        unrelated_result = {
            "chunk": "This is a different case notice.",
            "metadata_storage_name": "Other Notice Packet.pdf",
            "metadata_storage_path": (
                "https://acct.blob.core.windows.net/lucycmnotices/"
                "generic-notices/other-case/Other Notice Packet.pdf"
            ),
            "metadata_storage_file_extension": ".pdf",
            "file_extension": ".pdf",
        }
        _install_search_stubs(unrelated_result)

        member_record = {
            "_new_case_value": "case-guid",
            "new_estimatedsettlementamount": 99.25,
        }
        env = {
            "AZURE_SEARCH_ENDPOINT": "https://search.example.net",
            "AZURE_SEARCH_API_KEY": "test",
            "AZURE_SEARCH_INDEX_NAME": "lucy-notices-v2",
            "AZURE_STORAGE_ACCOUNT_NAME": "acct",
            "AZURE_STORAGE_CONTAINER_NAME": "lucyrag",
            "AZURE_GENERIC_NOTICE_CONTAINER": "lucycmnotices",
        }
        with patch.dict(os.environ, env, clear=False), patch.object(
            user_functions, "_fetch_generic_notice_member_record", return_value=member_record
        ), patch.object(
            user_functions, "_fetch_case_title_for_member", return_value="Acme Wage Case"
        ), patch.object(
            user_functions, "get_case_notice", return_value=None
        ), patch.object(
            user_functions, "generate_sas_url", return_value="https://sas.example/notice.pdf?sig=1"
        ) as generate_sas:
            output = user_functions.find_notice_for_user_sync("A123")

        self.assertIn("I checked both required notice paths", output)
        self.assertIn("NOTICE_SOURCE_TYPE:** notice_unavailable_after_generic_fallback", output)
        self.assertIn("NOTICE_LOOKUP_STATUS:** no_pdf_after_individualized_and_generic", output)
        self.assertIn("Use the authenticated Dynamics member/case record", output)
        self.assertNotIn("check back in about two weeks", output)
        generate_sas.assert_not_called()


if __name__ == "__main__":
    unittest.main()
