import io
import json
import sys
import unittest
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from case_documents_sync.sync import (
    CaseDocumentsListingError,
    SyncConfig,
    blob_content_type,
    build_case_documents_path,
    build_destination_blob_name,
    get_drive_id,
    is_eligible_case_document,
    is_mirror_blob,
    item_fingerprint,
    list_case_documents,
    normalize_drive_relative_path,
    prune_stale_case_document_blobs,
    should_upload,
    sync_case_documents,
)


def file_item(name, item_id="item-1", size=100, etag="e1"):
    return {
        "id": item_id,
        "name": name,
        "size": size,
        "eTag": etag,
        "cTag": f"c-{etag}",
        "lastModifiedDateTime": "2026-08-01T00:00:00Z",
        "file": {"hashes": {"quickXorHash": f"x-{etag}"}},
    }


class FakeGraph:
    def __init__(self, *, children_by_url=None, fail_download=False, error_status_by_url=None):
        self.children_by_url = children_by_url or {}
        self.downloaded = []
        self.fail_download = fail_download
        self.error_status_by_url = error_status_by_url or {}

    def get_json(self, url):
        if "/sites/" in url and ":/sites/" in url:
            return {"id": "site-1"}
        raise AssertionError(f"unexpected get_json url: {url}")

    def get_all(self, url):
        if url.endswith("/sites/site-1/drives"):
            return [{"id": "drive-1", "name": "Documents", "driveType": "documentLibrary"}]
        if url in self.error_status_by_url:
            response = requests.models.Response()
            response.status_code = self.error_status_by_url[url]
            raise requests.HTTPError(f"error {response.status_code}", response=response)
        if url in self.children_by_url:
            return self.children_by_url[url]
        response = requests.models.Response()
        response.status_code = 404
        raise requests.HTTPError("not found", response=response)

    def download_file(self, drive_id, item_id):
        self.downloaded.append((drive_id, item_id))
        if self.fail_download:
            response = requests.models.Response()
            response.status_code = 502
            raise requests.HTTPError("download failed", response=response)
        return b"%PDF case document"


class FakeBlob:
    def __init__(self):
        self.payload = None

    def download_blob(self):
        if self.payload is None:
            raise RuntimeError("missing")
        return self

    def readall(self):
        return self.payload


class FakeContainer:
    def __init__(self, ledger=None, blobs=None):
        self.created = False
        self.uploads = {}
        self.deleted = []
        self.blobs = list(blobs or [])
        self.ledger_blob = FakeBlob()
        if ledger is not None:
            self.ledger_blob.payload = json.dumps(ledger).encode("utf-8")

    def create_container(self):
        self.created = True

    def get_blob_client(self, name):
        self.requested_ledger_name = name
        return self.ledger_blob

    def upload_blob(self, name, data, overwrite=False, **kwargs):
        body = data.getvalue() if isinstance(data, io.BytesIO) else data
        self.uploads[name] = {"data": body, "overwrite": overwrite, "kwargs": kwargs}

    def list_blobs(self, name_starts_with=None):
        for name in self.blobs:
            if not name_starts_with or name.startswith(name_starts_with):
                yield {"name": name}

    def delete_blob(self, name):
        self.deleted.append(name)


class FakeBlobService:
    def __init__(self, container):
        self.container = container

    def get_container_client(self, name):
        self.requested_container = name
        return self.container


def children_url(path):
    from urllib.parse import quote

    return f"https://graph.microsoft.com/v1.0/drives/drive-1/root:/{quote(path, safe='/')}:/children"


CASE_ROOT = "Active Cases/Settlements"


class PathTests(unittest.TestCase):
    def test_normalize_strips_drive_alias(self):
        self.assertEqual(
            normalize_drive_relative_path("/Shared Documents/Active Cases/Settlements"),
            "Active Cases/Settlements",
        )

    def test_build_case_documents_path(self):
        config = SyncConfig()
        self.assertEqual(
            build_case_documents_path("7 Eleven", config),
            "Active Cases/Settlements/7 Eleven/Case Documents",
        )

    def test_destination_blob_name_is_verbatim(self):
        self.assertEqual(
            build_destination_blob_name("Soapy Joes Group Inc et al", "Class Notice.pdf"),
            "Soapy Joes Group Inc et al/Class Notice.pdf",
        )


