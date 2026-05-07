import io
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from generic_notice_sync.sync import (
    SyncConfig,
    blob_metadata_value,
    build_destination_blob_name,
    build_notice_packet_path,
    item_fingerprint,
    normalize_drive_relative_path,
    should_upload,
    sync_generic_notices,
    _is_notice_packet_file,
    _select_best_notice_source,
)


class FakeGraph:
    def __init__(self, *, fail_download=False):
        self.downloaded = []
        self.fail_download = fail_download

    def download_file(self, drive_id, item_id, *, as_pdf=False):
        self.downloaded.append((drive_id, item_id, as_pdf))
        if self.fail_download:
            raise requests.HTTPError("bad conversion")
        return b"%PDF generic notice"


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
    def __init__(self, ledger=None):
        self.created = False
        self.uploads = {}
        self.ledger_blob = FakeBlob()
        if ledger is not None:
            self.ledger_blob.payload = json.dumps(ledger).encode("utf-8")

    def create_container(self, exist_ok=False):
        self.created = exist_ok

    def get_blob_client(self, name):
        self.requested_ledger_name = name
        return self.ledger_blob

    def upload_blob(self, name, data, overwrite=False, **kwargs):
        body = data.getvalue() if isinstance(data, io.BytesIO) else data
        self.uploads[name] = {"data": body, "overwrite": overwrite, "kwargs": kwargs}


class FakeBlobService:
    def __init__(self, container):
        self.container = container

    def get_container_client(self, container_name):
        self.container_name = container_name
        return self.container


class GenericNoticeSyncTests(unittest.TestCase):
    def test_path_normalization_accepts_shared_documents_root(self):
        self.assertEqual(
            normalize_drive_relative_path("/Shared Documents/Active Cases/Settlements"),
            "Active Cases/Settlements",
        )
        config = SyncConfig(case_root_path="/Shared Documents/Active Cases/Settlements")
        self.assertEqual(
            build_notice_packet_path("Acme Case", config),
            "Active Cases/Settlements/Acme Case/Print/Notice packet",
        )

    def test_destination_blob_name_is_generic_and_case_scoped(self):
        self.assertEqual(
            build_destination_blob_name("Acme Wage & Hour", "Notice Packet.pdf"),
            "generic-notices/acme-wage-hour/Notice Packet.pdf",
        )
        self.assertEqual(
            build_destination_blob_name("Acme Wage & Hour", "Notice Packet.docx"),
            "generic-notices/acme-wage-hour/Notice Packet.pdf",
        )

    def test_should_upload_compares_meaningful_source_fingerprint(self):
        item = {
            "id": "item-1",
            "eTag": "a",
            "cTag": "b",
            "size": 123,
            "lastModifiedDateTime": "2026-05-06T00:00:00Z",
            "file": {"hashes": {"sha1Hash": "abc"}},
        }
        self.assertTrue(should_upload(item, None))
        self.assertFalse(should_upload(item, {"source": item_fingerprint(item)}))
        changed = dict(item)
        changed["size"] = 456
        self.assertTrue(should_upload(changed, {"source": item_fingerprint(item)}))

    def test_select_best_notice_source_returns_one_non_mail_merge_notice(self):
        selected = _select_best_notice_source(
            [
                {"name": "Case - Class Notice Mail Merge.pdf"},
                {"name": "Case - Notice Packet - Copy.docx"},
                {"name": "Case - Notice Packet.docx"},
            ]
        )

        self.assertEqual(selected["name"], "Case - Notice Packet.docx")

    def test_blob_metadata_value_is_ascii_safe(self):
        self.assertEqual(blob_metadata_value("Mary’s Settlement – Final"), "Marys Settlement  Final")

    def test_notice_candidate_excludes_merge_and_ssn_artifacts(self):
        self.assertFalse(_is_notice_packet_file("Case - Class Notice Packet - Mail Merge.pdf"))
        self.assertFalse(_is_notice_packet_file("Case - Class Notice Packet (with SSN).pdf"))
        self.assertTrue(_is_notice_packet_file("Case - Class Notice Packet.pdf"))

    def test_sync_uploads_only_changed_generic_notice_pdf(self):
        from generic_notice_sync import sync as sync_module

        config = SyncConfig(destination_container="lucycmnotices")
        case = {"name": "Acme’s Case", "folder": {}}
        pdf = {
            "id": "pdf-1",
            "name": "Notice Packet.pdf",
            "eTag": "v1",
            "size": 10,
            "lastModifiedDateTime": "2026-05-06T00:00:00Z",
            "file": {"hashes": {"sha1Hash": "sha"}},
        }
        container = FakeContainer()
        graph = FakeGraph()

        with mock.patch.object(sync_module, "get_site_id", return_value="site"), mock.patch.object(
            sync_module, "get_drive_id", return_value="drive"
        ), mock.patch.object(
            sync_module, "list_case_folders", return_value=[case]
        ), mock.patch.object(
            sync_module, "list_notice_pdfs", return_value=[pdf]
        ), mock.patch.object(
            sync_module, "content_settings", side_effect=lambda value: {"content_type": value}
        ):
            stats = sync_generic_notices(
                graph=graph,
                blob_service_client=FakeBlobService(container),
                config=config,
            )

        self.assertEqual(stats["uploaded"], 1)
        upload = container.uploads["generic-notices/acme-s-case/Notice Packet.pdf"]
        self.assertEqual(upload["kwargs"]["metadata"]["case_name"], "Acmes Case")
        self.assertEqual(graph.downloaded, [("drive", "pdf-1", False)])

    def test_sync_continues_when_one_notice_cannot_be_downloaded(self):
        from generic_notice_sync import sync as sync_module

        config = SyncConfig(destination_container="lucycmnotices")
        case = {"name": "Broken Case", "folder": {}}
        pdf = {
            "id": "pdf-1",
            "name": "Notice Packet.docx",
            "eTag": "v1",
            "size": 10,
            "lastModifiedDateTime": "2026-05-06T00:00:00Z",
            "file": {"hashes": {"sha1Hash": "sha"}},
        }
        container = FakeContainer()
        graph = FakeGraph(fail_download=True)

        with mock.patch.object(sync_module, "get_site_id", return_value="site"), mock.patch.object(
            sync_module, "get_drive_id", return_value="drive"
        ), mock.patch.object(
            sync_module, "list_case_folders", return_value=[case]
        ), mock.patch.object(
            sync_module, "list_notice_pdfs", return_value=[pdf]
        ), mock.patch.object(
            sync_module, "content_settings", side_effect=lambda value: {"content_type": value}
        ):
            stats = sync_generic_notices(
                graph=graph,
                blob_service_client=FakeBlobService(container),
                config=config,
            )

        self.assertEqual(stats["failed"], 1)
        self.assertEqual(stats["uploaded"], 0)
        self.assertNotIn("generic-notices/broken-case/Notice Packet.pdf", container.uploads)


if __name__ == "__main__":
    unittest.main()
