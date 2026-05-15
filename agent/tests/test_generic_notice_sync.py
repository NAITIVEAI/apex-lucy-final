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
    list_notice_pdfs,
    normalize_drive_relative_path,
    should_upload,
    sync_generic_notices,
    _is_case_level_notice_source_file,
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
    def __init__(self, ledger=None, blobs=None):
        self.created = False
        self.uploads = {}
        self.deleted = []
        self.blobs = list(blobs or [])
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

    def list_blobs(self, name_starts_with=None):
        for name in self.blobs:
            if not name_starts_with or name.startswith(name_starts_with):
                yield {"name": name}

    def delete_blob(self, name):
        self.deleted.append(name)


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

    def test_destination_blob_name_is_flat_and_collision_resistant(self):
        pdf_blob = build_destination_blob_name("Acme Wage & Hour", "Notice Packet.pdf")
        docx_blob = build_destination_blob_name("Acme Wage & Hour", "Notice Packet.docx")

        self.assertRegex(
            pdf_blob,
            r"^generic-notices/acme-wage-hour--[0-9a-f]{8}--generic-notice\.pdf$",
        )
        self.assertEqual(pdf_blob, docx_blob)
        self.assertEqual(pdf_blob.count("/"), 1)
        self.assertNotIn("generic-notices/acme-wage-hour/", pdf_blob)

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

    def test_select_best_notice_source_prefers_template_over_member_named_sample(self):
        selected = _select_best_notice_source(
            [
                {"name": "Allergy - Notice - Anissa Coleman.pdf"},
                {"name": "Allergy - Notice v2.docx"},
            ]
        )

        self.assertEqual(selected["name"], "Allergy - Notice v2.docx")

    def test_blob_metadata_value_is_ascii_safe(self):
        self.assertEqual(blob_metadata_value("Mary’s Settlement – Final"), "Marys Settlement  Final")

    def test_notice_candidate_excludes_merge_and_ssn_artifacts(self):
        self.assertFalse(_is_notice_packet_file("Case - Class Notice Packet - Mail Merge.pdf"))
        self.assertFalse(_is_notice_packet_file("Case - Class Notice Packet (with SSN).pdf"))
        self.assertTrue(_is_notice_packet_file("Case - Class Notice Packet.pdf"))
        self.assertTrue(_is_notice_packet_file("Case - Notice v2.docx"))
        self.assertTrue(_is_notice_packet_file("Allergy - Notice v2.docx"))
        self.assertFalse(_is_notice_packet_file("Jonathan A Aguayo - Notice Packet.pdf"))
        self.assertFalse(_is_notice_packet_file("Case - Notice Packet - Anissa Coleman.pdf"))
        self.assertFalse(_is_case_level_notice_source_file("Case - Notice Packet - Jeremy Heriales.pdf"))
        self.assertFalse(_is_case_level_notice_source_file("Commercial Lighting - Notice - Trevor Lawson.pdf"))
        self.assertTrue(_is_case_level_notice_source_file("About Food - Notice of Pendency.docx"))
        self.assertTrue(_is_case_level_notice_source_file("American Pasteurization Company - Notice Packet.pdf"))

    def test_list_notice_pdfs_falls_back_to_one_level_mailing_folder(self):
        class Graph:
            def __init__(self):
                self.paths = []

            def get_all(self, url):
                from urllib.parse import unquote

                path = unquote(url.split("/root:", 1)[1].split(":/children", 1)[0]).strip("/")
                self.paths.append(path)
                if path.endswith("/Print/Notice packet"):
                    response = requests.Response()
                    response.status_code = 404
                    raise requests.HTTPError("missing", response=response)
                if path.endswith("/Print"):
                    return [
                        {"name": "Mail Merged", "folder": {}},
                        {"name": "Postal Sort", "folder": {}},
                        {"name": "2nd Mailing", "folder": {}},
                    ]
                if path.endswith("/Print/2nd Mailing"):
                    return [
                        {"name": "CTRE559.pdf", "file": {}, "id": "member-pdf"},
                        {"name": "Notice Packet to New CMS - pdf.pdf", "file": {}, "id": "notice-pdf"},
                        {"name": "Correction Notice Packet.docx", "file": {}, "id": "correction-docx"},
                    ]
                raise AssertionError(f"unexpected path: {path}")

        graph = Graph()
        selected = list_notice_pdfs(graph, "drive", "Creating a Legacy Inc", SyncConfig())

        self.assertEqual(selected[0]["id"], "notice-pdf")
        self.assertIn("Active Cases/Settlements/Creating a Legacy Inc/Print/2nd Mailing", graph.paths)
        self.assertNotIn("Active Cases/Settlements/Creating a Legacy Inc/Print/Mail Merged", graph.paths)

    def test_sync_uploads_only_changed_generic_notice_pdf(self):
        from generic_notice_sync import sync as sync_module

        config = SyncConfig(destination_container="lucycmnotices")
        case = {"id": "case-folder-1", "name": "Acme’s Case", "folder": {}}
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
        expected_blob = build_destination_blob_name("Acme’s Case", "Notice Packet.pdf", source_item_id="case-folder-1")
        upload = container.uploads[expected_blob]
        self.assertEqual(upload["kwargs"]["metadata"]["case_name"], "Acmes Case")
        self.assertEqual(upload["kwargs"]["metadata"]["case_slug"], "acme-s-case")
        self.assertRegex(upload["kwargs"]["metadata"]["case_key"], r"^[0-9a-f]{8}$")
        self.assertEqual(upload["kwargs"]["metadata"]["original_file_name"], "Notice Packet.pdf")
        self.assertEqual(upload["kwargs"]["metadata"]["source_file_name"], "Notice Packet.pdf")
        self.assertEqual(upload["kwargs"]["metadata"]["sharepoint_item_id"], "pdf-1")
        self.assertEqual(upload["kwargs"]["metadata"]["sharepoint_case_folder_id"], "case-folder-1")
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
        self.assertNotIn(
            build_destination_blob_name("Broken Case", "Notice Packet.docx", source_item_id="pdf-1"),
            container.uploads,
        )

    def test_sync_prunes_stale_generic_notice_projection_blobs_after_successful_walk(self):
        from generic_notice_sync import sync as sync_module

        config = SyncConfig(destination_container="lucycmnotices")
        case = {"id": "case-folder-1", "name": "Acme Case", "folder": {}}
        pdf = {
            "id": "pdf-1",
            "name": "Notice Packet.pdf",
            "eTag": "v1",
            "size": 10,
            "lastModifiedDateTime": "2026-05-06T00:00:00Z",
            "file": {"hashes": {"sha1Hash": "sha"}},
        }
        active_blob = build_destination_blob_name("Acme Case", "Notice Packet.pdf", source_item_id="case-folder-1")
        stale_blob = "generic-notices/old-case--12345678--generic-notice.pdf"
        nested_blob = "generic-notices/old-case/member-notice.pdf"
        noncanonical_flat_blob = "generic-notices/old-case--12345678--Old Notice.pdf"
        outside_prefix_blob = "member-notices/old-case--12345678--generic-notice.pdf"
        container = FakeContainer(
            ledger={
                "version": 1,
                "files": {
                    active_blob: {"source": item_fingerprint(pdf)},
                    stale_blob: {},
                    nested_blob: {},
                    noncanonical_flat_blob: {},
                },
            },
            blobs=[active_blob, stale_blob, nested_blob, noncanonical_flat_blob, outside_prefix_blob],
        )
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

        self.assertEqual(stats["skipped"], 1)
        self.assertEqual(stats["stale_deleted"], 3)
        self.assertEqual(container.deleted, [stale_blob, nested_blob, noncanonical_flat_blob])
        saved_ledger = json.loads(container.uploads[config.ledger_blob]["data"].decode("utf-8"))
        self.assertIn(active_blob, saved_ledger["files"])
        self.assertNotIn(stale_blob, saved_ledger["files"])
        self.assertNotIn(nested_blob, saved_ledger["files"])
        self.assertNotIn(noncanonical_flat_blob, saved_ledger["files"])


if __name__ == "__main__":
    unittest.main()