class EligibilityTests(unittest.TestCase):
    def test_allows_court_document_types(self):
        self.assertTrue(is_eligible_case_document("Settlement Agreement.pdf"))
        self.assertTrue(is_eligible_case_document("Class Notice.docx"))
        self.assertTrue(is_eligible_case_document("PA Order.doc"))

    def test_rejects_other_extensions(self):
        self.assertFalse(is_eligible_case_document("calculations.xlsx"))
        self.assertFalse(is_eligible_case_document("member list.csv"))
        self.assertFalse(is_eligible_case_document("notes.txt"))

    def test_rejects_mail_merge_and_ssn_names(self):
        self.assertFalse(is_eligible_case_document("Notice mail merge.pdf"))
        self.assertFalse(is_eligible_case_document("Members with SSN.docx"))
        self.assertFalse(is_eligible_case_document("list for merge.pdf"))

    def test_content_types(self):
        self.assertEqual(blob_content_type("a.pdf"), "application/pdf")
        self.assertEqual(blob_content_type("a.doc"), "application/msword")
        self.assertEqual(
            blob_content_type("a.docx"),
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
        self.assertEqual(blob_content_type("a.bin"), "application/octet-stream")


class LedgerTests(unittest.TestCase):
    def test_should_upload_new_and_changed(self):
        item = file_item("Doc.pdf")
        self.assertTrue(should_upload(item, None))
        self.assertFalse(should_upload(item, {"source": item_fingerprint(item)}))
        changed = file_item("Doc.pdf", etag="e2")
        self.assertTrue(should_upload(changed, {"source": item_fingerprint(item)}))


class MirrorBlobTests(unittest.TestCase):
    def test_ledger_and_root_blobs_are_not_mirror_blobs(self):
        self.assertFalse(is_mirror_blob("_sync/case_documents_ledger.json"))
        self.assertFalse(is_mirror_blob("stray-root-file.pdf"))
        self.assertTrue(is_mirror_blob("7 Eleven/Class Notice.pdf"))

    def test_prune_deletes_only_stale_mirror_blobs(self):
        container = FakeContainer(
            blobs=[
                "7 Eleven/Old Name.pdf",
                "7 Eleven/Current.pdf",
                "_sync/case_documents_ledger.json",
            ]
        )
        files_ledger = {"7 Eleven/Old Name.pdf": {"source": {}}}
        deleted = prune_stale_case_document_blobs(
            container,
            active_blob_names={"7 Eleven/Current.pdf"},
            files_ledger=files_ledger,
            dry_run=False,
        )
        self.assertEqual(deleted, 1)
        self.assertEqual(container.deleted, ["7 Eleven/Old Name.pdf"])
        self.assertNotIn("7 Eleven/Old Name.pdf", files_ledger)

    def test_prune_noop_without_active_names(self):
        container = FakeContainer(blobs=["7 Eleven/Doc.pdf"])
        deleted = prune_stale_case_document_blobs(
            container, active_blob_names=set(), files_ledger={}, dry_run=False
        )
        self.assertEqual(deleted, 0)
        self.assertEqual(container.deleted, [])


class ListCaseDocumentsTests(unittest.TestCase):
    def test_lists_only_eligible_files(self):
        config = SyncConfig()
        graph = FakeGraph(
            children_by_url={
                children_url(f"{CASE_ROOT}/7 Eleven/Case Documents"): [
                    file_item("Settlement Agreement.pdf", "i1"),
                    file_item("mail merge notices.pdf", "i2"),
                    file_item("calculations.xlsx", "i3"),
                    {"id": "f1", "name": "subfolder", "folder": {}},
                ]
            }
        )
        items = list_case_documents(graph, "drive-1", "7 Eleven", config)
        self.assertEqual([item["id"] for item in items], ["i1"])

    def test_missing_folder_returns_empty(self):
        config = SyncConfig()
        graph = FakeGraph()
        self.assertEqual(list_case_documents(graph, "drive-1", "No Folder Case", config), [])

    def test_non_404_listing_error_raises(self):
        config = SyncConfig()
        graph = FakeGraph(
            error_status_by_url={children_url(f"{CASE_ROOT}/Flaky Case/Case Documents"): 503}
        )
        with self.assertRaises(CaseDocumentsListingError):
            list_case_documents(graph, "drive-1", "Flaky Case", config)

    def test_nested_subfolder_logs_warning(self):
        config = SyncConfig()
        graph = FakeGraph(
            children_by_url={
                children_url(f"{CASE_ROOT}/7 Eleven/Case Documents"): [
                    file_item("Settlement Agreement.pdf", "i1"),
                    {"id": "f1", "name": "Old Drafts", "folder": {}},
                ]
            }
        )
        with self.assertLogs("case_documents_sync", level="WARNING") as logs:
            items = list_case_documents(graph, "drive-1", "7 Eleven", config)
        self.assertEqual([item["id"] for item in items], ["i1"])
        self.assertTrue(any("Old Drafts" in line for line in logs.output))


class DriveResolutionTests(unittest.TestCase):
    def test_matches_configured_drive_name(self):
        self.assertEqual(get_drive_id(FakeGraph(), "site-1", "Documents"), "drive-1")

    def test_raises_on_drive_name_mismatch_without_fallback(self):
        with self.assertRaises(RuntimeError):
            get_drive_id(FakeGraph(), "site-1", "Wrong Library")


class SyncTests(unittest.TestCase):
    def _graph(self, *, fail_download=False):
        return FakeGraph(
            children_by_url={
                children_url(CASE_ROOT): [
                    {"id": "case-1", "name": "7 Eleven", "folder": {}},
                    {"id": "case-2", "name": "No Docs Case", "folder": {}},
                ],
                children_url(f"{CASE_ROOT}/7 Eleven/Case Documents"): [
                    file_item("Class Notice.pdf", "i1"),
                    file_item("Settlement Agreement.docx", "i2", etag="e9"),
                ],
            },
            fail_download=fail_download,
        )

    def test_mirrors_all_eligible_files(self):
        container = FakeContainer()
        stats = sync_case_documents(
            graph=self._graph(),
            blob_service_client=FakeBlobService(container),
            config=SyncConfig(),
        )
        self.assertEqual(stats["cases_seen"], 2)
        self.assertEqual(stats["files_seen"], 2)
        self.assertEqual(stats["uploaded"], 2)
        self.assertEqual(stats["missing_case_documents"], 1)
        self.assertIn("7 Eleven/Class Notice.pdf", container.uploads)
        self.assertIn("7 Eleven/Settlement Agreement.docx", container.uploads)
        upload = container.uploads["7 Eleven/Class Notice.pdf"]
        self.assertEqual(upload["data"], b"%PDF case document")
        ledger_upload = container.uploads["_sync/case_documents_ledger.json"]
        ledger = json.loads(ledger_upload["data"].decode("utf-8"))
        self.assertIn("7 Eleven/Class Notice.pdf", ledger["files"])

    def test_skips_unchanged_files_via_ledger(self):
        item = file_item("Class Notice.pdf", "i1")
        ledger = {
            "version": 1,
            "files": {"7 Eleven/Class Notice.pdf": {"source": item_fingerprint(item)}},
        }
        graph = FakeGraph(
            children_by_url={
                children_url(CASE_ROOT): [{"id": "case-1", "name": "7 Eleven", "folder": {}}],
                children_url(f"{CASE_ROOT}/7 Eleven/Case Documents"): [item],
            }
        )
        container = FakeContainer(ledger=ledger)
        stats = sync_case_documents(
            graph=graph,
            blob_service_client=FakeBlobService(container),
            config=SyncConfig(),
        )
        self.assertEqual(stats["skipped"], 1)
        self.assertEqual(stats["uploaded"], 0)
        self.assertEqual(graph.downloaded, [])

    def test_download_failure_is_counted_and_not_ledgered(self):
        container = FakeContainer()
        stats = sync_case_documents(
            graph=self._graph(fail_download=True),
            blob_service_client=FakeBlobService(container),
            config=SyncConfig(),
        )
        self.assertEqual(stats["failed"], 2)
        self.assertEqual(stats["uploaded"], 0)
        ledger_upload = container.uploads["_sync/case_documents_ledger.json"]
        ledger = json.loads(ledger_upload["data"].decode("utf-8"))
        self.assertEqual(ledger["files"], {})

    def test_download_failure_skips_prune(self):
        container = FakeContainer(blobs=["7 Eleven/Previously Synced.pdf"])
        stats = sync_case_documents(
            graph=self._graph(fail_download=True),
            blob_service_client=FakeBlobService(container),
            config=SyncConfig(),
        )
        self.assertEqual(stats["failed"], 2)
        self.assertEqual(stats["prune_skipped"], 1)
        self.assertEqual(stats["stale_deleted"], 0)
        self.assertEqual(container.deleted, [])

    def test_listing_failure_skips_prune_and_keeps_blobs(self):
        graph = FakeGraph(
            children_by_url={
                children_url(CASE_ROOT): [
                    {"id": "case-1", "name": "7 Eleven", "folder": {}},
                    {"id": "case-2", "name": "Throttled Case", "folder": {}},
                ],
                children_url(f"{CASE_ROOT}/7 Eleven/Case Documents"): [
                    file_item("Class Notice.pdf", "i1"),
                ],
            },
            error_status_by_url={
                children_url(f"{CASE_ROOT}/Throttled Case/Case Documents"): 429
            },
        )
        container = FakeContainer(blobs=["Throttled Case/Settlement Agreement.pdf"])
        stats = sync_case_documents(
            graph=graph,
            blob_service_client=FakeBlobService(container),
            config=SyncConfig(),
        )
        self.assertEqual(stats["listing_failed"], 1)
        self.assertEqual(stats["missing_case_documents"], 0)
        self.assertEqual(stats["uploaded"], 1)
        self.assertEqual(stats["prune_skipped"], 1)
        self.assertEqual(stats["stale_deleted"], 0)
        self.assertEqual(container.deleted, [])
        self.assertIn("7 Eleven/Class Notice.pdf", container.uploads)

    def test_dry_run_does_not_write(self):
        container = FakeContainer()
        stats = sync_case_documents(
            graph=self._graph(),
            blob_service_client=FakeBlobService(container),
            config=SyncConfig(dry_run=True),
        )
        self.assertEqual(stats["uploaded"], 2)
        self.assertEqual(container.uploads, {})
        self.assertFalse(container.created)

    def test_default_container_is_portal_case_documents(self):
        container = FakeContainer()
        service = FakeBlobService(container)
        sync_case_documents(
            graph=self._graph(),
            blob_service_client=service,
            config=SyncConfig(),
        )
        self.assertEqual(service.requested_container, "portal-case-documents")


if __name__ == "__main__":
    unittest.main()
