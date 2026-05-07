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
        self.assertIn("Class count metric: weeks", context)
        self.assertNotIn("not approved", context)

    def test_notice_lookup_falls_back_to_generic_case_notice(self):
        user_functions = _load_user_functions()
        generic_result = {
            "chunk": "This generic notice explains the Acme settlement.",
            "metadata_storage_name": "Acme Notice Packet.pdf",
            "metadata_storage_path": (
                "https://acct.blob.core.windows.net/lucycmnotices/"
                "generic-notices/acme-wage-case/Acme Notice Packet.pdf"
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
            "AZURE_STORAGE_CONTAINER_NAME": "lucycmnotices",
        }
        with patch.dict(os.environ, env, clear=False), patch.object(
            user_functions, "_fetch_generic_notice_member_record", return_value=member_record
        ), patch.object(
            user_functions, "_fetch_case_title_for_member", return_value="Acme Wage Case"
        ), patch.object(
            user_functions, "generate_sas_url", return_value="https://sas.example/notice.pdf?sig=1"
        ):
            output = user_functions.find_notice_for_user_sync("A123")

        self.assertIn("generic notice packet", output)
        self.assertIn("NOTICE_SOURCE_TYPE:** generic_notice_fallback", output)
        self.assertIn("Estimated settlement amount: $99.25", output)
        self.assertIn("PDF_DISPLAY_INFO", output)
        self.assertIn("DISPLAY_MODE: side", output)


if __name__ == "__main__":
    unittest.main()
